#!/usr/bin/env python3
"""M4 benchmark: measure the current visible-window, process-backed BattleShip
Mario Break the Targets environment before anything is optimised.

Nothing here trains, optimises or changes the implementation under test. The
tool launches the same BattleShip build the M2 / M3 stack launches, with the
same environment (visible window, DirectX 11 with vsync as configured), and
records wall-clock, CPU-time and memory numbers around the frozen M1d / M2 /
M3 interfaces. Every quantity is either

  measured   -- a wall-clock or OS counter read around a real call, or a
                native steady-clock stamp the game itself recorded; or
  derived    -- an arithmetic combination of measured quantities, labelled
                as such in the JSON (`derived` sections) and in this text.

Sections (all run by default; select with --only):

  startup        wall-clock from immediately before process launch until M2
                 establishes a FRESH episode: WaitingForAction, can_step,
                 step_count 0. Several launches; distribution reported.
  step           sequential stepping through the raw M1d client (one request
                 per native tick) and, in a second fresh process, through the
                 M3 Gymnasium wrapper. One successful step == one M1c native
                 simulation tick, so the rate is native ticks per second, not
                 a rendering frame rate. With SSB64_RL_TIMING=1 (opt-in native
                 diagnostic, see docs/rl_measurements_m4.md) each raw step
                 also carries the game's own steady-clock stamps, which split
                 the client-observed latency into named native segments.
  rtt            round trip of the non-consuming ops ping / status / observe:
                 nothing advances; this is the loopback + JSON + worker floor.
  serialization  Python json.dumps / json.loads cost of representative M1d
                 request and response lines, measured in isolation (timeit).
  memory         working set / peak working set / private commit of each
                 BattleShip child (Windows: K32GetProcessMemoryInfo,
                 PROCESS_MEMORY_COUNTERS_EX; Linux: /proc/<pid>/status) plus
                 process CPU time (GetProcessTimes / /proc/<pid>/stat),
                 sampled at fresh readiness and after stepping.
  multiprocess   1..N independent BattleShip processes stepped concurrently,
                 each with its own OS process, M2 episode directory, port and
                 client, driven by one thread each; aggregate and per-process
                 native ticks per second, startup success, memory, failures.
  reliability    K consecutive fresh-process episodes fed the tracked 7.43 s
                 baseline replay with the M1e checks; failures are counted and
                 categorised, never retried.

Output: a JSON report (--out) plus a console summary. The JSON carries the
platform, Python and build metadata needed to read it later, and avoids
machine-specific absolute paths.

    python rl/tools/bench.py --out bench.json
    python rl/tools/bench.py --only startup,step,rtt --startup-samples 3
    python rl/tools/bench.py --max-processes 3 --reliability-episodes 5

Standard library plus the repository's own rl/ modules; the `step` section's
Gym half needs gymnasium (rl/requirements.txt) and is skipped with a note if
it is missing.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import timeit
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = RL_DIR.parent
sys.path.insert(0, str(RL_DIR))

from battleship_client import (  # noqa: E402
    PROTOCOL_VERSION,
    BattleShipClient,
    BattleShipError,
    Button,
    Observation,
    StepResult,
    StepState,
)
from battleship_process import (  # noqa: E402
    BattleShipEpisode,
    EpisodeFailure,
    EpisodeOutcome,
    LaunchConfig,
)
from btti_replay import ReplayFormatError, ReplayRow, read_btti_rows  # noqa: E402
from m1e_replay_regression import (  # noqa: E402
    COMPLETION_CONSUMED_TICK,
    COMPLETION_INPUT_TICK,
    COMPLETION_STEPS,
    COMPLETION_TIME_PASSED,
    DEFAULT_REPLAY,
    OBSERVATION_SCHEMA,
    SOURCE_ROWS,
    RegressionFailure,
    check_completion,
    check_step,
)
from m2_restart_regression import EXPECTED_RESULT  # noqa: E402

BENCHMARK_SCHEMA = 1
DEFAULT_EXECUTABLE = REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"
ENV_CONTRACT = "btt_raw_b8_s161_v1"  # M3 Gym-facing contract id (battleship_env.ENV_CONTRACT)
NATIVE_TIMING_ENV = "SSB64_RL_TIMING"  # opt-in native diagnostic stamps (M4)
SECTIONS = ("startup", "step", "rtt", "serialization", "memory", "multiprocess", "reliability")

# The native timing stamps a step response may carry (protocol 1, additive
# "timing" object, only when SSB64_RL_TIMING=1). Consecutive pairs define the
# named segments below; every stamp is std::chrono::steady_clock in ns inside
# the game process, so differences are exact within one process.
NATIVE_STAMPS = (
    "request_received_ns",  # transport worker extracted the request line (before JSON parse)
    "submit_ns",            # rlStepSubmit accepted the action (worker)
    "gate_open_ns",         # first PortPushFrame entry that ran a frame for this step (main thread)
    "consumed_ns",          # BTT controller read took the action for tick T (game coroutine)
    "logic_done_ns",        # PortPushFrame: game update complete, display list not yet drained (main thread)
    "observation_ns",       # GamePostUpdateEvent produced the paired result (main thread, after render + present)
    "collected_ns",         # rlStepWait returned the result to the worker
    "response_ready_ns",    # worker finished building the response JSON object (before dump/send)
)
NATIVE_SEGMENTS: Tuple[Tuple[str, str, str, str], ...] = (
    ("request_to_submit", "request_received_ns", "submit_ns",
     "request JSON parse, field validation, rlStepSubmit (transport worker thread)"),
    ("submit_to_gate_open", "submit_ns", "gate_open_ns",
     "submit -> next PortPushFrame entry with the gate open: the remainder of the parked idle-present "
     "iteration (paced present of the cached framebuffer: DXGI 1/60 s limiter + vsync) plus main-thread "
     "scheduling. Not stepping work."),
    ("gate_open_to_consume", "gate_open_ns", "consumed_ns",
     "PortPushFrame entry -> BTT controller read: cheats, SDL HandleEvents, vblank rotation, VRETRACE post, "
     "scheduler rounds up to the read"),
    ("consume_to_logic_done", "consumed_ns", "logic_done_ns",
     "controller read -> end of port_resume_service_threads: the game update of the tick (fighter, stage, "
     "targets, audio thread, display-list build/staging). No rendering, no present."),
    ("logic_done_to_observation", "logic_done_ns", "observation_ns",
     "display-list drain -> GamePostUpdateEvent: Fast3D render of the display list AND the present "
     "(DXGI frame-limiter wait, Present with vsync, frame-latency wait)."),
    ("observation_to_collect", "observation_ns", "collected_ns",
     "condition-variable wake of the transport worker after the paired result exists"),
    ("collect_to_response", "collected_ns", "response_ready_ns",
     "response JSON object construction (before nlohmann dump and send)"),
)
NATIVE_COUNTERS = ("host_iterations", "parked_iterations")


# -- small helpers ---------------------------------------------------------------------


def log(message: str) -> None:
    print(message, flush=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def percentile(sorted_values: Sequence[float], p: float) -> float:
    """Nearest-rank percentile of an already sorted, non-empty sequence."""
    if not sorted_values:
        raise ValueError("no samples")
    k = max(1, int(round(p / 100.0 * len(sorted_values))))
    return float(sorted_values[min(k, len(sorted_values)) - 1])


def describe(values: Sequence[float], unit: str) -> Dict[str, Any]:
    """count / min / median / mean / p95 / p99 / max / stdev of a sample."""
    if not values:
        return {"unit": unit, "count": 0}
    s = sorted(float(v) for v in values)
    return {
        "unit": unit,
        "count": len(s),
        "min": s[0],
        "median": statistics.median(s),
        "mean": statistics.fmean(s),
        "p95": percentile(s, 95),
        "p99": percentile(s, 99),
        "max": s[-1],
        "stdev": statistics.pstdev(s) if len(s) > 1 else 0.0,
    }


def fmt_stats(d: Dict[str, Any], digits: int = 2) -> str:
    if not d or d.get("count", 0) == 0:
        return "n/a"
    return (f"n={d['count']} min={d['min']:.{digits}f} median={d['median']:.{digits}f} "
            f"mean={d['mean']:.{digits}f} p95={d['p95']:.{digits}f} p99={d['p99']:.{digits}f} "
            f"max={d['max']:.{digits}f} {d['unit']}")


def relative_to_repo(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return path.name


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_describe() -> Dict[str, Any]:
    """Best effort: HEAD commit and dirty flag, no failure if git is absent."""
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(REPO_ROOT), capture_output=True,
                              text=True, timeout=10, check=False).stdout.strip()
        status = subprocess.run(["git", "status", "--porcelain"], cwd=str(REPO_ROOT), capture_output=True,
                                text=True, timeout=10, check=False).stdout
        return {"head": head or None, "dirty": bool(status.strip())}
    except (OSError, subprocess.TimeoutExpired):
        return {"head": None, "dirty": None}


def count_processes_named(name: str) -> Optional[int]:
    """Machine-wide count of running processes with this image name; None if unknown."""
    try:
        if platform.system() == "Windows":
            out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
                                 capture_output=True, text=True, timeout=15, check=False).stdout
            return sum(1 for line in out.splitlines() if line.startswith(f'"{name}"'))
        out = subprocess.run(["pgrep", "-c", "-x", name], capture_output=True, text=True, timeout=15,
                             check=False).stdout
        return int(out.strip() or 0)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


# -- deterministic action pattern -----------------------------------------------------

JAB_PERIOD = 60
ACTION_PATTERN = f"neutral stick; A (Mario's standing jab, in place) for one tick every {JAB_PERIOD} ticks"


def pattern_action(index: int) -> Tuple[int, int, int]:
    """Legal, deterministic, ML-free action for step `index`: neutral stick,
    a one-tick A press every JAB_PERIOD ticks. With a neutral stick A is
    Mario's standing jab (not a jump): he stays where he spawned on the
    enclosed start floor, no target is in reach, the stage never clears and a
    non-trivial fighter update still runs. Identical for every process and run."""
    return (int(Button.A) if index % JAB_PERIOD == 0 else int(Button.NONE), 0, 0)


def pattern_gym_action(index: int) -> Dict[str, int]:
    buttons, sx, sy = pattern_action(index)
    return {"button": 1 if buttons == int(Button.A) else 0, "stick_x": sx, "stick_y": sy}


# -- process metrics (memory, CPU) ----------------------------------------------------------

MEMORY_DEFINITION_WINDOWS = (
    "Windows PROCESS_MEMORY_COUNTERS_EX from K32GetProcessMemoryInfo: working_set = WorkingSetSize "
    "(resident pages now), peak_working_set = PeakWorkingSetSize (lifetime peak resident), "
    "private_bytes = PrivateUsage (private commit charge), peak_private_bytes = PeakPagefileUsage "
    "(peak commit charge). CPU time from GetProcessTimes (user + kernel, 100 ns units)."
)
MEMORY_DEFINITION_LINUX = (
    "Linux /proc/<pid>/status: working_set = VmRSS, peak_working_set = VmHWM, private_bytes = "
    "RssAnon (anonymous resident, closest available), peak_private_bytes = VmPeak (peak virtual, "
    "not commit). CPU time from /proc/<pid>/stat utime + stime."
)


class _PMCEx(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint32),
        ("PageFaultCount", ctypes.c_uint32),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]


def _filetime_seconds(ft: _FILETIME) -> float:
    return ((ft.dwHighDateTime << 32) | ft.dwLowDateTime) / 1e7


class ProcessMetrics:
    """Read memory and CPU counters of another process by pid. Standard library only."""

    def __init__(self) -> None:
        self.system = platform.system()
        self.definition = MEMORY_DEFINITION_WINDOWS if self.system == "Windows" else MEMORY_DEFINITION_LINUX
        if self.system == "Windows":
            self._k32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
            try:
                self._mem_info = self._k32.K32GetProcessMemoryInfo
            except AttributeError:  # older Windows: psapi export
                self._mem_info = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo  # type: ignore[attr-defined]
            self._k32.OpenProcess.restype = ctypes.c_void_p
            self._k32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
            self._k32.CloseHandle.argtypes = [ctypes.c_void_p]
            self._mem_info.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
            self._k32.GetProcessTimes.argtypes = [ctypes.c_void_p] + [ctypes.c_void_p] * 4

    def sample(self, pid: Optional[int]) -> Optional[Dict[str, Any]]:
        if pid is None:
            return None
        try:
            if self.system == "Windows":
                return self._sample_windows(pid)
            return self._sample_linux(pid)
        except (OSError, ValueError):
            return None

    def _sample_windows(self, pid: int) -> Optional[Dict[str, Any]]:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = self._k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return None
        try:
            pmc = _PMCEx()
            pmc.cb = ctypes.sizeof(pmc)
            if not self._mem_info(handle, ctypes.byref(pmc), pmc.cb):
                return None
            ct, et, kt, ut = _FILETIME(), _FILETIME(), _FILETIME(), _FILETIME()
            cpu_user = cpu_kernel = None
            if self._k32.GetProcessTimes(handle, ctypes.byref(ct), ctypes.byref(et), ctypes.byref(kt), ctypes.byref(ut)):
                cpu_user, cpu_kernel = _filetime_seconds(ut), _filetime_seconds(kt)
            return {
                "pid": pid,
                "working_set_bytes": int(pmc.WorkingSetSize),
                "peak_working_set_bytes": int(pmc.PeakWorkingSetSize),
                "private_bytes": int(pmc.PrivateUsage),
                "peak_private_bytes": int(pmc.PeakPagefileUsage),
                "page_faults": int(pmc.PageFaultCount),
                "cpu_user_s": cpu_user,
                "cpu_kernel_s": cpu_kernel,
            }
        finally:
            self._k32.CloseHandle(handle)

    @staticmethod
    def _sample_linux(pid: int) -> Optional[Dict[str, Any]]:
        fields: Dict[str, int] = {}
        with open(f"/proc/{pid}/status", encoding="utf-8") as fp:
            for line in fp:
                key, _, rest = line.partition(":")
                if key in ("VmRSS", "VmHWM", "RssAnon", "VmPeak"):
                    fields[key] = int(rest.split()[0]) * 1024
        with open(f"/proc/{pid}/stat", encoding="utf-8") as fp:
            stat = fp.read().rsplit(")", 1)[1].split()
        clk = os.sysconf("SC_CLK_TCK")
        return {
            "pid": pid,
            "working_set_bytes": fields.get("VmRSS"),
            "peak_working_set_bytes": fields.get("VmHWM"),
            "private_bytes": fields.get("RssAnon"),
            "peak_private_bytes": fields.get("VmPeak"),
            "page_faults": None,
            "cpu_user_s": int(stat[11]) / clk,
            "cpu_kernel_s": int(stat[12]) / clk,
        }


def mib(value: Optional[int]) -> Optional[float]:
    return None if value is None else round(value / (1024 * 1024), 1)


def memory_summary(sample: Optional[Dict[str, Any]]) -> str:
    if not sample:
        return "n/a"
    return (f"ws={mib(sample['working_set_bytes'])} MiB peak_ws={mib(sample['peak_working_set_bytes'])} MiB "
            f"private={mib(sample['private_bytes'])} MiB peak_private={mib(sample['peak_private_bytes'])} MiB "
            f"cpu_user={sample['cpu_user_s']} s cpu_kernel={sample['cpu_kernel_s']} s")


# -- launch with timing --------------------------------------------------------------------


@dataclass
class LaunchTiming:
    ok: bool
    outcome: str  # completed-fresh | EpisodeOutcome value | other
    pre_launch_to_fresh_s: Optional[float] = None
    pre_launch_to_popen_s: Optional[float] = None
    popen_to_transport_s: Optional[float] = None
    transport_to_fresh_s: Optional[float] = None
    pid: Optional[int] = None
    port: Optional[int] = None
    error: Optional[str] = None


def timed_start(episode: BattleShipEpisode) -> LaunchTiming:
    """episode.start() with the wall clock read immediately before launch().

    pre_launch is taken before any preflight (paths, port allocation, Popen);
    the M2 timeline supplies the Popen-return, transport and fresh instants.
    Fresh means the M2 gate: WaitingForAction, can_step, step_count == 0."""
    t_pre = time.perf_counter()
    m_pre = time.monotonic()
    try:
        episode.launch()
        episode.wait_for_transport()
        fresh = episode.wait_for_fresh_episode()
    except EpisodeFailure as exc:
        return LaunchTiming(False, exc.outcome.value, pid=episode.pid, port=episode.port, error=str(exc).splitlines()[0])
    except BattleShipError as exc:
        return LaunchTiming(False, "transport_failure", pid=episode.pid, port=episode.port, error=str(exc))
    t_fresh = time.perf_counter()
    if not (fresh.state == StepState.WAITING_FOR_ACTION and fresh.can_step and fresh.step_count == 0):
        return LaunchTiming(False, EpisodeOutcome.NOT_FRESH.value, pid=episode.pid, port=episode.port,
                            error=f"{fresh.state_name} can_step={fresh.can_step} step_count={fresh.step_count}")
    tl = episode.timeline
    return LaunchTiming(
        True, "fresh",
        pre_launch_to_fresh_s=t_fresh - t_pre,
        pre_launch_to_popen_s=tl["launched"] - m_pre,
        popen_to_transport_s=tl["transport"] - tl["launched"],
        transport_to_fresh_s=tl["fresh"] - tl["transport"],
        pid=episode.pid, port=episode.port,
    )


def safe_close(episode: BattleShipEpisode) -> str:
    try:
        return episode.close()
    except EpisodeFailure as exc:
        return f"cleanup_failure:{exc.outcome.value}"


# -- native timing ----------------------------------------------------------------------------


def native_segments_ms(timing: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """Named segment durations (ms) from one step's native stamps; None if any stamp is missing or zero."""
    try:
        stamps = {name: int(timing[name]) for name in NATIVE_STAMPS}
    except (KeyError, TypeError, ValueError):
        return None
    if any(v <= 0 for v in stamps.values()):
        return None
    out: Dict[str, float] = {}
    for name, start, end, _ in NATIVE_SEGMENTS:
        out[name] = (stamps[end] - stamps[start]) / 1e6
    out["native_total"] = (stamps["response_ready_ns"] - stamps["request_received_ns"]) / 1e6
    return out


