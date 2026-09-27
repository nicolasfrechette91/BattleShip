"""M7n: the registered all-three-seed reproduction check of the historical Phase K v1 control on the FINAL code and
executable (the M7l R1 / R2 / R3 procedure, reused unchanged; rl/m7h_run.py, rl/m7l_campaign.py, read-only towards
every historical file).

    R1  three curriculum-off btt_reward_v2 runs of 102,400 transitions (rl/configs/m7h/gate/m7h_r1_s{s}.toml, whose
        compatibility view equals Phase K m7g_s{s}_v1): final policy and statistics digests equal the pinned M7e =
        Phase K ckpt_000102400 digests, every episode row equal to the registered rows;
    R2  re-evaluation of the three historical final checkpoints (100 deterministic + 100 stochastic, seed 12345,
        frozen statistics, metrics on): every episode's native action digest, targets, end reason and metrics equal
        the recorded Phase K final evaluation;
    R3  the M7l decision inputs recomputed from R2 and from the historical records equal each other and the
        registered control values (deterministic facts included);
    R4  (pre-launch correction 1, 2026-09-26) the corrected gate-2 inputs of the control: the crossing candidates
        (btt_eval_metrics_v1 left entry or left-target break) of the historical final stochastic labels and of the
        R2 re-evaluation labels are identical sets, every candidate is replayed and analysed by
        rl/m7n_crossing (btt_qualified_crossing_v1), and X[v1][s] is recorded (the registered control has zero
        candidates in every seed, so X = 0 by the same criterion the v3 finals get).

If any check fails, the record says so and STOPS: the control is not reused and it is never replaced by newly
trained runs from here (that is a separate, explicit decision).

    python rl/m7n_control_check.py [--seeds 0,1,2] [--dry-run]

Writes below runs/m7n/_control/code_<fingerprint>__<utc>/ and runs/m7n/_control/control_check.json.
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
import m7h_run as hr  # noqa: E402

REPO_ROOT = RL_DIR.parent
EXE = REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"
ROOT = REPO_ROOT / "runs" / "m7n" / "_control"
RECORD = ROOT / "control_check.json"
M7L_MANIFEST = REPO_ROOT / "docs" / "rl_target2_m7l_manifest.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def log(msg: str) -> None:
    print(f"[m7n_control] {msg}", flush=True)


def code_fingerprint() -> Dict[str, Any]:
    """sha256 over every non-test rl/*.py, rl/data/*.json and the M7n / Phase K / R1 profiles (path + bytes)."""
    files = sorted(p for p in RL_DIR.glob("*.py") if not p.name.endswith("_tests.py"))
    files += sorted((RL_DIR / "data").glob("*.json"))
    files += sorted((RL_DIR / "configs" / "m7n").rglob("*.toml")) + sorted((RL_DIR / "configs" / "m7g").glob("*.toml"))
    files += sorted((RL_DIR / "configs" / "m7h" / "gate").glob("m7h_r1_s*.toml"))
    h = hashlib.sha256()
    for f in files:
        h.update(f.relative_to(REPO_ROOT).as_posix().encode("utf-8"))
        h.update(f.read_bytes())
    return {"sha256": h.hexdigest(), "files": len(files)}


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def r4_crossings(out: Path, seeds: Sequence[int], exe: Path) -> Dict[str, Any]:
    """R4: the corrected gate-2 inputs of the control, by the campaign's own code path (rl/m7n_crossing)."""
    import m7l_matrix as lm
    import m7n_crossing as xc

    flags = dict(hm.M6_FLAGS, **hm.EVAL_METRICS_FLAG)
    p: List[str] = []
    per: Dict[str, Any] = {}
    for s in seeds:
        h = lm.HistoricalControl(s)
        hist = xc.verify_crossings_in(h.eval_dir / "final", out / "r4" / f"{h.name}_historical_final", executable=exe,
                                      extra_env=flags, index_base=9900 + 20 * s)
        r2 = xc.verify_crossings_in(out / "r2" / f"{h.name}_final", out / "r4" / f"{h.name}_r2_final", executable=exe,
                                    extra_env=flags, index_base=9910 + 20 * s)
        if hist["candidate_digests"] != r2["candidate_digests"]:
            p.append(f"seed {s}: historical candidates {hist['candidate_digests']} != R2 {r2['candidate_digests']}")
        if not hist["ok"] or not r2["ok"]:
            p.append(f"seed {s}: crossing verification problems {hist['problems'][:2]} / {r2['problems'][:2]}")
        if (hist["X"], hist["candidates"]) != (r2["X"], r2["candidates"]):
            p.append(f"seed {s}: X / candidates differ: historical {hist['X']}/{hist['candidates']} R2 {r2['X']}/{r2['candidates']}")
        per[str(s)] = {k: hist[k] for k in ("candidates", "exact", "qualified_crossings", "verified_left_target_episodes",
                                           "unqualified_left_entries", "X")}
        per[str(s)].update(r2_candidates=r2["candidates"], r2_X=r2["X"], stochastic_episodes=hist["stochastic_episodes"],
                           doc=ec.repo_relative(out / "r4" / f"{h.name}_historical_final" / "crossing_verification.json"))
    return {"check": "R4", "criterion": xc.CRITERION, "flags": flags, "ok": not p, "problems": p, "per_seed": per}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    seeds = [int(s) for s in args.seeds.split(",")]
    from m7_runtime import install_kill_on_close_job, list_processes_named

    import m7l_campaign as lc

    code = code_fingerprint()
    exe_sha = sha256_file(EXE)
    manifest = json.loads(M7L_MANIFEST.read_text(encoding="utf-8"))
    out = ROOT / f"code_{code['sha256'][:12]}__{stamp()}"
    log(f"code {code['sha256'][:12]} ({code['files']} files), executable {exe_sha[:12]}, out {ec.repo_relative(out)}")
    if args.dry_run:
        log("dry run: R1 (3 x 102,400, reward v2) -> R2 (600 episodes) -> R1 vs Phase K pins -> R3 -> R4 (gate-2 inputs)")
        return 0
    if list_processes_named():
        log("BattleShip already running; refusing to start")
        return 2
    install_kill_on_close_job()
    # The M7h R1 runner pins the M7g executable; this check is BY DEFINITION on the final executable, so the pin is
    # pointed at it (a module attribute, no inherited file changes) and the actual hash is recorded here.
    hr.EXPECTED_EXE_SHA = exe_sha
    t0 = time.perf_counter()
    rc: Dict[str, int] = {}
    gates: List[Dict[str, Any]] = []
    try:
        for s in seeds:
            gate = g.launch_gate()
            gates.append(gate)
            if not gate["ok"]:
                raise RuntimeError(f"launch gate refused before R1 s{s}: {gate['problems']}")
            rc[f"r1_s{s}"] = hr.cmd_r1(argparse.Namespace(seeds=str(s), base=out))
        for s in seeds:
            rc[f"r2_s{s}"] = hr.cmd_r2(argparse.Namespace(seeds=str(s), base=out))
    except RuntimeError as exc:
        log(f"control check NOT completed (nothing recorded; not a failed reproduction): {exc}")
        return 2
    results: Dict[str, Any] = {}
    for f in sorted((out / "results").glob("r*.json")):
        results[f.stem] = {k: v for k, v in json.loads(f.read_text(encoding="utf-8")).items() if k in (
            "check", "seed", "ok", "problems", "final_digests", "m7e_digests", "rows_compared", "rows_registered",
            "compared", "wall_s", "learn_s", "throughput", "identity")}
    r1pk = lc.r1_phase_k(out, seeds, manifest)
    r3 = lc.r3_inputs(out, seeds)
    (out / "results" / "r1_phase_k.json").write_text(json.dumps(r1pk, indent=1, default=str), encoding="utf-8")
    (out / "results" / "r3_m7l.json").write_text(json.dumps(r3, indent=1, default=str), encoding="utf-8")
    r4 = r4_crossings(out, seeds, EXE)
    (out / "results" / "r4_crossings.json").write_text(json.dumps(r4, indent=1, default=str), encoding="utf-8")
    problems = [f"{k}: exit {v}" for k, v in rc.items() if v != 0] + \
        [f"{k}: {r['problems'][:2]}" for k, r in results.items() if not r.get("ok")] + \
        [f"R1 vs Phase K: {x}" for x in r1pk["problems"]] + [f"R3: {x}" for x in r3["problems"]] + \
        [f"R4: {x}" for x in r4["problems"]]
    want = {f"r1_s{s}" for s in seeds} | {f"r2_s{s}" for s in seeds}
    if not want <= set(results):
        problems.append(f"missing results {sorted(want - set(results))}")
    rec = {"schema": "m7n_control_check_v2", "utc": utc_now(), "code": code, "executable_sha256": exe_sha,
           "m7l_manifest_sha256": sha256_file(M7L_MANIFEST), "out": ec.repo_relative(out), "seeds": seeds,
           "exit_codes": rc, "results": results, "r1_phase_k": r1pk,
           "r3": {k: r3[k] for k in ("ok", "problems", "per_seed")},
           "r4": {k: r4[k] for k in ("ok", "problems", "per_seed", "criterion", "flags")}, "launch_gates": gates,
           "wall_s": round(time.perf_counter() - t0, 1), "problems": problems, "ok": not problems,
           "rule": "any problem -> the historical control is NOT reused; it is never replaced by new runs here"}
    ROOT.mkdir(parents=True, exist_ok=True)
    for p in (out / "control_check.json", RECORD):
        p.write_text(json.dumps(rec, indent=1, default=str) + "\n", encoding="utf-8")
    log(f"control check {'PASS' if rec['ok'] else 'FAIL'} in {rec['wall_s'] / 60:.1f} min {problems[:3]}")
    return 0 if rec["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
