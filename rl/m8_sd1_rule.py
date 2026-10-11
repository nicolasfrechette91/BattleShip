#!/usr/bin/env python3
"""M8-sd1: the registered rule `m8_sd1_rule_v1` (pure; no game, no numpy, no torch).

One session, one set of keyed draws, NO control arm: a search for trajectories, not a policy result. The rule reads only quantities verified before it is applied:

    the verified clears   every sd1 pool candidate whose fresh-process replay from tick 0 is EXACT (the native action digest, every consumed tick, the break table, the four clear
                          facts, and the replay's completion_input_tick equal to the candidate's registered clear tick); the best is the one with the smallest completion_input_tick
    T_rec                 the archive's best verified clear before sd1 (rd4's: completion_input_tick 2,315, completion_time_passed 2,314), pinned at the open; never an online claim
    M                     the registered margin, 24 ticks (about 1 % of T_rec rounded up to a whole tick; it exceeds the longest explorer hold and the jump buffer)

    INVALID               any integrity failure (evaluated first)
    INCOMPLETE            not a performance result (evaluated second)
    PROGRESS              a verified clear with completion_input_tick <= T_rec - M (= 2,291); the fastest one is the result and the new reference
    RECORD_BELOW_MARGIN   no PROGRESS, and a verified clear with T_rec - M < completion_input_tick < T_rec: the new reference, not progress
    NO_SHORTER_CLEAR      otherwise

The clock that defines "shorter" is `completion_input_tick`, the clock the replay truth measures (one submitted word per consumed tick); `completion_time_passed` is reported beside it
and the two are never collapsed. The reported TIERS are derived from the record reference alone (floor(0.95 T_rec) = 2,199, floor(0.90 T_rec) = 2,083) or are round reporting
thresholds (2,000); they are reported only, and `outcome_of` has no access to them (a static test asserts it).

THE LINE (decided 2026-10-11): sd1 is one session. After PROGRESS or RECORD_BELOW_MARGIN an sd2 under the same design with the new record reference may be proposed (its own
authorisation); after NO_SHORTER_CLEAR an sd2 may be proposed only with a stated reason read from the diagnostics; an INCOMPLETE session counts as sd1 once exploration has started
(a repeat is then sd2, with its reason stated), and does not count before exploration started; an INVALID session is a repair and a new approval, and whether it counts is the user's
decision (recorded as None, never guessed). No third session without a review. The sd line is separate from the rd line: sd1 neither consumes nor grants rd5 (rd4's record leaves
rd5 "permitted, not started", and that status is copied through unchanged).

Stops carried: S5 (BOUND_VIOLATION: the bound is withdrawn under a new contract) and S7 (INVALID or INCOMPLETE: repair and a new approval; never an extension or an automatic retry).
S3 (horizon pressure) is reported only. There is no mechanism check and no dilution guard (the dilution verdict is reported only). Flags: BOUND_VIOLATION; INHERITED_REPLAY_INEXACT
(an inherited descriptive replay that did not reproduce: reported, never an outcome input).

    python rl/m8_sd1_rule.py self-test
"""
from __future__ import annotations

import hashlib
import inspect
import json
import math
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

import m8_rd2_rule as rule2

RULE_ID = "m8_sd1_rule_v1"
SCOPE = ("M8-sd1: first time-directed continuation of archive m8_rd_a1 (rd1, rd2, rd3 and rd4 as closed) under m8_rd_select_v4 (m8_rd_select_v3 with two registered changes: the "
         "length-factor scale and a record bound on eligibility); one session, one set of keyed draws; no control arm; a search for trajectories, not a policy result, not a learning "
         "result, not a comparison of v4 with v3")
