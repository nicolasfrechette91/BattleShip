#!/usr/bin/env python3
"""M7j tests: btt_reward_v3 (opt-in) - pure cases and game-backed cases.

    python rl/m7j_tests.py unit            # no game
    python rl/m7j_tests.py game            # launches BattleShip (fresh processes, no training beyond the PPO smoke)
    python rl/m7j_tests.py all
    python rl/m7j_tests.py <case> [<case> ...]

Unit: contract identity (v1 / v2 JSON unchanged, v3 frozen, custom cannot claim v3, route block enforced), geometry
against the decoded collision data, the sweep-timing formula and its bounds, entry classification, the per-episode
state machine (one-time bonuses, ordering, fall categories, violations), v2 parity on every sweep-free trajectory,
strict configuration, wrapper guards, evaluation flags and the offline ranking inequalities. This suite never reads
the user-recorded crossing fixtures; per the M7g-a isolation rule only m7g_* files touch them. Their one-off classifier
validation is recorded in runs/m7j/offline/ (docs/rl_reward_v3_m7j.md, section 3).

Game: the TAS under v3 (diagnostic on) against v2 (diagnostic off) - identical native observations, rewards differing
on the sweep step only; two CONSTRUCTED test trajectories (TAS prefix of 410 rows + a scripted stick-right tail; never
observed from a policy, never training data) that exercise the qualified landing, its one-time +2 and the -1
post-landing fall; the worker path (scripted fall, horizon, the verified M7h crossing 83112a8c replayed through a v3
worker); wiring refusals; a bounded PPO smoke through the v3 pilot profile with a final evaluation; resume rules.

Outputs: runs/m7j/_tests_<utc>/ (git-ignored). Native RNG state is never read, logged, compared or hashed.
"""
from __future__ import annotations

import argparse
import json
import math
import multiprocessing
import os
import random
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import btt_reward_v3 as v3  # noqa: E402
import experiment_config as ec  # noqa: E402
from btt_learning import RewardContractViolation  # noqa: E402
from btt_rewards import (REWARD_V1, REWARD_V2, REWARD_V3, RewardContractError, custom_reward_id,  # noqa: E402
                         expected_return, make_reward_contract, reward_contract_from_json, reward_extra_env,
                         reward_step)
from m7_smoke import (EXECUTABLE, FALL_TICK, FLAGS, REPLAY, USER_CONFIG, CaseFailure, Suite,  # noqa: E402
                      artifact_rows_are_canonical, battleship_pids, check, fall_script, log, prepare_workers)

REPO_ROOT = Path(__file__).resolve().parent.parent
PILOT_TOML = REPO_ROOT / "rl" / "configs" / "m7j" / "m7j_v3_pilot_s0.toml"
V2_TOML = REPO_ROOT / "rl" / "configs" / "m7_mario_us_reward_v2.toml"
DIAG = ("SSB64_RL_TARGET_DIAG", "1")
V3_FLAGS = tuple(FLAGS) + (DIAG,)
TAS_RETURN_V2 = 19.553
TAS_SWEEP_TICK = 358                     # target 0 (fireball) completes the seven right targets
TAS_ENTRY_TICK = 359
CUT = 410                                # constructed trajectories: TAS rows 0..409, then the scripted tail
RIGHT_TAIL = (0, 80, 0)                  # stick right, no button (Track 1 stick 1, button 0)
LANDING_TICK = 444                       # measured 2026-09-25 (scratch probe, exe 1e7c62a0)
CONSTRUCTED_FALL_TICK = 661
# Historical v1 / v2 JSON (M7b) and the semantic fingerprints recorded by the historical runs (module version 2).
V1_JSON = '{"contract": "btt_reward_v1", "target_broken": 1.0, "per_step": -0.001, "clear_bonus": 10.0, "failure_penalty": 0.0}'
V2_JSON = '{"contract": "btt_reward_v2", "target_broken": 1.0, "per_step": -0.001, "clear_bonus": 10.0, "failure_penalty": -5.0}'
HISTORICAL_PROFILES = ("m7g/m7g_s0_v1", "m7g/m7g_s1_v1", "m7g/m7g_s2_v1", "m7g/m7g_s0_v2", "m7g/m7g_s1_v2",
                       "m7g/m7g_s2_v2", "m7e/m7e_s0_v2", "m7e/m7e_s1_v2", "m7e/m7e_s2_v2", "m7h/m7h_f_s0",
                       "m7h/m7h_f_s1", "m7h/m7h_f_s2")
HISTORICAL_FINGERPRINTS = {   # runs/<...>/experiment_resolved.json fingerprints.semantic_fingerprint (first 16 hex)
    "m7g/m7g_s0_v1": "d8d993eaacf7ee72", "m7g/m7g_s1_v1": "dd87c6c044691af1", "m7g/m7g_s2_v1": "684dc27abebbc9f4",
    "m7g/m7g_s0_v2": "7ebf069407cc1e49", "m7g/m7g_s1_v2": "c9bdb6369f08ed64", "m7g/m7g_s2_v2": "b9286221247fa7ec",
    "m7e/m7e_s0_v2": "d8d993eaacf7ee72", "m7e/m7e_s1_v2": "dd87c6c044691af1", "m7e/m7e_s2_v2": "684dc27abebbc9f4",
    "m7h/m7h_f_s0": "641390966a21171f", "m7h/m7h_f_s1": "e4971eb93d008c89", "m7h/m7h_f_s2": "22b970e5a987c2f3",
}
M7H_CROSSING = {"run": "m7h_f_s1", "suffix": "83112a8c", "rows": 3221, "v2_return": -2.221}

F = v3.FULL_MASK
RIGHT_IDS = (0, 2, 3, 4, 5, 7, 9)


def _mask_without(*ids: int) -> int:
    m = F
    for i in ids:
        m &= ~(1 << i)
    return m


# -- unit cases ------------------------------------------------------------------------------------------------------


