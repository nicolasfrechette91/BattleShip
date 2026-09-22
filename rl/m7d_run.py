#!/usr/bin/env python3
"""M7d orchestrator: controlled reward-v1 versus reward-v2 comparison (matrix in rl/m7d_matrix.py).

    python rl/m7d_run.py manifest                  # resolved comparison manifest -> docs/rl_reward_comparison_m7d_manifest.json
    python rl/m7d_run.py train                     # the six runs, sequential, counterbalanced order; verified runs are skipped
    python rl/m7d_run.py train --resume <run>      # continue <run>'s OWN lineage from its latest checkpoint set
    python rl/m7d_run.py evaluate                  # random baseline + every run's post-hoc evaluation plan
    python rl/m7d_run.py replay                    # best preserved artifact per run (+ every preserved clear), native stepping
    python rl/m7d_run.py status

Training goes through the unchanged M7 trainer (`python rl/train_m7.py
--config rl/configs/m7d/<run>.toml`, one fresh Python process per run, its
own kill-on-close job object). While a run trains, a monitor thread samples
every 15 s: BattleShip process count (hard limit 10), the trainer's worker
processes and their thread counts, listening loopback ports in the M7 port
blocks and their owners, memory and commit, system CPU, free disk, the user's
BattleShip.cfg.json fingerprint, and every new row of metrics/episodes.jsonl
(reward-contract closed form, one-time v2 penalty, target / tick ranges,
startup modes, anomalies). A hard alert (more than 10 BattleShip processes,
user configuration changed, disk below 5 GiB, a reward-contract or episode
invariant violated) stops the run (CTRL_BREAK -> the trainer saves
interrupted/, then a kill if needed) and the matrix. After every run the
directory is verified (checkpoints, statistics, episodes, artifacts,
lifecycle, cleanup) and the historical run tree is re-fingerprinted.

Evaluation runs after training, in this process (never inside the trainer):
frozen VecNormalize statistics, seed 12345, 5 workers with the standby
lifecycle, every episode's canonical artifact preserved.

Standard library at module level only: evaluation spawn workers re-import
this file as __mp_main__. No native RNG inspection, logging, validation,
control, comparison or hashing exists here.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import multiprocessing
import os
import platform
import shutil
import signal
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import experiment_config as ec  # noqa: E402  (no torch)
import m7d_matrix as mm  # noqa: E402  (no torch)

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_INTERRUPTED = 0, 1, 2, 130
REPO_ROOT = mm.REPO_ROOT
IS_WINDOWS = platform.system() == "Windows"
BATTLESHIP_IMAGE = "BattleShip.exe" if IS_WINDOWS else "BattleShip"
PORT_RANGE = (30000, 30000 + 5 * 250 - 1)       # the five rank blocks used by training and evaluation workers
MIN_FREE_DISK_GIB = 5.0
MONITOR_INTERVAL_S = 15.0
USER_CONFIG = REPO_ROOT / "build-us" / "Release" / "BattleShip.cfg.json"
END_REASONS = ("clear", "fall", "horizon", "lifecycle_failure")
STARTUP_MODES = ("cold_start", "standby_promoted", "cold_fallback")
TARGETS_TOTAL = 10


def log(message: str) -> None:
    print(f"[m7d {datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    return ec.sha256_file(Path(path))


def jsonl_rows(path: Path, start: int = 0) -> Tuple[List[Dict[str, Any]], int]:
    """Rows of a JSON-lines file from byte offset `start` (only complete lines); returns (rows, new offset)."""
    if not path.is_file():
        return [], start
    with open(path, "rb") as fp:
        fp.seek(start)
        data = fp.read()
    end = data.rfind(b"\n")
    if end < 0:
        return [], start
    rows = [json.loads(line) for line in data[:end + 1].decode("utf-8").splitlines() if line.strip()]
    return rows, start + end + 1


# -- system probes (Windows ctypes; standard library only) ---------------------------------------------------------

if IS_WINDOWS:
    from ctypes import wintypes

    class _PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", wintypes.WCHAR * 260)]

    class _MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
                    ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
                    ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
                    ("ullAvailExtendedVirtual", ctypes.c_uint64)]

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    _k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    _k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(_MEMORYSTATUSEX)]


def process_table() -> List[Dict[str, Any]]:
    """Every process: pid, parent pid, image name, thread count (Toolhelp32 snapshot)."""
    if not IS_WINDOWS:
        return []
    snap = _k32.CreateToolhelp32Snapshot(0x2, 0)   # TH32CS_SNAPPROCESS
    if not snap or snap == wintypes.HANDLE(-1).value:
        return []
    out: List[Dict[str, Any]] = []
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        ok = _k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            out.append({"pid": int(entry.th32ProcessID), "ppid": int(entry.th32ParentProcessID),
                        "image": entry.szExeFile, "threads": int(entry.cntThreads)})
            ok = _k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        _k32.CloseHandle(snap)
    return out


def descendants(table: Sequence[Mapping[str, Any]], root_pid: int) -> List[Mapping[str, Any]]:
    children: Dict[int, List[Mapping[str, Any]]] = {}
    for p in table:
        children.setdefault(int(p["ppid"]), []).append(p)
    out, stack, seen = [], [int(root_pid)], {int(root_pid)}
    while stack:
        for c in children.get(stack.pop(), []):
            if c["pid"] not in seen:
                seen.add(c["pid"])
                out.append(c)
                stack.append(c["pid"])
    return out


def memory_status() -> Dict[str, Any]:
    if not IS_WINDOWS:
        return {}
    m = _MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
    if not _k32.GlobalMemoryStatusEx(ctypes.byref(m)):
        return {}
    gib = 2 ** 30
    return {"load_pct": int(m.dwMemoryLoad), "avail_phys_gib": round(m.ullAvailPhys / gib, 3),
            "total_phys_gib": round(m.ullTotalPhys / gib, 3),
            "commit_used_gib": round((m.ullTotalPageFile - m.ullAvailPageFile) / gib, 3),
            "commit_limit_gib": round(m.ullTotalPageFile / gib, 3), "avail_commit_gib": round(m.ullAvailPageFile / gib, 3)}


def listening_ports(lo: int = PORT_RANGE[0], hi: int = PORT_RANGE[1]) -> List[Dict[str, Any]]:
    """Listening TCP sockets with a local port in [lo, hi] (netstat -ano), with the owning pid."""
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True, timeout=30,
                             check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return [{"error": "netstat failed"}]
    rows = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] == "TCP" and parts[3] == "LISTENING":
            try:
                port = int(parts[1].rsplit(":", 1)[1])
                pid = int(parts[4])
            except (ValueError, IndexError):
                continue
            if lo <= port <= hi:
                rows.append({"port": port, "pid": pid, "local": parts[1]})
    return rows


def user_config_fingerprint() -> Dict[str, Any]:
    from m7_runtime import file_fingerprint

    return file_fingerprint(USER_CONFIG)


def system_state(*, label: str) -> Dict[str, Any]:
    """Pre/post condition snapshot: BattleShip processes, ports in the M7 blocks, user config, disk, memory, env."""
    from m7_runtime import list_processes_named

    table = process_table()
    images = {p["pid"]: p["image"] for p in table}
    ports = listening_ports()
    for p in ports:
        p["image"] = images.get(p.get("pid"))
    disk = shutil.disk_usage(REPO_ROOT)
    ssb_env = sorted(k for k in os.environ if k.upper().startswith("SSB64_"))
    return {"label": label, "utc": utc_now(), "battleship_pids": list_processes_named(BATTLESHIP_IMAGE) or [],
            "listening_ports_in_blocks": ports,
            "battleship_listeners": [p for p in ports if p.get("image") == BATTLESHIP_IMAGE],
            "user_config": user_config_fingerprint(), "disk_free_gib": round(disk.free / 2 ** 30, 2),
            "memory": memory_status(), "ssb64_environment_variables": ssb_env}


# -- episode / artifact / checkpoint verification --------------------------------------------------------------------


def validate_episode_row(row: Mapping[str, Any], contract: Any, horizon: int) -> List[str]:
    """Invariants of one worker episode summary (training episodes.jsonl or an evaluation row normalised to it)."""
    from btt_rewards import expected_return

    p: List[str] = []
    end = row.get("end_reason")
    t, steps = row.get("targets_broken"), row.get("steps")
    tag = f"rank {row.get('rank')} episode {row.get('worker_episode')}"
    if end not in END_REASONS:
        p.append(f"{tag}: end_reason {end!r}")
    if not isinstance(t, int) or not 0 <= t <= TARGETS_TOTAL:
        p.append(f"{tag}: targets_broken {t!r}")
    if not isinstance(steps, int) or not 1 <= steps <= horizon:
        p.append(f"{tag}: steps {steps!r}")
    if p:
        return p
    fall, clear = end == "fall", end == "clear"
    obs = row.get("terminal_native_observation") or {}
    if end == "horizon" and steps != horizon:
        p.append(f"{tag}: horizon truncation after {steps} steps")
    if clear:
        if not (row.get("cleared") is True and t == TARGETS_TOTAL and row.get("completion_time_passed") is not None
                and row.get("completion_input_tick") is not None):
            p.append(f"{tag}: clear without verified completion facts")
        if obs and int(obs.get("targets_remaining", -1)) != 0:
            p.append(f"{tag}: clear with targets_remaining {obs.get('targets_remaining')}")
    elif row.get("cleared"):
        p.append(f"{tag}: cleared flag on a {end} episode")
    if fall:
        if row.get("termination_reason") != "native_failure":
            p.append(f"{tag}: fall with termination_reason {row.get('termination_reason')!r}")
        if obs and not (int(obs.get("game_status", -1)) == 5 and int(obs.get("targets_remaining", 0)) > 0):
            p.append(f"{tag}: fall observation game_status {obs.get('game_status')} targets {obs.get('targets_remaining')}")
    if obs and int(obs.get("btt_active", 0)) == 1 and int(obs.get("targets_remaining", -1)) != TARGETS_TOTAL - t:
        p.append(f"{tag}: terminal targets_remaining {obs.get('targets_remaining')} != {TARGETS_TOTAL - t}")
    if end != "lifecycle_failure":
        want = expected_return(t, steps, cleared=clear, native_failure=fall, contract=contract)
        got = float(row.get("return"))
        if abs(got - want) > 1e-6:
            p.append(f"{tag}: return {got!r} != contract closed form {want!r} ({contract.contract})")
    terms = 1 if (fall and float(contract.failure_penalty) != 0.0) else 0
    if int(row.get("failure_penalty_terms", -1)) != terms or \
            abs(float(row.get("failure_penalty_total", 0.0)) - terms * float(contract.failure_penalty)) > 1e-12:
        p.append(f"{tag}: failure penalty terms {row.get('failure_penalty_terms')} total "
                 f"{row.get('failure_penalty_total')} (expected {terms} under {contract.contract})")
    ticks = row.get("target_break_ticks")
    if ticks is not None:
        if len(ticks) != t or any(not isinstance(k, int) for k in ticks) or list(ticks) != sorted(ticks) \
                or (ticks and not (0 <= ticks[0] and ticks[-1] <= steps - 1)):
            p.append(f"{tag}: target_break_ticks {ticks} inconsistent with {t} targets / {steps} steps")
    if row.get("startup_mode") not in STARTUP_MODES:
        p.append(f"{tag}: startup_mode {row.get('startup_mode')!r}")
    return p


def eval_row_as_summary(r: Mapping[str, Any], contract: Any) -> Dict[str, Any]:
    """An evaluation.json row in the worker-summary shape validate_episode_row expects (evaluation rows carry the
    penalty term count; the total follows from the checkpoint's contract)."""
    terms = r.get("failure_penalty_terms")
    return {"rank": r.get("rank"), "worker_episode": r.get("worker_episode"), "end_reason": r.get("end_reason"),
            "targets_broken": r.get("targets_broken"), "steps": r.get("length"), "return": r.get("raw_return"),
            "cleared": r.get("cleared"), "completion_time_passed": r.get("completion_time_passed"),
            "completion_input_tick": r.get("completion_input_tick"), "termination_reason": r.get("termination_reason"),
            "failure_penalty_terms": terms,
            "failure_penalty_total": None if terms is None else int(terms) * float(contract.failure_penalty),
            "target_break_ticks": r.get("target_break_ticks"), "startup_mode": r.get("startup_mode")}


def verify_artifacts(paths: Sequence[str], contract_id: str) -> Dict[str, Any]:
    """Every preserved artifact: readable, canonical native contract, consumed ticks 0..n-1 (no hidden reset
    action), tick-0 initial observation, the run's reward contract; unique episode ids."""
    from run_artifacts import ArtifactError, read_artifact

    problems: List[str] = []
    ids = set()
    first_ticks: Dict[str, int] = {}
    modes: Dict[str, int] = {}
    for p in paths:
        d = Path(p) if Path(p).is_absolute() else REPO_ROOT / p
        try:
            art = read_artifact(d)
        except ArtifactError as exc:
            problems.append(f"{p}: {exc}")
            continue
        md = art.metadata
        if art.episode_id in ids:
            problems.append(f"{p}: duplicate episode id {art.episode_id}")
        ids.add(art.episode_id)
        ticks = [a.consumed_tick for a in art.actions]
        n = len(ticks)
        failed = md.get("status") == "failed"
        expect = list(range(n))
        if failed and ticks and ticks[-1] is None:
            ticks, expect = ticks[:-1], expect[:-1]
        if ticks != expect:
            problems.append(f"{p}: consumed ticks are not 0..{n - 1} (first {ticks[:3]})")
        if ticks:
            first_ticks[str(ticks[0])] = first_ticks.get(str(ticks[0]), 0) + 1
        init = md.get("initial_observation") or {}
        if init and (init.get("input_tick") != 0 or init.get("time_passed") != 0):
            problems.append(f"{p}: initial observation input_tick {init.get('input_tick')} time_passed {init.get('time_passed')}")
        labels = md.get("labels") or {}
        if labels.get("reward_contract") != contract_id:
            problems.append(f"{p}: reward_contract label {labels.get('reward_contract')!r} != {contract_id}")
        mode = labels.get("startup_mode")
        modes[str(mode)] = modes.get(str(mode), 0) + 1
        if md.get("action_contract") != "rlaction_native_v1":
            problems.append(f"{p}: action contract {md.get('action_contract')}")
    return {"artifacts": len(paths), "unique_ids": len(ids), "first_consumed_tick": first_ticks, "startup_modes": modes,
            "problems": problems[:50], "problem_count": len(problems), "ok": not problems}


def inspect_vecnormalize(path: Path) -> Dict[str, Any]:
    """Unpickle a saved VecNormalize (no environment) and report its normalisation flags and statistics."""
    import pickle

    import numpy as np

    with open(path, "rb") as fp:
        vn = pickle.load(fp)
    mean, var = np.asarray(vn.obs_rms.mean, dtype=np.float64), np.asarray(vn.obs_rms.var, dtype=np.float64)
    return {"norm_obs": bool(vn.norm_obs), "norm_reward": bool(vn.norm_reward), "clip_obs": float(vn.clip_obs),
            "obs_rms_count": float(vn.obs_rms.count), "obs_rms_finite": bool(np.isfinite(mean).all() and np.isfinite(var).all()),
            "ret_rms_count": float(vn.ret_rms.count),
            "note": "SB3 updates ret_rms whenever training=True even with norm_reward=False; it is never applied"}


def checkpoint_labels(total: int, interval: int) -> List[int]:
    return list(range(0, total, interval))


def checkpoint_digests(ckpt_dir: Path) -> Tuple[str, str]:
    """(policy parameter digest, obs_rms digest) of a saved checkpoint set (loads model.zip on the CPU)."""
    import pickle

    import m7_trainer as tr
    from m7_evaluation import obs_rms_digest, policy_parameter_digest

    model = tr.M7PPO.load(str(Path(ckpt_dir) / "model.zip"), device="cpu")
    with open(Path(ckpt_dir) / "vecnormalize.pkl", "rb") as fp:
        vn = pickle.load(fp)
    return policy_parameter_digest(model), obs_rms_digest(vn)


def expected_initial_from_manifest(name: str) -> Optional[Tuple[str, str]]:
    if not mm.MANIFEST_DOC.is_file():
        return None
    r = (mm.read_json(mm.MANIFEST_DOC).get("runs") or {}).get(name) or {}
    if not r.get("expected_initial_policy_digest"):
        return None
    return r["expected_initial_policy_digest"], r["expected_initial_obs_rms_digest"]


def verify_training_run(run_dir: Path, exp: Any, *, fresh: bool = True, expected_start: int = 0,
                        expected_initial: Optional[Tuple[str, str]] = None) -> Dict[str, Any]:
    """Post-run verification of one training run directory (one lineage segment)."""
    from m7_evaluation import CheckpointError, read_checkpoint_set

    problems: List[str] = []
    checks: Dict[str, Any] = {}
    run_dir = Path(run_dir)
    summary = mm.read_json(run_dir / "training_summary.json")
    run_json = mm.read_json(run_dir / "run.json")
    v = exp.values
    total = int(v["run.total_transitions"])
    contract = exp.reward
    checks["status"] = summary.get("status")
    checks["leak_free"] = bool((summary.get("cleanup") or {}).get("leak_free"))
    uc = summary.get("user_config") or {}
    checks["user_config_byte_identical"] = bool(uc.get("byte_identical"))
    checks["user_config_mtime_unchanged"] = bool(uc.get("mtime_unchanged"))
    checks["sb3_num_timesteps"] = (summary.get("timesteps") or {}).get("sb3_num_timesteps")
    checks["lineage"] = run_json.get("lineage")
    checks["seed"] = (run_json.get("seeds") or {}).get("base_seed")
    checks["reward_contract"] = (run_json.get("reward_contract") or {}).get("contract")
    block = run_json.get("experiment") or {}
    checks["semantic_fingerprint_matches"] = block.get("semantic_fingerprint") == exp.semantic_fingerprint
    checks["experiment_toml_matches_source"] = sha256_file(run_dir / "experiment.toml") == exp.source.sha256
    if checks["status"] != "completed":
        problems.append(f"status {checks['status']}")
    if not checks["leak_free"]:
        problems.append("cleanup not leak-free")
    if not (checks["user_config_byte_identical"] and checks["user_config_mtime_unchanged"]):
        problems.append("user configuration changed during the run")
    if checks["sb3_num_timesteps"] != total:
        problems.append(f"sb3_num_timesteps {checks['sb3_num_timesteps']} != {total}")
    if fresh and checks["lineage"]:
        problems.append(f"not a fresh model: lineage {checks['lineage']}")
    if checks["seed"] != int(v["run.base_seed"]):
        problems.append(f"base_seed {checks['seed']} != {v['run.base_seed']}")
    if checks["reward_contract"] != contract.contract:
        problems.append(f"reward contract {checks['reward_contract']} != {contract.contract}")
    if not checks["semantic_fingerprint_matches"] or not checks["experiment_toml_matches_source"]:
        problems.append("experiment provenance does not match the profile")
    # Checkpoint sets: every interval set of this segment + final, hashes verified, statistics frozen-loadable,
    # observation-only normalisation.
    interval = int(v["checkpoint.interval"])
    labels = [f"ckpt_{t:09d}" for t in checkpoint_labels(total, interval) if t >= expected_start and
              (t > expected_start or (fresh and bool(v["checkpoint.initial"])))]
    sets: Dict[str, Any] = {}
    for name in labels + ["final"]:
        d = run_dir / ("final" if name == "final" else f"checkpoints/{name}")
        try:
            meta = read_checkpoint_set(d)
        except (CheckpointError, OSError, ValueError) as exc:
            problems.append(f"checkpoint {name}: {exc}")
            continue
        vn = inspect_vecnormalize(d / "vecnormalize.pkl")
        entry = {"num_timesteps": meta.get("num_timesteps"), "n_updates": meta.get("n_updates"),
                 "vecnormalize": vn, "reward_contract": (meta.get("contracts") or {}).get("reward_contract"),
                 "semantic_fingerprint": (meta.get("experiment") or {}).get("semantic_fingerprint"),
                 "base_seed": (meta.get("seeds") or {}).get("base_seed"), "lifecycle": meta.get("lifecycle")}
        sets[name] = entry
        if vn["norm_reward"] or not vn["norm_obs"] or vn["clip_obs"] != float(v["ppo.vecnormalize.clip_obs"]) \
                or not vn["obs_rms_finite"]:
            problems.append(f"checkpoint {name}: VecNormalize {vn}")
        if (meta.get("vecnormalize") or {}).get("norm_reward") is not False:
            problems.append(f"checkpoint {name}: checkpoint.json norm_reward {(meta.get('vecnormalize') or {}).get('norm_reward')}")
        if entry["reward_contract"] != contract.contract or entry["semantic_fingerprint"] != exp.semantic_fingerprint \
                or entry["base_seed"] != int(v["run.base_seed"]):
            problems.append(f"checkpoint {name}: identity {entry['reward_contract']} / {entry['base_seed']}")
    if fresh and "ckpt_000000000" in sets and sets["ckpt_000000000"].get("n_updates") != 0:
        problems.append("ckpt_000000000 is not the untrained policy")
    if fresh and expected_initial is not None and "ckpt_000000000" in sets:
        got = checkpoint_digests(run_dir / "checkpoints" / "ckpt_000000000")
        checks["initial_policy"] = {"policy_digest": got[0], "obs_rms_digest": got[1],
                                    "expected_policy_digest": expected_initial[0],
                                    "expected_obs_rms_digest": expected_initial[1],
                                    "matches_fresh_construction": tuple(got) == tuple(expected_initial)}
        if tuple(got) != tuple(expected_initial):
            problems.append("ckpt_000000000 differs from a fresh model built from the profile (not a fresh start)")
    checks["checkpoint_sets"] = sets
    # Training episodes.
    rows, _ = jsonl_rows(run_dir / "metrics" / "episodes.jsonl")
    row_problems: List[str] = []
    for r in rows:
        row_problems.extend(validate_episode_row(r, contract, int(v["environment.horizon"])))
    ends: Dict[str, int] = {}
    for r in rows:
        ends[r["end_reason"]] = ends.get(r["end_reason"], 0) + 1
    checks["episodes"] = {"rows": len(rows), "end_reasons": ends, "row_problems": row_problems[:50],
                          "row_problem_count": len(row_problems),
                          "penalty_terms_total": sum(int(r.get("failure_penalty_terms") or 0) for r in rows),
                          "anomaly_events": sum(int(r.get("anomaly_events") or 0) for r in rows),
                          "startup_modes": {m: sum(1 for r in rows if r.get("startup_mode") == m) for m in STARTUP_MODES}}
    if row_problems:
        problems.append(f"{len(row_problems)} episode invariant violation(s): {row_problems[:3]}")
    if ends.get("lifecycle_failure"):
        problems.append(f"{ends['lifecycle_failure']} lifecycle failure(s) during training")
    # Artifacts.
    written = (summary.get("artifacts") or {}).get("written") or []
    art = verify_artifacts(written, contract.contract)
    checks["artifacts"] = art
    if not art["ok"]:
        problems.append(f"artifact problems: {art['problems'][:3]}")
    if art["unique_ids"] != int((summary.get("artifacts") or {}).get("preserved") or 0):
        problems.append(f"{art['unique_ids']} artifact directories != {summary['artifacts'].get('preserved')} preserved")
    # Lifecycle.
    lc = summary.get("lifecycle") or {}
    sb = lc.get("standby") or {}
    threads = sb.get("threads") or {}
    checks["lifecycle"] = {"expected_max_game_processes": lc.get("expected_max_game_processes"),
                           "observed_max_concurrent_per_worker": lc.get("observed_max_concurrent_per_worker"),
                           "reset_modes": lc.get("reset_modes"), "promotions": sb.get("promotions"),
                           "cold_fallbacks": sb.get("cold_fallbacks"), "fallback_reasons": sb.get("fallback_reasons"),
                           "standby_failed_attempts": sb.get("standby_failed_attempts"),
                           "standby_failures": sb.get("standby_failures"), "standby_lost": sb.get("standby_lost"),
                           "threads": threads}
    if (lc.get("expected_max_game_processes") != mm.MAX_GAME_PROCESSES
            or int(lc.get("observed_max_concurrent_per_worker") or 0) > 2):
        problems.append(f"process bound: {checks['lifecycle']}")
    if threads and (threads.get("started") != threads.get("joined") or threads.get("alive_at_close")):
        problems.append(f"launcher threads not all joined: {threads}")
    return {"run_dir": ec.repo_relative(run_dir), "verified_utc": utc_now(), "checks": checks, "problems": problems,
            "ok": not problems}


# -- live monitor ------------------------------------------------------------------------------------------------------


class Monitor:
    """Samples the machine while a trainer (or an evaluation) runs; raises hard alerts that stop the run."""

    def __init__(self, *, out: Path, root_pid: int, run_dir: Optional[Path] = None, contract: Any = None,
                 horizon: int = 3600, interval: float = MONITOR_INTERVAL_S, user_config: Optional[Dict[str, Any]] = None):
        self.out = Path(out)
        self.root_pid = int(root_pid)
        self.run_dir = Path(run_dir) if run_dir else None
        self.contract = contract
        self.horizon = int(horizon)
        self.interval = float(interval)
        self.user_config = user_config or user_config_fingerprint()
        self.hard_alerts: List[str] = []
        self.soft_alerts: List[str] = []
        self.samples = 0
        self.max_battleship = 0
        self.max_listeners = 0
        self.worker_threads: Dict[int, List[int]] = {}
        self.cpu: List[float] = []
        self.avail_phys: List[float] = []
        self.commit_used: List[float] = []
        self.avail_commit: List[float] = []
        self.disk_free: List[float] = []
        self.episode_rows = 0
        self.episode_ends: Dict[str, int] = {}
        self.startup_modes: Dict[str, int] = {}
        self.cold_fallbacks = 0
        self.startup_failures = 0
        self.anomalies = 0
        self.lifecycle_failures = 0
        self._offset = 0
        self._over_last = False
        self._listen_over_last = False
        self.max_exited_entries = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="m7d-monitor", daemon=True)
        self._cpu_prev: Optional[Dict[str, float]] = None
        self.out.parent.mkdir(parents=True, exist_ok=True)

    def start(self) -> "Monitor":
        from m7_runtime import system_cpu_times

        self._cpu_prev = system_cpu_times()
        self._thread.start()
        return self

    def stop(self) -> Dict[str, Any]:
        self._stop.set()
        self._thread.join(timeout=60)
        self.sample()   # final sample
        return self.summary()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.sample()
            except Exception as exc:  # noqa: BLE001 - the monitor must never kill the run by itself
                self.soft_alerts.append(f"monitor sample error: {type(exc).__name__}: {exc}")

    def _hard(self, message: str) -> None:
        if message not in self.hard_alerts:
            self.hard_alerts.append(message)
            log(f"HARD ALERT: {message}")

    def _soft(self, message: str) -> None:
        self.soft_alerts.append(message)
        if len(self.soft_alerts) <= 200:
            log(f"note: {message}")

    def sample(self) -> Dict[str, Any]:
        from m7_runtime import cpu_utilisation, system_cpu_times

        now = system_cpu_times()
        cpu = cpu_utilisation(self._cpu_prev, now)
        self._cpu_prev = now
        table = process_table()
        tree = descendants(table, self.root_pid)
        # live BattleShip processes only: an exited process whose handle is not released yet has no thread
        battleship = [p for p in table if p["image"] == BATTLESHIP_IMAGE and int(p["threads"]) > 0]
        exited_entries = sum(1 for p in table if p["image"] == BATTLESHIP_IMAGE and int(p["threads"]) == 0)
        outside = [p["pid"] for p in battleship if p["pid"] not in {q["pid"] for q in tree}]
        workers = [p for p in tree if p["image"].lower().startswith("python")]
        for w in workers:
            self.worker_threads.setdefault(w["pid"], []).append(int(w["threads"]))
        images = {p["pid"]: p["image"] for p in table}
        ports = listening_ports()
        bs_listen = [p for p in ports if images.get(p.get("pid")) == BATTLESHIP_IMAGE]
        mem = memory_status()
        disk = shutil.disk_usage(REPO_ROOT).free / 2 ** 30
        cfg = user_config_fingerprint()
        self.max_battleship = max(self.max_battleship, len(battleship))
        self.max_listeners = max(self.max_listeners, len(bs_listen))
        self.max_exited_entries = max(self.max_exited_entries, exited_entries)
        if cpu is not None:
            self.cpu.append(cpu)
        if mem:
            self.avail_phys.append(mem["avail_phys_gib"])
            self.commit_used.append(mem["commit_used_gib"])
            self.avail_commit.append(mem["avail_commit_gib"])
        self.disk_free.append(disk)
        # A count above the limit must persist over two consecutive samples (15 s apart) to stop the run; a single
        # reading is recorded as a soft note (it would be a process caught between retirement and reaping).
        over = len(battleship) > mm.MAX_GAME_PROCESSES
        if over and self._over_last:
            self._hard(f"{len(battleship)} BattleShip processes in two consecutive samples (limit {mm.MAX_GAME_PROCESSES})")
        elif over:
            self._soft(f"{len(battleship)} BattleShip processes in one sample (limit {mm.MAX_GAME_PROCESSES})")
        self._over_last = over
        if outside:
            self._soft(f"BattleShip process(es) outside the monitored tree: {outside}")
        listen_over = len(bs_listen) > mm.MAX_GAME_PROCESSES
        if listen_over and self._listen_over_last:
            self._hard(f"{len(bs_listen)} BattleShip listening sockets in the M7 port blocks (two samples)")
        elif listen_over:
            self._soft(f"{len(bs_listen)} BattleShip listening sockets in one sample")
        self._listen_over_last = listen_over
        if cfg.get("sha256") != self.user_config.get("sha256") or cfg.get("mtime_ns") != self.user_config.get("mtime_ns"):
            self._hard("the user's build-us/Release/BattleShip.cfg.json changed")
        if disk < MIN_FREE_DISK_GIB:
            self._hard(f"free disk {disk:.1f} GiB < {MIN_FREE_DISK_GIB} GiB")
        if mem and mem.get("avail_commit_gib", 99) < 0.75:
            self._soft(f"available commit {mem['avail_commit_gib']} GiB")
        for pid, series in self.worker_threads.items():
            if len(series) >= 3 and series[-1] > series[0] + 12:
                self._soft(f"worker {pid} thread count grew {series[0]} -> {series[-1]}")
        progress: Dict[str, Any] = {}
        if self.run_dir is not None:
            rows, self._offset = jsonl_rows(self.run_dir / "metrics" / "episodes.jsonl", self._offset)
            for r in rows:
                self.episode_rows += 1
                self.episode_ends[r.get("end_reason")] = self.episode_ends.get(r.get("end_reason"), 0) + 1
                mode = r.get("startup_mode")
                self.startup_modes[str(mode)] = self.startup_modes.get(str(mode), 0) + 1
                if mode == "cold_fallback" and (r.get("worker_episode") or 0) > 1:
                    self.cold_fallbacks += 1
                    self._soft(f"cold fallback: rank {r.get('rank')} episode {r.get('worker_episode')} "
                               f"{(r.get('startup') or {}).get('fallback')}")
                fails = (r.get("startup") or {}).get("failures") or []
                if fails:
                    self.startup_failures += len(fails)
                    self._soft(f"startup failure(s) before rank {r.get('rank')} episode {r.get('worker_episode')}: "
                               f"{[f.get('outcome') for f in fails]}")
                if r.get("anomaly_events"):
                    self.anomalies += int(r["anomaly_events"])
                    self._soft(f"position-delta anomaly: rank {r.get('rank')} episode {r.get('worker_episode')}")
                if r.get("end_reason") == "lifecycle_failure":
                    self.lifecycle_failures += 1
                    self._soft(f"lifecycle failure: rank {r.get('rank')} episode {r.get('worker_episode')} "
                               f"{r.get('failure_outcome')}")
                if self.contract is not None:
                    bad = validate_episode_row(r, self.contract, self.horizon)
                    if bad:
                        self._hard(f"episode invariant violated: {bad[:2]}")
            ro = self.run_dir / "metrics" / "rollouts.jsonl"
            rollouts = 0
            if ro.is_file():
                with open(ro, "rb") as fp:
                    rollouts = sum(1 for _ in fp)
            progress = {"episodes": self.episode_rows, "rollouts": rollouts}
        record = {"t": utc_now(), "cpu_util": cpu, "battleship": len(battleship), "battleship_exited": exited_entries,
                  "battleship_pids": [p["pid"] for p in battleship], "battleship_outside_tree": outside,
                  "tree_processes": len(tree), "workers": [{"pid": w["pid"], "threads": w["threads"]} for w in workers],
                  "battleship_listeners": len(bs_listen),
                  "other_listeners": [{"port": p["port"], "image": images.get(p.get("pid"))} for p in ports
                                      if images.get(p.get("pid")) != BATTLESHIP_IMAGE],
                  "memory": mem, "disk_free_gib": round(disk, 2), "user_config_sha256": cfg.get("sha256"),
                  "progress": progress, "hard_alerts": len(self.hard_alerts)}
        with open(self.out, "a", encoding="utf-8", newline="\n") as fp:
            fp.write(json.dumps(record, separators=(",", ":")) + "\n")
        self.samples += 1
        return record

    def summary(self) -> Dict[str, Any]:
        def stats(xs: Sequence[float]) -> Dict[str, Any]:
            return {} if not xs else {"n": len(xs), "mean": round(statistics.fmean(xs), 4), "min": round(min(xs), 4),
                                      "max": round(max(xs), 4)}
        return {"samples": self.samples, "interval_s": self.interval, "max_battleship_processes": self.max_battleship,
                "max_battleship_listeners": self.max_listeners, "max_exited_battleship_entries": self.max_exited_entries,
                "cpu_util": stats(self.cpu),
                "avail_phys_gib": stats(self.avail_phys), "commit_used_gib": stats(self.commit_used),
                "avail_commit_gib": stats(self.avail_commit), "disk_free_gib": stats(self.disk_free),
                "worker_threads": {str(pid): {"first": s[0], "max": max(s), "last": s[-1]}
                                   for pid, s in self.worker_threads.items()},
                "episodes_seen": self.episode_rows, "episode_ends": self.episode_ends,
                "startup_modes": self.startup_modes, "cold_fallbacks_after_first": self.cold_fallbacks,
                "startup_failures": self.startup_failures, "anomalies": self.anomalies,
                "lifecycle_failures": self.lifecycle_failures, "hard_alerts": self.hard_alerts,
                "soft_alerts": self.soft_alerts[:200], "soft_alert_count": len(self.soft_alerts)}


