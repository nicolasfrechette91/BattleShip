#!/usr/bin/env python3
"""M3 smoke validation of rl/battleship_env.py (the Gymnasium wrapper itself).

Nothing here learns. Each case proves one property of the wrapper on top of
the frozen M1c / M1d / M2 stack, using the real BattleShip executable
(build-us/Release/BattleShip.exe by default) wherever a process is needed.

    python rl/m3_gym_smoke.py                       # every case, in order
    python rl/m3_gym_smoke.py construct action_mapping   # no game needed

Cases:
  construct         spaces exist, sampling is legal, no process is launched, close() before reset is safe
  action_mapping    exact Gym <-> native conversion over every Gym button and every stick value in -80..80;
                    C-down / C-right and stick values outside -80..80 are unrepresentable (rejected, never
                    clamped) before anything is sent; illegal native words stay unrepresentable
  reset_tick_zero   reset() returns the pre-tick-0 observation (input_tick 0, step_count 0) without
                    consuming tick 0; `observe` is non-consuming; the first step consumes exactly tick 0
  raw_actions       every Gym button (none, A, B, Z, L, R, C-up, C-left) and the analog boundaries
                    (-80,-80) (-79,0) (0,0) (79,0) (80,80) plus intermediates reach the wire exactly;
                    then, bypassing the wrapper, the raw client shows the native layer still accepts
                    C-down, C-right and full int8 sticks
  random_agent      bounded action_space.sample() episode: legal, in-space observations, truncated at the
                    Python limit, process disposed
  reset_partial     reset, a few steps, reset again: new process, step_count 0, no inherited progress
  replay_complete   the 7.43 s baseline through the wrapper: 447 actions, 446/447, terminated, exit 0,
                    result JSON; then reset gives a fresh process again
  env_checker       gymnasium.utils.env_checker.check_env, warnings reported verbatim
  close_paths       close() before reset, mid-episode, after a failed reset, after a failed step, twice

Every case ends by checking that no BattleShip process owned by the test is
alive and that the machine-wide BattleShip.exe count is back to what it was
before the case. Exit status: 0 all requested cases passed, 1 otherwise,
2 bad usage.
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
import traceback
import warnings
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402

from battleship_client import Button, StepState  # noqa: E402
from battleship_env import (  # noqa: E402
    BUTTON_INDEX,
    BUTTON_NAMES,
    BUTTON_TABLE,
    DEFAULT_EXECUTABLE,
    ENV_CONTRACT,
    PLACEHOLDER_REWARD,
    STICK_MAX,
    STICK_MIN,
    STICK_STATES,
    BattleShipBTTEnv,
    BattleShipEnvError,
    action_to_native,
    make_action_space,
    make_observation_space,
    native_to_action,
)
from battleship_process import EpisodeFailure, EpisodeOutcome, LaunchConfig  # noqa: E402
from btti_replay import read_btti_rows  # noqa: E402
from m1e_replay_regression import (  # noqa: E402
    COMPLETION_CONSUMED_TICK,
    COMPLETION_INPUT_TICK,
    COMPLETION_STEPS,
    COMPLETION_TIME_PASSED,
    DEFAULT_REPLAY,
    MAX_TARGETS,
    SOURCE_ROWS,
    check_completion,
    check_step,
)
from m2_restart_regression import EXPECTED_RESULT  # noqa: E402

NEUTRAL = {"button": 0, "stick_x": 0, "stick_y": 0}


def log(message: str) -> None:
    print(message, flush=True)


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


# -- process accounting ----------------------------------------------------------------


def count_battleship_processes(executable: Path) -> Optional[int]:
    """Machine-wide count of running processes with the executable's name; None if unknown."""
    name = executable.name
    try:
        if platform.system() == "Windows":
            out = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=15, check=False,
            ).stdout
            return sum(1 for line in out.splitlines() if line.startswith(f'"{name}"'))
        out = subprocess.run(["pgrep", "-c", "-x", name], capture_output=True, text=True, timeout=15, check=False).stdout
        return int(out.strip() or 0)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def check_no_leak(env: BattleShipBTTEnv, before: Optional[int], executable: Path) -> None:
    expect(not env.owned_process_alive, "the environment still owns a live process")
    expect(env.episode is None or not env.episode.alive, "the owned episode is still alive")
    after = count_battleship_processes(executable)
    if before is not None and after is not None:
        # The count may drop below the baseline if an unrelated process ended
        # meanwhile; it must never rise.
        expect(after <= before, f"BattleShip process count rose from {before} to {after}: a process leaked")
    log(f"  cleanup ok: owned process gone, {executable.name} count {before} -> {after}")


# -- wire recording ----------------------------------------------------------------------


class WireRecorder:
    """Wraps BattleShipClient.send_raw_line on one instance and keeps every request line."""

    def __init__(self, client: Any):
        self.lines: List[str] = []
        self._original = client.send_raw_line

        def record(line: str) -> None:
            self.lines.append(line)
            self._original(line)

        client.send_raw_line = record

    def steps(self) -> List[Dict[str, Any]]:
        return [json.loads(line) for line in self.lines if json.loads(line).get("op") == "step"]


# -- cases ---------------------------------------------------------------------------


