#!/usr/bin/env python3
"""M7s stage-1 learned-return gate driver (design: docs/rl_goal_exploration_design_2026-09-28.md, revision 5).
NOT AUTHORISED TO RUN: `run` refuses without an APPROVED record matching the current identity.

    python rl/m7s_gate.py status
    python rl/m7s_gate.py preflight [--skip-unit]   # no game: tests, pinned P1 expectations, D: coverage, approval
    python rl/m7s_gate.py approval-template         # prints the record to review (never writes it)
    python rl/m7s_gate.py init-check                # no game: initialisation diagnostics on recorded replies
    python rl/m7s_gate.py run                       # refused unless preflight passes

`run`, in order: P1, the live identity check, before any training: (a) the eight pinned Track 1 artifacts through the
goal worker stack with the null goal (27,521 ticks), then (b) the goal-on check: one pinned normal tick-0 trace with a
goal first validly reached on its tick 774, run twice in one evaluation-mode worker (1,548 ticks); any mismatch stops
the gate. Then per seed 0, 1, 2: the shared initial parameters, phase A (20 null-goal tick-0 episodes), the frozen
goal set E + matched schedule + evaluation plan, R's phase B (358,400 ticks, 70 x 100 GCSL steps), U's phase B (the
same 358,400 ticks, no updates), the held-out evaluation of R and U (30 episodes each, identical goals, order and
sampling seeds), exact replays of the first two R and two U rare returns, exact native replays of the first two
claimed clears (a clear is never a return; an unreplayed clear is never claimed); finally rule v2, applied once.
The native RNG is never inspected; the driver never commits, pushes or deletes evidence. The pinned P1 trace is
validation evidence only: it never enters training, the goal set, the archive or a start state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import m7s_analysis as ma  # noqa: E402
import m7s_goal as mg  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
RL = REPO_ROOT / "rl"
RUNS = REPO_ROOT / "runs"
GATE_ROOT = RUNS / "m7s" / "gate"
STATE_DIR = GATE_ROOT / "_gate"
APPROVAL = REPO_ROOT / "docs" / "rl_gcsl_return_m7s_gate_approval.json"
BACKUP_BASE = Path(r"D:\BattleShip_runs_backup\2026-09-28")
BACKUP_INCREMENTS = (Path(r"D:\BattleShip_runs_backup\2026-09-28_incr_m7r"),)
EXECUTABLE = REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"
PINNED = RUNS / "m7q" / "_equiv" / "input_all"
SEEDS = (0, 1, 2)
REPLAYS_PER_ARM = 2
CLEAR_REPLAYS_PER_SEED = 2        # exact native replays of claimed clears; a clear beyond this is reported, never claimed
NORMAL_STARTS = ("cold_start", "standby_promoted", "cold_fallback")   # normal tick-0 starts of the M7c lifecycle
IDENTITY_TICKS = 27_521           # P1 (a): the eight pinned artifacts with the null goal
# P1 (b), the goal-on identity check (design section 5.1). A normal tick-0 trace of the M7e seed-2 policy (validation
# evidence only) whose goal (17, 8, floor line 2) is first validly occupied on consumed tick 774; the same bin is occupied
# in the air from tick 771, so a contact-blind probe would end the episode three ticks early.
GOAL_ON = {"trace": "runs/m7q/_equiv/input_all/fx_m7e_s2_best6.json.gz",
           "trace_sha256": "856c0e8d0f197ab3045dd6e5ea5a436a8672114b266b5b0a40efed944b3d299e",
           "goal": "17,8,2",
           "reach_tick": 774,
           "prefix_action_digest": "8821b2ad2673a5474b5e090b45c19b715af6eedf47ade2e0d0346b3c23d226a8",
           "v3_prefix_sha256": "c9000896dbb6015313a03ae09df4df6b38a5fd86cd9b19c6b5ef9965b500f0e7",
           "repeats": 2}
GOAL_ON_TICKS = GOAL_ON["repeats"] * GOAL_ON["reach_tick"]        # 1,548: no word beyond the reach tick is ever sent
P1_BUDGET = {"null_goal": IDENTITY_TICKS, "goal_on": GOAL_ON_TICKS}
TICK_BUDGET = {"p1_identity": sum(P1_BUDGET.values()),             # 29,069
               "phase_a": len(SEEDS) * mg.PHASE_A_EPISODES * mg.HORIZON,
               "phase_b": len(SEEDS) * 2 * 358_400,
               "evaluation": len(SEEDS) * 2 * 30 * mg.HORIZON,
               "replays": len(SEEDS) * 2 * REPLAYS_PER_ARM * mg.HORIZON,
               "clear_replays": len(SEEDS) * CLEAR_REPLAYS_PER_SEED * mg.HORIZON}
TICK_BUDGET["total"] = sum(TICK_BUDGET.values())            # 3,108,269
CODE_FILES = ("m7s_goal.py", "m7s_policy.py", "m7s_worker.py", "m7s_collect.py", "m7s_analysis.py", "m7s_gate.py",
              "m7s_tests.py", "m7n_obs.py", "btt_parallel.py", "battleship_env.py", "run_artifacts.py",
              "m7_vec_env.py", "m7_runtime.py", "m7f_trace.py", "experiment_config.py", "m7_trainer.py",
              "tools/runs_backup.py", "configs/m7n/m7n_s0_v3.toml")


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def write_json(path: Path, data: Any) -> None:
    import m7s_collect as mc

    mc.write_json(path, data)


# -- identity and approval ----------------------------------------------------------------------------------------------


def identity() -> Dict[str, Any]:
    import m7s_policy as mp

    return {"rule": ma.RULE_ID, "rule_sha256": ma.rule_digest(), "goal_blind_tv": ma.GOAL_BLIND_TV,
            "goal_contract_sha256": mg.contract_digest(), "policy_contract_sha256": mp.contract_digest(),
            "executable_sha256": sha256_file(EXECUTABLE) if EXECUTABLE.is_file() else None,
            "code": {f"rl/{f}": sha256_file(RL / f) for f in CODE_FILES},
            "p1": {"budget": P1_BUDGET, "goal_on": GOAL_ON}, "clear_replays_per_seed": CLEAR_REPLAYS_PER_SEED,
            "tick_budget": TICK_BUDGET, "seeds": list(SEEDS),
            "backup": {"base": str(BACKUP_BASE), "increments": [str(p) for p in BACKUP_INCREMENTS]}}


def approval_status() -> Tuple[bool, str]:
    if not APPROVAL.is_file():
        return False, f"no approval record at {APPROVAL.relative_to(REPO_ROOT)} (the gate is not authorised)"
    rec = json.loads(APPROVAL.read_text(encoding="utf-8"))
    if not str(rec.get("approval", "")).startswith("APPROVED"):
        return False, f"approval record says {rec.get('approval')!r}"
    want = identity()
    diffs = [k for k in ("rule", "rule_sha256", "goal_blind_tv", "goal_contract_sha256", "policy_contract_sha256",
                         "executable_sha256", "p1", "clear_replays_per_seed", "tick_budget") if rec.get(k) != want[k]]
    diffs += [f"code:{f}" for f, h in want["code"].items() if (rec.get("code") or {}).get(f) != h]
    if diffs:
        return False, f"approval record does not match the current identity: {diffs[:8]}"
    return True, "approved"


# -- D: base + increments coverage (decision U7) -------------------------------------------------------------------------


def combined_coverage(source: Path = RUNS, base: Path = BACKUP_BASE,
                      increments: Sequence[Path] = BACKUP_INCREMENTS) -> Dict[str, Any]:
    """Every regular file under `source` covered (same size and mtime) by the base manifest or by the manifest of the
    increment whose recorded source subtree contains it; every destination's record PASS with its manifest intact."""
    sys.path.insert(0, str(RL / "tools"))
    import runs_backup as rb

    out: Dict[str, Any] = {"ok": False, "destinations": []}
    manifests: List[Tuple[str, Dict[str, Tuple[str, int, int]]]] = []
    for dest in (base, *increments):
        rec_path = Path(dest) / rb.RECORD
        if not rec_path.is_file():
            out["reason"] = f"no verification record at {dest}"
            return out
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
        man_ok = hashlib.sha256((Path(dest) / rb.MANIFEST).read_bytes()).hexdigest() == rec.get("manifest_sha256")
        src = Path(rec.get("source", ""))
        try:
            prefix = src.resolve().relative_to(Path(source).resolve()).as_posix()
        except ValueError:
            out["reason"] = f"{dest}: recorded source {src} is not under {source}"
            return out
        prefix = "" if prefix == "." else prefix + "/"
        out["destinations"].append({"dest": str(dest), "result": rec.get("result"), "files": rec.get("files"),
                                    "verified_utc": rec.get("verified_utc"), "manifest_intact": man_ok, "prefix": prefix})
        if rec.get("result") != "PASS" or not man_ok:
            out["reason"] = f"{dest}: record {rec.get('result')!r}, manifest intact {man_ok}"
            return out
        manifests.append((prefix, rb.read_manifest(Path(dest))))
    files, _skipped, errors = rb.walk(Path(source))
    uncovered = []
    for rel, (size, mtime) in files.items():
        ok = False
        for prefix, man in manifests:
            if rel.startswith(prefix):
                m = man.get(rel[len(prefix):])
                if m is not None and (m[1], m[2]) == (size, mtime):
                    ok = True
                    break
        if not ok:
            uncovered.append(rel)
    out.update({"source_files": len(files), "uncovered": len(uncovered), "uncovered_examples": sorted(uncovered)[:20],
                "unreadable": len(errors)})
    if errors:
        out["reason"] = f"{len(errors)} unreadable source entries"
    elif uncovered:
        out["reason"] = f"{len(uncovered)} files under runs/ are not covered by the base or an increment"
    else:
        out["ok"] = True
    return out


