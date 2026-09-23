"""M7g-b: strict reader for the opt-in structured-spatial diagnostic `btt_spatial_v1` (SSB64_RL_SPATIAL=1).

The native side (decomp sc1pbonusstage.c rlGameFillSpatial, PORT only; port/rl/rl_spatial.cpp) adds a top-level
`"spatial"` object to observe and step replies, paired with the reply's observation exactly like the M7f `"targets"`
object, and `"spatial_diag": true` to status. It carries:

  * `lines` (observe replies only): the collision line table, vertices as stored (local to their yakumono group);
  * `groups`: per yakumono group the DObj status, whether the game translates its vertices, translate and the
    last-update speed (group 2 is the moving platform);
  * `fighter`: Mario's MPCollData contact state;
  * `target_live_mask` / `target_positions`: the live position of every unbroken target under the M7f stable ID.

This module parses that object strictly (exact key sets, JSON types), turns the line table into world-space
segments with the game's own translate rule, pins the expected static line table of Mario's stage, and checks the
per-reply native invariants used by the M7g-b validation. It is pure: no process, no file writes, no torch.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Sequence, Tuple

import numpy as np

SPATIAL_ENV = "SSB64_RL_SPATIAL"
CONTRACT = "btt_spatial_v1"
SCHEMA = 1
REPLY_KEY = "spatial"
STATUS_KEY = "spatial_diag"

MAX_GROUPS = 4
MAX_LINES = 32
MAX_LINE_VERTICES = 4
TARGET_COUNT = 10

# port/rl/rl.h RL_SPATIAL_* (cross-checked against the decomp enums at compile time in sc1pbonusstage.c)
LINE_FLOOR, LINE_CEIL, LINE_RWALL, LINE_LWALL = 0, 1, 2, 3
LINE_TYPE_NAMES = ("floor", "ceil", "rwall", "lwall")
VERTEX_PASS = 0x4000
VERTEX_CLIFF = 0x8000
CONTACT_LWALL, CONTACT_RWALL, CONTACT_CEIL, CONTACT_FLOOR = 0x0001, 0x0020, 0x0400, 0x0800
GROUP_STATUS_NONE, GROUP_STATUS_OFF = 0, 3
ANOMALY_BITS = {0: "group_overflow", 1: "line_overflow", 2: "vertex_overflow", 3: "bad_group", 4: "target_mismatch"}

# Mario's Break the Targets (US), read natively and identical to the decomp stage source
# decomp/src/relocData/124_GRBonus1MarioFile2.c (rl/m7g_obs_tests.py unit_stage_table checks it against a decode of
# that source and against every native table captured in M7g-b):
# (line id, type, group, flags, vertices as stored). Group 2 is local to the moving platform's DObj.
EXPECTED_LINES: Tuple[Tuple[int, int, int, int, Tuple[Tuple[float, float], ...]], ...] = (
    (0, LINE_FLOOR, 1, 0, ((-2100.0, 3000.0), (-1200.0, 3000.0))),
    (1, LINE_FLOOR, 1, 0, ((2100.0, -450.0), (3300.0, -450.0))),
    (2, LINE_FLOOR, 1, VERTEX_PASS, ((2100.0, -1500.0), (1200.0, -1500.0))),
    (3, LINE_FLOOR, 1, 0, ((-3900.0, -1950.0), (-2700.0, -1950.0))),
    (4, LINE_FLOOR, 1, 0, ((-1800.0, -2550.0), (2100.0, -2550.0))),
    (5, LINE_CEIL, 1, 0, ((-3600.0, -4050.0), (-3900.0, -4050.0))),
    (6, LINE_CEIL, 1, 0, ((2400.0, -2850.0), (-2100.0, -2850.0))),
    (7, LINE_CEIL, 1, 0, ((-3000.0, -2250.0), (-3900.0, -2250.0))),
    (8, LINE_CEIL, 1, 0, ((3300.0, -750.0), (2400.0, -750.0))),
    (9, LINE_CEIL, 1, 0, ((-1200.0, 2700.0), (-1800.0, 2700.0))),
    (10, LINE_RWALL, 1, 0, ((3300.0, -450.0), (3300.0, -750.0))),
    (11, LINE_RWALL, 1, 0, ((2400.0, -750.0), (2400.0, -2850.0))),
    (12, LINE_RWALL, 1, 0, ((-1200.0, 3000.0), (-1200.0, 2700.0))),
    (13, LINE_RWALL, 1, 0, ((-1800.0, 2700.0), (-1800.0, -2550.0))),
    (14, LINE_RWALL, 1, 0, ((-2700.0, -1950.0), (-2700.0, -2850.0), (-3600.0, -3750.0), (-3600.0, -4050.0))),
    (15, LINE_LWALL, 1, 0, ((-3900.0, -2250.0), (-3900.0, -1950.0))),
    (16, LINE_LWALL, 1, 0, ((-3900.0, -4050.0), (-3900.0, -3750.0), (-3000.0, -2850.0), (-3000.0, -2250.0))),
    (17, LINE_LWALL, 1, 0, ((-2100.0, -2850.0), (-2100.0, 3000.0))),
    (18, LINE_LWALL, 1, 0, ((2100.0, -2550.0), (2100.0, -450.0))),
    (19, LINE_FLOOR, 2, VERTEX_PASS, ((600.0, 300.0), (-600.0, 300.0))),
)
PLATFORM_GROUP = 2
PLATFORM_LINE = 19
PLATFORM_TRANSLATE_X = 2700.0
PLATFORM_TRANSLATE_Y_RANGE = (1500.0, 3300.0)   # DObj translate; the standable surface is 300 higher
MOVING_TARGET_ID = 2
MOVING_TARGET_OFFSET_Y = 600.0                    # measured: target 2 centre = platform translate + 600 every tick,
MOVING_TARGET_TOLERANCE = 0.01                    # to within float32 rounding (the two animations are evaluated
                                                  # separately; observed deviations are single ulps, <= 0.0005)
MAP_BOUNDS = (9600, -9600, 9600, -9600)           # blast zones: top, bottom, right, left
CAMERA_BOUNDS = (5000, -5000, 5000, -5000)


class SpatialError(ValueError):
    """A reply's spatial object is missing or not a valid btt_spatial_v1 object."""


