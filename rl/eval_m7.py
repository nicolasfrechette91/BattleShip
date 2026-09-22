#!/usr/bin/env python3
"""M7a: evaluation CLI (never updates the policy or its normalisation statistics).

    python rl/eval_m7.py checkpoint runs/<id>/final --out runs/<id>/evaluations/manual_final
    python rl/eval_m7.py random --episodes 100 --out runs/<dir>/random_baseline
    python rl/eval_m7.py report --pilot runs/<pilot id> --random runs/<dir>/random_baseline --out <json>

A checkpoint is a checkpoint-set directory (model.zip + vecnormalize.pkl +
checkpoint.json + preservation_state.json); the statistics are mandatory and
loaded frozen (training = False, norm_reward = False). Every episode runs in a
fresh BattleShip process with the M6 training flags and the M7 worker stack.
Standard library only at module level (spawn workers re-import this file).
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import sys
from pathlib import Path
from typing import Optional, Sequence

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
            p.add_argument("--deterministic-episodes", type=int, default=2)
            p.add_argument("--stochastic-episodes", type=int, default=20)
        else:
            p.add_argument("--episodes", type=int, default=100)
        p.add_argument("--out", required=True)
        p.add_argument("--exe", default=None)
        p.add_argument("--workers", type=int, default=4)
        p.add_argument("--seed", type=int, default=12345)
        p.add_argument("--horizon", type=int, default=3600)
    r = sub.add_parser("report")
    r.add_argument("--pilot", required=True, help="pilot run directory")
    r.add_argument("--random", required=True, help="random-baseline evaluation directory")
    r.add_argument("--out", required=True)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    import m7_evaluation as ev  # heavy imports only in the parent process
    from battleship_env import DEFAULT_EXECUTABLE

    if args.command == "report":
        from m7_report import pilot_report

        report = pilot_report(Path(args.pilot), Path(args.random))
        with open(args.out, "w", encoding="utf-8", newline="\n") as fp:
            json.dump(report, fp, indent=2)
            fp.write("\n")
        print(json.dumps(report.get("learning_evidence"), indent=2), flush=True)
        return EXIT_OK
    settings = ev.EvaluationSettings(executable=str(args.exe or DEFAULT_EXECUTABLE), horizon=args.horizon,
                                     n_workers=args.workers, seed=args.seed)
    from m7_runtime import install_kill_on_close_job

    install_kill_on_close_job()
    try:
        if args.command == "checkpoint":
            result = ev.evaluate_checkpoint(args.checkpoint_dir, args.out, settings=settings,
                                            deterministic_episodes=args.deterministic_episodes,
                                            stochastic_episodes=args.stochastic_episodes)
        else:
            result = ev.evaluate_random(args.out, settings=settings, episodes=args.episodes)
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
