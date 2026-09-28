#!/usr/bin/env python3
"""M7p wall-top census: how often does the seed-1 geo4 final policy reach the wall top (ledge L0) in its 100 recorded
final stochastic tick-0 episodes? The campaign decision (failure_regression, v3 selected) is NOT re-decided and no new
policy evaluation is run: the census exactly replays the 100 preserved canonical action artifacts (the two addendum traces
are reused, 98 are replayed) and counts native contact evidence. Lives under rl/tools (outside the frozen fingerprint set).

    python rl/tools/m7p_walltop_census.py register   # the 100 episodes, definitions, runtime estimate (write-once)
    python rl/tools/m7p_walltop_census.py replay     # 98 minimal exact fresh-process replays, raw replies kept, resumable
    python rl/tools/m7p_walltop_census.py count      # the census over all 100 traces -> census.json

Counting rules (frozen in the registration):
  * a step is GROUNDED when the native observation says fighter_valid 1, btt_active 1, ground_air_state 0; its SURFACE
    is the native collision line the fighter stands on (spatial.fighter.floor_line_id, SSB64_RL_SPATIAL contract),
    cross-checked against the decoded geometry (m7g_fixture.classify_ground must name the same line); no landing is
    inferred from height or proximity;
  * a CONTACT STRETCH is a maximal run of consecutive grounded steps on one line; an AIRBORNE SEGMENT is what lies
    between two stretches (or a stretch and the episode's end);
  * an L1 TAKEOFF is an airborne segment that starts from a stretch on line 1 (the raised right step);
  * a WALL-TOP LANDING is the first grounded step of a stretch on line 0 (the ledge L0, x -2100..-1200, y 3000) that
    follows an airborne segment; an L0 VISIT groups L0 stretches separated only by hops that re-land on L0;
  * the visit's ARRIVAL is the surface of the stretch before its first airborne segment (the takeoff surface) and its
    DEPARTURE is the airborne segment after its last L0 stretch, classified by what happens next: a left entry
    (x < -2100, then landing surface / qualified per btt_qualified_crossing_v1, code m7n_crossing.analyse_trace, unchanged),
    a landing on another surface, a native failure, or the horizon;
  * qualified left landings and left-target breaks come from the frozen criterion code, not from this file.
Native gameplay is authoritative; native RNG is never inspected; fixtures / TAS are not read.
"""
from __future__ import annotations

import argparse
import gzip
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

RL_DIR = Path(__file__).resolve().parents[1]
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import experiment_config as ec  # noqa: E402
import m7g_fixture as fx  # noqa: E402
import m7n_crossing as xc  # noqa: E402
import m7p_matrix as pm  # noqa: E402

REPO_ROOT = RL_DIR.parent
OUT = REPO_ROOT / "runs" / "m7p" / "addendum" / "walltop_census"
REGISTRY = REPO_ROOT / "docs" / "rl_geometry_scale_m7p_walltop_census_registration.json"
ADDENDUM_REGISTRY = REPO_ROOT / "docs" / "rl_geometry_scale_m7p_crossing_replays.json"
ADDENDUM_TRACES = REPO_ROOT / "runs" / "m7p" / "addendum" / "crossings" / "replays"
EVAL = REPO_ROOT / "runs" / "m7p" / "campaign" / "_eval" / "m7p_geo4_s1" / "final" / "stochastic" / "evaluation.json"
CHECKPOINT = REPO_ROOT / "runs" / "m7p" / "campaign" / "m7p_geo4_s1" / "final"
LEDGE_LINE, RIGHT_STEP_LINE, PLATFORM_LINE = 0, 1, 19
UP_B_STATUSES = (225, 226)
# runtime basis: the two addendum replays (3445 steps 7.7 s, 1227 steps 4.0 s) -> ~1.67 ms per step + ~2.0 s per process
PER_STEP_MS, FIXED_S = 1.67, 2.0


def read_json(p: Path) -> Any:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def write_json(p: Path, d: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=1, default=str) + "\n", encoding="utf-8")