def u_contract_identity(suite: Suite) -> Dict[str, Any]:
    check(json.dumps(REWARD_V1.to_json()) == V1_JSON and json.dumps(REWARD_V2.to_json()) == V2_JSON, "v1 / v2 JSON changed")
    j = REWARD_V3.to_json()
    check(j["contract"] == "btt_reward_v3" and REWARD_V3.values() == REWARD_V2.values() and REWARD_V3 != REWARD_V2
          and REWARD_V3.canonical and "route" in j and "route" not in REWARD_V2.to_json(), "v3 identity")
    r = j["route"]
    check(r["right_target_ids"] == list(RIGHT_IDS) and r["right_sweep_bonus"] == 3.0 and r["right_sweep_timing_max"] == 2.0
          and r["horizon_ticks"] == 3600 and r["crossing_landing_bonus"] == 2.0 and r["post_landing_failure_penalty"] == -1.0,
          f"frozen route constants {r}")
    check(make_reward_contract("btt_reward_v3", REWARD_V2.values()) is REWARD_V3, "canonical v3 from its base values")
    for bad in ({**REWARD_V2.values(), "failure_penalty": -4.0}, {**REWARD_V2.values(), "per_step": -0.002}):
        try:
            make_reward_contract("btt_reward_v3", bad)
            raise CaseFailure(f"altered v3 accepted: {bad}")
        except RewardContractError:
            pass
    custom = make_reward_contract("custom", REWARD_V2.values())
    check(custom.contract == custom_reward_id(REWARD_V2.values()) and not custom.canonical and "route" not in custom.to_json(),
          "custom never claims v3")
    check(reward_contract_from_json(j) is REWARD_V3 and reward_contract_from_json(json.loads(V2_JSON)) is REWARD_V2,
          "from_json round trip")
    tampered = json.loads(json.dumps(j))
    tampered["route"]["right_sweep_bonus"] = 4.0
    for rec in (tampered, {k: v for k, v in j.items() if k != "route"}, {**json.loads(V2_JSON), "route": r}):
        try:
            reward_contract_from_json(rec)
            raise CaseFailure(f"record accepted: {rec}")
        except RewardContractError:
            pass
    for fn in (lambda: reward_step(10, 9, clear=False, native_failure=False, contract=REWARD_V3),
               lambda: expected_return(1, 1, cleared=False, contract=REWARD_V3)):
        try:
            fn()
            raise CaseFailure("the v1 / v2 arithmetic accepted a route contract")
        except RewardContractError:
            pass
    import pickle

    check(pickle.loads(pickle.dumps(REWARD_V3)) == REWARD_V3, "pickle (spawn workers)")
    check(reward_extra_env(REWARD_V2) == () and reward_extra_env(REWARD_V1) == () and reward_extra_env(REWARD_V3) == (DIAG,),
          "native flags per contract")
    return {"v3": j}


def u_geometry(suite: Suite) -> Dict[str, Any]:
    """The frozen route constants against the pinned native line table (m7g_spatial.EXPECTED_LINES, itself checked
    against the decomp stage source by m7g_obs_tests unit_stage_table)."""
    import m7g_spatial as sp

    lines = {ln[0]: (ln[1], ln[4]) for ln in sp.EXPECTED_LINES}
    c = REWARD_V3

    def span(i: int, axis: int) -> Tuple[float, float]:
        vals = [v[axis] for v in lines[i][1]]
        return min(vals), max(vals)

    check(lines[17][0] == sp.LINE_LWALL and span(17, 0) == (c.left_boundary_x, c.left_boundary_x)
          and span(17, 1) == (c.under_stage_y, c.wall_top_y), "line 17 = the main solid's left face (x -2100, y -2850..3000)")
    check(lines[0][0] == sp.LINE_FLOOR and span(0, 1) == (c.wall_top_y, c.wall_top_y) and span(0, 0)[0] == c.left_boundary_x,
          "line 0 = the ledge top at the wall's height")
    check(lines[6][0] == sp.LINE_CEIL and span(6, 1) == (c.under_stage_y, c.under_stage_y)
          and span(6, 0)[0] == c.left_boundary_x, "line 6 = the main solid's underside")
    left_floors = [i for i, (kind, pts) in lines.items() if kind == sp.LINE_FLOOR and i != sp.PLATFORM_LINE
                   and max(p[0] for p in pts) < c.left_boundary_x]
    check(left_floors == [3] and span(3, 0) == (c.landing_floor_x_min, c.landing_floor_x_max)
          and span(3, 1) == (c.landing_floor_y, c.landing_floor_y), f"line 3 = the only left-side floor ({left_floors})")
    # Right targets = the M7f native IDs whose spawn lies right of the main solid's left face (tracked M7f mapping doc).
    mapping = json.loads((REPO_ROOT / "docs" / "rl_target_identity_m7f_mapping.json").read_text(encoding="utf-8"))
    right = tuple(sorted(t["id"] for t in mapping["targets"] if t["spawn"][0] >= c.left_boundary_x))
    left = sorted(t["id"] for t in mapping["targets"] if t["region"] == "left_of_wall")
    check(right == tuple(c.right_target_ids) and left == [1, 6, 8] and len(mapping["targets"]) == 10, f"right targets {right}")
    return {"left_floors": left_floors, "right_ids": right}


def u_timing(suite: Suite) -> Dict[str, Any]:
    t0, tl = v3.sweep_timing(0), v3.sweep_timing(3599)
    check(t0 == 2.0 * 3599 / 3600 and tl == 0.0, f"bounds {t0} {tl}")
    check(v3.sweep_timing(TAS_SWEEP_TICK) == 2.0 * (3600 - 359) / 3600, "TAS")
    check(all(v3.sweep_timing(t) > v3.sweep_timing(t + 1) for t in range(3599)), "strictly decreasing")
    for bad in (-1, 3600, 10 ** 6):
        try:
            v3.sweep_timing(bad)
            raise CaseFailure(f"consumed tick {bad} accepted")
        except v3.RewardV3Violation:
            pass
    return {"n1": t0, "n3600": tl, "tas": v3.sweep_timing(TAS_SWEEP_TICK)}


