#!/usr/bin/env python3
"""M9-g3: the registered rules `m9_g3_s1_rule_v1` and `m9_g3_line_rule_v1`, the measures D and R (g2's, read unchanged), and their self-tests
(pure, standard library only).

    python rl/m9_g3_rule.py self-test

`m9_g3_s1_rule_v1`, evaluated in this order (the first that holds is the outcome; the stop review 3.3, decision 5):

    INVALID       any integrity or compliance failure, "an attempt inside its spacing" (rebuilt from the records by verify-run) and "a pointer move without
                  a recorded passing attempt" included
    INCOMPLETE    P1, P2 or T0 (the reused tape verified and the drift check) not passed; training ended before a valid end (the 80-minute wall, the
                  native-tick cap or the transition cap; STALLED does not exist); the close audit incomplete at a landing D_1 or R_1 needs; B unpinned
                  at an audited landing whose verified count is at least 10; an unverified audit clear that could change D_1 or R_1
    PASS          R_1 <= 1,966
    INCONCLUSIVE  D_1 <= 2,128
    NULL          D_1 = none

`m9_g3_line_rule_v1` (checked at every session close, in order; decision 4, stop review 3.4). Every END is a progress or time condition; NO outcome
depends on an attempt count, and a NULL s1 does NOT end the line by itself:

    SUSPENDED         the session is INVALID; or two consecutive sessions are INCOMPLETE
    END_SUCCESS       D_k <= 1,473
    END_BUDGET_2128   k = 2 and D_2 = none
    END_BUDGET_1966   k = 4 and D_4 later than 1,966 (none, or 2,128)
    END_BUDGET_1694   k = 6 and D_6 later than 1,694
    END_NO_PROGRESS   k >= 4 and D_k not earlier than D_{k-2}
    END_CAP           k = 8 without END_SUCCESS
    CONTINUE          otherwise; session k + 1 is proposable with its own approval

k counts the sessions whose training reached at least 50 % of the wall cap (an INCOMPLETE session below that does not count); D_k is the depth of the
k-th counted session. A last session that does not count leaves the line where the previous counted session left it (CONTINUE, unless SUSPENDED).
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

import m9_g2_rule as R2
import m9_g3_contract as G

S1_OUTCOMES = ("INVALID", "INCOMPLETE", "PASS", "INCONCLUSIVE", "NULL")
LINE_OUTCOMES = ("SUSPENDED", "END_SUCCESS", "END_BUDGET_2128", "END_BUDGET_1966", "END_BUDGET_1694", "END_NO_PROGRESS", "END_CAP", "CONTINUE")
depth = R2.depth                                      # D (bars None) / R (bars given): unchanged
frontier_backed = R2.frontier_backed


def s1_rule_description() -> Dict[str, Any]:
    return {"rule": G.S1_RULE_ID, "order": list(S1_OUTCOMES), "landings": list(G.LANDINGS), "D": f"earliest landing with >= {G.D_MIN_CLEARS} of {G.AUDIT_EPISODES} verified sticky clears at it and every later audited landing",
            "R": "the same with >= B(landing) = max(10, ceil(20 p_hat) + 5), B from the reused pinned tape", "pass": f"R_1 <= {G.PASS_REACH}", "inconclusive": f"D_1 <= {G.INCONCLUSIVE_DEPTH}", "null": "D_1 = none",
            "invalid_includes": ["an attempt inside its spacing (rebuilt from the records)", "a pointer move without a recorded passing attempt (strip and every re-check)", "a tape-table digest mismatch",
                                 "a tape drift (a drift episode whose outcome differs from the reused table's)", "every g2 INVALID condition"],
            "incomplete": ["P1, P2 or T0 (the reused tape verified, the drift check) not passed", "training ended before a valid end (wall, tick or transition cap; STALLED does not exist)",
                           "the close audit incomplete at a landing D_1 or R_1 needs", "B unpinned at an audited landing whose verified count is at least 10", "an unverified audit clear that could change D_1 or R_1"],
            "diagnostics_never_deciding": ["R_unperturbed", "deterministic", "tick 0", "FRONTIER_BACKED", "entropy", "calibration gap", "handover diagnostic", "the trigger-to-test gap", "the attempt yield",
                                           "the replenishment schedule", "per-pointer attempt counts"]}


def line_rule_description() -> Dict[str, Any]:
    return {"rule": G.LINE_RULE_ID, "order": list(LINE_OUTCOMES), "budget": {str(k): v for k, v in sorted(G.LINE_BUDGET.items())}, "success_depth": G.LINE_SUCCESS_DEPTH,
            "progress_from_session": G.LINE_PROGRESS_FROM_SESSION, "cap_sessions": G.LINE_CAP_SESSIONS, "incomplete_counts_if_train_fraction": G.INCOMPLETE_COUNTS_IF_TRAIN_FRACTION,
            "never_ends_on": ["a NULL s1", "an attempt count", "a HELD or STALLED state (none exists)"], "d_k": "the depth of the k-th counted session"}


def s1_rule_digest() -> str:
    return hashlib.sha256(json.dumps(s1_rule_description(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def line_rule_digest() -> str:
    return hashlib.sha256(json.dumps(line_rule_description(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


# -- the s1 rule --------------------------------------------------------------------------------------------------------------------


def apply_s1(facts: Mapping[str, Any]) -> Dict[str, Any]:
    """`facts`: invalid (list), phases ({open, p1, p2, t0, train, audit, verify: bool}), training ({valid_end, stop}), audit ({landing: {n, clears, verified}}),
    bars ({landing: B or None}), pointer_final, optional unperturbed ({landing: {n, clears}}), tick0 ({...}), deterministic. The logic is g2's rule with the g3
    identity; STALLED is not a valid end because it does not exist."""
    rows = {int(k): v for k, v in dict(facts.get("audit") or {}).items()}
    bars = {int(k): v for k, v in dict(facts.get("bars") or {}).items()}
    n = int(facts.get("audit_n") or G.AUDIT_EPISODES)                 # the registered 20; a synthetic test may audit fewer
    out: Dict[str, Any] = {"rule": G.S1_RULE_ID, "rule_sha256": s1_rule_digest(), "audit_n": n}
    d_v = depth(rows, n=n, count="verified")
    d_c = depth(rows, n=n, count="claimed")
    r_v = depth(rows, bars=bars, n=n, count="verified")
    r_c = depth(rows, bars=bars, n=n, count="claimed")
    out.update({"D": d_v["value"], "R": r_v["value"], "D_if_every_claimed_clear_were_verified": d_c["value"], "R_if_every_claimed_clear_were_verified": r_c["value"],
                "D_chain": d_v["chain"], "R_chain": r_v["chain"], "bars": {str(k): v for k, v in sorted(bars.items(), reverse=True)}})
    invalid = list(facts.get("invalid") or [])
    if invalid:
        out.update({"outcome": "INVALID", "reasons": invalid})
        return _diag(out, facts, rows)
    reasons: List[str] = []
    phases = dict(facts.get("phases") or {})
    for p in ("p1", "p2", "t0"):
        if not phases.get(p):
            reasons.append(f"{p.upper()} not passed")
    tr = dict(facts.get("training") or {})
    if not tr.get("valid_end") or str(tr.get("stop") or "").startswith("stalled"):
        reasons.append(f"training stopped before a valid end ({tr.get('stop')})")
    if 2128 not in rows or int(rows[2128].get("n", 0)) < n:
        reasons.append("the close audit is incomplete at 2128")
    for lam in d_v["undecidable"]:
        if f"the close audit is incomplete at {lam}" not in reasons:
            reasons.append(f"the close audit is incomplete at {lam}")
    if d_v["value"] != d_c["value"]:
        reasons.append(f"an unverified audit clear could change D ({d_v['value']} counted, {d_c['value']} if every claimed clear held)")
    for lam, row in sorted(rows.items(), reverse=True):
        if int(row.get("n", 0)) >= n and int(row.get("verified", 0)) >= G.D_MIN_CLEARS and bars.get(lam) is None:
            reasons.append(f"the tape baseline is unpinned at {lam} (B needed)")
    if r_v["value"] != r_c["value"]:
        reasons.append(f"an unverified audit clear could change R ({r_v['value']} counted, {r_c['value']} if every claimed clear held)")
    if reasons:
        out.update({"outcome": "INCOMPLETE", "reasons": reasons})
        return _diag(out, facts, rows)
    if r_v["value"] is not None and r_v["value"] <= G.PASS_REACH:
        out.update({"outcome": "PASS", "reasons": [f"R_1 = {r_v['value']} <= {G.PASS_REACH}"]})
    elif d_v["value"] is not None and d_v["value"] <= G.INCONCLUSIVE_DEPTH:
        out.update({"outcome": "INCONCLUSIVE", "reasons": [f"D_1 = {d_v['value']} <= {G.INCONCLUSIVE_DEPTH}; R_1 = {r_v['value']}"]})
    else:
        out.update({"outcome": "NULL", "reasons": ["D_1 = none: not even 10 of 20 at 2,128"]})
    return _diag(out, facts, rows)


def _diag(out: Dict[str, Any], facts: Mapping[str, Any], rows: Mapping[int, Mapping[str, Any]]) -> Dict[str, Any]:
    unp = {int(k): v for k, v in dict(facts.get("unperturbed") or {}).items()}
    ptr = facts.get("pointer_final")
    out["route_mastered_ticks"] = None if out.get("R") is None else G.ROUTE_END - int(out["R"])
    n = int(facts.get("audit_n") or G.AUDIT_EPISODES)
    out["diagnostics"] = {"R_unperturbed": depth(unp, n=int(facts.get("unperturbed_n") or G.AUDIT_UNPERTURBED), count="claimed")["value"] if unp else None,
                          "frontier_backed": frontier_backed(rows, int(ptr), n=n) if ptr is not None else None,
                          "tick0": facts.get("tick0"), "deterministic": facts.get("deterministic"), "note": "diagnostics only: none changes the outcome"}
    return out


# -- the line rule ------------------------------------------------------------------------------------------------------------------


def apply_line(sessions: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """`sessions`: in order, {k, outcome (the s1-style rule outcome, or INVALID / INCOMPLETE), D, train_fraction (0..1)}. Returns the line outcome after the
    last. Nothing here reads an attempt count, a HELD or a STALLED flag: none can end the line."""
    out: Dict[str, Any] = {"rule": G.LINE_RULE_ID, "rule_sha256": line_rule_digest()}
    if not sessions:
        out.update({"outcome": "CONTINUE", "k": 0, "reasons": ["no session yet"], "counted_sessions": [], "depths": []})
        return out
    counted = [s for s in sessions if not (s.get("outcome") == "INCOMPLETE" and float(s.get("train_fraction") or 0.0) < G.INCOMPLETE_COUNTS_IF_TRAIN_FRACTION)]
    k = len(counted)
    last = sessions[-1]
    out["k"] = k
    out["counted_sessions"] = [int(s.get("k", i + 1)) for i, s in enumerate(counted)]
    out["depths"] = [s.get("D") for s in counted]
    if last.get("outcome") == "INVALID":
        out.update({"outcome": "SUSPENDED", "reasons": ["the session is INVALID: repair and re-approval before any next session"]})
        return out
    if len(sessions) >= 2 and sessions[-1].get("outcome") == "INCOMPLETE" and sessions[-2].get("outcome") == "INCOMPLETE":
        out.update({"outcome": "SUSPENDED", "reasons": ["two consecutive INCOMPLETE sessions"]})
        return out
    if k == 0 or counted[-1] is not last:
        out.update({"outcome": "CONTINUE", "reasons": [f"the last session does not count toward k (k = {k}); session {len(sessions) + 1} is proposable with its own approval"]})
        return out
    d_k = counted[-1].get("D")
    if d_k is not None and int(d_k) <= G.LINE_SUCCESS_DEPTH:
        out.update({"outcome": "END_SUCCESS", "reasons": [f"D_{k} = {d_k} <= {G.LINE_SUCCESS_DEPTH}: crossing learned; the right side and the claim need a separate proposal"]})
        return out
    if k in G.LINE_BUDGET and (d_k is None or int(d_k) > G.LINE_BUDGET[k]):
        out.update({"outcome": f"END_BUDGET_{G.LINE_BUDGET[k]}", "reasons": [f"k = {k} and D_{k} = {d_k} is later than {G.LINE_BUDGET[k]}"]})
        return out
    if k >= G.LINE_PROGRESS_FROM_SESSION:
        prev2 = counted[-3].get("D") if len(counted) >= 3 else None
        later_or_equal = (d_k is None) or (prev2 is not None and int(d_k) >= int(prev2))
        if later_or_equal:
            out.update({"outcome": "END_NO_PROGRESS", "reasons": [f"D_{k} = {d_k} is not earlier than D_{k - 2} = {prev2}"]})
            return out
    if k >= G.LINE_CAP_SESSIONS:
        out.update({"outcome": "END_CAP", "reasons": [f"k = {k} without END_SUCCESS"]})
        return out
    out.update({"outcome": "CONTINUE", "reasons": [f"session {k + 1} is proposable, with its own approval"]})
    return out


# -- self-test ----------------------------------------------------------------------------------------------------------------------


def _row(verified: int, clears: Optional[int] = None, n: int = 20) -> Dict[str, Any]:
    return {"n": n, "clears": verified if clears is None else clears, "verified": verified}


def _facts(audit: Mapping[int, Dict[str, Any]], bars: Optional[Mapping[int, Optional[int]]] = None, pointer: int = 1980, **over: Any) -> Dict[str, Any]:
    f: Dict[str, Any] = {"invalid": [], "phases": {"open": True, "p1": True, "p2": True, "t0": True, "train": True, "audit": True, "verify": True},
                         "training": {"valid_end": True, "stop": "wall cap of phase train reached"}, "audit": dict(audit), "bars": dict(bars if bars is not None else {lam: 10 for lam in G.LANDINGS}),
                         "pointer_final": pointer}
    f.update(over)
    return f


def _s(k: int, outcome: str, D: Optional[int], **over: Any) -> Dict[str, Any]:
    d = {"k": k, "outcome": outcome, "D": D, "train_fraction": 1.0, "attempts": 999, "failed_attempts": {"2280": 999}}      # absurd attempt counts: never read
    d.update(over)
    return d


def self_test() -> List[str]:
    problems: List[str] = []

    def expect(label: str, got: Any, want: Any) -> None:
        if got != want:
            problems.append(f"{label}: got {got!r}, want {want!r}")

    B15 = {2128: 15, 1966: 10, 1694: 10, 1473: 10, 1369: 10, 1248: 10}
    # -- the s1 rule (g2's logic under the g3 identity) --
    out = apply_s1(_facts({2128: _row(15), 1966: _row(10)}, B15, pointer=1940))
    expect("PASS at R = 1966", (out["outcome"], out["D"], out["R"], out["rule"]), ("PASS", 1966, 1966, G.S1_RULE_ID))
    out = apply_s1(_facts({2128: _row(14), 1966: _row(12)}, B15, pointer=1940))
    expect("14 < B(2128) = 15: not PASS, D = 1966 -> INCONCLUSIVE", (out["outcome"], out["D"], out["R"]), ("INCONCLUSIVE", 1966, None))
    out = apply_s1(_facts({2128: _row(10)}, B15, pointer=2120))
    expect("D = 2128 -> INCONCLUSIVE", (out["outcome"], out["D"], out["R"]), ("INCONCLUSIVE", 2128, None))
    out = apply_s1(_facts({2128: _row(9)}, B15, pointer=2120))
    expect("9 of 20 at 2128 -> NULL", (out["outcome"], out["D"]), ("NULL", None))
    expect("no clear -> NULL", apply_s1(_facts({2128: _row(0)}, B15, pointer=2300))["outcome"], "NULL")
    out = apply_s1(_facts({2128: _row(15), 1966: _row(9), 1694: _row(20)}, B15, pointer=1600))
    expect("chain stops at 1966", (out["outcome"], out["D"], out["R"]), ("INCONCLUSIVE", 2128, 2128))
    out = apply_s1(_facts({2128: _row(15)}, B15, pointer=1900))
    expect("1966 not audited: D = 2128", (out["D"], out["R"], out["D_chain"]["1966"]), (2128, 2128, "not_audited"))
    out = apply_s1(_facts({2128: _row(16), 1966: _row(12), 1694: _row(11)}, {2128: 15, 1966: 13, 1694: 10}, pointer=1600))
    expect("R stops where the bar fails", (out["D"], out["R"]), (1694, 2128))
    expect("the reused bars: 95/200 -> 15, 98/200 -> 15, 2/40 -> 10, 0/40 -> 10", (G.bar_from_counts(95, 200), G.bar_from_counts(98, 200), G.bar_from_counts(2, 40), G.bar_from_counts(0, 40)), (15, 15, 10, 10))
    expect("INVALID outranks all", apply_s1(_facts({2128: _row(15), 1966: _row(10)}, B15, invalid=["an attempt inside its spacing"]))["outcome"], "INVALID")
    expect("T0 (the reused tape / drift check) not passed", apply_s1(_facts({2128: _row(15), 1966: _row(10)}, B15, phases={"p1": True, "p2": True, "t0": False}))["outcome"], "INCOMPLETE")
    expect("training stopped early", apply_s1(_facts({2128: _row(15), 1966: _row(10)}, B15, training={"valid_end": False, "stop": "memory"}))["outcome"], "INCOMPLETE")
    expect("a 'stalled' stop is not a valid end in g3", apply_s1(_facts({2128: _row(15), 1966: _row(10)}, B15, training={"valid_end": True, "stop": "stalled: x"}))["outcome"], "INCOMPLETE")
    expect("the tick cap is a valid end", apply_s1(_facts({2128: _row(15), 1966: _row(10)}, B15, training={"valid_end": True, "stop": "native tick cap"}))["outcome"], "PASS")
    expect("the transition cap is a valid end", apply_s1(_facts({2128: _row(15), 1966: _row(10)}, B15, training={"valid_end": True, "stop": "transition_cap"}))["outcome"], "PASS")
    expect("audit short at 2128", apply_s1(_facts({2128: _row(15, n=19)}, B15))["outcome"], "INCOMPLETE")
    expect("audit short at a reached landing", apply_s1(_facts({2128: _row(15), 1966: _row(10, n=19)}, B15, pointer=1940))["outcome"], "INCOMPLETE")
    expect("an unverified clear that could change D", apply_s1(_facts({2128: _row(15), 1966: _row(9, clears=10)}, B15, pointer=1940))["outcome"], "INCOMPLETE")
    expect("an unverified clear that could change R", apply_s1(_facts({2128: _row(14, clears=15), 1966: _row(10)}, B15, pointer=1940))["outcome"], "INCOMPLETE")
    expect("an unverified clear that cannot change D or R does not stop the rule", apply_s1(_facts({2128: _row(15, clears=16), 1966: _row(10, clears=12)}, B15, pointer=1940))["outcome"], "PASS")
    expect("B unpinned where the count is >= 10 is INCOMPLETE", apply_s1(_facts({2128: _row(15)}, {2128: None}, pointer=2120))["outcome"], "INCOMPLETE")
    expect("B unpinned where the count is < 10 does not matter: NULL", apply_s1(_facts({2128: _row(9)}, {2128: None}, pointer=2120))["outcome"], "NULL")
    base = apply_s1(_facts({2128: _row(15), 1966: _row(10)}, B15, pointer=1940))
    withd = apply_s1(_facts({2128: _row(15), 1966: _row(10)}, B15, pointer=1940, unperturbed={2128: _row(0)}, tick0={"n": 20, "clears": 0}))
    expect("diagnostics do not change the outcome", (base["outcome"], base["D"], base["R"]), (withd["outcome"], withd["D"], withd["R"]))
    expect("frontier_backed true when every passed landing holds", base["diagnostics"]["frontier_backed"], True)
    expect("FRONTIER_AHEAD when a passed landing decayed", apply_s1(_facts({2128: _row(15), 1966: _row(3)}, B15, pointer=1900))["diagnostics"]["frontier_backed"], False)
    # -- the line rule: every END is a progress or time condition --
    expect("empty line", apply_line([])["outcome"], "CONTINUE")
    expect("s1 NULL does NOT end the line", apply_line([_s(1, "NULL", None)])["outcome"], "CONTINUE")
    expect("s1 INCONCLUSIVE continues", apply_line([_s(1, "INCONCLUSIVE", 2128)])["outcome"], "CONTINUE")
    expect("s1 PASS continues", apply_line([_s(1, "PASS", 1966)])["outcome"], "CONTINUE")
    expect("k = 2 with D_2 = none: END_BUDGET_2128", apply_line([_s(1, "NULL", None), _s(2, "NULL", None)])["outcome"], "END_BUDGET_2128")
    expect("k = 2 with D_2 = 2128 continues", apply_line([_s(1, "NULL", None), _s(2, "INCONCLUSIVE", 2128)])["outcome"], "CONTINUE")
    expect("k = 3 is never a budget check", apply_line([_s(1, "NULL", None), _s(2, "INCONCLUSIVE", 2128), _s(3, "INCONCLUSIVE", 2128)])["outcome"], "CONTINUE")
    s4 = [_s(1, "NULL", None), _s(2, "INCONCLUSIVE", 2128), _s(3, "INCONCLUSIVE", 2128), _s(4, "INCONCLUSIVE", 2128)]
    expect("k = 4 with D_4 = 2128: END_BUDGET_1966", apply_line(s4)["outcome"], "END_BUDGET_1966")
    s4b = s4[:3] + [_s(4, "PASS", 1966)]
    expect("k = 4 with D_4 = 1966 and D_2 = 2128 continues", apply_line(s4b)["outcome"], "CONTINUE")
    s4c = [_s(1, "PASS", 1966), _s(2, "PASS", 1966), _s(3, "PASS", 1966), _s(4, "PASS", 1966)]
    expect("k = 4 with D_4 = D_2 = 1966: END_NO_PROGRESS", apply_line(s4c)["outcome"], "END_NO_PROGRESS")
    s5 = s4b + [_s(5, "PASS", 1966)]
    expect("k = 5 with D_5 = 1966 and D_3 = 2128 continues", apply_line(s5)["outcome"], "CONTINUE")
    s6 = s5 + [_s(6, "PASS", 1966)]
    expect("k = 6 with D_6 = 1966: END_BUDGET_1694 (checked before no-progress)", apply_line(s6)["outcome"], "END_BUDGET_1694")
    s6b = s5 + [_s(6, "PASS", 1694)]
    expect("k = 6 with D_6 = 1694 and D_4 = 1966 continues", apply_line(s6b)["outcome"], "CONTINUE")
    s7 = s6b + [_s(7, "PASS", 1694)]
    expect("k = 7 with D_7 = 1694 and D_5 = 1966 continues", apply_line(s7)["outcome"], "CONTINUE")
    s8 = s7 + [_s(8, "PASS", 1694)]
    expect("k = 8 with D_8 = D_6 = 1694: END_NO_PROGRESS before the cap", apply_line(s8)["outcome"], "END_NO_PROGRESS")
    s8b = s7 + [_s(8, "PASS", 1600)]
    expect("k = 8 with progress but no success: END_CAP", apply_line(s8b)["outcome"], "END_CAP")
    expect("success at any k", apply_line([_s(1, "PASS", 1473)])["outcome"], "END_SUCCESS")
    expect("success at k = 2 outranks the budget", apply_line([_s(1, "NULL", None), _s(2, "PASS", 1369)])["outcome"], "END_SUCCESS")
    expect("INVALID suspends", apply_line([_s(1, "INVALID", None)])["outcome"], "SUSPENDED")
    expect("two INCOMPLETE suspend", apply_line([_s(1, "INCOMPLETE", None, train_fraction=0.9), _s(2, "INCOMPLETE", None, train_fraction=0.9)])["outcome"], "SUSPENDED")
    expect("a short INCOMPLETE session does not count toward k", apply_line([_s(1, "INCOMPLETE", None, train_fraction=0.1)])["k"], 0)
    expect("a short INCOMPLETE last session leaves the line where it was", apply_line([_s(1, "NULL", None), _s(2, "INCOMPLETE", None, train_fraction=0.1)])["outcome"], "CONTINUE")
    expect("a long INCOMPLETE session counts: k = 2 with D none ends the budget", apply_line([_s(1, "NULL", None), _s(2, "INCOMPLETE", None, train_fraction=0.9)])["outcome"], "END_BUDGET_2128")
    # attempt counts can never end the line: the rule ignores them entirely
    for s in ([_s(1, "NULL", None, attempts=10 ** 6, held=True, stalled=True)], [_s(1, "INCONCLUSIVE", 2128, failed_attempts={"2280": 10 ** 6}, stalled=True)]):
        expect("attempt counts, HELD and STALLED flags are never read", apply_line(s)["outcome"], "CONTINUE")
    expect("digests stable", (len(s1_rule_digest()), len(line_rule_digest()), s1_rule_digest() == s1_rule_digest()), (64, 64, True))
    expect("the g3 rule digests differ from g2's", (s1_rule_digest() != R2.s1_rule_digest(), line_rule_digest() != R2.line_rule_digest()), (True, True))
    return problems


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "self-test":
        problems = self_test()
        for p in problems:
            print("FAIL:", p)
        print(f"m9_g3_rule self-test: {'PASS' if not problems else 'FAIL'} ({len(problems)} problem(s)), s1 {s1_rule_digest()[:16]} line {line_rule_digest()[:16]}")
        return 0 if not problems else 1
    print(json.dumps({"s1": s1_rule_description(), "line": line_rule_description()}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
