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

from analysis import check_connectivity, face_normal, inside_solid, loops, segment_box_hit
from geometry import KIND_CEIL, KIND_FLOOR, KIND_LWALL, KIND_RWALL, VERTEX_COLL_PASS, Geometry, lines_from_trace_reply

EVENT_SCHEMA = "btt_glitch_event_v1"
DETECTOR = {"name": "tools/glitch/detect.py", "version": 1}

MAP_FLAG_LWALL, MAP_FLAG_RWALL, MAP_FLAG_CEIL, MAP_FLAG_FLOOR = 0x1, 0x20, 0x400, 0x800


@dataclass
class Params:
    cross_margin: float = 0.01          # how far behind a line a swept point must end to count as crossing it
    vertex_eps: float = 0.001           # float error at a vertex: the 0.001 start tolerance of the flat tests and the +-0.001
                                        # clamp of the line getters (mpcollision.c; GLITCH_CANDIDATES.md 1.4), about 4 ulps here
    snap_threshold: float = 1.0         # |position change - velocity prediction| that counts as a snap (units)
    hitlag_window: int = 11             # longest hitlag after a hit: (s32)(19 / 3 + 5), ftParamGetHitLag US (ftparam.c:1674-1680)
                                        # with Mario's largest hitbox damage 19 (202_MarioMainMotion.c); hitlag_mul is 1.5 only for
                                        # electric hits between fighters (ftmain.c:3020, 3140). In BTT the only hits are target breaks
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
        self.has_entity = bool(en)  # False in live replies (explore flags: spatial only): no hitlag, attack flag or weapons
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
        self.convex = {(self.geo.line(f.where["lines"][0]).group, tuple(f.where["point"])): f.where for f in check_connectivity(self.geo)
                       if f.check in ("corner", "bend") and f.where.get("corner") == "convex"}
        self.events: List[Dict[str, Any]] = []
        self.counts: Dict[str, int] = {}
        self.last_break: Optional[int] = None

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
                    # a real crossing ends behind the segment itself; an end past the segment's end is a corner pass
                    # (e.g. a point clamped on a wall that rises past its top end): counted, and logged near a convex vertex
                    u1 = ((p1[0] - s0[0]) * seg[0] + (p1[1] - s0[1]) * seg[1]) / seg_len2
                    eps_u = self.p.vertex_eps / math.sqrt(seg_len2)
                    if not eps_u < u1 < 1 - eps_u:
                        self.counts["corner_pass"] = self.counts.get("corner_pass", 0) + 1
                        self._corner_pass(a, b, line, k, which, p0, p1, s1 if u1 >= 1 - eps_u else s0, u1)
                        continue
                    if flags & VERTEX_COLL_PASS:
                        # one-way line: a downward crossing is a fall through it (M9), an ordinary mechanic; logged, never a clip
                        self.counts["pass_line_crossing"] = self.counts.get("pass_line_crossing", 0) + 1
                        self.emit("pass_through", ["M9"], a, b, -d1, self.p.cross_margin, {
                            "key": [line.id, k, which], "line": line.id, "segment": k, "kind": line.kind_name, "point": which,
                            "group": line.group, "depth_behind": -d1, "crossing_xy_local": list(q), "u_on_segment": u})
                        continue
                    mech = ["M3", "M5", "M2"] if which == "center" else ["M5", "M2", "M3"]
                    self.emit("line_crossing", mech, a, b, -d1, self.p.cross_margin, {
                        "key": [line.id, k, which], "line": line.id, "segment": k, "kind": line.kind_name, "point": which,
                        "segment_xy": [list(s0), list(s1)], "group": line.group, "depth_behind": -d1,
                        "crossing_xy_local": list(q), "u_on_segment": u,
                        "corner_proximity": min(u, 1 - u) * math.sqrt(seg_len2)})

    def _corner_pass(self, a: State, b: State, line: Any, k: int, which: str, p0: Tuple[float, float], p1: Tuple[float, float],
                     vertex: Tuple[float, float], u_end: float) -> None:
        corner = self.convex.get((line.group, tuple(vertex)))
        if corner is None:
            return
        d = _point_segment_distance(vertex, p0, p1)
        if d > self.p.vertex_eps:
            return
        self.emit("corner_pass_near_vertex", ["M5"], a, b, d, self.p.vertex_eps, {
            "key": [line.id, k, which, list(vertex)], "line": line.id, "segment": k, "kind": line.kind_name, "point": which,
            "vertex": list(vertex), "vertex_lines": corner["lines"], "vertex_angle_deg": corner.get("angle_deg"), "distance": d,
            "u_end": u_end, "path_local": [list(p0), list(p1)], "group": line.group,
            "on_adjacent_floor": b.ga == 0 and b.floor_id in corner["lines"]})

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
        if b.x == a.x and b.y == a.y:
            # exactly unchanged although the velocity says it should move: hitlag only within hitlag_window ticks of a break
            since = None if self.last_break is None else b.index - self.last_break
            if since is not None and 0 <= since <= self.p.hitlag_window:
                self.counts["freeze:after_break"] = self.counts.get("freeze:after_break", 0) + 1
                return
            self.counts["freeze:unexplained"] = self.counts.get("freeze:unexplained", 0) + 1
            self.emit("freeze_unexplained", ["M6"], a, b, score, self.p.snap_threshold,
                      {"key": ["freeze"], "predicted_delta": [px, py], "ticks_since_break": since, "hitlag_window": self.p.hitlag_window,
                       "mask_curr": b.mask, "entity_hitlag": b.hitlag if b.has_entity else None})
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

    def _note_break(self, a: State, b: State) -> None:
        if a.target_mask is not None and b.target_mask is not None and int(a.target_mask) & ~int(b.target_mask):
            self.last_break = b.index

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
            if not b.has_entity:
                # live replies cannot attribute a break; flag only a fighter-to-target line through a solid (replay decides)
                self.counts["break_live"] = self.counts.get("break_live", 0) + 1
                hit = self._solid_lines_between(body1, pos)
                if hit:
                    self.emit("break_occluded", ["M11"], a, b, len(hit), 0, {
                        "key": [tid], "target": tid, "target_xy": list(pos), "fighter_to_target": [list(body1), list(pos)],
                        "solid_lines_between": hit, "hitter": "unknown (no entity block)"})
                continue
            r = h + self.p.body_reach
            # hitlag starting on the break tick is the game's own sign that the fighter's attack connected
            # (itprocess.c:311 sets attack_damage, ftmain.c:4094-4134 turns it into hitlag): a melee hit at any reach
            onset = b.hitlag > 0 and a.hitlag == 0
            if onset or segment_box_hit(body0, body1, (pos[0] - r, pos[1] - r), (pos[0] + r, pos[1] + r)):
                attack = onset or a.attack_active or b.attack_active or b.status in self.p.fireball_status_ids
                hitters.append({"hitter": "fighter", "from": list(body0), "to": list(body1), "attack_flag_or_fireball_status": bool(attack),
                                "hitlag_onset": onset})
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

    def _solid_lines_between(self, frm: Tuple[float, float], pos: Tuple[float, float]) -> List[int]:
        return sorted({line.id for line in self.geo.lines if line.group not in self.moving
                       for s0, s1, f in line.segments() if not (f & VERTEX_COLL_PASS) and _segments_cross(frm, pos, s0, s1)})

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
            self._note_break(a, b)
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


