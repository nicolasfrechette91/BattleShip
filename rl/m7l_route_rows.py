#!/usr/bin/env python3
"""M7l: the closed-form check of one episode row under a route reward contract (btt_reward_v3, btt_reward_v3_t2).

A route return depends on native facts the row's counters do not carry (target identity, the sweep tick, a qualified
landing), so the closed form is computed from the row's own per-episode record `reward_v3` (written by the M7j route
wrapper into training rows, evaluation rows and artifact labels) and cross-checked against the row's counters:

    return          = btt_reward_v3 closed form (+ the btt_reward_v3_t2 moving-target credit when that contract is used)
    failure total   = post_landing_failure_penalty after a qualified landing, else failure_penalty, on a native failure

m7d_run.validate_episode_row dispatches here for route contracts only (it used to raise for them); v1 / v2 rows never
reach this module, so their checks are unchanged. Pure: no game, no files.
"""
from __future__ import annotations

from typing import Any, List, Mapping, Optional, Tuple

TOL = 1e-6


def route_expected(row: Mapping[str, Any], contract: Any) -> Tuple[Optional[float], Optional[float], List[str]]:
    """(expected return, expected failure-penalty total, problems) of a finished (non lifecycle-failure) episode row
    whose `steps`, `targets_broken`, `end_reason` and `target_break_ticks` are the worker's own counters."""
    from btt_reward_t2 import expected_return_v3_t2, moving_target_timing
    from btt_reward_v3 import RewardV3Violation, expected_return_v3
    from btt_rewards import MovingTargetRouteRewardContract, RewardContractError, is_route_contract

    if not is_route_contract(contract):
        raise ValueError(f"{getattr(contract, 'contract', contract)!r} is not a route contract")
    rec = row.get("reward_v3")
    if not isinstance(rec, Mapping):
        return None, None, [f"no reward_v3 record under {contract.contract}"]
    p: List[str] = []
    steps, t = int(row.get("steps")), int(row.get("targets_broken"))
    end = row.get("end_reason")
    fall, clear = end == "fall", end == "clear"
    if rec.get("reward_contract") != contract.contract:
        p.append(f"reward_v3 record contract {rec.get('reward_contract')!r} != {contract.contract}")
    if rec.get("steps") != steps:
        p.append(f"reward_v3 record steps {rec.get('steps')} != {steps}")
    broken = [int(i) for i in rec.get("broken_ids") or []]
    if len(broken) != t or len(set(broken)) != len(broken):
        p.append(f"reward_v3 broken_ids {broken} != {t} targets")
    sweep = rec.get("right_sweep")
    sweep_tick = None if sweep is None else int(sweep["consumed_tick"])
    landing = rec.get("qualified_landing") is not None
    kw = dict(targets_broken=t, steps=steps, cleared=clear, native_failure=fall, sweep_consumed_tick=sweep_tick,
              qualified_landing=landing)
    mt = rec.get("moving_target")
    try:
        if isinstance(contract, MovingTargetRouteRewardContract):
            tid = int(contract.moving_target_id)
            if (mt is not None) != (tid in broken):
                p.append(f"moving-target record {mt} vs broken ids {broken}")
            tick = None
            if mt is not None:
                tick = int(mt["consumed_tick"])
                if abs(float(mt["moving_target_term"]) - moving_target_timing(tick, contract)) > TOL:
                    p.append(f"moving-target term {mt['moving_target_term']} != closed form at tick {tick}")
                ticks = row.get("target_break_ticks")
                if ticks is not None and tick not in ticks:
                    p.append(f"moving-target tick {tick} not among the break ticks {ticks}")
            want = expected_return_v3_t2(moving_target_consumed_tick=tick, contract=contract, **kw)
        else:
            if mt is not None:
                p.append(f"a moving-target record under {contract.contract}")
            want = expected_return_v3(contract=contract, **kw)
    except (RewardContractError, RewardV3Violation, KeyError, TypeError, ValueError) as exc:
        return None, None, p + [f"route closed form: {type(exc).__name__}: {exc}"]
    total = (rec.get("term_totals") or {}).get("total")
    if total is None or abs(float(total) - want) > TOL:
        p.append(f"reward_v3 term total {total} != closed form {want}")
    failure_total = (float(contract.post_landing_failure_penalty) if landing else float(contract.failure_penalty)) \
        if fall else 0.0
    return want, failure_total, p
