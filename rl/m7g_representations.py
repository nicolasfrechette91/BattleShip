"""M7g-b Phase F: evidence-based comparison of three spatial representation families for policy observation v2.

Everything here is measured from the stage data the native `btt_spatial_v1` diagnostic reports (the collision line
table, the moving platform's translate over a full replay, the live target positions) and from in-memory dummy
policies; nothing trains, nothing touches the M7g-a crossing fixtures (the crossing opportunities are evaluated from
geometry: the raised right step L1 around its marked corner and the moving platform over its whole range).

Families:
  1. global semantic grid  world-aligned channels (solid, one-way surface, live target, Mario), CNN encoder
  2. structured segments   every collision segment + live targets relative to Mario, fixed-size, MLP (m7g_obs.py)
  3. egocentric rays       N distance probes from Mario's collision centre with hit kinds, MLP

    python rl/m7g_representations.py --trace runs/m7g_obs/_equiv/post_spatial/tas_no_render_raphnet.json.gz
                                     --out docs/rl_observation_v2_m7g_comparison.json
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import numpy as np  # noqa: E402

import m7g_obs as mo  # noqa: E402
import m7g_spatial as ms  # noqa: E402

REPO_ROOT = RL_DIR.parent
SCHEMA = "battleship_m7g_representation_comparison_v1"

TARGET_HALF = 150.0                 # target hurtbox half-extent: damage_coll_size 300 x 0.5 (itmanager.c)
DIAMOND = (320.0, 190.0, 0.0, 150.0)  # Mario map_coll top / centre / bottom / width (native fighter.coll)
GRID_RESOLUTIONS = (50, 75, 100, 150, 200, 300)
GRID_EXTENT_X = (-4050.0, 5250.0)   # every segment, target box and the platform, aligned to multiples of 150
GRID_EXTENT_Y = (-4200.0, 4200.0)
RAY_COUNTS = (16, 32, 64)
RAY_RANGES = (2500.0, 3500.0, 5000.0)
HUMAN_VIEW = {"up": 2710.0, "down": 2440.0, "half_width_4_3": 3476.0, "half_width_16_9": 4635.0}  # camera audit [E]


# -- measured stage data ---------------------------------------------------------------------------------------

def measured_stage(trace: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Line table, target positions and the platform's translate range. From a spatial trace when given (native
    measurements), else from the pinned table plus tick-0 values."""
    lines = [ms.SpatialLine(i, t, g, f, len(v), v) for i, t, g, f, v in ms.EXPECTED_LINES]
    targets = {0: (-1350.0, -2250.0), 1: (-3450.0, -2550.0), 2: (2700.0, 2750.927), 3: (4950.0, -1800.0),
               4: (0.0, -900.0), 5: (0.0, 300.0), 6: (-3300.0, 3300.0), 7: (0.0, 1650.0), 8: (-3300.0, 600.0),
               9: (1650.0, -2250.0)}
    plat = (1500.0, 3300.0)
    source = "pinned table (no trace given)"
    speeds: List[float] = []
    if trace is not None:
        s0 = ms.spatial_of(trace["initial"], expect_lines=True)
        if ms.expected_table_problems(s0.lines or ()):
            raise SystemExit("trace line table differs from the pinned table")
        lines = list(s0.lines or ())
        targets = {i: s0.target_positions[i] for i in range(ms.TARGET_COUNT) if s0.target_live_mask & (1 << i)}
        ys = [s0.groups[ms.PLATFORM_GROUP].translate[1]]
        for r in trace.get("steps") or []:
            s = ms.spatial_of(r, expect_lines=False)
            if s.live:
                ys.append(s.groups[ms.PLATFORM_GROUP].translate[1])
                speeds.append(abs(s.groups[ms.PLATFORM_GROUP].speed[1]))
        plat = (min(ys), max(ys))
        source = f"native btt_spatial_v1 trace ({len(ys)} live snapshots)"
    return {"lines": lines, "targets": targets, "platform_translate_y": plat, "source": source,
            "platform_max_speed": max(speeds) if speeds else None}