def load_trace(p: Path) -> Dict[str, Any]:
    with gzip.open(p, "rt", encoding="utf-8") as fp:
        return json.load(fp)


# -- registration ------------------------------------------------------------------------------------------------------


def cmd_register() -> int:
    if REGISTRY.is_file():
        print(f"refused: {ec.repo_relative(REGISTRY)} exists (a registered list is never rewritten)")
        return 1
    ev = read_json(EVAL)
    add = read_json(ADDENDUM_REGISTRY)
    addendum = {}
    for k, e in enumerate(add["episodes"]):
        tp = ADDENDUM_TRACES / f"{k:02d}_{e['episode_id'][-8:]}" / "trace.json.gz"
        addendum[e["episode_id"]] = {"path": ec.repo_relative(tp), "sha256": xc.sha256_file(tp)}
    ck = read_json(CHECKPOINT / "checkpoint.json")
    exp = ec.load_experiment(pm.RunSpec(1, 2).config_path)
    episodes = []
    for row in sorted(ev["episodes"], key=lambda r: r["order"]):
        art = REPO_ROOT / row["artifact_dir"]
        a = addendum.get(row["episode_id"])
        episodes.append({"order": row["order"], "episode_id": row["episode_id"], "rank": row["rank"],
                         "worker_episode": row["worker_episode"], "native_action_digest": row["native_action_digest"],
                         "artifact_dir": row["artifact_dir"],
                         "artifact_actions_sha256": xc.sha256_file(art / "actions.jsonl"),
                         "artifact_metadata_sha256": xc.sha256_file(art / "metadata.json"),
                         "length": row["length"], "end_reason": row["end_reason"], "targets_broken": row["targets_broken"],
                         "target_break_ticks": row["target_break_ticks"],
                         "recorded_min_live_x": row["eval_metrics"]["min_live_x"],
                         "recorded_first_left_entry_tick": (row["eval_metrics"]["first_left_entry"] or {}).get("consumed_tick"),
                         "source": "addendum_trace" if a else "replay", "addendum_trace": a})
    n_rep = sum(1 for e in episodes if e["source"] == "replay")
    ticks = sum(e["length"] for e in episodes if e["source"] == "replay")
    est = n_rep * FIXED_S + ticks * PER_STEP_MS / 1000.0
    reg = {"contract": "m7p_walltop_census_v1", "utc": xc.utc_now(),
           "purpose": "exact-replay census of the 100 preserved seed-1 geo4 final stochastic tick-0 episodes: wall-top (ledge L0) "
                      "landings counted from native contact evidence; the campaign decision (failure_regression, v3 selected) is "
                      "not re-decided; no new stochastic evaluation, no training",
           "checkpoint": {"path": ec.repo_relative(CHECKPOINT), "run_id": ck["run_id"], "num_timesteps": ck["num_timesteps"],
                          "files_sha256": {f: xc.sha256_file(CHECKPOINT / f) for f in ("model.zip", "vecnormalize.pkl", "checkpoint.json")},
                          "observation": (ck.get("contracts") or {}).get("policy_observation_contract"),
                          "observation_sha256": (ck.get("contracts") or {}).get("policy_observation_contract_sha256")},
           "executable_sha256": xc.sha256_file(exp.executable), "flags": dict(exp.extra_env, **pm.DIAG_FLAG),
           "evaluation": {"path": ec.repo_relative(EVAL), "sha256": xc.sha256_file(EVAL), "episodes": len(ev["episodes"])},
           "addendum_registry": {"path": ec.repo_relative(ADDENDUM_REGISTRY), "sha256": xc.sha256_file(ADDENDUM_REGISTRY)},
           "geometry_source_sha256": xc.geometry().source_sha256,
           "definitions": __doc__.split("Counting rules (frozen in the registration):", 1)[1].strip(),
           "exactness": "digest equal to native_action_digest, no consumed_tick mismatch, 0 unsent, step count equal to the "
                        "recorded length, replayed break table equal to the recorded target_break_ticks, replayed first left "
                        "entry equal to the recorded one",
           "runtime_estimate": {"episodes_to_replay": n_rep, "episodes_reused": len(episodes) - n_rep, "ticks_to_replay": ticks,
                                "per_step_ms": PER_STEP_MS, "fixed_s_per_process": FIXED_S, "estimate_s": round(est),
                                "estimate_min": round(est / 60, 1),
                                "mode": "sequential, one fresh process per episode, runtime dir removed after each",
                                "basis": "addendum replays: 3445 steps 7.7 s, 1227 steps 4.0 s"},
           "outputs": {"traces": ec.repo_relative(OUT / "replays"), "replays_log": ec.repo_relative(OUT / "replays.jsonl"),
                       "summary": ec.repo_relative(OUT / "replays_summary.json"), "census": ec.repo_relative(OUT / "census.json")},
           "episodes": episodes,
           "exclusions": ["no new stochastic evaluation", "no training", "fixtures and TAS not read", "no native RNG inspection",
                          "frozen M7p results, rule and code fingerprints unchanged (this tool lives under rl/tools)"]}
    write_json(REGISTRY, reg)
    print(f"registered {len(episodes)} episodes ({n_rep} to replay, {len(episodes) - n_rep} reused; {ticks} ticks; "
          f"estimate {est / 60:.1f} min) -> {ec.repo_relative(REGISTRY)}")
    return 0