# -- matrix state ------------------------------------------------------------------------------------------------------

STATE_FILE = mm.STATE_DIR / "state.json"


def load_state() -> Dict[str, Any]:
    if STATE_FILE.is_file():
        return mm.read_json(STATE_FILE)
    return {"schema": "battleship_m7d_state_v1", "created_utc": utc_now(), "runs": {}, "evaluations": {}, "events": []}


def save_state(state: Dict[str, Any]) -> None:
    state["updated_utc"] = utc_now()
    mm.write_json(STATE_FILE, state)


def event(state: Dict[str, Any], kind: str, **data: Any) -> None:
    state.setdefault("events", []).append(dict({"utc": utc_now(), "event": kind}, **data))
    save_state(state)


# -- training ------------------------------------------------------------------------------------------------------------


def stop_trainer(proc: subprocess.Popen, grace_s: float = 240.0) -> str:
    """Graceful stop: CTRL_BREAK (the trainer turns it into KeyboardInterrupt, saves interrupted/ and closes its
    workers); kill after the grace period (its kill-on-close job object then removes workers and games)."""
    try:
        if IS_WINDOWS:
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.send_signal(signal.SIGINT)
    except (OSError, ValueError) as exc:
        log(f"could not signal the trainer ({exc}); killing it")
        proc.kill()
        return "killed"
    try:
        proc.wait(timeout=grace_s)
        return "interrupted"
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=60)
        return "killed_after_grace"


