#!/usr/bin/env python3
"""M3: Gymnasium environment around the frozen M1/M2 BattleShip stack.

``BattleShipBTTEnv`` wraps one Mario Break the Targets episode per OS process:

    env = BattleShipBTTEnv()
    observation, info = env.reset()
    observation, reward, terminated, truncated, info = env.step(action)
    env.close()

It is an API milestone, not a learning milestone. It contains no reward
design (``reward`` is always the documented placeholder ``0.0``), no
training code, no Track 1 discretisation, no headless mode and no
multiprocessing. Everything below the API is the validated stack, used as
is:

    reset()  -> M2 BattleShipEpisode: dispose the previous process, launch a
                NEW BattleShip process with isolated files, wait for the
                fresh native state (WaitingForAction, can_step,
                step_count 0), then read the initial observation through
                the non-consuming M1d `observe` op. Tick 0 is NOT consumed.
    step()   -> exactly one M1d `step`, i.e. exactly one M1c native tick:
                consumed_tick == T, observation.input_tick == T + 1.
    close()  -> M2 close(): idempotent, terminates or kills whatever is
                still alive, never leaks the owned process.

Observation space: the frozen M1b RLObservation schema, field for field, as
a ``gymnasium.spaces.Dict`` with the native widths (uint32 / int32 /
float32) and no narrower ranges than the native contract guarantees. The
two validity flags (btt_active, fighter_valid) are Discrete(2).

Action space: the Gym-facing test domain, a deliberate subset of the M1c
raw controller contract. The native contract underneath is unchanged: any
int8 stick value and any of the nine permitted single buttons stay valid at
the M1c / M1d layer, and the raw client still exposes all of them.

    button   Discrete(8)               index into BUTTON_TABLE (none, A, B,
                                       Z, L, R, C-up, C-left)
    stick_x  Discrete(161, start=-80)  exact native value, -80..80
    stick_y  Discrete(161, start=-80)  exact native value, -80..80

Why this subset: analog magnitudes beyond 80 add no effective controller
state (they are capped to +-80 in effect), two C directions are enough to
validate the environment, and leaving out the redundant actions avoids
duplicate effective actions in the Gym domain. C-down, C-right and stick
magnitudes above 80 are unrepresentable through a valid Gym action: they
are rejected, never clamped, never sampled. The Gym space is therefore NOT
lossless over every M1c action; the raw M1d client remains the exact
interface. This is not Track 1 (btt_s9_b8_v1), which reduces both domains
further and stays reserved.

A Box with integer dtype was rejected for the stick: Gymnasium's
Box.sample() clips integer samples two values inside the limits, so the
end points could never be sampled. Discrete with a start offset samples
every value uniformly and `contains` is exact.

Failures of the process, transport or lifecycle raise EpisodeFailure (M2)
or BattleShipError (M1d); they are never reported as a finished episode.
"""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

