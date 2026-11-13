#!/usr/bin/env python3
"""Option D tests (docs/frs_option_d_design_2026-11-11.md section 9). Zero native ticks: no ROM, no game process. Phase 1 covers the
selection (tools/frs/order_select.py) with pure in-process tests (a fake archive and a fake burst oracle, U2 to U12) and the run 3
manifest check (T-M1); phase 2 covers the search (tools/frs/order_search.py) on run 3's fake game (E1 to E6, U11, U13, T-M2) and one
read-only real-lab reading (the frontier's best).

    python -B tools/frs/order_search_tests.py            every test
    python -B tools/frs/order_search_tests.py unit       the in-process tests only
    python -B tools/frs/order_search_tests.py e2e        the fake-game nights (zero native ticks; a few minutes)
    python -B tools/frs/order_search_tests.py real       the read-only real-lab tests
    python -B tools/frs/order_search_tests.py <name>...  the named tests
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
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
import frs_guard as g  # noqa: E402
import order_search as O  # noqa: E402
import order_select as osel  # noqa: E402
import run3_load as rl3  # noqa: E402
import run3_select as rs  # noqa: E402
from infra_testlib import check, cleanup, run_suite, tmpdir  # noqa: E402

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


# -- a fake archive and a fake game (pure, zero native ticks) -----------------------------------------------------------------------------

NEW, REPLACED, LATER = rs.NEW, rs.REPLACED, "later"


def level_of(mask: int) -> int:
    return osel.TARGETS_TOTAL - bin(int(mask) & osel.ROOT_MASK).count("1")


def _words(tag: str, n: int) -> bytes:
    h = hashlib.sha256(tag.encode()).digest()
    return (h * (n // len(h) + 1))[:n]


def _digest(words: bytes) -> str:
    return hashlib.sha256(b"w" + words).hexdigest()[:16]


@dataclass
class FCell:
    """The fields of crossing_search.Cell that the selectors read."""
    cid: int
    key: Tuple[int, int, str, int, int]
    level: int
    tick: int
    words: Optional[bytes]
    digest: str
    chain: bytes
    quarantined: Optional[str] = None
    retired: Optional[str] = None

    def alive(self) -> bool:
        return self.words is not None and self.quarantined is None and self.retired is None


class FArchive:
    """crossing_search.Archive's keep rule (a key's representative is its earliest arrival), in memory."""

    def __init__(self, bound: int = 600):
        self.cells: List[FCell] = []
        self.by_key: Dict[Tuple[Any, ...], int] = {}
        self.bound = int(bound)

    def eligible(self, c: FCell) -> bool:
        return c.alive() and c.level < osel.TARGETS_TOTAL and c.tick <= self.bound

    def keep(self, key: Sequence[Any], tick: int, words: bytes) -> Tuple[str, FCell]:
        k = (int(key[0]), int(key[1]), str(key[2]), int(key[3]), int(key[4]))
        chain = hashlib.sha256(b"c" + words).digest()
        cid = self.by_key.get(k)
        if cid is None:
            c = FCell(len(self.cells), k, level_of(k[3]), int(tick), bytes(words), _digest(words), chain)
            self.cells.append(c)
            self.by_key[k] = c.cid
            return NEW, c
        c = self.cells[cid]
        if int(tick) >= c.tick:
            return LATER, c
        c.tick, c.words, c.digest, c.chain = int(tick), bytes(words), _digest(words), chain
        return REPLACED, c


class Static:
    """A fixed archive built from orders (target labels in break order) under the single tick-0 root."""

    def __init__(self, spec: Sequence[Tuple[Any, ...]] = (), root: bool = True):
        self.a = FArchive()
        self.niches: Dict[int, Any] = {}
        self.x = 0
        self.root = self.add((), 0) if root else None
        for item in spec:
            self.add(*item)

    def add(self, order: Sequence[int], tick: int, res: str = "a") -> FCell:
        niche = (osel.ROOT_MASK, tuple(int(t) for t in order))
        self.x += 1
        v, c = self.a.keep((self.x, 0, res, osel.mask_of_order(niche), 0), tick, _words(f"{tuple(order)}|{tick}|{self.x}", tick))
        assert v == NEW
        self.niches[c.cid] = niche
        return c

    def selector(self, **kw: Any) -> osel.OrderSelector:
        return osel.OrderSelector(self.a, osel.OrderParams(**kw), niches=self.niches)


class ScriptRng:
    def __init__(self, vals: Sequence[float]):
        self.vals = list(vals)

    def random(self) -> float:
        return self.vals.pop(0)


def kept_child(a: FArchive, parent_niche: Any, breaks: Sequence[Sequence[int]], tick: int, x: int, res: str = "a") -> Tuple[str, FCell, Any]:
    """A reach at `tick` of a burst from a parent of niche `parent_niche` that broke `breaks` ([[tick, target], ...]), kept by the archive."""
    mask = osel.mask_of_order(parent_niche)
    for t, i in breaks:
        if int(t) <= tick:
            mask &= ~(1 << int(i))
    niche = rs.child_niche(parent_niche, mask, tick, breaks)
    v, c = a.keep((x, 0, res, mask, 0), tick, _words(f"child|{x}|{tick}|{breaks}", tick))
    return v, c, niche


def send(sel: osel.OrderSelector, c: Any, n: int, stream: str = "breadth") -> Dict[str, Any]:
    """A dispatch of cell c with a constructed draw (breadth unless said), with the fields the engine adds."""
    draw = {"stream": stream, "level": int(c.level), "group": rs.glabel(sel.group[int(c.cid)])}
    info = dict(sel.on_dispatch(c, draw, n))
    info.update(cid=int(c.cid), level=int(c.level))
    return info


def take(sel: osel.OrderSelector, info: Dict[str, Any], kept: Sequence[Any] = (), n: int = 0, row: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    kept = [k for k in kept if k[0] in (NEW, REPLACED)]
    return sel.on_ingest(info, row or {"outcome": "end", "advanced": bool(kept), "levels": {}}, kept, [], n)


def draw_once(sel: osel.OrderSelector, rng: Any, n: int) -> Tuple[Any, Dict[str, Any], Dict[str, Any]]:
    c, draw = sel.select(rng)
    info = dict(sel.on_dispatch(c, draw, n))
    info.update(cid=int(c.cid), level=int(c.level))
    return c, draw, info


class Game:
    """A fake burst oracle. A cell's state is its key (x, y, resource class, mask, floor) and tick. A burst plays `steps` steps of `step`
    ticks: x and y move on a small grid, and with probability p_break one live target breaks per step (never two on one tick). All of it
    is a keyed hash of the cell's prefix digest and the burst's iteration, so the game is a fixed function. `perm` relabels the targets:
    the relabelled game is the original one seen through the permutation (U12)."""

    def __init__(self, perm: Optional[Sequence[int]] = None, step: int = 8, steps: int = 6, p_break: float = 0.4, grid: int = 4):
        self.perm = list(perm) if perm is not None else list(range(osel.TARGETS_TOTAL))
        self.inv = [0] * osel.TARGETS_TOTAL
        for i, j in enumerate(self.perm):
            self.inv[j] = i
        self.step, self.steps, self.p_break, self.grid = step, steps, p_break, grid

    @staticmethod
    def pm(mask: int, perm: Sequence[int]) -> int:
        return sum(1 << perm[i] for i in range(osel.TARGETS_TOTAL) if (int(mask) >> i) & 1)

    def burst(self, c: Any, k: int) -> Tuple[List[Tuple[Any, ...]], List[List[int]]]:
        m = self.pm(c.key[3], self.inv)
        x, y, res, _m, fl = c.key
        t, words = int(c.tick), bytes(c.words)
        states, breaks = [], []
        for j in range(self.steps):
            b = hashlib.sha256(f"{c.digest}|{k}|{j}".encode()).digest()
            x, y = (x + b[0] % 3 - 1) % self.grid, (y + b[1] % 3 - 1) % self.grid
            if b[2] < 40:
                res = "ab"[b[3] % 2]
            words += b[4:4 + self.step]
            t += self.step
            live = [i for i in range(osel.TARGETS_TOTAL) if (m >> i) & 1]
            if live and b[12] < int(self.p_break * 256):
                tgt = live[b[13] % len(live)]
                m &= ~(1 << tgt)
                breaks.append([t, tgt])
            states.append((t, x, y, res, m, fl, words))
            if m == 0:
                break
        return ([(t, x, y, res, self.pm(m, self.perm), fl, w) for t, x, y, res, m, fl, w in states], [[t, self.perm[i]] for t, i in breaks])


def run_fake(sel: osel.OrderSelector, a: FArchive, game: Game, rng: Any, N: int) -> List[Tuple[Any, ...]]:
    """The engine's loop without the reorder window: select, send, play, keep under the pace rule, ingest."""
    seq: List[Tuple[Any, ...]] = []
    it: Counter = Counter()
    for n in range(N):
        pick = sel.select(rng)
        if pick is None:
            break
        c, draw = pick
        info = dict(sel.on_dispatch(c, draw, n))
        info.update(cid=int(c.cid), level=int(c.level))
        k = it[c.cid]
        it[c.cid] += 1
        states, breaks = game.burst(c, k)
        kept, claim = [], None
        for t, x, y, res, m, fl, w in states:
            lv = level_of(m)
            if lv >= osel.TARGETS_TOTAL:
                claim = {"completion_input_tick": t, "words_digest": _digest(w)}
                break
            if not sel.pace.keeps(lv, t):
                sel.pace.rejected.note(lv, t)
                continue
            v, cell = a.keep((x, y, res, m, fl), t, w)
            if v in (NEW, REPLACED):
                kept.append((v, cell, rs.child_niche(info["niche"], m, t, breaks)))
        row = {"outcome": "clear" if claim else "end", "claimed": claim, "advanced": bool(breaks), "levels": {}, "breaks_after_start": breaks}
        out = sel.on_ingest(info, row, kept, [], n)
        seq.append((n, int(c.cid), draw["stream"], int(draw["level"]), draw.get("rank"),
                    tuple((v, int(cell.cid), int(cell.tick)) for v, cell, _ in kept), tuple(out["milestones"]), bool(out["retired"])))
    return seq