def train_once(*, config: Path, run_dir: Path, log_path: Path, monitor_path: Path, contract: Any, horizon: int,
               run_id: Optional[str] = None, output_root: Optional[Path] = None,
               resume_from: Optional[Path] = None) -> Dict[str, Any]:
    """One trainer process (`train_m7.py --config ...`) under the live monitor."""
    cmd = [sys.executable, "-u", str(REPO_ROOT / "rl" / "train_m7.py"), "--config", str(config)]
    if run_id:
        cmd += ["--run-id", run_id]
    if output_root:
        cmd += ["--output-root", str(output_root)]
    if resume_from:
        cmd += ["--resume-from", str(resume_from)]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0
    t0 = time.perf_counter()
    started = utc_now()
    with open(log_path, "a", encoding="utf-8", newline="\n") as lf:
        lf.write(f"# {started} {' '.join(cmd)}\n")
        lf.flush()
        proc = subprocess.Popen(cmd, cwd=str(REPO_ROOT), stdout=lf, stderr=subprocess.STDOUT, creationflags=flags)
        log(f"trainer pid {proc.pid}: {' '.join(Path(c).name if i < 2 else c for i, c in enumerate(cmd))}")
        monitor = Monitor(out=monitor_path, root_pid=proc.pid, run_dir=run_dir, contract=contract, horizon=horizon).start()
        stop_reason = None
        try:
            while proc.poll() is None:
                time.sleep(2.0)
                if monitor.hard_alerts and stop_reason is None:
                    stop_reason = "hard_alert"
                    log(f"stopping the trainer: {monitor.hard_alerts}")
                    stop_reason = f"hard_alert -> {stop_trainer(proc)}"
        except KeyboardInterrupt:
            stop_reason = f"orchestrator_interrupt -> {stop_trainer(proc)}"
        rc = proc.wait()
        mon = monitor.stop()
    return {"command": cmd, "pid": proc.pid, "exit_code": rc, "started_utc": started, "finished_utc": utc_now(),
            "wall_s": round(time.perf_counter() - t0, 1), "stop_reason": stop_reason, "monitor": mon,
            "log": ec.repo_relative(log_path), "monitor_log": ec.repo_relative(monitor_path)}


