#!/usr/bin/env python3
"""M7o offline assessment tools (outside the fingerprinted set; read-only towards frozen evidence).

    python rl/tools/m7o_offline.py register-replays   # the bounded replay list: m7n_s0_v3 initial + final stochastic labels
    python rl/tools/m7o_offline.py replay [--workers 3] # exact fresh-process replays, compact rows kept (t,x,y,ga,status,vx,vy,jumps,live)
    python rl/tools/m7o_offline.py status
    python rl/tools/m7o_offline.py simulate      # exact worker-slot simulation with the production module
    python rl/tools/m7o_offline.py variants      # fixture-free variant comparison on policy-generated traces

Purpose: policy-generated v3 tick-0 trajectories of an untrained policy (ckpt_000000000, 100 episodes) and of the
trained final (100 episodes) of one seed, for the exact worker-slot simulation of the exploration credit. Evaluation
flags of the run + the target diagnostic; native gameplay authoritative; no training, no new evaluation.
"""
from __future__ import annotations

import argparse
import gzip
import json
import multiprocessing
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

RL_DIR = Path(__file__).resolve().parents[1]
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import experiment_config as ec  # noqa: E402
import m7n_crossing as xc  # noqa: E402
import m7n_matrix as nm  # noqa: E402

REPO_ROOT = RL_DIR.parent
OUT = REPO_ROOT / "runs" / "m7o" / "offline"
REGISTRY = REPO_ROOT / "docs" / "rl_exploration_credit_m7o_replays.json"
LABELS = (("m7n_s0_v3", "initial"), ("m7n_s0_v3", "final"))


def write_json(p: Path, d: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=1, default=str) + "\n", encoding="utf-8")


