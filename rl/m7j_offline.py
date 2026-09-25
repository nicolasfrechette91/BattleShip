#!/usr/bin/env python3
"""M7j offline check of the candidate btt_reward_v3 (no training; no recorded file is modified).

    python rl/m7j_offline.py census  --out runs/m7j/offline/<name>
    python rl/m7j_offline.py replay  --out runs/m7j/offline/<name>
    python rl/m7j_offline.py ranking --out runs/m7j/offline/<name>
    python rl/m7j_offline.py all     --out runs/m7j/offline/<name>

census   every recorded tick-0 evaluation episode of Phase K and M7h (eval_metrics: target identity, first left
         entry) and every recorded training row: v3 - v2 per episode where it is exact without a replay, and the rows
         that need identity (>= 7 targets) listed for the replay set.
replay   the pre-declared REPLAY_SET, each episode replayed from tick 0 in a fresh process with the target diagnostic
         on (m7f_trace.run_stepping_trace, the same flags as the M7f/M7h verifiers); gameplay must reproduce the
         recorded native action digest and consumed ticks exactly; then v2 and v3 are computed per step by
         btt_rewards.reward_step and btt_reward_v3.RouteRewardState on the SAME replies.
ranking  closed-form returns of outcome classes under v2 and v3, and synthetic loophole sequences through the v3 state
         machine. Every synthetic case is labelled `synthetic`; nothing synthetic is an observed trajectory.

Native RNG state is never read, logged, compared or hashed. The crossing fixtures are not read here.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parent
REPO_ROOT = RL_DIR.parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import btt_reward_v3 as v3  # noqa: E402
from btt_rewards import REWARD_V2, REWARD_V3, reward_step  # noqa: E402

RIGHT = set(REWARD_V3.right_target_ids)
LEFT = {1, 6, 8}
EARLY_SWEEP_LAST_TICK = 2699        # descriptive: a sweep on or before consumed tick 2,699 leaves >= 900 ticks
EXECUTABLE = REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"
EXPECTED_EXE_SHA = "1e7c62a05a9397fb4ef1d404d85a793cd01c4dbdc187068e3a63890cb5cbeb97"
REPLAY_FLAGS = {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1", "SSB64_RL_TARGET_DIAG": "1"}
EVAL_FAMILIES = {
    "phase_k": ("runs/m7g_k/_eval", ("m7g_s0_v1", "m7g_s1_v1", "m7g_s2_v1", "m7g_s0_v2", "m7g_s1_v2", "m7g_s2_v2",
                                     "random_baseline")),
    "m7h": ("runs/m7h/campaign/_eval", ("m7h_f_s0", "m7h_f_s1", "m7h_f_s2")),
}
TRAINING_ROOTS = ("runs/m7a_pilot_n5", "runs/m7d", "runs/m7e", "runs/m7g_k", "runs/m7h/campaign")
M7H_LEFT = "runs/m7h/campaign/{run}/curriculum/left_episodes.jsonl"

# Pre-declared before the first replay (2026-09-25). kind: tas | artifact | left_record.
REPLAY_SET: Tuple[Dict[str, Any], ...] = (
    {"key": "tas", "kind": "tas", "why": "the 7.43 s TAS clear (route: seven right targets, then over the wall)"},
    {"key": "m7h_f_s2_final_9a130d1f", "kind": "artifact", "why": "the only seven-right tick-0 evaluation episode (late)",
     "path": "runs/m7h/campaign/_eval/m7h_f_s2/final/stochastic/workers/w*/artifacts/episode_20260925T020610Z_9a130d1f"},
    {"key": "m7a_pilot_50bbb545", "kind": "artifact", "why": "the only tick-0 TRAINING episode with seven targets (v1 era)",
     "path": "runs/m7a_pilot_n5/workers/w01/artifacts/episode_20260922T021311Z_50bbb545"},
    {"key": "m7h_s1_83112a8c", "kind": "left_record", "run": "m7h_f_s1", "id": "83112a8c",
     "why": "the verified M7h over-wall crossing with a left-floor landing, then a fall"},
    {"key": "m7h_s1_438d5fcb", "kind": "left_record", "run": "m7h_f_s1", "id": "438d5fcb",
     "why": "over-wall crossing, airborne only, fall"},
    {"key": "m7h_s2_56a1af09", "kind": "left_record", "run": "m7h_f_s2", "id": "56a1af09",
     "why": "under-stage (off-stage) left entry, fall"},
    {"key": "m7h_s1_79be8064", "kind": "left_record", "run": "m7h_f_s1", "id": "79be8064",
     "why": "reproduced left start, left target 8, fall (7 targets with the prefix)"},
    {"key": "m7h_s1_d9c5249d", "kind": "left_record", "run": "m7h_f_s1", "id": "d9c5249d",
     "why": "reproduced left start, left target 6, fall (7 targets with the prefix)"},
    {"key": "m7h_s1_67d3898c", "kind": "left_record", "run": "m7h_f_s1", "id": "67d3898c",
     "why": "7 targets with the prefix, fall"},
    {"key": "m7h_s2_9052fc6d", "kind": "artifact", "why": "7 targets with the prefix, horizon",
     "path": "runs/m7h/campaign/m7h_f_s2/workers/w02/artifacts/episode_20260924T221344Z_9052fc6d"},
    {"key": "m7h_f_s0_final_det0", "kind": "eval_order", "run": "m7h_f_s0", "mode": "deterministic", "select": "order0",
     "why": "ordinary partial run: final deterministic"},
    {"key": "m7h_f_s1_final_det0", "kind": "eval_order", "run": "m7h_f_s1", "mode": "deterministic", "select": "order0",
     "why": "ordinary partial run: final deterministic"},
    {"key": "m7h_f_s2_final_det0", "kind": "eval_order", "run": "m7h_f_s2", "mode": "deterministic", "select": "order0",
     "why": "ordinary partial run: final deterministic"},
    {"key": "m7h_f_s0_final_sto0", "kind": "eval_order", "run": "m7h_f_s0", "mode": "stochastic", "select": "order0",
     "why": "ordinary partial run: first final stochastic episode"},
    {"key": "m7h_f_s1_final_sto0", "kind": "eval_order", "run": "m7h_f_s1", "mode": "stochastic", "select": "order0",
     "why": "ordinary partial run: first final stochastic episode"},
    {"key": "m7h_f_s2_final_sto0", "kind": "eval_order", "run": "m7h_f_s2", "mode": "stochastic", "select": "order0",
     "why": "ordinary partial run: first final stochastic episode"},
    {"key": "m7h_f_s0_final_fall0", "kind": "eval_order", "run": "m7h_f_s0", "mode": "stochastic", "select": "first_fall",
     "why": "ordinary partial run: first final stochastic fall"},
    {"key": "m7h_f_s2_final_fall0", "kind": "eval_order", "run": "m7h_f_s2", "mode": "stochastic", "select": "first_fall",
     "why": "ordinary partial run: first final stochastic fall"},
)


def read_json(p: Path) -> Any:
    with open(p, "r", encoding="utf-8") as fp:
        return json.load(fp)


def write_json(p: Path, data: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        raise FileExistsError(f"{p} exists (never overwritten)")
    with open(p, "w", encoding="utf-8", newline="\n") as fp:
        json.dump(data, fp, indent=1, sort_keys=False)
        fp.write("\n")


def jsonl(p: Path) -> List[Dict[str, Any]]:
    out = []
    with open(p, "r", encoding="utf-8") as fp:
        for line in fp:
            if line.strip():
                out.append(json.loads(line))
    return out


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# -- census ----------------------------------------------------------------------------------------------------------


def sweep_from_breaks(breaks: Sequence[Mapping[str, Any]]) -> Optional[int]:
    """Consumed tick of the step on which the seventh right target broke (None without a sweep)."""
    seen = set()
    for b in sorted(breaks, key=lambda b: (int(b["consumed_tick"]), int(b.get("break_order", 0)))):
        if int(b["target_id"]) in RIGHT:
            seen.add(int(b["target_id"]))
            if seen == RIGHT:
                return int(b["consumed_tick"])
    return None


def census_eval() -> Dict[str, Any]:
    fam_out: Dict[str, Any] = {}
    differing: List[Dict[str, Any]] = []
    problems: List[str] = []
    for fam, (root, runs) in EVAL_FAMILIES.items():
        agg = {"episodes": 0, "labels": 0, "left_entries": 0, "left_target_breaks": 0, "sweeps": 0, "early_sweeps": 0,
               "v3_equal_v2": 0, "v3_differs": 0, "target2": 0, "static6": 0, "falls": 0, "horizon": 0, "clears": 0,
               "per_run": {}}
        for run in runs:
            files = sorted(glob.glob(str(REPO_ROOT / root / run / "*" / "*" / "evaluation.json")))
            if run == "random_baseline":
                files = sorted(glob.glob(str(REPO_ROOT / root / run / "*" / "evaluation.json")))
            n_run = 0
            for f in files:
                d = read_json(Path(f))
                agg["labels"] += 1
                if (d.get("reward_contract") or {}).get("contract") != "btt_reward_v2":
                    problems.append(f"{f}: reward contract {(d.get('reward_contract') or {}).get('contract')}")
                for e in d.get("episodes") or []:
                    em = e.get("eval_metrics") or {}
                    if "target_breaks" not in em or em.get("ok") is not True:
                        problems.append(f"{f}: {e.get('episode_id')} without a complete eval_metrics record")
                        continue
                    n_run += 1
                    agg["episodes"] += 1
                    ids = {int(b["target_id"]) for b in em["target_breaks"]}
                    agg["target2"] += 2 in ids
                    agg["static6"] += (RIGHT - {2}) <= ids
                    agg["left_target_breaks"] += bool(ids & LEFT)
                    agg["falls"] += e.get("end_reason") == "fall"
                    agg["horizon"] += e.get("end_reason") == "horizon"
                    agg["clears"] += bool(e.get("cleared"))
                    if em.get("first_left_entry") is not None:
                        agg["left_entries"] += 1
                        problems.append(f"{f}: {e['episode_id']} has a left entry: needs a replay, not a census row")
                        continue
                    t = sweep_from_breaks(em["target_breaks"])
                    delta = 0.0
                    if t is not None:
                        agg["sweeps"] += 1
                        agg["early_sweeps"] += t <= EARLY_SWEEP_LAST_TICK
                        delta = REWARD_V3.right_sweep_bonus + v3.sweep_timing(t)
                    if delta:
                        agg["v3_differs"] += 1
                        differing.append({"family": fam, "file": os.path.relpath(f, REPO_ROOT).replace("\\", "/"),
                                          "episode_id": e["episode_id"], "mode": e.get("mode"),
                                          "end_reason": e.get("end_reason"), "sweep_consumed_tick": t,
                                          "v2_return": e.get("raw_return"), "v3_minus_v2": delta,
                                          "v3_return": (e.get("raw_return") or 0.0) + delta,
                                          "broken_ids_in_order": [int(b["target_id"]) for b in em["target_breaks"]]})
                    else:
                        agg["v3_equal_v2"] += 1
            agg["per_run"][run] = n_run
        fam_out[fam] = agg
    return {"families": fam_out, "differing": differing, "problems": problems,
            "rule": "no episode has a left entry, so no landing can occur and the failure term is v2's; v3 - v2 is "
                    "exactly the sweep term of an episode whose eval_metrics show all seven right targets broken"}


def census_training() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    need_identity: List[Dict[str, Any]] = []
    for root in TRAINING_ROOTS:
        files = sorted(glob.glob(str(REPO_ROOT / root / "*" / "metrics" / "episodes.jsonl")))
        files += sorted(glob.glob(str(REPO_ROOT / root / "metrics" / "episodes.jsonl")))
        agg = {"runs": 0, "rows": 0, "tick0_rows": 0, "rows_lt7_total_targets": 0, "rows_ge7_total_targets": 0,
               "max_total_targets": 0, "contracts": {}}
        for f in files:
            rel = os.path.relpath(f, REPO_ROOT).replace("\\", "/")
            if "/_" in rel.split("metrics")[0][len(root):]:
                continue        # test / gate / tool directories
            agg["runs"] += 1
            for r in jsonl(Path(f)):
                if r.get("role") not in (None, "training"):
                    continue
                agg["rows"] += 1
                m = r.get("m7h") or {}
                pre = int(m.get("prefix_targets_broken") or 0)
                tot = int(r.get("targets_broken") or 0) + pre
                if not m or m.get("start_kind") in ("tick0", "tick0_initial"):
                    agg["tick0_rows"] += 1
                c = r.get("reward_contract") or "btt_reward_v1(legacy)"
                agg["contracts"][c] = agg["contracts"].get(c, 0) + 1
                agg["max_total_targets"] = max(agg["max_total_targets"], tot)
                if tot >= 7:
                    agg["rows_ge7_total_targets"] += 1
                    need_identity.append({"file": rel, "episode_id": r.get("episode_id"), "targets_total": tot,
                                          "prefix_targets": pre, "start_kind": m.get("start_kind", "tick0"),
                                          "end_reason": r.get("end_reason")})
                else:
                    agg["rows_lt7_total_targets"] += 1
        out[root] = agg
    return {"roots": out, "need_identity": need_identity,
            "rule": "a trajectory with fewer than seven targets broken cannot complete the right sweep, and every v3 "
                    "route term is gated by the sweep, so its v3 reward equals its v2 reward on every step"}


def census_feasibility() -> Dict[str, Any]:
    """The M7i review feasibility episodes (git-ignored review evidence; never a training or decision input)."""
    root = REPO_ROOT / "runs" / "review" / "m7i_feasibility"
    rows = []
    for p in sorted(root.glob("episodes_r*.jsonl")):
        rows.extend(jsonl(p))
    if not rows:
        return {"available": False}
    def ints(v: Any) -> List[int]:
        if isinstance(v, bool):
            return []
        if isinstance(v, int):
            return [v]
        if isinstance(v, (list, tuple)):
            return [x for y in v for x in ints(y)]
        if isinstance(v, Mapping):
            return ints(v.get("target_id", v.get("id")))
        return []

    with_t2 = sum(1 for r in rows if 2 in ints(r.get("all_breaks")))
    return {"available": True, "episodes": len(rows), "prefix_breaks": "83112a8c prefix: IDs 4, 0, 9, 3, 5, 7 "
            "(target 2 never broken in the anchor)", "episodes_breaking_target_2_in_policy_phase": with_t2,
            "landings": sum(1 for r in rows if r.get("landing")), "falls": sum(1 for r in rows if r.get("end") == "fall"),
            "conclusion": "without target 2 no episode can complete the right sweep, so every v3 term is zero and v3 "
                          "equals v2 on every step" if with_t2 == 0 else "some episodes broke target 2: replay needed"}


# -- replay ----------------------------------------------------------------------------------------------------------


def _eval_artifact(run: str, mode: str, select: str) -> Tuple[Path, Dict[str, Any]]:
    d = read_json(REPO_ROOT / "runs" / "m7h" / "campaign" / "_eval" / run / "final" / mode / "evaluation.json")
    eps = sorted(d["episodes"], key=lambda e: e.get("order", 0))
    if select == "order0":
        e = eps[0]
    elif select == "first_fall":
        e = next(e for e in eps if e.get("end_reason") == "fall")
    else:
        raise ValueError(select)
    return REPO_ROOT / e["artifact_dir"], e


def actions_for(item: Mapping[str, Any]) -> Tuple[List[Tuple[int, int, int, Optional[int]]], Dict[str, Any]]:
    import m7f_trace as tr

    kind = item["kind"]
    if kind == "tas":
        # The file has 468 rows; the native clear ends the episode after row 447 (consumed tick 446), so 21 rows stay
        # unsent by design. Reference digest: M7f's recorded TAS stepping trace (diagnostic on, same flags).
        acts = tr.tas_actions()
        ref = None
        m7f = REPO_ROOT / "runs" / "m7f" / "_equiv" / "post_on" / "tas_no_render_raphnet.json.gz"
        if m7f.is_file():
            import gzip

            with gzip.open(m7f, "rt", encoding="utf-8") as fp:
                ref = json.load(fp).get("action_digest")
        return acts, {"source": os.path.relpath(tr.TAS_PATH, REPO_ROOT).replace("\\", "/"), "reference_digest": ref,
                      "reference": "runs/m7f/_equiv/post_on/tas_no_render_raphnet.json.gz" if ref else None,
                      "rows": len(acts), "expected_replayed_rows": 447}
    if kind in ("artifact", "eval_order"):
        if kind == "artifact":
            hits = sorted(glob.glob(str(REPO_ROOT / item["path"])))
            if len(hits) != 1:
                raise FileNotFoundError(f"{item['key']}: {len(hits)} artifact matches for {item['path']}")
            adir, row = Path(hits[0]), None
        else:
            adir, row = _eval_artifact(item["run"], item["mode"], item["select"])
        acts, meta = tr.artifact_actions(adir)
        labels = meta.get("labels") or {}
        info = {"source": os.path.relpath(adir, REPO_ROOT).replace("\\", "/"), "rows": len(acts),
                "reference_digest": labels.get("native_action_digest"), "end_reason": labels.get("end_reason"),
                "recorded_return": labels.get("episode_return"), "recorded_contract": labels.get("reward_contract")}
        if row is not None:
            info.update({"episode_id": row["episode_id"], "eval_raw_return": row.get("raw_return")})
        return acts, info
    if kind == "left_record":
        import m7h_verify as mv

        recs = [r for r in jsonl(REPO_ROOT / M7H_LEFT.format(run=item["run"])) if r["episode_id"].endswith(item["id"])]
        if len(recs) != 1:
            raise LookupError(f"{item['key']}: {len(recs)} left-episode records")
        r = recs[0]
        acts = mv.track1_actions(bytes.fromhex(r["actions_hex"]))
        return acts, {"source": M7H_LEFT.format(run=item["run"]), "episode_id": r["episode_id"], "rows": len(acts),
                      "reference_digest": r["full_digest"], "end_reason": r.get("end_reason"),
                      "prefix_length": r.get("prefix_length"), "class": r.get("class")}
    raise ValueError(kind)


def replay_one(item: Mapping[str, Any], work: Path, index: int) -> Dict[str, Any]:
    import m7f_trace as tr
    from m7_runtime import remove_worker_runtime

    acts, info = actions_for(item)
    t0 = time.perf_counter()
    trace = tr.run_stepping_trace(f"m7j_{item['key']}", EXECUTABLE, acts, work, extra_env=REPLAY_FLAGS, index=index,
                                  rank=0)
    steps = trace["steps"]
    expected_rows = int(info.get("expected_replayed_rows") or len(acts))
    exact = {"consumed_tick_mismatch": trace["consumed_tick_mismatch"], "unsent": trace["unsent"],
             "expected_unsent": len(acts) - expected_rows,
             "digest": trace["action_digest"], "digest_equal": (info.get("reference_digest") is not None
                                                               and trace["action_digest"] == info["reference_digest"])}
    if item["kind"] == "tas":
        exact["clear"] = bool(trace.get("result")) and trace["result"].get("outcome") == "clear"
        exact["digest_equal"] = exact["digest_equal"] and exact["clear"]
    res = v3.rescore_trace(trace["initial"], steps)
    rec = res["v3_record"]
    last = steps[-1]
    clear, failure = v3.termination_from_reply(last)
    end = "clear" if clear else ("fall" if failure else ("horizon" if int(last["consumed_tick"]) == 3599 else "other"))
    out = {"key": item["key"], "why": item["why"], **info, "replayed_rows": len(steps), "end": end, "exact": exact,
           "v2_return": res["v2_return"], "v3_return": res["v3_return"], "v3_minus_v2": res["delta"],
           "differing_steps": res["differing_steps"], "v3_record": rec, "wall_s": round(time.perf_counter() - t0, 2)}
    if info.get("recorded_return") is not None and info.get("recorded_contract") == "btt_reward_v2" \
            and not info.get("prefix_length"):
        out["v2_equals_recorded"] = math.isclose(res["v2_return"], float(info["recorded_return"]), abs_tol=1e-9)
    remove_worker_runtime(work / "runtime")
    return out


def run_replays(out: Path) -> Dict[str, Any]:
    exe_sha = sha256_file(EXECUTABLE)
    if exe_sha != EXPECTED_EXE_SHA:
        raise RuntimeError(f"executable sha {exe_sha} != {EXPECTED_EXE_SHA}")
    results = []
    for k, item in enumerate(REPLAY_SET):
        r = replay_one(item, out / "work" / item["key"], 9900 + k)
        print(json.dumps({x: r.get(x) for x in ("key", "replayed_rows", "end", "v2_return", "v3_return", "v3_minus_v2")}
                         | {"exact": r["exact"]["digest_equal"] and r["exact"]["consumed_tick_mismatch"] is None}),
              flush=True)
        results.append(r)
    return {"executable_sha256": exe_sha, "flags": REPLAY_FLAGS, "episodes": results,
            "all_exact": all(r["exact"]["digest_equal"] and r["exact"]["consumed_tick_mismatch"] is None
                             and r["exact"]["unsent"] == r["exact"]["expected_unsent"] for r in results)}


# -- ranking and loopholes -------------------------------------------------------------------------------------------


def _v2(targets: int, steps: int, *, cleared: bool = False, fall: bool = False) -> float:
    return targets * 1.0 + steps * -0.001 + (10.0 if cleared else 0.0) + (-5.0 if fall else 0.0)


def _v3(targets: int, steps: int, *, cleared: bool = False, fall: bool = False, sweep: Optional[int] = None,
        landed: bool = False) -> float:
    return v3.expected_return_v3(targets_broken=targets, steps=steps, cleared=cleared, native_failure=fall,
                                 sweep_consumed_tick=sweep, qualified_landing=landed)


def ranking_table() -> Dict[str, Any]:
    """Closed-form returns of outcome classes. Ticks are chosen as illustrative anchors; the conclusions are checked
    as inequalities over the whole tick range in `inequalities`."""
    H = 3600
    rows = []

    def add(name: str, kind: str, v2r: float, v3r: float, note: str = "") -> None:
        rows.append({"outcome": name, "kind": kind, "v2": round(v2r, 6), "v3": round(v3r, 6), "note": note})

    add("stay right, 5 targets, survive to horizon", "observed class", _v2(5, H), _v3(5, H))
    add("stay right, 6 right targets, survive", "observed class", _v2(6, H), _v3(6, H))
    add("stay right, 6 right targets, fall at 2000", "observed class", _v2(6, 2000, fall=True), _v3(6, 2000, fall=True))
    add("sweep on consumed tick 3570 (late), survive", "observed once (M7h F s2)", _v2(7, H), _v3(7, H, sweep=3570))
    add("sweep on consumed tick 1499, survive right", "never observed", _v2(7, H), _v3(7, H, sweep=1499))
    add("premature crossing (6 right) + line-3 landing + fall at 3220", "observed (M7h 83112a8c, full trajectory)",
        _v2(6, 3221, fall=True), _v3(6, 3221, fall=True))
    add("premature crossing, 6 right + 3 left, survive (stranded)", "never observed", _v2(9, H), _v3(9, H))
    add("premature crossing, 6 right + 2 left in the air, fall at 2000", "partly observed (left breaks + falls)",
        _v2(8, 2000, fall=True), _v3(8, 2000, fall=True))
    add("sweep 1500, qualified crossing, fall before landing at 1800", "never observed",
        _v2(7, 1800, fall=True), _v3(7, 1800, fall=True, sweep=1499))
    add("sweep 1500, crossing, landing, fall at 1900 (no left target)", "never observed",
        _v2(7, 1900, fall=True), _v3(7, 1900, fall=True, sweep=1499, landed=True))
    add("sweep 1500, crossing, landing, survive (no left target)", "never observed",
        _v2(7, H), _v3(7, H, sweep=1499, landed=True))
    add("sweep 1500, 6+8 in the air, landing, fall at 2100", "never observed",
        _v2(9, 2100, fall=True), _v3(9, 2100, fall=True, sweep=1499, landed=True))
    add("sweep 1500, crossing, landing, clear at 2400", "never observed",
        _v2(10, 2400, cleared=True), _v3(10, 2400, cleared=True, sweep=1499, landed=True))
    add("TAS: sweep 358, over-wall entry 359, clear at 446 (no landing)", "observed (TAS, not a policy)",
        _v2(10, 447, cleared=True), _v3(10, 447, cleared=True, sweep=358))
    # inequalities over the whole range
    ineq = []

    def check(name: str, ok: bool, detail: str) -> None:
        ineq.append({"claim": name, "holds": bool(ok), "detail": detail})

    worst_sweep_survive = min(_v3(7, H, sweep=t) for t in range(0, H))
    best_premature_stranded = _v3(9, H)
    check("a sweep then surviving on the right beats any premature crossing that strands with all 3 left targets",
          worst_sweep_survive > best_premature_stranded,
          f"min over sweep ticks {worst_sweep_survive:.4f} > {best_premature_stranded:.4f} (v2: {_v2(7, H):.4f} < "
          f"{_v2(9, H):.4f}, i.e. v2 ranks the stranded route higher)")
    check("after a sweep, crossing + landing + a later fall beats staying right to the horizon (any ticks)",
          all(_v3(7, tf, fall=True, sweep=ts, landed=True) > _v3(7, H, sweep=ts)
              for ts in range(0, H, 37) for tf in range(ts + 2, H + 1, 53)), "grid over sweep / fall ticks")
    check("after a sweep, crossing and falling WITHOUT a landing is worse than staying right to the horizon",
          all(_v3(7, tf, fall=True, sweep=ts) < _v3(7, H, sweep=ts)
              for ts in range(0, H, 37) for tf in range(ts + 2, H + 1, 53)), "grid; the -5 dominates -0.001/tick")
    check("a premature crossing is scored exactly as under v2",
          all(_v3(k, s, fall=f) == _v2(k, s, fall=f) for k in range(0, 10) for s in (500, 2000, 3600) for f in (0, 1)),
          "no v3 term fires without the sweep")
    check("no fall (without a qualified landing) outscores surviving to the horizon with the same targets (M7b "
          "invariant kept wherever v2 applies)",
          all(_v3(k, s, fall=True) < _v3(k, H) for k in range(0, 10) for s in range(1, H + 1, 7)), "")
    post = [tf for tf in range(2, H + 1) if _v3(7, tf, fall=True, sweep=0, landed=True) > _v3(7, H, sweep=0, landed=True)]
    check("POST-LANDING: a fall on any step before tick 2,600 outscores idling to the horizon (the M7b invariant is "
          "deliberately broken after a qualified landing)",
          bool(post) and max(post) == 2599,
          f"fall better iff 0.001 * t_f + 1 < 3.6, i.e. t_f < 2600 (last such t_f = {max(post) if post else None}); "
          f"both outcomes have the same targets and neither clears")
    check("the sweep is worth more the earlier it completes, by at most 2.0",
          _v3(7, H, sweep=0) - _v3(7, H, sweep=3599) < 2.0 and all(
              _v3(7, H, sweep=t) >= _v3(7, H, sweep=t + 1) for t in range(0, H - 1)), "")
    return {"rows": rows, "inequalities": ineq}


def _run_synthetic(seq: Sequence[Tuple[str, Mapping[str, Any]]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any], float]:
    """seq of (label, reply fields); the reply is built by btt_reward_v3._reply."""
    st = v3.RouteRewardState()
    st.start(v3._initial())
    out = []
    total = 0.0
    for t, (label, kw) in enumerate(seq):
        kw = dict(kw)
        clear = kw.pop("clear", False)
        fail = kw.pop("fail", False)
        terms = st.step(v3._reply(t, **kw), clear=clear, native_failure=fail)
        total += terms.total
        out.append({"t": t, "label": label, **{k: v for k, v in terms.to_json().items() if v}})
    return out, st.record(), total


def loophole_cases() -> List[Dict[str, Any]]:
    """Synthetic sequences through the v3 state machine (labelled synthetic; not observed trajectories)."""
    F = v3.FULL_MASK
    right = [0, 2, 3, 4, 5, 7, 9]
    m6 = F
    for tid in right[:-1]:
        m6 &= ~(1 << tid)
    m7 = m6 & ~(1 << right[-1])
    cases = []

    def case(name: str, seq: Sequence[Tuple[str, Mapping[str, Any]]], expect: Mapping[str, Any]) -> None:
        steps, rec, total = _run_synthetic(seq)
        got = {"sweep_terms": sum(1 for s in steps if s.get("sweep_term")),
               "crossing_terms": sum(1 for s in steps if s.get("crossing_term")),
               "failure_term": next((s["failure_term"] for s in steps if s.get("failure_term")), 0.0)}
        ok = all(got[k] == v for k, v in expect.items())
        cases.append({"case": name, "kind": "synthetic", "ok": ok, "expect": dict(expect), "got": got,
                      "return": round(total, 6), "record": {k: rec[k] for k in ("right_sweep", "entry_counts",
                                                                                 "qualified_entries", "qualified_landing",
                                                                                 "first_line3_landing", "failure_category")}})

    up = dict(x=-2000.0, y=3500.0)
    over = dict(x=-2200.0, y=3400.0)
    land = dict(x=-3000.0, y=-1950.0, g=0)
    case("farming: sweep re-reported on every later step", [("sweep", dict(x=0.0, y=0.0, remaining=m7))] +
         [("idle", dict(x=0.0, y=0.0, remaining=m7))] * 5, {"sweep_terms": 1, "crossing_terms": 0})
    case("multi-target tick: last right + left target 6 on one tick",
         [("six", dict(x=0.0, y=0.0, remaining=m6)), ("both", dict(x=0.0, y=0.0, remaining=m7 & ~(1 << 6)))],
         {"sweep_terms": 1})
    case("repeated landing after a qualified crossing", [("sweep", dict(x=0.0, y=0.0, remaining=m7)),
         ("up", dict(up, remaining=m7)), ("over", dict(over, remaining=m7)), ("land", dict(land, remaining=m7)),
         ("jump", dict(x=-3000.0, y=-1500.0, remaining=m7)), ("land2", dict(land, remaining=m7))],
         {"sweep_terms": 1, "crossing_terms": 1})
    case("premature crossing, then the sweep completes while on the left, then a landing",
         [("six", dict(x=0.0, y=0.0, remaining=m6)), ("up", dict(up, remaining=m6)), ("over", dict(over, remaining=m6)),
          ("sweep_left", dict(x=-2500.0, y=2000.0, remaining=m7)), ("land", dict(land, remaining=m7)),
          ("fall", dict(x=-3000.0, y=-9000.0, remaining=m7, game_status=5, fail=True))],
         {"sweep_terms": 1, "crossing_terms": 0, "failure_term": -5.0})
    case("under-stage entry after the sweep, then a line-3 landing",
         [("sweep", dict(x=0.0, y=0.0, remaining=m7)), ("under", dict(x=-2000.0, y=-8000.0, remaining=m7)),
          ("in", dict(x=-2200.0, y=-8100.0, remaining=m7)), ("land", dict(land, remaining=m7))],
         {"crossing_terms": 0})
    case("wrong surface: ledge top and the moving platform after the sweep",
         [("sweep", dict(x=0.0, y=0.0, remaining=m7)), ("ledge", dict(x=-1500.0, y=3000.0, g=0, remaining=m7)),
          ("platform", dict(x=2700.0, y=2400.0, g=0, remaining=m7))], {"crossing_terms": 0})
    case("landing on the native-failure step is not counted",
         [("sweep", dict(x=0.0, y=0.0, remaining=m7)), ("up", dict(up, remaining=m7)), ("over", dict(over, remaining=m7)),
          ("land_fail", dict(land, remaining=m7, game_status=5, fail=True))],
         {"crossing_terms": 0, "failure_term": -5.0})
    case("sweep on the same step as the over-wall entry qualifies",
         [("six", dict(x=0.0, y=0.0, remaining=m6)), ("up", dict(up, remaining=m6)), ("over_sweep", dict(over, remaining=m7)),
          ("land", dict(land, remaining=m7))], {"sweep_terms": 1, "crossing_terms": 1})
    case("exit right after a qualified landing, then a fall on the right keeps -1 (landing latched)",
         [("sweep", dict(x=0.0, y=0.0, remaining=m7)), ("up", dict(up, remaining=m7)), ("over", dict(over, remaining=m7)),
          ("land", dict(land, remaining=m7)), ("back", dict(x=-2000.0, y=3400.0, remaining=m7)),
          ("fall", dict(x=0.0, y=-9000.0, remaining=m7, game_status=5, fail=True))],
         {"crossing_terms": 1, "failure_term": -1.0})
    return cases


def ranking(out: Optional[Path] = None) -> Dict[str, Any]:
    return {"table": ranking_table(), "loopholes": loophole_cases()}


# -- driver ----------------------------------------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="M7j offline check of btt_reward_v3")
    p.add_argument("what", choices=("census", "replay", "ranking", "all"))
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    out = Path(a.out)
    if not out.is_absolute():
        out = REPO_ROOT / out
    out.mkdir(parents=True, exist_ok=True)
    meta = {"created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "contract": REWARD_V3.to_json(),
            "code_sha256": {n: sha256_file(RL_DIR / n) for n in ("btt_reward_v3.py", "btt_rewards.py", "m7j_offline.py")}}
    rc = 0
    if a.what in ("census", "all"):
        c = {"meta": meta, "eval": census_eval(), "training": census_training(), "feasibility": census_feasibility()}
        write_json(out / "census.json", c)
        print(json.dumps({"eval": {f: {k: v for k, v in g.items() if k != "per_run"} for f, g in c["eval"]["families"].items()},
                          "differing": c["eval"]["differing"], "problems": c["eval"]["problems"][:5],
                          "training": {r: {k: v for k, v in g.items()} for r, g in c["training"]["roots"].items()},
                          "need_identity": c["training"]["need_identity"], "feasibility": c["feasibility"]}, indent=1))
    if a.what in ("ranking", "all"):
        r = {"meta": meta, **ranking()}
        write_json(out / "ranking.json", r)
        for row in r["table"]["rows"]:
            print(f"{row['v2']:>9.3f} {row['v3']:>9.3f}  {row['outcome']}  [{row['kind']}]")
        for q in r["table"]["inequalities"]:
            print(("HOLDS " if q["holds"] else "FAILS ") + q["claim"] + " | " + q["detail"])
        for cs in r["loopholes"]:
            print(("ok   " if cs["ok"] else "FAIL ") + cs["case"], cs["got"], cs["return"])
            rc |= 0 if cs["ok"] else 1
    if a.what in ("replay", "all"):
        rr = {"meta": meta, **run_replays(out)}
        write_json(out / "replay.json", rr)
        rc |= 0 if rr["all_exact"] else 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
