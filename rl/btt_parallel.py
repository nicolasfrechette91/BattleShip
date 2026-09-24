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
import threading
import time
import traceback
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import gymnasium as gym
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))

from battleship_client import BattleShipError, Observation, StepState  # noqa: E402
from battleship_env import DEFAULT_EXECUTABLE, BattleShipBTTEnv, BattleShipEnvError, observation_to_gym  # noqa: E402
from battleship_process import BattleShipEpisode, EpisodeFailure, EpisodeOutcome, LaunchConfig  # noqa: E402
from m7_standby import (  # noqa: E402
    MAX_STANDBY_COUNT,
    STANDBY_CONTRACT,
    AcquireResult,
    LaunchOutcome,
    StandbyManager,
    StandbyState,
    verify_readiness,
)
from btt_learning import (  # noqa: E402
    REWARD_CONTRACT,
    TARGETS_TOTAL,
    RewardV1Wrapper,
    Track1PolicyWrapper,
    contracts as m5_contracts,
    live_targets,
)
from btt_rewards import REWARD_V1, RewardContract, reward_step  # noqa: E402
from m7_runtime import (  # noqa: E402
    IS_WINDOWS,
    PORT_BLOCK_BASE,
    PORT_BLOCK_SIZE,
    PortCandidates,
    pid_alive,
    portable_path,
    prepare_worker_runtime,
    remove_worker_runtime,
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

# M7c standby lifecycle (rl/m7_standby.py). Reset modes recorded in info["m7_startup"]["mode"], artifact labels
# and episode summaries: how the active process of an episode came to exist.
STARTUP_MODE_COLD_START = "cold_start"            # standby off, or the worker's very first process
STARTUP_MODE_STANDBY_PROMOTED = "standby_promoted"  # a ready standby became active (no launch waited for)
STARTUP_MODE_COLD_FALLBACK = "cold_fallback"      # standby on, but none usable: synchronous fresh launch
STANDBY_STATUS_FLAGS = {"SSB64_RL_NO_RENDER": "no_render", "SSB64_RAPHNET_DISABLE": "raphnet_disabled"}


@dataclass(frozen=True)
class StandbySettings:
    """M7c lifecycle configuration of one worker (plain data, picklable)."""

    preboot: bool = False
    count: int = 0                     # 0 or 1 in M7c
    wait_timeout: float = 120.0        # bound on waiting for a launch in flight at reset (then cancel + cold fallback)

    def __post_init__(self) -> None:
        if self.count < 0 or self.count > MAX_STANDBY_COUNT:
            raise ValueError(f"standby_count must be 0..{MAX_STANDBY_COUNT}")
        if bool(self.preboot) != (self.count == 1):
            raise ValueError("standby_preboot = true requires standby_count = 1 (and false requires 0)")
        if self.wait_timeout <= 0:
            raise ValueError("standby_wait_timeout must be > 0")

    @property
    def enabled(self) -> bool:
        return bool(self.preboot) and self.count >= 1

    def to_json(self) -> Dict[str, Any]:
        return {"contract": STANDBY_CONTRACT, "standby_preboot": bool(self.preboot), "standby_count": int(self.count),
                "standby_wait_timeout_s": float(self.wait_timeout), "max_processes_per_worker": 1 + int(self.count)}


def expected_status_flags(extra_env: Mapping[str, str]) -> Dict[str, bool]:
    """The status flags (M6 no_render / raphnet_disabled) every process of this worker must report."""
    return {flag: extra_env.get(var) == "1" for var, flag in STANDBY_STATUS_FLAGS.items()}


def is_native_failure(observation: Observation, state: StepState) -> bool:
    """The btt_native_failure_v1 rule on one post-update M1c step result."""
    return (
        state != StepState.EPISODE_ENDED
        and int(observation.btt_active) == 1
        and int(observation.game_status) == GAME_STATUS_END
        and int(observation.targets_remaining) > 0
    )


def m7_contracts(horizon: int, reward: RewardContract = REWARD_V1) -> Dict[str, Any]:
    """Every contract a checkpoint depends on (compared on load/resume).

    M7b: `reward_contract` / `reward_constants` describe the actual reward
    contract of the run (btt_reward_v1 unless configured otherwise); the M5
    identifiers of the other contracts are unchanged."""
    c = dict(m5_contracts())
    c.update({
        "reward_contract": reward.contract,
        "failure_contract": FAILURE_CONTRACT,
        "failure_rule": "first post-update observation with game_status == 5, btt_active == 1, "
                        "targets_remaining > 0 and no native EpisodeEnded -> terminated, reason native_failure",
        "termination_reasons": [TERMINATION_NATIVE_CLEAR, TERMINATION_NATIVE_FAILURE],
        "truncation_reasons": ["max_episode_steps", "episode_failure"],
        "horizon_native_ticks": int(horizon),
        "reward_constants": reward.to_json(),
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
    - M7c standby lifecycle (rl/m7_standby.py) when `standby.enabled`: after
      every reset the next process boots in a background thread; the next
      reset promotes it (cached tick-0 observation, no hidden action) or
      falls back to the synchronous launch above. In standby mode every
      launch gets its own generation runtime directory (private config /
      imgui / logs) so two processes of one worker never share a mutable
      file; with standby off the M7a layout (one runtime directory per
      worker) is unchanged.
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
        standby: Optional[StandbySettings] = None,
        generation_runtime_root: Optional[Path] = None,
        profile: Optional[Mapping[str, Any]] = None,
        standby_fault: Optional[Mapping[str, Any]] = None,
        retain_failed_cap: int = 20,
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
        # M7c
        self.standby_settings = standby or StandbySettings()
        self.expected_flags = expected_status_flags(dict(launch_config.extra_env))
        self.profile: Dict[str, Any] = dict(profile or {})
        self.standby_fault = dict(standby_fault or {})
        self.retain_failed_cap = int(retain_failed_cap)
        self._base_launch = self.launch_config          # M3 may have added a run_root; keep that version as the base
        self._generation = 0                            # unique per launch attempt (cold or standby) of this worker
        self._port_lock = threading.Lock()
        self._dir_lock = threading.Lock()
        self._runtime_by_episode_dir: Dict[str, Optional[str]] = {}   # episode dir -> generation runtime dir
        self._standby_dirs: Dict[int, List[Tuple[Optional[str], Optional[str]]]] = {}  # generation -> attempt dirs
        self._squat_sockets: List[Any] = []
        self.standby_failed_dirs_kept = 0
        self.ledger_hook: Optional[Callable[[Dict[str, Any]], None]] = None
        self.max_concurrent_processes = 0
        self.retire_s: List[float] = []
        self.last_reset_timing: Dict[str, Any] = {}
        self.standby_events: List[Dict[str, Any]] = []
        self.last_standby_close: Optional[Dict[str, Any]] = None
        self.standby: Optional[StandbyManager] = None
        if self.standby_settings.enabled:
            if generation_runtime_root is None:
                raise ValueError("standby mode needs generation_runtime_root")
            self.generation_runtime_root: Optional[Path] = Path(generation_runtime_root)
            self.standby = StandbyManager(rank=self.rank, launch_fn=self._standby_launch,
                                          startup_attempts=self.startup_attempts,
                                          join_timeout=float(launch_config.request_timeout) + float(launch_config.exit_timeout) + 5.0,
                                          request_timeout=float(launch_config.request_timeout))
        else:
            self.generation_runtime_root = Path(generation_runtime_root) if generation_runtime_root else None

    # -- generations, ports and directories -------------------------------------------------------------------

    def _next_generation(self) -> int:
        with self._dir_lock:
            self._generation += 1
            return self._generation

    def _claim_port(self) -> Tuple[int, List[int]]:
        with self._port_lock:
            return self.ports.claim()

    def _prepare_generation_runtime(self, generation: int, attempt: int) -> Path:
        """A private runtime directory (config copy, imgui copy, .tcc junction) for one launch attempt."""
        assert self.generation_runtime_root is not None
        d = self.generation_runtime_root / f"g{generation:04d}_a{attempt}"
        prepare_worker_runtime(d, Path(self._base_launch.executable))
        return d

    def _launch_config_for(self, port: int, runtime_dir: Optional[Path]) -> LaunchConfig:
        if runtime_dir is None:
            return replace(self._base_launch, port=port)
        return replace(self._base_launch, port=port, working_dir=runtime_dir)

    def _note_dirs(self, episode_dir: Optional[str], runtime_dir: Optional[Path]) -> None:
        if episode_dir is not None:
            with self._dir_lock:
                self._runtime_by_episode_dir[str(episode_dir)] = str(runtime_dir) if runtime_dir else None

    def runtime_dir_for(self, episode_dir: Optional[os.PathLike | str]) -> Optional[str]:
        if episode_dir is None:
            return None
        with self._dir_lock:
            return self._runtime_by_episode_dir.get(str(episode_dir))

    def live_processes(self) -> int:
        """Live BattleShip processes this worker owns right now (active + standby); never more than 2."""
        n = 1 if self.owned_process_alive else 0
        if self.standby is not None:
            n += self.standby.live_standby_processes()
        return n

    def _note_concurrency(self) -> int:
        n = self.live_processes()
        if n > self.max_concurrent_processes:
            self.max_concurrent_processes = n
        return n

    # -- reset: promotion, cold start, cold fallback -----------------------------------------------------------

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        t_reset = time.perf_counter()
        retire = self._dispose_episode()      # the previous process is gone before its directory is touched
        retire_s = time.perf_counter() - t_reset
        if retire is not None:
            self.retire_s.append(retire_s)
        self._flush_process_sample()
        self.drain_deletions()
        self.reset_count += 1
        self.last_failure_outcome = None
        timing: Dict[str, Any] = {"retire_s": round(retire_s, 4), "retire_action": retire, "standby_wait_s": 0.0,
                                  "promotion_s": None}
        if self.standby is None:
            observation, info = self._cold_reset(seed, options, t_reset, mode=STARTUP_MODE_COLD_START, fallback=None)
        else:
            acquired = self.standby.acquire(self.standby_settings.wait_timeout, targets_total=TARGETS_TOTAL)
            timing["standby_wait_s"] = round(acquired.waited_s, 4)
            if acquired.kind == "ready":
                assert acquired.record is not None and acquired.observe is not None
                t0 = time.perf_counter()
                try:
                    observation, info = self._promote(acquired, seed, t_reset)
                except BaseException:
                    if self.standby.state == StandbyState.PROMOTING:
                        self.standby.abandon_promotion("promotion raised in the worker")
                    raise
                timing["promotion_s"] = round(time.perf_counter() - t0, 4)
            else:
                rec = acquired.record
                fallback = {"reason": acquired.kind, "generation": rec.generation if rec else None,
                            "standby_attempts": list(rec.attempts) if rec else [],
                            "standby_error": rec.error if rec else None, "lost_reason": rec.lost_reason if rec else None}
                if acquired.kind == "starting_error":
                    raise RuntimeError(f"worker {self.rank}: standby launcher raised unexpectedly: {rec.error if rec else None}")
                if rec is not None:
                    self._dispose_standby_record(rec.generation, rec.outcome)
                first = acquired.kind == "none" and self.reset_count == 1
                mode = STARTUP_MODE_COLD_START if first else STARTUP_MODE_COLD_FALLBACK
                if not first:
                    self.standby_events.append({"reset": self.reset_count, "event": acquired.kind, **fallback})
                observation, info = self._cold_reset(seed, options, t_reset, mode=mode, fallback=None if first else fallback)
            # The active process exists with its own generation; only now does the next standby start.
            self._launch_standby()
        timing["reset_s"] = round(time.perf_counter() - t_reset, 4)
        self.last_reset_timing = timing
        assert self.current_startup is not None
        self.current_startup.update({"retire_s": timing["retire_s"], "standby_wait_s": timing["standby_wait_s"],
                                     "promotion_s": timing["promotion_s"], "reset_s": timing["reset_s"],
                                     "live_processes_after_reset": self._note_concurrency()})
        info["m7_startup"] = self.current_startup
        return observation, info

    def _cold_reset(self, seed: Optional[int], options: Optional[dict], t_reset: float, *, mode: str,
                    fallback: Optional[Dict[str, Any]]):
        attempts: List[Dict[str, Any]] = []
        for attempt in range(1, self.startup_attempts + 1):
            port, busy = self._claim_port()
            if self.port_claim_hook is not None:
                self.port_claim_hook(attempt, port)  # test hook only (simulates a squatter after the probe)
            generation = self._next_generation()
            runtime_dir = self._prepare_generation_runtime(generation, attempt) if self.standby is not None else None
            self.launch_config = self._launch_config_for(port, runtime_dir)
            self._episode_index = generation - 1      # M3 increments once per launch: the episode index IS the generation
            t_attempt = time.perf_counter()
            try:
                observation, info = super().reset(seed=seed if attempt == 1 else None, options=options)
            except EpisodeFailure as exc:
                pid = exc.diagnostics.get("pid")
                record = {"reset": self.reset_count, "generation": generation, "attempt": attempt, "port": port,
                          "busy_ports_skipped": busy, "outcome": exc.outcome.value,
                          "message": exc.message.splitlines()[0][:300], "pid": pid,
                          "elapsed_s": round(time.perf_counter() - t_attempt, 3),
                          "process_alive_after": pid_alive(pid), "episode_dir": exc.diagnostics.get("episode_dir"),
                          "runtime_dir": str(runtime_dir) if runtime_dir else None}
                attempts.append(record)
                self.startup_attempt_log.append(record)
                self._note_dirs(exc.diagnostics.get("episode_dir"), runtime_dir)
                if exc.outcome in NON_RETRYABLE_STARTUP:
                    raise M7StartupError(self.rank, self.reset_count, attempts) from exc
                continue
            elapsed = time.perf_counter() - t_attempt
            record = {"reset": self.reset_count, "generation": generation, "attempt": attempt, "port": port,
                      "busy_ports_skipped": busy, "outcome": "fresh", "pid": info.get("pid"), "elapsed_s": round(elapsed, 3),
                      "runtime_dir": str(runtime_dir) if runtime_dir else None}
            attempts.append(record)
            self.startup_attempt_log.append(record)
            self._note_dirs(info.get("episode_dir"), runtime_dir)
            self._time_client()
            self._current_sample = None
            self.current_startup = {"mode": mode, "generation": generation, "attempts": len(attempts),
                                    "failed_attempts": len(attempts) - 1, "ports": [a["port"] for a in attempts],
                                    "reset_s": round(time.perf_counter() - t_reset, 3), "fresh_attempt_s": round(elapsed, 3),
                                    "failures": [a for a in attempts if a["outcome"] != "fresh"],
                                    "runtime_dir": str(runtime_dir) if runtime_dir else None,
                                    "lifecycle": self.standby_settings.to_json(), "fallback": fallback,
                                    "standby_startup_s": None, "ready_before_promotion_s": None}
            return observation, info
        raise M7StartupError(self.rank, self.reset_count, attempts)

    def _promote(self, acquired: AcquireResult, seed: Optional[int], t_reset: float):
        """Install a verified ready standby as the active process: no launch, no reset op, no step, no hidden action."""
        assert self.standby is not None
        gym.Env.reset(self, seed=seed)   # exactly what M3's reset does first (Python-side RNG only)
        if self._phase == "closed":
            raise BattleShipEnvError("reset() after close()")
        rec = acquired.record
        assert rec is not None and rec.episode is not None and acquired.observe is not None
        if rec.profile != self.profile:
            raise RuntimeError(f"worker {self.rank}: standby generation {rec.generation} was booted for another profile "
                               f"({rec.profile} vs {self.profile})")
        episode = rec.episode
        observe = acquired.observe
        self._require_initial(0, observe, episode)     # M3's own tick-0 contract, on the fresh re-observation
        self._steps = 0
        self.last_step_result = None
        self.last_episode_exit = None
        self._episode_index = rec.generation
        self._episode = episode
        self.launch_config = episode.config
        self._phase = "active"
        self.last_observe = observe
        self._time_client()
        self._current_sample = None
        self._sample_process()
        resource = dict(self._current_sample) if self._current_sample else None
        promoted = self.standby.promoted(resource)
        self.standby_events.append({"reset": self.reset_count, "event": "promoted", "generation": promoted.generation,
                                    "standby_startup_s": promoted.startup_s,
                                    "ready_before_promotion_s": promoted.ready_before_promotion_s,
                                    "exposed_wait_s": round(acquired.waited_s, 4)})
        record = {"reset": self.reset_count, "generation": promoted.generation, "attempt": len(promoted.attempts),
                  "port": episode.port, "outcome": "promoted", "pid": episode.pid, "elapsed_s": promoted.startup_s,
                  "runtime_dir": promoted.runtime_dir, "standby": True}
        self.startup_attempt_log.append(record)
        self.current_startup = {"mode": STARTUP_MODE_STANDBY_PROMOTED, "generation": promoted.generation,
                                "attempts": len(promoted.attempts), "failed_attempts": len(promoted.attempts) - 1,
                                "ports": [a["port"] for a in promoted.attempts],
                                "reset_s": round(time.perf_counter() - t_reset, 3), "fresh_attempt_s": None,
                                "failures": [a for a in promoted.attempts if a["outcome"] != "fresh"],
                                "runtime_dir": promoted.runtime_dir, "lifecycle": self.standby_settings.to_json(),
                                "fallback": None, "standby_startup_s": promoted.startup_s,
                                "ready_before_promotion_s": promoted.ready_before_promotion_s,
                                "readiness_proof": promoted.proof, "standby_ready_utc": promoted.ready_utc}
        info = self._base_info(observe.observation, observe.state, observe.state_name, observe.step_count)
        info["consumed_tick"] = None
        return observation_to_gym(observe.observation), info

    def _launch_standby(self) -> None:
        if self.standby is None or self.standby.state != StandbyState.NO_STANDBY:
            return
        generation = self._next_generation()
        self.standby.launch(generation, profile=self.profile)
        self._note_concurrency()

    # -- background launch (runs in the StandbyManager thread) -------------------------------------------------------

    def _standby_fault_for(self, generation: int, attempt: int) -> Optional[str]:
        f = self.standby_fault
        if not f:
            return None
        gens = f.get("generations")
        if gens is not None and generation not in gens:
            return None
        if f.get("squat_attempts") == "all" or attempt in (f.get("squat_attempts") or []):
            return "squat_post_launch"
        if attempt in (f.get("startup_timeout_attempts") or []):
            return "startup_timeout"
        return None

    def _squat(self, port: int) -> None:
        import socket

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
            s.listen(4)
            self._squat_sockets.append(s)
        except OSError:
            s.close()

    def _standby_launch(self, generation: int, attempt: int, manager: StandbyManager) -> LaunchOutcome:
        port, busy = self._claim_port()
        fault = self._standby_fault_for(generation, attempt)
        runtime_dir = self._prepare_generation_runtime(generation, attempt)
        cfg = self._launch_config_for(port, runtime_dir)
        if fault == "startup_timeout":
            # a loopback connect to a not-yet-listening port can block until the game listens: bound it too
            cfg = replace(cfg, startup_timeout=0.3, request_timeout=0.05)
        episode = BattleShipEpisode(cfg, index=generation)
        episode.m7_busy_ports_skipped = busy  # type: ignore[attr-defined]
        with self._dir_lock:
            self._standby_dirs.setdefault(generation, [])
        try:
            episode.launch()
            manager.note_inflight(episode.process, episode.pid, port)
            assert episode.paths is not None
            with self._dir_lock:
                self._standby_dirs[generation].append((str(episode.paths.directory), str(runtime_dir)))
            self._note_dirs(str(episode.paths.directory), runtime_dir)
            self._note_concurrency()
            if fault == "squat_post_launch":
                self._squat(port)   # taken before the game binds: its bind fails, the attempt ends as a startup failure
            episode.wait_for_transport()
            episode.wait_for_fresh_episode()
            assert episode.client is not None
            try:
                observe = episode.client.observe()
                raw = episode.client.request("status")
            except BattleShipError as exc:
                raise episode.classify_step_failure(exc) from exc
            flags = {k: raw.get(k) for k in self.expected_flags}
            proof = verify_readiness(observe, flags, self.expected_flags, TARGETS_TOTAL)
            resource = self.metrics.sample(episode.pid) if self.metrics is not None else None
            return LaunchOutcome(episode=episode, observe=observe, proof=proof, runtime_dir=str(runtime_dir), resource=resource)
        except EpisodeFailure as exc:
            action = self._close_quietly(episode)
            exc.diagnostics.update({"port": port, "busy_ports_skipped": busy, "runtime_dir": str(runtime_dir),
                                    "cleanup_action": action, "cancelled": manager.cancelled()})
            raise
        except BaseException:
            self._close_quietly(episode)
            raise

    @staticmethod
    def _close_quietly(episode: BattleShipEpisode) -> str:
        try:
            return episode.close()
        except EpisodeFailure as exc:
            return f"cleanup_failure: {exc.message}"

    def _dispose_standby_record(self, generation: int, outcome: str) -> None:
        """Queue the directories of a standby generation that never became active (failed, lost, cancelled)."""
        with self._dir_lock:
            dirs = list(self._standby_dirs.pop(generation, []))
        for episode_dir, runtime_dir in dirs:
            # A launch cancelled by shutdown is not a failure: its files are removed. Failed and lost generations
            # are kept for debugging under the same cap as lifecycle-failure episode directories.
            failure = outcome in ("failed", "lost")
            keep = failure and self.standby_failed_dirs_kept < self.retain_failed_cap
            record = {"kind": "standby_dir", "rank": self.rank, "generation": generation, "outcome": outcome,
                      "episode_dir": portable_path(episode_dir), "runtime_dir": portable_path(runtime_dir),
                      "decision": "kept_failure_debug" if keep else ("deleted_failure_over_cap" if failure
                                                                      else "deleted_cancelled")}
            if keep:
                self.standby_failed_dirs_kept += 1
            else:
                self.queue_deletion(episode_dir, record)
            if self.ledger_hook is not None:
                self.ledger_hook(record)

    def standby_snapshot(self) -> Dict[str, Any]:
        """Control/inspection method (env_method): the standby state and pid, without touching anything."""
        if self.standby is None:
            return {"enabled": False, "state": None, "pid": None, "live_processes": self.live_processes()}
        rec = self.standby.record
        return {"enabled": True, "state": self.standby.state.value, "pid": self.standby.standby_pid(),
                "generation": rec.generation if rec else None, "live_processes": self.live_processes(),
                "active_pid": self._episode.pid if self._episode is not None else None,
                "thread_alive": self.standby.thread_alive()}

    def wait_standby_settled(self, timeout: float = 120.0) -> Dict[str, Any]:
        """Test helper (env_method): block until the standby is no longer starting."""
        deadline = time.monotonic() + timeout
        while self.standby is not None and self.standby.state == StandbyState.STARTING and time.monotonic() < deadline:
            time.sleep(0.05)
        return self.standby_snapshot()

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
            if self.standby is not None:
                self.last_standby_close = self.standby.close()   # cancel + join + close first: no new process can appear
            super().close()
        finally:
            if self.standby is not None:
                for h in list(self.standby.history):
                    if h.get("generation") in self._standby_dirs and h.get("outcome") != "promoted":
                        self._dispose_standby_record(int(h["generation"]), str(h.get("outcome")))
            for s in self._squat_sockets:
                try:
                    s.close()
                except OSError:
                    pass
            self._squat_sockets = []
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
        """Delete an M2 episode directory (and its generation runtime directory, standby mode) once no process
        can hold files in it (next reset or close)."""
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
            runtime_dir = self.runtime_dir_for(directory)
            if runtime_dir:
                try:
                    remove_worker_runtime(Path(runtime_dir))
                    entry["runtime_dir_deleted"] = True
                except (OSError, RuntimeError) as exc:
                    entry["runtime_dir_deleted"] = False
                    entry["runtime_dir_error"] = f"{type(exc).__name__}: {exc}"
                with self._dir_lock:
                    self._runtime_by_episode_dir.pop(str(directory), None)
            self.deletion_log.append(entry)

    def standby_report(self) -> Dict[str, Any]:
        base = {"lifecycle": self.standby_settings.to_json(), "max_concurrent_processes": self.max_concurrent_processes,
                "retire_s": [round(v, 4) for v in self.retire_s], "events": list(self.standby_events),
                "standby_failed_dirs_kept": self.standby_failed_dirs_kept, "last_close": self.last_standby_close}
        if self.standby is not None:
            base["manager"] = self.standby.report()
        return base


# -- reward --------------------------------------------------------------------------------------------


class M7RewardWrapper(RewardV1Wrapper):
    """A versioned reward contract (rl/btt_rewards.py) evaluated on M7 transitions.

    The target, step and clear terms are the unchanged M5 reward_v1() with
    the NATIVE CLEAR as its terminal flag (clear bonus and the
    targets_remaining == 0 check apply to the native EpisodeEnded result
    only). The contract's failure_penalty is added exactly once, on the step
    whose termination_reason is native_failure (btt_native_failure_v1); it
    is 0.0 under btt_reward_v1 and -5.0 under btt_reward_v2. No other step
    can carry that reason: a horizon truncation, a lifecycle failure (Track 1
    returns it as a truncation with reward 0.0 above this wrapper), an
    interruption or a cleanup never reaches this arithmetic as a failure."""

    def __init__(self, env: Any, contract: RewardContract = REWARD_V1, tracker: Optional["M7EpisodeTracker"] = None):
        super().__init__(env, contract.v1_config(), tracker)
        self.reward_contract = contract
        self.episode_failure_terms = 0

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        self.episode_failure_terms = 0
        observation, info = super().reset(seed=seed, options=options)
        info["reward_contract"] = self.reward_contract.contract
        return observation, info

    def step(self, action: Any):
        observation, _placeholder, terminated, truncated, info = self.env.step(action)  # EpisodeFailure propagates
        reason = info.get("termination_reason") if terminated else None
        clear = reason == TERMINATION_NATIVE_CLEAR
        native_failure = reason == TERMINATION_NATIVE_FAILURE
        current = live_targets(observation)
        terms = reward_step(self._previous_targets, current, clear=clear, native_failure=native_failure,
                            contract=self.reward_contract)
        self._previous_targets = current
        self.last_breakdown = terms.m5_breakdown()
        self.episode_return += terms.total
        self.episode_steps += 1
        self.episode_targets_broken += terms.newly_broken
        if terms.failure_term:
            self.episode_failure_terms += 1
        info["reward_contract"] = self.reward_contract.contract
        info["reward_terms"] = terms.to_json()
        if self.reward_contract.contract == REWARD_CONTRACT:
            info["reward_v1"] = self.last_breakdown.to_json()   # M7a key, kept for v1 runs
        info["episode_return"] = self.episode_return
        info["episode_targets_broken"] = self.episode_targets_broken
        if self.tracker is not None:
            self.tracker.note_step(terms, terminated, truncated, info)
        return observation, terms.total, terminated, truncated, info


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
        reward: RewardContract = REWARD_V1,
        retain_failed_cap: int = 20,
        preserve_all: bool = False,
        experiment: Optional[Mapping[str, Any]] = None,
    ):
        self.run_id = run_id
        self.role = role
        self.rank = int(rank)
        self.coordinator = coordinator
        self.artifact_root = Path(artifact_root)
        self.ledger_path = Path(ledger_path)
        self.env = env
        self.reward = reward
        self.experiment = dict(experiment) if experiment else None   # M7b summary block (fingerprints, reward id)
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
                         "pid": None, "port": None, "startup": startup, "digest": hashlib.sha256(),
                         "failure_term_total": 0.0, "failure_terms": 0, "target_break_ticks": []}
        return {
            "milestone": M7_MILESTONE,
            "role": self.role,
            "run_id": self.run_id,
            "rank": self.rank,
            "worker_episode": self.episodes_started,
            "native_steps_at_start": self.native_steps,
            "sb3_num_timesteps_at_start": self.sb3_num_timesteps,
            "checkpoint_label": self.checkpoint_label,
            "contracts": m7_contracts(self.env.max_episode_steps or 0, self.reward),
            "reward_contract": self.reward.contract,
            "reward_constants": self.reward.to_json(),
            "experiment": self.experiment,
            "startup": startup,
            # M7c: how this episode's process came to exist (cold_start / standby_promoted / cold_fallback) and the
            # worker's lifecycle configuration; labels only, the artifact format is unchanged.
            "lifecycle": self.env.standby_settings.to_json(),
            "startup_mode": startup.get("mode"),
        }

    def note_step(self, breakdown: Any, terminated: bool, truncated: bool, info: Mapping[str, Any]) -> None:
        self.native_steps += 1
        cur = self._current
        if not cur:
            return
        cur["steps"] += 1
        cur["return"] += breakdown.total
        cur["targets_broken"] += breakdown.newly_broken
        if breakdown.newly_broken:
            # M7d: consumed tick of every target break (summary only; artifacts and labels are unchanged)
            cur["target_break_ticks"].extend([info.get("consumed_tick")] * int(breakdown.newly_broken))
        failure_term = float(getattr(breakdown, "failure_term", 0.0) or 0.0)
        if failure_term:
            cur["failure_term_total"] += failure_term
            cur["failure_terms"] += 1
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
                                "pid": None, "port": None, "startup": {}, "digest": hashlib.sha256(),
                                "failure_term_total": 0.0, "failure_terms": 0, "target_break_ticks": []}
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
            "reward_contract": self.reward.contract,
            "failure_penalty_applied": bool(cur["failure_terms"]),
            "failure_penalty_total": cur["failure_term_total"],
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
                  "runtime_dir": portable_path(self.env.runtime_dir_for(cur["episode_dir"])),
                  "startup_mode": (cur.get("startup") or {}).get("mode"),
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
            "target_break_ticks": list(cur.get("target_break_ticks") or []),   # M7d: consumed tick of each break
            "reward_contract": self.reward.contract,
            "failure_penalty_applied": bool(cur["failure_terms"]),
            "failure_penalty_terms": cur["failure_terms"],
            "failure_penalty_total": cur["failure_term_total"],
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
            "startup_mode": (cur.get("startup") or {}).get("mode"),
            "sb3_num_timesteps_at_end": self.sb3_num_timesteps,
            "checkpoint_label": self.checkpoint_label,
        }

    def pop_summary(self) -> Optional[Dict[str, Any]]:
        s, self._pending_summary = self._pending_summary, None
        if s is not None:
            self.summaries_emitted += 1
        return s

    def extend_pending_summary(self, build: Callable[[Mapping[str, Any]], Mapping[str, Any]]) -> bool:
        """M7g Phase K (evaluation workers only, rl/m7g_eval_metrics.py): merge facts computed from the episode that
        just ended - `build` receives a copy of its summary - before the worker hands the summary to the parent.
        Returns False (and changes nothing) when no summary is pending. Nothing else in the tracker changes."""
        if self._pending_summary is None:
            return False
        self._pending_summary.update(build(dict(self._pending_summary)))
        return True

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
        self._reported_standby_pid: Optional[int] = None
        base.ledger_hook = tracker._ledger

    def _standby_pid_if_changed(self) -> Optional[int]:
        """The standby pid when it differs from the last one reported to the parent (for orphan cleanup)."""
        pid = self.base.standby.standby_pid() if self.base.standby is not None else None
        if pid != self._reported_standby_pid:
            self._reported_standby_pid = pid
            return pid
        return None

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        t0 = time.perf_counter()
        observation, info = self.env.reset(seed=seed, options=options)
        dt = time.perf_counter() - t0
        self.reset_times.append(dt)
        self.step_in_episode = 0
        timing = self.base.last_reset_timing
        slim = {"m7_rank": self.worker_spec.rank, "m7_reset_s": dt, "pid": info.get("pid"), "port": info.get("port"),
                "m7_startup": info.get("m7_startup"), "m7_standby_wait_s": timing.get("standby_wait_s", 0.0),
                "m7_retire_s": timing.get("retire_s", 0.0), "m7_promotion_s": timing.get("promotion_s"),
                "m7_startup_mode": (info.get("m7_startup") or {}).get("mode"),
                "m7_standby_pid": self.base.standby.standby_pid() if self.base.standby is not None else None,
                "m7_standby_pid_reported": True}
        self._reported_standby_pid = slim["m7_standby_pid"]
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
        if self.base.standby is not None:
            pid = self._standby_pid_if_changed()
            if pid is not None:
                slim["m7_standby_pid"] = pid
                slim["m7_standby_pid_reported"] = True
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
        ctx = {"worker_episode": self.tracker.episodes_started, "step_in_episode": self.step_in_episode,
               "game_pid": self.base.episode.pid if self.base.episode is not None else None,
               "phase": self.base.phase}
        try:
            ctx["standby"] = self.base.standby_snapshot()
        except Exception:  # noqa: BLE001 - context only
            pass
        return ctx

    def standby_snapshot(self) -> Dict[str, Any]:
        return self.base.standby_snapshot()

    def wait_standby_settled(self, timeout: float = 120.0) -> Dict[str, Any]:
        return self.base.wait_standby_settled(timeout)

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
            "startup_failures": [a for a in self.base.startup_attempt_log if a["outcome"] not in ("fresh", "promoted")],
            "native_step_hist": self.base.native_hist.to_json(),
            "service_hist": self.service_hist.to_json(),
            "game_process_samples": samples,
            "episode_dir_deletions": list(self.base.deletion_log),
            "worker_process": own,
            "standby": self.base.standby_report(),
            "startup_modes": {STARTUP_MODE_STANDBY_PROMOTED: sum(1 for a in self.base.startup_attempt_log
                                                                 if a.get("outcome") == "promoted"),
                              "cold": sum(1 for a in self.base.startup_attempt_log if a.get("outcome") == "fresh")},
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
    reward_contract: RewardContract = REWARD_V1   # M7b: versioned contract (rl/btt_rewards.py); default v1
    experiment: Optional[Dict[str, Any]] = None   # M7b: experiment summary block written into every artifact label
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
    # M7c standby lifecycle (rl/m7_standby.py); defaults = M7a/M7b behaviour (no standby process)
    standby_preboot: bool = False
    standby_count: int = 0
    standby_wait_timeout: float = 120.0
    standby_fault: Optional[Dict[str, Any]] = None   # test only: {"generations": [..], "squat_attempts": [..] | "all",
                                                     #            "startup_timeout_attempts": [..]}

    @property
    def standby(self) -> StandbySettings:
        return StandbySettings(preboot=self.standby_preboot, count=self.standby_count, wait_timeout=self.standby_wait_timeout)

    def profile(self) -> Dict[str, Any]:
        """The task / reward / flag identity every process of this worker must have been booted for."""
        exp = self.experiment or {}
        return {"reward_contract": self.reward_contract.contract, "reward_values": self.reward_contract.values(),
                "semantic_fingerprint": exp.get("semantic_fingerprint"), "task_id": exp.get("task_id"),
                "horizon": int(self.horizon), "flags": expected_status_flags(dict(self.extra_env)),
                "executable": str(self.executable)}

    @property
    def worker_seed(self) -> int:
        return int(self.base_seed) + int(self.rank)

    def paths(self) -> Dict[str, Path]:
        root = Path(self.worker_dir)
        return {"root": root, "runtime": root / "runtime", "episodes": root / "episodes",
                "artifacts": root / "artifacts", "ledger": root / "dispositions.jsonl",
                "runtime_gens": root / "runtime_gens"}


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
                              port_claim_hook=_PortSquatter(spec.squat_first_attempt) if spec.squat_first_attempt else None,
                              standby=spec.standby, generation_runtime_root=paths["runtime_gens"], profile=spec.profile(),
                              standby_fault=spec.standby_fault, retain_failed_cap=spec.retain_failed_cap)
    tracker = M7EpisodeTracker(run_id=spec.run_id, role=spec.role, rank=spec.rank,
                               coordinator=RunCoordinator(spec.coordination_dir), artifact_root=paths["artifacts"],
                               ledger_path=paths["ledger"], env=base, reward=spec.reward_contract,
                               retain_failed_cap=spec.retain_failed_cap, preserve_all=spec.preserve_all,
                               experiment=spec.experiment)
    rewarded = M7RewardWrapper(base, spec.reward_contract, tracker)
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
                        # M7c: the standby report must describe the state AFTER close (thread joined, standby closed)
                        report["standby"] = closed_env.base.standby_report()
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
