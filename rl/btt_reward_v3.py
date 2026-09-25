#!/usr/bin/env python3
"""M7j: the per-step arithmetic of btt_reward_v3 (pure: no game, no gym, no SB3).

The constants are frozen in btt_rewards.REWARD_V3 (a RouteRewardContract; fingerprinted through its route block).
v3 = the unchanged btt_reward_v2 terms plus three route terms. All inputs are native step replies of the M1c
stepping protocol with the M7f target-identity diagnostic on (SSB64_RL_TARGET_DIAG=1): the M1b observation (position,
ground state, targets_remaining, liveness) and the diagnostic's remaining_mask (bit i = stable native target ID i).

Per step, in this order (rule btt_route_rule_v3):

1. Base terms, exactly as v2: reward_v1(previous targets_remaining, current, native clear) = +1.0 per newly broken
   target, -0.001 per consumed native tick, +10.0 once on the native clear. The number of newly broken targets must
   equal the number of mask bits that turned off, and no bit may turn back on (native state is authoritative; a
   disagreement is a RewardV3Violation, never silently repaired).

2. Right sweep (one-time): on the first step whose reply shows all seven right targets {0, 2, 3, 4, 5, 7, 9} broken,
       sweep_term = 3.0 + 2.0 * (3600 - n) / 3600,   n = consumed_tick + 1
   n is the number of native ticks consumed through that step (consumed_tick counts from 0 at the tick-0 reset), so
   the timing part lies in [0, 2): 2 * 3599 / 3600 when the sweep completes on the very first tick, exactly 0 when it
   completes on the step that consumes tick 3599 (the horizon's last step). n outside 1..3600 is a violation.
   Several targets breaking on one tick (including right and left targets together) pay +1 each and the sweep once.

3. Region events, on live steps only (fighter_valid == 1 and btt_active == 1):
   * an entry is a pair of consecutive live steps (P, E) with x_P >= -2100 > x_E (the main solid's left face; the
     tick-0 reset observation is the predecessor of the first step); y_c = y interpolated at x = -2100;
       over_wall    y_c >= 3000 - 1   (above the ledge top: the only way over the wall)
       under_stage  y_c <= -2850 + 1  (below the main solid: an off-stage fall under the stage)
       through_face otherwise         (physically impossible; counted as an anomaly, never rewarded)
     a first live left step without a live predecessor is `unpaired` (never rewarded);
   * the entry is QUALIFIED iff it is over_wall and the right sweep is complete in the entry step's reply (breaks up to
     and including that step): a premature crossing is never qualified, and neither is any later landing after it;
   * an exit is a pair (P, E) with x_P < -2100 <= x_E; it ends the qualification of the left visit;
   * a landing is a live grounded step (ground_air_state == 0) on the only left-side floor, line 3:
     |y + 1950| <= 1 and -3901 <= x <= -2699;
   * crossing_term = +2.0 on the first landing inside a qualified left visit (one-time per episode; a second landing,
     a repeated crossing, a landing on any other surface or a landing after an unqualified entry pays nothing). A
     landing on the native-failure step itself is not counted.

4. Failure term, only on the native-failure step (btt_native_failure_v1): -1.0 if a qualified landing happened on an
   EARLIER step of the episode, else -5.0 (v2). Clears, horizon truncations, interruptions, startup / transport /
   lifecycle failures and administrative endings never reach this term (exactly as v2).

total = ((v2 base total + failure_term) + sweep_term) + crossing_term, so a step without a route term is
bit-identical to its v2 reward. Consequence (tested): on any trajectory that never completes the right sweep, v3 and
v2 give identical per-step rewards; every v3-specific term is gated by the sweep.

Self-test (no game): python rl/btt_reward_v3.py --self-test
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from btt_learning import RewardContractViolation, live_targets, reward_v1
from btt_rewards import REWARD_V3, RewardContractError, RewardTerms, RouteRewardContract, is_route_contract

DIAG_REPLY_KEY = "targets"                      # m7f_targets.REPLY_KEY (the M7f diagnostic's top-level reply key)
DIAG_CONTRACT = "btt_target_identity_v1"        # m7f_targets.CONTRACT_ID
TARGET_COUNT = 10
FULL_MASK = (1 << TARGET_COUNT) - 1
STEP_STATE_EPISODE_ENDED = 6                    # battleship_client.StepState.EPISODE_ENDED
GAME_STATUS_END = 5                             # btt_parallel.GAME_STATUS_END

OVER_WALL = "over_wall"
UNDER_STAGE = "under_stage"
THROUGH_FACE = "through_face"
UNPAIRED = "unpaired"
ENTRY_CLASSES = (OVER_WALL, UNDER_STAGE, THROUGH_FACE, UNPAIRED)
FAIL_POST_LANDING = "post_landing"
FAIL_STANDARD = "standard"
RECORD_CONTRACT = "btt_reward_v3_episode_v1"
EVENT_CAP = 16                                  # entries / exits kept per episode record (counters are exact)


class RewardV3Violation(RewardContractViolation):
    """A reply contradicts the native target contract, the diagnostic or the tick-0 episode contract."""


@dataclass(frozen=True)
class RouteTerms(RewardTerms):
    """One step's btt_reward_v3 reward: the v2 breakdown plus the two route terms (failure_term may be -1.0)."""

    sweep_term: float = 0.0
    crossing_term: float = 0.0

    def to_json(self) -> Dict[str, Any]:
        return {**super().to_json(), "sweep_term": self.sweep_term, "crossing_term": self.crossing_term}


