#!/usr/bin/env python3
"""M7u3 gate `m7u3` driver (proposed; design: docs/rl_model_planning_m7u3_proposal_2026-10-01.md as amended by
docs/rl_model_planning_m7u3_decisions_2026-10-01.md). NOT AUTHORISED TO RUN: `run` refuses without an APPROVED record
matching the current identity, and preparation creates no such record.

    python rl/m7u3_gate.py status
    python rl/m7u3_gate.py preflight [--skip-unit]   # no game: tests, pins, identity retrain, D: coverage, readiness
    python rl/m7u3_gate.py approval-template         # prints the record a reviewer would write (never writes it)
    python rl/m7u3_gate.py run                       # refused unless preflight passes
    python rl/m7u3_gate.py verify-run                # read-only post-run verification (goals re-derive, tick-0 starts, digests)

SCOPE: refit-versus-frozen test of planner-controlled reach of rare behaviour-drawn airborne points from the normal
tick-0 reset (one seed, one refit, 24 non-overlapping goals). Never reported as a landing, a wall-top reach, a crossing,
a target result or a clear. M7u1's and M7u2's registered results and their scopes are unchanged.

`run` works in phases, under one native-tick ledger (at most 197,839 ticks, identity checks and replays included) and
one 4,500 s (75-minute) cap from launch, with per-phase caps and memory caps:
- **P1 identity:** m7u1 `g26_P`, `g14_P` and M7u2 `g14_P`, `g03_P` replayed from tick 0; words, every stored row field,
  the reach tick and the action digest must equal the records.
- **Training pool** (fitting only): 540 behaviour episodes of at most 192 words from the normal reset (stream seed 1).
- **Refit:** the M7u1 pipeline from scratch on M7u1's 80 training episodes + the training pool (seed 0, 6,000 steps).
  The ONLY place an optimizer exists; afterwards constructing one raises. The refit's file and parameter digests are
  recorded before the goal pool starts.
- **Goal pool** (never fitted): 540 behaviour episodes of at most 128 words (stream seed 2), collected after the refit
  is frozen.
- **Goal selection:** 24 non-overlapping goals from the goal pool only. Fewer means INCOMPLETE.
- **Evaluation:** 24 goals x PF / PR / RC / SR from the normal tick-0 reset, no prefix, at most 128 words each (stream
  seed 3 per goal, shared by the four arms).
- **Diagnostics** (forward passes only) and **exact replays of every success.**
- **Rule** `m7u3_refit_rule_v1`, applied once.

P_retrain (M7u1 data only, training seed 1) is an offline diagnostic model: loaded from its pinned file, forward passes
only, no native arm, no planner trial. The native RNG is never inspected; seeds are Python-side only. The driver never
commits, pushes or deletes evidence.
"""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import dataclasses
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402

import m7u2_gate as gg  # noqa: E402   (frozen-model pins and loaders, readiness, decision reproduction, check_replay)
import m7u2_goals as g2  # noqa: E402
import m7u3_goals as g3  # noqa: E402
import m7u3_refit as rf  # noqa: E402
import m7u3_rule as r3  # noqa: E402
import m7u_gate as g1  # noqa: E402   (generic ledger, clock, single-env replay, planning and evidence helpers)
import m7u_planner as up  # noqa: E402
import m7u_state as us  # noqa: E402

CapStop, IntegrityStop = g1.CapStop, g1.IntegrityStop

REPO_ROOT = Path(__file__).resolve().parent.parent
RL = REPO_ROOT / "rl"
RUNS = REPO_ROOT / "runs"
GATE_ROOT = RUNS / "m7u3" / "gate"
APPROVAL = REPO_ROOT / "docs" / "rl_model_planning_m7u3_gate_approval.json"
M7U2_APPROVAL = REPO_ROOT / "docs" / "rl_model_planning_m7u2_gate_approval.json"
M7U1 = gg.M7U1
M7U2 = RUNS / "m7u2" / "gate" / "_gate"
PREP_DIR = rf.PREP_DIR
RETRAIN_PATH = PREP_DIR / "p_retrain.pt"
IDENTITY_RECORD = PREP_DIR / "identity_retrain.json"
RETRAIN_RECORD = PREP_DIR / "p_retrain.json"
ATTESTATION = PREP_DIR / "prep_attestation.json"
BACKUP_ROOT = g1.BACKUP_ROOT
EXECUTABLE = g1.EXECUTABLE
GATE = "m7u3"
N_CANDIDATES = 64
N_WORKERS = 5
ARMS = r3.ARMS                                    # PF, PR, RC, SR
ARM_MODEL = {"PF": "frozen", "PR": "refit", "SR": "refit"}
ARM_CONTROLLER = {"PF": "P", "PR": "P", "RC": "RC", "SR": "S"}
REFIT_STEPS = rf.STEPS

PIN: Dict[str, Any] = dict(gg.PIN)
PIN.update({
    "m7u2_state_sha256": "f1fc4458ac98522b329ebe9c94107d8748f82d496c5c748f0fd32f1ba36ac633",
    "m7u2_goals_sha256": "f16ac74aecc90d3ff375bcbbd5e348d266d0adb6037b08835a7091eb5f103442",
    "m7u2_pool_sha256": "b6f3a44448798eaa71091c23d20b0dad5a77778d73362fadf492533cbfa1def2",
    "m7u2_goal_digest": "1af171ccc3036b3b79c8088500e9a17e1537166e58533c36413d016ee8561307",
    "p1_m7u2": {"g14_P": {"words": 49, "reach_tick": 49,
                          "native_action_digest": "8d79e2a5beeaa654e4a4332b77cc7e92e391d7ef08499c65427c3117156285df"},
                "g03_P": {"words": 60, "reach_tick": 60,
                          "native_action_digest": "c5e23f9ab1cd5fdc572ee6a644f13b6fe0c0bdb56e36fc3555c8ad840f34a635"}},
    # P_retrain (offline diagnostic model; filled by the preparation's `retrain` run, see prep_pins())
    "retrain_model_sha256": None, "retrain_parameter_digest": None,
})
# strict from-reset open-loop figures of the FROZEN model on the 360 M7u2 pool episodes (proposal section 1.2)
STRICT_M7U2_FROZEN_MEDIANS = {16: 153, 32: 333, 64: 714, 96: 908}

TRAIN_POOL = (g3.TRAIN_EPISODES, g3.TRAIN_TICKS)
GOAL_POOL = (g3.GOAL_EPISODES, g3.GOAL_TICKS)
P1_TICKS = (sum(v["words"] for v in PIN["p1"].values()) + sum(v["words"] for v in PIN["p1_m7u2"].values()))   # 463
N_TRIALS = g3.N_GOALS * len(ARMS)                                                                          # 96
TICK_BUDGET = {"p1": P1_TICKS,                                                                             # 463
               "train_pool": g3.TRAIN_EPISODES * g3.TRAIN_TICKS,                                           # 103,680
               "goal_pool": g3.GOAL_EPISODES * g3.GOAL_TICKS,                                              # 69,120
               "eval_control": N_TRIALS * g3.BUDGET,                                                       # 12,288
               "replays": N_TRIALS * g3.BUDGET}                                                            # 12,288
TICK_BUDGET["total"] = sum(TICK_BUDGET.values())                                                           # 197,839
WALL_CAPS_S = {"p1": 120, "train_pool": 750, "refit": 900, "goal_pool": 750, "goals": 120, "evaluation": 1500,
               "replays_analysis": 900}
GLOBAL_CAP_S = 4500           # amendment 1 (2026-10-01, before any native tick): was 3600; see the amendment record
MEMORY_CAPS_MB = {"main_private": 3072, "tree_private": 9216, "tree_working_set": 4096, "system_available_min": 1024,
                  "system_commit_free_min": 2048}
MEMORY_CAP_MB = MEMORY_CAPS_MB["main_private"]
MEMORY_SAMPLE_S = 5.0
READINESS = {"min_available_mb": 4096, "min_commit_free_mb": 10240, "probe_decisions": 40, "probe_warmup": 5,
             "probe_p95_max_s": 0.5, "train_probe_steps": 20, "train_probe_median_max_s": 0.10}
REPRO = {"m7u1_decisions": len(gg.REPRO_DECISIONS), "m7u2_decisions": 32, "tolerance": 1e-3}
M7U2_REPRO = tuple((k, arm, which) for k in range(0, 24, 3) for arm in ("P", "S") for which in ("first", "middle"))
CODE_FILES = ("m7u3_goals.py", "m7u3_refit.py", "m7u3_rule.py", "m7u3_analysis.py", "m7u3_gate.py", "m7u3_tests.py",
              "m7u2_goals.py", "m7u2_rule.py", "m7u2_gate.py", "m7u2_tests.py",
              "m7u_state.py", "m7u_model.py", "m7u_planner.py", "m7u_goals.py", "m7u_rule.py", "m7u_analysis.py",
              "m7u_worker.py", "m7u_gate.py", "m7u_tests.py", "btt_parallel.py", "battleship_env.py", "run_artifacts.py",
              "m7_vec_env.py", "m7_runtime.py", "m7n_obs.py", "m7q_obs.py", "m7q_input.py", "m7g_spatial.py",
              "m7n_entity.py", "m7q_status_table.py", "m7r_commit.py", "experiment_config.py", "m7_trainer.py",
              "m7f_trace.py", "btt_learning.py", "m7s_gate.py", "tools/runs_backup.py",
              "configs/m7q/m7q_pilot_s0.toml")
M7U1_FILES = ("rl/m7u_state.py", "rl/m7u_model.py", "rl/m7u_planner.py", "rl/m7u_goals.py", "rl/m7u_rule.py",
              "rl/m7u_analysis.py", "rl/m7u_worker.py", "rl/m7u_gate.py", "rl/m7u_tests.py")


def utc() -> str:
    return g1.utc()


# -- stream keys (Python-side only; the native RNG is never touched) ----------------------------------------------------

_SEED_OF = {"train": g3.SEED_TRAIN, "pool": g3.SEED_POOL, "goal": g3.SEED_EVAL}


def stream_key(kind: str, name: Any) -> str:
    """m7u3|1|train|t###  (training pool)   m7u3|2|pool|g###  (goal pool)   m7u3|3|goal|k  (evaluation, shared by the
    four arms of goal k)."""
    return f"m7u3|{_SEED_OF[kind]}|{kind}|{name}"


def all_stream_keys() -> Dict[str, List[str]]:
    return {"train": [stream_key("train", e) for e in g3.TRAIN_ENTRIES],
            "pool": [stream_key("pool", e) for e in g3.GOAL_ENTRIES],
            "goal": [stream_key("goal", k) for k in range(g3.N_GOALS)]}


def earlier_stream_keys() -> List[str]:
    """Every stream key m7u1 and M7u2 used or probed (their identifiers are fixed by their code)."""
    out = [f"m7u1|0|collect|c{i:03d}" for i in range(92)] + [f"m7u1|0|goal|{k}" for k in range(40)]
    out += [f"m7u2|0|collect|c{i:03d}" for i in range(360)] + [f"m7u2|0|goal|{k}" for k in range(24)]
    out += [f"m7u2|probe|{i}" for i in range(64)]
    return out


# -- memory: main process + whole process tree + system -----------------------------------------------------------------