# -- preflight -------------------------------------------------------------------------------------------------------------


def game_processes() -> List[int]:
    from m7_runtime import BATTLESHIP_IMAGE, list_processes_named

    return list(list_processes_named(BATTLESHIP_IMAGE) or [])


def preflight(*, run_unit: bool = True) -> Dict[str, Any]:
    problems: List[str] = []
    rep: Dict[str, Any] = {"utc": utc()}
    if GATE_ROOT.exists():
        problems.append(f"{GATE_ROOT.relative_to(REPO_ROOT)} exists (never overwritten)")
    if run_unit:
        for cmd, key in (([sys.executable, str(RL / "m7s_tests.py"), "unit"], "unit_suite"),
                         ([sys.executable, str(RL / "m7s_analysis.py"), "self-test"], "analysis_self_test")):
            r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)
            rep[key] = (r.stdout.strip().splitlines() or [r.stderr[-300:]])[-1:]
            if r.returncode != 0:
                problems.append(f"{key} failed")
    import m7s_policy as mp

    if ma.GOAL_BLIND_TV != mp.GOAL_BLIND_TV:
        problems.append(f"goal-blind threshold differs: rule {ma.GOAL_BLIND_TV} vs policy {mp.GOAL_BLIND_TV}")
    try:     # no game: the pinned P1 goal-on trace, words, first reach and v3 block are unchanged
        exp = goal_on_expected()
        rep["p1_goal_on_expected"] = {"ok": not exp["problems"], "problems": exp["problems"],
                                      "reach_tick": exp.get("reach_tick"), "v3_prefix_sha256": exp.get("v3_prefix_sha256")}
        problems += [f"P1 goal-on expectation: {p}" for p in exp["problems"]]
    except Exception as exc:  # noqa: BLE001 - reported as a preflight problem
        problems.append(f"P1 goal-on expectation raised {type(exc).__name__}: {exc}")
    cov = combined_coverage()
    rep["backup"] = {k: cov.get(k) for k in ("ok", "reason", "destinations", "source_files", "uncovered")}
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


# -- P1: the live identity check (game), before any training ---------------------------------------------------------------


def track1_of(buttons: int, stick_x: int, stick_y: int) -> Tuple[int, int]:
    from btt_learning import TRACK1_BUTTON_TABLE, TRACK1_STICK_TABLE

    s = [k for k, v in enumerate(TRACK1_STICK_TABLE) if (int(v[0]), int(v[1])) == (int(stick_x), int(stick_y))]
    b = [k for k, v in enumerate(TRACK1_BUTTON_TABLE) if int(v) == int(buttons)]
    if len(s) != 1 or len(b) != 1:
        raise mg.GoalContractError(f"({buttons}, {stick_x}, {stick_y}) is not a Track 1 word")
    return s[0], b[0]


def identity_check(work: Path, settings: Any) -> Dict[str, Any]:
    """P1 (a): the eight pinned Track 1 artifacts driven through the goal worker stack (null goal) reproduce their
    words. `ticks` counts the words actually sent."""
    import numpy as np

    import m7f_trace as mt
    import m7s_collect as mc
    import m7s_worker as msw
    from btt_parallel import RunCoordinator, initial_coordination_state
    from m7_runtime import prepare_worker_runtime
    from run_artifacts import read_artifact

    results = []
    for k, p in enumerate(sorted(PINNED.glob("fx_*.json.gz"))):
        tr = mt.read_trace(p)
        pinned = [(a.consumed_tick, a.buttons, a.stick_x, a.stick_y) for a in read_artifact(REPO_ROOT / tr["artifact"]).actions]
        root = work / f"a{k:02d}"
        coord = root / "coordination"
        RunCoordinator.create(coord, initial_coordination_state("m7s1_identity", "test", None))
        spec = mc.worker_spec(root, k % mc.N_WORKERS, "m7s1_identity", "test", settings, coord)
        prepare_worker_runtime(Path(spec.worker_dir) / "runtime", Path(settings.executable))
        env = msw.build_worker_env_m7s(spec)
        t0 = time.perf_counter()
        sent = 0
        try:
            env.goal.m7s_configure({"mode": "null", "phase": "identity", "episode_quota": 1, "end_on_success": False})
            env.reset()
            for _t, b, sx, sy in pinned:
                _o, _r, term, trunc, _i = env.step(np.array(track1_of(b, sx, sy), dtype=np.int64))
                sent += 1
                if term or trunc:
                    break
        finally:
            env.close()
        written = sorted((Path(spec.worker_dir) / "artifacts").iterdir())
        new = [(a.consumed_tick, a.buttons, a.stick_x, a.stick_y) for a in read_artifact(written[-1]).actions]
        results.append({"artifact": tr["artifact"], "ticks": sent, "words": len(pinned), "identical": new == pinned,
                        "sidecar": (written[-1] / mg.SIDECAR_FILE).is_file(), "wall_s": round(time.perf_counter() - t0, 2)})
    ticks = sum(r["ticks"] for r in results)
    return {"ok": all(r["identical"] and r["sidecar"] for r in results) and ticks == IDENTITY_TICKS,
            "ticks": ticks, "artifacts": results}


