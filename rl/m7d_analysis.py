#!/usr/bin/env python3
"""M7d: statistics, the pre-registered decision rule and the machine-readable comparison report.

    python rl/m7d_analysis.py --out docs/rl_reward_comparison_m7d.json

Reads only what the trainer, the evaluator, the orchestrator and the replay
step wrote under runs/m7d/ (plus the manifest); launches nothing. Gameplay
outcomes decide (verified clears, then targets, then completion time);
reward totals are reported as diagnostics only because the btt_reward_v1 and
btt_reward_v2 scales differ (a v2 fall carries an extra -5.0).

Statistics: percentile bootstrap (10,000 resamples, numpy default_rng with a
fixed seed per statistic) of differences of means / proportions between the
two runs of a seed (episodes resampled independently within each run), a
seed-stratified bootstrap for the aggregate (episodes resampled within each of
the six runs, the aggregate is the mean of the three per-seed differences) and,
as a more conservative view, a seed-cluster bootstrap (seeds resampled with
replacement, then episodes). Effect sizes: Cohen's h for rates, Cliff's delta
for target counts and objective keys, Cohen's d for target counts.
"""

from __future__ import annotations

import argparse
import math
import os
import statistics
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import m7d_matrix as mm  # noqa: E402

TARGETS_TOTAL = 10
HORIZON = 3600
LEVEL = mm.BOOTSTRAP_LEVEL
RESAMPLES = mm.BOOTSTRAP_RESAMPLES


# -- per-episode metrics -------------------------------------------------------------------------------------------


