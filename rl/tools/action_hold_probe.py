#!/usr/bin/env python3
"""Action-hold reachability probe (no training, no policy): can uniformly random Track 1 actions, each held for k
native ticks, reach the region the Mario BTT crossing needs from a normal tick-0 start?

Registered before running (write-once docs/rl_action_hold_probe_registration.json): hold lengths k in {1, 4, 8, 16},
100 fresh-process tick-0 episodes per k with Python seeds and an exact episode list, uniform sampling over the 72
Track 1 combinations at each decision boundary, the hold semantics, the recording contract, the S1-S5 stage
definitions, the feasibility threshold and the metrics. The rule is applied once by `summarize` (write-once decision).

Hold semantics: the chosen native (buttons, stick_x, stick_y) triple is submitted for up to k consecutive ticks; every
tick is one `step` request consuming exactly one native tick (consumed_tick == t, input_tick == t + 1 in the reply);
the hold stops immediately on a native episode end or a native failure; the final hold is clipped to the 3,600-tick
horizon. Nothing is hidden, skipped or merged; button-edge semantics are whatever the game makes of the repeated
native state (identical to a human holding the button).

    python rl/tools/action_hold_probe.py register
    python rl/tools/action_hold_probe.py run [--workers 3]
    python rl/tools/action_hold_probe.py replay          # exact replays of every episode meeting the threshold
    python rl/tools/action_hold_probe.py summarize       # per-k table + the registered rule, applied once

Reuses the M7n prefix-feasibility staging (S1-S5) and the M7f stepping-trace replay. Native gameplay is authoritative;
native RNG is never inspected; the crossing fixtures and the TAS are not read.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import multiprocessing
import os
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parents[1]
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))
TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

REPO_ROOT = RL_DIR.parent
OUT = REPO_ROOT / "runs" / "probes" / "action_hold"
REG_DOC = REPO_ROOT / "docs" / "rl_action_hold_probe_registration.json"
DECISION_DOC = REPO_ROOT / "docs" / "rl_action_hold_probe_decision.json"
EXECUTABLE = REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"
FLAGS = {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1", "SSB64_RL_SPATIAL": "1", "SSB64_RL_ENTITY": "1",
         "SSB64_RL_TARGET_DIAG": "1"}
HOLDS: Tuple[int, ...] = (1, 4, 8, 16)
EPISODES_PER_K = 100
HORIZON = 3600
TRACK1_COMBINATIONS = 72
ELEVATED_Y = 2400.0
LEDGE_RIGHT_X = -1200.0
WALL_TOP_Y = 3000.0
LEFT_TARGET_IDS = (1, 6, 8)
S2_THRESHOLD = 3          # per k, of 100 episodes
S3_THRESHOLD = 1          # per k, any raw over-wall entry

STAGES = {
    "cut": "0: every stage counts from the tick-0 reset; there is no prefix and no policy",
    "S1_approach": "a live post-update observation (fighter_valid 1, btt_active 1) with position_x <= -1200 (past the ledge's right end, at any height)",
    "S2_over_ledge": "a live observation with position_y >= 3000 and position_x <= -1200 (at or above the wall top, over the ledge span); evidence of reachability only",
    "S3_over_wall_entry": "an `over_wall` entry of btt_reward_v3.classify_entry (the pair of consecutive live observations crossing x = -2100 with interpolated crossing height >= wall top - tolerance); a raw entry, not a crossing",
    "S4_qualified_crossing": "btt_qualified_crossing_v1 (rl/m7n_crossing.analyse_trace): over_wall entry + over-ledge path + grounded takeoff + landing on a decoded left floor in the same visit",
    "S5_left_target_break": "target 1, 6 or 8 broken (btt_target_identity_v1 break records)",
    "elevated_step": "a live observation with position_y >= 2400 (two 800-unit cells above the main floor at y -2550)",
    "also_recorded": ["end (clear / fall / horizon)", "targets broken and per-target break ticks", "min live x, max live y",
                      "reward v2 return", "decisions and realised hold lengths", "native action digest", "raw replies (gz)"],
}
RULE = {
    "threshold_per_k": f"S2 in >= {S2_THRESHOLD} of {EPISODES_PER_K} episodes OR S3 in >= {S3_THRESHOLD} episode(s)",
    "if_some_k_gt_1_meets_it": "temporally correlated random actions can reach the relevant region under this probe (exploration "
                               "reachability); NOT a qualified crossing, NOT a learned success, NOT evidence that PPO will learn a crossing",
    "if_none_meets_it": "no foothold under the tested hold lengths; Track 1 crossing controllability is already established by the "
                        "validated fixtures and is not what this probe tests",
    "k_1_meets_it": "reported as such (per-tick random reachability); the comparison of interest is k > 1 against k = 1",
    "verification": "every episode meeting the threshold is replayed exactly (fresh process, same native rows) and its trajectory "
                    "re-staged; an episode whose replay is not exact or whose replay does not reproduce the stage is reported and "
                    "does not count",
    "applied": "once, by `summarize`, written to docs/rl_action_hold_probe_decision.json (write-once)",
    "never": ["a threshold changed after seeing results", "a raw over-wall entry or S2 called a crossing",
              "fixture or TAS inputs used to construct or seed the probe", "an extension or extra condition added after the run"],
}


# -- io --------------------------------------------------------------------------------------------------------------


def read_json(p: Path) -> Any:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def write_json(p: Path, d: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=1, sort_keys=False) + "\n", encoding="utf-8")


def write_once(p: Path, d: Any) -> None:
    if p.exists():
        raise SystemExit(f"{p} exists; registrations and decisions are write-once")
    write_json(p, d)


def sha256_file(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def log(msg: str) -> None:
    print(f"[hold-probe {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())


def episode_seed(k: int, i: int) -> int:
    return int(hashlib.sha256(f"action_hold|{k}|{i}".encode("ascii")).hexdigest()[:8], 16)


def episode_list() -> List[Dict[str, Any]]:
    eps = []
    idx = 0
    for k in HOLDS:
        for i in range(EPISODES_PER_K):
            idx += 1
            eps.append({"k": k, "i": i, "seed": episode_seed(k, i), "index": 8000 + idx})
    return eps


def episode_path(k: int, i: int) -> Path:
    return OUT / "episodes" / f"k{k:02d}" / f"ep{i:03d}.json.gz"


# -- game ------------------------------------------------------------------------------------------------------------


def launch(work: Path, rank: int, index: int):
    from battleship_process import BattleShipEpisode, LaunchConfig
    from m7_runtime import PortCandidates, prepare_worker_runtime

    work = Path(work).resolve()
    shutil.rmtree(work / "runtime", ignore_errors=True)
    prepare_worker_runtime(work / "runtime", EXECUTABLE)
    port, _busy = PortCandidates(rank).claim()
    (work / "episodes").mkdir(parents=True, exist_ok=True)
    cfg = LaunchConfig(executable=EXECUTABLE, working_dir=work / "runtime", run_root=work / "episodes", port=port,
                       startup_timeout=30.0, ready_timeout=90.0, request_timeout=15.0, exit_timeout=30.0, extra_env=dict(FLAGS))
    return BattleShipEpisode(cfg, index=index)


def cleanup(work: Path) -> None:
    from m7k_target2 import remove_runtime_with_retry

    remove_runtime_with_retry(Path(work) / "runtime")
    shutil.rmtree(Path(work) / "episodes", ignore_errors=True)


def stage(initial: Dict[str, Any], steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    """S1-S5 (M7n prefix-feasibility staging at cut 0) plus the probe's own counts, from raw replies only."""
    import m7g_fixture as fx
    import m7n_crossing as xc
    import m7n_prefix_feasibility as pf

    s = pf.staging(initial, steps, 0)
    live = [r["observation"] for r in steps if xc._live(r.get("observation") or {})]
    ys = [float(o["position_y"]) for o in live]
    xs = [float(o["position_x"]) for o in live]
    ev = fx.crossing_evidence(xc.geometry(), initial, steps)
    breaks = sorted((int(b["target_id"]), int(b["consumed_tick"])) for b in ((ev.get("targets") or {}).get("breaks") or []))
    return {"S1_approach": bool(s["S1_approach"]), "S1_first_tick": s["S1_first_tick"],
            "S2_over_ledge": bool(s["S2_over_ledge"]), "S2_first": s["S2_first"],
            "S3_over_wall_entry": bool(s["S3_over_wall_entry"]), "S3_entries": s["S3_entries"],
            "S4_qualified_crossing": bool(s["S4_qualified_any"]), "S5_left_target_breaks": s["S5_left_target_breaks"],
            "entries": s["entries_after_cut"], "route": s["route"], "terminal": s["terminal"], "fall_tick": s["fall_tick"],
            "min_live_x": min(xs) if xs else None, "max_live_y": max(ys) if ys else None,
            "elevated_steps": sum(1 for y in ys if y >= ELEVATED_Y), "live_steps": len(live),
            "breaks": breaks, "targets_broken": len(breaks)}


