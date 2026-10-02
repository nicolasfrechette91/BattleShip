#!/usr/bin/env python3
"""M8-rd2 offline tests: zero native ticks. No BattleShip launch, no replay on a real process, no training.

    python rl/m8_rd2_tests.py unit [--out DIR] [--only NAME[,NAME]]
    python rl/m8_rd2_tests.py e2e  [--out DIR] [--small]      # the production-count synthetic end-to-end run of the resume path
    python rl/m8_rd2_tests.py list

The synthetic native stand-in is rl/m8_rd_stub.py (a deterministic platformer that speaks the SSB64_RL_SPATIAL=1 reply format). The
resume path is exercised on a SYNTHETIC rd1 tree produced by rd1's own engine against that stand-in (archive, close record, frozen
runtime, a verified D:-style increment), and the rd2 session runs against it through the real worker processes. The real rd1 archive
under runs/m8_rd/ is only READ (the reference reproduction); nothing is ever written under runs/.

Light top-level imports only (spawned workers re-import this script).
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import io
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))

import m8_rd_archive as march  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_explore as mx  # noqa: E402
import m8_rd_resume as rs  # noqa: E402
import m8_rd_select2 as s2  # noqa: E402
import m8_rd_stub as stub  # noqa: E402
import m8_rd_tests as t1  # noqa: E402  (rd1's helpers and fixtures)
import m8_rd_worker as mw  # noqa: E402
import m8_rd2_report as rpt2  # noqa: E402
import m8_rd2_rule as rule2  # noqa: E402
import m8_rd2_worker as w2  # noqa: E402
from m8_rd_tests import Failure, check, raises, tmpdir  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
RL_DIR = Path(__file__).resolve().parent
RD1_REAL = REPO_ROOT / "runs" / "m8_rd"
NEW_MODULES = ("m8_rd_select2", "m8_rd_resume", "m8_rd2_worker", "m8_rd2_run", "m8_rd2_session", "m8_rd2_rule", "m8_rd2_report",
               "m8_rd2_snapshot")
RD1_FILES = ("m8_rd_cells", "m8_rd_explore", "m8_rd_archive", "m8_rd_claims", "m8_rd_rule", "m8_rd_worker", "m8_rd_run", "m8_rd_finish",
             "m8_rd_session", "m8_rd_report", "m8_rd_snapshot", "m8_rd_stub", "m8_rd_fakegame", "m8_rd_tests")
FLOOR_MIN = -600.0                                  # the synthetic worlds' lowest floor (the stub's floor 3)


# -- synthetic builders ------------------------------------------------------------------------------------------------------------------


class Krng:
    """A keyed sha256 stream (the tests, like the modules, never use a stateful generator)."""

    def __init__(self, seed: Any):
        self.seed, self.n = str(seed), 0

    def u(self) -> float:
        d = hashlib.sha256(f"{self.seed}|{self.n}".encode()).digest()
        self.n += 1
        return int.from_bytes(d[:8], "big") / 2.0 ** 64

    def i(self, lo: int, hi: int) -> int:
        return lo + min(hi - lo, int(self.u() * (hi - lo + 1)))

    def pick(self, seq: Sequence[Any]) -> Any:
        return seq[self.i(0, len(seq) - 1)]


STATUS = {"G": 10, "A2": 22, "A1": 22, "A0": 225, "A0h": 58, "X": 37}


def end17(x: float, y: float, *, vy: float = 0.0, status: int = 22, ga: int = 1, jumps: int = 0, targets: int = 10, t: int = 0) -> Tuple[Any, ...]:
    return (1, 100, t, t, 1, 1, targets, 1, float(x), float(y), 0.0, float(vy), 0.0, 1, ga, status, jumps)


def mkey(bx: int, by: int, res: str = "A2", mask: int = 1023, floor: int = 4) -> Tuple[int, int, str, int, int]:
    return t1.key(bx, by, res, mask, floor)


def reach_at(j: int, key: Tuple[Any, ...], *, y: Optional[float] = None, vy: float = 0.0, status: Optional[int] = None,
             terminal: bool = False) -> Tuple[Any, ...]:
    res = key[2]
    yy = key[1] * 300 + 100.0 if y is None else y
    st = status if status is not None else STATUS.get(res, 22)
    return t1.reach(j, key, end17(key[0] * 300 + 100.0, yy, vy=vy, status=st, ga=0 if res == "G" else 1, jumps=2 if res in ("A1", "A0") else 0,
                                  targets=mcell.popcount(key[3]), t=j), terminal)


def fresh2(aid: str = "t2", floor_min: float = -2550.0) -> s2.Archive2:
    a = s2.Archive2(aid, floor_min=floor_min)
    a.init_cell0(t1.key(0, 0), t1.mk_end(), bytes(32), bytes([1]) * 32)
    return a


def add_cell2(a: s2.Archive2, k: Tuple[Any, ...], L: int, *, y: float = 0.0, vy: float = 0.0, status: Optional[int] = None, doomed: bool = False,
              terminal: bool = False, chosen: int = 0, seen: int = 0) -> march.Cell:
    res = k[2]
    st = status if status is not None else STATUS.get(res, 22)
    c = march.Cell(id=len(a.cells), key=k, level=mcell.level_of_mask(k[3]), L=L, burst=-1, offset=0, parent=0,
                   end=end17(k[0] * 300 + 100.0, y, vy=vy, status=st, ga=0 if res == "G" else 1, t=L), end_digest=bytes(32), chain=bytes(32),
                   doomed=doomed, terminal=terminal, chosen=chosen, seen=seen)
    a._add(c)
    return c


def dispatch_to(a: s2.Archive2, cell: march.Cell, worker: int = 0, it: Optional[int] = None) -> int:
    """Log a dispatch of exactly `cell` (selection bypassed: the cell may be ineligible), with the next unused iteration number."""
    used = [e["it"] for e in a.events if e["ev"] == "dispatch"] + list(a._pending)
    n = (max(used) + 1) if (used and it is None) else (it if it is not None else 1000)
    a.apply_dispatch(n, cell.id, worker)
    return n


def ingest_from(a: s2.Archive2, cell: march.Cell, words: bytes, reaches: Sequence[Any], *, end_reason: str = "length", cum: int = 0,
                runs: Optional[Sequence[Sequence[int]]] = None, trans: Optional[Sequence[Any]] = None) -> Dict[str, Any]:
    it = dispatch_to(a, cell)
    res = t1.result(it, cell, words, reaches, end_reason, cum)
    if runs is not None:
        res["ground_runs"] = [list(r) for r in runs]
        res["res_transitions"] = [list(r) for r in (trans or [])]
    return a.ingest(res)


def synth_result(a: s2.Archive2, cell: march.Cell, it: int, rng: Krng, *, v2: bool) -> Dict[str, Any]:
    """A random but valid job result from `cell` (distinct first-visit keys in increasing ticks)."""
    n = rng.i(20, 100)
    start_L = cell.L
    words = bytes(rng.i(0, 71) for _ in range(n))
    ticks = sorted({start_L + rng.i(1, n) for _ in range(rng.i(1, 9))})
    end_reason = rng.pick(["length", "length", "fall"])
    reaches: List[Any] = []
    seen = set()
    runs: List[List[int]] = []
    for j in ticks:
        res = rng.pick(["G", "A2", "A1", "A0", "A0", "A1", "A2"])
        k = (rng.i(-3, 6), rng.i(-6, 4), res, rng.pick([1023, 1023, 1022, 1020, 1016, 1, 4]), rng.i(0, 4) if res == "G" else -1)
        if k in seen:
            continue
        seen.add(k)
        y = k[1] * 300 + rng.i(0, 299)
        st = STATUS["A0"] if (res == "A0" and rng.u() < 0.6) else (STATUS["A0h"] if res == "A0" else STATUS[res])
        reaches.append(t1.reach(j, k, end17(k[0] * 300 + 100.0, y, vy=rng.i(-60, 60), status=st, ga=0 if res == "G" else 1, jumps=2 if res in ("A1", "A0") else 0,
                                            targets=mcell.popcount(k[3]), t=j)))
        if res == "G":
            runs.append([j, j])
    if end_reason == "fall" and reaches:
        # the burst's last tick is the fall: its reach (class X, terminal) closes the burst
        j = start_L + n
        if j > reaches[-1][0]:
            reaches.append(t1.reach(j, (7, -9, "X", 1023, -1), end17(2100.0, -2700.0, status=STATUS["X"], t=j), True))
    res = t1.result(it, cell, words, reaches, end_reason, rng.i(0, 5000))
    if v2:
        res["ground_runs"] = runs
        res["res_transitions"] = []
    return res


def drive2(a: s2.Archive2, rng: Krng, n: int, it0: int, *, v2: bool) -> None:
    for it in range(it0, it0 + n):
        cell = a.dispatch(it, 0)
        a.ingest(synth_result(a, cell, it, rng, v2=v2))


def synth_archive(seed: str = "s", n1: int = 50, n2: int = 70, floor_min: float = -2100.0) -> s2.Archive2:
    rng = Krng(seed)
    a = fresh2("syn", floor_min)
    drive2(a, rng, n1, 0, v2=False)
    a.begin_v2(n1, "lines")
    drive2(a, rng, n2, n1, v2=True)
    return a


# -- the contract, the bound, the tree -------------------------------------------------------------------------------------------------


def unit_select2_contract() -> Dict[str, Any]:
    j = sum(73.8 - 2.4 * k for k in range(31))
    check(abs(j - s2.RISE_AERIAL_JUMP) < 1e-9, f"the aerial-jump rise is the discrete sum {j}")
    check(abs(s2.RISE_TORNADO - 2073.3333333333335) < 1e-9 and s2.RISE_UPB == 1361.3 and s2.BOUND_MARGIN == 300.0 and s2.GRAVITY == 2.4,
          "the registered Mario constants")
    check(s2.y_floor_min() == -2550.0, f"Y_floor_min is the lowest floor line of the native table: {s2.y_floor_min()}")
    check(s2.W_RES[mcell.RES_GROUNDED] == 1.0 and s2.W_RES[mcell.RES_A2] == 1.0 and s2.W_RES[mcell.RES_A1] == 0.5 and s2.W_RES[mcell.RES_A0] == 0.25,
          "w_res = 1, 1, 1/2, 1/4")
    clf = mcell.Classifier()
    up = sorted(s for s, c in clf._by_id.items() if c == s2.UPB_STATUS_CLASS)
    check(up == [225, 226], f"Mario's up-B statuses: {up}")
    check(clf.name(58) == "helpless", "helpless is status 58")
    d1 = s2.select2_contract_digest("a" * 64, "b" * 64)
    check(d1 == s2.select2_contract_digest("a" * 64, "b" * 64) and len(d1) == 64, "the contract digest is stable")
    check(d1 != s2.select2_contract_digest("c" * 64, "b" * 64) and d1 != s2.select2_contract_digest("a" * 64, "c" * 64)
          and d1 != s2.select2_contract_digest("a" * 64, "b" * 64, -500.0), "the digest covers the status table, the line table and the floor")
    check(s2.DRAW_SUFFIX == "_v2" and fresh2("x").draw_id == "x_v2", "the v2-specific draw id")
    check(mx.select_key("m8_rd_a1_v2", 2175) == "m8_rd|m8_rd_a1_v2|select|2175", "the v2 select key string")
    check(mx.explore_key("m8_rd_a1_v2", 2175, 3) == "m8_rd|m8_rd_a1_v2|explore|2175|3", "the v2 explore key string")
    return {"tornado": s2.RISE_TORNADO, "digest": d1[:12]}


def unit_bound_rule() -> Dict[str, Any]:
    fm = -2550.0
    R_a2, R_a1, R_up = (s2.RISE_TORNADO + s2.RISE_AERIAL_JUMP + s2.RISE_UPB), (s2.RISE_TORNADO + s2.RISE_UPB), s2.RISE_UPB
    cases = [("A2", "airborne", R_a2), ("A1", "airborne", R_a1), ("A0", "special_hi", R_up), ("A0", "helpless", 0.0)]
    for res, sc, R in cases:
        thr = fm - s2.BOUND_MARGIN - R                          # unrecoverable iff y < thr (strict)
        check(s2.bound_unrecoverable(res, sc, thr - 0.01, 0.0, fm), f"{res}/{sc}: just below the threshold is unrecoverable")
        check(not s2.bound_unrecoverable(res, sc, thr, 0.0, fm), f"{res}/{sc}: exactly at the threshold is not (strict inequality)")
        check(not s2.bound_unrecoverable(res, sc, thr + 0.01, 0.0, fm), f"{res}/{sc}: above the threshold is recoverable")
    # an upward velocity adds the ballistic rise; a downward one adds nothing
    hb = 50.0 ** 2 / 4.8 + 50.0
    check(abs(s2.rise_bound("A0", "helpless", 50.0) - hb) < 1e-12 and s2.rise_bound("A0", "helpless", -80.0) == 0.0, "ballistic rise from v_y")
    check(s2.rise_bound(mcell.RES_GROUNDED, "idle_ground", 0.0) is None and s2.rise_bound(mcell.RES_X, "damage", 0.0) is None, "G and X have no bound")
    check(not s2.bound_unrecoverable("G", "idle_ground", -99999.0, 0.0, fm), "a grounded cell is never bound-unrecoverable")
    # the floor is an input (nothing reads x)
    check(s2.bound_unrecoverable("A1", "airborne", -6500.0, 0.0, fm) and not s2.bound_unrecoverable("A1", "airborne", -6500.0, 0.0, -9000.0), "the floor is an input")
    a = fresh2("b", fm)
    lo = add_cell2(a, mkey(1, -21, "A1"), 100, y=-6290.0)
    hi = add_cell2(a, mkey(2, -21, "A1"), 100, y=-6200.0)
    check(a.bound[lo.id] and not a.bound[hi.id], "the flag follows the stored end record")
    a.begin_v2(10, "L")
    check(not a.eligible(lo) and a.eligible(hi), "a bound-unrecoverable cell is ineligible in mode 2")
    # X1: exactly one live target is exempt from E4-E6
    one = add_cell2(a, mkey(3, -21, "A1", mask=1), 100, y=-6290.0)
    check(a.bound[one.id] and a.eligible(one) and not a.doom_v2(one), "X1: a one-target cell is exempt from the bound")
    return {"A1_threshold": fm - s2.BOUND_MARGIN - R_a1}


def unit_descent_tree_vs_reference() -> Dict[str, Any]:
    n_checked = 0
    for seed in ("t1", "t2", "t3"):
        rng = Krng(seed)
        tree = s2.DescentTree()
        length, fell, last_g, parent, par_off = [], [], [], [], []
        for b in range(120):
            ln = rng.i(5, 90)
            fl = rng.u() < 0.4
            lg = rng.i(-1, ln) if rng.u() < 0.5 else -1
            if b == 0 or rng.u() < 0.1:
                pb, po = -1, 0
            else:
                pb = rng.i(0, b - 1)
                po = rng.i(0, length[pb])
            tree.add(b, ln, fl, lg, pb, po)
            length.append(ln), fell.append(fl), last_g.append(lg), parent.append(pb), par_off.append(po)
            if b % 7 == 0 or b == 119:
                R, F = s2.DescentTree.reference(length, fell, last_g, parent, par_off)
                check(tree.R == R and tree.F == F, f"seed {seed}, after burst {b}: the incremental tree differs from the reference")
                n_checked += 1
    # the changed set names every burst whose (R, F) changed
    tree = s2.DescentTree()
    tree.add(0, 50, True, -1, -1, 0)
    check(tree.R[0] == 0 and tree.F[0] == 50, "a fallen burst without ground is doomed everywhere")
    ch = tree.add(1, 10, False, 4, 0, 20)                  # a child from offset 20 that lands at offset 4 of itself
    check(sorted(ch) == [0, 1] and tree.R[0] == 21 and tree.F[0] == 50, "a landing child recovers every offset up to its start")
    ch = tree.add(2, 10, False, -1, 0, 30)                 # a pending child (no fall, no ground): changes nothing
    check(ch == [2] and tree.R[0] == 21, "a pending child changes nothing")
    ch = tree.add(3, 10, True, -1, 2, 5)                   # a fatal grandchild: bursts 2 and 0 get fatal evidence
    check(3 in ch and tree.F[2] == 5, "a fatal grandchild gives its parent fatal evidence")
    raises(s2.Select2Error, lambda: tree.add(9, 1, False, -1, -1, 0), "an out-of-order burst is refused")
    raises(s2.Select2Error, lambda: tree.add(4, 1, False, -1, 4, 0), "a burst from a later burst is refused")
    return {"checks": n_checked}


def unit_descent_doom_semantics() -> Dict[str, Any]:
    a = fresh2("dd", -2550.0)
    c0 = a.cells[0]
    a.begin_v2(1000, "L")
    K1, K2, K3 = mkey(1, 5, "A2"), mkey(2, 5, "A1"), mkey(3, 5, "A0")
    FX = (9, -9, "X", 1023, -1)
    # burst 0: 100 words ending in a native fall, three airborne reaches, nothing grounded
    ingest_from(a, c0, bytes(100), [reach_at(5, K1), reach_at(10, K2), reach_at(50, K3), t1.reach(100, FX, end17(900.0, -2800.0, status=37), True)],
                end_reason="fall", runs=[])
    k1, k2, k3 = (a.cells[a.by_key[k]] for k in (K1, K2, K3))
    check(a.desc[k1.id] and a.desc[k2.id] and a.desc[k3.id], "every airborne reach of a fallen burst with no landing is descent-doomed")
    check(not k1.doomed and not k2.doomed and k3.doomed, "E4 (the 60-tick window) is separate: only the last reach is inside it")
    check(not a.eligible(k1) and not a.eligible(k2) and not a.eligible(k3), "descent-doomed cells are ineligible")
    # burst 1 starts from K1's representative and lands at its offset 7: K1 is revived; K2 (offset 10 >= 6) is still doomed
    base = a.diag2["revivals"]
    ingest_from(a, k1, bytes(40), [reach_at(k1.L + 7, mkey(4, 0, "G", floor=4))], end_reason="length", runs=[[k1.L + 7, k1.L + 9]])
    check(not a.desc[k1.id] and a.desc[k2.id] and a.desc[k3.id], "a later landing from the reach clears its doom and only its")
    check(a.diag2["revivals"] == base + 1 and a.eligible(k1), "the revival is counted and the cell is eligible again")
    # burst 2 from K2's representative: fatal, no landing -> K2 stays doomed; its own new airborne reach is doomed from its own burst
    ingest_from(a, k2, bytes(20), [reach_at(k2.L + 3, mkey(5, 5, "A2"))], end_reason="fall", runs=[])
    new = a.cells[a.by_key[mkey(5, 5, "A2")]]
    check(a.desc[k2.id] and a.desc[new.id], "a fatal child dooms its reach and keeps the parent's doom")
    # a pending burst: ended by length with no landing and no fall -> not doomed (pending)
    ingest_from(a, c0, bytes(30), [reach_at(8, mkey(6, 5, "A2")), reach_at(20, mkey(7, 5, "A1"))], end_reason="length", runs=[])
    p1c, p2c = (a.cells[a.by_key[mkey(6, 5, "A2")]], a.cells[a.by_key[mkey(7, 5, "A1")]])
    check(not a.desc[p1c.id] and not a.desc[p2c.id] and a.eligible(p1c) and a.eligible(p2c), "no completed continuation means pending, not doomed")
    # a landing LATER in the same burst clears the reaches before it and not the ones after it
    P1, P2, GK = mkey(10, 5, "A2"), mkey(11, 5, "A1"), mkey(12, 0, "G", floor=4)
    ingest_from(a, c0, bytes(60), [reach_at(4, P1), t1.reach(15, GK, end17(3700.0, 0.0, status=10, ga=0, targets=10), False), reach_at(25, P2),
                                   t1.reach(60, FX, end17(900.0, -2800.0, status=37), True)], end_reason="fall", runs=[[15, 17]])
    q1, q2 = a.cells[a.by_key[P1]], a.cells[a.by_key[P2]]
    check(not a.desc[q1.id] and a.desc[q2.id], "a reach before the landing recovers, a reach after it (and a fall) does not")
    # X1: a one-target cell is exempt even when descent-doomed
    ingest_from(a, c0, bytes(100), [reach_at(5, mkey(13, 5, "A2", mask=1)), t1.reach(100, FX, end17(900.0, -2800.0, status=37), True)], end_reason="fall", runs=[])
    x1 = a.cells[a.by_key[mkey(13, 5, "A2", mask=1)]]
    check(a.desc[x1.id] and a.eligible(x1) and not a.doom_v2(x1), "X1 exempts a one-target cell from E4-E6")
    # the incremental flags equal the first-principles recomputation
    rd, rb = a.reference_flags()
    check(rd == a.desc and rb == a.bound, "the incremental flags equal the recomputation")
    return {"cells": len(a.cells), "revivals": a.diag2["revivals"]}


# -- the archive: v1 equivalence, selection, replacement -------------------------------------------------------------------------------


def unit_archive2_mode1_equals_v1() -> Dict[str, Any]:
    rng = Krng("eq")
    a1 = march.Archive("eq")
    a1.init_cell0(t1.key(0, 0), t1.mk_end(), bytes(32), bytes([1]) * 32)
    a2 = s2.Archive2("eq", floor_min=-2550.0)
    a2.init_cell0(t1.key(0, 0), t1.mk_end(), bytes(32), bytes([1]) * 32)
    for it in range(80):
        c1, c2 = a1.dispatch(it, 0), a2.dispatch(it, 0)
        check(c1.id == c2.id, f"iteration {it}: the mode-1 selection differs from rd1's ({c1.id} vs {c2.id})")
        res = synth_result(a2, c2, it, rng, v2=False)
        i1, i2 = a1.ingest(dict(res)), a2.ingest(dict(res))
        check(i1 == i2, f"iteration {it}: the ingest summaries differ")
    check([c.to_json() for c in a1.cells] == [c.to_json() for c in a2.cells], "mode 1 builds exactly rd1's cells")
    check([b.to_json(0) for b in a1.bursts] == [b.to_json(0) for b in a2.bursts] and a1.events == a2.events and a1.diag == a2.diag,
          "and exactly rd1's bursts, ledger and diagnostics")
    check(all(a1.eligible(c) == a2.eligible(c) for c in a1.cells), "and rd1's eligibility")
    check(march.audit(a1)["ok"] and s2.audit2(a2, "lines")["ok"], "both audits pass")
    pr = a2.probabilities()
    check(abs(sum(pr.values()) - 1.0) < 1e-9, "mode-1 probabilities sum to 1")
    return {"cells": len(a2.cells)}


def unit_select2_probabilities() -> Dict[str, Any]:
    a = fresh2("sel2", -2550.0)
    M = {0: 1023, 1: 1022, 2: 1020, 3: 1016}
    c1 = add_cell2(a, mkey(1, 0, "G", M[0], 4), 100, chosen=3, seen=8)
    c2 = add_cell2(a, mkey(2, 0, "A2", M[0]), 1000)
    c3 = add_cell2(a, mkey(3, 0, "A1", M[1]), 200, chosen=1, seen=1)
    c4 = add_cell2(a, mkey(4, 0, "A0", M[1]), 300, status=225)
    c5 = add_cell2(a, mkey(5, 0, "G", M[1], 1), 1100, seen=2)
    c6 = add_cell2(a, mkey(6, 0, "A2", M[2]), 500, chosen=2, seen=3)
    c7 = add_cell2(a, mkey(7, 0, "A2", M[2]), 600, doomed=True)                    # E4
    c8 = add_cell2(a, mkey(8, 0, "X", M[3]), 700)                                  # E1
    c9 = add_cell2(a, mkey(9, 0, "G", M[3], 4), 800, terminal=True)                # E2
    c10 = add_cell2(a, mkey(10, 0, "A1", M[2]), 900, y=-9000.0)                    # E6
    c11 = add_cell2(a, mkey(11, 0, "A1", M[2]), 950)
    a.desc[c11.id] = True                                                          # E5 (set directly: a flag, not a history)
    c12 = add_cell2(a, mkey(12, 0, "A1", 1), 960, doomed=True)                     # one live target: X1 exempts it from E4
    c13 = add_cell2(a, mkey(13, 0, "G", M[2], 4), mcell.HORIZON - mx.BURST_WORDS + 1)   # E3
    a._version += 1
    a.begin_v2(100, "lines")
    elig = {0: [a.cells[0], c1, c2], 1: [c3, c4, c5], 2: [c6], 9: [c12]}          # c12 has ONE live target: level 9
    for lv in (3,):
        check(lv not in a.eligible_levels(), "a level with no eligible cell is absent")
    check({c.id for lvl in a.eligible_levels().values() for c in lvl} == {c.id for cs in elig.values() for c in cs},
          "eligibility: E1 X, E2 terminal, E3 length, E4 doomed, E5 descent, E6 bound; X1 exempt; cell 0 always")
    top = 9
    lw = {lv: 1.0 / (1.0 + top - lv) for lv in elig}
    p: Dict[int, float] = {}
    for lv, cs in elig.items():
        lmin = min(c.L for c in cs)
        w = [(1 / math.sqrt(1 + c.chosen) + 1 / math.sqrt(1 + c.seen)) * 900 / (900 + c.L - lmin) * s2.W_RES[c.key[2]] for c in cs]
        for c, wi in zip(cs, w):
            p[c.id] = lw[lv] / sum(lw.values()) * wi / sum(w)
    got = a.probabilities()
    check(set(got) == set(p) and all(abs(got[k] - p[k]) < 1e-12 for k in p), "the analytic probabilities equal the independent formula")
    check(abs(sum(p.values()) - 1.0) < 1e-12, "they sum to 1")
    N = 40000
    counts: Dict[int, int] = {}
    for i in range(N):
        cid = a.select(1000 + i).id
        counts[cid] = counts.get(cid, 0) + 1
    check(set(counts) <= set(p), f"an ineligible cell was selected: {set(counts) - set(p)}")
    for cid, pr in p.items():
        f = counts.get(cid, 0) / N
        check(abs(f - pr) <= 4.5 * math.sqrt(pr * (1 - pr) / N) + 1e-3, f"cell {cid}: frequency {f:.4f}, analytic {pr:.4f}")
    check(all(a.select(2000 + i).id == a.select(2000 + i).id for i in range(50)), "selection is a pure function of the state and the iteration")
    # the resource weight within one level: identical but for the class -> 1 : 1 : 1/2 : 1/4
    b = fresh2("w", -2550.0)
    g = add_cell2(b, mkey(1, 0, "G", 1022, 4), 100)
    x2 = add_cell2(b, mkey(2, 0, "A2", 1022), 100)
    x1 = add_cell2(b, mkey(3, 0, "A1", 1022), 100)
    x0 = add_cell2(b, mkey(4, 0, "A0", 1022), 100)
    b.begin_v2(10, "L")
    pb = b.probabilities()
    check(abs(pb[x2.id] / pb[g.id] - 1.0) < 1e-12 and abs(pb[x1.id] / pb[g.id] - 0.5) < 1e-12 and abs(pb[x0.id] / pb[g.id] - 0.25) < 1e-12,
          "w_res is 1, 1, 1/2, 1/4")
    # the harmonic level weight 1 / (1 + top - level): a top of 9 weighs 1, level 2 weighs 1/8, level 1 weighs 1/9, level 0 weighs 1/10
    check(abs(lw[0] - 1 / 10) < 1e-12 and abs(lw[1] - 1 / 9) < 1e-12 and abs(lw[2] - 1 / 8) < 1e-12 and lw[9] == 1.0, "the level weights are harmonic")
    # the draws use the v2 key, not rd1's
    d = a.select(5)
    u1, u2 = mx.uniforms("m8_rd|sel2_v2|select|5")
    check(u1 != mx.uniforms("m8_rd|sel2|select|5")[0], "the v2 key differs from rd1's")
    return {"cells": len(a.cells), "eligible": len(p)}


def unit_replacement_v2() -> Dict[str, Any]:
    out: Dict[str, int] = {}
    FX = (9, -9, "X", 1023, -1)
    # 1. a doomed incumbent (E5: its burst fell) loses to a pending reach even if the pending one is longer
    a = fresh2("r1", -2550.0)
    a.begin_v2(1000, "L")
    K = mkey(1, 5, "A2")
    ingest_from(a, a.cells[0], bytes(100), [reach_at(5, K), t1.reach(100, FX, end17(900.0, -2800.0, status=37), True)], end_reason="fall", runs=[])
    c = a.cells[a.by_key[K]]
    check(a.desc[c.id] and c.L == 5, "setup: a doomed incumbent")
    ingest_from(a, a.cells[0], bytes(100), [reach_at(40, K)], end_reason="length", runs=[])
    check(c.L == 40 and not a.desc[c.id] and a.diag2["doomed_incumbent_replacements"] == 1,
          f"a doomed incumbent loses to a longer pending reach (L {c.L}, replacements {a.diag2['doomed_incumbent_replacements']})")
    # 2. a doomed new reach never beats a non-doomed incumbent, even when shorter
    ingest_from(a, a.cells[0], bytes(100), [reach_at(10, K), t1.reach(100, FX, end17(900.0, -2800.0, status=37), True)], end_reason="fall", runs=[])
    check(c.L == 40, "a doomed (own-burst) reach never beats a non-doomed incumbent")
    # 3. both doomed: the strictly shorter wins, a tie keeps the incumbent
    b = fresh2("r3", -2550.0)
    b.begin_v2(1000, "L")
    ingest_from(b, b.cells[0], bytes(100), [reach_at(20, K), t1.reach(100, FX, end17(900.0, -2800.0, status=37), True)], end_reason="fall", runs=[])
    cb = b.cells[b.by_key[K]]
    ingest_from(b, b.cells[0], bytes(100), [reach_at(10, K), t1.reach(100, FX, end17(900.0, -2800.0, status=37), True)], end_reason="fall", runs=[])
    check(cb.L == 10, "both doomed: the shorter reach wins")
    ingest_from(b, b.cells[0], bytes(100), [reach_at(10, K), t1.reach(100, FX, end17(900.0, -2800.0, status=37), True)], end_reason="fall", runs=[])
    check(cb.L == 10 and cb.replacements == 1, "a tie keeps the incumbent")
    # 4. E6: a bound-unrecoverable incumbent loses to a longer recoverable reach of the same cell key
    d = fresh2("r4", -2550.0)
    d.begin_v2(1000, "L")
    KB = mkey(2, -21, "A1")
    ingest_from(d, d.cells[0], bytes(100), [reach_at(30, KB, y=-6290.0)], end_reason="length", runs=[])
    cd = d.cells[d.by_key[KB]]
    check(d.bound[cd.id], "setup: bound-unrecoverable incumbent")
    ingest_from(d, d.cells[0], bytes(100), [reach_at(70, KB, y=-6200.0)], end_reason="length", runs=[])
    check(cd.L == 70 and not d.bound[cd.id] and d.diag2["doomed_incumbent_replacements"] == 1, "a recoverable reach replaces a bound-unrecoverable incumbent")
    ingest_from(d, d.cells[0], bytes(100), [reach_at(20, KB, y=-6290.0)], end_reason="length", runs=[])
    check(cd.L == 70, "a bound-unrecoverable reach does not replace a recoverable incumbent, even when shorter")
    # 5. X1: a doomed one-target incumbent is not doomed for replacement: a longer reach keeps it
    e = fresh2("r5", -2550.0)
    e.begin_v2(1000, "L")
    K1 = mkey(3, 5, "A2", mask=1)
    ingest_from(e, e.cells[0], bytes(100), [reach_at(5, K1), t1.reach(100, FX, end17(900.0, -2800.0, status=37), True)], end_reason="fall", runs=[])
    ce = e.cells[e.by_key[K1]]
    ingest_from(e, e.cells[0], bytes(100), [reach_at(40, K1)], end_reason="length", runs=[])
    check(ce.L == 5, "X1: a one-target incumbent keeps its place by the ordinary shorter-wins rule")
    out["done"] = 1
    return out


# -- the ledger rebuild, persistence, overlay ----------------------------------------------------------------------------------------


def unit_ledger_rebuild_v2() -> Dict[str, Any]:
    a = synth_archive("lr", 50, 70)
    check(len(a.cells) > 150 and a.mode == 2 and len(a.bursts) == 120, f"the synthetic archive: {len(a.cells)} cells")
    check(any(len(b.reaches[0]) == 4 for b in a.bursts[50:] if b.reaches), "v2 bursts carry the bound bit in their reach rows")
    check(all(len(b.reaches[0]) == 3 for b in a.bursts[:50] if b.reaches), "v1 bursts keep rd1's three-element rows")
    aud = s2.audit2(a, "lines")
    check(aud["ok"], f"audit of a two-mode archive: {aud['problems']}")
    check(aud["prefixes_reconstructed"] == len(a.cells), "every prefix reconstructs")
    rb = s2.rebuild2(a, "lines")
    check([c.to_json() for c in rb.cells] == [c.to_json() for c in a.cells] and rb.events == a.events and rb.diag2 == a.diag2, "the rebuild equals the archive")
    rd, rbd = a.reference_flags()
    check(rd == a.desc and rbd == a.bound, "the incremental flags equal the recomputation")
    check(a.diag2["newly_descent_doomed"] > 0 and a.diag2["doomed_incumbent_replacements"] >= 0, "the v2 counters ran")
    t = tmpdir("m8r2t_")
    a.write_files(t / "a", {"checkpoint_seq": 1})

    def load() -> s2.Archive2:
        b, _m = s2.Archive2.read_dir(t / "a")
        return b

    b = load()
    check(s2.audit2(b, "lines")["ok"], "a saved and reloaded archive audits")
    b = load()
    b.cells[len(b.cells) // 2].chosen += 1
    check(not s2.audit2(b, "lines")["ok"], "a tampered counter is detected")
    b = load()
    v2b = next(x for x in b.bursts[60:] if x.reaches)
    v2b.reaches[0][3] = 1 - v2b.reaches[0][3]
    check(not s2.audit2(b, "lines")["ok"], "a tampered bound bit is detected")
    b = load()
    v2b = next(x for x in b.bursts[60:] if len(x.reaches) > 1)
    v2b.reaches[1][2] = (v2b.reaches[1][2] + 1) % 3
    check(not s2.audit2(b, "lines")["ok"], "a tampered action is detected")
    b = load()
    b.events = [e for e in b.events if e["ev"] != "session"]
    check(not s2.audit2(b, "lines")["ok"], "a ledger without its session event does not rebuild")
    b = load()
    sess = next(e for e in b.events if e["ev"] == "session")
    sess["digest"] = "0" * 64
    check(not s2.audit2(b, "lines")["ok"], "a tampered session digest is detected")
    check(not s2.audit2(load(), "other lines")["ok"], "a different pinned line table is detected through the session digest")
    b = load()
    b.desc[7] = not b.desc[7]
    check(not s2.audit2(b, "lines")["ok"], "a tampered derived flag is detected against the recomputation")
    b = load()
    b.diag2["revivals"] += 1
    check(not s2.audit2(b, "lines")["ok"], "a tampered v2 counter is detected")
    b = load()
    b.bursts[70].wins[0]["end"][mcell.I_Y] = 123456.0 if b.bursts[70].wins else 0.0
    if b.bursts[70].wins:
        check(not s2.audit2(b, "lines")["ok"], "a tampered win record is detected")
    b = load()
    b.bursts[60].start_rep = (500, 0)
    check(not s2.audit2(b, "lines")["ok"], "a lineage that points forward is detected")
    shutil.rmtree(t, ignore_errors=True)
    return {"cells": len(a.cells), "wins": sum(len(x.wins) for x in a.bursts), "newly_doomed": a.diag2["newly_descent_doomed"], "revivals": a.diag2["revivals"]}


def unit_begin_v2_and_persistence() -> Dict[str, Any]:
    a = fresh2("bp", -2550.0)
    drive2(a, Krng("bp"), 20, 0, v2=False)
    n_ev = len(a.events)
    raises(s2.Select2Error, lambda: a.begin_v2(5, "L"), "reusing a dispatched iteration is refused")
    a.apply_dispatch(500, 0, 0)
    raises(s2.Select2Error, lambda: a.begin_v2(600, "L"), "a pending dispatch blocks the switch")
    a.note_failure(500, "x")
    ev = a.begin_v2(600, "L")
    check(ev["first_iteration"] == 600 and a.mode == 2 and a.events[-1] == ev and len(a.events) == n_ev + 3, "one session event, then mode 2")
    raises(s2.Select2Error, lambda: a.begin_v2(700, "L"), "a second switch is refused")
    check(ev["digest"] == s2.select2_contract_digest(a.clf.table_sha256, "L", a.floor_min), "the event carries the contract digest")
    check(a.select(600).id == a.select(600).id, "mode-2 selection is deterministic")
    # persistence: v1-style files, then v2 files; the prefix property
    t = tmpdir("m8r2p_")
    base = march.Archive("bp")
    base.init_cell0(t1.key(0, 0), t1.mk_end(), bytes(32), bytes([1]) * 32)
    rng = Krng("pp")
    for it in range(30):
        c = base.dispatch(it, 0)
        base.ingest(synth_result(a, c, it, rng, v2=False))
    base.write_files(t / "rd1", {"checkpoint_seq": 7, "session": "rd1"})
    x, meta = s2.Archive2.read_dir(t / "rd1", floor_min=-2550.0)
    check(x.mode == 1 and meta["schema"] == march.ARCHIVE_SCHEMA and s2.audit2(x, "L")["ok"], "an rd1-schema directory loads as mode 1 and audits")
    x.begin_v2(30, "L")
    drive2(x, rng, 25, 30, v2=True)
    march.save_checkpoint(t / "rd2" / "archive", x, {"checkpoint_seq": 8, "why": "x"})
    pp = rs.prefix_property(t / "rd1", t / "rd2" / "archive")
    check(pp["ok"] and pp["events.jsonl"]["lines"] == 60 and pp["bursts.idx.jsonl"]["lines"] == 30, f"the prefix property: {pp}")
    y, meta2 = s2.Archive2.read_dir(t / "rd2" / "archive")
    check(meta2["schema"] == s2.ARCHIVE_SCHEMA_V2 and meta2["floor_min"] == -2550.0 and y.mode == 2 and y.first_iteration == 30 and y.draw_id == "bp_v2",
          "the v2 directory is self-describing (schema, floor, mode, first iteration, draw id)")
    check([c.to_json() for c in y.cells] == [c.to_json() for c in x.cells] and y.diag2 == x.diag2 and y.desc == x.desc and y.bound == x.bound,
          "a reload reproduces cells, counters and derived flags")
    check(s2.audit2(y, "L")["ok"], "the reloaded v2 archive audits")
    # the prefix property fails when rd1's bytes are not kept
    z = t / "bad"
    shutil.copytree(t / "rd2" / "archive", z)
    ev_p = z / "events.jsonl"
    raw = ev_p.read_bytes()
    ev_p.write_bytes(raw.replace(b'"worker":0', b'"worker":1', 1))
    check(not rs.prefix_property(t / "rd1", z)["ok"], "a changed rd1 ledger line fails the prefix property")
    # atomic checkpoints of a v2 archive: a crash at any step leaves a verifying, auditable checkpoint
    for crash in (None, "tmp_written", "tmp_verified", "current_moved", "new_installed"):
        root = t / f"ck_{crash}" / "archive"
        march.save_checkpoint(root, x, {"checkpoint_seq": 1})
        drive2(y, Krng("more"), 6, 100, v2=True)
        try:
            march.save_checkpoint(root, y, {"checkpoint_seq": 2}, crash_at=crash)
            check(crash is None, "unexpected success")
        except march.SimulatedCrash:
            check(crash is not None, "unexpected crash")
        d, m, rep = march.load_latest_verified(root)
        check(d is not None, f"no verified checkpoint after a crash at {crash}: {rep}")
        loaded, _mm = s2.Archive2.read_dir(d)
        check(s2.audit2(loaded, "L")["ok"] and m["checkpoint_seq"] == 2, f"crash {crash}: the newest complete checkpoint audits")
        y, _m3 = s2.Archive2.read_dir(t / "rd2" / "archive")
    shutil.rmtree(t, ignore_errors=True)
    return {"cells": len(x.cells)}


def unit_overlay() -> Dict[str, Any]:
    t = tmpdir("m8r2o_")
    base = march.Archive("ov")
    base.init_cell0(t1.key(0, 0), t1.mk_end(), bytes(32), bytes([1]) * 32)
    a = fresh2("ov")
    rng = Krng("ov")
    for it in range(60):
        c = base.dispatch(it, 0)
        res = synth_result(a, a.cells[c.id] if c.id < len(a.cells) else c, it, rng, v2=False)
        base.ingest(dict(res))
        a.apply_dispatch(it, c.id, 0)
        a.ingest(dict(res))
    base.write_files(t / "rd1", {"checkpoint_seq": 7})
    ov = rs.build_overlay(t / "rd1", floor_min=-2550.0)
    check(ov["ok"] and len(ov["rows"]) == len(base.cells) and ov["sha256"] == hashlib.sha256(ov["bytes"]).hexdigest(), "the overlay is computed twice and equal")
    ov2 = rs.build_overlay(t / "rd1", floor_min=-2550.0)
    check(ov["bytes"] == ov2["bytes"], "and reproducible")
    reasons = {r for row in ov["rows"] for r in row["reasons"]}
    check(reasons <= {"x", "terminal", "horizon", "doom60", "descent", "bound"}, f"reason codes: {reasons}")
    check(ov["rows"][0]["eligible"] and ov["rows"][0]["reasons"] == [], "cell 0 is always eligible")
    cnt = ov["counts"]
    check(cnt["eligible_v1"] == sum(1 for c in base.cells if march.Archive.eligible(c)), "the v1-eligible count")
    check(cnt["eligible_v2"] == cnt["eligible_v1"] - cnt["union"], "eligible v2 = eligible v1 minus the union of the two exclusions")
    check(cnt["union"] <= cnt["descent_among_v1_eligible"] + cnt["bound_among_v1_eligible"], "union <= sum")
    ov_low = rs.build_overlay(t / "rd1", floor_min=-3000.0)
    check(ov_low["sha256"] != ov["sha256"] or ov_low["counts"]["bound_among_v1_eligible"] == ov["counts"]["bound_among_v1_eligible"], "the floor is an input")
    # tampering a cell changes the digest
    shutil.copytree(t / "rd1", t / "rd1b")
    cells_p = t / "rd1b" / "cells.jsonl"
    # (manifest verification refuses a changed file; that refusal is the check)
    cells_p.write_bytes(cells_p.read_bytes().replace(b'"chosen":', b'"chosen":1', 1))
    raises(march.ArchiveError, lambda: rs.build_overlay(t / "rd1b", floor_min=-2550.0), "a changed archive file is refused by its manifest")
    shutil.rmtree(t, ignore_errors=True)
    return {"cells": len(base.cells), "union": cnt["union"]}


# -- the worker --------------------------------------------------------------------------------------------------------------------------


def brute_force_summaries(world: str, words: bytes, L: int, clf: mcell.Classifier) -> Tuple[List[List[int]], List[List[Any]]]:
    tr = stub.replay_trace(world, words)
    runs: List[List[int]] = []
    trans: List[List[Any]] = []
    prev: Optional[str] = None
    cur: Optional[List[int]] = None
    for r in tr["steps"]:
        o = r["observation"]
        j = o["input_tick"]
        live = mcell.is_live(o)
        cls = mcell.resource_class(o, clf.name(o["fighter_status_id"])) if live else None
        grounded = live and o["ground_air_state"] == 0
        if j > L:
            if grounded:
                if cur is None:
                    cur = [j, j]
                else:
                    cur[1] = j
            elif cur is not None:
                runs.append(cur)
                cur = None
            if cls is not None and prev is not None and cls != prev:
                trans.append([j, prev, cls, float(o["position_x"]), float(o["position_y"])])
        if cls is not None:
            prev = cls
    if cur is not None:
        runs.append(cur)
    return runs, trans


def unit_iterate2_equals_iterate() -> Dict[str, Any]:
    clf = t1.classifier()
    n_runs = n_trans = 0
    for world in ("easy", "hard"):
        ctx = t1.job_ctx(world)
        pin = t1.pin_from(ctx)
        a = march.Archive("w2")
        a.init_cell0(tuple(pin["key"]), pin["obs"], bytes.fromhex(pin["digest"]), bytes.fromhex(pin["chain"]))
        cum = 0
        for it in range(40):
            cell = a.dispatch(it, 0)
            job = t1.iterate_job(a, cell, pin, it=it)
            r1 = mw.run_iterate(t1.job_ctx(world), dict(job))
            r2 = w2.run_iterate2(t1.job_ctx(world), dict(job, kind="iterate2"))
            check(r1["ok"] and r2["ok"], f"{world} {it}: {r1.get('kind')} {r2.get('kind')}")
            skip = {"wall_s", "step_s", "ground_runs", "res_transitions", "worker_contract"}
            d1 = {k: v for k, v in r1.items() if k not in skip}
            d2 = {k: v for k, v in r2.items() if k not in skip}
            check(d1 == d2, f"{world} {it}: iterate2 differs from iterate in {[k for k in d1 if d1[k] != d2.get(k)]}")
            check(set(r2) - set(r1) == {"ground_runs", "res_transitions", "worker_contract"}, "exactly the two new fields (and the contract id) are added")
            if r2["words"]:
                runs, trans = brute_force_summaries(world, bytes(job["words"]) + bytes(r2["words"]), cell.L, clf)
                check(r2["ground_runs"] == runs and r2["res_transitions"] == trans,
                      f"{world} {it}: the recorded summaries differ from the brute force over the replay")
                n_runs += len(runs)
                n_trans += len(trans)
            else:
                check(r2["ground_runs"] == [] and r2["res_transitions"] == [], "no burst, no summaries")
            a.ingest(dict(r1, cum_before=cum, session="t"))
            cum += r1["ticks"]
    check(n_runs > 20 and n_trans > 40, f"the comparison saw ground runs ({n_runs}) and class transitions ({n_trans})")
    # the allowance cut inside the prefix and inside the burst
    ctx = t1.job_ctx("easy")
    pin = t1.pin_from(ctx)
    a = march.Archive("w2c")
    a.init_cell0(tuple(pin["key"]), pin["obs"], bytes.fromhex(pin["digest"]), bytes.fromhex(pin["chain"]))
    a.ingest(dict(mw.run_iterate(ctx, t1.iterate_job(a, a.cells[0], pin, it=0)), cum_before=0, session="t"))
    c = [x for x in a.cells if x.id and x.L >= 12][-1]
    job = dict(t1.iterate_job(a, c, pin, it=1), kind="iterate2")
    r = w2.run_iterate2(ctx, dict(job, allowance=c.L - 3))
    check(r["end_reason"] == "cut" and r["ground_runs"] == [] and r["res_transitions"] == [], "a cut inside the prefix records nothing")
    r = w2.run_iterate2(ctx, dict(job, allowance=c.L + 17))
    if r["end_reason"] == "cut":
        runs, trans = brute_force_summaries("easy", bytes(job["words"]) + bytes(r["words"]), c.L, t1.classifier())
        check(r["ground_runs"] == runs and r["res_transitions"] == trans, "a cut burst records the executed ticks")
    # registration: the job table of a worker gains iterate2, the rd1 file is untouched
    w2.register_jobs()
    check("iterate2" in mw.JOBS and mw.JOBS["iterate2"] is w2.run_iterate2, "iterate2 is registered by the rd2 worker entry point")
    r = mw.run_job(t1.job_ctx("easy"), dict(job))
    check(r["ok"] and "ground_runs" in r, "run_job dispatches the iterate2 kind")
    # a malformed reply never raises from the recorder (rd1's own check turns it into its bad_reply mismatch)
    rec_ = w2.TickRecorder(5, t1.classifier())
    for bad in ({}, {"observation": {}}, {"observation": {"input_tick": "x"}}, {"observation": None}):
        rec_.note(bad)
    check(rec_.ground_runs == [] and rec_.res_transitions == [], "malformed replies are ignored by the recorder")
    r = mw.run_job(t1.job_ctx("easy", inject={"bad_consumed_job": 1}), dict(job, words=b"", allowance=60))
    check(not r["ok"] and r["kind"] == "mismatch", "a bad reply is still rd1's integrity mismatch through iterate2")
    # failures keep rd1's structured shapes
    r = mw.run_job(t1.job_ctx("easy", inject={"lifecycle_jobs": [1]}), dict(job))
    check(not r["ok"] and r["kind"] == "lifecycle", "a lifecycle failure through iterate2")
    r = mw.run_job(t1.job_ctx("easy"), dict(job, chain=bytes(32)))
    check(not r["ok"] and r["kind"] == "mismatch" and r["mismatch"] == "prefix_end", "a tampered chain is refused through iterate2 as through iterate")
    return {"runs": n_runs, "transitions": n_trans}


def unit_write_guard() -> Dict[str, Any]:
    t = tmpdir("m8wg_")
    prot, other = t / "rd1", t / "other"
    prot.mkdir()
    other.mkdir()
    (prot / "f.txt").write_text("x", encoding="utf-8")
    (prot / "sub").mkdir()
    (prot / "sub" / "g.txt").write_text("y", encoding="utf-8")
    mw.ProvenanceGuard.install()
    w2.WriteGuard.install([prot])
    base = len(mw.ProvenanceGuard.violations)

    def n() -> int:
        return len(mw.ProvenanceGuard.violations) - base

    try:
        # reads and writes elsewhere are silent
        (prot / "f.txt").read_text(encoding="utf-8")
        open(prot / "f.txt", "rb").close()
        (other / "o.txt").write_text("z", encoding="utf-8")
        shutil.copyfile(prot / "f.txt", other / "copy.txt")
        os.replace(other / "copy.txt", other / "copy2.txt")
        os.mkdir(other / "d")
        shutil.rmtree(other / "d")
        check(n() == 0, f"reads and writes outside the protected root are not violations: {mw.ProvenanceGuard.violations[base:]}")
        trials = [("write_text", lambda: (prot / "w.txt").write_text("a", encoding="utf-8")),
                  ("open w", lambda: open(prot / "w2.txt", "w").close()),
                  ("open a", lambda: open(prot / "f.txt", "a").close()),
                  ("open r+", lambda: open(prot / "f.txt", "r+").close()),
                  ("write_bytes", lambda: (prot / "w3.bin").write_bytes(b"1")),
                  ("mkdir", lambda: os.mkdir(prot / "nd")),
                  ("copyfile into", lambda: shutil.copyfile(other / "o.txt", prot / "c.txt")),
                  ("replace into", lambda: os.replace(other / "o.txt", prot / "r.txt")),
                  ("rename out of", lambda: os.rename(prot / "f.txt", other / "moved.txt")),
                  ("remove", lambda: os.remove(prot / "sub" / "g.txt")),
                  ("rmdir", lambda: os.rmdir(prot / "sub")),
                  ("rmtree", lambda: shutil.rmtree(prot / "nd"))]
        for name, fn in trials:
            before = n()
            try:
                fn()
            except OSError:
                pass
            check(n() > before, f"the write guard missed: {name}")
        check(all("protected root" in v for v in mw.ProvenanceGuard.violations[base:]), "violations are named")
        # a violation stops a session through the existing per-result check: it lives in the provenance list
        check(w2.WriteGuard._under(prot / "sub" / "x") and not w2.WriteGuard._under(other / "x") and not w2.WriteGuard._under(str(prot) + "2"),
              "the root test is exact (a sibling with the same prefix is not under it)")
        check(w2.WriteGuard._under("\\\\?\\" + str(prot / "f.txt")) and w2.WriteGuard._under(str(prot).replace("\\", "/") + "/a/../f.txt"),
              "extended-length and forward-slash paths are matched")
        before = n()
        w2.WriteGuard._hook("open", (object(), object(), object()))          # junk arguments never raise into the audited call
        w2.WriteGuard._hook("shutil.copyfile", (None,))
        check(n() == before, "a malformed audit event is ignored")
    finally:
        w2.WriteGuard.clear()
        del mw.ProvenanceGuard.violations[base:]
        shutil.rmtree(t, ignore_errors=True)
    return {"trials": len(trials)}


# -- the rule, the report, the budget -------------------------------------------------------------------------------------------------


def unit_rule2_module() -> Dict[str, Any]:
    check(rule2.self_test() == [], "the rule's self-test")
    d = rule2.rule_digest()
    check(d == rule2.rule_digest() and len(d) == 64, "the rule digest")
    check(rule2.MIN_EXPLORATION_TICKS == 2_000_000 and rule2.BELOW_FLOOR_MAX_PER_MILLE == 105 and rule2.FATAL_MAX_PER_MILLE == 110, "the registered thresholds")
    check(rule2.RD1["launch_capable_cells"] == 14 and rule2.RD1["returns"] == 2175 and rule2.RD1["max_targets"] == 7, "rd1's reference values")
    check(rule2.LADDER == ("none", "L0", "crossing", "left_target", "clear"), "the ladder")
    desc = rule2.rule_description()
    check(desc["control_arm"] is False and set(desc["stops"]) == set(rule2.STOPS), "no control arm, seven stop conditions")
    r = rule2.apply(invalid=[], incomplete=[], m=0, below_floor=100, dispatches=4000, fatal_returns=100, returns=4000, launch_capable_created=40)
    check(r["outcome"] == "NO_MILESTONE/DILUTION_REDUCED" and r["rd3_requirement_met"] and not r["any_stop"], f"a reduced-dilution record: {r['outcome']} {r['any_stop']}")
    return {"rule_digest": d[:12]}


def unit_report_on_rd1_reference() -> Dict[str, Any]:
    if not (RD1_REAL / "archive" / "manifest.sha256").is_file():
        return {"skipped": "no rd1 archive on this machine"}
    a, _meta = s2.Archive2.read_dir(RD1_REAL / "archive")
    d = rpt2.diagnostics(a, 0, 2174, first_new_cell=0)
    reg = d["D1_regions"]
    check([reg[k]["n"] for k in ("below", "beside", "onlow", "onhigh")] == [456, 180, 1274, 265] and reg["left_of_wall"]["n"] == 0,
          f"D1 reproduces rd1's regions: {reg}")
    check(abs(reg["below"]["share"] - 0.2097) < 5e-5 and abs(reg["onhigh"]["share"] - 0.1218) < 5e-5, "D1 percentages 20.97 and 12.18")
    check(d["D2_step_contact"]["dispatches"]["n"] == 12 and d["D2_step_contact"]["cells"] == 32, "D2")
    c = d["D3_classes"]
    check([c[k]["n"] for k in ("G", "A2", "A1", "A0")] == [96, 408, 764, 907] and c["a2a1_on_stage_y_ge_0"]["n"] == 96 and c["a2_y_ge_0"]["n"] == 30, "D3")
    s = d["D4_supply"]
    check(s["a2a1_cells"] == 4406 and s["a2a1_on_stage_y_ge_0_cells_v1_eligible"] == 403 and s["launch_capable_cells"] == 14 and s["launch_capable_dispatches"] == 2
          and s["launch_capable_cells_x_le_600"] == 0 and abs(s["highest_a2_y"] - 909.6) < 0.05 and abs(s["launch_capable_created_per_1000_returns"] - 6.4368) < 1e-4, f"D4: {s}")
    p = d["D5_closest_approach"]
    check(abs(p["min_distance_to_ledge_corner"] - 1017.0) < 0.5 and p["nearest_class"] == "A0" and abs(p["min_distance_a2a1"] - 2125.0) < 0.5
          and abs(p["best_y_at_x_le_-1200"] - 1252.3) < 0.05 and abs(p["best_y_at_x_le_-1500"] - 1207.6) < 0.05 and abs(p["highest_cell_y"] - 3247.0) < 0.5, f"D5: {p}")
    f = d["D6_fatal_returns"]
    check(f["fatal_by_reaches"] == 480 and f["returns"] == 2175 and abs(f["share_by_reaches"] - 0.2207) < 5e-5, "D6")
    check(d["level_of_dispatches"] == {"0": 52, "1": 84, "2": 132, "3": 195, "4": 370, "5": 370, "6": 664, "7": 308}, "dispatches by level")
    return {"checked": 7}


def unit_open_overlay_on_rd1_reference() -> Dict[str, Any]:
    if not (RD1_REAL / "archive" / "manifest.sha256").is_file():
        return {"skipped": "no rd1 archive on this machine"}
    ov = rs.build_overlay(RD1_REAL / "archive")
    check(ov["ok"], f"the overlay computed twice: {ov['problems']}")
    diffs = rs.expected_open_problems(ov["counts"])
    check(not diffs, f"the overlay equals the proposal's figures: {diffs}")
    check(ov["counts"]["eligible_v1"] == 6960 and ov["counts"]["eligible_v2"] == 4506 and ov["counts"]["union"] == 2454, "6,960 -> 4,506 eligible, 2,454 excluded")
    return {"sha256": ov["sha256"][:12]}


def unit_budget_projection() -> Dict[str, Any]:
    import m8_rd2_session as ses2

    caps = ses2.caps()
    check(caps["wall_caps_s"] == {"p1": 240.0, "T": 3000.0, "verify": 360.0} and caps["global_cap_s"] == 3600.0, f"the registered wall caps: {caps['wall_caps_s']}")
    check(caps["exploration_tick_cap"] == 6_000_000 and caps["min_exploration_ticks"] == 2_000_000 and caps["open_tick_cap"] == 70_000
          and caps["replay_tick_cap"] == 400_000 and caps["identity_k"] == 16 and caps["max_battleship_processes"] == 10, "the registered tick caps")
    check(caps["memory_caps_mb"] == {"main_private": 3072, "tree_private": 9216, "tree_working_set": 4096, "system_available_min": 1024,
                                     "system_commit_free_min": 2048}, "memory caps as rd1's")
    proj = rpt2.budget_projection(caps)
    check(proj["caps_s"]["sum"] == proj["caps_s"]["session_hard_cap"] == 3600.0, "the phase caps sum to the session cap")
    check(proj["pessimistic"]["valid"] and proj["pessimistic"]["fits_hard_cap"] and proj["every_cap_binding"]["equals_hard_cap"]
          and proj["fits_hard_cap_without_trimming"], f"the pessimistic projection fits without trimming: {proj['pessimistic']}")
    check(proj["pessimistic"]["wall_s"]["total"] <= 3600.0 and proj["expected"]["wall_s"]["total"] <= proj["pessimistic"]["wall_s"]["total"], "expected <= pessimistic <= cap")
    check(proj["expected"]["exploration_ticks"] > 2_000_000 and not proj["expected"]["tick_cap_binds"], "the expected exploration is valid and the wall cap binds first")
    cfg = ses2.run_config()
    check(cfg.arm_cap("T") == 6_000_000 and cfg.min_arm_ticks == 2_000_000 and cfg.n_workers == 5 and cfg.burst_words == 120 and cfg.horizon == 3600,
          "run_config carries the registered values")
    return {"pessimistic_s": proj["pessimistic"]["wall_s"]["total"], "expected_ticks": round(proj["expected"]["exploration_ticks"])}


def unit_identity_samples() -> Dict[str, Any]:
    import m8_rd2_run as run2

    a = synth_archive("is", 60, 60, floor_min=-2100.0)
    s = run2.identity_sample_open(a, 16)
    ids = [c.id for c in s["cells"]]
    check(len(ids) == 16 and len(set(ids)) == 16 and 0 not in ids, f"sixteen distinct non-root cells: {len(ids)}")
    check(s["names"][:3] == [f"top_level_{lv}" for lv in sorted({c.level for c in a.cells if c.id}, reverse=True)[:3]] or len(s["names"]) == 16, "the top levels come first")
    names = s["names"]
    check(names.count("highest_weight") <= 4 and names.count("keyed_launch_or_a2_high") <= 4 and names.count("keyed_eligible") <= 5, f"pool sizes: {names}")
    pr = a.probabilities()
    best = [cid for cid in sorted(pr, key=lambda i: (-pr[i], i))[:4]]
    check(all(b in ids for b in best), "the four highest-weight v2-eligible cells are in the sample")
    check(s["cells"] == run2.identity_sample_open(a, 16)["cells"], "the open sample is a pure function of the archive")
    for lv in sorted({c.level for c in a.cells if c.id}, reverse=True)[:3]:
        short = min((c for c in a.cells if c.id and c.level == lv), key=lambda c: (c.L, c.id))
        check(short.id in ids, f"the shortest cell of level {lv} is in the sample")
    sc = run2.identity_sample_close(a, 16)
    check(len(sc["cells"]) == 16 and len({c.id for c in sc["cells"]}) == 16, "the close sample")
    check(run2.identity_sample_close(a, 16)["cells"] == sc["cells"], "the close sample is deterministic")
    check(sc["cells"] != s["cells"], "and a different keyed sample from the open one")
    small = fresh2("small")
    small.begin_v2(5, "L")
    check(run2.identity_sample_open(small, 16)["cells"] == [] and run2.identity_sample_close(small, 16)["cells"] == [], "an archive with only cell 0 has no sample")
    return {"open_names": names}


# -- the resume protocol on a synthetic rd1 tree ---------------------------------------------------------------------------------------


_SYN: Dict[str, Any] = {}


def tree_expect(root: Path) -> Dict[str, Any]:
    a, meta = march.Archive.read_files(root / "archive")
    prev = json.loads((root / "archive.prev" / "archive_meta.json").read_text(encoding="utf-8"))
    its = sorted(e["it"] for e in a.events if e["ev"] == "dispatch")
    return {"cells": len(a.cells), "bursts": len(a.bursts), "events": len(a.events), "checkpoint_seq": meta["checkpoint_seq"],
            "previous_checkpoint_seq": prev["checkpoint_seq"], "dispatch_iterations": (its[0], its[-1])}


def synthetic_rd1(world: str = "hard", *, t_cap: int = 30000, c_cap: int = 24000, flags: Optional[Mapping[str, Any]] = None,
                  exe_sha: str = "e" * 64, runtime_files: Optional[Mapping[str, str]] = None, cache: bool = True) -> Dict[str, Any]:
    """A complete synthetic rd1 tree: rd1's own engine against the stub (archive with its checkpoints, close record, sessions), a frozen
    runtime directory, the pins rd1 would have recorded, and a verified increment of it (runs_backup, as D: holds for the real one)."""
    key = f"{world}|{t_cap}|{c_cap}|{bool(flags)}"
    if cache and key in _SYN:
        return _SYN[key]
    import m8_rd_finish as fin
    import m8_rd_run as mrun
    import m8_rd_session as ses1
    import runs_backup as rb

    t = tmpdir("m8r2syn_")
    root = t / "rd1"
    rt = root / "archive" / "runtime"
    rt.mkdir(parents=True)
    (rt / "BattleShip.cfg.json").write_text(json.dumps({"CVars": {"frozen": "FROZEN-CONFIG"}}), encoding="utf-8")
    (rt / "imgui.ini").write_text("[frozen]\n", encoding="utf-8")
    frozen = {n: mw.sha256_file(rt / n) for n in mw.FROZEN_FILES}
    fl = dict(flags) if flags is not None else {"explore": ses1.FLAGS_EXPLORE, "verify": ses1.FLAGS_VERIFY}
    pins = {"executable_sha256": exe_sha, "runtime_files": dict(runtime_files or {"BattleShip.o2r": "a" * 64, "f3d.o2r": "b" * 64,
                                                                                  "gamecontrollerdb.txt": "c" * 64}),
            "frozen_sha256": frozen, "contracts": ses1.contract_digests(), "flags": fl, "archive_id": "m8_rd_a1", "git_head": "0" * 40,
            "rule_sha256": "0" * 64, "p1": {}, "approval_sha256": "0" * 64}
    cfg = t1.small_cfg(root, arm_tick_cap=t_cap, min_arm_ticks=min(t_cap, c_cap) // 3, arm_caps={"T": t_cap, "C": c_cap}, n_workers=3,
                       wall_caps_s={"p1": 90.0, "T": 300.0, "C": 300.0, "verify": 300.0}, global_cap_s=1200.0)

    def worker_spec(rank: int, c: Any) -> Dict[str, Any]:
        return {"rank": rank, "backend": "m8_rd_stub:StubBackend", "world": world, "inject": {}, "failure_dir": str(c.session_dir / "failures")}

    env = mrun.RunEnv(worker_spec=worker_spec, replay=lambda cand, counted, label, slot: stub.replay_trace(world, bytes(cand["words"][:counted]), label),
                      analyse=stub.analyse, p1_inputs=lambda: stub.p1_inputs(world), pins=pins, log=lambda s: None)
    mw.ProvenanceGuard.violations.clear()
    sess = mrun.Session(cfg, env)
    out = fin.run_all(sess)
    check(out["rule"]["outcome"] in ("PASS", "NULL", "INCONCLUSIVE") and not out["rule"]["invalid"] and not out["rule"]["incomplete"],
          f"the synthetic rd1 session: {out['rule']['outcome']} {out['rule']['invalid']} {out['rule']['incomplete']}")
    incr = t / "incr"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = rb.cmd_backup(root, incr, 2)
    check(rc == 0 and (incr / "verification.json").is_file(), f"the synthetic increment: {buf.getvalue()[-300:]}")
    rec = {"t": t, "root": root, "incr": incr, "expect": tree_expect(root), "pins": pins, "frozen": frozen, "lines": sess.pin["lines"], "world": world}
    if cache:
        _SYN[key] = rec
    return rec


def copy_tree(syn: Mapping[str, Any]) -> Dict[str, Any]:
    """A private copy of a synthetic rd1 tree and its increment (mtimes kept, so the copy still equals its increment)."""
    t = tmpdir("m8r2cp_")
    shutil.copytree(syn["root"], t / "rd1")
    shutil.copytree(syn["incr"], t / "incr")
    # the copy of the source must keep the mtimes the manifest records
    import runs_backup as rb

    man = rb.read_manifest(syn["incr"])
    for rel, (_sha, _size, mt) in man.items():
        os.utime(t / "rd1" / rel.replace("/", os.sep), ns=(mt, mt))
    return dict(syn, t=t, root=t / "rd1", incr=t / "incr")


def live_pins_of(syn: Mapping[str, Any]) -> Dict[str, Any]:
    p = syn["pins"]
    return {k: p[k] for k in ("executable_sha256", "runtime_files", "contracts", "flags")}


def unit_resume_protocol_synthetic() -> Dict[str, Any]:
    import m8_rd2_session as ses2

    syn = synthetic_rd1()
    op = ses2.open_protocol(syn["root"], syn["incr"], expect=syn["expect"], check_overlay=False, live_pins=lambda: live_pins_of(syn), floor_min=FLOOR_MIN)
    check(op["ok"], f"the open protocol on a synthetic tree: {op['problems']}")
    check(op["R1_rd1_immutability"]["ok"] and op["R2_R4_archive"]["ok"] and not op["R3_pins"]["problems"] and op["R5_overlay"]["ok"], "R1-R5")
    # R1: any change of rd1's tree is caught
    for what in ("byte", "mtime", "extra", "missing", "increment"):
        cp = copy_tree(syn)
        target = cp["root"] / "archive" / "cells.jsonl"
        if what == "byte":
            st = target.stat()
            raw = target.read_bytes()
            target.write_bytes(raw[:-2] + b"9\n")
            os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns))
        elif what == "mtime":
            os.utime(target, ns=(1, 2))
        elif what == "extra":
            (cp["root"] / "stray.txt").write_text("x", encoding="utf-8")
        elif what == "missing":
            (cp["root"] / "sessions" / "rd1" / "state.json").unlink()
        else:
            rec_p = cp["incr"] / "verification.json"
            rec = json.loads(rec_p.read_text(encoding="utf-8"))
            rec["result"] = "FAIL"
            rec_p.write_text(json.dumps(rec), encoding="utf-8")
        imm = rs.rd1_immutability(cp["root"], cp["incr"])
        check(not imm["ok"], f"R1 missed a change of rd1's tree: {what}")
        shutil.rmtree(cp["t"], ignore_errors=True)
    # R2: wrong expectations, a tampered archive file, a changed close record
    bad = dict(syn["expect"], cells=syn["expect"]["cells"] + 1)
    check(not rs.rd1_archive_facts(syn["root"], bad)["ok"], "R2: a wrong cell count is refused")
    check(not rs.rd1_archive_facts(syn["root"], dict(syn["expect"], checkpoint_seq=99))["ok"], "R2: a wrong checkpoint sequence is refused")
    cp = copy_tree(syn)
    close_p = cp["root"] / "sessions" / "rd1" / "close.json"
    d = json.loads(close_p.read_text(encoding="utf-8"))
    d["archive"]["manifest"]["cells.jsonl"] = "0" * 64
    close_p.write_text(json.dumps(d), encoding="utf-8")
    check(not rs.rd1_archive_facts(cp["root"], syn["expect"])["ok"], "R2: the archive must equal rd1's close record")
    shutil.rmtree(cp["t"], ignore_errors=True)
    # R3: pins
    p = syn["pins"]
    live = live_pins_of(syn)
    check(rs.pin_problems(p, live, syn["root"] / "archive" / "runtime", p["frozen_sha256"]) == [], "R3: equal pins")
    check(rs.pin_problems(p, dict(live, executable_sha256="0" * 64), syn["root"] / "archive" / "runtime", p["frozen_sha256"]) == ["pin executable_sha256 differs"],
          "R3: only the executable differs -> reported alone")
    check(rs.pin_problems(p, dict(live, runtime_files={"BattleShip.o2r": "0" * 64}), syn["root"] / "archive" / "runtime", p["frozen_sha256"]), "R3: a runtime file")
    check(rs.pin_problems(p, dict(live, flags={"explore": {}, "verify": {}}), syn["root"] / "archive" / "runtime", p["frozen_sha256"]), "R3: the flags")
    check(rs.pin_problems(p, dict(live, contracts=dict(live["contracts"], m8_rd_cell_v1="0" * 64)), syn["root"] / "archive" / "runtime", p["frozen_sha256"]), "R3: a contract digest")
    cp = copy_tree(syn)
    (cp["root"] / "archive" / "runtime" / "imgui.ini").write_text("changed", encoding="utf-8")
    check(rs.pin_problems(p, live, cp["root"] / "archive" / "runtime", p["frozen_sha256"]), "R3: the frozen configuration changed")
    shutil.rmtree(cp["t"], ignore_errors=True)
    # R6: materialise
    ov = op["overlay"]
    t = tmpdir("m8mat_")
    rd2 = t / "rd2"
    a2 = rs.materialise(syn["root"], rd2, facts=op["facts"], overlay=ov, lines_sha256=syn["lines"],
                        meta_extra={"pins": p, "pin_tick0": op["facts"]["pin_tick0"], "ticks": {}, "ledger_T": {}}, increment_manifest_sha256="x" * 64,
                        utc="2026-10-02T00:00:00Z", floor_min=FLOOR_MIN)
    check(a2.mode == 2 and a2.first_iteration == syn["expect"]["dispatch_iterations"][1] + 1, "materialised: mode 2, iterations continue")
    for n in (*march.DATA_FILES, march.MANIFEST):
        check(mw.sha256_file(rd2 / "base" / n) == mw.sha256_file(syn["root"] / "archive" / n), f"the base copy of {n} is byte-identical to rd1's file")
    check(mw.sha256_file(rd2 / "derived" / "open_overlay.jsonl") == ov["sha256"], "the stored overlay hashes to its digest")
    ob = json.loads((rd2 / "derived" / "open_overlay.json").read_text(encoding="utf-8"))
    check(ob["sha256"] == ov["sha256"] and ob["computed_twice_equal"], "the overlay record")
    base = json.loads((rd2 / "derived" / "base.json").read_text(encoding="utf-8"))
    check(base["session_event"]["name"] == "rd2" and base["rd1_increment_manifest_sha256"] == "x" * 64 and base["overlay_sha256"] == ov["sha256"], "the base record")
    d, meta, rep = march.load_latest_verified(rd2 / "archive")
    check(d is not None and meta["checkpoint_seq"] == syn["expect"]["checkpoint_seq"] + 1 and meta["schema"] == s2.ARCHIVE_SCHEMA_V2, "the first v2 checkpoint")
    check(rs.prefix_property(syn["root"] / "archive", rd2 / "archive")["ok"], "the prefix property holds at the open")
    loaded, _m = s2.Archive2.read_dir(rd2 / "archive")
    check(s2.audit2(loaded, syn["lines"])["ok"], "the materialised archive audits")
    raises(rs.ResumeError, lambda: rs.materialise(syn["root"], rd2, facts=op["facts"], overlay=ov, lines_sha256=syn["lines"], meta_extra={},
                                                   increment_manifest_sha256="x", utc="u"), "an existing rd2 root is never overwritten")
    # nothing was written under rd1's tree by any of this
    check(rs.rd1_immutability(syn["root"], syn["incr"])["ok"], "rd1's tree is still equal to its increment after the open")
    shutil.rmtree(t, ignore_errors=True)
    return {"cells": len(a2.cells)}


# -- the session on a synthetic rd1 tree -----------------------------------------------------------------------------------------------


def stub_env2(world: str, rd1_root: Path, inject: Optional[Mapping[str, Any]] = None, **kw: Any) -> Any:
    import m8_rd_run as mrun

    def worker_spec(rank: int, cfg: Any) -> Dict[str, Any]:
        return {"rank": rank, "backend": "m8_rd_stub:StubBackend", "world": world, "inject": dict(inject or {}),
                "failure_dir": str(cfg.session_dir / "failures"), "protected_roots": [str(rd1_root)]}

    def replay(cand: Mapping[str, Any], counted: int, label: str, slot: int) -> Dict[str, Any]:
        return stub.replay_trace(world, bytes(cand["words"][:counted]), label)

    return mrun.RunEnv(worker_spec=worker_spec, replay=replay, analyse=stub.analyse, p1_inputs=lambda: stub.p1_inputs(world), pins={"stub": True},
                       log=kw.pop("log", lambda s: None), **kw)


def small_cfg2(root: Path, **kw: Any) -> Any:
    import m8_rd2_session as ses2

    base = dict(n_workers=3, arm_tick_cap=12000, arm_caps={"T": 12000}, min_arm_ticks=4000, p1_tick_cap=20000, replay_tick_cap=300000,
                wall_caps_s={"p1": 90.0, "T": 120.0, "C": 0.0, "verify": 120.0}, global_cap_s=600.0, checkpoint_every_s=4.0, verify_threads=2,
                identity_k=6)
    base.update(kw)
    if "arm_tick_cap" in kw and "arm_caps" not in kw:
        base["arm_caps"] = {"T": kw["arm_tick_cap"]}
    return ses2.run_config(root=root, **base)


def run2_small(syn: Mapping[str, Any], *, world: str = "hard", inject: Optional[Mapping[str, Any]] = None, env_kw: Optional[Mapping[str, Any]] = None,
               immutability: Optional[Callable[[], Mapping[str, Any]]] = None, env_kw_factory: Optional[Callable[[Mapping[str, Any]], Mapping[str, Any]]] = None,
               **cfg_kw: Any) -> Tuple[Dict[str, Any], Any, Path, Path]:
    """The rd2 session (open protocol, materialise, Session2, run_all2) against a synthetic rd1 tree and the stub, on a private copy."""
    import m8_rd2_run as run2
    import m8_rd2_session as ses2

    cp = copy_tree(syn)
    root = cp["t"] / "rd2"
    cfg = small_cfg2(root, **cfg_kw)
    op = ses2.open_protocol(cp["root"], cp["incr"], expect=cp["expect"], check_overlay=False, live_pins=lambda: live_pins_of(cp), floor_min=FLOOR_MIN)
    check(op["ok"], f"open protocol: {op['problems']}")
    a2 = rs.materialise(cp["root"], root, facts=op["facts"], overlay=op["overlay"], lines_sha256=cp["lines"],
                        meta_extra={"pins": cp["pins"], "pin_tick0": op["facts"]["pin_tick0"], "ticks": {}, "ledger_T": {}},
                        increment_manifest_sha256=op["R1_rd1_immutability"]["manifest_sha256"], utc="2026-10-02T00:00:00Z", floor_min=FLOOR_MIN)
    cfg.session_dir.mkdir(parents=True)
    mw.ProvenanceGuard.install()
    mw.ProvenanceGuard.violations.clear()
    w2.WriteGuard.install([cp["root"]])
    try:
        env = stub_env2(world, cp["root"], inject, **dict(env_kw or {}), **dict(env_kw_factory(cp) if env_kw_factory else {}))
        sess = run2.Session2(cfg, env, archive=a2, archive_pin=op["facts"]["pin_tick0"], base_info={"overlay_sha256": op["overlay"]["sha256"]},
                             rd1_root=cp["root"], lines_sha256=cp["lines"])
        imm = immutability or (lambda: rs.rd1_immutability(cp["root"], cp["incr"]))
        out = run2.run_all2(sess, immutability=imm)
    finally:
        w2.WriteGuard.clear()
    return out, sess, root, cp["t"]


def unit_session2_small_run() -> Dict[str, Any]:
    import m8_rd2_report as rpt

    syn = synthetic_rd1()
    out, sess, root, t = run2_small(syn)
    rule, close = out["rule"], out["close"]
    check(not rule["invalid"] and not rule["incomplete"] and rule["outcome"] in rule2.OUTCOMES, f"a complete small session: {rule['outcome']} {rule['invalid']} {rule['incomplete']}")
    check(sess.ledgers["T"].ticks == 12000, f"the exploration committed exactly its cap: {sess.ledgers['T'].ticks}")
    sd = sess.cfg.session_dir
    for f in ("p1.json", "identity_open.json", "arm_T.json", "verification.json", "rule.json", "close.json", "state.json", "iterations_T.jsonl", "ledger_T.json",
              "candidates_T.jsonl.gz"):
        check((sd / f).is_file(), f"missing {f}")
    p1 = json.loads((sd / "p1.json").read_text(encoding="utf-8"))
    check(p1["tick0"]["equals_archive_pin"] and p1["selftest"]["corrupted_refused"] and len(p1["traces"]) == 2, "P1 against the archive's pin")
    io_ = json.loads((sd / "identity_open.json").read_text(encoding="utf-8"))
    check(io_["ok"] and io_["cells"] == 6 and io_["verified"] == 6, f"open identity replays: {io_}")
    ver = json.loads((sd / "verification.json").read_text(encoding="utf-8"))
    check(ver["identity"]["ok"] and ver["identity"]["verified"] == ver["identity"]["cells"] == 6, f"close identity replays {ver['identity']}")
    check(close["audit"]["ok"] and close["prefix_property"]["ok"] and close["rd1_immutability"]["ok"] and not close["guard_violations"], f"close checks: {close}")
    check(sess.first_iteration == syn["expect"]["dispatch_iterations"][1] + 1 and sess.archive.events[len(sess.archive.events) - 1]["ev"] in ("ingest", "dispatch"),
          "iterations continue after rd1's")
    its = [e["it"] for e in sess.archive.events if e["ev"] == "dispatch"]
    check(its == list(range(its[0], its[-1] + 1)) and its[0] == 0 and its.count(sess.first_iteration) == 1, "dispatch iterations are contiguous and never reused")
    rows = [json.loads(x) for x in (sd / "iterations_T.jsonl").read_text(encoding="utf-8").splitlines()]
    check(sum(r["ticks"] for r in rows if "ticks" in r) == 12000 and all(r["tick0_equal"] for r in rows if "ticks" in r), "iteration rows add up; tick 0 equal everywhere")
    # every rd2 burst after the switch carries the diagnostics and the four-element rows
    v2b = [b for b in sess.archive.bursts if b.iteration >= sess.first_iteration]
    check(v2b and all(b.ground_runs is not None and b.session == "rd2" for b in v2b), "rd2 bursts carry ground runs and the session name")
    check(all(len(b.reaches[0]) == 4 for b in v2b if b.reaches) and all(len(b.reaches[0]) == 3 for b in sess.archive.bursts if b.iteration < sess.first_iteration and b.reaches),
          "rd2 reach rows have four elements, rd1's keep three")
    vr = rpt.verify_run(root, syn["root"], "rd2")
    check(vr["ok"], f"verify-run: {vr['problems']}")
    for f in ("p1.json", "identity_open.json", "arm_T.json", "verification.json", "rule.json", "close.json", "state.json"):
        check(json.loads((sd / f).read_text(encoding="utf-8")).get("scope") == rule2.SCOPE, f"the scope label is carried by {f}")
    # verify-run refuses a session with no recorded decision, no close record, or an m the exact replays do not hold
    cp = tmpdir("m8vr2_")
    shutil.copytree(root, cp / "rd2")
    (cp / "rd2" / "sessions" / "rd2" / "rule.json").unlink()
    vr2 = rpt.verify_run(cp / "rd2", syn["root"], "rd2")
    check(not vr2["ok"] and any("no rule.json" in p for p in vr2["problems"]), f"no decision recorded: {vr2['problems']}")
    shutil.copytree(root, cp / "rd2b")
    (cp / "rd2b" / "sessions" / "rd2" / "close.json").unlink()
    check(not rpt.verify_run(cp / "rd2b", syn["root"], "rd2")["ok"], "no close record is refused")
    shutil.copytree(root, cp / "rd2c")
    rp_ = cp / "rd2c" / "sessions" / "rd2" / "rule.json"
    d_ = json.loads(rp_.read_text(encoding="utf-8"))
    d_["m"] = 4 if d_["m"] != 4 else 0
    rp_.write_text(json.dumps(d_), encoding="utf-8")
    check(not rpt.verify_run(cp / "rd2c", syn["root"], "rd2")["ok"], "a recorded m that the exact replays do not hold is refused")
    shutil.rmtree(cp, ignore_errors=True)
    rep = rpt.full_report(root, syn["root"], "rd2")
    check(rep["rd2"]["dispatches"] == len(v2b) + sum(1 for e in sess.archive.events if e["ev"] == "ingest" and e["burst"] == -1 and e["it"] >= sess.first_iteration)
          or rep["rd2"]["dispatches"] >= len(v2b), "the report counts rd2's dispatches")
    check(rep["rd2"]["returns"] == rep["rule_inputs"]["returns"] and "upb_start_heights" in rep and "D7_efficiency" in rep and "D8_v2_mechanism" in rep, "the report sections")
    sh = rep["D8_v2_mechanism"]["exact_ground_evidence_shadow"]
    check(sh["cells_differing"] == sh["doomed_only_under_exact_runs"] + sh["doomed_only_under_reaches"] and sh["cells_differing"] >= 0, f"the exact-evidence shadow reading: {sh}")
    check(abs(rep["D7_efficiency"]["prefix_share"] - sess.arm_records["T"]["prefix_ticks"] / 12000) < 1e-9, "D7 prefix share")
    check(rule["extra"]["rule_inputs"] == rep["rule_inputs"], "the rule inputs equal the report's")
    # rd1's tree is untouched: still equal to its increment, no file under it was written
    check(rs.rd1_immutability(syn["root"], syn["incr"])["ok"], "the shared synthetic rd1 tree is untouched")
    return {"outcome": rule["outcome"], "cells": len(sess.archive.cells), "ticks": 12000}


def unit_session2_outcomes_and_stops() -> Dict[str, Any]:
    syn = synthetic_rd1()
    res: Dict[str, Any] = {}
    out, sess, _r, _t = run2_small(syn, arm_tick_cap=3000, min_arm_ticks=5000)
    check(out["rule"]["outcome"] == "INCOMPLETE" and any("reached 3,000" in x for x in out["rule"]["incomplete"]), f"below the minimum: {out['rule']['incomplete']}")
    res["below_minimum"] = out["rule"]["outcome"]
    out, sess, _r, _t = run2_small(syn, inject={"lifecycle_jobs": [14]}, n_workers=2, arm_tick_cap=8000, min_arm_ticks=1000)
    check(1 <= sess.lifecycle_failures["T"] <= 3 and sess.ledgers["T"].ticks == 8000 and out["rule"]["outcome"] != "INCOMPLETE",
          f"redrawn lifecycle failures {sess.lifecycle_failures}: {out['rule']['outcome']} {out['rule']['incomplete']}")
    check(any(e["ev"] == "fail" for e in sess.archive.events), "the archive ledger records the failed iteration")
    check(s2.audit2(sess.archive, syn["lines"])["ok"], "an archive with a failed iteration still audits")
    res["lifecycle_redrawn"] = sess.lifecycle_failures["T"]
    out, sess, _r, _t = run2_small(syn, inject={"lifecycle_jobs": [14, 15, 16, 17]}, n_workers=2, arm_tick_cap=12000, min_arm_ticks=1000)
    check(out["rule"]["outcome"] == "INCOMPLETE" and any("lifecycle failures" in x for x in out["rule"]["incomplete"]), f"more than three: {out['rule']['incomplete']}")
    res["lifecycle_over"] = out["rule"]["outcome"]
    out, sess, _r, _t = run2_small(syn, inject={"mismatch_job": 14, "mismatch_tick": 5}, n_workers=2, arm_tick_cap=20000, min_arm_ticks=1000)
    check(out["rule"]["outcome"] == "INVALID" and any("prefix_end" in x for x in out["rule"]["invalid"]), f"an integrity mismatch: {out['rule']['invalid']}")
    check(list((sess.cfg.session_dir / "failures").glob("iterate_*")), "the failed return's raw replies are preserved")
    res["mismatch"] = out["rule"]["outcome"]
    out, sess, _r, _t = run2_small(syn, inject={"provenance_job": 14}, n_workers=2, arm_tick_cap=5000, min_arm_ticks=1000)
    check(out["rule"]["outcome"] == "INVALID" and any("provenance" in x for x in out["rule"]["invalid"]), f"a provenance violation: {out['rule']['invalid']}")
    res["provenance"] = out["rule"]["outcome"]
    # rd1's tree changed (the close R1 fails) -> INVALID, whatever else happened
    out, sess, _r, _t = run2_small(syn, arm_tick_cap=3000, min_arm_ticks=1000, immutability=lambda: {"ok": False, "problems": ["cells.jsonl differs"]})
    check(out["rule"]["outcome"] == "INVALID" and any("rd1's tree changed" in x for x in out["rule"]["invalid"]), f"a changed rd1 tree: {out['rule']['invalid']}")
    res["rd1_changed"] = out["rule"]["outcome"]
    # a write under rd1's tree is a guard violation -> INVALID (the write happens in the session process, through the clock's memory probe)
    def writer(cp: Mapping[str, Any]) -> Mapping[str, Any]:
        done: List[int] = []

        def private_mb() -> float:
            if not done:
                done.append(1)
                (Path(cp["root"]) / "archive" / "stray.txt").write_text("x", encoding="utf-8")
            return 100.0

        return {"private_mb": private_mb}

    out, sess, _r, _t = run2_small(syn, inject={"slow_s": 0.02}, n_workers=2, arm_tick_cap=20000, min_arm_ticks=100, env_kw_factory=writer)
    check(out["rule"]["outcome"] == "INVALID" and any("protected root" in x or "rd1's tree changed" in x for x in out["rule"]["invalid"]),
          f"a write under rd1's tree: {out['rule']['outcome']} {out['rule']['invalid']}")
    check(any("protected root" in x for x in out["rule"]["invalid"]), f"the write guard named it: {out['rule']['invalid']}")
    res["rd1_write"] = out["rule"]["outcome"]
    # a software error in one close check is recorded (INCOMPLETE) and cannot hide the others
    def broken() -> Mapping[str, Any]:
        raise RuntimeError("injected immutability failure")

    out, sess, _r, _t = run2_small(syn, arm_tick_cap=3000, min_arm_ticks=1000, immutability=broken)
    cl = out["close"]
    check(out["rule"]["outcome"] == "INCOMPLETE" and any("rd1_immutability could not run" in x for x in out["rule"]["incomplete"]), f"an erroring close check: {out['rule']['incomplete']}")
    check("rd1_immutability_error" in cl and cl["audit"]["ok"] and cl["prefix_property"]["ok"], "the other close checks still ran")
    res["close_check_error"] = out["rule"]["outcome"]
    # a memory breach and a process-count breach -> INCOMPLETE
    class LateBreach:
        def __init__(self) -> None:
            self.t0 = time.monotonic()

        @property
        def breach(self) -> Optional[str]:
            return "memory cap: process tree private 99999 MB > 9216 MB" if time.monotonic() - self.t0 > 2.5 else None

    out, sess, _r, _t = run2_small(syn, env_kw={"sampler": LateBreach()}, inject={"slow_s": 0.05}, n_workers=2, arm_tick_cap=10 ** 7, min_arm_ticks=1000)
    check(out["rule"]["outcome"] == "INCOMPLETE" and any("memory cap" in x for x in out["rule"]["incomplete"]), f"a memory breach: {out['rule']['incomplete']}")
    res["memory"] = out["rule"]["outcome"]
    out, sess, _r, _t = run2_small(syn, env_kw={"tree_snapshot": lambda: {"battleship": 11}}, inject={"slow_s": 0.05}, n_workers=2, arm_tick_cap=10 ** 6,
                                   min_arm_ticks=1000, process_check_every_s=0.05)
    check(out["rule"]["outcome"] == "INCOMPLETE" and any("11 BattleShip processes" in x for x in out["rule"]["incomplete"]), "a process-count breach")
    res["processes"] = out["rule"]["outcome"]
    # the exploration's wall cap: valid at or above the minimum
    out, sess, _r, _t = run2_small(syn, inject={"slow_s": 0.04}, n_workers=2, arm_tick_cap=10 ** 7, min_arm_ticks=500,
                                   wall_caps_s={"p1": 90.0, "T": 2.0, "C": 0.0, "verify": 120.0}, global_cap_s=900.0)
    tT = sess.ledgers["T"].ticks
    check(sess.arm_records["T"]["stop"][0] == "wall_cap" and 500 <= tT < 10 ** 7 and not out["rule"]["incomplete"], f"a wall-capped exploration at or above the minimum is valid ({tT}): {out['rule']['incomplete']}")
    res["wall_cap"] = tT
    return res


def unit_session2_replay_cap() -> Dict[str, Any]:
    """The replay cap leaves candidates unverified: INCOMPLETE only when one could raise m."""
    syn = synthetic_rd1()
    out, sess, _r, _t = run2_small(syn, replay_tick_cap=150, arm_tick_cap=12000, min_arm_ticks=2000)
    ver = json.loads((sess.cfg.session_dir / "verification.json").read_text(encoding="utf-8"))
    check(ver["cap_hit"] is not None, "the replay cap was hit")
    ident = ver["identity"]
    if not ident or ident.get("verified") != ident.get("cells"):
        check(out["rule"]["outcome"] == "INCOMPLETE" and any("close identity replays did not complete" in x for x in out["rule"]["incomplete"]),
              f"close identity replays skipped at a cap must be INCOMPLETE: {out['rule']['outcome']} {out['rule']['incomplete']}")
    if out["rule"]["outcome"] == "INCOMPLETE":
        check(any("could raise m" in x for x in out["rule"]["incomplete"]) or any("close identity" in x for x in out["rule"]["incomplete"]),
              f"INCOMPLETE only with a reason: {out['rule']['incomplete']}")
    else:
        check(ver["arm"]["max_m_unverified"] <= ver["arm"]["m"], "a cap that cannot raise m is not INCOMPLETE")
    return {"outcome": out["rule"]["outcome"]}


def unit_cmd_run_with_fake_game() -> Dict[str, Any]:
    """`run`'s own sequence against the REAL lifecycle code and a fake game, on a synthetic rd1 tree: the open protocol (R1-R5), materialise,
    rd1's frozen runtime read in place, the whole-process-tree sampler, the real replay path, the close checks. Only the preflight (tested on its
    own) and the kill-on-close job are replaced."""
    import m7_runtime
    import m8_rd_session as ses1
    import m8_rd2_session as ses2

    fg = t1.fake_game_setup("m8cr2_")
    t = fg["t"]
    (fg["exe_dir"] / "config.yml").write_text("fake: true\n", encoding="utf-8")
    fx = t1.fake_flags(fg, "easy")
    fv = dict(fx, SSB64_RL_ENTITY="1", SSB64_RL_TARGET_DIAG="1", SSB64_RL_INPUT="1")
    saved1 = {k: getattr(ses1, k) for k in ("EXECUTABLE", "EXE_DIR", "RUNTIME_FILES", "p1_inputs")}
    keys2 = ("RD1_ROOT", "RD2_ROOT", "APPROVAL", "INCREMENT_RD1", "EXECUTABLE", "EXE_DIR", "FLAGS_EXPLORE", "FLAGS_VERIFY", "N_WORKERS", "RD1_EXPECT",
             "CHECK_EXPECTED_OVERLAY", "preflight")
    saved2 = {k: getattr(ses2, k) for k in keys2}
    saved_job = m7_runtime.install_kill_on_close_job
    saved_prep = m7_runtime.prepare_worker_runtime
    try:
        ses1.EXECUTABLE = fg["cmd"]
        ses1.EXE_DIR = fg["exe_dir"]
        ses1.RUNTIME_FILES = ("BattleShip.o2r", "f3d.o2r", "gamecontrollerdb.txt")
        ses1.p1_inputs = lambda: stub.p1_inputs("easy", (200, 150))
        exe_sha = mw.sha256_file(fg["cmd"])
        rt_pins = ses1.runtime_pins()
        syn = synthetic_rd1("easy", t_cap=16000, c_cap=12000, flags={"explore": fx, "verify": fv}, exe_sha=exe_sha, runtime_files=rt_pins, cache=False)
        approval = {"approval": "APPROVED by the test", "revision": 1, "executable_sha256": exe_sha, "contracts": syn["pins"]["contracts"],
                    "flags": {"explore": fx, "verify": fv}, "git_head": "0" * 40, "rule_sha256": rule2.rule_digest(), "p1": {}}
        (t / "approval.json").write_text(json.dumps(approval), encoding="utf-8")
        ses2.RD1_ROOT, ses2.RD2_ROOT = syn["root"], t / "rd2"
        ses2.APPROVAL, ses2.INCREMENT_RD1 = t / "approval.json", syn["incr"]
        ses2.EXECUTABLE, ses2.EXE_DIR, ses2.FLAGS_EXPLORE, ses2.FLAGS_VERIFY = fg["cmd"], fg["exe_dir"], fx, fv
        ses2.N_WORKERS = 2
        ses2.RD1_EXPECT = syn["expect"]
        ses2.CHECK_EXPECTED_OVERLAY = False
        ses2.preflight = lambda **k: {"ok": True, "problems": [], "executable_sha256": exe_sha, "git_head": "0" * 40}
        m7_runtime.install_kill_on_close_job = lambda: None
        real_build = ses2.build_real_env2

        def build(*a: Any, **k: Any) -> Any:
            env = real_build(*a, **k)
            env.analyse = stub.analyse                                   # the fake game has no target diagnostic
            return env

        ses2.build_real_env2 = build
        rc = ses2.cmd_run(overrides=dict(arm_tick_cap=3000, arm_caps={"T": 3000}, min_arm_ticks=1000, verify_threads=2, identity_k=4,
                                         wall_caps_s={"p1": 120.0, "T": 150.0, "C": 0.0, "verify": 150.0}, global_cap_s=900.0, p1_tick_cap=20000))
    finally:
        ses2.build_real_env2 = real_build
        for k, v in saved2.items():
            setattr(ses2, k, v)
        for k, v in saved1.items():
            setattr(ses1, k, v)
        m7_runtime.install_kill_on_close_job = saved_job
        m7_runtime.prepare_worker_runtime = saved_prep
        w2.WriteGuard.clear()
    check(rc == 0, "cmd_run returned 0")
    root = t / "rd2"
    sd = root / "sessions" / "rd2"
    for f in ("open.json", "approval_copy.json", "p1.json", "identity_open.json", "rule.json", "close.json", "memory_summary.json", "memory_tree.jsonl", "state.json"):
        check((sd / f).is_file(), f"missing {f}")
    rule = json.loads((sd / "rule.json").read_text(encoding="utf-8"))
    check(rule["outcome"] in rule2.OUTCOMES and not rule["invalid"] and not rule["incomplete"], f"cmd_run's session: {rule['outcome']} {rule['invalid']} {rule['incomplete']}")
    op = json.loads((sd / "open.json").read_text(encoding="utf-8"))
    check(op["pins"]["approval_sha256"] == mw.sha256_file(t / "approval.json") and op["pins"]["executable_sha256"] == exe_sha, "the open record pins the approval and the executable")
    check((sd / "approval_copy.json").read_bytes() == (t / "approval.json").read_bytes(), "a verbatim copy of the approval")
    check(op["open_protocol"]["R1_rd1_immutability"]["ok"] and op["open_protocol"]["R5_overlay"]["ok"], "the open record holds R1-R5")
    log = t1.fake_log(fg)
    frozen_h = syn["frozen"]["BattleShip.cfg.json"]
    check(log and all(x["cfg_sha256"] == frozen_h for x in log), f"every process read rd1's FROZEN configuration ({len(log)} launches)")
    check(all(x["cfg_sha256"] != fg["live_hash"] for x in log), "no process read the live configuration")
    check(any(x["flags"].get("SSB64_RL_TARGET_DIAG") == "1" for x in log), "the verification replays ran with the four diagnostics")
    check(t1.wait_dead([x["pid"] for x in log], 30.0) == [], "no fake game process survived the run")
    check(rs.rd1_immutability(syn["root"], syn["incr"])["ok"], "rd1's tree is byte-identical to its increment after the run")
    # the command refuses when the preflight does, before creating anything
    ses2.preflight = lambda **k: {"ok": False, "problems": ["x"]}
    ses2.RD2_ROOT = t / "rd2_never"
    try:
        check(ses2.cmd_run() == 2 and not (t / "rd2_never").exists(), "a failing preflight refuses before anything is created")
    finally:
        ses2.preflight = saved2["preflight"]
        ses2.RD2_ROOT = saved2["RD2_ROOT"]
    shutil.rmtree(t, ignore_errors=True)
    shutil.rmtree(syn["t"], ignore_errors=True)
    return {"launches": len(log), "outcome": rule["outcome"]}


# -- approval, preflight pieces, guards ------------------------------------------------------------------------------------------------


def unit_approval_isolated2() -> Dict[str, Any]:
    import m8_rd2_session as ses2

    want = ses2.identity()
    t = tmpdir("m8ap2_")
    p = t / "approval.json"
    ok, why = ses2.approval_status(p, want)
    check(not ok and "no approval record" in why, "no record: refused")
    good = dict(want, approval="APPROVED by the test", revision=1)
    p.write_text(json.dumps(good), encoding="utf-8")
    check(ses2.approval_status(p, want) == (True, "approved"), "a matching record is accepted")
    p.write_text(json.dumps(dict(good, approval="PENDING")), encoding="utf-8")
    check(not ses2.approval_status(p, want)[0], "PENDING is refused")
    n = 0
    alter = {"rule_sha256": "0" * 64, "executable_sha256": "0" * 64, "scope": "other", "archive_id": "x", "workers": 4, "burst_words": 121, "horizon": 3599,
             "flags": {"explore": {}, "verify": {}}, "contracts": dict(want["contracts"], m8_rd_select_v2="0" * 64), "key_strings": {"select_v2": "x"},
             "runtime_files": {"BattleShip.o2r": "0" * 64}, "p1": {}, "readiness": {"min_available_mb": 1}, "git_head": "0" * 40, "session": "rdX",
             "gate": "x", "milestone": "M9", "rule": "other", "base": dict(want["base"], rd1_increment_manifest_sha256="0" * 64),
             "open_overlay": {"sha256": "0" * 64}, "budgets": {"hard_cap": "61 min"}, "docs_sha256": {"docs/x.md": "0" * 64}}
    for k, v in alter.items():
        p.write_text(json.dumps(dict(good, **{k: v})), encoding="utf-8")
        check(not ses2.approval_status(p, want)[0], f"an altered {k} was accepted")
        n += 1
    for k in list(want["caps"]):
        caps = dict(want["caps"])
        caps[k] = {"x": 1}
        p.write_text(json.dumps(dict(good, caps=caps)), encoding="utf-8")
        check(not ses2.approval_status(p, want)[0], f"an altered cap {k} was accepted")
        n += 1
    for f in list(want["code"]):
        code = dict(want["code"])
        code[f] = "0" * 64
        p.write_text(json.dumps(dict(good, code=code)), encoding="utf-8")
        check(not ses2.approval_status(p, want)[0], f"an altered code hash for {f} was accepted")
        n += 1
    p.write_text(json.dumps(dict(good, d_records={"folders": ["2026-09-28"], "digest": "0" * 64})), encoding="utf-8")
    check(not ses2.approval_status(p, want)[0], "an altered D: records digest")
    p.write_text("{not json", encoding="utf-8")
    raises(ValueError, lambda: ses2.approval_status(p, want), "an unreadable record raises")
    check(ses2.APPROVAL != p and ses2.APPROVAL.name == "rl_m8_rd2_approval.json", "the repository path is untouched by the tests")
    check(set(want["contracts"]) == {"m8_rd_cell_v1", "m8_rd_select_v1", "m8_rd_explore_v1", "m8_rd_claims_v1", "track1_btt_s9_b8_v1", "btt_action_class_table_v2",
                                     "m8_rd_select_v2"}, "contract digests")
    check(want["rule"] == "m8_rd2_rule_v1" and want["workers"] == 5 and want["horizon"] == 3600 and want["base"]["rd1_checkpoint_seq"] == 7
          and want["base"]["rd1_increment"] == rs.RD1_INCREMENT_NAME, "registered identity entries")
    for f in ses2.NEW_CODE_FILES:
        check(f"rl/{f}" in want["code"] or f in ("m8_rd2_tests.py", "m8_rd2_snapshot.py", "m8_rd2_session.py") or not (RL_DIR / f).is_file(), f"{f} is pinned")
    shutil.rmtree(t, ignore_errors=True)
    return {"altered_entries_refused": n}


def unit_import_isolation2() -> Dict[str, Any]:
    code = ("import sys; sys.path.insert(0, r'%s'); " % RL_DIR + "import m8_rd_select2, m8_rd_resume, m8_rd2_worker, m8_rd2_run, m8_rd2_session, m8_rd2_rule, m8_rd2_report; "
            "print(sorted(m for m in ('torch', 'numpy', 'gymnasium', 'stable_baselines3', 'm7u3_gate', 'm7f_trace', 'm7n_crossing', 'm7g_fixture', 'btt_learning', "
            "'m7h_curriculum') if m in sys.modules))")
    r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=120)
    check(r.stdout.strip() == "[]", f"the rd2 modules imported heavy ones: {r.stdout.strip()} {r.stderr[-300:]}")
    return {}


def unit_source_guard2() -> Dict[str, Any]:
    """No rd2 module reads fixtures, recordings, the TAS or any .btti file; none imports a learning framework or the random module; and no
    call that writes can take a path built from rd1's root (rd1's tree is read-only)."""
    forbidden = ("rl/fixtures", "fixtures/m7g", "m7g/capture", "tas_input", "mario_743", ".btti", "btti_replay", "crossing_fixture", "rl_crossing")
    bad_imports = {"random", "torch", "gymnasium", "stable_baselines3", "numpy", "pandas", "scipy", "sklearn"}
    write_attrs = {"write_text", "write_bytes", "mkdir", "unlink", "rmdir", "touch", "rename", "replace", "chmod"}
    copy_funcs = {"copyfile", "copy", "copy2", "copytree", "move"}
    writers = {"write_json", "append_jsonl", "save_checkpoint", "write_files", "rmtree", "rmtree_retry", "remove_tree_retry", "replace_retry", "makedirs"}
    names_rd1 = ("rd1_root", "RD1_ROOT", "rd1_archive_dir", "M8_ROOT")
    hits: Dict[str, List[str]] = {}
    for name in NEW_MODULES:
        raw = (RL_DIR / f"{name}.py").read_text(encoding="utf-8")
        body = "\n".join(ln for ln in raw.replace("\\", "/").splitlines() if not ln.lstrip().startswith("FORBIDDEN_FRAGMENTS"))
        found = [f for f in forbidden if f in body]
        tree = ast.parse(raw)
        imports = set()
        for nd in ast.walk(tree):
            if isinstance(nd, ast.Import):
                imports |= {a.name.split(".")[0] for a in nd.names}
            elif isinstance(nd, ast.ImportFrom) and nd.module:
                imports.add(nd.module.split(".")[0])
        found += [f"import {i}" for i in sorted(imports & bad_imports)]

        def mentions_rd1(node: ast.AST) -> bool:
            return any(n in ast.unparse(node) for n in names_rd1)

        for nd in ast.walk(tree):
            if not isinstance(nd, ast.Call):
                continue
            f = nd.func
            fname = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
            if isinstance(f, ast.Attribute) and fname in write_attrs and mentions_rd1(f.value):
                found.append(f"write call on rd1 path: {ast.unparse(nd)[:80]}")
            if fname in writers and nd.args and mentions_rd1(nd.args[0]):
                found.append(f"write call with rd1 path: {ast.unparse(nd)[:80]}")
            if fname in copy_funcs and len(nd.args) >= 2 and mentions_rd1(nd.args[1]):
                found.append(f"copy into rd1 path: {ast.unparse(nd)[:80]}")
            if fname == "open" and len(nd.args) >= 2 and nd.args[0] and mentions_rd1(nd.args[0]):
                mode = ast.unparse(nd.args[1])
                if any(c in mode for c in "wax+"):
                    found.append(f"open for write on rd1 path: {ast.unparse(nd)[:80]}")
        if found:
            hits[name] = found
    check(not hits, f"forbidden vocabulary, imports or writes in the rd2 modules: {hits}")
    return {"modules": len(NEW_MODULES)}


def unit_tracked_files_unchanged2() -> Dict[str, Any]:
    import m8_rd_session as ses1

    check(ses1.tracked_changes() == [], f"tracked files differ from HEAD: {ses1.tracked_changes()[:5]}")
    check(ses1.untracked_not_new() == [], f"git status shows more than new files: {ses1.untracked_not_new()[:5]}")
    for f in RD1_FILES + ("m8_rd_tests",):
        r = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", str(RL_DIR / f"{f}.py")], cwd=REPO_ROOT)
        check(r.returncode == 0, f"rd1's {f}.py differs from HEAD")
    for d in ("docs/rl_m8_rd_proposal_2026-10-01.md", "docs/rl_m8_rd_amendment_2026-10-02.md", "docs/rl_m8_rd_implementation.md",
              "docs/rl_m8_rd_continuation_proposal_2026-10-02.md", "docs/rl_m8_rd1_results_2026-10-02.md", "docs/rl_m8_rd1_diagnosis_2026-10-02.md"):
        r = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", str(REPO_ROOT / d)], cwd=REPO_ROOT)
        check(r.returncode == 0, f"{d} differs from HEAD")
    return {"rd1_files": len(RD1_FILES)}


def unit_snapshot_tool2() -> Dict[str, Any]:
    t = tmpdir("m8sn2_")
    dest = t / "snap"
    r = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_rd2_snapshot.py"), "snapshot", "--dest", str(dest)], capture_output=True, text=True, timeout=900)
    check(r.returncode == 0, f"snapshot: {r.stdout[-500:]} {r.stderr[-500:]}")
    rec = json.loads((dest / "snapshot.json").read_text(encoding="utf-8"))
    check(rec["result"] == "PASS" and rec["n_files"] > 30 and not rec["problems"] and not rec["identity_code_mismatch"] and not rec["identity_docs_mismatch"],
          f"snapshot record: {rec['result']} {rec['problems']} {rec['identity_code_mismatch']} {rec['identity_docs_mismatch']}")
    names = {f["path"] for f in rec["files"]}
    check({"rl/m8_rd_select2.py", "rl/m8_rd2_run.py", "rl/m8_rd_cells.py", "docs/rl_m8_rd_continuation_proposal_2026-10-02.md"} <= names, "the snapshot holds the rd1 and rd2 code and the proposal")
    r = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_rd2_snapshot.py"), "verify", "--dest", str(dest)], capture_output=True, text=True, timeout=900)
    check(r.returncode == 0, f"verify: {r.stdout[-300:]}")
    r = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_rd2_snapshot.py"), "snapshot", "--dest", str(dest)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 2, "an existing destination is never overwritten")
    victim = dest / "files" / "rl" / "m8_rd_select2.py"
    victim.write_bytes(victim.read_bytes() + b"\n#tampered\n")
    r = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_rd2_snapshot.py"), "verify", "--dest", str(dest)], capture_output=True, text=True, timeout=900)
    check(r.returncode == 1 and "m8_rd_select2.py" in r.stdout, "a tampered copy fails the verification")
    ps = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_rd2_snapshot.py"), "powershell", "--dest", str(dest)], capture_output=True, text=True, timeout=60)
    check("Get-FileHash" in ps.stdout, "the independent re-hash script is generated")
    shutil.rmtree(t, ignore_errors=True)
    return {"files": rec["n_files"]}


# -- the registry and the CLI ----------------------------------------------------------------------------------------------------------------


TESTS: List[Tuple[str, Callable[[], Dict[str, Any]]]] = [
    ("select2_contract", unit_select2_contract), ("bound_rule", unit_bound_rule), ("descent_tree_vs_reference", unit_descent_tree_vs_reference),
    ("descent_doom_semantics", unit_descent_doom_semantics), ("archive2_mode1_equals_v1", unit_archive2_mode1_equals_v1),
    ("select2_probabilities", unit_select2_probabilities), ("replacement_v2", unit_replacement_v2), ("ledger_rebuild_v2", unit_ledger_rebuild_v2),
    ("begin_v2_and_persistence", unit_begin_v2_and_persistence), ("overlay", unit_overlay), ("iterate2_equals_iterate", unit_iterate2_equals_iterate),
    ("write_guard", unit_write_guard), ("rule2_module", unit_rule2_module), ("report_on_rd1_reference", unit_report_on_rd1_reference),
    ("open_overlay_on_rd1_reference", unit_open_overlay_on_rd1_reference), ("budget_projection", unit_budget_projection),
    ("identity_samples", unit_identity_samples), ("resume_protocol_synthetic", unit_resume_protocol_synthetic),
    ("session2_small_run", unit_session2_small_run), ("session2_outcomes_and_stops", unit_session2_outcomes_and_stops),
    ("session2_replay_cap", unit_session2_replay_cap), ("cmd_run_with_fake_game", unit_cmd_run_with_fake_game),
    ("approval_isolated2", unit_approval_isolated2), ("import_isolation2", unit_import_isolation2), ("source_guard2", unit_source_guard2),
    ("tracked_files_unchanged2", unit_tracked_files_unchanged2), ("snapshot_tool2", unit_snapshot_tool2),
]


def run_unit(only: Optional[Sequence[str]] = None, out: Optional[Path] = None) -> int:
    passed, failed = 0, []
    results: Dict[str, Any] = {}
    t_all = time.perf_counter()
    for name, fn in TESTS:
        if only and name not in only:
            continue
        t0 = time.perf_counter()
        try:
            detail = fn()
            results[name] = {"ok": True, "s": round(time.perf_counter() - t0, 1), "detail": detail}
            passed += 1
            print(f"PASS {name} ({time.perf_counter() - t0:.1f} s)", flush=True)
        except Exception as exc:  # noqa: BLE001
            results[name] = {"ok": False, "s": round(time.perf_counter() - t0, 1), "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-2500:]}
            failed.append(name)
            print(f"FAIL {name}: {type(exc).__name__}: {exc}\n{traceback.format_exc()[-1800:]}", flush=True)
    for rec in _SYN.values():
        shutil.rmtree(rec["t"], ignore_errors=True)
    total = passed + len(failed)
    if out is not None:
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "m8_rd2_unit.json").write_text(json.dumps({"passed": passed, "total": total, "failed": failed, "wall_s": round(time.perf_counter() - t_all, 1),
                                                           "results": results}, indent=1, default=str) + "\n", encoding="utf-8")
    print(f"{passed} / {total} passed (unit); wall {time.perf_counter() - t_all:.0f} s")
    return 0 if not failed else 1


# -- the production-count synthetic end-to-end run -----------------------------------------------------------------------------------------


def e2e(out: Path, small: bool = False, world: str = "hard") -> int:
    """The rd2 session at the registered counts (6,000,000 exploration ticks valid from 2,000,000, five workers, the registered caps and
    memory sampler) against a synthetic rd1 tree and the stub: the resume path (R1-R6), the overlay, P1 against the archive's pin, the open
    and close identity replays, the v2 selection and replacement, the descent-doom tree, the rule, the close audit and verify-run. The world
    is synthetic: the outcome says nothing about Mario."""
    import m8_rd2_report as rpt
    import m8_rd2_run as run2
    import m8_rd2_session as ses2
    import m8_rd_session as ses1

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    problems: List[str] = []
    t0 = time.perf_counter()
    syn = synthetic_rd1(world, t_cap=60000 if small else 600000, c_cap=40000 if small else 480000, cache=False)
    print(f"[e2e] synthetic rd1 tree built in {time.perf_counter() - t0:.0f} s: {syn['expect']}", flush=True)
    root = out / "rd2"
    if root.exists():
        shutil.rmtree(root)
    kw: Dict[str, Any] = dict(checkpoint_every_s=30.0)
    if small:
        kw.update(arm_tick_cap=200000, arm_caps={"T": 200000}, min_arm_ticks=60000, p1_tick_cap=70000)
    cfg = ses2.run_config(root=root, **kw)
    op = ses2.open_protocol(syn["root"], syn["incr"], expect=syn["expect"], check_overlay=False, live_pins=lambda: live_pins_of(syn), floor_min=FLOOR_MIN)
    if not op["ok"]:
        problems.append(f"open protocol: {op['problems']}")
    a2 = rs.materialise(syn["root"], root, facts=op["facts"], overlay=op["overlay"], lines_sha256=syn["lines"],
                        meta_extra={"pins": syn["pins"], "pin_tick0": op["facts"]["pin_tick0"], "ticks": {}, "ledger_T": {}},
                        increment_manifest_sha256=op["R1_rd1_immutability"]["manifest_sha256"], utc=ses2.utc(), floor_min=FLOOR_MIN)
    cfg.session_dir.mkdir(parents=True)
    sampler = ses1.make_sampler(out / "memory_tree.jsonl", cfg.memory_caps_mb)
    sampler.start()
    mw.ProvenanceGuard.install()
    mw.ProvenanceGuard.violations.clear()
    w2.WriteGuard.install([syn["root"]])
    logs: List[str] = []

    def log(s: str) -> None:
        line = f"[e2e {time.strftime('%H:%M:%S')}] {s}"
        logs.append(line)
        print(line, flush=True)

    env = stub_env2(world, syn["root"], None, tree_snapshot=lambda: getattr(sampler, "last", None), sampler=sampler, log=log)
    try:
        import m7u_gate as g1

        env.private_mb = g1.private_mb
    except Exception:  # noqa: BLE001
        pass
    t1_ = time.perf_counter()
    sess = run2.Session2(cfg, env, archive=a2, archive_pin=op["facts"]["pin_tick0"], base_info={"overlay_sha256": op["overlay"]["sha256"]}, rd1_root=syn["root"],
                         lines_sha256=syn["lines"])
    res = run2.run_all2(sess, immutability=lambda: rs.rd1_immutability(syn["root"], syn["incr"]))
    wall = time.perf_counter() - t1_
    mem = sampler.stop()
    w2.WriteGuard.clear()
    rule, close = res["rule"], res["close"]
    vr = rpt.verify_run(root, syn["root"], "rd2")
    report = rpt.full_report(root, syn["root"], "rd2")
    want = cfg.arm_cap("T")
    if sess.ledgers["T"].ticks != want:
        problems.append(f"exploration ticks {sess.ledgers['T'].ticks} != {want}")
    if rule["outcome"] in ("INVALID", "INCOMPLETE"):
        problems.append(f"outcome {rule['outcome']}: {rule['invalid']} {rule['incomplete']}")
    if not vr["ok"]:
        problems.append(f"verify-run: {vr['problems']}")
    if not close.get("audit", {}).get("ok"):
        problems.append(f"close audit: {close.get('audit')}")
    if mem["breach"]:
        problems.append(f"memory sampler breach {mem['breach']}")
    if mw.ProvenanceGuard.violations:
        problems.append(f"guard violations {mw.ProvenanceGuard.violations[:2]}")
    if not rs.rd1_immutability(syn["root"], syn["incr"])["ok"]:
        problems.append("rd1's synthetic tree changed")
    ver = json.loads((root / "sessions" / "rd2" / "verification.json").read_text(encoding="utf-8"))
    summary = {"small": small, "world": world, "wall_s": round(wall, 1), "outcome": rule["outcome"], "m": rule["m"], "ticks": sess.ledgers["T"].ticks,
               "exploration_wall_s": sess.arm_records["T"]["wall_s"], "ticks_per_s": sess.arm_records["T"]["ticks_per_s"], "stop": sess.arm_records["T"]["stop"],
               "cells": len(sess.archive.cells), "rd1_cells": syn["expect"]["cells"], "bursts": len(sess.archive.bursts), "candidates": len(sess.ledgers["T"].candidates),
               "phase_wall_s": sess.clock.to_json()["phase_wall_s"], "peak_main_private_mb": mem["peak"]["main_private_mb"],
               "peak_tree_private_mb": mem["peak"]["tree_private_mb"], "peak_tree_working_set_mb": mem["peak"]["tree_working_set_mb"], "peak_processes": mem["peak"]["processes"],
               "memory_samples": mem["samples"], "verify_run": vr["ok"], "replay_ticks": sess.ticks["replays"], "open_identity": sess.open_identity_record,
               "identity_close": ver["identity"], "audit": close.get("audit"), "prefix_property": close.get("prefix_property"), "archive_stats": sess.archive.stats(),
               "diag2": {k: (len(v) if isinstance(v, list) else v) for k, v in sess.archive.diag2.items()}, "lifecycle_failures": sess.lifecycle_failures,
               "rule_inputs": rule["extra"]["rule_inputs"], "stops": rule["any_stop"], "overlay_open": op["overlay"]["counts"],
               "overlay_close": close.get("archive", {}).get("overlay_close"), "upb": report.get("upb_start_heights", {}).get("transitions"),
               "problems": problems}
    (out / "e2e.json").write_text(json.dumps(summary, indent=1, default=str) + "\n", encoding="utf-8")
    (out / "e2e.log").write_text("\n".join(logs) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=1, default=str))
    shutil.rmtree(syn["t"], ignore_errors=True)
    print("E2E PASS" if not problems else f"E2E FAIL: {problems}")
    return 0 if not problems else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("unit", "e2e", "list"))
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--only", default=None)
    ap.add_argument("--small", action="store_true")
    ap.add_argument("--world", default="hard", choices=sorted(stub.WORLDS))
    a = ap.parse_args(argv)
    if a.cmd == "list":
        for name, _fn in TESTS:
            print(name)
        return 0
    if a.cmd == "unit":
        return run_unit(a.only.split(",") if a.only else None, a.out or Path(tempfile.mkdtemp(prefix="m8_unit2_")))
    return e2e(a.out or Path(tempfile.mkdtemp(prefix="m8_e2e2_")), small=a.small, world=a.world)


if __name__ == "__main__":
    sys.exit(main())
