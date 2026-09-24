#!/usr/bin/env python3
"""M7a: parallel Stable-Baselines3 PPO training for BattleShip Mario Break the Targets.

    PPO (MlpPolicy, CPU) -> VecNormalize (observations only) -> M7SubprocVecEnv (spawn workers)
        -> per worker: Track 1 -> M4 recorder -> btt_reward_v1 -> M3/M2 -> one BattleShip process

This module is imported lazily by the CLIs (rl/train_m7.py, rl/eval_m7.py) so
that spawn workers, which re-import the CLI as __mp_main__, never import
PyTorch or Stable-Baselines3.

Frozen contracts used unchanged: Track 1 `btt_s9_b8_v1`, `btt_reward_v1`,
`btt_policy_obs_v1`, the M3 environment, the M4 artifact format, M1c
one-action-one-tick stepping and process restart as reset. M7 adds the
native-failure (fall) termination `btt_native_failure_v1` and the
Python-owned 3600-tick horizon.

Observation path: raw native M1b observation -> btt_policy_obs_v1 (15 float32
features, unchanged) -> VecNormalize (running mean/variance, clip 10; reward
normalisation OFF, no reward clipping or transformation) -> policy input.
The statistics are saved beside every model and loaded (frozen) for
evaluation.

M7g Phase K (explicit opt-in, M7Config.observation / contracts.observation):
btt_policy_obs_v2_spatial selects MultiInputPolicy, the v2 worker stack
(rl/m7g_obs.py: SpatialObsV2Wrapper above Track 1, SSB64_RL_SPATIAL=1),
VecNormalize over the continuous keys only (norm_obs_keys) and the v2 run
contracts; checkpoints carry the observation and network identity and are
never loaded across observation contracts. btt_policy_obs_v1 is the default
and keeps every M7a-M7f value.

Run layout (never overwritten; a resume is a new run directory):

    runs/<run_id>/
        run.json                    metadata: config, resolved PPO values, contracts, seeds, flags, revisions, lineage
        checkpoints/ckpt_<t>/       model.zip + vecnormalize.pkl + checkpoint.json + preservation_state.json
        final/  interrupted/        same checkpoint-set layout
        coordination/               shared preservation state + ledger (file lock)
        workers/wNN/                runtime/ (private cwd), episodes/ (M2 dirs), artifacts/, dispositions.jsonl
        evaluations/<label>/        evaluation sets (their own workers, artifacts, evaluation.json)
        metrics/                    rollouts.jsonl, episodes.jsonl
        training_summary.json
"""

from __future__ import annotations

import json
import math
import os
import platform
import shutil
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import gymnasium
import numpy as np
import stable_baselines3
import torch
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.vec_env import VecNormalize

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import experiment_config as ec  # noqa: E402
import m7g_obs as mo  # noqa: E402
import m7g_policy as mp  # noqa: E402
from battleship_env import DEFAULT_EXECUTABLE  # noqa: E402
from btt_learning import POLICY_OBSERVATION_CONTRACT, POLICY_OBSERVATION_SIZE, TRACK1_CONTRACT  # noqa: E402
from btt_rewards import REWARD_V1, RewardContract  # noqa: E402
from btt_parallel import (  # noqa: E402
    END_ABORTED,
    END_CLEAR,
    END_FALL,
    END_HORIZON,
    END_LIFECYCLE_FAILURE,
    M7_HORIZON,
    M7_MILESTONE,
    LatencyHistogram,
    RunCoordinator,
    StandbySettings,
    WorkerFactory,
    WorkerSpec,
    initial_coordination_state,
    m7_contracts,
)
from m7_evaluation import (  # noqa: E402
    CHECKPOINT_SCHEMA,
    META_FILE,
    MODEL_FILE,
    PRESERVATION_FILE,
    VECNORM_FILE,
    CheckpointError,
    EvaluationSettings,
    check_model_identity,
    check_vecnormalize_identity,
    evaluate_checkpoint,
    obs_rms_record,
    read_checkpoint_set,
)
from m7_runtime import (  # noqa: E402
    BATTLESHIP_IMAGE,
    PORT_BLOCK_BASE,
    PORT_BLOCK_SIZE,
    USER_CONFIG_NAME,
    check_path_budget,
    cpu_utilisation,
    file_fingerprint,
    install_kill_on_close_job,
    list_processes_named,
    pid_alive,
    portable_path,
    prepare_worker_runtime,
    replace_with_retry,
    repository_revisions,
    sha256_file,
    system_cpu_times,
    validate_port_blocks,
    wait_until_no_process,
)
from m7_vec_env import M7SubprocVecEnv, M7VecEnvError  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUNS_DIR = REPO_ROOT / "runs"
M6_FLAGS: Tuple[Tuple[str, str], ...] = (("SSB64_RL_NO_RENDER", "1"), ("SSB64_RAPHNET_DISABLE", "1"))
ROLLOUT_SIZE = 5120
POLICY = "MlpPolicy"
ACTIVATIONS = {"tanh": torch.nn.Tanh, "relu": torch.nn.ReLU}
EXPERIMENT_TOML = "experiment.toml"              # unmodified copy of the source profile (M7b)
EXPERIMENT_RESOLVED = "experiment_resolved.json"  # canonical resolved configuration (M7b)

try:
    from bench import ProcessMetrics  # rl/tools/bench.py
except Exception:  # noqa: BLE001
    ProcessMetrics = None  # type: ignore[assignment]


def log(message: str) -> None:
    print(message, flush=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path: Path, data: Any) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fp:
        json.dump(data, fp, indent=2, default=str)
        fp.write("\n")
    replace_with_retry(tmp, path)


def append_jsonl(path: Path, record: Mapping[str, Any]) -> None:
    with open(path, "a", encoding="utf-8", newline="\n") as fp:
        fp.write(json.dumps(record, separators=(",", ":"), default=str) + "\n")


def versions() -> Dict[str, Any]:
    return {"python": platform.python_version(), "platform": platform.platform(), "gymnasium": gymnasium.__version__,
            "numpy": np.__version__, "torch": torch.__version__, "stable_baselines3": stable_baselines3.__version__,
            "cpu_count": os.cpu_count()}


# -- PPO with optimizer timing ---------------------------------------------------------------------------


class M7PPO(PPO):
    """SB3 PPO, unchanged algorithm; train() is timed and its logged metrics are kept per update."""

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.m7_train_s: List[float] = []
        self.m7_train_metrics: List[Dict[str, float]] = []

    def train(self) -> None:
        t0 = time.perf_counter()
        super().train()
        self.m7_train_s.append(time.perf_counter() - t0)
        self.m7_train_metrics.append({k: float(v) for k, v in self.logger.name_to_value.items()
                                      if k.startswith("train/") and isinstance(v, (int, float, np.integer, np.floating))})

    def _excluded_save_params(self) -> List[str]:
        # m7_reward_contract / m7_experiment (M7b) are deliberately NOT excluded: they are saved in model.zip
        return super()._excluded_save_params() + ["m7_train_s", "m7_train_metrics"]


class ForwardTimer:
    """Times policy.__call__ (rollout inference only: PPO.train uses evaluate_actions, predict uses _predict)."""

    def __init__(self, policy: torch.nn.Module):
        self.calls = 0
        self.total_s = 0.0
        self._t0 = 0.0
        policy.register_forward_pre_hook(self._pre)
        policy.register_forward_hook(self._post)

    def _pre(self, *_args: Any) -> None:
        self._t0 = time.perf_counter()

    def _post(self, *_args: Any) -> None:
        self.total_s += time.perf_counter() - self._t0
        self.calls += 1


def policy_kwargs(config: "M7Config") -> Dict[str, Any]:
    """Explicit network architecture. M7a passed nothing and got SB3's defaults (pi/vf 64x64, Tanh,
    orthogonal init); the M7a profile resolves to exactly those values (proved by the parity test)."""
    layers = [int(v) for v in config.net_arch]
    return {"net_arch": {"pi": list(layers), "vf": list(layers)}, "activation_fn": ACTIVATIONS[config.activation]}


def resolved_ppo_params(model: PPO, policy: str = POLICY) -> Dict[str, Any]:
    def sched(v: Any) -> Any:
        return float(v(1.0)) if callable(v) else v

    opt = model.policy.optimizer
    return {
        "algorithm": "PPO",
        "policy": policy,
        "policy_class": type(model.policy).__name__,
        "learning_rate": sched(model.learning_rate),
        "n_steps": model.n_steps,
        "n_envs": model.n_envs,
        "rollout_size": model.n_steps * model.n_envs,
        "batch_size": model.batch_size,
        "n_epochs": model.n_epochs,
        "gamma": model.gamma,
        "gae_lambda": model.gae_lambda,
        "clip_range": sched(model.clip_range),
        "clip_range_vf": sched(model.clip_range_vf),
        "normalize_advantage": model.normalize_advantage,
        "ent_coef": model.ent_coef,
        "vf_coef": model.vf_coef,
        "max_grad_norm": model.max_grad_norm,
        "use_sde": model.use_sde,
        "sde_sample_freq": model.sde_sample_freq,
        "target_kl": model.target_kl,
        "stats_window_size": model._stats_window_size,
        "net_arch": str(model.policy.net_arch),
        "activation_fn": model.policy.activation_fn.__name__,
        "ortho_init": model.policy.ortho_init,
        "share_features_extractor": model.policy.share_features_extractor,
        "optimizer": type(opt).__name__,
        "optimizer_defaults": {k: (list(v) if isinstance(v, tuple) else v) for k, v in opt.defaults.items()
                               if k in ("lr", "eps", "betas", "weight_decay", "amsgrad")},
        "device": str(model.device),
        "seed": model.seed,
    }


# -- configuration and layout ---------------------------------------------------------------------------


