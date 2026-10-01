#!/usr/bin/env python3
"""M7u2 gate `m7u2` driver (proposed; design: docs/rl_model_planning_m7u2_tick0_proposal_2026-09-30.md). NOT
AUTHORISED TO RUN: `run` refuses without an APPROVED record matching the current identity, and preparation creates no
such record.

    python rl/m7u2_gate.py status
    python rl/m7u2_gate.py preflight [--skip-unit]   # no game: tests, frozen-model checks, D: coverage, readiness
    python rl/m7u2_gate.py approval-template         # prints the record a reviewer would write (never writes it)
    python rl/m7u2_gate.py run                       # refused unless preflight passes

SCOPE: a proposed test of rare airborne-point reach initiated from the normal tick-0 reset, with the frozen m7u1 model
on one seed. Never reported as a landing, a crossing, a target result or a clear. m7u1's PASS and its scope (local
control after self-generated supplied prefixes) are unchanged.

`run` works in phases, under one native-tick ledger (at most 56,930 ticks, identity checks and replays included) and
one 40-minute cap from launch, with per-phase caps:
- **P1 identity:** m7u1's g26_P and g14_P replayed from tick 0. Words, every stored row field, the reach tick and the
  action digest must equal the m7u1 records.
- **Goal-source pool:** exactly 360 behaviour episodes of at most 128 words, from the normal reset.
- **Goal selection:** 24 goals, from the pool only. Fewer means INCOMPLETE.
- **Evaluation:** 24 goals x P / RC / S from the normal tick-0 reset, with no prefix, for at most 128 words each.
- **Diagnostics** (forward passes only).
- **Exact success replays.**
- **Rule** `m7u2_tick0_rule_v1`, applied once.

The frozen model is never updated:
- no optimizer can be constructed during the run;
- the parameters do not require gradients;
- the parameter digest is checked at preflight, before and after evaluation, and after analysis.

Outcomes:
- a cap stop or too few goals is INCOMPLETE: no retry, extension or relaxed eligibility;
- an integrity failure is INVALID.

The native RNG is never inspected; seeds are Python-side only. The driver never commits, pushes or deletes evidence.
"""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import dataclasses
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402

import m7u2_goals as g2  # noqa: E402
import m7u2_rule as r2  # noqa: E402
import m7u_gate as g1  # noqa: E402   (generic ledger, clock, single-env replay, planning and evidence helpers)
import m7u_goals as ug  # noqa: E402   (m7u1's goals, read for P1 and the decision-reproduction check only)
import m7u_planner as up  # noqa: E402
import m7u_state as us  # noqa: E402

CapStop, IntegrityStop = g1.CapStop, g1.IntegrityStop

REPO_ROOT = Path(__file__).resolve().parent.parent
RL = REPO_ROOT / "rl"
RUNS = REPO_ROOT / "runs"
GATE_ROOT = RUNS / "m7u2" / "gate"
APPROVAL = REPO_ROOT / "docs" / "rl_model_planning_m7u2_gate_approval.json"
M7U1 = RUNS / "m7u" / "gate" / "_gate"
MODEL_PATH = M7U1 / "model.pt"
EXECUTABLE = g1.EXECUTABLE
GATE = "m7u2"
GATE_SEED = 0
N_CANDIDATES = 64
N_WORKERS = 5

# Frozen m7u1 identity (runs/m7u, committed record in docs/rl_model_planning_m7u_gate_results_2026-09-30.md).
PIN: Dict[str, Any] = {
    "model_sha256": "a4bd30e51d379e57c070b6728f494f8abf52814efade2ae67ac39186e082e6fd",
    "parameter_digest": "0e70af78f1bec21039fa65f6f35ed180d69b31a02dd482480b946aced1bc0156",
    "vocab": {"S": 61, "V3": 16, "V4": 28}, "members": 3,
    "track_sha256": "16318edf0902749a267db9b89903f163df90df16713d441ef42b192aea6c6534",
    "planner_sha256": "e1f9bc8fe4606a8eb2092da109b7ac00a356aaa15a2c5a734b2cd6413a44fa3b",
    "state_sha256": "7c29113386d327edef77ecbc9e00b984c3f4e3c1acf00c742daaa6f42e98e6b7",
    "world_digest": "ca1ac287141d02c112eee70263c59b773af0054de690da68f0ee248dc91f72e4",
    "executable_sha256": "30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee",
    "m7u1_state_sha256": "29f0d70f1043207ec64ae7049c61cdeb694f6ead5fd6ae18c390eebbb5bd91cd",
    "m7u1_goals_sha256": "8e14e9f8f6bcb4a3992d615f5ed5d1df70b3bcd4f195ce34f13d690211acc636",
    "m7u1_collection_sha256": "46d17d5092b5dbf7aa24563e9633228c8c97e863ee495c9bdc887a8e39c467e0",
    "reference_digest": "4337cc35beebb23e342c11a2490ae72ed57495b9eb856e0d4f9eb9bc81ab912b",
    "tick0_row_digest": "0bf8dbd7b03ab2e418a98c2cb9e20208f4fb1597023c12686a3d5921d5e67686",
    "p1": {"g26_P": {"words": 171, "reach_tick": 171,
                     "native_action_digest": "3b3bd40209cd8e0ed1a9415746d37bba5458cd1144aabad2a06c6b41bf518928"},
           "g14_P": {"words": 183, "reach_tick": 183,
                     "native_action_digest": "33087dc8a6e98bb1f9b716c92736906871f46bf64f17d27cea64cb61ae4a0d30"}},
}
REPLAYS = {"P": 6, "RC": 2, "S": 2}
TICK_BUDGET = {"p1": sum(v["words"] for v in PIN["p1"].values()),                        # 354
               "pool": g2.POOL_EPISODES * g2.POOL_TICKS,                                  # 46,080
               "eval_control": g2.N_GOALS * 3 * g2.BUDGET,                                # 9,216
               "replays": sum(REPLAYS.values()) * g2.BUDGET}                              # 1,280
