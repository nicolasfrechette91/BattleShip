#!/usr/bin/env python3
"""Step 8 tests (2026-11-06 session): run 3's selection (tools/frs/run3_select.py), its start (tools/frs/run3_load.py), its exports
(tools/frs/run3_export.py) and the engine (tools/frs/crossing_search_run3.py). Zero native ticks: the unit tests run in process on a small
synthetic archive; the `real` tests read the lab's run 1 and run 2 folders and import (read only); the `e2e` tests run the engine on fake
game processes (rl/m8_rd_fakegame.py, the stub world behind the real launcher) in guarded children. THE WORLD IS SYNTHETIC.

    python -B tools/frs/crossing_search_run3_tests.py            every test
    python -B tools/frs/crossing_search_run3_tests.py unit       in-process tests only
    python -B tools/frs/crossing_search_run3_tests.py real       the lab's runs 1 + 2 (zero ticks; skipped when the lab is absent)
    python -B tools/frs/crossing_search_run3_tests.py e2e        the engine on the fake game

The owner's test plan (2026-11-06, SESSION_LOG_2026-11-04.md section 16.7):
    niches      units (parent niche + the burst's breaks, several breaks ordered by tick, seeds) and the engine's derivation equal to the
                offline one on every cell row of runs 1 + 2 (`unit_niche_inheritance`, `real_niches_equal_offline`)
    moves       a scripted A -> B move: membership, ranks, anchors in both groups, a displaced third anchor, the staleness reset, the breadth
                count kept, both groups' windows / counters / demotion unchanged, an emptied group leaving its level and returning with its
                history, the pooled warm start of a new niche (`unit_moves`)
    e2e         two same-seed runs on the fake game with group moves, identical under D4 (dispatch rows except clock fields, cells.jsonl rows
                with niche and group, end records, hourly records, triggers), vacuity guard >= 5 group moves (`e2e_same_seed_runs`)
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

assert sys.flags.dont_write_bytecode, "run with python -B"

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
RL = REPO / "rl"
for _p in (RL, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import det_schedule as det  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import run3_export as rx  # noqa: E402
import run3_load as rl3  # noqa: E402
import run3_select as rs  # noqa: E402
from infra_testlib import check, cleanup, run_suite, tmpdir  # noqa: E402

LAB = Path(os.environ.get("RUN3_TEST_LAB", "C:/BattleShip_lab"))
RUN1_REAL = LAB / "crossing_2026-10-15"
RUN2_REAL = LAB / "crossing_2026-10-15_run2"


def params(**kw: Any) -> Any:
    import crossing_search_run3 as C

    return C.Params3(**kw)


# -- a small synthetic archive -------------------------------------------------------------------------------------------------------------------


class FC:
    def __init__(self, cid: int, level: int, mask: int, cls: str, tick: int):
        self.cid, self.level, self.tick = cid, level, tick
        self.key = (0, 0, cls, mask, -1)
        self.words: Optional[bytes] = b"x"
        self.quarantined: Optional[str] = None
        self.retired: Optional[str] = None
        self.digest = f"d{cid}_{tick}"
        self.cleared = 0

    def alive(self) -> bool:
        return self.words is not None and self.quarantined is None and self.retired is None


class FA:
    def __init__(self, cells: List[FC], bound: int):
        self.cells, self.bound = cells, bound

    def eligible(self, c: FC) -> bool:
        return c.alive() and c.level < 10 and c.tick <= self.bound


A_N, B_N, C_N = (15, (3,)), (23, (4,)), (15, ())          # level 7 mask 7 via target 3 / via target 4; level 6 mask 15
GA, GB, GC = (7, 7, "15:3"), (7, 7, "23:4"), (6, 15, "15:")


def tails_of(hist: Mapping[str, Mapping[str, int]]) -> Dict[str, str]:
    """A per-dispatch sequence matching each group's counters (oldest first): its falls first, its breaks and e last."""
    out = {}
    for gl, h in hist.items():
        n, f, b, e = int(h["n"]), int(h["fall"]), int(h["b"]), int(h["e"])
        out[gl] = "".join(str(rs.window_code(i < f, i >= n - b, i >= n - e)) for i in range(n))
    return out


def fixture(history: Optional[Mapping[str, Mapping[str, int]]] = None, tails: Optional[Mapping[str, str]] = None,
            **pkw: Any) -> Tuple[FA, rs.Run3Selector]:
    cells = [FC(0, 7, 7, "A0", 100), FC(1, 7, 7, "A0", 110), FC(2, 7, 7, "A0", 120), FC(3, 7, 7, "A0", 130),   # group A
             FC(4, 7, 7, "A0", 105), FC(5, 7, 7, "A0", 115), FC(6, 7, 7, "A0", 125),                         # group B
             FC(7, 6, 15, "A1", 50), FC(8, 6, 15, "A1", 60)]                                                  # group C
    niches = {0: A_N, 1: A_N, 2: A_N, 3: A_N, 4: B_N, 5: B_N, 6: B_N, 7: C_N, 8: C_N}
    hist = history if history is not None else {rs.glabel(GA): {"n": 400, "fall": 100, "b": 8, "bu": 8, "e": 0},
                                                rs.glabel(GB): {"n": 400, "fall": 100, "b": 2, "bu": 2, "e": 0},
                                                rs.glabel(GC): {"n": 400, "fall": 100, "b": 4, "bu": 4, "e": 0}}
    a = FA(cells, 1000)
    return a, rs.Run3Selector(a, params(**pkw), niches=niches, history=hist, cid_dispatches={1: 7}, best_claim=None,
                              history_tails=tails if tails is not None else tails_of(hist))


def info_of(sel: rs.Run3Selector, cid: int, stream: str = "rank") -> Dict[str, Any]:
    c = sel.a.cells[cid]
    return {"group": sel.group[cid], "level": c.level, "stream": stream, "cid": cid, "digest": c.digest, "niche": sel.niche[cid]}


QUIET = {"outcome": "out_of_words", "levels": {}, "advanced": False}


def replace(c: FC, tick: int) -> FC:
    c.tick = tick
    c.digest = f"d{c.cid}_{tick}"
    return c


# -- unit tests ---------------------------------------------------------------------------------------------------------------------------------


def unit_niche_inheritance() -> Dict[str, Any]:
    st: Counter = Counter()
    check(rs.seed_niche(7) == (7, ()) and rs.niche_label((7, ())) == "7:", "a seed's niche is its mask and no target")
    one = rs.child_niche((15, ()), 7, 60, [[50, 3]], st)
    check(one == (15, (3,)) and st["steps_single_agree"] == 1, f"one break: the parent's niche plus that target {one}")
    child_mask = 1023 & ~(1 << 2) & ~(1 << 5) & ~(1 << 7)
    multi = rs.child_niche((1023, ()), child_mask, 40, [[30, 7], [20, 5], [30, 2]], st)
    check(multi == (1023, (5, 2, 7)) and rs.niche_label(multi) == "1023:5-2-7" and st["steps_multi"] == 1,
          f"several breaks in one burst: by break tick, ties by target id {multi}")
    late = rs.child_niche((1023, ()), 1023 & ~(1 << 2) & ~(1 << 5), 40, [[50, 5], [45, 2]], st)
    check(late == (1023, (2, 5)), f"breaks after the child's tick do not order it: target id order {late}")
    grand = rs.child_niche(one, 3, 90, [[80, 2]], st)
    check(grand == (15, (3, 2)), f"a grandchild extends its parent's niche {grand}")
    none = rs.child_niche(one, 7, 70, [], st)
    check(none == one, "no target broken: the parent's niche")
    return {"stats": dict(st)}


def unit_moves() -> Dict[str, Any]:
    a, sel = fixture()
    check([cid for _t, cid in sel.gall[GA]] == [0, 1, 2, 3] and sel.anchors[GA] == [0, 1, 2] and sel.anchors[GB] == [4, 5, 6], "the start: A 4 cells, anchors 3+3")
    sel.anc[1].update(w=0.25, bursts=3)
    sel.stale[1] = 5
    hist_a, hist_b = dict(sel.hist[GA]), dict(sel.hist[GB])
    win_a, win_b = list(sel.win[GA]), list(sel.win[GB])
    dem0 = set(sel.dem)
    # cell 1 (an anchor of A) replaced by a faster arrival from another order: it moves to B; the dispatch is credited to C (cell 7)
    replace(a.cells[1], 101)
    out = sel.on_ingest(info_of(sel, 7), QUIET, [(rs.REPLACED, a.cells[1], B_N)], [], 1)
    check(out["moves"] == 1 and sel.group[1] == GB and sel.niche[1] == B_N, "cell 1 moved to B")
    check([cid for _t, cid in sel.gall[GA]] == [0, 2, 3] and [cid for _t, cid in sel.gall[GB]] == [1, 4, 5, 6], "membership and ranks of both groups")
    check(sel.members(GB).index(1) == 0, "inserted into B by its tick (rank 0)")
    check(sel.anchors[GA] == [0, 2, 3] and sel.anc[3]["w"] == 1.0 and sel.anc[3]["bursts"] == 0, "A: the next cell of the class becomes an anchor at w 1")
    check(sel.anchors[GB] == [1, 4, 5] and 6 not in sel.anc, "B: the moved cell is an anchor, B's third anchor (cell 6) lost status and weight")
    check(sel.anc[1]["w"] == 1.0 and sel.anc[1]["bursts"] == 0 and sel.anc[1]["group"] == GB, "the weight and bursts the old representative earned are dropped")
    check(sel.stale.get(1) == 0 and sel.bcount[1] == 7, "staleness reset; the breadth count stays with the cell id")
    check(dict(sel.hist[GA]) == hist_a and dict(sel.hist[GB]) == hist_b and list(sel.win[GA]) == win_a and list(sel.win[GB]) == win_b and sel.dem == dem0,
          "both groups' windows, counters and demotion unchanged by the move")
    check(sel.hist[GC]["n"] == 401, "the dispatch was credited to the group dispatched (C)")
    # rule 1: a same-niche replacement of an anchor resets it to w 1 / 0 bursts
    sel.anc[0].update(w=0.125, bursts=4)
    replace(a.cells[0], 99)
    sel.on_ingest(info_of(sel, 7), QUIET, [(rs.REPLACED, a.cells[0], A_N)], [], 2)
    check(sel.group[0] == GA and sel.anc[0]["w"] == 1.0 and sel.anc[0]["bursts"] == 0, "same-niche replacement of an anchor: w 1, 0 bursts")
    # an emptied group leaves its level (phi recomputed) and returns with its history
    lv_before = sel.levels()[7]
    _sh, phi2 = sel.shares(7)
    for cid, t in ((0, 98), (2, 97), (3, 96)):
        replace(a.cells[cid], t)
        sel.on_ingest(info_of(sel, 7), QUIET, [(rs.REPLACED, a.cells[cid], B_N)], [], 3)
    check(GA not in sel.levels().get(7, []) and lv_before == [GA, GB], f"A has no eligible cell: it left level 7 {sel.levels()}")
    _sh, phi1 = sel.shares(7)
    check(abs(phi2 - 0.125) < 1e-12 and abs(phi1 - 0.25) < 1e-12, f"phi recomputed: {phi2} -> {phi1}")
    check(dict(sel.hist[GA]) == hist_a and list(sel.win[GA]) == win_a, "A kept its history while empty")
    replace(a.cells[3], 95)
    sel.on_ingest(info_of(sel, 7), QUIET, [(rs.REPLACED, a.cells[3], A_N)], [], 4)
    check(GA in sel.levels()[7] and list(sel.win[GA]) == win_a and sel.warm[GA]["source"] == "run2", "A returned with its history")
    # a brand-new niche: the pooled warm start of its level
    pooled = sum(sum(sel.win[g]) for g in sel.win if g[0] == 6) / sum(len(sel.win[g]) for g in sel.win if g[0] == 6)
    c9 = FC(9, 6, 15, "A2", 70)
    a.cells.append(c9)
    sel.on_ingest(info_of(sel, 4), QUIET, [(rs.NEW, c9, (31, (4,)))], [], 5)        # credited to B (level 7): level 6's windows unchanged
    gD = (6, 15, "31:4")
    check(sel.warm[gD]["source"] == "pooled_level" and abs(sel.warm[gD]["rate"] - pooled) < 1e-12 and len(sel.win[gD]) == 200,
          f"a new niche group starts at its level's pooled rate {sel.warm[gD]} vs {pooled}")
    return {"moves": sel.cnt["moves"], "events": len(sel.events)}


def unit_demotion_and_shares() -> Dict[str, Any]:
    hist = {rs.glabel(GA): {"n": 999, "fall": 800, "b": 0, "bu": 0, "e": 0}, rs.glabel(GB): {"n": 400, "fall": 100, "b": 6, "bu": 6, "e": 2},
            rs.glabel(GC): {"n": 10, "fall": 1, "b": 0, "bu": 0, "e": 0}}
    a, sel = fixture(hist)
    check(GA not in sel.dem, "999 dispatches: not demoted yet")
    sh, phi = sel.shares(7)
    rho_a, rho_b = (200 * 0 + 1) / 202, (200 * 8 / 400 + 1) / 202
    exp = {GA: max(phi, rho_a / (rho_a + rho_b)), GB: max(phi, rho_b / (rho_a + rho_b))}
    t = sum(exp.values())
    check(all(abs(sh[g] - exp[g] / t) < 1e-12 for g in exp), f"normalised then floored: {sh}")
    fall = {"outcome": "fall", "levels": {}, "advanced": False}
    sel.on_ingest(info_of(sel, 0), fall, [], [], 1)
    check(GA in sel.dem and sel.events[-1]["kind"] == "demoted" and sel.events[-1]["history"]["n"] == 1000, f"the 1,000th fall demotes: {sel.events[-1:]}")
    sh, phi = sel.shares(7)
    check(abs(sh[GA] - phi / 4) < 1e-12 and abs(sh[GB] - (1 - phi / 4)) < 1e-12, f"a demoted group gets phi / 4: {sh}")
    check(all(cid not in sel.breadth_pool() for cid in (0, 1, 2, 3)), "a demoted group is not in the breadth pool")
    brk = {"outcome": "fall", "levels": {"8": 1500}, "advanced": True}
    sel.on_ingest(info_of(sel, 0), brk, [], [], 2)
    check(GA not in sel.dem and sel.events[-1]["kind"] == "exit" and sel.events[-1]["history"]["b"] == 1, "its first break (any break) is the exit")
    useful = {"outcome": "fall", "levels": {"8": 900}, "advanced": True}
    before = sum(sel.win[GA])
    sel.on_ingest(info_of(sel, 0), useful, [], [], 3)
    check(sum(sel.win[GA]) == before + 1 and sel.hist[GA]["bu"] == 1, "a useful break (next arrival <= the bound) counts in the window")
    return {"events": [e["kind"] for e in sel.events]}


FALL = {"outcome": "fall", "levels": {}, "advanced": False}
BREAK = {"outcome": "fall", "levels": {}, "advanced": True}


