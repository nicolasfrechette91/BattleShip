#!/usr/bin/env python3
"""DECISIVE 4b: the run 3 start recomputed in the new budget unit (level, mask, order niche). Zero native ticks, read-only.

    python -B tools/analysis/run3_design/d4b_niche_units.py [--lab C:/BattleShip_lab] [--out logs/run3_design]

Order niche of a cell row = (live-target mask of the seed its lineage starts from, the targets broken after the seed, in break
order). The lineage is exact (origin.parent_digest -> the parent row); a step that breaks two or more targets is ordered by the
producing burst's breaks_after_start ticks (ties by target id). The pre-seed order is not in the archive: seeds with the same mask
share a niche.

Replays run 2 in ingest order from run 1's final archive, attributing every dispatch to the group of the representative actually
dispatched (the row of that cell whose tick equals the dispatch's start_tick, else the current one), and counts per new group:
    n, falls, b = bursts that broke a target, bu = useful breaks (next-level arrival <= 1,220; at level 9 a claimed clear <= 1,220),
    e = new earliest arrivals in a deeper NEW group (at level 9: a claimed clear faster than every earlier claim).
Then at run 3's start (runs 1 + 2 merged, bound 1,220), per new group with eligible cells: eligible cells, classes, anchors (3
earliest eligible per class), phi = 1 / (4 x groups at the level), the warm-start rate rho0 = (200 x (bu + e) / n + 1) / 202,
DECISIVE 2's demotion (n >= 1,000, b = 0, e = 0, falls >= 75 %; also shown with bu in place of b), and the start shares
(normalised, floored at phi, demoted at phi / 4). The mask-group shares (DECISIVE 1 as approved) are printed alongside.
Also counts group moves: replacements whose new row is in another niche than the row it replaced (runs 1 and 2).
"""
import bisect
import collections

import _common as C

a = C.parse(__doc__)
K = 3
rows_by_run = {1: [], 2: []}
for run, p in ((1, a.r1), (2, a.r2)):
    for r in C.rows(p / "cells.jsonl"):
        if r.get("key"):
            r.pop("words_hex", None)
            rows_by_run[run].append(r)
bydig = {}
for run in (1, 2):
    for r in rows_by_run[run]:
        r["_run"] = run
        bydig.setdefault(r["digest"], r)
breaks_of = {}
D = {1: C.bursts(a.r1), 2: C.bursts(a.r2)}
for run in (1, 2):
    for d in D[run]:
        if d.get("breaks_after_start"):
            breaks_of[(run, int(d["n"]))] = [(int(t), int(i)) for t, i in d["breaks_after_start"]]

memo = {}
stats = collections.Counter()


def niche_of(r):
    path, cur, base = [], r, None
    while cur is not None:
        if cur["digest"] in memo:
            base = memo[cur["digest"]]
            break
        path.append(cur)
        pd = (cur.get("origin") or {}).get("parent_digest")
        cur = bydig.get(pd) if pd else None
    if base is None:
        root = path.pop()
        base = (int(root["key"][3]), ())
        memo[root["digest"]] = base
    for row in reversed(path):
        sm, order = base
        prev = sm & ~sum(1 << t for t in order)
        m = int(row["key"][3])
        gone = [i for i in range(16) if (prev >> i) & 1 and not (m >> i) & 1]
        if len(gone) >= 2:
            stats["steps_multi"] += 1
            bk = breaks_of.get((row["_run"], int(row["origin"]["n"])), [])
            when = {i: t for t, i in bk if t <= int(row["tick"])}
            gone.sort(key=lambda i: (when.get(i, 10 ** 9), i))
        elif len(gone) == 1:
            bk = breaks_of.get((row["_run"], int(row["origin"]["n"])))
            if bk is not None:
                stats["steps_single_checked"] += 1
                stats["steps_single_agree"] += int(any(i == gone[0] and t <= int(row["tick"]) for t, i in bk))
        base = (sm, order + tuple(gone))
        memo[row["digest"]] = base
    return base


def label(nk):
    return f"{nk[0]}:{'-'.join(str(t) for t in nk[1])}"


def gkey(row):
    return (int(row["level"]), int(row["key"][3]), label(niche_of(row)))


# moves in runs 1 and 2
prev_row = {}
moves = collections.Counter()
for run in (1, 2):
    for r in rows_by_run[run]:
        cid = int(r["cid"])
        if cid in prev_row:
            moves[f"run{run}_replacements"] += 1
            if gkey(prev_row[cid]) != gkey(r):
                moves[f"run{run}_moves"] += 1
                moves[f"run{run}_moves_L{int(r['level'])}"] += 1
        prev_row[cid] = r

# replay run 2 with new-unit attribution
cur = {}
hist = collections.defaultdict(list)          # cid -> rows applied so far
groups = collections.defaultdict(list)        # new group -> sorted [(tick, cid)]


def put(cid, r):
    old = cur.get(cid)
    if old is not None:
        groups[gkey(old)].remove((int(old["tick"]), cid))
    cur[cid] = r
    hist[cid].append(r)
    bisect.insort(groups[gkey(r)], (int(r["tick"]), cid))


