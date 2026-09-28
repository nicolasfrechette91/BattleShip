#!/usr/bin/env python3
"""M7p evidence addendum: the two left-side candidates of the seed-1 geo4 final evaluation (the campaign decision is NOT
re-decided). Lives under rl/tools (outside the frozen M7p fingerprint set); reads the recorded campaign evidence; writes
below runs/m7p/addendum/crossings and the write-once registered replay list in docs/.

    python rl/tools/m7p_crossing_addendum.py register   # the two episodes (ids, digests, artifacts, flags); refused if it exists
    python rl/tools/m7p_crossing_addendum.py replay     # minimal exact fresh-process replays with every raw reply kept
    python rl/tools/m7p_crossing_addendum.py facts      # the per-episode facts (takeoff, jumps, platform, entry, landing, end)

The replay is the minimal one the addendum needs: the preserved records hold the actions, break ticks, entry / landing /
terminal facts and the takeoff surface, but not the jumps available, the moving-platform state or the height path
between takeoff and entry. Native gameplay is authoritative; native RNG is never inspected; fixtures / TAS are not read.
"""
from __future__ import annotations

import argparse
import gzip
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
import m7n_crossing as xc  # noqa: E402
import m7p_matrix as pm  # noqa: E402

REPO_ROOT = RL_DIR.parent
OUT = REPO_ROOT / "runs" / "m7p" / "addendum" / "crossings"
REGISTRY = REPO_ROOT / "docs" / "rl_geometry_scale_m7p_crossing_replays.json"
CROSSING_DOC = REPO_ROOT / "runs" / "m7p" / "campaign" / "_clears" / "m7p_geo4_s1" / "final" / "crossing_verification.json"
EVAL = REPO_ROOT / "runs" / "m7p" / "campaign" / "_eval" / "m7p_geo4_s1" / "final" / "stochastic" / "evaluation.json"
CHECKPOINT = REPO_ROOT / "runs" / "m7p" / "campaign" / "m7p_geo4_s1" / "final"
STICK = {(0, 0): "neutral", (80, 0): "R", (80, 80): "UR", (0, 80): "U", (-80, 80): "UL", (-80, 0): "L", (-80, -80): "DL", (0, -80): "D", (80, -80): "DR"}
BTN = {0: "none", 32768: "A", 16384: "B", 8: "C-up", 2: "C-left", 32: "L", 16: "R", 8192: "Z"}


def read_json(p: Path) -> Any:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def write_json(p: Path, d: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=1, default=str) + "\n", encoding="utf-8")


def candidates() -> List[Dict[str, Any]]:
    doc = read_json(CROSSING_DOC)
    ev = read_json(EVAL)
    out = []
    for r in doc["records"]:
        row = next(e for e in ev["episodes"] if e["episode_id"] == r["episode_id"])
        an = r["analysis"]
        out.append({"episode_id": r["episode_id"], "native_action_digest": r["native_action_digest"], "artifact_dir": row["artifact_dir"],
                    "artifact_actions_sha256": xc.sha256_file(REPO_ROOT / row["artifact_dir"] / "actions.jsonl"),
                    "replay_work_dir": ec.repo_relative(Path(r["work"])), "reasons": r["reasons"], "exact": r["exact"],
                    "qualified_crossing": r["qualified_crossing"], "verified_left_target_break": r["verified_left_target_break"],
                    "breaks": an["breaks"], "approach_surface": an["approach_surface"], "first_left_entry": an["first_left_entry"],
                    "entries": an["entries"], "landings": an["landings"][:1], "terminal": an["terminal"], "route": an["route"],
                    "rank": row["rank"], "worker_episode": row["worker_episode"], "length": row["length"], "end_reason": row["end_reason"]})
    return out


