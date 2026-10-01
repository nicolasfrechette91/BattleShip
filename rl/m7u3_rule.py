"""M7u3 gate m7u3 (proposed): rule `m7u3_refit_rule_v1`, the pre-declared model-diagnostic reading, and the M7u2
replication readout (design: docs/rl_model_planning_m7u3_proposal_2026-10-01.md section 5-6, as amended by
docs/rl_model_planning_m7u3_decisions_2026-10-01.md). Pure Python (no NumPy, no torch).

Arms (24 independent goals each, one stream per goal per arm, success = the first valid reach of g within 128 ticks of
the normal tick-0 reset): PF = P_frozen (the m7u1 model), PR = P_refit, RC = no model, SR = S_refit (the refit commanded
pi(g), scored on g). For X in {PF, RC, SR}: b_X = #(PR and not X), c_X = #(not PR and X), d_X = b_X + c_X and
p_X = sum_{i = b_X}^{d_X} C(d_X, i) / 2^d_X, the exact one-sided sign probability (p_X = 1 when d_X = 0).

- INVALID: any integrity failure. INCOMPLETE: a cap or goal-availability stop (not a result; no retry).
- PASS: p_PF <= 0.05 and p_RC <= 0.05 and p_SR <= 0.05 (an intersection-union test, no multiplicity correction).
- NULL: b_PF - c_PF <= 1.
- INCONCLUSIVE otherwise; the record names each blocker.

PASS and NULL cannot both hold: p_PF <= 0.05 needs b_PF - c_PF >= 5. The rule is applied once, to complete paired
outcomes, after every success replay is verified; no diagnostic quantity enters it.

Everything below `rule_digest` is REPORTED beside the decision and can never alter it:
- `readings`: the proposal's pre-registered readings of a NULL / INCONCLUSIVE outcome;
- `model_reading`: how the strict from-reset open-loop error of the refit relative to the frozen model is read, with the
  P_retrain-versus-frozen difference as the retrain-variation reference (fixed before any native data existed);
- `replication_readout`: P_frozen versus RC on the fresh independent goals against M7u2's PASS thresholds.

    python rl/m7u3_rule.py self-test
"""
from __future__ import annotations

import hashlib
import json
import sys
from math import comb
from typing import Any, Dict, List, Mapping, Optional, Sequence

RULE_ID = "m7u3_refit_rule_v1"
N = 24
ARMS = ("PF", "PR", "RC", "SR")
ALPHA_NUM, ALPHA_DEN = 1, 20                       # alpha = 0.05, compared in exact integer arithmetic
NULL_MAX_BF = 1
PRIMARY_MIN_DIFF = 2                               # a "primary not significant" blocker needs b_PF - c_PF >= 2
SCOPE = ("refit-versus-frozen test of planner-controlled reach of rare behaviour-drawn airborne points from the normal "
         "tick-0 reset (one seed, one refit, 24 non-overlapping goals)")
FORBIDDEN_WORDS = ("landing", "crossing", "cross the wall", "wall top", "wall-top", "clear", "target")
NOT_ESTABLISHED = ("tick-0-specific data (rather than more data of any kind or a changed training trajectory) as the cause",
                   "replication across seeds, refits or pools", "reach of points the training pool never passed through early",
                   "goals beyond 128 ticks or sequences of goals", "a landing", "the wall top", "a crossing", "targets",
                   "a clear", "any advantage over PPO", "any change to the selected baseline")

# the proposal's pre-registered readings of a NULL / INCONCLUSIVE outcome (section 6)
O_FLOOR = -0.20                                    # a refit reduction of the strict 64-tick median error of at least 20 %
DW_NONE, DW_SOME = 1, 3                            # witness-acceptance differences W_refit - W_frozen
HORIZONS = (16, 32, 64, 96)
PRIMARY_HORIZON = 64
# the M7u2 PASS thresholds the replication readout applies in independent units (the S condition is not evaluable:
# decision 5 has no S_frozen arm)
M7U2_PASS_MIN_P, M7U2_PASS_MIN_BR, M7U2_NULL_MAX_BR = 6, 6, 1
# every appearance of the replication readout carries this label (amendment record, 2026-10-01)
REPLICATION_READING_LABEL = "partial replication (S condition not evaluable)"


