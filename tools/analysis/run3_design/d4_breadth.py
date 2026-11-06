#!/usr/bin/env python3
"""DECISIVE 4 (breadth): the crossing cell, where useful breaks come from, order niches, and simulated breadth options.

    python -B tools/analysis/run3_design/d4_breadth.py [--lab C:/BattleShip_lab] [--out logs/run3_design]

Needs d3_dispatch_log.json (d3_anchor_replay.py). Zero native ticks, read-only. Prints and writes d4_breadth.json:

  A. The crossing cell: the level-7 link of the 1,245's lineage (walked by origin.parent with the representative current when each
     child was made). When it was made, every dispatch of its cell id in runs 1 and 2, how long it waited, the size of the pools a
     breadth draw would have drawn from at that moment (eligible cells at levels 6-9, at level 7, in its group, never dispatched),
     and its state at run 3's start.
  B. Useful breaks in run 2, per dispatch: u = the burst's first arrival at the next level is <= 1,220 (so it makes a cell that is
     eligible in run 3); at level 9, u = a claimed clear. By level x 100-tick bin of the dispatched cell, by class, by group-rank
     decile, by the cell's earlier dispatches; and how many breaks came from cells above 1,220 (none can be useful).
  C. Order niches: (level, the live-target mask of the run-1 seed the lineage starts from, the targets broken after it, in order),
     from the exact lineage (origin.parent_digest -> the parent row). Niches per level at run 3's start, cells per niche, run 2
     dispatches and useful breaks per niche (by the cell's current representative).
  D. One simulated night (run3_model.py; 39,309 dispatches) for exploitation = DECISIVE 1 + 3 at share 1 - beta and a breadth
     stream at share beta with one of these draws over the eligible cells (demoted groups excluded unless stated):
        U   uniform over cells;           LU  uniform level (6-9), then uniform cell;
        GU  uniform group, then cell;     EX  level weight x group share (DECISIVE 1's allocation), then uniform cell in the group;
        CB  count-based: weight 1 / (1 + dispatches in runs 1-2 + breadth draws so far) (sequential);
        ON  the review's order niches: uniform over (level, niche), then the niche's earliest cell half the time, else uniform.
     Expected useful breaks = sum over cells of draws x the run 2 rate of the cell's (group, or level for groups with < 1,000 run 2
     dispatches; 100-tick bin), and the draws of the crossing-band cells, of the demoted groups, of the crossing cell itself.
     Readings, not predictions: rates are run 2 averages under run 2's own selection; per-cell differences inside a bin are ignored.
"""
import bisect
import collections
import math

import numpy as np

import _common as C
import run3_model as M

a = C.parse(__doc__)
out = {}
cells = M.load_cells(a)
dlog = M.load_dlog(a)
groups = M.eligible_groups(cells)
st = M.group_stats(dlog)
shares = M.shares(groups, st)
anc = M.class_anchors(groups, cells)
dem_groups = {g for g in groups if M.demoted(st, g)}
D1 = C.bursts(a.r1)
D2 = C.bursts(a.r2)

# ---- A. the crossing cell ------------------------------------------------------------------------------------------------------
hist = collections.defaultdict(list)          # cid -> [(run, origin n, row without words)]
rows_all = []
for run, p in ((1, a.r1), (2, a.r2)):
    for r in C.rows(p / "cells.jsonl"):
        if r.get("key"):
            r.pop("words_hex", None)
            hist[int(r["cid"])].append((run, int((r.get("origin") or {}).get("n") or 0), r))
            rows_all.append((run, r))


def rep_at(cid, run, n):
    best = None
    for (rr, nn, r) in hist.get(cid, []):
        if (rr, nn) <= (run, n):
            best = (rr, nn, r)
    return best


best_v = min((v for v in C.rows(a.r2 / "verifications.jsonl") if v.get("verdict") == "VERIFIED" and v.get("kind") == "clear"),
             key=lambda v: v["completion_input_tick"])