def cmd_register() -> int:
    if REGISTRY.is_file():
        print(f"refused: {ec.repo_relative(REGISTRY)} exists (a registered list is never rewritten)")
        return 1
    ck = read_json(CHECKPOINT / "checkpoint.json")
    exp = ec.load_experiment(pm.RunSpec(1, 2).config_path)
    reg = {"contract": "m7p_crossing_addendum_replays_v1", "utc": xc.utc_now(),
           "purpose": "minimal exact replays (raw replies kept) of the two seed-1 geo4 final left-side candidates, to report jumps available at "
                      "takeoff, moving-platform state and the height path; the campaign decision (failure_regression) is not re-decided",
           "checkpoint": {"path": ec.repo_relative(CHECKPOINT), "run_id": ck["run_id"], "num_timesteps": ck["num_timesteps"],
                          "files_sha256": {f: xc.sha256_file(CHECKPOINT / f) for f in ("model.zip", "vecnormalize.pkl", "checkpoint.json")},
                          "observation": (ck.get("contracts") or {}).get("policy_observation_contract"),
                          "observation_sha256": (ck.get("contracts") or {}).get("policy_observation_contract_sha256")},
           "executable_sha256": xc.sha256_file(exp.executable), "flags": dict(exp.extra_env, **pm.DIAG_FLAG),
           "crossing_document": {"path": ec.repo_relative(CROSSING_DOC), "sha256": xc.sha256_file(CROSSING_DOC)},
           "evaluation": {"path": ec.repo_relative(EVAL), "sha256": xc.sha256_file(EVAL)},
           "episodes": candidates(), "exclusions": ["fixtures and TAS not read", "no native RNG inspection", "no policy evaluation"]}
    write_json(REGISTRY, reg)
    print(f"registered {len(reg['episodes'])} episode(s) -> {ec.repo_relative(REGISTRY)}")
    return 0


def cmd_replay() -> int:
    import m7f_trace as tr
    from m7_runtime import BATTLESHIP_IMAGE, install_kill_on_close_job, list_processes_named, wait_until_no_process

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
    results = []
    for k, e in enumerate(reg["episodes"]):
        art = REPO_ROOT / e["artifact_dir"]
        if xc.sha256_file(art / "actions.jsonl") != e["artifact_actions_sha256"]:
            print(f"{e['episode_id']}: artifact changed since registration")
            return 1
        rows = [json.loads(l) for l in (art / "actions.jsonl").read_text(encoding="utf-8").splitlines()]
        acts = [(int(r["buttons"]), int(r["stick_x"]), int(r["stick_y"]), int(r["consumed_tick"])) for r in rows]
        work = OUT / "replays" / f"{k:02d}_{e['episode_id'][-8:]}"
        work.mkdir(parents=True, exist_ok=True)
        t0 = time.perf_counter()
        trace = tr.run_stepping_trace(f"m7p_crossing_{k}", exe, acts, work / "game", extra_env=dict(reg["flags"]), index=9970 + k)
        digest = tr.action_digest(acts[:len(trace["steps"])], [s["consumed_tick"] for s in trace["steps"]])
        exact = trace["consumed_tick_mismatch"] is None and trace["unsent"] == 0 and digest == e["native_action_digest"]
        with gzip.open(work / "trace.json.gz", "wt", encoding="utf-8") as fp:
            json.dump({"episode_id": e["episode_id"], "exact": exact, "digest": digest, "initial": trace["initial"], "steps": trace["steps"]}, fp)
        results.append({"episode_id": e["episode_id"], "exact": exact, "steps": len(trace["steps"]), "unsent": trace["unsent"],
                        "consumed_tick_mismatch": trace["consumed_tick_mismatch"], "trace": ec.repo_relative(work / "trace.json.gz"),
                        "wall_s": round(time.perf_counter() - t0, 1)})
        print(f"{e['episode_id']}: exact {exact}, {len(trace['steps'])} steps, {results[-1]['wall_s']} s")
        from m7k_target2 import remove_runtime_with_retry
        remove_runtime_with_retry(work / "game" / "runtime")
    leftover = wait_until_no_process(BATTLESHIP_IMAGE, timeout=30.0)
    write_json(OUT / "replays_summary.json", {"contract": "m7p_crossing_addendum_replays_result_v1", "utc": xc.utc_now(),
                                              "registry_sha256": xc.sha256_file(REGISTRY), "results": results, "leftover_pids": leftover})
    return 0 if all(r["exact"] for r in results) and not leftover else 1


def _obs(step: Dict[str, Any]) -> Dict[str, Any]:
    return step["observation"]


