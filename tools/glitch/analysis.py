"""Geometry checks that map the GLITCH_CANDIDATES.md mechanisms onto a stage's collision lines.

Every check is generic: it reads the line table and Mario's collision diamond (map_coll: top, center, bottom,
width) and reports where a mechanism's preconditions hold. Output names places; it is meant for explaining and
detecting what an agent did, not for steering an agent (no reward, route or input is derived here).

Mechanism ids (M1..M14) refer to GLITCH_CANDIDATES.md.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from geometry import (KIND_CEIL, KIND_FLOOR, KIND_LWALL, KIND_NAMES, KIND_RWALL, VERTEX_COLL_CLIFF, VERTEX_COLL_PASS,
                      Geometry, Line)

Point = Tuple[float, float]
EPS = 1e-6


@dataclass
class Ecb:
    top: float
    center: float
    bottom: float
    width: float

    @classmethod
    def parse(cls, text: str) -> "Ecb":
        vals = [float(v) for v in text.split(",")]
        if len(vals) != 4:
            raise ValueError("--ecb needs top,center,bottom,width")
        return cls(*vals)


@dataclass
class Finding:
    check: str
    mechanism: str
    status: str            # "present" (preconditions hold here), "info", "absent" (check ran, nothing found)
    detail: str
    where: Dict[str, Any] = field(default_factory=dict)


# -- small geometry helpers ------------------------------------------------------------------------------------


def face_normal(kind: int, a: Point, b: Point) -> Point:
    """Unit normal pointing to the free (face) side: floor up, ceiling down, lwall -x, rwall +x."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = (-dy, dx)
    want = {KIND_FLOOR: (0.0, 1.0), KIND_CEIL: (0.0, -1.0), KIND_LWALL: (-1.0, 0.0), KIND_RWALL: (1.0, 0.0)}[kind]
    if n[0] * want[0] + n[1] * want[1] < 0:
        n = (dy, -dx)
    length = math.hypot(*n) or 1.0
    return (n[0] / length, n[1] / length)


def ray_hit(p: Point, d: Point, segs: Sequence[Tuple[Any, Point, Point]], skip: Iterable[Any] = ()) -> Optional[Tuple[float, Any]]:
    """First segment hit by the ray p + t d (t > 1e-6): (t, key of that segment)."""
    best: Optional[Tuple[float, Any]] = None
    skip = set(skip)
    for lid, a, b in segs:
        if lid in skip:
            continue
        ex, ey = b[0] - a[0], b[1] - a[1]
        den = d[0] * ey - d[1] * ex
        if abs(den) < 1e-12:
            continue
        wx, wy = a[0] - p[0], a[1] - p[1]
        t = (wx * ey - wy * ex) / den
        u = (wx * d[1] - wy * d[0]) / den
        if t > 1e-6 and -1e-9 <= u <= 1 + 1e-9 and (best is None or t < best[0]):
            best = (t, lid)
    return best


def point_in_polygon(p: Point, poly: Sequence[Point]) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % n]
        if (y1 > p[1]) != (y2 > p[1]):
            x = x1 + (p[1] - y1) * (x2 - x1) / (y2 - y1)
            if p[0] < x:
                inside = not inside
    return inside


def segment_box_hit(a: Point, b: Point, lo: Point, hi: Point) -> bool:
    """Does segment ab intersect the axis-aligned box [lo, hi] (Liang-Barsky)?"""
    t0, t1 = 0.0, 1.0
    for axis in (0, 1):
        d = b[axis] - a[axis]
        for p, q in ((-d, a[axis] - lo[axis]), (d, hi[axis] - a[axis])):
            if abs(p) < 1e-12:
                if q < 0:
                    return False
            else:
                r = q / p
                if p < 0:
                    t0 = max(t0, r)
                else:
                    t1 = min(t1, r)
                if t0 > t1:
                    return False
    return True


def world_segments(geo: Geometry, include_pass: bool = False,
                   translate: Optional[Mapping[int, Point]] = None) -> List[Tuple[int, Point, Point]]:
    out = []
    for line in geo.lines:
        off = (translate or {}).get(line.group, (0.0, 0.0))
        for a, b, f in line.segments():
            if (f & VERTEX_COLL_PASS) and not include_pass:
                continue
            out.append((line.id, (a[0] + off[0], a[1] + off[1]), (b[0] + off[0], b[1] + off[1])))
    return out


