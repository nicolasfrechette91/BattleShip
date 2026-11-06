#!/usr/bin/env python3
"""Run 3's start: runs 1 + 2 merged (2026-11-06 session, step 8; MINOR table O1, DECISIVE 4b). Zero native ticks; reads the two run
folders only.

    run 2           its folder is checked like run 1's (rl contract, a clean stop, a clean integrity record, the configuration = the plan)
                    and must have been planned on THIS run 1 (cell rows and start time recorded in its plan).
    merge           the cells of run 1 then run 2 in file order: the last row per cell id is its representative (run 2's new cells
                    continue run 1's ids). Origins of every representative ever kept (both runs), dispatch statistics by words digest
                    and by cell id (both key families), claimed clears per final representative, the fastest claim.
    niches          every row's order niche from its exact lineage (origin.parent_digest -> the first row with that digest), as
                    tools/analysis/run3_design/d4b_niche_units.py derives it; a multi-target step is ordered by the producing burst's
                    breaks_after_start (run and dispatch number of the row's origin).
    history         run 2 replayed in its dispatch-file order from run 1's final archive: every dispatch is credited to the group
                    (level, mask, niche) of the representative actually dispatched (the row of that cell whose tick equals the
                    dispatch's start tick), with n, falls, b (a burst that broke a target), bu (a useful break: next-level arrival <=
                    the bound; level 9: a claimed clear <= the bound) and e (a new earliest arrival in a deeper group; level 9: a
                    claimed clear faster than every earlier claim). Group moves (a replacement into another niche) are counted.

Standard library only.
"""
from __future__ import annotations

import bisect
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

import run3_select as rs

RUN2_CONTRACT = "frs_crossing_search_run2_v1"
RUN1_CONTRACT = "frs_crossing_search_v1"
RUN2_FILES = ("plan.json", "run/config.json", "run/summary.json", "run/cells.jsonl", "run/dispatches.jsonl")   # verifications.jsonl: only once a claim is replayed
CLEAN_STATUSES = ("COMPLETED", "ARCHIVE_EMPTY", "TICK_CAP", "WALL_CAP", "CELLS_CAP", "DISPATCH_CAP", "MEMORY_BUDGET")
FAMILY = {1: "crossing", 2: "crossing2"}
LIGHT_DISPATCH = ("n", "cid", "k", "level", "start_tick", "outcome", "levels", "breaks_after_start", "advanced", "claimed", "draw_id")


class LoadError(RuntimeError):
    pass


def read_jsonl(p: Path) -> Iterator[Dict[str, Any]]:
    with open(p, encoding="utf-8") as f:
        for ln in f:
            if ln.strip():
                yield json.loads(ln)


def _clean_run(d: Path, contract: str) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    plan = json.loads((d / "plan.json").read_text(encoding="utf-8"))
    config = json.loads((d / "run" / "config.json").read_text(encoding="utf-8"))
    summary = json.loads((d / "run" / "summary.json").read_text(encoding="utf-8"))
    for name, obj in (("plan.json", plan), ("run/config.json", config), ("run/summary.json", summary)):
        if obj.get("contract") != contract or obj.get("mode") != "lab":
            raise LoadError(f"refused: {d / name} is not a {contract} lab record")
    if summary.get("status") not in CLEAN_STATUSES:
        raise LoadError(f"refused: {d} did not stop cleanly (status {summary.get('status')})")
    integ = summary.get("integrity") or {}
    if integ.get("guard_violations_main") or integ.get("lab_code_changed_during_run") or integ.get("reference_ok") is not True \
            or integ.get("lab_code_digest_end") != config.get("lab_code_digest") or integ.get("battleship_left") or integ.get("prefix_mismatches"):
        raise LoadError(f"refused: {d}'s integrity record is not clean: {integ}")
    if config.get("params") != plan.get("params"):
        raise LoadError(f"refused: {d}'s run configuration is not its plan's")
    return plan, config, summary