@dataclass(frozen=True)
class SpatialGroup:
    id: int
    present: int
    status: int
    translated: int
    translate: Tuple[float, float]
    speed: Tuple[float, float]


@dataclass(frozen=True)
class SpatialLine:
    id: int
    type: int
    group: int
    flags: int
    vertex_total: int
    vertices: Tuple[Tuple[float, float], ...]


@dataclass(frozen=True)
class SpatialFighter:
    valid: int
    floor_line_id: int
    ceil_line_id: int
    lwall_line_id: int
    rwall_line_id: int
    mask_curr: int
    floor_dist: float
    carry: Tuple[float, float]
    coll: Tuple[float, float, float, float]


@dataclass(frozen=True)
class SpatialSnapshot:
    input_tick: int
    scene_active: int
    live: int
    update_tic: int
    anomaly_flags: int
    map_bounds: Tuple[int, int, int, int]
    camera_bounds: Tuple[int, int, int, int]
    groups: Tuple[SpatialGroup, ...]
    fighter: Optional[SpatialFighter]      # None only from a lean parse (key set checked, values not read)
    target_live_mask: int
    target_positions: Tuple[Tuple[float, float], ...]
    lines: Optional[Tuple[SpatialLine, ...]]

    def group(self, gid: int) -> Optional[SpatialGroup]:
        return self.groups[gid] if 0 <= gid < len(self.groups) else None


# -- strict parsing ---------------------------------------------------------------------------------------------

_TOP_KEYS = {"contract", "spatial_schema", "input_tick", "scene_active", "live", "update_tic", "anomaly_flags",
             "map_bounds", "camera_bounds", "groups", "fighter", "target_live_mask", "target_positions"}
_GROUP_KEYS = {"id", "present", "status", "translated", "translate", "speed"}
_FIGHTER_KEYS = {"valid", "floor_line_id", "ceil_line_id", "lwall_line_id", "rwall_line_id", "mask_curr",
                 "floor_dist", "carry", "coll"}
