"""M9-g1: the staged-start arena, the episode bookkeeping and the training VecEnv over staged starts.

`Arena` drives a slot pool: idle slots are given the next start (a stage job), staged starts wait parked at input tick tau (READY), and a
READY start becomes an ACTIVE episode when a consumer takes it. An episode is stepped one native tick per submitted word; the per-episode
bookkeeping lives in `EpisodeCtx` (submitted / sampled words, sticky mask, reward under btt_reward_v2 REBASED at the handover so that prefix
breaks earn nothing, horizon counted from the reset, fall = native failure = termination). `TrainVecEnv` is the Stable-Baselines3 VecEnv
whose n_envs episodes are taken from the arena; prefix ticks never enter a rollout and `num_timesteps` counts policy transitions only.

Semantics (proposal 5.1-5.2, the exact submit / consume / input-tick contract): the prefix word i consumes tick i; the policy's first word
consumes tick tau and its observation is the one built from every reply 0..tau-1; a parked process waits at WaitingForAction, no tick passes.
"""
from __future__ import annotations

import hashlib
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

import m8_rd_cells as mcell
import m9_contract as C
import m9_sticky as S
from btt_rewards import REWARD_V2, reward_step

VEC_CONTRACT = "m9_vec_v1"


class CapStop(Exception):
    """A cap ended a phase. `valid` is True for the registered ends of a phase (its wall cap, its native-tick cap, its transition cap) and False for
    any earlier stop (memory, process count, lifecycle failures, a dead worker): the latter is INCOMPLETE."""

    def __init__(self, reason: str, valid: bool = False):
        super().__init__(reason)
        self.reason, self.valid = reason, bool(valid)


class IntegrityStop(Exception):
    """An integrity failure: the session is INVALID."""

    def __init__(self, why: str, detail: Optional[Mapping[str, Any]] = None):
        super().__init__(why)
        self.why, self.detail = why, dict(detail or {})


class TickBudget:
    """Native ticks of a phase: staged prefixes are RESERVED at dispatch (exactly tau), policy steps are added as they are taken."""

    def __init__(self, cap: int):
        self.cap = int(cap)
        self.consumed = 0
        self.reserved = 0
        self.prefix = 0
        self.policy = 0

    def total(self) -> int:
        return self.consumed + self.reserved

    def can_stage(self, tau: int) -> bool:
        return self.total() + int(tau) <= self.cap

    def reserve(self, tau: int) -> None:
        self.reserved += int(tau)

    def staged(self, tau: int) -> None:
        self.reserved -= int(tau)
        self.consumed += int(tau)
        self.prefix += int(tau)

    def failed(self, tau: int, ticks_done: int = 0) -> None:
        self.reserved -= int(tau)
        self.consumed += int(ticks_done)

    def step(self, n: int = 1) -> None:
        self.consumed += n
        self.policy += n

    def exhausted(self) -> bool:
        return self.total() >= self.cap


@dataclass
class StartJob:
    episode: int
    start: Any                      # m9_curriculum.Start (or a start-shaped object: .tau .lineage .region .shared .pointer)
    label: Optional[str]            # the sticky label (None = no perturbation)
    driver: str = "policy"          # policy | tape | random
    deterministic: bool = False
    kind: str = "train"
    tier: int = 0
    job_id: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.job_id:
            self.job_id = f"{self.kind}-{self.episode:07d}"


