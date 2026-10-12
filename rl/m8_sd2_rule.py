#!/usr/bin/env python3
"""M8-sd2: the registered rule `m8_sd2_rule_v1` (pure; no game, no numpy, no torch).

The second time-directed continuation of archive m8_rd_a1 (rd1, rd2, rd3, rd4 and sd1 as closed) under `m8_rd_select_v4` unchanged, with the record reference moved to sd1's
verified clear. One session, one set of keyed draws, NO control arm: a search for trajectories, not a policy result. The rule reads only quantities verified before it is applied:

    the verified clears   every sd2 pool candidate whose fresh-process replay from tick 0 is EXACT (the native action digest, every consumed tick, the break table, the four clear
                          facts, and the replay's completion_input_tick equal to the candidate's registered clear tick); the best is the one with the smallest completion_input_tick
    T_rec                 the archive's best verified clear before sd2 (sd1's: completion_input_tick 2,086, completion_time_passed 2,085), pinned at the open; never an online claim
    M                     the registered margin, 24 ticks (sd1's constant, carried unchanged; it is not re-derived)

    INVALID               any integrity failure (evaluated first)
    INCOMPLETE            not a performance result (evaluated second); before exploration started it does not count (NOT_STARTED), after it counts (COUNTED_INCOMPLETE)
    PROGRESS              a verified clear with completion_input_tick <= T_rec - M (= 2,062); the fastest one is the result and the new reference
    RECORD_BELOW_MARGIN   no PROGRESS, and a verified clear with T_rec - M < completion_input_tick < T_rec: the new reference, not progress
    NO_SHORTER_CLEAR      otherwise

The clock that defines "shorter" is `completion_input_tick`, the clock the replay truth measures (one submitted word per consumed tick); `completion_time_passed` is reported beside it
and the two are never collapsed. The reported TIERS are derived from the record reference alone (floor(0.95 T_rec) = 1,981, floor(0.90 T_rec) = 1,877) or are the round reporting
threshold decided for sd2 (1,800: the stretch tier below the 10 % tier, sd1's role for 2,000); they are reported only, and `outcome_of` has no access to them (a static test asserts it).

THE LINE (decided 2026-10-12): sd2 is the line's second session. EVERY counted outcome ends in a written review before any sd3. After PROGRESS or RECORD_BELOW_MARGIN the best verified
clear is the archive's new record reference and an sd3 under the same design may be proposed only after the review (SD3_AFTER_REVIEW_NEW_REFERENCE); after NO_SHORTER_CLEAR the reference
stays and an sd3 needs the review and a stated reason read from the diagnostics (SD3_AFTER_REVIEW_WITH_REASON); an INCOMPLETE session counts as sd2 once exploration has started
(COUNTED_INCOMPLETE: an sd3 only after a review that states the cause) and does not count before exploration started (NOT_STARTED: sd2 may be repaired and run again as sd2 with a new
approval and a new snapshot, after the recorded procedure); an INVALID session is a repair and a new approval, and whether it counts is the user's decision (recorded as None, never
guessed). The sd line's first session (sd1) is copied through from sd1's own rule record; the rd line is copied through unchanged: sd2 neither consumes nor grants rd5.

Stops carried: S5 (BOUND_VIOLATION: the bound is withdrawn under a new contract) and S7 (INVALID or INCOMPLETE: repair and a new approval; never an extension or an automatic retry).
S3 (horizon pressure) is reported only. There is no mechanism check and no dilution guard (the dilution verdict is reported only). Flags: BOUND_VIOLATION; INHERITED_REPLAY_INEXACT
(an inherited descriptive replay that did not reproduce: reported, never an outcome input).

    python rl/m8_sd2_rule.py self-test
"""
from __future__ import annotations

import hashlib
import inspect
import json
import math
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

import m8_rd2_rule as rule2
import m8_sd1_rule as rule5

RULE_ID = "m8_sd2_rule_v1"
SESSION = "sd2"
PREDECESSOR = "sd1"
SCOPE = ("M8-sd2: second time-directed continuation of archive m8_rd_a1 (rd1, rd2, rd3, rd4 and sd1 as closed) under m8_rd_select_v4 unchanged, with the record reference moved "
         "to sd1's verified clear; one session, one set of keyed draws; no control arm; a search for trajectories, not a policy result, not a learning result, not a comparison "
         "of v4 with anything")