# -- solids (closed loops of non-pass lines) -----------------------------------------------------------------------


@dataclass
class Loop:
    line_ids: List[int]
    polygon: List[Point]
    solid_inside: bool


def loops(geo: Geometry, static_only: bool = True, moving_groups: Iterable[int] = ()) -> List[Loop]:
    """Closed chains of non-pass lines joined end to end (by coordinates). solid_inside: the faces point out."""
    moving = set(moving_groups)
    cand = [l for l in geo.lines if not l.is_pass and not (static_only and l.group in moving)]
    by_end: Dict[Point, List[int]] = {}
    for l in cand:
        for p in (l.points[0], l.points[-1]):
            by_end.setdefault(p, []).append(l.id)
    used: set = set()
    out: List[Loop] = []
    lines = {l.id: l for l in cand}
    for start in cand:
        if start.id in used:
            continue
        chain, poly = [start.id], list(start.points)
        cur_end = start.points[-1]
        ok = False
        while True:
            nxt = [i for i in by_end.get(cur_end, []) if i not in chain]
            if not nxt:
                ok = cur_end == start.points[0] and len(chain) > 2
                break
            ln = lines[nxt[0]]
            pts = ln.points if ln.points[0] == cur_end else list(reversed(ln.points))
            chain.append(ln.id)
            poly.extend(pts[1:])
            cur_end = pts[-1]
            if cur_end == start.points[0]:
                ok = True
                break
        if not ok:
            continue
        used.update(chain)
        if poly[-1] == poly[0]:
            poly = poly[:-1]
        l0 = lines[chain[0]]
        a, b, _ = l0.segments()[0]
        n = face_normal(l0.kind, a, b)
        mid = ((a[0] + b[0]) / 2 + n[0], (a[1] + b[1]) / 2 + n[1])
        out.append(Loop(chain, poly, solid_inside=not point_in_polygon(mid, poly)))
    return out


def inside_solid(p: Point, solids: Sequence[Loop]) -> Optional[int]:
    for i, lp in enumerate(solids):
        if lp.solid_inside and point_in_polygon(p, lp.polygon):
            return i
    return None


# -- checks ----------------------------------------------------------------------------------------------------------


def _ranges(geo: Geometry) -> List[Tuple[int, int, List[int]]]:
    """(group, kind, line ids) in the order the sweep loops visit them."""
    if geo.raw is not None:
        return [(li.yakumono_id, k, list(range(first, first + count)))
                for li in geo.raw.line_info for k, (first, count) in enumerate(li.data) if count]
    out: List[Tuple[int, int, List[int]]] = []
    for l in geo.lines:
        if out and out[-1][0] == l.group and out[-1][1] == l.kind:
            out[-1][2].append(l.id)
        else:
            out.append((l.group, l.kind, [l.id]))
    return out


def check_sweep_order(geo: Geometry) -> List[Finding]:
    """M1: the swept-line loops stop scanning a group at the first line wholly past the sweep (goto l_break). That is
    only safe if lines are ordered: floors and right walls by descending far bound, ceilings and left walls by
    ascending near bound (mpcollision.c:949-955, 1453-1459, 1773-1779, 2314-2320)."""
    out: List[Finding] = []
    for group, kind, ids in _ranges(geo):
        ls = [geo.line(i) for i in ids]
        for i, li in enumerate(ls):
            for lj in ls[i + 1:]:
                if kind in (KIND_FLOOR, KIND_RWALL):
                    bad = lj.coll_far > li.coll_far
                    why = f"far bound {lj.coll_far} of line {lj.id} > far bound {li.coll_far} of earlier line {li.id}"
                else:
                    bad = lj.coll_near < li.coll_near
                    why = f"near bound {lj.coll_near} of line {lj.id} < near bound {li.coll_near} of earlier line {li.id}"
                if bad:
                    out.append(Finding("sweep_order", "M1", "present",
                                       f"{KIND_NAMES[kind]} lines of group {group}: {why}; a sweep that ends past line "
                                       f"{li.id} stops before testing line {lj.id}", {"lines": [li.id, lj.id], "group": group}))
    if not out:
        out.append(Finding("sweep_order", "M1", "absent", "every group/kind range is ordered as the early exits assume"))
    return out


