#!/usr/bin/env python3
"""M7u gate `m7u1` driver (design: docs/rl_model_planning_m7u_proposal_2026-09-29.md, revision 2, §6-§7).
NOT AUTHORISED TO RUN: `run` refuses without an APPROVED record matching the current identity, and this preparation step
creates no such record.

    python rl/m7u_gate.py status
    python rl/m7u_gate.py preflight [--skip-unit]   # no game: tests, benchmark + track records, D: coverage, approval
    python rl/m7u_gate.py approval-template         # prints the record a reviewer would write (never writes it)
    python rl/m7u_gate.py run                       # refused unless preflight passes

SCOPE: local control after the agent's own supplied recorded prefix. A reach is a rising airborne point 64 ticks from a
start state of this run's own behaviour episodes; it is never reported as a landing, a crossing or a reach from tick 0.

`run`, in order, each phase under its own native-tick cap and wall-clock cap inside ONE 60-minute cap from launch:
P1 identity (2 pinned Track 1 artifacts through the M7u stack) -> collection (92 RC episodes) -> clock-track, RC-regeneration
and storage integrity (1 training episode replayed) -> goals (frozen before training) -> training (E = 3, S steps from
the benchmark) -> evaluation (40 goals x P / RC / S, prefixes itemised) -> reported diagnostics -> exact success replays
-> rule `m7u1_control_rule_v2`, applied once. A cap or availability stop is INCOMPLETE (never a performance result; no
retry, no extension); an integrity failure is INVALID. The native RNG is never inspected; seeds are Python-side only.
The driver never commits, pushes or deletes evidence.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402

import m7u_goals as ug  # noqa: E402
import m7u_planner as up  # noqa: E402
import m7u_rule as ur  # noqa: E402
import m7u_state as us  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
RL = REPO_ROOT / "rl"
RUNS = REPO_ROOT / "runs"
LOGS = REPO_ROOT / "logs"
GATE_ROOT = RUNS / "m7u" / "gate"
APPROVAL = REPO_ROOT / "docs" / "rl_model_planning_m7u_gate_approval.json"
BENCH_RECORD = LOGS / "m7u_bench" / "bench.json"
TRACK_RECORD = LOGS / "m7u_track_check" / "track_check.json"
BACKUP_ROOT = Path(r"D:\BattleShip_runs_backup")
BACKUP_BASE = BACKUP_ROOT / "2026-09-28"
EXECUTABLE = REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"
PINNED_DIR = RUNS / "m7q" / "_equiv" / "input_all"
P1_TRACES = (("fx_m7d_s0v1_det_fall.json.gz", 3361), ("fx_m7d_s0v1_fall6_double.json.gz", 2560))
GATE_SEED = 0
MEMBERS = 3
N_COLLECT = 92
N_TRAIN = N_COLLECT - ug.HELDOUT_EPISODES          # 80
REPLAYS = {"P": 6, "RC": 2, "S": 2}
CONTROL_TICKS_PER_TRIAL = ug.BUDGET
PREFIX_TICKS_PER_TRIAL = ug.T_MAX
TRIALS = ug.N_GOALS * 3
TICK_BUDGET = {"p1": sum(n for _, n in P1_TRACES),                                    # 5,921
               "collection": N_COLLECT * 3600,                                         # 331,200
               "storage": 3600,
               "eval_prefix": TRIALS * PREFIX_TICKS_PER_TRIAL,                         # 72,000
               "eval_control": TRIALS * CONTROL_TICKS_PER_TRIAL,                       # 11,520
               "replays": sum(REPLAYS.values()) * (PREFIX_TICKS_PER_TRIAL + CONTROL_TICKS_PER_TRIAL)}   # 6,960
TICK_BUDGET["total"] = sum(TICK_BUDGET.values())                                        # 431,201
WALL_CAPS_S = {"p1": 180, "collection": 600, "storage": 120, "train": 900, "evaluation": 1500,
               "replays_analysis": 300}
GLOBAL_CAP_S = 3600
MEMORY_CAP_MB = 3072
BENCH_CHOICES = {"n_candidates": (64, 32), "train_steps": (6000, 4500, 3000)}
CODE_FILES = ("m7u_state.py", "m7u_model.py", "m7u_planner.py", "m7u_goals.py", "m7u_rule.py", "m7u_analysis.py",
              "m7u_worker.py", "m7u_gate.py", "m7u_tests.py", "tools/m7u_bench.py", "tools/m7u_track_check.py",
              "btt_parallel.py", "battleship_env.py", "run_artifacts.py", "m7_vec_env.py", "m7_runtime.py", "m7n_obs.py",
              "m7q_obs.py", "m7q_input.py", "m7g_spatial.py", "m7n_entity.py", "m7q_status_table.py", "m7r_commit.py",
              "experiment_config.py", "m7_trainer.py", "tools/runs_backup.py", "configs/m7q/m7q_pilot_s0.toml")


PINNED_WORLD_DIGEST = us.world_digest(us.static_world_pinned())


class CapStop(Exception):
    """A native-tick, wall-clock or memory cap was reached: the run is INCOMPLETE."""


class IntegrityStop(Exception):
    """An integrity check failed: the run is INVALID."""


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write_json(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


# -- caps --------------------------------------------------------------------------------------------------------------


class Ledger:
    """Native ticks per phase against TICK_BUDGET. `check` refuses BEFORE a request would exceed a phase or the total."""

    def __init__(self, budget: Mapping[str, int] = TICK_BUDGET):
        self.budget = dict(budget)
        self.used = {k: 0 for k in self.budget if k != "total"}

    def total(self) -> int:
        return sum(self.used.values())

    def check(self, phase: str, n: int) -> None:
        if n <= 0:
            return
        if self.used[phase] + n > self.budget[phase]:
            raise CapStop(f"native-tick cap of phase {phase}: {self.used[phase]} + {n} > {self.budget[phase]}")
        if self.total() + n > self.budget["total"]:
            raise CapStop(f"total native-tick cap: {self.total()} + {n} > {self.budget['total']}")

    def add(self, phase: str, n: int) -> None:
        self.used[phase] += int(n)
        if self.used[phase] > self.budget[phase] or self.total() > self.budget["total"]:
            raise IntegrityStop(f"ledger over budget after consumption in {phase}")

    def to_json(self) -> Dict[str, Any]:
        return {"used": dict(self.used), "total": self.total(), "budget": dict(self.budget)}


def private_mb() -> Optional[float]:
    """This process's private bytes (Windows K32GetProcessMemoryInfo), None elsewhere."""
    if os.name != "nt":
        return None

    class PMC(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong), ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t), ("PrivateUsage", ctypes.c_size_t)]

    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.K32GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(PMC), ctypes.c_ulong]
    if not k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
        return None
    return pmc.PrivateUsage / 2 ** 20


