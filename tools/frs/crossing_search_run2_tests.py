#!/usr/bin/env python3
"""Zero-tick tests of crossing search run 2 (tools/frs/crossing_search_run2.py). No game process is started: the real lab import and the real
run 1 folder are read (never written) for the resume checks; the synthetic stub world (rl/m8_rd_stub) stands in for the game in the archive,
policy and end-to-end checks (a synthetic run 1 is made with run 1's own engine, then run 2 resumes from it in a guarded child process). The
test process never arms the lab guard and writes only under temporary folders, which it removes.

    python -B tools/frs/crossing_search_run2_tests.py                 every test
    python -B tools/frs/crossing_search_run2_tests.py real            the real-import checks only (reads <lab root>/import and run 1's folder)
    python -B tools/frs/crossing_search_run2_tests.py stub            the synthetic checks only
    python -B tools/frs/crossing_search_run2_tests.py only <name>     the tests whose name contains <name>
    ... [--lab-root DIR] [--run1 DIR]                                 the lab root and run 1 folder of the real checks (default C:/BattleShip_lab, newest crossing_*)
"""
from __future__ import annotations

import json
import os
import random
import shutil
import sys
import tempfile
import time
import traceback
import types
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

assert sys.flags.dont_write_bytecode, "run with python -B"

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
RL = REPO / "rl"
sys.path.insert(0, str(RL))
sys.path.insert(0, str(HERE))

import crossing_search as cs  # noqa: E402
import crossing_search_run2 as r2  # noqa: E402
import crossing_search_tests as cst  # noqa: E402
import frontier_search_tests as fst  # noqa: E402
import frs_archive as fa  # noqa: E402
import frs_guard as g  # noqa: E402
import frs_run as fr  # noqa: E402
import frs_tests as T  # noqa: E402
import frs_verify as fv  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_stub as stub  # noqa: E402

# The owner's expectations from the run 1 record (docs/frs_crossing_search_2026-10-15.md): test literals only, never read by the search.
EXPECTED_RUN1_BEST = 1429
EXPECTED_RUN1_CELLS = 32744
EXPECTED_RUN1_VERIFIED = 298
EXPECTED_BOUND = EXPECTED_RUN1_BEST - 24 - 1
EXPECTED_REFERENCE = 1885

TESTS: List[Tuple[str, str, Callable[[], Optional[Dict[str, Any]]]]] = []
CREATED: List[Path] = []
LAB = Path(g.DEFAULT_LAB_ROOT)
RUN1: Optional[Path] = None
_REAL: Dict[str, Any] = {}


def real(fn: Callable[[], Optional[Dict[str, Any]]]) -> Callable[[], Optional[Dict[str, Any]]]:
    TESTS.append(("real", fn.__name__, fn))
    return fn


def synthetic(fn: Callable[[], Optional[Dict[str, Any]]]) -> Callable[[], Optional[Dict[str, Any]]]:
    TESTS.append(("stub", fn.__name__, fn))
    return fn


