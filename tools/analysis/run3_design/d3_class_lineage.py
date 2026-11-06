#!/usr/bin/env python3
"""DECISIVE 3 (anchors): yield by resource class, the verified lineages and where their links ranked (zero native ticks).

    python -B tools/analysis/run3_design/d3_class_lineage.py [--lab C:/BattleShip_lab] [--out logs/run3_design]

Needs d3_dispatch_log.json from d3_anchor_replay.py in --out. Prints and writes d3_class_lineage.json:
  - run 2's break and fall rates per dispatch by (level, class);
  - eligible cells at run 3's start by (level, class);
  - every verified clear of runs 1 and 2 with its lineage (level, tick, class), walked through origin.parent with the
    representative that was current when the child was made;
  - for run 2's three verified bests: each link's group rank and class rank at the dispatch that made the next link, and the
    ingests it waited since it was made.
"""
import collections
import json

import _common as C

a = C.parse(__doc__)
dlog = {int(k): v for k, v in json.load(open(a.out / "d3_dispatch_log.json", encoding="utf-8")).items()}
R = {1: a.r1, 2: a.r2}
hist = collections.defaultdict(list)
for run in (1, 2):
    for r in C.rows(R[run] / "cells.jsonl"):
        if r.get("key"):
            hist[int(r["cid"])].append((run, int((r.get("origin") or {}).get("n") or 0), r))
cls = {cid: h[-1][2]["key"][2] for cid, h in hist.items()}
out = {}

tab = collections.defaultdict(collections.Counter)
for d in C.bursts(a.r2):
    c = cls.get(int(d["cid"]))
    for key in ((int(d["level"]), c), ("all", c)):
        t = tab[key]
        t["n"] += 1
        t["b"] += int(bool(d.get("breaks_after_start")))
        t["fall"] += int(d.get("outcome") == "fall")
print("== run 2 yield by class ==\nlevel class     n     b/n   falls")
out["yield_by_class"] = {}
for lv in [6, 7, 8, 9, "all"]:
    for c in ["A0", "A1", "A2", "G"]:
        t = tab[(lv, c)]
        if t["n"]:
            out["yield_by_class"][f"{lv}|{c}"] = dict(t)
            print(f"{lv!s:>5} {c:>4} {t['n']:6d} {100 * t['b'] / t['n']:6.2f}% {100 * t['fall'] / t['n']:5.1f}%  (b {t['b']})")
cnt = collections.Counter()
for cid, h in hist.items():
    r = h[-1][2]
    if int(r["tick"]) <= C.BOUND_RUN3:
        cnt[f"{int(r['level'])}|{r['key'][2]}"] += 1
out["eligible_by_level_class"] = dict(sorted(cnt.items()))
print("\neligible at run 3 start by level x class:", {k: v for k, v in out["eligible_by_level_class"].items() if int(k.split("|")[0]) >= 6})


def rep_at(cid, run, n):
    best = None
    for (rr, nn, r) in hist.get(cid, []):
        if (rr, nn) <= (run, n):
            best = (rr, nn, r)
    return best


print("\n== verified clears: lineage ==")
out["lineages"] = []
for run in (1, 2):
    for v in C.rows(R[run] / "verifications.jsonl"):
        if v.get("verdict") != "VERIFIED" or v.get("kind") != "clear":
            continue
        cid, n = int(v["cid"]), int(v["n"])
        chain, seen, cur = [], set(), rep_at(cid, run, n)
        while cur is not None and cid not in seen:
            seen.add(cid)
            rr, nn, r = cur
            chain.append([int(r["level"]), int(r["tick"]), r["key"][2], int(r["key"][3]), rr, nn, cid])
            par = (r.get("origin") or {}).get("parent")
            if par is None:
                break
            cid = int(par)
            cur = rep_at(cid, rr, nn)
        out["lineages"].append({"run": run, "n": n, "clear": v.get("completion_input_tick"), "chain": chain})
        print(f"run {run} n {n} clear {v.get('completion_input_tick')}: " + " <- ".join(f"L{x[0]}@{x[1]}{x[2]}" for x in chain if x[0] >= 5))

ing = {n: v["ingest"] for n, v in dlog.items()}
print("\n== run 2 verified bests: each link's ranks at the dispatch that made the next link ==")
out["links"] = []
for v in C.rows(a.r2 / "verifications.jsonl"):
    if v.get("verdict") != "VERIFIED" or v.get("kind") != "clear":
        continue
    cid, n = int(v["cid"]), int(v["n"])
    print(f"-- clear {v['completion_input_tick']} (run 2 dispatch {n})")
    child_n, cur = n, rep_at(cid, 2, n)
    while cur is not None:
        rr, made_n, r = cur
        d = dlog.get(child_n)
        wait = (ing[child_n] - ing[made_n]) if (rr == 2 and made_n in ing and child_n in ing) else None
        link = {"clear": v["completion_input_tick"], "level": int(r["level"]), "tick": int(r["tick"]), "cls": r["key"][2], "mask": int(r["key"][3]),
                "made": f"r{rr}:{made_n}", "rg": d and d["rg"], "gsize": d and d["gsize"], "rc": d and d["rc"], "csize": d and d["csize"], "wait": wait}
        out["links"].append(link)
        print(f"L{link['level']} @{link['tick']} {link['cls']} mask {link['mask']} | made {link['made']} | rg {link['rg']}/{link['gsize']} "
              f"rc {link['rc']}/{link['csize']} | wait {wait}")
        par = (r.get("origin") or {}).get("parent")
        if par is None or rr == 1:
            break
        child_n, cid = made_n, int(par)
        cur = rep_at(cid, rr, made_n)
C.dump(a, "d3_class_lineage.json", out)