def check_running_index(geo: Geometry) -> List[Finding]:
    """M1b: func_ovl2_800FB04C stores coll_pos and yakumono id at a running index, assuming line ids are laid out
    group by group and kind by kind. A different layout gives lines another line's bounds and group."""
    if geo.raw is None:
        return [Finding("running_index", "M1", "info", "needs the raw line_info (ROM or decomp source), not a trace")]
    out: List[Finding] = []
    l = 0
    for li in geo.raw.line_info:
        for k, (first, count) in enumerate(li.data):
            if count and first != l:
                out.append(Finding("running_index", "M1", "present",
                                   f"group {li.yakumono_id} {KIND_NAMES[k]} lines start at id {first} but the running "
                                   f"index is {l}: their coll_pos and yakumono id belong to other lines",
                                   {"group": li.yakumono_id, "kind": KIND_NAMES[k], "first": first, "running": l}))
            l += count
    for line in geo.lines:
        if line.group != line.group_seq:
            out.append(Finding("running_index", "M1", "present",
                               f"line {line.id}: swept as group {line.group} but vertex_info says group {line.group_seq}",
                               {"lines": [line.id]}))
    if not out:
        out.append(Finding("running_index", "M1", "absent", "line ids are laid out in the order the running index assumes"))
    return out


PORT_FIXED_REGIONS = ("geometry", "mapobjs", "line_info", "vertex_links", "vertex_id", "vertex_data")


