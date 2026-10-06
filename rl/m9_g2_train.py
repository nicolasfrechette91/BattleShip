"""M9-g2: the training driver: the g2 recorder (g1's on g2 keys, plus the frontier's windows), checkpoints with the curriculum state, the callback with
the attempt hook at the rollout boundary, and `train`.

PPO is g1's: the M7n v3 profile with the entropy coefficient 0.01, a FRESH policy (seed 0) in s1 (`make_fresh_ppo` = rl/m9_train.make_ppo), resumed in a
later session (`resume_ppo`: PPO.load with the training vector, the continuity assertions of rl/m9_g2_resume, the training seed 1000 + k). Routes are start
states only: there is no imitation, self-imitation or auxiliary loss anywhere in this module, and `train` never reads an action of a lineage.

The attempt hook: at `on_rollout_start` (SB3 calls it after the previous rollout's update) a pending trigger runs `rl/m9_g2_probe.run_attempt`; the four
playing slots stay parked; a STALLED frontier ends training as a registered valid end. `train(model, ...)` accepts any model with the SB3 interface: the
production run passes SB3's PPO, the tests pass rl/m9_g2_stub.G2StubModel through the SAME driver, callback and recorders.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

import m9_artifacts as A
import m9_g2_arena as AR
import m9_g2_contract as G
import m9_g2_frontier as F
import m9_g2_probe as PR
import m9_g2_resume as RS
import m9_sticky as S
import m9_train as T
import m9_vec as V

TRAIN_CONTRACT = "m9_g2_train_v1"


# -- start source -------------------------------------------------------------------------------------------------------------------


class TrainSource(T.TrainSource):
    """g1's training source (a start drawn when a slot becomes free) with the g2 label."""

    def next_job(self, arena: Any) -> Optional[V.StartJob]:
        if self._back:
            return self._back.pop()
        ep = self.counter
        self.counter += 1
        start = self.cur.draw(ep)
        return V.StartJob(ep, start, G.train_label(ep), driver="policy", kind="train", job_id=f"train-{ep:07d}")


# -- the recorder --------------------------------------------------------------------------------------------------------------------


class G2TrainRecorder(T.TrainRecorder):
    """g1's recorder with g2 keys (the artifact sample) and the frontier's window events instead of the blocks."""

    def __init__(self, run_dir: Path, frontier: F.Frontier, tables: Mapping[str, Any], *, session: int, first_clears: int = G.FIRST_CLEARS_VERIFIED,
                 now: Callable[[], float] = time.monotonic, write_artifacts: bool = True):
        super().__init__(run_dir, frontier, tables, first_clears=first_clears, now=now, write_artifacts=write_artifacts)
        self.frontier = frontier
        self.session = int(session)
        self.events: Dict[str, int] = {}

    def on_episode(self, ctx: V.EpisodeCtx, rec: Dict[str, Any]) -> None:
        self.episodes += 1
        self.clears += int(rec["clear"])
        self.ends[rec["end_reason"]] = self.ends.get(rec["end_reason"], 0) + 1
        st = ctx.job.start
        words = self.tables[ctx.lineage].words
        hold = T.mid_hold(words, ctx.tau)
        row = dict(rec, t_wall_s=round(self.now() - self.t0, 2), mid_hold=hold, pointer_now=self.cur.pointer, session=self.session)
        A.append_jsonl(self.dir / "episodes.jsonl", A.stamp(row))
        reg = self.clear_by_region.setdefault(st.region, [0, 0])
        reg[0] += 1
        reg[1] += int(rec["clear"])
        self.recent_returns.append(rec["return"])
        if len(self.recent_returns) > 200:
            self.recent_returns.pop(0)
        if rec["clear"] and len(self.first_clears) < self.first_clears_cap:
            self.first_clears.append({"episode": rec["episode"], "online": ctx.online(ctx.final), "words": ctx.words(), "tau": ctx.tau, "ticks": rec["ticks"]})
        if self.write_artifacts and (rec["clear"] or int(S.uniform(G.artifact_sample_key(ctx.job.episode)) * 1000) < G.ARTIFACT_SAMPLE_PER_MILLE):
            self._artifact(ctx, rec)

    def on_outcome(self, ctx: V.EpisodeCtx, cleared: bool) -> None:
        st = ctx.job.start
        before = self.cur.pointer
        hold = T.mid_hold(self.tables[ctx.lineage].words, ctx.tau)
        counted = st.region == "strip" and st.pointer == before
        ev = self.frontier.record(st, cleared)
        if counted and hold is not None:
            d = self.by_pointer.setdefault(before, {"mid_hold": [0, 0], "at_change": [0, 0]})
            cell = d["mid_hold" if hold else "at_change"]
            cell[0] += 1
            cell[1] += int(cleared)
        if not counted and st.region == "strip":
            A.append_jsonl(self.dir / "stale.jsonl", A.stamp({"episode": ctx.job.job_id, "start_pointer": st.pointer, "pointer_now": before, "tau": st.tau, "clear": bool(cleared),
                                                             "t_wall_s": round(self.now() - self.t0, 2)}))
        if ev is not None and ev.get("event") != "after_trigger":
            self.events[ev["event"]] = self.events.get(ev["event"], 0) + 1
            A.append_jsonl(self.dir / "windows.jsonl", A.stamp(dict(ev, t_wall_s=round(self.now() - self.t0, 2), episodes=self.episodes, session=self.session)))

    def summary(self) -> Dict[str, Any]:
        s = super().summary()
        s["window_events"] = dict(self.events)
        return s


