"""M7s stage 1: the pre-registered comparison and rule `m7s1_return_rule_v2` (design revision 5, section 6).

The goal is the unit of analysis. Per seed and rare goal g: r_g, u_g in {0, 1, 2} returns (first valid reaches, i.e.
goal_reached truncations) of R and U in their two evaluation episodes of g, d_g = r_g - u_g, T = sum d_g, and the exact
one-sided sign-flip p over the 2^10 goal-level sign patterns (valid under H0 because each d_g is symmetric when R and U have equal success probability on g).

v2 = v1 plus the goal-blind safeguard, registered before any live run: a seed whose trained R is goal-blind (its
post-training goal-swap action TV is below GOAL_BLIND_TV = 0.01) can never be a rare pass, however many goals it
reaches through generic behaviour; that seed is inconclusive and its success counts are reported. v1 was never applied.

    python rl/m7s_analysis.py self-test
"""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

RULE_ID = "m7s1_return_rule_v2"
RARE_T_MIN = 5
RARE_DISTINCT_MIN = 3
P_MAX = 0.05
MID_SUCCESS_MIN = 7
MID_T_MIN = 3
DATA_GOALS_MIN = 6
DATA_EPISODES_MIN = 2
REJECT_T_MAX = 1
SEEDS_REQUIRED = 2
GOAL_BLIND_TV = 0.01            # registered before any live run, never tuned; equals m7s_policy.GOAL_BLIND_TV (tested)


def rule_description() -> Dict[str, Any]:
    return {"rule": RULE_ID, "unit": "goal", "test": "exact one-sided goal-level sign flip",
            "rare_pass": {"T_min": RARE_T_MIN, "distinct_goals_min": RARE_DISTINCT_MIN, "p_max": P_MAX,
                          "goal_blind": "never a rare pass when R's post-training goal-swap action TV < goal_blind_tv"},
            "functional": {"mid_successes_min": MID_SUCCESS_MIN, "T_mid_min": MID_T_MIN},
            "data_present": {"goals_min": DATA_GOALS_MIN, "episodes_min": DATA_EPISODES_MIN},
            "reject": {"T_max": REJECT_T_MAX, "requires": ["functional", "data_present"]},
            "seeds_required": SEEDS_REQUIRED, "goal_blind_tv": GOAL_BLIND_TV,
            "success": "evaluation episodes with truncation_reason goal_reached only (a clear is never a return)",
            "outcomes": ["invalid", "incomplete", "pass_return_learned", "fail_return_not_learned", "inconclusive"]}


def rule_digest() -> str:
    return hashlib.sha256(json.dumps(rule_description(), sort_keys=True).encode("utf-8")).hexdigest()


def sign_flip_p(d: Sequence[int]) -> float:
    """Exact one-sided p = P(sum eps_g |d_g| >= sum d_g) over all 2^len(d) sign patterns."""
    t = sum(int(x) for x in d)
    mags = [abs(int(x)) for x in d]
    hits = sum(1 for eps in itertools.product((1, -1), repeat=len(mags)) if sum(e * m for e, m in zip(eps, mags)) >= t)
    return hits / 2 ** len(mags)


