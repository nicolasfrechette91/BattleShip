"""M7f regression chain (native change: target-identity diagnostic).

Sequential, one suite at a time, zero BattleShip.exe required before and after each, user configuration fingerprinted
around every suite, output only below runs/m7f/_regressions/<utc>/ (the M7e chain writes runs/m7e/_matrix, a
historical tree, and is therefore not reused).

M7f must not train or fine-tune any model, so every existing case that runs PPO training against BattleShip is
excluded and listed in EXCLUDED_TRAINING (a native observation/stepping change is still covered by the replay,
stepping, lifecycle, reward, recorder and vector cases that remain). Two unit cases instantiate a throwaway SB3 PPO on
an in-memory dummy environment for 16-128 steps (m5 policy_observation, m7_smoke unit_metadata): no BattleShip
process, nothing persisted; they are kept because m5 policy_observation pins the exact 15-value policy vector.

Usage: python rl/m7f_regressions.py [--only a,b] [--keep-going]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

REPO_ROOT = RL_DIR.parent
EXE = REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"
DECOMP_PINNED = "91d7b6b75e97f46c10ce2f09ac68abe1799213b6"
DECOMP_EDITED = ("decomp/src/sc/sc1pmode/sc1pbonusstage.c", "decomp/src/it/itground/ittarget.c")
M6_FLAGS = ("--child-env", "SSB64_RL_NO_RENDER=1", "--child-env", "SSB64_RAPHNET_DISABLE=1")

EXCLUDED_TRAINING = {
    "m7e_tests": ["bounded_training", "bounded_posthoc_evaluation", "bounded_replay", "bounded_cleanup"],
    "m7d_tests": ["paired_bounded_training", "bounded_posthoc_evaluation", "bounded_replay"],
    "m7c_standby_tests": ["interrupt_active_play", "interrupt_during_standby_launch", "worker_exception_both_slots",
                          "startup_contention", "v2_standby_smoke", "resume_lifecycle_game"],
    "m7_smoke": ["vector_smoke_n2", "vector_smoke_n4", "vector_smoke_n5", "checkpoint_reload", "resume_short",
                 "worker_exception_cleanup", "interrupt_cleanup"],
    "m7b_smoke": ["config_parity", "v2_ppo_smoke", "resume_allowed", "resume_rejected"],
    "m5_smoke": ["ppo_smoke", "save_load_inference"],
}
M7C_GAME = ["cold_vs_standby_replay", "terminal_paths_promotion", "shutdown_active_and_ready", "shutdown_while_starting",
            "wait_timeout_fallback", "active_timeout_then_promotion", "standby_startup_timeout_retry",
            "standby_bind_failure_retry", "standby_exhausted_cold_fallback", "standby_lost_after_ready",
            "job_object_kill_standby"]
M7_SMOKE = ["unit", "isolation_boot_replay", "fall_regression", "request_timeout_cleanup", "startup_failure_retry",
            "job_object_kill"]
M5_CASES = ["track1_mapping", "reward_synthetic", "policy_observation", "baseline_reward", "learning_reset_step",
            "failure_truncation"]

Step = Tuple[str, Union[List[str], Callable[[Path], Dict[str, Any]]], int]


def py(*args: str) -> List[str]:
    return [sys.executable, "-u", "-B", *args]


# -- hand-launched suites (M1d / M1e never launch BattleShip themselves) ---------------------------------


def _hand_launch(work: Path, extra_env: Dict[str, str]) -> Tuple[subprocess.Popen, int]:
    from battleship_client import BattleShipClient
    from m7_runtime import PortCandidates, prepare_worker_runtime

    work.mkdir(parents=True, exist_ok=True)
    runtime = work / "runtime"
    prepare_worker_runtime(runtime, EXE)  # private cwd: the user's configuration is never touched
    port, _ = PortCandidates(0).claim()
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("SSB64_")}
    env.update({"SSB64_RL_BTT": "1", "SSB64_RL_STEP": "1", "SSB64_RL_PORT": str(port),
                "SSB64_SAVE_PATH": str(work / "save.bin"), "SSB64_RL_RESULT_PATH": str(work / "result.json"),
                **extra_env})
    log = open(work / "battleship_stdout.log", "wb")
    p = subprocess.Popen([str(EXE)], cwd=str(runtime), env=env, stdin=subprocess.DEVNULL, stdout=log,
                         stderr=subprocess.STDOUT)
    deadline = time.monotonic() + 60
    while True:
        if p.poll() is not None:
            raise RuntimeError(f"BattleShip exited early with {p.returncode}")
        try:
            c = BattleShipClient(port=port, timeout=2.0)
            c.connect()
            c.ping()
            c.close()
            break
        except Exception:
            if time.monotonic() > deadline:
                p.kill()
                raise
            time.sleep(0.2)
    return p, port


def _finish(p: subprocess.Popen) -> None:
    if p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait(timeout=10)


def _run_against(work: Path, extra_env: Dict[str, str], argv: List[str], log_name: str) -> Dict[str, Any]:
    p, port = _hand_launch(work, extra_env)
    try:
        cmd = argv + ["--port", str(port)]
        r = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=600, check=False)
        (work / log_name).write_text((r.stdout or "") + (r.stderr or ""), encoding="utf-8", newline="\n")
    finally:
        _finish(p)
    result = json.loads((work / "result.json").read_text(encoding="utf-8")) if (work / "result.json").is_file() else None
    return {"exit_code": r.returncode, "tail": (r.stdout or "").strip().splitlines()[-4:], "result": result,
            "env": extra_env}


def m1e_default(root: Path) -> Dict[str, Any]:
    out = _run_against(root / "m1e_default", {}, py(str(RL_DIR / "m1e_replay_regression.py")), "m1e.log")
    ok = out["exit_code"] == 0 and (out["result"] or {}).get("completion_input_tick") == 447
    return {"ok": ok, **out}


def m1e_diag(root: Path) -> Dict[str, Any]:
    env = {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1", "SSB64_RL_TARGET_DIAG": "1"}
    out = _run_against(root / "m1e_diag", env, py(str(RL_DIR / "m1e_replay_regression.py")), "m1e.log")
    ti = (out["result"] or {}).get("target_identity") or {}
    ok = out["exit_code"] == 0 and ti.get("remaining_mask") == 0 and ti.get("break_count") == 10
    return {"ok": ok, **out}


def m1d_transport(root: Path) -> Dict[str, Any]:
    a = _run_against(root / "m1d_a", {}, py(str(RL_DIR / "m1d_smoke.py"), "errors", "single", "delayed", "disconnect"),
                     "m1d.log")
    # argparse: tests are positional, --port may follow them
    b = _run_against(root / "m1d_b", {}, py(str(RL_DIR / "m1d_smoke.py"), "baseline", "--btti",
                                            str(REPO_ROOT / "tas_input_2" / "mario_743.btti")), "m1d.log")
    return {"ok": a["exit_code"] == 0 and b["exit_code"] == 0, "neutral_tests": a, "baseline": b}


def native_authoritative(root: Path) -> Dict[str, Any]:
    import m7f_trace as tr

    nat = tr.native_tas_replay(EXE, root / "native_authoritative", diag=False)
    res = nat["result"] or {}
    ok = (nat["exit_code"] == 0 and nat["complete_line"] and nat["checksum_line"] and
          (res.get("targets_broken"), res.get("completion_time_passed"), res.get("completion_input_tick")) == (10, 446, 447)
          and "target_identity" not in res)
    return {"ok": ok, **{k: nat[k] for k in ("exit_code", "complete_line", "checksum_line", "replay_lines", "wall_s")},
            "result": res}


def chain(root: Path) -> List[Step]:
    r = str(root)
    return [
        ("m7f_tests_unit", py("rl/m7f_tests.py", "unit", "--root", f"{r}/m7f_unit"), 600),
        ("m7f_nonport_cl", py("rl/m7f_nonport_view.py", "--rev", DECOMP_PINNED, "--cl", f"{r}/nonport_cl",
                              *DECOMP_EDITED), 600),
        ("m7e_tests_unit", py("rl/m7e_tests.py", "unit", "--root", f"{r}/m7e_unit"), 1800),
        ("m7d_tests_unit", py("rl/m7d_tests.py", "unit", "--root", f"{r}/m7d_unit"), 1800),
        ("m7b_config_tests", py("rl/m7b_config_tests.py", "--root", f"{r}/m7b_config"), 1800),
        ("m7f_tests_game", py("rl/m7f_tests.py", "game", "--root", f"{r}/m7f_game"), 1800),
        ("native_authoritative", native_authoritative, 600),
        ("m1e_default", m1e_default, 900),
        ("m1e_diag", m1e_diag, 900),
        ("m1d_transport", m1d_transport, 900),
        ("m7e_existing_suites", py("rl/m7e_tests.py", "existing_suites", "--root", f"{r}/m7e_existing"), 3600),
        ("m7d_existing_suites", py("rl/m7d_tests.py", "existing_suites", "--root", f"{r}/m7d_existing"), 3600),
        ("m7c_standby_tests", py("rl/m7c_standby_tests.py", "unit", *M7C_GAME, "--root", f"{r}/m7c"), 3600),
        ("m7b_smoke_replay", py("rl/m7b_smoke.py", "tas_v1_v2", "fall_v1_v2", "truncation_v2", "--root",
                                f"{r}/m7b_smoke"), 3600),
        ("m7_smoke", py("rl/m7_smoke.py", *M7_SMOKE, "--root", f"{r}/m7_smoke"), 3600),
        ("m6_equivalence", py("rl/m6_equivalence_regression.py", "--run-dir", f"{r}/m6_equivalence", "--out",
                              f"{r}/m6_equivalence.json"), 1800),
        ("m6_raphnet_bypass", py("rl/m6_raphnet_bypass_regression.py", "--run-dir", f"{r}/m6_raphnet", "--out",
                                 f"{r}/m6_raphnet.json"), 3600),
        ("m5_smoke", py("rl/m5_smoke.py", *M5_CASES, "--run-dir", f"{r}/m5"), 1800),
        ("m5_smoke_flags", py("rl/m5_smoke.py", *M5_CASES, "--run-dir", f"{r}/m5_flags", *M6_FLAGS), 1800),
        ("m4_smoke", py("rl/m4_smoke.py", "--run-dir", f"{r}/m4"), 1800),
        ("m3_gym_smoke", py("rl/m3_gym_smoke.py", "--run-dir", f"{r}/m3"), 1800),
        ("m2_restart_regression", py("rl/m2_restart_regression.py", "--run-dir", f"{r}/m2_restart"), 1800),
        ("m2_lifecycle_smoke", py("rl/m2_lifecycle_smoke.py", "--run-dir", f"{r}/m2_lifecycle"), 1800),
    ]


def main(argv: Optional[Sequence[str]] = None) -> int:
    import m7d_run as dr
    from m7_runtime import install_kill_on_close_job

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default=None)
    ap.add_argument("--keep-going", action="store_true")
    ap.add_argument("--root", default=None)
    args = ap.parse_args(argv)
    install_kill_on_close_job()
    leaked = sorted(k for k in os.environ if k.upper().startswith("SSB64_"))
    if leaked:
        raise SystemExit(f"SSB64_* variables in the environment would leak into every child: {leaked}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = Path(args.root).resolve() if args.root else REPO_ROOT / "runs" / "m7f" / "_regressions" / stamp
    root.mkdir(parents=True, exist_ok=True)
    for sub in ("m2_lifecycle", "m2_restart", "m3", "m4", "m5", "m5_flags", "m6_equivalence", "m6_raphnet"):
        (root / sub).mkdir(exist_ok=True)
    only = set(args.only.split(",")) if args.only else None
    uc_before = dr.user_config_fingerprint()
    results: Dict[str, Any] = {}
    ok = True
    for name, how, timeout in chain(root):
        if only and name not in only:
            continue
        pre = dr.system_state(label=f"before {name}")
        if pre["battleship_pids"]:
            results[name] = {"status": "BLOCKED", "battleship_before": pre["battleship_pids"]}
            ok = False
            break
        t0 = time.perf_counter()
        entry: Dict[str, Any] = {}
        try:
            if callable(how):
                detail = how(root)
                entry = {"status": "PASS" if detail.get("ok") else "FAIL", "detail": detail}
            else:
                rc = subprocess.run(how, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=timeout,
                                    check=False)
                (root / f"{name}.log").write_text((rc.stdout or "") + (rc.stderr or ""), encoding="utf-8",
                                                  newline="\n")
                entry = {"status": "PASS" if rc.returncode == 0 else "FAIL", "exit_code": rc.returncode,
                         "command": " ".join(how[3:]), "tail": (rc.stdout or "").strip().splitlines()[-4:]}
        except Exception as exc:
            entry = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
        entry["wall_s"] = round(time.perf_counter() - t0, 1)
        post = dr.system_state(label=f"after {name}")
        uc = dr.user_config_fingerprint()
        entry.update({"battleship_after": post["battleship_pids"], "listeners_after": post["listening_ports_in_blocks"],
                      "user_config_sha256_unchanged": uc.get("sha256") == uc_before.get("sha256"),
                      "user_config_mtime_unchanged": uc.get("mtime_ns") == uc_before.get("mtime_ns")})
        if post["battleship_pids"]:
            entry["status"], entry["problem"] = "FAIL", "BattleShip processes left running"
        if not entry["user_config_sha256_unchanged"]:
            entry["status"], entry["problem"] = "FAIL", "user configuration content changed"
        results[name] = entry
        ok &= entry["status"] == "PASS"
        print(f"[m7f_regressions] {name}: {entry['status']} in {entry['wall_s']} s; cfg sha unchanged "
              f"{entry['user_config_sha256_unchanged']} mtime unchanged {entry['user_config_mtime_unchanged']}",
              flush=True)
        if entry["status"] != "PASS" and not args.keep_going:
            break
    for label, cwd in (("git_diff_check", REPO_ROOT), ("git_diff_check_decomp", REPO_ROOT / "decomp")):
        dc = subprocess.run(["git", "diff", "--check"], cwd=str(cwd), capture_output=True, text=True, timeout=120,
                            check=False)
        results[label] = {"status": "PASS" if dc.returncode == 0 else "FAIL", "exit_code": dc.returncode,
                          "output": ((dc.stdout or "") + (dc.stderr or "")).strip()[:2000]}
        ok &= dc.returncode == 0
    record = {"schema": "battleship_m7f_regressions_v1", "utc": stamp, "root": root.relative_to(REPO_ROOT).as_posix(),
              "results": results, "excluded_training_cases": EXCLUDED_TRAINING,
              "user_config_before": uc_before, "user_config_after": dr.user_config_fingerprint(),
              "passed": sum(1 for v in results.values() if v.get("status") == "PASS"), "suites": len(results), "ok": ok}
    (root / "results.json").write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"[m7f_regressions] {record['passed']}/{record['suites']} PASS -> {record['root']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