def unit_rolling_demotion() -> Dict[str, Any]:
    """Demotion on the group's last 1,000 dispatches (owner 2026-11-08; zero-break rule, owner 2026-11-11): a group whose older history
    holds breaks and an e is demoted exactly when its last break leaves the window, at 0 falls (the whole-history rule and the falls
    criterion never would); a break is the exit, and after it the group is demoted again exactly when that break leaves the window, 1,000
    of its dispatches later (the window is the hysteresis). Sequences that disagree with the counters refuse."""
    hist = {rs.glabel(GA): {"n": 1004, "fall": 0, "b": 5, "bu": 5, "e": 1}, rs.glabel(GB): {"n": 400, "fall": 100, "b": 2, "bu": 2, "e": 0},
            rs.glabel(GC): {"n": 400, "fall": 100, "b": 4, "bu": 4, "e": 0}}
    seq_a = [6, 2, 2, 2, 2] + [0] * 999                         # breaks and an e first; the last break is the window's oldest dispatch; no fall
    tails = dict(tails_of(hist), **{rs.glabel(GA): "".join(map(str, seq_a))})
    a, sel = fixture(hist, tails)
    check(GA not in sel.dem and sel.window_counts(GA) == {"n": 1000, "fall": 0, "b": 1, "e": 0}, f"the start window: {sel.window_counts(GA)}")
    sel.on_ingest(info_of(sel, 0), QUIET, [], [], 1)
    ev = sel.events[-1]
    check(GA in sel.dem and ev["kind"] == "demoted" and ev["window"] == {"n": 1000, "fall": 0, "b": 0, "e": 0} and ev["history"]["b"] == 5,
          f"the last break leaves the window: demoted at 0 falls although the whole history holds 5 breaks {ev}")
    sh, phi = sel.shares(7)
    check(abs(sh[GA] - phi / 4) < 1e-12, "a demoted group gets phi / 4")
    sel.on_ingest(info_of(sel, 0), FALL, [], [], 2)
    check(GA in sel.dem and len(sel.events) == 1, f"a fall changes nothing: still demoted {sel.events}")
    sel.on_ingest(info_of(sel, 0), BREAK, [], [], 3)
    check(GA not in sel.dem and sel.events[-1]["kind"] == "exit" and sel.events[-1]["window"]["b"] == 1, f"a break is the exit {sel.events[-1]}")
    k = 0
    while GA not in sel.dem and k < 2000:
        k += 1
        sel.on_ingest(info_of(sel, 0), QUIET, [], [], 3 + k)
    check(k == 1000 and sel.window_counts(GA) == {"n": 1000, "fall": 0, "b": 0, "e": 0} and len(sel.events) == 3,
          f"demoted again exactly when the break left the window, no event before: {k} {len(sel.events)}")
    _a, v3 = fixture(hist, tails, demote_fall_rate=0.75, demote_exit_fall_rate=0.70)
    v3.on_ingest(info_of(v3, 0), QUIET, [], [], 1)
    check(GA not in v3.dem and not v3.events, "the v3 thresholds (falls >= 75 %) on the same window: never demoted")
    bad = dict(tails, **{rs.glabel(GB): tails[rs.glabel(GB)][:-1]})
    try:
        fixture(hist, bad)
        raise AssertionError("a sequence shorter than its counters was accepted")
    except ValueError as exc:
        check("does not match" in str(exc), f"refused: {exc}")
    return {"refall_after_break": k, "events": [e["kind"] for e in sel.events]}


def unit_demotion_hysteresis() -> Dict[str, Any]:
    """The 2026-11-10/11 night's flip (group (9, 256, 326:2-6-1): exit at 749 falls of 1,000, demoted again at 750, eleven events, no break),
    reproduced on a window whose oldest dispatches alternate quiet / fall: the 2026-11-08 rule (exit threshold = demotion threshold) flips on
    every dispatch, the hysteresis (owner 2026-11-11: demoted at >= 75 %, exit on a break, an e, or falls < 70 %) logs one demotion. Then
    the exit comes at 699 falls, never between 700 and 749; an e entering the window is an exit; the status at the start is the rule
    replayed over the whole sequence; an exit threshold above the demotion threshold refuses. The v3 thresholds are passed explicitly
    (run3_select_v4's default is the zero-break rule, unit_zero_break_demotion); they stay reproducible for the night-2 replay."""
    V3 = {"demote_fall_rate": 0.75}
    front = [0, 1] * 5                                          # the window's oldest ten dispatches: quiet, fall, quiet, fall ...
    seq = [6, 2, 2] + front + [1] * 744 + [0] * 246             # old breaks and an e outside the window; the window: 749 falls, 0 b, 0 e
    hist = {rs.glabel(GA): {"n": len(seq), "fall": sum(c & 1 for c in seq), "b": 3, "bu": 3, "e": 1},
            rs.glabel(GB): {"n": 400, "fall": 100, "b": 2, "bu": 2, "e": 0}, rs.glabel(GC): {"n": 400, "fall": 100, "b": 4, "bu": 4, "e": 0}}
    tails = dict(tails_of(hist), **{rs.glabel(GA): "".join(map(str, seq))})
    pushes = [FALL, QUIET] * 4 + [FALL]                         # 750, 749, 750, 749, ... 750
    kinds: Dict[str, List[Tuple[str, int]]] = {}
    for name, rate in (("rule_2026_11_08", 0.75), ("hysteresis", 0.70)):
        a, sel = fixture(hist, tails, demote_exit_fall_rate=rate, **V3)
        check(GA not in sel.dem and sel.window_counts(GA) == {"n": 1000, "fall": 749, "b": 0, "e": 0}, f"{name}: the start window {sel.window_counts(GA)}")
        for i, row in enumerate(pushes):
            sel.on_ingest(info_of(sel, 0), row, [], [], 1 + i)
        kinds[name] = [(e["kind"], e["window"]["fall"]) for e in sel.events]
        if name == "hysteresis":
            hy = sel
    check(kinds["rule_2026_11_08"] == [("demoted", 750), ("exit", 749)] * 4 + [("demoted", 750)], f"the old rule flips on every dispatch: {kinds}")
    check(kinds["hysteresis"] == [("demoted", 750)] and GA in hy.dem, f"the hysteresis: one demotion, no flip: {kinds}")
    n = len(pushes)
    falls_seen = []
    while GA in hy.dem and n < 200:                             # quiet dispatches push falls out of the window one by one
        n += 1
        hy.on_ingest(info_of(hy, 0), QUIET, [], [], n)
        falls_seen.append(hy.window_counts(GA)["fall"])
    ev = hy.events[-1]
    check(ev["kind"] == "exit" and ev["window"]["fall"] == 699 and min(falls_seen[:-1]) == 700 and len(hy.events) == 2,
          f"the exit comes at 699 falls, never at 700 to 749: {ev} {falls_seen[:3]}...{falls_seen[-3:]}")
    # an e entering the window exits (a kept level-8 cell earlier than every alive cell of its group, from a dispatch of group A)
    seq_e = [1] * 760 + [0] * 240
    hist_e = dict(hist, **{rs.glabel(GA): {"n": 1000, "fall": 760, "b": 0, "bu": 0, "e": 0}})
    a, sel = fixture(hist_e, dict(tails, **{rs.glabel(GA): "".join(map(str, seq_e))}), demote_exit_fall_rate=0.70, **V3)
    check(GA in sel.dem, "760 falls, no break: demoted at the start")
    deep = FC(9, 8, 3, "A0", 50)
    a.cells.append(deep)
    out = sel.on_ingest(info_of(sel, 0), QUIET, [(rs.NEW, deep, (15, (3, 2)))], [], 1)
    check(out["e"] == 1 and out["b"] == 0 and GA not in sel.dem and sel.events[-1]["kind"] == "exit" and sel.events[-1]["window"]["e"] == 1,
          f"an e entering the window is the exit: {out} {sel.events[-1:]}")
    # the status at the start: the rule replayed over the whole sequence (demoted at 750, then decayed to 720 without a break)
    starts = {}
    for name, rate, tail in (("decayed_720", 0.70, [1] * 750 + [0] * 280), ("decayed_720_old_rule", 0.75, [1] * 750 + [0] * 280),
                             ("decayed_690", 0.70, [1] * 750 + [0] * 310), ("never_750", 0.70, [0] * 280 + [1] * 720)):
        h2 = dict(hist, **{rs.glabel(GA): {"n": len(tail), "fall": sum(tail), "b": 0, "bu": 0, "e": 0}})
        _a, s2 = fixture(h2, dict(tails, **{rs.glabel(GA): "".join(map(str, tail))}), demote_exit_fall_rate=rate, **V3)
        starts[name] = (GA in s2.dem, s2.window_counts(GA)["fall"])
    check(starts == {"decayed_720": (True, 720), "decayed_720_old_rule": (False, 720), "decayed_690": (False, 690), "never_750": (False, 720)},
          f"start status replayed over the sequence: {starts}")
    try:
        params(demote_exit_fall_rate=0.8, **V3).check()
        raise AssertionError("an exit threshold above the demotion threshold was accepted")
    except Exception as exc:
        check("exit threshold" in str(exc), f"refused: {exc}")
    return {"old_rule_events": len(kinds["rule_2026_11_08"]), "hysteresis_events": len(kinds["hysteresis"]), "exit_at": 699, "starts": starts}


def unit_zero_break_demotion() -> Dict[str, Any]:
    """The gap in DECISIVE 2 the owner found before night 3 (group (9, 256, 326:2-6-1): 0 breaks in 4,521 run 3 dispatches at 30-54 % falls,
    never demoted under the falls criterion). The zero-break rule (owner 2026-11-11, run3_select_v4: both fall rates 0): a group whose last
    1,000 dispatches hold 0 breaks and 0 e is demoted whatever its falls, at the start (the rule replayed over its sequence) and the moment
    its window fills; the other group of its level then takes 1 - phi / 4; a break 10 dispatches inside the window holds the demotion off
    for exactly 11 more dispatches at 0 falls; a break or an e is the exit. The v3 thresholds on the same sequences demote nothing."""
    seq_a = [6, 2, 2] + [0] * 497 + [1, 1, 0, 0, 0] * 200       # old breaks and an e; then 1,000 dispatches at 40 % falls, 0 b, 0 e
    seq_b = [1, 0, 0] * 333                                     # 999 dispatches, 0 breaks: one short of the window
    seq_c = [0] * 10 + [2] + [0] * 989                          # 1,000 dispatches at 0 falls; one break, the window's 11th oldest
    hist = {}
    for g, s in ((GA, seq_a), (GB, seq_b), (GC, seq_c)):
        hist[rs.glabel(g)] = {"n": len(s), "fall": sum(c & 1 for c in s), "b": sum((c >> 1) & 1 for c in s), "bu": sum((c >> 1) & 1 for c in s),
                              "e": sum((c >> 2) & 1 for c in s)}
    tails = {rs.glabel(GA): "".join(map(str, seq_a)), rs.glabel(GB): "".join(map(str, seq_b)), rs.glabel(GC): "".join(map(str, seq_c))}
    a, sel = fixture(hist, tails)
    dem_start = sorted(rs.glabel(g) for g in sel.dem)
    check(sel.dem == {GA} and sel.window_counts(GA) == {"n": 1000, "fall": 400, "b": 0, "e": 0} and sel.hist[GA]["b"] == 3,
          f"A (40 % falls, 0 breaks in its last 1,000, 3 older breaks) demoted at the start; B (999) and C (a break inside) not: {sel.dem}")
    sh, phi = sel.shares(7)
    check(abs(phi - 0.125) < 1e-12 and abs(sh[GA] - phi / 4) < 1e-12 and abs(sh[GB] - (1 - phi / 4)) < 1e-12, f"B takes 1 - phi / 4: {sh}")
    _a, v3 = fixture(hist, tails, demote_fall_rate=0.75, demote_exit_fall_rate=0.70)
    sh3, _phi3 = v3.shares(7)
    check(not v3.dem and sh3[GB] < sh[GB], f"under the v3 thresholds nothing is demoted and B's share is lower: {sh3}")
    sel.on_ingest(info_of(sel, 4), QUIET, [], [], 1)
    check(GB in sel.dem and sel.events[-1]["kind"] == "demoted" and sel.events[-1]["window"] == {"n": 1000, "fall": 333, "b": 0, "e": 0},
          f"B's window fills with 0 breaks at 33 % falls: demoted {sel.events[-1:]}")
    k = 0
    while GC not in sel.dem and k < 50:
        k += 1
        sel.on_ingest(info_of(sel, 7), QUIET, [], [], 1 + k)
    check(k == 11 and sel.window_counts(GC) == {"n": 1000, "fall": 0, "b": 0, "e": 0}, f"C demoted exactly when its break left the window: {k}")
    sel.on_ingest(info_of(sel, 0), BREAK, [], [], 100)
    check(GA not in sel.dem and sel.events[-1]["kind"] == "exit" and sel.events[-1]["group"] == rs.glabel(GA), f"A: a break is the exit {sel.events[-1:]}")
    deep = FC(9, 8, 3, "A0", 50)
    a.cells.append(deep)
    out = sel.on_ingest(info_of(sel, 4), QUIET, [(rs.NEW, deep, (15, (3, 2)))], [], 101)
    check(out["e"] == 1 and out["b"] == 0 and GB not in sel.dem and sel.events[-1]["kind"] == "exit" and sel.events[-1]["window"]["e"] == 1,
          f"B: an e is the exit {out} {sel.events[-1:]}")
    for i in range(30):
        sel.on_ingest(info_of(sel, 0), FALL, [], [], 200 + i)
    check(GA not in sel.dem and sel.window_counts(GA)["b"] == 1, "A after its exit: 30 falls, the break still in the window, not demoted")
    return {"demoted_at_start": dem_start, "b_share": round(sh[GB], 6), "b_share_v3": round(sh3[GB], 6), "c_after": k,
            "events": [(e["group"], e["kind"]) for e in sel.events]}


def unit_new_earliest_in_demoted_group() -> Dict[str, Any]:
    """A burst that gives a DEMOTED group a new earliest eligible cell queues that cell for 3 trigger draws (owner 2026-11-08), one cell per
    group per burst (its earliest); not for a cell that is not the group's earliest, nor in a group that is not demoted; served in turn
    through breadth slots within the trigger cap."""
    hist = {rs.glabel(GA): {"n": 1000, "fall": 1000, "b": 0, "bu": 0, "e": 0}, rs.glabel(GB): {"n": 400, "fall": 100, "b": 2, "bu": 2, "e": 0},
            rs.glabel(GC): {"n": 400, "fall": 100, "b": 4, "bu": 4, "e": 0}}
    a, sel = fixture(hist, trigger_cap=0.5)
    check(sel.dem == {GA}, f"A demoted at the start: {sel.dem}")
    c90, c95 = FC(9, 7, 7, "A1", 90), FC(10, 7, 7, "A1", 95)    # level 7 cells of A's niche, from a level-6 dispatch (cell 7, group C)
    a.cells += [c90, c95]
    out = sel.on_ingest(info_of(sel, 7), QUIET, [(rs.NEW, c95, A_N), (rs.NEW, c90, A_N)], [], 1)
    t = sel.triggers[out["landing_triggers"][0]] if out["landing_triggers"] else {}
    check(len(out["landing_triggers"]) == 1 and t.get("classes") == [rs.LANDING_CLASS] and t.get("cells") == [[9, 90]] and t.get("draws_queued") == 3
          and t.get("group") == rs.glabel(GA) and out["e"] == 1 and list(sel.tq) == [[9, c90.digest, 3, t["index"]]],
          f"one cell (the earliest, 90) queued for 3 draws: {out} {t}")
    c92 = FC(11, 7, 7, "A1", 92)
    a.cells.append(c92)
    out2 = sel.on_ingest(info_of(sel, 7), QUIET, [(rs.NEW, c92, A_N)], [], 2)
    check(out2["landing_triggers"] == [], "not earlier than the group's earliest (90): nothing queued")
    c101 = FC(12, 7, 7, "A1", 101)
    a.cells.append(c101)
    out3 = sel.on_ingest(info_of(sel, 7), QUIET, [(rs.NEW, c101, B_N)], [], 3)
    check(out3["landing_triggers"] == [] and out3["e"] == 1 and GB not in sel.dem, "B's new earliest cell (101 < 105): B is not demoted, nothing queued")
    served: List[Tuple[str, int]] = []
    for i in range(12):
        c, d = sel.select(Seq([0.1, 0.5]))
        sel.on_dispatch(c, d, 10 + i)
        served.append((d["stream"], c.cid))
    trig = [cid for s_, cid in served if s_ == "trigger"]
    check(trig == [9, 9, 9] and not sel.tq and sel.cnt["trigger_draws"] <= 0.5 * sel.cnt["breadth_draws"] and sel.cnt["landing_triggers"] == 1,
          f"3 draws within the cap: {served}")
    return {"queued": 1, "served": len(trig)}