TICK_BUDGET["total"] = sum(TICK_BUDGET.values())                                           # 56,930
WALL_CAPS_S = {"p1": 120, "pool": 600, "goals": 120, "evaluation": 1200, "replays_analysis": 300}
GLOBAL_CAP_S = 2400
MEMORY_CAP_MB = 3072
READINESS = {"min_available_mb": 4096, "min_commit_free_mb": 10240, "probe_decisions": 40, "probe_warmup": 5,
             "probe_p95_max_s": 0.5}
# 32 fixed recorded m7u1 decisions: (goal k, arm, 'first' | 'middle'), re-scored with the frozen model at preflight.
REPRO_DECISIONS = tuple((k, arm, which) for k in range(0, 40, 5) for arm in ("P", "S") for which in ("first", "middle"))
REPRO_TOLERANCE = 1e-3
CODE_FILES = ("m7u2_goals.py", "m7u2_rule.py", "m7u2_gate.py", "m7u2_tests.py",
              "m7u_state.py", "m7u_model.py", "m7u_planner.py", "m7u_goals.py", "m7u_rule.py", "m7u_analysis.py",
              "m7u_worker.py", "m7u_gate.py", "m7u_tests.py", "btt_parallel.py", "battleship_env.py", "run_artifacts.py",
              "m7_vec_env.py", "m7_runtime.py", "m7n_obs.py", "m7q_obs.py", "m7q_input.py", "m7g_spatial.py",
              "m7n_entity.py", "m7q_status_table.py", "m7r_commit.py", "experiment_config.py", "m7_trainer.py",
              "m7f_trace.py", "btt_learning.py", "m7s_gate.py", "tools/runs_backup.py",
              "configs/m7q/m7q_pilot_s0.toml")


def utc() -> str:
    return g1.utc()


# -- the frozen m7u1 model and its sources (read-only) -----------------------------------------------------------------


@dataclasses.dataclass
class M7u1Sources:
    """The m7u1 records this gate reads (never writes): its 92 behaviour episodes (the chance reference, the tick-0
    record and the training split that rebuilds the clock track), its goals and its trial records."""
    episodes: List[Tuple[str, np.ndarray, np.ndarray, bool]]      # (id, rows, words, fell), collection.json order
    train_ids: List[str]
    goals: List[Dict[str, Any]]
    trials: Dict[str, Dict[str, Any]]


def load_m7u1_sources(root: Path = M7U1, *, check_pins: bool = True) -> M7u1Sources:
    for name, key in (("state.json", "m7u1_state_sha256"), ("goals.json", "m7u1_goals_sha256"),
                      ("collection.json", "m7u1_collection_sha256")):
        if check_pins and g1.sha256_file(root / name) != PIN[key]:
            raise IntegrityStop(f"m7u1 record {name} differs from its pinned sha256")
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    coll = json.loads((root / "collection.json").read_text(encoding="utf-8"))
    eps = []
    for e in coll["episodes"]:
        d = g1.resolve(e["artifact_dir"])
        with np.load(d / e["sidecar"]) as z:
            eps.append((str(e["episode_id"]), z["rows"], z["words"].astype(np.int64),
                        e["termination_reason"] == "native_failure"))
    goals = json.loads((root / "goals.json").read_text(encoding="utf-8"))["goals"]
    trials = {t["entry"]: t for t in state["phases"]["evaluation"]["trials"]}
    return M7u1Sources(episodes=eps, train_ids=list(state["integrity"]["collection"]["train_ids"]), goals=goals,
                       trials=trials)


def tick0_row(src: M7u1Sources) -> np.ndarray:
    row0 = np.array(src.episodes[0][1][0], dtype=np.float64)
    for eid, rows, _w, _f in src.episodes:
        same = (rows[0] == row0) | (np.isnan(rows[0]) & np.isnan(row0))
        if not same.all():
            raise IntegrityStop(f"m7u1 episode {eid}: tick-0 row differs from the others")
    return row0


def reference(src: M7u1Sources) -> g2.Reference:
    ref = g2.Reference([(eid, rows, fell) for eid, rows, _w, fell in src.episodes])
    if ref.n != g2.REF_EPISODES:
        raise IntegrityStop(f"reference has {ref.n} episodes, pinned {g2.REF_EPISODES}")
    return ref


@dataclasses.dataclass
class Frozen:
    model: Any
    vocab: Any
    ctx: Any
    track: Any


def parameter_digest(model: Any) -> str:
    import m7u_model as um

    return um.parameter_digest(model)


def load_frozen(src: M7u1Sources, path: Path = MODEL_PATH, *, pins: Mapping[str, Any] = PIN) -> Frozen:
    """The frozen ensemble with every pin checked: file, parameters, vocabulary, members, clock track rebuilt from the
    preserved m7u1 training sidecars. Gradients are switched off; the model is put in eval mode."""
    import m7u_model as um

    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != pins["model_sha256"]:
        raise IntegrityStop(f"{path}: model file differs from the pinned m7u1 model")
    model, vocab, _meta = um.load(path)
    if um.parameter_digest(model) != pins["parameter_digest"]:
        raise IntegrityStop("frozen model parameter digest differs from the pin")
    if {"S": vocab.S, "V3": vocab.V3, "V4": vocab.V4} != pins["vocab"] or model.members != pins["members"]:
        raise IntegrityStop("frozen model vocabulary or member count differs from the pin")
    for p in model.parameters():
        p.requires_grad_(False)
    model.eval()
    by_id = {eid: rows for eid, rows, _w, _f in src.episodes}
    track, probs = us.build_clock_track([by_id[i] for i in src.train_ids])
    if probs or track.digest() != pins["track_sha256"]:
        raise IntegrityStop("the clock track rebuilt from the m7u1 training sidecars differs from the pin")
    try:                                          # imagination from the last controlled tick reaches 128 + 64
        track.at(np.arange(0, g2.BUDGET + up.H + 1))
    except us.StateError as exc:
        raise IntegrityStop(f"the frozen clock track does not cover input ticks 0..{g2.BUDGET + up.H}: {exc}") from exc
    ctx = um.make_context(vocab, us.static_world_pinned(), track)
    return Frozen(model=model, vocab=vocab, ctx=ctx, track=track)