# -- replay ------------------------------------------------------------------------------------------------------------


def _trace_path(e: Dict[str, Any]) -> Path:
    return OUT / "replays" / f"{e['order']:03d}_{e['episode_id'][-8:]}" / "trace.json.gz"


def _done(e: Dict[str, Any]) -> bool:
    p = _trace_path(e)
    return p.is_file() and (p.parent / "result.json").is_file()


def cmd_replay() -> int:
    import m7f_trace as tr
    from m7_runtime import BATTLESHIP_IMAGE, install_kill_on_close_job, list_processes_named, wait_until_no_process
    from m7k_target2 import remove_runtime_with_retry

    if not REGISTRY.is_file():
        print("no registry: run `register` first")
        return 1
    if list_processes_named():
        print("BattleShip already running; refusing")
        return 2
    install_kill_on_close_job()
    reg = read_json(REGISTRY)
    exe = ec.load_experiment(pm.RunSpec(1, 2).config_path).executable
    if xc.sha256_file(exe) != reg["executable_sha256"]:
        print("executable differs from the registered one")
        return 1
    n_replay = sum(1 for e in reg["episodes"] if e["source"] == "replay")
    todo = [e for e in reg["episodes"] if e["source"] == "replay" and not _done(e)]
    print(f"{len(todo)} episode(s) to replay ({n_replay - len(todo)} already done)", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    t_all = time.perf_counter()
    for e in todo:
        art = REPO_ROOT / e["artifact_dir"]
        if xc.sha256_file(art / "actions.jsonl") != e["artifact_actions_sha256"]:
            print(f"{e['episode_id']}: artifact changed since registration; stopping")
            return 1
        acts, _meta = tr.artifact_actions(art)
        work = _trace_path(e).parent
        work.mkdir(parents=True, exist_ok=True)
        t0 = time.perf_counter()
        trace = tr.run_stepping_trace(f"m7p_walltop_{e['order']:03d}", exe, acts, work / "game",
                                      extra_env=dict(reg["flags"]), index=9800 + e["order"])
        digest = tr.action_digest(acts[:len(trace["steps"])], [s["consumed_tick"] for s in trace["steps"]])
        exact = (trace["consumed_tick_mismatch"] is None and trace["unsent"] == 0
                 and digest == e["native_action_digest"] and len(trace["steps"]) == e["length"])
        with gzip.open(_trace_path(e), "wt", encoding="utf-8") as fp:
            json.dump({"episode_id": e["episode_id"], "exact": exact, "digest": digest,
                       "initial": trace["initial"], "steps": trace["steps"]}, fp)
        res = {"order": e["order"], "episode_id": e["episode_id"], "exact": exact, "steps": len(trace["steps"]),
               "unsent": trace["unsent"], "consumed_tick_mismatch": trace["consumed_tick_mismatch"], "digest": digest,
               "startup_s": trace.get("startup_s"), "stepping_s": trace.get("stepping_s"),
               "wall_s": round(time.perf_counter() - t0, 1), "trace": ec.repo_relative(_trace_path(e)), "utc": xc.utc_now()}
        res["runtime_cleanup"] = remove_runtime_with_retry(work / "game" / "runtime")
        write_json(work / "result.json", res)
        with (OUT / "replays.jsonl").open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(res, default=str) + "\n")
        print(f"[{e['order']:03d}] {e['episode_id'][-8:]}: exact {exact}, {len(trace['steps'])} steps, {res['wall_s']} s", flush=True)
        if not exact:
            print("inexact replay; stopping (partial results preserved)")
            leftover = wait_until_no_process(BATTLESHIP_IMAGE, timeout=30.0)
            return 3 if not leftover else 4
    leftover = wait_until_no_process(BATTLESHIP_IMAGE, timeout=30.0)
    results = [read_json(_trace_path(e).parent / "result.json") for e in reg["episodes"] if e["source"] == "replay" and _done(e)]
    write_json(OUT / "replays_summary.json",
               {"contract": "m7p_walltop_census_replays_result_v1", "utc": xc.utc_now(),
                "registry_sha256": xc.sha256_file(REGISTRY), "replayed": len(results),
                "exact": sum(1 for r in results if r["exact"]),
                "wall_s_this_invocation": round(time.perf_counter() - t_all, 1),
                "wall_s_sum": round(sum(r["wall_s"] for r in results), 1), "leftover_pids": leftover, "results": results})
    print(f"done: {len(results)} replayed, {sum(1 for r in results if r['exact'])} exact, leftover {leftover}")
    return 0 if all(r["exact"] for r in results) and not leftover and len(results) == n_replay else 1


