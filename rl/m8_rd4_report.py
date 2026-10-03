"""M8-rd4: the registered diagnostics, the mechanism check's inputs, the rule inputs and the read-only post-run verification (zero native ticks).

The nine diagnostics D1-D9 of rd2 (rl/m8_rd2_report.py, reused unchanged) and rd3's new readings (rl/m8_rd3_report.py, reused unchanged) are computed for rd4's dispatches beside THREE reference
columns, all recomputed by the same functions from the archives: rd3 (its dispatches 6,212..10,405, evaluated on rd3's closing archive = rd4's base), rd2 (2,175..6,211, on rd2's closing
archive) and rd1 (0..2,174, on rd1's archive). The additional readings of decision 9, all REPORTED ONLY:

    returns to left-of-wall cells and to wall-top cells     dispatches whose start cell stands left of x = -2,100 (and -1,650 / -1,800) or on floor line 0
    the share of returns by start-cell session of creation  rd1 / rd2 / rd3 / rd4
    the seen-count distribution of the start cells          at dispatch, with the new cells per return of each class
    closest approach to the left floor                      rd3's reading (floor line 3)

The mechanism check (decision 7) reads, from the ledger replay (the audit's own rebuild), each rd4 dispatch's start cell's `seen` AT DISPATCH. Nothing here is read by the selection, the explorer, the
cell key or the rule except those two counts.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import m8_rd_archive as march  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_select2 as s2  # noqa: E402
import m8_rd2_report as rpt2  # noqa: E402
import m8_rd2_rule as rule2  # noqa: E402
import m8_rd3_report as rpt3  # noqa: E402
import m8_rd4_rule as rule4  # noqa: E402
import m8_rd4_select as s4  # noqa: E402

I_X, I_Y = mcell.I_X, mcell.I_Y
SEEN_BUCKETS = ((0, 1), (2, 3), (4, 7), (8, 15), (16, 31), (32, 63), (64, None))
SESSIONS = ("rd1", "rd2", "rd3", "rd4")


def _read(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


replay_verified_m = rpt3.replay_verified_m
replay_verified_t = rpt3.replay_verified_t
budget_projection = rpt2.budget_projection


# -- the mechanism check's inputs ---------------------------------------------------------------------------------------------------------------


def returns_by_iteration(a: march.Archive, it_lo: int, it_hi: Optional[int] = None) -> Dict[int, int]:
    """The ingested jobs (returns) of an iteration range: iteration -> burst id (-1 for a job cut inside its prefix)."""
    return {int(r["it"]): int(r["burst"]) for r in rpt2.returns_of(a, it_lo, it_hi)}


def new_cells_by_iteration(a: march.Archive) -> Dict[int, int]:
    """The cells each iteration's burst created (NEW wins)."""
    return {b.iteration: sum(1 for w in b.wins if int(w["a"]) == march.ACTION_NEW) for b in a.bursts}


def mechanism_inputs(a: march.Archive, rows: Sequence[Mapping[str, Any]], first_it: int, first_new_cell: int) -> Dict[str, int]:
    """returns = rd4's ingested jobs; seen_ge_8 = those whose start cell had been seen 8 or more times AT DISPATCH; new_cells = cells created from the open archive's cell count on."""
    rets = returns_by_iteration(a, first_it)
    seen8 = sum(1 for r in rows if int(r["it"]) in rets and int(r["it"]) >= first_it and int(r["seen"]) >= rule4.SEEN_MIN)
    return {"returns": len(rets), "seen_ge_8": seen8, "new_cells": len(a.cells) - int(first_new_cell)}