def make_env(args: argparse.Namespace, **overrides: Any) -> BattleShipBTTEnv:
    fields: Dict[str, Any] = dict(
        executable=Path(args.exe),
        run_root=args.run_root,
        startup_timeout=args.startup_timeout,
        ready_timeout=args.ready_timeout,
        request_timeout=args.request_timeout,
        exit_timeout=args.exit_timeout,
    )
    max_steps = overrides.pop("max_episode_steps", None)
    fields.update(overrides)
    return BattleShipBTTEnv(LaunchConfig(**fields), max_episode_steps=max_steps)


def case_construct(args: argparse.Namespace) -> None:
    before = count_battleship_processes(Path(args.exe))
    env = BattleShipBTTEnv(executable=Path(args.exe))
    expect(env.action_space is not None and env.observation_space is not None, "spaces missing")
    expect(env.episode is None and not env.owned_process_alive, "construction launched a process")
    expect(env.phase == "idle", f"phase {env.phase}, expected idle")
    expect(set(env.action_space.spaces) == {"button", "stick_x", "stick_y"}, "action space keys")
    expect(len(env.observation_space.spaces) == 17, f"{len(env.observation_space.spaces)} observation fields, expected 17")

    expect(env.action_space["button"].n == 8 and len(BUTTON_TABLE) == 8, "button domain must have exactly 8 states")
    expect(env.action_space["stick_x"].n == 161 and env.action_space["stick_x"].start == -80, "stick_x must be Discrete(161, start=-80)")
    expect(env.action_space["stick_y"].n == 161 and env.action_space["stick_y"].start == -80, "stick_y must be Discrete(161, start=-80)")
    expect(ENV_CONTRACT == "btt_raw_b8_s161_v1", f"contract id {ENV_CONTRACT}")

    env.action_space.seed(1234)
    seen_buttons, seen_x, seen_y = set(), set(), set()
    for _ in range(20000):
        action = env.action_space.sample()
        expect(env.action_space.contains(action), f"sampled action outside its own space: {action}")
        native = action_to_native(action)  # raises if illegal
        # Explicit domain checks: no sampled action may rely on native clipping.
        expect(native.buttons in BUTTON_INDEX, f"sample produced a button word outside the Gym domain 0x{native.buttons:04X}")
        expect(native.buttons not in (int(Button.C_DOWN), int(Button.C_RIGHT)), "sample produced C-down / C-right")
        expect(-80 <= native.stick_x <= 80 and -80 <= native.stick_y <= 80, f"sample outside -80..80: {native}")
        seen_buttons.add(native.buttons)
        seen_x.add(native.stick_x)
        seen_y.add(native.stick_y)
    expect(seen_buttons == set(BUTTON_INDEX), f"sampling missed buttons: {sorted(set(BUTTON_INDEX) - seen_buttons)}")
    expect(seen_x == set(range(STICK_MIN, STICK_MAX + 1)), f"sampling missed {STICK_STATES - len(seen_x)} stick_x values")
    expect(seen_y == set(range(STICK_MIN, STICK_MAX + 1)), f"sampling missed {STICK_STATES - len(seen_y)} stick_y values")
    log(f"  20000 samples: all inside the Gym domain; every button ({len(seen_buttons)}) and every value in "
        f"{STICK_MIN}..{STICK_MAX} on both axes sampled; sampled stick min/max x=({min(seen_x)},{max(seen_x)}) "
        f"y=({min(seen_y)},{max(seen_y)})")

    # Observation conversion: a wire-shaped Observation becomes exact-dtype
    # 0-d arrays that the space contains without any casting warning.
    from battleship_client import Observation
    from battleship_env import observation_to_gym

    synthetic = Observation(1, 511, 447, 446, 1, 1, 0, 1, 12.5, -2550.0, -0.25, 3.0, 1.75, -1, 1, 42, 2)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        converted = observation_to_gym(synthetic)
        expect(env.observation_space.contains(converted), "converted observation not contained")
    expect(all(isinstance(v, np.ndarray) and v.shape == () for k, v in converted.items() if k not in ("btt_active", "fighter_valid")),
           "Box fields must convert to 0-d arrays")
    expect(all(type(converted[k]) is int for k in ("btt_active", "fighter_valid")), "flag fields must convert to plain ints")
    expect(float(converted["position_y"]) == -2550.0 and int(converted["facing_direction"]) == -1
           and int(converted["input_tick"]) == 447 and converted["fighter_valid"] == 1, "conversion changed a value")
    log(f"  observation_space fields ({len(converted)}): {', '.join(env.observation_space.spaces)}")

    try:
        env.step(NEUTRAL)
    except BattleShipEnvError as exc:
        log(f"  step() before reset refused: {exc}")
    else:
        raise AssertionError("step() before reset must raise")

    env.close()
    env.close()
    expect(env.phase == "closed", "close() did not close")
    check_no_leak(env, before, Path(args.exe))


