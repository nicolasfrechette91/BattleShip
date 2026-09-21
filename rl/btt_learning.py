#!/usr/bin/env python3
"""M5: Track 1 learning action space, reward v1, policy observation adapter and
training-side artifact policy for BattleShip Mario Break the Targets.

Everything here is Python-owned and sits ABOVE the frozen stack. Nothing
native, nothing in M1/M2, the M3 raw environment (`btt_raw_b8_s161_v1`) or
the M4 recorder changes; the learner reaches BattleShip only through

    Track 1 action  ->  explicit table  ->  M3 legal action  ->  M1d/M1c  ->  native controller frame

Wrapper stack built by make_learning_env() (inner to outer):

    BattleShipBTTEnv            M3: one fresh process per episode, one native tick per step
    RewardV1Wrapper             btt_reward_v1 from the M3 transition (targets_remaining, terminated)
    EpisodeRecordingWrapper     M4: canonical native triples + consumed ticks, anomaly detectors
    Track1PolicyWrapper         MultiDiscrete([9, 8]) in, flat float32 policy observation out

The reward wrapper sits below the M4 recorder so that the recorder's
on_episode_end hook (where TrainingTracker decides what to preserve) already
sees the finished episode's return and target count. The Track 1 wrapper is
outermost so the recorder keeps seeing M3 actions and records the native
triple the environment actually submitted, never a Track 1 index.

Track 1 (`btt_s9_b8_v1`): MultiDiscrete([9, 8]), dimension 0 = stick state,
dimension 1 = button state. Nine stick states (neutral plus the eight
cardinal/diagonal directions at magnitude 80) and eight button states (none,
A, B, C-up, C-left, L, R, Z). C-down, C-right, Start, the D-pad and every
button combination are absent. Every mapping is a table lookup: nothing is
clamped, scaled or approximated, and every Track 1 action is by construction
a legal M3 action, hence a legal native action. The tracked 7.43 s replay
uses intermediate analog values, so it is NOT representable in Track 1 and is
never approximated through it: M1e/M2/M3 keep the exact baseline.

Reward v1 (`btt_reward_v1`), per native step:

    reward = newly_broken_targets * target_broken     (1.0 each)
           + per_step                                 (-0.001)
           + clear_bonus if the step is the native EpisodeEnded result (10.0)

Targets broken are the DECREASE in the live targets_remaining count between
consecutive observations; an increase is a contract violation
(RewardContractViolation), never a negative reward. Truncation gets no bonus,
reset produces no reward, wall-clock time is never read. The exact 447-step
baseline (10 targets, clear) totals 10 + 10 - 0.447 = 19.553.

Policy observation (`btt_policy_obs_v1`): a float32 vector of the 15 M3
gameplay fields in declaration order, excluding the two diagnostics
`observation_schema` and `host_frame`. Stable-Baselines3 cannot consume the
M3 Dict space directly (its CombinedExtractor applies nn.Flatten() to each
entry and the M3 entries are zero-dimensional Boxes; verified: IndexError
"Dimension out of range" in torch's flatten). No normalisation is applied:
the native contract establishes no ranges, and the values are cast to
float32 as they are (uint32 counters are far below 2**24 in any episode).

Bounded episodes: M3's Python-owned max_episode_steps (native ticks) is
reused unchanged; DEFAULT_MAX_EPISODE_STEPS is the M5 training default.
A mid-episode lifecycle failure (EpisodeFailure raised by M3 after it has
disposed of the process, e.g. the request timeout after the fighter leaves
the stage) is reported by Track1PolicyWrapper as a truncated step
(terminated False, truncated True, info["truncation_reason"] ==
"episode_failure") so a learner can go on with the next fresh process; it
is never reported as a native completion.

No RNG inspection, logging, control or hashing of any kind exists here;
seeds are Python/ML-side only and never reach the game.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

import gymnasium as gym
import numpy as np
from gymnasium import spaces

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from battleship_client import Button, Observation  # noqa: E402
from battleship_env import (  # noqa: E402
    BUTTON_INDEX,
    DEFAULT_EXECUTABLE,
    ENV_CONTRACT,
    OBSERVATION_FIELDS,
    BattleShipBTTEnv,
    NativeAction,
    action_to_native,
)
from battleship_process import EpisodeFailure, LaunchConfig  # noqa: E402
from run_artifacts import (  # noqa: E402
    DEFAULT_POSITION_DELTA_THRESHOLD,
    EpisodeRecorder,
    EpisodeRecordingWrapper,
    EpisodeStatus,
    ObservationDetector,
    PositionDeltaDetector,
    PreservationReason,
)

# Mario's Break the Targets has ten targets (the frozen M1e MAX_TARGETS); the
# recorder derives targets_broken = TARGETS_TOTAL - final targets_remaining.
TARGETS_TOTAL = 10

# M5 training default for M3's max_episode_steps, in native ticks. About four
# times the 447-tick scripted clear: conservative room for exploration, not a
# bound tuned to the TAS. Game-time equivalent: the tracked baseline pairs
# time_passed 446 with the 7.43 s display time, i.e. 60 tics per second, so
# 1800 ticks are about 30 s of game time (never wall-clock).
DEFAULT_MAX_EPISODE_STEPS = 1800


# -- Track 1 action space -----------------------------------------------------------------

TRACK1_CONTRACT = "btt_s9_b8_v1"

# Dimension 0: stick state -> exact native (stick_x, stick_y). Magnitude 80 is
# the M3 domain limit and the largest effective analog value.
TRACK1_STICK_TABLE: Tuple[Tuple[int, int], ...] = (
    (0, 0),      # 0 neutral
    (80, 0),     # 1 right
    (80, 80),    # 2 up-right
    (0, 80),     # 3 up
    (-80, 80),   # 4 up-left
    (-80, 0),    # 5 left
    (-80, -80),  # 6 down-left
    (0, -80),    # 7 down
    (80, -80),   # 8 down-right
)
TRACK1_STICK_NAMES: Tuple[str, ...] = (
    "neutral", "right", "up-right", "up", "up-left", "left", "down-left", "down", "down-right",
)

# Dimension 1: button state -> native button word. This ordering supersedes
# the older draft that used C-down: C-up and C-left are the two C choices.
TRACK1_BUTTON_TABLE: Tuple[Button, ...] = (
    Button.NONE,    # 0
    Button.A,       # 1
    Button.B,       # 2
    Button.C_UP,    # 3
    Button.C_LEFT,  # 4
    Button.L,       # 5
    Button.R,       # 6
    Button.Z,       # 7
)
TRACK1_BUTTON_NAMES: Tuple[str, ...] = ("none", "A", "B", "C-up", "C-left", "L", "R", "Z")

TRACK1_STICK_STATES = len(TRACK1_STICK_TABLE)    # 9
TRACK1_BUTTON_STATES = len(TRACK1_BUTTON_TABLE)  # 8
TRACK1_ACTION_COUNT = TRACK1_STICK_STATES * TRACK1_BUTTON_STATES  # 72

# Track 1 button index -> M3 BUTTON_TABLE index (M3 order: none, A, B, Z, L, R, C-up, C-left).
TRACK1_TO_M3_BUTTON: Tuple[int, ...] = tuple(BUTTON_INDEX[int(button)] for button in TRACK1_BUTTON_TABLE)

_STICK_INDEX: Dict[Tuple[int, int], int] = {xy: index for index, xy in enumerate(TRACK1_STICK_TABLE)}
_BUTTON_INDEX: Dict[int, int] = {int(button): index for index, button in enumerate(TRACK1_BUTTON_TABLE)}


def make_track1_action_space() -> spaces.MultiDiscrete:
    return spaces.MultiDiscrete([TRACK1_STICK_STATES, TRACK1_BUTTON_STATES])


def enumerate_track1_actions() -> Iterator[Tuple[int, int]]:
    """All 72 (stick_index, button_index) pairs, stick-major."""
    for stick in range(TRACK1_STICK_STATES):
        for button in range(TRACK1_BUTTON_STATES):
            yield stick, button


def _index_value(name: str, value: Any, limit: int) -> int:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"Track 1 {name} index must be an integer, got a boolean")
    if isinstance(value, (int, np.integer)):
        index = int(value)
    elif isinstance(value, np.ndarray) and value.shape == () and np.issubdtype(value.dtype, np.integer):
        index = int(value)
    else:
        raise ValueError(f"Track 1 {name} index must be an integer, got {type(value).__name__}")
    if not 0 <= index < limit:
        raise ValueError(f"Track 1 {name} index {index} outside 0..{limit - 1}")
    return index


def track1_indices(action: Any) -> Tuple[int, int]:
    """Validate a Track 1 action (any 2-element integer sequence or array) and return (stick, button)."""
    if isinstance(action, np.ndarray):
        if action.shape != (2,):
            raise ValueError(f"Track 1 action must have shape (2,), got {action.shape}")
        if not np.issubdtype(action.dtype, np.integer):
            raise ValueError(f"Track 1 action must have an integer dtype, got {action.dtype}")
        values: Sequence[Any] = (action[0], action[1])
    elif isinstance(action, (list, tuple)):
        if len(action) != 2:
            raise ValueError(f"Track 1 action must have 2 entries, got {len(action)}")
        values = action
    else:
        raise ValueError(f"Track 1 action must be a 2-element sequence or array, got {type(action).__name__}")
    return _index_value("stick", values[0], TRACK1_STICK_STATES), _index_value("button", values[1], TRACK1_BUTTON_STATES)


def track1_to_m3(action: Any) -> Dict[str, int]:
    """Track 1 action -> the exact M3 Gym action (button index, stick_x, stick_y). Pure table lookup."""
    stick, button = track1_indices(action)
    stick_x, stick_y = TRACK1_STICK_TABLE[stick]
    return {"button": TRACK1_TO_M3_BUTTON[button], "stick_x": stick_x, "stick_y": stick_y}


def track1_to_native(action: Any) -> NativeAction:
    """Track 1 action -> the native RLAction triple, through the unchanged M3 conversion."""
    return action_to_native(track1_to_m3(action))


def native_to_track1(buttons: int, stick_x: int, stick_y: int) -> Tuple[int, int]:
    """Inverse for native triples inside Track 1; ValueError for anything Track 1 cannot express
    (intermediate analog values, C-down, C-right, ...). Used to read artifacts back, never to clamp."""
    if int(buttons) not in _BUTTON_INDEX:
        raise ValueError(f"button word 0x{int(buttons):04X} is not a Track 1 button state")
    key = (int(stick_x), int(stick_y))
    if key not in _STICK_INDEX:
        raise ValueError(f"stick ({stick_x}, {stick_y}) is not one of the 9 Track 1 stick states")
    return _STICK_INDEX[key], _BUTTON_INDEX[int(buttons)]


def track1_action_name(action: Any) -> str:
    stick, button = track1_indices(action)
    return f"{TRACK1_STICK_NAMES[stick]}+{TRACK1_BUTTON_NAMES[button]}"


# -- reward v1 ------------------------------------------------------------------------------

REWARD_CONTRACT = "btt_reward_v1"


@dataclass(frozen=True)
class RewardV1Config:
    """The three constants of btt_reward_v1. Central, documented, not tuned in M5."""

    target_broken: float = 1.0   # per newly broken target (decrease of targets_remaining)
    per_step: float = -0.001     # per consumed native tick
    clear_bonus: float = 10.0    # once, on the native EpisodeEnded result (successful clear)

    def to_json(self) -> Dict[str, Any]:
        return {"contract": REWARD_CONTRACT, "target_broken": self.target_broken, "per_step": self.per_step,
                "clear_bonus": self.clear_bonus}


DEFAULT_REWARD_CONFIG = RewardV1Config()


class RewardContractViolation(RuntimeError):
    """The observations contradict the BTT contract (targets rising, a clear with targets left)."""


@dataclass(frozen=True)
class RewardBreakdown:
    total: float
    newly_broken: int
    target_term: float
    step_term: float
    clear_term: float

    def to_json(self) -> Dict[str, Any]:
        return {"total": self.total, "newly_broken": self.newly_broken, "target_term": self.target_term,
                "step_term": self.step_term, "clear_term": self.clear_term}


def live_targets(observation: Mapping[str, Any]) -> Optional[int]:
    """targets_remaining of an M3 Gym observation, or None when btt_active is 0 (then the field is a
    deterministic zero by the M1b contract, never 'all targets broken')."""
    return int(observation["targets_remaining"]) if int(observation["btt_active"]) == 1 else None


def reward_v1(
    previous_targets: Optional[int],
    current_targets: Optional[int],
    terminated: bool,
    config: RewardV1Config = DEFAULT_REWARD_CONFIG,
) -> RewardBreakdown:
    """The reward of one native step.

    previous_targets / current_targets: the live targets_remaining before and after the step
    (None when not live). terminated: the step returned the native EpisodeEnded result.
    """
    if previous_targets is None or current_targets is None:
        newly_broken = 0
    else:
        if current_targets > previous_targets:
            raise RewardContractViolation(
                f"targets_remaining rose from {previous_targets} to {current_targets}; the BTT contract counts down only"
            )
        newly_broken = int(previous_targets) - int(current_targets)
    if terminated and current_targets != 0:
        raise RewardContractViolation(
            f"native EpisodeEnded with targets_remaining {current_targets!r}; a clear requires 0"
        )
    target_term = newly_broken * config.target_broken
    step_term = config.per_step
    clear_term = config.clear_bonus if terminated else 0.0
    return RewardBreakdown(target_term + step_term + clear_term, newly_broken, target_term, step_term, clear_term)


def expected_return(targets_broken: int, steps: int, cleared: bool, config: RewardV1Config = DEFAULT_REWARD_CONFIG) -> float:
    """Closed form of the episode return under btt_reward_v1 (for checks; the wrapper accumulates per step)."""
    return targets_broken * config.target_broken + steps * config.per_step + (config.clear_bonus if cleared else 0.0)


# -- policy observation ----------------------------------------------------------------------

POLICY_OBSERVATION_CONTRACT = "btt_policy_obs_v1"

# Excluded from the policy input: pure diagnostics that describe the capture,
# not the game (schema id; host-side callback count that advances on parked
# host iterations). Everything else in the M1b snapshot is gameplay state and
# is kept, raw, in declaration order.
POLICY_EXCLUDED_FIELDS: Tuple[str, ...] = ("observation_schema", "host_frame")
POLICY_FIELDS: Tuple[str, ...] = tuple(name for name, _ in OBSERVATION_FIELDS if name not in POLICY_EXCLUDED_FIELDS)
POLICY_OBSERVATION_SIZE = len(POLICY_FIELDS)  # 15


def make_policy_observation_space() -> spaces.Box:
    return spaces.Box(low=-np.inf, high=np.inf, shape=(POLICY_OBSERVATION_SIZE,), dtype=np.float32)


def policy_observation(observation: Mapping[str, Any]) -> np.ndarray:
    """M3 Gym observation (Dict) -> float32 vector over POLICY_FIELDS. Values are cast, never scaled."""
    return np.array([float(observation[name]) for name in POLICY_FIELDS], dtype=np.float32)


def policy_observation_from_native(observation: Observation) -> np.ndarray:
    return np.array([float(getattr(observation, name)) for name in POLICY_FIELDS], dtype=np.float32)


# -- wrappers -------------------------------------------------------------------------------------


class RewardV1Wrapper(gym.Wrapper):
    """btt_reward_v1 on top of BattleShipBTTEnv. Replaces the M3 placeholder 0.0 with the reward of
    the transition; changes nothing else (actions, observations, termination, truncation, info keys
    all pass through). Sits directly on the M3 environment, below the M4 recorder."""

    def __init__(self, env: Any, config: RewardV1Config = DEFAULT_REWARD_CONFIG, tracker: Optional["TrainingTracker"] = None):
        super().__init__(env)
        self.reward_config = config
        self.tracker = tracker
        self._previous_targets: Optional[int] = None
        self.episode_return = 0.0
        self.episode_steps = 0
        self.episode_targets_broken = 0
        self.last_breakdown: Optional[RewardBreakdown] = None

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        observation, info = self.env.reset(seed=seed, options=options)
        self._previous_targets = live_targets(observation)
        self.episode_return = 0.0
        self.episode_steps = 0
        self.episode_targets_broken = 0
        self.last_breakdown = None
        info["reward_contract"] = REWARD_CONTRACT
        return observation, info

    def step(self, action: Any):
        observation, _placeholder, terminated, truncated, info = self.env.step(action)  # EpisodeFailure propagates
        current = live_targets(observation)
        breakdown = reward_v1(self._previous_targets, current, terminated, self.reward_config)
        self._previous_targets = current
        self.last_breakdown = breakdown
        self.episode_return += breakdown.total
        self.episode_steps += 1
        self.episode_targets_broken += breakdown.newly_broken
        info["reward_contract"] = REWARD_CONTRACT
        info["reward_v1"] = breakdown.to_json()
        info["episode_return"] = self.episode_return
        info["episode_targets_broken"] = self.episode_targets_broken
        if self.tracker is not None:
            self.tracker.note_step(breakdown, terminated, truncated, info)
        return observation, breakdown.total, terminated, truncated, info


class Track1PolicyWrapper(gym.Wrapper):
    """Outermost learning wrapper: MultiDiscrete([9, 8]) actions in, float32 policy observations out.

    A Track 1 action is converted to its M3 action before anything is sent
    (ValueError for an invalid one, nothing consumed). A mid-episode
    EpisodeFailure (M3 has already disposed of the process; the M4 recorder
    below has already finished that episode as FAILED) becomes a truncated
    step returning the last observation with reward 0.0 (no tick was
    consumed) so the next reset() can start a fresh process."""

    def __init__(self, env: Any):
        super().__init__(env)
        self.action_space = make_track1_action_space()
        self.observation_space = make_policy_observation_space()
        self._last_policy_observation: Optional[np.ndarray] = None
        self.failures: List[Dict[str, Any]] = []

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        observation, info = self.env.reset(seed=seed, options=options)
        policy_obs = policy_observation(observation)
        self._last_policy_observation = policy_obs
        info["track1_contract"] = TRACK1_CONTRACT
        info["policy_observation_contract"] = POLICY_OBSERVATION_CONTRACT
        info["m3_observation"] = observation
        return policy_obs, info

    def step(self, action: Any):
        stick, button = track1_indices(action)
        m3_action = track1_to_m3((stick, button))
        try:
            observation, reward, terminated, truncated, info = self.env.step(m3_action)
        except EpisodeFailure as exc:
            if self._last_policy_observation is None:
                raise
            record = {"outcome": exc.outcome.value, "message": exc.message, "track1_action": [stick, button]}
            self.failures.append(record)
            info = {
                "track1_contract": TRACK1_CONTRACT,
                "track1_action": [stick, button],
                "track1_action_name": track1_action_name((stick, button)),
                "consumed_tick": None,
                "truncation_reason": "episode_failure",
                "failure_outcome": exc.outcome.value,
                "failure_message": exc.message,
                "failure_diagnostics": dict(exc.diagnostics),
            }
            return self._last_policy_observation, 0.0, False, True, info
        policy_obs = policy_observation(observation)
        self._last_policy_observation = policy_obs
        info["track1_contract"] = TRACK1_CONTRACT
        info["track1_action"] = [stick, button]
        info["track1_action_name"] = track1_action_name((stick, button))
        info["m3_action"] = m3_action
        info["m3_observation"] = observation
        return policy_obs, reward, terminated, truncated, info


# -- training tracker: best-run semantics and the M5 preservation policy ---------------------------

# M5 preservation vocabulary. The M4 PreservationReason enum is used as is;
# "first successful clear" has no M4 member, so it is written as
# new_fastest_completed_run (the first clear is the fastest so far) with an
# explanatory note, and every M5 decision is additionally tagged in
# labels["preservation_events"] so an artifact can be queried by M5 event.
EVENT_PERIODIC = "periodic_milestone"
EVENT_NEW_BEST_TARGETS = "new_best_target_count"
EVENT_FIRST_CLEAR = "first_successful_clear"
EVENT_NEW_FASTEST_CLEAR = "new_fastest_completed_run"
EVENT_ANOMALY = "anomaly"
EVENT_MANUAL = "manual"
PRESERVATION_EVENTS: Tuple[str, ...] = (
    EVENT_PERIODIC, EVENT_NEW_BEST_TARGETS, EVENT_FIRST_CLEAR, EVENT_NEW_FASTEST_CLEAR, EVENT_ANOMALY, EVENT_MANUAL,
)


@dataclass
class EpisodeSummary:
    episode_number: int
    role: str
    status: str
    steps: int
    episode_return: float
    targets_broken: int
    cleared: bool
    completion_time_passed: Optional[int]
    completion_input_tick: Optional[int]
    native_steps_at_end: int
    sb3_num_timesteps_at_end: Optional[int]
    checkpoint_label: Optional[str]
    preservation_events: List[str]
    preservation_reasons: List[str]
    anomaly_events: int
    episode_id: Optional[str]

    def to_json(self) -> Dict[str, Any]:
        return dict(vars(self))


class TrainingTracker:
    """Training-side facts and the preservation policy for the M4 recorder.

    Counts native steps and episodes, keeps the best objective metrics
    (maximum targets broken; for native clears the minimum
    completion_time_passed, with completion_input_tick stored beside it and
    never compared or derived), decides periodic / best / first-clear /
    fastest-clear / manual preservation in on_episode_end(), and writes the
    training metadata (episode number, global timestep, checkpoint label,
    return, targets, terminal state, completion time) into the recorder's
    labels. host_frame and wall-clock time are never used as performance."""

    def __init__(
        self,
        *,
        run_id: Optional[str] = None,
        role: str = "training",
        periodic_episodes: Optional[int] = 10,
        periodic_timesteps: Optional[int] = None,
        reward_config: RewardV1Config = DEFAULT_REWARD_CONFIG,
        targets_total: int = TARGETS_TOTAL,
    ):
        if periodic_episodes is not None and periodic_episodes < 1:
            raise ValueError("periodic_episodes must be >= 1 or None")
        if periodic_timesteps is not None and periodic_timesteps < 1:
            raise ValueError("periodic_timesteps must be >= 1 or None")
        self.run_id = run_id
        self.role = role
        self.periodic_episodes = periodic_episodes
        self.periodic_timesteps = periodic_timesteps
        self.reward_config = reward_config
        self.targets_total = targets_total
        self.episodes_started = 0
        self.episodes_finished = 0
        self.native_steps = 0
        self.sb3_num_timesteps: Optional[int] = None  # set by the training callback
        self.checkpoint_label: Optional[str] = None
        self.best_targets_broken = 0
        self.best_completion_time_passed: Optional[int] = None
        self.best_completion_input_tick: Optional[int] = None
        self.first_clear_episode: Optional[int] = None
        self.clears = 0
        self.truncations = 0
        self.failures = 0
        self.aborted = 0
        self.mismatches: List[Dict[str, Any]] = []
        self.summaries: List[EpisodeSummary] = []
        self.preserved: List[EpisodeSummary] = []
        self._last_periodic_step = 0
        self._manual_note: Optional[str] = None
        self._current: Dict[str, Any] = {}

    # -- hooks used by the wrappers ---------------------------------------------------------------

    def labels_for_new_episode(self) -> Dict[str, Any]:
        """Called by EpisodeRecordingWrapper at every reset(): starts the episode's bookkeeping."""
        self.episodes_started += 1
        self._current = {"episode_number": self.episodes_started, "steps": 0, "return": 0.0, "targets_broken": 0,
                         "terminated": False, "truncated": False}
        return {
            "milestone": "M5",
            "role": self.role,
            "run_id": self.run_id,
            "episode_number": self.episodes_started,
            "native_steps_at_start": self.native_steps,
            "sb3_num_timesteps_at_start": self.sb3_num_timesteps,
            "checkpoint_label": self.checkpoint_label,
            "track1_contract": TRACK1_CONTRACT,
            "reward_contract": REWARD_CONTRACT,
            "reward_config": self.reward_config.to_json(),
            "policy_observation_contract": POLICY_OBSERVATION_CONTRACT,
            "best_targets_broken_before": self.best_targets_broken,
            "best_completion_time_passed_before": self.best_completion_time_passed,
        }

    def note_step(self, breakdown: RewardBreakdown, terminated: bool, truncated: bool, info: Mapping[str, Any]) -> None:
        """Called by RewardV1Wrapper after every accepted native step."""
        self.native_steps += 1
        if not self._current:  # stepping without the recorder wrapper having started an episode
            self._current = {"episode_number": self.episodes_started, "steps": 0, "return": 0.0, "targets_broken": 0,
                             "terminated": False, "truncated": False}
        self._current["steps"] += 1
        self._current["return"] += breakdown.total
        self._current["targets_broken"] += breakdown.newly_broken
        self._current["terminated"] = bool(terminated)
        self._current["truncated"] = bool(truncated)

    def request_manual_preservation(self, note: str = "manual") -> None:
        """Preserve the episode that ends next (the running one) for the reason `manual`."""
        self._manual_note = note

    def on_episode_end(self, recorder: EpisodeRecorder) -> None:
        """EpisodeRecordingWrapper hook: decide preservation and complete the labels. Never raises."""
        current = self._current or {"episode_number": self.episodes_started, "steps": 0, "return": 0.0,
                                    "targets_broken": 0, "terminated": False, "truncated": False}
        self._current = {}
        status = recorder.status.value
        terminal = dict(recorder.terminal)
        episode_number = int(current["episode_number"])
        steps = int(current["steps"])
        episode_return = float(current["return"])
        targets_broken = int(current["targets_broken"])
        cleared = recorder.status == EpisodeStatus.TERMINAL
        completion_time_passed = terminal.get("completion_time_passed") if cleared else None
        completion_input_tick = terminal.get("completion_input_tick") if cleared else None
        recorded_broken = terminal.get("targets_broken")
        if recorded_broken is not None and int(recorded_broken) != targets_broken:
            self.mismatches.append({"episode_number": episode_number, "reward_targets_broken": targets_broken,
                                    "recorder_targets_broken": int(recorded_broken)})
        finished = recorder.status in (EpisodeStatus.TERMINAL, EpisodeStatus.TRUNCATED, EpisodeStatus.FAILED)
        events: List[str] = []
        if finished:
            self.episodes_finished += 1
            if cleared:
                self.clears += 1
            elif recorder.status == EpisodeStatus.TRUNCATED:
                self.truncations += 1
            else:
                self.failures += 1
            # Periodic milestone: by finished-episode count and/or by native steps.
            due = False
            if self.periodic_episodes is not None and self.episodes_finished % self.periodic_episodes == 0:
                due = True
            if self.periodic_timesteps is not None and self.native_steps - self._last_periodic_step >= self.periodic_timesteps:
                due = True
            if due:
                self._last_periodic_step = self.native_steps
                recorder.preserve(PreservationReason.PERIODIC_MILESTONE,
                                  f"episode {episode_number} ({self.episodes_finished} finished, {self.native_steps} native steps)")
                events.append(EVENT_PERIODIC)
            # New best target count (strictly more than the best so far; 0 is never a best).
            if targets_broken > self.best_targets_broken:
                recorder.preserve(PreservationReason.NEW_BEST_TARGET_COUNT,
                                  f"{targets_broken} targets broken, previous best {self.best_targets_broken}")
                self.best_targets_broken = targets_broken
                events.append(EVENT_NEW_BEST_TARGETS)
            # Clears: first ever, then any faster one by the game's own completion_time_passed.
            if cleared and completion_time_passed is not None:
                ctp = int(completion_time_passed)
                if self.first_clear_episode is None:
                    self.first_clear_episode = episode_number
                    recorder.preserve(PreservationReason.NEW_FASTEST_COMPLETED_RUN,
                                      f"first successful clear: completion_time_passed {ctp} "
                                      f"(completion_input_tick {completion_input_tick})")
                    events.extend([EVENT_FIRST_CLEAR, EVENT_NEW_FASTEST_CLEAR])
                    self.best_completion_time_passed = ctp
                    self.best_completion_input_tick = completion_input_tick
                elif self.best_completion_time_passed is not None and ctp < self.best_completion_time_passed:
                    recorder.preserve(PreservationReason.NEW_FASTEST_COMPLETED_RUN,
                                      f"completion_time_passed {ctp} < previous best {self.best_completion_time_passed}")
                    events.append(EVENT_NEW_FASTEST_CLEAR)
                    self.best_completion_time_passed = ctp
                    self.best_completion_input_tick = completion_input_tick
        else:
            self.aborted += 1
        if self._manual_note is not None:
            recorder.preserve(PreservationReason.MANUAL, self._manual_note)
            events.append(EVENT_MANUAL)
            self._manual_note = None
        if recorder.events:
            events.append(EVENT_ANOMALY)  # M4 has already marked the episode; tagged here for queries
        recorder.labels.update({
            "episode_status": status,
            "episode_steps": steps,
            "episode_return": episode_return,
            "targets_broken": targets_broken,
            "terminated": cleared,
            "truncated": recorder.status == EpisodeStatus.TRUNCATED,
            "completion_time_passed": completion_time_passed,
            "completion_input_tick": completion_input_tick,
            "native_steps_at_end": self.native_steps,
            "sb3_num_timesteps_at_end": self.sb3_num_timesteps,
            "checkpoint_label": self.checkpoint_label,
            "preservation_events": events,
            "best_targets_broken_after": self.best_targets_broken,
            "best_completion_time_passed_after": self.best_completion_time_passed,
        })
        summary = EpisodeSummary(
            episode_number=episode_number, role=self.role, status=status, steps=steps, episode_return=episode_return,
            targets_broken=targets_broken, cleared=cleared, completion_time_passed=completion_time_passed,
            completion_input_tick=completion_input_tick, native_steps_at_end=self.native_steps,
            sb3_num_timesteps_at_end=self.sb3_num_timesteps, checkpoint_label=self.checkpoint_label,
            preservation_events=events, preservation_reasons=[m.reason for m in recorder.marks],
            anomaly_events=len(recorder.events), episode_id=recorder.episode_id if recorder.preserved else None,
        )
        self.summaries.append(summary)
        if recorder.preserved:
            self.preserved.append(summary)

    # -- reporting ------------------------------------------------------------------------------------

    def summary(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "role": self.role,
            "episodes_started": self.episodes_started,
            "episodes_finished": self.episodes_finished,
            "clears": self.clears,
            "truncations": self.truncations,
            "failures": self.failures,
            "aborted": self.aborted,
            "native_steps": self.native_steps,
            "sb3_num_timesteps": self.sb3_num_timesteps,
            "best_targets_broken": self.best_targets_broken,
            "best_completion_time_passed": self.best_completion_time_passed,
            "best_completion_input_tick": self.best_completion_input_tick,
            "first_clear_episode": self.first_clear_episode,
            "preserved_episodes": [s.to_json() for s in self.preserved],
            "targets_broken_mismatches": list(self.mismatches),
            "periodic_episodes": self.periodic_episodes,
            "periodic_timesteps": self.periodic_timesteps,
            "reward_config": self.reward_config.to_json(),
        }