# -- section: startup ------------------------------------------------------------------------------


def section_startup(args: argparse.Namespace, config: LaunchConfig, metrics: ProcessMetrics) -> Dict[str, Any]:
    log(f"[startup] {args.startup_samples} sequential launches to fresh WaitingForAction / can_step / step_count 0")
    samples: List[Dict[str, Any]] = []
    for i in range(1, args.startup_samples + 1):
        episode = BattleShipEpisode(config, index=1000 + i)
        try:
            timing = timed_start(episode)
            mem = metrics.sample(episode.pid) if timing.ok else None
            t_close = time.perf_counter()
            cleanup = safe_close(episode)
            close_s = time.perf_counter() - t_close
        except BaseException:
            safe_close(episode)
            raise
        record = {
            "sample": i, "ok": timing.ok, "outcome": timing.outcome, "pid": timing.pid, "port": timing.port,
            "pre_launch_to_fresh_s": timing.pre_launch_to_fresh_s,
            "pre_launch_to_popen_s": timing.pre_launch_to_popen_s,
            "popen_to_transport_s": timing.popen_to_transport_s,
            "transport_to_fresh_s": timing.transport_to_fresh_s,
            "close_s": close_s, "cleanup_action": cleanup,
            "memory_at_fresh": mem, "error": timing.error,
        }
        samples.append(record)
        if timing.ok:
            log(f"  launch {i}: fresh after {timing.pre_launch_to_fresh_s:.3f} s "
                f"(popen {timing.pre_launch_to_popen_s:.3f} + transport {timing.popen_to_transport_s:.3f} + "
                f"fresh {timing.transport_to_fresh_s:.3f}); close {close_s:.2f} s ({cleanup}); {memory_summary(mem)}")
        else:
            log(f"  launch {i}: FAILED {timing.outcome}: {timing.error}")
    ok = [s for s in samples if s["ok"]]
    result = {
        "definition": "wall-clock (time.perf_counter) from immediately before BattleShipEpisode.launch() (preflight, "
                      "port allocation and Popen included) until wait_for_fresh_episode() returned the fresh M2 gate: "
                      "state WaitingForAction, can_step true, step_count 0. This is fresh interactive readiness "
                      "(the state before native tick 0), which earlier notes called startup-to-Go.",
        "attempted": len(samples), "succeeded": len(ok), "failed": len(samples) - len(ok),
        "pre_launch_to_fresh": describe([s["pre_launch_to_fresh_s"] for s in ok], "s"),
        "stages": {
            "pre_launch_to_popen": describe([s["pre_launch_to_popen_s"] for s in ok], "s"),
            "popen_to_transport": describe([s["popen_to_transport_s"] for s in ok], "s"),
            "transport_to_fresh": describe([s["transport_to_fresh_s"] for s in ok], "s"),
            "close_terminate": describe([s["close_s"] for s in ok], "s"),
        },
        "samples": samples,
    }
    log(f"  startup-to-fresh: {fmt_stats(result['pre_launch_to_fresh'], 3)}")
    return result