# -- U2 (phase 1 part): replacement and group moves --------------------------------------------------------------------------------------


def unit_u2_group_move() -> Dict[str, Any]:
    s = Static([((0, 1), 100)])
    sel = s.selector()
    k = s.a.cells[1]
    g_old = sel.group[k.cid]
    niche = rs.child_niche(s.niches[s.root.cid], k.key[3], 60, [[20, 1], [40, 0]])
    v, c = s.a.keep(k.key, 60, _words("faster", 60))
    check(v == REPLACED and c.cid == k.cid and c.tick == 60, "a faster arrival at a known key replaces its representative")
    out = take(sel, send(sel, s.root, 0), [(v, c, niche)], 0)
    g_new = (2, k.key[3], "1023:1-0")
    check(sel.group[k.cid] == g_new and out["moves"] == 1, f"the cell moves to the faster arrival's order: {sel.group[k.cid]}")
    check(not sel.in_rotation(g_old) and sel.in_rotation(g_new) and out["rotation"] == {"order_joins": 1, "order_leaves": 1},
          f"the old order leaves the rotation, the new one joins: {out['rotation']}")
    return {"from": rs.glabel(g_old), "to": rs.glabel(g_new)}


# -- U3: root and niches -----------------------------------------------------------------------------------------------------------------


def unit_u3_root_and_niches() -> Dict[str, Any]:
    root = rs.seed_niche(osel.ROOT_MASK)
    check(root == (1023, ()) and rs.niche_label(root) == "1023:", "the root's niche is (1023, ())")
    s = Static([((4, 7), 90), ((9, 2), 95), ((1, 6), 80), ((4, 7, 0), 130)])
    sel = s.selector()
    check(sel.group[s.root.cid] == (0, 1023, "1023:") and sel.in_rotation((0, 1023, "1023:")), "the root's group, in the rotation")
    full = rs.child_niche(root, osel.mask_of_order((1023, (4, 7))), 60, [[30, 4], [50, 7]])
    check(full == (1023, (4, 7)), "a child's niche is the full order from tick 0")
    check(rs.child_niche(root, 1023 & ~(1 << 2) & ~(1 << 9), 60, [[50, 2], [30, 9]]) == (1023, (9, 2)),
          "a two-target burst is ordered by break tick")
    check(rs.child_niche(root, 1023 & ~(1 << 1) & ~(1 << 6), 60, [[40, 6], [40, 1]]) == (1023, (1, 6)),
          "two breaks on one tick are ordered by target label (section 2, run 3's rule)")
    check(rs.child_niche(full, osel.mask_of_order((1023, (4, 7, 0))), 90, [[70, 0]]) == (1023, (4, 7, 0)), "a grandchild extends the order")
    for c in s.a.cells:
        n_ = s.niches[c.cid]
        check(sel.group[c.cid] == (c.level, c.key[3], rs.niche_label(n_)) and osel.mask_of_order(n_) == c.key[3] and level_of(c.key[3]) == len(n_[1]),
              f"cell {c.cid}: group key = (L, mask, order), and the order determines the mask")
    # gap G5: same-tick breaks are counted per level reached (report-only)
    br = [[50, 3], [60, 4], [60, 7], [70, 1], [70, 2], [70, 9]]
    check(osel.same_tick_steps(2, br) == [(5, 2), (8, 3)] and osel.same_tick_steps(2, [[50, 3], [60, 4]]) == [],
          "same-tick steps: (level reached, targets on the tick)")
    twins = []
    for with_breaks in (True, False):
        t = Static([((0, 1), 40)])
        tsel = t.selector()
        row = {"outcome": "end", "advanced": True, "levels": {}, "breaks_after_start": br if with_breaks else []}
        take(tsel, send(tsel, t.a.cells[1], 0), [], 0, row)
        twins.append(tsel)
    check(twins[0].same_tick.summary() == {"8": {"ticks": 1, "targets": 3}, "5": {"ticks": 1, "targets": 2}} and twins[1].same_tick.summary() == {}
          and twins[0].same_tick.snapshot() == twins[0].same_tick.summary() and twins[0].same_tick.snapshot() == {},
          f"counted per level for the night and the period: {twins[0].same_tick.summary()}")
    check(all(dict(getattr(twins[0], f)) == dict(getattr(twins[1], f)) for f in ("set_count", "order_count", "rcount", "stale", "bcount"))
          and twins[0].retired == twins[1].retired, "the count enters no rule")
    return {"groups": sorted(rs.glabel(g) for g in sel.gall), "same_tick": twins[0].same_tick.summary()}


# -- U4: set, then order --------------------------------------------------------------------------------------------------------------------


def unit_u4_set_then_order() -> Dict[str, Any]:
    ten = [(6, 7, 8, 9), (6, 7, 9, 8), (6, 8, 7, 9), (6, 8, 9, 7), (6, 9, 7, 8), (6, 9, 8, 7), (7, 6, 8, 9), (7, 6, 9, 8), (7, 8, 6, 9), (7, 8, 9, 6)]
    spec = [((0, 1, 2, 3), 150), ((0, 1, 2, 3), 160)] + [(o, 170 + i) for i, o in enumerate(ten)] + [((4, 5, 6), 120 + i) for i in range(3)]
    spec += [((0, 1), 90), ((1, 0), 95), ((5,), 40)]
    s = Static(spec)
    sel = s.selector()
    check(sorted(sel.level_weights(list(sel.rotation_levels()))) == [1, 2, 3, 4], "levels 4 to 1 in the draw, level 0 outside it")
    rng = random.Random(11)
    streams: Counter = Counter()
    breadth_levels: Counter = Counter()
    for n in range(10000):
        bs, bo = dict(sel.set_count), dict(sel.order_count)
        c, draw, _info = draw_once(sel, rng, n)
        streams[draw["stream"]] += 1
        if draw["stream"] == "breadth":
            breadth_levels[draw["level"]] += 1
            check(dict(sel.set_count) == bs and dict(sel.order_count) == bo, f"draw {n}: a breadth draw changes no set or order count")
        else:
            g = sel.group[c.cid]
            st = osel.set_of(g)
            check(bs.get(st, 0) == min(bs.get(x, 0) for x in sel.rotation_levels()[draw["level"]]), f"draw {n}: the least-count set")
            check(bo.get(g, 0) == min(bo.get(x, 0) for x in sel.rot_by_set[st]), f"draw {n}: the least-count order of that set")
            check(sel.set_count[st] == bs.get(st, 0) + 1 and sel.order_count[g] == bo.get(g, 0) + 1, f"draw {n}: +1 to its set and order")
        if n % 50 == 0 or n == 9999:
            v = sel.within_one_violations()
            check(not v, f"draw {n}: within 1 at every level in the draw: {v}")
    root_set = (0, osel.ROOT_MASK)
    check(sel.set_count[root_set] == 0 and breadth_levels[0] > 0, f"level 0 (outside the draw): breadth only ({breadth_levels[0]} draws)")
    Q, B = (4, osel.mask_of_order((1023, (0, 1, 2, 3)))), (4, osel.mask_of_order((1023, ten[0])))
    ob = [sel.order_count[g] for g in sel.rot_by_set[B]]
    check(len(ob) == 10 and abs(sel.set_count[Q] - sel.set_count[B]) <= 1 and max(ob) - min(ob) <= 1,
          f"a set with one order and a set with ten get equal set counts ({sel.set_count[Q]} / {sel.set_count[B]}, orders {min(ob)} .. {max(ob)})")
    share = streams["breadth"] / 10000.0
    check(0.18 <= share <= 0.22 and streams["trigger"] == 0, f"breadth share {share}, no trigger stream")
    return {"streams": dict(streams), "set_counts_level4": [sel.set_count[Q], sel.set_count[B]], "orders_of_B": [min(ob), max(ob)]}


def unit_u4_ties() -> Dict[str, Any]:
    s = Static(root=False)
    y = s.add((0,), 100)                           # mask 1022, created first
    x = s.add((9,), 100)                           # mask 511: the lower mask value
    o83 = s.add((8, 3), 150)                       # "1023:8-3", created first
    o38 = s.add((3, 8), 150)                       # "1023:3-8": the lower label
    sel = s.selector(breadth_share=0.0)
    picks = []
    for lr in (0.1, 0.1, 0.9, 0.9):                # levels ascending (1, 2), weights 3/7 and 4/7: 0.1 draws level 1, 0.9 level 2
        c, draw = sel.select(ScriptRng([0.5, lr, 0.99, 0.0]))
        sel.on_dispatch(c, draw, len(picks))
        picks.append(c.cid)
    check(picks == [y.cid, x.cid, o83.cid, o38.cid], f"ties go to the earliest cell's id, not to the mask or the label: {picks}")
    s2 = Static(root=False)
    late_first = s2.add((2,), 120)
    early = s2.add((5,), 110)
    sel2 = s2.selector(breadth_share=0.0)
    c, _d = sel2.select(ScriptRng([0.5, 0.5, 0.99, 0.0]))
    check(c.cid == early.cid != late_first.cid, "on equal counts the earliest active cell's tick comes before the cell id")
    return {"picks": picks}