def read_run(d: Path, run: int, *, run1_rows: Optional[int] = None, run1_utc_start: Optional[str] = None) -> Dict[str, Any]:
    """One run folder, light: every cell row without its words (except the final representative's), the dispatch rows' selection-
    relevant fields, the verification rows."""
    d = Path(d)
    files = RUN2_FILES
    missing = [f for f in files if not (d / f).is_file()]
    if missing:
        raise LoadError(f"refused: {d} is not a crossing search output folder (missing {missing})")
    plan, config, summary = _clean_run(d, RUN1_CONTRACT if run == 1 else RUN2_CONTRACT)
    if run == 2:
        p1 = plan.get("run1") or {}
        if run1_rows is not None and int(p1.get("cell_rows") or -1) != int(run1_rows):
            raise LoadError(f"refused: run 2 was planned on a run 1 with {p1.get('cell_rows')} cell rows, not {run1_rows}")
        if run1_utc_start is not None and p1.get("utc_start") != run1_utc_start:
            raise LoadError(f"refused: run 2 was planned on a run 1 started {p1.get('utc_start')}, not {run1_utc_start}")
    rows: List[Dict[str, Any]] = []
    words_last: Dict[int, str] = {}
    for i, r in enumerate(read_jsonl(d / "run" / "cells.jsonl")):
        if r.get("ev") not in (rs.NEW, rs.REPLACED) or not r.get("words_hex") or not r.get("key"):
            raise LoadError(f"{d} cells.jsonl row {i + 1}: not a kept representative with its key and words")
        words_last[int(r["cid"])] = r.pop("words_hex")
        r["_run"] = run
        rows.append(r)
    disp: List[Dict[str, Any]] = []
    for r in read_jsonl(d / "run" / "dispatches.jsonl"):
        if r.get("kind", "burst") != "burst":
            continue
        fam = str(r.get("draw_id", "")).split("|")
        if len(fam) != 3 or fam[1] != FAMILY[run]:
            raise LoadError(f"{d} dispatch {r.get('n')}: key family {r.get('draw_id')} is not run {run}'s ({FAMILY[run]})")
        x = {k: r.get(k) for k in LIGHT_DISPATCH}
        x["digest"] = fam[2]
        disp.append(x)
    ver = list(read_jsonl(d / "run" / "verifications.jsonl")) if (d / "run" / "verifications.jsonl").is_file() else []
    return {"dir": d, "run": run, "plan": plan, "config": config, "summary": summary, "rows": rows, "words_last": words_last, "dispatches": disp,
            "verifications": ver}


def merge(run1: Mapping[str, Any], run2: Mapping[str, Any]) -> Dict[str, Any]:
    """The final representatives of runs 1 + 2 (with their words), origins, dispatch statistics, cleared counts, the fastest claim."""
    final: Dict[int, Dict[str, Any]] = {}
    origins: Dict[Tuple[int, str], Dict[str, Any]] = {}
    for R in (run1, run2):
        for r in R["rows"]:
            cid = int(r["cid"])
            if cid not in final and cid != len(final):
                raise LoadError(f"run {R['run']}: a new cell id {cid} where {len(final)} was next")
            final[cid] = r
            origins[(cid, str(r["digest"]))] = r["origin"]
    words: Dict[int, str] = {}
    for R in (run1, run2):
        words.update(R["words_last"])
    out_final: Dict[int, Dict[str, Any]] = {}
    for cid, r in final.items():
        x = dict(r)
        x["words_hex"] = words[cid]
        out_final[cid] = x
    by_digest: Dict[str, List[int]] = {}
    by_cid: Counter = Counter()
    cleared: Counter = Counter()
    claims: List[int] = []
    for R in (run1, run2):
        for d in R["dispatches"]:
            st = by_digest.setdefault(str(d["digest"]), [0, 0])
            st[0] += 1
            st[1] += int(bool(d.get("advanced")))
            by_cid[int(d["cid"])] += 1
            if d.get("outcome") == "clear":
                ct = (d.get("claimed") or {}).get("completion_input_tick")
                if ct is not None:
                    claims.append(int(ct))
                f = out_final.get(int(d["cid"]))
                if f is not None and str(f["digest"]) == str(d["digest"]):
                    cleared[int(d["cid"])] += 1
    return {"final": out_final, "origins": origins, "dispatch_stats": by_digest, "cid_dispatches": dict(by_cid), "cleared": dict(cleared),
            "best_claim": min(claims) if claims else None, "claims": len(claims)}


def breaks_index(runs: Sequence[Mapping[str, Any]]) -> Dict[Tuple[int, int], List[Tuple[int, int]]]:
    out: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
    for R in runs:
        for d in R["dispatches"]:
            if d.get("breaks_after_start"):
                out[(int(R["run"]), int(d["n"]))] = [(int(t), int(i)) for t, i in d["breaks_after_start"]]
    return out


class NicheIndex:
    """Order niche of every cell row of runs 1 + 2 by its exact lineage (d4b_niche_units.py's derivation)."""

    def __init__(self, runs: Sequence[Mapping[str, Any]]):
        self.bydig: Dict[str, Dict[str, Any]] = {}
        for R in runs:
            for r in R["rows"]:
                self.bydig.setdefault(str(r["digest"]), r)
        self.breaks = breaks_index(runs)
        self.memo: Dict[str, rs.Niche] = {}
        self.stats: Counter = Counter()

    def of(self, r: Mapping[str, Any]) -> rs.Niche:
        path: List[Mapping[str, Any]] = []
        cur: Optional[Mapping[str, Any]] = r
        base: Optional[rs.Niche] = None
        while cur is not None:
            if str(cur["digest"]) in self.memo:
                base = self.memo[str(cur["digest"])]
                break
            path.append(cur)
            o = cur.get("origin") or {}
            pd = o.get("parent_digest")
            nxt = self.bydig.get(str(pd)) if pd else None
            if pd and nxt is None:
                self.stats["orphans"] += 1
            cur = nxt
        if base is None:
            root = path.pop()
            base = rs.seed_niche(int(root["key"][3]))
            self.memo[str(root["digest"])] = base
            self.stats["roots"] += 1
        for row in reversed(path):
            bk = self.breaks.get((int(row["_run"]), int(row["origin"]["n"])))
            base = rs.child_niche(base, int(row["key"][3]), int(row["tick"]), bk, self.stats)
            self.memo[str(row["digest"])] = base
        return base


