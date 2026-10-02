#!/usr/bin/env python3
"""M8-rd1: the registered decision rule `m8_rd1_rule_v1` (pure; no game, no numpy, no torch).

Applied once, after the claims of both arms were verified at the comparison point (amendment 1). The rule reads only
verified quantities:  m = the highest milestone level (0 none, 1 wall-top landing, 2 qualified crossing, 3 left-target
break, 4 clear) whose predicate holds for some exactly replayed trajectory of the arm within the comparison point, and
t = the maximum number of targets broken in one exactly replayed trajectory from tick 0 within it.

    INVALID       any integrity failure (evaluated first)
    INCOMPLETE    not a performance result (evaluated second)
    PASS          m(T) > m(C), or m(T) = m(C) and t(T) >= t(C) + 2
    NULL          m(T) < m(C), or m(T) = m(C) and t(T) <= t(C)
    INCONCLUSIVE  otherwise (m equal and t(T) = t(C) + 1)

    python rl/m8_rd_rule.py self-test
"""
from __future__ import annotations

import hashlib
import itertools
import json
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence

LADDER = ("none", "L0", "crossing", "left_target", "clear")
RULE_ID = "m8_rd1_rule_v1"
PASS_MARGIN = 2
MIN_ARM_TICKS = 1_500_000
OUTCOMES = ("INVALID", "INCOMPLETE", "PASS", "NULL", "INCONCLUSIVE")
MAX_LIFECYCLE_FAILURES = 3


def rule_description() -> Dict[str, Any]:
    return {"rule": RULE_ID, "order": list(OUTCOMES), "ladder": list(LADDER), "pass_margin_targets": PASS_MARGIN,
            "pass": "m(T) > m(C), or m(T) = m(C) and t(T) >= t(C) + 2",
            "null": "m(T) < m(C), or m(T) = m(C) and t(T) <= t(C)", "inconclusive": "m equal and t(T) = t(C) + 1",
            "incomplete": [f"either arm below {MIN_ARM_TICKS:,} native ticks (amendment 1: arms are capped at 3,000,000 and "
                           "compared at T = the slower arm's tick count)",
                           "a candidate that could change the outcome was left unverified at the replay cap",
                           "a memory or process-count stop", f"more than {MAX_LIFECYCLE_FAILURES} lifecycle failures in an arm",
                           "a wall, tick or session cap that stopped identity (P1) or the claim verification before it "
                           "finished (read as the replay cap of section 11.2)"],
            "invalid": ["a tick-0 / prefix / end / chain mismatch", "a consumed-tick violation", "an inexact verification replay",
                        "a provenance or static-guard violation", "a pin drift", "any read of fixtures or TAS"],
            "reads": "verified m and t only; no diagnostic enters the rule"}


