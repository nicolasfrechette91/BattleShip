"""M8-rd: the cell contract `m8_rd_cell_v1`, the per-tick record and its chain digest, and the burst scanner.

Pure (standard library only, no game, no torch). Design: docs/rl_m8_rd_proposal_2026-10-01.md (revision 2) section 4 and
section 7.3, as amended by docs/rl_m8_rd_amendment_2026-10-02.md.

A cell key is computed from ONE raw reply produced with SSB64_RL_SPATIAL=1, on live steps only (`btt_active == 1` and
`fighter_valid == 1`):

    (bx, by, res, mask, floor)
      bx, by  floor(position / 300), grid origin = world origin, no clipping
      res     G  grounded; A2 airborne with double jump and up-B available; A1 airborne, up-B available, no double jump;
              A0 airborne without up-B (class special_hi or helpless); X damage / dead / appear / other / unmapped
      mask    the 10-bit live-target mask (spatial.target_live_mask)
      floor   the native floor line id when res == G, else -1

No RNG, no clock, no velocity. The record of a tick (observation without host_frame, the spatial fighter block, groups,
target_live_mask, target_positions, reply state and step_count) is canonicalised to JSON; the chain digest is
h_i = sha256(h_{i-1} || sha256(canonical(record_i))).
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

CELL_CONTRACT = "m8_rd_cell_v1"
RECORD_CONTRACT = "m8_rd_record_v1"
CHAIN_TAG = b"m8_rd_chain_v1\x00"
CELL_SIZE = 300
HORIZON = 3600
TARGETS_TOTAL = 10
GAME_STATUS_END = 5                       # btt_parallel.GAME_STATUS_END
STATE_WAITING = 2                         # StepState.WAITING_FOR_ACTION
STATE_ENDED = 6                           # StepState.EPISODE_ENDED
FIGHTER_CHARACTER = "mario"

RES_GROUNDED, RES_A2, RES_A1, RES_A0, RES_X = "G", "A2", "A1", "A0", "X"
RESOURCE_CLASSES = (RES_GROUNDED, RES_A2, RES_A1, RES_A0, RES_X)
X_STATUS_CLASSES = ("damage", "dead", "appear_entry", "other", "unmapped")
A0_STATUS_CLASSES = ("special_hi", "helpless")
NO_FLOOR = -1

# the 17 observation fields of the M1b snapshot, in wire order (rl/m7h_curriculum.OBSERVATION_FIELDS)
OBS_FIELDS: Tuple[str, ...] = ("observation_schema", "host_frame", "input_tick", "time_passed", "game_status", "btt_active",
                               "targets_remaining", "fighter_valid", "position_x", "position_y", "air_velocity_x",
                               "air_velocity_y", "ground_velocity_x", "facing_direction", "ground_air_state",
                               "fighter_status_id", "jumps_used")
OBS_INDEX = {k: i for i, k in enumerate(OBS_FIELDS)}
OBS_NO_HOST: Tuple[str, ...] = tuple(k for k in OBS_FIELDS if k != "host_frame")
HOST_FRAME = OBS_INDEX["host_frame"]
I_INPUT_TICK, I_X, I_Y, I_VX = OBS_INDEX["input_tick"], OBS_INDEX["position_x"], OBS_INDEX["position_y"], OBS_INDEX["air_velocity_x"]

# stage facts the milestone labels use (decoded stage table, rl/m7g_spatial.EXPECTED_LINES)
LEFT_BOUNDARY_X = -2100.0                 # strict, the M7g-a / btt_eval_metrics_v1 left-region rule
L0_FLOOR_LINE = 0                         # the wall top
LEFT_FLOOR_LINES = (3,)                   # the only left-side floor line
LEFT_TARGET_IDS = (1, 6, 8)

# Track 1 (`btt_s9_b8_v1`): word index = stick * 8 + button; the canonical native triple is the replay truth.
TRACK1_CONTRACT = "btt_s9_b8_v1"
STICK_TABLE: Tuple[Tuple[int, int], ...] = ((0, 0), (80, 0), (80, 80), (0, 80), (-80, 80), (-80, 0), (-80, -80), (0, -80),
                                            (80, -80))
BUTTON_TABLE: Tuple[int, ...] = (0x0000, 0x8000, 0x4000, 0x0008, 0x0002, 0x0020, 0x0010, 0x2000)
BUTTON_NAMES: Tuple[str, ...] = ("none", "A", "B", "C-up", "C-left", "L", "R", "Z")
TRACK1_WORDS = len(STICK_TABLE) * len(BUTTON_TABLE)       # 72
TRIPLES: Tuple[Tuple[int, int, int], ...] = tuple((BUTTON_TABLE[w % 8], STICK_TABLE[w // 8][0], STICK_TABLE[w // 8][1])
                                                  for w in range(TRACK1_WORDS))


class CellError(RuntimeError):
    """A reply that violates the cell contract (an integrity problem, never tolerated silently)."""


def triple(word: int) -> Tuple[int, int, int]:
    return TRIPLES[int(word)]


def track1_digest() -> str:
    d = {"contract": TRACK1_CONTRACT, "stick_table": [list(s) for s in STICK_TABLE], "button_table": list(BUTTON_TABLE),
         "button_names": list(BUTTON_NAMES), "word_index": "stick * 8 + button"}
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def native_digest(rows: Sequence[Tuple[int, int, int, int]]) -> str:
    """The M7 native_action_digest: sha256 over 'buttons,stick_x,stick_y,consumed_tick' lines."""
    h = hashlib.sha256()
    for b, x, y, t in rows:
        h.update(f"{int(b)},{int(x)},{int(y)},{int(t)}\n".encode("ascii"))
    return h.hexdigest()


def words_digest(words: bytes) -> str:
    """native_action_digest of a tick-0 word sequence (row i consumes tick i)."""
    return native_digest([(*TRIPLES[w], i) for i, w in enumerate(words)])


def contract_digest() -> str:
    d = {"contract": CELL_CONTRACT, "cell_size": CELL_SIZE, "key": ["bx", "by", "res", "mask", "floor"],
         "resource_classes": list(RESOURCE_CLASSES), "x_status_classes": list(X_STATUS_CLASSES),
         "a0_status_classes": list(A0_STATUS_CLASSES), "no_floor": NO_FLOOR, "live": "btt_active == 1 and fighter_valid == 1",
         "grounded": "ground_air_state == 0", "double_jump_available": "jumps_used < 2",
         "record": {"contract": RECORD_CONTRACT, "keys": ["o (observation without host_frame)", "f (spatial fighter)",
                                                          "g (spatial groups)", "m (target_live_mask)",
                                                          "p (target_positions)", "s (state)", "n (step_count)"],
                    "tick0_extra": "l: sha256 of the canonical observe-only collision line table"},
         "chain": "h_0 = sha256(tag || canonical(record_0)); h_i = sha256(h_{i-1} || sha256(canonical(record_i)))",
         "chain_tag": CHAIN_TAG.decode("ascii").strip("\x00"), "track1": track1_digest(),
         "labels": {"left_boundary_x": LEFT_BOUNDARY_X, "l0_floor_line": L0_FLOOR_LINE, "left_floor_lines": list(LEFT_FLOOR_LINES),
                    "left_target_ids": list(LEFT_TARGET_IDS)}}
    return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


# -- status classes ------------------------------------------------------------------------------------------------------


class Classifier:
    """fighter_status_id -> btt_action_class_table_v2 class name for one character (Mario validated). Loads the checked-in
    table (digest verified); an id outside the table is the explicit class `unmapped`, counted."""

    def __init__(self, table: Optional[Mapping[str, Any]] = None, character: str = FIGHTER_CHARACTER):
        import m7q_status_table as st

        table = dict(table) if table is not None else st.load_table()
        if table.get("table_id") != st.TABLE_ID or table.get("sha256") != st.table_digest(table):
            raise CellError(f"status table is not a valid {st.TABLE_ID}")
        if character not in table["characters"]:
            raise CellError(f"no status table for character {character!r}")
        self.table_id = table["table_id"]
        self.table_sha256 = table["sha256"]
        self.character = character
        self.validated = bool(table["characters"][character]["validated"])
        by_id: Dict[int, str] = {int(k): v for k, v in table["common"].items()}
        by_id.update({int(k): v for k, v in table["characters"][character]["ids"].items()})
        self._by_id = by_id
        self.unmapped_seen: Dict[int, int] = {}

    def name(self, status_id: int) -> str:
        c = self._by_id.get(int(status_id))
        if c is None:
            self.unmapped_seen[int(status_id)] = self.unmapped_seen.get(int(status_id), 0) + 1
            return "unmapped"
        return c


# -- the key -----------------------------------------------------------------------------------------------------------


def popcount(mask: int) -> int:
    return bin(int(mask)).count("1")


def is_live(o: Mapping[str, Any]) -> bool:
    return int(o["btt_active"]) == 1 and int(o["fighter_valid"]) == 1


def is_native_failure(o: Mapping[str, Any], state: int) -> bool:
    """btt_native_failure_v1 on one post-update reply (btt_parallel.is_native_failure)."""
    return (int(state) != STATE_ENDED and int(o["btt_active"]) == 1 and int(o["game_status"]) == GAME_STATUS_END
            and int(o["targets_remaining"]) > 0)


def resource_class(o: Mapping[str, Any], status_class: str) -> str:
    """G / A2 / A1 / A0 / X (section 4.1). X takes precedence over the ground / air split: a damage, dead, appear, other
    or unmapped status is X in either state."""
    if status_class in X_STATUS_CLASSES:
        return RES_X
    if int(o["ground_air_state"]) == 0:
        return RES_GROUNDED
    if status_class in A0_STATUS_CLASSES:
        return RES_A0
    return RES_A2 if int(o["jumps_used"]) < 2 else RES_A1


def cell_key(o: Mapping[str, Any], sp: Mapping[str, Any], clf: Classifier) -> Optional[Tuple[int, int, str, int, int]]:
    """The m8_rd_cell_v1 key of one reply's observation + spatial object, or None when the step is not live."""
    if not is_live(o):
        return None
    mask = int(sp["target_live_mask"])
    if popcount(mask) != int(o["targets_remaining"]):
        raise CellError(f"target_live_mask {mask:#x} disagrees with targets_remaining {o['targets_remaining']}")
    res = resource_class(o, clf.name(o["fighter_status_id"]))
    floor = int(sp["fighter"]["floor_line_id"]) if res == RES_GROUNDED else NO_FLOOR
    return (math.floor(float(o["position_x"]) / CELL_SIZE), math.floor(float(o["position_y"]) / CELL_SIZE), res, mask, floor)


