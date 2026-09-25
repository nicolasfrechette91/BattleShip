#!/usr/bin/env python3
"""M7k tests: btt_reward_v3_t2 (opt-in; btt_reward_v3 and v2 unchanged).

    python rl/m7k_tests.py unit | game | all | <case> ...

Unit: contract identity (v1 / v2 / v3 JSON unchanged, v3_t2 frozen and fingerprinted, round trip, tampering refused,
custom cannot claim it), the timing formula and bounds, one-time payment (also with several targets on one tick and
on terminal steps), bit-identical v3 parity on every step where target 2 does not break (random property test), the
per-episode record, strict configuration (obs v2 / horizon / curriculum / altered values refused; historical
fingerprints unchanged), wrapper and evaluator dispatch.
Game: the TAS through the v3_t2 wrapper against v3 (identical observations, rewards differing on the target-2 step
only), the recorded late seven-right episode 9a130d1f and a recorded no-target-2 episode through a v3_t2 worker, a
bounded PPO smoke with a final evaluation, and resume refusals between v3 and v3_t2.
Outputs: runs/m7k/_tests_<utc>/. The user crossing fixtures are not read. Native RNG state is never read.
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
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import btt_reward_t2 as t2  # noqa: E402
import btt_reward_v3 as v3  # noqa: E402
import experiment_config as ec  # noqa: E402
import m7j_tests as mj  # noqa: E402
from btt_rewards import (REWARD_V2, REWARD_V3, REWARD_V3_T2, RewardContractError, make_reward_contract,  # noqa: E402
                         reward_contract_from_json, reward_extra_env)
from m7_smoke import CaseFailure, Suite, battleship_pids, check, log, USER_CONFIG  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
PILOT_TOML = REPO_ROOT / "rl" / "configs" / "m7k" / "m7k_v3t2_pilot_s0.toml"
V3_JSON_SHA = "d9447d471b95dd59533dfd87192e8eff5e059a6fd42c8bc380e3e27ee6037196"   # registered in M7j
TAS_T2_TICK = 163
LATE_SEVEN = {"run": "m7h_f_s2", "label": "final", "mode": "stochastic", "suffix": "9a130d1f", "t2_tick": 3570}
F = (1 << 10) - 1


def _canon_sha(c: Any) -> str:
    import hashlib

    return hashlib.sha256(json.dumps(c.to_json(), sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()


# -- unit ------------------------------------------------------------------------------------------------------------


def u_contract(s: Suite) -> Dict[str, Any]:
    check(json.dumps(REWARD_V2.to_json()) == mj.V2_JSON and _canon_sha(REWARD_V3) == V3_JSON_SHA, "v2 / v3 changed")
    j = REWARD_V3_T2.to_json()
    mt = j["route"]["moving_target"]
    check(j["contract"] == "btt_reward_v3_t2" and REWARD_V3_T2.canonical and REWARD_V3_T2 != REWARD_V3
          and REWARD_V3_T2.values() == REWARD_V3.values()
          and {k: v for k, v in j["route"].items() if k != "moving_target"} == REWARD_V3.route_json()
          and mt == {"rule": "btt_moving_target_timing_v1", "target_id": 2, "timing_max": 2.0}, f"identity {mt}")
    check(make_reward_contract("btt_reward_v3_t2", REWARD_V2.values()) is REWARD_V3_T2
          and reward_contract_from_json(j) is REWARD_V3_T2 and reward_extra_env(REWARD_V3_T2) == (("SSB64_RL_TARGET_DIAG", "1"),),
          "canonical / round trip / flags")
    bad = json.loads(json.dumps(j))
    bad["route"]["moving_target"]["timing_max"] = 3.0
    for rec in (bad, REWARD_V3.to_json() | {"contract": "btt_reward_v3_t2"}, j | {"contract": "btt_reward_v3"}):
        try:
            reward_contract_from_json(rec)
            raise CaseFailure(f"accepted {rec['contract']}")
        except RewardContractError:
            pass
    custom = make_reward_contract("custom", REWARD_V2.values())
    check("route" not in custom.to_json(), "custom has no route block")
    return {"sha256": _canon_sha(REWARD_V3_T2), "moving_target": mt}


def u_timing(s: Suite) -> Dict[str, Any]:
    check(t2.moving_target_timing(0) == 2.0 * 3599 / 3600 and t2.moving_target_timing(3599) == 0.0, "bounds")
    check(all(t2.moving_target_timing(t) > t2.moving_target_timing(t + 1) for t in range(3599)), "decreasing")
    check(t2.moving_target_timing(TAS_T2_TICK) == 2.0 * (3600 - 164) / 3600, "TAS tick")
    for bad in (-1, 3600):
        try:
            t2.moving_target_timing(bad)
            raise CaseFailure(f"{bad} accepted")
        except v3.RewardV3Violation:
            pass
    return {"t0": t2.moving_target_timing(0), "tas": t2.moving_target_timing(TAS_T2_TICK)}


def _pair(masks: Sequence[int], fails: Sequence[bool] = (), clears: Sequence[bool] = ()) -> Any:
    a, b = t2.MovingTargetRouteRewardState(), v3.RouteRewardState(REWARD_V3)
    a.start(v3._initial())
    b.start(v3._initial())
    ta, tb = [], []
    for t, m in enumerate(masks):
        f = bool(fails[t]) if t < len(fails) else False
        c = bool(clears[t]) if t < len(clears) else False
        r = v3._reply(t, x=0.0, y=0.0, remaining=m, game_status=5 if f else 1, state=6 if c else 2)
        ta.append(a.step(r, clear=c, native_failure=f))
        tb.append(b.step(r, clear=c, native_failure=f))
    return a, ta, tb


def u_state(s: Suite) -> Dict[str, Any]:
    # one-time; several targets (incl. target 2) on one tick; re-reported mask pays nothing
    m = F & ~((1 << 2) | (1 << 4) | (1 << 8))
    a, ta, tb = _pair([F, m, m, m])
    diff = [i for i, (x, y) in enumerate(zip(ta, tb)) if x.total != y.total]
    check(diff == [1] and ta[1].newly_broken == 3 and ta[1].moving_target_term == t2.moving_target_timing(1), f"one-time {diff}")
    # target 2 on the native-failure step and on the clear step
    a, ta, tb = _pair([F, F & ~(1 << 2)], fails=[False, True])
    check(ta[1].failure_term == -5.0 and ta[1].moving_target_term == t2.moving_target_timing(1), "on the failure step")
    a, ta, tb = _pair([F & ~(F ^ (1 << 2)), 0], clears=[False, True])
    check(ta[1].clear_term == 10.0 and ta[1].moving_target_term == t2.moving_target_timing(1)
          and ta[1].sweep_term > 0, "on the clear step (with the sweep)")
    rec = a.record()
    check(rec["moving_target"]["consumed_tick"] == 1 and rec["reward_contract"] == "btt_reward_v3_t2"
          and math.isclose(rec["term_totals"]["total"], sum(x.total for x in ta)), "record")
    try:
        t2.make_route_state(REWARD_V2)
        raise CaseFailure("v2 accepted as a route contract")
    except RewardContractError:
        pass
    check(type(t2.make_route_state(REWARD_V3)) is v3.RouteRewardState, "v3 keeps its own state")
    return {"ok": True}


def u_parity(s: Suite) -> Dict[str, Any]:
    """Random masks and positions: v3_t2 differs from v3 exactly on the target-2 step, by exactly the credit."""
    rng = random.Random(20260925)
    trials = 0
    for trial in range(300):
        order = list(range(10))
        rng.shuffle(order)
        mask = F
        a, b = t2.MovingTargetRouteRewardState(), v3.RouteRewardState(REWARD_V3)
        a.start(v3._initial())
        b.start(v3._initial())
        x, y = 0.0, -2550.0
        n = rng.randint(5, 400)
        seen = []
        for t in range(n):
            if order and rng.random() < 0.06:
                mask &= ~(1 << order.pop())
            x = max(-5000.0, min(5000.0, x + rng.uniform(-400, 400)))
            y = max(-9000.0, min(5000.0, y + rng.uniform(-600, 600)))
            fail = t == n - 1 and rng.random() < 0.5
            r = v3._reply(t, x=x, y=y, g=0 if rng.random() < 0.2 and not fail else 1, remaining=mask,
                          game_status=5 if fail else 1)
            ta = a.step(r, clear=False, native_failure=fail)
            tb = b.step(r, clear=False, native_failure=fail)
            if ta.total != tb.total:
                seen.append((t, ta.total - (tb.total + ta.moving_target_term), ta.moving_target_term))
        broke = not (mask >> 2 & 1)
        check(len(seen) == (1 if broke and a.moving["moving_target_term"] != 0.0 else 0)
              and all(d[1] == 0.0 for d in seen), f"trial {trial}: {seen}")
        trials += 1
    return {"trials": trials}


def u_config(s: Suite) -> Dict[str, Any]:
    exp = ec.load_experiment(PILOT_TOML)
    check(exp.reward is REWARD_V3_T2 and dict(exp.extra_env).get("SSB64_RL_TARGET_DIAG") == "1", "pilot profile")
    control = ec.load_experiment(REPO_ROOT / "rl" / "configs" / "m7g" / "m7g_s0_v1.toml")
    diff = ec.compare_compatibility(exp.compatibility_view(), control.compatibility_view())
    check(set(diff) == {"contracts.reward_resolved", "environment.extra_env"}, f"vs Phase K control {sorted(diff)}")
    for name in mj.HISTORICAL_PROFILES:
        e = ec.load_experiment(REPO_ROOT / "rl" / "configs" / f"{name}.toml")
        check(e.semantic_fingerprint[:16] == mj.HISTORICAL_FINGERPRINTS[name], f"{name} fingerprint changed")
    v3p = ec.load_experiment(mj.PILOT_TOML)
    check(v3p.semantic_fingerprint == "004df8a58ad54629cc135c35b3c2844c03153aad4e6d750848eca28fbae6bb81",
          "the registered M7j v3 pilot profile changed")
    rejected = {}
    for name, changes in {"obs_v2": {"contracts.observation": "btt_policy_obs_v2_spatial", "ppo.policy": "MultiInputPolicy"},
                          "horizon": {"environment.horizon": 1800}, "altered": {"reward.failure_penalty": -4.0}}.items():
        try:
            ec.parse_toml_text(ec.to_toml_text(dict(exp.values, **changes), header=name))
            raise CaseFailure(f"{name} accepted")
        except ec.ConfigError as exc:
            rejected[name] = str(exc)[:160]
    try:
        ec.parse_toml_text(ec.to_toml_text(dict(exp.values), header="cur") +
                           '\n[curriculum]\ncontract = "btt_curriculum_frontier_v1"\ntick0_probability = 0.5\n'
                           'max_prefix_ticks = 3000\npre_fall_exclusion_ticks = 60\ncell_size = 300\n')
        raise CaseFailure("curriculum accepted")
    except ec.ConfigError as exc:
        rejected["curriculum"] = str(exc)[:160]
    return {"semantic": exp.semantic_fingerprint, "rejected": rejected}


def u_dispatch(s: Suite) -> Dict[str, Any]:
    import gymnasium as gym

    import btt_parallel as bp
    from m7_evaluation import EvaluationSettings
    from m7j_reward_env import M7RouteRewardWrapper

    class Env(gym.Env):
        observation_space = gym.spaces.Discrete(2)
        action_space = gym.spaces.Discrete(2)
        max_episode_steps = 3600

    try:
        bp.M7RewardWrapper(Env(), REWARD_V3_T2)
        raise CaseFailure("M7RewardWrapper accepted v3_t2")
    except ValueError:
        pass
    w = M7RouteRewardWrapper(Env(), REWARD_V3_T2, extra_env={"SSB64_RL_TARGET_DIAG": "1"})
    st = EvaluationSettings(executable="x", reward=REWARD_V3_T2)
    check(w.reward_contract is REWARD_V3_T2 and dict(st.effective_extra_env()).get("SSB64_RL_TARGET_DIAG") == "1"
          and st.records_flags, "wrapper / evaluator")
    return {"ok": True}


# -- game ------------------------------------------------------------------------------------------------------------


def g_tas_t2(s: Suite) -> Dict[str, Any]:
    d = s.dir("g_tas_t2")
    rows = mj._tas_rows()
    a = mj._m3_run(d / "v3", rows, REWARD_V3, mj.V3_FLAGS)
    b = _m3_run_t2(d / "v3_t2", rows)
    check(a["observations"] == b["observations"] and a["end"] == b["end"] == "native_clear", "gameplay")
    diff = [i for i, (x, y) in enumerate(zip(a["rewards"], b["rewards"])) if x != y]
    want = math.fsum(a["rewards"]) + t2.moving_target_timing(TAS_T2_TICK)
    check(diff == [TAS_T2_TICK] and abs(math.fsum(b["rewards"]) - want) < 1e-9
          and b["record"]["moving_target"]["consumed_tick"] == TAS_T2_TICK, f"steps {diff}")
    return {"v3": math.fsum(a["rewards"]), "v3_t2": math.fsum(b["rewards"])}


def _m3_run_t2(out: Path, actions: Sequence[Any]) -> Dict[str, Any]:
    from battleship_env import native_to_action
    from battleship_process import LaunchConfig
    from btt_parallel import M7BattleShipBTTEnv
    from m7_runtime import PortCandidates, prepare_worker_runtime
    from m7j_reward_env import M7RouteRewardWrapper

    out.mkdir(parents=True)
    prepare_worker_runtime(out / "runtime", mj.EXECUTABLE)
    base = M7BattleShipBTTEnv(LaunchConfig(executable=mj.EXECUTABLE, working_dir=out / "runtime", run_root=out / "episodes",
                                           extra_env=dict(mj.V3_FLAGS)), max_episode_steps=3600, rank=0, ports=PortCandidates(0))
    env = M7RouteRewardWrapper(base, REWARD_V3_T2, extra_env=dict(mj.V3_FLAGS))
    obs, rewards, end = [], [], None
    try:
        o, _ = env.reset()
        obs.append({k: np.asarray(v).item() for k, v in o.items()})
        for bb, x, y in actions:
            o, r, term, trunc, info = env.step(native_to_action(bb, x, y))
            obs.append({k: np.asarray(v).item() for k, v in o.items()})
            rewards.append(r)
            if term or trunc:
                end = info.get("termination_reason") or info.get("truncation_reason")
                break
    finally:
        env.close()
    return {"observations": obs, "rewards": rewards, "end": end, "record": env.last_record}


def _eval_episode(run: str, label: str, mode: str, pred: Callable[[Dict[str, Any]], bool]) -> Dict[str, Any]:
    d = json.loads((REPO_ROOT / "runs" / "m7h" / "campaign" / "_eval" / run / label / mode / "evaluation.json")
                   .read_text(encoding="utf-8"))
    return next(e for e in sorted(d["episodes"], key=lambda e: e.get("order", 0)) if pred(e))


def _worker_replay_t2(d: Path, e: Dict[str, Any]) -> Dict[str, Any]:
    import m7f_trace as tr
    from btt_learning import native_to_track1

    acts, meta = tr.artifact_actions(REPO_ROOT / e["artifact_dir"])
    md = [list(native_to_track1(b, x, y)) for (b, x, y, _t) in acts]
    r = mj._worker_run(d, REWARD_V3_T2, mj.V3_FLAGS, lambda i: md[i], len(md) + 5)
    ep = r["episode"]
    check(ep["native_action_digest"] == e["native_action_digest"] and ep["steps"] == len(md), "replay not exact")
    return ep


def g_worker_late_seven(s: Suite) -> Dict[str, Any]:
    e = _eval_episode(LATE_SEVEN["run"], LATE_SEVEN["label"], LATE_SEVEN["mode"],
                      lambda e: e["episode_id"].endswith(LATE_SEVEN["suffix"]))
    ep = _worker_replay_t2(s.dir("g_worker_late_seven"), e)
    rv = ep["reward_v3"]
    want_v3 = e["raw_return"] + 3.0 + v3.sweep_timing(3570)
    want = want_v3 + t2.moving_target_timing(LATE_SEVEN["t2_tick"])
    check(abs(ep["return"] - want) < 1e-9 and rv["moving_target"]["consumed_tick"] == LATE_SEVEN["t2_tick"]
          and rv["right_sweep"]["consumed_tick"] == 3570 and ep["reward_contract"] == "btt_reward_v3_t2", f"{ep['return']} vs {want}")
    return {"v2": e["raw_return"], "v3_t2": ep["return"], "moving_target_term": rv["moving_target"]["moving_target_term"]}


def g_worker_no_t2(s: Suite) -> Dict[str, Any]:
    e = _eval_episode("m7h_f_s1", "final", "stochastic", lambda e: 2 not in (e["eval_metrics"]["broken_ids"] or [])
                      and e["end_reason"] == "horizon")
    ep = _worker_replay_t2(s.dir("g_worker_no_t2"), e)
    check(abs(ep["return"] - e["raw_return"]) < 1e-9 and ep["reward_v3"]["moving_target"] is None, "v3_t2 == v2 without target 2")
    return {"return": ep["return"]}


SMOKE = dict(mj.SMOKE)


def g_ppo_smoke_t2(s: Suite) -> Dict[str, Any]:
    from m7_evaluation import checkpoint_reward_contract, read_checkpoint_set
    from m7_trainer import M7PPO, config_from_experiment, run_training

    exp = mj._derive(s, PILOT_TOML, "t2_ppo_smoke", **SMOKE)
    run_s = run_training(config_from_experiment(exp))
    check(run_s["status"] == "completed" and run_s["user_config"]["byte_identical"], run_s["status"])
    run = s.root / "t2_ppo_smoke"
    rows = [r for r in mj._rows(run) if r["end_reason"] != "aborted"]
    bad = []
    for r in rows:
        rv = r["reward_v3"]
        want = t2.expected_return_v3_t2(moving_target_consumed_tick=(rv["moving_target"] or {}).get("consumed_tick"),
                                        targets_broken=r["targets_broken"], steps=r["steps"], cleared=r["cleared"],
                                        native_failure=r["end_reason"] == "fall",
                                        sweep_consumed_tick=(rv["right_sweep"] or {}).get("consumed_tick"),
                                        qualified_landing=rv["qualified_landing"] is not None)
        if abs(r["return"] - want) > 1e-9 or r["reward_contract"] != "btt_reward_v3_t2":
            bad.append((r["episode_id"], r["return"], want))
    check(rows and not bad, f"rows vs closed form: {bad}")
    for sd in sorted((run / "checkpoints").iterdir()) + [run / "final"]:
        check(checkpoint_reward_contract(read_checkpoint_set(sd)) is REWARD_V3_T2, sd.name)
    check(M7PPO.load(str(run / "final" / "model.zip"), device="cpu").m7_reward_contract == REWARD_V3_T2.to_json(), "model")
    ev = json.loads((next((run / "evaluations").iterdir()) / "evaluation_summary.json").read_text(encoding="utf-8"))
    check(ev["reward_contract"] == REWARD_V3_T2.to_json() and ev["extra_env"].get("SSB64_RL_TARGET_DIAG") == "1", "evaluation")
    return {"episodes": len(rows), "returns": [round(r["return"], 6) for r in rows],
            "cleanup": run_s["cleanup"], "e2e": run_s["throughput"]["end_to_end_transitions_per_s"]}


def g_resume_refused(s: Suite) -> Dict[str, Any]:
    from m7_evaluation import CheckpointError
    from m7_trainer import config_from_experiment, run_training

    src = s.root / "t2_ppo_smoke" / "checkpoints" / "ckpt_000005120"
    check(src.is_dir(), "run g_ppo_smoke_t2 first")
    exp = mj._derive(s, mj.PILOT_TOML, "t2_to_v3", **{**SMOKE, "run.total_transitions": 10240, "evaluation.final": False,
                                                       "run.mode": "resume", "resume.source_checkpoint": str(src)})
    try:
        run_training(config_from_experiment(exp))
        raise CaseFailure("v3 resume from a v3_t2 checkpoint accepted")
    except (CheckpointError, ec.ConfigError) as exc:
        msg = str(exc)[:200]
    check(not (s.root / "t2_to_v3").exists(), "directory created")
    return {"refused": msg}


UNIT = {"u_contract": u_contract, "u_timing": u_timing, "u_state": u_state, "u_parity": u_parity, "u_config": u_config,
        "u_dispatch": u_dispatch}
GAME = {"g_tas_t2": g_tas_t2, "g_worker_late_seven": g_worker_late_seven, "g_worker_no_t2": g_worker_no_t2,
        "g_ppo_smoke_t2": g_ppo_smoke_t2, "g_resume_refused": g_resume_refused}
ALL = {**UNIT, **GAME}


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cases", nargs="*")
    a = p.parse_args(argv)
    names: List[str] = []
    for c in a.cases or ["all"]:
        names += list(UNIT) if c == "unit" else list(GAME) if c == "game" else list(ALL) if c == "all" else [c]
    unknown = [n for n in names if n not in ALL]
    if unknown:
        p.error(f"unknown {unknown}")
    if "g_resume_refused" in names and "g_ppo_smoke_t2" not in names:
        names.insert(names.index("g_resume_refused"), "g_ppo_smoke_t2")
    from m7_runtime import file_fingerprint, install_kill_on_close_job, wait_until_no_process

    install_kill_on_close_job()
    root = REPO_ROOT / "runs" / "m7k" / f"_tests_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    root.mkdir(parents=True)
    suite = Suite(root)
    cfg = file_fingerprint(USER_CONFIG)
    if any(n in GAME for n in names) and battleship_pids():
        log(f"ERROR: BattleShip already running: {battleship_pids()}")
        return 2
    fails = 0
    for n in names:
        t0 = time.perf_counter()
        try:
            det, ok, err = ALL[n](suite), True, None
        except Exception as exc:  # noqa: BLE001
            det, ok, err = {"traceback": traceback.format_exc()[-3000:]}, False, f"{type(exc).__name__}: {exc}"
        left = wait_until_no_process(timeout=20) if n in GAME else []
        if left or file_fingerprint(USER_CONFIG).get("sha256") != cfg.get("sha256"):
            ok, err = False, (err or "") + f" | leaked {left} / user config changed"
        fails += not ok
        suite.results[n] = {"ok": ok, "error": err, "wall_s": round(time.perf_counter() - t0, 2), "details": det}
        log(f"{'PASS' if ok else 'FAIL'} {n} ({suite.results[n]['wall_s']} s)" + (f": {err}" if err else ""))
        (root / "m7k_tests_results.json").write_text(json.dumps({"cases": suite.results}, indent=1, default=str),
                                                     encoding="utf-8")
    log(f"M7k tests: {len(names) - fails}/{len(names)} PASS; {root}")
    return 0 if not fails else 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
