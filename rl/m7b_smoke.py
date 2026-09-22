#!/usr/bin/env python3
"""M7b game-backed validation: TOML-configured training parity, btt_reward_v2, checkpoints, resume.

    python rl/m7b_smoke.py                 # every case, in order (launches BattleShip)
    python rl/m7b_smoke.py tas_v1_v2 fall_v1_v2

Cases: tas_v1_v2 (the 447-step TAS returns 19.553 under v1 and v2), fall_v1_v2
(the known 432-step fall returns -0.432 under v1 and -5.432 under v2, penalty
recorded in the episode summary and the artifact labels), truncation_v2 (a
horizon truncation receives no terminal term), config_parity (a run driven
by the checked-in v1 TOML with bounded operational overrides reproduces the
M7a M7Config path episode for episode), v2_ppo_smoke (bounded PPO through the
v2 profile: training initialises, v2 rewards reach PPO, checkpoint sets with
VecNormalize statistics save, the final set reloads and infers in the final
evaluation, artifacts carry btt_reward_v2), resume_allowed (a resume with
permitted operational changes continues the v2 run in a new directory with
lineage), resume_rejected (reward / PPO / horizon / architecture /
VecNormalize / executable changes are refused before any directory exists).

After every case: zero BattleShip.exe processes and the user's
build-us/Release/BattleShip.cfg.json byte-identical to its value at the
start of the suite. Outputs go under runs/_m7b_smoke_<utc>/ (git-ignored).
Standard library + NumPy + Gymnasium at module level only: spawn children
re-import this file.
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing
import os
import shutil
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import experiment_config as ec  # noqa: E402
from btt_rewards import REWARD_V1, REWARD_V2, RewardContract, expected_return  # noqa: E402
from m7_smoke import (  # noqa: E402
    EXECUTABLE,
    FALL_TICK,
    FLAGS,
    REPLAY,
    USER_CONFIG,
    CaseFailure,
    Suite,
    artifact_rows_are_canonical,
    battleship_pids,
    check,
    fall_script,
    log,
    prepare_workers,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
V1_TOML = REPO_ROOT / "rl" / "configs" / "m7_mario_us_reward_v1.toml"
V2_TOML = REPO_ROOT / "rl" / "configs" / "m7_mario_us_reward_v2.toml"
TAS_RETURN = 19.553
FALL_RETURN_V1 = -0.432
FALL_RETURN_V2 = -5.432


def derive(suite: Suite, profile: Path, name: str, **changes: Any) -> ec.Experiment:
    """The checked-in profile with bounded operational / smoke-size overrides, written as its own TOML file."""
    base = ec.load_experiment(profile)
    values = dict(base.values)
    values["run.output_root"] = str(suite.root)
    values["run.name"] = name
    values.update(changes)
    text = ec.to_toml_text(values, header=f"derived by rl/m7b_smoke.py from {profile.name} for case {name}")
    d = suite.root / "configs"
    d.mkdir(exist_ok=True)
    path = d / f"{name}.toml"
    path.write_text(text, encoding="utf-8")
    return ec.load_experiment(path)


SMOKE_TRAIN = {"environment.process_count": 2, "ppo.n_steps": 2560, "run.total_transitions": 10240, "environment.horizon": 600,
               "checkpoint.interval": 5120, "evaluation.interval": 0, "evaluation.initial": False, "evaluation.final": False,
               "artifacts.periodic_episodes": 4, "run.mode": "train"}


# -- reward contracts on the real game ------------------------------------------------------------------


def _tas_return(out: Path, contract: RewardContract) -> Dict[str, Any]:
    from battleship_env import native_to_action
    from battleship_process import LaunchConfig
    from btt_parallel import M7BattleShipBTTEnv, M7RewardWrapper, TERMINATION_NATIVE_CLEAR
    from btti_replay import read_btti_rows
    from m7_runtime import PortCandidates, prepare_worker_runtime

    out.mkdir(parents=True)
    prepare_worker_runtime(out / "runtime", EXECUTABLE)
    base = M7BattleShipBTTEnv(LaunchConfig(executable=EXECUTABLE, working_dir=out / "runtime", run_root=out / "episodes",
                                           extra_env=dict(FLAGS)), max_episode_steps=3600, rank=0, ports=PortCandidates(0))
    env = M7RewardWrapper(base, contract)
    rewards: List[float] = []
    terms: List[Dict[str, Any]] = []
    try:
        _obs, info = env.reset()
        check(info["reward_contract"] == contract.contract, "reset info contract")
        for row in read_btti_rows(str(REPLAY)):
            _o, r, term, trunc, info = env.step(native_to_action(row.buttons, row.stick_x, row.stick_y))
            rewards.append(r)
            terms.append(info["reward_terms"])
            if term or trunc:
                break
    finally:
        env.close()
    res = base.last_step_result
    check(term and not trunc and info.get("termination_reason") == TERMINATION_NATIVE_CLEAR, f"{contract.contract}: not a native clear")
    check(len(rewards) == 447 and res.consumed_tick == 446 and res.observation.input_tick == 447, "replay completion values")
    total = math.fsum(rewards)
    check(abs(total - TAS_RETURN) < 1e-9, f"{contract.contract}: TAS return {total} != {TAS_RETURN}")
    check(all(t["failure_term"] == 0.0 for t in terms) and terms[-1]["clear_term"] == 10.0 and env.episode_failure_terms == 0,
          f"{contract.contract}: terms")
    return {"steps": len(rewards), "return_fsum": round(total, 9), "clear_term": terms[-1]["clear_term"],
            "failure_terms": env.episode_failure_terms, "targets_broken": env.episode_targets_broken}


def tas_v1_v2(suite: Suite) -> Dict[str, Any]:
    d = suite.dir("tas_v1_v2")
    return {c.contract: _tas_return(d / c.contract, c) for c in (REWARD_V1, REWARD_V2)}


def _scripted_vec_run(base: Path, contract: RewardContract, script: Callable[[int], List[int]], *, horizon: int,
                      steps_limit: int, experiment: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from m7_vec_env import M7SubprocVecEnv
    from run_artifacts import read_artifact

    factories, _coord = prepare_workers(base, [dict(rank=0, horizon=horizon, preserve_all=True, reward_contract=contract,
                                                    experiment=experiment, exit_timeout=5.0)], f"scripted_{contract.contract}")
    venv = M7SubprocVecEnv(factories, step_timeout=120)
    out: Dict[str, Any] = {}
    try:
        venv.reset()
        for i in range(steps_limit):
            _obs, rew, dones, infos = venv.step(np.array([script(i)]))
            if dones[0]:
                ep = infos[0]["m7_episode"]
                out = {"done_at_step_index": i, "last_reward": float(rew[0]), "termination_reason": infos[0].get("termination_reason"),
                       "truncation_reason": infos[0].get("truncation_reason"), "episode": ep}
                break
    finally:
        venv.close()
    check(out, "episode did not finish within the step limit")
    ep = out["episode"]
    art_dir = Path(ep["artifact_dir"]) if Path(ep["artifact_dir"]).is_absolute() else REPO_ROOT / ep["artifact_dir"]
    art = read_artifact(art_dir)
    out["artifact"] = artifact_rows_are_canonical(art_dir)
    out["artifact_labels"] = {k: art.metadata["labels"].get(k) for k in ("reward_contract", "reward_constants", "experiment",
                                                                          "failure_penalty_applied", "failure_penalty_total",
                                                                          "episode_return", "end_reason")}
    out["artifact_contracts_reward"] = art.metadata["labels"]["contracts"]["reward_contract"]
    out["close"] = {k: v for k, v in (venv.close_report or {}).items() if k != "ranks"}
    return out


def fall_v1_v2(suite: Suite) -> Dict[str, Any]:
    d = suite.dir("fall_v1_v2")
    res = {}
    v2 = ec.load_experiment(V2_TOML)
    for contract, want in ((REWARD_V1, FALL_RETURN_V1), (REWARD_V2, FALL_RETURN_V2)):
        r = _scripted_vec_run(d / contract.contract, contract, fall_script, horizon=3600, steps_limit=800,
                              experiment=v2.summary() if contract is REWARD_V2 else None)
        ep = r["episode"]
        check(r["termination_reason"] == "native_failure" and ep["end_reason"] == "fall" and ep["status"] == "terminal", str(r))
        check(ep["steps"] == FALL_TICK + 1 == 432 and ep["targets_broken"] == 0, f"{contract.contract}: fall geometry {ep['steps']}")
        check(abs(ep["return"] - want) < 1e-9, f"{contract.contract}: fall return {ep['return']} != {want}")
        check(abs(r["last_reward"] - (-0.001 + contract.failure_penalty)) < 1e-9, f"{contract.contract}: terminal step reward {r['last_reward']}")
        check(ep["reward_contract"] == contract.contract and ep["failure_penalty_applied"] == bool(contract.failure_penalty)
              and ep["failure_penalty_terms"] == (1 if contract.failure_penalty else 0)
              and ep["failure_penalty_total"] == contract.failure_penalty, f"{contract.contract}: summary {ep}")
        lab = r["artifact_labels"]
        check(lab["reward_contract"] == contract.contract and lab["reward_constants"] == contract.to_json()
              and abs(lab["episode_return"] - want) < 1e-9 and lab["failure_penalty_applied"] == bool(contract.failure_penalty)
              and r["artifact_contracts_reward"] == contract.contract, f"{contract.contract}: artifact labels {lab}")
        check(r["artifact"]["rows"] == 432 and r["artifact"]["terminal"]["termination_reason"] == "native_failure", str(r["artifact"]))
        if contract is REWARD_V2:
            check(lab["experiment"]["reward_contract"] == "btt_reward_v2" and lab["experiment"]["name"] == v2.name, "experiment label")
        res[contract.contract] = {k: v for k, v in r.items() if k != "episode"} | {"episode_return": ep["return"], "steps": ep["steps"]}
    return res


def truncation_v2(suite: Suite) -> Dict[str, Any]:
    d = suite.dir("truncation_v2")
    r = _scripted_vec_run(d, REWARD_V2, lambda i: [0, 0], horizon=300, steps_limit=400, experiment=ec.load_experiment(V2_TOML).summary())
    ep = r["episode"]
    check(r["truncation_reason"] == "max_episode_steps" and ep["end_reason"] == "horizon" and ep["status"] == "truncated", str(r))
    check(ep["steps"] == 300 and abs(ep["return"] - (-0.3 + ep["targets_broken"])) < 1e-9, f"truncation return {ep['return']}")
    check(ep["failure_penalty_applied"] is False and ep["failure_penalty_terms"] == 0 and ep["failure_penalty_total"] == 0.0,
          "penalty on a horizon truncation")
    check(abs(r["last_reward"] - (-0.001)) < 1e-9, f"last step reward {r['last_reward']}")
    return {k: v for k, v in r.items() if k != "episode"} | {"episode_return": ep["return"], "steps": ep["steps"],
                                                             "targets_broken": ep["targets_broken"]}


# -- TOML-driven training ---------------------------------------------------------------------------------------


def _episode_rows(run: Path) -> List[Dict[str, Any]]:
    p = run / "metrics" / "episodes.jsonl"   # absent when no episode finished during the run
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()] if p.is_file() else []


def _provenance_checks(run: Path, exp: ec.Experiment, contract: RewardContract) -> Dict[str, Any]:
    from m7_evaluation import checkpoint_reward_contract, read_checkpoint_set
    from m7_runtime import sha256_file

    run_json = json.loads((run / "run.json").read_text(encoding="utf-8"))
    check((run / "experiment.toml").is_file() and (run / "experiment_resolved.json").is_file(), "experiment files missing")
    check(sha256_file(run / "experiment.toml") == exp.source.sha256, "experiment.toml is not the byte-exact source")
    resolved = json.loads((run / "experiment_resolved.json").read_text(encoding="utf-8"))
    check(resolved["fingerprints"]["semantic_fingerprint"] == exp.semantic_fingerprint
          and resolved["resolved"]["reward"] == contract.to_json(), "experiment_resolved.json")
    e = run_json["experiment"]
    check(e["semantic_fingerprint"] == exp.semantic_fingerprint and e["source"]["sha256"] == exp.source.sha256
          and e["reward_contract"] == contract.contract and run_json["reward_contract"] == contract.to_json()
          and run_json["contracts"]["reward_contract"] == contract.contract and run_json["executable"]["sha256"]
          and run_json["revisions"]["head"] and run_json["versions"]["stable_baselines3"], "run.json provenance")
    sets = sorted(p for p in (run / "checkpoints").iterdir()) + [run / "final"]
    for s in sets:
        meta = read_checkpoint_set(s)
        check((s / "vecnormalize.pkl").is_file() and meta["reward_contract"] == contract.to_json()
              and meta["experiment"]["semantic_fingerprint"] == exp.semantic_fingerprint
              and checkpoint_reward_contract(meta) == contract, f"{s.name}: checkpoint metadata")
    summary = json.loads((run / "training_summary.json").read_text(encoding="utf-8"))
    check(summary["experiment"]["semantic_fingerprint"] == exp.semantic_fingerprint and summary["reward_contract"] == contract.to_json(),
          "training_summary provenance")
    labels = []
    for meta_path in run.glob("workers/w*/artifacts/*/metadata.json"):
        m = json.loads(meta_path.read_text(encoding="utf-8"))
        lab = m["labels"]
        check(lab["reward_contract"] == contract.contract and lab["contracts"]["reward_contract"] == contract.contract
              and lab["experiment"]["semantic_fingerprint"] == exp.semantic_fingerprint, f"{meta_path}: labels")
        labels.append(meta_path.parent.name)
    return {"checkpoint_sets": [s.name for s in sets], "artifacts_labelled": len(labels), "run_json_experiment": e["name"]}


def config_parity(suite: Suite) -> Dict[str, Any]:
    """The checked-in v1 TOML (bounded overrides) reproduces the M7a M7Config path episode for episode."""
    from m7_trainer import M7Config, config_from_experiment, run_training

    exp = derive(suite, V1_TOML, "parity_toml", **SMOKE_TRAIN)
    legacy = ec.from_legacy_arguments("train", {"n_envs": 2, "total_timesteps": 10240, "run_id": "parity_toml", "seed": 0,
                                                "horizon": 600, "periodic_episodes": 4, "eval_workers": None, "eval_seed": 12345,
                                                "eval_stochastic_episodes": 20, "eval_deterministic_episodes": 2,
                                                "checkpoint_interval": 5120, "runs_dir": str(suite.root), "exe": None,
                                                "eval_interval": 0, "eval_initial": False, "eval_final": False})
    check(legacy.semantic_fingerprint == exp.semantic_fingerprint, "derived TOML != legacy train arguments (semantic)")
    m7a = M7Config(run_id="parity_m7a", n_envs=2, total_timesteps=10240, runs_dir=suite.root, purpose="test", horizon=600,
                   checkpoint_interval=5120, periodic_episodes=4)
    check(ec.compare_compatibility(exp.compatibility_view(), m7a.compatibility_view()) == {}, "M7a config view differs")
    s_a = run_training(m7a)
    s_b = run_training(config_from_experiment(exp, purpose="test"))
    for label, s in (("m7a", s_a), ("toml", s_b)):
        check(s["status"] == "completed" and s["cleanup"]["leak_free"] and s["user_config"]["byte_identical"], f"{label}: {s['status']}")
        check(s["timesteps"]["sb3_num_timesteps"] == 10240 and s["timesteps"]["n_updates"] == 20, f"{label}: timesteps")
    key = lambda e: (e["rank"], e["worker_episode"])  # noqa: E731
    rows_a = sorted(_episode_rows(suite.root / "parity_m7a"), key=key)
    rows_b = sorted(_episode_rows(suite.root / "parity_toml"), key=key)
    fields = ("rank", "worker_episode", "end_reason", "steps", "targets_broken", "native_action_digest", "cleared")
    view_a = [{f: e[f] for f in fields} | {"return": round(e["return"], 9)} for e in rows_a]
    view_b = [{f: e[f] for f in fields} | {"return": round(e["return"], 9)} for e in rows_b]
    check(view_a == view_b and len(view_a) >= 2, f"episode statistics differ: {view_a} vs {view_b}")
    check(s_a["ppo"] == s_b["ppo"] | {"seed": s_a["ppo"]["seed"]}, f"resolved PPO values differ: {s_a['ppo']} vs {s_b['ppo']}")
    roll_a = [(r["rollout"], r["targets_mean"], r["end_reasons"]) for r in s_a["rollouts"]]
    roll_b = [(r["rollout"], r["targets_mean"], r["end_reasons"]) for r in s_b["rollouts"]]
    check(roll_a == roll_b, "rollout statistics differ")
    check(s_b["experiment"]["source"]["kind"] == "toml" and s_a["experiment"] is None, "provenance blocks")
    prov = _provenance_checks(suite.root / "parity_toml", exp, REWARD_V1)
    # The M7a-path run records no experiment block but the same reward contract and compatibility view.
    run_a = json.loads((suite.root / "parity_m7a" / "run.json").read_text(encoding="utf-8"))
    check(run_a["experiment"] is None and run_a["reward_contract"] == REWARD_V1.to_json()
          and ec.compare_compatibility(run_a["compatibility_view"], exp.compatibility_view()) == {}, "M7a-path run.json")
    return {"episodes": view_b, "rollouts": roll_b, "semantic_fingerprint": exp.semantic_fingerprint,
            "legacy_translation_equal": True, "e2e_tps": {"m7a": s_a["throughput"]["end_to_end_transitions_per_s"],
                                                          "toml": s_b["throughput"]["end_to_end_transitions_per_s"]},
            "provenance": prov}


def v2_ppo_smoke(suite: Suite) -> Dict[str, Any]:
    """Bounded PPO through the v2 profile (N=2, 15,360 transitions, 3600-tick horizon, final evaluation 1 + 2 episodes)."""
    from m7_trainer import M7PPO, config_from_experiment, run_training

    exp = derive(suite, V2_TOML, "v2_ppo_smoke", **{"environment.process_count": 2, "ppo.n_steps": 2560,
                                                    "run.total_transitions": 15360, "checkpoint.interval": 5120,
                                                    "evaluation.interval": 0, "evaluation.initial": False, "evaluation.final": True,
                                                    "evaluation.deterministic_episodes": 1, "evaluation.stochastic_episodes": 2,
                                                    "artifacts.periodic_episodes": 2, "run.mode": "train"})
    check(exp.reward == REWARD_V2, "derived v2 profile lost its reward")
    s = run_training(config_from_experiment(exp))
    check(s["status"] == "completed" and s["cleanup"]["leak_free"] and s["user_config"]["byte_identical"], f"{s['status']} {s['cleanup']}")
    check(s["timesteps"]["sb3_num_timesteps"] == 15360 and s["timesteps"]["n_updates"] == 30, str(s["timesteps"]))
    run = suite.root / "v2_ppo_smoke"
    rows = _episode_rows(run)
    finished = [e for e in rows if e["end_reason"] != "aborted"]
    check(finished, "no finished episode")
    fall_rows, mism = [], []
    for e in finished:
        want = expected_return(e["targets_broken"], e["steps"], cleared=e["cleared"], native_failure=e["end_reason"] == "fall",
                               contract=REWARD_V2)
        if abs(e["return"] - want) > 1e-9:
            mism.append((e["rank"], e["worker_episode"], e["return"], want))
        check(e["reward_contract"] == "btt_reward_v2", "episode row contract")
        check(e["failure_penalty_applied"] == (e["end_reason"] == "fall"), f"penalty flag vs end reason: {e['end_reason']}")
        if e["end_reason"] == "fall":
            fall_rows.append({"rank": e["rank"], "worker_episode": e["worker_episode"], "steps": e["steps"],
                              "targets": e["targets_broken"], "return": round(e["return"], 6)})
    check(not mism, f"returns disagree with the v2 closed form: {mism}")
    # SB3 saw v2 rewards: the Monitor-compatible episode returns equal the contract returns.
    prov = _provenance_checks(run, exp, REWARD_V2)
    model = M7PPO.load(str(run / "final" / "model.zip"), device="cpu")
    check(model.m7_reward_contract == REWARD_V2.to_json() and model.m7_experiment["semantic_fingerprint"] == exp.semantic_fingerprint,
          "final model.zip provenance")
    evals = list((run / "evaluations").iterdir())
    check(len(evals) == 1, f"expected one final evaluation, got {evals}")
    ev = json.loads((evals[0] / "evaluation_summary.json").read_text(encoding="utf-8"))
    check(ev["reward_contract"] == REWARD_V2.to_json() and ev["experiment"]["reward_contract"] == "btt_reward_v2"
          and ev["model_reward_contract"] == REWARD_V2.to_json(), "evaluation summary provenance")
    for mode in ("deterministic", "stochastic"):
        m = ev["modes"][mode]
        check(m["frozen_check"]["policy_parameters_unchanged"] and m["frozen_check"]["obs_rms_unchanged"]
              and m["reward_contract"] == REWARD_V2.to_json() and m["aggregate"]["episodes"] == (1 if mode == "deterministic" else 2),
              f"{mode}: evaluation")
        for row in m["episodes"]:
            want = expected_return(row["targets_broken"], row["length"], cleared=row["cleared"],
                                   native_failure=row["end_reason"] == "fall", contract=REWARD_V2)
            check(abs(row["raw_return"] - want) < 1e-9, f"{mode}: evaluation raw return {row['raw_return']} != {want}")
    eval_art = list(evals[0].glob("*/workers/w*/artifacts/*/metadata.json"))
    check(eval_art, "no evaluation artifact")
    for p in eval_art:
        lab = json.loads(p.read_text(encoding="utf-8"))["labels"]
        check(lab["reward_contract"] == "btt_reward_v2" and lab["experiment"]["reward_contract"] == "btt_reward_v2", "eval artifact label")
    return {"episodes": s["episodes"], "falls_with_penalty": fall_rows, "e2e_tps": s["throughput"]["end_to_end_transitions_per_s"],
            "checkpoints": [c["label"] for c in s["checkpoints"]], "evaluation": {m: ev["modes"][m]["aggregate"] for m in ev["modes"]},
            "eval_artifacts": len(eval_art), "provenance": prov, "rollout_return_means": [r["return_mean"] for r in s["rollouts"]],
            "train_metrics_last": (s["rollouts"][-1].get("train_metrics") or {}).get("train/explained_variance")}


def resume_allowed(suite: Suite) -> Dict[str, Any]:
    from m7_runtime import sha256_file
    from m7_trainer import config_from_experiment, run_training

    source_run = suite.root / "v2_ppo_smoke"
    source = source_run / "checkpoints" / "ckpt_000005120"
    before = {str(p.relative_to(source_run)): sha256_file(p) for p in source_run.rglob("*") if p.is_file()}
    exp = derive(suite, V2_TOML, "v2_resumed", **{"environment.process_count": 2, "ppo.n_steps": 2560,
                                                  "run.total_transitions": 10240, "checkpoint.interval": 10240,
                                                  "evaluation.interval": 0, "evaluation.initial": False, "evaluation.final": False,
                                                  "artifacts.periodic_episodes": 3, "run.mode": "resume",
                                                  "resume.source_checkpoint": str(source), "run.notes": "operational changes only",
                                                  "environment.request_timeout_s": 12.0})
    cfg = config_from_experiment(exp)
    check(cfg.total_timesteps == 5120 and cfg.resume_from == source.resolve(), f"resume accounting {cfg.total_timesteps}")
    s = run_training(cfg)
    after = {str(p.relative_to(source_run)): sha256_file(p) for p in source_run.rglob("*") if p.is_file()}
    check(before == after, "the source run changed during resume")
    t = s["timesteps"]
    check(t["start"] == 5120 and t["sb3_num_timesteps"] == 10240 and t["transitions_this_run"] == 5120, f"timesteps {t}")
    check(s["status"] == "completed" and s["cleanup"]["leak_free"], str(s["status"]))
    lin = s["lineage"]
    check(lin and lin[-1]["num_timesteps"] == 5120 and lin[-1]["reward_contract"] == "btt_reward_v2"
          and lin[-1]["experiment"]["name"] == "v2_ppo_smoke" and lin[-1]["executable_change"] is None, f"lineage {lin}")
    prov = _provenance_checks(suite.root / "v2_resumed", exp, REWARD_V2)
    final_meta = json.loads((suite.root / "v2_resumed" / "final" / "checkpoint.json").read_text(encoding="utf-8"))
    check(final_meta["num_timesteps"] == 10240 and final_meta["lineage"][-1]["run_id"] == "v2_ppo_smoke", "final set lineage")
    rows = _episode_rows(suite.root / "v2_resumed")   # one rollout of 2560 ticks per worker may finish no episode
    check(all(e["reward_contract"] == "btt_reward_v2" for e in rows), "resumed episodes contract")
    return {"timesteps": t, "lineage": lin, "source_files_unchanged": len(before), "provenance": prov,
            "episodes_started": s["episodes"]["started"], "episodes_finished": s["episodes"]["finished"]}


def resume_rejected(suite: Suite) -> Dict[str, Any]:
    from m7_evaluation import CheckpointError
    from m7_trainer import M7Run, config_from_experiment, run_training

    source = suite.root / "v2_ppo_smoke" / "checkpoints" / "ckpt_000005120"
    common = {"environment.process_count": 2, "ppo.n_steps": 2560, "run.total_transitions": 10240, "checkpoint.interval": 5120,
              "evaluation.interval": 0, "evaluation.initial": False, "evaluation.final": False, "run.mode": "resume",
              "resume.source_checkpoint": str(source)}
    rejected = {}
    attempts = {
        "reward_v1": (V1_TOML, {}, "reward"),
        "gamma": (V2_TOML, {"ppo.gamma": 0.99}, "gamma"),                      # M7a PPO check fires first
        "horizon": (V2_TOML, {"environment.horizon": 1800}, "horizon"),
        "net_arch": (V2_TOML, {"ppo.net_arch": [32, 32]}, "ppo.net_arch"),
        "clip_obs": (V2_TOML, {"ppo.vecnormalize.clip_obs": 5.0}, "ppo.vecnormalize.clip_obs"),
        "process_count": (V2_TOML, {"environment.process_count": 1, "ppo.n_steps": 5120}, "n_envs"),
        "custom_reward": (V2_TOML, {"contracts.reward": "custom", "reward.failure_penalty": -4.0}, "reward"),
        "flags": (V2_TOML, {"environment.raphnet_disable": False}, "extra_env"),
    }
    for name, (profile, changes, needle) in attempts.items():
        run_name = f"rejected_{name}"
        exp = derive(suite, profile, run_name, **{**common, **changes})
        try:
            run_training(config_from_experiment(exp))
            raise CaseFailure(f"{name}: resume accepted")
        except (CheckpointError, ec.ConfigError) as exc:
            rejected[name] = str(exc)[:200]
        check(needle in rejected[name], f"{name}: message lacks {needle!r}: {rejected[name]}")
        check(not (suite.root / run_name).exists(), f"{name}: a rejected resume created a run directory")
    # Executable identity: a set whose recorded executable sha256 differs is refused unless explicitly allowed.
    tampered = suite.root / "ckpt_other_exe"
    shutil.copytree(source, tampered)
    m = json.loads((tampered / "checkpoint.json").read_text(encoding="utf-8"))
    m["executable"]["sha256"] = "0" * 64
    (tampered / "checkpoint.json").write_text(json.dumps(m, indent=2), encoding="utf-8")
    exp = derive(suite, V2_TOML, "rejected_executable", **dict(common, **{"resume.source_checkpoint": str(tampered)}))
    try:
        run_training(config_from_experiment(exp))
        raise CaseFailure("executable change accepted without the override")
    except CheckpointError as exc:
        rejected["executable"] = str(exc)[:200]
    check("executable sha256" in rejected["executable"] and not (suite.root / "rejected_executable").exists(), rejected["executable"])
    allowed = derive(suite, V2_TOML, "allowed_executable", **dict(common, **{"resume.source_checkpoint": str(tampered),
                                                                             "resume.allow_executable_change": True}))
    meta = M7Run(config_from_experiment(allowed))._source_checkpoint()   # verification only; nothing is created
    check(meta["_executable_change"]["accepted_by"] == "resume.allow_executable_change"
          and not (suite.root / "allowed_executable").exists(), "override not recorded")
    return {"rejected": rejected, "executable_override": meta["_executable_change"]}


# -- runner ---------------------------------------------------------------------------------------------------------

CASES: Dict[str, Callable[[Suite], Dict[str, Any]]] = {
    "tas_v1_v2": tas_v1_v2,
    "fall_v1_v2": fall_v1_v2,
    "truncation_v2": truncation_v2,
    "config_parity": config_parity,
    "v2_ppo_smoke": v2_ppo_smoke,
    "resume_allowed": resume_allowed,
    "resume_rejected": resume_rejected,
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cases", nargs="*", help="case names (default: all)")
    parser.add_argument("--root", default=None, help="output root (default: runs/_m7b_smoke_<utc>)")
    args = parser.parse_args(argv)
    names = list(args.cases or CASES)
    unknown = [n for n in names if n not in CASES]
    if unknown:
        parser.error(f"unknown case(s) {unknown}")
    if any(n in names for n in ("resume_allowed", "resume_rejected")) and "v2_ppo_smoke" not in names:
        names.insert(0, "v2_ppo_smoke")
    from m7_runtime import file_fingerprint, install_kill_on_close_job, wait_until_no_process

    install_kill_on_close_job()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = (Path(args.root) if args.root else REPO_ROOT / "runs" / f"_m7b_smoke_{stamp}").resolve()
    root.mkdir(parents=True, exist_ok=False)
    suite = Suite(root)
    user_cfg = file_fingerprint(USER_CONFIG)
    before = battleship_pids()
    if before:
        log(f"ERROR: BattleShip already running: {before}")
        return 2
    log(f"M7b smoke: {len(names)} case(s), output {root}, user config sha256 {user_cfg['sha256'][:16]}")
    failures = 0
    for name in names:
        t0 = time.perf_counter()
        try:
            details = CASES[name](suite)
            ok, error = True, None
        except Exception as exc:  # noqa: BLE001
            ok, error, details = False, f"{type(exc).__name__}: {exc}", {"traceback": traceback.format_exc()[-4000:]}
        left = wait_until_no_process(timeout=20)
        cfg_now = file_fingerprint(USER_CONFIG)
        cfg_ok = cfg_now.get("sha256") == user_cfg.get("sha256")
        if left or not cfg_ok:
            ok = False
            error = (error or "") + f" | leaked {left}" * bool(left) + " | user config bytes changed" * (not cfg_ok)
        failures += 0 if ok else 1
        suite.results[name] = {"ok": ok, "error": error, "wall_s": round(time.perf_counter() - t0, 2),
                               "battleship_after": left, "user_config_sha256_unchanged": cfg_ok,
                               "user_config_mtime_unchanged": cfg_now.get("mtime_ns") == user_cfg.get("mtime_ns"),
                               "details": details}
        log(f"{'PASS' if ok else 'FAIL'} {name} ({suite.results[name]['wall_s']} s)" + (f": {error}" if error else ""))
        with open(root / "m7b_smoke_results.json", "w", encoding="utf-8", newline="\n") as fp:
            json.dump({"cases": suite.results, "user_config_start": user_cfg}, fp, indent=2, default=str)
    log(f"M7b smoke: {len(names) - failures}/{len(names)} PASS; results {root / 'm7b_smoke_results.json'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