def unit_e_and_anchor_success() -> Dict[str, Any]:
    a, sel = fixture()
    deep = FC(9, 6 + 1, 7, "A0", 90)                    # a deeper group (level 7) arrival at 90 < A's earliest 100: e = 1
    a.cells.append(deep)
    sel.anc[7].update(w=0.5, bursts=1)
    out = sel.on_ingest(info_of(sel, 7, "anchor"), QUIET, [(rs.NEW, deep, A_N)], [], 1)
    check(out["e"] == 1 and out["anchor_success"] is True and sel.anc[7]["w"] == 1.0 and sel.anc[7]["successes"] == 1, f"e and anchor success: {out}")
    late = FC(10, 7, 7, "A2", 140)                      # deeper, not earliest; but the first A2 of A: an anchor -> success, e = 0
    a.cells.append(late)
    out = sel.on_ingest(info_of(sel, 7, "anchor"), QUIET, [(rs.NEW, late, A_N)], [], 2)
    check(out["e"] == 0 and out["anchor_success"] is True, f"a new anchor in a deeper group without e: {out}")
    late2 = FC(11, 7, 7, "A0", 150)                     # deeper, A0 already has 3 earlier anchors: no success, w halves
    a.cells.append(late2)
    out = sel.on_ingest(info_of(sel, 7, "anchor"), QUIET, [(rs.NEW, late2, A_N)], [], 3)
    check(out["anchor_success"] is False and sel.anc[7]["w"] == 0.5, f"no success: w halves {sel.anc[7]}")
    for i in range(5):
        sel.on_ingest(info_of(sel, 7, "anchor"), QUIET, [], [], 4 + i)
    check(sel.anc[7]["w"] == 0.125, "the weight floor 1/8")
    out = sel.on_ingest(info_of(sel, 7, "rank"), QUIET, [], [], 10)
    check(out["anchor_success"] is None and sel.anc[7]["w"] == 0.125, "a rank draw of an anchor does not change its anchor weight")
    return {"w": sel.anc[7]["w"]}


class Seq:
    def __init__(self, xs: Sequence[float]):
        self.xs = list(xs)

    def random(self) -> float:
        return self.xs.pop(0)


def unit_draws() -> Dict[str, Any]:
    a, sel = fixture()
    # exploitation: level 7 (deepest, weight 1 of 1.5), group by share, anchor when u3 < 0.5 x w_max = 0.5
    c, d = sel.select(Seq([0.9, 0.9, 0.0, 0.1]))
    check(d["stream"] == "anchor" and c.cid == 0, f"an anchor draw: the highest w, fewest bursts, earliest tick {d} {c.cid}")
    sel.on_dispatch(c, d, 1)
    c2, d2 = sel.select(Seq([0.9, 0.9, 0.0, 0.1]))
    check(d2["stream"] == "anchor" and c2.cid == 1, f"rotation: the next anchor (fewest anchor bursts) {c2.cid}")
    c3, d3 = sel.select(Seq([0.9, 0.9, 0.0, 0.9, 0.0]))
    check(d3["stream"] == "rank" and d3["rank"] == 0, f"a rank draw at u = 0: rank 0 {d3}")
    ws = sel.rank_weights(GA)
    check(abs(ws[0] - 1.0 * max(0.05, 1 / 2)) < 1e-12 and abs(ws[1] - 0.5) < 1e-12, f"(1 + rank)^-1 x max(0.05, 1 / (1 + stale)) {ws}")
    a.cells[2].cleared = 2
    check(abs(sel.rank_weights(GA)[2] - (1 / 3) * 0.01) < 1e-12, "x 0.1 per claimed clear")
    # breadth: count-based over the pool in cell-id order
    pool = sel.breadth_pool()
    w = [1 / (1 + sel.bcount.get(cid, 0)) for cid in pool]
    target = sum(w[:3]) / sum(w) + 1e-9
    c4, d4 = sel.select(Seq([0.1, target]))
    check(d4["stream"] == "breadth" and c4.cid == pool[3], f"count-based breadth: cumulative in cell-id order {d4} {c4.cid} {pool}")
    # keyed streams: the breadth share over 100,000 dispatches
    rng = det.KeyedRandom(5, "test")
    n = Counter()
    for i in range(100000):
        rng.begin(i + 1)
        n[sel.select(rng)[1]["stream"]] += 1
    share = (n["breadth"] + n["trigger"]) / 100000
    check(abs(share - 0.2) < 0.01, f"breadth share {share:.4f} within 0.20 +/- 0.01")
    return {"streams": dict(n), "breadth_share": round(share, 4)}


def add(a: FA, level: int, mask: int, cls: str, tick: int) -> FC:
    c = FC(len(a.cells), level, mask, cls, tick)
    a.cells.append(c)
    return c


def unit_triggers() -> Dict[str, Any]:
    a, sel = fixture(trigger_cap=0.5)
    k = [add(a, 7, 7, "A1", t) for t in (45, 50, 60)]
    kept = [(rs.NEW, c, A_N) for c in k]
    ev = [{"kind": "line_crossing", "step": 51, "step_from": 49, "event_id": "e1"}, {"kind": "break_occluded", "step": 20, "step_from": 19, "event_id": "e0"}]
    out = sel.on_ingest(info_of(sel, 7), QUIET, kept, ev, 1)
    t = sel.triggers[out["trigger"]]
    check(t["classes"] == ["line_crossing"] and [c for c, _t in t["cells"]] == [k[1].cid, k[2].cid] and t["draws_queued"] == 6 and len(sel.tq) == 2,
          f"kept cells at ticks >= step_from + 1 (50), 3 draws each; break_occluded records only {t}")
    occl = sel.on_ingest(info_of(sel, 7), QUIET, [], [{"kind": "break_occluded", "step": 5, "step_from": 4}], 2)
    check(occl["trigger"] is None, "break_occluded never triggers")
    for i in range(2):                                         # nothing kept: the fallback queues the dispatched cell (7) each time
        sel.on_ingest(info_of(sel, 7), QUIET, [], [{"kind": "line_crossing", "step": 1, "step_from": 0}], 3 + i)
    fourth = sel.on_ingest(info_of(sel, 7), QUIET, [], [{"kind": "line_crossing", "step": 1, "step_from": 0}], 5)
    check(fourth["trigger"] is None and sel.trig_seen["line_crossing"] == 4, "a class seen in 3 earlier bursts no longer triggers")
    # rule b (owner 2026-11-06): a non-finite burst queues its last kept eligible cell, or the dispatched cell when it kept none
    early, c_nf = add(a, 7, 7, "A1", 40), add(a, 7, 7, "A1", 70)
    nf = sel.on_ingest(info_of(sel, 7), QUIET, [(rs.NEW, early, A_N), (rs.NEW, c_nf, A_N)], [{"kind": "nonfinite", "step": 80, "step_from": 79}], 6)
    tn = sel.triggers[nf["trigger"]]
    check(tn["cells"] == [[c_nf.cid, 70]] and tn["rule"] == ["last_kept_before_null"], f"a non-finite reply: the burst's last kept cell is queued {tn}")
    nf2 = sel.on_ingest(info_of(sel, 8), QUIET, [], [{"kind": "nonfinite", "step": 90, "step_from": 89}], 7)
    tn2 = sel.triggers[nf2["trigger"]]
    check(tn2["cells"] == [[8, 60]] and tn2["rule"] == ["dispatched_cell"], f"a non-finite burst that kept nothing: the dispatched cell {tn2}")
    served: List[Tuple[str, int]] = []
    for i in range(40):
        c, d = sel.select(Seq([0.1, 0.5]))
        sel.on_dispatch(c, d, 10 + i)
        served.append((d["stream"], c.cid))
    trig = [cid for s_, cid in served if s_ == "trigger"]
    check(sel.cnt["trigger_draws"] <= 0.5 * sel.cnt["breadth_draws"] and trig[:6] == [k[1].cid, k[2].cid, 7, 7, c_nf.cid, 8], f"served in turn within the cap: {served[:8]}")
    check(Counter(trig) == Counter({k[1].cid: 3, k[2].cid: 3, 7: 6, c_nf.cid: 3, 8: 3}) and not sel.tq, f"3 draws per queued entry: {Counter(trig)}")
    # a queued cell replaced before its draw is dropped
    a2, sel2 = fixture(trigger_cap=1.0)
    c30 = add(a2, 7, 7, "A1", 55)
    sel2.on_ingest(info_of(sel2, 7), QUIET, [(rs.NEW, c30, A_N)], [{"kind": "inside_solid", "step": 60, "step_from": 54}], 1)
    replace(c30, 52)
    c, d = sel2.select(Seq([0.1, 0.5]))
    check(d["stream"] == "breadth" and sel2.cnt["trigger_dropped"] == 1, f"a replaced queued cell is dropped: {d}")
    return {"served": len(trig), "triggers": len(sel.triggers)}


def unit_trigger_fallback() -> Dict[str, Any]:
    """Detector classes (owner 2026-11-06): the kept cells at or after the event; when there is none, the burst's last kept eligible cell;
    when the burst kept none, the dispatched cell. The rule used is recorded."""
    a, sel = fixture()
    early, late = add(a, 7, 7, "A1", 40), add(a, 7, 7, "A1", 60)
    o1 = sel.on_ingest(info_of(sel, 7), QUIET, [(rs.NEW, early, A_N), (rs.NEW, late, A_N)], [{"kind": "inside_solid", "step": 100, "step_from": 99}], 1)
    t1 = sel.triggers[o1["trigger"]]
    check(t1["cells"] == [[late.cid, 60]] and t1["rule"] == ["last_kept_cell"], f"nothing kept after the event: the last kept cell {t1}")
    o2 = sel.on_ingest(info_of(sel, 8), QUIET, [], [{"kind": "floor_switch_unlinked", "step": 70, "step_from": 69}], 2)
    t2 = sel.triggers[o2["trigger"]]
    check(t2["cells"] == [[8, 60]] and t2["rule"] == ["dispatched_cell"], f"nothing kept at all: the dispatched cell {t2}")
    after = add(a, 7, 7, "A1", 90)
    o3 = sel.on_ingest(info_of(sel, 7), QUIET, [(rs.NEW, early, A_N), (rs.NEW, after, A_N)], [{"kind": "inside_solid", "step": 85, "step_from": 84}], 3)
    t3 = sel.triggers[o3["trigger"]]
    check(t3["cells"] == [[after.cid, 90]] and t3["rule"] == ["kept_at_or_after_event"], f"a cell kept after the event: the usual rule {t3}")
    return {"rules": [t1["rule"][0], t2["rule"][0], t3["rule"][0]]}


class _Rec:
    def __init__(self) -> None:
        self.rows: List[Tuple[str, Dict[str, Any]]] = []

    def append_jsonl(self, path: Any, row: Mapping[str, Any]) -> None:
        self.rows.append((Path(path).name, dict(row)))


class _Env:
    def wait_no_battleship(self, t: float) -> List[int]:
        return []

    def log(self, s: str) -> None:
        pass

    def now(self) -> float:
        return 0.0


def unit_claims_frozen() -> Dict[str, Any]:
    """CLAIMS_FROZEN (owner 2026-11-06), on a stub engine at the close: a text replay with other clocks freezes every verified clear of the
    run (status CLAIMS_FROZEN, exit code 5), the remaining text replays are skipped, best_times and exports get frozen rows, the banner."""
    import crossing_search as cs
    import crossing_search_run3 as C

    check(cs.EXIT[C.CLAIMS_FROZEN] == 5 and cs.STATUS_RANK[C.CLAIMS_FROZEN] == cs.STATUS_RANK["SEARCH_INVALID"], "the status and its exit code")
    eng = object.__new__(C.Run3Engine)
    rec = _Rec()
    calls: List[str] = []

    def lying_replay(words: bytes, label: str) -> Dict[str, Any]:
        calls.append(label)
        return {"ok": True, "result": {"outcome": "clear", "completion_input_tick": 101, "completion_time_passed": 100}}

    for k, v in {"best_history": [{"n": 5}, {"n": 9}], "text_replay_fn": lying_replay, "env": _Env(), "fs": rec, "dir": Path("run"), "text_replays": [],
                 "claims_frozen": None, "status": "WALL_CAP", "notes": [], "stopping": True, "stop_reason": "wall", "pool": None, "t0": 0.0, "phase": "close",
                 "c": {"dispatches": 0}, "events": [],
                 "vrows": [{"n": 5, "verdict": "VERIFIED", "words_hex": "00" * 100, "completion_input_tick": 100, "completion_time_passed": 99},
                           {"n": 9, "verdict": "VERIFIED", "words_hex": "00" * 90, "completion_input_tick": 90, "completion_time_passed": 89}]}.items():
        setattr(eng, k, v)
    eng.run_text_replays()
    check(eng.status == C.CLAIMS_FROZEN and cs.EXIT[eng.status] == 5, f"status {eng.status}")
    cf = eng.claims_frozen
    check(cf and cf["frozen_clears"] == [5, 9] and cf["clocks_text"] == [101, 100] and cf["clocks_verified"] == [100, 99] and cf["archive"] == "to_investigate",
          f"the freeze record {cf}")
    check(len(calls) == 1 and eng.text_replays[0]["equal"] is False and eng.text_replays[1].get("skipped", "").startswith("claims frozen"),
          f"one text replay, the next one skipped: {calls} {eng.text_replays}")
    frozen = [(f, r["n"]) for f, r in rec.rows if r.get("frozen")]
    check(sorted(frozen) == sorted([("best_times.jsonl", 5), ("best_times.jsonl", 9), ("exports.jsonl", 5), ("exports.jsonl", 9)]), f"frozen rows {frozen}")
    banner = C.frozen_banner({"run3": {"claims_frozen": cf}})
    check(banner and "CLAIMS FROZEN" in banner[0] and "--accept-run" in banner[0], "the banner")
    check(C.frozen_banner({"run3": {"claims_frozen": None}}) == [], "no banner without a freeze")
    return {"status": eng.status, "frozen": cf["frozen_clears"]}


