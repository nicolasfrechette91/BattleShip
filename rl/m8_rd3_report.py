"""M8-rd3: the registered diagnostics, the rule inputs and the read-only post-run verification (zero native ticks).

The nine diagnostics D1-D9 of rd2 (rl/m8_rd2_report.py, reused unchanged) are computed for rd3's dispatches beside two reference columns, both recomputed by the same functions from
the archives: rd2 (its dispatches 2,175..6,211, evaluated on rd2's closing archive = rd3's base) and rd1 (0..2,174, on rd1's archive). The new reports of the decisions (I7):

    wall-top cells and the dispatches from them          cells of class G on floor line 0; dispatch events whose start cell is one
    cells left of the wall face                          stored x < -1,650 (and, additionally, x < -1,800 and x < -2,100)
    closest approach to the left floor                   minimum point-to-segment distance from a cell's (x, y) to floor line 3
    selection probability of the wall-top cells at the open   the analytic v2 probability under the archive as materialised (before any rd3 dispatch)

Everything is derived from the archive (cells, bursts, the ordered ledger) and the session files. Nothing here is read by the selection, the explorer, the cell key or the rule.
"""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import m8_rd_archive as march  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_claims as mclaims  # noqa: E402
import m8_rd_select2 as s2  # noqa: E402
import m8_rd2_report as rpt2  # noqa: E402
import m8_rd2_rule as rule2  # noqa: E402
import m8_rd3_rule as rule3  # noqa: E402
import m8_rd3_select as s3  # noqa: E402

I_X, I_Y = mcell.I_X, mcell.I_Y
WALL_FACE_X = -1650.0                           # the M7f wall-face reference
LEFT_X_THRESHOLDS = (-1650.0, -1800.0, -2100.0)
LEFT_FLOOR_LINE = mcell.LEFT_FLOOR_LINES[0]     # floor line 3


def _read(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def left_floor_segment() -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """The two vertices of floor line 3, read lazily from the pinned native line table (rl/m7g_spatial.EXPECTED_LINES, the table the tick-0 pin digest covers)."""
    import m7g_spatial as sp

    for lid, typ, _group, _flags, verts in sp.EXPECTED_LINES:
        if lid == LEFT_FLOOR_LINE and typ == sp.LINE_FLOOR:
            return (float(verts[0][0]), float(verts[0][1])), (float(verts[1][0]), float(verts[1][1]))
    raise RuntimeError(f"floor line {LEFT_FLOOR_LINE} not found in the pinned line table")


def seg_distance(px: float, py: float, a: Tuple[float, float], b: Tuple[float, float]) -> float:
    """The distance from a point to the closed segment ab."""
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    n = dx * dx + dy * dy
    u = 0.0 if n == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / n))
    return math.hypot(px - (ax + u * dx), py - (ay + u * dy))


class _Bursts:
    """A view with only `.bursts` (the rd2 reading helpers read nothing else)."""

    def __init__(self, bursts: Sequence[Any]):
        self.bursts = list(bursts)


def bursts_in(a: march.Archive, it_lo: int, it_hi: Optional[int] = None) -> _Bursts:
    return _Bursts([b for b in a.bursts if b.iteration >= it_lo and (it_hi is None or b.iteration <= it_hi)])


# -- the new diagnostics ------------------------------------------------------------------------------------------------------------------


def wall_top_cells(a: march.Archive) -> List[march.Cell]:
    return [c for c in a.cells if c.key[2] == mcell.RES_GROUNDED and c.key[4] == mcell.L0_FLOOR_LINE]