def case_action_mapping(args: argparse.Namespace) -> None:
    space = make_action_space()

    # The button mapping is explicit and stable: index -> name -> native word.
    expected_table = [
        (0, "none", Button.NONE), (1, "A", Button.A), (2, "B", Button.B), (3, "Z", Button.Z),
        (4, "L", Button.L), (5, "R", Button.R), (6, "C-up", Button.C_UP), (7, "C-left", Button.C_LEFT),
    ]
    actual_table = [(i, BUTTON_NAMES[i], BUTTON_TABLE[i]) for i in range(len(BUTTON_TABLE))]
    expect(actual_table == expected_table, f"button table changed: {actual_table}")
    expect(space["button"].n == 8 and not space["button"].contains(8) and not space["button"].contains(9),
           "button space must have exactly the 8 declared indices")
    for word in (Button.C_DOWN, Button.C_RIGHT):
        expect(int(word) not in BUTTON_INDEX, f"{word.name} must be absent from the Gym button domain")
    log("  button mapping: " + ", ".join(f"{i}={name}(0x{int(b):04X})" for i, name, b in expected_table)
        + "; C-down and C-right absent")

    # Every Gym button with every stick value in -80..80 on each axis, round-tripped exactly.
    count = 0
    for button in BUTTON_TABLE:
        for value in range(STICK_MIN, STICK_MAX + 1):
            for stick_x, stick_y in ((value, -value), (STICK_MIN if value % 2 else STICK_MAX, value)):
                action = native_to_action(int(button), stick_x, stick_y)
                expect(space.contains(action), f"{action} not in action space")
                native = action_to_native(action)
                expect(
                    (native.buttons, native.stick_x, native.stick_y) == (int(button), stick_x, stick_y),
                    f"round trip changed {(int(button), stick_x, stick_y)} -> {native}",
                )
                count += 1
    log(f"  {count} native triples ({len(BUTTON_TABLE)} buttons x {STICK_STATES} values x 2) round-tripped exactly")

    # Analog boundaries: exact pass-through, no clamping anywhere inside the domain.
    for value in (-80, -79, 0, 79, 80):
        native = action_to_native({"button": 0, "stick_x": value, "stick_y": -value})
        expect((native.stick_x, native.stick_y) == (value, -value), f"boundary {value} changed to {native}")
    log("  boundaries -80, -79, 0, 79, 80 pass through unchanged")

    representative = [
        ("none", Button.NONE, (0, 0)),
        ("A", Button.A, (-80, -80)),
        ("B", Button.B, (-79, 0)),
        ("Z", Button.Z, (79, 0)),
        ("L", Button.L, (80, 80)),
        ("R", Button.R, (-1, 1)),
        ("C-up", Button.C_UP, (37, -61)),
        ("C-left", Button.C_LEFT, (80, -80)),
    ]
    for name, button, (x, y) in representative:
        native = action_to_native({"button": BUTTON_INDEX[int(button)], "stick_x": x, "stick_y": y})
        expect(native == native.__class__(int(button), x, y), f"{name} conversion wrong: {native}")
        # numpy scalars and 0-d arrays, as action_space.sample() yields them, must convert identically
        np_action = {"button": np.int64(BUTTON_INDEX[int(button)]), "stick_x": np.array(x), "stick_y": np.int8(y)}
        expect(action_to_native(np_action) == native, f"{name}: numpy-typed action converted differently")
    log("  representative actions " + ", ".join(f"{n}({x},{y})" for n, _, (x, y) in representative) + " exact")

    # Native words the Gym domain cannot represent: illegal ones as before,
    # plus C-down / C-right, which stay legal at the M1c / M1d layer only.
    rejected_native = [Button.START, Button.DPAD_UP, Button.DPAD_DOWN, Button.DPAD_LEFT, Button.DPAD_RIGHT,
                       Button.A | Button.B, Button.C_UP | Button.C_RIGHT, 0x00C0, 0x0040, 0xFFFF,
                       Button.C_DOWN, Button.C_RIGHT]
    for word in rejected_native:
        try:
            native_to_action(int(word), 0, 0)
        except ValueError:
            continue
        raise AssertionError(f"button word 0x{int(word):04X} must be unrepresentable")
    # Natively legal stick values outside the Gym domain are rejected, not clamped.
    for value in (-81, 81, -128, 127):
        for key in ("stick_x", "stick_y"):
            try:
                native_to_action(0, value if key == "stick_x" else 0, value if key == "stick_y" else 0)
            except ValueError:
                continue
            raise AssertionError(f"{key}={value} must be unrepresentable")

    # (action, whether Gymnasium's own space.contains is expected to reject it too)
    rejected_gym = [
        ({"button": 8, "stick_x": 0, "stick_y": 0}, True),       # would be C-down in the old table
        ({"button": 9, "stick_x": 0, "stick_y": 0}, True),       # would be C-right in the old table
        ({"button": -1, "stick_x": 0, "stick_y": 0}, True),
        ({"button": 0, "stick_x": 81, "stick_y": 0}, True),
        ({"button": 0, "stick_x": -81, "stick_y": 0}, True),
        ({"button": 0, "stick_x": 0, "stick_y": 81}, True),
        ({"button": 0, "stick_x": 0, "stick_y": -81}, True),
        ({"button": 0, "stick_x": 127, "stick_y": 0}, True),
        ({"button": 0, "stick_x": 0, "stick_y": -128}, True),
        ({"button": 0, "stick_x": 0.0, "stick_y": 0}, True),
        ({"button": True, "stick_x": 0, "stick_y": 0}, False),   # bool is an int subclass for Discrete.contains
        ({"button": 0, "stick_x": 0}, True),
        ({"buttons": 0, "stick_x": 0, "stick_y": 0}, True),
        ([0, 0, 0], True),
    ]
    for action, space_rejects in rejected_gym:
        # The converter is the gate that runs before anything reaches the wire.
        try:
            action_to_native(action)  # type: ignore[arg-type]
        except ValueError:
            pass
        else:
            raise AssertionError(f"action {action!r} must be rejected")
        if space_rejects:
            expect(not space.contains(action), f"action_space accepted {action}")
    log(f"  {len(rejected_native)} native words unrepresentable (C-down, C-right included); stick -81/81/-128/127 "
        f"rejected on both axes; {len(rejected_gym)} malformed or out-of-domain Gym actions rejected, never clamped")