import gymnasium as gym
import numpy as np
from gymnasium import spaces

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from battleship_client import (  # noqa: E402
    PROTOCOL_VERSION,
    BattleShipError,
    Button,
    Observation,
    Observe,
    ProtocolError,
    StepResult,
    StepState,
)
from battleship_process import (  # noqa: E402
    BattleShipEpisode,
    EpisodeExit,
    EpisodeFailure,
    EpisodeOutcome,
    LaunchConfig,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXECUTABLE = REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"

# Identifies this exact Gym-facing observation/action contract: 8 button
# states, 161 stick values per axis. It names the Gym domain only, not the
# wider M1c / M1d transport capability (nine buttons, full int8 sticks).
# Bump when either space or the conversion changes; Track 1 will be a
# different id.
ENV_CONTRACT = "btt_raw_b8_s161_v1"

# The Gymnasium API needs a number here. 0.0 is a placeholder and nothing
# else: no target, completion, time, distance or movement term exists in M3.
# Reward design is Python-owned and belongs to a later learning milestone.
PLACEHOLDER_REWARD = 0.0

# info keys that name the OS process behind an episode. Two resets are two
# processes, so these can never be equal across resets; every other info key
# is deterministic for the same action sequence. gymnasium's check_env
# asserts info equality across two seeded resets and therefore stops on
# these (documented in docs/rl_gymnasium_m3.md); strip them to compare.
PROCESS_IDENTITY_INFO_KEYS: Tuple[str, ...] = ("pid", "port", "episode_dir", "episode_index")


# -- action space ------------------------------------------------------------------

# Index -> native button word, the Gym-facing button domain:
#   0 none, 1 A, 2 B, 3 Z, 4 L, 5 R, 6 C-up, 7 C-left
# Every entry is a legal M1c single-button word (RL_BUTTONS_PERMITTED in
# port/rl/rl.h). C-down and C-right are legal at the M1c / M1d layer but
# deliberately absent here: two C directions suffice for M3. Start, the
# D-pad and every multi-button word are unrepresentable as before.
BUTTON_TABLE: Tuple[Button, ...] = (
    Button.NONE,
    Button.A,
    Button.B,
    Button.Z,
    Button.L,
    Button.R,
    Button.C_UP,
    Button.C_LEFT,
)
BUTTON_NAMES: Tuple[str, ...] = ("none", "A", "B", "Z", "L", "R", "C-up", "C-left")
BUTTON_INDEX: Dict[int, int] = {int(button): index for index, button in enumerate(BUTTON_TABLE)}

# Gym-facing analog domain. The native contract is int8 (-128..127); values
# beyond +-80 add no effective controller state, so the Gym space stops at
# 80 and anything outside it is an invalid Gym action, never clamped.
STICK_MIN = -80
STICK_MAX = 80
STICK_STATES = STICK_MAX - STICK_MIN + 1  # 161


@dataclass(frozen=True)
class NativeAction:
    """The RLAction triple exactly as the wire carries it."""

    buttons: int  # N64 button word, 0 or one permitted RL_BUTTON_* bit
    stick_x: int  # native int8
    stick_y: int  # native int8


def make_action_space() -> spaces.Dict:
    return spaces.Dict(
        {
            "button": spaces.Discrete(len(BUTTON_TABLE)),
            "stick_x": spaces.Discrete(STICK_STATES, start=STICK_MIN),
            "stick_y": spaces.Discrete(STICK_STATES, start=STICK_MIN),
        }
    )


def _as_int(name: str, value: Any) -> int:
    """Accept Python ints and integer numpy scalars / 0-d arrays; nothing else."""
    if isinstance(value, bool) or isinstance(value, np.bool_):
        raise ValueError(f"action[{name!r}] must be an integer, got a boolean")
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, np.ndarray) and value.shape == () and np.issubdtype(value.dtype, np.integer):
        return int(value)
    raise ValueError(f"action[{name!r}] must be an integer, got {type(value).__name__}")


def action_to_native(action: Mapping[str, Any]) -> NativeAction:
    """Convert a Gym action to the native triple, validating every field.

    Values inside the Gym domain pass through exactly; nothing is clamped.
    Raises ValueError for anything outside the action space (a stick value
    beyond +-80 included). A valid Gym action can never produce an illegal
    native button word.
    """
    if not isinstance(action, Mapping):
        raise ValueError(f"action must be a mapping with button/stick_x/stick_y, got {type(action).__name__}")
    expected = {"button", "stick_x", "stick_y"}
    if set(action) != expected:
        raise ValueError(f"action keys must be {sorted(expected)}, got {sorted(action)}")
    button = _as_int("button", action["button"])
    stick_x = _as_int("stick_x", action["stick_x"])
    stick_y = _as_int("stick_y", action["stick_y"])
    if not 0 <= button < len(BUTTON_TABLE):
        raise ValueError(f"action['button'] {button} outside 0..{len(BUTTON_TABLE) - 1}")
    for name, value in (("stick_x", stick_x), ("stick_y", stick_y)):
        if not STICK_MIN <= value <= STICK_MAX:
            raise ValueError(f"action[{name!r}] {value} outside {STICK_MIN}..{STICK_MAX}")
    return NativeAction(buttons=int(BUTTON_TABLE[button]), stick_x=stick_x, stick_y=stick_y)