def read_json(p: Path) -> Any:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def log(msg: str) -> None:
    print(f"[m7o_offline {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def cmd_register(_: argparse.Namespace) -> int:
    if REGISTRY.is_file():
        print(f"refused: {ec.repo_relative(REGISTRY)} exists")
        return 2
    spec = nm.matrix()[0]
    exp = nm.load_run(spec)
    items = []
    for run, label in LABELS:
        ev = read_json(spec.eval_dir / label / "stochastic" / "evaluation.json")
        for e in sorted(ev["episodes"], key=lambda x: x.get("order", 0)):
            em = e.get("eval_metrics") or {}
            items.append({"run": run, "label": label, "order": e.get("order"), "episode_id": e["episode_id"], "artifact_dir": e["artifact_dir"],
                          "native_action_digest": e["native_action_digest"], "end_reason": e["end_reason"], "length": e["length"],
                          "targets_broken": e["targets_broken"],
                          "recorded_breaks": [[int(b["target_id"]), int(b["consumed_tick"])] for b in em.get("target_breaks") or []]})
    reg = {"schema": "m7o_offline_replays_v1", "utc": xc.utc_now(), "purpose": "policy-generated v3 tick-0 trajectories (untrained and "
           "trained) for the offline exploration-credit simulation; diagnostic only; no training, no new evaluation",
           "executable_sha256": xc.sha256_file(exp.executable), "flags": dict(exp.extra_env, **nm.DIAG_FLAG),
           "exactness": "consumed ticks, all actions, native action digest, break table", "episodes": items}
    write_json(REGISTRY, reg)
    log(f"registered {len(items)} episodes -> {ec.repo_relative(REGISTRY)}")
    return 0


_RANK = 0


def _init(counter: Any) -> None:
    global _RANK
    with counter.get_lock():
        counter.value += 1
        _RANK = int(counter.value)
    from m7_runtime import install_kill_on_close_job

    install_kill_on_close_job()


def _replay(job: Dict[str, Any]) -> Dict[str, Any]:
    import m7f_trace as tr
    from m7k_target2 import remove_runtime_with_retry

    art = REPO_ROOT / job["artifact_dir"]
    acts, _meta = tr.artifact_actions(art)
    work = OUT / "replays" / "work" / f"{job['label']}_{job['order']:03d}"
    t0 = time.perf_counter()
    trace = tr.run_stepping_trace(f"m7o_{job['label']}_{job['order']}", Path(job["executable"]), acts, work, extra_env=dict(job["flags"]),
                                  index=8000 + int(job["index"]), rank=_RANK)
    steps = trace["steps"]
    ev = xc.fx.crossing_evidence(xc.geometry(), trace["initial"], steps)
    breaks = [[int(b["target_id"]), int(b["consumed_tick"])] for b in ev["targets"]["breaks"]]
    exact = {"consumed_tick_mismatch": trace["consumed_tick_mismatch"], "unsent": trace["unsent"],
             "digest_equal": trace["action_digest"] == job["native_action_digest"], "breaks_equal": breaks == job["recorded_breaks"]}
    exact["ok"] = exact["consumed_tick_mismatch"] is None and exact["unsent"] == 0 and exact["digest_equal"] and exact["breaks_equal"]
    rows = []
    for s in steps:
        o = s.get("observation") or {}
        live = int(o.get("fighter_valid", 0)) == 1 and int(o.get("btt_active", 0)) == 1
        rows.append([s.get("consumed_tick"), o.get("position_x"), o.get("position_y"), o.get("ground_air_state"), o.get("fighter_status_id"),
                     o.get("air_velocity_x"), o.get("air_velocity_y"), o.get("jumps_used"), int(live)])
    i0 = trace["initial"]["observation"]
    last = steps[-1]
    fall = xc.fx.is_fall(last)
    doc = {"episode_id": job["episode_id"], "label": job["label"], "order": job["order"], "exact": exact, "fall": fall,
           "end": "clear" if last.get("state") == xc.fx.STEP_STATE_EPISODE_ENDED else ("fall" if fall else "horizon"),
           "map_bounds": trace["initial"].get("spatial", {}).get("map_bounds"), "initial": [i0.get("position_x"), i0.get("position_y")],
           "fields": ["t", "x", "y", "ga", "status", "vx", "vy", "jumps", "live"], "rows": rows, "breaks": breaks,
           "wall_s": round(time.perf_counter() - t0, 2)}
    out = OUT / "replays" / "traces" / f"{job['label']}_{job['order']:03d}.json.gz"
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8") as fp:
        json.dump(doc, fp)
    remove_runtime_with_retry(work / "runtime")
    return {k: doc[k] for k in ("episode_id", "label", "order", "exact", "end", "wall_s")}


def cmd_replay(args: argparse.Namespace) -> int:
    from m7_runtime import BATTLESHIP_IMAGE, install_kill_on_close_job, list_processes_named, wait_until_no_process

    install_kill_on_close_job()
    reg = read_json(REGISTRY)
    exe = nm.load_run(nm.matrix()[0]).executable
    if xc.sha256_file(exe) != reg["executable_sha256"]:
        print("executable differs from the registered one")
        return 2
    if list_processes_named():
        print("BattleShip already running")
        return 2
    done = {p.name[:-8] for p in (OUT / "replays" / "traces").glob("*.json.gz")} if (OUT / "replays" / "traces").is_dir() else set()
    jobs = [dict(e, executable=str(exe), flags=reg["flags"], index=i) for i, e in enumerate(reg["episodes"])
            if f"{e['label']}_{e['order']:03d}" not in done]
    log(f"{len(jobs)} replay(s) to run ({len(done)} done)")
    ctx = multiprocessing.get_context("spawn")
    counter = ctx.Value("i", 0)
    results, failures = [], []
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=int(args.workers), mp_context=ctx, initializer=_init, initargs=(counter,)) as ex:
        futs = {ex.submit(_replay, j): j for j in jobs}
        for n, fut in enumerate(as_completed(futs), 1):
            j = futs[fut]
            try:
                r = fut.result()
                results.append(r)
                if not r["exact"]["ok"]:
                    failures.append(r)
                if n % 20 == 0 or n == len(futs):
                    log(f"{n}/{len(futs)} replays, {len(failures)} inexact, {time.perf_counter() - t0:.0f} s")
            except Exception as exc:  # noqa: BLE001
                failures.append({"job": {k: j[k] for k in ("label", "order")}, "error": f"{type(exc).__name__}: {exc}"})
                log(f"FAILED {j['label']} {j['order']}: {type(exc).__name__}: {exc}")
    leftover = wait_until_no_process(BATTLESHIP_IMAGE, timeout=30.0)
    write_json(OUT / "replays" / "summary.json", {"utc": xc.utc_now(), "registry_sha256": xc.sha256_file(REGISTRY), "ran": len(results),
                                                  "failures": failures, "leftover_pids": leftover, "wall_s": round(time.perf_counter() - t0, 1)})
    log(f"done: {len(results)} ran, {len(failures)} failure(s), leftover {leftover}")
    return 0 if not failures and not leftover else 1



