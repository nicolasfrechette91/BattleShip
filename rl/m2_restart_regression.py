#!/usr/bin/env python3
"""M2: repeated fresh-process regression for Mario Break the Targets.

Runs N consecutive episodes (default 3). Every episode launches a NEW
BattleShip process through rl/battleship_process.py, proves it fresh
(WaitingForAction, can_step, step_count 0), feeds tas_input_2/mario_743.btti
one row per M1d step with the M1e per-step and completion checks, collects
the terminal EpisodeEnded result, waits for the native clean exit
(SSB64_RL_EXIT_ON_END=1), and validates the isolated result JSON against the
frozen M1a values. The previous process must be gone before the next one is
launched; nothing is ever reset in-process.

    python rl/m2_restart_regression.py
    python rl/m2_restart_regression.py --episodes 5 --exe build-us/Release/BattleShip.exe

Per-episode files (save, result JSON, process log) live in a unique directory
under --run-dir (default: a fresh temp dir, printed at the end). Only 447 of
the 468 source rows are consumed; the last 21 lie after the completion cursor
and are never sent. The native replay regression (M0/M1a) owns all 468 rows
and their checksum; nothing here recomputes it.

Exit status: 0 PASS, 1 any episode or invariant failed, 2 unusable replay or
bad usage. Standard library only.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from battleship_client import BattleShipError, Observation, StepResult, StepState  # noqa: E402
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
    MAX_TARGETS,
    SOURCE_ROWS,
    RegressionFailure,
    check_completion,
    check_step,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXECUTABLE = REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"

# Frozen M1a result values for the baseline (docs: result schema 1).
EXPECTED_RESULT = {
    "result_schema": 1,
    "outcome": "clear",
    "targets_broken": MAX_TARGETS,
    "completion_time_passed": COMPLETION_TIME_PASSED,
    "completion_input_tick": COMPLETION_INPUT_TICK,
    "time_passed_final": COMPLETION_TIME_PASSED,
    "input_cursor_final": COMPLETION_INPUT_TICK,
}
# host_frames is diagnostic: present, an integer, never compared across runs.

EXIT_PASS = 0
EXIT_FAILED = 1
EXIT_BAD_INPUT = 2


@dataclass
class EpisodeReport:
    index: int
    outcome: str = "not_started"
    pid: Optional[int] = None
    port: Optional[int] = None
    directory: Optional[Path] = None
    save_path: Optional[Path] = None
    result_path: Optional[Path] = None
    log_path: Optional[Path] = None
    fresh_step_count: Optional[int] = None
    steps: int = 0
    last_consumed_tick: Optional[int] = None
    completion_time_passed: Optional[int] = None
    completion_input_tick: Optional[int] = None
    targets_remaining: Optional[int] = None
    final_state: Optional[str] = None
    exit_code: Optional[int] = None
    cleanup_action: Optional[str] = None
    result_ok: bool = False
    host_frames: Optional[int] = None
    boot_s: Optional[float] = None
    episode_s: Optional[float] = None
    failure: Optional[str] = None

    @property
    def completed(self) -> bool:
        return self.outcome == EpisodeOutcome.COMPLETED.value


def log(message: str) -> None:
    print(message, flush=True)


def step_rows(episode: BattleShipEpisode, rows: Sequence[ReplayRow], report: EpisodeReport) -> StepResult:
    """Submit rows one at a time with the M1e checks; stop at the terminal result."""
    assert episode.client is not None
    previous: Optional[Observation] = None
    result: Optional[StepResult] = None
    for row_index, row in enumerate(rows):
        try:
            result = episode.client.step(row.buttons, row.stick_x, row.stick_y)
        except BattleShipError as exc:
            raise episode.classify_step_failure(exc) from exc
        check_step(row_index, result, previous)
        report.steps = result.step_count
        report.last_consumed_tick = result.consumed_tick
        previous = result.observation
        if result.observation.targets_remaining == 0:
            check_completion(row_index, result)
            return result
    raise RegressionFailure(
        f"all {len(rows)} source rows were consumed without reaching targets_remaining == 0",
        row=len(rows) - 1,
        expected_consumed_tick=COMPLETION_CONSUMED_TICK,
        result=result,
    )


def check_result_json(result: Dict[str, object]) -> None:
    for key, expected in EXPECTED_RESULT.items():
        if result.get(key) != expected:
            raise RegressionFailure(f"result JSON {key} is {result.get(key)!r}, expected {expected!r}")


def run_one_episode(index: int, config: LaunchConfig, rows: Sequence[ReplayRow]) -> EpisodeReport:
    report = EpisodeReport(index=index)
    episode = BattleShipEpisode(config, index=index)
    try:
        with episode:
            fresh = episode.start()
            report.pid, report.port = episode.pid, episode.port
            assert episode.paths is not None
            report.directory = episode.paths.directory
            report.save_path = episode.paths.save_path
            report.result_path = episode.paths.result_path
            report.log_path = episode.paths.log_path
            report.boot_s = episode.seconds("launched", "fresh")
            # Proved by start(); restated here so the report carries the evidence.
            if not (fresh.state == StepState.WAITING_FOR_ACTION and fresh.can_step and fresh.step_count == 0):
                raise RegressionFailure(
                    f"episode is not fresh: {fresh.state_name} can_step={fresh.can_step} step_count={fresh.step_count}"
                )
            report.fresh_step_count = fresh.step_count
            log(f"  episode {index}: pid={episode.pid} port={episode.port} fresh {fresh.state_name} "
                f"step_count={fresh.step_count} after {report.boot_s:.1f} s")

            started = time.monotonic()
            terminal = step_rows(episode, rows, report)
            report.episode_s = time.monotonic() - started
            o = terminal.observation
            report.completion_time_passed = o.time_passed
            report.completion_input_tick = o.input_tick
            report.targets_remaining = o.targets_remaining
            report.final_state = terminal.state_name
            report.host_frames = o.host_frame
            log(f"  episode {index}: terminal {terminal.state_name} consumed_tick={terminal.consumed_tick} "
                f"input_tick={o.input_tick} time_passed={o.time_passed} targets={o.targets_remaining} "
                f"step_count={terminal.step_count} in {report.episode_s:.1f} s")

            done = episode.finish(terminal)
            report.exit_code = done.exit_code
            check_result_json(done.result)
            report.result_ok = True
            report.outcome = EpisodeOutcome.COMPLETED.value
            log(f"  episode {index}: exit_code={done.exit_code} result JSON ok "
                f"({done.result['targets_broken']}/{done.result['completion_time_passed']}/"
                f"{done.result['completion_input_tick']}, host_frames={done.result['host_frames']})")
    except EpisodeFailure as exc:
        report.outcome = exc.outcome.value
        report.failure = str(exc)
        report.exit_code = exc.exit_code if exc.exit_code is not None else report.exit_code
    except RegressionFailure as exc:
        report.outcome = "regression_failure"
        report.failure = describe_regression_failure(exc)
    finally:
        report.cleanup_action = episode.cleanup_action
        if report.exit_code is None:
            report.exit_code = episode.exit_code
        if episode.alive:  # close() raises cleanup_failure before this can be true; belt and braces
            report.outcome = EpisodeOutcome.CLEANUP_FAILURE.value
            report.failure = f"pid {episode.pid} still alive after cleanup"
    return report


def describe_regression_failure(exc: RegressionFailure) -> str:
    parts = [exc.reason]
    if exc.row is not None:
        parts.append(f"source_row={exc.row}")
    if exc.expected_consumed_tick is not None:
        parts.append(f"expected_consumed_tick={exc.expected_consumed_tick}")
    if exc.result is not None:
        r, o = exc.result, exc.result.observation
        parts.append(
            f"actual consumed_tick={r.consumed_tick} input_tick={o.input_tick} time_passed={o.time_passed} "
            f"targets_remaining={o.targets_remaining} step_count={r.step_count} state={r.state_name}"
        )
    if exc.native_error is not None:
        parts.append(f"native_error={exc.native_error}")
    return "; ".join(parts)


def check_fresh_process_invariants(reports: Sequence[EpisodeReport]) -> List[str]:
    """Every episode used a new directory, save path, result path and log path."""
    problems: List[str] = []
    for name in ("directory", "save_path", "result_path", "log_path"):
        values = [getattr(r, name) for r in reports if getattr(r, name) is not None]
        if len(set(values)) != len(values):
            problems.append(f"{name} reused between episodes")
    return problems


def print_summary(reports: Sequence[EpisodeReport], run_root: Path, all_fresh: bool, all_exited: bool,
                  passed: bool) -> None:
    lines = [f"M2 {'PASS' if passed else 'FAIL'}", f"episodes={len(reports)}", ""]
    for r in reports:
        completion = (
            f"{r.completion_time_passed}/{r.completion_input_tick}"
            if r.completion_time_passed is not None
            else "n/a"
        )
        lines.append(
            f"episode={r.index} outcome={r.outcome} pid={r.pid} fresh_step_count={r.fresh_step_count} "
            f"steps={r.steps} last_consumed_tick={r.last_consumed_tick} completion={completion} "
            f"targets_remaining={r.targets_remaining} final_state={r.final_state} exit_code={r.exit_code} "
            f"cleanup={r.cleanup_action} result_json={'ok' if r.result_ok else 'not_validated'}"
        )
        if r.failure:
            lines.append(f"  failure: {r.failure}")
    lines += [
        "",
        f"source_rows={SOURCE_ROWS}",
        f"rows_after_completion={SOURCE_ROWS - COMPLETION_STEPS}",
        f"all_fresh={'true' if all_fresh else 'false'}",
        f"all_processes_exited={'true' if all_exited else 'false'}",
        f"run_dir={run_root}",
    ]
    print("\n".join(lines), flush=True)


def parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--episodes", type=int, default=3, help="consecutive fresh processes to run (default: %(default)s)")
    parser.add_argument("--exe", default=str(DEFAULT_EXECUTABLE), help="BattleShip executable (default: %(default)s)")
    parser.add_argument("--working-dir", default=None, help="child working directory (default: the executable's directory)")
    parser.add_argument("--run-dir", default=None, help="parent of the per-episode directories (default: a new temp dir)")
    parser.add_argument("--replay", default=str(DEFAULT_REPLAY), help="replay to feed (default: %(default)s)")
    parser.add_argument("--startup-timeout", type=float, default=60.0, help="seconds for the transport to appear")
    parser.add_argument("--ready-timeout", type=float, default=180.0, help="seconds for fresh WaitingForAction")
    parser.add_argument("--request-timeout", type=float, default=30.0, help="seconds per M1d request")
    parser.add_argument("--exit-timeout", type=float, default=30.0, help="seconds for the native clean exit")
    args = parser.parse_args(argv)
    if args.episodes < 1:
        parser.error("--episodes must be >= 1")
    for name in ("startup_timeout", "ready_timeout", "request_timeout", "exit_timeout"):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be > 0")
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    try:
        rows = read_btti_rows(args.replay)
    except (OSError, ReplayFormatError) as exc:
        log(f"M2 ERROR: cannot use replay: {exc}")
        return EXIT_BAD_INPUT
    if len(rows) != SOURCE_ROWS:
        log(f"M2 ERROR: {args.replay} has {len(rows)} rows; this regression is defined for the {SOURCE_ROWS}-row baseline")
        return EXIT_BAD_INPUT

    executable = Path(args.exe)
    if not executable.is_file():
        log(f"M2 ERROR: executable not found: {executable}")
        return EXIT_BAD_INPUT
    run_root = Path(args.run_dir) if args.run_dir else Path(tempfile.mkdtemp(prefix="battleship_m2_"))
    config = LaunchConfig(
        executable=executable,
        working_dir=Path(args.working_dir) if args.working_dir else None,
        run_root=run_root,
        startup_timeout=args.startup_timeout,
        ready_timeout=args.ready_timeout,
        request_timeout=args.request_timeout,
        exit_timeout=args.exit_timeout,
    )

    reports: List[EpisodeReport] = []
    previous: Optional[EpisodeReport] = None
    all_exited = True
    for index in range(1, args.episodes + 1):
        log(f"[episode {index}/{args.episodes}]")
        if previous is not None and previous.outcome == EpisodeOutcome.CLEANUP_FAILURE.value:
            log(f"M2 ERROR: episode {previous.index} left a live process; not launching episode {index}")
            all_exited = False
            break
        report = run_one_episode(index, config, rows)
        reports.append(report)
        log(f"  episode {index}: {report.outcome} (cleanup={report.cleanup_action})")
        previous = report

    problems = check_fresh_process_invariants(reports)
    all_fresh = all(r.fresh_step_count == 0 for r in reports) and len(reports) == args.episodes and not problems
    all_exited = all_exited and all(r.exit_code is not None for r in reports)
    passed = all_fresh and all_exited and all(r.completed for r in reports)
    for problem in problems:
        log(f"M2 invariant violated: {problem}")
    print_summary(reports, run_root, all_fresh, all_exited, passed)
    return EXIT_PASS if passed else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
