#!/usr/bin/env python3
"""M7k offline reward comparison (no training; no recorded file modified).

    python rl/m7k_rewards.py --target2 runs/m7k/target2/<name> --out runs/m7k/rewards/<name>

Candidates (closed forms over recorded episodes; none of them changes gameplay):
  v2        btt_reward_v2
  v3        btt_reward_v3 (registered, unchanged): v2 + right-sweep term (no recorded episode has a qualified landing)
  ER(c)     v3 + an evenly distributed right-target timing credit c*(3600 - n)/3600 on each right target's first break
            (the proposed btt_reward_v3_rt; offline only, not implemented)
  T2(b)     v3 + a target-2-specific timing credit b*(3600 - n)/3600 on target 2's first break
            (n = consumed_tick + 1, the v3 timing convention)
At equal budget (c = 2/7, b = 2.0) both add at most 2.0 per episode; b = 1 and b = 4 are sensitivity rows.

Episode sources:
  eval     every tick-0 evaluation episode of Phase K (6 runs + random baseline) and M7h F (3 runs): target identity and
           break ticks from btt_eval_metrics_v1 (exact; no left entry in any of them, so no v3 landing term);
  train    the unbiased Phase K v1 training sample (every 10th finished episode, `periodic_milestone`), target identity
           from the M7k exact replays (runs/m7k/target2/<name>/traces).
Also: the separately assessed post-landing fall penalty (future contract; closed forms) and the first-clear relevance
test baselines. The TAS and the user crossing fixtures are not read.
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import math
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parent
REPO_ROOT = RL_DIR.parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import m7k_target2 as t2m  # noqa: E402

H = 3600
RIGHT = t2m.RIGHT
STATIC = t2m.STATIC
T2 = t2m.T2
DEADLINE_TICK = 2699          # the M7j "early" convention: >= 900 ticks left after the event
C_EVEN = 2.0 / 7.0
B_T2 = 2.0


def timing(tick: int) -> float:
    n = int(tick) + 1
    if not 1 <= n <= H:
        raise ValueError(f"tick {tick} outside the tick-0 horizon")
    return (H - n) / H


# -- episodes --------------------------------------------------------------------------------------------------------


def eval_episodes() -> List[Dict[str, Any]]:
    out = []
    for fam, run, label, mode, f in t2m._eval_files():
        d = t2m.read_json(f)
        for e in d.get("episodes") or []:
            em = e.get("eval_metrics") or {}
            if "target_breaks" not in em:
                continue
            if em.get("first_left_entry") is not None:
                raise RuntimeError(f"{e['episode_id']}: a left entry would need a replay for v3's landing term")
            out.append({"source": "eval", "family": fam, "run": run, "label": label, "mode": mode,
                        "episode_id": e["episode_id"], "steps": int(e["length"]), "end": e["end_reason"],
                        "cleared": bool(e.get("cleared")),
                        "breaks": [(int(b["target_id"]), int(b["consumed_tick"])) for b in em["target_breaks"]],
                        "recorded_return": e.get("raw_return")})
    return out


def train_episodes(target2_dir: Path) -> List[Dict[str, Any]]:
    sel = {i["episode_id"]: i for i in t2m.read_json(target2_dir / "selection.json")["items"]}
    out = []
    for p in sorted((target2_dir / "traces").glob("*.json.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as fp:
            tr = json.load(fp)
        it = sel[tr["episode_id"]]
        if "D" not in it["sets"]:
            continue
        out.append({"source": "train", "family": "phase_k", "run": it["run"], "label": "training", "mode": "stochastic",
                    "episode_id": tr["episode_id"], "steps": tr["steps"], "end": {"fall": "fall", "horizon": "horizon",
                                                                                   "clear": "clear"}.get(tr["end"], tr["end"]),
                    "cleared": tr["end"] == "clear", "breaks": [tuple(b) for b in tr["breaks"]],
                    "recorded_return": it.get("raw_return"), "sb3_num_timesteps_seen": it.get("sb3_num_timesteps_seen")})
    return out


# -- candidates ------------------------------------------------------------------------------------------------------


def sweep_tick(breaks: Sequence[Tuple[int, int]]) -> Optional[int]:
    seen = {}
    for tid, t in sorted(breaks, key=lambda b: b[1]):
        seen.setdefault(tid, t)
    if all(i in seen for i in RIGHT):
        return max(seen[i] for i in RIGHT)
    return None


def r_v2(ep: Mapping[str, Any]) -> float:
    return len(ep["breaks"]) * 1.0 + ep["steps"] * -0.001 + (10.0 if ep["cleared"] else 0.0) + (-5.0 if ep["end"] == "fall" else 0.0)


def r_v3(ep: Mapping[str, Any]) -> float:
    s = sweep_tick(ep["breaks"])
    return r_v2(ep) + (0.0 if s is None else 3.0 + 2.0 * timing(s))


def term_er(ep: Mapping[str, Any], c: float = C_EVEN) -> float:
    return sum(c * timing(t) for tid, t in ep["breaks"] if tid in RIGHT)


def term_t2(ep: Mapping[str, Any], b: float = B_T2) -> float:
    return sum(b * timing(t) for tid, t in ep["breaks"] if tid == T2)


CANDIDATES: Dict[str, Callable[[Mapping[str, Any]], float]] = {
    "v2": r_v2,
    "v3": r_v3,
    "ER_c2/7": lambda e: r_v3(e) + term_er(e, C_EVEN),
    "T2_b2": lambda e: r_v3(e) + term_t2(e, 2.0),
    "T2_b1": lambda e: r_v3(e) + term_t2(e, 1.0),
    "T2_b4": lambda e: r_v3(e) + term_t2(e, 4.0),
}
NEW_TERM: Dict[str, Callable[[Mapping[str, Any]], float]] = {
    "ER_c2/7": lambda e: term_er(e, C_EVEN), "T2_b2": lambda e: term_t2(e, 2.0),
    "T2_b1": lambda e: term_t2(e, 1.0), "T2_b4": lambda e: term_t2(e, 4.0),
}


def has_t2(ep: Mapping[str, Any]) -> bool:
    return any(tid == T2 for tid, _ in ep["breaks"])


def statics(ep: Mapping[str, Any]) -> int:
    return len({tid for tid, _ in ep["breaks"] if tid in STATIC})


# -- comparison ------------------------------------------------------------------------------------------------------


def _mean(v: Sequence[float]) -> Optional[float]:
    return round(statistics.fmean(v), 4) if v else None


def within_label_signal(eps: Sequence[Mapping[str, Any]], fn: Callable[[Mapping[str, Any]], float]) -> Dict[str, Any]:
    """For every label (checkpoint x mode) that contains both target-2 and other episodes: the standardised return gap
    (mean over target-2 episodes - mean over the rest) / sd(label), and the mean percentile of target-2 episodes."""
    by: Dict[Tuple[str, str, str], List[Mapping[str, Any]]] = {}
    for e in eps:
        by.setdefault((e["run"], e["label"], e["mode"]), []).append(e)
    z, pct, n_lab = [], [], 0
    for key, grp in by.items():
        a = [fn(e) for e in grp if has_t2(e)]
        b = [fn(e) for e in grp if not has_t2(e)]
        if not a or len(b) < 2:
            continue
        allv = [fn(e) for e in grp]
        sd = statistics.pstdev(allv)
        if sd == 0:
            continue
        n_lab += 1
        z.append((statistics.fmean(a) - statistics.fmean(b)) / sd)
        srt = sorted(allv)
        for v in a:
            pct.append(sum(1 for x in srt if x < v) / len(srt))
    return {"labels": n_lab, "mean_z": _mean(z), "median_z": round(statistics.median(z), 4) if z else None,
            "t2_mean_percentile": _mean(pct), "t2_episodes": len(pct)}


def contrast(eps: Sequence[Mapping[str, Any]], fn: Callable[[Mapping[str, Any]], float]) -> Dict[str, Any]:
    """The bottleneck contrast: episodes with all six static targets and target 2 vs all six static without it, and
    episodes with target 2 vs 'late static six, no target 2'."""
    six_t2 = [fn(e) for e in eps if statics(e) == 6 and has_t2(e)]
    six_no = [fn(e) for e in eps if statics(e) == 6 and not has_t2(e)]
    t2_any = [fn(e) for e in eps if has_t2(e)]
    no_t2 = [fn(e) for e in eps if not has_t2(e)]
    return {"six_with_t2": {"n": len(six_t2), "mean": _mean(six_t2)}, "six_without_t2": {"n": len(six_no), "mean": _mean(six_no)},
            "gap_six": None if not six_t2 or not six_no else round(statistics.fmean(six_t2) - statistics.fmean(six_no), 4),
            "t2_any_mean": _mean(t2_any), "no_t2_mean": _mean(no_t2),
            "gap_any": None if not t2_any or not no_t2 else round(statistics.fmean(t2_any) - statistics.fmean(no_t2), 4)}


def compare(eps: Sequence[Mapping[str, Any]], name: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {"population": name, "episodes": len(eps), "t2_episodes": sum(1 for e in eps if has_t2(e)),
                           "t2_rate": round(sum(1 for e in eps if has_t2(e)) / len(eps), 5) if eps else None,
                           "candidates": {}}
    for cname, fn in CANDIDATES.items():
        row: Dict[str, Any] = {"mean_return": _mean([fn(e) for e in eps]), "signal": within_label_signal(eps, fn),
                               "contrast": contrast(eps, fn)}
        if cname in NEW_TERM:
            terms = [(NEW_TERM[cname](e), has_t2(e)) for e in eps]
            tot = sum(v for v, _ in terms)
            t2_mass = sum(term_t2(e, 1.0) * (C_EVEN if cname.startswith("ER") else float(cname.split("_b")[1]))
                          for e in eps)
            row.update({"new_term_nonzero_rate": round(sum(1 for v, _ in terms if v) / len(terms), 5) if terms else None,
                        "new_term_mean": _mean([v for v, _ in terms]),
                        "new_term_mass_on_target2": round(t2_mass / tot, 4) if tot else None})
        out["candidates"][cname] = row
    return out


def pair_rankings() -> List[Dict[str, Any]]:
    """Observed-type outcome classes (medians from the M7k analysis), each ranked by every candidate. All survive to
    the horizon; ticks are consumed ticks."""
    def ep(breaks: Sequence[Tuple[int, int]], steps: int = H, end: str = "horizon") -> Dict[str, Any]:
        return {"breaks": list(breaks), "steps": steps, "end": end, "cleared": False}

    statics_early = [(9, 41), (4, 76), (0, 154), (5, 400), (3, 900), (7, 1699)]
    statics_late = [(9, 41), (4, 200), (0, 432), (5, 1069), (3, 2139), (7, 2930)]
    classes = {
        "A: six static early (last at 1,699), no target 2": ep(statics_early),
        "B: six static late (last at 2,930), no target 2": ep(statics_late),
        "C: four static + target 2 at 1,500": ep(statics_early[:4] + [(2, 1500)]),
        "D: four static + target 2 at 3,000": ep(statics_early[:4] + [(2, 3000)]),
        "E: sweep late (six static early + target 2 at 3,570)": ep(statics_early + [(2, 3570)]),
        "F: sweep early (six static early + target 2 at 1,800)": ep(statics_early + [(2, 1800)]),
        "G: five static early, no target 2": ep(statics_early[:5]),
    }
    out = []
    for cname, fn in CANDIDATES.items():
        vals = {k: round(fn(v), 4) for k, v in classes.items()}
        out.append({"candidate": cname, "returns": vals, "order": sorted(vals, key=lambda k: -vals[k])})
    return out


# -- separately assessed: the post-landing fall penalty (future contract) --------------------------------------------


def landing_assessment() -> Dict[str, Any]:
    """After a qualified landing at tick t_L with the sweep done at t_s: compare a fall at t_f >= t_L with idling to the
    horizon without another target (same targets), and with staying right after the sweep (no crossing)."""
    step = 0.001

    def forms() -> Dict[str, Callable[[int], float]]:
        return {"v3 registered: -1": lambda tf: -1.0, "constant -3.7": lambda tf: -3.7,
                "time-dependent, delta 0.25": lambda tf: -step * (H - tf) - 0.25,
                "time-dependent, delta 0.5": lambda tf: -step * (H - tf) - 0.5,
                "time-dependent, delta 1.0": lambda tf: -step * (H - tf) - 1.0,
                "v2 standard: -5": lambda tf: -5.0}

    rows = []
    for name, P in forms().items():
        fall_beats_idle = [tf for tf in range(1, H + 1) if P(tf) - step * tf > -step * H + 1e-12]
        # after a sweep at t_s: crossing + landing (+2) + fall at t_f vs staying right to the horizon
        cross_loses = [tf for tf in range(1, H + 1) if 2.0 + P(tf) - step * tf <= -step * H]
        # attempt for the last left target (success = +1 target +10 clear) vs idling: break-even success probability
        worst_gap = max(-step * H - (P(tf) - step * tf) for tf in range(1, H + 1))    # cost of a failed attempt vs idle
        best_gap = min(-step * H - (P(tf) - step * tf) for tf in range(1, H + 1))
        rows.append({
            "penalty": name,
            "fall_beats_idle_ticks": [min(fall_beats_idle), max(fall_beats_idle)] if fall_beats_idle else None,
            "no_suicide_incentive": not fall_beats_idle,
            "crossing_landing_fall_loses_to_staying_right_ticks": [min(cross_loses), max(cross_loses)] if cross_loses else None,
            "failed_attempt_cost_vs_idle": [round(best_gap, 4), round(worst_gap, 4)],
            "attempt_break_even_probability": [round(max(0.0, g) / (11.0 + max(0.0, g)), 4) for g in (best_gap, worst_gap)],
        })
    return {"question": "a qualified-landing fall penalty under which immediate falling never scores higher than "
                        "surviving without another target", "rows": rows,
            "recommendation": "time-dependent P(t_f) = -0.001*(3600 - t_f) - delta with delta > 0 (a fall is exactly delta "
                              "worse than idling at every tick, and crossing + landing + a later fall still beats staying "
                              "right for delta < 2); delta = 0.5 proposed; a separate future id (btt_reward_v3_l2)"}


# -- first-clear relevance -------------------------------------------------------------------------------------------


def relevance(eps: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """L (leading): target 2 broken by consumed tick 2,699 in an episode that also breaks >= 5 of the 6 static targets.
    R (relevance): all seven right targets broken by consumed tick 2,699 (>= 900 ticks left for crossing + left side)."""
    by: Dict[str, Dict[str, int]] = {}
    for e in eps:
        key = f"{e['run']}:{e['label']}:{e['mode']}"
        d = by.setdefault(key, {"n": 0, "L": 0, "R": 0, "t2": 0})
        d["n"] += 1
        t2t = next((t for tid, t in e["breaks"] if tid == T2), None)
        d["t2"] += t2t is not None
        d["L"] += t2t is not None and t2t <= DEADLINE_TICK and statics(e) >= 5
        s = sweep_tick(e["breaks"])
        d["R"] += s is not None and s <= DEADLINE_TICK
    finals = {k: v for k, v in by.items() if ":final:stochastic" in k}
    return {"definition": relevance.__doc__, "final_stochastic": finals,
            "pooled_all_labels": {k: sum(v[k] for v in by.values()) for k in ("n", "L", "R", "t2")}}


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="M7k offline reward comparison")
    p.add_argument("--target2", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    t2dir = Path(a.target2) if Path(a.target2).is_absolute() else REPO_ROOT / a.target2
    out = Path(a.out) if Path(a.out).is_absolute() else REPO_ROOT / a.out
    ev = eval_episodes()
    tr = train_episodes(t2dir)
    # consistency: the closed-form v2 equals every recorded evaluation return
    bad = [e["episode_id"] for e in ev if e["recorded_return"] is not None and abs(r_v2(e) - e["recorded_return"]) > 1e-6]
    pops = {
        "eval_all_tick0": ev,
        "eval_policies_stochastic": [e for e in ev if e["mode"] == "stochastic" and e["run"] != "random_baseline"],
        "eval_phase_k_v1_final_stochastic": [e for e in ev if e["run"] in ("m7g_s0_v1", "m7g_s1_v1", "m7g_s2_v1")
                                             and e["label"] == "final" and e["mode"] == "stochastic"],
        "train_phase_k_v1_sample": tr,
    }
    res = {"contract": "m7k_reward_comparison_v1", "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "recorded_v2_mismatches": bad[:10], "populations": {k: compare(v, k) for k, v in pops.items() if v},
           "pair_rankings": pair_rankings(), "landing_assessment": landing_assessment(),
           "relevance": relevance(ev),
           "train_t2_rate": {"episodes": len(tr), "t2": sum(1 for e in tr if has_t2(e)),
                             "by_run": {r: [len([e for e in tr if e["run"] == r]),
                                            sum(1 for e in tr if e["run"] == r and has_t2(e))]
                                        for r in sorted({e["run"] for e in tr})}}}
    t2m.write_json(out / "comparison.json", res)
    print(json.dumps({"mismatches": len(bad), "train_t2_rate": res["train_t2_rate"]}, indent=1))
    for name, pop in res["populations"].items():
        print(f"== {name}: n {pop['episodes']}, target 2 {pop['t2_episodes']} ({pop['t2_rate']})")
        for c, row in pop["candidates"].items():
            s = row["signal"]
            print(f"  {c:8s} mean {row['mean_return']:>8} z {s['mean_z']} pct {s['t2_mean_percentile']} "
                  f"gap_six {row['contrast']['gap_six']} gap_any {row['contrast']['gap_any']} "
                  f"nonzero {row.get('new_term_nonzero_rate')} t2mass {row.get('new_term_mass_on_target2')}")
    for pr in res["pair_rankings"]:
        print(pr["candidate"], "->", " > ".join(k.split(":")[0] for k in pr["order"]))
    for r in res["landing_assessment"]["rows"]:
        print(r)
    print(json.dumps(res["relevance"]["pooled_all_labels"]), json.dumps(res["relevance"]["final_stochastic"]))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