# -- section: rtt + raw step ------------------------------------------------------------------


def time_calls(fn: Callable[[], Any], count: int) -> List[float]:
    out: List[float] = []
    for _ in range(count):
        t0 = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t0) * 1e3)
    return out


def section_rtt_and_raw_step(args: argparse.Namespace, config: LaunchConfig, metrics: ProcessMetrics,
                             want_rtt: bool, want_step: bool) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], Dict[str, Any]]:
    """One fresh process: protocol-only RTTs first (nothing consumed), then raw M1d stepping."""
    rtt: Optional[Dict[str, Any]] = None
    step: Optional[Dict[str, Any]] = None
    captured: Dict[str, Any] = {}
    episode = BattleShipEpisode(config, index=2001)
    try:
        timing = timed_start(episode)
        if not timing.ok:
            failure = {"ok": False, "outcome": timing.outcome, "error": timing.error}
            return (failure if want_rtt else None), (failure if want_step else None), captured
        client = episode.client
        assert client is not None
        pid = episode.pid

        if want_rtt:
            log(f"[rtt] pid={pid}: {args.rtt_samples} x ping / status / observe on the fresh parked process")
            # Warm the socket path once per op, then time each op separately.
            for op in ("ping", "status", "observe"):
                client.request(op)
            ping_ms = time_calls(lambda: client.request("ping"), args.rtt_samples)
            status_ms = time_calls(lambda: client.request("status"), args.rtt_samples)
            observe_ms = time_calls(lambda: client.request("observe"), args.rtt_samples)
            after = client.status()
            observe_reply = client.request("observe")
            captured["observe_response"] = observe_reply
            consumed_nothing = (after.state == StepState.WAITING_FOR_ACTION and after.step_count == 0
                                and observe_reply["observation"]["input_tick"] == 0)
            rtt = {
                "definition": "wall-clock around BattleShipClient.request(op) for the non-consuming ops: Python "
                              "json.dumps, socket send, native select wake + JSON parse + handler + dump + send, "
                              "socket recv, Python json.loads. Nothing native advances; input_tick stays 0.",
                "samples_per_op": args.rtt_samples,
                "ping": describe(ping_ms, "ms"),
                "status": describe(status_ms, "ms"),
                "observe": describe(observe_ms, "ms"),
                "nothing_consumed": consumed_nothing,
                "observe_response_bytes": len(json.dumps(observe_reply, separators=(",", ":"))),
            }
            log(f"  ping    {fmt_stats(rtt['ping'], 3)}")
            log(f"  status  {fmt_stats(rtt['status'], 3)}")
            log(f"  observe {fmt_stats(rtt['observe'], 3)}  nothing_consumed={consumed_nothing}")

        if want_step:
            total = args.warmup_steps + args.steps
            log(f"[step/raw] pid={pid}: {args.warmup_steps} warm-up + {args.steps} measured raw M1d steps ({ACTION_PATTERN})")
            mem_before = metrics.sample(pid)
            latencies: List[float] = []
            segments: Dict[str, List[float]] = {name: [] for name, *_ in NATIVE_SEGMENTS}
            segments["native_total"] = []
            counters: Dict[str, List[int]] = {name: [] for name in NATIVE_COUNTERS}
            residual: List[float] = []
            timing_seen = 0
            first_response: Optional[Dict[str, Any]] = None
            last: Optional[Dict[str, Any]] = None
            t_window0 = time.perf_counter()
            for i in range(total):
                buttons, sx, sy = pattern_action(i)
                t0 = time.perf_counter()
                r = client.request("step", buttons=buttons, stick_x=sx, stick_y=sy)
                dt_ms = (time.perf_counter() - t0) * 1e3
                if r["consumed_tick"] != i or r["observation"]["input_tick"] != i + 1 or r["step_count"] != i + 1:
                    raise RuntimeError(f"pairing broken at step {i}: {r['consumed_tick']} / {r['observation']['input_tick']} / {r['step_count']}")
                if r["state"] != int(StepState.WAITING_FOR_ACTION):
                    raise RuntimeError(f"episode left WaitingForAction at step {i}: {r['state_name']}")
                last = r
                if first_response is None:
                    first_response = r
                if i < args.warmup_steps:
                    continue
                latencies.append(dt_ms)
                seg = native_segments_ms(r["timing"]) if isinstance(r.get("timing"), dict) else None
                if seg is not None:
                    timing_seen += 1
                    for name, value in seg.items():
                        segments[name].append(value)
                    for name in NATIVE_COUNTERS:
                        counters[name].append(int(r["timing"].get(name, 0)))
                    residual.append(dt_ms - seg["native_total"])
            window_s = time.perf_counter() - t_window0
            mem_after = metrics.sample(pid)
            assert last is not None and first_response is not None
            captured["step_response"] = first_response
            measured_window_s = sum(latencies) / 1e3
            step = {
                "definition": "wall-clock around one raw M1d `step` request (BattleShipClient.request): one accepted "
                              "step == one M1c native simulation tick. Rate = measured steps / sum of their latencies. "
                              "This is native stepping throughput, not a rendering frame rate.",
                "pid": pid, "warmup_steps": args.warmup_steps, "measured_steps": len(latencies),
                "action_pattern": ACTION_PATTERN,
                "latency_ms": describe(latencies, "ms"),
                "native_ticks_per_s": len(latencies) / measured_window_s if measured_window_s > 0 else None,
                "wall_window_s_including_warmup": window_s,
                "final_input_tick": last["observation"]["input_tick"],
                "final_time_passed": last["observation"]["time_passed"],
                "final_targets_remaining": last["observation"]["targets_remaining"],
                "memory_before": mem_before, "memory_after": mem_after,
                "cpu_per_step_ms": None,
                "native_timing": None,
            }
            if mem_before and mem_after and mem_before["cpu_user_s"] is not None and mem_after["cpu_user_s"] is not None:
                cpu = (mem_after["cpu_user_s"] + mem_after["cpu_kernel_s"]) - (mem_before["cpu_user_s"] + mem_before["cpu_kernel_s"])
                step["cpu_per_step_ms"] = cpu * 1e3 / total  # derived: child CPU time over the whole run / all steps
                step["cpu_time_definition"] = ("derived: (child user+kernel CPU time after - before) / (warm-up + measured "
                                                "steps). CPU time the game process spent per step; the rest of the wall "
                                                "latency is waiting (pacing, vsync, scheduling, socket).")
            if timing_seen:
                step["native_timing"] = {
                    "available": True, "steps_with_stamps": timing_seen,
                    "clock": "std::chrono::steady_clock, ns, inside the game process (SSB64_RL_TIMING=1)",
                    "segments": {name: {"contains": desc, "ms": describe(segments[name], "ms")}
                                 for name, _, _, desc in NATIVE_SEGMENTS},
                    "native_total_ms": describe(segments["native_total"], "ms"),
                    "counters": {name: describe(counters[name], "iterations") for name in NATIVE_COUNTERS},
                    "steps_with_one_host_iteration": sum(1 for v in counters["host_iterations"] if v == 1),
                    "client_residual_ms": {
                        "derived": "client wall latency - native_total: socket transit both ways, transport worker "
                                   "select() wake, nlohmann dump + send, Python json.dumps/json.loads and recv",
                        "ms": describe(residual, "ms"),
                    },
                }
            else:
                step["native_timing"] = {"available": False,
                                         "reason": "no `timing` object in step responses (build without the M4 "
                                                   "diagnostic, or SSB64_RL_TIMING not set)"}
            log(f"  raw step latency {fmt_stats(step['latency_ms'], 2)}")
            log(f"  native ticks/s = {step['native_ticks_per_s']:.2f}; child CPU per step = "
                f"{step['cpu_per_step_ms'] if step['cpu_per_step_ms'] is None else round(step['cpu_per_step_ms'], 2)} ms (derived)")
            if timing_seen:
                for name, _, _, _ in NATIVE_SEGMENTS:
                    log(f"    native {name:24s} {fmt_stats(describe(segments[name], 'ms'), 2)}")
                log(f"    native {'total':24s} {fmt_stats(describe(segments['native_total'], 'ms'), 2)}")
                log(f"    client residual (derived)  {fmt_stats(describe(residual, 'ms'), 2)}")
                for name in NATIVE_COUNTERS:
                    log(f"    native {name:24s} {fmt_stats(describe(counters[name], 'iterations'), 0)}")
            else:
                log("  native timing: unavailable (no `timing` in responses)")
            log(f"  final input_tick={last['observation']['input_tick']} time_passed={last['observation']['time_passed']} "
                f"targets={last['observation']['targets_remaining']}; {memory_summary(mem_after)}")
    finally:
        safe_close(episode)
    return rtt, step, captured