def _run3_folder(root: Path, name: str, status: Optional[str], *, archive_id: str = "A", ref: int = 100) -> Path:
    import crossing_search_run3 as C

    d = root / name
    (d / "run").mkdir(parents=True)
    (d / "plan.json").write_text(json.dumps({"contract": C.RUN3_CONTRACT, "archive_id": archive_id, "e7": {"reference_completion_input_tick": ref, "margin": 24}}),
                                 encoding="utf-8")
    (d / "run" / "config.json").write_text("{}", encoding="utf-8")
    (d / "run" / "cells.jsonl").write_text("", encoding="utf-8")
    if status is not None:
        (d / "run" / "summary.json").write_text(json.dumps({"contract": C.RUN3_CONTRACT, "mode": "lab", "status": status,
                                                            "integrity": {"reference_ok": True, "run3_code_digest": "x", "run3_code_digest_end": "x"}}), encoding="utf-8")
    return d


def unit_non_clean_sources_refused() -> Dict[str, Any]:
    """A run 3 folder that did not stop cleanly (CLAIMS_FROZEN, SEARCH_INVALID, no summary) is refused as a --best-from source and as an
    end-record source, unless the owner's decision names it (--accept-run, recorded in the plan)."""
    import crossing_search as cs
    import crossing_search_run3 as C
    import run3_archive as rar

    root = tmpdir("run3_sources_")
    try:
        ok, frozen, invalid = _run3_folder(root, "ok", "WALL_CAP"), _run3_folder(root, "frozen", C.CLAIMS_FROZEN), _run3_folder(root, "invalid", "SEARCH_INVALID")
        nosum = _run3_folder(root, "nosum", None)
        check(C.read_best_source(ok, 100, "A")["accepted_non_clean"] is False, "a clean folder is read")
        refused = []
        for d in (frozen, invalid):
            try:
                C.read_best_source(d, 100, "A")
            except cs.SearchError as exc:
                refused.append(d.name)
                check("--accept-run" in str(exc), f"the refusal names the flag: {exc}")
        check(refused == ["frozen", "invalid"], f"non-clean folders refused as best sources: {refused}")
        check(C.read_best_source(frozen, 100, "A", accepted=[frozen])["accepted_non_clean"] is True, "admitted when the plan names it")
        files = [d / "run" / "cells.jsonl" for d in (ok, frozen, invalid, nosum)]
        bad = rar.end_record_source_problems(files)
        check(len(bad) == 3 and "CLAIMS_FROZEN" in bad[0] and "SEARCH_INVALID" in bad[1] and "no summary" in bad[2], f"end-record sources: {bad}")
        bad2 = rar.end_record_source_problems(files, [frozen, invalid / "run"])
        check(len(bad2) == 1 and "no summary" in bad2[0], f"named folders admitted (the output folder or its run folder): {bad2}")
    finally:
        cleanup(root)
    return {"refused_best_sources": refused, "end_record_problems": len(bad)}


def unit_plan_flags_match_saved_plan() -> Dict[str, Any]:
    """`run` refuses --best-from / --accept-run folders that differ from those its saved plan records: a non-clean folder is admitted only by
    the plan (owner 2026-11-06), never by a flag given at `run` alone; a flag dropped at `run` is refused too."""
    import crossing_search_run3 as C

    a, f = Path("C:/lab/crossing_a_run3"), Path("C:/lab/crossing_f_run3")
    saved = {"run3": {"best_from": [{"dir": str(a)}, {"dir": str(f)}], "accept_runs": [str(f)]}}
    check(C.plan_flag_problems(saved, [a, f], [f]) is None, "the same flags pass")
    check(C.plan_flag_problems(saved, [Path(str(a).upper()), f], [f]) is None, "path case and separators do not matter")
    cases = {"accept_at_run_only": C.plan_flag_problems({"run3": {"best_from": [{"dir": str(f)}]}}, [f], [f]),
             "accept_dropped": C.plan_flag_problems(saved, [a, f], []),
             "best_from_added": C.plan_flag_problems(saved, [a, f, Path("C:/lab/x")], [f]),
             "best_from_order": C.plan_flag_problems(saved, [f, a], [f])}
    check(all(cases.values()), f"every difference refused: {cases}")
    check("--accept-run" in cases["accept_at_run_only"] and "--best-from" in cases["best_from_added"], f"the refusal names the flag: {cases}")
    check(C.plan_flag_problems({"run3": {"best_from": []}}, [], []) is None, "an old plan without accept_runs and no flags passes")
    return {"refused": sorted(cases)}


def unit_real_windows() -> Dict[str, Any]:
    """Rule a (owner 2026-11-09): with an inherited run the D1 window is the group's last 200 real values (u + e at the plan's bound), the front
    padded with the group's whole-history rate; a window string that disagrees with the counters is refused; without one, DECISIVE 1's warm
    start is unchanged."""
    hist = {rs.glabel(GA): {"n": 50, "fall": 10, "b": 5, "bu": 4, "e": 1}, rs.glabel(GB): {"n": 300, "fall": 100, "b": 20, "bu": 12, "e": 3},
            rs.glabel(GC): {"n": 400, "fall": 100, "b": 4, "bu": 4, "e": 0}}
    wa = "0" * 44 + "1" * 3 + "2" + "0" * 2               # 50 values, sum 5 = bu 4 + e 1, the 2 near the end
    wb = "1" * 15 + "0" * 285                              # 300 values, sum 15 = bu 12 + e 3, all in the first 100 (outside the last 200)
    wc = "1" * 4 + "0" * 396
    win = {rs.glabel(GA): wa, rs.glabel(GB): wb, rs.glabel(GC): wc}
    a = FA(fixture()[0].cells, 1000)
    niches = {0: A_N, 1: A_N, 2: A_N, 3: A_N, 4: B_N, 5: B_N, 6: B_N, 7: C_N, 8: C_N}
    sel = rs.Run3Selector(a, params(), niches=niches, history=hist, cid_dispatches={}, best_claim=None, history_tails=tails_of(hist), history_windows=win)
    wA, wB = list(sel.win[GA]), list(sel.win[GB])
    check(len(wA) == 200 and wA[:150] == [5 / 50] * 150 and wA[150:] == [float(ch) for ch in wa], "A: 150 padded at its rate 0.1, then its 50 real values")
    check(wB == [0.0] * 200 and sel.warm[GB]["source"] == "real_window" and sel.warm[GB]["real"] == 200, "B: its last 200 real values (all 0)")
    check(abs(sel.rho(GB) - 1 / 202) < 1e-12, "B's rate is its real recent one, not its whole-history 0.05")
    try:
        rs.Run3Selector(a, params(), niches=niches, history=hist, cid_dispatches={}, best_claim=None, history_tails=tails_of(hist),
                        history_windows=dict(win, **{rs.glabel(GA): wa[:-1]}))
        raise AssertionError("a window shorter than the counters was accepted")
    except ValueError as exc:
        check("do not match" in str(exc), f"refused: {exc}")
    plain = rs.Run3Selector(a, params(), niches=niches, history=hist, cid_dispatches={}, best_claim=None, history_tails=tails_of(hist))
    check(list(plain.win[GB]) == [15 / 300] * 200 and plain.warm[GB]["source"] == "run2", "no inherited run: DECISIVE 1's warm start")
    return {"rho_B_real": round(sel.rho(GB), 6), "rho_B_warm": round(plain.rho(GB), 6)}


def unit_inherit_chain() -> Dict[str, Any]:
    """The inherited folders must form one linear chain after runs 1 + 2 (owner 2026-11-09): each planned on the same runs 1 and 2 and on
    exactly the folders before it; a sibling (planned on the same predecessors as an earlier one), a folder planned on another run 2 and a
    folder given twice are refused."""
    import crossing_search_run3 as C

    r1, r2 = {"dir": "C:/lab/run1", "cell_rows": 10}, {"dir": "C:/lab/run2", "cell_rows": 20}
    A, B, S = Path("C:/lab/a"), Path("C:/lab/b"), Path("C:/lab/s")
    pa = {"run1": dict(r1), "run2": dict(r2), "run3": {}}
    pb = {"run1": dict(r1), "run2": dict(r2), "run3": {"inherit": [{"dir": str(A)}]}}
    ps = {"run1": dict(r1), "run2": dict(r2), "run3": {"inherit": []}}
    check(C.inherit_chain_problems(r1, r2, [(A, pa), (B, pb)]) == [], "a then b (planned on a): one chain")
    cases = {"sibling": C.inherit_chain_problems(r1, r2, [(A, pa), (S, ps)]),
             "wrong_order": C.inherit_chain_problems(r1, r2, [(B, pb), (A, pa)]),
             "other_run2": C.inherit_chain_problems(r1, r2, [(A, dict(pa, run2={"dir": "C:/lab/other", "cell_rows": 20}))]),
             "twice": C.inherit_chain_problems(r1, r2, [(A, pa), (A, pa)])}
    check(all(cases.values()) and "sibling" in cases["sibling"][0] and "another run2" in cases["other_run2"][0] and "twice" in cases["twice"][0],
          f"every broken chain refused: {cases}")
    saved = {"run3": {"best_from": [], "accept_runs": [], "inherit": [{"dir": str(A)}]}}
    check(C.plan_flag_problems(saved, [], [], [A]) is None and "--inherit" in (C.plan_flag_problems(saved, [], [], []) or ""),
          "`run` takes exactly the saved plan's --inherit")
    return {"refused": sorted(cases)}


def unit_level_weights() -> Dict[str, Any]:
    """level_weights (owner 2026-11-09, "7-8 first"): w[k] for the level k below the deepest eligible one, 0 past the list, normalised by the draw;
    the default () keeps level_decay; the value is recorded in the plan's parameters; the hourly record gives per level the weight, the
    dispatches, u + e per 1,000 ingested and the earliest arrival."""
    import random

    import crossing_search as cs
    import crossing_search_run3 as C

    _a, plain = fixture()
    check(plain.level_weights([6, 7]) == {7: 1.0, 6: 0.5}, "default: level_decay 0.5")
    _a, sel = fixture(level_weights=(0.20, 0.35, 0.35, 0.10), breadth_share=0.0)
    check(sel.level_weights([6, 7, 8, 9]) == {9: 0.20, 8: 0.35, 7: 0.35, 6: 0.10} and sel.level_weights([5, 6, 7, 8, 9])[5] == 0.0,
          "w[k] counted down from the deepest eligible level, 0 past the list")
    check(sel.level_weights([6, 7]) == {7: 0.20, 6: 0.35}, "the fixture's levels 7 and 6 get w[0] and w[1]")
    rng = random.Random(5)
    lv = Counter(int(sel.select(rng)[1]["level"]) for _ in range(4000))
    f7 = lv[7] / 4000
    check(abs(f7 - 0.20 / 0.55) < 0.03, f"draws follow the normalised weights: level 7 {f7:.3f} (expected {0.20 / 0.55:.3f})")
    for bad in ((0.0, 1.0), (0.5, -0.1)):
        try:
            C.Params3(level_weights=bad).check()
            raise AssertionError(f"level_weights {bad} accepted")
        except cs.SearchError:
            pass
    check(C.Params3(level_weights=(0.2, 0.35, 0.35, 0.1)).as_dict()["level_weights"] == [0.2, 0.35, 0.35, 0.1] and C.Params3().as_dict()["level_weights"] == [],
          "the value is in the plan's parameters")
    sel.on_ingest(info_of(sel, 0), {"outcome": "fall", "levels": {"8": 900}, "advanced": True}, [], [], 1)
    sel.on_ingest(info_of(sel, 1), QUIET, [], [], 2)
    rec = sel.snapshot({})
    l7 = rec["levels"]["7"]
    check(l7["ingested"] == 2 and l7["u"] == 1 and l7["per_1000"] == 500.0 and l7["earliest"] == 100 and abs(l7["weight"] - 0.20 / 0.55) < 1e-6,
          f"the hourly record per level: {rec['levels']}")
    return {"level7_share": round(f7, 3), "levels": rec["levels"]}


def unit_bk2_roundtrip() -> Dict[str, Any]:
    import importlib.util

    import btti_replay as bt

    spec = importlib.util.spec_from_file_location("bk2_to_btt_inputs", REPO / "tools" / "bk2_to_btt_inputs.py")
    conv = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(conv)
    words = bytes(range(mcell.TRACK1_WORDS)) + bytes((7 * i + 3) % mcell.TRACK1_WORDS for i in range(500))
    data = rx.bk2_bytes(words, "test")
    rows = rx.bk2_rows(data)
    inherited = [conv.parse_row(r, i) for i, r in enumerate(rows)]
    check(inherited == rx.triples(words), "tools/bk2_to_btt_inputs.py reads the exported bk2 back to exactly the words' rows")
    check([rx.parse_bk2_row(r) for r in rows] == rx.triples(words), "the run's own reader agrees")
    d = tmpdir("run3_bk2_")
    try:
        (d / "x.bk2").write_bytes(data)
        r = subprocess.run([sys.executable, "-B", str(REPO / "tools" / "bk2_to_btt_inputs.py"), str(d / "x.bk2"), str(d / "x.btti")], capture_output=True, text=True)
        check(r.returncode == 0, f"the inherited converter ran: {r.stderr}")
        via_tool = [tuple(x) for x in bt.read_btti_rows(str(d / "x.btti"))]
        (d / "y.btti").write_text(rx.btti_text(words, "test"), encoding="ascii", newline="\n")
        direct = [tuple(x) for x in bt.read_btti_rows(str(d / "y.btti"))]
        check(via_tool == direct == rx.triples(words), "the .btti export equals the converter's output, read by rl/btti_replay.py")
        check(rx.bk2_bytes(words, "test") == data, "the bk2 bytes are deterministic")
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = sorted(z.namelist())
        check(names == ["Comments.txt", "Header.txt", "Input Log.txt"], f"the bk2 entries {names}")
    finally:
        cleanup(d)
    return {"frames": len(words)}


def unit_params() -> Dict[str, Any]:
    import crossing_search_run3 as C

    p = C.Params3()
    p.check()
    d = p.as_dict()
    need = ("breadth_share", "window", "rank_exp", "novelty_floor", "phi_factor", "demote_min_dispatches", "demote_fall_rate", "demote_exit_fall_rate", "demote_share_factor", "anchor_k",
            "anchor_share", "anchor_w_floor", "trigger_classes", "trigger_rarity", "trigger_draws_per_cell", "trigger_cap", "summary_every_s", "cleared_weight",
            "level_decay", "max_segments", "rng_seed")
    check(all(k in d for k in need) and d["max_segments"] == 6 and d["breadth_share"] == 0.2 and d["trigger_classes"] == list(C.TRIGGER_CLASSES),
          f"every parameter recorded: {sorted(set(need) - set(d))}")
    check(d["demote_min_dispatches"] == 1000 and d["demote_fall_rate"] == 0.0 and d["demote_exit_fall_rate"] == 0.0 and rs.SELECT_CONTRACT == "run3_select_v4",
          f"the zero-break rule by default (owner 2026-11-11): {d['demote_min_dispatches']} {d['demote_fall_rate']} {d['demote_exit_fall_rate']} {rs.SELECT_CONTRACT}")
    C.Params3(demote_fall_rate=0.75, demote_exit_fall_rate=0.70).check()
    bad = 0
    for kw in ({"breadth_share": 1.0}, {"retire_after": 5}, {"cleared_weight": 0.0}, {"reset_novelty": False}, {"summary_every_dispatches": 10},
               {"anchor_w_floor": 0.0}, {"window": 0}, {"demote_fall_rate": 0.75, "demote_exit_fall_rate": 0.76}, {"demote_exit_fall_rate": 0.01}):
        try:
            C.Params3(**kw).check()
        except C.SearchError:
            bad += 1
    check(bad == 9, f"every out-of-range parameter refused ({bad}/9)")
    import run3_manifest as rm

    m = rm.run3_code_manifest()
    check(all(f"tools/frs/{n}.py" in m for n in ("crossing_search_run3", "run3_select", "run3_load", "run3_export")), "the run 3 manifest covers the step 8 files")
    return {"manifest_files": len(m), "digest": rm.code_digest(m)[:16]}