def static_segments_world(lines: Sequence[ms.SpatialLine]) -> List[Tuple[int, int, int, Tuple[float, float],
                                                                          Tuple[float, float]]]:
    """(line, type, flags, a, b) for the static group only (world coordinates)."""
    return [(ln, typ, flags, a, b) for ln, _k, typ, grp, flags, a, b in ms.static_segments(lines) if grp == 1]


def solid_polygons(lines: Sequence[ms.SpatialLine]) -> List[np.ndarray]:
    """Closed solid outlines: chain the static, non-pass-through segments by shared endpoints."""
    segs = [(a, b) for _l, _t, flags, a, b in static_segments_world(lines) if not flags & ms.VERTEX_PASS]
    adj: Dict[Tuple[float, float], List[Tuple[float, float]]] = {}
    for a, b in segs:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    if any(len(v) != 2 for v in adj.values()):
        raise SystemExit("static outline is not a set of closed loops")
    seen: set = set()
    polys = []
    for start in adj:
        if start in seen:
            continue
        loop = [start]
        seen.add(start)
        prev, cur = None, start
        while True:
            nxt = [p for p in adj[cur] if p != prev]
            nxt_p = nxt[0] if nxt else adj[cur][0]
            if nxt_p == start:
                break
            loop.append(nxt_p)
            seen.add(nxt_p)
            prev, cur = cur, nxt_p
        polys.append(np.array(loop, dtype=np.float64))
    return polys


def inside(polys: Sequence[np.ndarray], px: np.ndarray, py: np.ndarray) -> np.ndarray:
    """Even-odd point-in-polygon, union over polygons (vectorised)."""
    res = np.zeros(px.shape, dtype=bool)
    for poly in polys:
        x0, y0 = poly[:, 0], poly[:, 1]
        x1, y1 = np.roll(x0, -1), np.roll(y0, -1)
        c = np.zeros(px.shape, dtype=bool)
        for i in range(len(poly)):
            cond = ((y0[i] > py) != (y1[i] > py))
            with np.errstate(divide="ignore", invalid="ignore"):
                xint = (x1[i] - x0[i]) * (py - y0[i]) / (y1[i] - y0[i]) + x0[i]
            c ^= cond & (px < xint)
        res |= c
    return res


# -- family 1: global semantic grid --------------------------------------------------------------------------------

