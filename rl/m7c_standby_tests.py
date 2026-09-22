#!/usr/bin/env python3
"""M7c standby-lifecycle tests: state machine, configuration, semantic equivalence, failure and cleanup paths.

    python rl/m7c_standby_tests.py                 # every case, in order (game cases launch BattleShip)
    python rl/m7c_standby_tests.py unit            # the no-game unit cases only
    python rl/m7c_standby_tests.py cold_vs_standby_replay shutdown_active_and_ready

No-game unit cases: unit_state_machine (every StandbyManager transition with a fake launcher),
unit_readiness_contract, unit_config_lifecycle (schema, profiles, dry run, fingerprints),
unit_resume_lifecycle (checkpoint compatibility across lifecycle modes).

Game cases (sequential): cold_vs_standby_replay (the authoritative 447-action replay: one cold reference
against 1 cold + 10 standby-promoted episodes, every submitted action, consumed tick, observation field,
terminal value, reward and canonical artifact compared; v2 too), terminal_paths_promotion (fall, horizon
truncation and promotion after each, v1 and v2 returns), shutdown_active_and_ready, shutdown_while_starting,
wait_timeout_fallback, interrupt_active_play, interrupt_during_standby_launch, worker_exception_both_slots,
active_timeout_then_promotion, standby_startup_timeout_retry, standby_bind_failure_retry,
standby_lost_after_ready, standby_exhausted_cold_fallback, job_object_kill_standby, startup_contention,
v2_standby_smoke, resume_lifecycle_game.

After every case: zero BattleShip.exe processes, no listening socket left on any port a worker used, and the
user's build-us/Release/BattleShip.cfg.json byte-identical (sha256 and mtime) to its value at the start of
the suite. Outputs go under runs/_m7c_tests_<utc>/ (git-ignored). Standard library + NumPy + Gymnasium at
module level only: spawn children re-import this file.
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import experiment_config as ec  # noqa: E402
from btt_rewards import REWARD_V1, REWARD_V2, RewardContract, expected_return  # noqa: E402
from m7_smoke import (  # noqa: E402
    EXECUTABLE,
    FALL_TICK,
    FLAGS,
    REPLAY,
    USER_CONFIG,
    CaseFailure,
    Suite,
    _obs,
    artifact_rows_are_canonical,
    battleship_pids,
    check,
    fall_script,
    log,
    prepare_workers,
    short_config,
)
from m7b_smoke import V1_TOML, V2_TOML, FALL_RETURN_V1, FALL_RETURN_V2, TAS_RETURN, derive  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
V1_STANDBY_TOML = REPO_ROOT / "rl" / "configs" / "m7_mario_us_reward_v1_standby.toml"
V2_STANDBY_TOML = REPO_ROOT / "rl" / "configs" / "m7_mario_us_reward_v2_standby.toml"
PILOT_FINAL = REPO_ROOT / "runs" / "m7a_pilot_n5" / "final"
COMPLETION_STEPS = 447
NEUTRAL_T1 = [0, 0]   # Track 1 neutral stick, no button
STANDBY_KW = dict(standby_preboot=True, standby_count=1)


# -- shared helpers ---------------------------------------------------------------------------------------------


def listening_ports() -> List[int]:
    """Loopback TCP ports with a LISTENING socket right now (netstat; [] if unavailable)."""
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True, timeout=30, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    ports = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0].upper() == "TCP" and parts[3].upper() == "LISTENING" and parts[1].startswith("127.0.0.1:"):
            try:
                ports.append(int(parts[1].rsplit(":", 1)[1]))
            except ValueError:
                pass
    return ports


def ports_used(report: Dict[str, Any]) -> List[int]:
    ports = {a["port"] for a in report.get("startup_attempts", []) if a.get("port")}
    for h in (report.get("standby") or {}).get("manager", {}).get("history", []):
        for a in h.get("attempts", []):
            if a.get("port"):
                ports.add(a["port"])
    return sorted(ports)


def check_cleanup(reports: Dict[Any, Optional[Dict[str, Any]]], where: str) -> Dict[str, Any]:
    """Zero processes, every standby thread joined, no listening socket left on the ports used."""
    left = battleship_pids()
    check(not left, f"{where}: BattleShip left running: {left}")
    used: List[int] = []
    for rank, r in reports.items():
        if not r:
            continue
        sb = (r.get("standby") or {}).get("manager")
        if sb is not None:
            check(not sb.get("thread_alive") and sb.get("threads_started") == sb.get("threads_joined"),
                  f"{where}: rank {rank} standby thread not joined: started {sb.get('threads_started')} joined "
                  f"{sb.get('threads_joined')} alive {sb.get('thread_alive')}")
            check(sb.get("state") == "no_standby", f"{where}: rank {rank} standby state {sb.get('state')} after close")
        used += ports_used(r)
    still = sorted(set(used) & set(listening_ports()))
    check(not still, f"{where}: ports still listening after close: {still}")
    return {"ports_used": sorted(set(used)), "battleship_after": left}


def standby_spec(**kw: Any) -> Dict[str, Any]:
    d = dict(rank=0, horizon=3600, preserve_all=True, exit_timeout=5.0, **STANDBY_KW)
    d.update(kw)
    return d


class VecRun:
    """A vector run over one or more workers with per-episode Track 1 scripts; collects reset infos and summaries."""

    def __init__(self, base: Path, specs: Sequence[Dict[str, Any]], run_id: str, *, step_timeout: float = 240.0,
                 periodic: Optional[int] = None):
        from m7_vec_env import M7SubprocVecEnv

        self.factories, self.coord = prepare_workers(base, specs, run_id, periodic=periodic)
        self.venv = M7SubprocVecEnv(self.factories, step_timeout=step_timeout)
        self.n = len(specs)
        self.resets: List[List[Dict[str, Any]]] = [[] for _ in specs]      # reset infos per worker (initial + auto)
        self.episodes: List[List[Dict[str, Any]]] = [[] for _ in specs]    # m7_episode summaries per worker
        self.first_step_info: List[Optional[Dict[str, Any]]] = [None] * self.n
        self.steps = 0
        self.reports: Dict[Any, Optional[Dict[str, Any]]] = {}

    def reset(self) -> None:
        self.venv.reset()
        for i in range(self.n):
            self.resets[i].append(dict(self.venv.reset_infos[i]))

    def step(self, actions: Sequence[Sequence[int]]) -> Tuple[Any, Any, Any, List[Dict[str, Any]]]:
        obs, rew, dones, infos = self.venv.step(np.array(actions))
        self.steps += 1
        for i in range(self.n):
            if self.first_step_info[i] is None:
                self.first_step_info[i] = dict(infos[i])
            if dones[i]:
                self.episodes[i].append(infos[i]["m7_episode"])
                self.resets[i].append(dict(self.venv.reset_infos[i]))
        return obs, rew, dones, infos

    def run_episodes(self, scripts: Sequence[Callable[[int], List[int]]], *, max_steps: int = 20000) -> None:
        """Episode k of worker 0 follows scripts[k]; other workers follow scripts[0] (single-worker cases)."""
        idx = [0] * self.n
        pos = [0] * self.n
        while min(len(e) for e in self.episodes) < len(scripts) and self.steps < max_steps:
            actions = []
            for i in range(self.n):
                k = min(len(self.episodes[i]), len(scripts) - 1)
                actions.append(scripts[k](pos[i]))
            _o, _r, dones, _i = self.step(actions)
            for i in range(self.n):
                pos[i] = 0 if dones[i] else pos[i] + 1
                idx[i] += 1
        check(min(len(e) for e in self.episodes) >= len(scripts), f"only {[len(e) for e in self.episodes]} episodes in {self.steps} steps")

    def snapshot(self, rank: int = 0) -> Dict[str, Any]:
        return self.venv.env_method("standby_snapshot", indices=[rank])[0]

    def settle(self, rank: int = 0, timeout: float = 120.0) -> Dict[str, Any]:
        return self.venv.env_method("wait_standby_settled", timeout, indices=[rank])[0]

    def close(self) -> Dict[str, Any]:
        self.venv.close()
        self.reports = self.venv.worker_reports()
        return {k: v for k, v in (self.venv.close_report or {}).items() if k != "ranks"}

    def modes(self, rank: int = 0) -> List[Optional[str]]:
        return [(r.get("m7_startup") or {}).get("mode") for r in self.resets[rank]]


def neutral(_i: int) -> List[int]:
    return list(NEUTRAL_T1)


# -- unit: the state machine with a fake launcher -----------------------------------------------------------------


class _FakeProcess:
    def __init__(self) -> None:
        self.returncode: Optional[int] = None
        self.terminated = False

    def poll(self) -> Optional[int]:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = 1


class _FakeClient:
    def __init__(self, ep: "_FakeEpisode") -> None:
        self.ep = ep

    def status(self):
        from battleship_client import ConnectionClosed, Status, StepState

        if self.ep.fail_requests:
            raise ConnectionClosed("fake: connection lost")
        return Status(state=StepState.WAITING_FOR_ACTION, state_name="WaitingForAction", can_step=True, step_count=self.ep.step_count)

    def observe(self):
        return _fake_observe(self.ep.step_count, self.ep.input_tick)

    def close(self) -> None:
        pass


def _fake_observe(step_count: int = 0, input_tick: int = 0):
    from battleship_client import Observe, StepState

    return Observe(state=StepState.WAITING_FOR_ACTION, state_name="WaitingForAction", can_step=True, step_count=step_count,
                   observation=_obs(input_tick=input_tick, time_passed=0, host_frame=64))


class _FakeEpisode:
    def __init__(self, pid: int, port: int) -> None:
        self.process = _FakeProcess()
        self.pid, self.port = pid, port
        self.client = _FakeClient(self)
        self.paths = None
        self.config = None
        self.closed = False
        self.fail_requests = False
        self.step_count = 0
        self.input_tick = 0

    @property
    def alive(self) -> bool:
        return self.process.poll() is None

    def close(self) -> str:
        self.closed = True
        if self.process.returncode is None:
            self.process.returncode = 0
        return "terminated"


class _FakeLauncher:
    """launch_fn whose per-attempt behaviour is scripted: ok | fail | block | raise."""

    def __init__(self, script: Sequence[str]) -> None:
        self.script = list(script)
        self.calls: List[Tuple[int, int]] = []
        self.release = threading.Event()
        self.episodes: List[_FakeEpisode] = []
        self.saw_cancel = False
        self.pid = 1000

    def __call__(self, generation: int, attempt: int, manager: Any):
        from battleship_process import EpisodeFailure, EpisodeOutcome
        from m7_standby import LaunchOutcome, verify_readiness

        self.calls.append((generation, attempt))
        behaviour = self.script[min(len(self.calls), len(self.script)) - 1]
        self.pid += 1
        ep = _FakeEpisode(self.pid, 40000 + self.pid)
        manager.note_inflight(ep.process, ep.pid, ep.port)
        if behaviour == "raise":
            raise RuntimeError("fake launcher bug")
        if behaviour == "block":
            while not self.release.is_set() and ep.process.poll() is None:
                time.sleep(0.01)
            if ep.process.poll() is not None:
                self.saw_cancel = manager.cancelled()
                ep.close()
                raise EpisodeFailure(EpisodeOutcome.STARTUP_FAILURE, "fake: process exited (terminated by cancel)")
        if behaviour == "fail":
            ep.close()
            raise EpisodeFailure(EpisodeOutcome.TRANSPORT_FAILURE, "fake: transport never reachable")
        self.episodes.append(ep)
        obs = ep.client.observe()
        proof = verify_readiness(obs, {"no_render": True, "raphnet_disabled": True},
                                 {"no_render": True, "raphnet_disabled": True}, 10)
        return LaunchOutcome(episode=ep, observe=obs, proof=proof, runtime_dir="fake", resource={"cpu_user_s": 0.0})


def _wait_state(manager: Any, wanted: Sequence[str], timeout: float = 10.0) -> str:
    deadline = time.monotonic() + timeout
    while manager.state.value not in wanted and time.monotonic() < deadline:
        time.sleep(0.005)
    return manager.state.value


def unit_state_machine(suite: Suite) -> Dict[str, Any]:
    from m7_standby import StandbyError, StandbyManager, StandbyState

    out: Dict[str, Any] = {}
    # 1. happy path: launch -> starting -> ready -> acquire -> promoting -> promoted -> no_standby
    fl = _FakeLauncher(["ok"])
    m = StandbyManager(rank=0, launch_fn=fl, startup_attempts=3, join_timeout=5)
    check(m.state == StandbyState.NO_STANDBY and m.acquire(0.1).kind == "none", "initial state")
    rec = m.launch(2, profile={"p": 1})
    check(m.state in (StandbyState.STARTING, StandbyState.READY), "launch -> starting")
    check(_wait_state(m, ["ready"]) == "ready", "ready never reached")
    check(m.standby_pid() == fl.episodes[0].pid and m.live_standby_processes() == 1, "standby pid / liveness")
    a = m.acquire(1.0, targets_total=10)
    check(a.kind == "ready" and a.record is rec and a.observe is not None and m.state == StandbyState.PROMOTING, f"acquire {a.kind}")
    check(rec.startup_s is not None and rec.ready_before_promotion_s is not None and rec.proof["input_tick"] == 0, "record timing/proof")
    done = m.promoted({"cpu_user_s": 0.1})
    check(done.outcome == "promoted" and m.state == StandbyState.NO_STANDBY and m.record is None, "promoted -> no_standby")
    check(not fl.episodes[0].closed, "a promoted episode must not be closed by the manager")
    check(m.counts["launches"] == 1 and m.counts["ready"] == 1 and m.counts["promoted"] == 1, str(m.counts))
    out["happy"] = m.report()["counts"]
    # 2. launch while starting refused; cancel during starting terminates the in-flight process and joins
    fl = _FakeLauncher(["block"])
    m = StandbyManager(rank=0, launch_fn=fl, startup_attempts=3, join_timeout=5)
    m.launch(3)
    time.sleep(0.05)
    check(m.state == StandbyState.STARTING and m.thread_alive(), "not starting")
    try:
        m.launch(4)
        check(False, "second launch accepted")
    except StandbyError:
        pass
    rec = m.cancel()
    check(rec is not None and rec.outcome == "cancelled" and not m.thread_alive() and m.state == StandbyState.NO_STANDBY,
          f"cancel: {rec.outcome if rec else None} alive={m.thread_alive()}")
    check(fl.saw_cancel and fl.episodes == [], "the launcher did not observe the cancel")
    check(m.counts["cancelled"] == 1 and m.counts["failed_attempts"] == 0, f"cancel must not count as a failed attempt: {m.counts}")
    out["cancel_starting"] = rec.to_json()
    # 3. attempts exhausted -> failed -> acquire reports it and consumes it
    fl = _FakeLauncher(["fail", "fail", "fail"])
    m = StandbyManager(rank=0, launch_fn=fl, startup_attempts=3, join_timeout=5)
    m.launch(5)
    check(_wait_state(m, ["failed"]) == "failed", "failed never reached")
    a = m.acquire(1.0)
    check(a.kind == "failed" and len(a.record.attempts) == 3 and m.state == StandbyState.NO_STANDBY, f"exhausted: {a.kind}")
    check(all(x["outcome"] == "transport_failure" for x in a.record.attempts) and m.counts["failed_attempts"] == 3, "attempt records")
    out["exhausted"] = [x["outcome"] for x in a.record.attempts]
    # 4. one failed attempt then fresh
    fl = _FakeLauncher(["fail", "ok"])
    m = StandbyManager(rank=0, launch_fn=fl, startup_attempts=3, join_timeout=5)
    m.launch(6)
    check(_wait_state(m, ["ready"]) == "ready", "retry never ready")
    a = m.acquire(1.0)
    check(a.kind == "ready" and len(a.record.attempts) == 2 and a.record.attempts[0]["outcome"] == "transport_failure"
          and a.record.attempts[1]["outcome"] == "fresh", "retry attempts")
    m.promoted()
    # 5. lost: process died after readiness
    fl = _FakeLauncher(["ok"])
    m = StandbyManager(rank=0, launch_fn=fl, startup_attempts=3, join_timeout=5)
    m.launch(7)
    _wait_state(m, ["ready"])
    fl.episodes[0].process.returncode = 3
    a = m.acquire(1.0)
    check(a.kind == "lost" and "exited" in a.record.lost_reason and fl.episodes[0].closed and m.state == StandbyState.NO_STANDBY,
          f"lost: {a.kind} {a.record.lost_reason if a.record else None}")
    out["lost_dead"] = a.record.lost_reason
    # 6. lost: transport failed after readiness
    fl = _FakeLauncher(["ok"])
    m = StandbyManager(rank=0, launch_fn=fl, startup_attempts=3, join_timeout=5)
    m.launch(8)
    _wait_state(m, ["ready"])
    fl.episodes[0].fail_requests = True
    a = m.acquire(1.0)
    check(a.kind == "lost" and "re-verification" in a.record.lost_reason and fl.episodes[0].closed, f"lost transport: {a.kind}")
    # 7. lost: state moved (an action was consumed somehow) -> never promoted with a stale observation
    fl = _FakeLauncher(["ok"])
    m = StandbyManager(rank=0, launch_fn=fl, startup_attempts=3, join_timeout=5)
    m.launch(9)
    _wait_state(m, ["ready"])
    fl.episodes[0].step_count = 1
    fl.episodes[0].input_tick = 1
    a = m.acquire(1.0)
    check(a.kind == "lost" and "status changed" in a.record.lost_reason, f"lost stale: {a.kind} {a.record.lost_reason}")
    # 7b. lost: observation drifted while parked (status unchanged)
    fl = _FakeLauncher(["ok"])
    m = StandbyManager(rank=0, launch_fn=fl, startup_attempts=3, join_timeout=5)
    m.launch(10)
    _wait_state(m, ["ready"])
    fl.episodes[0].input_tick = 1
    a = m.acquire(1.0)
    check(a.kind == "lost" and "changed while parked" in a.record.lost_reason, f"lost drift: {a.kind} {a.record.lost_reason}")
    check(m.counts["lost"] == 1, str(m.counts))
    # 8. wait timeout: a launch still in flight at reset is cancelled after the bound
    fl = _FakeLauncher(["block"])
    m = StandbyManager(rank=0, launch_fn=fl, startup_attempts=3, join_timeout=5)
    m.launch(11)
    t0 = time.perf_counter()
    a = m.acquire(0.2)
    waited = time.perf_counter() - t0
    check(a.kind == "wait_timeout" and 0.19 <= waited < 2.0 and m.state == StandbyState.NO_STANDBY and not m.thread_alive(),
          f"wait timeout: {a.kind} waited {waited:.3f} state {m.state.value}")
    check(m.counts["wait_timeouts"] == 1 and fl.saw_cancel, str(m.counts))
    # 9. unexpected launcher error -> structured failure at the next acquire
    fl = _FakeLauncher(["raise"])
    m = StandbyManager(rank=0, launch_fn=fl, startup_attempts=3, join_timeout=5)
    m.launch(12)
    check(_wait_state(m, ["failed"]) == "failed", "raise -> failed")
    a = m.acquire(1.0)
    check(a.kind == "starting_error" and "fake launcher bug" in (a.record.error or ""), f"starting_error: {a.kind}")
    # 10. close: ready standby closed, idempotent, launch after close refused
    fl = _FakeLauncher(["ok"])
    m = StandbyManager(rank=0, launch_fn=fl, startup_attempts=3, join_timeout=5)
    m.launch(13)
    _wait_state(m, ["ready"])
    c1 = m.close()
    c2 = m.close()
    check(fl.episodes[0].closed and c1["thread_joined"] and c2["state"] == "no_standby", f"close {c1} {c2}")
    try:
        m.launch(14)
        check(False, "launch after close accepted")
    except StandbyError:
        pass
    try:
        m.acquire(0.1)
        check(False, "acquire after close accepted")
    except StandbyError:
        pass
    # 11. abandon_promotion closes the episode the caller could not install
    fl = _FakeLauncher(["ok"])
    m = StandbyManager(rank=0, launch_fn=fl, startup_attempts=3, join_timeout=5)
    m.launch(15)
    _wait_state(m, ["ready"])
    m.acquire(1.0)
    m.abandon_promotion("test")
    check(fl.episodes[0].closed and m.state == StandbyState.NO_STANDBY and m.counts["lost"] == 1, "abandon")
    rep = m.report()
    check(rep["contract"] == "btt_standby_lifecycle_v1" and len(rep["history"]) == 1 and rep["history"][0]["outcome"] == "lost", "report")
    out["report_keys"] = sorted(rep)
    return out


def unit_readiness_contract(suite: Suite) -> Dict[str, Any]:
    from battleship_process import EpisodeFailure
    from m7_standby import observations_equal, verify_readiness

    flags = {"no_render": True, "raphnet_disabled": True}
    proof = verify_readiness(_fake_observe(), flags, flags, 10)
    check(proof.input_tick == 0 and proof.step_count == 0 and proof.flags == flags, "proof")
    rejected = {}
    for label, obs, sf in (
            ("input_tick", _fake_observe(0, 1), flags),
            ("step_count", _fake_observe(1, 0), flags),
            ("flag_value", _fake_observe(), {"no_render": False, "raphnet_disabled": True}),
            ("flag_missing", _fake_observe(), {"no_render": True}),
    ):
        try:
            verify_readiness(obs, sf, flags, 10)
            check(False, f"{label} accepted")
        except EpisodeFailure as exc:
            rejected[label] = exc.message[:120]
    try:
        verify_readiness(_fake_observe(), flags, flags, 9)
        check(False, "targets accepted")
    except EpisodeFailure as exc:
        rejected["targets"] = exc.message[:120]
    from battleship_client import Observe, StepState

    bad = Observe(state=StepState.WAITING_FOR_ACTION, state_name="WaitingForAction", can_step=True, step_count=0,
                  observation=_obs(input_tick=0, time_passed=1, host_frame=64))
    try:
        verify_readiness(bad, flags, flags, 10)
        check(False, "time_passed accepted")
    except EpisodeFailure as exc:
        rejected["time_passed"] = exc.message[:120]
    check(observations_equal(_fake_observe(), _fake_observe()) == [] and observations_equal(_fake_observe(), _fake_observe(0, 1)) == ["input_tick"],
          "observations_equal")
    return {"proof": proof.to_json(), "rejected": rejected}


def unit_config_lifecycle(suite: Suite) -> Dict[str, Any]:
    from m7_trainer import M7Config, config_from_experiment

    v1, v1s = ec.load_experiment(V1_TOML), ec.load_experiment(V1_STANDBY_TOML)
    v2, v2s = ec.load_experiment(V2_TOML), ec.load_experiment(V2_STANDBY_TOML)
    for exp, on in ((v1, False), (v2, False), (v1s, True), (v2s, True)):
        check(exp.standby_preboot is on and exp.standby_count == (1 if on else 0), f"{exp.name}: lifecycle values")
        check(exp.lifecycle()["max_game_processes"] == exp.process_count * (2 if on else 1), f"{exp.name}: max processes")
        check(exp.summary()["lifecycle"]["standby_preboot"] is on and exp.resolved_json()["resolved"]["lifecycle"]["standby_count"] == (1 if on else 0),
              f"{exp.name}: lifecycle not recorded in summary/resolved")
        cfg = config_from_experiment(exp)
        check(cfg.standby_preboot is on and cfg.standby.enabled is on and cfg.lifecycle_json()["max_game_processes"] == exp.max_game_processes,
              f"{exp.name}: M7Config lifecycle")
        cfg.validate()
    for a, b in ((v1, v1s), (v2, v2s)):
        diff = {k for k in a.values if a.values[k] != b.values[k]}
        check(diff == {"run.name", "run.notes", "environment.standby_preboot", "environment.standby_count"},
              f"{a.name} vs {b.name} differ in {diff}")
        check(a.semantic_fingerprint != b.semantic_fingerprint and a.compatibility_fingerprint != b.compatibility_fingerprint,
              "the lifecycle mode must change both fingerprints")
    check(v1s.reward == REWARD_V1 and v2s.reward == REWARD_V2, "standby profiles' reward contracts")
    # rejections
    errors = {}
    for label, changes in (("count_without_preboot", {"environment.standby_count": 1}),
                           ("preboot_without_count", {"environment.standby_preboot": True}),
                           ("count_two", {"environment.standby_preboot": True, "environment.standby_count": 2}),
                           ("lifecycle_override_outside_resume", {"resume.allow_lifecycle_change": True}),
                           ("wait_zero", {"environment.standby_wait_timeout_s": 0.0})):
        values = dict(v1.values)
        values.update(changes)
        try:
            ec.build_experiment({"schema": ec.SCHEMA_ID, **ec._nest(values)}, source=v1.source, toml_text=v1.toml_text)
            check(False, f"{label} accepted")
        except ec.ConfigError as exc:
            errors[label] = str(exc).splitlines()[1][:160]
    try:
        M7Config(run_id="x", n_envs=1, total_timesteps=5120, standby_preboot=True, standby_count=0).validate()
        check(False, "M7Config preboot/count mismatch accepted")
    except ValueError as exc:
        errors["m7config_mismatch"] = str(exc)[:120]
    # legacy path: never a standby
    legacy = ec.from_legacy_arguments("pilot", {"n_envs": 5, "run_id": "m7a_pilot_n5"}, n_envs=5, run_name="m7a_pilot_n5")
    check(legacy.standby_preboot is False and legacy.standby_count == 0, "legacy arguments must resolve to no standby")
    check(legacy.semantic_fingerprint == v1.semantic_fingerprint, "legacy pilot vs v1 profile semantic parity (with lifecycle fields)")
    # dry run text
    text = ec.describe(v1s)
    check("lifecycle   : standby_preboot True  standby_count 1" in text and "expected maximum game processes 10" in text, "dry-run lifecycle line")
    check("expected maximum game processes 5 (training" in ec.describe(v1), "dry-run standby-off line")
    r = subprocess.run([sys.executable, str(REPO_ROOT / "rl" / "train_m7.py"), "--config", str(V2_STANDBY_TOML), "--dry-run"],
                       capture_output=True, text=True, timeout=120, check=False)
    check(r.returncode == 0 and "standby_preboot True" in r.stdout and "btt_reward_v2" in r.stdout, f"dry-run CLI: {r.returncode} {r.stdout[-400:]}")
    return {"v1_standby": v1s.summary(), "v2_standby": v2s.summary(), "rejected": errors,
            "fingerprints": {e.name: {"semantic": e.semantic_fingerprint, "compatibility": e.compatibility_fingerprint}
                             for e in (v1, v2, v1s, v2s)}}


def unit_resume_lifecycle(suite: Suite) -> Dict[str, Any]:
    from m7b_config_tests import _m7a_shaped_meta

    v1, v1s = ec.load_experiment(V1_TOML), ec.load_experiment(V1_STANDBY_TOML)
    view_v1 = ec.compatibility_view_from_values(v1.values, v1.reward, dict(v1.extra_env))
    view_v1s = ec.compatibility_view_from_values(v1s.values, v1s.reward, dict(v1s.extra_env))
    m7a = ec.checkpoint_compatibility_view(_m7a_shaped_meta(legacy_record=True))
    check(m7a["environment.standby_preboot"] is False and m7a["environment.standby_count"] == 0, "M7a-shaped view defaults")
    check(ec.compare_compatibility(m7a, view_v1) == {}, "M7a checkpoint vs v1 profile")
    d = ec.compare_compatibility(m7a, view_v1s)
    check(set(d) == {"environment.standby_preboot", "environment.standby_count"} and ec.lifecycle_only_diffs(d),
          f"M7a checkpoint vs standby profile: {d}")
    # M7b-shaped: stored compatibility view without lifecycle keys -> defaults (no standby existed)
    old_view = {k: v for k, v in view_v1.items() if not k.startswith("environment.standby")}
    m7b = dict(_m7a_shaped_meta(), experiment={"compatibility_view": old_view})
    cv = ec.checkpoint_compatibility_view(m7b)
    check(cv["environment.standby_preboot"] is False and ec.compare_compatibility(cv, view_v1) == {}, "M7b-shaped defaults")
    # M7c-shaped with a lifecycle block (standby on) vs the historical profile
    m7c = dict(_m7a_shaped_meta(), lifecycle={"standby_preboot": True, "standby_count": 1})
    cv = ec.checkpoint_compatibility_view(m7c)
    check(cv["environment.standby_preboot"] is True and list(ec.compare_compatibility(cv, view_v1)) ==
          ["environment.standby_preboot", "environment.standby_count"], "standby checkpoint vs standby-off profile")
    check(not ec.lifecycle_only_diffs({}) and not ec.lifecycle_only_diffs({"ppo.gamma": {}, "environment.standby_count": {}}),
          "lifecycle_only_diffs")
    out: Dict[str, Any] = {"m7a_vs_standby_diffs": d}
    # trainer-level: the real M7a pilot set (when present) under the standby profile
    if PILOT_FINAL.is_dir():
        from m7_evaluation import CheckpointError
        from m7_trainer import M7Run, config_from_experiment

        exe_sha = ec.sha256_file(v1.executable)
        meta = json.loads((PILOT_FINAL / "checkpoint.json").read_text(encoding="utf-8"))
        allow_exe = meta.get("executable", {}).get("sha256") != exe_sha
        base = {"run.mode": "resume", "resume.source_checkpoint": str(PILOT_FINAL), "run.total_transitions": 1_024_000 + 5120,
                "run.output_root": str(suite.root / "unit_resume_lifecycle")}
        if allow_exe:
            base["resume.allow_executable_change"] = True
        err = None
        try:
            M7Run(config_from_experiment(_variant(v1s, base)))._source_checkpoint()
        except CheckpointError as exc:
            err = str(exc)
        check(err is not None and "allow_lifecycle_change" in err and "standby_preboot" in err, f"resume across modes accepted: {err}")
        meta2 = M7Run(config_from_experiment(_variant(v1s, dict(base, **{"resume.allow_lifecycle_change": True}))))._source_checkpoint()
        check(meta2 is not None and meta2.get("_lifecycle_change", {}).get("accepted_by") == "resume.allow_lifecycle_change",
              "override not recorded")
        check(M7Run(config_from_experiment(_variant(v1, base)))._source_checkpoint() is not None, "same-mode resume rejected")
        out["real_pilot"] = {"rejected_message": err[:300], "override_recorded": meta2["_lifecycle_change"],
                             "executable_changed": allow_exe}
        check(not (suite.root / "unit_resume_lifecycle").exists(), "_source_checkpoint created a directory")
    return out


def _variant(exp: ec.Experiment, changes: Dict[str, Any]) -> ec.Experiment:
    values = dict(exp.values)
    values.update(changes)
    return ec.build_experiment({"schema": ec.SCHEMA_ID, **ec._nest(values)}, source=exp.source, toml_text=exp.toml_text)


# -- game: semantic equivalence and repeated promotions -----------------------------------------------------------


def _raw_stack(out: Path, contract: RewardContract, standby: bool, *, rank: int = 0, request_timeout: float = 10.0,
               exit_timeout: float = 10.0):
    """M7 base env + reward + M4 recorder (M3 action domain): the worker stack below Track 1, every episode preserved."""
    from battleship_process import LaunchConfig
    from btt_learning import TARGETS_TOTAL
    from btt_parallel import M7BattleShipBTTEnv, M7RewardWrapper, StandbySettings
    from m7_runtime import PortCandidates, prepare_worker_runtime
    from run_artifacts import EpisodeRecordingWrapper, PositionDeltaDetector, PreservationReason

    out.mkdir(parents=True)
    prepare_worker_runtime(out / "runtime", EXECUTABLE)
    launch = LaunchConfig(executable=EXECUTABLE, working_dir=out / "runtime", run_root=out / "episodes", extra_env=dict(FLAGS),
                          request_timeout=request_timeout, exit_timeout=exit_timeout)
    base = M7BattleShipBTTEnv(launch, max_episode_steps=3600, rank=rank, ports=PortCandidates(rank),
                              standby=StandbySettings(standby, 1 if standby else 0, 120.0),
                              generation_runtime_root=out / "runtime_gens",
                              profile={"reward_contract": contract.contract, "horizon": 3600})
    rewarded = M7RewardWrapper(base, contract)
    rec = EpisodeRecordingWrapper(rewarded, out / "artifacts", detectors=[PositionDeltaDetector(300.0)],
                                  labels=lambda: {"startup_mode": (base.current_startup or {}).get("mode"),
                                                  "lifecycle": base.standby_settings.to_json()},
                                  on_episode_end=lambda r: r.preserve(PreservationReason.MANUAL, "m7c equivalence"),
                                  targets_total=TARGETS_TOTAL)
    return base, rec


def _replay_episode(base: Any, env: Any, rows: Sequence[Any]) -> Dict[str, Any]:
    """One full replay through the stack; every authoritative value recorded for comparison."""
    from battleship_env import OBSERVATION_FIELDS, native_to_action
    from run_artifacts import read_artifact

    t0 = time.perf_counter()
    _obs_, info = env.reset()
    reset_s = time.perf_counter() - t0
    startup = dict(info["m7_startup"])
    initial = base.last_observe
    rec: Dict[str, Any] = {
        "startup": startup, "reset_s": round(reset_s, 4), "reset_info": {k: info.get(k) for k in ("input_tick", "step_count", "state_name")},
        "initial": {"state": int(initial.state), "step_count": initial.step_count, "can_step": initial.can_step,
                    **{n: getattr(initial.observation, n) for n, _ in OBSERVATION_FIELDS}},
        "steps": [], "rewards": [], "pid": info.get("pid"), "port": info.get("port"), "episode_dir": info.get("episode_dir"),
    }
    t1 = time.perf_counter()
    term = trunc = False
    for row in rows:
        _o, r, term, trunc, info = env.step(native_to_action(row.buttons, row.stick_x, row.stick_y))
        res = base.last_step_result
        rec["steps"].append({"buttons": row.buttons, "stick_x": row.stick_x, "stick_y": row.stick_y, "state": int(res.state),
                             "step_count": res.step_count, "consumed_tick": res.consumed_tick,
                             **{n: getattr(res.observation, n) for n, _ in OBSERVATION_FIELDS}})
        rec["rewards"].append(float(r))
        if term or trunc:
            break
    rec["stepping_s"] = round(time.perf_counter() - t1, 4)
    rec["terminated"], rec["truncated"] = bool(term), bool(trunc)
    rec["termination_reason"] = info.get("termination_reason")
    rec["result"] = dict(info.get("result") or {})
    rec["rows_unsent"] = len(rows) - len(rec["steps"])
    rec["return"] = math.fsum(rec["rewards"])
    art_dir = env.last_artifact_dir
    art = read_artifact(art_dir)
    rec["artifact_dir"] = str(art_dir)
    rec["actions_bytes_sha256"] = ec.sha256_file(art_dir / "actions.jsonl")
    meta = art.metadata
    rec["artifact_authoritative"] = {k: meta[k] for k in ("artifact_schema", "format", "action_contract", "source_action_contract",
                                                          "action_count", "actions_with_result", "status", "terminal",
                                                          "anomaly_events", "detectors", "initial_observation", "final_observation")}
    rec["artifact_labels"] = meta["labels"]
    rec["anomaly_events"] = len(meta["anomaly_events"])
    return rec


def _compare_episodes(ref: Dict[str, Any], cand: Dict[str, Any], label: str) -> None:
    check(ref["initial"] == cand["initial"], f"{label}: initial tick-0 observation differs: "
                                             f"{ {k: (ref['initial'][k], cand['initial'][k]) for k in ref['initial'] if ref['initial'][k] != cand['initial'][k]} }")
    check(len(ref["steps"]) == len(cand["steps"]), f"{label}: {len(cand['steps'])} steps vs {len(ref['steps'])}")
    for i, (a, b) in enumerate(zip(ref["steps"], cand["steps"])):
        if a != b:
            diffs = {k: (a[k], b[k]) for k in a if a[k] != b[k]}
            check(False, f"{label}: step {i} differs: {diffs}")
    check(ref["rewards"] == cand["rewards"], f"{label}: rewards differ")
    check(ref["result"] == cand["result"], f"{label}: terminal result JSON differs: {ref['result']} vs {cand['result']}")
    check(ref["actions_bytes_sha256"] == cand["actions_bytes_sha256"], f"{label}: canonical actions.jsonl differs")
    check(ref["artifact_authoritative"] == cand["artifact_authoritative"], f"{label}: artifact metadata differs")
    check((ref["terminated"], ref["truncated"], ref["termination_reason"], ref["rows_unsent"], ref["anomaly_events"]) ==
          (cand["terminated"], cand["truncated"], cand["termination_reason"], cand["rows_unsent"], cand["anomaly_events"]),
          f"{label}: terminal facts differ")


def _check_clear_contract(rec: Dict[str, Any], label: str) -> None:
    last = rec["steps"][-1]
    check(len(rec["steps"]) == COMPLETION_STEPS and last["consumed_tick"] == 446 and last["input_tick"] == 447
          and last["time_passed"] == 446 and last["step_count"] == 447 and last["targets_remaining"] == 0
          and rec["rows_unsent"] == 21 and rec["termination_reason"] == "native_clear" and rec["anomaly_events"] == 0
          and rec["result"].get("completion_time_passed") == 446 and rec["result"].get("completion_input_tick") == 447
          and rec["result"].get("targets_broken") == 10, f"{label}: frozen completion contract violated: {last} {rec['result']}")
    first = rec["steps"][0]
    check(first["consumed_tick"] == 0 and first["input_tick"] == 1 and first["step_count"] == 1, f"{label}: first step {first}")
    check(rec["initial"]["input_tick"] == 0 and rec["initial"]["step_count"] == 0 and rec["reset_info"]["input_tick"] == 0, f"{label}: tick 0")


def cold_vs_standby_replay(suite: Suite) -> Dict[str, Any]:
    from btti_replay import read_btti_rows

    d = suite.dir("cold_vs_standby_replay")
    rows = read_btti_rows(str(REPLAY))
    out: Dict[str, Any] = {}
    # Reference: standby off, two cold episodes (must match each other).
    base, env = _raw_stack(d / "cold_v1", REWARD_V1, False)
    try:
        ref = [_replay_episode(base, env, rows) for _ in range(2)]
    finally:
        env.close()
    for r in ref:
        _check_clear_contract(r, "cold")
        check(abs(r["return"] - TAS_RETURN) < 1e-9 and r["startup"]["mode"] == "cold_start", "cold reference")
    _compare_episodes(ref[0], ref[1], "cold vs cold")
    check(battleship_pids() == [], "reference leg leaked")
    # Candidate: standby on, 1 cold + 10 promoted episodes, each compared to the cold reference.
    base, env = _raw_stack(d / "standby_v1", REWARD_V1, True)
    try:
        cand = [_replay_episode(base, env, rows) for _ in range(11)]
        snapshot = base.standby_snapshot()
        check(snapshot["state"] in ("starting", "ready") and snapshot["live_processes"] >= 1, f"before close: {snapshot}")  # the clear already retired the active
    finally:
        env.close()
    report = base.standby_report()   # after close: the in-flight generation 12 cancelled, thread joined
    modes = [c["startup"]["mode"] for c in cand]
    check(modes == ["cold_start"] + ["standby_promoted"] * 10, f"modes {modes}")
    for i, c in enumerate(cand):
        _check_clear_contract(c, f"standby episode {i + 1}")
        _compare_episodes(ref[0], c, f"cold vs standby episode {i + 1}")
        check(abs(c["return"] - TAS_RETURN) < 1e-9, f"episode {i + 1} return {c['return']}")
        check(c["artifact_labels"]["startup_mode"] == modes[i] and c["artifact_labels"]["lifecycle"]["standby_preboot"] is True,
              "artifact labels carry the lifecycle")
        if i:
            st = c["startup"]
            check(st["generation"] == i + 1 and st["attempts"] == 1 and st["failed_attempts"] == 0 and st["promotion_s"] < 0.5
                  and st["standby_startup_s"] is not None and st["readiness_proof"]["input_tick"] == 0
                  and st["readiness_proof"]["flags"] == {"no_render": True, "raphnet_disabled": True}, f"promotion record {st}")
    pids = [c["pid"] for c in cand]
    ports = [c["port"] for c in cand]
    check(len(set(pids)) == 11 and len(set(ports)) == 11 and len({c["episode_dir"] for c in cand}) == 11, "identity reuse across generations")
    m = report["manager"]
    check(m["counts"]["promoted"] == 10 and m["counts"]["ready"] == 10 and m["counts"]["failed"] == 0 and m["counts"]["lost"] == 0
          and m["counts"]["failed_attempts"] == 0 and m["counts"]["cancelled"] == 1 and m["counts"]["launches"] == 11, str(m["counts"]))
    check(report["max_concurrent_processes"] == 2 and not m["thread_alive"] and m["threads_started"] == m["threads_joined"] == 11, str(report))
    art_dirs = sorted(p.name for p in (d / "standby_v1" / "artifacts").iterdir())
    check(len(art_dirs) == 11, f"standby boots must not create artifacts: {len(art_dirs)} artifact directories for 11 episodes")
    gens = sorted(p.name for p in (d / "standby_v1" / "runtime_gens").iterdir())
    check(len(gens) == 11 and "g0012_a1" not in gens, f"cancelled generation's runtime directory not removed: {gens}")
    check(battleship_pids() == [], "candidate leg leaked")
    out["v1"] = {"reference": [{k: r[k] for k in ("startup", "reset_s", "stepping_s", "return", "rows_unsent", "pid", "port")} for r in ref],
                 "candidates": [{k: c[k] for k in ("startup", "reset_s", "stepping_s", "return", "rows_unsent", "pid", "port")} for c in cand],
                 "actions_sha256": ref[0]["actions_bytes_sha256"], "standby_counts": m["counts"],
                 "standby_startup_s": m["startup_s"], "exposed_wait_s": m["exposed_wait_s"], "promotions": m["counts"]["promoted"],
                 "artifact_dirs": len(art_dirs)}
    # v2: same trajectory and return (19.553) under the standby lifecycle; digests equal the v1 reference.
    base, env = _raw_stack(d / "standby_v2", REWARD_V2, True)
    try:
        c2 = [_replay_episode(base, env, rows) for _ in range(3)]
    finally:
        env.close()
    for i, c in enumerate(c2):
        _check_clear_contract(c, f"v2 episode {i + 1}")
        check(abs(c["return"] - TAS_RETURN) < 1e-9, f"v2 episode {i + 1} return {c['return']}")
        check(c["actions_bytes_sha256"] == ref[0]["actions_bytes_sha256"] and c["steps"] == ref[0]["steps"]
              and c["initial"] == ref[0]["initial"], f"v2 episode {i + 1} trajectory differs from the cold v1 reference")
    check([c["startup"]["mode"] for c in c2] == ["cold_start", "standby_promoted", "standby_promoted"], "v2 modes")
    out["v2"] = {"returns": [c["return"] for c in c2], "modes": [c["startup"]["mode"] for c in c2]}
    return out


def terminal_paths_promotion(suite: Suite) -> Dict[str, Any]:
    """Fall (native_failure) -> promotion -> horizon truncation -> promotion -> fall, under v1 and v2."""
    from run_artifacts import read_artifact

    d = suite.dir("terminal_paths_promotion")
    out: Dict[str, Any] = {}
    for contract, fall_return in ((REWARD_V1, FALL_RETURN_V1), (REWARD_V2, FALL_RETURN_V2)):
        run = VecRun(d / contract.contract, [standby_spec(horizon=600, reward_contract=contract)], f"terminal_{contract.contract}")
        try:
            run.reset()
            run.run_episodes([fall_script, neutral, fall_script])
            snap = run.snapshot()
        finally:
            close = run.close()
        eps = run.episodes[0]
        modes = run.modes()
        check(modes[:4] == ["cold_start", "standby_promoted", "standby_promoted", "standby_promoted"], f"{contract.contract}: modes {modes}")
        check([e["end_reason"] for e in eps[:3]] == ["fall", "horizon", "fall"], f"{contract.contract}: {[e['end_reason'] for e in eps]}")
        for e, want in zip(eps[:3], (fall_return, -0.6, fall_return)):
            check(abs(e["return"] - want) < 1e-9, f"{contract.contract}: {e['end_reason']} return {e['return']} != {want}")
            check(e["startup_mode"] == e["startup"]["mode"] and e["reward_contract"] == contract.contract, "summary lifecycle")
        check(eps[0]["last_consumed_tick"] == FALL_TICK and eps[0]["steps"] == FALL_TICK + 1 and eps[2]["last_consumed_tick"] == FALL_TICK,
              f"{contract.contract}: fall ticks {[e['last_consumed_tick'] for e in eps]}")
        check(eps[1]["steps"] == 600 and eps[1]["last_consumed_tick"] == 599, f"{contract.contract}: horizon {eps[1]['steps']}")
        check((eps[0]["failure_penalty_applied"], eps[0]["failure_penalty_terms"]) == (contract is REWARD_V2, 1 if contract is REWARD_V2 else 0)
              and eps[1]["failure_penalty_applied"] is False, f"{contract.contract}: penalty flags")
        for e in eps[:3]:
            art_dir = Path(e["artifact_dir"]) if Path(e["artifact_dir"]).is_absolute() else REPO_ROOT / e["artifact_dir"]
            art = artifact_rows_are_canonical(art_dir)
            check(art["rows"] == e["steps"], f"{contract.contract}: artifact rows {art['rows']} != steps {e['steps']}")
            labels = read_artifact(art_dir).metadata["labels"]
            check(labels["startup_mode"] == e["startup_mode"] and labels["lifecycle"]["standby_preboot"] is True
                  and labels["startup"]["mode"] == e["startup_mode"], "artifact lifecycle labels")
        cleanup = check_cleanup(run.reports, contract.contract)
        rep = run.reports[0]["standby"]["manager"]
        check(rep["counts"]["promoted"] >= 3 and rep["counts"]["lost"] == 0 and rep["counts"]["failed"] == 0, str(rep["counts"]))
        check(close["forced_terminations"] == [] and not close["orphan_games_killed"], str(close))
        out[contract.contract] = {"modes": modes, "episodes": [{k: e[k] for k in ("end_reason", "steps", "return", "startup_mode",
                                                                                  "failure_penalty_terms", "last_consumed_tick")} for e in eps[:3]],
                                  "promotions": [{k: r["m7_startup"].get(k) for k in ("generation", "standby_wait_s", "promotion_s",
                                                                                     "standby_startup_s", "ready_before_promotion_s")}
                                                 for r in run.resets[0][1:4]],
                                  "cleanup": cleanup, "snapshot_before_close": snap}
    return out


# -- game: shutdown, interruption, faults -------------------------------------------------------------------------


def shutdown_active_and_ready(suite: Suite) -> Dict[str, Any]:
    from m7_runtime import pid_alive

    d = suite.dir("shutdown_active_and_ready")
    run = VecRun(d, [standby_spec()], "shutdown_ready")
    try:
        run.reset()
        for _ in range(20):
            run.step([NEUTRAL_T1])
        snap = run.settle()
        check(snap["state"] == "ready" and snap["live_processes"] == 2 and snap["pid"] and snap["active_pid"], f"snapshot {snap}")
        check(sorted(battleship_pids()) == sorted([snap["pid"], snap["active_pid"]]), "expected exactly the active and the standby")
    finally:
        close = run.close()
    check(not pid_alive(snap["pid"]) and not pid_alive(snap["active_pid"]), "a process survived close()")
    rep = run.reports[0]["standby"]
    check(rep["last_close"]["thread_joined"] and rep["manager"]["history"][-1]["outcome"] == "closed", str(rep["last_close"]))
    check(close["forced_terminations"] == [] and not close["orphan_games_killed"] and run.reports[0]["closed_cleanly"], str(close))
    gens = sorted(p.name for p in (d / "workers" / "w00" / "runtime_gens").iterdir())
    cleanup = check_cleanup(run.reports, "shutdown_active_and_ready")
    return {"snapshot": snap, "close": close, "runtime_gens_left": gens, "cleanup": cleanup,
            "standby_history": rep["manager"]["history"]}


def shutdown_while_starting(suite: Suite) -> Dict[str, Any]:
    from m7_runtime import pid_alive

    d = suite.dir("shutdown_while_starting")
    run = VecRun(d, [standby_spec()], "shutdown_starting")
    try:
        run.reset()
        snap = run.snapshot()
        check(snap["state"] == "starting" and snap["thread_alive"], f"standby should still be booting: {snap}")
        t0 = time.perf_counter()
    finally:
        close = run.close()
    close_s = time.perf_counter() - t0
    check(snap["pid"] is None or not pid_alive(snap["pid"]), "in-flight standby survived close()")
    rep = run.reports[0]["standby"]["manager"]
    check(rep["counts"]["cancelled"] == 1 and rep["counts"]["failed_attempts"] == 0 and rep["counts"]["failed"] == 0
          and rep["history"][-1]["outcome"] == "cancelled" and not rep["thread_alive"], f"cancel accounting: {rep['counts']}")
    check(close_s < 30, f"close took {close_s:.1f} s")
    gens = sorted(p.name for p in (d / "workers" / "w00" / "runtime_gens").iterdir())
    check("g0002_a1" not in gens, f"cancelled generation directory kept: {gens}")
    cleanup = check_cleanup(run.reports, "shutdown_while_starting")
    return {"snapshot": snap, "close_s": round(close_s, 2), "counts": rep["counts"], "cleanup": cleanup}


def wait_timeout_fallback(suite: Suite) -> Dict[str, Any]:
    """The first episode ends before the standby is ready and the bound is tiny: cancel + cold fallback."""
    d = suite.dir("wait_timeout_fallback")
    run = VecRun(d, [standby_spec(horizon=40, standby_wait_timeout=0.05)], "wait_timeout")
    try:
        run.reset()
        run.run_episodes([neutral, neutral, neutral])
        snap = run.settle()
    finally:
        close = run.close()
    modes = run.modes()
    check(modes[0] == "cold_start" and modes[1] == "cold_fallback", f"modes {modes}")
    fb = run.resets[0][1]["m7_startup"]["fallback"]
    check(fb["reason"] == "wait_timeout" and fb["generation"] == 2, f"fallback record {fb}")
    rep = run.reports[0]["standby"]["manager"]
    check(rep["counts"]["wait_timeouts"] >= 1 and rep["counts"]["cancelled"] >= 1, str(rep["counts"]))
    check(all(e["end_reason"] == "horizon" and e["steps"] == 40 for e in run.episodes[0][:3]), "episodes")
    ev = run.reports[0]["standby"]["events"]
    check(any(e["event"] == "wait_timeout" for e in ev), f"events {ev}")
    cleanup = check_cleanup(run.reports, "wait_timeout_fallback")
    return {"modes": modes, "fallback": fb, "counts": rep["counts"], "events": ev, "cleanup": cleanup, "close": close}


def _interrupt_run(suite: Suite, name: str, at_step: int) -> Dict[str, Any]:
    from m7_evaluation import read_checkpoint_set
    from m7_trainer import run_training

    s = run_training(short_config(suite, name, 1, horizon=3600, interrupt_at_vec_step=at_step, **STANDBY_KW))
    check(s["status"] == "interrupted", s["status"])
    check(s["cleanup"]["leak_free"] and s["cleanup"]["close"]["forced_terminations"] == [] and not s["cleanup"]["close"]["orphan_games_killed"],
          str(s["cleanup"]))
    check(s["lifecycle"]["settings"]["standby_preboot"] is True and s["lifecycle"]["standby"]["threads"]["alive_at_close"] == 0
          and s["lifecycle"]["standby"]["threads"]["started"] == s["lifecycle"]["standby"]["threads"]["joined"], str(s["lifecycle"]["standby"]["threads"]))
    meta = read_checkpoint_set(suite.root / name / "interrupted")
    check(meta["lifecycle"]["standby_preboot"] is True, "interrupted set lacks the lifecycle")
    reports = {rank: {"standby": sb, "startup_attempts": []} for rank, sb in s["lifecycle"]["per_worker"].items() if sb}
    cleanup = check_cleanup(reports, name)
    return {"status": s["status"], "vec_steps": s["vector"]["timing"]["vec_steps"], "standby": s["lifecycle"]["standby"]["counts"],
            "history": [h["outcome"] for h in s["lifecycle"]["per_worker"][0]["manager"]["history"]], "cleanup": cleanup,
            "user_config": s["user_config"]["byte_identical"]}


def interrupt_active_play(suite: Suite) -> Dict[str, Any]:
    r = _interrupt_run(suite, "interrupt_active", 2500)
    check(r["history"] == ["closed"], f"expected the ready standby closed at the interrupt: {r['history']}")
    return r


def interrupt_during_standby_launch(suite: Suite) -> Dict[str, Any]:
    r = _interrupt_run(suite, "interrupt_launch", 3)
    check(r["history"] == ["cancelled"], f"expected the booting standby cancelled at the interrupt: {r['history']}")
    return r


def worker_exception_both_slots(suite: Suite) -> Dict[str, Any]:
    from m7_trainer import run_training
    from m7_vec_env import M7WorkerFailure

    err = None
    try:
        run_training(short_config(suite, "worker_exception_standby", 2, horizon=3600, fault={"raise_in_step": (2, 50)}, fault_rank=1,
                                  **STANDBY_KW))
    except M7WorkerFailure as exc:
        err = exc
    check(err is not None and err.rank == 1 and "M7InjectedFault" in err.failure.exc_type, f"got {err!r}")
    ctx = err.failure.context
    check(ctx.get("env_closed") is True and ctx.get("standby", {}).get("enabled") is True, f"context {ctx}")
    s = json.loads((suite.root / "worker_exception_standby" / "training_summary.json").read_text())
    check(s["status"] == "failed" and s["cleanup"]["leak_free"], f"{s['status']} {s['cleanup']}")
    check(battleship_pids() == [], "BattleShip left running")
    return {"failure": err.failure.describe()[:300], "standby_context": ctx.get("standby"), "cleanup": s["cleanup"],
            "orphans_killed": s["cleanup"]["close"].get("orphan_games_killed")}


def active_timeout_then_promotion(suite: Suite) -> Dict[str, Any]:
    """Detection off: the fall hangs the step -> episode_timeout lifecycle failure -> auto-reset promotes the standby."""
    d = suite.dir("active_timeout_then_promotion")
    run = VecRun(d, [standby_spec(horizon=700, detect_native_failure=False, request_timeout=3.0, exit_timeout=3.0)], "active_timeout")
    try:
        run.reset()
        run.run_episodes([fall_script, neutral], max_steps=2500)
        # the second episode is running on the promoted process: a few more steps must work
        for _ in range(50):
            run.step([NEUTRAL_T1])
        snap = run.snapshot()
    finally:
        close = run.close()
    ep = run.episodes[0][0]
    check(ep["end_reason"] == "lifecycle_failure" and ep["failure_outcome"] == "episode_timeout", f"{ep['end_reason']} {ep['failure_outcome']}")
    modes = run.modes()
    check(modes[:2] == ["cold_start", "standby_promoted"], f"modes {modes}")
    check(run.episodes[0][1]["end_reason"] == "horizon" or snap["active_pid"], "the promoted process did not serve steps")
    cleanup = check_cleanup(run.reports, "active_timeout_then_promotion")
    return {"first_episode": {k: ep[k] for k in ("end_reason", "failure_outcome", "steps")}, "modes": modes,
            "promotion": run.resets[0][1]["m7_startup"], "cleanup": cleanup, "close": close}


def _standby_fault_case(suite: Suite, name: str, fault: Dict[str, Any], **spec_kw: Any) -> Tuple[VecRun, Dict[str, Any], List[Dict[str, Any]]]:
    d = suite.dir(name)
    run = VecRun(d, [standby_spec(horizon=300, request_timeout=3.0, standby_fault=fault, **spec_kw)], name)
    try:
        run.reset()
        run.run_episodes([neutral, neutral, neutral])
    finally:
        close = run.close()
    history = run.reports[0]["standby"]["manager"]["history"]
    return run, close, history


def standby_startup_timeout_retry(suite: Suite) -> Dict[str, Any]:
    from m7_runtime import pid_alive

    run, close, history = _standby_fault_case(suite, "standby_startup_timeout_retry",
                                              {"generations": [2], "startup_timeout_attempts": [1]})
    gen2 = next(h for h in history if h["generation"] == 2)
    att = gen2["attempts"]
    check(gen2["outcome"] == "promoted" and len(att) == 2 and att[0]["outcome"] == "startup_timeout" and att[1]["outcome"] == "fresh",
          f"gen 2 attempts {att}")
    check(att[0]["port"] != att[1]["port"] and att[0]["pid"] != att[1]["pid"] and not pid_alive(att[0]["pid"]), "retry identity")
    st = run.resets[0][1]["m7_startup"]
    check(st["mode"] == "standby_promoted" and st["attempts"] == 2 and st["failed_attempts"] == 1 and len(st["failures"]) == 1, str(st))
    cleanup = check_cleanup(run.reports, "standby_startup_timeout_retry")
    return {"gen2": gen2, "promotion": st, "cleanup": cleanup, "close": close}


def standby_bind_failure_retry(suite: Suite) -> Dict[str, Any]:
    from m7_runtime import pid_alive

    run, close, history = _standby_fault_case(suite, "standby_bind_failure_retry", {"generations": [2], "squat_attempts": [1]})
    gen2 = next(h for h in history if h["generation"] == 2)
    att = gen2["attempts"]
    check(gen2["outcome"] == "promoted" and len(att) == 2 and att[0]["outcome"] in ("transport_failure", "startup_timeout", "startup_failure")
          and att[1]["outcome"] == "fresh", f"gen 2 attempts {att}")
    check(att[0]["port"] != att[1]["port"] and not pid_alive(att[0]["pid"]), "the failed attempt's process must be dead and its port not reused")
    check(run.modes()[1] == "standby_promoted", str(run.modes()))
    cleanup = check_cleanup(run.reports, "standby_bind_failure_retry")
    return {"gen2": gen2, "cleanup": cleanup, "close": close}


def standby_exhausted_cold_fallback(suite: Suite) -> Dict[str, Any]:
    run, close, history = _standby_fault_case(suite, "standby_exhausted_cold_fallback", {"generations": [2], "squat_attempts": "all"})
    gen2 = next(h for h in history if h["generation"] == 2)
    check(gen2["outcome"] == "failed" and len(gen2["attempts"]) == 3 and all(a["outcome"] != "fresh" for a in gen2["attempts"]),
          f"gen 2 {gen2['outcome']} {[a['outcome'] for a in gen2['attempts']]}")
    eps = run.episodes[0]
    check(eps[0]["end_reason"] == "horizon" and eps[0]["steps"] == 300, "the active episode must run unaffected by the standby failure")
    modes = run.modes()
    check(modes[:3] == ["cold_start", "cold_fallback", "standby_promoted"], f"modes {modes}")
    fb = run.resets[0][1]["m7_startup"]["fallback"]
    check(fb["reason"] == "failed" and len(fb["standby_attempts"]) == 3, f"fallback {fb}")
    ev = run.reports[0]["standby"]["events"]
    check(any(e["event"] == "failed" for e in ev), str(ev))
    kept = [l for l in (suite.root / "standby_exhausted_cold_fallback" / "workers" / "w00" / "dispositions.jsonl").read_text().splitlines()
            if '"standby_dir"' in l and '"outcome":"failed"' in l]
    check(len(kept) == 3 and all(json.loads(l)["decision"] == "kept_failure_debug" for l in kept), f"standby dir dispositions {kept}")
    cleanup = check_cleanup(run.reports, "standby_exhausted_cold_fallback")
    return {"gen2_attempts": [a["outcome"] for a in gen2["attempts"]], "modes": modes, "fallback": fb, "cleanup": cleanup,
            "counts": run.reports[0]["standby"]["manager"]["counts"], "close": close}


def standby_lost_after_ready(suite: Suite) -> Dict[str, Any]:
    from m7_runtime import kill_pid, pid_alive

    d = suite.dir("standby_lost_after_ready")
    run = VecRun(d, [standby_spec(horizon=200)], "standby_lost")
    try:
        run.reset()
        snap = run.settle()
        check(snap["state"] == "ready" and snap["pid"], f"snapshot {snap}")
        check(kill_pid(snap["pid"], expected_image="BattleShip.exe"), "could not kill the ready standby")
        deadline = time.monotonic() + 10
        while pid_alive(snap["pid"]) and time.monotonic() < deadline:
            time.sleep(0.05)
        run.run_episodes([neutral, neutral, neutral])
    finally:
        close = run.close()
    modes = run.modes()
    check(modes[:3] == ["cold_start", "cold_fallback", "standby_promoted"], f"modes {modes}")
    fb = run.resets[0][1]["m7_startup"]["fallback"]
    check(fb["reason"] == "lost" and "exited" in (fb["lost_reason"] or ""), f"fallback {fb}")
    hist = run.reports[0]["standby"]["manager"]["history"]
    lost = [h for h in hist if h["outcome"] == "lost"]
    check(len(lost) == 1 and lost[0]["generation"] == 2 and lost[0]["pid"] == snap["pid"], str(lost))
    cleanup = check_cleanup(run.reports, "standby_lost_after_ready")
    return {"killed_pid": snap["pid"], "modes": modes, "fallback": fb, "counts": run.reports[0]["standby"]["manager"]["counts"],
            "cleanup": cleanup, "close": close}


def _job_victim_standby(root: str) -> None:
    """Separate trainer-like process: job + 2 workers, each with an active and a ready standby, then waits to be killed."""
    from btt_parallel import RunCoordinator, WorkerFactory, WorkerSpec, initial_coordination_state
    from m7_runtime import install_kill_on_close_job, prepare_worker_runtime
    from m7_vec_env import M7SubprocVecEnv

    base = Path(root)
    job = install_kill_on_close_job()
    RunCoordinator.create(base / "coordination", initial_coordination_state("victim", "test", None))
    factories = []
    for r in range(2):
        wd = base / "workers" / f"w{r:02d}"
        prepare_worker_runtime(wd / "runtime", EXECUTABLE)
        factories.append(WorkerFactory(WorkerSpec(rank=r, run_id="victim", role="test", worker_dir=str(wd.resolve()),
                                                  coordination_dir=str((base / "coordination").resolve()),
                                                  executable=str(EXECUTABLE), horizon=3600, **STANDBY_KW)))
    venv = M7SubprocVecEnv(factories)
    venv.reset()
    snaps = venv.env_method("wait_standby_settled", 120.0)
    info = {"job": job.describe(), "parent": os.getpid(), "workers": [p.pid for p in venv.processes],
            "games": list(venv.game_pids), "standbys": [s["pid"] for s in snaps], "states": [s["state"] for s in snaps]}
    (base / "victim_pids.json").write_text(json.dumps(info))
    time.sleep(600)


def job_object_kill_standby(suite: Suite) -> Dict[str, Any]:
    from m7_runtime import kill_pid, pid_alive

    d = suite.dir("job_object_kill_standby")
    proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "_job_victim_standby", str(d)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pid_file = d / "victim_pids.json"
    deadline = time.monotonic() + 240
    while not pid_file.exists():
        check(proc.poll() is None, f"victim exited early ({proc.returncode})")
        check(time.monotonic() < deadline, "victim never reported its processes")
        time.sleep(0.5)
    info = json.loads(pid_file.read_text())
    check(info["states"] == ["ready", "ready"] and all(info["standbys"]), f"standbys not ready: {info}")
    everything = info["workers"] + info["games"] + info["standbys"]
    alive_before = {p: pid_alive(p) for p in everything}
    check(all(alive_before.values()) and len(set(everything)) == 6, f"not all 6 processes alive before the kill: {alive_before}")
    kill_pid(proc.pid)  # TerminateProcess: no Python cleanup runs in the victim
    proc.wait(30)
    deadline = time.monotonic() + 15
    while any(pid_alive(p) for p in everything) and time.monotonic() < deadline:
        time.sleep(0.25)
    alive_after = {p: pid_alive(p) for p in everything}
    check(not any(alive_after.values()), f"processes survived the hard kill of their trainer: {alive_after}")
    return {"victim": info, "alive_after": alive_after}


# -- game: startup contention, bounded v2 smoke, resume across modes ----------------------------------------------


def startup_contention(suite: Suite) -> Dict[str, Any]:
    """Initial boot of N active + N standby processes for N=4 and N=5 (one rollout each) against standby off."""
    from m7_trainer import run_training

    out: Dict[str, Any] = {}
    for n in (4, 5):
        for label, kw in (("off", {}), ("on", STANDBY_KW)):
            name = f"contention_n{n}_{label}"
            s = run_training(short_config(suite, name, n, horizon=3600, total_timesteps=5120, checkpoint_interval=5120, **kw))
            check(s["status"] == "completed" and s["cleanup"]["leak_free"] and s["restarts"]["startup_retries"] == 0
                  and s["lifecycle"]["standby"]["standby_failed_attempts"] == 0, f"{name}: {s['status']} {s['cleanup']} {s['restarts']}")
            per = s["lifecycle"]["per_worker"]
            first_standby = {}
            for rank in range(n):
                p = (per.get(rank) or per.get(str(rank)) or {})
                hist = (p.get("manager") or {}).get("history", [])
                first_standby[rank] = hist[0].get("startup_s") if hist else None
            out[name] = {"initial_reset_s": s["wall"]["initial_reset_s"], "e2e_tps": s["throughput"]["end_to_end_transitions_per_s"],
                         "first_standby_startup_s": first_standby, "observed_max_concurrent_per_worker": s["lifecycle"]["observed_max_concurrent_per_worker"],
                         "expected_max_game_processes": s["lifecycle"]["expected_max_game_processes"],
                         "standby": {k: s["lifecycle"]["standby"][k] for k in ("promotions", "hits_ready_at_reset", "late_hits_waited",
                                                                             "cold_fallbacks", "standby_startup_s", "exposed_wait_s")},
                         "cpu_util_collect": s["cpu"]["system_util_collect_mean"], "native_step": s["latency"]["native_step"],
                         "episodes": s["episodes"]["finished"], "reset_modes": s["lifecycle"]["reset_modes"]}
            check(s["lifecycle"]["observed_max_concurrent_per_worker"] <= (2 if kw else 1), "more processes than the lifecycle allows")
    return out


def _episode_rows(run: Path) -> List[Dict[str, Any]]:
    p = run / "metrics" / "episodes.jsonl"
    return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []


def v2_standby_smoke(suite: Suite) -> Dict[str, Any]:
    """Bounded PPO through the v2 standby profile: penalties once per fall, lifecycle recorded everywhere, no leaks."""
    from m7_trainer import M7PPO, config_from_experiment, run_training

    n = int(suite.shared.get("selected_n", 2))
    exp = derive(suite, V2_STANDBY_TOML, "v2_standby_smoke", **{"environment.process_count": n, "ppo.n_steps": 5120 // n,
                                                                "run.total_transitions": 15360, "checkpoint.interval": 5120,
                                                                "evaluation.interval": 0, "evaluation.initial": False,
                                                                "evaluation.final": True, "evaluation.deterministic_episodes": 1,
                                                                "evaluation.stochastic_episodes": 2, "artifacts.periodic_episodes": 2,
                                                                "run.mode": "train"})
    check(exp.reward == REWARD_V2 and exp.standby_preboot, "derived profile")
    s = run_training(config_from_experiment(exp))
    check(s["status"] == "completed" and s["cleanup"]["leak_free"] and s["user_config"]["byte_identical"], f"{s['status']} {s['cleanup']}")
    check(s["timesteps"]["sb3_num_timesteps"] == 15360 and s["timesteps"]["n_updates"] == 30, str(s["timesteps"]))
    run = suite.root / "v2_standby_smoke"
    rows = _episode_rows(run)
    finished = [e for e in rows if e["end_reason"] != "aborted"]
    check(finished, "no finished episode")
    falls, mism = [], []
    for e in finished:
        want = expected_return(e["targets_broken"], e["steps"], cleared=e["cleared"], native_failure=e["end_reason"] == "fall", contract=REWARD_V2)
        if abs(e["return"] - want) > 1e-9:
            mism.append((e["rank"], e["worker_episode"], e["return"], want))
        check(e["reward_contract"] == "btt_reward_v2" and e["failure_penalty_applied"] == (e["end_reason"] == "fall")
              and e["failure_penalty_terms"] == (1 if e["end_reason"] == "fall" else 0), f"penalty flags {e}")
        check(e["startup_mode"] in ("cold_start", "standby_promoted", "cold_fallback"), f"startup mode {e['startup_mode']}")
        if e["end_reason"] == "fall":
            falls.append({"rank": e["rank"], "worker_episode": e["worker_episode"], "steps": e["steps"], "return": round(e["return"], 6),
                          "startup_mode": e["startup_mode"]})
    check(not mism, f"returns disagree with the v2 closed form: {mism}")
    lc = s["lifecycle"]
    check(lc["settings"]["standby_preboot"] is True and lc["standby"]["promotions"] >= 1 and lc["standby"]["standby_lost"] == 0
          and lc["standby"]["threads"]["alive_at_close"] == 0 and lc["observed_max_concurrent_per_worker"] == 2, str(lc["standby"]))
    run_json = json.loads((run / "run.json").read_text(encoding="utf-8"))
    check(run_json["lifecycle"]["standby_preboot"] is True and run_json["experiment"]["lifecycle"]["standby_count"] == 1, "run.json lifecycle")
    for ck in sorted((run / "checkpoints").iterdir()) + [run / "final"]:
        meta = json.loads((ck / "checkpoint.json").read_text(encoding="utf-8"))
        check(meta["lifecycle"]["standby_preboot"] is True and meta["experiment"]["compatibility_view"]["environment.standby_count"] == 1,
              f"{ck.name}: lifecycle missing")
    model = M7PPO.load(str(run / "final" / "model.zip"), device="cpu")
    check(model.m7_reward_contract == REWARD_V2.to_json() and model.m7_experiment["lifecycle"]["standby_preboot"] is True, "model.zip provenance")
    evals = list((run / "evaluations").iterdir())
    check(len(evals) == 1, f"expected one final evaluation, got {evals}")
    ev = json.loads((evals[0] / "evaluation_summary.json").read_text(encoding="utf-8"))
    check(ev["reward_contract"] == REWARD_V2.to_json() and ev["lifecycle"]["standby_preboot"] is True
          and ev["checkpoint_lifecycle"]["standby_preboot"] is True, "evaluation lifecycle")
    for mode in ("deterministic", "stochastic"):
        m = ev["modes"][mode]
        check(m["frozen_check"]["policy_parameters_unchanged"] and m["frozen_check"]["obs_rms_unchanged"]
              and m["lifecycle"]["standby_preboot"] is True and m["workers_closed_cleanly"], f"{mode}: evaluation")
        for row in m["episodes"]:
            want = expected_return(row["targets_broken"], row["length"], cleared=row["cleared"], native_failure=row["end_reason"] == "fall",
                                   contract=REWARD_V2)
            check(abs(row["raw_return"] - want) < 1e-9, f"{mode}: raw return {row['raw_return']} != {want}")
    labels = [json.loads(p.read_text(encoding="utf-8"))["labels"] for p in run.glob("workers/w*/artifacts/*/metadata.json")]
    check(labels and all(l["reward_contract"] == "btt_reward_v2" and l["lifecycle"]["standby_preboot"] is True
                         and l["startup_mode"] in ("cold_start", "standby_promoted", "cold_fallback") for l in labels), "artifact labels")
    suite.shared["v2_standby_smoke_run"] = str(run)
    return {"n_envs": n, "episodes": s["episodes"], "falls_with_penalty": falls, "e2e_tps": s["throughput"]["end_to_end_transitions_per_s"],
            "lifecycle": {k: lc["standby"][k] for k in ("promotions", "hits_ready_at_reset", "late_hits_waited", "cold_fallbacks",
                                                        "standby_failures", "standby_lost", "hidden_startup_s_total", "exposed_wait_s_total")},
            "reset_modes": lc["reset_modes"], "checkpoints": [c["label"] for c in s["checkpoints"]],
            "evaluation": {m: ev["modes"][m]["aggregate"] for m in ev["modes"]}, "artifacts": len(labels),
            "rollout_return_means": [r["return_mean"] for r in s["rollouts"]]}


def resume_lifecycle_game(suite: Suite) -> Dict[str, Any]:
    """Resume the v2 standby smoke under standby off: refused; with resume.allow_lifecycle_change: one more rollout, recorded."""
    from m7_evaluation import CheckpointError
    from m7_trainer import config_from_experiment, run_training

    run = Path(suite.shared["v2_standby_smoke_run"])
    ck = run / "checkpoints" / "ckpt_000010240"
    n = int(suite.shared.get("selected_n", 2))
    common = {"environment.process_count": n, "ppo.n_steps": 5120 // n, "run.total_transitions": 15360, "checkpoint.interval": 5120,
              "evaluation.interval": 0, "evaluation.initial": False, "evaluation.final": False, "artifacts.periodic_episodes": 2,
              "run.mode": "resume", "resume.source_checkpoint": str(ck)}
    err = None
    try:
        config_from_experiment(derive(suite, V2_TOML, "resume_off_rejected", **common))
        run_training(config_from_experiment(derive(suite, V2_TOML, "resume_off_rejected2", **common)))
    except CheckpointError as exc:
        err = str(exc)
    check(err is not None and "allow_lifecycle_change" in err, f"resume across modes was not refused: {err}")
    check(not (suite.root / "resume_off_rejected2").exists(), "rejected resume created a run directory")
    exp = derive(suite, V2_TOML, "resume_off_allowed", **dict(common, **{"resume.allow_lifecycle_change": True}))
    s = run_training(config_from_experiment(exp))
    check(s["status"] == "completed" and s["cleanup"]["leak_free"] and s["timesteps"]["sb3_num_timesteps"] == 15360, str(s["timesteps"]))
    lineage = s["lineage"][-1]
    check(lineage["lifecycle_change"]["accepted_by"] == "resume.allow_lifecycle_change"
          and lineage["lifecycle_at_checkpoint"]["standby_preboot"] is True and s["lifecycle"]["settings"]["standby_preboot"] is False,
          f"lineage {lineage}")
    check(s["lifecycle"]["reset_modes"].get("standby_promoted", 0) == 0 and s["lifecycle"]["observed_max_concurrent_per_worker"] <= 1,
          "a standby-off resume must not promote")
    return {"rejected": err[:300], "resumed_timesteps": s["timesteps"], "lineage_change": lineage["lifecycle_change"],
            "reset_modes": s["lifecycle"]["reset_modes"]}


# -- runner --------------------------------------------------------------------------------------------------------

UNIT_CASES: Dict[str, Callable[[Suite], Dict[str, Any]]] = {
    "unit_state_machine": unit_state_machine,
    "unit_readiness_contract": unit_readiness_contract,
    "unit_config_lifecycle": unit_config_lifecycle,
    "unit_resume_lifecycle": unit_resume_lifecycle,
}
GAME_CASES: Dict[str, Callable[[Suite], Dict[str, Any]]] = {
    "cold_vs_standby_replay": cold_vs_standby_replay,
    "terminal_paths_promotion": terminal_paths_promotion,
    "shutdown_active_and_ready": shutdown_active_and_ready,
    "shutdown_while_starting": shutdown_while_starting,
    "wait_timeout_fallback": wait_timeout_fallback,
    "interrupt_active_play": interrupt_active_play,
    "interrupt_during_standby_launch": interrupt_during_standby_launch,
    "worker_exception_both_slots": worker_exception_both_slots,
    "active_timeout_then_promotion": active_timeout_then_promotion,
    "standby_startup_timeout_retry": standby_startup_timeout_retry,
    "standby_bind_failure_retry": standby_bind_failure_retry,
    "standby_exhausted_cold_fallback": standby_exhausted_cold_fallback,
    "standby_lost_after_ready": standby_lost_after_ready,
    "job_object_kill_standby": job_object_kill_standby,
    "startup_contention": startup_contention,
    "v2_standby_smoke": v2_standby_smoke,
    "resume_lifecycle_game": resume_lifecycle_game,
}
ALL_CASES = {**UNIT_CASES, **GAME_CASES}


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["_job_victim_standby"]:
        _job_victim_standby(argv[1])
        return 0
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cases", nargs="*", help="case names, 'unit' or 'game' (default: all)")
    parser.add_argument("--root", default=None, help="output root (default: runs/_m7c_tests_<utc>)")
    parser.add_argument("--selected-n", type=int, default=2, help="process count for the bounded v2 standby smoke")
    args = parser.parse_args(argv)
    names: List[str] = []
    for c in args.cases or list(ALL_CASES):
        names += list(UNIT_CASES) if c == "unit" else list(GAME_CASES) if c == "game" else [c]
    unknown = [n for n in names if n not in ALL_CASES]
    if unknown:
        parser.error(f"unknown case(s) {unknown}")
    if "resume_lifecycle_game" in names and "v2_standby_smoke" not in names:
        names.insert(names.index("resume_lifecycle_game"), "v2_standby_smoke")
    from m7_runtime import file_fingerprint, install_kill_on_close_job, wait_until_no_process

    install_kill_on_close_job()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = (Path(args.root) if args.root else REPO_ROOT / "runs" / f"_m7c_tests_{stamp}").resolve()
    root.mkdir(parents=True, exist_ok=False)
    suite = Suite(root)
    suite.shared["selected_n"] = args.selected_n
    user_cfg = file_fingerprint(USER_CONFIG)
    before = battleship_pids()
    if before:
        log(f"ERROR: BattleShip already running: {before}")
        return 2
    log(f"M7c tests: {len(names)} case(s), output {root}, user config sha256 {user_cfg['sha256'][:16]}")
    failures = 0
    for name in names:
        t0 = time.perf_counter()
        try:
            details = ALL_CASES[name](suite)
            ok, error = True, None
        except Exception as exc:  # noqa: BLE001 - reported per case
            ok, error, details = False, f"{type(exc).__name__}: {exc}", {"traceback": traceback.format_exc()[-6000:]}
        left = wait_until_no_process(timeout=20)
        cfg_now = file_fingerprint(USER_CONFIG)
        cfg_ok = cfg_now.get("sha256") == user_cfg.get("sha256") and cfg_now.get("mtime_ns") == user_cfg.get("mtime_ns")
        if left or not cfg_ok:
            ok = False
            error = (error or "") + f" | leaked {left}" * bool(left) + " | user config changed" * (not cfg_ok)
        failures += 0 if ok else 1
        suite.results[name] = {"ok": ok, "error": error, "wall_s": round(time.perf_counter() - t0, 2),
                               "battleship_after": left, "user_config_sha256_unchanged": cfg_now.get("sha256") == user_cfg.get("sha256"),
                               "user_config_mtime_unchanged": cfg_now.get("mtime_ns") == user_cfg.get("mtime_ns"), "details": details}
        log(f"{'PASS' if ok else 'FAIL'} {name} ({suite.results[name]['wall_s']} s)" + (f": {error}" if error else ""))
        with open(root / "m7c_tests_results.json", "w", encoding="utf-8", newline="\n") as fp:
            json.dump({"cases": suite.results, "user_config_start": user_cfg}, fp, indent=2, default=str)
    log(f"M7c tests: {len(names) - failures}/{len(names)} PASS; results {root / 'm7c_tests_results.json'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
