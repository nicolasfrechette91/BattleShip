"""M7u: the compact native state row, the bookkeeping history, the exogenous clock track and the static world.

Design: docs/rl_model_planning_m7u_proposal_2026-09-29.md (revision 2, sections 3-4). Opt-in; nothing here is used by any
earlier contract. NumPy only (spawn workers import this module; no PyTorch).

Three kinds of quantity, kept apart on purpose:

* NATIVE ROW (`FIELDS`): values read from one raw reply of the existing diagnostics (SSB64_RL_SPATIAL / ENTITY / INPUT),
  never computed. In imagination the learned model predicts the next row's gameplay fields (rl/m7u_model.py).
* CONTROLLER ENCODING / BOOKKEEPING (`HIST_FIELDS`, `advance_history`): deterministic functions of the submitted Track 1
  words and of the row sequence itself (previous words, previous tap levels, the status before the current status run,
  ticks in the run, facing at run start, last grounded floor line, the air-tornado bit, previous positions). The same
  function is applied to recorded and to imagined sequences.
* EXOGENOUS TRACK (`ClockTrack`): the moving platform group's translate / speed and the moving target's position as a
  function of the clock, used only when every training episode holds exactly equal values at every live tick.

The native latched input state (the game's button_tap / button_release masks after its R -> A+Z fold, hitlag accumulation
and hit-tick clearing, the stick tap counters with their forced resets, the Z timer) is part of the NATIVE ROW: it is
gameplay-dependent and is learned, never derived from the words. The words themselves are exact controller truth. No
gravity, drift, collision, fold, stick-band or status-transition rule of the game is implemented here.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

import m7g_spatial as ms
import m7n_entity as ne
import m7q_input as mi

CONTRACT = "m7u_native_state_v1"
HISTORY_CONTRACT = "m7u_bookkeeping_v1"
TRACK_CONTRACT = "m7u_clock_track_v1"

# Scales: identical to btt_policy_obs_v3_entities / v4 (rl/m7n_obs.py, rl/m7q_obs.py).
LENGTH_SCALE = 2000.0
VELOCITY_SCALE = 50.0
TIME_SCALE = 3600.0
PROGRESS_SCALE = 60.0
STATUS_ID_SCALE = 256.0
STATUS_TICS_CAP = 240
HITLAG_CAP = 60
FLOOR_DIST_CAP = 8000.0
ANIM_FRAME_CAP = 240.0
ANIM_SPEED_CAP = 2.0
Z_WINDOW = mi.Z_CANCEL_WINDOW       # 10
TARGET_COUNT = ms.TARGET_COUNT      # 10
MOVING_TARGET_ID = ms.MOVING_TARGET_ID
PLATFORM_GROUP = ms.PLATFORM_GROUP
N_FLOOR_CLASSES = 21                # floor_line_id -1 (none) and 0..19
JUMPS_MAX = 2                       # Mario (entity jumps_max, checked per reply)
SEGMENTS_KEPT = 8                   # nearest segments in the model input
SEG_GEOM, SEG_KIND = 8, 7

# Contract buttons, in the v4 hold-bit order (A, B, Z, L, R, C-up, C-left).
BUTTON_BITS = mi.CONTRACT_BUTTONS
CONTACT_BITS = (ms.CONTACT_FLOOR, ms.CONTACT_CEIL, ms.CONTACT_LWALL, ms.CONTACT_RWALL)
CONTACT_EDGE_BIT = 0x8000

FIELDS: Tuple[str, ...] = (
    "input_tick", "time_passed", "valid", "game_status",
    "x", "y", "vax", "vay", "vgx", "floor_dist", "carry_x", "carry_y", "coll_top", "coll_width", "anim_frame", "anim_speed",
    "status", "ga", "facing", "jumps_used", "fastfall", "floor_line", "c_floor", "c_ceil", "c_lwall", "c_rwall", "c_edge",
    "hitlag", "attack", "shield", "mflag1", "tap_x", "tap_y", "z", "hold", "tap_mask", "rel_mask", "stick_x", "stick_y",
    "status_tics", "live_mask", "targets_remaining", "grp_tx", "grp_ty", "grp_sx", "grp_sy", "t2_x", "t2_y", "n_proj",
    "jumps_max",
)
F = {name: i for i, name in enumerate(FIELDS)}
N_FIELDS = len(FIELDS)

# Bookkeeping history (one row per state). Words are Track 1 (stick, button) indices, -1 = none (before tick 0).
HIST_FIELDS: Tuple[str, ...] = (
    "w1s", "w1b", "w2s", "w2b", "w3s", "w3b", "tapx1", "tapy1", "tapx2", "tapy2",
    "prev_status", "run_ticks", "facing_start", "last_floor", "tornado", "prev_x", "prev_y", "prev_t2x", "prev_t2y",
)
Hh = {name: i for i, name in enumerate(HIST_FIELDS)}
N_HIST = len(HIST_FIELDS)

TAP_LEVEL_VALUES = (1.0, 0.75, 0.5, 0.25, 0.0)   # level index 0..4 <-> v4 tap encoding of raw 1 / 2 / 3 / 4..253 / 254
N_TAP_LEVELS = 5
N_Z_LEVELS = Z_WINDOW + 2                         # 0..10 and 11+ (incl. the 65536 reset)

# Mario ids (rl/data/m7n_action_classes_v2.json names; checked by the tests against the table)
STATUS_SPECIAL_AIR_LW = 228                       # nFTMarioStatusSpecialAirLw: the air tornado


class StateError(RuntimeError):
    """A reply cannot be turned into a native row, or a sequence breaks the row / history contract."""


# -- native row --------------------------------------------------------------------------------------------------------


def tap_level_index(raw: int) -> int:
    """Raw native tap counter -> 5-level index (1 -> 0, 2 -> 1, 3 -> 2, 4..253 -> 3, 254 / 0 -> 4)."""
    r = int(raw)
    if 1 <= r <= 3:
        return r - 1
    if 4 <= r < mi.TAP_MAX:
        return 3
    return 4


def z_level_index(raw: int) -> int:
    r = int(raw)
    return min(max(r, 0), Z_WINDOW + 1)


def button_mask7(word: int) -> int:
    """Native 16-bit button word -> the 7 contract bits in v4 hold-bit order (bit k = BUTTON_BITS[k])."""
    return sum(1 << k for k, bit in enumerate(BUTTON_BITS) if int(word) & bit)


def row_from_reply(reply: Mapping[str, Any]) -> np.ndarray:
    """One float64 row from a raw observe / step reply carrying observation + spatial + entity + input (strictly parsed
    by the existing readers). A teardown or invalid-fighter reply gives valid = 0 (other fields as read)."""
    o = reply.get("observation")
    if not isinstance(o, Mapping):
        raise StateError("reply without an observation")
    sp_obj = reply.get("spatial")
    sp = ms.spatial_of(reply, expect_lines=isinstance(sp_obj, Mapping) and "lines" in sp_obj)   # observe replies carry lines
    en = ne.entity_of(reply)
    inp = mi.input_of(reply)
    tick = int(o["input_tick"])
    if not (sp.input_tick == en.input_tick == inp.input_tick == tick):
        raise StateError(f"snapshot ticks {sp.input_tick} / {en.input_tick} / {inp.input_tick} != observation {tick}")
    r = np.zeros(N_FIELDS, dtype=np.float64)
    valid = (int(o.get("btt_active", 0)) == 1 and int(o.get("fighter_valid", 0)) == 1 and sp.live and en.live
             and inp.live and inp.valid and sp.fighter is not None and sp.fighter.valid and en.fighter.valid)
    r[F["input_tick"]] = tick
    r[F["time_passed"]] = int(o["time_passed"])
    r[F["valid"]] = 1.0 if valid else 0.0
    r[F["game_status"]] = int(o["game_status"])
    r[F["x"]], r[F["y"]] = float(o["position_x"]), float(o["position_y"])
    r[F["vax"]], r[F["vay"]] = float(o["air_velocity_x"]), float(o["air_velocity_y"])
    r[F["vgx"]] = float(o["ground_velocity_x"])
    r[F["status"]] = int(o["fighter_status_id"])
    r[F["ga"]] = int(o["ground_air_state"])
    r[F["facing"]] = int(o["facing_direction"])
    r[F["jumps_used"]] = int(o["jumps_used"])
    r[F["targets_remaining"]] = int(o["targets_remaining"])
    if sp.fighter is not None:
        f = sp.fighter
        r[F["floor_dist"]] = float(f.floor_dist)
        r[F["carry_x"]], r[F["carry_y"]] = float(f.carry[0]), float(f.carry[1])
        r[F["coll_top"]], r[F["coll_width"]] = float(f.coll[0]), float(f.coll[3])
        r[F["floor_line"]] = int(f.floor_line_id)
        for name, bit in zip(("c_floor", "c_ceil", "c_lwall", "c_rwall"), CONTACT_BITS):
            r[F[name]] = 1.0 if int(f.mask_curr) & bit else 0.0
        r[F["c_edge"]] = 1.0 if int(f.mask_curr) & CONTACT_EDGE_BIT else 0.0
    ef = en.fighter
    r[F["fastfall"]] = int(ef.fastfall)
    r[F["hitlag"]] = int(ef.hitlag_tics)
    r[F["attack"]] = int(ef.attack_active)
    r[F["shield"]] = int(ef.shield_active)
    r[F["status_tics"]] = int(ef.status_total_tics)
    r[F["jumps_max"]] = int(ef.jumps_max)
    r[F["anim_frame"]], r[F["anim_speed"]] = float(inp.anim_frame), float(inp.anim_speed)
    r[F["mflag1"]] = 1.0 if int(inp.motion_flag1) != 0 else 0.0
    r[F["tap_x"]], r[F["tap_y"]] = int(inp.tap_stick_x), int(inp.tap_stick_y)
    r[F["z"]] = int(inp.tics_since_last_z)
    r[F["hold"]] = button_mask7(inp.button_hold)
    r[F["tap_mask"]] = button_mask7(inp.button_tap)
    r[F["rel_mask"]] = button_mask7(inp.button_release)
    r[F["stick_x"]], r[F["stick_y"]] = int(inp.stick_x), int(inp.stick_y)
    r[F["live_mask"]] = int(sp.target_live_mask)
    grp = None
    for g in sp.groups:
        if g.present and g.translated:
            if g.id != PLATFORM_GROUP:
                raise StateError(f"translated group {g.id} is not the pinned platform group {PLATFORM_GROUP}")
            grp = g
    if grp is not None:
        r[F["grp_tx"]], r[F["grp_ty"]] = float(grp.translate[0]), float(grp.translate[1])
        r[F["grp_sx"]], r[F["grp_sy"]] = float(grp.speed[0]), float(grp.speed[1])
    if int(sp.target_live_mask) >> MOVING_TARGET_ID & 1:
        r[F["t2_x"]], r[F["t2_y"]] = (float(v) for v in sp.target_positions[MOVING_TARGET_ID])
    else:
        r[F["t2_x"]] = r[F["t2_y"]] = np.nan
    r[F["n_proj"]] = len(ne.owned_weapons(en))
    return r


def contract_digest() -> str:
    d = {"contract": CONTRACT, "fields": list(FIELDS), "history": HISTORY_CONTRACT, "hist_fields": list(HIST_FIELDS),
         "track": TRACK_CONTRACT, "button_bits": list(BUTTON_BITS), "contact_bits": list(CONTACT_BITS),
         "edge_bit": CONTACT_EDGE_BIT, "tap_levels": list(TAP_LEVEL_VALUES), "z_levels": N_Z_LEVELS,
         "status_special_air_lw": STATUS_SPECIAL_AIR_LW, "segments_kept": SEGMENTS_KEPT}
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode("utf-8")).hexdigest()


# -- bookkeeping history -----------------------------------------------------------------------------------------------


def init_history(row0: np.ndarray) -> np.ndarray:
    """History of the reset (tick-0) row: no previous words; tap history = the row's own levels; the status run starts
    here; last grounded floor = the row's floor line when grounded, else -1; previous positions = the row's own."""
    h = np.zeros(N_HIST, dtype=np.float64)
    for k in ("w1s", "w1b", "w2s", "w2b", "w3s", "w3b"):
        h[Hh[k]] = -1
    tx, ty = tap_level_index(row0[F["tap_x"]]), tap_level_index(row0[F["tap_y"]])
    h[Hh["tapx1"]] = h[Hh["tapx2"]] = tx
    h[Hh["tapy1"]] = h[Hh["tapy2"]] = ty
    h[Hh["prev_status"]] = row0[F["status"]]
    h[Hh["run_ticks"]] = 0
    h[Hh["facing_start"]] = row0[F["facing"]]
    h[Hh["last_floor"]] = row0[F["floor_line"]] if int(row0[F["ga"]]) == 0 else -1
    h[Hh["tornado"]] = 0
    h[Hh["prev_x"]], h[Hh["prev_y"]] = row0[F["x"]], row0[F["y"]]
    h[Hh["prev_t2x"]], h[Hh["prev_t2y"]] = row0[F["t2_x"]], row0[F["t2_y"]]
    return h


def advance_history(h: np.ndarray, row_prev: np.ndarray, word: Tuple[int, int], row_next: np.ndarray) -> np.ndarray:
    """History of `row_next`, reached from `row_prev` (history `h`) by submitting Track 1 `word`. The identical rule is
    implemented batched in torch (rl/m7u_model.advance_history_t); the tests check equality on recorded sequences."""
    n = h.copy()
    n[Hh["w3s"]], n[Hh["w3b"]] = h[Hh["w2s"]], h[Hh["w2b"]]
    n[Hh["w2s"]], n[Hh["w2b"]] = h[Hh["w1s"]], h[Hh["w1b"]]
    n[Hh["w1s"]], n[Hh["w1b"]] = int(word[0]), int(word[1])
    n[Hh["tapx2"]], n[Hh["tapy2"]] = h[Hh["tapx1"]], h[Hh["tapy1"]]
    n[Hh["tapx1"]], n[Hh["tapy1"]] = tap_level_index(row_prev[F["tap_x"]]), tap_level_index(row_prev[F["tap_y"]])
    if int(row_next[F["status"]]) != int(row_prev[F["status"]]):
        n[Hh["prev_status"]] = row_prev[F["status"]]
        n[Hh["run_ticks"]] = 0
        n[Hh["facing_start"]] = row_next[F["facing"]]
    else:
        n[Hh["run_ticks"]] = min(h[Hh["run_ticks"]] + 1, STATUS_TICS_CAP)
    if int(row_next[F["ga"]]) == 0:
        n[Hh["last_floor"]] = row_next[F["floor_line"]]
        n[Hh["tornado"]] = 0
    elif int(row_prev[F["status"]]) == STATUS_SPECIAL_AIR_LW and int(row_next[F["status"]]) != STATUS_SPECIAL_AIR_LW:
        n[Hh["tornado"]] = 1
    n[Hh["prev_x"]], n[Hh["prev_y"]] = row_prev[F["x"]], row_prev[F["y"]]
    n[Hh["prev_t2x"]], n[Hh["prev_t2y"]] = row_prev[F["t2_x"]], row_prev[F["t2_y"]]
    return n


def history_sequence(rows: np.ndarray, words: Sequence[Tuple[int, int]]) -> np.ndarray:
    """(T + 1, N_HIST) histories of a recorded episode: rows (T + 1) and the T words submitted between them."""
    rows = np.asarray(rows, dtype=np.float64)
    if len(rows) != len(words) + 1:
        raise StateError(f"{len(rows)} rows for {len(words)} words")
    out = np.zeros((len(rows), N_HIST), dtype=np.float64)
    out[0] = init_history(rows[0])
    for k, w in enumerate(words):
        out[k + 1] = advance_history(out[k], rows[k], w, rows[k + 1])
    return out


# -- static world and the exogenous clock track -------------------------------------------------------------------------


@dataclass(frozen=True)
class StaticWorld:
    """What the reset reply fixes for the whole episode: the stage segments (local coordinates, the v3 builder's float32
    rounding), their v3 kind columns, the translated group of each segment, and the static target positions."""
    seg: np.ndarray            # (n, 4) ax, ay, bx, by (float64 of float32-rounded stored vertices)
    kind: np.ndarray           # (n, 7) float32, v3 segment_kind columns (the moving column is set per state)
    group: np.ndarray          # (n,) int
    static_targets: np.ndarray  # (10, 2), NaN for the moving target
    lines_digest: str


# Static target centres of Mario's stage (M7f native table; equal in every captured reset reply, checked by the tests).
STATIC_TARGET_POSITIONS: Tuple[Tuple[float, float], ...] = (
    (-1350.0, -2250.0), (-3450.0, -2550.0), (float("nan"), float("nan")), (4950.0, -1800.0),
    (4.999999873689376e-06, -900.0), (1.9999999494757503e-05, 300.0), (-3300.0, 3300.0), (0.0, 1650.0),
    (-3300.0, 600.0), (1650.0, -2250.0))


def static_world(reset_reply: Mapping[str, Any]) -> StaticWorld:
    """The static world of one reset (observe) reply."""
    sp = ms.spatial_of(reset_reply, expect_lines=True)
    st = np.full((TARGET_COUNT, 2), np.nan, dtype=np.float64)
    for i in range(TARGET_COUNT):
        if i != MOVING_TARGET_ID and sp.target_live_mask >> i & 1:
            st[i] = sp.target_positions[i]
    return _world_of(sp.lines or (), st)


def static_world_pinned() -> StaticWorld:
    """The static world from the stage table pinned in rl/m7g_spatial.py (EXPECTED_LINES, checked against every native
    table since M7g) and STATIC_TARGET_POSITIONS. The driver checks every episode's reset reply against it."""
    lines = [ms.SpatialLine(id=i, type=t, group=g, flags=f, vertex_total=len(v), vertices=tuple(tuple(p) for p in v))
             for i, t, g, f, v in ms.EXPECTED_LINES]
    return _world_of(lines, np.array(STATIC_TARGET_POSITIONS, dtype=np.float64))


