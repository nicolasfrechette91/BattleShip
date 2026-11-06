#!/usr/bin/env python3
"""DECISIVE 3 (anchors): one simulated night per group, the rank draw alone against rank draw + anchors (zero native ticks).

    python -B tools/analysis/run3_design/d3_anchor_sim.py [--lab C:/BattleShip_lab] [--out logs/run3_design]

Needs d3_dispatch_log.json (d3_anchor_replay.py). Model: run3_model.py, with exploitation at 80 % of the night (the review's
reserve, as assumed when DECISIVE 3 was decided). Variants per group:
    D1        the approved rank draw alone;
    lead_1/8  anchors with the review's "most lead" draw (highest w, then earliest tick), floor 1/8;
    rot_1/8   anchors with the rotating draw (highest w, fewest anchor bursts, earliest tick, id), floor 1/8 (APPROVED);
    rot_1/4, rot_1/16   the same with floors 1/4 and 1/16.
Prints and writes d3_anchor_sim.json: the anchors' share of draws, the 10 earliest cells' share, the draws of each class's
earliest cell and of each class's 3 earliest; plus the descendant rule's count (anchors with an earliest descendant at the next
level, and how many of those are not already anchors).
"""
import collections

import _common as C
import run3_model as M

a = C.parse(__doc__)
cells = M.load_cells(a)
dlog = M.load_dlog(a)
groups = M.eligible_groups(cells)
st = M.group_stats(dlog)
shares = M.shares(groups, st)
anc = M.class_anchors(groups, cells)

children = collections.defaultdict(list)
for cid, c in cells.items():
    if c["parent"] is not None:
        children[int(c["parent"])].append(cid)


def earliest_desc_next_level(x):
    lv = cells[x]["level"]
    best, stack, seen = None, [x], {x}
    while stack:
        y = stack.pop()
        for ch in children.get(y, []):
            if ch in seen:
                continue
            seen.add(ch)
            c = cells[ch]
            if c["level"] == lv + 1:
                if c["tick"] <= C.BOUND_RUN3 and (best is None or (c["tick"], ch) < (cells[best]["tick"], best)):
                    best = ch
            elif c["level"] == lv:
                stack.append(ch)
    return best


desc_total, desc_extra = 0, collections.defaultdict(set)
for g, al in anc.items():
    for x in al:
        dsc = earliest_desc_next_level(x)
        if dsc is not None:
            desc_total += 1
            g2 = (cells[dsc]["level"], cells[dsc]["mask"])
            if dsc not in anc.get(g2, []):
                desc_extra[C.gkey(g2)].add(dsc)
out = {"anchors": sum(len(v) for v in anc.values()), "groups": len(anc), "with_descendant": desc_total, "descendants_not_anchors": {k: len(v) for k, v in desc_extra.items()},
       "shares": {C.gkey(g): v for g, v in shares.items()}, "res": {}}
print("class anchors:", out["anchors"], "in", out["groups"], "groups; anchors with a descendant at the next level:", desc_total,
      "; not already anchors:", sum(len(v) for v in desc_extra.values()), out["descendants_not_anchors"])
VARIANTS = (("D1", None, "bursts"), ("lead_1/8", 0.125, "lead"), ("rot_1/8", 0.125, "bursts"), ("rot_1/4", 0.25, "bursts"), ("rot_1/16", 0.0625, "bursts"))
for g in sorted(groups, key=lambda x: (-x[0], x[1])):
    if len(groups[g]) < 20:
        continue
    N = M.group_draws(g, shares, beta=0.2)
    row = {"share": shares[g], "eligible": len(groups[g]), "draws": N}
    print(g, f"share {shares[g]:.3f} eligible {len(groups[g])} draws {N}")
    for name, wm, rot in VARIANTS:
        r = M.night(g, groups, cells, anc, N, w_min=wm, rotate=rot)
        disp, ids = r["draws"], r["ids"]
        first, top3 = {}, collections.Counter()
        for i, cid in enumerate(ids):
            first.setdefault(cells[cid]["cls"], i)
        pos = {cid: i for i, cid in enumerate(ids)}
        for x in anc[g]:
            top3[cells[x]["cls"]] += int(disp[pos[x]])
        x = {"anchor_share": round(r["anchor_share"], 3), "top10": round(float(disp[:10].sum()) / max(1, N), 3),
             "class_earliest": {c: int(disp[i]) for c, i in sorted(first.items())}, "class_top3": dict(sorted(top3.items()))}
        row[name] = x
        print(f"   {name:9s} anchors {x['anchor_share']:5.3f} top10 {x['top10']:5.3f} class-earliest {x['class_earliest']} class-top3 {x['class_top3']}")
    out["res"][C.gkey(g)] = row
C.dump(a, "d3_anchor_sim.json", out)
