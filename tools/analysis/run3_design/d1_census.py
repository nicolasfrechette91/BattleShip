#!/usr/bin/env python3
"""DECISIVE 1 (selection inside a level): run 2's census per level and per (level, mask) group.

    python -B tools/analysis/run3_design/d1_census.py [--lab C:/BattleShip_lab] [--out logs/run3_design]

Prints and writes d1_census.json:
  - run 2's outcomes, wall, ticks (prefix vs burst);
  - per level: dispatches, bursts that broke a target, falls, clears;
  - per group: dispatches, breaks, falls, clears (rows as run3_archive.group_table counts them);
  - per level: cells (runs 1 + 2 merged), cells <= 1,220 (run 3's E7 bound), <= 1,404 (run 2's first bound), dispatched in run 2;
  - per main group: the share of the group's run 2 dispatches that went to its 10 earliest cells, cells never dispatched, and
    the share the approved rank draw (1 + rank)^-1 would give the 10 earliest among cells <= 1,220.
Session log section 16.2 quotes these numbers.
"""
import collections
import json

import _common as C
import run3_archive as ar

a = C.parse(__doc__)
cells, rep = ar.merged_cells([a.r1 / "cells.jsonl", a.r2 / "cells.jsonl"])
D = C.bursts(a.r2)
out = {"cells": len(cells), "dispatches": len(D)}
print("dispatches", len(D), "outcomes", collections.Counter(d["outcome"] for d in D).most_common())
s = json.load(open(a.r2 / "summary.json", encoding="utf-8"))
work = {k: s["work"].get(k) for k in ("dispatches", "jobs", "ticks", "burst_ticks", "prefix_ticks")}
print("status", s["status"], "elapsed_s", s.get("elapsed_s"), "work", work)
out["summary"] = {"status": s["status"], "elapsed_s": s.get("elapsed_s"), "work": work}

lv = collections.defaultdict(collections.Counter)
for d in D:
    c = lv[d["level"]]
    c["disp"] += 1
    c["broke"] += bool(d.get("breaks_after_start"))
    c["fall"] += d["outcome"] == "fall"
    c["clear"] += d["outcome"] == "clear"
print("level: dispatches / broke / falls / clears")
for k in sorted(lv):
    print(" ", k, dict(lv[k]))
out["levels"] = {str(k): dict(v) for k, v in lv.items()}

tab = ar.group_table(D, cells)
print("groups (level, mask): dispatches broke falls clears  [top 14]")
for g in tab[:14]:
    print(" ", g)
out["groups"] = tab

disp_cids = collections.Counter(d["cid"] for d in D)
per = collections.defaultdict(lambda: [0, 0, 0, 0])
for cid, c in cells.items():
    p = per[c["level"]]
    p[0] += 1
    p[1] += c["tick"] <= C.BOUND_RUN3
    p[2] += c["tick"] <= C.RUN1_BEST - C.MARGIN - 1
    p[3] += cid in disp_cids
print("level: cells / tick<=1220 (run 3 E7) / tick<=1404 (run 2 E7) / cells dispatched in run 2")
for k in sorted(per):
    print(" ", k, per[k])
out["cells_per_level"] = {str(k): dict(zip(("cells", "le_1220", "le_1404", "dispatched_run2"), v)) for k, v in per.items()}

by_g = collections.defaultdict(list)
for cid, c in cells.items():
    by_g[ar.group_of(c["level"], c)].append((c["tick"], cid))
gd = collections.Counter(ar.group_of(int(d["level"]), cells.get(int(d["cid"]))) for d in D)


def H(n):
    return sum(1 / (1 + r) for r in range(n))


print("group: cells (all / tick<=1220) | run 2: dispatches, share to the 10 earliest cells, cells never dispatched | "
      "rank draw a=1: share of the 10 earliest among <=1220")
out["top10"] = {}
for g in [(9, 2), (9, 256), (9, 64), (8, 258), (8, 66), (8, 320), (7, 322), (6, 326), (6, 330)]:
    cs = sorted(by_g[g])
    el = [x for x in cs if x[0] <= C.BOUND_RUN3]
    top = {cid for _t, cid in cs[:10]}
    n = gd[g] or 1
    share_top = sum(disp_cids[c] for c in top) / n
    never = sum(1 for _t, cid in cs if disp_cids[cid] == 0)
    rk = H(min(10, len(el))) / H(len(el)) if el else 0
    print(f"  {g}: {len(cs)} / {len(el)} | {gd[g]}, {share_top:.3f}, {never} of {len(cs)} | {rk:.2f}  "
          f"(earliest ticks {[t for t, _ in cs[:3]]})")
    out["top10"][C.gkey(g)] = {"cells": len(cs), "eligible": len(el), "dispatches": gd[g], "run2_top10_share": share_top,
                              "never_dispatched": never, "rank_draw_top10_share": rk, "earliest": [t for t, _ in cs[:3]]}
C.dump(a, "d1_census.json", out)
