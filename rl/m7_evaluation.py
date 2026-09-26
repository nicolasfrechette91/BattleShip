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

M7g Phase K: a checkpoint is evaluated under its OWN policy observation
contract as well (checkpoint.json contracts.policy_observation_contract):
btt_policy_obs_v2_spatial checkpoints run the v2 worker stack
(rl/m7g_obs.py, SSB64_RL_SPATIAL=1 added to the evaluation flags) and their
per-key VecNormalize statistics; the model's stored observation space,
policy class and VecNormalize keys must match that contract, so a v1 model
is never evaluated as v2 or vice versa. v1 checkpoints evaluate exactly as
before.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import pickle
import statistics
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import torch
from stable_baselines3.common.utils import set_random_seed
from stable_baselines3.common.vec_env import VecNormalize

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import m7g_obs as mo  # noqa: E402
from btt_learning import (  # noqa: E402
    POLICY_OBSERVATION_CONTRACT,
    TARGETS_TOTAL,
    TRACK1_BUTTON_STATES,
    TRACK1_STICK_STATES,
    make_policy_observation_space,
)
from btt_parallel import (  # noqa: E402
    END_CLEAR,
    M7_HORIZON,
    RunCoordinator,
    StandbySettings,
    WorkerFactory,
    WorkerSpec,
    initial_coordination_state,
)
from btt_rewards import (REWARD_V1, RewardContract, RewardContractError, reward_contract_from_json,  # noqa: E402
                         reward_extra_env)
from m7_runtime import (  # noqa: E402
    PORT_BLOCK_BASE,
    PORT_BLOCK_SIZE,
    check_path_budget,
    portable_path,
    prepare_worker_runtime,
    validate_port_blocks,
)
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
    row = _base_row(e)
    if e.get("eval_metrics") is not None:   # M7g Phase K btt_eval_metrics_v1, only when the evaluator enabled it
        row["eval_metrics"] = e["eval_metrics"]
    if e.get("reward_v3") is not None:      # M7l: the route reward record, route contracts only (v1 / v2 rows unchanged)
        row["reward_v3"] = e["reward_v3"]
    return row


def _base_row(e: Mapping[str, Any]) -> Dict[str, Any]:
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
        # M7d (additive): break timing, lifecycle and penalty facts of the worker episode summary
        "target_break_ticks": e.get("target_break_ticks"),
        "last_consumed_tick": e.get("last_consumed_tick"),
        "startup_mode": e.get("startup_mode"),
        "failure_penalty_terms": e.get("failure_penalty_terms"),
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
    stored = dict(meta.get("contracts") or {})
    if stored:
        # M7b: a legacy M7a `reward_constants` record (no failure_penalty) is btt_reward_v1 with 0.0 and is
        # normalised for the comparison; an inconsistent record is refused.
        try:
            reward = reward_contract_from_json(stored.get("reward_constants"), contract_id=stored.get("reward_contract"))
        except RewardContractError as exc:
            raise CheckpointError(f"{meta_path}: {exc}") from exc
        stored["reward_constants"] = reward.to_json()
        stored["reward_contract"] = reward.contract
        meta["contracts"] = stored
    if expected_contracts is not None:
        diffs = {k: {"checkpoint": stored.get(k), "expected": v} for k, v in expected_contracts.items()
                 if stored.get(k) != v}
        if diffs:
            raise CheckpointError(f"incompatible contracts: {json.dumps(diffs)[:2000]}")
    return meta


def checkpoint_reward_contract(meta: Mapping[str, Any]) -> RewardContract:
    """The reward contract a checkpoint set was trained under (never reinterpreted)."""
    contracts = meta.get("contracts") or {}
    return reward_contract_from_json(contracts.get("reward_constants"), contract_id=contracts.get("reward_contract"))


def policy_parameter_digest(model: Any) -> str:
    h = hashlib.sha256()
    for name, tensor in sorted(model.policy.state_dict().items()):
        h.update(name.encode())
        h.update(tensor.detach().cpu().numpy().tobytes())
    return h.hexdigest()


def obs_rms_digest(vecnorm: VecNormalize) -> str:
    """sha256 of the observation statistics. v1 (one RunningMeanStd): mean, var, count, exactly as M7a-M7f. A Dict
    observation (M7g v2; obs_rms is a dict over the normalised keys): key name + mean, var, count per key, sorted."""
    rms = vecnorm.obs_rms
    h = hashlib.sha256()
    for key, stats in (sorted(rms.items()) if isinstance(rms, dict) else ((None, rms),)):
        if key is not None:
            h.update(key.encode("ascii"))
        h.update(np.asarray(stats.mean, dtype=np.float64).tobytes())
        h.update(np.asarray(stats.var, dtype=np.float64).tobytes())
        h.update(np.float64(stats.count).tobytes())
    return h.hexdigest()