def unit_u4_cell_draw_is_run3s() -> Dict[str, Any]:
    """Section 3.4: inside an order, the cell draw (anchors, rank draw, staleness) is run 3's, unchanged."""
    s = Static([((0, 1, 2), 100 + 7 * i, "ab"[i % 2]) for i in range(12)], root=False)
    p = osel.OrderParams(breadth_share=0.0)
    d = osel.OrderSelector(s.a, p, niches=s.niches)
    r3 = rs.Run3Selector(s.a, osel.run3_view(p), niches=s.niches, history={}, cid_dispatches={}, best_claim=None)
    src = random.Random(7)
    streams: Counter = Counter()
    for n in range(250):
        u, lr, u3, rr = (src.random() for _ in range(4))
        cd, dd = d.select(ScriptRng([u, lr, u3, rr]))
        c3, d3 = r3.select(ScriptRng([u, lr, 0.0, u3, rr]))     # run 3 draws a group in between (one group here)
        check(cd.cid == c3.cid and dd["stream"] == d3["stream"] and dd.get("rank") == d3.get("rank"),
              f"draw {n}: D {cd.cid} {dd['stream']} vs run 3 {c3.cid} {d3['stream']}")
        streams[dd["stream"]] += 1
        infos = []
        for sel, c, dr in ((d, cd, dd), (r3, c3, d3)):
            info = dict(sel.on_dispatch(c, dr, n))
            info.update(cid=int(c.cid), level=int(c.level))
            infos.append(info)
        if n % 3 == 2:
            for sel, info in zip((d, r3), infos):
                sel.on_ingest(info, {"outcome": "end", "advanced": False, "levels": {}}, [], [], n)
    check(dict(d.stale) == dict(r3.stale) and {k: v["w"] for k, v in d.anc.items()} == {k: v["w"] for k, v in r3.anc.items()},
          "the same staleness and anchor weights after 250 draws")
    check(streams["anchor"] > 0 and streams["rank"] > 0, f"both anchor and rank draws were compared: {dict(streams)}")
    return {"streams": dict(streams)}


# -- U5: newcomers and returners ----------------------------------------------------------------------------------------------------------


def unit_u5_newcomers() -> Dict[str, Any]:
    s = Static([((0, 1, 2), 120), ((1, 0, 2), 125), ((3, 4, 5), 130)])
    A, B, C = s.a.cells[1:4]
    rootn = s.niches[s.root.cid]
    sel = s.selector(breadth_share=0.0, retire_after=3)
    rng = random.Random(5)
    T, U = (3, A.key[3]), (3, C.key[3])
    n = 0
    while sel.set_count[T] + sel.set_count[U] < 12:
        draw_once(sel, rng, n)
        n += 1
    m_sets = min(sel.set_count[T], sel.set_count[U])
    m_orders = min(sel.order_count[g] for g in sel.rot_by_set[T])
    k_set = kept_child(s.a, rootn, [[30, 6], [50, 7], [70, 8]], 80, x=100)
    k_ord = kept_child(s.a, rootn, [[30, 2], [50, 1], [70, 0]], 85, x=101)
    out = take(sel, send(sel, s.root, n), [k_set, k_ord], n)
    n += 1
    V, g_new = (3, k_set[1].key[3]), sel.group[k_ord[1].cid]
    check(sel.set_count[V] == m_sets and sel.order_count[g_new] == m_orders and out["rotation"] == {"order_joins": 2, "set_joins": 1},
          f"a set and an order created mid-run join at their siblings' minimum ({sel.set_count[V]} / {m_sets}, {sel.order_count[g_new]} / {m_orders})")
    k_deep = kept_child(s.a, rootn, [[20, 0], [40, 1], [60, 2], [80, 9]], 90, x=102)
    take(sel, send(sel, s.root, n), [k_deep], n)
    n += 1
    W4 = (4, k_deep[1].key[3])
    check(sel.set_count[W4] == 0 and sel.order_count[sel.group[k_deep[1].cid]] == 0, "a newcomer where there never was a sibling starts at 0")
    check(not sel.within_one_violations(), f"within 1 after the newcomers: {sel.within_one_violations()}")
    # C, the only cell of U's only order, retires after R = 3 dispatches: U leaves the rotation and keeps its count
    gU = sel.group[C.cid]
    cU, oU = sel.set_count[U], sel.order_count[gU]
    for _ in range(3):
        take(sel, send(sel, C, n), [], n)
        n += 1
    check(C.cid in sel.retired and not sel.in_rotation(gU) and U not in sel.rot_by_level[3] and sel.set_count[U] == cU,
          "a unit whose cells all retired leaves the rotation and keeps its count")
    while min(sel.set_count[T], sel.set_count[V]) < cU + 3:
        draw_once(sel, rng, n)
        n += 1
    expect = max(cU, min(sel.set_count[T], sel.set_count[V]))
    k_back = kept_child(s.a, rootn, [[30, 3], [50, 4], [70, 5]], 95, x=103)
    out = take(sel, send(sel, s.root, n), [k_back], n)
    n += 1
    check(sel.in_rotation(gU) and sel.set_count[U] == expect > cU and sel.order_count[gU] == oU and out["rotation"] == {"order_returns": 1, "set_returns": 1},
          f"returning resumes at max(its count, the siblings' minimum): set {sel.set_count[U]} (was {cU}), order {sel.order_count[gU]} (no sibling: its own {oU})")
    # an order above its siblings' minimum resumes at its own count
    gA = sel.group[A.cid]
    while True:
        c, draw, _i = draw_once(sel, rng, n)
        n += 1
        others = [sel.order_count[g] for g in sel.rot_by_set[T] if g != gA]
        if draw["stream"] != "breadth" and sel.group[c.cid] == gA and sel.order_count[gA] > min(others):
            break
    own = sel.order_count[gA]
    for _ in range(3):
        take(sel, send(sel, A, n), [], n)
        n += 1
    check(not sel.in_rotation(gA), "A's order left the rotation (its only cell retired)")
    k_a = kept_child(s.a, rootn, [[30, 0], [50, 1], [70, 2]], 99, x=104)
    m_now = min(sel.order_count[g] for g in sel.rot_by_set[T])
    take(sel, send(sel, s.root, n), [k_a], n)
    check(sel.in_rotation(gA) and sel.order_count[gA] == max(own, m_now) == own, f"resumes at its own count {own} above the minimum {m_now}")
    # gap G1: a level that empties and refills. S is level 3's only set; it retires; a newcomer N joins with no sibling in the rotation
    g1 = Static([((0, 1, 2), 120)])
    Sc = g1.a.cells[1]
    gsel = g1.selector(breadth_share=0.0, retire_after=2)
    S = (3, Sc.key[3])
    m = 0
    while gsel.set_count[S] < 30:
        draw_once(gsel, rng, m)
        m += 1
    for _ in range(2):
        take(gsel, send(gsel, Sc, m), [], m)
        m += 1
    g1root = g1.niches[g1.root.cid]
    kN = kept_child(g1.a, g1root, [[30, 6], [50, 7], [70, 8]], 80, x=100)
    take(gsel, send(gsel, g1.root, m), [kN], m)
    m += 1
    N = (3, kN[1].key[3])
    check(S not in gsel.rot_by_level[3] and gsel.set_count[N] == gsel.set_count[S] == 30,
          f"G1: with no sibling in the rotation, the newcomer starts at the highest count any sibling ever had ({gsel.set_count[N]})")
    kS = kept_child(g1.a, g1root, [[30, 0], [50, 1], [70, 2]], 85, x=101)
    take(gsel, send(gsel, g1.root, m), [kS], m)
    m += 1
    check(S in gsel.rot_by_level[3] and gsel.set_count[S] == 30 and not gsel.within_one_violations(), "G1: S returns at 30; within 1 holds")
    picked: Counter = Counter()
    while sum(picked.values()) < 20:
        c, d, _i = draw_once(gsel, rng, m)
        m += 1
        if d["level"] == 3:
            picked[osel.set_of(gsel.group[c.cid])] += 1
            check(not gsel.within_one_violations(), f"G1: within 1 at every draw: {gsel.within_one_violations()}")
    check(picked[S] == picked[N] == 10, f"G1: no catch-up burst, the two sets alternate: {dict(picked)}")
    return {"set_counts": {osel.slabel(k): int(v) for k, v in sorted(sel.set_count.items())}, "dstat": dict(sel.dstat),
            "g1_refill": {osel.slabel(k): int(v) for k, v in sorted(gsel.set_count.items())}}


# -- U6: level weights --------------------------------------------------------------------------------------------------------------------


def unit_u6_level_weights() -> Dict[str, Any]:
    W = (0.4, 0.3, 0.2, 0.1)
    check(osel.level_draw_weights([7, 5, 4, 2, 1], W) == {7: 0.4, 5: 0.3, 4: 0.2, 2: 0.1}, "by rank among the levels present (gap D)")
    two = osel.level_draw_weights([3, 1], W)
    check(set(two) == {3, 1} and abs(two[3] - 4 / 7) < 1e-12 and abs(two[1] - 3 / 7) < 1e-12, f"renormalised over fewer levels: {two}")
    check(osel.level_draw_weights([], W) == {}, "no level, no weight")
    s = Static([(tuple(range(7)), 330), (tuple(range(5)), 300), ((5, 6, 7, 8), 250), ((9, 8), 150), ((3,), 100)], root=False)
    sel = s.selector(breadth_share=0.0, retire_after=1)
    lw = sel.level_weights(list(sel.rotation_levels()))
    check(lw == {7: 0.4, 5: 0.3, 4: 0.2, 2: 0.1}, f"levels 7, 5, 4, 2 in the draw, level 1 not: {lw}")
    rng = random.Random(3)
    freq: Counter = Counter()
    for _ in range(20000):
        _c, d = sel.select(rng)
        freq[d["level"]] += 1
    check(all(abs(freq[lv] / 20000.0 - w) < 0.015 for lv, w in lw.items()) and freq[1] == 0, f"the level draw follows the weights: {dict(freq)}")
    c5 = next(c for c in s.a.cells if c.level == 5)
    take(sel, send(sel, c5, 0), [], 0)
    lw2 = sel.level_weights(list(sel.rotation_levels()))
    check(c5.cid in sel.retired and lw2 == {7: 0.4, 4: 0.3, 2: 0.2, 1: 0.1}, f"a level with only retired cells is skipped: {lw2}")
    return {"weights": {str(k): v for k, v in lw2.items()}, "freq": {str(k): v for k, v in sorted(freq.items())}}


