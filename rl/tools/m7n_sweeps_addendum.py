#!/usr/bin/env python3
"""M7n results addendum: the seven-right-target sweeps of the FINAL stochastic tick-0 evaluations (both arms).

Lives under rl/tools so the frozen M7n code fingerprint (rl/*.py, rl/data, profiles, rules) is untouched; reads the
recorded campaign evidence only; writes below runs/m7n/addendum/sweeps and the registered replay list in docs/.

    python rl/tools/m7n_sweeps_addendum.py records    # what the existing records establish (no game)
    python rl/tools/m7n_sweeps_addendum.py register   # the fixed replay list (sweep episodes only), refused if it exists
    python rl/tools/m7n_sweeps_addendum.py replay     # exact fresh-process replays with the read-only diagnostics
    python rl/tools/m7n_sweeps_addendum.py table      # the addendum tables (markdown) from the records + replays

Registered definitions reused unchanged (rl/m7l_analysis.episode_facts, rule v2 parameters): right = {0, 2, 3, 4, 5,
7, 9}; sweep tick = max first-break tick over the seven; L = target 2 broken by consumed tick <= 2699 with >= 5 static
right targets broken in the episode; R = all seven right targets broken by consumed tick <= 2699. Remaining actions
= 3600 - (sweep consumed_tick + 1). Post-sweep behaviour comes from the exact replay's native trajectory only.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

RL_DIR = Path(__file__).resolve().parents[1]
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import experiment_config as ec  # noqa: E402
import m7g_fixture as fx  # noqa: E402
import m7l_analysis as la  # noqa: E402
import m7n_analysis as na  # noqa: E402
import m7n_crossing as xc  # noqa: E402
import m7n_matrix as nm  # noqa: E402

REPO_ROOT = RL_DIR.parent
OUT = REPO_ROOT / "runs" / "m7n" / "addendum" / "sweeps"
REGISTRY = REPO_ROOT / "docs" / "rl_observation_v3_m7n_sweeps_addendum_replays.json"
ANALYSIS = REPO_ROOT / "runs" / "m7n" / "campaign" / "_matrix" / "analysis_n3.json"
HORIZON = 3600


def read_json(p: Path) -> Any:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def write_json(p: Path, d: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=1, default=str) + "\n", encoding="utf-8")


def final_labels() -> List[Dict[str, Any]]:
    out = []
    for spec in nm.matrix():
        out.append({"arm": "v3", "seed": spec.seed, "run": spec.name, "label_dir": spec.eval_dir / "final",
                    "flags": dict(nm.load_run(spec).extra_env, **nm.DIAG_FLAG)})
    for s in nm.SEEDS:
        h = nm.HistoricalControl(s)
        out.append({"arm": "v1", "seed": s, "run": h.name, "label_dir": h.eval_dir / "final",
                    "flags": dict(nm.M6_FLAGS, **nm.DIAG_FLAG)})
    return out


def sweep_rows(P: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every final stochastic episode of both arms whose seven right targets all broke, with the registered facts."""
    rows = []
    for lab in final_labels():
        eps = la.read_label(lab["label_dir"])["stochastic"]
        for e in eps:
            f, problems = la.episode_facts(e, P)
            if not f["seven_right"]:
                continue
            em = e["eval_metrics"]
            breaks = [(int(b["target_id"]), int(b["consumed_tick"])) for b in em["target_breaks"]]
            sweep = int(f["sweep_tick"])
            rows.append({"arm": lab["arm"], "seed": lab["seed"], "run": lab["run"], "episode_id": e["episode_id"],
                         "order": e.get("order"), "artifact_dir": e["artifact_dir"],
                         "native_action_digest": e["native_action_digest"], "breaks": breaks,
                         "t2_tick": f["t2_tick"], "sweep_tick": sweep, "remaining_actions": HORIZON - (sweep + 1),
                         "L": bool(f["L"]), "R": bool(f["R"]), "targets": f["targets"], "end_reason": e["end_reason"],
                         "length": e["length"], "last_consumed_tick": e.get("last_consumed_tick"),
                         "min_live_x": em.get("min_live_x"), "left_region_steps": em.get("left_region_steps"),
                         "first_left_entry": em.get("first_left_entry"), "left_targets": em.get("left_targets_broken"),
                         "record_problems": problems, "flags": lab["flags"]})
    rows.sort(key=lambda r: (r["arm"], r["seed"], r["order"]))
    return rows