_LINE_KEYS = {"id", "type", "group", "flags", "vertex_total", "vertices"}
_TOP_KEYS_OBSERVE = _TOP_KEYS | {"lines"}


# Exact JSON types: json.loads yields int for integers and float for reals; `type(v) is int` also rejects booleans.
def _int(v: Any, what: str, lo: Optional[int] = None, hi: Optional[int] = None) -> int:
    if type(v) is not int:
        raise SpatialError(f"{what}: expected a JSON integer, got {v!r}")
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        raise SpatialError(f"{what}: {v} outside [{lo}, {hi}]")
    return v


def _num(v: Any, what: str) -> float:
    t = type(v)
    if t is float:
        if v - v != 0.0:                 # NaN or infinity
            raise SpatialError(f"{what}: expected a finite JSON number, got {v!r}")
        return v
    if t is int:
        return float(v)
    raise SpatialError(f"{what}: expected a finite JSON number, got {v!r}")


def _pair(v: Any, what: str) -> Tuple[float, float]:
    if type(v) is not list or len(v) != 2:
        raise SpatialError(f"{what}: expected [x, y], got {v!r}")
    return _num(v[0], what), _num(v[1], what)


def _keys(obj: Any, expected: Any, what: str) -> None:
    if type(obj) is not dict:
        raise SpatialError(f"{what}: expected an object")
    if obj.keys() != expected:
        raise SpatialError(f"{what}: keys {sorted(set(obj) ^ set(expected))} differ from the contract")


def parse_spatial(obj: Any, *, expect_lines: bool, lean: bool = False) -> SpatialSnapshot:
    """Parse one `spatial` object. expect_lines=True for observe replies (the line table is required), False for
    step replies (it must be absent). lean=True (the observation hot path) checks the fighter block's key set but
    neither reads nor type-checks its values (the observation does not use them; fighter is None); every other field
    is validated exactly as in the full parse."""
    _keys(obj, _TOP_KEYS_OBSERVE if expect_lines else _TOP_KEYS, "spatial")
    if obj["contract"] != CONTRACT or _int(obj["spatial_schema"], "spatial_schema") != SCHEMA:
        raise SpatialError(f"spatial: contract {obj['contract']!r} schema {obj['spatial_schema']!r}")
    u32 = (0, 2 ** 32 - 1)
    s32 = (-2 ** 31, 2 ** 31 - 1)
    mb, cb = obj["map_bounds"], obj["camera_bounds"]
    if not (isinstance(mb, list) and len(mb) == 4 and isinstance(cb, list) and len(cb) == 4):
        raise SpatialError("spatial: map_bounds / camera_bounds must be 4-integer lists")
    groups_raw = obj["groups"]
    if not isinstance(groups_raw, list) or len(groups_raw) > MAX_GROUPS:
        raise SpatialError("spatial.groups: expected a list of at most 4 groups")
    groups: List[SpatialGroup] = []
    for i, g in enumerate(groups_raw):
        _keys(g, _GROUP_KEYS, f"spatial.groups[{i}]")
        if _int(g["id"], "group.id") != i:
            raise SpatialError(f"spatial.groups[{i}]: id {g['id']} out of order")
        groups.append(SpatialGroup(id=i, present=_int(g["present"], "group.present", 0, 1),
                                   status=_int(g["status"], "group.status", *u32),
                                   translated=_int(g["translated"], "group.translated", 0, 1),
                                   translate=_pair(g["translate"], "group.translate"),
                                   speed=_pair(g["speed"], "group.speed")))
    f = obj["fighter"]
    _keys(f, _FIGHTER_KEYS, "spatial.fighter")
    coll = f["coll"]
    if not isinstance(coll, list) or len(coll) != 4:
        raise SpatialError("spatial.fighter.coll: expected 4 numbers")
    fighter = None if lean else SpatialFighter(valid=_int(f["valid"], "fighter.valid", 0, 1),
                             floor_line_id=_int(f["floor_line_id"], "floor_line_id", *s32),
                             ceil_line_id=_int(f["ceil_line_id"], "ceil_line_id", *s32),
                             lwall_line_id=_int(f["lwall_line_id"], "lwall_line_id", *s32),
                             rwall_line_id=_int(f["rwall_line_id"], "rwall_line_id", *s32),
                             mask_curr=_int(f["mask_curr"], "mask_curr", *u32),
                             floor_dist=_num(f["floor_dist"], "floor_dist"),
                             carry=_pair(f["carry"], "fighter.carry"),
                             coll=tuple(_num(c, "fighter.coll") for c in coll))  # type: ignore[arg-type]
    tp = obj["target_positions"]
    if not isinstance(tp, list) or len(tp) != TARGET_COUNT:
        raise SpatialError("spatial.target_positions: expected 10 [x, y] pairs")
    lines: Optional[Tuple[SpatialLine, ...]] = None
    if expect_lines:
        raw = obj["lines"]
        if not isinstance(raw, list) or len(raw) > MAX_LINES:
            raise SpatialError("spatial.lines: expected a list of at most 32 lines")
        parsed: List[SpatialLine] = []
        for i, ln in enumerate(raw):
            _keys(ln, _LINE_KEYS, f"spatial.lines[{i}]")
            if _int(ln["id"], "line.id") != i:
                raise SpatialError(f"spatial.lines[{i}]: id {ln['id']} out of order")
            verts = ln["vertices"]
            if not isinstance(verts, list) or not 1 <= len(verts) <= MAX_LINE_VERTICES:
                raise SpatialError(f"spatial.lines[{i}].vertices: expected 1..4 vertices")
            parsed.append(SpatialLine(id=i, type=_int(ln["type"], "line.type", 0, 3),
                                      group=_int(ln["group"], "line.group", 0, MAX_GROUPS - 1),
                                      flags=_int(ln["flags"], "line.flags", 0, 0xFFFF),
                                      vertex_total=_int(ln["vertex_total"], "line.vertex_total", 0, 2 ** 16),
                                      vertices=tuple(_pair(v, "line.vertex") for v in verts)))
        lines = tuple(parsed)
    return SpatialSnapshot(
        input_tick=_int(obj["input_tick"], "input_tick", *u32),
        scene_active=_int(obj["scene_active"], "scene_active", 0, 1),
        live=_int(obj["live"], "live", 0, 1),
        update_tic=_int(obj["update_tic"], "update_tic", *u32),
        anomaly_flags=_int(obj["anomaly_flags"], "anomaly_flags", *u32),
        map_bounds=tuple(_int(v, "map_bounds", *s32) for v in mb),  # type: ignore[arg-type]
        camera_bounds=tuple(_int(v, "camera_bounds", *s32) for v in cb),  # type: ignore[arg-type]
        groups=tuple(groups), fighter=fighter,
        target_live_mask=_int(obj["target_live_mask"], "target_live_mask", 0, 2 ** TARGET_COUNT - 1),
        target_positions=tuple(_pair(p, "target_position") for p in tp),
        lines=lines)