# -- section: gym step ---------------------------------------------------------------------------


def section_gym_step(args: argparse.Namespace, config: LaunchConfig, metrics: ProcessMetrics) -> Dict[str, Any]:
    try:
        from battleship_env import BattleShipBTTEnv  # noqa: WPS433 (optional dependency: gymnasium)
    except ImportError as exc:
        log(f"[step/gym] skipped: {exc}")
        return {"available": False, "reason": f"gymnasium import failed: {exc}"}
    total = args.warmup_steps + args.steps
    log(f"[step/gym] {args.warmup_steps} warm-up + {args.steps} measured BattleShipBTTEnv.step() calls")
    env = BattleShipBTTEnv(config, max_episode_steps=None)
    try:
        t0 = time.perf_counter()
        observation, info = env.reset()
        reset_s = time.perf_counter() - t0
        pid = info["pid"]
        mem_before = metrics.sample(pid)
        latencies: List[float] = []
        for i in range(total):
            action = pattern_gym_action(i)
            t0 = time.perf_counter()
            observation, reward, terminated, truncated, info = env.step(action)
            dt_ms = (time.perf_counter() - t0) * 1e3
            if info["consumed_tick"] != i or int(observation["input_tick"]) != i + 1:
                raise RuntimeError(f"pairing broken at gym step {i}")
            if terminated or truncated:
                raise RuntimeError(f"episode ended at gym step {i}")
            if i >= args.warmup_steps:
                latencies.append(dt_ms)
        mem_after = metrics.sample(pid)
        measured_window_s = sum(latencies) / 1e3
        result = {
            "available": True,
            "definition": "wall-clock around BattleShipBTTEnv.step(action): Gym action validation + conversion, the "
                          "raw M1d step, observation_to_gym (numpy 0-d arrays) and the info dict. One call == one "
                          "native tick.",
            "pid": pid, "reset_s": reset_s, "warmup_steps": args.warmup_steps, "measured_steps": len(latencies),
            "latency_ms": describe(latencies, "ms"),
            "native_ticks_per_s": len(latencies) / measured_window_s if measured_window_s > 0 else None,
            "final_input_tick": int(observation["input_tick"]),
            "memory_before": mem_before, "memory_after": mem_after,
        }
        log(f"  reset (M2 launch + observe) {reset_s:.3f} s; gym step latency {fmt_stats(result['latency_ms'], 2)}")
        log(f"  native ticks/s through the wrapper = {result['native_ticks_per_s']:.2f}; {memory_summary(mem_after)}")
        return result
    finally:
        env.close()