def new_diagnostics(a: march.Archive, it_lo: int, it_hi: Optional[int] = None) -> Dict[str, Any]:
    """The decisions' additional readings, for the dispatches of an iteration range and the cells of `a`."""
    rows = rpt2.dispatch_rows(a, it_lo, it_hi)
    wt = wall_top_cells(a)
    wt_ids = {c.id for c in wt}
    xs = [(float(c.end[I_X]), c.id) for c in a.cells]
    seg = left_floor_segment()

    def dist(c: march.Cell) -> float:
        return seg_distance(float(c.end[I_X]), float(c.end[I_Y]), seg[0], seg[1])

    air = [c for c in a.cells if c.key[2] in (mcell.RES_A2, mcell.RES_A1)]
    near = min(a.cells, key=dist) if a.cells else None
    near_air = min(air, key=dist) if air else None
    left = {f"x_lt_{int(t)}": sum(1 for x, _i in xs if x < t) for t in LEFT_X_THRESHOLDS}
    leftmost = min(xs) if xs else None
    return {"wall_top": {"cells": len(wt), "cell_ids": [c.id for c in wt][:40], "dispatches_from": sum(1 for r in rows if r["cell"] in wt_ids), "dispatches": len(rows),
                         "shortest_L": min((c.L for c in wt), default=None), "highest_y": max((float(c.end[I_Y]) for c in wt), default=None)},
            "left_of_wall_face": {**left, "wall_face_x": WALL_FACE_X, "leftmost_x": leftmost[0] if leftmost else None, "leftmost_cell": leftmost[1] if leftmost else None},
            "left_floor_approach": {"floor_line": LEFT_FLOOR_LINE, "segment": [list(seg[0]), list(seg[1])],
                                    "min_distance_all": dist(near) if near else None, "nearest_cell": near.id if near else None,
                                    "nearest_class": near.key[2] if near else None,
                                    "nearest_position": [float(near.end[I_X]), float(near.end[I_Y])] if near else None,
                                    "min_distance_a2a1": dist(near_air) if near_air else None, "nearest_a2a1_cell": near_air.id if near_air else None,
                                    "nearest_a2a1_position": [float(near_air.end[I_X]), float(near_air.end[I_Y])] if near_air else None}}


def open_selection_probabilities(a: s2.Archive2) -> Dict[str, Any]:
    """The analytic v2 selection probability of the wall-top cells under the archive as it stands (call it on the archive as materialised: before any rd3 dispatch)."""
    probs = a.probabilities()
    wt = wall_top_cells(a)
    per = {str(c.id): {"eligible": bool(a.eligible(c)), "probability": probs.get(c.id, 0.0), "level": c.level, "L": c.L, "chosen": c.chosen, "seen": c.seen} for c in wt}
    levels = a.eligible_levels()
    top = max(levels) if levels else None
    return {"wall_top_cells": len(wt), "eligible": sum(1 for v in per.values() if v["eligible"]), "total_probability": sum(v["probability"] for v in per.values()),
            "per_cell": per, "eligible_cells": sum(len(v) for v in levels.values()), "top_eligible_level": top,
            "per_dispatch_expectation_over_100_dispatches": 100.0 * sum(v["probability"] for v in per.values())}


# -- the rule inputs ------------------------------------------------------------------------------------------------------------------------


def rule_inputs3(a: s3.Archive3, first_it: int, first_new_cell: int) -> Dict[str, Any]:
    """The registered counts of rd3 (iterations from `first_it`, cells from `first_new_cell`). BOUND_VIOLATION counts only violations recorded in rd3's bursts."""
    ins = dict(rpt2.rule_inputs(a, first_it, first_new_cell))
    ins["bound_violations"] = sum(1 for v in a.diag2["bound_violations"] if int(v.get("iteration", -1)) >= first_it)
    return ins


RD3_LEVELS = ("crossing", "left_target", "clear")             # the wall-top landing is rd2's: rd3 does not re-claim it


def replay_verified_m(replays: Sequence[Mapping[str, Any]]) -> int:
    """The highest ladder level (crossing, left target, clear) held by an exactly replayed trajectory. The replays' `l0` flag reads the whole trajectory, prefix included, so a descendant
    of a wall-top cell always shows it: the wall-top landing is therefore not part of rd3's m (it is rd2's, and never progress)."""
    m = 0
    for r in replays:
        if not r.get("exact"):
            continue
        lv = mclaims.levels_of(r)
        for name in RD3_LEVELS:
            if lv[name]:
                m = max(m, mclaims.ladder_index(name))
    return m


def replay_verified_t(replays: Sequence[Mapping[str, Any]]) -> int:
    """The largest number of targets broken by any exactly replayed trajectory (the maximum-targets candidate is replayed first, so it is among them)."""
    return max((int(r["t"]) for r in replays if r.get("exact")), default=0)


# -- the full report ------------------------------------------------------------------------------------------------------------------------