def spatial_of(reply: Mapping[str, Any], *, expect_lines: bool, lean: bool = False) -> SpatialSnapshot:
    """The parsed spatial object of an observe (expect_lines=True) or step reply; SpatialError when absent."""
    if REPLY_KEY not in reply:
        raise SpatialError(f"reply {reply.get('op')!r} has no {REPLY_KEY!r} object (is {SPATIAL_ENV}=1 effective?)")
    return parse_spatial(reply[REPLY_KEY], expect_lines=expect_lines, lean=lean)


def require_spatial_status(status: Mapping[str, Any]) -> None:
    if status.get(STATUS_KEY) is not True:
        raise SpatialError(f"status reply lacks {STATUS_KEY}=true: {SPATIAL_ENV}=1 is not effective in this process")


# -- geometry ---------------------------------------------------------------------------------------------------

def line_table_key(lines: Sequence[SpatialLine]) -> Tuple[Tuple[Any, ...], ...]:
    """The comparable static content of a native line table: (id, type, group, flags, vertices)."""
    return tuple((ln.id, ln.type, ln.group, ln.flags, tuple(ln.vertices)) for ln in lines)


def expected_table_problems(lines: Sequence[SpatialLine]) -> List[str]:
    """Differences between a native line table and EXPECTED_LINES (empty list = identical)."""
    problems: List[str] = []
    if len(lines) != len(EXPECTED_LINES):
        problems.append(f"{len(lines)} lines, expected {len(EXPECTED_LINES)}")
    for ln, exp in zip(lines, EXPECTED_LINES):
        got = (ln.id, ln.type, ln.group, ln.flags, tuple(ln.vertices))
        if got != exp:
            problems.append(f"line {ln.id}: {got} != {exp}")
        if ln.vertex_total != len(ln.vertices):
            problems.append(f"line {ln.id}: vertex_total {ln.vertex_total} != {len(ln.vertices)} stored")
    return problems