# -- section: serialization -----------------------------------------------------------------------


def _bench_us(stmt: Callable[[], Any], iterations: int, repeat: int = 5) -> Dict[str, float]:
    timer = timeit.Timer(stmt)
    runs = timer.repeat(repeat=repeat, number=iterations)
    per = [r / iterations * 1e6 for r in runs]
    return {"min_us": min(per), "median_us": statistics.median(per), "max_us": max(per),
            "iterations": iterations, "repeat": repeat}


def section_serialization(args: argparse.Namespace, captured: Dict[str, Any]) -> Dict[str, Any]:
    log(f"[serialization] Python json cost of representative M1d lines ({args.serialization_iterations} iterations x 5)")
    compact = {"separators": (",", ":")}
    step_request = {"protocol": PROTOCOL_VERSION, "op": "step", "buttons": int(Button.B), "stick_x": -37, "stick_y": 61}
    ping_request = {"protocol": PROTOCOL_VERSION, "op": "ping"}
    step_response = captured.get("step_response")
    observe_response = captured.get("observe_response")
    source = "captured from this run's real responses (re-dumped compactly)"
    if step_response is None:
        source = "synthetic (no real response captured in this run)"
        obs = {"observation_schema": 1, "host_frame": 380, "input_tick": 12, "time_passed": 11, "game_status": 1,
               "btt_active": 1, "targets_remaining": 10, "fighter_valid": 1, "position_x": -1234.5677490234375,
               "position_y": 78.25, "air_velocity_x": 0.0, "air_velocity_y": -2.3999998569488525,
               "ground_velocity_x": 0.0, "facing_direction": 1, "ground_air_state": 1, "fighter_status_id": 27,
               "jumps_used": 1}
        step_response = {"protocol": 1, "op": "step", "ok": True, "step_schema": 1, "state": 2,
                         "state_name": "WaitingForAction", "step_count": 12, "consumed_tick": 11, "observation": obs}
        observe_response = {"protocol": 1, "op": "observe", "ok": True, "state": 2, "state_name": "WaitingForAction",
                            "can_step": True, "step_count": 12, "observation": obs}
    if observe_response is None:  # step measured without the rtt section: same observation shape, observe framing
        observe_response = {"protocol": 1, "op": "observe", "ok": True, "state": step_response["state"],
                            "state_name": step_response["state_name"], "can_step": True,
                            "step_count": step_response["step_count"], "observation": step_response["observation"]}
    step_response_plain = {k: v for k, v in step_response.items() if k != "timing"}
    lines = {
        "step_request": json.dumps(step_request, **compact),
        "ping_request": json.dumps(ping_request, **compact),
        "step_response": json.dumps(step_response_plain, **compact),
        "step_response_with_timing": json.dumps(step_response, **compact),
        "observe_response": json.dumps(observe_response, **compact),
    }
    n = args.serialization_iterations
    results: Dict[str, Any] = {
        "definition": "timeit of json.dumps(obj, separators=(',', ':')) and json.loads(line) in this Python process, "
                      "in isolation from sockets and the game. Microseconds per call; min over 5 repeats is the "
                      "least-disturbed figure, median is typical.",
        "source_of_structures": source,
        "line_bytes": {k: len(v) for k, v in lines.items()},
        "dumps": {
            "step_request": _bench_us(lambda: json.dumps(step_request, **compact), n),
            "ping_request": _bench_us(lambda: json.dumps(ping_request, **compact), n),
        },
        "loads": {
            "step_response": _bench_us(lambda: json.loads(lines["step_response"]), n),
            "observe_response": _bench_us(lambda: json.loads(lines["observe_response"]), n),
            "ping_response": _bench_us(lambda: json.loads('{"protocol":1,"op":"ping","ok":true}'), n),
        },
    }
    if "timing" in step_response:
        results["loads"]["step_response_with_timing"] = _bench_us(lambda: json.loads(lines["step_response_with_timing"]), n)
    d = results["dumps"]["step_request"]["median_us"]
    l = results["loads"]["step_response"]["median_us"]
    results["derived"] = {
        "python_json_per_step_us": d + l,
        "note": "derived: dumps(step request) + loads(step response) medians; the Python JSON share of one step. "
                "The native nlohmann parse/dump cost is not measured here (see native_timing transport segments).",
    }
    line_bytes = dict(results["line_bytes"])
    line_bytes["ping_response"] = len('{"protocol":1,"op":"ping","ok":true}')
    for group in ("dumps", "loads"):
        for name, r in results[group].items():
            log(f"  {group:5s} {name:26s} {line_bytes.get(name, 0)!s:>4} B  "
                f"min={r['min_us']:.2f} us median={r['median_us']:.2f} us")
    log(f"  python json per step (derived) = {results['derived']['python_json_per_step_us']:.2f} us")
    return results


# -- section: multiprocess ----------------------------------------------------------------------------


@dataclass
class WorkerResult:
    index: int
    launch: Optional[LaunchTiming] = None
    steps: int = 0
    latencies_ms: List[float] = field(default_factory=list)
    active_s: float = 0.0
    error: Optional[str] = None
    memory: Optional[Dict[str, Any]] = None
    cleanup: Optional[str] = None
    final_input_tick: Optional[int] = None


