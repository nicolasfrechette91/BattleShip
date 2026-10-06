#!/usr/bin/env python3
"""M9-g2: the registered rules `m9_g2_s1_rule_v1` and `m9_g2_line_rule_v1`, the measures D and R, and their self-tests (pure, standard library only).

    python rl/m9_g2_rule.py self-test

D_k (sustained frontier depth) = the earliest registered landing such that, at it and at every later AUDITED landing, the frozen final policy's verified sticky
clears are >= 10 of 20. R_k (reliable reach) = the same with >= B(landing), the pinned tape bar. A landing that was not audited does not pass; R is never earlier
than D. `m9_g2_s1_rule_v1`, evaluated in this order (the first that holds is the outcome):

    INVALID       any integrity or compliance failure
    INCOMPLETE    P1, P2 or T0 not passed; training ended before a valid end (wall / tick / transition cap or STALLED); the close audit incomplete at a landing
                  D_1 or R_1 needs; B unpinned at an audited landing whose verified count is at least 10; an unverified audit clear that could change D_1 or R_1
    PASS          R_1 <= 1,966
    INCONCLUSIVE  D_1 <= 2,128
    NULL          D_1 = none

`m9_g2_line_rule_v1` (checked at every session close, in order): SUSPENDED (an INVALID session, or two consecutive INCOMPLETE sessions), END_NULL_S1,
END_STALLED, END_SUCCESS (D_k <= 1,473), END_BUDGET_1966 (k = 3 and D_3 later than 1,966), END_NO_PROGRESS (k >= 4 and D_k not earlier than D_{k-2}),
END_CAP (k = 8), else CONTINUE. An INCOMPLETE session counts toward k only if its training reached at least 50 % of its wall cap.
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

import m9_g2_contract as G

S1_OUTCOMES = ("INVALID", "INCOMPLETE", "PASS", "INCONCLUSIVE", "NULL")
LINE_OUTCOMES = ("SUSPENDED", "END_NULL_S1", "END_STALLED", "END_SUCCESS", "END_BUDGET_1966", "END_NO_PROGRESS", "END_CAP", "CONTINUE")


def s1_rule_description() -> Dict[str, Any]:
    return {"rule": G.S1_RULE_ID, "order": list(S1_OUTCOMES), "landings": list(G.LANDINGS), "D": f"earliest landing with >= {G.D_MIN_CLEARS} of {G.AUDIT_EPISODES} verified sticky clears at it and every later audited landing",
            "R": "the same with >= B(landing) = max(10, ceil(20 p_hat) + 5)", "pass": f"R_1 <= {G.PASS_REACH}", "inconclusive": f"D_1 <= {G.INCONCLUSIVE_DEPTH}", "null": "D_1 = none",
            "incomplete": ["P1, P2 or T0 not passed", "training ended before a valid end (wall, tick, transition cap or STALLED)", "the close audit incomplete at a landing D_1 or R_1 needs",
                           "B unpinned at an audited landing whose verified count is at least 10", "an unverified audit clear that could change D_1 or R_1"],
            "diagnostics_never_deciding": ["R_unperturbed", "deterministic", "tick 0", "FRONTIER_BACKED", "entropy", "calibration gap", "handover diagnostic"]}


def line_rule_description() -> Dict[str, Any]:
    return {"rule": G.LINE_RULE_ID, "order": list(LINE_OUTCOMES), "budget_depth": G.LINE_BUDGET_DEPTH, "budget_sessions": G.LINE_BUDGET_SESSIONS, "progress_from_session": G.LINE_PROGRESS_FROM_SESSION,
            "cap_sessions": G.LINE_CAP_SESSIONS, "success_depth": G.LINE_SUCCESS_DEPTH, "incomplete_counts_if_train_fraction": G.INCOMPLETE_COUNTS_IF_TRAIN_FRACTION}


def s1_rule_digest() -> str:
    return hashlib.sha256(json.dumps(s1_rule_description(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def line_rule_digest() -> str:
    return hashlib.sha256(json.dumps(line_rule_description(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


# -- the measures -------------------------------------------------------------------------------------------------------------------


def _passes(row: Mapping[str, Any], need: Optional[int], n: int, count: str) -> Optional[bool]:
    """True / False, or None when undecidable (the audit short of n, or B unknown)."""
    if int(row.get("n", 0)) < n:
        return None
    if need is None:
        return None
    c = int(row["verified"]) if count == "verified" else int(row["clears"])
    return c >= need


def depth(rows: Mapping[int, Mapping[str, Any]], *, bars: Optional[Mapping[int, Optional[int]]] = None, n: int = G.AUDIT_EPISODES, count: str = "verified",
          landings: Sequence[int] = G.LANDINGS) -> Dict[str, Any]:
    """D (bars None) or R (bars given) over the audited rows: the earliest landing such that it and every later landing passes. Returns {value, undecidable:
    [landings], chain: {landing: pass}}. The chain stops at the first landing that fails or is not audited; an undecidable landing stops it too and is named."""
    value: Optional[int] = None
    undecidable: List[int] = []
    chain: Dict[int, Any] = {}
    for lam in sorted(landings, reverse=True):
        row = rows.get(lam)
        if row is None:
            chain[lam] = "not_audited"
            break
        need = G.D_MIN_CLEARS if bars is None else bars.get(lam)
        p = _passes(row, need, n, count)
        chain[lam] = p
        if p is None:
            undecidable.append(lam)
            break
        if p:
            value = lam
        else:
            break
    return {"value": value, "undecidable": undecidable, "chain": {str(k): v for k, v in chain.items()}}


def frontier_backed(rows: Mapping[int, Mapping[str, Any]], pointer: int, *, n: int = G.AUDIT_EPISODES, landings: Sequence[int] = G.LANDINGS) -> Optional[bool]:
    behind = [lam for lam in landings if lam >= int(pointer) + G.STRIP]
    if not behind:
        return True
    out = True
    for lam in behind:
        p = _passes(rows.get(lam, {}), G.D_MIN_CLEARS, n, "verified")
        if p is None:
            return None
        out = out and p
    return out


# -- the s1 rule --------------------------------------------------------------------------------------------------------------------


def apply_s1(facts: Mapping[str, Any]) -> Dict[str, Any]:
    """`facts`: invalid (list), phases ({open, p1, p2, t0, train, audit, verify: bool}), training ({valid_end, stop}), audit ({landing: {n, clears, verified}}),
    bars ({landing: B or None}), pointer_final, optional unperturbed ({landing: {n, clears}}), tick0 ({...}), deterministic."""
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
    if not tr.get("valid_end"):
        reasons.append(f"training stopped before a valid end ({tr.get('stop')})")
    # the audit must cover 2,128 and be complete at every landing the chain reaches
    if 2128 not in rows or int(rows[2128].get("n", 0)) < n:
        reasons.append("the close audit is incomplete at 2128")
    for lam in d_v["undecidable"]:
        if f"the close audit is incomplete at {lam}" not in reasons:
            reasons.append(f"the close audit is incomplete at {lam}")
    if d_v["value"] != d_c["value"]:
        reasons.append(f"an unverified audit clear could change D ({d_v['value']} counted, {d_c['value']} if every claimed clear held)")
    # B unpinned where it could matter: an audited landing whose verified count is at least 10
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
    """`sessions`: in order, {k, outcome (s1 rule or INVALID/INCOMPLETE), D, stalled (bool), train_fraction (0..1)}. Returns the line outcome after the last."""
    out: Dict[str, Any] = {"rule": G.LINE_RULE_ID, "rule_sha256": line_rule_digest()}
    if not sessions:
        out.update({"outcome": "CONTINUE", "k": 0, "reasons": ["no session yet"], "counted_sessions": []})
        return out
    counted: List[Mapping[str, Any]] = []
    for s in sessions:
        if s.get("outcome") == "INCOMPLETE" and float(s.get("train_fraction") or 0.0) < G.INCOMPLETE_COUNTS_IF_TRAIN_FRACTION:
            continue
        counted.append(s)
    k = len(counted)
    last = sessions[-1]
    out["k"] = k
    out["counted_sessions"] = [int(s.get("k", i + 1)) for i, s in enumerate(counted)]
    if last.get("outcome") == "INVALID":
        out.update({"outcome": "SUSPENDED", "reasons": ["the session is INVALID: repair and re-approval before any next session"]})
        return out
    if len(sessions) >= 2 and sessions[-1].get("outcome") == "INCOMPLETE" and sessions[-2].get("outcome") == "INCOMPLETE":
        out.update({"outcome": "SUSPENDED", "reasons": ["two consecutive INCOMPLETE sessions"]})
        return out
    if int(last.get("k", len(sessions))) == 1 and last.get("outcome") == "NULL":
        out.update({"outcome": "END_NULL_S1", "reasons": ["g2-s1 is NULL"]})
        return out
    if any(bool(s.get("stalled")) for s in sessions):
        out.update({"outcome": "END_STALLED", "reasons": ["a pointer has 6 failed attempts over the line"]})
        return out
    d_last = last.get("D")
    if d_last is not None and int(d_last) <= G.LINE_SUCCESS_DEPTH:
        out.update({"outcome": "END_SUCCESS", "reasons": [f"D_{k} = {d_last} <= {G.LINE_SUCCESS_DEPTH}: crossing learned; g3 needs a separate proposal"]})
        return out
    if k == G.LINE_BUDGET_SESSIONS and (d_last is None or int(d_last) > G.LINE_BUDGET_DEPTH):
        out.update({"outcome": "END_BUDGET_1966", "reasons": [f"k = {k} and D_{k} = {d_last} is later than {G.LINE_BUDGET_DEPTH}"]})
        return out
    if k >= G.LINE_PROGRESS_FROM_SESSION:
        prev2 = counted[-3].get("D") if len(counted) >= 3 else None
        later_or_equal = (d_last is None) or (prev2 is not None and int(d_last) >= int(prev2))
        if later_or_equal:
            out.update({"outcome": "END_NO_PROGRESS", "reasons": [f"D_{k} = {d_last} is not earlier than D_{k - 2} = {prev2}"]})
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
                         "training": {"valid_end": True, "stop": "wall_cap"}, "audit": dict(audit), "bars": dict(bars if bars is not None else {lam: 10 for lam in G.LANDINGS}),
                         "pointer_final": pointer}
    f.update(over)
    return f


def self_test() -> List[str]:
    problems: List[str] = []

    def expect(label: str, got: Any, want: Any) -> None:
        if got != want:
            problems.append(f"{label}: got {got!r}, want {want!r}")

    B15 = {2128: 15, 1966: 10, 1694: 10, 1473: 10, 1369: 10, 1248: 10}
    # PASS: R <= 1,966 with the bar 15 at 2,128
    out = apply_s1(_facts({2128: _row(15), 1966: _row(10)}, B15, pointer=1940))
    expect("PASS at R = 1966", (out["outcome"], out["D"], out["R"]), ("PASS", 1966, 1966))
    out = apply_s1(_facts({2128: _row(14), 1966: _row(12)}, B15, pointer=1940))
    expect("14 < B(2128) = 15: not PASS, D = 1966 -> INCONCLUSIVE", (out["outcome"], out["D"], out["R"]), ("INCONCLUSIVE", 1966, None))
    out = apply_s1(_facts({2128: _row(10)}, B15, pointer=2120))
    expect("D = 2128 -> INCONCLUSIVE", (out["outcome"], out["D"], out["R"]), ("INCONCLUSIVE", 2128, None))
    out = apply_s1(_facts({2128: _row(9)}, B15, pointer=2120))
    expect("9 of 20 at 2128 -> NULL", (out["outcome"], out["D"]), ("NULL", None))
    out = apply_s1(_facts({2128: _row(0)}, B15, pointer=2300))
    expect("no clear -> NULL", out["outcome"], "NULL")
    # the chain stops at the first failing landing even when deeper ones pass
    out = apply_s1(_facts({2128: _row(15), 1966: _row(9), 1694: _row(20)}, B15, pointer=1600))
    expect("chain stops at 1966", (out["outcome"], out["D"], out["R"]), ("INCONCLUSIVE", 2128, 2128))
    # a landing not audited does not pass
    out = apply_s1(_facts({2128: _row(15)}, B15, pointer=1900))
    expect("1966 not audited: D = 2128", (out["D"], out["R"], out["D_chain"]["1966"]), (2128, 2128, "not_audited"))
    # R never earlier than D
    out = apply_s1(_facts({2128: _row(16), 1966: _row(12), 1694: _row(11)}, {2128: 15, 1966: 13, 1694: 10}, pointer=1600))
    expect("R stops where the bar fails", (out["D"], out["R"]), (1694, 2128))
    # bar arithmetic
    expect("bar from counts 95/200", G.bar_from_counts(95, 200), 15)
    expect("bar from counts 0/40", G.bar_from_counts(0, 40), 10)
    expect("bar from counts 10/40", G.bar_from_counts(10, 40), 10)
    expect("bar from counts 11/40 (ceil 5.5 = 6, +5 = 11)", G.bar_from_counts(11, 40), 11)
    expect("bar from counts 100/200", G.bar_from_counts(100, 200), 15)
    expect("bar from counts 101/200 (ceil 10.1 = 11, +5 = 16)", G.bar_from_counts(101, 200), 16)
    expect("bar(p_hat) agrees", (G.bar(0.475), G.bar(0.0), G.bar(0.5), G.bar(0.505)), (15, 10, 15, 16))
    # INCOMPLETE conditions
    expect("INVALID outranks all", apply_s1(_facts({2128: _row(15), 1966: _row(10)}, B15, invalid=["x"]))["outcome"], "INVALID")
    expect("T0 not passed", apply_s1(_facts({2128: _row(15), 1966: _row(10)}, B15, phases={"p1": True, "p2": True, "t0": False}))["outcome"], "INCOMPLETE")
    expect("training stopped early", apply_s1(_facts({2128: _row(15), 1966: _row(10)}, B15, training={"valid_end": False, "stop": "memory"}))["outcome"], "INCOMPLETE")
    expect("audit short at 2128", apply_s1(_facts({2128: _row(15, n=19)}, B15))["outcome"], "INCOMPLETE")
    expect("audit short at a reached landing", apply_s1(_facts({2128: _row(15), 1966: _row(10, n=19)}, B15, pointer=1940))["outcome"], "INCOMPLETE")
    out = apply_s1(_facts({2128: _row(15), 1966: _row(9, clears=10)}, B15, pointer=1940))
    expect("an unverified clear that could change D", out["outcome"], "INCOMPLETE")
    out = apply_s1(_facts({2128: _row(14, clears=15), 1966: _row(10)}, B15, pointer=1940))
    expect("an unverified clear that could change R", out["outcome"], "INCOMPLETE")
    out = apply_s1(_facts({2128: _row(15, clears=16), 1966: _row(10, clears=12)}, B15, pointer=1940))
    expect("an unverified clear that cannot change D or R does not stop the rule", out["outcome"], "PASS")
    out = apply_s1(_facts({2128: _row(15)}, {2128: None}, pointer=2120))
    expect("B unpinned where the count is >= 10 is INCOMPLETE", out["outcome"], "INCOMPLETE")
    out = apply_s1(_facts({2128: _row(9)}, {2128: None}, pointer=2120))
    expect("B unpinned where the count is < 10 does not matter: NULL", out["outcome"], "NULL")
    # STALLED is a valid end
    expect("stalled is a valid end", apply_s1(_facts({2128: _row(15), 1966: _row(10)}, B15, training={"valid_end": True, "stop": "stalled"}))["outcome"], "PASS")
    # diagnostics never decide
    base = apply_s1(_facts({2128: _row(15), 1966: _row(10)}, B15, pointer=1940))
    withd = apply_s1(_facts({2128: _row(15), 1966: _row(10)}, B15, pointer=1940, unperturbed={2128: _row(0)}, tick0={"n": 20, "clears": 0}))
    expect("diagnostics do not change the outcome", (base["outcome"], base["D"], base["R"]), (withd["outcome"], withd["D"], withd["R"]))
    expect("frontier_backed true when every passed landing holds", base["diagnostics"]["frontier_backed"], True)
    ahead = apply_s1(_facts({2128: _row(15), 1966: _row(3)}, B15, pointer=1900))
    expect("FRONTIER_AHEAD when a passed landing decayed", ahead["diagnostics"]["frontier_backed"], False)
    # the line rule
    expect("empty line", apply_line([])["outcome"], "CONTINUE")
    expect("s1 NULL ends the line", apply_line([{"k": 1, "outcome": "NULL", "D": None}])["outcome"], "END_NULL_S1")
    expect("s1 INCONCLUSIVE continues", apply_line([{"k": 1, "outcome": "INCONCLUSIVE", "D": 2128}])["outcome"], "CONTINUE")
    expect("s1 PASS continues", apply_line([{"k": 1, "outcome": "PASS", "D": 1966}])["outcome"], "CONTINUE")
    expect("stalled ends", apply_line([{"k": 1, "outcome": "INCONCLUSIVE", "D": 2128}, {"k": 2, "outcome": "INCONCLUSIVE", "D": 2128, "stalled": True}])["outcome"], "END_STALLED")
    expect("success", apply_line([{"k": 1, "outcome": "PASS", "D": 1966}, {"k": 2, "outcome": "PASS", "D": 1473}])["outcome"], "END_SUCCESS")
    s3 = [{"k": 1, "outcome": "INCONCLUSIVE", "D": 2128}, {"k": 2, "outcome": "INCONCLUSIVE", "D": 2128}, {"k": 3, "outcome": "INCONCLUSIVE", "D": 2128}]
    expect("budget at k = 3 without 1966", apply_line(s3)["outcome"], "END_BUDGET_1966")
    s3b = s3[:2] + [{"k": 3, "outcome": "PASS", "D": 1966}]
    expect("1966 at k = 3 continues", apply_line(s3b)["outcome"], "CONTINUE")
    s4 = s3b + [{"k": 4, "outcome": "PASS", "D": 1966}]
    expect("k = 4: D_4 = 1966 not earlier than D_2 = 2128 -> continue (it is earlier)", apply_line(s4)["outcome"], "CONTINUE")
    s5 = s4 + [{"k": 5, "outcome": "PASS", "D": 1966}]
    expect("k = 5: D_5 = 1966 not earlier than D_3 = 1966 -> no progress", apply_line(s5)["outcome"], "END_NO_PROGRESS")
    s5b = s4 + [{"k": 5, "outcome": "PASS", "D": 1694}]
    expect("k = 5 with a new landing continues", apply_line(s5b)["outcome"], "CONTINUE")
    s8 = [{"k": i, "outcome": "PASS", "D": d} for i, d in enumerate((1966, 1966, 1966, 1694, 1694, 1694, 1694, 1694), start=1)]
    expect("END_NO_PROGRESS before the cap when D stalls", apply_line(s8[:6])["outcome"], "END_NO_PROGRESS")
    s8c = [{"k": i, "outcome": "PASS", "D": d} for i, d in enumerate((1966, 1966, 1966, 1694, 1694, 1694, 1694, 1694), start=1)]
    s8c[5]["D"] = 1600                                              # a synthetic deeper landing keeps progress alive to the cap
    s8c[6]["D"] = 1600
    s8c[7]["D"] = 1500
    expect("cap at k = 8", apply_line(s8c)["outcome"], "END_CAP")
    expect("INVALID suspends", apply_line([{"k": 1, "outcome": "INVALID", "D": None}])["outcome"], "SUSPENDED")
    expect("two INCOMPLETE suspend", apply_line([{"k": 1, "outcome": "INCOMPLETE", "D": None, "train_fraction": 0.9}, {"k": 2, "outcome": "INCOMPLETE", "D": None, "train_fraction": 0.9}])["outcome"], "SUSPENDED")
    expect("a short INCOMPLETE session does not count toward k", apply_line([{"k": 1, "outcome": "INCOMPLETE", "D": None, "train_fraction": 0.1}])["k"], 0)
    expect("digests stable", (len(s1_rule_digest()), len(line_rule_digest()), s1_rule_digest() == s1_rule_digest()), (64, 64, True))
    return problems


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "self-test":
        problems = self_test()
        for p in problems:
            print("FAIL:", p)
        print(f"m9_g2_rule self-test: {'PASS' if not problems else 'FAIL'} ({len(problems)} problem(s)), s1 {s1_rule_digest()[:16]} line {line_rule_digest()[:16]}")
        return 0 if not problems else 1
    print(json.dumps({"s1": s1_rule_description(), "line": line_rule_description()}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