def _lineage_dirs(spec: mm.RunSpec, state: Mapping[str, Any]) -> List[Path]:
    rs = (state.get("runs") or {}).get(spec.name) or {}
    dirs = [spec.run_dir]
    for seg in rs.get("lineage") or []:
        p = REPO_ROOT / seg["run_dir"]
        if p not in dirs:
            dirs.append(p)
    return dirs


def latest_checkpoint(spec: mm.RunSpec, state: Mapping[str, Any]) -> Optional[Path]:
    """The newest resumable set of a run's lineage: an interrupted/ set, else the highest ckpt_<t>."""
    best: Optional[Tuple[int, Path]] = None
    for d in _lineage_dirs(spec, state):
        cands = []
        if (d / "interrupted" / "checkpoint.json").is_file():
            cands.append(d / "interrupted")
        cands += [c for c in (d / "checkpoints").glob("ckpt_*") if (c / "checkpoint.json").is_file()]
        for c in cands:
            t = int(mm.read_json(c / "checkpoint.json").get("num_timesteps") or 0)
            if best is None or t > best[0]:
                best = (t, c)
    return None if best is None else best[1]


def cmd_manifest(args: argparse.Namespace) -> int:
    manifest = mm.build_manifest()
    out = Path(args.out) if args.out else mm.MANIFEST_DOC
    mm.write_json(out, manifest)
    log(f"manifest written: {ec.repo_relative(out)}  ok={manifest['ok']}  problems={manifest['problems']}")
    for seed, pair in manifest["pairs"].items():
        log(f"  {seed}: resolved diffs {pair['resolved_proof']['differing_paths']} unexpected "
            f"{pair['resolved_proof']['unexpected']}; trainer diffs {pair['trainer_proof']['differing_paths']} unexpected "
            f"{pair['trainer_proof']['unexpected']}")
    return EXIT_OK if manifest["ok"] else EXIT_FAILED


