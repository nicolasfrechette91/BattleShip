"""M9-g3: the training driver: g2's recorder and checkpoints on g3 keys and identities (the curriculum state carries the g3 line contract, the g3 frontier
rule and the spacing state), the callback with the attempt hook at the rollout boundary (g2's class, with the spacing state in every rollout row), and
`train`.

PPO is g2's, which is g1's: the M7n v3 profile with the entropy coefficient 0.01, a FRESH policy (seed 0) in s1 (`make_fresh_ppo` = rl/m9_train.make_ppo),
resumed in a later session (`resume_ppo` = rl/m9_g2_train.resume_ppo: PPO.load with the training vector, the continuity assertions, the training seed
1000 + k). Routes are start states only: there is no imitation, self-imitation or auxiliary loss anywhere in this module, and `train` never reads an action
of a lineage.

Reading (decisions record R-train): `rl/m9_g2_train.train` cannot take the g3 frontier unchanged because it calls g2's `run_attempt` and writes the g2 line
contract into every checkpoint; it is copied here with those references changed. The callback class is g2's, subclassed only to add the spacing state to
the per-rollout row; its STALLED branch can never fire (the g3 frontier is never stalled).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

import m9_artifacts as A
import m9_g2_arena as AR
import m9_g2_resume as RS
import m9_g2_train as TR2
import m9_g3_contract as G
import m9_g3_frontier as F
import m9_g3_probe as PR
import m9_sticky as S
import m9_train as T
import m9_vec as V

TRAIN_CONTRACT = "m9_g3_train_v1"
make_fresh_ppo = TR2.make_fresh_ppo
resume_ppo = TR2.resume_ppo
sha256_file = TR2.sha256_file


# -- start source --------------------------------------------------------------------------------------------------------------------


class TrainSource(TR2.TrainSource):
    """g2's training source (a start drawn when a slot becomes free) with the g3 label."""

    def next_job(self, arena: Any) -> Optional[V.StartJob]:
        if self._back:
            return self._back.pop()
        ep = self.counter
        self.counter += 1
        start = self.cur.draw(ep)
        return V.StartJob(ep, start, G.train_label(ep), driver="policy", kind="train", job_id=f"train-{ep:07d}")


# -- the recorder ---------------------------------------------------------------------------------------------------------------------


class G3TrainRecorder(TR2.G2TrainRecorder):
    """g2's recorder with the g3 artifact-sample key; the frontier's window events (trigger, deferred_trigger, void) go to windows.jsonl as in g2."""

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


# -- checkpoints ----------------------------------------------------------------------------------------------------------------------


