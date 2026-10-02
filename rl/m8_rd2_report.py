"""M8-rd2: the registered diagnostics D1-D9, the rule inputs and the read-only post-run verification (zero native ticks).

Every figure is derived from the archive (cells, bursts, the ordered ledger) and the session files. The same functions run on rd1's
archive, which must reproduce the reference values of the continuation proposal (section 4.3); that reproduction is a unit test.
A position "at dispatch" is the stored position of the start cell's representative AT THE TIME OF THE DISPATCH, read from the win
record of the burst that created that representative.
"""
from __future__ import annotations

import gzip
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import m8_rd_archive as march  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_select2 as s2  # noqa: E402
import m8_rd2_rule as rule2  # noqa: E402

LEDGE_CORNER = (-1200.0, 3000.0)
LAUNCH_CAPABLE_Y = 1639.0
LAUNCH_CAPABLE_X = 600.0
BELOW_FLOOR_Y = -2850.0
BESIDE_X = 3600.0
LEFT_OF_WALL_X = -2100.0
I_X, I_Y, I_VY = mcell.I_X, mcell.I_Y, mcell.OBS_INDEX["air_velocity_y"]
CLASSES = (mcell.RES_GROUNDED, mcell.RES_A2, mcell.RES_A1, mcell.RES_A0)


