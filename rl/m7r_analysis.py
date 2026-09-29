#!/usr/bin/env python3
"""M7r control-learning gate: exact measures, bootstrap intervals and the decision rule (design rev 3, section 5).

    python rl/m7r_analysis.py self-test
    python rl/m7r_analysis.py measures <gate_trace.json.gz>

Measures (one episode, from the per-tick gate trace written by rl/m7r_worker.GateTraceWrapper; rows[0] = the tick-0
observe reply R_-1, rows[t + 1] = the reply R_t after consumed tick t with the word consumed on tick t):

  live tick t      R_{t-1} and R_t both live (btt_active, fighter_valid, valid input object)
  ST1 (decisive)   A = live ticks with airborne(R_{t-1}); segments = maximal runs of consecutive ticks of A; S = segments
                   of >= 40 ticks; coh(G) = abs(sum sgn(stick_x_t)) / len(G); ST1 = mean over S; defined iff S non-empty
  PR1 (decisive)   M = A | B | C-up | C-left | L (an R press is counted through its folded A bit; Z excluded); press ticks
                   P = live t with hitlag(R_{t-1}) == 0 and tap(R_t) & M != 0, minus ticks whose only move bit is B while
                   class(R_{t-1}) == special_lw (tornado presses); effective = status(R_t) != status(R_{t-1});
                   PR1 = effective / len(P); defined iff P non-empty
  RE1 (supporting) distinct floor_line_id >= 0 over R_t of live ticks with airborne(R_t) == 0
  T (guardrail)    10 - targets_remaining of the last reply

Rule (per seed s, M in {ST1, PR1}; included episodes only; 90 % percentile bootstrap of the difference of means, 10,000
resamples within each group, generator seeded from sha256("m7r_gate|<s>|<M>|<comparison>")): M improves in seed s iff
the lower bounds of (C final - F final) and (C final - C untrained) are both > 0; a group with < 5 included episodes
leaves M undefined (never improved). Outcomes in order: invalid / incomplete; pass_discovery (a verified clear,
qualified crossing or left-target break in any C final episode); fail_no_learning (mean T C final <= C untrained in
>= 2 seeds); fail_regression (mean T C final <= F final - 1/2 in >= 2 seeds); pass_control (>= 2 seeds in each of which
BOTH ST1 and PR1 improve); inconclusive. RE1 is reported with the same intervals and never decides. Exploratory: a pass
is not proof of long-run superiority. Python-side RNG only; the native RNG is never touched.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import numpy as np

RULE_ID = "m7r_gate_rule_v1"
DECISIVE = ("ST1", "PR1")
SUPPORTING = ("RE1",)
MEASURES = DECISIVE + SUPPORTING + ("T",)
SEGMENT_MIN = 40
MIN_INCLUDED = 5
BOOTSTRAP_RESAMPLES = 10_000
CI_LEVEL = 0.90
T_MARGIN = Fraction(1, 2)
SEEDS_REQUIRED = 2
BUTTON_A, BUTTON_B, BUTTON_Z, BUTTON_L, BUTTON_C_UP, BUTTON_C_LEFT = 0x8000, 0x4000, 0x2000, 0x0020, 0x0008, 0x0002
MOVE_MASK = BUTTON_A | BUTTON_B | BUTTON_C_UP | BUTTON_C_LEFT | BUTTON_L
F = {name: i for i, name in enumerate(("t", "buttons", "stick_x", "stick_y", "live", "status", "klass", "airborne",
                                        "hitlag", "button_tap", "button_hold", "floor_line_id", "air_vx", "air_vy",
                                        "pos_x", "pos_y", "targets"))}


def read_trace(path: Path) -> Dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as fp:
        return json.load(fp)


def _special_lw_index(classes: Sequence[str]) -> int:
    return list(classes).index("special_lw")


def episode_measures(rows: Sequence[Sequence[Any]], classes: Sequence[str]) -> Dict[str, Any]:
    """ST1, PR1, RE1, T and their denominators for one episode (None = undefined)."""
    lw = _special_lw_index(classes)
    n = len(rows) - 1          # consumed ticks
    live = [bool(rows[t][F["live"]]) and bool(rows[t + 1][F["live"]]) for t in range(n)]
    # ST1
    segments: List[List[int]] = []
    cur: List[int] = []
    for t in range(n):
        if live[t] and rows[t][F["airborne"]] == 1:
            cur.append(t)
        elif cur:
            segments.append(cur)
            cur = []
    if cur:
        segments.append(cur)
    long_segs = [g for g in segments if len(g) >= SEGMENT_MIN]
    cohs = []
    for g in long_segs:
        s = sum((1 if rows[t + 1][F["stick_x"]] > 0 else -1 if rows[t + 1][F["stick_x"]] < 0 else 0) for t in g)
        cohs.append(abs(s) / len(g))
    st1 = float(np.mean(cohs)) if cohs else None
    # PR1
    presses = effective = 0
    for t in range(n):
        if not live[t] or rows[t][F["hitlag"]] != 0:
            continue
        bits = int(rows[t + 1][F["button_tap"]]) & MOVE_MASK
        if not bits:
            continue
        if bits == BUTTON_B and rows[t][F["klass"]] == lw:
            continue
        presses += 1
        effective += int(rows[t + 1][F["status"]] != rows[t][F["status"]])
    pr1 = (effective / presses) if presses else None
    # RE1, T
    floors = {int(rows[t + 1][F["floor_line_id"]]) for t in range(n)
              if live[t] and rows[t + 1][F["airborne"]] == 0 and int(rows[t + 1][F["floor_line_id"]]) >= 0}
    return {"ST1": st1, "PR1": pr1, "RE1": len(floors), "T": 10 - int(rows[-1][F["targets"]]),
            "ticks": n, "st1_segments": len(long_segs), "pr1_presses": presses, "pr1_effective": effective,
            "floors": sorted(floors)}


# -- bootstrap -----------------------------------------------------------------------------------------------------


def _rng(*parts: Any) -> np.random.Generator:
    key = "m7r_gate|" + "|".join(str(p) for p in parts)
    return np.random.default_rng(int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "little"))


def bootstrap_diff(a: Sequence[float], b: Sequence[float], rng: np.random.Generator,
                   resamples: int = BOOTSTRAP_RESAMPLES, level: float = CI_LEVEL) -> Dict[str, float]:
    """Percentile interval of mean(a) - mean(b), resampling episodes with replacement within each group."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    ma = a[rng.integers(0, len(a), size=(resamples, len(a)))].mean(axis=1)
    mb = b[rng.integers(0, len(b), size=(resamples, len(b)))].mean(axis=1)
    d = ma - mb
    lo, hi = np.quantile(d, [(1 - level) / 2, 1 - (1 - level) / 2])
    return {"diff": float(a.mean() - b.mean()), "lo": float(lo), "hi": float(hi)}