def recorded_v3(trace: Mapping[str, Any], ticks: int) -> Any:
    """(ticks + 1, 606) float32: the v3 observations the UNCHANGED v3 wrapper builds from the recorded raw replies of
    `trace` for consumed ticks 0..ticks. A stand-in for Track1PolicyWrapper and below hands the recorded replies to the
    v3 wrapper through an episode client, exactly as the live client does; nothing is launched."""
    from types import SimpleNamespace

    import gymnasium as gym
    import numpy as np

    import m7n_obs as mn

    replies = [trace["initial"]] + list(trace["steps"][:ticks])
    if len(replies) != ticks + 1:
        raise mg.GoalContractError(f"the trace has {len(replies) - 1} steps, {ticks} needed")

    class _Client:
        def __init__(self) -> None:
            self.k = 0

        def request(self, op: str, **_payload: Any) -> Dict[str, Any]:
            if op == "observe":
                return replies[0]
            self.k += 1
            return replies[self.k]

    class _Recorded(gym.Env):
        observation_space = gym.spaces.Box(-np.inf, np.inf, (15,), np.float32)
        action_space = gym.spaces.MultiDiscrete([9, 8])

        def __init__(self) -> None:
            self.base = SimpleNamespace(episode=None, last_observe=None, last_step_result=None)

        def reset(self, *, seed=None, options=None):
            self.base.episode = SimpleNamespace(client=_Client())
            self.base.last_observe = SimpleNamespace(observation=dict(replies[0]["observation"]))
            self.base.last_step_result = None
            return np.zeros(15, np.float32), {}

        def step(self, action):
            r = self.base.episode.client.request("step")
            self.base.last_step_result = SimpleNamespace(step_count=r["step_count"])
            return np.zeros(15, np.float32), 0.0, False, False, {}

    inner = _Recorded()
    v3 = mn.EntityObsV3Wrapper(inner, base=inner.base, character=mn.DEFAULT_CHARACTER)
    out = [mn.flatten(v3.reset()[0])]
    for _ in range(ticks):
        out.append(mn.flatten(v3.step(np.zeros(2, np.int64))[0]))
    return np.stack(out).astype(np.float32)


def goal_on_expected(registered: Mapping[str, Any] = GOAL_ON, *, trace_path: Optional[Path] = None) -> Dict[str, Any]:
    """No game: the P1 goal-on expectations recomputed from the pinned trace, each checked against its registered
    value (trace sha256, word-prefix digest, first valid reach tick, v3 block digest). `problems` empty = usable."""
    import numpy as np

    import m7f_trace as mt

    path = Path(trace_path) if trace_path is not None else REPO_ROOT / registered["trace"]
    out: Dict[str, Any] = {"problems": [], "trace": str(registered["trace"]), "goal": None, "reach_tick": None}
    if not path.is_file():
        out["problems"].append(f"pinned trace {path} missing")
        return out
    sha = sha256_file(path)
    if sha != registered["trace_sha256"]:
        out["problems"].append(f"pinned trace sha256 {sha} != registered {registered['trace_sha256']}")
        return out
    tr = mt.read_trace(path)
    R = int(registered["reach_tick"])
    goal = mg.parse_key(registered["goal"])
    acts, _meta = mt.artifact_actions(REPO_ROOT / tr["artifact"])
    prefix = acts[:R]
    words = [(int(t), int(b), int(sx), int(sy)) for b, sx, sy, t in prefix]
    digest = mt.action_digest(prefix, [a[3] for a in prefix])
    if digest != registered["prefix_action_digest"]:
        out["problems"].append(f"word-prefix digest {digest} != registered {registered['prefix_action_digest']}")
    if [w[0] for w in words] != list(range(R)):
        out["problems"].append("the pinned words are not consumed ticks 0..R-1")
    ini = tr["initial"]
    if int(ini.get("step_count", -1)) != 0 or int((ini.get("observation") or {}).get("input_tick", -1)) != 0:
        out["problems"].append("the pinned trace does not start at normal tick 0")
    steps = list(tr["steps"][:R])
    cells = [mg.state_cell(mg.reply_state(r)) for r in steps]
    first = next((k for k, c in enumerate(cells, start=1) if c == goal), None)
    if first != R:
        out["problems"].append(f"the goal {registered['goal']} is first validly occupied on tick {first}, not {R}")
    other = next((k for k, c in enumerate(cells, start=1) if c is not None and c[:2] == goal[:2] and c[2] != goal[2]), None)
    v3 = recorded_v3(tr, R)
    v3_sha = hashlib.sha256(v3.tobytes()).hexdigest()
    if v3_sha != registered["v3_prefix_sha256"]:
        out["problems"].append(f"v3 block digest {v3_sha} != registered {registered['v3_prefix_sha256']}")
    positions = [(s["x"], s["y"]) for s in (mg.reply_state(r) for r in [ini] + steps)]
    out.update({"goal": goal, "goal_key": mg.cell_key(goal), "reach_tick": R, "repeats": int(registered["repeats"]),
                "words": words, "track1": [track1_of(b, sx, sy) for _t, b, sx, sy in words],
                "prefix_action_digest": digest, "cells": [mg.cell_key(c) if c is not None else None for c in cells],
                "v3": v3, "v3_prefix_sha256": v3_sha,
                "goal_vectors": np.stack([mg.goal_features(goal, x, y, mg.HORIZON - t) for t, (x, y) in enumerate(positions)]),
                "same_bin_other_contact_tick": other})
    return out


def _artifact_words(artifact_dir: Path) -> List[Tuple[int, int, int, int]]:
    from run_artifacts import read_artifact

    return [(a.consumed_tick, a.buttons, a.stick_x, a.stick_y) for a in read_artifact(artifact_dir).actions]


def _goal_on_env(work: Path, settings: Any) -> Any:
    """One real goal worker (rank 0, the M7n v3 environment with its standby) for the goal-on check."""
    import m7s_collect as mc
    import m7s_worker as msw
    from btt_parallel import RunCoordinator, initial_coordination_state
    from m7_runtime import prepare_worker_runtime

    coord = work / "coordination"
    RunCoordinator.create(coord, initial_coordination_state("m7s1_p1_goal_on", "test", None))
    spec = mc.worker_spec(work, 0, "m7s1_p1_goal_on", "test", settings, coord)
    prepare_worker_runtime(Path(spec.worker_dir) / "runtime", Path(settings.executable))
    return msw.build_worker_env_m7s(spec)


def _resolve(p: Any) -> Path:
    q = Path(str(p))
    return q if q.is_absolute() else REPO_ROOT / q