def rule_digest() -> str:
    return hashlib.sha256(json.dumps(rule_description(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def comparison_point(ticks_T: int, ticks_C: int, minimum: int = MIN_ARM_TICKS) -> Dict[str, Any]:
    """Amendment 1: T = the cumulative native tick count of the slower arm; INCOMPLETE if either arm is below 1,500,000
    (`minimum` is a parameter for the scaled-down tests only; the session uses the default)."""
    point = int(min(ticks_T, ticks_C))
    reasons = [f"arm {a} reached {n:,} native ticks (< {minimum:,})" for a, n in (("T", ticks_T), ("C", ticks_C))
               if n < minimum]
    return {"T": point, "slower": "T" if ticks_T <= ticks_C else "C", "incomplete": reasons}


def label(m_T: int, m_C: int, t_T: int, t_C: int) -> str:
    if m_T > m_C or (m_T == m_C and t_T >= t_C + PASS_MARGIN):
        return "PASS"
    if m_T < m_C or (m_T == m_C and t_T <= t_C):
        return "NULL"
    return "INCONCLUSIVE"


def could_change(m_T: int, m_C: int, t_T: int, t_C: int, max_m_T: int, max_m_C: int) -> bool:
    """True when some milestone outcome of the unverified candidates would give a different label than the current one."""
    labels = {label(a, b, t_T, t_C) for a in range(m_T, max(m_T, max_m_T) + 1) for b in range(m_C, max(m_C, max_m_C) + 1)}
    return len(labels) > 1


def apply(*, invalid: Sequence[str], incomplete: Sequence[str], m_T: int, m_C: int, t_T: int, t_C: int,
          extra: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    for name, v in (("m_T", m_T), ("m_C", m_C)):
        if not 0 <= int(v) < len(LADDER):
            raise ValueError(f"{name} {v} is not a ladder level")
    for name, v in (("t_T", t_T), ("t_C", t_C)):
        if not 0 <= int(v) <= 10:
            raise ValueError(f"{name} {v} is not a target count")
    rec: Dict[str, Any] = {"rule": RULE_ID, "rule_sha256": rule_digest(), "m_T": int(m_T), "m_C": int(m_C), "t_T": int(t_T),
                           "t_C": int(t_C), "milestone_T": LADDER[m_T], "milestone_C": LADDER[m_C],
                           "invalid": list(invalid), "incomplete": list(incomplete)}
    if invalid:
        rec["outcome"] = "INVALID"
    elif incomplete:
        rec["outcome"] = "INCOMPLETE"
    else:
        rec["outcome"] = label(m_T, m_C, t_T, t_C)
        if rec["outcome"] == "PASS":
            if m_T > m_C:
                rec["pass_milestone"] = LADDER[m_T]
            else:
                rec["pass_targets"] = int(t_T) - int(t_C)
    if extra:
        rec["extra"] = dict(extra)
    return rec


def self_test() -> List[str]:
    problems: List[str] = []

    def expect(cond: bool, msg: str) -> None:
        if not cond:
            problems.append(msg)

    # boundaries of the +2 margin and of the milestone comparison
    for m in range(5):
        for t in range(2, 9):
            expect(label(m, m, t + 2, t) == "PASS", f"m={m} t+2 should pass")
            expect(label(m, m, t + 1, t) == "INCONCLUSIVE", f"m={m} t+1 should be inconclusive")
            expect(label(m, m, t, t) == "NULL", f"m={m} equal t should be null")
            expect(label(m, m, t - 1, t) == "NULL", f"m={m} lower t should be null")
        for m2 in range(5):
            if m > m2:
                expect(label(m, m2, 0, 10) == "PASS", f"m {m} > {m2} should pass whatever t")
            if m < m2:
                expect(label(m, m2, 10, 0) == "NULL", f"m {m} < {m2} should be null whatever t")
    # disjoint and exhaustive on the full grid
    for m_T, m_C, t_T, t_C in itertools.product(range(5), range(5), range(11), range(11)):
        labs = [name for name, cond in (
            ("PASS", m_T > m_C or (m_T == m_C and t_T >= t_C + 2)),
            ("NULL", m_T < m_C or (m_T == m_C and t_T <= t_C)),
            ("INCONCLUSIVE", m_T == m_C and t_T == t_C + 1)) if cond]
        expect(len(labs) == 1 and labs[0] == label(m_T, m_C, t_T, t_C), f"not disjoint / exhaustive at {(m_T, m_C, t_T, t_C)}")
    # precedence
    r = apply(invalid=["x"], incomplete=["y"], m_T=4, m_C=0, t_T=10, t_C=0)
    expect(r["outcome"] == "INVALID", "INVALID must come first")
    r = apply(invalid=[], incomplete=["y"], m_T=4, m_C=0, t_T=10, t_C=0)
    expect(r["outcome"] == "INCOMPLETE", "INCOMPLETE must come before PASS")
    r = apply(invalid=[], incomplete=[], m_T=2, m_C=1, t_T=5, t_C=7)
    expect(r["outcome"] == "PASS" and r.get("pass_milestone") == "crossing", "a higher milestone passes with the milestone reading")
    r = apply(invalid=[], incomplete=[], m_T=1, m_C=1, t_T=7, t_C=5)
    expect(r["outcome"] == "PASS" and r.get("pass_targets") == 2, "t + 2 passes with the targets reading")
    # the comparison point (amendment 1)
    cp = comparison_point(3_000_000, 2_400_000)
    expect(cp["T"] == 2_400_000 and cp["slower"] == "C" and not cp["incomplete"], "T is the slower arm")
    cp = comparison_point(1_499_999, 3_000_000)
    expect(cp["T"] == 1_499_999 and len(cp["incomplete"]) == 1, "below 1,500,000 is incomplete")
    cp = comparison_point(1_500_000, 1_500_000)
    expect(not cp["incomplete"], "1,500,000 exactly is valid")
    cp = comparison_point(1_000_000, 1_200_000)
    expect(len(cp["incomplete"]) == 2, "both arms below the minimum are both named")
    # could_change
    expect(not could_change(2, 1, 5, 5, 2, 1), "nothing unverified cannot change the outcome")
    expect(could_change(1, 1, 5, 5, 3, 1), "an unverified higher milestone in T changes NULL to PASS")
    expect(not could_change(4, 1, 5, 5, 4, 3), "T already ahead of any possible control milestone")
    expect(could_change(2, 1, 5, 5, 2, 4), "a higher unverified control milestone changes PASS to NULL")
    expect(not could_change(2, 2, 5, 5, 2, 4), "NULL stays NULL whatever the control's unverified milestone")
    for bad in ((5, 0, 0, 0), (0, 0, 11, 0)):
        try:
            apply(invalid=[], incomplete=[], m_T=bad[0], m_C=bad[1], t_T=bad[2], t_C=bad[3])
            expect(False, f"{bad} should be refused")
        except ValueError:
            pass
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