def world_digest(world: StaticWorld) -> str:
    h = hashlib.sha256(world.lines_digest.encode("utf-8"))
    h.update(np.ascontiguousarray(np.nan_to_num(world.static_targets, nan=-1e30)).tobytes())
    return h.hexdigest()


def _world_of(lines: Sequence[ms.SpatialLine], static_targets: np.ndarray) -> StaticWorld:
    segs = ms.static_segments(lines)
    if not segs or len(segs) > 32:
        raise StateError(f"{len(segs)} collision segments (1..32 expected)")
    seg = np.zeros((len(segs), 4), dtype=np.float64)
    kind = np.zeros((len(segs), SEG_KIND), dtype=np.float32)
    group = np.zeros(len(segs), dtype=np.int64)
    type_col = {ms.LINE_FLOOR: 1, ms.LINE_CEIL: 2, ms.LINE_RWALL: 3, ms.LINE_LWALL: 4}
    for i, (_line, _piece, typ, grp, flags, a, b) in enumerate(segs):
        seg[i] = [float(np.float32(c)) for c in (a[0], a[1], b[0], b[1])]
        kind[i, 0] = 1.0
        kind[i, type_col[typ]] = 1.0
        kind[i, 5] = 1.0 if flags & ms.VERTEX_PASS else 0.0
        group[i] = int(grp)
    key = json.dumps(ms.line_table_key(lines), sort_keys=True, default=list)
    return StaticWorld(seg=seg, kind=kind, group=group, static_targets=np.asarray(static_targets, dtype=np.float64),
                       lines_digest=hashlib.sha256(key.encode("utf-8")).hexdigest())


