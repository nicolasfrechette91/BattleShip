#!/usr/bin/env python3
"""M8-rd2: the registered rule `m8_rd2_rule_v1` (pure; no game, no numpy, no torch).

One session, one set of keyed draws, NO control arm: the rule is milestone-only. It reads only quantities verified before it is
applied: m = the highest milestone (0 none, 1 wall-top landing, 2 qualified crossing, 3 left-target break, 4 clear) held by a
fresh-process replay from tick 0, exactly equal to its claim, of a trajectory whose qualifying event lies in a burst ingested during
rd2; and the registered dilution counts.

    INVALID                  any integrity failure (evaluated first)
    INCOMPLETE               not a performance result (evaluated second)
    PROGRESS_CLEAR           m = 4          PROGRESS_LEFT_TARGET  m = 3
    PROGRESS_CROSSING        m = 2          PROGRESS_WALL_TOP     m = 1
    NO_MILESTONE/DILUTION_REDUCED   m = 0, and (a) below-floor dispatches <= 10.5 % of rd2 dispatches and (b) fatal returns <= 11.0 %
                                    of rd2 returns
    NO_MILESTONE/DILUTION_PERSISTS  m = 0 otherwise

BOUND_VIOLATION is an orthogonal flag recorded with any outcome. The dilution verdict is reported with every outcome; it decides only
the stop path. "Progress" is a verified milestone and nothing else: a higher target count, more launch-capable cells or a closer
approach are reported, never progress. Without a control arm a PROGRESS outcome cannot attribute the milestone to v2 rather than to
more returns.

    python rl/m8_rd2_rule.py self-test
"""
from __future__ import annotations

import hashlib
import json
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

LADDER = ("none", "L0", "crossing", "left_target", "clear")
RULE_ID = "m8_rd2_rule_v1"
SCOPE = ("M8-rd2: continuation of archive m8_rd_a1 under m8_rd_select_v2; one session, one set of keyed draws; no control arm; "
         "not a policy result, not a learning result, not a comparison of v2 with v1")
MIN_EXPLORATION_TICKS = 2_000_000
MAX_LIFECYCLE_FAILURES = 3
BELOW_FLOOR_MAX_PER_MILLE = 105          # 10.5 % of rd2 dispatches start below the main floor (y < -2,850) at most
FATAL_MAX_PER_MILLE = 110                # 11.0 % of rd2 returns end in a native fall with no grounded tick at most
# rd1's measured values (docs/rl_m8_rd1_diagnosis_2026-10-02.md, the continuation proposal 4.3): the reference of the diagnostics
RD1 = {"dispatches": 2175, "below_floor": 456, "fatal_returns": 480, "launch_capable_cells": 14, "returns": 2175,
       "step_contact_cells": 32, "max_targets": 7}
OUTCOME_FOR_M = {1: "PROGRESS_WALL_TOP", 2: "PROGRESS_CROSSING", 3: "PROGRESS_LEFT_TARGET", 4: "PROGRESS_CLEAR"}
OUTCOMES = ("INVALID", "INCOMPLETE", "PROGRESS_CLEAR", "PROGRESS_LEFT_TARGET", "PROGRESS_CROSSING", "PROGRESS_WALL_TOP",
            "NO_MILESTONE/DILUTION_REDUCED", "NO_MILESTONE/DILUTION_PERSISTS")
TOP_LEVEL_MEDIAN_L_LIMIT = 3000
STOPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")