def u_classify(suite: Suite) -> Dict[str, Any]:
    cases = [((-2090.0, 3000.0, -2110.0, 3000.0), v3.OVER_WALL), ((-2099.0, 2999.0, -2101.0, 2999.0), v3.OVER_WALL),
             ((-2099.0, 2998.99, -2101.0, 2998.99), v3.THROUGH_FACE), ((-2090.0, -2849.0, -2110.0, -2849.0), v3.UNDER_STAGE),
             ((-2090.0, -2848.9, -2110.0, -2848.9), v3.THROUGH_FACE), ((-2080.0, 2980.0, -2120.0, 3030.0), v3.OVER_WALL),
             ((-2090.0, -8000.0, -2110.0, -8400.0), v3.UNDER_STAGE), ((-2090.0, 0.0, -2110.0, 0.0), v3.THROUGH_FACE)]
    for (px, py, x, y), want in cases:
        got, yc = v3.classify_entry(px, py, x, y)
        check(got == want, f"{(px, py, x, y)}: {got} (y_c {yc}) != {want}")
    check(v3.classify_entry(-2080.0, 2980.0, -2120.0, 3030.0)[1] == 3005.0, "interpolation")
    for x, y, want in ((-2700.0, -1950.0, True), (-2699.0, -1951.0, True), (-2698.9, -1950.0, False),
                       (-3901.0, -1950.0, True), (-3000.0, -1948.9, False), (-1500.0, 3000.0, False)):
        check(v3.on_landing_floor(x, y) is want, f"landing floor ({x}, {y})")
    return {"cases": len(cases)}


def _run(seq: Sequence[Tuple[Dict[str, Any], bool, bool]], initial: Optional[Dict[str, Any]] = None):
    st = v3.RouteRewardState()
    st.start(initial or v3._initial())
    return st, [st.step(r, clear=c, native_failure=f) for r, c, f in seq]


def u_state(suite: Suite) -> Dict[str, Any]:
    import m7j_offline as off

    cases = off.loophole_cases()
    bad = [c["case"] for c in cases if not c["ok"]]
    check(not bad, f"loophole cases failed: {bad}")
    R = v3._reply
    # violations
    viol = {
        "count_vs_mask": [(dict(R(0, x=0.0, y=0.0, remaining=_mask_without(4)), observation=dict(
            R(0, x=0.0, y=0.0, remaining=_mask_without(4))["observation"], targets_remaining=10)), False, False)],
        "revived": [(R(0, x=0.0, y=0.0, remaining=_mask_without(4)), False, False), (R(1, x=0.0, y=0.0), False, False)],
        "no_diag": [({k: v for k, v in R(0, x=0.0, y=0.0).items() if k != v3.DIAG_REPLY_KEY}, False, False)],
        "after_terminal": [(R(0, x=0.0, y=-9000.0, game_status=5), False, True), (R(1, x=0.0, y=-9000.0), False, False)],
        "clear_and_failure": [(R(0, x=0.0, y=0.0), True, True)],
    }
    for name, seq in viol.items():
        try:
            _run(seq)
            raise CaseFailure(f"{name}: accepted")
        except (RewardContractViolation, RewardContractError):   # RewardV3Violation is a RewardContractViolation
            pass
    for name, init in (("not_tick0", dict(v3._initial(), observation=dict(v3._initial()["observation"], input_tick=5))),
                       ("not_full", dict(v3._initial(), targets={**v3._initial()["targets"], "remaining_mask": F & ~1}))):
        try:
            v3.RouteRewardState().start(init)
            raise CaseFailure(f"{name}: accepted")
        except v3.RewardV3Violation:
            pass
    # a non-live step breaks the entry pair: the next left step is `unpaired`, never qualified
    m7 = _mask_without(*RIGHT_IDS)
    st, terms = _run([(R(0, x=0.0, y=0.0, remaining=m7), False, False),
                      (R(1, x=-2000.0, y=3500.0, remaining=m7, live=False), False, False),
                      (R(2, x=-2200.0, y=3400.0, remaining=m7), False, False),
                      (R(3, x=-3000.0, y=-1950.0, g=0, remaining=m7), False, False)])
    rec = st.record()
    check(rec["entry_counts"][v3.UNPAIRED] == 1 and rec["qualified_landing"] is None and terms[-1].crossing_term == 0.0,
          f"unpaired entry {rec['entry_counts']}")
    # the sweep pays once even when two right targets complete it on one tick; +1 per target
    st, terms = _run([(R(0, x=0.0, y=0.0, remaining=_mask_without(0, 3, 4, 5, 9)), False, False),
                      (R(1, x=0.0, y=0.0, remaining=m7), False, False)])
    check(terms[1].newly_broken == 2 and terms[1].sweep_term == 3.0 + v3.sweep_timing(1) and terms[0].sweep_term == 0.0,
          "two right targets on the completing tick")
    return {"loophole_cases": [(c["case"], c["got"]) for c in cases], "violations": sorted(viol)}