def level_of_mask(mask: int) -> int:
    """Progress level: targets broken."""
    return TARGETS_TOTAL - popcount(mask)


def obs_tuple(o: Mapping[str, Any]) -> Tuple[Any, ...]:
    """The 17 observation values in OBS_FIELDS order (host_frame included, at HOST_FRAME)."""
    return tuple(o[k] for k in OBS_FIELDS)


def obs_dict(t: Sequence[Any]) -> Dict[str, Any]:
    return {k: v for k, v in zip(OBS_FIELDS, t)}


def obs_diffs(a: Sequence[Any], b: Sequence[Any], ignore: Sequence[int] = (HOST_FRAME,)) -> Dict[str, Tuple[Any, Any]]:
    """Field differences of two observation tuples, exact in value and in JSON type (1 != 1.0); host_frame is ignored."""
    return {OBS_FIELDS[i]: (a[i], b[i]) for i in range(len(OBS_FIELDS))
            if i not in ignore and (a[i] != b[i] or type(a[i]) is not type(b[i]))}


# -- record, canonical form, chain -------------------------------------------------------------------------------------------


def record_of(reply: Mapping[str, Any]) -> Dict[str, Any]:
    """The per-tick record of one raw step or observe reply (references into the reply, nothing copied)."""
    o, sp = reply["observation"], reply["spatial"]
    return {"o": {k: o[k] for k in OBS_NO_HOST}, "f": sp["fighter"], "g": sp["groups"], "m": sp["target_live_mask"],
            "p": sp["target_positions"], "s": reply["state"], "n": reply["step_count"]}


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def record_digest(rec: Mapping[str, Any]) -> bytes:
    return hashlib.sha256(canonical(rec)).digest()