def tree_snapshot(root_pid: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Private and working-set bytes of this process and every descendant (workers, BattleShip, standbys) plus the system
    available memory / free commit. Windows only (ctypes); None elsewhere or on failure."""
    if os.name != "nt":
        return None
    try:
        from ctypes import wintypes

        class PE(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                        ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                        ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t), ("PrivateUsage", ctypes.c_size_t)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PE)]
        k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PE)]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        snap = k32.CreateToolhelp32Snapshot(0x2, 0)
        if snap in (None, wintypes.HANDLE(-1).value, -1):
            return None
        parent_of: Dict[int, int] = {}
        name_of: Dict[int, str] = {}
        try:
            pe = PE()
            pe.dwSize = ctypes.sizeof(PE)
            ok = k32.Process32FirstW(snap, ctypes.byref(pe))
            while ok:
                parent_of[int(pe.th32ProcessID)] = int(pe.th32ParentProcessID)
                name_of[int(pe.th32ProcessID)] = str(pe.szExeFile)
                ok = k32.Process32NextW(snap, ctypes.byref(pe))
        finally:
            k32.CloseHandle(snap)
        root = int(root_pid if root_pid is not None else os.getpid())
        members = {root}
        grew = True
        while grew:
            grew = False
            for pid, par in parent_of.items():
                if par in members and pid not in members:
                    members.add(pid)
                    grew = True
        private = working = main_private = 0.0
        counted = 0
        for pid in sorted(members):
            h = k32.OpenProcess(0x1000 | 0x0010, False, pid) or k32.OpenProcess(0x0400 | 0x0010, False, pid)
            if not h:
                continue
            try:
                pmc = PMC()
                pmc.cb = ctypes.sizeof(PMC)
                if k32.K32GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
                    counted += 1
                    private += pmc.PrivateUsage / 2 ** 20
                    working += pmc.WorkingSetSize / 2 ** 20
                    if pid == root:
                        main_private = pmc.PrivateUsage / 2 ** 20
            finally:
                k32.CloseHandle(h)
        sysmem = gg.memory_status() or {}
        return {"processes": len(members), "counted": counted, "tree_private_mb": round(private, 1),
                "tree_working_set_mb": round(working, 1), "main_private_mb": round(main_private, 1),
                "battleship": sum(1 for p in members if name_of.get(p, "").lower().startswith("battleship")),
                "system_available_mb": round(sysmem.get("available_mb", float("nan")), 1),
                "system_commit_free_mb": round(sysmem.get("commit_free_mb", float("nan")), 1)}
    except (OSError, ValueError, AttributeError):
        return None


def memory_breach(snap: Mapping[str, Any], caps: Mapping[str, float] = MEMORY_CAPS_MB) -> Optional[str]:
    """The first cap a snapshot violates (None when within every cap)."""
    if snap["main_private_mb"] > caps["main_private"]:
        return f"memory cap: main process private {snap['main_private_mb']:.0f} MB > {caps['main_private']} MB"
    if snap["tree_private_mb"] > caps["tree_private"]:
        return f"memory cap: process tree private {snap['tree_private_mb']:.0f} MB > {caps['tree_private']} MB"
    if snap["tree_working_set_mb"] > caps["tree_working_set"]:
        return f"memory cap: process tree working set {snap['tree_working_set_mb']:.0f} MB > {caps['tree_working_set']} MB"
    if snap["system_available_mb"] < caps["system_available_min"]:
        return f"memory cap: system available {snap['system_available_mb']:.0f} MB < {caps['system_available_min']} MB"
    if snap["system_commit_free_mb"] < caps["system_commit_free_min"]:
        return f"memory cap: system free commit {snap['system_commit_free_mb']:.0f} MB < {caps['system_commit_free_min']} MB"
    return None


class TreeSampler:
    """Samples the whole process tree every `interval` seconds into a JSON-lines log and remembers the first cap breach.
    `snapshot` is injectable (offline tests)."""

    def __init__(self, path: Path, interval: float = MEMORY_SAMPLE_S, caps: Mapping[str, float] = MEMORY_CAPS_MB,
                 snapshot: Callable[[], Optional[Dict[str, Any]]] = tree_snapshot, now: Callable[[], float] = time.monotonic):
        self.path, self.interval, self.caps, self.snapshot, self.now = Path(path), float(interval), dict(caps), snapshot, now
        self.breach: Optional[str] = None
        self.peak = {"main_private_mb": 0.0, "tree_private_mb": 0.0, "tree_working_set_mb": 0.0, "processes": 0,
                     "system_available_min_mb": float("inf"), "system_commit_free_min_mb": float("inf")}
        self.samples = 0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._t0 = now()

    def sample(self) -> Optional[Dict[str, Any]]:
        snap = self.snapshot()
        if snap is None:
            return None
        self.samples += 1
        for k in ("main_private_mb", "tree_private_mb", "tree_working_set_mb", "processes"):
            self.peak[k] = max(self.peak[k], snap[k])
        self.peak["system_available_min_mb"] = min(self.peak["system_available_min_mb"], snap["system_available_mb"])
        self.peak["system_commit_free_min_mb"] = min(self.peak["system_commit_free_min_mb"], snap["system_commit_free_mb"])
        why = memory_breach(snap, self.caps)
        if why and self.breach is None:
            self.breach = why
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(dict(snap, t_s=round(self.now() - self._t0, 1), utc=utc(), breach=why)) + "\n")
        return snap

    def start(self) -> "TreeSampler":
        def loop() -> None:
            while not self._stop.is_set():
                try:
                    self.sample()
                except Exception:       # noqa: BLE001 - a sampler fault must never stop the run
                    pass
                self._stop.wait(self.interval)

        self._thread = threading.Thread(target=loop, name="m7u3-tree-sampler", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> Dict[str, Any]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
        return {"samples": self.samples, "peak": dict(self.peak), "breach": self.breach, "interval_s": self.interval}


class Clock3(g1.Clock):
    """m7u1's clock (global cap, here GLOBAL_CAP_S = 4,500 s; per-phase wall caps; main-process memory) plus the tree sampler's
    breach. m7u1's stop message still reads "60-minute cap reached (<elapsed> s)"; that text is m7u1's, unchanged."""

    def __init__(self, *a: Any, sampler: Optional[TreeSampler] = None, **k: Any):
        super().__init__(*a, **k)
        self.sampler = sampler

    def check(self, force_memory: bool = False) -> None:
        super().check(force_memory)
        if self.sampler is not None and self.sampler.breach:
            raise CapStop(self.sampler.breach)


# -- records read (never written): m7u1, M7u2 ----------------------------------------------------------------------------


def sha256_file(p: Path) -> str:
    return g1.sha256_file(p)


def load_m7u2_records(root: Path = M7U2, *, check_pins: bool = True) -> Dict[str, Any]:
    for name, key in (("state.json", "m7u2_state_sha256"), ("goals.json", "m7u2_goals_sha256"),
                      ("pool.json", "m7u2_pool_sha256")):
        if check_pins and sha256_file(root / name) != PIN[key]:
            raise IntegrityStop(f"M7u2 record {name} differs from its pinned sha256")
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    goals = json.loads((root / "goals.json").read_text(encoding="utf-8"))
    pool = json.loads((root / "pool.json").read_text(encoding="utf-8"))
    if check_pins and goals["digest"] != PIN["m7u2_goal_digest"]:
        raise IntegrityStop("M7u2 goal digest differs from its pin")
    return {"state": state, "goals": goals["goals"], "pool": pool["episodes"],
            "trials": {t["entry"]: t for t in state["phases"]["evaluation"]["trials"]}}


def m7u2_pool_episodes(rec: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """The 360 M7u2 pool episodes (rows, words), in pool.json order: used for forward passes only."""
    import m7u_worker as uw

    out = []
    for e in rec["pool"]:
        side = uw.read_sidecar(g1.resolve(e["artifact_dir"]))
        out.append({"entry": e["entry"], "episode_id": e["episode_id"], "rows": side["rows"], "words": side["words"],
                    "fell": e["termination_reason"] == "native_failure"})
    return out


def p1_expected_m7u2(rec: Mapping[str, Any], row0: np.ndarray,
                     artifact_words: Callable[[Any], List[Tuple[int, int]]] = g1.artifact_track1_words,
                     read_sidecar: Optional[Callable[[Any], Mapping[str, Any]]] = None) -> List[Dict[str, Any]]:
    """M7u2's two pinned tick-0 trials as replay entries (t = 0, no prefix)."""
    import m7u_worker as uw

    read_sidecar = read_sidecar or (lambda d: uw.read_sidecar(g1.resolve(d)))
    start = [None if np.isnan(v) else float(v) for v in row0]
    out = []
    for name, pin in PIN["p1_m7u2"].items():
        t = rec["trials"][name]
        g = rec["goals"][int(t["goal_k"])]
        words = artifact_words(t["artifact_dir"])
        side = read_sidecar(t["artifact_dir"])
        if len(words) != pin["words"] or [tuple(w) for w in side["words"]] != words:
            raise IntegrityStop(f"P1 m7u2 {name}: artifact words differ from the sidecar or the pin")
        if t["reach_tick"] != pin["reach_tick"] or t["native_action_digest"] != pin["native_action_digest"]:
            raise IntegrityStop(f"P1 m7u2 {name}: M7u2 record differs from the pin")
        out.append({"entry": f"p1_m7u2_{name}", "kind": "trial", "t": 0, "budget": g2.BUDGET, "goal": [g["x"], g["y"]],
                    "prefix": [], "expected_start_row": start, "words": [list(w) for w in words],
                    "expected": {"rows": side["rows"], "reach_tick": pin["reach_tick"],
                                 "native_action_digest": pin["native_action_digest"]}})
    return out


def reproduce_m7u2_decisions(fz: gg.Frozen, rec: Mapping[str, Any], root: Path = M7U2) -> Dict[str, Any]:
    """Re-score 32 recorded M7u2 tick-0 decisions (8 goals x P / S x first / middle) with the frozen model: the chosen
    candidate must be identical and every score within the tolerance."""
    import torch

    import m7u_model as um

    out = []
    with torch.inference_mode():
        for k, arm, which in M7U2_REPRO:
            with np.load(root / "trials" / f"g{k:02d}_{arm}.npz") as z:
                i = 0 if which == "first" else len(z["chosen"]) // 2
                gk = k if arm == "P" else g2.scrambled(k)
                goal = (rec["goals"][gk]["x"], rec["goals"][gk]["y"])
                n = z["candidates"].shape[1]
                roll = um.rollout(fz.model, fz.ctx, torch.tensor(np.repeat(z["root_row"][i][None], n, 0)),
                                  torch.tensor(np.repeat(z["root_hist"][i][None], n, 0)),
                                  torch.tensor(z["candidates"][i].astype(np.int64)))
                s, _reach = up.score(roll.x, roll.y, roll.air, roll.fall_at, goal, g2.BUDGET - int(z["at_tick"][i]))
                s = s.numpy()
                out.append({"trial": f"g{k:02d}_{arm}", "decision": int(z["decision"][i]),
                            "chosen_equal": int(np.argmin(s)) == int(z["chosen"][i]),
                            "max_abs_diff": float(np.max(np.abs(s - z["scores"][i])))})
    ok = all(r["chosen_equal"] for r in out) and max(r["max_abs_diff"] for r in out) <= REPRO["tolerance"]
    return {"ok": ok, "decisions": len(out), "chosen_equal": sum(r["chosen_equal"] for r in out),
            "max_abs_diff": max(r["max_abs_diff"] for r in out), "tolerance": REPRO["tolerance"]}


# -- P_retrain (offline diagnostic model) and the preparation's pins -----------------------------------------------------


def prep_pins() -> Dict[str, Any]:
    """The pins the preparation recorded for P_retrain (file sha256 and parameter digest), read from its record. The
    record is attested (sha256 of the refit code at training time) by `prep_attestation.json`."""
    if not RETRAIN_RECORD.is_file():
        return {}
    rec = json.loads(RETRAIN_RECORD.read_text(encoding="utf-8"))
    return {"retrain_model_sha256": rec["model_sha256"], "retrain_parameter_digest": rec["parameter_digest"]}


def retrain_pins() -> Dict[str, Any]:
    p = prep_pins()
    return {"model_sha256": PIN["retrain_model_sha256"] or p.get("retrain_model_sha256"),
            "parameter_digest": PIN["retrain_parameter_digest"] or p.get("retrain_parameter_digest")}


def load_retrain(frozen: gg.Frozen, path: Path = RETRAIN_PATH, *, pins: Optional[Mapping[str, Any]] = None) -> gg.Frozen:
    """P_retrain with its pins checked, gradients off, eval mode. It shares the frozen model's vocabulary (same data) and
    clock track; its context is built from them."""
    import m7u_model as um

    pins = dict(pins or retrain_pins())
    if not pins.get("model_sha256") or not pins.get("parameter_digest"):
        raise IntegrityStop("P_retrain pins are missing (the preparation has not trained it)")
    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != pins["model_sha256"]:
        raise IntegrityStop(f"{path}: P_retrain file differs from its pin")
    model, vocab, _meta = um.load(path)
    if um.parameter_digest(model) != pins["parameter_digest"]:
        raise IntegrityStop("P_retrain parameter digest differs from its pin")
    if {"S": vocab.S, "V3": vocab.V3, "V4": vocab.V4} != PIN["vocab"] or model.members != PIN["members"]:
        raise IntegrityStop("P_retrain vocabulary or member count differs from the frozen model's")
    for p in model.parameters():
        p.requires_grad_(False)
    model.eval()
    return gg.Frozen(model=model, vocab=vocab, ctx=um.make_context(vocab, us.static_world_pinned(), frozen.track),
                     track=frozen.track)


def attestation_status() -> Tuple[bool, str]:
    """The identity retrain and the P_retrain training were run by the CURRENT refit code, reproduced the frozen
    parameters bit for bit, and the retrain is pinned."""
    if not IDENTITY_RECORD.is_file() or not RETRAIN_RECORD.is_file() or not ATTESTATION.is_file():
        return False, "preparation records missing (identity retrain, P_retrain, attestation)"
    ident = json.loads(IDENTITY_RECORD.read_text(encoding="utf-8"))
    rec = json.loads(RETRAIN_RECORD.read_text(encoding="utf-8"))
    att = json.loads(ATTESTATION.read_text(encoding="utf-8"))
    if not ident.get("bit_exact") or ident.get("parameter_digest") != PIN["parameter_digest"]:
        return False, "the identity retrain did not reproduce the frozen parameters bit for bit"
    if ident.get("parameter_diff", {}).get("max_abs_diff") != 0.0:
        return False, "the identity retrain has a nonzero parameter difference"
    if att.get("refit_code_sha256") != sha256_file(RL / "m7u3_refit.py"):
        return False, "m7u3_refit.py changed after the identity retrain / P_retrain were run"
    if att.get("identity_record_sha256") != sha256_file(IDENTITY_RECORD) or att.get("retrain_record_sha256") != sha256_file(RETRAIN_RECORD):
        return False, "a preparation record changed after it was attested"
    if att.get("retrain_model_sha256") != sha256_file(RETRAIN_PATH) or rec["model_sha256"] != att.get("retrain_model_sha256"):
        return False, "the P_retrain file changed after it was attested"
    if rec["steps"] != REFIT_STEPS or rec["seed"] != rf.RETRAIN_SEED or not rec["differs_from_frozen"]:
        return False, "P_retrain was not trained as specified (6,000 steps, seed 1, a different model)"
    return True, "attested"


# -- D: records ----------------------------------------------------------------------------------------------------------


def d_records_digest(root: Path = BACKUP_ROOT, folders: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """sha256 over the top-level record and manifest files (everything except the `runs` copy) of the base and every
    increment. With `folders`, only those folders (so a later increment does not change a pinned digest)."""
    out: Dict[str, str] = {}
    if Path(root).is_dir():
        for d in sorted(p for p in Path(root).iterdir() if p.is_dir()):
            if folders is not None and d.name not in folders:
                continue
            h = hashlib.sha256()
            for f in sorted(p for p in d.iterdir() if p.is_file()):
                h.update(f.name.encode("utf-8"))
                h.update(sha256_file(f).encode("ascii"))
            out[d.name] = h.hexdigest()
    return {"folders": sorted(out), "digest": hashlib.sha256(json.dumps(out, sort_keys=True).encode("utf-8")).hexdigest(),
            "per_folder": out}


# -- readiness ---------------------------------------------------------------------------------------------------------


def training_probe(frozen: gg.Frozen, *, steps: int = READINESS["train_probe_steps"], warmup: int = 3, n: int = 4000,
                   seed: int = 99) -> Dict[str, float]:
    """Median seconds of one refit-sized training step (3 members x batch 1,024) on a THROWAWAY model with synthetic
    data: never the frozen model, P_retrain or the refit. Constructs an optimizer outside the refit phase (a registered,
    probe-only one)."""
    import torch

    import m7u_model as um

    g = torch.Generator().manual_seed(seed)
    v = frozen.vocab
    dense = torch.randn(n, um.DENSE, generator=g)
    s = torch.randint(1, v.S, (n,), generator=g)
    allowed = np.nonzero(v.h3_mask[0])[0]
    tg = {"s": s, "h2": torch.tensor([int(np.nonzero(v.h2_mask[int(i)])[0][0]) for i in s]),
          "h3": torch.tensor([int(allowed[i % len(allowed)]) for i in range(n)]), "h4": torch.randint(0, v.V4, (n,), generator=g),
          "ga": torch.zeros(n, dtype=torch.long), "tapx": torch.randint(0, 5, (n,), generator=g),
          "tapy": torch.randint(0, 5, (n,), generator=g), "z": torch.randint(0, us.N_Z_LEVELS, (n,), generator=g),
          "masks": torch.zeros(n, 14), "h6": 0.5 * dense[:, :len(um.H6_FIELDS)].clone(),
          "breaks": torch.zeros(n, us.TARGET_COUNT), "live": torch.ones(n, us.TARGET_COUNT), "fall": torch.zeros(n)}
    ts = um.TransitionSet(dense=dense, cur=torch.randint(0, v.S, (n,), generator=g),
                          prev=torch.randint(0, v.S, (n,), generator=g), targets=tg, episode_of=np.arange(n) // 100,
                          n_episodes=n // 100)
    model = um.DynamicsEnsemble(v, members=3, seed=seed)
    boot = [np.arange(n)] * 3
    times = []
    for i in range(warmup + steps):
        t = time.perf_counter()
        rf.train_loop(model, frozen.ctx, ts, boot, steps=1, seed=seed + i, log_every=10 ** 9)
        if i >= warmup:
            times.append(time.perf_counter() - t)
    return {"steps": steps, "median_s": float(np.median(times)), "p95_s": float(np.quantile(times, 0.95))}


def readiness(probe: Callable[[], Mapping[str, float]], memory: Callable[[], Optional[Mapping[str, float]]] = gg.memory_status,
              train_probe: Optional[Callable[[], Mapping[str, float]]] = None) -> Dict[str, Any]:
    rep = gg.readiness(probe, memory)
    problems = list(rep["problems"])
    tp = dict(train_probe()) if train_probe is not None else None
    if tp is not None and tp["median_s"] > READINESS["train_probe_median_max_s"]:
        problems.append(f"training step median {tp['median_s']:.3f} s > {READINESS['train_probe_median_max_s']} s")
    return {"ok": not problems, "problems": problems, "memory": rep["memory"], "timing": rep["timing"], "train_probe": tp,
            "thresholds": dict(READINESS)}


# -- identity, approval, preflight -------------------------------------------------------------------------------------


def m7u2_approval_code() -> Dict[str, str]:
    if not M7U2_APPROVAL.is_file():
        return {}
    return dict(json.loads(M7U2_APPROVAL.read_text(encoding="utf-8")).get("code") or {})


def identity() -> Dict[str, Any]:
    import m7u_model as um  # noqa: F401

    rp = retrain_pins()
    dr = d_records_digest()
    return {"gate": GATE, "scope": g3.SCOPE, "rule": r3.RULE_ID, "rule_sha256": r3.rule_digest(),
            "goal_contract": g3.GOAL_CONTRACT, "goal_contract_sha256": g3.contract_digest(),
            "planner_sha256": up.contract_digest(), "state_sha256": us.contract_digest(),
            "frozen_model": {k: PIN[k] for k in ("model_sha256", "parameter_digest", "vocab", "members", "track_sha256")},
            "retrain_model": {"role": "offline diagnostic only: no native arm, no planner trial", "seed": rf.RETRAIN_SEED,
                              "steps": REFIT_STEPS, "data": "m7u1 training episodes only", **rp},
            "refit": {"contract": rf.CONTRACT, "code_sha256": sha256_file(RL / "m7u3_refit.py"), "seed": rf.TRAIN_SEED,
                      "steps": REFIT_STEPS, "batch": rf.BATCH, "lr": rf.LR, "members": rf.MEMBERS, "from_scratch": True,
                      "bootstrap": "stratified (m7u1's 80 episodes, then the training pool); empty pool == m7u1's",
                      "data": f"m7u1 training episodes (80) + training pool t000..t{g3.TRAIN_EPISODES - 1:03d}",
                      "identity_retrain": "bit-exact against the frozen parameter digest (prep_attestation)"},
            "m7u1_sources": {k: PIN[k] for k in ("m7u1_state_sha256", "m7u1_goals_sha256", "m7u1_collection_sha256",
                                                 "reference_digest", "tick0_row_digest")},
            "m7u2_sources": {k: PIN[k] for k in ("m7u2_state_sha256", "m7u2_goals_sha256", "m7u2_pool_sha256",
                                                 "m7u2_goal_digest")},
            "m7u2_approval_code": m7u2_approval_code(),
            "world_digest": PIN["world_digest"], "p1": {"m7u1": PIN["p1"], "m7u2": PIN["p1_m7u2"]},
            "executable_sha256": sha256_file(EXECUTABLE) if EXECUTABLE.is_file() else None,
            "code": {f"rl/{f}": sha256_file(RL / f) for f in CODE_FILES if (RL / f).is_file()},
            "arms": list(ARMS), "n_candidates": N_CANDIDATES, "stream_seeds": dict(_SEED_OF),
            "training_pool": list(TRAIN_POOL), "goal_pool": list(GOAL_POOL), "n_goals": g3.N_GOALS,
            "non_overlap_span": g3.NON_OVERLAP_SPAN, "budget": g3.BUDGET, "tick_budget": TICK_BUDGET,
            "wall_caps_s": WALL_CAPS_S, "global_cap_s": GLOBAL_CAP_S, "memory_caps_mb": MEMORY_CAPS_MB,
            "memory_sample_s": MEMORY_SAMPLE_S, "readiness": READINESS, "replays": "every success of every arm",
            "repro": REPRO, "d_records": {"folders": dr["folders"], "digest": dr["digest"]}}


def _norm(v: Any) -> str:
    return json.dumps(v, sort_keys=True, default=str)


def approval_status() -> Tuple[bool, str]:
    if not APPROVAL.is_file():
        return False, f"no approval record at {APPROVAL.relative_to(REPO_ROOT)} (the gate is not authorised)"
    rec = json.loads(APPROVAL.read_text(encoding="utf-8"))
    if not str(rec.get("approval", "")).startswith("APPROVED"):
        return False, f"approval record says {rec.get('approval')!r}"
    want = identity()
    diffs = [k for k in want if k not in ("code", "d_records") and _norm(rec.get(k)) != _norm(want[k])]
    diffs += [f"code:{f}" for f, h in want["code"].items() if (rec.get("code") or {}).get(f) != h]
    pinned = (rec.get("d_records") or {})
    if pinned.get("folders"):
        if d_records_digest(folders=pinned["folders"])["digest"] != pinned.get("digest"):
            diffs.append("d_records")
    else:
        diffs.append("d_records")
    if diffs:
        return False, f"approval record does not match the current identity: {diffs[:8]}"
    return True, "approved"


def m7u1_files_equal_head() -> List[str]:
    r = subprocess.run(["git", "diff", "--name-only", "HEAD", "--", *M7U1_FILES], capture_output=True, text=True, cwd=REPO_ROOT)
    return [ln for ln in r.stdout.split() if ln]


def m7u2_files_unchanged() -> List[str]:
    return [f for f, h in m7u2_approval_code().items() if (REPO_ROOT / f).is_file() and sha256_file(REPO_ROOT / f) != h]


def stream_key_problems() -> List[str]:
    keys = all_stream_keys()
    problems = []
    names = list(keys)
    for i, a in enumerate(names):
        if len(set(keys[a])) != len(keys[a]):
            problems.append(f"duplicate stream keys in {a}")
        for b in names[i + 1:]:
            if set(keys[a]) & set(keys[b]):
                problems.append(f"stream keys of {a} and {b} overlap")
    earlier = set(earlier_stream_keys())
    for a in names:
        if set(keys[a]) & earlier:
            problems.append(f"stream keys of {a} overlap an m7u1 / M7u2 key")
    return problems


def preflight(*, run_unit: bool = True, probe: bool = True) -> Dict[str, Any]:
    problems: List[str] = []
    rep: Dict[str, Any] = {"utc": utc(), "scope": g3.SCOPE}
    if GATE_ROOT.parent.exists():
        problems.append(f"{GATE_ROOT.parent.relative_to(REPO_ROOT)} exists (never overwritten)")
    if run_unit:
        for cmd, key in (([sys.executable, str(RL / "m7u3_tests.py"), "unit"], "unit_suite"),
                         ([sys.executable, str(RL / "m7u3_rule.py"), "self-test"], "rule_self_test")):
            r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)
            rep[key] = (r.stdout.strip().splitlines() or [r.stderr[-300:]])[-1:]
            if r.returncode != 0:
                problems.append(f"{key} failed")
    fz = row0 = None
    try:
        src = gg.load_m7u1_sources()
        row0 = gg.tick0_row(src)
        ref = gg.reference(src)
        if g2.row_digest(row0) != PIN["tick0_row_digest"] or ref.digest() != PIN["reference_digest"]:
            problems.append("tick-0 record or chance reference differs from the pin")
        fz = gg.load_frozen(src)
        rep["frozen_model"] = "pins ok"
        rep["decision_reproduction_m7u1"] = gg.reproduce_decisions(fz, src)
        rec2 = load_m7u2_records()
        rep["decision_reproduction_m7u2"] = reproduce_m7u2_decisions(fz, rec2)
        for k in ("decision_reproduction_m7u1", "decision_reproduction_m7u2"):
            if not rep[k]["ok"]:
                problems.append(f"the frozen model does not reproduce the recorded decisions ({k})")
        retrain = load_retrain(fz)
        rep["retrain_model"] = {"pins": "ok", "parameter_digest": retrain_pins()["parameter_digest"][:16]}
    except (IntegrityStop, OSError, KeyError, ValueError) as exc:
        problems.append(f"frozen / retrain / record identity: {type(exc).__name__}: {exc}")
    ok_att, why_att = attestation_status()
    rep["attestation"] = why_att
    if not ok_att:
        problems.append(f"preparation attestation: {why_att}")
    bad = m7u1_files_equal_head()
    if bad:
        problems.append(f"m7u1 files differ from HEAD: {bad}")
    bad2 = m7u2_files_unchanged()
    if bad2:
        problems.append(f"M7u2 files differ from the M7u2 approval's hashes: {bad2[:5]}")
    problems += [f"stream keys: {p}" for p in stream_key_problems()]
    if up.contract_digest() != PIN["planner_sha256"] or us.contract_digest() != PIN["state_sha256"]:
        problems.append("planner or state contract differs from m7u1")
    if g1.PINNED_WORLD_DIGEST != PIN["world_digest"]:
        problems.append("pinned stage table differs from m7u1")
    if not EXECUTABLE.is_file() or sha256_file(EXECUTABLE) != PIN["executable_sha256"]:
        problems.append("executable missing or differs from the m7u1 executable")
    cov = g1.combined_coverage()
    rep["backup"] = {k: cov.get(k) for k in ("ok", "reason", "source_files", "uncovered", "increments", "skipped")}
    if not cov.get("ok"):
        problems.append(f"backup prerequisite not met: {cov.get('reason')}")
    dr = d_records_digest()
    rep["d_records"] = {"folders": dr["folders"], "digest": dr["digest"]}
    procs = g1.game_processes()
    if procs:
        problems.append(f"BattleShip already running: {procs}")
    ok, why = approval_status()
    rep["approval"] = why
    if not ok:
        problems.append(why)
    if probe and fz is not None and row0 is not None:
        rep["readiness"] = readiness(lambda: gg.timing_probe(fz, row0), train_probe=lambda: training_probe(fz))
        if not rep["readiness"]["ok"]:
            problems += [f"readiness: {p}" for p in rep["readiness"]["problems"]]
    rep["problems"] = problems
    rep["ok"] = not problems
    return rep


# -- controllers, entries ----------------------------------------------------------------------------------------------


def pool_stream_kind(entry: str) -> str:
    return "train" if re.fullmatch(r"t\d{3}", entry) else "pool"


def controller_for(entry: Mapping[str, Any], n_candidates: int, goals: Optional[Sequence[g2.Goal]] = None) -> up.Controller:
    if entry["kind"] == "collect":
        return up.Controller(arm="collect", stream_key=stream_key(pool_stream_kind(entry["entry"]), entry["entry"]),
                             n_candidates=n_candidates)
    arm, k = entry["arm"], int(entry["goal_k"])
    key = stream_key("goal", k)                   # shared by the four arms of a goal (common random numbers)
    if arm == "RC":
        return up.Controller(arm="RC", stream_key=key, n_candidates=n_candidates, budget=int(entry["budget"]))
    target = goals[k] if arm in ("PF", "PR") else goals[g3.scrambled(k, len(goals))]
    return up.Controller(arm=ARM_CONTROLLER[arm], stream_key=key, n_candidates=n_candidates, goal=(target.x, target.y),
                         budget=int(entry["budget"]))


def pool_configs(n_workers: int, entries: Sequence[str]) -> Dict[int, Dict[str, Any]]:
    cfg: Dict[int, Dict[str, Any]] = {r: {"mode": "collect", "phase": "pool", "entries": []} for r in range(n_workers)}
    for i, name in enumerate(entries):
        cfg[i % n_workers]["entries"].append({"entry": name, "kind": "collect"})
    return cfg


def evaluation_configs(goals: Sequence[g2.Goal], n_workers: int, row0: np.ndarray) -> Dict[int, Dict[str, Any]]:
    """Every trial starts at the normal tick-0 reset: t = 0, an empty prefix, the tick-0 record as its start row."""
    cfg: Dict[int, Dict[str, Any]] = {r: {"mode": "trial", "phase": "evaluation", "entries": []} for r in range(n_workers)}
    start = [None if np.isnan(v) else float(v) for v in row0]
    order = []
    for g in goals:
        rot = g.k % len(ARMS)
        order += [(g, a) for a in list(ARMS)[rot:] + list(ARMS)[:rot]]
    for i, (g, arm) in enumerate(order):
        cfg[i % n_workers]["entries"].append({
            "entry": f"e{g.k:02d}_{arm}", "kind": "trial", "arm": arm, "goal_k": g.k, "t": 0, "budget": g3.BUDGET,
            "goal": [g.x, g.y], "prefix": [], "expected_start_row": start})
    return cfg


def validate_entries(configs: Mapping[int, Mapping[str, Any]], phase: str, goals: Optional[Sequence[g2.Goal]],
                     row0: np.ndarray, pool_entries: Optional[Sequence[str]] = None) -> None:
    """Refuse (before anything is launched) any evaluation entry that is not a normal tick-0 trial, and any pool entry
    that is not a plain behaviour episode of the registered set."""
    start = [None if np.isnan(v) else float(v) for v in row0]
    for c in configs.values():
        for e in c["entries"]:
            if phase in ("train_pool", "goal_pool"):
                if e.get("kind") != "collect" or set(e) - {"entry", "kind"}:
                    raise ValueError(f"pool entry {e.get('entry')}: not a plain behaviour episode")
                if pool_entries is not None and e["entry"] not in pool_entries:
                    raise ValueError(f"pool entry {e.get('entry')}: not one of the registered entries")
                continue
            if e.get("kind") != "trial" or int(e.get("t", -1)) != 0 or list(e.get("prefix", [None])) != []:
                raise ValueError(f"evaluation entry {e.get('entry')}: prefixes and archived starts are not allowed")
            if e.get("expected_start_row") != start or int(e.get("budget", 0)) != g3.BUDGET:
                raise ValueError(f"evaluation entry {e.get('entry')}: not the tick-0 record or not the 128-word budget")
            g = goals[int(e["goal_k"])]
            if list(e["goal"]) != [g.x, g.y] or e.get("arm") not in ARMS:
                raise ValueError(f"evaluation entry {e.get('entry')}: the scored goal must be g itself")


# -- the drive loop (normal tick-0 starts only) ------------------------------------------------------------------------


def drive(venv: Any, configs: Mapping[int, Mapping[str, Any]], *, phase: str, ledger: g1.Ledger, clock: g1.Clock,
          n_candidates: int, row0: np.ndarray, goals: Optional[Sequence[g2.Goal]] = None,
          models: Optional[Mapping[str, Tuple[Any, Any]]] = None, track: Optional[us.ClockTrack] = None,
          pool_entries: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """Drive every worker through its entries from the normal tick-0 reset. Before a task's first word its reset row
    must equal the tick-0 record; every step record must report k = words submitted (input_tick = consumed + 1).
    `models` maps 'frozen' / 'refit' to (model, ctx); each arm plans with its own model, batched per model."""
    ledger_key = {"train_pool": "train_pool", "goal_pool": "goal_pool", "evaluation": "eval_control"}[phase]
    validate_entries(configs, phase, goals, row0, pool_entries)
    n = venv.num_envs
    ranks = [int(r) for r in getattr(venv, "ranks", range(n))]
    venv.env_method_each("m7u_configure", {i: ((dict(configs[ranks[i]]),), {}) for i in range(n)})
    venv.reset()
    by_entry = {e["entry"]: e for c in configs.values() for e in c["entries"]}
    results: List[Dict[str, Any]] = []

    def new_task(i: int, rec: Optional[Mapping[str, Any]]) -> Optional[g1.Task]:
        if not rec or rec.get("idle"):
            return None
        e = by_entry[rec["entry"]]
        if rec.get("world_digest") != PIN["world_digest"]:
            raise IntegrityStop(f"entry {rec['entry']}: reset world differs from the pinned stage table")
        r0 = np.array(rec["row"], dtype=np.float64)
        diff = [us.FIELDS[j] for j in np.nonzero(~((r0 == row0) | (np.isnan(r0) & np.isnan(row0))))[0]]
        if diff:
            raise IntegrityStop(f"entry {rec['entry']}: reset row differs from the tick-0 record ({diff[:6]})")
        return g1.Task(rank=ranks[i], entry=e, controller=controller_for(e, n_candidates, goals), rows=[r0],
                       hist=us.init_history(r0))

    tasks: List[Optional[g1.Task]] = [new_task(i, (venv.reset_infos[i] or {}).get("m7u")) for i in range(n)]
    while any(t is not None for t in tasks):
        pending: Dict[str, List[Tuple[g1.Task, np.ndarray]]] = {}
        for task in tasks:
            if task is None:
                continue
            c = task.controller
            if c.needs_decision():
                arr = c.prepare()
                if c.needs_model:
                    pending.setdefault(ARM_MODEL[task.entry["arm"]], []).append((task, arr))
                else:
                    rec = g1.decision_record(task, arr, 0) if phase == "evaluation" else None
                    c.choose(0)
                    if rec is not None:
                        task.evidence.append(rec)
        for key, items in pending.items():
            g1.plan_batch(models[key][0], models[key][1], items)
        actions = np.zeros((n, 2), dtype=np.int64)
        active = 0
        for i, task in enumerate(tasks):
            if task is not None:
                actions[i] = task.controller.next_word()
                active += 1
        ledger.check(ledger_key, active)
        clock.check()
        _obs, _rew, dones, infos = venv.step(actions)
        for i, task in enumerate(tasks):
            if task is None:
                continue
            rec = (infos[i] or {}).get("m7u") or {}
            if rec.get("idle") or rec.get("entry") != task.entry["entry"]:
                raise IntegrityStop(f"rank {ranks[i]}: step record does not belong to entry {task.entry['entry']}")
            if not rec.get("consumed"):
                raise IntegrityStop(f"rank {ranks[i]} entry {task.entry['entry']}: episode failure (no tick consumed)")
            word = (int(actions[i, 0]), int(actions[i, 1]))
            row = np.array(rec["row"], dtype=np.float64)
            task.hist = us.advance_history(task.hist, task.rows[-1], word, row)
            task.rows.append(row)
            task.words.append(word)
            ledger.add(ledger_key, 1)
            if int(rec.get("k", -1)) != len(task.words) or int(row[us.F["input_tick"]]) != len(task.words):
                raise IntegrityStop(f"entry {task.entry['entry']}: tick semantics (k {rec.get('k')}, input_tick "
                                    f"{row[us.F['input_tick']]}, words {len(task.words)})")
            if track is not None and row[us.F["valid"]] == 1.0:
                tk = track.at(np.array([int(row[us.F["input_tick"]])]))[0]
                cols = [us.F[c] for c in us.TRACK_COLUMNS]
                if any(not (np.isnan(a) and np.isnan(b)) and a != b for a, b in zip(row[cols][:4], tk[:4])):
                    raise IntegrityStop(f"entry {task.entry['entry']}: platform differs from the clock track")
            if dones[i]:
                summary = (infos[i] or {}).get("m7_episode") or {}
                results.append(gg._task_result(task, rec, summary))
                tasks[i] = None if rec.get("idle_next") else new_task(i, (venv.reset_infos[i] or {}).get("m7u"))
    return results


# -- pools -------------------------------------------------------------------------------------------------------------


def check_pool(results: Sequence[Mapping[str, Any]], entries: Sequence[str], max_words: int,
               read_sidecar: Callable[[Any], Mapping[str, Any]], n_candidates: int) -> List[str]:
    """Every registered entry present exactly once; <= max_words words; the word stream equals its offline regeneration;
    the sidecar equals the streamed rows."""
    import m7u_worker as uw

    problems: List[str] = []
    if sorted(r["entry"] for r in results) != sorted(entries):
        problems.append(f"pool produced {len(results)} episodes, not exactly the {len(entries)} registered")
    for r in results:
        if len(r["words"]) > max_words:
            problems.append(f"{r['entry']}: {len(r['words'])} words > {max_words}")
        regen = up.rc_words(stream_key(pool_stream_kind(r["entry"]), r["entry"]), n_candidates, len(r["words"]))
        if [tuple(w) for w in r["words"]] != regen:
            problems.append(f"{r['entry']}: words differ from the behaviour regeneration")
        side = read_sidecar(r["artifact_dir"])
        if len(side["rows"]) != len(r["rows"]) or uw.rows_equal(side["rows"].reshape(-1), r["rows"].reshape(-1)):
            problems.append(f"{r['entry']}: sidecar rows differ from the streamed rows")
    return problems


def pool_record(results: Sequence[Mapping[str, Any]], kind: str) -> Dict[str, Any]:
    return {"scope": g3.SCOPE, "role": "fitting only" if kind == "train" else "goal source, never fitted",
            "episodes": [{"entry": r["entry"], "episode_id": r["episode_id"], "words": int(len(r["words"])),
                          "rank": r["rank"], "stream_key": stream_key(kind, r["entry"]),
                          "artifact_dir": str(r["artifact_dir"]), "sidecar": r["sidecar"],
                          "native_action_digest": r["native_action_digest"], "termination_reason": r["termination_reason"],
                          "truncation_reason": r["truncation_reason"], "startup_mode": r["startup_mode"]}
                         for r in sorted(results, key=lambda r: r["entry"])]}


def pool_episodes(results: Sequence[Mapping[str, Any]], by_entry: bool = False) -> List[Any]:
    """The pool's episodes sorted by entry. `by_entry` names each episode by its entry (as M7u2's pool accuracy did: the id only
    seeds the sha order of the open-loop start ticks), otherwise by its episode id."""
    import m7u_model as um

    return [um.Episode(episode_id=str(r["entry"] if by_entry else r["episode_id"]), rows=r["rows"], words=r["words"],
                       fell=r["termination_reason"] == "native_failure")
            for r in sorted(results, key=lambda r: r["entry"])]


def refit_manifest(src: Any, train_results: Sequence[Mapping[str, Any]], m7u2_pool: Sequence[Mapping[str, Any]],
                   goal_ids: Sequence[str] = (), train_entries: Sequence[str] = g3.TRAIN_ENTRIES) -> Dict[str, Any]:
    """The refit's data manifest, with its exclusions verified: exactly M7u1's 80 training episodes plus the registered
    training-pool entries; none of M7u1's held-out episodes, M7u2's pool episodes or goal-pool episodes."""
    held = {e[0] for e in src.episodes} - set(src.train_ids)
    pool_ids = [str(r["episode_id"]) for r in sorted(train_results, key=lambda r: r["entry"])]
    m7u2_ids = {str(e["episode_id"]) for e in m7u2_pool}
    problems = []
    if len(src.train_ids) != rf.N_M7U1_TRAIN or len(set(src.train_ids)) != rf.N_M7U1_TRAIN:
        problems.append("m7u1 training ids are not 80 distinct episodes")
    if len(held) != 12 or held & set(src.train_ids):
        problems.append("m7u1 held-out episodes overlap the training episodes")
    if set(pool_ids) & held:
        problems.append("a training-pool episode is an m7u1 held-out episode")
    if set(pool_ids) & set(src.train_ids):
        problems.append("a training-pool episode is an m7u1 training episode")
    if set(pool_ids) & m7u2_ids:
        problems.append("a training-pool episode is an M7u2 pool episode")
    if set(pool_ids) & set(goal_ids):
        problems.append("a training-pool episode is a goal-pool episode")
    if sorted(r["entry"] for r in train_results) != sorted(train_entries):
        problems.append(f"the training pool is not exactly the registered entries ({len(train_entries)})")
    return {"m7u1_train_ids": list(src.train_ids), "pool_entries": [r["entry"] for r in sorted(train_results, key=lambda r: r["entry"])],
            "pool_episode_ids": pool_ids, "excluded": {"m7u1_heldout": sorted(held), "m7u2_pool_episodes": len(m7u2_ids),
                                                       "goal_pool": "none exists until training has ended"},
            "problems": problems}


# -- evidence ----------------------------------------------------------------------------------------------------------


def save_trial(directory: Path, r: Mapping[str, Any], goals: Sequence[g2.Goal]) -> Dict[str, Any]:
    ev = r["evidence"]
    words = [tuple(int(v) for v in w) for w in r["words"]]
    arrays: Dict[str, np.ndarray] = {
        "rows": np.asarray(r["rows"], dtype=np.float64), "words": np.asarray(r["words"], dtype=np.int16).reshape(-1, 2),
        "hist": us.history_sequence(r["rows"], words),
        "decision": np.array([d["decision"] for d in ev], dtype=np.int32),
        "at_tick": np.array([d["at_tick"] for d in ev], dtype=np.int32),
        "chosen": np.array([d["chosen"] for d in ev], dtype=np.int32)}
    for key in ("candidates", "root_row", "root_hist", "scores", "reach_at", "pred_x", "pred_y", "pred_air",
                "pred_fall_at"):
        if ev and key in ev[0]:
            arrays[key] = np.stack([d[key] for d in ev])
    k, arm = int(r["goal_k"]), r["arm"]
    commanded = None if arm == "RC" else (goals[k] if arm in ("PF", "PR") else goals[g3.scrambled(k, len(goals))])
    meta = {"entry": r["entry"], "arm": arm, "goal_k": k, "t": 0, "scored_goal": [goals[k].x, goals[k].y],
            "commanded_goal_k": None if commanded is None else commanded.k,
            "commanded_goal": None if commanded is None else [commanded.x, commanded.y],
            "model": ARM_MODEL.get(arm), "stream_key": stream_key("goal", k), "model_evaluated": arm != "RC",
            "episode_id": r["episode_id"], "artifact_dir": str(r["artifact_dir"]), "reach_tick": r["reach_tick"],
            "truncation_reason": r["truncation_reason"], "termination_reason": r["termination_reason"],
            "native_action_digest": r["native_action_digest"], "scope": g3.SCOPE}
    path = Path(directory) / f"{r['entry']}.npz"
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, meta=np.frombuffer(json.dumps(meta, default=str).encode("utf-8"), dtype=np.uint8), **arrays)
    return {"file": path.name, "decisions": len(ev), "sha256": g1.sha256_stream(path)}


def replay_selection(outcomes: Mapping[str, Sequence[bool]]) -> List[Tuple[str, int]]:
    """(arm, goal k) of every success of every arm, in arm and registered goal order."""
    return [(arm, k) for arm in ARMS for k, ok in enumerate(outcomes[arm]) if ok]


# -- diagnostics (forward passes only; never an input of the rule) ----------------------------------------------------


def diagnostics(*, models: Mapping[str, Tuple[Any, Any]], retrain: Tuple[Any, Any], goals: Sequence[g2.Goal],
                row0: np.ndarray, by: Mapping[Tuple[int, str], Mapping[str, Any]], outcomes: Mapping[str, Sequence[bool]],
                goal_pool: Sequence[Mapping[str, Any]], goal_eps: Sequence[Any], m7u1_heldout: Sequence[Any],
                m7u2_pool: Optional[Sequence[Mapping[str, Any]]], m7u2_eps: Optional[Sequence[Any]],
                recorded: Mapping[str, Any], check_pins: bool) -> Dict[str, Any]:
    """Every registered diagnostic. Each block is guarded: a defect in one is recorded under `errors` and never stops the
    run or alters the decision."""
    import m7u_analysis as ua
    import m7u3_analysis as an

    out: Dict[str, Any] = {"errors": {}}
    named = {"frozen": models["frozen"], "refit": models["refit"], "retrain": retrain}
    n = len(goals)

    def guard(name: str, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except Exception as exc:    # noqa: BLE001 - a diagnostic defect is reported, never fatal
            out["errors"][name] = f"{type(exc).__name__}: {exc}"
            return None

    # D1: witness acceptance from tick 0
    def d1() -> Dict[str, Any]:
        w = {name: an.witness_acceptance(m, c, goals, row0) for name, (m, c) in named.items()}
        return {"per_model": w, "W_frozen": w["frozen"]["count"], "W_refit": w["refit"]["count"],
                "W_retrain": w["retrain"]["count"],
                "paired_frozen_vs_refit": an.paired_table(w["frozen"]["accepted"], w["refit"]["accepted"])}

    out["D1_witness"] = guard("D1_witness", d1)

    # D2: strict from-reset open-loop error. (a) the goal pool, (b) the M7u2 pool; never fitted by any model
    def d2(eps: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        strict = {name: an.strict_open_loop(m, c, eps) for name, (m, c) in named.items()}
        per = {name: an.summarise_strict(s) for name, s in strict.items()}
        paired = {"refit_vs_frozen": an.paired_strict(strict["refit"], strict["frozen"]),
                  "retrain_vs_frozen": an.paired_strict(strict["retrain"], strict["frozen"])}
        reading = r3.model_reading({h: {k: strict[k][h]["error"].tolist() for k in ("frozen", "refit", "retrain")}
                                    for h in an.HORIZONS})
        return {"summary": per, "paired": paired, "model_reading": reading}

    out["D2a_goal_pool"] = guard("D2a_goal_pool", lambda: d2(goal_pool))
    if m7u2_pool is not None:
        out["D2b_m7u2_pool"] = guard("D2b_m7u2_pool", lambda: d2(m7u2_pool))
        d2b = out.get("D2b_m7u2_pool")
        if d2b and check_pins:
            got = {h: d2b["summary"]["frozen"][str(h)].get("median") for h in an.HORIZONS}
            ok = all(got[h] is not None and abs(got[h] - STRICT_M7U2_FROZEN_MEDIANS[h]) <= 1.0 for h in an.HORIZONS)
            d2b["reproduces_proposal_1_2"] = {"expected": STRICT_M7U2_FROZEN_MEDIANS, "got": got, "ok": ok}
            if not ok:
                out["errors"]["D2b_cross_check"] = "the frozen strict figures do not reproduce proposal 1.2 (analysis defect)"

    # D3: failure attribution of each P arm with its own model
    def d3() -> Dict[str, Any]:
        res = {}
        for arm, key in (("PF", "frozen"), ("PR", "refit")):
            m, c = models[key]
            trials = {k: {"rows": by[(k, arm)]["rows"], "words": by[(k, arm)]["words"],
                          "goal": (goals[k].x, goals[k].y), "decisions": by[(k, arm)]["decisions"],
                          "reached": bool(outcomes[arm][k])} for k in range(n)}
            attr = {k: an.attribution(m, c, trials[k]) for k in range(n)}
            flags = {k: ua.ambiguity_flags(by[(k, arm)]["rows"], 0)["any"] for k in range(n)}
            res[arm] = {"summary": an.attribution_summary(attr, flags, outcomes[arm]),
                        "per_goal": {str(k): attr[k] for k in range(n)}}
            res[arm]["_trials"] = trials
            res[arm]["_attr"] = attr
        return res

    d3r = guard("D3_attribution", d3)
    out["D3_attribution"] = ({a: {k: v for k, v in d3r[a].items() if not k.startswith("_")} for a in d3r}
                             if d3r else None)

    # D4: cross attribution (the same executed words from the same decision states through the other model)
    def d4() -> Dict[str, Any]:
        return {"PF_model_failures_through_refit": an.cross_attribution(models["frozen"], models["refit"], d3r["PF"]["_trials"],
                                                                       d3r["PF"]["_attr"], outcomes["PF"]),
                "PR_model_failures_through_frozen": an.cross_attribution(models["refit"], models["frozen"], d3r["PR"]["_trials"],
                                                                        d3r["PR"]["_attr"], outcomes["PR"])}

    if d3r:
        out["D4_cross_attribution"] = guard("D4_cross_attribution", d4)

    # D5: continuity and regression
    def d5() -> Dict[str, Any]:
        res: Dict[str, Any] = {"goal_pool_early_window_and_one_step": {}, "m7u1_heldout": {}}
        for name, (m, c) in named.items():
            res["goal_pool_early_window_and_one_step"][name] = an.one_step_and_open_loop(m, c, goal_eps)
            res["m7u1_heldout"][name] = an.one_step_and_open_loop(m, c, m7u1_heldout)
        if check_pins:
            held = res["m7u1_heldout"]["frozen"]
            rec = recorded.get("m7u1_heldout_accuracy") or {}
            ok = bool(rec) and all(abs(held["open_loop"][h]["median"] - rec["open_loop"][h]["median"]) <= 0.05
                                   for h in ("16", "32", "64")) and abs(held["pos_err_median"] - rec["pos_err_median"]) <= 0.001
            res["frozen_reproduces_m7u1_heldout"] = {"ok": ok, "recorded": rec.get("open_loop")}
            if not ok:
                out["errors"]["D5_m7u1_reproduction"] = "the frozen model does not reproduce m7u1's held-out figures"
            if m7u2_eps is not None and recorded.get("m7u2_pool_accuracy"):
                pa = an.one_step_and_open_loop(*named["frozen"], m7u2_eps)
                rec2 = recorded["m7u2_pool_accuracy"]
                ok2 = all(abs(pa["open_loop"][h]["median"] - rec2["open_loop"][h]["median"]) <= 0.05 for h in ("16", "32", "64"))
                res["frozen_reproduces_m7u2_pool_early_window"] = {"ok": ok2, "recorded": rec2.get("open_loop")}
                if not ok2:
                    out["errors"]["D5_m7u2_reproduction"] = "the frozen model does not reproduce M7u2's early-window figures"
        return res

    out["D5_continuity"] = guard("D5_continuity", d5)

    # D6: executed-block calibration, ambiguity flags, movement census
    def d6() -> Dict[str, Any]:
        cal = {"PF": an.executed_calibration(*models["frozen"], [by[(k, "PF")] for k in range(n)]),
               "PR": an.executed_calibration(*models["refit"], [by[(k, "PR")] for k in range(n)]),
               "SR": an.executed_calibration(*models["refit"], [by[(k, "SR")] for k in range(n)])}
        flags = {f"{k}:{arm}": ua.ambiguity_flags(by[(k, arm)]["rows"], 0) for k in range(n) for arm in ARMS}
        census = {by[(k, arm)]["entry"]: gg.movement_census(by[(k, arm)]) for k in range(n) for arm in ARMS}
        return {"calibration_executed": cal, "ambiguity": flags, "movement_census": census}

    out["D6"] = guard("D6", d6)
    return out


def coverage_report(goals: Sequence[g2.Goal], train_eps: Sequence[Any], m7u1_eps: Sequence[Any],
                    outcomes: Mapping[str, Sequence[bool]]) -> Dict[str, Any]:
    """D8, computed AFTER selection: per goal, how many training-pool and m7u1 training episodes make a valid airborne
    reach of its box within input ticks 1..128; reach outcomes tabulated by coverage (descriptive only)."""
    tp = g3.coverage(goals, [(e.episode_id, e.rows, e.fell) for e in train_eps])
    m1 = g3.coverage(goals, [(e.episode_id, e.rows, e.fell) for e in m7u1_eps])
    rows = []
    for k, g in enumerate(goals):
        rows.append({"goal_k": k, "training_pool": tp[k], "m7u1_train": m1[k], **{arm: bool(outcomes[arm][k]) for arm in ARMS}})
    by_cov: Dict[str, Any] = {}
    for label, lo, hi in (("0", 0, 0), ("1-5", 1, 5), ("6-15", 6, 15), (">=16", 16, 10 ** 9)):
        sel = [r for r in rows if lo <= r["training_pool"] <= hi]
        by_cov[label] = {"goals": len(sel), **{arm: sum(r[arm] for r in sel) for arm in ARMS}}
    return {"per_goal": rows, "by_training_pool_coverage": by_cov,
            "median_training_pool": float(np.median(tp)) if tp else None, "median_m7u1_train": float(np.median(m1)) if m1 else None}


# -- the gate ----------------------------------------------------------------------------------------------------------


def run_gate(*, settings: Any, train_settings: Any, goal_settings: Any, root: Path, venv_factory: Callable[..., Any],
             env_factory: Callable[..., Any], clock: g1.Clock, src: gg.M7u1Sources, frozen: gg.Frozen, retrain: gg.Frozen,
             ledger: Optional[g1.Ledger] = None, n_candidates: int = N_CANDIDATES,
             p1_entries: Optional[Sequence[Mapping[str, Any]]] = None,
             artifact_words: Callable[[Any], List[Tuple[int, int]]] = g1.artifact_track1_words,
             read_sidecar: Optional[Callable[[Any], Mapping[str, Any]]] = None,
             ref: Optional[g2.Reference] = None, row0: Optional[np.ndarray] = None, m7u2_rec: Optional[Mapping[str, Any]] = None,
             m7u2_pool: Optional[Sequence[Mapping[str, Any]]] = None,
             train_entries: Sequence[str] = g3.TRAIN_ENTRIES, goal_entries: Sequence[str] = g3.GOAL_ENTRIES,
             n_goals: int = g3.N_GOALS, n_workers: int = N_WORKERS, refit_steps: int = REFIT_STEPS,
             pin_track: Optional[str] = PIN["track_sha256"], check_pins: bool = True) -> Dict[str, Any]:
    """Every phase in order under the caps; returns the state (with `decision`). Factories, sources, the reference and the
    M7u2 records are injectable only so the offline tests can drive this exact code with synthetic workers."""
    import torch

    import m7u_model as um
    import m7u_worker as uw

    torch.set_num_threads(max(1, (os.cpu_count() or 6)))
    read_sidecar = read_sidecar or (lambda d: uw.read_sidecar(g1.resolve(d)))
    ledger = ledger or g1.Ledger(TICK_BUDGET)
    row0 = gg.tick0_row(src) if row0 is None else np.asarray(row0, dtype=np.float64)
    ref = ref or gg.reference(src)
    pdig_frozen = gg.parameter_digest(frozen.model)
    pdig_retrain = gg.parameter_digest(retrain.model)
    state: Dict[str, Any] = {"started_utc": utc(), "gate": GATE, "scope": g3.SCOPE, "phases": {},
                             "integrity": {"problems": []}, "frozen_model": {"parameter_digest": pdig_frozen},
                             "retrain_model": {"parameter_digest": pdig_retrain}, "tick0_row_digest": g2.row_digest(row0),
                             "reference_digest": ref.digest(), "evidence": {}}
    state_dir = Path(root) / "_gate"
    optimizers_before = len(rf.OPTIMIZERS)
    guard = contextlib.ExitStack()
    refit_digest: List[str] = []

    def save() -> None:
        state["ledger"] = ledger.to_json()
        state["clock"] = clock.to_json()
        sampler = getattr(clock, "sampler", None)
        if sampler is not None:
            state["memory_tree"] = {"samples": sampler.samples, "peak": dict(sampler.peak), "breach": sampler.breach}
        g1.write_json(state_dir / "state.json", state)

    def finish(outcome: Dict[str, Any]) -> Dict[str, Any]:
        clock.end()
        state["decision"] = outcome
        state["finished_utc"] = utc()
        save()
        return state

    def digests_check(where: str) -> None:
        if gg.parameter_digest(frozen.model) != pdig_frozen:
            raise IntegrityStop(f"frozen model parameters changed ({where})")
        if gg.parameter_digest(retrain.model) != pdig_retrain:
            raise IntegrityStop(f"P_retrain parameters changed ({where})")
        if refit_digest and gg.parameter_digest(models["refit"][0]) != refit_digest[0]:
            raise IntegrityStop(f"refit parameters changed ({where})")

    models: Dict[str, Tuple[Any, Any]] = {"frozen": (frozen.model, frozen.ctx)}
    try:
        with guard:
            # P1: pinned artifacts (m7u1 g26_P / g14_P, M7u2 g14_P / g03_P) reproduced through the stack, every row field
            clock.begin("p1")
            rec2 = m7u2_rec if m7u2_rec is not None else load_m7u2_records(check_pins=check_pins)
            entries = (list(p1_entries) if p1_entries is not None
                       else gg.p1_expected(src, artifact_words, read_sidecar) + p1_expected_m7u2(rec2, row0, artifact_words,
                                                                                                read_sidecar))
            res = g1.run_single(env_factory(Path(root) / "p1", "m7u3_p1", "identity", settings),
                                [{k: v for k, v in e.items() if k != "expected"} for e in entries], phase="p1",
                                ledger=ledger, clock=clock)
            p1 = [dict(gg.check_replay(r, e["expected"], e["words"]), entry=e["entry"]) for r, e in zip(res, entries)]
            state["phases"]["p1"] = p1
            save()
            if len(p1) != len(entries) or not all(p["ok"] for p in p1):
                raise IntegrityStop("P1: the pinned artifacts were not reproduced exactly")
            m7u2_pool_data = m7u2_pool if m7u2_pool is not None else (m7u2_pool_episodes(rec2) if check_pins else None)
            # training pool (fitting only)
            clock.begin("train_pool")
            venv = venv_factory(Path(root) / "train_pool", "m7u3_train", "pool", train_settings)
            try:
                train_res = drive(venv, pool_configs(n_workers, train_entries), phase="train_pool", ledger=ledger,
                                  clock=clock, n_candidates=n_candidates, row0=row0, track=frozen.track,
                                  pool_entries=train_entries)
            finally:
                venv.close()
            problems = check_pool(train_res, train_entries, g3.TRAIN_TICKS, read_sidecar, n_candidates)
            g1.write_json(state_dir / "train_pool.json", pool_record(train_res, "train"))
            state["phases"]["train_pool"] = {"episodes": len(train_res), "ticks": ledger.used["train_pool"],
                                             "problems": problems[:12],
                                             "falls": sum(1 for r in train_res if r["termination_reason"] == "native_failure")}
            save()
            if problems:
                raise IntegrityStop(f"training pool integrity: {problems[:3]}")
            # refit: the ONLY place an optimizer exists
            clock.begin("refit")
            manifest = refit_manifest(src, train_res, m7u2_pool_data or [], train_entries=train_entries)
            if manifest["problems"]:
                raise IntegrityStop(f"refit data manifest: {manifest['problems'][:3]}")
            base_eps, held_eps = rf.m7u1_split(src)
            train_eps = pool_episodes(train_res)

            def stop() -> Optional[str]:
                try:
                    clock.check()
                except CapStop as exc:
                    return str(exc)
                return None

            fit = rf.refit(base_eps, train_eps, held_eps, seed=rf.TRAIN_SEED, steps=refit_steps, should_stop=stop,
                           expected_track_sha256=pin_track)
            if fit.train.stopped:
                raise CapStop(fit.train.stopped)
            opts = rf.OPTIMIZERS[optimizers_before:]
            if len(opts) != 1 or not opts[0]["all_model_params"]:
                raise IntegrityStop(f"expected exactly one optimizer over the refit's parameters, got {opts}")
            if fit.vocab_dims["S"] > um.S_CAP or fit.vocab_dims["V3"] > um.V3_CAP or fit.vocab_dims["V4"] > um.V4_CAP:
                raise IntegrityStop(f"refit vocabulary {fit.vocab_dims} exceeds the caps")
            for p in fit.model.parameters():
                p.requires_grad_(False)
            fit.model.eval()
            guard.enter_context(gg.no_optimizer())               # no optimizer can be constructed from here on
            model_path = state_dir / "model_refit.pt"
            model_path.parent.mkdir(parents=True, exist_ok=True)
            file_sha = um.save(fit.model, fit.vocab, model_path, meta={"kind": "p_refit", "seed": rf.TRAIN_SEED,
                                                                      "steps": fit.steps, "contract": rf.CONTRACT})
            refit_digest.append(fit.parameter_digest)
            models["refit"] = (fit.model, fit.ctx)
            state["refit_model"] = {"parameter_digest": fit.parameter_digest, "model_sha256": file_sha}
            state["phases"]["refit"] = {"steps": fit.steps, "wall_s": fit.train.wall_s, "build_wall_s": fit.build_wall_s,
                                        "log": fit.train.log, "transitions": fit.transitions,
                                        "heldout_transitions": fit.heldout_transitions, "vocab": fit.vocab_dims,
                                        "vocab_vs_frozen": PIN["vocab"], "track_sha256": fit.track.digest(),
                                        "n_base": fit.n_base, "n_pool": fit.n_pool, "optimizers": opts,
                                        "bootstrap_sizes": fit.boot_sizes, "manifest": {k: v for k, v in manifest.items()
                                                                                        if k != "pool_episode_ids"}}
            g1.write_json(state_dir / "refit.json", dict(state["phases"]["refit"], manifest=manifest,
                                                         model_sha256=file_sha, parameter_digest=fit.parameter_digest))
            save()                                               # the refit's digests are on record before the goal pool
            # goal pool: collected AFTER the refit is frozen
            clock.begin("goal_pool")
            digests_check("before the goal pool")
            venv = venv_factory(Path(root) / "goal_pool", "m7u3_pool", "pool", goal_settings)
            try:
                pool = drive(venv, pool_configs(n_workers, goal_entries), phase="goal_pool", ledger=ledger, clock=clock,
                             n_candidates=n_candidates, row0=row0, track=frozen.track, pool_entries=goal_entries)
            finally:
                venv.close()
            problems = check_pool(pool, goal_entries, g3.GOAL_TICKS, read_sidecar, n_candidates)
            g_ids = {str(r["episode_id"]) for r in pool}
            if g_ids & (set(manifest["pool_episode_ids"]) | set(src.train_ids)):
                problems.append("a goal-pool episode is also a training episode")
            g1.write_json(state_dir / "goal_pool.json", pool_record(pool, "pool"))
            state["phases"]["goal_pool"] = {"episodes": len(pool), "ticks": ledger.used["goal_pool"], "problems": problems[:12],
                                            "falls": sum(1 for r in pool if r["termination_reason"] == "native_failure")}
            save()
            if problems:
                raise IntegrityStop(f"goal pool integrity: {problems[:3]}")
            # goals: deterministic, from the goal pool and the fixed reference only; frozen before evaluation
            clock.begin("goals")
            try:
                sel = g3.select_goals([{"entry": r["entry"], "episode_id": r["episode_id"], "rows": r["rows"],
                                        "words": r["words"], "fell": r["termination_reason"] == "native_failure"}
                                       for r in pool], ref, row0, entries=goal_entries, n_goals=n_goals)
            except g3.GoalError as exc:
                state["phases"]["goals"] = dict(exc.record, error=str(exc))
                save()
                if exc.incomplete:
                    raise CapStop(f"goal availability: {exc}") from exc
                raise IntegrityStop(f"goal selection: {exc}") from exc
            goals: List[g2.Goal] = sel["goals"]
            g1.write_json(state_dir / "goals.json", {"record": sel["record"], "goals": [g.to_json() for g in goals],
                                                     "digest": g3.goals_digest(goals)})
            state["phases"]["goals"] = dict(sel["record"], digest=g3.goals_digest(goals))
            save()
            # evaluation: normal tick-0 starts only
            clock.begin("evaluation")
            digests_check("before evaluation")
            venv = venv_factory(Path(root) / "evaluation", "m7u3_eval", "evaluation", settings)
            try:
                trials = drive(venv, evaluation_configs(goals, n_workers, row0), phase="evaluation", ledger=ledger,
                               clock=clock, n_candidates=n_candidates, row0=row0, goals=goals, models=models,
                               track=frozen.track)
            finally:
                venv.close()
            digests_check("after evaluation")
            if len(trials) != len(ARMS) * len(goals):
                raise IntegrityStop(f"{len(trials)} of {len(ARMS) * len(goals)} trials finished")
            by = {(r["goal_k"], r["arm"]): r for r in trials}
            outcomes = {arm: [by[(k, arm)]["reach_tick"] is not None and by[(k, arm)]["truncation_reason"] == uw.END_GOAL
                              for k in range(len(goals))] for arm in ARMS}
            state["evidence"]["trials"] = {r["entry"]: save_trial(state_dir / "trials", r, goals) for r in trials}
            state["phases"]["evaluation"] = {
                "trials": [{k: v for k, v in r.items() if k not in ("rows", "words", "evidence")} for r in trials],
                "outcomes": outcomes, "ticks": ledger.used["eval_control"],
                "clears": sum(1 for r in trials if r["cleared"])}
            save()
            # diagnostics (forward passes only) and exact success replays
            clock.begin("replays_analysis")
            ctx_of = {"PF": models["frozen"][1], "PR": models["refit"][1], "SR": models["refit"][1], "RC": models["refit"][1]}
            for label, arms in (("frozen", ("PF",)), ("refit", ("PR", "SR", "RC"))):
                try:
                    eps = [um.Episode(episode_id=r["entry"], rows=r["rows"], words=r["words"],
                                      fell=r.get("termination_reason") == "native_failure")
                           for r in trials if r["arm"] in arms]
                    state["evidence"][f"model_inputs_trials_{label}"] = g1.save_transitions(
                        state_dir / f"model_inputs_trials_{label}.npz", um.build_transitions(ctx_of[arms[0]], eps), eps)
                except Exception as exc:   # noqa: BLE001 - evidence only
                    state["evidence"][f"model_inputs_trials_{label}"] = {"error": f"{type(exc).__name__}: {exc}"}
            goal_pool_eps = [{"entry": r["entry"], "rows": r["rows"], "words": r["words"]}
                             for r in sorted(pool, key=lambda r: r["entry"])]
            recorded: Dict[str, Any] = {}
            if check_pins:
                recorded = {"m7u1_heldout_accuracy": json.loads((M7U1 / "state.json").read_text(encoding="utf-8"))
                            ["phases"]["diagnostics"]["heldout_accuracy"],
                            "m7u2_pool_accuracy": rec2["state"]["phases"]["diagnostics"]["pool_accuracy"]}
            m7u2_eps_um = ([um.Episode(episode_id=str(e.get("entry", e["episode_id"])), rows=e["rows"], words=e["words"],
                                       fell=bool(e["fell"])) for e in m7u2_pool_data] if m7u2_pool_data is not None else None)
            diag = diagnostics(models=models, retrain=(retrain.model, retrain.ctx), goals=goals, row0=row0, by=by,
                               outcomes=outcomes, goal_pool=goal_pool_eps, goal_eps=pool_episodes(pool, by_entry=True),
                               m7u1_heldout=held_eps, m7u2_pool=m7u2_pool_data, m7u2_eps=m7u2_eps_um, recorded=recorded,
                               check_pins=check_pins)
            diag["D8_coverage"] = None
            try:
                diag["D8_coverage"] = coverage_report(goals, train_eps, base_eps, outcomes)
            except Exception as exc:   # noqa: BLE001
                diag["errors"]["D8_coverage"] = f"{type(exc).__name__}: {exc}"
            diag["D9_refit_training"] = {k: state["phases"]["refit"][k] for k in ("steps", "wall_s", "log", "transitions", "vocab")}
            diag["mean_ticks_first_reach"] = {arm: [by[(k, arm)]["reach_tick"] for k in range(len(goals))] for arm in ARMS}
            state["phases"]["diagnostics"] = diag
            save()
            replays = []
            entries_by_id = {e["entry"]: e for c in evaluation_configs(goals, 1, row0).values() for e in c["entries"]}
            for arm, k in replay_selection(outcomes):
                r = by[(k, arm)]
                words = artifact_words(r["artifact_dir"])
                entry = dict(entries_by_id[r["entry"]], words=[list(w) for w in words])
                rr = g1.run_single(env_factory(Path(root) / "replays" / r["entry"], "m7u3_replay", "replay", settings),
                                   [entry], phase="replays", ledger=ledger, clock=clock)[0]
                orig = read_sidecar(r["artifact_dir"])
                chk = gg.check_replay(rr, {"rows": orig["rows"], "reach_tick": r["reach_tick"],
                                           "native_action_digest": r["native_action_digest"]}, words)
                chk["ok"] = chk["ok"] and words == [tuple(w) for w in r["words"]]
                replays.append(dict(chk, entry=r["entry"], arm=arm))
            state["phases"]["replays"] = replays
            digests_check("after analysis")
            save()
            integrity_ok = all(r["ok"] for r in replays)
            if not integrity_ok:
                state["integrity"]["problems"].append("a success replay was not exact")
            decision = r3.apply(outcomes, integrity_ok=integrity_ok)
            if decision["outcome"] in ("PASS", "NULL", "INCONCLUSIVE"):
                d2a = (diag.get("D2a_goal_pool") or {}).get("model_reading") or {}
                d1 = diag.get("D1_witness") or {}
                d_w = (d1["W_refit"] - d1["W_frozen"]) if d1 else None
                decision["readings"] = r3.readings(decision, o_rel=d2a.get("o_rel_64"), d_w=d_w)
                decision["model_reading"] = d2a
                decision["replication_readout"] = r3.replication_readout(outcomes)
                decision["goal_independence"] = sel["record"]["independence"]
                n = decision["n"]
                decision["summary"] = (f"m7u3 ({r3.SCOPE}): {decision['outcome']}; PF {n['PF']}, PR {n['PR']}, RC {n['RC']}, "
                                       f"SR {n['SR']} of {len(goals)}")
                bad = r3.scope_problems(decision["summary"])
                if bad:
                    raise IntegrityStop(f"decision summary uses forbidden wording {bad}")
            return finish(decision)
    except CapStop as exc:
        return finish(r3.apply({}, integrity_ok=True, incomplete=str(exc)))
    except (IntegrityStop, ValueError, rf.RefitError, um_error()) as exc:
        state["integrity"]["problems"].append(f"{type(exc).__name__}: {exc}")
        return finish(r3.apply({}, integrity_ok=False))


def um_error() -> type:
    import m7u_model as um

    return um.ModelError


def cmd_run() -> int:
    from m7_runtime import install_kill_on_close_job
    import m7u_worker as uw

    pf = preflight()
    if not pf["ok"]:
        print(json.dumps(pf, indent=1, default=str))
        print("refused: preflight problems (see above); nothing was launched")
        return 2
    install_kill_on_close_job()
    src = gg.load_m7u1_sources()
    settings = uw.env_settings()
    frozen = gg.load_frozen(src)
    retrain = load_retrain(frozen)
    sampler = TreeSampler(GATE_ROOT / "_gate" / "memory_tree.jsonl").start()
    try:
        clock = Clock3(caps=WALL_CAPS_S, global_cap=GLOBAL_CAP_S, memory_cap_mb=MEMORY_CAP_MB, sampler=sampler)
        state = run_gate(settings=settings, train_settings=dataclasses.replace(settings, horizon=g3.TRAIN_TICKS),
                         goal_settings=dataclasses.replace(settings, horizon=g3.GOAL_TICKS), root=GATE_ROOT,
                         venv_factory=g1.real_venv_factory, env_factory=g1.real_env_factory, clock=clock, src=src,
                         frozen=frozen, retrain=retrain)
    finally:
        sampler.stop()
    print(json.dumps(state.get("decision"), indent=1, default=str)[:4000])
    return 0


def verify_run(root: Path = GATE_ROOT, *, ref: Optional[g2.Reference] = None, row0: Optional[np.ndarray] = None,
               frozen_digest: str = PIN["parameter_digest"], retrain_digest: Optional[str] = None) -> Dict[str, Any]:
    """Read-only post-run verification, independent of the driver: the goals re-derive from the stored goal-pool sidecars
    with an identical digest (0 overlapping pairs by brute force, one goal per episode, a selection with no outcome, model or
    training-pool argument); every trial file starts at the tick-0 record with input_tick = words and at most 128 words; the
    refit file matches its recorded digests, differs from the frozen model and was recorded before the goal pool; the frozen
    and retrain digests are the pins."""
    import m7u_model as um
    import m7u_worker as uw

    gd = Path(root) / "_gate"
    problems: List[str] = []
    state = json.loads((gd / "state.json").read_text(encoding="utf-8"))
    if ref is None or row0 is None:
        src = gg.load_m7u1_sources()
        row0 = gg.tick0_row(src) if row0 is None else row0
        ref = gg.reference(src) if ref is None else ref
    stored = json.loads((gd / "goals.json").read_text(encoding="utf-8"))
    gp = json.loads((gd / "goal_pool.json").read_text(encoding="utf-8"))
    pool = []
    for e in gp["episodes"]:
        side = uw.read_sidecar(g1.resolve(e["artifact_dir"]))
        pool.append({"entry": e["entry"], "episode_id": e["episode_id"], "rows": side["rows"], "words": side["words"],
                     "fell": e["termination_reason"] == "native_failure"})
    again = g3.select_goals(pool, ref, row0, entries=[p["entry"] for p in pool], n_goals=len(stored["goals"]))
    if g3.goals_digest(again["goals"]) != stored["digest"]:
        problems.append("the goals do not re-derive with an identical digest")
    ind = g3.independence_report([g.to_json() for g in again["goals"]])
    if ind["overlapping_pairs"]:
        problems.append(f"overlapping goals: {ind['overlapping_pairs'][:2]}")
    if len({g.entry for g in again["goals"]}) != len(again["goals"]):
        problems.append("two goals share a source episode")
    bad_args = set(inspect_params(g3.select_goals)) - {"pool", "reference", "tick0_row", "entries", "n_goals"}
    if bad_args:
        problems.append(f"select_goals has unexpected arguments {bad_args}")
    checked = 0
    for f in sorted((gd / "trials").glob("*.npz")):
        with np.load(f) as z:
            meta = json.loads(z["meta"].tobytes().decode("utf-8"))
            rows, words = z["rows"], z["words"]
            if meta["t"] != 0 or not np.array_equal(rows[0], row0, equal_nan=True):
                problems.append(f"{f.name}: not a tick-0 start")
            if not all(int(rows[i, us.F["input_tick"]]) == i for i in range(len(rows))) or len(words) != len(rows) - 1:
                problems.append(f"{f.name}: input_tick differs from the words submitted")
            if len(words) > g3.BUDGET or meta["stream_key"] != stream_key("goal", meta["goal_k"]):
                problems.append(f"{f.name}: budget or stream key")
        checked += 1
    rm = state.get("refit_model") or {}
    if rm:
        if sha256_file(gd / "model_refit.pt") != rm["model_sha256"]:
            problems.append("the refit file differs from its recorded sha256")
        model, _vocab, _meta = um.load(gd / "model_refit.pt")
        if um.parameter_digest(model) != rm["parameter_digest"]:
            problems.append("the refit parameter digest differs from its record")
        if rm["parameter_digest"] in (frozen_digest, retrain_digest):
            problems.append("the refit equals the frozen model or P_retrain")
    else:
        problems.append("no refit record")
    if state.get("frozen_model", {}).get("parameter_digest") != frozen_digest:
        problems.append("the frozen digest recorded at the start differs from the pin")
    if retrain_digest is not None and state.get("retrain_model", {}).get("parameter_digest") != retrain_digest:
        problems.append("the P_retrain digest recorded at the start differs from the pin")
    return {"ok": not problems, "problems": problems, "goals": len(again["goals"]), "goals_digest": stored["digest"][:16],
            "min_pairwise_chebyshev": ind["min_pairwise_chebyshev"], "trial_files_checked": checked}


def inspect_params(fn: Callable[..., Any]) -> List[str]:
    import inspect

    return list(inspect.signature(fn).parameters)


def cmd_verify_run() -> int:
    rep = verify_run(retrain_digest=retrain_pins()["parameter_digest"])
    print(json.dumps(rep, indent=1))
    return 0 if rep["ok"] else 1


def cmd_attest_prep() -> int:
    """Write logs/m7u3_prep/prep_attestation.json: the sha256 of the refit code and of the three preparation outputs (the
    identity record, the P_retrain record and file), after checking that the identity retrain was bit-exact, that P_retrain
    was trained as specified, and that m7u3_refit.py was last modified BEFORE either run started (so the recorded runs used
    this code). Never overwrites an existing attestation."""
    import calendar

    if ATTESTATION.exists():
        print(f"{ATTESTATION} exists (never overwritten)")
        return 2
    ident = json.loads(IDENTITY_RECORD.read_text(encoding="utf-8"))
    rec = json.loads(RETRAIN_RECORD.read_text(encoding="utf-8"))
    problems = []
    if not ident.get("bit_exact") or ident["parameter_diff"].get("max_abs_diff") != 0.0:
        problems.append("the identity retrain is not bit-exact")
    if rec["steps"] != REFIT_STEPS or rec["seed"] != rf.RETRAIN_SEED or not rec["differs_from_frozen"]:
        problems.append("P_retrain was not trained as specified")
    code = RL / "m7u3_refit.py"
    mtime = code.stat().st_mtime
    for name, r in (("identity", ident), ("retrain", rec)):
        ended = calendar.timegm(time.strptime(r["utc"], "%Y-%m-%dT%H:%M:%SZ"))
        if mtime > ended - r["wall_s"]:
            problems.append(f"m7u3_refit.py was modified after the {name} run started")
    if rec["model_sha256"] != sha256_file(RETRAIN_PATH):
        problems.append("the P_retrain file does not match its record")
    if problems:
        print(json.dumps({"attested": False, "problems": problems}, indent=1))
        return 1
    att = {"contract": "m7u3_prep_attestation_v1", "utc": utc(), "refit_code_sha256": sha256_file(code),
           "identity_record_sha256": sha256_file(IDENTITY_RECORD), "retrain_record_sha256": sha256_file(RETRAIN_RECORD),
           "retrain_model_sha256": rec["model_sha256"], "retrain_parameter_digest": rec["parameter_digest"],
           "identity_parameter_digest": ident["parameter_digest"], "torch": ident["torch"], "threads": ident["threads"],
           "note": "the file's modification time precedes the start of both recorded runs"}
    ATTESTATION.write_text(json.dumps(att, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(att, indent=1))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("attest-prep")
    sub.add_parser("verify-run")
    p = sub.add_parser("preflight")
    p.add_argument("--skip-unit", action="store_true")
    sub.add_parser("approval-template")
    sub.add_parser("run")
    a = ap.parse_args(argv)
    if a.cmd == "attest-prep":
        return cmd_attest_prep()
    if a.cmd == "verify-run":
        return cmd_verify_run()
    if a.cmd == "status":
        print(json.dumps({"identity": identity(), "approval": approval_status()[1], "gate_root_exists": GATE_ROOT.exists()},
                         indent=1, default=str))
        return 0
    if a.cmd == "preflight":
        rep = preflight(run_unit=not a.skip_unit)
        print(json.dumps(rep, indent=1, default=str))
        return 0 if rep["ok"] else 1
    if a.cmd == "approval-template":
        tpl = dict(identity(), approval="PENDING (a reviewer replaces this with APPROVED <name> <date>)")
        print(json.dumps(tpl, indent=1, default=str))
        return 0
    return cmd_run()


if __name__ == "__main__":
    sys.exit(main())
