#!/usr/bin/env python3
"""M7: worker-side stack for parallel Stable-Baselines3 training on BattleShip Mario Break the Targets.

Nothing here imports Stable-Baselines3 or PyTorch: spawn workers stay light
(Gymnasium, NumPy and the frozen M1-M5 stack only). The parent side (the
SubprocVecEnv subclass, PPO, VecNormalize) lives in rl/m7_vec_env.py and
rl/m7_trainer.py.

One worker = one vector environment slot = at most one BattleShip process at a
time. Its environment stack, inner to outer:

    M7BattleShipBTTEnv      M3 BattleShipBTTEnv + per-rank port candidates with bounded startup
                            retry + native-failure (fall) termination + native-step timing
    M7RewardWrapper         btt_reward_v1, unchanged constants and function; the clear bonus and
                            the clear check apply to the native clear only (never to a fall)
    EpisodeRecordingWrapper M4 recorder, unchanged: canonical native triples + consumed_tick
    Track1PolicyWrapper     M5, unchanged: MultiDiscrete([9, 8]) in, 15-float policy observation out
    EpisodeStatsWrapper     SB3-Monitor-compatible info["episode"] (r, l, t), no SB3 import
    M7WorkerWrapper         slim picklable info, rank/episode context on errors, control methods

Fall semantics (btt_native_failure_v1). Break the Targets has no native
failure result: after a fall the game shows its failure sequence
(game_status 5 for one update, 6 for 90, 7 for 5), unloads the scene, and the
next M1c step never completes (measured in M7 Phase A). The first post-update
observation with game_status == 5 (nSCBattleGameStatusEnd), btt_active == 1,
targets_remaining > 0 and no native EpisodeEnded result is therefore the
native failure: the step is returned as terminated=True, truncated=False,
info["termination_reason"] = "native_failure", the process is disposed of
at once and no further step is sent. The clear transition carries
EpisodeEnded with targets_remaining == 0 and is never classified as a fall.

Preservation decisions that must be global across workers (periodic
milestone, new best target count, first clear, new fastest clear) are made
under a file lock by RunCoordinator; every worker writes its artifacts into
its own directory. Anomaly (M4 detector) and manual reasons are worker-local.

No native RNG inspection, logging, validation, control, comparison or hashing
exists here. The only digest is a Python-side SHA-256 of the canonical
native actions an episode submitted (for determinism checks of evaluation).
"""

from __future__ import annotations

import bisect
import dataclasses
import hashlib
import json
import math
import os
import random
import shutil
import signal
import sys
import time
import traceback
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import gymnasium as gym
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))

from battleship_client import Observation, StepState  # noqa: E402
from battleship_env import DEFAULT_EXECUTABLE, BattleShipBTTEnv  # noqa: E402
from battleship_process import EpisodeFailure, EpisodeOutcome, LaunchConfig  # noqa: E402
from btt_learning import (  # noqa: E402
    DEFAULT_REWARD_CONFIG,
    REWARD_CONTRACT,
    TARGETS_TOTAL,
    RewardV1Config,
    RewardV1Wrapper,
    Track1PolicyWrapper,
    contracts as m5_contracts,
    live_targets,
    reward_v1,
)
from m7_runtime import (  # noqa: E402
    IS_WINDOWS,
    PORT_BLOCK_BASE,
    PORT_BLOCK_SIZE,
    PortCandidates,
    pid_alive,
    portable_path,
    replace_with_retry,
)
from run_artifacts import (  # noqa: E402
    DEFAULT_POSITION_DELTA_THRESHOLD,
    EpisodeRecorder,
    EpisodeRecordingWrapper,
    EpisodeStatus,
    PositionDeltaDetector,
    PreservationReason,
)

try:
    from bench import ProcessMetrics  # rl/tools/bench.py, standard library only
except Exception:  # noqa: BLE001 - metrics are optional diagnostics
    ProcessMetrics = None  # type: ignore[assignment]

M7_MILESTONE = "M7a"
M7_HORIZON = 3600  # native ticks = 60 s of game time at 60 tics/s; Python-owned bound (no native limit exists)

# nSCBattleGameStatusEnd (decomp src/sc/scdef.h). ifCommonBattleSetInterface
# sets it for both the clear announcement and the failure announcement.
GAME_STATUS_END = 5
FAILURE_CONTRACT = "btt_native_failure_v1"
TERMINATION_NATIVE_CLEAR = "native_clear"
TERMINATION_NATIVE_FAILURE = "native_failure"

END_CLEAR = "clear"
END_FALL = "fall"
END_HORIZON = "horizon"
END_LIFECYCLE_FAILURE = "lifecycle_failure"
END_ABORTED = "aborted"

# The M2 lifecycle outcomes a startup attempt may end with and be retried
# (a new process on a new port). A process that survives kill is not retried.
NON_RETRYABLE_STARTUP = (EpisodeOutcome.CLEANUP_FAILURE,)


def is_native_failure(observation: Observation, state: StepState) -> bool:
    """The btt_native_failure_v1 rule on one post-update M1c step result."""
    return (
        state != StepState.EPISODE_ENDED
        and int(observation.btt_active) == 1
        and int(observation.game_status) == GAME_STATUS_END
        and int(observation.targets_remaining) > 0
    )


def m7_contracts(horizon: int) -> Dict[str, Any]:
    """Every contract a checkpoint depends on (compared on load/resume)."""
    c = dict(m5_contracts())
    c.update({
        "failure_contract": FAILURE_CONTRACT,
        "failure_rule": "first post-update observation with game_status == 5, btt_active == 1, "
                        "targets_remaining > 0 and no native EpisodeEnded -> terminated, reason native_failure",
        "termination_reasons": [TERMINATION_NATIVE_CLEAR, TERMINATION_NATIVE_FAILURE],
        "truncation_reasons": ["max_episode_steps", "episode_failure"],
        "horizon_native_ticks": int(horizon),
        "reward_constants": DEFAULT_REWARD_CONFIG.to_json(),
    })
    return c


# -- latency histogram ---------------------------------------------------------------------------

_EDGES = [10 ** (e / 20.0) for e in range(-100, 41)]  # 10 us .. 100 s, 20 bins per decade (upper edges)


