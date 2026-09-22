#!/usr/bin/env python3
"""M7c: standby (pre-booted) BattleShip process lifecycle for one worker.

A worker keeps exactly one ACTIVE BattleShip process (the episode being
stepped) and at most one STANDBY process that boots in the background while
the active episode runs. When the active episode ends, the old process is
closed and reaped, the ready standby is PROMOTED to active without resetting
or stepping it (its cached tick-0 observation is the reset observation), and
the next standby is launched. Nothing native changes: a standby is an
ordinary M2 launch (new process, new port, new isolated files, fresh
WaitingForAction / can_step / step_count 0) whose readiness was proven by
non-consuming requests; parked at tick 0 it consumes no action and its
simulated time does not advance (measured in M7c Phase A: every observation
field identical after 20 s, CPU 0.3 % of a core).

State machine (StandbyState), one instance per worker::

    no_standby --launch()--> starting --thread: fresh + readiness proven--> ready
    starting   --thread: attempts exhausted / unexpected error--> failed
    starting   --cancel()--> closing --> no_standby
    ready      --acquire(): alive + re-verified--> promoting --promoted()--> no_standby
    ready      --acquire(): dead or re-check failed--> (lost) no_standby
    ready      --cancel()/close()--> closing --> no_standby
    failed     --acquire()--> (failure consumed, reported) no_standby

Ownership rules:

- The launcher thread owns the BattleShipEpisode it creates until the state
  is `ready` and the thread has finished; the main thread never touches that
  object before then. Cancellation from the main thread only terminates the
  OS process (an OS-level action), which makes the thread's bounded M2 wait
  loops return; the thread then closes and reaps its own episode.
- `acquire()` (main thread) takes ownership of a ready episode after joining
  the thread and re-verifying liveness, transport, state and the tick-0
  observation. The caller installs it as active and calls `promoted()`.
- Never more than one standby exists or is in flight; `launch()` refuses
  otherwise. Each launch has a unique generation number, port, process,
  runtime directory and episode directory, allocated by the caller's
  `launch_fn`.
- `close()` cancels, joins (bounded) and closes whatever is left; it is
  idempotent and is the last word on cleanup (the Windows job object is the
  backstop behind it).

The module is standard library + rl/battleship_process.py; the actual
launch (ports, runtime directories, M2 launch, readiness checks) is injected
as `launch_fn` so the state machine is unit-testable without a game.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from battleship_client import BattleShipError, Observe, StepState  # noqa: E402
from battleship_process import BattleShipEpisode, EpisodeFailure, EpisodeOutcome  # noqa: E402

STANDBY_CONTRACT = "btt_standby_lifecycle_v1"
MAX_STANDBY_COUNT = 1


class StandbyState(str, Enum):
    NO_STANDBY = "no_standby"
    STARTING = "starting"
    READY = "ready"
    PROMOTING = "promoting"
    FAILED = "failed"
    CLOSING = "closing"


class StandbyError(RuntimeError):
    """Invalid transition or invariant violation (a programming error, never a game failure)."""


@dataclass
class ReadinessProof:
    """What a standby proved before it may be promoted (all non-consuming requests)."""

    state_name: str
    can_step: bool
    step_count: int
    input_tick: int
    time_passed: int
    btt_active: int
    targets_remaining: int
    flags: Dict[str, bool]              # status.no_render / status.raphnet_disabled
    proven_at_utc: str

    def to_json(self) -> Dict[str, Any]:
        return dict(vars(self))


@dataclass
class LaunchOutcome:
    """Returned by launch_fn for one successful attempt."""

    episode: BattleShipEpisode
    observe: Observe
    proof: ReadinessProof
    runtime_dir: Optional[str] = None
    resource: Optional[Dict[str, Any]] = None   # process sample at readiness (diagnostic)


@dataclass
class StandbyRecord:
    """Everything about one standby generation, kept for reports and artifacts."""

    generation: int
    rank: int
    launched_at: float                                # perf_counter at launch()
    profile: Dict[str, Any] = field(default_factory=dict)   # reward contract id, fingerprint, task, flags expected
    attempts: List[Dict[str, Any]] = field(default_factory=list)
    outcome: str = "starting"                         # starting | ready | failed | cancelled | promoted | lost | closed
    ready_at: Optional[float] = None
    startup_s: Optional[float] = None
    ready_utc: Optional[str] = None
    pid: Optional[int] = None
    port: Optional[int] = None
    runtime_dir: Optional[str] = None
    episode_dir: Optional[str] = None
    save_path: Optional[str] = None
    result_path: Optional[str] = None
    proof: Optional[Dict[str, Any]] = None
    resource_at_ready: Optional[Dict[str, Any]] = None
    resource_at_promotion: Optional[Dict[str, Any]] = None
    ready_before_promotion_s: Optional[float] = None
    error: Optional[str] = None                       # unexpected (non-lifecycle) thread error, with traceback
    lost_reason: Optional[str] = None
    cleanup_action: Optional[str] = None
    episode: Optional[BattleShipEpisode] = field(default=None, repr=False)
    observe: Optional[Observe] = field(default=None, repr=False)

    def to_json(self) -> Dict[str, Any]:
        return {k: v for k, v in vars(self).items() if k not in ("episode", "observe")}


@dataclass
class AcquireResult:
    kind: str                     # ready | none | failed | lost | wait_timeout | starting_error
    waited_s: float
    record: Optional[StandbyRecord] = None
    observe: Optional[Observe] = None   # fresh re-observation at promotion (identical to the cached one)


# Lifecycle outcomes that end a standby launch without retry (a process that survives kill is not retried).
NON_RETRYABLE = (EpisodeOutcome.CLEANUP_FAILURE,)


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def verify_readiness(observe: Observe, status_flags: Dict[str, bool], expected_flags: Dict[str, bool],
                     targets_total: int) -> ReadinessProof:
    """The promotability contract on a non-consuming observe + status. Raises EpisodeFailure(not_fresh) otherwise."""
    problems = []
    if observe.state != StepState.WAITING_FOR_ACTION or not observe.can_step:
        problems.append(f"state {observe.state_name} can_step={observe.can_step}")
    if observe.step_count != 0:
        problems.append(f"step_count {observe.step_count}")
    o = observe.observation
    if o.input_tick != 0:
        problems.append(f"input_tick {o.input_tick} (an action was consumed)")
    if o.time_passed != 0:
        problems.append(f"time_passed {o.time_passed} (simulated time advanced)")
    if o.btt_active != 1:
        problems.append(f"btt_active {o.btt_active}")
    if int(o.targets_remaining) != int(targets_total):
        problems.append(f"targets_remaining {o.targets_remaining} != {targets_total}")
    for name, want in expected_flags.items():
        if name not in status_flags:
            problems.append(f"status has no `{name}` flag")
        elif bool(status_flags[name]) != bool(want):
            problems.append(f"status.{name}={status_flags[name]} expected {want}")
    if problems:
        raise EpisodeFailure(EpisodeOutcome.NOT_FRESH, "standby readiness contract violated: " + "; ".join(problems))
    return ReadinessProof(state_name=observe.state_name, can_step=bool(observe.can_step), step_count=int(observe.step_count),
                          input_tick=int(o.input_tick), time_passed=int(o.time_passed), btt_active=int(o.btt_active),
                          targets_remaining=int(o.targets_remaining), flags=dict(status_flags), proven_at_utc=utc_now())


def observations_equal(a: Observe, b: Observe) -> List[str]:
    """Field names that differ between two non-consuming observations (state, step_count and every observation field)."""
    diffs = []
    if a.state != b.state or a.can_step != b.can_step or a.step_count != b.step_count:
        diffs.append("state/can_step/step_count")
    for name in a.observation.__dataclass_fields__:
        if getattr(a.observation, name) != getattr(b.observation, name):
            diffs.append(name)
    return diffs


class StandbyManager:
    """One worker's standby slot. Thread-safe; the launcher runs in a daemon thread owned by this object.

    launch_fn(generation, attempt, manager) -> LaunchOutcome, raising EpisodeFailure for a classified
    lifecycle failure of that attempt. It must register the launched OS process with
    `manager.note_inflight(process, pid, port)` right after Popen so that cancel() can terminate it, and it
    must return only after the readiness contract was proven (verify_readiness)."""

    def __init__(self, *, rank: int, launch_fn: Callable[[int, int, "StandbyManager"], LaunchOutcome],
                 startup_attempts: int = 3, join_timeout: float = 30.0, request_timeout: float = 10.0,
                 history_cap: int = 1000):
        if startup_attempts < 1:
            raise ValueError("startup_attempts must be >= 1")
        self.rank = int(rank)
        self.launch_fn = launch_fn
        self.startup_attempts = int(startup_attempts)
        self.join_timeout = float(join_timeout)
        self.request_timeout = float(request_timeout)
        self.history_cap = int(history_cap)
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._state = StandbyState.NO_STANDBY
        self._record: Optional[StandbyRecord] = None
        self._thread: Optional[threading.Thread] = None
        self._cancel = threading.Event()
        self._inflight: Optional[Any] = None       # subprocess.Popen of the attempt in progress
        self._inflight_pid: Optional[int] = None
        self._closed = False
        self.history: List[Dict[str, Any]] = []     # bounded records of every generation
        self.counts: Dict[str, int] = {"launches": 0, "attempts": 0, "failed_attempts": 0, "ready": 0, "promoted": 0,
                                       "failed": 0, "lost": 0, "cancelled": 0, "wait_timeouts": 0, "starting_errors": 0}
        self.exposed_wait_s: List[float] = []
        self.startup_s: List[float] = []
        self.ready_before_promotion_s: List[float] = []
        self.promotion_s: List[float] = []
        self.threads_started = 0
        self.threads_joined = 0
        self.last_join_ok: Optional[bool] = None

    # -- queries -----------------------------------------------------------------------------------------

    @property
    def state(self) -> StandbyState:
        with self._lock:
            return self._state

    @property
    def record(self) -> Optional[StandbyRecord]:
        with self._lock:
            return self._record

    def standby_pid(self) -> Optional[int]:
        """Pid of the standby process in flight or ready (for the parent's orphan cleanup)."""
        with self._lock:
            if self._state in (StandbyState.STARTING, StandbyState.CLOSING) and self._inflight_pid is not None:
                return self._inflight_pid
            if self._record is not None and self._record.episode is not None and self._state in (
                    StandbyState.READY, StandbyState.PROMOTING, StandbyState.CLOSING):
                return self._record.episode.pid
            return None

    def live_standby_processes(self) -> int:
        with self._lock:
            if self._state == StandbyState.STARTING and self._inflight is not None and self._inflight.poll() is None:
                return 1
            if self._record is not None and self._record.episode is not None and self._record.episode.alive \
                    and self._state in (StandbyState.READY, StandbyState.PROMOTING, StandbyState.CLOSING):
                return 1
            return 0

    def thread_alive(self) -> bool:
        t = self._thread
        return t is not None and t.is_alive()

    # -- launcher-side registration -------------------------------------------------------------------------

    def note_inflight(self, process: Any, pid: Optional[int], port: Optional[int]) -> None:
        with self._lock:
            self._inflight = process
            self._inflight_pid = pid
            if self._record is not None:
                self._record.pid = pid
                self._record.port = port
            cancelled = self._cancel.is_set()
        if cancelled and process is not None and process.poll() is None:
            # cancel() ran before the process existed: end it now instead of letting it boot to readiness
            try:
                process.terminate()
            except OSError:
                pass

    def cancelled(self) -> bool:
        return self._cancel.is_set()

    # -- transitions -----------------------------------------------------------------------------------------

    def launch(self, generation: int, profile: Optional[Dict[str, Any]] = None) -> StandbyRecord:
        """no_standby -> starting: start the background launch of generation `generation`."""
        with self._lock:
            if self._closed:
                raise StandbyError("launch() after close()")
            if self._state != StandbyState.NO_STANDBY:
                raise StandbyError(f"launch() while a standby is {self._state.value} (at most one standby per worker)")
            if self._thread is not None and self._thread.is_alive():
                raise StandbyError("launch() while the previous launcher thread is still alive")
            rec = StandbyRecord(generation=int(generation), rank=self.rank, launched_at=time.perf_counter(),
                                profile=dict(profile or {}))
            self._record = rec
            self._state = StandbyState.STARTING
            self._cancel.clear()
            self._inflight = None
            self._inflight_pid = None
            self.counts["launches"] += 1
            thread = threading.Thread(target=self._run, args=(rec,), name=f"m7-standby-r{self.rank}-g{generation}",
                                      daemon=True)
            self._thread = thread
            self.threads_started += 1
            thread.start()
            return rec

    def _run(self, rec: StandbyRecord) -> None:
        outcome: Optional[LaunchOutcome] = None
        try:
            for attempt in range(1, self.startup_attempts + 1):
                if self._cancel.is_set():
                    break
                t0 = time.perf_counter()
                try:
                    outcome = self.launch_fn(rec.generation, attempt, self)
                except EpisodeFailure as exc:
                    pid = exc.diagnostics.get("pid")
                    cancelled = self._cancel.is_set()
                    entry = {"generation": rec.generation, "attempt": attempt, "port": exc.diagnostics.get("port"),
                             "outcome": "cancelled" if cancelled else exc.outcome.value,
                             "lifecycle_outcome": exc.outcome.value,
                             "message": exc.message.splitlines()[0][:300], "pid": pid,
                             "elapsed_s": round(time.perf_counter() - t0, 3),
                             "episode_dir": exc.diagnostics.get("episode_dir"),
                             "busy_ports_skipped": exc.diagnostics.get("busy_ports_skipped"),
                             "cancelled": cancelled}
                    with self._lock:
                        rec.attempts.append(entry)
                        self.counts["attempts"] += 1
                        if not cancelled:
                            self.counts["failed_attempts"] += 1
                        self._inflight = None
                        self._inflight_pid = None
                    if exc.outcome in NON_RETRYABLE or cancelled:
                        break
                    continue
                elapsed = time.perf_counter() - t0
                with self._lock:
                    self.counts["attempts"] += 1
                    ep = outcome.episode
                    rec.attempts.append({"generation": rec.generation, "attempt": attempt, "port": ep.port, "outcome": "fresh",
                                         "pid": ep.pid, "elapsed_s": round(elapsed, 3),
                                         "busy_ports_skipped": getattr(ep, "m7_busy_ports_skipped", None)})
                    rec.pid, rec.port = ep.pid, ep.port
                    rec.runtime_dir = outcome.runtime_dir
                    if ep.paths is not None:
                        rec.episode_dir = str(ep.paths.directory)
                        rec.save_path = str(ep.paths.save_path)
                        rec.result_path = str(ep.paths.result_path)
                    rec.proof = outcome.proof.to_json()
                    rec.resource_at_ready = outcome.resource
                    rec.episode = ep
                    rec.observe = outcome.observe
                    rec.ready_at = time.perf_counter()
                    rec.ready_utc = utc_now()
                    rec.startup_s = round(rec.ready_at - rec.launched_at, 4)
                    self._inflight = None
                    self._inflight_pid = None
                    if self._cancel.is_set() or self._state != StandbyState.STARTING:
                        # cancelled while the last request was in flight: this thread still owns the episode
                        rec.outcome = "cancelled"
                        rec.cleanup_action = self._close_episode(ep)
                        rec.episode = None
                        self.counts["cancelled"] += 1
                        self._state = StandbyState.NO_STANDBY
                    else:
                        rec.outcome = "ready"
                        self.counts["ready"] += 1
                        self.startup_s.append(rec.startup_s)
                        self._state = StandbyState.READY
                    self._cond.notify_all()
                return
            with self._lock:
                if self._cancel.is_set():
                    rec.outcome = "cancelled"
                    self.counts["cancelled"] += 1
                    self._state = StandbyState.NO_STANDBY
                else:
                    rec.outcome = "failed"
                    self.counts["failed"] += 1
                    self._state = StandbyState.FAILED
                self._cond.notify_all()
        except BaseException as exc:  # noqa: BLE001 - structured: surfaced at the next acquire(), never silent
            with self._lock:
                rec.outcome = "failed"
                rec.error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-4000:]}"
                self.counts["starting_errors"] += 1
                if outcome is not None and outcome.episode is not None and rec.episode is None:
                    rec.cleanup_action = self._close_episode(outcome.episode)
                self._inflight = None
                self._inflight_pid = None
                self._state = StandbyState.FAILED
                self._cond.notify_all()

    def acquire(self, wait_timeout: float, *, targets_total: Optional[int] = None) -> AcquireResult:
        """Main thread, at reset time: hand over a verified ready standby, or explain why not.

        Waits (bounded by `wait_timeout`) while a launch is in flight. A ready standby is re-verified with a
        non-consuming status + observe; a dead or diverged one is closed and reported as `lost`."""
        t0 = time.perf_counter()
        with self._lock:
            if self._closed:
                raise StandbyError("acquire() after close()")
            if self._state == StandbyState.NO_STANDBY:
                return AcquireResult("none", 0.0)
            if self._state == StandbyState.STARTING:
                deadline = t0 + max(0.0, float(wait_timeout))
                while self._state == StandbyState.STARTING:
                    remaining = deadline - time.perf_counter()
                    if remaining <= 0:
                        break
                    self._cond.wait(remaining)
            waited = time.perf_counter() - t0
            state = self._state
            rec = self._record
        if state == StandbyState.STARTING:
            self.counts["wait_timeouts"] += 1
            self.exposed_wait_s.append(waited)
            self._cancel_locked_free()
            return AcquireResult("wait_timeout", waited, rec)
        self.exposed_wait_s.append(waited)
        self._join_thread()
        with self._lock:
            state, rec = self._state, self._record
            if state == StandbyState.FAILED:
                assert rec is not None
                self._state = StandbyState.NO_STANDBY
                self._archive(rec)
                self._record = None
                return AcquireResult("starting_error" if rec.error else "failed", waited, rec)
            if state != StandbyState.READY or rec is None or rec.episode is None:
                # cancelled in between (close() racing a reset): nothing to hand over
                return AcquireResult("none", waited, rec)
            self._state = StandbyState.PROMOTING
        # Re-verification outside the lock (bounded loopback requests; the thread is finished, we own the episode).
        ep = rec.episode
        lost: Optional[str] = None
        fresh: Optional[Observe] = None
        if not ep.alive:
            lost = f"process exited (code {ep.process.returncode if ep.process else None}) after readiness"
        else:
            try:
                assert ep.client is not None
                status = ep.client.status()
                if not (status.state == StepState.WAITING_FOR_ACTION and status.can_step and status.step_count == 0):
                    lost = f"status changed after readiness: {status.state_name} can_step={status.can_step} step_count={status.step_count}"
                else:
                    fresh = ep.client.observe()
                    diffs = observations_equal(rec.observe, fresh)
                    if diffs:
                        lost = f"tick-0 observation changed while parked: {diffs}"
                    elif targets_total is not None and int(fresh.observation.targets_remaining) != int(targets_total):
                        lost = f"targets_remaining {fresh.observation.targets_remaining} at promotion"
            except BattleShipError as exc:
                lost = f"re-verification request failed: {type(exc).__name__}: {exc}"
        with self._lock:
            if lost is not None:
                rec.outcome = "lost"
                rec.lost_reason = lost
                rec.cleanup_action = self._close_episode(ep)
                rec.episode = None
                self.counts["lost"] += 1
                self._state = StandbyState.NO_STANDBY
                self._archive(rec)
                self._record = None
                return AcquireResult("lost", waited, rec)
            rec.ready_before_promotion_s = round(time.perf_counter() - (rec.ready_at or time.perf_counter()), 4)
            return AcquireResult("ready", waited, rec, fresh)

    def promoted(self, resource: Optional[Dict[str, Any]] = None) -> StandbyRecord:
        """promoting -> no_standby: the caller now owns the episode as its active process."""
        with self._lock:
            if self._state != StandbyState.PROMOTING or self._record is None:
                raise StandbyError(f"promoted() in state {self._state.value}")
            rec = self._record
            rec.outcome = "promoted"
            rec.resource_at_promotion = resource
            rec.episode = None          # ownership transferred
            rec.observe = None
            self.counts["promoted"] += 1
            if rec.ready_before_promotion_s is not None:
                self.ready_before_promotion_s.append(rec.ready_before_promotion_s)
            self._state = StandbyState.NO_STANDBY
            self._archive(rec)
            self._record = None
            return rec

    def abandon_promotion(self, reason: str) -> None:
        """promoting -> no_standby without taking the episode (the caller failed to install it): close it."""
        with self._lock:
            if self._state != StandbyState.PROMOTING or self._record is None:
                raise StandbyError(f"abandon_promotion() in state {self._state.value}")
            rec = self._record
            rec.outcome = "lost"
            rec.lost_reason = reason
            if rec.episode is not None:
                rec.cleanup_action = self._close_episode(rec.episode)
                rec.episode = None
            self.counts["lost"] += 1
            self._state = StandbyState.NO_STANDBY
            self._archive(rec)
            self._record = None

    def cancel(self) -> Optional[StandbyRecord]:
        """Cancel a launch in flight or drop a ready standby; joins the thread (bounded) and closes the process."""
        return self._cancel_locked_free()

    def close(self) -> Dict[str, Any]:
        """Idempotent final cleanup: cancel + join + close. Returns what was done."""
        rec = self._cancel_locked_free()
        with self._lock:
            self._closed = True
        return {"cancelled_generation": rec.generation if rec else None, "thread_joined": not self.thread_alive(),
                "state": self.state.value}

    # -- internals ---------------------------------------------------------------------------------------------

    def _cancel_locked_free(self) -> Optional[StandbyRecord]:
        with self._lock:
            state, rec = self._state, self._record
            if state in (StandbyState.NO_STANDBY, StandbyState.FAILED) and not self.thread_alive():
                if state == StandbyState.FAILED and rec is not None:
                    self._state = StandbyState.NO_STANDBY
                    self._archive(rec)
                    self._record = None
                return None
            self._cancel.set()
            if state == StandbyState.STARTING:
                self._state = StandbyState.CLOSING
                proc = self._inflight
                if proc is not None and proc.poll() is None:
                    try:
                        proc.terminate()   # OS-level only; the launcher thread classifies, closes and reaps
                    except OSError:
                        pass
            elif state in (StandbyState.READY, StandbyState.PROMOTING):
                self._state = StandbyState.CLOSING
        self._join_thread()
        with self._lock:
            rec = self._record
            if rec is not None and rec.episode is not None:
                rec.cleanup_action = self._close_episode(rec.episode)
                rec.episode = None
                rec.outcome = "closed" if rec.outcome in ("ready", "promoted") else "cancelled"
                if rec.outcome == "cancelled":
                    self.counts["cancelled"] += 1
            if rec is not None:
                self._archive(rec)
            self._record = None
            self._state = StandbyState.NO_STANDBY
            self._inflight = None
            self._inflight_pid = None
            return rec

    def _join_thread(self) -> None:
        t = self._thread
        if t is None or t is threading.current_thread():
            return
        if t.is_alive():
            t.join(self.join_timeout)
        self.last_join_ok = not t.is_alive()
        if self.last_join_ok:
            self.threads_joined += 1
            self._thread = None

    @staticmethod
    def _close_episode(ep: BattleShipEpisode) -> str:
        try:
            return ep.close()
        except EpisodeFailure as exc:
            return f"cleanup_failure: {exc.message}"

    def _archive(self, rec: StandbyRecord) -> None:
        if any(h.get("generation") == rec.generation for h in self.history):
            for i, h in enumerate(self.history):
                if h.get("generation") == rec.generation:
                    self.history[i] = rec.to_json()
            return
        if len(self.history) >= self.history_cap:
            self.history.pop(0)
        self.history.append(rec.to_json())

    # -- report ---------------------------------------------------------------------------------------------------

    def report(self) -> Dict[str, Any]:
        def stats(v: List[float]) -> Dict[str, Any]:
            if not v:
                return {"n": 0}
            s = sorted(v)
            return {"n": len(s), "sum_s": round(sum(s), 4), "mean_s": round(sum(s) / len(s), 4),
                    "median_s": round(s[len(s) // 2], 4), "p90_s": round(s[min(len(s) - 1, int(0.9 * len(s)))], 4),
                    "max_s": round(s[-1], 4), "min_s": round(s[0], 4)}

        with self._lock:
            current = self._record.to_json() if self._record is not None else None
            state = self._state.value
        return {
            "contract": STANDBY_CONTRACT,
            "state": state,
            "counts": dict(self.counts),
            "hits": self.counts["promoted"],
            "startup_s": stats(self.startup_s),
            "exposed_wait_s": stats(self.exposed_wait_s),
            "ready_before_promotion_s": stats(self.ready_before_promotion_s),
            "promotion_s": stats(self.promotion_s),
            "threads_started": self.threads_started,
            "threads_joined": self.threads_joined,
            "thread_alive": self.thread_alive(),
            "last_join_ok": self.last_join_ok,
            "current": current,
            "history": list(self.history),
        }