def episode_metrics(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Objective and behavioural facts of one evaluation row (evaluation.json) or training row (episodes.jsonl)."""
    steps = int(row.get("length", row.get("steps")))
    targets = int(row["targets_broken"])
    end = row["end_reason"]
    ticks = row.get("target_break_ticks")
    last = max(ticks) if ticks else None
    idle_tail = steps - (last + 1) if last is not None else steps
    clear = end == "clear" and bool(row.get("cleared")) and row.get("completion_time_passed") is not None
    return {
        "targets": targets, "steps": steps, "end_reason": end, "clear": clear, "fall": end == "fall",
        "horizon": end == "horizon", "lifecycle_failure": end == "lifecycle_failure",
        "completion_time_passed": row.get("completion_time_passed") if clear else None,
        "completion_input_tick": row.get("completion_input_tick") if clear else None,
        "idle_tail": idle_tail if ticks is not None else None,
        "idle": (end == "horizon" and idle_tail >= mm.IDLE_TAIL_TICKS) if ticks is not None else None,
        "first_target_tick": min(ticks) if ticks else None,
        "targets_per_1000_ticks": 1000.0 * targets / steps,
        "objective_key": (1, TARGETS_TOTAL, -int(row["completion_time_passed"])) if clear else (0, targets, 0),
        "return": float(row.get("raw_return", row.get("return", 0.0))),
        "native_action_digest": row.get("native_action_digest"),
    }


def _q(xs: Sequence[float], p: float) -> Optional[float]:
    if not xs:
        return None
    return float(np.quantile(np.asarray(xs, dtype=np.float64), p))


# -- bootstrap -----------------------------------------------------------------------------------------------------------


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def bootstrap_mean(values: Sequence[float], *, seed: int = 0) -> Optional[List[float]]:
    if len(values) < 2:
        return None
    x = np.asarray(values, dtype=np.float64)
    m = x[_rng(seed).integers(0, len(x), size=(RESAMPLES, len(x)))].mean(axis=1)
    lo, hi = np.quantile(m, [(1 - LEVEL) / 2, 1 - (1 - LEVEL) / 2])
    return [round(float(lo), 4), round(float(hi), 4)]


def bootstrap_diff(a: Sequence[float], b: Sequence[float], *, seed: int = 0) -> Dict[str, Any]:
    """mean(b) - mean(a) with independent resampling (a = v1, b = v2)."""
    x, y = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    if len(x) < 2 or len(y) < 2:
        return {"diff": None, "ci": None}
    rng = _rng(seed)
    dx = x[rng.integers(0, len(x), size=(RESAMPLES, len(x)))].mean(axis=1)
    dy = y[rng.integers(0, len(y), size=(RESAMPLES, len(y)))].mean(axis=1)
    lo, hi = np.quantile(dy - dx, [(1 - LEVEL) / 2, 1 - (1 - LEVEL) / 2])
    return {"diff": round(float(y.mean() - x.mean()), 4), "ci": [round(float(lo), 4), round(float(hi), 4)]}


def stratified_diff(pairs: Sequence[Tuple[Sequence[float], Sequence[float]]], *, seed: int = 0) -> Dict[str, Any]:
    """Mean over strata (seeds) of mean(b_s) - mean(a_s); episodes resampled within each run."""
    rng = _rng(seed)
    point = statistics.fmean(float(np.mean(b)) - float(np.mean(a)) for a, b in pairs)
    acc = np.zeros(RESAMPLES)
    for a, b in pairs:
        x, y = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
        acc += y[rng.integers(0, len(y), size=(RESAMPLES, len(y)))].mean(axis=1) - \
            x[rng.integers(0, len(x), size=(RESAMPLES, len(x)))].mean(axis=1)
    acc /= len(pairs)
    lo, hi = np.quantile(acc, [(1 - LEVEL) / 2, 1 - (1 - LEVEL) / 2])
    return {"diff": round(point, 4), "ci": [round(float(lo), 4), round(float(hi), 4)], "method": "seed-stratified"}


def cluster_diff(pairs: Sequence[Tuple[Sequence[float], Sequence[float]]], *, seed: int = 0) -> Dict[str, Any]:
    """Seeds resampled with replacement, then episodes within each chosen seed (conservative; only 3 seeds)."""
    rng = _rng(seed)
    k = len(pairs)
    arrs = [(np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)) for a, b in pairs]
    out = np.empty(RESAMPLES)
    for i in range(RESAMPLES):
        picks = rng.integers(0, k, size=k)
        vals = []
        for j in picks:
            x, y = arrs[j]
            vals.append(y[rng.integers(0, len(y), size=len(y))].mean() - x[rng.integers(0, len(x), size=len(x))].mean())
        out[i] = float(np.mean(vals))
    lo, hi = np.quantile(out, [(1 - LEVEL) / 2, 1 - (1 - LEVEL) / 2])
    return {"ci": [round(float(lo), 4), round(float(hi), 4)], "method": "seed-cluster (3 seeds: 10 distinct seed multisets)"}


# -- effect sizes ----------------------------------------------------------------------------------------------------------


def cohen_h(p_a: float, p_b: float) -> float:
    return round(2 * math.asin(math.sqrt(p_b)) - 2 * math.asin(math.sqrt(p_a)), 4)


def cohen_d(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    if len(a) < 2 or len(b) < 2:
        return None
    va, vb = statistics.variance(a), statistics.variance(b)
    pooled = math.sqrt(((len(a) - 1) * va + (len(b) - 1) * vb) / (len(a) + len(b) - 2))
    return None if pooled == 0 else round((statistics.fmean(b) - statistics.fmean(a)) / pooled, 4)


def cliffs_delta(a: Sequence[Any], b: Sequence[Any]) -> float:
    """P(b > a) - P(b < a) over all pairs (works for tuples: objective keys)."""
    gt = lt = 0
    for x in a:
        for y in b:
            if y > x:
                gt += 1
            elif y < x:
                lt += 1
    return round((gt - lt) / (len(a) * len(b)), 4)


# -- summaries of one evaluation set ---------------------------------------------------------------------------------------


def summarize_mode(rows: Sequence[Mapping[str, Any]], *, seed: int = 0) -> Dict[str, Any]:
    ms = [episode_metrics(r) for r in rows]
    n = len(ms)
    if n == 0:
        return {"episodes": 0}
    t = [m["targets"] for m in ms]
    steps = [m["steps"] for m in ms]
    clears = [m for m in ms if m["clear"]]
    falls = [m for m in ms if m["fall"]]
    horizon = [m for m in ms if m["horizon"]]
    incomplete = [m for m in ms if not m["clear"]]
    idle_known = [m for m in ms if m["idle"] is not None]
    tails = [m["idle_tail"] for m in ms if m["idle_tail"] is not None]
    horizon_tails = [m["idle_tail"] for m in horizon if m["idle_tail"] is not None]
    first = [m["first_target_tick"] for m in ms if m["first_target_tick"] is not None]
    best_incomplete = max(incomplete, key=lambda m: (m["targets"], -m["steps"])) if incomplete else None
    digests = {m["native_action_digest"] for m in ms}
    return {
        "episodes": n,
        "clears": len(clears), "clear_rate": round(len(clears) / n, 4),
        "clear_rate_ci95": bootstrap_mean([1.0 if m["clear"] else 0.0 for m in ms], seed=seed),
        "completion_clocks": [{"completion_time_passed": m["completion_time_passed"],
                               "completion_input_tick": m["completion_input_tick"]} for m in clears],
        "fastest_clear": None if not clears else min(({"completion_time_passed": m["completion_time_passed"],
                                                       "completion_input_tick": m["completion_input_tick"]} for m in clears),
                                                     key=lambda c: c["completion_time_passed"]),
        "targets_mean": round(statistics.fmean(t), 4), "targets_mean_ci95": bootstrap_mean(t, seed=seed),
        "targets_median": statistics.median(t), "targets_max": max(t), "targets_min": min(t),
        "targets_std": round(statistics.pstdev(t), 4),
        "targets_histogram": {str(k): t.count(k) for k in range(TARGETS_TOTAL + 1)},
        "falls": len(falls), "fall_rate": round(len(falls) / n, 4),
        "fall_rate_ci95": bootstrap_mean([1.0 if m["fall"] else 0.0 for m in ms], seed=seed + 1),
        "horizon_truncations": len(horizon), "horizon_rate": round(len(horizon) / n, 4),
        "lifecycle_failures": sum(1 for m in ms if m["lifecycle_failure"]),
        "idle": {"definition": f"horizon episode with >= {mm.IDLE_TAIL_TICKS} ticks after its last target break (or none)",
                 "episodes_with_break_ticks": len(idle_known),
                 "idle_episodes": sum(1 for m in idle_known if m["idle"]),
                 "idle_rate": round(sum(1 for m in idle_known if m["idle"]) / len(idle_known), 4) if idle_known else None,
                 "idle_tail_mean": round(statistics.fmean(tails), 1) if tails else None,
                 "horizon_idle_tail_mean": round(statistics.fmean(horizon_tails), 1) if horizon_tails else None,
                 "zero_target_episodes": t.count(0),
                 "first_target_tick_median": statistics.median(first) if first else None,
                 "targets_per_1000_ticks_mean": round(statistics.fmean(m["targets_per_1000_ticks"] for m in ms), 4)},
        "length": {"mean": round(statistics.fmean(steps), 1), "median": statistics.median(steps), "min": min(steps),
                   "max": max(steps), "p10": _q(steps, 0.1), "p90": _q(steps, 0.9)},
        "best_incomplete": None if best_incomplete is None else {"targets": best_incomplete["targets"],
                                                                 "steps": best_incomplete["steps"],
                                                                 "end_reason": best_incomplete["end_reason"]},
        "return_mean_diagnostic": round(statistics.fmean(m["return"] for m in ms), 4),
        "distinct_action_digests": len(digests),
        "anomaly_events": sum(int(r.get("anomaly_events") or 0) for r in rows),
        "startup_modes": {k: sum(1 for r in rows if r.get("startup_mode") == k)
                          for k in ("cold_start", "standby_promoted", "cold_fallback")},
    }


def learning_evidence(final: Sequence[int], initial: Sequence[int], random_baseline: Sequence[int]) -> Dict[str, Any]:
    """The M7a rule (m7_evaluation.learning_evidence): mean targets of the final stochastic policy above both the
    initial policy and the random baseline, 95 % bootstrap CI of each difference > 0."""
    vs_i = bootstrap_diff(initial, final, seed=11)
    vs_r = bootstrap_diff(random_baseline, final, seed=12)
    ok = bool(vs_i["ci"] and vs_r["ci"] and vs_i["ci"][0] > 0 and vs_r["ci"][0] > 0)
    return {"vs_initial": vs_i, "vs_random": vs_r, "learning_supported": ok}


# -- the pre-registered decision rule ----------------------------------------------------------------------------------------


def paired_statistics(per_seed: Mapping[int, Mapping[str, Sequence[Mapping[str, Any]]]]) -> Dict[str, Any]:
    """per_seed[s] = {"v1": rows, "v2": rows} (final stochastic evaluation rows). Returns D_s, F_s, C_s, I_s and the
    aggregate D, F, C, I with their intervals (definitions in m7d_matrix.DECISION_RULE)."""
    seeds = sorted(per_seed)
    out: Dict[str, Any] = {"per_seed": {}, "aggregate": {}}
    pairs: Dict[str, List[Tuple[List[float], List[float]]]] = {"targets": [], "fall": [], "idle": [], "clear": [],
                                                                "horizon": []}
    for i, s in enumerate(seeds):
        m1 = [episode_metrics(r) for r in per_seed[s]["v1"]]
        m2 = [episode_metrics(r) for r in per_seed[s]["v2"]]
        vals = {
            "targets": ([m["targets"] for m in m1], [m["targets"] for m in m2]),
            "fall": ([float(m["fall"]) for m in m1], [float(m["fall"]) for m in m2]),
            "idle": ([float(bool(m["idle"])) for m in m1], [float(bool(m["idle"])) for m in m2]),
            "clear": ([float(m["clear"]) for m in m1], [float(m["clear"]) for m in m2]),
            "horizon": ([float(m["horizon"]) for m in m1], [float(m["horizon"]) for m in m2]),
        }
        for k, v in vals.items():
            pairs[k].append(v)
        d = bootstrap_diff(*vals["targets"], seed=100 + i)
        f = bootstrap_diff(*vals["fall"], seed=200 + i)
        idle = bootstrap_diff(*vals["idle"], seed=300 + i)
        hz = bootstrap_diff(*vals["horizon"], seed=400 + i)
        c = int(sum(vals["clear"][1]) - sum(vals["clear"][0]))
        p1f, p2f = statistics.fmean(vals["fall"][0]), statistics.fmean(vals["fall"][1])
        out["per_seed"][str(s)] = {
            "D_s": d, "F_s": f, "I_s": idle, "horizon_rate_diff": hz, "C_s": c,
            "clears": {"v1": int(sum(vals["clear"][0])), "v2": int(sum(vals["clear"][1]))},
            "targets_mean": {"v1": round(statistics.fmean(vals["targets"][0]), 4),
                             "v2": round(statistics.fmean(vals["targets"][1]), 4)},
            "fall_rate": {"v1": round(p1f, 4), "v2": round(p2f, 4)},
            "effect_sizes": {"cohen_h_fall": cohen_h(p1f, p2f),
                             "cohen_d_targets": cohen_d(vals["targets"][0], vals["targets"][1]),
                             "cliffs_delta_targets": cliffs_delta(vals["targets"][0], vals["targets"][1]),
                             "cliffs_delta_objective": cliffs_delta([m["objective_key"] for m in m1],
                                                                    [m["objective_key"] for m in m2])},
            "relative": {"targets_pct": _rel(statistics.fmean(vals["targets"][0]), statistics.fmean(vals["targets"][1])),
                         "fall_rate_pct": _rel(p1f, p2f)},
        }
    agg = out["aggregate"]
    agg["D"] = dict(stratified_diff(pairs["targets"], seed=500), cluster=cluster_diff(pairs["targets"], seed=501))
    agg["F"] = dict(stratified_diff(pairs["fall"], seed=600), cluster=cluster_diff(pairs["fall"], seed=601))
    agg["I"] = dict(stratified_diff(pairs["idle"], seed=700), cluster=cluster_diff(pairs["idle"], seed=701))
    agg["horizon_rate"] = stratified_diff(pairs["horizon"], seed=800)
    agg["C"] = sum(v["C_s"] for v in out["per_seed"].values())
    all1 = [x for a, _b in pairs["targets"] for x in a]
    all2 = [x for _a, b in pairs["targets"] for x in b]
    f1 = [x for a, _b in pairs["fall"] for x in a]
    f2 = [x for _a, b in pairs["fall"] for x in b]
    agg["pooled"] = {"targets_mean": {"v1": round(statistics.fmean(all1), 4), "v2": round(statistics.fmean(all2), 4)},
                     "fall_rate": {"v1": round(statistics.fmean(f1), 4), "v2": round(statistics.fmean(f2), 4)},
                     "cohen_h_fall": cohen_h(statistics.fmean(f1), statistics.fmean(f2)),
                     "cohen_d_targets": cohen_d(all1, all2), "cliffs_delta_targets": cliffs_delta(all1, all2)}
    agg["sign_consistency"] = {
        "targets_up": sum(1 for v in out["per_seed"].values() if v["D_s"]["diff"] > 0),
        "falls_down": sum(1 for v in out["per_seed"].values() if v["F_s"]["diff"] < 0),
        "seeds": len(seeds)}
    return out


def _rel(a: float, b: float) -> Optional[float]:
    return None if a == 0 else round(100.0 * (b - a) / a, 2)


def decide(stats: Mapping[str, Any], margin: float = mm.NON_INFERIORITY_TARGETS) -> Dict[str, Any]:
    """Apply m7d_matrix.DECISION_RULE (registered before any M7d data existed)."""
    ps = stats["per_seed"]
    agg = stats["aggregate"]
    D, F, I, C = agg["D"], agg["F"], agg["I"], int(agg["C"])
    c_s = [int(v["C_s"]) for v in ps.values()]
    d_sig = sum(1 for v in ps.values() if v["D_s"]["ci"] and v["D_s"]["ci"][0] > 0)
    f_sig = sum(1 for v in ps.values() if v["F_s"]["ci"] and v["F_s"]["ci"][1] < 0)
    cond = {
        "v1_fewer_clears_aggregate": C < 0,
        "v1_significantly_fewer_targets": D["ci"][1] < 0,
        "v1_targets_for_survival": D["diff"] < -margin and F["ci"][1] < 0,
        "v2_more_clears": C > 0 and all(c >= 0 for c in c_s),
        "v2_more_targets": D["ci"][0] > 0 and d_sig >= 2,
        "v2_fewer_falls_non_inferior": (D["ci"][0] > -margin and C >= 0 and F["ci"][1] < 0 and f_sig >= 2
                                        and I["ci"][0] <= 0),
    }
    counts = {"seeds_with_significant_target_gain": d_sig, "seeds_with_significant_fall_reduction": f_sig}
    if cond["v1_fewer_clears_aggregate"] or cond["v1_significantly_fewer_targets"] or cond["v1_targets_for_survival"]:
        verdict = "v1 retained"
    elif cond["v2_more_clears"] or cond["v2_more_targets"] or cond["v2_fewer_falls_non_inferior"]:
        verdict = "v2 preferred"
    else:
        verdict = "inconclusive - more evidence required"
    return {"classification": verdict, "conditions": cond, "counts": counts, "rule_id": mm.DECISION_RULE["rule_id"],
            "margin_targets": margin}


# -- report ------------------------------------------------------------------------------------------------------------------


def _eval_summary(spec: mm.RunSpec, label: str) -> Optional[Dict[str, Any]]:
    p = spec.eval_dir / label / "evaluation_summary.json"
    return mm.read_json(p) if p.is_file() else None


def _mode_rows(summary: Optional[Mapping[str, Any]], mode: str) -> List[Dict[str, Any]]:
    if not summary:
        return []
    return list(((summary.get("modes") or {}).get(mode) or {}).get("episodes") or [])


def training_windows(rows: Sequence[Mapping[str, Any]], window: int = 51_200) -> List[Dict[str, Any]]:
    buckets: Dict[int, List[Mapping[str, Any]]] = {}
    for r in rows:
        t = int(r.get("sb3_num_timesteps_seen") or 0)
        buckets.setdefault(max(t - 1, 0) // window, []).append(r)
    out = []
    for k in sorted(buckets):
        ms = [episode_metrics(r) for r in buckets[k]]
        n = len(ms)
        out.append({"transitions_from": k * window, "transitions_to": (k + 1) * window, "episodes": n,
                    "targets_mean": round(statistics.fmean(m["targets"] for m in ms), 4),
                    "targets_max": max(m["targets"] for m in ms),
                    "fall_rate": round(sum(m["fall"] for m in ms) / n, 4),
                    "horizon_rate": round(sum(m["horizon"] for m in ms) / n, 4),
                    "clears": sum(m["clear"] for m in ms),
                    "length_mean": round(statistics.fmean(m["steps"] for m in ms), 1),
                    "idle_rate": round(sum(1 for m in ms if m["idle"]) / n, 4),
                    "return_mean_diagnostic": round(statistics.fmean(m["return"] for m in ms), 4)})
    return out


def _run_segments(spec: mm.RunSpec, state: Mapping[str, Any]) -> List[Path]:
    rs = (state.get("runs") or {}).get(spec.name) or {}
    segs = [spec.run_dir] + [mm.REPO_ROOT / s["run_dir"] for s in rs.get("lineage") or []]
    return [s for s in segs if (s / "training_summary.json").is_file()]


def training_section(spec: mm.RunSpec, state: Mapping[str, Any]) -> Dict[str, Any]:
    from m7d_run import jsonl_rows

    segs = _run_segments(spec, state)
    if not segs:
        return {"available": False}
    rs = (state.get("runs") or {}).get(spec.name) or {}
    summaries = [mm.read_json(s / "training_summary.json") for s in segs]
    rows: List[Dict[str, Any]] = []
    for s in segs:
        rows.extend(jsonl_rows(s / "metrics" / "episodes.jsonl")[0])
    last = summaries[-1]
    ms = [episode_metrics(r) for r in rows]
    t = [m["targets"] for m in ms]
    clears = [m for m in ms if m["clear"]]
    lifecycle = last.get("lifecycle") or {}
    sb = lifecycle.get("standby") or {}
    seg_state = [rs.get("segment")] + list(rs.get("lineage") or [])
    monitors = [s["result"]["monitor"] for s in seg_state if s and s.get("result")]
    return {
        "available": True, "segments": [mm.ec.repo_relative(s) for s in segs],
        "interrupted_or_resumed": len(segs) > 1, "status": [s.get("status") for s in summaries],
        "created_utc": summaries[0].get("created_utc"), "finished_utc": last.get("finished_utc"),
        "wall_run_s": sum((s.get("wall") or {}).get("run_total_s") or 0 for s in summaries),
        "wall_learn_s": sum((s.get("wall") or {}).get("learn_s") or 0 for s in summaries),
        "transitions": sum((s.get("timesteps") or {}).get("transitions_this_run") or 0 for s in summaries),
        "sb3_num_timesteps": (last.get("timesteps") or {}).get("sb3_num_timesteps"),
        "rollouts": sum((s.get("timesteps") or {}).get("rollouts") or 0 for s in summaries),
        "end_to_end_transitions_per_s": [(s.get("throughput") or {}).get("end_to_end_transitions_per_s") for s in summaries],
        "collection_transitions_per_s": [(s.get("throughput") or {}).get("collection_transitions_per_s") for s in summaries],
        "time_split": last.get("time_split"),
        "episodes": {"started": sum((s.get("episodes") or {}).get("started") or 0 for s in summaries),
                     "finished": len(rows), "clears": len(clears), "falls": sum(m["fall"] for m in ms),
                     "horizon": sum(m["horizon"] for m in ms),
                     "lifecycle_failures": sum(m["lifecycle_failure"] for m in ms),
                     "abnormal": sum(1 for m in ms if m["end_reason"] not in ("clear", "fall", "horizon")),
                     "targets_mean": round(statistics.fmean(t), 4) if t else None, "targets_max": max(t) if t else None,
                     "targets_histogram": {str(k): t.count(k) for k in range(TARGETS_TOTAL + 1)},
                     "completion_clocks": [{"completion_time_passed": m["completion_time_passed"],
                                            "completion_input_tick": m["completion_input_tick"]} for m in clears],
                     "penalty_terms": sum(int(r.get("failure_penalty_terms") or 0) for r in rows),
                     "anomaly_events": sum(int(r.get("anomaly_events") or 0) for r in rows)},
        "lifecycle": {"reset_modes": lifecycle.get("reset_modes"), "promotions": sb.get("promotions"),
                      "hits_ready_at_reset": sb.get("hits_ready_at_reset"), "late_hits_waited": sb.get("late_hits_waited"),
                      "cold_fallbacks": sb.get("cold_fallbacks"), "fallback_reasons": sb.get("fallback_reasons"),
                      "exposed_wait_s_total": sb.get("exposed_wait_s_total"),
                      "hidden_startup_s_total": sb.get("hidden_startup_s_total"),
                      "standby_startup_s": sb.get("standby_startup_s"),
                      "standby_failed_attempts": sb.get("standby_failed_attempts"),
                      "standby_failures": sb.get("standby_failures"), "standby_lost": sb.get("standby_lost"),
                      "standby_wait_timeouts": sb.get("standby_wait_timeouts"), "threads": sb.get("threads"),
                      "observed_max_concurrent_per_worker": lifecycle.get("observed_max_concurrent_per_worker"),
                      "expected_max_game_processes": lifecycle.get("expected_max_game_processes")},
        "restarts": {k: v for k, v in (last.get("restarts") or {}).items() if k != "startup_failures"},
        "failures": last.get("failures"),
        "latency": last.get("latency"),
        "cpu": last.get("cpu"),
        "memory": {k: v for k, v in (last.get("memory") or {}).items() if k in (
            "game_process_peak_working_set_mib_max", "game_process_private_mib_max")},
        "monitor": [{k: m.get(k) for k in ("samples", "max_battleship_processes", "max_battleship_listeners", "cpu_util",
                                            "avail_phys_gib", "commit_used_gib", "avail_commit_gib", "disk_free_gib",
                                            "cold_fallbacks_after_first", "startup_failures", "anomalies",
                                            "lifecycle_failures", "hard_alerts", "soft_alert_count")} for m in monitors],
        "artifacts": {"preserved": sum((s.get("artifacts") or {}).get("preserved") or 0 for s in summaries),
                      "discarded": sum((s.get("artifacts") or {}).get("discarded") or 0 for s in summaries)},
        "checkpoints": sum(len(s.get("checkpoints") or []) for s in summaries),
        "cleanup_leak_free": all((s.get("cleanup") or {}).get("leak_free") for s in summaries),
        "user_config_byte_identical": all((s.get("user_config") or {}).get("byte_identical") for s in summaries),
        "lineage": (mm.read_json(segs[-1] / "run.json") or {}).get("lineage"),
        "windows": training_windows(rows),
        "rollout_curve": _rollout_curve(segs),
        "verification": rs.get("verification"),
        "status_in_matrix": rs.get("status"),
    }


def _rollout_curve(segs: Sequence[Path]) -> List[Dict[str, Any]]:
    from m7d_run import jsonl_rows

    out = []
    for s in segs:
        for r in jsonl_rows(s / "metrics" / "rollouts.jsonl")[0]:
            tm = r.get("train_metrics") or {}
            out.append({"num_timesteps": r.get("num_timesteps"), "episodes_finished": r.get("episodes_finished"),
                        "targets_mean": r.get("targets_mean"), "end_reasons": r.get("end_reasons"),
                        "collect_s": r.get("collect_s"), "entropy_loss": tm.get("train/entropy_loss"),
                        "approx_kl": tm.get("train/approx_kl"), "explained_variance": tm.get("train/explained_variance"),
                        "clip_fraction": tm.get("train/clip_fraction")})
    return out


def evaluation_section(spec: mm.RunSpec, random_targets: Sequence[int]) -> Dict[str, Any]:
    exp = mm.load_run(spec)
    out: Dict[str, Any] = {"points": []}
    for plan in mm.evaluation_plan(spec, exp):
        s = _eval_summary(spec, plan["label"])
        if s is None:
            out["points"].append({"label": plan["label"], "num_timesteps": plan["num_timesteps"], "available": False})
            continue
        point = {"label": plan["label"], "num_timesteps": s.get("checkpoint_num_timesteps"), "available": True,
                 "checkpoint": s.get("checkpoint"), "reward_contract": (s.get("reward_contract") or {}).get("contract"),
                 "wall_s": s.get("wall_s")}
        for mode in ("deterministic", "stochastic"):
            r = (s.get("modes") or {}).get(mode) or {}
            point[mode] = dict(summarize_mode(r.get("episodes") or [], seed=17),
                               frozen_check=r.get("frozen_check"),
                               deterministic_identical=r.get("deterministic_episodes_identical"),
                               startup_failures=r.get("startup_failures"),
                               workers_closed_cleanly=r.get("workers_closed_cleanly"),
                               reset_modes=(r.get("lifecycle") or {}).get("timing_reset_modes"),
                               excess_episodes_not_counted=r.get("excess_episodes_not_counted"),
                               wall_s=r.get("wall_s"))
        out["points"].append(point)
    init, final = _eval_summary(spec, "initial"), _eval_summary(spec, "final")
    if init and final:
        out["learning_evidence"] = learning_evidence(
            [int(r["targets_broken"]) for r in _mode_rows(final, "stochastic")],
            [int(r["targets_broken"]) for r in _mode_rows(init, "stochastic")], random_targets)
    return out


def clear_witnesses(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Count clears in one episode set through four independent recorded facts: the end reason, the
    `cleared` flag, ten broken targets and a completion clock. A clear is counted only when all four
    agree (`episode_metrics` already requires end reason + flag + clock)."""
    end = sum(1 for r in rows if r.get("end_reason") == "clear")
    flag = sum(1 for r in rows if bool(r.get("cleared")))
    ten = sum(1 for r in rows if int(r.get("targets_broken") or 0) >= TARGETS_TOTAL)
    clock = sum(1 for r in rows if r.get("completion_time_passed") is not None)
    verified = sum(1 for r in rows if episode_metrics(r)["clear"] and int(r["targets_broken"]) >= TARGETS_TOTAL)
    return {"verified_clears": verified, "witnesses": {"end_reason_clear": end, "cleared_flag": flag,
                                                       "ten_targets_broken": ten, "completion_clock": clock},
            "witnesses_agree": len({verified, end, flag, ten, clock}) == 1,
            "targets_max": max((int(r.get("targets_broken") or 0) for r in rows), default=None)}


def _census_row(category: str, mode: str, sessions: Sequence[Mapping[str, Any]], *, planned: int,
                in_primary_endpoint: bool, note: str) -> Dict[str, Any]:
    rows: List[Mapping[str, Any]] = []
    for s in sessions:
        rows.extend(s["rows"])
    per = sorted({int(s["episodes"]) for s in sessions})
    return dict({"category": category, "mode": mode, "evaluations": len(sessions),
                 "models_or_checkpoints": len({(s["run"], s["checkpoint"]) for s in sessions}),
                 "models": len({s["run"] for s in sessions}),
                 "episodes_per_evaluation": per, "episodes_planned": planned, "episodes_total": len(rows),
                 "episode_rows_preserved": len(rows),
                 "complete": len(rows) == planned,
                 "excess_episodes_not_counted": sum(int(s.get("excess") or 0) for s in sessions),
                 "in_primary_endpoint": in_primary_endpoint, "note": note},
                **clear_witnesses(rows))


def episode_census() -> Dict[str, Any]:
    """Exact accounting of every episode M7d played: the approved initial and final evaluation sets, the
    intermediate (learning-curve) evaluations, the random Track-1 baseline and training.

    Counts are taken from the per-episode rows written to disk - every M7d evaluation ran with
    `preserve_all`, so each session's rows are complete - never from a narrative summary. `episodes_planned`
    comes from `m7d_matrix.evaluation_plan`, so an evaluation set that was never run shows up as a shortfall
    instead of silently disappearing."""
    specs = mm.matrix()
    sessions: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    planned: Dict[Tuple[str, str], int] = {}
    missing: List[Dict[str, Any]] = []
    for spec in specs:
        exp = mm.load_run(spec)
        for plan in mm.evaluation_plan(spec, exp):
            category = "curve" if plan["label"].startswith("curve_") else plan["label"]
            summary = _eval_summary(spec, plan["label"])
            for mode in ("stochastic", "deterministic"):
                key = (category, mode)
                planned[key] = planned.get(key, 0) + int(plan[f"{mode}_episodes"])
                if summary is None:
                    missing.append({"run": spec.name, "label": plan["label"], "mode": mode,
                                    "episodes_planned": int(plan[f"{mode}_episodes"])})
                    continue
                md = (summary.get("modes") or {}).get(mode) or {}
                sessions.setdefault(key, []).append(
                    {"run": spec.name, "checkpoint": summary.get("checkpoint"),
                     "num_timesteps": summary.get("checkpoint_num_timesteps"),
                     "episodes": len(md.get("episodes") or []), "rows": md.get("episodes") or [],
                     "excess": md.get("excess_episodes_not_counted")})
    notes = {
        ("initial", "stochastic"): "untrained policy (ckpt_000000000); learning-evidence denominator and the "
                                   "pairing check (v1 and v2 of a seed must be identical here)",
        ("initial", "deterministic"): "untrained policy; pairing check only",
        ("curve", "stochastic"): "9 intermediate checkpoints per run (every 102,400 transitions); learning curve",
        ("curve", "deterministic"): "9 intermediate checkpoints per run; learning curve",
        ("final", "stochastic"): "PRIMARY ENDPOINT of the pre-registered decision rule",
        ("final", "deterministic"): "secondary endpoint (greedy policy)",
    }
    out_rows = [_census_row(cat, mode, sessions.get((cat, mode)) or [], planned=planned[(cat, mode)],
                            in_primary_endpoint=(cat, mode) == ("final", "stochastic"),
                            note=notes[(cat, mode)])
                for cat in ("initial", "curve", "final") for mode in ("stochastic", "deterministic")]
    rnd = mm.EVAL_ROOT / "random_baseline" / "evaluation_summary.json"
    if rnd.is_file():
        doc = mm.read_json(rnd)
        md = (doc.get("modes") or {}).get("random") or {}
        out_rows.append(_census_row(
            "random_baseline", "random",
            [{"run": "random_baseline", "checkpoint": None, "episodes": len(md.get("episodes") or []),
              "rows": md.get("episodes") or [], "excess": md.get("excess_episodes_not_counted")}],
            planned=int(mm.FINAL_EPISODES["stochastic"]), in_primary_endpoint=False,
            note="Track-1 uniform random policy, no model; learning-evidence floor and M7a cross-check"))
    training: List[Mapping[str, Any]] = []
    started = 0
    from m7d_run import jsonl_rows, load_state

    state = load_state()
    for spec in specs:
        for seg in _run_segments(spec, state):
            training.extend(jsonl_rows(seg / "metrics" / "episodes.jsonl")[0])
            started += int(((mm.read_json(seg / "training_summary.json") or {}).get("episodes") or {}).get("started") or 0)
    train_row = dict({"category": "training", "mode": "on-policy rollout collection", "evaluations": len(specs),
                      "models_or_checkpoints": len(specs), "models": len(specs), "episodes_per_evaluation": [],
                      "episodes_planned": None, "episodes_total": len(training),
                      "episode_rows_preserved": len(training), "complete": True,
                      "episodes_started": started, "in_primary_endpoint": False,
                      "note": "not an evaluation: episodes played while learning (started - finished = the "
                              "episodes still in flight when each run reached its transition budget)"},
                     **clear_witnesses(training))
    evaluation_total = sum(r["episodes_total"] for r in out_rows)
    return {
        "evaluation": out_rows, "training": train_row,
        "missing_evaluations": missing,
        "totals": {"evaluation_sessions": sum(r["evaluations"] for r in out_rows),
                   "evaluation_episodes": evaluation_total,
                   "evaluation_episodes_planned": sum(r["episodes_planned"] for r in out_rows),
                   "training_episodes": len(training),
                   "all_episodes": evaluation_total + len(training),
                   "verified_clears_evaluation": sum(r["verified_clears"] for r in out_rows),
                   "verified_clears_training": train_row["verified_clears"],
                   "verified_clears_total": sum(r["verified_clears"] for r in out_rows) + train_row["verified_clears"],
                   "targets_max_anywhere": max([r["targets_max"] for r in out_rows if r["targets_max"] is not None]
                                               + [train_row["targets_max"] or 0])},
        "protocol_complete": not missing and all(r["complete"] for r in out_rows),
        "note": "The decision rule reads only the 'final stochastic' row. Every other row is context: the "
                "initial sets anchor learning evidence and prove the pairing, the curve sets are the learning "
                "curve, the random baseline is the floor, and training episodes are not evaluations.",
    }


def build_report() -> Dict[str, Any]:
    from m7d_run import load_state

    state = load_state()
    manifest = mm.read_json(mm.MANIFEST_DOC)
    random_summary = mm.read_json(mm.EVAL_ROOT / "random_baseline" / "evaluation_summary.json") \
        if (mm.EVAL_ROOT / "random_baseline" / "evaluation_summary.json").is_file() else None
    random_rows = _mode_rows(random_summary, "random")
    random_targets = [int(r["targets_broken"]) for r in random_rows]
    specs = mm.matrix()
    runs: Dict[str, Any] = {}
    for spec in specs:
        runs[spec.name] = {"seed": spec.seed, "reward": spec.reward, "order_index": spec.order_index,
                           "training": training_section(spec, state),
                           "evaluation": evaluation_section(spec, random_targets)}
        rp = spec.replay_dir / "replay.json"
        runs[spec.name]["replay"] = mm.read_json(rp) if rp.is_file() else None
    # Paired comparisons.
    final_rows = {s.name: _mode_rows(_eval_summary(s, "final"), "stochastic") for s in specs}
    det_rows = {s.name: _mode_rows(_eval_summary(s, "final"), "deterministic") for s in specs}
    init_rows = {s.name: {m: _mode_rows(_eval_summary(s, "initial"), m) for m in ("deterministic", "stochastic")}
                 for s in specs}
    complete = all(final_rows[s.name] for s in specs)
    comparison: Dict[str, Any] = {"complete": complete}
    if complete:
        per_seed = {seed: {"v1": final_rows[f"m7d_s{seed}_v1"], "v2": final_rows[f"m7d_s{seed}_v2"]} for seed in mm.SEEDS}
        stats = paired_statistics(per_seed)
        comparison["final_stochastic"] = stats
        comparison["decision"] = decide(stats)
        comparison["deterministic"] = {
            str(seed): {r: summarize_mode(det_rows[f"m7d_s{seed}_{r}"], seed=19) for r in ("v1", "v2")}
            for seed in mm.SEEDS}
        comparison["deterministic_objective"] = {
            str(seed): {r: (max((episode_metrics(x)["objective_key"] for x in det_rows[f"m7d_s{seed}_{r}"]), default=None))
                        for r in ("v1", "v2")} for seed in mm.SEEDS}
        comparison["initial_policy_identity"] = {
            str(seed): {m: _identical_rows(init_rows[f"m7d_s{seed}_v1"][m], init_rows[f"m7d_s{seed}_v2"][m])
                        for m in ("deterministic", "stochastic")} for seed in mm.SEEDS}
        comparison["objective_rank"] = {
            str(seed): _objective_compare(final_rows[f"m7d_s{seed}_v1"], final_rows[f"m7d_s{seed}_v2"])
            for seed in mm.SEEDS}
        comparison["diagnostic_reward"] = _diagnostic_reward(final_rows)
    comparison["training_identity"] = paired_training_identity(state)
    comparison["throughput_lifecycle"] = _throughput_comparison(runs)
    return {
        "schema": "battleship_m7d_report_v1", "milestone": mm.MILESTONE, "created_utc": _now(),
        "manifest": {"path": mm.ec.repo_relative(mm.MANIFEST_DOC), "created_utc": manifest.get("created_utc"),
                     "ok": manifest.get("ok"), "executable": manifest.get("executable"),
                     "decision_rule": manifest.get("decision_rule")},
        "seeds": list(mm.SEEDS), "order": manifest.get("order"),
        "random_baseline": None if random_summary is None else {
            "summary": summarize_mode(random_rows, seed=23),
            "cross_check_m7a": ((state.get("evaluations") or {}).get("random_baseline") or {}).get("cross_check_m7a"),
            "wall_s": random_summary.get("wall_s")},
        "runs": runs, "comparison": comparison, "episode_census": episode_census(),
        "matrix_state": {"events": state.get("events"), "user_config_before": state.get("user_config_before")},
        "claims_policy": "Gameplay outcomes decide (verified clear > targets > completion time). Reward totals are "
                         "diagnostic only: v1 and v2 numerical returns are not comparable (a v2 fall adds -5.0).",
    }


def paired_training_identity(state: Mapping[str, Any], rollout: int = 5120) -> Dict[str, Any]:
    """Common random numbers: with one seed, both runs start from the same untrained policy and the same PPO
    sampling stream, so their episodes are identical until the first rollout that contains a fall (the first
    rollout whose reward can differ). Reports, per seed, how many finished episodes were compared, how many were
    identical in gameplay, and which raw-return differences occurred (-5.0 exactly on falls, 0.0 otherwise)."""
    from m7d_run import jsonl_rows

    out: Dict[str, Any] = {}
    for seed in mm.SEEDS:
        rows = {}
        for r in ("v1", "v2"):
            spec = mm.run_by_name(f"m7d_s{seed}_{r}")
            segs = _run_segments(spec, state)
            rows[r] = [e for s in segs for e in jsonl_rows(s / "metrics" / "episodes.jsonl")[0]]
        if not rows["v1"] or not rows["v2"]:
            continue
        ro = lambda e: (int(e["sb3_num_timesteps_seen"]) + rollout - 1) // rollout  # noqa: E731
        falls = [ro(e) for e in rows["v1"] if e["end_reason"] == "fall"]
        k_f = min(falls) if falls else None
        cut = k_f if k_f is not None else max(ro(e) for e in rows["v1"])
        a = {(e["rank"], e["worker_episode"]): e for e in rows["v1"] if ro(e) <= cut}
        b = {(e["rank"], e["worker_episode"]): e for e in rows["v2"] if ro(e) <= cut}
        keys = sorted(set(a) & set(b))
        gameplay = ("native_action_digest", "steps", "targets_broken", "end_reason", "target_break_ticks")
        identical = sum(1 for k in keys if all(a[k][f] == b[k][f] for f in gameplay))
        diffs = sorted({round(float(b[k]["return"]) - float(a[k]["return"]), 9) for k in keys})
        out[str(seed)] = {"first_fall_rollout": k_f, "episodes_compared": len(keys),
                          "same_episode_set": sorted(a) == sorted(b), "identical_gameplay": identical,
                          "raw_return_differences": diffs,
                          "falls_among_compared": sum(1 for k in keys if a[k]["end_reason"] == "fall")}
    return out


def _identical_rows(a: Sequence[Mapping[str, Any]], b: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    n = min(len(a), len(b))
    same = sum(1 for x, y in zip(a[:n], b[:n]) if (x["native_action_digest"], x["targets_broken"], x["length"],
                                                   x["end_reason"]) == (y["native_action_digest"], y["targets_broken"],
                                                                        y["length"], y["end_reason"]))
    ret = [round(float(y["raw_return"]) - float(x["raw_return"]), 6) for x, y in zip(a[:n], b[:n])]
    return {"compared": n, "identical_gameplay": same,
            "return_differences": sorted(set(ret)), "note": "v2 - v1 raw return; -5.0 exactly on falls, 0 otherwise"}


def _objective_compare(a: Sequence[Mapping[str, Any]], b: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    ka = [episode_metrics(r)["objective_key"] for r in a]
    kb = [episode_metrics(r)["objective_key"] for r in b]
    return {"best_v1": list(max(ka)), "best_v2": list(max(kb)), "cliffs_delta_objective": cliffs_delta(ka, kb),
            "note": "objective key = (verified clear, targets, -completion_time_passed); larger is better"}


def _diagnostic_reward(final_rows: Mapping[str, Sequence[Mapping[str, Any]]]) -> Dict[str, Any]:
    out = {"warning": "diagnostic only: v1 and v2 returns use different scales (v2 adds -5.0 per fall); never evidence "
                      "that one contract is better"}
    for name, rows in final_rows.items():
        if not rows:
            continue
        rets = [float(r["raw_return"]) for r in rows]
        falls = sum(1 for r in rows if r["end_reason"] == "fall")
        v1_equiv = [float(r["raw_return"]) + (5.0 if (name.endswith("_v2") and r["end_reason"] == "fall") else 0.0)
                    for r in rows]
        out[name] = {"return_mean_own_contract": round(statistics.fmean(rets), 4),
                     "return_mean_rescored_as_v1": round(statistics.fmean(v1_equiv), 4), "falls": falls}
    return out


def _throughput_comparison(runs: Mapping[str, Any]) -> Dict[str, Any]:
    rows = {}
    for name, r in runs.items():
        t = r["training"]
        if not t.get("available"):
            continue
        rows[name] = {"end_to_end_transitions_per_s": t["end_to_end_transitions_per_s"],
                      "collection_transitions_per_s": t["collection_transitions_per_s"],
                      "wall_learn_s": t["wall_learn_s"], "episodes_finished": t["episodes"]["finished"],
                      "falls": t["episodes"]["falls"], "promotions": t["lifecycle"]["promotions"],
                      "cold_fallbacks": t["lifecycle"]["cold_fallbacks"],
                      "exposed_wait_s_total": t["lifecycle"]["exposed_wait_s_total"],
                      "max_battleship": max((m.get("max_battleship_processes") or 0) for m in t["monitor"]) if t["monitor"] else None,
                      "cpu_util_mean": [(m.get("cpu_util") or {}).get("mean") for m in t["monitor"]]}
    by_reward: Dict[str, List[float]] = {"v1": [], "v2": []}
    for name, r in rows.items():
        v = r["end_to_end_transitions_per_s"]
        if v and v[-1]:
            by_reward[name[-2:]].append(float(v[-1]))
    return {"per_run": rows,
            "mean_end_to_end": {k: round(statistics.fmean(v), 1) if v else None for k, v in by_reward.items()},
            "caveat": "throughput depends on the policy (episode length, fall rate -> restarts) and on background load; "
                      "it is a lifecycle diagnostic, never evidence about a reward contract"}


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(mm.REPO_ROOT / "docs" / "rl_reward_comparison_m7d.json"))
    args = parser.parse_args(argv)
    report = build_report()
    mm.write_json(Path(args.out), report)
    d = (report["comparison"].get("decision") or {})
    print(f"report written: {args.out}; decision: {d.get('classification')}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