def lr_counts(P: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for lab in final_labels():
        eps = la.read_label(lab["label_dir"])["stochastic"]
        facts = [la.episode_facts(e, P)[0] for e in eps]
        out[f"{lab['arm']}_s{lab['seed']}"] = {"n": len(facts), "L": sum(f["L"] for f in facts), "R": sum(f["R"] for f in facts),
                                               "seven_right": sum(f["seven_right"] for f in facts),
                                               "t2": sum(f["t2"] for f in facts)}
    for arm in ("v1", "v3"):
        ks = [k for k in out if k.startswith(arm + "_")]
        out[f"{arm}_pooled"] = {q: sum(out[k][q] for k in ks) for q in ("n", "L", "R", "seven_right", "t2")}
    return out


def cmd_records(P: Dict[str, Any]) -> int:
    rows = sweep_rows(P)
    doc = {"contract": "m7n_sweeps_addendum_records_v1", "utc": xc.utc_now(), "definitions": {
        "right_ids": list(P["right_ids"]), "deadline_consumed_tick": P["deadline_consumed_tick"],
        "L": "target 2 broken by the deadline with >= L_static_right_min static right targets broken in the episode",
        "R": "all seven right targets broken by the deadline", "remaining_actions": "3600 - (sweep consumed_tick + 1)"},
        "lr_counts": lr_counts(P), "sweeps": rows,
        "what_records_establish": "break order and ticks, sweep tick, L / R, end reason, length, min live x, left-region "
                                  "steps, first left entry (all None here); NOT heights, wall approach or post-sweep motion"}
    write_json(OUT / "records.json", doc)
    print(json.dumps({k: doc[k] for k in ("lr_counts",)}, indent=1))
    for r in rows:
        print(r["arm"], r["seed"], r["episode_id"][-8:], "sweep", r["sweep_tick"], "t2", r["t2_tick"], "rem", r["remaining_actions"],
              "L", r["L"], "R", r["R"], r["end_reason"], "min_x", round(r["min_live_x"], 1), "problems", r["record_problems"])
    return 0


def cmd_register(P: Dict[str, Any]) -> int:
    if REGISTRY.is_file():
        print(f"refused: {ec.repo_relative(REGISTRY)} exists (a registered list is never rewritten)")
        return 2
    rows = sweep_rows(P)
    reg = {"schema": "m7n_sweeps_addendum_replays_v1", "utc": xc.utc_now(), "purpose": "post-sweep behaviour of the "
           "seven-right-target sweep episodes of the final stochastic tick-0 evaluations; diagnostic only, never gating, "
           "never a re-decision of n3", "criterion": "exact replay (m7n_crossing exactness: digest, consumed ticks, all "
           "actions, break table, first left entry, target count) with the read-only diagnostics of the arm's evaluation "
           "flags; trajectory from native observations only", "no_training": True, "no_new_evaluation": True,
           "analysis_n3_sha256": xc.sha256_file(ANALYSIS), "executable_sha256": xc.sha256_file(nm.load_run(nm.matrix()[0]).executable),
           "episodes": [{k: r[k] for k in ("arm", "seed", "run", "episode_id", "order", "artifact_dir", "native_action_digest",
                                            "breaks", "sweep_tick", "flags")} for r in rows]}
    write_json(REGISTRY, reg)
    print(f"registered {len(reg['episodes'])} episode(s) -> {ec.repo_relative(REGISTRY)}")
    return 0


def post_sweep(ev: Dict[str, Any], steps: Sequence[Dict[str, Any]], sweep_tick: int, geo: fx.StageGeometry) -> Dict[str, Any]:
    d = geo.derived
    face_x, top_y, left_x = float(d["wall_right_face_x"]), float(d["wall_top_y"]), float(d["left_boundary_x"])
    rows = ev["trajectory"]["rows"]        # [consumed_tick, x, y, ground_air_state, status, surface]
    after = [r for r in rows if r[0] is not None and int(r[0]) > sweep_tick and r[1] is not None]
    live_after = [(i, s) for i, s in enumerate(steps) if int(s.get("consumed_tick", -1)) > sweep_tick
                  and xc._live(s.get("observation") or {})]
    if not after:
        return {"steps_after_sweep": 0}
    xs = [float(r[1]) for r in after]
    ys = [float(r[2]) for r in after]
    i_minx = min(range(len(after)), key=lambda i: xs[i])
    i_maxy = max(range(len(after)), key=lambda i: ys[i])
    at_top = [r for r in after if float(r[2]) >= top_y]
    near_face = [r for r in after if float(r[1]) <= face_x + 600.0]
    surfaces: List[Dict[str, Any]] = []
    for r in after:
        g = r[5]
        if g is None:
            continue
        if surfaces and surfaces[-1]["surface"] == g and surfaces[-1]["last_tick"] == int(r[0]) - 1:
            surfaces[-1]["last_tick"] = int(r[0])
        else:
            surfaces.append({"surface": g, "first_tick": int(r[0]), "last_tick": int(r[0]), "x": r[1], "y": r[2]})
    ledge = f"L{d['ledge_line']}"
    last = steps[-1]
    fall = fx.is_fall(last)
    return {
        "steps_after_sweep": len(after), "live_steps_after_sweep": len(live_after),
        "x_at_sweep": next((float(r[1]) for r in rows if r[0] == sweep_tick), None),
        "y_at_sweep": next((float(r[2]) for r in rows if r[0] == sweep_tick), None),
        "min_x_after": {"x": xs[i_minx], "y": ys[i_minx], "tick": after[i_minx][0]},
        "max_y_after": {"x": xs[i_maxy], "y": ys[i_maxy], "tick": after[i_maxy][0]},
        "distance_to_wall_face_at_min_x": xs[i_minx] - face_x,
        "steps_at_or_above_wall_top_after": len(at_top),
        "first_at_or_above_wall_top_after": {"tick": at_top[0][0], "x": at_top[0][1], "y": at_top[0][2]} if at_top else None,
        "steps_within_600_of_wall_face_after": len(near_face),
        "ledge_contacts_after": sum(1 for r in after if r[5] == ledge),
        "left_region_steps_after": sum(1 for r in after if float(r[1]) < left_x),
        "surface_runs_after": surfaces[:40], "surface_runs_after_count": len(surfaces),
        "distinct_surfaces_after": sorted({s["surface"] for s in surfaces}),
        "terminal": ev["terminal"], "native_failure": fall,
        "final_position": {"x": rows[-1][1], "y": rows[-1][2], "tick": rows[-1][0]},
    }


def cmd_replay() -> int:
    import m7f_trace as tr
    from m7_runtime import BATTLESHIP_IMAGE, install_kill_on_close_job, wait_until_no_process
    from m7k_target2 import remove_runtime_with_retry

    if not REGISTRY.is_file():
        print("no registered list: run register first")
        return 2
    install_kill_on_close_job()
    reg = read_json(REGISTRY)
    exe = nm.load_run(nm.matrix()[0]).executable
    if xc.sha256_file(exe) != reg["executable_sha256"]:
        print("executable differs from the registered one; refusing")
        return 2
    geo = xc.geometry()
    results = []
    for k, e in enumerate(reg["episodes"]):
        work = OUT / "replays" / f"{k:02d}_{e['episode_id'][-8:]}"
        if (work / "result.json").is_file():
            results.append(read_json(work / "result.json"))
            continue
        art = REPO_ROOT / e["artifact_dir"]
        acts, _meta = tr.artifact_actions(art)
        src = work / "source_actions.jsonl"
        work.mkdir(parents=True, exist_ok=True)
        src.write_bytes((art / "actions.jsonl").read_bytes())                 # the source actions, preserved beside the replay
        t0 = time.perf_counter()
        trace = tr.run_stepping_trace(f"m7n_sweep_{k}", exe, acts, work / "game", extra_env=dict(e["flags"]), index=9950 + k)
        steps = trace["steps"]
        ev = fx.crossing_evidence(geo, trace["initial"], steps)
        breaks = [(int(b["target_id"]), int(b["consumed_tick"])) for b in ev["targets"]["breaks"]]
        exact = {"consumed_tick_mismatch": trace["consumed_tick_mismatch"], "unsent": trace["unsent"],
                 "digest_equal": trace["action_digest"] == e["native_action_digest"],
                 "breaks_equal_recorded": breaks == [tuple(b) for b in e["breaks"]],
                 "no_left_entry_as_recorded": ev["first_left_entry"] is None}
        exact["ok"] = all(v is True for kk, v in exact.items() if kk != "consumed_tick_mismatch" and kk != "unsent") \
            and exact["consumed_tick_mismatch"] is None and exact["unsent"] == 0
        an = xc.analyse_trace(trace["initial"], steps, geo)
        res = {"episode_id": e["episode_id"], "arm": e["arm"], "seed": e["seed"], "sweep_tick": e["sweep_tick"], "exact": exact,
               "steps": len(steps), "breaks": breaks, "evidence": {kk: ev[kk] for kk in ("max_y", "min_x", "wall_top", "moving_platform",
                                                                                     "terminal", "crossed", "first_left_entry")},
               "post_sweep": post_sweep(ev, steps, int(e["sweep_tick"]), geo),
               "entries": an["entries"], "qualified_crossing": an["qualified_crossing"],
               "trajectory": ev["trajectory"], "wall_s": round(time.perf_counter() - t0, 1)}
        write_json(work / "result.json", res)
        remove_runtime_with_retry(work / "game" / "runtime")
        leftover = wait_until_no_process(BATTLESHIP_IMAGE, timeout=30.0)
        res["leftover_pids"] = leftover
        results.append(res)
        ps = res["post_sweep"]
        print(f"{e['arm']} s{e['seed']} {e['episode_id'][-8:]}: exact {exact['ok']} steps {len(steps)} min_x_after {ps['min_x_after']} "
              f"max_y_after {ps['max_y_after']} top_steps {ps['steps_at_or_above_wall_top_after']} terminal {ps['terminal']['kind']} leak {leftover}")
        if leftover:
            return 1
    summary = {"contract": "m7n_sweeps_addendum_replays_result_v1", "utc": xc.utc_now(), "registry_sha256": xc.sha256_file(REGISTRY),
               "episodes": [{kk: r[kk] for kk in r if kk != "trajectory"} for r in results],
               "all_exact": all(r["exact"]["ok"] for r in results)}
    write_json(OUT / "replays_summary.json", summary)
    print("all exact:", summary["all_exact"])
    return 0 if summary["all_exact"] else 1


def cmd_table(P: Dict[str, Any]) -> int:
    rec = read_json(OUT / "records.json")
    rep = read_json(OUT / "replays_summary.json") if (OUT / "replays_summary.json").is_file() else None
    by_id = {r["episode_id"]: r for r in (rep or {}).get("episodes", [])}
    print("| arm / seed | episode | break order (id@tick) | target 2 | sweep tick | remaining | L | R | end |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in rec["sweeps"]:
        order = " ".join(f"{i}@{t}" for i, t in r["breaks"])
        print(f"| {r['arm']} s{r['seed']} | `{r['episode_id']}` | {order} | {r['t2_tick']} | {r['sweep_tick']} | {r['remaining_actions']} | "
              f"{'yes' if r['L'] else 'no'} | {'yes' if r['R'] else 'no'} | {r['end_reason']} ({r['length']}) |")
    print()
    print(json.dumps(rec["lr_counts"], indent=1))
    if rep:
        print()
        for r in rep["episodes"]:
            ps = r["post_sweep"]
            print(f"{r['arm']} s{r['seed']} {r['episode_id'][-8:]}: exact={r['exact']['ok']} at sweep ({ps['x_at_sweep']}, {ps['y_at_sweep']}); "
                  f"min x after {ps['min_x_after']} (face {ps['distance_to_wall_face_at_min_x']:.0f}); max y after {ps['max_y_after']}; "
                  f"steps >= wall top {ps['steps_at_or_above_wall_top_after']}; within 600 of face {ps['steps_within_600_of_wall_face_after']}; "
                  f"ledge contacts {ps['ledge_contacts_after']}; left steps {ps['left_region_steps_after']}; surfaces {ps['distinct_surfaces_after']} "
                  f"({ps['surface_runs_after_count']} runs); terminal {ps['terminal']['kind']} at {ps['final_position']}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["records", "register", "replay", "table"])
    args = ap.parse_args(argv)
    P = na.params(na.load_rule())
    return {"records": lambda: cmd_records(P), "register": lambda: cmd_register(P), "replay": cmd_replay,
            "table": lambda: cmd_table(P)}[args.command]()


if __name__ == "__main__":
    sys.exit(main())