class GridRasterizer:
    CHANNELS = ("solid", "one_way_surface", "live_target", "mario")

    def __init__(self, lines: Sequence[ms.SpatialLine], cell: float, *, supersample: int = 6):
        self.cell = float(cell)
        self.x0, self.y0 = GRID_EXTENT_X[0], GRID_EXTENT_Y[0]
        self.w = int(round((GRID_EXTENT_X[1] - GRID_EXTENT_X[0]) / cell))
        self.h = int(round((GRID_EXTENT_Y[1] - GRID_EXTENT_Y[0]) / cell))
        polys = solid_polygons(lines)
        k = supersample
        offs = (np.arange(k) + 0.5) / k
        cx = self.x0 + (np.arange(self.w)[:, None] + offs[None, :]).reshape(-1) * cell
        cy = self.y0 + (np.arange(self.h)[:, None] + offs[None, :]).reshape(-1) * cell
        X, Y = np.meshgrid(cx, cy)
        cover = inside(polys, X, Y).reshape(self.h, k, self.w, k).mean(axis=(1, 3))
        self.coverage = cover                                   # row 0 = lowest y
        self.solid = (cover >= 0.5).astype(np.uint8)
        self.static_one_way = np.zeros((self.h, self.w), dtype=np.uint8)
        for _l, _t, flags, a, b in static_segments_world(lines):
            if flags & ms.VERTEX_PASS:
                self._stamp_hline(self.static_one_way, a, b)
        self.platform_local = [(a, b) for _l, _k, _t, g, _f, a, b in ms.static_segments(lines) if g == 2]

    def row(self, y: float) -> int:
        """The cell row a surface at height y is drawn in: the row whose cell contains y, with a surface exactly on a
        cell boundary drawn in the row above (the side one stands on)."""
        return int(math.floor((y - self.y0) / self.cell))

    def col(self, x: float) -> int:
        return int(math.floor((x - self.x0) / self.cell))

    def _stamp_hline(self, grid: np.ndarray, a: Tuple[float, float], b: Tuple[float, float]) -> None:
        """Mark the cells a horizontal surface from a to b is drawn in (its row, every column it spans)."""
        r = self.row(a[1])
        lo, hi = self.col(min(a[0], b[0])), self.col(max(a[0], b[0]) - 1e-6)
        if 0 <= r < self.h:
            grid[r, max(lo, 0):min(hi, self.w - 1) + 1] = 1

    def build(self, mario: Tuple[float, float], platform_y: float, targets: Mapping[int, Tuple[float, float]]
              ) -> np.ndarray:
        g = np.zeros((4, self.h, self.w), dtype=np.uint8)
        g[0] = self.solid
        g[1] = self.static_one_way
        for a, b in self.platform_local:
            self._stamp_hline(g[1], (a[0] + ms.PLATFORM_TRANSLATE_X, a[1] + platform_y),
                              (b[0] + ms.PLATFORM_TRANSLATE_X, b[1] + platform_y))
        for tx, ty in targets.values():
            c0, c1 = self.col(tx - TARGET_HALF), self.col(tx + TARGET_HALF - 1e-6)
            r0, r1 = self.row(ty - TARGET_HALF), self.row(ty + TARGET_HALF - 1e-6)
            g[2, max(r0, 0):min(r1, self.h - 1) + 1, max(c0, 0):min(c1, self.w - 1) + 1] = 1
        mx, my = mario
        r, c = self.row(my + DIAMOND[1]), self.col(mx)
        if 0 <= r < self.h and 0 <= c < self.w:
            g[3, r, c] = 1
        return g * 255

    # measured fidelity ----------------------------------------------------------------------------------------
    def full_cells_across(self, x0: float, x1: float, y0: float, y1: float, axis: str) -> int:
        """Fully solid cells (coverage == 1) across a solid feature's thickness, along a probe through its middle."""
        if axis == "x":
            r = self.row((y0 + y1) / 2.0)
            cols = range(self.col(x0 - self.cell), self.col(x1 + self.cell) + 1)
            return int(sum(1 for c in cols if 0 <= c < self.w and self.coverage[r, c] >= 0.999))
        c = self.col((x0 + x1) / 2.0)
        rows = range(self.row(y0 - self.cell), self.row(y1 + self.cell) + 1)
        return int(sum(1 for r in rows if 0 <= r < self.h and self.coverage[r, c] >= 0.999))

    def solid_cells_across(self, x0: float, x1: float, y0: float, y1: float, axis: str) -> int:
        """Cells marked solid (coverage >= 0.5) along the same probe."""
        if axis == "x":
            r = self.row((y0 + y1) / 2.0)
            cols = range(self.col(x0 - self.cell), self.col(x1 + self.cell) + 1)
            return int(sum(1 for c in cols if 0 <= c < self.w and self.solid[r, c]))
        c = self.col((x0 + x1) / 2.0)
        rows = range(self.row(y0 - self.cell), self.row(y1 + self.cell) + 1)
        return int(sum(1 for r in rows if 0 <= r < self.h and self.solid[r, c]))

    def free_cells_between(self, x: float, y0: float, y1: float) -> int:
        c = self.col(x)
        return int(sum(1 for r in range(self.row(y0), self.row(y1 - 1e-6) + 1)
                       if 0 <= r < self.h and not self.solid[r, c]))


def _on_line(v: float, origin: float, cell: float) -> bool:
    """v lies on a cell boundary (within 1e-3 world units: native target x values such as 5e-06 count as 0)."""
    q = (v - origin) / cell
    return abs(q - round(q)) * cell < 1e-3


# Thin solid features and gaps, from the decoded / native line table (world units).
SOLID_FEATURES = {
    "tall_wall_column (x -2100..-1800, 300 wide)": (-2100, -1800, -1000, 1000, "x"),
    "wall_top_ledge (y 2700..3000 under L0, 300 thick)": (-1800, -1200, 2700, 3000, "y"),
    "right_column (x 2100..2400)": (2100, 2400, -2000, -1000, "x"),
    "right_step_ledge (y -750..-450, under L1)": (2400, 3300, -750, -450, "y"),
    "left_platform (y -2250..-1950)": (-3900, -3000, -2250, -1950, "y"),
    "bottom_slab (y -2850..-2550)": (-1800, 2100, -2850, -2550, "y"),
}


