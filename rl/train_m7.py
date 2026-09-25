#!/usr/bin/env python3
"""M7 training CLI for BattleShip Mario Break the Targets (M7b: TOML-configured).

    python rl/train_m7.py --config rl/configs/m7_mario_us_reward_v1.toml --dry-run
    python rl/train_m7.py --config rl/configs/m7_mario_us_reward_v1.toml --run-id <run name>
    python rl/train_m7.py --config rl/configs/m7_mario_us_reward_v2.toml --run-id <run name>
    python rl/train_m7.py --config <profile> --resume-from runs/<id>/checkpoints/ckpt_<t> --run-id <new run name>

The TOML profile (rl/experiment_config.py) is the authoritative source of
every behavioural setting: task, contracts, reward values, environment
behaviour, PPO, VecNormalize, evaluation protocol. The command line only
selects the profile and operational things that cannot change what the
experiment means: --dry-run (parse, validate, resolve, print; launches
nothing and writes nothing unless --dry-run-output names a file), --run-id
(run.name), --output-root (run.output_root), --resume-from
(run.mode = resume + resume.source_checkpoint). Every override is recorded
in the run's experiment block.

Legacy M7a subcommands (compatibility path, translated into the same
schema and recorded as such; behaviour identical to M7a):

    python rl/train_m7.py train   --n-envs 4 --total-timesteps 51200 --run-id <id>
    python rl/train_m7.py compare --order 4,5,5,4 --total-timesteps 51200 --compare-id <id>
    python rl/train_m7.py pilot   --n-envs <N> --run-id <id>          # 1,024,000 transitions, evaluation cadence
    python rl/train_m7.py resume  --from runs/<id>/checkpoints/ckpt_<t> --n-envs <N> --total-timesteps 5120 --run-id <new id>

Every training process gets the M6 flags the profile enables
(SSB64_RL_NO_RENDER=1 and SSB64_RAPHNET_DISABLE=1 in the checked-in
profiles). Workers run in isolated runtime directories; the user's
BattleShip.cfg.json is never opened by a worker. Output layout: see
rl/m7_trainer.py.

This file imports only the standard library at module level: SubprocVecEnv
spawn workers re-import it as __mp_main__ and must stay free of PyTorch.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

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
    # accepted after the subcommand as well; SUPPRESS keeps a top-level --dry-run from being reset to False
    p.add_argument("--dry-run", dest="dry_run", action="store_true", default=argparse.SUPPRESS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=None, help="TOML experiment profile (authoritative behavioural settings)")
    parser.add_argument("--dry-run", action="store_true",
                        help="parse, validate, resolve and print; launch nothing, write nothing (except --dry-run-output)")
    parser.add_argument("--dry-run-output", default=None, help="optional path: write the resolved JSON there (dry run only)")
    parser.add_argument("--run-id", default=None, help="override run.name (operational; recorded)")
    parser.add_argument("--output-root", default=None, help="override run.output_root (operational; recorded)")
    parser.add_argument("--resume-from", default=None,
                        help="checkpoint-set directory: run.mode = resume, resume.source_checkpoint (operational; recorded)")
    sub = parser.add_subparsers(dest="command", required=False, metavar="{train,compare,pilot,resume}",
                                help="legacy M7a subcommands (compatibility path)")
    t = sub.add_parser("train")
    _common(t)
    t.add_argument("--n-envs", type=int, required=True)
    t.add_argument("--total-timesteps", type=int, required=True)
    t.add_argument("--run-id", dest="legacy_run_id", default=None)
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
    pl.add_argument("--run-id", dest="legacy_run_id", default=None)
    r = sub.add_parser("resume")
    _common(r)
    r.add_argument("--from", dest="source", required=True, help="checkpoint set directory to continue from")
    r.add_argument("--n-envs", type=int, required=True)
    r.add_argument("--total-timesteps", type=int, required=True, help="additional transitions")
    r.add_argument("--run-id", dest="legacy_run_id", default=None)
    return parser


def parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def _legacy_namespace(args: argparse.Namespace) -> Dict[str, Any]:
    """The legacy argparse values under the M7a names expected by experiment_config.from_legacy_arguments."""
    d = dict(vars(args))
    d["run_id"] = d.pop("legacy_run_id", None)
    return d


def dry_run(exp: Any, output: Optional[str]) -> int:
    """Print the resolved configuration, contract identities and fingerprints; write nothing unless asked."""
    import experiment_config as ec

    meta = None
    if exp.mode == "resume" and exp.resume_source is not None:
        meta_path = Path(exp.resume_source) / "checkpoint.json"
        if meta_path.is_file():
            with open(meta_path, encoding="utf-8") as fp:
                meta = json.load(fp)
        else:
            print(f"resume source has no checkpoint.json: {meta_path}", flush=True)
    print(ec.describe(exp, checkpoint_meta=meta), flush=True)
    resolved = exp.resolved_json()
    print("resolved configuration (JSON):", flush=True)
    print(json.dumps(resolved, indent=2, sort_keys=True), flush=True)
    print("dry run: no process launched, no file written" + (f" except {output}" if output else ""), flush=True)
    if output:
        out = Path(output)
        with open(out, "w", encoding="utf-8", newline="\n") as fp:
            json.dump(resolved, fp, indent=2, sort_keys=True)
            fp.write("\n")
    return EXIT_OK


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv_list = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv_list)
    if args.config is None and args.command is None:
        parser.print_usage()
        print("ERROR: give --config <profile.toml> (or a legacy subcommand)", flush=True)
        return EXIT_USAGE
    if args.config is not None and args.command is not None:
        print("ERROR: --config and a legacy subcommand are exclusive", flush=True)
        return EXIT_USAGE
    signal.signal(signal.SIGINT, _raise_keyboard_interrupt)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _raise_keyboard_interrupt)
    import experiment_config as ec  # light: no torch

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    try:
        if args.config is not None:
            exp = ec.load_experiment(args.config)
            overrides: Dict[str, Any] = {}
            if args.run_id:
                overrides["run.name"] = args.run_id
            if args.output_root:
                overrides["run.output_root"] = args.output_root
            if args.resume_from:
                overrides["run.mode"] = "resume"
                overrides["resume.source_checkpoint"] = args.resume_from
            if overrides:
                exp = exp.with_overrides(overrides)
            if args.dry_run:
                return dry_run(exp, args.dry_run_output)
            print(f"[m7] experiment {exp.name}: reward {exp.reward.contract}, semantic fingerprint "
                  f"{exp.semantic_fingerprint[:16]}..., source sha256 {exp.source.sha256[:16]}...", flush=True)
            import m7_trainer as tr  # heavy imports only in the parent process
            from m7_evaluation import CheckpointError

            cfg = tr.config_from_experiment(exp)
            summary = tr.run_training(cfg)
        else:
            legacy = _legacy_namespace(args)
            command = args.command
            print(f"[m7] legacy compatibility path: 'train_m7.py {command}' arguments are translated into the "
                  "experiment schema (rl/experiment_config.py); behaviour identical to M7a", flush=True)
            if command == "compare":
                compare_id = args.compare_id or f"m7_compare_{stamp}"
                order = [int(v) for v in args.order.split(",")]
                runs_dir = Path(args.runs_dir) if args.runs_dir else Path(ec.REPO_ROOT) / "runs"
                root = (runs_dir / compare_id).resolve()
                legacy_cmp = dict(legacy, runs_dir=str(root))

                def make(k: int, n: int, run_id: str) -> Any:
                    e = ec.from_legacy_arguments("compare", legacy_cmp, argv=argv_list, n_envs=n, run_name=run_id)
                    return tr.config_from_experiment(e, purpose="process_count_comparison")

                first = ec.from_legacy_arguments("compare", legacy_cmp, argv=argv_list, n_envs=order[0], run_name="run1")
                if args.dry_run:
                    return dry_run(first, args.dry_run_output)
                import m7_trainer as tr

                base = tr.config_from_experiment(first, purpose="process_count_comparison")
                report = tr.run_comparison(base, order, compare_id, config_factory=make, root=root)
                print(f"selection: {report['selection']}", flush=True)
                return EXIT_OK
            run_name = legacy.get("run_id") or f"m7_{command}_{stamp}"
            exp = ec.from_legacy_arguments(command, legacy, argv=argv_list, run_name=run_name)
            if args.dry_run:
                return dry_run(exp, args.dry_run_output)
            import m7_trainer as tr
            from m7_evaluation import CheckpointError

            cfg = tr.config_from_experiment(exp)
            summary = tr.run_training(cfg)
    except ec.ConfigError as exc:
        print(f"ERROR: {exc}", flush=True)
        return EXIT_USAGE
    except (FileExistsError, ValueError) as exc:
        print(f"ERROR: {exc}", flush=True)
        return EXIT_USAGE
    except RuntimeError as exc:
        if type(exc).__name__ == "CheckpointError":
            print(f"ERROR: {exc}", flush=True)
            return EXIT_USAGE
        raise
    except KeyboardInterrupt:
        print("interrupted", flush=True)
        return EXIT_INTERRUPTED
    if summary["status"] in ("interrupted", "stopped"):     # M7h: "stopped" = cooperative stop request
        return EXIT_INTERRUPTED
    return EXIT_OK if summary["status"] == "completed" and summary["cleanup"]["leak_free"] else EXIT_FAILED


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