def u_v2_parity(suite: Suite) -> Dict[str, Any]:
    """Random synthetic trajectories: without the sweep, v3 per-step rewards equal v2's bit for bit; with it, they
    differ only on the sweep step, a qualified landing step and a post-landing failure step."""
    rng = random.Random(20260925)
    n_eq = n_sweep = 0
    for trial in range(400):
        allow_sweep = trial % 2 == 1
        order = list(range(10))
        rng.shuffle(order)
        if not allow_sweep:
            order = [t for t in order if t != 2]           # target 2 never breaks: no sweep possible
        mask, prev = F, 10
        st = v3.RouteRewardState()
        st.start(v3._initial())
        x, y = 0.0, -2550.0
        steps = rng.randint(5, 400)
        diffs = []
        for t in range(steps):
            if order and rng.random() < 0.05:
                for _ in range(rng.choice((1, 1, 1, 2))):
                    if order:
                        mask &= ~(1 << order.pop())
            x = max(-5000.0, min(5000.0, x + rng.uniform(-400, 400)))
            y = max(-9000.0, min(5000.0, y + rng.uniform(-600, 600)))
            if rng.random() < 0.05:
                y = -1950.0
            last = t == steps - 1
            fail = last and rng.random() < 0.5
            g = 0 if (y == -1950.0 or rng.random() < 0.2) and not fail else 1
            r = v3._reply(t, x=x, y=y, g=g, remaining=mask, game_status=5 if fail else 1)
            term = st.step(r, clear=False, native_failure=fail)
            cur = bin(mask).count("1")
            ref = reward_step(prev, cur, clear=False, native_failure=fail, contract=REWARD_V2)
            prev = cur
            if term.total != ref.total:
                diffs.append((t, term.sweep_term, term.crossing_term, term.failure_term))
        if st.sweep is None:
            check(not diffs, f"trial {trial}: v3 != v2 without a sweep at {diffs[:3]}")
            n_eq += 1
        else:
            n_sweep += 1
            check(all(d[1] or d[2] or d[3] == -1.0 for d in diffs), f"trial {trial}: unexplained difference {diffs[:3]}")
    return {"trials_without_sweep": n_eq, "trials_with_sweep": n_sweep}


def u_config(suite: Suite) -> Dict[str, Any]:
    pilot = ec.load_experiment(PILOT_TOML)
    check(pilot.reward is REWARD_V3 and dict(pilot.extra_env).get(DIAG[0]) == "1", "pilot profile")
    control = ec.load_experiment(REPO_ROOT / "rl" / "configs" / "m7g" / "m7g_s0_v1.toml")
    diff = ec.compare_compatibility(pilot.compatibility_view(), control.compatibility_view())
    check(set(diff) == {"contracts.reward_resolved", "environment.extra_env"}, f"pilot vs Phase K control: {sorted(diff)}")
    fps = {}
    for name in HISTORICAL_PROFILES:
        e = ec.load_experiment(REPO_ROOT / "rl" / "configs" / f"{name}.toml")
        fps[name] = e.semantic_fingerprint[:16]
        check(fps[name] == HISTORICAL_FINGERPRINTS[name], f"{name}: semantic fingerprint changed {fps[name]}")
        check(DIAG[0] not in dict(e.extra_env), f"{name}: v1 / v2 profile gained the diagnostic flag")
    rejected = {}
    base = dict(pilot.values)
    attempts = {
        "obs_v2": {"contracts.observation": "btt_policy_obs_v2_spatial", "ppo.policy": "MultiInputPolicy"},
        "horizon": {"environment.horizon": 1800},
        "altered_value": {"reward.failure_penalty": -4.0},
        "curriculum": {},
        "unknown_id": {"contracts.reward": "btt_reward_v4"},
    }
    curriculum_table = ('\n[curriculum]\ncontract = "btt_curriculum_frontier_v1"\ntick0_probability = 0.5\n'
                        'max_prefix_ticks = 3000\npre_fall_exclusion_ticks = 60\ncell_size = 300\n')
    for name, changes in attempts.items():
        values = dict(base, **changes)
        text = ec.to_toml_text(values, header=f"m7j_tests u_config {name}")
        if name == "curriculum":
            text += curriculum_table
        try:
            ec.parse_toml_text(text)
            raise CaseFailure(f"{name}: accepted")
        except ec.ConfigError as exc:
            rejected[name] = str(exc)[:240]
    check("btt_policy_obs_v1" in rejected["obs_v2"] and "3600" in rejected["horizon"] and "canonical" in rejected["altered_value"]
          and "tick-0" in rejected["curriculum"], f"messages {rejected}")
    return {"historical_fingerprints_unchanged": fps, "rejected": rejected, "pilot_semantic": pilot.semantic_fingerprint}


class _FakeBase:
    max_episode_steps = 3600

    def __init__(self, horizon: int = 3600):
        self.max_episode_steps = horizon
        self.observation_space = None
        self.action_space = None


def u_wrappers(suite: Suite) -> Dict[str, Any]:
    import gymnasium as gym

    import btt_parallel as bp
    from m7_evaluation import EvaluationSettings
    from m7j_reward_env import M7RouteRewardWrapper

    class Env(gym.Env):
        observation_space = gym.spaces.Discrete(2)
        action_space = gym.spaces.Discrete(2)

        def __init__(self, horizon: int = 3600):
            self.max_episode_steps = horizon

    out = {}
    for name, fn in {
        "v1_wrapper_refuses_v3": lambda: bp.M7RewardWrapper(Env(), REWARD_V3),
        "route_wrapper_needs_flag": lambda: M7RouteRewardWrapper(Env(), REWARD_V3, extra_env=dict(FLAGS)),
        "route_wrapper_needs_v3": lambda: M7RouteRewardWrapper(Env(), REWARD_V2, extra_env=dict(V3_FLAGS)),
        "route_wrapper_needs_horizon": lambda: M7RouteRewardWrapper(Env(300), REWARD_V3, extra_env=dict(V3_FLAGS)),
    }.items():
        try:
            fn()
            raise CaseFailure(f"{name}: accepted")
        except ValueError as exc:
            out[name] = str(exc)[:160]
    w = M7RouteRewardWrapper(Env(), REWARD_V3, extra_env=dict(V3_FLAGS))
    check(type(bp.M7RewardWrapper(Env(), REWARD_V2)) is bp.M7RewardWrapper and w.route_capable, "construction")
    try:
        w.rebase_for_policy_phase({})
        raise CaseFailure("prefix rebase accepted under v3")
    except RuntimeError:
        pass
    s2 = EvaluationSettings(executable=str(EXECUTABLE), reward=REWARD_V2)
    s3 = EvaluationSettings(executable=str(EXECUTABLE), reward=REWARD_V3)
    s3m = EvaluationSettings(executable=str(EXECUTABLE), reward=REWARD_V3, eval_metrics=True)
    check(s2.effective_extra_env() == tuple(FLAGS) and not s2.records_flags, "v2 evaluation flags unchanged")
    check(dict(s3.effective_extra_env()) == dict(V3_FLAGS) and s3.records_flags, "v3 evaluation adds the diagnostic")
    check(dict(s3m.effective_extra_env()) == dict(V3_FLAGS), "v3 + metrics")
    return out