# -- exact worker-slot simulation (production accounting) ----------------------------------------------------------------

import gzip as _gzip
import math as _math
import random as _random
import statistics as _stt
from collections import Counter as _Counter

import btt_explore_cells as xp  # noqa: E402
import m7n_status_table as _st  # noqa: E402

M7N_S0_ROWS = REPO_ROOT / "runs" / "m7n" / "campaign" / "m7n_s0_v3" / "metrics" / "episodes.jsonl"
JUMPS_MAX = 2          # Mario (entity diagnostic jumps_max on every replayed step); stated assumption for the variants


def _traces(label: str):
    out = []
    for p in sorted((OUT / "replays" / "traces").glob(f"{label}_*.json.gz")):
        with _gzip.open(p, "rt", encoding="utf-8") as fp:
            out.append(json.load(fp))
    return out


def _run_episode(trace, table, cls):
    """The production module over one replayed trace: returns (record, per-step credits by cell)."""
    x0, y0 = trace["initial"]
    reset = {"fighter_valid": 1, "btt_active": 1, "position_x": x0, "position_y": y0, "ground_air_state": 0}
    ep = xp.ExploreEpisode.start(reset, trace["map_bounds"], table)
    rows = trace["rows"]
    n = len(rows)
    for i, r in enumerate(rows):
        t, x, y, ga, status, vx, vy, jumps, live = r
        obs = {"fighter_valid": int(live), "btt_active": int(live), "position_x": x, "position_y": y, "ground_air_state": ga}
        last = i == n - 1
        ep.step(obs, cls.name(int(status)) if live else "unmapped", consumed_tick=t, native_failure=bool(trace["fall"] and last),
                episode_end=last)
    # credited CELLS (the record keeps up to 64 banked events; an episode banks at most cap / (beta * w) of them)
    events = [(e["tick"], (e["cell"][0] + 0.5) * ep.size, (e["cell"][1] + 0.5) * ep.size, e["amount"]) for e in ep.events]
    rec = ep.record()
    rec["_events_truncated"] = rec["cells_credited"] > len(ep.events)
    return rec, events


def _slot_orders():
    rows = [json.loads(l) for l in M7N_S0_ROWS.read_text(encoding="utf-8").splitlines()]
    by = {}
    for r in sorted(rows, key=lambda r: (int(r["rank"]), int(r["worker_episode"]))):
        by.setdefault(int(r["rank"]), []).append(r["worker_episode"])
    return {k: len(v) for k, v in by.items()}