def check_port_swap(geo: Geometry) -> List[Finding]:
    """M12: the PORT build rotates u16 pairs inside each u32 word of these arrays (mpcollision.c:4160-4258,
    port/bridge/lbreloc_byteswap.cpp portFixupStructU16). A region that is not word-aligned or whose last word
    overlaps another fixed region gets a word rotated twice or at the wrong boundary: PC-only geometry."""
    if geo.raw is None or not geo.raw.regions:
        return [Finding("port_swap", "M12", "info", "needs region offsets (ROM extraction or decomp source)")]
    regs = geo.raw.regions
    words: Dict[str, set] = {}
    out: List[Finding] = []
    for name in PORT_FIXED_REGIONS:
        if name not in regs:
            continue
        off, size = regs[name]
        if name == "geometry":
            words[name] = {off // 4, (off + 20) // 4}
        else:
            words[name] = set(range(off // 4, off // 4 + (size + 3) // 4))
        if off % 4:
            out.append(Finding("port_swap", "M12", "present", f"{name} starts at 0x{off:X}, not word-aligned", {"region": name}))
    names = list(words)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            both = words[a] & words[b]
            if both:
                out.append(Finding("port_swap", "M12", "present",
                                   f"{a} and {b} share word(s) {sorted(hex(4 * w) for w in both)}: rotated twice on PC",
                                   {"regions": [a, b]}))
    if not out:
        out.append(Finding("port_swap", "M12", "absent",
                           "every fixed region is word-aligned and no word is rotated twice", {"regions": {k: [hex(v[0]), v[1]] for k, v in regs.items()}}))
    return out


def check_degenerate(geo: Geometry) -> List[Finding]:
    """Data hazards: a floor/ceiling segment with equal x or a wall segment with equal y makes the getters loop
    forever (mpCollisionGetFCCommon "same vtx x error", mpCollisionGetLRCommon "same vtx y error")."""
    out: List[Finding] = []
    for l in geo.lines:
        for a, b, _ in l.segments():
            if l.kind in (KIND_FLOOR, KIND_CEIL) and a[0] == b[0]:
                out.append(Finding("degenerate", "-", "present", f"{l.kind_name} line {l.id} has a vertical segment {a}-{b}", {"lines": [l.id]}))
            if l.kind in (KIND_LWALL, KIND_RWALL) and a[1] == b[1]:
                out.append(Finding("degenerate", "-", "present", f"{l.kind_name} line {l.id} has a horizontal segment {a}-{b}", {"lines": [l.id]}))
    if not out:
        out.append(Finding("degenerate", "-", "absent", "no zero-span segment"))
    return out


def check_short_floors(geo: Geometry, cliffedge_inset: float = 40.0) -> List[Finding]:
    """M8b: mpCommonCheckSetFighterCliffEdge (mpcommon.c:24-97) evaluates the floor 40 units inside its end and uses
    floor_dist without checking the getter's result. A floor narrower than 40 leaves floor_dist, flags and angle
    uninitialised: the teeter snap then reads stack garbage (differs between N64 and PC builds)."""
    out = []
    for l in geo.lines:
        if l.kind == KIND_FLOOR:
            xs = [p[0] for p in l.points]
            span = max(xs) - min(xs)
            if span < cliffedge_inset:
                out.append(Finding("short_floor", "M8", "present", f"floor line {l.id} spans {span:g} < {cliffedge_inset:g}", {"lines": [l.id]}))
    if not out:
        out.append(Finding("short_floor", "M8", "absent", f"every floor line spans at least {cliffedge_inset:g}"))
    return out


def check_connectivity(geo: Geometry) -> List[Finding]:
    """M5/M6 context: corners (convex, concave, inconsistent), unlinked touches, dangling ends."""
    out: List[Finding] = []
    ends: Dict[Point, List[Tuple[Line, int]]] = {}
    for l in geo.lines:
        ends.setdefault(l.points[0], []).append((l, 0))
        ends.setdefault(l.points[-1], []).append((l, -1))
    convex = concave = odd = 0
    for p, items in sorted(ends.items()):
        if len(items) == 1:
            l = items[0][0]
            out.append(Finding("dangling_end", "M5", "info", f"{l.kind_name} line {l.id} ends at {p} with no neighbour"
                               + (" (pass-through)" if l.is_pass else ""), {"lines": [l.id], "point": list(p)}))
            continue
        if len(items) > 2:
            out.append(Finding("multi_join", "M5", "present", f"{len(items)} line ends meet at {p}", {"lines": [i[0].id for i in items], "point": list(p)}))
        (la, ia), (lb, ib) = items[0], items[1]
        if la.vertex_index and lb.vertex_index and la.vertex_index[ia] != lb.vertex_index[ib]:
            out.append(Finding("unlinked_touch", "M5", "present",
                               f"lines {la.id} and {lb.id} touch at {p} through different vertex indices: the game's edge "
                               "links (by index) do not join them, so edge-based corner handling is skipped",
                               {"lines": [la.id, lb.id], "point": list(p)}))
        segs = []
        for l, i in ((la, ia), (lb, ib)):
            s = l.segments()[0] if i == 0 else l.segments()[-1]
            other = s[1] if i == 0 else s[0]
            d = (other[0] - p[0], other[1] - p[1])
            nrm = face_normal(l.kind, s[0], s[1])
            segs.append((l, d, nrm))
        (l1, d1, n1), (l2, d2, n2) = segs
        u1 = (d1[0] / math.hypot(*d1), d1[1] / math.hypot(*d1))
        u2 = (d2[0] / math.hypot(*d2), d2[1] / math.hypot(*d2))
        bis = (u1[0] + u2[0], u1[1] + u2[1])
        if math.hypot(*bis) < 1e-9:
            kind = "straight"
        else:
            q = (bis[0] * 1e-3, bis[1] * 1e-3)
            s1, s2 = q[0] * n1[0] + q[1] * n1[1], q[0] * n2[0] + q[1] * n2[1]
            kind = "convex" if (s1 < 0 and s2 < 0) else "concave" if (s1 > 0 and s2 > 0) else "inconsistent"
        angle = math.degrees(math.acos(max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1]))))
        if kind == "convex":
            convex += 1
        elif kind == "concave":
            concave += 1
        else:
            odd += 1
        status = "present" if kind in ("convex", "inconsistent") else "info"
        mech = "M6" if kind == "inconsistent" else "M5"
        out.append(Finding("corner", mech, status,
                           f"{kind} corner {angle:.0f} deg at {p}: {l1.kind_name} {l1.id} / {l2.kind_name} {l2.id}",
                           {"lines": [l1.id, l2.id], "point": list(p), "corner": kind, "angle_deg": round(angle, 3)}))
    bends = 0
    for l in geo.lines:
        for i in range(1, len(l.points) - 1):
            p, pa, pb = l.points[i], l.points[i - 1], l.points[i + 1]
            n1 = face_normal(l.kind, pa, p)
            n2 = face_normal(l.kind, p, pb)
            u1 = (pa[0] - p[0], pa[1] - p[1])
            u2 = (pb[0] - p[0], pb[1] - p[1])
            m1, m2 = math.hypot(*u1), math.hypot(*u2)
            u1, u2 = (u1[0] / m1, u1[1] / m1), (u2[0] / m2, u2[1] / m2)
            bis = (u1[0] + u2[0], u1[1] + u2[1])
            angle = math.degrees(math.acos(max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1]))))
            if math.hypot(*bis) < 1e-9:
                continue
            q = (bis[0] * 1e-3, bis[1] * 1e-3)
            s1, s2 = q[0] * n1[0] + q[1] * n1[1], q[0] * n2[0] + q[1] * n2[1]
            kind = "convex" if (s1 < 0 and s2 < 0) else "concave" if (s1 > 0 and s2 > 0) else "inconsistent"
            bends += 1
            out.append(Finding("bend", "M6" if kind == "inconsistent" else "M5", "present" if kind != "concave" else "info",
                               f"{kind} bend {angle:.0f} deg inside {l.kind_name} line {l.id} at {p} (slope change: "
                               "the wall vertex rule of mpProcessRun*WallCollision applies)",
                               {"lines": [l.id], "point": list(p), "corner": kind, "angle_deg": round(angle, 3)}))
    out.append(Finding("corner_summary", "M5", "info", f"{convex} convex, {concave} concave, {odd} other corners at line ends; {bends} bends inside lines"))
    return out