def run_episode(job: Dict[str, Any]) -> Dict[str, Any]:
    import numpy as np

    import m7f_trace as tr
    import m7h_curriculum as mc
    from battleship_client import StepState
    from btt_learning import live_targets
    from btt_parallel import is_native_failure
    from btt_rewards import REWARD_V2, reward_step

    k, i, seed = int(job["k"]), int(job["i"]), int(job["seed"])
    work = OUT / "work" / f"k{k:02d}_ep{i:03d}"
    rng = np.random.default_rng(seed)
    replies: List[Dict[str, Any]] = []
    rows: List[Tuple[int, int, int, int]] = []
    decisions: List[Tuple[int, int, int]] = []     # (track1 index, first tick, realised hold length)
    terms = {"target_term": 0.0, "step_term": 0.0, "clear_term": 0.0, "failure_term": 0.0}
    t0 = time.perf_counter()
    end: Optional[str] = None
    exit_code = None
    contract_violations: List[str] = []
    ep = launch(work, int(job["rank"]), int(job["index"]))
    with ep:
        ep.start()
        client = ep.client
        tr._capture_requests(client, replies)
        client.request("status")
        initial = client.request("observe")
        o0 = initial["observation"]
        if int(o0["input_tick"]) != 0 or int(o0["targets_remaining"]) != 10 or int(initial.get("step_count", 0)) != 0:
            raise RuntimeError(f"reset observation input_tick {o0['input_tick']} targets {o0['targets_remaining']}")
        prev_targets = live_targets(o0)
        steps: List[Dict[str, Any]] = []
        t = 0
        finished = False
        while t < HORIZON and not finished:
            a = int(rng.integers(0, TRACK1_COMBINATIONS))
            stick, button = divmod(a, 8)
            b, x, y = mc.track1_triple(mc.encode_track1(stick, button))
            hold = min(k, HORIZON - t)
            realised = 0
            first = t
            for _ in range(hold):
                r = client.step(b, x, y)
                rep = replies[-1]
                if r.consumed_tick != t:
                    raise RuntimeError(f"tick {t}: consumed_tick {r.consumed_tick}")
                o = rep["observation"]
                if int(o["input_tick"]) != t + 1:
                    contract_violations.append(f"tick {t}: input_tick {o['input_tick']}")
                steps.append(rep)
                rows.append((b, x, y, int(r.consumed_tick)))
                realised += 1
                ended = r.state == StepState.EPISODE_ENDED
                failure = is_native_failure(r.observation, r.state)
                clear = ended and int(o["btt_active"]) == 1 and int(o["targets_remaining"]) == 0
                cur = live_targets(o)
                rt = reward_step(prev_targets, cur, clear=clear, native_failure=failure, contract=REWARD_V2)
                prev_targets = cur
                for key in terms:
                    terms[key] += getattr(rt, key)
                t += 1
                if ended or failure:
                    end = "clear" if clear else ("fall" if failure else "ended_not_clear")
                    if ended:
                        done = ep.finish(r)
                        exit_code = done.exit_code
                    finished = True
                    break
            decisions.append((a, first, realised))
        if end is None:
            end = "horizon"
    if contract_violations:
        raise RuntimeError(f"recording contract violated: {contract_violations[:3]}")
    st = stage(initial, steps)
    holds = [d[2] for d in decisions]
    rec = {"k": k, "i": i, "seed": seed, "index": int(job["index"]), "end": end, "exit_code": exit_code,
           "ticks": len(rows), "decisions": len(decisions), "hold_full": sum(1 for h in holds if h == k),
           "hold_short": sum(1 for h in holds if h < k), "wall_s": round(time.perf_counter() - t0, 2),
           "native_action_digest": mc.native_digest(rows),
           "reward_v2": {key: round(v, 4) for key, v in terms.items()}, "return_v2": round(sum(terms.values()), 4),
           "stage": st}
    p = episode_path(k, i)
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wt", encoding="utf-8") as fp:
        json.dump({"record": rec, "rows": rows, "decisions": decisions, "initial": initial, "steps": steps}, fp)
    rec["episode_file"] = str(p.relative_to(REPO_ROOT)).replace("\\", "/")
    rec["episode_file_sha256"] = sha256_file(p)
    cleanup(work)
    return rec