def curriculum_state_record(frontier: F.Frontier, *, num_timesteps: int, tape_table_sha256: Optional[str], session: int, extra: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    rec = dict(frontier.state(), carried=frontier.carried_state(), num_timesteps=int(num_timesteps), session=int(session), line_contract_sha256=G.line_contract_digest(),
               frontier_rule=G.FRONTIER_RULE_ID, gate=G.GATE, line=G.LINE_ID, tape_table_sha256=tape_table_sha256, ppo=dict(G.PPO), sticky_p=G.STICKY_P, landings=list(frontier.landings))
    if extra:
        rec.update(extra)
    return rec


def save_checkpoint(model: Any, frontier: F.Frontier, run_dir: Path, n: int, why: str, *, session: int, tape_table_sha256: Optional[str], extra: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """checkpoints/ckpt_<t>/{model.zip, curriculum_state.json, checkpoint.json}: the digests of model.zip, of its policy and optimizer members and of the
    curriculum state are pinned in checkpoint.json (decision 12)."""
    d = Path(run_dir) / "checkpoints" / (f"ckpt_{n:09d}" if why != "final" else "final")
    d.mkdir(parents=True, exist_ok=False)
    model.save(str(d / "model.zip"))
    A.write_json(d / "curriculum_state.json", A.stamp(curriculum_state_record(frontier, num_timesteps=n, tape_table_sha256=tape_table_sha256, session=session)), overwrite=False)
    lc = G.line_contract_description()
    meta = {"checkpoint": d.name, "why": why, "num_timesteps": int(n), "session": int(session), "model_zip_sha256": sha256_file(d / "model.zip"), "model_zip_bytes": (d / "model.zip").stat().st_size,
            "members_sha256": RS.zip_member_digests(d / "model.zip"), "curriculum_state_sha256": sha256_file(d / "curriculum_state.json"), "pointer": frontier.pointer,
            "spacing": frontier.spacing_state(), "observation": lc["observation"], "action": lc["action"], "reward": lc["reward"],
            "ppo": dict(G.PPO), "gate": G.GATE, "scope": G.SCOPE, "line_contract_sha256": G.line_contract_digest(), "frontier_rule": G.FRONTIER_RULE_ID}
    if extra:
        meta.update(extra)
    A.write_json(d / "checkpoint.json", A.stamp(meta))
    return {k: meta[k] for k in ("checkpoint", "why", "num_timesteps", "model_zip_sha256", "model_zip_bytes", "members_sha256", "curriculum_state_sha256", "pointer", "spacing")}


# -- the callback -----------------------------------------------------------------------------------------------------------------------


def make_callback_class() -> Any:
    Base = TR2.make_callback_class()

    class G3Callback(Base):
        """g2's callback (checkpoints, the attempt hook at the rollout boundary, the caps); the per-rollout row adds the spacing state and the deferred triggers.

        Periodic checkpoints are aligned to the SESSION START (pre-launch hazard fix H2 of the s2 review, docs/rl_m9_g3_s2_prelaunch_review_2026-10-07.md):
        a resumed session whose saved count is not a multiple of the rollout (s1 ended mid-rollout at 708,712 = 138 x 5,120 + 2,152) would otherwise never
        reach a boundary with num_timesteps % 102,400 == 0 and would hold no periodic checkpoint at all. CHECKPOINT_EVERY (102,400) and the line contract
        are unchanged; only the alignment moves from 0 to the session's own start. In s1 (start 0) the two rules coincide."""

        def _on_rollout_start(self) -> None:
            n = int(self.model.num_timesteps)
            if n > self.start_timesteps and (n - self.start_timesteps) % self.every == 0:
                self._checkpoint(n)
            if self.fr.pending is not None and not self.fr.held() and not self.fr.stalled:      # g2's attempt hook, unchanged (g3 has no HELD and no STALLED: g2's STALLED stop is unreachable)
                t = self.now()
                rec = self.attempt(self.rec.episodes, n)
                self.pause_s += self.now() - t
                self.attempts.append({k: rec.get(k) for k in ("n", "a", "pointer", "result", "new_pointer", "wall_s", "snapshot")})
                if rec.get("result") == "MOVED":
                    A.append_jsonl(self.run_dir / "moves.jsonl", A.stamp({"t_wall_s": round(self.now() - self.t0, 2), "from": rec["pointer"], "to": rec["new_pointer"], "attempt": rec["n"],
                                                                         "a": rec["a"], "num_timesteps": n, "episodes": self.rec.episodes, "session": self.fr.session}))
            elif self.fr.pending is not None:
                self.fr.pending = None

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
                   "pointer": self.fr.pointer, "moves": len(self.fr.moves_all), "attempts": len(self.fr.attempts), "spacing": fs["spacing"], "deferred_triggers": fs["deferred_triggers"],
                   "window": fs["window"], "windows": fs["windows"], "episodes": self.rec.episodes, "clears": self.rec.clears, "stale_strip_outcomes": self.fr.stale, "counted_strip_outcomes": self.fr.counted,
                   "staged": sm["staged"], "wait_s": sm["wait_s"], "waits": sm["waits"], "withdrawn": sm.get("withdrawn", 0), "prefix_ticks": sm["prefix_ticks"], "policy_ticks": sm["policy_ticks"],
                   "probe_ticks": int(getattr(self.arena.budget, "probe", 0)), "pause_s": round(self.pause_s, 2), "lifecycle_failures": len(sm["lifecycle_failures"]),
                   "ep_return_mean_recent": round(sum(ep_r) / len(ep_r), 4) if ep_r else None,
                   "update_metrics_of_the_previous_rollout": {k.split("/")[-1]: float(v) for k, v in logged.items() if k.startswith("train/")}}
            A.append_jsonl(self.run_dir / "rollouts.jsonl", A.stamp(row))
            self.last_t, self.last_n = t, n

    return G3Callback


# -- train --------------------------------------------------------------------------------------------------------------------------------


def train(model: Any, env: Any, arena: AR.G2Arena, frontier: F.Frontier, recorder: G3TrainRecorder, *, run_dir: Path, guard: Callable[[], None], now: Callable[[], float], session: int,
          pool: Any, tables: Mapping[str, Any], lengths: Mapping[str, int], snapshot_of: Callable[[Any], Callable[[Path], Dict[str, Any]]], make_policy: Callable[[Path, str], Any],
          log: Callable[[str], None], transition_cap: int = G.TRANSITION_CAP, tape_table_sha256: Optional[str] = None, artifacts_root: Optional[Path] = None,
          flatten: Any = None, checkpoint_every: int = G.CHECKPOINT_EVERY, resumed: bool = False, extra_meta: Optional[Mapping[str, Any]] = None,
          expect_initial_members: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """Run `model.learn` under the registered caps with the replenishing controlled frontier. `valid_end` is True for the wall cap, the native-tick cap and
    the transition cap; False for any earlier stop. The final checkpoint (model, optimizer state, curriculum state) is always written. In a resumed session
    `expect_initial_members` names the predecessor's final policy and optimizer member digests: the initial checkpoint must carry them bit for bit (H12 of
    the s2 review), checked before the first rollout so that a wrong load costs nothing."""
    import m9_g2_policy as PO

    run_dir = Path(run_dir)
    Callback = make_callback_class()
    start_n = int(getattr(model, "num_timesteps", 0))
    flat = flatten if flatten is not None else PO.flatten_obs

    def save(m: Any, n: int, why: str) -> Dict[str, Any]:
        info = save_checkpoint(m, frontier, run_dir, n, why, session=session, tape_table_sha256=tape_table_sha256, extra=extra_meta)
        if why == "initial" and expect_initial_members is not None:
            got = dict(info.get("members_sha256") or {})
            want = dict(expect_initial_members)
            if got != want:
                raise V.IntegrityStop("the resumed model's initial checkpoint members differ from the predecessor's final members", {"got": got, "expected": want, "checkpoint": info.get("checkpoint")})
            stop["initial_members_equal_predecessor"] = True
        return info

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
                 "pointer_final": frontier.pointer, "spacing_final": frontier.spacing_state(), "deferred_triggers": frontier.deferred, "attempts_per_pointer": {str(k): v for k, v in sorted(frontier.line_failed.items())},
                 "resumed_seed": getattr(model, "resumed_seed", None), "initial_members_checked": expect_initial_members is not None})
    return stop


def contract_description() -> Dict[str, Any]:
    return {"contract": TRAIN_CONTRACT, "ppo": dict(G.PPO), "checkpoint_every": G.CHECKPOINT_EVERY, "n_steps": "5,120 / 4", "losses": "PPO only: no imitation, self-imitation or auxiliary loss; "
            "routes are start states only", "valid_ends": ["wall cap", "native-tick cap", "transition cap"], "attempt_hook": "on_rollout_start, after the previous update; refused inside the spacing",
            "checkpoint_alignment": "periodic checkpoints at start_timesteps + j x checkpoint_every, aligned to the session's own start (the s2 review's H2); the initial checkpoint at the start"}
