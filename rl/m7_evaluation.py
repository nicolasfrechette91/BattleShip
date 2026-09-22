#!/usr/bin/env python3
"""M7: evaluation of PPO checkpoints (and a uniform-random Track 1 baseline) on fresh BattleShip processes.

Evaluation never updates the policy or the normalisation statistics:

- the checkpoint set (model.zip + vecnormalize.pkl + checkpoint.json) is
  loaded and verified (file hashes, contracts); a missing or mismatched
  statistics file is refused;
- VecNormalize is loaded with training = False and norm_reward = False, so
  its running mean/variance never change; the policy parameters and the
  statistics are hashed before and after and must be identical;
- no optimizer step, no learn() call.

Modes: `deterministic` (argmax policy; the game is deterministic, so every
episode of one checkpoint is expected to be identical, which is checked with
the Python-side digest of the submitted canonical native actions),
`stochastic` (policy sampling with a fixed Torch seed), `random` (uniform
Track 1 actions from a seeded NumPy generator). Every episode runs in a fresh
BattleShip process through the same M7 worker stack as training (isolated
runtime directories, both M6 flags, the 3600-tick horizon, native-failure
termination, btt_reward_v1 for the diagnostic raw return, M4 artifacts).

Objective ranking (reward never overrides it): a verified clear ranks above
any incomplete episode; incomplete episodes rank by targets broken; clears
rank by lower completion_time_passed (completion_input_tick is reported
beside it, never compared).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import torch
from stable_baselines3.common.utils import set_random_seed
from stable_baselines3.common.vec_env import VecNormalize

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from btt_learning import TRACK1_BUTTON_STATES, TRACK1_STICK_STATES, TARGETS_TOTAL  # noqa: E402
from btt_parallel import (  # noqa: E402
    END_CLEAR,
    M7_HORIZON,
    RunCoordinator,
    WorkerFactory,
    WorkerSpec,
    initial_coordination_state,
)
from m7_runtime import check_path_budget, portable_path, prepare_worker_runtime, validate_port_blocks  # noqa: E402
from m7_vec_env import M7SubprocVecEnv  # noqa: E402

EVALUATION_SCHEMA = 1
MODES = ("deterministic", "stochastic", "random")


# -- objective ranking ------------------------------------------------------------------------------


def objective_key(episode: Mapping[str, Any]) -> Tuple[int, int, int]:
    """Larger is better. (verified clear, targets broken, -completion_time_passed)."""
    cleared = bool(episode.get("cleared")) and episode.get("completion_time_passed") is not None
    if cleared:
        return (1, int(TARGETS_TOTAL), -int(episode["completion_time_passed"]))
    return (0, int(episode.get("targets_broken", 0)), 0)


def rank_episodes(episodes: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    """Best first. Ties keep their input order (stable sort); reward is never consulted."""
    return sorted(episodes, key=objective_key, reverse=True)


# -- statistics ----------------------------------------------------------------------------------------


def bootstrap_mean_ci(values: Sequence[float], *, resamples: int = 10000, seed: int = 0,
                      level: float = 0.95) -> Optional[Tuple[float, float]]:
    if len(values) < 2:
        return None
    rng = np.random.default_rng(seed)
    data = np.asarray(values, dtype=np.float64)
    means = data[rng.integers(0, len(data), size=(resamples, len(data)))].mean(axis=1)
    lo, hi = np.quantile(means, [(1 - level) / 2, 1 - (1 - level) / 2])
    return float(lo), float(hi)


def bootstrap_diff_ci(a: Sequence[float], b: Sequence[float], *, resamples: int = 10000, seed: int = 0,
                      level: float = 0.95) -> Optional[Dict[str, float]]:
    """CI of mean(a) - mean(b) with independent resampling of both groups."""
    if len(a) < 2 or len(b) < 2:
        return None
    rng = np.random.default_rng(seed)
    x, y = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    da = x[rng.integers(0, len(x), size=(resamples, len(x)))].mean(axis=1)
    db = y[rng.integers(0, len(y), size=(resamples, len(y)))].mean(axis=1)
    lo, hi = np.quantile(da - db, [(1 - level) / 2, 1 - (1 - level) / 2])
    return {"mean_difference": float(x.mean() - y.mean()), "ci_low": float(lo), "ci_high": float(hi), "level": level}


def aggregate(episodes: Sequence[Mapping[str, Any]], *, seed: int = 0) -> Dict[str, Any]:
    n = len(episodes)
    if n == 0:
        return {"episodes": 0}
    targets = [int(e["targets_broken"]) for e in episodes]
    lengths = [int(e["steps"]) for e in episodes]
    returns = [float(e["return"]) for e in episodes]
    end = {}
    for e in episodes:
        end[e["end_reason"]] = end.get(e["end_reason"], 0) + 1
    clears = [e for e in episodes if e["end_reason"] == END_CLEAR]
    hist = {str(k): targets.count(k) for k in range(TARGETS_TOTAL + 1)}
    best = rank_episodes(episodes)[0]
    fastest = min(clears, key=lambda e: int(e["completion_time_passed"])) if clears else None
    ci = bootstrap_mean_ci(targets, seed=seed)
    return {
        "episodes": n,
        "targets_mean": round(statistics.fmean(targets), 4),
        "targets_mean_ci95": None if ci is None else [round(ci[0], 4), round(ci[1], 4)],
        "targets_median": statistics.median(targets),
        "targets_std": round(statistics.pstdev(targets), 4),
        "targets_min": min(targets),
        "targets_max": max(targets),
        "targets_histogram": hist,
        "end_reasons": end,
        "terminated": sum(1 for e in episodes if e.get("status") == "terminal"),
        "truncated": sum(1 for e in episodes if e.get("status") == "truncated"),
        "clears": len(clears),
        "falls": end.get("fall", 0),
        "horizon_truncations": end.get("horizon", 0),
        "lifecycle_failures": end.get("lifecycle_failure", 0),
        "length_mean": round(statistics.fmean(lengths), 2),
        "return_mean_diagnostic": round(statistics.fmean(returns), 4),
        "return_max_diagnostic": round(max(returns), 4),
        "best_episode": _row(best),
        "fastest_clear": None if fastest is None else _row(fastest),
        "distinct_action_digests": len({e.get("native_action_digest") for e in episodes}),
    }


def _row(e: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "rank": e.get("rank"),
        "worker_episode": e.get("worker_episode"),
        "episode_id": e.get("episode_id"),
        "targets_broken": e.get("targets_broken"),
        "raw_return": e.get("return"),
        "length": e.get("steps"),
        "terminated": e.get("status") == "terminal",
        "truncated": e.get("status") == "truncated",
        "end_reason": e.get("end_reason"),
        "termination_reason": e.get("termination_reason"),
        "truncation_reason": e.get("truncation_reason"),
        "failure_outcome": e.get("failure_outcome"),
        "cleared": e.get("cleared"),
        "completion_time_passed": e.get("completion_time_passed"),
        "completion_input_tick": e.get("completion_input_tick"),
        "artifact_dir": e.get("artifact_dir"),
        "native_action_digest": e.get("native_action_digest"),
        "anomaly_events": e.get("anomaly_events"),
    }


# -- checkpoint sets ------------------------------------------------------------------------------------

CHECKPOINT_SCHEMA = 1
MODEL_FILE = "model.zip"
VECNORM_FILE = "vecnormalize.pkl"
META_FILE = "checkpoint.json"
PRESERVATION_FILE = "preservation_state.json"


class CheckpointError(RuntimeError):
    """A checkpoint set is incomplete, altered or incompatible."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_checkpoint_set(directory: os.PathLike | str, *, expected_contracts: Optional[Mapping[str, Any]] = None
                        ) -> Dict[str, Any]:
    """Verify a checkpoint set and return its metadata. Raises CheckpointError on any problem."""
    d = Path(directory)
    meta_path = d / META_FILE
    if not meta_path.is_file():
        raise CheckpointError(f"{meta_path} missing: not an M7 checkpoint set")
    with open(meta_path, encoding="utf-8") as fp:
        meta = json.load(fp)
    if meta.get("checkpoint_schema") != CHECKPOINT_SCHEMA:
        raise CheckpointError(f"checkpoint_schema {meta.get('checkpoint_schema')!r}, expected {CHECKPOINT_SCHEMA}")
    for name in (MODEL_FILE, VECNORM_FILE, PRESERVATION_FILE):
        path = d / name
        if not path.is_file():
            raise CheckpointError(f"{path} missing: the model and its normalisation statistics must travel together")
        expected = (meta.get("files") or {}).get(name)
        if expected is None:
            raise CheckpointError(f"checkpoint.json records no hash for {name}")
        actual = _sha256(path)
        if actual != expected:
            raise CheckpointError(f"{name} sha256 {actual[:16]}... does not match checkpoint.json {expected[:16]}...")
    if expected_contracts is not None:
        stored = meta.get("contracts") or {}
        diffs = {k: {"checkpoint": stored.get(k), "expected": v} for k, v in expected_contracts.items()
                 if stored.get(k) != v}
        if diffs:
            raise CheckpointError(f"incompatible contracts: {json.dumps(diffs)[:2000]}")
    return meta