def run2_history(run1: Mapping[str, Any], run2: Mapping[str, Any], niches: NicheIndex, bound: int) -> Dict[str, Any]:
    """Run 2 replayed in dispatch-file order with each dispatch credited to the group of the representative actually dispatched."""

    def gk(row: Mapping[str, Any]) -> rs.GKey:
        return (int(row["level"]), int(row["key"][3]), rs.niche_label(niches.of(row)))

    cur: Dict[int, Mapping[str, Any]] = {}
    hist: Dict[int, List[Mapping[str, Any]]] = defaultdict(list)
    groups: Dict[rs.GKey, List[Tuple[int, int]]] = defaultdict(list)

    def put(cid: int, r: Mapping[str, Any]) -> None:
        old = cur.get(cid)
        if old is not None:
            lst = groups[gk(old)]
            i = bisect.bisect_left(lst, (int(old["tick"]), cid))
            del lst[i]
        cur[cid] = r
        hist[cid].append(r)
        bisect.insort(groups[gk(r)], (int(r["tick"]), cid))

    moves: Counter = Counter()
    prev: Dict[int, Mapping[str, Any]] = {}
    for R in (run1, run2):
        for r in R["rows"]:
            cid = int(r["cid"])
            if cid in prev:
                moves[f"run{R['run']}_replacements"] += 1
                if gk(prev[cid]) != gk(r):
                    moves[f"run{R['run']}_moves"] += 1
            prev[cid] = r
    for r in run1["rows"]:
        put(int(r["cid"]), r)
    claims1 = [int(d["claimed"]["completion_input_tick"]) for d in run1["dispatches"] if d.get("outcome") == "clear" and (d.get("claimed") or {}).get("completion_input_tick") is not None]
    best_claim = min(claims1) if claims1 else 10 ** 9
    ev_by_n: Dict[int, List[Mapping[str, Any]]] = defaultdict(list)
    for r in run2["rows"]:
        ev_by_n[int(r["origin"]["n"])].append(r)
    st: Dict[rs.GKey, Counter] = defaultdict(Counter)
    attr: Counter = Counter()
    for d in run2["dispatches"]:
        cid = int(d["cid"])
        rep = next((x for x in reversed(hist.get(cid, [])) if int(x["tick"]) == int(d["start_tick"])), None)
        attr["by_start_tick" if rep is not None else "current_row"] += 1
        rep = rep or cur.get(cid)
        if rep is None:
            attr["unattributed"] += 1
            continue
        g = gk(rep)
        lv = g[0]
        nxt = (d.get("levels") or {}).get(str(lv + 1))
        ct = (d.get("claimed") or {}).get("completion_input_tick")
        s = st[g]
        s["n"] += 1
        s["fall"] += int(d.get("outcome") == "fall")
        s["b"] += int(bool(d.get("breaks_after_start")))
        s["bu"] += int(ct is not None and int(ct) <= bound) if lv == rs.TARGETS_TOTAL - 1 else int(nxt is not None and int(nxt) <= bound)
        e = 0
        for r in ev_by_n.get(int(d["n"]), []):
            if int(r["level"]) > lv:
                g2 = gk(r)
                if not groups[g2] or int(r["tick"]) < groups[g2][0][0]:
                    e = 1
        if lv == rs.TARGETS_TOTAL - 1 and ct is not None and int(ct) < best_claim:
            e = 1
            best_claim = int(ct)
        s["e"] += e
        for r in ev_by_n.get(int(d["n"]), []):
            put(int(r["cid"]), r)
    return {"groups": {rs.glabel(g): {k: int(v.get(k, 0)) for k in rs.HIST_FIELDS} for g, v in sorted(st.items())}, "attribution": dict(attr),
            "moves": dict(moves), "final_digests": {cid: str(r["digest"]) for cid, r in cur.items()}}


def load(run1_dir: Path, run2_dir: Path, bound: int, *, run1_rows: Optional[int] = None, run1_utc_start: Optional[str] = None) -> Dict[str, Any]:
    """Everything run 3's plan needs from the two run folders (zero native ticks)."""
    R1 = read_run(Path(run1_dir), 1)
    R2 = read_run(Path(run2_dir), 2, run1_rows=run1_rows if run1_rows is not None else len(R1["rows"]),
                  run1_utc_start=run1_utc_start if run1_utc_start is not None else R1["summary"].get("utc_start"))
    M = merge(R1, R2)
    nx = NicheIndex([R1, R2])
    niches = {cid: nx.of(r) for cid, r in M["final"].items()}
    H = run2_history(R1, R2, nx, int(bound))
    bad = [cid for cid, dg in H["final_digests"].items() if str(M["final"][cid]["digest"]) != dg]
    if bad or len(H["final_digests"]) != len(M["final"]):
        raise LoadError(f"refused: the replayed run 2 archive is not the merged one ({len(bad)} cells differ)")
    return {"R1": R1, "R2": R2, "M": M, "niches": niches, "niche_stats": dict(nx.stats), "history": H}
