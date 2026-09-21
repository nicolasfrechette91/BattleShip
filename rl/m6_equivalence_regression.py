"""M6: semantic-equivalence regression of the training no-render host mode.

Feeds the authoritative 7.43 s Mario Break the Targets replay
(tas_input_2/mario_743.btti, 468 rows) through the frozen M1d client into two
kinds of fresh BattleShip process, launched with the M2 lifecycle:

  normal      the default visual host path (render, present, paced)
  no_render   SSB64_RL_NO_RENDER=1 (display lists discarded, no present, no
              presentation pacing; the M6 training mode)

and compares EVERY submitted step, not only the terminal result: for each
of the 447 steps the step-level fields (state, step_count, consumed_tick)
and every authoritative observation field (input_tick, time_passed,
game_status, btt_active, targets_remaining, fighter_valid, position,
air velocities, ground velocity, facing direction, ground/air state, fighter
status, jumps used, observation_schema). The only field not compared is
host_frame, which is a diagnostic host counter by contract; it is still
recorded and reported (identical or not) but never asserted.

The initial observations (the M3 `observe` snapshot at fresh WaitingForAction,
input_tick 0) are compared the same way before any action is sent.

On top of the equivalence, the no-render trace must reproduce the frozen
contract on its own: 447 submitted actions, last consumed_tick 446,
completion_time_passed 446 and completion_input_tick 447 (two clocks, never
combined), final step_count 447, targets_remaining 0, native EpisodeEnded,
exit code 0, 21 source rows never submitted, and zero large_position_delta
events from the default M4 detector (300 units per tick). The process must
report no_render true in its `status` response, and the normal process
false, so the comparison cannot silently run two processes of the same kind.

Finally the canonical M4 artifact recorded from the normal run (native
triples + consumed ticks, rlaction_native_v1) is read back and resubmitted
through a third, fresh no-render process with run_artifacts.resubmit_actions;
its step results must equal the no-render trace field for field.

Nothing is tolerated: the first divergent step index and field is reported
and the run fails. No tolerances, no RNG inspection, no reward, no Gym.

Usage:
    python rl/m6_equivalence_regression.py
    python rl/m6_equivalence_regression.py --repeats 3 --out m6_equivalence.json
    python rl/m6_equivalence_regression.py --exe build-us/Release/BattleShip.exe --run-dir <dir>

Exit codes: 0 PASS, 1 divergence / regression / lifecycle failure, 2 bad input.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from battleship_client import BattleShipError, Observation, Observe, StepResult, StepState  # noqa: E402
from battleship_process import BattleShipEpisode, EpisodeFailure, LaunchConfig  # noqa: E402
from btti_replay import ReplayFormatError, ReplayRow, read_btti_rows  # noqa: E402
from m1e_replay_regression import (  # noqa: E402
    COMPLETION_CONSUMED_TICK,
    COMPLETION_INPUT_TICK,
    COMPLETION_STEPS,
    COMPLETION_TIME_PASSED,
    MAX_TARGETS,
    SOURCE_ROWS,
    RegressionFailure,
    check_completion,
    check_step,
)
from m2_restart_regression import EXPECTED_RESULT, describe_regression_failure  # noqa: E402
from run_artifacts import (  # noqa: E402
    DEFAULT_POSITION_DELTA_THRESHOLD,
    NATIVE_ACTION_CONTRACT,
    EpisodeRecorder,
    EpisodeStatus,
    PositionDeltaDetector,
    PreservationReason,
    read_artifact,
    resubmit_actions,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXECUTABLE = REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"
DEFAULT_REPLAY = REPO_ROOT / "tas_input_2" / "mario_743.btti"

NO_RENDER_ENV = "SSB64_RL_NO_RENDER"
NO_RENDER_CHILD_ENV = {NO_RENDER_ENV: "1"}

EXIT_PASS = 0
EXIT_FAILED = 1
EXIT_BAD_INPUT = 2

# Diagnostic by contract (M1b): the host's GamePostUpdateEvent counter. It is
# recorded and reported but never asserted, because boot and parked host
# iterations are not part of the simulation.
EXCLUDED_OBSERVATION_FIELDS = ("host_frame",)
OBSERVATION_FIELDS = tuple(f.name for f in fields(Observation) if f.name not in EXCLUDED_OBSERVATION_FIELDS)
STEP_FIELDS = ("state", "step_count", "consumed_tick")


def log(message: str) -> None:
    print(message, flush=True)


def count_battleship_processes(executable: Path) -> Optional[int]:
    name = executable.name
    try:
        if platform.system() == "Windows":
            out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
                                 capture_output=True, text=True, timeout=15, check=False).stdout
            return sum(1 for line in out.splitlines() if line.startswith(f'"{name}"'))
        out = subprocess.run(["pgrep", "-c", "-x", name], capture_output=True, text=True, timeout=15, check=False).stdout
        return int(out.strip() or 0)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


# -- traces -------------------------------------------------------------------------------------------


@dataclass
class StepRecord:
    """One accepted step, exactly as the M1d client returned it."""

    state: int
    state_name: str
    step_count: int
    consumed_tick: int
    observation: Observation

    def compared(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"state": self.state, "step_count": self.step_count, "consumed_tick": self.consumed_tick}
        for name in OBSERVATION_FIELDS:
            d[name] = getattr(self.observation, name)
        return d


@dataclass
class Trace:
    label: str
    no_render: bool
    pid: Optional[int] = None
    port: Optional[int] = None
    boot_s: Optional[float] = None
    stepping_s: Optional[float] = None
    initial: Optional[Observation] = None
    steps: List[StepRecord] = field(default_factory=list)
    exit_code: Optional[int] = None
    result: Dict[str, Any] = field(default_factory=dict)
    artifact_dir: Optional[Path] = None
    anomaly_events: int = 0
    rows_unsent: Optional[int] = None

    def summary(self) -> Dict[str, Any]:
        last = self.steps[-1] if self.steps else None
        return {
            "label": self.label, "no_render": self.no_render, "pid": self.pid, "port": self.port,
            "boot_to_fresh_s": None if self.boot_s is None else round(self.boot_s, 3),
            "stepping_wall_s": None if self.stepping_s is None else round(self.stepping_s, 3),
            "actions_submitted": len(self.steps),
            "rows_unsent": self.rows_unsent,
            "last_consumed_tick": last.consumed_tick if last else None,
            "final_step_count": last.step_count if last else None,
            "final_state": last.state_name if last else None,
            "completion_time_passed": last.observation.time_passed if last else None,
            "completion_input_tick": last.observation.input_tick if last else None,
            "targets_remaining": last.observation.targets_remaining if last else None,
            "host_frame_final": last.observation.host_frame if last else None,
            "exit_code": self.exit_code,
            "result_json_ok": all(self.result.get(k) == v for k, v in EXPECTED_RESULT.items()) if self.result else False,
            "anomaly_events_at_default_threshold": self.anomaly_events,
            "artifact_dir": str(self.artifact_dir) if self.artifact_dir else None,
        }


def read_no_render_flag(episode: BattleShipEpisode) -> bool:
    """The additive M6 `no_render` field of the status response; missing means an executable without M6."""
    assert episode.client is not None
    r = episode.client.request("status")
    if "no_render" not in r:
        raise RegressionFailure("status response has no `no_render` field: the executable predates M6 or was not rebuilt")
    if not isinstance(r["no_render"], bool):
        raise RegressionFailure(f"status.no_render must be a JSON boolean, got {r['no_render']!r}")
    return bool(r["no_render"])


def run_trace(label: str, index: int, config: LaunchConfig, rows: Sequence[ReplayRow], artifact_root: Path,
              expect_no_render: bool) -> Trace:
    """One fresh process, the replay through the raw M1d client, every step recorded, M4 artifact written."""
    trace = Trace(label=label, no_render=expect_no_render)
    episode = BattleShipEpisode(config, index=index)
    with episode:
        fresh = episode.start()
        trace.pid, trace.port = episode.pid, episode.port
        trace.boot_s = episode.seconds("launched", "fresh")
        if not (fresh.state == StepState.WAITING_FOR_ACTION and fresh.can_step and fresh.step_count == 0):
            raise RegressionFailure(f"{label}: episode is not fresh: {fresh.state_name} step_count={fresh.step_count}")
        actual_no_render = read_no_render_flag(episode)
        if actual_no_render != expect_no_render:
            raise RegressionFailure(f"{label}: process reports no_render={actual_no_render}, expected {expect_no_render} "
                                    f"(child env {dict(config.extra_env)})")
        client = episode.client
        assert client is not None
        initial: Observe = client.observe()
        if initial.observation.input_tick != 0 or initial.step_count != 0:
            raise RegressionFailure(f"{label}: initial observe is not the pre-tick-0 snapshot: {initial}")
        trace.initial = initial.observation
        recorder = EpisodeRecorder(episode_id=f"m6_{label}_{index}", source_action_contract=NATIVE_ACTION_CONTRACT,
                                   labels={"role": "m6_equivalence", "host_mode": label, "checkpoint_label": "scripted_baseline_7.43"},
                                   detectors=[PositionDeltaDetector(DEFAULT_POSITION_DELTA_THRESHOLD)], initial=initial,
                                   diagnostics={"pid": episode.pid, "port": episode.port, "child_env": dict(config.extra_env)})
        recorder.preserve(PreservationReason.MANUAL, f"M6 equivalence: {label} trace of the tracked 7.43 s baseline")
        log(f"  {label}: pid={episode.pid} port={episode.port} fresh after {trace.boot_s:.2f} s, no_render={actual_no_render}")

        previous: Optional[Observation] = None
        terminal: Optional[StepResult] = None
        t0 = time.perf_counter()
        for row_index, row in enumerate(rows):
            recorder.record_action(row.buttons, row.stick_x, row.stick_y)
            try:
                result = client.step(row.buttons, row.stick_x, row.stick_y)
            except BattleShipError as exc:
                raise episode.classify_step_failure(exc) from exc
            recorder.record_result(result)
            check_step(row_index, result, previous)
            trace.steps.append(StepRecord(int(result.state), result.state_name, result.step_count, result.consumed_tick,
                                          result.observation))
            previous = result.observation
            if result.observation.targets_remaining == 0:
                check_completion(row_index, result)
                terminal = result
                break
        trace.stepping_s = time.perf_counter() - t0
        if terminal is None:
            raise RegressionFailure(f"{label}: all {len(rows)} rows consumed without reaching targets_remaining == 0")
        trace.rows_unsent = len(rows) - len(trace.steps)

        done = episode.finish(terminal)
        trace.exit_code = done.exit_code
        trace.result = dict(done.result)
        for key, expected in EXPECTED_RESULT.items():
            if trace.result.get(key) != expected:
                raise RegressionFailure(f"{label}: result JSON {key} is {trace.result.get(key)!r}, expected {expected!r}")
        recorder.finish_from_step(terminal, EpisodeStatus.TERMINAL, targets_total=MAX_TARGETS,
                                  extra={"exit_code": done.exit_code})
        trace.anomaly_events = len(recorder.events)
        trace.artifact_dir = recorder.write(artifact_root)
    o = terminal.observation
    log(f"  {label}: {len(trace.steps)} actions in {trace.stepping_s:.2f} s, terminal {terminal.state_name} "
        f"consumed_tick={terminal.consumed_tick} time_passed={o.time_passed} input_tick={o.input_tick} "
        f"step_count={terminal.step_count} targets={o.targets_remaining} host_frame={o.host_frame} exit={trace.exit_code} "
        f"rows_unsent={trace.rows_unsent} anomaly_events={trace.anomaly_events} artifact={trace.artifact_dir.name}")
    return trace


# -- comparison ---------------------------------------------------------------------------------------


@dataclass
class Divergence:
    where: str  # "initial" or "step <index>"
    field: str
    reference: Any
    candidate: Any

    def __str__(self) -> str:
        return f"{self.where}: {self.field} differs: reference={self.reference!r} candidate={self.candidate!r}"


def compare_observations(where: str, reference: Observation, candidate: Observation) -> Optional[Divergence]:
    for name in OBSERVATION_FIELDS:
        a, b = getattr(reference, name), getattr(candidate, name)
        if a != b or type(a) is not type(b):
            return Divergence(where, name, a, b)
    return None


def compare_traces(reference: Trace, candidate: Trace) -> Tuple[Optional[Divergence], bool]:
    """First divergence on the authoritative fields (None if equivalent) and whether host_frame matched throughout."""
    host_frames_identical = True
    assert reference.initial is not None and candidate.initial is not None
    d = compare_observations("initial", reference.initial, candidate.initial)
    if d is not None:
        return d, host_frames_identical
    host_frames_identical &= reference.initial.host_frame == candidate.initial.host_frame
    n = min(len(reference.steps), len(candidate.steps))
    for i in range(n):
        r, c = reference.steps[i], candidate.steps[i]
        for name in STEP_FIELDS:
            if getattr(r, name) != getattr(c, name):
                return Divergence(f"step {i}", name, getattr(r, name), getattr(c, name)), host_frames_identical
        d = compare_observations(f"step {i}", r.observation, c.observation)
        if d is not None:
            return d, host_frames_identical
        host_frames_identical &= r.observation.host_frame == c.observation.host_frame
    if len(reference.steps) != len(candidate.steps):
        return Divergence(f"step {n}", "actions_submitted", len(reference.steps), len(candidate.steps)), host_frames_identical
    return None, host_frames_identical


def check_frozen_contract(trace: Trace) -> None:
    last = trace.steps[-1]
    o = last.observation
    checks = [
        (len(trace.steps) == COMPLETION_STEPS, f"actions submitted {len(trace.steps)} != {COMPLETION_STEPS}"),
        (last.consumed_tick == COMPLETION_CONSUMED_TICK, f"last consumed_tick {last.consumed_tick} != {COMPLETION_CONSUMED_TICK}"),
        (o.time_passed == COMPLETION_TIME_PASSED, f"completion_time_passed {o.time_passed} != {COMPLETION_TIME_PASSED}"),
        (o.input_tick == COMPLETION_INPUT_TICK, f"completion_input_tick {o.input_tick} != {COMPLETION_INPUT_TICK}"),
        (last.step_count == COMPLETION_STEPS, f"final step_count {last.step_count} != {COMPLETION_STEPS}"),
        (o.targets_remaining == 0, f"targets_remaining {o.targets_remaining} != 0"),
        (last.state == int(StepState.EPISODE_ENDED), f"final state {last.state_name} != EpisodeEnded"),
        (trace.exit_code == 0, f"exit code {trace.exit_code} != 0"),
        (trace.rows_unsent == SOURCE_ROWS - COMPLETION_STEPS, f"rows unsent {trace.rows_unsent} != {SOURCE_ROWS - COMPLETION_STEPS}"),
        (trace.anomaly_events == 0, f"{trace.anomaly_events} large_position_delta event(s) at the default "
                                     f"{DEFAULT_POSITION_DELTA_THRESHOLD:g}-unit threshold"),
    ]
    for ok, message in checks:
        if not ok:
            raise RegressionFailure(f"{trace.label}: frozen contract violated: {message}")


def replay_artifact(index: int, config: LaunchConfig, artifact_dir: Path, reference: Trace) -> Dict[str, Any]:
    """Canonical M4 artifact -> fresh no-render process; results must equal the no-render trace."""
    art = read_artifact(artifact_dir)
    if art.metadata["action_contract"] != NATIVE_ACTION_CONTRACT or len(art.actions) != COMPLETION_STEPS:
        raise RegressionFailure(f"artifact {artifact_dir.name}: contract {art.metadata['action_contract']} / {len(art.actions)} rows")
    trace = Trace(label="artifact_replay_no_render", no_render=True)
    collected: List[StepRecord] = []
    episode = BattleShipEpisode(config, index=index)
    with episode:
        fresh = episode.start()
        trace.pid, trace.port, trace.boot_s = episode.pid, episode.port, episode.seconds("launched", "fresh")
        if not (fresh.state == StepState.WAITING_FOR_ACTION and fresh.can_step and fresh.step_count == 0):
            raise RegressionFailure(f"artifact replay: episode is not fresh: {fresh.state_name}")
        if read_no_render_flag(episode) is not True:
            raise RegressionFailure("artifact replay: process is not in no-render mode")
        client = episode.client
        assert client is not None
        trace.initial = client.observe().observation
        t0 = time.perf_counter()
        try:
            results = resubmit_actions(client, art.actions, on_result=lambda a, r: collected.append(
                StepRecord(int(r.state), r.state_name, r.step_count, r.consumed_tick, r.observation)))
        except BattleShipError as exc:
            raise episode.classify_step_failure(exc) from exc
        trace.stepping_s = time.perf_counter() - t0
        trace.steps = collected
        trace.rows_unsent = SOURCE_ROWS - len(collected)
        terminal = results[-1]
        if terminal.state != StepState.EPISODE_ENDED:
            raise RegressionFailure(f"artifact replay ended in {terminal.state_name} after {len(results)} actions")
        done = episode.finish(terminal)
        trace.exit_code = done.exit_code
        trace.result = dict(done.result)
    divergence, host_frames_identical = compare_traces(reference, trace)
    if divergence is not None:
        raise RegressionFailure(f"artifact replay through no-render diverges from the no-render trace: {divergence}")
    check_frozen_contract(trace)
    log(f"  artifact_replay: {len(collected)} recorded actions through a fresh no-render process reproduced the "
        f"no-render trace field for field ({len(OBSERVATION_FIELDS)} observation fields + {len(STEP_FIELDS)} step fields), "
        f"terminal {trace.steps[-1].observation.time_passed}/{trace.steps[-1].observation.input_tick}, exit {trace.exit_code}, "
        f"host_frames_identical={host_frames_identical}")
    return {**trace.summary(), "host_frames_identical_to_no_render_trace": host_frames_identical}


# -- main -------------------------------------------------------------------------------------------


def parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--exe", default=str(DEFAULT_EXECUTABLE), help="BattleShip executable (default: %(default)s)")
    parser.add_argument("--run-dir", default=None, help="parent of the per-episode and artifact directories (default: a new temp dir)")
    parser.add_argument("--replay", default=str(DEFAULT_REPLAY), help="authoritative replay (default: %(default)s)")
    parser.add_argument("--repeats", type=int, default=1, help="no-render traces to compare against the normal trace (default: %(default)s)")
    parser.add_argument("--out", default=None, help="write a JSON summary of the comparison here")
    parser.add_argument("--startup-timeout", type=float, default=60.0)
    parser.add_argument("--ready-timeout", type=float, default=180.0)
    parser.add_argument("--request-timeout", type=float, default=30.0)
    parser.add_argument("--exit-timeout", type=float, default=30.0)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.repeats < 1:
        log("M6 ERROR: --repeats must be >= 1")
        return EXIT_BAD_INPUT
    try:
        rows = read_btti_rows(args.replay)
    except (OSError, ReplayFormatError) as exc:
        log(f"M6 ERROR: cannot use replay: {exc}")
        return EXIT_BAD_INPUT
    if len(rows) != SOURCE_ROWS:
        log(f"M6 ERROR: {args.replay} has {len(rows)} rows; this regression is defined for the {SOURCE_ROWS}-row baseline")
        return EXIT_BAD_INPUT
    executable = Path(args.exe)
    if not executable.is_file():
        log(f"M6 ERROR: executable not found: {executable}")
        return EXIT_BAD_INPUT
    run_root = Path(args.run_dir) if args.run_dir else Path(tempfile.mkdtemp(prefix="battleship_m6_"))
    run_root.mkdir(parents=True, exist_ok=True)
    artifacts = run_root / "artifacts"
    artifacts.mkdir(exist_ok=True)

    def launch_config(extra_env: Dict[str, str]) -> LaunchConfig:
        return LaunchConfig(executable=executable, run_root=run_root, startup_timeout=args.startup_timeout,
                            ready_timeout=args.ready_timeout, request_timeout=args.request_timeout,
                            exit_timeout=args.exit_timeout, extra_env=extra_env)

    normal_config = launch_config({})
    no_render_config = launch_config(dict(NO_RENDER_CHILD_ENV))

    before = count_battleship_processes(executable)
    log(f"M6 equivalence: {executable.name} processes before: {before}; replay {Path(args.replay).name} ({len(rows)} rows); "
        f"comparing {len(STEP_FIELDS)} step fields + {len(OBSERVATION_FIELDS)} observation fields per step; "
        f"excluded (diagnostic, reported only): {', '.join(EXCLUDED_OBSERVATION_FIELDS)}")
    report: Dict[str, Any] = {
        "tool": "rl/m6_equivalence_regression.py",
        "replay": Path(args.replay).name,
        "source_rows": len(rows),
        "no_render_child_env": dict(NO_RENDER_CHILD_ENV),
        "compared_step_fields": list(STEP_FIELDS),
        "compared_observation_fields": list(OBSERVATION_FIELDS),
        "excluded_observation_fields": list(EXCLUDED_OBSERVATION_FIELDS),
        "excluded_reason": "host_frame is the host GamePostUpdateEvent counter, diagnostic by the M1b contract; "
                           "reported as host_frames_identical, never asserted",
        "traces": [],
        "comparisons": [],
        "artifact_replay": None,
        "result": None,
    }
    failure: Optional[str] = None
    try:
        log("[normal] default visual host path")
        normal = run_trace("normal", 6000, normal_config, rows, artifacts, expect_no_render=False)
        check_frozen_contract(normal)
        report["traces"].append(normal.summary())

        for k in range(args.repeats):
            log(f"[no_render {k + 1}/{args.repeats}] {NO_RENDER_ENV}=1 training host path")
            candidate = run_trace("no_render", 6100 + k, no_render_config, rows, artifacts, expect_no_render=True)
            report["traces"].append(candidate.summary())
            divergence, host_frames_identical = compare_traces(normal, candidate)
            comparison = {
                "candidate": candidate.label, "candidate_index": k, "steps_compared": min(len(normal.steps), len(candidate.steps)),
                "equivalent": divergence is None, "first_divergence": None if divergence is None else vars(divergence),
                "host_frames_identical": host_frames_identical,
                "stepping_wall_s": {"normal": round(normal.stepping_s or 0.0, 3), "no_render": round(candidate.stepping_s or 0.0, 3)},
            }
            report["comparisons"].append(comparison)
            if divergence is not None:
                raise RegressionFailure(f"normal vs no_render diverge: {divergence}")
            check_frozen_contract(candidate)
            log(f"  equivalent: {comparison['steps_compared']} steps + initial observation identical on every compared field; "
                f"host_frames_identical={host_frames_identical}; stepping wall normal {normal.stepping_s:.2f} s vs "
                f"no_render {candidate.stepping_s:.2f} s (informational, not a benchmark)")
            if k == 0:
                assert normal.artifact_dir is not None
                log("[artifact_replay] canonical M4 artifact of the normal trace -> fresh no-render process")
                report["artifact_replay"] = replay_artifact(6200, no_render_config, normal.artifact_dir, candidate)
    except RegressionFailure as exc:
        failure = describe_regression_failure(exc) if exc.row is not None else str(exc)
    except EpisodeFailure as exc:
        failure = f"lifecycle failure {exc.outcome.value}: {exc}"
    except BattleShipError as exc:
        failure = f"client error: {exc}"

    after = count_battleship_processes(executable)
    leaked = before is not None and after is not None and after > before
    report["process_count"] = {"before": before, "after": after, "leaked": leaked}
    if failure is None and leaked:
        failure = f"{executable.name} count rose from {before} to {after}"
    report["result"] = "PASS" if failure is None else "FAIL"
    report["failure"] = failure
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        log(f"summary written to {args.out}")
    log(f"run_dir={run_root}")
    if failure is None:
        log(f"M6 EQUIVALENCE PASS: normal vs no_render x{args.repeats}: every compared field identical on all "
            f"{COMPLETION_STEPS} steps; no_render reproduces {COMPLETION_STEPS}/{COMPLETION_CONSUMED_TICK}/"
            f"{COMPLETION_TIME_PASSED}/{COMPLETION_INPUT_TICK}, exit 0, {SOURCE_ROWS - COMPLETION_STEPS} rows unsent, "
            f"0 anomaly events; artifact replay identical; processes before={before} after={after}")
        return EXIT_PASS
    log(f"M6 EQUIVALENCE FAIL: {failure}")
    return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