def run_level(n: int, args: argparse.Namespace, config: LaunchConfig, metrics: ProcessMetrics,
              exe_name: str, baseline_count: Optional[int]) -> Dict[str, Any]:
    log(f"[multiprocess] level n={n}: launching {n} independent BattleShip processes concurrently")
    results = [WorkerResult(index=i) for i in range(n)]
    episodes = [BattleShipEpisode(config, index=3000 + n * 10 + i) for i in range(n)]
    launched = threading.Barrier(n)
    go = threading.Event()
    t_level0 = time.perf_counter()

    def worker(i: int) -> None:
        res, episode = results[i], episodes[i]
        try:
            res.launch = timed_start(episode)
            try:
                launched.wait(timeout=config.startup_timeout + config.ready_timeout + 30)
            except threading.BrokenBarrierError:
                pass
            if not res.launch.ok:
                return
            go.wait()
            client = episode.client
            assert client is not None
            deadline = time.perf_counter() + args.mp_seconds
            t_active0 = time.perf_counter()
            i_step = 0
            while time.perf_counter() < deadline:
                buttons, sx, sy = pattern_action(i_step)
                t0 = time.perf_counter()
                r = client.request("step", buttons=buttons, stick_x=sx, stick_y=sy)
                res.latencies_ms.append((time.perf_counter() - t0) * 1e3)
                if r["consumed_tick"] != i_step or r["state"] != int(StepState.WAITING_FOR_ACTION):
                    raise RuntimeError(f"pairing/state broken at step {i_step}: {r['consumed_tick']} {r['state_name']}")
                res.final_input_tick = r["observation"]["input_tick"]
                i_step += 1
            res.active_s = time.perf_counter() - t_active0
            res.steps = i_step
            res.memory = metrics.sample(episode.pid)
        except (BattleShipError, EpisodeFailure, RuntimeError) as exc:
            res.error = f"{type(exc).__name__}: {str(exc).splitlines()[0]}"
            try:
                launched.abort()
            except threading.BrokenBarrierError:
                pass

    threads = [threading.Thread(target=worker, args=(i,), name=f"bs-{n}-{i}", daemon=True) for i in range(n)]
    py_cpu0 = time.process_time()
    for t in threads:
        t.start()
    # Release the stepping window once every worker has either reached fresh or failed.
    while any(t.is_alive() and results[i].launch is None for i, t in enumerate(threads)):
        time.sleep(0.05)
    ready = sum(1 for r in results if r.launch and r.launch.ok)
    t_go = time.perf_counter()
    go.set()
    for t in threads:
        t.join()
    window_s = time.perf_counter() - t_go
    py_cpu = time.process_time() - py_cpu0
    cleanups = [safe_close(e) for e in episodes]
    for r, c in zip(results, cleanups):
        r.cleanup = c
    after_count = count_processes_named(exe_name)
    leak = (baseline_count is not None and after_count is not None and after_count > baseline_count)
    total_steps = sum(r.steps for r in results)
    per_process = []
    for r in results:
        per_process.append({
            "index": r.index, "pid": r.launch.pid if r.launch else None, "port": r.launch.port if r.launch else None,
            "startup_ok": bool(r.launch and r.launch.ok), "startup_outcome": r.launch.outcome if r.launch else "not_started",
            "startup_s": r.launch.pre_launch_to_fresh_s if r.launch else None,
            "steps": r.steps, "active_s": r.active_s,
            "steps_per_s": (r.steps / r.active_s) if r.active_s > 0 else None,
            "latency_ms": describe(r.latencies_ms, "ms"),
            "final_input_tick": r.final_input_tick, "memory_after": r.memory,
            "error": r.error, "cleanup_action": r.cleanup,
        })
    level = {
        "n": n, "ready": ready, "startup_failures": n - ready,
        "window_s": window_s, "requested_window_s": args.mp_seconds,
        "total_steps": total_steps,
        "aggregate_steps_per_s": total_steps / window_s if window_s > 0 else None,
        "aggregate_definition": "sum of steps completed by all processes during the shared window / window wall time "
                                "(window opens when every process is fresh and closes when the last worker returns)",
        "per_process_steps_per_s": describe([p["steps_per_s"] for p in per_process if p["steps_per_s"]], "steps/s"),
        "per_process_latency_ms_all": describe([x for r in results for x in r.latencies_ms], "ms"),
        "startup_s": describe([p["startup_s"] for p in per_process if p["startup_s"] is not None], "s"),
        "memory_after_mib": {
            "working_set": describe([mib(p["memory_after"]["working_set_bytes"]) for p in per_process if p["memory_after"]], "MiB"),
            "peak_working_set": describe([mib(p["memory_after"]["peak_working_set_bytes"]) for p in per_process if p["memory_after"]], "MiB"),
            "private": describe([mib(p["memory_after"]["private_bytes"]) for p in per_process if p["memory_after"]], "MiB"),
        },
        "driver_python_cpu_s": py_cpu,
        "driver_note": "all processes are driven from ONE Python process with one thread per BattleShip (socket I/O "
                       "releases the GIL); driver_python_cpu_s is that process's CPU time over the level.",
        "process_count_after_cleanup": after_count, "process_leak": leak,
        "errors": [p["error"] for p in per_process if p["error"]],
        "per_process": per_process,
        "level_wall_s": time.perf_counter() - t_level0,
    }
    agg = level["aggregate_steps_per_s"]
    log(f"  n={n}: ready={ready}/{n} window={window_s:.1f}s total_steps={total_steps} "
        f"aggregate={agg if agg is None else round(agg, 2)} steps/s per_process={fmt_stats(level['per_process_steps_per_s'], 2)}")
    log(f"  n={n}: latency {fmt_stats(level['per_process_latency_ms_all'], 2)}; startup {fmt_stats(level['startup_s'], 2)}; "
        f"ws {fmt_stats(level['memory_after_mib']['working_set'], 1)}; leak={leak}; driver cpu={py_cpu:.2f}s")
    for e in level["errors"]:
        log(f"  n={n}: ERROR {e}")
    return level


def section_multiprocess(args: argparse.Namespace, config: LaunchConfig, metrics: ProcessMetrics, exe_name: str) -> Dict[str, Any]:
    logical = os.cpu_count() or 1
    candidate = max(1, logical - 1)
    max_n = args.max_processes if args.max_processes is not None else candidate
    baseline = count_processes_named(exe_name)
    levels = []
    for n in range(1, max_n + 1):
        level = run_level(n, args, config, metrics, exe_name, baseline)
        levels.append(level)
        if level["process_leak"]:
            log("  stopping the sweep: a BattleShip process leaked")
            break
        if level["ready"] == 0:
            log("  stopping the sweep: no process reached fresh at this level")
            break
    return {
        "definition": "independent BattleShip processes stepped concurrently (own OS process, M2 episode dir, port, "
                      "client, thread). Aggregate = total steps in the shared window / window wall time.",
        "logical_cpus": logical, "candidate_n": candidate, "tested_max_n": max_n, "window_s": args.mp_seconds,
        "action_pattern": ACTION_PATTERN,
        "levels": levels,
    }


# -- section: reliability ------------------------------------------------------------------------------

RELIABILITY_CATEGORIES = (
    "startup_failure", "startup_timeout", "readiness_timeout", "not_fresh", "transport_failure",
    "premature_exit", "episode_timeout", "request_rejected", "incorrect_terminal_result",
    "exit_timeout", "exit_failure", "result_invalid", "cleanup_failure", "process_leak",
)


def run_reliability_episode(index: int, config: LaunchConfig, rows: Sequence[ReplayRow], exe_name: str,
                            baseline_count: Optional[int]) -> Dict[str, Any]:
    record: Dict[str, Any] = {"episode": index, "ok": False, "category": None, "detail": None,
                              "pid": None, "port": None, "startup_s": None, "stepping_s": None,
                              "steps": 0, "last_consumed_tick": None, "completion_time_passed": None,
                              "completion_input_tick": None, "targets_remaining": None, "exit_code": None,
                              "cleanup_action": None}
    episode = BattleShipEpisode(config, index=4000 + index)
    try:
        launch = timed_start(episode)
        record["pid"], record["port"], record["startup_s"] = launch.pid, launch.port, launch.pre_launch_to_fresh_s
        if not launch.ok:
            record["category"], record["detail"] = launch.outcome, launch.error
            return record
        client = episode.client
        assert client is not None
        previous: Optional[Observation] = None
        terminal: Optional[StepResult] = None
        t0 = time.perf_counter()
        try:
            for row_index, row in enumerate(rows):
                result = client.step(row.buttons, row.stick_x, row.stick_y)
                check_step(row_index, result, previous)
                record["steps"] = result.step_count
                record["last_consumed_tick"] = result.consumed_tick
                previous = result.observation
                if result.observation.targets_remaining == 0:
                    check_completion(row_index, result)
                    terminal = result
                    break
        except BattleShipError as exc:
            failure = episode.classify_step_failure(exc)
            record["category"], record["detail"] = failure.outcome.value, str(failure).splitlines()[0]
            record["exit_code"] = failure.exit_code
            return record
        except RegressionFailure as exc:
            record["category"], record["detail"] = "incorrect_terminal_result", exc.reason
            return record
        record["stepping_s"] = time.perf_counter() - t0
        if terminal is None:
            record["category"], record["detail"] = "incorrect_terminal_result", "all source rows consumed without completion"
            return record
        o = terminal.observation
        record["completion_time_passed"], record["completion_input_tick"] = o.time_passed, o.input_tick
        record["targets_remaining"] = o.targets_remaining
        try:
            done = episode.finish(terminal)
        except EpisodeFailure as exc:
            record["category"], record["detail"], record["exit_code"] = exc.outcome.value, str(exc).splitlines()[0], exc.exit_code
            return record
        record["exit_code"] = done.exit_code
        for key, expected in EXPECTED_RESULT.items():
            if done.result.get(key) != expected:
                record["category"] = "incorrect_terminal_result"
                record["detail"] = f"result JSON {key} is {done.result.get(key)!r}, expected {expected!r}"
                return record
        record["ok"] = True
        return record
    finally:
        record["cleanup_action"] = safe_close(episode)
        if str(record["cleanup_action"]).startswith("cleanup_failure"):
            record["ok"], record["category"] = False, "cleanup_failure"
        after = count_processes_named(exe_name)
        if baseline_count is not None and after is not None and after > baseline_count:
            record["ok"], record["category"] = False, "process_leak"
            record["detail"] = f"{exe_name} count {after} > baseline {baseline_count} after cleanup"