def p_exact(b: int, c: int) -> float:
    """Exact one-sided sign probability P(X >= b), X ~ Binomial(b + c, 1/2); 1.0 when there are no discordant pairs."""
    d = b + c
    if d == 0:
        return 1.0
    return sum(comb(d, i) for i in range(b, d + 1)) / 2 ** d


def significant(b: int, c: int) -> bool:
    """p_exact(b, c) <= 0.05, decided in exact integer arithmetic (no float comparison at the boundary)."""
    d = b + c
    if d == 0:
        return False
    return sum(comb(d, i) for i in range(b, d + 1)) * ALPHA_DEN <= ALPHA_NUM * 2 ** d


def paired(pr: Sequence[bool], other: Sequence[bool]) -> Dict[str, Any]:
    b = sum(1 for a, x in zip(pr, other) if a and not x)
    c = sum(1 for a, x in zip(pr, other) if x and not a)
    return {"b": b, "c": c, "diff": b - c, "p": p_exact(b, c), "significant": significant(b, c)}


def apply(outcomes: Mapping[str, Sequence[bool]], *, integrity_ok: bool, incomplete: Optional[str] = None) -> Dict[str, Any]:
    """outcomes: arm -> 24 booleans in registered goal order."""
    if incomplete:
        return {"rule": RULE_ID, "outcome": "INCOMPLETE", "reason": incomplete,
                "note": "a cap or availability stop: not a performance result; no retry, extension or relaxation"}
    if not integrity_ok:
        return {"rule": RULE_ID, "outcome": "INVALID", "reason": "integrity failure (see the integrity record)"}
    for arm in ARMS:
        if len(outcomes.get(arm, ())) != N:
            return {"rule": RULE_ID, "outcome": "INVALID", "reason": f"arm {arm} has {len(outcomes.get(arm, ()))} outcomes"}
    o = {a: list(map(bool, outcomes[a])) for a in ARMS}
    vs = {"PF": paired(o["PR"], o["PF"]), "RC": paired(o["PR"], o["RC"]), "SR": paired(o["PR"], o["SR"])}
    passed = all(v["significant"] for v in vs.values())
    null = vs["PF"]["diff"] <= NULL_MAX_BF
    if passed and null:
        raise AssertionError("PASS and NULL overlap")          # impossible by construction
    blockers: List[str] = []
    if not passed:
        if vs["PF"]["diff"] >= PRIMARY_MIN_DIFF and not vs["PF"]["significant"]:
            blockers.append(f"primary not significant: b-c {vs['PF']['diff']}, p {vs['PF']['p']:.4f} > 0.05")
        if not vs["RC"]["significant"]:
            blockers.append(f"not model-attributable: p vs RC {vs['RC']['p']:.4f} > 0.05")
        if not vs["SR"]["significant"]:
            blockers.append(f"undirected: p vs S_refit {vs['SR']['p']:.4f} > 0.05")
    outcome = "PASS" if passed else ("NULL" if null else "INCONCLUSIVE")
    return {"rule": RULE_ID, "outcome": outcome, "n": {a: sum(o[a]) for a in ARMS},
            "PR_vs_PF": vs["PF"], "PR_vs_RC": vs["RC"], "PR_vs_SR": vs["SR"],
            "blockers": [] if outcome != "INCONCLUSIVE" else blockers, "scope": SCOPE,
            "not_established": list(NOT_ESTABLISHED)}


def readings(decision: Mapping[str, Any], *, o_rel: Optional[float], d_w: Optional[int]) -> List[str]:
    """The proposal's pre-registered readings (reported only; never an outcome). o_rel: the relative change of the median
    strict 64-tick from-rest error on the goal pool, refit versus frozen (D2a; negative = the refit is better).
    d_w: W_refit - W_frozen, the difference in goals whose recorded path the model accepts from tick 0."""
    if decision.get("outcome") not in ("NULL", "INCONCLUSIVE", "PASS"):
        return []
    out: List[str] = []
    f, r, s = decision["PR_vs_PF"], decision["PR_vs_RC"], decision["PR_vs_SR"]
    if decision["outcome"] != "PASS":
        if o_rel is None or d_w is None:
            out.append("unread: the model diagnostics are unavailable")
        else:
            if o_rel > O_FLOOR and d_w <= DW_NONE:
                out.append("no model gain from rest: at this dose the added data did not materially reduce from-rest "
                           "rollout error; the limit lies in the model or its training form, not in how densely the "
                           "data cover the reset neighbourhood")
            if (o_rel <= O_FLOOR or d_w >= DW_SOME) and f["diff"] <= NULL_MAX_BF:
                out.append("model gain, no reach gain: prediction from rest improved but reach did not; search or the "
                           "remaining error is binding")
        if -f["diff"] >= 2:
            out.append("regression: the refit reached fewer goals than the frozen model")
    if f["significant"] and not r["significant"]:
        out.append("not model-attributable: the no-model control also reaches the points the refit gained")
    if f["significant"] and not s["significant"]:
        out.append("undirected: the refit sends the planner to more airborne points whatever the command")
    return out


