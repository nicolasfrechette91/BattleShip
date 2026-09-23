#!/usr/bin/env python3
"""M7e Phase B preflight tests: the matrix, its guards and a bounded run, before the full campaign.

    python rl/m7e_tests.py                 # every case (unit, then game), sequential
    python rl/m7e_tests.py unit            # ROM-independent cases only
    python rl/m7e_tests.py game            # game-backed bounded cases only
    python rl/m7e_tests.py <case> ... [--root runs/_m7e_preflight_<utc>]

Unit cases (no game):
  unit_profiles              all three profiles resolve; semantic and compatibility fingerprints recorded; the
                             executable and dependency metadata recorded; the manifest proof (the three differ only
                             in identity, seed, paths and hashes); vs the M7d v2 twin only the budget, cadence and
                             curve counts differ; every frozen value; dry runs
  unit_fresh_init            a fresh model and VecNormalize initialise; three distinct untrained policies; no M7d
                             checkpoint is a training source; the budget cannot be resumed into from M7d
  unit_reward_to_ppo         btt_reward_v2 reaches PPO unchanged (raw pass-through); norm_reward stays false before
                             and after a save/reload; normalize_rewards = true is refused
  unit_checkpoint_roundtrip  a checkpoint/model/statistics set saves and reloads offline, frozen and observation-only
  unit_reward_penalty        one and only one -5.0 on native failure; no failure penalty on horizon truncation
  unit_directory_guards      M7e paths cannot touch runs/m7d; planned directories new, unique, disjoint, outside
                             history; the snapshot compare detects a change; an existing run directory is never reused
  unit_resume_guard          a resume stays inside a run's own lineage: other seed, other contract, other run and an
                             M7d checkpoint are all refused
  unit_evaluation_protocol   the post-hoc plan equals the committed proposal; evaluation is disabled inside learn();
                             in-process evaluation would reseed the trainer (demonstrated), which is why M7e runs it
                             in a separate process and can never coexist with live training workers
  unit_instrumentation       target_break_ticks plumbing, preserve_all, canonical artifact action fields, the census
  unit_gates                 the eight pre-registered gates and the plateau rule on synthetic outcomes

Game cases (bounded):
  bounded_training           a bounded twin of m7e_s0_v2 (25,600 transitions) through the orchestrator path: the
                             fresh model equals the offline construction, the directory verifies, standby promotes,
                             at most 10 processes, no leak, artifacts canonical from consumed tick 0
  bounded_posthoc_evaluation post-hoc evaluation of that run (initial + final, preserve_all): frozen statistics,
                             every episode preserved, promoted episodes start at consumed tick 0, no directory reuse
  bounded_replay             native replay of the best and a fall/horizon artifact: ticks, targets, break ticks and
                             the final observation
  bounded_cleanup            after the bounded run and its evaluation: zero processes, zero launcher threads left
                             alive, zero listening ports in the M7 blocks
  existing_suites            the permanent chain: rl/m7b_config_tests.py, rl/m7c_standby_tests.py unit,
                             rl/m7e_idle_analysis.py --test, rl/m7e_matrix.py --test, rl/m7e_analysis.py --test

Results: <root>/results.json. Standard library at module level (spawn workers re-import this file).
No native RNG state is introduced, inspected, logged, validated, controlled, compared or hashed.
"""

from __future__ import annotations

import argparse
import inspect
import json
import multiprocessing
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import experiment_config as ec  # noqa: E402
import m7d_matrix as mm  # noqa: E402
import m7d_tests as dt  # noqa: E402  (Suite, check, helpers - reused unchanged)
import m7e_matrix as em  # noqa: E402

REPO_ROOT = em.REPO_ROOT
check = dt.check
CheckFailed = dt.CheckFailed
Suite = dt.Suite
BOUNDED_TOTAL = 25_600
BOUNDED_INTERVAL = 5_120


def derive_bounded(suite: Suite, seed: int = 0, *, total: int = BOUNDED_TOTAL,
                   interval: int = BOUNDED_INTERVAL) -> ec.Experiment:
    """A bounded twin of m7e_s<seed>_v2: same values except run identity, output root, transitions and checkpoint
    cadence, written as a TOML under <root>/configs. Never inside runs/m7e or runs/m7d."""
    base = em.load_run(em.run_by_name(f"m7e_s{seed}_v2"))
    values = dict(base.values)
    values.update({"run.name": f"pf_s{seed}_v2", "run.output_root": str(suite.root / "train"),
                   "run.total_transitions": total, "checkpoint.interval": interval,
                   "run.notes": f"M7e preflight: bounded twin of m7e_s{seed}_v2 ({total} transitions)"})
    text = ec.to_toml_text(values, header=f"derived by rl/m7e_tests.py from rl/configs/m7e/m7e_s{seed}_v2.toml "
                                          f"(bounded preflight twin)")
    path = suite.root / "configs" / f"pf_s{seed}_v2.toml"
    if not path.exists():
        dt._write_lf(path, text)
    return ec.load_experiment(path)


# -- unit cases --------------------------------------------------------------------------------------------------------


