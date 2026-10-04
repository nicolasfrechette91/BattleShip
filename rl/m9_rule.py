#!/usr/bin/env python3
"""M9-g1: the registered decision rule `m9_g1_rule_v1` and its self-test (pure, standard library only).

    python rl/m9_rule.py self-test

The reliable reach R is the earliest landing state lambda such that, at lambda AND at every later landing state (larger tick), the final
policy's sticky clear count is at least 10 of 20, every counted clear is verified by exact replay, and the count exceeds the paired tape
control's by at least 5 of 20. R is none when the last landing (2,128) fails. Evaluation order, the first that holds is the outcome:

    INVALID       any integrity or compliance failure (the facts carry the reasons)
    INCOMPLETE    P1-P4 not passed; training stopped before its wall, tick or transition cap; any landing from 2,128 to 1,248 not fully
                  evaluated (20 policy and 20 tape episodes); an unverified clear that could change R
    PASS          R <= 1,694 (the wall-top landing or earlier); R <= 1,473 adds "crossing learned"
    INCONCLUSIVE  R in {1,966, 2,128}
    NULL          R = none

Diagnostics that never decide: R for the unperturbed evaluation (the same count rule, no tape margin), R_fine on the descriptive grid, the
route mastered (2,326 - R), the best checkpoint by reach. `claim_status` defines the final claim (50 of 100 unperturbed, 50 of 100 sticky,
tape margin 25); g1 does not test it.
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import m9_contract as C

RULE_ID = C.RULE_ID
ROUTE_END = 2326                       # T_clear's length: "route mastered = 2,326 - R ticks"
OUTCOMES = ("INVALID", "INCOMPLETE", "PASS", "INCONCLUSIVE", "NULL")


def rule_description() -> Dict[str, Any]:
    return {"rule": RULE_ID, "order": list(OUTCOMES), "landings": list(C.LANDINGS),
            "reach": "earliest landing with >= %d of %d verified sticky clears and >= %d more than the paired tape, at it and at every later landing"
                     % (C.GATE_MIN_CLEARS, C.EVAL_EPISODES, C.TAPE_MARGIN),
            "pass_depth": C.PASS_DEPTH, "crossing_depth": C.CROSSING_DEPTH, "inconclusive_depths": list(C.INCONCLUSIVE_DEPTHS),
            "incomplete": ["P1-P4 not all passed", "training ended before its wall, tick or transition cap", "a landing from 2,128 to 1,248 not fully evaluated",
                           "an unverified clear that could change R"],
            "diagnostics_never_deciding": ["R unperturbed", "R_fine", "route mastered", "best checkpoint by reach", "tick-0 behaviour", "handover diagnostic"],
            "claim": dict(C.CLAIM)}


def rule_digest() -> str:
    return hashlib.sha256(json.dumps(rule_description(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def landing_ok(row: Mapping[str, Any], *, min_clears: int, margin: Optional[int], n: int, count: str) -> bool:
    """One landing state. `count` = 'verified' (only verified policy clears count; the tape's claimed clears all count, the strict side),
    'claimed' (every claimed policy clear counts; only verified tape clears count: the most favourable reading)."""
    if int(row.get("n", 0)) < n:
        return False
    if count == "verified":
        policy = int(row["verified"])
        tape = int(row.get("tape_clears", 0))
    else:
        policy = int(row["clears"])
        tape = int(row.get("tape_verified", row.get("tape_clears", 0)))
    if policy < min_clears:
        return False
    if margin is not None:
        if int(row.get("tape_n", 0)) < n:
            return False
        if policy - tape < margin:
            return False
    return True


def depth(rows: Mapping[int, Mapping[str, Any]], *, min_clears: int = C.GATE_MIN_CLEARS, margin: Optional[int] = C.TAPE_MARGIN,
          n: int = C.EVAL_EPISODES, count: str = "verified") -> Optional[int]:
    """The earliest landing (smallest tick) such that it and every landing with a larger tick passes. None when the largest landing fails."""
    r: Optional[int] = None
    for lam in sorted(rows, reverse=True):
        if landing_ok(rows[lam], min_clears=min_clears, margin=margin, n=n, count=count):
            r = lam
        else:
            break
    return r


def fully_evaluated(rows: Mapping[int, Mapping[str, Any]], landings: Sequence[int] = C.LANDINGS) -> List[int]:
    """Landings from the registered list that are missing or short of 20 policy or 20 tape episodes."""
    out = []
    for lam in landings:
        row = rows.get(lam)
        if row is None or int(row.get("n", 0)) < C.EVAL_EPISODES or int(row.get("tape_n", 0)) < C.EVAL_EPISODES:
            out.append(lam)
    return out


def apply(facts: Mapping[str, Any]) -> Dict[str, Any]:
    """`facts`: invalid (list of reasons), phases ({p1..p4: bool}), training ({valid_end: bool, stop: str}), reach ({landing: {n, clears,
    verified, tape_n, tape_clears, tape_verified}}), optional unperturbed (same shape without tape), fine ({tick: {n, clears}})."""
    rows = {int(k): v for k, v in dict(facts.get("reach") or {}).items()}
    reasons: List[str] = []
    invalid = list(facts.get("invalid") or [])
    out: Dict[str, Any] = {"rule": RULE_ID, "rule_sha256": rule_digest()}
    r_counted = depth(rows, count="verified") if rows else None
    r_claimed = depth(rows, count="claimed") if rows else None
    out.update({"R": r_counted, "R_if_every_claimed_clear_were_verified": r_claimed})
    if invalid:
        out.update({"outcome": "INVALID", "reasons": invalid, "crossing_learned": False})
        return _diagnostics(out, facts, rows)
    phases = dict(facts.get("phases") or {})
    for p in ("p1", "p2", "p3", "p4"):
        if not phases.get(p):
            reasons.append(f"{p.upper()} not passed")
    tr = dict(facts.get("training") or {})
    if not tr.get("valid_end"):
        reasons.append(f"training stopped before a cap ({tr.get('stop')})")
    short = fully_evaluated(rows, tuple(facts.get("landings") or C.LANDINGS))
    if short:
        reasons.append(f"landing states not fully evaluated: {short}")
    if r_counted != r_claimed:
        reasons.append(f"an unverified clear could change R ({r_counted} counted, {r_claimed} if every claimed clear held)")
    if reasons:
        out.update({"outcome": "INCOMPLETE", "reasons": reasons, "crossing_learned": False})
        return _diagnostics(out, facts, rows)
    if r_counted is None:
        out.update({"outcome": "NULL", "reasons": ["no reliable clear even from the last landing state"], "crossing_learned": False})
    elif r_counted <= C.PASS_DEPTH:
        out.update({"outcome": "PASS", "reasons": [f"R = {r_counted} <= {C.PASS_DEPTH}"], "crossing_learned": r_counted <= C.CROSSING_DEPTH})
    else:
        out.update({"outcome": "INCONCLUSIVE", "reasons": [f"R = {r_counted} in {list(C.INCONCLUSIVE_DEPTHS)}"], "crossing_learned": False})
    return _diagnostics(out, facts, rows)


def _diagnostics(out: Dict[str, Any], facts: Mapping[str, Any], rows: Mapping[int, Mapping[str, Any]]) -> Dict[str, Any]:
    unp = {int(k): v for k, v in dict(facts.get("unperturbed") or {}).items()}
    fine = {int(k): v for k, v in dict(facts.get("fine") or {}).items()}
    out["route_mastered_ticks"] = None if out.get("R") is None else ROUTE_END - int(out["R"])
    out["diagnostics"] = {
        "R_unperturbed": depth(unp, margin=None, count="claimed") if unp else None,
        "R_fine": depth(fine, min_clears=C.FINE_GRID_MIN_CLEARS, margin=None, n=C.FINE_GRID_EPISODES, count="claimed") if fine else None,
        "note": "diagnostics only: neither changes the outcome"}
    return out


def claim_status(unperturbed_clears: int, sticky_clears: int, tape_clears: int, episodes: int = 100) -> Dict[str, Any]:
    """The final claim (defined, not tested in g1): at least 50 of 100 unperturbed, 50 of 100 sticky, and 25 more than the tape."""
    a = unperturbed_clears >= C.CLAIM["unperturbed_clears_min_of_100"] and episodes == C.CLAIM["episodes"]
    b = sticky_clears >= C.CLAIM["sticky_clears_min_of_100"] and sticky_clears - tape_clears >= C.CLAIM["tape_margin_min"] and episodes == C.CLAIM["episodes"]
    return {"part_a": a, "part_b": b, "claim": a and b}


# -- self-test ----------------------------------------------------------------------------------------------------------------------


def _row(clears: int, verified: Optional[int] = None, tape: int = 0, tape_verified: Optional[int] = None, n: int = 20, tape_n: int = 20) -> Dict[str, Any]:
    return {"n": n, "clears": clears, "verified": clears if verified is None else verified, "tape_n": tape_n, "tape_clears": tape,
            "tape_verified": tape if tape_verified is None else tape_verified}


def _facts(per: Mapping[int, Dict[str, Any]], **over: Any) -> Dict[str, Any]:
    f: Dict[str, Any] = {"invalid": [], "phases": {"p1": True, "p2": True, "p3": True, "p4": True}, "training": {"valid_end": True, "stop": "wall_cap"},
                         "reach": dict(per)}
    f.update(over)
    return f


def self_test() -> List[str]:
    problems: List[str] = []

    def expect(label: str, got: Any, want: Any) -> None:
        if got != want:
            problems.append(f"{label}: got {got!r}, want {want!r}")

    L = list(C.LANDINGS)
    good = {lam: _row(12, tape=1) for lam in L}
    expect("all landings pass -> PASS and crossing learned", (apply(_facts(good))["outcome"], apply(_facts(good))["crossing_learned"], apply(_facts(good))["R"]), ("PASS", True, 1248))
    # boundary: 9 of 20 fails, 10 passes (margin 0 tape)
    for c, want in ((9, None), (10, 1248)):
        rows = {lam: _row(c) for lam in L}
        expect(f"{c} of 20 everywhere", depth(rows), want)
    # boundary: the margin is 5, not 4
    for tape, ok in ((5, True), (6, True), (7, False)):
        expect(f"margin 11 - {tape}", landing_ok(_row(11, tape=tape), min_clears=10, margin=5, n=20, count="verified"), ok)
    expect("margin exactly 5", landing_ok(_row(10, tape=5), min_clears=10, margin=5, n=20, count="verified"), True)
    expect("margin 4 fails", landing_ok(_row(10, tape=6), min_clears=10, margin=5, n=20, count="verified"), False)
    # the chain: a failing landing stops R even when later (smaller) landings pass
    rows = {2128: _row(15), 1966: _row(15), 1694: _row(9), 1473: _row(20), 1369: _row(20), 1248: _row(20)}
    expect("R stops at the first failing landing", depth(rows), 1966)
    out = apply(_facts(rows))
    expect("R = 1966 is INCONCLUSIVE", (out["outcome"], out["crossing_learned"]), ("INCONCLUSIVE", False))
    rows = {2128: _row(10), 1966: _row(0), 1694: _row(20), 1473: _row(20), 1369: _row(20), 1248: _row(20)}
    expect("R = 2128 is INCONCLUSIVE", apply(_facts(rows))["outcome"], "INCONCLUSIVE")
    rows = {lam: _row(0) for lam in L}
    out = apply(_facts(rows))
    expect("no reach -> NULL", (out["outcome"], out["R"], out["route_mastered_ticks"]), ("NULL", None, None))
    rows = {2128: _row(20), 1966: _row(20), 1694: _row(10), 1473: _row(9), 1369: _row(20), 1248: _row(20)}
    out = apply(_facts(rows))
    expect("R = 1694 -> PASS, not crossing learned", (out["outcome"], out["crossing_learned"], out["route_mastered_ticks"]), ("PASS", False, 2326 - 1694))
    rows = {2128: _row(20), 1966: _row(20), 1694: _row(20), 1473: _row(20), 1369: _row(3), 1248: _row(20)}
    out = apply(_facts(rows))
    expect("R = 1473 -> PASS and crossing learned", (out["outcome"], out["crossing_learned"], out["R"]), ("PASS", True, 1473))
    # deeper landings than the registered six extend R
    rows = {**{lam: _row(20) for lam in L}, 900: _row(10), 600: _row(2)}
    expect("a deeper landing extends R", depth(rows), 900)
    # precedence: INVALID over INCOMPLETE over the performance outcome
    expect("INVALID outranks all", apply(_facts(good, invalid=["x"], phases={"p1": False}))["outcome"], "INVALID")
    expect("INCOMPLETE outranks PASS (P3 not passed)", apply(_facts(good, phases={"p1": True, "p2": True, "p3": False, "p4": True}))["outcome"], "INCOMPLETE")
    expect("INCOMPLETE: training stopped early", apply(_facts(good, training={"valid_end": False, "stop": "memory"}))["outcome"], "INCOMPLETE")
    expect("INCOMPLETE: a landing short of 20 episodes", apply(_facts({**good, 1248: _row(12, n=19)}))["outcome"], "INCOMPLETE")
    expect("INCOMPLETE: a landing short of 20 tape episodes", apply(_facts({**good, 1473: _row(12, tape_n=19)}))["outcome"], "INCOMPLETE")
    expect("INCOMPLETE: a landing missing", apply(_facts({k: v for k, v in good.items() if k != 1369}))["outcome"], "INCOMPLETE")
    # unverified clears: only verified clears count, and an unverified one that could change R makes the gate INCOMPLETE
    unv = {**good, 1694: _row(10, verified=9)}
    out = apply(_facts(unv))
    expect("an unverified clear that could change R is INCOMPLETE", (out["outcome"], out["R"], out["R_if_every_claimed_clear_were_verified"]), ("INCOMPLETE", 1966, 1248))
    unv2 = {**good, 1694: _row(15, verified=12)}
    expect("an unverified clear that cannot change R does not stop the rule", apply(_facts(unv2))["outcome"], "PASS")
    # a claimed tape clear that was not verified counts against the margin on the strict side
    tp = {**good, 1694: _row(15, tape=11, tape_verified=9)}
    out = apply(_facts(tp))
    expect("tape claimed clears count on the strict side", out["outcome"], "INCOMPLETE")
    # claim
    expect("claim thresholds", claim_status(50, 50, 25)["claim"], True)
    expect("claim: 49 unperturbed", claim_status(49, 50, 0)["claim"], False)
    expect("claim: margin 24", claim_status(50, 50, 26)["claim"], False)
    expect("claim: 49 sticky", claim_status(50, 49, 0)["claim"], False)
    # diagnostics never decide
    base = apply(_facts(good))
    withd = apply(_facts(good, unperturbed={lam: _row(0, tape=0) for lam in L}, fine={2300: _row(0, n=10)}))
    expect("diagnostics do not change the outcome", (base["outcome"], base["R"]), (withd["outcome"], withd["R"]))
    expect("R_unperturbed uses no tape margin", withd["diagnostics"]["R_unperturbed"], None)
    unp_ok = apply(_facts(good, unperturbed={lam: _row(10, tape=20) for lam in L}))
    expect("R_unperturbed ignores the tape", unp_ok["diagnostics"]["R_unperturbed"], 1248)
    fine = {2300 - 25 * i: _row(5, n=10) for i in range(10)}
    expect("R_fine needs 5 of 10", apply(_facts(good, fine=fine))["diagnostics"]["R_fine"], 2300 - 25 * 9)
    expect("rule digest is stable", rule_digest() == rule_digest() and len(rule_digest()) == 64, True)
    return problems


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "self-test":
        problems = self_test()
        for p in problems:
            print("FAIL:", p)
        print(f"m9_rule self-test: {'PASS' if not problems else 'FAIL'} ({len(problems)} problem(s)), digest {rule_digest()}")
        return 0 if not problems else 1
    print(json.dumps(rule_description(), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
