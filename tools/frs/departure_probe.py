#!/usr/bin/env python3
"""Departure probe (lab, exploratory, unregistered): is the band of the moving-group cycle in which the verified clears leave the
moving collision group forced by the geometry, or inherited habit?

The probe takes one verified lab clear (default: the fastest VERIFIED clear in the lab's verification records) and reads everything
from that clear's own verified traces, never from a constant: the non-static collision groups (a group whose recorded translation
takes more than one value), their lines (the observe-only line table), the fighter's contact intervals with them (floor_line_id is
one of the group's lines), the departure, the group's motion period, and the break that followed. No line id, group id, coordinate,
height, period, target id or tick number is written in this file.

    contact interval  [C0, C1]: a maximal run of ticks whose floor_line_id belongs to the group; with several, the one with the
                      largest ride-or-still count (ticks grounded on the group, or with the position unchanged from the previous tick)
    airborne exit     G = the interval's last grounded tick; the exit is the airborne run G + 1 .. C1 that leaves the group
    departure D       the tick before the status run that contains G began (the exit's onset: the clear's word at index D starts the
                      exit). The state at input tick D is the clear's last state on the group before the exit
    baseline B        the first break after D in the verified clear (input tick, as the native target records report it)
    period P          the median gap between successive turning points of the group's translation (same kind), measured from the
                      clear's own series; phase(t) = (t - first bottom turning point) mod P
    window            earlier departures d in [F, D] (F: the interval's first grounded tick; the words of the clear up to d), later
                      departures d in (D, D + P] (the clear's words up to D, then the neutral canonical word while the fighter stays
                      grounded on the group, checked natively)
    on-group breaks   the clear's breaks with F <= tick <= D; a departure d before one of them is a pre-break departure (its own part
                      of the curve and of every table)
    exits at each d   (a) the clear's own exit words D .. B, shifted to start at d, then the neutral word up to the budget;
                      (g1 .. gK) the lab burst generator (rl/frs_archive.stream_words: the m8_rd_explore_v1 keyed stream) with the
                      recorded Python seed in its key family; the same K streams at every d (common random numbers)
    budget            E = ceil(budget_factor * (B - D)) exit words after d

Per candidate (one fresh BattleShip process from tick 0 with the verify flags, process restart for every candidate): the tick
contract of every step (consumed_tick = T, input_tick = T + 1, step_count = T + 1) and the native action digest (any failure ends the
run as PROBE_INVALID), the pinned game files (re-hashed by rl/frs_verify before every replay, controls included; a change, pin drift,
ends the run as PROBE_INVALID on the first detection), the prefix digest (the m8_rd chain at d against the verified clear's chain, or against the filler reference
replay for later departures; a mismatch retires that process, is logged, and the run continues with fresh processes; three mismatches
abort the run), the candidate's own departure measured with the D rule (departure_tick; a row counts only when it departs at d), the
first break after d (tick from tick 0, target id as the native target records report it, whether it is the target the baseline broke
next), the progress tick (the first tick after d whose live-target mask is a subset of the baseline's at B: the candidate has broken
every target the baseline had, in any order; it beats B when the progress tick is before B), the end states at those ticks.

The probe never extends a candidate to a full clear and never claims a clear. Nothing here reads, logs, controls, compares or hashes
native RNG state. Process restart resets the episode; no soft reset.

    python -B tools/frs/departure_probe.py --dry-run [--lab-root C:/BattleShip_lab] [--clear best|RUN:N:CID] [--variants K]
                                           [--seed S] [--budget-factor F] [--band] [--list]
    python -B tools/frs/departure_probe.py run --out DIR --expect-digest HEX --expect-band HEX --expect-head SHA [same options]
                                           [--slots 5] [--max-wall-min 45]

--dry-run is zero native ticks: it reads only the chosen clear's verification row and its two verified traces (plus, for the cost
estimate, the lab's existing replay-timing records; with --band, the other verified clears' traces and the band digest), writes
nothing, takes no lock. `run` writes only under DIR inside the lab root (rl/frs_guard; never under the lab's import folder), takes
lab.lock, refuses (exit 2) on readiness (registered thresholds, never lowered), on running BattleShip processes, on the import pins,
on tracked changes under tools/, rl/ or docs/, when HEAD differs from --expect-head, when the candidate set differs from
--expect-digest or the band from --expect-band, and on an existing DIR that holds anything but this plan's plan.json,
candidates.jsonl and refused_*.json. The native time is capped at --max-wall-min (at most 45); a run stopped by the cap is PARTIAL.
Zero-tick tests: tools/frs/departure_probe_tests.py. Run with python -B.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import gzip
import hashlib
import json
import math
import statistics
import subprocess
import sys
import threading
import traceback
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Mapping, Optional, Sequence, Tuple

assert sys.flags.dont_write_bytecode, "run with python -B"

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "rl"))

import frs_archive as fa  # noqa: E402
import frs_guard as g  # noqa: E402
import frs_machine as fm  # noqa: E402
import frs_report as frep  # noqa: E402
import frs_verify as fv  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_claims as mclaims  # noqa: E402
import m8_rd_worker as mw  # noqa: E402

PROBE_CONTRACT = "frs_departure_probe_v1"
KEY_FAMILY = "departure"
VARIANT_CLEAR = "a"
MAX_WALL_MIN = 45.0                     # owner, 2026-11-02: hard cap of the probe's native time
FAILED_SHARE_MAX = 0.10                 # INCONCLUSIVE above this share of planned candidates that failed to run
MISMATCH_ABORT = 3                      # prefix-digest mismatches that abort the run
EXIT = {"COMPLETED": 0, "PARTIAL": 0, "MEMORY_BUDGET": 0, "REFUSED": 2, "ABORTED": 3, "PROBE_INVALID": 3, "PROBE_INCOMPLETE": 4}
STATUS_RANK = {"COMPLETED": 0, "PARTIAL": 1, "MEMORY_BUDGET": 1, "ABORTED": 2, "PROBE_INCOMPLETE": 2, "PROBE_INVALID": 3}
NOT_FORCED, FORCED_IN_PROBE, INCONCLUSIVE, IN_BAND_GAIN = "NOT_FORCED", "FORCED_IN_PROBE", "INCONCLUSIVE", "IN_BAND_GAIN"
NEUTRAL_WORD = mcell.TRIPLES.index((0, 0, 0))          # the canonical Track 1 word with no button and a centred stick
TRACKED_DIRS = ("tools", "rl", "docs")                  # owner, 2026-11-03: a run refuses any tracked change under these


class ProbeError(RuntimeError):
    """A violated probe invariant, or a field the method needs that the records lack (zero-tick)."""


class Refused(Exception):
    """Open-phase refusal: nothing was launched."""


# -- trace access ----------------------------------------------------------------------------------------------------------------------


def reply_at(trace: Mapping[str, Any], t: int) -> Mapping[str, Any]:
    """The reply after input tick t (t = 0: the tick-0 observe reply)."""
    return trace["initial"] if t == 0 else trace["steps"][t - 1]


def last_tick(trace: Mapping[str, Any]) -> int:
    return len(trace["steps"])


def chain_list(trace: Mapping[str, Any]) -> List[bytes]:
    """chain[t] = the m8_rd chain digest over the records of input ticks 0 .. t (the lab's prefix digest)."""
    ch = [mcell.chain_start(mcell.tick0_record(trace["initial"]))]
    for s in trace["steps"]:
        ch.append(mcell.chain_next(ch[-1], mcell.record_digest(mcell.record_of(s))))
    return ch


def grounded(r: Mapping[str, Any]) -> bool:
    return int(r["observation"]["ground_air_state"]) == 0                 # m8_rd_cell_v1: grounded = ground_air_state == 0


def floor_line(r: Mapping[str, Any]) -> int:
    return int(r["spatial"]["fighter"]["floor_line_id"])


def position(r: Mapping[str, Any]) -> Tuple[float, float]:
    o = r["observation"]
    return float(o["position_x"]), float(o["position_y"])


def live_mask(r: Mapping[str, Any]) -> int:
    return int(r["spatial"]["target_live_mask"])


def group_translation(r: Mapping[str, Any], gid: int) -> Optional[List[float]]:
    for gr in r["spatial"]["groups"]:
        if int(gr["id"]) == int(gid):
            return [float(v) for v in gr["translate"]]
    return None


REQUIRED_STEP = {"observation": ("input_tick", "ground_air_state", "fighter_status_id", "position_x", "position_y", "air_velocity_x",
                                 "air_velocity_y", "ground_velocity_x", "jumps_used", "facing_direction"),
                 "spatial": ("fighter", "groups", "target_live_mask"), "targets": ("records",)}


def required_field_problems(trace: Mapping[str, Any]) -> List[str]:
    """Every field the method reads, on every reply; a missing field stops the probe (never substituted)."""
    out: List[str] = []
    init = trace.get("initial") or {}
    lines = (init.get("spatial") or {}).get("lines")
    if not lines:
        out.append("initial.spatial.lines (the observe-only line table with each line's group) is missing")
    elif any("id" not in ln or "group" not in ln for ln in lines):
        out.append("initial.spatial.lines: a line without id or group")
    if not trace.get("steps"):
        out.append("the trace has no steps")
    for t in range(0, len(trace.get("steps") or []) + 1):
        r = reply_at(trace, t)
        for part, keys in REQUIRED_STEP.items():
            if part == "targets" and t == 0:
                continue
            obj = r.get(part)
            if not isinstance(obj, Mapping):
                out.append(f"tick {t}: {part} is missing")
                continue
            for k in keys:
                if k not in obj:
                    out.append(f"tick {t}: {part}.{k} is missing")
        fi = (r.get("spatial") or {}).get("fighter") or {}
        if "floor_line_id" not in fi:
            out.append(f"tick {t}: spatial.fighter.floor_line_id is missing")
        for gr in (r.get("spatial") or {}).get("groups") or []:
            if "id" not in gr or "translate" not in gr:
                out.append(f"tick {t}: spatial.groups entry without id or translate")
                break
        if t > 0:
            for rec in (r.get("targets") or {}).get("records") or []:
                if "id" not in rec or "break_input_tick" not in rec:
                    out.append(f"tick {t}: targets.records entry without id or break_input_tick")
                    break
        if len(out) > 20:
            break
    return out


def native_breaks(trace: Mapping[str, Any]) -> Tuple[List[List[int]], List[Dict[str, Any]]]:
    """[[input tick, target id]] in tick order: a break is a tick whose live-target mask loses bits; its target id is the native target
    identity record whose break_input_tick is that tick (as reported). Anomalies (mask and records disagree) are returned, never hidden."""
    out: List[List[int]] = []
    anomalies: List[Dict[str, Any]] = []
    prev = live_mask(reply_at(trace, 0))
    for t in range(1, last_tick(trace) + 1):
        r = reply_at(trace, t)
        m = live_mask(r)
        gone = prev & ~m
        if gone:
            ids = sorted(int(x["id"]) for x in r["targets"]["records"] if int(x["break_input_tick"]) == t)
            bits = [i for i in range(gone.bit_length()) if gone >> i & 1]
            if ids != bits:
                anomalies.append({"tick": t, "record_ids": ids, "mask_bits": bits})
            out.extend([t, i] for i in ids)
        prev = m
    return out, anomalies


# -- geometry from the clear's own trace (zero native ticks) ------------------------------------------------------------------------------


def line_groups(trace: Mapping[str, Any]) -> Dict[int, int]:
    """{line id: group id} from the observe-only line table of the tick-0 reply."""
    return {int(ln["id"]): int(ln["group"]) for ln in trace["initial"]["spatial"]["lines"]}


def group_series(trace: Mapping[str, Any]) -> Dict[int, List[List[float]]]:
    """{group id: [translation at input tick 0 .. n]} for every group present on every reply."""
    ids = [int(gr["id"]) for gr in trace["initial"]["spatial"]["groups"]]
    out: Dict[int, List[List[float]]] = {gid: [] for gid in ids}
    for t in range(0, last_tick(trace) + 1):
        r = reply_at(trace, t)
        for gid in ids:
            tr = group_translation(r, gid)
            if tr is None:
                raise ProbeError(f"group {gid} is missing from the reply of tick {t}")
            out[gid].append(tr)
    return out


def moving_groups(series: Mapping[int, Sequence[Sequence[float]]], lines: Mapping[int, int]) -> List[Dict[str, Any]]:
    """Every group whose recorded translation takes more than one value: its lines, the range of each component and the moving axis
    (the component with the largest range)."""
    out = []
    for gid, ser in sorted(series.items()):
        dims = len(ser[0])
        ranges = [[min(v[i] for v in ser), max(v[i] for v in ser)] for i in range(dims)]
        widths = [hi - lo for lo, hi in ranges]
        if max(widths) <= 0.0:
            continue
        axis = max(range(dims), key=lambda i: (widths[i], -i))
        out.append({"group": int(gid), "lines": sorted(ln for ln, gg in lines.items() if gg == gid), "ranges": ranges, "axis": axis,
                    "other_axes_moving": [i for i in range(dims) if i != axis and widths[i] > 0.0]})
    return out


def contact_intervals(trace: Mapping[str, Any], groups: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Every maximal run of ticks whose floor_line_id is a line of a moving group, with its riding (grounded), still (position unchanged
    from the previous tick) and ride-or-still counts."""
    out = []
    n = last_tick(trace)
    for gm in groups:
        lines = set(gm["lines"])
        t = 0
        while t <= n:
            if floor_line(reply_at(trace, t)) not in lines:
                t += 1
                continue
            s = t
            while t + 1 <= n and floor_line(reply_at(trace, t + 1)) in lines:
                t += 1
            e = t
            ride = still = both = 0
            for k in range(s, e + 1):
                r = reply_at(trace, k)
                gr = grounded(r)
                st = k > 0 and position(r) == position(reply_at(trace, k - 1))
                ride += int(gr)
                still += int(st)
                both += int(gr or st)
            out.append({"group": int(gm["group"]), "start": s, "end": e, "ticks": e - s + 1, "riding": ride, "still": still, "ride_or_still": both,
                        "ends_trace": e == n})
            t = e + 1
    return out


def pick_interval(intervals: Sequence[Mapping[str, Any]]) -> int:
    if not intervals:
        raise ProbeError("the clear never has a floor line of a moving group: no contact interval")
    return max(range(len(intervals)), key=lambda i: (intervals[i]["ride_or_still"], -intervals[i]["start"]))


def departure_core(trace: Mapping[str, Any], s: int, e: int) -> Dict[str, Any]:
    """The departure rule on the contact run [s, e] (floor line on the group), shared by the probed clear's D, the band's sources and every
    candidate's measured departure: F (first grounded tick), G (last grounded tick), A = G + 1 (first tick of the airborne exit), S (first
    tick of the status run that contains G), D = max(s, S - 1) (the exit's onset). `kind` is 'airborne' when the rule applies; otherwise
    'no_exit' (the run reaches the end of the trace), 'never_grounded', 'left_grounded' (grounded at G + 1) or 'onset_before_grounded'."""
    if e >= last_tick(trace):
        return {"kind": "no_exit", "C0": s, "C1": e}
    ground = [t for t in range(s, e + 1) if grounded(reply_at(trace, t))]
    if not ground:
        return {"kind": "never_grounded", "C0": s, "C1": e}
    F, G = ground[0], ground[-1]
    if grounded(reply_at(trace, G + 1)):
        return {"kind": "left_grounded", "C0": s, "C1": e, "F": F, "G": G}
    status = int(reply_at(trace, G)["observation"]["fighter_status_id"])
    S = G
    while S - 1 >= s and int(reply_at(trace, S - 1)["observation"]["fighter_status_id"]) == status:
        S -= 1
    D = max(s, S - 1)
    return {"kind": "airborne" if D >= F else "onset_before_grounded", "C0": s, "F": F, "C1": e, "L": e + 1, "G": G, "A": G + 1, "S": S, "D": D,
            "status_G": status}


def departure_of(trace: Mapping[str, Any], iv: Mapping[str, Any]) -> Dict[str, Any]:
    """The departure rule (departure_core) on the chosen contact interval, refused when it does not apply. F is the earlier window's start;
    the clear's word at index D starts the exit; C1 is the interval's last tick and L = C1 + 1 the first tick whose floor line is off the
    group."""
    s, e = int(iv["start"]), int(iv["end"])
    if iv["ends_trace"]:
        raise ProbeError("the contact interval reaches the end of the trace: no exit")
    dc = departure_core(trace, s, e)
    if dc["kind"] == "never_grounded":
        raise ProbeError("the fighter is never grounded on the group in the contact interval: no departure from it")
    if dc["kind"] == "left_grounded":
        raise ProbeError(f"the fighter leaves the group grounded at tick {dc['G'] + 1} (no airborne exit)")
    if dc["kind"] != "airborne":
        raise ProbeError(f"the exit's onset {dc.get('D')} precedes the first grounded tick {dc.get('F')} on the group: no grounded departure window")
    F, G, D = dc["F"], dc["G"], dc["D"]
    st = lambda t: int(reply_at(trace, t)["observation"]["fighter_status_id"])  # noqa: E731
    return {"C0": s, "F": F, "C1": e, "L": e + 1, "G": G, "A": G + 1, "S": dc["S"], "D": D, "status_D": st(D), "status_G": st(G), "status_A": st(G + 1),
            "grounded_D": grounded(reply_at(trace, D)), "floor_line_D": floor_line(reply_at(trace, D)),
            "alternatives": {"last_contact_tick": e, "last_grounded_tick": G, "onset_tick": D}}


def measured_departure(trace: Mapping[str, Any], d: int, lines: set) -> Dict[str, Any]:
    """A candidate's own departure, by the D rule (departure_core) on the contact run (floor line on the group) that contains d.
    `reason`: 'at_d' (departure_tick == d), 'later', 'earlier', or why there is no departure tick ('not_on_group_at_d', 'no_exit' = still
    on the group's line when the trace ends, 'never_grounded', 'left_grounded', 'onset_before_grounded'). `floor_line_leave_tick` is the
    first tick after d whose floor line is off the group (floor-line based, never used for the band)."""
    n = last_tick(trace)
    if d > n or floor_line(reply_at(trace, d)) not in lines:
        return {"departure_tick": None, "kind": "not_on_group_at_d", "reason": "not_on_group_at_d", "floor_line_leave_tick": None}
    s, e = d, d
    while s - 1 >= 0 and floor_line(reply_at(trace, s - 1)) in lines:
        s -= 1
    while e + 1 <= n and floor_line(reply_at(trace, e + 1)) in lines:
        e += 1
    dc = departure_core(trace, s, e)
    out = {"departure_tick": None, "kind": dc["kind"], "reason": dc["kind"], "floor_line_leave_tick": e + 1 if e < n else None,
           "detail": {k: dc[k] for k in ("C0", "F", "G", "A", "S", "status_G") if k in dc}}
    if dc["kind"] == "airborne":
        D = int(dc["D"])
        out.update(departure_tick=D, reason="at_d" if D == d else "later" if D > d else "earlier")
    return out


def line_span(trace: Mapping[str, Any], t: int, line: int, gid: int, axis: int) -> Optional[List[float]]:
    """The world extent of a line across the group's moving axis at tick t: its observe-only vertices (local to its group) plus the group's
    recorded translation."""
    ln = next((x for x in trace["initial"]["spatial"]["lines"] if int(x["id"]) == int(line)), None)
    tr = group_translation(reply_at(trace, t), gid)
    if ln is None or tr is None or not ln.get("vertices"):
        return None
    other = 1 - int(axis) if len(tr) == 2 else 0
    vals = [float(v[other]) + float(tr[other]) for v in ln["vertices"]]
    return [min(vals), max(vals)]


def run_lengths(vals: Sequence[Any]) -> List[List[Any]]:
    out: List[List[Any]] = []
    for v in vals:
        if out and out[-1][0] == v:
            out[-1][1] += 1
        else:
            out.append([v, 1])
    return out


def exit_run_of(trace: Mapping[str, Any], geo: Mapping[str, Any], clf: Any) -> Dict[str, Any]:
    """What the record shows from the first airborne tick A to the interval's last tick C1 and at L = C1 + 1: ground / air, the status runs
    with their classes, the fighter's position and height above the group's line (spatial.fighter.floor_dist when recorded), the line's
    extent across the moving axis, and the floor line reported at L. floor_line_id names the floor line under the fighter, airborne or not."""
    dep, gid, axis = geo["departure"], geo["group"], geo["axis"]
    A, C1, L = int(dep["A"]), int(dep["C1"]), int(dep["L"])
    other = 1 - int(axis)
    key = ("position_x", "position_y")[other]

    def at(t: int) -> Dict[str, Any]:
        r = reply_at(trace, t)
        o, f = r["observation"], r["spatial"]["fighter"]
        fl = floor_line(r)
        return {"tick": t, "grounded": grounded(r), "status": int(o["fighter_status_id"]), "status_class": clf.name(o["fighter_status_id"]),
                "x": round(float(o["position_x"]), 1), "y": round(float(o["position_y"]), 1), "air_vx": round(float(o["air_velocity_x"]), 1),
                "air_vy": round(float(o["air_velocity_y"]), 1), "floor_line_id": fl, "floor_dist": round(float(f["floor_dist"]), 1) if "floor_dist" in f else None,
                "floor_line_span": line_span(trace, t, fl, int(geo["lines"].get(fl, gid)), axis) if fl in geo["lines"] else None,
                "group_line_span": line_span(trace, t, geo["group_lines"][0], gid, axis)}

    ticks = range(A, C1 + 1)
    stat = [int(reply_at(trace, t)["observation"]["fighter_status_id"]) for t in ticks]
    return {"ticks": len(ticks), "all_airborne": all(not grounded(reply_at(trace, t)) for t in ticks),
            "floor_lines": sorted({floor_line(reply_at(trace, t)) for t in ticks}),
            "status_runs": [[s, n, clf.name(s)] for s, n in run_lengths(stat)], "position_axis": key,
            "at_A": at(A), "at_C1": at(C1), "at_L": at(L)}


def spans_of(trace: Mapping[str, Any], geo: Mapping[str, Any], B: int) -> Dict[str, Any]:
    """B - D split at the record's own events: D -> A (the exit's onset to the first airborne tick), A -> L (airborne with the floor line still
    on the group), L -> the first grounded tick after L (the flight off the group), that landing -> B (the static side)."""
    dep = geo["departure"]
    D, A, L = int(dep["D"]), int(dep["A"]), int(dep["L"])
    land = next((t for t in range(L, int(B) + 1) if grounded(reply_at(trace, t))), None)
    parts = {"onset_to_airborne": A - D, "airborne_over_group": L - A, "flight_off_group": (land - L) if land is not None else int(B) - L,
             "static_side_to_B": (int(B) - land) if land is not None else 0}
    return {"D": D, "S": int(dep["S"]), "A": A, "C1": int(dep["C1"]), "L": L, "landing": land,
            "landing_floor_line": floor_line(reply_at(trace, land)) if land is not None else None,
            "flight_floor_lines": sorted({floor_line(reply_at(trace, t)) for t in range(L, (land if land is not None else int(B)))}),
            "B": int(B), "B_minus_D": int(B) - D, "parts": parts, "parts_sum": sum(parts.values()),
            "B_minus_L": int(B) - L, "contact_ticks_C0_to_C1": int(dep["C1"]) - int(dep["C0"]) + 1}


def turning_points(y: Sequence[float]) -> List[Tuple[int, str]]:
    """(tick, 'bottom' | 'top') where the direction of motion (zero steps carry the previous direction) changes sign."""
    sgn: List[int] = [0]
    cur = 0
    for t in range(1, len(y)):
        dv = y[t] - y[t - 1]
        if dv > 0:
            cur = 1
        elif dv < 0:
            cur = -1
        sgn.append(cur)
    out = []
    for t in range(1, len(y) - 1):
        if sgn[t] != 0 and sgn[t + 1] != 0 and sgn[t] != sgn[t + 1]:
            out.append((t, "bottom" if sgn[t] < 0 else "top"))
    return out


def period_of(y: Sequence[float], tolerance: int = 1) -> Dict[str, Any]:
    """The period as the median gap between successive turning points of the same kind; refused when fewer than two of one kind exist
    or a gap differs from the median by more than `tolerance` ticks."""
    tp = turning_points(y)
    gaps = {kind: [b - a for (a, ka), (b, kb) in zip([x for x in tp if x[1] == kind], [x for x in tp if x[1] == kind][1:])] for kind in ("bottom", "top")}
    allg = gaps["bottom"] + gaps["top"]
    if not allg:
        raise ProbeError(f"the group's translation series has no two turning points of the same kind ({len(tp)} turning points): no period")
    P = int(statistics.median(allg))
    if P <= 0 or any(abs(x - P) > tolerance for x in allg):
        raise ProbeError(f"the group's motion is not periodic in the record: gaps {allg}")
    bottoms = [t for t, k in tp if k == "bottom"]
    if not bottoms:
        raise ProbeError("no bottom turning point in the record: no phase origin")
    return {"P": P, "origin": bottoms[0], "turning_points": [list(x) for x in tp], "gaps": gaps}


def direction_at(y: Sequence[float], t: int) -> int:
    """+1 / -1: the sign of the group's motion from tick t (the last nonzero step at or after t, else before)."""
    for k in range(t, len(y) - 1):
        if y[k + 1] != y[k]:
            return 1 if y[k + 1] > y[k] else -1
    for k in range(min(t, len(y) - 1), 0, -1):
        if y[k] != y[k - 1]:
            return 1 if y[k] > y[k - 1] else -1
    return 0


def phase_of(t: int, period: Mapping[str, Any]) -> int:
    return (int(t) - int(period["origin"])) % int(period["P"])


def geometry(trace: Mapping[str, Any], group: Optional[int] = None) -> Dict[str, Any]:
    """Moving groups, contact intervals (all), the chosen interval, the departure, the period and the group's state at D, from one trace.
    `group` restricts the contact intervals to one group id (the band sources use the probed clear's group)."""
    lines = line_groups(trace)
    series = group_series(trace)
    moving = moving_groups(series, lines)
    if not moving:
        raise ProbeError("no collision group with a non-static translation in the record")
    use = [gm for gm in moving if group is None or gm["group"] == int(group)]
    if not use:
        raise ProbeError(f"group {group} is static in this record")
    intervals = contact_intervals(trace, use)
    k = pick_interval(intervals)
    iv = intervals[k]
    gm = next(x for x in use if x["group"] == iv["group"])
    y = [v[gm["axis"]] for v in series[gm["group"]]]
    dep = departure_of(trace, iv)
    per = period_of(y)
    D = dep["D"]
    at = lambda t: {"tick": t, "translation": series[gm["group"]][t], "axis_value": y[t], "direction": direction_at(y, t),  # noqa: E731
                    "phase": phase_of(t, per)}
    return {"lines": lines, "moving": moving, "intervals": intervals, "chosen": k, "group": gm["group"], "group_lines": gm["lines"],
            "axis": gm["axis"], "y": y, "departure": dep, "period": per,
            "group_at": {"C0": at(dep["C0"]), "D": at(D), "A": at(dep["A"]), "C1": at(dep["C1"])}}


# -- the probed clear (zero native ticks) -------------------------------------------------------------------------------------------------------


def verification_files(lab_root: Path) -> List[Path]:
    return sorted(p for p in Path(lab_root).glob("*/run/verifications.jsonl") if p.is_file())


def verified_rows(lab_root: Path) -> List[Dict[str, Any]]:
    """Every VERIFIED clear row of the lab's verification records, with its run folder name."""
    out = []
    for p in verification_files(lab_root):
        for ln in p.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            r = json.loads(ln)
            if r.get("kind") == "clear" and r.get("verdict") == fv.VERIFIED and r.get("words_hex") and r.get("words_digest"):
                out.append(dict(r, _run=p.parent.parent.name, _file=str(p)))
    return out


def clear_key(r: Mapping[str, Any]) -> Tuple[Any, ...]:
    return (int(r["completion_input_tick"]), int(r["completion_time_passed"]), str(r["_run"]), int(r.get("n", r.get("pair", 0)) or 0))


def select_clear(rows: Sequence[Mapping[str, Any]], spec: str) -> Dict[str, Any]:
    """'best' = the fastest VERIFIED clear (completion_input_tick, then completion_time_passed); 'RUN:N:CID' = that verification row."""
    if not rows:
        raise ProbeError("no VERIFIED clear row in the lab's verification records")
    if spec == "best":
        return dict(min(rows, key=clear_key))
    try:
        run, n, cid = spec.split(":")
        hits = [r for r in rows if r["_run"] == run and int(r.get("n", -1)) == int(n) and int(r.get("cid", -1)) == int(cid)]
    except ValueError:
        raise ProbeError(f"--clear {spec!r}: expected best or RUN:N:CID")
    if len(hits) != 1:
        raise ProbeError(f"--clear {spec}: {len(hits)} VERIFIED clear rows match")
    return dict(hits[0])


def trace_paths(lab_root: Path, row: Mapping[str, Any]) -> Tuple[Path, Path]:
    """The row's two verification traces: by the verification label (clear_n<n>_c<cid>_k<k>), else the only *_r1 / *_r2 pair of the run whose
    native action digest is the row's words digest."""
    tdir = Path(lab_root) / str(row["_run"]) / "run" / "traces"
    if all(k in row for k in ("n", "cid", "k")):
        base = f"clear_n{int(row['n'])}_c{int(row['cid'])}_k{int(row['k'])}"
        p1, p2 = tdir / f"{base}_r1.json.gz", tdir / f"{base}_r2.json.gz"
        if p1.is_file() and p2.is_file():
            return p1, p2
    pairs = []
    for p1 in sorted(tdir.glob("*_r1.json.gz")):
        if read_trace(p1).get("action_digest") == row["words_digest"]:
            p2 = p1.with_name(p1.name[:-len("_r1.json.gz")] + "_r2.json.gz")
            if p2.is_file():
                pairs.append((p1, p2))
    if len(pairs) != 1:
        raise ProbeError(f"{len(pairs)} verification trace pairs carry the clear's words digest in {tdir}")
    return pairs[0]


def read_trace(p: Path) -> Dict[str, Any]:
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return json.load(f)


def load_clear(lab_root: Path, spec: str = "best", analyse: fv.Analyse = fv.real_analyse) -> Dict[str, Any]:
    """The verification row, its words and its two verified traces, checked against each other the way the lab verifies a clear: both
    traces made with the verify flags, both evaluate to the row's claim (clocks, words digest, final chain, break table), and their m8_rd
    chains agree at every tick. Any disagreement or missing field stops the probe."""
    rows = verified_rows(lab_root)
    row = select_clear(rows, spec)
    best = min(rows, key=clear_key)
    words = bytes.fromhex(row["words_hex"])
    p1, p2 = trace_paths(lab_root, row)
    tr1, tr2 = read_trace(p1), read_trace(p2)
    problems: List[str] = []
    if mcell.words_digest(words) != row["words_digest"] or len(words) != int(row["words"]):
        problems.append("the row's words do not reproduce its words digest")
    for name, tr in (("r1", tr1), ("r2", tr2)):
        missing = required_field_problems(tr)
        if missing:
            raise ProbeError(f"the {name} trace lacks fields the method needs: {missing[:8]}")
        if dict(tr.get("extra_env") or {}) != fv.FLAGS_VERIFY:
            problems.append(f"{name} was not made with the verify flags")
        ev = fv.evaluate(tr, words, analyse)
        for k in ("completion_input_tick", "completion_time_passed"):
            if ev.get(k) != row.get(k):
                problems.append(f"{name}: {k} {ev.get(k)} differs from the row's {row.get(k)}")
        if ev["outcome"] != "clear" or not ev["ticks_ok"] or not ev["action_digest_ok"] or ev["action_digest"] != row["words_digest"]:
            problems.append(f"{name}: outcome {ev['outcome']}, ticks_ok {ev['ticks_ok']}, digest ok {ev['action_digest_ok']}")
        if ev["final_chain"] != row.get(f"chain_{name}") or ev["final_chain"] != row["claim"].get("chain"):
            problems.append(f"{name}: the final chain differs from the verification row")
        if ev["breaks"] != row.get(f"breaks_{name}"):
            problems.append(f"{name}: the break table differs from the verification row")
    ch1, ch2 = chain_list(tr1), chain_list(tr2)
    first_diff = next((t for t, (a, b) in enumerate(zip(ch1, ch2)) if a != b), None)
    if len(ch1) != len(ch2) or first_diff is not None:
        problems.append(f"r1 and r2 differ per tick (first at tick {first_diff})")
    br, anomalies = native_breaks(tr1)
    if br != row.get("breaks_r1"):
        problems.append(f"the break table read from the native target records differs from the row's: {br} vs {row.get('breaks_r1')}")
    if problems:
        raise ProbeError(f"the probed clear's verified records disagree: {problems[:6]}")
    ident = {"run": row["_run"], "n": row.get("n"), "cid": row.get("cid"), "k": row.get("k"), "words": len(words), "words_digest": row["words_digest"],
             "completion_input_tick": row["completion_input_tick"], "completion_time_passed": row["completion_time_passed"],
             "final_chain": row["claim"]["chain"], "breaks": row["breaks_r1"], "verification_file": row["_file"],
             "traces": [str(p1), str(p2)], "is_best_verified": clear_key(row) == clear_key(best), "verified_rows_in_lab": len(rows)}
    return {"row": row, "ident": ident, "words": words, "r1": tr1, "r2": tr2, "chain": ch1, "breaks": br, "break_anomalies": anomalies}


# -- the window and the candidates (zero native ticks) ---------------------------------------------------------------------------------------


def baseline_of(trace: Mapping[str, Any], breaks: Sequence[Sequence[int]], D: int, clf: Any, geo: Mapping[str, Any]) -> Dict[str, Any]:
    after = [b for b in breaks if int(b[0]) > int(D)]
    if not after:
        raise ProbeError(f"the clear has no break after the departure tick {D}")
    B, target = int(after[0][0]), int(after[0][1])
    return {"B": B, "target": target, "B_minus_D": B - int(D), "mask": live_mask(reply_at(trace, B)), "mask_before": live_mask(reply_at(trace, B - 1)),
            "end_state": end_state(trace, B, geo, clf)}


def end_state(trace: Mapping[str, Any], t: int, geo: Mapping[str, Any], clf: Any) -> Dict[str, Any]:
    """The fighter's state at input tick t (an end state at a break): ground / air, status and its class (helpless or not), velocities,
    position, jumps, the floor line and whether it is on the probed group, the live mask and the group's translation."""
    r = reply_at(trace, t)
    o = r["observation"]
    cls = clf.name(o["fighter_status_id"])
    tr = group_translation(r, geo["group"])
    return {"tick": int(t), "grounded": grounded(r), "status": int(o["fighter_status_id"]), "status_class": cls, "helpless": cls == "helpless",
            "resource": mcell.resource_class(o, cls), "air_vx": round(float(o["air_velocity_x"]), 3), "air_vy": round(float(o["air_velocity_y"]), 3),
            "ground_vx": round(float(o["ground_velocity_x"]), 3), "x": round(float(o["position_x"]), 1), "y": round(float(o["position_y"]), 1),
            "jumps_used": int(o["jumps_used"]), "facing": int(o["facing_direction"]), "floor_line_id": floor_line(r),
            "on_group": floor_line(r) in set(geo["group_lines"]), "live_mask": live_mask(r), "group_translation": tr}


def flight_sign(trace: Mapping[str, Any], geo: Mapping[str, Any]) -> int:
    """The direction of the clear's next flight along the group's moving axis: the sign of the fighter's air velocity component at the
    first airborne tick of the exit (axis 0 = x, axis 1 = y)."""
    o = reply_at(trace, geo["departure"]["A"])["observation"]
    v = float(o["air_velocity_x"] if geo["axis"] == 0 else o["air_velocity_y"])
    return 1 if v > 0 else -1 if v < 0 else 0


def window_of(geo: Mapping[str, Any]) -> Dict[str, Any]:
    """Earlier d in [F, D] (F: the first grounded tick on the group; owner, 2026-11-02: the airborne contact ticks before it are excluded),
    later d in (D, D + P]. The full window only (owner, 2026-11-03: the reductions are plan text, not options)."""
    dep, P = geo["departure"], int(geo["period"]["P"])
    F, D = int(dep["F"]), int(dep["D"])
    earlier = list(range(F, D + 1))
    later = list(range(D + 1, D + P + 1))
    return {"earlier": earlier, "later": later, "rule": "full", "full": {"earlier": len(earlier), "later": len(later)}}


def bit_reverse_order(n: int) -> List[int]:
    """0 .. n-1 in van der Corput order: every prefix of the order spreads over the whole range (a capped run keeps a uniform subsample)."""
    if n <= 1:
        return list(range(n))
    bits = (n - 1).bit_length()
    return sorted(range(n), key=lambda i: (int(format(i, f"0{bits}b")[::-1], 2), i))


@dataclass
class ProbeParams:
    variants: int = 1
    seed: int = 1
    budget_factor: float = 2.0


def draw_id_of(clear: Mapping[str, Any], seed: int) -> str:
    return f"{clear['ident']['words_digest'][:16]}|{KEY_FAMILY}|s{int(seed)}"


def on_group_breaks(breaks: Sequence[Sequence[int]], dep: Mapping[str, Any]) -> List[List[int]]:
    """The clear's breaks from the interval's first grounded tick to the departure (F <= tick <= D; owner, 2026-11-03), as the native
    records report them."""
    return [[int(t), int(i)] for t, i in breaks if int(dep["F"]) <= int(t) <= int(dep["D"])]


def pending_of(d: int, onb: Sequence[Sequence[int]]) -> List[List[int]]:
    """The on-group breaks the clear takes after d: a departure at d leaves before them (a pre-break departure when not empty)."""
    return [list(b) for b in onb if int(b[0]) > int(d)]


def build_plan(clear: Mapping[str, Any], params: ProbeParams, clf: Any) -> Dict[str, Any]:
    """The probe's derivation and its ordered candidate list (the first is the control: d = D with the clear's own exit)."""
    tr, words = clear["r1"], clear["words"]
    geo = geometry(tr)
    dep, per = geo["departure"], geo["period"]
    D, P = int(dep["D"]), int(per["P"])
    base = baseline_of(tr, clear["breaks"], D, clf, geo)
    B = base["B"]
    E = int(math.ceil(params.budget_factor * (B - D)))
    if E < B - D:
        raise ProbeError(f"the budget {E} is shorter than the clear's own exit {B - D}")
    win = window_of(geo)
    onb = on_group_breaks(clear["breaks"], dep)
    draw_id = draw_id_of(clear, params.seed)
    exits: Dict[str, bytes] = {VARIANT_CLEAR: bytes(words[D:B]) + bytes([NEUTRAL_WORD]) * (E - (B - D))}
    for k in range(1, params.variants + 1):
        exits[f"g{k}"] = fa.stream_words(draw_id, k, E)
    order_d = [D] + [x for x in (win["earlier"] + win["later"]) if x != D]
    rest = order_d[1:]
    ordered = [D] + [rest[i] for i in bit_reverse_order(len(rest))]
    cands: List[Dict[str, Any]] = []
    for d in ordered:
        prefix = bytes(words[:d]) if d <= D else bytes(words[:D]) + bytes([NEUTRAL_WORD]) * (d - D)
        pend = pending_of(d, onb)
        for v, ex in exits.items():
            w = (prefix + ex)[:mcell.HORIZON]
            cands.append({"idx": len(cands), "label": f"d{d:05d}_{v}", "d": d, "side": "control" if (d == D and v == VARIANT_CLEAR) else
                          ("earlier" if d <= D else "later"), "variant": v, "prefix_ref": "clear" if d <= D else "filler", "pre_break": bool(pend),
                          "pending_on_group": pend, "words": w, "words_digest": mcell.words_digest(w), "ticks": len(w)})
    y = geo["y"]
    def d_info(d: int) -> Dict[str, Any]:
        return {"phase": phase_of(d, per), "axis_value": y[d] if d < len(y) else None, "direction": direction_at(y, d) if d < len(y) else None}
    pre = sorted({c["d"] for c in cands if c["pre_break"]})
    digest = hashlib.sha256(json.dumps({"contract": PROBE_CONTRACT, "clear": clear["ident"]["words_digest"], "D": D, "B": B, "E": E, "P": P,
                                        "F": int(dep["F"]), "on_group_breaks": onb,
                                        "cands": [[c["d"], c["variant"], c["words_digest"], int(c["pre_break"])] for c in cands]},
                                       separators=(",", ":")).encode("utf-8")).hexdigest()
    plan = {"mode": "lab", "contract": PROBE_CONTRACT, "utc": g.utc(), "clear": clear["ident"],
            "break_anomalies": clear["break_anomalies"],
            "groups": geo["moving"], "contact_intervals": geo["intervals"], "chosen_interval": geo["chosen"],
            "choice_rule": "the contact interval with the largest ride-or-still count (riding = grounded on the group; still = position unchanged)",
            "group": geo["group"], "group_lines": geo["group_lines"], "axis": geo["axis"], "departure": dep,
            "period": {k: per[k] for k in ("P", "origin", "gaps")}, "turning_points": per["turning_points"], "group_at": geo["group_at"],
            "baseline": base, "budget": {"factor": params.budget_factor, "E": E, "margin": E - (B - D), "rule": "E = ceil(factor * (B - D)) exit words after d"},
            "window": {"rule": win["rule"], "full": win["full"], "earlier": [min(win["earlier"]), max(win["earlier"]), len(win["earlier"])],
                       "later": [min(win["later"]), max(win["later"]), len(win["later"])] if win["later"] else None,
                       "d_count": len(ordered), "start_rule": "the first grounded tick on the group (owner, 2026-11-02)",
                       "excluded_airborne_contact": [int(dep["C0"]), int(dep["F"]) - 1, int(dep["F"]) - int(dep["C0"])]},
            "on_group_breaks": onb,
            "pre_break": {"rule": "a departure before one of the clear's on-group breaks (F <= break tick <= D, break tick > d): labelled pre-break, "
                                  "its own part of the curve and of every table with its own counts; counted like any departure (it beats B "
                                  "only when its progress tick is before B, so it must also break the on-group targets) and on the band's "
                                  "earlier side when outside the band (owner, 2026-11-03)",
                          "d": [pre[0], pre[-1], len(pre)] if pre else None},
            "progress_rule": {"rule": "progress tick = the first tick after d whose live-target mask is a subset of the baseline's at B (every "
                                      "target the baseline had broken by B, in any order); a candidate beats B when its progress tick is before "
                                      "B (owner, 2026-11-03)", "baseline_mask": base["mask"],
                              "baseline_live_targets": [i for i in range(int(base["mask"]).bit_length()) if int(base["mask"]) >> i & 1]},
            "exit_run": exit_run_of(tr, geo, clf), "spans": spans_of(tr, geo, B),
            "flight_sign": flight_sign(tr, geo), "neutral_word": NEUTRAL_WORD, "neutral_triple": list(mcell.TRIPLES[NEUTRAL_WORD]),
            "variants": {"clear_exit": VARIANT_CLEAR, "generic": [f"g{k}" for k in range(1, params.variants + 1)], "K": params.variants,
                         "seed": params.seed, "draw_id": draw_id, "generator": "rl/frs_archive.stream_words (m8_rd_explore_v1 keyed stream), iteration k"},
            "candidates": len(cands), "ticks_planned": sum(c["ticks"] for c in cands), "candidate_set_digest": digest,
            "flags_verify": fv.FLAGS_VERIFY}
    return {"plan": plan, "candidates": cands, "geo": geo, "baseline": base, "d_info": d_info, "window": win, "E": E}


def candidate_row(c: Mapping[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in c.items() if k != "words"}


# -- the band of the verified clears (zero native ticks) ---------------------------------------------------------------------------------------


def band_sources(lab_root: Path) -> List[Tuple[str, Path, Optional[Dict[str, Dict[str, Any]]]]]:
    """(label, trace path, {words digest: the VERIFIED row's clocks}) of every stored replay trace that can belong to a VERIFIED clear:
    each run's *_r1 traces against that run's VERIFIED rows, and the lab import's reference clear (the registered verified clear the lab
    imported; None: checked by rl/frs_verify.load_reference instead)."""
    want: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for r in verified_rows(lab_root):
        want.setdefault(r["_run"], {})[r["words_digest"]] = {k: r[k] for k in ("completion_input_tick", "completion_time_passed")}
    out: List[Tuple[str, Path, Optional[Dict[str, Dict[str, Any]]]]] = []
    for run, digests in sorted(want.items()):
        for p in sorted((Path(lab_root) / run / "run" / "traces").glob("*_r1.json.gz")):
            out.append((f"{run}:{p.name}", p, digests))
    ref = Path(lab_root) / "import" / "reference" / "trace.json.gz"
    if ref.is_file():
        out.append(("import:reference", ref, None))
    return out


def verified_clear_problems(tr: Mapping[str, Any], clocks: Optional[Mapping[str, Any]]) -> List[str]:
    """Why a band source is not a verified clear's trace: not made with the verify flags, a tick-contract break, the native target records
    disagreeing with the live mask, not the four clear facts (ten breaks from the native target records), or clocks other than the
    VERIFIED row's (when given)."""
    out: List[str] = []
    if dict(tr.get("extra_env") or {}) != fv.FLAGS_VERIFY:
        out.append("not made with the verify flags")
    br = tick_contract_break(tr)
    if br is not None:
        out.append(f"tick contract: {br}")
    breaks, anomalies = native_breaks(tr)
    if anomalies:
        out.append(f"the native target records disagree with the live mask: {anomalies[:2]}")
    facts = mclaims.clear_facts(tr, len(breaks))
    if not facts["all"]:
        out.append(f"not a clear: {({k: v for k, v in facts.items() if v is False})}")
    for k, v in dict(clocks or {}).items():
        if facts.get(k) != v:
            out.append(f"{k} {facts.get(k)} differs from the VERIFIED row's {v}")
    return out


def arc_of(phases: Sequence[int], P: int) -> Dict[str, Any]:
    """The shortest circular arc [start, start + length] (mod P) that contains every phase."""
    ps = sorted({int(p) % P for p in phases})
    if not ps:
        raise ProbeError("no phase for the band")
    if len(ps) == 1:
        return {"start": ps[0], "length": 0, "end": ps[0], "phases": ps}
    gaps = [((ps[(i + 1) % len(ps)] - ps[i]) % P, i) for i in range(len(ps))]
    big, i = max(gaps)
    start = ps[(i + 1) % len(ps)]
    length = (P - big) % P
    return {"start": start, "length": length, "end": (start + length) % P, "phases": ps}


def in_arc(phase: int, arc: Mapping[str, Any], P: int) -> bool:
    return (int(phase) - int(arc["start"])) % P <= int(arc["length"])


def band_row(label: str, digest: str, gg: Mapping[str, Any]) -> Dict[str, Any]:
    dep = gg["departure"]
    return {"source": label, "digest": str(digest)[:16], "D": dep["D"], "phase": phase_of(dep["D"], gg["period"]), "P": gg["period"]["P"],
            "G": dep["G"], "S": dep["S"], "status_G": dep["status_G"], "G_minus_D": int(dep["G"]) - int(dep["D"]),
            "axis_value": gg["group_at"]["D"]["axis_value"], "direction": gg["group_at"]["D"]["direction"]}


def band_digest(band: Mapping[str, Any]) -> str:
    """sha256 over what the band is computed from: the probed clear's own row, every source row, every skipped source, the period and the
    arc (the run refuses a band that differs from --expect-band)."""
    body = {"contract": PROBE_CONTRACT, "P": band["P"], "own": band["own"], "rows": band["rows"], "skipped": band["skipped"], "arc": band["arc"]}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def band_of(lab_root: Path, plan: Mapping[str, Any], geo: Mapping[str, Any], analyse: fv.Analyse = fv.real_analyse) -> Dict[str, Any]:
    """The departure phase (same rules, same group id, each clear's own period measurement) of every verified clear with a trace; the band
    is the shortest arc of the cycle containing all of them, the probed clear's own departure included. Every source must be a verified
    clear's trace (verified_clear_problems; the import reference by rl/frs_verify.load_reference): any other is refused (ProbeError)."""
    P = int(geo["period"]["P"])
    own = band_row("probed clear", plan["clear"]["words_digest"], geo)
    rows: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    phases = [own["phase"]]
    seen = {plan["clear"]["words_digest"]}
    for label, p, digests in band_sources(lab_root):
        tr = read_trace(p)
        dg = tr.get("action_digest")
        if (digests is not None and dg not in digests) or dg in seen:
            continue                                       # not a VERIFIED clear's trace, or a trajectory already counted
        if digests is None:
            ref = fv.load_reference(p.parent, analyse)
            bad = list(ref["problems"]) + ([] if dg == ref["meta"].get("native_action_digest") else ["its digest is not the reference's"])
            bad += verified_clear_problems(tr, None)
        else:
            bad = verified_clear_problems(tr, digests[dg])
        if bad:
            raise ProbeError(f"band source {label} is not a verified clear's trace: {bad[:4]}")
        seen.add(dg)
        try:
            gg = geometry(tr, group=geo["group"])
        except ProbeError as exc:
            skipped.append({"source": label, "why": str(exc)[:200]})
            continue
        if int(gg["period"]["P"]) != P:
            skipped.append({"source": label, "why": f"period {gg['period']['P']} differs from the probed clear's {P}"})
            continue
        r = band_row(label, dg, gg)
        phases.append(r["phase"])
        rows.append(r)
    arc = arc_of(phases, P)
    vals = [r["axis_value"] for r in rows]
    onset = sorted({(r["status_G"], r["G_minus_D"]) for r in [own] + rows})
    band = {"rule": "shortest arc of phase (mod the measured period) containing the departure phase of every verified clear with a trace",
            "sources": len(rows), "skipped": skipped, "arc": arc, "P": P, "axis_value_range": [min(vals), max(vals)] if vals else None,
            "directions": sorted({r["direction"] for r in rows}), "own": own, "rows": rows,
            "onsets": [{"status_G": s, "G_minus_D": k, "rows": sum(1 for r in [own] + rows if (r["status_G"], r["G_minus_D"]) == (s, k))} for s, k in onset]}
    band["digest"] = band_digest(band)
    return band


def band_counts(cands: Sequence[Mapping[str, Any]], d_info: Callable[[int], Mapping[str, Any]], band: Mapping[str, Any], D: int) -> Dict[str, int]:
    """The planned departure ticks inside and outside the band, by side (earlier: d < D, later: d > D) and pre-break, as if every candidate
    departed at its d (the run decides on each candidate's measured departure)."""
    pre = {int(c["d"]): bool(c["pre_break"]) for c in cands}
    out = {"in_band": 0, "in_band_pre_break": 0, "outside_earlier": 0, "outside_earlier_pre_break": 0, "outside_later": 0}
    for d, pb in sorted(pre.items()):
        if in_arc(d_info(d)["phase"], band["arc"], band["P"]):
            out["in_band"] += 1
            out["in_band_pre_break"] += int(pb)
        elif d < int(D):
            out["outside_earlier"] += 1
            out["outside_earlier_pre_break"] += int(pb)
        else:
            out["outside_later"] += 1
    return out


# -- cost (zero native ticks: the lab's own replay-timing records) ------------------------------------------------------------------------------


def measured_cost(lab_root: Path) -> Dict[str, Any]:
    """Per-candidate cost of a fresh-process verify-flag replay with its trace saved, from the lab's records: the splice probe (several
    such replays at once, nothing else running) gives slot seconds = fixed + per_tick * ticks; crossing run 2's check replays (two at once
    beside the search workers) are a cross-check. Nothing here is assumed: a missing record leaves the estimate unavailable."""
    out: Dict[str, Any] = {"available": False}
    for run in sorted(Path(lab_root).glob("splice_probe_*/run")):
        s, rp, pre = run / "summary.json", run / "results.jsonl", run / "preflight.json"
        if not (s.is_file() and rp.is_file() and pre.is_file()):
            continue
        summ = json.loads(s.read_text(encoding="utf-8"))
        slots = int(json.loads(pre.read_text(encoding="utf-8"))["workers"])
        rows = [json.loads(ln) for ln in rp.read_text(encoding="utf-8").splitlines() if ln.strip()]
        ctl = [r for r in rows if r.get("kind") == "control"]
        cand = [r for r in rows if r.get("kind") != "control" and r.get("startup_s") is not None and r.get("stepping_s") is not None]
        if not cand or len(ctl) != 1:
            continue
        su, sp, tk = (sum(float(r[k]) for r in cand) for k in ("startup_s", "stepping_s", "ticks"))
        ctl_s = float(ctl[0]["startup_s"]) + float(ctl[0]["stepping_s"])
        wall = float(summ["wall_s"]) - ctl_s                    # the control ran alone first; its runtime set-up is inside the overhead
        overhead = (slots * wall - su - sp) / len(cand)
        out = {"available": True, "source": str(run), "slots": slots, "replays": len(cand), "wall_s": float(summ["wall_s"]), "mean_ticks": round(tk / len(cand)),
               "startup_s": round(su / len(cand), 3), "per_tick_s": round(sp / tk, 7), "overhead_s": round(overhead, 3),
               "fixed_s": round(su / len(cand) + overhead, 3), "aggregate_s_per_replay": round(wall / len(cand), 3)}
        break
    pts: List[Tuple[float, float]] = []
    files = sorted(Path(lab_root).glob("*/run/checks.jsonl"))
    for p in files:
        for ln in p.read_text(encoding="utf-8").splitlines():
            r = json.loads(ln) if ln.strip() else {}
            if r.get("ok") and r.get("ticks") and r.get("wall_s"):
                pts.append((float(r["ticks"]), float(r["wall_s"])))
    f = fm.fit([x for x, _ in pts], [y for _, y in pts]) if len(pts) >= 3 else None
    if f:
        out["cross_check"] = {"source": ", ".join(str(p) for p in files), "replays": len(pts), "wall_s_fixed": round(f[0], 3),
                              "wall_s_per_tick": round(f[1], 7), "note": "single-replay wall (no trace save), during a search run"}
    return out


def expected_wall(cands: Sequence[Mapping[str, Any]], cost: Mapping[str, Any], slots: int, controls_ticks: Sequence[int]) -> Optional[Dict[str, Any]]:
    if not cost.get("available"):
        return None
    c = lambda n: float(cost["fixed_s"]) + float(cost["per_tick_s"]) * n  # noqa: E731
    open_s = max(c(n) for n in controls_ticks)                # the three control replays run at once
    cand_s = sum(c(int(x["ticks"])) for x in cands) / max(1, slots)
    return {"open_s": round(open_s, 1), "candidates_s": round(cand_s, 1), "native_s": round(open_s + cand_s, 1),
            "native_min": round((open_s + cand_s) / 60.0, 1), "per_candidate_slot_s": round(cand_s * slots / max(1, len(cands)), 2)}


# -- per-candidate reading ------------------------------------------------------------------------------------------------------------------


def tick_contract_break(trace: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """The first break of the tick contract (consumed_tick = T, input_tick = T + 1, step_count = T + 1 on every step, and no recorded
    consumed-tick mismatch), or None."""
    if trace.get("consumed_tick_mismatch") is not None:
        return {"consumed_tick_mismatch": trace["consumed_tick_mismatch"]}
    for i, s in enumerate(trace.get("steps") or []):
        got = {"consumed_tick": s.get("consumed_tick"), "input_tick": (s.get("observation") or {}).get("input_tick"), "step_count": s.get("step_count")}
        if got != {"consumed_tick": i, "input_tick": i + 1, "step_count": i + 1}:
            return {"step": i, **got}
    return None


def ticks_ok_of(trace: Mapping[str, Any]) -> bool:
    return tick_contract_break(trace) is None


def pin_watch(replay: fv.ReplayFn, seen: List[Dict[str, Any]]) -> fv.ReplayFn:
    """`replay` with each pin drift noted in `seen` (label, detail) before it propagates: rl/frs_verify re-hashes the pinned game files beside
    the executable before every replay and raises MismatchError 'pin_drift', which fv.replay_with_retry turns into an error string."""
    def watched(words: bytes, label: str, slot: int) -> Optional[Dict[str, Any]]:
        try:
            return replay(words, label, slot)
        except mw.MismatchError as exc:
            if exc.kind == "pin_drift":
                seen.append({"label": label, "detail": exc.detail})
            raise

    return watched


def outcome_of(trace: Mapping[str, Any], n_words: int) -> str:
    steps = trace["steps"]
    if (trace.get("result") or {}).get("outcome") == "clear":
        return "clear_not_claimed"
    if steps and mcell.is_native_failure(steps[-1]["observation"], steps[-1]["state"]):
        return "fall"
    return "budget_end" if len(steps) == n_words else "ended_other"


def read_candidate(trace: Optional[Mapping[str, Any]], c: Mapping[str, Any], ctx: Mapping[str, Any], errors: Sequence[str] = ()) -> Dict[str, Any]:
    """One results.jsonl row. ctx: geo, baseline, ref_chain {'clear': [...], 'filler': [...]}, clf, d_info, band (optional).
    The tick contract and the action digest come first (outcome 'contract': the run is PROBE_INVALID), then the prefix digest. A valid row
    carries its measured departure (departed_at_d: departure_tick == d; only those rows count, and in_band is read on departure_phase),
    its first break after d, and its progress tick (beats_B: progress_tick < B)."""
    d, B = int(c["d"]), int(ctx["baseline"]["B"])
    row: Dict[str, Any] = {"idx": c["idx"], "label": c["label"], "d": d, "side": c["side"], "variant": c["variant"], "ticks_planned": c["ticks"],
                           "pre_break": bool(c.get("pre_break")), "pending_on_group": list(c.get("pending_on_group") or []),
                           **{f"d_{k}": v for k, v in ctx["d_info"](d).items()}, "errors": list(errors)[:3]}
    if trace is None:
        row.update(outcome="error", valid=False, failed=True)
        return row
    steps = trace["steps"]
    n = len(steps)
    words = c["words"]
    contract = tick_contract_break(trace)
    digest_ok = trace.get("action_digest") == mcell.words_digest(bytes(words[:n]))
    row.update({"ticks": n, "ticks_ok": contract is None, "digest_ok": digest_ok, "prefix_ref": c["prefix_ref"], "startup_s": trace.get("startup_s"),
                "stepping_s": trace.get("stepping_s")})
    if contract is not None or not digest_ok:
        row.update(outcome="contract", valid=False, failed=True, contract={"tick": contract, "action_digest_ok": digest_ok})
        return row
    ch = chain_list(trace)
    ref = ctx["ref_chain"].get(c["prefix_ref"])
    prefix_equal = ref is not None and n >= d and len(ref) > d and ch[d] == ref[d]
    row.update({"prefix_equal": prefix_equal, "final_chain": ch[-1].hex(), "outcome": outcome_of(trace, len(words))})
    if not prefix_equal:
        diff = None
        if ref is not None:
            diff = next((t for t in range(0, min(d, len(ref) - 1, n) + 1) if ch[t] != ref[t]), None)
        row.update(outcome="mismatch", valid=False, failed=True, mismatch_first_tick=diff)
        return row
    if c["side"] == "control":
        row["chain_at_B_equal"] = n >= B and len(ref) > B and ch[B] == ref[B]
    geo = ctx["geo"]
    dep = measured_departure(trace, d, set(geo["group_lines"]))
    dt_, fl = dep["departure_tick"], dep["floor_line_leave_tick"]
    row.update({"valid": True, "failed": False, "departure_tick": dt_, "departure_phase": phase_of(dt_, geo["period"]) if dt_ is not None else None,
                "departure_reason": dep["reason"], "departed_at_d": dep["reason"] == "at_d", "departure": dep["detail"],
                "floor_line_leave_tick": fl, "floor_line_leave_phase": phase_of(fl - 1, geo["period"]) if fl is not None else None})
    if ctx.get("band") is not None:
        row["in_band"] = in_arc(row["departure_phase"], ctx["band"]["arc"], ctx["band"]["P"]) if dt_ is not None else None
    br, anomalies = native_breaks(trace)
    after = [b for b in br if int(b[0]) > d]
    base_mask = int(ctx["baseline"]["mask"])
    prog = next((t for t in range(d + 1, n + 1) if live_mask(reply_at(trace, t)) & ~base_mask == 0), None)
    beats = prog is not None and prog < B
    row.update({"break_anomalies": anomalies[:3], "breaks_after": after[:4], "progress_tick": prog,
                "progress_targets": sorted(int(i) for t, i in after if int(t) == prog) if prog is not None else None,
                "progress_exit_ticks": prog - d if prog is not None else None, "beats_B": beats, "gain": B - prog if beats else None,
                "progress_end_state": end_state(trace, prog, geo, ctx["clf"]) if prog is not None else None})
    if not after:
        row.update(first_break=None, earlier_than_B=False, comparable=None)
        return row
    t, target = int(after[0][0]), int(after[0][1])
    at_t = sorted(int(i) for tt, i in after if int(tt) == t)
    pend = {int(i) for _t, i in row["pending_on_group"]}
    m = live_mask(reply_at(trace, t))
    row.update({"first_break": {"tick": t, "target": target, "targets_at_tick": at_t, "same_as_baseline_next": target == int(ctx["baseline"]["target"]),
                                "on_group_target": bool(pend & set(at_t)), "mask": m, "exit_ticks": t - d},
                "comparable": (m & ~base_mask) == 0, "earlier_than_B": t < B, "end_state": end_state(trace, t, geo, ctx["clf"])})
    return row


# -- verdict ---------------------------------------------------------------------------------------------------------------------------------


def sides_of(outside: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """S1 (owner, 2026-11-03): which sides of the band were testable, from the valid, counted (departed at d) outside-band rows. A row's
    side is its candidate's: 'earlier' (d <= D, pre-break departures included) or 'later' (d > D); the control (d = D) is in the band by
    construction."""
    e = [r for r in outside if r.get("side") == "earlier"]
    later = [r for r in outside if r.get("side") == "later"]
    ep = sum(1 for r in e if r.get("pre_break"))
    if e and later:
        which = "both sides"
    elif later:
        which = "later side only"
    elif e:
        which = "earlier side only"
    else:
        which = "neither side"
    text = (f"{which} of the band tested (valid outside-band rows that departed at d: earlier side {len(e)}, of them pre-break {ep}; "
            f"later side {len(later)})")
    return {"earlier": len(e), "earlier_pre_break": ep, "later": len(later), "which": which, "statement": text}


def verdict_of(rows: Sequence[Mapping[str, Any]], planned: int, status: str, B: int, band_ok: bool) -> Dict[str, Any]:
    """NOT_FORCED / FORCED_IN_PROBE / INCONCLUSIVE, plus IN_BAND_GAIN (the case the three rules leave open: a departure beats B, but only
    inside the band). A row counts only when it is valid and departed at d (its measured departure, by the D rule, is d); its band side is
    read on that departure. Rows that did not depart at d are reported apart and never counted. A candidate beats B when its progress tick
    (its live mask a subset of the baseline's at B) is before B; earlier first breaks without that progress are reported, never counted as
    faster. Pre-break departures count like any other (owner, 2026-11-03) and are reported with their own counts."""
    failed = [r for r in rows if r.get("failed")]
    valid = [r for r in rows if r.get("valid")]
    counted = [r for r in valid if r.get("departed_at_d")]
    nd = [r for r in valid if not r.get("departed_at_d")]
    pre = [r for r in valid if r.get("pre_break")]
    reasons_nd: Dict[str, int] = {}
    for r in nd:
        reasons_nd[str(r.get("departure_reason"))] = reasons_nd.get(str(r.get("departure_reason")), 0) + 1
    out: Dict[str, Any] = {"planned": planned, "ran": len(rows), "valid": len(valid), "failed": len(failed),
                           "failed_share": round(len(failed) / planned, 4) if planned else None, "B": B,
                           "counted": len(counted), "counted_pre_break": sum(1 for r in counted if r.get("pre_break")),
                           "did_not_depart_at_d": {"rows": len(nd), "pre_break": sum(1 for r in nd if r.get("pre_break")),
                                                   "by_reason": dict(sorted(reasons_nd.items())), "counted": 0},
                           "pre_break": pre_break_summary(pre, B)}
    reasons = []
    if status not in ("COMPLETED",):
        reasons.append(f"the run did not complete its planned window (status {status})")
    if len(rows) < planned:
        reasons.append(f"{planned - len(rows)} planned candidates did not run")
    if planned and len(failed) > FAILED_SHARE_MAX * planned:
        reasons.append(f"{len(failed)} of {planned} candidates failed to run (> {FAILED_SHARE_MAX:.0%})")
    if not band_ok:
        reasons.append("the band of the verified clears is not available")
    outside = [r for r in counted if r.get("in_band") is False]
    sides = sides_of(outside)
    if band_ok and not outside:
        reasons.append("no valid departure at d outside the band (rows that did not depart at d are never counted)")
    beats = [r for r in counted if r.get("beats_B")]
    beats_out = [r for r in beats if r.get("in_band") is False]
    earlier_less = [r for r in counted if r.get("earlier_than_B") and not r.get("beats_B")]
    later = [r for r in outside if r.get("first_break") and not r.get("earlier_than_B")]
    none = [r for r in outside if not r.get("first_break")]
    pb = lambda xs: sum(1 for r in xs if r.get("pre_break"))  # noqa: E731
    out.update({"beats_B": len(beats), "beats_B_pre_break": pb(beats), "beats_B_outside_band": len(beats_out),
                "beats_B_outside_band_pre_break": pb(beats_out), "d_beating_B": len({r["d"] for r in beats}),
                "d_beating_B_outside_band": len({r["d"] for r in beats_out}), "earlier_with_less_progress": len(earlier_less),
                "outside_band_valid": len(outside), "outside_band_pre_break": pb(outside), "outside_band_later_break": len(later),
                "outside_band_no_break": len(none),
                "outside_band_earlier_less_progress": sum(1 for r in earlier_less if r.get("in_band") is False), "sides": sides})
    best = min(beats_out or beats, key=lambda r: (r["progress_tick"], r["d"], r["variant"]), default=None)
    if best is not None:
        out["best"] = {k: best.get(k) for k in ("label", "d", "variant", "side", "pre_break", "departure_tick", "departure_phase", "in_band", "gain",
                                                "progress_tick", "progress_targets", "first_break", "progress_end_state")}
    if reasons:
        out.update(verdict=INCONCLUSIVE, reasons=reasons)
    elif beats_out:
        out.update(verdict=NOT_FORCED, reasons=[f"{len({r['d'] for r in beats_out})} departures outside the band beat B "
                                                f"({pb(beats_out)} of the {len(beats_out)} candidates pre-break); best gain {best['gain']} ticks "
                                                f"at d {best['d']}{' (pre-break)' if best.get('pre_break') else ''}"])
    elif beats:
        out.update(verdict=IN_BAND_GAIN, reasons=["no departure outside the band beats B, but a departure inside it does"])
    else:
        out.update(verdict=FORCED_IN_PROBE, reasons=["no departure beats B; outside the band every counted candidate does not break within the "
                                                     "budget, first breaks at or after B, or breaks earlier without the baseline's progress before B"])
    out["reasons"] = out["reasons"] + [sides["statement"]]
    return out


def verdict_line(v: Mapping[str, Any]) -> str:
    """The verdict with its reasons, the sides of the band that were tested (S1) and the pre-break counts next to it."""
    pbs, nd = v["pre_break"], v["did_not_depart_at_d"]
    return (f"Verdict {v['verdict']}: {'; '.join(v.get('reasons') or [])}. Pre-break departures: valid {pbs['valid']}, departed at d "
            f"{pbs['departed_at_d']}, outside the band {pbs['outside_band']}, beat B {pbs['beats_B']} (counted, labelled pre-break). "
            f"Did not depart at d: {nd['rows']} (pre-break {nd['pre_break']}; {nd['by_reason']}), never counted.")


def pre_break_summary(pre: Sequence[Mapping[str, Any]], B: int) -> Dict[str, Any]:
    """The pre-break departures' own part of the curve and their own counts: which break each reaches first (as reported), how many departed
    at d, are outside the band and beat B (counted like any departure, labelled pre-break; owner, 2026-11-03)."""
    by_target: Dict[str, Dict[str, Any]] = {}
    for r in pre:
        fb = r.get("first_break")
        key = "none" if not fb else str(fb["target"])
        e = by_target.setdefault(key, {"candidates": 0, "on_group_target": 0, "same_as_baseline_next": 0, "earliest_tick": None, "earliest_d": None})
        e["candidates"] += 1
        if fb:
            e["on_group_target"] += int(bool(fb.get("on_group_target")))
            e["same_as_baseline_next"] += int(bool(fb.get("same_as_baseline_next")))
            if e["earliest_tick"] is None or fb["tick"] < e["earliest_tick"]:
                e["earliest_tick"], e["earliest_d"] = fb["tick"], r["d"]
    ds = sorted({r["d"] for r in pre})
    dep = [r for r in pre if r.get("departed_at_d")]
    beats = [r for r in dep if r.get("beats_B")]
    return {"valid": len(pre), "d": [ds[0], ds[-1], len(ds)] if ds else None, "first_break_by_target": by_target,
            "departed_at_d": len(dep), "did_not_depart_at_d": len(pre) - len(dep), "outside_band": sum(1 for r in dep if r.get("in_band") is False),
            "earlier_than_B": sum(1 for r in dep if r.get("earlier_than_B")), "beats_B": len(beats),
            "beats_B_outside_band": sum(1 for r in beats if r.get("in_band") is False), "counted_as_gain": len(beats)}


def part_of(r: Mapping[str, Any]) -> str:
    return "pre_break" if r.get("pre_break") else str(r.get("side"))


def curve_rows(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """The curve: per d and variant, the measured departure, the first-break and progress ticks (or the reason there are none), sorted by d;
    `part` labels the pre-break departures and `departed_at_d` the rows that count."""
    out = []
    for r in sorted(rows, key=lambda x: (x["d"], x["variant"])):
        fb = r.get("first_break") or {}
        es = r.get("end_state") or {}                      # at the first break; results.jsonl also has the end state at the progress tick
        out.append({"d": r["d"], "variant": r["variant"], "type": "clear_exit" if r["variant"] == VARIANT_CLEAR else "generic", "part": part_of(r),
                    "side": r["side"], "phase": r.get("d_phase"), "axis_value": r.get("d_axis_value"), "direction": r.get("d_direction"),
                    "outcome": r.get("outcome"), "departure_tick": r.get("departure_tick"), "departure_phase": r.get("departure_phase"),
                    "departed_at_d": r.get("departed_at_d"), "departure_reason": r.get("departure_reason"), "in_band": r.get("in_band"),
                    "first_break_tick": fb.get("tick"), "target": fb.get("target"), "on_group_target": fb.get("on_group_target"),
                    "same_as_baseline_next": fb.get("same_as_baseline_next"), "comparable": r.get("comparable"),
                    "progress_tick": r.get("progress_tick"), "beats_B": r.get("beats_B"), "gain": r.get("gain"), "grounded": es.get("grounded"),
                    "helpless": es.get("helpless"), "status": es.get("status"), "air_vx": es.get("air_vx"), "air_vy": es.get("air_vy"),
                    "floor_line_leave_tick": r.get("floor_line_leave_tick"), "floor_line_leave_phase": r.get("floor_line_leave_phase")})
    return out


def curve_csv(rows: Sequence[Mapping[str, Any]]) -> str:
    cr = curve_rows(rows)
    if not cr:
        return ""
    keys = list(cr[0].keys())
    lines = [",".join(keys)]
    for r in cr:
        lines.append(",".join("" if r[k] is None else str(r[k]) for k in keys))
    return "\n".join(lines) + "\n"


def curve_by_type(rows: Sequence[Mapping[str, Any]], key: str = "first_break") -> Dict[str, Dict[str, Any]]:
    """Per variant type, per d: the earliest first-break tick (key 'first_break') or progress tick (key 'progress') among that type's
    counted candidates (valid, departed at d; None = none within the budget); the pre-break departures form their own part
    (`pre_break_clear_exit`, `pre_break_generic`)."""
    out: Dict[str, Dict[str, Any]] = {"clear_exit": {}, "generic": {}, "pre_break_clear_exit": {}, "pre_break_generic": {}}
    for r in rows:
        if not (r.get("valid") and r.get("departed_at_d")):
            continue
        typ = ("pre_break_" if r.get("pre_break") else "") + ("clear_exit" if r["variant"] == VARIANT_CLEAR else "generic")
        t = (r.get("first_break") or {}).get("tick") if key == "first_break" else r.get("progress_tick")
        cur = out[typ].get(str(r["d"]))
        out[typ][str(r["d"])] = t if cur is None else (min(cur, t) if t is not None else cur)
    return out


# -- the engine (native; Phase 2 only, with the owner's go) ---------------------------------------------------------------------------------------


@dataclass
class ProbeConfig:
    lab_root: Path
    out: Path
    run_dir: Path
    slots: int = 5
    max_wall_s: float = MAX_WALL_MIN * 60.0
    stop_reserve_s: float = 60.0
    progress_every_s: float = 60.0
    save_traces: bool = True
    head: Optional[str] = None                 # the HEAD checked at run start (git_facts; --expect-head)


class Probe:
    def __init__(self, cfg: ProbeConfig, env: Any, clear: Mapping[str, Any], P: Mapping[str, Any], band: Optional[Mapping[str, Any]], clf: Any,
                 cost: Optional[Mapping[str, Any]] = None):
        self.cfg, self.env, self.clear, self.P, self.band, self.clf = cfg, env, clear, P, band, clf
        self.plan, self.cands = P["plan"], P["candidates"]
        self.cost = cost or {}
        self.fs = g.LabFS(cfg.lab_root)
        self.dir = Path(cfg.run_dir)
        self.t0 = env.now()
        self.t_native: Optional[float] = None
        self.t_native_end: Optional[float] = None
        self.utc_start = g.utc()
        self.phase = "open"
        self.status = "COMPLETED"
        self.stop_reason: Optional[str] = None
        self.stopping = False
        self.notes: List[str] = []
        self.sampler: Optional[fm.Sampler] = None
        self.rows: List[Dict[str, Any]] = []
        self.controls: Dict[str, Any] = {}
        self.queue: Deque[Dict[str, Any]] = deque()
        self.not_dispatched: List[Dict[str, Any]] = []
        self.c = {"dispatched": 0, "returned": 0, "valid": 0, "failed": 0, "mismatches": 0, "contract": 0, "pin_drift": 0, "ticks": 0,
                  "control_ticks": 0}
        self.pin_drift: List[Dict[str, Any]] = []
        self.ref_chain: Dict[str, List[bytes]] = {"clear": list(clear["chain"])}
        self.later_max: Optional[int] = None
        self.code: Dict[str, str] = {}
        self.integrity: Dict[str, Any] = {}
        self._last_progress = self.t0
        self._lock = threading.Lock()
        geo, base = P["geo"], P["baseline"]
        self.ctx = {"geo": geo, "baseline": base, "ref_chain": self.ref_chain, "clf": clf, "d_info": P["d_info"], "band": band}

    # -- bookkeeping ---------------------------------------------------------------------------------------------------------------------

    def log(self, s: str) -> None:
        self.env.log(f"departure probe: {s}")
        try:
            self.fs.append_jsonl(self.dir / "run_log.jsonl", {"t_s": round(self.env.now() - self.t0, 1), "phase": self.phase, "msg": s[:2000]})
        except (OSError, g.LabRootError):
            pass

    def mark(self, status: str, reason: str) -> None:
        if STATUS_RANK[status] > STATUS_RANK[self.status]:
            self.status = status
        self.notes.append(f"{status}: {reason}"[:600])
        if not self.stopping:
            self.stopping = True
            self.stop_reason = reason[:600]
        if status != "COMPLETED":
            self.log(f"{status}: {reason}")

    def pin_drift_found(self, label: str, detail: Any) -> None:
        """The pinned game files changed during the run (the pin check before every replay): an integrity failure of the native run, treated
        as a tick-contract failure (S6): PROBE_INVALID on the first detection, so no verdict is drawn (owner, 2026-11-03)."""
        self.c["pin_drift"] += 1
        self.pin_drift.append({"label": label, "detail": detail})
        self.mark("PROBE_INVALID", f"the pinned game files changed during the run (pin drift, detected before {label}): "
                                   f"{json.dumps(detail, default=str)[:400]} (an integrity failure of the native run; owner, 2026-11-03)")

    def native_elapsed(self) -> float:
        return 0.0 if self.t_native is None else self.env.now() - self.t_native

    def deadline_reached(self) -> bool:
        return self.t_native is not None and self.native_elapsed() >= self.cfg.max_wall_s - self.cfg.stop_reserve_s

    # -- run ----------------------------------------------------------------------------------------------------------------------------------

    def run(self) -> int:
        try:
            self.open()
        except Refused as exc:
            self.fs.write_json(self.cfg.out / f"refused_{g.utc_compact()}.json", {"mode": "lab", "utc": g.utc(), "reason": str(exc)})
            print(f"REFUSED: {exc}", flush=True)
            if self.sampler is not None:
                self.sampler.stop()
            return EXIT["REFUSED"]
        except Exception as exc:  # noqa: BLE001 - an open failure after launching is a closed, reported stop
            self.mark("PROBE_INCOMPLETE", f"open failed: {type(exc).__name__}: {exc}")
            self.log(traceback.format_exc()[-2000:])
        else:
            if not self.stopping:
                try:
                    self.dispatch_phase()
                except Exception as exc:  # noqa: BLE001
                    self.mark("PROBE_INCOMPLETE", f"probe error: {type(exc).__name__}: {exc}")
                    self.log(traceback.format_exc()[-2000:])
        try:
            self.close()
        except Exception as exc:  # noqa: BLE001
            self.mark("PROBE_INCOMPLETE", f"close error: {type(exc).__name__}: {exc}")
            self.log(traceback.format_exc()[-2000:])
            try:
                self.write_summary()
            except Exception:  # noqa: BLE001
                self.log(traceback.format_exc()[-2000:])
        return EXIT[self.status]

    # -- open: refusals, then the controls (the clear twice, the filler reference) ---------------------------------------------------------------

    def open(self) -> None:
        env = self.env
        if self.dir.exists():
            raise Refused(f"{self.dir} exists (a run folder is never overwritten)")
        ready = env.readiness()
        if not ready["ok"]:
            raise Refused(f"readiness: {ready['problems']}")
        pids = env.battleship_pids()
        if pids is None or pids:
            raise Refused(f"BattleShip processes already running (or unreadable): {pids}")
        bad = env.import_problems()
        if bad:
            raise Refused(f"import pins: {bad[:6]}")
        self.fs.mkdir(self.dir)
        self.code = env.code_manifest()
        self.fs.write_json(self.dir / "config.json", self.config_record(ready))
        self.sampler = fm.Sampler(lambda r: self.fs.append_jsonl(self.dir / "memory.jsonl", r), interval=env.sample_s, row_every=env.row_every_s,
                                  caps=env.caps or fm.CAPS_MB, soft=env.soft, snapshot=env.snapshot, now=env.now,
                                  extra=lambda: {"phase": self.phase, "dispatched": self.c["dispatched"]}).start()
        self.phase = "controls"
        self.t_native = env.now()
        words = self.clear["words"]
        D, P = int(self.plan["departure"]["D"]), int(self.plan["period"]["P"])
        filler = bytes(words[:D]) + bytes([NEUTRAL_WORD]) * P
        jobs = {"clear_r1": (words, 0), "clear_r2": (words, 1), "filler": (filler, 2)}
        res: Dict[str, Tuple[Optional[Dict[str, Any]], List[str]]] = {}
        drift: List[Dict[str, Any]] = []
        with cf.ThreadPoolExecutor(max_workers=3) as ex:
            futs = {ex.submit(fv.replay_with_retry, pin_watch(env.replay, drift), w, f"control_{k}", slot): k for k, (w, slot) in jobs.items()}
            for fu in cf.as_completed(futs):
                res[futs[fu]] = fu.result()
        for k, (tr, _e) in res.items():
            if tr is not None:
                self.c["control_ticks"] += len(tr.get("steps") or [])
                fv.save_trace(self.dir / "traces" / f"control_{k}.json.gz", tr)
        self.check_controls(res, filler, D, P, drift)

    def check_controls(self, res: Mapping[str, Tuple[Optional[Dict[str, Any]], List[str]]], filler: bytes, D: int, P: int,
                       drift: Sequence[Mapping[str, Any]] = ()) -> None:
        words, row = self.clear["words"], self.clear["row"]
        ev = {k: fv.evaluate(res[k][0], words, self.env.analyse) for k in ("clear_r1", "clear_r2")}
        claim = {"words_digest": row["words_digest"], "completion_input_tick": row["completion_input_tick"],
                 "completion_time_passed": row["completion_time_passed"], "chain": row["claim"]["chain"]}
        v = fv.verdict(ev["clear_r1"], ev["clear_r2"], claim)
        per_tick = {k: res[k][0] is not None and chain_list(res[k][0]) == self.ref_chain["clear"] for k in ("clear_r1", "clear_r2")}
        breaks_ok = {k: ev[k].get("breaks") == row["breaks_r1"] for k in ev}
        contract = {k: res[k][0] is not None and ticks_ok_of(res[k][0]) for k in ev}       # step_count too (fv.evaluate does not check it)
        ftr, ferr = res["filler"]
        fill: Dict[str, Any] = {"errors": ferr, "ran": ftr is not None}
        if ftr is not None:
            fch = chain_list(ftr)
            lines = set(self.P["geo"]["group_lines"])
            n = len(ftr["steps"])
            off = next((t for t in range(D + 1, n + 1) if not (grounded(reply_at(ftr, t)) and floor_line(reply_at(ftr, t)) in lines)), None)
            self.later_max = (off - 1) if off is not None else min(n, D + P)
            fill.update({"ticks": n, "ticks_ok": ticks_ok_of(ftr), "digest_ok": ftr.get("action_digest") == mcell.words_digest(filler[:n]),
                         "chain_at_D_equal": len(fch) > D and fch[D] == self.ref_chain["clear"][D], "first_tick_off_group": off,
                         "later_max_d": self.later_max, "outcome": outcome_of(ftr, len(filler))})
            self.ref_chain["filler"] = fch
        self.controls = {"clear": {"verdict": v["verdict"], "reasons": v["reasons"], "per_tick_chain_equal": per_tick, "breaks_equal": breaks_ok,
                                   "tick_contract_ok": contract,
                                   "clocks": [[ev[k].get("completion_input_tick"), ev[k].get("completion_time_passed")] for k in ev],
                                   "errors": [res[k][1] for k in ev]},
                         "filler": fill, "pin_drift": [dict(x) for x in drift]}
        self.fs.write_json(self.dir / "controls.json", self.controls)
        if drift:
            for x in drift:
                self.pin_drift_found(x["label"], x["detail"])
            return
        if v["verdict"] == fv.ERROR or not fill["ran"]:
            self.mark("PROBE_INCOMPLETE", f"a control replay could not run: {v['reasons']} {ferr[:2]}")
            return
        if v["verdict"] != fv.VERIFIED or not all(per_tick.values()) or not all(breaks_ok.values()) or not all(contract.values()):
            self.mark("PROBE_INVALID", f"the clear did not replay exactly in two fresh processes: {v['reasons']} per tick {per_tick} breaks {breaks_ok} "
                                       f"tick contract {contract}")
            return
        if not (fill["ticks_ok"] and fill["digest_ok"] and fill["chain_at_D_equal"]):
            self.mark("PROBE_INVALID", f"the filler reference does not reproduce the clear's prefix: {fill}")
            return
        later_cut = [c for c in self.cands if c["side"] == "later" and int(c["d"]) > int(self.later_max)]
        self.not_dispatched = [{"label": c["label"], "d": c["d"], "why": "the filler reference leaves the group before d"} for c in later_cut]
        cut = {c["idx"] for c in later_cut}
        self.queue = deque(c for c in self.cands if c["idx"] not in cut)
        self.log(f"controls: the clear replayed exactly twice; filler stays on the group to {self.later_max} "
                 f"({len(later_cut)} later candidates beyond it are not dispatched); {len(self.queue)} candidates queued")

    def config_record(self, ready: Mapping[str, Any]) -> Dict[str, Any]:
        import frs_lab as fl
        import frs_run as fr

        c = self.cfg
        return {"mode": "lab", "contract": PROBE_CONTRACT, "utc": g.utc(), "probe_file_sha256": g.sha256_file(Path(__file__).resolve()),
                "lab_code_digest": fr.code_digest(self.code) if self.code else None, "lab_code_files": len(self.code), "git": fl.git_state(),
                "slots": c.slots, "max_wall_s": c.max_wall_s, "stop_reserve_s": c.stop_reserve_s, "readiness": ready,
                "max_battleship_processes": fm.MAX_BATTLESHIP, "memory_caps_mb": dict(self.env.caps or fm.CAPS_MB),
                "head_checked": c.head, "flags_verify": fv.FLAGS_VERIFY, "backend": self.env.backend,
                "candidate_set_digest": self.plan["candidate_set_digest"],
                "candidates": self.plan["candidates"], "ticks_planned": self.plan["ticks_planned"], "clear": self.plan["clear"],
                "variants": self.plan["variants"], "budget": self.plan["budget"], "window": self.plan["window"],
                "band": None if self.band is None else {k: self.band.get(k) for k in ("rule", "sources", "arc", "P", "digest")}, "cost_estimate": dict(self.cost)}

    # -- dispatch ---------------------------------------------------------------------------------------------------------------------------------

    def run_candidate(self, c: Mapping[str, Any], slot: int) -> Dict[str, Any]:
        t = self.env.now()
        drift: List[Dict[str, Any]] = []
        try:
            tr, errors = fv.replay_with_retry(pin_watch(self.env.replay, drift), c["words"], c["label"], slot)
            if tr is not None and self.cfg.save_traces:
                fv.save_trace(self.dir / "traces" / f"{c['label']}.json.gz", tr)          # saved before it is read (a crash keeps it)
            row = read_candidate(tr, c, self.ctx, errors)
        except Exception as exc:  # noqa: BLE001 - a crashed candidate is a failed row, never hidden
            row = {"idx": c["idx"], "label": c["label"], "d": c["d"], "side": c["side"], "variant": c["variant"], "outcome": "error",
                   "valid": False, "failed": True, "errors": [f"{type(exc).__name__}: {exc}"[:400]]}
        if drift:                                                                          # no process was launched: the run is PROBE_INVALID
            row.update(outcome="pin_drift", valid=False, failed=True, pin_drift=drift[0])
        row["wall_s"] = round(self.env.now() - t, 2)
        row["slot"] = slot
        return row

    def dispatch_phase(self) -> None:
        cfg, env = self.cfg, self.env
        assert self.sampler is not None
        self.phase = "dispatch"
        free = list(range(cfg.slots))[::-1]
        running: Dict[cf.Future, Tuple[Dict[str, Any], int]] = {}
        with cf.ThreadPoolExecutor(max_workers=cfg.slots) as ex:
            while True:
                while self.queue and free and not self.stopping:
                    if self.deadline_reached():
                        self.mark("PARTIAL", f"the native-time cap {cfg.max_wall_s / 60.0:g} min is reached (minus the {cfg.stop_reserve_s:.0f} s stop reserve)")
                        break
                    c = self.queue.popleft()
                    slot = free.pop()
                    running[ex.submit(self.run_candidate, c, slot)] = (c, slot)
                    self.c["dispatched"] += 1
                if not running:
                    break
                done, _ = cf.wait(list(running), timeout=0.5, return_when=cf.FIRST_COMPLETED)
                for fu in done:
                    c, slot = running.pop(fu)
                    free.append(slot)
                    self.on_row(fu.result())
                self.checks()
                self.progress()
        self.t_native_end = env.now()
        self.progress(force=True)

    def on_row(self, row: Dict[str, Any]) -> None:
        with self._lock:
            self.rows.append(row)
            self.c["returned"] += 1
            self.c["ticks"] += int(row.get("ticks") or 0)
            self.c["valid"] += int(bool(row.get("valid")))
            self.c["failed"] += int(bool(row.get("failed")))
            self.fs.append_jsonl(self.dir / "results.jsonl", row)
        if row.get("outcome") == "contract":
            self.c["contract"] += 1
            self.mark("PROBE_INVALID", f"the tick contract or the action digest failed on {row['label']}: {row.get('contract')} "
                                       "(an integrity failure of the native run; owner, 2026-11-03)")
        if row.get("outcome") == "pin_drift":
            self.pin_drift_found(row["label"], (row.get("pin_drift") or {}).get("detail"))
        if row.get("outcome") == "mismatch":
            self.c["mismatches"] += 1
            self.log(f"prefix mismatch on {row['label']} (first differing tick {row.get('mismatch_first_tick')}): that process is retired; "
                     f"the run continues with fresh processes ({self.c['mismatches']} of {MISMATCH_ABORT})")
            if self.c["mismatches"] >= MISMATCH_ABORT:
                self.mark("ABORTED", f"{self.c['mismatches']} prefix-digest mismatches")
        if row.get("side") == "control":
            fb = row.get("first_break") or {}
            if not (row.get("valid") and row.get("chain_at_B_equal") and fb.get("tick") == self.plan["baseline"]["B"]
                    and fb.get("target") == self.plan["baseline"]["target"]):
                self.mark("PROBE_INVALID", f"the in-run control (d = D, the clear's own exit) does not reproduce B: {fb} {row.get('outcome')}")
        planned = len(self.cands) - len(self.not_dispatched)
        if planned and self.c["failed"] > FAILED_SHARE_MAX * planned:
            self.mark("PROBE_INCOMPLETE", f"{self.c['failed']} of {planned} candidates failed to run (> {FAILED_SHARE_MAX:.0%})")

    def checks(self) -> None:
        s = self.sampler
        assert s is not None
        if s.hard_breach:
            self.mark("PROBE_INCOMPLETE", s.hard_breach)
        elif s.proc_breach:
            self.mark("PROBE_INCOMPLETE", s.proc_breach)
        elif g.LabGuard.violations:
            self.mark("PROBE_INVALID", f"guard violation in the main process: {g.LabGuard.violations[:2]}")
        elif s.soft_breach:
            self.mark("MEMORY_BUDGET", s.soft_breach)

    def progress(self, force: bool = False) -> None:
        now = self.env.now()
        if not force and now - self._last_progress < self.cfg.progress_every_s:
            return
        self._last_progress = now
        beats = sum(1 for r in self.rows if r.get("beats_B"))
        self.log(f"native {self.native_elapsed():.0f}s dispatched {self.c['dispatched']} returned {self.c['returned']} valid {self.c['valid']} "
                 f"failed {self.c['failed']} mismatches {self.c['mismatches']} beat B {beats} queued {len(self.queue)}")
        try:
            self.fs.write_json(self.dir / "state.json", {"mode": "lab", "utc": g.utc(), "phase": self.phase, "native_s": round(self.native_elapsed(), 1),
                                                          "counters": self.c, "status": self.status, "stop": self.stop_reason, "queued": len(self.queue)})
        except OSError:
            pass

    # -- close --------------------------------------------------------------------------------------------------------------------------------

    def close(self) -> None:
        self.phase = "close"
        left = self.env.wait_no_battleship(60.0)
        if self.t_native is not None and self.t_native_end is None:
            self.t_native_end = self.env.now()
        changed = [rel for rel, h in self.code.items() if (g.REPO / rel).is_file() and g.sha256_file(g.REPO / rel) != h]
        self.integrity.update({"guard_violations_main": list(g.LabGuard.violations)[:5], "lab_code_changed_during_run": changed,
                               "probe_file_sha256_end": g.sha256_file(Path(__file__).resolve()), "battleship_left": left,
                               "prefix_mismatches": self.c["mismatches"]})
        if left:
            self.mark("PROBE_INCOMPLETE", f"BattleShip processes still alive after the close: {left}")
        self.write_summary()
        self.log(f"done: {self.status} ({self.stop_reason}); summary {self.dir / 'summary.json'}")

    def write_summary(self) -> Dict[str, Any]:
        mem = self.sampler.stop() if self.sampler is not None else {}
        planned = len(self.cands) - len(self.not_dispatched)
        v = verdict_of(self.rows, planned, self.status, int(self.plan["baseline"]["B"]), self.band is not None)
        native_s = None if self.t_native is None else round((self.t_native_end or self.env.now()) - self.t_native, 1)
        later_d = sorted({int(c["d"]) for c in self.cands if c["side"] == "later"})
        cut_d = sorted({int(x["d"]) for x in self.not_dispatched})
        later_cut = {"filler_first_tick_off_group": (self.controls.get("filler") or {}).get("first_tick_off_group"), "later_max_d": self.later_max,
                     "later_planned_d": len(later_d), "later_dispatched_d": len(later_d) - len(cut_d), "cut": bool(cut_d),
                     "counted_as": "complete: the later window is the ticks the filler stays grounded on the group (owner, 2026-11-02)"}
        s = {"mode": "lab", "contract": PROBE_CONTRACT, "claims": "none (the probe never extends a candidate to a clear and claims nothing)",
             "status": self.status, "stop": {"reason": self.stop_reason, "notes": self.notes[:12]}, "verdict": v, "verdict_line": verdict_line(v),
             "git": {"head": self.cfg.head}, "utc_start": self.utc_start, "utc_end": g.utc(), "folder": str(self.dir), "native_s": native_s,
             "max_wall_s": self.cfg.max_wall_s,
             "elapsed_s": round(self.env.now() - self.t0, 1), "counters": dict(self.c), "planned_after_filler": planned,
             "not_dispatched": len(self.not_dispatched), "later_max_d": self.later_max, "later_cut": later_cut, "controls": self.controls,
             "derived": {k: self.plan[k] for k in ("group", "group_lines", "axis", "departure", "period", "baseline", "budget", "window", "variants",
                                                    "on_group_breaks", "pre_break", "progress_rule", "spans", "candidate_set_digest", "candidates")},
             "band": None if self.band is None else {k: self.band.get(k) for k in ("rule", "sources", "arc", "P", "axis_value_range", "directions",
                                                                                  "onsets", "digest")},
             "curve_by_type": curve_by_type(self.rows), "progress_by_type": curve_by_type(self.rows, "progress"), "cost_estimate": dict(self.cost),
             "memory": {"peak": mem.get("peak"), "soft_breach": mem.get("soft_breach"), "hard_breach": mem.get("hard_breach"),
                        "proc_breach": mem.get("proc_breach")}, "integrity": dict(self.integrity, pin_drift=self.pin_drift[:5])}
        self.fs.write_text(self.dir / "summary.json", frep.compact_json(s), atomic=True)
        self.fs.write_text(self.dir / "curve.csv", curve_csv(self.rows), atomic=True)
        if self.not_dispatched:
            self.fs.write_text(self.dir / "not_dispatched.jsonl", "".join(json.dumps(x, separators=(",", ":")) + "\n" for x in self.not_dispatched))
        self.fs.write_text(self.dir / "report.md", report_md(s, self.rows), atomic=True)
        return s


def report_md(s: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> str:
    v, dv = s["verdict"], s["derived"]
    dep, base = dv["departure"], dv["baseline"]
    pbs, nd, sd = v["pre_break"], v["did_not_depart_at_d"], v["sides"]
    band = s["band"]
    lines = [f"# Departure probe run ({s['utc_start'][:10]})", "",
             f"Lab, exploratory, unregistered; no claims. Status **{s['status']}** ({s['stop']['reason']}). HEAD `{(s.get('git') or {}).get('head')}`.", "",
             f"**{verdict_line(v)}**", "",
             "| measure | value |", "|---|---|",
             f"| native time / cap | {frep.fmt(s['native_s'], 0)} s / {frep.fmt(s['max_wall_s'], 0)} s |",
             f"| group / lines / axis | {dv['group']} / {dv['group_lines']} / {dv['axis']} |",
             f"| contact C0..C1 / first grounded F / G / A / D / L | {dep['C0']}..{dep['C1']} / {dep['F']} / {dep['G']} / {dep['A']} / {dep['D']} / {dep['L']} |",
             f"| later window cut (filler first off the group / last later d / later d dispatched of planned) | "
             f"{s['later_cut']['filler_first_tick_off_group']} / {s['later_cut']['later_max_d']} / {s['later_cut']['later_dispatched_d']} of "
             f"{s['later_cut']['later_planned_d']} (counted as complete) |",
             f"| sides of the band tested (outside the band, departed at d: earlier / of them pre-break / later) | {sd['earlier']} / "
             f"{sd['earlier_pre_break']} / {sd['later']} ({sd['which']}) |",
             f"| pre-break departures (d range; valid / departed at d / outside band / beat B, counted) | {dv['pre_break']['d']}; {pbs['valid']} / "
             f"{pbs['departed_at_d']} / {pbs['outside_band']} / {pbs['beats_B']} |",
             f"| did not depart at d (rows / pre-break / by reason; never counted) | {nd['rows']} / {nd['pre_break']} / {nd['by_reason']} |",
             f"| baseline B (target) / B - D / budget E | {base['B']} ({base['target']}) / {base['B_minus_D']} / {dv['budget']['E']} |",
             f"| progress rule: baseline live mask at B (live targets) | {dv['progress_rule']['baseline_mask']} ({dv['progress_rule']['baseline_live_targets']}) |",
             f"| period P / origin | {dv['period']['P']} / {dv['period']['origin']} |",
             f"| band arc (start, length) / sources / digest | {None if band is None else (band['arc']['start'], band['arc']['length'])} / "
             f"{None if band is None else band['sources']} / {None if band is None else band.get('digest')} |",
             f"| candidates planned / after filler / returned / valid / counted (departed at d) / failed / mismatches / contract / pin drift | "
             f"{dv['candidates']} / {s['planned_after_filler']} / {s['counters']['returned']} / {s['counters']['valid']} / {v['counted']} / "
             f"{s['counters']['failed']} / {s['counters']['mismatches']} / {s['counters']['contract']} / {s['counters']['pin_drift']} |",
             f"| beat B (all / pre-break / outside band / outside band pre-break) / distinct d (all / outside band) | {v.get('beats_B')} / "
             f"{v.get('beats_B_pre_break')} / {v.get('beats_B_outside_band')} / {v.get('beats_B_outside_band_pre_break')} / {v.get('d_beating_B')} / "
             f"{v.get('d_beating_B_outside_band')} |",
             f"| first break earlier than B without the baseline's progress before B (all / outside band) | {v.get('earlier_with_less_progress')} / "
             f"{v.get('outside_band_earlier_less_progress')} |",
             f"| outside band: first break at or after B / no break | {v.get('outside_band_later_break')} / {v.get('outside_band_no_break')} |",
             f"| best | {json.dumps(v.get('best'), separators=(',', ':'), default=str)[:800]} |", "",
             "Curve (counted rows only; per d: first-break tick / progress tick after d, chained from tick 0; '-' = none within the budget; "
             "'nd' = did not depart at d; 'x' = failed or not run):", "",
             "| d | phase | in band | clear exit | generic best |", "|---|---|---|---|---|"]
    by: Dict[int, List[Mapping[str, Any]]] = {}
    for r in rows:
        by.setdefault(int(r["d"]), []).append(r)

    def cell(rs: Sequence[Mapping[str, Any]]) -> str:
        dep_rows = [r for r in rs if r.get("valid") and r.get("departed_at_d")]
        if not dep_rows:
            return "nd" if any(r.get("valid") for r in rs) else "x"
        r = min(dep_rows, key=lambda x: (x.get("progress_tick") is None, x.get("progress_tick") or 0, ((x.get("first_break") or {}).get("tick") is None)))
        fb = (r.get("first_break") or {}).get("tick")
        return f"{'-' if fb is None else fb} / {'-' if r.get('progress_tick') is None else r['progress_tick']}"

    for d in sorted(d for d, rs in by.items() if not any(r.get("pre_break") for r in rs)):
        rs = by[d]
        inb = next((r.get("in_band") for r in rs if r.get("valid") and r.get("departed_at_d")), "-")
        lines.append(f"| {d} | {rs[0].get('d_phase')} | {inb} | {cell([r for r in rs if r['variant'] == VARIANT_CLEAR])} | "
                     f"{cell([r for r in rs if r['variant'] != VARIANT_CLEAR])} |")
    pre_rows = sorted((r for r in rows if r.get("pre_break")), key=lambda r: (int(r["d"]), r["variant"]))
    lines += ["", "Pre-break departures (before the clear's on-group break; their own part of the curve with their own counts; counted like any "
                  "departure, so a pre-break row beats B only when its progress tick is before B): the first break each reaches, as the native "
                  "records report it.", "",
              f"By first-break target: {json.dumps(pbs['first_break_by_target'], separators=(',', ':'))}", "",
              "| d | variant | phase | departed at d | in band | first break tick | target | on-group target | baseline's next | progress tick | beats B |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in pre_rows:
        fb = r.get("first_break") or {}
        lines.append(f"| {r['d']} | {r['variant']} | {r.get('d_phase')} | {r.get('departed_at_d', r.get('outcome'))} | {r.get('in_band')} | "
                     f"{fb.get('tick', '-')} | {fb.get('target', '-')} | {fb.get('on_group_target', '-')} | {fb.get('same_as_baseline_next', '-')} | "
                     f"{'-' if r.get('progress_tick') is None else r['progress_tick']} | {r.get('beats_B')} |")
    lines += ["", f"Controls: {json.dumps(s['controls'], separators=(',', ':'), default=str)[:1600]}", "",
              f"Integrity: {json.dumps(s['integrity'], separators=(',', ':'), default=str)}", ""]
    return "\n".join(lines)


# -- commands ---------------------------------------------------------------------------------------------------------------------------------


def run_command(lab_root: Path, out: Path, a: argparse.Namespace, clear_spec: str, digest: str, band: str, head: str) -> str:
    return (f"python -B tools/frs/departure_probe.py run --lab-root {Path(lab_root).as_posix()} --out {Path(out).as_posix()} --clear {clear_spec} "
            f"--variants {a.variants} --seed {a.seed} --budget-factor {a.budget_factor:g} --slots {a.slots} --max-wall-min {a.max_wall_min:g} "
            f"--expect-digest {digest} --expect-band {band} --expect-head {head}")


def git_facts(repo: Path = REPO) -> Dict[str, Any]:
    """HEAD and the tracked changes under TRACKED_DIRS (git status; untracked files are not changes). None = could not be read."""
    def git(*args: str) -> Optional[str]:
        try:
            r = subprocess.run(["git", *args], capture_output=True, text=True, cwd=str(repo), timeout=120)
        except (OSError, subprocess.SubprocessError):
            return None
        return r.stdout if r.returncode == 0 else None

    head = git("rev-parse", "HEAD")
    st = git("status", "--porcelain", "--untracked-files=no", "--", *TRACKED_DIRS)
    return {"head": head.strip() if head else None, "tracked_changes": None if st is None else [ln for ln in st.splitlines() if ln.strip()]}


def tree_problems(facts: Mapping[str, Any], expect_head: Optional[str]) -> List[str]:
    """N5 (owner, 2026-11-03): a run refuses a tracked change under TRACKED_DIRS and a HEAD other than --expect-head (the full hash)."""
    out: List[str] = []
    if not facts.get("head"):
        out.append("HEAD could not be read")
    elif facts["head"] != expect_head:
        out.append(f"HEAD {facts['head']} differs from --expect-head {expect_head}")
    ch = facts.get("tracked_changes")
    if ch is None:
        out.append("git status could not be read")
    elif ch:
        out.append(f"{len(ch)} tracked changes under {', '.join(x + '/' for x in TRACKED_DIRS)}: {list(ch)[:6]}")
    return out


def under_import(out: Path, lab: Path) -> bool:
    return any(g.under(a, b) for a in g.forms(out) for b in g.forms(Path(lab) / "import"))


def out_problems(out: Path, lab: Path, digest: str, band: Optional[str]) -> List[str]:
    """S5 (owner, 2026-11-03): --out is never under the lab's import folder, and an existing --out may hold only this plan's plan.json (same
    candidate-set digest and, when given, band digest), candidates.jsonl and refused_*.json files from a refused attempt."""
    out = Path(out)
    probs: List[str] = []
    if under_import(out, lab):
        probs.append(f"{out} is under the lab's import folder")
    if not out.exists():
        return probs
    if not out.is_dir():
        return probs + [f"{out} exists and is not a folder"]
    for p in sorted(out.iterdir()):
        if p.name == "plan.json" and p.is_file():
            try:
                saved = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                probs.append(f"{p} cannot be read: {exc}")
                continue
            if saved.get("candidate_set_digest") != digest:
                probs.append(f"{p} holds another candidate set ({saved.get('candidate_set_digest')})")
            if band is not None and (saved.get("band") or {}).get("digest") != band:
                probs.append(f"{p} holds another band ({(saved.get('band') or {}).get('digest')})")
        elif p.is_file() and (p.name == "candidates.jsonl" or (p.name.startswith("refused_") and p.name.endswith(".json"))):
            continue
        else:
            probs.append(f"{p} (an existing --out may hold only this plan's plan.json, candidates.jsonl and refused_*.json)")
    return probs


def refuse(msg: str) -> int:
    print(f"refused: {msg}", flush=True)
    return EXIT["REFUSED"]


def prepare(lab: Path, a: argparse.Namespace) -> Dict[str, Any]:
    clf = mcell.Classifier()
    clear = load_clear(lab, a.clear)
    P = build_plan(clear, ProbeParams(variants=a.variants, seed=a.seed, budget_factor=a.budget_factor), clf)
    ident = clear["ident"]
    spec = f"{ident['run']}:{ident['n']}:{ident['cid']}"
    return {"clf": clf, "clear": clear, "P": P, "spec": spec}


def describe(L: Mapping[str, Any], cost: Mapping[str, Any], slots: int, band: Optional[Mapping[str, Any]], listing: bool) -> List[str]:
    p, P = L["P"]["plan"], L["P"]
    dep, base, per = p["departure"], p["baseline"], p["period"]
    ga = p["group_at"]
    out = [f"clear: {json.dumps({k: p['clear'][k] for k in ('run', 'n', 'cid', 'words', 'completion_input_tick', 'completion_time_passed', 'is_best_verified', 'verified_rows_in_lab')}, separators=(',', ':'))}",
           "input records: r1 and r2 traces both evaluate to the verification row (clocks, digest, final chain, breaks), equal per tick; "
           f"native-record break table equals the row's ({len(p['clear']['breaks'])} breaks, anomalies {len(p['break_anomalies'])})"]
    for gm in p["groups"]:
        out.append(f"moving group: id {gm['group']} lines {gm['lines']} translation ranges {gm['ranges']} axis {gm['axis']}")
    for i, iv in enumerate(p["contact_intervals"]):
        out.append(f"contact interval {i}{' (chosen)' if i == p['chosen_interval'] else ''}: group {iv['group']} ticks {iv['start']}..{iv['end']} "
                   f"({iv['ticks']}) riding {iv['riding']} still {iv['still']} ride-or-still {iv['ride_or_still']}")
    out.append(f"departure: C0 {dep['C0']}, first grounded F {dep['F']}, D {dep['D']} (status {dep['status_D']}, grounded {dep['grounded_D']}, floor line "
               f"{dep['floor_line_D']}); exit status run starts S {dep['S']} (status {dep['status_G']}); last grounded G {dep['G']}; airborne A {dep['A']} "
               f"(status {dep['status_A']}); last tick with the floor line on the group C1 {dep['C1']}; first tick off it L {dep['L']}")
    xr = p["exit_run"]
    a1, c1, l1 = xr["at_A"], xr["at_C1"], xr["at_L"]
    out.append(f"exit run A {a1['tick']}..C1 {c1['tick']} ({xr['ticks']} ticks): all airborne {xr['all_airborne']}; spatial.fighter.floor_line_id "
               f"{xr['floor_lines']} throughout (the floor line under the fighter, airborne or not); status runs {xr['status_runs']}")
    out.append(f"  at A: {json.dumps(a1, separators=(',', ':'))}")
    out.append(f"  at C1: {json.dumps(c1, separators=(',', ':'))}")
    out.append(f"  at L: {json.dumps(l1, separators=(',', ':'))}")
    out.append(f"  reading: from A the fighter is airborne; floor_line_id stays on the group's line while {xr['position_axis']} is inside the line's "
               f"extent {c1['group_line_span']} (vertices plus translation); at C1 it is {(-c1['floor_dist']) if c1['floor_dist'] is not None else '?'} above "
               f"the line (floor_dist {c1['floor_dist']}), {xr['position_axis']} {c1['x'] if xr['position_axis'] == 'position_x' else c1['y']}; at L "
               f"{xr['position_axis']} {l1['x'] if xr['position_axis'] == 'position_x' else l1['y']} is outside it and the floor line becomes {l1['floor_line_id']}. "
               f"Contact (grounded on the group) ended at G {dep['G']}")
    sp = p["spans"]
    out.append(f"spans: D {sp['D']} -> A {sp['A']} -> L {sp['L']} -> landing {sp['landing']} (first grounded tick after L, floor line "
               f"{sp['landing_floor_line']}; floor lines under the flight {sp['flight_floor_lines']}) -> B {sp['B']}; parts {sp['parts']} sum "
               f"{sp['parts_sum']} = B - D {sp['B_minus_D']}; B - L {sp['B_minus_L']}; ticks C0..C1 {sp['contact_ticks_C0_to_C1']}")
    out.append(f"period: P {per['P']} (gaps {per['gaps']}), origin {per['origin']}; group at C0 {json.dumps(ga['C0'])}; at D {json.dumps(ga['D'])}; "
               f"at A {json.dumps(ga['A'])}")
    out.append(f"baseline: B {base['B']} target {base['target']} (B - D {base['B_minus_D']}); mask at B {base['mask']} (before {base['mask_before']}); "
               f"end state {json.dumps(base['end_state'], separators=(',', ':'))}")
    w = p["window"]
    out.append(f"window ({w['rule']}; full {w['full']}): earlier d {w['earlier'][0]}..{w['earlier'][1]} ({w['earlier'][2]}), "
               f"later d {None if not w['later'] else str(w['later'][0]) + '..' + str(w['later'][1])} ({0 if not w['later'] else w['later'][2]}); "
               f"{w['d_count']} departure ticks")
    out.append(f"variants: {p['variants']['clear_exit']} (the clear's exit words D..B shifted to d, then neutral word {p['neutral_word']} "
               f"{p['neutral_triple']}) + generic {p['variants']['generic']} (seed {p['variants']['seed']}, draw id {p['variants']['draw_id']}); "
               f"budget E {p['budget']['E']} = ceil({p['budget']['factor']:g} x {base['B_minus_D']}) (margin {p['budget']['margin']})")
    out.append(f"flight sign along the axis at A: {p['flight_sign']:+d}")
    pb, pr = p["pre_break"], p["progress_rule"]
    out.append(f"on-group breaks of the clear (F <= tick <= D): {p['on_group_breaks']}; pre-break departures d {pb['d']} "
               f"(labelled pre-break, their own part of the curve with their own counts; counted like any departure: a gain only when the "
               f"progress tick is before B; on the band's earlier side when outside the band)")
    out.append(f"progress: a candidate beats B when, at a tick before B, its live mask is a subset of the baseline's at B ({pr['baseline_mask']}, "
               f"live targets {pr['baseline_live_targets']}): every target the baseline had broken, in any order")
    out.append("departure of each candidate: measured with the D rule on the contact run that contains d; a row counts only when its departure "
               "tick is d (the band side and the band test use that departure)")
    out.append(f"window start: {w['start_rule']}; excluded airborne contact ticks {w['excluded_airborne_contact'][0]}..{w['excluded_airborne_contact'][1]} "
               f"({w['excluded_airborne_contact'][2]})")
    out.append(f"candidates: {p['candidates']} ({w['d_count']} d x {1 + p['variants']['K']}), ticks planned {p['ticks_planned']:,}, "
               f"candidate-set digest {p['candidate_set_digest']}")
    cands = P["candidates"]
    out.append("dispatch order (first 12): " + " ".join(c["label"] for c in cands[:12]) + " ...")
    out.append("last 6: " + " ".join(c["label"] for c in cands[-6:]))
    if band is not None:
        bc = band_counts(cands, P["d_info"], band, int(dep["D"]))
        ph = sorted({r["phase"] for r in band["rows"]} | {band["own"]["phase"]})
        out.append(f"band: arc start {band['arc']['start']} length {band['arc']['length']} (of P {band['P']}) from {band['sources']} verified clears "
                   f"(skipped {len(band['skipped'])}) and the probed clear; departure phases {ph}; axis values {band['axis_value_range']}, directions "
                   f"{band['directions']}")
        out.append(f"band onsets (status of G, G - D, rows): {[[x['status_G'], x['G_minus_D'], x['rows']] for x in band['onsets']]}; probed clear "
                   f"{json.dumps(band['own'], separators=(',', ':'))}")
        out.append(f"planned departure ticks (as if each departs at d): in band {bc['in_band']} (pre-break {bc['in_band_pre_break']}); outside the band "
                   f"on the earlier side {bc['outside_earlier']} (pre-break {bc['outside_earlier_pre_break']}), on the later side {bc['outside_later']}")
        out.append(f"band digest {band['digest']}")
    else:
        out.append("band digest: not computed (give --band; the run needs --expect-band)")
    ctl = [len(L["clear"]["words"]), len(L["clear"]["words"]), int(dep["D"]) + int(per["P"])]
    ew = expected_wall(cands, cost, slots, ctl)
    if ew is None:
        out.append("cost: no measured replay-timing record in the lab; no estimate")
    else:
        out.append(f"cost model ({cost['source']}): slot s = {cost['fixed_s']} + {cost['per_tick_s'] * 1000:.3f} ms x ticks at {cost['slots']} at once "
                   f"({cost['replays']} replays, mean {cost['mean_ticks']} ticks, {cost['aggregate_s_per_replay']} s per replay overall)")
        if cost.get("cross_check"):
            cc = cost["cross_check"]
            out.append(f"cross-check ({cc['source']}): wall = {cc['wall_s_fixed']} + {cc['wall_s_per_tick'] * 1000:.3f} ms x ticks over {cc['replays']} replays")
        out.append(f"expected native wall at {slots} slots: open {ew['open_s']} s + candidates {ew['candidates_s']} s = {ew['native_min']} min "
                   f"({ew['per_candidate_slot_s']} slot s per candidate)")
    if listing:
        out.append("candidate list (label d side variant ticks words_digest):")
        out.extend(f"  {c['label']} {c['d']} {c['side']} {c['variant']} {c['ticks']} {c['words_digest'][:16]}" for c in cands)
    return out


def cmd_dry_run(lab: Path, out: Path, a: argparse.Namespace) -> int:
    L = prepare(lab, a)
    band = band_of(lab, L["P"]["plan"], L["P"]["geo"]) if a.band else None
    cost = measured_cost(lab)
    for ln in describe(L, cost, a.slots, band, a.list):
        print(ln)
    facts = git_facts()
    ch = facts.get("tracked_changes")
    print(f"git: HEAD {facts.get('head')}; tracked changes under {', '.join(x + '/' for x in TRACKED_DIRS)}: "
          f"{'unreadable' if ch is None else len(ch)}{' (commit them first: the run refuses them)' if ch else ''}")
    digest = L["P"]["plan"]["candidate_set_digest"]
    bad = out_problems(out, lab, digest, band["digest"] if band is not None else None)
    print(f"output folder {out.as_posix()}: {'refused by the run: ' + '; '.join(bad) if bad else 'accepted by the run'}")
    print("dry run: zero native ticks, nothing written, no lock taken")
    head = facts["head"] if facts.get("head") and ch == [] else "<HEAD after the commit>"
    print("phase 2 command:", run_command(lab, out, a, L["spec"], digest, band["digest"] if band is not None else "<run the dry run with --band>", head))
    return 0


def cmd_run(lab: Path, out: Path, a: argparse.Namespace) -> int:
    """Every refusal here comes before anything is written or launched: the git state, the candidate set, the band, the output folder."""
    import frs_lab as fl
    from m7_runtime import install_kill_on_close_job

    facts = git_facts()
    bad = tree_problems(facts, a.expect_head)
    if bad:
        return refuse(f"git: {bad}")
    L = prepare(lab, a)
    p = L["P"]["plan"]
    if p["candidate_set_digest"] != a.expect_digest:
        return refuse(f"the candidate set {p['candidate_set_digest']} differs from --expect-digest {a.expect_digest}")
    band = band_of(lab, p, L["P"]["geo"])
    if band["digest"] != a.expect_band:
        return refuse(f"the band {band['digest']} differs from --expect-band {a.expect_band}")
    bad = out_problems(out, lab, p["candidate_set_digest"], band["digest"])
    if bad:
        return refuse(f"output folder: {bad[:4]}")
    run_dir = out / "run"
    cost = measured_cost(lab)
    fs = g.LabFS(lab)
    fs.mkdir(out)
    fs.write_json(out / "plan.json", dict(p, band=band, git={"head": facts["head"]}))
    fs.write_text(out / "candidates.jsonl", "".join(json.dumps(candidate_row(c), separators=(",", ":")) + "\n" for c in L["P"]["candidates"]),
                  atomic=True)
    install_kill_on_close_job()
    cfg = ProbeConfig(lab_root=lab, out=out, run_dir=run_dir, slots=a.slots, max_wall_s=60.0 * a.max_wall_min, head=facts["head"])
    code = Probe(cfg, fl.real_env(lab, run_dir), L["clear"], L["P"], band, L["clf"], cost).run()
    print(f"exit {code}: {run_dir / 'report.md'}")
    return code


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("command", nargs="?", choices=("run",), help="run (native, Phase 2); omit with --dry-run")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--lab-root", default=str(g.DEFAULT_LAB_ROOT))
    ap.add_argument("--out", default=None, help="default <lab root>/departure_probe_<date>")
    ap.add_argument("--clear", default="best", help="best (the fastest VERIFIED lab clear) or RUN:N:CID")
    ap.add_argument("--variants", type=int, default=1, help="K generic exit variants per departure tick")
    ap.add_argument("--seed", type=int, default=1, help="the Python seed in the burst generator's key family (never native RNG)")
    ap.add_argument("--budget-factor", type=float, default=2.0, help="exit budget E = ceil(F x (B - D)) words after d")
    ap.add_argument("--band", action="store_true", help="dry run: also read the other verified clears' traces for the band and its digest")
    ap.add_argument("--list", action="store_true", help="dry run: print every planned candidate")
    ap.add_argument("--slots", type=int, default=5)
    ap.add_argument("--max-wall-min", type=float, default=MAX_WALL_MIN)
    ap.add_argument("--expect-digest", default=None, help="run: the candidate-set digest printed by --dry-run")
    ap.add_argument("--expect-band", default=None, help="run: the band digest printed by --dry-run --band")
    ap.add_argument("--expect-head", default=None, help="run: the full HEAD hash the run must start from (git rev-parse HEAD)")
    a = ap.parse_args(argv)
    if a.dry_run == (a.command == "run"):
        return refuse("give exactly one of --dry-run or run")
    if not 0 < a.max_wall_min <= MAX_WALL_MIN:
        return refuse(f"--max-wall-min is in (0, {MAX_WALL_MIN:g}]")
    if not 1 <= a.slots <= 5:
        return refuse("1 to 5 slots (at most 5 game processes at once)")
    if a.variants < 0 or a.budget_factor < 1.0:
        return refuse("--variants >= 0, --budget-factor >= 1")
    try:
        lab = g.validate_lab_root(Path(a.lab_root))
        out = g.validate_run_dir(Path(a.out) if a.out else lab / f"departure_probe_{dt.date.today().isoformat()}", lab)
    except g.LabRootError as exc:
        print(str(exc), flush=True)
        return EXIT["REFUSED"]
    if under_import(out, lab):
        return refuse(f"--out {out} is under the lab's import folder")
    g.LabGuard.install(lab)
    if a.dry_run:
        try:
            return cmd_dry_run(lab, out, a)
        except ProbeError as exc:
            print(f"stopped: {exc}")
            return 3
    missing = [k for k, v in (("--expect-digest", a.expect_digest), ("--expect-band", a.expect_band), ("--expect-head", a.expect_head)) if not v]
    if missing:
        return refuse(f"run needs {', '.join(missing)} (printed by --dry-run --band)")
    if not (lab / "import" / "import_manifest.json").is_file():
        return refuse("no lab import (rl/frs_lab.py import first)")
    lock = g.LabLock(lab, "departure_probe run")
    try:
        lock.acquire()
    except g.LabRootError as exc:
        print(str(exc), flush=True)
        return EXIT["REFUSED"]
    try:
        return cmd_run(lab, out, a)
    except ProbeError as exc:
        print(f"stopped: {exc}")
        return 3
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