def _require_route(contract: Any) -> RouteRewardContract:
    if not is_route_contract(contract):
        raise RewardContractError(f"btt_reward_v3 arithmetic needs a route contract, got {getattr(contract, 'contract', contract)!r}")
    return contract


def right_mask(contract: RouteRewardContract = REWARD_V3) -> int:
    m = 0
    for i in contract.right_target_ids:
        m |= 1 << int(i)
    return m


def sweep_timing(consumed_tick: int, contract: RouteRewardContract = REWARD_V3) -> float:
    """right_sweep_timing_max * (H - n) / H with n = consumed_tick + 1 (ticks consumed through the step)."""
    h = int(contract.horizon_ticks)
    n = int(consumed_tick) + 1
    if not 1 <= n <= h:
        raise RewardV3Violation(f"right sweep on consumed tick {consumed_tick}: n = {n} is outside 1..{h} (v3 is defined "
                                f"for tick-0 episodes of at most {h} ticks)")
    return float(contract.right_sweep_timing_max) * (h - n) / h


def classify_entry(px: float, py: float, x: float, y: float,
                   contract: RouteRewardContract = REWARD_V3) -> Tuple[str, float]:
    """Class and crossing height of an entry pair (P, E) with px >= left_boundary_x > x."""
    xl = float(contract.left_boundary_x)
    if not (px >= xl > x):
        raise ValueError(f"not an entry pair: x_P {px} x_E {x}")
    y_c = py + (y - py) * (xl - px) / (x - px)
    tol = float(contract.entry_y_tolerance)
    if y_c >= float(contract.wall_top_y) - tol:
        return OVER_WALL, y_c
    if y_c <= float(contract.under_stage_y) + tol:
        return UNDER_STAGE, y_c
    return THROUGH_FACE, y_c


def on_landing_floor(x: float, y: float, contract: RouteRewardContract = REWARD_V3) -> bool:
    tol = float(contract.landing_tolerance)
    return (abs(float(y) - float(contract.landing_floor_y)) <= tol
            and float(contract.landing_floor_x_min) - tol <= float(x) <= float(contract.landing_floor_x_max) + tol)


def is_live(observation: Mapping[str, Any]) -> bool:
    return int(observation.get("fighter_valid", 0)) == 1 and int(observation.get("btt_active", 0)) == 1


def remaining_mask(reply: Mapping[str, Any]) -> int:
    """The diagnostic's remaining_mask of one observe / step reply (lean, strict parse: no records needed)."""
    t = reply.get(DIAG_REPLY_KEY)
    if not isinstance(t, Mapping):
        raise RewardV3Violation(f"reply has no {DIAG_REPLY_KEY!r} object: btt_reward_v3 needs SSB64_RL_TARGET_DIAG=1")
    if t.get("contract") != DIAG_CONTRACT or t.get("target_schema") != 1:
        raise RewardV3Violation(f"unexpected target diagnostic {t.get('contract')!r} schema {t.get('target_schema')!r}")
    sc, mask = t.get("spawn_count"), t.get("remaining_mask")
    if isinstance(sc, bool) or isinstance(mask, bool) or not isinstance(sc, int) or not isinstance(mask, int):
        raise RewardV3Violation("target diagnostic spawn_count / remaining_mask are not integers")
    if sc != TARGET_COUNT or mask < 0 or mask > FULL_MASK:
        raise RewardV3Violation(f"target diagnostic spawn_count {sc} remaining_mask {mask:#x} (expected 10 targets)")
    return mask