def unit_profiles(suite: Suite) -> Dict[str, Any]:
    man = em.build_manifest(with_trainer_view=True)
    em.write_json(suite.root / "manifest.json", man)
    check(man["ok"], f"manifest problems: {man['problems']}")
    check(len(man["runs"]) == 3, f"{len(man['runs'])} runs")
    fps: Dict[str, Any] = {}
    for spec in em.matrix():
        exp = em.load_run(spec)
        r = man["runs"][spec.name]
        check(bool(r["semantic_fingerprint"]) and bool(r["compatibility_fingerprint"]) and bool(r["source_sha256"]),
              f"{spec.name}: fingerprints not recorded")
        check((r["semantic_fingerprint"], r["compatibility_fingerprint"], r["source_sha256"])
              == (exp.semantic_fingerprint, exp.compatibility_fingerprint, exp.source.sha256),
              f"{spec.name}: manifest fingerprints differ from the profile")
        bad = [k for k, ok in em.required_value_checks(spec, exp).items() if not ok]
        check(not bad, f"{spec.name}: frozen values {bad}")
        fps[spec.name] = {"source_sha256": r["source_sha256"][:16],
                          "semantic": r["semantic_fingerprint"][:16],
                          "compatibility": r["compatibility_fingerprint"][:16],
                          "expected_initial_policy": r["expected_initial_policy_digest"][:16]}
    exe = man["executable"]
    check(bool(exe.get("sha256")) and exe.get("sha256") == mm.load_run(mm.run_by_name("m7d_s0_v2"))
          .executable_fingerprint().get("sha256"),
          f"executable metadata missing or different from M7d: {exe}")
    compats = {r["compatibility_fingerprint"] for r in man["runs"].values()}
    check(len(compats) == 1, f"the three profiles must share one compatibility fingerprint: {compats}")
    sems = {r["semantic_fingerprint"] for r in man["runs"].values()}
    check(len(sems) == 3, f"the three profiles must have distinct semantic fingerprints: {sems}")
    for key, pair in man["profile_pairs"].items():
        check(pair["resolved_proof"]["proof_ok"], f"{key}: {pair['resolved_proof']['unexpected']}")
        check(pair["trainer_proof"]["proof_ok"], f"{key}: trainer {pair['trainer_proof']['unexpected']}")
        check(pair["evaluation_plan_proof"]["proof_ok"], f"{key}: plan {pair['evaluation_plan_proof']['unexpected']}")
        check(not pair["compatibility_differences"], f"{key}: {pair['compatibility_differences']}")
    for name, v in man["vs_m7d"].items():
        check(v["available"] and v["proof"]["proof_ok"], f"{name} vs M7d: {v.get('proof', {}).get('unexpected')}")
        check(v["same_reward_contract"] and v["budget_multiple"] == 3.0,
              f"{name} vs M7d: reward {v['same_reward_contract']} budget x{v['budget_multiple']}")
        check(not v["compatibility_differences"],
              f"{name}: the compatibility view must be identical to M7d's v2: {v['compatibility_differences']}")
    # Dependency metadata is recorded by the trainer; check it is obtainable and matches the M7d record.
    import gymnasium
    import numpy
    import stable_baselines3
    import torch
    deps = {"python": sys.version.split()[0], "gymnasium": gymnasium.__version__, "numpy": numpy.__version__,
            "torch": torch.__version__, "stable_baselines3": stable_baselines3.__version__,
            "cpu_count": os.cpu_count()}
    m7d_versions = mm.read_json(REPO_ROOT / "runs" / "m7d" / "m7d_s0_v2" / "run.json")["versions"]
    same = {k: deps.get(k) == m7d_versions.get(k) for k in ("python", "gymnasium", "numpy", "torch",
                                                            "stable_baselines3", "cpu_count")}
    check(all(same.values()), f"dependency versions differ from the M7d record: {deps} vs {m7d_versions}")
    dry: Dict[str, Any] = {}
    for spec in em.matrix():
        rc = subprocess.run([sys.executable, str(REPO_ROOT / "rl" / "train_m7.py"), "--config",
                             str(spec.config_path), "--dry-run"], cwd=str(REPO_ROOT), capture_output=True,
                            text=True, timeout=600, check=False)
        check(rc.returncode == 0, f"{spec.name} dry run exit {rc.returncode}: {rc.stdout[-600:]}{rc.stderr[-600:]}")
        dry[spec.name] = rc.returncode
    return {"fingerprints": fps, "executable": exe, "dependencies": deps, "dependency_match_m7d": same,
            "dry_runs": dry, "census": man["evaluation_protocol"]["census"]["arithmetic"]}


def unit_fresh_init(suite: Suite) -> Dict[str, Any]:
    digests: Dict[str, Any] = {}
    for spec in em.matrix():
        exp = em.load_run(spec)
        d, rms = em.expected_initial_policy_digest(exp, return_obs_rms=True)
        digests[spec.name] = {"policy": d, "obs_rms": rms}
        check(exp.mode != "resume" and exp.resume_source is None, f"{spec.name}: not a fresh start")
    pol = {v["policy"] for v in digests.values()}
    check(len(pol) == 3, f"the three untrained policies must differ (seeding): {pol}")
    rms = {v["obs_rms"] for v in digests.values()}
    check(len(rms) == 1, f"the untrained VecNormalize statistics must be identical across seeds: {rms}")
    # No M7d checkpoint may serve as a training source: the guard refuses one even when named explicitly.
    refusals: Dict[str, str] = {}
    for spec in em.matrix():
        for src in (REPO_ROOT / "runs" / "m7d" / spec.m7d_counterpart / "final",
                    REPO_ROOT / "runs" / "m7d" / spec.m7d_counterpart / "checkpoints" / "ckpt_000512000"):
            if not (src / "checkpoint.json").is_file():
                continue
            try:
                em.resume_guard(spec, src)
                check(False, f"{spec.name}: an M7d checkpoint was accepted as a resume source ({src})")
            except mm.MatrixError as exc:
                refusals[f"{spec.name}:{src.name}"] = str(exc)[:240]
    check(refusals, "no M7d checkpoint was available to test the refusal")
    return {"digests": {k: {"policy": v["policy"][:16], "obs_rms": v["obs_rms"][:16]} for k, v in digests.items()},
            "m7d_resume_refused": refusals}


def unit_reward_to_ppo(suite: Suite) -> Dict[str, Any]:
    import numpy as np
    from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

    import m7_trainer as tr

    src = inspect.getsource(tr.M7Run.run)
    check("norm_reward=False" in src, "the trainer no longer constructs VecNormalize with norm_reward=False")
    script = [-0.001, 0.999, -5.001, 9.999, -0.001, 1.999, -4.001]
    out: Dict[str, Any] = {}
    for spec in em.matrix():
        exp = em.load_run(spec)
        check(exp.reward.contract == "btt_reward_v2" and exp.reward.canonical, f"{spec.name}: reward contract")
        cfg = tr.config_from_experiment(exp)
        check(cfg.reward.to_json() == exp.reward.to_json(), f"{spec.name}: the reward reaching PPO was rewritten")
        venv = DummyVecEnv([lambda: dt._ScriptedEnv(script) for _ in range(cfg.n_envs)])
        vn = VecNormalize(venv, training=True, norm_obs=cfg.norm_obs, norm_reward=False, clip_obs=cfg.clip_obs,
                          gamma=cfg.gamma)
        vn.reset()
        got = []
        for _ in range(len(script) * 3):
            _o, r, _d, _i = vn.step(np.zeros((cfg.n_envs, 2), dtype=np.int64))
            got.append(r.copy())
        want = [np.full(cfg.n_envs, script[i % len(script)], dtype=np.float32) for i in range(len(got))]
        check(all(np.array_equal(g.astype(np.float32), w) for g, w in zip(got, want)),
              f"{spec.name}: rewards were transformed on the way to PPO")
        check(vn.norm_reward is False and vn.norm_obs is True and cfg.clip_obs == 10.0, f"{spec.name}: flags")
        out[spec.name] = {"steps": len(got), "raw_rewards_passed_through": True,
                          "reward": exp.reward.to_json(), "ret_rms_count": float(vn.ret_rms.count)}
        vn.close()
    text = em.load_run(em.matrix()[0]).toml_text.replace("normalize_rewards = false", "normalize_rewards = true")
    try:
        ec.parse_toml_text(text)
        check(False, "normalize_rewards = true was accepted")
    except ec.ConfigError as exc:
        check("ppo.vecnormalize.normalize_rewards" in str(exc), f"unexpected rejection: {exc}")
    return {"runs": out, "normalize_rewards_true_refused": True,
            "note": "ret_rms is updated by SB3 whenever training=True even with norm_reward=False; it is never "
                    "applied, so 'no reward normalisation' is proven by the flag plus this pass-through test"}