chain, cid, child_n, cur = [], int(best_v["cid"]), int(best_v["n"]), None
cur = rep_at(cid, 2, child_n)
while cur is not None:
    rr, made_n, r = cur
    chain.append({"cid": cid, "level": int(r["level"]), "tick": int(r["tick"]), "cls": r["key"][2], "mask": int(r["key"][3]),
                  "made_run": rr, "made_n": made_n, "next_made_by_n": child_n})
    par = (r.get("origin") or {}).get("parent")
    if par is None or rr == 1:
        break
    child_n, cid = made_n, int(par)
    cur = rep_at(cid, rr, made_n)
x7 = [c for c in chain if c["level"] == 7][0]
X = x7["cid"]
d1_of_x = [d for d in D1 if int(d["cid"]) == X]
d2_of_x = [d for d in D2 if int(d["cid"]) == X]
run1_ingest_made = next((i for i, d in enumerate(D1, 1) if int(d["n"]) == x7["made_n"]), None)
cross_ingest = dlog[x7["next_made_by_n"]]["ingest"]
waited = (len(D1) - run1_ingest_made) + cross_ingest if run1_ingest_made else None
A = {"cell": x7, "run1_dispatches_of_cell_id": len(d1_of_x), "run2_dispatches_before_crossing": sum(1 for d in d2_of_x if d["n"] < x7["next_made_by_n"]),
     "crossing_dispatch": x7["next_made_by_n"], "crossing_outcome": next(({"outcome": d["outcome"], "levels": d.get("levels")} for d in d2_of_x if d["n"] == x7["next_made_by_n"]), None),
     "made_at_run1_ingest": run1_ingest_made, "run1_dispatches": len(D1), "crossing_at_run2_ingest": cross_ingest, "dispatches_waited": waited,
     "run2_dispatches_of_cell_id": len(d2_of_x)}

# pools at the crossing dispatch: replay run 1's final archive + run 2's events up to that ingest
pool_cells = {}
for r in C.rows(a.r1 / "cells.jsonl"):
    if r.get("key") and r.get("ev") in ("new", "replaced"):
        pool_cells[int(r["cid"])] = (int(r["level"]), int(r["tick"]), int(r["key"][3]))
ev_by_n = collections.defaultdict(list)
for r in C.rows(a.r2 / "cells.jsonl"):
    ev_by_n[int(r["origin"]["n"])].append((int(r["cid"]), int(r["level"]), int(r["tick"]), int(r["key"][3])))
disp_hist = collections.Counter(int(d["cid"]) for d in D1)
for d in D2:
    if d["n"] == x7["next_made_by_n"]:
        break
    disp_hist[int(d["cid"])] += 1
    for cid_, lv, t, m in ev_by_n.get(int(d["n"]), []):
        pool_cells[cid_] = (lv, t, m)
bound_then = dlog[x7["next_made_by_n"]]["bound"]
el_then = {c: v for c, v in pool_cells.items() if 6 <= v[0] <= 9 and v[1] <= bound_then}
A["pools_at_crossing"] = {"bound": bound_then, "eligible_l6_9": len(el_then), "eligible_l7": sum(1 for v in el_then.values() if v[0] == 7),
                          "eligible_group": sum(1 for v in el_then.values() if (v[0], v[2]) == (7, x7["mask"])),
                          "never_dispatched_eligible_l6_9": sum(1 for c in el_then if disp_hist[c] == 0),
                          "groups_l6_9": len({(v[0], v[2]) for v in el_then.values()})}
cx = cells.get(X)
el_g = groups.get((7, x7["mask"]), [])
pos = {c: i for i, (_, c) in enumerate(el_g)}
A["run3_start"] = {"tick": cx and cx["tick"], "still_978": bool(cx and cx["tick"] == x7["tick"]), "group_rank": pos.get(X), "group_eligible": len(el_g),
                   "class_rank": sum(1 for t, c in el_g if cells[c]["cls"] == x7["cls"] and (t, c) < (cx["tick"], X)) if cx else None}