def rule_description() -> Dict[str, Any]:
    return {"rule": RULE_ID, "order": list(OUTCOMES), "ladder": list(LADDER), "control_arm": False,
            "m": "the highest milestone of an exactly replayed trajectory whose qualifying event lies in a burst ingested during rd2",
            "no_milestone_labels": {"DILUTION_REDUCED": f"below-floor dispatch share <= {BELOW_FLOOR_MAX_PER_MILLE / 10} % and fatal-return "
                                                         f"share <= {FATAL_MAX_PER_MILLE / 10} %", "DILUTION_PERSISTS": "otherwise"},
            "dilution_counts": {"below_floor": "rd2 dispatches whose start cell's stored position at dispatch has y < -2,850",
                                "fatal_return": "rd2 returns that end in a native fall with no grounded live tick in the burst "
                                                "(the exact ground runs of the rd2 worker; the reach reading is reported beside it)"},
            "rd1_reference": RD1, "launch_capable": "A2 or A1 cell with y >= 1,639 that was created in rd2, counted in the final archive",
            "rd3_requirement": "launch-capable cells created in rd2 per 1,000 rd2 returns strictly above rd1's 14 / 2,175 per 1,000",
            "incomplete": [f"exploration below {MIN_EXPLORATION_TICKS:,} native ticks",
                           "a memory, process-count, session-cap or worker-error stop",
                           f"more than {MAX_LIFECYCLE_FAILURES} lifecycle failures", "the open phase (P1, identity replays) not completed",
                           "a candidate that could raise m left unverified at the replay cap"],
            "invalid": ["a tick-0 / prefix / end / chain mismatch", "a consumed-tick violation", "an inexact verification replay",
                        "a provenance or static-guard violation, or any write under runs/m8_rd/", "a pin drift",
                        "any read of fixtures, recordings or the TAS", "a change of rd1's tree (R1) at the close",
                        "a prefix-property failure", "an open overlay that does not reproduce", "a failed ledger rebuild"],
            "stops": {"S1": "M8-rd1 NULL (not triggered: rd1 PASS)",
                      "S2": "no verified over-wall lineage after three sessions: after a NO_MILESTONE outcome at most one more session "
                            "(rd3) may be proposed under this design; a second NO_MILESTONE stops the line",
                      "S3": f"median L of the top level's eligible cells > {TOP_LEVEL_MEDIAN_L_LIMIT} before a left target (m < 3): horizon "
                            "review (a longer horizon is a new decision and a new label)",
                      "S4": "the outcome is NO_MILESTONE/DILUTION_PERSISTS: v2 failed its own mechanism; revise the selection under a "
                            "new label; no rd3 under v2",
                      "S5": "BOUND_VIOLATION: the bound is withdrawn or corrected under a new contract; no rd3 under v2 unchanged",
                      "S6": "NO_MILESTONE/DILUTION_REDUCED with launch-capable cells created per 1,000 returns not above rd1's: the "
                            "bottleneck is the explorer or the key; propose a new design rather than rd3",
                      "S7": "INVALID or INCOMPLETE: repair and a new approval; never an extension or an automatic retry"},
            "reads": "verified m and the registered counts only; no diagnostic enters the milestone"}