def cmd_simulate(_: argparse.Namespace) -> int:
    U, T = _traces("initial"), _traces("final")
    if len(U) != 100 or len(T) != 100:
        print(f"need 100 + 100 replays, have {len(U)} + {len(T)}")
        return 2
    cls = _st.ActionClassifier(_st.load_table(), "mario")
    slots = _slot_orders()
    report = {"utc": xc.utc_now(), "slots": slots, "pools": {"untrained": len(U), "trained": len(T)},
              "assumption": "each slot's k-th episode takes a trajectory drawn (seeded, with replacement) from the untrained pool "
                            "(ckpt_000000000 of m7n_s0_v3) or the trained pool (its final); scenarios: all untrained, all trained, "
                            "linear crossover; not a learning model", "scenarios": {}}
    F = []
    for p_ in sorted((REPO_ROOT / "runs" / "m7n" / "feasibility" / "prefix" / "foothold" / "work").glob("*/episode.json.gz")):
        with _gzip.open(p_, "rt", encoding="utf-8") as fp:
            g_ = json.load(fp)
        rows_ = [[r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], int(r[1] is not None)] for r in g_["trajectory_after_cut"]]
        if rows_ and rows_[0][1] is not None:
            F.append({"rows": rows_, "fall": g_["end"] == "fall", "initial": [rows_[0][1], rows_[0][2]], "map_bounds": [9600, -9600, 9600, -9600],
                      "breaks": []})
    report["pools"]["foothold_post_cut_elevated_stand_in"] = len(F)
    report["assumption"] += "; 'mixed_elevated' = untrained pool for the first third of each slot, then the 225 M7n foothold post-cut "                             "segments (seeds 1-2 policies after their sweeps; partial episodes) as a stand-in for elevated behaviour"
    for scenario in ("untrained", "trained", "mixed", "mixed_elevated"):
        per_slot = {}
        pooled_first, pooled_mid, pooled_last, pooled_all = [], [], [], []
        high_credit_by_phase = {"first": 0.0, "mid": 0.0, "last": 0.0}
        highleft_credit_by_phase = {"first": 0.0, "mid": 0.0, "last": 0.0}
        v2_targets = 0
        voided_falls = 0.0
        cap_hits = 0
        first_high_w = []
        for rank, K in sorted(slots.items()):
            rng = _random.Random(1000 + rank)
            table = xp.ExploreTable(rank=rank)
            seq = []
            for k in range(K):
                f = k / max(1, K - 1)
                if scenario == "mixed_elevated":
                    pool = U if k < K // 3 else F
                else:
                    pool = U if scenario == "untrained" else T if scenario == "trained" else (U if rng.random() < 1.0 - f else T)
                tr = pool[rng.randrange(len(pool))]
                rec, events = _run_episode(tr, table, cls)
                seq.append(rec["bonus"])
                v2_targets += len(tr["breaks"])
                if rec["ended"] == "native_failure":
                    voided_falls += rec["voided"]
                cap_hits += int(rec["cap_hit"])
                report.setdefault("events_truncated_episodes", 0)
                report["events_truncated_episodes"] += int(rec["_events_truncated"])
                phase = "first" if k < K // 4 else "last" if k >= K - K // 4 else "mid"
                for (t, x, y, amt) in events:
                    if y >= 2400:
                        high_credit_by_phase[phase] += amt
                        if x < 0:
                            highleft_credit_by_phase[phase] += amt
                        if phase == "last":
                            first_high_w.append(amt / xp.BETA)
            q = K // 4
            per_slot[rank] = {"episodes": K, "first_quarter_mean": round(_stt.mean(seq[:q]), 4), "mid_mean": round(_stt.mean(seq[q:K - q]), 4),
                              "last_quarter_mean": round(_stt.mean(seq[-q:]), 4), "total": round(sum(seq), 3), "table_cells": len(table.counts),
                              "cells_seen_by_ge_10": sum(1 for n in table.counts.values() if n >= 10)}
            pooled_first += seq[:q]; pooled_mid += seq[q:K - q]; pooled_last += seq[-q:]; pooled_all += seq
        report["scenarios"][scenario] = {
            "per_slot": per_slot,
            "pooled": {"first_quarter_mean": round(_stt.mean(pooled_first), 4), "mid_mean": round(_stt.mean(pooled_mid), 4),
                       "last_quarter_mean": round(_stt.mean(pooled_last), 4), "total_bonus": round(sum(pooled_all), 2),
                       "v2_target_reward": v2_targets, "bonus_over_targets": round(sum(pooled_all) / max(1, v2_targets), 4),
                       "voided_in_falls": round(voided_falls, 3), "cap_hits": cap_hits, "episodes": len(pooled_all),
                       "decay_ratio_last_over_first": round(_stt.mean(pooled_last) / _stt.mean(pooled_first), 4) if _stt.mean(pooled_first) else None},
            "elevated_credit_by_phase": {k: round(v, 3) for k, v in high_credit_by_phase.items()},
            "high_left_credit_by_phase": {k: round(v, 3) for k, v in highleft_credit_by_phase.items()},
            "late_elevated_first_visit_weight_mean": round(_stt.mean(first_high_w), 4) if first_high_w else None,
            "late_elevated_first_visits": len(first_high_w)}
    # pooled-table reference (one table for all slots) on the trained scenario, for the decay comparison
    table = xp.ExploreTable(rank=None)
    rng = _random.Random(7)
    seq = []
    for k in range(sum(slots.values())):
        rec, _ = _run_episode(T[rng.randrange(len(T))], table, cls)
        seq.append(rec["bonus"])
    q = len(seq) // 4
    report["pooled_table_reference_trained"] = {"first_quarter_mean": round(_stt.mean(seq[:q]), 4), "last_quarter_mean": round(_stt.mean(seq[-q:]), 4),
                                                "total": round(sum(seq), 2)}
    write_json(OUT / "slot_simulation.json", report)
    print(json.dumps({k: v for k, v in report.items() if k != "scenarios"}, indent=1))
    for sc, v in report["scenarios"].items():
        print(sc, json.dumps({k: v[k] for k in ("pooled", "elevated_credit_by_phase", "high_left_credit_by_phase",
                                                 "late_elevated_first_visit_weight_mean", "late_elevated_first_visits")}, indent=0))
        print("  per slot:", {r: (s["first_quarter_mean"], s["mid_mean"], s["last_quarter_mean"], s["table_cells"]) for r, s in v["per_slot"].items()})
    return 0