def native_to_action(buttons: int, stick_x: int, stick_y: int) -> Dict[str, int]:
    """Inverse of action_to_native for native triples inside the Gym domain
    (e.g. replay rows).

    Raises ValueError for a button word the Gym space cannot represent
    (Start, D-pad, unknown bits, several buttons, and the natively legal
    C-down / C-right) or a stick value outside -80..80 (natively legal up
    to the int8 limits, but outside the Gym domain).
    """
    if buttons not in BUTTON_INDEX:
        raise ValueError(f"button word 0x{buttons:04X} is not in the Gym-facing button domain")
    for name, value in (("stick_x", stick_x), ("stick_y", stick_y)):
        if not STICK_MIN <= value <= STICK_MAX:
            raise ValueError(f"{name} {value} outside {STICK_MIN}..{STICK_MAX}")
    return {"button": BUTTON_INDEX[buttons], "stick_x": int(stick_x), "stick_y": int(stick_y)}


# -- observation space -----------------------------------------------------------------

# RLObservation (port/rl/rl.h) in declaration order with its native widths.
# Kinds: "u32" uint32_t, "flag" uint32_t that is exactly 0 or 1 by contract,
# "f32" float, "i32" int32_t. Ranges are the full native widths: the contract
# guarantees nothing narrower (targets_remaining happens to count 10 -> 0 and
# game_status 0/1/2 today, but neither is promised by the type).
OBSERVATION_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("observation_schema", "u32"),
    ("host_frame", "u32"),
    ("input_tick", "u32"),
    ("time_passed", "u32"),
    ("game_status", "u32"),
    ("btt_active", "flag"),
    ("targets_remaining", "u32"),
    ("fighter_valid", "flag"),
    ("position_x", "f32"),
    ("position_y", "f32"),
    ("air_velocity_x", "f32"),
    ("air_velocity_y", "f32"),
    ("ground_velocity_x", "f32"),
    ("facing_direction", "i32"),
    ("ground_air_state", "i32"),
    ("fighter_status_id", "i32"),
    ("jumps_used", "u32"),
)

_KIND_DTYPE = {"u32": np.uint32, "flag": np.uint32, "f32": np.float32, "i32": np.int32}


def _space_for(kind: str) -> spaces.Space:
    if kind == "u32":
        return spaces.Box(low=0, high=np.iinfo(np.uint32).max, shape=(), dtype=np.uint32)
    if kind == "flag":
        return spaces.Discrete(2)
    if kind == "f32":
        return spaces.Box(low=-np.inf, high=np.inf, shape=(), dtype=np.float32)
    if kind == "i32":
        return spaces.Box(low=np.iinfo(np.int32).min, high=np.iinfo(np.int32).max, shape=(), dtype=np.int32)
    raise ValueError(kind)


def make_observation_space() -> spaces.Dict:
    return spaces.Dict({name: _space_for(kind) for name, kind in OBSERVATION_FIELDS})


def observation_to_gym(observation: Observation) -> Dict[str, Any]:
    """The wire Observation as a Gym observation, one entry per field.

    Box fields become 0-d arrays in the native dtype; the two Discrete flags
    become plain ints (Gymnasium's convention for a Discrete observation).
    Integers are exact; the floats came off the wire as the exact float32
    value widened to double, so the cast back is lossless."""
    gym_obs: Dict[str, Any] = {}
    for name, kind in OBSERVATION_FIELDS:
        value = getattr(observation, name)
        gym_obs[name] = int(value) if kind == "flag" else np.array(value, dtype=_KIND_DTYPE[kind])
    return gym_obs


# -- environment ----------------------------------------------------------------------------


class BattleShipEnvError(RuntimeError):
    """Misuse of the environment API (step before reset, reset after close, ...)."""