@contextlib.contextmanager
def no_optimizer():
    """While active, constructing ANY torch optimizer raises IntegrityStop (the model is frozen for the whole run)."""
    import torch

    orig = torch.optim.Optimizer.__init__

    def refuse(self, *a, **k):   # noqa: ANN001
        raise IntegrityStop("an optimizer was constructed during m7u2 (the m7u1 model is frozen)")

    torch.optim.Optimizer.__init__ = refuse
    try:
        yield
    finally:
        torch.optim.Optimizer.__init__ = orig


def reproduce_decisions(fz: Frozen, src: M7u1Sources, root: Path = M7U1) -> Dict[str, Any]:
    """Re-score the 32 fixed recorded m7u1 decisions: the chosen candidate must be identical and every score within
    REPRO_TOLERANCE (m7u1 planned some decisions in batches, which changes float rounding only)."""
    import torch

    import m7u_model as um

    rows_out = []
    with torch.inference_mode():
        for k, arm, which in REPRO_DECISIONS:
            with np.load(root / "trials" / f"g{k:02d}_{arm}.npz") as z:
                i = 0 if which == "first" else len(z["chosen"]) // 2
                gk = k if arm == "P" else ug.scrambled(k)
                goal = (src.goals[gk]["x"], src.goals[gk]["y"])
                n = z["candidates"].shape[1]
                roll = um.rollout(fz.model, fz.ctx, torch.tensor(np.repeat(z["root_row"][i][None], n, 0)),
                                  torch.tensor(np.repeat(z["root_hist"][i][None], n, 0)),
                                  torch.tensor(z["candidates"][i].astype(np.int64)))
                s, _reach = up.score(roll.x, roll.y, roll.air, roll.fall_at, goal, ug.BUDGET - int(z["at_tick"][i]))
                s = s.numpy()
                rows_out.append({"trial": f"g{k:02d}_{arm}", "decision": int(z["decision"][i]),
                                 "chosen_equal": int(np.argmin(s)) == int(z["chosen"][i]),
                                 "max_abs_diff": float(np.max(np.abs(s - z["scores"][i])))})
    ok = all(r["chosen_equal"] for r in rows_out) and max(r["max_abs_diff"] for r in rows_out) <= REPRO_TOLERANCE
    return {"ok": ok, "decisions": len(rows_out), "chosen_equal": sum(r["chosen_equal"] for r in rows_out),
            "max_abs_diff": max(r["max_abs_diff"] for r in rows_out), "tolerance": REPRO_TOLERANCE}


# -- launch readiness (zero ticks; a refusal consumes nothing and is not a result) -------------------------------------