def _defined(values: Sequence[Optional[float]]) -> List[float]:
    return [float(v) for v in values if v is not None]


def seed_comparison(seed: Any, groups: Mapping[str, Mapping[str, Sequence[Optional[float]]]]) -> Dict[str, Any]:
    """groups = {"C_final": {measure: [per-episode values]}, "C_untrained": {...}, "F_final": {...}}."""
    out: Dict[str, Any] = {}
    for m in DECISIVE + SUPPORTING:
        cf, ff, cu = (_defined(groups[g][m]) for g in ("C_final", "F_final", "C_untrained"))
        rec: Dict[str, Any] = {"included": {"C_final": len(cf), "F_final": len(ff), "C_untrained": len(cu)}}
        if min(len(cf), len(ff), len(cu)) < MIN_INCLUDED:
            rec.update({"defined": False, "improves": False})
        else:
            vs_f = bootstrap_diff(cf, ff, _rng(seed, m, "C_final-F_final"))
            vs_u = bootstrap_diff(cf, cu, _rng(seed, m, "C_final-C_untrained"))
            rec.update({"defined": True, "vs_F": vs_f, "vs_untrained": vs_u,
                        "improves": bool(vs_f["lo"] > 0 and vs_u["lo"] > 0),
                        "F_better": bool(vs_f["hi"] < 0)})
        out[m] = rec
    t = {g: [Fraction(int(v)) for v in groups[g]["T"]] for g in ("C_final", "F_final", "C_untrained")}
    means = {g: (sum(v, Fraction(0)) / len(v)) if v else None for g, v in t.items()}
    out["T"] = {"means": {g: (None if v is None else str(v)) for g, v in means.items()},
                "means_float": {g: (None if v is None else float(v)) for g, v in means.items()},
                "no_learning": means["C_final"] is not None and means["C_untrained"] is not None
                and means["C_final"] <= means["C_untrained"],
                "regression": means["C_final"] is not None and means["F_final"] is not None
                and means["C_final"] <= means["F_final"] - T_MARGIN}
    out["both_decisive_improve"] = all(out[m]["improves"] for m in DECISIVE)
    return out


