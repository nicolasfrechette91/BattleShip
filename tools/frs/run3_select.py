#!/usr/bin/env python3
"""Run 3 selection (2026-11-06 session, step 8; the decisions are SESSION_LOG_2026-11-04.md section 16 and
docs/rl_decisions_2026-11-04.md section 5). Pure: no process, no file, no clock. The engine (tools/frs/crossing_search_run3.py) calls
`select` with its keyed uniforms (tools/frs/det_schedule.KeyedRandom), `on_dispatch` when the job is sent and `on_ingest` at the
in-order ingest of the result, so every decision here is a function of the plan, the parameters, the seed and the reorder window.

    order niche     (the mask of the run 1 seed a representative's lineage starts from, the targets broken after the seed in break
                    order). A child = its parent representative's niche + the targets its burst broke at or before the child's tick
                    (break tick, then target id; the targets are the ones the parent's mask has and the child's has not, as in
                    tools/analysis/run3_design/d4b_niche_units.py). Same-mask seeds share a niche (the pre-seed order is not archived).
    group           (level, mask, niche label) of a cell's CURRENT representative; level and mask never change, so a cell moves only
                    when a replacement's lineage has another order (DECISIVE 4b). History stays with the group dispatched.
    streams         per dispatch: with probability breadth_share (0.2) a breadth draw (DECISIVE 4), otherwise exploitation:
                    a level (decay 0.5 from the deepest eligible level; or, owner 2026-11-09, `level_weights` w[k] for the level k below the
                    deepest eligible one, levels past the list at 0), a group by its share, then an anchor (DECISIVE 3) with
                    probability anchor_share x w_max, else the rank draw (DECISIVE 1). When no cell is eligible for breadth the
                    dispatch falls back to exploitation (recorded).
    shares          (with an inherited run 3 folder, owner 2026-11-09, rule a: the window starts as the group's last 200 REAL dispatches of
                    runs 2 and 3 with u at this run's bound, the front padded with its whole-history rate; otherwise as follows)
                    rho = (sum of the window + 1) / (window length + 2); the window holds the group's last 200 dispatches, each
                    worth u + e (u: a useful break, next-level arrival <= the bound, at level 9 a claimed clear <= the bound; e: a new
                    earliest arrival in a deeper group, at level 9 a claimed clear faster than every earlier claim). It starts as 200
                    pseudo-dispatches at the group's whole-run-2 rate (u + e) / n, or, for a group with no history, at its level's
                    pooled rate (the windows of the level's groups; else every level's; else 0). Normalised over the non-demoted
                    groups, floored at phi = phi_factor / (groups at the level), rescaled to 1 - (demoted) x phi / 4; a demoted
                    group gets phi x demote_share_factor (DECISIVE 1, the warm-start fix, 4b rule 2).
    demotion        (owner 2026-11-08, replacing the whole-history rule) the group's LAST demote_min_dispatches (1,000) dispatches, run 2
                    then run 3 in ingest order: the window full, 0 bursts that broke a target (any break, 4b rule 3), 0 e, falls >= 75 %
                    of the window. Exit: the condition stops holding (a break or an e enters, or the falls drop below 75 %). Events
                    logged with the window's counters. A burst whose kept cells give a DEMOTED group a new earliest eligible cell (earlier
                    than every alive cell of that group before the burst) queues that cell (one per group per burst) with
                    trigger_draws_per_cell (3) draws through the trigger queue (class demoted_new_earliest, same cap).
    cell weight     (1 + rank)^-rank_exp x max(novelty_floor, 1 / (1 + dispatches selected since the representative was set))
                    x cleared_weight^(claimed clears of the representative); rank = position by (tick, cell id) among the group's
                    eligible cells. The staleness count is taken when a dispatch is SELECTED (deterministic under D4), so the
                    reorder window does not hand one cell ten draws in a row.
    anchors         the anchor_k (3) earliest eligible cells of each resource class in each group. A new anchor (a cell that becomes
                    one, or an anchor whose representative is replaced, 4b rule 1) starts at w 1 and 0 bursts. An anchor draw picks
                    the highest w, then the fewest anchor bursts, then the earliest tick, then the cell id; its burst count grows when
                    it is selected; at ingest w resets to 1 on success (the burst kept a cell at a deeper level that is an anchor
                    of its group; at level 9 a claimed clear faster than every earlier claim) or halves, floor 1/8. Only anchor
                    draws update w and bursts.
    breadth         count-based: weight 1 / (1 + dispatches of the cell id in runs 1-3, counted when selected), over the eligible
                    cells of the non-demoted groups, cumulative in cell-id order.
    triggers        a burst with an event of a trigger class (default line_crossing, inside_solid, floor_switch_unlinked, nonfinite)
                    seen in fewer than trigger_rarity (3) earlier bursts of the run queues, for a detector class, its kept (new or
                    replaced), eligible cells whose tick is >= the event's first state (step_from + 1: the state before the
                    anomalous transition); when there is none, and for a non-finite reply (the burst is cut before it), the burst's
                    last kept eligible cell, or the dispatched cell when it kept none (owner 2026-11-06: rule b, then the same
                    fallback for detector classes); trigger_draws_per_cell (3) breadth draws each, served in turn;
                    a breadth slot serves the queue while trigger draws stay <= trigger_cap (10 %) of breadth draws. Entries whose
                    cell was replaced or became ineligible are dropped (counted). Demotion does not exclude a triggered cell.

Standard library only. No coordinate, target id, route or tick is in any rule.
"""
from __future__ import annotations

import bisect
import math
from collections import Counter, deque
from typing import Any, Deque, Dict, List, Mapping, Optional, Sequence, Set, Tuple