def check(cond: Any, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def tmpdir(tag: str) -> Path:
    p = Path(tempfile.mkdtemp(prefix=f"crossing2_{tag}_"))
    CREATED.append(p)
    return p


def read_jsonl(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def real_plan() -> Dict[str, Any]:
    if not _REAL:
        imp = LAB / "import"
        check((imp / "import_manifest.json").is_file(), f"no lab import at {imp}")
        r1 = RUN1 or r2.default_run1(LAB)
        check(r1 is not None, f"no crossing search output folder under {LAB}")
        _REAL.update(r2.build_plan(LAB, r1, r2.Params2()))
        _REAL["run1_dir"] = r1
    return _REAL


# =============================================================================================================================================
# the real run 1 archive (zero native ticks)
# =============================================================================================================================================


@real
def real_resume_on_run1_archive() -> Dict[str, Any]:
    P = real_plan()
    p, a, R, R1, best, bound = P["plan"], P["archive"], P["R"], P["R1"], P["best"], P["bound"]
    arrival = {int(k): int(v) for k, v in R["arrival"].items()}
    ref_t = int(R["expected"]["completion_input_tick"])
    check(ref_t == EXPECTED_REFERENCE and best["completion_input_tick"] == EXPECTED_RUN1_BEST and bound == EXPECTED_BOUND == p["e7"]["bound_max_L"] and p["e7"]["margin"] == 24
          and p["e7"]["run1_best_completion_input_tick"] == EXPECTED_RUN1_BEST and bound < p["e7"]["bound_run1"], f"the E7 bound {bound} from run 1's best {best['completion_input_tick']}")
    check(best["verified_in_run1"] == EXPECTED_RUN1_VERIFIED and best["arrival"][mcell.TARGETS_TOTAL] == best["completion_input_tick"] and sorted(best["arrival"]) == list(range(mcell.TARGETS_TOTAL + 1)),
          f"the best clear's pace {best['arrival']}")
    check(len(best["words"]) == best["completion_input_tick"] and mcell.words_digest(best["words"]) == best["words_digest"], "the best clear's words")
    # the archive: every final representative of run 1, same ids, one per key, consistent
    check(a.inherited == len(a.cells) == len(R1["final"]) == EXPECTED_RUN1_CELLS == p["archive"]["inherited"], f"{a.inherited} inherited cells")
    keys = set()
    seeds1 = {int(r["fsid"]) for r in R1["seed_rows"]}
    for i, c in enumerate(a.cells):
        r = R1["final"][c.cid]
        check(c.cid == i and c.inherited and not c.verified and c.end == () and c.words is not None, f"cell {c.cid}: inherited, unverified")
        check(len(c.words) == c.tick == int(r["tick"]) and c.digest == r["digest"] == mcell.words_digest(c.words) and c.level == mcell.level_of_mask(c.key[3]) == int(r["level"])
              and c.lead == arrival[c.level] - c.tick == int(r["lead"]) and c.chain.hex() == r["chain"] and c.end_digest.hex() == r["end_digest"], f"cell {c.cid}: words, digests, level, lead")
        check(c.key not in keys, f"cell {c.cid}: a second cell at its key")
        keys.add(c.key)
        check(c.root in seeds1 and c.next_k == 0 and c.fresh == c.dispatched and c.check_attempts == 0, f"cell {c.cid}: root {c.root}, next_k {c.next_k}")
        check(a.eligible(c) == (c.tick <= bound and not (c.cleared and a.p2.cleared_weight <= 0)), f"cell {c.cid}: eligibility at the bound")
    beyond = sum(1 for c in a.cells if c.tick > bound)
    check(beyond > 0 and p["archive"]["eligible"] == sum(1 for c in a.cells if a.eligible(c)) == a.inherited - beyond, f"{beyond} cells beyond the bound are loaded and ineligible")
    pl = p["archive"]["per_level"]
    check(sum(d["eligible"] for d in pl.values()) == p["archive"]["eligible"] and all(d["eligible_verified"] == 0 and d["eligible_unverified"] == d["eligible"] for d in pl.values()), f"per level {pl}")
    # dispatch statistics rebuilt from run 1's dispatch rows: the best clear's cell (record: k 0 and 1) and the totals
    bc = a.cells[best["cid"]]
    check(bc.dispatched == 2 and bc.breaks == 1 and bc.tick == best["start_tick"], f"the best clear's cell: dispatched {bc.dispatched}, breaks {bc.breaks}")
    check(sum(c.dispatched for c in a.cells) <= int(R1["summary"]["work"]["dispatches"]) and sum(c.breaks for c in a.cells) <= int(R1["summary"]["work"]["advanced"]), "the carried-over statistics")
    # cleared starts: every cell with a clear count has a verification row from its tick
    vrows = R1["verifications"]
    for c in a.cells:
        if c.cleared:
            check(any(int(v["cid"]) == c.cid and int(v["start_tick"]) == c.tick for v in vrows), f"cell {c.cid}: cleared {c.cleared} without a verification row")
    check(p["archive"]["cleared_starts"] >= 1 and p["archive"]["cleared_starts_rows"] >= p["archive"]["cleared_starts"], f"cleared starts {p['archive']['cleared_starts']}")
    base_w = cs.Archive.cell_weight(a, bc)
    check(bc.cleared == 1 and a.eligible(bc) and abs(a.cell_weight(bc) / base_w - a.p2.cleared_weight) < 1e-6, f"the best clear's cell carries its clear: cleared {bc.cleared}, weight {a.cell_weight(bc)} vs {base_w}")
    # the pace table: the two deepest live levels, lineages by root seed
    ah = p["archive"]["ahead_of_pace"]
    check(set(ah) == {str(lv) for lv in r2.PACE_LEVELS} and all(d["cells_ahead"] > 0 and d["earliest_tick"] < d["pace_tick"] and all(t["root"] in seeds1 for t in d["top"]) for d in ah.values()), f"ahead of pace {ah}")
    # eager plan: the deepest eligible level (all its eligible cells when the budget allows) plus one canary per level, canaries first
    e = p["eager"]
    deepest = max(int(lv) for lv, d in pl.items() if d["eligible"])
    check(e["levels_deep"] == [deepest] and e["per_level"][str(deepest)] == pl[str(deepest)]["eligible"] and e["truncated"] == 0 and e["estimated_wall_min"] <= e["budget_min"]
          and all(e["per_level"].get(lv, 0) >= 1 for lv, d in pl.items() if d["eligible"]), f"the eager plan {dict((k, v) for k, v in e.items() if k != 'cids')}")
    first = [a.cells[cid] for cid in e["cids"][:len(pl)]]
    check(len({c.level for c in first}) == len([lv for lv, d in pl.items() if d["eligible"]]), "the canaries (one per level) come first")
    # draws: no verified cell yet, so the verified-only draw gives nothing and the plain draw gives unverified eligible cells
    rng = random.Random(3)
    check(a.select2(rng, True) is None, "no verified cell to draw")
    seen_levels = set()
    for _ in range(300):
        pick = a.select2(rng, False)
        check(pick is not None and a.eligible(pick[0]) and not pick[0].verified and pick[1]["verified_only"] is False, "a plain draw")
        seen_levels.add(pick[0].level)
    check(deepest in seen_levels, f"the deepest level is drawn {seen_levels}")
    # the key family differs from run 1's
    did = f"{a.archive_id}|{r2.KEY_FAMILY}|{a.cells[0].digest}"
    check(did != a.cells[0].draw_id(a.archive_id) and r2.KEY_FAMILY != cs.KEY_FAMILY, "a new key family")
    # deterministic plan; the lab code digest is run 1's; the projection
    P2 = r2.build_plan(LAB, P["run1_dir"], r2.Params2())
    check(P2["plan"]["archive_set_digest"] == p["archive_set_digest"] and P2["plan"]["e7"] == p["e7"], "the plan is deterministic")
    dig = fr.code_digest(fr.code_manifest())
    check(dig == p["run1"]["lab_code_digest"] == R1["config"]["lab_code_digest"], f"the lab code digest {dig[:16]} is run 1's")
    proj = r2.projection2(p["throughput_fit"], p["check_fit"], pl, r2.Params2(), 5, 8.0, R1["summary"])
    check(proj["available"] and all(r["dispatches_per_h"] > 0 for r in proj["rows"]) and proj["checks"]["checks_per_h_capacity"] > 0 and proj["memory"]["projected_main_mb"] < proj["memory"]["soft_budget_main_mb"],
          f"the projection {proj}")
    return {"inherited": a.inherited, "eligible": p["archive"]["eligible"], "beyond": beyond, "bound": bound, "best": best["completion_input_tick"], "pace": {k: v for k, v in best["arrival"].items() if k in r2.PACE_LEVELS},
            "per_level_eligible": {lv: d["eligible"] for lv, d in pl.items()}, "eager": {k: v for k, v in e.items() if k != "cids"}, "roots": p["archive"]["roots"],
            "ahead": {lv: (d["cells_ahead"], d["lineages"]) for lv, d in ah.items()}, "projection": {r["burst_workers"]: r["dispatches_per_h"] for r in proj["rows"]},
            "memory_8h": proj["memory"].get("projected_main_mb"), "lab_code_digest": dig[:16]}


# =============================================================================================================================================
# the resumed archive's rules (synthetic keys)
# =============================================================================================================================================


def fake_run1(cells: Sequence[Tuple[int, int, int, int, Optional[Tuple[int, int]]]], arrival: Dict[int, int]) -> Dict[str, Any]:
    """(cid, level, tick, tag, parent (cid, tag) or None) -> read_run1's shape: final rows, origins, dispatch stats (filled by the caller)."""
    final: Dict[int, Dict[str, Any]] = {}
    origins: Dict[Tuple[int, str], Dict[str, Any]] = {}
    for cid, lv, tick, tag, parent in cells:
        words = cst.words_for(tick, tag)
        dg = mcell.words_digest(words)
        if parent is None:
            origin = {"kind": "seed", "fsid": 1000 + cid}
        else:
            origin = {"kind": "burst", "parent": parent[0], "parent_digest": parent[1], "k": 0, "offset": 1, "n": 1}
        final[cid] = {"cid": cid, "key": list(cst.key_of(tag, lv)), "level": lv, "tick": tick, "lead": arrival[lv] - tick, "digest": dg, "end_digest": (b"\x01" * 32).hex(),
                      "chain": (b"\x02" * 32).hex(), "origin": origin, "words_hex": words.hex(), "seen": 2, "replaced": 0}
        origins[(cid, dg)] = origin
    return {"final": final, "origins": origins, "dispatch_stats": {}}


@synthetic
def resumed_archive_rules() -> Dict[str, Any]:
    arrival = {lv: 100 * lv for lv in range(mcell.TARGETS_TOTAL + 1)}
    bound_run1, bound = 1000 - 24 - 1, 800 - 24 - 1
    # cells: a seed at level 7 (tick 500), its child at level 8 (tick 640), a grandchild at level 9 (tick 700), a level-9 cell beyond run 2's bound (900), a second level-8 cell (650)
    d_seed = mcell.words_digest(cst.words_for(500, 1))
    d_child = mcell.words_digest(cst.words_for(640, 2))
    cells = [(0, 7, 500, 1, None), (1, 8, 640, 2, (0, d_seed)), (2, 9, 700, 3, (1, d_child)), (3, 9, 900, 4, (1, d_child)), (4, 8, 650, 5, None)]
    R1 = fake_run1(cells, arrival)
    R1["dispatch_stats"] = {mcell.words_digest(cst.words_for(640, 2)): [5, 2], mcell.words_digest(cst.words_for(700, 3)): [3, 0]}
    cleared = {2: 1}
    for bad in (dict(cleared_weight=1.5), dict(cleared_weight=-0.1), dict(check_slots=0), dict(check_queue_max=0), dict(eager_levels=-1), dict(check_error_limit=-1)):
        try:
            r2.Params2(**bad).check()
            raise AssertionError(f"params {bad} were accepted")
        except cs.SearchError:
            pass
    a = r2.ResumeArchive("arch", arrival, bound, r2.Params2(cleared_weight=0.1, pace_exp=0.0))
    load = a.load_run1(R1, bound_run1, cleared, reset_novelty=False)
    check(load["inherited"] == 5 == len(a.cells) and [c.cid for c in a.cells] == [0, 1, 2, 3, 4] and a.bound == bound and a.counts["new"] == 0, f"loaded {load}")
    c0, c1, c2, c3, c4 = a.cells
    check(all(c.inherited and not c.verified and c.end == () and c.seen == 2 for c in a.cells), "inherited, unverified, seen carried")
    check(c1.dispatched == c1.fresh == 5 and c1.breaks == 2 and c2.dispatched == 3 and c0.dispatched == 0, "dispatch statistics carried over")
    check(c0.root == 1000 and c1.root == 1000 and c2.root == 1000 and c3.root == 1000 and c4.root == 1004 and load["roots"] == 2, f"roots {[c.root for c in a.cells]}")
    check(c2.cleared == 1 and c3.cleared == 0, "cleared starts applied")
    check(not a.eligible(c3) and c3.tick > bound and a.eligible(c0) and a.eligible(c1) and a.eligible(c2) and a.eligible(c4), "a cell beyond run 2's bound is loaded but ineligible")
    check(a.levels_present2(False) == [7, 8, 9] and a.levels_present2(True) == [] and a.select2(random.Random(1), True) is None, "no verified cell yet")
    check(load["per_level"]["9"]["beyond_bound"] == 1 and load["per_level"]["9"]["eligible_unverified"] == 1 and load["per_level"]["8"]["dispatches_run1"] == 5, f"per level {load['per_level']}")
    # reset_novelty: fresh 0, dispatched kept
    b = r2.ResumeArchive("arch", arrival, bound, r2.Params2(reset_novelty=True))
    b.load_run1(R1, bound_run1, {}, reset_novelty=True)
    check(b.cells[1].fresh == 0 and b.cells[1].dispatched == 5, "reset novelty")
    # pending: not drawn; verified: drawn by the verified-only draw; the weight of a cleared cell is a tenth
    rng = random.Random(2)
    a.mark_pending(c0)
    check(not a.eligible(c0) and a.counts["pending"] == 1, "a pending cell is ineligible")
    draws = {}
    for _ in range(400):
        c, d = a.select2(rng, False)
        draws[c.cid] = draws.get(c.cid, 0) + 1
    check(0 not in draws and 3 not in draws and set(draws) <= {1, 2, 4}, f"pending and beyond-bound cells are never drawn {draws}")
    a.mark_verified(c0, cst.obs_for(500))
    check(c0.verified and c0.end == cst.obs_for(500) and a.eligible(c0) and a.dispatchable(c0) and a.counts["pending"] == 0 and a.counts["checked_ok"] == 1, "verified after its check")
    for _ in range(50):
        c, d = a.select2(rng, True)
        check(c is c0 and d["verified_only"] is True and d["level_eligible"] == 1, "the verified-only draw gives the only verified cell")
    a.mark_verified(c1, cst.obs_for(640))
    a.mark_verified(c2, cst.obs_for(700))
    a.mark_verified(c4, cst.obs_for(650))
    c1.fresh = c1.dispatched = c1.breaks = 0
    a.touch(c1)
    n = {}
    for _ in range(6000):
        c, _d = a.select2(rng, True)
        if c.level == 8:
            n[c.cid] = n.get(c.cid, 0) + 1
    check(0.8 < n[1] / n[4] < 1.25, f"two equal level-8 cells {n}")
    a.mark_cleared(c4)
    n = {}
    for _ in range(8000):
        c, _d = a.select2(rng, True)
        if c.level == 8:
            n[c.cid] = n.get(c.cid, 0) + 1
    check(0.06 < n.get(4, 0) / n[1] < 0.15, f"a cleared start is drawn a tenth as often {n}")
    a.mark_cleared(c4)
    check(abs(a.cell_weight(c4) / a.cell_weight(c1) - 0.01) < 0.002, "a hundredth after two clears")
    # cleared_weight 0: never drawn, not eligible; a faster arrival lifts it
    z = r2.ResumeArchive("arch", arrival, bound, r2.Params2(cleared_weight=0.0))
    z.load_run1(R1, bound_run1, {4: 1}, reset_novelty=False)
    check(not z.eligible(z.cells[4]) and z.cells[4].cleared == 1 and z.eligible(z.cells[1]), "a cleared start is retired with cleared_weight 0")
    v, rep = z.keep(cst.key_of(5, 8), 8, 600, cst.words_for(600, 50), cst.obs_for(600), b"\x07" * 32, b"\x08" * 32, {"kind": "burst", "parent": 1, "parent_digest": z.cells[1].digest, "k": 0, "offset": 1, "n": 3}, 3)
    check(v == cs.REPLACED and rep is z.cells[4] and rep.cleared == 0 and rep.verified and not rep.inherited and rep.end == cst.obs_for(600) and z.eligible(rep) and rep.root == 1000
          and z.root_by_rep[(4, rep.digest)] == 1000, "a faster arrival at a cleared key is a fresh, verified start with its parent's root")
    # a faster arrival at a beyond-bound inherited key, within the bound: eligible, verified; a new key: a verified run 2 cell with the parent's root
    v3, c3b = a.keep(cst.key_of(4, 9), 9, 720, cst.words_for(720, 40), cst.obs_for(720), b"\x07" * 32, b"\x08" * 32, {"kind": "burst", "parent": 2, "parent_digest": c2.digest, "k": 1, "offset": 20, "n": 9}, 9)
    check(v3 == cs.REPLACED and c3b is c3 and c3.verified and a.eligible(c3) and c3.tick == 720 and c3.root == 1000 and c3.replaced == 1, "a faster arrival pulls a beyond-bound key into eligibility")
    v5, c5 = a.keep(cst.key_of(9, 9), 9, 730, cst.words_for(730, 41), cst.obs_for(730), b"\x07" * 32, b"\x08" * 32, {"kind": "burst", "parent": 2, "parent_digest": c2.digest, "k": 1, "offset": 30, "n": 9}, 9)
    check(v5 == cs.NEW and c5.cid == 5 and c5.verified and not c5.inherited and c5.root == 1000 and a.eligible(c5) and a.counts["new"] == 1, "a run 2 cell")
    v6, _ = a.keep(cst.key_of(9, 9), 9, bound + 1, cst.words_for(bound + 1, 42), cst.obs_for(1), b"\x07" * 32, b"\x08" * 32, {"kind": "burst", "parent": 2, "parent_digest": c2.digest, "k": 1, "offset": 1, "n": 9}, 9)
    check(v6 == cs.BEYOND, "run 2's bound applies to reaches")
    # quarantine through a check: ineligible, pending lifted
    a.mark_pending(c1)
    a.quarantine(c1, "check: differs")
    check(not a.eligible(c1) and c1.words is None and not c1.pending and a.counts["pending"] == 0, "quarantined by its check")
    # the pace table by root
    ah = a.ahead_of_pace({8: 700, 9: 760})
    # level 9: c2 (inherited), c3 (replaced by a run 2 arrival: a run 2 state) and c5 (new); level 8: c4 only (c1 is quarantined)
    check(ah["9"]["cells_ahead"] == 3 and ah["9"]["lineages"] == 1 and ah["9"]["top"][0]["root"] == 1000 and ah["9"]["found_run2_ahead"] == 2 and ah["8"]["cells_ahead"] == 1
          and ah["8"]["top"][0]["cleared"] == 2, f"ahead of pace {ah}")
    pl = a.per_level2()
    check(pl["8"]["quarantined"] == 1 and pl["9"]["found_run2"] == 2 and pl["9"]["cells"] == 3 and pl["9"]["cleared_starts"] == 1, f"per level {pl}")
    # the bulk digest is run 1's digest on every loaded prefix and on arbitrary words
    for n in (0, 1, 7, 500, 1999):
        w = cst.words_for(n, 11)
        check(r2.words_digest_bulk(w) == mcell.words_digest(w), f"the bulk digest of {n} words")
    try:
        bad = dict(R1, final={0: dict(R1["final"][0], digest="00" * 32)})
        r2.ResumeArchive("arch", arrival, bound, r2.Params2()).load_run1(bad, bound_run1, {}, reset_novelty=False)
        raise AssertionError("a wrong stored digest was loaded")
    except cs.SearchError:
        pass
    return {"draws_level8": n, "ahead": {lv: d["cells_ahead"] for lv, d in ah.items()}}


# =============================================================================================================================================
# the E7 bound and the cleared starts from verification rows; the verify-only-if-faster policy
# =============================================================================================================================================


def vrow(n: int, cid: int, start: int, clock: int, words: bytes, verdict: str = fv.VERIFIED, chain: str = "ab" * 32, k: int = 0, breaks: Optional[List[List[int]]] = None) -> Dict[str, Any]:
    br = breaks if breaks is not None else [[clock - 9 * (mcell.TARGETS_TOTAL - 1 - i), i] for i in range(mcell.TARGETS_TOTAL)]
    return {"kind": "clear", "n": n, "cid": cid, "k": k, "level": 9, "start_tick": start, "words": len(words), "words_hex": words.hex(), "words_digest": mcell.words_digest(words),
            "verdict": verdict, "completion_input_tick": clock, "completion_time_passed": clock - 1, "chain_r1": chain, "chain_r2": chain, "clocks_r1": [clock, clock - 1],
            "clocks_r2": [clock, clock - 1], "breaks_r1": br, "breaks_r2": br, "utc": "2026-10-15T00:00:00Z"}


@synthetic
def bound_and_policy() -> Dict[str, Any]:
    w1, w2, w3 = cst.words_for(900, 1), cst.words_for(880, 2), cst.words_for(870, 3)
    rows = [vrow(1, 5, 850, 900, w1), vrow(2, 6, 860, 880, w2), vrow(3, 7, 861, 870, w3, verdict=fv.NONDETERMINISTIC)]
    b = r2.best_verified_of(rows, 1000)
    check(b["completion_input_tick"] == 880 and b["n"] == 2 and b["words"] == w2 and b["arrival"][mcell.TARGETS_TOTAL] == 880 and len(b["arrival"]) == mcell.TARGETS_TOTAL + 1
          and b["verified_in_run1"] == 2, f"the best VERIFIED clear {b['completion_input_tick']}")
    for bad_rows, why in (([rows[2]], "no VERIFIED row"), (rows[:2], "not faster than the reference"), ([dict(rows[1], chain_r2="00" * 32)], "replays disagree")):
        try:
            r2.best_verified_of(bad_rows, 880 if why.startswith("not faster") else 1000)
            raise AssertionError(f"accepted: {why}")
        except cs.SearchError:
            pass
    check(r2.archive_set_digest({0: {"digest": "a", "tick": 1, "level": 1}}, b, 10) != r2.archive_set_digest({0: {"digest": "a", "tick": 1, "level": 1}}, b, 11), "the bound is in the archive set digest")
    # cleared starts: only rows whose final representative is the start that cleared
    final = {5: {"tick": 850, "digest": mcell.words_digest(w1[:850])}, 6: {"tick": 700, "digest": "x"}, 7: {"tick": 861, "digest": mcell.words_digest(w3[:861])}}
    cl = r2.cleared_starts_of(rows, final)
    check(cl == {5: 1, 7: 1}, f"cleared starts {cl}")
    # the policy: a claim is replayed only when faster than the best; a new best drops queued slower claims
    ns = types.SimpleNamespace(best={"completion_input_tick": 880}, best_history=[], elapsed=lambda: 12.0)
    cand = lambda clock, n=1: {"n": n, "cid": 1, "k": 0, "level": 9, "start_tick": 800, "lead": 1, "words": b"\x00" * clock, "claim": {"words_digest": "d", "completion_input_tick": clock, "completion_time_passed": clock - 1, "chain": None}}
    check(r2.ResumeSearch.should_replay(ns, cand(879)) and not r2.ResumeSearch.should_replay(ns, cand(880)) and not r2.ResumeSearch.should_replay(ns, cand(1000)), "faster only")
    no_clock = {"n": 2, "cid": 1, "k": 0, "level": 9, "start_tick": 800, "lead": 1, "words": b"\x00" * 870, "claim": {"words_digest": "d", "completion_input_tick": None, "completion_time_passed": None, "chain": None}}
    check(r2.ResumeSearch.should_replay(ns, no_clock), "a claim without a native clock is judged by its word count")
    r2.ResumeSearch.set_best(ns, vrow(9, 3, 840, 860, cst.words_for(860, 9)))
    check(ns.best["completion_input_tick"] == 860 and ns.best["source"] == "run2" and ns.best["arrival"][mcell.TARGETS_TOTAL] == 860 and ns.best_history[-1]["gain"] == 20
          and ns.best_history[-1]["previous_best"] == 880, f"the new best {ns.best}")
    check(not r2.ResumeSearch.should_replay(ns, cand(879)) and r2.ResumeSearch.should_replay(ns, cand(859)), "the policy follows the new best")
    # the verdict rows against the reference and the fit helpers
    words, claim = T.stub_clear("easy")
    t = claim["completion_input_tick"]
    row = cs.clear_row({"n": 1, "cid": 1, "k": 0, "level": 9, "start_tick": 1, "lead": 1, "words": words, "claim": claim}, fv.verify_twice(T.stub_replay(), stub.analyse, words, claim, "p", 0), t + 100)
    check(row["verdict"] == fv.VERIFIED and row["gain_vs_reference"] == 100, "a verified row")
    fit = r2.check_fit([{"ok": True, "ticks": 500, "stepping_s": 0.7, "startup_s": 2.0, "wall_s": 3.0}, {"ok": True, "ticks": 1000, "stepping_s": 1.4, "startup_s": 2.0, "wall_s": 3.7},
                        {"ok": True, "ticks": 1500, "stepping_s": 2.1, "startup_s": 2.0, "wall_s": 4.4}])
    check(fit["available"] and abs(fit["s_per_tick"] - 0.0014) < 1e-4 and abs(r2.check_wall_s(fit, 1000) - 3.7) < 0.05, f"the check fit {fit}")
    return {"best": b["completion_input_tick"], "cleared": cl, "new_best": ns.best["completion_input_tick"]}


# =============================================================================================================================================
# the refusals
# =============================================================================================================================================


@synthetic
def refusals() -> Dict[str, Any]:
    lab = tmpdir("lab")
    (lab / "import").mkdir()
    (lab / "import" / "import_manifest.json").write_text("{}", encoding="utf-8")
    run1 = lab / "xrun1"
    for f in r2.RUN1_FILES:
        (run1 / f).parent.mkdir(parents=True, exist_ok=True)
        (run1 / f).write_text("", encoding="utf-8")
    exits = {}
    base = ["plan", "--lab-root", str(lab), "--run1", str(run1)]
    for argv in (base + ["--out", str(REPO / "crossing_x")], base + ["--out", str(lab / "runs" / "x")], base + ["--out", str(run1)], base + ["--out", str(run1 / "run")],
                 base + ["--workers", "6"], base + ["--workers", "2", "--check-slots", "3"], base + ["--check-slots", "0"], base + ["--cleared-weight", "2"], base + ["--eager-levels", "-1"],
                 base + ["--level-decay", "0"], base + ["--max-wall-min", "0"], ["plan", "--lab-root", str(lab), "--run1", str(REPO / "runs" / "x")],
                 ["plan", "--lab-root", str(lab), "--run1", str(lab / "import")], ["plan", "--lab-root", str(lab)], ["plan", "--lab-root", str(REPO / "lab_x")]):
        try:
            cs_code = r2.main(argv)
            raise AssertionError(f"main accepted {argv} ({cs_code})")
        except SystemExit as exc:
            exits[" ".join(argv[1:])[-70:]] = str(exc)[:80]
        check(not g.LabGuard.installed, f"the refusal of {argv[1:]} happened before the guard was armed in this process")
    try:
        r2.read_run1(run1)
        raise AssertionError("an empty run 1 folder was read")
    except (cs.SearchError, ValueError):
        pass
    check(r2.default_run1(lab) is None, "no crossing_* folder")
    return {"main_refusals": len(exits)}


# =============================================================================================================================================
# the synthetic end-to-end: a synthetic run 1 (run 1's own engine in the stub world), then run 2 resumed from it
# =============================================================================================================================================


RUN_CHILD = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, {rl!r}); sys.path.insert(0, {here!r})
import frs_guard as g
lab = Path({lab!r})
g.LabGuard.install(lab)
import frs_machine as fm, frs_run as fr, m8_rd_stub as stub, crossing_search as cs, crossing_search_run2 as r2
out = Path({out!r}); run_dir = out / {run_name!r}; run1 = Path({run1!r})
params = r2.Params2(**{params!r})
P = r2.plan_and_write(lab, run1, out, params, stub.analyse)
env = fr.LabEnv(worker_spec=lambda rank: {{"rank": rank, "backend": "m8_rd_stub:StubBackend", "world": "easy", "inject": {{}},
                                           "failure_dir": str(run_dir / "failures"), "guard": g.LabGuard.spec()}},
                replay=lambda words, label, slot: stub.replay_trace("easy", words, label), analyse=stub.analyse,
                readiness=lambda: {{"ok": True, "problems": []}}, battleship_pids=lambda: [], snapshot=fm.tree_snapshot, import_problems=lambda: [],
                wait_no_battleship=lambda t: [], code_manifest=fr.code_manifest, backend="stub", sample_s=0.25, row_every_s=0.5,
                caps=dict(fm.CAPS_MB, main_private=1e9))
cfg = cs.SearchConfig(lab_root=lab, out=out, run_dir=run_dir, frontier_dir=run1, n_workers={workers!r}, max_ticks={max_ticks!r}, max_wall_s={max_wall!r},
                      expect_code={expect!r}, stop_grace_s=10.0, verify_floor_s=5.0, verify_s_per_clear=2.0, write_reserve_s=2.0, progress_every_s=2.0, seed_parallel=2)
code = r2.ResumeSearch(cfg, env, P, params).run()
print(json.dumps({{"code": code, "violations": g.LabGuard.violations[:3], "inherited": P["plan"]["archive"]["inherited"], "bound": P["bound"], "best": P["best"]["completion_input_tick"],
                  "eager": {{k: v for k, v in P["plan"]["eager"].items() if k != "cids"}}}}))
'''


def child2_code(lab: Path, out: Path, run1: Path, run_name: str, params: Dict[str, Any], *, workers: int = 2, max_ticks: int = 10 ** 9, max_wall: float = 300.0,
                expect: Optional[str] = None) -> str:
    return RUN_CHILD.format(rl=str(RL), here=str(HERE), lab=str(lab), out=str(out), run_name=run_name, run1=str(run1), params=params, workers=workers, max_ticks=max_ticks,
                            max_wall=max_wall, expect=expect)


def synthetic_run1(lab: Path, max_dispatches: int) -> Dict[str, Any]:
    """A crossing search (run 1) output folder made IN the stub world with run 1's own engine (crossing_search_tests' synthetic frontier, then
    crossing_search in a guarded child). THE WORLD IS SYNTHETIC."""
    syn = cst.synthetic_frontier(lab)
    out = lab / "crossing_syn"
    params = {"seeds": 12, "seed_order": "level", "level_decay": 0.5, "novelty_exp": 1.0, "seen_exp": 1.0, "bonus_exp": 1.0, "pace_exp": 0.5, "max_segments": 3,
              "retire_after": 0, "max_cells": 100000, "max_dispatches": max_dispatches, "rng_seed": 3}
    res = fst.run_child(cst.child_code(lab, out, syn["out"], "run", params, expect=syn["expect"]))
    check(res["code"] == 0 and not res["violations"], f"the synthetic run 1: {res}")
    s = json.loads((out / "run" / "summary.json").read_text(encoding="utf-8"))
    check(s["clears"]["verified"] >= 1 and s["status"] == "DISPATCH_CAP", f"the synthetic run 1 needs a verified clear and a clean stop: {s['status']} {s['clears']['verified']}")
    return {"out": out, "expect": syn["expect"], "summary": s, "frontier": syn}


def tamper_cells(src: Path, dst: Path, cids: Sequence[int]) -> None:
    """A copy of a run 1 folder whose FINAL representative of each given cell carries a wrong chain digest (its prefix will not reproduce it)."""
    shutil.copytree(src, dst)
    rows = read_jsonl(dst / "run" / "cells.jsonl")
    last = {}
    for i, r in enumerate(rows):
        last[r["cid"]] = i
    for cid in cids:
        rows[last[cid]]["chain"] = "00" * 32
    with open(dst / "run" / "cells.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")


@synthetic
def stub_end_to_end() -> Dict[str, Any]:
    lab = tmpdir("lab")
    r1 = synthetic_run1(lab, max_dispatches=110)
    run1, expect, s1 = r1["out"], r1["expect"], r1["summary"]
    best1 = s1["clears"]["best_verified"]["completion_input_tick"]
    out = lab / "crossing_syn_run2"
    params = {"seeds": 1, "seed_order": "level", "level_decay": 0.5, "novelty_exp": 1.0, "seen_exp": 1.0, "bonus_exp": 1.0, "pace_exp": 0.5, "max_segments": 3, "retire_after": 0,
              "max_cells": 100000, "max_dispatches": 400, "rng_seed": 5, "cleared_weight": 0.1, "check_slots": 1, "check_queue_max": 4, "eager_levels": 0, "eager_max_min": 15.0,
              "canary_per_level": 1, "reset_novelty": False, "check_error_limit": 10}                    # eager_levels 0: the canaries eagerly, every other inherited cell lazily
    # the zero-tick plan on the synthetic run 1: the bound from its best verified clear, the archive loaded, the eager set
    P = r2.build_plan(lab, run1, r2.Params2(**params), stub.analyse)
    p = P["plan"]
    final1 = {r["cid"]: r for r in read_jsonl(run1 / "run" / "cells.jsonl")}
    check(P["best"]["completion_input_tick"] == best1 and P["bound"] == best1 - cs.MARGIN - 1 and p["archive"]["inherited"] == len(final1) and p["archive"]["eligible"] >= 1
          and p["eager"]["cells"] >= 1, f"the plan on the synthetic run 1: best {best1}, bound {P['bound']}, {p['archive']}")
    (out).mkdir()
    (out / "plan.json").write_text(json.dumps({"archive_set_digest": "0" * 64}), encoding="utf-8")
    try:
        r2.plan_and_write(lab, run1, out, r2.Params2(**params), stub.analyse)
        raise AssertionError("a different saved archive set was overwritten")
    except cs.SearchError:
        pass
    (out / "plan.json").unlink()
    # an unclean run 1 is refused at the plan
    bad1 = lab / "crossing_syn_unclean"
    shutil.copytree(run1, bad1)
    s_bad = json.loads((bad1 / "run" / "summary.json").read_text(encoding="utf-8"))
    s_bad["status"] = "SEARCH_INVALID"
    (bad1 / "run" / "summary.json").write_text(json.dumps(s_bad), encoding="utf-8")
    try:
        r2.build_plan(lab, bad1, r2.Params2(**params), stub.analyse)
        raise AssertionError("an unclean run 1 was accepted")
    except cs.SearchError:
        pass
    # the wrong lab code digest is refused at open (nothing launched)
    res0 = fst.run_child(child2_code(lab, out, run1, "run_badcode", params, expect="0" * 64))
    check(res0["code"] == 2 and any(f.name.startswith("refused_") for f in out.iterdir()) and not (out / "run_badcode").exists(), f"a wrong lab code digest is refused: {res0}")
    # the run
    res = fst.run_child(child2_code(lab, out, run1, "run", params, expect=expect))
    check(res["code"] == 0 and not res["violations"], f"the synthetic run 2: {res}")
    run_dir = out / "run"
    s = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    rows = read_jsonl(run_dir / "dispatches.jsonl")
    cells2 = read_jsonl(run_dir / "cells.jsonl")
    checks = read_jsonl(run_dir / "checks.jsonl")
    vrows = read_jsonl(run_dir / "verifications.jsonl") if (run_dir / "verifications.jsonl").is_file() else []
    nr = read_jsonl(run_dir / "claims_not_replayed.jsonl") if (run_dir / "claims_not_replayed.jsonl").is_file() else []
    r2s = s["run2"]
    check(s["status"] == "DISPATCH_CAP" and s["work"]["dispatches"] == params["max_dispatches"] and s["contract"] == r2.RUN2_CONTRACT, f"{s['status']} {s['stop']} {s['work']}")
    check(s["reference"]["ok"] is True and r2s["anchor"]["ok"] is True and s["integrity"]["guard_violations_main"] == [] and s["integrity"]["battleship_left"] == []
          and s["integrity"]["lab_code_digest_end"] == expect and s["integrity"]["prefix_mismatches"] == 0, f"{s['reference']} {r2s['anchor']} {s['integrity']}")
    # the inherited cells were checked natively before their first burst: every dispatched representative is either checked ok (eager or lazy) or a run 2 cell
    ok_reps = {(c["cid"], c["digest"]) for c in checks if c["ok"] and not c.get("stale")}
    run2_reps = {(c["cid"], c["digest"]) for c in cells2}
    for r in rows:
        fam = r["draw_id"].split("|")
        check(fam[1] == r2.KEY_FAMILY and fam[0] == p["archive_id"], f"dispatch {r['n']}: key family {r['draw_id']}")
        check((r["cid"], fam[2]) in ok_reps or (r["cid"], fam[2]) in run2_reps, f"dispatch {r['n']}: cell {r['cid']} was dispatched without a check")
        check(r["prefix_level_ok"] and r["tick0_equal"] is True and r["outcome"] not in cs.BAD_OUTCOMES, f"dispatch {r['n']}: the prefix")
        burst = bytes.fromhex(r["words_hex"])
        check(fa.stream_words(r["draw_id"], r["k"], len(burst)) == burst, f"dispatch {r['n']}: the burst re-derives from its key family")
    ck = r2s["checks"]
    check(ck["checks_eager"] == res["eager"]["cells"] >= 1 and ck["checks_lazy"] >= 5 and ck["checks_ok"] == ck["checks_eager"] + ck["checks_lazy"] - ck["checks_stale"] and ck["checks_quarantined"] == 0
          and ck["checks_error"] == 0 and ck["check_ticks"] > 0 and r2s["draws"]["draws_unverified"] >= ck["checks_lazy"], f"the checks {ck} (eager planned {res['eager']}, draws {r2s['draws']})")
    check(r2s["inherited"] == len(final1) and s["archive"]["cells"] == len(final1) + sum(1 for c in cells2 if c["ev"] == "new"), "run 1's cells plus run 2's")
    inherited_dispatched = {r["cid"] for r in rows if r["cid"] in final1 and (r["cid"], r["draw_id"].split("|")[2]) in ok_reps}
    check(len(inherited_dispatched) >= 1 and any(r["cid"] not in final1 for r in rows) or len(inherited_dispatched) >= 2, "inherited and run 2 cells were both dispatched")
    # claims: replayed only when faster than the best; verified clocks strictly decrease; a faster clear than run 1's best was verified
    claimed = [r for r in rows if r["outcome"] == "clear"]
    check(len(claimed) == r2s["claims"]["claimed"] == len(vrows) + len(nr) and len(vrows) >= 1, f"claims {r2s['claims']} ({len(vrows)} replayed, {len(nr)} not)")
    best_seen = best1
    for v in sorted(vrows, key=lambda v: v["n"]):
        check(v["verdict"] == fv.VERIFIED and v["chain_r1"] == v["chain_r2"] and v["clocks_r1"] == v["clocks_r2"] and v["completion_input_tick"] < best_seen, f"verification {v['n']}: {v['completion_input_tick']} vs {best_seen}")
        best_seen = v["completion_input_tick"]
    for x in nr:
        check(x["verdict"] == r2.NOT_REPLAYED and x["claimed_completion_input_tick"] >= x["best_at_decision"] and len(x["words_hex"]) == 2 * x["words"], f"not replayed {x['n']}")
    check(r2s["faster_than_run1"] >= 1 and r2s["best"]["completion_input_tick"] < best1 and r2s["best"]["source"] == "run2" and r2s["best_history"] and s["clears"]["best_verified"]["completion_input_tick"] == r2s["best"]["completion_input_tick"],
          f"a faster clear than run 1's best {best1}: {r2s['best']}")
    check(r2s["gain_vs_run1_best"] == best1 - r2s["best"]["completion_input_tick"] and r2s["best"]["arrival"][str(mcell.TARGETS_TOTAL)] == r2s["best"]["completion_input_tick"], "the gain and the pace")
    # cleared starts: every representative that produced a claim carries its clear count
    by_rep_clears: Dict[Tuple[int, str], int] = {}
    for r in claimed:
        key = (r["cid"], r["draw_id"].split("|")[2])
        by_rep_clears[key] = by_rep_clears.get(key, 0) + 1
    check(r2s["cleared_starts"] >= 1 and sum(d["cleared_starts"] for d in r2s["per_level"].values()) == r2s["cleared_starts"], f"cleared starts {r2s['cleared_starts']}")
    # progress.md: the best against run 1 and the reference, the deepest level, the cells per level and the pace lineages
    prog = (run_dir / "progress.md").read_text(encoding="utf-8")
    check(prog.startswith("# Crossing search run 2: progress (") and "Final." in prog and "## Best verified clear" in prog and f"FASTER by {best1 - r2s['best']['completion_input_tick']} ticks" in prog
          and "## Deepest level and earliest ticks" in prog and "## Cells per level" in prog and "## Lineages ahead of the best clear's pace" in prog and "## Checks and claims" in prog
          and "## Verified clears" in prog, "progress.md sections")
    check((run_dir / "report.md").read_text(encoding="utf-8").startswith("# Crossing search run 2 (") and (run_dir / "run1_best.json").is_file() and (run_dir / "config.json").is_file()
          and (run_dir / "memory.jsonl").is_file() and (run_dir / "state.json").is_file(), "the run folder")
    cfg = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    check(cfg["contract"] == r2.RUN2_CONTRACT and cfg["key_family"] == r2.KEY_FAMILY and cfg["e7"]["bound_max_L"] == P["bound"] and cfg["run1"]["dir"] == str(run1), "config.json")
    # quarantine: tampered inherited cells (their chain) are quarantined by their eager check; the run goes on within the limit
    plan_cids = list(r2.build_plan(lab, run1, r2.Params2(**dict(params, eager_levels=1)), stub.analyse)["plan"]["eager"]["cids"])
    check(len(plan_cids) >= 5, f"the eager set of the deepest level holds at least five cells ({len(plan_cids)})")
    bad2 = lab / "crossing_syn_bad2"
    tamper_cells(run1, bad2, plan_cids[:2])
    out_b = lab / "crossing_syn_run2_bad2"
    res_b = fst.run_child(child2_code(lab, out_b, bad2, "run", dict(params, max_dispatches=60, eager_levels=1), expect=expect))
    sb = json.loads((out_b / "run" / "summary.json").read_text(encoding="utf-8"))
    check(res_b["code"] == 0 and sb["status"] == "DISPATCH_CAP" and sb["run2"]["checks"]["checks_quarantined"] == 2 and sb["archive"]["quarantined"] == 2 and sb["work"]["mismatches"] == 2,
          f"two tampered cells quarantined: {sb['status']} {sb['run2']['checks']} {sb['archive']}")
    qrows = [c for c in read_jsonl(out_b / "run" / "checks.jsonl") if not c["ok"]]
    check(sorted(c["cid"] for c in qrows) == sorted(plan_cids[:2]) and all("chain_equal" in str(c["why"]) for c in qrows), f"the quarantined cells {qrows}")
    check(not any(r["cid"] in plan_cids[:2] for r in read_jsonl(out_b / "run" / "dispatches.jsonl")), "a quarantined cell is never dispatched")
    # more than mismatch_limit quarantines: SEARCH_INVALID (exit 3)
    bad5 = lab / "crossing_syn_bad5"
    tamper_cells(run1, bad5, plan_cids[:5])
    out_c = lab / "crossing_syn_run2_bad5"
    res_c = fst.run_child(child2_code(lab, out_c, bad5, "run", dict(params, max_dispatches=60, eager_levels=10), expect=expect))
    sc = json.loads((out_c / "run" / "summary.json").read_text(encoding="utf-8"))
    check(res_c["code"] == 3 and sc["status"] == "SEARCH_INVALID" and sc["work"]["mismatches"] > 3, f"more than three quarantines invalidate the run: {sc['status']} {sc['work']['mismatches']}")
    # a wall cap and a tick cap stop cleanly, with the pending claims decided
    res_w = fst.run_child(child2_code(lab, out, run1, "run_wall", params, max_wall=20.0, expect=expect))
    sw = json.loads((out / "run_wall" / "summary.json").read_text(encoding="utf-8"))
    check(res_w["code"] == 0 and sw["status"] == "WALL_CAP" and sw["elapsed_s"] < 20.0 + 60.0 and sw["integrity"]["battleship_left"] == [] and "Final." in (out / "run_wall" / "progress.md").read_text(encoding="utf-8"),
          f"the wall cap: {sw['status']} {sw['elapsed_s']}")
    cap = s["work"]["reference_ticks"] + s["work"]["anchor_ticks"] + s["run2"]["eager"]["ticks"] + 6 * (P["bound"] + 120 * params["max_segments"]) + 10
    res_t = fst.run_child(child2_code(lab, out, run1, "run_cap", params, max_ticks=cap, expect=expect))
    st = json.loads((out / "run_cap" / "summary.json").read_text(encoding="utf-8"))
    check(res_t["code"] == 0 and st["status"] == "TICK_CAP" and st["work"]["ticks_total"] <= cap and st["unverified"] == [] and st["integrity"]["battleship_left"] == [], f"the tick cap: {st['status']} {st['work']}")
    # a second run into the same run folder is refused
    res5 = fst.run_child(child2_code(lab, out, run1, "run", params, expect=expect))
    check(res5["code"] == 2, f"an existing run folder is refused: {res5}")
    return {"run1": {"dispatches": s1["work"]["dispatches"], "cells": len(final1), "best": best1, "verified": s1["clears"]["verified"]},
            "run2": {"dispatches": s["work"]["dispatches"], "cells": s["archive"]["cells"], "best": r2s["best"]["completion_input_tick"], "gain": r2s["gain_vs_run1_best"], "verified": len(vrows),
                     "not_replayed": len(nr), "checks": ck, "eager": res["eager"], "cleared_starts": r2s["cleared_starts"], "inherited_dispatched": len(inherited_dispatched),
                     "draws": r2s["draws"]}, "quarantine": sb["run2"]["checks"], "invalid_mismatches": sc["work"]["mismatches"], "wall_jobs": sw["work"]["jobs"], "cap_jobs": st["work"]["jobs"]}


# =============================================================================================================================================


def main(argv: Sequence[str]) -> int:
    global LAB, RUN1
    args = list(argv[1:])
    for flag in ("--lab-root", "--run1"):
        if flag in args:
            i = args.index(flag)
            if flag == "--lab-root":
                LAB = Path(args[i + 1])
            else:
                RUN1 = Path(args[i + 1])
            del args[i:i + 2]
    sel = args[0] if args else "all"
    pick = [t for t in TESTS if sel == "all" or t[0] == sel or (sel == "only" and len(args) > 1 and args[1] in t[1])]
    passed = 0
    t_all = time.perf_counter()
    for kind, name, fn in pick:
        t0 = time.perf_counter()
        try:
            info = fn()
            passed += 1
            extra = json.dumps(info, default=str, separators=(",", ":"))[:700] if info else ""
            print(f"PASS {name} ({time.perf_counter() - t0:.1f} s) {extra}", flush=True)
        except Exception as exc:  # noqa: BLE001 - reported per test
            print(f"FAIL {name} ({time.perf_counter() - t0:.1f} s): {type(exc).__name__}: {exc}"[:3000], flush=True)
            print(traceback.format_exc()[-2500:], flush=True)
        if g.LabGuard.installed:
            print(f"STOP: the lab guard is armed in the test process after {name}; the remaining tests cannot run here (an audit hook cannot be removed)", flush=True)
            break
    for p in CREATED:
        shutil.rmtree(p, ignore_errors=True)
    print(f"crossing search run 2 tests: {passed}/{len(pick)} passed in {time.perf_counter() - t_all:.0f} s")
    return 0 if passed == len(pick) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