def _check_manifest_current() -> Dict[str, Any]:
    """The saved manifest must describe exactly the profiles on disk (sources and fingerprints)."""
    if not mm.MANIFEST_DOC.is_file():
        raise mm.MatrixError(f"{ec.repo_relative(mm.MANIFEST_DOC)} missing: run 'python rl/m7d_run.py manifest' first")
    saved = mm.read_json(mm.MANIFEST_DOC)
    if not saved.get("ok"):
        raise mm.MatrixError(f"the saved manifest reports problems: {saved.get('problems')}")
    for spec in mm.matrix():
        exp = mm.load_run(spec)
        r = saved["runs"][spec.name]
        if (r["source_sha256"], r["semantic_fingerprint"], r["compatibility_fingerprint"]) != \
                (exp.source.sha256, exp.semantic_fingerprint, exp.compatibility_fingerprint):
            raise mm.MatrixError(f"{spec.name}: profile changed since the manifest was written")
    exe = mm.load_run(mm.matrix()[0]).executable_fingerprint()
    if exe.get("sha256") != saved["executable"].get("sha256"):
        raise mm.MatrixError("the executable changed since the manifest was written")
    return saved


def _preconditions(label: str) -> Dict[str, Any]:
    st = system_state(label=label)
    problems = []
    if st["battleship_pids"]:
        problems.append(f"BattleShip.exe already running: {st['battleship_pids']}")
    if st["battleship_listeners"]:
        problems.append(f"BattleShip listeners in the port blocks: {st['battleship_listeners']}")
    if st["disk_free_gib"] < MIN_FREE_DISK_GIB:
        problems.append(f"free disk {st['disk_free_gib']} GiB")
    if st["ssb64_environment_variables"]:
        problems.append(f"SSB64_* variables set in the orchestrator environment: {st['ssb64_environment_variables']}")
    st["problems"] = problems
    return st