@dataclass(frozen=True)
class Segment:
    """One straight piece of a collision line in world space (a line with n vertices gives n-1 segments)."""
    line: int
    piece: int
    type: int
    group: int
    flags: int
    a: Tuple[float, float]
    b: Tuple[float, float]


def static_segments(lines: Sequence[SpatialLine]) -> List[Tuple[int, int, int, int, int, Tuple[float, float],
                                                                Tuple[float, float]]]:
    """(line, piece, type, group, flags, local a, local b) for every consecutive vertex pair, in line/piece order."""
    out = []
    for ln in lines:
        for k in range(len(ln.vertices) - 1):
            out.append((ln.id, k, ln.type, ln.group, ln.flags, ln.vertices[k], ln.vertices[k + 1]))
    return out


def world_segments(lines: Sequence[SpatialLine], groups: Sequence[SpatialGroup]) -> List[Segment]:
    """World-space segments with the game's rule (mpCollisionGetVertexPositionID): a group's translate is added to its
    stored vertices when the group is translated (anim joint attached or status != None)."""
    segs: List[Segment] = []
    for line, piece, typ, group, flags, a, b in static_segments(lines):
        g = groups[group] if group < len(groups) else None
        dx, dy = (g.translate if (g is not None and g.translated) else (0.0, 0.0))
        segs.append(Segment(line, piece, typ, group, flags,
                            (float(np.float32(a[0] + dx)), float(np.float32(a[1] + dy))),
                            (float(np.float32(b[0] + dx)), float(np.float32(b[1] + dy)))))
    return segs


def closest_point(p: Tuple[float, float], a: Tuple[float, float], b: Tuple[float, float]) -> Tuple[float, float]:
    """Closest point to p on segment ab (float64)."""
    ax, ay = a
    bx, by = b
    vx, vy = bx - ax, by - ay
    denom = vx * vx + vy * vy
    t = 0.0 if denom == 0.0 else max(0.0, min(1.0, ((p[0] - ax) * vx + (p[1] - ay) * vy) / denom))
    return ax + t * vx, ay + t * vy


# -- per-reply native invariants -------------------------------------------------------------------------------

def anomaly_names(flags: int) -> List[str]:
    return [name for bit, name in ANOMALY_BITS.items() if flags & (1 << bit)] + \
        ([f"unknown_0x{flags & ~0x1F:x}"] if flags & ~0x1F else [])


def on_platform(snap: Optional[SpatialSnapshot], observation: Optional[Mapping[str, Any]]) -> bool:
    """Mario grounded on the moving platform's line in this reply."""
    return (snap is not None and observation is not None and bool(snap.live) and snap.fighter is not None
            and bool(snap.fighter.valid)
            and int(observation.get("ground_air_state", 1)) == 0 and snap.fighter.floor_line_id == PLATFORM_LINE)