_RANK = 0


def _init(counter: Any) -> None:
    global _RANK
    with counter.get_lock():
        counter.value += 1
        _RANK = int(counter.value)
    from m7_runtime import install_kill_on_close_job

    install_kill_on_close_job()


def _job(job: Dict[str, Any]) -> Dict[str, Any]:
    return run_episode(dict(job, rank=_RANK))


# -- commands --------------------------------------------------------------------------------------------------------


def cmd_register(_: argparse.Namespace) -> int:
    if not EXECUTABLE.is_file():
        raise SystemExit(f"missing executable {EXECUTABLE}")
    doc = {
        "schema": "action_hold_probe_registration_v1",
        "utc": utc_now(),
        "question": "Can uniformly random Track 1 actions, each held for k native ticks, reach the region the Mario BTT crossing needs "
                    "from a normal tick-0 start, where per-tick random actions (k = 1) do not?",
        "status_of_the_hypothesis": "action persistence is a HYPOTHESIS about the zero first-event rate of the trained policies "
                                    "(docs/rl_learning_setup_review_2026-09-27.md, section 4); this probe tests random reachability only",
        "no_training": True, "no_policy": True, "no_production_contract_change": True,
        "conditions": {"hold_lengths": list(HOLDS), "episodes_per_k": EPISODES_PER_K, "horizon_ticks": HORIZON,
                       "start": "normal tick-0 reset of a fresh process (non-consuming observe, input_tick 0, 10 targets), no prefix"},
        "sampling": {"space": "the 72 Track 1 combinations of btt_s9_b8_v1 (9 stick states x 8 button states)",
                     "rule": "at each decision boundary a = numpy.random.default_rng(seed).integers(0, 72); stick = a // 8, button = a % 8; "
                             "the native triple is btt_learning TRACK1_STICK_TABLE[stick], TRACK1_BUTTON_TABLE[button]",
                     "seed": "sha256('action_hold|<k>|<i>')[:8] as an integer, one generator per episode; Python-side only, never reaches the game"},
        "hold_semantics": {"hold": "the same native triple is submitted for up to k consecutive ticks",
                           "stop": "immediately on a native EpisodeEnded result or a btt_native_failure_v1 detection (no further ticks)",
                           "clip": "the last hold is min(k, 3600 - t) so no tick beyond the horizon is submitted",
                           "recording": "every native tick is one `step` request; consumed_tick must equal t and the reply's input_tick t + 1; "
                                        "every reply is kept (raw, gz) and the canonical native rows (buttons, stick_x, stick_y, consumed_tick) "
                                        "give the M7 native_action_digest; no hidden steps, no ignored termination, no altered button edges"},
        "stages": STAGES,
        "rule": RULE,
        "metrics_per_condition": ["episodes", "end reasons (clear / fall / horizon)", "targets broken (mean, histogram)", "falls",
                                  "max live y (max, median), min live x (min)", "elevated-step episodes and steps", "S1 approach episodes",
                                  "S2 over-ledge episodes", "S3 raw over-wall entries", "S4 qualified crossings", "S5 left-target breaks",
                                  "mean reward v2 return", "decisions per episode, realised hold lengths", "wall time"],
        "historical_k1_baseline": {
            "record": "runs/m7g_k/_eval/random_baseline (100 episodes, uniform per-tick Track 1, seed 12345, 5 workers)",
            "reused": False,
            "why_not": ["its extra_env lacks SSB64_RL_SPATIAL / SSB64_RL_ENTITY (only NO_RENDER, RAPHNET_DISABLE, TARGET_DIAG)",
                        "no raw replies preserved (actions.jsonl + metadata + btt_eval_metrics_v1 only)",
                        "no height recorded, so S2 / elevated steps cannot be computed from it",
                        "its sampling used SB3's evaluation RNG, not the registered per-episode generators"],
            "use": "reported alongside as descriptive context only (3.23 targets, 30 falls, min live x -1650, 0 left entries)"},
        "executable": {"path": "build-us/Release/BattleShip.exe", "sha256": sha256_file(EXECUTABLE), "size": EXECUTABLE.stat().st_size},
        "flags": FLAGS,
        "code": {"tool": "rl/tools/action_hold_probe.py", "sha256": sha256_file(Path(__file__)),
                 "reused": {"rl/tools/m7n_prefix_feasibility.py": sha256_file(TOOLS_DIR / "m7n_prefix_feasibility.py"),
                            "rl/m7n_crossing.py": sha256_file(RL_DIR / "m7n_crossing.py"),
                            "rl/m7g_fixture.py": sha256_file(RL_DIR / "m7g_fixture.py"),
                            "rl/m7f_trace.py": sha256_file(RL_DIR / "m7f_trace.py"),
                            "rl/btt_reward_v3.py": sha256_file(RL_DIR / "btt_reward_v3.py")}},
        "exclusions": ["the two validated crossing fixtures and the 7.43 TAS are not read, replayed or used to construct the probe",
                       "no native RNG inspection, logging, control or hashing", "no PPO, no policy, no reward change, no network change"],
        "stop_conditions": ["any episode raising (integrity, transport, consumed-tick or recording-contract violation): the pool is "
                            "cancelled and the run exits 1", "a BattleShip process already running before launch", "the M7h launch gate "
                            "refusing", "a leftover BattleShip process after the run"],
        "resources": {"workers": 3, "expected_game_processes": "<= 3", "output_root": "runs/probes/action_hold"},
        "episodes": episode_list(),
    }
    write_once(REG_DOC, doc)
    log(f"registered {len(doc['episodes'])} episodes -> {REG_DOC.relative_to(REPO_ROOT)} (sha256 {sha256_file(REG_DOC)[:12]})")
    return 0


