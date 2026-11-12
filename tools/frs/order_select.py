#!/usr/bin/env python3
"""Option D selection: order discovery from tick 0 (docs/frs_option_d_design_2026-11-11.md, decided by the owner on 2026-11-12, section
12). Pure: no process, no file, no clock. Built on tools/frs/run3_select.py without editing it.

    pace line       line(L) = (G x L) // 10 + s, G = 480 (the owner's goal: completion at input tick 480 = a clock under 8.00 s),
                    s = 120 (D-Q1: one 120-input explorer segment of slack). A reach at level L with input tick t is kept, and its
                    cell eligible, only if t <= line(L). Integer arithmetic. The gate M1 = line(6) = 408.
    rejected        (owner 2026-11-12, section 7.2) per level, the count of reaches the line rejected and the earliest rejected tick
                    with its distance over line(L): report-only, read by no rule.
    claims          a clear is claimed when its completion input tick is under the frontier's best verified clear read at the plan
                    (section 4.1), at any tick: keeping stops at line(10) = 600, claims do not.
    active cell     eligible (alive, not cleared, inside the line) and not retired. Exploitation draws only active cells; breadth any
                    eligible cell, retired or not (D-Q5).
    the draw        (section 3.1) breadth with probability 0.2: run 3's count-based draw, weight 1 / (1 + dispatches of the cell), over
                    every eligible cell in cell-id order, set-blind. Otherwise exploitation: a level, 0.4 / 0.3 / 0.2 / 0.1 by rank among
                    the four deepest levels with an active cell (gap D); the set of that level with the lowest budget count; the order
                    of that set with the lowest budget count (ties: the earliest active cell's tick, then its cell id, gap A); then
                    run 3's cell draw unchanged (anchors, rank draw, staleness: tools/frs/run3_select.Run3Selector, subclassed, not
                    edited) over the order's active cells. No trigger stream (D-Q5).
    budget counts   exploitation draws only, counted when the dispatch is selected (D-Q3). A unit (set or order) is in the rotation
                    while it has an active cell. A unit entering it starts at max(its count, the minimum over its siblings in the
                    rotation), 0 when there is none; the siblings are read before the ingest that brings it in. A unit leaving keeps
                    its count (gap F).
    retirement      (D-Q4, gaps B and C) a cell retires after R = 300 of its dispatches (any stream, counted at ingest) none of which
                    kept a cell at a deeper level; a cell one of whose dispatches kept one never retires (a retired cell whose breadth
                    dispatch keeps one is active again); a faster representative restarts the count and the status.
    milestones      (section 8, gap E) M1 ... M4: the first kept arrival with at least L = 6 ... 9 targets broken at a tick <= line(L);
                    the clear line: the first clear whose completion input tick is <= line(10) (section 4.2). Each recorded once.

Standard library and run 3's selection module only. No coordinate, target id, route, order or tick from a record is in any rule.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import math
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

import run3_select as rs

SELECT_CONTRACT = "order_select_v1"
TARGETS_TOTAL = 10
ROOT_MASK = (1 << TARGETS_TOTAL) - 1                 # 1023: nothing broken at tick 0
STREAMS = ("rank", "anchor", "breadth")              # D-Q5: no trigger stream
EXPLOIT_STREAMS = ("rank", "anchor")
MILESTONES: Tuple[Tuple[str, int], ...] = (("M1", 6), ("M2", 7), ("M3", 8), ("M4", 9))
CLEAR_LINE = "clear_line"
SKey = Tuple[int, int]                               # a target set: (level, live mask)
GKey = Tuple[int, int, str]                          # an order: run 3's group (level, live mask, niche label)


class OrderParamsError(ValueError):
    """A parameter is refused (U1, U10)."""


class OrderGapError(RuntimeError):
    """A case the decided design does not define yet: refused here, never decided in code (the owner settles it)."""


def _is_int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


@dataclass(frozen=True)
class OrderParams:
    """D's selection parameters (the decided values are the defaults; section 12)."""
    goal: int = 480                                  # G: the owner's goal, completion input tick (section 4.2)
    slack: int = 120                                 # s (D-Q1)
    level_weights: Tuple[float, ...] = (0.4, 0.3, 0.2, 0.1)   # D-Q2: over the four deepest levels with an eligible, non-retired cell
    breadth_share: float = 0.2                       # D-Q5: count-based breadth, set-blind, over in-pace cells including retired ones
    retire_after: int = 300                          # D-Q4: R
    anchor_k: int = 3                                # run 3's cell draw inside an order (DECISIVE 3), unchanged
    anchor_share: float = 0.5
    anchor_w_floor: float = 0.125
    rank_exp: float = 1.0                            # run 3's rank draw (DECISIVE 1), unchanged
    novelty_floor: float = 0.05
    cleared_weight: float = 0.1

    def check(self) -> None:
        if not _is_int(self.goal) or not _is_int(self.slack):
            raise OrderParamsError(f"refused: the goal and the slack are integers (goal {self.goal!r}, slack {self.slack!r})")
        if self.goal <= 0 or self.slack < 0:
            raise OrderParamsError(f"refused: the goal is positive and the slack not negative (goal {self.goal}, slack {self.slack})")
        lw = tuple(self.level_weights)
        if not lw or len(lw) > TARGETS_TOTAL or any(not isinstance(w, (int, float)) or isinstance(w, bool) or not math.isfinite(w) or w < 0 for w in lw):
            raise OrderParamsError(f"refused: level weights are 1 to {TARGETS_TOTAL} finite, non-negative numbers ({lw!r})")
        if abs(sum(lw) - 1.0) > 1e-9:
            raise OrderParamsError(f"refused: the level weights sum to {sum(lw)!r}, not 1")
        if lw[0] <= 0:
            raise OrderParamsError("refused: the deepest level's weight is positive")
        if not isinstance(self.breadth_share, (int, float)) or isinstance(self.breadth_share, bool) or not 0.0 <= self.breadth_share <= 1.0:
            raise OrderParamsError(f"refused: the breadth share is in [0, 1] ({self.breadth_share!r})")
        if not _is_int(self.retire_after) or self.retire_after < 1:
            raise OrderParamsError(f"refused: R is an integer >= 1 ({self.retire_after!r})")
        if not _is_int(self.anchor_k) or self.anchor_k < 0 or not 0.0 < self.anchor_share <= 1.0 or not 0.0 < self.anchor_w_floor <= 1.0:
            raise OrderParamsError("refused: anchor_k >= 0, anchor_share and anchor_w_floor in (0, 1]")
        if self.rank_exp < 0 or not 0.0 <= self.novelty_floor <= 1.0 or not 0.0 < self.cleared_weight <= 1.0:
            raise OrderParamsError("refused: a cell-draw parameter is out of range")

    def as_record(self) -> Dict[str, Any]:
        d = asdict(self)
        d["level_weights"] = list(self.level_weights)
        return d