def tick0_record(observe_reply: Mapping[str, Any]) -> Dict[str, Any]:
    """The tick-0 record of a non-consuming `observe` reply: the per-tick record plus the digest of the observe-only
    collision line table."""
    rec = record_of(observe_reply)
    rec["l"] = hashlib.sha256(canonical(observe_reply["spatial"]["lines"])).hexdigest()
    return rec


def chain_start(rec0: Mapping[str, Any]) -> bytes:
    return hashlib.sha256(CHAIN_TAG + canonical(rec0)).digest()


def chain_next(prev: bytes, rd: bytes) -> bytes:
    return hashlib.sha256(prev + rd).digest()


# -- the burst scanner ---------------------------------------------------------------------------------------------------------


class BurstScanner:
    """Per-tick event detection over the post-prefix part of one trajectory (the milestone labels of section 11.2).

    `feed(j, o, sp, state)` takes the reply of tick j (j = input_tick, 1-based count of native ticks consumed). It records,
    for ticks fed:
      breaks       [(j, target id)] from the live-target mask (a mask bit that cleared)
      t_events     [(j, t)] each time the number broken rises (t = targets broken after that tick)
      first        l0 (grounded live tick on floor line 0), left_live (live x < -2100), left_floor (grounded live tick on
                   a left-side floor line), left_break (a left target broke), clear (native EpisodeEnded with 0 left)
    Every event is first-occurrence within the scanned part, except breaks and t_events which are complete."""

    def __init__(self, start_mask: int):
        self.mask = int(start_mask)
        self.t = level_of_mask(self.mask)
        self.breaks: List[Tuple[int, int]] = []
        self.t_events: List[Tuple[int, int]] = []
        self.first: Dict[str, Optional[int]] = {"l0": None, "left_live": None, "left_floor": None, "left_break": None,
                                                "clear": None}
        self.min_x_high: Optional[float] = None

    def feed(self, j: int, o: Mapping[str, Any], sp: Mapping[str, Any], state: int) -> None:
        mask = int(sp["target_live_mask"])
        if mask != self.mask:
            cleared = self.mask & ~mask
            if mask & ~self.mask:
                raise CellError(f"a target reappeared at tick {j}: {self.mask:#x} -> {mask:#x}")
            for i in range(TARGETS_TOTAL):
                if (cleared >> i) & 1:
                    self.breaks.append((j, i))
                    if i in LEFT_TARGET_IDS and self.first["left_break"] is None:
                        self.first["left_break"] = j
            self.mask = mask
            self.t = level_of_mask(mask)
            self.t_events.append((j, self.t))
        if is_live(o):
            x = float(o["position_x"])
            if x < LEFT_BOUNDARY_X and self.first["left_live"] is None:
                self.first["left_live"] = j
            if int(o["ground_air_state"]) == 0:
                fl = int(sp["fighter"]["floor_line_id"])
                if fl == L0_FLOOR_LINE and self.first["l0"] is None:
                    self.first["l0"] = j
                if fl in LEFT_FLOOR_LINES and self.first["left_floor"] is None:
                    self.first["left_floor"] = j
        if int(state) == STATE_ENDED and int(o["btt_active"]) == 1 and int(o["targets_remaining"]) == 0 \
                and self.first["clear"] is None:
            self.first["clear"] = j

    def labels(self) -> Dict[str, Any]:
        return {"t": self.t, "breaks": list(self.breaks), "t_events": list(self.t_events), "first": dict(self.first)}
