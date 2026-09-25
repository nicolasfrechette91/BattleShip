#!/usr/bin/env python3
"""M7k: moving target ID 2 — breaks and near misses in stored episodes (exact replays, native diagnostics only).

    python rl/m7k_target2.py select  --out runs/m7k/target2/<name>     # write the pre-declared replay list
    python rl/m7k_target2.py replay  --out runs/m7k/target2/<name> [--workers 4] [--limit N]
    python rl/m7k_target2.py analyze --out runs/m7k/target2/<name>

Replay sets (declared by rule before the first replay; recorded in selection.json):
  A  every tick-0 evaluation episode (Phase K 6 runs + its random baseline, M7h F 3 runs) whose btt_eval_metrics_v1
     record shows target 2 broken;
  B  every tick-0 evaluation episode with the six static right targets {0,3,4,5,7,9} broken and target 2 NOT broken
     (the population in which target 2 is the only right target missing);
  C  a reference sample: the first 20 episodes (evaluation order) of every final stochastic label (Phase K 6 runs,
     M7h F 3 runs) and of the Phase K random baseline;
  D  training: every Phase K v1 training artifact preserved as `periodic_milestone` (every 10th finished episode of
     the run, content-blind, so an unbiased sample of the control's training episodes).
Each episode is replayed from tick 0 in a fresh BattleShip process (m7f_trace.run_stepping_trace) with
SSB64_RL_NO_RENDER, SSB64_RAPHNET_DISABLE, SSB64_RL_TARGET_DIAG (identity) and SSB64_RL_SPATIAL (live target
positions, the moving platform's translate and Mario's floor line). Both diagnostics are read-only and proven
gameplay-neutral (M7f, M7g-b); every replay must reproduce the recorded native action digest and consumed ticks.

Per step the replay keeps: consumed tick, Mario position / ground state / status, target 2's live position, the
platform translate y and speed, whether Mario stands on the platform (floor line 19), and the broken-target mask.

The TAS and the user crossing fixtures are not read. Native RNG state is never read, logged, compared or hashed.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import hashlib
import json
import math
import os
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parent
REPO_ROOT = RL_DIR.parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

RIGHT = (0, 2, 3, 4, 5, 7, 9)
STATIC = (0, 3, 4, 5, 7, 9)
LEFT = (1, 6, 8)
T2 = 2
H = 3600
EXECUTABLE = REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"
EXPECTED_EXE_SHA = "1e7c62a05a9397fb4ef1d404d85a793cd01c4dbdc187068e3a63890cb5cbeb97"
FLAGS = {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1", "SSB64_RL_TARGET_DIAG": "1", "SSB64_RL_SPATIAL": "1"}
PHASE_K_RUNS = ("m7g_s0_v1", "m7g_s1_v1", "m7g_s2_v1", "m7g_s0_v2", "m7g_s1_v2", "m7g_s2_v2")
M7H_RUNS = ("m7h_f_s0", "m7h_f_s1", "m7h_f_s2")
EVAL_ROOTS = {"phase_k": "runs/m7g_k/_eval", "m7h": "runs/m7h/campaign/_eval"}
PLATFORM_LINE = 19
PLATFORM_GROUP = 2
NEAR_RADII = (300.0, 600.0, 1000.0)
# The approach zone: every target-2 break seen in the first analysis pass happened with Mario at x 2,224..3,136 and
# y >= 1,382 (up-B from below the low platform); the zone is that box, rounded outward to the right block's x span.
ZONE_X = (2100.0, 3300.0)
ZONE_Y_MIN = 1350.0


def read_json(p: Path) -> Any:
    with open(p, "r", encoding="utf-8") as fp:
        return json.load(fp)


def write_json(p: Path, data: Any, *, gz: bool = False) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        raise FileExistsError(f"{p} exists (never overwritten)")
    opener = (lambda: gzip.open(p, "wt", encoding="utf-8")) if gz else (lambda: open(p, "w", encoding="utf-8", newline="\n"))
    with opener() as fp:
        json.dump(data, fp, separators=(",", ":") if gz else None, indent=None if gz else 1)
        fp.write("\n")


def rel(p: Any) -> str:
    return os.path.relpath(str(p), REPO_ROOT).replace("\\", "/")


# -- selection -------------------------------------------------------------------------------------------------------


def _eval_files() -> List[Tuple[str, str, str, str, Path]]:
    out = []
    for fam, root in EVAL_ROOTS.items():
        runs = PHASE_K_RUNS if fam == "phase_k" else M7H_RUNS
        for run in runs:
            for f in sorted(glob.glob(str(REPO_ROOT / root / run / "*" / "*" / "evaluation.json"))):
                label, mode = Path(f).parts[-3], Path(f).parts[-2]
                out.append((fam, run, label, mode, Path(f)))
        if fam == "phase_k":
            for f in sorted(glob.glob(str(REPO_ROOT / root / "random_baseline" / "*" / "evaluation.json"))):
                out.append((fam, "random_baseline", "random", Path(f).parts[-2], Path(f)))
    return out


def select() -> Dict[str, Any]:
    items: Dict[str, Dict[str, Any]] = {}

    def add(key: str, rec: Dict[str, Any], group: str) -> None:
        if key in items:
            items[key]["sets"].append(group)
        else:
            items[key] = dict(rec, sets=[group])

    for fam, run, label, mode, f in _eval_files():
        d = read_json(f)
        eps = sorted(d.get("episodes") or [], key=lambda e: e.get("order", 0))
        for k, e in enumerate(eps):
            em = e.get("eval_metrics") or {}
            if "target_breaks" not in em:
                continue
            ids = {int(b["target_id"]) for b in em["target_breaks"]}
            rec = {"source": "evaluation", "family": fam, "run": run, "label": label, "mode": mode,
                   "episode_id": e["episode_id"], "artifact_dir": e["artifact_dir"], "end_reason": e.get("end_reason"),
                   "length": e.get("length"), "recorded_breaks": [(int(b["target_id"]), int(b["consumed_tick"]))
                                                                  for b in em["target_breaks"]],
                   "reference_digest": e.get("native_action_digest"), "raw_return": e.get("raw_return")}
            key = e["episode_id"]
            if T2 in ids:
                add(key, rec, "A")
            if set(STATIC) <= ids and T2 not in ids:
                add(key, rec, "B")
            if (label == "final" and mode == "stochastic" or run == "random_baseline") and k < 20:
                add(key, rec, "C")
    for run in PHASE_K_RUNS[:3]:
        for line in open(REPO_ROOT / "runs" / "m7g_k" / run / "metrics" / "episodes.jsonl", encoding="utf-8"):
            r = json.loads(line)
            if "periodic_milestone" in (r.get("preservation_events") or []) and r.get("artifact_dir"):
                add(r["episode_id"], {"source": "training", "family": "phase_k", "run": run, "label": "training",
                                      "mode": "stochastic", "episode_id": r["episode_id"], "artifact_dir": r["artifact_dir"],
                                      "end_reason": r.get("end_reason"), "length": r.get("steps"),
                                      "recorded_breaks": None, "reference_digest": r.get("native_action_digest"),
                                      "raw_return": r.get("return"), "sb3_num_timesteps_seen": r.get("sb3_num_timesteps_seen")},
                    "D")
    allv = sorted(items.values(), key=lambda r: (r["source"], r["family"], r["run"], r["label"], r["mode"], r["episode_id"]))
    lst = [r for r in allv if r.get("artifact_dir")]
    unreplayable = [{k: r[k] for k in ("run", "label", "episode_id", "sets", "recorded_breaks")} for r in allv
                    if not r.get("artifact_dir")]
    counts: Dict[str, int] = {}
    for r in lst:
        for s in r["sets"]:
            counts[s] = counts.get(s, 0) + 1
    return {"contract": "m7k_target2_selection_v1", "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "rules": {"A": "evaluation, target 2 broken", "B": "evaluation, six static right targets broken, target 2 not",
                      "C": "first 20 of every final stochastic label + Phase K random baseline",
                      "D": "Phase K v1 training artifacts preserved as periodic_milestone"},
            "counts": counts, "episodes": len(lst),
            "unreplayable_no_artifact": unreplayable, "items": lst}


# -- one replay (worker process) -------------------------------------------------------------------------------------

_RANK: Optional[int] = None


def _init_worker(counter: Any) -> None:
    global _RANK
    with counter.get_lock():
        counter.value += 1
        _RANK = int(counter.value)
    from m7_runtime import install_kill_on_close_job

    install_kill_on_close_job()


def replay_one(item: Mapping[str, Any], work_root: str, index: int) -> Dict[str, Any]:
    import m7f_trace as tr
    import m7g_spatial as sp
    from btt_reward_v3 import remaining_mask, termination_from_reply

    acts, _meta = tr.artifact_actions(REPO_ROOT / item["artifact_dir"])
    work = Path(work_root) / f"e{index:05d}"
    t0 = time.perf_counter()
    trace = tr.run_stepping_trace(f"m7k_t2_{index}", EXECUTABLE, acts, work, extra_env=FLAGS, index=index,
                                  rank=_RANK or 1)
    steps = trace["steps"]
    rows = []
    prev_mask = remaining_mask(trace["initial"])       # the tick-0 table (all ten alive)
    breaks = []
    for s in steps:
        o = s["observation"]
        snap = sp.spatial_of(s, expect_lines=False)
        grp = snap.group(PLATFORM_GROUP)
        mask = remaining_mask(s)
        t2_live = bool(snap.target_live_mask >> T2 & 1)
        t2 = snap.target_positions[T2] if t2_live else None
        onp = sp.on_platform(snap, o)
        newly = prev_mask & ~mask
        for tid in range(10):
            if newly >> tid & 1:
                breaks.append((tid, int(s["consumed_tick"])))
        rows.append([int(s["consumed_tick"]), round(float(o["position_x"]), 2), round(float(o["position_y"]), 2),
                     int(o["ground_air_state"]), int(o["fighter_status_id"]), int(o["fighter_valid"] == 1 and o["btt_active"] == 1),
                     None if t2 is None else round(float(t2[0]), 2), None if t2 is None else round(float(t2[1]), 2),
                     round(float(grp.translate[1]), 3) if grp else None, round(float(grp.speed[1]), 3) if grp else None,
                     int(onp), mask])
        prev_mask = mask
    last = steps[-1]
    clear, failure = termination_from_reply(last)
    end = "clear" if clear else ("fall" if failure else ("horizon" if int(last["consumed_tick"]) == H - 1 else "other"))
    recorded = item.get("recorded_breaks")
    exact = {"consumed_tick_mismatch": trace["consumed_tick_mismatch"], "unsent": trace["unsent"],
             "digest_equal": trace["action_digest"] == item.get("reference_digest"),
             "breaks_equal_recorded": None if recorded is None else [tuple(b) for b in recorded] == breaks}
    cleanup = remove_runtime_with_retry(work / "runtime")
    return {"episode_id": item["episode_id"], "index": index, "end": end, "steps": len(steps), "exact": exact,
            "runtime_cleanup": cleanup,
            "breaks": breaks, "fields": ["t", "x", "y", "g", "status", "live", "t2x", "t2y", "plat_y", "plat_vy",
                                         "on_platform", "remaining_mask"],
            "rows": rows, "wall_s": round(time.perf_counter() - t0, 2)}


def remove_runtime_with_retry(runtime: Path, timeout: float = 30.0) -> Dict[str, Any]:
    """remove_worker_runtime, retried while another process still holds a file of the finished episode (first pass:
    33 of 621 replays lost their result to PermissionError here). Records how long the files stayed locked and, via
    the Windows Restart Manager, which process held them."""
    from m7_runtime import remove_worker_runtime

    t0 = time.perf_counter()
    holders: List[Dict[str, Any]] = []
    attempts = 0
    while True:
        attempts += 1
        try:
            remove_worker_runtime(runtime)
            return {"attempts": attempts, "locked_s": round(time.perf_counter() - t0, 3), "holders": holders}
        except PermissionError as exc:
            if not holders:
                import m7k_teardown_probe as tp

                holders = tp.file_holders([exc.filename]) if getattr(exc, "filename", None) else []
            if time.perf_counter() - t0 > timeout:
                return {"attempts": attempts, "locked_s": None, "holders": holders, "error": str(exc)}
            time.sleep(0.05)


def run_replays(out: Path, workers: int, limit: Optional[int]) -> Dict[str, Any]:
    import multiprocessing

    from m7_runtime import install_kill_on_close_job, sha256_file

    exe_sha = sha256_file(EXECUTABLE)
    if exe_sha != EXPECTED_EXE_SHA:
        raise RuntimeError(f"executable {exe_sha} != {EXPECTED_EXE_SHA}")
    install_kill_on_close_job()
    sel = read_json(out / "selection.json")
    items = sel["items"][:limit] if limit else sel["items"]
    tdir = out / "traces"
    tdir.mkdir(parents=True, exist_ok=True)
    done = {p.name.split(".")[0] for p in tdir.glob("*.json.gz")}
    todo = [(i, it) for i, it in enumerate(items) if it["episode_id"] not in done]
    ctx = multiprocessing.get_context("spawn")
    counter = ctx.Value("i", 0)
    failures = []
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers, mp_context=ctx, initializer=_init_worker, initargs=(counter,)) as ex:
        futs = {ex.submit(replay_one, it, str(out / "work"), 30000 + i): it for i, it in todo}
        for n, fut in enumerate(as_completed(futs), 1):
            it = futs[fut]
            try:
                r = fut.result()
                write_json(tdir / f"{it['episode_id']}.json.gz", r, gz=True)
                ok = r["exact"]["digest_equal"] and r["exact"]["consumed_tick_mismatch"] is None and r["exact"]["unsent"] == 0 \
                    and r["exact"]["breaks_equal_recorded"] in (None, True)
                if not ok:
                    failures.append({"episode_id": it["episode_id"], "exact": r["exact"]})
            except Exception as exc:  # noqa: BLE001
                failures.append({"episode_id": it["episode_id"], "error": f"{type(exc).__name__}: {exc}"})
            if n % 25 == 0 or n == len(futs):
                print(f"[m7k] {n}/{len(futs)} replays, {len(failures)} problem(s), {time.perf_counter() - t0:.0f} s", flush=True)
    summary = {"executable_sha256": exe_sha, "flags": FLAGS, "requested": len(items), "replayed_now": len(todo),
               "failures": failures, "wall_s": round(time.perf_counter() - t0, 1)}
    p = out / f"replay_summary_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
    write_json(p, summary)
    return summary


# -- analysis --------------------------------------------------------------------------------------------------------


def _q(vals: Sequence[float]) -> Optional[Dict[str, float]]:
    v = sorted(vals)
    if not v:
        return None
    def at(p: float) -> float:
        return v[min(len(v) - 1, int(p * (len(v) - 1) + 0.5))]
    return {"n": len(v), "min": v[0], "p25": at(0.25), "median": at(0.5), "p75": at(0.75), "max": v[-1],
            "mean": round(statistics.fmean(v), 2)}


def episode_features(tr: Mapping[str, Any]) -> Dict[str, Any]:
    f = {k: i for i, k in enumerate(tr["fields"])}
    rows = tr["rows"]
    tr = dict(tr, breaks=[tuple(b) for b in tr["breaks"]])    # JSON stores pairs as lists
    brk = dict((tid, t) for tid, t in tr["breaks"])
    t2_tick = brk.get(T2)
    out: Dict[str, Any] = {"episode_id": tr["episode_id"], "end": tr["end"], "steps": tr["steps"],
                           "targets": len(brk), "breaks": tr["breaks"], "t2_broken": t2_tick is not None}
    right_ticks = [brk[i] for i in RIGHT if i in brk]
    static_ticks = [brk[i] for i in STATIC if i in brk]
    out["static_done_tick"] = max(static_ticks) if len(static_ticks) == len(STATIC) else None
    out["sweep_tick"] = max(right_ticks) if len(right_ticks) == len(RIGHT) else None
    # min distance to target 2 while it is alive (Mario's position = feet); platform contact; right-side height
    best = None
    within = {r: 0 for r in NEAR_RADII}
    plat_ticks = 0
    first_plat = None
    max_y_right = None
    zone_ticks = 0
    first_zone = None
    for r in rows:
        if r[f["live"]] and ZONE_X[0] <= r[f["x"]] <= ZONE_X[1] and r[f["y"]] >= ZONE_Y_MIN:
            zone_ticks += 1
            first_zone = first_zone if first_zone is not None else r[f["t"]]
        if r[f["on_platform"]]:
            plat_ticks += 1
            first_plat = first_plat if first_plat is not None else r[f["t"]]
        if r[f["live"]] and r[f["x"]] > 2100:
            max_y_right = r[f["y"]] if max_y_right is None else max(max_y_right, r[f["y"]])
        if r[f["t2x"]] is None or not r[f["live"]]:
            continue
        d = math.hypot(r[f["x"]] - r[f["t2x"]], r[f["y"]] - r[f["t2y"]])
        for rad in NEAR_RADII:
            within[rad] += d <= rad
        if best is None or d < best[0]:
            best = (d, r)
    out["zone_ticks"] = zone_ticks
    out["first_zone_tick"] = first_zone
    out["platform_ticks"] = plat_ticks
    out["first_platform_tick"] = first_plat
    out["max_y_right_of_2100"] = max_y_right
    out["ticks_within"] = {str(int(k)): v for k, v in within.items()}
    if best is not None:
        d, r = best
        out["closest"] = {"distance": round(d, 1), "t": r[f["t"]], "mario": [r[f["x"]], r[f["y"]]], "g": r[f["g"]],
                          "status": r[f["status"]], "target2": [r[f["t2x"]], r[f["t2y"]]], "plat_y": r[f["plat_y"]],
                          "plat_vy": r[f["plat_vy"]], "on_platform": bool(r[f["on_platform"]])}
    if t2_tick is not None:
        idx = next(i for i, r in enumerate(rows) if r[f["t"]] == t2_tick)
        r = rows[idx]
        pr = rows[idx - 1] if idx > 0 else None
        before_mask = pr[f["remaining_mask"]] if pr is not None else (1 << 10) - 1
        remaining_right = [i for i in RIGHT if i != T2 and before_mask >> i & 1]
        order = sorted(tr["breaks"], key=lambda b: (b[1], b[0])).index((T2, t2_tick)) + 1
        out["t2_break"] = {
            "t": t2_tick, "n": t2_tick + 1, "horizon_left": H - (t2_tick + 1), "break_order": order,
            "right_targets_remaining_before": remaining_right, "static_remaining_before": len(remaining_right),
            "mario": [r[f["x"]], r[f["y"]]], "g": r[f["g"]], "status": r[f["status"]],
            "on_platform": bool(r[f["on_platform"]]),
            "target2_prev": None if pr is None or pr[f["t2x"]] is None else [pr[f["t2x"]], pr[f["t2y"]]],
            "distance_prev": None if pr is None or pr[f["t2x"]] is None else round(math.hypot(
                r[f["x"]] - pr[f["t2x"]], r[f["y"]] - pr[f["t2y"]]), 1),
            "plat_y": r[f["plat_y"]], "plat_vy": r[f["plat_vy"]],
            "platform_ticks_before": sum(1 for x in rows[:idx + 1] if x[f["on_platform"]]),
        }
    return out


def platform_determinism(traces: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Is the platform translate a pure function of the consumed tick? (max spread over episodes per tick)"""
    by_t: Dict[int, Tuple[float, float]] = {}
    spread = 0.0
    n = 0
    for tr in traces:
        f = {k: i for i, k in enumerate(tr["fields"])}
        for r in tr["rows"]:
            y = r[f["plat_y"]]
            if y is None:
                continue
            t = r[f["t"]]
            if t in by_t:
                lo, hi = by_t[t]
                by_t[t] = (min(lo, y), max(hi, y))
                spread = max(spread, by_t[t][1] - by_t[t][0])
            else:
                by_t[t] = (y, y)
            n += 1
    ys = [by_t[t][0] for t in sorted(by_t)]
    ts = sorted(by_t)
    lows = [t for i, t in enumerate(ts[1:-1], 1) if ys[i] <= ys[i - 1] and ys[i] < ys[i + 1]]
    return {"samples": n, "ticks": len(by_t), "max_spread_same_tick": spread, "first_minima_ticks": lows[:6],
            "period_estimate": (lows[1] - lows[0]) if len(lows) > 1 else None,
            "y_range": [min(ys), max(ys)] if ys else None, "table_every_25": {t: by_t[t][0] for t in ts if t % 25 == 0}}


