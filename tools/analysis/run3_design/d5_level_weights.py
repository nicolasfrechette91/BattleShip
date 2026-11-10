#!/usr/bin/env python3
"""Level weights for the run inheriting run 3's night (owner 2026-11-09, before its smoke run). Zero native ticks, read-only.

    python -B tools/analysis/run3_design/d5_level_weights.py [--lab C:/BattleShip_lab] [--out logs/run3_design]

1. Yield per dispatch by level in the night (crossing_2026-11-06_run3), at the 953 definition (u = next-level arrival <= 953, at level 9
   a claimed clear <= 953; e = a new earliest arrival in a deeper group, at level 9 a claimed clear faster than every earlier claim), for
   every dispatch and for the dispatches whose start cell is at or under 953 (the cells the next run can draw).
2. How the level-8 and level-9 arrivals evolved over the night: hour by hour, the earliest arrival at 8, 9 and 10, the arrivals at or under
   953, and for each verified best the creation of its start cell and the dispatches until the clear.
3. One simulated night per level split with DECISIVE 4's model (tools/analysis/run3_design/run3_model.py: the within-group draw (1 + rank)^-1
   x max(0.05, 1 / (1 + draws)) and anchors, a static archive), on the real 953 start (the plan inheriting the night, built here with the
   committed code): per level the exploitation draws, the expected u + e at the night's per-level rates, and the level-9 cells' draws.
"""
import bisect
import collections
import json
import sys
from pathlib import Path

import numpy as np

import _common as C
import run3_model as M

a = C.parse(__doc__)
sys.path.insert(0, str(C.REPO / "tools" / "frs"))
import crossing_search_run3 as CS  # noqa: E402
import run3_load as L  # noqa: E402
import run3_select as rs  # noqa: E402