def u_ranking(suite: Suite) -> Dict[str, Any]:
    import m7j_offline as off

    t = off.ranking_table()
    failed = [q["claim"] for q in t["inequalities"] if not q["holds"]]
    check(not failed, f"ranking inequalities fail: {failed}")
    return {"inequalities": len(t["inequalities"])}


# -- game cases ------------------------------------------------------------------------------------------------------


def _m3_run(out: Path, actions: Sequence[Tuple[int, int, int]], contract: Any, flags: Sequence[Tuple[str, str]]):
    """One episode on the M3/M7 base env through the contract's wrapper (no tracker); native actions."""
    from battleship_env import native_to_action
    from battleship_process import LaunchConfig
    from btt_parallel import M7BattleShipBTTEnv, M7RewardWrapper
    from m7_runtime import PortCandidates, prepare_worker_runtime
    from m7j_reward_env import M7RouteRewardWrapper

    out.mkdir(parents=True)
    prepare_worker_runtime(out / "runtime", EXECUTABLE)
    base = M7BattleShipBTTEnv(LaunchConfig(executable=EXECUTABLE, working_dir=out / "runtime", run_root=out / "episodes",
                                           extra_env=dict(flags)), max_episode_steps=3600, rank=0, ports=PortCandidates(0))
    env = (M7RouteRewardWrapper(base, contract, extra_env=dict(flags)) if contract is REWARD_V3
           else M7RewardWrapper(base, contract))
    obs_seq, rewards, terms, ticks = [], [], [], []
    end = None
    try:
        o, _info = env.reset()
        obs_seq.append({k: np.asarray(v).item() for k, v in o.items()})
        for b, x, y in actions:
            o, r, term, trunc, info = env.step(native_to_action(b, x, y))
            obs_seq.append({k: np.asarray(v).item() for k, v in o.items()})
            rewards.append(r)
            terms.append(info["reward_terms"])
            ticks.append(base.last_step_result.consumed_tick)
            if term or trunc:
                end = info.get("termination_reason") or info.get("truncation_reason")
                break
    finally:
        env.close()
    rec = getattr(env, "last_record", None)
    return {"observations": obs_seq, "rewards": rewards, "terms": terms, "ticks": ticks, "end": end, "record": rec,
            "targets_broken": env.episode_targets_broken}


def _tas_rows() -> List[Tuple[int, int, int]]:
    from btti_replay import read_btti_rows

    return [(r.buttons, r.stick_x, r.stick_y) for r in read_btti_rows(str(REPLAY))]


def g_tas_v3(suite: Suite) -> Dict[str, Any]:
    d = suite.dir("g_tas_v3")
    rows = _tas_rows()
    a = _m3_run(d / "v2_diag_off", rows, REWARD_V2, FLAGS)
    b = _m3_run(d / "v3_diag_on", rows, REWARD_V3, V3_FLAGS)
    check(a["observations"] == b["observations"] and a["ticks"] == b["ticks"] == list(range(447)), "gameplay differs")
    check(a["end"] == b["end"] == "native_clear", f"ends {a['end']} {b['end']}")
    diff = [i for i, (x, y) in enumerate(zip(a["rewards"], b["rewards"])) if x != y]
    check(diff == [TAS_SWEEP_TICK], f"reward differs on steps {diff}")
    want = TAS_RETURN_V2 + 3.0 + 2.0 * (3600 - 359) / 3600
    got = math.fsum(b["rewards"])
    check(abs(math.fsum(a["rewards"]) - TAS_RETURN_V2) < 1e-9 and abs(got - want) < 1e-9, f"returns {got} vs {want}")
    rec = b["record"]
    check(rec["right_sweep"]["consumed_tick"] == TAS_SWEEP_TICK and rec["right_sweep"]["completing_ids"] == [0]
          and rec["first_entry"]["consumed_tick"] == TAS_ENTRY_TICK and rec["first_entry"]["class"] == v3.OVER_WALL
          and rec["first_entry"]["qualified"] and rec["qualified_landing"] is None and rec["failure_category"] is None,
          f"record {rec}")
    return {"v2_return": math.fsum(a["rewards"]), "v3_return": got, "sweep": rec["right_sweep"],
            "entry": rec["first_entry"], "observations_equal": True}


def _constructed(tail_len: Optional[int]) -> List[Tuple[int, int, int]]:
    rows = _tas_rows()[:CUT]
    if tail_len is None:     # stick right until the episode ends (lands at 444, walks off line 3, falls at 661)
        return rows + [RIGHT_TAIL] * (3600 - CUT)
    return rows + [RIGHT_TAIL] * tail_len + [(0, 0, 0)] * (3600 - CUT - tail_len)