def cmd_variants(_: argparse.Namespace) -> int:
    """Fixture-free variant comparison: in which state do policy-generated trajectories FIRST reach elevated cells
    (y >= 2400), and does the flight end in a landing? Variant G credits grounded first visits only; J credits grounded
    and airborne-with-a-jump-left; L (the contract) credits grounded and any airborne visit that a landing follows."""
    cls = _st.ActionClassifier(_st.load_table(), "mario")
    pools = {"untrained": _traces("initial"), "trained": _traces("final")}
    # sources + foothold continuations (post-cut rows) as policy-generated v3 traces with jumps
    extra = []
    for p in sorted((REPO_ROOT / "runs" / "m7n" / "feasibility" / "prefix" / "foothold" / "work").glob("*/episode.json.gz")):
        with _gzip.open(p, "rt", encoding="utf-8") as fp:
            g = json.load(fp)
        rows = [[r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], int(r[1] is not None)] for r in g["trajectory_after_cut"]]
        extra.append({"rows": rows, "fall": g["end"] == "fall", "initial": [rows[0][1], rows[0][2]] if rows and rows[0][1] is not None else [0, -2550],
                      "map_bounds": [9600, -9600, 9600, -9600], "breaks": []})
    pools["foothold_post_cut"] = extra
    out = {}
    for name, trs in pools.items():
        c = _Counter()
        for tr in trs:
            visited = set()
            pending_state = []   # (state_kind) of airborne elevated first visits awaiting a landing
            for r in tr["rows"]:
                t, x, y, ga, status, vx, vy, jumps, live = r
                if not live or x is None or cls.name(int(status)) in xp.INELIGIBLE_CLASSES:
                    continue
                cell = xp.cell_of(x, y, 800.0)
                grounded = int(ga) == 0
                if grounded and pending_state:
                    for kind in pending_state:
                        c[f"{kind}_then_landed"] += 1
                    pending_state = []
                if cell in visited or y < 2400:
                    visited.add(cell)
                    continue
                visited.add(cell)
                if grounded:
                    c["elevated_first_visit_grounded"] += 1
                elif jumps is not None and int(jumps) < JUMPS_MAX:
                    c["elevated_first_visit_air_jump_left"] += 1
                    pending_state.append("air_jump_left")
                else:
                    c["elevated_first_visit_air_helpless"] += 1
                    pending_state.append("air_helpless")
            for kind in pending_state:
                c[f"{kind}_never_landed"] += 1
        g_ = c["elevated_first_visit_grounded"]
        j_ = c["elevated_first_visit_air_jump_left"]
        h_ = c["elevated_first_visit_air_helpless"]
        tot = g_ + j_ + h_
        out[name] = {"trajectories": len(trs), "elevated_first_visits": tot, "grounded": g_, "air_jump_left": j_, "air_helpless": h_,
                     "air_jump_left_then_landed": c["air_jump_left_then_landed"], "air_jump_left_never_landed": c["air_jump_left_never_landed"],
                     "air_helpless_then_landed": c["air_helpless_then_landed"], "air_helpless_never_landed": c["air_helpless_never_landed"],
                     "share_credited": {"G_grounded_only": round(g_ / tot, 3) if tot else None,
                                        "J_jump_left": round((g_ + j_) / tot, 3) if tot else None,
                                        "L_landing_banked": round((g_ + c["air_jump_left_then_landed"] + c["air_helpless_then_landed"]) / tot, 3) if tot else None}}
    write_json(OUT / "variants.json", {"utc": xc.utc_now(), "jumps_max_assumed": JUMPS_MAX, "elevated": "y >= 2400 (cell row >= 3 at 800 units)",
                                       "pools": out})
    print(json.dumps(out, indent=1))
    return 0

def cmd_status(_: argparse.Namespace) -> int:
    s = OUT / "replays" / "summary.json"
    print(read_json(s) if s.is_file() else "no replay summary")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["register-replays", "replay", "status", "simulate", "variants"])
    ap.add_argument("--workers", default=3)
    args = ap.parse_args(argv)
    return {"register-replays": cmd_register, "replay": cmd_replay, "status": cmd_status, "simulate": cmd_simulate,
            "variants": cmd_variants}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