# -- checkpoints ---------------------------------------------------------------------------------------------------------------------


def sha256_file(p: Path) -> str:
    return RS.sha256_file(Path(p))


def curriculum_state_record(frontier: F.Frontier, *, num_timesteps: int, tape_table_sha256: Optional[str], session: int, extra: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    rec = dict(frontier.state(), carried=frontier.carried_state(), num_timesteps=int(num_timesteps), session=int(session), line_contract_sha256=G.line_contract_digest(),
               frontier_rule=G.FRONTIER_RULE_ID, tape_table_sha256=tape_table_sha256, ppo=dict(G.PPO), sticky_p=G.STICKY_P, landings=list(frontier.landings))
    if extra:
        rec.update(extra)
    return rec


def save_checkpoint(model: Any, frontier: F.Frontier, run_dir: Path, n: int, why: str, *, session: int, tape_table_sha256: Optional[str], extra: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """checkpoints/ckpt_<t>/{model.zip, curriculum_state.json, checkpoint.json}: the digests of model.zip, of its policy and optimizer members and of the
    curriculum state are pinned in checkpoint.json (decision 11, R7)."""
    d = Path(run_dir) / "checkpoints" / (f"ckpt_{n:09d}" if why != "final" else "final")
    d.mkdir(parents=True, exist_ok=False)
    model.save(str(d / "model.zip"))
    A.write_json(d / "curriculum_state.json", A.stamp(curriculum_state_record(frontier, num_timesteps=n, tape_table_sha256=tape_table_sha256, session=session)), overwrite=False)
    meta = {"checkpoint": d.name, "why": why, "num_timesteps": int(n), "session": int(session), "model_zip_sha256": sha256_file(d / "model.zip"), "model_zip_bytes": (d / "model.zip").stat().st_size,
            "members_sha256": RS.zip_member_digests(d / "model.zip"), "curriculum_state_sha256": sha256_file(d / "curriculum_state.json"), "pointer": frontier.pointer,
            "observation": G.line_contract_description()["observation"], "action": G.line_contract_description()["action"], "reward": G.line_contract_description()["reward"],
            "ppo": dict(G.PPO), "gate": G.GATE, "scope": G.SCOPE, "line_contract_sha256": G.line_contract_digest()}
    if extra:
        meta.update(extra)
    A.write_json(d / "checkpoint.json", A.stamp(meta))
    return {k: meta[k] for k in ("checkpoint", "why", "num_timesteps", "model_zip_sha256", "model_zip_bytes", "members_sha256", "curriculum_state_sha256", "pointer")}


# -- the model -----------------------------------------------------------------------------------------------------------------------


def make_fresh_ppo(env: Any, n_envs: int) -> Any:
    """g1's fresh PPO (rl/m9_train.make_ppo): the v3 network, seed 0, one torch thread, CPU, ent_coef 0.01."""
    return T.make_ppo(env, n_envs)


def resume_ppo(model_zip: Path, env: Any, n_envs: int, session: int) -> Any:
    """A later session's model: PPO.load with the training vector (the policy and the optimizer state restored), the continuity assertions, the seed 1000 + k."""
    import torch
    from stable_baselines3 import PPO

    import m7n_policy as pol

    torch.set_num_threads(int(G.PPO["torch_threads"]))
    pol.assert_v3_checkpoint(Path(model_zip))
    saved = RS.saved_counters(Path(model_zip))
    model = PPO.load(str(model_zip), env=env, device="cpu")
    if int(model.n_steps) * int(n_envs) != G.ROLLOUT_SIZE:
        raise RS.ResumeError(f"the loaded n_steps {model.n_steps} x {n_envs} envs is not the rollout {G.ROLLOUT_SIZE}")
    RS.assert_continuity(model, saved)
    model.set_random_seed(G.SESSION_SEED_BASE + int(session))
    model.resumed_seed = G.SESSION_SEED_BASE + int(session)          # recorded by the caller
    return model


# -- the callback ----------------------------------------------------------------------------------------------------------------------


def make_callback_class() -> Any:
    from stable_baselines3.common.callbacks import BaseCallback

    class G2Callback(BaseCallback):
        def __init__(self, *, run_dir: Path, env: Any, arena: AR.G2Arena, frontier: F.Frontier, recorder: G2TrainRecorder, guard: Callable[[], None], transition_cap: int,
                     now: Callable[[], float], save: Callable[[Any, int, str], Dict[str, Any]], attempt: Callable[[int, int], Dict[str, Any]], checkpoint_every: int = G.CHECKPOINT_EVERY,
                     start_timesteps: int = 0):
            super().__init__(verbose=0)
            self.run_dir, self.env, self.arena, self.fr, self.rec = Path(run_dir), env, arena, frontier, recorder
            self.guard, self.transition_cap, self.now, self.save, self.attempt, self.every = guard, int(transition_cap), now, save, attempt, int(checkpoint_every)
            self.start_timesteps = int(start_timesteps)
            self.t0 = now()
            self.rollout = 0
            self.saved: Dict[int, Dict[str, Any]] = {}
            self.checkpoints: List[Dict[str, Any]] = []
            self.attempts: List[Dict[str, Any]] = []
            self.stop_reason: Optional[str] = None
            self.last_t = self.t0
            self.last_n = self.start_timesteps
            self.pause_s = 0.0

        def _on_training_start(self) -> None:
            self._checkpoint(int(self.model.num_timesteps))

        def _checkpoint(self, n: int) -> None:
            if n in self.saved:
                return
            info = self.save(self.model, n, "initial" if n == self.start_timesteps else "periodic")
            info["wall_s"] = round(self.now() - self.t0, 2)
            self.saved[n] = info
            self.checkpoints.append(info)

        def _on_rollout_start(self) -> None:
            n = int(self.model.num_timesteps)
            if n > self.start_timesteps and n % self.every == 0:
                self._checkpoint(n)
            if self.fr.pending is not None and not self.fr.held() and not self.fr.stalled:
                t = self.now()
                rec = self.attempt(self.rec.episodes, n)
                self.pause_s += self.now() - t
                self.attempts.append({k: rec.get(k) for k in ("n", "a", "pointer", "result", "new_pointer", "wall_s", "snapshot")})
                if rec.get("result") == "MOVED":
                    A.append_jsonl(self.run_dir / "moves.jsonl", A.stamp({"t_wall_s": round(self.now() - self.t0, 2), "from": rec["pointer"], "to": rec["new_pointer"], "attempt": rec["n"],
                                                                         "a": rec["a"], "num_timesteps": n, "episodes": self.rec.episodes, "session": self.fr.session}))
                if self.fr.stalled:
                    raise V.CapStop(f"stalled: pointer {self.fr.stalled_pointer} has {G.ATTEMPTS_PER_LINE} failed attempts over the line", valid=True)
            elif self.fr.pending is not None:
                self.fr.pending = None                   # a trigger that cannot run (HELD): the window was already logged as held_trigger by the frontier

        def _on_step(self) -> bool:
            self.guard()
            if int(self.model.num_timesteps) - self.start_timesteps > self.transition_cap:
                self.stop_reason = "transition_cap"
                return False
            return True

        def _on_rollout_end(self) -> None:
            self.rollout += 1
            n = int(self.model.num_timesteps)
            t = self.now()
            logged = dict(getattr(getattr(self.model, "logger", None), "name_to_value", {}) or {})
            buf = getattr(self.model, "ep_info_buffer", None) or []
            ep_r = [float(e["r"]) for e in buf] if buf else []
            sm = self.arena.summary()
            fs = self.fr.state()
            row = {"rollout": self.rollout, "num_timesteps": n, "wall_s": round(t - self.t0, 2), "interval_transitions_per_s": round((n - self.last_n) / max(1e-9, t - self.last_t), 2),
                   "pointer": self.fr.pointer, "moves": len(self.fr.moves_all), "attempts": len(self.fr.attempts), "held": self.fr.held(), "stalled": self.fr.stalled,
                   "window": fs["window"], "windows": fs["windows"], "episodes": self.rec.episodes, "clears": self.rec.clears, "stale_strip_outcomes": self.fr.stale, "counted_strip_outcomes": self.fr.counted,
                   "staged": sm["staged"], "wait_s": sm["wait_s"], "waits": sm["waits"], "withdrawn": sm.get("withdrawn", 0), "prefix_ticks": sm["prefix_ticks"], "policy_ticks": sm["policy_ticks"],
                   "probe_ticks": int(getattr(self.arena.budget, "probe", 0)), "pause_s": round(self.pause_s, 2), "lifecycle_failures": len(sm["lifecycle_failures"]),
                   "ep_return_mean_recent": round(sum(ep_r) / len(ep_r), 4) if ep_r else None,
                   "update_metrics_of_the_previous_rollout": {k.split("/")[-1]: float(v) for k, v in logged.items() if k.startswith("train/")}}
            A.append_jsonl(self.run_dir / "rollouts.jsonl", A.stamp(row))
            self.last_t, self.last_n = t, n

    return G2Callback


# -- train ------------------------------------------------------------------------------------------------------------------------------


def train(model: Any, env: Any, arena: AR.G2Arena, frontier: F.Frontier, recorder: G2TrainRecorder, *, run_dir: Path, guard: Callable[[], None], now: Callable[[], float], session: int,
          pool: Any, tables: Mapping[str, Any], lengths: Mapping[str, int], snapshot_of: Callable[[Any], Callable[[Path], Dict[str, Any]]], make_policy: Callable[[Path, str], Any],
          log: Callable[[str], None], transition_cap: int = G.TRANSITION_CAP, tape_table_sha256: Optional[str] = None, artifacts_root: Optional[Path] = None,
          flatten: Any = None, checkpoint_every: int = G.CHECKPOINT_EVERY, resumed: bool = False, extra_meta: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Run `model.learn` under the registered caps with the controlled frontier. `valid_end` is True for the wall cap, the native-tick cap, the transition cap
    and STALLED; False for any earlier stop. The final checkpoint (model, optimizer state, curriculum state) is always written."""
    import m9_g2_policy as PO

    run_dir = Path(run_dir)
    Callback = make_callback_class()
    start_n = int(getattr(model, "num_timesteps", 0))
    flat = flatten if flatten is not None else PO.flatten_obs

    def save(m: Any, n: int, why: str) -> Dict[str, Any]:
        return save_checkpoint(m, frontier, run_dir, n, why, session=session, tape_table_sha256=tape_table_sha256, extra=extra_meta)

    def attempt(episodes_before: int, num_timesteps: int) -> Dict[str, Any]:
        return PR.run_attempt(frontier=frontier, train_arena=arena, pool=pool, tables=tables, train_budget=arena.budget, lengths=lengths, snapshot=snapshot_of(model), make_policy=make_policy,
                              attempt_root=run_dir / "attempts", probes_jsonl=run_dir / "probes.jsonl", attempts_jsonl=run_dir / "attempts.jsonl", withdrawn_jsonl=run_dir / "withdrawn.jsonl",
                              now=now, guard=guard, log=log, episodes_before=episodes_before, num_timesteps=num_timesteps, artifacts_root=artifacts_root, flatten=flat)

    cb = Callback(run_dir=run_dir, env=env, arena=arena, frontier=frontier, recorder=recorder, guard=guard, transition_cap=transition_cap, now=now, save=save, attempt=attempt,
                  checkpoint_every=checkpoint_every, start_timesteps=start_n)
    stop: Dict[str, Any] = {"reason": None, "valid_end": False, "error": None}
    t0 = now()
    try:
        kwargs: Dict[str, Any] = {"callback": cb}
        try:
            import inspect

            params = inspect.signature(model.learn).parameters
            if "log_interval" in params:
                kwargs["log_interval"] = None
            if "reset_num_timesteps" in params:
                kwargs["reset_num_timesteps"] = not resumed
        except (TypeError, ValueError):
            pass
        model.learn(total_timesteps=int(transition_cap), **kwargs)
        stop["reason"] = cb.stop_reason or "transition_cap"
        stop["valid_end"] = True
    except V.CapStop as exc:
        stop.update({"reason": exc.reason, "valid_end": exc.valid})
    except V.IntegrityStop as exc:
        stop.update({"reason": f"INTEGRITY: {exc.why}", "valid_end": False, "integrity": True, "detail": exc.detail})
    finally:
        try:
            if stop["reason"] is None:
                stop["reason"] = "error"
            n = int(getattr(model, "num_timesteps", 0))
            final = save_checkpoint(model, frontier, run_dir, n, "final", session=session, tape_table_sha256=tape_table_sha256, extra=extra_meta)
        except Exception as exc:                                 # noqa: BLE001 - recorded
            final = {"error": f"{type(exc).__name__}: {exc}"}
    stop.update({"num_timesteps": int(getattr(model, "num_timesteps", 0)), "start_timesteps": start_n, "session_transitions": int(getattr(model, "num_timesteps", 0)) - start_n,
                 "wall_s": round(now() - t0, 2), "rollouts": cb.rollout, "checkpoints": cb.checkpoints, "attempts": cb.attempts, "pause_s": round(cb.pause_s, 2), "final": final,
                 "transitions": int(getattr(env, "transitions", 0)),
                 "ticks": {"prefix": arena.budget.prefix, "policy": arena.budget.policy, "probe": int(getattr(arena.budget, "probe", 0)), "total": arena.budget.consumed, "cap": arena.budget.cap},
                 "stalled": frontier.stalled, "stalled_pointer": frontier.stalled_pointer, "pointer_final": frontier.pointer, "resumed_seed": getattr(model, "resumed_seed", None)})
    return stop


def contract_description() -> Dict[str, Any]:
    return {"contract": TRAIN_CONTRACT, "ppo": dict(G.PPO), "checkpoint_every": G.CHECKPOINT_EVERY, "n_steps": "5,120 / 4", "losses": "PPO only: no imitation, self-imitation or auxiliary loss; "
            "routes are start states only", "valid_ends": ["wall cap", "native-tick cap", "transition cap", "stalled"], "attempt_hook": "on_rollout_start, after the previous update"}
