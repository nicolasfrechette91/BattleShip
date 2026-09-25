#!/usr/bin/env python3
"""M7k: the per-step arithmetic of btt_reward_v3_t2 (pure: no game, no gym, no SB3).

btt_reward_v3_t2 = btt_reward_v3 exactly (rl/btt_reward_v3.py, unchanged and reused through subclassing) plus one
term, rule btt_moving_target_timing_v1:

    moving_target_term = moving_target_timing_max * (3600 - n) / 3600      (moving_target_timing_max = 2.0)

paid once, on the step whose reply first shows the moving target (native ID 2) broken; n = consumed_tick + 1 as in
v3's sweep timing (2 * 3599 / 3600 on the first tick, exactly 0 on the step that consumes tick 3,599; n outside
1..3,600 is a violation). Identity comes from the M7f diagnostic's remaining_mask, already cross-checked against the
native targets_remaining count by the v3 state. The term is added after v3's total:

    total = v3 total + moving_target_term

so a step on which target 2 does not break is bit-identical to its btt_reward_v3 reward (and therefore to btt_reward_v2
whenever no v3 route term fires). Nothing here is a policy input.

Self-test (no game): python rl/btt_reward_t2.py --self-test
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence

from btt_reward_v3 import RewardV3Violation, RouteRewardState, RouteTerms, _initial, _reply, expected_return_v3
from btt_rewards import (REWARD_V3, REWARD_V3_T2, MovingTargetRouteRewardContract, RewardContractError,
                         RouteRewardContract, is_route_contract)


@dataclass(frozen=True)
class MovingTargetTerms(RouteTerms):
    moving_target_term: float = 0.0

    def to_json(self) -> Dict[str, Any]:
        return {**super().to_json(), "moving_target_term": self.moving_target_term}


def moving_target_timing(consumed_tick: int, contract: MovingTargetRouteRewardContract = REWARD_V3_T2) -> float:
    h = int(contract.horizon_ticks)
    n = int(consumed_tick) + 1
    if not 1 <= n <= h:
        raise RewardV3Violation(f"moving target broken on consumed tick {consumed_tick}: n = {n} outside 1..{h}")
    return float(contract.moving_target_timing_max) * (h - n) / h


class MovingTargetRouteRewardState(RouteRewardState):
    """RouteRewardState (v3) + the one-time moving-target timing credit."""

    def __init__(self, contract: MovingTargetRouteRewardContract = REWARD_V3_T2):
        if not isinstance(contract, MovingTargetRouteRewardContract):
            raise RewardContractError(f"btt_reward_v3_t2 arithmetic needs its own contract, got {contract.contract!r}")
        super().__init__(contract)

    def start(self, initial_reply: Mapping[str, Any]) -> None:
        super().start(initial_reply)
        self.moving: Optional[Dict[str, Any]] = None
        self.totals["moving_target_term"] = 0.0

    def step(self, reply: Mapping[str, Any], *, clear: bool, native_failure: bool) -> MovingTargetTerms:
        before = self.broken_mask
        t = super().step(reply, clear=clear, native_failure=native_failure)
        tid = int(self.contract.moving_target_id)
        term = 0.0
        if not before >> tid & 1 and self.broken_mask >> tid & 1:
            consumed = int(reply["consumed_tick"])
            term = moving_target_timing(consumed, self.contract)
            self.moving = {"step_index": self.steps - 1, "consumed_tick": consumed, "n": consumed + 1,
                           "moving_target_term": term}
        self.totals["moving_target_term"] += term
        self.totals["total"] += term
        return MovingTargetTerms(t.total + term, t.newly_broken, t.target_term, t.step_term, t.clear_term,
                                 t.failure_term, t.sweep_term, t.crossing_term, term)

    def record(self) -> Dict[str, Any]:
        rec = super().record()
        rec["moving_target"] = self.moving
        return rec


def make_route_state(contract: RouteRewardContract) -> RouteRewardState:
    """The per-episode state of a route contract: v3's own for btt_reward_v3, the subclass for btt_reward_v3_t2."""
    if isinstance(contract, MovingTargetRouteRewardContract):
        return MovingTargetRouteRewardState(contract)
    if is_route_contract(contract):
        return RouteRewardState(contract)
    raise RewardContractError(f"{contract.contract} is not a route contract")


def expected_return_v3_t2(*, moving_target_consumed_tick: Optional[int], **kw: Any) -> float:
    """expected_return_v3 (same keywords) + the moving-target credit (None = target 2 not broken)."""
    contract = kw.pop("contract", REWARD_V3_T2)
    r = expected_return_v3(contract=contract, **kw)
    if moving_target_consumed_tick is not None:
        r += moving_target_timing(moving_target_consumed_tick, contract)
    return r


# -- self-test (no game) ---------------------------------------------------------------------------------------------


def self_test() -> int:
    failures: List[str] = []

    def expect(cond: bool, name: str) -> None:
        print(f"[{'PASS' if cond else 'FAIL'}] {name}")
        if not cond:
            failures.append(name)

    F = (1 << 10) - 1
    expect(moving_target_timing(0) == 2.0 * 3599 / 3600 and moving_target_timing(3599) == 0.0, "timing bounds")
    for bad in (-1, 3600):
        try:
            moving_target_timing(bad)
            failures.append(f"tick {bad} accepted")
        except RewardV3Violation:
            pass
    # target 2 first (tick 5), then the other six on one tick (sweep at 9); v3 parity on every other step
    m_after = F & ~(1 << 2)
    sweep_mask = m_after & ~sum(1 << i for i in (0, 3, 4, 5, 7, 9))
    masks = [F] * 5 + [m_after] * 4 + [sweep_mask]
    a, b = MovingTargetRouteRewardState(), RouteRewardState(REWARD_V3)
    a.start(_initial())
    b.start(_initial())
    diffs = []
    tot = 0.0
    for t, m in enumerate(masks):
        ta = a.step(_reply(t, x=0.0, y=0.0, remaining=m), clear=False, native_failure=False)
        tb = b.step(_reply(t, x=0.0, y=0.0, remaining=m), clear=False, native_failure=False)
        tot += ta.total
        if ta.total != tb.total:
            diffs.append((t, ta.total - tb.total))
    expect(len(diffs) == 1 and diffs[0][0] == 5 and math.isclose(diffs[0][1], moving_target_timing(5)), f"one-time, v3 parity {diffs}")
    want = expected_return_v3_t2(moving_target_consumed_tick=5, targets_broken=7, steps=10, cleared=False,
                                 native_failure=False, sweep_consumed_tick=9, qualified_landing=False)
    expect(math.isclose(tot, want) and a.record()["moving_target"]["consumed_tick"] == 5, "closed form + record")
    try:
        MovingTargetRouteRewardState(REWARD_V3)
        failures.append("v3 contract accepted by the t2 state")
    except RewardContractError:
        pass
    print(f"btt_reward_t2 self-test: {'PASS' if not failures else 'FAIL ' + str(failures)}")
    return 0 if not failures else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args(argv)
    return self_test() if a.self_test else (p.print_help() or 2)


if __name__ == "__main__":
    sys.exit(main())