def grid_family(stage: Mapping[str, Any]) -> Dict[str, Any]:
    lines = stage["lines"]
    rows = {}
    for cell in GRID_RESOLUTIONS:
        g = GridRasterizer(lines, cell)
        feats = {}
        for name, (x0, x1, y0, y1, axis) in SOLID_FEATURES.items():
            feats[name] = {"full_cells": g.full_cells_across(x0, x1, y0, y1, axis),
                           "solid_cells": g.solid_cells_across(x0, x1, y0, y1, axis)}
        # 45-degree band of the left structure: fully solid cells in the row through y -3300
        r = g.row(-3300.0)
        band_full = int(sum(1 for c in range(g.w) if g.coverage[r, c] >= 0.999
                            and -3900 <= g.x0 + (c + 0.5) * cell <= -2900))
        # gaps: above the wall top (the crossing gap) and the 600-wide shaft left of the wall
        gap_above_wall = g.free_cells_between(-1500.0, 3000.0, 3600.0)
        shaft_row = g.row(-1000.0)
        shaft_free = int(sum(1 for c in range(g.col(-2700.0), g.col(-2100.0 - 1e-6) + 1) if not g.solid[shaft_row, c]))
        # 150-unit gap between target 0's box (bottom -2400) and the floor (-2550) is free space in the solid channel
        t0_gap_rows = g.free_cells_between(-1350.0, -2550.0, -2400.0)
        erased = [n for n, f in feats.items() if f["solid_cells"] == 0] + \
            (["diagonal_band"] if band_full == 0 else []) + (["shaft"] if shaft_free == 0 else [])
        # one-way surfaces and the moving platform are drawn as a surface row (zero-thickness lines have no area)
        py0, py1 = stage["platform_translate_y"]
        plat_rows = len({g.row(y + 300.0) for y in np.linspace(py0, py1, 721)})
        ex = g.build((0.0, -2550.0), py0, stage["targets"])
        rows[cell] = {
            "shape_chw": [4, g.h, g.w], "cells": g.h * g.w, "values": 4 * g.h * g.w, "bytes_uint8": 4 * g.h * g.w,
            "solid_features": feats, "diagonal_band_full_cells": band_full, "gap_above_wall_free_rows": gap_above_wall,
            "shaft_free_columns": shaft_free, "target0_floor_gap_free_rows": t0_gap_rows,
            "erased_features": erased, "platform_distinct_rows": plat_rows,
            "platform_quantization_max_error": cell / 2.0, "mario_quantization_max_error": cell / 2.0,
            "static_vertices_on_cell_lines": all(
                _on_line(vx, GRID_EXTENT_X[0], cell) and _on_line(vy, GRID_EXTENT_Y[0], cell)
                for ln in lines if ln.group == 1 for vx, vy in ln.vertices),
            "target_boxes_on_cell_lines": all(
                _on_line(tx - TARGET_HALF, GRID_EXTENT_X[0], cell) and _on_line(ty - TARGET_HALF, GRID_EXTENT_Y[0], cell)
                for i, (tx, ty) in stage["targets"].items() if i != ms.MOVING_TARGET_ID),
            "example_channel_sums": [int(ex[i].astype(bool).sum()) for i in range(4)],
        }
    ok = [c for c in GRID_RESOLUTIONS if not rows[c]["erased_features"]
          and all(f["full_cells"] >= 1 for f in rows[c]["solid_features"].values())
          and rows[c]["diagonal_band_full_cells"] >= 1 and rows[c]["target0_floor_gap_free_rows"] >= 1]
    return {"resolutions": {str(k): v for k, v in rows.items()}, "coarsest_preserving_resolution": max(ok) if ok else None,
            "channels": list(GridRasterizer.CHANNELS),
            "extent": {"x": list(GRID_EXTENT_X), "y": list(GRID_EXTENT_Y)}}


# -- family 3: egocentric rays -------------------------------------------------------------------------------------

RAY_KINDS = ("floor", "ceiling", "wall", "one_way", "moving", "target")