def _repetition_problems(r: Mapping[str, Any], exp: Mapping[str, Any], words: Optional[List[Tuple[int, int, int, int]]],
                         side: Optional[Mapping[str, Any]]) -> List[str]:
    """Every registered P1 goal-on condition for one repetition (empty = identical)."""
    R, key = int(exp["reach_tick"]), exp["goal_key"]
    p: List[str] = []
    if r["v3_mismatch_ticks"]:
        p.append(f"v3 block differs at {len(r['v3_mismatch_ticks'])} ticks, first {r['v3_mismatch_ticks'][:5]}")
    if r["goal_mismatch_ticks"]:
        p.append(f"goal vector differs at ticks {r['goal_mismatch_ticks'][:5]}")
    if r["first_reach"] != R:
        p.append(f"first valid reach on tick {r['first_reach']}, registered {R}")
    end = r.get("end") or {}
    if (end.get("tick"), end.get("terminated"), end.get("truncated"), end.get("truncation_reason")) != (R, False, True, mg.END_GOAL):
        p.append(f"episode end {end}, registered (tick {R}, truncated, {mg.END_GOAL})")
    s = r.get("summary") or {}
    if (s.get("end_reason"), s.get("truncation_reason"), s.get("steps"), bool(s.get("cleared"))) != ("horizon", mg.END_GOAL, R, False):
        p.append(f"tracker summary {s.get('end_reason')} / {s.get('truncation_reason')} / {s.get('steps')} steps / "
                 f"cleared {s.get('cleared')}")
    if s.get("native_action_digest") != exp["prefix_action_digest"]:
        p.append(f"native_action_digest {s.get('native_action_digest')} != the pinned prefix digest")
    if not s.get("preserved"):
        p.append("the episode artifact was not preserved")
    if s.get("startup_mode") not in NORMAL_STARTS:
        p.append(f"startup mode {s.get('startup_mode')} is not a normal tick-0 start")
    if words is None or words != list(exp["words"]):
        n = None if words is None else next((k for k, (a, b) in enumerate(zip(words, exp["words"])) if a != b),
                                            min(len(words), len(exp["words"])))
        p.append(f"recorded native words differ from the pinned prefix (first difference at word {n}, "
                 f"{None if words is None else len(words)} vs {len(exp['words'])} words)")
    if r["sent"] != R:
        p.append(f"{r['sent']} words sent, {R} registered")
    want_cmd = [{"cell": key, "set_tick": 0, "reach_tick": R, "survival_120": None}]
    if side is None:
        p.append("no goal sidecar")
    else:
        if side.get("commanded") != want_cmd:
            p.append(f"sidecar commanded {side.get('commanded')} != {want_cmd}")
        if (side.get("ticks"), side.get("truncation_reason"), side.get("ended_by")) != (R, mg.END_GOAL, mg.END_GOAL):
            p.append(f"sidecar end {side.get('ticks')} / {side.get('truncation_reason')} / {side.get('ended_by')}")
        if side.get("cells") != list(exp["cells"]):
            p.append("sidecar cells differ from the pinned trace's")
        if side.get("plan_entry") != r["repeat"]:
            p.append(f"sidecar plan entry {side.get('plan_entry')} != {r['repeat']}")
    if not r.get("parked_alive_after_truncation"):
        p.append("the process was not alive and parked after the goal_reached truncation")
    return p


def _close_and_check(env: Any, last_episode: Any, processes: Callable[[], List[int]]) -> Dict[str, Any]:
    """Close the worker and verify clean termination: the last parked process ended by terminate() (never killed, never
    exited on its own), the worker owns no live process, its standby closed with the launcher thread joined and no
    cleanup failure, and no BattleShip process is left on the machine."""
    rec: Dict[str, Any] = {"problems": []}
    try:
        env.close()
    except Exception as exc:  # noqa: BLE001 - recorded as a termination problem
        rec["problems"].append(f"close raised {type(exc).__name__}: {exc}")
    base = env.base
    if last_episode is not None:
        rec["last_cleanup_action"] = last_episode.cleanup_action
        rec["last_alive"] = bool(last_episode.alive)
        if last_episode.cleanup_action != "terminated" or last_episode.alive:
            rec["problems"].append(f"last process cleanup {last_episode.cleanup_action}, alive {last_episode.alive}")
    rec["worker_live_processes"] = int(base.live_processes())
    if rec["worker_live_processes"]:
        rec["problems"].append(f"{rec['worker_live_processes']} worker processes alive after close")
    sc = getattr(base, "last_standby_close", None)
    rec["standby_close"] = sc
    if sc is not None and (not sc.get("thread_joined") or sc.get("state") != "no_standby"):
        rec["problems"].append(f"standby close {sc}")
    hist = list(base.standby.history) if getattr(base, "standby", None) is not None else []
    rec["standby_cleanup_actions"] = [h.get("cleanup_action") for h in hist]
    bad = [a for a in rec["standby_cleanup_actions"] if a is not None and (str(a).startswith("cleanup_failure") or a == "still_alive")]
    if bad:
        rec["problems"].append(f"standby cleanup failures {bad}")
    rec["machine_battleship_processes"] = list(processes())
    if rec["machine_battleship_processes"]:
        rec["problems"].append(f"BattleShip processes left after close: {rec['machine_battleship_processes']}")
    return rec


def goal_on_check(work: Path, settings: Any, *, expected: Optional[Mapping[str, Any]] = None,
                  make_env: Optional[Callable[[], Any]] = None,
                  read_words: Optional[Callable[[Path], List[Tuple[int, int, int, int]]]] = None,
                  processes: Optional[Callable[[], List[int]]] = None) -> Dict[str, Any]:
    """P1 (b), the goal-on identity check. The pinned trace's recorded words drive ONE evaluation-mode goal worker
    (plan mode, end_on_success) commanding the registered goal, `repeats` episodes in a row (the first a cold start, the
    next through the normal lifecycle). Each repetition must show exactly: the recorded native word prefix (artifact
    words and digest); the v3 observation block bit-identical to the pinned trace's at every tick 0..R; the goal
    vector exact; the first valid reach on tick R and not earlier; the episode ending there as a truncation with
    truncation_reason goal_reached (tracker end_reason horizon; the sidecar agrees); the process alive and parked
    after that truncation, then ended by terminate(). After the last one the worker closes with no live process and
    none on the machine. No word after tick R is ever sent, so the check consumes at most repeats x R ticks. The
    first failing repetition stops the check; any problem fails P1 and stops the gate before training."""
    import numpy as np

    import m7n_obs as mn
    import m7s_worker as msw

    exp = expected if expected is not None else goal_on_expected()
    rep: Dict[str, Any] = {"ok": False, "ticks": 0, "cap": P1_BUDGET["goal_on"], "repetitions": [],
                           "problems": [f"expectation: {p}" for p in exp.get("problems") or []]}
    if rep["problems"]:
        return rep                                   # refused before anything is launched
    R, goal = int(exp["reach_tick"]), exp["goal"]
    make_env = make_env or (lambda: _goal_on_env(work, settings))
    read_words = read_words or _artifact_words
    processes = processes or game_processes
    t0 = time.perf_counter()
    env = make_env()
    parked = None
    try:
        env.goal.m7s_configure({"mode": "plan", "phase": "P1_goal_on", "episode_quota": int(exp["repeats"]),
                                "end_on_success": True,
                                "plan": [{"entry": e, "goal": goal} for e in range(int(exp["repeats"]))]})
        for k in range(int(exp["repeats"])):
            obs, _slim = env.reset()
            if parked is not None:                    # the previous repetition's parked process, retired by this reset
                prev = rep["repetitions"][-1]
                prev["retire_action"], prev["exited_after_retire"] = parked.cleanup_action, not parked.alive
                if parked.cleanup_action != "terminated" or parked.alive:
                    rep["problems"].append(f"repeat {k - 1}: parked process retired as {parked.cleanup_action}, "
                                           f"alive {parked.alive}")
                    parked = env.base.episode         # the newly started process: closed and checked below
                    break                             # no word of the next repetition is sent
            r: Dict[str, Any] = {"repeat": k, "sent": 0, "first_reach": None, "end": None, "summary": None,
                                 "v3_mismatch_ticks": [], "goal_mismatch_ticks": []}
            rep["repetitions"].append(r)

            def compare(t: int, o: Mapping[str, Any]) -> None:
                if mn.flatten(o).tobytes() != exp["v3"][t].tobytes():
                    r["v3_mismatch_ticks"].append(t)
                if not np.array_equal(np.asarray(o[msw.GOAL_KEY], dtype=np.float32), exp["goal_vectors"][t]):
                    r["goal_mismatch_ticks"].append(t)

            compare(0, obs)
            for t in range(1, R + 1):                 # never a word after the registered reach tick
                obs, _rew, term, trunc, info = env.step(np.asarray(exp["track1"][t - 1], dtype=np.int64))
                r["sent"] += 1
                rep["ticks"] += 1
                compare(t, obs)
                if "reached" in ((info.get("m7s") or {}).get("events") or []) and r["first_reach"] is None:
                    r["first_reach"] = t
                if term or trunc:
                    r["end"] = {"tick": t, "terminated": bool(term), "truncated": bool(trunc),
                                "truncation_reason": info.get("truncation_reason"),
                                "termination_reason": info.get("termination_reason")}
                    s = info.get("m7_episode") or {}
                    r["summary"] = {k2: s.get(k2) for k2 in ("episode_id", "artifact_dir", "end_reason", "truncation_reason",
                                                             "termination_reason", "steps", "cleared", "preserved",
                                                             "native_action_digest", "startup_mode")}
                    break
            parked = env.base.episode
            r["parked_alive_after_truncation"] = bool(parked is not None and parked.alive)
            words = side = None
            art = (r["summary"] or {}).get("artifact_dir")
            if art:
                import gzip

                words = read_words(_resolve(art))
                sp = _resolve(art) / mg.SIDECAR_FILE
                if sp.is_file():
                    with gzip.open(sp, "rt", encoding="utf-8") as fp:
                        side = json.load(fp)
            r["problems"] = _repetition_problems(r, exp, words, side)
            rep["problems"] += [f"repeat {k}: {p}" for p in r["problems"]]
            if rep["problems"]:
                break
    except Exception as exc:  # noqa: BLE001 - a raised check is a failed check
        rep["problems"].append(f"raised {type(exc).__name__}: {exc}")
    finally:
        rep["termination"] = _close_and_check(env, parked, processes)
    rep["problems"] += [f"termination: {p}" for p in rep["termination"]["problems"]]
    rep["wall_s"] = round(time.perf_counter() - t0, 2)
    rep["ok"] = not rep["problems"] and rep["ticks"] == int(exp["repeats"]) * R
    return rep