T_REC = 2086                                        # the archive's best verified clear before sd2: completion_input_tick (sd1 candidate 901, kind clear, iteration 15795)
T_REC_TIME_PASSED = 2085                            # its completion_time_passed, reported beside it, never collapsed with it
MARGIN = rule5.MARGIN                               # 24 ticks: sd1's registered constant, carried unchanged (not re-derived)
PROGRESS_BAR = T_REC - MARGIN                        # 2,062
TIER_FRACTIONS = (("5_percent", 0.95), ("10_percent", 0.90))
TIER_ROUND = 1800                                   # the round reporting threshold decided for sd2 (the stretch tier below the 10 % tier)
TIER_ROUND_KEY = f"round_{TIER_ROUND}"
MIN_EXPLORATION_TICKS = rule2.MIN_EXPLORATION_TICKS  # 2,000,000
MAX_LIFECYCLE_FAILURES = rule2.MAX_LIFECYCLE_FAILURES
TOP_LEVEL_MEDIAN_L_LIMIT = rule2.TOP_LEVEL_MEDIAN_L_LIMIT
OUTCOMES = ("INVALID", "INCOMPLETE", "PROGRESS", "RECORD_BELOW_MARGIN", "NO_SHORTER_CLEAR")
STOPS = ("S3", "S5", "S7")
FLAGS = ("BOUND_VIOLATION", "INHERITED_REPLAY_INEXACT")
LINE_STATUSES = ("REPAIR_NEEDED", "NOT_STARTED", "COUNTED_INCOMPLETE", "SD3_AFTER_REVIEW_NEW_REFERENCE", "SD3_AFTER_REVIEW_WITH_REASON")
LINE = ("sd2 is the line's second session; every counted outcome ends in a written review before any sd3; after PROGRESS or RECORD_BELOW_MARGIN the best verified clear is the "
        "archive's new record reference and an sd3 under the same design may be proposed only after the review; after NO_SHORTER_CLEAR the reference stays and an sd3 needs the review "
        "and a stated reason read from the diagnostics; an INCOMPLETE session counts as sd2 once exploration has started (an sd3 only after a review stating the cause) and does not "
        "count before exploration started (repair, a new approval and a new snapshot, then sd2 again); INVALID is a repair and a new approval and whether it counts is the user's "
        "decision; sd2 neither consumes nor grants rd5")
NOT_STARTED_PROCEDURE = ("rename logs/m8_sd2_run/ to logs/m8_sd2_run_not_started_<utc>/; if runs/m8_rd_sd2 was created, rename it to runs/_m8_rd_sd2_not_started_<utc> and back it up as "
                         "its own increment (coverage stays at 0 uncovered; a run tree is never deleted or overwritten); the approval is void: move it into the renamed log folder; a new "
                         "snapshot and a new approval dated the new session date; then sd2 again")


def tiers_for(t_rec: int) -> Dict[str, Any]:
    """The reported tiers, from the record reference alone (and one round threshold): floor(0.95 T_rec), floor(0.90 T_rec), the round threshold."""
    out: Dict[str, Any] = {name: int(math.floor(frac * int(t_rec))) for name, frac in TIER_FRACTIONS}
    out[TIER_ROUND_KEY] = TIER_ROUND
    out["derivation"] = {"5_percent": "floor(0.95 x T_rec)", "10_percent": "floor(0.90 x T_rec)", TIER_ROUND_KEY: "a round reporting threshold (decided 2026-10-12)"}
    out["reported_only"] = True
    return out


TIERS = tiers_for(T_REC)                            # 1,981 / 1,877 / 1,800
TIER_KEYS = ("5_percent", "10_percent", TIER_ROUND_KEY)


