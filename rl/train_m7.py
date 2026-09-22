#!/usr/bin/env python3
"""M7a: parallel PPO training CLI for BattleShip Mario Break the Targets.

    python rl/train_m7.py train   --n-envs 4 --total-timesteps 51200 --run-id <id>
    python rl/train_m7.py compare --order 4,5,5,4 --total-timesteps 51200 --compare-id <id>
    python rl/train_m7.py pilot   --n-envs <N> --run-id <id>          # 1,024,000 transitions, evaluation cadence
    python rl/train_m7.py resume  --from runs/<id>/checkpoints/ckpt_<t> --total-timesteps 5120 --run-id <new id>

Every training process gets SSB64_RL_NO_RENDER=1 and SSB64_RAPHNET_DISABLE=1
(the M6 training flags); nothing else is affected. Workers run in isolated
runtime directories under the run directory; the user's BattleShip.cfg.json is
never opened by a worker. Output layout: see rl/m7_trainer.py.

This file imports only the standard library at module level: SubprocVecEnv
spawn workers re-import it as __mp_main__ and must stay free of PyTorch.
"""

from __future__ import annotations

import argparse
import multiprocessing
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130

PILOT_TOTAL = 1_024_000
PILOT_CHECKPOINT = 51_200
PILOT_EVAL = 102_400


def _raise_keyboard_interrupt(signum, frame):  # noqa: ARG001 - signal handler signature
    raise KeyboardInterrupt(f"signal {signum}")


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--runs-dir", default=None, help="parent of run directories (default: <repo>/runs)")
    p.add_argument("--exe", default=None, help="BattleShip executable (default: build-us/Release/BattleShip.exe)")
    p.add_argument("--seed", type=int, default=0, help="base seed (Python/NumPy/Torch/SB3 only; never reaches the game)")
    p.add_argument("--horizon", type=int, default=3600, help="Python-owned episode bound in native ticks")
    p.add_argument("--checkpoint-interval", type=int, default=None)
    p.add_argument("--periodic-episodes", type=int, default=10, help="global periodic artifact every N finished episodes")
    p.add_argument("--eval-workers", type=int, default=None)
    p.add_argument("--eval-seed", type=int, default=12345)
    p.add_argument("--eval-stochastic-episodes", type=int, default=20)
    p.add_argument("--eval-deterministic-episodes", type=int, default=2)


def parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("train")
    _common(t)
    t.add_argument("--n-envs", type=int, required=True)
    t.add_argument("--total-timesteps", type=int, required=True)
    t.add_argument("--run-id", default=None)
    t.add_argument("--eval-interval", type=int, default=0)
    t.add_argument("--eval-initial", action="store_true")
    t.add_argument("--eval-final", action="store_true")
    c = sub.add_parser("compare")
    _common(c)
    c.add_argument("--order", default="4,5,5,4")
    c.add_argument("--total-timesteps", type=int, default=51200)
    c.add_argument("--compare-id", default=None)
    pl = sub.add_parser("pilot")
    _common(pl)
    pl.add_argument("--n-envs", type=int, required=True)
    pl.add_argument("--run-id", default=None)
    r = sub.add_parser("resume")
    _common(r)
    r.add_argument("--from", dest="source", required=True, help="checkpoint set directory to continue from")
    r.add_argument("--n-envs", type=int, required=True)
    r.add_argument("--total-timesteps", type=int, required=True, help="additional transitions")
    r.add_argument("--run-id", default=None)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    signal.signal(signal.SIGINT, _raise_keyboard_interrupt)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _raise_keyboard_interrupt)
    import m7_trainer as tr  # heavy imports only in the parent process
    from m7_evaluation import CheckpointError

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    common = {"base_seed": args.seed, "horizon": args.horizon, "periodic_episodes": args.periodic_episodes,
              "eval_workers": args.eval_workers, "eval_seed": args.eval_seed,
              "eval_stochastic_episodes": args.eval_stochastic_episodes,
              "eval_deterministic_episodes": args.eval_deterministic_episodes}
    if args.runs_dir:
        common["runs_dir"] = Path(args.runs_dir)
    if args.exe:
        common["executable"] = Path(args.exe)
        if not Path(args.exe).is_file():
            print(f"ERROR: executable not found: {args.exe}", flush=True)
            return EXIT_USAGE
    try:
        if args.command == "train":
            cfg = tr.M7Config(run_id=args.run_id or f"m7_train_{stamp}", n_envs=args.n_envs,
                              total_timesteps=args.total_timesteps, purpose="training",
                              checkpoint_interval=args.checkpoint_interval if args.checkpoint_interval is not None else 51200,
                              eval_interval=args.eval_interval, eval_initial=args.eval_initial,
                              eval_final=args.eval_final, **common)
            summary = tr.run_training(cfg)
        elif args.command == "compare":
            order = [int(v) for v in args.order.split(",")]
            base = tr.M7Config(run_id="unused", n_envs=order[0], total_timesteps=args.total_timesteps,
                               purpose="process_count_comparison",
                               checkpoint_interval=args.checkpoint_interval if args.checkpoint_interval is not None else 25600,
                               **common)
            report = tr.run_comparison(base, order, args.compare_id or f"m7_compare_{stamp}")
            print(f"selection: {report['selection']}", flush=True)
            return EXIT_OK
        elif args.command == "pilot":
            cfg = tr.M7Config(run_id=args.run_id or f"m7_pilot_{stamp}", n_envs=args.n_envs,
                              total_timesteps=PILOT_TOTAL, purpose="pilot",
                              checkpoint_interval=args.checkpoint_interval if args.checkpoint_interval is not None else PILOT_CHECKPOINT,
                              eval_interval=PILOT_EVAL, eval_initial=True, eval_final=True, **common)
            summary = tr.run_training(cfg)
        else:
            cfg = tr.M7Config(run_id=args.run_id or f"m7_resume_{stamp}", n_envs=args.n_envs,
                              total_timesteps=args.total_timesteps, purpose="resume",
                              checkpoint_interval=args.checkpoint_interval if args.checkpoint_interval is not None else 51200,
                              resume_from=Path(args.source), **common)
            summary = tr.run_training(cfg)
    except (CheckpointError, FileExistsError, ValueError) as exc:
        print(f"ERROR: {exc}", flush=True)
        return EXIT_USAGE
    except KeyboardInterrupt:
        print("interrupted", flush=True)
        return EXIT_INTERRUPTED
    if summary["status"] == "interrupted":
        return EXIT_INTERRUPTED
    return EXIT_OK if summary["status"] == "completed" and summary["cleanup"]["leak_free"] else EXIT_FAILED


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
