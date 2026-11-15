#!/usr/bin/env python3
"""The hand-off from option D to the frontier (owner 2026-11-14; docs/frs_option_d_design_2026-11-11.md section 6.7 and D-Q9): D folders as
`--seeds-from` and `--best-from` sources of a run 3 plan. Zero native ticks; D folders are only read.

    admission   (answer 8) contract frs_order_search_v1 in lab mode; a clean status (run 3's CLEAN_STATUSES); a clean integrity record (no guard
                violation, prefix mismatch, tick-0 inequality or game left, root equal, D's and the lab's code unchanged during the run, every
                recorded milestone verified); a verified M1. Anything else is admitted only when --accept-run names the folder (recorded with
                its reasons).
    seeds       (answers 5 and 12) the final representative of every D cell id at level >= SEED_MIN_LEVEL whose tick is within the plan's E7
                bound, retired cells included (retirement is D's budget state). Each one's words give its words digest, its key's level is its
                level, and its niche recomputed from D's own lineage (run3_load.NicheIndex over D's rows and dispatch breaks, from D's tick-0
                root) equals the niche D recorded; the label is therefore 1023 + D's break order.
    insertion   (answer 6) the archive's own keep rule (crossing_search.Archive.keep), mirrored on the plan's rows as run2.ResumeArchive.load_run1
                mirrors it: a new key is a new cell id after the frontier's; a strictly earlier tick replaces the representative (the cell id
                stays, the new representative starts fresh, its claimed clears are dropped; the cell moves to D's group, the old group keeps
                its history); an equal or later tick is dropped (LATER, recorded). Seeds are taken in tick order, ties in the order given, so
                between two D folders the faster one wins. Origin {"kind": "seed", "fsid": <negative id per D folder>, "source": "order",
                "folder", "d_cid", "d_digest", "niche"}: run 2's root rule reads kind and fsid; run3_load reads the niche of a seed row.
    validation  (answer 4) none here: every seed loads as an inherited cell with no end record, so its first dispatch is fused (the worker
                checks the prefix by D's chain and end-record digest; a mismatch is run 2's prefix mismatch).
    best        (answer 9) a D folder's verified clears (verifications.jsonl, kind clear, verdict VERIFIED) and its native text replays, in the
                shape of crossing_search_run3.read_best_source; the plan requires an equal text replay for a D best, as for a run 3 best.

No coordinate, target id, route or order is read as a preference: the niche is a record. Standard library only.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

import crossing_search as cs
import frs_archive as fa
import frs_guard as g
import m8_rd_cells as mcell
import run3_load as rl3
import run3_select as rs

ORDER_CONTRACT = "frs_order_search_v1"      # tools/frs/order_search.ORDER_CONTRACT (D imports run 3, not the reverse; a test compares them)
SEED_MIN_LEVEL = 6                          # owner 2026-11-14: D's level-6-or-deeper lineages (M1's level)
SEED_SOURCE = "order"
ROOT_MASK = (1 << mcell.TARGETS_TOTAL) - 1  # every target live: D's tick-0 root
D_FILES =("plan.json", "run/config.json", "run/summary.json", "run/cells.jsonl", "run/dispatches.jsonl")
SearchError = cs.SearchError


def _read_jsonl(p: Path) -> Iterator[Dict[str, Any]]:
    with open(p, encoding="utf-8") as f:
        for ln in f:
            if ln.strip():
                yield json.loads(ln)


def _sha256(p: Path) -> Optional[str]:
    return g.sha256_file(p) if Path(p).is_file() else None


def is_d_folder(d: Path) -> bool:
    """True when the folder's plan carries D's contract (the plan decides which reader takes a --best-from folder)."""
    p = Path(d) / "plan.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("contract") == ORDER_CONTRACT
    except (OSError, ValueError):
        return False


def admission_problems(plan: Mapping[str, Any], summary: Mapping[str, Any]) -> List[str]:
    """Why a D folder is not admitted without --accept-run (answer 8); empty when it is."""
    out: List[str] = []
    if summary.get("status") not in rl3.CLEAN_STATUSES:
        out.append(f"status {summary.get('status')}")
    integ = summary.get("integrity") or {}
    for k in ("guard_violations_main", "prefix_mismatches", "tick0_unequal_jobs", "battleship_left", "order_code_changed_during_run",
              "lab_code_changed_during_run", "milestones_not_verified"):
        if integ.get(k):
            out.append(f"integrity {k} {integ.get(k)}")
    if integ.get("root_equal") is not True:
        out.append(f"integrity root_equal {integ.get('root_equal')}")
    if not integ.get("order_code_digest") or integ.get("order_code_digest_end") != integ.get("order_code_digest"):
        out.append("integrity: D's code digest at the close differs from the open's")
    if ((summary.get("order") or {}).get("gate_m1") or {}).get("verified") is not True:
        out.append("M1 not verified")
    return out


def read_d_folder(d: Path, accepted: Sequence[Any] = ()) -> Dict[str, Any]:
    """A D folder admitted as a hand-off source (answer 8): its plan, config and summary; refused unless admitted, or named by --accept-run."""
    d = Path(d)
    missing = [f for f in D_FILES if not (d / f).is_file()]
    if missing:
        raise SearchError(f"refused: {d} is not a D output folder (missing {missing})")
    plan = json.loads((d / "plan.json").read_text(encoding="utf-8"))
    config = json.loads((d / "run" / "config.json").read_text(encoding="utf-8"))
    summary = json.loads((d / "run" / "summary.json").read_text(encoding="utf-8"))
    for name, obj in (("plan.json", plan), ("run/summary.json", summary), ("run/config.json", config)):
        if obj.get("contract") != ORDER_CONTRACT or obj.get("mode") != "lab":
            raise SearchError(f"refused: {d / name} is not a {ORDER_CONTRACT} lab record")
    probs = admission_problems(plan, summary)
    named = g.norm(d) in {g.norm(Path(a)) for a in accepted}
    if probs and not named:
        raise SearchError(f"refused: the D folder {d} is not admitted ({'; '.join(probs)}); only an explicit --accept-run naming it admits it")
    m1 = (summary.get("order") or {}).get("gate_m1") or {}
    return {"dir": str(d), "plan": plan, "config": config, "summary": summary, "status": summary.get("status"), "accepted_non_clean": bool(probs),
            "admission_problems": probs, "utc_start": summary.get("utc_start"), "utc_end": summary.get("utc_end"), "archive_id": plan.get("archive_id"),
            "m1": {"met": m1.get("met"), "verified": m1.get("verified"), "tick": m1.get("tick")}}


def seed_fsid(D: Mapping[str, Any]) -> int:
    """The lineage root id of a D folder's seeds: negative (run 1's frontier state ids are >= 0) and stable (from D's archive id)."""
    return -(int(hashlib.sha256(str(D["archive_id"]).encode("utf-8")).hexdigest()[:12], 16) + 1)


def d_seeds(D: Mapping[str, Any], bound: int, min_level: int = SEED_MIN_LEVEL) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """The seeds of an admitted D folder (answers 5 and 12) and a report. Raises when a seed's words, level or niche do not match its row."""
    d = Path(D["dir"])
    rows: List[Dict[str, Any]] = []
    for i, r in enumerate(_read_jsonl(d / "run" / "cells.jsonl")):
        if r.get("ev") not in (cs.NEW, cs.REPLACED):
            continue
        if not r.get("key") or r.get("words_hex") is None or not r.get("digest"):
            raise SearchError(f"refused: {d} cells.jsonl row {i + 1}: not a kept representative with its key, words and digest")
        r["_run"] = 0
        rows.append(r)
    disp = [{"n": int(x["n"]), "breaks_after_start": x.get("breaks_after_start")} for x in _read_jsonl(d / "run" / "dispatches.jsonl")
            if x.get("kind", "burst") == "burst" and x.get("n") is not None]
    final: Dict[int, Dict[str, Any]] = {}
    for r in rows:
        final[int(r["cid"])] = r
    nx = rl3.NicheIndex([{"run": 0, "rows": rows, "dispatches": disp}])
    seeds: List[Dict[str, Any]] = []
    per_level: Dict[str, int] = {}
    beyond = 0
    for cid in sorted(final):
        r = final[cid]
        level, tick = int(r["level"]), int(r["tick"])
        if level < int(min_level):
            continue
        if tick > int(bound):
            beyond += 1
            continue
        k = fa.norm_key(r["key"])
        words = bytes.fromhex(r["words_hex"])
        if level >= mcell.TARGETS_TOTAL or mcell.level_of_mask(k[3]) != level:
            raise SearchError(f"refused: {d} cell {cid}: level {level} / key level {mcell.level_of_mask(k[3])}")
        if len(words) != tick or mcell.words_digest(words) != r["digest"]:
            raise SearchError(f"refused: {d} cell {cid}: its words do not give its tick and words digest")
        if len(bytes.fromhex(str(r.get("end_digest") or ""))) != 32 or len(bytes.fromhex(str(r.get("chain") or ""))) != 32:
            raise SearchError(f"refused: {d} cell {cid}: no end-record digest or chain")
        niche = rs.niche_label(nx.of(r))
        if niche != r.get("niche"):
            raise SearchError(f"refused: {d} cell {cid}: its niche from D's own lineage {niche} is not the recorded {r.get('niche')}")
        if not niche.startswith(f"{ROOT_MASK}:"):
            raise SearchError(f"refused: {d} cell {cid}: its lineage does not start from the tick-0 root ({niche})")
        seeds.append({"folder": str(d), "d_archive_id": D["archive_id"], "d_cid": cid, "digest": r["digest"], "key": list(k), "level": level, "tick": tick,
                      "words_hex": r["words_hex"], "end_digest": r["end_digest"], "chain": r["chain"], "niche": niche})
        per_level[str(level)] = per_level.get(str(level), 0) + 1
    rep = {"dir": str(d), "status": D["status"], "accepted_non_clean": D["accepted_non_clean"], "admission_problems": D["admission_problems"],
           "utc_start": D["utc_start"], "utc_end": D["utc_end"], "archive_id": D["archive_id"], "m1": D["m1"], "fsid": seed_fsid(D), "min_level": int(min_level),
           "rows": len(rows), "finals": len(final), "candidates": len(seeds), "beyond_bound": beyond, "per_level": dict(sorted(per_level.items())),
           "niche_stats": dict(nx.stats), "cells_sha256": _sha256(d / "run" / "cells.jsonl"), "dispatches_sha256": _sha256(d / "run" / "dispatches.jsonl")}
    return seeds, rep


def insert_seeds(final: Dict[int, Dict[str, Any]], origins: Dict[Tuple[int, str], Mapping[str, Any]], cleared: Dict[int, int],
                 niches: Dict[int, rs.Niche], sources: Sequence[Tuple[Mapping[str, Any], Sequence[Mapping[str, Any]]]],
                 lead_of: Callable[[int, int], int]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Answer 6: the seeds of every source (D folder report, its seeds) enter the plan's final rows by the archive's keep rule (see the module
    docstring), in tick order, ties in the order given. Mutates final, origins, cleared and niches; returns one record per seed and counts."""
    by_key: Dict[Tuple[Any, ...], int] = {fa.norm_key(r["key"]): int(cid) for cid, r in final.items()}
    queue = sorted(((int(s["tick"]), i, j, rep, s) for i, (rep, ss) in enumerate(sources) for j, s in enumerate(ss)), key=lambda x: x[:3])
    records: List[Dict[str, Any]] = []
    counts = {cs.NEW: 0, cs.REPLACED: 0, cs.LATER: 0}
    for tick, _i, _j, rep, s in queue:
        k = fa.norm_key(s["key"])
        level = int(s["level"])
        origin = {"kind": "seed", "fsid": int(rep["fsid"]), "source": SEED_SOURCE, "folder": s["folder"], "d_archive_id": s["d_archive_id"],
                  "d_cid": int(s["d_cid"]), "d_digest": s["digest"], "niche": s["niche"]}
        row = {"key": list(k), "level": level, "tick": tick, "lead": int(lead_of(level, tick)), "digest": s["digest"], "end_digest": s["end_digest"],
               "chain": s["chain"], "origin": origin, "seen": 0, "replaced": 0, "words_hex": s["words_hex"], "niche": s["niche"]}
        rec = {"folder": s["folder"], "d_cid": int(s["d_cid"]), "digest": s["digest"], "key": list(k), "level": level, "tick": tick, "niche": s["niche"]}
        cid = by_key.get(k)
        if cid is None:
            cid = len(final)
            if cid in final:
                raise SearchError(f"the plan's cell ids are not contiguous before the seeds ({cid})")
            row["cid"] = cid
            final[cid] = row
            by_key[k] = cid
            verdict = cs.NEW
        else:
            old = final[cid]
            if tick >= int(old["tick"]):
                counts[cs.LATER] += 1
                records.append(dict(rec, verdict=cs.LATER, cid=cid, existing_tick=int(old["tick"]), existing_digest=old["digest"]))
                continue
            row.update({"cid": cid, "seen": int(old.get("seen") or 0), "replaced": int(old.get("replaced") or 0) + 1})
            rec["previous"] = {"digest": old["digest"], "tick": int(old["tick"]), "niche": rs.niche_label(niches[cid]) if cid in niches else None,
                               "origin": old.get("origin")}
            final[cid] = row
            cleared.pop(cid, None)
            verdict = cs.REPLACED
        origins[(cid, str(s["digest"]))] = origin
        niches[cid] = rl3.niche_of_label(s["niche"])
        counts[verdict] += 1
        records.append(dict(rec, verdict=verdict, cid=cid))
    return records, counts


def seed_set_digest(records: Sequence[Mapping[str, Any]]) -> str:
    return hashlib.sha256("".join(f"{r['verdict']}:{r['cid']}:{r['folder']}:{r['d_cid']}:{r['digest']}:{r['tick']};" for r in records).encode("utf-8")).hexdigest()


def d_best_source(D: Mapping[str, Any]) -> Dict[str, Any]:
    """Answer 9: an admitted D folder as a --best-from source, in crossing_search_run3.read_best_source's shape. Read only."""
    run = Path(D["dir"]) / "run"
    vp = run / "verifications.jsonl"
    ver = list(_read_jsonl(vp)) if vp.is_file() else []
    tp = run / "text_replays.jsonl"
    text = {int(t["n"]): t for t in _read_jsonl(tp) if t.get("n") is not None} if tp.is_file() else {}
    claims = [int(x["claimed"]["completion_input_tick"]) for x in _read_jsonl(run / "dispatches.jsonl")
              if x.get("outcome") == "clear" and (x.get("claimed") or {}).get("completion_input_tick") is not None]
    ok = [v for v in ver if v.get("kind") == "clear" and v.get("verdict") == "VERIFIED"]
    return {"dir": D["dir"], "kind": "order", "status": D["status"], "accepted_non_clean": D["accepted_non_clean"], "admission_problems": D["admission_problems"],
            "utc_start": D["utc_start"], "utc_end": D["utc_end"], "verifications": ver, "verified": len(ok),
            "best_in_folder": min((int(v["completion_input_tick"]) for v in ok), default=None), "text": text,
            "claims_min": min(claims) if claims else None, "verifications_sha256": _sha256(vp)}