T_REC = 2315                                        # the archive's best verified clear before sd1: completion_input_tick (rd4 claim t, cid 239, iteration 11286)
T_REC_TIME_PASSED = 2314                            # its completion_time_passed, reported beside it, never collapsed with it
MARGIN = 24                                         # ticks; about 1 % of T_REC rounded up (23.15 -> 24)
PROGRESS_BAR = T_REC - MARGIN                        # 2,291
TIER_FRACTIONS = (("5_percent", 0.95), ("10_percent", 0.90))
TIER_ROUND = 2000
MIN_EXPLORATION_TICKS = rule2.MIN_EXPLORATION_TICKS  # 2,000,000
MAX_LIFECYCLE_FAILURES = rule2.MAX_LIFECYCLE_FAILURES
TOP_LEVEL_MEDIAN_L_LIMIT = rule2.TOP_LEVEL_MEDIAN_L_LIMIT
OUTCOMES = ("INVALID", "INCOMPLETE", "PROGRESS", "RECORD_BELOW_MARGIN", "NO_SHORTER_CLEAR")
STOPS = ("S3", "S5", "S7")
FLAGS = ("BOUND_VIOLATION", "INHERITED_REPLAY_INEXACT")
LINE_STATUSES = ("REPAIR_NEEDED", "NOT_STARTED", "COUNTED_INCOMPLETE", "SD2_PROPOSABLE_NEW_REFERENCE", "SD2_PROPOSABLE_WITH_REASON")
LINE = "sd1 is one session; after PROGRESS or RECORD_BELOW_MARGIN an sd2 under the same design with the new record reference may be proposed (its own authorisation); after NO_SHORTER_CLEAR " \
       "an sd2 may be proposed only with a stated reason read from the diagnostics; an INCOMPLETE session counts as sd1 once exploration has started; INVALID is a repair and a new approval " \
       "and whether it counts is the user's decision; no third session without a review; sd1 neither consumes nor grants rd5"


def tiers_for(t_rec: int) -> Dict[str, Any]:
    """The reported tiers, from the record reference alone (and one round threshold): floor(0.95 T_rec), floor(0.90 T_rec), 2,000."""
    out: Dict[str, Any] = {name: int(math.floor(frac * int(t_rec))) for name, frac in TIER_FRACTIONS}
    out["round_2000"] = TIER_ROUND
    out["derivation"] = {"5_percent": "floor(0.95 x T_rec)", "10_percent": "floor(0.90 x T_rec)", "round_2000": "a round reporting threshold"}
    out["reported_only"] = True
    return out


TIERS = tiers_for(T_REC)                            # 2,199 / 2,083 / 2,000


def rule_description() -> Dict[str, Any]:
    return {"rule": RULE_ID, "order": list(OUTCOMES), "control_arm": False,
            "record_reference": {"completion_input_tick": T_REC, "completion_time_passed": T_REC_TIME_PASSED, "pinned": "at the open, from the archive's best verified clear (rd4 claim t, cid 239, "
                                 "iteration 11286); never an online claim; never moved during the session"},
            "margin": MARGIN, "progress_bar": f"completion_input_tick <= T_rec - M = {PROGRESS_BAR}",
            "measure": "the replay's completion_input_tick (one submitted word per consumed tick); completion_time_passed reported beside it, never collapsed, never decremented",
            "verified_clear": ["a fresh process from tick 0 with all four diagnostics", "native action digest == the candidate's words", "consumed tick i and input tick i + 1 for every i",
                               "break table == the online table", "the four clear facts (end reason clear, native outcome clear, ten targets, both completion clocks)",
                               "completion_input_tick == the candidate's registered clear tick (first.clear)"],
            "progress": f"a verified clear with completion_input_tick <= {PROGRESS_BAR}; the fastest is the result and the new reference",
            "record_below_margin": f"no PROGRESS, and a verified clear with {PROGRESS_BAR} < completion_input_tick < {T_REC}: the new reference, not progress",
            "no_shorter_clear": "otherwise",
            "tiers": {k: TIERS[k] for k in ("5_percent", "10_percent", "round_2000")}, "tiers_note": "reported only; derived from the record reference or round; no selection, claim or outcome reads them",
            "incomplete": [f"exploration below {MIN_EXPLORATION_TICKS:,} native ticks", "a memory, process-count, session-cap or worker-error stop",
                           f"more than {MAX_LIFECYCLE_FAILURES} lifecycle failures", "the open phase (P1, identity replays, the record re-verified) not completed",
                           f"a pool candidate with a registered clear tick <= {PROGRESS_BAR} left unverified at the replay cap before any exact clear replay", "the close identity replays not completed"],
            "invalid": ["a tick-0 / prefix / end / chain mismatch", "a consumed-tick violation", "an inexact replay of a pool candidate, of the record at the open or of an identity cell",
                        "a replayed clear whose completion_input_tick differs from its registered clear tick", "a pin drift", "a provenance or static-guard violation, or any write under another runs/ tree",
                        "any read of fixtures, recordings or the TAS", "a change of an earlier tree (R1) at the open or the close", "a prefix-chain failure at any level",
                        "an open overlay or a ledger rebuild that does not reproduce", "an inherited record fact that differs from the pinned one", "a record without its stamp"],
            "stops": {"S3": f"median L of the top level's eligible cells > {TOP_LEVEL_MEDIAN_L_LIMIT}: REPORTED ONLY (the left target exists)",
                      "S5": "BOUND_VIOLATION: the bound is withdrawn or corrected under a new contract",
                      "S7": "INVALID or INCOMPLETE: repair and a new approval; never an extension or an automatic retry"},
            "flags": list(FLAGS), "inherited_descriptive": "every clear-event trajectory of rd4's registry that no rd4 replay verified, replayed after the pool as a reported fact; never an outcome input; an inexact one raises INHERITED_REPLAY_INEXACT",
            "dilution": {"below_floor_max_per_mille": rule2.BELOW_FLOOR_MAX_PER_MILLE, "fatal_max_per_mille": rule2.FATAL_MAX_PER_MILLE, "note": "reported only: no guard"},
            "mechanism_check": "none", "line": LINE, "rd_line": "unchanged: sd1 neither consumes nor grants rd5; rd4's recorded status is copied through",
            "reads": "the verified clears' clocks and the registered counts only; no diagnostic and no tier enters the outcome"}