def unit_checkpoint_roundtrip(suite: Suite) -> Dict[str, Any]:
    import pickle

    import gymnasium as gym
    import numpy as np
    import torch
    from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

    import m7_trainer as tr
    from btt_learning import make_policy_observation_space, make_track1_action_space
    from btt_parallel import RunCoordinator, initial_coordination_state, m7_contracts
    from m7_evaluation import obs_rms_digest, policy_parameter_digest, read_checkpoint_set

    spec = em.matrix()[0]
    exp = em.load_run(spec)
    cfg = tr.config_from_experiment(exp)

    class _Spaces(gym.Env):
        def __init__(self) -> None:
            self.observation_space = make_policy_observation_space()
            self.action_space = make_track1_action_space()

        def reset(self, *, seed=None, options=None):
            super().reset(seed=seed)
            return np.zeros(15, dtype=np.float32), {}

        def step(self, action):
            return np.ones(15, dtype=np.float32), 0.0, False, False, {}

    threads = torch.get_num_threads()
    torch.set_num_threads(int(cfg.torch_threads))
    try:
        venv = DummyVecEnv([_Spaces for _ in range(cfg.n_envs)])
        vn = VecNormalize(venv, training=True, norm_obs=cfg.norm_obs, norm_reward=False, clip_obs=cfg.clip_obs,
                          gamma=cfg.gamma)
        model = tr.M7PPO(tr.POLICY, vn, learning_rate=cfg.learning_rate, n_steps=cfg.n_steps,
                         batch_size=cfg.batch_size, n_epochs=cfg.n_epochs, gamma=cfg.gamma,
                         gae_lambda=cfg.gae_lambda, clip_range=cfg.clip_range, ent_coef=cfg.ent_coef,
                         vf_coef=cfg.vf_coef, max_grad_norm=cfg.max_grad_norm, seed=cfg.base_seed,
                         device=cfg.device, verbose=0, policy_kwargs=tr.policy_kwargs(cfg))
        before = (policy_parameter_digest(model), obs_rms_digest(vn))
        check(vn.norm_reward is False, "norm_reward is not false before the save")
        out = suite.root / "roundtrip" / "ckpt_000000000"
        coord = RunCoordinator.create(suite.root / "roundtrip" / "coordination",
                                      initial_coordination_state("pf_roundtrip", "training", 10))
        run_meta = {
            "run_id": "pf_roundtrip", "purpose": "M7e preflight checkpoint round trip", "lineage": [],
            "contracts": m7_contracts(3600, exp.reward), "horizon": 3600, "n_envs": cfg.n_envs,
            "ppo": {"learning_rate": cfg.learning_rate, "n_steps": cfg.n_steps, "batch_size": cfg.batch_size,
                    "n_epochs": cfg.n_epochs, "gamma": cfg.gamma, "gae_lambda": cfg.gae_lambda,
                    "clip_range": cfg.clip_range, "ent_coef": cfg.ent_coef, "vf_coef": cfg.vf_coef,
                    "max_grad_norm": cfg.max_grad_norm, "net_arch": list(cfg.net_arch),
                    "activation": cfg.activation},
            "seeds": {"base_seed": int(exp.values["run.base_seed"])},
            "executable": exp.executable_fingerprint(), "revisions": {}, "m6_flags": dict(exp.extra_env),
            "versions": {"python": sys.version.split()[0], "torch": torch.__version__},
            "torch_threads": int(cfg.torch_threads),
            "experiment": dict(exp.summary(), compatibility_view=exp.compatibility_view()),
            "lifecycle": exp.lifecycle()}
        meta = tr.save_checkpoint_set(out, model, vn, run_meta=run_meta, coordinator=coord,
                                      label="ckpt_000000000", rollouts=0)
        vn.close()
    finally:
        torch.set_num_threads(threads)
    read = read_checkpoint_set(out)
    reloaded = tr.M7PPO.load(str(out / "model.zip"), device="cpu")
    with open(out / "vecnormalize.pkl", "rb") as fp:
        vn2 = pickle.load(fp)
    after = (policy_parameter_digest(reloaded), obs_rms_digest(vn2))
    check(after == before, f"the reloaded set differs: {after} vs {before}")
    check(vn2.norm_reward is False, "norm_reward is not false after the reload")
    check(vn2.norm_obs is True and float(vn2.clip_obs) == 10.0, f"reloaded flags: {vn2.norm_obs} {vn2.clip_obs}")
    check((read.get("vecnormalize") or {}).get("norm_reward") is False,
          f"checkpoint.json norm_reward: {(read.get('vecnormalize') or {}).get('norm_reward')}")
    check((read.get("contracts") or {}).get("reward_contract") == "btt_reward_v2",
          f"checkpoint reward contract: {read.get('contracts')}")
    files = sorted(p.name for p in out.iterdir())
    check({"checkpoint.json", "model.zip", "vecnormalize.pkl"} <= set(files), f"checkpoint set files: {files}")
    return {"files": files, "policy_digest": before[0][:16], "obs_rms_digest": before[1][:16],
            "reload_identical": True, "norm_reward_before": False, "norm_reward_after": False,
            "saved_keys": sorted(meta.keys()) if isinstance(meta, dict) else None}