class BattleShipBTTEnv(gym.Env):
    """One Mario Break the Targets episode per fresh BattleShip process.

    Constructing the object launches nothing. The first process starts at
    the first reset(). Not thread-safe.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        launch_config: Optional[LaunchConfig] = None,
        *,
        executable: Optional[os.PathLike] = None,
        run_root: Optional[os.PathLike] = None,
        max_episode_steps: Optional[int] = None,
        render_mode: Optional[str] = None,
    ):
        if render_mode is not None:
            raise ValueError(
                "BattleShipBTTEnv supports no render mode: BattleShip draws its own window and M3 adds no "
                "programmatic rendering"
            )
        if max_episode_steps is not None and max_episode_steps < 1:
            raise ValueError("max_episode_steps must be >= 1 or None")
        self.render_mode = None
        self.max_episode_steps = max_episode_steps

        if launch_config is None:
            launch_config = LaunchConfig(executable=Path(executable) if executable is not None else DEFAULT_EXECUTABLE)
        elif executable is not None:
            raise ValueError("pass either launch_config or executable, not both")
        if run_root is not None:
            launch_config = replace(launch_config, run_root=Path(run_root))
        elif launch_config.run_root is None:
            # One run root per environment so every episode of this instance
            # lands under the same directory (M2 would otherwise make a new
            # temp root per launch).
            launch_config = replace(launch_config, run_root=Path(tempfile.mkdtemp(prefix="battleship_m3_")))
        self.launch_config = launch_config

        self.action_space = make_action_space()
        self.observation_space = make_observation_space()

        self._episode: Optional[BattleShipEpisode] = None
        self._episode_index = 0
        self._phase = "idle"  # idle | active | terminated | truncated | failed | closed
        self._steps = 0
        self.last_observe: Optional[Observe] = None
        self.last_step_result: Optional[StepResult] = None
        self.last_episode_exit: Optional[EpisodeExit] = None

    # -- queries -----------------------------------------------------------------------------

    @property
    def episode(self) -> Optional[BattleShipEpisode]:
        """The currently owned M2 episode, or None."""
        return self._episode

    @property
    def phase(self) -> str:
        return self._phase

    @property
    def owned_process_alive(self) -> bool:
        return self._episode is not None and self._episode.alive

    # -- Gymnasium API --------------------------------------------------------------------------

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        # Python-side RNG only (self.np_random). Mario BTT has no RNG state
        # this project inspects or controls; the seed never reaches the game.
        super().reset(seed=seed)
        if self._phase == "closed":
            raise BattleShipEnvError("reset() after close()")

        # A reset is a new OS process. The previous one is gone first.
        self._dispose_episode()
        self._steps = 0
        self.last_step_result = None
        self.last_episode_exit = None
        self._episode_index += 1
        episode = BattleShipEpisode(self.launch_config, index=self._episode_index)
        self._episode = episode
        try:
            fresh = episode.start()  # launch + transport + fresh WaitingForAction / can_step / step_count 0
            assert episode.client is not None
            try:
                observe = episode.client.observe()  # non-consuming: no tick, no clock
            except ProtocolError as exc:
                if exc.error == "unknown_op":
                    raise EpisodeFailure(
                        EpisodeOutcome.REQUEST_REJECTED,
                        "this BattleShip build predates the M3 `observe` op; rebuild build-us Release",
                        episode=episode,
                    ) from exc
                raise episode.classify_step_failure(exc) from exc
            except BattleShipError as exc:
                raise episode.classify_step_failure(exc) from exc
            self._require_initial(fresh.step_count, observe, episode)
        except BaseException:
            self._phase = "failed"
            self._dispose_episode()
            raise

        self._phase = "active"
        self.last_observe = observe
        info = self._base_info(observe.observation, observe.state, observe.state_name, observe.step_count)
        info["consumed_tick"] = None
        return observation_to_gym(observe.observation), info

    def step(self, action: Mapping[str, Any]):
        if self._phase != "active":
            raise BattleShipEnvError(f"step() requires an active episode (phase is {self._phase}); call reset()")
        native = action_to_native(action)  # ValueError before anything is sent
        episode = self._episode
        assert episode is not None and episode.client is not None

        try:
            result = episode.client.step(native.buttons, native.stick_x, native.stick_y)
        except BattleShipError as exc:
            failure = episode.classify_step_failure(exc)
            self._phase = "failed"
            self._dispose_episode()
            raise failure from exc

        self._steps += 1
        self.last_step_result = result
        observation = observation_to_gym(result.observation)
        info = self._base_info(result.observation, result.state, result.state_name, result.step_count)
        info["consumed_tick"] = result.consumed_tick
        info["native_action"] = native

        terminated = result.state == StepState.EPISODE_ENDED
        truncated = False
        if terminated:
            # Native terminal state: the authoritative EpisodeEnded result of
            # M1c. The existing M2 finish path waits for the deferred clean
            # exit and validates the result JSON; the observation above is
            # already in the caller's hands whatever happens next.
            self._phase = "terminated"
            try:
                done = episode.finish(result)
            except EpisodeFailure:
                self._phase = "failed"
                self._dispose_episode()
                raise
            self.last_episode_exit = done
            info["exit_code"] = done.exit_code
            info["result"] = done.result
            info["result_path"] = str(done.result_path)
            info["cleanup_action"] = self._dispose_episode()
        elif self.max_episode_steps is not None and self._steps >= self.max_episode_steps:
            # Python-owned bound, never a native outcome: the parked process
            # is disposed of right here so a caller that stops stepping
            # cannot leak it.
            truncated = True
            self._phase = "truncated"
            info["truncation_reason"] = "max_episode_steps"
            info["cleanup_action"] = self._dispose_episode()

        return observation, PLACEHOLDER_REWARD, terminated, truncated, info

    def render(self):
        raise NotImplementedError("BattleShipBTTEnv has no render mode; BattleShip draws its own window")

    def close(self):
        """Idempotent. Safe before reset, mid-episode, after a terminal or
        truncated episode, after a failed reset or step, and repeatedly."""
        if self._phase == "closed":
            return
        self._phase = "closed"
        self._dispose_episode()

    # -- internals ---------------------------------------------------------------------------------

    def _dispose_episode(self) -> Optional[str]:
        episode, self._episode = self._episode, None
        if episode is None:
            return None
        return episode.close()  # M2: already_exited / terminated / killed, or raises cleanup_failure

    @staticmethod
    def _require_initial(fresh_step_count: int, observe: Observe, episode: BattleShipEpisode) -> None:
        """The initial observation must be the pre-tick-0 snapshot of a fresh episode."""
        problems = []
        if observe.state != StepState.WAITING_FOR_ACTION or not observe.can_step:
            problems.append(f"state {observe.state_name} can_step={observe.can_step}")
        if observe.step_count != 0 or fresh_step_count != 0:
            problems.append(f"step_count {observe.step_count} (fresh status said {fresh_step_count})")
        if observe.observation.input_tick != 0:
            problems.append(f"input_tick {observe.observation.input_tick} (tick 0 must not have been consumed)")
        if observe.observation.btt_active != 1:
            problems.append(f"btt_active {observe.observation.btt_active}")
        if problems:
            raise EpisodeFailure(
                EpisodeOutcome.NOT_FRESH,
                "initial observation is not the fresh pre-tick-0 state: " + "; ".join(problems),
                episode=episode,
            )

    def _base_info(self, observation: Observation, state: StepState, state_name: str, step_count: int) -> Dict[str, Any]:
        episode = self._episode
        return {
            "protocol": PROTOCOL_VERSION,
            "env_contract": ENV_CONTRACT,
            "observation_schema": observation.observation_schema,
            "state": int(state),
            "state_name": state_name,
            "step_count": step_count,
            "input_tick": observation.input_tick,
            "time_passed": observation.time_passed,
            "targets_remaining": observation.targets_remaining,
            "native_observation": observation,
            "episode_index": self._episode_index,
            "pid": episode.pid if episode is not None else None,
            "port": episode.port if episode is not None else None,
            "episode_dir": str(episode.paths.directory) if episode is not None and episode.paths else None,
        }