out["A_crossing_cell"] = A
print("== A. the crossing cell ==")
for k, v in A.items():
    print(f"  {k}: {v}")

# ---- C0. order niches of every cell (needed by B's rate model) ---------------------------------------------------------------------
bydig = {}
for run, r in rows_all:
    bydig.setdefault(r["digest"], r)
memo = {}


def niche_of(r):
    """(seed mask, targets broken after the seed in order) of a cell row, through parent digests."""
    path = []
    cur = r
    base = None
    while cur is not None:
        d = cur["digest"]
        if d in memo:
            base = memo[d]
            break
        path.append(cur)
        pd = (cur.get("origin") or {}).get("parent_digest")
        cur = bydig.get(pd) if pd else None
    if base is None:
        root = path.pop()
        base = (int(root["key"][3]), ())
        memo[root["digest"]] = base
    for row in reversed(path):
        m = int(row["key"][3])
        sm, order = base
        prev_mask = sm & ~sum(1 << t for t in order)
        broken = tuple(i for i in range(16) if (prev_mask >> i) & 1 and not (m >> i) & 1)
        base = (sm, order + broken)
        memo[row["digest"]] = base
    return base


last_row = {}
for run, r in rows_all:
    last_row[int(r["cid"])] = r
niche = {cid: niche_of(r) for cid, r in last_row.items()}


def nlabel(nk):
    return f"{nk[0]}:{'-'.join(str(t) for t in nk[1])}"


# ---- B. useful breaks in run 2 ---------------------------------------------------------------------------------------------------
gn_n = collections.Counter()
for d in D2:
    x = dlog.get(int(d["n"]))
    if x is not None and x["cid"] in niche:
        gn_n[tuple(x["g"]) + (nlabel(niche[x["cid"]]),)] += 1
BIG = {g for g, s in st.items() if s["n"] >= 1000}
BIGN = {k for k, v in gn_n.items() if v >= 1000}