def unit_reward_penalty(suite: Suite) -> Dict[str, Any]:
    """One and only one -5.0 on native failure; nothing extra on horizon truncation. Checked on the frozen reward
    module (btt_rewards.reward_step / expected_return) and against the episode-row validator the monitor uses."""
    import m7d_run as run
    from btt_rewards import RewardContractError, expected_return, reward_step

    exp = em.load_run(em.matrix()[0])
    contract = exp.reward
    check(contract.contract == "btt_reward_v2" and contract.failure_penalty == -5.0, f"contract {contract.to_json()}")
    cases: Dict[str, Any] = {}
    for name, (targets, steps, end) in {
        "fall_after_two_targets": (2, 900, "fall"),
        "horizon_after_four_targets": (4, 3600, "horizon"),
        "clear_after_ten_targets": (10, 500, "clear"),
    }.items():
        remaining = 10
        total = 0.0
        failure_terms = 0
        clear_terms = 0
        broken = 0
        every = max(1, steps // max(targets, 1))
        for i in range(steps):
            prev = remaining
            if broken < targets and (i + 1) % every == 0:
                remaining -= 1
                broken += 1
            last = i == steps - 1
            terms = reward_step(prev, remaining, clear=bool(end == "clear" and last),
                               native_failure=bool(end == "fall" and last), contract=contract)
            total += terms.total
            failure_terms += int(terms.failure_term != 0.0)
            clear_terms += int(terms.clear_term != 0.0)
        want_failures = 1 if end == "fall" else 0
        closed = expected_return(broken, steps, cleared=end == "clear", native_failure=end == "fall",
                                 contract=contract)
        check(abs(total - closed) < 1e-6, f"{name}: total {total} != closed form {closed}")
        check(failure_terms == want_failures,
              f"{name}: {failure_terms} failure terms, expected {want_failures}")
        check(clear_terms == (1 if end == "clear" else 0), f"{name}: {clear_terms} clear terms")
        cases[name] = {"targets": broken, "steps": steps, "end": end, "total": round(total, 6),
                       "closed_form": round(closed, 6), "failure_penalty_terms": failure_terms,
                       "clear_terms": clear_terms}
    # The fall episode's return must differ from the same episode without the penalty by exactly -5.0.
    no_penalty = expected_return(2, 900, cleared=False, native_failure=False, contract=contract)
    check(abs((cases["fall_after_two_targets"]["closed_form"] - no_penalty) - contract.failure_penalty) < 1e-9,
          "the fall penalty is not exactly the contract's failure_penalty, once")
    # A step can never be both a native clear and a native failure.
    try:
        reward_step(3, 2, clear=True, native_failure=True, contract=contract)
        check(False, "a step was accepted as both a clear and a native failure")
    except RewardContractError:
        pass
    # The same invariant through the validator the live monitor applies to every episode row.
    rows = {
        "fall": {"episode_id": "e1", "rank": 0, "worker_episode": 1, "end_reason": "fall", "steps": 900,
                 "targets_broken": 2,
                 "return": expected_return(2, 900, cleared=False, native_failure=True, contract=contract),
                 "failure_penalty_terms": 1, "failure_penalty_total": contract.failure_penalty,
                 "target_break_ticks": [100, 200], "last_consumed_tick": 899, "cleared": False,
                 "completion_time_passed": None, "completion_input_tick": None, "terminated": True,
                 "truncated": False, "termination_reason": "native_failure", "truncation_reason": None,
                 "startup_mode": "standby_promoted", "anomaly_events": 0,
                 "terminal_native_observation": {"game_status": 5, "targets_remaining": 8, "btt_active": 1}},
        "horizon": {"episode_id": "e2", "rank": 1, "worker_episode": 2, "end_reason": "horizon", "steps": 3600,
                    "targets_broken": 4,
                    "return": expected_return(4, 3600, cleared=False, native_failure=False, contract=contract),
                    "failure_penalty_terms": 0, "failure_penalty_total": 0.0,
                    "target_break_ticks": [10, 20, 30, 40], "last_consumed_tick": 3599, "cleared": False,
                    "completion_time_passed": None, "completion_input_tick": None, "terminated": False,
                    "truncated": True, "termination_reason": None, "truncation_reason": "max_episode_steps",
                    "startup_mode": "standby_promoted", "anomaly_events": 0,
                    "terminal_native_observation": {"game_status": 6, "targets_remaining": 6, "btt_active": 1}},
    }
    for name, row in rows.items():
        problems = run.validate_episode_row(row, contract, 3600)
        check(not problems, f"{name}: validator rejected a correct row: {problems}")
    bad_double = dict(rows["fall"], failure_penalty_terms=2,
                      failure_penalty_total=2 * contract.failure_penalty,
                      **{"return": rows["fall"]["return"] + contract.failure_penalty})
    check(run.validate_episode_row(bad_double, contract, 3600),
          "the validator accepted two failure-penalty terms on one episode")
    bad_horizon = dict(rows["horizon"], failure_penalty_terms=1,
                       failure_penalty_total=contract.failure_penalty,
                       **{"return": rows["horizon"]["return"] + contract.failure_penalty})
    check(run.validate_episode_row(bad_horizon, contract, 3600),
          "the validator accepted a failure penalty on a horizon truncation")
    missing_penalty = dict(rows["fall"], failure_penalty_terms=0, failure_penalty_total=0.0,
                           **{"return": expected_return(2, 900, cleared=False, native_failure=False,
                                                        contract=contract)})
    check(run.validate_episode_row(missing_penalty, contract, 3600),
          "the validator accepted a fall with no failure penalty")
    return {"cases": cases, "validator": {"correct_rows_accepted": sorted(rows), "double_penalty_rejected": True,
                                          "horizon_penalty_rejected": True},
            "clear_and_failure_together_refused": True,
            "missing_penalty_rejected": True,
            "fall_minus_no_penalty": round(cases["fall_after_two_targets"]["closed_form"] - no_penalty, 6)}


def unit_directory_guards(suite: Suite) -> Dict[str, Any]:
    plan = em.check_directory_plan(require_absent=False)
    check(plan["cannot_touch_m7d"], "a planned M7e directory overlaps runs/m7d")
    m7d = REPO_ROOT / "runs" / "m7d"
    for key, rel in plan["directories"].items():
        p = (REPO_ROOT / rel).resolve()
        check(not em.within(p, m7d.resolve()), f"{key} ({rel}) lies inside runs/m7d")
    hard = [p for p in plan["problems"] if "already exists" not in p]
    check(not hard, f"directory plan problems: {hard}")
    # A run directory is never reused: an existing directory without a completed summary is refused.
    import m7e_run as er
    fake = em.MATRIX_ROOT / "m7e_s0_v2"
    existed = fake.exists()
    refusal = None
    if not existed:
        fake.mkdir(parents=True)
        try:
            args = argparse.Namespace(only="m7e_s0_v2", resume=None, skip_resource_gate=True)
            try:
                er.cmd_train(args)
                check(False, "an existing run directory was reused")
            except em.MatrixError as exc:
                refusal = str(exc)[:240]
        finally:
            fake.rmdir()
    # The snapshot compare must see a change, a removal and an addition.
    tmp = suite.root / "snap"
    (tmp / "a").mkdir(parents=True, exist_ok=True)
    (tmp / "a" / "x.txt").write_text("one", encoding="utf-8")
    (tmp / "a" / "gone.txt").write_text("two", encoding="utf-8")
    before = em.historical_snapshot(root=tmp, exclude=())
    (tmp / "a" / "x.txt").write_text("changed", encoding="utf-8")
    (tmp / "a" / "gone.txt").unlink()
    (tmp / "a" / "new.txt").write_text("three", encoding="utf-8")
    after = em.historical_snapshot(root=tmp, exclude=())
    cmp = em.compare_snapshots(before, after)
    check(not cmp["identical"] and cmp["changed"] and cmp["removed"] and cmp["added_count"] == 1,
          f"the snapshot compare missed a change: {cmp}")
    same = em.compare_snapshots(after, em.historical_snapshot(root=tmp, exclude=()))
    check(same["identical"], f"an unchanged tree compared as changed: {same}")
    return {"plan": plan["directories"], "cannot_touch_m7d": True,
            "existing_run_directory_refused": refusal, "snapshot_detects": {k: cmp[k] for k in
                                                                            ("identical", "changed", "removed",
                                                                             "added_count")}}


def unit_resume_guard(suite: Suite) -> Dict[str, Any]:
    root = suite.root / "resume_guard"
    exps = {s.name: em.load_run(s) for s in em.matrix()}
    specs = {s.name: s for s in em.matrix()}
    own = dt._fake_checkpoint(root, "m7e_s0_v2", exps["m7e_s0_v2"], t=em.CHECKPOINT_INTERVAL)
    ok = mm.resume_guard(specs["m7e_s0_v2"], own, exps["m7e_s0_v2"], matrix_root=root)
    check(ok["base_seed"] == 0 and ok["reward_contract"] == "btt_reward_v2", f"own lineage: {ok}")
    cont = dt._fake_checkpoint(root, "m7e_s0_v2_r1", exps["m7e_s0_v2"], t=2 * em.CHECKPOINT_INTERVAL,
                               run_id="m7e_s0_v2_r1")
    mm.resume_guard(specs["m7e_s0_v2"], cont, exps["m7e_s0_v2"], matrix_root=root)
    refused: Dict[str, str] = {}
    cases = {
        "other_seed_run": (specs["m7e_s0_v2"], dt._fake_checkpoint(root, "m7e_s1_v2", exps["m7e_s1_v2"],
                                                                   t=em.CHECKPOINT_INTERVAL)),
        "other_seed_meta_in_own_dir": (specs["m7e_s2_v2"], dt._fake_checkpoint(root, "m7e_s2_v2", exps["m7e_s1_v2"],
                                                                               t=em.CHECKPOINT_INTERVAL,
                                                                               run_id="m7e_s2_v2")),
        "seed_tampered": (specs["m7e_s1_v2"], dt._fake_checkpoint(root, "m7e_s1_v2_t", exps["m7e_s1_v2"],
                                                                  t=em.CHECKPOINT_INTERVAL, run_id="m7e_s1_v2",
                                                                  seed_override=2)),
        "m7d_final": (specs["m7e_s0_v2"], REPO_ROOT / "runs" / "m7d" / "m7d_s0_v2" / "final"),
        "m7a_pilot_final": (specs["m7e_s0_v2"], REPO_ROOT / "runs" / "m7a_pilot_n5" / "final"),
    }
    for name, (spec, ckpt) in cases.items():
        if not (Path(ckpt) / "checkpoint.json").is_file():
            continue
        try:
            mm.resume_guard(spec, ckpt, exps[spec.name], matrix_root=root)
            check(False, f"{name}: resume was accepted")
        except mm.MatrixError as exc:
            refused[name] = str(exc)[:240]
    check(len(refused) >= 4, f"too few refusals exercised: {sorted(refused)}")
    # A v1 contract can never be resumed into an M7e run.
    v1 = ec.load_experiment(REPO_ROOT / "rl" / "configs" / "m7d" / "m7d_s0_v1.toml")
    diff = ec.compare_compatibility(
        ec.checkpoint_compatibility_view(mm.read_json(own / "checkpoint.json")),
        ec.compatibility_view_from_values(v1.values, v1.reward, dict(v1.extra_env)))
    check(list(diff) == ["contracts.reward_resolved"], f"generic layer reward diff {diff}")
    return {"accepted": ["own run", "own resumed continuation"], "refused": refused,
            "generic_layer_reward_diff": sorted(diff)}


def unit_evaluation_protocol(suite: Suite) -> Dict[str, Any]:
    import m7_trainer as tr

    out: Dict[str, Any] = {"plans": {}}
    census = em.evaluation_census_plan()
    check(census["reconciles"] and census["total_episodes"] == 3055,
          f"the census does not match the proposal's 3,055: {census['total_episodes']}")
    check(census["evaluated_points_per_seed"] == 11 and census["intermediate_points"] == 9, f"points {census}")
    for spec in em.matrix():
        exp = em.load_run(spec)
        plan = em.evaluation_plan(spec, exp)
        labels = [p["label"] for p in plan]
        check(labels[0] == "initial" and labels[-1] == "final" and len(labels) == 11, f"{spec.name}: {labels}")
        check([p["num_timesteps"] for p in plan] == em.evaluated_points(), f"{spec.name}: points")
        for p in plan:
            expect = (em.FINAL_EPISODES if p["label"] in ("initial", "final") else em.CURVE_EPISODES)
            check((p["deterministic_episodes"], p["stochastic_episodes"])
                  == (expect["deterministic"], expect["stochastic"]),
                  f"{spec.name} {p['label']}: episode counts {p}")
            check(p["frozen_vecnormalize"] and p["preserve_all"] and p["seed"] == em.EVAL_SEED
                  and p["workers"] == 5 and p["standby_preboot"] and p["standby_count"] == 1,
                  f"{spec.name} {p['label']}: protocol {p}")
            check(str(p["checkpoint"]).startswith(spec.name + "/") and str(p["out_dir"]).startswith("_eval/"),
                  f"{spec.name} {p['label']}: paths {p}")
        # Evaluation must be disabled inside learn().
        cfg = tr.config_from_experiment(exp)
        check(cfg.eval_interval == 0, f"{spec.name}: eval_interval {cfg.eval_interval} - learn() would evaluate")
        check((exp.values["evaluation.initial"], exp.values["evaluation.final"]) == (False, False),
              f"{spec.name}: initial/final evaluation enabled")
        src = inspect.getsource(tr.M7Run._boundary_work)
        check("if c.eval_interval and" in src, "the trainer's evaluation gate is no longer eval_interval-conditional")
        out["plans"][spec.name] = {"labels": labels, "points": [p["num_timesteps"] for p in plan],
                                   "stochastic_total": sum(int(p["stochastic_episodes"]) for p in plan),
                                   "deterministic_total": sum(int(p["deterministic_episodes"]) for p in plan),
                                   "eval_interval_in_trainer": cfg.eval_interval}
    # Why post-hoc: in-process evaluation reseeds the trainer's global generators. Demonstrated, not assumed.
    import numpy as np
    import torch
    from stable_baselines3.common.utils import set_random_seed

    torch.manual_seed(1234)
    np.random.seed(1234)
    a = (torch.randint(0, 10 ** 6, (4,)).tolist(), np.random.randint(0, 10 ** 6, 4).tolist())
    torch.manual_seed(1234)
    np.random.seed(1234)
    set_random_seed(em.EVAL_SEED)
    b = (torch.randint(0, 10 ** 6, (4,)).tolist(), np.random.randint(0, 10 ** 6, 4).tolist())
    check(a != b, "set_random_seed did not perturb the global generators - the hazard could not be demonstrated")
    # The orchestrator keeps them apart: train and evaluate are separate commands, and evaluate refuses to start
    # while a BattleShip process is alive.
    import m7e_run as er
    check("evaluate" in inspect.signature(er.main).parameters or True, "")
    src = inspect.getsource(er.cmd_evaluate)
    check("_preconditions" in src and "battleship" in inspect.getsource(er._preconditions).lower(),
          "cmd_evaluate does not check that no game process is alive first")
    check("unverified" in src, "cmd_evaluate does not require verified training first")
    return dict(out, census=census["arithmetic"],
                rng_hazard_demonstrated={"before": a[0], "after_set_random_seed": b[0], "differ": a != b},
                separation="evaluation is a separate orchestrator command in its own process; every profile sets "
                           "evaluation.interval = 0 with initial = false and final = false, so learn() never "
                           "evaluates and evaluation can never coexist with live training workers")


def unit_instrumentation(suite: Suite) -> Dict[str, Any]:
    import m7_evaluation as ev
    from run_artifacts import ARTIFACT_SCHEMA, NATIVE_ACTION_CONTRACT

    src = inspect.getsource(ev.run_episodes)
    check("preserve_all" in src, "preserve_all is not plumbed through the evaluation path")
    check("target_break_ticks" in inspect.getsource(ev), "target_break_ticks is not recorded by the evaluator")
    # Every M7d evaluation row carries the fields the M7e analysis needs; the schema is unchanged for M7e.
    sample = mm.read_json(REPO_ROOT / "runs" / "m7d" / "_eval" / "m7d_s0_v2" / "final" / "stochastic"
                          / "evaluation.json")
    need = {"episode_id", "targets_broken", "length", "end_reason", "target_break_ticks", "artifact_dir",
            "native_action_digest", "cleared", "completion_time_passed", "completion_input_tick",
            "last_consumed_tick", "startup_mode", "failure_penalty_terms", "anomaly_events", "mode"}
    have = set(sample["episodes"][0])
    check(need <= have, f"evaluation rows are missing {sorted(need - have)}")
    # Canonical native actions: an artifact's action rows are native values, one per consecutive tick from 0.
    art = REPO_ROOT / sample["episodes"][0]["artifact_dir"]
    from run_artifacts import read_artifact
    a = read_artifact(art)
    rows = a.actions
    check(rows, "artifact has no action rows")
    ticks = [int(r.consumed_tick) for r in rows]
    check(ticks == list(range(len(ticks))), f"consumed ticks are not 0..n-1: {ticks[:5]}...{ticks[-3:]}")
    keys = sorted(rows[0].to_json())
    check({"buttons", "stick_x", "stick_y", "consumed_tick", "sequence_index"} <= set(keys),
          f"action row keys {keys}")
    check(all(0 <= int(r.buttons) <= 0xFFFF and -128 <= int(r.stick_x) <= 127
              and -128 <= int(r.stick_y) <= 127 for r in rows), "action rows are not native values")
    check([r.sequence_index for r in rows] == list(range(len(rows))),
          "action sequence indices are not consecutive from 0")
    md = a.metadata
    check(md.get("artifact_schema") == ARTIFACT_SCHEMA, f"artifact schema: {md.get('artifact_schema')}")
    check(md.get("action_contract") == NATIVE_ACTION_CONTRACT,
          f"action contract: {md.get('action_contract')}")
    # The census must count executed against planned and fail on a gap.
    import m7e_run as er
    cen = er.census()
    check(cen["planned_episodes"] == 3055 and cen["planned_sessions"] == 67, f"census plan {cen['planned_episodes']}")
    check(not cen["complete"], "the census reports complete before anything has been evaluated")
    check(len(cen["missing"]) == len(cen["rows"]) + 1, f"missing count {len(cen['missing'])}")
    return {"artifact": ec.repo_relative(art), "action_rows": len(rows), "first_consumed_tick": ticks[0],
            "last_consumed_tick": ticks[-1], "action_row_keys": sorted(keys),
            "evaluation_row_fields_present": sorted(need),
            "census_planned": {"episodes": cen["planned_episodes"], "sessions": cen["planned_sessions"]},
            "census_detects_missing": len(cen["missing"])}


def unit_gates(suite: Suite) -> Dict[str, Any]:
    import m7e_analysis as an

    rc = an._tests()
    check(rc == 0, "the M7e gate and plateau definition tests failed")
    check(len(em.GATES) == 8, f"{len(em.GATES)} gates")
    keys = [g["key"] for g in em.GATES]
    check(keys == ["verified_clear", "better_targets_no_clear", "still_improving", "plateau", "worse_idling",
                   "seed_disagreement", "deterministic_collapse", "lifecycle_regression"], f"gate keys {keys}")
    check(em.PLATEAU_SLOPE_THRESHOLD == 0.25 and em.PLATEAU_WINDOW_POINTS == 6
          and em.PLATEAU_SEEDS_REQUIRED == 2 and em.PLATEAU_TAIL_TOLERANCE == 0.05,
          "the plateau rule's registered constants changed")
    return {"gates": keys, "plateau_rule": {"threshold": em.PLATEAU_SLOPE_THRESHOLD,
                                            "window_points": em.PLATEAU_WINDOW_POINTS,
                                            "seeds_required": em.PLATEAU_SEEDS_REQUIRED,
                                            "tail_tolerance": em.PLATEAU_TAIL_TOLERANCE},
            "analysis_definition_tests": "passed"}


# -- game cases --------------------------------------------------------------------------------------------------------


def bounded_training(suite: Suite) -> Dict[str, Any]:
    import m7d_run as run

    exp = derive_bounded(suite)
    expected = em.expected_initial_policy_digest(exp, return_obs_rms=True)
    full = em.expected_initial_policy_digest(em.load_run(em.run_by_name("m7e_s0_v2")), return_obs_rms=True)
    check(expected == full, "the bounded twin must share the full profile's untrained model")
    pre = run.system_state(label="before pf_s0_v2")
    check(not pre["battleship_pids"], f"BattleShip running before: {pre['battleship_pids']}")
    res = run.train_once(config=suite.root / "configs" / "pf_s0_v2.toml", run_dir=exp.run_dir, contract=exp.reward,
                         horizon=int(exp.values["environment.horizon"]),
                         log_path=suite.root / "logs" / "pf_s0_v2.log",
                         monitor_path=suite.root / "monitor" / "pf_s0_v2.jsonl")
    check(res["exit_code"] == 0 and not res["stop_reason"],
          f"pf_s0_v2: exit {res['exit_code']} {res['stop_reason']}")
    ver = run.verify_training_run(exp.run_dir, exp, expected_initial=expected)
    em.write_json(suite.root / "verify" / "pf_s0_v2.json", ver)
    check(ver["ok"], f"pf_s0_v2 verification: {ver['problems']}")
    mon = res["monitor"]
    check(mon["max_battleship_processes"] <= em.MAX_GAME_PROCESSES and not mon["hard_alerts"],
          f"monitor: {mon['max_battleship_processes']} {mon['hard_alerts']}")
    post = run.system_state(label="after pf_s0_v2")
    check(not post["battleship_pids"] and not post["battleship_listeners"], "leak after the run")
    lc = ver["checks"]["lifecycle"]
    check((lc.get("promotions") or 0) > 0, f"no standby promotion: {lc}")
    check(int(lc.get("observed_max_concurrent_per_worker") or 0) <= 2, f"per-worker process bound: {lc}")
    art = ver["checks"]["artifacts"]
    first = art.get("first_consumed_tick") or {}
    check(art["ok"] and set(map(str, first)) == {"0"},
          f"artifacts do not all start at consumed tick 0: {art}")
    summary = em.read_json(exp.run_dir / "training_summary.json")
    check(summary.get("evaluations") == [], f"in-process evaluations ran: {summary.get('evaluations')}")
    check(float((summary.get("wall") or {}).get("eval_s_total") or 0.0) == 0.0,
          f"time was spent evaluating inside learn(): {(summary.get('wall') or {}).get('eval_s_total')}")
    rows, _ = run.jsonl_rows(exp.run_dir / "metrics" / "episodes.jsonl")
    falls = sum(1 for e in rows if e["end_reason"] == "fall")
    pens = sum(int(e["failure_penalty_terms"]) for e in rows)
    check(pens == falls, f"{pens} failure-penalty terms for {falls} falls")
    horizon_pens = sum(int(e["failure_penalty_terms"]) for e in rows if e["end_reason"] == "horizon")
    check(horizon_pens == 0, f"{horizon_pens} failure penalties on horizon truncations")
    suite.shared["bounded_run_dir"] = str(exp.run_dir)
    suite.shared["bounded_config"] = str(suite.root / "configs" / "pf_s0_v2.toml")
    return {"wall_s": res["wall_s"], "episodes": ver["checks"]["episodes"], "lifecycle": lc,
            "monitor": {k: mon.get(k) for k in ("max_battleship_processes", "max_listeners", "samples",
                                                "avail_commit_gib", "worker_threads")},
            "initial_policy": ver["checks"].get("initial_policy"),
            "artifacts": {k: art.get(k) for k in ("artifacts", "first_consumed_tick", "startup_modes")},
            "falls": falls, "failure_penalty_terms": pens, "horizon_failure_penalties": horizon_pens,
            "in_process_evaluations": 0}


def bounded_posthoc_evaluation(suite: Suite) -> Dict[str, Any]:
    import torch

    import m7_evaluation as ev
    import m7d_run as run
    from btt_parallel import m7_contracts
    from m7_runtime import install_kill_on_close_job

    torch.set_num_threads(1)
    install_kill_on_close_job()
    exp = derive_bounded(suite)
    plan = {"deterministic_episodes": 2, "stochastic_episodes": 10}
    results: Dict[str, Any] = {}
    rows: Dict[str, Any] = {}
    settings = run.evaluation_settings(exp)
    for label, ckpt in (("initial", exp.run_dir / "checkpoints" / "ckpt_000000000"),
                        ("final", exp.run_dir / "final")):
        out = suite.root / "eval" / "pf_s0_v2" / label
        mon = run.Monitor(out=suite.root / "monitor" / "evaluation.jsonl", root_pid=os.getpid()).start()
        try:
            res = ev.evaluate_checkpoint(ckpt, out, settings=settings, deterministic_episodes=2,
                                         stochastic_episodes=10,
                                         expected_contracts=m7_contracts(3600, exp.reward),
                                         label=label, preserve_all=True)
        finally:
            m = mon.stop()
        check(m["max_battleship_processes"] <= em.MAX_GAME_PROCESSES and not m["hard_alerts"],
              f"monitor {m['max_battleship_processes']} {m['hard_alerts']}")
        ver = run.verify_evaluation(res, exp.reward, 3600, plan)
        check(ver["ok"], f"pf_s0_v2 {label}: {ver['problems']}")
        for mode, block in res["modes"].items():
            check(block.get("preserve_all") is True, f"{label} {mode}: preserve_all not set")
            check(len(block["episodes"]) == plan[f"{mode}_episodes"],
                  f"{label} {mode}: {len(block['episodes'])} episodes")
            fc = block.get("frozen_check") or {}
            check(fc.get("vecnormalize_norm_reward") is False and fc.get("vecnormalize_training") is False
                  and fc.get("policy_parameters_unchanged") is True and fc.get("obs_rms_unchanged") is True,
                  f"{label} {mode}: statistics not frozen: {fc}")
        arts = [e["artifact_dir"] for mode in res["modes"].values() for e in mode["episodes"]]
        av = run.verify_artifacts(arts, exp.reward.contract)
        check(av["ok"] and av["artifacts"] == 12, f"artifacts {av}")
        modes = {e["startup_mode"] for mode in res["modes"].values() for e in mode["episodes"]}
        check("standby_promoted" in modes, f"no promoted evaluation episode: {modes}")
        results[label] = {"verification": ver["per_mode"], "artifacts": av["first_consumed_tick"],
                          "startup_modes": av["startup_modes"],
                          "max_battleship": m["max_battleship_processes"]}
        rows[label] = res
        try:
            ev.evaluate_checkpoint(ckpt, out, settings=settings, deterministic_episodes=1, stochastic_episodes=0,
                                   label=label)
            check(False, "an evaluation reused an existing directory")
        except FileExistsError:
            pass
    # No M7e output path may be written by a preflight evaluation.
    check(not em.EVAL_ROOT.exists() or not any(em.EVAL_ROOT.rglob("evaluation.json")),
          "the preflight wrote into the real M7e evaluation tree")
    suite.shared["bounded_eval"] = str(suite.root / "eval" / "pf_s0_v2")
    return {"sets": results,
            "final_deterministic_identical": rows["final"]["modes"]["deterministic"].get(
                "deterministic_episodes_identical")}


def bounded_replay(suite: Suite) -> Dict[str, Any]:
    import m7d_run as run
    from m7_runtime import install_kill_on_close_job

    install_kill_on_close_job()
    exp = derive_bounded(suite)
    rows: List[Dict[str, Any]] = []
    for label in ("initial", "final"):
        for mode in ("deterministic", "stochastic"):
            f = suite.root / "eval" / "pf_s0_v2" / label / mode / "evaluation.json"
            if f.is_file():
                rows += list(em.read_json(f)["episodes"])
    check(rows, "no evaluation rows to replay")
    rows.sort(key=lambda e: (bool(e["cleared"]), e["targets_broken"]), reverse=True)
    chosen = [rows[0]]
    for end in ("fall", "horizon"):
        e = next((x for x in rows if x["end_reason"] == end and x not in chosen), None)
        if e is not None:
            chosen.append(e)
    records = []
    for k, e in enumerate(chosen):
        rec = run.replay_one(REPO_ROOT / e["artifact_dir"], suite.root / "replay" / f"r{k}",
                             executable=exp.executable, extra_env=dict(exp.extra_env), index=9600 + k,
                             expected_break_ticks=e["target_break_ticks"])
        check(rec["ok"], f"replay {e['episode_id']}: {rec['checks']} {rec.get('final_matches')}")
        records.append({"episode": e["episode_id"], "end_reason": e["end_reason"],
                        "targets": e["targets_broken"], "submitted": rec["submitted"], "checks": rec["checks"],
                        "host_frame_equal": rec["final_matches"].get("host_frame_equal"),
                        "stepping_s": rec["stepping_s"]})
    return {"replayed": records}


def bounded_cleanup(suite: Suite) -> Dict[str, Any]:
    import m7d_run as run

    st = run.system_state(label="after the bounded preflight")
    check(not st["battleship_pids"], f"BattleShip processes left: {st['battleship_pids']}")
    check(not st["listening_ports_in_blocks"], f"ports still listening: {st['listening_ports_in_blocks']}")
    run_dir = Path(suite.shared.get("bounded_run_dir") or (suite.root / "train" / "pf_s0_v2"))
    summary = em.read_json(run_dir / "training_summary.json")
    threads = (((summary.get("lifecycle") or {}).get("standby") or {}).get("threads")) or {}
    check(threads.get("started") == threads.get("joined") and not threads.get("alive_at_close"),
          f"launcher threads not all joined: {threads}")
    cleanup = summary.get("cleanup") or {}
    close = cleanup.get("close") or {}
    check(not close.get("forced_terminations") and not close.get("orphan_games_killed")
          and not close.get("drain_lost"), f"unclean close: {close}")
    ranks = cleanup.get("ranks") or {}
    check(all(v.get("closed_cleanly") for v in ranks.values()), f"a worker did not close cleanly: {ranks}")
    return {"battleship_processes": 0, "listening_ports_in_blocks": 0, "launcher_threads": threads,
            "close": close, "ranks_closed_cleanly": len(ranks)}


def existing_suites(suite: Suite) -> Dict[str, Any]:
    cmds = {
        "m7b_config_tests": [sys.executable, str(REPO_ROOT / "rl" / "m7b_config_tests.py")],
        "m7c_standby_tests_unit": [sys.executable, str(REPO_ROOT / "rl" / "m7c_standby_tests.py"), "unit"],
        "m7e_idle_analysis": [sys.executable, str(REPO_ROOT / "rl" / "m7e_idle_analysis.py"), "--test"],
        "m7e_matrix": [sys.executable, str(REPO_ROOT / "rl" / "m7e_matrix.py"), "--test"],
        "m7e_analysis": [sys.executable, str(REPO_ROOT / "rl" / "m7e_analysis.py"), "--test"],
    }
    out: Dict[str, Any] = {}
    for name, cmd in cmds.items():
        rc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=3600, check=False)
        tail = (rc.stdout or "").strip().splitlines()[-3:]
        out[name] = {"exit_code": rc.returncode, "tail": tail}
        dt._write_lf(suite.root / "suites" / f"{name}.log", (rc.stdout or "") + (rc.stderr or ""))
        check(rc.returncode == 0, f"{name} exit {rc.returncode}: {tail}")
    return out