class RaySensor:
    def __init__(self, lines: Sequence[ms.SpatialLine], n: int, rng: float):
        self.n, self.range = n, float(rng)
        ang = 2.0 * np.pi * np.arange(n) / n
        self.d = np.stack([np.cos(ang), np.sin(ang)], axis=1)
        self.static = [(ln, typ, flags, a, b) for ln, _k, typ, grp, flags, a, b in ms.static_segments(lines)]
        self.plat = [(ln, typ, flags, a, b) for ln, _k, typ, grp, flags, a, b in ms.static_segments(lines) if grp == 2]

    def segments(self, platform_y: float, targets: Mapping[int, Tuple[float, float]]):
        A, B, kind, ident = [], [], [], []
        for ln, typ, flags, a, b in self.static:
            if ln == ms.PLATFORM_LINE:
                continue
            A.append(a), B.append(b)
            kind.append(3 if flags & ms.VERTEX_PASS else {ms.LINE_FLOOR: 0, ms.LINE_CEIL: 1}.get(typ, 2))
            ident.append(f"L{ln}")
        for ln, typ, flags, a, b in self.plat:
            A.append((a[0] + ms.PLATFORM_TRANSLATE_X, a[1] + platform_y))
            B.append((b[0] + ms.PLATFORM_TRANSLATE_X, b[1] + platform_y))
            kind.append(4)
            ident.append(f"L{ln}")
        for tid, (tx, ty) in targets.items():
            h = TARGET_HALF
            corners = [(tx - h, ty - h), (tx + h, ty - h), (tx + h, ty + h), (tx - h, ty + h)]
            for k in range(4):
                A.append(corners[k]), B.append(corners[(k + 1) % 4])
                kind.append(5)
                ident.append(f"T{tid}")
        return np.array(A, float), np.array(B, float), np.array(kind), ident

    def cast(self, mario: Tuple[float, float], platform_y: float, targets: Mapping[int, Tuple[float, float]]):
        A, B, kind, ident = self.segments(platform_y, targets)
        o = np.array([mario[0], mario[1] + DIAMOND[1]])
        e = B - A                                          # (S,2)
        ao = A - o                                         # (S,2)
        den = self.d[:, 0:1] * e[None, :, 1] - self.d[:, 1:2] * e[None, :, 0]     # (N,S) cross(d, e)
        with np.errstate(divide="ignore", invalid="ignore"):
            t = (ao[None, :, 0] * e[None, :, 1] - ao[None, :, 1] * e[None, :, 0]) / den
            u = (ao[None, :, 0] * self.d[:, 1:2] - ao[None, :, 1] * self.d[:, 0:1]) / den
        ok = (np.abs(den) > 1e-12) & (t >= 0) & (t <= self.range) & (u >= 0) & (u <= 1)
        tt = np.where(ok, t, np.inf)
        best = np.argmin(tt, axis=1)
        dist = tt[np.arange(self.n), best]
        hit = np.isfinite(dist)
        feats = np.zeros((self.n, 1 + len(RAY_KINDS)), dtype=np.float32)
        feats[:, 0] = np.where(hit, dist / self.range, 1.0)
        feats[hit, 1 + kind[best[hit]]] = 1.0
        hits = {ident[best[i]] for i in range(self.n) if hit[i]}
        return feats, hits