class LatencyHistogram:
    """Mergeable log-spaced histogram of durations (seconds) with exact count, sum, min and max."""

    def __init__(self) -> None:
        self.counts = [0] * (len(_EDGES) + 1)
        self.n = 0
        self.total = 0.0
        self.min = math.inf
        self.max = 0.0

    def add(self, seconds: float) -> None:
        self.counts[bisect.bisect_left(_EDGES, seconds)] += 1
        self.n += 1
        self.total += seconds
        if seconds < self.min:
            self.min = seconds
        if seconds > self.max:
            self.max = seconds

    def to_json(self) -> Dict[str, Any]:
        return {"n": self.n, "sum_s": self.total, "min_s": None if self.n == 0 else self.min, "max_s": self.max,
                "counts": {str(i): c for i, c in enumerate(self.counts) if c}}

    @staticmethod
    def merged(items: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        counts: Dict[str, int] = {}
        n, total, lo, hi = 0, 0.0, math.inf, 0.0
        for d in items:
            if not d or not d.get("n"):
                continue
            for k, v in d["counts"].items():
                counts[k] = counts.get(k, 0) + int(v)
            n += int(d["n"])
            total += float(d["sum_s"])
            lo = min(lo, float(d["min_s"]))
            hi = max(hi, float(d["max_s"]))
        return {"n": n, "sum_s": total, "min_s": None if n == 0 else lo, "max_s": hi, "counts": counts}

    @staticmethod
    def summary(d: Mapping[str, Any]) -> Dict[str, Any]:
        """Mean, extremes and bin-resolution percentiles (upper bin edge, ~12 % resolution) in milliseconds."""
        n = int(d.get("n") or 0)
        if n == 0:
            return {"n": 0}
        counts = {int(k): int(v) for k, v in d["counts"].items()}
        out: Dict[str, Any] = {"n": n, "mean_ms": round(1000 * float(d["sum_s"]) / n, 4),
                               "min_ms": round(1000 * float(d["min_s"]), 4), "max_ms": round(1000 * float(d["max_s"]), 3)}
        for q in (0.5, 0.9, 0.99, 0.999):
            target = q * n
            acc = 0
            for idx in sorted(counts):
                acc += counts[idx]
                if acc >= target:
                    edge = _EDGES[idx] if idx < len(_EDGES) else float(d["max_s"])
                    out[f"p{str(q * 100).rstrip('0').rstrip('.')}_ms"] = round(1000 * min(edge, float(d["max_s"])), 4)
                    break
        return out


# -- errors ----------------------------------------------------------------------------------------


class M7StartupError(RuntimeError):
    """Every startup attempt of one reset failed."""

    def __init__(self, rank: int, episode: int, attempts: List[Dict[str, Any]]):
        self.rank = rank
        self.episode = episode
        self.attempts = attempts
        summary = "; ".join(f"attempt {a['attempt']} port {a['port']}: {a['outcome']}" for a in attempts)
        super().__init__(f"worker {rank}: no fresh episode after {len(attempts)} startup attempt(s) "
                         f"(worker episode {episode}): {summary}")


class M7InjectedFault(RuntimeError):
    """Deliberate worker exception used only by the M7 cleanup regressions."""


@dataclass
class WorkerFailure:
    """Sent to the parent instead of a reply when a worker command raised. Picklable."""

    rank: int
    command: str
    exc_type: str
    message: str
    traceback: str
    context: Dict[str, Any]

    def describe(self) -> str:
        ctx = ", ".join(f"{k}={v}" for k, v in self.context.items() if v is not None)
        return f"worker rank {self.rank} failed in '{self.command}': {self.exc_type}: {self.message} [{ctx}]"


# -- the environment --------------------------------------------------------------------------------


class M7BattleShipBTTEnv(BattleShipBTTEnv):
    """M3 environment with M7 lifecycle policy. Every M3 behaviour is kept; added:

    - reset(): up to `startup_attempts` fresh processes, each on a NEW port
      from this worker's block (probe, launch, detect failure, M3 disposes
      and reaps the process, next candidate). Every attempt is recorded.
    - step(): the btt_native_failure_v1 fall termination (see module doc);
      termination_reason native_clear on the native EpisodeEnded result.
    - timing of every native round trip (M1d `step` request) and periodic
      memory/CPU samples of the live game process.
    """

    def __init__(
        self,
        launch_config: LaunchConfig,
        *,
        max_episode_steps: int,
        rank: int,
        ports: PortCandidates,
        startup_attempts: int = 3,
        detect_native_failure: bool = True,
        sample_every: int = 1024,
        port_claim_hook: Optional[Callable[[int, int], None]] = None,
    ):
        super().__init__(launch_config, max_episode_steps=max_episode_steps)
        if startup_attempts < 1:
            raise ValueError("startup_attempts must be >= 1")
        self.rank = int(rank)
        self.ports = ports
        self.startup_attempts = int(startup_attempts)
        self.detect_native_failure = bool(detect_native_failure)
        self.sample_every = int(sample_every)
        self.port_claim_hook = port_claim_hook
        self.metrics = ProcessMetrics() if ProcessMetrics is not None else None
        self.reset_count = 0
        self.startup_attempt_log: List[Dict[str, Any]] = []   # every attempt of every reset
        self.current_startup: Optional[Dict[str, Any]] = None
        self.native_hist = LatencyHistogram()                  # M1d step round trips
        self.last_failure_outcome: Optional[str] = None
        self.process_samples: List[Dict[str, Any]] = []       # last sample of each process
        self._current_sample: Optional[Dict[str, Any]] = None
        self.deferred_deletions: List[Tuple[Path, Dict[str, Any]]] = []
        self.deletion_log: List[Dict[str, Any]] = []

    # -- reset with bounded startup retry ------------------------------------------------------

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        self._dispose_episode()      # the previous process is gone before its directory is touched
        self._flush_process_sample()
        self.drain_deletions()
        self.reset_count += 1
        self.last_failure_outcome = None
        attempts: List[Dict[str, Any]] = []
        t_reset = time.perf_counter()
        for attempt in range(1, self.startup_attempts + 1):
            port, busy = self.ports.claim()
            if self.port_claim_hook is not None:
                self.port_claim_hook(attempt, port)  # test hook only (simulates a squatter after the probe)
            self.launch_config = replace(self.launch_config, port=port)
            t_attempt = time.perf_counter()
            try:
                observation, info = super().reset(seed=seed if attempt == 1 else None, options=options)
            except EpisodeFailure as exc:
                pid = exc.diagnostics.get("pid")
                record = {"reset": self.reset_count, "attempt": attempt, "port": port, "busy_ports_skipped": busy,
                          "outcome": exc.outcome.value, "message": exc.message.splitlines()[0][:300], "pid": pid,
                          "elapsed_s": round(time.perf_counter() - t_attempt, 3),
                          "process_alive_after": pid_alive(pid),
                          "episode_dir": exc.diagnostics.get("episode_dir")}
                attempts.append(record)
                self.startup_attempt_log.append(record)
                if exc.outcome in NON_RETRYABLE_STARTUP:
                    raise M7StartupError(self.rank, self.reset_count, attempts) from exc
                continue
            elapsed = time.perf_counter() - t_attempt
            record = {"reset": self.reset_count, "attempt": attempt, "port": port, "busy_ports_skipped": busy,
                      "outcome": "fresh", "pid": info.get("pid"), "elapsed_s": round(elapsed, 3)}
            attempts.append(record)
            self.startup_attempt_log.append(record)
            self._time_client()
            self._current_sample = None
            self.current_startup = {"attempts": len(attempts), "failed_attempts": len(attempts) - 1,
                                    "ports": [a["port"] for a in attempts], "reset_s": round(time.perf_counter() - t_reset, 3),
                                    "fresh_attempt_s": round(elapsed, 3),
                                    "failures": [a for a in attempts if a["outcome"] != "fresh"]}
            info["m7_startup"] = self.current_startup
            return observation, info
        raise M7StartupError(self.rank, self.reset_count, attempts)

    def _time_client(self) -> None:
        client = self._episode.client if self._episode is not None else None
        if client is None:
            return
        original = client.step
        hist = self.native_hist

        def timed_step(buttons: int, stick_x: int, stick_y: int):
            t0 = time.perf_counter()
            try:
                return original(buttons, stick_x, stick_y)
            finally:
                hist.add(time.perf_counter() - t0)

        client.step = timed_step  # instance attribute on this episode's client only

    # -- step with native-failure termination ---------------------------------------------------------

    def step(self, action):
        try:
            observation, reward, terminated, truncated, info = super().step(action)
        except EpisodeFailure as exc:
            self.last_failure_outcome = exc.outcome.value
            raise
        if self.sample_every and self._steps % self.sample_every == 1:
            self._sample_process()
        result = self.last_step_result
        if (not terminated and self.detect_native_failure and result is not None
                and is_native_failure(result.observation, result.state)):
            # First post-update failure observation: end the episode now. No further
            # step is sent; the failure screen ticks are never advanced.
            if self._episode is not None:  # M3 may already have disposed it (horizon on this very tick)
                self._sample_process()
                info["cleanup_action"] = self._dispose_episode()
            self._phase = "terminated"
            terminated, truncated = True, False
            info.pop("truncation_reason", None)
            info["termination_reason"] = TERMINATION_NATIVE_FAILURE
        elif terminated:
            info["termination_reason"] = TERMINATION_NATIVE_CLEAR
        return observation, reward, terminated, truncated, info

    def close(self):
        try:
            super().close()
        finally:
            self._flush_process_sample()
            self.drain_deletions()

    # -- metrics and episode directories ---------------------------------------------------------------

    def _sample_process(self) -> None:
        if self.metrics is None or self._episode is None:
            return
        sample = self.metrics.sample(self._episode.pid)
        if sample:
            self._current_sample = sample

    def _flush_process_sample(self) -> None:
        if self._current_sample is not None:
            self.process_samples.append(self._current_sample)
            self._current_sample = None

    def queue_deletion(self, directory: Optional[os.PathLike | str], record: Dict[str, Any]) -> None:
        """Delete an M2 episode directory once no process can hold files in it (next reset or close)."""
        if directory:
            self.deferred_deletions.append((Path(directory), record))

    def drain_deletions(self) -> None:
        pending, self.deferred_deletions = self.deferred_deletions, []
        for directory, record in pending:
            entry = dict(record)
            try:
                if directory.exists():
                    shutil.rmtree(directory)
                entry["deleted"] = True
            except OSError as exc:
                entry["deleted"] = False
                entry["error"] = f"{type(exc).__name__}: {exc}"
            self.deletion_log.append(entry)


# -- reward --------------------------------------------------------------------------------------------


class M7RewardWrapper(RewardV1Wrapper):
    """btt_reward_v1 unchanged, evaluated with the NATIVE CLEAR as its terminal flag.

    Identical to RewardV1Wrapper except for the one argument: reward_v1()'s
    `terminated` parameter means "the native EpisodeEnded result" (clear
    bonus, and the targets_remaining == 0 check). An M7 native_failure step
    is terminated for the learner but is not a clear, so it receives
    newly_broken * 1.0 - 0.001 and no bonus; no failure penalty exists."""

    def step(self, action: Any):
        observation, _placeholder, terminated, truncated, info = self.env.step(action)  # EpisodeFailure propagates
        clear = bool(terminated and info.get("termination_reason") == TERMINATION_NATIVE_CLEAR)
        current = live_targets(observation)
        breakdown = reward_v1(self._previous_targets, current, clear, self.reward_config)
        self._previous_targets = current
        self.last_breakdown = breakdown
        self.episode_return += breakdown.total
        self.episode_steps += 1
        self.episode_targets_broken += breakdown.newly_broken
        info["reward_contract"] = REWARD_CONTRACT
        info["reward_v1"] = breakdown.to_json()
        info["episode_return"] = self.episode_return
        info["episode_targets_broken"] = self.episode_targets_broken
        if self.tracker is not None:
            self.tracker.note_step(breakdown, terminated, truncated, info)
        return observation, breakdown.total, terminated, truncated, info


# -- cross-worker coordination --------------------------------------------------------------------------


class FileLock:
    """Exclusive inter-process lock on one byte of a lock file (msvcrt on Windows, flock elsewhere)."""

    def __init__(self, path: Path, timeout: float = 120.0):
        self.path = Path(path)
        self.timeout = timeout
        self._fp = None

    def __enter__(self) -> "FileLock":
        self._fp = open(self.path, "a+b")
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                if IS_WINDOWS:
                    import msvcrt

                    self._fp.seek(0)
                    msvcrt.locking(self._fp.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self._fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    self._fp.close()
                    self._fp = None
                    raise TimeoutError(f"could not lock {self.path} within {self.timeout} s")
                time.sleep(0.002)

    def __exit__(self, *exc: Any) -> None:
        fp, self._fp = self._fp, None
        if fp is None:
            return
        try:
            if IS_WINDOWS:
                import msvcrt

                fp.seek(0)
                msvcrt.locking(fp.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
        finally:
            fp.close()


def _write_json_atomic(path: Path, data: Mapping[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fp:
        json.dump(data, fp, indent=2)
        fp.write("\n")
    replace_with_retry(tmp, path)


def initial_coordination_state(run_id: str, scope: str, periodic_episodes: Optional[int]) -> Dict[str, Any]:
    return {
        "schema": 1,
        "run_id": run_id,
        "scope": scope,
        "periodic_episodes": periodic_episodes,
        "episodes_finished": 0,
        "native_steps": 0,
        "best_targets_broken": 0,
        "best_targets_ref": None,
        "first_clear": None,
        "fastest_clear": None,
        "event_counts": {},
        "lineage": [],
    }


class RunCoordinator:
    """Global preservation decisions shared by all workers of one run (or one evaluation set).

    State lives in <dir>/state.json and every decision is appended to
    <dir>/preservation_ledger.jsonl, both only under <dir>/state.lock.
    Decisions are serialised, so two workers finishing at the same time can
    never both claim the same new best: the second one compares against the
    first one's value (ties are not a new best)."""

    STATE = "state.json"
    LOCK = "state.lock"
    LEDGER = "preservation_ledger.jsonl"

    def __init__(self, directory: os.PathLike | str):
        self.directory = Path(directory)
        self.state_path = self.directory / self.STATE
        self.lock_path = self.directory / self.LOCK
        self.ledger_path = self.directory / self.LEDGER

    @classmethod
    def create(cls, directory: os.PathLike | str, state: Mapping[str, Any]) -> "RunCoordinator":
        coord = cls(directory)
        coord.directory.mkdir(parents=True, exist_ok=True)
        if coord.state_path.exists():
            raise FileExistsError(f"coordination state already exists: {coord.state_path}")
        with FileLock(coord.lock_path):
            _write_json_atomic(coord.state_path, state)
        return coord

    def read(self) -> Dict[str, Any]:
        with FileLock(self.lock_path):
            with open(self.state_path, encoding="utf-8") as fp:
                return json.load(fp)

    def append_ledger(self, entries: Sequence[Mapping[str, Any]]) -> None:
        if not entries:
            return
        with FileLock(self.lock_path):
            self._append_unlocked(entries)

    def _append_unlocked(self, entries: Sequence[Mapping[str, Any]]) -> None:
        with open(self.ledger_path, "a", encoding="utf-8", newline="\n") as fp:
            for e in entries:
                fp.write(json.dumps(e, separators=(",", ":")) + "\n")

    def decide(self, facts: Mapping[str, Any]) -> List[Dict[str, Any]]:
        """Count one finished episode and return its global preservation events."""
        events: List[Dict[str, Any]] = []
        with FileLock(self.lock_path):
            with open(self.state_path, encoding="utf-8") as fp:
                state = json.load(fp)
            state["episodes_finished"] += 1
            state["native_steps"] += int(facts.get("steps", 0))
            ref = {"rank": facts.get("rank"), "worker_episode": facts.get("worker_episode"),
                   "episode_id": facts.get("episode_id"), "artifact_dir": facts.get("artifact_dir")}
            periodic = state.get("periodic_episodes")
            if periodic and state["episodes_finished"] % int(periodic) == 0:
                events.append({"event": "periodic_milestone", "reason": PreservationReason.PERIODIC_MILESTONE.value,
                               "note": f"global finished episode {state['episodes_finished']}"})
            targets = int(facts.get("targets_broken", 0))
            if targets > int(state["best_targets_broken"]):
                events.append({"event": "new_best_target_count", "reason": PreservationReason.NEW_BEST_TARGET_COUNT.value,
                               "note": f"{targets} targets broken, previous global best {state['best_targets_broken']}"})
                state["best_targets_broken"] = targets
                state["best_targets_ref"] = dict(ref, targets_broken=targets)
            if facts.get("cleared") and facts.get("completion_time_passed") is not None:
                ctp = int(facts["completion_time_passed"])
                clear_ref = dict(ref, completion_time_passed=ctp, completion_input_tick=facts.get("completion_input_tick"))
                if state["first_clear"] is None:
                    events.append({"event": "first_successful_clear",
                                   "reason": PreservationReason.NEW_FASTEST_COMPLETED_RUN.value,
                                   "note": f"first successful clear: completion_time_passed {ctp} "
                                           f"(completion_input_tick {facts.get('completion_input_tick')})"})
                    events.append({"event": "new_fastest_completed_run",
                                   "reason": PreservationReason.NEW_FASTEST_COMPLETED_RUN.value, "note": "first clear"})
                    state["first_clear"] = clear_ref
                    state["fastest_clear"] = clear_ref
                elif ctp < int(state["fastest_clear"]["completion_time_passed"]):
                    events.append({"event": "new_fastest_completed_run",
                                   "reason": PreservationReason.NEW_FASTEST_COMPLETED_RUN.value,
                                   "note": f"completion_time_passed {ctp} < previous best "
                                           f"{state['fastest_clear']['completion_time_passed']}"})
                    state["fastest_clear"] = clear_ref
            for e in events:
                state["event_counts"][e["event"]] = state["event_counts"].get(e["event"], 0) + 1
            _write_json_atomic(self.state_path, state)
            self._append_unlocked([dict(e, kind="global_decision", global_episode=state["episodes_finished"], **ref)
                                   for e in events])
        return events


# -- per-worker episode tracker -----------------------------------------------------------------------


class M7EpisodeTracker:
    """Training-side facts and the M7 preservation policy for one worker's M4 recorder."""

    def __init__(
        self,
        *,
        run_id: str,
        role: str,
        rank: int,
        coordinator: RunCoordinator,
        artifact_root: Path,
        ledger_path: Path,
        env: M7BattleShipBTTEnv,
        reward_config: RewardV1Config = DEFAULT_REWARD_CONFIG,
        retain_failed_cap: int = 20,
        preserve_all: bool = False,
    ):
        self.run_id = run_id
        self.role = role
        self.rank = int(rank)
        self.coordinator = coordinator
        self.artifact_root = Path(artifact_root)
        self.ledger_path = Path(ledger_path)
        self.env = env
        self.reward_config = reward_config
        self.retain_failed_cap = int(retain_failed_cap)
        self.preserve_all = bool(preserve_all)
        self.episodes_started = 0
        self.sb3_num_timesteps: Optional[int] = None
        self.checkpoint_label: Optional[str] = None
        self.native_steps = 0
        self.end_counts: Dict[str, int] = {}
        self.failure_outcomes: Dict[str, int] = {}
        self.preserved = 0
        self.discarded = 0
        self.anomaly_events = 0
        self.failed_dirs_kept = 0
        self.summaries_emitted = 0
        self.finished_returns: List[float] = []
        self._manual_note: Optional[str] = None
        self._current: Dict[str, Any] = {}
        self._pending_summary: Optional[Dict[str, Any]] = None

    # -- hooks ------------------------------------------------------------------------------------------

    def labels_for_new_episode(self) -> Dict[str, Any]:
        self.episodes_started += 1
        startup = dict(self.env.current_startup or {})
        self._current = {"worker_episode": self.episodes_started, "steps": 0, "return": 0.0, "targets_broken": 0,
                         "termination_reason": None, "truncation_reason": None, "episode_dir": None,
                         "pid": None, "port": None, "startup": startup, "digest": hashlib.sha256()}
        return {
            "milestone": M7_MILESTONE,
            "role": self.role,
            "run_id": self.run_id,
            "rank": self.rank,
            "worker_episode": self.episodes_started,
            "native_steps_at_start": self.native_steps,
            "sb3_num_timesteps_at_start": self.sb3_num_timesteps,
            "checkpoint_label": self.checkpoint_label,
            "contracts": m7_contracts(self.env.max_episode_steps or 0),
            "startup": startup,
        }

    def note_step(self, breakdown: Any, terminated: bool, truncated: bool, info: Mapping[str, Any]) -> None:
        self.native_steps += 1
        cur = self._current
        if not cur:
            return
        cur["steps"] += 1
        cur["return"] += breakdown.total
        cur["targets_broken"] += breakdown.newly_broken
        cur["termination_reason"] = info.get("termination_reason")
        cur["truncation_reason"] = info.get("truncation_reason")
        cur["episode_dir"] = info.get("episode_dir") or cur["episode_dir"]
        cur["pid"] = info.get("pid") or cur["pid"]
        cur["port"] = info.get("port") or cur["port"]
        native = info.get("native_action")
        if native is not None:
            cur["digest"].update(f"{native.buttons},{native.stick_x},{native.stick_y},{info.get('consumed_tick')}\n"
                                 .encode("ascii"))

    def request_manual_preservation(self, note: str) -> None:
        self._manual_note = note

    def on_episode_end(self, recorder: EpisodeRecorder) -> None:
        cur = self._current or {"worker_episode": self.episodes_started, "steps": 0, "return": 0.0, "targets_broken": 0,
                                "termination_reason": None, "truncation_reason": None, "episode_dir": None,
                                "pid": None, "port": None, "startup": {}, "digest": hashlib.sha256()}
        self._current = {}
        status = recorder.status
        if status == EpisodeStatus.TERMINAL:
            end_reason = END_FALL if cur["termination_reason"] == TERMINATION_NATIVE_FAILURE else END_CLEAR
        elif status == EpisodeStatus.TRUNCATED:
            end_reason = END_HORIZON
        elif status == EpisodeStatus.FAILED:
            end_reason = END_LIFECYCLE_FAILURE
        else:
            end_reason = END_ABORTED
        finished = end_reason != END_ABORTED
        cleared = end_reason == END_CLEAR
        terminal = recorder.terminal
        ctp = terminal.get("completion_time_passed") if cleared else None
        cit = terminal.get("completion_input_tick") if cleared else None
        failure_outcome = self.env.last_failure_outcome if end_reason == END_LIFECYCLE_FAILURE else None
        artifact_dir = self.artifact_root / recorder.episode_id
        events: List[Dict[str, Any]] = []
        if finished:
            events = self.coordinator.decide({
                "rank": self.rank, "worker_episode": cur["worker_episode"], "episode_id": recorder.episode_id,
                "artifact_dir": portable_path(artifact_dir), "steps": cur["steps"],
                "targets_broken": cur["targets_broken"], "cleared": cleared,
                "completion_time_passed": ctp, "completion_input_tick": cit,
            })
            for e in events:
                recorder.preserve(e["reason"], e["note"])
            if self.preserve_all:
                recorder.preserve(PreservationReason.MANUAL, f"{self.role}: every episode of this set is kept")
                events.append({"event": "manual", "reason": PreservationReason.MANUAL.value, "note": self.role})
        if self._manual_note is not None:
            recorder.preserve(PreservationReason.MANUAL, self._manual_note)
            events.append({"event": "manual", "reason": PreservationReason.MANUAL.value, "note": self._manual_note})
            self._manual_note = None
        if recorder.events:
            events.append({"event": "anomaly", "reason": PreservationReason.ANOMALY.value,
                           "note": f"{len(recorder.events)} detector event(s)"})
        recorder.terminal["end_reason"] = end_reason
        recorder.terminal["termination_reason"] = cur["termination_reason"] if status == EpisodeStatus.TERMINAL else None
        recorder.terminal["cleared"] = cleared
        if failure_outcome is not None:
            recorder.terminal["failure_outcome"] = failure_outcome
        recorder.labels.update({
            "episode_status": status.value,
            "end_reason": end_reason,
            "termination_reason": recorder.terminal["termination_reason"],
            "truncation_reason": cur["truncation_reason"] if status == EpisodeStatus.TRUNCATED else None,
            "failure_outcome": failure_outcome,
            "episode_steps": cur["steps"],
            "episode_return": cur["return"],
            "targets_broken": cur["targets_broken"],
            "cleared": cleared,
            "completion_time_passed": ctp,
            "completion_input_tick": cit,
            "native_steps_at_end": self.native_steps,
            "sb3_num_timesteps_at_end": self.sb3_num_timesteps,
            "checkpoint_label": self.checkpoint_label,
            "preservation_events": [e["event"] for e in events],
            "native_action_digest": cur["digest"].hexdigest(),
        })
        preserved = recorder.preserved
        # Disposition of the M2 per-episode directory (save, result JSON, process log).
        if preserved:
            decision = "kept_with_preserved_artifact"
        elif end_reason == END_LIFECYCLE_FAILURE and self.failed_dirs_kept < self.retain_failed_cap:
            decision = "kept_failure_debug"
            self.failed_dirs_kept += 1
        else:
            decision = "deleted_ordinary" if end_reason != END_LIFECYCLE_FAILURE else "deleted_failure_over_cap"
        record = {"kind": "episode_dir", "rank": self.rank, "worker_episode": cur["worker_episode"],
                  "episode_id": recorder.episode_id, "end_reason": end_reason,
                  "episode_dir": portable_path(cur["episode_dir"]), "decision": decision,
                  "artifact_dir": portable_path(artifact_dir) if preserved else None,
                  "preservation_reasons": [m.reason for m in recorder.marks]}
        if decision.startswith("deleted"):
            self.env.queue_deletion(cur["episode_dir"], record)
        self._ledger(record)
        # Counters and the summary handed to the parent with this step's info.
        self.end_counts[end_reason] = self.end_counts.get(end_reason, 0) + 1
        if failure_outcome:
            self.failure_outcomes[failure_outcome] = self.failure_outcomes.get(failure_outcome, 0) + 1
        self.anomaly_events += len(recorder.events)
        if preserved:
            self.preserved += 1
        else:
            self.discarded += 1
        if finished:
            self.finished_returns.append(cur["return"])
        final = recorder.final_observation
        self._pending_summary = {
            "rank": self.rank,
            "role": self.role,
            "worker_episode": cur["worker_episode"],
            "episode_id": recorder.episode_id,
            "status": status.value,
            "end_reason": end_reason,
            "termination_reason": recorder.terminal["termination_reason"],
            "truncation_reason": cur["truncation_reason"] if status == EpisodeStatus.TRUNCATED else None,
            "failure_outcome": failure_outcome,
            "steps": cur["steps"],
            "return": cur["return"],
            "targets_broken": cur["targets_broken"],
            "cleared": cleared,
            "completion_time_passed": ctp,
            "completion_input_tick": cit,
            "last_consumed_tick": terminal.get("last_consumed_tick"),
            "anomaly_events": len(recorder.events),
            "preservation_events": [e["event"] for e in events],
            "preserved": preserved,
            "artifact_dir": portable_path(artifact_dir) if preserved else None,
            "episode_dir_decision": decision,
            "native_action_digest": cur["digest"].hexdigest(),
            "terminal_native_observation": dataclasses.asdict(final) if final is not None else None,
            "pid": cur["pid"],
            "port": cur["port"],
            "startup": cur["startup"],
            "sb3_num_timesteps_at_end": self.sb3_num_timesteps,
            "checkpoint_label": self.checkpoint_label,
        }

    def pop_summary(self) -> Optional[Dict[str, Any]]:
        s, self._pending_summary = self._pending_summary, None
        if s is not None:
            self.summaries_emitted += 1
        return s

    def _ledger(self, record: Mapping[str, Any]) -> None:
        with open(self.ledger_path, "a", encoding="utf-8", newline="\n") as fp:
            fp.write(json.dumps(dict(record, time_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
                                separators=(",", ":")) + "\n")


# -- outer wrappers ---------------------------------------------------------------------------------------


class EpisodeStatsWrapper(gym.Wrapper):
    """SB3-Monitor-compatible episode statistics without importing SB3 in the worker.

    At the end of every episode info["episode"] = {"r": return (6 decimals),
    "l": length, "t": seconds since construction}, which is exactly what
    SB3's ep_info_buffer reads from Monitor."""

    def __init__(self, env: Any):
        super().__init__(env)
        self._t0 = time.time()
        self._return = 0.0
        self._length = 0

    def reset(self, **kwargs):
        self._return = 0.0
        self._length = 0
        return self.env.reset(**kwargs)

    def step(self, action):
        observation, reward, terminated, truncated, info = self.env.step(action)
        self._return += float(reward)
        self._length += 1
        if terminated or truncated:
            info["episode"] = {"r": round(self._return, 6), "l": self._length, "t": round(time.time() - self._t0, 6)}
        return observation, reward, terminated, truncated, info


_STEP_INFO_KEYS = ("episode", "termination_reason", "truncation_reason", "failure_outcome")


class M7WorkerWrapper(gym.Wrapper):
    """Outermost worker wrapper: small picklable infos, error context, control methods, test faults."""

    def __init__(self, env: Any, *, spec: "WorkerSpec", base: M7BattleShipBTTEnv, tracker: M7EpisodeTracker,
                 recording: EpisodeRecordingWrapper):
        super().__init__(env)
        self.worker_spec = spec  # gymnasium.Wrapper already owns a read-only `spec` property
        self.base = base
        self.tracker = tracker
        self.recording = recording
        self.service_hist = LatencyHistogram()
        self.reset_times: List[float] = []
        self.step_in_episode = 0
        self.closed = False

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        t0 = time.perf_counter()
        observation, info = self.env.reset(seed=seed, options=options)
        dt = time.perf_counter() - t0
        self.reset_times.append(dt)
        self.step_in_episode = 0
        slim = {"m7_rank": self.worker_spec.rank, "m7_reset_s": dt, "pid": info.get("pid"), "port": info.get("port"),
                "m7_startup": info.get("m7_startup")}
        return observation, slim

    def step(self, action):
        self.step_in_episode += 1
        fault = self.worker_spec.fault
        if fault and fault.get("raise_in_step") and self.tracker.episodes_started == int(fault["raise_in_step"][0]) \
                and self.step_in_episode == int(fault["raise_in_step"][1]):
            raise M7InjectedFault(f"injected worker fault (rank {self.worker_spec.rank}, worker episode "
                                  f"{self.tracker.episodes_started}, step {self.step_in_episode})")
        t0 = time.perf_counter()
        observation, reward, terminated, truncated, info = self.env.step(action)
        dt = time.perf_counter() - t0
        self.service_hist.add(dt)
        slim: Dict[str, Any] = {"m7_rank": self.worker_spec.rank, "m7_service_s": dt}
        for key in _STEP_INFO_KEYS:
            if key in info:
                slim[key] = info[key]
        summary = self.tracker.pop_summary()
        if summary is not None:
            slim["m7_episode"] = summary
        return observation, reward, terminated, truncated, slim

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.env.close()

    # -- control methods (SubprocVecEnv env_method) -------------------------------------------------------

    def set_training_context(self, num_timesteps: Optional[int], checkpoint_label: Optional[str]) -> bool:
        self.tracker.sb3_num_timesteps = None if num_timesteps is None else int(num_timesteps)
        self.tracker.checkpoint_label = checkpoint_label
        return True

    def request_manual_preservation(self, note: str) -> bool:
        self.tracker.request_manual_preservation(note)
        return True

    def error_context(self) -> Dict[str, Any]:
        return {"worker_episode": self.tracker.episodes_started, "step_in_episode": self.step_in_episode,
                "game_pid": self.base.episode.pid if self.base.episode is not None else None,
                "phase": self.base.phase}

    def worker_report(self) -> Dict[str, Any]:
        own = None
        if self.base.metrics is not None:
            own = self.base.metrics.sample(os.getpid())
        samples = self.base.process_samples + ([self.base._current_sample] if self.base._current_sample else [])
        return {
            "rank": self.worker_spec.rank,
            "role": self.worker_spec.role,
            "worker_pid": os.getpid(),
            "episodes_started": self.tracker.episodes_started,
            "native_steps": self.tracker.native_steps,
            "end_counts": dict(self.tracker.end_counts),
            "failure_outcomes": dict(self.tracker.failure_outcomes),
            "request_timeouts": int(self.tracker.failure_outcomes.get(EpisodeOutcome.EPISODE_TIMEOUT.value, 0)),
            "transport_failures": int(self.tracker.failure_outcomes.get(EpisodeOutcome.TRANSPORT_FAILURE.value, 0)),
            "preserved": self.tracker.preserved,
            "discarded": self.tracker.discarded,
            "artifacts_written": [portable_path(p) for p in self.recording.written],
            "anomaly_events": self.tracker.anomaly_events,
            "failed_dirs_kept": self.tracker.failed_dirs_kept,
            "resets": self.base.reset_count,
            "reset_times_s": [round(t, 4) for t in self.reset_times],
            "startup_attempts": list(self.base.startup_attempt_log),
            "startup_failures": [a for a in self.base.startup_attempt_log if a["outcome"] != "fresh"],
            "native_step_hist": self.base.native_hist.to_json(),
            "service_hist": self.service_hist.to_json(),
            "game_process_samples": samples,
            "episode_dir_deletions": list(self.base.deletion_log),
            "worker_process": own,
        }


# -- worker construction ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkerSpec:
    """Everything one worker needs; plain data, picklable with the standard pickle (spawn-safe)."""

    rank: int
    run_id: str
    role: str                         # training | evaluation | random_baseline | test
    worker_dir: str                   # absolute: <run>/workers/wNN (runtime/, episodes/, artifacts/ below)
    coordination_dir: str             # absolute: shared RunCoordinator directory
    executable: str
    horizon: int = M7_HORIZON
    base_seed: int = 0
    extra_env: Tuple[Tuple[str, str], ...] = (("SSB64_RL_NO_RENDER", "1"), ("SSB64_RAPHNET_DISABLE", "1"))
    reward: Tuple[float, float, float] = (DEFAULT_REWARD_CONFIG.target_broken, DEFAULT_REWARD_CONFIG.per_step,
                                          DEFAULT_REWARD_CONFIG.clear_bonus)
    position_delta_threshold: float = DEFAULT_POSITION_DELTA_THRESHOLD
    retain_failed_cap: int = 20
    startup_attempts: int = 3
    startup_timeout: float = 20.0
    ready_timeout: float = 60.0
    request_timeout: float = 10.0
    exit_timeout: float = 30.0
    detect_native_failure: bool = True
    preserve_all: bool = False
    port_block_base: int = PORT_BLOCK_BASE
    port_block_size: int = PORT_BLOCK_SIZE
    fault: Optional[Dict[str, Any]] = None      # test only: {"raise_in_step": (worker_episode, step)}
    squat_first_attempt: Optional[str] = None   # test only: "preflight" | "post_launch" (see _PortSquatter)

    @property
    def worker_seed(self) -> int:
        return int(self.base_seed) + int(self.rank)

    def paths(self) -> Dict[str, Path]:
        root = Path(self.worker_dir)
        return {"root": root, "runtime": root / "runtime", "episodes": root / "episodes",
                "artifacts": root / "artifacts", "ledger": root / "dispositions.jsonl"}


class _PortSquatter:
    """Test hook for the startup-retry regression: another application takes the first claimed port.

    mode "preflight": bound right after the M7 probe, so M2's own pre-launch check refuses the port
    (no process is started). mode "post_launch": bound ~0.15 s later from a thread, i.e. after M2 has
    launched BattleShip but before its transport binds, so the native bind fails, the attempt ends
    as a startup failure and M2/M3 must kill and reap the launched process before the retry."""

    def __init__(self, mode: str) -> None:
        if mode not in ("preflight", "post_launch"):
            raise ValueError(mode)
        self.mode = mode
        self.sockets: List[Any] = []
        self.squatted: List[int] = []

    def _bind(self, port: int) -> None:
        import socket

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
            s.listen(4)
        except OSError:
            s.close()
            return
        self.sockets.append(s)
        self.squatted.append(port)

    def __call__(self, attempt: int, port: int) -> None:
        if attempt != 1 or self.squatted or getattr(self, "_armed", False):
            return  # only the very first attempt of the worker's first reset
        self._armed = True
        if self.mode == "preflight":
            self._bind(port)
            return
        import threading

        threading.Timer(0.15, self._bind, args=(port,)).start()


def build_worker_env(spec: WorkerSpec) -> M7WorkerWrapper:
    """The full worker stack for one rank. Launches nothing until reset()."""
    random.seed(spec.worker_seed)            # Python-side reproducibility only; never reaches the game
    np.random.seed(spec.worker_seed % (2 ** 32))
    paths = spec.paths()
    if not (paths["runtime"] / "runtime_manifest.json").is_file():
        raise RuntimeError(f"worker runtime directory not prepared: {paths['runtime']}")
    for key in ("episodes", "artifacts"):
        paths[key].mkdir(parents=True, exist_ok=True)
    launch = LaunchConfig(
        executable=Path(spec.executable),
        working_dir=paths["runtime"],
        run_root=paths["episodes"],
        startup_timeout=spec.startup_timeout,
        ready_timeout=spec.ready_timeout,
        request_timeout=spec.request_timeout,
        exit_timeout=spec.exit_timeout,
        extra_env=dict(spec.extra_env),
    )
    ports = PortCandidates(spec.rank, spec.port_block_base, spec.port_block_size)
    base = M7BattleShipBTTEnv(launch, max_episode_steps=spec.horizon, rank=spec.rank, ports=ports,
                              startup_attempts=spec.startup_attempts, detect_native_failure=spec.detect_native_failure,
                              port_claim_hook=_PortSquatter(spec.squat_first_attempt) if spec.squat_first_attempt else None)
    tracker = M7EpisodeTracker(run_id=spec.run_id, role=spec.role, rank=spec.rank,
                               coordinator=RunCoordinator(spec.coordination_dir), artifact_root=paths["artifacts"],
                               ledger_path=paths["ledger"], env=base, reward_config=RewardV1Config(*spec.reward),
                               retain_failed_cap=spec.retain_failed_cap, preserve_all=spec.preserve_all)
    rewarded = M7RewardWrapper(base, RewardV1Config(*spec.reward), tracker)
    recording = EpisodeRecordingWrapper(rewarded, paths["artifacts"],
                                        detectors=[PositionDeltaDetector(spec.position_delta_threshold)],
                                        labels=tracker.labels_for_new_episode, on_episode_end=tracker.on_episode_end,
                                        targets_total=TARGETS_TOTAL)
    track1 = Track1PolicyWrapper(recording)
    stats = EpisodeStatsWrapper(track1)
    return M7WorkerWrapper(stats, spec=spec, base=base, tracker=tracker, recording=recording)


class WorkerFactory:
    """Top-level, picklable environment factory (no closures): one per rank."""

    def __init__(self, spec: WorkerSpec):
        self.spec = spec

    def __call__(self) -> M7WorkerWrapper:
        return build_worker_env(self.spec)


# -- the worker process -------------------------------------------------------------------------------------


def _get_wrapper_attr(env: Any, name: str) -> Any:
    getter = getattr(env, "get_wrapper_attr", None)
    if getter is not None:
        return getter(name)
    return getattr(env, name)


def _is_wrapped(env: Any, wrapper_class: Any) -> bool:
    current = env
    while isinstance(current, gym.Wrapper):
        if isinstance(current, wrapper_class):
            return True
        current = current.env
    return False


def m7_worker(remote: Any, parent_remote: Any, env_factory: Callable[[], Any]) -> None:
    """SubprocVecEnv worker loop with SB3's protocol and M7's cleanup guarantees.

    Same commands and replies as stable_baselines3's _worker (step with
    auto-reset, terminal_observation, TimeLimit.truncated; reset; get_spaces;
    env_method; get/set/has_attr; is_wrapped; close). Differences: Ctrl+C is
    ignored here (the parent coordinates shutdown), a failing command is
    reported to the parent as a WorkerFailure (rank, command, traceback,
    episode context) instead of silently ending the process, and the
    environment is closed in `finally` on every exit path."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, signal.SIG_IGN)
    parent_remote.close()
    env = None
    rank = getattr(getattr(env_factory, "spec", None), "rank", -1)
    try:
        try:
            env = env_factory()
        except Exception as exc:  # noqa: BLE001 - reported as the reply to the parent's first command
            failure = WorkerFailure(rank=rank, command="construct", exc_type=type(exc).__name__,
                                    message=str(exc)[:2000], traceback=traceback.format_exc()[-8000:],
                                    context={"env_closed": True})
            try:
                remote.send(failure)
            except (OSError, EOFError):
                pass
            return
        while True:
            try:
                cmd, data = remote.recv()
            except (EOFError, OSError):
                break  # parent gone: close below
            try:
                if cmd == "step":
                    observation, reward, terminated, truncated, info = env.step(data)
                    done = terminated or truncated
                    info["TimeLimit.truncated"] = truncated and not terminated
                    reset_info: Dict[str, Any] = {}
                    if done:
                        info["terminal_observation"] = observation
                        observation, reset_info = env.reset()
                    remote.send((observation, reward, done, info, reset_info))
                elif cmd == "reset":
                    seed, options = data
                    kwargs = {"options": options} if options else {}
                    observation, reset_info = env.reset(seed=seed, **kwargs)
                    remote.send((observation, reset_info))
                elif cmd == "close":
                    report = None
                    try:
                        report = env.worker_report() if hasattr(env, "worker_report") else None
                    finally:
                        env.close()
                        closed_env, env = env, None
                    if report is not None:
                        report["closed_cleanly"] = True
                        report["episode_dir_deletions"] = list(closed_env.base.deletion_log)
                    remote.send(("closed", report))
                    break
                elif cmd == "get_spaces":
                    remote.send((env.observation_space, env.action_space))
                elif cmd == "env_method":
                    method = _get_wrapper_attr(env, data[0])
                    remote.send(method(*data[1], **data[2]))
                elif cmd == "get_attr":
                    remote.send(_get_wrapper_attr(env, data))
                elif cmd == "has_attr":
                    try:
                        _get_wrapper_attr(env, data)
                        remote.send(True)
                    except AttributeError:
                        remote.send(False)
                elif cmd == "set_attr":
                    remote.send(setattr(env, data[0], data[1]))  # type: ignore[func-returns-value]
                elif cmd == "is_wrapped":
                    remote.send(_is_wrapped(env, data))
                elif cmd == "render":
                    remote.send(None)
                else:
                    raise NotImplementedError(f"`{cmd}` is not implemented in the M7 worker")
            except Exception as exc:  # noqa: BLE001 - reported to the parent with context, then this worker ends
                context: Dict[str, Any] = {}
                try:
                    context = env.error_context() if env is not None and hasattr(env, "error_context") else {}
                except Exception:  # noqa: BLE001
                    pass
                close_error = None
                try:
                    if env is not None:
                        env.close()
                        env = None
                except Exception as close_exc:  # noqa: BLE001
                    close_error = f"{type(close_exc).__name__}: {close_exc}"
                context["env_closed"] = env is None
                context["close_error"] = close_error
                failure = WorkerFailure(rank=rank, command=cmd, exc_type=type(exc).__name__, message=str(exc)[:2000],
                                        traceback=traceback.format_exc()[-8000:], context=context)
                try:
                    remote.send(failure)
                except (OSError, EOFError):
                    pass
                break
    finally:
        if env is not None:
            try:
                env.close()
            except Exception:  # noqa: BLE001 - last-resort path; the job object is the backstop
                pass
        try:
            remote.close()
        except OSError:
            pass