def rule_inputs4(a: s4.Archive4, rows: Sequence[Mapping[str, Any]], first_it: int, first_new_cell: int) -> Dict[str, Any]:
    """The registered counts of rd4: rd3's rule inputs (dilution counts, launch-capable cells created, bound violations of rd4's bursts, the top level's median L) and the mechanism check's."""
    ins = dict(rpt3.rule_inputs3(a, first_it, first_new_cell))
    mi = mechanism_inputs(a, rows, first_it, first_new_cell)
    assert mi["returns"] == ins["returns"], (mi, ins["returns"])
    ins.update(seen_ge_8=mi["seen_ge_8"], new_cells=mi["new_cells"])
    return ins


# -- the additional readings of decision 9 ------------------------------------------------------------------------------------------------------------


def bucket_name(lo: int, hi: Optional[int]) -> str:
    return f"{lo}+" if hi is None else (f"{lo}" if lo == hi else f"{lo}-{hi}")


def seen_distribution(rows: Sequence[Mapping[str, Any]], yields: Optional[Mapping[int, int]] = None, returned: Optional[Mapping[int, int]] = None) -> Dict[str, Any]:
    """The seen-count distribution of the start cells at dispatch (and, where the ledger gives it, the new cells per return of each class)."""
    out: Dict[str, Any] = {}
    n = len(rows)
    for lo, hi in SEEN_BUCKETS:
        sel = [r for r in rows if int(r["seen"]) >= lo and (hi is None or int(r["seen"]) <= hi)]
        rec: Dict[str, Any] = {"dispatches": len(sel), "share": (len(sel) / n) if n else None}
        if yields is not None and returned is not None:
            ret = [r for r in sel if int(r["it"]) in returned]
            rec["returns"] = len(ret)
            rec["new_cells_per_return"] = (sum(yields.get(int(r["it"]), 0) for r in ret) / len(ret)) if ret else None
        out[bucket_name(lo, hi)] = rec
    ge8 = sum(1 for r in rows if int(r["seen"]) >= rule4.SEEN_MIN)
    out["seen_ge_8"] = {"dispatches": ge8, "share": (ge8 / n) if n else None}
    return out