def termination_from_reply(reply: Mapping[str, Any]) -> Tuple[bool, bool]:
    """(clear, native_failure) of a raw step reply: the native EpisodeEnded result, and btt_native_failure_v1 (first
    post-update observation with game_status 5, btt_active 1, targets left and no EpisodeEnded). Offline use; the M7
    wrapper takes both from info["termination_reason"], which the same rule produced."""
    o = reply.get("observation") or {}
    ended = int(reply.get("state", -1)) == STEP_STATE_EPISODE_ENDED
    failure = (not ended and int(o.get("btt_active", 0)) == 1 and int(o.get("game_status", 0)) == GAME_STATUS_END
               and int(o.get("targets_remaining", 0)) > 0)
    return ended, failure


def _mask_ids(mask: int) -> List[int]:
    return [i for i in range(TARGET_COUNT) if mask >> i & 1]


class RouteRewardState:
    """The btt_reward_v3 state of one tick-0 episode. start(initial observe reply), then step(reply, ...) per step."""

    def __init__(self, contract: RouteRewardContract = REWARD_V3):
        self.contract = _require_route(contract)
        self.right = right_mask(self.contract)
        self.started = False

    # -- lifecycle ----------------------------------------------------------------------------------------------

    def start(self, initial_reply: Mapping[str, Any]) -> None:
        o = initial_reply.get("observation") or {}
        mask = remaining_mask(initial_reply)
        if int(o.get("input_tick", -1)) != 0:
            raise RewardV3Violation(f"btt_reward_v3 starts at the tick-0 reset only (input_tick {o.get('input_tick')})")
        if mask != FULL_MASK or live_targets(o) != TARGET_COUNT:
            raise RewardV3Violation(f"tick-0 reset without all ten targets alive (mask {mask:#x}, "
                                    f"targets_remaining {o.get('targets_remaining')})")
        self.started = True
        self.steps = 0
        self.prev_targets: Optional[int] = live_targets(o)
        self.broken_mask = 0
        self.prev_live: Optional[Tuple[float, float]] = (float(o["position_x"]), float(o["position_y"])) if is_live(o) else None
        self.region = "left" if self.prev_live is not None and self.prev_live[0] < float(self.contract.left_boundary_x) else "right"
        self.visit_qualified = False
        self.sweep: Optional[Dict[str, Any]] = None
        self.landing: Optional[Dict[str, Any]] = None                 # the qualified (paid) landing
        self.first_line3_landing: Optional[Dict[str, Any]] = None     # the first line-3 landing, qualified or not
        self.entries: List[Dict[str, Any]] = []
        self.exits: List[Dict[str, Any]] = []
        self.entry_counts: Dict[str, int] = {c: 0 for c in ENTRY_CLASSES}
        self.qualified_entries = 0
        self.exit_count = 0
        self.failure: Optional[str] = None
        self.totals = {"target_term": 0.0, "step_term": 0.0, "clear_term": 0.0, "failure_term": 0.0,
                       "sweep_term": 0.0, "crossing_term": 0.0, "total": 0.0}
        self.terminal_seen = False

    # -- one step -----------------------------------------------------------------------------------------------

    def step(self, reply: Mapping[str, Any], *, clear: bool, native_failure: bool) -> RouteTerms:
        if not self.started:
            raise RewardV3Violation("step before start (the tick-0 observe reply)")
        if self.terminal_seen:
            raise RewardV3Violation("step after the episode's terminal step")
        if clear and native_failure:
            raise RewardContractError("a step cannot be both a native clear and a native failure")
        c = self.contract
        o = reply.get("observation") or {}
        i = self.steps
        self.steps += 1
        consumed = int(reply["consumed_tick"])
        # 1. base terms (v2 arithmetic) and the identity cross-check
        current = live_targets(o)
        base = reward_v1(self.prev_targets, current, clear, c.v1_config())
        mask = remaining_mask(reply)
        broken = FULL_MASK & ~mask
        if self.broken_mask & ~broken:
            raise RewardV3Violation(f"step {i}: target(s) {_mask_ids(self.broken_mask & ~broken)} reported alive again")
        newly_mask = broken & ~self.broken_mask
        if current is not None and bin(mask).count("1") != current:
            raise RewardV3Violation(f"step {i}: remaining_mask {mask:#x} disagrees with targets_remaining {current}")
        if bin(newly_mask).count("1") != base.newly_broken:
            raise RewardV3Violation(f"step {i}: {base.newly_broken} newly broken by count but mask bits "
                                    f"{_mask_ids(newly_mask)}")
        self.broken_mask = broken
        self.prev_targets = current
        # 2. right sweep
        sweep_term = 0.0
        if self.sweep is None and broken & self.right == self.right:
            timing = sweep_timing(consumed, c)
            sweep_term = float(c.right_sweep_bonus) + timing
            self.sweep = {"step_index": i, "consumed_tick": consumed, "n": consumed + 1, "timing_term": timing,
                          "sweep_term": sweep_term, "completing_ids": [t for t in _mask_ids(newly_mask) if self.right >> t & 1]}
        # 3. region events (live steps only)
        crossing_term = 0.0
        landed_before = self.landing is not None
        if is_live(o):
            x, y = float(o["position_x"]), float(o["position_y"])
            xl = float(c.left_boundary_x)
            if self.prev_live is not None:
                px, py = self.prev_live
                if px >= xl > x:
                    cls, y_c = classify_entry(px, py, x, y, c)
                    self._entry(i, consumed, cls, y_c, x, y, px, py)
                elif px < xl <= x:
                    self._exit(i, consumed, x, y)
            elif x < xl and self.region != "left":
                self._entry(i, consumed, UNPAIRED, None, x, y, None, None)
            self.prev_live = (x, y)
            if (int(o.get("ground_air_state", -1)) == 0 and self.region == "left" and on_landing_floor(x, y, c)
                    and not native_failure):
                point = {"step_index": i, "consumed_tick": consumed, "x": x, "y": y,
                         "qualified": bool(self.visit_qualified)}
                if self.first_line3_landing is None:
                    self.first_line3_landing = point
                if self.visit_qualified and self.landing is None:
                    crossing_term = float(c.crossing_landing_bonus)
                    self.landing = dict(point, crossing_term=crossing_term)
        else:
            self.prev_live = None
        # 4. failure term
        failure_term = 0.0
        if native_failure:
            if landed_before:
                failure_term, self.failure = float(c.post_landing_failure_penalty), FAIL_POST_LANDING
            else:
                failure_term, self.failure = float(c.failure_penalty), FAIL_STANDARD
        total = base.total + failure_term + sweep_term + crossing_term
        terms = RouteTerms(total, base.newly_broken, base.target_term, base.step_term, base.clear_term, failure_term,
                           sweep_term, crossing_term)
        for k in ("target_term", "step_term", "clear_term", "failure_term", "sweep_term", "crossing_term", "total"):
            self.totals[k] += getattr(terms, k)
        if clear or native_failure:
            self.terminal_seen = True
        return terms

    def _entry(self, i: int, consumed: int, cls: str, y_c: Optional[float], x: float, y: float,
               px: Optional[float], py: Optional[float]) -> None:
        self.entry_counts[cls] += 1
        qualified = cls == OVER_WALL and self.sweep is not None
        self.region = "left"
        self.visit_qualified = qualified
        self.qualified_entries += int(qualified)
        if len(self.entries) < EVENT_CAP:
            self.entries.append({"step_index": i, "consumed_tick": consumed, "class": cls, "y_c": y_c, "x": x, "y": y,
                                 "x_prev": px, "y_prev": py, "sweep_complete": self.sweep is not None,
                                 "qualified": qualified})

    def _exit(self, i: int, consumed: int, x: float, y: float) -> None:
        self.exit_count += 1
        self.region = "right"
        self.visit_qualified = False
        if len(self.exits) < EVENT_CAP:
            self.exits.append({"step_index": i, "consumed_tick": consumed, "x": x, "y": y})

    # -- per-episode record -------------------------------------------------------------------------------------

    def record(self) -> Dict[str, Any]:
        first = self.entries[0] if self.entries else None
        return {
            "contract": RECORD_CONTRACT,
            "reward_contract": self.contract.contract,
            "steps": self.steps,
            "broken_ids": _mask_ids(self.broken_mask),
            "right_sweep": self.sweep,
            "first_entry": first,
            "entry_counts": dict(self.entry_counts),
            "qualified_entries": self.qualified_entries,
            "exits": self.exit_count,
            "entries": list(self.entries),
            "exit_events": list(self.exits),
            "qualified_landing": self.landing,
            "first_line3_landing": self.first_line3_landing,
            "failure_category": self.failure,
            "anomalies": {"through_face_entries": self.entry_counts[THROUGH_FACE]},
            "term_totals": dict(self.totals),
        }


