#!/usr/bin/env python3
"""M8-rd3: the registered rule `m8_rd3_rule_v1` (pure; no game, no numpy, no torch).

One session, one set of keyed draws, NO control arm: the rule is milestone-only and reads only quantities verified before it is applied:

    m  the highest ladder level (0 none, 1 wall-top landing, 2 qualified crossing, 3 left-target break, 4 clear) held by a fresh-process replay from tick 0, exactly equal
       to its claim, of a trajectory whose qualifying event lies in a burst ingested during rd3. In rd3's engine the wall-top landing (1) is rd2's and is NOT re-claimed (a
       burst that continues from a wall-top prefix would otherwise fail the frozen engine's l0 check): m is 0, 2, 3 or 4
    t  the number of targets broken by the exactly replayed maximum-targets candidate of rd3

    INVALID            any integrity failure (evaluated first)
    INCOMPLETE         not a performance result (evaluated second)
    PROGRESS           m >= 2 (a verified milestone above the wall-top landing, ordered crossing < left target < clear) OR t >= 8
    NO_NEW_MILESTONE   otherwise

A wall-top landing found again (m = 1) is reported and is never PROGRESS: rd2 already holds one. The record reports the highest milestone and the maximum targets, the basis of a
PROGRESS, the dilution verdict (reported with every outcome, never part of the outcome), BOUND_VIOLATION (an orthogonal flag) and the stop conditions S1-S7 carried over from the
proposal and rd2, with S2 (no verified qualified crossing after three sessions) evaluated explicitly from the three sessions' recorded milestones.

    python rl/m8_rd3_rule.py self-test
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

import m8_rd2_rule as rule2

LADDER = rule2.LADDER
RULE_ID = "m8_rd3_rule_v1"
SCOPE = ("M8-rd3: second continuation of archive m8_rd_a1 (rd1 and rd2 as closed) under m8_rd_select_v2; one session, one set of keyed draws; no control arm; "
         "not a policy result, not a learning result, not a comparison of v2 with v1")
PROGRESS_MIN_M = 2                        # above the wall-top landing: crossing (2) < left target (3) < clear (4)
PROGRESS_MIN_TARGETS = 8
MIN_EXPLORATION_TICKS = rule2.MIN_EXPLORATION_TICKS
MAX_LIFECYCLE_FAILURES = rule2.MAX_LIFECYCLE_FAILURES
TOP_LEVEL_MEDIAN_L_LIMIT = rule2.TOP_LEVEL_MEDIAN_L_LIMIT
OUTCOMES = ("INVALID", "INCOMPLETE", "PROGRESS", "NO_NEW_MILESTONE")
STOPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
RD2_LAUNCH_PER_1000 = 122.6158            # rd2's measured value, reported beside rd1's (information only)


def rule_description() -> Dict[str, Any]:
    return {"rule": RULE_ID, "order": list(OUTCOMES), "ladder": list(LADDER), "control_arm": False,
            "m": "the highest milestone (crossing, left target, clear) of an exactly replayed trajectory whose qualifying event lies in a burst ingested during rd3; the wall-top "
                 "landing is rd2's and is not re-claimed in rd3",
            "t": "the targets broken by the exactly replayed maximum-targets candidate of rd3",
            "progress": f"m >= {PROGRESS_MIN_M} (qualified crossing < left target < clear) or t >= {PROGRESS_MIN_TARGETS}; a wall-top landing (m = 1) is never progress",
            "no_new_milestone": "otherwise", "reported": ["highest milestone", "maximum targets verified", "progress basis", "dilution verdict", "BOUND_VIOLATION", "stops S1-S7"],
            "dilution": {"below_floor_max_per_mille": rule2.BELOW_FLOOR_MAX_PER_MILLE, "fatal_max_per_mille": rule2.FATAL_MAX_PER_MILLE,
                         "note": "reported with every outcome; decides only S4 and S6"},
            "rd1_reference": rule2.RD1, "launch_capable": "A2 or A1 cell with y >= 1,639 that was created in rd3, counted in the final archive",
            "incomplete": [f"exploration below {MIN_EXPLORATION_TICKS:,} native ticks", "a memory, process-count, session-cap or worker-error stop",
                           f"more than {MAX_LIFECYCLE_FAILURES} lifecycle failures", "the open phase (P1, identity replays) not completed",
                           "a candidate that could raise m or reach t >= 8 left unverified at the replay cap"],
            "invalid": ["a tick-0 / prefix / end / chain mismatch", "a consumed-tick violation", "an inexact verification replay",
                        "a provenance or static-guard violation, or any write under runs/m8_rd/ or runs/m8_rd_rd2/", "a pin drift",
                        "any read of fixtures, recordings or the TAS", "a change of rd1's or rd2's tree (R1) at the close", "a prefix-property failure at either level",
                        "an open overlay that does not reproduce", "a failed ledger rebuild"],
            "stops": {"S1": "M8-rd1 NULL (not triggered: rd1 PASS)",
                      "S2": "no verified qualified crossing after three sessions (rd1, rd2, rd3): triggered iff rd1, rd2 and rd3 all hold m < 2, rd3 is not INVALID and rd3's claims "
                            "were verified; read from the sessions' recorded files; the line stops for review",
                      "S3": f"median L of the top level's eligible cells > {TOP_LEVEL_MEDIAN_L_LIMIT} before a left target (m < 3): horizon review",
                      "S4": "NO_NEW_MILESTONE with the dilution verdict DILUTION_PERSISTS: v2 failed its own mechanism; revise the selection under a new label",
                      "S5": "BOUND_VIOLATION: the bound is withdrawn or corrected under a new contract",
                      "S6": "NO_NEW_MILESTONE with the dilution verdict DILUTION_REDUCED and launch-capable cells created per 1,000 returns not above rd1's: the bottleneck is the "
                            "explorer or the key; propose a new design",
                      "S7": "INVALID or INCOMPLETE: repair and a new approval; never an extension or an automatic retry"},
            "reads": "verified m and t and the registered counts only; no diagnostic enters the outcome"}


def rule_digest() -> str:
    return hashlib.sha256(json.dumps(rule_description(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def progress_basis(m: int, t: int) -> List[str]:
    out: List[str] = []
    if int(m) >= PROGRESS_MIN_M:
        out.append(f"milestone:{LADDER[int(m)]}")
    if int(t) >= PROGRESS_MIN_TARGETS:
        out.append(f"targets>={PROGRESS_MIN_TARGETS}")
    return out


def _prior_m(prior: Mapping[str, Any], key: str) -> int:
    rec = prior.get(key)
    if not isinstance(rec, Mapping) or not isinstance(rec.get("m"), int) or isinstance(rec.get("m"), bool) or not 0 <= rec["m"] < len(LADDER):
        raise ValueError(f"the recorded milestone of {key} is not available: {rec!r}")
    return int(rec["m"])


def apply(*, invalid: Sequence[str], incomplete: Sequence[str], m: int, t: int, below_floor: int, dispatches: int, fatal_returns: int, returns: int,
          launch_capable_created: int, prior: Mapping[str, Any], bound_violations: int = 0, top_level_median_L: Optional[int] = None,
          claims_verified: bool = True, extra: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    if not 0 <= int(m) < len(LADDER):
        raise ValueError(f"m {m} is not a ladder level")
    if not 0 <= int(t) <= 10:
        raise ValueError(f"t {t} is not a target count")
    for name, v in (("below_floor", below_floor), ("dispatches", dispatches), ("fatal_returns", fatal_returns), ("returns", returns),
                    ("launch_capable_created", launch_capable_created), ("bound_violations", bound_violations)):
        if int(v) < 0:
            raise ValueError(f"{name} {v} is negative")
    if below_floor > dispatches or fatal_returns > returns:
        raise ValueError("a count exceeds its total")
    m1, m2 = _prior_m(prior, "rd1"), _prior_m(prior, "rd2")
    dil = rule2.dilution(below_floor, dispatches, fatal_returns, returns)
    basis = progress_basis(m, t)
    rec: Dict[str, Any] = {"rule": RULE_ID, "rule_sha256": rule_digest(), "scope": SCOPE, "m": int(m), "milestone": LADDER[int(m)], "highest_milestone": LADDER[int(m)],
                           "max_targets_verified": int(t), "progress_basis": basis, "claims_verified": bool(claims_verified),
                           "prior_sessions": {"rd1": {"m": m1, "milestone": LADDER[m1]}, "rd2": {"m": m2, "milestone": LADDER[m2]}},
                           "highest_milestone_over_sessions": LADDER[max(m1, m2, int(m))], "invalid": list(invalid), "incomplete": list(incomplete), "dilution": dil,
                           "launch_capable_created": int(launch_capable_created), "launch_capable_per_1000_returns": rule2.rate_per_1000(launch_capable_created, returns),
                           "rd1_launch_capable_per_1000": rule2.rate_per_1000(rule2.RD1["launch_capable_cells"], rule2.RD1["returns"]),
                           "rd2_launch_capable_per_1000": RD2_LAUNCH_PER_1000, "launch_above_rd1": rule2.launch_above_rd1(launch_capable_created, returns),
                           "flags": ["BOUND_VIOLATION"] if bound_violations else [], "bound_violations": int(bound_violations)}
    if invalid:
        rec["outcome"] = "INVALID"
    elif incomplete:
        rec["outcome"] = "INCOMPLETE"
    elif basis:
        rec["outcome"] = "PROGRESS"
    else:
        rec["outcome"] = "NO_NEW_MILESTONE"
    out = rec["outcome"]
    no_crossing = max(m1, m2, int(m)) < PROGRESS_MIN_M
    s2 = bool(no_crossing and out != "INVALID" and claims_verified)
    stops: Dict[str, Dict[str, Any]] = {
        "S1": {"triggered": False, "note": "M8-rd1 was PASS"},
        "S2": {"triggered": s2, "note": (f"no verified qualified crossing after three sessions: rd1 m={m1}, rd2 m={m2}, rd3 m={int(m)}"
                                        + ("; not evaluable on an INVALID session" if (no_crossing and out == "INVALID") else "")
                                        + ("; not evaluable: rd3's claims were never verified" if (no_crossing and out != "INVALID" and not claims_verified) else "")
                                        if no_crossing else f"a verified milestone at or above the crossing exists (rd1 m={m1}, rd2 m={m2}, rd3 m={int(m)})")},
        "S3": {"triggered": bool(top_level_median_L is not None and top_level_median_L > TOP_LEVEL_MEDIAN_L_LIMIT and m < 3),
               "note": f"median L of the top level's eligible cells: {top_level_median_L}"},
        "S4": {"triggered": out == "NO_NEW_MILESTONE" and dil["verdict"] == "DILUTION_PERSISTS",
               "note": ("v2 failed its own mechanism" if (out == "NO_NEW_MILESTONE" and dil["verdict"] == "DILUTION_PERSISTS")
                        else f"not applicable (outcome {out}; the dilution verdict {dil['verdict']} is reported)")},
        "S5": {"triggered": bool(bound_violations), "note": f"{bound_violations} bound violations"},
        "S6": {"triggered": out == "NO_NEW_MILESTONE" and dil["verdict"] == "DILUTION_REDUCED" and not rec["launch_above_rd1"],
               "note": f"launch-capable cells created per 1,000 returns {rec['launch_capable_per_1000_returns']} against rd1's {rec['rd1_launch_capable_per_1000']}"},
        "S7": {"triggered": out in ("INVALID", "INCOMPLETE"), "note": "repair and a new approval; never an extension or an automatic retry"}}
    rec["stops"] = stops
    rec["any_stop"] = [k for k, v in stops.items() if v["triggered"]]
    if out in ("INVALID", "INCOMPLETE"):
        rec["next"] = "S7: repair and a new approval; no extension, no automatic retry"
    elif rec["any_stop"]:
        rec["next"] = f"stop conditions {rec['any_stop']} stop the line for review"
    else:
        rec["next"] = "a further session may be proposed, authorised separately, with S2-S7 re-evaluated"
    if extra:
        rec["extra"] = dict(extra)
    return rec


def self_test() -> List[str]:
    problems: List[str] = []

    def expect(cond: bool, msg: str) -> None:
        if not cond:
            problems.append(msg)

    prior: Dict[str, Any] = {"rd1": {"m": 0}, "rd2": {"m": 1}}
    base: Dict[str, Any] = dict(invalid=[], incomplete=[], m=0, t=7, below_floor=0, dispatches=4000, fatal_returns=0, returns=4000, launch_capable_created=30, prior=prior)
    # PROGRESS: m >= 2 or t >= 8; the wall-top landing and seven targets are not
    expect(apply(**dict(base, m=1, t=7))["outcome"] == "NO_NEW_MILESTONE", "a wall-top landing and seven targets are no progress")
    for m, name in ((2, "milestone:crossing"), (3, "milestone:left_target"), (4, "milestone:clear")):
        r = apply(**dict(base, m=m))
        expect(r["outcome"] == "PROGRESS" and r["progress_basis"] == [name] and r["highest_milestone"] == LADDER[m], f"m={m} -> PROGRESS {name}")
    for t in range(0, 11):
        r = apply(**dict(base, t=t))
        expect((r["outcome"] == "PROGRESS") == (t >= 8) and r["max_targets_verified"] == t, f"t={t}")
    r = apply(**dict(base, m=3, t=9))
    expect(r["progress_basis"] == ["milestone:left_target", "targets>=8"], f"both bases: {r['progress_basis']}")
    # precedence
    expect(apply(**dict(base, m=4, invalid=["x"], incomplete=["y"]))["outcome"] == "INVALID", "INVALID first")
    expect(apply(**dict(base, m=4, incomplete=["y"]))["outcome"] == "INCOMPLETE", "INCOMPLETE before progress")
    expect(apply(**dict(base, t=10, incomplete=["y"]))["outcome"] == "INCOMPLETE", "INCOMPLETE before a target count")
    # exhaustive and disjoint over (m, t, invalid, incomplete)
    for m in range(5):
        for t in (0, 7, 8, 10):
            for inv in (False, True):
                for inc in (False, True):
                    want = "INVALID" if inv else "INCOMPLETE" if inc else "PROGRESS" if (m >= 2 or t >= 8) else "NO_NEW_MILESTONE"
                    got = apply(**dict(base, m=m, t=t, invalid=["i"] if inv else [], incomplete=["c"] if inc else []))["outcome"]
                    expect(got == want, f"outcome table at {(m, t, inv, inc)}: {got} vs {want}")
    # S2: three sessions, read from the records
    r = apply(**base)
    expect(r["outcome"] == "NO_NEW_MILESTONE" and r["stops"]["S2"]["triggered"] and "S2" in r["any_stop"], "S2 on a NO_NEW_MILESTONE with no crossing anywhere")
    r = apply(**dict(base, m=2))
    expect(not r["stops"]["S2"]["triggered"] and r["outcome"] == "PROGRESS", "S2 not triggered once rd3 holds a crossing")
    r = apply(**dict(base, t=8))
    expect(r["outcome"] == "PROGRESS" and r["stops"]["S2"]["triggered"] and r["any_stop"] == ["S2"], "eight targets without a crossing: PROGRESS and S2 are both reported")
    r = apply(**dict(base, prior={"rd1": {"m": 0}, "rd2": {"m": 2}}))
    expect(not r["stops"]["S2"]["triggered"], "S2 not triggered when an earlier session holds a crossing")
    r = apply(**dict(base, prior={"rd1": {"m": 3}, "rd2": {"m": 1}}))
    expect(not r["stops"]["S2"]["triggered"], "S2 not triggered when rd1 holds a left target")
    r = apply(**dict(base, invalid=["x"]))
    expect(not r["stops"]["S2"]["triggered"] and r["stops"]["S7"]["triggered"], "S2 is not evaluable on an INVALID session")
    r = apply(**dict(base, incomplete=["x"]))
    expect(r["stops"]["S2"]["triggered"] and r["stops"]["S7"]["triggered"], "S2 is evaluated on an INCOMPLETE session's verified claims")
    r = apply(**dict(base, incomplete=["x"], claims_verified=False))
    expect(not r["stops"]["S2"]["triggered"] and r["stops"]["S7"]["triggered"] and r["claims_verified"] is False and "not evaluable" in r["stops"]["S2"]["note"],
           "S2 is not evaluable when rd3's claims were never verified")
    expect(apply(**base)["claims_verified"] is True, "claims_verified defaults to True")
    for bad in ({"rd1": {"m": 0}}, {"rd1": {"m": 0}, "rd2": None}, {"rd1": {"m": "1"}, "rd2": {"m": 1}}, {"rd1": {"m": True}, "rd2": {"m": 1}}, {"rd1": {"m": 5}, "rd2": {"m": 1}}):
        try:
            apply(**dict(base, prior=bad))
            expect(False, f"an unreadable prior {bad} should be refused")
        except ValueError:
            pass
    expect(apply(**base)["highest_milestone_over_sessions"] == "L0" and apply(**dict(base, m=3))["highest_milestone_over_sessions"] == "left_target", "the highest milestone over the sessions")
    # the dilution thresholds, exactly, and S4 / S6 (carried over from rd2, evaluated on NO_NEW_MILESTONE)
    for n, ok in ((420, True), (421, False)):
        expect(apply(**dict(base, below_floor=n))["dilution"]["below_floor_ok"] is ok, f"below-floor {n}/4000")
    for n, ok in ((440, True), (441, False)):
        expect(apply(**dict(base, fatal_returns=n))["dilution"]["fatal_ok"] is ok, f"fatal {n}/4000")
    r = apply(**dict(base, below_floor=2000))
    expect(r["stops"]["S4"]["triggered"] and not r["stops"]["S6"]["triggered"], "S4 on persisting dilution")
    r = apply(**dict(base, m=3, below_floor=2000))
    expect(r["outcome"] == "PROGRESS" and not r["stops"]["S4"]["triggered"] and r["dilution"]["verdict"] == "DILUTION_PERSISTS", "progress with persisting dilution: S4 not applicable")
    r = apply(**dict(base, launch_capable_created=27, returns=4200, dispatches=4200))
    expect(r["stops"]["S6"]["triggered"] and not r["stops"]["S4"]["triggered"], "S6: reduced dilution, launch-capable cells not above rd1's")
    r = apply(**dict(base, launch_capable_created=28, returns=4200, dispatches=4200))
    expect(not r["stops"]["S6"]["triggered"] and r["launch_above_rd1"], "S6 not triggered above rd1")
    # the other stops
    r = apply(**dict(base, m=1, bound_violations=2))
    expect(r["flags"] == ["BOUND_VIOLATION"] and r["stops"]["S5"]["triggered"], "S5 with any outcome")
    expect(apply(**dict(base, top_level_median_L=3001))["stops"]["S3"]["triggered"], "S3 above 3,000 with no left target")
    expect(not apply(**dict(base, m=3, top_level_median_L=3500))["stops"]["S3"]["triggered"], "S3 not triggered once a left target exists")
    expect(not apply(**dict(base, top_level_median_L=3000))["stops"]["S3"]["triggered"], "S3 is strict")
    r = apply(**dict(base, incomplete=["x"]))
    expect(r["stops"]["S7"]["triggered"] and "S7" in r["any_stop"] and not r["stops"]["S1"]["triggered"], "S7")
    # refusals
    for bad in (dict(base, m=5), dict(base, t=11), dict(base, t=-1), dict(base, below_floor=5000), dict(base, fatal_returns=-1)):
        try:
            apply(**bad)
            expect(False, f"{bad} should be refused")
        except ValueError:
            pass
    expect(rule_digest() == rule_digest() and len(rule_digest()) == 64 and rule_digest() != rule2.rule_digest(), "digest")
    expect(rule_description()["progress"].startswith("m >= 2") and PROGRESS_MIN_TARGETS == 8, "registered thresholds")
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
