"""M7q: reader of the native `btt_input_state_v1` diagnostic (SSB64_RL_INPUT=1): the player fighter's latched
controller state after the game's own R -> A+Z fold, the stick tap / hold counters, the Z-cancel timer, the animation
frame and playback speed and motion flag 1. Strict parse (every key checked), typed snapshot, and the numerical
invariants a valid stream must satisfy. The `input` object is additive and separate from `btt_entity_v1`: with the
flag unset a reply is byte-identical to the M7n executable's.

Everything here is a full native value (no cap, no scale); rl/m7q_obs.py applies the bounded policy encodings.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

INPUT_ENV = "SSB64_RL_INPUT"
CONTRACT = "btt_input_state_v1"
SCHEMA = 1
REPLY_KEY = "input"
STATUS_KEY = "input_diag"

# N64 button word bits (port/rl/rl.h RL_BUTTON_*). R is folded into A | Z by ftMainProcUpdateInterrupt before the
# edge detection, so a held R always reads with A and Z set as well.
BUTTON_A, BUTTON_B, BUTTON_Z, BUTTON_L, BUTTON_R = 0x8000, 0x4000, 0x2000, 0x0020, 0x0010
BUTTON_C_UP, BUTTON_C_DOWN, BUTTON_C_LEFT, BUTTON_C_RIGHT = 0x0008, 0x0004, 0x0002, 0x0001
CONTRACT_BUTTONS = (BUTTON_A, BUTTON_B, BUTTON_Z, BUTTON_L, BUTTON_R, BUTTON_C_UP, BUTTON_C_LEFT)   # the 7 hold bits
CONTRACT_BUTTON_MASK = sum(CONTRACT_BUTTONS)
FORBIDDEN_BUTTON_MASK = 0xFFFF & ~CONTRACT_BUTTON_MASK   # C-down, C-right, Start, D-pad: never in a Track 1 word

STICK_BAND = 20             # |stick| >= 20 enters the tap band (ftmain.c)
TAP_MAX = 254               # FTINPUT_STICKBUFFER_TICS_MAX: outside the band, forced stale, or a >= 254-tick hold
Z_TIMER_MAX = 65536         # FTINPUT_ZTRIGLAST_TICS_MAX: saturation and the reset value of an aerial start
Z_CANCEL_WINDOW = 10        # FTCOMMON_ATTACKAIR_SMOOTHLANDING_TICS_MAX: a landing cancels while the timer is <= 10


class InputError(ValueError):
    pass


@dataclass(frozen=True)
class InputSnapshot:
    input_tick: int
    scene_active: int
    live: int
    valid: int
    stick_x: int
    stick_y: int
    button_hold: int
    button_tap: int
    button_release: int
    tap_stick_x: int
    tap_stick_y: int
    hold_stick_x: int
    hold_stick_y: int
    tics_since_last_z: int
    anim_frame: float
    anim_speed: float
    motion_flag1: int


_KEYS = {"contract", "input_schema", "input_tick", "scene_active", "live", "valid", "stick_x", "stick_y",
         "button_hold", "button_tap", "button_release", "tap_stick_x", "tap_stick_y", "hold_stick_x",
         "hold_stick_y", "tics_since_last_z", "anim_frame", "anim_speed", "motion_flag1"}
_U32 = (0, 2 ** 32 - 1)
_S32 = (-2 ** 31, 2 ** 31 - 1)


def _int(v: Any, what: str, lo: Optional[int] = None, hi: Optional[int] = None) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        raise InputError(f"{what}: expected an integer, got {v!r}")
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        raise InputError(f"{what}: {v} outside [{lo}, {hi}]")
    return v


def _num(v: Any, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise InputError(f"{what}: expected a number, got {v!r}")
    return float(v)


def parse_input(obj: Any) -> InputSnapshot:
    if not isinstance(obj, dict):
        raise InputError("input: expected an object")
    if set(obj) != _KEYS:
        raise InputError(f"input: keys {sorted(set(obj) ^ _KEYS)} unexpected or missing")
    if obj["contract"] != CONTRACT or _int(obj["input_schema"], "input_schema") != SCHEMA:
        raise InputError(f"input: contract {obj['contract']!r} schema {obj['input_schema']!r}")
    return InputSnapshot(
        input_tick=_int(obj["input_tick"], "input_tick", *_U32),
        scene_active=_int(obj["scene_active"], "scene_active", 0, 1), live=_int(obj["live"], "live", 0, 1),
        valid=_int(obj["valid"], "valid", 0, 1),
        stick_x=_int(obj["stick_x"], "stick_x", -128, 127), stick_y=_int(obj["stick_y"], "stick_y", -128, 127),
        button_hold=_int(obj["button_hold"], "button_hold", 0, 0xFFFF),
        button_tap=_int(obj["button_tap"], "button_tap", 0, 0xFFFF),
        button_release=_int(obj["button_release"], "button_release", 0, 0xFFFF),
        tap_stick_x=_int(obj["tap_stick_x"], "tap_stick_x", 0, 255),
        tap_stick_y=_int(obj["tap_stick_y"], "tap_stick_y", 0, 255),
        hold_stick_x=_int(obj["hold_stick_x"], "hold_stick_x", 0, 255),
        hold_stick_y=_int(obj["hold_stick_y"], "hold_stick_y", 0, 255),
        tics_since_last_z=_int(obj["tics_since_last_z"], "tics_since_last_z", *_S32),
        anim_frame=_num(obj["anim_frame"], "anim_frame"), anim_speed=_num(obj["anim_speed"], "anim_speed"),
        motion_flag1=_int(obj["motion_flag1"], "motion_flag1", *_U32))


def input_of(reply: Mapping[str, Any]) -> InputSnapshot:
    """The parsed input object of an observe or step reply; InputError when absent."""
    if REPLY_KEY not in reply:
        raise InputError(f"reply {reply.get('op')!r} has no {REPLY_KEY!r} object (is {INPUT_ENV}=1 effective?)")
    return parse_input(reply[REPLY_KEY])


def require_input_status(status: Mapping[str, Any]) -> None:
    if status.get(STATUS_KEY) is not True:
        raise InputError(f"status reply lacks {STATUS_KEY}: true (the process was not booted with {INPUT_ENV}=1)")


def fold_buttons(word: int) -> int:
    """The game's own fold (ftmain.c ftMainProcUpdateInterrupt): a held R also sets A and Z."""
    return (word | BUTTON_A | BUTTON_Z) if word & BUTTON_R else word


