"""M8-rd: the reported readings (never deciding), the read-only post-run verification, and the rebuilt-executable projection.

Pure file readers over a finished session directory (zero native ticks).
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import m8_rd_archive as march
import m8_rd_cells as mcell
import m8_rd_claims as mclaims
import m8_rd_rule as mrule

LAUNCH_CAPABLE_Y = 1639.0          # M7p's measured minimum up-B start that can reach the wall top
LEDGE_RIGHT_X = -1200.0
LAUNCH_CAPABLE_X = 600.0
L1_FLOOR_LINE = 1


def _read(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_archive(root: Path) -> Tuple[Optional[march.Archive], Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    d, meta, report = march.load_latest_verified(Path(root) / "archive")
    if d is None:
        return None, None, report
    a, meta = march.Archive.read_files(d)
    return a, meta, report


def load_coverage_C(session_dir: Path) -> List[Tuple[Tuple[int, int, str, int, int], int, int]]:
    p = Path(session_dir) / "coverage_C.json.gz"
    if not p.is_file():
        return []
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return [((int(k[0]), int(k[1]), str(k[2]), int(k[3]), int(k[4])), int(c), int(t)) for k, c, t in json.load(f)]


def _readings(entries: Sequence[Tuple[Tuple[int, int, str, int, int], int, int, Optional[float], Optional[float]]],
              upto: Optional[int]) -> Dict[str, Any]:
    """entries: (key, first cumulative tick, tick within its trajectory, x, y); x and y are the cell's own position for the
    archive and the bin ceiling for the coverage-only arm."""
    sel = [e for e in entries if upto is None or e[1] <= upto]
    keys = [e[0] for e in sel]
    levels: Dict[int, Dict[str, int]] = {}
    for k, cum, tick, _x, _y in sel:
        lv = mcell.level_of_mask(k[3])
        d = levels.get(lv)
        if d is None or cum < d["cum"]:
            levels[lv] = {"cum": cum, "tick": tick}
    best_y = None
    for k, _c, _t, x, y in sel:
        if x is not None and x <= LEDGE_RIGHT_X and (best_y is None or y > best_y):
            best_y = y
    capable = [e for e in sel if e[0][2] in (mcell.RES_A2, mcell.RES_A1) and e[4] is not None and e[4] >= LAUNCH_CAPABLE_Y]
    return {"cells": len(sel), "masks": len({k[3] for k in keys}), "bins": len({(k[0], k[1]) for k in keys}),
            "resource": {r: sum(1 for k in keys if k[2] == r) for r in mcell.RESOURCE_CLASSES},
            "cells_by_level": {str(lv): sum(1 for k in keys if mcell.level_of_mask(k[3]) == lv) for lv in sorted({mcell.level_of_mask(k[3]) for k in keys})},
            "first_reach_by_level": {str(k): v for k, v in sorted(levels.items())},
            "best_y_with_x_le_-1200": best_y,
            "l1_contact_cells": sum(1 for k in keys if k[2] == mcell.RES_GROUNDED and k[4] == L1_FLOOR_LINE),
            "wall_top_cells": sum(1 for k in keys if k[2] == mcell.RES_GROUNDED and k[4] == mcell.L0_FLOOR_LINE),
            "left_of_wall_cells": sum(1 for k in keys if k[0] <= -8),
            "launch_capable_cells": len(capable),
            "launch_capable_cells_x_le_600": sum(1 for e in capable if e[3] is not None and e[3] <= LAUNCH_CAPABLE_X)}


def build_report(root: Path, session: str, T: Optional[int] = None) -> Dict[str, Any]:
    """The section 11.3 'reported, never deciding' readings, for both arms in full and within the comparison point."""
    sd = Path(root) / "sessions" / session
    rule = _read(sd / "rule.json") if (sd / "rule.json").is_file() else {}
    point = T if T is not None else (rule.get("extra") or {}).get("comparison_point")
    arch, meta, _rep = load_archive(root)
    out: Dict[str, Any] = {"comparison_point": point, "arms": {}}
    arm_T = _read(sd / "arm_T.json") if (sd / "arm_T.json").is_file() else None
    arm_C = _read(sd / "arm_C.json") if (sd / "arm_C.json").is_file() else None
    if arch is not None:
        entries = [(c.key, c.first_cum, c.L, float(c.end[mcell.I_X]), float(c.end[mcell.I_Y])) for c in arch.cells]
        out["arms"]["T"] = {"full": _readings(entries, None), "within_T": _readings(entries, point) if point else None,
                            "archive": arch.stats(), "returns": sum(1 for e in arch.events if e["ev"] == "ingest"),
                            "dispatches": sum(1 for e in arch.events if e["ev"] == "dispatch"),
                            "failed_iterations": sum(1 for e in arch.events if e["ev"] == "fail"),
                            "velocity_reversals": arch.diag}
    cov = load_coverage_C(sd)
    if cov:
        entries = [(k, c, t, k[0] * mcell.CELL_SIZE + mcell.CELL_SIZE, k[1] * mcell.CELL_SIZE + mcell.CELL_SIZE) for k, c, t in cov]
        out["arms"]["C"] = {"full": _readings(entries, None), "within_T": _readings(entries, point) if point else None,
                            "note": "coverage-only arm: x, y are the bin ceilings (the cell's own position is not kept)"}
    for name, rec in (("T", arm_T), ("C", arm_C)):
        if rec is not None:
            out["arms"].setdefault(name, {})["run"] = rec
    if arm_T and arm_T.get("ticks"):
        out["return_overhead"] = {"prefix_ticks": arm_T.get("prefix_ticks"), "ticks": arm_T["ticks"],
                                  "prefix_share": round(arm_T.get("prefix_ticks", 0) / max(1, arm_T["ticks"]), 4)}
    if (sd / "memory_summary.json").is_file():
        out["memory"] = _read(sd / "memory_summary.json")
    return out


# -- read-only post-run verification -----------------------------------------------------------------------------------------


def verify_run(root: Path, session: str) -> Dict[str, Any]:
    """Independent of the driver: the archive manifest verifies and the ledger rebuilds it exactly; the rule record is
    recomputed from the verification record; every route's actions hash to its metadata; the iteration rows add up to the
    arms' tick counts; no replay used for a claim is inexact unless the session is INVALID."""
    root, sd = Path(root), Path(root) / "sessions" / session
    problems: List[str] = []
    info: Dict[str, Any] = {}
    arch, meta, rep = load_archive(root)
    info["checkpoints"] = rep
    if arch is None:
        problems.append("no archive checkpoint with a verifying manifest")
    else:
        aud = march.audit(arch)
        info["audit"] = {k: aud[k] for k in ("ok", "cells", "bursts", "events")}
        if not aud["ok"]:
            problems += [f"audit: {p}" for p in aud["problems"][:5]]
    rule = _read(sd / "rule.json")
    ver = _read(sd / "verification.json") if (sd / "verification.json").is_file() else None
    if ver is not None:
        v = ver["arms"]
        again = mrule.apply(invalid=rule["invalid"], incomplete=rule["incomplete"], m_T=v["T"]["m"], m_C=v["C"]["m"],
                            t_T=v["T"]["t"], t_C=v["C"]["t"])
        for k in ("outcome", "m_T", "m_C", "t_T", "t_C"):
            if again[k] != rule[k]:
                problems.append(f"rule record: {k} {rule[k]} differs from the recomputation {again[k]}")
        info["recomputed_outcome"] = again["outcome"]
    if rule["rule_sha256"] != mrule.rule_digest():
        problems.append("the rule digest in the record differs from the current rule")
    for r in sorted((root / "routes").glob("*")) if (root / "routes").is_dir() else []:
        meta_p, act_p = r / "metadata.json", r / "actions.jsonl"
        if not (meta_p.is_file() and act_p.is_file()):
            problems.append(f"{r.name}: incomplete route directory")
            continue
        rows = [json.loads(ln) for ln in act_p.read_text(encoding="utf-8").splitlines()]
        digest = mcell.native_digest([(x["buttons"], x["stick_x"], x["stick_y"], x["consumed_tick"]) for x in rows])
        if digest != _read(meta_p)["native_action_digest"] or [x["consumed_tick"] for x in rows] != list(range(len(rows))):
            problems.append(f"{r.name}: actions differ from the recorded digest or consumed ticks")
    for arm in ("T", "C"):
        p, a = sd / f"iterations_{arm}.jsonl", sd / f"arm_{arm}.json"
        if p.is_file() and a.is_file():
            rows = [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()]
            total = sum(int(x["ticks"]) for x in rows if "ticks" in x)
            if total != _read(a)["ticks"]:
                problems.append(f"arm {arm}: iteration rows add up to {total} ticks, the arm record says {_read(a)['ticks']}")
            if any(x.get("tick0_equal") is False for x in rows):
                problems.append(f"arm {arm}: a row reports a tick-0 mismatch")
    if ver is not None and not rule["invalid"]:
        for arm in ("T", "C"):
            ledger = _read(sd / f"ledger_{arm}.json") if (sd / f"ledger_{arm}.json").is_file() else None
            info.setdefault("ledgers", {})[arm] = {"ticks": ledger["ticks"], "candidates": len(ledger["candidates"])} if ledger else None
        replays = [json.loads(ln) for ln in (sd / "verification" / "replays.jsonl").read_text(encoding="utf-8").splitlines()] \
            if (sd / "verification" / "replays.jsonl").is_file() else []
        bad = [r["label"] for r in replays if not r.get("exact")]
        if bad:
            problems.append(f"inexact replays in a session that is not INVALID: {bad[:4]}")
        info["replays"] = len(replays)
    return {"ok": not problems, "problems": problems, "info": info}


