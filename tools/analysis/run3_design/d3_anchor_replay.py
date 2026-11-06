#!/usr/bin/env python3
"""DECISIVE 3 (anchors): replay of run 2's archive history, dispatch by dispatch (zero native ticks).

    python -B tools/analysis/run3_design/d3_anchor_replay.py [--lab C:/BattleShip_lab] [--out logs/run3_design]

Starts from run 1's final archive, then walks run 2's dispatches in ingest order, applying the cell events each produced
(cells.jsonl rows by origin.n). For every dispatch it records the dispatched cell's arrival rank in its (level, mask) group and in
its (group, resource class), and:
    b   the burst broke a target;
    e   it made a new earliest arrival in a deeper group (at level 9: a claimed clear faster than every earlier claim);
    ea  it made a new anchor in a deeper group (a cell entering its class's 3 earliest there).
Prints and writes d3_anchor_replay.json: yield by class rank and by group rank (buckets 0, 1, 2, 3-9, 10-99, 100+), which ranks the
e events came from, the wait (ingests) of every new group-earliest arrival until its first dispatch, the anchor bursts per group,
new class-top-3 arrivals per level, and the anchor sets at run 3's start (bound 1,220) with the share the rank draw already gives
them. Also writes d3_dispatch_log.json (per dispatch n: ingest, cell, group, class, ranks, sizes, b, e, ea), read by
d3_class_lineage.py, d3_anchor_sim.py and d4_*.py.
"""
import bisect
import collections

import _common as C

a = C.parse(__doc__)
K = 3
cells = {}
grp = collections.defaultdict(list)    # (level, mask) -> sorted [(tick, cid)]
gcl = collections.defaultdict(list)    # (level, mask, class) -> sorted [(tick, cid)]


def put(cid, c):
    old = cells.get(cid)
    if old is not None:
        g = (old["level"], old["mask"])
        grp[g].remove((old["tick"], cid))
        gcl[g + (old["cls"],)].remove((old["tick"], cid))
    cells[cid] = c
    g = (c["level"], c["mask"])
    bisect.insort(grp[g], (c["tick"], cid))
    bisect.insort(gcl[g + (c["cls"],)], (c["tick"], cid))


def cell_of(r):
    k = r["key"]
    return {"level": int(r["level"]), "tick": int(r["tick"]), "cls": k[2], "mask": int(k[3]), "parent": (r.get("origin") or {}).get("parent")}


for r in C.rows(a.r1 / "cells.jsonl"):
    if r.get("ev") in ("new", "replaced") and r.get("key"):
        put(int(r["cid"]), cell_of(r))
r1_cells = len(cells)
best_claim = min((d["claimed"]["completion_input_tick"] for d in C.rows(a.r1 / "dispatches.jsonl") if d.get("claimed")), default=10 ** 9)
ev_by_n = collections.defaultdict(list)
for r in C.rows(a.r2 / "cells.jsonl"):
    ev_by_n[int(r["origin"]["n"])].append(r)

bound = C.RUN1_BEST - C.MARGIN - 1
steps = list(C.RUN2_BEST_STEPS)
BUCKETS = ["0", "1", "2", "3-9", "10-99", "100+"]


def rank(lst, tick, cid):
    return bisect.bisect_left(lst, (tick, cid))


def bucket(r):
    return "0" if r == 0 else "1" if r == 1 else "2" if r == 2 else "3-9" if r < 10 else "10-99" if r < 100 else "100+"


by_cls = collections.defaultdict(collections.Counter)
by_grp = collections.defaultdict(collections.Counter)
pending_first, waits = {}, []
e_sources = collections.Counter()
anchor_runs = collections.defaultdict(list)
ea_stats = collections.defaultdict(collections.Counter)
new_anchor = collections.Counter()
dlog = {}
ingest = 0
for d in C.bursts(a.r2):
    ingest += 1
    while steps and ingest > steps[0][0]:
        bound = steps[0][1] - C.MARGIN - 1
        steps.pop(0)
    cid = int(d["cid"])
    c = cells.get(cid)
    if c is None:
        continue
    g = (c["level"], c["mask"])
    rg = rank(grp[g], c["tick"], cid)
    rc = rank(gcl[g + (c["cls"],)], c["tick"], cid)
    b = int(bool(d.get("breaks_after_start")))
    e = ea = 0
    for r in ev_by_n.get(int(d["n"]), []):
        if r["level"] > c["level"] and r.get("key"):
            g2 = (int(r["level"]), int(r["key"][3]))
            if not grp[g2] or int(r["tick"]) < grp[g2][0][0]:
                e = 1
            lst = gcl[g2 + (r["key"][2],)]
            if len(lst) < K or int(r["tick"]) < lst[min(K, len(lst)) - 1][0]:
                ea = 1
    if c["level"] == 9 and d.get("claimed"):
        t = d["claimed"]["completion_input_tick"]
        if t < best_claim:
            e = 1
            best_claim = t
    lv = c["level"]
    for tab, r_ in ((by_cls, rc), (by_grp, rg)):
        for key in ((lv, bucket(r_)), ("all", bucket(r_))):
            tab[key]["n"] += 1
            tab[key]["b"] += b
            tab[key]["e"] += e
    if e:
        e_sources[("anchor" if rc < K else "other", lv)] += 1
    if rc < K:
        anchor_runs[g].append(e)
        ea_stats[lv]["n"] += 1
        ea_stats[lv]["ea"] += ea
        ea_stats[lv]["e"] += e
    if cid in pending_first:
        made, lvl, earliest = pending_first.pop(cid)
        waits.append((lvl, ingest - made, e, b, earliest))
    dlog[int(d["n"])] = {"ingest": ingest, "cid": cid, "g": list(g), "cls": c["cls"], "rg": rg, "rc": rc, "gsize": len(grp[g]),
                         "csize": len(gcl[g + (c["cls"],)]), "tick": c["tick"], "b": b, "e": e, "ea": ea, "bound": bound,
                         "outcome": d.get("outcome"), "ticks": int(d.get("ticks") or 0)}
    for r in ev_by_n.get(int(d["n"]), []):
        if not r.get("key"):
            continue
        nc = cell_of(r)
        g2 = (nc["level"], nc["mask"])
        earliest = (not grp[g2]) or nc["tick"] < grp[g2][0][0]
        lstc = gcl[g2 + (nc["cls"],)]
        if nc["tick"] <= bound and (len([1 for t, _ in lstc[:K] if t <= bound]) < K or nc["tick"] < lstc[K - 1][0]):
            new_anchor[nc["level"]] += 1
        put(int(r["cid"]), nc)
        if earliest:
            pending_first[int(r["cid"])] = (ingest, nc["level"], True)
        elif int(r["cid"]) in pending_first:
            p = pending_first[int(r["cid"])]
            pending_first[int(r["cid"])] = (p[0], nc["level"], p[2])

