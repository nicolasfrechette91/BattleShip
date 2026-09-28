#!/usr/bin/env python3
"""M7p: the v3 control reproduction check (R1) that qualifies the M7n v3 runs as the matched control of the M7p geometry-scaling comparison (copied from rl/m7o_control_check.py; the R1 profiles rl/configs/m7o/r1 are the M7n profiles at 102,400 and are read only).

For every seed s in 0, 1, 2: a fresh run of rl/configs/m7o/r1/m7o_r1_s{s}.toml (= the M7n v3 profile of the seed with
total_transitions 102,400, its own output root, NO exploration table) under the M7h guard, on the final code and
executable; then
  * its ckpt_000102400 (policy parameter digest and VecNormalize digest) must equal m7n_s{s}_v3/checkpoints/ckpt_000102400;
  * its episode rows (sb3_num_timesteps_seen <= 102,400) must equal the M7n run's rows on the R1 row keys (rl/m7h_matrix);
  * its ckpt_000000000 must equal the M7n initial set (fresh construction).
Any difference = the M7n runs cannot be reused as the control; this check stops and records; fresh control training is a
separate decision, never taken here.

    python rl/m7p_control_check.py [--seeds 0,1,2] [--dry-run]
Writes runs/m7p/campaign/_control/<utc>/ and runs/m7p/campaign/_control/control_check.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import experiment_config as ec  # noqa: E402
import m7d_run as dr  # noqa: E402
import m7h_guard as g  # noqa: E402
import m7h_matrix as hm  # noqa: E402

REPO_ROOT = RL_DIR.parent
ROOT = REPO_ROOT / "runs" / "m7p" / "campaign" / "_control"
RECORD = ROOT / "control_check.json"
PROFILES = {s: REPO_ROOT / "rl" / "configs" / "m7o" / "r1" / f"m7o_r1_s{s}.toml" for s in (0, 1, 2)}
M7N_RUNS = {s: REPO_ROOT / "runs" / "m7n" / "campaign" / f"m7n_s{s}_v3" for s in (0, 1, 2)}
T = 102_400


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def log(msg: str) -> None:
    print(f"[m7p_control {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def code_fingerprint() -> Dict[str, Any]:
    """sha256 over every non-test rl/*.py, rl/data/*.json and the M7n / M7o / Phase K profiles (path + bytes)."""
    files = sorted(p for p in RL_DIR.glob("*.py") if not p.name.endswith("_tests.py"))
    files += sorted((RL_DIR / "data").glob("*.json"))
    files += sorted((RL_DIR / "configs" / "m7n").rglob("*.toml")) + sorted((RL_DIR / "configs" / "m7o").rglob("*.toml"))
    files += sorted((RL_DIR / "configs" / "m7p").rglob("*.toml"))   # M7p: the campaign profiles
    files += sorted((RL_DIR / "configs" / "m7g").glob("*.toml"))
    h = hashlib.sha256()
    for f in files:
        h.update(f.relative_to(REPO_ROOT).as_posix().encode("utf-8"))
        h.update(f.read_bytes())
    return {"sha256": h.hexdigest(), "files": len(files)}


def rows_at(run_dir: Path, limit: int) -> List[Dict[str, Any]]:
    rows, _ = dr.jsonl_rows(run_dir / "metrics" / "episodes.jsonl")
    keys = hm.R_CONDITIONS["R1"]["row_keys"]
    out = [{k: r.get(k) for k in keys} for r in rows if int(r.get("sb3_num_timesteps_seen") or 0) <= limit]
    return sorted(out, key=lambda r: (int(r.get("sb3_num_timesteps_seen") or 0), r.get("rank"), r.get("worker_episode")))


def compare(seed: int, run_dir: Path) -> Dict[str, Any]:
    p: List[str] = []
    ref = M7N_RUNS[seed]
    # a run whose total is exactly one interval writes its 102,400 set as `final` (the boundary at t == total)
    got = list(dr.checkpoint_digests(run_dir / "final"))
    want = list(dr.checkpoint_digests(ref / "checkpoints" / f"ckpt_{T:09d}"))
    if got != want:
        p.append(f"final (t = {T}) digests {got} != m7n ckpt_{T:09d} {want}")
    g0 = list(dr.checkpoint_digests(run_dir / "checkpoints" / "ckpt_000000000"))
    w0 = list(dr.checkpoint_digests(ref / "checkpoints" / "ckpt_000000000"))
    if g0 != w0:
        p.append(f"ckpt_000000000 digests {g0} != m7n {w0}")
    fin = got
    r_got, r_want = rows_at(run_dir, T), rows_at(ref, T)
    if r_got != r_want:
        n = sum(1 for a, b in zip(r_got, r_want) if a != b) + abs(len(r_got) - len(r_want))
        p.append(f"episode rows differ: {len(r_got)} vs {len(r_want)} rows, {n} differing")
    return {"seed": seed, "ok": not p, "problems": p, "digests": got, "m7n_digests": want, "rows": len(r_got), "m7n_rows": len(r_want),
            "rows_sha256": hashlib.sha256(json.dumps(r_got, sort_keys=True, default=str).encode()).hexdigest()}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reuse", default=None, help="an earlier output directory: seeds already trained there are verified and compared, "
                                                  "the missing seeds are trained into it")
    args = ap.parse_args(argv)
    seeds = [int(s) for s in args.seeds.split(",")]
    from m7_runtime import install_kill_on_close_job, list_processes_named

    code = code_fingerprint()
    exe = ec.load_experiment(PROFILES[0]).executable
    exe_sha = sha256_file(exe)
    out = Path(args.reuse).resolve() if args.reuse else ROOT / stamp()
    log(f"code {code['sha256'][:12]} ({code['files']} files), executable {exe_sha[:12]}, out {ec.repo_relative(out)}")
    if args.dry_run:
        for s in seeds:
            exp = ec.load_experiment(PROFILES[s])
            m7n = ec.load_experiment(REPO_ROOT / "rl" / "configs" / "m7n" / f"m7n_s{s}_v3.toml")
            diff = sorted(ec.compare_compatibility(exp.compatibility_view(), m7n.compatibility_view()))
            log(f"seed {s}: total {exp.values['run.total_transitions']}, compatibility differences vs m7n {diff}")
        return 0
    if list_processes_named():
        log("BattleShip already running; refusing to start")
        return 2
    install_kill_on_close_job()
    t0 = time.perf_counter()
    results: Dict[str, Any] = {}
    gates = []
    for s in seeds:
        gate = g.launch_gate()
        gates.append(gate)
        if not gate["ok"]:
            log(f"launch gate refused before seed {s}: {gate['problems']} (nothing recorded)")
            return 2
        exp = ec.load_experiment(PROFILES[s])
        run_dir = out / exp.name
        tag = f"{exp.name}__{stamp()}"
        if (run_dir / "training_summary.json").is_file():
            log(f"seed {s}: reusing the run already trained at {ec.repo_relative(run_dir)}")
            res = {"exit_code": 0, "stop_kind": None, "wall_s": None, "leftover_battleship_pids": [], "monitor": {}, "reused": True}
        else:
            res = None
        res = res or g.train_guarded(config=PROFILES[s], run_dir=run_dir, log_path=out / "_guard" / "logs" / f"{tag}.log",
                              monitor_path=out / "_guard" / "monitor" / f"{tag}.jsonl", probe_path=out / "_guard" / "probe" / f"{tag}.jsonl",
                              contract=exp.reward, horizon=int(exp.values["environment.horizon"]), partial_root=out / "_partial",
                              output_root=out)
        entry: Dict[str, Any] = {"exit_code": res.get("exit_code"), "stop_kind": res.get("stop_kind"), "wall_s": res.get("wall_s"),
                                 "leftover": res.get("leftover_battleship_pids"), "hard_alerts": (res.get("monitor") or {}).get("hard_alerts")}
        if res.get("exit_code") != 0 or res.get("stop_kind") or res.get("leftover_battleship_pids"):
            entry.update(ok=False, problems=[f"training did not complete cleanly: {entry}"])
            results[f"r1_s{s}"] = entry
            log(f"seed {s}: training problem {entry}; stopping")
            break
        ver = dr.verify_training_run(run_dir, exp, fresh=True)
        entry["verification"] = {"ok": ver["ok"], "problems": ver["problems"][:10]}
        cmp = compare(s, run_dir)
        entry.update(cmp)
        if not ver["ok"]:
            entry["ok"] = False
            entry["problems"] = list(entry.get("problems") or []) + [f"verification: {ver['problems'][:3]}"]
        results[f"r1_s{s}"] = entry
        log(f"seed {s}: {'PASS' if entry['ok'] else 'FAIL ' + str(entry['problems'][:2])} ({cmp['rows']} rows)")
        if not entry["ok"]:
            break
    problems = [f"{k}: {v['problems'][:2]}" for k, v in results.items() if not v.get("ok")]
    if set(f"r1_s{s}" for s in seeds) - set(results):
        problems.append(f"missing seeds {sorted(set(f'r1_s{s}' for s in seeds) - set(results))}")
    rec = {"schema": "m7p_control_check_v1", "utc": utc_now(), "code": code, "executable_sha256": exe_sha, "out": ec.repo_relative(out),
           "seeds": seeds, "results": results, "launch_gates": gates, "wall_s": round(time.perf_counter() - t0, 1),
           "m7n_runs": {str(s): ec.repo_relative(M7N_RUNS[s]) for s in seeds}, "problems": problems, "ok": not problems,
           "rule": "any problem -> the M7n v3 runs are NOT reused as the control; fresh control training is a separate decision"}
    ROOT.mkdir(parents=True, exist_ok=True)
    for p in (out / "control_check.json", RECORD):
        p.write_text(json.dumps(rec, indent=1, default=str) + "\n", encoding="utf-8")
    log(f"control check {'PASS' if rec['ok'] else 'FAIL'} in {rec['wall_s'] / 60:.1f} min {problems[:3]}")
    return 0 if rec["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