def facts_for(e: Dict[str, Any], trace: Dict[str, Any], geo: fx.StageGeometry) -> Dict[str, Any]:
    import m7g_spatial as ms
    import m7n_entity as ne

    steps = trace["steps"]
    take = int(e["approach_surface"]["consumed_tick"])
    entry = int(e["first_left_entry"]["consumed_tick"])
    land = int(e["landings"][0]["consumed_tick"]) if e["landings"] else None
    end = int(e["terminal"]["last_consumed_tick"])
    breaks = [(int(t), int(c)) for t, c in e["breaks"]]

    def remaining(t: int) -> int:
        return 10 - sum(1 for _, c in breaks if c <= t)

    def state(t: int) -> Dict[str, Any]:
        s = steps[t]
        o = _obs(s)
        sp = ms.spatial_of(s, expect_lines=False)
        en = ne.entity_of(s)
        g2 = sp.group(2)
        return {"consumed_tick": t, "x": round(float(o["position_x"]), 1), "y": round(float(o["position_y"]), 1),
                "grounded": int(o["ground_air_state"]) == 0, "surface": fx.classify_ground(geo, o), "status_id": int(o["fighter_status_id"]),
                "jumps_used": int(o["jumps_used"]), "jumps_max": int(en.fighter.jumps_max), "air_velocity": [round(float(o["air_velocity_x"]), 1), round(float(o["air_velocity_y"]), 1)],
                "platform": {"y": round(float(g2.translate[1]), 1), "vy": round(float(g2.speed[1]), 2), "x": round(float(g2.translate[0]), 1)} if g2 else None,
                "targets_remaining": remaining(t)}

    # the last grounded step before entry, the jump-squat onset and the first airborne step after the takeoff surface
    last_ground = max(t for t in range(take, entry) if int(_obs(steps[t])["ground_air_state"]) == 0)
    first_air = last_ground + 1
    # height path: max y and the first tick above the wall top, between takeoff and entry; special_hi (up-B) onsets
    ys = [(t, float(_obs(steps[t])["position_y"]), float(_obs(steps[t])["position_x"])) for t in range(first_air, entry + 1)]
    max_t, max_y, max_x = max(ys, key=lambda z: z[1])
    over_top = next((t for t, y, x in ys if y >= 3000.0), None)
    statuses = [int(_obs(steps[t])["fighter_status_id"]) for t in range(first_air, entry + 1)]
    upb_onsets = [first_air + i for i, s in enumerate(statuses) if s in (225, 226) and (i == 0 or statuses[i - 1] not in (225, 226))]
    dj = next((t for t in range(first_air, entry + 1) if int(_obs(steps[t])["jumps_used"]) >= 2), None)
    return {"takeoff_surface_step": state(take), "last_grounded_before_entry": state(last_ground), "first_airborne": state(first_air),
            "double_jump_used_at": dj, "up_b_onsets_airborne": upb_onsets, "first_at_or_above_wall_top": over_top,
            "apex_before_entry": {"consumed_tick": max_t, "x": round(max_x, 1), "y": round(max_y, 1)}, "entry": state(entry),
            "landing": state(land) if land is not None else None, "termination": state(end) | {"kind": e["terminal"]["kind"]},
            "steps_takeoff_to_entry": entry - last_ground, "targets_remaining": {"takeoff": remaining(take), "entry": remaining(entry),
                                                                                 "landing": remaining(land) if land is not None else None, "termination": remaining(end)}}


def cmd_facts() -> int:
    reg = read_json(REGISTRY)
    geo = xc.geometry()
    out = {}
    for k, e in enumerate(reg["episodes"]):
        tp = OUT / "replays" / f"{k:02d}_{e['episode_id'][-8:]}" / "trace.json.gz"
        trace = json.load(gzip.open(tp, "rt", encoding="utf-8"))
        f = facts_for(e, trace, geo)
        f["exact_replay"] = trace["exact"]
        out[e["episode_id"]] = f
        print(f"\n== {e['episode_id']} (exact replay {trace['exact']})")
        print(json.dumps(f, indent=1))
    write_json(OUT / "facts.json", {"utc": xc.utc_now(), "registry_sha256": xc.sha256_file(REGISTRY), "facts": out})
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["register", "replay", "facts"])
    args = ap.parse_args(argv)
    return {"register": cmd_register, "replay": cmd_replay, "facts": cmd_facts}[args.command]()


if __name__ == "__main__":
    sys.exit(main())