def ray_family(stage: Mapping[str, Any]) -> Dict[str, Any]:
    lines, targets = stage["lines"], stage["targets"]
    static_targets = {i: p for i, p in targets.items() if i != ms.MOVING_TARGET_ID}
    py0, py1 = stage["platform_translate_y"]
    # Crossing opportunities from geometry only: standing anywhere on the raised right step L1 (Mario's TopN range on
    # it) and standing on the moving platform at every height of its range.
    lower = [(x, -450.0, py) for x in np.arange(2250.0, 3151.0, 150.0) for py in np.linspace(py0, py1, 7)]
    upper = [(x, py + 300.0, py) for x in np.arange(2250.0, 3151.0, 150.0) for py in np.linspace(py0, py1, 13)]
    ledge_ids = {"L0", "L9", "L12", "L13", "L17"}   # wall top ledge, overhang underside / tip, both wall faces
    out: Dict[str, Any] = {}
    for n in RAY_COUNTS:
        for rng in RAY_RANGES:
            sensor = RaySensor(lines, n, rng)

            def frac(points, want):
                c = 0
                for x, y, py in points:
                    _f, hits = sensor.cast((x, y), py, {**static_targets, 2: (2700.0, py + 600.0)})
                    c += bool(hits & want)
                return round(c / len(points), 4)

            ledge_top_lower = frac(lower, {"L0"})
            ledge_top_upper = frac(upper, {"L0"})
            wall_any_lower = frac(lower, ledge_ids)
            left_targets = frac(lower + upper, {"T1", "T6", "T8"})
            # global coverage: fraction of the 24 segments hit at least once, from a lattice of free positions
            covs = []
            polys = solid_polygons(lines)
            for x in np.arange(-3750.0, 4951.0, 600.0):
                for y in np.arange(-3900.0, 3901.0, 600.0):
                    if inside(polys, np.array([x]), np.array([y + 190.0]))[0]:
                        continue
                    _f, hits = sensor.cast((x, y), 2400.0, static_targets)
                    covs.append(len({h for h in hits if h.startswith("L")}) / 20.0)
            out[f"n{n}_r{int(rng)}"] = {
                "rays": n, "range": rng, "values": n * (1 + len(RAY_KINDS)),
                "angular_step_deg": 360.0 / n,
                "ledge_top_L0_seen_from_right_step_L1": ledge_top_lower,
                "ledge_top_L0_seen_from_moving_platform": ledge_top_upper,
                "wall_or_ledge_seen_from_right_step_L1": wall_any_lower,
                "left_targets_seen_from_crossing_takeoffs": left_targets,
                "mean_fraction_of_lines_hit": round(float(np.mean(covs)), 4), "positions": len(covs),
            }
    # geometric distances that bound what a range can reach
    corner = (-1200.0, 3000.0)
    step_corner = (2100.0, -450.0)
    dist_lower = math.dist((step_corner[0], step_corner[1] + DIAMOND[1]), corner)
    dist_upper_top = math.dist((2100.0, 3600.0 + DIAMOND[1]), corner)
    dist_upper_low = math.dist((2100.0, 1800.0 + DIAMOND[1]), corner)
    return {"configs": out, "kinds": list(RAY_KINDS), "origin": "Mario collision-diamond centre (TopN + 190)",
            "distance_to_ledge_corner": {"from_right_step_corner": round(dist_lower, 1),
                                         "from_platform_left_end_top": round(dist_upper_top, 1),
                                         "from_platform_left_end_bottom": round(dist_upper_low, 1)},
            "human_view_half_extents": HUMAN_VIEW}


# -- family 2: structured segments ---------------------------------------------------------------------------------

def segment_family(stage: Mapping[str, Any]) -> Dict[str, Any]:
    lines = stage["lines"]
    b = mo.SpatialObservationBuilder(lines)
    rng = np.random.default_rng(0)                 # Python-side sampling only
    py0, py1 = stage["platform_translate_y"]
    worst = 0.0
    for _ in range(2000):
        px = float(np.float32(rng.uniform(-9600, 9600)))
        py = float(np.float32(rng.uniform(-9600, 9600)))
        pyp = float(np.float32(rng.uniform(py0, py1)))
        snap = _fake_snapshot(pyp, stage["targets"])
        obs, _ = b.build(np.zeros(15, np.float32), {"input_tick": 0, "position_x": px, "position_y": py}, snap)
        a = np.array([s[5] for s in ms.static_segments(lines)])
        grp = np.array([s[3] for s in ms.static_segments(lines)])
        a = a + np.where(grp[:, None] == 2, [ms.PLATFORM_TRANSLATE_X, pyp], [0.0, 0.0])
        exact = a - np.array([px, py])
        worst = max(worst, float(np.max(np.abs(obs[mo.SEGMENT_GEOMETRY_KEY][:b.segment_count, 0:2] - exact))))
    return {"segments_on_stage": b.segment_count, "slots": mo.SEGMENT_SLOTS, "values": mo.FLAT_SIZE - 15,
            "values_with_state": mo.FLAT_SIZE, "max_float32_error_world_units_over_blast_zone": worst,
            "platform_position": "exact (native float32 translate; no quantization)",
            "thin_features": "zero-thickness one-way lines and 300-wide solids are exact segments; nothing erased"}