class EpisodeCtx:
    """One staged-then-active episode: words, sticky bookkeeping, rebased reward, the final record."""

    def __init__(self, job: StartJob, slot: int, staged: Mapping[str, Any], prefix_words: bytes):
        self.job, self.slot = job, slot
        self.tau = int(staged["tau"])
        self.lineage = str(staged["lineage"])
        self.prefix = bytes(prefix_words[:self.tau])
        self.prev_word: Optional[int] = self.prefix[-1] if self.tau > 0 else None
        self.sampled, self.sub, self.mask = bytearray(), bytearray(), bytearray()
        self.obs: Mapping[str, np.ndarray] = staged["obs"]
        self.prev_targets: Optional[int] = int(staged["targets_remaining"])
        self.ret = 0.0
        self.steps = 0
        self.terms = {"target_term": 0.0, "step_term": 0.0, "clear_term": 0.0, "failure_term": 0.0}
        self.staged = {k: staged.get(k) for k in ("boot_s", "native_s", "build_s", "wall_s", "mode", "pid", "worker", "handover_chain", "handover_v3", "ticks")}
        self.t_start = time.monotonic()
        self.final: Optional[Dict[str, Any]] = None
        self.lifecycle: Optional[Dict[str, Any]] = None

    @property
    def tick(self) -> int:
        return self.tau + len(self.sub)

    def choose(self, sampled: int) -> int:
        """The word to submit for the next tick (sticky applied) and its bookkeeping."""
        word, sticky = S.submit(self.job.label, self.tick, int(sampled), self.prev_word)
        self.sampled.append(int(sampled))
        self.sub.append(word)
        self.mask.append(1 if sticky else 0)
        self.prev_word = word
        return word

    def apply(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        """The reward under btt_reward_v2 (rebased at the handover) and the termination of one step reply."""
        cur = int(payload["targets_remaining"]) if int(payload["btt_active"]) == 1 else None
        terms = reward_step(self.prev_targets, cur, clear=bool(payload["clear"]), native_failure=bool(payload["fell"]), contract=REWARD_V2)
        self.prev_targets = cur
        self.ret += terms.total
        self.terms["target_term"] += terms.target_term
        self.terms["step_term"] += terms.step_term
        self.terms["clear_term"] += terms.clear_term
        self.terms["failure_term"] += terms.failure_term
        self.steps += 1
        self.obs = payload["obs"]
        end = payload["end"]
        return {"reward": float(terms.total), "terminated": end in ("clear", "fall", "ended"), "truncated": end == "horizon", "end": end}

    def words(self) -> bytes:
        return self.prefix + bytes(self.sub)

    def native_digest(self) -> str:
        return mcell.words_digest(self.words())

    def record(self, final: Mapping[str, Any]) -> Dict[str, Any]:
        """The compact canonical record of the episode (everything needed to replay and re-derive it)."""
        j = self.job
        rec = {"episode": j.job_id, "kind": j.kind, "driver": j.driver, "deterministic": j.deterministic, "label": j.label, "lineage": self.lineage, "tau": self.tau,
               "start": j.start.to_json() if hasattr(j.start, "to_json") else dict(j.extra.get("start") or {}), "end_reason": final["end_reason"],
               "clear": final["end_reason"] == "clear", "ticks": int(final["ticks"]), "policy_ticks": int(final["policy_ticks"]), "return": round(self.ret, 6),
               "reward_terms": {k: round(v, 6) for k, v in self.terms.items()}, "breaks": final["breaks"], "t": final["labels"]["t"],
               "first": final["labels"]["first"], "chain_final": final["chain_final"], "end_obs": final["end_obs"], "result": final.get("result"),
               "exit_code": final.get("exit_code"), "finish_error": final.get("finish_error"), "native_action_digest": self.native_digest(),
               "prefix_words": self.tau, "prefix_sha256": hashlib.sha256(self.prefix).hexdigest(), "submitted_hex": bytes(self.sub).hex(),
               "sampled_hex": bytes(self.sampled).hex(), "sticky_mask_hex": bytes(self.mask).hex(), "sticky_hits": int(sum(self.mask)),
               "stage": dict(self.staged), "native_s": final.get("native_s"), "build_s": final.get("build_s"), "wall_s": final.get("wall_s"),
               "stale_builds": final.get("stale_builds"), "projectile_overflow": final.get("projectile_overflow"), "slot": self.slot, "tier": j.tier}
        return rec

    def online(self, final: Mapping[str, Any]) -> Dict[str, Any]:
        return {"breaks": final["breaks"], "chain_final": final["chain_final"], "end_obs": final["end_obs"], "end_reason": final["end_reason"],
                "result": final.get("result"), "native_action_digest": self.native_digest()}


class Arena:
    """The slots of one pool, the staging pipeline and the active episodes. `source.next_job(arena)` yields the next StartJob or None."""

    def __init__(self, pool: Any, tables: Mapping[str, Any], source: Any, budget: TickBudget, *, now: Callable[[], float] = time.monotonic,
                 guard: Optional[Callable[[], None]] = None, lifecycle_limit: int = C.LIFECYCLE_FAILURE_LIMIT, max_staging: Optional[int] = None,
                 max_procs: Optional[int] = None, log: Optional[Callable[[str], None]] = None):
        self.pool, self.tables, self.source, self.budget = pool, tables, source, budget
        self.now, self.guard, self.lifecycle_limit, self.log = now, guard, int(lifecycle_limit), log or (lambda s: None)
        self.state = ["idle"] * pool.n
        self.job: List[Optional[StartJob]] = [None] * pool.n
        self.t_dispatch = [0.0] * pool.n
        self.ready: Deque[int] = deque()
        self.ready_payload: Dict[int, Dict[str, Any]] = {}
        self.active: Dict[int, EpisodeCtx] = {}
        self.max_staging = max_staging                  # staging + parked starts allowed at once (P3: the preparing slots)
        self.max_procs = max_procs                      # staging + parked + active processes allowed at once (P2: leaves room for the cold replays)
        self.lifecycle_failures: List[Dict[str, Any]] = []
        self.stage_log: List[Dict[str, Any]] = []
        self.wait_s = 0.0
        self.waits = 0
        self.staged_total = 0
        self.dispatched = 0
        self.source_done = False
        self.provenance: List[str] = []
        self.events_seen = 0
        self.stale_events = 0

    # -- staging --------------------------------------------------------------------------------------------------------------------

    def alive_slots(self) -> int:
        return sum(1 for i in range(self.pool.n) if self.pool.alive(i))

    def staging_count(self) -> int:
        return sum(1 for s in self.state if s == "staging")

    def process_count(self) -> int:
        """Slots that hold (or are launching) a BattleShip process: staging, parked and active."""
        return sum(1 for s in self.state if s in ("staging", "ready", "active"))

    def dispatch(self) -> None:
        """Give every idle live slot its next start while the budget allows (the budget reserves tau at dispatch)."""
        if self.source_done:
            return
        for slot in range(self.pool.n):
            if self.state[slot] != "idle" or not self.pool.alive(slot):
                continue
            if self.max_staging is not None and self.staging_count() + len(self.ready) >= self.max_staging:
                break
            if self.max_procs is not None and self.process_count() >= self.max_procs:
                break
            job = self.source.next_job(self)
            if job is None:
                self.source_done = True
                break
            if not self.budget.can_stage(job.start.tau):
                self.source.unget(job)
                self.source_done = True
                break
            self.budget.reserve(job.start.tau)
            self.job[slot] = job
            self.state[slot] = "staging"
            self.t_dispatch[slot] = self.now()
            self.dispatched += 1
            self.pool.send(slot, ("stage", {"episode": job.job_id, "lineage": job.start.lineage, "tau": int(job.start.tau), "label": job.label}))

    def _check_provenance(self, payload: Mapping[str, Any]) -> None:
        v = payload.get("provenance_violations")
        if v:
            self.provenance = list(v)
            raise IntegrityStop("provenance or write-guard violation", {"violations": list(v)[:5]})

    def handle(self, slot: int, kind: str, payload: Dict[str, Any]) -> Optional[Tuple[int, str, Dict[str, Any]]]:
        """Process one pool event. Staging events are consumed here; step / close events are returned to the caller."""
        self.events_seen += 1
        self._check_provenance(payload)
        if kind == "closed":
            return None
        if kind in ("staged", "stage_failed"):
            job = self.job[slot]
            if job is None or (payload.get("episode") is not None and payload.get("episode") != job.job_id):
                self.stale_events += 1                  # the reply of a stage started by an earlier arena of this pool: its job is not this arena's
                if kind == "stage_failed" and payload.get("kind") == "mismatch":
                    raise IntegrityStop(f"a staged start of an earlier phase failed an integrity check: {payload.get('mismatch')}", payload)    # never silently dropped
                return None
            tau = int(job.start.tau)
            if kind == "staged":
                self.budget.staged(tau)
                self.state[slot] = "ready"
                self.ready.append(slot)
                self.ready_payload[slot] = payload
                self.staged_total += 1
                self.stage_log.append({"episode": payload["episode"], "tau": tau, "wall_s": payload["wall_s"], "boot_s": payload["boot_s"],
                                       "native_s": payload["native_s"], "build_s": payload["build_s"], "mode": payload["mode"], "slot": slot,
                                       "dispatch_to_ready_s": round(self.now() - self.t_dispatch[slot], 3)})
                return None
            self.budget.failed(tau)
            self.state[slot] = "idle"
            self.job[slot] = None
            if payload.get("kind") == "mismatch":
                raise IntegrityStop(f"a staged start failed an integrity check: {payload.get('mismatch')}", payload)
            if payload.get("kind") == "lifecycle":
                self.lifecycle_failures.append({"episode": payload.get("episode"), "outcome": payload.get("outcome"), "message": payload.get("message"), "slot": slot})
                if len(self.lifecycle_failures) > self.lifecycle_limit:
                    raise CapStop(f"more than {self.lifecycle_limit} lifecycle failures", valid=False)
                if getattr(self.source, "requeue_on_lifecycle", False):
                    self.source.unget(job)                      # a fixed list is completed: the same job (same id, same sticky keys) is staged again
                    self.source_done = False
                return None
            if payload.get("kind") == "aborted":
                return None
            raise CapStop(f"a worker reported an error while staging: {payload.get('error')} {str(payload.get('trace', ''))[-500:]}", valid=False)
        if kind == "died":
            prev = self.state[slot]
            self.state[slot] = "dead"
            job, self.job[slot] = self.job[slot], None
            if prev == "staging" and job is not None:
                self.budget.failed(int(job.start.tau))           # the prefix reservation returns (a parked start's prefix was already consumed)
            if prev == "ready":
                try:
                    self.ready.remove(slot)                       # a parked start whose process is gone is never handed to a consumer
                except ValueError:
                    pass
                self.ready_payload.pop(slot, None)
            self.lifecycle_failures.append({"episode": job.job_id if job else None, "outcome": "worker_died", "message": str(payload), "slot": slot})
            if slot in self.active:
                return slot, "died", payload
            if job is not None and prev in ("staging", "ready") and getattr(self.source, "requeue_on_lifecycle", False):
                self.source.unget(job)                            # a fixed list is completed: its job is staged again on another slot
                self.source_done = False
            if len(self.lifecycle_failures) > self.lifecycle_limit:
                raise CapStop(f"more than {self.lifecycle_limit} lifecycle failures (a worker died)", valid=False)
            return None
        if kind == "fatal":
            raise CapStop(f"a worker is fatal: {payload}", valid=False)
        return slot, kind, payload

    def pump(self, timeout: float) -> List[Tuple[int, str, Dict[str, Any]]]:
        """Dispatch stages, poll the pool once, handle staging events and return the rest (stepped / step_failed / closed / died)."""
        if self.guard:
            self.guard()
        self.dispatch()
        out: List[Tuple[int, str, Dict[str, Any]]] = []
        for slot, kind, payload in self.pool.poll(timeout):
            r = self.handle(slot, kind, payload)
            if r is not None:
                out.append(r)
        if self.budget.exhausted():
            raise CapStop("native tick cap", valid=True)
        self.dispatch()
        return out

    def wait_ready(self, timeout: float = 0.2) -> int:
        """Block until a start is READY; returns its slot (and removes it from the ready queue). The wait is recorded."""
        t0 = self.now()
        waited = False
        while not self.ready:
            waited = True
            if self.source_done and self.staging_count() == 0 and not self.ready:
                # no start will ever be ready: the source is exhausted or the native-tick budget cannot fit another prefix (the registered end of the phase)
                raise CapStop("native tick cap (no further prefix fits the budget)", valid=True)
            leftovers = self.pump(timeout)
            if leftovers:
                raise RuntimeError(f"unexpected events while waiting for a ready start: {[(s, k) for s, k, _p in leftovers][:4]}")
        if waited:
            self.waits += 1
            self.wait_s += self.now() - t0
        return self.ready.popleft()

    # -- episodes -------------------------------------------------------------------------------------------------------------------

    def activate(self, slot: int) -> EpisodeCtx:
        payload = self.ready_payload.pop(slot)
        job = self.job[slot]
        assert job is not None
        ctx = EpisodeCtx(job, slot, payload, self.tables[payload["lineage"]].words)
        self.state[slot] = "active"
        self.active[slot] = ctx
        return ctx

    def send_step(self, ctx: EpisodeCtx, sampled_word: int) -> int:
        word = ctx.choose(sampled_word)
        self.pool.send(ctx.slot, ("step", {"word": word}))
        return word

    def release(self, slot: int) -> None:
        self.active.pop(slot, None)
        self.job[slot] = None
        if self.state[slot] != "dead":
            self.state[slot] = "idle"

    def close_unfinished(self) -> None:
        """At a phase end: close every parked or active process (the worker releases its BattleShip)."""
        for slot in range(self.pool.n):
            if self.state[slot] in ("ready", "active", "staging") and self.pool.alive(slot):
                try:
                    self.pool.send(slot, ("close", {}))
                except (OSError, BrokenPipeError):
                    pass

    def summary(self) -> Dict[str, Any]:
        return {"staged": self.staged_total, "dispatched": self.dispatched, "lifecycle_failures": list(self.lifecycle_failures), "wait_s": round(self.wait_s, 2),
                "waits": self.waits, "prefix_ticks": self.budget.prefix, "policy_ticks": self.budget.policy, "reserved": self.budget.reserved,
                "alive_slots": self.alive_slots()}


# -- the training VecEnv --------------------------------------------------------------------------------------------------------------------


def make_vec_env_class() -> Any:
    from gymnasium import spaces
    from stable_baselines3.common.vec_env import VecEnv

    import m9_obs

    class TrainVecEnv(VecEnv):
        """n_envs episodes taken from the arena. Rewards, terminations and truncations as documented in the module docstring."""

        def __init__(self, arena: Arena, n_envs: int, recorder: Optional[Callable[[EpisodeCtx, Mapping[str, Any]], None]] = None,
                     outcome: Optional[Callable[[EpisodeCtx, bool], None]] = None, on_step: Optional[Callable[[int], None]] = None):
            super().__init__(n_envs, m9_obs.observation_space(), spaces.MultiDiscrete([9, 8]))
            self.arena, self.recorder, self.outcome, self.on_step = arena, recorder, outcome, on_step
            self.eps: List[Optional[EpisodeCtx]] = [None] * n_envs
            self._actions: Optional[np.ndarray] = None
            self.transitions = 0
            self.episodes = 0
            self.clears = 0
            self.lifecycle_truncations = 0
            self.truncations = 0
            self._obs: Dict[str, np.ndarray] = {k: np.zeros((n_envs,) + tuple(sp.shape), dtype=np.float32) for k, sp in self.observation_space.spaces.items()}

        # -- helpers --
        def _set_obs(self, i: int, obs: Mapping[str, np.ndarray]) -> None:
            for k, v in obs.items():
                self._obs[k][i] = v

        def _copy_obs(self) -> Dict[str, np.ndarray]:
            return {k: v.copy() for k, v in self._obs.items()}

        def _start_episode(self, i: int) -> None:
            slot = self.arena.wait_ready()
            ctx = self.arena.activate(slot)
            self.eps[i] = ctx
            self._set_obs(i, ctx.obs)

        # -- VecEnv API --
        def reset(self):
            for i in range(self.num_envs):
                if self.eps[i] is None:
                    self._start_episode(i)
            self.reset_infos = [{} for _ in range(self.num_envs)]
            return self._copy_obs()

        def step_async(self, actions: np.ndarray) -> None:
            self._actions = np.asarray(actions)

        def step_wait(self):
            assert self._actions is not None
            pending: Dict[int, int] = {}
            for i in range(self.num_envs):
                ctx = self.eps[i]
                assert ctx is not None
                a = self._actions[i]
                self.arena.send_step(ctx, int(a[0]) * 8 + int(a[1]))
                pending[ctx.slot] = i
            replies: Dict[int, Tuple[str, Dict[str, Any]]] = {}
            while len(replies) < self.num_envs:
                for slot, kind, payload in self.arena.pump(0.05):
                    if slot not in pending:
                        raise RuntimeError(f"a reply from slot {slot} that no env is waiting for ({kind})")
                    replies[pending[slot]] = (kind, payload)
            rewards = np.zeros(self.num_envs, dtype=np.float32)
            dones = np.zeros(self.num_envs, dtype=bool)
            infos: List[Dict[str, Any]] = [{} for _ in range(self.num_envs)]
            for i in range(self.num_envs):
                kind, payload = replies[i]
                ctx = self.eps[i]
                assert ctx is not None
                if kind == "step_failed" or kind == "died":
                    self._failed_step(i, ctx, kind, payload, rewards, dones, infos)
                    continue
                self.arena.budget.step(1)
                self.transitions += 1
                r = ctx.apply(payload)
                rewards[i] = r["reward"]
                if r["terminated"] or r["truncated"]:
                    dones[i] = True
                    infos[i] = {"terminal_observation": {k: np.asarray(v, dtype=np.float32).copy() for k, v in payload["obs"].items()},
                                "TimeLimit.truncated": bool(r["truncated"] and not r["terminated"]),
                                "episode": {"r": round(ctx.ret, 6), "l": ctx.steps, "t": round(time.monotonic() - ctx.t_start, 3)},
                                "m9_end": r["end"], "m9_clear": r["end"] == "clear"}
                    final = payload["final"]
                    rec = ctx.record(final)
                    ctx.final = final
                    self.episodes += 1
                    self.truncations += int(bool(r["truncated"]))
                    self.clears += int(rec["clear"])
                    if self.recorder:
                        self.recorder(ctx, rec)
                    if self.outcome:
                        self.outcome(ctx, bool(rec["clear"]))
                    self.arena.release(ctx.slot)
                    self.eps[i] = None
                else:
                    self._set_obs(i, payload["obs"])
            if self.on_step:
                self.on_step(self.transitions)
            for i in range(self.num_envs):
                if self.eps[i] is None:
                    self._start_episode(i)
            return self._copy_obs(), rewards, dones, infos

        def _failed_step(self, i: int, ctx: EpisodeCtx, kind: str, payload: Mapping[str, Any], rewards: np.ndarray, dones: np.ndarray,
                         infos: List[Dict[str, Any]]) -> None:
            if kind == "step_failed" and payload.get("kind") == "mismatch":
                raise IntegrityStop(f"a policy-phase step failed an integrity check: {payload.get('mismatch')}", payload)
            if kind == "step_failed" and payload.get("kind") == "error":
                raise CapStop(f"a worker reported an error while stepping: {payload.get('error')} {str(payload.get('trace', ''))[-500:]}", valid=False)
            self.lifecycle_truncations += 1
            if kind != "died":                                      # a worker death was already counted by the arena when the event arrived
                self.arena.lifecycle_failures.append({"episode": ctx.job.job_id, "outcome": payload.get("outcome", kind), "message": str(payload.get("message", payload))[:200],
                                                      "slot": ctx.slot, "phase": "step"})
            if len(self.arena.lifecycle_failures) > self.arena.lifecycle_limit:
                raise CapStop(f"more than {self.arena.lifecycle_limit} lifecycle failures", valid=False)
            dones[i] = True
            rewards[i] = 0.0
            infos[i] = {"terminal_observation": {k: np.asarray(v, dtype=np.float32).copy() for k, v in ctx.obs.items()}, "TimeLimit.truncated": True,
                        "m9_end": "lifecycle_failure", "m9_clear": False}
            self.arena.release(ctx.slot)
            if kind == "died":
                self.arena.state[ctx.slot] = "dead"
            self.eps[i] = None

        def close(self) -> None:
            self.arena.close_unfinished()

        def get_attr(self, attr_name: str, indices: Any = None) -> List[Any]:
            return [getattr(self, attr_name, None) for _ in self._get_indices(indices)]

        def set_attr(self, attr_name: str, value: Any, indices: Any = None) -> None:
            raise NotImplementedError

        def env_method(self, method_name: str, *method_args: Any, indices: Any = None, **method_kwargs: Any) -> List[Any]:
            raise NotImplementedError

        def env_is_wrapped(self, wrapper_class: Any, indices: Any = None) -> List[bool]:
            return [False for _ in self._get_indices(indices)]

        def get_images(self) -> Sequence[Optional[np.ndarray]]:
            return [None] * self.num_envs

    return TrainVecEnv


def contract_description() -> Dict[str, Any]:
    return {"contract": VEC_CONTRACT, "reward": C.REWARD_CONTRACT + " rebased at the handover (prefix breaks earn nothing; the per-tick cost is the policy phase's)",
            "horizon": "input ticks from the reset (the prefix counts)", "terminated": "clear, fall (native failure), ended", "truncated": "horizon",
            "lifecycle_failure": "a truncation with reward 0, not an outcome of the curriculum", "num_timesteps": "policy transitions only"}