def check_passages_and_thickness(geo: Geometry, ecb: Ecb, moving_groups: Iterable[int] = (), step: float = 25.0) -> List[Finding]:
    """M2 (narrow passage: opposite contacts in one update, the last resolution wins), M3 (thin solid: fits between
    the swept diamond points), M4 (ground path has no ceiling test). Axis rays from each solid line."""
    moving = set(moving_groups)
    static = [((l.id, k), a, b) for l in geo.lines if not l.is_pass and l.group not in moving
              for k, (a, b, _) in enumerate(l.segments())]
    best_gap: Dict[Tuple[int, int], Tuple[float, Point]] = {}
    best_thick: Dict[Tuple[int, int], Tuple[float, Point]] = {}
    for l in geo.lines:
        if l.is_pass or l.group in moving:
            continue
        axis = (0.0, 1.0) if l.kind == KIND_FLOOR else (0.0, -1.0) if l.kind == KIND_CEIL else (-1.0, 0.0) if l.kind == KIND_LWALL else (1.0, 0.0)
        for k, (a, b, _) in enumerate(l.segments()):
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            n = max(2, int(length // step))
            for i in range(n + 1):
                t = min(max(i / n, 0.002), 0.998)
                p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                for table, d in ((best_gap, axis), (best_thick, (-axis[0], -axis[1]))):
                    hit = ray_hit(p, d, static, skip=[(l.id, k)])
                    if hit is None:
                        continue
                    key = (l.id, hit[1][0])
                    if key not in table or hit[0] < table[key][0]:
                        table[key] = (hit[0], p)
    out: List[Finding] = []
    horiz_full, horiz_center = 2 * ecb.width, ecb.width
    vert_full, vert_center = ecb.top - ecb.bottom, ecb.center - ecb.bottom
    seen = set()
    for (src, dst), (dist, p) in sorted(best_gap.items(), key=lambda kv: kv[1][0]):
        ls, ld = geo.line(src), geo.line(dst)
        pair = tuple(sorted((src, dst)))
        if pair in seen:
            continue
        seen.add(pair)
        if ls.kind in (KIND_LWALL, KIND_RWALL):
            if dist < horiz_full - 1e-3:
                sev = "center" if dist < horiz_center else "side vertex"
                out.append(Finding("narrow_passage", "M2", "present",
                                   f"horizontal gap {dist:g} between {ls.kind_name} {src} and {ld.kind_name} {dst} near {p} "
                                   f"< diamond width {horiz_full:g}: both walls can push in one update ({sev} ends inside a solid)",
                                   {"lines": [src, dst], "gap": dist, "point": list(p), "axis": "x"}))
        else:
            if dist < vert_full - 1e-3:
                sev = "center" if dist < vert_center else "top vertex"
                mech = "M4" if ls.kind == KIND_FLOOR and ld.kind == KIND_CEIL else "M2"
                out.append(Finding("low_clearance", mech, "present",
                                   f"vertical clearance {dist:g} between {ls.kind_name} {src} and {ld.kind_name} {dst} near {p} "
                                   f"< diamond height {vert_full:g} ({sev} would be past the ceiling while grounded)",
                                   {"lines": [src, dst], "gap": dist, "point": list(p), "axis": "y"}))
    seen.clear()
    for (src, dst), (dist, p) in sorted(best_thick.items(), key=lambda kv: kv[1][0]):
        ls, ld = geo.line(src), geo.line(dst)
        pair = tuple(sorted((src, dst)))
        if pair in seen:
            continue
        seen.add(pair)
        horizontal = ls.kind in (KIND_LWALL, KIND_RWALL)
        # A solid can slip between two swept diamond points only if it is thinner than their spacing: vertically
        # bottom->side (center-bottom) or side->top (top-center); horizontally the side vertex is `width` from the
        # bottom/top column.
        limits = [("width", ecb.width)] if horizontal else [("center-bottom", vert_center), ("top-center", ecb.top - ecb.center)]
        under = [name for name, v in limits if dist < v - 1e-3]
        if under:
            out.append(Finding("thin_solid", "M3", "present",
                               f"solid between {ls.kind_name} {src} and {ld.kind_name} {dst} is {dist:g} thick near {p} "
                               f"along {'x' if horizontal else 'y'} (< {', '.join(under)})",
                               {"lines": [src, dst], "thickness": dist, "point": list(p), "axis": "x" if horizontal else "y"}))
    for chk, mech in (("narrow_passage", "M2"), ("low_clearance", "M4"), ("thin_solid", "M3")):
        if not any(f.check == chk for f in out):
            out.append(Finding(chk, mech, "absent", f"no {chk.replace('_', ' ')} below the diamond thresholds"))
    return out


def check_pass_and_cliff(geo: Geometry) -> List[Finding]:
    out = []
    for l in geo.lines:
        if l.is_pass:
            out.append(Finding("pass_line", "M9", "info", f"{l.kind_name} line {l.id} (group {l.group}) is pass-through: landed on "
                               "only from above with downward motion; ignored while dropping through", {"lines": [l.id]}))
        if l.is_cliff:
            out.append(Finding("cliff_line", "M8", "info", f"line {l.id} has the ledge-grab flag", {"lines": [l.id]}))
    if not any(f.check == "cliff_line" for f in out):
        out.append(Finding("cliff_line", "M8", "absent", "no line carries the ledge-grab (cliff) flag: no ledge grab on this stage"))
    return out


def check_moving_band(geo: Geometry, ecb: Ecb, ranges: Mapping[int, Tuple[float, float, float, float]]) -> List[Finding]:
    """M7: the area a moving group's lines sweep (translate range), grown by the diamond, against static lines.
    Static ceilings or walls in it can be met while carried (the grounded path has no ceiling test)."""
    out: List[Finding] = []
    static = [s for s in world_segments(geo, include_pass=True) if geo.line(s[0]).group not in ranges]
    for gid, (x0, x1, y0, y1) in ranges.items():
        for l in geo.lines:
            if l.group != gid:
                continue
            xs = [p[0] for p in l.points]
            ys = [p[1] for p in l.points]
            lo = (min(xs) + x0 - ecb.width, min(ys) + y0 + ecb.bottom)
            hi = (max(xs) + x1 + ecb.width, max(ys) + y1 + ecb.top)
            hits = sorted({sid for sid, a, b in static if segment_box_hit(a, b, lo, hi)})
            status = "present" if hits else "absent"
            out.append(Finding("moving_band", "M7", status,
                               f"group {gid} line {l.id} sweeps x {lo[0]:g}..{hi[0]:g}, y {lo[1]:g}..{hi[1]:g} with the diamond; "
                               + (f"static lines inside: {hits}" if hits else "no static line inside"),
                               {"lines": [l.id] + hits, "box": [list(lo), list(hi)]}))
    if not ranges:
        out.append(Finding("moving_band", "M7", "info", "no moving-group range given (use --trace or --group-range)"))
    return out


def check_targets(geo: Geometry, targets: Sequence[Tuple[int, float, float, bool]], half_extent: float, reach: float,
                  solids: Sequence[Loop]) -> List[Finding]:
    """M11: target hurtboxes are boxes (half-extent from the item attributes) tested against swept hitboxes with no
    line-of-sight; a box that a solid line crosses can be hit from the other side of that line."""
    out: List[Finding] = []
    segs = world_segments(geo)
    for tid, x, y, animated in targets:
        lo, hi = (x - half_extent - reach, y - half_extent - reach), (x + half_extent + reach, y + half_extent + reach)
        hits = sorted({sid for sid, a, b in segs if segment_box_hit(a, b, lo, hi)})
        if hits:
            out.append(Finding("target_through_line", "M11", "present",
                               f"target {tid} at ({x:g}, {y:g}){' (animated)' if animated else ''}: its hurtbox grown by {reach:g} "
                               f"crosses solid lines {hits}: hittable from behind them", {"target": tid, "lines": hits}))
        if inside_solid((x, y), solids) is not None:
            out.append(Finding("target_in_solid", "M11", "present", f"target {tid} centre is inside a solid", {"target": tid}))
    if not targets:
        out.append(Finding("target_through_line", "M11", "info", "no target positions given (use --trace)"))
    elif not any(f.check == "target_through_line" for f in out):
        out.append(Finding("target_through_line", "M11", "absent", "no target hurtbox reaches a solid line"))
    return out


def check_bounds(geo: Geometry) -> List[Finding]:
    xs = [p[0] for l in geo.lines for p in l.points]
    ys = [p[1] for l in geo.lines for p in l.points]
    h = geo.header
    if not h:
        return [Finding("bounds", "M10", "info", "no header bounds available")]
    return [Finding("bounds", "M10", "info",
                    f"lines span x {min(xs):g}..{max(xs):g}, y {min(ys):g}..{max(ys):g}; map (death) bounds x "
                    f"{h.get('map_bound_left')}..{h.get('map_bound_right')}, y {h.get('map_bound_bottom')}..{h.get('map_bound_top')}; "
                    f"camera bounds x {h.get('camera_bound_left')}..{h.get('camera_bound_right')}, y "
                    f"{h.get('camera_bound_bottom')}..{h.get('camera_bound_top')}", dict(h))]


def run_all(geo: Geometry, ecb: Ecb, moving_ranges: Mapping[int, Tuple[float, float, float, float]] = {},
            targets: Sequence[Tuple[int, float, float, bool]] = (), target_half_extent: float = 150.0,
            target_reach: float = 100.0) -> Dict[str, Any]:
    solids = [lp for lp in loops(geo, moving_groups=moving_ranges.keys())]
    findings: List[Finding] = []
    findings += check_sweep_order(geo)
    findings += check_running_index(geo)
    findings += check_port_swap(geo)
    findings += check_degenerate(geo)
    findings += check_short_floors(geo)
    findings += check_connectivity(geo)
    findings += check_passages_and_thickness(geo, ecb, moving_ranges.keys())
    findings += check_pass_and_cliff(geo)
    findings += check_moving_band(geo, ecb, moving_ranges)
    findings += check_targets(geo, targets, target_half_extent, target_reach, solids)
    findings += check_bounds(geo)
    summary: Dict[str, Dict[str, int]] = {}
    for f in findings:
        summary.setdefault(f.check, {}).setdefault(f.status, 0)
        summary[f.check][f.status] += 1
    return {
        "schema": "btt_glitch_candidates_v1",
        "geometry_sha256": geo.sha256(),
        "origin": geo.origin,
        "ecb": asdict(ecb),
        "lines": len(geo.lines),
        "solids": [{"lines": lp.line_ids, "polygon": [list(p) for p in lp.polygon], "solid_inside": lp.solid_inside} for lp in solids],
        "summary": summary,
        "findings": [asdict(f) for f in findings],
        "notes": list(geo.notes),
    }


def to_markdown(result: Mapping[str, Any]) -> str:
    lines = [f"# Glitch geometry candidates ({result['origin']})", "",
             f"geometry sha256 `{result['geometry_sha256']}`, {result['lines']} lines, ECB {result['ecb']}", "",
             "Generated locally by tools/glitch/glitch.py. Names places; for explaining and detecting, not for steering an agent.", "",
             "| check | present | info | absent |", "| --- | ---: | ---: | ---: |"]
    for chk, c in result["summary"].items():
        lines.append(f"| {chk} | {c.get('present', 0)} | {c.get('info', 0)} | {c.get('absent', 0)} |")
    lines += ["", "| status | mechanism | check | detail |", "| --- | --- | --- | --- |"]
    order = {"present": 0, "info": 1, "absent": 2}
    for f in sorted(result["findings"], key=lambda f: (order.get(f["status"], 3), f["mechanism"], f["check"])):
        lines.append(f"| {f['status']} | {f['mechanism']} | {f['check']} | {f['detail'].replace('|', '/')} |")
    if result.get("notes"):
        lines += ["", "Notes:"] + [f"- {n}" for n in result["notes"]]
    return "\n".join(lines) + "\n"