def obs_rms_record(vecnorm: VecNormalize) -> Dict[str, Any]:
    """The statistics facts of checkpoint.json: v1 {obs_rms_count} as before; a Dict observation adds the per-key
    counts and the normalised keys (the binary keys have no statistics)."""
    rms = vecnorm.obs_rms
    if not isinstance(rms, dict):
        return {"obs_rms_count": float(rms.count)}
    counts = {k: float(v.count) for k, v in sorted(rms.items())}
    return {"obs_rms_count": min(counts.values()), "obs_rms_counts": counts,
            "norm_obs_keys": list(vecnorm.norm_obs_keys or [])}


# -- M7g Phase K: observation identity of checkpoints, models and statistics ---------------------------------


def observation_space_of(observation: str) -> Any:
    if observation == mo.OBS_CONTRACT:
        return mo.make_observation_space()
    if observation == POLICY_OBSERVATION_CONTRACT:
        return make_policy_observation_space()
    raise CheckpointError(f"unknown policy observation contract {observation!r}")


def checkpoint_observation_contract(meta: Mapping[str, Any]) -> str:
    """The policy observation a checkpoint set was trained on (never reinterpreted)."""
    obs = (meta.get("contracts") or {}).get("policy_observation_contract")
    if obs not in (POLICY_OBSERVATION_CONTRACT, mo.OBS_CONTRACT):
        raise CheckpointError(f"checkpoint.json records policy observation {obs!r}: not a supported contract")
    if obs == mo.OBS_CONTRACT and meta["contracts"].get("policy_observation_contract_sha256") != mo.contract_digest():
        raise CheckpointError(f"checkpoint.json records {mo.OBS_CONTRACT} digest "
                              f"{meta['contracts'].get('policy_observation_contract_sha256')!r}, this code builds "
                              f"{mo.contract_digest()!r}")
    return obs


def check_model_identity(model: Any, observation: str) -> None:
    """A loaded model must have been built for `observation`: stored space, policy class, recorded contract."""
    expected = observation_space_of(observation)
    if model.observation_space != expected:
        raise CheckpointError(f"model observation space {model.observation_space} is not {observation}'s {expected}")
    policy_class = "MultiInputActorCriticPolicy" if observation == mo.OBS_CONTRACT else "ActorCriticPolicy"
    if type(model.policy).__name__ != policy_class:
        raise CheckpointError(f"model policy {type(model.policy).__name__} is not {policy_class} ({observation})")
    recorded = getattr(model, "m7_policy_observation", None)
    if (recorded or POLICY_OBSERVATION_CONTRACT) != observation:
        raise CheckpointError(f"model.zip records policy observation {recorded!r}, expected {observation!r}")