def rate_key(g, tick, cid=None):
    gn = tuple(g)[:2] + (nlabel(niche[cid]),) if cid in niche else None
    if gn in BIGN:
        return ("n",) + gn, (tick // 100) * 100
    return (("g",) + tuple(g)[:2] if tuple(g)[:2] in BIG else ("l", g[0])), (tick // 100) * 100


tabB = collections.defaultdict(collections.Counter)
rate_n = collections.defaultdict(collections.Counter)
prior = collections.Counter(int(d["cid"]) for d in D1)
useful_parents = collections.defaultdict(list)
above_bound = collections.Counter()
for d in D2:
    x = dlog.get(int(d["n"]))
    if x is None:
        continue
    lv, g = x["g"][0], tuple(x["g"])
    nxt = (d.get("levels") or {}).get(str(lv + 1))
    u = int(d.get("outcome") == "clear") if lv == 9 else int(nxt is not None and int(nxt) <= C.BOUND_RUN3)
    k = prior[int(d["cid"])]
    prior[int(d["cid"])] += 1
    pb = "0" if k == 0 else "1" if k == 1 else "2-4" if k < 5 else "5-19" if k < 20 else "20+"
    for key in ((lv, "tick", (x["tick"] // 100) * 100), (lv, "cls", x["cls"]), (lv, "decile", min(9, int(10 * x["rg"] / max(1, x["gsize"])))),
                (lv, "prior", pb)):
        t = tabB[key]
        t["n"] += 1
        t["b"] += x["b"]
        t["u"] += u
    rk = rate_key(g, x["tick"], x["cid"])
    rate_n[rk]["n"] += 1
    rate_n[rk]["u"] += u
    if u and lv < 9:
        useful_parents[g].append(x["tick"])
    if x["tick"] > C.BOUND_RUN3:
        above_bound[f"L{lv}_dispatches"] += 1
        above_bound[f"L{lv}_breaks"] += x["b"]
        above_bound[f"L{lv}_useful_or_clear"] += u
out["B_useful"] = {f"{k[0]}|{k[1]}|{k[2]}": dict(v) for k, v in sorted(tabB.items(), key=lambda kv: (str(kv[0][0]), kv[0][1], str(kv[0][2])))}
out["B_above_bound"] = dict(above_bound)
band = {}
for g, ts in useful_parents.items():
    ts.sort()
    band[C.gkey(g)] = {"useful": len(ts), "tick_min": ts[0], "tick_q10": ts[len(ts) // 10], "tick_median": ts[len(ts) // 2], "tick_q90": ts[9 * len(ts) // 10], "tick_max": ts[-1]}
out["B_useful_parent_ticks"] = band
print("\n== B. useful breaks in run 2 (u = next-level arrival <= 1,220; level 9: a claimed clear) ==")
for lv in (6, 7, 8, 9):
    for kind in ("tick", "decile", "cls", "prior"):
        ks = sorted((k for k in tabB if k[0] == lv and k[1] == kind), key=lambda k: str(k[2]) if kind in ("cls", "prior") else k[2])
        print(f"  L{lv} {kind:6s} " + " | ".join(f"{k[2]}: {tabB[k]['n']}/{tabB[k]['u']}" for k in ks))
print("  dispatches of cells above 1,220 (level 9: claimed clears, all >= 1,245):", dict(sorted(above_bound.items())))
print("  ticks of the cells whose bursts were useful, per group:", band)


def rate(g, tick, cid=None):
    k = rate_key(g, tick, cid)
    n, u = rate_n[k]["n"], rate_n[k]["u"]
    if n < 20 and k[0][0] == "n":
        k = rate_key(g, tick, None)
        n, u = rate_n[k]["n"], rate_n[k]["u"]
    if n < 20:
        lk = (("l", g[0]), k[1])
        n, u = rate_n[lk]["n"] + n, rate_n[lk]["u"] + u
        if n < 20:
            return 0.0
    return (u + 0.5) / (n + 1)


# ---- C. order niches -------------------------------------------------------------------------------------------------------------
seeds = collections.Counter((int(r["level"]), int(r["key"][3])) for run, r in rows_all if (r.get("origin") or {}).get("kind") == "seed")
nic_cells = collections.defaultdict(list)
for g, el in groups.items():
    for t, cid in el:
        nic_cells[(g[0],) + niche[cid]].append((t, cid))
for v in nic_cells.values():
    v.sort()
nd = collections.defaultdict(collections.Counter)
for d in D2:
    x = dlog.get(int(d["n"]))
    if x is None or x["cid"] not in niche:
        continue
    key = (x["g"][0],) + niche[x["cid"]]
    lv = x["g"][0]
    nxt = (d.get("levels") or {}).get(str(lv + 1))
    nd[key]["n"] += 1
    nd[key]["b"] += x["b"]
    nd[key]["fall"] += d.get("outcome") == "fall"
    nd[key]["u"] += int(d.get("outcome") == "clear") if lv == 9 else int(nxt is not None and int(nxt) <= C.BOUND_RUN3)
C_ = {"seeds_by_level_mask": {f"{k[0]}|{k[1]}": v for k, v in sorted(seeds.items())}, "per_level": {}}
print("\n== C. order niches at run 3's start (eligible cells) ==")
print("  run 1 seeds by (level, mask):", dict(seeds))
for lv in (6, 7, 8, 9):
    ks = sorted((k for k in nic_cells if k[0] == lv), key=lambda k: -len(nic_cells[k]))
    rowsC = [{"niche": nlabel(k[1:]), "groups": sorted({C.gkey((cells[c]["level"], cells[c]["mask"])) for _t, c in nic_cells[k]}), "cells": len(nic_cells[k]),
              "earliest": nic_cells[k][0][0], "run2_dispatches": nd[k]["n"], "run2_breaks": nd[k]["b"], "run2_useful": nd[k]["u"], "run2_falls": nd[k]["fall"]} for k in ks]
    C_["per_level"][str(lv)] = rowsC
    print(f"  L{lv}: {len(ks)} niches")
    for r_ in rowsC:
        print(f"     {r_['niche']:12s} groups {r_['groups']} cells {r_['cells']} earliest {r_['earliest']} | run 2 dispatches {r_['run2_dispatches']} breaks {r_['run2_breaks']} useful {r_['run2_useful']} falls {r_['run2_falls']}")
    small = [r_ for r_ in rowsC if r_["cells"] <= 20]
    print(f"       niches with <= 20 cells: {len(small)}, their run 2 dispatches {sum(r_['run2_dispatches'] for r_ in small)}, useful {sum(r_['run2_useful'] for r_ in small)}")
out["C_niches"] = C_

# ---- D. simulated options ---------------------------------------------------------------------------------------------------------
all_el = [(g, t, cid) for g, el in groups.items() for t, cid in el]
idx = {cid: i for i, (_g, _t, cid) in enumerate(all_el)}
lev = np.array([g[0] for g, _t, _c in all_el])
rate_v = np.array([rate(g, t, c) for g, t, c in all_el])
is_dem = np.array([g in dem_groups for g, _t, _c in all_el])
G7 = (7, 322)
b7 = band.get(C.gkey(G7))
in_band = np.array([g == G7 and b7 is not None and b7["tick_q10"] <= t <= b7["tick_q90"] for g, t, _c in all_el])
nic_of_el = [nlabel(niche[c]) for _g, _t, c in all_el]
n7 = sorted({nic_of_el[i] for i, (g, _t, _c) in enumerate(all_el) if g == G7})
hist_disp = collections.Counter(int(d["cid"]) for d in D1 + D2)
h0 = np.array([hist_disp[c] for _g, _t, c in all_el], float)

# niche groups: (level, mask, order niche) as the budget unit (an alternative to DECISIVE 1's (level, mask))
groups_n = collections.defaultdict(list)
for g, t, c in all_el:
    groups_n[g + (nlabel(niche[c]),)].append((t, c))
for v in groups_n.values():
    v.sort()
st_n = collections.defaultdict(collections.Counter)
for dd in dlog.values():
    if dd["cid"] in niche:
        k = tuple(dd["g"]) + (nlabel(niche[dd["cid"]]),)
        st_n[k]["n"] += 1
        st_n[k]["b"] += dd["b"]
        st_n[k]["e"] += dd["e"]
        st_n[k]["fall"] += dd.get("outcome") == "fall"
shares_n = M.shares(groups_n, st_n)
anc_n = M.class_anchors(groups_n, cells)
# the same with rho counting only useful breaks (next-level arrival <= 1,220; at level 9 a claimed clear) instead of every break
u_by_n = {}
for d in D2:
    x = dlog.get(int(d["n"]))
    if x is not None:
        nxt = (d.get("levels") or {}).get(str(x["g"][0] + 1))
        u_by_n[int(d["n"])] = int(d.get("outcome") == "clear") if x["g"][0] == 9 else int(nxt is not None and int(nxt) <= C.BOUND_RUN3)
st_nu = collections.defaultdict(collections.Counter)
for n_, dd in dlog.items():
    if dd["cid"] in niche:
        k = tuple(dd["g"]) + (nlabel(niche[dd["cid"]]),)
        st_nu[k]["n"] += 1
        st_nu[k]["b"] += u_by_n.get(n_, 0)
        st_nu[k]["e"] += dd["e"]
        st_nu[k]["fall"] += dd.get("outcome") == "fall"
shares_nu = M.shares(groups_n, st_nu)
dem_n = sorted(C.gkey(g) for g in groups_n if M.demoted(st_n, g))
out["D_niche_groups"] = {C.gkey(g): {"cells": len(v), "share": shares_n[g], "run2": dict(st_n[g])} for g, v in groups_n.items()}
print("\n== D0. niche groups (level, mask, niche): start shares (normalised then floored, demotion) ==")
for g in sorted(groups_n, key=lambda g: (-g[0], -len(groups_n[g]))):
    print(f"  {g}: cells {len(groups_n[g])} share {shares_n[g]:.3f} (useful-break rho: {shares_nu[g]:.3f}) run 2 {dict(st_n[g])}")
print("  demoted:", dem_n)


def exploitation(beta, gset="mask", seed=1):
    gs, sh, an = {"mask": (groups, shares, anc), "niche": (groups_n, shares_n, anc_n), "niche_u": (groups_n, shares_nu, anc_n)}[gset]
    v = np.zeros(len(all_el))
    for g in gs:
        N = M.group_draws(g, sh, beta)
        if N <= 0:
            continue
        r = M.night(g, gs, cells, an, N, w_min=0.125, rotate="bursts", seed=seed)
        for k, cid in enumerate(r["ids"]):
            v[idx[cid]] += r["draws"][k]
    return v


def breadth_p(rule, include_demoted=False):
    ok = np.ones(len(all_el), bool) if include_demoted else ~is_dem
    p = np.zeros(len(all_el))
    gsz = collections.Counter(g for (g, _t, _c), o in zip(all_el, ok) if o)
    lsz = collections.Counter(g[0] for (g, _t, _c), o in zip(all_el, ok) if o)
    if rule == "U":
        p[ok] = 1 / ok.sum()
    elif rule == "LU":
        for i, (g, _t, _c) in enumerate(all_el):
            if ok[i]:
                p[i] = 1 / len(lsz) / lsz[g[0]]
    elif rule == "GU":
        for i, (g, _t, _c) in enumerate(all_el):
            if ok[i]:
                p[i] = 1 / len(gsz) / gsz[g]
    elif rule == "ON":
        keys = []
        for k, members in nic_cells.items():
            mm = [c for _t, c in members if include_demoted or (cells[c]["level"], cells[c]["mask"]) not in dem_groups]
            if mm:
                keys.append(mm)
        for mm in keys:
            for j, c in enumerate(mm):
                p[idx[c]] += (1 / len(keys)) * ((0.5 if j == 0 else 0.0) + 0.5 / len(mm))
    return p


def breadth_cb(n_draws, expl, include_demoted=False, seed=1):
    """Count-based: weight 1 / (1 + every dispatch of the cell: runs 1-2 and this night's exploitation and breadth so far)."""
    rng = np.random.default_rng(seed)
    ok = np.ones(len(all_el), bool) if include_demoted else ~is_dem
    h = h0 + expl
    v = np.zeros(len(all_el))
    w = np.where(ok, 1 / (1 + h), 0.0)
    for _ in range(n_draws):
        c = np.cumsum(w)
        i = min(len(w) - 1, int(np.searchsorted(c, rng.random() * c[-1], side="right")))
        v[i] += 1
        h[i] += 1
        w[i] = 1 / (1 + h[i])
    return v


def metrics(draws, name, beta):
    m = {"name": name, "beta": beta, **{f"u{lv}": float((draws * rate_v)[lev == lv].sum()) for lv in (6, 7, 8, 9)}}
    m["band_7_322"] = float(draws[in_band].sum())
    m["niches_7_322"] = {nk: float(sum(draws[i] for i in range(len(all_el)) if all_el[i][0] == G7 and nic_of_el[i] == nk)) for nk in n7}
    m["demoted_draws"] = float(draws[is_dem].sum())
    m["crossing_key_draws"] = float(draws[idx[X]]) if X in idx else None
    for gname, g in (("top10_9_2", (9, 2)), ("top10_9_256", (9, 256))):
        m[gname] = float(sum(draws[idx[c]] for _t, c in groups[g][:10]))
    for gname, g in (("anchorsA2G_7_322", (7, 322)), ("anchorsA2G_8_258", (8, 258))):
        m[gname] = float(sum(draws[idx[c]] for c in anc[g] if cells[c]["cls"] in ("A2", "G")))
    m["draws_by_level"] = {f"L{lv}": round(float(draws[lev == lv].sum())) for lv in (6, 7, 8, 9)}
    return m


res = []
run2_u = collections.Counter()
run2_band = 0
run2_n7 = collections.Counter()
for d in D2:
    x = dlog.get(int(d["n"]))
    if x is None:
        continue
    lv = x["g"][0]
    nxt = (d.get("levels") or {}).get(str(lv + 1))
    run2_u[f"u{lv}"] += int(d.get("outcome") == "clear") if lv == 9 else int(nxt is not None and int(nxt) <= C.BOUND_RUN3)
    if tuple(x["g"]) == G7:
        run2_band += int(b7["tick_q10"] <= x["tick"] <= b7["tick_q90"])
        if x["cid"] in niche:
            run2_n7[nlabel(niche[x["cid"]])] += 1
res.append({"name": "run 2 actual", "beta": None, **{k: float(v) for k, v in run2_u.items()}, "band_7_322": float(run2_band),
            "niches_7_322": dict(run2_n7)})
for gset in ("mask", "niche", "niche_u"):
    for beta in (0.0, 0.1, 0.2, 0.3):
        ex = exploitation(beta, gset)
        nb = int(round(M.NIGHT * beta))
        tag = {"mask": "", "niche": " [niche groups]", "niche_u": " [niche, useful rho]"}[gset]
        if beta == 0.0:
            res.append(metrics(ex, f"no breadth{tag}", beta))
            continue
        rules = ("U", "LU", "GU", "ON", "CB") if gset == "mask" else ("U", "CB")
        for rule in rules:
            bd = breadth_cb(nb, ex) if rule == "CB" else nb * breadth_p(rule)
            res.append(metrics(ex + bd, f"{rule}{tag}", beta))
        if gset == "mask":
            res.append(metrics(ex + nb * breadth_p("U", include_demoted=True), "U + demoted", beta))
            res.append(metrics(ex + breadth_cb(nb, ex, include_demoted=True), "CB + demoted", beta))
out["D_options"] = res

# retrospective: the crossing cell at the moment it crossed (run 2 pools): expected dispatches until a breadth draw reaches it
P_ = A["pools_at_crossing"]
retro = {}
for beta in (0.1, 0.2, 0.3):
    retro[str(beta)] = {"U": round(P_["eligible_l6_9"] / beta), "LU": round(4 * P_["eligible_l7"] / beta),
                        "GU": round(P_["groups_l6_9"] * P_["eligible_group"] / beta),
                        "CB_never_dispatched_first": round(P_["never_dispatched_eligible_l6_9"] / beta)}
retro["actual_run1_run2"] = A["dispatches_waited"]
out["D_retro_waits"] = retro
print("\n== D. one simulated night (39,309 dispatches): expected useful breaks u6 / u7 / u8 / clears; (7,322) band and niches; demoted; cost ==")
for m in res:
    if m.get("beta") is None:
        print(f"  run 2 actual: u {m.get('u6', 0):.0f} / {m.get('u7', 0):.0f} / {m.get('u8', 0):.0f} / {m.get('u9', 0):.0f} | band {m['band_7_322']:.0f} | niches {m['niches_7_322']}")
        continue
    print(f"  b {m['beta']:.1f} {m['name']:22s} u {m['u6']:5.1f} / {m['u7']:5.1f} / {m['u8']:5.1f} / {m['u9']:5.1f} | band {m['band_7_322']:5.0f} | niches "
          + " ".join(f"{k} {v:.0f}" for k, v in m["niches_7_322"].items())
          + f" | dem {m['demoted_draws']:4.0f} | key {m['crossing_key_draws']:.2f} | top10 (9,2) {m['top10_9_2']:4.0f} (9,256) {m['top10_9_256']:4.0f}"
          f" | A2+G anch (7,322) {m['anchorsA2G_7_322']:3.0f} (8,258) {m['anchorsA2G_8_258']:3.0f} | {m['draws_by_level']}")
print("\n== D. the crossing cell at the moment it crossed: dispatches until a breadth draw reaches it ==")
for k, v in retro.items():
    print(f"  {k}: {v}")
C.dump(a, "d4_breadth.json", out)