def _check_registration() -> Dict[str, Any]:
    reg = read_json(REG_DOC)
    if reg["executable"]["sha256"] != sha256_file(EXECUTABLE):
        raise SystemExit("executable differs from the registered one")
    if reg["code"]["sha256"] != sha256_file(Path(__file__)):
        raise SystemExit("this tool differs from the registered one; re-register (write-once) before running")
    return reg


def cmd_run(args: argparse.Namespace) -> int:
    import m7h_guard as g
    from m7_runtime import BATTLESHIP_IMAGE, install_kill_on_close_job, list_processes_named, wait_until_no_process

    install_kill_on_close_job()
    reg = _check_registration()
    if list_processes_named():
        raise SystemExit("BattleShip already running")
    gate = g.launch_gate()
    if not gate["ok"]:
        raise SystemExit(f"launch gate refused: {gate['problems']}")
    results_path = OUT / "results.jsonl"
    done = set()
    if results_path.is_file():
        for line in results_path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            done.add((r["k"], r["i"]))
    jobs = [e for e in reg["episodes"] if (e["k"], e["i"]) not in done]
    log(f"{len(jobs)} episode(s) to run ({len(done)} done); workers {args.workers}")
    attempts_path = OUT / "run_attempts.jsonl"
    OUT.mkdir(parents=True, exist_ok=True)
    with open(attempts_path, "a", encoding="utf-8") as fp:
        fp.write(json.dumps({"utc": utc_now(), "jobs": len(jobs), "done_before": len(done), "launch_gate": gate}) + "\n")
    ctx = multiprocessing.get_context("spawn")
    counter = ctx.Value("i", 0)
    failures: List[Dict[str, Any]] = []
    t0 = time.perf_counter()
    ex = ProcessPoolExecutor(max_workers=int(args.workers), mp_context=ctx, initializer=_init, initargs=(counter,))
    try:
        futs = {ex.submit(_job, j): j for j in jobs}
        for n, fut in enumerate(as_completed(futs), 1):
            j = futs[fut]
            try:
                r = fut.result()
            except Exception as exc:  # noqa: BLE001 - recorded; stops the run
                failures.append({"job": {k: j[k] for k in ("k", "i", "seed")}, "error": f"{type(exc).__name__}: {exc}"})
                log(f"FAILED k{j['k']} ep{j['i']}: {type(exc).__name__}: {exc} -> cancelling the run")
                break
            with open(results_path, "a", encoding="utf-8") as fp:
                fp.write(json.dumps(r) + "\n")
            s = r["stage"]
            log(f"{n}/{len(jobs)} k{r['k']:02d} ep{r['i']:03d}: {r['end']} targets {s['targets_broken']} maxy {s['max_live_y']:.0f} "
                f"minx {s['min_live_x']:.0f} elev {s['elevated_steps']} S1 {int(s['S1_approach'])} S2 {int(s['S2_over_ledge'])} "
                f"S3 {int(s['S3_over_wall_entry'])} S4 {int(s['S4_qualified_crossing'])} S5 {len(s['S5_left_target_breaks'])} {r['wall_s']:.0f}s")
    finally:
        ex.shutdown(wait=True, cancel_futures=True)
    leftover = wait_until_no_process(BATTLESHIP_IMAGE, timeout=30.0)
    summary = {"utc": utc_now(), "jobs": len(jobs), "completed": len(jobs) - len(failures) if not failures else None,
               "failures": failures, "leftover_pids": leftover, "wall_s": round(time.perf_counter() - t0, 1), "launch_gate": gate}
    with open(attempts_path, "a", encoding="utf-8") as fp:
        fp.write(json.dumps(summary) + "\n")
    log(f"done in {(time.perf_counter() - t0) / 60:.1f} min; failures {len(failures)}; leftover {leftover}")
    return 0 if not failures and not leftover else 1