TRACK_COLUMNS = ("grp_tx", "grp_ty", "grp_sx", "grp_sy", "t2_x", "t2_y")


@dataclass
class ClockTrack:
    """Clock-indexed exogenous values, built from recorded rows. `table[t]` holds TRACK_COLUMNS at input_tick t (NaN
    target columns where the moving target was never recorded live at t)."""
    table: np.ndarray            # (max_tick + 1, 6)
    covered: np.ndarray          # (max_tick + 1,) bool: at least one valid row at this tick

    def at(self, ticks: np.ndarray) -> np.ndarray:
        t = np.asarray(ticks, dtype=np.int64)
        if (t < 0).any() or (t >= len(self.table)).any() or not self.covered[t].all():
            bad = t[(t < 0) | (t >= len(self.table))].tolist()
            ok_t = t[(t >= 0) & (t < len(self.table))]
            bad += ok_t[~self.covered[ok_t]].tolist()
            raise StateError(f"clock track does not cover ticks {sorted(set(bad))[:5]}")
        return self.table[t]

    def digest(self) -> str:
        return hashlib.sha256(np.ascontiguousarray(self.table).tobytes() + self.covered.tobytes()).hexdigest()


def build_clock_track(episodes: Sequence[np.ndarray]) -> Tuple[ClockTrack, List[str]]:
    """The track from the valid rows of `episodes` and the list of problems: any tick at which two valid rows disagree
    (exact float equality) on the platform translate / speed, or on the moving target's position while it is live."""
    max_tick = 0
    for rows in episodes:
        v = rows[rows[:, F["valid"]] == 1.0]
        if len(v):
            max_tick = max(max_tick, int(v[:, F["input_tick"]].max()))
    table = np.full((max_tick + 1, len(TRACK_COLUMNS)), np.nan, dtype=np.float64)
    covered = np.zeros(max_tick + 1, dtype=bool)
    problems: List[str] = []
    cols = [F[c] for c in TRACK_COLUMNS]
    for e, rows in enumerate(episodes):
        for r in rows:
            if r[F["valid"]] != 1.0:
                continue
            t = int(r[F["input_tick"]])
            vals = r[cols]
            if not covered[t]:
                table[t] = vals
                covered[t] = True
                continue
            cur = table[t]
            for j, name in enumerate(TRACK_COLUMNS):
                a, b = cur[j], vals[j]
                if np.isnan(a) and not np.isnan(b):
                    table[t, j] = b
                elif not np.isnan(a) and not np.isnan(b) and a != b:
                    if len(problems) < 50:
                        problems.append(f"tick {t} {name}: {a!r} vs {b!r} (episode {e})")
                    else:
                        problems[-1] = "... more disagreements"
    return ClockTrack(table=table, covered=covered), problems