# -- the lab's runs 1 + 2 (read only, zero ticks) ---------------------------------------------------------------------------------------------------

EXPECT_4B = {"9|2|326:2-6-8": (433, 12, 51.2, False), "9|256|326:2-6-1": (53, 10, 46.7, False), "9|64|326:2-8-1": (1054, 6, 2.1, True),
             "8|258|326:2-6": (1422, 12, 52.1, False), "8|66|326:2-8": (2519, 12, 33.0, False), "8|258|322:6": (320, 11, 8.2, False),
             "8|320|326:2-1": (127, 9, 6.7, False), "7|322|326:2": (3555, 12, 66.9, False), "7|322|322:": (3603, 12, 9.8, False),
             "7|70|326:8": (397, 12, 7.8, False), "7|266|330:6": (139, 12, 7.8, False), "7|322|330:3": (173, 9, 7.8, False),
             "6|330|330:": (4434, 12, 51.2, False), "6|326|326:": (4235, 12, 48.8, False)}


def _offline_niches(rows_by_run: Mapping[int, List[Dict[str, Any]]], dispatches: Mapping[int, List[Dict[str, Any]]]) -> Dict[str, Tuple[int, Tuple[int, ...]]]:
    """tools/analysis/run3_design/d4b_niche_units.py's niche_of, as written there (the offline reference)."""
    bydig: Dict[str, Dict[str, Any]] = {}
    for run in (1, 2):
        for r in rows_by_run[run]:
            bydig.setdefault(r["digest"], r)
    breaks_of = {(run, int(d["n"])): [(int(t), int(i)) for t, i in d["breaks_after_start"]] for run in (1, 2) for d in dispatches[run] if d.get("breaks_after_start")}
    memo: Dict[str, Tuple[int, Tuple[int, ...]]] = {}

    def niche_of(r: Mapping[str, Any]) -> Tuple[int, Tuple[int, ...]]:
        path, cur, base = [], r, None
        while cur is not None:
            if cur["digest"] in memo:
                base = memo[cur["digest"]]
                break
            path.append(cur)
            pd = (cur.get("origin") or {}).get("parent_digest")
            cur = bydig.get(pd) if pd else None
        if base is None:
            root = path.pop()
            base = (int(root["key"][3]), ())
            memo[root["digest"]] = base
        for row in reversed(path):
            sm, order = base
            prev = sm & ~sum(1 << t for t in order)
            m = int(row["key"][3])
            gone = [i for i in range(16) if (prev >> i) & 1 and not (m >> i) & 1]
            if len(gone) >= 2:
                bk = breaks_of.get((row["_run"], int(row["origin"]["n"])), [])
                when = {i: t for t, i in bk if t <= int(row["tick"])}
                gone.sort(key=lambda i: (when.get(i, 10 ** 9), i))
            base = (sm, order + tuple(gone))
            memo[row["digest"]] = base
        return base

    return {r["digest"]: niche_of(r) for run in (1, 2) for r in rows_by_run[run]}


def real_niches_equal_offline() -> Dict[str, Any]:
    if not (RUN1_REAL / "run" / "cells.jsonl").is_file() or not (RUN2_REAL / "run" / "cells.jsonl").is_file():
        return {"skipped": f"no lab runs under {LAB}"}
    D = rl3.load(RUN1_REAL, RUN2_REAL, 1220)
    R1, R2 = D["R1"], D["R2"]
    off = _offline_niches({1: R1["rows"], 2: R2["rows"]}, {1: R1["dispatches"], 2: R2["dispatches"]})
    nx = rl3.NicheIndex([R1, R2])
    rows = R1["rows"] + R2["rows"]
    diffs = [r["digest"] for r in rows if nx.of(r) != off[r["digest"]]]
    finals = [cid for cid, n in D["niches"].items() if n != off[str(D["M"]["final"][cid]["digest"])]]
    check(not diffs and not finals and len(D["niches"]) == 37294, f"{len(diffs)} rows and {len(finals)} final cells differ ({len(rows)} rows, {len(D['niches'])} cells)")
    check(D["niche_stats"].get("orphans", 0) == 0 and D["niche_stats"]["steps_single_agree"] == D["niche_stats"]["steps_single_checked"] == 5221
          and D["niche_stats"]["steps_multi"] == 168, f"lineage checks {D['niche_stats']}")
    check(D["history"]["attribution"] == {"by_start_tick": 39309} and D["history"]["moves"]["run2_moves"] == 15770, f"history {D['history']['attribution']} {D['history']['moves']}")
    return {"rows": len(rows), "cells": len(D["niches"]), "stats": D["niche_stats"]}


def real_start_table() -> Dict[str, Any]:
    if not (LAB / "import" / "import_manifest.json").is_file() or not RUN2_REAL.is_dir():
        return {"skipped": f"no lab import or runs under {LAB}"}
    import crossing_search_run3 as C

    P = C.build_plan(LAB, RUN1_REAL, RUN2_REAL, C.Params3(), code_digest="test")
    p = P["plan"]
    rows = {r["group"]: r for r in p["run3"]["start"] if r["eligible"]}
    got = {g: (r["eligible"], r["anchors"], round(100 * r["share"], 1), r["demoted"]) for g, r in rows.items()}
    check(got == EXPECT_4B, f"the start table is the approved 4b table: {[(g, got.get(g), EXPECT_4B.get(g)) for g in sorted(set(got) | set(EXPECT_4B)) if got.get(g) != EXPECT_4B.get(g)]}")
    check(p["e7"]["bound_max_L"] == 1220 and p["best"]["completion_input_tick"] == 1245 and p["best"]["source"] == "run2" and p["archive"]["inherited"] == 37294
          and p["archive"]["eligible"] == 22464 and p["run3"]["anchors"] == 153 and p["route"]["completion_input_tick"] == 1885, f"{p['e7']} {p['best']} {p['archive']['eligible']}")
    check(sum(r["eligible"] for r in rows.values()) == 22464 and p["run3"]["demoted"] == ["9|64|326:2-8-1"], "eligible 22,464; only (9, 64) demoted")
    return {"groups": len(rows), "anchors": p["run3"]["anchors"], "eligible": p["archive"]["eligible"], "cleared_starts": p["archive"]["cleared_starts"]}


# -- end to end on the fake game ------------------------------------------------------------------------------------------------------------------

FLAGS = {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1", "SSB64_RL_SPATIAL": "1", "FAKEGAME_WORLD": "easy", "FAKEGAME_BOOT_S": "0.1",
         "FAKEGAME_IDLE_S": "60", "FAKEGAME_STEP_JITTER_S": "0.002"}
RUN2_PARAMS = {"seeds": 1, "seed_order": "level", "level_decay": 0.5, "novelty_exp": 1.0, "seen_exp": 1.0, "bonus_exp": 1.0, "pace_exp": 0.5, "max_segments": 3,
               "retire_after": 0, "max_cells": 100000, "max_dispatches": 240, "rng_seed": 5, "cleared_weight": 0.1, "check_slots": 1, "check_queue_max": 4,
               "eager_levels": 0, "eager_max_min": 15.0, "canary_per_level": 1, "reset_novelty": False, "check_error_limit": 10}
RUN3_PARAMS = {"max_segments": 3, "max_dispatches": 160, "rng_seed": 7, "check_slots": 1, "summary_every_s": 0.0, "summary_every_dispatches": 40}
CHILD = ("import json, sys\nfrom pathlib import Path\nsys.path.insert(0, %r); sys.path.insert(0, %r)\nimport frs_guard as g\n"
         "g.LabGuard.install(Path(%r))\nimport crossing_search_run3_tests as T\nprint(json.dumps(T.%s(json.loads(%r)), default=str))\n")


def run_child(fn: str, lab: Path, args: Mapping[str, Any], timeout: float = 1800.0) -> Dict[str, Any]:
    code = CHILD % (str(RL), str(HERE), str(lab), fn, json.dumps(args))
    r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=timeout, cwd=str(lab))
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise AssertionError(f"{fn}: child failed: {(r.stderr or r.stdout)[-3000:]}")


def engine3_child(a: Mapping[str, Any]) -> Dict[str, Any]:
    import crossing_search as cs
    import crossing_search_run3 as C
    import frs_guard as g
    import frs_machine as fm
    import frs_run as fr
    import frs_verify as fv
    import m8_rd_stub as stub
    import run3_manifest as rm
    import run3_search_tests as r3t

    lab, out, run1, run2, exe = Path(a["lab"]), Path(a["out"]), Path(a["run1"]), Path(a["run2"]), Path(a["exe"])
    run_dir = out / "run"
    params = C.Params3(**a["params"])
    code = a.get("run3_code_digest") or rm.code_digest(rm.run3_code_manifest())
    inherit, accept = [Path(x) for x in a.get("inherit") or []], [Path(x) for x in a.get("accept_runs") or []]
    C.plan_and_write(lab, run1, run2, out, params, stub.analyse, code_digest=code, inherit=inherit, accept_runs=accept)   # the `plan` command
    P = C.plan_via_child(lab, run1, run2, out, params, code_digest=code, analyse="stub", inherit=inherit, accept_runs=accept)   # what `run` does
    frozen = {"frozen_sha256": a["frozen"], "exe_copy_sha256": a["exe_copy"]}
    fk = {"exe": a["exe"], "frozen": a["frozen"]}

    def spec(rank: int) -> Dict[str, Any]:
        return dict(r3t.worker_spec(lab, fk, rank, int(a["port_base"]), run_dir / "failures", dict(FLAGS, **(a.get("worker_flags") or {}))),
                    guard=g.LabGuard.spec(), run3_selfcheck=True)

    env = fr.LabEnv(worker_spec=spec, replay=fv.make_real_replay(exe, lab / "run_replays", FLAGS, frozen), analyse=stub.analyse,
                    readiness=lambda: {"ok": True, "problems": []}, battleship_pids=lambda: [], snapshot=fm.tree_snapshot, import_problems=lambda: [],
                    wait_no_battleship=lambda t: [], code_manifest=fr.code_manifest, backend="real", sample_s=0.25, row_every_s=0.5,
                    caps=dict(fm.CAPS_MB, main_private=1e9))
    cfg = cs.SearchConfig(lab_root=lab, out=out, run_dir=run_dir, frontier_dir=run1, n_workers=3, max_ticks=10 ** 9, max_wall_s=1200.0, expect_code=None,
                          stop_grace_s=60.0, verify_floor_s=5.0, verify_s_per_clear=2.0, write_reserve_s=2.0, progress_every_s=2.0, seed_parallel=3)
    text = rx.make_text_replay(exe, run_dir / "text_replays") if a.get("text_replay", True) else None
    rc = C.Run3Night(cfg, env, P, params, text_replay=text, anomaly_build={"exe": "fake", "platform": sys.platform}).run()
    return {"code": rc, "violations": g.LabGuard.violations[:3], "bound": P["bound"], "best": P["best"]["completion_input_tick"],
            "start": P["plan"]["run3"]["start"], "eligible": P["plan"]["archive"]["eligible"], "inherited": P["plan"]["archive"]["inherited"],
            "inherit": P["plan"]["run3"].get("inherit"), "windows_rule": P["plan"]["run3"].get("windows_rule"), "end_record_files": P.get("end_record_files"),
            "history": P["run3"]["history"]}


def run2_child(a: Mapping[str, Any]) -> Dict[str, Any]:
    import crossing_search as cs
    import crossing_search_run2 as r2
    import frs_guard as g
    import frs_machine as fm
    import frs_run as fr
    import m8_rd_stub as stub

    lab, out, run1 = Path(a["lab"]), Path(a["out"]), Path(a["run1"])
    run_dir = out / "run"
    params = r2.Params2(**a["params"])
    P = r2.plan_and_write(lab, run1, out, params, stub.analyse)
    env = fr.LabEnv(worker_spec=lambda rank: {"rank": rank, "backend": "m8_rd_stub:StubBackend", "world": "easy", "inject": {}, "failure_dir": str(run_dir / "failures"),
                                              "guard": g.LabGuard.spec()},
                    replay=lambda words, label, slot: stub.replay_trace("easy", words, label), analyse=stub.analyse,
                    readiness=lambda: {"ok": True, "problems": []}, battleship_pids=lambda: [], snapshot=fm.tree_snapshot, import_problems=lambda: [],
                    wait_no_battleship=lambda t: [], code_manifest=fr.code_manifest, backend="stub", sample_s=0.25, row_every_s=0.5,
                    caps=dict(fm.CAPS_MB, main_private=1e9))
    cfg = cs.SearchConfig(lab_root=lab, out=out, run_dir=run_dir, frontier_dir=run1, n_workers=2, max_ticks=10 ** 9, max_wall_s=600.0, expect_code=None,
                          stop_grace_s=10.0, verify_floor_s=5.0, verify_s_per_clear=2.0, write_reserve_s=2.0, progress_every_s=2.0, seed_parallel=2)
    rc = r2.ResumeSearch(cfg, env, P, params).run()
    return {"code": rc, "violations": g.LabGuard.violations[:3], "best": P["best"]["completion_input_tick"]}