def policy_parameter_digest(model: Any) -> str:
    h = hashlib.sha256()
    for name, tensor in sorted(model.policy.state_dict().items()):
        h.update(name.encode())
        h.update(tensor.detach().cpu().numpy().tobytes())
    return h.hexdigest()


def obs_rms_digest(vecnorm: VecNormalize) -> str:
    rms = vecnorm.obs_rms
    h = hashlib.sha256()
    h.update(np.asarray(rms.mean, dtype=np.float64).tobytes())
    h.update(np.asarray(rms.var, dtype=np.float64).tobytes())
    h.update(np.float64(rms.count).tobytes())
    return h.hexdigest()


# -- running an evaluation ---------------------------------------------------------------------------------


@dataclass
class EvaluationSettings:
    executable: str
    horizon: int = M7_HORIZON
    n_workers: int = 4
    seed: int = 12345
    extra_env: Tuple[Tuple[str, str], ...] = (("SSB64_RL_NO_RENDER", "1"), ("SSB64_RAPHNET_DISABLE", "1"))
    startup_attempts: int = 3
    request_timeout: float = 10.0
    step_timeout: float = 900.0
    retain_failed_cap: int = 20


def _prepare_workers(root: Path, n: int, role: str, run_id: str, settings: EvaluationSettings, *,
                     preserve_all: bool) -> Tuple[List[WorkerFactory], Path]:
    root = Path(root).resolve()
    executable = Path(settings.executable).resolve()
    coord_dir = root / "coordination"
    RunCoordinator.create(coord_dir, initial_coordination_state(run_id, role, None))
    validate_port_blocks(range(n))
    factories = []
    for rank in range(n):
        wdir = root / "workers" / f"w{rank:02d}"
        prepare_worker_runtime(wdir / "runtime", executable)
        spec = WorkerSpec(rank=rank, run_id=run_id, role=role, worker_dir=str(wdir),
                          coordination_dir=str(coord_dir), executable=str(executable),
                          horizon=settings.horizon, base_seed=settings.seed, extra_env=tuple(settings.extra_env),
                          retain_failed_cap=settings.retain_failed_cap, startup_attempts=settings.startup_attempts,
                          request_timeout=settings.request_timeout, preserve_all=preserve_all)
        factories.append(WorkerFactory(spec))
    return factories, coord_dir