def _fake_snapshot(platform_y: float, targets: Mapping[int, Tuple[float, float]]) -> ms.SpatialSnapshot:
    groups = (ms.SpatialGroup(0, 1, 0, 0, (0.0, 0.0), (0.0, 0.0)), ms.SpatialGroup(1, 1, 0, 0, (0.0, 0.0), (0.0, 0.0)),
              ms.SpatialGroup(2, 1, 0, 1, (ms.PLATFORM_TRANSLATE_X, platform_y), (0.0, 17.0)))
    pos = [(0.0, 0.0)] * ms.TARGET_COUNT
    mask = 0
    for i, p in targets.items():
        pos[i] = (p[0], p[1]) if i != ms.MOVING_TARGET_ID else (ms.PLATFORM_TRANSLATE_X, platform_y + 600.0)
        mask |= 1 << i
    fighter = ms.SpatialFighter(1, 4, 0, 0, 0, 0, 0.0, (0.0, 0.0), DIAMOND)
    return ms.SpatialSnapshot(0, 1, 1, 61, 0, ms.MAP_BOUNDS, ms.CAMERA_BOUNDS, groups, fighter, mask, tuple(pos), None)


# -- costs -----------------------------------------------------------------------------------------------------------

def build_costs(stage: Mapping[str, Any], grid_cell: int, ray_n: int, ray_range: float, repeats: int = 3000
                ) -> Dict[str, Any]:
    lines, targets = stage["lines"], stage["targets"]
    b = mo.SpatialObservationBuilder(lines)
    g = GridRasterizer(lines, grid_cell)
    r = RaySensor(lines, ray_n, ray_range)
    rng = np.random.default_rng(1)
    pts = [(float(rng.uniform(-3000, 3000)), float(rng.uniform(-2500, 3500)), float(rng.uniform(1500, 3300)))
           for _ in range(repeats)]
    res = {}
    t0 = time.perf_counter()
    for x, y, py in pts:
        b.build(np.zeros(15, np.float32), {"input_tick": 0, "position_x": x, "position_y": y},
                _fake_snapshot(py, targets))
    res["segments_us"] = round((time.perf_counter() - t0) / repeats * 1e6, 2)
    t0 = time.perf_counter()
    for x, y, py in pts:
        g.build((x, y), py, targets)
    res[f"grid{grid_cell}_us"] = round((time.perf_counter() - t0) / repeats * 1e6, 2)
    t0 = time.perf_counter()
    for x, y, py in pts:
        r.cast((x, y), py, targets)
    res[f"rays{ray_n}_us"] = round((time.perf_counter() - t0) / repeats * 1e6, 2)
    t0 = time.perf_counter()
    for x, y, py in pts:
        _fake_snapshot(py, targets)
    res["snapshot_construction_us_included_above"] = round((time.perf_counter() - t0) / repeats * 1e6, 2)
    return res


