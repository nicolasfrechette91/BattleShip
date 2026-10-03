#!/usr/bin/env python3
"""M8-rd4: the registered rule `m8_rd4_rule_v1` (pure; no game, no numpy, no torch).

One session, one set of keyed draws, NO control arm. The rule reads only quantities verified before it is applied:

    m  the highest ladder level (0 none, 2 qualified crossing, 3 left-target break, 4 clear) held by a fresh-process replay from tick 0, exactly equal to its claim, of a trajectory whose
       qualifying event lies in a burst ingested during rd4. A crossing counts even when its ENTRY lies in an inherited prefix and its LANDING in an rd4 burst: the full route is verified by
       exact replay from tick 0 (the replay's analyser reads the whole trajectory). The wall-top landing (1) is rd2's and is not claimed again.
    t  the number of targets broken by the exactly replayed maximum-targets candidate (REPORTED; t >= 8 implies a left target, so it is not a separate basis)

    INVALID            any integrity failure (evaluated first)
    INCOMPLETE         not a performance result (evaluated second)
    PROGRESS           m >= 2: a verified qualified crossing (btt_qualified_crossing_v1), a left target or a clear
    NO_NEW_MILESTONE   otherwise

The highest milestone is reported with every outcome. The MECHANISM CHECK (decision 7) is evaluated at the close and reported with every outcome:

    MECHANISM_FAILS   more than 45.0 % of rd4's returns start from a cell seen 8 or more times (at dispatch), OR fewer than 1.74 new cells per return
    MECHANISM_HOLDS   otherwise

Both comparisons are exact integer arithmetic (a share of exactly 45.0 % and exactly 1.74 new cells per return hold). The dilution verdict is reported only (decision 8: no guard).

THE LINE BUDGET (decisions 1 and 7), reported as `line` with every outcome: the line continues for at most two sessions, rd4 and then rd5 at most; if there is no verified qualified crossing
(or higher) by the end of rd5 the line ends; an INCOMPLETE session counts as one of the two once exploration has started; a failed mechanism check without a verified crossing (or higher) ends the
line after rd4; a verified milestone always outranks the mechanism check. An INVALID session is a repair and a new approval: whether it consumes budget is the user's decision (rd5_permitted is then
None, never guessed).

Stops carried from rd3's rule: S3 (horizon pressure), S5 (BOUND_VIOLATION), S7 (INVALID / INCOMPLETE). S1, S2, S4 and S6 are replaced by the line budget above.

    python rl/m8_rd4_rule.py self-test
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

import m8_rd2_rule as rule2

LADDER = rule2.LADDER
RULE_ID = "m8_rd4_rule_v1"
SCOPE = ("M8-rd4: third continuation of archive m8_rd_a1 (rd1, rd2 and rd3 as closed) under m8_rd_select_v3 (m8_rd_select_v2 with one change: the count term (1 + seen)^-1/2); one session, "
         "one set of keyed draws; no control arm; not a policy result, not a learning result, not a comparison of v3 with v2")
PROGRESS_MIN_M = 2
MIN_EXPLORATION_TICKS = rule2.MIN_EXPLORATION_TICKS
MAX_LIFECYCLE_FAILURES = rule2.MAX_LIFECYCLE_FAILURES
TOP_LEVEL_MEDIAN_L_LIMIT = rule2.TOP_LEVEL_MEDIAN_L_LIMIT
SEEN_MIN = 8                                       # a "seen 8 or more times" start cell
SEEN_SHARE_MAX_PER_MILLE = 450                     # at most 45.0 % of returns start from such a cell
NEW_CELLS_MIN_PER_100_RETURNS = 174                # at least 1.74 new cells per return
OUTCOMES = ("INVALID", "INCOMPLETE", "PROGRESS", "NO_NEW_MILESTONE")
MECHANISM_VERDICTS = ("MECHANISM_HOLDS", "MECHANISM_FAILS", "NOT_EVALUABLE")
STOPS = ("S3", "S5", "S7")
BUDGET = "at most two sessions: rd4, then rd5 at most; the line ends if there is no verified qualified crossing (or higher) by the end of rd5"
RD3_REFERENCE = {"seen_ge_8_share": 1802 / 4194, "new_cells_per_return": 7309 / 4194,
                 "note": "rd3's REALISED values: 1,802 of 4,194 dispatches from cells seen 8 or more times at dispatch; 7,309 new cells in 4,194 returns (the stop review's 43.4 % is the analytic selection mass on such cells)"}


def rule_description() -> Dict[str, Any]:
    return {"rule": RULE_ID, "order": list(OUTCOMES), "ladder": list(LADDER), "control_arm": False,
            "m": "the highest milestone (crossing, left target, clear) of an exactly replayed trajectory whose qualifying event lies in a burst ingested during rd4; the entry of a crossing may lie in "
                 "an inherited prefix; the wall-top landing is rd2's and is not claimed again",
            "t": "the targets broken by the exactly replayed maximum-targets candidate of rd4 (reported, never a basis)",
            "progress": f"m >= {PROGRESS_MIN_M}: a verified qualified crossing (btt_qualified_crossing_v1), a left target or a clear", "no_new_milestone": "otherwise",
            "mechanism": {"fails": f"more than {SEEN_SHARE_MAX_PER_MILLE / 10} % of rd4's returns start from a cell seen {SEEN_MIN} or more times at dispatch, or fewer than "
                                   f"{NEW_CELLS_MIN_PER_100_RETURNS / 100} new cells per return", "holds": "otherwise", "exact": "integer arithmetic",
                          "new_cells": "cells created in rd4 (ids from the open archive's cell count) per rd4 return (an ingested job)",
                          "seen": "the start cell's `seen` counter AT DISPATCH, from the ledger replay", "reported_with": "every outcome"},
            "dilution": {"below_floor_max_per_mille": rule2.BELOW_FLOOR_MAX_PER_MILLE, "fatal_max_per_mille": rule2.FATAL_MAX_PER_MILLE, "note": "reported only: no guard (decision 8)"},
            "line": {"budget": BUDGET, "incomplete": "counts as one of the two once exploration has started",
                     "mechanism": "a failed mechanism check without a verified crossing (or higher) ends the line after rd4; a verified milestone outranks it",
                     "invalid": "repair and a new approval; whether it consumes budget is the user's decision"},
            "launch_capable": "A2 or A1 cell with y >= 1,639 that was created in rd4, counted in the final archive (reported)",
            "incomplete": [f"exploration below {MIN_EXPLORATION_TICKS:,} native ticks", "a memory, process-count, session-cap or worker-error stop",
                           f"more than {MAX_LIFECYCLE_FAILURES} lifecycle failures", "the open phase (P1, identity replays) not completed",
                           "a candidate that could raise m (by the events it carries) left unverified at the replay cap"],
            "invalid": ["a tick-0 / prefix / end / chain mismatch", "a consumed-tick violation", "an inexact verification replay",
                        "a provenance or static-guard violation, or any write under runs/m8_rd/, runs/m8_rd_rd2/ or runs/m8_rd_rd3/", "a pin drift",
                        "any read of fixtures, recordings or the TAS", "a change of an earlier tree (R1) at the close", "a prefix-chain failure at any level",
                        "an open overlay that does not reproduce", "a failed ledger rebuild"],
            "stops": {"S3": f"median L of the top level's eligible cells > {TOP_LEVEL_MEDIAN_L_LIMIT} before a left target (m < 3): horizon review",
                      "S5": "BOUND_VIOLATION: the bound is withdrawn or corrected under a new contract",
                      "S7": "INVALID or INCOMPLETE: repair and a new approval; never an extension or an automatic retry"},
            "reads": "verified m and the registered counts only; no diagnostic enters the outcome"}


def rule_digest() -> str:
    return hashlib.sha256(json.dumps(rule_description(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def mechanism(*, returns: int, seen_ge_8: int, new_cells: int) -> Dict[str, Any]:
    """The mechanism check, exact: more than 45.0 % of returns from cells seen 8 or more times, or fewer than 1.74 new cells per return, fails it."""
    for name, v in (("returns", returns), ("seen_ge_8", seen_ge_8), ("new_cells", new_cells)):
        if int(v) < 0:
            raise ValueError(f"{name} {v} is negative")
    if seen_ge_8 > returns:
        raise ValueError("more returns from seen >= 8 cells than returns")
    rec: Dict[str, Any] = {"returns": int(returns), "seen_ge_8": int(seen_ge_8), "new_cells": int(new_cells),
                           "seen_ge_8_share": (seen_ge_8 / returns) if returns else None, "new_cells_per_return": (new_cells / returns) if returns else None,
                           "thresholds": {"seen_ge_8_share_max": SEEN_SHARE_MAX_PER_MILLE / 1000, "new_cells_per_return_min": NEW_CELLS_MIN_PER_100_RETURNS / 100},
                           "rd3_reference": RD3_REFERENCE}
    if returns <= 0:
        rec.update(seen_ok=None, new_cells_ok=None, verdict="NOT_EVALUABLE")
        return rec
    seen_ok = int(seen_ge_8) * 1000 <= SEEN_SHARE_MAX_PER_MILLE * int(returns)
    cells_ok = int(new_cells) * 100 >= NEW_CELLS_MIN_PER_100_RETURNS * int(returns)
    rec.update(seen_ok=seen_ok, new_cells_ok=cells_ok, verdict="MECHANISM_HOLDS" if (seen_ok and cells_ok) else "MECHANISM_FAILS")
    return rec


def line_status(*, outcome: str, m: int, mech: Mapping[str, Any], exploration_started: bool, exploration_ticks: Optional[int] = None) -> Dict[str, Any]:
    """The state of the two-session budget after rd4 (decisions 1 and 7), from the outcome, the verified m, the mechanism verdict and whether exploration started."""
    base = {"budget": BUDGET, "session": "rd4", "exploration_ticks": exploration_ticks, "mechanism_returns": mech.get("returns"),
            "provisional": bool(exploration_ticks is not None and int(exploration_ticks) < MIN_EXPLORATION_TICKS)}      # a status read from fewer ticks than the validity floor is information, not a result
    if outcome == "INVALID":
        return dict(base, status="REPAIR_NEEDED", session_counts=None, rd5_permitted=None, line_ends=False,
                    reason="INVALID: repair and a new approval; whether this session consumes one of the two is the user's decision (not guessed here)")
    if int(m) >= PROGRESS_MIN_M:
        return dict(base, status="MILESTONE_VERIFIED", session_counts=True, rd5_permitted=True, line_ends=False,
                    reason=f"a verified {LADDER[int(m)]}: the line's requirement is met; rd5 may be proposed (at most one more session), authorised separately; the mechanism check does not apply")
    if not exploration_started:
        return dict(base, status="NOT_STARTED", session_counts=False, rd5_permitted=None, line_ends=False,
                    reason="exploration never started: this session does not count; it may be repaired and run (decision 1)")
    if mech["verdict"] == "MECHANISM_FAILS":
        return dict(base, status="LINE_ENDS_MECHANISM_FAILED", session_counts=True, rd5_permitted=False, line_ends=True,
                    reason="the mechanism check failed and rd4 has no verified crossing (or higher): the line ends after rd4")
    return dict(base, status="RD5_LAST_SESSION", session_counts=True, rd5_permitted=True, line_ends=False,
                reason=("no verified crossing in rd4 (" + ("INCOMPLETE counts as one of the two once exploration has started; " if outcome == "INCOMPLETE" else "")
                        + ("the mechanism check is not evaluable; " if mech["verdict"] == "NOT_EVALUABLE" else "the mechanism check holds; ")
                        + "rd5 may be proposed as the last session; the line ends if there is no verified qualified crossing (or higher) by the end of rd5)"))


def apply(*, invalid: Sequence[str], incomplete: Sequence[str], m: int, t: int, prior: Mapping[str, Any], returns: int, seen_ge_8: int, new_cells: int, below_floor: int, dispatches: int,
          fatal_returns: int, launch_capable_created: int, bound_violations: int = 0, top_level_median_L: Optional[int] = None, claims_verified: bool = True,
          exploration_started: bool = True, exploration_ticks: Optional[int] = None, extra: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    if not 0 <= int(m) < len(LADDER) or int(m) == 1:
        raise ValueError(f"m {m} is not a level rd4 claims (0, 2, 3 or 4)")
    if not 0 <= int(t) <= 10:
        raise ValueError(f"t {t} is not a target count")
    for name, v in (("below_floor", below_floor), ("dispatches", dispatches), ("fatal_returns", fatal_returns), ("launch_capable_created", launch_capable_created),
                    ("bound_violations", bound_violations)):
        if int(v) < 0:
            raise ValueError(f"{name} {v} is negative")
    if below_floor > dispatches or fatal_returns > returns:
        raise ValueError("a count exceeds its total")
    pm: Dict[str, int] = {}
    for key in ("rd1", "rd2", "rd3"):
        rec = prior.get(key)
        if not isinstance(rec, Mapping) or not isinstance(rec.get("m"), int) or isinstance(rec.get("m"), bool) or not 0 <= rec["m"] < len(LADDER):
            raise ValueError(f"the recorded milestone of {key} is not available: {rec!r}")
        pm[key] = int(rec["m"])
    mech = mechanism(returns=returns, seen_ge_8=seen_ge_8, new_cells=new_cells)
    dil = rule2.dilution(below_floor, dispatches, fatal_returns, returns)
    rec_out: Dict[str, Any] = {"rule": RULE_ID, "rule_sha256": rule_digest(), "scope": SCOPE, "m": int(m), "milestone": LADDER[int(m)], "highest_milestone": LADDER[int(m)],
                               "max_targets_verified": int(t), "claims_verified": bool(claims_verified), "exploration_started": bool(exploration_started),
                               "prior_sessions": {k: {"m": v, "milestone": LADDER[v]} for k, v in pm.items()},
                               "highest_milestone_over_sessions": LADDER[max(max(pm.values()), int(m))], "invalid": list(invalid), "incomplete": list(incomplete),
                               "mechanism": mech, "dilution": dict(dil, reported_only=True), "launch_capable_created": int(launch_capable_created),
                               "launch_capable_per_1000_returns": rule2.rate_per_1000(launch_capable_created, returns),
                               "rd1_launch_capable_per_1000": rule2.rate_per_1000(rule2.RD1["launch_capable_cells"], rule2.RD1["returns"]),
                               "flags": ["BOUND_VIOLATION"] if bound_violations else [], "bound_violations": int(bound_violations)}
    if invalid:
        out = "INVALID"
    elif incomplete:
        out = "INCOMPLETE"
    elif int(m) >= PROGRESS_MIN_M:
        out = "PROGRESS"
    else:
        out = "NO_NEW_MILESTONE"
    rec_out["outcome"] = out
    rec_out["progress_basis"] = [f"milestone:{LADDER[int(m)]}"] if int(m) >= PROGRESS_MIN_M else []
    rec_out["line"] = line_status(outcome=out, m=int(m), mech=mech, exploration_started=bool(exploration_started), exploration_ticks=exploration_ticks)
    stops: Dict[str, Dict[str, Any]] = {
        "S3": {"triggered": bool(top_level_median_L is not None and top_level_median_L > TOP_LEVEL_MEDIAN_L_LIMIT and int(m) < 3), "note": f"median L of the top level's eligible cells: {top_level_median_L}"},
        "S5": {"triggered": bool(bound_violations), "note": f"{bound_violations} bound violations"},
        "S7": {"triggered": out in ("INVALID", "INCOMPLETE"), "note": "repair and a new approval; never an extension or an automatic retry"}}
    rec_out["stops"] = stops
    rec_out["any_stop"] = [k for k, v in stops.items() if v["triggered"]]
    rec_out["next"] = rec_out["line"]["reason"]
    if rec_out["any_stop"]:
        rec_out["next"] += f"; stop conditions {rec_out['any_stop']} are reported for review"
    if extra:
        rec_out["extra"] = dict(extra)
    return rec_out


def self_test() -> List[str]:
    problems: List[str] = []

    def expect(cond: bool, msg: str) -> None:
        if not cond:
            problems.append(msg)

    prior: Dict[str, Any] = {"rd1": {"m": 0}, "rd2": {"m": 1}, "rd3": {"m": 0}}
    base: Dict[str, Any] = dict(invalid=[], incomplete=[], m=0, t=7, prior=prior, returns=4000, seen_ge_8=1600, new_cells=7000, below_floor=0, dispatches=4000, fatal_returns=0,
                                launch_capable_created=30)
    # the outcome table: PROGRESS only for m >= 2; a higher target count or a wall-top landing is not progress
    expect(apply(**base)["outcome"] == "NO_NEW_MILESTONE", "m 0 -> NO_NEW_MILESTONE")
    for t in range(0, 11):
        expect(apply(**dict(base, t=t))["outcome"] == "NO_NEW_MILESTONE" and apply(**dict(base, t=t))["max_targets_verified"] == t, f"t={t} is reported, never progress")
    for m, name in ((2, "crossing"), (3, "left_target"), (4, "clear")):
        r = apply(**dict(base, m=m))
        expect(r["outcome"] == "PROGRESS" and r["progress_basis"] == [f"milestone:{name}"] and r["highest_milestone"] == name, f"m={m} -> PROGRESS {name}")
    for bad in (dict(base, m=1), dict(base, m=5), dict(base, m=-1), dict(base, t=11), dict(base, below_floor=5000), dict(base, fatal_returns=4001), dict(base, seen_ge_8=4001)):
        try:
            apply(**bad)
            expect(False, f"{ {k: bad[k] for k in ('m', 't', 'below_floor', 'fatal_returns', 'seen_ge_8')} } should be refused")
        except ValueError:
            pass
    # precedence, exhaustive over (m, invalid, incomplete)
    for m in (0, 2, 3, 4):
        for inv in (False, True):
            for inc in (False, True):
                want = "INVALID" if inv else "INCOMPLETE" if inc else "PROGRESS" if m >= 2 else "NO_NEW_MILESTONE"
                got = apply(**dict(base, m=m, invalid=["i"] if inv else [], incomplete=["c"] if inc else []))["outcome"]
                expect(got == want, f"outcome table at {(m, inv, inc)}: {got} vs {want}")
    # the mechanism check: exact boundaries (45.0 % and 1.74 hold; one more fails)
    expect(mechanism(returns=1000, seen_ge_8=450, new_cells=1740)["verdict"] == "MECHANISM_HOLDS", "exactly 45.0 % and exactly 1.74 hold")
    expect(mechanism(returns=1000, seen_ge_8=451, new_cells=1740)["verdict"] == "MECHANISM_FAILS", "45.1 % fails")
    expect(mechanism(returns=1000, seen_ge_8=450, new_cells=1739)["verdict"] == "MECHANISM_FAILS", "1.739 fails")
    expect(mechanism(returns=1000, seen_ge_8=451, new_cells=1739)["verdict"] == "MECHANISM_FAILS", "both fail")
    expect(mechanism(returns=4194, seen_ge_8=1802, new_cells=7309)["verdict"] == "MECHANISM_HOLDS", "rd3's own realised values hold (1,802 of 4,194 = 43.0 %, 7,309 new cells = 1.743 per return)")
    expect(mechanism(returns=4194, seen_ge_8=1820, new_cells=7309)["seen_ok"] is True and mechanism(returns=4194, seen_ge_8=1888, new_cells=7309)["seen_ok"] is False, "the share boundary at 4,194 returns")
    expect(mechanism(returns=0, seen_ge_8=0, new_cells=0)["verdict"] == "NOT_EVALUABLE", "no returns: not evaluable")
    m = mechanism(returns=4000, seen_ge_8=1700, new_cells=7000)
    expect(m["seen_ge_8_share"] == 0.425 and m["new_cells_per_return"] == 1.75 and m["seen_ok"] and m["new_cells_ok"], "the recorded shares")
    # the line budget (decisions 1 and 7)
    ok_mech = mechanism(returns=1000, seen_ge_8=300, new_cells=2000)
    bad_mech = mechanism(returns=1000, seen_ge_8=600, new_cells=2000)
    low_cells = mechanism(returns=1000, seen_ge_8=300, new_cells=1000)
    r = apply(**dict(base, m=0, seen_ge_8=1000, new_cells=8000))
    expect(r["line"]["status"] == "RD5_LAST_SESSION" and r["line"]["rd5_permitted"] is True and not r["line"]["line_ends"], "NO_NEW_MILESTONE with the mechanism holding: rd5 is the last session")
    r = apply(**dict(base, m=0, seen_ge_8=2000))
    expect(r["line"]["status"] == "LINE_ENDS_MECHANISM_FAILED" and r["line"]["line_ends"] and r["line"]["rd5_permitted"] is False, "a failed share ends the line")
    r = apply(**dict(base, m=0, new_cells=1000))
    expect(r["line"]["line_ends"] and r["mechanism"]["new_cells_ok"] is False, "a failed new-cell rate ends the line")
    for m_ in (2, 3, 4):
        r = apply(**dict(base, m=m_, seen_ge_8=3000, new_cells=100))
        expect(r["outcome"] == "PROGRESS" and r["line"]["status"] == "MILESTONE_VERIFIED" and r["line"]["rd5_permitted"] and not r["line"]["line_ends"] and r["mechanism"]["verdict"] == "MECHANISM_FAILS",
               f"a verified milestone outranks a failed mechanism (m={m_})")
    r = apply(**dict(base, m=0, incomplete=["x"]))
    expect(r["outcome"] == "INCOMPLETE" and r["line"]["session_counts"] is True and r["line"]["rd5_permitted"] is True and r["line"]["status"] == "RD5_LAST_SESSION", "INCOMPLETE counts as one of the two")
    r = apply(**dict(base, m=0, incomplete=["x"], seen_ge_8=2000))
    expect(r["line"]["line_ends"], "INCOMPLETE with a failed mechanism and no crossing ends the line")
    r = apply(**dict(base, m=0, incomplete=["x"], seen_ge_8=2000, exploration_ticks=1_999_999))
    expect(r["line"]["line_ends"] and r["line"]["provisional"] is True and r["line"]["exploration_ticks"] == 1_999_999, "a status read from fewer than 2,000,000 ticks is flagged provisional (and still applied as written)")
    expect(apply(**dict(base, m=0, exploration_ticks=2_000_000))["line"]["provisional"] is False and apply(**base)["line"]["provisional"] is False, "provisional only below the validity floor")
    r = apply(**dict(base, m=2, incomplete=["x"]))
    expect(r["outcome"] == "INCOMPLETE" and r["line"]["status"] == "MILESTONE_VERIFIED" and r["highest_milestone"] == "crossing", "a verified crossing in an INCOMPLETE session is still reported and outranks the mechanism")
    r = apply(**dict(base, m=0, incomplete=["x"], exploration_started=False, returns=0, seen_ge_8=0, new_cells=0, dispatches=0))
    expect(r["line"]["status"] == "NOT_STARTED" and r["line"]["session_counts"] is False and r["mechanism"]["verdict"] == "NOT_EVALUABLE", "exploration never started: the session does not count")
    r = apply(**dict(base, m=0, returns=0, seen_ge_8=0, new_cells=0, dispatches=0))
    expect(r["line"]["status"] == "RD5_LAST_SESSION" and "not evaluable" in r["line"]["reason"], "no returns but exploration started: not evaluable, not a failure")
    r = apply(**dict(base, m=2, invalid=["x"]))
    expect(r["outcome"] == "INVALID" and r["line"]["status"] == "REPAIR_NEEDED" and r["line"]["rd5_permitted"] is None and r["line"]["session_counts"] is None, "INVALID: repair, budget not guessed")
    expect(r["stops"]["S7"]["triggered"], "S7 on INVALID")
    # reported only: dilution
    r = apply(**dict(base, below_floor=2000))
    expect(r["dilution"]["verdict"] == "DILUTION_PERSISTS" and r["dilution"]["reported_only"] and r["outcome"] == "NO_NEW_MILESTONE" and not r["line"]["line_ends"], "dilution is reported and guards nothing")
    # stops
    expect(apply(**dict(base, top_level_median_L=3001))["stops"]["S3"]["triggered"] and not apply(**dict(base, top_level_median_L=3000))["stops"]["S3"]["triggered"], "S3 is strict")
    expect(not apply(**dict(base, m=3, top_level_median_L=3500))["stops"]["S3"]["triggered"], "S3 not triggered once a left target exists")
    r = apply(**dict(base, bound_violations=2))
    expect(r["flags"] == ["BOUND_VIOLATION"] and r["stops"]["S5"]["triggered"], "S5")
    # the prior sessions are read, never defaulted
    for badp in ({"rd1": {"m": 0}, "rd2": {"m": 1}}, {"rd1": {"m": 0}, "rd2": {"m": 1}, "rd3": None}, {"rd1": {"m": "0"}, "rd2": {"m": 1}, "rd3": {"m": 0}},
                 {"rd1": {"m": True}, "rd2": {"m": 1}, "rd3": {"m": 0}}, {"rd1": {"m": 0}, "rd2": {"m": 5}, "rd3": {"m": 0}}):
        try:
            apply(**dict(base, prior=badp))
            expect(False, f"an unreadable prior {badp} should be refused")
        except ValueError:
            pass
    expect(apply(**base)["highest_milestone_over_sessions"] == "L0" and apply(**dict(base, m=3))["highest_milestone_over_sessions"] == "left_target", "the highest milestone over the sessions")
    expect(len(rule_digest()) == 64 and rule_digest() == rule_digest() and rule_digest() != rule2.rule_digest(), "digest")
    expect(rule_description()["progress"].startswith("m >= 2") and set(rule_description()["stops"]) == set(STOPS), "registered description")
    expect(SEEN_MIN == 8 and SEEN_SHARE_MAX_PER_MILLE == 450 and NEW_CELLS_MIN_PER_100_RETURNS == 174 and MIN_EXPLORATION_TICKS == 2_000_000, "registered thresholds")
    return problems


def main(argv: Optional[Sequence[str]] = None) -> int:
    if not argv or argv[0] != "self-test":
        print(__doc__)
        return 2
    problems = self_test()
    print(json.dumps({"rule": RULE_ID, "digest": rule_digest(), "problems": problems}))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