def case_reset_tick_zero(args: argparse.Namespace) -> None:
    before = count_battleship_processes(Path(args.exe))
    env = make_env(args)
    try:
        started = time.monotonic()
        observation, info = env.reset()
        boot_s = time.monotonic() - started
        expect(env.observation_space.contains(observation), "initial observation outside observation_space")
        expect(info["step_count"] == 0, f"reset step_count {info['step_count']}, expected 0")
        expect(info["state_name"] == "WaitingForAction", f"reset state {info['state_name']}")
        expect(info["consumed_tick"] is None, "reset must not report a consumed tick")
        expect(int(observation["input_tick"]) == 0, f"initial input_tick {int(observation['input_tick'])}, expected 0")
        expect(int(observation["time_passed"]) == 0, f"initial time_passed {int(observation['time_passed'])}, expected 0")
        expect(int(observation["btt_active"]) == 1 and int(observation["fighter_valid"]) == 1, "initial validity flags not set")
        expect(int(observation["targets_remaining"]) == MAX_TARGETS, f"initial targets {int(observation['targets_remaining'])}")
        expect(env.owned_process_alive, "no live process after reset")
        log(f"  reset: pid={info['pid']} port={info['port']} fresh after {boot_s:.1f} s; "
            f"step_count=0 input_tick=0 time_passed=0 targets={int(observation['targets_remaining'])} "
            f"game_status={int(observation['game_status'])} position=({float(observation['position_x']):.3f}, "
            f"{float(observation['position_y']):.3f})")

        # `observe` is non-consuming: repeated calls return the same snapshot and no tick moves.
        assert env.episode is not None and env.episode.client is not None
        client = env.episode.client
        first = client.observe()
        time.sleep(0.5)
        second = client.observe()
        status = client.status()
        expect(first.observation == second.observation, "two observe calls returned different snapshots")
        expect(first.observation == info["native_observation"], "observe disagrees with the reset observation")
        expect(second.step_count == 0 and status.step_count == 0 and status.can_step, "observe consumed something")
        expect(second.observation.input_tick == 0, "observe advanced input_tick")
        log("  observe x3 (0.5 s apart): identical snapshots, step_count 0, input_tick 0, can_step true")

        observation, reward, terminated, truncated, info = env.step(NEUTRAL)
        expect(info["consumed_tick"] == 0, f"first step consumed_tick {info['consumed_tick']}, expected 0")
        expect(int(observation["input_tick"]) == 1, f"first step input_tick {int(observation['input_tick'])}, expected 1")
        expect(info["step_count"] == 1, f"first step step_count {info['step_count']}, expected 1")
        expect(isinstance(reward, float) and reward == PLACEHOLDER_REWARD == 0.0, f"reward {reward!r}")
        expect(terminated is False and truncated is False, f"terminated={terminated} truncated={truncated}")
        expect(env.observation_space.contains(observation), "step observation outside observation_space")
        expect(info["state_name"] == "WaitingForAction", f"state after step {info['state_name']}")
        log(f"  first step: consumed_tick=0 observation.input_tick=1 step_count=1 reward=0.0 "
            f"terminated=False truncated=False time_passed={int(observation['time_passed'])}")

        observation, reward, terminated, truncated, info = env.step(NEUTRAL)
        expect(info["consumed_tick"] == 1 and int(observation["input_tick"]) == 2 and info["step_count"] == 2, "second step pairing")
        log("  second step: consumed_tick=1 input_tick=2 step_count=2")
    finally:
        env.close()
    expect(env.phase == "closed", "not closed")
    check_no_leak(env, before, Path(args.exe))


