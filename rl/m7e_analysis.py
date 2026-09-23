#!/usr/bin/env python3
"""M7e Phase B: results, the eight pre-registered decision gates and the machine-readable report.

    python rl/m7e_analysis.py --test         # definition tests (no run data needed)
    python rl/m7e_analysis.py                # -> docs/rl_extended_training_m7e.{json,md}

Reads only what the trainer, the evaluator, the orchestrator and the replay
step wrote under runs/m7e/ (plus runs/m7d/ read-only, for the paired M7d
reward-v2 baseline at the same seed, and the manifest); launches nothing and
writes nothing inside runs/m7d/.

Every metric definition is imported UNCHANGED from rl/m7e_idle_analysis.py -
the Phase A module the proposal (section 6.6) registers as the definition
source: tail_fraction, the M7d idle flag, zero_target_horizon,
early_then_stagnant, target gaps, targets_per_1000, survival-matched windows,
phase-progress bands, the action-stream statistics, the learning-curve
classifier, deterministic_collapse and optimization_telemetry. The bootstrap
and effect-size machinery is imported unchanged from rl/m7d_analysis.py. Only
the M7e loaders (M7e run names, the 3,072,000-transition budget and the
307,200 evaluation cadence), the plateau rule's slope CI, the gate logic and
the reporting live here.

Gameplay outcomes decide, in the frozen objective ranking: verified clear >
more targets > faster completion time. Reward totals are diagnostic only. No
native RNG state is introduced, inspected, logged, validated, controlled,
compared or hashed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import experiment_config as ec  # noqa: E402
import m7d_analysis as da  # noqa: E402  (numpy only)
import m7e_idle_analysis as ia  # noqa: E402  (the Phase A metric definitions, unchanged)
import m7e_matrix as em  # noqa: E402

import numpy as np  # noqa: E402

REPO_ROOT = em.REPO_ROOT
SCHEMA = "m7e_extended_training_v1"
DOC_JSON = REPO_ROOT / "docs" / "rl_extended_training_m7e.json"
DOC_MD = REPO_ROOT / "docs" / "rl_extended_training_m7e.md"
M7D_ROOT = REPO_ROOT / "runs" / "m7d"
M7D_EVAL = M7D_ROOT / "_eval"
TARGETS_TOTAL = ia.TARGETS_TOTAL
HORIZON = ia.HORIZON
TOTAL = em.TOTAL_TRANSITIONS

# -- metric definitions, reused unchanged from Phase A -----------------------------------------------------------------
Episode = ia.Episode
summarise = ia.summarise
survival_matched = ia.survival_matched
phase_progress = ia.phase_progress
action_summary = ia.action_summary
final_state_clusters = ia.final_state_clusters
classify_curve = ia.classify_curve
deterministic_collapse = ia.deterministic_collapse
optimization_telemetry = ia.optimization_telemetry
target_gaps = ia.target_gaps
theil_sen = ia._theil_sen
_r = ia._r
_mean = ia._mean


# -- loaders (M7e names, budget and cadence) ---------------------------------------------------------------------------


def _episode_from_row(run: str, seed: int, stage: str, transitions: Optional[int], mode: str,
                      e: Mapping[str, Any]) -> Episode:
    return Episode(run=run, seed=seed, contract="v2", stage=stage, transitions=transitions, mode=mode,
                   episode_id=str(e["episode_id"]), length=int(e["length"]), targets=int(e["targets_broken"]),
                   end_reason=str(e["end_reason"]), breaks=[int(x) for x in (e.get("target_break_ticks") or [])],
                   digest=e.get("native_action_digest"), artifact_dir=e.get("artifact_dir"),
                   anomalies=int(e.get("anomaly_events") or 0))


def _transitions_of(stage: str, total: int) -> Optional[int]:
    if stage == "initial":
        return 0
    if stage == "final":
        return total
    if stage.startswith("curve_t"):
        return int(stage.split("curve_t", 1)[1])
    return None


def load_evaluation_episodes(root: Path = em.EVAL_ROOT, prefix: str = "m7e_s",
                             total: int = TOTAL) -> List[Episode]:
    """Every evaluation row of the M7e models (the Phase A loader is M7d-specific by run name and budget)."""
    out: List[Episode] = []
    if not root.is_dir():
        return out
    for ev in sorted(root.rglob("evaluation.json")):
        rel = ev.relative_to(root).as_posix().split("/")
        run = rel[0]
        if not run.startswith(prefix):
            continue
        stage = ia._stage_of(rel)
        seed = int(run.split("_s", 1)[1][0])
        doc = json.loads(ev.read_text(encoding="utf-8"))
        for e in doc.get("episodes") or []:
            out.append(_episode_from_row(run, seed, stage, _transitions_of(stage, total),
                                         str(e.get("mode") or doc.get("mode")), e))
    return out


def load_training_episodes(root: Path = em.MATRIX_ROOT, prefix: str = "m7e_s") -> List[Episode]:
    out: List[Episode] = []
    if not root.is_dir():
        return out
    for run_dir in sorted(root.glob(f"{prefix}*")):
        p = run_dir / "metrics" / "episodes.jsonl"
        if not p.exists():
            continue
        run = run_dir.name
        seed = int(run.split("_s", 1)[1][0])
        with open(p, encoding="utf-8") as fp:
            for line in fp:
                if not line.strip():
                    continue
                e = json.loads(line)
                out.append(Episode(run=run, seed=seed, contract="v2", stage="training",
                                   transitions=e.get("sb3_num_timesteps_at_end"), mode="training",
                                   episode_id=str(e["episode_id"]), length=int(e["steps"]),
                                   targets=int(e["targets_broken"]), end_reason=str(e["end_reason"]),
                                   breaks=[int(x) for x in (e.get("target_break_ticks") or [])],
                                   digest=e.get("native_action_digest"), artifact_dir=e.get("artifact_dir"),
                                   final_obs=e.get("terminal_native_observation"),
                                   anomalies=int(e.get("anomaly_events") or 0)))
    return out


def load_random_baseline(root: Path = em.EVAL_ROOT) -> List[Episode]:
    base = root / "random_baseline"
    p = next((q for q in (base / "random" / "evaluation.json", base / "evaluation.json") if q.exists()), None)
    if p is None:
        return []
    doc = json.loads(p.read_text(encoding="utf-8"))
    return [Episode(run="random_baseline", seed=-1, contract="random", stage="random", transitions=None,
                    mode="random", episode_id=str(e["episode_id"]), length=int(e["length"]),
                    targets=int(e["targets_broken"]), end_reason=str(e["end_reason"]),
                    breaks=[int(x) for x in (e.get("target_break_ticks") or [])],
                    digest=e.get("native_action_digest"), artifact_dir=e.get("artifact_dir"))
            for e in doc.get("episodes") or []]


def m7d_v2_final(seed: int, mode: str = "stochastic") -> Optional[Dict[str, Any]]:
    """The paired M7d reward-v2 final set at the same seed (read-only; never written)."""
    p = M7D_EVAL / f"m7d_s{seed}_v2" / "final" / "evaluation_summary.json"
    if not p.is_file():
        return None
    doc = json.loads(p.read_text(encoding="utf-8"))
    rows = ((doc.get("modes") or {}).get(mode) or {}).get("episodes") or []
    eps = [_episode_from_row(f"m7d_s{seed}_v2", seed, "final", 1_024_000, mode, e) for e in rows]
    if not eps:
        return None
    s = summarise(eps)
    s["targets"] = [e.targets for e in eps]
    s["tail_fractions"] = [e.tail_frac for e in eps if e.tail_frac is not None]
    s["budget"] = 1_024_000
    return s


# -- curves ------------------------------------------------------------------------------------------------------------


def stable_seed(*parts: Any) -> int:
    """A reproducible bootstrap seed from a label. Python's hash() of a str is salted per process, so it can never
    seed a statistic that has to come out the same on a re-run."""
    h = hashlib.sha256("\0".join(str(x) for x in parts).encode("utf-8")).digest()
    return int.from_bytes(h[:4], "big")


def curve(eps: Sequence[Episode], run: str, mode: str) -> List[Dict[str, Any]]:
    """One evaluated point per stage, in transition order, with the summary metrics of that point."""
    by_stage: Dict[str, List[Episode]] = {}
    for e in eps:
        if e.run == run and e.mode == mode and e.transitions is not None:
            by_stage.setdefault(e.stage, []).append(e)
    rows: List[Dict[str, Any]] = []
    for stage, group in sorted(by_stage.items(), key=lambda kv: kv[1][0].transitions or 0):
        s = summarise(group)
        boot = da.bootstrap_mean([float(e.targets) for e in group], seed=stable_seed(run, mode, stage))
        rows.append({"stage": stage, "transitions": group[0].transitions, "episodes": len(group),
                     "targets_mean": s["targets_mean"], "targets_ci95": [_r(boot[0]), _r(boot[1])] if boot else None,
                     "targets_max": s["targets_max"], "targets_histogram": s["targets_histogram"],
                     "clears": s["clears"], "fall_rate": s["fall_rate"], "horizon_rate": s["horizon_rate"],
                     "length_mean": s["length_mean"], "tail_fraction_mean": s["tail_fraction_mean"],
                     "m7d_idle_rate": s["m7d_idle_rate"],
                     "zero_target_horizon_rate": s["zero_target_horizon_rate"],
                     "early_then_stagnant_rate": s["early_then_stagnant_rate"],
                     "first_target_tick_median": s["first_target_tick_median"],
                     "last_target_tick_median": s["last_target_tick_median"],
                     "gap_median": s["gap_median"], "targets_per_1000_ticks": s["targets_per_1000_ticks"],
                     "_targets": [e.targets for e in group],
                     "_tail_fracs": [e.tail_frac for e in group if e.tail_frac is not None]})
    return rows


def slope_ci(points: Sequence[Tuple[int, Sequence[float]]], *, resamples: int = em.BOOTSTRAP_RESAMPLES,
             level: float = em.BOOTSTRAP_LEVEL, seed: int = 20260922) -> Optional[Dict[str, Any]]:
    """Bootstrap CI of the Theil-Sen slope (targets per 1e6 transitions) over a set of evaluated points.

    The resampling unit is the episode, inside its own point: each point's episodes are resampled with
    replacement, the point mean is recomputed, and the Theil-Sen slope of the resampled point means is taken.
    This is the plateau rule's registered statistic (proposal section 6.6)."""
    pts = [(t, list(vs)) for t, vs in points if vs]
    if len(pts) < 3:
        return None
    xs = [t / 1e6 for t, _ in pts]
    obs = theil_sen(xs, [float(_mean(vs) or 0.0) for _, vs in pts])
    rng = np.random.default_rng(seed)
    draws: List[float] = []
    arrays = [np.asarray(vs, dtype=float) for _, vs in pts]
    for _ in range(int(resamples)):
        means = [float(rng.choice(a, size=a.size, replace=True).mean()) for a in arrays]
        s = theil_sen(xs, means)
        if s is not None:
            draws.append(s)
    if not draws:
        return None
    lo_q, hi_q = (1.0 - level) / 2.0, 1.0 - (1.0 - level) / 2.0
    lo, hi = float(np.quantile(draws, lo_q)), float(np.quantile(draws, hi_q))
    return {"points": len(pts), "transitions": [t for t, _ in pts], "slope_per_1e6": _r(obs, 4),
            "ci95": [_r(lo, 4), _r(hi, 4)], "resamples": int(resamples), "level": level,
            "unit": "targets per 1e6 transitions"}


