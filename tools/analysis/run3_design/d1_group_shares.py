#!/usr/bin/env python3
"""DECISIVE 1 (selection inside a level): group rates and the group-share formula, on run 2's dispatch rows.

    python -B tools/analysis/run3_design/d1_group_shares.py [--lab C:/BattleShip_lab] [--out logs/run3_design]

Prints and writes d1_group_shares.json:
  - the earliest arrival per level at run 2's start and end, and the dispatch of its last improvement (level 10 = clears, from
    the claimed completion_input_tick; run 1's best 1,429 as the start);
  - per group: dispatches n, bursts that broke a target b, new earliest arrivals at the next level e, rho = (b + e + 1) / (n + 2);
  - levels 9 and 8: the review's share as written, max(phi, rho) normalised (every group on the floor: equal thirds), against
    rho normalised first and then floored at phi = 1 / (4 x groups) (the approved formula), against run 2's actual split.
"""
import collections

import _common as C
import run3_archive as ar

a = C.parse(__doc__)
cells, _ = ar.merged_cells([a.r1 / "cells.jsonl", a.r2 / "cells.jsonl"])
D = C.bursts(a.r2, by_n=True)
earliest = collections.defaultdict(lambda: 10 ** 9)
for r in {r["cid"]: r for r in C.rows(a.r1 / "cells.jsonl")}.values():
    earliest[int(r["level"])] = min(earliest[int(r["level"])], int(r["tick"]))
earliest[10] = C.RUN1_BEST
start = dict(earliest)
last_impr = {}
e_by_group, n_by_group, b_by_group = collections.Counter(), collections.Counter(), collections.Counter()
for d in D:
    g = ar.group_of(int(d["level"]), cells.get(int(d["cid"])))
    n_by_group[g] += 1
    b_by_group[g] += bool(d.get("breaks_after_start"))
    lv = int(d["level"])
    for k, t in (d.get("levels") or {}).items():
        k, t = int(k), int(t)
        if k == 10 and d["outcome"] == "clear":
            t = int((d.get("claimed") or {}).get("completion_input_tick") or t)
        if t < earliest[k]:
            earliest[k] = t
            last_impr[k] = d["n"]
            if k == lv + 1:
                e_by_group[g] += 1
out = {"earliest": {str(k): {"start": start[k], "end": earliest[k], "last_improvement_n": last_impr.get(k)} for k in sorted(start)}}
print("earliest arrival per level: run 2 start -> end, last improvement at dispatch")
for k in sorted(start):
    print(" ", k, start[k], "->", earliest[k], "last at n", last_impr.get(k))
print("groups: n, breaks b, new earliest at next level e, rho = (b+e+1)/(n+2)")
rows_ = []
out["groups"] = {}
for g in sorted(n_by_group, key=lambda g: (-g[0], -n_by_group[g])):
    if n_by_group[g] < 100:
        continue
    n, b, e = n_by_group[g], b_by_group[g], e_by_group[g]
    rows_.append((g, n, b, e, (b + e + 1) / (n + 2)))
    print(" ", g, n, b, e, round((b + e + 1) / (n + 2), 4))
    out["groups"][C.gkey(g)] = {"n": n, "b": b, "e": e, "rho": (b + e + 1) / (n + 2)}
out["shares"] = {}
for L in (9, 8):
    gs = [r for r in rows_ if r[0][0] == L]
    G = len([g for g in n_by_group if g[0] == L])
    phi = 1 / (4 * G)
    raw = {r[0][1]: max(phi, r[4]) for r in gs}
    tot = sum(raw.values())
    norm = {r[0][1]: r[4] for r in gs}
    nt = sum(norm.values())
    normf = {k: max(phi, v / nt) for k, v in norm.items()}
    nf = sum(normf.values())
    actual = {r[0][1]: r[1] / sum(x[1] for x in gs) for r in gs}
    res = {"phi": phi, "as_written": {k: v / tot for k, v in raw.items()}, "normalised_then_floored": {k: v / nf for k, v in normf.items()},
           "run2_actual": actual}
    out["shares"][str(L)] = res
    fmt = lambda d: "{" + ", ".join(f"{k}: {v:.2f}" for k, v in d.items()) + "}"
    print(f"level {L}: groups {G}, phi {phi:.3f}; as written max(phi, rho): {fmt(res['as_written'])}; "
          f"normalised then floored: {fmt(res['normalised_then_floored'])}; run 2 actual: {fmt(actual)}")
C.dump(a, "d1_group_shares.json", out)