def full_report3(rd3_dir: Path, rd2_dir: Path, rd1_dir: Path, session: str = "rd3") -> Dict[str, Any]:
    """The registered diagnostics of a finished rd3 session beside rd2's and rd1's reference values (all recomputed from the archives)."""
    rd3_dir, rd2_dir, rd1_dir = Path(rd3_dir), Path(rd2_dir), Path(rd1_dir)
    sd = rd3_dir / "sessions" / session
    d, meta, rep = march.load_latest_verified(rd3_dir / "archive")
    if d is None:
        return {"ok": False, "reason": "no verified archive checkpoint", "checkpoints": rep}
    a, meta = s3.Archive3.read_dir(d)
    base, bmeta = s3.Archive3.read_dir(rd3_dir / "base")                    # rd2's closing archive = the archive at rd3's open
    a1, _m1 = s2.Archive2.read_dir(rd1_dir / "archive")
    rng = a.iteration_ranges()
    r3_first = int(a.rd3_first_iteration if a.rd3_first_iteration is not None else 0)
    n_rd1, n_rd2 = len(a1.cells), len(base.cells)
    rd2_lo, rd2_hi = rng["rd2"]
    rd3 = rpt2.diagnostics(a, r3_first, None, first_new_cell=n_rd2)
    out: Dict[str, Any] = {"iteration_ranges": {k: list(v) for k, v in rng.items()}, "first_new_cell": {"rd2": n_rd1, "rd3": n_rd2},
                           "rd3": rd3, "rd2_reference": rpt2.diagnostics(base, int(rd2_lo or 0), rd2_hi, first_new_cell=n_rd1),
                           "rd1_reference": rpt2.diagnostics(a1, 0, int(rd2_lo or 0) - 1, first_new_cell=0)}
    out["new"] = {"rd3": new_diagnostics(a, r3_first), "rd2_reference": new_diagnostics(base, int(rd2_lo or 0), rd2_hi), "rd1_reference": new_diagnostics(a1, 0, int(rd2_lo or 0) - 1)}
    out["selection_probability_at_the_open"] = open_selection_probabilities(base)
    rd2_ver = rd2_dir / "sessions" / "rd2" / "verification.json"
    out["D9_max_targets"] = {"archive_top_level": max(c.level for c in a.cells), "rd1": rule2.RD1["max_targets"],
                             "rd2": (_read(rd2_ver).get("arm") or {}).get("t") if rd2_ver.is_file() else None}
    out["upb_start_heights"] = {"rd3": rpt2.upb_start_heights(bursts_in(a, r3_first)), "rd2_reference": rpt2.upb_start_heights(bursts_in(base, int(rd2_lo or 0), rd2_hi))}
    out["ground_runs"] = {"rd3": rpt2.ground_run_readings(bursts_in(a, r3_first)), "rd2_reference": rpt2.ground_run_readings(bursts_in(base, int(rd2_lo or 0), rd2_hi))}
    rows = s2.overlay_rows(a)
    close_counts = s2.overlay_counts(a, rows)
    open_p = rd3_dir / "derived" / "open_overlay.json"
    base_d2 = bmeta.get("diag2") or {}
    own = {k: (len(v) if isinstance(v, list) else v) for k, v in a.diag2.items()}
    base_own = {k: (len(v) if isinstance(v, list) else v) for k, v in base_d2.items()}
    out["D8_v2_mechanism"] = {"open": _read(open_p)["counts"] if open_p.is_file() else None,
                              "close": {k: close_counts[k] for k in ("eligible_v1", "descent_among_v1_eligible", "bound_among_v1_eligible", "union", "eligible_v2")},
                              "counters_cumulative": own, "counters_rd2_close": base_own, "counters_rd3": {k: own[k] - base_own.get(k, 0) for k in own},
                              "exact_ground_evidence_shadow": rpt2.exact_evidence_shadow(a)}
    def efficiency(arm_path: Path, returns: int, new_cells: int) -> Optional[Dict[str, Any]]:
        if not arm_path.is_file():
            return None
        arm = _read(arm_path)
        ticks, prefix = arm.get("ticks", 0), arm.get("prefix_ticks", 0)
        return {"ticks": ticks, "prefix_ticks": prefix, "prefix_share": (prefix / ticks) if ticks else None, "new_exploration_ticks": ticks - prefix, "returns": returns,
                "new_cells_per_return": new_cells / returns if returns else None, "ticks_per_s": arm.get("ticks_per_s"), "wall_s": arm.get("wall_s"), "select_s": arm.get("select_s")}

    eff3 = efficiency(sd / "arm_T.json", rd3["returns"], len(a.cells) - n_rd2)
    if eff3 is not None:
        out["D7_efficiency"] = eff3
    out["D7_efficiency_references"] = {"rd2": efficiency(rd2_dir / "sessions" / "rd2" / "arm_T.json", out["rd2_reference"]["returns"], n_rd2 - n_rd1),
                                       "rd1": efficiency(rd1_dir / "sessions" / "rd1" / "arm_T.json", out["rd1_reference"]["returns"], n_rd1 - 1)}
    rd2_close = rd2_dir / "sessions" / "rd2" / "close.json"
    rd2_open = rd2_dir / "derived" / "open_overlay.json"
    if rd2_close.is_file():
        c2 = (_read(rd2_close).get("archive") or {})
        out["D8_v2_mechanism_rd2_reference"] = {"open": _read(rd2_open)["counts"] if rd2_open.is_file() else None,
                                                "close": {k: (c2.get("overlay_close") or {}).get(k) for k in ("eligible_v1", "descent_among_v1_eligible", "bound_among_v1_eligible", "union", "eligible_v2")},
                                                "counters": c2.get("diag2")}
    ver_p = sd / "verification.json"
    if ver_p.is_file():
        v = _read(ver_p)
        out["D9_max_targets"]["verified_in_rd3"] = (v.get("arm") or {}).get("max_targets")
    out["rule_inputs"] = rule_inputs3(a, r3_first, n_rd2)
    return out


