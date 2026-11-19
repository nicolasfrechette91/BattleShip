#!/usr/bin/env python3
"""Option D selection: order discovery from tick 0 (docs/frs_option_d_design_2026-11-11.md, decided by the owner on 2026-11-12, section
12). Pure: no process, no file, no clock. Built on tools/frs/run3_select.py without editing it.

    pace line       line(L) = (G x L) // 10 + s, G = 480 (the owner's goal: completion at input tick 480 = a clock under 8.00 s),
                    s = 120 (D-Q1: one 120-input explorer segment of slack). Integer arithmetic. The gate M1 = line(6).
    arrival rule    (owner 2026-11-16, order_select_v2) a state at level L < 10 with input tick t whose L-th break came at input tick a
                    (a = 0 at level 0) is kept, and its cell eligible, only if a <= line(L) AND t <= line(L + 1); level 9's limit is
                    therefore the clear line line(10). The line applies to the arrival at a level, and the state may then stay until the
                    next level's line. Keeping, drawing and the milestones use this one rule. (order_select_v1 applied t <= line(L) to
                    every state.)
    open line       (owner 2026-11-18, order_select_v4; option open_line_from = K, default None = off = v3 exactly) a state that has
                    broken K or more targets is also kept, and its cell eligible, when its K-th break came at or before line(K): no line
                    then applies to its later breaks or to its own tick. A state the arrival rule above keeps stays kept (the option only
                    opens). Keeping, drawing, the burst continuation and the resume read the rule with the option; the milestones do not
                    (M2 ... M4 still need the L-th break at or before line(L)).
    rejected        (owner 2026-11-12, section 7.2; v2 2026-11-16) per level, the count of reaches the rule rejected and the earliest
                    rejected tick with its distance over the limit it failed, split by reason: a late arrival (a > line(L)) or a passed
                    window (t > line(L + 1)): report-only, read by no rule.
    claims          a clear is claimed when its completion input tick is under the frontier's best verified clear read at the plan
                    (section 4.1), at any tick: keeping stops at line(10) = 600, claims do not.
    active cell     eligible (alive, not cleared, inside the arrival rule) and not retired. Exploitation draws only active cells; breadth any
                    eligible cell, retired or not (D-Q5).
    the draw        (section 3.1) breadth with probability 0.2: run 3's count-based draw, weight 1 / (1 + dispatches of the cell), over
                    every eligible cell in cell-id order, set-blind. Otherwise exploitation: a level, 0.4 / 0.3 / 0.2 / 0.1 by rank among
                    the four deepest levels with an active cell (gap D); the set of that level with the lowest budget count; the order
                    of that set with the lowest budget count (ties: the earliest active cell's tick, then its cell id, gap A); then
                    run 3's cell draw unchanged (anchors, rank draw, staleness: tools/frs/run3_select.Run3Selector, subclassed, not
                    edited) over the order's active cells. No trigger stream (D-Q5). An exploitation draw with no active cell falls
                    back to a breadth draw, recorded (gap G2). With the open line set to K (owner 2026-11-19, order_select_v6), all
                    levels >= K form ONE draw group: in the level draw the group stands where level K would stand, so it takes the
                    weight the deepest level takes (0.4) and the levels below K take the weights they take when K is the deepest level
                    (by rank among the levels present; with no active cell at a level >= K the group is absent and the rule is the
                    above); the group's draw is the stream "fewest": its active cell (every level >= K, every target set and order)
                    with the fewest dispatches of the cell (the breadth count: every stream, counted when selected, from zero each
                    night), ties to the deeper level, then the earlier tick, then the cell id; no set or order rotation, no anchor or
                    rank draw (the draw record says scope "group"). (v4 drew inside the rotation's order, v5 over one level with
                    per-level weights.) Levels below K keep the rotation and run 3's cell draw. Breadth draws are unchanged.
    fall cut        (owner 2026-11-19, order_select_v5; v6: grounded states spared; option fall_cut_y = Y, needs the open line's K,
                    default None = off) at levels >= K a state whose position y is below Y (y < Y) and whose resource class (the
                    cell key's) is not G (grounded) is not kept as a cell and its cell is not eligible (neither exploitation nor
                    breadth); an inherited cell below Y and not grounded stays in the archive (it holds its key) but is not drawable.
                    The engine gives the selector each cell's y (`y_of`); levels below K, the milestones, the continuation and the
                    reach records are unchanged. Report-only readout: the reaches the cut did not keep, and the grounded reaches below Y
                    it spared, per level (FallCutReaches).
    budget counts   exploitation draws only, counted when the dispatch is selected (D-Q3); with the open line, not the group's
                    draws at levels >= K (no rotation there). A unit (set or order) is in the rotation
                    while it has an active cell. A unit entering it starts at max(its count, the minimum over its siblings in the
                    rotation) (gap F); with no sibling in the rotation, at max(its count, the highest count any sibling ever had), 0
                    when there never was one (gap G1). The siblings are read before the ingest that brings it in. A unit leaving keeps
                    its count. The counts in the rotation stay within 1 at all times.
    retirement      (D-Q4, gaps B, C, G3, G4) a cell retires after R = 300 of its dispatches (any stream, counted at ingest) none of
                    which kept a cell at a deeper level, a clear at or before line(10) counting as one; a cell one of whose dispatches
                    kept one never retires (a retired cell whose breadth dispatch keeps one is active again); a faster representative
                    restarts the count and the status; a dispatch ingested after its cell's representative was replaced counts for
                    neither.
    milestones      (section 8, gap E; v3) M1 ... M4: the first cell kept during the night with at least L = 6 ... 9 targets broken whose
                    L-th break came at or before line(L) (the arrival rule) and happened during one of the night's bursts (owner
                    2026-11-16: in-night arrivals only; a break inherited in a resumed cell's prefix does not count, even in a cell kept
                    tonight); its tick is that break's. The clear line: the first clear whose completion input tick is <= line(10)
                    (section 4.2). Each recorded once. Cells inherited by a resume never meet a milestone.
    same-tick       (gap G5, report-only) per level reached, the burst ticks with two or more breaks: run 3's label tie orders
                    those targets in the order niche, so the pilot counts how often it decided an order.

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
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

import run3_select as rs

SELECT_CONTRACT = "order_select_v6"                 # v2 (owner 2026-11-16): the arrival rule; v1 kept a state only if its tick <= line(L);
                                                     # v3 (owner 2026-11-16): a milestone's L-th break must happen in one of the night's bursts
                                                     # v4 (owner 2026-11-18): the open line from level K and the fewest-dispatches cell draw at
                                                     # levels >= K, both behind open_line_from (default None: v3's behaviour exactly)
                                                     # v5 (owner 2026-11-19): at levels >= K the fewest draw is over the whole level (no set or
                                                     # order rotation there); the fall cut behind fall_cut_y (default None: off)
                                                     # v6 (owner 2026-11-19): with the open line, the levels >= K are one draw group (the
                                                     # deepest level's weight, fewest over the group, ties deeper level); the cut spares G
REJECT_REASONS = ("late_arrival", "window_passed")
GROUNDED = "G"                                       # the cell key's grounded resource class (rl/m8_rd_cells.RES_GROUNDED; order_search checks)
TARGETS_TOTAL = 10
ROOT_MASK = (1 << TARGETS_TOTAL) - 1                 # 1023: nothing broken at tick 0
STREAMS = ("rank", "anchor", "breadth", "fewest")    # D-Q5: no trigger stream; "fewest" only with the open line (levels >= K)
EXPLOIT_STREAMS = ("rank", "anchor", "fewest")
MILESTONES: Tuple[Tuple[str, int], ...] = (("M1", 6), ("M2", 7), ("M3", 8), ("M4", 9))
CLEAR_LINE = "clear_line"
SKey = Tuple[int, int]                               # a target set: (level, live mask)
GKey = Tuple[int, int, str]                          # an order: run 3's group (level, live mask, niche label)


class OrderParamsError(ValueError):
    """A parameter is refused (U1, U10)."""


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
    open_line_from: Optional[int] = None             # owner 2026-11-18: K, the open line from level K (1 ... 9); None = off (v3 exactly)
    fall_cut_y: Optional[float] = None               # owner 2026-11-19: Y, the fall cut at levels >= K (needs K); None = off

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
        k = self.open_line_from
        if k is not None and (not _is_int(k) or not 1 <= k < TARGETS_TOTAL):
            raise OrderParamsError(f"refused: the open line's level K is an integer in [1, {TARGETS_TOTAL - 1}] or off ({k!r})")
        y = self.fall_cut_y
        if y is not None:
            if not isinstance(y, (int, float)) or isinstance(y, bool) or not math.isfinite(y):
                raise OrderParamsError(f"refused: the fall cut's Y is a finite number or off ({y!r})")
            if k is None:
                raise OrderParamsError("refused: the fall cut applies at levels >= K, the open line's level: it needs open_line_from")

    def as_record(self) -> Dict[str, Any]:
        """The parameters as JSON; the open line and the fall cut appear only when set, so with them off the record (and the plan's) is
        v3's."""
        d = asdict(self)
        d["level_weights"] = list(self.level_weights)
        if self.open_line_from is None:
            d.pop("open_line_from")
        if self.fall_cut_y is None:
            d.pop("fall_cut_y")
        else:
            d["fall_cut_y"] = float(self.fall_cut_y)
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


def arrival_tick(break_ticks: Sequence[int], level: int) -> int:
    """The input tick of the level-th break of a state's break ticks (sorted, one per target broken); 0 at level 0 (the tick-0 root)."""
    level = int(level)
    if len(break_ticks) != level:
        raise ValueError(f"a level-{level} state carries {len(break_ticks)} break ticks")
    return int(break_ticks[level - 1]) if level > 0 else 0


class Pace:
    """The arrival rule for one parameter set: the keep / eligible test, and the rejected-reach readout (report-only). `reason`, `keeps`
    and `eligible` take the L-th break's tick and answer the v3 arrival rule; `reason_ticks`, `keeps_ticks` and `eligible_ticks` take all
    the state's break ticks and answer the rule with the open line (the same answers when it is off). D's engine and selector use the
    latter."""

    def __init__(self, p: OrderParams):
        p.check()
        self.p = p
        self.lines = tuple(pace_line(L, p.goal, p.slack) for L in range(TARGETS_TOTAL + 1))
        self.open_from: Optional[int] = None if p.open_line_from is None else int(p.open_line_from)
        self.cut_y: Optional[float] = None if p.fall_cut_y is None else float(p.fall_cut_y)
        self.rejected = RejectedReaches(self.lines)
        self.cut = FallCutReaches()

    def below_y(self, level: int, y: float) -> bool:
        """The option is set to Y, the state is at a level >= K (the open line's) and its position y is below Y (y < Y). Off: never."""
        return self.cut_y is not None and self.open_from is not None and int(level) >= self.open_from and float(y) < self.cut_y

    def below_cut(self, level: int, y: float, res: str) -> bool:
        """The fall cut (owner 2026-11-19; v6): below Y at a level >= K (below_y) and not grounded (the resource class `res`, the cell
        key's, is not G). Off: never."""
        return self.below_y(level, y) and str(res) != GROUNDED

    def line(self, level: int) -> int:
        return self.lines[int(level)]

    def window_end(self, level: int) -> int:
        """The last input tick a level-L state may have: line(L + 1) (level 9: the clear line, line(10))."""
        return self.lines[min(int(level) + 1, TARGETS_TOTAL)]

    def reason(self, level: int, tick: int, arrival: int) -> Optional[Tuple[str, int]]:
        """None when a level-L state at `tick` whose L-th break came at `arrival` is inside the rule; otherwise (reason, distance >= 1)."""
        lv = int(level)
        if not 0 <= lv < TARGETS_TOTAL:
            raise ValueError(f"the arrival rule covers levels 0 to {TARGETS_TOTAL - 1} ({lv})")
        if int(arrival) > int(tick):
            raise ValueError(f"an arrival at {arrival} after the state's own tick {tick}")
        if int(arrival) > self.lines[lv]:
            return ("late_arrival", int(arrival) - self.lines[lv])
        if int(tick) > self.window_end(lv):
            return ("window_passed", int(tick) - self.window_end(lv))
        return None

    def keeps(self, level: int, tick: int, arrival: int) -> bool:
        """The arrival rule: a state at level L < 10 is kept (and its cell eligible) only if its L-th break came at or before line(L) and
        its own tick is at or before line(L + 1)."""
        return int(level) < TARGETS_TOTAL and self.reason(level, tick, arrival) is None

    def eligible(self, c: Any, arrival: int) -> bool:
        """A cell (run 3's Cell or any object with level, tick, alive()) whose level-th break came at `arrival` is eligible: alive, not
        cleared, inside the arrival rule."""
        return bool(c.alive()) and int(c.level) < TARGETS_TOTAL and self.keeps(c.level, c.tick, arrival)

    def opened(self, level: int, break_ticks: Sequence[int]) -> bool:
        """The open line (owner 2026-11-18): the option is set to K, the state has broken K or more targets and its K-th break came at or
        before line(K). `break_ticks`: the state's break ticks, sorted, one per target broken."""
        k = self.open_from
        return k is not None and int(level) >= k and int(break_ticks[k - 1]) <= self.lines[k]

    def reason_ticks(self, level: int, tick: int, break_ticks: Sequence[int]) -> Optional[Tuple[str, int]]:
        """`reason` with the open line: None when the v3 rule keeps the state or the open line does; otherwise the v3 rule's reason and
        distance. `break_ticks`: sorted, one per target broken (the level-th is the arrival)."""
        bt = [int(t) for t in break_ticks]
        why = self.reason(level, tick, arrival_tick(bt, int(level)))
        if why is not None and self.opened(level, bt):
            return None
        return why

    def keeps_ticks(self, level: int, tick: int, break_ticks: Sequence[int]) -> bool:
        return int(level) < TARGETS_TOTAL and self.reason_ticks(level, tick, break_ticks) is None

    def eligible_ticks(self, c: Any, break_ticks: Sequence[int]) -> bool:
        return bool(c.alive()) and int(c.level) < TARGETS_TOTAL and self.keeps_ticks(c.level, c.tick, break_ticks)


class RejectedReaches:
    """Section 7.2 (owner 2026-11-12; v2 2026-11-16): per level, the reaches the arrival rule rejected, and the earliest rejected tick with
    its distance over the limit it failed and that limit's reason; per reason (a late arrival, a passed window) the count and the smallest
    distance; for the current period and the whole night. Report-only: no rule reads it."""

    def __init__(self, lines: Tuple[int, ...]):
        self.lines = tuple(int(x) for x in lines)
        self.night: Dict[int, Dict[str, Any]] = {}
        self.period: Dict[int, Dict[str, Any]] = {}

    @staticmethod
    def _note(d: Dict[int, Dict[str, Any]], level: int, tick: int, reason: str, over: int) -> None:
        r = d.get(level)
        if r is None:
            r = d[level] = {"count": 0, "earliest_tick": tick, "distance": over, "reason": reason}
        r["count"] += 1
        r[reason] = r.get(reason, 0) + 1
        k = f"{reason}_min_distance"
        r[k] = over if k not in r else min(r[k], over)
        if tick < r["earliest_tick"]:
            r["earliest_tick"], r["distance"], r["reason"] = tick, over, reason

    def note(self, level: int, tick: int, reason: str, over: int) -> int:
        """Record one rejected reach (Pace.reason's answer); returns its distance (>= 1)."""
        level, tick, over = int(level), int(tick), int(over)
        if reason not in REJECT_REASONS or over <= 0:
            raise ValueError(f"not a rejected reach: level {level}, tick {tick}, {reason} +{over}")
        self._note(self.night, level, tick, reason, over)
        self._note(self.period, level, tick, reason, over)
        return over

    @staticmethod
    def _rec(d: Mapping[int, Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
        return {str(lv): dict(d[lv]) for lv in sorted(d, reverse=True)}

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        """The hourly per-level readout; the period is reset."""
        out = self._rec(self.period)
        self.period = {}
        return out

    def summary(self) -> Dict[str, Dict[str, Any]]:
        return self._rec(self.night)


class FallCutReaches:
    """The fall cut's readout (owner 2026-11-19, report-only): per level, the in-night reaches the cut did not keep (inside the arrival
    rule, below Y, not grounded), with the highest such y and its tick, and the earliest tick; and (v6) the grounded reaches below Y it
    spared (`spared`: per level, they went on to the archive's keep rule); for the current period and the whole night. Read by no rule."""

    def __init__(self) -> None:
        self.night: Dict[int, Dict[str, Any]] = {}
        self.period: Dict[int, Dict[str, Any]] = {}
        self.spared_night: Counter = Counter()
        self.spared_period: Counter = Counter()

    def spare(self, level: int) -> None:
        self.spared_night[str(int(level))] += 1
        self.spared_period[str(int(level))] += 1

    @staticmethod
    def _spared(c: Counter) -> Dict[str, int]:
        return {k: int(c[k]) for k in sorted(c, key=int, reverse=True)}

    def spared_snapshot(self) -> Dict[str, int]:
        out = self._spared(self.spared_period)
        self.spared_period = Counter()
        return out

    def spared_summary(self) -> Dict[str, int]:
        return self._spared(self.spared_night)

    @staticmethod
    def _note(d: Dict[int, Dict[str, Any]], level: int, tick: int, y: float) -> None:
        r = d.get(level)
        if r is None:
            r = d[level] = {"count": 0, "earliest_tick": tick, "max_y": [y, tick]}
        r["count"] += 1
        r["earliest_tick"] = min(r["earliest_tick"], tick)
        if y > r["max_y"][0]:
            r["max_y"] = [y, tick]

    def note(self, level: int, tick: int, y: float) -> None:
        level, tick, y = int(level), int(tick), float(y)
        self._note(self.night, level, tick, y)
        self._note(self.period, level, tick, y)

    @staticmethod
    def _rec(d: Mapping[int, Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
        return {str(lv): {k: (list(v) if isinstance(v, list) else v) for k, v in d[lv].items()} for lv in sorted(d, reverse=True)}

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        out = self._rec(self.period)
        self.period = {}
        return out

    def summary(self) -> Dict[str, Dict[str, Any]]:
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
    """M1 ... M4 = levels 6 ... 9 (v3, the arrival rule, in-night breaks): the first cell kept during the night with at least L targets
    broken whose L-th break came at or before line(L) AND happened during one of the night's bursts (its tick is after the tick up to which
    the cell's lineage is inherited, `after`: 0 for the night's own root lineage, a resumed cell's own tick for its descendants; owner
    2026-11-16). The milestone's tick is that break's input tick, the cell's own tick is recorded beside it (gap E: a same-tick double break
    can skip level L, so a level-7 cell whose 6th and 7th breaks came at 400 meets M1). The clear line: the first clear with completion
    input tick <= line(10) (section 4.2; the archive keeps no level-10 cell). Each is recorded once, at its first occurrence, with the
    dispatch, the cell and the lineage digests (U8). Inherited (resumed) cells are never observed."""

    def __init__(self, pace: Pace):
        self.lines = tuple(pace.lines)
        self.met: Dict[str, Dict[str, Any]] = {}

    def observe_kept(self, c: Any, n: int, break_ticks: Sequence[int], after: int = 0) -> List[str]:
        bt = [int(t) for t in break_ticks]
        if len(bt) != int(c.level):
            raise ValueError(f"cell {c.cid} at level {c.level} carries {len(bt)} break ticks")
        out = []
        for name, L in MILESTONES:
            if name not in self.met and int(c.level) >= L and int(after) < bt[L - 1] <= self.lines[L]:
                self.met[name] = {"milestone": name, "level": L, "line": self.lines[L], "arrival_level": int(c.level), "tick": bt[L - 1],
                                  "cell_tick": int(c.tick), "inherited_until": int(after), "n": int(n), "cid": int(c.cid), "digest": str(c.digest),
                                  "chain": _hex(getattr(c, "chain", None))}
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


# -- same-tick breaks (gap G5, report-only) -------------------------------------------------------------------------------------------


def same_tick_steps(start_level: int, breaks_after_start: Sequence[Sequence[int]]) -> List[Tuple[int, int]]:
    """The burst ticks on which two or more targets broke, as (the level the lineage reached on that tick, targets broken on it)."""
    by_tick: Counter = Counter(int(t) for t, _i in breaks_after_start)
    out: List[Tuple[int, int]] = []
    lv = int(start_level)
    for t in sorted(by_tick):
        lv += by_tick[t]
        if by_tick[t] >= 2:
            out.append((lv, by_tick[t]))
    return out


class SameTickBreaks:
    """Section 7.2 (gap G5): per level reached, the burst ticks with two or more breaks and the targets broken on them, for the current
    period and the whole night. Report-only: no rule reads it."""

    def __init__(self) -> None:
        self.night: Dict[int, Dict[str, int]] = {}
        self.period: Dict[int, Dict[str, int]] = {}

    def note(self, start_level: int, breaks_after_start: Sequence[Sequence[int]]) -> List[Tuple[int, int]]:
        steps = same_tick_steps(start_level, breaks_after_start)
        for lv, k in steps:
            for d in (self.night, self.period):
                r = d.setdefault(lv, {"ticks": 0, "targets": 0})
                r["ticks"] += 1
                r["targets"] += k
        return steps

    @staticmethod
    def _rec(d: Mapping[int, Mapping[str, int]]) -> Dict[str, Dict[str, int]]:
        return {str(lv): dict(d[lv]) for lv in sorted(d, reverse=True)}

    def snapshot(self) -> Dict[str, Dict[str, int]]:
        out = self._rec(self.period)
        self.period = {}
        return out

    def summary(self) -> Dict[str, Dict[str, int]]:
        return self._rec(self.night)


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
    alive()); `p`: OrderParams; `niches`: the order niche of every cell (the tick-0 root: seed_niche(1023)); `breaks`: every cell's break
    ticks, sorted, one per target broken (the root: ()), a mapping the engine keeps current (it sets a kept cell's ticks before the ingest
    that brings the cell in; the selector holds the same object, not a copy). The engine calls `select` with its keyed uniforms,
    `on_dispatch` when the job is sent and `on_ingest` at the in-order ingest, as for run 3; `kept` holds only the cells the arrival rule
    kept (NEW or REPLACED). With the fall cut (v5) `y_of(cid)` gives the position y of the cell's current representative (its end
    record); it is required then and never read otherwise."""

    def __init__(self, archive: Any, p: OrderParams, *, niches: Mapping[int, Any], breaks: Mapping[int, Sequence[int]],
                 best_claim: Optional[int] = None, inherited_until: Optional[Mapping[int, int]] = None,
                 y_of: Optional[Callable[[int], float]] = None):
        p.check()
        self.dp = p
        self.pace = Pace(p)
        if self.pace.cut_y is not None and y_of is None:
            raise OrderParamsError("refused: the fall cut reads each cell's position y (y_of)")
        self.y_of = y_of
        self.breaks_of = breaks                            # the engine's mapping (v2): cell id -> sorted break ticks
        self.inherited_until: Mapping[int, int] = inherited_until if inherited_until is not None else {}   # v3: engine's; missing = 0
        self.R = int(p.retire_after)
        self.retired: Set[int] = set()                     # D's own: run 3's Cell.retired would take the cell out of breadth too
        self.deeper: Set[int] = set()                      # representatives one of whose dispatches kept a deeper cell: never retire
        self.rcount: Dict[int, int] = {}                   # ingested dispatches of the current representative
        self.set_count: Counter = Counter()                # exploitation draws per set
        self.order_count: Counter = Counter()              # exploitation draws per order
        self.rot_by_set: Dict[SKey, Set[GKey]] = {}        # the orders in the rotation, per set
        self.rot_by_level: Dict[int, Set[SKey]] = {}       # the sets in the rotation, per level
        self.ever_by_set: Dict[SKey, Set[GKey]] = {}       # every order that was ever in the rotation, per set (gap G1)
        self.ever_by_level: Dict[int, Set[SKey]] = {}      # every set that was ever in the rotation, per level (gap G1)
        self.milestones = Milestones(self.pace)
        self.same_tick = SameTickBreaks()
        self.dstat: Counter = Counter()
        self.retired_by_level: Counter = Counter()          # retirement events per level of the retired cell (report-only)
        super().__init__(archive, run3_view(p), niches=niches, history={}, cid_dispatches={}, best_claim=best_claim)
        self._rotate(set(self.gall))

    # -- run 3 hooks: membership, breadth pool, level weights; run 3's shares and demotion are not used -------------------------------

    def arrival(self, cid: int) -> int:
        """The input tick of the cell's level-th break (0 at level 0)."""
        return arrival_tick(self.breaks_of[int(cid)], int(self.a.cells[int(cid)].level))

    def eligible_cid(self, cid: int) -> bool:
        """Eligible under the arrival rule, with the open line when it is set (v4; off: v3's answer), and not below the fall cut (v5)."""
        c = self.a.cells[int(cid)]
        if not self.pace.eligible_ticks(c, self.breaks_of[int(cid)]):
            return False
        return self.pace.cut_y is None or not self.below_cut_cid(int(cid))

    def below_cut_cid(self, cid: int) -> bool:
        """The cell's representative is below the fall cut (a level >= K, y < Y, its key's resource class not G); False with the cut
        off."""
        if self.pace.cut_y is None:
            return False
        assert self.y_of is not None
        c = self.a.cells[int(cid)]
        return self.pace.below_cut(int(c.level), float(self.y_of(int(cid))), str(c.key[2]))

    def cut_undrawable(self) -> Dict[str, int]:
        """Per level, the cells the fall cut alone makes undrawable (alive, inside the arrival rule with the open line, below Y, not
        grounded); report-only. Empty with the cut off."""
        if self.pace.cut_y is None:
            return {}
        out: Counter = Counter()
        for cid, g in self.group.items():
            c = self.a.cells[cid]
            if int(g[0]) >= int(self.pace.open_from or 0) and self.pace.eligible_ticks(c, self.breaks_of[cid]) and self.below_cut_cid(cid):
                out[str(g[0])] += 1
        return {k: int(out[k]) for k in sorted(out, key=int, reverse=True)}

    def members(self, g: GKey) -> List[int]:
        """The order's ACTIVE cells (eligible under the arrival rule, not retired) in rank order (tick, cell id)."""
        m = self._mem.get(g)
        if m is None:
            m = [cid for _t, cid in self.gall.get(g, []) if cid not in self.retired and self.eligible_cid(cid)]
            self._mem[g] = m
        return m

    def breadth_pool(self) -> List[int]:
        """D-Q5: every eligible cell (inside the arrival rule), retired or not, in cell-id order; set-blind."""
        if self._pool is None:
            self._pool = sorted(cid for cid in self.group if self.eligible_cid(cid))
        return self._pool

    def draw_key(self, level: int) -> int:
        """The level draw's key of a level: the level itself, or K for every level >= K with the open line (v6: the levels >= K are one
        draw group, standing where level K stands)."""
        k = self.pace.open_from
        return int(level) if k is None or int(level) < k else int(k)

    def level_weights(self, levels: Sequence[int]) -> Dict[int, float]:
        """Gap D's weights by rank among the draw keys present (v6: with the open line, the group is the key K, so it takes the weight the
        deepest level takes and the levels below K take theirs as if K were the deepest level); off: one key per level, as before."""
        return level_draw_weights([self.draw_key(lv) for lv in levels], self.dp.level_weights)

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

    @staticmethod
    def _join_count(unit: Any, counts: Counter, in_rot: Iterable[Any], ever: Iterable[Any]) -> int:
        """Gap F and G1: max(the unit's count, the siblings' minimum); with no sibling in the rotation, max(its count, the highest count
        any sibling ever had), 0 when there never was one. Counts never fall, so 'ever had' is the siblings' current counts."""
        sib = [counts[x] for x in in_rot]
        ref = min(sib) if sib else max((counts[x] for x in ever if x != unit), default=0)
        return max(counts[unit], ref)

    def _rotate(self, touched: Iterable[GKey]) -> Dict[str, int]:
        """Re-evaluate the orders touched by an ingest, then their sets. A unit entering starts at _join_count; the siblings are read
        before this update (units entering together do not count each other, units leaving in it still count). A unit leaving keeps
        its count. The counts of the units in the rotation then stay within 1 at all times (section 3.1)."""
        rec: Counter = Counter()
        o_join: List[GKey] = []
        o_leave: List[GKey] = []
        for g in sorted({(int(x[0]), int(x[1]), str(x[2])) for x in touched}):
            now, was = bool(self.members(g)), self.in_rotation(g)
            if now and not was:
                o_join.append(g)
            elif was and not now:
                o_leave.append(g)
        start = {g: self._join_count(g, self.order_count, self.rot_by_set.get(set_of(g), ()), self.ever_by_set.get(set_of(g), ())) for g in o_join}
        for g in o_leave:
            self.rot_by_set[set_of(g)].discard(g)
        for g in o_join:
            ever = self.ever_by_set.setdefault(set_of(g), set())
            rec["order_returns" if g in ever else "order_joins"] += 1
            self.order_count[g] = start[g]
            self.rot_by_set.setdefault(set_of(g), set()).add(g)
            ever.add(g)
        rec["order_leaves"] += len(o_leave)
        s_join: List[SKey] = []
        s_leave: List[SKey] = []
        for s in sorted({set_of(g) for g in o_join + o_leave}):
            now, was = bool(self.rot_by_set.get(s)), s in self.rot_by_level.get(s[0], ())
            if now and not was:
                s_join.append(s)
            elif was and not now:
                s_leave.append(s)
        sstart = {s: self._join_count(s, self.set_count, self.rot_by_level.get(s[0], ()), self.ever_by_level.get(s[0], ())) for s in s_join}
        for s in s_leave:
            self.rot_by_level[s[0]].discard(s)
        for s in s_join:
            ever_s = self.ever_by_level.setdefault(s[0], set())
            rec["set_returns" if s in ever_s else "set_joins"] += 1
            self.set_count[s] = sstart[s]
            self.rot_by_level.setdefault(s[0], set()).add(s)
            ever_s.add(s)
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
        if not lv_sets:                                # gap G2: no active cell; retired cells may remain for breadth
            pick = self._breadth_d(rng)
            if pick is not None:
                pick[1]["fallback_breadth"] = True
                self.dstat["fallback_breadth"] += 1
            return pick
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
        k = self.pace.open_from
        if k is not None and lv >= k:
            # owner 2026-11-19 (v6; open line set to K): the draw group of every level >= K: its active cell with the fewest dispatches
            # (the breadth count: every stream, counted when selected) across every level, set and order of the group, ties to the deeper
            # level, then the earlier tick, then the cell id; no set or order rotation, no anchor or rank draw (v4 drew inside the
            # rotation's order, v5 inside one level)
            glevels = sorted(x for x in lv_sets if x >= k)
            pool = [cid for x in glevels for s_ in lv_sets[x] for g_ in self.rot_by_set[s_] for cid in self.members(g_)]
            cid = min(pool, key=lambda x: (self.bcount.get(x, 0), -int(self.group[x][0]), self.tick_of[x], x))
            g = self.group[cid]
            mem = self.members(g)
            draw = {"stream": "fewest", "scope": "group", "level": int(g[0]), "draw_group_from": k, "draw_group_levels": glevels,
                    "p_level": round(lw[lv] / total, 5), "set": slabel(set_of(g)), "group": rs.glabel(g), "draw_group_active": len(pool),
                    "group_eligible": len(mem), "rank": mem.index(cid), "count": int(self.bcount.get(cid, 0)), "fallback": False}
            return self.a.cells[cid], draw
        sets = lv_sets[lv]
        s = min(sets, key=lambda x: (self.set_count[x],) + self._set_first(x))
        orders = self.rot_by_set[s]
        g = min(orders, key=lambda x: (self.order_count[x],) + self._first(x))
        mem = self.members(g)
        # run 3's cell draw inside a group, unchanged (run3_select.Run3Selector._exploit after its group draw)
        p = self.p
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
            if draw.get("scope") == "group":               # v6: a draw of the group of levels >= K: no set or order rotation there
                if self.pace.open_from is None or int(g[0]) < self.pace.open_from:
                    raise RuntimeError(f"a group draw at level {g[0]} without the open line from that level")
                self.dstat["group_draws"] += 1
            else:
                self.order_count[g] += 1
                self.set_count[set_of(g)] += 1
        return info

    def on_ingest(self, info: Mapping[str, Any], row: Mapping[str, Any], kept: Sequence[Tuple[str, Any, Any]],
                  events: Sequence[Mapping[str, Any]], n: int) -> Dict[str, Any]:
        """One ingested burst: `info` the engine's in-flight record (on_dispatch's fields plus cid and level), `row` its dispatch row,
        `kept` the (verdict, cell, niche) of every cell the pace rule kept (NEW or REPLACED) in keep order, `events` its anomaly events."""
        cid0, lv0 = int(info["cid"]), int(info["level"])
        stale = self.a.cells[cid0].digest != info["digest"]   # gap G3: selected from a representative replaced before this ingest
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
        claim = (row.get("claimed") or {}) if row.get("outcome") == "clear" else {}
        cit = claim.get("completion_input_tick")
        clear_in_line = cit is not None and int(cit) <= self.pace.line(TARGETS_TOTAL)
        deeper = any(int(c.level) > lv0 for _v, c, _niche in kept) or clear_in_line     # gap G4: a clear inside the line counts
        self.same_tick.note(lv0, row.get("breaks_after_start") or [])                    # gap G5: report-only
        retired_now = again = False
        if stale:                                          # gap G3: it counts for neither representative
            self.dstat["stale_dispatches"] += 1
        elif cid0 in self.group:                           # D-Q4: the dispatched cell's count and status
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
                self.retired_by_level[str(lv0)] += 1
                retired_now = True
            if retired_now or again:
                g0 = self.group[cid0]
                self._refresh(g0)
                touched.add(g0)
        met: List[str] = []
        for _v, c, _niche in kept:
            met += self.milestones.observe_kept(c, n, self.breaks_of[int(c.cid)], after=int(self.inherited_until.get(int(c.cid), 0)))
        if row.get("outcome") == "clear":
            claim = row.get("claimed") or {}
            if claim.get("completion_input_tick") is not None and self.milestones.observe_clear(int(claim["completion_input_tick"]), n, cid0, claim):
                met.append(CLEAR_LINE)
        out.update({"kept_deeper": deeper, "stale": stale, "retired": retired_now, "active_again": again, "milestones": met,
                    "rotation": self._rotate(touched)})
        return out

    def on_quarantine(self, c: Any) -> None:
        g = self.group.get(int(c.cid))
        super().on_quarantine(c)
        self.retired.discard(int(c.cid))
        if g is not None:
            self._rotate({g})

    # -- readings -------------------------------------------------------------------------------------------------------------------

    def is_active(self, cid: int) -> bool:
        return cid in self.group and cid not in self.retired and self.eligible_cid(cid)

    def within_one_violations(self) -> List[str]:
        """At every level in the level draw (v6: every level of the group too; its counts do not move): the set counts differ by at most 1,
        and within each set the order counts do (D-Q3)."""
        out = []
        rot = list(self.rotation_levels())
        lw = self.level_weights(rot)
        for lv in sorted(x for x in rot if self.draw_key(x) in lw):
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
            if self.pace.open_from is not None and lv >= self.pace.open_from:
                d["draw_group"] = True                     # v6: the weight below is the whole group's, shared by its levels
            dk = self.draw_key(lv)
            d.update({"line": self.pace.line(lv), "in_draw": dk in lw, "weight": round(lw.get(dk, 0.0), 6), "sets": len(sets),
                      "orders": sum(len(self.rot_by_set[s]) for s in sets),
                      "set_count_min": min((self.set_count[s] for s in sets), default=None),
                      "set_count_max": max((self.set_count[s] for s in sets), default=None),
                      "order_spread_max": max(spreads, default=None),
                      "earliest_active_tick": first[0] if first else None,
                      "earliest_vs_line": (first[0] - self.pace.line(lv)) if first else None})
        return {str(lv): per[lv] for lv in sorted(per, reverse=True)}