def _med(v: Sequence[float]) -> float:
    s = sorted(v)
    n = len(s)
    return float(s[n // 2]) if n % 2 else float((s[n // 2 - 1] + s[n // 2]) / 2.0)


def model_reading(strict: Mapping[int, Mapping[str, Sequence[float]]]) -> Dict[str, Any]:
    """The pre-declared reading of the strict from-reset open-loop position error on the goal pool (never fitted).

    strict[h] = {"frozen": [...], "refit": [...], "retrain": [...]}: per-episode Chebyshev errors of the ensemble-mean
    position h ticks after the reset row, over the same episodes for the three models.

    Quantities (positive = lower error than the frozen model):
        red_refit(h)   = 1 - median(refit) / median(frozen)
        red_retrain(h) = 1 - median(retrain) / median(frozen)        the retrain-variation reference (one draw)
        better_refit(h), better_retrain(h) = share of episodes where that model's error is below the frozen model's.
    At the primary horizon h = 64:
        FLOOR   = red_refit >= 0.20                                   (the proposal's O <= -0.20)
        BEYOND  = red_refit > max(red_retrain, 0) and better_refit >= better_retrain, and red_refit(h) > red_retrain(h)
                  at no fewer than 3 of the 4 horizons.
    Label:
        MODEL_GAIN_BEYOND_RETRAIN_VARIATION  if FLOOR and BEYOND
        MODEL_GAIN_WITHIN_RETRAIN_VARIATION  if FLOOR and not BEYOND
        MODEL_REGRESSION                      if red_refit <= -0.20
        NO_MODEL_GAIN                         otherwise
    One retrain is one draw of retrain variation, not an interval. The label is reported and never alters the decision."""
    per: Dict[str, Any] = {}
    for h in HORIZONS:
        d = strict.get(h) or {}
        if not all(k in d and len(d[k]) for k in ("frozen", "refit", "retrain")):
            return {"label": "UNAVAILABLE", "reason": f"no strict errors at horizon {h}"}
        n = len(d["frozen"])
        if not (len(d["refit"]) == len(d["retrain"]) == n):
            return {"label": "UNAVAILABLE", "reason": f"horizon {h}: unequal episode counts"}
        mf, mr, mt = _med(d["frozen"]), _med(d["refit"]), _med(d["retrain"])
        per[h] = {"episodes": n, "median_frozen": mf, "median_refit": mr, "median_retrain": mt,
                  "red_refit": 1.0 - mr / mf if mf else None, "red_retrain": 1.0 - mt / mf if mf else None,
                  "better_refit": sum(1 for a, b in zip(d["refit"], d["frozen"]) if a < b) / n,
                  "better_retrain": sum(1 for a, b in zip(d["retrain"], d["frozen"]) if a < b) / n,
                  "median_paired_diff_refit_minus_frozen": _med([a - b for a, b in zip(d["refit"], d["frozen"])]),
                  "median_paired_diff_retrain_minus_frozen": _med([a - b for a, b in zip(d["retrain"], d["frozen"])])}
    p = per[PRIMARY_HORIZON]
    if p["red_refit"] is None:
        return {"label": "UNAVAILABLE", "reason": "zero frozen median"}
    floor = p["median_refit"] <= (1.0 + O_FLOOR) * p["median_frozen"]             # a reduction of at least 20 %
    agree = sum(1 for h in HORIZONS if per[h]["red_refit"] is not None and per[h]["red_retrain"] is not None
                and per[h]["red_refit"] > per[h]["red_retrain"])
    beyond = (p["red_refit"] > max(p["red_retrain"], 0.0) and p["better_refit"] >= p["better_retrain"] and agree >= 3)
    if floor and beyond:
        label = "MODEL_GAIN_BEYOND_RETRAIN_VARIATION"
    elif floor:
        label = "MODEL_GAIN_WITHIN_RETRAIN_VARIATION"
    elif p["median_refit"] >= (1.0 - O_FLOOR) * p["median_frozen"]:             # an increase of at least 20 %
        label = "MODEL_REGRESSION"
    else:
        label = "NO_MODEL_GAIN"
    return {"label": label, "primary_horizon": PRIMARY_HORIZON, "floor_met": floor, "beyond_retrain_variation": beyond,
            "horizons_where_refit_beats_retrain_reduction": agree, "per_horizon": {str(h): per[h] for h in HORIZONS},
            "o_rel_64": -p["red_refit"], "caveat": "one retrain is one draw of retrain variation, not an interval"}


def replication_readout(outcomes: Mapping[str, Sequence[bool]]) -> Dict[str, Any]:
    """P_frozen versus RC on the 24 fresh independent goals against M7u2's PASS thresholds applied in independent units.
    M7u2's PASS also needed b_S - c_S >= 5 against a scrambled-command control of the FROZEN model; there is no S_frozen
    arm in m7u3 (decision 5), so that condition is NOT evaluable and is reported as such. A separate readout: it never
    changes the m7u3 decision."""
    pf, rc = list(map(bool, outcomes["PF"])), list(map(bool, outcomes["RC"]))
    if len(pf) != N or len(rc) != N:
        return {"readout": "m7u2_replication_readout_v1", "label": "UNAVAILABLE", "reading_label": REPLICATION_READING_LABEL}
    v = paired(pf, rc)                                   # b = P_frozen only, c = RC only
    n_p = sum(pf)
    meets = n_p >= M7U2_PASS_MIN_P and v["diff"] >= M7U2_PASS_MIN_BR
    null = v["diff"] <= M7U2_NULL_MAX_BR
    label = "MEETS_EVALUABLE_M7U2_PASS_CONDITIONS" if meets else ("NULL_VS_RC" if null else "INCONCLUSIVE")
    return {"readout": "m7u2_replication_readout_v1", "label": label, "reading_label": REPLICATION_READING_LABEL,
            "n_P_frozen": n_p, "n_RC": sum(rc),
            "PF_vs_RC": v, "thresholds": {"n_P_min": M7U2_PASS_MIN_P, "b_minus_c_min": M7U2_PASS_MIN_BR,
                                          "null_max_b_minus_c": M7U2_NULL_MAX_BR},
            "unit": "goal (the 24 goals are independent by construction)",
            "not_evaluable": "M7u2's b_S - c_S >= 5 condition: no S_frozen arm (decision 5)",
            "never_alters": "the m7u3 decision"}


def rule_digest() -> str:
    d = {"rule": RULE_ID, "n": N, "arms": list(ARMS), "alpha": [ALPHA_NUM, ALPHA_DEN], "null_max_bf": NULL_MAX_BF,
         "primary_min_diff": PRIMARY_MIN_DIFF, "pass": "p_PF, p_RC, p_SR <= alpha (exact one-sided sign)",
         "o_floor": O_FLOOR, "dw": [DW_NONE, DW_SOME], "horizons": list(HORIZONS), "primary_horizon": PRIMARY_HORIZON,
         "model_reading": ["FLOOR red_refit(64) >= 0.20",
                           "BEYOND red_refit > max(red_retrain, 0) and better_refit >= better_retrain and red_refit > "
                           "red_retrain at >= 3 of 4 horizons"],
         "replication": [M7U2_PASS_MIN_P, M7U2_PASS_MIN_BR, M7U2_NULL_MAX_BR]}
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode("utf-8")).hexdigest()


def scope_problems(text: str) -> List[str]:
    low = text.lower()
    return [w for w in FORBIDDEN_WORDS if w in low]


# the proposal's section 5 table: smallest passing results at one-sided alpha = 0.05
MIN_PASSING = {5: (5, 0, 0.031), 6: (6, 0, 0.016), 7: (7, 0, 0.008), 8: (7, 1, 0.035), 9: (8, 1, 0.020), 10: (9, 1, 0.011),
               11: (9, 2, 0.033), 12: (10, 2, 0.019), 13: (10, 3, 0.046), 14: (11, 3, 0.029)}


def _arms(n_pf: int, n_pr: int, ov_pf: int, n_rc: int = 0, n_sr: int = 0, ov_rc: int = 0, ov_sr: int = 0
          ) -> Dict[str, List[bool]]:
    """PR on goals 0..n_pr-1; X reaches `ov` of PR's goals and the rest from the end of the list."""
    def arm(n: int, ov: int) -> List[bool]:
        return [i < ov or (N - (n - ov)) <= i for i in range(N)] if n else [False] * N
    pr = [i < n_pr for i in range(N)]
    return {"PR": pr, "PF": arm(n_pf, ov_pf), "RC": arm(n_rc, ov_rc), "SR": arm(n_sr, ov_sr)}


def self_test() -> List[str]:
    probs: List[str] = []
    # section 5 table: exact boundaries (b, c passes; one fewer b with one more c does not)
    for d, (b, c, p) in MIN_PASSING.items():
        if b + c != d or not significant(b, c) or abs(p_exact(b, c) - p) > 0.0006:
            probs.append(f"d={d}: ({b}, {c}) p {p_exact(b, c):.4f}")
        if significant(b - 1, c + 1):
            probs.append(f"d={d}: ({b - 1}, {c + 1}) must not pass")
    if significant(4, 0) or not significant(5, 0) or significant(0, 0) or p_exact(0, 0) != 1.0:
        probs.append("sign-test boundaries")
    # PASS requires all three; failing any one is not a PASS
    base = _arms(0, 8, 0)
    if apply(base, integrity_ok=True)["outcome"] != "PASS":
        probs.append("8 vs 0 / 0 / 0 must PASS")
    for rc_hits in range(0, 9):
        a = _arms(0, 8, 0)
        a["RC"] = [False] * N
        for i in range(rc_hits):
            a["RC"][i] = True                          # RC reaches goals PR also reaches: c stays 0, b falls
        out = apply(a, integrity_ok=True)
        want_pass = significant(8 - rc_hits, 0)
        if (out["outcome"] == "PASS") != want_pass:
            probs.append(f"RC overlap {rc_hits}: {out['outcome']}")
    if apply(_arms(0, 6, 0), integrity_ok=True)["outcome"] != "PASS":
        probs.append("6 vs 0 / 0 / 0 must PASS")
    if apply(_arms(0, 4, 0), integrity_ok=True)["outcome"] == "PASS":
        probs.append("4 vs 0 / 0 / 0 must not PASS (p 0.0625)")
    if apply(_arms(0, 5, 0), integrity_ok=True)["outcome"] != "PASS":
        probs.append("5 vs 0 / 0 / 0 must PASS (p 0.031)")
    # INCONCLUSIVE names its blockers
    inc = apply(_arms(0, 4, 0), integrity_ok=True)
    if inc["outcome"] != "INCONCLUSIVE" or not any(b.startswith("primary not significant") for b in inc["blockers"]):
        probs.append(f"4 vs 0: {inc['outcome']} {inc.get('blockers')}")
    a = _arms(0, 8, 0)
    a["SR"] = [True] * 8 + [False] * 16               # S_refit reaches everything PR does: undirected
    s_out = apply(a, integrity_ok=True)
    if s_out["outcome"] != "INCONCLUSIVE" or not any(b.startswith("undirected") for b in s_out["blockers"]):
        probs.append(f"undirected case: {s_out['outcome']} {s_out.get('blockers')}")
    # NULL threshold: b_F - c_F <= 1
    for n_pr, n_pf, ov, want in ((6, 5, 5, "NULL"), (7, 5, 5, "INCONCLUSIVE"), (8, 5, 5, "INCONCLUSIVE")):
        out = apply(_arms(n_pf, n_pr, ov), integrity_ok=True)
        if out["outcome"] != want:
            probs.append(f"PR {n_pr}, PF {n_pf} (overlap {ov}): {out['outcome']}, want {want}")
    # disjointness and totality over a structured enumeration
    for n_pr in range(N + 1):
        for n_pf in range(N + 1):
            for ov in range(max(0, n_pr + n_pf - N), min(n_pr, n_pf) + 1):
                for rc_n in (0, 3, 8):
                    for sr_n in (0, 3, 8):
                        arms = _arms(n_pf, n_pr, ov, n_rc=rc_n, n_sr=sr_n, ov_rc=0, ov_sr=min(sr_n, n_pr))
                        out = apply(arms, integrity_ok=True)
                        if out["outcome"] not in ("PASS", "NULL", "INCONCLUSIVE"):
                            probs.append(f"unexpected outcome {out['outcome']}")
                        if out["outcome"] == "PASS" and out["PR_vs_PF"]["diff"] < 5:
                            probs.append("PASS with b_PF - c_PF < 5")
                        if out["outcome"] == "NULL" and out["PR_vs_PF"]["significant"]:
                            probs.append("NULL with a significant primary")
    if apply(base, integrity_ok=False)["outcome"] != "INVALID":
        probs.append("integrity failure must be INVALID")
    if apply(base, integrity_ok=True, incomplete="wall cap")["outcome"] != "INCOMPLETE":
        probs.append("a cap stop must be INCOMPLETE")
    if apply({"PR": [True] * 23, "PF": [False] * 24, "RC": [False] * 24, "SR": [False] * 24},
             integrity_ok=True)["outcome"] != "INVALID":
        probs.append("a partial outcome list must be INVALID")
    # readout and reading
    rep = replication_readout({"PF": [True] * 7 + [False] * 17, "RC": [False] * 24})
    if rep["label"] != "MEETS_EVALUABLE_M7U2_PASS_CONDITIONS" or "S_frozen" not in rep["not_evaluable"]:
        probs.append(f"replication readout {rep['label']}")
    if replication_readout({"PF": [True] * 5 + [False] * 19, "RC": [False] * 24})["label"] != "INCONCLUSIVE":
        probs.append("replication: 5 vs 0 must be INCONCLUSIVE (n_P < 6)")
    if replication_readout({"PF": [True] * 1 + [False] * 23, "RC": [False] * 24})["label"] != "NULL_VS_RC":
        probs.append("replication: 1 vs 0 must be NULL_VS_RC")
    good = {h: {"frozen": [100.0 + i for i in range(20)], "refit": [60.0 + i for i in range(20)],
                "retrain": [98.0 + i for i in range(20)]} for h in HORIZONS}
    if model_reading(good)["label"] != "MODEL_GAIN_BEYOND_RETRAIN_VARIATION":
        probs.append(f"model reading (clear gain): {model_reading(good)['label']}")
    same = {h: {"frozen": [100.0 + i for i in range(20)], "refit": [70.0 + i for i in range(20)],
                "retrain": [70.0 + i for i in range(20)]} for h in HORIZONS}
    if model_reading(same)["label"] != "MODEL_GAIN_WITHIN_RETRAIN_VARIATION":
        probs.append(f"model reading (retrain does as well): {model_reading(same)['label']}")
    flat = {h: {"frozen": [100.0 + i for i in range(20)], "refit": [95.0 + i for i in range(20)],
                "retrain": [99.0 + i for i in range(20)]} for h in HORIZONS}
    if model_reading(flat)["label"] != "NO_MODEL_GAIN":
        probs.append(f"model reading (flat): {model_reading(flat)['label']}")
    worse = {h: {"frozen": [100.0 + i for i in range(20)], "refit": [130.0 + i for i in range(20)],
                 "retrain": [99.0 + i for i in range(20)]} for h in HORIZONS}
    if model_reading(worse)["label"] != "MODEL_REGRESSION":
        probs.append(f"model reading (regression): {model_reading(worse)['label']}")
    if model_reading({})["label"] != "UNAVAILABLE":
        probs.append("model reading without data must be UNAVAILABLE")
    if scope_problems(f"m7u3 ({SCOPE}): PASS; PF 3, PR 9, RC 0, SR 0 of 24") != []:
        probs.append("scope check false positive on the registered summary")
    if scope_problems("a wall-top landing") != ["landing", "wall-top"]:
        probs.append("scope check misses 'landing' / 'wall-top'")
    return probs


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "self-test":
        p = self_test()
        print(json.dumps({"rule": RULE_ID, "digest": rule_digest(), "problems": p}))
        sys.exit(1 if p else 0)
    print(json.dumps({"rule": RULE_ID, "digest": rule_digest()}))
