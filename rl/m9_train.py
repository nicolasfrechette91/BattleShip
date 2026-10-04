"""M9-g1: the training driver: start sources, the episode recorder, the PPO callback (caps, checkpoints, per-rollout metrics) and `train`.

PPO is the M7n v3 profile (SB3 MultiInputPolicy [64, 64] tanh, lr 3e-4, rollout 5,120, batch 512, 10 epochs, gamma 0.999, lambda 0.995, clip 0.2,
vf 0.5, grad norm 0.5, one torch thread, CPU, no observation or reward normalisation, base seed 0) with a FRESH policy and ONE change, the
entropy coefficient 0.01 from the start (decision 6; a standard value, never tuned). The vector width is the playing slots of the process split
(4, or 2 with n_steps doubled so that the rollout stays 5,120). Routes are used as start states only: there is no imitation, self-imitation or
auxiliary loss anywhere in this module, and `train` never reads an action of a lineage.

`train(model, ...)` accepts any model with the SB3 interface (`learn`, `predict`, `save`): the production run passes SB3's PPO, the tests pass
m9_stub.StubModel through the SAME driver, callbacks and recorders.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import m9_artifacts as A
import m9_contract as C
import m9_curriculum as CU
import m9_sticky as S
import m9_vec as V

TRAIN_CONTRACT = "m9_train_v1"


# -- start sources -------------------------------------------------------------------------------------------------------------------


class TrainSource:
    """Starts of the training phase: each is drawn from the curriculum when a slot becomes free (as late as possible), keyed by its episode number."""

    def __init__(self, curriculum: CU.Curriculum, first_episode: int = 0):
        self.cur = curriculum
        self.counter = int(first_episode)
        self._back: List[V.StartJob] = []

    def next_job(self, arena: Any) -> Optional[V.StartJob]:
        if self._back:
            return self._back.pop()
        ep = self.counter
        self.counter += 1
        start = self.cur.draw(ep)
        return V.StartJob(ep, start, S.train_label(ep), driver="policy", kind="train", job_id=f"train-{ep:07d}")

    def unget(self, job: V.StartJob) -> None:
        self._back.append(job)


class WindowSource:
    """Random starts in a fixed tau window (P3, the split measurement): keyed draws, no pointer, a random policy."""

    def __init__(self, tag: str, lo: int, hi: int, lineage: str = C.TAPE_LINEAGE):
        self.tag, self.lo, self.hi, self.lineage = tag, int(lo), int(hi), lineage
        self.counter = 0
        self._back: List[V.StartJob] = []

    def next_job(self, arena: Any) -> Optional[V.StartJob]:
        if self._back:
            return self._back.pop()
        ep = self.counter
        self.counter += 1
        u = S.uniform(f"m9|g1|p3|{self.tag}|{ep}|tau")
        tau = self.lo + min(self.hi - self.lo, int(u * (self.hi - self.lo + 1)))
        start = CU.Start(ep, "window", tau, self.lineage, tau <= C.SHARED_PREFIX, -1)
        return V.StartJob(ep, start, f"p3:{self.tag}:{ep}", driver="random", kind=f"p3_{self.tag}", job_id=f"p3-{self.tag}-{ep:05d}")

    def unget(self, job: V.StartJob) -> None:
        self._back.append(job)


class ListSource:
    """A fixed list of jobs in priority order (the evaluation, P2, P4). A job whose staging died (a lifecycle failure) is put back and staged again with the
    SAME id and label (so its sticky draws are identical): a fixed list must be completed, unlike the training source, which simply draws a fresh start."""

    requeue_on_lifecycle = True

    def __init__(self, jobs: Sequence[V.StartJob]):
        self.jobs = list(jobs)
        self.i = 0
        self._back: List[V.StartJob] = []

    def next_job(self, arena: Any) -> Optional[V.StartJob]:
        if self._back:
            return self._back.pop()
        if self.i >= len(self.jobs):
            return None
        j = self.jobs[self.i]
        self.i += 1
        return j

    def unget(self, job: V.StartJob) -> None:
        self._back.append(job)

    def remaining(self) -> int:
        return len(self.jobs) - self.i + len(self._back)


# -- the recorder -------------------------------------------------------------------------------------------------------------------


def mid_hold(words: bytes, tau: int) -> Optional[bool]:
    """The handover diagnostic's class of a start: True when the prefix's last word continues a hold (words[tau-1] == words[tau-2])."""
    if tau < 2:
        return None
    return bool(words[tau - 1] == words[tau - 2])


class TrainRecorder:
    """Per-episode records of the training phase: the compact canonical record, the pointer and block logs, the keyed 2 % artifact sample, the first
    20 clears (verification), the handover diagnostic. Every write goes through the metadata-enforcing writers."""

    def __init__(self, run_dir: Path, curriculum: CU.Curriculum, tables: Mapping[str, Any], *, first_clears: int = 20, now: Callable[[], float] = time.monotonic,
                 write_artifacts: bool = True):
        self.dir = Path(run_dir)
        self.cur = curriculum
        self.tables = tables
        self.first_clears_cap = first_clears
        self.now = now
        self.t0 = now()
        self.write_artifacts = write_artifacts
        self.episodes = 0
        self.clears = 0
        self.first_clears: List[Dict[str, Any]] = []
        self.recent_returns: List[float] = []
        self.by_pointer: Dict[int, Dict[str, List[int]]] = {}
        self.clear_by_region: Dict[str, List[int]] = {}
        self.artifacts_written = 0
        self.ends: Dict[str, int] = {}

    def on_episode(self, ctx: V.EpisodeCtx, rec: Dict[str, Any]) -> None:
        self.episodes += 1
        self.clears += int(rec["clear"])
        self.ends[rec["end_reason"]] = self.ends.get(rec["end_reason"], 0) + 1
        st = ctx.job.start
        words = self.tables[ctx.lineage].words
        hold = mid_hold(words, ctx.tau)
        row = dict(rec, t_wall_s=round(self.now() - self.t0, 2), mid_hold=hold, pointer_now=self.cur.pointer)
        A.append_jsonl(self.dir / "episodes.jsonl", A.stamp(row))
        reg = self.clear_by_region.setdefault(st.region, [0, 0])
        reg[0] += 1
        reg[1] += int(rec["clear"])
        self.recent_returns.append(rec["return"])
        if len(self.recent_returns) > 200:
            self.recent_returns.pop(0)
        if rec["clear"] and len(self.first_clears) < self.first_clears_cap:
            self.first_clears.append({"episode": rec["episode"], "online": ctx.online(ctx.final), "words": ctx.words(), "tau": ctx.tau, "ticks": rec["ticks"]})
        if self.write_artifacts and (rec["clear"] or int(S.uniform(f"m9|g1|artifact|{ctx.job.episode}") * 1000) < C.ARTIFACT_SAMPLE_PER_MILLE):
            self._artifact(ctx, rec)

    def on_outcome(self, ctx: V.EpisodeCtx, cleared: bool) -> None:
        """The curriculum's record of a finished episode (a native end or the horizon): blocks, moves and stale accounting."""
        st = ctx.job.start
        before = self.cur.pointer
        hold = mid_hold(self.tables[ctx.lineage].words, ctx.tau)
        counted = st.region == "strip" and st.pointer == before
        blk = self.cur.record(st, cleared)
        if counted and hold is not None:
            d = self.by_pointer.setdefault(before, {"mid_hold": [0, 0], "at_change": [0, 0]})
            cell = d["mid_hold" if hold else "at_change"]
            cell[0] += 1
            cell[1] += int(cleared)
        if not counted and st.region == "strip":
            A.append_jsonl(self.dir / "stale.jsonl", A.stamp({"episode": ctx.job.job_id, "start_pointer": st.pointer, "pointer_now": before, "tau": st.tau, "clear": bool(cleared),
                                                             "t_wall_s": round(self.now() - self.t0, 2)}))
        if blk is not None:
            A.append_jsonl(self.dir / "blocks.jsonl", A.stamp(dict(blk, t_wall_s=round(self.now() - self.t0, 2), episodes=self.episodes)))
            if blk["moved"]:
                A.append_jsonl(self.dir / "pointer.jsonl", A.stamp({"t_wall_s": round(self.now() - self.t0, 2), "from": blk["pointer"], "to": blk["new_pointer"],
                                                                   "block": blk["block"], "clears": blk["clears"], "episodes": self.episodes}))

    def _artifact(self, ctx: V.EpisodeCtx, rec: Dict[str, Any]) -> None:
        words = ctx.words()
        rows = [(*__import__("m8_rd_cells").TRIPLES[w], i) for i, w in enumerate(words)]
        A.write_episode_artifact(self.dir.parent / "artifacts", rec["episode"], rows, {"lineage": ctx.lineage, "tau": ctx.tau, "start": rec["start"], "label": rec["label"],
                                                                                    "sticky_mask_hex": rec["sticky_mask_hex"], "sampled_hex": rec["sampled_hex"],
                                                                                    "native_action_digest": rec["native_action_digest"], "chain_final": rec["chain_final"],
                                                                                    "prefix_sha256": rec["prefix_sha256"]},
                                 status="clear" if rec["clear"] else rec["end_reason"], terminal={"end_reason": rec["end_reason"], "ticks": rec["ticks"], "targets_broken": rec["t"],
                                                                                                 "completion": (rec.get("result") or {})},
                                 labels={"phase": "train", "m9_kind": rec["kind"]}, preservation_reason="manual")
        self.artifacts_written += 1

    def summary(self) -> Dict[str, Any]:
        return {"episodes": self.episodes, "clears": self.clears, "ends": dict(self.ends), "clear_by_region": {k: list(v) for k, v in self.clear_by_region.items()},
                "handover_diagnostic": {str(p): {k: list(v) for k, v in d.items()} for p, d in sorted(self.by_pointer.items(), reverse=True)},
                "artifacts_written": self.artifacts_written, "first_clears_kept": len(self.first_clears)}