# -- numpy reference featurisation (tests only; production uses the torch path in rl/m7u_model.py) -----------------------


def segment_rows_all(world: StaticWorld, px: float, py: float, grp_tx: float, grp_ty: float, grp_sx: float,
                     grp_sy: float) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(n, 8) geometry rows, (n, 7) kind rows and (n,) closest-point distances for every segment, with the v3 builder's
    arithmetic (rl/m7n_obs.EntityObservationBuilder.build): the moving group's float32 translate added in float32."""
    f32 = np.float32
    geo = np.zeros((len(world.seg), SEG_GEOM), dtype=np.float64)
    dist = np.zeros(len(world.seg), dtype=np.float64)
    kind = world.kind.copy()
    L, V = LENGTH_SCALE, VELOCITY_SCALE
    for i, (ax, ay, bx, by) in enumerate(world.seg):
        sx = sy = 0.0
        if int(world.group[i]) == PLATFORM_GROUP:
            ax = float(f32(ax) + f32(grp_tx))
            ay = float(f32(ay) + f32(grp_ty))
            bx = float(f32(bx) + f32(grp_tx))
            by = float(f32(by) + f32(grp_ty))
            sx, sy = grp_sx, grp_sy
            kind[i, 6] = 1.0
        vx, vy = bx - ax, by - ay
        vv = vx * vx + vy * vy
        rax, ray = ax - px, ay - py
        t = -(rax * vx + ray * vy) / vv
        t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
        nx, ny = rax + t * vx, ray + t * vy
        geo[i] = (rax / L, ray / L, (bx - px) / L, (by - py) / L, nx / L, ny / L, sx / V, sy / V)
        dist[i] = float(np.hypot(nx, ny))
    return geo, kind, dist