def decide(inputs: Mapping[str, Any]) -> Dict[str, Any]:
    """inputs = {"integrity": {"ok": bool, "problems": [...]}, "complete": bool, "incomplete_reasons": [...],
    "discovery": {"C_final": [events]}, "seeds": {s: groups}}; returns the outcome and every intermediate value."""
    report: Dict[str, Any] = {"rule": RULE_ID, "exploratory": True}
    if not (inputs.get("integrity") or {}).get("ok", False):
        report.update(outcome="invalid", reasons=list((inputs.get("integrity") or {}).get("problems") or ["integrity"]))
        return report
    if not inputs.get("complete", False):
        report.update(outcome="incomplete", reasons=list(inputs.get("incomplete_reasons") or []))
        return report
    per_seed = {str(s): seed_comparison(s, g) for s, g in sorted((inputs.get("seeds") or {}).items())}
    report["per_seed"] = per_seed
    discoveries = list((inputs.get("discovery") or {}).get("C_final") or [])
    report["discoveries"] = discoveries
    no_learning = sum(1 for r in per_seed.values() if r["T"]["no_learning"])
    regression = sum(1 for r in per_seed.values() if r["T"]["regression"])
    both = [s for s, r in per_seed.items() if r["both_decisive_improve"]]
    report["counts"] = {"seeds": len(per_seed), "no_learning_seeds": no_learning, "regression_seeds": regression,
                        "seeds_with_both_ST1_and_PR1_improving": both}
    if discoveries:
        report.update(outcome="pass_discovery", reasons=[f"{len(discoveries)} verified discovery event(s) in C finals"])
    elif no_learning >= SEEDS_REQUIRED:
        report.update(outcome="fail_no_learning", reasons=[f"mean T of C final <= C untrained in {no_learning} seeds"])
    elif regression >= SEEDS_REQUIRED:
        report.update(outcome="fail_regression", reasons=[f"mean T of C final <= F final - 1/2 in {regression} seeds"])
    elif len(both) >= SEEDS_REQUIRED:
        report.update(outcome="pass_control", reasons=[f"ST1 and PR1 both improve in seeds {both}"])
    else:
        report.update(outcome="inconclusive", reasons=[f"ST1 and PR1 both improve in {len(both)} seed(s)"])
    return report


# -- self-test --------------------------------------------------------------------------------------------------------


def _groups(rng: np.random.Generator, *, c: Mapping[str, float], f: Mapping[str, float], u: Mapping[str, float],
            n: int = 30, nu: int = 20, t: Sequence[float] = (5.0, 5.0, 3.0), sd: float = 0.05) -> Dict[str, Any]:
    def g(mu: Mapping[str, float], k: int, tm: float) -> Dict[str, List[Any]]:
        return {"ST1": list(np.clip(rng.normal(mu["ST1"], sd, k), 0, 1)),
                "PR1": list(np.clip(rng.normal(mu["PR1"], sd, k), 0, 1)),
                "RE1": list(rng.integers(1, 5, k)), "T": [int(round(tm))] * k}
    return {"C_final": g(c, n, t[0]), "F_final": g(f, n, t[1]), "C_untrained": g(u, nu, t[2])}


