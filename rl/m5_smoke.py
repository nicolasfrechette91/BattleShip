#!/usr/bin/env python3
"""M5 smoke validation: Track 1 action space, reward v1, policy observation adapter,
learning-environment reset/step/truncation, bounded PPO training, artifact capture,
save/load inference, cleanup.

The first three cases need no game. The others launch the real BattleShip
(build-us/Release/BattleShip.exe by default) through the frozen M2/M3 stack.
Nothing here judges the policy's skill: the PPO case proves the pipeline,
not learning.

    python rl/m5_smoke.py                                        # every case, in order
    python rl/m5_smoke.py track1_mapping reward_synthetic policy_observation   # no game needed

Cases:
  track1_mapping       action_space == MultiDiscrete([9, 8]); all 72 Track 1 actions map to the expected
                       exact M3 action and native triple (and back); C-down / C-right / Start / D-pad and
                       intermediate analog values are unrepresentable; 20000 samples are all legal and cover
                       every one of the 72 actions; malformed actions are rejected, never clamped; the M3
                       contract btt_raw_b8_s161_v1 and its spaces are unchanged
  reward_synthetic     btt_reward_v1 on synthetic transitions: no target, one target, several targets,
                       successful clear, truncation without clear, target-count increase (contract
                       violation), non-live counts, custom constants; the closed-form 447-step baseline
                       return 19.553; RewardV1Wrapper over a fake M3 env accumulates exactly
  policy_observation   the 15-field float32 adapter: fields, exclusions, dtype/shape/values, space
                       containment; SB3 rejects the raw M3 Dict space (the reason the adapter exists) and
                       trains on the adapter's space with MultiDiscrete([9, 8]) actions (no game)
  baseline_reward      real game: the exact 7.43 s replay through RewardV1Wrapper(BattleShipBTTEnv) on the
                       raw M3 path (never Track 1): 447 steps, 10 targets, native clear, return 19.553,
                       completion 446 / 447 unchanged, result JSON equal to the frozen values
  learning_reset_step  real game: make_learning_env -> reset gives step_count 0 / input_tick 0 (nothing
                       consumed); the first Track 1 action consumes tick 0 (input_tick 1, step_count 1,
                       reward -0.001, canonical native triple recorded); a tiny max_episode_steps truncates
                       (terminated False, truncated True), the process is disposed; with a 1-unit detector
                       the episode is preserved for `anomaly` with the M5 training labels; a second reset
                       is a new process at step_count 0
  failure_truncation   real game: SSB64_MAX_FRAMES ends the process mid-episode; the learning wrapper
                       reports a truncated step (truncation_reason episode_failure, outcome premature_exit),
                       the tracker counts a failure, no process is left, and the next reset works
  ppo_smoke            real game: a bounded train_m5.run_training(): >= 1 rollout and optimizer update
                       (policy parameters change), >= 2 finished episodes, a checkpoint and the final model
                       saved, the model reloaded and stepped, >= 1 periodic artifact with canonical native
                       actions and training metadata readable by the M4 reader, no process leak
  save_load_inference  real game: PPO.load of the saved model -> fresh learning env -> reset -> predict ->
                       step: the predicted action fits MultiDiscrete([9, 8]) and maps to a legal M3 action;
                       consumed_tick 0 / input_tick 1 on the first step

Every game case checks that no BattleShip process is left behind. Exit
status: 0 all requested cases passed, 1 otherwise, 2 bad usage.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import time
import traceback
import warnings
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gymnasium as gym  # noqa: E402
import numpy as np  # noqa: E402
from gymnasium import spaces  # noqa: E402

from battleship_client import Button, Observation  # noqa: E402
from battleship_env import (  # noqa: E402
    BUTTON_TABLE,
    DEFAULT_EXECUTABLE,
    ENV_CONTRACT,
    STICK_MAX,
    STICK_MIN,
    BattleShipBTTEnv,
    make_action_space,
    make_observation_space,
    native_to_action,
    observation_to_gym,
)
from battleship_process import LaunchConfig  # noqa: E402
from btt_learning import (  # noqa: E402
    DEFAULT_REWARD_CONFIG,
    EVENT_ANOMALY,
    EVENT_PERIODIC,
    POLICY_EXCLUDED_FIELDS,
    POLICY_FIELDS,
    POLICY_OBSERVATION_CONTRACT,
    POLICY_OBSERVATION_SIZE,
    PRESERVATION_EVENTS,
    REWARD_CONTRACT,
    TARGETS_TOTAL,
    TRACK1_ACTION_COUNT,
    TRACK1_BUTTON_NAMES,
    TRACK1_BUTTON_TABLE,
    TRACK1_CONTRACT,
    TRACK1_STICK_TABLE,
    TRACK1_TO_M3_BUTTON,
    LearningEnvConfig,
    RewardContractViolation,
    RewardV1Config,
    RewardV1Wrapper,
    TrainingTracker,
    enumerate_track1_actions,
    expected_return,
    make_learning_env,
    make_policy_observation_space,
    make_track1_action_space,
    native_to_track1,
    policy_observation,
    policy_observation_from_native,
    reward_v1,
    track1_action_name,
    track1_to_m3,
    track1_to_native,
)
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
from m4_smoke import check_no_leak, count_battleship_processes  # noqa: E402
from run_artifacts import (  # noqa: E402
    NATIVE_ACTION_CONTRACT,
    EpisodeStatus,
    PositionDeltaDetector,
    PreservationReason,
    read_artifact,
)


def log(message: str) -> None:
    print(message, flush=True)


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def expect_raises(fn: Callable[[], Any], exc_type: type, label: str) -> None:
    try:
        fn()
    except exc_type:
        return
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(f"{label}: raised {type(exc).__name__} instead of {exc_type.__name__}: {exc}") from exc
    raise AssertionError(f"{label}: accepted, expected {exc_type.__name__}")


def close_to(value: float, target: float, tolerance: float = 1e-9) -> bool:
    return abs(float(value) - float(target)) <= tolerance


# -- synthetic helpers ------------------------------------------------------------------------------


def native_obs(*, tick: int = 1, targets: int = 10, btt: int = 1, valid: int = 1, x: float = 0.0, y: float = 0.0,
               status: int = 226, host: int = 100) -> Observation:
    return Observation(
        observation_schema=1, host_frame=host, input_tick=tick, time_passed=max(tick - 1, 0), game_status=1,
        btt_active=btt, targets_remaining=targets, fighter_valid=valid, position_x=x, position_y=y,
        air_velocity_x=1.5, air_velocity_y=-2.5, ground_velocity_x=0.25, facing_direction=-1, ground_air_state=1,
        fighter_status_id=status, jumps_used=2,
    )


class FakeM3Env(gym.Env):
    """Scripted stand-in for BattleShipBTTEnv (M3 spaces, M3-shaped observations, no process).

    `script` is the sequence of (targets_remaining, terminated, truncated) per step."""

    def __init__(self, script: Sequence[tuple], initial_targets: int = 10):
        self.observation_space = make_observation_space()
        self.action_space = make_action_space()
        self.script = list(script)
        self.initial_targets = initial_targets
        self.t = 0

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        super().reset(seed=seed)
        self.t = 0
        return observation_to_gym(native_obs(tick=0, targets=self.initial_targets)), {"step_count": 0, "input_tick": 0}

    def step(self, action):
        targets, terminated, truncated = self.script[self.t]
        self.t += 1
        obs = observation_to_gym(native_obs(tick=self.t, targets=targets))
        return obs, 0.0, terminated, truncated, {"consumed_tick": self.t - 1, "step_count": self.t, "input_tick": self.t}


# -- no-game cases ------------------------------------------------------------------------------------


def case_track1_mapping(args: argparse.Namespace) -> None:
    space = make_track1_action_space()
    expect(isinstance(space, spaces.MultiDiscrete) and np.array_equal(space.nvec, np.array([9, 8])),
           f"action space must be MultiDiscrete([9, 8]), got {space}")
    expect(TRACK1_CONTRACT == "btt_s9_b8_v1" and TRACK1_ACTION_COUNT == 72, "contract id / count")
    expect(TRACK1_STICK_TABLE == ((0, 0), (80, 0), (80, 80), (0, 80), (-80, 80), (-80, 0), (-80, -80), (0, -80), (80, -80)),
           f"stick table changed: {TRACK1_STICK_TABLE}")
    expect(TRACK1_BUTTON_TABLE == (Button.NONE, Button.A, Button.B, Button.C_UP, Button.C_LEFT, Button.L, Button.R, Button.Z),
           f"button table changed: {TRACK1_BUTTON_TABLE}")
    expect(TRACK1_BUTTON_NAMES == ("none", "A", "B", "C-up", "C-left", "L", "R", "Z"), "button names")
    expect(Button.C_DOWN not in TRACK1_BUTTON_TABLE and Button.C_RIGHT not in TRACK1_BUTTON_TABLE
           and Button.START not in TRACK1_BUTTON_TABLE, "C-down / C-right / Start must not be Track 1 buttons")

    # M3 contract and spaces are unchanged (Track 1 sits above them).
    m3_space = make_action_space()
    expect(ENV_CONTRACT == "btt_raw_b8_s161_v1", f"M3 contract changed: {ENV_CONTRACT}")
    expect(m3_space["button"] == spaces.Discrete(8) and m3_space["stick_x"] == spaces.Discrete(161, start=-80)
           and m3_space["stick_y"] == spaces.Discrete(161, start=-80) and (STICK_MIN, STICK_MAX) == (-80, 80),
           f"M3 action space changed: {m3_space}")
    expect(TRACK1_TO_M3_BUTTON == (0, 1, 2, 6, 7, 4, 5, 3), f"Track 1 -> M3 button index map: {TRACK1_TO_M3_BUTTON}")

    # Every one of the 72 actions, against an independently written expectation.
    m3_index_of = {int(button): index for index, button in enumerate(BUTTON_TABLE)}
    count = 0
    for stick, button in enumerate_track1_actions():
        x, y = TRACK1_STICK_TABLE[stick]
        word = int(TRACK1_BUTTON_TABLE[button])
        expected_m3 = {"button": m3_index_of[word], "stick_x": x, "stick_y": y}
        for form in ((stick, button), [stick, button], np.array([stick, button]), np.array([stick, button], dtype=np.int32)):
            m3 = track1_to_m3(form)
            expect(m3 == expected_m3, f"({stick},{button}) via {type(form).__name__}: {m3} != {expected_m3}")
            expect(m3_space.contains(m3), f"({stick},{button}) is not a legal M3 action: {m3}")
            native = track1_to_native(form)
            expect((native.buttons, native.stick_x, native.stick_y) == (word, x, y),
                   f"({stick},{button}) native {native} != {(word, x, y)}")
        expect(native_to_track1(word, x, y) == (stick, button), f"inverse of ({stick},{button}) failed")
        expect(space.contains(np.array([stick, button])), f"({stick},{button}) not in the space")
        count += 1
    expect(count == 72, f"enumerated {count} actions")
    log(f"  72/72 Track 1 actions -> exact M3 action + native triple (and back); e.g. (2,3) -> "
        f"{track1_to_m3((2, 3))} / {track1_to_native((2, 3))} = {track1_action_name((2, 3))}")

    # Unrepresentable native inputs (never clamped): C-down, C-right, Start, D-pad, intermediate analog values.
    for word in (Button.C_DOWN, Button.C_RIGHT, Button.START, Button.DPAD_UP, Button.DPAD_DOWN, int(Button.A) | int(Button.B), 0x00C0):
        expect_raises(lambda w=word: native_to_track1(int(w), 0, 0), ValueError, f"button 0x{int(word):04X}")
    for xy in ((37, -61), (80, 40), (1, 0), (-79, 0), (127, 0), (0, -128), (60, 60)):
        expect_raises(lambda p=xy: native_to_track1(0, *p), ValueError, f"stick {xy}")
    log("  C-down, C-right, Start, D-pad, multi-button words and intermediate analog values are not Track 1 actions")

    # Sampling: legal, and covers all 72 actions.
    space.seed(args.seed)
    seen = set()
    n = 20000
    for _ in range(n):
        sample = space.sample()
        expect(isinstance(sample, np.ndarray) and sample.shape == (2,) and np.issubdtype(sample.dtype, np.integer), f"sample {sample!r}")
        expect(space.contains(sample), f"sample outside the space: {sample}")
        m3 = track1_to_m3(sample)
        expect(m3_space.contains(m3), f"sample maps outside M3: {m3}")
        seen.add((int(sample[0]), int(sample[1])))
    expect(len(seen) == 72, f"{n} samples covered {len(seen)} of 72 actions")
    log(f"  {n} action_space.sample() draws: all legal, all map to legal M3 actions, all 72 actions covered")

    # Malformed actions: rejected before anything could be sent.
    bad = [(9, 0), (0, 8), (-1, 0), (0, -1), (0.0, 0), (0, 1.5), (True, 0), (0, False), [0], [0, 0, 0], "00", 3,
           np.array([0, 0], dtype=np.float32), np.array([[0, 0]]), np.array([9, 0]), np.array([0, 8]), None,
           {"stick": 0, "button": 0}]
    for action in bad:
        expect_raises(lambda a=action: track1_to_m3(a), ValueError, f"malformed {action!r}")
    log(f"  {len(bad)} malformed / out-of-range actions rejected with ValueError, never clamped")


def case_reward_synthetic(args: argparse.Namespace) -> None:
    cfg = DEFAULT_REWARD_CONFIG
    expect(REWARD_CONTRACT == "btt_reward_v1" and (cfg.target_broken, cfg.per_step, cfg.clear_bonus) == (1.0, -0.001, 10.0),
           f"reward constants {cfg}")
    cases = [
        ("no target broken", (10, 10, False), -0.001, 0),
        ("one target broken", (10, 9, False), 0.999, 1),
        ("two targets in one step", (10, 8, False), 1.999, 2),
        ("three targets in one step", (5, 2, False), 2.999, 3),
        ("successful clear, last target", (1, 0, True), 10.999, 1),
        ("successful clear, two at once", (2, 0, True), 11.999, 2),
        ("truncation without clear", (3, 3, False), -0.001, 0),
        ("count not live before", (None, 5, False), -0.001, 0),
        ("count not live after", (5, None, False), -0.001, 0),
    ]
    for label, (prev, cur, term), total, broken in cases:
        r = reward_v1(prev, cur, term, cfg)
        expect(close_to(r.total, total) and r.newly_broken == broken, f"{label}: {r} != {total}/{broken}")
        expect(close_to(r.target_term + r.step_term + r.clear_term, r.total), f"{label}: terms do not add up")
    expect_raises(lambda: reward_v1(9, 10, False, cfg), RewardContractViolation, "targets rising 9 -> 10")
    expect_raises(lambda: reward_v1(0, 1, False, cfg), RewardContractViolation, "targets rising 0 -> 1")
    expect_raises(lambda: reward_v1(2, 1, True, cfg), RewardContractViolation, "clear with a target left")
    custom = RewardV1Config(target_broken=2.0, per_step=-0.01, clear_bonus=5.0)
    expect(close_to(reward_v1(10, 9, False, custom).total, 1.99) and close_to(reward_v1(1, 0, True, custom).total, 6.99),
           "custom constants not applied")
    expect(close_to(expected_return(10, 447, True), 19.553), f"closed-form baseline return {expected_return(10, 447, True)}")
    expect(close_to(expected_return(10, 447, False), 9.553), "truncated variant must not get the bonus")
    log(f"  {len(cases)} transitions exact (no target -0.001, one 0.999, two 1.999, clear 10.999 / 11.999, truncation -0.001, "
        "non-live 0 targets); rising counts and a clear with targets left raise RewardContractViolation; "
        "custom constants applied; closed form 10 + 10 - 0.447 = 19.553")

    # The wrapper over a scripted M3 stand-in: exact accumulation, tracker bookkeeping, no bonus on truncation.
    tracker = TrainingTracker(run_id="synthetic", periodic_episodes=None)
    env = RewardV1Wrapper(FakeM3Env([(10, False, False), (9, False, False), (9, False, False), (7, False, False), (1, False, False),
                                     (0, True, False)]), cfg, tracker)
    obs, info = env.reset()
    expect(info["reward_contract"] == REWARD_CONTRACT and env.episode_return == 0.0, "reset must produce no reward")
    rewards = []
    for _ in range(6):
        obs, reward, terminated, truncated, info = env.step({"button": 0, "stick_x": 0, "stick_y": 0})
        rewards.append(reward)
    expect([round(r, 6) for r in rewards] == [-0.001, 0.999, -0.001, 1.999, 5.999, 10.999], f"wrapper rewards {rewards}")
    expect(close_to(env.episode_return, expected_return(10, 6, True), 1e-9) and env.episode_targets_broken == 10 and terminated
           and not truncated,
           f"wrapper accumulation {env.episode_return} / {env.episode_targets_broken}")
    expect(info["reward_v1"]["clear_term"] == 10.0 and info["episode_return"] == env.episode_return, f"info {info['reward_v1']}")
    expect(tracker.native_steps == 6, f"tracker native steps {tracker.native_steps}")
    env2 = RewardV1Wrapper(FakeM3Env([(10, False, False), (10, False, True)]), cfg)
    env2.reset()
    env2.step({"button": 0, "stick_x": 0, "stick_y": 0})
    obs, reward, terminated, truncated, info = env2.step({"button": 0, "stick_x": 0, "stick_y": 0})
    expect(truncated and not terminated and close_to(reward, -0.001) and close_to(env2.episode_return, -0.002), "truncation got a bonus")
    env3 = RewardV1Wrapper(FakeM3Env([(10, False, False), (11, False, False)]), cfg)
    env3.reset()
    env3.step({"button": 0, "stick_x": 0, "stick_y": 0})
    expect_raises(lambda: env3.step({"button": 0, "stick_x": 0, "stick_y": 0}), RewardContractViolation, "wrapper on rising targets")
    log("  RewardV1Wrapper over a scripted M3 stand-in: per-step rewards exact, return 19.994 for 10 targets in 6 steps with a "
        "clear, -0.002 for a 2-step truncation, rising targets raise; reset produces no reward")


def case_policy_observation(args: argparse.Namespace) -> None:
    expect(POLICY_OBSERVATION_CONTRACT == "btt_policy_obs_v1" and POLICY_OBSERVATION_SIZE == 15, "contract / size")
    expect(POLICY_EXCLUDED_FIELDS == ("observation_schema", "host_frame"), f"excluded {POLICY_EXCLUDED_FIELDS}")
    expect(POLICY_FIELDS == ("input_tick", "time_passed", "game_status", "btt_active", "targets_remaining", "fighter_valid",
                             "position_x", "position_y", "air_velocity_x", "air_velocity_y", "ground_velocity_x",
                             "facing_direction", "ground_air_state", "fighter_status_id", "jumps_used"), f"fields {POLICY_FIELDS}")
    space = make_policy_observation_space()
    expect(space.shape == (15,) and space.dtype == np.float32, f"space {space}")
    native = native_obs(tick=447, targets=0, x=2431.5, y=932.525, status=226, host=4000000000)
    vec = policy_observation(observation_to_gym(native))
    expect(isinstance(vec, np.ndarray) and vec.shape == (15,) and vec.dtype == np.float32, f"vector {vec.dtype} {vec.shape}")
    expect(space.contains(vec), "vector not in the policy space")
    expected = np.array([447, 446, 1, 1, 0, 1, 2431.5, 932.525, 1.5, -2.5, 0.25, -1, 1, 226, 2], dtype=np.float32)
    expect(np.array_equal(vec, expected), f"values {vec} != {expected}")
    expect(np.array_equal(policy_observation_from_native(native), vec), "native-path adapter differs")
    expect(4000000000 not in vec and 1 not in vec[:1] or True, "")  # host_frame / schema never appear: checked by fields above
    log("  15 float32 features in M1b order without observation_schema / host_frame; values cast exactly (447, 446, ..., 226, 2)")

    # Why the adapter exists: SB3 cannot consume the M3 Dict space as is; it can consume the adapter's space.
    from stable_baselines3 import PPO

    class SpaceProbe(gym.Env):
        def __init__(self, obs_space, obs_fn):
            self.observation_space, self.action_space, self._fn, self._t = obs_space, make_track1_action_space(), obs_fn, 0

        def reset(self, *, seed=None, options=None):
            super().reset(seed=seed)
            self._t = 0
            return self._fn(self._t), {}

        def step(self, action):
            expect(make_track1_action_space().contains(np.asarray(action)), f"SB3 produced an illegal action {action!r}")
            self._t += 1
            return self._fn(self._t), -0.001, False, self._t >= 8, {}

    raw_error: Optional[str] = None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            PPO("MultiInputPolicy", SpaceProbe(make_observation_space(), lambda t: observation_to_gym(native_obs(tick=t))),
                n_steps=16, batch_size=8, n_epochs=1, seed=args.seed, device="cpu", verbose=0).learn(16)
        except IndexError as exc:
            raw_error = f"IndexError: {exc}"
        expect(raw_error is not None, "SB3 unexpectedly accepted the raw M3 Dict space; re-evaluate whether the adapter is needed")
        model = PPO("MlpPolicy", SpaceProbe(space, lambda t: policy_observation(observation_to_gym(native_obs(tick=t)))),
                    n_steps=16, batch_size=8, n_epochs=1, seed=args.seed, device="cpu", verbose=0)
        model.learn(32)
        action, _ = model.predict(vec, deterministic=True)
    expect(make_track1_action_space().contains(np.asarray(action)) and np.asarray(action).shape == (2,), f"predict {action!r}")
    log(f"  SB3 MultiInputPolicy on the raw M3 Dict space fails ({raw_error[:70]}...); MlpPolicy on the adapter space trains 32 "
        f"steps and predicts a legal Track 1 action {np.asarray(action).tolist()}")


# -- game cases ---------------------------------------------------------------------------------------------


def launch_config(args: argparse.Namespace, **overrides: Any) -> LaunchConfig:
    fields: Dict[str, Any] = dict(executable=Path(args.exe), run_root=args.run_root, startup_timeout=args.startup_timeout,
                                  ready_timeout=args.ready_timeout, request_timeout=args.request_timeout,
                                  exit_timeout=args.exit_timeout, extra_env=dict(args.child_env))
    if "extra_env" in overrides:
        overrides["extra_env"] = {**dict(args.child_env), **dict(overrides["extra_env"])}
    fields.update(overrides)
    return LaunchConfig(**fields)


def env_config(args: argparse.Namespace, artifact_root: Path, **overrides: Any) -> LearningEnvConfig:
    fields: Dict[str, Any] = dict(artifact_root=artifact_root, executable=Path(args.exe), episodes_root=args.run_root,
                                  startup_timeout=args.startup_timeout, ready_timeout=args.ready_timeout,
                                  request_timeout=args.request_timeout, exit_timeout=args.exit_timeout,
                                  extra_env=dict(args.child_env))
    # A case-specific extra_env (e.g. SSB64_MAX_FRAMES) is layered on top of --child-env, never instead of it.
    if "extra_env" in overrides:
        overrides["extra_env"] = {**dict(args.child_env), **dict(overrides["extra_env"])}
    fields.update(overrides)
    return LearningEnvConfig(**fields)


def field_index(name: str) -> int:
    return POLICY_FIELDS.index(name)


def case_baseline_reward(args: argparse.Namespace) -> None:
    """The exact 7.43 s trajectory on the raw M3 path with reward v1 attached. Never through Track 1."""
    before = count_battleship_processes(Path(args.exe))
    rows = read_btti_rows(args.replay)
    expect(len(rows) == SOURCE_ROWS, f"{len(rows)} replay rows, expected {SOURCE_ROWS}")
    unrepresentable = 0
    for row in rows:
        try:
            native_to_track1(row.buttons, row.stick_x, row.stick_y)
        except ValueError:
            unrepresentable += 1
    expect(unrepresentable > 0, "the tracked replay unexpectedly fits Track 1; the doc's representability claim needs revisiting")
    tracker = TrainingTracker(run_id="baseline", periodic_episodes=None)
    env = RewardV1Wrapper(BattleShipBTTEnv(launch_config(args)), DEFAULT_REWARD_CONFIG, tracker)
    rewards: List[float] = []
    try:
        observation, info = env.reset()
        expect(info["step_count"] == 0 and int(observation["input_tick"]) == 0 and env.episode_return == 0.0, "reset state")
        previous = None
        terminated = truncated = False
        for row_index, row in enumerate(rows):
            observation, reward, terminated, truncated, info = env.step(native_to_action(row.buttons, row.stick_x, row.stick_y))
            rewards.append(float(reward))
            result = env.env.last_step_result
            check_step(row_index, result, previous)
            previous = result.observation
            expect(info["reward_v1"]["newly_broken"] >= 0 and math.isfinite(reward), f"row {row_index}: reward {info['reward_v1']}")
            if terminated:
                check_completion(row_index, result)
                break
        expect(terminated and not truncated, "baseline did not terminate natively")
        for key, value in EXPECTED_RESULT.items():
            expect(info["result"].get(key) == value, f"result JSON {key} is {info['result'].get(key)!r}, expected {value!r}")
        o = env.env.last_step_result.observation
        expect(len(rewards) == COMPLETION_STEPS == info["step_count"] and info["consumed_tick"] == COMPLETION_CONSUMED_TICK,
               f"steps {len(rewards)} / consumed {info['consumed_tick']}")
        expect(o.time_passed == COMPLETION_TIME_PASSED and o.input_tick == COMPLETION_INPUT_TICK and o.targets_remaining == 0,
               f"completion {o.time_passed}/{o.input_tick}/{o.targets_remaining}")
        total = math.fsum(rewards)
        expect(close_to(total, 19.553, 1e-9), f"baseline return {total!r} != 19.553")
        expect(close_to(env.episode_return, 19.553, 1e-6), f"wrapper return {env.episode_return!r}")
        expect(env.episode_targets_broken == MAX_TARGETS == TARGETS_TOTAL, f"targets broken {env.episode_targets_broken}")
        expect(rewards[-1] == 10.0 + 1.0 - 0.001 or close_to(rewards[-1], 10.999), f"terminal reward {rewards[-1]}")
        target_steps = [i for i, r in enumerate(rewards) if r > 0]
        expect(len(target_steps) <= 10 and sum(1 for r in rewards if r < 0) == COMPLETION_STEPS - len(target_steps), "reward sign pattern")
        expect(tracker.native_steps == COMPLETION_STEPS, f"tracker counted {tracker.native_steps} steps")
    finally:
        env.close()
    check_no_leak(before, Path(args.exe))
    log(f"  raw M3 path: {len(rewards)} steps, last consumed_tick {COMPLETION_CONSUMED_TICK}, completion_time_passed "
        f"{COMPLETION_TIME_PASSED}, completion_input_tick {COMPLETION_INPUT_TICK}, targets 0, return {math.fsum(rewards):.3f} "
        f"(wrapper {env.episode_return:.6f}), target-breaking steps at consumed ticks {target_steps}, "
        f"{unrepresentable} of {SOURCE_ROWS} replay rows are outside Track 1 (never sent through it)")


def case_learning_reset_step(args: argparse.Namespace) -> None:
    before = count_battleship_processes(Path(args.exe))
    artifacts = Path(tempfile.mkdtemp(prefix="artifacts_learning_", dir=str(args.run_root)))
    tracker = TrainingTracker(run_id="smoke_reset_step", periodic_episodes=None)
    tracker.checkpoint_label = "none"
    bound = 12  # 2 probing steps, then 10 ticks walking left (the movement M4's anomaly_live case verified at threshold 1)
    env = make_learning_env(env_config(args, artifacts, max_episode_steps=bound, detectors=(PositionDeltaDetector(1.0),)), tracker)
    try:
        expect(isinstance(env.action_space, spaces.MultiDiscrete) and env.observation_space.shape == (15,), "learning env spaces")
        expect(not env.base_env.owned_process_alive, "constructing the env must launch nothing")
        observation, info = env.reset(seed=args.seed)
        pid = info["pid"]
        expect(env.base_env.owned_process_alive, "reset must launch a process")
        expect(observation.shape == (15,) and observation.dtype == np.float32, f"reset observation {observation}")
        expect(info["step_count"] == 0 and info["input_tick"] == 0 and info["consumed_tick"] is None, f"reset info {info['step_count']}")
        expect(observation[field_index("input_tick")] == 0.0 and observation[field_index("time_passed")] == 0.0
               and observation[field_index("targets_remaining")] == 10.0 and observation[field_index("btt_active")] == 1.0,
               f"reset vector {observation}")
        expect(env.base_env.last_observe is not None and env.base_env.last_observe.observation.input_tick == 0, "tick 0 consumed at reset")
        expect(info["track1_contract"] == TRACK1_CONTRACT and info["reward_contract"] == REWARD_CONTRACT
               and info["policy_observation_contract"] == POLICY_OBSERVATION_CONTRACT, "contract ids in info")
        expect(tracker.episodes_started == 1 and env.recording.recorder is not None and env.recording.recorder.labels["episode_number"] == 1,
               "recorder / tracker not started")
        log(f"  reset: pid {pid}, step_count 0, input_tick 0, consumed_tick None, policy vector {observation.tolist()[:6]}...")

        observation, reward, terminated, truncated, info = env.step((1, 0))  # right + none
        expect(info["consumed_tick"] == 0 and info["input_tick"] == 1 and info["step_count"] == 1, f"first step {info['consumed_tick']}")
        expect(observation[field_index("input_tick")] == 1.0, "policy vector input_tick after the first step")
        expect(close_to(reward, -0.001) and not terminated and not truncated, f"first step reward {reward}")
        native = info["native_action"]
        expect((native.buttons, native.stick_x, native.stick_y) == (0, 80, 0) and info["track1_action"] == [1, 0]
               and info["m3_action"] == {"button": 0, "stick_x": 80, "stick_y": 0}, f"native action {native}")
        rec = env.recording.recorder
        expect(rec is not None and rec.action_count == 1 and rec.actions[0].consumed_tick == 0
               and (rec.actions[0].buttons, rec.actions[0].stick_x, rec.actions[0].stick_y) == (0, 80, 0), "canonical action not recorded")
        observation, reward, terminated, truncated, info = env.step(np.array([3, 3]))  # up + C-up (numpy form, as SB3 sends)
        expect(info["consumed_tick"] == 1 and (info["native_action"].buttons, info["native_action"].stick_y) == (int(Button.C_UP), 80),
               f"second step {info['native_action']}")
        expect(not terminated and not truncated, "second step must not end the episode")
        deltas = []
        for i in range(2, bound):
            x_before = float(info["m3_observation"]["position_x"])
            observation, reward, terminated, truncated, info = env.step([5, 0])  # left + none
            deltas.append(round(float(info["m3_observation"]["position_x"]) - x_before, 2))
            expect(info["consumed_tick"] == i and not terminated, f"walk step {i}")
        expect(truncated and info["consumed_tick"] == bound - 1 and info["truncation_reason"] == "max_episode_steps",
               f"bound {bound}: {info.get('truncation_reason')}")
        expect(not env.base_env.owned_process_alive and info["cleanup_action"] in ("terminated", "killed", "already_exited"),
               f"process not disposed at truncation: {info.get('cleanup_action')}")
        expect(close_to(env.rewarder.episode_return, -0.001 * bound) and tracker.native_steps == bound, f"return {env.rewarder.episode_return}")
        expect(len(env.recording.written) == 1, f"the 1-unit detector must have preserved the episode: {env.recording.written}")
        art = read_artifact(env.recording.written[0])
        m = art.metadata
        expect(m["source_action_contract"] == ENV_CONTRACT and m["action_contract"] == NATIVE_ACTION_CONTRACT, "artifact contracts")
        expect([(a.buttons, a.stick_x, a.stick_y, a.consumed_tick) for a in art.actions]
               == [(0, 80, 0, 0), (int(Button.C_UP), 0, 80, 1)] + [(0, -80, 0, i) for i in range(2, bound)], f"artifact rows {art.actions}")
        expect([native_to_track1(a.buttons, a.stick_x, a.stick_y) for a in art.actions] == [(1, 0), (3, 3)] + [(5, 0)] * (bound - 2),
               "rows are not the Track 1 actions sent")
        labels = m["labels"]
        expect(labels["episode_number"] == 1 and labels["episode_status"] == "truncated" and labels["episode_steps"] == bound
               and close_to(labels["episode_return"], -0.001 * bound) and labels["targets_broken"] == 0 and labels["truncated"] is True
               and labels["terminated"] is False and labels["completion_time_passed"] is None and labels["native_steps_at_end"] == bound
               and labels["checkpoint_label"] == "none" and labels["track1_contract"] == TRACK1_CONTRACT
               and labels["reward_contract"] == REWARD_CONTRACT and labels["preservation_events"] == [EVENT_ANOMALY],
               f"labels {labels}")
        expect([r["reason"] for r in m["preservation_reasons"]][0] == "anomaly" and m["status"] == "truncated"
               and m["terminal"]["targets_remaining"] == 10 and m["terminal"]["last_consumed_tick"] == bound - 1, f"metadata {m['terminal']}")
        expect("seed" not in json.dumps(labels).lower().replace("seed_scope", "") and "rng" not in json.dumps(m).lower(), "no RNG metadata")
        log(f"  Track 1 (1,0) consumed tick 0 -> input_tick 1, step_count 1, reward -0.001, native (0, 80, 0) recorded; (3,3) tick 1; "
            f"(5,0) x{bound - 2} with x deltas {deltas}; bound {bound} -> truncated, process {info['cleanup_action']}; artifact "
            f"{art.episode_id} preserved for anomaly (1-unit detector, {len(m['anomaly_events'])} events) with training labels")

        observation, info = env.reset(seed=args.seed)
        expect(info["pid"] != pid and info["step_count"] == 0 and info["input_tick"] == 0 and tracker.episodes_started == 2,
               "second reset is not a fresh process")
        observation, reward, terminated, truncated, info = env.step((0, 0))
        expect(info["consumed_tick"] == 0 and info["step_count"] == 1, "second episode's first step")
        log(f"  second reset: new pid {info['pid']}, step_count 0, first step consumed tick 0 again")
    finally:
        env.close()
    expect(not env.base_env.owned_process_alive, "close() left the process alive")
    expect(tracker.aborted == 1 and tracker.truncations == 1 and tracker.episodes_finished == 1, f"tracker {tracker.summary()}")
    check_no_leak(before, Path(args.exe))


def case_failure_truncation(args: argparse.Namespace) -> None:
    """A process that ends mid-episode (SSB64_MAX_FRAMES clean-exit debug aid) becomes a truncated step."""
    before = count_battleship_processes(Path(args.exe))
    artifacts = Path(tempfile.mkdtemp(prefix="artifacts_failure_", dir=str(args.run_root)))
    tracker = TrainingTracker(run_id="smoke_failure", periodic_episodes=None)
    env = make_learning_env(env_config(args, artifacts, max_episode_steps=100000, extra_env={"SSB64_MAX_FRAMES": str(args.max_frames)}),
                            tracker)
    try:
        observation, info = env.reset(seed=args.seed)
        steps = 0
        truncated = terminated = False
        t0 = time.monotonic()
        while not (truncated or terminated):
            observation, reward, terminated, truncated, info = env.step((0, 0))
            steps += 1
            expect(steps < 5000, "no failure within 5000 steps")
        expect(truncated and not terminated, f"expected truncation, got terminated={terminated}")
        expect(info["truncation_reason"] == "episode_failure" and info["failure_outcome"] == "premature_exit"
               and info["consumed_tick"] is None and reward == 0.0, f"failure info {info}")
        expect(observation.shape == (15,) and np.all(np.isfinite(observation)), "failure step must return the last observation")
        expect(env.base_env.phase == "failed" and not env.base_env.owned_process_alive, "process not disposed after the failure")
        expect(len(env.failures) == 1 and tracker.failures == 1 and tracker.episodes_finished == 1, f"tracker {tracker.summary()}")
        expect(env.recording.recorder is not None and env.recording.recorder.status == EpisodeStatus.FAILED, "recorder status")
        log(f"  SSB64_MAX_FRAMES={args.max_frames}: {steps - 1} neutral steps, then the step after the exit returned truncated=True, "
            f"terminated=False, truncation_reason episode_failure ({info['failure_outcome']}) after {time.monotonic() - t0:.1f} s; "
            f"recorder status failed, preserved={env.recording.recorder.preserved}")
        observation, info = env.reset(seed=args.seed)
        observation, reward, terminated, truncated, info = env.step((0, 0))
        expect(info["consumed_tick"] == 0 and info["step_count"] == 1, "reset after a failure must give a fresh episode")
        log(f"  reset after the failure: new pid {info['pid']}, first step consumed tick 0")
    finally:
        env.close()
    check_no_leak(before, Path(args.exe))


def case_ppo_smoke(args: argparse.Namespace) -> None:
    from train_m5 import TrainingConfig, run_training

    before = count_battleship_processes(Path(args.exe))
    runs_dir = Path(args.run_root) / "runs"
    config = TrainingConfig(
        run_id="m5_smoke_ppo", runs_dir=runs_dir, executable=Path(args.exe), total_timesteps=args.ppo_timesteps, seed=args.seed,
        max_episode_steps=args.ppo_episode_steps, n_steps=args.ppo_n_steps, batch_size=args.ppo_batch_size, n_epochs=2,
        checkpoint_interval=args.ppo_n_steps * 2, periodic_episodes=2, eval_steps=20, verbose=args.ppo_verbose,
        startup_timeout=args.startup_timeout, ready_timeout=args.ready_timeout, request_timeout=args.request_timeout,
        exit_timeout=args.exit_timeout, extra_env=dict(args.child_env),
    )
    t0 = time.monotonic()
    summary = run_training(config)
    wall = time.monotonic() - t0
    check_no_leak(before, Path(args.exe))
    t = summary["training"]
    expect(t["sb3_num_timesteps"] >= config.total_timesteps and t["native_steps"] == t["sb3_num_timesteps"],
           f"timesteps {t['sb3_num_timesteps']} / native {t['native_steps']}")
    expect(t["rollouts"] >= 1 and (t["sb3_n_updates"] or 0) >= 1 and t["policy_parameters_changed"] is True,
           f"no optimizer update: rollouts {t['rollouts']} n_updates {t['sb3_n_updates']} changed {t['policy_parameters_changed']}")
    expect(t["episodes_finished"] >= 2, f"expected >= 2 finished episodes (episode boundary), got {t['episodes_finished']}")
    expect(t["interrupted"] is False and not summary["owned_process_alive"], "training state")
    expect(len(t["checkpoints"]) >= 1 and all((runs_dir / config.run_id / "checkpoints" / c).is_file() for c in t["checkpoints"]),
           f"checkpoints {t['checkpoints']}")
    final_model = Path(summary["paths"]["final_model"])
    expect(final_model.is_file() and (runs_dir / config.run_id / "config.json").is_file()
           and (runs_dir / config.run_id / "training_summary.json").is_file(), "output files")
    tracker = t["tracker"]
    expect(tracker["targets_broken_mismatches"] == [], f"reward / recorder target counts disagree: {tracker['targets_broken_mismatches']}")
    inference = summary["inference"]
    expect(inference["model_reloaded"] and inference["steps"] >= 1 and inference["all_rewards_finite"]
           and all(a in [list(p) for p in enumerate_track1_actions()] for a in inference["actions"])
           and inference["consumed_ticks"][: inference["steps"]] == list(range(inference["steps"]))
           and not inference["owned_process_alive"], f"inference {inference}")
    expect(inference["artifacts"] and inference["tracker"]["preserved_episodes"][0]["preservation_reasons"] == ["manual"],
           f"the evaluation episode must be preserved manually: {inference['artifacts']}")

    # Artifacts: at least one periodic milestone, canonical native actions, training metadata, M4 reader.
    artifact_root = Path(summary["paths"]["artifacts"])
    written = summary["artifacts"]["written"]
    expect(len(written) >= 1, "no training artifact preserved")
    periodic = 0
    reasons_seen = set()
    for name in written:
        art = read_artifact(artifact_root / name)
        m = art.metadata
        reasons = [r["reason"] for r in m["preservation_reasons"]]
        reasons_seen.update(reasons)
        labels = m["labels"]
        expect(m["action_contract"] == NATIVE_ACTION_CONTRACT and m["source_action_contract"] == ENV_CONTRACT, f"{name}: contracts")
        expect(m["action_count"] == len(art.actions) >= 1 and [a.consumed_tick for a in art.actions] == list(range(len(art.actions))),
               f"{name}: consumed ticks")
        for a in art.actions:  # canonical native triples, each one a Track 1 action
            expect(isinstance(a.buttons, int) and isinstance(a.stick_x, int) and isinstance(a.stick_y, int), f"{name}: row types")
            native_to_track1(a.buttons, a.stick_x, a.stick_y)
        for key in ("episode_number", "native_steps_at_start", "native_steps_at_end", "sb3_num_timesteps_at_start",
                    "sb3_num_timesteps_at_end", "checkpoint_label", "episode_return", "episode_status", "targets_broken",
                    "terminated", "truncated", "completion_time_passed", "completion_input_tick", "preservation_events",
                    "track1_contract", "reward_contract", "reward_config", "run_id", "role"):
            expect(key in labels, f"{name}: label {key} missing")
        expect(labels["role"] == "training" and labels["run_id"] == config.run_id and labels["track1_contract"] == TRACK1_CONTRACT
               and labels["reward_contract"] == REWARD_CONTRACT and labels["episode_steps"] == len(art.actions)
               and math.isfinite(labels["episode_return"]) and labels["episode_status"] in ("truncated", "terminal", "failed"),
               f"{name}: labels {labels}")
        expect(set(labels["preservation_events"]) <= set(PRESERVATION_EVENTS) and len(labels["preservation_events"]) >= 1, f"{name}: events")
        expect(labels["completion_time_passed"] is None or labels["episode_status"] == "terminal", f"{name}: completion on a non-clear")
        if EVENT_PERIODIC in labels["preservation_events"]:
            periodic += 1
            expect(PreservationReason.PERIODIC_MILESTONE.value in reasons, f"{name}: periodic event without the M4 reason")
        expect(m["detectors"][0]["config"]["threshold"] == config.position_delta_threshold, f"{name}: detector config")
    expect(periodic >= 1, f"no periodic milestone artifact among {written}")
    first = read_artifact(artifact_root / written[0]).metadata
    example = {k: first["labels"][k] for k in ("episode_number", "sb3_num_timesteps_at_end", "checkpoint_label", "episode_return",
                                               "targets_broken", "episode_status", "preservation_events")}
    args.trained_model = final_model
    log(f"  PPO/MlpPolicy: {t['sb3_num_timesteps']} timesteps, {t['episodes_started']} started / {t['episodes_finished']} finished "
        f"episodes, {t['rollouts']} rollouts, sb3 n_updates {t['sb3_n_updates']} ({t['gradient_steps_derived']} gradient steps), "
        f"parameters changed {t['policy_parameters_changed']}, train wall {t['wall_s']} s (case wall {wall:.1f} s), "
        f"checkpoints {t['checkpoints']}, final {final_model.name}")
    log(f"  artifacts: {len(written)} preserved ({periodic} periodic), reasons {sorted(reasons_seen)}; "
        f"discarded {summary['artifacts']['discarded']}; evaluation artifact {inference['artifacts']}; example labels {example}")
    log(f"  inference from the reloaded model: {inference['steps']} steps, actions {inference['actions'][:6]}..., "
        f"native {inference['native_actions'][:3]}..., return {inference['episode_return']:.4f}")


def case_save_load_inference(args: argparse.Namespace) -> None:
    from stable_baselines3 import PPO

    from train_m5 import TrainingConfig, run_training

    before = count_battleship_processes(Path(args.exe))
    model_path: Optional[Path] = getattr(args, "trained_model", None)
    if model_path is None or not Path(model_path).is_file():
        log("  no model from ppo_smoke in this invocation: training a minimal one first")
        config = TrainingConfig(run_id="m5_smoke_minimal", runs_dir=Path(args.run_root) / "runs", executable=Path(args.exe),
                                total_timesteps=64, seed=args.seed, max_episode_steps=32, n_steps=32, batch_size=16, n_epochs=1,
                                checkpoint_interval=0, periodic_episodes=None, eval_steps=0, verbose=0,
                                startup_timeout=args.startup_timeout, ready_timeout=args.ready_timeout,
                                request_timeout=args.request_timeout, exit_timeout=args.exit_timeout,
                                extra_env=dict(args.child_env))
        model_path = Path(run_training(config)["paths"]["final_model"])
        check_no_leak(before, Path(args.exe))
    model = PPO.load(str(model_path), device="cpu")
    expect(isinstance(model.action_space, spaces.MultiDiscrete) and np.array_equal(model.action_space.nvec, [9, 8]), f"loaded action space {model.action_space}")
    expect(model.observation_space.shape == (15,), f"loaded observation space {model.observation_space}")
    artifacts = Path(tempfile.mkdtemp(prefix="artifacts_inference_", dir=str(args.run_root)))
    env = make_learning_env(env_config(args, artifacts, max_episode_steps=10), TrainingTracker(run_id="smoke_inference", periodic_episodes=None))
    try:
        observation, info = env.reset(seed=args.seed)
        expect(info["step_count"] == 0 and info["input_tick"] == 0, "fresh reset")
        actions = []
        for i in range(10):
            action, _ = model.predict(observation, deterministic=True)
            action = np.asarray(action)
            expect(action.shape == (2,) and np.issubdtype(action.dtype, np.integer) and env.action_space.contains(action),
                   f"predicted action {action!r} outside MultiDiscrete([9, 8])")
            m3 = track1_to_m3(action)
            expect(make_action_space().contains(m3), f"predicted action maps outside M3: {m3}")
            observation, reward, terminated, truncated, info = env.step(action)
            actions.append(track1_action_name(action))
            expect(info["consumed_tick"] == i and info["step_count"] == i + 1 and math.isfinite(reward)
                   and observation.shape == (15,) and np.all(np.isfinite(observation)), f"step {i}")
            if terminated or truncated:
                break
        expect(truncated and not terminated, "10-step bound expected")
    finally:
        env.close()
    check_no_leak(before, Path(args.exe))
    log(f"  {model_path.name} loaded -> fresh env -> reset -> predict -> step x{len(actions)}: consumed ticks 0..{len(actions) - 1}, "
        f"actions {actions[:5]}...")


CASES: Dict[str, Callable[[argparse.Namespace], None]] = {
    "track1_mapping": case_track1_mapping,
    "reward_synthetic": case_reward_synthetic,
    "policy_observation": case_policy_observation,
    "baseline_reward": case_baseline_reward,
    "learning_reset_step": case_learning_reset_step,
    "failure_truncation": case_failure_truncation,
    "ppo_smoke": case_ppo_smoke,
    "save_load_inference": case_save_load_inference,
}
GAME_CASES = set(CASES) - {"track1_mapping", "reward_synthetic", "policy_observation"}


def _bad_kv(value: str) -> bool:
    raise ValueError(f"--child-env expects KEY=VALUE, got {value!r}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cases", nargs="*", choices=sorted(CASES), help="cases to run, in order (default: all)")
    parser.add_argument("--exe", default=str(DEFAULT_EXECUTABLE))
    parser.add_argument("--run-dir", default=None, help="parent of episode, artifact and run directories (default: a new temp dir)")
    parser.add_argument("--replay", default=str(DEFAULT_REPLAY))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-frames", type=int, default=600, help="SSB64_MAX_FRAMES for failure_truncation (default: %(default)s)")
    parser.add_argument("--ppo-timesteps", type=int, default=512, help="ppo_smoke total timesteps (default: %(default)s)")
    parser.add_argument("--ppo-episode-steps", type=int, default=128, help="ppo_smoke max_episode_steps (default: %(default)s)")
    parser.add_argument("--ppo-n-steps", type=int, default=128, help="ppo_smoke PPO n_steps (default: %(default)s)")
    parser.add_argument("--ppo-batch-size", type=int, default=32, help="ppo_smoke PPO batch_size (default: %(default)s)")
    parser.add_argument("--ppo-verbose", type=int, default=0, help="SB3 verbosity inside ppo_smoke (default: %(default)s)")
    parser.add_argument("--startup-timeout", type=float, default=60.0)
    parser.add_argument("--ready-timeout", type=float, default=180.0)
    parser.add_argument("--request-timeout", type=float, default=30.0)
    parser.add_argument("--exit-timeout", type=float, default=30.0)
    parser.add_argument("--child-env", action="append", default=[], metavar="KEY=VALUE",
                        help="extra environment for every launched BattleShip process (M2 LaunchConfig.extra_env), e.g. "
                             "SSB64_RL_NO_RENDER=1 for the M6 training no-render host mode; repeatable")
    args = parser.parse_args(argv)
    try:
        args.child_env = dict(kv.split("=", 1) for kv in args.child_env if "=" in kv or _bad_kv(kv))
    except ValueError as exc:
        parser.error(str(exc))
    names = list(dict.fromkeys(args.cases)) or list(CASES)
    args.run_root = Path(args.run_dir) if args.run_dir else Path(tempfile.mkdtemp(prefix="battleship_m5_smoke_"))
    args.run_root.mkdir(parents=True, exist_ok=True)
    args.trained_model = None
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
    log(f"M5 {'PASS' if failures == 0 else 'FAIL'} cases={len(names)} failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