@dataclass
class M7Config:
    run_id: str
    n_envs: int
    total_timesteps: int
    n_steps: Optional[int] = None           # default ROLLOUT_SIZE // n_envs
    runs_dir: Path = DEFAULT_RUNS_DIR
    executable: Path = DEFAULT_EXECUTABLE
    purpose: str = "training"
    batch_size: int = 512
    n_epochs: int = 10
    gamma: float = 0.999
    gae_lambda: float = 0.995
    learning_rate: float = 3e-4
    clip_range: float = 0.2
    ent_coef: float = 0.0
    vf_coef: float = 0.5
    max_grad_norm: float = 0.5
    base_seed: int = 0
    horizon: int = M7_HORIZON
    checkpoint_interval: int = 51200
    initial_checkpoint: bool = True
    eval_interval: int = 0
    eval_initial: bool = False
    eval_final: bool = False
    eval_deterministic_episodes: int = 2
    eval_stochastic_episodes: int = 20
    eval_workers: Optional[int] = None
    eval_seed: int = 12345
    periodic_episodes: int = 10
    retain_failed_cap: int = 20
    position_delta_threshold: float = 300.0
    startup_attempts: int = 3
    startup_timeout: float = 20.0
    ready_timeout: float = 60.0
    request_timeout: float = 10.0
    exit_timeout: float = 30.0
    step_timeout: float = 900.0
    torch_threads: int = 1
    device: str = "cpu"
    clip_obs: float = 10.0
    norm_obs: bool = True
    extra_env: Tuple[Tuple[str, str], ...] = M6_FLAGS
    resume_from: Optional[Path] = None
    # M7b: reward contract, network, ports, worker root, experiment provenance (all default to M7a behaviour)
    reward: RewardContract = REWARD_V1
    net_arch: Tuple[int, ...] = (64, 64)
    activation: str = "tanh"
    port_block_base: int = PORT_BLOCK_BASE
    port_block_size: int = PORT_BLOCK_SIZE
    worker_runtime_root: Optional[Path] = None
    allow_executable_change: bool = False
    experiment: Optional[Any] = field(default=None, repr=False, compare=False)  # experiment_config.Experiment
    # M7g Phase K: policy observation contract and the SB3 policy class it requires (defaults = v1, M7a-M7f)
    observation: str = POLICY_OBSERVATION_CONTRACT
    policy: str = POLICY
    # M7c standby lifecycle (rl/m7_standby.py); defaults = M7a/M7b behaviour
    standby_preboot: bool = False
    standby_count: int = 0
    standby_wait_timeout: float = 120.0
    allow_lifecycle_change: bool = False
    standby_fault: Optional[Dict[str, Any]] = None      # test hook (worker standby launches), never used by experiments
    standby_fault_rank: Optional[int] = None
    # test hooks (never used by the comparison or the pilot)
    fault: Optional[Dict[str, Any]] = None
    fault_rank: Optional[int] = None
    interrupt_at_vec_step: Optional[int] = None
    detect_native_failure: bool = True
    squat_first_attempt_rank: Optional[int] = None

    def __post_init__(self) -> None:
        if self.n_steps is None:
            self.n_steps = ROLLOUT_SIZE // max(1, int(self.n_envs))
        # Absolute paths only: every game process runs with its private runtime directory as cwd.
        self.runs_dir = Path(self.runs_dir).resolve()
        self.executable = Path(self.executable).resolve()
        if self.resume_from is not None:
            self.resume_from = Path(self.resume_from).resolve()
        if self.worker_runtime_root is not None:
            self.worker_runtime_root = Path(self.worker_runtime_root).resolve()
        self.net_arch = tuple(int(v) for v in self.net_arch)

    @property
    def rollout_size(self) -> int:
        return int(self.n_steps) * int(self.n_envs)

    def experiment_summary(self) -> Optional[Dict[str, Any]]:
        return self.experiment.summary() if self.experiment is not None else None

    @property
    def observation_v2(self) -> bool:
        return self.observation == mo.OBS_CONTRACT

    def compatibility_view(self) -> Dict[str, Any]:
        """The resume-compatibility view of this configuration (experiment_config.COMPAT_KEYS)."""
        return {
            "task.id": "ssb64_us_mario_btt_v1",
            "contracts.observation": self.observation,
            "contracts.action": TRACK1_CONTRACT,
            "contracts.reward_resolved": self.reward.to_json(),
            "contracts.artifact_schema": ec.ARTIFACT_SCHEMA,
            "contracts.protocol_version": ec.PROTOCOL_VERSION,
            "environment.horizon": int(self.horizon),
            "environment.process_count": int(self.n_envs),
            "environment.extra_env": dict(self.extra_env),
            "ppo.policy": self.policy,
            "ppo.net_arch": list(self.net_arch),
            "ppo.activation": self.activation,
            "ppo.learning_rate": float(self.learning_rate),
            "ppo.rollout_size": self.rollout_size,
            "ppo.n_steps": int(self.n_steps),
            "ppo.batch_size": int(self.batch_size),
            "ppo.n_epochs": int(self.n_epochs),
            "ppo.gamma": float(self.gamma),
            "ppo.gae_lambda": float(self.gae_lambda),
            "ppo.clip_range": float(self.clip_range),
            "ppo.ent_coef": float(self.ent_coef),
            "ppo.vf_coef": float(self.vf_coef),
            "ppo.max_grad_norm": float(self.max_grad_norm),
            "ppo.device": self.device,
            "ppo.vecnormalize.normalize_observations": bool(self.norm_obs),
            "ppo.vecnormalize.normalize_rewards": False,
            "ppo.vecnormalize.clip_obs": float(self.clip_obs),
            "environment.standby_preboot": bool(self.standby_preboot),
            "environment.standby_count": int(self.standby_count),
        }

    @property
    def standby(self) -> StandbySettings:
        return StandbySettings(preboot=self.standby_preboot, count=self.standby_count, wait_timeout=self.standby_wait_timeout)

    def lifecycle_json(self) -> Dict[str, Any]:
        s = self.standby.to_json()
        s["max_game_processes"] = int(self.n_envs) * (1 + int(self.standby_count))
        s["eval_max_game_processes"] = int(self.eval_workers or self.n_envs) * (1 + int(self.standby_count))
        return s

    def validate(self) -> None:
        if self.n_envs < 1 or self.n_steps < 1:
            raise ValueError("n_envs and n_steps must be >= 1")
        self.standby  # noqa: B018 - StandbySettings validates preboot/count/wait_timeout consistency
        if self.activation not in ACTIVATIONS:
            raise ValueError(f"activation {self.activation!r} not in {sorted(ACTIVATIONS)}")
        if not self.net_arch or any(v < 1 for v in self.net_arch):
            raise ValueError(f"net_arch {self.net_arch!r} must be non-empty positive widths")
        if not isinstance(self.reward, RewardContract):
            raise ValueError("reward must be a btt_rewards.RewardContract")
        # M7g Phase K: the observation contract fixes the policy class, its native flag and observation normalisation.
        if self.observation not in ec.OBSERVATION_POLICY:
            raise ValueError(f"observation {self.observation!r} not in {list(ec.OBSERVATION_POLICY)}")
        if self.policy != ec.OBSERVATION_POLICY[self.observation]:
            raise ValueError(f"observation {self.observation!r} requires policy "
                             f"{ec.OBSERVATION_POLICY[self.observation]!r}, not {self.policy!r}")
        missing = [f"{k}={v}" for k, v in ec.OBSERVATION_EXTRA_ENV[self.observation] if dict(self.extra_env).get(k) != v]
        if missing:
            raise ValueError(f"observation {self.observation!r} needs the native flags {missing} in extra_env")
        if self.observation_v2 and not self.norm_obs:
            raise ValueError(f"observation {self.observation!r} requires norm_obs (VecNormalize over {list(mo.NORMALIZED_KEYS)})")
        if self.observation_v2 and (self.net_arch != tuple(mp.NET_ARCH) or self.activation != mp.ACTIVATION):
            raise ValueError(f"observation {self.observation!r} is validated only with {mp.NETWORK_ID} "
                             f"(net_arch {list(mp.NET_ARCH)}, {mp.ACTIVATION}), not {list(self.net_arch)} {self.activation}")
        if self.experiment is not None:
            view, mine = self.experiment.compatibility_view(), self.compatibility_view()
            diffs = ec.compare_compatibility(view, mine)
            if diffs:
                raise ValueError(f"M7Config disagrees with its experiment profile: {diffs}")
        if self.rollout_size % self.batch_size != 0:
            raise ValueError(f"batch_size {self.batch_size} must divide the rollout size {self.rollout_size}")
        if self.total_timesteps < 1 or self.total_timesteps % self.rollout_size != 0:
            raise ValueError(f"total_timesteps {self.total_timesteps} must be a positive multiple of the rollout "
                             f"size {self.rollout_size} (exact transition accounting)")
        for name in ("checkpoint_interval", "eval_interval"):
            v = getattr(self, name)
            if v < 0 or (v and v % self.rollout_size != 0):
                raise ValueError(f"{name} must be 0 or a multiple of the rollout size {self.rollout_size}")
        if self.eval_interval and (not self.checkpoint_interval or self.eval_interval % self.checkpoint_interval):
            raise ValueError("eval_interval must be a multiple of checkpoint_interval (evaluations use saved sets)")
        if self.horizon < 1:
            raise ValueError("horizon must be >= 1")
        if self.device != "cpu":
            raise ValueError("M7a trains on the CPU only")

    def to_json(self) -> Dict[str, Any]:
        d = {k: v for k, v in asdict(self).items() if k != "experiment"}
        d["runs_dir"] = portable_path(self.runs_dir)
        d["executable"] = portable_path(self.executable)
        d["resume_from"] = portable_path(self.resume_from) if self.resume_from else None
        d["worker_runtime_root"] = portable_path(self.worker_runtime_root) if self.worker_runtime_root else None
        d["extra_env"] = dict(self.extra_env)
        d["rollout_size"] = self.rollout_size
        d["reward"] = self.reward.to_json()
        d["net_arch"] = list(self.net_arch)
        d["experiment"] = self.experiment_summary()
        d["lifecycle"] = self.lifecycle_json()
        return d