out = {"run1_cells": r1_cells, "run2_dispatches": ingest, "cells_end": len(cells),
       "anchor_bursts_by_level": {str(k): dict(v) for k, v in ea_stats.items()}, "new_class_top3_arrivals_by_level": {str(k): v for k, v in new_anchor.items()}}
print("anchor bursts (class rank < 3) by level: n, ea, e:", out["anchor_bursts_by_level"])
print("new class-top-3 arrivals in run 2 by level:", out["new_class_top3_arrivals_by_level"])


def table(tab, name):
    print(f"\n== yield by {name} rank ==")
    print("level bucket   n   share   b/n   e/n")
    for lv in [6, 7, 8, 9, "all"]:
        tot = sum(tab[(lv, bk)]["n"] for bk in BUCKETS)
        for bk in BUCKETS:
            x = tab[(lv, bk)]
            if x["n"]:
                print(f"{lv!s:>5} {bk:>6} {x['n']:6d} {100 * x['n'] / tot:6.1f}% {100 * x['b'] / x['n']:6.2f}% {100 * x['e'] / x['n']:6.2f}%  (b {x['b']}, e {x['e']})")
    out[name] = {f"{lv}|{bk}": dict(tab[(lv, bk)]) for lv in [6, 7, 8, 9, "all"] for bk in BUCKETS}


table(by_cls, "class")
table(by_grp, "group")
print("\n== e sources (class rank < 3 = anchor) ==", dict(e_sources))
out["e_sources"] = {f"{x}|{y}": v for (x, y), v in e_sources.items()}
print("\n== new group-earliest arrivals: ingests until first dispatch ==")
out["earliest_never_dispatched"] = sum(1 for v in pending_first.values() if v[2])
for lv in [7, 8, 9, 10]:
    w = sorted(x[1] for x in waits if x[0] == lv and x[4])
    if not w:
        continue
    fe = sum(x[2] for x in waits if x[0] == lv and x[4])
    fb = sum(x[3] for x in waits if x[0] == lv and x[4])
    q = lambda p: w[min(len(w) - 1, int(p * len(w)))]
    print(f"level {lv}: {len(w)} dispatched, wait median {q(0.5)} q25 {q(0.25)} q75 {q(0.75)} max {w[-1]}; first dispatch e {fe}, b {fb}")
    out[f"waits_l{lv}"] = {"n": len(w), "median": q(0.5), "q25": q(0.25), "q75": q(0.75), "max": w[-1], "first_e": fe, "first_b": fb}
print("new group-earliest never dispatched:", out["earliest_never_dispatched"])
print("\n== anchor bursts (class rank < 3) per group with >= 50: n, e ==")
for g, seq in sorted(anchor_runs.items(), key=lambda x: (-x[0][0], -len(x[1]))):
    if len(seq) >= 50:
        print(g, len(seq), sum(seq))
out["anchor_bursts_per_group"] = {C.gkey(g): [len(s), sum(s)] for g, s in anchor_runs.items()}

print("\n== run 3 start (bound 1,220): anchors per group ==")
start = {}
for g in sorted(grp, key=lambda x: (-x[0], x[1])):
    if g[0] < 6:
        continue
    el = [(t, cid) for t, cid in grp[g] if t <= C.BOUND_RUN3]
    if len(el) < 20:
        continue
    classes = sorted({cells[cid]["cls"] for _, cid in el})
    anchors = set()
    for cl in classes:
        anchors |= {cid for _, cid in [(t, cid) for t, cid in gcl[g + (cl,)] if t <= C.BOUND_RUN3][:K]}
    pos = {cid: i for i, (_, cid) in enumerate(el)}
    wsum = sum(1 / (1 + i) for i in range(len(el)))
    info = {"eligible": len(el), "classes": classes, "anchors": len(anchors), "anchor_group_ranks": sorted(pos[x] for x in anchors),
            "rank_draw_share_of_anchors": round(sum(1 / (1 + pos[x]) for x in anchors) / wsum, 3),
            "class_earliest_ticks": {cl: [t for t, cid in gcl[g + (cl,)] if t <= C.BOUND_RUN3][:1] for cl in classes},
            "class_sizes": {cl: sum(1 for t, cid in gcl[g + (cl,)] if t <= C.BOUND_RUN3) for cl in classes}}
    start[C.gkey(g)] = info
    print(g, info)
out["run3_start"] = start
C.dump(a, "d3_anchor_replay.json", out)
C.dump(a, "d3_dispatch_log.json", dlog)