def analyze(out: Path) -> Dict[str, Any]:
    sel = read_json(out / "selection.json")
    items = {it["episode_id"]: it for it in sel["items"]}
    traces = []
    for p in sorted((out / "traces").glob("*.json.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as fp:
            traces.append(json.load(fp))
    feats = []
    for tr in traces:
        ft = episode_features(tr)
        it = items[tr["episode_id"]]
        ft.update({k: it[k] for k in ("sets", "source", "family", "run", "label", "mode")})
        ft["exact"] = tr["exact"]
        feats.append(ft)
    det = platform_determinism(traces)
    a = [x for x in feats if "A" in x["sets"]]
    b = [x for x in feats if "B" in x["sets"]]
    c = [x for x in feats if "C" in x["sets"]]
    d = [x for x in feats if "D" in x["sets"]]
    t2b = [x["t2_break"] for x in feats if x.get("t2_break")]
    res: Dict[str, Any] = {
        "contract": "m7k_target2_analysis_v1", "traces": len(traces),
        "all_exact": all(x["exact"]["digest_equal"] and x["exact"]["consumed_tick_mismatch"] is None
                         and x["exact"]["breaks_equal_recorded"] in (None, True) for x in feats),
        "platform": det,
        "sets": {k: len(v) for k, v in (("A", a), ("B", b), ("C", c), ("D", d))},
        "t2_breaks": {
            "episodes": len(t2b),
            "tick": _q([x["t"] for x in t2b]),
            "horizon_left": _q([x["horizon_left"] for x in t2b]),
            "break_order": _q([x["break_order"] for x in t2b]),
            "static_remaining_before": {str(k): sum(1 for x in t2b if x["static_remaining_before"] == k) for k in range(7)},
            "mario_status": _count(x["status"] for x in t2b),
            "on_platform": sum(1 for x in t2b if x["on_platform"]),
            "platform_contact_before": sum(1 for x in t2b if x["platform_ticks_before"] > 0),
            "grounded": sum(1 for x in t2b if x["g"] == 0),
            "distance_prev": _q([x["distance_prev"] for x in t2b if x["distance_prev"] is not None]),
            "plat_y": _q([x["plat_y"] for x in t2b if x["plat_y"] is not None]),
            "plat_rising": sum(1 for x in t2b if (x["plat_vy"] or 0) > 0),
            "mario_x": _q([x["mario"][0] for x in t2b]), "mario_y": _q([x["mario"][1] for x in t2b]),
        },
        "by_set": {},
        "episodes": feats,
    }
    for name, grp in (("A", a), ("B", b), ("C", c), ("D", d)):
        res["by_set"][name] = {
            "n": len(grp), "t2_broken": sum(1 for x in grp if x["t2_broken"]),
            "closest_distance": _q([x["closest"]["distance"] for x in grp if x.get("closest") and not x["t2_broken"]]),
            "within_300_any": sum(1 for x in grp if not x["t2_broken"] and x["ticks_within"]["300"] > 0),
            "within_600_any": sum(1 for x in grp if not x["t2_broken"] and x["ticks_within"]["600"] > 0),
            "within_1000_any": sum(1 for x in grp if not x["t2_broken"] and x["ticks_within"]["1000"] > 0),
            "zone_visit": sum(1 for x in grp if x["zone_ticks"] > 0),
            "zone_visit_no_t2": sum(1 for x in grp if x["zone_ticks"] > 0 and not x["t2_broken"]),
            "first_zone_tick": _q([x["first_zone_tick"] for x in grp if x["first_zone_tick"] is not None]),
            "platform_contact": sum(1 for x in grp if x["platform_ticks"] > 0),
            "platform_contact_no_t2": sum(1 for x in grp if x["platform_ticks"] > 0 and not x["t2_broken"]),
            "max_y_right": _q([x["max_y_right_of_2100"] for x in grp if x["max_y_right_of_2100"] is not None]),
            "static_done_tick": _q([x["static_done_tick"] for x in grp if x["static_done_tick"] is not None]),
            "ends": _count(x["end"] for x in grp),
        }
    return res


def _count(vals: Any) -> Dict[str, int]:
    c: Dict[str, int] = {}
    for v in vals:
        c[str(v)] = c.get(str(v), 0) + 1
    return dict(sorted(c.items(), key=lambda kv: -kv[1]))


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="M7k target-2 analysis")
    p.add_argument("what", choices=("select", "replay", "analyze"))
    p.add_argument("--out", required=True)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--limit", type=int, default=None)
    a = p.parse_args(argv)
    out = Path(a.out) if Path(a.out).is_absolute() else REPO_ROOT / a.out
    if a.what == "select":
        s = select()
        write_json(out / "selection.json", s)
        print(json.dumps({"counts": s["counts"], "episodes": s["episodes"]}))
        return 0
    if a.what == "replay":
        s = run_replays(out, a.workers, a.limit)
        print(json.dumps({k: v for k, v in s.items() if k != "failures"} | {"failures": s["failures"][:5]}))
        return 0 if not s["failures"] else 1
    r = analyze(out)
    write_json(out / f"analysis_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json", r)
    print(json.dumps({k: v for k, v in r.items() if k not in ("episodes", "platform")} |
                     {"platform": {k: v for k, v in r["platform"].items() if k != "table_every_25"}}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