def rule_description() -> Dict[str, Any]:
    return {"rule": RULE_ID, "session": SESSION, "predecessor": PREDECESSOR, "order": list(OUTCOMES), "control_arm": False,
            "record_reference": {"completion_input_tick": T_REC, "completion_time_passed": T_REC_TIME_PASSED,
                                 "pinned": "at the open, from the archive's best verified clear (sd1 candidate 901, kind clear, iteration 15795); never an online claim; never moved during the session"},
            "margin": MARGIN, "margin_note": "sd1's registered constant, carried unchanged", "progress_bar": f"completion_input_tick <= T_rec - M = {PROGRESS_BAR}",
            "measure": "the replay's completion_input_tick (one submitted word per consumed tick); completion_time_passed reported beside it, never collapsed, never decremented",
            "verified_clear": ["a fresh process from tick 0 with all four diagnostics", "native action digest == the candidate's words", "consumed tick i and input tick i + 1 for every i",
                               "break table == the online table", "the four clear facts (end reason clear, native outcome clear, ten targets, both completion clocks)",
                               "completion_input_tick == the candidate's registered clear tick (first.clear)"],
            "progress": f"a verified clear with completion_input_tick <= {PROGRESS_BAR}; the fastest is the result and the new reference",
            "record_below_margin": f"no PROGRESS, and a verified clear with {PROGRESS_BAR} < completion_input_tick < {T_REC}: the new reference, not progress",
            "no_shorter_clear": "otherwise",
            "tiers": {k: TIERS[k] for k in TIER_KEYS}, "tiers_note": "reported only; derived from the record reference or round; no selection, claim or outcome reads them",
            "incomplete": [f"exploration below {MIN_EXPLORATION_TICKS:,} native ticks", "a memory, process-count, session-cap or worker-error stop",
                           f"more than {MAX_LIFECYCLE_FAILURES} lifecycle failures", "the open phase (P1, identity replays, the record re-verified) not completed",
                           f"a pool candidate with a registered clear tick <= {PROGRESS_BAR} left unverified at the replay cap before any exact clear replay", "the close identity replays not completed"],
            "incomplete_counts": {"before_exploration_started": "NOT_STARTED: does not count; " + NOT_STARTED_PROCEDURE,
                                  "after_exploration_started": "COUNTED_INCOMPLETE: counts as sd2; an sd3 only after a review that states the cause"},
            "invalid": ["a tick-0 / prefix / end / chain mismatch", "a consumed-tick violation", "an inexact replay of a pool candidate, of the record at the open or of an identity cell",
                        "a replayed clear whose completion_input_tick differs from its registered clear tick", "a pin drift", "a provenance or static-guard violation, or any write under another runs/ tree",
                        "any read of fixtures, recordings or the TAS", "a change of any of the five earlier trees (R1) at the open or the close", "a prefix-chain failure at any level",
                        "an open overlay or a ledger rebuild that does not reproduce", "an inherited record fact that differs from the pinned one", "a record without its stamp"],
            "stops": {"S3": f"median L of the top level's eligible cells > {TOP_LEVEL_MEDIAN_L_LIMIT}: REPORTED ONLY (the left target exists)",
                      "S5": "BOUND_VIOLATION: the bound is withdrawn or corrected under a new contract",
                      "S7": "INVALID or INCOMPLETE: repair and a new approval; never an extension or an automatic retry"},
            "flags": list(FLAGS), "inherited_descriptive": "every clear-event trajectory of sd1's registry that no sd1 replay verified, replayed after the pool as a reported fact; never an outcome input; an inexact one raises INHERITED_REPLAY_INEXACT",
            "dilution": {"below_floor_max_per_mille": rule2.BELOW_FLOOR_MAX_PER_MILLE, "fatal_max_per_mille": rule2.FATAL_MAX_PER_MILLE, "note": "reported only: no guard"},
            "mechanism_check": "none", "line": LINE, "line_statuses": list(LINE_STATUSES), "review": "a written review before any sd3, whatever the counted outcome",
            "sd_line_predecessor": "sd1's recorded line status and whether it counted are copied through from sd1's rule record",
            "rd_line": "unchanged: sd2 neither consumes nor grants rd5; the status sd1 copied through from rd4 is copied through again",
            "reads": "the verified clears' clocks and the registered counts only; no diagnostic and no tier enters the outcome"}