def case_raw_actions(args: argparse.Namespace) -> None:
    before = count_battleship_processes(Path(args.exe))
    plan: List[Tuple[str, Button, int, int]] = [
        ("none", Button.NONE, 0, 0),
        ("A", Button.A, -80, -80),
        ("B", Button.B, -79, 0),
        ("Z", Button.Z, 79, 0),
        ("L", Button.L, 80, 80),
        ("R", Button.R, -1, 1),
        ("C-up", Button.C_UP, 37, -61),
        ("C-left", Button.C_LEFT, 80, -80),
        ("none", Button.NONE, 0, 79),
        ("A", Button.A, 0, -79),
    ]
    env = make_env(args)
    try:
        observation, info = env.reset()
        assert env.episode is not None and env.episode.client is not None
        client = env.episode.client
        recorder = WireRecorder(client)
        for index, (name, button, x, y) in enumerate(plan):
            action = {"button": BUTTON_INDEX[int(button)], "stick_x": x, "stick_y": y}
            expect(env.action_space.contains(action), f"{name} action not in space")
            observation, reward, terminated, truncated, info = env.step(action)
            expect(info["consumed_tick"] == index, f"{name}: consumed_tick {info['consumed_tick']}, expected {index}")
            expect(int(observation["input_tick"]) == index + 1, f"{name}: input_tick {int(observation['input_tick'])}")
            expect(env.observation_space.contains(observation), f"{name}: observation outside space")
            expect(not terminated and not truncated and reward == 0.0, f"{name}: unexpected outcome")
            native = info["native_action"]
            expect((native.buttons, native.stick_x, native.stick_y) == (int(button), x, y), f"{name}: native {native}")
        sent = recorder.steps()
        expect(len(sent) == len(plan), f"{len(sent)} step requests on the wire, expected {len(plan)}")
        for (name, button, x, y), request in zip(plan, sent):
            expect(
                (request["buttons"], request["stick_x"], request["stick_y"]) == (int(button), x, y)
                and request["protocol"] == 1
                and all(isinstance(request[k], int) and not isinstance(request[k], bool) for k in ("buttons", "stick_x", "stick_y")),
                f"{name}: wire request {request} does not carry the exact values",
            )
        log("  " + "; ".join(f"{name}=0x{int(b):04X}({x},{y})" for name, b, x, y in plan))
        log(f"  {len(plan)} steps: consumed ticks 0..{len(plan) - 1}; every wire request carried the exact integers")

        # Boundary demonstration, bypassing the wrapper on purpose: the native
        # M1c / M1d contract underneath is unchanged and still accepts what
        # the Gym domain leaves out. The wrapper's own step counter is not
        # used after this; the environment is closed right below.
        below = [("C-down", int(Button.C_DOWN), 0, 0), ("C-right", int(Button.C_RIGHT), 0, 0),
                 ("none", int(Button.NONE), -128, 127), ("none", int(Button.NONE), 127, -128)]
        next_tick = len(plan)
        for name, word, x, y in below:
            result = client.step(word, x, y)
            expect(result.consumed_tick == next_tick, f"raw {name}({x},{y}): consumed_tick {result.consumed_tick}")
            expect(result.state == StepState.WAITING_FOR_ACTION, f"raw {name}: state {result.state_name}")
            next_tick += 1
        log(f"  raw client (below the wrapper): C-down, C-right and sticks (-128,127) / (127,-128) still accepted "
            f"natively, consumed ticks {len(plan)}..{next_tick - 1}")
    finally:
        env.close()
    check_no_leak(env, before, Path(args.exe))


def case_random_agent(args: argparse.Namespace) -> None:
    before = count_battleship_processes(Path(args.exe))
    limit = args.random_steps
    env = make_env(args, max_episode_steps=limit)
    env.action_space.seed(args.seed)
    try:
        observation, info = env.reset(seed=args.seed)
        expect(env.observation_space.contains(observation), "initial observation outside space")
        pid = info["pid"]
        steps = 0
        terminated = truncated = False
        buttons_used: Dict[str, int] = {}
        min_targets = int(observation["targets_remaining"])
        stick_lo, stick_hi = 0, 0
        started = time.monotonic()
        while not (terminated or truncated):
            action = env.action_space.sample()
            expect(env.action_space.contains(action), f"sample outside space: {action}")
            native = action_to_native(action)
            expect(native.buttons in BUTTON_INDEX and -80 <= native.stick_x <= 80 and -80 <= native.stick_y <= 80,
                   f"sample outside the Gym domain: {native}")
            stick_lo = min(stick_lo, native.stick_x, native.stick_y)
            stick_hi = max(stick_hi, native.stick_x, native.stick_y)
            buttons_used[BUTTON_NAMES[BUTTON_INDEX[native.buttons]]] = buttons_used.get(BUTTON_NAMES[BUTTON_INDEX[native.buttons]], 0) + 1
            observation, reward, terminated, truncated, info = env.step(action)
            expect(env.observation_space.contains(observation), f"step {steps}: observation outside space")
            expect(info["consumed_tick"] == steps, f"step {steps}: consumed_tick {info['consumed_tick']}")
            expect(int(observation["input_tick"]) == steps + 1, f"step {steps}: input_tick")
            expect(reward == 0.0, f"step {steps}: reward {reward!r}")
            steps += 1
            min_targets = min(min_targets, int(observation["targets_remaining"]))
            expect(steps <= limit, "stepped past the Python limit")
        wall = time.monotonic() - started
        if terminated:
            # A random agent clearing the stage within the bound would be a
            # native completion, which is not what this case tests.
            raise AssertionError(f"random agent natively completed the stage after {steps} steps; raise --random-steps? "
                                 "(not a wrapper failure, but the case cannot classify it as truncation)")
        expect(truncated and not terminated, f"expected truncated at the limit, got terminated={terminated} truncated={truncated}")
        expect(steps == limit and info["step_count"] == limit, f"steps {steps} / step_count {info['step_count']}, expected {limit}")
        expect(info["truncation_reason"] == "max_episode_steps", f"truncation_reason {info.get('truncation_reason')}")
        expect(info["cleanup_action"] == "terminated", f"cleanup_action {info['cleanup_action']}, expected terminated")
        expect(env.phase == "truncated" and not env.owned_process_alive, "truncated episode still owns a live process")
        log(f"  pid={pid}: {steps} sampled steps in {wall:.1f} s ({1000 * wall / steps:.0f} ms/step), consumed ticks 0..{steps - 1}, "
            f"truncated=True terminated=False, process terminated at the limit")
        log(f"  buttons sampled: {dict(sorted(buttons_used.items()))}; sampled stick values within [{stick_lo}, {stick_hi}]; "
            f"targets_remaining min {min_targets}; final time_passed={int(observation['time_passed'])} "
            f"input_tick={int(observation['input_tick'])}")
        try:
            env.step(NEUTRAL)
        except BattleShipEnvError as exc:
            log(f"  step() after truncation refused: {exc}")
        else:
            raise AssertionError("step() after truncation must raise")
    finally:
        env.close()
    check_no_leak(env, before, Path(args.exe))


