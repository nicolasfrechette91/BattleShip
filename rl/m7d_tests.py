#!/usr/bin/env python3
"""M7d preflight tests: the matrix, its guards and a bounded paired run, before any full training.

    python rl/m7d_tests.py                 # every case (unit, then game), sequential
    python rl/m7d_tests.py unit            # ROM-independent cases only
    python rl/m7d_tests.py game            # game-backed bounded cases only
    python rl/m7d_tests.py <case> ... [--root runs/_m7d_preflight_<utc>]

Unit cases (no game):
  unit_matrix_profiles         manifest proof: pairs differ only in reward identity/definition, run identity,
                               output paths and derived hashes; seeds 0/1/2; order; every required value; dry runs
  unit_fresh_paired_init       untrained policy + VecNormalize digests: equal within a seed pair, distinct across seeds
  unit_reward_normalization    VecNormalize as the trainer builds it returns raw rewards; normalize_rewards = true refused
  unit_directory_guards        planned directories new, unique, disjoint, outside history; snapshot compare detects
                               changes; an existing run directory is never reused
  unit_resume_guard            resume only inside a run's own lineage: other seed / other reward / M7a refused
  unit_validators              episode invariants (closed-form returns, one-time v2 penalty, ticks) and system probes
  unit_instrumentation         target_break_ticks in the tracker summary, preserve_all plumbing, evaluation row keys
  unit_decision_rule           the pre-registered rule on synthetic outcomes (v2 preferred / v1 retained / inconclusive)
Game cases (bounded):
  paired_bounded_training      seed 0 v1 and v2 profiles, 25,600 transitions each through the orchestrator path
                               (train_m7.py subprocess + monitor): fresh models equal to the offline construction,
                               identical untrained sets, identical first-rollout gameplay, returns differ by exactly
                               -5.0 per fall, verified directories, promotions, <= 10 processes, no leak
  bounded_posthoc_evaluation   post-hoc evaluation of both runs (initial + final, 2 det + 12 stoch, preserve_all):
                               frozen statistics, identical paired initial evaluations, promoted episodes start at
                               consumed tick 0, every episode preserved, no directory reuse
  bounded_replay               native replay of the best and a fall artifact: ticks, targets, final observation,
                               break ticks equal to the evaluation summary
  existing_suites              rl/m7b_config_tests.py (16), rl/m7c_standby_tests.py unit + cold_vs_standby_replay +
                               terminal_paths_promotion, rl/m7b_smoke.py tas_v1_v2 fall_v1_v2 truncation_v2

Results: <root>/results.json. Standard library at module level (spawn workers re-import this file).
"""

from __future__ import annotations

import argparse
import inspect
import json
import multiprocessing
import os
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import experiment_config as ec  # noqa: E402
import m7d_matrix as mm  # noqa: E402

REPO_ROOT = mm.REPO_ROOT


class CheckFailed(AssertionError):
    pass


def check(ok: bool, message: str) -> None:
    if not ok:
        raise CheckFailed(message)