def config_from_experiment(exp: "ec.Experiment", *, run_id: Optional[str] = None, output_root: Optional[Path] = None,
                           resume_from: Optional[Path] = None, purpose: Optional[str] = None) -> M7Config:
    """Translate a validated experiment_config.Experiment into the trainer's M7Config (M7b).

    The TOML is authoritative for every behavioural value; run_id / output_root
    / resume_from are the permitted operational overrides (recorded in the
    experiment block). For a resume the schema's cumulative
    run.total_transitions becomes the additional transitions of this run."""
    overrides: Dict[str, Any] = {}
    if run_id is not None:
        overrides["run.name"] = run_id
    if output_root is not None:
        overrides["run.output_root"] = str(output_root)
    if resume_from is not None:
        overrides["run.mode"] = "resume"
        overrides["resume.source_checkpoint"] = str(resume_from)
    if overrides:
        exp = exp.with_overrides(overrides)
    v = exp.values
    total = int(v["run.total_transitions"])
    if exp.mode == "resume":
        assert exp.resume_source is not None
        meta = read_checkpoint_set(exp.resume_source)   # existence + hashes only; contracts are compared in M7Run
        _total, total = ec.resume_total_transitions(exp, int(meta["num_timesteps"]))
    return M7Config(
        run_id=exp.name, n_envs=exp.process_count, total_timesteps=total, n_steps=int(v["ppo.n_steps"]),
        runs_dir=exp.output_root, executable=exp.executable,
        purpose=purpose or {"train": "training", "pilot": "pilot", "resume": "resume"}[exp.mode],
        batch_size=int(v["ppo.batch_size"]), n_epochs=int(v["ppo.n_epochs"]), gamma=float(v["ppo.gamma"]),
        gae_lambda=float(v["ppo.gae_lambda"]), learning_rate=float(v["ppo.learning_rate"]),
        clip_range=float(v["ppo.clip_range"]), ent_coef=float(v["ppo.ent_coef"]), vf_coef=float(v["ppo.vf_coef"]),
        max_grad_norm=float(v["ppo.max_grad_norm"]), base_seed=int(v["run.base_seed"]),
        horizon=int(v["environment.horizon"]), checkpoint_interval=int(v["checkpoint.interval"]),
        initial_checkpoint=bool(v["checkpoint.initial"]), eval_interval=int(v["evaluation.interval"]),
        eval_initial=bool(v["evaluation.initial"]), eval_final=bool(v["evaluation.final"]),
        eval_deterministic_episodes=int(v["evaluation.deterministic_episodes"]),
        eval_stochastic_episodes=int(v["evaluation.stochastic_episodes"]),
        eval_workers=int(v["evaluation.workers"]) or None, eval_seed=int(v["evaluation.seed"]),
        periodic_episodes=int(v["artifacts.periodic_episodes"]), retain_failed_cap=int(v["artifacts.retain_failed_cap"]),
        position_delta_threshold=float(v["environment.position_delta_threshold"]),
        startup_attempts=int(v["environment.startup_attempts"]), startup_timeout=float(v["environment.startup_timeout_s"]),
        ready_timeout=float(v["environment.ready_timeout_s"]), request_timeout=float(v["environment.request_timeout_s"]),
        exit_timeout=float(v["environment.exit_timeout_s"]), step_timeout=float(v["environment.step_timeout_s"]),
        torch_threads=int(v["ppo.torch_threads"]), device=str(v["ppo.device"]),
        clip_obs=float(v["ppo.vecnormalize.clip_obs"]), norm_obs=bool(v["ppo.vecnormalize.normalize_observations"]),
        extra_env=exp.extra_env, resume_from=exp.resume_source, reward=exp.reward,
        net_arch=tuple(v["ppo.net_arch"]), activation=str(v["ppo.activation"]),
        port_block_base=int(v["environment.port_block_base"]), port_block_size=int(v["environment.port_block_size"]),
        worker_runtime_root=exp.worker_runtime_root, allow_executable_change=bool(v["resume.allow_executable_change"]),
        experiment=exp,
        standby_preboot=bool(v["environment.standby_preboot"]), standby_count=int(v["environment.standby_count"]),
        standby_wait_timeout=float(v["environment.standby_wait_timeout_s"]),
        allow_lifecycle_change=bool(v["resume.allow_lifecycle_change"]),
        observation=str(v["contracts.observation"]), policy=str(v["ppo.policy"]),
    )


# -- M7g Phase K: observation-dependent construction (v1 = the M7a-M7f objects, unchanged) ------------------------


def run_contracts(config: M7Config) -> Dict[str, Any]:
    """Every contract a checkpoint of this configuration depends on (compared on resume and evaluation)."""
    if config.observation_v2:
        return mo.m7g_contracts(config.horizon, config.reward)
    return m7_contracts(config.horizon, config.reward)


def worker_factory(config: M7Config, spec: WorkerSpec) -> Any:
    """The picklable worker factory of the configured observation (v2 = the M7 stack + SpatialObsV2Wrapper)."""
    return mo.M7gWorkerFactory(spec) if config.observation_v2 else WorkerFactory(spec)


def vecnormalize_keys(config: M7Config) -> Dict[str, Any]:
    """VecNormalize keyword for the configured observation: v2 normalises only its continuous keys (the binary keys
    are never normalised; SB3's default would normalise all five); v1 passes nothing (M7a-M7f call unchanged)."""
    return {"norm_obs_keys": list(mo.NORMALIZED_KEYS)} if config.observation_v2 else {}


def make_vecnormalize(config: M7Config, venv: Any) -> VecNormalize:
    """Observation-only VecNormalize, exactly as M7Run.run constructs it for a fresh run."""
    c = config
    return VecNormalize(venv, training=True, norm_obs=c.norm_obs, norm_reward=False, clip_obs=c.clip_obs,
                        gamma=c.gamma, **vecnormalize_keys(c))


def make_model(config: M7Config, vecnorm: VecNormalize) -> "M7PPO":
    """A fresh PPO model of this configuration (policy class from the observation contract; M7a-M7f arguments)."""
    c = config
    return M7PPO(c.policy, vecnorm, learning_rate=c.learning_rate, n_steps=c.n_steps, batch_size=c.batch_size,
                 n_epochs=c.n_epochs, gamma=c.gamma, gae_lambda=c.gae_lambda, clip_range=c.clip_range,
                 ent_coef=c.ent_coef, vf_coef=c.vf_coef, max_grad_norm=c.max_grad_norm, seed=c.base_seed,
                 device=c.device, verbose=0, policy_kwargs=policy_kwargs(c))


def annotate_model(config: M7Config, model: "M7PPO") -> None:
    """Identity stored inside model.zip: M7b reward contract + experiment provenance; M7g v2 models also carry their
    observation contract (a v1 model.zip gains nothing)."""
    model.m7_reward_contract = config.reward.to_json()
    model.m7_experiment = config.experiment_summary()
    if config.observation_v2:
        model.m7_policy_observation = config.observation


def policy_network_identity(config: M7Config, model: PPO) -> Optional[Dict[str, Any]]:
    """The measured network and observation identity of a v2 model (None for v1: no v1 record gains a key)."""
    if not config.observation_v2:
        return None
    return dict(mp.describe(model), observation=ec.policy_observation_identity(config.observation))


@dataclass(frozen=True)
class M7Layout:
    root: Path
    workers_root: Optional[Path] = None   # M7b environment.worker_runtime_root; default <root>/workers

    @property
    def run_json(self) -> Path:
        return self.root / "run.json"

    @property
    def experiment_toml(self) -> Path:
        return self.root / EXPERIMENT_TOML

    @property
    def experiment_resolved(self) -> Path:
        return self.root / EXPERIMENT_RESOLVED

    @property
    def checkpoints(self) -> Path:
        return self.root / "checkpoints"

    @property
    def final(self) -> Path:
        return self.root / "final"

    @property
    def interrupted(self) -> Path:
        return self.root / "interrupted"

    @property
    def coordination(self) -> Path:
        return self.root / "coordination"

    @property
    def workers(self) -> Path:
        return self.workers_root if self.workers_root is not None else self.root / "workers"

    @property
    def evaluations(self) -> Path:
        return self.root / "evaluations"

    @property
    def metrics(self) -> Path:
        return self.root / "metrics"

    @property
    def summary(self) -> Path:
        return self.root / "training_summary.json"

    def checkpoint(self, timesteps: int) -> Path:
        return self.checkpoints / f"ckpt_{int(timesteps):09d}"

    def create(self) -> None:
        if self.root.exists():
            raise FileExistsError(f"run directory already exists (never overwritten): {self.root}")
        if self.workers_root is not None and self.workers_root.exists():
            raise FileExistsError(f"worker directory already exists (never overwritten): {self.workers_root}")
        for d in (self.root, self.checkpoints, self.workers, self.evaluations, self.metrics):
            d.mkdir(parents=True, exist_ok=False)


