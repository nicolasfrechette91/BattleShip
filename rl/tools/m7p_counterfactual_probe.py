#!/usr/bin/env python3
"""M7p scripted counterfactual probe (diagnostic only): the earliest native-actionable second jump in the failed high
L1 flights of the seed-1 geo4 final policy. Modified trajectories are SCRIPTED COUNTERFACTUAL PROBES: never learned
crossings, evaluation successes, demonstrations, curriculum prefixes or training starts. The M7p decision is not touched.

    python rl/tools/m7p_counterfactual_probe.py register   # sources, controls, exact edits, cap, measurements (write-once)
    python rl/tools/m7p_counterfactual_probe.py run        # controls + variants through the unchanged one-tick interface
    python rl/tools/m7p_counterfactual_probe.py report     # source-vs-variant measurements -> results.json

Causal question (registered): in the two failed angled flights where the native fighter had one actionable tick before
the tick the policy used for its second jump, does issuing the second jump one tick earlier (the earliest the native
rules allow with the rest of the recorded sequence unchanged) raise the up-B start height and produce a valid L0
landing, (a) with the up-B input tick unchanged, which lengthens the jump-to-up-B interval by one tick, or (b) with the
up-B press also moved one tick earlier, which keeps the interval? The 3-7 tick gap observed against the two landings
cannot be realised by an isolated edit in any of the four failures (the jump already came at the first actionable tick
after a ~45-tick aerial fireball / late aerial attack), and the other two failures have no actionable tick before their
jump at all; that limitation is reported, no other manoeuvre is substituted. Native rules used (decomp/src/ft/ftcommon):
aerial jump = stick y >= 53 held at an actionable tick (Fall / Jump / JumpAerial / FallSpecial / DamageFall), aerial
up-B = fresh B press (button_tap) with stick y >= 40. Native RNG is not inspected; fixtures / TAS are not read.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parents[1]
for p in (RL_DIR, RL_DIR / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import experiment_config as ec  # noqa: E402
import m7g_fixture as fx  # noqa: E402
import m7n_crossing as xc  # noqa: E402
import m7p_matrix as pm  # noqa: E402

REPO_ROOT = RL_DIR.parent
OUT = REPO_ROOT / "runs" / "m7p" / "addendum" / "counterfactual"
REGISTRY = REPO_ROOT / "docs" / "rl_geometry_scale_m7p_counterfactual_registration.json"
CENSUS_REG = REPO_ROOT / "docs" / "rl_geometry_scale_m7p_walltop_census_registration.json"
CENSUS_TRACES = REPO_ROOT / "runs" / "m7p" / "addendum" / "walltop_census" / "replays"
B, L_TRIG, NONE = 16384, 32, 0
LABEL = "scripted counterfactual probe (diagnostic); not a learned crossing, evaluation success, demonstration, curriculum prefix or training start"

# the four failed angled high flights (episode short id -> takeoff tick, census order)
SOURCES = {"2394f859": {"takeoff": 3093, "order": 59}, "78b3dea2": {"takeoff": 1206, "order": 89},
           "d3a8d7b1": {"takeoff": 1887, "order": 93}, "f5806b84": {"takeoff": 3094, "order": 35}}
# per-source native lock facts (from the census traces): the aerial move that blocked the jump, its last tick, the first
# actionable tick (Fall) before the policy's jump, and the policy's jump tick (all in dt after takeoff)
LOCKS = {"2394f859": {"move": "SpecialAirN (aerial fireball), B at dt 1", "lock_last_dt": 45, "actionable_dt": 46, "jump_dt": 47, "up_b_dt": 97},
         "78b3dea2": {"move": "SpecialAirN (aerial fireball), B at dt 2", "lock_last_dt": 46, "actionable_dt": None, "jump_dt": 47, "up_b_dt": 100},
         "d3a8d7b1": {"move": "AttackAirB (aerial attack), A at dt 10", "lock_last_dt": 48, "actionable_dt": 49, "jump_dt": 50, "up_b_dt": 91},
         "f5806b84": {"move": "SpecialAirN (aerial fireball), B at dt 2", "lock_last_dt": 46, "actionable_dt": None, "jump_dt": 47, "up_b_dt": 93}}
# exact edits: (dt, field, from, to); every other tick of the source sequence is unchanged
VARIANTS = [
    {"id": "V1", "source": "2394f859", "kind": "jump -1, up-B tick unchanged (interval 50 -> 51)",
     "edits": [(46, "stick_y", 0, 80)]},
    {"id": "V2", "source": "2394f859", "kind": "jump -1, up-B -1 (interval 50 kept)",
     "edits": [(46, "stick_y", 0, 80), (95, "buttons", B, NONE), (96, "buttons", L_TRIG, B)]},
    {"id": "V3", "source": "d3a8d7b1", "kind": "jump -1, up-B tick unchanged (interval 41 -> 42)",
     "edits": [(49, "stick_y", 0, 80)]},
    {"id": "V4", "source": "d3a8d7b1", "kind": "jump -1, up-B -1 (interval 41 kept)",
     "edits": [(49, "stick_y", 0, 80), (89, "buttons", B, NONE), (90, "buttons", L_TRIG, B)]},
]
CAP = 4


def read_json(p: Path) -> Any:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def write_json(p: Path, d: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=1, default=str) + "\n", encoding="utf-8")


def census_episode(short: str) -> Dict[str, Any]:
    return next(e for e in read_json(CENSUS_REG)["episodes"] if e["episode_id"].endswith(short))


def source_actions(e: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in (REPO_ROOT / e["artifact_dir"] / "actions.jsonl").read_text(encoding="utf-8").splitlines()]


def apply_edits(rows: List[Dict[str, Any]], takeoff: int, edits: Sequence[Tuple[int, str, int, int]]) -> List[Dict[str, Any]]:
    out = [dict(r) for r in rows]
    by = {int(r["consumed_tick"]): r for r in out}
    for dt, field, old, new in edits:
        r = by[takeoff + dt]
        if int(r[field]) != old:
            raise SystemExit(f"edit precondition failed at dt {dt}: {field} is {r[field]}, expected {old}")
        r[field] = new
    return out


def cmd_register() -> int:
    if REGISTRY.is_file():
        print(f"refused: {ec.repo_relative(REGISTRY)} exists (write-once)")
        return 1
    exp = ec.load_experiment(pm.RunSpec(1, 2).config_path)
    creg = read_json(CENSUS_REG)
    sources = {}
    for short, s in SOURCES.items():
        e = census_episode(short)
        tp = CENSUS_TRACES / f"{e['order']:03d}_{short}" / "trace.json.gz"
        rows = source_actions(e)
        sources[short] = {"episode_id": e["episode_id"], "artifact_dir": e["artifact_dir"], "native_action_digest": e["native_action_digest"],
                          "artifact_actions_sha256": e["artifact_actions_sha256"], "length": e["length"], "takeoff_tick": s["takeoff"],
                          "census_trace": {"path": ec.repo_relative(tp), "sha256": xc.sha256_file(tp)}, "lock": LOCKS[short],
                          "source_inputs_at_edit_ticks": {str(dt): {k: rows[s["takeoff"] + dt][k] for k in ("buttons", "stick_x", "stick_y", "consumed_tick")}
                                                          for dt in sorted({d for v in VARIANTS if v["source"] == short for d, *_ in v["edits"]} | {LOCKS[short]["jump_dt"], LOCKS[short]["up_b_dt"]})}}
    variants = []
    for v in VARIANTS:
        e = census_episode(v["source"])
        rows = source_actions(e)
        edited = apply_edits(rows, SOURCES[v["source"]]["takeoff"], v["edits"])
        changed = [i for i, (a, b) in enumerate(zip(rows, edited)) if a != b]
        variants.append({**v, "edits": [{"dt": dt, "tick": SOURCES[v["source"]]["takeoff"] + dt, "field": f, "from": a, "to": b} for dt, f, a, b in v["edits"]],
                         "ticks_changed": changed, "ticks_unchanged": len(rows) - len(changed), "label": LABEL})
    reg = {"contract": "m7p_counterfactual_probe_v1", "utc": xc.utc_now(), "label": LABEL,
           "causal_question": __doc__.split("Causal question (registered):", 1)[1].split("Native rules used", 1)[0].strip(),
           "native_rules": {"aerial_jump": "ftCommonJumpAerial*: interrupt checked from Fall / Jump / JumpAerial / FallSpecial / DamageFall; fires when "
                                           "stick_range.y >= FTCOMMON_JUMPAERIAL_STICK_RANGE_MIN (53) is HELD (or a C button is held); not checked from "
                                           "SpecialAirN or aerial attacks",
                            "aerial_up_b": "ftcommonspecialair.c: button_tap & B (fresh press) and stick_range.y >= FTCOMMON_SPECIALHI_STICK_RANGE_MIN (40)",
                            "input_semantics": "one native tick per submitted controller state; edges are computed natively from consecutive states, so a "
                                               "button kept from the previous tick is a hold, not a tap"},
           "limitation": "the registered 'earlier timings derived from the observed gap' (3-7 ticks) cannot be realised by an isolated edit: in all "
                         "four failures the second jump already occurred at the first tick the native fighter could jump after its aerial fireball / "
                         "attack; reaching dt 40-44 would require removing 17-20 B presses (no fireball) and would re-time the jump by the residual "
                         "stick sequence, i.e. a different manoeuvre, which is not done. 78b3dea2 and f5806b84 have no actionable tick before "
                         "their jump (SpecialAirN ends at dt 46, jump at 47): no valid isolated edit exists, no variant is run for them. The "
                         "maximum isolated shift is one tick, in 2394f859 (Fall at dt 46) and d3a8d7b1 (Fall at dt 49).",
           "preservation": "stick x is never changed (only stick y 0 -> 80 at the one Fall tick, so the horizontal input is kept); buttons at the "
                           "jump tick are unchanged (B is a hold there, not a tap, so no up-B is triggered); variants (b) release B one tick "
                           "before the moved press and replace the L trigger of the following tick by B, giving one fresh B tap one tick earlier; "
                           "every other tick of the source sequence is submitted unchanged to its end (fall / horizon)",
           "cap": {"variants": CAP, "controls": 2, "adaptive_search": False, "additional_attempts": False},
           "expectation_before_running": "from the fixed angled up-B rise (+1361.3 from the press) and the observed fall rate at the press (about "
                                         "-30 per tick): variants (a) start the up-B about one falling tick lower and gain roughly nothing; variants (b) "
                                         "start about 30 higher (2394f859 apex ~3020, above the top; d3a8d7b1 apex ~2980, below); whether an apex above "
                                         "3000 yields a landing also depends on x clearance and contact, which is what the probe measures",
           "measurements": ["native second jump: JumpAerialF/B onset tick and jumps_used transition", "up-B onset tick and fighter y (and launch tick)",
                            "apex tick, x, y", "contact sequence: ticks with x clamped at -1050.0 and right-wall id 12; floor id changes",
                            "first tick with y >= 3000 over the ledge span", "valid L0 landing: grounded with native floor line 0 and classify_ground L0",
                            "first divergence tick from the source trace; subsequent outcome (landing surface / fall / horizon)"],
           "checkpoint_not_used": "no policy is evaluated; the checkpoint is not loaded",
           "executable_sha256": xc.sha256_file(exp.executable), "flags": dict(exp.extra_env, **pm.DIAG_FLAG),
           "census_registration_sha256": xc.sha256_file(CENSUS_REG), "sources": sources, "controls": ["2394f859", "d3a8d7b1"], "variants": variants,
           "exclusions": ["no policy evaluation", "no training", "no reward / observation change", "fixtures and TAS not read", "no native RNG inspection"]}
    write_json(REGISTRY, reg)
    print(f"registered {len(variants)} variants + {len(reg['controls'])} controls -> {ec.repo_relative(REGISTRY)}")
    return 0


def _run_one(name: str, e: Dict[str, Any], rows: List[Dict[str, Any]], exe: Path, flags: Dict[str, str], index: int) -> Dict[str, Any]:
    import m7f_trace as tr
    from m7k_target2 import remove_runtime_with_retry

    acts = [(int(r["buttons"]), int(r["stick_x"]), int(r["stick_y"]), int(r["consumed_tick"])) for r in rows]
    work = OUT / "runs" / name
    work.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    trace = tr.run_stepping_trace(f"m7p_cf_{name}", exe, acts, work / "game", extra_env=flags, index=index)
    digest = tr.action_digest(acts[:len(trace["steps"])], [s["consumed_tick"] for s in trace["steps"]])
    with gzip.open(work / "trace.json.gz", "wt", encoding="utf-8") as fp:
        json.dump({"name": name, "label": LABEL, "episode_id": e["episode_id"], "digest": digest, "initial": trace["initial"], "steps": trace["steps"]}, fp)
    res = {"name": name, "label": LABEL, "source": e["episode_id"], "steps": len(trace["steps"]), "unsent": trace["unsent"],
           "consumed_tick_mismatch": trace["consumed_tick_mismatch"], "digest": digest, "wall_s": round(time.perf_counter() - t0, 1),
           "trace": ec.repo_relative(work / "trace.json.gz"), "runtime_cleanup": remove_runtime_with_retry(work / "game" / "runtime")}
    write_json(work / "result.json", res)
    print(f"{name}: {len(trace['steps'])} steps, mismatch {trace['consumed_tick_mismatch']}, unsent {trace['unsent']}, {res['wall_s']} s", flush=True)
    return res


def cmd_run() -> int:
    from m7_runtime import BATTLESHIP_IMAGE, install_kill_on_close_job, list_processes_named, wait_until_no_process

    if not REGISTRY.is_file():
        print("no registry")
        return 1
    if (OUT / "runs_summary.json").is_file():
        print("refused: the probe already ran (no additional attempts)")
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
    results = []
    k = 0
    for short in reg["controls"]:
        e = census_episode(short)
        if xc.sha256_file(REPO_ROOT / e["artifact_dir"] / "actions.jsonl") != e["artifact_actions_sha256"]:
            print("artifact changed; stopping")
            return 1
        r = _run_one(f"control_{short}", e, source_actions(e), exe, dict(reg["flags"]), 9700 + k)
        r["control"] = True
        r["exact"] = r["consumed_tick_mismatch"] is None and r["unsent"] == 0 and r["digest"] == e["native_action_digest"] and r["steps"] == e["length"]
        results.append(r)
        k += 1
    for v in reg["variants"][:CAP]:
        e = census_episode(v["source"])
        rows = apply_edits(source_actions(e), SOURCES[v["source"]]["takeoff"], [(d["dt"], d["field"], d["from"], d["to"]) for d in v["edits"]])
        r = _run_one(f"{v['id']}_{v['source']}", e, rows, exe, dict(reg["flags"]), 9700 + k)
        r.update({"control": False, "variant": v["id"], "kind": v["kind"], "edits": v["edits"]})
        results.append(r)
        k += 1
    leftover = wait_until_no_process(BATTLESHIP_IMAGE, timeout=30.0)
    write_json(OUT / "runs_summary.json", {"contract": "m7p_counterfactual_probe_runs_v1", "utc": xc.utc_now(), "registry_sha256": xc.sha256_file(REGISTRY),
                                          "label": LABEL, "results": results, "leftover_pids": leftover})
    return 0 if not leftover else 1


# -- measurements (pure) -----------------------------------------------------------------------------------------------


def measure(trace: Dict[str, Any], takeoff: int, geo: fx.StageGeometry) -> Dict[str, Any]:
    steps = trace["steps"]
    by = {int(s["consumed_tick"]): s for s in steps}
    tbl = read_json(RL_DIR / "data" / "m7n_action_classes_v1.json")
    names = {int(k): v for k, v in tbl["common_names"].items()}
    names.update({int(k): v for k, v in tbl["characters"]["mario"]["names"].items()})

    def o(t):
        return by[t]["observation"]

    def f(t):
        return by[t]["spatial"]["fighter"]

    def live(t):
        return t in by and int(o(t).get("fighter_valid", 0)) == 1 and int(o(t).get("btt_active", 0)) == 1

    # the flight: from the takeoff tick to the first grounded step after it
    t = takeoff + 1
    while live(t) and int(o(t)["ground_air_state"]) == 1:
        t += 1
    land_t = t if live(t) else None
    flight = [tt for tt in range(takeoff + 1, (land_t if land_t is not None else t)) if live(tt)]
    jump = next((tt for tt in flight if "JumpAerial" in names.get(int(o(tt)["fighter_status_id"]), "")), None)
    j2 = next((tt for tt in flight if int(o(tt)["jumps_used"]) >= 2), None)
    upb = next((tt for tt in flight if int(o(tt)["fighter_status_id"]) in (225, 226)), None)
    launch = next((tt for tt in flight if upb is not None and tt > upb and float(o(tt)["air_velocity_y"]) > 100.0), None)
    apex_t = max(flight, key=lambda tt: float(o(tt)["position_y"])) if flight else None
    clamp = [tt for tt in flight if float(o(tt)["position_x"]) == -1050.0 and f(tt)["rwall_line_id"] == 12]
    top = next((tt for tt in flight if float(o(tt)["position_y"]) >= 3000.0), None)
    over = next((tt for tt in flight if float(o(tt)["position_y"]) >= 3000.0 and float(o(tt)["position_x"]) <= -1200.0), None)
    landing = None
    if land_t is not None:
        surf = fx.classify_ground(geo, o(land_t))
        landing = {"tick": land_t, "x": round(float(o(land_t)["position_x"]), 1), "y": round(float(o(land_t)["position_y"]), 1),
                   "native_floor_line": f(land_t)["floor_line_id"], "surface": surf, "valid_L0": surf == "L0" and f(land_t)["floor_line_id"] == 0}
    an = xc.analyse_trace(trace["initial"], steps, geo)
    fall = an["native_failure_step"]
    pt = lambda tt: {"tick": tt, "dt": tt - takeoff, "x": round(float(o(tt)["position_x"]), 1), "y": round(float(o(tt)["position_y"]), 1),  # noqa: E731
                     "vy": round(float(o(tt)["air_velocity_y"]), 1), "status": names.get(int(o(tt)["fighter_status_id"]), "?"), "jumps_used": int(o(tt)["jumps_used"])}
    return {"second_jump": pt(jump) if jump else None, "jumps_used_2_at": j2, "up_b_onset": pt(upb) if upb else None, "up_b_launch": pt(launch) if launch else None,
            "interval_jump_to_up_b": (upb - jump) if (upb and jump) else None, "apex": pt(apex_t) if apex_t else None,
            "clamp_ticks": clamp, "clamp_y": [round(float(o(tt)["position_y"]), 1) for tt in clamp], "first_y_ge_3000": pt(top) if top else None,
            "first_over_ledge_span": pt(over) if over else None, "landing": landing, "airborne_ticks": len(flight),
            "episode_end": {"steps": len(steps), "native_failure_step": fall, "left_entries": len(an["entries"]), "qualified_crossing": an["qualified_crossing"],
                            "breaks": an["breaks"]}}


def cmd_report() -> int:
    reg = read_json(REGISTRY)
    runs = read_json(OUT / "runs_summary.json")
    geo = xc.geometry()
    out = []
    for r in runs["results"]:
        short = r["source"][-8:]
        trace = json.load(gzip.open(REPO_ROOT / r["trace"], "rt", encoding="utf-8"))
        src = json.load(gzip.open(REPO_ROOT / reg["sources"][short]["census_trace"]["path"], "rt", encoding="utf-8"))
        m = measure(trace, SOURCES[short]["takeoff"], geo)
        div = next((i for i, (a, b) in enumerate(zip(trace["steps"], src["steps"])) if a["observation"] != b["observation"]), None)
        m["first_divergence_tick"] = div
        m["source_measure"] = measure(src, SOURCES[short]["takeoff"], geo) if not r["control"] else None
        out.append({**{k: r[k] for k in ("name", "label", "source", "steps", "consumed_tick_mismatch", "unsent", "control")},
                    "variant": r.get("variant"), "kind": r.get("kind"), "edits": r.get("edits"), "exact_control": r.get("exact"), "measure": m})
    write_json(OUT / "results.json", {"contract": "m7p_counterfactual_probe_results_v1", "utc": xc.utc_now(), "registry_sha256": xc.sha256_file(REGISTRY),
                                      "label": LABEL, "results": out})
    for x in out:
        m = x["measure"]
        print(f"\n== {x['name']} ({x['kind'] or 'control'}) exact_control={x.get('exact_control')} divergence={m['first_divergence_tick']}")
        for k in ("second_jump", "up_b_onset", "up_b_launch", "interval_jump_to_up_b", "apex", "clamp_ticks", "clamp_y", "first_y_ge_3000", "first_over_ledge_span", "landing", "episode_end"):
            print(f"  {k:22s} {json.dumps(m[k], default=str)}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["register", "run", "report"])
    a = ap.parse_args(argv)
    return {"register": cmd_register, "run": cmd_run, "report": cmd_report}[a.command]()


if __name__ == "__main__":
    sys.exit(main())