# -- environment builder -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class LearningEnvConfig:
    """Everything make_learning_env() needs. Paths are the caller's; nothing is hard-coded."""

    artifact_root: Path
    executable: Path = DEFAULT_EXECUTABLE
    episodes_root: Optional[Path] = None  # LaunchConfig.run_root (M2 per-episode save/result/log dirs)
    max_episode_steps: int = DEFAULT_MAX_EPISODE_STEPS
    reward: RewardV1Config = DEFAULT_REWARD_CONFIG
    position_delta_threshold: float = DEFAULT_POSITION_DELTA_THRESHOLD
    detectors: Optional[Tuple[ObservationDetector, ...]] = None  # None: PositionDeltaDetector(position_delta_threshold)
    startup_timeout: float = 60.0
    ready_timeout: float = 180.0
    request_timeout: float = 30.0
    exit_timeout: float = 30.0
    extra_env: Mapping[str, str] = field(default_factory=dict)


def make_learning_env(config: LearningEnvConfig, tracker: Optional[TrainingTracker] = None) -> Track1PolicyWrapper:
    """Build the M5 stack around a fresh BattleShipBTTEnv. Launches nothing until reset()."""
    if config.max_episode_steps < 1:
        raise ValueError("max_episode_steps must be >= 1")
    launch = LaunchConfig(
        executable=Path(config.executable),
        run_root=Path(config.episodes_root) if config.episodes_root is not None else None,
        startup_timeout=config.startup_timeout,
        ready_timeout=config.ready_timeout,
        request_timeout=config.request_timeout,
        exit_timeout=config.exit_timeout,
        extra_env=dict(config.extra_env),
    )
    base = BattleShipBTTEnv(launch, max_episode_steps=config.max_episode_steps)
    rewarded = RewardV1Wrapper(base, config.reward, tracker)
    detectors: Iterable[ObservationDetector] = (
        config.detectors if config.detectors is not None else (PositionDeltaDetector(config.position_delta_threshold),)
    )
    recorded = EpisodeRecordingWrapper(
        rewarded,
        config.artifact_root,
        detectors=list(detectors),
        labels=tracker.labels_for_new_episode if tracker is not None else None,
        on_episode_end=tracker.on_episode_end if tracker is not None else None,
        targets_total=TARGETS_TOTAL,
    )
    outer = Track1PolicyWrapper(recorded)
    outer.base_env = base            # type: ignore[attr-defined]
    outer.rewarder = rewarded        # type: ignore[attr-defined]
    outer.recording = recorded       # type: ignore[attr-defined]
    return outer


def contracts() -> Dict[str, Any]:
    """Identifiers of every contract the learner depends on (for config/summary files)."""
    return {
        "m3_action_contract": ENV_CONTRACT,
        "track1_contract": TRACK1_CONTRACT,
        "reward_contract": REWARD_CONTRACT,
        "policy_observation_contract": POLICY_OBSERVATION_CONTRACT,
        "policy_fields": list(POLICY_FIELDS),
        "policy_excluded_fields": list(POLICY_EXCLUDED_FIELDS),
        "track1_stick_table": [list(xy) for xy in TRACK1_STICK_TABLE],
        "track1_button_table": [int(b) for b in TRACK1_BUTTON_TABLE],
        "track1_button_names": list(TRACK1_BUTTON_NAMES),
        "targets_total": TARGETS_TOTAL,
    }