def save_checkpoint_set(directory: Path, model: PPO, vecnorm: VecNormalize, *, run_meta: Mapping[str, Any],
                        coordinator: RunCoordinator, label: str, rollouts: int) -> Dict[str, Any]:
    """Write model + matching VecNormalize statistics + metadata + preservation snapshot. Refuses to overwrite."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    model.save(str(directory / MODEL_FILE))
    vecnorm.save(str(directory / VECNORM_FILE))
    write_json(directory / PRESERVATION_FILE, coordinator.read())
    meta = {
        "checkpoint_schema": CHECKPOINT_SCHEMA,
        "milestone": M7_MILESTONE,
        "label": label,
        "created_utc": utc_now(),
        "num_timesteps": int(model.num_timesteps),
        "n_updates": int(model._n_updates),
        "rollouts_completed": int(rollouts),
        "policy_note": "parameters after n_updates optimizer passes (n_epochs per rollout)",
        "vecnormalize": {"norm_obs": vecnorm.norm_obs, "norm_reward": vecnorm.norm_reward, "clip_obs": vecnorm.clip_obs,
                         "clip_reward": vecnorm.clip_reward, "epsilon": vecnorm.epsilon,
                         **obs_rms_record(vecnorm),   # v1: obs_rms_count only (as before); v2: + per-key counts / keys
                         "load_rule": "load with training=False and norm_reward=False for evaluation"},
        **{k: run_meta[k] for k in ("run_id", "purpose", "lineage", "contracts", "horizon", "n_envs", "ppo", "seeds",
                                     "executable", "revisions", "m6_flags", "versions", "torch_threads")},
        # M7c: the process lifecycle this set was trained under (compared on resume; see experiment_config)
        "lifecycle": run_meta.get("lifecycle"),
        # M7b: reward identity and experiment provenance travel with every set (None for legacy-shaped run_meta)
        "reward_contract": (run_meta.get("contracts") or {}).get("reward_constants"),
        "experiment": run_meta.get("experiment"),
        "files": {name: sha256_file(directory / name) for name in (MODEL_FILE, VECNORM_FILE, PRESERVATION_FILE)},
    }
    if run_meta.get("policy_network") is not None:   # M7g: v2 observation / network identity (absent for v1)
        meta["policy_network"] = run_meta["policy_network"]
    write_json(directory / META_FILE, meta)
    return {"label": label, "path": portable_path(directory), "num_timesteps": meta["num_timesteps"],
            "n_updates": meta["n_updates"]}


# -- one training run ---------------------------------------------------------------------------------------


class M7Callback(BaseCallback):
    def __init__(self, run: "M7Run"):
        super().__init__(0)
        self.run = run

    def _on_training_start(self) -> None:
        self.run.on_training_start()

    def _on_rollout_start(self) -> None:
        self.run.on_rollout_start()

    def _on_step(self) -> bool:
        self.run.on_step(self.locals)
        return True

    def _on_rollout_end(self) -> None:
        self.run.on_rollout_end()

    def _on_training_end(self) -> None:
        self.run.on_training_end()


def _stats(values: Sequence[float], digits: int = 3) -> Dict[str, Any]:
    if not values:
        return {"n": 0}
    s = sorted(values)
    q = lambda p: s[min(len(s) - 1, max(0, int(math.ceil(p * len(s))) - 1))]  # noqa: E731
    return {"n": len(s), "mean": round(statistics.fmean(s), digits), "median": round(statistics.median(s), digits),
            "p90": round(q(0.9), digits), "min": round(s[0], digits), "max": round(s[-1], digits)}


class M7Run:
    """State of one training run: construction, callbacks, checkpoints, evaluation, cleanup, summary."""

    def __init__(self, config: M7Config):
        config.validate()
        self.config = config
        workers_root = (Path(config.worker_runtime_root) / config.run_id) if config.worker_runtime_root else None
        self.layout = M7Layout(Path(config.runs_dir) / config.run_id, workers_root)
        self.model: Optional[M7PPO] = None
        self.vecnorm: Optional[VecNormalize] = None
        self.venv: Optional[M7SubprocVecEnv] = None
        self.coordinator: Optional[RunCoordinator] = None
        self.forward: Optional[ForwardTimer] = None
        self.episodes: List[Dict[str, Any]] = []
        self.rollouts: List[Dict[str, Any]] = []
        self.checkpoints: List[Dict[str, Any]] = []
        self.evaluations: List[Dict[str, Any]] = []
        self.walls: Dict[str, float] = {"checkpoint_s": 0.0, "eval_s": 0.0, "context_s": 0.0}
        self.optimize_walls: List[float] = []
        self._t_learn = 0.0
        self._t_rollout = 0.0
        self._last_rollout_end: Optional[float] = None
        self._cpu_rollout: Optional[Dict[str, float]] = None
        self._cpu_opt: Optional[Dict[str, float]] = None
        self._timing_snapshot: Optional[Dict[str, Any]] = None
        self._fwd_snapshot = (0, 0.0)
        self._label = "initial"
        self.cpu_collect: List[Tuple[float, float]] = []
        self.cpu_optimize: List[Tuple[float, float]] = []
        self.run_meta: Dict[str, Any] = {}
        self.start_timesteps = 0

    # -- construction ----------------------------------------------------------------------------------

    def _specs(self) -> List[WorkerSpec]:
        c = self.config
        specs = []
        for rank in range(c.n_envs):
            wdir = (self.layout.workers / f"w{rank:02d}").resolve()
            specs.append(WorkerSpec(
                rank=rank, run_id=c.run_id, role="training", worker_dir=str(wdir),
                coordination_dir=str(self.layout.coordination.resolve()), executable=str(c.executable),
                horizon=c.horizon, base_seed=c.base_seed, extra_env=tuple(c.extra_env),
                reward_contract=c.reward, experiment=c.experiment_summary(),
                position_delta_threshold=c.position_delta_threshold, retain_failed_cap=c.retain_failed_cap,
                startup_attempts=c.startup_attempts, startup_timeout=c.startup_timeout, ready_timeout=c.ready_timeout,
                request_timeout=c.request_timeout, exit_timeout=c.exit_timeout,
                port_block_base=c.port_block_base, port_block_size=c.port_block_size,
                detect_native_failure=c.detect_native_failure,
                fault=c.fault if c.fault_rank == rank else None,
                squat_first_attempt=("post_launch" if c.squat_first_attempt_rank == rank else None),
                standby_preboot=c.standby_preboot, standby_count=c.standby_count,
                standby_wait_timeout=c.standby_wait_timeout,
                standby_fault=c.standby_fault if c.standby_fault_rank == rank else None))
        return specs

    def _source_checkpoint(self) -> Optional[Dict[str, Any]]:
        """Verify the resume source and its compatibility BEFORE anything is created (M7a checks + M7b view)."""
        c = self.config
        if c.resume_from is None:
            return None
        meta = read_checkpoint_set(c.resume_from, expected_contracts=run_contracts(c))
        ppo = meta.get("ppo") or {}
        wanted = {"n_envs": c.n_envs, "n_steps": c.n_steps, "batch_size": c.batch_size, "n_epochs": c.n_epochs,
                  "gamma": c.gamma, "gae_lambda": c.gae_lambda, "learning_rate": c.learning_rate,
                  "clip_range": c.clip_range, "ent_coef": c.ent_coef, "vf_coef": c.vf_coef,
                  "max_grad_norm": c.max_grad_norm}
        diffs = {k: {"checkpoint": ppo.get(k), "requested": v} for k, v in wanted.items() if ppo.get(k) != v}
        if diffs:
            raise CheckpointError(f"resume requires the checkpoint's PPO settings and process count: {diffs}")
        # M7b: the full compatibility view (task, contracts, reward id + values, architecture, VecNormalize,
        # flags, device) and the executable identity.
        compat = ec.compare_compatibility(ec.checkpoint_compatibility_view(meta), c.compatibility_view())
        if compat and ec.lifecycle_only_diffs(compat) and c.allow_lifecycle_change:
            # M7c: a different standby lifecycle mode changes no trajectory, reward or artifact by contract, but a
            # resume across modes is never silent: it needs resume.allow_lifecycle_change and is recorded.
            meta["_lifecycle_change"] = {"diffs": compat, "accepted_by": "resume.allow_lifecycle_change"}
            compat = {}
        if compat:
            hint = (" (only the standby lifecycle differs: set resume.allow_lifecycle_change = true to accept it)"
                    if ec.lifecycle_only_diffs(compat) else "")
            raise CheckpointError("resume rejected: compatibility-affecting fields differ from the checkpoint: "
                                  + json.dumps(compat, sort_keys=True, default=str)[:3000] + hint)
        stored_exe = (meta.get("executable") or {}).get("sha256")
        current_exe = sha256_file(Path(c.executable))
        if stored_exe != current_exe:
            if not c.allow_executable_change:
                raise CheckpointError(f"resume rejected: executable sha256 {current_exe[:16]}... differs from the "
                                      f"checkpoint's {str(stored_exe)[:16]}... (set resume.allow_executable_change = true "
                                      "to accept a separately validated build)")
            meta["_executable_change"] = {"checkpoint_sha256": stored_exe, "current_sha256": current_exe,
                                          "accepted_by": "resume.allow_executable_change"}
        return meta

    # -- callbacks ----------------------------------------------------------------------------------------

    def on_training_start(self) -> None:
        self.walls["initial_reset_s"] = time.perf_counter() - self._t_learn
        self._broadcast()

    def on_rollout_start(self) -> None:
        now = time.perf_counter()
        if self._last_rollout_end is not None:
            self.optimize_walls.append(now - self._last_rollout_end)
            if self.rollouts:
                self.rollouts[-1]["optimize_wall_s"] = round(now - self._last_rollout_end, 4)
                self.rollouts[-1]["train_s"] = round(self.model.m7_train_s[-1], 4) if self.model.m7_train_s else None
                self.rollouts[-1]["train_metrics"] = self.model.m7_train_metrics[-1] if self.model.m7_train_metrics else None
                self.rollouts[-1]["cpu_util_optimize"] = cpu_utilisation(self._cpu_opt, system_cpu_times())
                append_jsonl(self.layout.metrics / "rollouts.jsonl", self.rollouts[-1])
        t = int(self.model.num_timesteps)
        self._boundary(t)
        self._broadcast()
        self._timing_snapshot = self.venv.timing.to_json()
        self._fwd_snapshot = (self.forward.calls, self.forward.total_s)
        self._cpu_rollout = system_cpu_times()
        self._t_rollout = time.perf_counter()

    def on_step(self, local_vars: Mapping[str, Any]) -> None:
        infos = local_vars.get("infos") or ()
        t = int(self.model.num_timesteps)
        for info in infos:
            summary = info.get("m7_episode")
            if summary is not None:
                row = dict(summary, sb3_num_timesteps_seen=t)
                self.episodes.append(row)
                append_jsonl(self.layout.metrics / "episodes.jsonl", row)

    def on_rollout_end(self) -> None:
        now = time.perf_counter()
        collect = now - self._t_rollout
        cpu = cpu_utilisation(self._cpu_rollout, system_cpu_times())
        self._cpu_opt = system_cpu_times()
        timing = self.venv.timing.to_json()
        prev = self._timing_snapshot or {}
        calls, total = self.forward.calls - self._fwd_snapshot[0], self.forward.total_s - self._fwd_snapshot[1]
        finished = [e for e in self.episodes if e.get("rollout_index") is None]
        for e in finished:
            e["rollout_index"] = len(self.rollouts)
        record = {
            "rollout": len(self.rollouts) + 1,
            "num_timesteps": int(self.model.num_timesteps),
            "collect_s": round(collect, 4),
            "vec_step_wall_s": round(timing["wall_s"] - prev.get("wall_s", 0.0), 4),
            "reset_vec_steps": timing["reset_vec_steps"] - prev.get("reset_vec_steps", 0),
            "reset_vec_steps_wall_s": round(timing["reset_vec_steps_wall_s"] - prev.get("reset_vec_steps_wall_s", 0.0), 4),
            "policy_forward_calls": calls,
            "policy_forward_s": round(total, 4),
            "cpu_util_collect": cpu,
            "episodes_finished": len(finished),
            "end_reasons": {r: sum(1 for e in finished if e["end_reason"] == r) for r in
                            (END_CLEAR, END_FALL, END_HORIZON, END_LIFECYCLE_FAILURE)},
            "targets_mean": round(statistics.fmean([e["targets_broken"] for e in finished]), 4) if finished else None,
            "targets_max": max((e["targets_broken"] for e in finished), default=None),
            "return_mean": round(statistics.fmean([e["return"] for e in finished]), 4) if finished else None,
        }
        self.rollouts.append(record)
        self._last_rollout_end = now
        if self.config.purpose != "test":
            log(f"[m7] {self.config.run_id} rollout {record['rollout']}: t={record['num_timesteps']} "
                f"collect {collect:.2f}s ({self.config.rollout_size / collect:.0f} tr/s) episodes {len(finished)} "
                f"targets mean {record['targets_mean']} max {record['targets_max']} ends {record['end_reasons']}")

    def on_training_end(self) -> None:
        if self._last_rollout_end is not None:
            now = time.perf_counter()
            self.optimize_walls.append(now - self._last_rollout_end)
            if self.rollouts:
                self.rollouts[-1]["optimize_wall_s"] = round(now - self._last_rollout_end, 4)
                self.rollouts[-1]["train_s"] = round(self.model.m7_train_s[-1], 4) if self.model.m7_train_s else None
                self.rollouts[-1]["train_metrics"] = self.model.m7_train_metrics[-1] if self.model.m7_train_metrics else None
                self.rollouts[-1]["cpu_util_optimize"] = cpu_utilisation(self._cpu_opt, system_cpu_times())
                append_jsonl(self.layout.metrics / "rollouts.jsonl", self.rollouts[-1])
            self._last_rollout_end = None

    def _broadcast(self) -> None:
        t0 = time.perf_counter()
        self.venv.env_method("set_training_context", int(self.model.num_timesteps), self._label)
        self.walls["context_s"] += time.perf_counter() - t0

    def _boundary(self, t: int) -> None:
        """Checkpoint / evaluation at a rollout boundary (policy after t/rollout updates)."""
        c = self.config
        if t <= self.start_timesteps:
            return
        t_boundary = time.perf_counter()
        try:
            self._boundary_work(t)
        finally:
            # checkpoint + evaluation time spent inside learn(); excluded from end-to-end throughput
            self.walls["inside_overhead_s"] = self.walls.get("inside_overhead_s", 0.0) + time.perf_counter() - t_boundary

    def _boundary_work(self, t: int) -> None:
        c = self.config
        if c.checkpoint_interval and t % c.checkpoint_interval == 0:
            t0 = time.perf_counter()
            saved = save_checkpoint_set(self.layout.checkpoint(t), self.model, self.vecnorm, run_meta=self.run_meta,
                                        coordinator=self.coordinator, label=f"ckpt_{t:09d}", rollouts=len(self.rollouts))
            self.checkpoints.append(saved)
            self._label = saved["label"]
            self.walls["checkpoint_s"] += time.perf_counter() - t0
            if c.eval_interval and t % c.eval_interval == 0:
                self._evaluate(self.layout.checkpoint(t), f"t{t:09d}")

    def _evaluate(self, checkpoint_dir: Path, label: str) -> Dict[str, Any]:
        c = self.config
        t0 = time.perf_counter()
        settings = EvaluationSettings(executable=str(c.executable), horizon=c.horizon,
                                      n_workers=c.eval_workers or c.n_envs, seed=c.eval_seed,
                                      extra_env=tuple(c.extra_env), startup_attempts=c.startup_attempts,
                                      request_timeout=c.request_timeout, step_timeout=c.step_timeout,
                                      retain_failed_cap=c.retain_failed_cap, reward=c.reward,
                                      experiment=c.experiment_summary(),
                                      port_block_base=c.port_block_base, port_block_size=c.port_block_size,
                                      standby_preboot=c.standby_preboot, standby_count=c.standby_count,
                                      standby_wait_timeout=c.standby_wait_timeout, observation=c.observation)
        result = evaluate_checkpoint(checkpoint_dir, self.layout.evaluations / label, settings=settings,
                                     deterministic_episodes=c.eval_deterministic_episodes,
                                     stochastic_episodes=c.eval_stochastic_episodes,
                                     expected_contracts=run_contracts(c), label=label)
        dt = time.perf_counter() - t0
        self.walls["eval_s"] += dt
        entry = {"label": label, "checkpoint": portable_path(checkpoint_dir), "wall_s": round(dt, 3),
                 "num_timesteps": result.get("checkpoint_num_timesteps"),
                 "modes": {m: {"aggregate": r["aggregate"], "frozen_check": r.get("frozen_check"),
                               "deterministic_episodes_identical": r.get("deterministic_episodes_identical"),
                               "startup_failures": r.get("startup_failures"),
                               "workers_closed_cleanly": r.get("workers_closed_cleanly")}
                           for m, r in result["modes"].items()}}
        self.evaluations.append(entry)
        agg = {m: v["aggregate"] for m, v in entry["modes"].items()}
        log(f"[m7] evaluation {label}: " + "; ".join(
            f"{m} targets mean {a.get('targets_mean')} max {a.get('targets_max')} clears {a.get('clears')} "
            f"falls {a.get('falls')} horizon {a.get('horizon_truncations')}" for m, a in agg.items()) + f" ({dt:.1f}s)")
        return entry

    # -- the run ---------------------------------------------------------------------------------------------

    def run(self) -> Dict[str, Any]:
        c = self.config
        t_run = time.perf_counter()
        created = utc_now()
        source = self._source_checkpoint()
        check_path_budget(self.layout.root)
        self.layout.create()
        job = install_kill_on_close_job()
        torch.set_num_threads(c.torch_threads)
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            pass
        preexisting = list_processes_named(BATTLESHIP_IMAGE)
        if preexisting:
            raise RuntimeError(f"{BATTLESHIP_IMAGE} already running (pids {preexisting}); M7 runs need a quiet machine")
        user_cfg_path = Path(c.executable).resolve().parent / USER_CONFIG_NAME
        user_cfg_before = file_fingerprint(user_cfg_path)
        port_blocks = validate_port_blocks(range(c.n_envs), c.port_block_base, c.port_block_size)
        specs = self._specs()
        lineage: List[Dict[str, Any]] = []
        if source is not None:
            lineage = list(source.get("lineage") or []) + [{
                "run_id": source.get("run_id"), "checkpoint": portable_path(c.resume_from),
                "checkpoint_label": source.get("label"), "num_timesteps": source.get("num_timesteps"),
                "n_updates": source.get("n_updates"), "files": source.get("files"),
                "reward_contract": (source.get("contracts") or {}).get("reward_contract"),
                "experiment": source.get("experiment"),
                "executable_change": source.get("_executable_change"),
                "lifecycle_change": source.get("_lifecycle_change"),
                "lifecycle_at_checkpoint": source.get("lifecycle"),
                "versions_at_checkpoint": source.get("versions")}]
        # M7b provenance: the source profile copy, the resolved configuration and the fingerprints.
        experiment_meta = None
        if c.experiment is not None:
            with open(self.layout.experiment_toml, "w", encoding="utf-8", newline="\n") as fp:
                fp.write(c.experiment.toml_text)
            write_json(self.layout.experiment_resolved, c.experiment.resolved_json())
            experiment_meta = dict(c.experiment.summary(), compatibility_view=c.experiment.compatibility_view(),
                                   files={EXPERIMENT_TOML: sha256_file(self.layout.experiment_toml),
                                          EXPERIMENT_RESOLVED: sha256_file(self.layout.experiment_resolved)})
            if experiment_meta["files"][EXPERIMENT_TOML] != c.experiment.source.sha256:
                raise RuntimeError("the saved experiment.toml does not reproduce the source fingerprint")
        self.run_meta = {
            "milestone": M7_MILESTONE,
            "run_id": c.run_id,
            "purpose": c.purpose,
            "created_utc": created,
            "lineage": lineage,
            "contracts": run_contracts(c),
            "reward_contract": c.reward.to_json(),
            "experiment": experiment_meta,
            "compatibility_view": c.compatibility_view(),
            "horizon": c.horizon,
            "n_envs": c.n_envs,
            "seeds": {"base_seed": c.base_seed, "sb3_seed": c.base_seed,
                      "worker_seeds": [s.worker_seed for s in specs],
                      "vec_env_reset_seeds": [c.base_seed + r for r in range(c.n_envs)],
                      "eval_seed": c.eval_seed, "scope": "Python / NumPy / PyTorch / SB3 only; never reaches the game"},
            "executable": {"path": portable_path(c.executable), "sha256": sha256_file(Path(c.executable))},
            "revisions": repository_revisions(),
            "m6_flags": dict(c.extra_env),
            "versions": versions(),
            "torch_threads": {"requested": c.torch_threads, "get_num_threads": torch.get_num_threads(),
                              "workers": "no torch import in workers"},
            "port_blocks": port_blocks,
            "job_object": job.describe(),
            "lifecycle": c.lifecycle_json(),
            "config": c.to_json(),
        }
        # Coordination state (continued from the source checkpoint on resume).
        if source is not None:
            with open(Path(c.resume_from) / PRESERVATION_FILE, encoding="utf-8") as fp:
                state = json.load(fp)
            state["run_id"] = c.run_id
            state["lineage"] = list(state.get("lineage") or []) + [{"run_id": source.get("run_id"),
                                                                    "checkpoint": portable_path(c.resume_from)}]
        else:
            state = initial_coordination_state(c.run_id, "training", c.periodic_episodes)
        self.coordinator = RunCoordinator.create(self.layout.coordination, state)
        runtime_manifests = {}
        for spec in specs:
            runtime_manifests[spec.rank] = prepare_worker_runtime(spec.paths()["runtime"], Path(c.executable))
        self.run_meta["worker_runtime"] = runtime_manifests
        status, error, interrupted = "completed", None, False
        t_spawn = time.perf_counter()
        learn_s = None
        try:
            self.venv = M7SubprocVecEnv([worker_factory(c, s) for s in specs], step_timeout=c.step_timeout)
            self.venv.interrupt_at_step = c.interrupt_at_vec_step
            self.walls["spawn_s"] = time.perf_counter() - t_spawn
            if source is not None:
                self.vecnorm = VecNormalize.load(str(Path(c.resume_from) / VECNORM_FILE), self.venv)
                self.vecnorm.training = True
                self.vecnorm.norm_reward = False
                if bool(self.vecnorm.norm_obs) != bool(c.norm_obs) or float(self.vecnorm.clip_obs) != float(c.clip_obs):
                    raise CheckpointError(f"resume rejected: the saved VecNormalize (norm_obs {self.vecnorm.norm_obs}, "
                                          f"clip_obs {self.vecnorm.clip_obs}) differs from the configuration "
                                          f"(norm_obs {c.norm_obs}, clip_obs {c.clip_obs})")
                check_vecnormalize_identity(self.vecnorm, c.observation)   # M7g: statistics of this observation
                self.model = M7PPO.load(str(Path(c.resume_from) / MODEL_FILE), env=self.vecnorm, device=c.device)
                check_model_identity(self.model, c.observation)            # M7g: never across observations
                self.model.set_random_seed(c.base_seed)
                self.start_timesteps = int(self.model.num_timesteps)
            else:
                # the constructor literal is pinned by the M7d / M7e source guards; make_vecnormalize() is the same call
                self.vecnorm = VecNormalize(self.venv, training=True, norm_obs=c.norm_obs, norm_reward=False,
                                            clip_obs=c.clip_obs, gamma=c.gamma, **vecnormalize_keys(c))
                self.model = make_model(c, self.vecnorm)
            annotate_model(c, self.model)
            self.forward = ForwardTimer(self.model.policy)
            self.run_meta["ppo"] = resolved_ppo_params(self.model, c.policy)
            if c.observation_v2:
                self.run_meta["policy_network"] = policy_network_identity(c, self.model)
            write_json(self.layout.run_json, self.run_meta)
            if source is None and c.initial_checkpoint:
                t0 = time.perf_counter()
                self.checkpoints.append(save_checkpoint_set(self.layout.checkpoint(0), self.model, self.vecnorm,
                                                            run_meta=self.run_meta, coordinator=self.coordinator,
                                                            label="ckpt_000000000", rollouts=0))
                self.walls["checkpoint_s"] += time.perf_counter() - t0
                if c.eval_initial:
                    self._evaluate(self.layout.checkpoint(0), "t000000000")
            self._label = self.checkpoints[-1]["label"] if self.checkpoints else (
                source.get("label") if source else "initial")
            log(f"[m7] {c.run_id}: PPO n_envs={c.n_envs} n_steps={c.n_steps} rollout={c.rollout_size} "
                f"total={c.total_timesteps} start_t={self.start_timesteps} horizon={c.horizon} seed={c.base_seed}")
            self._t_learn = time.perf_counter()
            try:
                self.model.learn(total_timesteps=c.total_timesteps, callback=M7Callback(self),
                                 reset_num_timesteps=(source is None), progress_bar=False)
            except KeyboardInterrupt:
                interrupted, status = True, "interrupted"
                log("[m7] interrupted: draining workers, saving interrupted/, closing")
                self.venv.drain_pending()
                try:
                    self.venv.env_method("request_manual_preservation", "training interrupted (KeyboardInterrupt)")
                except M7VecEnvError as exc:
                    log(f"[m7] could not request manual preservation: {exc}")
            learn_s = time.perf_counter() - self._t_learn
        except BaseException as exc:  # noqa: BLE001 - recorded, cleanup below, then re-raised
            status, error = "failed", exc
            if isinstance(exc, KeyboardInterrupt):
                status, interrupted, error = "interrupted", True, None
        finally:
            t_close = time.perf_counter()
            if self.vecnorm is not None:
                self.vecnorm.close()
            elif self.venv is not None:
                self.venv.close()
            self.walls["close_s"] = time.perf_counter() - t_close
        # Final / interrupted checkpoint set (the statistics are in memory; the workers are closed).
        final_set = None
        if self.model is not None and self.vecnorm is not None:
            target = self.layout.interrupted if interrupted else (self.layout.final if error is None else None)
            if target is not None:
                t0 = time.perf_counter()
                final_set = save_checkpoint_set(target, self.model, self.vecnorm, run_meta=self.run_meta,
                                                coordinator=self.coordinator, label=target.name,
                                                rollouts=len(self.rollouts))
                self.walls["checkpoint_s"] += time.perf_counter() - t0
        if error is None and not interrupted and c.eval_final and final_set is not None:
            try:
                self._evaluate(self.layout.final, f"t{int(self.model.num_timesteps):09d}_final")
            except Exception as exc:  # noqa: BLE001 - recorded in the summary, re-raised after it is written
                status, error = "evaluation_failed", exc
        survivors = wait_until_no_process(BATTLESHIP_IMAGE, timeout=20.0)
        job_pids = [p for p in job.pids() if p != os.getpid() and pid_alive(p)] if job.active else []
        user_cfg_after = file_fingerprint(user_cfg_path)
        summary = self._summary(status=status, error=error, learn_s=learn_s, run_s=time.perf_counter() - t_run,
                                final_set=final_set, survivors=survivors, job_pids=job_pids,
                                user_cfg=(user_cfg_before, user_cfg_after), created=created)
        write_json(self.layout.summary, summary)
        log(f"[m7] {c.run_id}: {status}; e2e {summary['throughput'].get('end_to_end_transitions_per_s')} tr/s; "
            f"episodes {summary['episodes']['finished']}; leaks {len(survivors)}; summary {portable_path(self.layout.summary)}")
        if error is not None:
            raise error
        return summary

    # -- summary ------------------------------------------------------------------------------------------------

    def _summary(self, *, status: str, error: Optional[BaseException], learn_s: Optional[float], run_s: float,
                 final_set: Optional[Dict[str, Any]], survivors: List[int], job_pids: List[int],
                 user_cfg: Tuple[Dict[str, Any], Dict[str, Any]], created: str) -> Dict[str, Any]:
        c = self.config
        model = self.model
        venv = self.venv
        reports = venv.worker_reports() if venv is not None else {}
        timing = venv.timing.to_json() if venv is not None else {}
        close = dict(venv.close_report or {}) if venv is not None else {}
        close.pop("ranks", None)
        rank_close = {r: {k: v for k, v in e.items() if k != "worker_report"}
                      for r, e in ((venv.close_report or {}).get("ranks", {}) if venv else {}).items()}
        finished = [e for e in self.episodes if e["end_reason"] != END_ABORTED]
        transitions = (int(model.num_timesteps) - self.start_timesteps) if model is not None else 0
        collect_s = sum(r["collect_s"] for r in self.rollouts)
        train_s = sum(model.m7_train_s) if model is not None else 0.0
        optimize_wall_s = sum(self.optimize_walls)
        native_hists = [r.get("native_step_hist") for r in reports.values() if r]
        service_hists = [r.get("service_hist") for r in reports.values() if r]
        reset_times = [t for r in reports.values() if r for t in r.get("reset_times_s", [])]
        startup_failures = [a | {"rank": r["rank"]} for r in reports.values() if r for a in r.get("startup_failures", [])]
        startup_attempts = sum(len(r.get("startup_attempts", [])) for r in reports.values() if r)
        game_samples = [s for r in reports.values() if r for s in r.get("game_process_samples", [])]
        worker_procs = {rank: (r or {}).get("worker_process") for rank, r in reports.items()}
        failure_outcomes: Dict[str, int] = {}
        for r in reports.values():
            for k, v in (r or {}).get("failure_outcomes", {}).items():
                failure_outcomes[k] = failure_outcomes.get(k, 0) + v
        per_worker_native = {}
        for rank, r in reports.items():
            if r and r.get("native_step_hist", {}).get("n"):
                h = r["native_step_hist"]
                per_worker_native[rank] = {"steps": h["n"], "native_step_s": round(h["sum_s"], 3),
                                           "ticks_per_native_second": round(h["n"] / h["sum_s"], 1),
                                           "latency": LatencyHistogram.summary(h)}
        merged_native = LatencyHistogram.merged(native_hists)
        parent = ProcessMetrics().sample(os.getpid()) if ProcessMetrics is not None else None
        clears = [e for e in finished if e["end_reason"] == END_CLEAR]
        fastest = min(clears, key=lambda e: e["completion_time_passed"]) if clears else None
        end_counts = {r: sum(1 for e in finished if e["end_reason"] == r)
                      for r in (END_CLEAR, END_FALL, END_HORIZON, END_LIFECYCLE_FAILURE)}
        coordination = self.coordinator.read() if self.coordinator is not None else None
        written = [p for r in reports.values() if r for p in r.get("artifacts_written", [])]
        deletions = [d for r in reports.values() if r for d in r.get("episode_dir_deletions", [])]
        cpu_c = [r["cpu_util_collect"] for r in self.rollouts if r.get("cpu_util_collect") is not None]
        cpu_o = [r["cpu_util_optimize"] for r in self.rollouts if r.get("cpu_util_optimize") is not None]
        e2e = None
        if learn_s:
            inside = self.walls.get("inside_overhead_s", 0.0)
            e2e = round(transitions / max(1e-9, learn_s - inside), 1)
        return {
            "milestone": M7_MILESTONE,
            "run_id": c.run_id,
            "purpose": c.purpose,
            "created_utc": created,
            "finished_utc": utc_now(),
            "status": status,
            "error": None if error is None else f"{type(error).__name__}: {str(error)[:4000]}",
            "config": c.to_json(),
            "experiment": self.run_meta.get("experiment"),
            "reward_contract": c.reward.to_json(),
            "ppo": self.run_meta.get("ppo"),
            "contracts": self.run_meta.get("contracts"),
            "seeds": self.run_meta.get("seeds"),
            "m6_flags": dict(c.extra_env),
            "executable": self.run_meta.get("executable"),
            "revisions": self.run_meta.get("revisions"),
            "versions": self.run_meta.get("versions"),
            "torch_threads": self.run_meta.get("torch_threads"),
            "job_object": self.run_meta.get("job_object"),
            "lineage": self.run_meta.get("lineage"),
            "observation_path": ("raw native M1b observation + btt_spatial_v1 -> btt_policy_obs_v2_spatial (Dict, 525 "
                                 "values; state = btt_policy_obs_v1) -> VecNormalize(norm_obs=True, norm_obs_keys=%s, "
                                 "clip_obs=%g, norm_reward=False) -> MultiInputPolicy" % (list(mo.NORMALIZED_KEYS), c.clip_obs))
            if c.observation_v2 else
            "raw native M1b observation -> btt_policy_obs_v1 (15 float32, unchanged) -> "
            "VecNormalize(norm_obs=True, clip_obs=%g, norm_reward=False) -> policy" % c.clip_obs,
            "timesteps": {"requested_additional": c.total_timesteps, "start": self.start_timesteps,
                          "sb3_num_timesteps": None if model is None else int(model.num_timesteps),
                          "transitions_this_run": transitions,
                          "n_updates": None if model is None else int(model._n_updates),
                          "rollouts": len(self.rollouts), "optimizer_passes": 0 if model is None else len(model.m7_train_s)},
            "wall": {
                "run_total_s": round(run_s, 3),
                "spawn_s": round(self.walls.get("spawn_s", 0.0), 3),
                "initial_reset_s": round(self.walls.get("initial_reset_s", 0.0), 3),
                "learn_s": None if learn_s is None else round(learn_s, 3),
                "collect_s": round(collect_s, 3),
                "train_s": round(train_s, 3),
                "optimize_wall_s": round(optimize_wall_s, 3),
                "checkpoint_s_total": round(self.walls["checkpoint_s"], 3),
                "eval_s_total": round(self.walls["eval_s"], 3),
                "inside_learn_overhead_s": round(self.walls.get("inside_overhead_s", 0.0), 3),
                "context_broadcast_s": round(self.walls["context_s"], 3),
                "close_s": round(self.walls.get("close_s", 0.0), 3),
            },
            "throughput": {
                "end_to_end_transitions_per_s": e2e,
                "end_to_end_definition": "transitions of this run / (learn() wall time - checkpoint and evaluation "
                                         "time spent inside learn()); includes the initial reset, every process "
                                         "restart, synchronous stalls, inference, IPC and PPO updates",
                "collection_transitions_per_s": round(transitions / collect_s, 1) if collect_s else None,
                "native_ticks_per_s_aggregate_capacity": round(sum(v["ticks_per_native_second"]
                                                                   for v in per_worker_native.values()), 1)
                if per_worker_native else None,
                "native_definition": "per worker: native steps / time inside the M1d step round trip; summed over "
                                     "workers. This is native tick capacity, not PPO training throughput.",
                "per_worker_native": per_worker_native,
            },
            "time_split": {
                "collect_pct": round(100 * collect_s / (collect_s + optimize_wall_s), 2) if collect_s else None,
                "optimize_pct": round(100 * optimize_wall_s / (collect_s + optimize_wall_s), 2) if collect_s else None,
            },
            "policy_inference": None if self.forward is None else {
                "calls": self.forward.calls, "total_s": round(self.forward.total_s, 3),
                "mean_ms": round(1000 * self.forward.total_s / self.forward.calls, 4) if self.forward.calls else None},
            "vector": {
                "timing": timing,
                "synchronous_stall_s": round(sum(timing.get("per_worker_idle_s", [])), 3) if timing else None,
                "stall_definition": "sum over workers and vector steps of (vector step wall - that worker's own "
                                    "step time - its restart time): time a worker waited for the slowest one",
                "reset_vec_steps_wall_s": timing.get("reset_vec_steps_wall_s"),
            },
            "latency": {
                "native_step": LatencyHistogram.summary(merged_native),
                "worker_service": LatencyHistogram.summary(LatencyHistogram.merged(service_hists)),
                "vector_step_wall": timing.get("wall_ms"),
            },
            "restarts": {"reset_s": _stats(reset_times), "startup_attempts": startup_attempts,
                         "startup_retries": len(startup_failures), "startup_failures": startup_failures,
                         "note": "reset_s is the worker-side reset time: a cold launch (about 2.3 s) or, with the M7c "
                                 "standby lifecycle, the promotion of a ready standby (milliseconds) plus any exposed "
                                 "wait for one still booting; see lifecycle.standby"},
            "lifecycle": lifecycle_summary(c, reports, timing),
            "episodes": {
                "started": sum((r or {}).get("episodes_started", 0) for r in reports.values()),
                "finished": len(finished),
                "end_reasons": end_counts,
                "terminated": end_counts[END_CLEAR] + end_counts[END_FALL],
                "truncated": end_counts[END_HORIZON] + end_counts[END_LIFECYCLE_FAILURE],
                "length_mean": round(statistics.fmean([e["steps"] for e in finished]), 2) if finished else None,
                "return_mean": round(statistics.fmean([e["return"] for e in finished]), 4) if finished else None,
                "return_max": round(max(e["return"] for e in finished), 4) if finished else None,
                "targets_mean": round(statistics.fmean([e["targets_broken"] for e in finished]), 4) if finished else None,
                "targets_max": max((e["targets_broken"] for e in finished), default=None),
                "clears": len(clears),
                "fastest_clear": None if fastest is None else {k: fastest[k] for k in (
                    "rank", "episode_id", "completion_time_passed", "completion_input_tick", "artifact_dir")},
                "falls": end_counts[END_FALL],
            },
            "failures": {
                "lifecycle_failure_outcomes": failure_outcomes,
                "request_timeouts": failure_outcomes.get("episode_timeout", 0),
                "transport_failures": failure_outcomes.get("transport_failure", 0),
                "worker_startup_failures": len(startup_failures),
                "action_legality_failures": 0 if error is None else int("ValueError" in str(error)),
                "worker_failure": None if error is None else str(error).splitlines()[0][:500],
            },
            "anomalies": sum((r or {}).get("anomaly_events", 0) for r in reports.values()),
            "artifacts": {"preserved": sum((r or {}).get("preserved", 0) for r in reports.values()),
                          "discarded": sum((r or {}).get("discarded", 0) for r in reports.values()),
                          "written": written, "episode_dirs_deleted": sum(1 for d in deletions if d.get("deleted")),
                          "episode_dir_delete_errors": [d for d in deletions if not d.get("deleted")],
                          "failed_dirs_kept": sum((r or {}).get("failed_dirs_kept", 0) for r in reports.values()),
                          "coordination_state": coordination},
            "checkpoints": self.checkpoints + ([final_set] if final_set else []),
            "evaluations": self.evaluations,
            "cpu": {"system_util_collect_mean": round(statistics.fmean(cpu_c), 4) if cpu_c else None,
                    "system_util_optimize_mean": round(statistics.fmean(cpu_o), 4) if cpu_o else None,
                    "logical_cpus": os.cpu_count(),
                    "parent_cpu_s": None if not parent else round((parent.get("cpu_user_s") or 0) +
                                                                  (parent.get("cpu_kernel_s") or 0), 3)},
            "memory": {
                "parent": parent,
                "workers": worker_procs,
                "game_process_peak_working_set_mib_max": round(max((s.get("peak_working_set_bytes") or 0)
                                                                   for s in game_samples) / 2 ** 20, 1)
                if game_samples else None,
                "game_process_private_mib_max": round(max((s.get("private_bytes") or 0) for s in game_samples) / 2 ** 20, 1)
                if game_samples else None,
                "game_process_samples": len(game_samples),
            },
            "rollouts": self.rollouts,
            "cleanup": {"close": close, "ranks": rank_close, "battleship_processes_after": survivors,
                        "job_processes_after": job_pids, "leak_free": not survivors and not job_pids},
            "user_config": {"before": user_cfg[0], "after": user_cfg[1],
                            "byte_identical": user_cfg[0].get("sha256") == user_cfg[1].get("sha256"),
                            "mtime_unchanged": user_cfg[0].get("mtime_ns") == user_cfg[1].get("mtime_ns")},
        }


def lifecycle_summary(config: M7Config, reports: Mapping[Any, Optional[Dict[str, Any]]],
                      timing: Mapping[str, Any]) -> Dict[str, Any]:
    """M7c: aggregate the workers' standby reports (hits, misses, fallbacks, hidden/exposed time, resources)."""
    per_worker = {rank: (r or {}).get("standby") for rank, r in reports.items()}
    managers = [s.get("manager") for s in per_worker.values() if s and s.get("manager")]
    counts: Dict[str, int] = {}
    for m in managers:
        for k, v in m.get("counts", {}).items():
            counts[k] = counts.get(k, 0) + int(v)
    events = [e for s in per_worker.values() if s for e in s.get("events", [])]
    promoted = [e for e in events if e.get("event") == "promoted"]
    hits = [e for e in promoted if (e.get("exposed_wait_s") or 0.0) < 0.005]
    late = [e for e in promoted if (e.get("exposed_wait_s") or 0.0) >= 0.005]
    fallbacks = [e for e in events if e.get("event") not in ("promoted",)]
    fallback_reasons: Dict[str, int] = {}
    for e in fallbacks:
        fallback_reasons[e["event"]] = fallback_reasons.get(e["event"], 0) + 1
    startup = [v for m in managers for v in _hist_values(m.get("startup_s"))]
    hidden_startup_s = sum(float(e.get("standby_startup_s") or 0.0) for e in promoted)
    exposed = [float(e.get("exposed_wait_s") or 0.0) for e in promoted] + \
              [float(v) for s in per_worker.values() if s for v in []]
    ready_before = [float(e.get("ready_before_promotion_s") or 0.0) for e in promoted]
    retire = [v for s in per_worker.values() if s for v in s.get("retire_s", [])]
    history = [h for m in managers for h in m.get("history", [])]
    parked: List[Dict[str, Any]] = []
    for h in history:
        a, b = h.get("resource_at_ready"), h.get("resource_at_promotion")
        if a and b and h.get("outcome") == "promoted":
            parked.append({"cpu_s_while_parked": round((b.get("cpu_user_s") or 0) + (b.get("cpu_kernel_s") or 0)
                                                        - (a.get("cpu_user_s") or 0) - (a.get("cpu_kernel_s") or 0), 4),
                           "parked_s": h.get("ready_before_promotion_s"),
                           "ws_mib_at_ready": round((a.get("working_set_bytes") or 0) / 2 ** 20, 1),
                           "private_mib_at_ready": round((a.get("private_bytes") or 0) / 2 ** 20, 1),
                           "boot_cpu_s": round((a.get("cpu_user_s") or 0) + (a.get("cpu_kernel_s") or 0), 3)})
    threads = {"started": sum(int(m.get("threads_started", 0)) for m in managers),
               "joined": sum(int(m.get("threads_joined", 0)) for m in managers),
               "alive_at_close": sum(1 for m in managers if m.get("thread_alive"))}
    resets_total = sum(int(v) for v in timing.get("per_worker_resets", [])) if timing else 0
    return {
        "settings": config.lifecycle_json(),
        "expected_max_game_processes": config.lifecycle_json()["max_game_processes"],
        "observed_max_concurrent_per_worker": max((int(s.get("max_concurrent_processes", 0)) for s in per_worker.values() if s),
                                                  default=0),
        "reset_modes": dict((timing or {}).get("reset_modes", {})),
        "standby": {
            "counts": counts,
            "promotions": len(promoted),
            "hits_ready_at_reset": len(hits),
            "late_hits_waited": len(late),
            "cold_fallbacks": len(fallbacks),
            "fallback_reasons": fallback_reasons,
            "hit_rate_of_auto_resets": round(len(hits) / resets_total, 4) if resets_total else None,
            "promotion_rate_of_auto_resets": round(len(promoted) / resets_total, 4) if resets_total else None,
            "standby_startup_s": _stats(startup),
            "hidden_startup_s_total": round(hidden_startup_s, 3),
            "exposed_wait_s": _stats(exposed),
            "exposed_wait_s_total": round(sum(exposed), 3),
            "ready_before_promotion_s": _stats(ready_before),
            "promotion_s_total": round(sum((timing or {}).get("per_worker_promotion_s", [])), 4),
            "retire_s": _stats(retire, 4),
            "standby_failed_attempts": counts.get("failed_attempts", 0),
            "standby_failures": counts.get("failed", 0),
            "standby_lost": counts.get("lost", 0),
            "standby_wait_timeouts": counts.get("wait_timeouts", 0),
            "standby_starting_errors": counts.get("starting_errors", 0),
            "threads": threads,
            "parked_resource": {"samples": len(parked),
                                "cpu_s_while_parked_max": max((p["cpu_s_while_parked"] for p in parked), default=None),
                                "cpu_s_while_parked_mean": round(statistics.fmean([p["cpu_s_while_parked"] for p in parked]), 4)
                                if parked else None,
                                "parked_s_mean": round(statistics.fmean([p["parked_s"] or 0.0 for p in parked]), 3) if parked else None,
                                "ws_mib_at_ready_max": max((p["ws_mib_at_ready"] for p in parked), default=None),
                                "private_mib_at_ready_max": max((p["private_mib_at_ready"] for p in parked), default=None),
                                "boot_cpu_s_mean": round(statistics.fmean([p["boot_cpu_s"] for p in parked]), 3) if parked else None},
        },
        "per_worker": per_worker,
    }