def memory_status() -> Optional[Dict[str, float]]:
    if os.name != "nt":
        return None

    class MEMSTAT(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    m = MEMSTAT()
    m.dwLength = ctypes.sizeof(MEMSTAT)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
        return None
    return {"available_mb": m.ullAvailPhys / 2 ** 20, "commit_free_mb": m.ullAvailPageFile / 2 ** 20}


def timing_probe(fz: Frozen, row0: np.ndarray, *, n: int = READINESS["probe_decisions"],
                 warmup: int = READINESS["probe_warmup"], n_candidates: int = N_CANDIDATES) -> Dict[str, float]:
    """Complete planning decisions from the tick-0 row with the frozen model (probe streams, never used by a trial)."""
    import torch

    import m7u_model as um

    hist = us.init_history(row0)
    times = []
    with torch.inference_mode():
        for i in range(warmup + n):
            t = time.perf_counter()
            c = up.Controller(arm="P", stream_key=f"m7u2|probe|{i}", n_candidates=n_candidates, goal=(0.0, -1500.0),
                              budget=g2.BUDGET)
            arr = c.prepare()
            roll = um.rollout(fz.model, fz.ctx, torch.tensor(np.repeat(row0[None], n_candidates, 0)),
                              torch.tensor(np.repeat(hist[None], n_candidates, 0)), torch.tensor(arr))
            s, _r = up.score(roll.x, roll.y, roll.air, roll.fall_at, c.goal, c.remaining())
            c.choose(int(torch.argmin(s)))
            if i >= warmup:
                times.append(time.perf_counter() - t)
    return {"n": n, "median_s": float(np.median(times)), "p95_s": float(np.quantile(times, 0.95))}


def readiness(probe: Callable[[], Mapping[str, float]], memory: Callable[[], Optional[Mapping[str, float]]] = memory_status
              ) -> Dict[str, Any]:
    problems: List[str] = []
    mem = memory()
    if mem is None:
        problems.append("memory status unavailable")
    else:
        if mem["available_mb"] < READINESS["min_available_mb"]:
            problems.append(f"available memory {mem['available_mb']:.0f} MB < {READINESS['min_available_mb']} MB")
        if mem["commit_free_mb"] < READINESS["min_commit_free_mb"]:
            problems.append(f"free commit {mem['commit_free_mb']:.0f} MB < {READINESS['min_commit_free_mb']} MB")
    t = dict(probe())
    if t["p95_s"] > READINESS["probe_p95_max_s"]:
        problems.append(f"planning decision p95 {t['p95_s']:.3f} s > {READINESS['probe_p95_max_s']} s")
    return {"ok": not problems, "problems": problems, "memory": mem, "timing": t, "thresholds": dict(READINESS)}


# -- identity, approval, preflight -------------------------------------------------------------------------------------


def identity() -> Dict[str, Any]:
    return {"gate": GATE, "scope": g2.SCOPE, "rule": r2.RULE_ID, "rule_sha256": r2.rule_digest(),
            "goal_contract": g2.GOAL_CONTRACT, "goal_contract_sha256": g2.contract_digest(),
            "planner_sha256": up.contract_digest(), "state_sha256": us.contract_digest(),
            "frozen_model": {k: PIN[k] for k in ("model_sha256", "parameter_digest", "vocab", "members", "track_sha256")},
            "m7u1_sources": {k: PIN[k] for k in ("m7u1_state_sha256", "m7u1_goals_sha256", "m7u1_collection_sha256",
                                                 "reference_digest", "tick0_row_digest")},
            "world_digest": PIN["world_digest"], "p1": PIN["p1"],
            "executable_sha256": g1.sha256_file(EXECUTABLE) if EXECUTABLE.is_file() else None,
            "code": {f"rl/{f}": g1.sha256_file(RL / f) for f in CODE_FILES if (RL / f).is_file()},
            "n_candidates": N_CANDIDATES, "gate_seed": GATE_SEED, "pool": [g2.POOL_EPISODES, g2.POOL_TICKS],
            "n_goals": g2.N_GOALS, "budget": g2.BUDGET, "tick_budget": TICK_BUDGET, "wall_caps_s": WALL_CAPS_S,
            "global_cap_s": GLOBAL_CAP_S, "memory_cap_mb": MEMORY_CAP_MB, "readiness": READINESS, "replays": REPLAYS,
            "repro": {"decisions": len(REPRO_DECISIONS), "tolerance": REPRO_TOLERANCE}}


def _norm(v: Any) -> str:
    return json.dumps(v, sort_keys=True, default=str)


def approval_status() -> Tuple[bool, str]:
    if not APPROVAL.is_file():
        return False, f"no approval record at {APPROVAL.relative_to(REPO_ROOT)} (the gate is not authorised)"
    rec = json.loads(APPROVAL.read_text(encoding="utf-8"))
    if not str(rec.get("approval", "")).startswith("APPROVED"):
        return False, f"approval record says {rec.get('approval')!r}"
    want = identity()
    diffs = [k for k in want if k != "code" and _norm(rec.get(k)) != _norm(want[k])]
    diffs += [f"code:{f}" for f, h in want["code"].items() if (rec.get("code") or {}).get(f) != h]
    if diffs:
        return False, f"approval record does not match the current identity: {diffs[:8]}"
    return True, "approved"


def preflight(*, run_unit: bool = True, probe: bool = True) -> Dict[str, Any]:
    problems: List[str] = []
    rep: Dict[str, Any] = {"utc": utc(), "scope": g2.SCOPE}
    if GATE_ROOT.exists():
        problems.append(f"{GATE_ROOT.relative_to(REPO_ROOT)} exists (never overwritten)")
    if run_unit:
        for cmd, key in (([sys.executable, str(RL / "m7u2_tests.py"), "unit"], "unit_suite"),
                         ([sys.executable, str(RL / "m7u2_rule.py"), "self-test"], "rule_self_test")):
            r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)
            rep[key] = (r.stdout.strip().splitlines() or [r.stderr[-300:]])[-1:]
            if r.returncode != 0:
                problems.append(f"{key} failed")
    fz = row0 = None
    try:
        src = load_m7u1_sources()
        row0 = tick0_row(src)
        ref = reference(src)
        if g2.row_digest(row0) != PIN["tick0_row_digest"] or ref.digest() != PIN["reference_digest"]:
            problems.append("tick-0 record or chance reference differs from the pin")
        fz = load_frozen(src)
        rep["frozen_model"] = "pins ok"
        rep["decision_reproduction"] = reproduce_decisions(fz, src)
        if not rep["decision_reproduction"]["ok"]:
            problems.append("the frozen model does not reproduce the recorded m7u1 decisions")
    except (IntegrityStop, OSError, KeyError, ValueError) as exc:
        problems.append(f"frozen identity: {type(exc).__name__}: {exc}")
    if up.contract_digest() != PIN["planner_sha256"] or us.contract_digest() != PIN["state_sha256"]:
        problems.append("planner or state contract differs from m7u1")
    if g1.PINNED_WORLD_DIGEST != PIN["world_digest"]:
        problems.append("pinned stage table differs from m7u1")
    if not EXECUTABLE.is_file() or g1.sha256_file(EXECUTABLE) != PIN["executable_sha256"]:
        problems.append("executable missing or differs from the m7u1 executable")
    cov = g1.combined_coverage()
    rep["backup"] = {k: cov.get(k) for k in ("ok", "reason", "source_files", "uncovered", "increments", "skipped")}
    if not cov.get("ok"):
        problems.append(f"backup prerequisite not met: {cov.get('reason')}")
    procs = g1.game_processes()
    if procs:
        problems.append(f"BattleShip already running: {procs}")
    ok, why = approval_status()
    rep["approval"] = why
    if not ok:
        problems.append(why)
    if probe and fz is not None and row0 is not None:
        rep["readiness"] = readiness(lambda: timing_probe(fz, row0))
        if not rep["readiness"]["ok"]:
            problems += [f"readiness: {p}" for p in rep["readiness"]["problems"]]
    rep["problems"] = problems
    rep["ok"] = not problems
    return rep


# -- controllers and entries -------------------------------------------------------------------------------------------


def stream_key(kind: str, name: Any) -> str:
    return f"m7u2|{GATE_SEED}|{kind}|{name}"


def controller_for(entry: Mapping[str, Any], n_candidates: int, goals: Optional[Sequence[g2.Goal]] = None) -> up.Controller:
    if entry["kind"] == "collect":
        return up.Controller(arm="collect", stream_key=stream_key("collect", entry["entry"]), n_candidates=n_candidates)
    arm, k = entry["arm"], int(entry["goal_k"])
    key = stream_key("goal", k)                   # shared by the three arms of a goal (common random numbers)
    if arm == "RC":
        return up.Controller(arm="RC", stream_key=key, n_candidates=n_candidates, budget=int(entry["budget"]))
    target = goals[k] if arm == "P" else goals[g2.scrambled(k, len(goals))]
    return up.Controller(arm=arm, stream_key=key, n_candidates=n_candidates, goal=(target.x, target.y),
                         budget=int(entry["budget"]))