def case_reset_partial(args: argparse.Namespace) -> None:
    before = count_battleship_processes(Path(args.exe))
    env = make_env(args)
    try:
        observation, info = env.reset()
        pid_1, dir_1 = info["pid"], info["episode_dir"]
        episode_1 = env.episode
        for tick in range(5):
            observation, reward, terminated, truncated, info = env.step({"button": BUTTON_INDEX[int(Button.A)], "stick_x": 80, "stick_y": 0})
            expect(info["consumed_tick"] == tick, f"consumed_tick {info['consumed_tick']}")
        progressed = (int(observation["input_tick"]), int(observation["time_passed"]), info["step_count"])
        expect(progressed == (5, 4, 5) or progressed[0] == 5 and progressed[2] == 5, f"unexpected progress {progressed}")
        log(f"  process 1 pid={pid_1}: 5 steps, input_tick={progressed[0]} time_passed={progressed[1]} step_count={progressed[2]}")

        observation, info = env.reset()
        pid_2, dir_2 = info["pid"], info["episode_dir"]
        expect(episode_1 is not None and not episode_1.alive, "process 1 still alive after reset")
        expect(episode_1.cleanup_action == "terminated", f"process 1 cleanup {episode_1.cleanup_action}, expected terminated")
        expect(pid_2 != pid_1 and dir_2 != dir_1, "reset reused the process or the episode directory")
        expect(info["step_count"] == 0 and int(observation["input_tick"]) == 0 and int(observation["time_passed"]) == 0,
               f"process 2 not fresh: step_count={info['step_count']} input_tick={int(observation['input_tick'])} "
               f"time_passed={int(observation['time_passed'])}")
        expect(int(observation["targets_remaining"]) == MAX_TARGETS, "process 2 inherited target progress")
        expect(env.observation_space.contains(observation), "process 2 observation outside space")
        observation, reward, terminated, truncated, info = env.step(NEUTRAL)
        expect(info["consumed_tick"] == 0 and int(observation["input_tick"]) == 1, "process 2 first step did not consume tick 0")
        log(f"  process 2 pid={pid_2}: fresh step_count=0 input_tick=0 time_passed=0 targets={MAX_TARGETS}; "
            f"first step consumed tick 0; process 1 {episode_1.cleanup_action}")
    finally:
        env.close()
    check_no_leak(env, before, Path(args.exe))


def case_replay_complete(args: argparse.Namespace) -> None:
    before = count_battleship_processes(Path(args.exe))
    rows = read_btti_rows(args.replay)
    expect(len(rows) == SOURCE_ROWS, f"{len(rows)} replay rows, expected {SOURCE_ROWS}")
    # The Gym domain is a subset of the native one, so representability of
    # this replay is checked, not assumed. Nothing is substituted or clamped:
    # a row outside the domain fails here, before any process is launched.
    c_down = sum(1 for r in rows if r.buttons & int(Button.C_DOWN))
    c_right = sum(1 for r in rows if r.buttons & int(Button.C_RIGHT))
    beyond = sum(1 for r in rows if abs(r.stick_x) > 80 or abs(r.stick_y) > 80)
    for row_index, row in enumerate(rows):
        try:
            native_to_action(row.buttons, row.stick_x, row.stick_y)
        except ValueError as exc:
            raise AssertionError(f"replay row {row_index} is outside the Gym domain: {exc}") from exc
    log(f"  replay representable in the Gym domain: {len(rows)} rows, C-down rows={c_down}, C-right rows={c_right}, "
        f"rows with |stick| > 80: {beyond}")
    env = make_env(args)
    try:
        observation, info = env.reset()
        pid_1 = info["pid"]
        previous = None
        sent = 0
        terminated = truncated = False
        started = time.monotonic()
        for row_index, row in enumerate(rows):
            action = native_to_action(row.buttons, row.stick_x, row.stick_y)
            observation, reward, terminated, truncated, info = env.step(action)
            sent += 1
            result = env.last_step_result
            assert result is not None
            check_step(row_index, result, previous)  # M1e per-step invariants, unchanged
            expect(env.observation_space.contains(observation), f"row {row_index}: observation outside space")
            expect(reward == 0.0, f"row {row_index}: reward {reward!r}")
            expect(truncated is False, f"row {row_index}: truncated")
            previous = result.observation
            if terminated:
                check_completion(row_index, result)  # frozen 446 / 447 completion
                break
        wall = time.monotonic() - started
        expect(terminated, f"all {len(rows)} rows sent without native completion")
        expect(sent == COMPLETION_STEPS and info["step_count"] == COMPLETION_STEPS, f"steps {sent} / step_count {info['step_count']}")
        expect(info["consumed_tick"] == COMPLETION_CONSUMED_TICK, f"last consumed_tick {info['consumed_tick']}")
        expect(int(observation["input_tick"]) == COMPLETION_INPUT_TICK, f"completion input_tick {int(observation['input_tick'])}")
        expect(int(observation["time_passed"]) == COMPLETION_TIME_PASSED, f"completion time_passed {int(observation['time_passed'])}")
        expect(int(observation["targets_remaining"]) == 0, "targets remain at completion")
        expect(info["state_name"] == "EpisodeEnded", f"terminal state {info['state_name']}")
        expect(info["exit_code"] == 0, f"exit code {info['exit_code']}, expected 0")
        for key, value in EXPECTED_RESULT.items():
            expect(info["result"].get(key) == value, f"result JSON {key} is {info['result'].get(key)!r}, expected {value!r}")
        expect(info["cleanup_action"] == "already_exited", f"cleanup after completion {info['cleanup_action']}")
        expect(env.phase == "terminated" and not env.owned_process_alive, "terminated episode still owns a live process")
        log(f"  pid={pid_1}: actions_consumed={sent} last_consumed_tick={info['consumed_tick']} "
            f"completion_time_passed={int(observation['time_passed'])} completion_input_tick={int(observation['input_tick'])} "
            f"final_step_count={info['step_count']} targets_remaining={int(observation['targets_remaining'])} "
            f"terminated={terminated} truncated={truncated} exit_code={info['exit_code']} "
            f"rows_unsent={len(rows) - sent} wall={wall:.1f}s")
        log(f"  result JSON: {json.dumps({k: info['result'][k] for k in EXPECTED_RESULT})} host_frames={info['result']['host_frames']}")

        observation, info = env.reset()
        expect(info["pid"] != pid_1, "reset after completion reused the process")
        expect(info["step_count"] == 0 and int(observation["input_tick"]) == 0, "reset after completion is not fresh")
        expect(int(observation["targets_remaining"]) == MAX_TARGETS, "reset after completion inherited target progress")
        log(f"  reset after completion: new pid={info['pid']} step_count=0 input_tick=0 targets={MAX_TARGETS}")
    finally:
        env.close()
    check_no_leak(env, before, Path(args.exe))