SELECT_CONTRACT = "run3_select_v2"            # v2 (owner 2026-11-08): rolling demotion window + new earliest cells of demoted groups
TARGETS_TOTAL = 10
NEW, REPLACED = "new", "replaced"
STREAMS = ("rank", "anchor", "breadth", "trigger")
NONFINITE = "nonfinite"
HIST_FIELDS = ("n", "fall", "b", "bu", "e")
LANDING_CLASS = "demoted_new_earliest"


def window_code(fall: int, b: int, e: int) -> int:
    """One dispatch in the demotion window: bit 0 fall, bit 1 a break, bit 2 an e (a digit 0-7 in the plan's tails)."""
    return (1 if fall else 0) | (2 if b else 0) | (4 if e else 0)
Niche = Tuple[int, Tuple[int, ...]]
GKey = Tuple[int, int, str]


# -- niches ---------------------------------------------------------------------------------------------------------------------------


def niche_label(n: Niche) -> str:
    return f"{int(n[0])}:{'-'.join(str(int(t)) for t in n[1])}"


def glabel(g: GKey) -> str:
    return f"{g[0]}|{g[1]}|{g[2]}"


def seed_niche(mask: int) -> Niche:
    return (int(mask), ())


def child_niche(parent: Niche, child_mask: int, child_tick: int, breaks_post: Optional[Sequence[Sequence[int]]],
                stats: Optional[Counter] = None) -> Niche:
    """The parent's niche + the targets the parent's mask has and the child's has not, ordered by the burst's break tick (at or before
    the child's tick; a target without one last), then target id. `breaks_post` = the burst's [[tick, target id]] after its start."""
    sm, order = int(parent[0]), tuple(parent[1])
    prev = sm & ~sum(1 << int(t) for t in order)
    m = int(child_mask)
    gone = [i for i in range(16) if (prev >> i) & 1 and not (m >> i) & 1]
    if stats is not None and m & ~prev:
        stats["mask_regrowth"] += 1
    if len(gone) >= 2:
        if stats is not None:
            stats["steps_multi"] += 1
        when = {int(i): int(t) for t, i in (breaks_post or []) if int(t) <= int(child_tick)}
        gone.sort(key=lambda i: (when.get(i, 10 ** 9), i))
    elif len(gone) == 1 and stats is not None and breaks_post is not None:
        stats["steps_single_checked"] += 1
        stats["steps_single_agree"] += int(any(int(i) == gone[0] and int(t) <= int(child_tick) for t, i in breaks_post))
    return (sm, order + tuple(gone))


# -- the selector -----------------------------------------------------------------------------------------------------------------------------


def _new_period() -> Dict[str, Any]:
    return {"dispatches": 0, "ingested": 0, "by_group": {}, "by_level": Counter(), "streams": Counter(), "breadth_by_level": Counter(),
            "breadth_by_group": Counter(), "breadth_by_niche": Counter(), "useful": Counter(), "e": Counter(), "breaks": Counter(),
            "moves": 0, "move_samples": [], "events": [], "triggers": [], "trigger_dropped": 0, "fallback_exploit": 0,
            "anchor_successes": Counter(), "anchor_bursts_ingested": Counter(),
            "ingested_by_level": Counter(), "useful_by_level": Counter(), "e_by_level": Counter()}