def g_constructed_land_fall(suite: Suite) -> Dict[str, Any]:
    """CONSTRUCTED test trajectory (TAS prefix + scripted tail): sweep, qualified entry, +2 landing, -1 fall."""
    d = suite.dir("g_constructed_land_fall")
    acts = _constructed(None)
    a = _m3_run(d / "v2", acts, REWARD_V2, FLAGS)
    b = _m3_run(d / "v3", acts, REWARD_V3, V3_FLAGS)
    check(a["observations"] == b["observations"] and a["end"] == b["end"] == "native_failure", "gameplay / end")
    rec = b["record"]
    n = len(b["rewards"])
    check(n == CONSTRUCTED_FALL_TICK + 1 and rec["qualified_landing"]["consumed_tick"] == LANDING_TICK
          and rec["failure_category"] == v3.FAIL_POST_LANDING, f"steps {n} record {rec}")
    diff = [i for i, (x, y) in enumerate(zip(a["rewards"], b["rewards"])) if x != y]
    check(diff == [TAS_SWEEP_TICK, LANDING_TICK, CONSTRUCTED_FALL_TICK], f"differing steps {diff}")
    check(b["terms"][LANDING_TICK]["crossing_term"] == 2.0 and b["terms"][-1]["failure_term"] == -1.0
          and sum(1 for t in b["terms"] if t["crossing_term"]) == 1, "one-time +2 and the -1 fall")
    want = v3.expected_return_v3(targets_broken=b["targets_broken"], steps=n, cleared=False, native_failure=True,
                                 sweep_consumed_tick=TAS_SWEEP_TICK, qualified_landing=True)
    check(abs(math.fsum(b["rewards"]) - want) < 1e-9, f"closed form {math.fsum(b['rewards'])} vs {want}")
    return {"steps": n, "targets_broken": b["targets_broken"], "v2_return": math.fsum(a["rewards"]),
            "v3_return": math.fsum(b["rewards"]), "landing": rec["qualified_landing"], "differing_steps": diff,
            "kind": "constructed test trajectory (never observed from a policy; not training data)"}


def g_constructed_land_idle(suite: Suite) -> Dict[str, Any]:
    """CONSTRUCTED: sweep, qualified entry, landing (+2 once while standing 3,000+ ticks), horizon truncation."""
    d = suite.dir("g_constructed_land_idle")
    b = _m3_run(d / "v3", _constructed(LANDING_TICK + 2 - CUT), REWARD_V3, V3_FLAGS)
    rec = b["record"]
    check(b["end"] == "max_episode_steps" and len(b["rewards"]) == 3600 and rec["failure_category"] is None, f"end {b['end']}")
    check(sum(1 for t in b["terms"] if t["crossing_term"]) == 1 and rec["qualified_landing"]["consumed_tick"] == LANDING_TICK,
          "exactly one landing bonus")
    want = v3.expected_return_v3(targets_broken=b["targets_broken"], steps=3600, cleared=False, native_failure=False,
                                 sweep_consumed_tick=TAS_SWEEP_TICK, qualified_landing=True)
    check(abs(math.fsum(b["rewards"]) - want) < 1e-9, "closed form")
    return {"v3_return": math.fsum(b["rewards"]), "targets_broken": b["targets_broken"],
            "kind": "constructed test trajectory (never observed from a policy; not training data)"}


def _worker_run(base: Path, contract: Any, flags: Sequence[Tuple[str, str]], script: Callable[[int], List[int]],
                steps_limit: int) -> Dict[str, Any]:
    from m7_vec_env import M7SubprocVecEnv
    from run_artifacts import read_artifact

    factories, _coord = prepare_workers(base, [dict(rank=0, horizon=3600, preserve_all=True, reward_contract=contract,
                                                    extra_env=tuple(flags), exit_timeout=5.0)], f"m7j_{contract.contract}")
    venv = M7SubprocVecEnv(factories, step_timeout=120)
    out: Dict[str, Any] = {}
    try:
        venv.reset()
        for i in range(steps_limit):
            _o, rew, dones, infos = venv.step(np.array([script(i)]))
            if dones[0]:
                out = {"steps": i + 1, "last_reward": float(rew[0]), "episode": infos[0]["m7_episode"]}
                break
    finally:
        venv.close()
    check(out, "episode did not finish")
    ep = out["episode"]
    adir = Path(ep["artifact_dir"]) if Path(ep["artifact_dir"]).is_absolute() else REPO_ROOT / ep["artifact_dir"]
    out["artifact"] = artifact_rows_are_canonical(adir)
    out["labels"] = read_artifact(adir).metadata["labels"]
    return out


def g_worker_fall_v3(suite: Suite) -> Dict[str, Any]:
    d = suite.dir("g_worker_fall_v3")
    r = _worker_run(d, REWARD_V3, V3_FLAGS, fall_script, 800)
    ep = r["episode"]
    check(ep["end_reason"] == "fall" and ep["steps"] == FALL_TICK + 1 and abs(ep["return"] - (-5.432)) < 1e-9
          and ep["failure_penalty_total"] == -5.0 and ep["reward_contract"] == "btt_reward_v3", f"row {ep}")
    rv = ep.get("reward_v3") or {}
    check(rv.get("failure_category") == v3.FAIL_STANDARD and rv.get("right_sweep") is None
          and r["labels"].get("reward_v3") == rv and r["labels"]["reward_constants"] == REWARD_V3.to_json(), f"v3 record {rv}")
    return {"return": ep["return"], "reward_v3": rv}


def g_worker_horizon_v3(suite: Suite) -> Dict[str, Any]:
    d = suite.dir("g_worker_horizon_v3")
    r = _worker_run(d, REWARD_V3, V3_FLAGS, lambda i: [0, 0], 3700)
    ep = r["episode"]
    check(ep["end_reason"] == "horizon" and ep["steps"] == 3600 and ep["failure_penalty_terms"] == 0
          and abs(ep["return"] - (-3.6 + ep["targets_broken"])) < 1e-9 and abs(r["last_reward"] + 0.001) < 1e-12, f"row {ep}")
    check(ep["reward_v3"]["steps"] == 3600 and ep["reward_v3"]["failure_category"] is None, "record")
    return {"return": ep["return"]}