def check_snapshot(snap: InputSnapshot, observation: Mapping[str, Any], *, prev: Optional[InputSnapshot] = None,
                   prev_observation: Optional[Mapping[str, Any]] = None) -> List[str]:
    """Numerical invariants of one input snapshot against the observation it is paired with (and the previous
    snapshot of the same episode, when given). Returns problem strings (empty = all hold).

    * pairing: input_tick equals the observation's; live implies scene_active; valid iff the observation's fighter is
      valid (while live);
    * word: no forbidden button bit (C-down, C-right, Start, D-pad cannot come from the Track 1 / M3 action domain);
      the fold holds (R set => A and Z set); tap and release edges are subsets of the fold-consistent domain;
    * stick: inside [-80, 80] (the game's clamp);
    * tap counters: never 0 (initialised to 254, set to 1, incremented with a cap, or forced to 254: ftmain.c,
      ftmanager.c:1005); a counter outside the band reads exactly 254; hold counters likewise;
    * Z timer: 0 <= t <= 65536; between consecutive replies it is 0, prev + 1 (capped), or 65536 (an aerial start /
      damage / ledge reset);
    * anim_speed >= 0, finite; anim_frame finite."""
    p: List[str] = []
    if snap.input_tick != int(observation["input_tick"]):
        p.append(f"input_tick {snap.input_tick} != observation {observation['input_tick']}")
    if snap.live and not snap.scene_active:
        p.append("live without scene_active")
    if not snap.live:
        return p
    if int(observation.get("fighter_valid", 0)) != snap.valid:
        p.append(f"valid {snap.valid} vs observation fighter_valid {observation.get('fighter_valid')}")
    if not snap.valid:
        return p
    if snap.button_hold & FORBIDDEN_BUTTON_MASK:
        p.append(f"button_hold 0x{snap.button_hold:04x} has a forbidden bit")
    if fold_buttons(snap.button_hold) != snap.button_hold:
        p.append(f"button_hold 0x{snap.button_hold:04x} violates the R -> A+Z fold")
    if (snap.button_tap | snap.button_release) & FORBIDDEN_BUTTON_MASK:
        p.append("button_tap / button_release has a forbidden bit")
    if not (-80 <= snap.stick_x <= 80 and -80 <= snap.stick_y <= 80):
        p.append(f"stick ({snap.stick_x}, {snap.stick_y}) outside the clamp")
    for name, tap, hold, stick in (("x", snap.tap_stick_x, snap.hold_stick_x, snap.stick_x),
                                   ("y", snap.tap_stick_y, snap.hold_stick_y, snap.stick_y)):
        if tap == 0 or hold == 0:
            p.append(f"tap/hold_stick_{name} is 0 (impossible per source)")
        if tap > TAP_MAX or hold > TAP_MAX:
            p.append(f"tap/hold_stick_{name} above {TAP_MAX}")
        if abs(stick) < STICK_BAND and (tap != TAP_MAX or hold != TAP_MAX):
            p.append(f"stick_{name} {stick} outside the band but tap {tap} / hold {hold} != {TAP_MAX}")
    if not (0 <= snap.tics_since_last_z <= Z_TIMER_MAX):
        p.append(f"tics_since_last_z {snap.tics_since_last_z} outside [0, {Z_TIMER_MAX}]")
    if prev is not None and prev.live and prev.valid and prev_observation is not None:
        t0, t1 = prev.tics_since_last_z, snap.tics_since_last_z
        if t1 not in (0, min(t0 + 1, Z_TIMER_MAX), Z_TIMER_MAX):
            p.append(f"tics_since_last_z {t0} -> {t1} is neither 0, +1 nor the reset")
    if snap.anim_speed < 0.0 or snap.anim_speed != snap.anim_speed:
        p.append(f"anim_speed {snap.anim_speed}")
    if snap.anim_frame != snap.anim_frame:
        p.append("anim_frame is NaN")
    return p


