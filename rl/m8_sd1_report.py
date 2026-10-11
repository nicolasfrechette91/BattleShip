"""M8-sd1: the registered diagnostics (reported only), the rule inputs and the read-only post-run verification (zero native ticks).

rd4's diagnostics (rl/m8_rd2_report.py D1-D9, rl/m8_rd3_report.py's readings, rl/m8_rd4_report.py's seen distribution and frontier returns, all reused unchanged) are computed for sd1's
dispatches beside rd4's reference column (its dispatches 10,406..13,885 on rd4's closing archive = sd1's base) and rd3's, rd2's and rd1's. The proposal's section 6.4 readings, as decided
on 2026-10-11 (no census number enters the code):

    the completion-tick distribution of every clear event sd1 registered (verified or not, marked)
    the best verified clear's two clocks, the tiers reached (reported only)
    dispatches to cells AHEAD OF THE RECORD PACE, per level: L < the record route's own arrival at that level, read at runtime from the record candidate's break table
    dispatches to cells within ONE BURST (120 words) of their level's shortest arrival at the open, and at or below the round threshold 2,000, per level
    the shortest L of each level at the open and at the close; the shortest verified left-floor landing
    the share of returns from cells seen 8 or more times and the new cells per return (rd4's mechanism readings, as readings only)
    the dilution verdict (reported only), E7's count at the open and at the close, the analytic v3-against-v4 selection masses on the same archive at the open

Nothing here is read by the selection, the explorer, the cell key or the rule.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import m8_rd_archive as march  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_explore as mx  # noqa: E402
import m8_rd_select2 as s2  # noqa: E402
import m8_rd2_report as rpt2  # noqa: E402
import m8_rd3_report as rpt3  # noqa: E402
import m8_rd4_report as rpt4  # noqa: E402
import m8_sd1_artifacts as art  # noqa: E402
import m8_sd1_claims as cl5  # noqa: E402
import m8_sd1_resume as r5  # noqa: E402
import m8_sd1_rule as rule5  # noqa: E402
import m8_sd1_select as s5  # noqa: E402

I_X, I_Y = mcell.I_X, mcell.I_Y
SESSIONS = s5.SESSIONS
ROUND_THRESHOLD = rule5.TIER_ROUND                 # 2,000: a round reporting threshold
SEEN_MIN = 8                                       # rd4's mechanism reading, kept as a reading
replay_verified_t = rpt3.replay_verified_t
budget_projection = rpt2.budget_projection


def _read(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


# -- the rule inputs and the readings' raw data --------------------------------------------------------------------------------------------------------------------


def rule_inputs5(a: s5.Archive5, rows: Sequence[Mapping[str, Any]], first_it: int, first_new_cell: int) -> Dict[str, Any]:
    """The registered counts of sd1 (rd3's rule inputs: the dilution counts, launch-capable cells created, bound violations of sd1's bursts, the top level's median L under v4)."""
    ins = dict(rpt3.rule_inputs3(a, first_it, first_new_cell))
    with a.as_v4():
        ins["top_level_median_L"] = a.stats()["top_level_median_L"]
    mi = rpt4.mechanism_inputs(a, rows, first_it, first_new_cell)
    assert mi["returns"] == ins["returns"], (mi, ins["returns"])
    ins["seen_ge_8_reading"] = mi["seen_ge_8"]
    ins["new_cells_reading"] = mi["new_cells"]
    return ins


def record_pace(record_candidate: Mapping[str, Any]) -> Dict[str, int]:
    """The record route's own arrival at each number of broken targets: the input tick of its l-th break, from its registered break table (read at runtime, never a literal)."""
    ticks = sorted(int(j) for j, _i in record_candidate["breaks"])
    return {str(n): t for n, t in enumerate(ticks, 1)}


def creation_shares5(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    return {s: {"dispatches": sum(1 for r in rows if r["created_in"] == s), "share": (sum(1 for r in rows if r["created_in"] == s) / n) if n else None} for s in SESSIONS}


def pace_readings(rows: Sequence[Mapping[str, Any]], pace: Mapping[str, int], lmin_open: Mapping[str, int]) -> Dict[str, Any]:
    """Per level: dispatches to cells ahead of the record pace (L < the record's arrival at that level), within one burst of the level's shortest arrival at the open, and at or below
    the round threshold."""
    out: Dict[str, Any] = {}
    levels = sorted({int(r["level"]) for r in rows})
    for lv in levels:
        sel = [r for r in rows if int(r["level"]) == lv]
        p = pace.get(str(lv))
        lm = lmin_open.get(str(lv))
        out[str(lv)] = {"dispatches": len(sel), "record_pace": p, "ahead_of_pace": sum(1 for r in sel if p is not None and int(r["L"]) < p),
                        "shortest_L_at_open": lm, "within_one_burst": sum(1 for r in sel if lm is not None and int(r["L"]) - lm <= mx.BURST_WORDS),
                        f"at_or_below_{ROUND_THRESHOLD}": sum(1 for r in sel if int(r["L"]) <= ROUND_THRESHOLD)}
    out["note"] = "the record pace is read from the record candidate's break table at runtime; one burst = 120 words; the round threshold is a reporting threshold; nothing here is a selection input"
    return out


def shortest_by_level(a: march.Archive) -> Dict[str, Any]:
    levels = sorted({c.level for c in a.cells})
    return {str(lv): {"cells": sum(1 for c in a.cells if c.level == lv), "min_L": min(c.L for c in a.cells if c.level == lv)} for lv in levels}


def left_floor_landings(a: march.Archive) -> Dict[str, Any]:
    lf = [c for c in a.cells if c.key[2] == mcell.RES_GROUNDED and c.key[4] in mcell.LEFT_FLOOR_LINES]
    return {"cells": len(lf), "min_L": min((c.L for c in lf), default=None), "by_level": {str(lv): sum(1 for c in lf if c.level == lv) for lv in sorted({c.level for c in lf})}}


def clear_event_distribution(ledger_path: Path, verified_cids: Sequence[int]) -> Dict[str, Any]:
    """Every clear event sd1 registered (the clear-kind candidates' registered clear ticks), marked verified or not."""
    p = Path(ledger_path)
    if not p.is_file():
        return {"events": [], "count": 0}
    led = _read(p)
    vs = set(int(x) for x in verified_cids)
    ev = []
    for c in led.get("candidates") or []:
        if c.get("kind") == "clear" and (c.get("first") or {}).get("clear") is not None:
            ev.append({"cid": int(c["cid"]), "iteration": int(c["iteration"]), "clear_tick": int(c["first"]["clear"]), "verified": int(c["cid"]) in vs})
    ev.sort(key=lambda e: (e["clear_tick"], e["cid"]))
    return {"events": ev, "count": len(ev), "verified": sum(1 for e in ev if e["verified"]), "fastest_registered": ev[0]["clear_tick"] if ev else None}


def analytic_masses(a: s5.Archive5, pace: Mapping[str, int], lmin_open: Mapping[str, int]) -> Dict[str, Any]:
    """The analytic selection mass at the open under v3 and v4 on the same archive: by level, and on the top level's cells ahead of the record pace, within one burst of the shortest
    arrival, and at or below the round threshold. A reading, never an input of the selection."""
    out: Dict[str, Any] = {}
    for mode in ("v3", "v4"):
        probs = a.probabilities(mode)
        by_level: Dict[str, float] = {}
        for cid, p in probs.items():
            lv = str(a.cells[cid].level)
            by_level[lv] = by_level.get(lv, 0.0) + p
        top = max((a.cells[cid].level for cid in probs), default=0)
        tp = pace.get(str(top))
        tl = lmin_open.get(str(top))
        cells_top = [a.cells[cid] for cid in probs if a.cells[cid].level == top]
        out[mode] = {"eligible_cells": len(probs), "by_level": by_level, "top_level": top,
                     "top_level_mass": {"ahead_of_pace": sum(probs[c.id] for c in cells_top if tp is not None and c.L < tp),
                                        "within_one_burst": sum(probs[c.id] for c in cells_top if tl is not None and c.L - tl <= mx.BURST_WORDS),
                                        f"at_or_below_{ROUND_THRESHOLD}": sum(probs[c.id] for c in cells_top if c.L <= ROUND_THRESHOLD)},
                     "mean_dispatch_L": sum(probs[cid] * a.cells[cid].L for cid in probs)}
    return out


# -- the full report ---------------------------------------------------------------------------------------------------------------------------------------------------


def full_report5(sd1_dir: Path, rd4_dir: Path, rd3_dir: Path, rd2_dir: Path, rd1_dir: Path, session: str = "sd1") -> Dict[str, Any]:
    """The registered diagnostics of a finished sd1 session beside rd4's, rd3's, rd2's and rd1's reference values (all recomputed from the archives)."""
    sd1_dir, rd4_dir, rd3_dir, rd2_dir, rd1_dir = Path(sd1_dir), Path(rd4_dir), Path(rd3_dir), Path(rd2_dir), Path(rd1_dir)
    sd = sd1_dir / "sessions" / session
    d, meta, rep = march.load_latest_verified(sd1_dir / "archive")
    if d is None:
        return {"ok": False, "reason": "no verified archive checkpoint", "checkpoints": rep}
    a, meta = s5.Archive5.read_dir(d)
    lines = str((meta.get("pin_tick0") or {}).get("lines"))
    base, bmeta = s5.Archive5.read_dir(sd1_dir / "base")                       # rd4's closing archive = the archive at sd1's open
    a3, _m3 = s2.Archive2.read_dir(rd3_dir / "archive")
    a2, _m2 = s2.Archive2.read_dir(rd2_dir / "archive")
    a1, _m1 = s2.Archive2.read_dir(rd1_dir / "archive")
    rng = a.iteration_ranges()
    first = int(a.sd1_first_iteration if a.sd1_first_iteration is not None else 0)
    n1, n2, n3, n4 = len(a1.cells), len(a2.cells), len(a3.cells), len(base.cells)
    rows_all: List[Dict[str, Any]] = []
    s5.rebuild5(a, lines, on_dispatch=rows_all.append)
    by = {s: [] for s in SESSIONS}
    for r in rows_all:
        by[a.session_of_iteration(int(r["it"]))].append(r)
    out: Dict[str, Any] = {"iteration_ranges": {k: list(v) for k, v in rng.items()}, "first_new_cell": {"rd2": n1, "rd3": n2, "rd4": n3, "sd1": n4},
                           "record_reference": a.record_reference, "margin": a.margin, "bound_L": a.bound_max_L()}
    out["sd1"] = rpt2.diagnostics(a, first, None, first_new_cell=n4)
    out["rd4_reference"] = rpt2.diagnostics(base, int(rng["rd4"][0] or 0), rng["rd4"][1], first_new_cell=n3)
    out["rd3_reference"] = rpt2.diagnostics(a3, int(rng["rd3"][0] or 0), rng["rd3"][1], first_new_cell=n2)
    out["rd2_reference"] = rpt2.diagnostics(a2, int(rng["rd2"][0] or 0), rng["rd2"][1], first_new_cell=n1)
    out["rd1_reference"] = rpt2.diagnostics(a1, 0, int(rng["rd2"][0] or 0) - 1, first_new_cell=0)
    out["new"] = {"sd1": rpt3.new_diagnostics(a, first), "rd4_reference": rpt3.new_diagnostics(base, int(rng["rd4"][0] or 0), rng["rd4"][1])}
    yields = rpt4.new_cells_by_iteration(a)
    rets = rpt4.returns_by_iteration(a, first)
    out["readings"] = {"frontier_returns": {s: rpt4.frontier_returns(by[s]) for s in SESSIONS},
                       "returns_by_start_cell_session": {s: creation_shares5(by[s]) for s in SESSIONS},
                       "seen_distribution": {"sd1": rpt4.seen_distribution(by["sd1"], yields, rets),
                                             **{s: rpt4.seen_distribution(by[s], yields, rpt4.returns_by_iteration(a, *(rng[s] if rng[s][0] is not None else (0, None)))) for s in ("rd4", "rd3", "rd2", "rd1")}}}
    mi = rpt4.mechanism_inputs(a, rows_all, first, n4)
    out["mechanism_readings"] = {"sd1": {"returns": mi["returns"], "seen_ge_8": mi["seen_ge_8"], "seen_ge_8_share": (mi["seen_ge_8"] / mi["returns"]) if mi["returns"] else None,
                                         "new_cells": mi["new_cells"], "new_cells_per_return": (mi["new_cells"] / mi["returns"]) if mi["returns"] else None, "note": "readings only; no check"},
                                 **{s: {"seen_ge_8_share": rpt4.seen_distribution(by[s])["seen_ge_8"]["share"], "dispatches": len(by[s])} for s in ("rd4", "rd3", "rd2", "rd1")}}
    # the record pace (the record candidate's own break table, read from rd4's registry) and the open's shortest arrivals: the section 6.4 readings
    try:
        pace = record_pace(cl5.record_candidate(rd4_dir, a.record_reference))
    except (ValueError, OSError, KeyError) as exc:
        pace = {}
        out["pace_error"] = f"{type(exc).__name__}: {exc}"
    lmin_open = {lv: v["min_L"] for lv, v in shortest_by_level(base).items()}
    out["pace"] = {"record_pace": pace, "sd1": pace_readings(by["sd1"], pace, lmin_open), "rd4_reference": pace_readings(by["rd4"], pace, lmin_open)}
    out["shortest_L_by_level"] = {"open": shortest_by_level(base), "close": shortest_by_level(a)}
    out["left_floor_landings"] = {"open": left_floor_landings(base), "close": left_floor_landings(a)}
    ver_p = sd / "verification.json"
    ver = _read(ver_p) if ver_p.is_file() else {}
    arm = ver.get("arm") or {}
    verified = arm.get("verified_clears") or []
    out["clears"] = {"registered": clear_event_distribution(sd / "ledger_T.json", [v["cid"] for v in verified]), "verified": verified, "best_verified": arm.get("best_verified"),
                     "tiers": arm.get("tiers"), "pool": ver.get("pools"), "replay_order": arm.get("replay_order"), "inherited_descriptive": ver.get("inherited_descriptive")}
    # D8: the overlays at the open and the close, E7's counts
    rows_close = s5.overlay_rows5(a, int(a.record_reference["completion_input_tick"]), int(a.margin))
    close_counts = s5.overlay_counts5(a, rows_close, int(a.record_reference["completion_input_tick"]), int(a.margin))
    open_p = sd1_dir / "derived" / "open_overlay.json"
    open_counts = (_read(open_p).get("open_overlay") or {}).get("counts") if open_p.is_file() else None
    base_d2 = bmeta.get("diag2") or {}
    own = {k: (len(v) if isinstance(v, list) else v) for k, v in a.diag2.items()}
    base_own = {k: (len(v) if isinstance(v, list) else v) for k, v in base_d2.items()}
    out["D8_overlays"] = {"open": open_counts, "close": {k: close_counts.get(k) for k in ("eligible_v1", "descent_among_v1_eligible", "bound_among_v1_eligible", "union", "eligible_v2", "eligible_v3",
                                                                                            "eligible_v4", "record_bound_cells", "record_bound_among_v3_eligible", "record_bound_by_level",
                                                                                            "record_bound_among_v3_eligible_by_level", "eligible_v4_by_level", "shortest_eligible_L_by_level")},
                          "E7": {"open": {k: (open_counts or {}).get(k) for k in ("record_bound_cells", "record_bound_among_v3_eligible", "record_bound_by_level")},
                                 "close": {k: close_counts.get(k) for k in ("record_bound_cells", "record_bound_among_v3_eligible", "record_bound_by_level")}},
                          "counters_cumulative": own, "counters_rd4_close": base_own, "counters_sd1": {k: own[k] - base_own.get(k, 0) for k in own},
                          "exact_ground_evidence_shadow": rpt2.exact_evidence_shadow(a)}
    # the analytic masses at the open (zero ticks; rd4's closing archive with sd1 begun as at the materialisation)
    a_open, _mo = s5.Archive5.read_dir(sd1_dir / "archive.prev") if (sd1_dir / "archive.prev" / "manifest.sha256").is_file() and not march.verify_manifest(sd1_dir / "archive.prev") else (None, None)
    if a_open is not None and a_open.sd1_first_iteration is not None and not [e for e in a_open.events if e["ev"] == "dispatch" and e["it"] >= first]:
        out["selection_at_the_open"] = analytic_masses(a_open, pace, lmin_open)
    else:
        try:
            tmp, _mt = s5.Archive5.read_dir(sd1_dir / "base")
            tmp.begin_sd1(first, lines, a.record_reference, int(a.margin))
            out["selection_at_the_open"] = analytic_masses(tmp, pace, lmin_open)
        except (s5.Select5Error, march.ArchiveError) as exc:
            out["selection_at_the_open"] = {"error": f"{type(exc).__name__}: {exc}"}

    def efficiency(arm_path: Path, returns: int, new_cells: int) -> Optional[Dict[str, Any]]:
        if not arm_path.is_file():
            return None
        arm_ = _read(arm_path)
        ticks, prefix = arm_.get("ticks", 0), arm_.get("prefix_ticks", 0)
        return {"ticks": ticks, "prefix_ticks": prefix, "prefix_share": (prefix / ticks) if ticks else None, "new_exploration_ticks": ticks - prefix, "returns": returns,
                "new_cells_per_return": new_cells / returns if returns else None, "ticks_per_s": arm_.get("ticks_per_s"), "wall_s": arm_.get("wall_s"), "select_s": arm_.get("select_s")}

    eff = efficiency(sd / "arm_T.json", out["sd1"]["returns"], len(a.cells) - n4)
    if eff is not None:
        out["D7_efficiency"] = eff
    out["D7_efficiency_references"] = {"rd4": efficiency(rd4_dir / "sessions" / "rd4" / "arm_T.json", out["rd4_reference"]["returns"], n4 - n3),
                                       "rd3": efficiency(rd3_dir / "sessions" / "rd3" / "arm_T.json", out["rd3_reference"]["returns"], n3 - n2),
                                       "rd2": efficiency(rd2_dir / "sessions" / "rd2" / "arm_T.json", out["rd2_reference"]["returns"], n2 - n1),
                                       "rd1": efficiency(rd1_dir / "sessions" / "rd1" / "arm_T.json", out["rd1_reference"]["returns"], n1 - 1)}
    out["upb_start_heights"] = {"sd1": rpt2.upb_start_heights(rpt3.bursts_in(a, first)), "rd4_reference": rpt2.upb_start_heights(rpt3.bursts_in(base, int(rng["rd4"][0] or 0), rng["rd4"][1]))}
    out["ground_runs"] = {"sd1": rpt2.ground_run_readings(rpt3.bursts_in(a, first)), "rd4_reference": rpt2.ground_run_readings(rpt3.bursts_in(base, int(rng["rd4"][0] or 0), rng["rd4"][1]))}
    out["rule_inputs"] = rule_inputs5(a, rows_all, first, n4)
    rule_p = sd / "rule.json"
    if rule_p.is_file():
        rr = _read(rule_p)
        out["decision"] = {k: rr.get(k) for k in ("outcome", "best_verified", "flags", "any_stop", "tiers")}
        out["line"] = rr.get("line")
        out["dilution"] = rr.get("dilution")
    return out


# -- read-only post-run verification -----------------------------------------------------------------------------------------------------------------------------------


def verify_run5(sd1_dir: Path, rd4_dir: Path, rd3_dir: Path, rd2_dir: Path, rd1_dir: Path, session: str = "sd1") -> Dict[str, Any]:
    """Independent of the driver: the sd1 archive verifies and its ledger rebuilds it exactly (five parts); sd1's files begin with rd4's closing bytes and so on down the chain; both overlay files
    hash to their record; every record in the tree carries the stamp; the rule record (the outcome, the best verified clear, the flags, the stops, the line) is recomputed from the archive,
    the replays and rd4's records; every route's actions hash to its metadata; the iteration rows add up to the arm's ticks; no pool replay is inexact unless the session is INVALID."""
    sd1_dir, rd4_dir, rd3_dir, rd2_dir, rd1_dir = Path(sd1_dir), Path(rd4_dir), Path(rd3_dir), Path(rd2_dir), Path(rd1_dir)
    sd = sd1_dir / "sessions" / session
    problems: List[str] = []
    info: Dict[str, Any] = {}
    d, meta, rep = march.load_latest_verified(sd1_dir / "archive")
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
    a, meta = s5.Archive5.read_dir(d)
    if a.sd1_first_iteration is None:
        problems.append("the archive has no sd1 session event")
        return {"ok": False, "problems": problems, "info": info}
    lines = (meta.get("pin_tick0") or {}).get("lines")
    first = int(a.sd1_first_iteration)
    t_rec, margin = int(a.record_reference["completion_input_tick"]), int(a.margin)
    close_p = sd / "close.json"
    if close_p.is_file():
        rec_manifest = (_read(close_p).get("archive") or {}).get("manifest")
        if rec_manifest != {n: march.sha256_file(Path(d) / n) for n in march.DATA_FILES}:
            problems.append("the archive's files differ from the manifest the close record stores")
    aud = s5.audit5(a, str(lines), collect_rows_from=first)
    info["audit"] = {k: aud[k] for k in ("ok", "cells", "bursts", "events")}
    if not aud["ok"]:
        problems += [f"audit: {p}" for p in aud["problems"][:5]]
    chain = r5.prefix_chain(rd1_dir / "archive", rd2_dir / "archive", rd3_dir / "archive", rd4_dir / "archive", d)
    info["prefix_chain"] = {"ok": chain["ok"]}
    if not chain["ok"]:
        problems += chain["problems"]
    ovr = sd1_dir / "derived" / "open_overlay.json"
    if ovr.is_file():
        o = _read(ovr)
        for key, name in (("open_overlay", "open_overlay.jsonl"), ("rd4_closing_overlay", "rd4_closing_overlay.jsonl")):
            p = sd1_dir / "derived" / name
            if not p.is_file() or march.sha256_file(p) != (o.get(key) or {}).get("sha256"):
                problems.append(f"the overlay file {name} differs from its recorded digest")
        if o.get("record_reference") != a.record_reference or int(o.get("margin", -1)) != margin:
            problems.append("the overlay record's reference or margin differs from the archive's session event")
    else:
        problems.append("no open overlay record")
    base_p = sd1_dir / "derived" / "base.json"
    if base_p.is_file():
        b = _read(base_p)
        ev = next((e for e in a.events if e["ev"] == "session" and e.get("name") == "sd1"), None)
        if b.get("session_event") != ev:
            problems.append("the base record's session event differs from the ledger's")
        if meta.get("created_utc") != b.get("utc"):
            problems.append("archive_meta.json's created_utc is not the materialisation time")
    else:
        problems.append("no base record")
    arts = art.audit_tree5(sd1_dir)
    info["artifacts"] = {k: arts[k] for k in ("ok", "files", "headers", "exempt")}
    if not arts["ok"]:
        problems += [f"artifacts: {x}" for x in arts["failures"][:6]]
    n_open = len(s5.Archive5.read_dir(sd1_dir / "base")[0].cells) if (sd1_dir / "base").is_dir() else 0
    rp = sd / "verification" / "replays.jsonl"
    _h, reps = art.read_jsonl5(rp)
    ver = _read(sd / "verification.json") if (sd / "verification.json").is_file() else {}
    pool_reps = [r for r in reps if not r.get("inherited")]
    led_p = sd / "ledger_T.json"
    led = _read(led_p) if led_p.is_file() else {}
    cands = {int(c["cid"]): c for c in (led.get("candidates") or [])}
    words = cl5.registry_words(sd1_dir, session) if (sd / "candidates_T.jsonl.gz").is_file() else {}
    verified: List[Dict[str, Any]] = []
    for r in pool_reps:
        c = cands.get(int(r["cid"]))
        if c is None:
            problems.append(f"replay of candidate {r['cid']}: no registry entry")
            continue
        if r.get("exact") and r.get("clear") and not r.get("exactness5"):
            facts = r["clear_facts"]
            w = words.get(int(c["cid"]), b"")
            if len(w) != int(c.get("length", len(w))):
                problems.append(f"replay of candidate {r['cid']}: the registry's words do not match its recorded length")
            verified.append({"cid": int(c["cid"]), "iteration": int(c["iteration"]), "kind": c["kind"], "completion_input_tick": int(facts["completion_input_tick"]),
                             "completion_time_passed": int(facts["completion_time_passed"]), "native_action_digest": mcell.words_digest(w), "words": len(w)})
    if rule is not None:
        if rule["rule_sha256"] != rule5.rule_digest():
            problems.append("the rule digest in the record differs from the current rule")
        ins = rule_inputs5(a, aud["dispatch_rows"], first, n_open)
        rd4_line = r5.rd4_line_status(rd4_dir)
        inh = ((ver.get("inherited_descriptive") or {}).get("records")) or []
        again = rule5.apply(invalid=rule["invalid"], incomplete=rule["incomplete"], verified_clears=verified if rule.get("claims_verified", True) else [], t_rec=t_rec,
                            t_rec_time_passed=int(a.record_reference["completion_time_passed"]), margin=margin, exploration_started=rule.get("exploration_started", True),
                            exploration_ticks=(rule.get("extra") or {}).get("exploration_ticks"), returns=ins["returns"], dispatches=ins["dispatches"], below_floor=ins["below_floor"],
                            fatal_returns=ins["fatal_returns"], launch_capable_created=ins["launch_capable_created"], bound_violations=ins["bound_violations"],
                            top_level_median_L=ins["top_level_median_L"], inherited_descriptive=inh, rd4_line=rd4_line, claims_verified=rule.get("claims_verified", True),
                            max_targets=rule.get("max_targets_verified"), t_claimed_online=rule.get("t_claimed_online"))
        for k in ("outcome", "flags", "any_stop", "progress_bar", "margin"):
            if again[k] != rule[k]:
                problems.append(f"rule record: {k} {rule[k]} differs from the recomputation {again[k]}")
        rb, ab = rule.get("best_verified"), again.get("best_verified")
        if (rb is None) != (ab is None) or (rb is not None and (rb["cid"], rb["completion_input_tick"], rb["completion_time_passed"]) != (ab["cid"], ab["completion_input_tick"], ab["completion_time_passed"])):
            problems.append(f"rule record: the best verified clear {rb} differs from the replays' {ab}")
        if [v["cid"] for v in rule.get("verified_clears") or []] != [v["cid"] for v in again["verified_clears"]]:
            problems.append("rule record: the verified clears differ from the exact clear replays")
        if again["line"]["status"] != rule["line"]["status"] or again["line"]["session_counts"] != rule["line"]["session_counts"] or again["line"]["rd_line"] != rule["line"]["rd_line"]:
            problems.append(f"rule record: the line status {rule['line']} differs from the recomputation {again['line']}")
        if rule["record_reference"] != {"completion_input_tick": t_rec, "completion_time_passed": int(a.record_reference["completion_time_passed"])}:
            problems.append("rule record: the record reference differs from the archive's session event")
        info["recomputed_outcome"] = again["outcome"]
        info["recomputed_line"] = again["line"]["status"]
        if rule.get("max_targets_verified") is not None and replay_verified_t(pool_reps) != rule["max_targets_verified"]:
            problems.append(f"rule record: max targets {rule['max_targets_verified']} differs from the maximum the exact replays hold ({replay_verified_t(pool_reps)})")
    for r in sorted((sd1_dir / "routes").glob("*")) if (sd1_dir / "routes").is_dir() else []:
        meta_p, act_p = r / "metadata.json", r / "actions.jsonl"
        if not (meta_p.is_file() and act_p.is_file()):
            problems.append(f"{r.name}: incomplete route directory")
            continue
        rows_ = [json.loads(ln) for ln in act_p.read_text(encoding="utf-8").splitlines() if ln.strip()]
        digest = mcell.native_digest([(x["buttons"], x["stick_x"], x["stick_y"], x["consumed_tick"]) for x in rows_])
        m = _read(meta_p)
        if digest != m["native_action_digest"] or [x["consumed_tick"] for x in rows_] != list(range(len(rows_))):
            problems.append(f"{r.name}: actions differ from the recorded digest or consumed ticks")
        if m.get("claim") == "clear" and (m.get("completion_clocks") or {}).get("completion_input_tick") != len(rows_):
            problems.append(f"{r.name}: a clear route whose completion_input_tick is not its word count")
    p, arm_p = sd / "iterations_T.jsonl", sd / "arm_T.json"
    if p.is_file() and arm_p.is_file():
        rows_ = art.rows_of(p)
        total = sum(int(x["ticks"]) for x in rows_ if "ticks" in x)
        if total != _read(arm_p)["ticks"]:
            problems.append(f"iteration rows add up to {total} ticks, the arm record says {_read(arm_p)['ticks']}")
        if any(x.get("tick0_equal") is False for x in rows_):
            problems.append("a row reports a tick-0 mismatch")
    if rule is not None and not rule["invalid"] and rp.is_file():
        bad = [r.get("label") for r in pool_reps if not r.get("exact") or r.get("exactness5")]
        if bad:
            problems.append(f"inexact pool replays in a session that is not INVALID: {bad[:4]}")
        info["replays"] = len(reps)
    return {"ok": not problems, "problems": problems, "info": info}
