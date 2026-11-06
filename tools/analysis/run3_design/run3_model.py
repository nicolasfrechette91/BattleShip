"""The run 3 selection model used by the design simulations (DECISIVE 1-4): the start archive, group shares, anchors and one
simulated night per group. Zero native ticks; numpy.

Model (what the simulations assume, stated once):
  - start archive = runs 1 + 2 merged (last row per cell id), eligible = tick <= 1,220, levels 6-9;
  - one night = 39,309 dispatches (run 2's volume); exploitation share 1 - beta; level weights 8/15, 4/15, 2/15, 1/15 for
    levels 9, 8, 7, 6 (decay 0.5, run 2's live levels);
  - group shares = rho = (b + e + 1) / (n + 2) over the group's whole run 2 history (from d3_dispatch_log.json), normalised, floored
    at 1 / (4 x groups at the level), renormalised; demoted groups (>= 1,000 dispatches, 0 b, 0 e, >= 75 % falls) get phi / 4.
    (DECISIVE 1's 200-pseudo-dispatch warm start gives start shares within a few points of these; the D3 numbers used these.)
  - within a group: DECISIVE 1's weight (1 + rank)^-1 x max(0.05, 1 / (1 + draws of the cell)) and, when anchors are on,
    DECISIVE 3's anchors (3 earliest per class, share 0.5 x max w, halving to a floor, draw by highest w, fewest bursts, tick, id);
  - no successes and no new cells during the night (conservative: anchors stay decayed, ranks stay fixed).
"""
from __future__ import annotations

import collections
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

import _common as C

NIGHT = 39309
LVW = {9: 8 / 15, 8: 4 / 15, 7: 2 / 15, 6: 1 / 15}
K = 3


def load_cells(a) -> Dict[int, Dict[str, Any]]:
    last = {}
    for p in (a.r1, a.r2):
        for r in C.rows(p / "cells.jsonl"):
            if r.get("key"):
                last[int(r["cid"])] = r
    return {cid: {"level": int(r["level"]), "tick": int(r["tick"]), "cls": r["key"][2], "mask": int(r["key"][3]),
                  "parent": (r.get("origin") or {}).get("parent"), "digest": r.get("digest"),
                  "parent_digest": (r.get("origin") or {}).get("parent_digest")} for cid, r in last.items()}


def load_dlog(a) -> Dict[int, Dict[str, Any]]:
    return {int(k): v for k, v in json.load(open(a.out / "d3_dispatch_log.json", encoding="utf-8")).items()}


def eligible_groups(cells) -> Dict[Tuple[int, int], List[Tuple[int, int]]]:
    groups = collections.defaultdict(list)
    for cid, c in cells.items():
        if c["tick"] <= C.BOUND_RUN3 and c["level"] in LVW:
            groups[(c["level"], c["mask"])].append((c["tick"], cid))
    for el in groups.values():
        el.sort()
    return groups


def group_stats(dlog) -> Dict[Tuple[int, int], collections.Counter]:
    st = collections.defaultdict(collections.Counter)
    for d in dlog.values():
        g = tuple(d["g"])
        st[g]["n"] += 1
        st[g]["b"] += d["b"]
        st[g]["e"] += d["e"]
        st[g]["fall"] += d.get("outcome") == "fall"
    return st


def demoted(st, g) -> bool:
    s = st[g]
    return s["n"] >= 1000 and s["b"] == 0 and s["e"] == 0 and s["fall"] >= 0.75 * s["n"]


def shares(groups, st) -> Dict[Tuple[int, int], float]:
    out = {}
    for lv in LVW:
        gs = [g for g in groups if g[0] == lv]
        if not gs:
            continue
        rho = {g: (st[g]["b"] + st[g]["e"] + 1) / (st[g]["n"] + 2) for g in gs}
        tot = sum(rho.values())
        phi = 1 / (4 * len(gs))
        dem = {g for g in gs if demoted(st, g)}
        sh = {g: max(phi, rho[g] / tot) for g in gs if g not in dem}
        rest = 1 - len(dem) * phi / 4
        t2 = sum(sh.values())
        for g in gs:
            out[g] = phi / 4 if g in dem else rest * sh[g] / t2
    return out


def class_anchors(groups, cells) -> Dict[Tuple[int, int], List[int]]:
    out = {}
    for g, el in groups.items():
        per = collections.defaultdict(list)
        for _t, cid in el:
            if len(per[cells[cid]["cls"]]) < K:
                per[cells[cid]["cls"]].append(cid)
        out[g] = [cid for v in per.values() for cid in v]
    return out


def night(g, groups, cells, anchors_of, N: int, w_min: Optional[float] = 0.125, rotate: str = "bursts", s0: float = 0.5,
          seed: int = 1, disp0: Optional[np.ndarray] = None) -> Dict[str, Any]:
    """N exploitation draws in group g; returns per-cell draw counts (aligned with groups[g]) and the anchors' share."""
    el = groups[g]
    n = len(el)
    ids = [cid for _, cid in el]
    pos = {cid: i for i, cid in enumerate(ids)}
    rankw = 1.0 / (1.0 + np.arange(n))
    disp = np.zeros(n) if disp0 is None else disp0.astype(float).copy()
    base = disp.copy()
    anchors = [] if w_min is None else list(anchors_of[g])
    w = {x: 1.0 for x in anchors}
    nb = {x: 0 for x in anchors}
    rng = np.random.default_rng(seed)
    na = 0
    for _ in range(N):
        if anchors and rng.random() < s0 * max(w.values()):
            if rotate == "lead":
                x = min(anchors, key=lambda y: (-w[y], cells[y]["tick"], y))
            else:
                x = min(anchors, key=lambda y: (-w[y], nb[y], cells[y]["tick"], y))
            nb[x] += 1
            i = pos[x]
            w[x] = max(w_min, w[x] / 2)
            na += 1
        else:
            wt = rankw * np.maximum(0.05, 1.0 / (1.0 + disp))
            c = np.cumsum(wt)
            i = min(n - 1, int(np.searchsorted(c, rng.random() * c[-1], side="right")))
        disp[i] += 1
    return {"draws": disp - base, "anchor_share": na / max(1, N), "ids": ids}


def group_draws(g, shares_, beta: float = 0.0) -> int:
    return int(round(NIGHT * (1 - beta) * LVW[g[0]] * shares_[g]))
