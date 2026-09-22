#!/usr/bin/env python3
"""M7 evaluation CLI (never updates the policy or its normalisation statistics).

    python rl/eval_m7.py checkpoint runs/<id>/final --out runs/<id>/evaluations/manual_final [--config <profile>]
    python rl/eval_m7.py random --config rl/configs/m7_mario_us_reward_v1.toml --out runs/<dir>/random_baseline
    python rl/eval_m7.py random --episodes 100 --out runs/<dir>/random_baseline          # legacy arguments
    python rl/eval_m7.py report --pilot runs/<pilot id> --random runs/<dir>/random_baseline --out <json>

A checkpoint is a checkpoint-set directory (model.zip + vecnormalize.pkl +
checkpoint.json + preservation_state.json); the statistics are mandatory and
loaded frozen (training = False, norm_reward = False). A checkpoint is
always evaluated under its OWN reward contract (M7b: read from
checkpoint.json, cross-checked with model.zip); with --config the profile
must be compatible with the checkpoint (task, contracts, reward, horizon,
architecture, VecNormalize) and supplies the operational settings
(workers, executable, timeouts). The random baseline takes its episode
count, seed, horizon, flags and reward contract from --config (legacy
arguments remain accepted). Every episode runs in a fresh BattleShip process
with the M7 worker stack. Standard library only at module level (spawn
workers re-import this file).
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


def parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("checkpoint", "random"):
        p = sub.add_parser(name)
        if name == "checkpoint":
            p.add_argument("checkpoint_dir")
            p.add_argument("--deterministic-episodes", type=int, default=None)
            p.add_argument("--stochastic-episodes", type=int, default=None)
        else:
            p.add_argument("--episodes", type=int, default=None, help="default: evaluation.random_baseline_episodes or 100")
        p.add_argument("--out", required=True)
        p.add_argument("--config", default=None, help="TOML experiment profile (operational settings + reward for random)")
        p.add_argument("--exe", default=None)
        p.add_argument("--workers", type=int, default=None)
        p.add_argument("--seed", type=int, default=None)
        p.add_argument("--horizon", type=int, default=None)
    r = sub.add_parser("report")
    r.add_argument("--pilot", required=True, help="pilot run directory")
    r.add_argument("--random", required=True, help="random-baseline evaluation directory")
    r.add_argument("--out", required=True)
    return parser.parse_args(argv)


def _settings(args: argparse.Namespace, ev: Any, exp: Any) -> Any:
    from battleship_env import DEFAULT_EXECUTABLE

    if exp is not None:
        v = exp.values
        return ev.EvaluationSettings(
            executable=str(args.exe or exp.executable), horizon=int(args.horizon or v["environment.horizon"]),
            n_workers=int(args.workers or exp.eval_workers), seed=int(args.seed if args.seed is not None else v["evaluation.seed"]),
            extra_env=exp.extra_env, startup_attempts=int(v["environment.startup_attempts"]),
            request_timeout=float(v["environment.request_timeout_s"]), step_timeout=float(v["environment.step_timeout_s"]),
            retain_failed_cap=int(v["artifacts.retain_failed_cap"]), reward=exp.reward, experiment=exp.summary(),
            port_block_base=int(v["environment.port_block_base"]), port_block_size=int(v["environment.port_block_size"]))
    return ev.EvaluationSettings(executable=str(args.exe or DEFAULT_EXECUTABLE), horizon=int(args.horizon or 3600),
                                 n_workers=int(args.workers or 4), seed=int(args.seed if args.seed is not None else 12345))


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.command == "report":
        from m7_report import pilot_report

        report = pilot_report(Path(args.pilot), Path(args.random))
        with open(args.out, "w", encoding="utf-8", newline="\n") as fp:
            json.dump(report, fp, indent=2)
            fp.write("\n")
        print(json.dumps(report.get("learning_evidence"), indent=2), flush=True)
        return EXIT_OK
    import experiment_config as ec

    exp = None
    if args.config:
        try:
            exp = ec.load_experiment(args.config)
        except ec.ConfigError as exc:
            print(f"ERROR: {exc}", flush=True)
            return EXIT_USAGE
    import m7_evaluation as ev  # heavy imports only in the parent process
    from m7_runtime import install_kill_on_close_job

    settings = _settings(args, ev, exp)
    install_kill_on_close_job()
    try:
        if args.command == "checkpoint":
            meta = ev.read_checkpoint_set(args.checkpoint_dir)
            if exp is not None:
                diffs = ec.compare_compatibility(ec.checkpoint_compatibility_view(meta),
                                                 ec.compatibility_view_from_values(exp.values, exp.reward, dict(exp.extra_env)))
                if diffs:
                    raise ev.CheckpointError(f"--config {args.config} is not compatible with the checkpoint: "
                                             f"{json.dumps(diffs, sort_keys=True)[:2000]}")
            det = args.deterministic_episodes if args.deterministic_episodes is not None else (
                int(exp.values["evaluation.deterministic_episodes"]) if exp else 2)
            sto = args.stochastic_episodes if args.stochastic_episodes is not None else (
                int(exp.values["evaluation.stochastic_episodes"]) if exp else 20)
            result = ev.evaluate_checkpoint(args.checkpoint_dir, args.out, settings=settings,
                                            deterministic_episodes=det, stochastic_episodes=sto)
            print(f"reward contract: {result['reward_contract']['contract']}", flush=True)
        else:
            episodes = args.episodes if args.episodes is not None else (
                int(exp.values["evaluation.random_baseline_episodes"]) if exp else 100)
            result = ev.evaluate_random(args.out, settings=settings, episodes=episodes)
            print(f"reward contract: {settings.reward.contract}", flush=True)
    except ev.CheckpointError as exc:
        print(f"ERROR: {exc}", flush=True)
        return EXIT_USAGE
    for mode, r in result["modes"].items():
        a = r["aggregate"]
        print(f"{mode}: episodes {a['episodes']} targets mean {a['targets_mean']} (CI95 {a['targets_mean_ci95']}) "
              f"max {a['targets_max']} clears {a['clears']} falls {a['falls']} horizon {a['horizon_truncations']} "
              f"frozen {r.get('frozen_check')}", flush=True)
    return EXIT_OK


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