# -- the callback ---------------------------------------------------------------------------------------------------------------------


def make_callback_class() -> Any:
    from stable_baselines3.common.callbacks import BaseCallback

    class M9Callback(BaseCallback):
        """Caps, checkpoints every 102,400 transitions (written at the next rollout start, after the update) and one metrics row per rollout."""

        def __init__(self, *, run_dir: Path, env: Any, arena: V.Arena, curriculum: CU.Curriculum, recorder: TrainRecorder, guard: Callable[[], None],
                     transition_cap: int, now: Callable[[], float], save: Callable[[Any, int, str], Dict[str, Any]], checkpoint_every: int = C.CHECKPOINT_EVERY):
            super().__init__(verbose=0)
            self.run_dir, self.env, self.arena, self.cur, self.rec = Path(run_dir), env, arena, curriculum, recorder
            self.guard, self.transition_cap, self.now, self.save, self.every = guard, int(transition_cap), now, save, int(checkpoint_every)
            self.t0 = now()
            self.rollout = 0
            self.saved: Dict[int, Dict[str, Any]] = {}
            self.checkpoints: List[Dict[str, Any]] = []
            self.stop_reason: Optional[str] = None
            self.last_t = self.t0
            self.last_n = 0

        def _on_training_start(self) -> None:
            self._checkpoint(0)

        def _checkpoint(self, n: int) -> None:
            if n in self.saved:
                return
            info = self.save(self.model, n, "initial" if n == 0 else "periodic")
            info["wall_s"] = round(self.now() - self.t0, 2)
            self.saved[n] = info
            self.checkpoints.append(info)

        def _on_rollout_start(self) -> None:
            n = int(self.model.num_timesteps)
            if n > 0 and n % self.every == 0:
                self._checkpoint(n)

        def _on_step(self) -> bool:
            self.guard()
            # The transition cap (3,072,000 = exactly 600 rollouts of 5,120) ends `learn` itself at a rollout boundary, AFTER the last update: stopping inside
            # the last rollout would discard its update. Only a count beyond the cap (not reachable with a cap that is a multiple of the rollout) stops here.
            if int(self.model.num_timesteps) > self.transition_cap:
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
            row = {"rollout": self.rollout, "num_timesteps": n, "wall_s": round(t - self.t0, 2), "interval_transitions_per_s": round((n - self.last_n) / max(1e-9, t - self.last_t), 2),
                   "pointer": self.cur.pointer, "moves": len(self.cur.moves), "blocks": len(self.cur.blocks), "episodes": self.rec.episodes, "clears": self.rec.clears,
                   "stale_strip_outcomes": self.cur.stale, "counted_strip_outcomes": self.cur.counted, "staged": sm["staged"], "wait_s": sm["wait_s"], "waits": sm["waits"],
                   "prefix_ticks": sm["prefix_ticks"], "policy_ticks": sm["policy_ticks"], "lifecycle_failures": len(sm["lifecycle_failures"]),
                   "ep_return_mean_recent": round(sum(ep_r) / len(ep_r), 4) if ep_r else None,
                   "update_metrics_of_the_previous_rollout": {k.split("/")[-1]: float(v) for k, v in logged.items() if k.startswith("train/")}}
            A.append_jsonl(self.run_dir / "rollouts.jsonl", A.stamp(row))
            self.last_t, self.last_n = t, n

    return M9Callback