def cmd_train(args: argparse.Namespace) -> int:
    manifest = _check_manifest_current()
    mm.STATE_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()
    if not (mm.STATE_DIR / "manifest.json").is_file():
        mm.write_json(mm.STATE_DIR / "manifest.json", manifest)
    snap_dir = mm.STATE_DIR / "snapshots"
    before_path = snap_dir / "historical_before.json"
    if not before_path.is_file():
        log("fingerprinting the historical run tree (runs/, M7d tree excluded, junctions not followed)")
        mm.write_json(before_path, mm.historical_snapshot())
        event(state, "historical_snapshot_before", path=ec.repo_relative(before_path))
    before = mm.read_json(before_path)
    if "user_config_before" not in state:
        state["user_config_before"] = user_config_fingerprint()
        save_state(state)
    specs = mm.matrix()
    if args.resume:
        specs = [mm.run_by_name(args.resume)]
    elif args.only:
        specs = [mm.run_by_name(args.only)]
    for spec in specs:
        rs = state["runs"].setdefault(spec.name, {"status": "pending", "lineage": []})
        if rs.get("status") == "verified":
            log(f"{spec.name}: already verified, skipped")
            continue
        exp = mm.load_run(spec)
        resume_from = None
        segment_dir = spec.run_dir
        run_id = None
        if args.resume:
            ckpt = latest_checkpoint(spec, state)
            if ckpt is None:
                raise mm.MatrixError(f"{spec.name}: no checkpoint set to resume from")
            guard = mm.resume_guard(spec, ckpt, exp)
            k = len(rs.get("lineage") or []) + 1
            run_id = f"{spec.name}_r{k}"
            segment_dir = mm.MATRIX_ROOT / run_id
            resume_from = ckpt
            event(state, "resume_guard_passed", run=spec.name, guard=guard, new_segment=run_id)
        elif spec.run_dir.exists():
            summary = spec.run_dir / "training_summary.json"
            if summary.is_file() and mm.read_json(summary).get("status") == "completed":
                log(f"{spec.name}: completed run directory found; verifying it")
                ver = verify_training_run(spec.run_dir, exp, expected_initial=expected_initial_from_manifest(spec.name))
                mm.write_json(mm.STATE_DIR / "verify" / f"{spec.name}.json", ver)
                rs.update(status="verified" if ver["ok"] else "verification_failed", verification=ver["problems"])
                save_state(state)
                if not ver["ok"]:
                    log(f"{spec.name}: verification FAILED: {ver['problems']}")
                    return EXIT_FAILED
                continue
            raise mm.MatrixError(f"{spec.name}: {ec.repo_relative(spec.run_dir)} exists without a completed summary; "
                                 f"inspect it and continue with 'train --resume {spec.name}' (never overwritten)")
        pre = _preconditions(f"before {segment_dir.name}")
        if pre["problems"]:
            rs.update(status="blocked", blocked=pre["problems"])
            save_state(state)
            log(f"{spec.name}: preconditions failed: {pre['problems']}")
            return EXIT_FAILED
        log(f"=== {spec.order_index}/6 {segment_dir.name}: seed {spec.seed}, {exp.reward.contract}, "
            f"semantic {exp.semantic_fingerprint[:16]}...")
        rs.update(status="running", started_utc=utc_now(), preconditions=pre)
        save_state(state)
        result = train_once(config=spec.config_path, run_dir=segment_dir, contract=exp.reward,
                            horizon=int(exp.values["environment.horizon"]), run_id=run_id, resume_from=resume_from,
                            log_path=mm.STATE_DIR / "logs" / f"{segment_dir.name}.log",
                            monitor_path=mm.STATE_DIR / "monitor" / f"{segment_dir.name}.jsonl")
        post = system_state(label=f"after {segment_dir.name}")
        if post["battleship_pids"]:
            time.sleep(10)
            post = system_state(label=f"after {segment_dir.name} (+10 s)")
        seg = {"run_dir": ec.repo_relative(segment_dir), "resume_from": ec.repo_relative(resume_from) if resume_from else None,
               "result": result, "postconditions": post}
        if resume_from:
            rs.setdefault("lineage", []).append(seg)
        else:
            rs["segment"] = seg
        if result["exit_code"] != 0 or result["stop_reason"]:
            rs.update(status="interrupted" if result["exit_code"] == EXIT_INTERRUPTED else "failed",
                      finished_utc=utc_now())
            save_state(state)
            log(f"{segment_dir.name}: trainer exit {result['exit_code']} stop {result['stop_reason']}; matrix stopped "
                f"(evidence kept; resume with 'train --resume {spec.name}' after diagnosis)")
            return EXIT_FAILED
        ver = verify_training_run(segment_dir, exp, fresh=resume_from is None,
                                  expected_start=0 if resume_from is None else
                                  int(mm.read_json(Path(resume_from) / "checkpoint.json")["num_timesteps"]),
                                  expected_initial=expected_initial_from_manifest(spec.name))
        after = mm.historical_snapshot()
        hist = mm.compare_snapshots(before, after)
        ver["historical_tree"] = hist
        if not hist["identical"]:
            ver["problems"].append(f"historical run tree changed: {hist}")
            ver["ok"] = False
        if post["battleship_pids"] or post["battleship_listeners"]:
            ver["problems"].append(f"leak after the run: {post['battleship_pids']} {post['battleship_listeners']}")
            ver["ok"] = False
        if post["user_config"].get("sha256") != state["user_config_before"].get("sha256") or \
                post["user_config"].get("mtime_ns") != state["user_config_before"].get("mtime_ns"):
            ver["problems"].append("user configuration changed")
            ver["ok"] = False
        mm.write_json(mm.STATE_DIR / "verify" / f"{segment_dir.name}.json", ver)
        rs.update(status="verified" if ver["ok"] else "verification_failed", finished_utc=utc_now(),
                  verification=ver["problems"])
        save_state(state)
        log(f"{segment_dir.name}: {'VERIFIED' if ver['ok'] else 'VERIFICATION FAILED'} in {result['wall_s']} s; "
            f"max BattleShip {result['monitor']['max_battleship_processes']}; problems {ver['problems'][:3]}")
        if not ver["ok"]:
            return EXIT_FAILED
    return EXIT_OK


# -- evaluation ------------------------------------------------------------------------------------------------------------


def evaluation_settings(exp: Any) -> Any:
    import m7_evaluation as ev

    v = exp.values
    return ev.EvaluationSettings(
        executable=str(exp.executable), horizon=int(v["environment.horizon"]), n_workers=exp.eval_workers,
        seed=int(v["evaluation.seed"]), extra_env=tuple(exp.extra_env), startup_attempts=int(v["environment.startup_attempts"]),
        request_timeout=float(v["environment.request_timeout_s"]), step_timeout=float(v["environment.step_timeout_s"]),
        retain_failed_cap=int(v["artifacts.retain_failed_cap"]), reward=exp.reward, experiment=exp.summary(),
        port_block_base=int(v["environment.port_block_base"]), port_block_size=int(v["environment.port_block_size"]),
        standby_preboot=exp.standby_preboot, standby_count=exp.standby_count,
        standby_wait_timeout=float(v["environment.standby_wait_timeout_s"]))


def resolve_checkpoint(spec: mm.RunSpec, state: Mapping[str, Any], label: str, t: int) -> Path:
    """Locate a planned checkpoint in the run's lineage (the original directory, then resumed segments)."""
    dirs = _lineage_dirs(spec, state)
    if label == "final":
        for d in reversed(dirs):
            if (d / "final" / "checkpoint.json").is_file():
                return d / "final"
        raise mm.MatrixError(f"{spec.name}: no final set")
    for d in dirs:
        c = d / "checkpoints" / f"ckpt_{t:09d}"
        if (c / "checkpoint.json").is_file():
            return c
    raise mm.MatrixError(f"{spec.name}: checkpoint ckpt_{t:09d} not found in {[ec.repo_relative(d) for d in dirs]}")


def verify_evaluation(result: Mapping[str, Any], contract: Any, horizon: int, plan: Mapping[str, Any]) -> Dict[str, Any]:
    problems: List[str] = []
    per_mode: Dict[str, Any] = {}
    for mode, want in (("deterministic", plan["deterministic_episodes"]), ("stochastic", plan["stochastic_episodes"])):
        r = (result.get("modes") or {}).get(mode)
        if want == 0:
            continue
        if r is None:
            problems.append(f"{mode}: missing")
            continue
        rows = r.get("episodes") or []
        fc = r.get("frozen_check") or {}
        entry = {"episodes": len(rows), "frozen_check": fc, "workers_closed_cleanly": r.get("workers_closed_cleanly"),
                 "startup_failures": r.get("startup_failures"), "preserve_all": r.get("preserve_all"),
                 "deterministic_identical": r.get("deterministic_episodes_identical"),
                 "artifacts_missing": sum(1 for e in rows if not e.get("artifact_dir")),
                 "reset_modes": (r.get("lifecycle") or {}).get("timing_reset_modes")}
        per_mode[mode] = entry
        if len(rows) != want:
            problems.append(f"{mode}: {len(rows)} episodes != {want}")
        if not (fc.get("policy_parameters_unchanged") and fc.get("obs_rms_unchanged")
                and fc.get("vecnormalize_training") is False and fc.get("vecnormalize_norm_reward") is False):
            problems.append(f"{mode}: frozen check {fc}")
        if not r.get("workers_closed_cleanly"):
            problems.append(f"{mode}: workers did not close cleanly")
        if entry["artifacts_missing"]:
            problems.append(f"{mode}: {entry['artifacts_missing']} episode(s) without a preserved artifact")
        for e in rows:
            bad = validate_episode_row(eval_row_as_summary(e, contract), contract, horizon)
            if bad:
                problems.extend(bad[:2])
    return {"per_mode": per_mode, "problems": problems[:50], "ok": not problems}


