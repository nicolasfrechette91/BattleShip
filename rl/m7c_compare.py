#!/usr/bin/env python3
"""M7c lifecycle throughput experiment: standby off vs on, and N=4 vs N=5 with standby on.

    python rl/m7c_compare.py stage1 --compare-id m7c_stage1          # N=5 off, N=5 on   (btt_reward_v1)
    python rl/m7c_compare.py stage2 --compare-id m7c_stage2          # N=4 on, N=5 on, N=5 on, N=4 on
    python rl/m7c_compare.py custom --order 5:off,5:on --compare-id x

Every run derives from the checked-in v1 profile (rl/configs/m7_mario_us_reward_v1.toml) with exactly the
M7a comparison workload: 51,200 transitions = 10 rollouts of 5120, batch 512, 10 epochs, gamma 0.999, GAE
lambda 0.995, horizon 3600, observation-only VecNormalize, unchanged network and learning rate, base seed 0,
checkpoint every 25,600, no evaluation, periodic artifact every 10 episodes. Only process_count (and the
derived n_steps) and the M7c lifecycle keys differ between runs. Runs are sequential on a quiet machine
(zero BattleShip.exe before each). The report (comparison_report.json under runs/<compare-id>/) carries the
M7a comparison columns plus the lifecycle metrics (promotions, hit rate, cold fallbacks, hidden startup time,
exposed wait, parked-standby resources, observed process concurrency) and, for stage 2, the M7a selection
rule (reliable end-to-end PPO transitions/s; within 5 % choose N=4).

Standard library at module level only (spawn workers re-import this file).
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import signal
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REPO_ROOT = Path(__file__).resolve().parent.parent
V1_TOML = REPO_ROOT / "rl" / "configs" / "m7_mario_us_reward_v1.toml"
COMPARE_WORKLOAD: Dict[str, Any] = {
    "run.mode": "train", "run.total_transitions": 51200, "checkpoint.interval": 25600, "checkpoint.initial": True,
    "evaluation.interval": 0, "evaluation.initial": False, "evaluation.final": False, "artifacts.periodic_episodes": 10,
}
STAGE1: List[Tuple[int, bool]] = [(5, False), (5, True)]
STAGE2: List[Tuple[int, bool]] = [(4, True), (5, True), (5, True), (4, True)]


def _raise_keyboard_interrupt(signum, frame):  # noqa: ARG001
    raise KeyboardInterrupt(f"signal {signum}")


def parse_order(text: str) -> List[Tuple[int, bool]]:
    order = []
    for item in text.split(","):
        n, _, mode = item.strip().partition(":")
        if mode not in ("on", "off"):
            raise argparse.ArgumentTypeError(f"{item!r}: expected N:on or N:off")
        order.append((int(n), mode == "on"))
    return order


def derive_experiment(root: Path, run_name: str, n: int, standby: bool, base_toml: Path = V1_TOML) -> Any:
    import experiment_config as ec

    base = ec.load_experiment(base_toml)
    values = dict(base.values)
    values.update(COMPARE_WORKLOAD)
    values.update({"run.name": run_name, "run.output_root": str(root), "environment.process_count": n,
                   "ppo.n_steps": int(values["ppo.rollout_size"]) // n,
                   "environment.standby_preboot": bool(standby), "environment.standby_count": 1 if standby else 0,
                   "run.notes": f"M7c lifecycle comparison: N={n}, standby {'on' if standby else 'off'}, M7a comparison workload"})
    text = ec.to_toml_text(values, header=f"derived by rl/m7c_compare.py from {base_toml.name} for {run_name}")
    cfg_dir = root / "configs"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = cfg_dir / f"{run_name}.toml"
    path.write_text(text, encoding="utf-8")
    return ec.load_experiment(path)


def lifecycle_columns(summary: Dict[str, Any]) -> Dict[str, Any]:
    lc = summary.get("lifecycle") or {}
    sb = lc.get("standby") or {}
    t = (summary.get("vector") or {}).get("timing") or {}
    return {
        "standby_preboot": (lc.get("settings") or {}).get("standby_preboot"),
        "expected_max_game_processes": lc.get("expected_max_game_processes"),
        "observed_max_concurrent_per_worker": lc.get("observed_max_concurrent_per_worker"),
        "reset_modes": lc.get("reset_modes"),
        "promotions": sb.get("promotions"),
        "hits_ready_at_reset": sb.get("hits_ready_at_reset"),
        "late_hits_waited": sb.get("late_hits_waited"),
        "cold_fallbacks": sb.get("cold_fallbacks"),
        "fallback_reasons": sb.get("fallback_reasons"),
        "hit_rate_of_auto_resets": sb.get("hit_rate_of_auto_resets"),
        "standby_startup_s": sb.get("standby_startup_s"),
        "hidden_startup_s_total": sb.get("hidden_startup_s_total"),
        "exposed_wait_s": sb.get("exposed_wait_s"),
        "exposed_wait_s_total": sb.get("exposed_wait_s_total"),
        "ready_before_promotion_s": sb.get("ready_before_promotion_s"),
        "promotion_s_total": sb.get("promotion_s_total"),
        "retire_s": sb.get("retire_s"),
        "standby_failed_attempts": sb.get("standby_failed_attempts"),
        "standby_failures": sb.get("standby_failures"),
        "standby_lost": sb.get("standby_lost"),
        "standby_wait_timeouts": sb.get("standby_wait_timeouts"),
        "threads": sb.get("threads"),
        "parked_resource": sb.get("parked_resource"),
        "per_worker_standby_wait_s": t.get("per_worker_standby_wait_s"),
        "per_worker_retire_s": t.get("per_worker_retire_s"),
        "per_worker_reset_s": t.get("per_worker_reset_s"),
        "reset_ms": t.get("reset_ms"),
        "total_game_process_memory_mib_est": _game_memory_estimate(summary, lc),
        "parent_peak_private_mib": round(((summary.get("memory") or {}).get("parent") or {}).get("peak_private_bytes", 0) / 2 ** 20, 1),
        "worker_private_mib_max": round(max((((w or {}).get("private_bytes") or 0) for w in ((summary.get("memory") or {}).get("workers") or {}).values()),
                                            default=0) / 2 ** 20, 1),
    }


def _game_memory_estimate(summary: Dict[str, Any], lc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    mem = summary.get("memory") or {}
    ws = mem.get("game_process_peak_working_set_mib_max")
    private = mem.get("game_process_private_mib_max")
    n = lc.get("expected_max_game_processes")
    if ws is None or n is None:
        return None
    return {"processes": n, "working_set_mib_sum_at_peak_per_process": round(ws * n, 1),
            "private_mib_sum_at_peak_per_process": round((private or 0) * n, 1),
            "note": "upper bound: every process at its own peak; standbys parked at tick 0 measured about 112 MiB working set"}


def run_stage(order: Sequence[Tuple[int, bool]], compare_id: str, runs_dir: Path, base_toml: Path) -> Dict[str, Any]:
    import m7_trainer as tr
    from m7_runtime import BATTLESHIP_IMAGE, list_processes_named

    root = (runs_dir / compare_id).resolve()
    if root.exists():
        raise FileExistsError(f"comparison directory already exists: {root}")
    root.mkdir(parents=True)
    rows: List[Dict[str, Any]] = []
    for k, (n, standby) in enumerate(order, 1):
        run_name = f"run{k}_n{n}_{'standby' if standby else 'cold'}"
        before = list_processes_named(BATTLESHIP_IMAGE)
        if before:
            raise RuntimeError(f"BattleShip processes present before run {k}: {before}")
        exp = derive_experiment(root, run_name, n, standby, base_toml)
        cfg = tr.config_from_experiment(exp, purpose="lifecycle_comparison")
        print(f"[m7c] run {k}/{len(order)}: N={n} standby={'on' if standby else 'off'} semantic {exp.semantic_fingerprint[:16]}", flush=True)
        summary = tr.run_training(cfg)
        row = tr.comparison_row(summary)
        row.update(lifecycle_columns(summary))
        row["semantic_fingerprint"] = exp.semantic_fingerprint
        rows.append(row)
        _write(root / "comparison_report.json", _report(order, compare_id, rows, base_toml, partial=True))
    report = _report(order, compare_id, rows, base_toml, partial=False)
    _write(root / "comparison_report.json", report)
    return report


def _pairwise(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Standby off vs on at the same N: throughput gain, exposed restart time, hidden startup, resources."""
    out: Dict[str, Any] = {}
    by_key: Dict[Tuple[int, bool], List[Dict[str, Any]]] = {}
    for r in rows:
        by_key.setdefault((int(r["n_envs"]), bool(r["standby_preboot"])), []).append(r)
    for n in sorted({k[0] for k in by_key}):
        off, on = by_key.get((n, False), []), by_key.get((n, True), [])
        if off and on:
            m_off = statistics.fmean(float(r["end_to_end_transitions_per_s"]) for r in off)
            m_on = statistics.fmean(float(r["end_to_end_transitions_per_s"]) for r in on)
            out[str(n)] = {"off_runs": [r["run_id"] for r in off], "on_runs": [r["run_id"] for r in on],
                           "end_to_end_tps_off": round(m_off, 1), "end_to_end_tps_on": round(m_on, 1),
                           "gain": round((m_on - m_off) / m_off, 4) if m_off else None,
                           "reset_vec_steps_wall_s_off": [r["reset_vec_steps_wall_s"] for r in off],
                           "reset_vec_steps_wall_s_on": [r["reset_vec_steps_wall_s"] for r in on],
                           "synchronous_stall_s_off": [r["synchronous_stall_s"] for r in off],
                           "synchronous_stall_s_on": [r["synchronous_stall_s"] for r in on],
                           "collect_s_off": [r["collect_s"] for r in off], "collect_s_on": [r["collect_s"] for r in on],
                           "optimize_wall_s_off": [r["optimize_wall_s"] for r in off], "optimize_wall_s_on": [r["optimize_wall_s"] for r in on],
                           "native_step_p50_ms": {"off": [r["native_step_latency"].get("p50_ms") for r in off],
                                                  "on": [r["native_step_latency"].get("p50_ms") for r in on]},
                           "native_step_p99_ms": {"off": [r["native_step_latency"].get("p99_ms") for r in off],
                                                  "on": [r["native_step_latency"].get("p99_ms") for r in on]},
                           "cpu_util_collect": {"off": [r["cpu_util_collect"] for r in off], "on": [r["cpu_util_collect"] for r in on]},
                           "episodes_finished": {"off": [r["episodes_finished"] for r in off], "on": [r["episodes_finished"] for r in on]},
                           "end_reasons": {"off": [r["end_reasons"] for r in off], "on": [r["end_reasons"] for r in on]}}
    return out