class Clock:
    """The 60-minute cap and the per-phase caps. Launch = construction, immediately before P1 starts the first native
    process; the zero-tick preflight precedes it and launches nothing. `now` is injectable (offline tests)."""

    def __init__(self, now: Callable[[], float] = time.monotonic, caps: Mapping[str, float] = WALL_CAPS_S,
                 global_cap: float = GLOBAL_CAP_S, memory: Callable[[], Optional[float]] = private_mb,
                 memory_cap_mb: float = MEMORY_CAP_MB):
        self.now, self.caps, self.global_cap = now, dict(caps), float(global_cap)
        self.memory, self.memory_cap = memory, float(memory_cap_mb)
        self.t0 = now()
        self.phase: Optional[str] = None
        self.phase_t0 = self.t0
        self.phase_wall: Dict[str, float] = {}
        self.peak_mb = 0.0
        self._n = 0

    def begin(self, phase: str) -> None:
        self.end()
        if phase not in self.caps:
            raise KeyError(phase)
        self.phase, self.phase_t0 = phase, self.now()
        self.check(force_memory=True)

    def end(self) -> None:
        if self.phase is not None:
            self.phase_wall[self.phase] = round(self.phase_wall.get(self.phase, 0.0) + self.now() - self.phase_t0, 2)
            self.phase = None

    def elapsed(self) -> float:
        return self.now() - self.t0

    def check(self, force_memory: bool = False) -> None:
        t = self.now()
        if t - self.t0 > self.global_cap:
            raise CapStop(f"60-minute cap reached ({t - self.t0:.0f} s) in phase {self.phase}")
        if self.phase is not None and t - self.phase_t0 > self.caps[self.phase]:
            raise CapStop(f"wall cap of phase {self.phase} reached ({t - self.phase_t0:.0f} s > {self.caps[self.phase]} s)")
        self._n += 1
        if force_memory or self._n % 256 == 0:
            mb = self.memory()
            if mb is not None:
                self.peak_mb = max(self.peak_mb, mb)
                if mb > self.memory_cap:
                    raise CapStop(f"memory cap: {mb:.0f} MB > {self.memory_cap:.0f} MB private")

    def to_json(self) -> Dict[str, Any]:
        return {"elapsed_s": round(self.elapsed(), 1), "phase_wall_s": dict(self.phase_wall), "caps_s": dict(self.caps),
                "global_cap_s": self.global_cap, "peak_private_mb": round(self.peak_mb, 1)}


# -- identity, approval, backup coverage, preflight --------------------------------------------------------------------


