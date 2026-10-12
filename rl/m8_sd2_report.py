"""M8-sd2: the registered diagnostics (reported only), the rule inputs and the read-only post-run verification (zero native ticks).

sd1's diagnostics (rl/m8_sd1_report.py: the record pace, the per-level readings, the left-floor landings, the clear-event distribution, the analytic masses; rd4's D1-D9 behind them,
all reused unchanged) are computed for sd2's dispatches beside sd1's reference column (its dispatches 13,886..17,556 on sd1's closing archive = sd2's base) and rd4's, rd3's, rd2's
and rd1's. The record pace is candidate 901's own break table, read at runtime. E7's counts are reported at BOTH bounds (sd1's reference and sd2's) at the open and at the close:
the same archive under the two references, a reading of what the moved reference excludes. Nothing here is read by the selection, the explorer, the cell key or the rule.
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
import m8_rd_select2 as s2  # noqa: E402
import m8_rd2_report as rpt2  # noqa: E402
import m8_rd3_report as rpt3  # noqa: E402
import m8_rd4_report as rpt4  # noqa: E402
import m8_sd1_report as rpt5  # noqa: E402
import m8_sd2_artifacts as art  # noqa: E402
import m8_sd2_claims as cl6  # noqa: E402
import m8_sd2_resume as r6  # noqa: E402
import m8_sd2_rule as rule6  # noqa: E402
import m8_sd2_select as s6  # noqa: E402

SESSIONS = s6.SESSIONS
ROUND_THRESHOLD = rule6.TIER_ROUND                 # 1,800: the round reporting threshold (sd1's was 2,000)
SEEN_MIN = rpt5.SEEN_MIN                           # 8: rd4's mechanism reading, kept as a reading
replay_verified_t = rpt3.replay_verified_t
budget_projection = rpt2.budget_projection
record_pace = rpt5.record_pace
shortest_by_level = rpt5.shortest_by_level
left_floor_landings = rpt5.left_floor_landings
clear_event_distribution = rpt5.clear_event_distribution
PREDECESSOR = r6.PREDECESSOR


def _read(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


# -- the rule inputs and the readings' raw data --------------------------------------------------------------------------------------------------------------------


def rule_inputs6(a: s6.Archive6, rows: Sequence[Mapping[str, Any]], first_it: int, first_new_cell: int) -> Dict[str, Any]:
    """The registered counts of sd2 (sd1's rule inputs: the dilution counts, launch-capable cells created, bound violations of sd2's bursts, the top level's median L under v4 at sd2's bound)."""
    return rpt5.rule_inputs5(a, rows, first_it, first_new_cell)


def creation_shares6(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    return {s: {"dispatches": sum(1 for r in rows if r["created_in"] == s), "share": (sum(1 for r in rows if r["created_in"] == s) / n) if n else None} for s in SESSIONS}


def pace_readings6(rows: Sequence[Mapping[str, Any]], pace: Mapping[str, int], lmin_open: Mapping[str, int]) -> Dict[str, Any]:
    """Per level: dispatches to cells ahead of the record pace (L < the record's arrival at that level), within one burst of the level's shortest arrival at the open, and at or below the round
    threshold (sd2's: 1,800)."""
    out: Dict[str, Any] = {}
    levels = sorted({int(r["level"]) for r in rows})
    for lv in levels:
        sel = [r for r in rows if int(r["level"]) == lv]
        p = pace.get(str(lv))
        lm = lmin_open.get(str(lv))
        out[str(lv)] = {"dispatches": len(sel), "record_pace": p, "ahead_of_pace": sum(1 for r in sel if p is not None and int(r["L"]) < p),
                        "shortest_L_at_open": lm, "within_one_burst": sum(1 for r in sel if lm is not None and int(r["L"]) - lm <= rpt5.mx.BURST_WORDS),
                        f"at_or_below_{ROUND_THRESHOLD}": sum(1 for r in sel if int(r["L"]) <= ROUND_THRESHOLD)}
    out["note"] = "the record pace is read from the record candidate's break table at runtime; one burst = 120 words; the round threshold is a reporting threshold; nothing here is a selection input"
    return out


def analytic_masses6(a: s6.Archive6, pace: Mapping[str, int], lmin_open: Mapping[str, int]) -> Dict[str, Any]:
    """The analytic selection mass at the open under v3, v4 at sd1's bound and v4 at sd2's bound on the same archive: by level, and on the top level's cells ahead of the record pace, within one
    burst of the shortest arrival, and at or below the round threshold. A reading, never an input of the selection."""
    out: Dict[str, Any] = {}
    modes = (("v3", lambda: a.probabilities("v3")), ("v4_previous_bound", lambda: a.probabilities_at_bound(a.sd1_bound_max_L())), ("v4", lambda: a.probabilities("v4")))
    for name, fn in modes:
        probs = fn()
        by_level: Dict[str, float] = {}
        for cid, p in probs.items():
            lv = str(a.cells[cid].level)
            by_level[lv] = by_level.get(lv, 0.0) + p
        top = max((a.cells[cid].level for cid in probs), default=0)
        tp = pace.get(str(top))
        tl = lmin_open.get(str(top))
        cells_top = [a.cells[cid] for cid in probs if a.cells[cid].level == top]
        out[name] = {"eligible_cells": len(probs), "by_level": by_level, "top_level": top,
                     "top_level_mass": {"ahead_of_pace": sum(probs[c.id] for c in cells_top if tp is not None and c.L < tp),
                                        "within_one_burst": sum(probs[c.id] for c in cells_top if tl is not None and c.L - tl <= rpt5.mx.BURST_WORDS),
                                        f"at_or_below_{ROUND_THRESHOLD}": sum(probs[c.id] for c in cells_top if c.L <= ROUND_THRESHOLD)},
                     "mean_dispatch_L": sum(probs[cid] * a.cells[cid].L for cid in probs)}
    out["bounds"] = {"v4_previous_bound": a.sd1_bound_max_L(), "v4": a.bound_max_L()}
    return out


def e7_counts(a: s6.Archive6, t_rec: int, margin: int) -> Dict[str, Any]:
    rows = s6.overlay_rows6(a, t_rec, margin)
    c = s6.overlay_counts6(a, rows, t_rec, margin)
    return {k: c.get(k) for k in ("bound_L", "record_reference_completion_input_tick", "eligible_v3", "eligible_v4", "record_bound_cells", "record_bound_among_v3_eligible", "record_bound_by_level",
                                  "record_bound_among_v3_eligible_by_level", "eligible_v4_by_level", "shortest_eligible_L_by_level")}


# -- the full report ---------------------------------------------------------------------------------------------------------------------------------------------------


def full_report6(sd2_dir: Path, sd1_dir: Path, rd4_dir: Path, rd3_dir: Path, rd2_dir: Path, rd1_dir: Path, session: str = "sd2") -> Dict[str, Any]:
    """The registered diagnostics of a finished sd2 session beside sd1's, rd4's, rd3's, rd2's and rd1's reference values (all recomputed from the archives)."""
    sd2_dir, sd1_dir, rd4_dir, rd3_dir, rd2_dir, rd1_dir = Path(sd2_dir), Path(sd1_dir), Path(rd4_dir), Path(rd3_dir), Path(rd2_dir), Path(rd1_dir)
    sd = sd2_dir / "sessions" / session
    d, meta, rep = march.load_latest_verified(sd2_dir / "archive")
    if d is None:
        return {"ok": False, "reason": "no verified archive checkpoint", "checkpoints": rep}
    a, meta = s6.Archive6.read_dir(d)
    lines = str((meta.get("pin_tick0") or {}).get("lines"))
    base, bmeta = s6.Archive6.read_dir(sd2_dir / "base")                       # sd1's closing archive = the archive at sd2's open
    a4, _m4 = s2.Archive2.read_dir(rd4_dir / "archive")
    a3, _m3 = s2.Archive2.read_dir(rd3_dir / "archive")
    a2, _m2 = s2.Archive2.read_dir(rd2_dir / "archive")
    a1, _m1 = s2.Archive2.read_dir(rd1_dir / "archive")
    rng = a.iteration_ranges()
    first = int(a.sd2_first_iteration if a.sd2_first_iteration is not None else 0)
    n1, n2, n3, n4, n5 = len(a1.cells), len(a2.cells), len(a3.cells), len(a4.cells), len(base.cells)
    rows_all: List[Dict[str, Any]] = []
    s6.rebuild6(a, lines, on_dispatch=rows_all.append)
    by: Dict[str, List[Dict[str, Any]]] = {s: [] for s in SESSIONS}
    for r in rows_all:
        by[a.session_of_iteration(int(r["it"]))].append(r)
    out: Dict[str, Any] = {"iteration_ranges": {k: list(v) for k, v in rng.items()}, "first_new_cell": {"rd2": n1, "rd3": n2, "rd4": n3, "sd1": n4, "sd2": n5},
                           "record_reference": a.record_reference, "previous_record_reference": a.sd1_record_reference, "margin": a.margin, "bound_L": a.bound_max_L(), "previous_bound_L": a.sd1_bound_max_L()}
    out["sd2"] = rpt2.diagnostics(a, first, None, first_new_cell=n5)
    out["sd1_reference"] = rpt2.diagnostics(base, int(rng["sd1"][0] or 0), rng["sd1"][1], first_new_cell=n4)
    out["rd4_reference"] = rpt2.diagnostics(a4, int(rng["rd4"][0] or 0), rng["rd4"][1], first_new_cell=n3)
    out["rd3_reference"] = rpt2.diagnostics(a3, int(rng["rd3"][0] or 0), rng["rd3"][1], first_new_cell=n2)
    out["rd2_reference"] = rpt2.diagnostics(a2, int(rng["rd2"][0] or 0), rng["rd2"][1], first_new_cell=n1)
    out["rd1_reference"] = rpt2.diagnostics(a1, 0, int(rng["rd2"][0] or 0) - 1, first_new_cell=0)
    out["new"] = {"sd2": rpt3.new_diagnostics(a, first), "sd1_reference": rpt3.new_diagnostics(base, int(rng["sd1"][0] or 0), rng["sd1"][1])}
    yields = rpt4.new_cells_by_iteration(a)
    rets = rpt4.returns_by_iteration(a, first)
    out["readings"] = {"frontier_returns": {s: rpt4.frontier_returns(by[s]) for s in SESSIONS},
                       "returns_by_start_cell_session": {s: creation_shares6(by[s]) for s in SESSIONS},
                       "seen_distribution": {"sd2": rpt4.seen_distribution(by["sd2"], yields, rets),
                                             **{s: rpt4.seen_distribution(by[s], yields, rpt4.returns_by_iteration(a, *(rng[s] if rng[s][0] is not None else (0, None)))) for s in ("sd1", "rd4", "rd3", "rd2", "rd1")}}}
    mi = rpt4.mechanism_inputs(a, rows_all, first, n5)
    out["mechanism_readings"] = {"sd2": {"returns": mi["returns"], "seen_ge_8": mi["seen_ge_8"], "seen_ge_8_share": (mi["seen_ge_8"] / mi["returns"]) if mi["returns"] else None,
                                         "new_cells": mi["new_cells"], "new_cells_per_return": (mi["new_cells"] / mi["returns"]) if mi["returns"] else None, "note": "readings only; no check"},
                                 **{s: {"seen_ge_8_share": rpt4.seen_distribution(by[s])["seen_ge_8"]["share"], "dispatches": len(by[s])} for s in ("sd1", "rd4", "rd3", "rd2", "rd1")}}
    # the record pace (the record candidate's own break table, read from sd1's registry) and the open's shortest arrivals
    try:
        pace = record_pace(cl6.record_candidate6(sd1_dir, a.record_reference))
    except (ValueError, OSError, KeyError) as exc:
        pace = {}
        out["pace_error"] = f"{type(exc).__name__}: {exc}"
    lmin_open = {lv: v["min_L"] for lv, v in shortest_by_level(base).items()}
    out["pace"] = {"record_pace": pace, "sd2": pace_readings6(by["sd2"], pace, lmin_open), "sd1_reference": pace_readings6(by["sd1"], pace, lmin_open), "rd4_reference": pace_readings6(by["rd4"], pace, lmin_open)}
    out["shortest_L_by_level"] = {"open": shortest_by_level(base), "close": shortest_by_level(a)}
    out["left_floor_landings"] = {"open": left_floor_landings(base), "close": left_floor_landings(a)}
    ver_p = sd / "verification.json"
    ver = _read(ver_p) if ver_p.is_file() else {}
    arm = ver.get("arm") or {}
    verified = arm.get("verified_clears") or []
    out["clears"] = {"registered": clear_event_distribution(sd / "ledger_T.json", [v["cid"] for v in verified]), "verified": verified, "best_verified": arm.get("best_verified"),
                     "tiers": arm.get("tiers"), "pool": ver.get("pools"), "replay_order": arm.get("replay_order"), "inherited_descriptive": ver.get("inherited_descriptive")}
    # D8: the overlays at the open and the close, E7's counts at both bounds
    t_new, m = int(a.record_reference["completion_input_tick"]), int(a.margin)
    t_prev, m_prev = int(a.sd1_record_reference["completion_input_tick"]), int(a.sd1_margin)
    rows_close = s6.overlay_rows6(a, t_new, m)
    close_counts = s6.overlay_counts6(a, rows_close, t_new, m)
    open_p = sd2_dir / "derived" / "open_overlay.json"
    open_rec = _read(open_p) if open_p.is_file() else {}
    open_counts = (open_rec.get("open_overlay") or {}).get("counts")
    prev_open_counts = (open_rec.get("sd1_closing_overlay") or {}).get("counts")
    base_d2 = bmeta.get("diag2") or {}
    own = {k: (len(v) if isinstance(v, list) else v) for k, v in a.diag2.items()}
    base_own = {k: (len(v) if isinstance(v, list) else v) for k, v in base_d2.items()}
    keys = ("eligible_v1", "descent_among_v1_eligible", "bound_among_v1_eligible", "union", "eligible_v2", "eligible_v3", "eligible_v4", "record_bound_cells", "record_bound_among_v3_eligible",
            "record_bound_by_level", "record_bound_among_v3_eligible_by_level", "eligible_v4_by_level", "shortest_eligible_L_by_level")
    out["D8_overlays"] = {"open": open_counts, "open_previous_bound": prev_open_counts, "close": {k: close_counts.get(k) for k in keys},
                          "E7": {"open": {"at_sd2_bound": {k: (open_counts or {}).get(k) for k in ("bound_L", "record_bound_cells", "record_bound_among_v3_eligible", "record_bound_by_level")},
                                          "at_sd1_bound": {k: (prev_open_counts or {}).get(k) for k in ("bound_L", "record_bound_cells", "record_bound_among_v3_eligible", "record_bound_by_level")}},
                                 "close": {"at_sd2_bound": e7_counts(a, t_new, m), "at_sd1_bound": e7_counts(a, t_prev, m_prev)}},
                          "counters_cumulative": own, "counters_sd1_close": base_own, "counters_sd2": {k: own[k] - base_own.get(k, 0) for k in own},
                          "exact_ground_evidence_shadow": rpt2.exact_evidence_shadow(a)}
    # the analytic masses at the open (zero ticks; sd1's closing archive with sd2 begun as at the materialisation)
    a_open: Optional[s6.Archive6] = None
    if (sd2_dir / "archive.prev" / "manifest.sha256").is_file() and not march.verify_manifest(sd2_dir / "archive.prev"):
        a_open, _mo = s6.Archive6.read_dir(sd2_dir / "archive.prev")
    if a_open is not None and a_open.sd2_first_iteration is not None and not [e for e in a_open.events if e["ev"] == "dispatch" and e["it"] >= first]:
        out["selection_at_the_open"] = analytic_masses6(a_open, pace, lmin_open)
    else:
        try:
            tmp, _mt = s6.Archive6.read_dir(sd2_dir / "base")
            tmp.begin_sd2(first, lines, a.record_reference, int(a.margin))
            out["selection_at_the_open"] = analytic_masses6(tmp, pace, lmin_open)
        except (s6.Select6Error, march.ArchiveError) as exc:
            out["selection_at_the_open"] = {"error": f"{type(exc).__name__}: {exc}"}

    def efficiency(arm_path: Path, returns: int, new_cells: int) -> Optional[Dict[str, Any]]:
        if not arm_path.is_file():
            return None
        arm_ = _read(arm_path)
        ticks, prefix = arm_.get("ticks", 0), arm_.get("prefix_ticks", 0)
        return {"ticks": ticks, "prefix_ticks": prefix, "prefix_share": (prefix / ticks) if ticks else None, "new_exploration_ticks": ticks - prefix, "returns": returns,
                "new_cells_per_return": new_cells / returns if returns else None, "ticks_per_s": arm_.get("ticks_per_s"), "wall_s": arm_.get("wall_s"), "select_s": arm_.get("select_s")}

    eff = efficiency(sd / "arm_T.json", out["sd2"]["returns"], len(a.cells) - n5)
    if eff is not None:
        out["D7_efficiency"] = eff
    out["D7_efficiency_references"] = {"sd1": efficiency(sd1_dir / "sessions" / PREDECESSOR / "arm_T.json", out["sd1_reference"]["returns"], n5 - n4),
                                       "rd4": efficiency(rd4_dir / "sessions" / "rd4" / "arm_T.json", out["rd4_reference"]["returns"], n4 - n3),
                                       "rd3": efficiency(rd3_dir / "sessions" / "rd3" / "arm_T.json", out["rd3_reference"]["returns"], n3 - n2),
                                       "rd2": efficiency(rd2_dir / "sessions" / "rd2" / "arm_T.json", out["rd2_reference"]["returns"], n2 - n1),
                                       "rd1": efficiency(rd1_dir / "sessions" / "rd1" / "arm_T.json", out["rd1_reference"]["returns"], n1 - 1)}
    out["upb_start_heights"] = {"sd2": rpt2.upb_start_heights(rpt3.bursts_in(a, first)), "sd1_reference": rpt2.upb_start_heights(rpt3.bursts_in(base, int(rng["sd1"][0] or 0), rng["sd1"][1]))}
    out["ground_runs"] = {"sd2": rpt2.ground_run_readings(rpt3.bursts_in(a, first)), "sd1_reference": rpt2.ground_run_readings(rpt3.bursts_in(base, int(rng["sd1"][0] or 0), rng["sd1"][1]))}
    out["rule_inputs"] = rule_inputs6(a, rows_all, first, n5)
    rule_p = sd / "rule.json"
    if rule_p.is_file():
        rr = _read(rule_p)
        out["decision"] = {k: rr.get(k) for k in ("outcome", "best_verified", "flags", "any_stop", "tiers")}
        out["line"] = rr.get("line")
        out["dilution"] = rr.get("dilution")
    return out


# -- read-only post-run verification -----------------------------------------------------------------------------------------------------------------------------------


def verify_run6(sd2_dir: Path, sd1_dir: Path, rd4_dir: Path, rd3_dir: Path, rd2_dir: Path, rd1_dir: Path, session: str = "sd2") -> Dict[str, Any]:
    """Independent of the driver: the sd2 archive verifies and its ledger rebuilds it exactly (six parts); sd2's files begin with sd1's closing bytes and so on down the chain; both overlay files
    hash to their record; every record in the tree carries the stamp; the rule record (the outcome, the best verified clear, the flags, the stops, the line) is recomputed from the archive,
    the replays and sd1's records; every route's actions hash to its metadata; the iteration rows add up to the arm's ticks; no pool replay is inexact unless the session is INVALID."""
    sd2_dir, sd1_dir, rd4_dir, rd3_dir, rd2_dir, rd1_dir = Path(sd2_dir), Path(sd1_dir), Path(rd4_dir), Path(rd3_dir), Path(rd2_dir), Path(rd1_dir)
    sd = sd2_dir / "sessions" / session
    problems: List[str] = []
    info: Dict[str, Any] = {}
    d, meta, rep = march.load_latest_verified(sd2_dir / "archive")
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
    a, meta = s6.Archive6.read_dir(d)
    if a.sd2_first_iteration is None:
        problems.append("the archive has no sd2 session event")
        return {"ok": False, "problems": problems, "info": info}
    lines = (meta.get("pin_tick0") or {}).get("lines")
    first = int(a.sd2_first_iteration)
    t_rec, margin = int(a.record_reference["completion_input_tick"]), int(a.margin)
    close_p = sd / "close.json"
    if close_p.is_file():
        rec_manifest = (_read(close_p).get("archive") or {}).get("manifest")
        if rec_manifest != {n: march.sha256_file(Path(d) / n) for n in march.DATA_FILES}:
            problems.append("the archive's files differ from the manifest the close record stores")
    aud = s6.audit6(a, str(lines), collect_rows_from=first)
    info["audit"] = {k: aud[k] for k in ("ok", "cells", "bursts", "events")}
    if not aud["ok"]:
        problems += [f"audit: {p}" for p in aud["problems"][:5]]
    chain = r6.prefix_chain6(rd1_dir / "archive", rd2_dir / "archive", rd3_dir / "archive", rd4_dir / "archive", sd1_dir / "archive", d)
    info["prefix_chain"] = {"ok": chain["ok"]}
    if not chain["ok"]:
        problems += chain["problems"]
    ovr = sd2_dir / "derived" / "open_overlay.json"
    if ovr.is_file():
        o = _read(ovr)
        for key, name in (("open_overlay", "open_overlay.jsonl"), ("sd1_closing_overlay", "sd1_closing_overlay.jsonl")):
            p = sd2_dir / "derived" / name
            if not p.is_file() or march.sha256_file(p) != (o.get(key) or {}).get("sha256"):
                problems.append(f"the overlay file {name} differs from its recorded digest")
        if o.get("record_reference") != a.record_reference or int(o.get("margin", -1)) != margin or o.get("previous_record_reference") != a.sd1_record_reference:
            problems.append("the overlay record's references or margin differ from the archive's session events")
    else:
        problems.append("no open overlay record")
    base_p = sd2_dir / "derived" / "base.json"
    if base_p.is_file():
        b = _read(base_p)
        ev = next((e for e in a.events if e["ev"] == "session" and e.get("name") == s6.SESSION_NAME), None)
        if b.get("session_event") != ev:
            problems.append("the base record's session event differs from the ledger's")
        if meta.get("created_utc") != b.get("utc"):
            problems.append("archive_meta.json's created_utc is not the materialisation time")
    else:
        problems.append("no base record")
    arts = art.audit_tree6(sd2_dir)
    info["artifacts"] = {k: arts[k] for k in ("ok", "files", "headers", "exempt")}
    if not arts["ok"]:
        problems += [f"artifacts: {x}" for x in arts["failures"][:6]]
    n_open = len(s6.Archive6.read_dir(sd2_dir / "base")[0].cells) if (sd2_dir / "base").is_dir() else 0
    rp = sd / "verification" / "replays.jsonl"
    _h, reps = art.read_jsonl5(rp)
    ver = _read(sd / "verification.json") if (sd / "verification.json").is_file() else {}
    pool_reps = [r for r in reps if not r.get("inherited")]
    led_p = sd / "ledger_T.json"
    led = _read(led_p) if led_p.is_file() else {}
    cands = {int(c["cid"]): c for c in (led.get("candidates") or [])}
    words = cl6.registry_words(sd2_dir, session) if (sd / "candidates_T.jsonl.gz").is_file() else {}
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
        if rule["rule_sha256"] != rule6.rule_digest():
            problems.append("the rule digest in the record differs from the current rule")
        ins = rule_inputs6(a, aud["dispatch_rows"], first, n_open)
        sd1_line = r6.sd1_line_status(sd1_dir)
        inh = ((ver.get("inherited_descriptive") or {}).get("records")) or []
        again = rule6.apply(invalid=rule["invalid"], incomplete=rule["incomplete"], verified_clears=verified if rule.get("claims_verified", True) else [], t_rec=t_rec,
                            t_rec_time_passed=int(a.record_reference["completion_time_passed"]), margin=margin, exploration_started=rule.get("exploration_started", True),
                            exploration_ticks=(rule.get("extra") or {}).get("exploration_ticks"), returns=ins["returns"], dispatches=ins["dispatches"], below_floor=ins["below_floor"],
                            fatal_returns=ins["fatal_returns"], launch_capable_created=ins["launch_capable_created"], bound_violations=ins["bound_violations"],
                            top_level_median_L=ins["top_level_median_L"], inherited_descriptive=inh, sd1_line=sd1_line, claims_verified=rule.get("claims_verified", True),
                            max_targets=rule.get("max_targets_verified"), t_claimed_online=rule.get("t_claimed_online"))
        for k in ("outcome", "flags", "any_stop", "progress_bar", "margin"):
            if again[k] != rule[k]:
                problems.append(f"rule record: {k} {rule[k]} differs from the recomputation {again[k]}")
        rb, ab = rule.get("best_verified"), again.get("best_verified")
        if (rb is None) != (ab is None) or (rb is not None and (rb["cid"], rb["completion_input_tick"], rb["completion_time_passed"]) != (ab["cid"], ab["completion_input_tick"], ab["completion_time_passed"])):
            problems.append(f"rule record: the best verified clear {rb} differs from the replays' {ab}")
        if [v["cid"] for v in rule.get("verified_clears") or []] != [v["cid"] for v in again["verified_clears"]]:
            problems.append("rule record: the verified clears differ from the exact clear replays")
        if again["line"]["status"] != rule["line"]["status"] or again["line"]["session_counts"] != rule["line"]["session_counts"] or again["line"]["rd_line"] != rule["line"]["rd_line"] \
                or again["line"]["sd_line"] != rule["line"]["sd_line"]:
            problems.append(f"rule record: the line status {rule['line']} differs from the recomputation {again['line']}")
        if rule["record_reference"] != {"completion_input_tick": t_rec, "completion_time_passed": int(a.record_reference["completion_time_passed"])}:
            problems.append("rule record: the record reference differs from the archive's session event")
        info["recomputed_outcome"] = again["outcome"]
        info["recomputed_line"] = again["line"]["status"]
        if rule.get("max_targets_verified") is not None and replay_verified_t(pool_reps) != rule["max_targets_verified"]:
            problems.append(f"rule record: max targets {rule['max_targets_verified']} differs from the maximum the exact replays hold ({replay_verified_t(pool_reps)})")
    for r in sorted((sd2_dir / "routes").glob("*")) if (sd2_dir / "routes").is_dir() else []:
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