class Run3Selector:
    """The run 3 draw and its state. `archive`: the engine's archive (cells, eligible(), bound); `p`: Params3 (crossing_search_run3)."""

    def __init__(self, archive: Any, p: Any, *, niches: Mapping[int, Niche], history: Mapping[Any, Mapping[str, int]],
                 cid_dispatches: Mapping[int, int], best_claim: Optional[int], history_tails: Optional[Mapping[Any, str]] = None,
                 history_windows: Optional[Mapping[Any, str]] = None):
        self.a = archive
        self.p = p
        self.bound = int(archive.bound)
        self.W = int(p.window)
        self.niche: Dict[int, Niche] = {int(k): (int(v[0]), tuple(int(t) for t in v[1])) for k, v in niches.items()}
        self.group: Dict[int, GKey] = {}
        self.tick_of: Dict[int, int] = {}
        self.gall: Dict[GKey, List[Tuple[int, int]]] = {}
        self._mem: Dict[GKey, List[int]] = {}
        self.hist: Dict[GKey, Counter] = {}
        for g, h in history.items():
            gk = tuple(g) if not isinstance(g, str) else _parse_glabel(g)
            self.hist[(int(gk[0]), int(gk[1]), str(gk[2]))] = Counter({k: int(h.get(k, 0)) for k in HIST_FIELDS})
        self.hist_start = {g: dict(h) for g, h in self.hist.items()}
        self.DW = int(p.demote_min_dispatches)
        self.dwin: Dict[GKey, Deque[int]] = {}
        self.dcnt: Dict[GKey, List[int]] = {}                  # [falls, breaks, e] over the window
        tails = {(tuple(g) if not isinstance(g, str) else _parse_glabel(g)): str(t) for g, t in (history_tails or {}).items()}
        for g, h in self.hist.items():                         # every group with a history has its sequence, and they agree
            t = tails.get(g, "")
            codes = [int(ch) for ch in t]
            if len(codes) != h["n"] or sum(c & 1 for c in codes) != h["fall"] or sum((c >> 1) & 1 for c in codes) != h["b"] \
                    or sum((c >> 2) & 1 for c in codes) != h["e"]:
                raise ValueError(f"group {glabel(g)}: its history sequence ({len(codes)} codes) does not match its counters {dict(h)}")
            for c in codes[-self.DW:]:
                self._push(g, c)
        self.real_windows: Optional[Dict[GKey, str]] = None    # rule a (owner 2026-11-09): with an inherited run, the D1 window is real
        if history_windows is not None:
            self.real_windows = {(tuple(g) if not isinstance(g, str) else _parse_glabel(g)): str(w) for g, w in history_windows.items()}
            for g, h in self.hist.items():
                w = self.real_windows.get(g, "")
                if len(w) != h["n"] or sum(int(ch) for ch in w) != h["bu"] + h["e"]:
                    raise ValueError(f"group {glabel(g)}: its D1 window values ({len(w)}) do not match its counters {dict(h)}")
        self.hist3: Dict[GKey, Counter] = {}
        self.win: Dict[GKey, Deque[float]] = {}
        self.warm: Dict[GKey, Dict[str, Any]] = {}
        self.dem: Set[GKey] = set()
        self.anchors: Dict[GKey, List[int]] = {}
        self.anc: Dict[int, Dict[str, Any]] = {}
        self.stale: Dict[int, int] = {}
        self.bcount: Dict[int, int] = {int(k): int(v) for k, v in cid_dispatches.items()}
        self.best_claim = int(best_claim) if best_claim is not None else None
        self.tq: Deque[List[Any]] = deque()
        self.trig_seen: Counter = Counter()
        self.triggers: List[Dict[str, Any]] = []
        self.cnt: Counter = Counter()
        self.events: List[Dict[str, Any]] = []
        self.niche_stats: Counter = Counter()
        self.period = _new_period()
        self.cum = {"streams": Counter(), "useful": Counter(), "e": Counter(), "breaks": Counter(), "dispatches_by_group": Counter(),
                    "ingested_by_level": Counter(), "useful_by_level": Counter(), "e_by_level": Counter()}
        self._pool: Optional[List[int]] = None
        self.n_ingested = 0
        for c in archive.cells:
            if self._indexable(c):
                if c.cid not in self.niche:
                    raise ValueError(f"cell {c.cid} has no order niche")
                self._insert(c)
        with_history = [g for g in sorted(self.gall) if self.hist.get(g, Counter()).get("n", 0) > 0]
        for g in with_history + [g for g in sorted(self.gall) if g not in set(with_history)]:
            self._ensure_window(g)                                   # history first: a group without one starts at the pooled rate
        self.dem = {g for g in self.gall if self._demoted(g)}
        for g in sorted(self.gall):
            self._recompute_anchors(g)
        self.start = self.table()

    # -- membership -------------------------------------------------------------------------------------------------------------------------

    @staticmethod
    def _indexable(c: Any) -> bool:
        return c.alive() and c.level < TARGETS_TOTAL and c.key is not None

    def gkey_of(self, c: Any, niche: Optional[Niche] = None) -> GKey:
        return (int(c.level), int(c.key[3]), niche_label(niche if niche is not None else self.niche[c.cid]))

    def _insert(self, c: Any) -> GKey:
        g = self.gkey_of(c)
        bisect.insort(self.gall.setdefault(g, []), (int(c.tick), int(c.cid)))
        self.group[c.cid] = g
        self.tick_of[c.cid] = int(c.tick)
        self._mem.pop(g, None)
        self._pool = None
        return g

    def _remove(self, cid: int) -> Optional[GKey]:
        g = self.group.pop(cid, None)
        if g is None:
            return None
        lst = self.gall[g]
        i = bisect.bisect_left(lst, (self.tick_of[cid], cid))
        if i >= len(lst) or lst[i] != (self.tick_of[cid], cid):
            raise RuntimeError(f"cell {cid} is not where its group index says ({g}, tick {self.tick_of[cid]})")
        del lst[i]
        self.tick_of.pop(cid, None)
        self._mem.pop(g, None)
        self._pool = None
        return g

    def members(self, g: GKey) -> List[int]:
        """The group's eligible cells in rank order (tick, cell id)."""
        m = self._mem.get(g)
        if m is None:
            m = []
            for t, cid in self.gall.get(g, []):
                if t > self.bound:
                    break
                if self.a.eligible(self.a.cells[cid]):
                    m.append(cid)
            self._mem[g] = m
        return m

    def levels(self) -> Dict[int, List[GKey]]:
        out: Dict[int, List[GKey]] = {}
        for g in sorted(self.gall):
            if self.members(g):
                out.setdefault(g[0], []).append(g)
        return out

    # -- shares -----------------------------------------------------------------------------------------------------------------------------

    def _pooled(self, level: int) -> Tuple[float, str]:
        for scope in ("level", "all"):
            ws = [w for g, w in self.win.items() if scope == "all" or g[0] == level]
            n = sum(len(w) for w in ws)
            if n:
                return sum(sum(w) for w in ws) / n, scope
        return 0.0, "none"

    def _ensure_window(self, g: GKey) -> None:
        if g in self.win:
            return
        h = self.hist.get(g)
        if self.real_windows is not None and h and h["n"] > 0:          # rule a: the last W real values, the front padded with the whole-history rate
            vals = [float(int(ch)) for ch in self.real_windows.get(g, "")[-self.W:]]
            rate = (h["bu"] + h["e"]) / h["n"]
            self.win[g] = deque([rate] * (self.W - len(vals)) + vals)
            self.warm[g] = {"rate": rate, "source": "real_window", "real": len(vals), "at_ingest": self.n_ingested}
            self.hist.setdefault(g, Counter({k: 0 for k in HIST_FIELDS}))
            return
        if h and h["n"] > 0:
            rate, src = (h["bu"] + h["e"]) / h["n"], "run2"
        else:
            rate, scope = self._pooled(g[0])
            src = f"pooled_{scope}"
        self.win[g] = deque([rate] * self.W)
        self.warm[g] = {"rate": rate, "source": src, "at_ingest": self.n_ingested}
        self.hist.setdefault(g, Counter({k: 0 for k in HIST_FIELDS}))

    def rho(self, g: GKey) -> float:
        w = self.win[g]
        return (sum(w) + 1.0) / (len(w) + 2.0)

    def shares(self, level: int, gs: Optional[Sequence[GKey]] = None) -> Tuple[Dict[GKey, float], float]:
        if gs is None:
            gs = self.levels().get(level, [])
        gs = sorted(gs)
        if not gs:
            return {}, 0.0
        p = self.p
        phi = p.phi_factor / len(gs)
        dem = [g for g in gs if g in self.dem]
        keep = [g for g in gs if g not in self.dem]
        out: Dict[GKey, float] = {}
        if keep:
            rho = {g: self.rho(g) for g in keep}
            tot = sum(rho.values())
            sh = {g: max(phi, rho[g] / tot) for g in keep}
            left = 1.0 - len(dem) * phi * p.demote_share_factor
            t2 = sum(sh.values())
            out = {g: left * sh[g] / t2 for g in keep}
        out.update({g: phi * p.demote_share_factor for g in dem})
        return out, phi

    # -- demotion -----------------------------------------------------------------------------------------------------------------------------

    def _push(self, g: GKey, code: int) -> None:
        w = self.dwin.setdefault(g, deque())
        c = self.dcnt.setdefault(g, [0, 0, 0])
        w.append(int(code))
        c[0] += code & 1
        c[1] += (code >> 1) & 1
        c[2] += (code >> 2) & 1
        while len(w) > self.DW:
            old = w.popleft()
            c[0] -= old & 1
            c[1] -= (old >> 1) & 1
            c[2] -= (old >> 2) & 1

    def window_counts(self, g: GKey) -> Dict[str, int]:
        c = self.dcnt.get(g, [0, 0, 0])
        return {"n": len(self.dwin.get(g, ())), "fall": c[0], "b": c[1], "e": c[2]}

    def _demoted(self, g: GKey) -> bool:
        w = self.dwin.get(g)
        if not w or len(w) < self.DW:
            return False
        falls, breaks, e = self.dcnt[g]
        return breaks == 0 and e == 0 and falls >= self.p.demote_fall_rate * len(w)

    def _check_demotion(self, g: GKey, n: int) -> None:
        now = self._demoted(g)
        was = g in self.dem
        if now == was:
            return
        if now:
            self.dem.add(g)
        else:
            self.dem.discard(g)
        self._pool = None
        h = self.hist[g]
        ev = {"kind": "demoted" if now else "exit", "n": int(n), "ingested": self.n_ingested, "group": glabel(g), "history": dict(h),
              "window": self.window_counts(g),
              "fall_rate": round(h["fall"] / h["n"], 4) if h["n"] else None, "run3": dict(self.hist3.get(g, {}))}
        self.events.append(ev)
        self.period["events"].append(ev)

    # -- anchors --------------------------------------------------------------------------------------------------------------------------------

    def _recompute_anchors(self, g: GKey) -> None:
        k = int(self.p.anchor_k)
        per: Dict[str, List[int]] = {}
        for cid in self.members(g):
            cls = str(self.a.cells[cid].key[2])
            lst = per.setdefault(cls, [])
            if len(lst) < k:
                lst.append(cid)
        new = sorted((cid for lst in per.values() for cid in lst), key=lambda cid: (self.tick_of[cid], cid))
        for cid in set(self.anchors.get(g, [])) - set(new):          # displaced (or left the group): status and weight are dropped
            if self.anc.get(cid, {}).get("group") == g:
                self.anc.pop(cid, None)
        for cid in new:
            st = self.anc.get(cid)
            if st is None or st["group"] != g or st["digest"] != self.a.cells[cid].digest:
                self.anc[cid] = {"w": 1.0, "bursts": 0, "successes": 0, "since": self.n_ingested, "digest": self.a.cells[cid].digest, "group": g}
        if new:
            self.anchors[g] = new
        else:
            self.anchors.pop(g, None)

    def anchor_rows(self, g: GKey) -> List[Dict[str, Any]]:
        out = []
        for cid in self.anchors.get(g, []):
            c, st = self.a.cells[cid], self.anc[cid]
            out.append({"cid": cid, "class": str(c.key[2]), "tick": int(c.tick), "w": st["w"], "bursts": st["bursts"], "successes": st["successes"]})
        return out

    # -- the draw -----------------------------------------------------------------------------------------------------------------------------------

    def select(self, rng: Any) -> Optional[Tuple[Any, Dict[str, Any]]]:
        lv_groups = self.levels()
        if not lv_groups:
            return None
        u = rng.random()
        fallback = False
        if u < self.p.breadth_share:
            pick = self._breadth(rng)
            if pick is not None:
                return pick
            fallback = True
        return self._exploit(rng, lv_groups, fallback)

    def level_weights(self, levels: Sequence[int]) -> Dict[int, float]:
        """The exploitation weight of each level with an eligible cell (not normalised; the draw normalises): level_decay^(deepest - level),
        or (owner 2026-11-09) the explicit level_weights[deepest - level] (0 past the list)."""
        levels = sorted(levels)
        top = levels[-1]
        lw_param = tuple(getattr(self.p, "level_weights", ()) or ())
        if lw_param:
            lw = {lv: (float(lw_param[top - lv]) if top - lv < len(lw_param) else 0.0) for lv in levels}
        else:
            lw = {lv: self.p.level_decay ** (top - lv) for lv in levels}
        return lw

    def _exploit(self, rng: Any, lv_groups: Mapping[int, List[GKey]], fallback: bool) -> Tuple[Any, Dict[str, Any]]:
        p = self.p
        levels = sorted(lv_groups)
        lw = self.level_weights(levels)
        total = sum(lw.values())
        r = rng.random() * total
        lv = levels[-1]
        acc = 0.0
        for cand in levels:
            acc += lw[cand]
            if r < acc:
                lv = cand
                break
        gs = lv_groups[lv]
        sh, phi = self.shares(lv, gs)
        tot = sum(sh[g] for g in gs)
        r = rng.random() * tot
        g = gs[-1]
        acc = 0.0
        for cand in gs:
            acc += sh[cand]
            if r < acc:
                g = cand
                break
        mem = self.members(g)
        anc = self.anchors.get(g, [])
        wmax = max((self.anc[cid]["w"] for cid in anc), default=0.0)
        u3 = rng.random()
        draw = {"stream": "rank", "level": lv, "p_level": round(lw[lv] / total, 5), "group": glabel(g), "share": round(sh[g], 6), "phi": round(phi, 6),
                "rho": round(self.rho(g), 6), "demoted": g in self.dem, "group_eligible": len(mem), "anchors": len(anc), "anchor_p": round(p.anchor_share * wmax, 6),
                "fallback": fallback}
        if anc and u3 < p.anchor_share * wmax:
            cid = min(anc, key=lambda x: (-self.anc[x]["w"], self.anc[x]["bursts"], self.tick_of[x], x))
            st = self.anc[cid]
            draw.update({"stream": "anchor", "rank": mem.index(cid), "anchor_w": st["w"], "anchor_bursts": st["bursts"]})
            return self.a.cells[cid], draw
        ws = self.rank_weights(g, mem)
        cum: List[float] = []
        s = 0.0
        for w in ws:
            s += w
            cum.append(s)
        r = rng.random() * s
        pos = min(bisect.bisect_right(cum, r), len(ws) - 1)
        draw.update({"rank": pos, "w_share": round(ws[pos] / s, 6)})
        return self.a.cells[mem[pos]], draw

    def rank_weights(self, g: GKey, mem: Optional[Sequence[int]] = None) -> List[float]:
        p = self.p
        mem = self.members(g) if mem is None else mem
        out = []
        for i, cid in enumerate(mem):
            c = self.a.cells[cid]
            w = (1.0 + i) ** (-p.rank_exp) * max(p.novelty_floor, 1.0 / (1.0 + self.stale.get(cid, 0)))
            k = int(getattr(c, "cleared", 0) or 0)
            if k:
                w *= p.cleared_weight ** k
            out.append(w)
        return out

    def breadth_pool(self) -> List[int]:
        if self._pool is None:
            pool: List[int] = []
            for g in sorted(self.gall):
                if g not in self.dem:
                    pool.extend(self.members(g))
            self._pool = sorted(pool)
        return self._pool

    def _breadth(self, rng: Any) -> Optional[Tuple[Any, Dict[str, Any]]]:
        p = self.p
        if self.tq and self.cnt["trigger_draws"] + 1 <= p.trigger_cap * (self.cnt["breadth_draws"] + 1):
            while self.tq:
                cid, digest, _left, ti = self.tq[0]
                c = self.a.cells[cid]
                if c.digest != digest or cid not in self.group or not self.a.eligible(c):
                    self.tq.popleft()
                    self.cnt["trigger_dropped"] += 1
                    self.period["trigger_dropped"] += 1
                    self.triggers[ti]["dropped"] += 1
                    continue
                g = self.group[cid]
                return c, {"stream": "trigger", "level": int(c.level), "group": glabel(g), "trigger": ti, "demoted": g in self.dem,
                           "rank": self.members(g).index(cid)}
        pool = self.breadth_pool()
        if not pool:
            return None
        cum: List[float] = []
        s = 0.0
        for cid in pool:
            s += 1.0 / (1.0 + self.bcount.get(cid, 0))
            cum.append(s)
        r = rng.random() * s
        pos = min(bisect.bisect_right(cum, r), len(pool) - 1)
        cid = pool[pos]
        g = self.group[cid]
        return self.a.cells[cid], {"stream": "breadth", "level": int(self.a.cells[cid].level), "group": glabel(g), "pool": len(pool),
                                   "count": self.bcount.get(cid, 0), "w_share": round((1.0 / (1.0 + self.bcount.get(cid, 0))) / s, 8),
                                   "rank": self.members(g).index(cid)}

    # -- dispatch and ingest ------------------------------------------------------------------------------------------------------------------------

    def on_dispatch(self, c: Any, draw: Mapping[str, Any], n: int) -> Dict[str, Any]:
        """The job was sent: the selection-time counters. Returns what the engine keeps with the in-flight job."""
        cid = int(c.cid)
        g = self.group[cid]
        stream = draw["stream"]
        self.stale[cid] = self.stale.get(cid, 0) + 1
        self.bcount[cid] = self.bcount.get(cid, 0) + 1
        if stream == "anchor":
            self.anc[cid]["bursts"] += 1
        if stream in ("breadth", "trigger"):
            self.cnt["breadth_draws"] += 1
        if stream == "trigger":
            self.cnt["trigger_draws"] += 1
            e = self.tq.popleft()
            if e[0] != cid:
                raise RuntimeError(f"the trigger queue head {e[0]} is not the drawn cell {cid}")
            e[2] -= 1
            self.triggers[e[3]]["draws_given"] += 1
            if e[2] > 0:
                self.tq.append(e)
        if draw.get("fallback"):
            self.period["fallback_exploit"] += 1
            self.cnt["fallback_exploit"] += 1
        pg = self.period["by_group"].setdefault(glabel(g), Counter())
        pg[stream] += 1
        pg["dispatches"] += 1
        if int(draw.get("rank", 10 ** 9)) < 10:
            pg["top10"] += 1
        self.period["dispatches"] += 1
        self.period["streams"][stream] += 1
        self.period["by_level"][str(g[0])] += 1
        if stream in ("breadth", "trigger"):
            self.period["breadth_by_level"][str(g[0])] += 1
            self.period["breadth_by_group"][glabel(g)] += 1
            self.period["breadth_by_niche"][g[2]] += 1
        self.cum["streams"][stream] += 1
        self.cum["dispatches_by_group"][glabel(g)] += 1
        return {"group": g, "niche": self.niche[cid], "stream": stream, "digest": c.digest}

    def on_quarantine(self, c: Any) -> None:
        g = self._remove(int(c.cid))
        if g is not None:
            self.anc.pop(int(c.cid), None)
            self._recompute_anchors(g)

    def on_ingest(self, info: Mapping[str, Any], row: Mapping[str, Any], kept: Sequence[Tuple[str, Any, Niche]],
                  events: Sequence[Mapping[str, Any]], n: int) -> Dict[str, Any]:
        """One ingested burst: `info` the engine's in-flight record (with on_dispatch's fields), `row` its dispatch row, `kept` the
        (verdict, cell, niche) of every NEW / REPLACED cell in keep order, `events` the burst's anomaly events (glitch and non-finite)."""
        p = self.p
        self.n_ingested += 1
        g: GKey = tuple(info["group"])  # type: ignore[assignment]
        lv = int(info["level"])
        stream = info["stream"]
        claimed = (row.get("claimed") or {}).get("completion_input_tick") if row.get("outcome") == "clear" else None
        if lv >= TARGETS_TOTAL - 1:
            u = int(claimed is not None and int(claimed) <= self.bound)
        else:
            nxt = (row.get("levels") or {}).get(str(lv + 1))
            u = int(nxt is not None and int(nxt) <= self.bound)
        e = 0
        landings: Dict[GKey, Tuple[int, int]] = {}             # the earliest kept cell beating each group's earliest alive cell
        for _v, c, niche in kept:
            g2 = self.gkey_of(c, niche)
            lst = self.gall.get(g2)
            earliest = not lst or int(c.tick) < lst[0][0]
            if c.level > lv and earliest:
                e = 1
            if earliest and c.level < TARGETS_TOTAL:
                t2 = (int(c.tick), int(c.cid))
                if g2 not in landings or t2 < landings[g2]:
                    landings[g2] = t2
        new_best_claim = claimed is not None and (self.best_claim is None or int(claimed) < self.best_claim)
        if new_best_claim:
            self.best_claim = int(claimed)
            if lv >= TARGETS_TOTAL - 1:
                e = 1
        b = int(bool(row.get("advanced")))
        fall = int(row.get("outcome") == "fall")
        for h in (self.hist.setdefault(g, Counter({k: 0 for k in HIST_FIELDS})), self.hist3.setdefault(g, Counter())):
            h["n"] += 1
            h["fall"] += fall
            h["b"] += b
            h["bu"] += u
            h["e"] += e
        self._ensure_window(g)
        w = self.win[g]
        w.append(float(u + e))
        while len(w) > self.W:
            w.popleft()
        self._push(g, window_code(fall, b, e))
        for d_ in (self.period, self.cum):                     # owner 2026-11-09: the per-level yield in the hourly record
            d_["ingested_by_level"][str(lv)] += 1
            d_["useful_by_level"][str(lv)] += u
            d_["e_by_level"][str(lv)] += e
        self._check_demotion(g, n)
        # the kept cells: niches, moves, ranks, anchors
        affected: Set[GKey] = set()
        moves = []
        for verdict, c, niche in kept:
            cid = int(c.cid)
            old = self._remove(cid) if cid in self.group else None
            if verdict == REPLACED:
                self.anc.pop(cid, None)
                self.stale[cid] = 0
            self.niche[cid] = niche
            new = self._insert(c)
            if old is not None:
                affected.add(old)
                if old != new:
                    moves.append({"n": int(n), "cid": cid, "from": glabel(old), "to": glabel(new), "tick": int(c.tick)})
            affected.add(new)
        for gg in sorted(affected):
            self._ensure_window(gg)
            self._check_demotion(gg, n)
            self._recompute_anchors(gg)
        self.cnt["moves"] += len(moves)
        self.period["moves"] += len(moves)
        self.period["move_samples"] = (self.period["move_samples"] + moves)[:20]
        # the anchor's own update
        success = None
        cid0 = int(info["cid"])
        if stream == "anchor":
            st = self.anc.get(cid0)
            if st is not None and st["digest"] == info["digest"]:
                success = bool(new_best_claim and lv >= TARGETS_TOTAL - 1)
                for _v, c, _niche in kept:
                    if c.level > lv and int(c.cid) in self.anchors.get(self.group.get(int(c.cid), ()), []):  # type: ignore[arg-type]
                        success = True
                st["w"] = 1.0 if success else max(p.anchor_w_floor, st["w"] / 2.0)
                st["successes"] += int(success)
                self.period["anchor_bursts_ingested"][glabel(g)] += 1
                self.period["anchor_successes"][glabel(g)] += int(success)
        # new earliest eligible cells of demoted groups (owner 2026-11-08): trigger draws
        landed = [self._landing_trigger(g2, cid, n) for g2, (_t, cid) in sorted(landings.items())
                  if g2 in self.dem and self.group.get(cid) == g2 and cid in self.members(g2)]
        # triggers
        trig = self._trigger(kept, events, n, cid0)
        # counters for the records
        for d in (self.period, self.cum):
            d["useful"][stream] += u
            d["e"][stream] += e
            d["breaks"][stream] += b
        self.period["ingested"] += 1
        return {"u": u, "e": e, "b": b, "moves": len(moves), "anchor_success": success, "trigger": trig, "landing_triggers": landed}

    def _landing_trigger(self, g: GKey, cid: int, n: int) -> int:
        p = self.p
        c = self.a.cells[cid]
        ti = len(self.triggers)
        rec = {"index": ti, "n": int(n), "ingested": self.n_ingested, "classes": [LANDING_CLASS], "all_classes": [LANDING_CLASS], "event_ids": [],
               "first_tick": int(c.tick), "rule": ["new_earliest_in_demoted_group"], "group": glabel(g), "cells": [[int(cid), int(c.tick)]],
               "draws_queued": int(p.trigger_draws_per_cell), "draws_given": 0, "dropped": 0}
        self.triggers.append(rec)
        self.period["triggers"].append(ti)
        self.cnt["landing_triggers"] += 1
        if int(p.trigger_draws_per_cell) > 0:
            self.tq.append([int(cid), c.digest, int(p.trigger_draws_per_cell), ti])
        return ti

    def _trigger(self, kept: Sequence[Tuple[str, Any, Niche]], events: Sequence[Mapping[str, Any]], n: int,
                 dispatched_cid: Optional[int] = None) -> Optional[int]:
        p = self.p
        tc = set(p.trigger_classes)
        mine = [ev for ev in events if str(ev.get("kind")) in tc]
        classes = sorted({str(ev["kind"]) for ev in mine})
        rare = [k for k in classes if self.trig_seen[k] < p.trigger_rarity]
        for k in classes:
            self.trig_seen[k] += 1
        if not rare:
            return None
        t0 = min(int(ev.get("step_from", ev.get("step", 0))) + 1 for ev in mine if str(ev["kind"]) in rare)
        picked: Set[Tuple[int, int]] = set()
        how: List[str] = []

        def fallback(label: str) -> None:                          # owner 2026-11-06, rule (b): the last kept cell, else the dispatched one
            before = [(int(c.tick), int(c.cid)) for _v, c, _n in kept if self.a.eligible(c)]
            if before:
                picked.add(max(before))
                how.append(label)
                return
            c0 = self.a.cells[int(dispatched_cid)] if dispatched_cid is not None else None
            if c0 is not None and int(c0.cid) in self.group and self.a.eligible(c0):
                picked.add((int(c0.tick), int(c0.cid)))
                how.append("dispatched_cell")
            else:
                how.append("none_eligible")

        detector = [k for k in rare if k != NONFINITE]
        if detector:                                               # a detector event: the kept cells at or after its first state
            t1 = min(int(ev.get("step_from", ev.get("step", 0))) + 1 for ev in mine if str(ev["kind"]) in detector)
            after = {(int(c.tick), int(c.cid)) for _v, c, _n in kept if int(c.tick) >= t1 and self.a.eligible(c)}
            if after:
                picked |= after
                how.append("kept_at_or_after_event")
            else:                                                  # owner 2026-11-06: the same fallback as rule (b)
                fallback("last_kept_cell")
        if NONFINITE in rare and not picked:                       # the burst is cut before the null
            fallback("last_kept_before_null")
        cells = sorted(picked)
        ti = len(self.triggers)
        rec = {"index": ti, "n": int(n), "ingested": self.n_ingested, "classes": rare, "all_classes": classes,
               "event_ids": [ev.get("event_id") for ev in mine if str(ev["kind"]) in rare][:8], "first_tick": t0, "rule": how,
               "cells": [[cid, t] for t, cid in cells], "draws_queued": len(cells) * int(p.trigger_draws_per_cell), "draws_given": 0, "dropped": 0}
        self.triggers.append(rec)
        self.period["triggers"].append(ti)
        for t, cid in cells:
            self.tq.append([cid, self.a.cells[cid].digest, int(p.trigger_draws_per_cell), ti])
        return ti

    # -- records ------------------------------------------------------------------------------------------------------------------------------------

    def table(self) -> List[Dict[str, Any]]:
        """One row per group with at least one alive cell: membership, rate, share, demotion, history, anchors."""
        lv_groups = self.levels()
        sh_by: Dict[GKey, float] = {}
        phi_by: Dict[int, float] = {}
        for lv, gs in lv_groups.items():
            sh, phi = self.shares(lv, gs)
            sh_by.update(sh)
            phi_by[lv] = phi
        out = []
        for g in sorted(self.gall, key=lambda g: (-g[0], -sh_by.get(g, 0.0), g)):
            mem = self.members(g)
            if not mem and not self.hist3.get(g, Counter()).get("n"):
                continue                                              # no eligible cell and no run 3 dispatch: not in any draw
            h = self.hist.get(g, Counter())
            classes = Counter(str(self.a.cells[cid].key[2]) for cid in mem)
            ws = self.rank_weights(g, mem) if mem else []
            out.append({"group": glabel(g), "level": g[0], "mask": g[1], "niche": g[2], "cells": len(self.gall[g]), "eligible": len(mem),
                        "earliest_eligible": self.tick_of[mem[0]] if mem else None, "earliest_cell": self.gall[g][0][0] if self.gall[g] else None,
                        "classes": dict(sorted(classes.items())), "anchors": len(self.anchors.get(g, [])),
                        "rho": round(self.rho(g), 6) if g in self.win else None, "share": round(sh_by[g], 6) if g in sh_by else None,
                        "phi": round(phi_by[g[0]], 6) if g[0] in phi_by and mem else None, "demoted": g in self.dem,
                        "warm": dict(self.warm[g]) if g in self.warm else None,
                        "history": {k: int(h.get(k, 0)) for k in HIST_FIELDS}, "fall_rate": round(h["fall"] / h["n"], 4) if h.get("n") else None,
                        "run3": {k: int(self.hist3.get(g, Counter()).get(k, 0)) for k in HIST_FIELDS},
                        "top10_weight_share": round(sum(ws[:10]) / sum(ws), 4) if ws else None})
        return out

    def earliest_by_level(self) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for g, lst in self.gall.items():
            if not lst:
                continue
            t, cid = lst[0]
            d = out.get(str(g[0]))
            if d is None or (t, cid) < (d["tick"], d["cid"]):
                out[str(g[0])] = {"tick": t, "cid": cid, "group": glabel(g)}
        return dict(sorted(out.items(), key=lambda kv: -int(kv[0])))

    def snapshot(self, meta: Mapping[str, Any]) -> Dict[str, Any]:
        """The hourly record: the state now and this period's counters; the period is reset."""
        per = self.period
        table = self.table()
        groups = []
        for row in table:
            gl = row["group"]
            pg = per["by_group"].get(gl, Counter())
            gk = _parse_glabel(gl)
            groups.append(dict(row, period={k: int(v) for k, v in sorted(pg.items())},
                               top10_share_dispatches=round(pg["top10"] / pg["dispatches"], 4) if pg.get("dispatches") else None,
                               anchors_detail=self.anchor_rows(gk), anchor_bursts_ingested=int(per["anchor_bursts_ingested"].get(gl, 0)),
                               anchor_successes=int(per["anchor_successes"].get(gl, 0))))
        pool = self.breadth_pool()
        lvg = self.levels()
        lw0 = self.level_weights(list(lvg)) if lvg else {}
        lw = {lv: w / sum(lw0.values()) for lv, w in lw0.items()} if lw0 else {}
        eb = self.earliest_by_level()
        levels_rec = {}
        for lv in sorted({int(x) for x in list(per["by_level"]) + list(per["ingested_by_level"])} | set(lw), reverse=True):
            k = str(lv)
            ing, u_, e_ = int(per["ingested_by_level"].get(k, 0)), int(per["useful_by_level"].get(k, 0)), int(per["e_by_level"].get(k, 0))
            levels_rec[k] = {"weight": round(lw.get(lv, 0.0), 6), "dispatched": int(per["by_level"].get(k, 0)), "ingested": ing, "u": u_, "e": e_,
                             "per_1000": round(1000.0 * (u_ + e_) / ing, 3) if ing else None, "earliest": (eb.get(k) or {}).get("tick"),
                             "eligible": sum(len(self.members(g)) for g in lvg.get(lv, []))}
        rec = dict(meta)
        rec.update({"contract": SELECT_CONTRACT, "ingested_total": self.n_ingested, "groups": groups, "earliest_by_level": self.earliest_by_level(),
                    "period": {"dispatches": per["dispatches"], "ingested": per["ingested"], "streams": dict(per["streams"]), "by_level": dict(per["by_level"]),
                               "useful": dict(per["useful"]), "e": dict(per["e"]), "breaks": dict(per["breaks"]), "moves": per["moves"],
                               "move_samples": list(per["move_samples"]), "fallback_exploit": per["fallback_exploit"]},
                    "demotions": list(per["events"]),
                    "breadth": {"by_level": dict(per["breadth_by_level"]), "by_group": dict(per["breadth_by_group"]), "by_niche": dict(per["breadth_by_niche"]),
                                "pool": len(pool), "never_dispatched": sum(1 for cid in pool if self.bcount.get(cid, 0) == 0),
                                "useful_breadth": int(per["useful"]["breadth"] + per["useful"]["trigger"]),
                                "useful_exploitation": int(per["useful"]["rank"] + per["useful"]["anchor"]),
                                "e_breadth": int(per["e"]["breadth"] + per["e"]["trigger"]), "e_exploitation": int(per["e"]["rank"] + per["e"]["anchor"]),
                                "cumulative": {"streams": dict(self.cum["streams"]), "useful": dict(self.cum["useful"]), "e": dict(self.cum["e"])}},
                    "triggers": {"new": [dict(self.triggers[i]) for i in per["triggers"]], "total": len(self.triggers), "queue": len(self.tq),
                                 "trigger_draws": int(self.cnt["trigger_draws"]), "breadth_draws": int(self.cnt["breadth_draws"]),
                                 "allowed_now": math.floor(self.p.trigger_cap * self.cnt["breadth_draws"]), "dropped": int(per["trigger_dropped"]),
                                 "classes_seen": dict(self.trig_seen)},
                    "moves_total": int(self.cnt["moves"]), "best_claim": self.best_claim, "levels": levels_rec})
        self.period = _new_period()
        return rec

    def summary(self) -> Dict[str, Any]:
        return {"contract": SELECT_CONTRACT, "ingested": self.n_ingested, "counters": dict(self.cnt), "streams": dict(self.cum["streams"]),
                "useful": dict(self.cum["useful"]), "e": dict(self.cum["e"]), "breaks": dict(self.cum["breaks"]), "events": list(self.events),
                "triggers": [dict(t) for t in self.triggers], "trigger_queue": len(self.tq), "classes_seen": dict(self.trig_seen),
                "table": self.table(), "earliest_by_level": self.earliest_by_level(), "best_claim": self.best_claim,
                "dispatches_by_group": dict(self.cum["dispatches_by_group"])}


def _parse_glabel(s: str) -> GKey:
    lv, mask, niche = str(s).split("|", 2)
    return (int(lv), int(mask), niche)


def start_table_check(table: Sequence[Mapping[str, Any]], expect: Sequence[Mapping[str, Any]]) -> List[str]:
    """Differences between two start tables in the fields the plan records (group, eligible, anchors, share, demoted)."""
    key = lambda r: r["group"]
    a = {key(r): r for r in table}
    b = {key(r): r for r in expect}
    out = []
    for g in sorted(set(a) | set(b)):
        if g not in a or g not in b:
            out.append(f"{g}: only in {'the engine' if g in a else 'the plan'}")
            continue
        for f in ("eligible", "anchors", "share", "demoted", "rho"):
            if a[g].get(f) != b[g].get(f):
                out.append(f"{g}: {f} {a[g].get(f)} != {b[g].get(f)}")
    return out