INFO_IDENTITY_ASSERTION = "Deterministic step info are not equivalent for the same seed and action"


def case_env_checker(args: argparse.Namespace) -> None:
    """gymnasium.utils.env_checker.check_env, then the one check it cannot pass
    for a process-backed environment, repeated with the process identity
    stripped from info."""
    from gymnasium.utils.env_checker import check_env, data_equivalence

    from battleship_env import PROCESS_IDENTITY_INFO_KEYS

    before = count_battleship_processes(Path(args.exe))
    env = make_env(args)
    outcome = "passed"
    started = time.monotonic()
    with warnings.catch_warnings(record=True) as records:
        warnings.simplefilter("always")
        try:
            check_env(env)
        except AssertionError as exc:
            # The only accepted failure: two seeded resets are two OS
            # processes, so pid / port / episode_dir / episode_index in info
            # differ by construction. Anything else is a real violation.
            expect(str(exc) == INFO_IDENTITY_ASSERTION, f"check_env raised an unexpected assertion: {exc}")
            outcome = f"stopped at the documented process-identity assertion: {exc}"
        finally:
            env.close()
    caught = [str(record.message) for record in records]
    log(f"  check_env {outcome} after {time.monotonic() - started:.1f} s; {len(caught)} warning(s):")
    for message in caught:
        log(f"    WARN: {message}")
    check_no_leak(env, before, Path(args.exe))

    # check_step_determinism again, by hand, with the process identity removed.
    env = make_env(args)
    try:
        env.action_space.seed(123)
        action = env.action_space.sample()
        env.reset(seed=123)
        obs_0, rew_0, term_0, trunc_0, info_0 = env.step(action)
        env.reset(seed=123)
        obs_1, rew_1, term_1, trunc_1, info_1 = env.step(action)
    finally:
        env.close()
    expect(data_equivalence(obs_0, obs_1, exact=True), "step observations differ between two fresh processes")
    expect(rew_0 == rew_1 == 0.0 and term_0 == term_1 is False and trunc_0 is trunc_1 is False, "step outcome differs")
    differing = sorted(k for k in info_0 if not data_equivalence(info_0[k], info_1[k], exact=True))
    expect(set(differing) <= set(PROCESS_IDENTITY_INFO_KEYS), f"non-identity info keys differ: {differing}")
    stripped_0 = {k: v for k, v in info_0.items() if k not in PROCESS_IDENTITY_INFO_KEYS}
    stripped_1 = {k: v for k, v in info_1.items() if k not in PROCESS_IDENTITY_INFO_KEYS}
    expect(data_equivalence(stripped_0, stripped_1, exact=True), "info differs beyond the process identity")
    log(f"  by hand: same seeded action {action_to_native(action)} on two fresh processes gave exactly equal observations "
        f"(host_frame {int(obs_0['host_frame'])}), reward, terminated, truncated; info differed only in {differing}")
    check_no_leak(env, before, Path(args.exe))