class LiveScanner(Detector):
    """The same detectors fed one reply at a time, for use during a burst. Replies before `emit_from` only update the break
    history and the look-back window (no detector runs on them: they were scanned when they were a burst); events are emitted
    for steps >= emit_from. `stick_x` may be passed per step when the replies carry no input block."""

    def __init__(self, initial: Mapping[str, Any], geometry: Optional[Geometry] = None, params: Optional[Params] = None,
                 source: Optional[Mapping[str, Any]] = None, emit_from: int = 0) -> None:
        super().__init__({"initial": initial, "steps": []}, geometry, params, source)
        self.emit_from = int(emit_from)
        self.prev: Optional[State] = None
        self._raw: Optional[Tuple[int, Mapping[str, Any]]] = (-1, initial)    # the tick-0 observe pairs with step 0, as in run()
        m0 = (initial.get("spatial") or {}).get("target_live_mask")
        self._mask: Optional[int] = None if m0 is None else int(m0)
        self._recent: List[Tuple[int, int, int]] = []          # (step, status, |stick_x|), the last platform_window + 1 steps
        self._inside: Optional[Tuple[State, State, int]] = None

    def feed(self, index: int, reply: Mapping[str, Any], stick_x: Optional[int] = None) -> None:
        sp = reply.get("spatial") or {}
        m = sp.get("target_live_mask")
        if m is not None:
            if self._mask is not None and int(self._mask) & ~int(m):
                self.last_break = index
            self._mask = int(m)
        lookback = self.p.platform_window + 1
        if index < self.emit_from - lookback:
            self._raw = (index, reply)
            return
        if self.prev is None and self._raw is not None and self._raw[0] == index - 1:
            self.prev = State(*self._raw)
        s = State(index, reply)
        if stick_x is not None:
            s.stick_x = int(stick_x)
        self._recent = (self._recent + [(index, s.status, abs(s.stick_x))])[-lookback:]
        a, self.prev = self.prev, s
        if index < self.emit_from or a is None or not (a.live and s.live) or s.index != a.index + 1:
            return
        self.line_crossings(a, s)
        self.bounds(a, s)
        self.snaps(a, s)
        self.floor_switch(a, s)
        self.target_breaks(a, s)
        self.native_flags(s)
        idx = inside_solid(_point(s, self.ecb, "center"), self.solids)
        if idx is not None:
            self._inside = (self._inside[0], s, idx) if self._inside else (a, s, idx)
        elif self._inside:
            self._emit_inside(*self._inside)
            self._inside = None

    def finish(self) -> List[Dict[str, Any]]:
        if self._inside:
            self._emit_inside(*self._inside)
            self._inside = None
        return self.events

    def _platform(self, idx: int) -> List[str]:
        lo = idx + 1 - self.p.platform_window
        for step, status, stick in self._recent:
            if step >= lo and status in self.p.transn_status_ids and stick > self.p.transn_stick_threshold:
                return ["d1_transn_cosf"]
        return []


def _point_segment_distance(v: Tuple[float, float], p: Tuple[float, float], q: Tuple[float, float]) -> float:
    dx, dy = q[0] - p[0], q[1] - p[1]
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((v[0] - p[0]) * dx + (v[1] - p[1]) * dy) / L2))
    return math.hypot(p[0] + t * dx - v[0], p[1] + t * dy - v[1])


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
