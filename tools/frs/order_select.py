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

Standard library only. No coordinate, target id, route, order or tick from a record is in any rule.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

SELECT_CONTRACT = "order_select_v1"
TARGETS_TOTAL = 10
ROOT_MASK = (1 << TARGETS_TOTAL) - 1                 # 1023: nothing broken at tick 0


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