def section_reliability(args: argparse.Namespace, config: LaunchConfig, exe_name: str) -> Dict[str, Any]:
    rows = read_btti_rows(args.replay)
    if len(rows) != SOURCE_ROWS:
        raise ReplayFormatError(f"{args.replay} has {len(rows)} rows; the baseline has {SOURCE_ROWS}")
    log(f"[reliability] {args.reliability_episodes} consecutive fresh-process baseline episodes (no retries)")
    baseline = count_processes_named(exe_name)
    episodes = []
    for i in range(1, args.reliability_episodes + 1):
        rec = run_reliability_episode(i, config, rows, exe_name, baseline)
        episodes.append(rec)
        if rec["ok"]:
            log(f"  episode {i}: OK pid={rec['pid']} startup={rec['startup_s']:.2f}s stepping={rec['stepping_s']:.2f}s "
                f"steps={rec['steps']} last_consumed_tick={rec['last_consumed_tick']} "
                f"completion={rec['completion_time_passed']}/{rec['completion_input_tick']} exit={rec['exit_code']} "
                f"cleanup={rec['cleanup_action']}")
        else:
            log(f"  episode {i}: FAIL {rec['category']}: {rec['detail']} (steps={rec['steps']}, cleanup={rec['cleanup_action']})")
    ok = [e for e in episodes if e["ok"]]
    categories = {c: sum(1 for e in episodes if e["category"] == c) for c in RELIABILITY_CATEGORIES}
    other = [e["category"] for e in episodes if not e["ok"] and e["category"] not in RELIABILITY_CATEGORIES]
    result = {
        "definition": "each episode: NEW BattleShip process (M2), fresh gate, tas_input_2/mario_743.btti fed one row "
                      "per M1d step with the M1e per-step checks, terminal EpisodeEnded at consumed_tick 446 / "
                      "input_tick 447 / time_passed 446 / step_count 447, native clean exit 0, result JSON equal to "
                      "the frozen M1a values, cleanup, machine-wide process count unchanged. No retries.",
        "attempted": len(episodes), "successful": len(ok), "failed": len(episodes) - len(ok),
        "failure_rate": (len(episodes) - len(ok)) / len(episodes) if episodes else None,
        "failure_categories": {k: v for k, v in categories.items() if v} | ({"other": other} if other else {}),
        "startup_s": describe([e["startup_s"] for e in episodes if e["startup_s"] is not None], "s"),
        "stepping_s": describe([e["stepping_s"] for e in ok], "s"),
        "expected_terminal": {"steps": COMPLETION_STEPS, "last_consumed_tick": COMPLETION_CONSUMED_TICK,
                              "completion_time_passed": COMPLETION_TIME_PASSED,
                              "completion_input_tick": COMPLETION_INPUT_TICK, "rows_unsent": SOURCE_ROWS - COMPLETION_STEPS},
        "episodes": episodes,
    }
    log(f"  attempted={result['attempted']} successful={result['successful']} failed={result['failed']} "
        f"failure_rate={result['failure_rate']}")
    return result


# -- driver ---------------------------------------------------------------------------------------------