# -- U7: retirement -------------------------------------------------------------------------------------------------------------------------


def unit_u7_retirement() -> Dict[str, Any]:
    s = Static([((0, 1), 100), ((2, 3), 110), ((4, 5), 120), ((6, 7), 130)])
    X, Y, Z, W = s.a.cells[1:5]
    sel = s.selector()
    check(sel.R == 300, "R = 300")
    cnt = [0]

    def burst(c: Any, kept: Sequence[Any] = (), row: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        out = take(sel, send(sel, c, cnt[0]), kept, cnt[0], row)
        cnt[0] += 1
        return out

    for _ in range(299):
        burst(X)
    check(X.cid not in sel.retired and sel.is_active(X.cid), "not retired at 299 dispatches")
    out = burst(X)
    gX = sel.group[X.cid]
    check(out["retired"] and X.cid in sel.retired, "retired at exactly 300 dispatches none of which kept a deeper cell")
    check(X.cid in sel.breadth_pool() and s.a.cells[X.cid] is X and X.cid not in sel.members(gX), "it stays in the archive and in breadth")
    check(not sel.in_rotation(gX) and osel.set_of(gX) not in sel.rot_by_level.get(2, ()), "its order and set (no other cell) leave the rotation")
    burst(Y, [kept_child(s.a, sel.niche[Y.cid], [[140, 9]], 150, x=200)])
    for _ in range(400):
        burst(Y)
    check(Y.cid not in sel.retired and sel.is_active(Y.cid), "a cell one of whose dispatches kept a deeper cell never retires")
    burst(Z, [kept_child(s.a, sel.niche[Z.cid], [], 160, x=201)])
    for _ in range(298):
        burst(Z)
    check(Z.cid not in sel.retired, "a kept cell at the same level does not count (299 dispatches)")
    check(burst(Z)["retired"], "... and Z retires at 300")
    behind = {"outcome": "end", "advanced": True, "levels": {"3": 400}}
    for _ in range(299):
        burst(W, [], behind)
    check(W.cid not in sel.retired and burst(W, [], behind)["retired"], "a cell whose only break is behind the line (nothing kept) retires at exactly 300")
    # gap B: a faster representative restarts the count and the status, and a retired cell becomes active again
    rootn = s.niches[s.root.cid]
    v, c = s.a.keep(X.key, 90, _words("fasterX", 90))
    take(sel, send(sel, s.root, cnt[0]), [(v, c, rs.child_niche(rootn, X.key[3], 90, [[30, 0], [60, 1]]))], cnt[0])
    cnt[0] += 1
    check(v == REPLACED and X.cid not in sel.retired and sel.rcount[X.cid] == 0 and sel.in_rotation(gX), "B: a replaced retired cell is active again, count 0")
    for _ in range(299):
        burst(X)
    check(X.cid not in sel.retired and burst(X)["retired"], "B: the new representative retires after its own 300")
    v, c = s.a.keep(Y.key, 105, _words("fasterY", 105))
    take(sel, send(sel, s.root, cnt[0]), [(v, c, rs.child_niche(rootn, Y.key[3], 105, [[30, 2], [60, 3]]))], cnt[0])
    cnt[0] += 1
    check(v == REPLACED and Y.cid not in sel.deeper, "B: the kept-a-deeper-cell status restarts too")
    for _ in range(299):
        burst(Y)
    check(Y.cid not in sel.retired and burst(Y)["retired"], "B: so Y retires at 300 after the replacement")
    # gap C: a retired cell whose breadth dispatch keeps a deeper cell is active again and never retires
    out = burst(X, [kept_child(s.a, sel.niche[X.cid], [[100, 8]], 110, x=202)])
    check(out["active_again"] and sel.is_active(X.cid) and sel.in_rotation(sel.group[X.cid]), "C: active again after a breadth dispatch kept a deeper cell")
    for _ in range(400):
        burst(X)
    check(X.cid not in sel.retired, "C: and it never retires")
    return {"dispatches": cnt[0], "dstat": dict(sel.dstat)}


def unit_u7_stale_clear_fallback() -> Dict[str, Any]:
    # gap G3: a dispatch ingested after its cell got a faster representative counts for neither, even when it kept a deeper cell
    s = Static([((0, 1), 100)])
    X = s.a.cells[1]
    sel = s.selector()
    rootn = s.niches[s.root.cid]
    stale_info = send(sel, X, 0)
    v, c = s.a.keep(X.key, 80, _words("fasterX", 80))
    take(sel, send(sel, s.root, 1), [(v, c, rs.child_niche(rootn, X.key[3], 80, [[30, 0], [60, 1]]))], 1)
    deep = kept_child(s.a, (1023, (0, 1)), [[110, 5]], 120, x=50)
    out = take(sel, stale_info, [deep], 2)
    check(v == REPLACED and out["stale"] and sel.rcount[X.cid] == 0 and X.cid not in sel.deeper and sel.dstat["stale_dispatches"] == 1
          and deep[1].cid in sel.group, "G3: counted for neither representative; what it kept is still kept")
    for i in range(299):
        take(sel, send(sel, X, 3 + i), [], 3 + i)
    check(X.cid not in sel.retired and take(sel, send(sel, X, 400), [], 400)["retired"], "G3: so the new representative retires at its own 300")
    # gap G4: a clear at or before 600 counts as keeping a deeper cell
    clear = lambda t: {"outcome": "clear", "claimed": {"completion_input_tick": t, "words_digest": "w"}, "advanced": True, "levels": {}}
    results = {}
    for cit in (600, 601):
        t = Static([(tuple(range(9)), 500)])
        N9 = t.a.cells[1]
        tsel = t.selector()
        take(tsel, send(tsel, N9, 0), [], 0, clear(cit))
        for i in range(298):
            take(tsel, send(tsel, N9, 1 + i), [], 1 + i)
        last = take(tsel, send(tsel, N9, 299), [], 299)
        results[cit] = (N9.cid in tsel.deeper, last["retired"])
    check(results[600] == (True, False) and results[601] == (False, True),
          f"G4: a level-9 cell whose dispatch cleared at 600 never retires; at 601 it retires at 300: {results}")
    # gap G2: with every eligible cell retired, an exploitation draw falls back to a breadth draw, recorded
    f = Static([((0, 1), 100)], root=False)
    C = f.a.cells[0]
    fsel = f.selector(retire_after=1, breadth_share=0.0)
    take(fsel, send(fsel, C, 0), [], 0)
    c2, d2 = fsel.select(random.Random(1))
    check(C.cid in fsel.retired and not fsel.rotation_levels() and c2.cid == C.cid and d2["stream"] == "breadth" and d2.get("fallback_breadth")
          and fsel.dstat["fallback_breadth"] == 1, f"G2: breadth fallback {d2}")
    fsel.on_dispatch(c2, d2, 1)
    check(fsel.set_count[osel.set_of(fsel.group[C.cid])] == 0, "G2: the fallback is a breadth draw and changes no budget count")
    return {"g4": {str(k): list(v) for k, v in results.items()}, "fallback": d2}


# -- U8: milestones -----------------------------------------------------------------------------------------------------------------------


def unit_u8_milestones() -> Dict[str, Any]:
    pace = osel.Pace(osel.OrderParams())

    def fc(level: int, tick: int, cid: int = 1, high: bool = False) -> FCell:
        mask = (osel.ROOT_MASK >> level) if high else ((osel.ROOT_MASK << level) & osel.ROOT_MASK)
        assert level_of(mask) == level
        return FCell(cid, (0, 0, "a", mask, 0), level, tick, b"", f"d{cid}", b"\x01\x02")

    for name, L in osel.MILESTONES:
        line = pace.line(L)
        for high in (False, True):
            ms = osel.Milestones(pace)
            check(ms.observe_kept(fc(L, line + 1, high=high), 5) == [], f"{name}: not at line({L}) + 1 = {line + 1}")
            check(ms.observe_kept(fc(L, line, 7, high=high), 6) == [name], f"{name}: met at line({L}) = {line}, in either mask")
    ms = osel.Milestones(pace)
    check(ms.observe_kept(fc(7, 400), 3) == ["M1", "M2"], "gap E: a level-7 arrival at 400 with no level-6 cell meets M1 and M2")
    check(ms.observe_kept(fc(6, 300, cid=9), 4) == [] and ms.met["M1"]["cid"] == 1, "recorded once, at the first occurrence")
    check(ms.met["M1"] == {"milestone": "M1", "level": 6, "line": 408, "arrival_level": 7, "tick": 400, "n": 3, "cid": 1, "digest": "d1", "chain": "0102"},
          f"with dispatch, cell and lineage digest: {ms.met['M1']}")
    ms = osel.Milestones(pace)
    check(not ms.observe_clear(601, 1, 2, {}) and ms.observe_clear(600, 2, 3, {"words_digest": "w", "final_chain": "ab"})
          and ms.met[osel.CLEAR_LINE]["completion_input_tick"] == 600 and not ms.observe_clear(500, 3, 4, {}), "the clear line: 600, not 601; once")
    s = Static([((0, 1, 2, 3, 4), 300)])
    sel = s.selector()
    c5 = s.a.cells[1]
    kd = kept_child(s.a, sel.niche[c5.cid], [[400, 9]], 408, x=300)
    out = take(sel, send(sel, c5, 0), [kd], 0)
    check(out["milestones"] == ["M1"] and sel.milestones.met["M1"]["cid"] == kd[1].cid, "through the selector: a kept level-6 arrival at 408 is M1")
    out = take(sel, send(sel, s.root, 1), [], 1, {"outcome": "clear", "claimed": {"completion_input_tick": 590, "words_digest": "x"}, "levels": {}})
    check(out["milestones"] == [osel.CLEAR_LINE] and [r["milestone"] for r in sel.milestones.records()] == ["M1", osel.CLEAR_LINE],
          "through the selector: a clear at 590 is the clear line")
    return {"records": sel.milestones.records()}


# -- U12: relabelling invariance ------------------------------------------------------------------------------------------------------------


def _plabel(label: str, perm: Sequence[int]) -> str:
    seed, rest = label.split(":")
    return seed + ":" + "-".join(str(perm[int(t)]) for t in rest.split("-") if t != "")


def unit_u12_relabelling() -> Dict[str, Any]:
    perm = [3, 7, 0, 9, 1, 5, 8, 2, 6, 4]
    runs = []
    for pm in (None, perm):
        s = Static()
        sel = s.selector(retire_after=2)              # small R and a sparser game: retirements, leaves and returns happen
        runs.append((s, sel, run_fake(sel, s.a, Game(pm, p_break=0.2), random.Random(20261112), 3000)))
    (s0, a, q0), (_s1, b, q1) = runs
    check(len(q0) == 3000 and q0 == q1, "the same dispatch sequence (cell, stream, level, rank, kept cells, milestones, retirements) with the labels permuted")
    check({(lv, Game.pm(m, perm)): v for (lv, m), v in a.set_count.items()} == dict(b.set_count), "the same set counts, relabelled")
    check({(lv, Game.pm(m, perm), _plabel(lb, perm)): v for (lv, m, lb), v in a.order_count.items()} == dict(b.order_count),
          "the same order counts, relabelled")
    check(a.milestones.records() == b.milestones.records() and a.retired == b.retired and a.pace.rejected.summary() == b.pace.rejected.summary(),
          "the same milestones, retirements and rejected reaches")
    check(dict(a.stale) == dict(b.stale) and dict(a.bcount) == dict(b.bcount), "the same staleness and breadth counts")
    check(not a.same_tick.summary() and not b.same_tick.summary(), "U12 assumes no same-tick breaks (gap G5): the fake game breaks one target per tick")
    streams = Counter(x[2] for x in q0)
    per_level = a.level_readout()
    many = max(v["sets"] for v in per_level.values())
    check(streams["breadth"] and streams["rank"] and streams["anchor"] and a.dstat["retired"] > 0 and a.milestones.met and many >= 3,
          f"a non-trivial run: streams {dict(streams)}, retired {a.dstat['retired']}, milestones {sorted(a.milestones.met)}, sets at one level {many}")
    return {"streams": dict(streams), "cells": len(s0.a.cells), "retired": a.dstat["retired"], "milestones": sorted(a.milestones.met),
            "deepest": max(c.level for c in s0.a.cells), "rotation": {k: int(v) for k, v in sorted(a.dstat.items())}}



# -- phase 2, pure: the root comparison and F3 with the pace filter -----------------------------------------------------------------------


def unit_root_differences() -> Dict[str, Any]:
    a = {"ok": True, "obs": [1, 2, 3] + [0] * (len(O.mcell.OBS_FIELDS) - 3), "digest": "d", "chain": "c", "lines": 4, "key": [0, 0, "a", 1023, 0], "mask": 1023}
    b = dict(a)
    check(O.root_differences([a, b]) == [], "two equal tick-0 reads")
    host = list(a["obs"])
    host[O.mcell.HOST_FRAME] = 99
    check(O.root_differences([a, dict(b, obs=host)]) == [], "host_frame is not compared")
    check(O.root_differences([a, dict(b, digest="e")]) == ["digest"] and O.root_differences([a, dict(b, mask=1022, key=None)]) == ["key", "mask"],
          "the digest, the key and the mask are compared")
    check(O.root_differences([a, {"ok": False, "kind": "died"}])[0].startswith("a tick-0 read failed") and O.root_differences([a])[0].startswith("a tick-0 read"),
          "a failed or missing read is a difference")
    return {"fields": len(a["obs"])}


# -- U14: D's process-tree sampler (owner 2026-11-13, fix A; session log 20.5) -----------------------------------------------------------


def _bare_walk(root: int, parent_of: Mapping[int, int]) -> List[int]:
    """rl/frs_machine.tree_snapshot's walk (lines 127-137 at 73cbde95): descendants by parent PID alone."""
    children: Dict[int, List[int]] = {}
    for pid, ppid in parent_of.items():
        if pid != ppid:
            children.setdefault(ppid, []).append(pid)
    tree, stack = [], [root]
    while stack:
        p = stack.pop()
        if p in tree:
            continue
        tree.append(p)
        stack.extend(children.get(p, []))
    return tree


def unit_u14_tree_sampler() -> Dict[str, Any]:
    # The pilot's machine in miniature: the run (python 18288, five workers, a game and a standby each), one game given PID 912, the
    # dead parent of csrss and wininit since boot; services and svchosts under wininit; explorer an orphan of the dead 7456.
    parent_of: Dict[int, int] = {4: 0, 608: 912, 1096: 912, 700: 1096, 7496: 7456, 17800: 900, 18288: 17800}
    created: Dict[int, Optional[int]] = {4: 0, 608: 10, 1096: 11, 700: 12, 7496: 900, 900: 5000, 17800: 6000, 18288: 6001}
    for i in range(30):
        parent_of[710 + 4 * i], created[710 + 4 * i] = 700, 13 + i                 # svchosts
    parent_of[900] = 710                                                            # WmiPrvSE, the launcher's parent
    run = [18288]
    for w in range(5):
        wp = 20000 + 4 * w
        parent_of[wp], created[wp] = 18288, 6010 + w
        run.append(wp)
        for j, gp in enumerate((21000 + 8 * w, 21004 + 8 * w)):
            parent_of[gp], created[gp] = wp, 7000 + 10 * w + j
            run.append(gp)
    bare_before = set(_bare_walk(18288, parent_of))
    guarded_before = set(O.guarded_tree(18288, parent_of, created.get))
    check(bare_before == guarded_before == set(run), f"a normal tree: both walks count exactly the run ({len(run)} processes)")
    # A worker's new game is given PID 912 (reuse): the bare walk adopts csrss, wininit and everything under them.
    parent_of[912], created[912] = 20008, 9000
    bare = set(_bare_walk(18288, parent_of))
    guarded = set(O.guarded_tree(18288, parent_of, created.get))
    adopted = bare - set(run) - {912}
    check({608, 1096, 700} <= adopted and 900 in adopted and 18288 in bare, f"the bare walk adopts {len(adopted)} system processes")
    check(guarded == set(run) | {912}, "D's walk keeps the run and the reused-PID game, and adopts none of the orphans")
    check(set(O.guarded_tree(912, parent_of, created.get)) == {912}, "from the reused PID itself: csrss and wininit are older, not children")
    check(set(O.guarded_tree(912, {608: 912, 1096: 912}, lambda p: None)) == {912}, "a root whose creation time is unknown adopts nothing")
    # Edges: a child created at its parent's instant counts; a child whose time cannot be read is not counted, nor its subtree; a cycle ends.
    check(set(O.guarded_tree(1, {2: 1, 3: 2}, {1: 5, 2: 5, 3: 6}.get)) == {1, 2, 3}, "created at the parent's instant: a child")
    check(set(O.guarded_tree(1, {2: 1, 3: 2}, {1: 5, 2: None, 3: 6}.get)) == {1}, "an unreadable child and its subtree are not counted")
    check(set(O.guarded_tree(1, {1: 2, 2: 1}, {1: 5, 2: 6}.get)) == {1, 2}, "a parent-PID cycle terminates")
    # The wiring at the sampler (order_search.py, the open): run 3's real snapshot is replaced; a test's injected snapshot is kept.
    fake = lambda: None  # noqa: E731
    check(O.sampler_snapshot(O.fm.tree_snapshot) is O.d_tree_snapshot and O.sampler_snapshot(fake) is fake, "sampler_snapshot wiring")
    live = O.d_tree_snapshot()
    if os.name == "nt":
        ref = O.fm.tree_snapshot()
        check(live is not None and ref is not None and set(live) == set(ref) and live["processes"] >= 1,
              f"the live record has run 3's keys: {sorted(live or {})}")
    return {"run": len(run), "bare_with_reuse": len(bare), "guarded_with_reuse": len(guarded), "live_processes": (live or {}).get("processes")}


def unit_f3_pace_filter() -> Dict[str, Any]:
    night = object.__new__(O.OrderNight)                 # only the attributes continuation_asof reads
    night.pace = osel.Pace(osel.OrderParams())
    night._asof = det.AsOfIndex()
    six = (1, 1, "a", (osel.ROOT_MASK << 6) & osel.ROOT_MASK, 0)
    three = (2, 1, "a", (osel.ROOT_MASK << 3) & osel.ROOT_MASK, 0)
    night._asof.record(three, 0, 250, new=True)
    d = O.OrderNight.continuation_asof(night, [[409, list(six)]], 0)
    check(not d["go"] and d["outside_line"] == 1 and d["reaches"] == 0, f"a new key behind the line does not continue the burst: {d}")
    d = O.OrderNight.continuation_asof(night, [[408, list(six)]], 0)
    check(d["go"] and d["new"] == 1 and d["outside_line"] == 0, f"a new key on the line continues it: {d}")
    d = O.OrderNight.continuation_asof(night, [[240, list(three)], [265, list(six)]], 0)
    check(d["go"] and d["shorter"] == 1 and d["max_gain"] == 10, f"a faster arrival inside the line continues it: {d}")
    d = O.OrderNight.continuation_asof(night, [[265, list(three)]], 0)
    check(not d["go"] and d["outside_line"] == 1, f"level 3 at 265 is behind line(3) = 264: {d}")
    return {"line6": night.pace.line(6)}


# -- fake-game end to end (run 3's fake game; zero native ticks) -----------------------------------------------------------------------------

E_FLAGS = {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1", "SSB64_RL_SPATIAL": "1", "FAKEGAME_WORLD": "easy", "FAKEGAME_BOOT_S": "0.1",
           "FAKEGAME_IDLE_S": "60", "FAKEGAME_STEP_JITTER_S": "0.002"}
E_ENGINE = {"max_segments": 3, "max_dispatches": 160, "rng_seed": 7, "check_slots": 1, "summary_every_s": 0.0, "summary_every_dispatches": 40}
CHILD = ("import json, sys\nfrom pathlib import Path\nsys.path.insert(0, %r); sys.path.insert(0, %r)\nimport frs_guard as g\n"
         "g.LabGuard.install(Path(%r))\nimport order_search_tests as T\nprint(json.dumps(T.%s(json.loads(%r)), default=str))\n")


def run_child(fn: str, lab: Path, args: Mapping[str, Any], timeout: float = 1800.0) -> Dict[str, Any]:
    code = CHILD % (str(RL), str(HERE), str(lab), fn, json.dumps(args))
    r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=timeout, cwd=str(lab))
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise AssertionError(f"{fn}: child failed: {(r.stderr or r.stdout)[-3000:]}")