def _hist_values(stats: Optional[Mapping[str, Any]]) -> List[float]:
    """The manager reports summary statistics only; expose the mean n times so merged stats stay weighted."""
    if not stats or not stats.get("n"):
        return []
    return [float(stats["mean_s"])] * int(stats["n"])


def run_training(config: M7Config) -> Dict[str, Any]:
    return M7Run(config).run()


# -- process-count comparison --------------------------------------------------------------------------------


def comparison_row(summary: Mapping[str, Any]) -> Dict[str, Any]:
    t, w, e, f = summary["throughput"], summary["wall"], summary["episodes"], summary["failures"]
    return {
        "run_id": summary["run_id"],
        "n_envs": summary["config"]["n_envs"],
        "n_steps": summary["config"]["n_steps"],
        "status": summary["status"],
        "transitions": summary["timesteps"]["transitions_this_run"],
        "rollouts": summary["timesteps"]["rollouts"],
        "learn_s": w["learn_s"],
        "end_to_end_transitions_per_s": t["end_to_end_transitions_per_s"],
        "collection_transitions_per_s": t["collection_transitions_per_s"],
        "native_ticks_per_s_aggregate_capacity": t["native_ticks_per_s_aggregate_capacity"],
        "collect_s": w["collect_s"],
        "optimize_wall_s": w["optimize_wall_s"],
        "train_s": w["train_s"],
        "collect_pct": summary["time_split"]["collect_pct"],
        "optimize_pct": summary["time_split"]["optimize_pct"],
        "policy_inference_s": (summary.get("policy_inference") or {}).get("total_s"),
        "native_step_s": round(sum(v["native_step_s"] for v in t["per_worker_native"].values()), 3),
        "initial_reset_s": w["initial_reset_s"],
        "restart_s": summary["restarts"]["reset_s"],
        "synchronous_stall_s": summary["vector"]["synchronous_stall_s"],
        "reset_vec_steps_wall_s": summary["vector"]["reset_vec_steps_wall_s"],
        "episodes_started": e["started"],
        "episodes_finished": e["finished"],
        "end_reasons": e["end_reasons"],
        "length_mean": e["length_mean"],
        "return_mean": e["return_mean"],
        "return_max": e["return_max"],
        "targets_mean": e["targets_mean"],
        "targets_max": e["targets_max"],
        "clears": e["clears"],
        "fastest_clear": e["fastest_clear"],
        "startup_retries": summary["restarts"]["startup_retries"],
        "startup_failures": f["worker_startup_failures"],
        "request_timeouts": f["request_timeouts"],
        "transport_failures": f["transport_failures"],
        "action_legality_failures": f["action_legality_failures"],
        "anomalies": summary["anomalies"],
        "cpu_util_collect": summary["cpu"]["system_util_collect_mean"],
        "cpu_util_optimize": summary["cpu"]["system_util_optimize_mean"],
        "parent_peak_working_set_mib": round((summary["memory"]["parent"] or {}).get("peak_working_set_bytes", 0) / 2 ** 20, 1),
        "parent_peak_private_mib": round((summary["memory"]["parent"] or {}).get("peak_private_bytes", 0) / 2 ** 20, 1),
        "worker_peak_working_set_mib_max": round(max(((w or {}).get("peak_working_set_bytes") or 0)
                                                     for w in summary["memory"]["workers"].values()) / 2 ** 20, 1)
        if summary["memory"]["workers"] else None,
        "game_peak_working_set_mib_max": summary["memory"]["game_process_peak_working_set_mib_max"],
        "game_private_mib_max": summary["memory"]["game_process_private_mib_max"],
        "native_step_latency": summary["latency"]["native_step"],
        "worker_service_latency": summary["latency"]["worker_service"],
        "vector_step_wall": summary["latency"]["vector_step_wall"],
        "artifacts_preserved": summary["artifacts"]["preserved"],
        "artifacts_discarded": summary["artifacts"]["discarded"],
        "checkpoints_written": len(summary["checkpoints"]),
        "leak_free": summary["cleanup"]["leak_free"],
        "workers_closed_cleanly": all(e.get("closed_cleanly") for e in summary["cleanup"]["ranks"].values()),
        "forced_terminations": summary["cleanup"]["close"].get("forced_terminations"),
        "user_config_byte_identical": summary["user_config"]["byte_identical"],
        # M7c lifecycle columns
        "standby_preboot": (summary.get("lifecycle") or {}).get("settings", {}).get("standby_preboot"),
        "standby_count": (summary.get("lifecycle") or {}).get("settings", {}).get("standby_count"),
        "expected_max_game_processes": (summary.get("lifecycle") or {}).get("expected_max_game_processes"),
        "observed_max_concurrent_per_worker": (summary.get("lifecycle") or {}).get("observed_max_concurrent_per_worker"),
        "reset_modes": (summary.get("lifecycle") or {}).get("reset_modes"),
        "standby_metrics": {k: v for k, v in ((summary.get("lifecycle") or {}).get("standby") or {}).items()
                            if k not in ("counts",)},
        "standby_failed_attempts": ((summary.get("lifecycle") or {}).get("standby") or {}).get("standby_failed_attempts", 0),
        "reset_vec_step_wall_hist": (summary["vector"]["timing"] or {}).get("reset_ms"),
    }