def g_worker_m7h_crossing(suite: Suite) -> Dict[str, Any]:
    """The verified M7h crossing 83112a8c (premature: target 2 alive) replayed from tick 0 through a v3 worker."""
    from m7h_curriculum import decode_track1

    rec = next(json.loads(line) for line in (REPO_ROOT / "runs" / "m7h" / "campaign" / M7H_CROSSING["run"] / "curriculum"
                                             / "left_episodes.jsonl").read_text(encoding="utf-8").splitlines()
               if line.strip() and json.loads(line)["episode_id"].endswith(M7H_CROSSING["suffix"]))
    acts = [list(decode_track1(a)) for a in bytes.fromhex(rec["actions_hex"])]
    d = suite.dir("g_worker_m7h_crossing")
    r = _worker_run(d, REWARD_V3, V3_FLAGS, lambda i: acts[i], len(acts) + 5)
    ep = r["episode"]
    rv = ep["reward_v3"]
    check(ep["native_action_digest"] == rec["full_digest"] and ep["steps"] == M7H_CROSSING["rows"], "replay not exact")
    check(abs(ep["return"] - M7H_CROSSING["v2_return"]) < 1e-9 and ep["failure_penalty_total"] == -5.0, f"return {ep['return']}")
    check(rv["first_entry"]["class"] == v3.OVER_WALL and not rv["first_entry"]["qualified"]
          and rv["first_line3_landing"]["consumed_tick"] == 3004 and not rv["first_line3_landing"]["qualified"]
          and rv["qualified_landing"] is None and rv["right_sweep"] is None and 2 not in rv["broken_ids"], f"record {rv}")
    return {"return": ep["return"], "entry": rv["first_entry"], "landing": rv["first_line3_landing"]}


def g_wiring(suite: Suite) -> Dict[str, Any]:
    from btt_parallel import build_worker_env

    d = suite.dir("g_wiring")
    out = {}
    for name, kw in {"no_diag_flag": dict(extra_env=tuple(FLAGS)), "horizon_300": dict(extra_env=V3_FLAGS, horizon=300)}.items():
        facs, _ = prepare_workers(d / name, [dict(rank=0, horizon=kw.pop("horizon", 3600), reward_contract=REWARD_V3, **kw)],
                                  f"wiring_{name}")
        try:
            build_worker_env(facs[0].spec)
            raise CaseFailure(f"{name}: worker built")
        except ValueError as exc:
            out[name] = str(exc)[:160]
    check(not battleship_pids(), "a refused worker launched a process")
    return out


def _derive(suite: Suite, profile: Path, name: str, **changes: Any) -> ec.Experiment:
    values = dict(ec.load_experiment(profile).values)
    values.update({"run.output_root": str(suite.root), "run.name": name, **changes})
    d = suite.root / "configs"
    d.mkdir(exist_ok=True)
    p = d / f"{name}.toml"
    p.write_text(ec.to_toml_text(values, header=f"derived by rl/m7j_tests.py from {profile.name}"), encoding="utf-8")
    return ec.load_experiment(p)


SMOKE = {"environment.process_count": 2, "ppo.n_steps": 2560, "run.total_transitions": 15360, "checkpoint.interval": 5120,
         "evaluation.interval": 0, "evaluation.initial": False, "evaluation.final": True, "evaluation.deterministic_episodes": 1,
         "evaluation.stochastic_episodes": 2, "artifacts.periodic_episodes": 2, "run.mode": "train"}


def _rows(run: Path) -> List[Dict[str, Any]]:
    p = run / "metrics" / "episodes.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.is_file() else []


def _v3_closed_form(row: Dict[str, Any], steps_key: str = "steps") -> float:
    rv = row["reward_v3"]
    return v3.expected_return_v3(targets_broken=row["targets_broken"], steps=row[steps_key], cleared=row["cleared"],
                                 native_failure=row["end_reason"] == "fall",
                                 sweep_consumed_tick=(rv["right_sweep"] or {}).get("consumed_tick"),
                                 qualified_landing=rv["qualified_landing"] is not None)


def g_ppo_smoke_v3(suite: Suite) -> Dict[str, Any]:
    from m7_evaluation import checkpoint_reward_contract, read_checkpoint_set
    from m7_trainer import M7PPO, config_from_experiment, run_training

    exp = _derive(suite, PILOT_TOML, "v3_ppo_smoke", **SMOKE)
    check(exp.reward is REWARD_V3 and dict(exp.extra_env).get(DIAG[0]) == "1", "derived profile")
    s = run_training(config_from_experiment(exp))
    check(s["status"] == "completed" and s["cleanup"]["leak_free"] and s["user_config"]["byte_identical"], f"{s['status']}")
    check(s["timesteps"]["sb3_num_timesteps"] == 15360, str(s["timesteps"]))
    run = suite.root / "v3_ppo_smoke"
    rows = [r for r in _rows(run) if r["end_reason"] != "aborted"]
    check(rows, "no finished episode")
    bad = [(r["rank"], r["worker_episode"], r["return"], _v3_closed_form(r)) for r in rows
           if abs(r["return"] - _v3_closed_form(r)) > 1e-9 or r["reward_contract"] != "btt_reward_v3"]
    check(not bad, f"rows disagree with the v3 closed form: {bad}")
    rj = json.loads((run / "run.json").read_text(encoding="utf-8"))
    check(rj["reward_contract"] == REWARD_V3.to_json() and rj["m6_flags"].get(DIAG[0]) == "1", "run.json")
    for sdir in sorted((run / "checkpoints").iterdir()) + [run / "final"]:
        meta = read_checkpoint_set(sdir)
        check(checkpoint_reward_contract(meta) is REWARD_V3 and meta["reward_contract"] == REWARD_V3.to_json(), sdir.name)
    model = M7PPO.load(str(run / "final" / "model.zip"), device="cpu")
    check(model.m7_reward_contract == REWARD_V3.to_json(), "model.zip contract")
    ev_dir = next((run / "evaluations").iterdir())
    ev = json.loads((ev_dir / "evaluation_summary.json").read_text(encoding="utf-8"))
    check(ev["reward_contract"] == REWARD_V3.to_json() and ev.get("extra_env", {}).get(DIAG[0]) == "1", "evaluation flags")
    eval_rows = []
    for mode in ("deterministic", "stochastic"):
        m = ev["modes"][mode]
        check(m["frozen_check"]["policy_parameters_unchanged"] and m["frozen_check"]["obs_rms_unchanged"], f"{mode} frozen")
        for e in m["episodes"]:
            eval_rows.append(e["raw_return"])
    return {"episodes": len(rows), "returns": [round(r["return"], 6) for r in rows], "eval_raw_returns": eval_rows,
            "e2e_tps": s["throughput"]["end_to_end_transitions_per_s"],
            "sweeps": sum(1 for r in rows if r["reward_v3"]["right_sweep"])}