def _report(order: Sequence[Tuple[int, bool]], compare_id: str, rows: List[Dict[str, Any]], base_toml: Path, *, partial: bool) -> Dict[str, Any]:
    import m7_trainer as tr

    selection = None
    if not partial and {int(r["n_envs"]) for r in rows} == {4, 5} and all(r["standby_preboot"] for r in rows):
        selection = tr.select_process_count(rows)
    return {"milestone": "M7c", "compare_id": compare_id, "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "partial": partial, "order": [{"n_envs": n, "standby": s} for n, s in order], "base_profile": str(base_toml.name),
            "equal_workload": dict(COMPARE_WORKLOAD, rollout_size=5120, batch_size=512, n_epochs=10, gamma=0.999, gae_lambda=0.995,
                                   horizon=3600, base_seed=0, reward_contract="btt_reward_v1",
                                   vecnormalize="observations only, clip 10", network="MlpPolicy 64x64 tanh, lr 3e-4"),
            "runs": rows, "standby_off_vs_on": _pairwise(rows), "selection": selection,
            "selection_rule": "reliable end-to-end PPO transitions/s; within 5 % choose N=4; reliability, memory, CPU headroom and "
                              "latency tails outrank marginal throughput (rl/m7_trainer.select_process_count)"}


def _write(path: Path, data: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fp:
        json.dump(data, fp, indent=2, default=str)
        fp.write("\n")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="stage", required=True)
    for name in ("stage1", "stage2", "custom"):
        p = sub.add_parser(name)
        p.add_argument("--compare-id", required=True)
        p.add_argument("--runs-dir", default=None)
        p.add_argument("--base-toml", default=None)
        if name == "custom":
            p.add_argument("--order", type=parse_order, required=True, help="e.g. 5:off,5:on")
    args = parser.parse_args(argv)
    signal.signal(signal.SIGINT, _raise_keyboard_interrupt)
    order = {"stage1": STAGE1, "stage2": STAGE2}.get(args.stage) or args.order
    runs_dir = Path(args.runs_dir) if args.runs_dir else REPO_ROOT / "runs"
    base_toml = Path(args.base_toml) if args.base_toml else V1_TOML
    from m7_runtime import install_kill_on_close_job

    install_kill_on_close_job()
    try:
        report = run_stage(order, args.compare_id, runs_dir, base_toml)
    except KeyboardInterrupt:
        print("interrupted", flush=True)
        return 130
    print(json.dumps({"standby_off_vs_on": report["standby_off_vs_on"], "selection": report["selection"]}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