def rule_digest() -> str:
    return hashlib.sha256(json.dumps(rule_description(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


# -- the outcome (pure integer arithmetic; no tier, no diagnostic) ---------------------------------------------------------------------------------------


def outcome_of(best_completion_input_tick: Optional[int], t_rec: int, margin: int) -> str:
    """PROGRESS / RECORD_BELOW_MARGIN / NO_SHORTER_CLEAR from the best verified clock alone (None: no verified clear)."""
    if best_completion_input_tick is None:
        return "NO_SHORTER_CLEAR"
    c, t, m = int(best_completion_input_tick), int(t_rec), int(margin)
    if c <= t - m:
        return "PROGRESS"
    if c < t:
        return "RECORD_BELOW_MARGIN"
    return "NO_SHORTER_CLEAR"


def tier_report(completion_input_tick: Optional[int], t_rec: int) -> Dict[str, Any]:
    """Which reported tiers a verified clock reaches (reported only)."""
    tiers = tiers_for(t_rec)
    c = None if completion_input_tick is None else int(completion_input_tick)
    return {"completion_input_tick": c, "tiers": {k: tiers[k] for k in ("5_percent", "10_percent", "round_2000")},
            "reached": {k: (c is not None and c <= tiers[k]) for k in ("5_percent", "10_percent", "round_2000")}, "reported_only": True}


def best_of(verified_clears: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """The fastest verified clear: the smallest completion_input_tick, then the smallest cid."""
    if not verified_clears:
        return None
    return dict(min(verified_clears, key=lambda v: (int(v["completion_input_tick"]), int(v.get("cid", 0)))))


def _check_verified(verified_clears: Sequence[Mapping[str, Any]]) -> None:
    for v in verified_clears:
        for k in ("completion_input_tick", "completion_time_passed"):
            if not isinstance(v.get(k), int) or isinstance(v.get(k), bool) or v[k] <= 0:
                raise ValueError(f"a verified clear without an integer {k}: {v}")
        if "cid" not in v or "native_action_digest" not in v:
            raise ValueError(f"a verified clear without its cid or digest: {v}")


# -- the line -----------------------------------------------------------------------------------------------------------------------------------------------


def line_status(*, outcome: str, exploration_started: bool, exploration_ticks: Optional[int], best: Optional[Mapping[str, Any]], rd4_line: Mapping[str, Any]) -> Dict[str, Any]:
    """The state of the sd line after sd1 and the rd line, unchanged."""
    rd5 = rd4_line.get("rd5_permitted")
    base: Dict[str, Any] = {"line": LINE, "session": "sd1", "exploration_started": bool(exploration_started), "exploration_ticks": exploration_ticks,
                            "provisional": bool(exploration_ticks is not None and int(exploration_ticks) < MIN_EXPLORATION_TICKS),
                            "best_verified": dict(best) if best else None,
                            "rd_line": {"rd5_permitted_before_sd1": rd5, "rd5_permitted_after_sd1": rd5, "consumed_by_sd1": False, "granted_by_sd1": False,
                                        "source": rd4_line.get("source"), "note": "sd1 neither consumes nor grants rd5; rd4's recorded status is copied through unchanged"}}
    if outcome == "INVALID":
        return dict(base, status="REPAIR_NEEDED", session_counts=None, sd2="repair and a new approval; whether this session counts is the user's decision (not guessed here)",
                    new_reference=None, reason="INVALID: repair and a new approval; whether sd1 consumed its session is the user's decision")
    if outcome == "INCOMPLETE":
        if not exploration_started:
            return dict(base, status="NOT_STARTED", session_counts=False, sd2="sd1 may be repaired and run again as sd1 (exploration never started: this session does not count)",
                        new_reference=None, reason="exploration never started: this session does not count; repair and a new approval, then sd1 again")
        return dict(base, status="COUNTED_INCOMPLETE", session_counts=True, new_reference=None,
                    sd2="proposable only with a stated reason read from the diagnostics (the INCOMPLETE's cause is to be stated); a verified clear found before the stop is reported, and whether it becomes the reference is decided with the sd2 proposal",
                    reason="INCOMPLETE after exploration started: it counts as sd1; a repeat is sd2 under the stated-reason rule")
    if outcome in ("PROGRESS", "RECORD_BELOW_MARGIN"):
        return dict(base, status="SD2_PROPOSABLE_NEW_REFERENCE", session_counts=True, new_reference=dict(best) if best else None,
                    sd2="an sd2 under the same design with the new record reference may be proposed (its own authorisation)",
                    reason=f"{outcome}: the best verified clear is the archive's new record reference" + ("" if outcome == "PROGRESS" else " (inside the margin: a new reference, not progress)"))
    return dict(base, status="SD2_PROPOSABLE_WITH_REASON", session_counts=True, new_reference=None,
                sd2="proposable only with a stated reason read from the diagnostics (for example a still under-dispatched fast tail); no third session without a review",
                reason="NO_SHORTER_CLEAR: the reference stays; an sd2 needs a stated diagnostic reason")


# -- the rule ------------------------------------------------------------------------------------------------------------------------------------------------


def apply(*, invalid: Sequence[str], incomplete: Sequence[str], verified_clears: Sequence[Mapping[str, Any]], t_rec: int, t_rec_time_passed: int, margin: int, exploration_started: bool,
          exploration_ticks: Optional[int], returns: int, dispatches: int, below_floor: int, fatal_returns: int, launch_capable_created: int, bound_violations: int = 0,
          top_level_median_L: Optional[int] = None, inherited_descriptive: Sequence[Mapping[str, Any]] = (), rd4_line: Optional[Mapping[str, Any]] = None, claims_verified: bool = True,
          max_targets: Optional[int] = None, t_claimed_online: Optional[int] = None, extra: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    if not isinstance(t_rec, int) or isinstance(t_rec, bool) or t_rec <= 0 or not isinstance(margin, int) or isinstance(margin, bool) or margin < 1 or margin >= t_rec:
        raise ValueError(f"T_rec {t_rec!r} and the margin {margin!r} must be positive integers with the margin below T_rec")
    for name, v in (("returns", returns), ("dispatches", dispatches), ("below_floor", below_floor), ("fatal_returns", fatal_returns), ("launch_capable_created", launch_capable_created),
                    ("bound_violations", bound_violations)):
        if int(v) < 0:
            raise ValueError(f"{name} {v} is negative")
    if below_floor > dispatches or fatal_returns > returns:
        raise ValueError("a count exceeds its total")
    if max_targets is not None and not 0 <= int(max_targets) <= 10:
        raise ValueError(f"max targets {max_targets} is not a target count")
    _check_verified(verified_clears)
    best = best_of(verified_clears)
    rd4_line = dict(rd4_line or {"rd5_permitted": None, "source": None})
    dil = rule2.dilution(below_floor, dispatches, fatal_returns, returns)
    inh = [dict(x) for x in inherited_descriptive]
    flags: List[str] = []
    if bound_violations:
        flags.append("BOUND_VIOLATION")
    if any(not x.get("exact") for x in inh):
        flags.append("INHERITED_REPLAY_INEXACT")
    if invalid:
        out = "INVALID"
    elif incomplete:
        out = "INCOMPLETE"
    else:
        out = outcome_of(None if best is None else int(best["completion_input_tick"]), t_rec, margin)
    rec: Dict[str, Any] = {"rule": RULE_ID, "rule_sha256": rule_digest(), "scope": SCOPE, "outcome": out,
                           "record_reference": {"completion_input_tick": int(t_rec), "completion_time_passed": int(t_rec_time_passed)}, "margin": int(margin), "progress_bar": int(t_rec) - int(margin),
                           "best_verified": best, "verified_clears": sorted((dict(v) for v in verified_clears), key=lambda v: (int(v["completion_input_tick"]), int(v.get("cid", 0)))),
                           "tiers": tier_report(None if best is None else int(best["completion_input_tick"]), t_rec),
                           "claims_verified": bool(claims_verified), "exploration_started": bool(exploration_started), "max_targets_verified": max_targets, "t_claimed_online": t_claimed_online,
                           "invalid": list(invalid), "incomplete": list(incomplete), "flags": flags,
                           "inherited_descriptive": {"replays": inh, "count": len(inh), "exact": sum(1 for x in inh if x.get("exact")), "inexact": sum(1 for x in inh if not x.get("exact")),
                                                     "note": "reported facts only; never an outcome input"},
                           "dilution": dict(dil, reported_only=True), "launch_capable_created": int(launch_capable_created),
                           "launch_capable_per_1000_returns": rule2.rate_per_1000(launch_capable_created, returns), "bound_violations": int(bound_violations), "mechanism_check": None}
    rec["line"] = line_status(outcome=out, exploration_started=bool(exploration_started), exploration_ticks=exploration_ticks, best=best, rd4_line=rd4_line)
    stops: Dict[str, Dict[str, Any]] = {
        "S3": {"triggered": bool(top_level_median_L is not None and int(top_level_median_L) > TOP_LEVEL_MEDIAN_L_LIMIT), "reported_only": True,
               "note": f"median L of the top level's eligible cells: {top_level_median_L} (reported only: the left target exists)"},
        "S5": {"triggered": bool(bound_violations), "reported_only": False, "note": f"{bound_violations} bound violations"},
        "S7": {"triggered": out in ("INVALID", "INCOMPLETE"), "reported_only": False, "note": "repair and a new approval; never an extension or an automatic retry"}}
    rec["stops"] = stops
    rec["any_stop"] = [k for k, v in stops.items() if v["triggered"] and not v["reported_only"]]
    rec["next"] = rec["line"]["reason"]
    if rec["any_stop"]:
        rec["next"] += f"; stop conditions {rec['any_stop']} are reported for review"
    if flags:
        rec["next"] += f"; flags {flags}"
    if extra:
        rec["extra"] = dict(extra)
    return rec


# -- the self-test -------------------------------------------------------------------------------------------------------------------------------------------


def self_test() -> List[str]:
    problems: List[str] = []

    def expect(cond: bool, msg: str) -> None:
        if not cond:
            problems.append(msg)

    expect(T_REC == 2315 and T_REC_TIME_PASSED == 2314 and MARGIN == 24 and PROGRESS_BAR == 2291, "the registered constants")
    expect(TIERS["5_percent"] == 2199 and TIERS["10_percent"] == 2083 and TIERS["round_2000"] == 2000 and TIERS["reported_only"] is True, f"the tiers: {TIERS}")
    expect(tiers_for(1000) == {"5_percent": 950, "10_percent": 900, "round_2000": 2000, "derivation": TIERS["derivation"], "reported_only": True}, "the tiers derive from the reference alone")
    # the outcome boundaries by exact integer arithmetic
    expect(outcome_of(2291, 2315, 24) == "PROGRESS" and outcome_of(2290, 2315, 24) == "PROGRESS" and outcome_of(1, 2315, 24) == "PROGRESS", "at or below the bar: PROGRESS")
    for c in range(2292, 2315):
        expect(outcome_of(c, 2315, 24) == "RECORD_BELOW_MARGIN", f"{c}: RECORD_BELOW_MARGIN")
    expect(outcome_of(2315, 2315, 24) == "NO_SHORTER_CLEAR" and outcome_of(2316, 2315, 24) == "NO_SHORTER_CLEAR" and outcome_of(None, 2315, 24) == "NO_SHORTER_CLEAR", "at or above the record, or none: NO_SHORTER_CLEAR")
    expect(outcome_of(2314, 2315, 1) == "PROGRESS" and outcome_of(2315, 2315, 1) == "NO_SHORTER_CLEAR", "with M = 1 RECORD_BELOW_MARGIN disappears")
    expect(outcome_of(100, 200, 24) == "PROGRESS" and outcome_of(177, 200, 24) == "RECORD_BELOW_MARGIN" and outcome_of(176, 200, 24) == "PROGRESS", "the reference is a parameter")
    sig = inspect.signature(outcome_of)
    expect(list(sig.parameters) == ["best_completion_input_tick", "t_rec", "margin"], "outcome_of reads the clock, the reference and the margin and nothing else")
    src = inspect.getsource(outcome_of)
    expect("tier" not in src.lower() and "TIER" not in src, "outcome_of does not read the tiers")
    # tiers reported
    tr = tier_report(2083, 2315)
    expect(tr["reached"] == {"5_percent": True, "10_percent": True, "round_2000": False} and tr["reported_only"], f"tier report: {tr}")
    expect(tier_report(None, 2315)["reached"] == {"5_percent": False, "10_percent": False, "round_2000": False}, "no clear: no tier")
    # the rule, precedence exhaustive over (best, invalid, incomplete)
    rd4_line = {"rd5_permitted": True, "source": "sessions/rd4/rule.json"}
    vc = lambda c: {"cid": 1, "iteration": 20000, "completion_input_tick": c, "completion_time_passed": c - 1, "native_action_digest": "a" * 64, "words": c}       # noqa: E731
    base: Dict[str, Any] = dict(invalid=[], incomplete=[], verified_clears=[], t_rec=2315, t_rec_time_passed=2314, margin=24, exploration_started=True, exploration_ticks=5_000_000, returns=3000,
                                dispatches=3000, below_floor=100, fatal_returns=200, launch_capable_created=10, rd4_line=rd4_line)
    for best, inv, inc in ((None, False, False), (2291, False, False), (2300, False, False), (2315, False, False), (2291, True, False), (2291, False, True), (None, True, True)):
        want = "INVALID" if inv else "INCOMPLETE" if inc else outcome_of(best, 2315, 24)
        r = apply(**dict(base, verified_clears=[vc(best)] if best else [], invalid=["i"] if inv else [], incomplete=["c"] if inc else []))
        expect(r["outcome"] == want, f"outcome table at {(best, inv, inc)}: {r['outcome']} vs {want}")
    # the best is the smallest clock, then the smallest cid; the record carries every verified clear sorted
    r = apply(**dict(base, verified_clears=[dict(vc(2300), cid=5), dict(vc(2260), cid=9), dict(vc(2260), cid=4)]))
    expect(r["best_verified"]["cid"] == 4 and r["best_verified"]["completion_input_tick"] == 2260 and [v["cid"] for v in r["verified_clears"]] == [4, 9, 5] and r["outcome"] == "PROGRESS", "the best verified clear")
    expect(r["tiers"]["reached"]["5_percent"] is False and r["tiers"]["reached"]["round_2000"] is False, "tiers reported, outcome unchanged")
    expect(r["line"]["status"] == "SD2_PROPOSABLE_NEW_REFERENCE" and r["line"]["new_reference"]["cid"] == 4 and r["line"]["session_counts"] is True, "PROGRESS: sd2 proposable with the new reference")
    r = apply(**dict(base, verified_clears=[vc(2300)]))
    expect(r["outcome"] == "RECORD_BELOW_MARGIN" and r["line"]["status"] == "SD2_PROPOSABLE_NEW_REFERENCE" and r["line"]["new_reference"]["completion_input_tick"] == 2300, "RECORD_BELOW_MARGIN: a new reference, not progress")
    r = apply(**base)
    expect(r["outcome"] == "NO_SHORTER_CLEAR" and r["line"]["status"] == "SD2_PROPOSABLE_WITH_REASON" and r["line"]["new_reference"] is None and r["line"]["session_counts"] is True, "NO_SHORTER_CLEAR: sd2 only with a reason")
    r = apply(**dict(base, verified_clears=[vc(2315)]))
    expect(r["outcome"] == "NO_SHORTER_CLEAR" and r["best_verified"]["completion_input_tick"] == 2315, "a verified clear equal to the record is not shorter")
    r = apply(**dict(base, incomplete=["x"]))
    expect(r["outcome"] == "INCOMPLETE" and r["line"]["status"] == "COUNTED_INCOMPLETE" and r["line"]["session_counts"] is True and r["stops"]["S7"]["triggered"] and r["any_stop"] == ["S7"],
           "INCOMPLETE after exploration started counts")
    r = apply(**dict(base, incomplete=["x"], exploration_started=False, exploration_ticks=0, returns=0, dispatches=0, below_floor=0, fatal_returns=0))
    expect(r["outcome"] == "INCOMPLETE" and r["line"]["status"] == "NOT_STARTED" and r["line"]["session_counts"] is False, "INCOMPLETE before exploration started does not count")
    r = apply(**dict(base, incomplete=["x"], exploration_ticks=1_999_999))
    expect(r["line"]["provisional"] is True and apply(**dict(base, exploration_ticks=2_000_000))["line"]["provisional"] is False, "provisional below the validity floor")
    r = apply(**dict(base, invalid=["x"], verified_clears=[vc(2000)]))
    expect(r["outcome"] == "INVALID" and r["line"]["status"] == "REPAIR_NEEDED" and r["line"]["session_counts"] is None and r["best_verified"]["completion_input_tick"] == 2000, "INVALID: repair, the budget not guessed, the clear still reported")
    # the rd line is copied through unchanged
    for v in (True, False, None):
        r = apply(**dict(base, rd4_line={"rd5_permitted": v, "source": "s"}))
        expect(r["line"]["rd_line"] == {"rd5_permitted_before_sd1": v, "rd5_permitted_after_sd1": v, "consumed_by_sd1": False, "granted_by_sd1": False, "source": "s", "note": r["line"]["rd_line"]["note"]},
               f"rd5 {v} unchanged")
    # inherited descriptive replays: reported, flagged when inexact, never an outcome input
    inh = [{"iteration": 1, "exact": True}, {"iteration": 2, "exact": False, "problems": ["x"]}]
    r = apply(**dict(base, verified_clears=[vc(2291)], inherited_descriptive=inh))
    expect(r["outcome"] == "PROGRESS" and "INHERITED_REPLAY_INEXACT" in r["flags"] and r["inherited_descriptive"]["inexact"] == 1 and r["inherited_descriptive"]["count"] == 2, "an inexact inherited replay is a flag, not an outcome")
    r2 = apply(**dict(base, verified_clears=[vc(2291)], inherited_descriptive=[{"iteration": 1, "exact": True}]))
    expect(r2["outcome"] == r["outcome"] and r2["flags"] == [], "the flag changes nothing else")
    # stops and flags
    r = apply(**dict(base, bound_violations=2))
    expect("BOUND_VIOLATION" in r["flags"] and r["stops"]["S5"]["triggered"] and r["any_stop"] == ["S5"], "S5")
    r = apply(**dict(base, top_level_median_L=3001))
    expect(r["stops"]["S3"]["triggered"] and r["stops"]["S3"]["reported_only"] and r["any_stop"] == [], "S3 is reported only")
    expect(not apply(**dict(base, top_level_median_L=3000))["stops"]["S3"]["triggered"], "S3 is strict")
    # reported only: dilution; no mechanism check
    r = apply(**dict(base, below_floor=2000))
    expect(r["dilution"]["verdict"] == "DILUTION_PERSISTS" and r["dilution"]["reported_only"] and r["outcome"] == "NO_SHORTER_CLEAR" and r["mechanism_check"] is None, "dilution reported, no guard, no mechanism check")
    # refusals
    for bad in (dict(base, margin=0), dict(base, margin=2315), dict(base, t_rec=0), dict(base, below_floor=5000), dict(base, fatal_returns=5000), dict(base, max_targets=11),
                dict(base, verified_clears=[{"cid": 1, "completion_input_tick": "2000", "completion_time_passed": 1999, "native_action_digest": "a" * 64}]),
                dict(base, verified_clears=[{"cid": 1, "completion_input_tick": 2000, "native_action_digest": "a" * 64}])):
        try:
            apply(**bad)
            expect(False, "a malformed input should be refused")
        except ValueError:
            pass
    expect(len(rule_digest()) == 64 and rule_digest() == rule_digest() and rule_digest() != rule2.rule_digest(), "digest")
    d = rule_description()
    expect(d["order"] == list(OUTCOMES) and set(d["stops"]) == set(STOPS) and d["mechanism_check"] == "none" and d["tiers"] == {"5_percent": 2199, "10_percent": 2083, "round_2000": 2000}, "registered description")
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