# -- read-only post-run verification ----------------------------------------------------------------------------------------------------------


def verify_run3(rd3_dir: Path, rd2_dir: Path, rd1_dir: Path, session: str = "rd3") -> Dict[str, Any]:
    """Independent of the driver: the rd3 archive verifies and its ledger rebuilds it exactly (three parts); rd3's files begin with rd2's closing bytes and rd2's begin with rd1's;
    the overlay file hashes to its record; the rule record is recomputed from the archive, the earlier sessions' records and the verification replays; every route's actions hash
    to its metadata; the iteration rows add up to the arm's ticks; no replay used for a claim is inexact unless the session is INVALID."""
    import m8_rd_claims as mclaims
    import m8_rd_resume as rs
    import m8_rd3_resume as r3

    rd3_dir, rd2_dir, rd1_dir = Path(rd3_dir), Path(rd2_dir), Path(rd1_dir)
    sd = rd3_dir / "sessions" / session
    problems: List[str] = []
    info: Dict[str, Any] = {}
    d, meta, rep = march.load_latest_verified(rd3_dir / "archive")
    info["checkpoints"] = rep
    rule = _read(sd / "rule.json") if (sd / "rule.json").is_file() else None
    if rule is None:
        problems.append("no rule.json: the session recorded no decision")
    for f in ("close.json", "state.json"):
        if not (sd / f).is_file():
            problems.append(f"no {f}")
    if (sd / "state.json").is_file() and _read(sd / "state.json").get("phase") != "done":
        problems.append(f"the session state is {_read(sd / 'state.json').get('phase')!r}, not done")
    if d is None or meta is None:
        return {"ok": False, "problems": ["no archive checkpoint with a verifying manifest"], "info": info}
    if Path(d).name != "archive":
        problems.append(f"the newest checkpoint directory does not verify: the verified one is {Path(d).name}")
    a, meta = s3.Archive3.read_dir(d)
    lines = (meta.get("pin_tick0") or {}).get("lines")
    close_p = sd / "close.json"
    if close_p.is_file():
        rec_manifest = (_read(close_p).get("archive") or {}).get("manifest")
        if rec_manifest != {n: march.sha256_file(Path(d) / n) for n in march.DATA_FILES}:
            problems.append("the archive's files differ from the manifest the close record stores")
    aud = s3.audit3(a, str(lines))
    info["audit"] = {k: aud[k] for k in ("ok", "cells", "bursts", "events")}
    if not aud["ok"]:
        problems += [f"audit: {p}" for p in aud["problems"][:5]]
    chain = r3.prefix_chain(rd1_dir / "archive", rd2_dir / "archive", d)
    info["prefix_chain"] = {"ok": chain["ok"]}
    if not chain["ok"]:
        problems += chain["problems"]
    ov, ovr = rd3_dir / "derived" / "open_overlay.jsonl", rd3_dir / "derived" / "open_overlay.json"
    if ov.is_file() and ovr.is_file():
        if rs.sha256_file(ov) != _read(ovr)["sha256"]:
            problems.append("the overlay file differs from its recorded digest")
    else:
        problems.append("no open overlay record")
    r3_first = int(a.rd3_first_iteration if a.rd3_first_iteration is not None else 0)
    n_open = len(s3.Archive3.read_dir(rd3_dir / "base")[0].cells) if (rd3_dir / "base").is_dir() else 0
    rp = sd / "verification" / "replays.jsonl"
    reps = [json.loads(ln) for ln in rp.read_text(encoding="utf-8").splitlines()] if rp.is_file() else []
    if rule is not None:
        if rule["rule_sha256"] != rule3.rule_digest():
            problems.append("the rule digest in the record differs from the current rule")
        ins = rule_inputs3(a, r3_first, n_open)
        prior = r3.prior_milestones(rd1_dir, rd2_dir)
        again = rule3.apply(invalid=rule["invalid"], incomplete=rule["incomplete"], m=rule["m"], t=rule["max_targets_verified"], below_floor=ins["below_floor"],
                            dispatches=ins["dispatches"], fatal_returns=ins["fatal_returns"], returns=ins["returns"], launch_capable_created=ins["launch_capable_created"],
                            prior=prior, bound_violations=ins["bound_violations"], top_level_median_L=ins["top_level_median_L"])
        for k in ("outcome", "m", "max_targets_verified", "any_stop"):
            if again[k] != rule[k]:
                problems.append(f"rule record: {k} {rule[k]} differs from the recomputation {again[k]}")
        info["recomputed_outcome"] = again["outcome"]
        m_again = replay_verified_m(reps)
        if m_again != rule["m"]:
            problems.append(f"rule record: m {rule['m']} differs from the milestone the exact replays hold ({m_again})")
        t_again = replay_verified_t(reps)
        if t_again != rule["max_targets_verified"]:
            problems.append(f"rule record: max targets {rule['max_targets_verified']} differs from the maximum the exact replays hold ({t_again})")
    for r in sorted((rd3_dir / "routes").glob("*")) if (rd3_dir / "routes").is_dir() else []:
        meta_p, act_p = r / "metadata.json", r / "actions.jsonl"
        if not (meta_p.is_file() and act_p.is_file()):
            problems.append(f"{r.name}: incomplete route directory")
            continue
        rows = [json.loads(ln) for ln in act_p.read_text(encoding="utf-8").splitlines()]
        digest = mcell.native_digest([(x["buttons"], x["stick_x"], x["stick_y"], x["consumed_tick"]) for x in rows])
        if digest != _read(meta_p)["native_action_digest"] or [x["consumed_tick"] for x in rows] != list(range(len(rows))):
            problems.append(f"{r.name}: actions differ from the recorded digest or consumed ticks")
    p, arm_p = sd / "iterations_T.jsonl", sd / "arm_T.json"
    if p.is_file() and arm_p.is_file():
        rows = [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()]
        total = sum(int(x["ticks"]) for x in rows if "ticks" in x)
        if total != _read(arm_p)["ticks"]:
            problems.append(f"iteration rows add up to {total} ticks, the arm record says {_read(arm_p)['ticks']}")
        if any(x.get("tick0_equal") is False for x in rows):
            problems.append("a row reports a tick-0 mismatch")
    if rule is not None and not rule["invalid"] and rp.is_file():
        bad = [r["label"] for r in reps if not r.get("exact")]
        if bad:
            problems.append(f"inexact replays in a session that is not INVALID: {bad[:4]}")
        info["replays"] = len(reps)
    return {"ok": not problems, "problems": problems, "info": info}


# -- the budget projection (preparation): rd2's, reused unchanged -----------------------------------------------------------------------------


budget_projection = rpt2.budget_projection