def write_fake_frontier(lab: Path, best: int) -> Path:
    """A frontier (run 3) folder holding only what D reads: its plan and summary contracts, a clean status and integrity, the best."""
    d = lab / "crossing_fake_run3"
    (d / "run").mkdir(parents=True, exist_ok=True)
    (d / "plan.json").write_text(json.dumps({"contract": O.C.RUN3_CONTRACT, "mode": "lab"}), encoding="utf-8")
    (d / "run" / "summary.json").write_text(json.dumps({"contract": O.C.RUN3_CONTRACT, "mode": "lab", "status": "DISPATCH_CAP", "utc_end": "2026-11-12T00:00:00Z",
                                                        "integrity": {"reference_ok": True, "run3_code_digest": "x", "run3_code_digest_end": "x", "prefix_mismatches": 0,
                                                                      "battleship_left": []},
                                                        "run3": {"claims_frozen": None, "best": {"completion_input_tick": int(best), "completion_time_passed": int(best) - 1,
                                                                                                 "chain": "00", "words_digest": "w", "n": 1}}}), encoding="utf-8")
    return d


class _RootUnequal(O.OrderNight):
    """E2: an injected inequality between the two tick-0 reads."""

    def root_reads(self) -> List[Dict[str, Any]]:
        reads = super().root_reads()
        if len(reads) == 2 and reads[1].get("ok"):
            reads[1] = dict(reads[1], digest="0" * 64)
        return reads