# -- census (pure) -----------------------------------------------------------------------------------------------------


def _live(o: Dict[str, Any]) -> bool:
    return int(o.get("fighter_valid", 0)) == 1 and int(o.get("btt_active", 0)) == 1


def _surface_of(step: Dict[str, Any]) -> Optional[int]:
    """The native floor line the fighter stands on, or None when airborne / not live."""
    o = step.get("observation") or {}
    if not _live(o) or int(o.get("ground_air_state", -1)) != 0:
        return None
    return int(((step.get("spatial") or {}).get("fighter") or {})["floor_line_id"])


def _label(line: int) -> str:
    return "moving_platform" if line == PLATFORM_LINE else f"L{line}"


def _pt(step: Dict[str, Any]) -> Dict[str, Any]:
    o = step["observation"]
    return {"consumed_tick": int(step["consumed_tick"]), "x": round(float(o["position_x"]), 1),
            "y": round(float(o["position_y"]), 1), "status_id": int(o["fighter_status_id"]), "jumps_used": int(o["jumps_used"])}


def census_for(rec: Dict[str, Any], trace: Dict[str, Any], geo: fx.StageGeometry) -> Dict[str, Any]:
    steps = trace["steps"]
    an = xc.analyse_trace(trace["initial"], steps, geo)
    breaks = [(int(t), int(c)) for t, c in an["breaks"]]
    left_x = float(geo.derived["left_boundary_x"])

    def remaining(tick: int) -> int:
        return 10 - sum(1 for _, c in breaks if c <= tick)

    surf = [_surface_of(s) for s in steps]
    # geometry cross-check of every grounded step
    mism = [i for i, s in enumerate(steps)
            if surf[i] is not None and fx.classify_ground(geo, s["observation"]) != _label(surf[i])]
    # contact stretches
    stretches: List[Dict[str, Any]] = []
    for i, ln in enumerate(surf):
        if ln is None:
            continue
        if stretches and stretches[-1]["line"] == ln and stretches[-1]["end"] == i - 1:
            stretches[-1]["end"] = i
        else:
            stretches.append({"line": ln, "start": i, "end": i})
    fall_idx = an["native_failure_step"]
    horizon = len(steps) >= 3600 and fall_idx is None

    def segment_after(st: Dict[str, Any], nxt: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        a, b = st["end"] + 1, (nxt["start"] - 1 if nxt else len(steps) - 1)
        obs = [steps[i]["observation"] for i in range(a, b + 1) if _live(steps[i]["observation"])]
        ys = [float(o["position_y"]) for o in obs] or [float("nan")]
        xs = [float(o["position_x"]) for o in obs] or [float("nan")]
        sts = [int(o["fighter_status_id"]) for o in obs]
        left_i = next((i for i in range(a, b + 1)
                       if _live(steps[i]["observation"]) and float(steps[i]["observation"]["position_x"]) < left_x), None)
        return {"from_line": st["line"], "from": _label(st["line"]), "takeoff": _pt(steps[st["end"]]),
                "first_airborne_tick": int(steps[a]["consumed_tick"]) if a <= b else None,
                "airborne_steps": b - a + 1, "to_line": nxt["line"] if nxt else None,
                "to": _label(nxt["line"]) if nxt else None, "landing": _pt(steps[nxt["start"]]) if nxt else None,
                "max_y": round(max(ys), 1), "min_x": round(min(xs), 1),
                "over_ledge": any(y >= 3000.0 and x <= -1200.0 for x, y in zip(xs, ys)),
                "left_entry_tick": int(steps[left_i]["consumed_tick"]) if left_i is not None else None,
                "double_jump": any(int(o["jumps_used"]) >= 2 for o in obs), "up_b": any(s in UP_B_STATUSES for s in sts),
                "ends": "landing" if nxt else ("fall" if fall_idx is not None else ("horizon" if horizon else "end"))}

    segments = [segment_after(st, stretches[k + 1] if k + 1 < len(stretches) else None) for k, st in enumerate(stretches)]
    l1_takeoffs = [sg for sg in segments if sg["from_line"] == RIGHT_STEP_LINE]
    # L0 visits: stretches on line 0, merged across hops that re-land on line 0
    visits: List[Dict[str, Any]] = []
    k = 0
    while k < len(stretches):
        st = stretches[k]
        if st["line"] != LEDGE_LINE:
            k += 1
            continue
        arrival = segments[k - 1] if k > 0 else None  # the airborne segment that landed here
        grounded = st["end"] - st["start"] + 1
        hops = 0
        last = k
        while last + 1 < len(stretches) and stretches[last + 1]["line"] == LEDGE_LINE:
            hops += 1
            grounded += stretches[last + 1]["end"] - stretches[last + 1]["start"] + 1
            last += 1
        dep = segments[last]
        land_tick = int(steps[st["start"]]["consumed_tick"])
        entry = next((en for en in an["entries"]
                      if dep["left_entry_tick"] is not None and int(en["consumed_tick"]) == dep["left_entry_tick"]), None)
        if dep["left_entry_tick"] is not None:
            outcome = "left_entry"
        elif dep["to"] is not None:
            outcome = f"landed_{dep['to']}"
        else:
            outcome = dep["ends"]
        visits.append({"first_landing": _pt(steps[st["start"]]), "first_landing_tick": land_tick,
                       "targets_remaining_at_landing": remaining(land_tick), "arrival": arrival,
                       "grounded_steps_on_L0": grounded, "hops_on_L0": hops,
                       "last_L0_tick": int(steps[stretches[last]["end"]]["consumed_tick"]),
                       "departure": dep, "outcome": outcome,
                       "left_landing": (entry or {}).get("landing"), "qualified": bool((entry or {}).get("qualified")),
                       "left_target_breaks_after": [(t, c) for t, c in an["left_target_breaks"] if c > land_tick]})
        k = last + 1
    live_steps = [s["observation"] for s in steps if _live(s["observation"])]
    return {"episode_id": rec["episode_id"], "order": rec["order"], "exact_replay": bool(trace.get("exact")),
            "steps": len(steps), "end_reason": rec["end_reason"], "targets_broken": len(breaks),
            "contact_geometry_mismatches": len(mism),
            "grounded_steps_by_line": {_label(ln): sum(1 for s in surf if s == ln) for ln in sorted({s for s in surf if s is not None})},
            "max_y": round(max(float(o["position_y"]) for o in live_steps), 1),
            "min_x": round(min(float(o["position_x"]) for o in live_steps), 1),
            "steps_at_or_above_wall_top": an["wall_top"]["steps_at_or_above_wall_top"],
            "l1_takeoffs": l1_takeoffs, "l0_visits": visits,
            "left_entries": len(an["entries"]), "qualified_crossing": an["qualified_crossing"],
            "left_target_breaks": an["left_target_breaks"],
            "first_left_entry_tick": (an["first_left_entry"] or {}).get("consumed_tick")}


def aggregate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    with_visit = [r for r in rows if r["l0_visits"]]
    firsts = [r["l0_visits"][0] for r in with_visit]
    all_visits = [v for r in rows for v in r["l0_visits"]]
    l1 = [sg for r in rows for sg in r["l1_takeoffs"]]
    l1_to_l0 = [sg for sg in l1 if sg["to_line"] == LEDGE_LINE]
    l1_over = [sg for sg in l1 if sg["over_ledge"] and sg["to_line"] != LEDGE_LINE]
    return {"episodes": len(rows), "exact": sum(1 for r in rows if r["exact_replay"]),
            "contact_geometry_mismatches": sum(r["contact_geometry_mismatches"] for r in rows),
            "episodes_with_wall_top_landing": len(with_visit), "wall_top_visits_total": len(all_visits),
            "episodes_with_wall_top_landing_ids": [r["episode_id"] for r in with_visit],
            "first_landing_ticks": [v["first_landing_tick"] for v in firsts],
            "targets_remaining_at_first_landing": [v["targets_remaining_at_landing"] for v in firsts],
            "arrival_surfaces": Counter((v["arrival"] or {}).get("from") for v in all_visits),
            "grounded_steps_on_L0_per_visit": [v["grounded_steps_on_L0"] for v in all_visits],
            "departure_outcomes": Counter(v["outcome"] for v in all_visits),
            "qualified_left_landings": sum(1 for v in all_visits if v["qualified"]),
            "left_target_breaks_after_landing": sum(len(v["left_target_breaks_after"]) for v in all_visits),
            "l1_takeoffs_total": len(l1), "episodes_with_l1_takeoff": sum(1 for r in rows if r["l1_takeoffs"]),
            "l1_takeoffs_landing_L0": len(l1_to_l0), "l1_takeoffs_over_ledge_not_landing_L0": len(l1_over),
            "l1_takeoff_landing_surfaces": Counter(sg["to"] or sg["ends"] for sg in l1),
            "l1_takeoff_max_y_quartiles": (statistics.quantiles([sg["max_y"] for sg in l1], n=4) if len(l1) >= 4
                                           else [sg["max_y"] for sg in l1]),
            "episodes_max_y_at_or_above_wall_top": sum(1 for r in rows if r["max_y"] >= 3000.0),
            "episodes_min_x_left_of_ledge_right_end": sum(1 for r in rows if r["min_x"] <= -1200.0),
            "left_entries_total": sum(r["left_entries"] for r in rows),
            "episodes_with_left_entry": sum(1 for r in rows if r["left_entries"]),
            "qualified_crossings": sum(1 for r in rows if r["qualified_crossing"]),
            "episodes_with_left_target_break": sum(1 for r in rows if r["left_target_breaks"]),
            "grounded_steps_by_line_total": dict(sum((Counter(r["grounded_steps_by_line"]) for r in rows), Counter()))}


def cmd_count() -> int:
    reg = read_json(REGISTRY)
    geo = xc.geometry()
    rows, problems = [], []
    for e in reg["episodes"]:
        tp = REPO_ROOT / e["addendum_trace"]["path"] if e["source"] == "addendum_trace" else _trace_path(e)
        if not tp.is_file():
            problems.append(f"{e['episode_id']}: trace missing ({ec.repo_relative(tp)})")
            continue
        if e["source"] == "addendum_trace" and xc.sha256_file(tp) != e["addendum_trace"]["sha256"]:
            problems.append(f"{e['episode_id']}: addendum trace changed since registration")
            continue
        trace = load_trace(tp)
        row = census_for(e, trace, geo)
        replayed_breaks = [c for _, c in xc.analyse_trace(trace["initial"], trace["steps"], geo)["breaks"]]
        row["breaks_equal_recorded"] = replayed_breaks == list(e["target_break_ticks"])
        row["first_left_entry_equal_recorded"] = row["first_left_entry_tick"] == e["recorded_first_left_entry_tick"]
        row["exact_replay"] = bool(row["exact_replay"] and row["breaks_equal_recorded"]
                                   and row["first_left_entry_equal_recorded"] and row["steps"] == e["length"])
        rows.append(row)
    agg = aggregate(rows) if rows else {}
    out = {"contract": "m7p_walltop_census_result_v1", "utc": xc.utc_now(), "registry_sha256": xc.sha256_file(REGISTRY),
           "complete": not problems and len(rows) == len(reg["episodes"]), "problems": problems, "aggregate": agg, "episodes": rows}
    write_json(OUT / "census.json", out)
    print(json.dumps({k: v for k, v in agg.items() if k != "episodes_with_wall_top_landing_ids"}, indent=1, default=str))
    for r in rows:
        for v in r["l0_visits"]:
            a = v["arrival"] or {}
            print(f"  {r['episode_id'][-8:]} order {r['order']:3d}: landed L0 at {v['first_landing_tick']} from {a.get('from')} "
                  f"(takeoff {(a.get('takeoff') or {}).get('consumed_tick')}), targets left {v['targets_remaining_at_landing']}, "
                  f"{v['grounded_steps_on_L0']} grounded steps (+{v['hops_on_L0']} hops), departure -> {v['outcome']} "
                  f"(min_x {v['departure']['min_x']}), qualified {v['qualified']}, left breaks {v['left_target_breaks_after']}")
    if problems:
        print("PROBLEMS:", *problems, sep="\n  ")
    return 0 if out["complete"] else 1


def self_test() -> int:
    """The counting code against the two addendum traces and their documented facts."""
    geo = xc.geometry()
    add = read_json(ADDENDUM_REGISTRY)
    want = {"episode_20260928T072129Z_44619208": (2318, 2434, 525, "left_entry", True, [(6, 3008)]),
            "episode_20260928T072253Z_85c10043": (745, 868, 131, "left_entry", False, [])}
    ok = True
    for k, e in enumerate(add["episodes"]):
        tr = load_trace(ADDENDUM_TRACES / f"{k:02d}_{e['episode_id'][-8:]}" / "trace.json.gz")
        row = census_for({"episode_id": e["episode_id"], "order": k, "end_reason": e["end_reason"]}, tr, geo)
        v = row["l0_visits"]
        got = ((v[0]["arrival"]["takeoff"]["consumed_tick"], v[0]["first_landing_tick"], v[0]["grounded_steps_on_L0"],
                v[0]["outcome"], v[0]["qualified"], [tuple(b) for b in v[0]["left_target_breaks_after"]])
               if len(v) == 1 else None)
        good = got == want[e["episode_id"]] and v[0]["arrival"]["from"] == "L1" and row["contact_geometry_mismatches"] == 0
        ok &= good
        print(f"{e['episode_id'][-8:]}: visits {len(v)} got {got} want {want[e['episode_id']]} "
              f"l1_takeoffs {len(row['l1_takeoffs'])} -> {'PASS' if good else 'FAIL'}")
    print("self_test", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["register", "replay", "count", "self_test"])
    args = ap.parse_args(argv)
    return {"register": cmd_register, "replay": cmd_replay, "count": cmd_count, "self_test": self_test}[args.command]()


if __name__ == "__main__":
    sys.exit(main())
