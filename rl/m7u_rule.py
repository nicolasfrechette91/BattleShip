"""M7u gate m7u1: rule `m7u1_control_rule_v2`, applied once to native trial outcomes (design:
docs/rl_model_planning_m7u_proposal_2026-09-29.md, revision 2, §6.5). No accuracy, calibration or attribution quantity
enters the rule; those are reported beside it to read a NULL. Scope: local control after the agent's own supplied
prefix; a PASS is never reported as a landing, a crossing or a policy-controlled reach from tick 0.

    python rl/m7u_rule.py self-test
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

RULE_ID = "m7u1_control_rule_v2"
N = 40
PASS_MIN_P = 10
PASS_MIN_BR = 8
PASS_MIN_BS = 6
NULL_MAX_BR = 2
NULL_MAX_BS = 0
FORBIDDEN_WORDS = ("landing", "crossing", "cross the wall", "tick-0 reach", "from tick 0", "clear")


def paired(p: Sequence[bool], q: Sequence[bool]) -> Dict[str, int]:
    b = sum(1 for a, c in zip(p, q) if a and not c)
    c = sum(1 for a, c_ in zip(p, q) if c_ and not a)
    return {"b": b, "c": c, "diff": b - c}


def apply(outcomes: Mapping[str, Sequence[bool]], *, integrity_ok: bool, incomplete: Optional[str] = None) -> Dict[str, Any]:
    """outcomes: arm -> 40 booleans in registered goal order (success = first valid reach of g within the budget)."""
    if incomplete:
        return {"rule": RULE_ID, "outcome": "INCOMPLETE", "reason": incomplete,
                "note": "a cap or availability stop: not a performance result, no retry or extension"}
    if not integrity_ok:
        return {"rule": RULE_ID, "outcome": "INVALID", "reason": "integrity failure (see the integrity record)"}
    for arm in ("P", "RC", "S"):
        if len(outcomes.get(arm, ())) != N:
            return {"rule": RULE_ID, "outcome": "INVALID", "reason": f"arm {arm} has {len(outcomes.get(arm, ()))} outcomes"}
    p, rc, s = (list(map(bool, outcomes[a])) for a in ("P", "RC", "S"))
    n_p, n_rc, n_s = sum(p), sum(rc), sum(s)
    vr, vs = paired(p, rc), paired(p, s)
    passed = n_p >= PASS_MIN_P and vr["diff"] >= PASS_MIN_BR and vs["diff"] >= PASS_MIN_BS
    null = vr["diff"] <= NULL_MAX_BR or vs["diff"] <= NULL_MAX_BS
    if passed and null:
        raise AssertionError("PASS and NULL overlap")          # impossible by construction
    blockers: List[str] = []
    if not passed:
        if n_p < PASS_MIN_P:
            blockers.append(f"n_P {n_p} < {PASS_MIN_P}")
        if vr["diff"] < PASS_MIN_BR:
            blockers.append(f"b_R - c_R {vr['diff']} < {PASS_MIN_BR}")
        if vs["diff"] < PASS_MIN_BS:
            blockers.append(f"b_S - c_S {vs['diff']} < {PASS_MIN_BS}")
    outcome = "PASS" if passed else ("NULL" if null else "INCONCLUSIVE")
    return {"rule": RULE_ID, "outcome": outcome, "n": {"P": n_p, "RC": n_rc, "S": n_s}, "vs_RC": vr, "vs_S": vs,
            "blockers": blockers, "scope": "local control after the agent's own supplied prefix",
            "not_established": ["reach from a normal tick-0 start", "replication across seeds", "wall-top landing",
                                "wall crossing", "targets", "a clear", "speed"]}


def null_reading(decision: Mapping[str, Any], *, model_share: Optional[float], witness_share: Optional[float]) -> Optional[str]:
    """The reported reading of a NULL (never an outcome): M = share of P failures attributed MODEL, W = share of P
    failures whose witness continuation the ensemble accepts."""
    if decision.get("outcome") != "NULL":
        return None
    vr, vs = decision["vs_RC"]["diff"], decision["vs_S"]["diff"]
    if vs <= NULL_MAX_BS and vr >= 3:
        return "undirected: the learned model changes behaviour, but not toward the command"
    if model_share is None or witness_share is None:
        return "unread: attribution unavailable"
    if model_share >= 0.5:
        return "rollout error: predicted reaching plans were not followed natively"
    if witness_share >= 0.5:
        return "search: the model accepts known-feasible continuations the planner did not find or keep"
    return "false negatives: the model rejects known-feasible continuations"


def rule_digest() -> str:
    d = {"rule": RULE_ID, "n": N, "pass": [PASS_MIN_P, PASS_MIN_BR, PASS_MIN_BS], "null": [NULL_MAX_BR, NULL_MAX_BS]}
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode("utf-8")).hexdigest()


def scope_problems(text: str) -> List[str]:
    """Words a decision record must never use about a rising-point reach."""
    low = text.lower()
    return [w for w in FORBIDDEN_WORDS if w in low]


def self_test() -> List[str]:
    probs: List[str] = []

    def arms(np_: int, nrc: int, ns: int, overlap_rc: int = 0, overlap_s: int = 0) -> Dict[str, List[bool]]:
        p = [i < np_ for i in range(N)]
        rc = [i < overlap_rc or (N - (nrc - overlap_rc)) <= i for i in range(N)]
        s = [i < overlap_s or (N - (ns - overlap_s)) <= i for i in range(N)]
        return {"P": p, "RC": rc, "S": s}

    cases = [((10, 2, 4), "PASS"), ((10, 2, 5), "INCONCLUSIVE"), ((9, 0, 0), "INCONCLUSIVE"), ((4, 2, 1), "NULL"),
             ((12, 12, 3), "NULL"), ((12, 3, 12), "NULL"), ((15, 4, 8), "PASS"), ((11, 5, 3), "INCONCLUSIVE")]
    for (np_, nrc, ns), want in cases:
        got = apply(arms(np_, nrc, ns), integrity_ok=True)["outcome"]
        if got != want:
            probs.append(f"({np_}, {nrc}, {ns}) -> {got}, want {want}")
    if apply(arms(10, 0, 0), integrity_ok=False)["outcome"] != "INVALID":
        probs.append("integrity failure must be INVALID")
    if apply(arms(40, 0, 0), integrity_ok=True, incomplete="wall cap")["outcome"] != "INCOMPLETE":
        probs.append("a cap stop must be INCOMPLETE")
    # exhaustive disjointness over every count triple with disjoint success sets
    for np_ in range(N + 1):
        for nrc in range(0, N - np_ + 1, 3):
            for ns in range(0, N - np_ + 1, 3):
                d = apply({"P": [i < np_ for i in range(N)], "RC": [i >= N - nrc for i in range(N)],
                           "S": [i >= N - ns for i in range(N)]}, integrity_ok=True)
                if d["outcome"] not in ("PASS", "NULL", "INCONCLUSIVE"):
                    probs.append(f"unexpected outcome {d['outcome']}")
    if scope_problems("P reached rising points after its own prefix") != []:
        probs.append("scope check false positive")
    if scope_problems("a wall-top landing") != ["landing"]:
        probs.append("scope check misses 'landing'")
    return probs


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "self-test":
        p = self_test()
        print(json.dumps({"rule": RULE_ID, "digest": rule_digest(), "problems": p}))
        sys.exit(1 if p else 0)
    print(json.dumps({"rule": RULE_ID, "digest": rule_digest()}))