def case_close_paths(args: argparse.Namespace) -> None:
    before = count_battleship_processes(Path(args.exe))

    # close() before reset, twice.
    env = make_env(args)
    env.close()
    env.close()
    try:
        env.reset()
    except BattleShipEnvError as exc:
        log(f"  before reset: close() x2 fine; reset() after close refused: {exc}")
    else:
        raise AssertionError("reset() after close() must raise")

    # close() during an active episode, twice.
    env = make_env(args)
    observation, info = env.reset()
    for _ in range(3):
        env.step(NEUTRAL)
    episode = env.episode
    assert episode is not None
    env.close()
    env.close()
    expect(episode.cleanup_action == "terminated" and not episode.alive, f"mid-episode cleanup {episode.cleanup_action}")
    log(f"  mid-episode: pid={info['pid']} {episode.cleanup_action}; close() idempotent")

    # close() after a failed reset (missing executable -> startup_failure).
    env = BattleShipBTTEnv(executable=Path(args.exe).with_name("no_such_BattleShip.exe"), run_root=args.run_root)
    try:
        env.reset()
    except EpisodeFailure as exc:
        expect(exc.outcome == EpisodeOutcome.STARTUP_FAILURE, f"expected startup_failure, got {exc.outcome.value}")
        expect(env.phase == "failed" and env.episode is None, "failed reset left an episode behind")
        log(f"  failed reset: {exc.outcome.value} raised, no episode retained")
    else:
        raise AssertionError("reset() with a missing executable must raise EpisodeFailure")
    env.close()
    env.close()
    try:
        env.step(NEUTRAL)
    except BattleShipEnvError:
        pass
    else:
        raise AssertionError("step() after a failed reset and close must raise")

    # close() after a failed step: the pre-existing SSB64_MAX_FRAMES debug aid
    # ends the process mid-episode with exit code 0, which M2 classifies as
    # premature_exit; the wrapper must raise it, never report a finished episode.
    env = make_env(args, extra_env={"SSB64_MAX_FRAMES": str(args.max_frames)})
    observation, info = env.reset()
    steps = 0
    failure: Optional[EpisodeFailure] = None
    deadline = time.monotonic() + args.ready_timeout
    try:
        while failure is None:
            expect(time.monotonic() < deadline, f"frame cap never ended the process after {steps} steps")
            try:
                observation, reward, terminated, truncated, info = env.step(NEUTRAL)
                steps += 1
                expect(not terminated and not truncated, "neutral input must not end the episode")
            except EpisodeFailure as exc:
                failure = exc
        expect(failure.outcome == EpisodeOutcome.PREMATURE_EXIT, f"expected premature_exit, got {failure.outcome.value}")
        expect(failure.exit_code == 0, f"exit code {failure.exit_code}, expected the clean-exit code 0")
        expect(env.phase == "failed" and env.episode is None and not env.owned_process_alive, "failed step left a process")
        log(f"  failed step: premature_exit (exit_code=0) raised after {steps} steps; no episode retained")
    finally:
        env.close()
        env.close()
    check_no_leak(env, before, Path(args.exe))


CASES: Dict[str, Callable[[argparse.Namespace], None]] = {
    "construct": case_construct,
    "action_mapping": case_action_mapping,
    "reset_tick_zero": case_reset_tick_zero,
    "raw_actions": case_raw_actions,
    "random_agent": case_random_agent,
    "reset_partial": case_reset_partial,
    "replay_complete": case_replay_complete,
    "env_checker": case_env_checker,
    "close_paths": case_close_paths,
}
GAME_CASES = set(CASES) - {"construct", "action_mapping"}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cases", nargs="*", choices=sorted(CASES), help="cases to run, in order (default: all)")
    parser.add_argument("--exe", default=str(DEFAULT_EXECUTABLE), help="BattleShip executable (default: %(default)s)")
    parser.add_argument("--run-dir", default=None, help="parent of the per-episode directories (default: a new temp dir)")
    parser.add_argument("--replay", default=str(DEFAULT_REPLAY), help="baseline replay (default: %(default)s)")
    parser.add_argument("--random-steps", type=int, default=150, help="bound of the random-agent case (default: %(default)s)")
    parser.add_argument("--seed", type=int, default=0, help="action_space / reset seed of the random-agent case")
    parser.add_argument("--max-frames", type=int, default=600, help="SSB64_MAX_FRAMES for the failed-step path")
    parser.add_argument("--startup-timeout", type=float, default=60.0)
    parser.add_argument("--ready-timeout", type=float, default=180.0)
    parser.add_argument("--request-timeout", type=float, default=30.0)
    parser.add_argument("--exit-timeout", type=float, default=30.0)
    args = parser.parse_args(argv)
    if args.random_steps < 1:
        parser.error("--random-steps must be >= 1")
    names = list(dict.fromkeys(args.cases)) or list(CASES)
    args.run_root = Path(args.run_dir) if args.run_dir else Path(tempfile.mkdtemp(prefix="battleship_m3_smoke_"))
    if any(name in GAME_CASES for name in names) and not Path(args.exe).is_file():
        log(f"ERROR: executable not found: {args.exe}")
        return 2

    baseline = count_battleship_processes(Path(args.exe))
    log(f"{Path(args.exe).name} processes before the run: {baseline}")
    failures = 0
    for name in names:
        log(f"[{name}]")
        started = time.monotonic()
        try:
            CASES[name](args)
        except Exception as exc:  # noqa: BLE001 - report every failure kind
            failures += 1
            log(f"FAIL {name} ({time.monotonic() - started:.1f}s): {exc}")
            traceback.print_exc()
        else:
            log(f"PASS {name} ({time.monotonic() - started:.1f}s)")
    final = count_battleship_processes(Path(args.exe))
    log(f"{Path(args.exe).name} processes after the run: {final}")
    if baseline is not None and final is not None and final > baseline:
        failures += 1
        log("FAIL cleanup: BattleShip process count rose during the run")
    log(f"run_dir={args.run_root}")
    log(f"M3 {'PASS' if failures == 0 else 'FAIL'} cases={len(names)} failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
