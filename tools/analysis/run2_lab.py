#!/usr/bin/env python3
"""A crossing-search run folder (raw rows) as the same analyses RUN2_ANALYSIS.md draws from the records (read-only).

    python -B tools/analysis/run2_lab.py --run C:/BattleShip_lab/crossing_2026-10-15_run2/run --out <folder>

Reads dispatches.jsonl, cells.jsonl and verifications.jsonl (required) and checks.jsonl, summary.json (optional), one line at
a time, and writes <out>/lab_analysis.json plus charts. Writes nothing in the run folder. Every number here is MEASURED from
the rows (unlike run2_records.py's worker-time split, which is inferred), except where a field says otherwise.

What it computes:
    per_target      the earliest break of each target over every burst (breaks_after_start, absolute ticks) and verified clear
    orders          the complete order of every verified clear, the fastest clock per order and how many clears share it
    over_time       per window of 1,000 dispatches: new cells, replacements, bursts that broke a target, falls, clears
                    claimed, and the running earliest arrival per level (from cells.jsonl NEW / REPLACED rows)
    stalls          the longest stretch of dispatches without a new earliest arrival at the deepest level, and since the
                    last one
    worker_time     job clock (wall_s), stepping (step_s), continuation questions (ask_s), checks and verification walls,
                    measured, against workers x run wall (the rest is outside the job clock: close, transfer, idle)
    groups          dispatches, breaks, falls and clears per (level, live-target mask) group
    oddities        bursts with two breaks at most 3 ticks apart; cells whose position bucket is a robust outlier (more than
                    5 MAD from the median); rows whose integrity flags are not clean

Full order prefixes of non-clearing trajectories need the lineage across runs (the route-insight report's scripts); they are
not rebuilt here. Standard library, plus matplotlib for the charts (skipped with --no-charts).
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

WINDOW = 1000
SHORT_GAP = 3
OUTLIER_MADS = 5.0


def rows(path: Path) -> Iterator[Dict[str, Any]]:
    if not path.is_file():
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def analyse(run: Path, workers: Optional[int] = None) -> Dict[str, Any]:
    run = Path(run)
    for need in ("dispatches.jsonl", "cells.jsonl"):
        if not (run / need).is_file():
            raise SystemExit(f"refused: {run / need} not found (is this a crossing-search run folder?)")
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8")) if (run / "summary.json").is_file() else {}
    config = json.loads((run / "config.json").read_text(encoding="utf-8")) if (run / "config.json").is_file() else {}

    # -- cells: key per cell id, events over dispatches ------------------------------------------------------------------------------
    key_of: Dict[int, List[Any]] = {}
    cell_events: List[Tuple[int, str, int, int]] = []          # (n, ev, level, tick)
    bx: List[int] = []
    by: List[int] = []
    cell_pos: List[Tuple[int, int, int]] = []
    for c in rows(run / "cells.jsonl"):
        key_of[int(c["cid"])] = c["key"]
        n = int(c.get("n") or 0)
        cell_events.append((n, c["ev"], int(c["level"]), int(c["tick"])))
        if c["ev"] == "new":
            bx.append(int(c["key"][0]))
            by.append(int(c["key"][1]))
            cell_pos.append((int(c["cid"]), int(c["key"][0]), int(c["key"][1])))

    # -- dispatches ------------------------------------------------------------------------------------------------------------------
    per_target: Dict[int, Dict[str, Any]] = {}
    windows: Dict[int, Dict[str, int]] = {}
    groups: Dict[str, Dict[str, int]] = {}
    short: List[Dict[str, Any]] = []
    flags: List[Dict[str, Any]] = []
    t = {"jobs": 0, "wall_s": 0.0, "step_s": 0.0, "ask_s": 0.0, "ticks": 0, "burst_words": 0}
    n_max = 0
    for d in rows(run / "dispatches.jsonl"):
        if d.get("kind", "burst") != "burst":
            continue
        n = int(d["n"])
        n_max = max(n_max, n)
        w = windows.setdefault((n - 1) // WINDOW, {"dispatches": 0, "broke": 0, "falls": 0, "clears": 0, "new_cells": 0, "replacements": 0})
        w["dispatches"] += 1
        w["broke"] += int(bool(d.get("advanced")))
        w["falls"] += int(d.get("outcome") == "fall")
        w["clears"] += int(d.get("outcome") == "clear")
        if "wall_s" in d and d["wall_s"] is not None:
            t["jobs"] += 1
            t["wall_s"] += float(d["wall_s"] or 0.0)
            t["step_s"] += float(d.get("step_s") or 0.0)
            t["ask_s"] += float(d.get("ask_s") or 0.0)
        t["ticks"] += int(d.get("ticks") or 0)
        t["burst_words"] += int(d.get("words_played") or 0)
        br = sorted((int(a), int(b)) for a, b in (d.get("breaks_after_start") or []))
        for tick, target in br:
            cur = per_target.get(target)
            if cur is None or tick < cur["tick"]:
                per_target[target] = {"tick": tick, "dispatch": n, "source": "burst"}
        for (t1, a), (t2, b) in zip(br, br[1:]):
            if t2 - t1 <= SHORT_GAP:
                short.append({"dispatch": n, "first": [t1, a], "second": [t2, b], "gap": t2 - t1})
        key = key_of.get(int(d["cid"]))
        g = groups.setdefault(f"{d['level']}|{key[3] if key else '?'}", {"level": int(d["level"]), "mask": key[3] if key else None, "dispatches": 0,
                                                                         "broke": 0, "falls": 0, "clears": 0})
        g["dispatches"] += 1
        g["broke"] += int(bool(d.get("advanced")))
        g["falls"] += int(d.get("outcome") == "fall")
        g["clears"] += int(d.get("outcome") == "clear")
        bad = {k: d.get(k) for k in ("prefix_level_ok", "tick0_equal") if d.get(k) is False}
        if d.get("outcome") in ("mismatch", "lifecycle", "aborted"):
            bad["outcome"] = d.get("outcome")
        if bad:
            flags.append({"dispatch": n, **bad})

    for n, ev, _lv, _tick in cell_events:
        if n <= 0:
            continue
        w = windows.setdefault((n - 1) // WINDOW, {"dispatches": 0, "broke": 0, "falls": 0, "clears": 0, "new_cells": 0, "replacements": 0})
        w["new_cells" if ev == "new" else "replacements"] += 1

    # -- earliest arrival per level over dispatches, and the stalls ------------------------------------------------------------------
    earliest: Dict[int, List[Tuple[int, int]]] = {}
    best: Dict[int, int] = {}
    for n, _ev, lv, tick in sorted(cell_events, key=lambda e: e[0]):
        if lv not in best or tick < best[lv]:
            best[lv] = tick
            earliest.setdefault(lv, []).append((n, tick))
    deepest = max(earliest) if earliest else None
    stall = None
    if deepest is not None:
        ns = [n for n, _ in earliest[deepest]] + [n_max]
        gaps = [(b - a, a, b) for a, b in zip(ns, ns[1:])]
        g = max(gaps) if gaps else (0, 0, 0)
        stall = {"level": deepest, "longest_without_new_earliest": g[0], "from_dispatch": g[1], "to_dispatch": g[2],
                 "since_last": n_max - earliest[deepest][-1][0]}

    # -- verified clears and their orders --------------------------------------------------------------------------------------------
    orders: Dict[str, Dict[str, Any]] = {}
    vwall = 0.0
    verified = 0
    for v in rows(run / "verifications.jsonl"):
        vwall += float(v.get("wall_s") or 0.0)
        if v.get("verdict") != "VERIFIED":
            continue
        verified += 1
        br = sorted((int(a), int(b)) for a, b in (v.get("breaks_r1") or []))
        for tick, target in br:
            cur = per_target.get(target)
            if cur is None or tick < cur["tick"]:
                per_target[target] = {"tick": tick, "dispatch": v.get("n"), "source": "verified clear"}
        order = ", ".join(str(b) for _t, b in br)
        o = orders.setdefault(order, {"order": order, "fastest": None, "clears": 0})
        o["clears"] += 1
        cit = v.get("completion_input_tick")
        if cit is not None and (o["fastest"] is None or int(cit) < o["fastest"]):
            o["fastest"] = int(cit)

    cwall = sum(float(c.get("wall_s") or 0.0) for c in rows(run / "checks.jsonl"))
    wall = float(summary.get("wall_s") or summary.get("elapsed_s") or 0.0)
    n_workers = workers or int(config.get("n_workers") or 0) or None
    worker_time: Dict[str, Any] = {"evidence": "measured", "jobs": t["jobs"], "job_clock_s": round(t["wall_s"], 1), "stepping_s": round(t["step_s"], 1),
                                   "ask_s": round(t["ask_s"], 1), "checks_s": round(cwall, 1), "verification_s": round(vwall, 1),
                                   "ticks": t["ticks"], "burst_words": t["burst_words"]}
    if n_workers and wall:
        total = n_workers * wall
        worker_time.update({"workers": n_workers, "run_wall_s": round(wall, 1), "worker_s": round(total, 1),
                            "outside_job_clock_s": round(total - t["wall_s"] - cwall - vwall, 1),
                            "note": "outside the job clock = close, result transfer, ingest, selection and idle slots"})

    # -- position outliers (robust z on the 300-unit buckets of new cells) -----------------------------------------------------------
    out_pos: List[Dict[str, Any]] = []
    if len(bx) >= 10:
        for axis, vals, idx in (("x", bx, 1), ("y", by, 2)):
            med = statistics.median(vals)
            mad = statistics.median(abs(v - med) for v in vals) or 1.0
            for cid, x, y in cell_pos:
                z = abs((x, y)[idx - 1] - med) / mad
                if z > OUTLIER_MADS:
                    out_pos.append({"cid": cid, "axis": axis, "bucket": (x, y)[idx - 1], "median": med, "mads": round(z, 1)})

    return {"run": str(run), "status": summary.get("status"), "dispatches": n_max, "verified_clears": verified,
            "per_target": {str(k): v for k, v in sorted(per_target.items())},
            "orders": sorted(orders.values(), key=lambda o: (o["fastest"] if o["fastest"] is not None else 10 ** 9)),
            "over_time": {"window": WINDOW, "rows": [dict(w, window=k + 1) for k, w in sorted(windows.items())]},
            "earliest": {str(k): v for k, v in sorted(earliest.items())}, "stall": stall, "worker_time": worker_time,
            "groups": sorted(groups.values(), key=lambda g: (-g["level"], -g["dispatches"])),
            "oddities": {"short_gaps": short[:200], "short_gaps_total": len(short), "position_outliers": out_pos[:200],
                         "position_outliers_total": len(out_pos), "integrity_flags": flags[:200], "integrity_flags_total": len(flags)}}


def charts(A: Dict[str, Any], out: Path) -> List[str]:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import chartstyle as cs
    import matplotlib.pyplot as plt

    cs.apply()
    made = []
    ot = A["over_time"]["rows"]
    if ot:
        fig, axes = plt.subplots(1, 3, figsize=(11, 3.4))
        for ax, key, title in zip(axes, ("new_cells", "broke", "clears"), ("New cells", "Bursts that broke a target", "Clears claimed")):
            ax.bar([str(r["window"]) for r in ot], [r[key] for r in ot], width=0.62, color=cs.BLUE)
            ax.set_title(f"{title} per {A['over_time']['window']:,} dispatches")
            ax.set_xlabel("window of dispatches")
            cs.ygrid(ax)
        cs.header(fig, "Exploration over the run, per window of dispatches", f"measured · {A['run']}")
        cs.save(fig, out / "lab_over_time.png")
        made.append("lab_over_time.png")
    if A["earliest"]:
        fig, ax = plt.subplots(figsize=(9, 4))
        levels = sorted((int(k) for k in A["earliest"]), reverse=True)[:3]
        for color, lv in zip(cs.SERIES, levels):
            pts = A["earliest"][str(lv)]
            xs = [p[0] for p in pts] + [A["dispatches"]]
            ys = [p[1] for p in pts] + [pts[-1][1]]
            ax.step(xs, ys, where="post", color=color, lw=1.8, label=f"level {lv}")
        ax.set_xlabel("dispatch")
        ax.set_ylabel("earliest arrival (input tick)")
        ax.legend()
        cs.ygrid(ax)
        cs.header(fig, "Earliest arrival at the three deepest levels", f"measured · {A['run']}")
        cs.save(fig, out / "lab_earliest.png")
        made.append("lab_earliest.png")
    return made


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", type=Path, required=True, help="the run folder (holds dispatches.jsonl, cells.jsonl, ...)")
    ap.add_argument("--out", type=Path, required=True, help="output folder (created; must not be the run folder)")
    ap.add_argument("--workers", type=int, default=None, help="worker count, when config.json does not say")
    ap.add_argument("--no-charts", action="store_true")
    a = ap.parse_args(argv)
    if a.out.resolve() == a.run.resolve():
        print("refused: --out must not be the run folder (this tool writes nothing there)", file=sys.stderr)
        return 2
    A = analyse(a.run, a.workers)
    a.out.mkdir(parents=True, exist_ok=True)
    with open(a.out / "lab_analysis.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(A, f, indent=1)
        f.write("\n")
    made = [] if a.no_charts else charts(A, a.out)
    print(f"{A['dispatches']:,} dispatches, {A['verified_clears']} verified clears, {len(A['per_target'])} targets with a break, "
          f"{A['oddities']['short_gaps_total']} short gaps, {A['oddities']['integrity_flags_total']} integrity flags -> {a.out / 'lab_analysis.json'}"
          + (f", {', '.join(made)}" if made else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
