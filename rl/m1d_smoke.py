#!/usr/bin/env python3
"""M1d smoke tests: drive a running BattleShip through the loopback transport.

Launch BattleShip yourself first (M1d has no process management). From
build-us/Release, with an isolated save file:

    SSB64_RL_BTT=1 SSB64_RL_STEP=1 SSB64_RL_PORT=5555 SSB64_SAVE_PATH=<save> ./BattleShip.exe

then run one or more tests against it:

    python rl/m1d_smoke.py --port 5555 errors single delayed disconnect
    python rl/m1d_smoke.py --port 5555 baseline --btti tas_input_2/mario_743.btti
    python rl/m1d_smoke.py --port 5555 shutdown        # game launched with SSB64_MAX_FRAMES

One BattleShip process runs one episode, so `baseline` (which clears the
stage) and `shutdown` (which waits for the process to exit) each need a fresh
process. The other tests submit only neutral input and can share a process.

Exit status is 0 only if every requested test passed. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from typing import Callable, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from battleship_client import (  # noqa: E402
    BattleShipClient,
    Button,
    ConnectionClosed,
    NativeStepError,
    StepResult,
    StepState,
)

NEUTRAL = (int(Button.NONE), 0, 0)

# Frozen M0 / M1a completion point of tas_input_2/mario_743.btti.
BASELINE_ROWS = 468
BASELINE_TIME_PASSED = 446
BASELINE_INPUT_TICK = 447
BASELINE_TARGETS = 10

# Deliberately irregular wall-clock delays (seconds) inserted before the
# given rows of the baseline run, plus a small delay every 37th row.
BASELINE_DELAYS: Dict[int, float] = {5: 2.0, 60: 0.5, 120: 3.0, 200: 1.5, 300: 4.0, 400: 1.0, 440: 2.5}


def log(message: str) -> None:
    print(message, flush=True)


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def read_btti_rows(path: str) -> List[Tuple[int, int, int]]:
    """Parse the BTT text replay exactly as decomp/src/sys/netreplay.c does:
    '#' comments and blank lines skipped, rows are buttons_hex,stick_x,stick_y
    with buttons in 0..0xFFFF and sticks in -128..127."""
    rows: List[Tuple[int, int, int]] = []
    with open(path, encoding="utf-8") as fp:
        for lineno, line in enumerate(fp, 1):
            if line.startswith("#") or line.strip() == "":
                continue
            parts = line.strip().split(",")
            if len(parts) != 3:
                raise ValueError(f"{path}:{lineno}: expected buttons_hex,stick_x,stick_y")
            buttons, stick_x, stick_y = int(parts[0], 16), int(parts[1]), int(parts[2])
            if not (0 <= buttons <= 0xFFFF and -128 <= stick_x <= 127 and -128 <= stick_y <= 127):
                raise ValueError(f"{path}:{lineno}: value out of native range")
            rows.append((buttons, stick_x, stick_y))
    return rows


def new_client(args: argparse.Namespace) -> BattleShipClient:
    client = BattleShipClient(port=args.port, host=args.host, timeout=args.timeout)
    client.connect(retry_timeout=args.connect_timeout)
    return client


def describe(result: StepResult) -> str:
    o = result.observation
    return (
        f"consumed_tick={result.consumed_tick} input_tick={o.input_tick} time_passed={o.time_passed} "
        f"targets={o.targets_remaining} pos=({o.position_x:.2f},{o.position_y:.2f}) state={result.state_name}"
    )


# -- tests ---------------------------------------------------------------------


def test_single(args: argparse.Namespace) -> None:
    """Connect, wait for activation, submit neutral actions, check the pairing."""
    with new_client(args) as client:
        client.ping()
        s0 = client.wait_until_can_step(timeout=args.boot_timeout)
        log(f"  activation: state={s0.state_name} can_step={s0.can_step} step_count={s0.step_count}")

        prev = client.step(*NEUTRAL)
        expect(prev.observation.observation_schema == 1, "unexpected observation schema")
        expect(prev.observation.input_tick == prev.consumed_tick + 1, "input_tick must be consumed_tick + 1")
        expect(prev.step_count == s0.step_count + 1, "step_count must advance by one")
        if s0.step_count == 0:
            expect(prev.consumed_tick == 0, f"the first step of the episode consumed {prev.consumed_tick}, expected 0")
        t0 = prev.consumed_tick
        log(f"  step 1: {describe(prev)}")

        for i in range(2, 7):
            s = client.status()
            expect(s.can_step and s.state == StepState.WAITING_FOR_ACTION, f"expected WaitingForAction, got {s}")
            expect(s.step_count == prev.step_count, "status step_count must match the last result")
            r = client.step(*NEUTRAL)
            expect(r.consumed_tick == prev.observation.input_tick, "each step must consume the next tick")
            expect(r.observation.input_tick == r.consumed_tick + 1, "input_tick must be consumed_tick + 1")
            expect(r.observation.host_frame == prev.observation.host_frame + 1,
                   "exactly one host update may run per step (status must not advance anything)")
            expect(r.step_count == prev.step_count + 1, "step_count must advance by exactly one per request")
            prev = r
        log(f"  step 6: {describe(prev)}")
        log(f"  6 requests -> 6 native ticks (consumed {t0}..{prev.consumed_tick}), host_frame +1 per step")


def test_delayed(args: argparse.Namespace, delays: Sequence[float] = (2.0, 3.5, 5.0)) -> None:
    """Several seconds of Python-side waiting must not change native BTT state."""
    with new_client(args) as client:
        client.wait_until_can_step(timeout=args.boot_timeout)
        prev = client.step(*NEUTRAL)
        total = 0.0
        for delay in delays:
            time.sleep(delay)
            total += delay
            s = client.status()
            expect(s.can_step and s.step_count == prev.step_count, f"waiting changed the step state: {s}")
            r = client.step(*NEUTRAL)
            o, p = r.observation, prev.observation
            expect(r.consumed_tick == p.input_tick, "step after a delay must consume the next tick")
            expect(o.input_tick == r.consumed_tick + 1, "input_tick must be consumed_tick + 1")
            expect(o.host_frame == p.host_frame + 1,
                   f"{delay}s of waiting ran host updates: host_frame {p.host_frame} -> {o.host_frame}")
            expect(o.time_passed == p.time_passed + 1, f"time_passed {p.time_passed} -> {o.time_passed} across one tick")
            expect(o.targets_remaining == p.targets_remaining, "targets changed while parked")
            log(f"  waited {delay:.1f}s: host_frame/input_tick/time_passed each advanced by exactly 1 on the next "
                f"step, targets unchanged; {describe(r)}")
            prev = r
        log(f"  {total:.1f}s of wall-clock waiting advanced the game by exactly {len(delays)} ticks")


def test_errors(args: argparse.Namespace) -> None:
    """Malformed and invalid requests are rejected and never advance the game."""
    with new_client(args) as client:
        s = client.status()
        if s.state == StepState.INACTIVE:
            try:
                client.step(*NEUTRAL)
                raise AssertionError("a step while Inactive must be rejected")
            except NativeStepError as exc:
                expect(exc.error == "not_ready" and exc.native_code == -4, f"unexpected rejection {exc.response}")
            log("  step while Inactive          -> not_ready (-4)")
        else:
            log(f"  (game already {s.state_name}; the Inactive not_ready case was not exercised)")

        client.wait_until_can_step(timeout=args.boot_timeout)
        base = client.step(*NEUTRAL)  # authoritative anchor: the next valid step must consume base.input_tick

        def raw(line: str) -> Callable[[], dict]:
            return lambda: client.raw_request(line)

        def req(**fields: object) -> Callable[[], dict]:
            return lambda: client.raw_request(json.dumps(fields))

        def step(buttons: object, stick_x: object = 0, stick_y: object = 0) -> Callable[[], dict]:
            return req(protocol=1, op="step", buttons=buttons, stick_x=stick_x, stick_y=stick_y)

        cases: List[Tuple[str, Callable[[], dict], str, Optional[int]]] = [
            ("malformed text", raw("this is not json"), "malformed_request", None),
            ("JSON array", raw("[1,2,3]"), "malformed_request", None),
            ("JSON string", raw('"step"'), "malformed_request", None),
            ("unknown op", req(protocol=1, op="dance"), "unknown_op", None),
            ("protocol 2", req(protocol=2, op="status"), "unsupported_protocol", None),
            ("protocol as string", req(protocol="1", op="status"), "unsupported_protocol", None),
            ("missing protocol", req(op="status"), "unsupported_protocol", None),
            ("non-string op", req(protocol=1, op=5), "malformed_request", None),
            ("missing op", req(protocol=1), "malformed_request", None),
            ("step without fields", req(protocol=1, op="step"), "missing_field", None),
            ("null buttons", step(None), "missing_field", None),
            ("missing stick_y", req(protocol=1, op="step", buttons=0, stick_x=0), "missing_field", None),
            ("Start", step(int(Button.START)), "invalid_action", -3),
            ("D-pad up", step(int(Button.DPAD_UP)), "invalid_action", -3),
            ("D-pad right", step(int(Button.DPAD_RIGHT)), "invalid_action", -3),
            ("A+B", step(int(Button.A) | int(Button.B)), "invalid_action", -3),
            ("Z+L", step(int(Button.Z) | int(Button.L)), "invalid_action", -3),
            ("unknown bit 0x0040", step(0x0040), "invalid_action", -3),
            ("unknown bit 0x0080", step(0x0080), "invalid_action", -3),
            ("buttons 0x10000", step(0x10000), "out_of_range", None),
            ("buttons -1", step(-1), "out_of_range", None),
            ("stick_x 128", step(0, 128, 0), "out_of_range", None),
            ("stick_y -129", step(0, 0, -129), "out_of_range", None),
            ("float stick_x 1.5", step(0, 1.5, 0), "malformed_request", None),
            ("float buttons 0.0", step(0.0), "malformed_request", None),
            ("string buttons", step("A"), "malformed_request", None),
            ("bool buttons", step(True), "malformed_request", None),
        ]
        for name, fn, error, native_code in cases:
            response = fn()
            expect(response.get("ok") is False, f"{name}: expected ok=false, got {response}")
            expect(response.get("error") == error, f"{name}: expected {error}, got {response}")
            expect(response.get("native_code") == native_code, f"{name}: expected native_code {native_code}, got {response}")
            suffix = f" ({native_code})" if native_code is not None else ""
            log(f"  {name:28s} -> {error}{suffix}")

        after = client.status()
        expect(after.can_step and after.step_count == base.step_count, f"invalid requests changed the step state: {after}")

        r = client.step(*NEUTRAL)
        expect(r.consumed_tick == base.observation.input_tick, "the next valid step must consume the anchored tick")
        expect(r.observation.host_frame == base.observation.host_frame + 1,
               "invalid requests ran host updates (host_frame advanced by more than the one valid step)")
        log(f"  {len(cases)} rejected requests: step_count still {after.step_count}, next step consumed tick "
            f"{r.consumed_tick} with host_frame +1")
        log(f"  connection still usable: {describe(r)}")


def test_disconnect(args: argparse.Namespace) -> None:
    """Disconnects never corrupt or duplicate native step state."""
    first = new_client(args)
    first.wait_until_can_step(timeout=args.boot_timeout)
    r1 = first.step(*NEUTRAL)
    first.close()  # parked in WaitingForAction
    time.sleep(0.3)

    second = new_client(args)
    s2 = second.status()
    expect(s2.can_step, f"reconnect must find WaitingForAction, got {s2.state_name}")
    expect(s2.step_count == r1.step_count, "step_count changed across a parked disconnect")
    log(f"  disconnect while parked: reconnect sees state={s2.state_name} step_count={s2.step_count} unchanged")

    # Submit a valid action and vanish before reading its result.
    second.send_raw_line(json.dumps({"protocol": 1, "op": "step", "buttons": 0, "stick_x": 0, "stick_y": 0}))
    second.close()
    time.sleep(0.5)

    third = new_client(args)
    s3 = third.status()
    expect(s3.can_step, f"after an orphaned step the game must be parked again, got {s3.state_name}")
    expect(s3.step_count == r1.step_count + 1, f"orphaned step: step_count {s3.step_count}, expected {r1.step_count + 1}")

    r3 = third.step(*NEUTRAL)
    expect(
        r3.consumed_tick == r1.observation.input_tick + 1,
        f"orphaned step: next consumed tick {r3.consumed_tick}, expected {r1.observation.input_tick + 1}",
    )
    expect(r3.observation.host_frame == r1.observation.host_frame + 2,
           f"orphaned step: host_frame {r1.observation.host_frame} -> {r3.observation.host_frame}, expected +2")
    expect(r3.step_count == s3.step_count + 1, "step_count must continue from the status value")
    log(f"  disconnect after submit: exactly one tick ran for the orphaned action (consumed ticks "
        f"{r1.consumed_tick}, [{r1.observation.input_tick} orphaned], {r3.consumed_tick}; host_frame +2)")
    log(f"  stepping resumes normally: {describe(r3)}")
    third.close()


def test_baseline(args: argparse.Namespace) -> None:
    """Feed the frozen baseline rows through the transport with irregular delays."""
    expect(bool(args.btti), "baseline needs --btti <path to mario_743.btti>")
    rows = read_btti_rows(args.btti)
    expect(len(rows) == BASELINE_ROWS, f"expected {BASELINE_ROWS} rows, parsed {len(rows)}")

    with new_client(args) as client:
        s = client.wait_until_can_step(timeout=args.boot_timeout)
        expect(s.step_count == 0, f"baseline needs a fresh episode, step_count is already {s.step_count}")
        started = time.monotonic()
        slept = 0.0
        targets = BASELINE_TARGETS
        final: Optional[StepResult] = None
        for tick, (buttons, stick_x, stick_y) in enumerate(rows):
            delay = BASELINE_DELAYS.get(tick, 0.05 if tick % 37 == 0 else 0.0)
            if delay:
                time.sleep(delay)
                slept += delay
            r = client.step(buttons, stick_x, stick_y)
            expect(r.consumed_tick == tick, f"row {tick} consumed at tick {r.consumed_tick}")
            expect(r.observation.input_tick == tick + 1, f"row {tick}: input_tick {r.observation.input_tick}")
            if tick == 0:
                expect(r.observation.targets_remaining == BASELINE_TARGETS, "stage must start with 10 targets")
            if r.observation.targets_remaining != targets:
                log(f"  tick {tick:3d}: targets {targets} -> {r.observation.targets_remaining} "
                    f"(time_passed={r.observation.time_passed})")
                targets = r.observation.targets_remaining
            if r.observation.btt_active and r.observation.targets_remaining == 0:
                final = r
                break
        elapsed = time.monotonic() - started
        expect(final is not None, "the baseline rows never cleared the stage")
        assert final is not None
        log(f"  completion: {describe(final)} step_count={final.step_count}")
        log(f"  wall clock {elapsed:.1f}s of which {slept:.1f}s deliberate delays")
        expect(final.consumed_tick == BASELINE_INPUT_TICK - 1, f"completion consumed_tick {final.consumed_tick}")
        expect(final.observation.input_tick == BASELINE_INPUT_TICK, f"completion input_tick {final.observation.input_tick}")
        expect(final.observation.time_passed == BASELINE_TIME_PASSED, f"completion time_passed {final.observation.time_passed}")
        expect(final.state == StepState.EPISODE_ENDED, f"final state {final.state_name}")
        expect(final.step_count == BASELINE_INPUT_TICK, f"final step_count {final.step_count}")

        try:
            client.step(*NEUTRAL)
            raise AssertionError("a step after EpisodeEnded must be rejected")
        except NativeStepError as exc:
            expect(exc.error == "episode_ended" and exc.native_code == -6, f"unexpected rejection {exc.response}")
        log("  step after completion         -> episode_ended (-6)")
        s = client.status()
        expect(s.state == StepState.EPISODE_ENDED and not s.can_step, f"status after completion: {s}")
        expect(s.step_count == final.step_count, "status step_count must match the final result")
        log(f"  status: state={s.state_name} can_step={s.can_step} step_count={s.step_count}")

    if args.result_json:
        deadline = time.monotonic() + 5.0
        while not os.path.exists(args.result_json) and time.monotonic() < deadline:
            time.sleep(0.1)
        with open(args.result_json, encoding="utf-8") as fp:
            result = json.load(fp)
        expect(result.get("outcome") == "clear", f"M1a result outcome {result.get('outcome')}")
        expect(result.get("targets_broken") == BASELINE_TARGETS, f"M1a targets_broken {result.get('targets_broken')}")
        expect(result.get("completion_time_passed") == BASELINE_TIME_PASSED, f"M1a completion_time_passed {result}")
        expect(result.get("completion_input_tick") == BASELINE_INPUT_TICK, f"M1a completion_input_tick {result}")
        log(f"  M1a result JSON agrees: targets_broken={result['targets_broken']} "
            f"completion_time_passed={result['completion_time_passed']} "
            f"completion_input_tick={result['completion_input_tick']}")


def test_shutdown(args: argparse.Namespace) -> None:
    """Keep stepping until BattleShip exits (launch it with SSB64_MAX_FRAMES);
    the client must see a clear stopping error or EOF, never a hang."""
    with new_client(args) as client:
        client.wait_until_can_step(timeout=args.boot_timeout)
        deadline = time.monotonic() + args.boot_timeout
        steps = 0
        while True:
            try:
                client.step(*NEUTRAL)
                steps += 1
            except NativeStepError as exc:
                expect(exc.error == "stopping" and exc.native_code == -7, f"unexpected rejection {exc.response}")
                log(f"  step in flight at shutdown after {steps} steps -> stopping (-7)")
                try:
                    client.status()
                    raise AssertionError("expected EOF after the stopping error")
                except ConnectionClosed as eof:
                    log(f"  then EOF: {eof}")
                return
            except ConnectionClosed as eof:
                log(f"  EOF after {steps} steps: {eof}")
                return
            expect(time.monotonic() < deadline, "BattleShip did not exit within the timeout")


TESTS: Dict[str, Callable[[argparse.Namespace], None]] = {
    "single": test_single,
    "delayed": test_delayed,
    "errors": test_errors,
    "disconnect": test_disconnect,
    "baseline": test_baseline,
    "shutdown": test_shutdown,
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tests", nargs="+", choices=sorted(TESTS), help="tests to run, in order")
    parser.add_argument("--port", type=int, required=True, help="SSB64_RL_PORT of the running BattleShip")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--timeout", type=float, default=30.0, help="socket timeout per request, seconds")
    parser.add_argument("--connect-timeout", type=float, default=60.0, help="retry a refused connection this long")
    parser.add_argument("--boot-timeout", type=float, default=180.0, help="max wait for BTT activation / exit")
    parser.add_argument("--btti", help="baseline: path to tas_input_2/mario_743.btti")
    parser.add_argument("--result-json", help="baseline: SSB64_RL_RESULT_PATH of the running game, to cross-check")
    args = parser.parse_args(argv)

    failures = 0
    for name in args.tests:
        log(f"[{name}]")
        started = time.monotonic()
        try:
            TESTS[name](args)
        except Exception as exc:  # noqa: BLE001 - report every failure kind
            failures += 1
            log(f"FAIL {name} ({time.monotonic() - started:.1f}s): {exc}")
            traceback.print_exc()
        else:
            log(f"PASS {name} ({time.monotonic() - started:.1f}s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