class Suite:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.results: Dict[str, Any] = {}
        self.shared: Dict[str, Any] = {}

    def run(self, name: str, fn: Callable[["Suite"], Dict[str, Any]]) -> bool:
        from m7_runtime import list_processes_named

        t0 = time.perf_counter()
        print(f"--- {name}", flush=True)
        try:
            details = fn(self)
            status = "PASS"
            error = None
        except Exception as exc:  # noqa: BLE001 - recorded
            details, status = {}, "FAIL"
            error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-3000:]}"
        leftover = list_processes_named("BattleShip.exe") or []
        if leftover:
            status = "FAIL"
            error = (error or "") + f"\nBattleShip.exe left running: {leftover}"
        self.results[name] = {"status": status, "seconds": round(time.perf_counter() - t0, 1), "details": details,
                              "error": error, "battleship_after": leftover}
        print(f"    {status} ({self.results[name]['seconds']} s){'' if error is None else ' ' + error.splitlines()[0]}",
              flush=True)
        mm.write_json(self.root / "results.json", {"utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                                   "results": self.results})
        return status == "PASS"


# -- helpers -------------------------------------------------------------------------------------------------------------


def _write_lf(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fp:
        fp.write(text)


def derive_bounded(suite: Suite, reward: str, *, total: int = 25_600, interval: int = 5_120) -> ec.Experiment:
    """A bounded twin of m7d_s0_<reward>: same values except run identity, output root, transitions and checkpoint
    cadence (both operational / semantic budget fields), written as a TOML under <root>/configs."""
    base = mm.load_run(mm.run_by_name(f"m7d_s0_{reward}"))
    values = dict(base.values)
    values.update({"run.name": f"pf_s0_{reward}", "run.output_root": str(suite.root / "train"),
                   "run.total_transitions": total, "checkpoint.interval": interval,
                   "run.notes": f"M7d preflight: bounded twin of m7d_s0_{reward} ({total} transitions)"})
    text = ec.to_toml_text(values, header=f"derived by rl/m7d_tests.py from rl/configs/m7d/m7d_s0_{reward}.toml "
                                          f"(bounded preflight twin)")
    path = suite.root / "configs" / f"pf_s0_{reward}.toml"
    if not path.exists():
        _write_lf(path, text)
    return ec.load_experiment(path)


class _ScriptedEnv:
    """Offline environment with the worker stack's spaces that emits a fixed reward script (no game)."""

    def __new__(cls, rewards: Sequence[float]):
        import gymnasium as gym
        import numpy as np

        from btt_learning import make_policy_observation_space, make_track1_action_space

        class Env(gym.Env):
            def __init__(self) -> None:
                self.observation_space = make_policy_observation_space()
                self.action_space = make_track1_action_space()
                self.i = 0

            def reset(self, *, seed=None, options=None):
                super().reset(seed=seed)
                return np.zeros(15, dtype=np.float32), {}

            def step(self, action):
                r = float(rewards[self.i % len(rewards)])
                self.i += 1
                return np.full(15, float(self.i), dtype=np.float32), r, False, False, {}

        return Env()


# -- unit cases -------------------------------------------------------------------------------------------------------------


def unit_matrix_profiles(suite: Suite) -> Dict[str, Any]:
    m = mm.build_manifest()
    check(m["ok"], f"manifest problems: {m['problems']}")
    check(tuple(mm.SEEDS) == (0, 1, 2), "seeds")
    check([(o["seed"], o["reward"]) for o in m["order"]] == [(0, "v1"), (0, "v2"), (1, "v2"), (1, "v1"), (2, "v1"),
                                                             (2, "v2")], "counterbalanced order")
    for seed, pair in m["pairs"].items():
        for key in ("resolved_proof", "trainer_proof", "evaluation_plan_proof"):
            check(pair[key]["proof_ok"], f"{seed} {key}: {pair[key]['unexpected']}")
        check(pair["same_base_seed"] and pair["same_compatibility_except_reward"] and pair["same_initial_policy"],
              f"{seed}: seed / compatibility / initial policy")
        cats = pair["resolved_proof"]["by_category"]
        check(set(cats["reward_identity_and_definition"]) == {"config.contracts.reward", "config.reward.failure_penalty",
                                                              "resolved.reward.contract", "resolved.reward.failure_penalty"},
              f"{seed}: the reward definition must differ exactly in id and penalty: {cats}")
    for name, v in m["vs_canonical"].items():
        check(v["proof"]["proof_ok"] and v["same_compatibility_fingerprint"], f"{name} vs canonical: {v['proof']}")
        check(v["same_semantic_fingerprint"] == (m["runs"][name]["seed"] == 0), f"{name}: semantic vs canonical")
    for k, v in m["across_seeds"].items():
        check(v["proof"]["proof_ok"] and v["same_compatibility_fingerprint"], f"{k}: {v['proof']}")
    for name, r in m["runs"].items():
        check(all(r["required_value_checks"].values()), f"{name}: {r['required_value_checks']}")
    dry = {}
    for spec in mm.matrix():
        out = subprocess.run([sys.executable, str(REPO_ROOT / "rl" / "train_m7.py"), "--config", str(spec.config_path),
                              "--dry-run"], capture_output=True, text=True, timeout=120, cwd=str(REPO_ROOT))
        check(out.returncode == 0, f"{spec.name}: dry run exit {out.returncode}: {out.stdout[-500:]}")
        check("expected maximum game processes 10 (training, N=5)" in out.stdout, f"{spec.name}: lifecycle line")
        check("evaluation  : every 0  initial False  final False" in out.stdout, f"{spec.name}: evaluation line")
        dry[spec.name] = [line for line in out.stdout.splitlines() if line.startswith(("reward", "run  ", "lifecycle"))]
    suite.shared["manifest"] = m
    return {"pairs": {k: {"resolved_differing_paths": v["resolved_proof"]["differing_paths"],
                          "trainer_differing_paths": v["trainer_proof"]["differing_paths"]} for k, v in m["pairs"].items()},
            "semantic": {n: r["semantic_fingerprint"][:16] for n, r in m["runs"].items()},
            "compatibility": {n: r["compatibility_fingerprint"][:16] for n, r in m["runs"].items()},
            "initial_policy_digest": {n: r["expected_initial_policy_digest"][:16] for n, r in m["runs"].items()},
            "dry_runs": dry}


def unit_fresh_paired_init(suite: Suite) -> Dict[str, Any]:
    digests = {}
    for spec in mm.matrix():
        exp = mm.load_run(spec)
        digests[spec.name] = mm.expected_initial_policy_digest(exp, return_obs_rms=True)
        again = mm.expected_initial_policy_digest(exp, return_obs_rms=True)
        check(again == digests[spec.name], f"{spec.name}: construction not reproducible")
    for seed in mm.SEEDS:
        check(digests[f"m7d_s{seed}_v1"] == digests[f"m7d_s{seed}_v2"], f"seed {seed}: v1 and v2 untrained models differ")
    per_seed = {seed: digests[f"m7d_s{seed}_v1"][0] for seed in mm.SEEDS}
    check(len(set(per_seed.values())) == 3, f"seeds share an untrained policy: {per_seed}")
    obs = {digests[s.name][1] for s in mm.matrix()}
    check(len(obs) == 1, "untrained observation statistics must be the VecNormalize defaults for every run")
    suite.shared["expected_initial"] = digests
    return {"policy": {k: v[0][:16] for k, v in digests.items()}, "obs_rms": sorted(x[:16] for x in obs)}


def unit_reward_normalization(suite: Suite) -> Dict[str, Any]:
    import numpy as np
    from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

    import m7_trainer as tr

    src = inspect.getsource(tr.M7Run.run)
    check("norm_reward=False" in src and "VecNormalize(self.venv, training=True, norm_obs=c.norm_obs, norm_reward=False"
          in src, "the trainer no longer constructs VecNormalize with norm_reward=False")
    script = [-0.001, 0.999, -5.001, 9.999, -0.001, 1.999, -4.001]
    out = {}
    for spec in mm.matrix():
        cfg = tr.config_from_experiment(mm.load_run(spec))
        venv = DummyVecEnv([lambda: _ScriptedEnv(script) for _ in range(cfg.n_envs)])
        vn = VecNormalize(venv, training=True, norm_obs=cfg.norm_obs, norm_reward=False, clip_obs=cfg.clip_obs,
                          gamma=cfg.gamma)
        vn.reset()
        got = []
        for _ in range(len(script) * 3):
            _o, r, _d, _i = vn.step(np.zeros((cfg.n_envs, 2), dtype=np.int64))
            got.append(r.copy())
        want = [np.full(cfg.n_envs, script[i % len(script)], dtype=np.float32) for i in range(len(got))]
        check(all(np.array_equal(g.astype(np.float32), w) for g, w in zip(got, want)), f"{spec.name}: rewards transformed")
        check(vn.norm_reward is False and vn.norm_obs is True and cfg.clip_obs == 10.0, f"{spec.name}: flags")
        out[spec.name] = {"steps": len(got), "raw_rewards_passed_through": True, "ret_rms_count": float(vn.ret_rms.count)}
        vn.close()
    text = mm.load_run(mm.matrix()[0]).toml_text.replace("normalize_rewards = false", "normalize_rewards = true")
    try:
        ec.parse_toml_text(text)
        check(False, "normalize_rewards = true was accepted")
    except ec.ConfigError as exc:
        check("ppo.vecnormalize.normalize_rewards" in str(exc), f"unexpected rejection: {exc}")
    return {"runs": out, "note": "ret_rms is updated by SB3 during training but never applied (norm_reward=False)"}


def unit_directory_guards(suite: Suite) -> Dict[str, Any]:
    import m7_trainer as tr

    # Structure (uniqueness, disjointness, outside the historical tree) always holds; the "must not exist yet"
    # guard is asserted in whichever state the repository is in: before the matrix the planned directories are
    # absent, after it the guard must refuse to reuse them (run directories are never overwritten).
    plan = mm.check_directory_plan(require_absent=False)
    check(plan["ok"], f"directory plan: {plan['problems']}")
    absent = mm.check_directory_plan(require_absent=True)
    matrix_exists = mm.MATRIX_ROOT.exists()
    if matrix_exists:
        check(not absent["ok"] and absent["existing"], "the guard accepted existing M7d run directories")
    else:
        check(absent["ok"] and not absent["existing"], f"directory plan: {absent['problems']}")
    check(mm.within(REPO_ROOT / "runs" / "m7d" / "m7d_s0_v1", REPO_ROOT / "runs" / "m7d"), "within()")
    check(not mm.within(REPO_ROOT / "runs" / "m7d", REPO_ROOT / "runs" / "m7a_pilot_n5"), "within() false positive")
    historical = sorted(p.name for p in (REPO_ROOT / "runs").iterdir() if p.is_dir())
    for key, rel in plan["directories"].items():
        for h in historical:
            check(not (mm.within(REPO_ROOT / rel, REPO_ROOT / "runs" / h) or mm.within(REPO_ROOT / "runs" / h,
                                                                                         REPO_ROOT / rel))
                  or h == "m7d", f"{key} overlaps runs/{h}")
    scratch = suite.root / "guards"
    existing = scratch / "run_exists"
    existing.mkdir(parents=True)
    try:
        tr.M7Layout(existing).create()
        check(False, "M7Layout.create reused an existing run directory")
    except FileExistsError:
        pass
    tree = scratch / "tree"
    (tree / "a").mkdir(parents=True)
    for name in ("x.json", "a/y.json", "a/z.json"):
        _write_lf(tree / name, name)
    before = mm.historical_snapshot(root=tree, exclude=())
    check(mm.compare_snapshots(before, mm.historical_snapshot(root=tree, exclude=()))["identical"], "self compare")
    _write_lf(tree / "a" / "y.json", "changed")
    os.utime(tree / "x.json", ns=(before["entries"]["x.json"]["mtime_ns"] + 10 ** 9,) * 2)
    (tree / "a" / "z.json").unlink()
    _write_lf(tree / "new.json", "new")
    cmp = mm.compare_snapshots(before, mm.historical_snapshot(root=tree, exclude=()))
    check(not cmp["identical"] and cmp["changed"] == ["a/y.json"] and cmp["mtime_changed"] == ["x.json"]
          and cmp["removed"] == ["a/z.json"] and cmp["added"] == ["new.json"], f"snapshot compare: {cmp}")
    snap = mm.historical_snapshot(with_entries=False)
    return {"matrix_directories_exist": matrix_exists, "guard_refuses_existing": bool(absent["existing"]),
            "planned": plan["directories"], "historical_top_level": len(historical),
            "historical_files": snap["files"], "historical_bytes": snap["bytes"],
            "historical_aggregate": snap["aggregate_sha256"], "snapshot_compare_detects": cmp}


def _fake_checkpoint(root: Path, run_dir_name: str, exp: ec.Experiment, *, t: int = 51200,
                     run_id: Optional[str] = None, seed_override: Optional[int] = None) -> Path:
    from btt_parallel import m7_contracts

    d = root / run_dir_name / "checkpoints" / f"ckpt_{t:09d}"
    d.mkdir(parents=True)
    meta = {"checkpoint_schema": 1, "run_id": run_id or run_dir_name, "num_timesteps": t,
            "contracts": m7_contracts(3600, exp.reward),
            "seeds": {"base_seed": int(exp.values["run.base_seed"]) if seed_override is None else seed_override},
            "experiment": dict(exp.summary(), compatibility_view=exp.compatibility_view()),
            "lifecycle": exp.lifecycle()}
    mm.write_json(d / "checkpoint.json", meta)
    return d


def unit_resume_guard(suite: Suite) -> Dict[str, Any]:
    root = suite.root / "resume_guard"
    exps = {s.name: mm.load_run(s) for s in mm.matrix()}
    specs = {s.name: s for s in mm.matrix()}
    own = _fake_checkpoint(root, "m7d_s0_v1", exps["m7d_s0_v1"])
    ok = mm.resume_guard(specs["m7d_s0_v1"], own, matrix_root=root)
    check(ok["base_seed"] == 0 and ok["reward_contract"] == "btt_reward_v1", f"own lineage: {ok}")
    cont = _fake_checkpoint(root, "m7d_s0_v1_r1", exps["m7d_s0_v1"], t=102400, run_id="m7d_s0_v1_r1")
    mm.resume_guard(specs["m7d_s0_v1"], cont, matrix_root=root)
    refused = {}
    cases = {
        "other_seed_run": (specs["m7d_s0_v1"], _fake_checkpoint(root, "m7d_s1_v1", exps["m7d_s1_v1"])),
        "other_reward_run": (specs["m7d_s0_v1"], _fake_checkpoint(root, "m7d_s0_v2", exps["m7d_s0_v2"])),
        "other_seed_meta_in_own_dir": (specs["m7d_s2_v2"], _fake_checkpoint(root, "m7d_s2_v2", exps["m7d_s1_v2"],
                                                                            run_id="m7d_s2_v2")),
        "seed_tampered": (specs["m7d_s1_v2"], _fake_checkpoint(root, "m7d_s1_v2", exps["m7d_s1_v2"], seed_override=2)),
        "m7a_pilot_final": (specs["m7d_s0_v1"], REPO_ROOT / "runs" / "m7a_pilot_n5" / "final"),
    }
    for name, (spec, ckpt) in cases.items():
        try:
            mm.resume_guard(spec, ckpt, matrix_root=root)
            check(False, f"{name}: resume was accepted")
        except mm.MatrixError as exc:
            refused[name] = str(exc)[:300]
    # The generic M7b resume layer refuses a reward change but permits a seed change: that is why the matrix adds its
    # own lineage guard.
    view = ec.checkpoint_compatibility_view(mm.read_json(own / "checkpoint.json"))
    reward_diff = ec.compare_compatibility(view, ec.compatibility_view_from_values(
        exps["m7d_s0_v2"].values, exps["m7d_s0_v2"].reward, dict(exps["m7d_s0_v2"].extra_env)))
    seed_diff = ec.compare_compatibility(view, ec.compatibility_view_from_values(
        exps["m7d_s1_v1"].values, exps["m7d_s1_v1"].reward, dict(exps["m7d_s1_v1"].extra_env)))
    check(list(reward_diff) == ["contracts.reward_resolved"], f"generic reward diff {reward_diff}")
    check(seed_diff == {}, f"generic seed diff {seed_diff}")
    return {"accepted": ["own run", "own resumed continuation"], "refused": refused,
            "generic_layer": {"reward_change": sorted(reward_diff), "seed_change": "permitted (semantic field) -> "
                              "blocked only by the M7d lineage guard"}}


def unit_validators(suite: Suite) -> Dict[str, Any]:
    import m7d_run as run
    from btt_rewards import REWARD_V1, REWARD_V2

    obs_fall = {"btt_active": 1, "game_status": 5, "targets_remaining": 8}
    base = {"rank": 0, "worker_episode": 2, "end_reason": "fall", "targets_broken": 2, "steps": 832,
            "return": 2 - 0.832 - 5.0, "cleared": False, "completion_time_passed": None, "completion_input_tick": None,
            "termination_reason": "native_failure", "failure_penalty_terms": 1, "failure_penalty_total": -5.0,
            "target_break_ticks": [100, 500], "startup_mode": "standby_promoted", "terminal_native_observation": obs_fall}
    check(run.validate_episode_row(base, REWARD_V2, 3600) == [], f"valid v2 fall rejected: "
          f"{run.validate_episode_row(base, REWARD_V2, 3600)}")
    v1 = dict(base, **{"return": 2 - 0.832, "failure_penalty_terms": 0, "failure_penalty_total": 0.0})
    check(run.validate_episode_row(v1, REWARD_V1, 3600) == [], "valid v1 fall rejected")
    bad = {
        "v2_fall_without_penalty": (dict(base, failure_penalty_terms=0, failure_penalty_total=0.0), REWARD_V2),
        "v1_fall_with_penalty": (dict(v1, failure_penalty_terms=1, failure_penalty_total=-5.0), REWARD_V1),
        "wrong_return": (dict(base, **{"return": 2 - 0.832}), REWARD_V2),
        "horizon_short": (dict(v1, end_reason="horizon", termination_reason=None, steps=3599,
                               terminal_native_observation=None, **{"return": 2 - 3.599}), REWARD_V1),
        "clear_without_completion": (dict(v1, end_reason="clear", cleared=True, targets_broken=10,
                                          termination_reason="native_clear", terminal_native_observation=None,
                                          target_break_ticks=list(range(10)), **{"return": 10 - 0.832 + 10}), REWARD_V1),
        "break_ticks_mismatch": (dict(v1, target_break_ticks=[100]), REWARD_V1),
        "unknown_startup_mode": (dict(v1, startup_mode="hidden_reset"), REWARD_V1),
    }
    detected = {}
    for name, (row, contract) in bad.items():
        problems = run.validate_episode_row(row, contract, 3600)
        check(problems != [], f"{name} not detected")
        detected[name] = problems[0][:120]
    table = run.process_table()
    check(any(p["pid"] == os.getpid() for p in table), "process table lacks this process")
    mem = run.memory_status()
    check(mem.get("total_phys_gib", 0) > 1, f"memory status {mem}")
    ports = run.listening_ports()
    return {"detected": detected, "processes": len(table), "memory": mem, "listeners_in_blocks": ports}


def unit_instrumentation(suite: Suite) -> Dict[str, Any]:
    import m7_evaluation as ev
    from btt_parallel import M7EpisodeTracker, RunCoordinator, StandbySettings, initial_coordination_state
    from btt_rewards import REWARD_V2, RewardTerms

    check("preserve_all" in inspect.signature(ev.run_episodes).parameters, "run_episodes has no preserve_all")
    check("preserve_all" in inspect.signature(ev.evaluate_checkpoint).parameters, "evaluate_checkpoint has no preserve_all")
    row = ev._row({"target_break_ticks": [3, 9], "startup_mode": "standby_promoted", "failure_penalty_terms": 1,
                   "last_consumed_tick": 431})
    for key in ("target_break_ticks", "startup_mode", "failure_penalty_terms", "last_consumed_tick"):
        check(key in row, f"evaluation row lacks {key}")

    class StubEnv:
        current_startup = {"mode": "standby_promoted"}
        max_episode_steps = 3600
        standby_settings = StandbySettings(preboot=True, count=1)

    coord_dir = suite.root / "instrumentation" / "coordination"
    coord = RunCoordinator.create(coord_dir, initial_coordination_state("t", "test", None))
    tracker = M7EpisodeTracker(run_id="t", role="test", rank=0, coordinator=coord,
                               artifact_root=suite.root / "instrumentation" / "artifacts",
                               ledger_path=suite.root / "instrumentation" / "ledger.jsonl", env=StubEnv(), reward=REWARD_V2)
    tracker.labels_for_new_episode()
    script = [(0, 0), (1, 1), (0, 2), (2, 3), (0, 4), (1, 5)]   # (newly broken, consumed tick)
    for n, tick in script:
        terms = RewardTerms(total=n - 0.001, newly_broken=n, target_term=float(n), step_term=-0.001, clear_term=0.0,
                            failure_term=0.0)
        tracker.note_step(terms, False, False, {"consumed_tick": tick})
    check(tracker._current["target_break_ticks"] == [1, 3, 3, 5], f"break ticks {tracker._current['target_break_ticks']}")
    check(tracker._current["targets_broken"] == 4, "targets")
    return {"target_break_ticks": tracker._current["target_break_ticks"], "row_keys": sorted(row)}


def _synthetic_rows(targets: Sequence[int], ends: Sequence[str], *, idle: Sequence[bool] = (), seed: int = 0,
                    clears: int = 0) -> List[Dict[str, Any]]:
    rows = []
    for i, (t, e) in enumerate(zip(targets, ends)):
        length = 3600 if e == "horizon" else 1500
        is_idle = bool(idle[i]) if idle else False
        last = (length - 2000) if is_idle else (length - 100)
        ticks = sorted([max(0, last - 10 * k) for k in range(t)]) if t else []
        rows.append({"end_reason": e, "targets_broken": t, "length": length, "cleared": False,
                     "completion_time_passed": None, "target_break_ticks": ticks, "raw_return": 0.0,
                     "native_action_digest": f"{seed}-{i}"})
    for k in range(clears):
        rows[k] = {"end_reason": "clear", "targets_broken": 10, "length": 900, "cleared": True,
                   "completion_time_passed": 800 + k, "completion_input_tick": 801 + k,
                   "target_break_ticks": list(range(0, 1000, 100))[:10], "raw_return": 0.0,
                   "native_action_digest": f"c{seed}-{k}"}
    return rows


def unit_decision_rule(suite: Suite) -> Dict[str, Any]:
    import numpy as np

    import m7d_analysis as an

    rng = np.random.default_rng(7)

    def arm(mean_t: float, fall: float, idle: float = 0.0, clears: int = 0, n: int = 100) -> List[Dict[str, Any]]:
        t = np.clip(np.round(rng.normal(mean_t, 1.2, n)), 0, 9).astype(int).tolist()
        ends = ["fall" if rng.random() < fall else "horizon" for _ in range(n)]
        idl = [e == "horizon" and rng.random() < idle for e in ends]
        return _synthetic_rows(t, ends, idle=idl, clears=clears)

    def scenario(v1: Callable[[], Any], v2: Callable[[], Any]) -> str:
        per_seed = {s: {"v1": v1(), "v2": v2()} for s in (0, 1, 2)}
        return an.decide(an.paired_statistics(per_seed))["classification"]

    def identical() -> str:
        per_seed = {}
        for s in (0, 1, 2):
            rows = arm(4.0, 0.6)
            per_seed[s] = {"v1": rows, "v2": list(rows)}
        return an.decide(an.paired_statistics(per_seed))["classification"]

    results = {
        "identical": identical(),
        "v2_more_targets": scenario(lambda: arm(4.0, 0.6), lambda: arm(5.5, 0.6)),
        "v2_fewer_targets": scenario(lambda: arm(4.0, 0.6), lambda: arm(2.5, 0.6)),
        "v2_fewer_falls_same_targets": scenario(lambda: arm(4.0, 0.8, 0.0), lambda: arm(4.0, 0.3, 0.0)),
        "v2_survival_for_targets": scenario(lambda: arm(4.0, 0.8), lambda: arm(3.2, 0.1)),
        "v2_fewer_falls_but_idles": scenario(lambda: arm(4.0, 0.8, 0.0), lambda: arm(4.0, 0.3, 0.9)),
        "v2_more_clears": scenario(lambda: arm(4.0, 0.6), lambda: arm(4.0, 0.6, clears=3)),
        "v2_fewer_clears": scenario(lambda: arm(4.0, 0.6, clears=3), lambda: arm(4.0, 0.6)),
    }
    expected = {"identical": "inconclusive - more evidence required", "v2_more_targets": "v2 preferred",
                "v2_fewer_targets": "v1 retained", "v2_fewer_falls_same_targets": "v2 preferred",
                "v2_survival_for_targets": "v1 retained",
                "v2_fewer_falls_but_idles": "inconclusive - more evidence required",
                "v2_more_clears": "v2 preferred", "v2_fewer_clears": "v1 retained"}
    for k, want in expected.items():
        check(results[k] == want, f"{k}: {results[k]} != {want}")
    return {"scenarios": results}


# -- game cases ----------------------------------------------------------------------------------------------------------


def paired_bounded_training(suite: Suite) -> Dict[str, Any]:
    import m7d_run as run

    out: Dict[str, Any] = {"runs": {}}
    exps = {r: derive_bounded(suite, r) for r in ("v1", "v2")}
    expected = mm.expected_initial_policy_digest(exps["v1"], return_obs_rms=True)
    check(expected == mm.expected_initial_policy_digest(exps["v2"], return_obs_rms=True), "paired untrained models")
    check(expected == mm.expected_initial_policy_digest(mm.load_run(mm.run_by_name("m7d_s0_v1")), return_obs_rms=True),
          "the bounded twin must share the full profile's untrained model")
    for r in ("v1", "v2"):
        exp = exps[r]
        pre = run.system_state(label=f"before pf_s0_{r}")
        check(not pre["battleship_pids"], f"BattleShip running before: {pre['battleship_pids']}")
        res = run.train_once(config=suite.root / "configs" / f"pf_s0_{r}.toml", run_dir=exp.run_dir, contract=exp.reward,
                             horizon=int(exp.values["environment.horizon"]),
                             log_path=suite.root / "logs" / f"pf_s0_{r}.log",
                             monitor_path=suite.root / "monitor" / f"pf_s0_{r}.jsonl")
        check(res["exit_code"] == 0 and not res["stop_reason"], f"pf_s0_{r}: exit {res['exit_code']} {res['stop_reason']}")
        ver = run.verify_training_run(exp.run_dir, exp, expected_initial=expected)
        mm.write_json(suite.root / "verify" / f"pf_s0_{r}.json", ver)
        check(ver["ok"], f"pf_s0_{r} verification: {ver['problems']}")
        mon = res["monitor"]
        check(mon["max_battleship_processes"] <= mm.MAX_GAME_PROCESSES and not mon["hard_alerts"],
              f"monitor: {mon['max_battleship_processes']} {mon['hard_alerts']}")
        post = run.system_state(label=f"after pf_s0_{r}")
        check(not post["battleship_pids"] and not post["battleship_listeners"], "leak after the run")
        lc = ver["checks"]["lifecycle"]
        check((lc.get("promotions") or 0) > 0, f"no standby promotion in pf_s0_{r}: {lc}")
        out["runs"][r] = {"wall_s": res["wall_s"], "episodes": ver["checks"]["episodes"],
                          "lifecycle": lc, "monitor": {k: mon[k] for k in ("max_battleship_processes",
                                                                           "max_battleship_listeners", "cpu_util",
                                                                           "avail_commit_gib", "worker_threads")},
                          "initial_policy": ver["checks"].get("initial_policy"),
                          "artifacts": {k: ver["checks"]["artifacts"][k] for k in ("artifacts", "first_consumed_tick",
                                                                                  "startup_modes")}}
    # Paired gameplay ("common random numbers"): same seed, same untrained policy, same PPO sampling stream, so both
    # runs play identical episodes until the first rollout that contains a fall; only the update after that rollout
    # can differ (the v2 fall reward is 5.0 lower). Checkpoints before that update must be identical as well.
    from m7d_run import jsonl_rows

    rollout = 5120
    rows = {r: jsonl_rows(exps[r].run_dir / "metrics" / "episodes.jsonl")[0] for r in ("v1", "v2")}

    def rollout_of(e: Mapping[str, Any]) -> int:
        return (int(e["sb3_num_timesteps_seen"]) + rollout - 1) // rollout

    fall_rollouts = [rollout_of(e) for e in rows["v1"] if e["end_reason"] == "fall"]
    k_f = min(fall_rollouts) if fall_rollouts else 10 ** 9
    early = {r: {(e["rank"], e["worker_episode"]): e for e in rows[r] if rollout_of(e) <= k_f} for r in ("v1", "v2")}
    check(set(early["v1"]) == set(early["v2"]), f"episodes up to rollout {k_f} differ: {sorted(early['v1'])} "
                                                f"{sorted(early['v2'])}")
    same = 0
    for key, a in early["v1"].items():
        b = early["v2"][key]
        gameplay = ("native_action_digest", "steps", "targets_broken", "end_reason", "target_break_ticks")
        check(all(a[k] == b[k] for k in gameplay), f"episode {key}: gameplay differs between v1 and v2")
        want = -5.0 if a["end_reason"] == "fall" else 0.0
        check(abs((b["return"] - a["return"]) - want) < 1e-9, f"episode {key}: return difference {b['return'] - a['return']}")
        same += 1
    check(same > 0, "no finished episode to compare before the first fall rollout")
    ck = {}
    for r in ("v1", "v2"):
        ck[r] = run.checkpoint_digests(exps[r].run_dir / "checkpoints" / "ckpt_000000000")
    check(ck["v1"] == ck["v2"] == tuple(expected), f"ckpt_000000000 digests {ck} expected {expected}")
    identical_sets, diverged_sets = [], []
    for t in range(rollout, 25_600, rollout):
        a = run.checkpoint_digests(exps["v1"].run_dir / "checkpoints" / f"ckpt_{t:09d}")
        b = run.checkpoint_digests(exps["v2"].run_dir / "checkpoints" / f"ckpt_{t:09d}")
        (identical_sets if a == b else diverged_sets).append(t)
        if t < k_f * rollout:
            check(a == b, f"ckpt_{t:09d} differs before the first fall rollout ({k_f})")
    falls = {r: sum(1 for e in rows[r] if e["end_reason"] == "fall") for r in ("v1", "v2")}
    pens = {r: sum(int(e["failure_penalty_terms"]) for e in rows[r]) for r in ("v1", "v2")}
    check(pens["v1"] == 0 and pens["v2"] == falls["v2"], f"penalty terms {pens} falls {falls}")
    out.update({"first_fall_rollout": None if k_f == 10 ** 9 else k_f,
                "identical_episodes_until_first_fall_rollout": same, "falls": falls, "penalty_terms": pens,
                "identical_checkpoint_sets": identical_sets, "diverged_checkpoint_sets": diverged_sets,
                "ckpt0_policy_digest": ck["v1"][0][:16], "ckpt0_obs_rms_digest": ck["v1"][1][:16]})
    suite.shared["bounded"] = {r: str(exps[r].run_dir) for r in ("v1", "v2")}
    return out


def bounded_posthoc_evaluation(suite: Suite) -> Dict[str, Any]:
    import torch

    import m7_evaluation as ev
    import m7d_run as run
    from btt_parallel import m7_contracts
    from m7_runtime import install_kill_on_close_job

    torch.set_num_threads(1)
    install_kill_on_close_job()
    exps = {r: derive_bounded(suite, r) for r in ("v1", "v2")}
    results: Dict[str, Any] = {}
    rows: Dict[str, Any] = {}
    plan = {"deterministic_episodes": 2, "stochastic_episodes": 12}
    for r in ("v1", "v2"):
        exp = exps[r]
        settings = run.evaluation_settings(exp)
        for label, ckpt in (("initial", exp.run_dir / "checkpoints" / "ckpt_000000000"), ("final", exp.run_dir / "final")):
            out = suite.root / "eval" / f"pf_s0_{r}" / label
            mon = run.Monitor(out=suite.root / "monitor" / "evaluation.jsonl", root_pid=os.getpid()).start()
            try:
                res = ev.evaluate_checkpoint(ckpt, out, settings=settings, deterministic_episodes=2,
                                             stochastic_episodes=12, expected_contracts=m7_contracts(3600, exp.reward),
                                             label=label, preserve_all=True)
            finally:
                m = mon.stop()
            check(m["max_battleship_processes"] <= mm.MAX_GAME_PROCESSES and not m["hard_alerts"], f"monitor {m['hard_alerts']}")
            ver = run.verify_evaluation(res, exp.reward, 3600, plan)
            check(ver["ok"], f"pf_s0_{r} {label}: {ver['problems']}")
            arts = [e["artifact_dir"] for mode in res["modes"].values() for e in mode["episodes"]]
            av = run.verify_artifacts(arts, exp.reward.contract)
            check(av["ok"] and av["artifacts"] == 14, f"artifacts {av}")
            modes = {e["startup_mode"] for mode in res["modes"].values() for e in mode["episodes"]}
            check("standby_promoted" in modes, f"no promoted evaluation episode: {modes}")
            results[f"{r}:{label}"] = {"verification": ver["per_mode"], "artifacts": av["first_consumed_tick"],
                                       "startup_modes": av["startup_modes"], "max_battleship": m["max_battleship_processes"]}
            rows[f"{r}:{label}"] = res
            try:
                ev.evaluate_checkpoint(ckpt, out, settings=settings, deterministic_episodes=1, stochastic_episodes=0,
                                       label=label)
                check(False, "an evaluation reused an existing directory")
            except FileExistsError:
                pass
    for mode in ("deterministic", "stochastic"):
        a = rows["v1:initial"]["modes"][mode]["episodes"]
        b = rows["v2:initial"]["modes"][mode]["episodes"]
        check(len(a) == len(b), "paired initial evaluations: episode counts")
        for x, y in zip(a, b):
            check((x["native_action_digest"], x["targets_broken"], x["length"], x["end_reason"]) ==
                  (y["native_action_digest"], y["targets_broken"], y["length"], y["end_reason"]),
                  f"initial {mode}: paired evaluation episodes differ")
            want = -5.0 if x["end_reason"] == "fall" else 0.0
            check(abs((y["raw_return"] - x["raw_return"]) - want) < 1e-9, "initial: return difference")
    det = rows["v1:final"]["modes"]["deterministic"]
    suite.shared["bounded_eval"] = {k: str(suite.root / "eval" / f"pf_s0_{k.split(':')[0]}" / k.split(":")[1])
                                   for k in rows}
    return {"sets": results, "final_v1_deterministic_identical": det.get("deterministic_episodes_identical")}


def bounded_replay(suite: Suite) -> Dict[str, Any]:
    import m7d_run as run
    from m7_runtime import install_kill_on_close_job

    install_kill_on_close_job()
    exp = derive_bounded(suite, "v2")
    rows = []
    for label in ("initial", "final"):
        for mode in ("deterministic", "stochastic"):
            f = suite.root / "eval" / "pf_s0_v2" / label / mode / "evaluation.json"
            rows += [dict(e, _file=str(f)) for e in mm.read_json(f)["episodes"]]
    check(rows, "no evaluation rows to replay")
    rows.sort(key=lambda e: (bool(e["cleared"]), e["targets_broken"]), reverse=True)
    chosen = [rows[0]]
    fall = next((e for e in rows if e["end_reason"] == "fall" and e is not rows[0]), None)
    if fall is not None:
        chosen.append(fall)
    horizon = next((e for e in rows if e["end_reason"] == "horizon" and e not in chosen), None)
    if horizon is not None:
        chosen.append(horizon)
    records = []
    for k, e in enumerate(chosen):
        rec = run.replay_one(REPO_ROOT / e["artifact_dir"], suite.root / "replay" / f"r{k}", executable=exp.executable,
                             extra_env=dict(exp.extra_env), index=9500 + k, expected_break_ticks=e["target_break_ticks"])
        check(rec["ok"], f"replay {e['episode_id']}: {rec['checks']} {rec.get('final_matches')}")
        records.append({"episode": e["episode_id"], "end_reason": e["end_reason"], "targets": e["targets_broken"],
                        "submitted": rec["submitted"], "checks": rec["checks"],
                        "host_frame_equal": rec["final_matches"].get("host_frame_equal"), "stepping_s": rec["stepping_s"]})
    return {"replayed": records}


def unit_episode_census(suite: Suite) -> Dict[str, Any]:
    """The evaluation accounting: a clear needs four agreeing witnesses, and the census must count the
    executed episodes against the planned ones so a skipped evaluation set cannot disappear silently."""
    import m7d_analysis as an

    full = _synthetic_rows([3, 4], ["horizon", "fall"], clears=1)
    check(an.clear_witnesses(full)["verified_clears"] == 1, "a complete clear was not counted")
    check(an.clear_witnesses(full)["witnesses_agree"], "witnesses disagree on a complete clear")
    for drop, name in ((("cleared",), "cleared flag"), (("completion_time_passed",), "completion clock"),
                       (("targets_broken",), "ten targets"), (("end_reason",), "end reason")):
        partial = [dict(r) for r in full]
        for key in drop:
            partial[0][key] = {"targets_broken": 9, "end_reason": "horizon"}.get(key, None) \
                if key in ("targets_broken", "end_reason") else (False if key == "cleared" else None)
        w = an.clear_witnesses(partial)
        check(w["verified_clears"] == 0, f"a clear missing its {name} was still counted: {w}")
        check(not w["witnesses_agree"], f"witnesses agreed although the {name} was missing: {w}")
    none_rows = _synthetic_rows([0, 6], ["fall", "horizon"])
    w = an.clear_witnesses(none_rows)
    check(w["verified_clears"] == 0 and w["witnesses_agree"] and w["targets_max"] == 6, f"clear-free set: {w}")

    census = an.episode_census()
    rows = census["evaluation"]
    check({(r["category"], r["mode"]) for r in rows} >= {(c, m) for c in ("initial", "final", "curve")
                                                         for m in ("stochastic", "deterministic")},
          "the census lost one of the approved evaluation categories")
    total = sum(r["episodes_total"] for r in rows)
    check(total == census["totals"]["evaluation_episodes"], "census rows do not sum to the reported total")
    check(census["totals"]["all_episodes"] == total + census["totals"]["training_episodes"], "grand total")
    for r in rows:
        check(r["episodes_total"] == r["episode_rows_preserved"],
              f"{r['category']}/{r['mode']}: counted episodes != preserved rows")
        check(r["witnesses_agree"], f"{r['category']}/{r['mode']}: clear witnesses disagree")
        check(r["episodes_total"] == r["episodes_planned"] and r["complete"],
              f"{r['category']}/{r['mode']}: {r['episodes_total']} episodes run against {r['episodes_planned']} planned")
        if r["evaluations"]:
            check(len(r["episodes_per_evaluation"]) == 1
                  and r["episodes_per_evaluation"][0] * r["evaluations"] == r["episodes_total"],
                  f"{r['category']}/{r['mode']}: uneven episode counts {r['episodes_per_evaluation']}")
    check(census["protocol_complete"] and not census["missing_evaluations"],
          f"an approved evaluation set is missing: {census['missing_evaluations']}")
    primary = [r for r in rows if r["in_primary_endpoint"]]
    check(len(primary) == 1 and (primary[0]["category"], primary[0]["mode"]) == ("final", "stochastic"),
          "the primary endpoint is not the final stochastic set")
    return {"totals": census["totals"], "protocol_complete": census["protocol_complete"],
            "missing_evaluations": census["missing_evaluations"],
            "categories": [f"{r['category']}/{r['mode']}={r['episodes_total']}" for r in rows]}


def existing_suites(suite: Suite) -> Dict[str, Any]:
    cmds = {
        "m7b_config_tests": [sys.executable, "rl/m7b_config_tests.py", "--root", str(suite.root / "m7b_config")],
        "m7c_standby_selected": [sys.executable, "rl/m7c_standby_tests.py", "unit", "cold_vs_standby_replay",
                                 "terminal_paths_promotion", "--root", str(suite.root / "m7c")],
        "m7b_smoke_selected": [sys.executable, "rl/m7b_smoke.py", "tas_v1_v2", "fall_v1_v2", "truncation_v2",
                               "--root", str(suite.root / "m7b_smoke")],
    }
    out = {}
    for name, cmd in cmds.items():
        t0 = time.perf_counter()
        log_path = suite.root / "logs" / f"{name}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w", encoding="utf-8", newline="\n") as lf:
            rc = subprocess.run(cmd, cwd=str(REPO_ROOT), stdout=lf, stderr=subprocess.STDOUT, timeout=3600).returncode
        tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-6:]
        out[name] = {"exit": rc, "seconds": round(time.perf_counter() - t0, 1), "tail": tail}
        check(rc == 0, f"{name} exit {rc}: {tail}")
    return out


UNIT_CASES: Dict[str, Callable[[Suite], Dict[str, Any]]] = {
    "unit_matrix_profiles": unit_matrix_profiles,
    "unit_fresh_paired_init": unit_fresh_paired_init,
    "unit_reward_normalization": unit_reward_normalization,
    "unit_directory_guards": unit_directory_guards,
    "unit_resume_guard": unit_resume_guard,
    "unit_validators": unit_validators,
    "unit_instrumentation": unit_instrumentation,
    "unit_decision_rule": unit_decision_rule,
    "unit_episode_census": unit_episode_census,
}
GAME_CASES: Dict[str, Callable[[Suite], Dict[str, Any]]] = {
    "paired_bounded_training": paired_bounded_training,
    "bounded_posthoc_evaluation": bounded_posthoc_evaluation,
    "bounded_replay": bounded_replay,
    "existing_suites": existing_suites,
}
ALL_CASES = {**UNIT_CASES, **GAME_CASES}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cases", nargs="*", help="case names, 'unit' or 'game' (default: all)")
    parser.add_argument("--root", default=None, help="output root (default: runs/_m7d_preflight_<utc>)")
    args = parser.parse_args(argv)
    names: List[str] = []
    for c in args.cases or ["unit", "game"]:
        names += list(UNIT_CASES) if c == "unit" else list(GAME_CASES) if c == "game" else [c]
    unknown = [n for n in names if n not in ALL_CASES]
    if unknown:
        print(f"unknown cases: {unknown}; known: {list(ALL_CASES)}", flush=True)
        return 2
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = Path(args.root) if args.root else REPO_ROOT / "runs" / f"_m7d_preflight_{stamp}"
    root = root if root.is_absolute() else REPO_ROOT / root
    root.mkdir(parents=True, exist_ok=True)
    suite = Suite(root)
    print(f"M7d preflight: {len(names)} case(s) -> {ec.repo_relative(root)}", flush=True)
    ok = True
    for n in names:
        ok &= suite.run(n, ALL_CASES[n])
    passed = sum(1 for r in suite.results.values() if r["status"] == "PASS")
    print(f"M7d preflight: {passed}/{len(suite.results)} PASS", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