def read_jsonl(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.is_file() else []


def synthetic_run1_all_seeds(lab: Path, max_dispatches: int) -> Path:
    """crossing_search_run2_tests.synthetic_run1 with every key of the frontier's two deepest levels as a seed (32 instead of 12): the
    level-8 seeds bring lineages that reach level-9 keys through different targets, so group moves can happen (the vacuity guard)."""
    import crossing_search_run2_tests as r2t

    syn = r2t.cst.synthetic_frontier(lab)
    out = lab / "crossing_syn"
    prm = {"seeds": 32, "seed_order": "level", "level_decay": 0.5, "novelty_exp": 1.0, "seen_exp": 1.0, "bonus_exp": 1.0, "pace_exp": 0.5, "max_segments": 3,
           "retire_after": 0, "max_cells": 100000, "max_dispatches": max_dispatches, "rng_seed": 3}
    res = r2t.fst.run_child(r2t.cst.child_code(lab, out, syn["out"], "run", prm, expect=syn["expect"]))
    check(res["code"] == 0 and not res["violations"], f"the synthetic run 1: {res}")
    s = json.loads((out / "run" / "summary.json").read_text(encoding="utf-8"))
    check(s["clears"]["verified"] >= 1 and s["status"] == "DISPATCH_CAP", f"the synthetic run 1 needs a verified clear and a clean stop: {s['status']} {s['clears']['verified']}")
    return out


def _fake_exe_path(lab: Path) -> Path:
    return lab / "fake" / "exe" / ("BattleShip.cmd" if os.name == "nt" else "BattleShip")


def _fk_hashes(lab: Path) -> Dict[str, Any]:
    import m8_rd_worker as mw

    exe = _fake_exe_path(lab)
    return {"frozen": {n: mw.sha256_file(exe.parent / n) for n in mw.FROZEN_FILES},
            "exe_copy": {n: mw.sha256_file(exe.parent / n) for n in (exe.name, "BattleShip.o2r", "f3d.o2r", "gamecontrollerdb.txt")}}


class Bench3:
    """A synthetic run 1 (run 1's engine, stub world) and a synthetic run 2 on it (run 2's engine, stub world), then run 3 on the fake game."""

    def __init__(self) -> None:
        import crossing_search_run2_tests as r2t
        import run3_search_tests as r3t

        self.attempts: List[str] = []
        reuse = os.environ.get("RUN3_LAB")                 # a kept fixture lab (RUN3_KEEP=1 of an earlier run): its runs 1 + 2 are reused
        if reuse:
            self.lab, self.run1, self.run2 = Path(reuse), Path(reuse) / "crossing_syn", Path(reuse) / "crossing_syn_run2"
            for d in sorted(self.lab.glob("run3_*")):
                cleanup(d)
            self.attempts.append("reused")
            self.fk = r3t.fake_setup(self.lab) if not (self.lab / "fake").is_dir() else {"exe": str(_fake_exe_path(self.lab)), **_fk_hashes(self.lab)}
            self.port = 44000
            self.runs: Dict[str, Dict[str, Any]] = {}
            return
        for _ in range(4):                       # run 1's engine is not deterministic: a run without a verified clear is retried
            self.lab = tmpdir("run3_night_lab_")
            try:
                self.run1 = synthetic_run1_all_seeds(self.lab, max_dispatches=200)
                self.run2 = self.lab / "crossing_syn_run2"
                res = run_child("run2_child", self.lab, {"lab": str(self.lab), "out": str(self.run2), "run1": str(self.run1), "params": RUN2_PARAMS})
                s2 = json.loads((self.run2 / "run" / "summary.json").read_text(encoding="utf-8"))
                check(res["code"] == 0 and s2["status"] == "DISPATCH_CAP" and not res["violations"], f"the synthetic run 2: {res} {s2['status']}")
                self.attempts.append("ok")
                break
            except AssertionError as exc:
                self.attempts.append(str(exc)[:160])
                cleanup(self.lab)
        else:
            raise AssertionError(f"no usable synthetic runs 1 + 2 in 4 attempts: {self.attempts}")
        self.fk = r3t.fake_setup(self.lab)
        self.port = 44000
        self.runs: Dict[str, Dict[str, Any]] = {}

    def run(self, name: str, prm: Mapping[str, Any] = RUN3_PARAMS, **extra: Any) -> Dict[str, Any]:
        if name in self.runs:
            return self.runs[name]
        out = self.lab / f"run3_{name}"
        self.port += 1000
        res = run_child("engine3_child", self.lab, dict({"lab": str(self.lab), "out": str(out), "run1": str(self.run1), "run2": str(self.run2), "exe": self.fk["exe"],
                                                         "frozen": self.fk["frozen"], "exe_copy": self.fk["exe_copy"], "params": dict(prm), "port_base": self.port}, **extra))
        d = out / "run"
        res.update({"dir": d, "summary": json.loads((d / "summary.json").read_text(encoding="utf-8")), "config": json.loads((d / "config.json").read_text(encoding="utf-8")),
                    "dispatches": read_jsonl(d / "dispatches.jsonl"), "cells": read_jsonl(d / "cells.jsonl"), "hourly": read_jsonl(d / "hourly.jsonl"),
                    "triggers": read_jsonl(d / "triggers.jsonl"), "exports": read_jsonl(d / "exports.jsonl"), "text": read_jsonl(d / "text_replays.jsonl"),
                    "bursts": read_jsonl(d / "anomaly_bursts.jsonl"), "verifications": read_jsonl(d / "verifications.jsonl")})
        self.runs[name] = res
        return res

    def close(self) -> None:
        if os.environ.get("RUN3_KEEP") == "1":
            print(f"kept: {self.lab}")
            return
        cleanup(self.lab)


_BENCH: Optional[Bench3] = None


def bench() -> Bench3:
    global _BENCH
    if _BENCH is None:
        _BENCH = Bench3()
    return _BENCH


RECORD_VOLATILE = ("utc", "best_verified", "verified", "status", "elapsed_s", "dispatches")


def _record_sig(rows: Sequence[Mapping[str, Any]]) -> List[str]:
    return [json.dumps({k: v for k, v in r.items() if k not in RECORD_VOLATILE}, sort_keys=True, default=str) for r in rows]


def e2e_same_seed_runs() -> Dict[str, Any]:
    """Two same-seed run 3s on the fake game (reorder window, step jitter): >= 5 group moves (vacuity guard), and the same dispatches (with
    stream, group, niche), cell rows (with niche, group, moved_from), end records, hourly records and triggers."""
    import crossing_search_run3 as C

    b = bench()
    A, B = b.run("a"), b.run("b")
    for r in (A, B):
        s = r["summary"]
        check(r["code"] == 0 and not r["violations"] and s["status"] == "DISPATCH_CAP" and s["work"]["dispatches"] == RUN3_PARAMS["max_dispatches"]
              and s["contract"] == C.RUN3_CONTRACT, f"a clean stop at the dispatch cap: {r['code']} {r['violations']} {s['status']} {s['stop']} (folder {r['dir']})")
        check(s["integrity"]["prefix_mismatches"] == 0 and s["integrity"]["run3_code_digest_end"] == r["config"]["run3"]["code"]["digest"], "integrity")
        check(all(d.get("stream") in rs.STREAMS and d.get("group") and d.get("niche") is not None for d in r["dispatches"]), "every dispatch row carries stream, group, niche")
        check(all(x.get("niche") is not None and x.get("group") for x in r["cells"] if x["ev"] in ("new", "replaced")), "every NEW / REPLACED row carries niche and group")
    moves = [x for x in A["cells"] if x.get("moved_from")]
    check(len(moves) >= 5, f"vacuity guard: {len(moves)} group moves (>= 5 needed)")
    dsig = lambda r: [s + (d.get("stream"), d.get("group"), d.get("niche"), json.dumps(d.get("draw"), sort_keys=True)) for s, d in
                      zip(det.dispatch_signature(r["dispatches"]), sorted(r["dispatches"], key=lambda d: int(d["n"])))]
    check(dsig(A) == dsig(B), "the same dispatches (with stream, group, niche, draw)")
    csig = lambda r: [s + (x.get("niche"), x.get("group"), x.get("moved_from")) for s, x in zip(det.cells_signature(r["cells"]), r["cells"])]
    check(csig(A) == csig(B), "the same cell rows (with niche, group, moved_from)")
    ends = lambda r: [(x["cid"], x["digest"], x["n"], [v for i, v in enumerate(x["end"]) if i != mcell.HOST_FRAME]) for x in r["cells"] if x["ev"] == "end_record"]
    check(ends(A) == ends(B), "the same end records")
    check(len(A["hourly"]) >= 4 and _record_sig(A["hourly"]) == _record_sig(B["hourly"]), f"the same hourly records ({len(A['hourly'])})")
    tsig = lambda r: [json.dumps({k: v for k, v in t.items() if k != "utc"}, sort_keys=True) for t in r["triggers"]]
    check(tsig(A) == tsig(B), "the same triggers")
    rec = A["hourly"][0]
    check({"groups", "earliest_by_level", "demotions", "breadth", "triggers", "period"} <= set(rec) and all("anchors_detail" in g_ and "share" in g_ and "fall_rate" in g_
                                                                                                         for g_ in rec["groups"]), "the record's fields")
    md = (A["dir"] / "hourly.md").read_text(encoding="utf-8")
    check(all(x in md for x in ("### Groups", "### Demotions and exits", "### Anchors", "### Breadth", "### Anomaly triggers", "Earliest arrival per level")),
          "hourly.md sections")
    sel = A["summary"]["run3"]["selection"]
    streams = sel["streams"]
    check(streams.get("breadth", 0) + streams.get("trigger", 0) >= 10 and streams.get("rank", 0) >= 10, f"both streams used: {streams}")
    # the merged start: run 3's archive = runs 1 + 2
    check(A["summary"]["run3"]["best_start"]["completion_input_tick"] == A["best"] and A["config"]["e7"]["bound_max_L"] == A["bound"], "the start's best and bound")
    for v in A["verifications"]:
        if v["verdict"] == "VERIFIED":
            ex = [x for x in A["exports"] if x["n"] == v["n"]]
            check(ex and ex[0]["roundtrip_ok"] and Path(ex[0]["bk2"]).is_file() and Path(ex[0]["btti"]).is_file(), f"verified clear {v['n']}: exported")
    for t in A["text"]:
        check(t.get("equal") is True, f"text replay of a new best: {t}")
    return {"moves": len(moves), "dispatches": len(A["dispatches"]), "streams": streams, "hourly": len(A["hourly"]), "triggers": len(A["triggers"]),
            "verified": sum(1 for v in A["verifications"] if v["verdict"] == "VERIFIED"), "exports": len(A["exports"]), "text_replays": len(A["text"]),
            "eligible_at_start": A["eligible"], "groups_at_start": len([r for r in A["start"] if r["eligible"]]), "events": len(sel["events"])}


def e2e_nonfinite_trigger() -> Dict[str, Any]:
    """Non-finite replies on the fake game (FAKEGAME_NONFINITE_*), rule (b) of 2026-11-06: every non-finite burst that triggers queues one
    cell, the burst's last kept eligible cell or, when it kept none, the dispatched cell; the queued cells are served as trigger draws within
    the cap and the records show them; the runs stop cleanly with no prefix mismatch."""
    b = bench()
    # 1. observation.position_x (in the record and the key) past every eligible prefix: rarity stops the triggers at 3; each queues one cell
    first = b.run("a")
    bound = int(first["bound"])
    r0 = b.run("nf0", dict(RUN3_PARAMS, summary_every_dispatches=40), worker_flags={"FAKEGAME_NONFINITE_P": "0.01", "FAKEGAME_NONFINITE_SEED": "3",
                                                                                    "FAKEGAME_NONFINITE_FIELD": "observation.position_x",
                                                                                    "FAKEGAME_NONFINITE_MIN_STEP": str(bound + 2)})
    s0 = r0["summary"]
    check(r0["code"] == 0 and s0["status"] == "DISPATCH_CAP" and s0["integrity"]["prefix_mismatches"] == 0, f"a clean stop: {r0['code']} {s0['status']} {s0['stop']}")
    check([d for d in r0["dispatches"] if d.get("outcome") == "nonfinite"], "at least one burst met a non-finite reply")
    t0 = r0["triggers"]
    check(len(t0) == 3 and all(t["classes"] == ["nonfinite"] for t in t0) and s0["run3"]["selection"]["classes_seen"]["nonfinite"] > 3,
          f"rarity: exactly 3 triggers of the class {[(t['n'], t['classes']) for t in t0]} {s0['run3']['selection']['classes_seen']}")
    # 2. spatial.update_tic (in neither the record nor the key) from tick 1, rarity 50: triggers at eligible ticks queue cells, served in turn
    r = b.run("nf", dict(RUN3_PARAMS, summary_every_dispatches=40, trigger_rarity=50), worker_flags={"FAKEGAME_NONFINITE_P": "0.002", "FAKEGAME_NONFINITE_SEED": "5",
                                                                                                     "FAKEGAME_NONFINITE_FIELD": "spatial.update_tic",
                                                                                                     "FAKEGAME_NONFINITE_MIN_STEP": "1"})
    s = r["summary"]
    check(r["code"] == 0 and s["status"] == "DISPATCH_CAP" and s["integrity"]["prefix_mismatches"] == 0, f"a clean stop: {r['code']} {s['status']} {s['stop']}")
    nf = [d for d in r["dispatches"] if d.get("outcome") == "nonfinite"]
    check(nf, "at least one burst met a non-finite reply")
    trig = r["triggers"]
    check(trig and all(t["classes"] == ["nonfinite"] for t in trig) and len(trig) <= 50, f"triggers: {[(t['n'], t['classes'], t['cells']) for t in trig]}")
    sel = s["run3"]["selection"]
    given = sum(t["draws_given"] for t in sel["triggers"])
    queued = sum(t["draws_queued"] for t in sel["triggers"])
    check(sel["streams"].get("trigger", 0) == given and given <= 0.1 * (sel["streams"].get("trigger", 0) + sel["streams"].get("breadth", 0)) + 1e-9,
          f"trigger draws {given} (queued {queued}) within 10 % of breadth draws {sel['streams']}")
    check(sel["classes_seen"].get("nonfinite", 0) >= len(trig), f"classes seen {sel['classes_seen']}")
    md = (r["dir"] / "hourly.md").read_text(encoding="utf-8")
    check("Trigger 0:" in md or not queued, "hourly.md lists the trigger")
    served = [d for d in r["dispatches"] if d.get("stream") == "trigger"]
    cells_q = {c for t in trig for c, _t in t["cells"]}
    check(all(d["cid"] in cells_q for d in served), "every trigger draw is a queued cell")
    by_n = {int(d["n"]): d for d in r["dispatches"]}
    check(len(trig) == len(nf) and all(t["first_tick"] == int(by_n[t["n"]]["start_tick"]) + int(by_n[t["n"]]["words_played"]) for t in trig),
          f"one trigger per non-finite burst (rarity 50), at the burst's cut tick: {len(trig)} triggers, {len(nf)} bursts")
    # rule (b): one cell per trigger, the burst's last kept cell (one of its kept cell ids, the latest) or the dispatched cell
    rules: Counter = Counter()
    for t_ in trig:
        d = by_n[int(t_["n"])]
        check(len(t_["cells"]) == 1 and t_["draws_queued"] == 3, f"trigger {t_['index']}: one cell, 3 draws {t_}")
        cid, tick = t_["cells"][0]
        rules[t_["rule"][0]] += 1
        if t_["rule"] == ["last_kept_before_null"]:
            check(cid in d["kept"]["cids"] and tick < t_["first_tick"] + 1, f"trigger {t_['index']}: a kept cell of the burst before the null {t_} {d['kept']}")
        else:
            check(t_["rule"] == ["dispatched_cell"] and cid == int(d["cid"]) and not [c for c in d["kept"]["cids"]], f"trigger {t_['index']}: the dispatched cell {t_} {d['kept']}")
    for t_ in t0:
        check(len(t_["cells"]) == 1 and t_["rule"][0] in ("last_kept_before_null", "dispatched_cell"), f"nf0 trigger {t_['index']}: one cell {t_}")
    check(queued > 0 and given >= 1 and len(served) == given, f"cells were queued ({queued} draws) and served ({given} trigger draws, {len(served)} rows)")
    for run_ in (r0, r):
        check(not run_["violations"], f"no guard violation: {run_['violations']}")
        for v_ in run_["verifications"]:
            if v_["verdict"] == "VERIFIED":
                ex_ = [x for x in run_["exports"] if x["n"] == v_["n"]]
                check(ex_ and ex_[0].get("roundtrip_ok") is True and not ex_[0].get("error"), f"verified clear {v_['n']}: exported {ex_}")
        check(all(t_.get("equal") is True for t_ in run_["text"]), f"text replays of new bests: {run_['text']}")
    check("Trigger 0:" in md and "draws queued" in md, "hourly.md lists the triggers")
    return {"run_nf0_triggers": len(t0), "nonfinite_bursts": len(nf), "triggers": len(trig), "queued": queued, "given": given, "rules": dict(rules),
            "streams": sel["streams"]}


def guarded_exports_child(a: Mapping[str, Any]) -> Dict[str, Any]:
    """In a child with the lab guard installed (as the engine runs): the export writer and one fake-game text replay of real words."""
    import frs_guard as g

    lab = Path(a["lab"])
    words = bytes.fromhex(a["words_hex"])
    ex = rx.export_clear(g.LabFS(lab), lab / "guarded" / "clears", "clear_test", words, {"n": 1})
    rep = rx.make_text_replay(Path(a["exe"]), lab / "guarded" / "text_replays")(words, "best")
    v = rx.text_replay_verdict(rep, int(a["cit"]), int(a["ctp"]))
    return {"export": ex, "verdict": v, "violations": g.LabGuard.violations[:5]}


def e2e_exports_under_guard() -> Dict[str, Any]:
    """The .btt.txt / .bk2 export and the text replay under the lab guard: no path holds the provenance fragment '.btti', nothing is
    refused, the round trip holds and the text replay gives the verified clocks (a defect found 2026-11-06: the guard refused '.btti')."""
    import crossing_search_run2 as r2

    b = bench()
    R1 = r2.read_run1(b.run1)
    best = r2.best_verified_of(R1["verifications"], 10 ** 9)
    res = run_child("guarded_exports_child", b.lab, {"lab": str(b.lab), "exe": b.fk["exe"], "words_hex": bytes(best["words"]).hex(),
                                                     "cit": best["completion_input_tick"], "ctp": best["completion_time_passed"]})
    ex, v = res["export"], res["verdict"]
    check(not res["violations"], f"no guard refusal: {res['violations']}")
    check(ex.get("roundtrip_ok") is True and ex["btti"].endswith(rx.TEXT_SUFFIX) and ".btti" not in ex["btti"] and Path(ex["bk2"]).is_file()
          and Path(ex["btti"]).is_file(), f"the export: {ex}")
    check(v["equal"] is True, f"the guarded text replay gives the verified clocks: {v}")
    return {"export": Path(ex["btti"]).name, "clocks": v["clocks_text"]}


def unit_export_clear() -> Dict[str, Any]:
    """The export writer through the lab's guarded file system: a .btti and a .bk2 under the run folder, the round trip, the digests."""
    import frs_guard as g

    lab = tmpdir("run3_export_lab_")
    try:
        fs = g.LabFS(lab)
        words = bytes((5 * i + 1) % mcell.TRACK1_WORDS for i in range(300))
        ex = rx.export_clear(fs, lab / "run" / "clears", "clear_n7_t300", words, {"n": 7, "completion_input_tick": 300})
        check(ex["roundtrip_ok"] and Path(ex["bk2"]).is_file() and Path(ex["btti"]).is_file() and ex["frames"] == 300
              and ex["words_digest"] == mcell.words_digest(words), f"export {ex}")
        check(rx.bk2_rows(Path(ex["bk2"]).read_bytes()) and len(Path(ex["btti"]).read_text(encoding="ascii").splitlines()) == 303, "the files' contents")
    finally:
        cleanup(lab)
    return {"bk2_sha256": ex["bk2_sha256"][:16]}


def e2e_detector_trigger_fallback() -> Dict[str, Any]:
    """Detector triggers on the fake game (owner 2026-11-06): with classes the stub world raises (position_snap, beyond_camera_bounds)
    as trigger classes for this run only and rarity 50, every trigger queues one or more cells: the kept cells at or after the event, or
    else the burst's last kept cell, or else the dispatched cell; the fallbacks are exercised and the queued cells are served."""
    b = bench()
    r = b.run("det", dict(RUN3_PARAMS, trigger_classes=["position_snap", "beyond_camera_bounds"], trigger_rarity=50))
    s = r["summary"]
    check(r["code"] == 0 and s["status"] == "DISPATCH_CAP" and s["integrity"]["prefix_mismatches"] == 0 and not r["violations"],
          f"a clean stop: {r['code']} {s['status']} {s['stop']} {r['violations']}")
    trig = r["triggers"]
    by_n = {int(d["n"]): d for d in r["dispatches"]}
    rules: Counter = Counter()
    for t in trig:
        d = by_n[int(t["n"])]
        rules[t["rule"][0]] += 1
        check(t["cells"] and t["rule"][0] in ("kept_at_or_after_event", "last_kept_cell", "dispatched_cell"), f"trigger {t['index']} queues a cell: {t}")
        if t["rule"] == ["last_kept_cell"]:
            check(len(t["cells"]) == 1 and t["cells"][0][0] in d["kept"]["cids"] and t["cells"][0][1] < t["first_tick"] + 1 + 10 ** 6,
                  f"trigger {t['index']}: the burst's last kept cell {t} {d['kept']}")
        if t["rule"] == ["dispatched_cell"]:
            check(t["cells"] == [[int(d["cid"]), t["cells"][0][1]]] and not d["kept"]["cids"], f"trigger {t['index']}: the dispatched cell {t} {d['kept']}")
    check(trig and (rules["last_kept_cell"] + rules["dispatched_cell"]) >= 1, f"the fallback was exercised: {dict(rules)} over {len(trig)} triggers")
    sel = s["run3"]["selection"]
    served = [d for d in r["dispatches"] if d.get("stream") == "trigger"]
    queued = {c for t in trig for c, _t in t["cells"]}
    check(served and all(d["cid"] in queued for d in served) and len(served) <= 0.1 * (sel["streams"].get("breadth", 0) + len(served)) + 1e-9,
          f"queued cells served within the cap: {len(served)} of {sel['streams']}")
    return {"triggers": len(trig), "rules": dict(rules), "served": len(served)}


def e2e_frozen_run_not_inherited() -> Dict[str, Any]:
    """A run 3 folder marked CLAIMS_FROZEN (a copy of a real fake-game run with that status) is refused by a later plan as a --best-from
    source and by the engine as an end-record source, and admitted only when the plan's --accept-run names it (owner 2026-11-06)."""
    import crossing_search as cs
    import crossing_search_run3 as C
    import frs_guard as g
    import frs_machine as fm
    import frs_run as fr
    import frs_verify as fv
    import m8_rd_stub as stub
    import run3_manifest as rm
    import run3_search_tests as r3t

    b = bench()
    A = b.run("a")
    frz = b.lab / "run3_frz_copy"
    if frz.exists():
        cleanup(frz)
    shutil.copytree(A["dir"].parent, frz)
    _json_edit(frz / "run" / "summary.json", status=C.CLAIMS_FROZEN, run3=dict(A["summary"]["run3"], claims_frozen={"n": 0, "archive": "to_investigate"}))
    params = C.Params3(**RUN3_PARAMS)
    code = rm.code_digest(rm.run3_code_manifest())
    try:
        C.build_plan(b.lab, b.run1, b.run2, params, stub.analyse, code_digest=code, best_from=[frz])
        raise AssertionError("a CLAIMS_FROZEN folder was accepted as a best source")
    except cs.SearchError as exc:
        check("--accept-run" in str(exc), f"refused with the flag named: {exc}")
    P = C.build_plan(b.lab, b.run1, b.run2, params, stub.analyse, code_digest=code, best_from=[frz], accept_runs=[frz])
    check(P["plan"]["run3"]["best_from"][0]["accepted_non_clean"] is True and P["accept_runs"] == [str(frz)], "admitted when named, recorded in the plan")
    run_dir = b.lab / "run3_frz_engine" / "run"
    fk = {"exe": b.fk["exe"], "frozen": b.fk["frozen"]}
    env = fr.LabEnv(worker_spec=lambda rank: r3t.worker_spec(b.lab, fk, rank, 47000, run_dir / "failures", FLAGS),
                    replay=fv.make_real_replay(Path(b.fk["exe"]), b.lab / "run_replays", FLAGS, {"frozen_sha256": b.fk["frozen"], "exe_copy_sha256": b.fk["exe_copy"]}),
                    analyse=stub.analyse, readiness=lambda: {"ok": True, "problems": []}, battleship_pids=lambda: [], snapshot=fm.tree_snapshot,
                    import_problems=lambda: [], wait_no_battleship=lambda t: [], code_manifest=fr.code_manifest, backend="real", sample_s=0.25, row_every_s=0.5,
                    caps=dict(fm.CAPS_MB, main_private=1e9))
    cfg = cs.SearchConfig(lab_root=b.lab, out=run_dir.parent, run_dir=run_dir, frontier_dir=b.run1, n_workers=1, max_ticks=10 ** 9, max_wall_s=60.0, expect_code=None)
    P2 = C.build_plan(b.lab, b.run1, b.run2, params, stub.analyse, code_digest=code)
    P2["end_record_files"] = [str(frz / "run" / "cells.jsonl")]
    try:
        C.Run3Night(cfg, env, P2, params, text_replay=None, anomaly_build={})
        raise AssertionError("end records of a CLAIMS_FROZEN run were imported")
    except cs.SearchError as exc:
        check("did not stop cleanly" in str(exc), f"the end-record import refused: {exc}")
    P3 = C.build_plan(b.lab, b.run1, b.run2, params, stub.analyse, code_digest=code, accept_runs=[frz])
    P3["end_record_files"] = [str(frz / "run" / "cells.jsonl")]
    eng = C.Run3Night(cfg, env, P3, params, text_replay=None, anomaly_build={})
    check(eng.end_import["records"] >= 1 and not run_dir.exists() and not g.LabGuard.violations, f"admitted when the plan names it: {eng.end_import}")
    return {"refused": 2, "admitted_records": eng.end_import["records"]}


def e2e_inherit_a_to_b() -> Dict[str, Any]:
    """Run B inherits run A on the fake game (owner 2026-11-09): B's archive is A's final one (every cell id, A's new cells included), B's new
    cells continue the ids after them, A's end records are imported, B's history for every group is run 2's plus A's own totals (n, falls,
    b, e), rule a for the windows; B stops cleanly. A CLAIMS_FROZEN copy of A is refused unless --accept-run names it, a copy with one
    niche label altered is refused, and A followed by a sibling (a copy of A) is refused."""
    import crossing_search as cs
    import crossing_search_run3 as C
    import m8_rd_stub as stub
    import run3_manifest as rm

    b = bench()
    A = b.run("a")
    adir = A["dir"].parent
    B = b.run("b_inherits_a", inherit=[str(adir)])
    check(B["code"] == 0 and not B["violations"] and B["summary"]["status"] in ("DISPATCH_CAP", "WALL_CAP"), f"run B: {B['code']} {B['summary']['status']}")
    a_new = sum(1 for r in A["cells"] if r.get("ev") == "new")
    a_rows = sum(1 for r in A["cells"] if r.get("ev") in ("new", "replaced"))
    a_plan_archive = json.loads((adir / "plan.json").read_text(encoding="utf-8"))["archive"]
    rep = (B["inherit"] or [{}])[0]
    check(rep.get("rows") == rep.get("niche_equal") == a_rows and rep.get("new_cells") == a_new and rep.get("history_dispatches") == len(A["dispatches"]),
          f"A's rows, niches and dispatches: {rep} vs rows {a_rows} new {a_new} dispatches {len(A['dispatches'])}")
    check(B["inherited"] == int(a_plan_archive["inherited"]) + a_new, f"B inherits A's final archive: {B['inherited']} = {a_plan_archive['inherited']} + {a_new}")
    b_new = [int(r["cid"]) for r in B["cells"] if r.get("ev") == "new"]
    check(not b_new or min(b_new) == B["inherited"], f"B's new cell ids continue after A's: {min(b_new) if b_new else None} vs {B['inherited']}")
    e = B["summary"]["run3"]["end_records"]
    check(B["end_record_files"] == [str(adir / "run" / "cells.jsonl")] and e["imported"] >= 1, f"A's end records imported: {e}")
    a_tab = {r["group"]: r["run3"] for r in A["summary"]["run3"]["selection"]["table"]}
    a_plan = json.loads((adir / "plan.json").read_text(encoding="utf-8"))
    hist0 = a_plan["run3"]["history"]["groups"]
    bad = [gl for gl, h in B["history"].items() if any(int(h[k]) != int(hist0.get(gl, {}).get(k, 0)) + int(a_tab.get(gl, {}).get(k, 0)) for k in ("n", "fall", "b", "e"))]
    check(not bad, f"B's history = run 2's + A's own totals: {bad[:4]}")
    check(str(B["windows_rule"]).startswith("a:"), "rule a")
    # refusals, plan only
    params = C.Params3(**RUN3_PARAMS)
    code = rm.code_digest(rm.run3_code_manifest())
    refused: Dict[str, str] = {}
    frz = b.lab / "run3_inherit_frozen"
    shutil.copytree(adir, frz)
    _json_edit(frz / "run" / "summary.json", status=C.CLAIMS_FROZEN)
    try:
        C.build_plan(b.lab, b.run1, b.run2, params, stub.analyse, code_digest=code, inherit=[frz])
        raise AssertionError("a CLAIMS_FROZEN folder was inherited")
    except (cs.SearchError, C.rl3.LoadError) as exc:
        refused["frozen"] = str(exc)[-400:]
    Pf = C.build_plan(b.lab, b.run1, b.run2, params, stub.analyse, code_digest=code, inherit=[frz], accept_runs=[frz])
    check(Pf["plan"]["run3"]["inherit"][0]["accepted_non_clean"] is True, "a frozen folder named by --accept-run is admitted and recorded")
    alt = b.lab / "run3_inherit_altered"
    shutil.copytree(adir, alt)
    lines = (alt / "run" / "cells.jsonl").read_text(encoding="utf-8").splitlines()
    i = next(k for k, x in enumerate(lines) if json.loads(x).get("ev") in ("new", "replaced"))
    r = json.loads(lines[i])
    r["niche"] = r["niche"] + "-0"
    lines[i] = json.dumps(r, separators=(",", ":"))
    (alt / "run" / "cells.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        C.build_plan(b.lab, b.run1, b.run2, params, stub.analyse, code_digest=code, inherit=[alt])
        raise AssertionError("a folder whose recorded niche differs was inherited")
    except (cs.SearchError, C.rl3.LoadError) as exc:
        refused["niche"] = str(exc)[-400:]
    sib = b.lab / "run3_inherit_sibling"
    shutil.copytree(adir, sib)
    try:
        C.build_plan(b.lab, b.run1, b.run2, params, stub.analyse, code_digest=code, inherit=[adir, sib])
        raise AssertionError("a sibling folder was inherited after A")
    except (cs.SearchError, C.rl3.LoadError) as exc:
        refused["sibling"] = str(exc)[-400:]
    check("--accept-run" in refused["frozen"] and "niche" in refused["niche"] and "sibling" in refused["sibling"], f"the refusals: {refused}")
    for d in (frz, alt, sib):
        cleanup(d)
    return {"inherited": B["inherited"], "a_new": a_new, "end_imported": e["imported"], "refused": sorted(refused)}


def e2e_text_replay() -> Dict[str, Any]:
    """The native text-replay path on the fake game: run 1's best verified clear replayed from its words gives its verified clocks; a
    truncated copy gives no clear."""
    import crossing_search_run2 as r2

    b = bench()
    R1 = r2.read_run1(b.run1)
    best = r2.best_verified_of(R1["verifications"], 10 ** 9)
    fn = rx.make_text_replay(Path(b.fk["exe"]), b.lab / "text_replay_test")
    rep = fn(bytes(best["words"]), "best")
    v = rx.text_replay_verdict(rep, best["completion_input_tick"], best["completion_time_passed"])
    check(v["equal"] is True, f"the text replay gives the verified clocks: {v} {rep}")
    cut = rx.text_replay_verdict(fn(bytes(best["words"])[:-5], "cut"), best["completion_input_tick"], best["completion_time_passed"])
    check(cut["equal"] is False and cut["outcome"] is None, f"a cut copy: no clear {cut}")
    return {"clocks": v["clocks_text"], "wall_s": rep.get("wall_s")}


UNIT = {"unit_niche_inheritance": unit_niche_inheritance, "unit_moves": unit_moves, "unit_demotion_and_shares": unit_demotion_and_shares,
        "unit_rolling_demotion": unit_rolling_demotion, "unit_demotion_hysteresis": unit_demotion_hysteresis,
        "unit_zero_break_demotion": unit_zero_break_demotion,
        "unit_new_earliest_in_demoted_group": unit_new_earliest_in_demoted_group,
        "unit_e_and_anchor_success": unit_e_and_anchor_success, "unit_draws": unit_draws, "unit_triggers": unit_triggers, "unit_trigger_fallback": unit_trigger_fallback, "unit_claims_frozen": unit_claims_frozen,
        "unit_non_clean_sources_refused": unit_non_clean_sources_refused, "unit_plan_flags_match_saved_plan": unit_plan_flags_match_saved_plan,
        "unit_real_windows": unit_real_windows, "unit_inherit_chain": unit_inherit_chain, "unit_level_weights": unit_level_weights,
        "unit_bk2_roundtrip": unit_bk2_roundtrip,
        "unit_export_clear": unit_export_clear, "unit_params": unit_params}
CELL_ATTRS = ("cid", "key", "level", "tick", "lead", "words", "end", "end_digest", "chain", "digest", "origin", "created_at", "seen", "dispatched", "fresh",
              "breaks", "new_children", "replaced", "quarantined", "retired", "next_k", "first_level_reach", "previous", "inherited", "verified", "pending",
              "cleared", "root", "check_attempts")


def real_plan_via_child_equal() -> Dict[str, Any]:
    """The run's plan route (a child process, payload, archive rebuilt here) gives exactly build_plan's result: every attribute of all
    37,294 cells, the archive's indexes and counters, the plan, the start table. The payload is written to a temporary folder under the
    lab root (the child runs under the lab guard) and removed."""
    if not (LAB / "import" / "import_manifest.json").is_file() or not RUN2_REAL.is_dir():
        return {"skipped": f"no lab import or runs under {LAB}"}
    import crossing_search_run3 as C

    params = C.Params3(rng_seed=1, summary_every_s=600.0)
    A = C.build_plan(LAB, RUN1_REAL, RUN2_REAL, params, code_digest="test")
    tmp = LAB / "probes" / f"run3_plan_child_test_{os.getpid()}"
    tmp.mkdir(parents=True)
    try:
        B = C.plan_via_child(LAB, RUN1_REAL, RUN2_REAL, tmp, params, code_digest="test")
        check(not any(tmp.iterdir()), f"the payload was removed: {list(tmp.iterdir())}")
    finally:
        cleanup(tmp)
    a, b = A["archive"], B["archive"]
    diffs = [(c.cid, k) for c, d in zip(a.cells, b.cells) for k in CELL_ATTRS if getattr(c, k, None) != getattr(d, k, None)]
    check(len(a.cells) == len(b.cells) == 37294 and not diffs, f"{len(diffs)} cell attributes differ, first {diffs[:5]}")
    for k in ("by_key", "by_level", "counts", "_pos", "inherited", "bound", "arrival", "archive_id", "words_bytes", "root_by_rep"):
        check(getattr(a, k) == getattr(b, k), f"the archive's {k} differs")
    check({lv: (e["tick"], e["cid"]) for lv, e in a.earliest.items()} == {lv: (e["tick"], e["cid"]) for lv, e in b.earliest.items()}, "earliest per level")
    plan_a = {k: v for k, v in A["plan"].items() if k != "utc"}
    plan_b = {k: v for k, v in B["plan"].items() if k != "utc"}
    check(json.dumps(plan_a, sort_keys=True, default=str) == json.dumps(plan_b, sort_keys=True, default=str), "the same plan")
    for k in ("bound", "bound_run1", "cleared", "run3_code_digest"):
        check(A[k] == B[k], f"P[{k!r}] differs")
    check(A["best"] == B["best"] and A["R"] == B["R"] and A["meta"] == B["meta"] and A["run3"] == B["run3"], "best, reference, meta, run 3 inputs")
    sa = rs.Run3Selector(a, params, niches=A["run3"]["niches"], history=A["run3"]["history"], cid_dispatches=A["run3"]["cid_dispatches"], best_claim=A["run3"]["best_claim"],
                         history_tails=A["run3"]["history_tails"])
    sb = rs.Run3Selector(b, params, niches=B["run3"]["niches"], history=B["run3"]["history"], cid_dispatches=B["run3"]["cid_dispatches"], best_claim=B["run3"]["best_claim"],
                         history_tails=B["run3"]["history_tails"])
    check(sa.start == sb.start, "the same start table")
    el = [r for r in sb.start if r["eligible"]]
    check(len(el) == 14 and sum(r["anchors"] for r in el) == 153 and [r["group"] for r in el if r["demoted"]] == ["9|64|326:2-8-1"], "14 groups, 153 anchors, (9, 64) demoted")
    return {"cells": len(b.cells), "attributes_compared": len(CELL_ATTRS), "groups": len(el)}


SMOKE_REAL = LAB / "crossing_2026-11-06_run3_smoke"


def real_best_from_smoke() -> Dict[str, Any]:
    """Option (c), owner 2026-11-06: the archive of runs 1 + 2, the best and the bound from every verified clear, the smoke run's included
    (1,196 -> bound 1,171); the cell that produced the 1,196 stays eligible; a source folder that is not clean, or whose best has no equal
    text replay, is refused (copies under a temporary folder of the lab, removed)."""
    if not (SMOKE_REAL / "run" / "summary.json").is_file():
        return {"skipped": f"no smoke run under {SMOKE_REAL}"}
    import crossing_search as cs
    import crossing_search_run3 as C

    P = C.build_plan(LAB, RUN1_REAL, RUN2_REAL, C.Params3(rng_seed=2), code_digest="test", best_from=[SMOKE_REAL])
    p = P["plan"]
    check(p["best"]["completion_input_tick"] == 1196 and p["best"]["source"] == "run3:crossing_2026-11-06_run3_smoke" and p["e7"]["bound_max_L"] == 1171
          and P["bound"] == 1171 and p["run3"]["best_claim"] == 1196 and p["archive"]["inherited"] == 37294, f"{p['e7']} {p['best']}")
    c = P["archive"].cells[12331]
    check(c.level == 9 and c.tick == 1114 and P["archive"].eligible(c), f"the 1,196's start cell: level {c.level} tick {c.tick}")
    el = [r for r in p["run3"]["start"] if r["eligible"]]
    check(all(r["earliest_eligible"] <= 1171 for r in el) and sum(r["eligible"] for r in el) == p["archive"]["eligible"], "eligibility at 1,171")
    tmp = LAB / "probes" / f"run3_best_from_test_{os.getpid()}"
    refused = {}
    try:
        for name, edit in (("unclean", lambda d: _json_edit(d / "run" / "summary.json", status="SEARCH_INVALID")),
                           ("no_text_replay", lambda d: (d / "run" / "text_replays.jsonl").unlink())):
            d = tmp / name
            (d / "run").mkdir(parents=True)
            for f in ("plan.json", "run/summary.json", "run/config.json", "run/verifications.jsonl", "run/text_replays.jsonl", "run/dispatches.jsonl"):
                (d / f).write_bytes((SMOKE_REAL / f).read_bytes())
            edit(d)
            try:
                C.build_plan(LAB, RUN1_REAL, RUN2_REAL, C.Params3(rng_seed=2), code_digest="test", best_from=[d])
                refused[name] = None
            except cs.SearchError as exc:
                refused[name] = str(exc)[:120]
    finally:
        cleanup(tmp)
    check(all(refused.values()), f"refusals: {refused}")
    return {"bound": P["bound"], "eligible": p["archive"]["eligible"], "groups": len(el), "refused": sorted(refused)}


NIGHT_REAL = LAB / "crossing_2026-11-06_run3"
NIGHT_953 = [("9|2|326:2-6-8", 39, 925, 6, 1.0, 0.005), ("8|258|326:2-6", 224, 869, 8, 1.0, 0.0545), ("7|70|326:8", 418, 894, 12, 0.167, 0.005),
             ("7|262|326:6", 385, 789, 12, 0.167, 0.005), ("7|266|330:6", 210, 879, 12, 0.167, 0.005), ("7|322|322:", 2002, 493, 12, 0.167, 0.005),
             ("7|322|326:2", 2992, 499, 12, 0.167, 0.005), ("7|322|330:3", 162, 651, 9, 0.167, 0.005), ("6|326|326:", 4847, 461, 12, 0.556, 0.0495),
             ("6|330|330:", 4521, 486, 12, 0.444, 0.0396)]


def real_inherit_night_table() -> Dict[str, Any]:
    """The plan inheriting run 3's night (owner 2026-11-09) reproduces the 953 start table shown before the build (zero-tick prototype): best
    978 from the night, bound 953, 46,240 cells, 15,800 eligible, the ten groups' eligible cells, earliest, anchors, shares and rates; every
    night row keeps its recorded niche; the night's 41,737 dispatches replay to its own per-group totals; its cells file gives the end records."""
    import crossing_search_run3 as C

    P = C.build_plan(LAB, RUN1_REAL, RUN2_REAL, C.Params3(rng_seed=3), code_digest="test", inherit=[NIGHT_REAL])
    p = P["plan"]
    check(P["bound"] == 953 and p["best"]["completion_input_tick"] == 978 and p["best"]["source"] == "run3:crossing_2026-11-06_run3",
          f"best and bound: {p['best']} {P['bound']}")
    check(p["archive"]["inherited"] == 46240 and p["archive"]["eligible"] == 15800, f"the archive: {p['archive']['inherited']} / {p['archive']['eligible']}")
    el = [r for r in p["run3"]["start"] if r["eligible"]]
    got = [(r["group"], r["eligible"], r["earliest_eligible"], r["anchors"], round(r["share"], 3), round(r["rho"], 4)) for r in el]
    check(got == NIGHT_953 and not [r for r in el if r["demoted"]], f"the 953 table: {got}")
    rep = p["run3"]["inherit"][0]
    check(rep["rows"] == rep["niche_equal"] == 74924 and rep["history_dispatches"] == 41737 and rep["history_groups_checked"] == 23
          and rep["end_record_rows"] == 4314 and P["end_record_files"] == [str(NIGHT_REAL / "run" / "cells.jsonl")], f"the night's checks: {rep}")
    check(p["run3"]["windows_rule"].startswith("a:"), "rule a")
    return {"groups": len(el), "eligible": p["archive"]["eligible"], "niche_equal": rep["niche_equal"]}


NIGHT2_REAL = LAB / "crossing_2026-11-10_run3b"
ZERO_BREAK_DEMOTED_934 = ["7|322|330:3", "7|74|330:8", "9|256|326:2-6-1"]


def real_two_nights_zero_break() -> Dict[str, Any]:
    """Night 3's plan (owner 2026-11-11: both nights inherited in order, best 959, bound 934) under the zero-break rule demotes exactly the
    three groups the replay names (tools/analysis/run3_design/d2_zero_break_replay.py: (7, 322, 330:3) 0 breaks in 2,114, (7, 74, 330:8)
    1,184 without a break, (9, 256, 326:2-6-1) 4,482 without), so (9, 2, 326:2-6-8) takes 1 - phi / 4 of level 9 instead of half; under
    the v3 thresholds the same plan demotes no group with an eligible cell (the table planned before the change). Archive and eligibility
    are the same under both."""
    if not (NIGHT_REAL / "run" / "summary.json").is_file() or not (NIGHT2_REAL / "run" / "summary.json").is_file():
        return {"skipped": f"no inherited nights under {LAB}"}
    import crossing_search_run3 as C

    out = {}
    for name, kw in (("zero_break", {}), ("v3", {"demote_fall_rate": 0.75, "demote_exit_fall_rate": 0.70})):
        P = C.build_plan(LAB, RUN1_REAL, RUN2_REAL, C.Params3(rng_seed=4, **kw), code_digest="test", inherit=[NIGHT_REAL, NIGHT2_REAL])
        p = P["plan"]
        el = {r["group"]: r for r in p["run3"]["start"] if r["eligible"]}
        out[name] = {"bound": P["bound"], "best": p["best"]["completion_input_tick"], "eligible": p["archive"]["eligible"], "groups": len(el),
                     "demoted": sorted(g for g, r in el.items() if r["demoted"]), "share_9_2": round(el["9|2|326:2-6-8"]["share"], 6),
                     "share_9_256": round(el["9|256|326:2-6-1"]["share"], 6), "table": {g: (r["eligible"], r["anchors"], r["earliest_eligible"]) for g, r in el.items()}}
    z, v = out["zero_break"], out["v3"]
    check(z["bound"] == v["bound"] == 934 and z["best"] == v["best"] == 959 and z["eligible"] == v["eligible"] == 17813 and z["groups"] == v["groups"] == 14
          and z["table"] == v["table"], f"the same archive and groups: {[(k, z[k], v[k]) for k in ('bound', 'best', 'eligible', 'groups')]}")
    check(z["demoted"] == ZERO_BREAK_DEMOTED_934 and v["demoted"] == [], f"demoted: zero-break {z['demoted']}, v3 {v['demoted']}")
    check(abs(z["share_9_2"] - (1 - 0.125 / 4)) < 1e-6 and abs(z["share_9_256"] - 0.125 / 4) < 1e-6 and abs(v["share_9_2"] - 0.5) < 1e-6,
          f"level 9: (9, 2) {v['share_9_2']} -> {z['share_9_2']}, (9, 256) {v['share_9_256']} -> {z['share_9_256']}")
    return {k: {x: y for x, y in r.items() if x != "table"} for k, r in out.items()}


def _json_edit(path: Path, **kw: Any) -> None:
    obj = json.loads(path.read_text(encoding="utf-8"))
    obj.update(kw)
    path.write_text(json.dumps(obj), encoding="utf-8")


REAL = {"real_niches_equal_offline": real_niches_equal_offline, "real_start_table": real_start_table,
        "real_plan_via_child_equal": real_plan_via_child_equal, "real_best_from_smoke": real_best_from_smoke,
        "real_inherit_night_table": real_inherit_night_table, "real_two_nights_zero_break": real_two_nights_zero_break}
E2E = {"e2e_same_seed_runs": e2e_same_seed_runs, "e2e_nonfinite_trigger": e2e_nonfinite_trigger,
       "e2e_detector_trigger_fallback": e2e_detector_trigger_fallback, "e2e_frozen_run_not_inherited": e2e_frozen_run_not_inherited,
       "e2e_inherit_a_to_b": e2e_inherit_a_to_b, "e2e_text_replay": e2e_text_replay, "e2e_exports_under_guard": e2e_exports_under_guard}

if __name__ == "__main__":
    args = sys.argv[1:]
    groups = {"unit": UNIT, "real": REAL, "e2e": E2E}
    tests = dict(groups[args[0]]) if args[:1] and args[0] in groups else dict(UNIT, **REAL, **E2E)
    rest = [x for x in args if x not in groups]
    try:
        code = run_suite("run3 night tests", tests, rest)
    finally:
        if _BENCH is not None:
            _BENCH.close()
    sys.exit(code)