def pool_configs(n_workers: int, entries: Sequence[str] = g2.POOL_ENTRIES) -> Dict[int, Dict[str, Any]]:
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
        arms = ["P", "RC", "S"]
        rot = g.k % 3
        order += [(g, a) for a in arms[rot:] + arms[:rot]]
    for i, (g, arm) in enumerate(order):
        cfg[i % n_workers]["entries"].append({
            "entry": f"g{g.k:02d}_{arm}", "kind": "trial", "arm": arm, "goal_k": g.k, "t": 0, "budget": g2.BUDGET,
            "goal": [g.x, g.y], "prefix": [], "expected_start_row": start})
    return cfg


def validate_entries(configs: Mapping[int, Mapping[str, Any]], phase: str, goals: Optional[Sequence[g2.Goal]],
                     row0: np.ndarray) -> None:
    """Refuse (before anything is launched) any evaluation entry that is not a normal tick-0 trial, and any pool entry
    that is not a plain behaviour episode."""
    start = [None if np.isnan(v) else float(v) for v in row0]
    for c in configs.values():
        for e in c["entries"]:
            if phase == "pool":
                if e.get("kind") != "collect" or set(e) - {"entry", "kind"}:
                    raise ValueError(f"pool entry {e.get('entry')}: not a plain behaviour episode")
                continue
            if e.get("kind") != "trial" or int(e.get("t", -1)) != 0 or list(e.get("prefix", [None])) != []:
                raise ValueError(f"evaluation entry {e.get('entry')}: prefixes and archived starts are not allowed")
            if e.get("expected_start_row") != start or int(e.get("budget", 0)) != g2.BUDGET:
                raise ValueError(f"evaluation entry {e.get('entry')}: not the tick-0 record or not the 128-word budget")
            g = goals[int(e["goal_k"])]
            if list(e["goal"]) != [g.x, g.y] or e.get("arm") not in ("P", "RC", "S"):
                raise ValueError(f"evaluation entry {e.get('entry')}: the scored goal must be g itself")


# -- the drive loop (normal tick-0 starts only) ------------------------------------------------------------------------


def drive(venv: Any, configs: Mapping[int, Mapping[str, Any]], *, phase: str, ledger: g1.Ledger, clock: g1.Clock,
          n_candidates: int, row0: np.ndarray, goals: Optional[Sequence[g2.Goal]] = None, model: Any = None,
          ctx: Any = None, track: Optional[us.ClockTrack] = None) -> List[Dict[str, Any]]:
    """Drive every worker through its entries from the normal tick-0 reset. Before a task's first word, its reset row
    must equal the tick-0 record; every step record must report k = words submitted (input_tick = consumed + 1)."""
    ledger_key = {"pool": "pool", "evaluation": "eval_control"}[phase]
    validate_entries(configs, phase, goals, row0)
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
        pending: List[Tuple[g1.Task, np.ndarray]] = []
        for task in tasks:
            if task is None:
                continue
            c = task.controller
            if c.needs_decision():
                arr = c.prepare()
                if c.needs_model:
                    pending.append((task, arr))
                else:
                    rec = g1.decision_record(task, arr, 0) if phase == "evaluation" else None
                    c.choose(0)
                    if rec is not None:
                        task.evidence.append(rec)
        if pending:
            g1.plan_batch(model, ctx, pending)
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
                results.append(_task_result(task, rec, summary))
                tasks[i] = None if rec.get("idle_next") else new_task(i, (venv.reset_infos[i] or {}).get("m7u"))
    return results


def _task_result(task: g1.Task, rec: Mapping[str, Any], summary: Mapping[str, Any]) -> Dict[str, Any]:
    c = task.controller
    return {"entry": task.entry["entry"], "kind": task.entry["kind"], "arm": task.entry.get("arm"),
            "goal_k": task.entry.get("goal_k"), "rank": task.rank,
            "rows": np.stack(task.rows), "words": np.array(task.words, dtype=np.int64).reshape(-1, 2),
            "reach_tick": rec.get("reach_tick"), "truncation_reason": rec.get("truncation_reason"),
            "termination_reason": rec.get("termination_reason"),
            "decisions": [d.at_tick for d in c.decisions] if c else [],
            "decision_log": [(d.at_tick, d.chosen, d.predicted_reach) for d in c.decisions] if c else [],
            "episode_id": summary.get("episode_id"), "artifact_dir": summary.get("artifact_dir"),
            "native_action_digest": summary.get("native_action_digest"), "startup_mode": summary.get("startup_mode"),
            "end_reason": summary.get("end_reason"), "cleared": bool(summary.get("cleared")),
            "sidecar": ((summary.get("m7u") or {}).get("sidecar")), "evidence": task.evidence}


# -- P1 and replays ----------------------------------------------------------------------------------------------------


def p1_expected(src: M7u1Sources, artifact_words: Callable[[Any], List[Tuple[int, int]]] = g1.artifact_track1_words,
                read_sidecar: Optional[Callable[[Any], Mapping[str, Any]]] = None) -> List[Dict[str, Any]]:
    """The two pinned m7u1 trials, as m7u1 replay entries, with their recorded rows, reach tick and action digest. A
    stack-identity check only: no m7u2 trial ever starts from them."""
    import m7u_worker as uw

    read_sidecar = read_sidecar or (lambda d: uw.read_sidecar(g1.resolve(d)))
    goals = {g["k"]: g for g in src.goals}
    out = []
    for name, pin in PIN["p1"].items():
        t = src.trials[name]
        g = goals[int(t["goal_k"])]
        words = artifact_words(t["artifact_dir"])
        side = read_sidecar(t["artifact_dir"])
        if len(words) != pin["words"] or [tuple(w) for w in side["words"]] != words:
            raise IntegrityStop(f"P1 {name}: artifact words differ from the sidecar or the pin")
        if t["reach_tick"] != pin["reach_tick"] or t["native_action_digest"] != pin["native_action_digest"]:
            raise IntegrityStop(f"P1 {name}: m7u1 record differs from the pin")
        out.append({"entry": f"p1_{name}", "kind": "trial", "t": int(g["t"]), "budget": ug.BUDGET,
                    "goal": [g["x"], g["y"]], "prefix": [list(w) for w in g["prefix"]],
                    "expected_start_row": g["expected_start_row"], "words": [list(w) for w in words],
                    "expected": {"rows": side["rows"], "reach_tick": pin["reach_tick"],
                                 "native_action_digest": pin["native_action_digest"]}})
    return out