def _run_evaluation(state: Dict[str, Any], key: str, fn: Callable[[], Dict[str, Any]], out_dir: Path) -> Dict[str, Any]:
    """Run one evaluation set under the monitor. A complete set (evaluation_summary.json) is never redone; a partial
    directory left by an aborted attempt is kept, renamed <dir>__incomplete_<utc>, and the set is re-run."""
    done = out_dir / "evaluation_summary.json"
    if done.is_file():
        return mm.read_json(done)
    if out_dir.exists():
        aside = out_dir.with_name(out_dir.name + "__incomplete_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
        out_dir.rename(aside)
        event(state, "incomplete_evaluation_moved_aside", key=key, to=ec.repo_relative(aside))
    pre = _preconditions(f"before evaluation {key}")
    if pre["problems"]:
        raise mm.MatrixError(f"evaluation {key}: preconditions failed: {pre['problems']}")
    monitor = Monitor(out=mm.STATE_DIR / "monitor" / "evaluation.jsonl", root_pid=os.getpid()).start()
    t0 = time.perf_counter()
    try:
        result = fn()
    finally:
        mon = monitor.stop()
    post = system_state(label=f"after evaluation {key}")
    if post["battleship_pids"]:
        time.sleep(10)
        post = system_state(label=f"after evaluation {key} (+10 s)")
    ev_state = state.setdefault("evaluations", {}).setdefault(key, {})
    ev_state.update(wall_s=round(time.perf_counter() - t0, 1), finished_utc=utc_now(), monitor=mon,
                    leak_free=not post["battleship_pids"], out_dir=ec.repo_relative(out_dir))
    if mon["hard_alerts"] or post["battleship_pids"]:
        save_state(state)
        raise mm.MatrixError(f"evaluation {key}: monitor alerts {mon['hard_alerts']} / leaked {post['battleship_pids']}")
    save_state(state)
    return result


def cmd_evaluate(args: argparse.Namespace) -> int:
    import torch

    import m7_evaluation as ev
    from btt_parallel import m7_contracts
    from m7_runtime import install_kill_on_close_job

    torch.set_num_threads(1)   # evaluation inference in this process; recorded, identical for every model
    install_kill_on_close_job()
    state = load_state()
    only = set(args.only.split(",")) if args.only else None
    labels = set(args.labels.split(",")) if args.labels else None
    # Random baseline (shared reference; gameplay does not depend on the reward contract).
    if not args.skip_random and only is None:
        exp0 = mm.load_run(mm.matrix()[0])
        out = mm.EVAL_ROOT / "random_baseline"
        settings = evaluation_settings(exp0)
        res = _run_evaluation(state, "random_baseline",
                              lambda: ev.evaluate_random(out, settings=settings, episodes=mm.RANDOM_BASELINE_EPISODES), out)
        cross = random_cross_check(res)
        state["evaluations"]["random_baseline"]["cross_check_m7a"] = cross
        save_state(state)
        a = res["modes"]["random"]["aggregate"]
        log(f"random baseline: targets mean {a['targets_mean']} falls {a['falls']} horizon {a['horizon_truncations']}; "
            f"identical to the M7a baseline: {cross.get('identical_episodes')}/{cross.get('compared')}")
    for spec in mm.matrix():
        if only and spec.name not in only:
            continue
        rs = (state.get("runs") or {}).get(spec.name) or {}
        if rs.get("status") != "verified":
            log(f"{spec.name}: training not verified (status {rs.get('status')}); evaluation skipped")
            continue
        exp = mm.load_run(spec)
        settings = evaluation_settings(exp)
        horizon = int(exp.values["environment.horizon"])
        for plan in mm.evaluation_plan(spec, exp):
            if labels and plan["label"] not in labels and not (plan["label"].startswith("curve") and "curve" in labels):
                continue
            key = f"{spec.name}:{plan['label']}"
            ckpt = resolve_checkpoint(spec, state, plan["label"], int(plan["num_timesteps"]))
            out = mm.EVAL_ROOT / spec.name / plan["label"]
            t0 = time.perf_counter()
            res = _run_evaluation(state, key, lambda: ev.evaluate_checkpoint(
                ckpt, out, settings=settings, deterministic_episodes=int(plan["deterministic_episodes"]),
                stochastic_episodes=int(plan["stochastic_episodes"]),
                expected_contracts=m7_contracts(horizon, exp.reward), label=plan["label"], preserve_all=True), out)
            ver = verify_evaluation(res, exp.reward, horizon, plan)
            state["evaluations"][key].update(verification=ver, checkpoint=ec.repo_relative(ckpt))
            save_state(state)
            agg = {m: (res["modes"][m]["aggregate"]) for m in res["modes"]}
            log(f"{key}: " + "; ".join(f"{m} targets {a.get('targets_mean')} clears {a.get('clears')} falls {a.get('falls')} "
                                       f"horizon {a.get('horizon_truncations')}" for m, a in agg.items())
                + f" ({time.perf_counter() - t0:.0f} s){'' if ver['ok'] else ' PROBLEMS ' + str(ver['problems'][:3])}")
            if not ver["ok"]:
                return EXIT_FAILED
    return EXIT_OK


def random_cross_check(res: Mapping[str, Any]) -> Dict[str, Any]:
    """The M7d random baseline (standby lifecycle) against M7a's cold-start random baseline: same executable, seed,
    worker count and collection order, so every episode must be identical (native-action digest, targets, length)."""
    if not mm.M7A_RANDOM_BASELINE.is_file():
        return {"available": False}
    old = mm.read_json(mm.M7A_RANDOM_BASELINE)["modes"]["random"]["episodes"]
    new = res["modes"]["random"]["episodes"]
    n = min(len(old), len(new))
    same = sum(1 for a, b in zip(old[:n], new[:n]) if (a["native_action_digest"], a["targets_broken"], a["length"],
                                                      a["end_reason"]) == (b["native_action_digest"], b["targets_broken"],
                                                                           b["length"], b["end_reason"]))
    first_diff = next((i for i, (a, b) in enumerate(zip(old[:n], new[:n]))
                       if a["native_action_digest"] != b["native_action_digest"]), None)
    return {"available": True, "compared": n, "identical_episodes": same, "first_difference_index": first_diff,
            "m7a": ec.repo_relative(mm.M7A_RANDOM_BASELINE)}


# -- replay of preserved artifacts through interactive native stepping -----------------------------------------------


def objective_from_labels(md: Mapping[str, Any]) -> Tuple[int, int, int]:
    labels = md.get("labels") or {}
    if labels.get("cleared") and labels.get("completion_time_passed") is not None:
        return (1, TARGETS_TOTAL, -int(labels["completion_time_passed"]))
    return (0, int(labels.get("targets_broken") or 0), 0)


def run_artifacts(spec: mm.RunSpec, state: Mapping[str, Any]) -> List[Path]:
    dirs = [d / "workers" for d in _lineage_dirs(spec, state)] + [spec.eval_dir]
    out: List[Path] = []
    for root in dirs:
        if root.is_dir():
            out.extend(p.parent for p in root.rglob("metadata.json") if p.parent.parent.name == "artifacts")
    return sorted(out)


def replay_one(artifact_dir: Path, work: Path, *, executable: Path, extra_env: Mapping[str, str], index: int,
               expected_break_ticks: Optional[Sequence[int]] = None) -> Dict[str, Any]:
    """Resubmit an artifact's canonical native actions to a fresh BattleShip process (raw M1d client, one action
    per native tick) and compare consumed ticks, targets, terminal state and the final observation."""
    from battleship_client import BattleShipError, StepState
    from battleship_process import BattleShipEpisode, LaunchConfig
    from m7_runtime import PortCandidates, prepare_worker_runtime
    from run_artifacts import read_artifact, resubmit_actions

    art = read_artifact(artifact_dir)
    md = art.metadata
    runtime = work / "runtime"
    prepare_worker_runtime(runtime, executable)
    port, _busy = PortCandidates(0).claim()
    cfg = LaunchConfig(executable=Path(executable), working_dir=runtime, run_root=work / "episodes", port=port,
                       startup_timeout=20.0, ready_timeout=60.0, request_timeout=10.0, exit_timeout=30.0,
                       extra_env=dict(extra_env))
    (work / "episodes").mkdir(parents=True, exist_ok=True)
    per_step: List[Tuple[int, int, int]] = []
    record: Dict[str, Any] = {"artifact": ec.repo_relative(artifact_dir), "episode_id": art.episode_id,
                              "labels": {k: (md.get("labels") or {}).get(k) for k in (
                                  "run_id", "role", "rank", "worker_episode", "end_reason", "targets_broken",
                                  "cleared", "completion_time_passed", "completion_input_tick", "reward_contract",
                                  "startup_mode", "checkpoint_label")},
                              "actions": len(art.actions), "status": md.get("status")}
    episode = BattleShipEpisode(cfg, index=index)
    with episode:
        fresh = episode.start()
        record["fresh"] = {"state": fresh.state_name, "step_count": fresh.step_count, "can_step": fresh.can_step}
        client = episode.client
        initial = client.observe().observation
        record["initial_matches"] = _obs_equal(initial, md.get("initial_observation"))
        t0 = time.perf_counter()
        try:
            results = resubmit_actions(client, art.actions, on_result=lambda a, r: per_step.append(
                (int(r.consumed_tick), int(r.observation.targets_remaining), int(r.state))))
        except BattleShipError as exc:
            raise episode.classify_step_failure(exc) from exc
        record["stepping_s"] = round(time.perf_counter() - t0, 3)
        last = results[-1]
        final = last.observation
        record["submitted"] = len(results)
        record["last_consumed_tick"] = int(last.consumed_tick)
        record["final_state"] = last.state_name
        record["final_matches"] = _obs_equal(final, md.get("final_observation"))
        record["targets_broken"] = TARGETS_TOTAL - int(final.targets_remaining)
        breaks, prev = [], TARGETS_TOTAL
        for tick, remaining, _state in per_step:
            breaks.extend([tick] * max(0, prev - remaining))
            prev = remaining
        record["target_break_ticks"] = breaks
        if expected_break_ticks is not None:
            record["break_ticks_match_summary"] = list(expected_break_ticks) == breaks
        terminal = md.get("terminal") or {}
        if last.state == StepState.EPISODE_ENDED:
            done = episode.finish(last)
            record["exit_code"] = done.exit_code
            record["result"] = dict(done.result)
            record["completion_time_passed"] = int(final.time_passed)
            record["completion_input_tick"] = int(final.input_tick)
            record["cleared_natively"] = int(final.targets_remaining) == 0 and bool(done.result.get("outcome") == "clear")
        else:
            record["game_status"] = int(final.game_status)
    labels = md.get("labels") or {}
    checks = {
        "fresh": record["fresh"]["state"] == "WaitingForAction" and record["fresh"]["step_count"] == 0,
        "initial_observation": record["initial_matches"]["equal"],
        "all_actions_or_clear": record["submitted"] == len(art.actions) or record["final_state"] == "EpisodeEnded",
        "final_observation": record["final_matches"]["equal"],
        "targets": record["targets_broken"] == int(labels.get("targets_broken") or terminal.get("targets_broken") or 0),
        "end": (record["final_state"] == "EpisodeEnded") == bool(labels.get("cleared")),
    }
    if labels.get("cleared"):
        checks["completion_clocks"] = (record.get("completion_time_passed"), record.get("completion_input_tick")) == \
            (labels.get("completion_time_passed"), labels.get("completion_input_tick"))
        checks["native_clear"] = bool(record.get("cleared_natively"))
    if labels.get("end_reason") == "fall":
        checks["fall_status"] = record.get("game_status") == 5 and record["targets_broken"] < TARGETS_TOTAL
    if expected_break_ticks is not None:
        checks["break_ticks"] = bool(record.get("break_ticks_match_summary"))
    record["checks"] = checks
    record["ok"] = all(checks.values())
    return record


def _obs_equal(obs: Any, recorded: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    import dataclasses

    if recorded is None:
        return {"equal": False, "reason": "no recorded observation"}
    live = dataclasses.asdict(obs)
    diffs = {k: {"replay": live.get(k), "recorded": recorded.get(k)} for k in sorted(set(live) | set(recorded))
             if k != "host_frame" and live.get(k) != recorded.get(k)}
    return {"equal": not diffs, "diffs": diffs, "host_frame_equal": live.get("host_frame") == recorded.get("host_frame")}


def _summary_break_ticks(spec: mm.RunSpec, episode_id: str) -> Optional[List[int]]:
    """target_break_ticks of an episode from the evaluation rows (M7d instrumentation), when recorded."""
    for f in spec.eval_dir.rglob("evaluation.json") if spec.eval_dir.is_dir() else []:
        for e in mm.read_json(f).get("episodes") or []:
            if e.get("episode_id") == episode_id:
                return e.get("target_break_ticks")
    return None


def cmd_replay(args: argparse.Namespace) -> int:
    from m7_runtime import install_kill_on_close_job

    install_kill_on_close_job()
    state = load_state()
    ok = True
    for spec in mm.matrix():
        if args.only and spec.name not in args.only.split(","):
            continue
        exp = mm.load_run(spec)
        arts = run_artifacts(spec, state)
        metas = []
        for a in arts:
            md = mm.read_json(a / "metadata.json")
            metas.append((objective_from_labels(md), str(a), md))
        if not metas:
            log(f"{spec.name}: no preserved artifact")
            continue
        metas.sort(key=lambda x: x[0], reverse=True)
        chosen = [metas[0]] + [m for m in metas[1:] if m[0][0] == 1]    # the best + every preserved clear
        out_dir = spec.replay_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        records = []
        for k, (key, path, md) in enumerate(chosen):
            work = out_dir / f"replay_{k:02d}_{Path(path).name[-8:]}"
            if work.exists():
                raise mm.MatrixError(f"{work} exists (never overwritten)")
            rec = replay_one(Path(path), work, executable=exp.executable, extra_env=dict(exp.extra_env),
                             index=9000 + k, expected_break_ticks=_summary_break_ticks(spec, md.get("episode_id")))
            rec["objective_key"] = list(key)
            records.append(rec)
            ok &= rec["ok"]
            log(f"{spec.name}: replay {md.get('episode_id')} objective {key}: ok={rec['ok']} {rec['checks']}")
        mm.write_json(out_dir / "replay.json", {"run": spec.name, "artifacts_considered": len(metas),
                                                "replayed": records, "utc": utc_now()})
    return EXIT_OK if ok else EXIT_FAILED


def cmd_status(args: argparse.Namespace) -> int:  # noqa: ARG001
    state = load_state()
    for spec in mm.matrix():
        rs = state["runs"].get(spec.name) or {}
        log(f"{spec.order_index} {spec.name}: {rs.get('status', 'pending')} {rs.get('verification') or ''}")
    for k, v in (state.get("evaluations") or {}).items():
        log(f"eval {k}: {v.get('wall_s')} s ok={((v.get('verification') or {}).get('ok'))}")
    return EXIT_OK


def _raise_keyboard_interrupt(signum, frame):  # noqa: ARG001 - signal handler signature
    raise KeyboardInterrupt(f"signal {signum}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    m = sub.add_parser("manifest")
    m.add_argument("--out", default=None)
    t = sub.add_parser("train")
    t.add_argument("--only", default=None, help="one run name (default: the whole matrix in order)")
    t.add_argument("--resume", default=None, help="continue this run's own lineage from its latest checkpoint set")
    e = sub.add_parser("evaluate")
    e.add_argument("--only", default=None, help="comma-separated run names")
    e.add_argument("--labels", default=None, help="comma-separated labels: initial, final, curve (default: all)")
    e.add_argument("--skip-random", action="store_true")
    r = sub.add_parser("replay")
    r.add_argument("--only", default=None)
    sub.add_parser("status")
    args = parser.parse_args(argv)
    if IS_WINDOWS and hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _raise_keyboard_interrupt)
    try:
        return {"manifest": cmd_manifest, "train": cmd_train, "evaluate": cmd_evaluate, "replay": cmd_replay,
                "status": cmd_status}[args.command](args)
    except mm.MatrixError as exc:
        log(f"ERROR: {exc}")
        return EXIT_FAILED
    except ec.ConfigError as exc:
        log(f"ERROR: {exc}")
        return EXIT_USAGE
    except KeyboardInterrupt:
        log("interrupted")
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
