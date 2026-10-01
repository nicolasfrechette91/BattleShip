"""M7u2 gate m7u2 (proposed): rule `m7u2_tick0_rule_v1`, applied once to native trial outcomes (design:
docs/rl_model_planning_m7u2_tick0_proposal_2026-09-30.md, §3.6). No accuracy, calibration or attribution quantity
enters the rule; those are reported beside it to read a NULL.

Scope: a proposed test of rare airborne-point reach initiated from the normal tick-0 reset (frozen m7u1 model, one
seed). A PASS is never reported as a landing, a crossing, a target result or a clear.

    python rl/m7u2_rule.py self-test
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

RULE_ID = "m7u2_tick0_rule_v1"
N = 24
PASS_MIN_P = 6
PASS_MIN_BR = 6
PASS_MIN_BS = 5
NULL_MAX_BR = 1
NULL_MAX_BS = 0
UNDIRECTED_MIN_BR = 2
FORBIDDEN_WORDS = ("landing", "crossing", "cross the wall", "wall top", "wall-top", "clear", "target")
SCOPE = "rare airborne-point reach initiated from the normal tick-0 reset (frozen m7u1 model, one seed)"
NOT_ESTABLISHED = ("a landing", "the wall top", "a crossing", "targets", "a clear", "speed", "goals beyond 128 ticks",
                   "sequences of goals", "goals not drawn from behaviour", "replication across seeds or models",
                   "superiority over PPO")


def paired(p: Sequence[bool], q: Sequence[bool]) -> Dict[str, int]:
    b = sum(1 for a, c in zip(p, q) if a and not c)
    c = sum(1 for a, c_ in zip(p, q) if c_ and not a)
    return {"b": b, "c": c, "diff": b - c}


def apply(outcomes: Mapping[str, Sequence[bool]], *, integrity_ok: bool, incomplete: Optional[str] = None) -> Dict[str, Any]:
    """outcomes: arm -> 24 booleans in registered goal order (success = the first valid reach of g within 128 ticks
    of the normal tick-0 reset)."""
    if incomplete:
        return {"rule": RULE_ID, "outcome": "INCOMPLETE", "reason": incomplete,
                "note": "a cap or availability stop: not a performance result; no retry, extension or relaxation"}
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
            "blockers": blockers, "scope": SCOPE, "not_established": list(NOT_ESTABLISHED)}


def null_reading(decision: Mapping[str, Any], *, model_share: Optional[float],
                 witness_share: Optional[float]) -> Optional[str]:
    """The reported reading of a NULL (never an outcome): M = share of P failures attributed MODEL, W = share of goals
    whose recorded witness (from tick 0) the ensemble accepts."""
    if decision.get("outcome") != "NULL":
        return None
    vr, vs = decision["vs_RC"]["diff"], decision["vs_S"]["diff"]
    if vs <= NULL_MAX_BS and vr >= UNDIRECTED_MIN_BR:
        return "undirected: the model changes behaviour, but not toward the command"
    if model_share is None or witness_share is None:
        return "unread: attribution unavailable"
    if model_share >= 0.5:
        return "rollout error from rest: predicted reaching plans were not followed natively"
    if witness_share >= 0.5:
        return "search: the model accepts feasible continuations the planner did not find from rest"
    return "false negatives: the model rejects feasible continuations"


def rule_digest() -> str:
    d = {"rule": RULE_ID, "n": N, "pass": [PASS_MIN_P, PASS_MIN_BR, PASS_MIN_BS], "null": [NULL_MAX_BR, NULL_MAX_BS],
         "undirected_min_br": UNDIRECTED_MIN_BR}
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode("utf-8")).hexdigest()


def scope_problems(text: str) -> List[str]:
    """Words a decision record must never use about an airborne-point reach."""
    low = text.lower()
    return [w for w in FORBIDDEN_WORDS if w in low]


def self_test() -> List[str]:
    probs: List[str] = []

    def arms(np_: int, nrc: int, ns: int, overlap_rc: int = 0, overlap_s: int = 0) -> Dict[str, List[bool]]:
        p = [i < np_ for i in range(N)]
        rc = [i < overlap_rc or (N - (nrc - overlap_rc)) <= i for i in range(N)]
        s = [i < overlap_s or (N - (ns - overlap_s)) <= i for i in range(N)]
        return {"P": p, "RC": rc, "S": s}

    cases = [((6, 0, 1), "PASS"), ((6, 0, 2), "INCONCLUSIVE"), ((5, 0, 0), "INCONCLUSIVE"), ((6, 1, 0), "INCONCLUSIVE"),
             ((2, 1, 0), "NULL"), ((8, 8, 1), "NULL"), ((8, 1, 8), "NULL"), ((10, 2, 3), "PASS"), ((9, 3, 4), "PASS"),
             ((9, 4, 4), "INCONCLUSIVE"), ((7, 0, 0, 0, 0), "PASS")]
    for c, want in cases:
        got = apply(arms(*c), integrity_ok=True)["outcome"]
        if got != want:
            probs.append(f"{c} -> {got}, want {want}")
    # boundaries: b_R - c_R = 6 passes, 5 does not; b_S - c_S = 5 passes, 4 does not; n_P = 6 passes, 5 does not
    if apply(arms(6, 0, 1), integrity_ok=True)["outcome"] != "PASS":
        probs.append("boundary n_P 6 / diff 6 / diff 5 must PASS")
    if apply(arms(6, 0, 2), integrity_ok=True)["outcome"] == "PASS":
        probs.append("b_S - c_S 4 must not PASS")
    if apply(arms(24, 0, 0), integrity_ok=False)["outcome"] != "INVALID":
        probs.append("integrity failure must be INVALID")
    if apply(arms(24, 0, 0), integrity_ok=True, incomplete="goal availability")["outcome"] != "INCOMPLETE":
        probs.append("an availability or cap stop must be INCOMPLETE")
    if apply({"P": [True] * 23, "RC": [False] * 24, "S": [False] * 24}, integrity_ok=True)["outcome"] != "INVALID":
        probs.append("a partial outcome list must be INVALID")
    for np_ in range(N + 1):
        for nrc in range(0, N - np_ + 1):
            for ns in range(0, N - np_ + 1):
                d = apply({"P": [i < np_ for i in range(N)], "RC": [i >= N - nrc for i in range(N)],
                           "S": [i >= N - ns for i in range(N)]}, integrity_ok=True)
                if d["outcome"] not in ("PASS", "NULL", "INCONCLUSIVE"):
                    probs.append(f"unexpected outcome {d['outcome']}")
    if scope_problems(f"m7u2 ({SCOPE}): PASS; P 7, RC 0, S 1 of 24") != []:
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