class _MilestoneAltered(O.OrderNight):
    """E4: M1's recorded chain is altered before its verification, so both replays disagree with the record."""

    def verify_milestone(self, row: Mapping[str, Any]) -> Dict[str, Any]:
        if row["milestone"] == "M1":
            row = dict(row, chain="f" * 64)
        return super().verify_milestone(row)


class _CodeChanged(O.OrderNight):
    """T-M2: a file of D's manifest 'changes' during the run (its recorded hash is altered before the close's comparison)."""

    def write_summary(self) -> Dict[str, Any]:
        if self.order_code and "order_code_digest_end" not in self.integrity:
            k = sorted(self.order_code)[0]
            self.order_code = dict(self.order_code, **{k: "0" * 64})
        return super().write_summary()


ENGINES = {"night": O.OrderNight, "root_unequal": _RootUnequal, "milestone_altered": _MilestoneAltered, "code_changed": _CodeChanged}


def order_child(a: Mapping[str, Any]) -> Dict[str, Any]:
    """In a child with the lab guard installed: D's `plan` (in process), then a night on the fake game (or the stub backend)."""
    import crossing_search as cs
    import frs_guard as g
    import frs_machine as fm
    import frs_run as fr
    import frs_verify as fv
    import m8_rd_stub as stub
    import run3_export as rx
    import run3_search_tests as r3t

    lab, out, frontier = Path(a["lab"]), Path(a["out"]), Path(a["frontier"])
    run_dir = out / "run"
    dp = osel.OrderParams(**(a.get("order") or {}))
    ep = O.engine_params(dp, **a["engine"])
    opened: List[str] = []
    if a.get("audit"):
        def hook(ev: str, args: Any) -> None:
            if ev == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
                opened.append(os.fsdecode(args[0]))
        sys.addaudithook(hook)
    plan = O.plan_and_write(lab, frontier, out, dp, ep)
    world = a.get("world", "easy")
    flags = dict(E_FLAGS, FAKEGAME_WORLD=world)
    os.environ["FAKEGAME_WORLD"] = world          # this child only: the text replay passes the environment (minus SSB64_*) to the fake game
    text = None
    if a.get("stub"):
        inject = dict(a.get("inject") or {})

        def spec(rank: int) -> Dict[str, Any]:
            return {"rank": rank, "backend": "m8_rd_stub:StubBackend", "world": world, "inject": inject, "failure_dir": str(run_dir / "failures"), "guard": g.LabGuard.spec()}

        replay = lambda words, label, slot: stub.replay_trace(world, words, label)  # noqa: E731
        backend = "stub"
    else:
        fk = {"exe": a["exe"], "frozen": a["frozen"]}
        frozen = {"frozen_sha256": a["frozen"], "exe_copy_sha256": a["exe_copy"]}

        def spec(rank: int) -> Dict[str, Any]:
            return dict(r3t.worker_spec(lab, fk, rank, int(a["port_base"]), run_dir / "failures", flags), guard=g.LabGuard.spec(), run3_selfcheck=True)

        replay = fv.make_real_replay(Path(a["exe"]), lab / f"replays_{out.name}", flags, frozen)
        backend = "real"
        if a.get("text_replay"):
            text = rx.make_text_replay(Path(a["exe"]), run_dir / "text_replays")
    caps = dict(fm.CAPS_MB, main_private=1e9)
    soft = dict(fm.soft_budget(caps), main_private=float(a["soft_main_mb"])) if a.get("soft_main_mb") else None
    env = fr.LabEnv(worker_spec=spec, replay=replay, analyse=stub.analyse, readiness=lambda: {"ok": True, "problems": []}, battleship_pids=lambda: [],
                    snapshot=fm.tree_snapshot, import_problems=lambda: [], wait_no_battleship=lambda t: [], code_manifest=fr.code_manifest, backend=backend,
                    sample_s=0.25, row_every_s=0.5, caps=caps, soft=soft)
    cfg = cs.SearchConfig(lab_root=lab, out=out, run_dir=run_dir, frontier_dir=frontier, n_workers=int(a.get("workers", 3)), max_ticks=10 ** 9, max_wall_s=1200.0,
                          expect_code=None, stop_grace_s=60.0, verify_floor_s=5.0, verify_s_per_clear=2.0, write_reserve_s=2.0, progress_every_s=2.0, seed_parallel=3)
    P = O.engine_plan(plan, ep)
    if a.get("code_override"):
        P["order"]["code"] = {"digest": a["code_override"]}
    rc = ENGINES[a.get("engine_class", "night")](cfg, env, P, ep, order_params=dp, text_replay=text, anomaly_build={"exe": "fake", "platform": sys.platform}).run()
    res = {"code": rc, "violations": g.LabGuard.violations[:3], "plan": {k: plan[k] for k in ("sources", "archive_id", "claim_threshold", "code")}}
    if a.get("audit"):
        res["opened"] = sorted(set(opened))
    return res