def bench_choice(record: Optional[Mapping[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The benchmark's chosen (n_candidates, train_steps), or None when it did not fit or is absent."""
    rec = record if record is not None else (json.loads(BENCH_RECORD.read_text(encoding="utf-8"))
                                             if BENCH_RECORD.is_file() else None)
    if not rec or not rec.get("fits"):
        return None
    ch = rec.get("choice") or {}
    if ch.get("n_candidates") not in BENCH_CHOICES["n_candidates"] or ch.get("train_steps") not in BENCH_CHOICES["train_steps"]:
        return None
    return {"n_candidates": int(ch["n_candidates"]), "train_steps": int(ch["train_steps"])}


def discover_increments(root: Path = BACKUP_ROOT, base: Path = BACKUP_BASE, runs: Path = RUNS) -> Dict[str, Any]:
    """Every D: increment whose top-level verification record's source lies under runs/ (increments of other sources,
    such as logs/, are listed as skipped)."""
    sys.path.insert(0, str(RL / "tools"))
    import runs_backup as rb

    inc, skipped = [], []
    if Path(root).is_dir():
        for d in sorted(p for p in Path(root).iterdir() if p.is_dir() and p.resolve() != Path(base).resolve()):
            rec = d / rb.RECORD
            if not rec.is_file():
                skipped.append({"dest": str(d), "why": "no top-level verification record"})
                continue
            src = Path(json.loads(rec.read_text(encoding="utf-8")).get("source", ""))
            try:
                src.resolve().relative_to(Path(runs).resolve())
                inc.append(d)
            except ValueError:
                skipped.append({"dest": str(d), "why": f"source {src} is not under runs/"})
    return {"increments": inc, "skipped": skipped}


def combined_coverage() -> Dict[str, Any]:
    import m7s_gate as msg   # reused unchanged: the base + increment coverage walk

    disc = discover_increments()
    cov = msg.combined_coverage(RUNS, BACKUP_BASE, disc["increments"])
    cov["increments"] = [str(p) for p in disc["increments"]]
    cov["skipped"] = disc["skipped"]
    return cov


def identity(choice: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    import m7u_model as um

    choice = choice if choice is not None else bench_choice()
    return {"gate": "m7u1", "scope": ug.SCOPE, "rule": ur.RULE_ID, "rule_sha256": ur.rule_digest(),
            "planner_sha256": up.contract_digest(), "state_sha256": us.contract_digest(),
            "model_contract": um.MODEL_CONTRACT, "goal_contract": ug.GOAL_CONTRACT, "members": MEMBERS,
            "choice": dict(choice) if choice else None,
            "bench_sha256": sha256_file(BENCH_RECORD) if BENCH_RECORD.is_file() else None,
            "track_check_sha256": sha256_file(TRACK_RECORD) if TRACK_RECORD.is_file() else None,
            "executable_sha256": sha256_file(EXECUTABLE) if EXECUTABLE.is_file() else None,
            "code": {f"rl/{f}": sha256_file(RL / f) for f in CODE_FILES if (RL / f).is_file()},
            "tick_budget": TICK_BUDGET, "wall_caps_s": WALL_CAPS_S, "global_cap_s": GLOBAL_CAP_S,
            "memory_cap_mb": MEMORY_CAP_MB, "gate_seed": GATE_SEED, "p1": [list(p) for p in P1_TRACES],
            "replays": REPLAYS}


def approval_status() -> Tuple[bool, str]:
    if not APPROVAL.is_file():
        return False, f"no approval record at {APPROVAL.relative_to(REPO_ROOT)} (the gate is not authorised)"
    rec = json.loads(APPROVAL.read_text(encoding="utf-8"))
    if not str(rec.get("approval", "")).startswith("APPROVED"):
        return False, f"approval record says {rec.get('approval')!r}"
    want = identity()
    diffs = [k for k in ("rule_sha256", "planner_sha256", "state_sha256", "choice", "bench_sha256", "track_check_sha256",
                         "executable_sha256", "tick_budget", "wall_caps_s", "global_cap_s", "memory_cap_mb")
             if rec.get(k) != want[k]]
    diffs += [f"code:{f}" for f, h in want["code"].items() if (rec.get("code") or {}).get(f) != h]
    if diffs:
        return False, f"approval record does not match the current identity: {diffs[:8]}"
    return True, "approved"


def game_processes() -> List[int]:
    from m7_runtime import BATTLESHIP_IMAGE, list_processes_named

    return list(list_processes_named(BATTLESHIP_IMAGE) or [])


def preflight(*, run_unit: bool = True) -> Dict[str, Any]:
    problems: List[str] = []
    rep: Dict[str, Any] = {"utc": utc()}
    if GATE_ROOT.exists():
        problems.append(f"{GATE_ROOT.relative_to(REPO_ROOT)} exists (never overwritten)")
    if run_unit:
        for cmd, key in (([sys.executable, str(RL / "m7u_tests.py"), "unit"], "unit_suite"),
                         ([sys.executable, str(RL / "m7u_rule.py"), "self-test"], "rule_self_test")):
            r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)
            rep[key] = (r.stdout.strip().splitlines() or [r.stderr[-300:]])[-1:]
            if r.returncode != 0:
                problems.append(f"{key} failed")
    choice = bench_choice()
    rep["bench_choice"] = choice
    if choice is None:
        problems.append(f"no fitting benchmark choice in {BENCH_RECORD.relative_to(REPO_ROOT)}")
    track = json.loads(TRACK_RECORD.read_text(encoding="utf-8")) if TRACK_RECORD.is_file() else None
    rep["track_check"] = {k: (track or {}).get(k) for k in ("ok", "traces", "ticks_compared", "problems")}
    if not (track or {}).get("ok"):
        problems.append("the read-only clock-track check is missing or failed")
    cov = combined_coverage()
    rep["backup"] = {k: cov.get(k) for k in ("ok", "reason", "source_files", "uncovered", "increments", "skipped")}
    if not cov.get("ok"):
        problems.append(f"backup prerequisite not met: {cov.get('reason')}")
    procs = game_processes()
    if procs:
        problems.append(f"BattleShip already running: {procs}")
    if not EXECUTABLE.is_file():
        problems.append(f"missing executable {EXECUTABLE}")
    ok, why = approval_status()
    rep["approval"] = why
    if not ok:
        problems.append(why)
    rep["problems"] = problems
    rep["ok"] = not problems
    return rep


# -- the vectorised drive loop ------------------------------------------------------------------------------------------


@dataclass
class Task:
    rank: int
    entry: Dict[str, Any]
    controller: Optional[up.Controller]
    rows: List[np.ndarray] = field(default_factory=list)
    words: List[Tuple[int, int]] = field(default_factory=list)
    hist: Optional[np.ndarray] = None
    prefix_identity: Optional[Dict[str, Any]] = None
    evidence: List[Dict[str, Any]] = field(default_factory=list)   # evaluation only: one record per decision

    @property
    def t(self) -> int:
        return int(self.entry.get("t", 0)) if self.entry.get("kind") == "trial" else 0

    def in_prefix(self) -> bool:
        return self.entry.get("kind") == "trial" and len(self.words) < self.t


def controller_for(entry: Mapping[str, Any], n_candidates: int, goals: Optional[Sequence[ug.Goal]] = None) -> up.Controller:
    if entry["kind"] == "collect":
        return up.Controller(arm="collect", stream_key=f"m7u1|{GATE_SEED}|collect|{entry['entry']}", n_candidates=n_candidates)
    arm, k = entry["arm"], int(entry["goal_k"])
    key = f"m7u1|{GATE_SEED}|goal|{k}"                    # shared by the three arms of a goal (common random numbers)
    if arm == "RC":
        return up.Controller(arm="RC", stream_key=key, n_candidates=n_candidates, budget=int(entry["budget"]))
    target = goals[k] if arm == "P" else goals[ug.scrambled(k)]
    return up.Controller(arm=arm, stream_key=key, n_candidates=n_candidates, goal=(target.x, target.y),
                         budget=int(entry["budget"]))


def decision_record(task: Task, arr: np.ndarray, chosen: int, **predictions: np.ndarray) -> Dict[str, Any]:
    """Evidence of one decision, taken before the controller advances: the candidate words, the root native row and
    bookkeeping history the model started from, the choice, and (P / S only) the scores and every member's predicted
    trajectory of every candidate. RC records no prediction because it evaluates no model."""
    c = task.controller
    return {"decision": len(c.decisions), "at_tick": int(c.executed), "chosen": int(chosen),
            "candidates": np.asarray(arr).astype(np.int8), "root_row": np.array(task.rows[-1], dtype=np.float64),
            "root_hist": np.array(task.hist, dtype=np.float64), **predictions}


def plan_batch(model: Any, ctx: Any, items: Sequence[Tuple[Task, np.ndarray]]) -> None:
    import torch

    import m7u_model as um

    n = items[0][1].shape[0]
    rows = np.repeat(np.stack([t.rows[-1] for t, _ in items]), n, axis=0)
    hist = np.repeat(np.stack([t.hist for t, _ in items]), n, axis=0)
    plans = np.concatenate([a for _, a in items])
    roll = um.rollout(model, ctx, torch.tensor(rows), torch.tensor(hist), torch.tensor(plans))
    for b, (task, arr) in enumerate(items):
        sl = slice(b * n, (b + 1) * n)
        c = task.controller
        s, reach_at = up.score(roll.x[:, sl], roll.y[:, sl], roll.air[:, sl], roll.fall_at[:, sl], c.goal, c.remaining())
        j = int(torch.argmin(s))
        rec = decision_record(task, arr, j, scores=s.numpy().astype(np.float64),
                              reach_at=reach_at.numpy().astype(np.int16),
                              pred_x=roll.x[:, sl].numpy().astype(np.float32),
                              pred_y=roll.y[:, sl].numpy().astype(np.float32),
                              pred_air=roll.air[:, sl].numpy().astype(bool),
                              pred_fall_at=roll.fall_at[:, sl].numpy().astype(np.int16))
        c.choose(j, predicted_reach=int((reach_at[:, j] < up.H).sum()))
        task.evidence.append(rec)


def drive(venv: Any, configs: Mapping[int, Mapping[str, Any]], *, phase: str, ledger: Ledger, clock: Clock,
          n_candidates: int, goals: Optional[Sequence[ug.Goal]] = None, model: Any = None, ctx: Any = None,
          track: Optional[us.ClockTrack] = None) -> List[Dict[str, Any]]:
    """Drive every worker through its configured entries. Evaluation ledgers prefix and controlled ticks separately."""
    n = venv.num_envs
    ranks = [int(r) for r in getattr(venv, "ranks", range(n))]
    venv.env_method_each("m7u_configure", {i: ((dict(configs[ranks[i]]),), {}) for i in range(n)})
    venv.reset()
    by_entry = {e["entry"]: e for c in configs.values() for e in c["entries"]}
    results: List[Dict[str, Any]] = []

    def new_task(i: int, rec: Optional[Mapping[str, Any]]) -> Optional[Task]:
        if not rec or rec.get("idle"):
            return None
        e = by_entry[rec["entry"]]
        if rec.get("world_digest") != PINNED_WORLD_DIGEST:
            raise IntegrityStop(f"entry {rec['entry']}: reset world differs from the pinned stage table")
        row0 = np.array(rec["row"], dtype=np.float64)
        return Task(rank=ranks[i], entry=e, controller=controller_for(e, n_candidates, goals), rows=[row0],
                    hist=us.init_history(row0))

    tasks: List[Optional[Task]] = [new_task(i, (venv.reset_infos[i] or {}).get("m7u")) for i in range(n)]
    while any(t is not None for t in tasks):
        pending: List[Tuple[Task, np.ndarray]] = []
        for task in tasks:
            if task is None or task.in_prefix():
                continue
            c = task.controller
            if c.needs_decision():
                arr = c.prepare()
                if c.needs_model:
                    pending.append((task, arr))
                else:
                    rec = decision_record(task, arr, 0) if phase == "evaluation" else None
                    c.choose(0)
                    if rec is not None:
                        task.evidence.append(rec)
        if pending:
            plan_batch(model, ctx, pending)
        actions = np.zeros((n, 2), dtype=np.int64)
        n_pre = n_ctl = 0
        for i, task in enumerate(tasks):
            if task is None:
                continue
            if task.in_prefix():
                actions[i] = task.entry["prefix"][len(task.words)]
                n_pre += 1
            else:
                actions[i] = task.controller.next_word()
                n_ctl += 1
        if phase == "evaluation":
            ledger.check("eval_prefix", n_pre)
            ledger.check("eval_control", n_ctl)
        else:
            ledger.check(phase, n_pre + n_ctl)
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
            was_prefix = task.in_prefix()
            word = (int(actions[i, 0]), int(actions[i, 1]))
            row = np.array(rec["row"], dtype=np.float64)
            task.hist = us.advance_history(task.hist, task.rows[-1], word, row)
            task.rows.append(row)
            task.words.append(word)
            ledger.add(("eval_prefix" if was_prefix else "eval_control") if phase == "evaluation" else phase, 1)
            if "prefix_identity" in rec:
                task.prefix_identity = rec["prefix_identity"]
                if not rec["prefix_identity"].get("ok"):
                    raise IntegrityStop(f"entry {task.entry['entry']}: start state differs from the record "
                                        f"({rec['prefix_identity'].get('fields')})")
            if track is not None and row[us.F["valid"]] == 1.0:
                tk = track.at(np.array([int(row[us.F["input_tick"]])]))[0]
                cols = [us.F[c] for c in us.TRACK_COLUMNS]
                if any(not (np.isnan(a) and np.isnan(b)) and a != b for a, b in zip(row[cols][:4], tk[:4])):
                    raise IntegrityStop(f"entry {task.entry['entry']}: platform differs from the clock track")
            if dones[i]:
                summary = (infos[i] or {}).get("m7_episode") or {}
                results.append(_task_result(task, rec, summary))
                nxt = None if rec.get("idle_next") else new_task(i, (venv.reset_infos[i] or {}).get("m7u"))
                tasks[i] = nxt
    return results


def _task_result(task: Task, rec: Mapping[str, Any], summary: Mapping[str, Any]) -> Dict[str, Any]:
    c = task.controller
    return {"entry": task.entry["entry"], "kind": task.entry["kind"], "arm": task.entry.get("arm"),
            "goal_k": task.entry.get("goal_k"), "t": task.t, "rank": task.rank,
            "rows": np.stack(task.rows), "words": np.array(task.words, dtype=np.int64).reshape(-1, 2),
            "reach_tick": rec.get("reach_tick"), "truncation_reason": rec.get("truncation_reason"),
            "termination_reason": rec.get("termination_reason"), "prefix_identity": task.prefix_identity,
            "decisions": [d.at_tick for d in c.decisions] if c else [],
            "decision_log": [(d.at_tick, d.chosen, d.predicted_reach) for d in c.decisions] if c else [],
            "episode_id": summary.get("episode_id"), "artifact_dir": summary.get("artifact_dir"),
            "native_action_digest": summary.get("native_action_digest"), "startup_mode": summary.get("startup_mode"),
            "end_reason": summary.get("end_reason"), "cleared": bool(summary.get("cleared")),
            "sidecar": ((summary.get("m7u") or {}).get("sidecar")), "evidence": task.evidence}


# -- evidence files (uncompressed .npz for a predictable write time; the D: increment hashes them) ---------------------


def sha256_stream(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def save_transitions(path: Path, ts: Any, episodes: Sequence[Any]) -> Dict[str, Any]:
    """The per-tick model inputs exactly as the model consumed them (dense features, current / previous status indices)
    and their one-step targets. Row i is the recorded transition tick[i] -> tick[i] + 1 of episodes[episode_of[i]];
    only pairs of valid rows are transitions (the model never sees the others)."""
    import m7u_model as um

    ticks = [um.episode_transitions(e)[0] for e in episodes]
    tick = np.concatenate(ticks) if ticks else np.zeros(0, dtype=np.int64)
    if len(tick) != len(ts.cur):
        raise IntegrityStop(f"{path.name}: {len(tick)} transition ticks for {len(ts.cur)} inputs")
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, episode_ids=np.array([str(e.episode_id) for e in episodes]), episode_of=ts.episode_of, tick=tick,
             dense=ts.dense.numpy(), cur=ts.cur.numpy(), prev=ts.prev.numpy(),
             **{f"target_{k}": v.numpy() for k, v in ts.targets.items()})
    return {"file": path.name, "transitions": int(len(tick)), "episodes": len(episodes), "sha256": sha256_stream(path)}


def save_trial(directory: Path, r: Mapping[str, Any], goals: Sequence[ug.Goal]) -> Dict[str, Any]:
    """One evaluation trial: native rows and canonical words from tick 0 (the supplied prefix is words[:t]), bookkeeping
    histories, and every decision's candidate-selection record and predictions (P / S)."""
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
    k = int(r["goal_k"])
    arm = r["arm"]
    commanded = None if arm == "RC" else (goals[k] if arm == "P" else goals[ug.scrambled(k)])
    meta = {"entry": r["entry"], "arm": arm, "goal_k": k, "t": r["t"], "scored_goal": [goals[k].x, goals[k].y],
            "commanded_goal_k": None if commanded is None else commanded.k,
            "commanded_goal": None if commanded is None else [commanded.x, commanded.y],
            "stream_key": f"m7u1|{GATE_SEED}|goal|{k}", "model_evaluated": arm != "RC",
            "episode_id": r["episode_id"], "artifact_dir": str(r["artifact_dir"]), "reach_tick": r["reach_tick"],
            "truncation_reason": r["truncation_reason"], "termination_reason": r["termination_reason"],
            "prefix_identity": r["prefix_identity"], "native_action_digest": r["native_action_digest"],
            "scope": ug.SCOPE}
    path = Path(directory) / f"{r['entry']}.npz"
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, meta=np.frombuffer(json.dumps(meta, default=str).encode("utf-8"), dtype=np.uint8), **arrays)
    return {"file": path.name, "decisions": len(ev), "sha256": sha256_stream(path)}


# -- single-environment path (P1, storage check, exact replays) ---------------------------------------------------------


def run_single(env: Any, entries: Sequence[Mapping[str, Any]], *, phase: str, ledger: Ledger, clock: Clock
               ) -> List[Dict[str, Any]]:
    """Submit each replay entry's words through ONE worker stack (fresh process per entry, normal tick-0 reset)."""
    out = []
    try:
        env.trial.m7u_configure({"mode": "replay", "entries": list(entries), "phase": phase})
        for e in entries:
            _obs, info = env.reset()
            rr = info.get("m7u") or {}
            if rr.get("world_digest") != PINNED_WORLD_DIGEST:
                raise IntegrityStop(f"entry {e['entry']}: reset world differs from the pinned stage table")
            rows = [np.array(rr["row"], dtype=np.float64)]
            sent, summary, rec = 0, {}, {}
            for w in e["words"]:
                ledger.check(phase, 1)
                clock.check()
                _o, _r, term, trunc, info = env.step(np.array(w, dtype=np.int64))
                ledger.add(phase, 1)
                sent += 1
                rec = info.get("m7u") or {}
                rows.append(np.array(rec["row"], dtype=np.float64))
                if term or trunc:
                    summary = info.get("m7_episode") or {}
                    break
            out.append({"entry": e["entry"], "sent": sent, "words": len(e["words"]), "rows": np.stack(rows),
                        "reach_tick": rec.get("reach_tick"), "truncation_reason": rec.get("truncation_reason"),
                        "termination_reason": rec.get("termination_reason"),
                        "native_action_digest": summary.get("native_action_digest"),
                        "artifact_dir": summary.get("artifact_dir"), "episode_id": summary.get("episode_id")})
    finally:
        env.close()
    return out


def artifact_track1_words(artifact_dir: Any) -> List[Tuple[int, int]]:
    """The canonical native words of a preserved artifact, as Track 1 indices (replay truth -> the same words)."""
    import m7f_trace as mt
    from btt_learning import native_to_track1

    art = Path(artifact_dir)
    art = art if art.is_absolute() else REPO_ROOT / art
    acts, _meta = mt.artifact_actions(art)
    return [tuple(int(v) for v in native_to_track1(b, x, y)) for (b, x, y, _t) in acts]


def resolve(p: Any) -> Path:
    q = Path(p)
    return q if q.is_absolute() else REPO_ROOT / q


# -- the gate -------------------------------------------------------------------------------------------------------------


def real_venv_factory(root: Path, run_id: str, role: str, settings: Any) -> Any:
    import m7u_worker as uw
    from btt_parallel import RunCoordinator, initial_coordination_state
    from m7_runtime import prepare_worker_runtime, validate_port_blocks
    from m7_vec_env import M7SubprocVecEnv

    root = Path(root).resolve()
    if root.exists():
        raise IntegrityStop(f"{root} exists (never overwritten)")
    coord = root / "coordination"
    RunCoordinator.create(coord, initial_coordination_state(run_id, role, None))
    validate_port_blocks(range(uw.N_WORKERS), settings.port_block_base, settings.port_block_size)
    factories = []
    for rank in range(uw.N_WORKERS):
        spec = uw.worker_spec(root, rank, run_id, role, settings, coord)
        prepare_worker_runtime(Path(spec.worker_dir) / "runtime", Path(settings.executable))
        factories.append(uw.M7uWorkerFactory(spec))
    return M7SubprocVecEnv(factories, step_timeout=settings.step_timeout)


def real_env_factory(root: Path, run_id: str, role: str, settings: Any) -> Any:
    import m7u_worker as uw
    from btt_parallel import RunCoordinator, initial_coordination_state
    from m7_runtime import prepare_worker_runtime

    root = Path(root).resolve()
    coord = root / "coordination"
    RunCoordinator.create(coord, initial_coordination_state(run_id, role, None))
    spec = uw.worker_spec(root, 0, run_id, role, settings, coord)
    prepare_worker_runtime(Path(spec.worker_dir) / "runtime", Path(settings.executable))
    return uw.build_worker_env_m7u(spec)


def collection_configs(n_workers: int) -> Dict[int, Dict[str, Any]]:
    cfg: Dict[int, Dict[str, Any]] = {r: {"mode": "collect", "phase": "collection", "entries": []} for r in range(n_workers)}
    for i in range(N_COLLECT):
        cfg[i % n_workers]["entries"].append({"entry": f"c{i:03d}", "kind": "collect"})
    return cfg


def evaluation_configs(goals: Sequence[ug.Goal], n_workers: int) -> Dict[int, Dict[str, Any]]:
    cfg: Dict[int, Dict[str, Any]] = {r: {"mode": "trial", "phase": "evaluation", "entries": []} for r in range(n_workers)}
    order = []
    for g in goals:
        arms = ["P", "RC", "S"]
        rot = g.k % 3
        for arm in arms[rot:] + arms[:rot]:
            order.append((g, arm))
    for i, (g, arm) in enumerate(order):
        cfg[i % n_workers]["entries"].append({
            "entry": f"g{g.k:02d}_{arm}", "kind": "trial", "arm": arm, "goal_k": g.k, "t": g.t, "budget": ug.BUDGET,
            "goal": [g.x, g.y], "prefix": [list(w) for w in g.prefix],
            "expected_start_row": [None if np.isnan(v) else v for v in g.expected_start_row]})
    return cfg


def _episodes_from(results: Sequence[Mapping[str, Any]]) -> List[Any]:
    import m7u_model as um

    return [um.Episode(episode_id=str(r["episode_id"]), rows=r["rows"], words=r["words"],
                       fell=r.get("termination_reason") == "native_failure") for r in results]


def run_gate(*, settings: Any, choice: Mapping[str, Any], root: Path, venv_factory: Callable[..., Any],
             env_factory: Callable[..., Any], clock: Clock, ledger: Optional[Ledger] = None,
             p1_entries: Optional[Sequence[Mapping[str, Any]]] = None, n_workers: int = 5,
             artifact_words: Callable[[Any], List[Tuple[int, int]]] = artifact_track1_words,
             read_sidecar: Optional[Callable[[Any], Mapping[str, Any]]] = None) -> Dict[str, Any]:
    """Every phase in order under the caps. Returns the state (with `decision`). Factories are injectable only so the
    offline tests can drive this exact code with synthetic workers; `cmd_run` passes the real ones."""
    import torch

    import m7u_analysis as ua
    import m7u_model as um
    import m7u_worker as uw

    torch.set_num_threads(max(1, (os.cpu_count() or 6)))
    read_sidecar = read_sidecar or (lambda d: uw.read_sidecar(resolve(d)))
    ledger = ledger or Ledger()
    n_cand, steps = int(choice["n_candidates"]), int(choice["train_steps"])
    state: Dict[str, Any] = {"started_utc": utc(), "scope": ug.SCOPE, "choice": dict(choice), "phases": {},
                             "integrity": {"problems": []}}
    state_dir = Path(root) / "_gate"

    def save() -> None:
        state["ledger"] = ledger.to_json()
        state["clock"] = clock.to_json()
        write_json(state_dir / "state.json", state)

    def finish(outcome: Dict[str, Any]) -> Dict[str, Any]:
        clock.end()
        state["decision"] = outcome
        state["finished_utc"] = utc()
        save()
        return state

    try:
        # P1: live identity of the pinned artifacts through the M7u stack
        clock.begin("p1")
        entries = list(p1_entries) if p1_entries is not None else p1_expected()
        res = run_single(env_factory(Path(root) / "p1", "m7u1_p1", "identity", settings), entries, phase="p1",
                         ledger=ledger, clock=clock)
        p1 = [{"entry": r["entry"], "sent": r["sent"], "words": r["words"],
               "identical": r["sent"] == r["words"] and artifact_words(r["artifact_dir"]) == [tuple(w) for w in e["words"]]}
              for r, e in zip(res, entries)]
        state["phases"]["p1"] = p1
        save()
        if not all(p["identical"] for p in p1):
            raise IntegrityStop("P1: the pinned artifacts were not reproduced word for word")
        # collection (RC behaviour episodes)
        clock.begin("collection")
        venv = venv_factory(Path(root) / "collection", "m7u1_collect", "collect", settings)
        try:
            coll = drive(venv, collection_configs(n_workers), phase="collection", ledger=ledger, clock=clock,
                         n_candidates=n_cand)
        finally:
            venv.close()
        state["phases"]["collection"] = {"episodes": len(coll), "ticks": ledger.used["collection"],
                                         "startup_modes": sorted({str(r["startup_mode"]) for r in coll})}
        if len(coll) != N_COLLECT:
            raise IntegrityStop(f"collection produced {len(coll)} of {N_COLLECT} episodes")
        problems = []
        for r in coll:                                    # RC == behaviour: regenerate every word stream offline
            regen = up.rc_words(f"m7u1|{GATE_SEED}|collect|{r['entry']}", n_cand, len(r["words"]))
            if [tuple(w) for w in r["words"]] != regen:
                problems.append(f"{r['entry']}: words differ from the RC regeneration")
            side = read_sidecar(r["artifact_dir"])
            if uw.rows_equal(side["rows"].reshape(-1), r["rows"].reshape(-1)) or len(side["rows"]) != len(r["rows"]):
                problems.append(f"{r['entry']}: sidecar rows differ from the streamed rows")
        ids = [str(r["episode_id"]) for r in coll]
        train_ids, held_ids = ug.heldout_split(ids)
        train = [r for r in coll if str(r["episode_id"]) in set(train_ids)]
        held = [r for r in coll if str(r["episode_id"]) in set(held_ids)]
        track, tprob = us.build_clock_track([r["rows"] for r in train])
        problems += [f"clock track: {p}" for p in tprob]
        for r in held:
            v = r["rows"][r["rows"][:, us.F["valid"]] == 1.0]
            try:
                tk = track.at(v[:, us.F["input_tick"]].astype(np.int64))
            except us.StateError as exc:
                problems.append(f"held-out {r['entry']}: {exc}")
                continue
            cols = [us.F[c] for c in us.TRACK_COLUMNS[:4]]
            if not np.array_equal(v[:, cols], tk[:, :4]):
                problems.append(f"held-out {r['entry']}: platform differs from the clock track")
        state["integrity"]["collection"] = {"problems": problems, "track_sha256": track.digest(),
                                            "train_ids": train_ids, "heldout_ids": held_ids}
        held_set = set(held_ids)
        write_json(state_dir / "collection.json", {"scope": ug.SCOPE, "train_ids": train_ids, "heldout_ids": held_ids,
                                                   "episodes": [{
            "entry": r["entry"], "episode_id": r["episode_id"],
            "split": "heldout" if str(r["episode_id"]) in held_set else "train", "rank": r["rank"],
            "ticks": int(len(r["words"])), "stream_key": f"m7u1|{GATE_SEED}|collect|{r['entry']}",
            "artifact_dir": str(r["artifact_dir"]), "sidecar": r["sidecar"],
            "native_action_digest": r["native_action_digest"], "startup_mode": r["startup_mode"],
            "termination_reason": r["termination_reason"], "truncation_reason": r["truncation_reason"],
            "end_reason": r["end_reason"], "cleared": r["cleared"]} for r in coll]})
        save()
        if problems:
            raise IntegrityStop(f"collection integrity: {problems[:3]}")
        # storage check: one training episode replayed from tick 0
        clock.begin("storage")
        first = sorted(train, key=lambda r: ug.sha(f"m7u1|storage|{r['episode_id']}"))[0]
        words = artifact_words(first["artifact_dir"])
        sres = run_single(env_factory(Path(root) / "storage", "m7u1_storage", "storage", settings),
                          [{"entry": first["entry"], "kind": "collect", "words": [list(w) for w in words]}],
                          phase="storage", ledger=ledger, clock=clock)[0]
        side = read_sidecar(first["artifact_dir"])
        diff = sorted({f for a, b in zip(side["rows"], sres["rows"]) for f in uw.rows_equal(a, b)})
        st_ok = len(sres["rows"]) == len(side["rows"]) and not diff and words == [tuple(w) for w in first["words"]]
        state["phases"]["storage"] = {"entry": first["entry"], "ok": st_ok, "fields_differing": diff[:12],
                                      "ticks": sres["sent"]}
        save()
        if not st_ok:
            raise IntegrityStop("storage check failed")
        # goals (frozen before training)
        clock.begin("train")
        table = ug.chance_table([(r["rows"], r.get("termination_reason") == "native_failure") for r in train])
        try:
            sel = ug.select_goals({str(r["episode_id"]): (r["rows"], r["words"], r.get("termination_reason") == "native_failure")
                                   for r in held}, table)
        except ug.GoalError as exc:
            if exc.incomplete:
                raise CapStop(f"goal availability: {exc}") from exc
            raise
        goals: List[ug.Goal] = sel["goals"]
        write_json(state_dir / "goals.json", {"record": sel["record"], "goals": [g.to_json() for g in goals],
                                              "digest": ug.goals_digest(goals)})
        state["phases"]["goals"] = dict(sel["record"], digest=ug.goals_digest(goals))
        save()
        # training
        episodes = _episodes_from(train)
        next_rows = np.concatenate([e.rows[1:] for e in episodes])
        vocab = um.build_vocab(next_rows)
        ctx = um.make_context(vocab, us.static_world_pinned(), track)
        ts = um.build_transitions(ctx, episodes)
        held_eps = _episodes_from(held)
        hold = um.build_transitions(ctx, held_eps)
        state["evidence"] = {"model_inputs_train": save_transitions(state_dir / "model_inputs_train.npz", ts, episodes),
                             "model_inputs_heldout": save_transitions(state_dir / "model_inputs_heldout.npz", hold,
                                                                      held_eps)}
        save()
        model = um.DynamicsEnsemble(vocab, members=MEMBERS, seed=GATE_SEED)

        def stop() -> Optional[str]:
            try:
                clock.check()
            except CapStop as exc:
                return str(exc)
            return None

        tr = um.train(model, ctx, ts, steps=steps, seed=GATE_SEED, heldout=hold, should_stop=stop)
        if tr.stopped:
            raise CapStop(tr.stopped)
        digest = um.save(model, vocab, state_dir / "model.pt", meta={"steps": tr.steps, "choice": dict(choice)})
        pdig = um.parameter_digest(model)
        state["phases"]["train"] = {"steps": tr.steps, "wall_s": tr.wall_s, "log": tr.log, "model_sha256": digest,
                                    "parameter_digest": pdig, "vocab": {"S": vocab.S, "V3": vocab.V3, "V4": vocab.V4},
                                    "transitions": len(ts.cur), "heldout_transitions": len(hold.cur)}
        save()
        # evaluation
        clock.begin("evaluation")
        model.eval()
        venv = venv_factory(Path(root) / "evaluation", "m7u1_eval", "evaluation", settings)
        try:
            trials = drive(venv, evaluation_configs(goals, n_workers), phase="evaluation", ledger=ledger, clock=clock,
                           n_candidates=n_cand, goals=goals, model=model, ctx=ctx, track=track)
        finally:
            venv.close()
        if um.parameter_digest(model) != pdig:
            raise IntegrityStop("model parameters changed during evaluation")
        if len(trials) != ug.N_GOALS * 3:
            raise IntegrityStop(f"{len(trials)} of {ug.N_GOALS * 3} trials finished")
        by = {(r["goal_k"], r["arm"]): r for r in trials}
        outcomes = {arm: [by[(k, arm)]["reach_tick"] is not None and by[(k, arm)]["truncation_reason"] == uw.END_GOAL
                          for k in range(ug.N_GOALS)] for arm in ("P", "RC", "S")}
        state["evidence"]["trials"] = {r["entry"]: save_trial(state_dir / "trials", r, goals) for r in trials}
        state["phases"]["evaluation"] = {
            "trials": [{k: v for k, v in r.items() if k not in ("rows", "words", "evidence")} for r in trials],
            "outcomes": outcomes, "clears": sum(1 for r in trials if r["cleared"]),
            "ticks": {"prefix": ledger.used["eval_prefix"], "control": ledger.used["eval_control"]}}
        save()
        # reported diagnostics (forward passes only) and exact replays
        clock.begin("replays_analysis")
        trial_eps = [um.Episode(episode_id=r["entry"], rows=r["rows"], words=r["words"],
                                fell=r.get("termination_reason") == "native_failure") for r in trials]
        state["evidence"]["model_inputs_trials"] = save_transitions(
            state_dir / "model_inputs_trials.npz", um.build_transitions(ctx, trial_eps), trial_eps)
        save()
        diag: Dict[str, Any] = {}
        attr = {}
        for k in range(ug.N_GOALS):
            r = by[(k, "P")]
            attr[k] = ua.trial_attribution(model, ctx, {"rows": r["rows"], "words": r["words"], "t": r["t"],
                                                        "goal": (goals[k].x, goals[k].y), "decisions": r["decisions"],
                                                        "reached": outcomes["P"][k]})
        fails = [k for k in range(ug.N_GOALS) if not outcomes["P"][k]]
        starts = np.stack([goals[k].expected_start_row for k in range(ug.N_GOALS)]).astype(np.float64)
        hists = np.stack([us.history_sequence(by[(k, "P")]["rows"][:goals[k].t + 1],
                                              [tuple(w) for w in by[(k, "P")]["words"][:goals[k].t]])[-1]
                          for k in range(ug.N_GOALS)])
        wit = ua.witness_accepted(model, ctx, goals, starts, hists)
        m_share = (sum(1 for k in fails if attr[k]["class"] == "MODEL") / len(fails)) if fails else None
        w_share = (sum(1 for k in fails if wit[k]) / len(fails)) if fails else None
        flags = {f"{k}:{arm}": ua.ambiguity_flags(by[(k, arm)]["rows"], goals[k].t)
                 for k in range(ug.N_GOALS) for arm in ("P", "RC", "S")}
        clean = [k for k in fails if not flags[f"{k}:P"]["any"]]
        m_clean = (sum(1 for k in clean if attr[k]["class"] == "MODEL") / len(clean)) if clean else None
        diag.update({"attribution": {str(k): v for k, v in attr.items()}, "model_share": m_share,
                     "model_share_unflagged": m_clean, "unflagged_failures": len(clean),
                     "witness_share": w_share, "witness_all": int(wit.sum()), "ambiguity": flags})
        diag["heldout_accuracy"] = ua.heldout_accuracy(model, ctx, _episodes_from(held))
        errs: Dict[str, List[np.ndarray]] = {"executed": [], "executed_spread": [], "heldout": [], "heldout_spread": []}
        for arm in ("P", "S"):
            for k in range(ug.N_GOALS):
                r = by[(k, arm)]
                hs = us.history_sequence(r["rows"], [tuple(int(v) for v in w) for w in r["words"]])
                e_, s_ = ua.block_errors(model, ctx, r["rows"], hs, r["words"], [r["t"] + a for a in r["decisions"]])
                errs["executed"].append(e_)
                errs["executed_spread"].append(s_)
        for r in held:
            hs = us.history_sequence(r["rows"], [tuple(int(v) for v in w) for w in r["words"]])
            starts = [s for s in range(0, len(r["words"]) - up.EXEC, 64) if r["rows"][s:s + up.EXEC + 1, us.F["valid"]].all()]
            e_, s_ = ua.block_errors(model, ctx, r["rows"], hs, r["words"], starts)
            errs["heldout"].append(e_)
            errs["heldout_spread"].append(s_)
        cal = {}
        for name in ("executed", "heldout"):
            e_ = np.concatenate(errs[name]) if errs[name] else np.zeros(0)
            s_ = np.concatenate(errs[f"{name}_spread"]) if errs[name] else np.zeros(0)
            cal[name] = {"blocks": int(len(e_)), "error_gt_box": int((e_ > up.BOX).sum()),
                         "auroc_spread": ua.auroc(s_, e_ > up.BOX),
                         "error_median": float(np.median(e_)) if len(e_) else None}
        diag["calibration"] = cal
        state["phases"]["diagnostics"] = diag
        save()
        replays = []
        entries_by_id = {e["entry"]: e for e in evaluation_configs(goals, 1)[0]["entries"]}
        for arm, cap in REPLAYS.items():
            wins = [k for k in range(ug.N_GOALS) if outcomes[arm][k]][:cap]
            for k in wins:
                r = by[(k, arm)]
                words = artifact_words(r["artifact_dir"])
                entry = dict(entries_by_id[r["entry"]])
                entry["words"] = [list(w) for w in words]
                rr = run_single(env_factory(Path(root) / "replays" / r["entry"], "m7u1_replay", "replay", settings),
                                [entry], phase="replays", ledger=ledger, clock=clock)[0]
                orig = read_sidecar(r["artifact_dir"])
                diff = sorted({f for a, b in zip(orig["rows"], rr["rows"]) for f in uw.rows_equal(a, b)})
                ok = (rr["native_action_digest"] == r["native_action_digest"] and rr["reach_tick"] == r["reach_tick"]
                      and len(rr["rows"]) == len(orig["rows"]) and not diff and words == [tuple(w) for w in r["words"]])
                replays.append({"entry": r["entry"], "ok": ok, "reach_tick": rr["reach_tick"], "fields_differing": diff[:12]})
        state["phases"]["replays"] = replays
        save()
        integrity_ok = all(r["ok"] for r in replays)
        if not integrity_ok:
            state["integrity"]["problems"].append("a success replay was not exact")
        decision = ur.apply(outcomes, integrity_ok=integrity_ok)
        decision["null_reading"] = ur.null_reading(decision, model_share=m_share, witness_share=w_share)
        decision["summary"] = (f"m7u1 ({ug.SCOPE}): {decision['outcome']}; P {decision.get('n', {}).get('P')}, "
                               f"RC {decision.get('n', {}).get('RC')}, S {decision.get('n', {}).get('S')} of {ug.N_GOALS}")
        bad = ur.scope_problems(decision["summary"].replace(ug.SCOPE, ""))
        if bad:
            raise IntegrityStop(f"decision summary uses forbidden wording {bad}")
        return finish(decision)
    except CapStop as exc:
        return finish(ur.apply({}, integrity_ok=True, incomplete=str(exc)))
    except IntegrityStop as exc:
        state["integrity"]["problems"].append(str(exc))
        return finish(ur.apply({}, integrity_ok=False))


def p1_expected() -> List[Dict[str, Any]]:
    import m7f_trace as mt

    out = []
    for name, n in P1_TRACES:
        tr = mt.read_trace(PINNED_DIR / name)
        words = artifact_track1_words(tr["artifact"])
        if len(words) != n:
            raise IntegrityStop(f"P1 {name}: {len(words)} words, pinned {n}")
        out.append({"entry": name, "kind": "collect", "words": [list(w) for w in words]})
    return out


def cmd_run() -> int:
    from m7_runtime import install_kill_on_close_job
    import m7u_worker as uw

    pf = preflight()
    if not pf["ok"]:
        print(json.dumps(pf, indent=1, default=str))
        print("refused: preflight problems (see above); nothing was launched")
        return 2
    install_kill_on_close_job()
    state = run_gate(settings=uw.env_settings(), choice=bench_choice(), root=GATE_ROOT, venv_factory=real_venv_factory,
                     env_factory=real_env_factory, clock=Clock())
    print(json.dumps(state.get("decision"), indent=1, default=str)[:4000])
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    p = sub.add_parser("preflight")
    p.add_argument("--skip-unit", action="store_true")
    sub.add_parser("approval-template")
    sub.add_parser("run")
    a = ap.parse_args(argv)
    if a.cmd == "status":
        print(json.dumps({"identity": identity(), "approval": approval_status()[1],
                          "gate_root_exists": GATE_ROOT.exists()}, indent=1, default=str))
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