def check_replay(rr: Mapping[str, Any], expected: Mapping[str, Any], words: Sequence[Sequence[int]]) -> Dict[str, Any]:
    import m7u_worker as uw

    rows = expected["rows"]
    diff = sorted({f for a, b in zip(rows, rr["rows"]) for f in uw.rows_equal(a, b)})
    ok = (rr["sent"] == len(words) and len(rr["rows"]) == len(rows) and not diff
          and rr["reach_tick"] == expected["reach_tick"]
          and rr["native_action_digest"] == expected["native_action_digest"])
    return {"ok": ok, "sent": rr["sent"], "reach_tick": rr["reach_tick"], "fields_differing": diff[:12]}


def replay_selection(outcomes: Mapping[str, Sequence[bool]], caps: Mapping[str, int] = REPLAYS) -> List[Tuple[str, int]]:
    """(arm, goal k) of the success replays: the first successes of each arm in registered order, at most caps[arm]."""
    out = []
    for arm, cap in caps.items():
        out += [(arm, k) for k in [k for k, ok in enumerate(outcomes[arm]) if ok][:cap]]
    return out


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
    commanded = None if arm == "RC" else (goals[k] if arm == "P" else goals[g2.scrambled(k, len(goals))])
    meta = {"entry": r["entry"], "arm": arm, "goal_k": k, "t": 0, "scored_goal": [goals[k].x, goals[k].y],
            "commanded_goal_k": None if commanded is None else commanded.k,
            "commanded_goal": None if commanded is None else [commanded.x, commanded.y],
            "stream_key": stream_key("goal", k), "model_evaluated": arm != "RC", "episode_id": r["episode_id"],
            "artifact_dir": str(r["artifact_dir"]), "reach_tick": r["reach_tick"],
            "truncation_reason": r["truncation_reason"], "termination_reason": r["termination_reason"],
            "native_action_digest": r["native_action_digest"], "scope": g2.SCOPE}
    path = Path(directory) / f"{r['entry']}.npz"
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, meta=np.frombuffer(json.dumps(meta, default=str).encode("utf-8"), dtype=np.uint8), **arrays)
    return {"file": path.name, "decisions": len(ev), "sha256": g1.sha256_stream(path)}


def movement_census(r: Mapping[str, Any]) -> Dict[str, Any]:
    """Status entries after the reset up to the reach (or the end): what the controller initiated (reported only)."""
    rows = np.asarray(r["rows"])
    end = r["reach_tick"] if r["reach_tick"] is not None else len(rows) - 1
    ev = g2.rise_events(rows, 0, end)
    return {"composition": g2.composition(ev), "first_rise_tick": ev[0][0] if ev else None,
            "double_jumps": sum(1 for _i, n in ev if n == "double_jump"), "reach_tick": r["reach_tick"]}


# -- the gate ----------------------------------------------------------------------------------------------------------


