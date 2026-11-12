#!/usr/bin/env python3
"""Option D tests (docs/frs_option_d_design_2026-11-11.md section 9). Zero native ticks: no ROM, no game process. Phase 1 covers the
selection (tools/frs/order_select.py) with pure in-process tests and the run 3 manifest check.

    python -B tools/frs/order_search_tests.py            every test
    python -B tools/frs/order_search_tests.py unit       the in-process tests only
    python -B tools/frs/order_search_tests.py <name>...  the named tests
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

assert sys.flags.dont_write_bytecode, "run with python -B"

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
RL = REPO / "rl"
for _p in (RL, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import order_select as osel  # noqa: E402
from infra_testlib import check, run_suite  # noqa: E402

D_MODULES = ("order_select", "order_search", "order_search_tests")
# The run 3 manifest digest (tools/frs/run3_manifest.py) of the frontier code at 73cbde95 (contract run3_select_v4). The manifest hashes
# working-file bytes: the main tree's working copy holds 7 rl/ files with CRLF line endings (the index has LF), a fresh checkout holds
# them with LF. Same content, two digests; both are the frontier code. Any other value means a run 3 file changed.
RUN3_DIGESTS = {"73cbde955079b7abfd5635288d1adfd8511aae7db469deba84ac10d3e1193262": "main tree working copy (7 rl/ files CRLF)",
                "11ec3040c29543072ace9712f0a549660fa0fafe2b17e02b98b833c512307f87": "the same files with LF (fresh checkout)"}


def _refused(fn, *a, **k) -> bool:
    try:
        fn(*a, **k)
    except osel.OrderParamsError:
        return True
    return False


# -- U1: the pace line -------------------------------------------------------------------------------------------------------------------


def unit_u1_pace_line() -> Dict[str, Any]:
    p = osel.OrderParams()
    pace = osel.Pace(p)
    want = [120, 168, 216, 264, 312, 360, 408, 456, 504, 552, 600]
    check(list(pace.lines) == want, f"line(L) at G 480, s 120: {pace.lines}")
    check(all(osel.pace_line(L) == want[L] for L in range(11)), "pace_line defaults")
    for L in range(10):
        check(pace.keeps(L, want[L]) and not pace.keeps(L, want[L] + 1), f"level {L}: kept at line(L), not at line(L) + 1")
    check(pace.line(6) == 408, "the gate M1 = line(6) = 408")
    other = osel.Pace(osel.OrderParams(goal=500, slack=90))
    check(list(other.lines) == [(500 * L) // 10 + 90 for L in range(11)], "G and s are parameters")
    odd = osel.Pace(osel.OrderParams(goal=487, slack=0))
    check(odd.line(3) == (487 * 3) // 10 and odd.line(3) == 146, "integer arithmetic (floor)")
    refusals = {"G 0": dict(goal=0), "G -1": dict(goal=-1), "s -1": dict(slack=-1), "G 480.0": dict(goal=480.0), "s 120.5": dict(slack=120.5),
                "G True": dict(goal=True), "s '120'": dict(slack="120")}
    for name, kw in refusals.items():
        check(_refused(osel.Pace, osel.OrderParams(**kw)), f"refused: {name}")
    check(_refused(osel.pace_line, 11) and _refused(osel.pace_line, -1) and _refused(osel.pace_line, 2.0), "a level outside 0 ... 10 is refused")
    return {"lines": list(pace.lines), "refusals": len(refusals)}


# -- U2 (phase 1 part): the rejected-reach readout ----------------------------------------------------------------------------------------


def unit_u2_rejected_readout() -> Dict[str, Any]:
    pace = osel.Pace(osel.OrderParams())
    rr = pace.rejected
    check(rr.note(6, 409) == 1, "a reach at line(6) + 1 is rejected at level 6 with distance +1")
    rr.note(6, 450)
    rr.note(6, 415)
    rr.note(3, 400)
    check(_raises_value(rr.note, 6, 408), "a reach at line(L) is not a rejected reach")
    night = rr.summary()
    check(night["6"] == {"count": 3, "earliest_tick": 409, "distance": 1}, f"level 6: count 3, earliest the minimum (409, +1): {night['6']}")
    check(night["3"] == {"count": 1, "earliest_tick": 400, "distance": 136}, f"level 3: {night['3']}")
    hour = rr.snapshot()
    check(hour == night, "the first period equals the night so far")
    rr.note(6, 430)
    check(rr.snapshot() == {"6": {"count": 1, "earliest_tick": 430, "distance": 22}} and rr.summary()["6"]["count"] == 4,
          "the period resets at each snapshot; the night accumulates")
    fresh = osel.Pace(osel.OrderParams())
    check(all(fresh.keeps(L, t) == pace.keeps(L, t) for L in range(10) for t in (0, 100, 408, 409, 600)),
          "the readout enters no keep rule (the same answers with and without rejected reaches noted)")
    return {"night": rr.summary()}


def _raises_value(fn, *a) -> bool:
    try:
        fn(*a)
    except ValueError:
        return True
    return False


# -- U9: claims -------------------------------------------------------------------------------------------------------------------------


def unit_u9_claims() -> Dict[str, Any]:
    check(osel.claim_wanted(906, 907) and not osel.claim_wanted(907, 907) and not osel.claim_wanted(950, 907),
          "a clear is claimed only when faster than the frontier's best")
    check(osel.claim_wanted(700, 907), "a clear past line(10) = 600 is still claimed when faster than the frontier's best (U2)")
    check(_refused(osel.claim_wanted, 500, None) and _refused(osel.claim_wanted, 500, 0) and _refused(osel.claim_wanted, 500, 907.0),
          "the threshold is a positive integer read at the plan")
    return {"threshold": 907}


# -- U10: parameters ---------------------------------------------------------------------------------------------------------------------


def unit_u10_params() -> Dict[str, Any]:
    p = osel.OrderParams()
    p.check()
    check((p.goal, p.slack, p.level_weights, p.breadth_share, p.retire_after) == (480, 120, (0.4, 0.3, 0.2, 0.1), 0.2, 300),
          f"the decided defaults: {p}")
    refusals = {
        "weights sum 0.9": dict(level_weights=(0.4, 0.3, 0.2)),
        "weights sum 1.1": dict(level_weights=(0.5, 0.3, 0.2, 0.1)),
        "a negative weight": dict(level_weights=(1.1, -0.1)),
        "the deepest weight 0": dict(level_weights=(0.0, 1.0)),
        "no weight": dict(level_weights=()),
        "R 0": dict(retire_after=0),
        "R 300.0": dict(retire_after=300.0),
        "breadth -0.1": dict(breadth_share=-0.1),
        "breadth 1.1": dict(breadth_share=1.1),
    }
    for name, kw in refusals.items():
        check(_refused(osel.OrderParams(**kw).check), f"refused: {name}")
    for ok in (dict(breadth_share=0.0), dict(breadth_share=1.0), dict(retire_after=1), dict(level_weights=(1.0,))):
        osel.OrderParams(**ok).check()
    f0 = osel.params_fingerprint(p)
    check(f0 == osel.params_fingerprint(osel.OrderParams()) and len(f0) == 64, "the fingerprint is a function of the parameters")
    changed = {name: osel.params_fingerprint(osel.OrderParams(**kw)) for name, kw in
               {"slack": dict(slack=121), "R": dict(retire_after=299), "weights": dict(level_weights=(0.4, 0.3, 0.1, 0.2)),
                "breadth": dict(breadth_share=0.25)}.items()}
    check(all(f != f0 for f in changed.values()) and len(set(changed.values())) == len(changed), "every parameter changes the fingerprint")
    check(p.as_record()["level_weights"] == [0.4, 0.3, 0.2, 0.1], "the record is JSON-ready")
    return {"fingerprint": f0[:16], "refusals": len(refusals)}


# -- T-M1: the run 3 manifest is untouched by D's files --------------------------------------------------------------------------------------


def unit_tm1_run3_digest() -> Dict[str, Any]:
    r = subprocess.run([sys.executable, "-B", str(HERE / "run3_manifest.py")], cwd=str(REPO), capture_output=True, text=True, timeout=300)
    check(r.returncode == 0, f"run3_manifest exit {r.returncode}: {r.stderr[-400:]}")
    m = json.loads(r.stdout)
    names = set(m.get("entries") or []) | {Path(k).stem for k in (m.get("manifest") or {})}
    leaked = sorted(set(D_MODULES) & names)
    check(not leaked, f"D's modules are not in the run 3 manifest: {leaked}")
    check(m["files"] == 54, f"the run 3 manifest still has 54 files ({m['files']})")
    check(m["digest"] in RUN3_DIGESTS, f"the run 3 digest {m['digest']} is the frontier code's (73cbde95, or the same files with LF)")
    return {"digest": m["digest"][:16], "which": RUN3_DIGESTS[m["digest"]], "files": m["files"]}


UNIT = {"unit_u1_pace_line": unit_u1_pace_line, "unit_u2_rejected_readout": unit_u2_rejected_readout, "unit_u9_claims": unit_u9_claims,
        "unit_u10_params": unit_u10_params, "unit_tm1_run3_digest": unit_tm1_run3_digest}

if __name__ == "__main__":
    args = sys.argv[1:]
    groups = {"unit": UNIT}
    tests = dict(groups[args[0]]) if args[:1] and args[0] in groups else dict(UNIT)
    rest = [x for x in args if x not in groups]
    sys.exit(run_suite("option D tests", tests, rest))