def check_vecnormalize_identity(vecnorm: VecNormalize, observation: str) -> None:
    """Statistics must belong to `observation`: one Box RunningMeanStd for v1, exactly the continuous keys for v2."""
    rms = vecnorm.obs_rms
    if observation == mo.OBS_CONTRACT:
        keys = list(vecnorm.norm_obs_keys or [])
        if not isinstance(rms, dict) or keys != list(mo.NORMALIZED_KEYS) or sorted(rms) != sorted(mo.NORMALIZED_KEYS):
            raise CheckpointError(f"VecNormalize statistics are not {observation}'s: norm_obs_keys {keys}, "
                                  f"statistics {sorted(rms) if isinstance(rms, dict) else type(rms).__name__}")
    elif isinstance(rms, dict) or tuple(np.shape(rms.mean)) != tuple(observation_space_of(observation).shape):
        raise CheckpointError(f"VecNormalize statistics are not {observation}'s (a Box of "
                              f"{observation_space_of(observation).shape})")


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
    # M7b: the reward contract of the diagnostic raw return (a checkpoint evaluation uses the checkpoint's own
    # contract), the experiment summary block for artifact labels, and the port block geometry.
    reward: RewardContract = REWARD_V1
    experiment: Optional[Dict[str, Any]] = None
    port_block_base: int = PORT_BLOCK_BASE
    port_block_size: int = PORT_BLOCK_SIZE
    # M7c standby lifecycle of the evaluation workers (same contract as training; defaults = off)
    standby_preboot: bool = False
    standby_count: int = 0
    standby_wait_timeout: float = 120.0
    # M7g Phase K: policy observation of the evaluation workers. None = the checkpoint's own contract
    # (evaluate_checkpoint) / btt_policy_obs_v1 (random baseline); an explicit value must match the checkpoint.
    observation: Optional[str] = None
    # M7g Phase K: record btt_eval_metrics_v1 per episode (rl/m7g_eval_metrics.py; adds SSB64_RL_TARGET_DIAG=1 to the
    # evaluation flags). Default off: every earlier evaluation is unchanged.
    eval_metrics: bool = False

    @property
    def observation_contract(self) -> str:
        return self.observation or POLICY_OBSERVATION_CONTRACT

    def effective_extra_env(self) -> Tuple[Tuple[str, str], ...]:
        """The native flags the evaluation workers boot with (the diagnostic flag added when metrics are on, and the
        flags the reward contract needs: M7j btt_reward_v3 reads the target diagnostic; v1 / v2 add none)."""
        needed = reward_extra_env(self.reward)
        if not self.eval_metrics and not needed:
            return tuple(self.extra_env)
        flags = dict(self.extra_env)
        if self.eval_metrics:
            from m7g_eval_metrics import with_diag_flag

            flags = dict(with_diag_flag(self.extra_env))
        flags.update(dict(needed))
        return tuple(flags.items())

    @property
    def records_flags(self) -> bool:
        """Whether an evaluation record carries extra_env (M7g v2 / metrics; M7j v3). Earlier v1 / v2 records unchanged."""
        return self.eval_metrics or bool(reward_extra_env(self.reward))

    def lifecycle(self) -> Dict[str, Any]:
        s = StandbySettings(preboot=self.standby_preboot, count=self.standby_count, wait_timeout=self.standby_wait_timeout).to_json()
        s["max_game_processes"] = int(self.n_workers) * (1 + int(self.standby_count))
        return s


def _prepare_workers(root: Path, n: int, role: str, run_id: str, settings: EvaluationSettings, *,
                     preserve_all: bool) -> Tuple[List[WorkerFactory], Path]:
    root = Path(root).resolve()
    executable = Path(settings.executable).resolve()
    coord_dir = root / "coordination"
    RunCoordinator.create(coord_dir, initial_coordination_state(run_id, role, None))
    validate_port_blocks(range(n), settings.port_block_base, settings.port_block_size)
    factories = []
    for rank in range(n):
        wdir = root / "workers" / f"w{rank:02d}"
        prepare_worker_runtime(wdir / "runtime", executable)
        spec = WorkerSpec(rank=rank, run_id=run_id, role=role, worker_dir=str(wdir),
                          coordination_dir=str(coord_dir), executable=str(executable),
                          horizon=settings.horizon, base_seed=settings.seed,
                          extra_env=settings.effective_extra_env(),
                          reward_contract=settings.reward, experiment=settings.experiment,
                          retain_failed_cap=settings.retain_failed_cap, startup_attempts=settings.startup_attempts,
                          request_timeout=settings.request_timeout, preserve_all=preserve_all,
                          port_block_base=settings.port_block_base, port_block_size=settings.port_block_size,
                          standby_preboot=settings.standby_preboot, standby_count=settings.standby_count,
                          standby_wait_timeout=settings.standby_wait_timeout)
        # M7g: the v2 stack refuses a spec without SSB64_RL_SPATIAL=1 (every standby generation boots with it too)
        factory: Any = (mo.M7gWorkerFactory(spec) if settings.observation_contract == mo.OBS_CONTRACT
                        else WorkerFactory(spec))
        if settings.eval_metrics:   # M7g Phase K: btt_eval_metrics_v1 recorder inside the worker (evaluation only)
            from m7g_eval_metrics import EvalMetricsWorkerFactory

            factory = EvalMetricsWorkerFactory(factory)
        factories.append(factory)
    return factories, coord_dir