def check_snapshot(snap: SpatialSnapshot, observation: Mapping[str, Any], *,
                   prev: Optional[SpatialSnapshot] = None, prev_observation: Optional[Mapping[str, Any]] = None,
                   static_targets: Optional[Mapping[int, Tuple[float, float]]] = None) -> List[str]:
    """Numerical invariants of one spatial snapshot against the observation it is paired with (and the previous
    snapshot of the same episode, when given). Returns problem strings (empty = all hold).

    * pairing: input_tick equals the observation's; live implies scene_active; no anomaly bit;
    * stage constants: blast-zone / camera bounds; group 2 (platform) translated with x 2700 and y in 1500..3300;
      groups 0 and 1 untranslated at the origin;
    * platform speed: exactly float32(translate_y - previous translate_y) when both replies are live and one update
      apart (update_tic advanced by exactly 1);
    * platform contact: grounded on line 19 -> Mario stands exactly on the platform surface (float32 translate_y +
      300); grounded on it in this AND the previous reply -> Mario's MPCollData carry equals the platform speed (on
      the landing update the carry is still 0: physics runs before the collision pass that grounds him);
    * targets: popcount(live mask) == targets_remaining; target 2 at (2700, platform translate_y + 600); every other
      live target at its static position (static_targets, when given). Target 2 is compared within
      MOVING_TARGET_TOLERANCE (float32 rounding of two separately evaluated animations), everything else exactly."""
    p: List[str] = []
    if snap.input_tick != int(observation["input_tick"]):
        p.append(f"input_tick {snap.input_tick} != observation {observation['input_tick']}")
    if snap.live and not snap.scene_active:
        p.append("live without scene_active")
    if snap.anomaly_flags:
        p.append(f"anomaly flags {anomaly_names(snap.anomaly_flags)}")
    if not snap.live:
        return p
    if snap.map_bounds != MAP_BOUNDS or snap.camera_bounds != CAMERA_BOUNDS:
        p.append(f"bounds {snap.map_bounds} / {snap.camera_bounds}")
    if len(snap.groups) != 3 or not all(g.present for g in snap.groups):
        p.append(f"expected 3 present groups, got {[(g.id, g.present) for g in snap.groups]}")
        return p
    for g in snap.groups[:2]:
        if g.translated or g.translate != (0.0, 0.0) or g.speed != (0.0, 0.0) or g.status != GROUP_STATUS_NONE:
            p.append(f"group {g.id} not static at the origin: {g}")
    plat = snap.groups[PLATFORM_GROUP]
    ty = plat.translate[1]
    if not plat.translated or plat.status != GROUP_STATUS_NONE or plat.translate[0] != PLATFORM_TRANSLATE_X \
            or not PLATFORM_TRANSLATE_Y_RANGE[0] <= ty <= PLATFORM_TRANSLATE_Y_RANGE[1] or plat.speed[0] != 0.0:
        p.append(f"platform group out of contract: {plat}")
    if prev is not None and prev.live:
        if snap.update_tic != (prev.update_tic + 1) % 65536:
            p.append(f"update_tic {prev.update_tic} -> {snap.update_tic} (expected +1)")
        else:
            expect = float(np.float32(np.float32(ty) - np.float32(prev.groups[PLATFORM_GROUP].translate[1])))
            if plat.speed[1] != expect:
                p.append(f"platform speed {plat.speed[1]} != translate change {expect}")
    fighter = snap.fighter
    if fighter is None:
        p.append("snapshot from a lean parse: invariants need the full parse")
        return p
    if int(observation.get("fighter_valid", 0)) == 1 and not fighter.valid:
        p.append("observation fighter valid but spatial fighter invalid")
    if on_platform(snap, observation):
        if on_platform(prev, prev_observation) and fighter.carry != plat.speed:
            p.append(f"on the platform: carry {fighter.carry} != platform speed {plat.speed}")
        surface = float(np.float32(np.float32(ty) + np.float32(300.0)))
        if float(observation["position_y"]) != surface:
            p.append(f"on the platform: position_y {observation['position_y']} != surface {surface}")
    live_count = bin(snap.target_live_mask).count("1")
    if int(observation.get("btt_active", 0)) == 1 and live_count != int(observation["targets_remaining"]):
        p.append(f"live targets {live_count} != targets_remaining {observation['targets_remaining']}")
    for i in range(TARGET_COUNT):
        pos = snap.target_positions[i]
        if not snap.target_live_mask & (1 << i):
            if pos != (0.0, 0.0):
                p.append(f"target {i} not live but position {pos}")
            continue
        if i == MOVING_TARGET_ID:
            if pos[0] != PLATFORM_TRANSLATE_X or abs(pos[1] - (ty + MOVING_TARGET_OFFSET_Y)) > MOVING_TARGET_TOLERANCE:
                p.append(f"target 2 at {pos}, expected (2700, platform {ty} + 600)")
        elif static_targets is not None and i in static_targets and pos != tuple(static_targets[i]):
            p.append(f"target {i} at {pos}, expected static {tuple(static_targets[i])}")
    return p