def run_episodes(*, mode: str, episodes: int, out_dir: Path, run_id: str, settings: EvaluationSettings,
                 model: Any = None, vecnorm_path: Optional[Path] = None, n_workers: Optional[int] = None) -> Dict[str, Any]:
    """Run `episodes` complete episodes in one mode; returns per-episode rows and aggregates.

    Collection order is deterministic: the first `episodes` completed
    episodes by vector step, then by rank. Episodes still running when the
    quota is met are aborted at close and never counted (reported as excess)."""
    if mode not in MODES:
        raise ValueError(mode)
    if (mode == "random") != (model is None):
        raise ValueError("a model is required for deterministic/stochastic, forbidden for random")
    n = max(1, min(int(n_workers or settings.n_workers), int(episodes)))
    out_dir = Path(out_dir)
    check_path_budget(out_dir, suffix=70)
    out_dir.mkdir(parents=True, exist_ok=False)
    role = "random_baseline" if mode == "random" else "evaluation"
    factories, coord_dir = _prepare_workers(out_dir, n, role, run_id, settings, preserve_all=(mode == "deterministic"))
    t0 = time.perf_counter()
    venv = M7SubprocVecEnv(factories, step_timeout=settings.step_timeout)
    env: Any = venv
    vecnorm = None
    params_before = rms_before = None
    if model is not None:
        if vecnorm_path is None:
            raise CheckpointError("policy evaluation requires the checkpoint's VecNormalize statistics")
        vecnorm = VecNormalize.load(str(vecnorm_path), venv)
        vecnorm.training = False       # statistics frozen
        vecnorm.norm_reward = False    # raw btt_reward_v1 returns
        env = vecnorm
        params_before = policy_parameter_digest(model)
        rms_before = obs_rms_digest(vecnorm)
    set_random_seed(settings.seed)
    rng = np.random.default_rng(settings.seed)
    collected: List[Dict[str, Any]] = []
    excess = 0
    vec_steps = 0
    try:
        env.seed(settings.seed)
        obs = env.reset()
        while len(collected) < episodes:
            if mode == "random":
                actions = np.stack([rng.integers(0, TRACK1_STICK_STATES, size=n),
                                    rng.integers(0, TRACK1_BUTTON_STATES, size=n)], axis=1)
            else:
                with torch.no_grad():
                    actions, _ = model.predict(obs, deterministic=(mode == "deterministic"))
            obs, _rewards, _dones, infos = env.step(actions)
            vec_steps += 1
            for info in infos:
                summary = info.get("m7_episode")
                if summary is None:
                    continue
                if len(collected) < episodes:
                    collected.append(dict(summary, mode=mode, order=len(collected)))
                else:
                    excess += 1
    finally:
        env.close()
    wall = time.perf_counter() - t0
    unchanged = None
    if model is not None:
        unchanged = {"policy_parameters_unchanged": policy_parameter_digest(model) == params_before,
                     "obs_rms_unchanged": obs_rms_digest(vecnorm) == rms_before,
                     "vecnormalize_training": vecnorm.training, "vecnormalize_norm_reward": vecnorm.norm_reward}
    close = venv.close_report or {}
    reports = venv.worker_reports()
    result = {
        "mode": mode,
        "episodes_requested": episodes,
        "workers": n,
        "seed": settings.seed,
        "wall_s": round(wall, 3),
        "vec_steps": vec_steps,
        "excess_episodes_not_counted": excess,
        "frozen_check": unchanged,
        "aggregate": aggregate(collected, seed=settings.seed),
        "episodes": [_row(e) | {"mode": mode, "order": e["order"]} for e in collected],
        "close": {k: v for k, v in close.items() if k != "ranks"},
        "workers_closed_cleanly": all(bool(e.get("closed_cleanly")) for e in close.get("ranks", {}).values()),
        "startup_failures": sum(len((r or {}).get("startup_failures", [])) for r in reports.values()),
        "coordination_state": RunCoordinator(coord_dir).read(),
    }
    if mode == "deterministic":
        digests = {e["native_action_digest"] for e in collected}
        result["deterministic_episodes_identical"] = len(digests) == 1
    with open(out_dir / "evaluation.json", "w", encoding="utf-8", newline="\n") as fp:
        json.dump(result, fp, indent=2)
        fp.write("\n")
    return result