def rule_digest() -> str:
    return hashlib.sha256(json.dumps(rule_description(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def share_ok(count: int, total: int, per_mille_max: int) -> bool:
    """count / total <= per_mille_max / 1000, exactly (integers)."""
    return total > 0 and int(count) * 1000 <= int(per_mille_max) * int(total)


def launch_above_rd1(launch_cells: int, returns: int) -> bool:
    """launch-capable cells per 1,000 returns strictly above rd1's value (14 / 2,175), exactly (integers)."""
    return returns > 0 and int(launch_cells) * RD1["returns"] > RD1["launch_capable_cells"] * int(returns)


def rate_per_1000(count: int, total: int) -> Optional[float]:
    return None if total <= 0 else round(1000.0 * count / total, 4)


def dilution(below_floor: int, dispatches: int, fatal_returns: int, returns: int) -> Dict[str, Any]:
    a = share_ok(below_floor, dispatches, BELOW_FLOOR_MAX_PER_MILLE)
    b = share_ok(fatal_returns, returns, FATAL_MAX_PER_MILLE)
    return {"below_floor": int(below_floor), "dispatches": int(dispatches), "below_floor_share": (below_floor / dispatches) if dispatches else None,
            "fatal_returns": int(fatal_returns), "returns": int(returns), "fatal_share": (fatal_returns / returns) if returns else None,
            "below_floor_ok": a, "fatal_ok": b, "verdict": "DILUTION_REDUCED" if (a and b) else "DILUTION_PERSISTS",
            "rd1": {"below_floor_share": RD1["below_floor"] / RD1["dispatches"], "fatal_share": RD1["fatal_returns"] / RD1["returns"]}}


def apply(*, invalid: Sequence[str], incomplete: Sequence[str], m: int, below_floor: int, dispatches: int, fatal_returns: int,
          returns: int, launch_capable_created: int, bound_violations: int = 0, top_level_median_L: Optional[int] = None,
          extra: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    if not 0 <= int(m) < len(LADDER):
        raise ValueError(f"m {m} is not a ladder level")
    for name, v in (("below_floor", below_floor), ("dispatches", dispatches), ("fatal_returns", fatal_returns), ("returns", returns),
                    ("launch_capable_created", launch_capable_created), ("bound_violations", bound_violations)):
        if int(v) < 0:
            raise ValueError(f"{name} {v} is negative")
    if below_floor > dispatches or fatal_returns > returns:
        raise ValueError("a count exceeds its total")
    dil = dilution(below_floor, dispatches, fatal_returns, returns)
    rec: Dict[str, Any] = {"rule": RULE_ID, "rule_sha256": rule_digest(), "scope": SCOPE, "m": int(m), "milestone": LADDER[int(m)],
                           "invalid": list(invalid), "incomplete": list(incomplete), "dilution": dil,
                           "launch_capable_created": int(launch_capable_created),
                           "launch_capable_per_1000_returns": rate_per_1000(launch_capable_created, returns),
                           "rd1_launch_capable_per_1000": rate_per_1000(RD1["launch_capable_cells"], RD1["returns"]),
                           "rd3_requirement_met": launch_above_rd1(launch_capable_created, returns),
                           "flags": ["BOUND_VIOLATION"] if bound_violations else [], "bound_violations": int(bound_violations)}
    if invalid:
        rec["outcome"] = "INVALID"
    elif incomplete:
        rec["outcome"] = "INCOMPLETE"
    elif m >= 1:
        rec["outcome"] = OUTCOME_FOR_M[int(m)]
    else:
        rec["outcome"] = "NO_MILESTONE/" + dil["verdict"]
    out = rec["outcome"]
    stops: Dict[str, Dict[str, Any]] = {
        "S1": {"triggered": False, "note": "M8-rd1 was PASS"},
        "S2": {"triggered": False, "note": ("a NO_MILESTONE outcome: at most one more session (rd3) may be proposed under this design; "
                                            "a second NO_MILESTONE stops the line") if out.startswith("NO_MILESTONE") else "not applicable"},
        "S3": {"triggered": bool(top_level_median_L is not None and top_level_median_L > TOP_LEVEL_MEDIAN_L_LIMIT and m < 3),
               "note": f"median L of the top level's eligible cells: {top_level_median_L}"},
        "S4": {"triggered": out == "NO_MILESTONE/DILUTION_PERSISTS", "note": "v2 failed its own mechanism" if out == "NO_MILESTONE/DILUTION_PERSISTS"
               else f"not applicable (outcome {out}; the dilution verdict {dil['verdict']} is reported)"},
        "S5": {"triggered": bool(bound_violations), "note": f"{bound_violations} bound violations"},
        "S6": {"triggered": out == "NO_MILESTONE/DILUTION_REDUCED" and not rec["rd3_requirement_met"],
               "note": f"launch-capable cells created per 1,000 returns {rec['launch_capable_per_1000_returns']} against rd1's "
                       f"{rec['rd1_launch_capable_per_1000']}"},
        "S7": {"triggered": out in ("INVALID", "INCOMPLETE"), "note": "repair and a new approval; never an extension or an automatic retry"}}
    rec["stops"] = stops
    rec["any_stop"] = [k for k, v in stops.items() if v["triggered"]]
    if out == "INVALID" or out == "INCOMPLETE":
        rec["next"] = "S7: repair and a new approval; no extension, no automatic retry"
    elif rec["any_stop"]:
        rec["next"] = f"stop conditions {rec['any_stop']} stop the line for review"
    elif out.startswith("PROGRESS"):
        rec["next"] = "an rd3 may be proposed, authorised separately, with S2-S7 re-evaluated"
    else:
        rec["next"] = "rd3 under the same design may be proposed as the last session before S2"
    if extra:
        rec["extra"] = dict(extra)
    return rec


def self_test() -> List[str]:
    problems: List[str] = []

    def expect(cond: bool, msg: str) -> None:
        if not cond:
            problems.append(msg)

    base: Dict[str, Any] = dict(invalid=[], incomplete=[], m=0, below_floor=0, dispatches=4000, fatal_returns=0, returns=4000,
                                launch_capable_created=30)
    # the thresholds, exactly, at the boundary and one step either side
    for n, ok in ((420, True), (421, False)):                      # 10.5 % of 4,000 = 420
        r = apply(**dict(base, below_floor=n))
        expect(r["dilution"]["below_floor_ok"] is ok, f"below-floor {n}/4000: {r['dilution']['below_floor_ok']}")
    for n, ok in ((440, True), (441, False)):                      # 11.0 % of 4,000 = 440
        r = apply(**dict(base, fatal_returns=n))
        expect(r["dilution"]["fatal_ok"] is ok, f"fatal {n}/4000: {r['dilution']['fatal_ok']}")
    expect(apply(**dict(base, below_floor=420, fatal_returns=440))["outcome"] == "NO_MILESTONE/DILUTION_REDUCED", "both at the limit: reduced")
    expect(apply(**dict(base, below_floor=421))["outcome"] == "NO_MILESTONE/DILUTION_PERSISTS", "below-floor over the limit: persists")
    expect(apply(**dict(base, fatal_returns=441))["outcome"] == "NO_MILESTONE/DILUTION_PERSISTS", "fatal over the limit: persists")
    # the ladder
    for m, name in OUTCOME_FOR_M.items():
        expect(apply(**dict(base, m=m))["outcome"] == name, f"m={m} -> {name}")
    # precedence: INVALID, INCOMPLETE, then the milestone
    expect(apply(**dict(base, m=4, invalid=["x"], incomplete=["y"]))["outcome"] == "INVALID", "INVALID first")
    expect(apply(**dict(base, m=4, incomplete=["y"]))["outcome"] == "INCOMPLETE", "INCOMPLETE before progress")
    # disjoint and exhaustive over the counts that matter
    for m in range(5):
        for bf in (0, 420, 421, 4000):
            for fr in (0, 440, 441, 4000):
                outs = [name for name, cond in (
                    *[(OUTCOME_FOR_M[k], m == k) for k in OUTCOME_FOR_M],
                    ("NO_MILESTONE/DILUTION_REDUCED", m == 0 and bf <= 420 and fr <= 440),
                    ("NO_MILESTONE/DILUTION_PERSISTS", m == 0 and not (bf <= 420 and fr <= 440))) if cond]
                r = apply(**dict(base, m=m, below_floor=bf, fatal_returns=fr))
                expect(len(outs) == 1 and outs[0] == r["outcome"], f"not disjoint / exhaustive at {(m, bf, fr)}: {outs} vs {r['outcome']}")
    # the dilution verdict is reported with every outcome and never changes a PROGRESS outcome
    r = apply(**dict(base, m=2, below_floor=4000, fatal_returns=4000))
    expect(r["outcome"] == "PROGRESS_CROSSING" and r["dilution"]["verdict"] == "DILUTION_PERSISTS" and not r["stops"]["S4"]["triggered"],
           "progress with persisting dilution stays progress; S4 is not applicable")
    # the rd3 requirement is strict and exact: 14 / 2,175 per 1,000
    expect(not launch_above_rd1(14, 2175) and launch_above_rd1(15, 2175) and not launch_above_rd1(27, 4200) and launch_above_rd1(28, 4200),
           "launch-capable comparison against rd1 (14 / 2,175)")
    expect(not launch_above_rd1(0, 0), "no returns: never above")
    # the stops
    r = apply(**dict(base, launch_capable_created=27, returns=4200, dispatches=4200))
    expect(r["stops"]["S6"]["triggered"] and r["outcome"] == "NO_MILESTONE/DILUTION_REDUCED" and r["any_stop"] == ["S6"], f"S6: {r['any_stop']}")
    r = apply(**dict(base, launch_capable_created=28, returns=4200, dispatches=4200))
    expect(not r["stops"]["S6"]["triggered"] and "rd3" in r["next"], "S6 not triggered above rd1")
    r = apply(**dict(base, below_floor=2000))
    expect(r["stops"]["S4"]["triggered"] and r["any_stop"] == ["S4"], "S4 on persisting dilution")
    r = apply(**dict(base, m=1, bound_violations=2))
    expect(r["flags"] == ["BOUND_VIOLATION"] and r["stops"]["S5"]["triggered"] and r["outcome"] == "PROGRESS_WALL_TOP", "S5 with any outcome")
    r = apply(**dict(base, top_level_median_L=3001))
    expect(r["stops"]["S3"]["triggered"], "S3 above 3,000 with no left target")
    r = apply(**dict(base, m=3, top_level_median_L=3500))
    expect(not r["stops"]["S3"]["triggered"], "S3 not triggered once a left target exists")
    r = apply(**dict(base, incomplete=["x"]))
    expect(r["stops"]["S7"]["triggered"] and r["any_stop"] == ["S7"], "S7")
    # refusals
    for bad in (dict(base, m=5), dict(base, below_floor=5000), dict(base, fatal_returns=-1)):
        try:
            apply(**bad)
            expect(False, f"{bad} should be refused")
        except ValueError:
            pass
    expect(rule_digest() == rule_digest() and len(rule_digest()) == 64, "digest")
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