def g_resume_v3(suite: Suite) -> Dict[str, Any]:
    from m7_evaluation import CheckpointError
    from m7_trainer import config_from_experiment, run_training

    src = suite.root / "v3_ppo_smoke" / "checkpoints" / "ckpt_000005120"
    check(src.is_dir(), "run g_ppo_smoke_v3 first")
    common = {**SMOKE, "run.total_transitions": 10240, "evaluation.final": False, "run.mode": "resume",
              "resume.source_checkpoint": str(src)}
    rejected = {}
    for name, (profile, changes) in {"to_v2": (V2_TOML, {}), "diag_off": (PILOT_TOML, {"contracts.reward": "btt_reward_v2"})}.items():
        exp = _derive(suite, profile, f"v3_rejected_{name}", **{**common, **changes})
        try:
            run_training(config_from_experiment(exp))
            raise CaseFailure(f"{name}: resume accepted")
        except (CheckpointError, ec.ConfigError) as exc:
            rejected[name] = str(exc)[:200]
        check(not (suite.root / f"v3_rejected_{name}").exists(), f"{name}: directory created")
    exp = _derive(suite, PILOT_TOML, "v3_resumed", **common)
    s = run_training(config_from_experiment(exp))
    check(s["status"] == "completed" and s["timesteps"]["sb3_num_timesteps"] == 10240, f"resume {s['status']}")
    return {"rejected": rejected, "resumed": s["timesteps"]}


UNIT_CASES: Dict[str, Callable[[Suite], Dict[str, Any]]] = {
    "u_contract_identity": u_contract_identity, "u_geometry": u_geometry, "u_timing": u_timing, "u_classify": u_classify,
    "u_state": u_state, "u_v2_parity": u_v2_parity, "u_config": u_config, "u_wrappers": u_wrappers,
    "u_ranking": u_ranking,
}
GAME_CASES: Dict[str, Callable[[Suite], Dict[str, Any]]] = {
    "g_tas_v3": g_tas_v3, "g_constructed_land_fall": g_constructed_land_fall,
    "g_constructed_land_idle": g_constructed_land_idle, "g_worker_fall_v3": g_worker_fall_v3,
    "g_worker_horizon_v3": g_worker_horizon_v3, "g_worker_m7h_crossing": g_worker_m7h_crossing, "g_wiring": g_wiring,
    "g_ppo_smoke_v3": g_ppo_smoke_v3, "g_resume_v3": g_resume_v3,
}
ALL_CASES = {**UNIT_CASES, **GAME_CASES}


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cases", nargs="*", help="unit | game | all | case names")
    p.add_argument("--root", default=None)
    a = p.parse_args(argv)
    sel = a.cases or ["all"]
    names: List[str] = []
    for s in sel:
        names += list(UNIT_CASES) if s == "unit" else list(GAME_CASES) if s == "game" else list(ALL_CASES) if s == "all" else [s]
    unknown = [n for n in names if n not in ALL_CASES]
    if unknown:
        p.error(f"unknown case(s) {unknown}")
    if "g_resume_v3" in names and "g_ppo_smoke_v3" not in names:
        names.insert(names.index("g_resume_v3"), "g_ppo_smoke_v3")
    from m7_runtime import file_fingerprint, install_kill_on_close_job, wait_until_no_process

    install_kill_on_close_job()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = (Path(a.root) if a.root else REPO_ROOT / "runs" / "m7j" / f"_tests_{stamp}").resolve()
    root.mkdir(parents=True, exist_ok=False)
    suite = Suite(root)
    user_cfg = file_fingerprint(USER_CONFIG)
    game = any(n in GAME_CASES for n in names)
    if game and battleship_pids():
        log(f"ERROR: BattleShip already running: {battleship_pids()}")
        return 2
    log(f"M7j tests: {len(names)} case(s), output {root}")
    failures = 0
    for name in names:
        t0 = time.perf_counter()
        try:
            details = ALL_CASES[name](suite)
            ok, error = True, None
        except Exception as exc:  # noqa: BLE001
            ok, error, details = False, f"{type(exc).__name__}: {exc}", {"traceback": traceback.format_exc()[-4000:]}
        left = wait_until_no_process(timeout=20) if name in GAME_CASES else []
        cfg_ok = file_fingerprint(USER_CONFIG).get("sha256") == user_cfg.get("sha256")
        if left or not cfg_ok:
            ok = False
            error = (error or "") + f" | leaked {left}" * bool(left) + " | user config bytes changed" * (not cfg_ok)
        failures += 0 if ok else 1
        suite.results[name] = {"ok": ok, "error": error, "wall_s": round(time.perf_counter() - t0, 2), "details": details}
        log(f"{'PASS' if ok else 'FAIL'} {name} ({suite.results[name]['wall_s']} s)" + (f": {error}" if error else ""))
        with open(root / "m7j_tests_results.json", "w", encoding="utf-8", newline="\n") as fp:
            json.dump({"cases": suite.results, "user_config_start": user_cfg}, fp, indent=2, default=str)
    log(f"M7j tests: {len(names) - failures}/{len(names)} PASS; results {root / 'm7j_tests_results.json'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