def run_episodes(*, mode: str, episodes: int, out_dir: Path, run_id: str, settings: EvaluationSettings,
                 model: Any = None, vecnorm_path: Optional[Path] = None, n_workers: Optional[int] = None,
                 preserve_all: Optional[bool] = None) -> Dict[str, Any]:
    """Run `episodes` complete episodes in one mode; returns per-episode rows and aggregates.

    Collection order is deterministic: the first `episodes` completed
    episodes by vector step, then by rank. Episodes still running when the
    quota is met are aborted at close and never counted (reported as excess).
    preserve_all (M7d): None keeps the default (every deterministic episode is
    preserved, other modes preserve new-best / clear / anomaly episodes only);
    True preserves the canonical artifact of every episode of this set."""
    if mode not in MODES:
        raise ValueError(mode)
    if (mode == "random") != (model is None):
        raise ValueError("a model is required for deterministic/stochastic, forbidden for random")
    n = max(1, min(int(n_workers or settings.n_workers), int(episodes)))
    out_dir = Path(out_dir)
    check_path_budget(out_dir, suffix=70)
    out_dir.mkdir(parents=True, exist_ok=False)
    role = "random_baseline" if mode == "random" else "evaluation"
    keep_all = (mode == "deterministic") if preserve_all is None else bool(preserve_all)
    factories, coord_dir = _prepare_workers(out_dir, n, role, run_id, settings, preserve_all=keep_all)
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
        try:
            check_vecnormalize_identity(vecnorm, settings.observation_contract)
        except CheckpointError:
            venv.close()
            raise
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
        "reward_contract": settings.reward.to_json(),
        "experiment": settings.experiment,
        "wall_s": round(wall, 3),
        "vec_steps": vec_steps,
        "excess_episodes_not_counted": excess,
        "preserve_all": keep_all,
        "frozen_check": unchanged,
        "aggregate": aggregate(collected, seed=settings.seed),
        "episodes": [_row(e) | {"mode": mode, "order": e["order"]} for e in collected],
        "close": {k: v for k, v in close.items() if k != "ranks"},
        "workers_closed_cleanly": all(bool(e.get("closed_cleanly")) for e in close.get("ranks", {}).values()),
        "startup_failures": sum(len((r or {}).get("startup_failures", [])) for r in reports.values()),
        "coordination_state": RunCoordinator(coord_dir).read(),
        # M7c: lifecycle of the evaluation workers and their standby statistics
        "lifecycle": dict(settings.lifecycle(), timing_reset_modes=venv.timing.to_json().get("reset_modes"),
                          per_worker={rank: (r or {}).get("standby") for rank, r in reports.items()},
                          startup_modes={rank: (r or {}).get("startup_modes") for rank, r in reports.items()}),
    }
    if mode == "deterministic":
        digests = {e["native_action_digest"] for e in collected}
        result["deterministic_episodes_identical"] = len(digests) == 1
    if settings.observation_contract != POLICY_OBSERVATION_CONTRACT or settings.records_flags:
        # M7g: v2 and/or evaluation metrics only (earlier v1 records unchanged); M7j: v3 reward too
        result["policy_observation_contract"] = settings.observation_contract
        result["extra_env"] = dict(settings.effective_extra_env())
    if settings.eval_metrics:
        from m7g_eval_metrics import CONTRACT as EVAL_METRICS_CONTRACT

        result["eval_metrics_contract"] = EVAL_METRICS_CONTRACT
        result["eval_metrics_recorded"] = sum(1 for e in collected if e.get("eval_metrics") is not None)
    with open(out_dir / "evaluation.json", "w", encoding="utf-8", newline="\n") as fp:
        json.dump(result, fp, indent=2)
        fp.write("\n")
    return result