def self_test() -> int:
    rng = np.random.default_rng(7)
    ok = True

    def expect(cond: bool, name: str) -> None:
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + name)
        ok = ok and cond

    good = {"ST1": 0.7, "PR1": 0.6}
    base = {"ST1": 0.3, "PR1": 0.3}
    integ = {"ok": True, "problems": []}

    def run(seeds: Mapping[str, Any], **kw: Any) -> Dict[str, Any]:
        return decide({"integrity": kw.get("integrity", integ), "complete": kw.get("complete", True),
                       "discovery": {"C_final": kw.get("disc", [])}, "seeds": seeds})

    all3 = {s: _groups(rng, c=good, f=base, u=base) for s in (0, 1, 2)}
    expect(run(all3)["outcome"] == "pass_control", "clear improvement in 3 seeds -> pass_control")
    one = {0: _groups(rng, c=good, f=base, u=base), 1: _groups(rng, c=base, f=base, u=base),
           2: _groups(rng, c=base, f=base, u=base)}
    expect(run(one)["outcome"] == "inconclusive", "improvement in 1 seed only -> inconclusive")
    split = {0: _groups(rng, c={"ST1": 0.7, "PR1": 0.3}, f=base, u=base),
             1: _groups(rng, c=good, f=base, u=base),
             2: _groups(rng, c={"ST1": 0.3, "PR1": 0.6}, f=base, u=base)}
    r = run(split)
    expect(r["outcome"] == "inconclusive" and r["counts"]["seeds_with_both_ST1_and_PR1_improving"] == ["1"],
           "ST1 and PR1 improving in different seeds (both only in seed 1) -> inconclusive")
    structural = {s: _groups(rng, c=good, f=base, u=good) for s in (0, 1, 2)}
    expect(run(structural)["outcome"] == "inconclusive", "better than F but not than its own untrained -> not improved")
    reg = {s: _groups(rng, c=good, f=base, u=base, t=(4.0, 5.0, 3.0)) for s in (0, 1, 2)}
    expect(run(reg)["outcome"] == "fail_regression", "control gains with T 1 below F in 3 seeds -> fail_regression")
    edge = {s: _groups(rng, c=good, f=base, u=base, t=(5.0, 5.5, 3.0)) for s in (0, 1, 2)}
    expect(decide({"integrity": integ, "complete": True, "discovery": {}, "seeds": {
        s: dict(g, C_final=dict(g["C_final"], T=[5] * 30), F_final=dict(g["F_final"], T=[5, 6] * 15))
        for s, g in edge.items()}})["outcome"] == "fail_regression", "T exactly 1/2 below F -> regression (inclusive)")
    nol = {s: _groups(rng, c=good, f=base, u=base, t=(3.0, 3.0, 3.0)) for s in (0, 1, 2)}
    expect(run(nol)["outcome"] == "fail_no_learning", "T equal to untrained in 3 seeds -> fail_no_learning (inclusive)")
    expect(run(reg, disc=[{"episode_id": "x", "kind": "qualified_crossing"}])["outcome"] == "pass_discovery",
           "a verified discovery passes even with a regression")
    expect(run(all3, integrity={"ok": False, "problems": ["replay not exact"]})["outcome"] == "invalid",
           "integrity failure -> invalid")
    expect(run(all3, complete=False)["outcome"] == "incomplete", "missing run -> incomplete")
    few = {s: dict(g, C_untrained=dict(g["C_untrained"], ST1=[None] * 16 + [0.3] * 4)) for s, g in all3.items()}
    r = run(few)
    expect(r["outcome"] == "inconclusive" and not r["per_seed"]["0"]["ST1"]["defined"],
           "fewer than 5 included episodes -> ST1 undefined, never improved")
    # measures on a synthetic trace
    classes = ["idle_ground", "airborne", "special_lw"]
    rows = [[-1, None, None, None, 1, 10, 0, 0, 0, 0, 0, 3, 0.0, 0.0, 0.0, 0.0, 10]]
    for t in range(60):   # 60 airborne ticks, stick left 45 / right 15; one effective A press, one lost A press
        tap = BUTTON_A if t in (10, 20) else 0
        status = 20 if t < 10 else 21
        rows.append([t, tap, -80 if t < 45 else 80, 0, 1, status, 1, 1, 0, tap, tap, -1, 0.0, 0.0, 0.0, 0.0, 10])
    rows.append([60, 0, 0, 0, 1, 30, 0, 0, 0, 0, 0, 3, 0.0, 0.0, 0.0, 0.0, 9])
    m = episode_measures(rows, classes)
    # ticks 1..60 meet an airborne reply (row 0 is grounded): 44 left, 15 right, 1 neutral -> abs(-29) / 60
    expect(m["ST1"] is not None and abs(m["ST1"] - 29 / 60) < 1e-9 and m["st1_segments"] == 1,
           f"ST1 on a 60-tick airborne segment (44 left, 15 right, 1 neutral) = 29/60 ({m['ST1']})")
    expect(m["pr1_presses"] == 2 and m["pr1_effective"] == 1 and m["PR1"] == 0.5, f"PR1 = 1 effective / 2 presses ({m})")
    expect(m["RE1"] == 1 and m["T"] == 1, "RE1 counts floor line 3 once; T = 1")
    print("self-test", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("self-test")
    mp = sub.add_parser("measures")
    mp.add_argument("trace", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "self-test":
        return self_test()
    doc = read_trace(a.trace)
    print(json.dumps(episode_measures(doc["rows"], doc["classes"]), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