def read_jsonl(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.is_file() else []


class DBench:
    """One temporary lab: run 3's fake executable, a fake frontier folder (best 3,000, so every fake clear is claimed); D's nights by name."""

    def __init__(self) -> None:
        import run3_search_tests as r3t

        self.lab = tmpdir("order_e2e_lab_")
        self.fk = r3t.fake_setup(self.lab)
        self.frontier = write_fake_frontier(self.lab, 3000)
        self.port = 52000
        self.runs: Dict[str, Dict[str, Any]] = {}

    def run(self, name: str, **args: Any) -> Dict[str, Any]:
        if name in self.runs:
            return self.runs[name]
        out = self.lab / f"order_{name}"
        self.port += 1000
        base = {"lab": str(self.lab), "out": str(out), "frontier": str(self.frontier), "exe": self.fk["exe"], "frozen": self.fk["frozen"], "exe_copy": self.fk["exe_copy"],
                "port_base": self.port, "engine": dict(E_ENGINE)}
        res = run_child("order_child", self.lab, dict(base, **args))
        d = out / "run"
        res["dir"] = d
        res["out"] = out
        if (d / "summary.json").is_file():
            res.update({"summary": json.loads((d / "summary.json").read_text(encoding="utf-8")), "config": json.loads((d / "config.json").read_text(encoding="utf-8")),
                        "root": json.loads((d / "root.json").read_text(encoding="utf-8")) if (d / "root.json").is_file() else None,
                        "dispatches": read_jsonl(d / "dispatches.jsonl"), "cells": read_jsonl(d / "cells.jsonl"), "hourly": read_jsonl(d / "hourly.jsonl"),
                        "milestones": read_jsonl(d / "milestones.jsonl"), "mver": read_jsonl(d / "milestone_verifications.jsonl"),
                        "verifications": read_jsonl(d / "verifications.jsonl"), "exports": read_jsonl(d / "exports.jsonl"), "text": read_jsonl(d / "text_replays.jsonl")})
        self.runs[name] = res
        return res

    def close(self) -> None:
        if os.environ.get("ORDER_KEEP") == "1":
            print(f"kept: {self.lab}")
            return
        cleanup(self.lab)


_DBENCH: Optional[DBench] = None


def dbench() -> DBench:
    global _DBENCH
    if _DBENCH is None:
        _DBENCH = DBench()
    return _DBENCH


PORT_LEASE_NAME = re.compile(r"port_\d+\.lease(\.[0-9a-f]{32}\.tmp)?")   # rl/port_lease.py: lease_path() and its atomic write
HOURLY_VOLATILE = ("utc", "elapsed_s", "dispatches", "status", "memory_main_mb", "jobs_per_h", "verified", "best_verified")


def _bursts(r: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return [x for x in r["dispatches"] if x.get("kind", "burst") == "burst"]


def e2e_e1_same_seed() -> Dict[str, Any]:
    """E1: two same-seed nights (reorder window, step jitter) give identical dispatch rows, cells, hourly records and milestones."""
    b = dbench()
    A, B = b.run("a"), b.run("b")
    for r in (A, B):
        check(r["code"] == 0 and r["summary"]["status"] == "DISPATCH_CAP" and not r["violations"] and len(_bursts(r)) == 160,
              f"a clean 160-dispatch night: {r['code']} {r.get('summary', {}).get('status')} {r.get('summary', {}).get('stop')} {r['violations']}")
    check(det.dispatch_signature(A["dispatches"]) == det.dispatch_signature(B["dispatches"]), "the same dispatch rows (cell, k, draw id, words, outcome, kept, cont)")
    sel = lambda r: [(x["n"], x.get("stream"), x.get("group"), x.get("niche"), json.dumps(x.get("draw"), sort_keys=True)) for x in _bursts(r)]  # noqa: E731
    check(sel(A) == sel(B), "the same draws (stream, set, order, counts, rank)")
    check(det.cells_signature(A["cells"]) == det.cells_signature(B["cells"]), "the same cell rows")
    hs = lambda r: [json.dumps({k: v for k, v in h.items() if k not in HOURLY_VOLATILE}, sort_keys=True) for h in r["hourly"]]  # noqa: E731
    check(len(A["hourly"]) >= 4 and hs(A) == hs(B), f"the same hourly records ({len(A['hourly'])})")
    ms = lambda r: [{k: v for k, v in m.items() if k not in ("utc", "elapsed_s")} for m in r["milestones"]]  # noqa: E731
    check(ms(A) == ms(B), "the same milestones")
    lv = {x["level"] for x in _bursts(A)}
    return {"dispatches": len(_bursts(A)), "cells": len(A["cells"]), "levels_dispatched": sorted(lv), "hourly": len(A["hourly"]),
            "milestones": [m["milestone"] for m in A["milestones"]], "streams": dict(Counter(x.get("stream") for x in _bursts(A)))}


def e2e_e2_root() -> Dict[str, Any]:
    """E2: the root is read twice in fresh processes and equal; it is the first cell; an injected inequality stops the open."""
    b = dbench()
    A = b.run("a")
    root = A["root"]
    reads = root["reads"]
    check(root["equal"] and len(reads) == 2 and reads[0]["digest"] == reads[1]["digest"] and reads[0]["chain"] == reads[1]["chain"] and reads[0]["pid"] != reads[1]["pid"],
          f"two fresh processes, equal tick-0 records: {[(r['pid'], r['digest'][:12]) for r in reads]}")
    c0 = A["cells"][0]
    check(c0["ev"] == "new" and c0["level"] == 0 and c0["tick"] == 0 and c0["words_hex"] == "" and c0["key"][3] == osel.ROOT_MASK,
          f"the root is the first cell (level 0, tick 0, no word, mask 1023): {c0}")
    check(all(x.get("tick0_equal") is True for x in _bursts(A)), "every dispatch's tick 0 equals the root's pin")
    check(any(x["start_tick"] == 0 for x in _bursts(A)), "the root (empty prefix) is dispatched")
    U = b.run("root_unequal", engine_class="root_unequal", engine=dict(E_ENGINE, max_dispatches=20))
    s = U["summary"]
    check(s["status"] == "SEARCH_INVALID" and "tick-0 inequality" in str(s["stop"]["reason"]) and not _bursts(U) and not U["root"]["equal"],
          f"an injected inequality: SEARCH_INVALID, no dispatch: {s['status']} {s['stop']}")
    return {"root_digest": reads[0]["digest"][:16], "unequal": U["root"]["differs"]}


def e2e_e3_pace_budget() -> Dict[str, Any]:
    """E3: behind-pace reaches are never kept (and are counted), the budget stays within 1, the streams are exploitation or breadth only."""
    b = dbench()
    A = b.run("a")
    o = A["summary"]["order"]
    lines = o["plan"]["pace"]["lines"]
    kept = [c for c in A["cells"] if c["ev"] in ("new", "replaced")]
    check(kept and all(int(c["tick"]) <= int(lines[str(c["level"])]) for c in kept), "no kept cell behind the line")
    check(o["rejected_reaches"] > 0 and sum(r["count"] for r in o["rejected"].values()) == o["rejected_reaches"]
          and all(r["distance"] >= 1 for r in o["rejected"].values()), f"the line rejected reaches (report-only): {o['rejected']}")
    streams = Counter(x.get("stream") for x in _bursts(A))
    check(set(streams) <= {"rank", "anchor", "breadth"} and streams["breadth"] and (streams["rank"] + streams["anchor"]), f"no trigger stream: {dict(streams)}")
    check(not (A["dir"] / "triggers.jsonl").exists(), "no trigger record")
    check(not any("budget_counts_not_within_1" in h["flags"] for h in o["hourly_records"]) and o["selection"]["within_one_violations"] == [],
          "the set and order counts stay within 1 at every level in the level draw (every record)")
    drawn = {x["draw"]["set"] for x in _bursts(A) if x.get("stream") in ("rank", "anchor")}
    levels = {x["draw"]["level"] for x in _bursts(A) if x.get("stream") in ("rank", "anchor")}
    check(len(drawn) >= 3 and len(levels) >= 2, f"exploitation drew several sets and levels: {len(drawn)} sets, levels {sorted(levels)}")
    beyond = sum(x["kept"].get("beyond", 0) for x in _bursts(A))
    check(beyond == o["rejected_reaches"], f"the rows' BEYOND verdicts are the rejected reaches ({beyond})")
    return {"rejected": o["rejected"], "streams": dict(streams), "sets_drawn": len(drawn), "levels_drawn": sorted(levels), "rotation": o["selection"]["rotation"]}




def e2e_e4_milestone() -> Dict[str, Any]:
    """E4: a level-6 arrival at or before line(6) = 408 is M1, verified at the close by two replays (and exported); a disagreeing replay
    leaves it unverified, reported, and the night SEARCH_INVALID (not a test of M1). The decided parameters: the fake world reaches level 6."""
    b = dbench()
    M = b.run("a")
    o = M["summary"]["order"]
    m1 = [m for m in o["milestones"] if m["milestone"] == "M1"]
    check(M["code"] == 0 and m1 and m1[0]["tick"] <= o["plan"]["milestones"]["M1"]["line"], f"M1 met in the fake world: {[m['milestone'] for m in o['milestones']]}")
    v1 = [v for v in M["mver"] if v["milestone"] == "M1"]
    check(v1 and v1[0]["verdict"] == "VERIFIED" and v1[0]["r1"]["final_chain"] == v1[0]["r2"]["final_chain"] == m1[0]["chain"] and o["gate_m1"]["verified"],
          f"M1 verified by two replays: {v1}")
    ex = [e for e in M["exports"] if e.get("milestone") == "M1"]
    check(ex and Path(ex[0]["btti"]).is_file() and ex[0]["frames"] == m1[0]["words"], "the verified prefix is exported as a .btt.txt")
    check(len(M["mver"]) == len(o["milestones"]), "every recorded milestone was verified once (first arrival only)")
    X = b.run("m_bad", engine_class="milestone_altered")
    ox = X["summary"]["order"]
    vx = [v for v in X["mver"] if v["milestone"] == "M1"]
    check(X["summary"]["status"] == "SEARCH_INVALID" and vx and vx[0]["verdict"] == "NOT_VERIFIED" and not ox["gate_m1"]["verified"]
          and "M1" in X["summary"]["integrity"]["milestones_not_verified"] and any("chain" in r for r in vx[0]["reasons"]),
          f"a disagreeing replay: M1 unverified and reported, SEARCH_INVALID: {X['summary']['status']} {vx}")
    return {"milestones": [(m["milestone"], m["tick"], m["verdict"]) for m in o["milestones"]], "m1": m1[0]["tick"], "bad": vx[0]["reasons"]}


def e2e_e5_caps_stops() -> Dict[str, Any]:
    """E5: the cells cap and a soft memory breach are clean stops; more than 3 prefix mismatches are SEARCH_INVALID; no game process left."""
    b = dbench()
    Cc = b.run("cells", engine=dict(E_ENGINE, max_cells=40, max_dispatches=0))
    Mm = b.run("memory", soft_main_mb=1.0, engine=dict(E_ENGINE, max_dispatches=0))
    Mi = b.run("mismatch", stub=True, inject={"mismatch_job": 3, "mismatch_tick": 5}, engine=dict(E_ENGINE, max_dispatches=400))
    out = {}
    for name, r, want in (("cells", Cc, "CELLS_CAP"), ("memory", Mm, "MEMORY_BUDGET"), ("mismatch", Mi, "SEARCH_INVALID")):
        s = r["summary"]
        out[name] = [s["status"], s["work"]["mismatches"], s["work"]["dispatches"]]
        check(s["status"] == want and not r["violations"] and s["integrity"].get("battleship_left") == [], f"{name}: {s['status']} (want {want}) {s['stop']}")
    check(Mi["summary"]["work"]["mismatches"] > 3 and "prefix mismatches" in str(Mi["summary"]["stop"]["reason"]), f"the mismatch limit: {Mi['summary']['stop']}")
    return out


def e2e_e6_exports() -> Dict[str, Any]:
    """E6: a fake verified clear (the trivial world clears at tick 1) gives a .btt.txt and a .bk2 with the round trip, a text replay of
    the new best, and the clear-line milestone's verified prefix export; ten targets on one tick are counted as same-tick breaks."""
    b = dbench()
    # one worker: in the trivial world every burst ends at tick 1, so three workers cycle fake processes fast enough for one memory sample
    # to catch 185 of them (5,056 MB) and trip the registered tree cap; the caps stay as registered
    T6 = b.run("trivial", world="trivial", workers=1, engine=dict(E_ENGINE, max_dispatches=12), text_replay=True)
    o = T6["summary"]["order"]
    ver = [v for v in T6["verifications"] if v.get("verdict") == "VERIFIED"]
    check(T6["code"] == 0 and ver and o["best"]["completion_input_tick"] == 1 and o["faster_than_frontier"] >= 1, f"a verified clear at tick 1: {o['best']}")
    ex = [e for e in T6["exports"] if e.get("bk2")]
    check(ex and ex[0]["roundtrip_ok"] is True and Path(ex[0]["btti"]).is_file() and Path(ex[0]["bk2"]).is_file(), f"the clear's exports: {ex[:1]}")
    check(T6["text"] and T6["text"][0].get("equal") is True, f"the native text replay of the new best (fake game): {T6['text'][:1]}")
    cl = [m for m in o["milestones"] if m["milestone"] == "clear_line"]
    mex = [e for e in T6["exports"] if e.get("milestone") == "clear_line"]
    check(cl and cl[0]["verdict"] == "VERIFIED" and mex and Path(mex[0]["btti"]).is_file() and not o["gate_m1"]["met"],
          f"the clear line verified and exported; M1 not met (no kept level-6 cell): {cl}")
    st = o["selection"]["same_tick"]
    check(st.get("10", {}).get("targets", 0) >= 10, f"ten targets on one tick are a same-tick break at level 10: {st}")
    return {"best": o["best"]["completion_input_tick"], "exports": len(T6["exports"]), "same_tick": st}


def e2e_u11_isolation() -> Dict[str, Any]:
    """U11: run 3 refuses a D folder; D refuses a D folder as its frontier, another tool's plan in its folder, and any inheritance flag;
    D writes only under its own folder through the guard."""
    b = dbench()
    A = b.run("a")
    try:
        rl3.read_run3(A["out"], 4)
        raise AssertionError("run 3 loaded a D folder")
    except rl3.LoadError as exc:
        check("frs_crossing_search_run3_v1" in str(exc), f"run3_load refuses a D folder by contract: {exc}")
    try:
        O.read_frontier_best(A["out"])
        raise AssertionError("D read a D folder as the frontier")
    except O.SearchError as exc:
        check("D folder" in str(exc), str(exc))
    other = b.lab / "order_holds_run3_plan"
    other.mkdir(exist_ok=True)
    (other / "plan.json").write_text(json.dumps({"contract": O.C.RUN3_CONTRACT}), encoding="utf-8")
    dp = osel.OrderParams()
    try:
        O.plan_and_write(b.lab, b.frontier, other, dp, O.engine_params(dp, rng_seed=1))
        raise AssertionError("D planned into a folder holding a run 3 plan")
    except O.SearchError as exc:
        check("another tool's plan" in str(exc), str(exc))
    for argv in (["plan", "--frontier", str(b.frontier), "--rng-seed", "1", "--inherit", str(A["out"])],
                 ["plan", "--frontier", str(b.frontier), "--rng-seed", "1", "--best-from", str(b.frontier)]):
        try:
            O.main(argv)
            raise AssertionError(f"accepted {argv[-2]}")
        except SystemExit as exc:
            check(exc.code == 2, f"{argv[-2]} is not a flag of D (argparse refusal): {exc.code}")
    check(not A["violations"] and (A["dir"] / "summary.json").is_file(), "the night wrote under its own folder with no guard violation")
    return {"refused": ["run3_load", "frontier=D", "run 3 plan", "--inherit", "--best-from"]}


def e2e_u13_no_human_input() -> Dict[str, Any]:
    """U13: the plan's sources are the frontier's best record only; the plan and the night open no fixture, capture, TAS or human
    recording (an audit hook on every open of the main process)."""
    b = dbench()
    H = b.run("audit", audit=True, engine=dict(E_ENGINE, max_dispatches=30))
    check(H["code"] == 0, f"a clean night: exit {H['code']}, {(H.get('summary') or {}).get('status')} {(H.get('summary') or {}).get('stop')}")
    check(H["plan"]["sources"] == [str(b.frontier / "run" / "summary.json")], f"the plan's source list: {H['plan']['sources']}")
    bad = [p for p in H["opened"] if any(f in p.replace("\\", "/").lower() for f in g.FORBIDDEN_FRAGMENTS)]
    check(not bad, f"no forbidden path opened: {bad[:5]}")
    lab, own, fr_dir = g.norm(b.lab), g.norm(H["out"]), g.norm(b.frontier)
    outside = sorted({p for p in H["opened"] if g.under(g.norm(p), lab) and not g.under(g.norm(p), own) and not g.under(g.norm(p), g.norm(b.lab / "fake"))
                      and not g.under(g.norm(p), g.norm(b.lab / f"replays_{H['out'].name}"))})
    # rl/port_lease.py: the machine-wide port lease the shared launcher (rl/battleship_process.py) holds for every game process it starts,
    # under the guard in <lab root>/port_leases (the fresh-process verification and milestone replays launch from the main process).
    # Launch bookkeeping, read by no rule of D: only these two exact name patterns, only directly in <lab root>/port_leases.
    leases = [p for p in outside if g.norm(Path(p).parent) == g.norm(b.lab / "port_leases") and PORT_LEASE_NAME.fullmatch(Path(p).name)]
    rest = [p for p in outside if p not in leases]
    check(all(g.under(g.norm(p), fr_dir) for p in rest) and {Path(p).name for p in rest} <= {"plan.json", "summary.json"},
          f"in the lab, only D's folder, the frontier's plan and summary, and port leases are opened: {rest}")
    return {"opened": len(H["opened"]), "lab_outside_own": rest, "port_leases": len(leases)}


def e2e_tm2_code_digest() -> Dict[str, Any]:
    """T-M2: D's manifest covers its import closure (D's two modules and every run 3 file), hashes with LF line endings, is enforced at
    the open, and a change during the run is SEARCH_INVALID at the close."""
    import run3_manifest as rm

    b = dbench()
    A = b.run("a")
    oc = A["config"]["order_code"]
    files = set(oc["files"])
    run3 = set(rm.run3_code_manifest())
    check(oc["digest"] == oc["expected"] == A["plan"]["code"]["digest"] and {"tools/frs/order_search.py", "tools/frs/order_select.py"} <= files and run3 <= files
          and len(files) == len(run3) + 2, f"D's manifest: {len(files)} files = run 3's {len(run3)} + D's 2")
    t = tmpdir("order_lf_")
    try:
        (t / "lf.py").write_bytes(b"a = 1\nb = 2\n")
        (t / "crlf.py").write_bytes(b"a = 1\r\nb = 2\r\n")
        check(O.lf_sha256(t / "lf.py") == O.lf_sha256(t / "crlf.py") != hashlib.sha256(b"a = 1\r\nb = 2\r\n").hexdigest(), "CRLF and LF copies hash the same")
    finally:
        cleanup(t)
    R = b.run("refused", code_override="0" * 64, engine=dict(E_ENGINE, max_dispatches=10))
    check(R["code"] == O.cs.EXIT["REFUSED"] and not R["dir"].exists() and list(R["out"].glob("refused_*.json")), f"a different digest refuses the open: {R['code']}")
    X = b.run("code_changed", engine_class="code_changed", engine=dict(E_ENGINE, max_dispatches=20))
    si = X["summary"]["integrity"]
    check(X["summary"]["status"] == "SEARCH_INVALID" and si["order_code_changed_during_run"], f"a change during the run: {X['summary']['status']} {si.get('order_code_changed_during_run')}")
    return {"files": len(files), "digest": oc["digest"][:16]}


def real_frontier_best() -> Dict[str, Any]:
    """Zero ticks, read only: the frontier chain's last night (night 3) gives the claim threshold 907."""
    d = Path("C:/BattleShip_lab/crossing_2026-11-11_run3c")
    if not (d / "run" / "summary.json").is_file():
        return {"skipped": f"no {d}"}
    fb = O.read_frontier_best(d)
    check(fb["completion_input_tick"] == 907 and fb["completion_time_passed"] == 906, f"night 3's best: {fb}")
    return {k: fb[k] for k in ("completion_input_tick", "completion_time_passed", "status")}


UNIT = {f.__name__: f for f in (unit_u1_pace_line, unit_u2_rejected_readout, unit_u2_group_move, unit_u3_root_and_niches, unit_u4_set_then_order,
                                unit_u4_ties, unit_u4_cell_draw_is_run3s, unit_u5_newcomers, unit_u6_level_weights, unit_u7_retirement,
                                unit_u7_stale_clear_fallback, unit_u8_milestones, unit_u9_claims, unit_u10_params, unit_u12_relabelling, unit_root_differences,
                                unit_u14_tree_sampler, unit_f3_pace_filter, unit_tm1_run3_digest)}

E2E = {f.__name__: f for f in (e2e_e1_same_seed, e2e_e2_root, e2e_e3_pace_budget, e2e_e4_milestone, e2e_e5_caps_stops, e2e_e6_exports,
                               e2e_u11_isolation, e2e_u13_no_human_input, e2e_tm2_code_digest)}
REAL = {f.__name__: f for f in (real_frontier_best,)}

if __name__ == "__main__":
    args = sys.argv[1:]
    groups = {"unit": UNIT, "e2e": E2E, "real": REAL}
    tests = dict(groups[args[0]]) if args[:1] and args[0] in groups else dict(UNIT, **E2E, **REAL)
    rest = [x for x in args if x not in groups]
    try:
        code = run_suite("option D tests", tests, rest)
    finally:
        if _DBENCH is not None:
            _DBENCH.close()
    sys.exit(code)