def select_process_count(rows: Sequence[Mapping[str, Any]], tolerance: float = 0.05) -> Dict[str, Any]:
    by_n: Dict[int, List[Mapping[str, Any]]] = {}
    for r in rows:
        by_n.setdefault(int(r["n_envs"]), []).append(r)

    def problems(rs: Sequence[Mapping[str, Any]]) -> List[str]:
        out = []
        for r in rs:
            if r["status"] != "completed":
                out.append(f"{r['run_id']}: status {r['status']}")
            for key in ("startup_failures", "request_timeouts", "transport_failures", "action_legality_failures",
                        "standby_failed_attempts"):
                if r.get(key):
                    out.append(f"{r['run_id']}: {key} {r[key]}")
            if not r["leak_free"] or not r["workers_closed_cleanly"] or r["forced_terminations"]:
                out.append(f"{r['run_id']}: cleanup problem")
            if (r["end_reasons"] or {}).get("lifecycle_failure"):
                out.append(f"{r['run_id']}: lifecycle failures {r['end_reasons']['lifecycle_failure']}")
        return out

    per_n = {}
    for n, rs in sorted(by_n.items()):
        tps = [float(r["end_to_end_transitions_per_s"]) for r in rs]
        per_n[n] = {"runs": [r["run_id"] for r in rs], "end_to_end_tps": tps, "mean_end_to_end_tps": round(statistics.fmean(tps), 1),
                    "spread_pct": round(100 * (max(tps) - min(tps)) / statistics.fmean(tps), 2) if len(tps) > 1 else 0.0,
                    "mean_optimize_pct": round(statistics.fmean([float(r["optimize_pct"]) for r in rs]), 2),
                    "mean_cpu_util_collect": round(statistics.fmean([float(r["cpu_util_collect"] or 0) for r in rs]), 4),
                    "reliability_problems": problems(rs)}
    decision: Dict[str, Any] = {"per_n": per_n, "tolerance": tolerance}
    if set(per_n) != {4, 5}:
        decision.update({"selected": None, "reason": "need both N=4 and N=5"})
        return decision
    p4, p5 = per_n[4], per_n[5]
    gain = (p5["mean_end_to_end_tps"] - p4["mean_end_to_end_tps"]) / p4["mean_end_to_end_tps"]
    decision["n5_vs_n4_gain"] = round(gain, 4)
    if p4["reliability_problems"] and not p5["reliability_problems"]:
        decision.update({"selected": 5, "reason": "N=4 showed reliability problems, N=5 none"})
    elif p5["reliability_problems"] and not p4["reliability_problems"]:
        decision.update({"selected": 4, "reason": "N=5 showed reliability problems, N=4 none"})
    elif gain > tolerance:
        decision.update({"selected": 5, "reason": f"N=5 end-to-end throughput {100 * gain:.1f} % above N=4 "
                                                   f"(> {100 * tolerance:.0f} %) with equal reliability"})
    else:
        decision.update({"selected": 4, "reason": f"N=5 vs N=4 end-to-end difference {100 * gain:+.1f} % is within "
                                                   f"{100 * tolerance:.0f} % or negative: N=4 preferred for stability "
                                                   "and CPU headroom"})
    return decision


