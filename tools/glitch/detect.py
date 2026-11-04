"""Offline anomaly detector for Break-the-Targets per-tick traces (the lab's stepping traces: {"initial": observe reply,
"steps": [step reply, ...]} with the observation, btt_spatial_v1, btt_entity_v1, btt_input_state_v1 and
btt_target_identity_v1 blocks).

Read-only: it consumes recorded replies and writes events. Each event is one JSON object (schema
btt_glitch_event_v1, documented in GLITCH_CANDIDATES.md section 3.3). Detectors are generic (geometry comes from the
trace's own native line table); no route, coordinate or target id is built in.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from analysis import face_normal, inside_solid, loops, segment_box_hit
from geometry import KIND_CEIL, KIND_FLOOR, KIND_LWALL, KIND_RWALL, VERTEX_COLL_PASS, Geometry, lines_from_trace_reply

EVENT_SCHEMA = "btt_glitch_event_v1"
DETECTOR = {"name": "tools/glitch/detect.py", "version": 1}

MAP_FLAG_LWALL, MAP_FLAG_RWALL, MAP_FLAG_CEIL, MAP_FLAG_FLOOR = 0x1, 0x20, 0x400, 0x800


@dataclass
class Params:
    cross_margin: float = 0.01          # how far behind a line a swept point must end to count as crossing it
    snap_threshold: float = 1.0         # |position change - velocity prediction| that counts as a snap (units)
    target_half_extent: float = 150.0   # ITBonus1ObjectHeader damage_coll_size 300 x 0.5 (itmanager.c:382)
    body_reach: float = 500.0           # generous reach of Mario's hitboxes from his centre (not measured)
    weapon_radius: float = 100.0        # Mario fireball WPAttributes size 200 x 0.5 (204_MarioSpecial1.c)
    transn_status_ids: Tuple[int, ...] = (225, 226)   # nFTMarioStatusSpecialHi / SpecialAirHi (rl/data/m7n_action_classes_v2.json)
    fireball_status_ids: Tuple[int, ...] = (223, 224)  # nFTMarioStatusSpecialN / SpecialAirN
    transn_stick_threshold: int = 50    # FTMARIO_SUPERJUMP_TURN_STICK_THRESHOLD (ftmario.h)
    platform_window: int = 30           # ticks back to look for the D1 path
    all_snaps: bool = False             # emit every snap, not only unexplained / edge snaps
    default_ecb: Tuple[float, float, float, float] = (320.0, 190.0, 0.0, 150.0)  # 203_MarioMain.c map_coll


@dataclass
class State:
    index: int                # -1 = initial observe reply, else step index
    reply: Mapping[str, Any]

    def __post_init__(self) -> None:
        r = self.reply
        o = r.get("observation") or {}
        sp = r.get("spatial") or {}
        f = sp.get("fighter") or {}
        en = r.get("entity") or {}
        ef = en.get("fighter") or {}
        inp = r.get("input") or {}
        tg = r.get("targets") or {}
        self.live = int(o.get("fighter_valid", 0)) == 1 and int(o.get("btt_active", 0)) == 1
        self.x = float(o.get("position_x", 0.0))
        self.y = float(o.get("position_y", 0.0))
        self.vx = float(o.get("air_velocity_x", 0.0))
        self.vy = float(o.get("air_velocity_y", 0.0))
        self.ga = int(o.get("ground_air_state", -1))
        self.status = int(o.get("fighter_status_id", -1))
        self.input_tick = o.get("input_tick")
        self.consumed_tick = r.get("consumed_tick")
        self.floor_id = int(f.get("floor_line_id", -1))
        self.lwall_id = int(f.get("lwall_line_id", -1))
        self.rwall_id = int(f.get("rwall_line_id", -1))
        self.ceil_id = int(f.get("ceil_line_id", -1))
        self.mask = int(f.get("mask_curr", 0))
        carry = f.get("carry") or [0.0, 0.0]
        self.carry = (float(carry[0]), float(carry[1]))
        self.coll = tuple(float(v) for v in f["coll"]) if f.get("coll") else None
        self.groups = {int(g["id"]): (float(g["translate"][0]), float(g["translate"][1]))
                       for g in sp.get("groups") or [] if int(g.get("translated", 0)) == 1}
        self.map_bounds = sp.get("map_bounds")
        self.camera_bounds = sp.get("camera_bounds")
        self.target_mask = sp.get("target_live_mask", tg.get("remaining_mask"))
        self.target_positions = sp.get("target_positions") or []
        self.target_records = {int(t["id"]): t for t in tg.get("records") or []}
        self.weapons = {int(w.get("serial", i)): w for i, w in enumerate(en.get("weapons") or [])}
        self.hitlag = int(ef.get("hitlag_tics", 0) or 0)
        self.attack_active = int(ef.get("attack_active", 0) or 0)
        self.stick_x = int(inp.get("stick_x", 0) or 0)
        self.flags = {k: int((r.get(k) or {}).get("anomaly_flags", 0) or 0) for k in ("spatial", "entity", "targets")}


def _point(s: State, ecb: Tuple[float, float, float, float], which: str) -> Tuple[float, float]:
    top, center, bottom, width = ecb
    return {"bottom": (s.x, s.y + bottom), "top": (s.x, s.y + top), "center": (s.x, s.y + center),
            "right": (s.x + width, s.y + center), "left": (s.x - width, s.y + center)}[which]


POINTS_BY_KIND = {KIND_FLOOR: ("bottom", "center"), KIND_CEIL: ("top", "center"),
                  KIND_LWALL: ("right", "bottom", "top", "center"), KIND_RWALL: ("left", "bottom", "top", "center")}


def _local(p: Tuple[float, float], s: State, group: int) -> Tuple[float, float]:
    off = s.groups.get(group, (0.0, 0.0))
    return (p[0] - off[0], p[1] - off[1])


def _snapshot(s: State) -> Dict[str, Any]:
    return {"step": s.index, "input_tick": s.input_tick, "consumed_tick": s.consumed_tick, "pos": [s.x, s.y],
            "vel_air": [s.vx, s.vy], "ga": s.ga, "status": s.status, "floor": s.floor_id, "lwall": s.lwall_id,
            "rwall": s.rwall_id, "ceil": s.ceil_id, "mask_curr": s.mask, "carry": list(s.carry), "hitlag": s.hitlag}


class Detector:
    def __init__(self, trace: Mapping[str, Any], geometry: Optional[Geometry] = None, params: Optional[Params] = None,
                 source: Optional[Mapping[str, Any]] = None) -> None:
        self.p = params or Params()
        self.source = dict(source or {})
        initial = trace.get("initial") or {}
        self.states = [State(-1, initial)] + [State(i, r) for i, r in enumerate(trace.get("steps") or [])]
        self.geo = geometry or lines_from_trace_reply(initial)
        coll = next((s.coll for s in self.states if s.coll), None)
        self.ecb = coll or self.p.default_ecb
        moving = set()
        for s in self.states:
            moving.update(s.groups)
        self.moving = moving
        self.solids = [lp for lp in loops(self.geo, moving_groups=moving) if lp.solid_inside]
        self.events: List[Dict[str, Any]] = []
        self.counts: Dict[str, int] = {}

    # -- event plumbing ---------------------------------------------------------------------------------------------

    def _platform(self, idx: int) -> List[str]:
        tags = []
        lo = max(0, idx + 1 - self.p.platform_window)
        for s in self.states[lo:idx + 2]:
            if s.status in self.p.transn_status_ids and abs(s.stick_x) > self.p.transn_stick_threshold:
                tags.append("d1_transn_cosf")
                break
        return tags

    def emit(self, kind: str, mechanisms: Sequence[str], prev: State, cur: State, score: float, threshold: float,
             evidence: Mapping[str, Any], tick_to: Optional[int] = None) -> None:
        key = json.dumps([self.geo.sha256(), self.source.get("trace"), kind, cur.index, evidence.get("key")], default=str)
        ev = {
            "schema": EVENT_SCHEMA,
            "event_id": hashlib.sha256(key.encode()).hexdigest()[:16],
            "kind": kind,
            "mechanisms": list(mechanisms),
            "step": cur.index,
            "step_from": prev.index,
            "step_to": cur.index if tick_to is None else tick_to,
            "input_tick": cur.input_tick,
            "consumed_tick": cur.consumed_tick,
            "score": round(float(score), 6),
            "threshold": threshold,
            "source": self.source,
            "geometry_sha256": self.geo.sha256(),
            "ecb": list(self.ecb),
            "fighter": {"prev": _snapshot(prev), "curr": _snapshot(cur)},
            "evidence": {k: v for k, v in evidence.items() if k != "key"},
            "platform_sensitive": self._platform(cur.index),
            "detector": DETECTOR,
            "needs_replay": True,
        }
        self.events.append(ev)
        self.counts[kind] = self.counts.get(kind, 0) + 1

    # -- detectors --------------------------------------------------------------------------------------------------

    def line_crossings(self, a: State, b: State) -> None:
        for line in self.geo.lines:
            pts = POINTS_BY_KIND[line.kind]
            for k, (s0, s1, flags) in enumerate(line.segments()):
                n = face_normal(line.kind, s0, s1)
                seg = (s1[0] - s0[0], s1[1] - s0[1])
                seg_len2 = seg[0] ** 2 + seg[1] ** 2
                for which in pts:
                    p0 = _local(_point(a, self.ecb, which), a, line.group)
                    p1 = _local(_point(b, self.ecb, which), b, line.group)
                    d0 = (p0[0] - s0[0]) * n[0] + (p0[1] - s0[1]) * n[1]
                    d1 = (p1[0] - s0[0]) * n[0] + (p1[1] - s0[1]) * n[1]
                    if not (d0 >= -self.p.cross_margin and d1 < -self.p.cross_margin):
                        continue
                    t = d0 / (d0 - d1) if d0 != d1 else 0.0
                    q = (p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t)
                    u = ((q[0] - s0[0]) * seg[0] + (q[1] - s0[1]) * seg[1]) / seg_len2
                    tol = 0.5 / math.sqrt(seg_len2)
                    if not -tol <= u <= 1 + tol:
                        continue
                    if flags & VERTEX_COLL_PASS:
                        # one-way line: crossing it is ordinary (M9); counted for explanation, not emitted
                        self.counts["pass_line_crossing"] = self.counts.get("pass_line_crossing", 0) + 1
                        continue
                    mech = ["M3", "M5", "M2"] if which == "center" else ["M5", "M2", "M3"]
                    self.emit("line_crossing", mech, a, b, -d1, self.p.cross_margin, {
                        "key": [line.id, k, which], "line": line.id, "segment": k, "kind": line.kind_name, "point": which,
                        "segment_xy": [list(s0), list(s1)], "group": line.group, "depth_behind": -d1,
                        "crossing_xy_local": list(q), "u_on_segment": u,
                        "corner_proximity": min(u, 1 - u) * math.sqrt(seg_len2)})

    def solid_occupancy(self) -> None:
        run: Optional[Tuple[State, State, int]] = None
        prev_live: Optional[State] = None
        for s in self.states:
            if not s.live:
                continue
            c = _point(s, self.ecb, "center")
            idx = inside_solid(c, self.solids)
            if idx is not None:
                run = (run[0], s, idx) if run else (prev_live or s, s, idx)
            elif run:
                self._emit_inside(*run)
                run = None
            prev_live = s
        if run:
            self._emit_inside(*run)

    def _emit_inside(self, first: State, last: State, solid: int) -> None:
        self.emit("inside_solid", ["M3", "M2", "M5"], first, last, last.index - first.index, 0,
                  {"key": [solid, first.index], "solid": solid, "solid_lines": self.solids[solid].line_ids,
                   "ticks_inside": last.index - first.index}, tick_to=last.index)

    def bounds(self, a: State, b: State) -> None:
        for name, bounds, kind in (("map", b.map_bounds, "beyond_map_bounds"), ("camera", b.camera_bounds, "beyond_camera_bounds")):
            if not bounds:
                continue
            top, bottom, right, left = bounds
            out = [w for w, bad in (("top", b.y > top), ("bottom", b.y < bottom), ("right", b.x > right), ("left", b.x < left)) if bad]
            was = a.map_bounds if name == "map" else a.camera_bounds
            if out and was:
                t0, b0, r0, l0 = was
                if not (a.y > t0 or a.y < b0 or a.x > r0 or a.x < l0):
                    self.emit(kind, ["M10"], a, b, 1.0, 0, {"key": out, "sides": out, "bounds": bounds})

    def snaps(self, a: State, b: State) -> None:
        if a.hitlag > 0 or b.hitlag > 0:
            return
        grounded_both = a.ga == 0 and b.ga == 0
        px = b.vx + (b.carry[0] if b.ga == 0 else 0.0)
        if grounded_both:
            py = b.vy + b.carry[1]
        elif a.ga == 1 and b.ga == 0:
            py = a.vy
        else:
            py = b.vy
        rx, ry = (b.x - a.x) - px, (b.y - a.y) - py
        score = max(abs(rx), abs(ry))
        if score <= self.p.snap_threshold:
            return
        cls = self._classify_snap(a, b, rx, ry)
        self.counts[f"snap:{cls}"] = self.counts.get(f"snap:{cls}", 0) + 1
        if self.p.all_snaps or cls in ("unexplained", "edge_snap"):
            mech = {"edge_snap": ["M8"], "unexplained": ["M6", "M7", "M8"]}.get(cls, ["M6"])
            self.emit("position_snap", mech, a, b, score, self.p.snap_threshold,
                      {"key": [cls], "class": cls, "residual": [rx, ry], "predicted_delta": [px, py]})

    def _classify_snap(self, a: State, b: State, rx: float, ry: float) -> str:
        top, center, bottom, width = self.ecb
        if b.ga == 0 and 0 <= b.floor_id < len(self.geo.lines):
            fl = self.geo.line(b.floor_id)
            off = b.groups.get(fl.group, (0.0, 0.0))
            ends = [fl.points[0][0] + off[0], fl.points[-1][0] + off[0]]
            lo, hi = min(ends), max(ends)
            for xe in (lo, hi, lo + 40.0, hi - 40.0):
                if abs(b.x - xe) < 0.01 and abs(rx) > self.p.snap_threshold:
                    return "edge_snap"
        if a.ga != b.ga:
            return "landing" if b.ga == 0 else "takeoff"
        if abs(rx) > self.p.snap_threshold and b.mask & (MAP_FLAG_LWALL | MAP_FLAG_RWALL):
            return "wall_clamp"
        if abs(ry) > self.p.snap_threshold and b.mask & MAP_FLAG_CEIL:
            return "ceiling_clamp"
        if a.status != b.status:
            return "status_change"
        on_moving = [s.floor_id for s in (a, b) if s.ga == 0 and 0 <= s.floor_id < len(self.geo.lines)
                     and self.geo.line(s.floor_id).group in self.moving]
        if on_moving and abs(rx) <= self.p.snap_threshold:
            return "moving_line"
        return "unexplained"

    def floor_switch(self, a: State, b: State) -> None:
        if not (a.ga == 0 and b.ga == 0 and a.floor_id >= 0 and b.floor_id >= 0 and a.floor_id != b.floor_id):
            return
        if max(a.floor_id, b.floor_id) >= len(self.geo.lines):
            return
        la, lb = self.geo.line(a.floor_id), self.geo.line(b.floor_id)
        ends_a = {la.points[0], la.points[-1]}
        ends_b = {lb.points[0], lb.points[-1]}
        if ends_a & ends_b:
            return
        self.emit("floor_switch_unlinked", ["M6", "M7", "M9"], a, b, abs(b.y - a.y), 0,
                  {"key": [la.id, lb.id], "from_line": la.id, "to_line": lb.id, "dy": b.y - a.y})

    def target_breaks(self, a: State, b: State) -> None:
        if a.target_mask is None or b.target_mask is None:
            return
        cleared = int(a.target_mask) & ~int(b.target_mask)
        if not cleared:
            return
        top, center, bottom, width = self.ecb
        h = self.p.target_half_extent
        for tid in range(32):
            if not cleared >> tid & 1:
                continue
            pos = None
            if tid < len(a.target_positions) and (int(a.target_mask) >> tid & 1):
                pos = tuple(a.target_positions[tid])
            rec = b.target_records.get(tid) or a.target_records.get(tid)
            if rec and rec.get("break") and any(rec["break"][:2]):
                pos = (float(rec["break"][0]), float(rec["break"][1]))
            if pos is None:
                continue
            hitters: List[Dict[str, Any]] = []
            body0, body1 = (a.x, a.y + center), (b.x, b.y + center)
            r = h + self.p.body_reach
            if segment_box_hit(body0, body1, (pos[0] - r, pos[1] - r), (pos[0] + r, pos[1] + r)):
                attack = a.attack_active or b.attack_active or b.status in self.p.fireball_status_ids
                hitters.append({"hitter": "fighter", "from": list(body0), "to": list(body1), "attack_flag_or_fireball_status": bool(attack)})
            rw = h + self.p.weapon_radius
            for serial in set(a.weapons) | set(b.weapons):
                wa, wb = a.weapons.get(serial), b.weapons.get(serial)
                if wa and wb:
                    s0, s1 = tuple(wa["translate"]), tuple(wb["translate"])
                elif wa:
                    s0 = tuple(wa["translate"])
                    v = wa.get("velocity") or [0.0, 0.0]
                    s1 = (s0[0] + v[0], s0[1] + v[1])
                else:
                    s0 = s1 = tuple(wb["translate"])
                if segment_box_hit(s0, s1, (pos[0] - rw, pos[1] - rw), (pos[0] + rw, pos[1] + rw)):
                    hitters.append({"hitter": "weapon", "serial": serial, "from": list(s0), "to": list(s1)})
            plausible = [x for x in hitters if x["hitter"] == "weapon" or x["attack_flag_or_fireball_status"]]
            evidence = {"key": [tid], "target": tid, "target_xy": list(pos), "hitters": hitters,
                        "box_half_extent": h, "body_reach": self.p.body_reach, "weapon_radius": self.p.weapon_radius}
            if not plausible:
                self.emit("break_without_plausible_hitter", ["M11"], a, b, 1.0, 0, evidence)
                continue
            blocked_by: List[List[int]] = []
            for x in plausible:
                frm = tuple(x["to"])
                hit = sorted({line.id for line in self.geo.lines if line.group not in self.moving
                              for s0, s1, f in line.segments()
                              if not (f & VERTEX_COLL_PASS) and _segments_cross(frm, pos, s0, s1)})
                blocked_by.append(hit)
            if all(blocked_by):
                evidence["solid_lines_between"] = sorted({i for hit in blocked_by for i in hit})
                self.emit("break_through_solid", ["M11"], a, b, len(evidence["solid_lines_between"]), 0, evidence)

    def native_flags(self, b: State) -> None:
        bad = {k: v for k, v in b.flags.items() if v}
        if bad:
            self.emit("native_anomaly_flag", ["-"], b, b, 1.0, 0, {"key": sorted(bad), "flags": bad})

    def run(self) -> Dict[str, Any]:
        live = [s for s in self.states if s.live]
        for a, b in zip(live, live[1:]):
            if b.index != a.index + 1:
                self.counts["tick_gap"] = self.counts.get("tick_gap", 0) + 1
                continue
            self.line_crossings(a, b)
            self.bounds(a, b)
            self.snaps(a, b)
            self.floor_switch(a, b)
            self.target_breaks(a, b)
            self.native_flags(b)
        self.solid_occupancy()
        self.events.sort(key=lambda e: (e["step"], e["kind"]))
        return {"schema": "btt_glitch_scan_v1", "source": self.source, "geometry_sha256": self.geo.sha256(),
                "ecb": list(self.ecb), "live_ticks": len(live), "solids": len(self.solids), "counts": self.counts,
                "events": len(self.events)}


def _segments_cross(p: Tuple[float, float], q: Tuple[float, float], a: Tuple[float, float], b: Tuple[float, float]) -> bool:
    def orient(o, u, v):
        return (u[0] - o[0]) * (v[1] - o[1]) - (u[1] - o[1]) * (v[0] - o[0])
    d1, d2 = orient(a, b, p), orient(a, b, q)
    d3, d4 = orient(p, q, a), orient(p, q, b)
    return (d1 > 0) != (d2 > 0) and (d3 > 0) != (d4 > 0) and d1 != 0 and d2 != 0 and d3 != 0 and d4 != 0


def scan(trace: Mapping[str, Any], geometry: Optional[Geometry] = None, params: Optional[Params] = None,
         source: Optional[Mapping[str, Any]] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    det = Detector(trace, geometry, params, source)
    summary = det.run()
    return det.events, summary