def p1_identity(work: Path, settings: Any, *, null_goal: Optional[Callable[..., Dict[str, Any]]] = None,
                goal_on: Optional[Callable[..., Dict[str, Any]]] = None) -> Dict[str, Any]:
    """P1 before any training: (a) the null-goal word identity, then (b) the goal-on identity. The first failure
    (including a raised check) stops P1; every sent tick is counted against its cap."""
    null_goal = null_goal or identity_check
    goal_on = goal_on or goal_on_check
    out: Dict[str, Any] = {"ok": False, "ticks": 0, "caps": dict(P1_BUDGET), "stopped_at": None}
    for name, fn in (("null_goal", null_goal), ("goal_on", goal_on)):
        try:
            res = fn(work / name, settings)
        except Exception as exc:  # noqa: BLE001 - a raised check is a failed check
            res = {"ok": False, "ticks": 0, "problems": [f"raised {type(exc).__name__}: {exc}"]}
        out[name] = res
        out["ticks"] += int(res.get("ticks") or 0)
        if int(res.get("ticks") or 0) > P1_BUDGET[name]:
            res["ok"] = False
            res.setdefault("problems", []).append(f"{res.get('ticks')} ticks exceed the cap {P1_BUDGET[name]}")
        if not res.get("ok"):
            out["stopped_at"] = name
            return out
    out["ok"] = out["ticks"] == TICK_BUDGET["p1_identity"]
    return out


# -- one seed (game) -------------------------------------------------------------------------------------------------------


def _venv(root: Path, run_id: str, role: str, settings: Any) -> Any:
    import m7s_collect as mc
    from m7_vec_env import M7SubprocVecEnv

    return M7SubprocVecEnv(mc.prepare_factories(root, run_id, role, settings), step_timeout=settings.step_timeout)


def _phase(root: Path, run_id: str, role: str, settings: Any, **kw: Any) -> Any:
    import m7s_collect as mc

    venv = _venv(root, run_id, role, settings)
    try:
        return mc.run_phase(venv=venv, **kw)
    finally:
        venv.close()


def end_class(e: Mapping[str, Any]) -> str:
    """How an episode ended. The tracker labels every truncation end_reason `horizon`; truncation_reason tells a first
    valid reach (goal_reached) from a worker tick quota (tick_quota) and the native horizon (max_episode_steps)."""
    er, tr = e.get("end_reason"), e.get("truncation_reason")
    if er == "horizon":
        return {mg.END_GOAL: "goal_reached", mg.END_QUOTA: "tick_quota", mg.NATIVE_HORIZON: "native_horizon"}.get(tr, "other")
    return {"fall": "fall", "clear": "clear", "lifecycle_failure": "lifecycle_failure"}.get(str(er), "other")


def clear_fact_problems(e: Mapping[str, Any]) -> List[str]:
    """A clear is recorded only when the four recorded facts agree (M7d): end_reason clear with termination
    native_clear and no truncation, the cleared flag, ten broken targets and both completion clocks. A cleared flag on
    any other end is equally inconsistent."""
    from btt_parallel import TARGETS_TOTAL, TERMINATION_NATIVE_CLEAR

    who = e.get("episode_id")
    if end_class(e) != "clear":
        return [f"{who}: cleared flag on a {end_class(e)} end"] if e.get("cleared") else []
    p = []
    if e.get("termination_reason") != TERMINATION_NATIVE_CLEAR or e.get("truncation_reason") is not None:
        p.append(f"{who}: clear with termination {e.get('termination_reason')} / truncation {e.get('truncation_reason')}")
    if not e.get("cleared"):
        p.append(f"{who}: end_reason clear without the cleared flag")
    if e.get("targets_broken") != TARGETS_TOTAL:
        p.append(f"{who}: clear with {e.get('targets_broken')} targets broken")
    if not isinstance(e.get("completion_time_passed"), int) or not isinstance(e.get("completion_input_tick"), int):
        p.append(f"{who}: clear without both completion clocks")
    return p


