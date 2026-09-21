#!/usr/bin/env python3
"""M5: bounded Stable-Baselines3 PPO training smoke for BattleShip Mario Break the Targets.

This is a learning-pipeline proof, not serious training. It shows that

    PPO -> Track 1 (btt_s9_b8_v1) -> M3 (btt_raw_b8_s161_v1) -> M2 -> BattleShip

initialises, resets, samples Track 1 actions, receives btt_reward_v1,
performs optimizer updates, crosses episode boundaries, saves a model,
reloads it, runs inference from the reloaded model, records M4 artifacts
with training metadata, and closes every owned BattleShip process. Nothing
here is expected to clear the stage, beat random play or the 7.43 s baseline.

    python rl/train_m5.py                                    # bounded default run under runs/<run_id>/
    python rl/train_m5.py --total-timesteps 512 --max-episode-steps 128 --periodic-episodes 2
    python rl/train_m5.py --evaluate runs/<run_id>/final_model.zip --eval-steps 60
    python rl/train_m5.py --child-env SSB64_RL_NO_RENDER=1        # M6 training no-render host mode

Output layout (portable metadata, no machine-specific absolute paths):

    <runs-dir>/<run_id>/
        config.json               effective configuration, versions, contracts
        checkpoints/              ppo_<sb3 timesteps>_steps.zip at --checkpoint-interval
        artifacts/<episode_id>/   preserved M4 episode artifacts (metadata.json + actions.jsonl)
        episodes/                 M2 per-episode game files (save, result JSON, process log)
        final_model.zip           the model at the end of training
        interrupted_model.zip     only after Ctrl+C
        training_summary.json     counts, updates, wall time, artifacts, inference result

One BattleShip environment only (DummyVecEnv over a single process-backed
env); no SubprocVecEnv, no multiprocessing, no headless mode. The seed is a
Python/PyTorch seed for experiment repeatability; it never reaches the game.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gymnasium  # noqa: E402
import numpy as np  # noqa: E402
import stable_baselines3  # noqa: E402
import torch  # noqa: E402
from stable_baselines3 import PPO  # noqa: E402
from stable_baselines3.common.callbacks import BaseCallback  # noqa: E402
from stable_baselines3.common.monitor import Monitor  # noqa: E402
from stable_baselines3.common.vec_env import DummyVecEnv  # noqa: E402

from battleship_env import DEFAULT_EXECUTABLE  # noqa: E402
from btt_learning import (  # noqa: E402
    DEFAULT_MAX_EPISODE_STEPS,
    DEFAULT_REWARD_CONFIG,
    POLICY_OBSERVATION_SIZE,
    LearningEnvConfig,
    TrainingTracker,
    contracts,
    make_learning_env,
    track1_action_name,
    track1_to_native,
)
from run_artifacts import DEFAULT_POSITION_DELTA_THRESHOLD  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUNS_DIR = REPO_ROOT / "runs"
ALGORITHM = "PPO"
POLICY = "MlpPolicy"  # flat float32 Box observation (btt_policy_obs_v1); MultiDiscrete([9, 8]) actions

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


def log(message: str) -> None:
    print(message, flush=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def portable_path(path: Path) -> str:
    """Repo-relative when inside the repository, otherwise the file name only."""
    try:
        return Path(path).resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return Path(path).name


def versions() -> Dict[str, Any]:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "gymnasium": gymnasium.__version__,
        "numpy": np.__version__,
        "torch": torch.__version__,
        "stable_baselines3": stable_baselines3.__version__,
    }


# -- configuration -----------------------------------------------------------------------------


@dataclass
class TrainingConfig:
    run_id: str
    runs_dir: Path = DEFAULT_RUNS_DIR
    executable: Path = DEFAULT_EXECUTABLE
    total_timesteps: int = 1024
    seed: int = 0
    max_episode_steps: int = DEFAULT_MAX_EPISODE_STEPS
    n_steps: int = 256
    batch_size: int = 64
    n_epochs: int = 4
    learning_rate: float = 3e-4
    gamma: float = 0.99
    checkpoint_interval: int = 512  # SB3 timesteps between checkpoints; 0 disables
    periodic_episodes: Optional[int] = 10
    periodic_timesteps: Optional[int] = None
    position_delta_threshold: float = DEFAULT_POSITION_DELTA_THRESHOLD
    eval_steps: int = 30
    device: str = "cpu"
    verbose: int = 1
    startup_timeout: float = 60.0
    ready_timeout: float = 180.0
    request_timeout: float = 30.0
    exit_timeout: float = 30.0
    extra_env: Dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        if self.total_timesteps < 1:
            raise ValueError("total_timesteps must be >= 1")
        if self.max_episode_steps < 1:
            raise ValueError("max_episode_steps must be >= 1")
        if self.n_steps < 1 or self.batch_size < 1 or self.n_epochs < 1:
            raise ValueError("n_steps, batch_size and n_epochs must be >= 1")
        if self.checkpoint_interval < 0:
            raise ValueError("checkpoint_interval must be >= 0")
        if self.eval_steps < 0:
            raise ValueError("eval_steps must be >= 0")

    def to_json(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "runs_dir": portable_path(self.runs_dir),
            "executable": portable_path(self.executable),
            "algorithm": ALGORITHM,
            "policy": POLICY,
            "total_timesteps": self.total_timesteps,
            "seed": self.seed,
            "seed_scope": "python/numpy/torch only; never reaches the game",
            "max_episode_steps": self.max_episode_steps,
            "n_steps": self.n_steps,
            "batch_size": self.batch_size,
            "n_epochs": self.n_epochs,
            "learning_rate": self.learning_rate,
            "gamma": self.gamma,
            "checkpoint_interval": self.checkpoint_interval,
            "periodic_episodes": self.periodic_episodes,
            "periodic_timesteps": self.periodic_timesteps,
            "position_delta_threshold": self.position_delta_threshold,
            "eval_steps": self.eval_steps,
            "device": self.device,
            "startup_timeout": self.startup_timeout,
            "ready_timeout": self.ready_timeout,
            "request_timeout": self.request_timeout,
            "exit_timeout": self.exit_timeout,
            "extra_env": dict(self.extra_env),
            "reward": DEFAULT_REWARD_CONFIG.to_json(),
            "vec_env": "DummyVecEnv(1)",
        }


@dataclass(frozen=True)
class RunLayout:
    root: Path

    @property
    def config_path(self) -> Path:
        return self.root / "config.json"

    @property
    def checkpoints(self) -> Path:
        return self.root / "checkpoints"

    @property
    def artifacts(self) -> Path:
        return self.root / "artifacts"

    @property
    def episodes(self) -> Path:
        return self.root / "episodes"

    @property
    def final_model(self) -> Path:
        return self.root / "final_model.zip"

    @property
    def interrupted_model(self) -> Path:
        return self.root / "interrupted_model.zip"

    @property
    def summary_path(self) -> Path:
        return self.root / "training_summary.json"

    def create(self) -> None:
        for directory in (self.root, self.checkpoints, self.artifacts, self.episodes):
            directory.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, data: Mapping[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fp:
        json.dump(data, fp, indent=2)
        fp.write("\n")
    os.replace(tmp, path)


# -- callback ----------------------------------------------------------------------------------------


class M5TrainingCallback(BaseCallback):
    """Keeps the tracker's global timestep and checkpoint label current; saves periodic checkpoints.

    The checkpoint label stored in artifact labels is the stem of the most
    recent saved checkpoint ("initial" before the first one); together with
    the SB3 timestep counters in the labels it places an episode in training."""

    def __init__(self, tracker: TrainingTracker, layout: RunLayout, checkpoint_interval: int, verbose: int = 0):
        super().__init__(verbose)
        self.tracker = tracker
        self.layout = layout
        self.checkpoint_interval = int(checkpoint_interval)
        self.checkpoints: List[Path] = []
        self.rollouts = 0
        self._next_checkpoint = self.checkpoint_interval if self.checkpoint_interval > 0 else None

    def _on_training_start(self) -> None:
        self.tracker.sb3_num_timesteps = int(self.num_timesteps)
        if self.tracker.checkpoint_label is None:
            self.tracker.checkpoint_label = "initial"

    def _on_step(self) -> bool:
        self.tracker.sb3_num_timesteps = int(self.num_timesteps)
        if self._next_checkpoint is not None and self.num_timesteps >= self._next_checkpoint:
            self.save_checkpoint()
            while self._next_checkpoint <= self.num_timesteps:
                self._next_checkpoint += self.checkpoint_interval
        return True

    def _on_rollout_end(self) -> None:
        self.rollouts += 1

    def save_checkpoint(self) -> Path:
        stem = f"ppo_{int(self.num_timesteps):08d}_steps"
        path = self.layout.checkpoints / stem
        self.model.save(path)
        saved = path.with_suffix(".zip")
        self.checkpoints.append(saved)
        self.tracker.checkpoint_label = stem
        if self.verbose:
            log(f"[m5] checkpoint {saved.name} at sb3 timestep {self.num_timesteps}")
        return saved


# -- training -----------------------------------------------------------------------------------------


def snapshot_parameters(model: PPO) -> List[torch.Tensor]:
    return [p.detach().clone() for p in model.policy.parameters()]


def parameters_changed(before: Sequence[torch.Tensor], model: PPO) -> bool:
    return any(not torch.equal(b, p.detach()) for b, p in zip(before, model.policy.parameters()))


def build_env_config(config: TrainingConfig, layout: RunLayout, max_episode_steps: int) -> LearningEnvConfig:
    return LearningEnvConfig(
        artifact_root=layout.artifacts,
        executable=Path(config.executable),
        episodes_root=layout.episodes,
        max_episode_steps=max_episode_steps,
        reward=DEFAULT_REWARD_CONFIG,
        position_delta_threshold=config.position_delta_threshold,
        startup_timeout=config.startup_timeout,
        ready_timeout=config.ready_timeout,
        request_timeout=config.request_timeout,
        exit_timeout=config.exit_timeout,
        extra_env=dict(config.extra_env),
    )


def run_inference(
    model_path: Path,
    config: TrainingConfig,
    layout: RunLayout,
    *,
    steps: int,
    note: str,
) -> Dict[str, Any]:
    """Load a saved model, run `steps` deterministic actions on a fresh environment, record the episode.

    The episode is bounded to `steps` through M3's max_episode_steps, so it
    ends truncated (unless the policy clears the stage first) and the tracker
    preserves it for the reason `manual` as the evaluation record."""
    model = PPO.load(str(model_path), device=config.device)
    tracker = TrainingTracker(run_id=config.run_id, role="evaluation", periodic_episodes=None)
    tracker.checkpoint_label = model_path.stem
    tracker.sb3_num_timesteps = int(getattr(model, "num_timesteps", 0))  # the training stage the saved model was at
    env = make_learning_env(build_env_config(config, layout, max(int(steps), 1)), tracker)
    tracker.request_manual_preservation(note)
    result: Dict[str, Any] = {
        "model": model_path.name,
        "model_reloaded": True,
        "model_action_space": str(model.action_space),
        "model_observation_space": str(model.observation_space),
        "steps_requested": int(steps),
        "steps": 0,
        "actions": [],
        "native_actions": [],
        "consumed_ticks": [],
        "rewards": [],
        "episode_return": 0.0,
        "terminated": False,
        "truncated": False,
        "all_rewards_finite": True,
        "targets_broken": 0,
        "artifacts": [],
    }
    t0 = time.perf_counter()
    try:
        observation, info = env.reset(seed=config.seed)
        result["reset_step_count"] = info.get("step_count")
        result["reset_input_tick"] = info.get("input_tick")
        for _ in range(int(steps)):
            action, _state = model.predict(observation, deterministic=True)
            action = np.asarray(action)
            if not env.action_space.contains(action):
                raise RuntimeError(f"predicted action {action!r} is outside MultiDiscrete([9, 8])")
            native = track1_to_native(action)
            observation, reward, terminated, truncated, info = env.step(action)
            result["steps"] += 1
            result["actions"].append([int(action[0]), int(action[1])])
            result["native_actions"].append([native.buttons, native.stick_x, native.stick_y])
            result["consumed_ticks"].append(info.get("consumed_tick"))
            result["rewards"].append(float(reward))
            result["episode_return"] += float(reward)
            if not math.isfinite(float(reward)) or not np.all(np.isfinite(observation)):
                result["all_rewards_finite"] = False
            result["terminated"], result["truncated"] = bool(terminated), bool(truncated)
            if terminated or truncated:
                break
    finally:
        env.close()
    result["wall_s"] = round(time.perf_counter() - t0, 3)
    result["targets_broken"] = tracker.summaries[-1].targets_broken if tracker.summaries else 0
    result["artifacts"] = [p.name for p in env.recording.written]  # type: ignore[attr-defined]
    result["tracker"] = tracker.summary()
    result["owned_process_alive"] = bool(env.base_env.owned_process_alive)  # type: ignore[attr-defined]
    return result


def run_training(config: TrainingConfig) -> Dict[str, Any]:
    """The whole M5 pipeline: train (bounded), save, reload, infer, summarise. Returns the summary."""
    config.validate()
    layout = RunLayout(Path(config.runs_dir) / config.run_id)
    layout.create()
    write_json(layout.config_path, {"milestone": "M5", "created_utc": utc_now(), "config": config.to_json(),
                                    "versions": versions(), "contracts": contracts()})
    log(f"[m5] run {config.run_id}: {ALGORITHM}/{POLICY}, {config.total_timesteps} timesteps, "
        f"max_episode_steps {config.max_episode_steps}, n_steps {config.n_steps}, batch {config.batch_size}, "
        f"epochs {config.n_epochs}, seed {config.seed}, device {config.device}")

    tracker = TrainingTracker(run_id=config.run_id, role="training", periodic_episodes=config.periodic_episodes,
                              periodic_timesteps=config.periodic_timesteps, reward_config=DEFAULT_REWARD_CONFIG)
    tracker.sb3_num_timesteps = 0          # the first reset happens inside learn() before any callback fires
    tracker.checkpoint_label = "initial"   # the freshly initialised policy, before the first optimizer update
    learning_env = make_learning_env(build_env_config(config, layout, config.max_episode_steps), tracker)
    monitor = Monitor(learning_env)
    vec_env = DummyVecEnv([lambda: monitor])
    model = PPO(POLICY, vec_env, n_steps=config.n_steps, batch_size=config.batch_size, n_epochs=config.n_epochs,
                learning_rate=config.learning_rate, gamma=config.gamma, seed=config.seed, device=config.device,
                verbose=config.verbose)
    callback = M5TrainingCallback(tracker, layout, config.checkpoint_interval, verbose=config.verbose)
    before = snapshot_parameters(model)
    interrupted = False
    t0 = time.perf_counter()
    try:
        model.learn(total_timesteps=config.total_timesteps, callback=callback)
    except KeyboardInterrupt:
        interrupted = True
        log("[m5] KeyboardInterrupt: saving interrupted_model.zip and closing the environment")
        tracker.request_manual_preservation("training interrupted (KeyboardInterrupt)")
        model.save(layout.interrupted_model.with_suffix(""))
    finally:
        vec_env.close()  # Monitor -> Track 1 -> recorder (aborts a running episode) -> M3 close(): process disposed
    train_wall = time.perf_counter() - t0
    changed = parameters_changed(before, model)
    model.save(layout.final_model.with_suffix(""))
    n_updates = getattr(model, "_n_updates", None)
    minibatches_per_epoch = math.ceil(config.n_steps / config.batch_size)
    gradient_steps = None if n_updates is None else int(n_updates) * minibatches_per_epoch
    log(f"[m5] training done: sb3 timesteps {model.num_timesteps}, native steps {tracker.native_steps}, "
        f"episodes started {tracker.episodes_started} / finished {tracker.episodes_finished}, rollouts {callback.rollouts}, "
        f"sb3 n_updates {n_updates}, parameters changed {changed}, wall {train_wall:.1f} s, interrupted {interrupted}")

    inference: Dict[str, Any] = {}
    inference_error: Optional[str] = None
    if config.eval_steps > 0:
        try:
            inference = run_inference(layout.final_model, config, layout, steps=config.eval_steps,
                                      note=f"post-training evaluation of {layout.final_model.name}")
            log(f"[m5] inference from the reloaded model: {inference['steps']} steps, return {inference['episode_return']:.4f}, "
                f"terminated {inference['terminated']}, truncated {inference['truncated']}, artifacts {inference['artifacts']}")
        except Exception as exc:  # noqa: BLE001 - reported in the summary, then re-raised after writing it
            inference_error = f"{type(exc).__name__}: {exc}"

    written = [p.name for p in learning_env.recording.written]  # type: ignore[attr-defined]
    summary: Dict[str, Any] = {
        "milestone": "M5",
        "run_id": config.run_id,
        "created_utc": utc_now(),
        "versions": versions(),
        "algorithm": ALGORITHM,
        "policy": POLICY,
        "policy_observation_size": POLICY_OBSERVATION_SIZE,
        "config": config.to_json(),
        "contracts": contracts(),
        "training": {
            "total_timesteps_requested": config.total_timesteps,
            "sb3_num_timesteps": int(model.num_timesteps),
            "native_steps": tracker.native_steps,
            "episodes_started": tracker.episodes_started,
            "episodes_finished": tracker.episodes_finished,
            "rollouts": callback.rollouts,
            "sb3_n_updates": None if n_updates is None else int(n_updates),
            "gradient_steps_derived": gradient_steps,
            "gradient_steps_note": "sb3_n_updates counts n_epochs per rollout; gradient steps = sb3_n_updates * ceil(n_steps / batch_size)",
            "policy_parameters_changed": bool(changed),
            "wall_s": round(train_wall, 3),
            "interrupted": interrupted,
            "checkpoints": [p.name for p in callback.checkpoints],
            "final_model": layout.final_model.name,
            "interrupted_model": layout.interrupted_model.name if interrupted else None,
            "episode_failures": list(learning_env.failures),  # type: ignore[attr-defined]
            "tracker": tracker.summary(),
        },
        "artifacts": {
            "directory": "artifacts",
            "written": written,
            "discarded": learning_env.recording.discarded,  # type: ignore[attr-defined]
        },
        "inference": inference,
        "inference_error": inference_error,
        "owned_process_alive": bool(learning_env.base_env.owned_process_alive),  # type: ignore[attr-defined]
    }
    write_json(layout.summary_path, summary)
    summary["paths"] = {  # absolute, for the caller only; not written to disk
        "root": str(layout.root),
        "config": str(layout.config_path),
        "checkpoints": [str(p) for p in callback.checkpoints],
        "final_model": str(layout.final_model),
        "summary": str(layout.summary_path),
        "artifacts": str(layout.artifacts),
    }
    log(f"[m5] summary written: {layout.summary_path}")
    if inference_error is not None:
        raise RuntimeError(f"inference after training failed: {inference_error}")
    return summary


def run_evaluation(model_path: Path, config: TrainingConfig) -> Dict[str, Any]:
    layout = RunLayout(Path(config.runs_dir) / config.run_id)
    layout.create()
    result = run_inference(model_path, config, layout, steps=config.eval_steps, note=f"evaluation of {model_path.name}")
    write_json(layout.root / "evaluation_summary.json", {"milestone": "M5", "created_utc": utc_now(), "versions": versions(),
                                                          "config": config.to_json(), "inference": result})
    log(f"[m5] evaluation: {result['steps']} steps, return {result['episode_return']:.4f}, terminated {result['terminated']}, "
        f"truncated {result['truncated']}, actions {[track1_action_name(a) for a in result['actions'][:8]]}..., "
        f"artifacts {result['artifacts']}")
    return result


# -- CLI --------------------------------------------------------------------------------------------------------


def parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--exe", default=str(DEFAULT_EXECUTABLE), help="BattleShip executable (default: %(default)s)")
    parser.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR), help="parent of run directories (default: %(default)s)")
    parser.add_argument("--run-id", default=None, help="run directory name (default: m5_<utc timestamp>)")
    parser.add_argument("--total-timesteps", type=int, default=1024, help="SB3 timesteps to train (default: %(default)s)")
    parser.add_argument("--seed", type=int, default=0, help="Python/NumPy/PyTorch seed; never reaches the game")
    parser.add_argument("--max-episode-steps", type=int, default=DEFAULT_MAX_EPISODE_STEPS,
                        help="M3 Python-owned episode bound in native ticks (default: %(default)s)")
    parser.add_argument("--n-steps", type=int, default=256)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--n-epochs", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--gamma", type=float, default=0.99)
    parser.add_argument("--checkpoint-interval", type=int, default=512, help="SB3 timesteps between checkpoints; 0 disables")
    parser.add_argument("--periodic-episodes", type=int, default=10, help="preserve every Nth finished episode; 0 disables")
    parser.add_argument("--periodic-timesteps", type=int, default=0, help="also preserve after every N native steps; 0 disables")
    parser.add_argument("--position-delta-threshold", type=float, default=DEFAULT_POSITION_DELTA_THRESHOLD,
                        help="M4 anomaly detector threshold, game units per tick (default: %(default)s)")
    parser.add_argument("--eval-steps", type=int, default=30, help="inference steps from the reloaded model (0 skips)")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--verbose", type=int, default=1)
    parser.add_argument("--evaluate", default=None, metavar="MODEL", help="only load MODEL and run --eval-steps on a fresh env")
    parser.add_argument("--startup-timeout", type=float, default=60.0)
    parser.add_argument("--ready-timeout", type=float, default=180.0)
    parser.add_argument("--request-timeout", type=float, default=30.0)
    parser.add_argument("--exit-timeout", type=float, default=30.0)
    parser.add_argument("--child-env", action="append", default=[], metavar="KEY=VALUE",
                        help="extra environment for every launched BattleShip process (TrainingConfig.extra_env -> M2 "
                             "LaunchConfig.extra_env), e.g. SSB64_RL_NO_RENDER=1 for the M6 training no-render host "
                             "mode; repeatable; recorded in config.json")
    args = parser.parse_args(argv)
    child_env: Dict[str, str] = {}
    for item in args.child_env:
        if "=" not in item:
            parser.error(f"--child-env expects KEY=VALUE, got {item!r}")
        key, value = item.split("=", 1)
        child_env[key] = value
    args.child_env = child_env
    return args


def config_from_args(args: argparse.Namespace) -> TrainingConfig:
    run_id = args.run_id or f"m5_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    return TrainingConfig(
        run_id=run_id,
        runs_dir=Path(args.runs_dir),
        executable=Path(args.exe),
        total_timesteps=args.total_timesteps,
        seed=args.seed,
        max_episode_steps=args.max_episode_steps,
        n_steps=args.n_steps,
        batch_size=args.batch_size,
        n_epochs=args.n_epochs,
        learning_rate=args.learning_rate,
        gamma=args.gamma,
        checkpoint_interval=args.checkpoint_interval,
        periodic_episodes=args.periodic_episodes or None,
        periodic_timesteps=args.periodic_timesteps or None,
        position_delta_threshold=args.position_delta_threshold,
        eval_steps=args.eval_steps,
        device=args.device,
        verbose=args.verbose,
        startup_timeout=args.startup_timeout,
        ready_timeout=args.ready_timeout,
        request_timeout=args.request_timeout,
        exit_timeout=args.exit_timeout,
        extra_env=dict(args.child_env),
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if not Path(args.exe).is_file():
        log(f"ERROR: executable not found: {args.exe}")
        return EXIT_USAGE
    config = config_from_args(args)
    try:
        config.validate()
    except ValueError as exc:
        log(f"ERROR: {exc}")
        return EXIT_USAGE
    try:
        if args.evaluate:
            model_path = Path(args.evaluate)
            if not model_path.is_file():
                log(f"ERROR: model not found: {model_path}")
                return EXIT_USAGE
            run_evaluation(model_path, config)
        else:
            summary = run_training(config)
            t = summary["training"]
            log(f"M5 TRAINING SMOKE OK: run {config.run_id}: {t['sb3_num_timesteps']} timesteps, "
                f"{t['episodes_finished']} finished episodes, {t['sb3_n_updates']} sb3 updates, "
                f"parameters changed {t['policy_parameters_changed']}, {len(summary['artifacts']['written'])} artifact(s), "
                f"inference {summary['inference'].get('steps')} steps")
    except KeyboardInterrupt:
        log("interrupted")
        return EXIT_FAILED
    except Exception as exc:  # noqa: BLE001 - one line for the operator, full trace after it
        import traceback

        log(f"M5 FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return EXIT_FAILED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