NIGHT = a.lab / "crossing_2026-11-06_run3"
BOUND = 953
rd = NIGHT / "run"
disp = sorted(C.bursts(rd), key=lambda d: int(d["n"]))
recs = [json.loads(x) for x in (rd / "hourly.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
hour_end = [int(r["ingested_total"]) for r in recs]          # dispatches ingested at each record (hours 1-7, then the close)

# -- 1. yield per dispatch by level (e rebuilt as run3_load.inherited_history does, validated there) --------------------------------------
R1 = L.read_run(a.lab / "crossing_2026-10-15", 1)
R2 = L.read_run(a.lab / "crossing_2026-10-15_run2", 2, run1_rows=len(R1["rows"]), run1_utc_start=R1["summary"].get("utc_start"))
R3 = L.read_run3(NIGHT, 3)
nx = L.NicheIndex([R1, R2, R3])
H = L.run2_history(R1, R2, nx, BOUND)
st = H.pop("_state")
groups_alive, gk = st["groups"], st["gk"]
ev_by_n = collections.defaultdict(list)
for r in R3["rows"]:
    ev_by_n[int(r["origin"]["n"])].append(r)
best_claim = int(R3["plan"]["run3"]["best_claim"])
per = collections.defaultdict(collections.Counter)
timeline = []
for d in R3["dispatches"]:
    lv = int(d["level"])
    claimed = (d.get("claimed") or {}).get("completion_input_tick") if d.get("outcome") == "clear" else None
    nxt = (d.get("levels") or {}).get(str(lv + 1))
    u = int(claimed is not None and int(claimed) <= BOUND) if lv == 9 else int(nxt is not None and int(nxt) <= BOUND)
    u_own = int(claimed is not None and int(claimed) <= 1171) if lv == 9 else int(nxt is not None and int(nxt) <= 1171)
    e = 0
    for r in ev_by_n.get(int(d["n"]), []):
        if int(r["level"]) > lv:
            lst = groups_alive.get(gk(r))
            if not lst or int(r["tick"]) < lst[0][0]:
                e = 1
    if claimed is not None and int(claimed) < best_claim:
        best_claim = int(claimed)
        if lv == 9:
            e = 1
    for key in ("all", "start<=953" if int(d["start_tick"]) <= BOUND else None):
        if key:
            c = per[(lv, key)]
            c.update({"n": 1, "u953": u, "e": e, "u1171": u_own, "fall": int(d.get("outcome") == "fall"), "break": int(bool(d.get("advanced")))})
    timeline.append((int(d["n"]), lv, d.get("levels") or {}, claimed, int(d["start_tick"]), int(d["cid"])))
    for r in ev_by_n.get(int(d["n"]), []):
        st["put"](int(r["cid"]), r)
print("1. yield per 1,000 dispatches by level (u953 + e: the next run's definition; u1171: the night's)")
yield_rate = {}
for lv in (9, 8, 7, 6):
    for key in ("all", "start<=953"):
        c = per[(lv, key)]
        if not c["n"]:
            continue
        r_ = (c["u953"] + c["e"]) / c["n"]
        if key == "start<=953":
            yield_rate[lv] = r_
        print(f"   level {lv} {key:11s} n {c['n']:6d}  u953 {c['u953']:4d}  e {c['e']:3d}  -> {1000 * r_:6.2f} per 1,000   (u1171 {c['u1171']:5d}, "
              f"falls {c['fall'] / c['n']:.2f}, breaks {c['break'] / c['n']:.3f})")

# -- 2. evolution over the night ------------------------------------------------------------------------------------------------------
print("\n2. by hour: earliest arrival at levels 8 / 9 / clear (claimed), arrivals at or under 953 at levels 8 / 9, level-9 dispatches")
earliest = {8: None, 9: None, 10: None}
h_i, rows_h = 0, []
cnt = collections.Counter()
for n, lv, levels, claimed, t0, cid in timeline:
    while h_i < len(hour_end) and n > hour_end[h_i]:
        rows_h.append((h_i, dict(earliest), dict(cnt)))
        cnt = collections.Counter()
        h_i += 1
    for k, t in levels.items():
        k, t = int(k), int(t)
        if k in (8, 9):
            if earliest[k] is None or t < earliest[k]:
                earliest[k] = t
            cnt[f"L{k}<=953"] += int(t <= BOUND)
    if claimed is not None and (earliest[10] is None or int(claimed) < earliest[10]):
        earliest[10] = int(claimed)
    cnt[f"disp_L{lv}"] += 1
rows_h.append((h_i, dict(earliest), dict(cnt)))
for h, e_, c in rows_h:
    print(f"   hour {h + 1}: earliest L8 {e_[8]} L9 {e_[9]} clear {e_[10]} | arrivals <=953 L8 {c.get('L8<=953', 0)} L9 {c.get('L9<=953', 0)} | "
          f"dispatches L9 {c.get('disp_L9', 0)} L8 {c.get('disp_L8', 0)} L7 {c.get('disp_L7', 0)}")
ver = [json.loads(x) for x in (rd / "verifications.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
row_by = {(int(r["cid"]), int(r["tick"])): r for r in R3["rows"]}
print("\n   verified bests: start cell created at dispatch -> cleared at dispatch (level-9 dispatches in between, dispatches of that start)")
l9_ns = [n for n, lv, *_ in timeline if lv == 9]
for v in sorted((v for v in ver if v.get("verdict") == "VERIFIED"), key=lambda v: v["n"]):
    d = next(x for x in R3["dispatches"] if int(x["n"]) == int(v["n"]))
    r = row_by.get((int(d["cid"]), int(d["start_tick"])))
    born = int(r["origin"]["n"]) if r else None
    between = sum(1 for n in l9_ns if born is not None and born < n < int(v["n"]))
    same = sum(1 for n, lv, _l, _c, t0, cid in timeline if cid == int(d["cid"]) and t0 == int(d["start_tick"]) and n <= int(v["n"]))
    print(f"   {v['completion_input_tick']}: start {d['start_tick']} (cell {d['cid']}) created at {born if born is not None else 'run 1/2'}, cleared at {v['n']}: "
          f"{between} level-9 dispatches between, the start's {same}th dispatch")

# -- 3. simulated nights per level split on the real 953 start -----------------------------------------------------------------------
P = CS.build_plan(a.lab, a.lab / "crossing_2026-10-15", a.lab / "crossing_2026-10-15_run2", CS.Params3(rng_seed=3), code_digest="analysis",
                  inherit=[NIGHT])
arch, X = P["archive"], P["run3"]
sel = rs.Run3Selector(arch, CS.Params3(rng_seed=3), niches=X["niches"], history=X["history"], cid_dispatches=X["cid_dispatches"],
                      best_claim=X["best_claim"], history_tails=X["history_tails"], history_windows=X["history_windows"])
groups, cells, shares = {}, {}, {}
for lv, gs in sel.levels().items():
    sh, _phi = sel.shares(lv, gs)
    for g in gs:
        mem = sel.members(g)
        groups[g] = [(int(arch.cells[c].tick), int(c)) for c in mem]
        for c in mem:
            cells[int(c)] = {"tick": int(arch.cells[c].tick), "cls": str(arch.cells[c].key[2])}
        shares[g] = sh[g]
anchors = M.class_anchors(groups, cells)
EXPL = int(round(len(disp) * (1 - 0.2)))
SPLITS = {"current 8/15 4/15 2/15 1/15": {9: 8 / 15, 8: 4 / 15, 7: 2 / 15, 6: 1 / 15}, "flat 1/4 each": {9: 0.25, 8: 0.25, 7: 0.25, 6: 0.25},
          "7-8 first 0.20 0.35 0.35 0.10": {9: 0.20, 8: 0.35, 7: 0.35, 6: 0.10}}
print(f"\n3. simulated nights ({EXPL} exploitation draws, the night's volume x 0.8; static archive; seed 1): per level draws, expected u + e at the night's"
      " per-level rates for start <= 953, and level 9's cells")
sim = {}
for name, lw in SPLITS.items():
    out = {"draws": {}, "expected": {}}
    l9 = None
    for g, el in groups.items():
        N = int(round(EXPL * lw[g[0]] * shares[g]))
        r = M.night(g, groups, cells, anchors, N, w_min=0.125, rotate="bursts", seed=1)
        out["draws"][g[0]] = out["draws"].get(g[0], 0) + N
        out["expected"][g[0]] = out["expected"].get(g[0], 0.0) + N * yield_rate.get(g[0], 0.0)
        if g[0] == 9:
            l9 = r["draws"]
    d9 = np.sort(l9)[::-1] if l9 is not None else np.zeros(0)
    out["l9"] = {"cells": int(len(l9)), "per_cell_mean": float(l9.mean()), "min": int(l9.min()), "median": float(np.median(l9)),
                 "earliest_cell": int(l9[0]), "cells_under_50": int((l9 < 50).sum()), "top5": [int(x) for x in d9[:5]]}
    sim[name] = out
    print(f"   {name:32s} draws L9 {out['draws'][9]:6d} L8 {out['draws'][8]:6d} L7 {out['draws'][7]:6d} L6 {out['draws'][6]:6d} | expected u+e "
          + " ".join(f"L{lv} {out['expected'][lv]:5.1f}" for lv in (9, 8, 7, 6))
          + f" | L9 cells: mean {out['l9']['per_cell_mean']:.0f}, min {out['l9']['min']}, earliest cell {out['l9']['earliest_cell']}, under 50: {out['l9']['cells_under_50']}")
C.dump(a, "d5_level_weights.json", {"bound": BOUND, "yield": {f"{lv}|{k}": dict(c) for (lv, k), c in per.items()}, "yield_rate_start953": yield_rate,
                                    "hours": rows_h, "simulations": {k: {"draws": v["draws"], "expected": v["expected"], "l9": v["l9"]} for k, v in sim.items()}})