def plateau_verdict(stoch: Mapping[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """The pre-registered plateau rule (proposal section 6.6), applied exactly as written."""
    per_seed: Dict[str, Any] = {}
    excluded = 0
    tail_fell_too_far: List[str] = []
    for run, rows in sorted(stoch.items()):
        window = rows[-em.PLATEAU_WINDOW_POINTS:]
        ci = slope_ci([(int(r["transitions"]), r["_targets"]) for r in window])
        excl = bool(ci and ci["ci95"][1] < em.PLATEAU_SLOPE_THRESHOLD)
        tail_first = window[0]["tail_fraction_mean"] if window else None
        tail_last = window[-1]["tail_fraction_mean"] if window else None
        tail_drop = None if (tail_first is None or tail_last is None) else _r(tail_first - tail_last)
        fell = bool(tail_drop is not None and tail_drop > em.PLATEAU_TAIL_TOLERANCE)
        per_seed[run] = {"window_transitions": [int(r["transitions"]) for r in window],
                         "window_points": len(window), "slope": ci,
                         "ci_excludes_threshold": excl, "threshold": em.PLATEAU_SLOPE_THRESHOLD,
                         "tail_fraction_first": tail_first, "tail_fraction_last": tail_last,
                         "tail_fraction_drop": tail_drop, "tail_fell_more_than_tolerance": fell,
                         "tolerance": em.PLATEAU_TAIL_TOLERANCE}
        excluded += int(excl)
        if fell:
            tail_fell_too_far.append(run)
    declared = excluded >= em.PLATEAU_SEEDS_REQUIRED and not tail_fell_too_far
    return {"rule": em.PLATEAU_RULE, "per_seed": per_seed, "seeds_excluding_threshold": excluded,
            "seeds_required": em.PLATEAU_SEEDS_REQUIRED, "seeds_with_tail_still_shrinking": tail_fell_too_far,
            "plateau_declared": bool(declared),
            "why": (f"both halves satisfied ({excluded} of {len(per_seed)} seeds exclude "
                    f"+{em.PLATEAU_SLOPE_THRESHOLD}, need {em.PLATEAU_SEEDS_REQUIRED}; no tail shrank by more than "
                    f"{em.PLATEAU_TAIL_TOLERANCE})" if declared else
                    f"{excluded} of {len(per_seed)} seeds exclude +{em.PLATEAU_SLOPE_THRESHOLD} "
                    f"(need {em.PLATEAU_SEEDS_REQUIRED})"
                    + (f", but the tail is still shrinking by more than {em.PLATEAU_TAIL_TOLERANCE} in "
                       f"{tail_fell_too_far}, which the rule requires to be absent"
                       if tail_fell_too_far else ""))}


def curve_class(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Phase A section 3's classifier, unchanged: Theil-Sen slope against a noise scale."""
    pts = [(int(r["transitions"]), float(r["targets_mean"])) for r in rows if r.get("targets_mean") is not None]
    return classify_curve(pts)


# -- training sections -------------------------------------------------------------------------------------------------


def training_section(spec: em.RunSpec, state: Mapping[str, Any]) -> Dict[str, Any]:
    rs = (state.get("runs") or {}).get(spec.name) or {}
    segs = [spec.run_dir] + [REPO_ROOT / s["run_dir"] for s in (rs.get("lineage") or [])]
    out: Dict[str, Any] = {"run": spec.name, "seed": spec.seed, "order_index": spec.order_index,
                           "status": rs.get("status"), "verification_problems": rs.get("verification"),
                           "lineage_segments": [ec.repo_relative(p) for p in segs],
                           "interruptions": len(rs.get("lineage") or []),
                           "started_utc": rs.get("started_utc"), "finished_utc": rs.get("finished_utc")}
    summaries, runjsons = [], []
    for p in segs:
        sp, rp = p / "training_summary.json", p / "run.json"
        if sp.is_file():
            summaries.append(json.loads(sp.read_text(encoding="utf-8")))
        if rp.is_file():
            runjsons.append(json.loads(rp.read_text(encoding="utf-8")))
    if not summaries:
        out["present"] = False
        return out
    out["present"] = True
    last, rj = summaries[-1], (runjsons[-1] if runjsons else {})
    out["provenance"] = {"executable": rj.get("executable"), "revisions": rj.get("revisions"),
                         "versions": rj.get("versions"), "seeds": rj.get("seeds"),
                         "experiment": rj.get("experiment"), "reward_contract": rj.get("reward_contract"),
                         "m6_flags": rj.get("m6_flags"), "lifecycle": rj.get("lifecycle"),
                         "port_blocks": rj.get("port_blocks"), "job_object": rj.get("job_object"),
                         "torch_threads": rj.get("torch_threads"), "n_envs": rj.get("n_envs")}
    wall = sum(float((s.get("wall") or {}).get("run_total_s") or 0.0) for s in summaries)
    orchestrated = sum(float(((seg or {}).get("result") or {}).get("wall_s") or 0.0)
                       for seg in ([rs.get("segment")] if rs.get("segment") else []) + list(rs.get("lineage") or []))
    steps = (last.get("timesteps") or {}).get("sb3_num_timesteps")
    out["training"] = {"status": last.get("status"), "wall_s": round(wall, 1), "wall_min": round(wall / 60.0, 1),
                       "orchestrated_wall_s": round(orchestrated, 1),
                       "orchestrated_wall_min": round(orchestrated / 60.0, 1),
                       "sb3_num_timesteps": steps,
                       "transitions_per_s": _r(steps / wall, 1) if (steps and wall) else None,
                       "trainer_end_to_end_transitions_per_s":
                           (last.get("throughput") or {}).get("end_to_end_transitions_per_s"),
                       "trainer_collection_transitions_per_s":
                           (last.get("throughput") or {}).get("collection_transitions_per_s"),
                       "timesteps": last.get("timesteps"), "wall_breakdown": last.get("wall"),
                       "time_split": last.get("time_split"), "cpu": last.get("cpu"), "memory": last.get("memory"),
                       "episodes": last.get("episodes"), "restarts": last.get("restarts"),
                       "failures": last.get("failures"), "anomalies": last.get("anomalies"),
                       "in_process_evaluations": len(last.get("evaluations") or []),
                       "eval_s_total_inside_learn": (last.get("wall") or {}).get("eval_s_total"),
                       "cleanup": last.get("cleanup"), "user_config": last.get("user_config"),
                       "checkpoint_sets": len(last.get("checkpoints") or []),
                       "checkpoint_labels": [c.get("label") for c in (last.get("checkpoints") or [])],
                       "artifacts": last.get("artifacts")}
    lc = last.get("lifecycle") or {}
    sb = lc.get("standby") or {}
    out["lifecycle"] = {"expected_max_game_processes": lc.get("expected_max_game_processes"),
                        "observed_max_concurrent_per_worker": lc.get("observed_max_concurrent_per_worker"),
                        "reset_modes": lc.get("reset_modes"), "promotions": sb.get("promotions"),
                        "cold_fallbacks": sb.get("cold_fallbacks"), "fallback_reasons": sb.get("fallback_reasons"),
                        "standby_failed_attempts": sb.get("standby_failed_attempts"),
                        "standby_failures": sb.get("standby_failures"), "standby_lost": sb.get("standby_lost"),
                        "exposed_wait_s": sb.get("exposed_wait_s") or sb.get("wait_s"),
                        "threads": sb.get("threads")}
    mons = [(s.get("result") or {}).get("monitor") for s in
            ([rs.get("segment")] if rs.get("segment") else []) + list(rs.get("lineage") or []) if s]
    mons = [m for m in mons if m]
    if mons:
        def _last(key):
            vals = [m.get(key) for m in mons if m.get(key) is not None]
            return vals[-1] if vals else None
        out["monitor"] = {"samples": sum(int(m.get("samples") or 0) for m in mons),
                          "max_battleship_processes": max(int(m.get("max_battleship_processes") or 0) for m in mons),
                          "max_battleship_listeners": max(int(m.get("max_battleship_listeners") or 0) for m in mons),
                          "hard_alerts": [a for m in mons for a in (m.get("hard_alerts") or [])],
                          "soft_alerts_count": sum(int(m.get("soft_alert_count") or 0) for m in mons),
                          "soft_alerts_sample": [a for m in mons for a in (m.get("soft_alerts") or [])][:10],
                          "cpu_util": _last("cpu_util"),
                          "avail_phys_gib": _last("avail_phys_gib"),
                          "avail_commit_gib": _last("avail_commit_gib"),
                          "commit_used_gib": _last("commit_used_gib"),
                          "disk_free_gib": _last("disk_free_gib"),
                          "episodes_seen": sum(int(m.get("episodes_seen") or 0) for m in mons),
                          "episode_ends": _last("episode_ends"),
                          "startup_modes": _last("startup_modes"),
                          "startup_failures": sum(int(m.get("startup_failures") or 0) for m in mons),
                          "cold_fallbacks_after_first": sum(int(m.get("cold_fallbacks_after_first") or 0)
                                                            for m in mons),
                          "worker_threads": _last("worker_threads"),
                          "max_exited_battleship_entries": max(int(m.get("max_exited_battleship_entries") or 0)
                                                               for m in mons),
                          "lifecycle_failures": sum(int(m.get("lifecycle_failures") or 0) for m in mons),
                          "anomalies": sum(int(m.get("anomalies") or 0) for m in mons)}
    out["optimization"] = optimization_telemetry(spec.name, root=em.MATRIX_ROOT)
    return out


def training_episode_windows(eps: Sequence[Episode], run: str, window: int = em.CHECKPOINT_INTERVAL) -> List[Dict[str, Any]]:
    rows = [e for e in eps if e.run == run and e.transitions is not None]
    if not rows:
        return []
    out: List[Dict[str, Any]] = []
    hi = 0
    while hi < TOTAL:
        lo, hi = hi, hi + window
        grp = [e for e in rows if lo < (e.transitions or 0) <= hi]
        if not grp:
            continue
        s = summarise(grp)
        out.append({"window": [lo, hi], "episodes": len(grp), "targets_mean": s["targets_mean"],
                    "targets_max": s["targets_max"], "clears": s["clears"], "fall_rate": s["fall_rate"],
                    "horizon_rate": s["horizon_rate"], "tail_fraction_mean": s["tail_fraction_mean"]})
    return out


# -- clears ------------------------------------------------------------------------------------------------------------


def clear_census(ev: Sequence[Episode], tr: Sequence[Episode]) -> Dict[str, Any]:
    """Every clear or clear candidate, with the four agreement conditions and the native replay verdict."""
    rows: List[Dict[str, Any]] = []
    for e in list(ev) + list(tr):
        if e.end_reason != "clear" and e.targets < TARGETS_TOTAL:
            continue
        md = ia.read_artifact_metadata(e.artifact_dir) if e.artifact_dir else None
        labels = (md or {}).get("labels") or {}
        rows.append({"run": e.run, "seed": e.seed, "stage": e.stage, "mode": e.mode, "episode_id": e.episode_id,
                     "transitions": e.transitions, "targets_broken": e.targets, "length": e.length,
                     "end_reason": e.end_reason, "artifact_dir": e.artifact_dir,
                     "native_action_digest": e.digest, "target_break_ticks": e.breaks,
                     "cleared_flag": labels.get("cleared"),
                     "completion_time_passed": labels.get("completion_time_passed"),
                     "completion_input_tick": labels.get("completion_input_tick"),
                     "agreement": {
                         "native_end_reason_clear": e.end_reason == "clear",
                         "cleared_flag": bool(labels.get("cleared")),
                         "ten_targets_broken": e.targets == TARGETS_TOTAL,
                         "valid_completion_clock": labels.get("completion_time_passed") is not None
                         and labels.get("completion_input_tick") is not None}})
    for r in rows:
        r["all_conditions_agree"] = all(r["agreement"].values())
    replays = replay_evidence()
    verified: List[Dict[str, Any]] = []
    candidates: List[Dict[str, Any]] = []
    for r in rows:
        rep = next((x for x in replays.get("records", [])
                    if x.get("episode_id") == r["episode_id"]), None)
        r["native_replay"] = None if rep is None else {"ok": rep.get("ok"), "checks": rep.get("checks")}
        (verified if (r["all_conditions_agree"] and rep and rep.get("ok")) else candidates).append(r)
    return {"clears_or_candidates": len(rows), "verified_clears": len(verified), "clear_candidates": len(candidates),
            "verified": verified, "candidates": candidates,
            "requirement": "a clear requires agreement among the native end reason, the cleared flag, zero remaining "
                           "targets (ten broken) and a valid completion clock, AND reproduction through the native "
                           "replay path; anything less is a candidate",
            "baseline": {"source": "tas_input_2/mario_743.btti", "source_rows": 468, "targets": 10,
                         "displayed_time": 7.43, "completion_time_passed": 446, "completion_input_tick": 447,
                         "interactive_actions_submitted": 447, "last_consumed_tick": 446, "final_step_count": 447,
                         "unsubmitted_source_rows": 21, "native_replay_checksum": "0x93E9EFB4",
                         "note": "the two clocks are reported separately; neither is collapsed nor decremented, and "
                                 "the TAS is never approximated through Track 1"}}


def replay_evidence() -> Dict[str, Any]:
    """Every runs/m7e/_replay/<run>/replay.json record."""
    records: List[Dict[str, Any]] = []
    per_run: Dict[str, Any] = {}
    if em.REPLAY_ROOT.is_dir():
        for p in sorted(em.REPLAY_ROOT.rglob("replay.json")):
            doc = json.loads(p.read_text(encoding="utf-8"))
            per_run[str(doc.get("run"))] = {"artifacts_considered": doc.get("artifacts_considered"),
                                            "replayed": len(doc.get("replayed") or []),
                                            "all_ok": all(r.get("ok") for r in (doc.get("replayed") or [])),
                                            "clear_candidates": doc.get("clear_candidates"),
                                            "clears_verified": doc.get("clears_verified")}
            records.extend(doc.get("replayed") or [])
    return {"per_run": per_run, "records": records, "replayed": len(records),
            "all_ok": bool(records) and all(r.get("ok") for r in records)}


# -- the eight gates ---------------------------------------------------------------------------------------------------


def evaluate_gates(report: Mapping[str, Any]) -> Dict[str, Any]:
    """The eight pre-registered gates of proposal section 7, applied exactly as written. Gate 8 pre-empts; gates 1,
    2 and 4 are mutually exclusive and evaluated in that order."""
    seeds = list(em.SEEDS)
    runs = {s: f"m7e_s{s}_v2" for s in seeds}
    finals = {s: (report["per_seed"].get(runs[s], {}).get("final") or {}) for s in seeds}
    base = {s: (report["m7d_baseline"].get(str(s)) or {}) for s in seeds}
    out: Dict[str, Any] = {}

    # Gate 8 first: it pre-empts all others.
    integ = report["integrity"]
    g8_signals = {
        "process_count_breach": integ.get("max_battleship_processes_over_limit"),
        "port_leak": integ.get("port_leaks"),
        "non_reproducing_artifact": integ.get("non_reproducing_artifacts"),
        "git_diff_check_failed": integ.get("git_diff_check_failed"),
        "user_config_changed": integ.get("user_config_changed"),
        "historical_tree_changed": integ.get("historical_tree_changed"),
        "verification_failed_runs": integ.get("verification_failed_runs"),
        "monitor_hard_alerts": integ.get("monitor_hard_alerts"),
        "evaluation_census_incomplete": integ.get("census_incomplete"),
    }
    out["gate_8"] = {"gate": 8, "key": "lifecycle_regression", "signals": g8_signals,
                     "triggered": any(bool(v) for v in g8_signals.values()),
                     "response": em.GATES[7]["response"]}

    # Gate 1: a verified clear.
    cc = report["clears"]
    out["gate_1"] = {"gate": 1, "key": "verified_clear", "verified_clears": cc["verified_clears"],
                     "clear_candidates": cc["clear_candidates"],
                     "triggered": cc["verified_clears"] > 0, "response": em.GATES[0]["response"]}

    # Gate 2: better targets, no clear.
    improved, deltas, ceiling = [], {}, 0
    for s in seeds:
        f, b = finals.get(s) or {}, base.get(s) or {}
        if f.get("targets_mean") is None or b.get("targets_mean") is None:
            continue
        d = _r(float(f["targets_mean"]) - float(b["targets_mean"]))
        deltas[str(s)] = {"m7e": f["targets_mean"], "m7d": b["targets_mean"], "delta": d,
                          "m7e_max": f.get("targets_max"), "m7d_max": b.get("targets_max")}
        if d is not None and d > 0:
            improved.append(s)
        ceiling = max(ceiling, int(f.get("targets_max") or 0))
    out["gate_2"] = {"gate": 2, "key": "better_targets_no_clear", "per_seed": deltas,
                     "seeds_improved": improved, "seeds_improved_count": len(improved),
                     "observed_ceiling": ceiling, "ceiling_still_at_most_6": ceiling <= 6,
                     "aggregate_delta": _r(_mean([v["delta"] for v in deltas.values() if v["delta"] is not None])),
                     "triggered": len(improved) >= 2 and cc["verified_clears"] == 0,
                     "response": em.GATES[1]["response"]}

    # Gates 4 and 3: the plateau rule and its complement.
    pl = report["plateau"]
    out["gate_4"] = {"gate": 4, "key": "plateau", "plateau_declared": pl["plateau_declared"],
                     "detail": pl["why"], "triggered": bool(pl["plateau_declared"]),
                     "response": em.GATES[3]["response"]}
    out["gate_3"] = {"gate": 3, "key": "still_improving", "no_plateau": not pl["plateau_declared"],
                     "curve_classes": {r: c["class"] for r, c in report["curve_classification"].items()},
                     "triggered": not pl["plateau_declared"], "response": em.GATES[2]["response"]}

    # Gate 5: worse idling.
    tail_up, zth = [], {}
    for s in seeds:
        f, b = finals.get(s) or {}, base.get(s) or {}
        if f.get("tail_fraction_mean") is not None and b.get("tail_fraction_mean") is not None:
            d = float(f["tail_fraction_mean"]) - float(b["tail_fraction_mean"])
            if d >= 0.10:
                tail_up.append(s)
        zth[str(s)] = f.get("zero_target_horizon_rate")
    targets_flat_or_down = all((deltas.get(str(s), {}).get("delta") or 0.0) <= 0 for s in seeds) if deltas else False
    zth_breach = [k for k, v in zth.items() if v is not None and float(v) > 0.05]
    out["gate_5"] = {"gate": 5, "key": "worse_idling",
                     "tail_fraction_rise_per_seed": {str(s): _r((finals.get(s) or {}).get("tail_fraction_mean", 0)
                                                                - (base.get(s) or {}).get("tail_fraction_mean", 0))
                                                     if (finals.get(s) or {}).get("tail_fraction_mean") is not None
                                                     and (base.get(s) or {}).get("tail_fraction_mean") is not None
                                                     else None for s in seeds},
                     "seeds_with_tail_rise_ge_0_10": tail_up,
                     "zero_target_horizon_rate": zth, "zero_target_horizon_breach": zth_breach,
                     "targets_flat_or_down": targets_flat_or_down,
                     "triggered": len(tail_up) >= 2 or bool(zth_breach) or targets_flat_or_down,
                     "response": em.GATES[4]["response"]}

    # Gate 6: strong seed disagreement.
    classes = {r: c["class"] for r, c in report["curve_classification"].items()}
    improving = [r for r, c in classes.items() if c == "improving"]
    regressing = [r for r, c in classes.items() if c == "regressing"]
    out["gate_6"] = {"gate": 6, "key": "seed_disagreement", "classes": classes,
                     "improving": improving, "regressing": regressing,
                     "triggered": bool(improving) and bool(regressing), "response": em.GATES[5]["response"]}

    # Gate 7: deterministic collapse at final.
    coll = {}
    for s in seeds:
        det = (report["per_seed"].get(runs[s], {}).get("final_deterministic") or {}).get("collapse") or {}
        coll[str(s)] = det.get("collapse_share")
    breached = [k for k, v in coll.items() if v is not None and float(v) >= 0.5]
    out["gate_7"] = {"gate": 7, "key": "deterministic_collapse", "collapse_share": coll,
                     "seeds_collapsed": breached, "triggered": len(breached) >= 2,
                     "entropy_still_falling": {str(s): ((report["per_seed"].get(runs[s], {}).get("training") or {})
                                                       .get("optimization") or {}).get("still_concentrating")
                                               for s in seeds},
                     "response": em.GATES[6]["response"]}

    order = ["gate_8", "gate_1", "gate_2", "gate_4", "gate_3", "gate_5", "gate_6", "gate_7"]
    triggered = [k for k in order if out[k]["triggered"]]
    # The next action is the TRIGGERED gates' own pre-registered responses, never a relabelling of them. Gate 3's
    # response forbids silently extending, so "additional unchanged-v2 training" is only selected when gate 3 is the
    # sole classifying gate AND gate 2 did not fire (i.e. the budget question is still the open one).
    if out["gate_8"]["triggered"]:
        classification = "gate_8_lifecycle_regression"
        next_action = "infrastructure repair"
        rationale = em.GATES[7]["response"]
    elif out["gate_1"]["triggered"]:
        classification = "gate_1_verified_clear"
        next_action = "clear consolidation"
        rationale = em.GATES[0]["response"]
    elif out["gate_2"]["triggered"]:
        classification = "gate_2_better_targets_no_clear"
        if out["gate_3"]["triggered"]:
            # Both fired: v2 is confirmed on objective rank 2 and more transitions helped, but no plateau was
            # reached. Gate 2 sends M7f at the CEILING with target-identity instrumentation promoted from optional
            # to prerequisite; gate 3 forbids a silent extension and requires M7f to be opened as an explicit
            # budget-versus-intervention decision. Neither response is "train the same thing for longer".
            next_action = ("ceiling-directed M7f, gated on target-identity instrumentation: neither an unchanged-v2 "
                           "extension (gate 3 forbids extending silently; a further extension needs its own "
                           "pre-registration and maximum) nor an anti-idle intervention (gate 4 did not fire, and "
                           "the proposal reserves that for a declared plateau)")
            rationale = ("gate 2: " + em.GATES[1]["response"] + " || gate 3: " + em.GATES[2]["response"])
        else:
            next_action = "controlled anti-idle/exploration intervention"
            rationale = em.GATES[1]["response"]
    elif out["gate_4"]["triggered"]:
        classification = "gate_4_plateau"
        next_action = "controlled anti-idle/exploration intervention"
        rationale = em.GATES[3]["response"]
    elif out["gate_3"]["triggered"]:
        classification = "gate_3_still_improving"
        next_action = ("open M7f as an explicit budget-versus-intervention decision; a further unchanged-v2 "
                       "extension requires its own pre-registration and its own maximum")
        rationale = em.GATES[2]["response"]
    else:
        classification = "unclassified"
        next_action = "more replication"
        rationale = "no classifying gate fired"
    if out["gate_6"]["triggered"]:
        next_action = "more replication: " + next_action
        rationale = em.GATES[5]["response"] + " || " + rationale
    return {"gates": [out[k] for k in order], "by_key": out, "triggered": triggered,
            "classification": classification, "selected_next_action": next_action,
            "next_action_rationale": rationale,
            "ordering": em.GATE_ORDERING, "objective_ranking": list(em.OBJECTIVE_RANKING),
            "note": "the gates and their thresholds were registered in 9d45235 before any M7e Phase B data existed; "
                    "none was redefined after seeing the data. The next action is the triggered gates' own "
                    "pre-registered responses, recommended and not implemented."}


# -- integrity ---------------------------------------------------------------------------------------------------------


def integrity(state: Mapping[str, Any], cen: Mapping[str, Any]) -> Dict[str, Any]:
    import subprocess

    verify_dir = em.STATE_DIR / "verify"
    vers = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in verify_dir.glob("*.json")} \
        if verify_dir.is_dir() else {}
    hard = [a for v in vers.values() for a in ((v.get("historical_tree") or {}).get("changed") or [])]
    mon_hard: List[str] = []
    max_bs = 0
    leaks: List[Any] = []
    for name, rs in (state.get("runs") or {}).items():
        for seg in ([rs.get("segment")] if rs.get("segment") else []) + list(rs.get("lineage") or []):
            mon = ((seg or {}).get("result") or {}).get("monitor") or {}
            mon_hard.extend(mon.get("hard_alerts") or [])
            max_bs = max(max_bs, int(mon.get("max_battleship_processes") or 0))
            max_listen = int(mon.get("max_battleship_listeners") or 0)
            if max_listen > em.MAX_GAME_PROCESSES:
                mon_hard.append(f"{name}: {max_listen} BattleShip listeners > {em.MAX_GAME_PROCESSES}")
            post = (seg or {}).get("postconditions") or {}
            if post.get("battleship_pids"):
                leaks.append({name: post["battleship_pids"]})
            if post.get("battleship_listeners"):
                leaks.append({name: post["battleship_listeners"]})
    for key, ev in (state.get("evaluations") or {}).items():
        mon = ev.get("monitor") or {}
        mon_hard.extend(mon.get("hard_alerts") or [])
        max_bs = max(max_bs, int(mon.get("max_battleship_processes") or 0))
        if ev.get("leak_free") is False:
            leaks.append({key: "not leak free"})
    try:
        rc = subprocess.run(["git", "diff", "--check"], cwd=str(REPO_ROOT), capture_output=True, text=True,
                            timeout=120, check=False)
        diff_check_failed = rc.returncode != 0
        diff_check_output = (rc.stdout or "") + (rc.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        diff_check_failed, diff_check_output = True, f"{type(exc).__name__}: {exc}"
    snap = em.STATE_DIR / "snapshots" / "historical_before.json"
    hist_changed = any(not ((v.get("historical_tree") or {}).get("identical", True)) for v in vers.values())
    uc_before = (state.get("user_config_before") or {}).get("sha256")
    uc_now = dr_user_config()
    rep = replay_evidence()
    non_repro = [r.get("episode_id") for r in rep["records"] if not r.get("ok")]
    return {
        "verification_failed_runs": sorted(n for n, v in vers.items() if not v.get("ok")),
        "verified_runs": sorted(n for n, v in vers.items() if v.get("ok")),
        "monitor_hard_alerts": mon_hard,
        "max_battleship_processes": max_bs,
        "max_battleship_processes_over_limit": max_bs > em.MAX_GAME_PROCESSES,
        "process_limit": em.MAX_GAME_PROCESSES,
        "port_leaks": leaks,
        "historical_tree_changed": hist_changed,
        "historical_baseline": ec.repo_relative(snap) if snap.is_file() else None,
        "historical_changed_files": hard[:20],
        "user_config_before_sha256": uc_before, "user_config_now_sha256": uc_now,
        "user_config_changed": bool(uc_before and uc_now and uc_before != uc_now),
        "git_diff_check_failed": diff_check_failed, "git_diff_check_output": diff_check_output.strip()[:2000],
        "non_reproducing_artifacts": non_repro,
        "replay": {k: v for k, v in rep.items() if k != "records"},
        "census_incomplete": not cen.get("complete", False),
        "census": {k: v for k, v in cen.items() if k not in ("rows", "plan")},
    }


def dr_user_config() -> Optional[str]:
    import m7d_run as dr
    return (dr.user_config_fingerprint() or {}).get("sha256")


# -- the report --------------------------------------------------------------------------------------------------------


def build_report() -> Dict[str, Any]:
    import m7e_run as er

    state = er.load_state()
    cen = er.census()
    ev = load_evaluation_episodes()
    tr = load_training_episodes()
    rnd = load_random_baseline()
    per_seed: Dict[str, Any] = {}
    stoch_curves: Dict[str, List[Dict[str, Any]]] = {}
    det_curves: Dict[str, List[Dict[str, Any]]] = {}
    for spec in em.matrix():
        sc = curve(ev, spec.name, "stochastic")
        dc = curve(ev, spec.name, "deterministic")
        if sc:
            stoch_curves[spec.name] = sc
        if dc:
            det_curves[spec.name] = dc
        final_s = [e for e in ev if e.run == spec.name and e.stage == "final" and e.mode == "stochastic"]
        final_d = [e for e in ev if e.run == spec.name and e.stage == "final" and e.mode == "deterministic"]
        init_s = [e for e in ev if e.run == spec.name and e.stage == "initial" and e.mode == "stochastic"]
        entry: Dict[str, Any] = {"run": spec.name, "seed": spec.seed,
                                 "training": training_section(spec, state),
                                 "training_windows": training_episode_windows(tr, spec.name),
                                 "stochastic_curve": [{k: v for k, v in r.items() if not k.startswith("_")}
                                                      for r in sc],
                                 "deterministic_curve": [{k: v for k, v in r.items() if not k.startswith("_")}
                                                         for r in dc]}
        if final_s:
            s = summarise(final_s)
            s["survival_matched"] = survival_matched(final_s)
            s["phase_progress"] = phase_progress(final_s)
            s["actions"] = action_summary(final_s, limit=100)
            # final_state_clusters falls back to the artifact metadata's final_observation, so it works on
            # evaluation rows too (they carry no final_obs of their own); it returns None if no position exists.
            s["final_state_clusters"] = final_state_clusters(final_s)
            boot = da.bootstrap_mean([float(e.targets) for e in final_s], seed=1000 + spec.seed)
            s["targets_ci95"] = [_r(boot[0]), _r(boot[1])] if boot else None
            entry["final"] = s
        if init_s:
            entry["initial"] = summarise(init_s)
        if final_d:
            sd = summarise(final_d)
            sd["actions"] = action_summary(final_d, limit=100)
            sd["collapse"] = deterministic_collapse({**sd, "actions": sd["actions"]})
            entry["final_deterministic"] = sd
        per_seed[spec.name] = entry
    baseline = {str(s): m7d_v2_final(s) for s in em.SEEDS}
    report: Dict[str, Any] = {
        "schema": SCHEMA, "milestone": em.MILESTONE, "phase": em.PHASE,
        "created_utc": er.utc_now(),
        "purpose": "whether unchanged btt_reward_v2 and unchanged PPO continue learning beyond the M7d "
                   "1,024,000-transition budget, produce the first verified clear, or reach a defensible plateau",
        "authority": ec.repo_relative(em.PROPOSAL_DOC),
        "budget": {"per_seed": TOTAL, "hard_maximum": True, "checkpoint_interval": em.CHECKPOINT_INTERVAL,
                   "evaluation_interval": em.EVAL_INTERVAL},
        "rows_read": {"evaluation": len(ev), "training": len(tr), "random_baseline": len(rnd),
                      "total": len(ev) + len(tr) + len(rnd)},
        "random_baseline": summarise(rnd) if rnd else None,
        "definitions": ia.definitions_block(),
        "per_seed": per_seed,
        "m7d_baseline": {k: ({kk: vv for kk, vv in (v or {}).items() if not kk.startswith("_")
                              and kk not in ("targets", "tail_fractions")} if v else None)
                         for k, v in baseline.items()},
        "curve_classification": {r: curve_class(rows) for r, rows in stoch_curves.items()},
        "deterministic_curve_classification": {r: curve_class(rows) for r, rows in det_curves.items()},
        "plateau": plateau_verdict(stoch_curves) if stoch_curves else
        {"plateau_declared": False, "why": "no stochastic curve data", "rule": em.PLATEAU_RULE, "per_seed": {}},
        "clears": clear_census(ev, tr),
        "replay": replay_evidence(),
        "census": cen,
    }
    # The gate evaluation needs the m7d baseline as plain numbers plus integrity.
    report["m7d_baseline"] = {k: (None if v is None else
                                  {"targets_mean": v["targets_mean"], "targets_max": v["targets_max"],
                                   "tail_fraction_mean": v["tail_fraction_mean"], "fall_rate": v["fall_rate"],
                                   "horizon_rate": v["horizon_rate"], "clears": v["clears"],
                                   "zero_target_horizon_rate": v["zero_target_horizon_rate"],
                                   "m7d_idle_rate": v["m7d_idle_rate"], "episodes": v["episodes"],
                                   "budget": v["budget"]})
                              for k, v in baseline.items()}
    report["integrity"] = integrity(state, cen)
    report["decision"] = evaluate_gates(report)
    report["limitations"] = [
        "Three seeds, one task, one horizon, one process count, one PPO configuration, one machine, one executable "
        "build. Nothing here generalises beyond that.",
        "Target identity remains unknown: target_break_ticks records when a target broke, never which one, so every "
        "statement about which targets are or are not reached is an inference from counts and timing.",
        "The M7d comparison is a between-experiment contrast at the same seed, not a within-experiment randomised "
        "one; M7e's first 1,024,000 transitions are a replication of M7d's curve, and the checkpoint cadence and "
        "intermediate evaluation counts differ by design.",
        "Reward totals are diagnostic only and are never used to rank a result.",
        "A plateau verdict rests on the registered rule's window and thresholds; a different window could read "
        "differently, which is why the rule was fixed before the data existed.",
        "Deterministic results describe the argmax policy, which the Phase A diagnosis showed is a different animal "
        "from the sampled one; the stochastic policy is the reported one.",
    ]
    return report


# -- markdown ----------------------------------------------------------------------------------------------------------


def _f(x: Any, nd: int = 3) -> str:
    if x is None:
        return "-"
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, (int,)):
        return f"{x:,}"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def render_markdown(rep: Mapping[str, Any]) -> str:
    L: List[str] = []
    a = L.append
    dec = rep["decision"]
    a("# RL M7e Phase B: the bounded reward-v2 extension")
    a("")
    a(f"Generated by `rl/m7e_analysis.py` from `runs/m7e/`. Authority for every registered number: "
      f"[`{Path(rep['authority']).name}`]({Path(rep['authority']).name}).")
    a("")
    a(f"Rows read: **{rep['rows_read']['evaluation']} evaluation**, **{rep['rows_read']['training']} training**, "
      f"**{rep['rows_read']['random_baseline']} random baseline** = **{rep['rows_read']['total']}**.")
    a("")
    a(f"Budget: **{rep['budget']['per_seed']:,} transitions per seed, hard maximum**; checkpoint cadence "
      f"{rep['budget']['checkpoint_interval']:,}; evaluated every {rep['budget']['evaluation_interval']:,}.")
    a("")
    a(f"**Classification: `{dec['classification']}`. Selected next action: {dec['selected_next_action']}.** "
      f"(Recommended, not implemented.)")
    a("")
    a("## Training")
    a("")
    a("| run | seed | status | transitions | wall min | transitions/s | episodes (fin) | clears | falls | "
      "horizon | max BattleShip | promotions | cold fallbacks | interruptions | hard alerts |")
    a("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for name, e in rep["per_seed"].items():
        t = e.get("training") or {}
        tt, lc, mon = t.get("training") or {}, t.get("lifecycle") or {}, t.get("monitor") or {}
        ep = tt.get("episodes") or {}
        ends = ep.get("end_reasons") or {}
        a(f"| {name} | {e['seed']} | {t.get('status')} | {_f(tt.get('sb3_num_timesteps'))} | "
          f"{_f(tt.get('wall_min'), 1)} | {_f(tt.get('trainer_end_to_end_transitions_per_s'), 1)} | "
          f"{_f(ep.get('finished'))} | {_f(ep.get('clears'))} | {_f(ends.get('fall'))} | "
          f"{_f(ends.get('horizon'))} | {_f(mon.get('max_battleship_processes'))} | "
          f"{_f(lc.get('promotions'))} | {_f(lc.get('cold_fallbacks'))} | {_f(t.get('interruptions'))} | "
          f"{len(mon.get('hard_alerts') or [])} |")
    a("")
    a("| run | training targets mean | max | checkpoint sets | artifacts preserved | launcher threads "
      "(started/joined/alive) | in-process evaluations | eval seconds inside learn() | anomalies | "
      "user config byte-identical |")
    a("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for name, e in rep["per_seed"].items():
        t = e.get("training") or {}
        tt, lc = t.get("training") or {}, t.get("lifecycle") or {}
        ep, th = tt.get("episodes") or {}, (lc.get("threads") or {})
        uc = tt.get("user_config") or {}
        a(f"| {name} | {_f(ep.get('targets_mean'), 3)} | {_f(ep.get('targets_max'))} | "
          f"{_f(tt.get('checkpoint_sets'))} | {_f((tt.get('artifacts') or {}).get('preserved'))} | "
          f"{_f(th.get('started'))}/{_f(th.get('joined'))}/{_f(th.get('alive_at_close'))} | "
          f"{_f(tt.get('in_process_evaluations'))} | {_f(tt.get('eval_s_total_inside_learn'), 1)} | "
          f"{_f(tt.get('anomalies'))} | {_f(uc.get('byte_identical'))} |")
    a("")
    a("## Stochastic learning curves (mean targets per evaluated checkpoint)")
    a("")
    runs = list(rep["per_seed"].keys())
    if runs:
        a("| transitions | " + " | ".join(runs) + " |")
        a("| --- | " + " | ".join("---" for _ in runs) + " |")
        pts = em.evaluated_points()
        for t in pts:
            cells = []
            for r in runs:
                row = next((x for x in rep["per_seed"][r]["stochastic_curve"] if x["transitions"] == t), None)
                cells.append("-" if row is None else
                             f"{_f(row['targets_mean'], 2)} / {_f(row['fall_rate'], 2)} (n={row['episodes']})")
            a(f"| {t:,} | " + " | ".join(cells) + " |")
        a("")
        a("Cell format: mean targets / fall rate (episodes).")
    a("")
    a("## Curve classification (Phase A section 3's rule, unchanged)")
    a("")
    a("| run | mode | class | Theil-Sen (targets / 1e6) | noise scale | last third - first third | "
      "first -> last | best |")
    a("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for mode, block in (("stochastic", rep["curve_classification"]),
                        ("deterministic", rep["deterministic_curve_classification"])):
        for r, c in block.items():
            a(f"| {r} | {mode} | {c.get('class')} | {_f(c.get('theil_sen_targets_per_1e6'))} | "
              f"{_f(c.get('noise_scale_targets_per_1e6'))} | {_f(c.get('third_delta_targets'))} | "
              f"{_f(c.get('first'), 2)} -> {_f(c.get('last'), 2)} | {_f(c.get('best'), 2)} @ "
              f"{_f(c.get('argmax_transitions'))} |")
    a("")
    a("## The pre-registered plateau rule (proposal section 6.6)")
    a("")
    pl = rep["plateau"]
    a(f"Window: {pl['rule']['window']}. Threshold: +{em.PLATEAU_SLOPE_THRESHOLD} targets per 1e6 transitions, "
      f"{em.PLATEAU_SEEDS_REQUIRED} of 3 seeds, and no seed's tail fraction may have fallen by more than "
      f"{em.PLATEAU_TAIL_TOLERANCE}.")
    a("")
    a("| run | slope | 95 % CI | CI excludes +0.25 | tail frac first -> last | drop | tail still shrinking |")
    a("| --- | --- | --- | --- | --- | --- | --- |")
    for r, v in (pl.get("per_seed") or {}).items():
        s = v.get("slope") or {}
        ci = s.get("ci95") or [None, None]
        a(f"| {r} | {_f(s.get('slope_per_1e6'))} | [{_f(ci[0])}, {_f(ci[1])}] | "
          f"{_f(v.get('ci_excludes_threshold'))} | {_f(v.get('tail_fraction_first'))} -> "
          f"{_f(v.get('tail_fraction_last'))} | {_f(v.get('tail_fraction_drop'))} | "
          f"{_f(v.get('tail_fell_more_than_tolerance'))} |")
    a("")
    a(f"**Plateau declared: {_f(pl['plateau_declared'])}** - {pl['why']}")
    a("")
    a("## Final stochastic results, against the paired M7d reward-v2 baseline")
    a("")
    a("| seed | M7e targets | 95 % CI | M7d targets | delta | M7e max | M7d max | falls | horizon | tail frac | "
      "M7d tail frac | zero-target horizon |")
    a("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for spec in em.matrix():
        e = rep["per_seed"].get(spec.name, {})
        f = e.get("final") or {}
        b = rep["m7d_baseline"].get(str(spec.seed)) or {}
        ci = f.get("targets_ci95") or [None, None]
        d = None
        if f.get("targets_mean") is not None and b.get("targets_mean") is not None:
            d = float(f["targets_mean"]) - float(b["targets_mean"])
        a(f"| {spec.seed} | {_f(f.get('targets_mean'), 2)} | [{_f(ci[0], 2)}, {_f(ci[1], 2)}] | "
          f"{_f(b.get('targets_mean'), 2)} | {_f(d, 3)} | {_f(f.get('targets_max'))} | {_f(b.get('targets_max'))} | "
          f"{_f(f.get('fall_rate'), 2)} | {_f(f.get('horizon_rate'), 2)} | {_f(f.get('tail_fraction_mean'))} | "
          f"{_f(b.get('tail_fraction_mean'))} | {_f(f.get('zero_target_horizon_rate'), 2)} |")
    a("")
    a("## Target timing and the no-progress tail (final stochastic)")
    a("")
    a("| seed | first target (median) | last target (median) | gap median | gap p90 | targets / 1000 ticks | "
      "tail mean | tail fraction | M7d idle rate | early-then-stagnant |")
    a("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for spec in em.matrix():
        f = (rep["per_seed"].get(spec.name, {}).get("final") or {})
        a(f"| {spec.seed} | {_f(f.get('first_target_tick_median'), 1)} | "
          f"{_f(f.get('last_target_tick_median'), 1)} | {_f(f.get('gap_median'), 1)} | {_f(f.get('gap_p90'), 1)} | "
          f"{_f(f.get('targets_per_1000_ticks'))} | {_f(f.get('tail_mean'), 1)} | "
          f"{_f(f.get('tail_fraction_mean'))} | {_f(f.get('m7d_idle_rate'), 2)} | "
          f"{_f(f.get('early_then_stagnant_rate'), 2)} |")
    a("")
    a("## Action behaviour (final stochastic, 100 episodes) and deterministic collapse")
    a("")
    a("| seed | joint entropy (bits) | distinct actions/ep | max run (mean) | head entropy | tail entropy | "
      "head switch | tail switch | tail long-run share |")
    a("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for spec in em.matrix():
        act = (((rep["per_seed"].get(spec.name, {}).get("final")) or {}).get("actions") or {})
        ent = ((act.get("pooled") or {}).get("entropy") or {})
        per = (act.get("per_episode") or {})
        ht = (act.get("head_tail") or {})
        a(f"| {spec.seed} | {_f(ent.get('joint_bits'))} | {_f(per.get('distinct_joint_actions_mean'), 1)} | "
          f"{_f(per.get('max_run_mean'), 1)} | {_f(ht.get('head_entropy_bits_mean'))} | "
          f"{_f(ht.get('tail_entropy_bits_mean'))} | {_f(ht.get('head_switch_rate_mean'))} | "
          f"{_f(ht.get('tail_switch_rate_mean'))} | {_f(ht.get('tail_long_run_share_mean'))} |")
    a("")
    a("The Phase A diagnosis reads the tail through these four numbers: entropy against the 6.170-bit maximum, the "
      "switch rate, the share of ticks inside a run of at least 60 identical actions, and the deterministic "
      "collapse share. They are the same definitions, unchanged.")
    a("")
    a("### Deterministic (argmax) play at `final`, 100 episodes")
    a("")
    a("| seed | targets | max | clears | max run (ticks) | collapse share | collapsed | joint entropy (bits) | "
      "M7d collapse share |")
    a("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    m7d_collapse = {0: 0.945, 1: 0.098, 2: 0.918}
    for spec in em.matrix():
        det = (rep["per_seed"].get(spec.name, {}).get("final_deterministic") or {})
        coll = det.get("collapse") or {}
        a(f"| {spec.seed} | {_f(det.get('targets_mean'), 2)} | {_f(det.get('targets_max'))} | "
          f"{_f(det.get('clears'))} | {_f(coll.get('max_run_ticks'))} | {_f(coll.get('collapse_share'))} | "
          f"{_f(coll.get('collapsed'))} | {_f(coll.get('joint_entropy_bits'))} | "
          f"{m7d_collapse.get(spec.seed)} |")
    a("")
    a("## Optimization state at the budget's end (SB3 rollout metrics)")
    a("")
    a("| seed | H start (nats) | H end | fraction of max | slope / 1e6 | last-third slope | deceleration | "
      "still concentrating | explained variance |")
    a("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for spec in em.matrix():
        o = ((rep["per_seed"].get(spec.name, {}).get("training") or {}).get("optimization") or {})
        a(f"| {spec.seed} | {_f(o.get('entropy_nats_start'))} | {_f(o.get('entropy_nats_end'))} | "
          f"{_f(o.get('entropy_fraction_end'))} | {_f(o.get('entropy_slope_per_1e6'))} | "
          f"{_f(o.get('entropy_slope_last_third_per_1e6'))} | {_f(o.get('deceleration'))} | "
          f"{_f(o.get('still_concentrating'))} | {_f(o.get('explained_variance_mean_last_third'))} |")
    a("")
    a("## Clears and native verification")
    a("")
    cc = rep["clears"]
    a(f"Clears or candidates: **{cc['clears_or_candidates']}**; verified clears: **{cc['verified_clears']}**; "
      f"candidates not verified: **{cc['clear_candidates']}**.")
    a("")
    a(cc["requirement"])
    a("")
    b = cc["baseline"]
    a(f"Authoritative native baseline, restated and untouched: `{b['source']}`, {b['source_rows']} source rows, "
      f"{b['targets']} targets, displayed time {b['displayed_time']}, "
      f"`completion_time_passed = {b['completion_time_passed']}`, "
      f"`completion_input_tick = {b['completion_input_tick']}`, "
      f"{b['interactive_actions_submitted']} interactive actions submitted, last `consumed_tick` "
      f"{b['last_consumed_tick']}, final `step_count` {b['final_step_count']}, "
      f"{b['unsubmitted_source_rows']} source rows intentionally unsubmitted, native replay checksum "
      f"`{b['native_replay_checksum']}`. {b['note']}")
    a("")
    a("## Evaluation census (planned versus executed)")
    a("")
    cen = rep["census"]
    a(f"Planned **{cen['planned_episodes']}** episodes in **{cen['planned_sessions']}** sessions; executed "
      f"**{cen['executed_episodes']}** in **{cen['executed_sessions']}**. Complete: "
      f"**{_f(cen['complete'])}**.")
    a("")
    a(f"Arithmetic: {cen['plan']['arithmetic']['stochastic_per_seed']} stochastic; "
      f"{cen['plan']['arithmetic']['deterministic_per_seed']} deterministic; "
      f"{cen['plan']['arithmetic']['per_seed']} per seed; {cen['plan']['arithmetic']['three_seeds']}; "
      f"{cen['plan']['arithmetic']['plus_random_baseline']}.")
    if cen["missing"]:
        a("")
        a("Missing:")
        for m in cen["missing"][:20]:
            a(f"- {m}")
    a("")
    a("## The eight pre-registered decision gates")
    a("")
    a("| # | gate | triggered | evidence |")
    a("| --- | --- | --- | --- |")
    for g in dec["gates"]:
        ev_bits = {k: v for k, v in g.items() if k not in ("gate", "key", "triggered", "response")}
        txt = json.dumps(ev_bits, default=str)
        if len(txt) > 420:
            txt = txt[:417] + "..."
        a(f"| {g['gate']} | {g['key']} | **{_f(g['triggered'])}** | `{txt}` |")
    a("")
    a(dec["ordering"])
    a("")
    a(f"**Classification: `{dec['classification']}`. Selected next action: {dec['selected_next_action']}.**")
    a("")
    a(dec["note"])
    a("")
    a("## Integrity")
    a("")
    ig = rep["integrity"]
    a(f"- Maximum live BattleShip processes observed: **{ig['max_battleship_processes']}** "
      f"(limit {ig['process_limit']}).")
    a(f"- Monitor hard alerts: **{len(ig['monitor_hard_alerts'])}**.")
    a(f"- Port / process leaks: **{len(ig['port_leaks'])}**.")
    a(f"- Historical run tree changed: **{_f(ig['historical_tree_changed'])}** (baseline "
      f"`{ig['historical_baseline']}`).")
    a(f"- User configuration sha256 unchanged: **{_f(not ig['user_config_changed'])}** "
      f"(`{str(ig['user_config_now_sha256'])[:16]}...`).")
    a(f"- `git diff --check`: **{'FAILED' if ig['git_diff_check_failed'] else 'passes'}**.")
    a(f"- Non-reproducing preserved artifacts: **{len(ig['non_reproducing_artifacts'])}**.")
    a(f"- Replay records: **{ig['replay'].get('replayed')}**, all reproduced: "
      f"**{_f(ig['replay'].get('all_ok'))}**.")
    a("")
    a("## Limitations")
    a("")
    for x in rep["limitations"]:
        a(f"- {x}")
    a("")
    return "\n".join(L) + "\n"


# -- tests -------------------------------------------------------------------------------------------------------------


def _tests() -> int:
    failures: List[str] = []

    def check(ok: bool, label: str) -> None:
        print(f"  {'ok  ' if ok else 'FAIL'} {label}")
        if not ok:
            failures.append(label)

    print("m7e_analysis definitions")
    check(_transitions_of("initial", TOTAL) == 0, "initial -> 0 transitions")
    check(_transitions_of("final", TOTAL) == TOTAL, "final -> the full budget")
    check(_transitions_of("curve_t001536000", TOTAL) == 1_536_000, "curve label -> its transition count")
    check(_transitions_of("random", TOTAL) is None, "random has no transition count")
    check(stable_seed("m7e_s0_v2", "stochastic", "final") == stable_seed("m7e_s0_v2", "stochastic", "final")
          and stable_seed("a") != stable_seed("b") and 0 <= stable_seed("a") < 2 ** 32,
          "bootstrap seeds are reproducible and label-specific")
    check(stable_seed("m7e_s0_v2", "stochastic", "final") == 145645413,
          f"the stable seed changed value: {stable_seed('m7e_s0_v2', 'stochastic', 'final')}")
    # A synthetic rising curve must classify as improving and its slope CI must exclude the plateau threshold.
    rng = np.random.default_rng(7)
    rising = []
    for i, t in enumerate(em.evaluated_points()[-em.PLATEAU_WINDOW_POINTS:]):
        base = 4.0 + 1.5 * (t / 1e6)
        rising.append((t, list(base + rng.normal(0, 0.05, 60))))
    ci = slope_ci(rising, resamples=400, seed=1)
    check(ci is not None and ci["ci95"][0] > em.PLATEAU_SLOPE_THRESHOLD,
          f"a clearly rising curve's CI lies above +0.25 ({ci and ci['ci95']})")
    flat = [(t, list(4.0 + rng.normal(0, 0.05, 60))) for t in em.evaluated_points()[-em.PLATEAU_WINDOW_POINTS:]]
    ci2 = slope_ci(flat, resamples=400, seed=2)
    check(ci2 is not None and ci2["ci95"][1] < em.PLATEAU_SLOPE_THRESHOLD,
          f"a flat curve's CI excludes +0.25 ({ci2 and ci2['ci95']})")
    # The plateau rule needs BOTH halves.
    def rows_from(pairs, tail_first, tail_last):
        out = []
        n = len(pairs)
        for i, (t, vs) in enumerate(pairs):
            tf = tail_first + (tail_last - tail_first) * (i / max(n - 1, 1))
            out.append({"stage": f"curve_t{t:09d}", "transitions": t, "episodes": len(vs),
                        "targets_mean": _mean(vs), "tail_fraction_mean": tf, "_targets": vs})
        return out
    v_flat = plateau_verdict({"a": rows_from(flat, 0.50, 0.50), "b": rows_from(flat, 0.50, 0.50),
                              "c": rows_from(flat, 0.50, 0.50)})
    check(v_flat["plateau_declared"], "flat curves with a flat tail declare a plateau")
    v_tail = plateau_verdict({"a": rows_from(flat, 0.60, 0.40), "b": rows_from(flat, 0.50, 0.50),
                              "c": rows_from(flat, 0.50, 0.50)})
    check(not v_tail["plateau_declared"], "a still-shrinking tail blocks the plateau even with a flat target curve")
    v_rise = plateau_verdict({"a": rows_from(rising, 0.50, 0.50), "b": rows_from(rising, 0.50, 0.50),
                              "c": rows_from(rising, 0.50, 0.50)})
    check(not v_rise["plateau_declared"], "a rising curve is not a plateau")
    v_split = plateau_verdict({"a": rows_from(flat, 0.50, 0.50), "b": rows_from(flat, 0.50, 0.50),
                               "c": rows_from(rising, 0.50, 0.50)})
    check(v_split["plateau_declared"] and v_split["seeds_excluding_threshold"] == 2,
          "2 of 3 seeds is enough, as registered")
    v_one = plateau_verdict({"a": rows_from(flat, 0.50, 0.50), "b": rows_from(rising, 0.50, 0.50),
                             "c": rows_from(rising, 0.50, 0.50)})
    check(not v_one["plateau_declared"], "1 of 3 seeds is not enough")
    # Gate logic on a synthetic report.
    def gate_report(**kw):
        base = {
            "per_seed": {f"m7e_s{s}_v2": {"final": {"targets_mean": 4.5, "targets_max": 6,
                                                    "tail_fraction_mean": 0.48,
                                                    "zero_target_horizon_rate": 0.0},
                                          "final_deterministic": {"collapse": {"collapse_share": 0.2}},
                                          "training": {"optimization": {"still_concentrating": True}}}
                         for s in em.SEEDS},
            "m7d_baseline": {str(s): {"targets_mean": 3.9, "targets_max": 6, "tail_fraction_mean": 0.48}
                             for s in em.SEEDS},
            "curve_classification": {f"m7e_s{s}_v2": {"class": "improving"} for s in em.SEEDS},
            "plateau": {"plateau_declared": False, "why": "still improving"},
            "clears": {"verified_clears": 0, "clear_candidates": 0},
            "integrity": {},
        }
        for k, v in kw.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                base[k] = {**base[k], **v}
            else:
                base[k] = v
        return base
    g = evaluate_gates(gate_report())
    check(g["classification"] == "gate_2_better_targets_no_clear" and g["by_key"]["gate_2"]["triggered"],
          "better targets without a clear classifies as gate 2")
    check(g["by_key"]["gate_3"]["triggered"] and not g["by_key"]["gate_4"]["triggered"],
          "no plateau -> gate 3, not gate 4")
    check("ceiling-directed" in g["selected_next_action"]
          and "extension" in g["selected_next_action"],
          f"gate 2 + gate 3 must select the registered ceiling-directed response, not a silent extension: "
          f"{g['selected_next_action']}")
    check("target-identity instrumentation" in g["next_action_rationale"],
          "the gate-2 response's instrumentation prerequisite is not carried into the rationale")
    g = evaluate_gates(gate_report(clears={"verified_clears": 1, "clear_candidates": 0}))
    check(g["classification"] == "gate_1_verified_clear" and g["selected_next_action"] == "clear consolidation",
          "a verified clear classifies as gate 1 and selects clear consolidation")
    g = evaluate_gates(gate_report(integrity={"max_battleship_processes_over_limit": True}))
    check(g["classification"] == "gate_8_lifecycle_regression" and g["selected_next_action"] == "infrastructure repair",
          "gate 8 pre-empts everything")
    g = evaluate_gates(gate_report(integrity={"user_config_changed": True}))
    check(g["by_key"]["gate_8"]["triggered"], "a changed user configuration trips gate 8")
    g = evaluate_gates(gate_report(integrity={"git_diff_check_failed": True}))
    check(g["by_key"]["gate_8"]["triggered"], "a git diff --check failure trips gate 8")
    g = evaluate_gates(gate_report(
        per_seed={f"m7e_s{s}_v2": {"final": {"targets_mean": 3.9, "targets_max": 6, "tail_fraction_mean": 0.62,
                                             "zero_target_horizon_rate": 0.0},
                                   "final_deterministic": {"collapse": {"collapse_share": 0.9}},
                                   "training": {"optimization": {"still_concentrating": False}}}
                  for s in em.SEEDS}))
    check(g["by_key"]["gate_5"]["triggered"], "a tail rise of 0.14 in three seeds trips gate 5")
    check(g["by_key"]["gate_7"]["triggered"], "collapse_share 0.9 in three seeds trips gate 7")
    g = evaluate_gates(gate_report(curve_classification={"m7e_s0_v2": {"class": "improving"},
                                                        "m7e_s1_v2": {"class": "regressing"},
                                                        "m7e_s2_v2": {"class": "plateaued"}}))
    check(g["by_key"]["gate_6"]["triggered"] and g["selected_next_action"].startswith("more replication"),
          f"one improving and one regressing seed trips gate 6 and leads with more replication: "
          f"{g['selected_next_action']}")
    g = evaluate_gates(gate_report(
        plateau={"plateau_declared": True, "why": "flat"},
        per_seed={f"m7e_s{s}_v2": {"final": {"targets_mean": 3.9, "targets_max": 6, "tail_fraction_mean": 0.48,
                                             "zero_target_horizon_rate": 0.0},
                                   "final_deterministic": {"collapse": {"collapse_share": 0.2}},
                                   "training": {"optimization": {"still_concentrating": False}}}
                  for s in em.SEEDS}))
    check(g["by_key"]["gate_4"]["triggered"] and not g["by_key"]["gate_3"]["triggered"],
          "a declared plateau trips gate 4 and not gate 3")
    # Definition sources must be the Phase A module itself, not copies.
    check(summarise is ia.summarise and classify_curve is ia.classify_curve
          and deterministic_collapse is ia.deterministic_collapse
          and optimization_telemetry is ia.optimization_telemetry,
          "every metric definition is the Phase A object itself (reused unchanged)")
    check(em.TOTAL_TRANSITIONS == 3_072_000 and em.EVAL_INTERVAL == 307_200
          and em.CHECKPOINT_INTERVAL == 102_400, "the registered budget and cadences")
    print(f"m7e_analysis: {'all definition tests passed' if not failures else str(len(failures)) + ' FAILED'}")
    return 0 if not failures else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="M7e Phase B results, gates and report")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--json", default=str(DOC_JSON))
    ap.add_argument("--md", default=str(DOC_MD))
    args = ap.parse_args(list(argv) if argv is not None else None)
    if args.test:
        return _tests()
    rep = build_report()
    em.write_json(Path(args.json), rep)
    Path(args.md).write_text(render_markdown(rep), encoding="utf-8", newline="\n")
    print(f"m7e report -> {ec.repo_relative(Path(args.json))} and {ec.repo_relative(Path(args.md))}")
    print(f"classification: {rep['decision']['classification']}; "
          f"next action: {rep['decision']['selected_next_action']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