def network_costs(grid_hw: Tuple[int, int], ray_n: int) -> Dict[str, Any]:
    """In-memory dummy SB3 policies (initialisation + forward passes only; no learning, no environment)."""
    import torch
    from gymnasium import spaces
    from stable_baselines3.common.policies import ActorCriticPolicy, MultiInputActorCriticPolicy

    torch.manual_seed(0)
    threads_before = torch.get_num_threads()
    torch.set_num_threads(1)          # the M7 profiles pin ppo.torch_threads = 1
    act = spaces.MultiDiscrete([9, 8])
    kw = {"net_arch": {"pi": [64, 64], "vf": [64, 64]}, "activation_fn": torch.nn.Tanh}
    inf = np.inf
    common = {"state": spaces.Box(-inf, inf, (15,), np.float32),
              "target_geometry": spaces.Box(-inf, inf, (10, 2), np.float32),
              "target_live": spaces.Box(0.0, 1.0, (10,), np.float32)}
    candidates = {
        "v1_mlp (control)": (ActorCriticPolicy, spaces.Box(-inf, inf, (15,), np.float32)),
        "segments (v2 candidate)": (MultiInputActorCriticPolicy, mo.make_observation_space()),
        f"rays{ray_n} + targets": (MultiInputActorCriticPolicy, spaces.Dict({
            **common, "rays": spaces.Box(-inf, inf, (ray_n, 1 + len(RAY_KINDS)), np.float32)})),
        f"grid {grid_hw[0]}x{grid_hw[1]} NatureCNN + targets": (MultiInputActorCriticPolicy, spaces.Dict({
            **common, "grid": spaces.Box(0, 255, (4, grid_hw[0], grid_hw[1]), np.uint8)})),
    }
    out = {}
    for name, (cls, space) in candidates.items():
        pol = cls(space, act, lambda _: 3e-4, **kw)
        pol.set_training_mode(False)
        params = int(sum(p.numel() for p in pol.parameters()))
        feat = int(pol.features_extractor.features_dim)

        def batch(n):
            if isinstance(space, spaces.Dict):
                return {k: torch.as_tensor(np.stack([s.sample() for _ in range(n)])) for k, s in space.spaces.items()}
            return torch.as_tensor(np.stack([space.sample() for _ in range(n)]))

        lat = {}
        with torch.no_grad():
            for n in (5, 512):
                x = batch(n)
                for _ in range(5):
                    pol.evaluate_actions(x, torch.zeros((n, 2), dtype=torch.long)) if n == 512 else pol(x)
                reps = 200 if n == 5 else 20
                t0 = time.perf_counter()
                for _ in range(reps):
                    pol.evaluate_actions(x, torch.zeros((n, 2), dtype=torch.long)) if n == 512 else pol(x)
                lat[f"batch{n}_ms"] = round((time.perf_counter() - t0) / reps * 1e3, 4)
        obs_bytes = int(sum(int(np.prod(s.shape)) * np.dtype(s.dtype).itemsize for s in space.spaces.values())) \
            if isinstance(space, spaces.Dict) else 15 * 4
        # PPO update estimate [E]: 10 epochs x 10 minibatches of 512, backward ~ 2x forward
        update_s = round(3 * lat["batch512_ms"] * 100 / 1e3, 3)
        out[name] = {"parameters": params, "features_dim": feat, **lat, "obs_bytes": obs_bytes,
                     "rollout_buffer_obs_mib_5120": round(obs_bytes * 5120 / 2 ** 20, 3),
                     "ppo_update_compute_estimate_s": update_s}
    torch.set_num_threads(threads_before)
    return {"policies": out, "torch": torch.__version__, "threads": 1,
            "cpu": platform.processor(), "note": "forward passes of randomly initialised in-memory policies on "
                                                 "random observations; PPO update time is an estimate (3 x forward "
                                                 "of 100 minibatches of 512), not a measurement of training"}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trace", type=Path, help="a spatial capture trace (json.gz) for measured stage data")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    import m7f_trace as mt

    trace = mt.read_trace(a.trace) if a.trace else None
    stage = measured_stage(trace)
    report: Dict[str, Any] = {"schema": SCHEMA, "stage_source": stage["source"],
                              "platform_translate_y_measured": list(stage["platform_translate_y"]),
                              "platform_max_speed_measured": stage["platform_max_speed"],
                              "targets_measured": {str(k): list(v) for k, v in sorted(stage["targets"].items())}}
    report["grid"] = grid_family(stage)
    report["segments"] = segment_family(stage)
    report["rays"] = ray_family(stage)
    cell = report["grid"]["coarsest_preserving_resolution"] or 150
    hw = tuple(report["grid"]["resolutions"][str(cell)]["shape_chw"][1:])
    report["build_costs"] = build_costs(stage, cell, 32, 3500.0)
    report["networks"] = network_costs(hw, 32)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"grid_coarsest": cell, "grid_hw": hw, "build_costs": report["build_costs"],
                      "networks": {k: {kk: vv for kk, vv in v.items() if kk in ("parameters", "batch5_ms",
                                                                              "batch512_ms", "obs_bytes")}
                                   for k, v in report["networks"]["policies"].items()}}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