def run_gate(*, settings: Any, pool_settings: Any, root: Path, venv_factory: Callable[..., Any],
             env_factory: Callable[..., Any], clock: g1.Clock, src: M7u1Sources, frozen: Frozen,
             ledger: Optional[g1.Ledger] = None, n_candidates: int = N_CANDIDATES,
             p1_entries: Optional[Sequence[Mapping[str, Any]]] = None,
             artifact_words: Callable[[Any], List[Tuple[int, int]]] = g1.artifact_track1_words,
             read_sidecar: Optional[Callable[[Any], Mapping[str, Any]]] = None,
             ref: Optional[g2.Reference] = None, row0: Optional[np.ndarray] = None,
             pool_entries: Sequence[str] = g2.POOL_ENTRIES, n_goals: int = g2.N_GOALS,
             n_workers: int = N_WORKERS) -> Dict[str, Any]:
    """Every phase in order under the caps; returns the state (with `decision`). Factories, sources and the reference
    are injectable only so the offline tests can drive this exact code with synthetic workers."""
    import torch

    import m7u_analysis as ua
    import m7u_model as um
    import m7u_worker as uw

    torch.set_num_threads(max(1, (os.cpu_count() or 6)))
    read_sidecar = read_sidecar or (lambda d: uw.read_sidecar(g1.resolve(d)))
    ledger = ledger or g1.Ledger(TICK_BUDGET)
    row0 = tick0_row(src) if row0 is None else np.asarray(row0, dtype=np.float64)
    ref = ref or reference(src)
    model, ctx, track = frozen.model, frozen.ctx, frozen.track
    pdig = parameter_digest(model)
    state: Dict[str, Any] = {"started_utc": utc(), "gate": GATE, "scope": g2.SCOPE, "phases": {},
                             "integrity": {"problems": []}, "frozen_model": {"parameter_digest": pdig},
                             "tick0_row_digest": g2.row_digest(row0), "reference_digest": ref.digest(), "evidence": {}}
    state_dir = Path(root) / "_gate"

    def save() -> None:
        state["ledger"] = ledger.to_json()
        state["clock"] = clock.to_json()
        g1.write_json(state_dir / "state.json", state)

    def finish(outcome: Dict[str, Any]) -> Dict[str, Any]:
        clock.end()
        state["decision"] = outcome
        state["finished_utc"] = utc()
        save()
        return state

    def frozen_check(where: str) -> None:
        if parameter_digest(model) != pdig:
            raise IntegrityStop(f"frozen model parameters changed ({where})")

    try:
        # P1: m7u1's pinned artifacts reproduced through the stack, every row field
        clock.begin("p1")
        entries = list(p1_entries) if p1_entries is not None else p1_expected(src, artifact_words, read_sidecar)
        res = g1.run_single(env_factory(Path(root) / "p1", "m7u2_p1", "identity", settings),
                            [{k: v for k, v in e.items() if k != "expected"} for e in entries], phase="p1",
                            ledger=ledger, clock=clock)
        p1 = [dict(check_replay(r, e["expected"], e["words"]), entry=e["entry"]) for r, e in zip(res, entries)]
        state["phases"]["p1"] = p1
        save()
        if len(p1) != len(entries) or not all(p["ok"] for p in p1):
            raise IntegrityStop("P1: the pinned m7u1 artifacts were not reproduced exactly")
        # goal-source pool: exactly the registered behaviour episodes, <= 128 words, from the normal reset
        clock.begin("pool")
        venv = venv_factory(Path(root) / "pool", "m7u2_pool", "pool", pool_settings)
        try:
            pool = drive(venv, pool_configs(n_workers, pool_entries), phase="pool", ledger=ledger, clock=clock,
                         n_candidates=n_candidates, row0=row0)
        finally:
            venv.close()
        problems = []
        if sorted(r["entry"] for r in pool) != sorted(pool_entries):
            problems.append(f"pool produced {len(pool)} episodes, not exactly the {len(pool_entries)} registered")
        for r in pool:
            if len(r["words"]) > g2.POOL_TICKS:
                problems.append(f"{r['entry']}: {len(r['words'])} words > {g2.POOL_TICKS}")
            if [tuple(w) for w in r["words"]] != up.rc_words(stream_key("collect", r["entry"]), n_candidates,
                                                             len(r["words"])):
                problems.append(f"{r['entry']}: words differ from the behaviour regeneration")
            side = read_sidecar(r["artifact_dir"])
            if len(side["rows"]) != len(r["rows"]) or uw.rows_equal(side["rows"].reshape(-1), r["rows"].reshape(-1)):
                problems.append(f"{r['entry']}: sidecar rows differ from the streamed rows")
        g1.write_json(state_dir / "pool.json", {"scope": g2.SCOPE, "held_out_by_construction": True, "episodes": [
            {"entry": r["entry"], "episode_id": r["episode_id"], "words": int(len(r["words"])), "rank": r["rank"],
             "stream_key": stream_key("collect", r["entry"]), "artifact_dir": str(r["artifact_dir"]),
             "sidecar": r["sidecar"], "native_action_digest": r["native_action_digest"],
             "termination_reason": r["termination_reason"], "truncation_reason": r["truncation_reason"],
             "startup_mode": r["startup_mode"]} for r in pool]})
        state["phases"]["pool"] = {"episodes": len(pool), "ticks": ledger.used["pool"], "problems": problems[:12],
                                   "falls": sum(1 for r in pool if r["termination_reason"] == "native_failure")}
        save()
        if problems:
            raise IntegrityStop(f"pool integrity: {problems[:3]}")
        # goals: deterministic, from the pool and the fixed reference only; frozen before evaluation
        clock.begin("goals")
        try:
            sel = g2.select_goals([{"entry": r["entry"], "episode_id": r["episode_id"], "rows": r["rows"],
                                    "words": r["words"], "fell": r["termination_reason"] == "native_failure"}
                                   for r in pool], ref, row0, entries=pool_entries, n_goals=n_goals)
        except g2.GoalError as exc:
            state["phases"]["goals"] = dict(exc.record, error=str(exc))
            save()
            if exc.incomplete:
                raise CapStop(f"goal availability: {exc}") from exc
            raise IntegrityStop(f"goal selection: {exc}") from exc
        goals: List[g2.Goal] = sel["goals"]
        g1.write_json(state_dir / "goals.json", {"record": sel["record"], "goals": [g.to_json() for g in goals],
                                                 "digest": g2.goals_digest(goals)})
        state["phases"]["goals"] = dict(sel["record"], digest=g2.goals_digest(goals))
        save()
        # evaluation: normal tick-0 starts only
        clock.begin("evaluation")
        frozen_check("before evaluation")
        venv = venv_factory(Path(root) / "evaluation", "m7u2_eval", "evaluation", settings)
        try:
            trials = drive(venv, evaluation_configs(goals, n_workers, row0), phase="evaluation", ledger=ledger,
                           clock=clock, n_candidates=n_candidates, row0=row0, goals=goals, model=model, ctx=ctx,
                           track=track)
        finally:
            venv.close()
        frozen_check("after evaluation")
        if len(trials) != 3 * len(goals):
            raise IntegrityStop(f"{len(trials)} of {3 * len(goals)} trials finished")
        by = {(r["goal_k"], r["arm"]): r for r in trials}
        outcomes = {arm: [by[(k, arm)]["reach_tick"] is not None and by[(k, arm)]["truncation_reason"] == uw.END_GOAL
                          for k in range(len(goals))] for arm in ("P", "RC", "S")}
        state["evidence"]["trials"] = {r["entry"]: save_trial(state_dir / "trials", r, goals) for r in trials}
        state["phases"]["evaluation"] = {
            "trials": [{k: v for k, v in r.items() if k not in ("rows", "words", "evidence")} for r in trials],
            "outcomes": outcomes, "ticks": ledger.used["eval_control"],
            "clears": sum(1 for r in trials if r["cleared"])}
        save()
        # diagnostics (forward passes only) and exact success replays
        clock.begin("replays_analysis")
        trial_eps = [um.Episode(episode_id=r["entry"], rows=r["rows"], words=r["words"],
                                fell=r.get("termination_reason") == "native_failure") for r in trials]
        state["evidence"]["model_inputs_trials"] = g1.save_transitions(
            state_dir / "model_inputs_trials.npz", um.build_transitions(ctx, trial_eps), trial_eps)
        attr = {k: ua.trial_attribution(model, ctx, {"rows": by[(k, "P")]["rows"], "words": by[(k, "P")]["words"],
                                                     "t": 0, "goal": (goals[k].x, goals[k].y),
                                                     "decisions": by[(k, "P")]["decisions"], "reached": outcomes["P"][k]})
                for k in range(len(goals))}
        with torch.inference_mode():
            hist0 = us.init_history(row0)
            plans = np.stack([ua._pad(g.witness, g2.TAU_MAX) for g in goals])
            roll = um.rollout(model, ctx, torch.tensor(np.repeat(row0[None], len(goals), 0)),
                              torch.tensor(np.repeat(hist0[None], len(goals), 0)), torch.tensor(plans))
            wit, _first = ua.majority_reach(roll, np.array([[g.x, g.y] for g in goals]),
                                            np.array([g.tau for g in goals]))
        fails = [k for k in range(len(goals)) if not outcomes["P"][k]]
        m_share = (sum(1 for k in fails if attr[k]["class"] == "MODEL") / len(fails)) if fails else None
        w_share = float(np.mean(wit)) if len(goals) else None
        flags = {f"{k}:{arm}": ua.ambiguity_flags(by[(k, arm)]["rows"], 0)
                 for k in range(len(goals)) for arm in ("P", "RC", "S")}
        census = {r["entry"]: movement_census(r) for r in trials}
        blocks: Dict[str, List[np.ndarray]] = {"e": [], "s": []}
        for arm in ("P", "S"):
            for k in range(len(goals)):
                r = by[(k, arm)]
                hs = us.history_sequence(r["rows"], [tuple(int(v) for v in w) for w in r["words"]])
                e_, s_ = ua.block_errors(model, ctx, r["rows"], hs, r["words"], list(r["decisions"]))
                blocks["e"].append(e_)
                blocks["s"].append(s_)
        e_all = np.concatenate(blocks["e"]) if blocks["e"] else np.zeros(0)
        s_all = np.concatenate(blocks["s"]) if blocks["s"] else np.zeros(0)
        pool_eps = [um.Episode(episode_id=r["entry"], rows=r["rows"], words=r["words"],
                               fell=r["termination_reason"] == "native_failure") for r in pool]
        state["phases"]["diagnostics"] = {
            "attribution": {str(k): v for k, v in attr.items()}, "model_share": m_share,
            "witness_from_tick0": [bool(v) for v in wit], "witness_share": w_share, "ambiguity": flags,
            "movement_census": census,
            "calibration_executed": {"blocks": int(len(e_all)), "error_gt_box": int((e_all > up.BOX).sum()),
                                     "auroc_spread": ua.auroc(s_all, e_all > up.BOX),
                                     "error_median": float(np.median(e_all)) if len(e_all) else None},
            "pool_accuracy": ua.heldout_accuracy(model, ctx, pool_eps),
            "witness_composition": {str(g.k): g.witness_composition for g in goals}}
        save()
        replays = []
        entries_by_id = {e["entry"]: e for c in evaluation_configs(goals, 1, row0).values() for e in c["entries"]}
        for arm, k in replay_selection(outcomes):
            r = by[(k, arm)]
            words = artifact_words(r["artifact_dir"])
            entry = dict(entries_by_id[r["entry"]], words=[list(w) for w in words])
            rr = g1.run_single(env_factory(Path(root) / "replays" / r["entry"], "m7u2_replay", "replay", settings),
                               [entry], phase="replays", ledger=ledger, clock=clock)[0]
            orig = read_sidecar(r["artifact_dir"])
            chk = check_replay(rr, {"rows": orig["rows"], "reach_tick": r["reach_tick"],
                                    "native_action_digest": r["native_action_digest"]}, words)
            chk["ok"] = chk["ok"] and words == [tuple(w) for w in r["words"]]
            replays.append(dict(chk, entry=r["entry"]))
        state["phases"]["replays"] = replays
        frozen_check("after analysis")
        save()
        integrity_ok = all(r["ok"] for r in replays)
        if not integrity_ok:
            state["integrity"]["problems"].append("a success replay was not exact")
        decision = r2.apply(outcomes, integrity_ok=integrity_ok)
        decision["null_reading"] = r2.null_reading(decision, model_share=m_share, witness_share=w_share)
        ov = sel["record"]["overlap"]
        decision["goal_overlap"] = {k: ov[k] for k in ("n_pairs", "n_possible_pairs", "correlated_groups",
                                                      "independent_goals", "reading")}
        decision["summary"] = (f"m7u2 ({r2.SCOPE}): {decision['outcome']}; P {decision.get('n', {}).get('P')}, "
                               f"RC {decision.get('n', {}).get('RC')}, S {decision.get('n', {}).get('S')} of {len(goals)}")
        bad = r2.scope_problems(decision["summary"])
        if bad:
            raise IntegrityStop(f"decision summary uses forbidden wording {bad}")
        return finish(decision)
    except CapStop as exc:
        return finish(r2.apply({}, integrity_ok=True, incomplete=str(exc)))
    except (IntegrityStop, ValueError) as exc:
        state["integrity"]["problems"].append(f"{type(exc).__name__}: {exc}")
        return finish(r2.apply({}, integrity_ok=False))


def cmd_run() -> int:
    from m7_runtime import install_kill_on_close_job
    import m7u_worker as uw

    pf = preflight()
    if not pf["ok"]:
        print(json.dumps(pf, indent=1, default=str))
        print("refused: preflight problems (see above); nothing was launched")
        return 2
    install_kill_on_close_job()
    src = load_m7u1_sources()
    settings = uw.env_settings()
    with no_optimizer():
        state = run_gate(settings=settings, pool_settings=dataclasses.replace(settings, horizon=g2.POOL_TICKS),
                         root=GATE_ROOT, venv_factory=g1.real_venv_factory, env_factory=g1.real_env_factory,
                         clock=g1.Clock(caps=WALL_CAPS_S, global_cap=GLOBAL_CAP_S, memory_cap_mb=MEMORY_CAP_MB),
                         src=src, frozen=load_frozen(src))
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