def rule_digest() -> str:
    return hashlib.sha256(json.dumps(rule_description(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


# -- the outcome (pure integer arithmetic; no tier, no diagnostic) ---------------------------------------------------------------------------------------


def outcome_of(best_completion_input_tick: Optional[int], t_rec: int, margin: int) -> str:
    """PROGRESS / RECORD_BELOW_MARGIN / NO_SHORTER_CLEAR from the best verified clock alone (None: no verified clear). The same arithmetic as sd1's (a test asserts it on a grid)."""
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
    return {"completion_input_tick": c, "tiers": {k: tiers[k] for k in TIER_KEYS}, "reached": {k: (c is not None and c <= tiers[k]) for k in TIER_KEYS}, "reported_only": True}


best_of = rule5.best_of                             # the fastest verified clear: the smallest completion_input_tick, then the smallest cid (sd1's, unchanged)
_check_verified = rule5._check_verified


# -- the line -----------------------------------------------------------------------------------------------------------------------------------------------


def line_status(*, outcome: str, exploration_started: bool, exploration_ticks: Optional[int], best: Optional[Mapping[str, Any]], sd1_line: Mapping[str, Any]) -> Dict[str, Any]:
    """The state of the sd line after sd2 (sd1's status copied through) and the rd line, unchanged (sd1's copy of rd4's status copied through again)."""
    rd5 = sd1_line.get("rd5_permitted")
    base: Dict[str, Any] = {"line": LINE, "session": SESSION, "exploration_started": bool(exploration_started), "exploration_ticks": exploration_ticks,
                            "provisional": bool(exploration_ticks is not None and int(exploration_ticks) < MIN_EXPLORATION_TICKS),
                            "best_verified": dict(best) if best else None, "review_required_before_sd3": True,
                            "sd_line": {"sd1_status": sd1_line.get("status"), "sd1_session_counts": sd1_line.get("session_counts"), "source": sd1_line.get("source"),
                                        "note": "sd1's recorded line status, copied through unchanged; sd2 is the line's second session"},
                            "rd_line": {"rd5_permitted_before_sd2": rd5, "rd5_permitted_after_sd2": rd5, "consumed_by_sd2": False, "granted_by_sd2": False,
                                        "source": sd1_line.get("source"), "note": "sd2 neither consumes nor grants rd5; the status sd1 copied through from rd4 is copied through unchanged"}}
    if outcome == "INVALID":
        return dict(base, status="REPAIR_NEEDED", session_counts=None, sd3="repair and a new approval; whether this session counts is the user's decision (not guessed here); no sd3 before the repair is reviewed",
                    new_reference=None, reason="INVALID: repair and a new approval; whether sd2 consumed its session is the user's decision")
    if outcome == "INCOMPLETE":
        if not exploration_started:
            return dict(base, status="NOT_STARTED", session_counts=False, sd3="none: sd2 may be repaired and run again as sd2 (exploration never started: this session does not count); " + NOT_STARTED_PROCEDURE,
                        new_reference=None, reason="exploration never started: this session does not count; repair, a new approval and a new snapshot, then sd2 again")
        return dict(base, status="COUNTED_INCOMPLETE", session_counts=True, new_reference=None,
                    sd3="only after a written review that states the INCOMPLETE's cause; a verified clear found before the stop is reported, and the review decides whether it becomes the reference",
                    reason="INCOMPLETE after exploration started: it counts as sd2; the line has had its two sessions; an sd3 only after a review stating the cause")
    if outcome in ("PROGRESS", "RECORD_BELOW_MARGIN"):
        return dict(base, status="SD3_AFTER_REVIEW_NEW_REFERENCE", session_counts=True, new_reference=dict(best) if best else None,
                    sd3="an sd3 under the same design with the new record reference may be proposed only after a written review (no third session without a review)",
                    reason=f"{outcome}: the best verified clear is the archive's new record reference" + ("" if outcome == "PROGRESS" else " (inside the margin: a new reference, not progress)") + "; the review first")
    return dict(base, status="SD3_AFTER_REVIEW_WITH_REASON", session_counts=True, new_reference=None,
                sd3="only after a written review and with a stated reason read from the diagnostics",
                reason="NO_SHORTER_CLEAR: the reference stays; an sd3 needs the review and a stated diagnostic reason")


# -- the rule ------------------------------------------------------------------------------------------------------------------------------------------------


def apply(*, invalid: Sequence[str], incomplete: Sequence[str], verified_clears: Sequence[Mapping[str, Any]], t_rec: int, t_rec_time_passed: int, margin: int, exploration_started: bool,
          exploration_ticks: Optional[int], returns: int, dispatches: int, below_floor: int, fatal_returns: int, launch_capable_created: int, bound_violations: int = 0,
          top_level_median_L: Optional[int] = None, inherited_descriptive: Sequence[Mapping[str, Any]] = (), sd1_line: Optional[Mapping[str, Any]] = None, claims_verified: bool = True,
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
    sd1_line = dict(sd1_line or {"status": None, "session_counts": None, "rd5_permitted": None, "source": None})
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
    rec["line"] = line_status(outcome=out, exploration_started=bool(exploration_started), exploration_ticks=exploration_ticks, best=best, sd1_line=sd1_line)
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

    expect(T_REC == 2086 and T_REC_TIME_PASSED == 2085 and MARGIN == 24 == rule5.MARGIN and PROGRESS_BAR == 2062, "the registered constants")
    expect(TIERS["5_percent"] == 1981 and TIERS["10_percent"] == 1877 and TIERS["round_1800"] == 1800 and TIERS["reported_only"] is True and TIER_ROUND_KEY == "round_1800", f"the tiers: {TIERS}")
    expect(TIERS["5_percent"] == math.floor(0.95 * T_REC) and TIERS["10_percent"] == math.floor(0.90 * T_REC), "the tiers derive from the reference alone")
    expect(tiers_for(1000) == {"5_percent": 950, "10_percent": 900, "round_1800": 1800, "derivation": TIERS["derivation"], "reported_only": True}, "the tiers derive from the reference alone (parameter)")
    expect(TIERS["5_percent"] > TIERS["10_percent"] > TIERS["round_1800"], "the tiers are ordered: the round tier lies below the 10 % tier")
    # the outcome boundaries by exact integer arithmetic
    expect(outcome_of(2062, 2086, 24) == "PROGRESS" and outcome_of(2061, 2086, 24) == "PROGRESS" and outcome_of(1, 2086, 24) == "PROGRESS", "at or below the bar: PROGRESS")
    for c in range(2063, 2086):
        expect(outcome_of(c, 2086, 24) == "RECORD_BELOW_MARGIN", f"{c}: RECORD_BELOW_MARGIN")
    expect(outcome_of(2086, 2086, 24) == "NO_SHORTER_CLEAR" and outcome_of(2087, 2086, 24) == "NO_SHORTER_CLEAR" and outcome_of(None, 2086, 24) == "NO_SHORTER_CLEAR", "at or above the record, or none: NO_SHORTER_CLEAR")
    expect(outcome_of(2085, 2086, 1) == "PROGRESS" and outcome_of(2086, 2086, 1) == "NO_SHORTER_CLEAR", "with M = 1 RECORD_BELOW_MARGIN disappears")
    expect(outcome_of(100, 200, 24) == "PROGRESS" and outcome_of(177, 200, 24) == "RECORD_BELOW_MARGIN" and outcome_of(176, 200, 24) == "PROGRESS", "the reference is a parameter")
    expect(all(outcome_of(c, t, m) == rule5.outcome_of(c, t, m) for t in (200, 2086, 2315) for m in (1, 24) for c in list(range(t - 60, t + 3)) + [None]), "the same arithmetic as sd1's rule")
    sig = inspect.signature(outcome_of)
    expect(list(sig.parameters) == ["best_completion_input_tick", "t_rec", "margin"], "outcome_of reads the clock, the reference and the margin and nothing else")
    src = inspect.getsource(outcome_of)
    expect("tier" not in src.lower() and "TIER" not in src, "outcome_of does not read the tiers")
    # tiers reported
    tr = tier_report(1877, 2086)
    expect(tr["reached"] == {"5_percent": True, "10_percent": True, "round_1800": False} and tr["reported_only"], f"tier report: {tr}")
    expect(tier_report(1800, 2086)["reached"] == {"5_percent": True, "10_percent": True, "round_1800": True}, "the round tier")
    expect(tier_report(None, 2086)["reached"] == {"5_percent": False, "10_percent": False, "round_1800": False}, "no clear: no tier")
    # the rule, precedence exhaustive over (best, invalid, incomplete)
    sd1_line = {"status": "SD2_PROPOSABLE_NEW_REFERENCE", "session_counts": True, "rd5_permitted": True, "source": "sessions/sd1/rule.json"}
    vc = lambda c: {"cid": 1, "iteration": 20000, "completion_input_tick": c, "completion_time_passed": c - 1, "native_action_digest": "a" * 64, "words": c}       # noqa: E731
    base: Dict[str, Any] = dict(invalid=[], incomplete=[], verified_clears=[], t_rec=2086, t_rec_time_passed=2085, margin=24, exploration_started=True, exploration_ticks=5_000_000, returns=3000,
                                dispatches=3000, below_floor=100, fatal_returns=200, launch_capable_created=10, sd1_line=sd1_line)
    for best, inv, inc in ((None, False, False), (2062, False, False), (2070, False, False), (2086, False, False), (2062, True, False), (2062, False, True), (None, True, True)):
        want = "INVALID" if inv else "INCOMPLETE" if inc else outcome_of(best, 2086, 24)
        r = apply(**dict(base, verified_clears=[vc(best)] if best else [], invalid=["i"] if inv else [], incomplete=["c"] if inc else []))
        expect(r["outcome"] == want, f"outcome table at {(best, inv, inc)}: {r['outcome']} vs {want}")
    # the best is the smallest clock, then the smallest cid; the record carries every verified clear sorted
    r = apply(**dict(base, verified_clears=[dict(vc(2070), cid=5), dict(vc(2030), cid=9), dict(vc(2030), cid=4)]))
    expect(r["best_verified"]["cid"] == 4 and r["best_verified"]["completion_input_tick"] == 2030 and [v["cid"] for v in r["verified_clears"]] == [4, 9, 5] and r["outcome"] == "PROGRESS", "the best verified clear")
    expect(r["tiers"]["reached"] == {"5_percent": False, "10_percent": False, "round_1800": False}, "tiers reported, outcome unchanged")
    expect(r["line"]["status"] == "SD3_AFTER_REVIEW_NEW_REFERENCE" and r["line"]["new_reference"]["cid"] == 4 and r["line"]["session_counts"] is True and r["line"]["review_required_before_sd3"] is True,
           "PROGRESS: the new reference; an sd3 only after the review")
    r = apply(**dict(base, verified_clears=[vc(2070)]))
    expect(r["outcome"] == "RECORD_BELOW_MARGIN" and r["line"]["status"] == "SD3_AFTER_REVIEW_NEW_REFERENCE" and r["line"]["new_reference"]["completion_input_tick"] == 2070, "RECORD_BELOW_MARGIN: a new reference, not progress; the review first")
    r = apply(**base)
    expect(r["outcome"] == "NO_SHORTER_CLEAR" and r["line"]["status"] == "SD3_AFTER_REVIEW_WITH_REASON" and r["line"]["new_reference"] is None and r["line"]["session_counts"] is True, "NO_SHORTER_CLEAR: the review and a reason")
    r = apply(**dict(base, verified_clears=[vc(2086)]))
    expect(r["outcome"] == "NO_SHORTER_CLEAR" and r["best_verified"]["completion_input_tick"] == 2086, "a verified clear equal to the record is not shorter")
    r = apply(**dict(base, incomplete=["x"]))
    expect(r["outcome"] == "INCOMPLETE" and r["line"]["status"] == "COUNTED_INCOMPLETE" and r["line"]["session_counts"] is True and r["stops"]["S7"]["triggered"] and r["any_stop"] == ["S7"],
           "INCOMPLETE after exploration started counts")
    r = apply(**dict(base, incomplete=["x"], exploration_started=False, exploration_ticks=0, returns=0, dispatches=0, below_floor=0, fatal_returns=0))
    expect(r["outcome"] == "INCOMPLETE" and r["line"]["status"] == "NOT_STARTED" and r["line"]["session_counts"] is False and "run again as sd2" in r["line"]["sd3"] and "never deleted" in r["line"]["sd3"],
           "INCOMPLETE before exploration started does not count; the repeat procedure is written")
    r = apply(**dict(base, incomplete=["x"], exploration_ticks=1_999_999))
    expect(r["line"]["provisional"] is True and apply(**dict(base, exploration_ticks=2_000_000))["line"]["provisional"] is False, "provisional below the validity floor")
    r = apply(**dict(base, invalid=["x"], verified_clears=[vc(2000)]))
    expect(r["outcome"] == "INVALID" and r["line"]["status"] == "REPAIR_NEEDED" and r["line"]["session_counts"] is None and r["best_verified"]["completion_input_tick"] == 2000, "INVALID: repair, the budget not guessed, the clear still reported")
    expect(set(r["line"]["status"] for r in (apply(**dict(base, invalid=["x"])), apply(**dict(base, incomplete=["x"], exploration_started=False, exploration_ticks=0, returns=0, dispatches=0, below_floor=0, fatal_returns=0)),
                                              apply(**dict(base, incomplete=["x"])), apply(**dict(base, verified_clears=[vc(2062)])), apply(**base))) == set(LINE_STATUSES), "the five line statuses are all reachable")
    # the sd line and the rd line are copied through unchanged
    for v in (True, False, None):
        r = apply(**dict(base, sd1_line={"status": "S", "session_counts": True, "rd5_permitted": v, "source": "s"}))
        expect(r["line"]["rd_line"] == {"rd5_permitted_before_sd2": v, "rd5_permitted_after_sd2": v, "consumed_by_sd2": False, "granted_by_sd2": False, "source": "s", "note": r["line"]["rd_line"]["note"]},
               f"rd5 {v} unchanged")
        expect(r["line"]["sd_line"]["sd1_status"] == "S" and r["line"]["sd_line"]["sd1_session_counts"] is True, "sd1's line copied through")
    # inherited descriptive replays: reported, flagged when inexact, never an outcome input
    inh = [{"iteration": 1, "exact": True}, {"iteration": 2, "exact": False, "problems": ["x"]}]
    r = apply(**dict(base, verified_clears=[vc(2062)], inherited_descriptive=inh))
    expect(r["outcome"] == "PROGRESS" and "INHERITED_REPLAY_INEXACT" in r["flags"] and r["inherited_descriptive"]["inexact"] == 1 and r["inherited_descriptive"]["count"] == 2, "an inexact inherited replay is a flag, not an outcome")
    r2 = apply(**dict(base, verified_clears=[vc(2062)], inherited_descriptive=[{"iteration": 1, "exact": True}]))
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
    for bad in (dict(base, margin=0), dict(base, margin=2086), dict(base, t_rec=0), dict(base, below_floor=5000), dict(base, fatal_returns=5000), dict(base, max_targets=11),
                dict(base, verified_clears=[{"cid": 1, "completion_input_tick": "2000", "completion_time_passed": 1999, "native_action_digest": "a" * 64}]),
                dict(base, verified_clears=[{"cid": 1, "completion_input_tick": 2000, "native_action_digest": "a" * 64}])):
        try:
            apply(**bad)
            expect(False, "a malformed input should be refused")
        except ValueError:
            pass
    expect(len(rule_digest()) == 64 and rule_digest() == rule_digest() and rule_digest() != rule5.rule_digest() and rule_digest() != rule2.rule_digest(), "digest")
    d = rule_description()
    expect(d["order"] == list(OUTCOMES) and set(d["stops"]) == set(STOPS) and d["mechanism_check"] == "none" and d["tiers"] == {"5_percent": 1981, "10_percent": 1877, "round_1800": 1800}
           and d["line_statuses"] == list(LINE_STATUSES) and d["predecessor"] == "sd1", "registered description")
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
