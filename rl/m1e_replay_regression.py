#!/usr/bin/env python3
"""M1e: permanent scripted-replay regression through the frozen M1d / M1c path.

Feeds the raw controller rows of tas_input_2/mario_743.btti to an ALREADY
RUNNING BattleShip, one row per M1d `step`, and requires the authoritative
Mario Break the Targets completion: consumed_tick 446, observation
input_tick 447, time_passed 446, targets_remaining 0, native state EpisodeEnded.

This script never launches, restarts, kills or resets BattleShip. Start a
fresh process yourself, from build-us/Release:

    SSB64_RL_BTT=1 SSB64_RL_STEP=1 SSB64_RL_PORT=5555 SSB64_SAVE_PATH=<save> ./BattleShip.exe

then run:

    python rl/m1e_replay_regression.py --port 5555
    python rl/m1e_replay_regression.py --port 5555 --delay-ms 25 --delay-every 20

One BattleShip process runs one episode and this regression ends it, so every
run needs a fresh process. A process that is already partway through an
episode, ended or stopping is refused with a non-zero exit; nothing is reset
or recovered.

Only 447 of the 468 source rows are consumed: the episode ends when row 446
breaks the last target, and the remaining 21 rows lie after the completion
cursor. They are deliberately not sent. The native replay regression (M0/M1a)
is what validates all 468 rows and their checksum.

Exit status: 0 PASS, 1 regression or precondition failure, 2 unusable or
malformed replay or bad usage (nothing was sent to BattleShip).
Standard library only.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from battleship_client import (  # noqa: E402
    DEFAULT_HOST,
    BattleShipClient,
    BattleShipError,
    Observation,
    ProtocolError,
    StepResult,
    StepState,
)
from btti_replay import ReplayFormatError, ReplayRow, read_btti_rows  # noqa: E402

# Frozen M0 / M1a / M1b / M1c contract for tas_input_2/mario_743.btti. The
# clocks are distinct and none is derived from another: consumed_tick and
# input_tick are native input ticks (one apart by M1c construction), time_passed
# is the in-game timer, step_count counts accepted steps.
OBSERVATION_SCHEMA = 1
SOURCE_ROWS = 468
MAX_TARGETS = 10
COMPLETION_STEPS = 447
COMPLETION_CONSUMED_TICK = 446
COMPLETION_INPUT_TICK = 447
COMPLETION_TIME_PASSED = 446

DEFAULT_REPLAY = Path(__file__).resolve().parent.parent / "tas_input_2" / "mario_743.btti"
REQUEST_TIMEOUT_S = 30.0  # per request, so a hung BattleShip fails instead of hanging the run
READY_POLL_S = 0.05

EXIT_PASS = 0
EXIT_FAILED = 1
EXIT_BAD_INPUT = 2

FRESH_EPISODE_HINT = "Regression requires a fresh BattleShip M1c episode; relaunch BattleShip and retry."


class RegressionFailure(Exception):
    """One violated expectation, carrying whatever context the report needs."""

    def __init__(
        self,
        reason: str,
        *,
        row: Optional[int] = None,
        expected_consumed_tick: Optional[int] = None,
        result: Optional[StepResult] = None,
        native_error: Optional[str] = None,
    ):
        super().__init__(reason)
        self.reason = reason
        self.row = row
        self.expected_consumed_tick = expected_consumed_tick
        self.result = result
        self.native_error = native_error
        self.native_state: Optional[str] = None  # filled in by main() once the client can be asked


@dataclass(frozen=True)
class Summary:
    source_rows: int
    steps: int
    completion: StepResult
    delay_ms: int
    delay_every: int
    delays_applied: int
    wall_s: float


def describe_error(exc: BaseException) -> str:
    if isinstance(exc, ProtocolError):  # includes NativeStepError
        code = f" native_code={exc.native_code}" if exc.native_code is not None else ""
        return f"{exc.error}{code}: {exc.message}"
    return f"{type(exc).__name__}: {exc}"


def best_effort_native_state(client: BattleShipClient) -> str:
    if not client.connected:
        return "unavailable (no connection)"
    try:
        status = client.status()
    except BattleShipError as exc:
        return f"unavailable ({exc})"
    return f"{status.state_name} can_step={status.can_step} step_count={status.step_count}"


def require_fresh_episode(client: BattleShipClient, ready_timeout: float) -> None:
    """Wait out boot (Inactive), then insist on WaitingForAction with step_count 0.

    BattleShipClient.wait_until_can_step is not enough here: it accepts any
    WaitingForAction, including an episode that is already partway through.
    Anything other than Inactive or WaitingForAction is refused immediately.
    """
    deadline = time.monotonic() + ready_timeout
    while True:
        status = client.status()
        if status.state == StepState.WAITING_FOR_ACTION:
            if status.step_count != 0:
                raise RegressionFailure(
                    f"{FRESH_EPISODE_HINT} The episode is already in progress (step_count={status.step_count})."
                )
            return
        if status.state != StepState.INACTIVE:
            raise RegressionFailure(f"{FRESH_EPISODE_HINT} Native state is {status.state_name}.")
        if time.monotonic() >= deadline:
            raise RegressionFailure(
                f"BattleShip was still Inactive after {ready_timeout:g} s; it never reached its first input tick "
                "(launched with SSB64_RL_BTT=1 SSB64_RL_STEP=1?)."
            )
        time.sleep(READY_POLL_S)


def check_step(row: int, result: StepResult, previous: Optional[Observation]) -> None:
    """Per-step invariants for source row `row` while the episode is active."""
    o = result.observation

    def require(condition: bool, reason: str) -> None:
        if not condition:
            raise RegressionFailure(reason, row=row, expected_consumed_tick=row, result=result)

    require(result.consumed_tick == row, f"consumed_tick is {result.consumed_tick}, expected {row}")
    require(o.input_tick == row + 1, f"observation.input_tick is {o.input_tick}, expected {row + 1}")
    require(result.step_count == row + 1, f"step_count is {result.step_count}, expected {row + 1}")
    require(
        o.observation_schema == OBSERVATION_SCHEMA,
        f"observation_schema is {o.observation_schema}, expected {OBSERVATION_SCHEMA}",
    )
    require(o.btt_active == 1, f"btt_active is {o.btt_active}, expected 1")
    require(o.fighter_valid == 1, f"fighter_valid is {o.fighter_valid}, expected 1")
    require(
        0 <= o.targets_remaining <= MAX_TARGETS,
        f"targets_remaining {o.targets_remaining} outside 0..{MAX_TARGETS}",
    )
    if o.targets_remaining == 0:
        expected_state, expected_name = StepState.EPISODE_ENDED, "EpisodeEnded"
    else:
        expected_state, expected_name = StepState.WAITING_FOR_ACTION, "WaitingForAction"
    require(
        result.state == expected_state,
        f"result state is {result.state_name}, expected {expected_name} with targets_remaining={o.targets_remaining}",
    )
    if previous is not None:
        require(
            o.targets_remaining <= previous.targets_remaining,
            f"targets_remaining rose from {previous.targets_remaining} to {o.targets_remaining}",
        )
        require(
            o.time_passed >= previous.time_passed,
            f"time_passed fell from {previous.time_passed} to {o.time_passed}",
        )


def check_completion(row: int, result: StepResult) -> None:
    """The first result with targets_remaining == 0 must be the frozen completion."""
    o = result.observation

    def require(condition: bool, reason: str) -> None:
        if not condition:
            raise RegressionFailure(
                reason, row=row, expected_consumed_tick=COMPLETION_CONSUMED_TICK, result=result
            )

    require(
        result.consumed_tick == COMPLETION_CONSUMED_TICK,
        f"completion consumed_tick is {result.consumed_tick}, expected {COMPLETION_CONSUMED_TICK}",
    )
    require(
        o.input_tick == COMPLETION_INPUT_TICK,
        f"completion input_tick is {o.input_tick}, expected {COMPLETION_INPUT_TICK}",
    )
    require(
        o.time_passed == COMPLETION_TIME_PASSED,
        f"completion time_passed is {o.time_passed}, expected {COMPLETION_TIME_PASSED}",
    )
    require(
        result.step_count == COMPLETION_STEPS,
        f"completion step_count is {result.step_count}, expected {COMPLETION_STEPS}",
    )
    require(
        result.state == StepState.EPISODE_ENDED,
        f"completion state is {result.state_name}, expected EpisodeEnded",
    )


def run_episode(client: BattleShipClient, rows: Sequence[ReplayRow], args: argparse.Namespace) -> Summary:
    require_fresh_episode(client, args.ready_timeout)

    delay_s = args.delay_ms / 1000.0
    delays_applied = 0
    previous: Optional[Observation] = None
    result: Optional[StepResult] = None
    completion: Optional[StepResult] = None
    completion_row = -1
    started = time.monotonic()

    for row_index, row in enumerate(rows):
        # Deterministic wall-clock gap before every delay_every-th row (row 0
        # included): the parked game must not notice it.
        if args.delay_ms > 0 and row_index % args.delay_every == 0:
            time.sleep(delay_s)
            delays_applied += 1
        try:
            result = client.step(row.buttons, row.stick_x, row.stick_y)
        except BattleShipError as exc:
            raise RegressionFailure(
                f"step for source row {row_index} was not completed",
                row=row_index,
                expected_consumed_tick=row_index,
                native_error=describe_error(exc),
            ) from exc
        check_step(row_index, result, previous)
        previous = result.observation
        if result.observation.targets_remaining == 0:
            completion, completion_row = result, row_index
            break

    if completion is None:
        raise RegressionFailure(
            f"all {len(rows)} source rows were consumed without reaching targets_remaining == 0",
            row=len(rows) - 1,
            expected_consumed_tick=COMPLETION_CONSUMED_TICK,
            result=result,
        )
    check_completion(completion_row, completion)

    status = client.status()
    if status.state != StepState.EPISODE_ENDED or status.can_step or status.step_count != COMPLETION_STEPS:
        raise RegressionFailure(
            "native status after completion is "
            f"{status.state_name} can_step={status.can_step} step_count={status.step_count}, "
            f"expected EpisodeEnded can_step=False step_count={COMPLETION_STEPS}",
            row=completion_row,
            expected_consumed_tick=COMPLETION_CONSUMED_TICK,
            result=completion,
        )

    return Summary(
        source_rows=len(rows),
        steps=completion.step_count,
        completion=completion,
        delay_ms=args.delay_ms,
        delay_every=args.delay_every,
        delays_applied=delays_applied,
        wall_s=time.monotonic() - started,
    )


def print_pass(summary: Summary) -> None:
    c, o = summary.completion, summary.completion.observation
    lines = [
        "M1e PASS",
        f"source_rows={summary.source_rows}",
        f"steps={summary.steps}",
        f"last_consumed_tick={c.consumed_tick}",
        f"completion_input_tick={o.input_tick}",
        f"completion_time_passed={o.time_passed}",
        f"targets_remaining={o.targets_remaining}",
        f"final_state={c.state_name}",
        f"rows_after_completion={summary.source_rows - summary.steps}",
    ]
    if summary.delay_ms > 0:
        lines.append(
            f"delay_ms={summary.delay_ms} delay_every={summary.delay_every} delays_applied={summary.delays_applied}"
        )
    lines.append(f"wall_s={summary.wall_s:.2f}")
    lines.append(f"host_frame_diagnostic={o.host_frame}")
    print("\n".join(lines), flush=True)


def print_failure(failure: RegressionFailure) -> None:
    lines = ["M1e FAIL", f"reason: {failure.reason}"]
    if failure.row is not None:
        lines.append(f"source_row: {failure.row}")
    if failure.expected_consumed_tick is not None:
        lines.append(f"expected_consumed_tick: {failure.expected_consumed_tick}")
    if failure.result is not None:
        r, o = failure.result, failure.result.observation
        lines += [
            f"actual_consumed_tick: {r.consumed_tick}",
            f"actual_observation_input_tick: {o.input_tick}",
            f"actual_time_passed: {o.time_passed}",
            f"targets_remaining: {o.targets_remaining}",
            f"step_count: {r.step_count}",
            f"result_state: {r.state_name}",
        ]
    elif failure.row is not None:
        lines.append("actual_consumed_tick: n/a (no step result)")
    if failure.native_error is not None:
        lines.append(f"native_error: {failure.native_error}")
    if failure.native_state is not None:
        lines.append(f"native_state: {failure.native_state}")
    print("\n".join(lines), flush=True)


def parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, required=True, help="SSB64_RL_PORT of the running BattleShip")
    parser.add_argument("--host", default=DEFAULT_HOST, help="host of the running BattleShip (default: %(default)s)")
    parser.add_argument(
        "--replay",
        default=str(DEFAULT_REPLAY),
        help="replay to feed; the expected results are fixed to the 468-row baseline (default: %(default)s)",
    )
    parser.add_argument(
        "--connect-timeout", type=float, default=30.0, help="retry a refused connection this many seconds (default: %(default)s)"
    )
    parser.add_argument(
        "--ready-timeout",
        type=float,
        default=180.0,
        help="seconds to wait for a booting BattleShip to reach its first input tick (default: %(default)s)",
    )
    parser.add_argument(
        "--delay-ms", type=int, default=0, help="sleep this many milliseconds before selected rows (default: none)"
    )
    parser.add_argument(
        "--delay-every",
        type=int,
        default=1,
        help="with --delay-ms, sleep before every Nth source row, starting with row 0 (default: %(default)s)",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be 1..65535")
    if args.delay_ms < 0:
        parser.error("--delay-ms must be >= 0")
    if args.delay_every < 1:
        parser.error("--delay-every must be >= 1")
    if args.connect_timeout < 0 or args.ready_timeout < 0:
        parser.error("timeouts must be >= 0")
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    # The replay is validated in full before any connection is made, so a bad
    # file can never leave BattleShip partway through an episode.
    try:
        rows = read_btti_rows(args.replay)
    except (OSError, ReplayFormatError) as exc:
        print(f"M1e ERROR: cannot use replay: {exc}", flush=True)
        return EXIT_BAD_INPUT
    if len(rows) != SOURCE_ROWS:
        print(
            f"M1e ERROR: {args.replay} has {len(rows)} rows; this regression is defined for the "
            f"{SOURCE_ROWS}-row baseline",
            flush=True,
        )
        return EXIT_BAD_INPUT

    client = BattleShipClient(port=args.port, host=args.host, timeout=REQUEST_TIMEOUT_S)
    failure: Optional[RegressionFailure] = None
    summary: Optional[Summary] = None
    try:
        client.connect(retry_timeout=args.connect_timeout)
        summary = run_episode(client, rows, args)
    except RegressionFailure as exc:
        failure = exc
    except BattleShipError as exc:  # transport failure outside a step: connect or status
        failure = RegressionFailure("transport failure before or after stepping", native_error=describe_error(exc))
    try:
        if failure is not None:
            failure.native_state = best_effort_native_state(client)
    finally:
        client.close()

    if failure is not None:
        print_failure(failure)
        return EXIT_FAILED
    assert summary is not None
    print_pass(summary)
    return EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