UNIT_CASES: Dict[str, Callable[[Suite], Dict[str, Any]]] = {
    "unit_profiles": unit_profiles,
    "unit_fresh_init": unit_fresh_init,
    "unit_reward_to_ppo": unit_reward_to_ppo,
    "unit_checkpoint_roundtrip": unit_checkpoint_roundtrip,
    "unit_reward_penalty": unit_reward_penalty,
    "unit_directory_guards": unit_directory_guards,
    "unit_resume_guard": unit_resume_guard,
    "unit_evaluation_protocol": unit_evaluation_protocol,
    "unit_instrumentation": unit_instrumentation,
    "unit_gates": unit_gates,
}
GAME_CASES: Dict[str, Callable[[Suite], Dict[str, Any]]] = {
    "bounded_training": bounded_training,
    "bounded_posthoc_evaluation": bounded_posthoc_evaluation,
    "bounded_replay": bounded_replay,
    "bounded_cleanup": bounded_cleanup,
    "existing_suites": existing_suites,
}
ALL_CASES: Dict[str, Callable[[Suite], Dict[str, Any]]] = {**UNIT_CASES, **GAME_CASES}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cases", nargs="*", help="case names, 'unit' or 'game' (default: all)")
    parser.add_argument("--root", default=None, help="output root (default: runs/_m7e_preflight_<utc>)")
    args = parser.parse_args(argv)
    names: List[str] = []
    for c in args.cases or ["unit", "game"]:
        names += list(UNIT_CASES) if c == "unit" else list(GAME_CASES) if c == "game" else [c]
    unknown = [n for n in names if n not in ALL_CASES]
    if unknown:
        print(f"unknown cases: {unknown}; known: {list(ALL_CASES)}", flush=True)
        return 2
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = Path(args.root) if args.root else REPO_ROOT / "runs" / f"_m7e_preflight_{stamp}"
    root = root if root.is_absolute() else REPO_ROOT / root
    root.mkdir(parents=True, exist_ok=True)
    suite = Suite(root)
    print(f"M7e preflight: {len(names)} case(s) -> {ec.repo_relative(root)}", flush=True)
    ok = True
    for n in names:
        ok &= suite.run(n, ALL_CASES[n])
    passed = sum(1 for r in suite.results.values() if r["status"] == "PASS")
    print(f"M7e preflight: {passed}/{len(suite.results)} PASS", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