# -- the model ------------------------------------------------------------------------------------------------------------------------


def ppo_kwargs(n_envs: int) -> Dict[str, Any]:
    if C.ROLLOUT_SIZE % n_envs:
        raise ValueError(f"rollout {C.ROLLOUT_SIZE} is not divisible by {n_envs} envs")
    p = C.PPO
    return {"learning_rate": p["learning_rate"], "n_steps": C.ROLLOUT_SIZE // n_envs, "batch_size": p["batch_size"], "n_epochs": p["n_epochs"], "gamma": p["gamma"],
            "gae_lambda": p["gae_lambda"], "clip_range": p["clip_range"], "ent_coef": p["ent_coef"], "vf_coef": p["vf_coef"], "max_grad_norm": p["max_grad_norm"]}


def make_ppo(env: Any, n_envs: int) -> Any:
    """A freshly initialised SB3 PPO on the v3 network (rl/m7n_policy.make_model), seed 0, one torch thread, CPU."""
    import torch

    import m7n_policy as pol

    torch.set_num_threads(int(C.PPO["torch_threads"]))
    return pol.make_model(env, seed=int(C.PPO["seed"]), **ppo_kwargs(n_envs))


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def save_checkpoint(model: Any, run_dir: Path, n: int, why: str, extra: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """checkpoints/ckpt_<t>/{model.zip, checkpoint.json} (the digest of the model file is pinned in checkpoint.json and in the checkpoint index)."""
    d = Path(run_dir) / "checkpoints" / (f"ckpt_{n:09d}" if why != "final" else "final")
    d.mkdir(parents=True, exist_ok=False)
    model.save(str(d / "model.zip"))
    meta = {"checkpoint": d.name, "why": why, "num_timesteps": int(n), "model_zip_sha256": sha256_file(d / "model.zip"), "model_zip_bytes": (d / "model.zip").stat().st_size,
            "observation": C.OBSERVATION_CONTRACT, "action": C.ACTION_CONTRACT, "reward": C.REWARD_CONTRACT, "ppo": dict(C.PPO), "gate": C.GATE, "scope": C.SCOPE}
    if extra:
        meta.update(extra)
    A.write_json(d / "checkpoint.json", A.stamp(meta))
    return {k: meta[k] for k in ("checkpoint", "why", "num_timesteps", "model_zip_sha256", "model_zip_bytes")}


def train(model: Any, env: Any, arena: V.Arena, curriculum: CU.Curriculum, recorder: TrainRecorder, *, run_dir: Path, guard: Callable[[], None],
          now: Callable[[], float], transition_cap: int = C.TRANSITION_CAP, extra_meta: Optional[Mapping[str, Any]] = None,
          checkpoint_every: int = C.CHECKPOINT_EVERY) -> Dict[str, Any]:
    """Run `model.learn` under the registered caps. Returns the stop record: `valid_end` is True for the wall cap, the native-tick cap and the transition
    cap (the registered ends of the phase) and False for any earlier stop. The final checkpoint is always written (the model after its last update)."""
    run_dir = Path(run_dir)
    Callback = make_callback_class()

    def save(m: Any, n: int, why: str) -> Dict[str, Any]:
        return save_checkpoint(m, run_dir, n, why, extra_meta)

    cb = Callback(run_dir=run_dir, env=env, arena=arena, curriculum=curriculum, recorder=recorder, guard=guard, transition_cap=transition_cap, now=now, save=save,
                  checkpoint_every=checkpoint_every)
    stop = {"reason": None, "valid_end": False, "error": None}
    t0 = now()
    try:
        kwargs: Dict[str, Any] = {"callback": cb}
        try:
            import inspect

            if "log_interval" in inspect.signature(model.learn).parameters:
                kwargs["log_interval"] = None
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
            final = save_checkpoint(model, run_dir, n, "final", extra_meta)
        except Exception as exc:                                 # noqa: BLE001 - recorded
            final = {"error": f"{type(exc).__name__}: {exc}"}
    stop.update({"num_timesteps": int(getattr(model, "num_timesteps", 0)), "wall_s": round(now() - t0, 2), "rollouts": cb.rollout, "checkpoints": cb.checkpoints,
                 "final": final, "transitions": int(getattr(env, "transitions", 0)), "ticks": {"prefix": arena.budget.prefix, "policy": arena.budget.policy,
                                                                                              "total": arena.budget.consumed, "cap": arena.budget.cap}})
    return stop


def contract_description() -> Dict[str, Any]:
    return {"contract": TRAIN_CONTRACT, "ppo": dict(C.PPO), "checkpoint_every": C.CHECKPOINT_EVERY, "n_steps": "5,120 / vector width", "losses": "PPO only: no imitation, "
            "self-imitation or auxiliary loss; routes are start states only", "valid_ends": ["wall cap", "native-tick cap", "transition cap"]}