# -- rebuilt-executable re-verification (section 7.2): the plan and its projected cost ----------------------------------------


def reverify_plan(archive: march.Archive) -> List[Dict[str, Any]]:
    """One job per burst that holds at least one representative: the trajectory up to the last representative of that burst,
    with every such cell checked at its L along that one replay."""
    by_burst: Dict[int, List[march.Cell]] = {}
    for c in archive.cells:
        if c.burst >= 0:
            by_burst.setdefault(c.burst, []).append(c)
    jobs = []
    for b, cells in sorted(by_burst.items()):
        burst = archive.bursts[b]
        top = max(cells, key=lambda c: c.offset)
        words = archive.rep_words(b, top.offset)
        jobs.append({"kind": "reverify", "burst": b, "words": words,
                     "checks": [{"cell": c.id, "L": c.L, "end": c.end, "end_digest": c.end_digest, "chain": c.chain,
                                 "terminal": c.terminal}
                                for c in sorted(cells, key=lambda c: c.L)], "allowance": len(words)})
    return jobs


def reverify_projection(root: Path, rate_ticks_per_s: Tuple[float, float] = (1700.0, 2900.0)) -> Dict[str, Any]:
    arch, meta, rep = load_archive(Path(root))
    if arch is None:
        return {"ok": False, "reason": "no verified archive checkpoint", "checkpoints": rep}
    jobs = reverify_plan(arch)
    ticks = sum(len(j["words"]) for j in jobs)
    covered = sum(len(j["checks"]) for j in jobs)
    return {"ok": True, "cells": len(arch.cells), "cells_covered": covered + 1, "bursts_with_representatives": len(jobs),
            "projected_native_ticks": ticks, "projected_hours": [round(ticks / r / 3600, 3) for r in rate_ticks_per_s[::-1]],
            "rates_ticks_per_s": list(rate_ticks_per_s),
            "note": "cell 0 is covered by the tick-0 pin; a mismatch stops the session for review, nothing is dropped or re-pinned"}