def run_comparison(base: M7Config, order: Sequence[int], compare_id: str,
                   config_factory: Optional[Any] = None, root: Optional[Path] = None) -> Dict[str, Any]:
    """Sequential runs with different process counts. `config_factory(k, n, run_id)` (M7b) builds each run's
    M7Config from the legacy arguments so that every run carries its own experiment provenance; `root` is the
    comparison directory (default <runs_dir>/<compare_id>)."""
    root = Path(root) if root is not None else Path(base.runs_dir) / compare_id
    if root.exists():
        raise FileExistsError(f"comparison directory already exists: {root}")
    root.mkdir(parents=True)
    rows = []
    for k, n in enumerate(order, 1):
        run_id = f"{compare_id}/run{k}_n{n}"
        if config_factory is not None:
            cfg = config_factory(k, int(n), run_id)
        else:
            cfg = replace(base, run_id=run_id, n_envs=int(n), n_steps=ROLLOUT_SIZE // int(n), experiment=None)
        before = list_processes_named(BATTLESHIP_IMAGE)
        if before:
            raise RuntimeError(f"BattleShip processes present before comparison run {k}: {before}")
        log(f"[m7] comparison run {k}/{len(order)}: N={n}")
        summary = run_training(cfg)
        rows.append(comparison_row(summary))
    decision = select_process_count(rows)
    report = {"milestone": M7_MILESTONE, "compare_id": compare_id, "created_utc": utc_now(), "order": list(order),
              "equal_workload": {"rollout_size": ROLLOUT_SIZE, "total_transitions": base.total_timesteps,
                                 "rollouts": base.total_timesteps // ROLLOUT_SIZE, "horizon": base.horizon,
                                 "batch_size": base.batch_size, "n_epochs": base.n_epochs, "gamma": base.gamma,
                                 "gae_lambda": base.gae_lambda, "base_seed": base.base_seed,
                                 "checkpoint_interval": base.checkpoint_interval,
                                 "periodic_episodes": base.periodic_episodes, "m6_flags": dict(base.extra_env),
                                 "reward_contract": base.reward.to_json(), "lifecycle": base.standby.to_json()},
              "runs": rows, "selection": decision}
    write_json(root / "comparison_report.json", report)
    return report