def _eval_rows(res: Any, plan: Sequence[Mapping[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Evaluation rows for the rule. Success is decided by truncation_reason == goal_reached ONLY, and must agree with the
    sidecar: a success has its reach on the last recorded tick; every other end has no reach; an evaluation episode can
    never end by the tick quota. A native clear (also one on the tick the goal is entered) is an accepted end, never a
    return; its recorded clear facts must agree, and it is claimed only after an exact native replay (verify_clears)."""
    problems: List[str] = []
    by_entry = {int(e["plan_entry"]): e for e in res.episodes if e.get("plan_entry") is not None}
    rows = []
    for p in plan:
        e = by_entry.get(int(p["entry"]))
        if e is None:
            problems.append(f"plan entry {p['entry']} has no episode")
            continue
        cmd = ((e.get("m7s") or {}).get("commanded") or [{}])[0]
        if cmd.get("cell") != p["cell"]:
            problems.append(f"plan entry {p['entry']}: commanded {cmd.get('cell')} != {p['cell']}")
        if not e.get("preserved"):
            problems.append(f"plan entry {p['entry']}: episode not preserved")
        cls = end_class(e)
        reach = cmd.get("reach_tick")
        success = cls == "goal_reached"
        if success and reach != e.get("ticks"):
            problems.append(f"plan entry {p['entry']}: goal_reached but sidecar reach {reach} != last tick {e.get('ticks')}")
        if not success and reach is not None:
            problems.append(f"plan entry {p['entry']}: reach {reach} recorded but the episode ended as {cls}")
        if cls in ("tick_quota", "other"):
            problems.append(f"plan entry {p['entry']}: evaluation episode ended as {cls} ({e.get('truncation_reason')})")
        problems += [f"plan entry {p['entry']}: {q}" for q in clear_fact_problems(e)]
        rows.append({"entry": int(p["entry"]), "stratum": p["stratum"], "cell": p["cell"], "success": success,
                     "end_class": cls, "end_reason": e.get("end_reason"), "truncation_reason": e.get("truncation_reason"),
                     "termination_reason": e.get("termination_reason"), "cleared": bool(e.get("cleared")),
                     "reach_tick": reach, "episode_id": e.get("episode_id"), "artifact_dir": e.get("artifact_dir"),
                     "native_action_digest": e.get("native_action_digest"), "ticks": e.get("ticks"), "rank": e.get("rank")})
    if len(res.episodes) != len(plan):
        problems.append(f"{len(res.episodes)} evaluation episodes for {len(plan)} plan entries")
    return rows, problems


def replay_precondition(row: Mapping[str, Any]) -> List[str]:
    """A replay may only be used as evidence of a return when the row is a goal_reached truncation ending on its reach."""
    p = []
    if row.get("truncation_reason") != mg.END_GOAL or row.get("end_class") != "goal_reached":
        p.append(f"{row.get('episode_id')}: not a goal_reached episode ({row.get('end_reason')}, {row.get('truncation_reason')})")
    if row.get("reach_tick") is None or row.get("reach_tick") != row.get("ticks"):
        p.append(f"{row.get('episode_id')}: reach {row.get('reach_tick')} is not the last tick {row.get('ticks')}")
    return p


def replay_success(row: Mapping[str, Any], work: Path, settings: Any, index: int) -> Dict[str, Any]:
    """Exact tick-0 replay of one claimed return: the row must be a goal_reached truncation; equal action digest;
    per-tick cells equal to the sidecar's; the goal first occupied (validly) at the recorded reach tick, which is the
    last recorded tick."""
    import gzip

    import m7f_trace as mt

    pre = replay_precondition(row)
    if pre:
        return {"episode_id": row.get("episode_id"), "ok": False, "problems": pre, "ticks": 0}
    art = Path(row["artifact_dir"])
    art = art if art.is_absolute() else REPO_ROOT / art
    with gzip.open(art / mg.SIDECAR_FILE, "rt", encoding="utf-8") as fp:
        side = json.load(fp)
    acts, _meta = mt.artifact_actions(art)
    tr = mt.run_stepping_trace(f"m7s1_replay_{index}", EXECUTABLE, acts, work, extra_env=dict(settings.extra_env),
                               index=9900 + index)
    cells = [mg.cell_key(c) if (c := mg.state_cell(mg.reply_state(r))) else None for r in tr.get("steps") or []]
    goal = row["cell"]
    first = next((k for k, c in enumerate(cells, start=1) if c == goal), None)
    rec = {"episode_id": row["episode_id"], "cell": goal, "digest_equal": tr.get("action_digest") == row["native_action_digest"],
           "consumed_tick_mismatch": tr.get("consumed_tick_mismatch"), "unsent": tr.get("unsent"),
           "cells_equal_sidecar": cells == list(side.get("cells") or []), "first_reach": first,
           "recorded_reach": row["reach_tick"], "ticks": len(cells),
           "sidecar_truncation_reason": side.get("truncation_reason")}
    rec["ok"] = bool(rec["digest_equal"] and rec["consumed_tick_mismatch"] is None and rec["unsent"] == 0
                     and rec["cells_equal_sidecar"] and first == row["reach_tick"] == len(cells)
                     and side.get("truncation_reason") == mg.END_GOAL)
    return rec


def clear_candidates(groups: Sequence[Tuple[str, Sequence[Mapping[str, Any]]]], *,
                     fact_check_sources: Optional[Sequence[str]] = None) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Every episode that ended as a native clear, in the registered order of `groups` (evaluation R, evaluation U,
    phase B R, phase B U, phase A), deduplicated by native action digest; plus the clear-fact problems of the rows of
    `fact_check_sources` (default: all; the evaluation rows are already checked by _eval_rows)."""
    cands: List[Dict[str, Any]] = []
    problems: List[str] = []
    seen = set()
    for source, rows in groups:
        for e in rows:
            if fact_check_sources is None or source in fact_check_sources:
                problems += [f"{source}: {q}" for q in clear_fact_problems(e)]
            if end_class(e) != "clear" or str(e.get("native_action_digest")) in seen:
                continue
            seen.add(str(e.get("native_action_digest")))
            cands.append({"source": source, "episode_id": e.get("episode_id"), "artifact_dir": e.get("artifact_dir"),
                          "preserved": bool(e.get("preserved")), "native_action_digest": e.get("native_action_digest"),
                          "ticks": e.get("ticks"), "targets_broken": e.get("targets_broken"),
                          "completion_time_passed": e.get("completion_time_passed"),
                          "completion_input_tick": e.get("completion_input_tick"),
                          "goal_reach_tick": (((e.get("m7s") or {}).get("commanded") or [{}])[-1]).get("reach_tick")})
    return cands, problems


def verify_clears(cands: Sequence[Mapping[str, Any]], work: Path, settings: Any, *, index_base: int,
                  cap: int = CLEAR_REPLAYS_PER_SEED, replay: Optional[Callable[..., Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Exact native replay of the first `cap` preserved clear candidates with the project's clear verifier
    (m7d_run.replay_one: fresh process, tick 0, canonical words; verified = every check passes, native clear, and
    completion_time_passed / completion_input_tick equal to the recorded pair, never collapsed). Only a verified clear
    is claimed; a candidate beyond the cap or without an artifact is reported as unverified and never claimed; a
    replayed clear that does not verify is an integrity problem."""
    if replay is None:
        import m7d_run as dr

        replay = dr.replay_one
    out: Dict[str, Any] = {"candidates": len(cands), "cap": int(cap), "replayed": [], "unverified_not_claimed": [],
                           "ticks": 0, "problems": []}
    for c in cands:
        if len(out["replayed"]) >= cap or not c.get("preserved") or not c.get("artifact_dir"):
            out["unverified_not_claimed"].append(dict(c, reason="over the replay cap" if len(out["replayed"]) >= cap
                                                      else "no preserved artifact"))
            continue
        k = len(out["replayed"])
        rec = replay(_resolve(c["artifact_dir"]), work / f"clear{k}", executable=Path(settings.executable),
                     extra_env=dict(settings.extra_env), index=index_base + k)
        checks = rec.get("checks") or {}
        clocks = [rec.get("completion_time_passed"), rec.get("completion_input_tick")]
        verified = bool(rec.get("ok") and checks.get("native_clear") and checks.get("completion_clocks")
                        and clocks == [c.get("completion_time_passed"), c.get("completion_input_tick")])
        out["ticks"] += int(rec.get("submitted") or 0)
        out["replayed"].append({"episode_id": c.get("episode_id"), "source": c.get("source"),
                                "recorded_clocks": [c.get("completion_time_passed"), c.get("completion_input_tick")],
                                "replayed_clocks": clocks, "checks": checks, "submitted": rec.get("submitted"),
                                "verified": verified})
        if not verified:
            out["problems"].append(f"claimed clear {c.get('episode_id')} ({c.get('source')}) did not replay exactly")
    out["verified"] = sum(1 for r in out["replayed"] if r["verified"])
    return out


def post_training_sensitivity(dataset: Sequence[mg.EpisodeData], r_pol: Any, u_pol: Any, goal_pool: Sequence[mg.Cell],
                              seed: int, n: int = 4000) -> Dict[str, Any]:
    """Goal-swap sensitivity of R after training and of U (= initialisation) on the same states from R's own episodes
    and the same goal pairs (the frozen E cells), so a goal-blind policy is visible. Rule v2 uses goal_blind_flag
    (R's TV < 0.01, fixed before any live run) to refuse a pass; everything else here is reported only."""
    import numpy as np

    import m7s_policy as mp

    rng = mg.generator("sensitivity", seed)
    eps = [e for e in dataset if len(e.cells)]
    picks = [(int(rng.integers(len(eps))), 0) for _ in range(n)]
    picks = [(i, int(rng.integers(len(eps[i].cells)))) for i, _ in picks]
    v3 = np.stack([eps[i].obs[t] for i, t in picks])
    pos = np.stack([eps[i].pos[t] for i, t in picks])
    ticks = np.array([t for _i, t in picks])
    r = mp.goal_sensitivity(r_pol, v3, pos, ticks, list(goal_pool), pairs=2000, seed=seed)
    u = mp.goal_sensitivity(u_pol, v3, pos, ticks, list(goal_pool), pairs=2000, seed=seed)
    return {"U_initial": u, "R_final": r, "goal_blind_tv": mp.GOAL_BLIND_TV,
            "goal_blind_flag": bool(r["action_tv_goal_swap"] < mp.GOAL_BLIND_TV),
            "tv_ratio_R_over_U": round(r["action_tv_goal_swap"] / max(u["action_tv_goal_swap"], 1e-12), 2)}


def rule_goal_sensitivity(sens: Mapping[str, Any]) -> Dict[str, Any]:
    """The rule-v2 input (goal-blind safeguard, decisive for a pass) from post_training_sensitivity's record."""
    return {"R_goal_swap_tv": sens["R_final"]["action_tv_goal_swap"], "U_goal_swap_tv": sens["U_initial"]["action_tv_goal_swap"],
            "goal_blind_flag": bool(sens["goal_blind_flag"])}


def collection_reaches(episodes: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Reported only: commanded-goal reaches in collection and the NON-DECISIVE 120-tick survival diagnostic."""
    cmds = [c for e in episodes for c in (e.get("m7s") or {}).get("commanded", [])]
    reached = [c for c in cmds if c.get("reach_tick") is not None]
    surv = [c.get("survival_120") for c in reached]
    return {"commanded": len(cmds), "reached": len(reached), "survival_120_true": sum(1 for v in surv if v is True),
            "survival_120_false": sum(1 for v in surv if v is False), "survival_120_censored": sum(1 for v in surv if v is None)}


def seed_run(seed: int, settings: Any, ledger: Dict[str, int]) -> Dict[str, Any]:
    import m7s_collect as mc
    import m7s_policy as mp

    root = GATE_ROOT / f"s{seed}"
    out: Dict[str, Any] = {"seed": seed, "problems": [], "walls": {}}
    init = mp.init_policy(seed)
    init_digest = mp.save_policy(root / "init.pt", init, {"seed": seed, "role": "shared initial parameters"})
    out["init_digest"] = init_digest
    dataset: List[mg.EpisodeData] = []

    res_a = _phase(root / "phase_a", f"m7s1_s{seed}_A", "training", settings, configs=mc.phase_configs("null", phase="A"),
                   policy=init, seed=seed, phase="A", tick_cap=mg.PHASE_A_EPISODES * mg.HORIZON, store=True,
                   dataset=dataset)
    ledger["phase_a"] += res_a.ticks
    out["walls"]["phase_a"] = res_a.wall_s
    pa = mc.phase_a_episodes(res_a)
    goal_set = mg.freeze_goal_set(seed, pa)
    prov = mg.check_provenance(goal_set, pa)
    if prov or not all(e["preserved"] for e in res_a.episodes):
        out["problems"] += prov + ([] if all(e["preserved"] for e in res_a.episodes) else ["phase-A episode not preserved"])
    schedule = mg.make_schedule(seed, goal_set)
    plan = mg.make_eval_plan(seed, goal_set)
    write_json(root / "goal_set.json", goal_set)
    write_json(root / "schedule.json", schedule)
    write_json(root / "eval_plan.json", plan)
    out["phase_a"] = {"ticks": res_a.ticks, "episodes": len(res_a.episodes), "goal_set_digest": goal_set["digest"],
                      "schedule_digest": schedule["digest"], "candidates": goal_set["candidates"]}
    rare = [g["cell"] for g in goal_set["rare"]]
    mid = [g["cell"] for g in goal_set["mid"]]

    # R: phase B with GCSL updates
    r_pol, r_meta = mp.load_policy(root / "init.pt")
    trainer = mp.GCSLTrainer(r_pol, seed)
    res_rb = _phase(root / "R_phase_b", f"m7s1_s{seed}_RB", "training", settings,
                    configs=mc.phase_configs("schedule", phase="B_R", schedule=schedule), policy=r_pol, seed=seed,
                    phase="B_R", tick_cap=mc.PHASE_B_TICKS, store=True, trainer=trainer, dataset=dataset,
                    chunk_ticks=mp.CHUNK_TICKS)
    ledger["phase_b"] += res_rb.ticks
    out["walls"]["R_phase_b"] = res_rb.wall_s
    if res_rb.ticks != mc.PHASE_B_TICKS or len(res_rb.train_chunks) != mc.PHASE_B_TICKS // mp.CHUNK_TICKS \
            or trainer.gradient_steps != (mc.PHASE_B_TICKS // mp.CHUNK_TICKS) * mp.STEPS_PER_CHUNK:
        out["problems"].append(f"R phase B accounting: {res_rb.ticks} ticks, {len(res_rb.train_chunks)} chunks, "
                               f"{trainer.gradient_steps} gradient steps")
    r_final = mp.save_policy(root / "R_final.pt", r_pol, {"seed": seed, "gradient_steps": trainer.gradient_steps})
    write_json(root / "R_train_chunks.json", res_rb.train_chunks)
    data_counts = {g: sum(1 for e in res_rb.episodes if g in e["first_reach"]) for g in rare}
    u_init, _ = mp.load_policy(root / "init.pt")
    out["goal_sensitivity"] = post_training_sensitivity(dataset, r_pol, u_init, [mg.parse_key(c) for c in rare + mid], seed)
    del dataset

    # U: the same schedule and ticks, no updates
    u_pol, _ = mp.load_policy(root / "init.pt")
    res_ub = _phase(root / "U_phase_b", f"m7s1_s{seed}_UB", "training", settings,
                    configs=mc.phase_configs("schedule", phase="B_U", schedule=schedule), policy=u_pol, seed=seed,
                    phase="B_U", tick_cap=mc.PHASE_B_TICKS, store=False)
    ledger["phase_b"] += res_ub.ticks
    out["walls"]["U_phase_b"] = res_ub.wall_s
    if res_ub.ticks != mc.PHASE_B_TICKS or mp.parameter_digest(u_pol) != init_digest:
        out["problems"].append(f"U phase B: {res_ub.ticks} ticks, parameters unchanged {mp.parameter_digest(u_pol) == init_digest}")

    # held-out evaluation, identical plan and sampling seeds
    evals: Dict[str, List[Dict[str, Any]]] = {}
    eval_res: Dict[str, Any] = {}
    for arm, pol in (("R", r_pol), ("U", u_pol)):
        res_e = _phase(root / f"{arm}_eval", f"m7s1_s{seed}_E{arm}", "evaluation", settings,
                       configs=mc.phase_configs("plan", phase=f"E_{arm}", plan=plan), policy=pol, seed=seed,
                       phase=f"E_{arm}", tick_cap=mc.EVAL_EPISODES * mg.HORIZON, store=False, plan=plan)
        ledger["evaluation"] += res_e.ticks
        out["walls"][f"{arm}_eval"] = res_e.wall_s
        rows, probs = _eval_rows(res_e, plan)
        out["problems"] += [f"{arm} eval: {p}" for p in probs]
        evals[arm] = rows
        eval_res[arm] = res_e
    if mp.parameter_digest(u_pol) != init_digest or mp.parameter_digest(r_pol) != r_final:
        out["problems"].append("a policy changed during evaluation")

    # exact replays of the first two R and two U rare successes
    replays = []
    for arm in ("R", "U"):
        wins = [r for r in evals[arm] if r["stratum"] == "rare" and r["success"]][:REPLAYS_PER_ARM]
        for k, row in enumerate(wins):
            rec = replay_success(row, root / "_replays" / f"{arm}{k}", settings, index=10 * seed + 4 * (arm == "U") + k)
            ledger["replays"] += int(rec["ticks"])
            replays.append(dict(rec, arm=arm))
    out["replays"] = replays
    out["problems"] += [f"replay {r['arm']} {r['episode_id']} not exact" for r in replays if not r["ok"]]

    # claimed clears (never returns): exact native replay of the first CLEAR_REPLAYS_PER_SEED, the rest never claimed
    groups = [("evaluation_R", eval_res["R"].episodes), ("evaluation_U", eval_res["U"].episodes),
              ("phase_b_R", res_rb.episodes), ("phase_b_U", res_ub.episodes), ("phase_a", res_a.episodes)]
    cands, cprobs = clear_candidates(groups, fact_check_sources=("phase_b_R", "phase_b_U", "phase_a"))
    out["problems"] += cprobs
    clears = verify_clears(cands, root / "_clears", settings, index_base=9800 + 10 * seed)
    ledger["clear_replays"] += int(clears["ticks"])
    out["clears"] = clears
    out["problems"] += clears["problems"]
    u_chance = {g: round(sum(1 for e in res_ub.episodes if g in e["first_reach"]) / max(1, len(res_ub.episodes)), 4)
                for g in rare + mid}
    out["analysis_inputs"] = {"r_eval": evals["R"], "u_eval": evals["U"], "rare_goals": rare, "mid_goals": mid,
                              "data_counts": data_counts, "goal_sensitivity": rule_goal_sensitivity(out["goal_sensitivity"])}
    out["reported"] = {"u_phase_b_chance_visit_rate": u_chance, "u_phase_b_episodes": len(res_ub.episodes),
                       "clears": {k: clears[k] for k in ("candidates", "verified", "replayed", "unverified_not_claimed")},
                       "r_phase_b_episodes": len(res_rb.episodes),
                       "r_phase_b_reaches": collection_reaches(res_rb.episodes),
                       "u_phase_b_reaches": collection_reaches(res_ub.episodes),
                       "goal_sensitivity_after_training": out.get("goal_sensitivity"),
                       "last_train_chunk": res_rb.train_chunks[-1] if res_rb.train_chunks else None}
    return out


# -- run -------------------------------------------------------------------------------------------------------------------


def cmd_run(*, p1: Optional[Callable[..., Dict[str, Any]]] = None,
            seed_fn: Optional[Callable[..., Dict[str, Any]]] = None) -> int:
    """`p1` / `seed_fn` default to p1_identity / seed_run (replaceable only by the offline tests)."""
    import m7s_collect as mc
    from m7_runtime import install_kill_on_close_job

    p1 = p1 or p1_identity
    seed_fn = seed_fn or seed_run
    pf = preflight()
    if not pf["ok"]:
        print(json.dumps(pf, indent=1))
        print("refused: preflight problems (see above); nothing was launched")
        return 2
    install_kill_on_close_job()
    settings = mc.env_settings()
    ledger = {k: 0 for k in TICK_BUDGET if k != "total"}
    state: Dict[str, Any] = {"started_utc": utc(), "identity": identity(), "preflight": pf, "ledger": ledger, "phases": {}}
    write_json(STATE_DIR / "state.json", state)
    t0 = time.perf_counter()
    ic = p1(STATE_DIR / "p1", settings)
    ic["wall_s"] = round(time.perf_counter() - t0, 1)
    ledger["p1_identity"] += int(ic.get("ticks") or 0)
    state["phases"]["p1_identity"] = ic
    if not ic.get("ok") or ledger["p1_identity"] > TICK_BUDGET["p1_identity"]:
        state["stopped"] = f"P1 failed at {ic.get('stopped_at')}; no training started"
        state["finished_utc"] = utc()
        write_json(STATE_DIR / "state.json", state)
        print(f"invalid: P1 (live identity) failed at {ic.get('stopped_at')}; stopping before any training")
        return 3
    write_json(STATE_DIR / "state.json", state)
    state["phases"]["seeds"] = {}
    for s in SEEDS:
        state["phases"]["seeds"][str(s)] = seed_fn(s, settings, ledger)
        write_json(STATE_DIR / "state.json", state)
        if state["phases"]["seeds"][str(s)]["problems"]:
            print(f"invalid: integrity problems in seed {s}; stopping")
            break
    over = {k: (v, TICK_BUDGET[k]) for k, v in ledger.items() if v > TICK_BUDGET[k]}
    state["ledger_over_budget"] = over
    decision = analyse(state)
    state["finished_utc"] = utc()
    write_json(STATE_DIR / "state.json", state)
    print(json.dumps(decision, indent=1)[:4000])
    return 0


def analyse(state: Mapping[str, Any]) -> Dict[str, Any]:
    seeds = (state.get("phases") or {}).get("seeds") or {}
    problems = [f"seed {s}: {p}" for s, r in seeds.items() for p in r.get("problems", [])]
    ic = (state.get("phases") or {}).get("p1_identity") or {}
    if not ic.get("ok"):
        problems.append(f"P1 identity check (stopped at {ic.get('stopped_at')})")
    problems += [f"budget {k}: {v}" for k, v in (state.get("ledger_over_budget") or {}).items()]
    complete = len(seeds) == len(SEEDS)
    decision = ma.decide({"integrity": {"ok": not problems, "problems": problems}, "complete": complete,
                          "incomplete_reasons": [] if complete else [f"{len(seeds)} of {len(SEEDS)} seeds"],
                          "seeds": {s: r["analysis_inputs"] for s, r in seeds.items() if "analysis_inputs" in r}})
    decision["reported"] = {s: r.get("reported") for s, r in seeds.items()}   # never deciding
    decision["clears"] = {"verified": sum(int((r.get("clears") or {}).get("verified") or 0) for r in seeds.values()),
                          "candidates": sum(int((r.get("clears") or {}).get("candidates") or 0) for r in seeds.values()),
                          "note": "reported only; a clear is never a return and is claimed only when verified"}
    decision["ledger"] = dict(state.get("ledger") or {})
    decision["tick_budget"] = TICK_BUDGET
    write_json(STATE_DIR / "analysis.json", decision)
    return decision


def init_check() -> Dict[str, Any]:
    """No game: the registered initialisation diagnostics on real v3 observations of the pinned traces."""
    import m7s_tests as mt

    return mt.init_check_report()


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("status", "preflight", "approval-template", "init-check", "run"))
    ap.add_argument("--skip-unit", action="store_true")
    a = ap.parse_args(argv)
    if a.command == "approval-template":
        print(json.dumps(dict(identity(), approval="PENDING (replace with 'APPROVED: <text>' only after review)"), indent=1))
        return 0
    if a.command == "preflight":
        rep = preflight(run_unit=not a.skip_unit)
        print(json.dumps(rep, indent=1))
        return 0 if rep["ok"] else 1
    if a.command == "init-check":
        rep = init_check()
        print(json.dumps(rep, indent=1))
        return 0 if rep.get("sensitivity_in_registered_range") else 1
    if a.command == "status":
        st = STATE_DIR / "state.json"
        print(json.dumps({"state": json.loads(st.read_text(encoding="utf-8")) if st.is_file() else None,
                          "approval": approval_status()[1], "tick_budget": TICK_BUDGET}, indent=1)[:4000])
        return 0
    return cmd_run()


if __name__ == "__main__":
    sys.exit(main())