# -- closed forms and offline helpers --------------------------------------------------------------------------------


def expected_return_v3(*, targets_broken: int, steps: int, cleared: bool, native_failure: bool,
                       sweep_consumed_tick: Optional[int], qualified_landing: bool,
                       contract: RouteRewardContract = REWARD_V3) -> float:
    """Closed form of an episode's v3 return (checks and ranking tables; the state machine accumulates per step).
    qualified_landing=True with native_failure means the landing preceded the failure step."""
    c = _require_route(contract)
    if cleared and native_failure:
        raise RewardContractError("an episode cannot be both cleared and a native failure")
    if qualified_landing and sweep_consumed_tick is None:
        raise RewardContractError("a qualified landing requires the right sweep")
    r = targets_broken * c.target_broken + steps * c.per_step + (c.clear_bonus if cleared else 0.0)
    if sweep_consumed_tick is not None:
        r += c.right_sweep_bonus + sweep_timing(sweep_consumed_tick, c)
    if qualified_landing:
        r += c.crossing_landing_bonus
    if native_failure:
        r += c.post_landing_failure_penalty if qualified_landing else c.failure_penalty
    return r


def rescore_trace(initial_reply: Mapping[str, Any], step_replies: Sequence[Mapping[str, Any]], *,
                  contract: RouteRewardContract = REWARD_V3, v2_contract: Any = None) -> Dict[str, Any]:
    """Offline: v3 (and v2) per-step rewards of a complete raw trace (tick-0 observe reply + every step reply, as
    m7f_trace.run_stepping_trace records them). Terminal flags come from termination_from_reply."""
    from btt_rewards import REWARD_V2, reward_step

    v2c = REWARD_V2 if v2_contract is None else v2_contract
    st = RouteRewardState(contract)
    st.start(initial_reply)
    prev = live_targets(initial_reply["observation"])
    v2_total = 0.0
    v3_total = 0.0
    differing: List[Dict[str, Any]] = []
    for k, r in enumerate(step_replies):
        clear, failure = termination_from_reply(r)
        t3 = st.step(r, clear=clear, native_failure=failure)
        cur = live_targets(r["observation"])
        t2 = reward_step(prev, cur, clear=clear, native_failure=failure, contract=v2c)
        prev = cur
        v2_total += t2.total
        v3_total += t3.total
        if t3.total != t2.total and len(differing) < 32:
            differing.append({"step_index": k, "consumed_tick": r.get("consumed_tick"), "v2": t2.total, "v3": t3.total,
                              "terms": t3.to_json()})
        if clear or failure:
            if k != len(step_replies) - 1:
                raise RewardV3Violation(f"trace continues after its terminal step {k}")
    rec = st.record()
    return {"v2_return": v2_total, "v3_return": v3_total, "delta": v3_total - v2_total, "differing_steps": differing,
            "v3_record": rec}