def _results() -> List[Dict[str, Any]]:
    p = OUT / "results.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()] if p.is_file() else []


def meets_threshold(rec: Dict[str, Any]) -> bool:
    s = rec["stage"]
    return bool(s["S2_over_ledge"]) or bool(s["S3_over_wall_entry"])


def cmd_replay(_: argparse.Namespace) -> int:
    import m7f_trace as tr
    import m7h_curriculum as mc
    from m7_runtime import BATTLESHIP_IMAGE, install_kill_on_close_job, list_processes_named, wait_until_no_process

    install_kill_on_close_job()
    _check_registration()
    if list_processes_named():
        raise SystemExit("BattleShip already running")
    rs = [r for r in _results() if meets_threshold(r)]
    out = OUT / "replays"
    out.mkdir(parents=True, exist_ok=True)
    verdicts = []
    for n, r in enumerate(rs, 1):
        p = REPO_ROOT / r["episode_file"]
        if sha256_file(p) != r["episode_file_sha256"]:
            raise SystemExit(f"{p} changed since it was recorded")
        doc = json.load(gzip.open(p, "rt", encoding="utf-8"))
        rows = [tuple(x) for x in doc["rows"]]
        work = out / "work" / f"k{r['k']:02d}_ep{r['i']:03d}"
        trace = tr.run_stepping_trace(f"hold_probe_replay_k{r['k']}_ep{r['i']}", EXECUTABLE, rows, work, extra_env=FLAGS,
                                      index=9500 + n, rank=0)
        rep_rows = [(b, x, y, int(s["consumed_tick"])) for (b, x, y, _t), s in zip(rows, trace["steps"])]
        exact = (trace["consumed_tick_mismatch"] is None and trace["unsent"] == 0
                 and mc.native_digest(rep_rows) == r["native_action_digest"])
        st = stage(trace["initial"], trace["steps"])
        same = {key: st[key] == r["stage"][key] for key in ("S1_approach", "S2_over_ledge", "S3_over_wall_entry",
                                                             "S4_qualified_crossing", "S5_left_target_breaks", "breaks")}
        v = {"k": r["k"], "i": r["i"], "exact": exact, "consumed_tick_mismatch": trace["consumed_tick_mismatch"], "unsent": trace["unsent"],
             "replay_end": trace["final_state"], "stage_replay": st, "stage_equal": same, "reproduced": exact and all(same.values()),
             "classification": {"raw_over_wall_entry": bool(st["S3_over_wall_entry"]), "over_ledge": bool(st["S2_over_ledge"]),
                                "qualified_crossing": bool(st["S4_qualified_crossing"]), "left_target_breaks": st["S5_left_target_breaks"],
                                "terminal": st["terminal"], "fall_tick": st["fall_tick"], "entries": st["entries"], "route": st["route"]}}
        verdicts.append(v)
        with gzip.open(out / f"k{r['k']:02d}_ep{r['i']:03d}.json.gz", "wt", encoding="utf-8") as fp:
            json.dump({"verdict": v, "trace_steps": trace["steps"], "initial": trace["initial"]}, fp)
        from m7k_target2 import remove_runtime_with_retry
        remove_runtime_with_retry(work / "runtime")
        shutil.rmtree(work / "episodes", ignore_errors=True)
        log(f"{n}/{len(rs)} k{r['k']} ep{r['i']}: exact {exact} reproduced {v['reproduced']} {v['classification']}")
    leftover = wait_until_no_process(BATTLESHIP_IMAGE, timeout=30.0)
    write_json(out / "verdicts.json", {"utc": utc_now(), "candidates": len(rs), "verdicts": verdicts, "leftover_pids": leftover})
    log(f"replayed {len(rs)} candidate(s); leftover {leftover}")
    return 0 if not leftover else 1