def params_fingerprint(p: OrderParams) -> str:
    """sha256 of the contract and the parameters, canonical JSON (U10)."""
    blob = json.dumps({"contract": SELECT_CONTRACT, "params": p.as_record()}, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# -- the pace line (section 4) ----------------------------------------------------------------------------------------------------------


def pace_line(level: int, goal: int = 480, slack: int = 120) -> int:
    """line(L) = (G x L) // 10 + s, integer arithmetic, L = 0 ... 10."""
    if not _is_int(level) or not 0 <= level <= TARGETS_TOTAL:
        raise OrderParamsError(f"refused: a level is an integer in [0, {TARGETS_TOTAL}] ({level!r})")
    return (int(goal) * int(level)) // TARGETS_TOTAL + int(slack)


class Pace:
    """The pace rule for one parameter set: the keep / eligible test, and the rejected-reach readout (report-only)."""

    def __init__(self, p: OrderParams):
        p.check()
        self.p = p
        self.lines = tuple(pace_line(L, p.goal, p.slack) for L in range(TARGETS_TOTAL + 1))
        self.rejected = RejectedReaches(self.lines)

    def line(self, level: int) -> int:
        return self.lines[int(level)]

    def keeps(self, level: int, tick: int) -> bool:
        """A reach at `level` with input tick `tick` is kept (and its cell eligible) only if tick <= line(level)."""
        return int(tick) <= self.lines[int(level)]

    def eligible(self, c: Any) -> bool:
        """A cell (run 3's Cell or any object with level, tick, alive()) is eligible: alive, not cleared, inside the line."""
        return bool(c.alive()) and int(c.level) < TARGETS_TOTAL and int(c.tick) <= self.lines[int(c.level)]


class RejectedReaches:
    """Section 7.2 (owner 2026-11-12): per level, the reaches the line rejected and the earliest rejected tick with its distance over
    line(L), for the current period and the whole night. Report-only: no rule reads it."""

    def __init__(self, lines: Tuple[int, ...]):
        self.lines = tuple(int(x) for x in lines)
        self.night: Dict[int, Dict[str, int]] = {}
        self.period: Dict[int, Dict[str, int]] = {}

    @staticmethod
    def _note(d: Dict[int, Dict[str, int]], level: int, tick: int, over: int) -> None:
        r = d.get(level)
        if r is None:
            d[level] = {"count": 1, "earliest_tick": tick, "distance": over}
            return
        r["count"] += 1
        if tick < r["earliest_tick"]:
            r["earliest_tick"], r["distance"] = tick, over

    def note(self, level: int, tick: int) -> int:
        """Record one rejected reach; returns its distance over the line (>= 1). A reach inside the line is refused here."""
        level, tick = int(level), int(tick)
        over = tick - self.lines[level]
        if over <= 0:
            raise ValueError(f"a reach at level {level}, tick {tick} is inside the line ({self.lines[level]}): it is not rejected")
        self._note(self.night, level, tick, over)
        self._note(self.period, level, tick, over)
        return over

    @staticmethod
    def _rec(d: Mapping[int, Mapping[str, int]]) -> Dict[str, Dict[str, int]]:
        return {str(lv): dict(d[lv]) for lv in sorted(d, reverse=True)}

    def snapshot(self) -> Dict[str, Dict[str, int]]:
        """The hourly per-level readout; the period is reset."""
        out = self._rec(self.period)
        self.period = {}
        return out

    def summary(self) -> Dict[str, Dict[str, int]]:
        return self._rec(self.night)


# -- claims (section 4.1, U9) -----------------------------------------------------------------------------------------------------------


def claim_wanted(completion_input_tick: int, frontier_best: int) -> bool:
    """A clear is claimed (queued for verification, as run 3 does) when it is faster than the frontier's best verified clear read at
    the plan, at any tick (keeping stops at line(10); claims do not). The plan always reads a frontier best (D-Q6)."""
    if not _is_int(frontier_best) or frontier_best <= 0:
        raise OrderParamsError(f"refused: the claim threshold is the frontier's best verified clear, a positive integer ({frontier_best!r})")
    return int(completion_input_tick) < int(frontier_best)


# -- milestones (section 8, gap E) ------------------------------------------------------------------------------------------------------


def _hex(x: Any) -> Optional[str]:
    if x is None:
        return None
    return x.hex() if isinstance(x, (bytes, bytearray)) else str(x)


class Milestones:
    """M1 ... M4 = levels 6 ... 9: the first kept arrival with at least L targets broken at a tick <= line(L) (gap E: a same-tick double
    break can skip level L, so a level-7 arrival at 400 meets M1). The clear line: the first clear with completion input tick <=
    line(10) (section 4.2; the archive keeps no level-10 cell). Each is recorded once, at its first occurrence, with the dispatch, the cell
    and the lineage digests (U8)."""

    def __init__(self, pace: Pace):
        self.lines = tuple(pace.lines)
        self.met: Dict[str, Dict[str, Any]] = {}

    def observe_kept(self, c: Any, n: int) -> List[str]:
        out = []
        for name, L in MILESTONES:
            if name not in self.met and int(c.level) >= L and int(c.tick) <= self.lines[L]:
                self.met[name] = {"milestone": name, "level": L, "line": self.lines[L], "arrival_level": int(c.level), "tick": int(c.tick),
                                  "n": int(n), "cid": int(c.cid), "digest": str(c.digest), "chain": _hex(getattr(c, "chain", None))}
                out.append(name)
        return out

    def observe_clear(self, completion_input_tick: int, n: int, cid: int, claim: Mapping[str, Any]) -> bool:
        cit = int(completion_input_tick)
        if CLEAR_LINE in self.met or cit > self.lines[TARGETS_TOTAL]:
            return False
        self.met[CLEAR_LINE] = {"milestone": CLEAR_LINE, "level": TARGETS_TOTAL, "line": self.lines[TARGETS_TOTAL], "completion_input_tick": cit,
                                "n": int(n), "cid": int(cid), "words_digest": claim.get("words_digest"),
                                "chain": _hex(claim.get("chain", claim.get("final_chain")))}
        return True

    def records(self) -> List[Dict[str, Any]]:
        order = [name for name, _L in MILESTONES] + [CLEAR_LINE]
        return [dict(self.met[k]) for k in order if k in self.met]


# -- the selector (section 3) -----------------------------------------------------------------------------------------------------------


def set_of(g: Sequence[Any]) -> SKey:
    return (int(g[0]), int(g[1]))


def slabel(s: SKey) -> str:
    return f"{int(s[0])}|{int(s[1])}"


def mask_of_order(niche: Tuple[int, Tuple[int, ...]]) -> int:
    """With the single tick-0 root the order determines the live mask (U3): the root's mask minus the targets the order broke."""
    m = int(niche[0])
    for t in niche[1]:
        m &= ~(1 << int(t))
    return m


def level_draw_weights(levels: Iterable[int], weights: Sequence[float]) -> Dict[int, float]:
    """Gap D: the deepest len(weights) levels present get weights[0], weights[1], ... by rank among the levels present (not by distance
    from the deepest level), renormalised over those present. Returns only the levels in the draw (weight > 0)."""
    top = sorted({int(lv) for lv in levels}, reverse=True)[:len(weights)]
    raw = {lv: float(weights[i]) for i, lv in enumerate(top) if float(weights[i]) > 0.0}
    tot = sum(raw.values())
    return {lv: w / tot for lv, w in raw.items()} if tot > 0 else {}


def run3_view(p: OrderParams) -> SimpleNamespace:
    """The fields tools/frs/run3_select.Run3Selector reads. Its cell draw inside an order takes D's values (run 3's, unchanged). Run 3's
    group shares, demotion and triggers are not used by D (section 3.4, D-Q4, D-Q5): their values only satisfy the constructor."""
    return SimpleNamespace(anchor_k=p.anchor_k, anchor_share=p.anchor_share, anchor_w_floor=p.anchor_w_floor, rank_exp=p.rank_exp,
                           novelty_floor=p.novelty_floor, cleared_weight=p.cleared_weight, breadth_share=p.breadth_share,
                           level_weights=tuple(p.level_weights), level_decay=0.5, window=200, phi_factor=0.25, demote_share_factor=0.25,
                           demote_min_dispatches=1000, demote_fall_rate=0.0, demote_exit_fall_rate=0.0, trigger_classes=(),
                           trigger_rarity=0, trigger_draws_per_cell=0, trigger_cap=0.0)


class OrderSelector(rs.Run3Selector):
    """D's draw and its state. `archive`: the engine's archive (cells indexed by id; each cell with cid, key, level, tick, digest,
    alive()); `p`: OrderParams; `niches`: the order niche of every cell (the tick-0 root: seed_niche(1023)). The engine calls `select`
    with its keyed uniforms, `on_dispatch` when the job is sent and `on_ingest` at the in-order ingest, as for run 3; `kept` holds only
    the cells the pace rule kept (NEW or REPLACED)."""

    def __init__(self, archive: Any, p: OrderParams, *, niches: Mapping[int, Any], best_claim: Optional[int] = None):
        p.check()
        self.dp = p
        self.pace = Pace(p)
        self.R = int(p.retire_after)
        self.retired: Set[int] = set()                     # D's own: run 3's Cell.retired would take the cell out of breadth too
        self.deeper: Set[int] = set()                      # representatives one of whose dispatches kept a deeper cell: never retire
        self.rcount: Dict[int, int] = {}                   # ingested dispatches of the current representative
        self.set_count: Counter = Counter()                # exploitation draws per set
        self.order_count: Counter = Counter()              # exploitation draws per order
        self.rot_by_set: Dict[SKey, Set[GKey]] = {}        # the orders in the rotation, per set
        self.rot_by_level: Dict[int, Set[SKey]] = {}       # the sets in the rotation, per level
        self.ever_orders: Set[GKey] = set()
        self.ever_sets: Set[SKey] = set()
        self.milestones = Milestones(self.pace)
        self.dstat: Counter = Counter()
        super().__init__(archive, run3_view(p), niches=niches, history={}, cid_dispatches={}, best_claim=best_claim)
        self._rotate(set(self.gall))

    # -- run 3 hooks: membership, breadth pool, level weights; run 3's shares and demotion are not used -------------------------------

    def members(self, g: GKey) -> List[int]:
        """The order's ACTIVE cells (eligible under the pace rule, not retired) in rank order (tick, cell id)."""
        m = self._mem.get(g)
        if m is None:
            m = [cid for _t, cid in self.gall.get(g, []) if cid not in self.retired and self.pace.eligible(self.a.cells[cid])]
            self._mem[g] = m
        return m

    def breadth_pool(self) -> List[int]:
        """D-Q5: every eligible cell (inside the line), retired or not, in cell-id order; set-blind."""
        if self._pool is None:
            self._pool = sorted(cid for cid in self.group if self.pace.eligible(self.a.cells[cid]))
        return self._pool

    def level_weights(self, levels: Sequence[int]) -> Dict[int, float]:
        return level_draw_weights(levels, self.dp.level_weights)

    def _ensure_window(self, g: GKey) -> None:
        """Run 3's group-share window is replaced by the least-count budget (section 3.4): an empty window, so run 3's ingest bookkeeping
        runs without its pooled warm start, which scans every group."""
        if g not in self.win:
            self.win[g] = deque()
            self.warm[g] = {"rate": None, "source": "not_used_by_D", "at_ingest": self.n_ingested}
            self.hist.setdefault(g, Counter({k: 0 for k in rs.HIST_FIELDS}))

    def _check_demotion(self, g: GKey, n: int) -> None:
        """No demotion in D (section 3.3): retirement replaces it."""
        return None

    # -- the rotation (gap F) -------------------------------------------------------------------------------------------------------

    def _first(self, g: GKey) -> Tuple[int, int]:
        cid = self.members(g)[0]
        return (self.tick_of[cid], cid)

    def _set_first(self, s: SKey) -> Tuple[int, int]:
        return min(self._first(g) for g in self.rot_by_set[s])

    def in_rotation(self, g: GKey) -> bool:
        return g in self.rot_by_set.get(set_of(g), ())

    def rotation_levels(self) -> Dict[int, List[SKey]]:
        return {lv: sorted(ss) for lv, ss in sorted(self.rot_by_level.items()) if ss}

    def _rotate(self, touched: Iterable[GKey]) -> Dict[str, int]:
        """Re-evaluate the orders touched by an ingest, then their sets. A unit entering starts at max(its count, the siblings'
        minimum); the siblings are the units in the rotation before this update (units entering together do not count each other,
        units leaving in it still count); 0 when there is none (gap F). A unit leaving keeps its count."""
        rec: Counter = Counter()
        o_join: List[GKey] = []
        o_leave: List[GKey] = []
        for g in sorted({(int(x[0]), int(x[1]), str(x[2])) for x in touched}):
            now, was = bool(self.members(g)), self.in_rotation(g)
            if now and not was:
                o_join.append(g)
            elif was and not now:
                o_leave.append(g)
        start = {g: max(self.order_count[g], min((self.order_count[x] for x in self.rot_by_set.get(set_of(g), ())), default=0)) for g in o_join}
        for g in o_leave:
            self.rot_by_set[set_of(g)].discard(g)
        for g in o_join:
            rec["order_returns" if g in self.ever_orders else "order_joins"] += 1
            self.order_count[g] = start[g]
            self.rot_by_set.setdefault(set_of(g), set()).add(g)
            self.ever_orders.add(g)
        rec["order_leaves"] += len(o_leave)
        s_join: List[SKey] = []
        s_leave: List[SKey] = []
        for s in sorted({set_of(g) for g in o_join + o_leave}):
            now, was = bool(self.rot_by_set.get(s)), s in self.rot_by_level.get(s[0], ())
            if now and not was:
                s_join.append(s)
            elif was and not now:
                s_leave.append(s)
        sstart = {s: max(self.set_count[s], min((self.set_count[x] for x in self.rot_by_level.get(s[0], ())), default=0)) for s in s_join}
        for s in s_leave:
            self.rot_by_level[s[0]].discard(s)
        for s in s_join:
            rec["set_returns" if s in self.ever_sets else "set_joins"] += 1
            self.set_count[s] = sstart[s]
            self.rot_by_level.setdefault(s[0], set()).add(s)
            self.ever_sets.add(s)
        rec["set_leaves"] += len(s_leave)
        self.dstat.update(rec)
        return {k: int(v) for k, v in sorted(rec.items()) if v}

    def _refresh(self, g: GKey) -> None:
        self._mem.pop(g, None)
        self._recompute_anchors(g)

    # -- the draw ---------------------------------------------------------------------------------------------------------------------

    def select(self, rng: Any) -> Optional[Tuple[Any, Dict[str, Any]]]:
        u = rng.random()
        if u < self.dp.breadth_share:
            return self._breadth_d(rng)                # None only with no eligible cell at all (then no active cell either)
        lv_sets = self.rotation_levels()
        if not lv_sets:
            if self.breadth_pool():
                raise OrderGapError(f"gap G2: an exploitation draw found no active cell while {len(self.breadth_pool())} retired cells are "
                                    "eligible for breadth; the design does not say whether to fall back to breadth or to stop")
            return None
        return self._exploit_d(rng, lv_sets)

    def _exploit_d(self, rng: Any, lv_sets: Mapping[int, List[SKey]]) -> Tuple[Any, Dict[str, Any]]:
        lw = self.level_weights(list(lv_sets))
        levels = sorted(lw)
        total = sum(lw.values())
        r = rng.random() * total
        lv = levels[-1]
        acc = 0.0
        for cand in levels:
            acc += lw[cand]
            if r < acc:
                lv = cand
                break
        sets = lv_sets[lv]
        s = min(sets, key=lambda x: (self.set_count[x],) + self._set_first(x))
        orders = self.rot_by_set[s]
        g = min(orders, key=lambda x: (self.order_count[x],) + self._first(x))
        # run 3's cell draw inside a group, unchanged (run3_select.Run3Selector._exploit after its group draw)
        p = self.p
        mem = self.members(g)
        anc = self.anchors.get(g, [])
        wmax = max((self.anc[cid]["w"] for cid in anc), default=0.0)
        u3 = rng.random()
        draw = {"stream": "rank", "level": lv, "p_level": round(lw[lv] / total, 5), "set": slabel(s), "set_count": int(self.set_count[s]),
                "sets": len(sets), "group": rs.glabel(g), "order_count": int(self.order_count[g]), "orders": len(orders),
                "group_eligible": len(mem), "anchors": len(anc), "anchor_p": round(p.anchor_share * wmax, 6), "fallback": False}
        if anc and u3 < p.anchor_share * wmax:
            cid = min(anc, key=lambda x: (-self.anc[x]["w"], self.anc[x]["bursts"], self.tick_of[x], x))
            st = self.anc[cid]
            draw.update({"stream": "anchor", "rank": mem.index(cid), "anchor_w": st["w"], "anchor_bursts": st["bursts"]})
            return self.a.cells[cid], draw
        ws = self.rank_weights(g, mem)
        cum: List[float] = []
        tot = 0.0
        for w in ws:
            tot += w
            cum.append(tot)
        r = rng.random() * tot
        pos = min(bisect.bisect_right(cum, r), len(ws) - 1)
        draw.update({"rank": pos, "w_share": round(ws[pos] / tot, 6)})
        return self.a.cells[mem[pos]], draw

    def _breadth_d(self, rng: Any) -> Optional[Tuple[Any, Dict[str, Any]]]:
        """Run 3's count-based breadth draw over D's pool (no trigger queue)."""
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
        c = self.a.cells[cid]
        g = self.group[cid]
        k = self.bcount.get(cid, 0)
        draw = {"stream": "breadth", "level": int(c.level), "set": slabel(set_of(g)), "group": rs.glabel(g), "pool": len(pool), "count": k,
                "w_share": round((1.0 / (1.0 + k)) / s, 8), "retired": cid in self.retired}
        if cid not in self.retired:
            draw["rank"] = self.members(g).index(cid)
        return c, draw

    # -- dispatch and ingest ------------------------------------------------------------------------------------------------------------

    def on_dispatch(self, c: Any, draw: Mapping[str, Any], n: int) -> Dict[str, Any]:
        stream = draw["stream"]
        if stream not in STREAMS:
            raise ValueError(f"stream {stream!r} is not one of D's streams {STREAMS} (D-Q5: no trigger stream)")
        if stream in EXPLOIT_STREAMS and int(c.cid) in self.retired:
            raise RuntimeError(f"an exploitation draw of the retired cell {c.cid}")
        info = super().on_dispatch(c, draw, n)
        if stream in EXPLOIT_STREAMS:                      # D-Q3: the budget counts exploitation draws, when selected
            g = info["group"]
            if not self.in_rotation(g):
                raise RuntimeError(f"an exploitation draw from order {rs.glabel(g)}, which is not in the rotation")
            self.order_count[g] += 1
            self.set_count[set_of(g)] += 1
        return info

    def on_ingest(self, info: Mapping[str, Any], row: Mapping[str, Any], kept: Sequence[Tuple[str, Any, Any]],
                  events: Sequence[Mapping[str, Any]], n: int) -> Dict[str, Any]:
        """One ingested burst: `info` the engine's in-flight record (on_dispatch's fields plus cid and level), `row` its dispatch row,
        `kept` the (verdict, cell, niche) of every cell the pace rule kept (NEW or REPLACED) in keep order, `events` its anomaly events."""
        cid0, lv0 = int(info["cid"]), int(info["level"])
        c0 = self.a.cells[cid0]
        if c0.digest != info["digest"]:
            raise OrderGapError(f"gap G3: dispatch {n} was selected from cell {cid0}'s earlier representative, replaced before this ingest; "
                                "the design does not say whether it counts toward the new representative's retirement")
        touched: Set[GKey] = set()
        for v, c, _niche in kept:
            if v not in (rs.NEW, rs.REPLACED):
                raise ValueError(f"a kept cell's verdict is NEW or REPLACED, not {v!r}")
            cid = int(c.cid)
            if cid in self.group:
                touched.add(self.group[cid])
            if v == rs.REPLACED:                           # gap B: a new trajectory; a retired cell is active again
                if cid in self.retired:
                    self.retired.discard(cid)
                    self.dstat["active_again_replaced"] += 1
                self.deeper.discard(cid)
            self.rcount[cid] = 0
        out = dict(super().on_ingest(info, row, kept, events, n))
        for _v, c, _niche in kept:
            touched.add(self.group[int(c.cid)])
        deeper = any(int(c.level) > lv0 for _v, c, _niche in kept)
        retired_now = again = False
        if cid0 in self.group:                             # D-Q4: the dispatched cell's count and status
            self.rcount[cid0] = self.rcount.get(cid0, 0) + 1
            if deeper:
                self.deeper.add(cid0)
                if cid0 in self.retired:                   # gap C
                    self.retired.discard(cid0)
                    self.dstat["active_again_deeper"] += 1
                    again = True
            elif cid0 not in self.deeper and cid0 not in self.retired and self.rcount[cid0] >= self.R:
                self.retired.add(cid0)
                self.dstat["retired"] += 1
                retired_now = True
            if retired_now or again:
                g0 = self.group[cid0]
                self._refresh(g0)
                touched.add(g0)
        met: List[str] = []
        for _v, c, _niche in kept:
            met += self.milestones.observe_kept(c, n)
        if row.get("outcome") == "clear":
            claim = row.get("claimed") or {}
            if claim.get("completion_input_tick") is not None and self.milestones.observe_clear(int(claim["completion_input_tick"]), n, cid0, claim):
                met.append(CLEAR_LINE)
        out.update({"kept_deeper": deeper, "retired": retired_now, "active_again": again, "milestones": met, "rotation": self._rotate(touched)})
        return out

    def on_quarantine(self, c: Any) -> None:
        g = self.group.get(int(c.cid))
        super().on_quarantine(c)
        self.retired.discard(int(c.cid))
        if g is not None:
            self._rotate({g})

    # -- readings -------------------------------------------------------------------------------------------------------------------

    def is_active(self, cid: int) -> bool:
        return cid in self.group and cid not in self.retired and self.pace.eligible(self.a.cells[cid])

    def within_one_violations(self) -> List[str]:
        """At every level in the level draw: the set counts differ by at most 1, and within each set the order counts do (D-Q3)."""
        out = []
        for lv in sorted(self.level_weights(list(self.rotation_levels()))):
            sets = sorted(self.rot_by_level.get(lv, ()))
            cs = [self.set_count[s] for s in sets]
            if cs and max(cs) - min(cs) > 1:
                out.append(f"level {lv}: set counts {min(cs)} .. {max(cs)}")
            for s in sets:
                oc = [self.order_count[g] for g in self.rot_by_set[s]]
                if oc and max(oc) - min(oc) > 1:
                    out.append(f"set {slabel(s)}: order counts {min(oc)} .. {max(oc)}")
        return out

    def level_readout(self) -> Dict[str, Dict[str, Any]]:
        """Per level (deepest first): cells, active and retired cells, sets and orders in the rotation, the budget range, the earliest
        active cell against the line (section 7.2's per-level fields that the selector holds)."""
        lw = self.level_weights(list(self.rotation_levels()))
        per: Dict[int, Dict[str, Any]] = {}
        for g, lst in self.gall.items():
            d = per.setdefault(int(g[0]), {"cells": 0, "active": 0, "retired": 0})
            d["cells"] += len(lst)
            d["active"] += len(self.members(g))
        for cid in self.retired:
            if cid in self.group:
                per[int(self.group[cid][0])]["retired"] += 1
        for lv, d in per.items():
            sets = sorted(self.rot_by_level.get(lv, ()))
            spreads = [max(oc) - min(oc) for oc in ([self.order_count[g] for g in self.rot_by_set[s]] for s in sets) if oc]
            first = min((self._set_first(s) for s in sets), default=None)
            d.update({"line": self.pace.line(lv), "in_draw": lv in lw, "weight": round(lw.get(lv, 0.0), 6), "sets": len(sets),
                      "orders": sum(len(self.rot_by_set[s]) for s in sets),
                      "set_count_min": min((self.set_count[s] for s in sets), default=None),
                      "set_count_max": max((self.set_count[s] for s in sets), default=None),
                      "order_spread_max": max(spreads, default=None),
                      "earliest_active_tick": first[0] if first else None,
                      "earliest_vs_line": (first[0] - self.pace.line(lv)) if first else None})
        return {str(lv): per[lv] for lv in sorted(per, reverse=True)}