def per_goal(eval_rows: Sequence[Mapping[str, Any]], stratum: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for e in eval_rows:
        if e["stratum"] == stratum:
            out[e["cell"]] = out.get(e["cell"], 0) + int(bool(e["success"]))
    return out


def goal_blind_of(gs: Optional[Mapping[str, Any]]) -> Tuple[Optional[bool], Optional[str]]:
    """(blind, problem). blind = R's post-training goal-swap action TV < GOAL_BLIND_TV (strict); the flag the gate
    reported must agree. A missing, non-finite or inconsistent record is a problem (the safeguard cannot be applied)."""
    if not isinstance(gs, Mapping):
        return None, "post-training goal sensitivity missing"
    tv, flag = gs.get("R_goal_swap_tv"), gs.get("goal_blind_flag")
    if isinstance(tv, bool) or not isinstance(tv, (int, float)) or not math.isfinite(float(tv)) or float(tv) < 0:
        return None, f"R_goal_swap_tv {tv!r} is not a finite non-negative number"
    if not isinstance(flag, bool):
        return None, f"goal_blind_flag {flag!r} is not a boolean"
    blind = float(tv) < GOAL_BLIND_TV
    if blind != flag:
        return None, f"reported goal_blind_flag {flag} disagrees with R_goal_swap_tv {tv} < {GOAL_BLIND_TV}"
    return blind, None


def seed_comparison(seed: Any, r_eval: Sequence[Mapping[str, Any]], u_eval: Sequence[Mapping[str, Any]],
                    rare_goals: Sequence[str], mid_goals: Sequence[str], data_counts: Mapping[str, int],
                    goal_sensitivity: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """r_eval / u_eval rows: {"stratum", "cell", "success"} (plan order); data_counts: rare goal -> number of R's own
    phase-B episodes that validly reached it; goal_sensitivity: {"R_goal_swap_tv", "U_goal_swap_tv",
    "goal_blind_flag"} from the gate's post-training measurement."""
    rr, ur = per_goal(r_eval, "rare"), per_goal(u_eval, "rare")
    rm, um = per_goal(r_eval, "mid"), per_goal(u_eval, "mid")
    d_rare = [rr.get(g, 0) - ur.get(g, 0) for g in rare_goals]
    t_rare = sum(d_rare)
    p = sign_flip_p(d_rare)
    distinct = sum(1 for g in rare_goals if rr.get(g, 0) > 0)
    mid_success = sum(rm.get(g, 0) for g in mid_goals)
    t_mid = sum(rm.get(g, 0) - um.get(g, 0) for g in mid_goals)
    d_goals = sum(1 for g in rare_goals if int(data_counts.get(g, 0)) >= DATA_EPISODES_MIN)
    blind, g_problem = goal_blind_of(goal_sensitivity)
    functional = mid_success >= MID_SUCCESS_MIN and t_mid >= MID_T_MIN
    rare_criteria = t_rare >= RARE_T_MIN and distinct >= RARE_DISTINCT_MIN and p <= P_MAX
    rare_pass = rare_criteria and blind is False
    reject = functional and d_goals >= DATA_GOALS_MIN and t_rare <= REJECT_T_MAX
    counts = (f"R {sum(rr.values())} vs U {sum(ur.values())} rare returns on {distinct} distinct goals, T = {t_rare}, "
              f"p = {p:.4f}; mid R {mid_success} / U {sum(um.values())}")
    blocking: List[str] = []
    if not rare_pass and not reject:
        if rare_criteria and blind:
            blocking.append(f"goal-blind R (post-training goal-swap action TV {(goal_sensitivity or {}).get('R_goal_swap_tv')}"
                            f" < {GOAL_BLIND_TV}): not credited as learned return ({counts})")
        if not functional:
            blocking.append("learner not functional on the mid goals")
        if d_goals < DATA_GOALS_MIN:
            blocking.append(f"data: {d_goals} rare goals with >= {DATA_EPISODES_MIN} own phase-B demonstrations")
        if REJECT_T_MAX < t_rare < RARE_T_MIN:
            blocking.append(f"T = {t_rare} in the gap")
        if t_rare >= RARE_T_MIN and (p > P_MAX or distinct < RARE_DISTINCT_MIN):
            blocking.append(f"T = {t_rare} but p = {p:.4f} / distinct goals {distinct}")
    gs = goal_sensitivity if isinstance(goal_sensitivity, Mapping) else {}
    return {"seed": seed, "d_rare": dict(zip(rare_goals, d_rare)), "T_rare": t_rare, "p_sign_flip": round(p, 6),
            "R_rare_successes": sum(rr.values()), "U_rare_successes": sum(ur.values()),
            "R_distinct_rare_goals": distinct, "R_mid_successes": mid_success, "T_mid": t_mid,
            "U_mid_successes": sum(um.values()), "data_goals": d_goals, "functional": functional,
            "R_goal_swap_tv": gs.get("R_goal_swap_tv"), "U_goal_swap_tv": gs.get("U_goal_swap_tv"),
            "goal_blind": blind, "goal_blind_tv": GOAL_BLIND_TV, "goal_sensitivity_problem": g_problem,
            "rare_criteria_met": rare_criteria, "rare_pass": rare_pass, "reject": reject, "blocking": blocking}


def decide(inputs: Mapping[str, Any]) -> Dict[str, Any]:
    """inputs = {"integrity": {"ok", "problems"}, "complete": bool, "seeds": {s: seed_comparison args}}."""
    rep: Dict[str, Any] = {"rule": RULE_ID, "rule_sha256": rule_digest(), "exploratory": True}
    integ = inputs.get("integrity") or {}
    if not integ.get("ok", False):
        rep.update(outcome="invalid", reasons=list(integ.get("problems") or ["integrity"]))
        return rep
    if not inputs.get("complete", False):
        rep.update(outcome="incomplete", reasons=list(inputs.get("incomplete_reasons") or []))
        return rep
    seeds = inputs.get("seeds") or {}
    per = {str(s): seed_comparison(s, **{**a, "goal_sensitivity": a.get("goal_sensitivity")})
           for s, a in sorted(seeds.items())}
    rep["per_seed"] = per
    g_problems = [f"seed {s}: {r['goal_sensitivity_problem']}" for s, r in per.items() if r["goal_sensitivity_problem"]]
    if g_problems:
        rep.update(outcome="invalid", reasons=g_problems)
        return rep
    passes = [s for s, r in per.items() if r["rare_pass"]]
    rejects = [s for s, r in per.items() if r["reject"]]
    blind_blocked = [s for s, r in per.items() if r["rare_criteria_met"] and r["goal_blind"]]
    rep["counts"] = {"seeds": len(per), "rare_pass": passes, "reject": rejects,
                     "goal_blind": [s for s, r in per.items() if r["goal_blind"]], "goal_blind_blocked_pass": blind_blocked}
    if len(passes) >= SEEDS_REQUIRED:
        rep.update(outcome="pass_return_learned", reasons=[f"rare pass in seeds {passes}"])
    elif len(rejects) >= SEEDS_REQUIRED:
        rep.update(outcome="fail_return_not_learned", reasons=[f"functional, data present, T <= {REJECT_T_MAX} in {rejects}"])
    else:
        rep.update(outcome="inconclusive", reasons={s: r["blocking"] for s, r in per.items()})
    return rep


# -- self-test -----------------------------------------------------------------------------------------------------------


def _rows(stratum: str, goals: Sequence[str], wins: Sequence[int]) -> List[Dict[str, Any]]:
    out = []
    for g, w in zip(goals, wins):
        for rep in range(2):
            out.append({"stratum": stratum, "cell": g, "success": rep < w})
    return out


SIGHTED = {"R_goal_swap_tv": 0.13, "U_goal_swap_tv": 0.0004, "goal_blind_flag": False}
BLIND = {"R_goal_swap_tv": 0.0031, "U_goal_swap_tv": 0.0004, "goal_blind_flag": True}


def self_test() -> int:
    rare = [f"r{k}" for k in range(10)]
    mid = [f"m{k}" for k in range(5)]
    fails: List[str] = []

    def expect(cond: bool, what: str) -> None:
        if not cond:
            fails.append(what)

    # the sign-flip p against brute force and known values
    expect(abs(sign_flip_p([1] * 5 + [0] * 5) - 1 / 32) < 1e-12, "5 positive goals -> 1/32")
    expect(abs(sign_flip_p([2] * 10) - 1 / 1024) < 1e-12, "10 positive goals -> 1/1024")
    expect(sign_flip_p([0] * 10) == 1.0, "all zero -> 1")
    expect(abs(sign_flip_p([2, 2, 2, 0, 0, 0, 0, 0, 0, 0]) - 1 / 8) < 1e-12, "3 goals -> 1/8")
    expect(abs(sign_flip_p([2, 1, 1, 1, 1, -1, 0, 0, 0, 0]) - 6 / 64) < 1e-12, "mixed magnitudes (all + or one 1 flipped)")
    data_ok = {g: 3 for g in rare}
    mid_good_r = _rows("mid", mid, [2, 2, 1, 1, 1])      # 7 of 10
    mid_u = _rows("mid", mid, [1, 0, 0, 0, 0])
    # a clear pass: R wins on 6 rare goals, U none
    r = _rows("rare", rare, [2, 1, 1, 1, 1, 1, 0, 0, 0, 0]) + mid_good_r
    u = _rows("rare", rare, [0] * 10) + mid_u
    c = seed_comparison(0, r, u, rare, mid, data_ok, SIGHTED)
    expect(c["rare_pass"] and c["T_rare"] == 7 and c["p_sign_flip"] <= 0.05, f"pass case {c}")
    # repeated goals: 8 successes on only 2 goals -> fails the distinct / p requirement
    r2 = _rows("rare", rare, [2, 2] + [0] * 8) + mid_good_r
    c2 = seed_comparison(0, r2, u, rare, mid, data_ok, SIGHTED)
    expect(not c2["rare_pass"] and not c2["reject"], f"two-goal case {c2}")
    # rejection: functional, data present, T <= 1
    r3 = _rows("rare", rare, [1] + [0] * 9) + mid_good_r
    c3 = seed_comparison(0, r3, u, rare, mid, data_ok, SIGHTED)
    expect(c3["reject"], f"reject case {c3}")
    # not functional -> inconclusive, never a rejection
    r4 = _rows("rare", rare, [0] * 10) + _rows("mid", mid, [1, 1, 1, 0, 0])
    c4 = seed_comparison(0, r4, u, rare, mid, data_ok, SIGHTED)
    expect(not c4["reject"] and c4["blocking"], f"non-functional case {c4}")
    # data absent -> inconclusive
    c5 = seed_comparison(0, r3, u, rare, mid, {g: 1 for g in rare}, SIGHTED)
    expect(not c5["reject"], f"data-absent case {c5}")
    # U also succeeding cancels
    u6 = _rows("rare", rare, [2, 1, 1, 1, 1, 1, 0, 0, 0, 0]) + mid_u
    c6 = seed_comparison(0, r, u6, rare, mid, data_ok, SIGHTED)
    expect(not c6["rare_pass"] and c6["T_rare"] == 0, f"matched-U case {c6}")
    # goal-blind safeguard: the same would-pass counts are never a pass, the counts are reported
    cb = seed_comparison(0, r, u, rare, mid, data_ok, BLIND)
    expect(cb["rare_criteria_met"] and not cb["rare_pass"] and cb["goal_blind"] and not cb["reject"],
           f"goal-blind would-pass case {cb}")
    expect(cb["R_rare_successes"] == 7 and cb["U_rare_successes"] == 0 and cb["R_distinct_rare_goals"] == 6
           and any("goal-blind" in b and "R 7 vs U 0" in b for b in cb["blocking"]), f"goal-blind counts {cb['blocking']}")
    # the threshold is strict and fixed: TV exactly 0.01 is not blind
    edge = seed_comparison(0, r, u, rare, mid, data_ok, {"R_goal_swap_tv": 0.01, "U_goal_swap_tv": 0.0004,
                                                         "goal_blind_flag": False})
    expect(edge["rare_pass"] and edge["goal_blind"] is False, "TV = 0.01 is not goal-blind")
    # decide
    ok = {"integrity": {"ok": True}, "complete": True}
    args = lambda rr, uu, dd=data_ok, gs=SIGHTED: {"r_eval": rr, "u_eval": uu, "rare_goals": rare, "mid_goals": mid,
                                                   "data_counts": dd, "goal_sensitivity": gs}
    d1 = decide(dict(ok, seeds={0: args(r, u), 1: args(r, u), 2: args(r3, u)}))
    expect(d1["outcome"] == "pass_return_learned", f"decide pass {d1['outcome']}")
    d2 = decide(dict(ok, seeds={0: args(r3, u), 1: args(r3, u), 2: args(r, u)}))
    expect(d2["outcome"] == "fail_return_not_learned", f"decide fail {d2['outcome']}")
    d3 = decide(dict(ok, seeds={0: args(r4, u), 1: args(r, u), 2: args(r3, u)}))
    expect(d3["outcome"] == "inconclusive", f"decide inconclusive {d3['outcome']}")
    d4 = decide({"integrity": {"ok": False, "problems": ["x"]}, "complete": True, "seeds": {}})
    expect(d4["outcome"] == "invalid", "decide invalid")
    d5 = decide({"integrity": {"ok": True}, "complete": False, "seeds": {}})
    expect(d5["outcome"] == "incomplete", "decide incomplete")
    # goal-blind in decide: three would-pass seeds, all goal-blind -> inconclusive, never a pass
    db = decide(dict(ok, seeds={s: args(r, u, gs=BLIND) for s in (0, 1, 2)}))
    expect(db["outcome"] == "inconclusive" and db["counts"]["goal_blind_blocked_pass"] == ["0", "1", "2"]
           and all(any("goal-blind" in b for b in db["reasons"][s]) for s in ("0", "1", "2")), f"decide all blind {db}")
    # one sighted pass + two blind would-pass seeds -> inconclusive (a blind seed cannot supply the second pass)
    dm = decide(dict(ok, seeds={0: args(r, u), 1: args(r, u, gs=BLIND), 2: args(r, u, gs=BLIND)}))
    expect(dm["outcome"] == "inconclusive" and dm["counts"]["rare_pass"] == ["0"], f"decide 1 sighted + 2 blind {dm}")
    # two sighted passes + one blind seed -> pass (the blind seed is excluded, not fatal)
    dp = decide(dict(ok, seeds={0: args(r, u), 1: args(r, u), 2: args(r, u, gs=BLIND)}))
    expect(dp["outcome"] == "pass_return_learned" and dp["counts"]["rare_pass"] == ["0", "1"], f"decide 2 sighted {dp}")
    # the safeguard cannot be skipped: missing / inconsistent sensitivity -> invalid
    dx = decide(dict(ok, seeds={0: args(r, u), 1: args(r, u), 2: args(r, u, gs=None)}))
    expect(dx["outcome"] == "invalid", f"missing sensitivity {dx['outcome']}")
    dy = decide(dict(ok, seeds={0: args(r, u), 1: args(r, u), 2: args(r, u, gs=dict(BLIND, goal_blind_flag=False))}))
    expect(dy["outcome"] == "invalid", f"inconsistent flag {dy['outcome']}")
    expect(d1["rule_sha256"] == rule_digest() and rule_description()["goal_blind_tv"] == 0.01, "rule identity")
    for f in fails:
        print("FAIL", f)
    print("self-test PASS" if not fails else f"self-test FAIL ({len(fails)})")
    return 0 if not fails else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "self-test":
        sys.exit(self_test())
    print(json.dumps({"rule": RULE_ID, "rule_sha256": rule_digest()}, indent=1))