# -- self-test (no game) --------------------------------------------------------------------------------------------


def _reply(t: int, *, x: float, y: float, g: int = 1, remaining: int = FULL_MASK, state: int = 2,
           game_status: int = 1, live: bool = True) -> Dict[str, Any]:
    o = {"input_tick": t + 1, "position_x": x, "position_y": y, "ground_air_state": g, "fighter_valid": int(live),
         "btt_active": 1, "targets_remaining": bin(remaining).count("1"), "game_status": game_status}
    return {"consumed_tick": t, "state": state, "observation": o,
            DIAG_REPLY_KEY: {"contract": DIAG_CONTRACT, "target_schema": 1, "spawn_count": 10, "remaining_mask": remaining}}


def _initial(x: float = 0.0, y: float = -2550.0) -> Dict[str, Any]:
    r = _reply(-1, x=x, y=y, g=0)
    r["observation"]["input_tick"] = 0
    r.pop("consumed_tick")
    return r


def self_test() -> int:
    failures: List[str] = []

    def expect(cond: bool, name: str) -> None:
        print(f"[{'PASS' if cond else 'FAIL'}] {name}")
        if not cond:
            failures.append(name)

    c = REWARD_V3
    expect(math.isclose(sweep_timing(0), 2 * 3599 / 3600) and sweep_timing(3599) == 0.0, "timing bounds")
    expect(math.isclose(sweep_timing(358), 2 * (3600 - 359) / 3600), "timing TAS tick 358")
    expect(classify_entry(-2090, 3000.0, -2110, 3000.0)[0] == OVER_WALL, "ledge step-off is over_wall")
    expect(classify_entry(-2090, -8000.0, -2110, -8400.0)[0] == UNDER_STAGE, "under-stage entry")
    expect(classify_entry(-2090, 0.0, -2110, 0.0)[0] == THROUGH_FACE, "through-face anomaly")
    expect(on_landing_floor(-2782.6, -1950.0) and not on_landing_floor(-1500.0, 3000.0), "landing floor")
    # a sweep, a qualified crossing, a landing and a post-landing fall
    st = RouteRewardState(c)
    st.start(_initial())
    mask = FULL_MASK
    ret = 0.0
    for t, tid in enumerate((0, 2, 3, 4, 5, 7, 9)):
        mask &= ~(1 << tid)
        ret += st.step(_reply(t, x=0.0, y=0.0, remaining=mask), clear=False, native_failure=False).total
    ret += st.step(_reply(7, x=-2000.0, y=3500.0, remaining=mask), clear=False, native_failure=False).total
    ret += st.step(_reply(8, x=-2200.0, y=3400.0, remaining=mask), clear=False, native_failure=False).total
    land = st.step(_reply(9, x=-3000.0, y=-1950.0, g=0, remaining=mask), clear=False, native_failure=False)
    ret += land.total
    again = st.step(_reply(10, x=-3000.0, y=-1950.0, g=0, remaining=mask), clear=False, native_failure=False)
    ret += again.total
    fall = st.step(_reply(11, x=-3000.0, y=-9000.0, remaining=mask, game_status=5), clear=False, native_failure=True)
    ret += fall.total
    rec = st.record()
    want = expected_return_v3(targets_broken=7, steps=12, cleared=False, native_failure=True, sweep_consumed_tick=6,
                              qualified_landing=True)
    expect(land.crossing_term == 2.0 and again.crossing_term == 0.0 and fall.failure_term == -1.0, "one-time landing, -1 fall")
    expect(math.isclose(ret, want) and rec["failure_category"] == FAIL_POST_LANDING, "closed form")
    # premature crossing: no bonus, -5
    st = RouteRewardState(c)
    st.start(_initial())
    st.step(_reply(0, x=-2000.0, y=3500.0), clear=False, native_failure=False)
    st.step(_reply(1, x=-2200.0, y=3400.0), clear=False, native_failure=False)
    t = st.step(_reply(2, x=-3000.0, y=-1950.0, g=0), clear=False, native_failure=False)
    f = st.step(_reply(3, x=-3000.0, y=-9000.0, game_status=5), clear=False, native_failure=True)
    expect(t.crossing_term == 0.0 and f.failure_term == -5.0 and st.record()["first_line3_landing"]["qualified"] is False,
           "premature crossing unrewarded")
    print(f"btt_reward_v3 self-test: {'PASS' if not failures else 'FAIL ' + str(failures)}")
    return 0 if not failures else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--self-test", action="store_true")
    a = p.parse_args(argv)
    if a.self_test:
        return self_test()
    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
