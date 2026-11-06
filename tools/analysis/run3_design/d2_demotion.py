#!/usr/bin/env python3
"""The E7 question, the DECISIVE 1 warm-start fix and DECISIVE 2 (demotion), on run 2's dispatch rows.

    python -B tools/analysis/run3_design/d2_demotion.py [--lab C:/BattleShip_lab] [--out logs/run3_design]

Prints and writes d2_demotion.json:
  - E7: level-9 cells <= 1,220, 1,221-1,244, >= 1,245; the shortest and median observed last segment (level-9 arrival or start ->
    claimed completion) over run 2's claimed clears;
  - per group: dispatches, share of run 2's ticks, falls, breaks, clears, new earliest arrivals at the next level e, and the same
    over its last 200 dispatches with rho;
  - start shares at levels 9 and 8 under (i) the literal last-200 warm start, (ii) 200 pseudo-dispatches at the whole-run-2 rate
    (the approved fix), (iii) (ii) + demotion (>= 1,000 dispatches, 0 breaks, 0 e, >= 75 % falls -> phi / 4);
  - P(0 breaks in 1,000 dispatches) at the lowest productive level-9 rate.
Session log section 16.3 quotes these numbers.
"""
import collections

import _common as C
import run3_archive as ar

a = C.parse(__doc__)
cells, _ = ar.merged_cells([a.r1 / "cells.jsonl", a.r2 / "cells.jsonl"])
D = C.bursts(a.r2, by_n=True)
out = {}
l9 = [c["tick"] for c in cells.values() if c["level"] == 9]
out["e7"] = {"le_1220": sum(t <= 1220 for t in l9), "1221_1244": sum(1221 <= t <= 1244 for t in l9), "ge_1245": sum(t >= 1245 for t in l9)}
segs = []
for d in D:
    if d["outcome"] == "clear":
        lv = d.get("levels") or {}
        ct = (d.get("claimed") or {}).get("completion_input_tick")
        t9 = lv.get("9", d["start_tick"] if d["level"] == 9 else None)
        if ct is not None and t9 is not None:
            segs.append(int(ct) - int(t9))
out["e7"].update({"claims": len(segs), "last_segment_min": min(segs), "last_segment_median": sorted(segs)[len(segs) // 2]})
print("E7:", out["e7"])

earliest = collections.defaultdict(lambda: 10 ** 9)
for r in {r["cid"]: r for r in C.rows(a.r1 / "cells.jsonl")}.values():
    earliest[int(r["level"])] = min(earliest[int(r["level"])], int(r["tick"]))
earliest[10] = C.RUN1_BEST
hist = collections.defaultdict(list)
tot_ticks = sum(int(d["ticks"]) for d in D)
for d in D:
    g = ar.group_of(int(d["level"]), cells.get(int(d["cid"])))
    lv = int(d["level"])
    e = 0
    for k, t in (d.get("levels") or {}).items():
        k, t = int(k), int(t)
        if k == 10 and d["outcome"] == "clear":
            t = int((d.get("claimed") or {}).get("completion_input_tick") or t)
        if t < earliest[k]:
            earliest[k] = t
            if k == lv + 1:
                e = 1
    hist[g].append((bool(d.get("breaks_after_start")), e, d["outcome"] == "fall", d["outcome"] == "clear", int(d["ticks"])))
print(f"total ticks {tot_ticks:,}")
print("group | dispatches, ticks share, falls %, breaks, clears, e | last 200: falls %, breaks, e, rho")
G = {}
out["groups"] = {}
for g in sorted(hist, key=lambda g: (-g[0], -len(hist[g]))):
    h = hist[g]
    if len(h) < 100:
        continue
    w = h[-200:]
    n, b, e, f = len(h), sum(x[0] for x in h), sum(x[1] for x in h), sum(x[2] for x in h) / len(h)
    wb, we = sum(x[0] for x in w), sum(x[1] for x in w)
    rho = (wb + we + 1) / (len(w) + 2)
    G[g] = (n, b, e, f, (wb, we))
    out["groups"][C.gkey(g)] = {"n": n, "ticks_share": sum(x[4] for x in h) / tot_ticks, "falls": f, "b": b,
                                "clears": sum(x[3] for x in h), "e": e, "last200": {"falls": sum(x[2] for x in w) / len(w), "b": wb, "e": we, "rho": rho}}
    print(f"  {g}: {n}, {sum(x[4] for x in h) / tot_ticks:.1%}, {f:.0%}, {b}, {sum(x[3] for x in h)}, {e}"
          f" | {sum(x[2] for x in w) / len(w):.0%}, {wb}, {we}, {rho:.4f}")


def shares(rho, demoted=()):
    phi = 1 / (4 * len(rho))
    keep = {k: v for k, v in rho.items() if k not in demoted}
    t = sum(keep.values())
    s = {k: max(phi, v / t) for k, v in keep.items()}
    st = sum(s.values())
    left = 1 - len(demoted) * phi / 4
    res = {k: left * v / st for k, v in s.items()}
    res.update({k: phi / 4 for k in demoted})
    return res


out["start_shares"] = {}
for L in (9, 8):
    gs = {g[1]: v for g, v in G.items() if g[0] == L}
    lit = {k: (wb + we + 1) / (200 + 2) for k, (n, _b, _e, _f, (wb, we)) in gs.items()}
    pri = {k: (200 * (b + e) / n + 1) / (200 + 2) for k, (n, b, e, _f, _w) in gs.items()}
    dem = [k for k, (n, b, e, f, _w) in gs.items() if n >= 1000 and b == 0 and e == 0 and f >= 0.75]
    fmt = lambda d: ", ".join(f"{k}: {v:.0%}" for k, v in d.items())
    res = {"literal_last200": shares(lit), "pseudo200_whole_run": shares(pri), "pseudo200_plus_demotion": shares(pri, dem), "demoted": dem}
    out["start_shares"][str(L)] = res
    print(f"level {L}: (i) literal last-200 warm start: {fmt(res['literal_last200'])}")
    print(f"          (ii) whole-run-2 rate as 200 pseudo-dispatches: {fmt(res['pseudo200_whole_run'])}")
    print(f"          (iii) (ii) + demotion of {dem}: {fmt(res['pseudo200_plus_demotion'])}")
out["p_zero_breaks_1000_at_46_4879"] = (1 - 46 / 4879) ** 1000
out["p_zero_breaks_200_at_90_8027"] = (1 - 90 / 8027) ** 200
print("P(0 breaks in 1,000) at 46/4879:", f"{out['p_zero_breaks_1000_at_46_4879']:.1e}",
      "; P(0 breaks in 200) at 90/8027:", f"{out['p_zero_breaks_200_at_90_8027']:.2f}")
C.dump(a, "d2_demotion.json", out)