def environment_info(args: argparse.Namespace, exe: Path, metrics: ProcessMetrics) -> Dict[str, Any]:
    uname = platform.uname()
    return {
        "platform": {"system": uname.system, "release": uname.release, "version": uname.version,
                     "machine": uname.machine, "processor": uname.processor},
        "python": {"version": platform.python_version(), "implementation": platform.python_implementation()},
        "logical_cpus": os.cpu_count(),
        "executable": {"name": exe.name, "repo_relative_path": relative_to_repo(exe), "size_bytes": exe.stat().st_size,
                       "mtime_utc": datetime.fromtimestamp(exe.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"),
                       "sha256": sha256_of(exe), "git": git_describe()},
        "contracts": {"protocol": PROTOCOL_VERSION, "observation_schema": OBSERVATION_SCHEMA, "m3_action_contract": ENV_CONTRACT,
                      "native_timing_env": NATIVE_TIMING_ENV},
        "memory_definition": metrics.definition,
        "child_extra_env": dict(args.child_env),
    }


def parse_kv(values: Sequence[str]) -> List[Tuple[str, str]]:
    out = []
    for v in values:
        key, sep, val = v.partition("=")
        if not sep or not key:
            raise argparse.ArgumentTypeError(f"--child-env expects KEY=VALUE, got {v!r}")
        out.append((key, val))
    return out


def parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--exe", default=str(DEFAULT_EXECUTABLE), help="BattleShip executable (default: %(default)s)")
    parser.add_argument("--run-dir", default=None, help="parent of the per-episode directories (default: a new temp dir)")
    parser.add_argument("--out", default=None, help="JSON report path (default: <run-dir>/bench_<timestamp>.json)")
    parser.add_argument("--only", default=",".join(SECTIONS), help=f"comma-separated sections (default: all of {','.join(SECTIONS)})")
    parser.add_argument("--startup-samples", type=int, default=5)
    parser.add_argument("--steps", type=int, default=600, help="measured sequential steps per stepping run (default: %(default)s)")
    parser.add_argument("--warmup-steps", type=int, default=30)
    parser.add_argument("--rtt-samples", type=int, default=500)
    parser.add_argument("--serialization-iterations", type=int, default=20000)
    parser.add_argument("--max-processes", type=int, default=None, help="top of the 1..N sweep (default: os.cpu_count() - 1, min 1)")
    parser.add_argument("--mp-seconds", type=float, default=10.0, help="concurrent stepping window per level (default: %(default)s)")
    parser.add_argument("--reliability-episodes", type=int, default=10)
    parser.add_argument("--replay", default=str(DEFAULT_REPLAY))
    parser.add_argument("--child-env", action="append", default=[], metavar="KEY=VALUE",
                        help="extra environment for every BattleShip child (applied before the mandatory M2 settings)")
    parser.add_argument("--no-native-timing", action="store_true",
                        help=f"do not set {NATIVE_TIMING_ENV}=1 for the children (default: set it; harmless on builds without it)")
    parser.add_argument("--startup-timeout", type=float, default=60.0)
    parser.add_argument("--ready-timeout", type=float, default=180.0)
    parser.add_argument("--request-timeout", type=float, default=30.0)
    parser.add_argument("--exit-timeout", type=float, default=30.0)
    args = parser.parse_args(argv)
    args.sections = [s.strip() for s in args.only.split(",") if s.strip()]
    unknown = [s for s in args.sections if s not in SECTIONS]
    if unknown:
        parser.error(f"unknown section(s) {unknown}; choose from {SECTIONS}")
    for name in ("startup_samples", "steps", "rtt_samples", "serialization_iterations", "reliability_episodes"):
        if getattr(args, name) < 1:
            parser.error(f"--{name.replace('_', '-')} must be >= 1")
    if args.warmup_steps < 0 or args.mp_seconds <= 0:
        parser.error("--warmup-steps must be >= 0 and --mp-seconds > 0")
    if args.max_processes is not None and args.max_processes < 1:
        parser.error("--max-processes must be >= 1")
    args.child_env = parse_kv(args.child_env)
    if not args.no_native_timing and NATIVE_TIMING_ENV not in dict(args.child_env):
        args.child_env.append((NATIVE_TIMING_ENV, "1"))
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    exe = Path(args.exe)
    if not exe.is_file():
        log(f"ERROR: executable not found: {exe}")
        return 2
    run_root = Path(args.run_dir) if args.run_dir else Path(tempfile.mkdtemp(prefix="battleship_m4_bench_"))
    run_root.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out) if args.out else run_root / f"bench_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    metrics = ProcessMetrics()
    config = LaunchConfig(
        executable=exe, run_root=run_root, startup_timeout=args.startup_timeout, ready_timeout=args.ready_timeout,
        request_timeout=args.request_timeout, exit_timeout=args.exit_timeout, extra_env=dict(args.child_env),
    )
    report: Dict[str, Any] = {
        "benchmark_schema": BENCHMARK_SCHEMA,
        "tool": "rl/tools/bench.py",
        "timestamp_utc": utc_now(),
        "environment": environment_info(args, exe, metrics),
        "parameters": {k: v for k, v in vars(args).items() if k not in ("exe", "run_dir", "out", "replay", "child_env")}
                      | {"replay": relative_to_repo(Path(args.replay)), "child_env": dict(args.child_env)},
        "process_count_before": count_processes_named(exe.name),
        "sections": {},
        "errors": {},
    }
    log(f"M4 bench: exe={exe.name} sha256={report['environment']['executable']['sha256'][:12]} "
        f"cpus={os.cpu_count()} sections={','.join(args.sections)} run_dir={run_root}")
    log(f"  {exe.name} processes before: {report['process_count_before']}")
    captured: Dict[str, Any] = {}
    t_all0 = time.perf_counter()

    def run(name: str, fn: Callable[[], Any]) -> None:
        t0 = time.perf_counter()
        try:
            report["sections"][name] = fn()
        except Exception as exc:  # noqa: BLE001 - one failing section must not lose the others
            report["errors"][name] = f"{type(exc).__name__}: {exc}"
            log(f"[{name}] ERROR {type(exc).__name__}: {exc}")
            traceback.print_exc()
        report.setdefault("section_wall_s", {})[name] = round(time.perf_counter() - t0, 2)

    if "startup" in args.sections:
        run("startup", lambda: section_startup(args, config, metrics))
    want_rtt, want_step = "rtt" in args.sections, "step" in args.sections
    if want_rtt or want_step:
        def _rtt_step() -> Any:
            rtt, raw, cap = section_rtt_and_raw_step(args, config, metrics, want_rtt, want_step)
            captured.update(cap)
            if rtt is not None:
                report["sections"]["rtt"] = rtt
            if raw is not None:
                report["sections"]["step"] = {"raw_client": raw}
            return None
        run("rtt_step", _rtt_step)
        report["sections"].pop("rtt_step", None)
        if want_step:
            def _gym() -> Any:
                gym = section_gym_step(args, config, metrics)
                report["sections"].setdefault("step", {})["gym_env"] = gym
                raw = report["sections"]["step"].get("raw_client") or {}
                if gym.get("available") and raw.get("latency_ms", {}).get("count"):
                    report["sections"]["step"]["derived"] = {
                        "gym_minus_raw_median_ms": gym["latency_ms"]["median"] - raw["latency_ms"]["median"],
                        "note": "derived: M3 wrapper overhead per step, difference of two separately measured medians "
                                "on two different processes",
                    }
                return None
            run("gym_step", _gym)
            report["sections"].pop("gym_step", None)
    if "serialization" in args.sections:
        run("serialization", lambda: section_serialization(args, captured))
    if "memory" in args.sections:
        # Memory is sampled inside the startup / step / multiprocess sections; this collects the definition
        # and the headline samples so the section exists on its own.
        def _memory() -> Any:
            s = report["sections"]
            return {
                "definition": metrics.definition,
                "at_fresh": [x["memory_at_fresh"] for x in s.get("startup", {}).get("samples", []) if x.get("memory_at_fresh")],
                "after_raw_stepping": s.get("step", {}).get("raw_client", {}).get("memory_after"),
                "after_gym_stepping": s.get("step", {}).get("gym_env", {}).get("memory_after"),
                "note": "per-level samples for concurrent processes are in sections.multiprocess.levels[*].per_process[*].memory_after",
            }
        run("memory", _memory)
        m = report["sections"].get("memory", {})
        for label, sample in (("fresh", (m.get("at_fresh") or [None])[0]), ("after raw stepping", m.get("after_raw_stepping"))):
            log(f"[memory] {label}: {memory_summary(sample)}")
    if "multiprocess" in args.sections:
        run("multiprocess", lambda: section_multiprocess(args, config, metrics, exe.name))
    if "reliability" in args.sections:
        run("reliability", lambda: section_reliability(args, config, exe.name))

    report["process_count_after"] = count_processes_named(exe.name)
    report["total_wall_s"] = round(time.perf_counter() - t_all0, 1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fp:
        json.dump(report, fp, indent=2)
    print_summary(report)
    log(f"  {exe.name} processes after: {report['process_count_after']} (before: {report['process_count_before']})")
    log(f"report={out_path}")
    leaked = (report["process_count_before"] is not None and report["process_count_after"] is not None
              and report["process_count_after"] > report["process_count_before"])
    return 1 if (report["errors"] or leaked) else 0


def print_summary(report: Dict[str, Any]) -> None:
    s = report["sections"]
    log("")
    log("M4 benchmark summary")
    log(f"  build {report['environment']['executable']['name']} sha256={report['environment']['executable']['sha256'][:12]} "
        f"git={report['environment']['executable']['git'].get('head')} dirty={report['environment']['executable']['git'].get('dirty')}; "
        f"{report['environment']['platform']['system']} {report['environment']['platform']['release']}; "
        f"python {report['environment']['python']['version']}; logical cpus {report['environment']['logical_cpus']}")
    if "startup" in s:
        st = s["startup"]
        log(f"  startup-to-fresh  {fmt_stats(st['pre_launch_to_fresh'], 3)} (ok {st['succeeded']}/{st['attempted']})")
    if "step" in s:
        raw, gym = s["step"].get("raw_client"), s["step"].get("gym_env")
        if raw and raw.get("latency_ms"):
            log(f"  raw M1d step      {fmt_stats(raw['latency_ms'], 2)}  -> {raw['native_ticks_per_s']:.2f} native ticks/s; "
                f"child CPU/step {raw['cpu_per_step_ms'] if raw['cpu_per_step_ms'] is None else round(raw['cpu_per_step_ms'], 2)} ms (derived)")
            nt = raw.get("native_timing") or {}
            if nt.get("available"):
                for name, seg in nt["segments"].items():
                    log(f"    {name:24s} median {seg['ms']['median']:.2f} ms  p95 {seg['ms']['p95']:.2f} ms")
                log(f"    {'native_total':24s} median {nt['native_total_ms']['median']:.2f} ms; client residual median "
                    f"{nt['client_residual_ms']['ms']['median']:.2f} ms (derived)")
        if gym and gym.get("available"):
            log(f"  M3 env.step       {fmt_stats(gym['latency_ms'], 2)}  -> {gym['native_ticks_per_s']:.2f} native ticks/s")
    if "rtt" in s and s["rtt"].get("ping"):
        r = s["rtt"]
        log(f"  RTT ping/status/observe medians {r['ping']['median']:.3f} / {r['status']['median']:.3f} / {r['observe']['median']:.3f} ms "
            f"(p95 {r['ping']['p95']:.3f} / {r['status']['p95']:.3f} / {r['observe']['p95']:.3f})")
    if "serialization" in s:
        se = s["serialization"]
        log(f"  Python JSON per step (derived) {se['derived']['python_json_per_step_us']:.1f} us "
            f"(dumps request {se['dumps']['step_request']['median_us']:.1f} + loads response {se['loads']['step_response']['median_us']:.1f})")
    if "multiprocess" in s:
        for lv in s["multiprocess"]["levels"]:
            agg = lv["aggregate_steps_per_s"]
            log(f"  N={lv['n']}: ready {lv['ready']}/{lv['n']} aggregate {agg if agg is None else round(agg, 2)} steps/s, "
                f"per-process median {lv['per_process_steps_per_s'].get('median', float('nan')):.2f} steps/s, "
                f"ws median {round(lv['memory_after_mib']['working_set'].get('median') or 0, 1)} MiB, leak={lv['process_leak']}, errors={len(lv['errors'])}")
    if "reliability" in s:
        r = s["reliability"]
        log(f"  reliability {r['successful']}/{r['attempted']} ok, failure rate {r['failure_rate']}, categories {r['failure_categories']}")
    if report["errors"]:
        log(f"  section errors: {report['errors']}")


if __name__ == "__main__":
    sys.exit(main())