def expected_hold_word(buttons: int) -> int:
    """The button_hold the game latches for a submitted native action word (the fold applied)."""
    return fold_buttons(int(buttons) & 0xFFFF)


def expected_taps(prev_hold: int, hold: int) -> int:
    return hold & ~prev_hold & 0xFFFF


def expected_releases(prev_hold: int, hold: int) -> int:
    return prev_hold & ~hold & 0xFFFF


def step_tap_counter(prev_counter: int, prev_stick: int, stick: int) -> int:
    """One tick of the ftmain.c tap-counter rule for one axis (no forced reset): 1 on band entry (including a sign
    reversal), prev + 1 capped at 254 while inside, 254 outside."""
    inside = abs(stick) >= STICK_BAND
    if not inside:
        return TAP_MAX
    same_side = (stick >= STICK_BAND and prev_stick >= STICK_BAND) or (stick <= -STICK_BAND and prev_stick <= -STICK_BAND)
    if same_side:
        return min(prev_counter + 1, TAP_MAX)
    return 1


def describe() -> Dict[str, Any]:
    return {"contract": CONTRACT, "schema": SCHEMA, "env": f"{INPUT_ENV}=1", "reply_key": REPLY_KEY,
            "status_key": STATUS_KEY,
            "fields": ["stick_x", "stick_y", "button_hold", "button_tap", "button_release", "tap_stick_x",
                       "tap_stick_y", "hold_stick_x", "hold_stick_y", "tics_since_last_z", "anim_frame", "anim_speed",
                       "motion_flag1"],
            "capture": "GamePostUpdateEvent after the update that consumed the paired action: the state after that "
                       "action was applied, stamped with the paired observation's input_tick",
            "button_fold": "R sets A and Z (ftmain.c ftMainProcUpdateInterrupt); the R bit stays set",
            "tap_counters": f"1 on entry into the |stick| >= {STICK_BAND} band (incl. sign reversal), +1 per tick inside "
                            f"(capped {TAP_MAX}), {TAP_MAX} outside; forced to {TAP_MAX} by dash / jump / fast fall / pass; "
                            "never 0 after fighter creation",
            "z_timer": f"0 on a Z or R tap, +1 per tick, saturates at {Z_TIMER_MAX}; set to {Z_TIMER_MAX} when an aerial "
                       f"attack starts, after damage and after a ledge drop; a landing from an armed aerial cancels its "
                       f"lag while the timer is <= {Z_CANCEL_WINDOW}"}