for r in rows_by_run[1]:
    if r.get("ev") in ("new", "replaced"):
        put(int(r["cid"]), r)
best_claim = min((d["claimed"]["completion_input_tick"] for d in D[1] if d.get("claimed")), default=10 ** 9)
ev_by_n = collections.defaultdict(list)
for r in rows_by_run[2]:
    ev_by_n[int(r["origin"]["n"])].append(r)
st = collections.defaultdict(collections.Counter)
attr = collections.Counter()
for d in D[2]:
    cid = int(d["cid"])
    rep = next((x for x in reversed(hist.get(cid, [])) if int(x["tick"]) == int(d["start_tick"])), None)
    attr["by_start_tick" if rep is not None else "current_row"] += 1
    rep = rep or cur.get(cid)
    if rep is None:
        continue
    g = gkey(rep)
    lv = g[0]
    nxt = (d.get("levels") or {}).get(str(lv + 1))
    ct = (d.get("claimed") or {}).get("completion_input_tick")
    s = st[g]
    s["n"] += 1
    s["fall"] += d.get("outcome") == "fall"
    s["b"] += bool(d.get("breaks_after_start"))
    s["bu"] += (ct is not None and int(ct) <= C.BOUND_RUN3) if lv == 9 else (nxt is not None and int(nxt) <= C.BOUND_RUN3)
    e = 0
    for r in ev_by_n.get(int(d["n"]), []):
        if int(r["level"]) > lv and r.get("key"):
            g2 = gkey(r)
            if not groups[g2] or int(r["tick"]) < groups[g2][0][0]:
                e = 1
    if lv == 9 and ct is not None and int(ct) < best_claim:
        e = 1
        best_claim = int(ct)
    s["e"] += e
    for r in ev_by_n.get(int(d["n"]), []):
        if r.get("key"):
            put(int(r["cid"]), r)

# run 3 start
el = collections.defaultdict(list)
for cid, r in cur.items():
    if int(r["tick"]) <= C.BOUND_RUN3 and 6 <= int(r["level"]) <= 9:
        el[gkey(r)].append((int(r["tick"]), cid, r["key"][2]))
for v in el.values():
    v.sort()


def shares_of(level, use_bu_for_demotion=False):
    gs = sorted(g for g in el if g[0] == level)
    phi = 1 / (4 * len(gs))
    rho0 = {}
    for g in gs:
        s = st[g]
        rate = (s["bu"] + s["e"]) / s["n"] if s["n"] else None
        rho0[g] = (200 * rate + 1) / 202 if rate is not None else None
    dem = {g for g in gs if st[g]["n"] >= 1000 and st[g]["bu" if use_bu_for_demotion else "b"] == 0 and st[g]["e"] == 0
           and st[g]["fall"] >= 0.75 * st[g]["n"]}
    keep = [g for g in gs if g not in dem]
    tot = sum(rho0[g] for g in keep)
    sh = {g: max(phi, rho0[g] / tot) for g in keep}
    left = 1 - len(dem) * phi / 4
    t2 = sum(sh.values())
    out = {g: left * sh[g] / t2 for g in keep}
    out.update({g: phi / 4 for g in dem})
    return gs, phi, rho0, dem, out


res = {"moves": dict(moves), "niche_steps": dict(stats), "attribution": dict(attr), "levels": {}}
print("group moves (replacements into another niche):", dict(moves))
print("lineage steps:", dict(stats), "| dispatch attribution:", dict(attr))
for lv in (9, 8, 7, 6):
    gs, phi, rho0, dem, sh = shares_of(lv)
    _, _, _, dem_bu, sh_bu = shares_of(lv, True)
    print(f"\nlevel {lv}: {len(gs)} groups, phi = 1/(4 x {len(gs)}) = {phi:.4f}")
    print("  group (level, mask, niche)      eligible  classes  anchors | run 2: n  falls   b  bu  e | rho0     share   demoted (b) / (bu)")
    rows_ = []
    for g in sorted(gs, key=lambda g: -sh[g]):
        s = st[g]
        classes = collections.Counter(c for _t, _cid, c in el[g])
        anchors = sum(min(K, v) for v in classes.values())
        row = {"group": C.gkey(g), "eligible": len(el[g]), "earliest": el[g][0][0], "classes": dict(classes), "anchors": anchors,
               "run2": dict(s), "rho0": rho0[g], "share": sh[g], "demoted": g in dem, "demoted_if_bu": g in dem_bu, "share_if_bu": sh_bu[g]}
        rows_.append(row)
        print(f"  {str(g):32s} {len(el[g]):6d}  {'/'.join(sorted(classes)):11s} {anchors:3d} | {s['n']:5d} {s['fall'] / max(1, s['n']):5.0%} {s['b']:4d} {s['bu']:3d} {s['e']:2d} | "
              f"{rho0[g]:.5f}  {sh[g]:6.1%}  {'yes' if g in dem else 'no'} / {'yes' if g in dem_bu else 'no'}")
    res["levels"][str(lv)] = {"phi": phi, "groups": rows_}
C.dump(a, "d4b_niche_units.json", res)
