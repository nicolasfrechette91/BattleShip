#!/usr/bin/env python3
"""M7a: machine-readable pilot report from a finished pilot run directory and a random-baseline evaluation.

Reads only files the trainer and the evaluator wrote (training_summary.json,
metrics/*.jsonl, evaluations/*/evaluation_summary.json, the random baseline's
evaluation_summary.json); launches nothing. Training-side curves are
reported as training statistics; learning is judged only by the fixed
evaluation protocol (stochastic evaluation of the final policy against the
initial policy and the random Track 1 baseline, see
m7_evaluation.learning_evidence) and never by training reward.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from m7_evaluation import aggregate, learning_evidence, rank_episodes  # noqa: E402

TRAIN_METRICS = ("train/approx_kl", "train/clip_fraction", "train/entropy_loss", "train/explained_variance",
                 "train/value_loss", "train/policy_gradient_loss", "train/loss")


def _jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _mode_rows(eval_summary: Mapping[str, Any], mode: str) -> List[Dict[str, Any]]:
    return list((eval_summary.get("modes", {}).get(mode) or {}).get("episodes") or [])


def training_windows(episodes: List[Dict[str, Any]], window: int = 51200) -> List[Dict[str, Any]]:
    """Finished training episodes grouped by the SB3 timestep at which they ended."""
    buckets: Dict[int, List[Dict[str, Any]]] = {}
    for e in episodes:
        if e.get("end_reason") == "aborted":
            continue
        t = int(e.get("sb3_num_timesteps_seen") or 0)
        buckets.setdefault((max(t - 1, 0)) // window, []).append(e)
    out = []
    for k in sorted(buckets):
        es = buckets[k]
        ends: Dict[str, int] = {}
        for e in es:
            ends[e["end_reason"]] = ends.get(e["end_reason"], 0) + 1
        out.append({"timesteps_from": k * window, "timesteps_to": (k + 1) * window, "episodes": len(es),
                    "targets_mean": round(statistics.fmean(e["targets_broken"] for e in es), 4),
                    "targets_max": max(e["targets_broken"] for e in es),
                    "return_mean": round(statistics.fmean(e["return"] for e in es), 4),
                    "length_mean": round(statistics.fmean(e["steps"] for e in es), 1),
                    "end_reasons": ends, "fall_rate": round(ends.get("fall", 0) / len(es), 4)})
    return out


def pilot_report(pilot_dir: Path, random_dir: Path) -> Dict[str, Any]:
    summary = json.loads((pilot_dir / "training_summary.json").read_text(encoding="utf-8"))
    rollouts = _jsonl(pilot_dir / "metrics" / "rollouts.jsonl")
    episodes = _jsonl(pilot_dir / "metrics" / "episodes.jsonl")
    evals: List[Dict[str, Any]] = []
    for d in sorted((pilot_dir / "evaluations").iterdir()):
        f = d / "evaluation_summary.json"
        if f.is_file():
            evals.append(json.loads(f.read_text(encoding="utf-8")))
    evals.sort(key=lambda e: int(e.get("checkpoint_num_timesteps") or 0))
    random_eval = json.loads((random_dir / "evaluation_summary.json").read_text(encoding="utf-8"))
    random_rows = _mode_rows(random_eval, "random")
    random_targets = [int(r["targets_broken"]) for r in random_rows]
    curve = []
    for e in evals:
        point: Dict[str, Any] = {"label": e["label"], "num_timesteps": e.get("checkpoint_num_timesteps"),
                                 "n_updates": e.get("checkpoint_n_updates"), "wall_s": e.get("wall_s")}
        for mode in ("deterministic", "stochastic"):
            m = e["modes"].get(mode) or {}
            a = m.get("aggregate") or {}
            point[mode] = {k: a.get(k) for k in ("episodes", "targets_mean", "targets_mean_ci95", "targets_median",
                                                 "targets_max", "targets_histogram", "clears", "falls",
                                                 "horizon_truncations", "lifecycle_failures", "length_mean",
                                                 "return_mean_diagnostic", "fastest_clear")}
            point[mode]["frozen_check"] = m.get("frozen_check")
            if mode == "deterministic":
                point[mode]["episodes_identical"] = m.get("deterministic_episodes_identical")
                point[mode]["episode"] = (m.get("episodes") or [None])[0]
        curve.append(point)
    initial = next((e for e in evals if int(e.get("checkpoint_num_timesteps") or 0) == 0), None)
    final = evals[-1] if evals else None
    init_targets = [int(r["targets_broken"]) for r in _mode_rows(initial, "stochastic")] if initial else []
    final_targets = [int(r["targets_broken"]) for r in _mode_rows(final, "stochastic")] if final else []
    evidence = learning_evidence(final_targets, init_targets, random_targets, seed=0) if final and initial else None
    per_point = []
    for e in evals:
        t = [int(r["targets_broken"]) for r in _mode_rows(e, "stochastic")]
        per_point.append({"label": e["label"], "num_timesteps": e.get("checkpoint_num_timesteps"),
                          **learning_evidence(t, init_targets, random_targets, seed=0)})
    all_eval_rows = [dict(r, label=e["label"]) for e in evals for m in ("deterministic", "stochastic")
                     for r in _mode_rows(e, m)]
    best = rank_episodes(all_eval_rows)[0] if all_eval_rows else None
    rollout_curve = [{"rollout": r["rollout"], "num_timesteps": r["num_timesteps"], "collect_s": r["collect_s"],
                      "optimize_wall_s": r.get("optimize_wall_s"), "train_s": r.get("train_s"),
                      "episodes_finished": r["episodes_finished"], "targets_mean": r["targets_mean"],
                      "targets_max": r["targets_max"], "return_mean": r["return_mean"], "end_reasons": r["end_reasons"],
                      **{k.split("/")[1]: (r.get("train_metrics") or {}).get(k) for k in TRAIN_METRICS}}
                     for r in rollouts]
    return {
        "milestone": "M7a",
        "report": "pilot",
        "pilot_run": summary["run_id"],
        "status": summary["status"],
        "config": summary["config"],
        "experiment": summary.get("experiment"),                       # M7b: profile identity + fingerprints
        "reward_contract": summary.get("reward_contract") or (summary["contracts"] or {}).get("reward_constants"),
        "ppo": summary["ppo"],
        "contracts": summary["contracts"],
        "seeds": summary["seeds"],
        "m6_flags": summary["m6_flags"],
        "executable": summary["executable"],
        "revisions": summary["revisions"],
        "versions": summary["versions"],
        "observation_path": summary["observation_path"],
        "timesteps": summary["timesteps"],
        "wall": summary["wall"],
        "throughput": {k: v for k, v in summary["throughput"].items() if k != "per_worker_native"},
        "time_split": summary["time_split"],
        "training_episodes": summary["episodes"],
        "training_windows": training_windows(episodes),
        "rollout_curve": rollout_curve,
        "evaluation_curve": curve,
        "random_baseline": {"label": random_eval.get("label"), "policy": random_eval.get("policy"),
                            "reward_contract": random_eval.get("reward_contract"),
                            "aggregate": (random_eval["modes"]["random"] or {}).get("aggregate"),
                            "workers": random_eval["modes"]["random"].get("workers"),
                            "wall_s": random_eval.get("wall_s")},
        "initial_policy": curve[0] if curve and curve[0]["num_timesteps"] == 0 else None,
        "final_policy": curve[-1] if curve else None,
        "learning_evidence": evidence,
        "learning_evidence_per_checkpoint": per_point,
        "best_evaluated_episode": best,
        "artifacts": {k: v for k, v in summary["artifacts"].items() if k != "written"} | {
            "written_count": len(summary["artifacts"]["written"])},
        "checkpoints": summary["checkpoints"],
        "failures": summary["failures"],
        "restarts": {k: v for k, v in summary["restarts"].items() if k != "startup_failures"}
        | {"startup_failures": summary["restarts"]["startup_failures"]},
        # M7c: process lifecycle of the run (standby settings, promotions, fallbacks, hidden/exposed time); None for M7a/M7b runs
        "lifecycle": {k: v for k, v in (summary.get("lifecycle") or {}).items() if k != "per_worker"} or None,
        "cleanup": summary["cleanup"],
        "user_config": summary["user_config"],
        "evaluation_overhead_s": summary["wall"]["eval_s_total"],
        "claims_policy": "No learning claim from training reward, single episodes or single target breaks. "
                         "learning_evidence.learning_supported is the only claim criterion.",
    }


def aggregate_rows(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Re-aggregate evaluation rows (used for combined views)."""
    if not rows:
        return None
    fixed = [dict(r, steps=r["length"], **{"return": r["raw_return"]},
                  status="terminal" if r["terminated"] else "truncated") for r in rows]
    return aggregate(fixed)