def cmd_summarize(_: argparse.Namespace) -> int:
    import statistics as stt

    reg = _check_registration()
    rs = _results()
    verd = read_json(OUT / "replays" / "verdicts.json") if (OUT / "replays" / "verdicts.json").is_file() else {"verdicts": []}
    vmap = {(v["k"], v["i"]): v for v in verd["verdicts"]}
    per = []
    for k in HOLDS:
        grp = [r for r in rs if r["k"] == k]
        st = [r["stage"] for r in grp]
        cand = [r for r in grp if meets_threshold(r)]
        reproduced = [r for r in cand if vmap.get((r["k"], r["i"]), {}).get("reproduced")]
        tg = [s["targets_broken"] for s in st]
        row = {"k": k, "n": len(grp), "complete": len(grp) == EPISODES_PER_K,
               "end": {e: sum(1 for r in grp if r["end"] == e) for e in ("clear", "fall", "horizon", "ended_not_clear")},
               "targets_mean": round(stt.fmean(tg), 3) if tg else None,
               "targets_hist": {str(v): tg.count(v) for v in range(11)} if tg else None,
               "max_live_y_max": max((s["max_live_y"] for s in st if s["max_live_y"] is not None), default=None),
               "max_live_y_median": stt.median(s["max_live_y"] for s in st) if st else None,
               "min_live_x_min": min((s["min_live_x"] for s in st if s["min_live_x"] is not None), default=None),
               "elevated_episodes": sum(1 for s in st if s["elevated_steps"] > 0), "elevated_steps": sum(s["elevated_steps"] for s in st),
               "S1": sum(1 for s in st if s["S1_approach"]), "S2": sum(1 for s in st if s["S2_over_ledge"]),
               "S3": sum(1 for s in st if s["S3_over_wall_entry"]), "S4": sum(1 for s in st if s["S4_qualified_crossing"]),
               "S5": sum(1 for s in st if s["S5_left_target_breaks"]),
               "candidates": len(cand), "candidates_reproduced": len(reproduced),
               "S2_reproduced": sum(1 for r in reproduced if r["stage"]["S2_over_ledge"]),
               "S3_reproduced": sum(1 for r in reproduced if r["stage"]["S3_over_wall_entry"]),
               "mean_return_v2": round(stt.fmean(r["return_v2"] for r in grp), 3) if grp else None,
               "decisions_mean": round(stt.fmean(r["decisions"] for r in grp), 1) if grp else None,
               "hold_short_total": sum(r["hold_short"] for r in grp), "wall_s": round(sum(r["wall_s"] for r in grp), 1)}
        row["meets_threshold"] = row["S2_reproduced"] >= S2_THRESHOLD or row["S3_reproduced"] >= S3_THRESHOLD
        per.append(row)
    complete = all(r["complete"] for r in per)
    unverified = [r for r in rs if meets_threshold(r) and (r["k"], r["i"]) not in vmap]
    if unverified:
        outcome = "INCOMPLETE (candidates not yet replayed)"
    elif not complete:
        outcome = "INCOMPLETE"
    else:
        longer = [r["k"] for r in per if r["k"] > 1 and r["meets_threshold"]]
        if longer:
            outcome = ("REACHABLE under hold k in " + str(longer) + ": temporally correlated random actions can reach the relevant "
                       "region under this probe (exploration reachability only; not a qualified crossing, not a learned success, "
                       "not evidence that PPO will learn a crossing)")
        else:
            outcome = ("NO FOOTHOLD under the tested hold lengths (Track 1 crossing controllability is established by the validated "
                       "fixtures and is not what this probe tests)")
    doc = {"utc": utc_now(), "registration_sha256": sha256_file(REG_DOC), "rule": reg["rule"], "per_k": per,
           "k1_meets_threshold": next(r["meets_threshold"] for r in per if r["k"] == 1) if complete else None,
           "outcome": outcome, "unverified_candidates": len(unverified)}
    write_json(OUT / "summary.json", doc)
    print("| k | n | clear / fall / horizon | targets mean | max y (max / median) | min x | elevated eps (steps) | S1 | S2 | S3 | S4 | S5 | candidates (reproduced) | mean v2 return | decisions | meets threshold |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in per:
        e = r["end"]
        print(f"| {r['k']} | {r['n']} | {e['clear']} / {e['fall']} / {e['horizon']} | {r['targets_mean']} | "
              f"{r['max_live_y_max']:.0f} / {r['max_live_y_median']:.0f} | {r['min_live_x_min']:.0f} | {r['elevated_episodes']} ({r['elevated_steps']}) | "
              f"{r['S1']} | {r['S2']} | {r['S3']} | {r['S4']} | {r['S5']} | {r['candidates']} ({r['candidates_reproduced']}) | "
              f"{r['mean_return_v2']} | {r['decisions_mean']} | {r['meets_threshold']} |")
    print("outcome:", outcome)
    if complete and not unverified and not DECISION_DOC.exists():
        write_once(DECISION_DOC, doc)
        log(f"decision written once -> {DECISION_DOC.relative_to(REPO_ROOT)}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["register", "run", "replay", "summarize"])
    ap.add_argument("--workers", default=3)
    args = ap.parse_args(argv)
    return {"register": cmd_register, "run": cmd_run, "replay": cmd_replay, "summarize": cmd_summarize}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