def evaluate_checkpoint(checkpoint_dir: os.PathLike | str, out_dir: os.PathLike | str, *, settings: EvaluationSettings,
                        deterministic_episodes: int = 2, stochastic_episodes: int = 20,
                        expected_contracts: Optional[Mapping[str, Any]] = None, label: Optional[str] = None,
                        preserve_all: Optional[bool] = None) -> Dict[str, Any]:
    """Full evaluation protocol for one checkpoint set (deterministic + stochastic sessions).

    preserve_all (M7d): passed to run_episodes for both modes (None = default preservation policy)."""
    from m7_trainer import M7PPO  # local: m7_trainer imports this module

    ckpt = Path(checkpoint_dir)
    meta = read_checkpoint_set(ckpt, expected_contracts=expected_contracts)
    if int(meta["contracts"]["horizon_native_ticks"]) != int(settings.horizon):
        raise CheckpointError(f"checkpoint horizon {meta['contracts']['horizon_native_ticks']} != evaluation horizon "
                              f"{settings.horizon}")
    # M7b: the diagnostic raw return is computed under the checkpoint's OWN reward contract (never the caller's),
    # and the checkpoint's experiment block travels into every evaluation artifact label.
    reward = checkpoint_reward_contract(meta)
    if settings.reward.contract != reward.contract and settings.reward != REWARD_V1:
        raise CheckpointError(f"evaluation reward {settings.reward.contract} differs from the checkpoint's "
                              f"{reward.contract}; a checkpoint is always evaluated under its own contract")
    settings = replace(settings, reward=reward, experiment=meta.get("experiment") or settings.experiment)
    # M7g: ... and under its own policy observation. Model, statistics and contract are cross-checked before any
    # directory is created or any worker spawned; v2 adds the native flag its observation needs.
    observation = checkpoint_observation_contract(meta)
    if settings.observation is not None and settings.observation != observation:
        raise CheckpointError(f"evaluation observation {settings.observation} differs from the checkpoint's "
                              f"{observation}; a checkpoint is always evaluated under its own observation contract")
    flags = dict(settings.extra_env)
    flags.update(dict(mo.SPATIAL_EXTRA_ENV) if observation == mo.OBS_CONTRACT else {})
    settings = replace(settings, observation=observation, extra_env=tuple(flags.items()))
    t0 = time.perf_counter()
    model = M7PPO.load(str(ckpt / MODEL_FILE), device="cpu")
    check_model_identity(model, observation)
    with open(ckpt / VECNORM_FILE, "rb") as fp:   # hash-verified above; the workers do not exist yet
        check_vecnormalize_identity(pickle.load(fp), observation)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=False)
    model_reward = getattr(model, "m7_reward_contract", None)
    if model_reward is not None and model_reward.get("contract") != reward.contract:
        raise CheckpointError(f"model.zip records reward contract {model_reward.get('contract')!r} but checkpoint.json "
                              f"records {reward.contract!r}")
    result: Dict[str, Any] = {
        "evaluation_schema": EVALUATION_SCHEMA,
        "label": label or ckpt.name,
        "checkpoint": portable_path(ckpt),
        "checkpoint_num_timesteps": meta.get("num_timesteps"),
        "checkpoint_n_updates": meta.get("n_updates"),
        "reward_contract": reward.to_json(),
        "experiment": meta.get("experiment"),
        "model_reward_contract": model_reward,
        "model_experiment": getattr(model, "m7_experiment", None),
        "lifecycle": settings.lifecycle(),
        "checkpoint_lifecycle": meta.get("lifecycle"),
        "horizon": settings.horizon,
        "observation_note": "raw native observations -> btt_policy_obs_v1 (15 float32, unchanged) -> "
                            "VecNormalize (frozen statistics of the checkpoint) -> policy input",
        "modes": {},
    }
    if observation == mo.OBS_CONTRACT:   # M7g: v2 only (v1 summaries unchanged)
        result["observation_note"] = ("raw native observations + btt_spatial_v1 -> btt_policy_obs_v2_spatial (Dict, "
                                      "525 values) -> VecNormalize (frozen per-key statistics of the checkpoint, "
                                      f"keys {list(mo.NORMALIZED_KEYS)}) -> MultiInputPolicy")
        result["policy_observation_contract"] = observation
        result["policy_network"] = meta.get("policy_network")
    if observation == mo.OBS_CONTRACT or settings.records_flags:
        result["extra_env"] = dict(settings.effective_extra_env())
    if settings.eval_metrics:
        result["policy_observation_contract"] = observation
        result["eval_metrics"] = True
    if deterministic_episodes > 0:
        result["modes"]["deterministic"] = run_episodes(
            mode="deterministic", episodes=deterministic_episodes, out_dir=out / "deterministic",
            run_id=f"eval:{result['label']}", settings=settings, model=model, vecnorm_path=ckpt / VECNORM_FILE,
            preserve_all=preserve_all)
    if stochastic_episodes > 0:
        result["modes"]["stochastic"] = run_episodes(
            mode="stochastic", episodes=stochastic_episodes, out_dir=out / "stochastic",
            run_id=f"eval:{result['label']}", settings=settings, model=model, vecnorm_path=ckpt / VECNORM_FILE,
            preserve_all=preserve_all)
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
              "policy": "uniform MultiDiscrete([9, 8]) from numpy.random.default_rng(seed)",
              "reward_contract": settings.reward.to_json(), "experiment": settings.experiment,
              "lifecycle": settings.lifecycle(),
              "modes": {"random": r}, "wall_s": r["wall_s"]}
    if settings.records_flags:   # M7g Phase K / M7j v3 (earlier random baselines unchanged)
        result["extra_env"] = dict(settings.effective_extra_env())
    if settings.eval_metrics:
        result["eval_metrics"] = True
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