def evaluate_checkpoint(checkpoint_dir: os.PathLike | str, out_dir: os.PathLike | str, *, settings: EvaluationSettings,
                        deterministic_episodes: int = 2, stochastic_episodes: int = 20,
                        expected_contracts: Optional[Mapping[str, Any]] = None, label: Optional[str] = None) -> Dict[str, Any]:
    """Full evaluation protocol for one checkpoint set (deterministic + stochastic sessions)."""
    from m7_trainer import M7PPO  # local: m7_trainer imports this module

    ckpt = Path(checkpoint_dir)
    meta = read_checkpoint_set(ckpt, expected_contracts=expected_contracts)
    if int(meta["contracts"]["horizon_native_ticks"]) != int(settings.horizon):
        raise CheckpointError(f"checkpoint horizon {meta['contracts']['horizon_native_ticks']} != evaluation horizon "
                              f"{settings.horizon}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=False)
    t0 = time.perf_counter()
    model = M7PPO.load(str(ckpt / MODEL_FILE), device="cpu")
    result: Dict[str, Any] = {
        "evaluation_schema": EVALUATION_SCHEMA,
        "label": label or ckpt.name,
        "checkpoint": portable_path(ckpt),
        "checkpoint_num_timesteps": meta.get("num_timesteps"),
        "checkpoint_n_updates": meta.get("n_updates"),
        "horizon": settings.horizon,
        "observation_note": "raw native observations -> btt_policy_obs_v1 (15 float32, unchanged) -> "
                            "VecNormalize (frozen statistics of the checkpoint) -> policy input",
        "modes": {},
    }
    if deterministic_episodes > 0:
        result["modes"]["deterministic"] = run_episodes(
            mode="deterministic", episodes=deterministic_episodes, out_dir=out / "deterministic",
            run_id=f"eval:{result['label']}", settings=settings, model=model, vecnorm_path=ckpt / VECNORM_FILE)
    if stochastic_episodes > 0:
        result["modes"]["stochastic"] = run_episodes(
            mode="stochastic", episodes=stochastic_episodes, out_dir=out / "stochastic",
            run_id=f"eval:{result['label']}", settings=settings, model=model, vecnorm_path=ckpt / VECNORM_FILE)
    result["wall_s"] = round(time.perf_counter() - t0, 3)
    with open(out / "evaluation_summary.json", "w", encoding="utf-8", newline="\n") as fp:
        json.dump(result, fp, indent=2)
        fp.write("\n")
    return result


def evaluate_random(out_dir: os.PathLike | str, *, settings: EvaluationSettings, episodes: int = 100) -> Dict[str, Any]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=False)
    r = run_episodes(mode="random", episodes=episodes, out_dir=out / "random", run_id="eval:random", settings=settings)
    result = {"evaluation_schema": EVALUATION_SCHEMA, "label": "random_track1", "horizon": settings.horizon,
              "policy": "uniform MultiDiscrete([9, 8]) from numpy.random.default_rng(seed)", "modes": {"random": r},
              "wall_s": r["wall_s"]}
    with open(out / "evaluation_summary.json", "w", encoding="utf-8", newline="\n") as fp:
        json.dump(result, fp, indent=2)
        fp.write("\n")
    return result


def learning_evidence(candidate: Sequence[float], initial: Sequence[float], random_baseline: Sequence[float],
                      *, seed: int = 0) -> Dict[str, Any]:
    """Target-count evidence: learning is claimed only if the candidate's mean exceeds BOTH baselines with
    the 95 % bootstrap CI of each difference strictly above zero."""
    vs_initial = bootstrap_diff_ci(candidate, initial, seed=seed)
    vs_random = bootstrap_diff_ci(candidate, random_baseline, seed=seed + 1)
    supported = bool(vs_initial and vs_random and vs_initial["ci_low"] > 0 and vs_random["ci_low"] > 0)
    return {"vs_initial": vs_initial, "vs_random": vs_random, "learning_supported": supported,
            "rule": "mean targets broken (stochastic evaluation) above both the initial policy and the random "
                    "baseline, 95 % bootstrap CI of each difference > 0"}


def finite(x: Any) -> bool:
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False