def _read(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def region(x: float, y: float) -> str:
    if y < BELOW_FLOOR_Y:
        return "below"
    if x > BESIDE_X:
        return "beside"
    return "onlow" if y < 0 else "onhigh"


def is_launch_capable(res: str, y: float) -> bool:
    return res in (mcell.RES_A2, mcell.RES_A1) and float(y) >= LAUNCH_CAPABLE_Y


# -- dispatch rows -----------------------------------------------------------------------------------------------------------------


def win_ends(a: march.Archive) -> Dict[Tuple[int, int], Tuple[int, Sequence[Any]]]:
    """(burst id, tick j) -> (cell id, the 17-value end record) of every NEW / REPLACE reach: the position of a representative."""
    out: Dict[Tuple[int, int], Tuple[int, Sequence[Any]]] = {}
    for b in a.bursts:
        for w in b.wins:
            out[(b.id, int(w["j"]))] = (int(w["cell"]), w["end"])
    return out


def dispatch_rows(a: march.Archive, it_lo: int, it_hi: Optional[int] = None) -> List[Dict[str, Any]]:
    """One row per dispatch event with it_lo <= iteration <= it_hi: the start cell, its class, level, floor and the stored position of
    the representative it was dispatched with."""
    wend = win_ends(a)
    rows = []
    for ev in a.events:
        if ev["ev"] != "dispatch" or ev["it"] < it_lo or (it_hi is not None and ev["it"] > it_hi):
            continue
        c = a.cells[ev["cell"]]
        b, o = int(ev["rep"][0]), int(ev["rep"][1])
        if b == -1:
            end = a.cells[0].end
        else:
            got = wend.get((b, a.bursts[b].start_L + o))
            if got is None or got[0] != c.id:
                raise march.ArchiveError(f"dispatch {ev['it']}: no win record gives the position of representative {(b, o)} of cell {c.id}")
            end = got[1]
        rows.append({"it": ev["it"], "cell": c.id, "res": c.key[2], "floor": c.key[4], "level": c.level, "L": ev["L"],
                     "x": float(end[I_X]), "y": float(end[I_Y]), "vy": float(end[I_VY])})
    return rows


def _share(n: int, total: int) -> Dict[str, Any]:
    return {"n": int(n), "share": (n / total) if total else None}


# -- the diagnostics ----------------------------------------------------------------------------------------------------------------


def returns_of(a: march.Archive, it_lo: int, it_hi: Optional[int] = None) -> List[Dict[str, Any]]:
    """The ingested jobs (returns) of the iteration range, with the burst (None when the job was cut inside its prefix)."""
    out = []
    for ev in a.events:
        if ev["ev"] != "ingest" or ev["it"] < it_lo or (it_hi is not None and ev["it"] > it_hi):
            continue
        out.append({"it": ev["it"], "burst": ev["burst"], "ticks": ev["ticks"]})
    return out


def fatal_counts(a: march.Archive, rets: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    """Returns that ended in a native fall with no grounded tick: by the exact ground runs (rd2 bursts) and by the grounded REACHES
    (the reading rd1's diagnosis used; the only one an rd1 burst has)."""
    reach_fatal = exact_fatal = exact_available = 0
    for r in rets:
        if r["burst"] < 0:
            continue
        b = a.bursts[r["burst"]]
        if b.end_reason != "fall":
            continue
        touched_reach = any(a.cells[row[1]].key[2] == mcell.RES_GROUNDED for row in b.reaches)
        reach_fatal += int(not touched_reach)
        runs = getattr(b, "ground_runs", None)
        if runs is None:
            exact_fatal += int(not touched_reach)
        else:
            exact_available += 1
            exact_fatal += int(not runs)
    return {"fatal_by_reaches": reach_fatal, "fatal_exact": exact_fatal, "bursts_with_exact_runs": exact_available}


def diagnostics(a: march.Archive, it_lo: int, it_hi: Optional[int] = None, *, first_new_cell: Optional[int] = None) -> Dict[str, Any]:
    """D1-D6 and the supply readings for the iteration range (rd1: 0..2174; rd2: 2175..). `first_new_cell` = the first cell id created
    in the range (None = every cell)."""
    rows = dispatch_rows(a, it_lo, it_hi)
    n = len(rows)
    reg = {k: sum(1 for r in rows if region(r["x"], r["y"]) == k) for k in ("below", "beside", "onlow", "onhigh")}
    a21 = [r for r in rows if r["res"] in (mcell.RES_A2, mcell.RES_A1)]
    cells = a.cells
    new_ids = range(first_new_cell if first_new_cell is not None else 0, len(cells))
    launch_cells = [c for c in cells if is_launch_capable(c.key[2], float(c.end[I_Y]))]
    launch_new = [c for c in launch_cells if c.id in new_ids]
    rets = returns_of(a, it_lo, it_hi)
    fatal = fatal_counts(a, rets)
    a2_ys = [float(c.end[I_Y]) for c in cells if c.key[2] == mcell.RES_A2]
    dist = lambda c: math.hypot(float(c.end[I_X]) - LEDGE_CORNER[0], float(c.end[I_Y]) - LEDGE_CORNER[1])      # noqa: E731
    air = [c for c in cells if c.key[2] in (mcell.RES_A2, mcell.RES_A1)]
    near = min(cells, key=dist) if cells else None
    near_air = min(air, key=dist) if air else None
    left12 = [float(c.end[I_Y]) for c in cells if float(c.end[I_X]) <= -1200.0]
    left15 = [float(c.end[I_Y]) for c in cells if float(c.end[I_X]) <= -1500.0]
    highest = max(cells, key=lambda c: float(c.end[I_Y])) if cells else None
    return {
        "dispatches": n, "returns": len(rets), "iterations": [it_lo, it_hi],
        "D1_regions": {**{k: _share(v, n) for k, v in reg.items()}, "left_of_wall": _share(sum(1 for r in rows if r["x"] < LEFT_OF_WALL_X), n)},
        "D2_step_contact": {"dispatches": _share(sum(1 for r in rows if r["res"] == mcell.RES_GROUNDED and r["floor"] == 1), n),
                            "cells": sum(1 for c in cells if c.key[2] == mcell.RES_GROUNDED and c.key[4] == 1)},
        "D3_classes": {**{k: _share(sum(1 for r in rows if r["res"] == k), n) for k in CLASSES},
                       "a2a1_on_stage_y_ge_0": _share(sum(1 for r in a21 if r["y"] >= 0 and r["x"] <= BESIDE_X), n),
                       "a2_y_ge_0": _share(sum(1 for r in rows if r["res"] == mcell.RES_A2 and r["y"] >= 0), n)},
        "D4_supply": {"a2a1_cells": len(air),
                      "a2a1_on_stage_y_ge_0_cells_v1_eligible": sum(1 for c in air if march.Archive.eligible(c) and float(c.end[I_Y]) >= 0 and float(c.end[I_X]) <= BESIDE_X),
                      "launch_capable_cells": len(launch_cells),
                      "launch_capable_dispatches": sum(1 for r in rows if is_launch_capable(r["res"], r["y"])),
                      "launch_capable_cells_x_le_600": sum(1 for c in launch_cells if float(c.end[I_X]) <= LAUNCH_CAPABLE_X),
                      "highest_a2_y": max(a2_ys) if a2_ys else None,
                      "launch_capable_cells_created": len(launch_new), "launch_capable_created_per_1000_returns": rule2.rate_per_1000(len(launch_new), len(rets))},
        "D5_closest_approach": {"min_distance_to_ledge_corner": dist(near) if near else None, "nearest_cell": near.id if near else None,
                                "nearest_class": near.key[2] if near else None,
                                "min_distance_a2a1": dist(near_air) if near_air else None,
                                "best_y_at_x_le_-1200": max(left12) if left12 else None, "best_y_at_x_le_-1500": max(left15) if left15 else None,
                                "highest_cell_y": float(highest.end[I_Y]) if highest else None, "highest_cell": highest.id if highest else None},
        "D6_fatal_returns": {**fatal, "returns": len(rets),
                             "share_by_reaches": (fatal["fatal_by_reaches"] / len(rets)) if rets else None,
                             "share_exact": (fatal["fatal_exact"] / len(rets)) if rets else None},
        "below_floor_dispatches": reg["below"], "level_of_dispatches": {str(lv): sum(1 for r in rows if r["level"] == lv) for lv in range(mcell.TARGETS_TOTAL + 1)
                                                                       if any(r["level"] == lv for r in rows)},
    }


def upb_start_heights(a: march.Archive) -> Dict[str, Any]:
    """The up-B start readings of the rd2 bursts' resource transitions (A2 / A1 -> A0): heights, positions and the (height, x) Pareto
    front. Measured only in rd2 (rd1 has no such field); never compared with rd1."""
    pts = []
    for b in a.bursts:
        for t in getattr(b, "res_transitions", None) or []:
            j, frm, to, x, y = t
            if to == mcell.RES_A0 and frm in (mcell.RES_A2, mcell.RES_A1):
                pts.append({"burst": b.id, "tick": int(j), "from": frm, "x": float(x), "y": float(y)})
    front = []
    for p in sorted(pts, key=lambda p: (-p["y"], p["x"])):
        if not front or p["x"] < min(q["x"] for q in front):
            front.append(p)
    bands = {}
    for p in pts:
        k = int(math.floor(p["y"] / 500.0) * 500)
        bands[str(k)] = bands.get(str(k), 0) + 1
    return {"transitions": len(pts), "max_y": max((p["y"] for p in pts), default=None),
            "at_or_above_1639": sum(1 for p in pts if p["y"] >= LAUNCH_CAPABLE_Y),
            "min_x_at_or_above_1639": min((p["x"] for p in pts if p["y"] >= LAUNCH_CAPABLE_Y), default=None),
            "y_bands_500": dict(sorted(bands.items(), key=lambda kv: int(kv[0]))), "pareto_front_height_vs_leftness": front[:25]}


def exact_evidence_shadow(a: s2.Archive2) -> Dict[str, Any]:
    """How many cells' descent flags would differ if the grounded evidence of an rd2 burst were its EXACT ground runs instead of its grounded
    reaches. Decision 5 keeps the reaches (the exact runs are diagnostics only); this reads, never applies, the difference, so a later session can
    judge whether the exact evidence matters."""
    key_res = [c.key[2] for c in a.cells]
    length = [len(b.words) for b in a.bursts]
    fell = [b.end_reason == "fall" for b in a.bursts]
    parent = [b.start_rep[0] for b in a.bursts]
    par_off = [b.start_rep[1] for b in a.bursts]
    last_g = []
    for b in a.bursts:
        runs = getattr(b, "ground_runs", None)
        if runs is None:
            last_g.append(max((int(j) - b.start_L for j, cid, *_x in b.reaches if key_res[cid] == mcell.RES_GROUNDED), default=-1))
        else:
            last_g.append(max((int(r[1]) - b.start_L for r in runs), default=-1))
    R, F = s2.DescentTree.reference(length, fell, last_g, parent, par_off)
    exact = [bool(c.key[2] in s2.AIRBORNE and c.burst >= 0 and R[c.burst] <= c.offset <= F[c.burst]) for c in a.cells]
    only_exact = sum(1 for e, r in zip(exact, a.desc) if e and not r)
    only_reach = sum(1 for e, r in zip(exact, a.desc) if r and not e)
    return {"cells_differing": only_exact + only_reach, "doomed_only_under_exact_runs": only_exact, "doomed_only_under_reaches": only_reach}


def ground_run_readings(a: march.Archive) -> Dict[str, Any]:
    bs = [b for b in a.bursts if getattr(b, "ground_runs", None) is not None]
    return {"bursts": len(bs), "bursts_touching_ground": sum(1 for b in bs if b.ground_runs),
            "runs": sum(len(b.ground_runs) for b in bs), "ground_ticks": sum(r[1] - r[0] + 1 for b in bs for r in b.ground_runs)}


def first_new_cell(a: s2.Archive2) -> int:
    """The id of the first cell created in rd2 (cells are appended in creation order; rd1's cells all have first_iter < first_iteration)."""
    fi = int(a.first_iteration or 0)
    return next((c.id for c in a.cells if c.id and c.first_iter >= fi), len(a.cells))


def rule_inputs(a: s2.Archive2, first_it: int, first_new_cell: int) -> Dict[str, Any]:
    d = diagnostics(a, first_it, None, first_new_cell=first_new_cell)
    stats = a.stats()
    return {"below_floor": d["below_floor_dispatches"], "dispatches": d["dispatches"], "fatal_returns": d["D6_fatal_returns"]["fatal_exact"],
            "returns": d["returns"], "launch_capable_created": d["D4_supply"]["launch_capable_cells_created"],
            "bound_violations": len(a.diag2["bound_violations"]), "top_level_median_L": stats["top_level_median_L"]}


def full_report(root: Path, rd1_root: Path, session: str = "rd2") -> Dict[str, Any]:
    """The registered diagnostics of a finished rd2 session beside rd1's reference values (both recomputed from the archives)."""
    root, rd1_root = Path(root), Path(rd1_root)
    sd = root / "sessions" / session
    d, meta, rep = march.load_latest_verified(root / "archive")
    if d is None:
        return {"ok": False, "reason": "no verified archive checkpoint", "checkpoints": rep}
    a, meta = s2.Archive2.read_dir(d)
    a1, _m1 = s2.Archive2.read_dir(rd1_root / "archive")
    first_it = int(a.first_iteration or 0)
    n_rd1 = len(a1.cells)
    out: Dict[str, Any] = {"first_iteration": first_it, "first_new_cell": n_rd1, "rd2": diagnostics(a, first_it, None, first_new_cell=n_rd1),
                           "rd1_reference": diagnostics(a1, 0, first_it - 1, first_new_cell=0)}
    out["D9_max_targets"] = {"archive_top_level": max(c.level for c in a.cells), "rd1": rule2.RD1["max_targets"]}
    out["upb_start_heights"] = upb_start_heights(a)
    out["ground_runs"] = ground_run_readings(a)
    rows = s2.overlay_rows(a)
    close_counts = s2.overlay_counts(a, rows)
    open_p = root / "derived" / "open_overlay.json"
    out["D8_v2_mechanism"] = {"open": _read(open_p)["counts"] if open_p.is_file() else None,
                              "close": {k: close_counts[k] for k in ("eligible_v1", "descent_among_v1_eligible", "bound_among_v1_eligible", "union", "eligible_v2")},
                              "counters": a.diag2 | {"bound_violations": len(a.diag2["bound_violations"])},
                              "exact_ground_evidence_shadow": exact_evidence_shadow(a)}
    arm_p, rows_p = sd / "arm_T.json", sd / "iterations_T.jsonl"
    if arm_p.is_file():
        arm = _read(arm_p)
        ticks, prefix = arm.get("ticks", 0), arm.get("prefix_ticks", 0)
        returns = out["rd2"]["returns"]
        out["D7_efficiency"] = {"ticks": ticks, "prefix_ticks": prefix, "prefix_share": (prefix / ticks) if ticks else None,
                                "new_exploration_ticks": ticks - prefix, "returns": returns,
                                "new_cells_per_return": (len(a.cells) - n_rd1) / returns if returns else None,
                                "ticks_per_s": arm.get("ticks_per_s"), "wall_s": arm.get("wall_s"), "select_s": arm.get("select_s")}
    ver_p = sd / "verification.json"
    if ver_p.is_file():
        v = _read(ver_p)
        out["D9_max_targets"]["verified_in_rd2"] = (v.get("arm") or {}).get("t")
    out["rule_inputs"] = rule_inputs(a, first_it, n_rd1)
    return out


# -- the budget projection (preparation) --------------------------------------------------------------------------------------------------


# measured anchors (rd1, docs/rl_m8_rd_continuation_proposal_2026-10-02.md section 5): wall per job = 1.94 s + ticks / 1,523, 1,120 ticks
# per job, 2,175 returns, 1,560 aggregate ticks/s at about 75 % worker utilisation; the action-hold probe's pessimistic serial-boot fit
# wall = 2.22 s + ticks / 789 per episode (docs/rl_m8_rd_implementation.md section 6)
RD1_RATE_TICKS_PER_S = 1560.0
RD1_JOB_FIT = (1.94, 1523.0)
PESSIMISTIC_JOB_FIT = (2.22, 789.0)


def budget_projection(caps: Mapping[str, Any], workers: int = 5) -> Dict[str, Any]:
    """Native-tick and wall projections of the registered caps: expected, pessimistic (serial boots at the slow per-worker rate, the
    wall cap of exploration binding plus its 20 s grace) and every cap binding. The sum of the three phase caps equals the session cap,
    so the session clock stops anything beyond it by construction (a stop inside verification is INCOMPLETE)."""
    wc = caps["wall_caps_s"]
    open_cap, explore_cap, verify_cap = float(wc["p1"]), float(wc["T"]), float(wc["verify"])
    hard = float(caps["global_cap_s"])
    grace = float(caps["wall_cap_grace_s"])
    min_ticks, tick_cap = int(caps["min_exploration_ticks"]), int(caps["exploration_tick_cap"])
    need_rate = min_ticks / explore_cap                                        # ticks/s the exploration needs to be valid in its wall cap
    mean_job_ticks = 1120.0
    out: Dict[str, Any] = {"caps_s": {"open": open_cap, "exploration": explore_cap, "verification": verify_cap, "sum": open_cap + explore_cap + verify_cap,
                                      "session_hard_cap": hard}}
    # expected: rd1's measured aggregate rate
    exp_ticks = RD1_RATE_TICKS_PER_S * explore_cap
    out["expected"] = {"exploration_ticks": min(exp_ticks, tick_cap), "tick_cap_binds": exp_ticks >= tick_cap, "returns": exp_ticks / mean_job_ticks,
                       "wall_s": {"open": 90.0, "exploration": explore_cap if exp_ticks < tick_cap else tick_cap / RD1_RATE_TICKS_PER_S,
                                  "verification": 150.0}}
    out["expected"]["wall_s"]["total"] = sum(out["expected"]["wall_s"].values())
    # pessimistic: every job pays a serial boot and the slow per-worker rate
    boot, rate = PESSIMISTIC_JOB_FIT
    job_wall = boot + (mean_job_ticks + 300.0) / rate                          # a longer mean job (L + 120 up to 1,580)
    agg = workers * (mean_job_ticks + 300.0) / job_wall
    p_ticks = agg * explore_cap
    out["pessimistic"] = {"aggregate_ticks_per_s": round(agg, 1), "exploration_ticks": round(min(p_ticks, tick_cap)),
                          "valid_from_ticks": min_ticks, "needs_ticks_per_s": round(need_rate, 1), "valid": agg >= need_rate,
                          "wall_s": {"open": 150.0, "exploration": explore_cap + grace + 5.0, "verification": 240.0}}
    out["pessimistic"]["wall_s"]["total"] = sum(out["pessimistic"]["wall_s"].values())
    out["pessimistic"]["fits_hard_cap"] = out["pessimistic"]["wall_s"]["total"] <= hard
    out["every_cap_binding"] = {"wall_s": open_cap + explore_cap + verify_cap, "equals_hard_cap": open_cap + explore_cap + verify_cap == hard,
                                "note": "the phase caps sum to the session cap; the exploration phase may overrun its own cap by the 20 s grace"}
    out["fits_hard_cap_without_trimming"] = bool(out["pessimistic"]["fits_hard_cap"] and out["every_cap_binding"]["equals_hard_cap"]
                                                 and out["pessimistic"]["valid"])
    return out


# -- read-only post-run verification -----------------------------------------------------------------------------------------------


def verify_run(root: Path, rd1_root: Path, session: str = "rd2") -> Dict[str, Any]:
    """Independent of the driver: the rd2 archive verifies and its ledger rebuilds it exactly; the prefix property holds against rd1's
    archive; the overlay file hashes to its record; the rule record is recomputed from the archive and the verification record; every
    route's actions hash to its metadata; the iteration rows add up to the arm's ticks; no replay used for a claim is inexact unless the
    session is INVALID."""
    import m8_rd_claims as mclaims
    import m8_rd_resume as rs

    root, rd1_root = Path(root), Path(rd1_root)
    sd = root / "sessions" / session
    problems: List[str] = []
    info: Dict[str, Any] = {}
    d, meta, rep = march.load_latest_verified(root / "archive")
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
    a, meta = s2.Archive2.read_dir(d)
    lines = (meta.get("pin_tick0") or {}).get("lines")
    aud = s2.audit2(a, str(lines))
    info["audit"] = {k: aud[k] for k in ("ok", "cells", "bursts", "events")}
    if not aud["ok"]:
        problems += [f"audit: {p}" for p in aud["problems"][:5]]
    pp = rs.prefix_property(rd1_root / "archive", d)
    info["prefix_property"] = pp
    if not pp["ok"]:
        problems += pp["problems"]
    ov = root / "derived" / "open_overlay.jsonl"
    ovr = root / "derived" / "open_overlay.json"
    if ov.is_file() and ovr.is_file():
        if rs.sha256_file(ov) != _read(ovr)["sha256"]:
            problems.append("the overlay file differs from its recorded digest")
    else:
        problems.append("no open overlay record")
    if rule is not None:
        if rule["rule_sha256"] != rule2.rule_digest():
            problems.append("the rule digest in the record differs from the current rule")
        ins = rule_inputs(a, int(a.first_iteration or 0), first_new_cell(a))
        again = rule2.apply(invalid=rule["invalid"], incomplete=rule["incomplete"], m=rule["m"], below_floor=ins["below_floor"],
                            dispatches=ins["dispatches"], fatal_returns=ins["fatal_returns"], returns=ins["returns"],
                            launch_capable_created=ins["launch_capable_created"], bound_violations=ins["bound_violations"],
                            top_level_median_L=ins["top_level_median_L"])
        for k in ("outcome", "m"):
            if again[k] != rule[k]:
                problems.append(f"rule record: {k} {rule[k]} differs from the recomputation {again[k]}")
        info["recomputed_outcome"] = again["outcome"]
    for r in sorted((root / "routes").glob("*")) if (root / "routes").is_dir() else []:
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
    rp = sd / "verification" / "replays.jsonl"
    if rule is not None:
        reps = [json.loads(ln) for ln in rp.read_text(encoding="utf-8").splitlines()] if rp.is_file() else []
        m_again = mclaims.milestone_level(reps)
        if m_again != rule["m"]:
            problems.append(f"rule record: m {rule['m']} differs from the milestone the exact replays hold ({m_again})")
    if rule is not None and not rule["invalid"] and (sd / "verification" / "replays.jsonl").is_file():
        replays = [json.loads(ln) for ln in (sd / "verification" / "replays.jsonl").read_text(encoding="utf-8").splitlines()]
        bad = [r["label"] for r in replays if not r.get("exact")]
        if bad:
            problems.append(f"inexact replays in a session that is not INVALID: {bad[:4]}")
        info["replays"] = len(replays)
    return {"ok": not problems, "problems": problems, "info": info}