def creation_shares(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """The share of returns by the session in which the start cell was created."""
    n = len(rows)
    return {s: {"dispatches": sum(1 for r in rows if r["created_in"] == s), "share": (sum(1 for r in rows if r["created_in"] == s) / n) if n else None} for s in SESSIONS}


def frontier_returns(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Returns to left-of-wall cells (the registered boundary x < -2,100, also x < -1,800 and x < -1,650) and to wall-top cells (grounded on floor line 0), by the start cell's stored position."""
    n = len(rows)

    def cnt(pred: Any) -> Dict[str, Any]:
        k = sum(1 for r in rows if pred(r))
        return {"dispatches": k, "share": (k / n) if n else None}

    return {"left_of_wall_x_lt_-2100": cnt(lambda r: r["x"] < -2100.0), "left_of_wall_x_lt_-1800": cnt(lambda r: r["x"] < -1800.0), "left_of_wall_x_lt_-1650": cnt(lambda r: r["x"] < -1650.0),
            "wall_top_cells": cnt(lambda r: r["res"] == mcell.RES_GROUNDED and r["floor"] == mcell.L0_FLOOR_LINE), "dispatches": n}


def session_rows(rows_all: Sequence[Mapping[str, Any]], a: s4.Archive4) -> Dict[str, List[Mapping[str, Any]]]:
    out: Dict[str, List[Mapping[str, Any]]] = {s: [] for s in SESSIONS}
    for r in rows_all:
        out[a.session_of_iteration(int(r["it"]))].append(r)
    return out


def ledger_rows(a: s2.Archive2, lines_sha256: str) -> List[Dict[str, Any]]:
    """Every dispatch's row (the start cell's counters at dispatch) from one rebuild of the ledger (zero native ticks)."""
    rows: List[Dict[str, Any]] = []
    s4.rebuild4(a, lines_sha256, on_dispatch=rows.append)
    return rows


def open_selection_probabilities4(a: s4.Archive4) -> Dict[str, Any]:
    """The analytic selection probability of the wall-top cells at the open (the archive as materialised, before any rd4 dispatch) under v2 (the rule rd3 ran) and under v3 (the rule rd4 runs)."""
    out: Dict[str, Any] = {}
    wt = rpt3.wall_top_cells(a)
    for mode in ("v2", "v3"):
        probs = a.probabilities(mode)
        per = {str(c.id): {"eligible": bool(a.eligible(c)), "probability": probs.get(c.id, 0.0), "level": c.level, "L": c.L, "chosen": c.chosen, "seen": c.seen} for c in wt}
        out[mode] = {"wall_top_cells": len(wt), "eligible": sum(1 for v in per.values() if v["eligible"]), "total_probability": sum(v["probability"] for v in per.values()), "per_cell": per,
                     "eligible_cells": len(probs)}
    return out


# -- the full report ---------------------------------------------------------------------------------------------------------------------------------


def full_report4(rd4_dir: Path, rd3_dir: Path, rd2_dir: Path, rd1_dir: Path, session: str = "rd4") -> Dict[str, Any]:
    """The registered diagnostics of a finished rd4 session beside rd3's, rd2's and rd1's reference values (all recomputed from the archives)."""
    rd4_dir, rd3_dir, rd2_dir, rd1_dir = Path(rd4_dir), Path(rd3_dir), Path(rd2_dir), Path(rd1_dir)
    sd = rd4_dir / "sessions" / session
    d, meta, rep = march.load_latest_verified(rd4_dir / "archive")
    if d is None:
        return {"ok": False, "reason": "no verified archive checkpoint", "checkpoints": rep}
    a, meta = s4.Archive4.read_dir(d)
    lines = str((meta.get("pin_tick0") or {}).get("lines"))
    base, bmeta = s4.Archive4.read_dir(rd4_dir / "base")                    # rd3's closing archive = the archive at rd4's open
    a2, _m2 = s2.Archive2.read_dir(rd2_dir / "archive")
    a1, _m1 = s2.Archive2.read_dir(rd1_dir / "archive")
    rng = a.iteration_ranges()
    r4_first = int(a.rd4_first_iteration if a.rd4_first_iteration is not None else 0)
    n_rd1, n_rd2, n_rd3 = len(a1.cells), len(a2.cells), len(base.cells)
    rd2_lo, rd2_hi = rng["rd2"]
    rd3_lo, rd3_hi = rng["rd3"]
    rows_all = ledger_rows(a, lines)
    by_session = session_rows(rows_all, a)
    out: Dict[str, Any] = {"iteration_ranges": {k: list(v) for k, v in rng.items()}, "first_new_cell": {"rd2": n_rd1, "rd3": n_rd2, "rd4": n_rd3}}
    out["rd4"] = rpt2.diagnostics(a, r4_first, None, first_new_cell=n_rd3)
    out["rd3_reference"] = rpt2.diagnostics(base, int(rd3_lo or 0), rd3_hi, first_new_cell=n_rd2)
    out["rd2_reference"] = rpt2.diagnostics(a2, int(rd2_lo or 0), rd2_hi, first_new_cell=n_rd1)
    out["rd1_reference"] = rpt2.diagnostics(a1, 0, int(rd2_lo or 0) - 1, first_new_cell=0)
    out["new"] = {"rd4": rpt3.new_diagnostics(a, r4_first), "rd3_reference": rpt3.new_diagnostics(base, int(rd3_lo or 0), rd3_hi),
                  "rd2_reference": rpt3.new_diagnostics(a2, int(rd2_lo or 0), rd2_hi), "rd1_reference": rpt3.new_diagnostics(a1, 0, int(rd2_lo or 0) - 1)}
    out["selection_probability_at_the_open"] = open_selection_probabilities4(base)
    yields = new_cells_by_iteration(a)
    rets4 = returns_by_iteration(a, r4_first)
    out["decision9"] = {"frontier_returns": {s: frontier_returns(by_session[s]) for s in ("rd4", "rd3", "rd2", "rd1")},
                        "returns_by_start_cell_session": {s: creation_shares(by_session[s]) for s in ("rd4", "rd3", "rd2", "rd1")},
                        "seen_distribution": {"rd4": seen_distribution(by_session["rd4"], yields, rets4),
                                              **{s: seen_distribution(by_session[s], yields, returns_by_iteration(a, *(rng[s] if rng[s][0] is not None else (0, None))))
                                                 for s in ("rd3", "rd2", "rd1")}}}
    mi = mechanism_inputs(a, rows_all, r4_first, n_rd3)
    out["mechanism"] = rule4.mechanism(**mi)
    out["mechanism_references"] = {s: {"seen_ge_8_share": seen_distribution(by_session[s])["seen_ge_8"]["share"], "dispatches": len(by_session[s])} for s in ("rd3", "rd2", "rd1")}
    out["D9_max_targets"] = {"archive_top_level": max(c.level for c in a.cells), "rd1": rule2.RD1["max_targets"]}
    for k, p in (("rd2", rd2_dir / "sessions" / "rd2" / "verification.json"), ("rd3", rd3_dir / "sessions" / "rd3" / "verification.json")):
        out["D9_max_targets"][k] = (_read(p).get("arm") or {}).get("max_targets", (_read(p).get("arm") or {}).get("t")) if p.is_file() else None
    out["upb_start_heights"] = {"rd4": rpt2.upb_start_heights(rpt3.bursts_in(a, r4_first)), "rd3_reference": rpt2.upb_start_heights(rpt3.bursts_in(base, int(rd3_lo or 0), rd3_hi))}
    out["ground_runs"] = {"rd4": rpt2.ground_run_readings(rpt3.bursts_in(a, r4_first)), "rd3_reference": rpt2.ground_run_readings(rpt3.bursts_in(base, int(rd3_lo or 0), rd3_hi))}
    rows = s2.overlay_rows(a)
    close_counts = s2.overlay_counts(a, rows)
    open_p = rd4_dir / "derived" / "open_overlay.json"
    base_d2 = bmeta.get("diag2") or {}
    own = {k: (len(v) if isinstance(v, list) else v) for k, v in a.diag2.items()}
    base_own = {k: (len(v) if isinstance(v, list) else v) for k, v in base_d2.items()}
    out["D8_mechanism_and_v2_flags"] = {"open": _read(open_p)["counts"] if open_p.is_file() else None,
                                        "close": {k: close_counts[k] for k in ("eligible_v1", "descent_among_v1_eligible", "bound_among_v1_eligible", "union", "eligible_v2")},
                                        "counters_cumulative": own, "counters_rd3_close": base_own, "counters_rd4": {k: own[k] - base_own.get(k, 0) for k in own},
                                        "exact_ground_evidence_shadow": rpt2.exact_evidence_shadow(a)}

    def efficiency(arm_path: Path, returns: int, new_cells: int) -> Optional[Dict[str, Any]]:
        if not arm_path.is_file():
            return None
        arm = _read(arm_path)
        ticks, prefix = arm.get("ticks", 0), arm.get("prefix_ticks", 0)
        return {"ticks": ticks, "prefix_ticks": prefix, "prefix_share": (prefix / ticks) if ticks else None, "new_exploration_ticks": ticks - prefix, "returns": returns,
                "new_cells_per_return": new_cells / returns if returns else None, "ticks_per_s": arm.get("ticks_per_s"), "wall_s": arm.get("wall_s"), "select_s": arm.get("select_s")}

    eff4 = efficiency(sd / "arm_T.json", out["rd4"]["returns"], len(a.cells) - n_rd3)
    if eff4 is not None:
        out["D7_efficiency"] = eff4
    out["D7_efficiency_references"] = {"rd3": efficiency(rd3_dir / "sessions" / "rd3" / "arm_T.json", out["rd3_reference"]["returns"], n_rd3 - n_rd2),
                                       "rd2": efficiency(rd2_dir / "sessions" / "rd2" / "arm_T.json", out["rd2_reference"]["returns"], n_rd2 - n_rd1),
                                       "rd1": efficiency(rd1_dir / "sessions" / "rd1" / "arm_T.json", out["rd1_reference"]["returns"], n_rd1 - 1)}
    ver_p = sd / "verification.json"
    if ver_p.is_file():
        v = _read(ver_p)
        out["D9_max_targets"]["verified_in_rd4"] = (v.get("arm") or {}).get("max_targets")
        out["claims"] = {"pools": v.get("pools"), "descriptive": (v.get("arm") or {}).get("descriptive"), "replays": (v.get("arm") or {}).get("replays")}
    out["rule_inputs"] = rule_inputs4(a, rows_all, r4_first, n_rd3)
    return out


# -- read-only post-run verification -----------------------------------------------------------------------------------------------------------------


def verify_run4(rd4_dir: Path, rd3_dir: Path, rd2_dir: Path, rd1_dir: Path, session: str = "rd4") -> Dict[str, Any]:
    """Independent of the driver: the rd4 archive verifies and its ledger rebuilds it exactly (four parts); rd4's files begin with rd3's closing bytes, rd3's with rd2's and rd2's with rd1's;
    the overlay file hashes to its record; the rule record (including the mechanism check and the line status) is recomputed from the archive, the earlier sessions' records and the verification
    replays; every route's actions hash to its metadata; the iteration rows add up to the arm's ticks; no replay used for a claim is inexact unless the session is INVALID."""
    import m8_rd4_resume as r4

    rd4_dir, rd3_dir, rd2_dir, rd1_dir = Path(rd4_dir), Path(rd3_dir), Path(rd2_dir), Path(rd1_dir)
    sd = rd4_dir / "sessions" / session
    problems: List[str] = []
    info: Dict[str, Any] = {}
    d, meta, rep = march.load_latest_verified(rd4_dir / "archive")
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
    a, meta = s4.Archive4.read_dir(d)
    lines = (meta.get("pin_tick0") or {}).get("lines")
    r4_first = int(a.rd4_first_iteration if a.rd4_first_iteration is not None else 0)
    close_p = sd / "close.json"
    if close_p.is_file():
        rec_manifest = (_read(close_p).get("archive") or {}).get("manifest")
        if rec_manifest != {n: march.sha256_file(Path(d) / n) for n in march.DATA_FILES}:
            problems.append("the archive's files differ from the manifest the close record stores")
    aud = s4.audit4(a, str(lines), collect_rows_from=r4_first)
    info["audit"] = {k: aud[k] for k in ("ok", "cells", "bursts", "events")}
    if not aud["ok"]:
        problems += [f"audit: {p}" for p in aud["problems"][:5]]
    chain = r4.prefix_chain(rd1_dir / "archive", rd2_dir / "archive", rd3_dir / "archive", d)
    info["prefix_chain"] = {"ok": chain["ok"]}
    if not chain["ok"]:
        problems += chain["problems"]
    ov, ovr = rd4_dir / "derived" / "open_overlay.jsonl", rd4_dir / "derived" / "open_overlay.json"
    if ov.is_file() and ovr.is_file():
        import m8_rd_resume as rs

        if rs.sha256_file(ov) != _read(ovr)["sha256"]:
            problems.append("the overlay file differs from its recorded digest")
    else:
        problems.append("no open overlay record")
    n_open = len(s4.Archive4.read_dir(rd4_dir / "base")[0].cells) if (rd4_dir / "base").is_dir() else 0
    rp = sd / "verification" / "replays.jsonl"
    reps = [json.loads(ln) for ln in rp.read_text(encoding="utf-8").splitlines()] if rp.is_file() else []
    if rule is not None:
        if rule["rule_sha256"] != rule4.rule_digest():
            problems.append("the rule digest in the record differs from the current rule")
        ins = rule_inputs4(a, aud["dispatch_rows"], r4_first, n_open)
        prior = r4.prior_milestones(rd1_dir, rd2_dir, rd3_dir)
        again = rule4.apply(invalid=rule["invalid"], incomplete=rule["incomplete"], m=rule["m"], t=rule["max_targets_verified"], prior=prior, claims_verified=rule.get("claims_verified", True),
                            exploration_started=rule.get("exploration_started", True), exploration_ticks=(rule.get("extra") or {}).get("exploration_ticks"), below_floor=ins["below_floor"], dispatches=ins["dispatches"], fatal_returns=ins["fatal_returns"],
                            returns=ins["returns"], seen_ge_8=ins["seen_ge_8"], new_cells=ins["new_cells"], launch_capable_created=ins["launch_capable_created"],
                            bound_violations=ins["bound_violations"], top_level_median_L=ins["top_level_median_L"])
        for k in ("outcome", "m", "max_targets_verified", "any_stop"):
            if again[k] != rule[k]:
                problems.append(f"rule record: {k} {rule[k]} differs from the recomputation {again[k]}")
        if again["mechanism"]["verdict"] != rule["mechanism"]["verdict"] or any(again["mechanism"][k] != rule["mechanism"][k] for k in ("returns", "seen_ge_8", "new_cells")):
            problems.append(f"rule record: the mechanism check {rule['mechanism']} differs from the recomputation {again['mechanism']}")
        if again["line"]["status"] != rule["line"]["status"] or again["line"]["rd5_permitted"] != rule["line"]["rd5_permitted"] or again["line"]["line_ends"] != rule["line"]["line_ends"]:
            problems.append(f"rule record: the line status {rule['line']} differs from the recomputation {again['line']}")
        info["recomputed_outcome"] = again["outcome"]
        info["recomputed_line"] = again["line"]["status"]
        m_again = replay_verified_m(reps)
        if m_again != rule["m"]:
            problems.append(f"rule record: m {rule['m']} differs from the milestone the exact replays hold ({m_again})")
        t_again = replay_verified_t(reps)
        if t_again != rule["max_targets_verified"]:
            problems.append(f"rule record: max targets {rule['max_targets_verified']} differs from the maximum the exact replays hold ({t_again})")
    for r in sorted((rd4_dir / "routes").glob("*")) if (rd4_dir / "routes").is_dir() else []:
        meta_p, act_p = r / "metadata.json", r / "actions.jsonl"
        if not (meta_p.is_file() and act_p.is_file()):
            problems.append(f"{r.name}: incomplete route directory")
            continue
        rows_ = [json.loads(ln) for ln in act_p.read_text(encoding="utf-8").splitlines()]
        digest = mcell.native_digest([(x["buttons"], x["stick_x"], x["stick_y"], x["consumed_tick"]) for x in rows_])
        if digest != _read(meta_p)["native_action_digest"] or [x["consumed_tick"] for x in rows_] != list(range(len(rows_))):
            problems.append(f"{r.name}: actions differ from the recorded digest or consumed ticks")
    p, arm_p = sd / "iterations_T.jsonl", sd / "arm_T.json"
    if p.is_file() and arm_p.is_file():
        rows_ = [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()]
        total = sum(int(x["ticks"]) for x in rows_ if "ticks" in x)
        if total != _read(arm_p)["ticks"]:
            problems.append(f"iteration rows add up to {total} ticks, the arm record says {_read(arm_p)['ticks']}")
        if any(x.get("tick0_equal") is False for x in rows_):
            problems.append("a row reports a tick-0 mismatch")
    if rule is not None and not rule["invalid"] and rp.is_file():
        bad = [r["label"] for r in reps if not r.get("exact")]
        if bad:
            problems.append(f"inexact replays in a session that is not INVALID: {bad[:4]}")
        info["replays"] = len(reps)
    return {"ok": not problems, "problems": problems, "info": info}
