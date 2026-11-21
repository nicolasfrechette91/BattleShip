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
import order_worker as OW  # noqa: E402
import run3_load as rl3  # noqa: E402
import run3_select as rs  # noqa: E402
from infra_testlib import check, cleanup, run_suite, tmpdir  # noqa: E402

D_MODULES = ("order_select", "order_search", "order_worker", "order_search_tests")
# The run 3 manifest digest (tools/frs/run3_manifest.py) of the frontier code (contract run3_select_v4). The manifest hashes working-file
# bytes: the main tree's working copy holds 7 rl/ files with CRLF line endings (the index has LF), a fresh checkout holds them with LF. Same
# content, two digests; both are the frontier code. Any other value means a run 3 file changed. Owner 2026-11-14 (design 6.7): fix B
# (rl/frs_machine.py) and the D hand-off (tools/frs/run3_dseeds.py, 55 files) replace the 73cbde95 / 11ec3040 pair of 54 files.
RUN3_FILES = 55
RUN3_DIGESTS = {"e9dad437b186984dfa553208507a5f1b7577e8ea1f271d92430bd8553af9b4f3": "main tree working copy (7 rl/ files CRLF)",
                "89e641509ae56f0715d6e16d28799fb1c58923ea81ad75196d33b4f8e9c7522b": "the same files with LF (fresh checkout)"}


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
    for L in range(10):                                  # the arrival rule (order_select_v2): arrival <= line(L), own tick <= line(L + 1)
        a = want[L] if L > 0 else 0
        check(pace.keeps(L, want[L + 1], a) and not pace.keeps(L, want[L + 1] + 1, a), f"level {L}: kept until line({L + 1}), not one tick later")
        if L > 0:
            check(not pace.keeps(L, want[L] + 1, want[L] + 1) and pace.reason(L, want[L] + 1, want[L] + 1) == ("late_arrival", 1),
                  f"level {L}: an arrival at line({L}) + 1 is late")
        check(pace.reason(L, want[L + 1] + 5, a) == ("window_passed", 5) and pace.window_end(L) == want[L + 1], f"level {L}: the window ends at line({L + 1})")
    check(pace.keeps(6, 456, 351) and not pace.keeps(6, 457, 351) and pace.keeps(6, 456, 408) and not pace.keeps(6, 420, 409),
          "a level-6 state that arrived at 351 stays until line(7) = 456; an arrival at 409 is not kept")
    check(pace.keeps(9, 600, 552) and not pace.keeps(9, 601, 552) and pace.window_end(9) == 600, "level 9's limit is the clear line line(10) = 600")
    check(not pace.keeps(10, 600, 600), "level 10 (a clear) is never a kept state")
    check(_raises_value(pace.reason, 6, 400, 401) and _raises_value(osel.arrival_tick, [1, 2], 3) and osel.arrival_tick([], 0) == 0
          and osel.arrival_tick([5, 9, 9], 3) == 9, "an arrival after the state's tick, or a break-tick count that is not the level, is refused")
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

    def rej(level: int, tick: int, arrival: int) -> int:
        why = pace.reason(level, tick, arrival)
        assert why is not None
        return rr.note(level, tick, *why)

    check(rej(6, 457, 351) == 1, "a level-6 state at line(7) + 1 = 457 is rejected (window passed, +1)")
    check(rej(6, 409, 409) == 1, "a level-6 arrival at line(6) + 1 = 409 is rejected (late arrival, +1)")
    rej(6, 470, 351)
    rej(3, 400, 200)
    check(_raises_value(rr.note, 6, 408, "late_arrival", 0) and _raises_value(rr.note, 6, 500, "pace", 3), "a distance under 1 or an unknown reason is refused")
    night = rr.summary()
    check(night["6"] == {"count": 3, "earliest_tick": 409, "distance": 1, "reason": "late_arrival", "window_passed": 2, "window_passed_min_distance": 1,
                         "late_arrival": 1, "late_arrival_min_distance": 1}, f"level 6: count 3, earliest the minimum (409, +1, late): {night['6']}")
    check(night["3"]["count"] == 1 and night["3"]["earliest_tick"] == 400 and night["3"]["distance"] == 88 and night["3"]["reason"] == "window_passed",
          f"level 3 (window line(4) = 312): {night['3']}")
    hour = rr.snapshot()
    check(hour == night, "the first period equals the night so far")
    rej(6, 430, 420)
    check(rr.snapshot()["6"]["count"] == 1 and rr.summary()["6"]["count"] == 4, "the period resets at each snapshot; the night accumulates")
    fresh = osel.Pace(osel.OrderParams())
    check(all(fresh.keeps(L, t, a) == pace.keeps(L, t, a) for L in range(10) for t in (100, 408, 409, 600) for a in (0, 100, 300) if a <= t),
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
    check(m["files"] == RUN3_FILES, f"the run 3 manifest has {RUN3_FILES} files ({m['files']})")
    check(m["digest"] in RUN3_DIGESTS, f"the run 3 digest {m['digest']} is the frontier code's (e9dad437, or the same files with LF)")
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


class TickArrivals(dict):
    """The selector's break ticks for the fake archive's cells: a fake cell's arrival is its own (current) tick, so under the arrival rule a
    fake cell is eligible exactly when its tick <= line(L) (the v1 rule the in-process tests were written for). An explicit entry wins.
    The engine's own break ticks are tested on the fake game (E3, E7, E8)."""

    def __init__(self, a: "FArchive"):
        super().__init__()
        self.a = a

    def __missing__(self, cid: int) -> Tuple[int, ...]:
        c = self.a.cells[int(cid)]
        return tuple([int(c.tick)] * int(c.level))


class Static:
    """A fixed archive built from orders (target labels in break order) under the single tick-0 root."""

    def __init__(self, spec: Sequence[Tuple[Any, ...]] = (), root: bool = True):
        self.a = FArchive()
        self.niches: Dict[int, Any] = {}
        self.breaks = TickArrivals(self.a)
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
        return osel.OrderSelector(self.a, osel.OrderParams(**kw), niches=self.niches, breaks=self.breaks)


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
            why = sel.pace.reason(lv, t, t if lv else 0)       # the fake's arrival is its tick (TickArrivals)
            if why is not None:
                sel.pace.rejected.note(lv, t, *why)
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
    d = osel.OrderSelector(s.a, p, niches=s.niches, breaks=s.breaks)
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

    def ticks(level: int, arrival: int) -> List[int]:
        return [max(0, arrival - 10 * (level - i)) for i in range(1, level)] + [arrival]

    for name, L in osel.MILESTONES:
        line = pace.line(L)
        for high in (False, True):
            ms = osel.Milestones(pace)
            check(ms.observe_kept(fc(L, line + 30, high=high), 5, ticks(L, line + 1)) == [], f"{name}: not with the L-th break at line({L}) + 1 = {line + 1}")
            check(ms.observe_kept(fc(L, line + 30, 7, high=high), 6, ticks(L, line)) == [name],
                  f"{name}: met by a cell at line({L}) + 30 whose L-th break came at line({L}) = {line}, in either mask (the arrival rule)")
            check(ms.met[name]["tick"] == line and ms.met[name]["cell_tick"] == line + 30, f"{name}: the milestone's tick is the break's: {ms.met[name]}")
    ms = osel.Milestones(pace)
    check(ms.observe_kept(fc(7, 420), 3, ticks(5, 300) + [400, 400]) == ["M1", "M2"],
          "gap E: a level-7 cell whose 6th and 7th breaks came at 400 (no level-6 cell) meets M1 and M2")
    check(ms.observe_kept(fc(6, 300, cid=9), 4, ticks(6, 300)) == [] and ms.met["M1"]["cid"] == 1, "recorded once, at the first occurrence")
    check(ms.met["M1"] == {"milestone": "M1", "level": 6, "line": 408, "arrival_level": 7, "tick": 400, "cell_tick": 420, "inherited_until": 0, "n": 3,
                           "cid": 1, "digest": "d1", "chain": "0102"}, f"with dispatch, cell and lineage digest: {ms.met['M1']}")
    ms = osel.Milestones(pace)
    check(ms.observe_kept(fc(7, 450), 1, ticks(5, 300) + [430, 430]) == ["M2"], "a double break at 430: M2 (line 456) but not M1 (line 408)")
    check(_raises_value(ms.observe_kept, fc(7, 450), 2, [1, 2]), "a cell whose break-tick count is not its level is refused")
    ms = osel.Milestones(pace)                           # v3 (owner 2026-11-16): the L-th break must happen in one of the night's bursts
    check(ms.observe_kept(fc(6, 411), 2, ticks(5, 300) + [351], after=351) == [],
          "a cell kept tonight whose 6th break (351) is in its inherited prefix (inherited until 351) does not meet M1")
    check(ms.observe_kept(fc(7, 460), 3, ticks(5, 300) + [351, 440], after=351) == ["M2"] and "M1" not in ms.met,
          "its 7th break at 440, made tonight, meets M2; the inherited 6th break still does not meet M1")
    check(ms.observe_kept(fc(6, 380), 4, ticks(5, 300) + [352], after=351) == ["M1"] and ms.met["M1"]["inherited_until"] == 351,
          "a 6th break one tick after the inherited prefix (352) happened tonight: M1")
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


def unit_cont_window_rule() -> Dict[str, Any]:
    """The continuation rule (owner 2026-11-16, replaces F3): at a boundary the burst continues while the state there is inside the arrival
    rule; the main process follows the job's mask through the reaches of every boundary question (one whole segment each)."""
    night = object.__new__(O.OrderNight)                 # only the attributes window_decision reads
    night.pace = osel.Pace(osel.OrderParams())
    m5, m6, m7 = ((osel.ROOT_MASK << k) & osel.ROOT_MASK for k in (5, 6, 7))
    p5 = ((50, 0), (90, 1), (130, 2), (200, 3), (240, 4))

    def job() -> Dict[str, Any]:
        return {"n": 1, "d_pairs0": p5, "d_mask0": m5}

    def ask(info: Dict[str, Any], words: int, reaches: Sequence[Tuple[int, int]], L: int = 250) -> Dict[str, Any]:
        return O.OrderEngine.window_decision(night, info, {"L": L, "words": words, "reaches": [[j, [j % 7, 0, "A2", m, -1]] for j, m in reaches]})

    a = job()
    d = ask(a, 120, [(300, m5), (351, m6), (360, m6)])
    check(d == {"go": True, "level": 6, "arrival": 351, "tick": 370}, f"a 6th break at 351 inside line(6): the state at 370 <= line(7) = 456 goes on: {d}")
    d = ask(a, 240, [(400, m6)])
    check(d == {"go": False, "level": 6, "arrival": 351, "tick": 490}, f"the same lineage at 490 > 456 stops (the arrival is remembered): {d}")
    b = job()
    check(ask(b, 120, [(260, m5)])["go"] and not ask(b, 240, [])["go"], "no break: level 5 (arrival 240) goes on at 370 <= line(6) = 408, stops at 490")
    c = job()
    d = ask(c, 240, [(420, m6)], L=250)
    check(d["go"] is False and d["arrival"] == 420 and d["level"] == 6, f"a 6th break at 420 > line(6) = 408 is a late arrival: stop: {d}")
    e = job()
    d = ask(e, 120, [(330, m7)], L=250)
    check(d == {"go": True, "level": 7, "arrival": 330, "tick": 370}, f"two targets on one tick: level 7, both breaks at 330: {d}")
    check(e["d_track"]["pairs"][-2:] == [(330, 5), (330, 6)], f"the followed break pairs: {e['d_track']['pairs']}")
    f = job()
    ask(f, 120, [(300, m6)])
    try:
        ask(f, 240, [(400, m5)])
        raise AssertionError("a live target came back and was accepted")
    except O.SearchError:
        pass
    g9 = {"n": 2, "d_pairs0": tuple((10 * (i + 1), i) for i in range(9)), "d_mask0": 1 << 9}
    check(O.OrderEngine.window_decision(night, g9, {"L": 540, "words": 60, "reaches": []})["go"] and
          not O.OrderEngine.window_decision(night, {"n": 3, "d_pairs0": g9["d_pairs0"], "d_mask0": 1 << 9}, {"L": 540, "words": 61, "reaches": []})["go"],
          "level 9: the window ends at the clear line line(10) = 600")
    return {"line6": night.pace.line(6), "window6": night.pace.window_end(6)}


def unit_burst_extent() -> Dict[str, Any]:
    """The exploration-extent record (owner 2026-11-16, report-only): per level and target set, over every reach, the highest y and the
    lowest / highest x with their ticks, for all reaches and for those inside the keep window; folded per set with the dispatch."""
    pace = osel.Pace(osel.OrderParams())
    m5, m6 = ((osel.ROOT_MASK << k) & osel.ROOT_MASK for k in (5, 6))
    breaks = [[50, 0], [90, 1], [130, 2], [200, 3], [240, 4], [390, 5]]

    def reach(j: int, m: int, x: float, y: float) -> List[Any]:
        obs = [0] * len(O.mcell.OBS_FIELDS)
        obs[O.OBS_X], obs[O.OBS_Y] = x, y
        return [j, [j % 5, 0, "A2", m, -1], obs, b"", b"", False]

    rs_ = [reach(350, m5, -200.0, 500.0), reach(310, m5, 100.0, 0.0), reach(395, m6, 50.0, 900.0), reach(470, m6, -400.0, 1200.0),
           reach(480, m6, 700.0, 100.0)]
    e = O.burst_extent(rs_, breaks, pace)
    five = {"reaches": 2, "max_y": [500.0, 350], "min_x": [-200.0, 350], "max_x": [100.0, 310]}
    check(e[f"5|{m5}"] == {"level": 5, "mask": m5, "all": five, "inside": five}, f"level 5, every reach inside line(6) = 408: {e[f'5|{m5}']}")
    check(e[f"6|{m6}"]["all"] == {"reaches": 3, "max_y": [1200.0, 470], "min_x": [-400.0, 470], "max_x": [700.0, 480]}
          and e[f"6|{m6}"]["inside"] == {"reaches": 1, "max_y": [900.0, 395], "min_x": [50.0, 395], "max_x": [50.0, 395]},
          f"level 6: the reaches past line(7) = 456 count under all only: {e[f'6|{m6}']}")
    acc: Dict[str, Any] = {}
    O.merge_extent(acc, e[f"6|{m6}"]["all"], 7)
    O.merge_extent(acc, {"reaches": 2, "max_y": [1500.0, 500], "min_x": [0.0, 499], "max_x": [800.0, 498]}, 9)
    check(acc == {"reaches": 5, "bursts": 2, "max_y": [1500.0, 500, 9], "min_x": [-400.0, 470, 7], "max_x": [800.0, 498, 9]}, f"folded with the dispatch: {acc}")
    try:
        O.burst_extent([reach(400, m6, 0.0, 0.0)], breaks[:5], pace)
        raise AssertionError("a reach whose break ticks are not its level was accepted")
    except O.SearchError:
        pass
    return {"level6": e[f"6|{m6}"]}


def unit_resume_lineage() -> Dict[str, Any]:
    """Resume (owner 2026-11-16): a folder row's niche and break pairs from the folder's own lineage (root, burst rows by parent digest and
    dispatch breaks, resumed rows and rows recording d_breaks); a dispatch whose breaks are not the targets the mask lost is refused."""
    root = {"cid": 0, "digest": "r", "key": [0, 0, "G", osel.ROOT_MASK, 4], "tick": 0, "level": 0, "origin": {"kind": "root"}}
    m1 = osel.ROOT_MASK & ~(1 << 4)
    m3 = m1 & ~(1 << 0) & ~(1 << 9)
    a = {"cid": 1, "digest": "a", "key": [1, 0, "A2", m1, -1], "tick": 30, "level": 1, "origin": {"kind": "burst", "parent_digest": "r", "n": 1}}
    b = {"cid": 2, "digest": "b", "key": [2, 0, "A1", m3, -1], "tick": 90, "level": 3, "origin": {"kind": "burst", "parent_digest": "a", "n": 2}}
    disp = {1: [[16, 4], [70, 0]], 2: [[60, 9], [60, 0], [95, 2]]}
    lx = O.LineageIndex([root, a, b], disp)
    na, pa = lx.of(a)
    nb, pb = lx.of(b)
    check(rs.niche_label(na) == "1023:4" and pa == ((16, 4),), f"a: one break at 16 (dispatch 1's break at 70 is after its tick 30): {na} {pa}")
    check(rs.niche_label(nb) == "1023:4-0-9" and pb == ((16, 4), (60, 0), (60, 9)), f"b: the same-tick pair ordered by target label: {nb} {pb}")
    r = {"cid": 3, "digest": "z", "key": [3, 0, "G", m3, 2], "tick": 120, "level": 3,
         "origin": {"kind": "resume", "niche": "1023:9-4-0", "d_breaks": [[12, 9], [40, 4], [99, 0]]}}
    c = {"cid": 4, "digest": "c", "key": [4, 0, "A2", m3 & ~(1 << 2), -1], "tick": 150, "level": 4,
         "origin": {"kind": "burst", "parent_digest": "z", "n": 3, "d_breaks": [[12, 9], [40, 4], [99, 0], [140, 2]]}}
    lx2 = O.LineageIndex([r, c], {3: [[140, 2]]})
    nc, pc = lx2.of(c)
    check(rs.niche_label(nc) == "1023:9-4-0-2" and pc == ((12, 9), (40, 4), (99, 0), (140, 2)), f"from a resumed row: {nc} {pc}")
    bad = dict(c, origin=dict(c["origin"], d_breaks=[[12, 9], [40, 4], [99, 0], [141, 2]]))
    try:
        O.LineageIndex([r, bad], {3: [[140, 2]]}).of(bad)
        raise AssertionError("a row whose recorded break ticks disagree with its lineage was accepted")
    except O.SearchError:
        pass
    wrong = dict(b, origin=dict(b["origin"], n=1))
    try:
        O.LineageIndex([root, a, wrong], disp).of(wrong)
        raise AssertionError("a dispatch whose breaks are not the lost targets was accepted")
    except O.SearchError:
        pass
    orphan = dict(b, origin=dict(b["origin"], parent_digest="missing"))
    try:
        O.LineageIndex([root, orphan], disp).of(orphan)
        raise AssertionError("an orphan row was accepted")
    except O.SearchError:
        pass
    return {"b": [rs.niche_label(nb), list(pb)], "c": [rs.niche_label(nc), list(pc)]}


# -- the open line from level K and the fewest-dispatches draw (owner 2026-11-18, order_select_v4) ---------------------------------------------


def _v3_or_open(pace: osel.Pace, lv: int, tick: int, bt: Sequence[int], k: Optional[int]) -> bool:
    """The rule by hand: v3 (L-th break <= line(L), tick <= line(L + 1)) or, at a level >= K, the K-th break <= line(K)."""
    a = bt[lv - 1] if lv else 0
    v3 = a <= pace.line(lv) and tick <= pace.line(min(lv + 1, 10))
    return lv < 10 and (v3 or (k is not None and lv >= k and bt[k - 1] <= pace.line(k)))


def unit_open_line_rule() -> Dict[str, Any]:
    """K = 7 at goal 480, slack 200 (line(7) = 536, line(8) = 584): a level-7 state past line(8) is kept when its 7th break came by 536 and
    not when it came after; levels >= 8 need only the 7th break by 536; a state v3 keeps stays kept; levels below 7 and the option off give
    v3's answers everywhere."""
    off = osel.Pace(osel.OrderParams(slack=200))
    on = osel.Pace(osel.OrderParams(slack=200, open_line_from=7))
    check((on.line(7), on.line(8), on.line(10)) == (536, 584, 680) and on.open_from == 7 and off.open_from is None, f"lines {on.lines}")
    b7 = [10, 50, 100, 200, 300, 400, 536]
    check(on.keeps_ticks(7, 585, b7) and on.keeps_ticks(7, 3600, b7) and not off.keeps_ticks(7, 585, b7), "a level-7 state past line(8) is kept with K = 7 only")
    late = b7[:6] + [537]
    check(not on.keeps_ticks(7, 560, late) and on.reason_ticks(7, 560, late) == ("late_arrival", 1) and not on.keeps_ticks(7, 900, late),
          "a level-7 state whose 7th break came after line(7) is not kept (v3's reason and distance)")
    check(on.keeps_ticks(8, 1500, b7 + [1400]) and on.keeps_ticks(9, 3000, b7 + [900, 2900]) and not off.keeps_ticks(8, 1500, b7 + [1400]),
          "levels 8 and 9: no line on the later breaks or the own tick")
    check(on.keeps_ticks(8, 600, late + [560]) and not on.keeps_ticks(8, 600, late + [590]) and on.reason_ticks(8, 600, late + [590]) == ("late_arrival", 6),
          "a level-8 state with a late 7th break: kept exactly when v3 keeps it (the option only opens)")
    check(not on.keeps_ticks(10, 700, b7 + [600, 650, 690]), "a clear is never a kept state")
    grid = 0
    for lv in range(10):
        for tick in (0, 100, 300, 400, 488, 489, 536, 537, 584, 585, 632, 680, 681, 900, 3600):
            for a in (0, 50, 200, 400, 488, 489, 536, 537, 584, 585, 700):
                if (lv == 0 and a) or a > tick:
                    continue
                bt = sorted([min(a, 5 + j) for j in range(lv - 1)] + ([a] if lv else []))
                want_on = _v3_or_open(on, lv, tick, bt, 7)
                check(on.keeps_ticks(lv, tick, bt) == want_on and off.keeps_ticks(lv, tick, bt) == _v3_or_open(off, lv, tick, bt, None)
                      == off.keeps(lv, tick, a), f"level {lv} tick {tick} breaks {bt}")
                if lv < 7:
                    check(on.reason_ticks(lv, tick, bt) == off.reason(lv, tick, a), f"level {lv} unaffected by K = 7")
                grid += 1
    c = SimpleCell(7, 700, True)
    check(on.eligible_ticks(c, b7) and not off.eligible_ticks(c, b7) and not on.eligible_ticks(SimpleCell(7, 700, False), b7), "eligible_ticks: alive and inside")
    return {"lines": list(on.lines), "grid": grid}


@dataclass
class SimpleCell:
    level: int
    tick: int
    live: bool

    def alive(self) -> bool:
        return self.live


def unit_open_line_params() -> Dict[str, Any]:
    """The option: K in 1 ... 9 or off (None); off keeps the parameter record v3's (no key), on adds it and changes the fingerprint."""
    for bad in (0, 10, -1, 7.0, True, "7"):
        check(_refused(osel.OrderParams(open_line_from=bad).check), f"refused: K = {bad!r}")
    for ok in (1, 7, 9, None):
        osel.OrderParams(open_line_from=ok).check()
    off, on = osel.OrderParams(), osel.OrderParams(open_line_from=7)
    check("open_line_from" not in off.as_record() and on.as_record()["open_line_from"] == 7, "the record carries K only when set")
    check(osel.params_fingerprint(on) != osel.params_fingerprint(off) != osel.params_fingerprint(osel.OrderParams(open_line_from=6)),
          "K changes the fingerprint")
    check(osel.SELECT_CONTRACT == "order_select_v7" and "fewest" in osel.STREAMS and "fewest" in osel.EXPLOIT_STREAMS, "contract v7, stream fewest")
    return {"fingerprint_off": osel.params_fingerprint(off)[:16], "fingerprint_k7": osel.params_fingerprint(on)[:16]}


def _lv7_static(k: Optional[int]) -> Tuple[Static, osel.OrderSelector, List[FCell]]:
    """Level-7 cells of one order past line(8) = 504 (default slack 120), 7th break at line(7) = 456; one with a late 7th break (460); one
    level-8 cell (7th at 456, 8th at 900)."""
    s = Static(root=False)
    order = (0, 1, 2, 3, 4, 5, 9)
    cells = [s.add(order, t) for t in (600, 520, 700, 650)]
    for c in cells:
        s.breaks[c.cid] = (10, 20, 30, 40, 50, 60, 456)
    late = s.add(order, 470)
    s.breaks[late.cid] = (10, 20, 30, 40, 50, 60, 460)
    deep = s.add(order + (6,), 950)
    s.breaks[deep.cid] = (10, 20, 30, 40, 50, 60, 456, 900)
    return s, s.selector(open_line_from=k), cells + [late, deep]


def unit_open_line_draw() -> Dict[str, Any]:
    """Draws at levels >= K follow the fewest dispatches of the cell (breadth included, counted when selected); no anchor or rank draw
    there; v6 (owner 2026-11-19): levels 7 and 8 are one draw group (scope "group"), ties to the deeper level, then the earlier tick, and
    the set / order budget does not count it; levels below K draw as before (same cells, same records, same uniforms)."""
    s, sel, cells = _lv7_static(7)
    a600, b520, c700, d650, late, deep = cells
    _s0, sel_off, _c0 = _lv7_static(None)
    check(sel_off.select(ScriptRng([0.5, 0.0, 0.0, 0.0])) is None, "option off: none of these cells is eligible (all past line(8) or late)")
    check(sel.is_active(a600.cid) and not sel.is_active(late.cid) and sel.is_active(deep.cid), "K = 7: eligible by the open line; the late one is not")
    check(sel.level_weights(list(sel.rotation_levels())) == {7: 1.0}, f"levels 7 and 8: one draw key: {sel.level_weights(list(sel.rotation_levels()))}")
    picks = []
    for n in range(6):
        c, draw = sel.select(ScriptRng([0.5, 0.0]))
        check(draw["stream"] == "fewest" and draw["scope"] == "group" and draw["draw_group_levels"] == [7, 8] and draw["level"] == int(c.level)
              and "anchor_p" not in draw, f"draw {n}: {draw}")
        pool = [x for lv in (7, 8) for st in sel.rot_by_level.get(lv, ()) for g_ in sel.rot_by_set[st] for x in sel.members(g_)]
        exp = min(pool, key=lambda x: (sel.bcount.get(x, 0), -int(sel.group[x][0]), sel.tick_of[x], x))
        check(c.cid == exp and draw["count"] == sel.bcount.get(c.cid, 0) and draw["rank"] == sel.members(sel.group[c.cid]).index(c.cid),
              f"draw {n}: the fewest-dispatch cell, then the deeper level, then the earliest tick ({c.cid} vs {exp})")
        info = dict(sel.on_dispatch(c, draw, n))
        info.update(cid=int(c.cid), level=int(c.level))
        take(sel, info, n=n)
        picks.append(int(c.tick))
    check(picks == [950, 520, 600, 650, 700, 950], f"the level-8 cell first (deeper), then level 7 in tick order, then again: {picks}")
    check(sel.set_count[(7, a600.key[3])] == 0 and sum(sel.order_count.values()) == 0 and sel.dstat["group_draws"] == 6,
          "v6: the set / order budget does not count the group's draws (no rotation at levels >= K)")
    info = send(sel, b520, 6, stream="breadth")          # a breadth dispatch counts for the cell too
    take(sel, info, n=6)
    c, draw = sel.select(ScriptRng([0.5, 0.0]))
    check(c.tick == 600 and draw["count"] == 1, f"after a breadth dispatch of 520, 600 has the fewest: {c.tick} {draw}")
    # levels below K: the same draws with and without the option
    spec = [((0, 1, 2), 100 + 3 * i) for i in range(8)] + [((0, 1, 2, 3, 4, 5), 300 + 5 * i) for i in range(6)] + [((4, 5, 6, 7, 8), 250 + 7 * i) for i in range(5)]
    t_on, t_off = Static(spec), Static(spec)
    s_on, s_off = t_on.selector(open_line_from=7), t_off.selector()
    r_on, r_off = random.Random(5), random.Random(5)
    streams: Counter = Counter()
    for n in range(400):
        p_on, p_off = s_on.select(r_on), s_off.select(r_off)
        check(p_on[0].cid == p_off[0].cid and p_on[1] == p_off[1], f"draw {n} below K: {p_on[1]} vs {p_off[1]}")
        for sel_, p in ((s_on, p_on), (s_off, p_off)):
            info = dict(sel_.on_dispatch(p[0], p[1], n))
            info.update(cid=int(p[0].cid), level=int(p[0].level))
            take(sel_, info, n=n)
        streams[p_on[1]["stream"]] += 1
    check(streams["anchor"] and streams["rank"] and not streams["fewest"], f"run 3's draw below K: {dict(streams)}")
    return {"picks": picks, "below_k_streams": dict(streams)}


def unit_open_line_plan() -> Dict[str, Any]:
    """The plan and the archive bound: off, the keep rule record is v3's (no open key) and the archive bound line(10); with K, the record
    states the open rule and the archive's bound is the horizon (crossing_search.Archive.keep never cuts a level >= K state's tick)."""
    lab = tmpdir("order_open_plan_")
    try:
        fr_dir = write_fake_frontier(lab, 3000)
        out = {}
        for name, kw in (("off", {"slack": 200}), ("k7", {"slack": 200, "open_line_from": 7})):
            dp = osel.OrderParams(**kw)
            ep = O.engine_params(dp, rng_seed=3)
            P = O.build_plan(lab, fr_dir, lab / f"order_{name}", dp, ep, code="test")
            E = O.engine_plan(P, ep)
            out[name] = (P, E)
        P0, E0 = out["off"]
        P7, E7 = out["k7"]
        check(set(P0["keep_rule"]) == {"selection_contract", "rule", "windows"} and "open_line_from" not in P0["params"], f"off: v3's records {P0['keep_rule'].keys()}")
        check(E0["archive"].bound == E0["bound"] == 680 == O.archive_bound(osel.OrderParams(slack=200)), f"off: the archive bound is line(10) = 680: {E0['bound']}")
        kr = P7["keep_rule"]
        check(kr["open_line_from"] == 7 and kr["open_line"] == 536 and kr["archive_bound"] == O.mcell.HORIZON == 3600 and P7["params"]["open_line_from"] == 7,
              f"K = 7: the plan states the open rule: {kr}")
        check(E7["archive"].bound == E7["bound"] == 3600 and E7["plan"]["e7"]["bound_max_L"] == 3600, "K = 7: the archive's bound is the horizon")
        check(P7["pace"] == P0["pace"] and P7["milestones"] == P0["milestones"] and kr["windows"] == P0["keep_rule"]["windows"], "lines, milestones and windows unchanged")
        return {"off_bound": E0["bound"], "k7": {k: kr[k] for k in ("open_line_from", "open_line", "archive_bound")}}
    finally:
        cleanup(lab)


# -- v5 (owner 2026-11-19): the level-wide fewest draw at levels >= K and the fall cut ---------------------------------------------------------

B7 = (10, 20, 30, 40, 50, 60, 456)                       # 7th break at line(7) = 456 (slack 120): kept past line(8) = 504 by the open line only


def _lv7_orders() -> Tuple[Static, Dict[str, List[FCell]]]:
    """Level 7, past line(8): set S1 with order A (5 cells) and order B (2 cells, one tied with A's first tick), set S2 with order C
    (2 cells); every 7th break at 456."""
    s = Static(root=False)
    spec = {"A": ((0, 1, 2, 3, 4, 5, 9), (600, 610, 620, 630, 640)), "B": ((0, 1, 2, 3, 4, 9, 5), (605, 600)),
            "C": ((0, 1, 2, 3, 4, 5, 6), (601, 700))}
    cells: Dict[str, List[FCell]] = {}
    for name, (order, ticks) in spec.items():
        for t in ticks:
            c = s.add(order, t)
            s.breaks[c.cid] = B7
            cells.setdefault(name, []).append(c)
    return s, cells


def unit_group_fewest_draw() -> Dict[str, Any]:
    """Ruling 1 (owner 2026-11-19, v6): with the open line, the levels >= K are one draw group; its draw takes the active cell with the
    fewest dispatches over every level, set and order of the group (ties: deeper level, then earlier tick, then cell id), so every cell of
    the group is drawn once before any twice, whatever its level or its order's size; no set or order budget is counted there, and the
    within-1 check holds."""
    s, cells = _lv7_orders()
    a = (0, 1, 2, 3, 4, 5, 9)
    deep = []
    for order, t, bt in ((a + (6,), 650, B7 + (630,)), (a + (6,), 640, B7 + (630,)), (a + (6, 7), 900, B7 + (630, 850))):
        c = s.add(order, t)
        s.breaks[c.cid] = bt
        deep.append(c)
    sel = s.selector(open_line_from=7)
    check(len(sel.rot_by_level[7]) == 2 and sum(len(sel.rot_by_set[x]) for x in sel.rot_by_level[7]) == 3 and set(sel.rotation_levels()) == {7, 8, 9},
          "levels 7 (two sets, three orders), 8 and 9")
    check(sel.level_weights(list(sel.rotation_levels())) == {7: 1.0}, "one draw key for levels 7 to 9")
    picks, groups = [], []
    for n in range(12):
        c, draw = sel.select(ScriptRng([0.5, 0.0]))
        pool = [cid for lv in (7, 8, 9) for x in sel.rot_by_level[lv] for g_ in sel.rot_by_set[x] for cid in sel.members(g_)]
        exp = min(pool, key=lambda x: (sel.bcount.get(x, 0), -int(sel.group[x][0]), sel.tick_of[x], x))
        check(c.cid == exp and draw["stream"] == "fewest" and draw["scope"] == "group" and draw["draw_group_active"] == 12 and draw["draw_group_levels"] == [7, 8, 9]
              and draw["count"] == sel.bcount.get(c.cid, 0) and draw["level"] == int(c.level) and draw["group"] == rs.glabel(sel.group[c.cid])
              and draw["set"] == osel.slabel(osel.set_of(sel.group[c.cid])), f"draw {n}: {draw} (want cell {exp})")
        info = dict(sel.on_dispatch(c, draw, n))
        info.update(cid=int(c.cid), level=int(c.level))
        take(sel, info, n=n)
        picks.append((int(c.level), int(c.tick), int(c.cid)))
        groups.append(draw["group"])
    a600, b600 = cells["A"][0], cells["B"][1]
    check([(lv, t) for lv, t, _c in picks] == [(9, 900), (8, 640), (8, 650), (7, 600), (7, 600), (7, 601), (7, 605), (7, 610), (7, 620), (7, 630), (7, 640), (7, 700)],
          f"every cell once: the deeper level first, then the earlier tick: {picks}")
    check(picks[3][2] == a600.cid < b600.cid == picks[4][2], "a tick tie at one level goes to the lower cell id, across orders")
    check((picks[2][1], picks[2][0]) == (650, 8) and (picks[10][1], picks[10][0]) == (640, 7), "level before tick: level 8 at 650 before level 7 at 600")
    c, draw = sel.select(ScriptRng([0.5, 0.0]))
    check(c.cid == deep[2].cid and draw["count"] == 1, f"then the deepest again: {c.cid} {draw}")
    per_order = Counter(groups)
    check(sorted(per_order.values()) == [1, 2, 2, 2, 5], f"draws per order follow the order's size, not an equal share: {dict(per_order)}")
    check(all(v == 0 for v in sel.set_count.values()) and all(v == 0 for v in sel.order_count.values()) and sel.dstat["group_draws"] == 12
          and not sel.within_one_violations(), "no set / order budget in the group; within 1 holds")
    s4, _c4 = _lv7_orders()                              # the same cells without the open line: none eligible (all past line(8))
    check(s4.selector().select(ScriptRng([0.5, 0.0, 0.0, 0.0])) is None, "off: no cell eligible")
    return {"picks": [(lv, t) for lv, t, _c in picks], "per_order": dict(per_order)}


def unit_group_weights() -> Dict[str, Any]:
    """Ruling 1's weights: with the open line from 7 the group (levels >= 7) takes the deepest level's weight and the levels below 7 take
    the weights they take when 7 is the deepest level present, by rank among the levels present (also when level 7 itself has no active
    cell); with no active cell at a level >= 7 the weights are the levels' own; the draw frequencies follow; the option off is unchanged."""
    lw = osel.OrderParams().level_weights
    below = [((0, 1, 2), 200), ((0, 1, 2, 3), 300), ((0, 1, 2, 3, 4), 350), ((0, 1, 2, 3, 4, 5), 400)]
    a = (0, 1, 2, 3, 4, 5, 9)
    deep = [(a, 600, B7), (a + (6,), 700, B7 + (650,)), (a + (6, 7), 800, B7 + (650, 750))]

    def build(with_levels: Sequence[int], **kw: Any) -> osel.OrderSelector:
        s = Static(root=False)
        for order, t in below:
            s.add(order, t)
        for order, t, bt in deep:
            if len(order) in with_levels:
                c = s.add(order, t)
                s.breaks[c.cid] = bt
        return s.selector(**kw)

    def w(sel: osel.OrderSelector) -> Dict[int, float]:
        return {k: round(v, 9) for k, v in sel.level_weights(list(sel.rotation_levels())).items()}

    as_if_7 = {k: round(v, 9) for k, v in osel.level_draw_weights([3, 4, 5, 6, 7], lw).items()}
    check(as_if_7 == {7: 0.4, 6: 0.3, 5: 0.2, 4: 0.1}, f"today with 7 the deepest: {as_if_7}")
    full = build((7, 8, 9), open_line_from=7)
    check(set(full.rotation_levels()) == {3, 4, 5, 6, 7, 8, 9} and w(full) == as_if_7, f"levels 3 to 9, the group = level 7's place: {w(full)}")
    today = {k: round(v, 9) for k, v in osel.level_draw_weights([3, 4, 5, 6, 7, 8, 9], lw).items()}
    check(today == {9: 0.4, 8: 0.3, 7: 0.2, 6: 0.1}, f"(per-level weights for the same levels: {today})")
    no7 = build((8,), open_line_from=7)
    check(set(no7.rotation_levels()) == {3, 4, 5, 6, 8} and w(no7) == as_if_7, f"only level 8 in the group: the same weights: {w(no7)}")
    none = build((), open_line_from=7)
    own = {k: round(v, 9) for k, v in osel.level_draw_weights([3, 4, 5, 6], lw).items()}
    check(w(none) == own == {6: 0.4, 5: 0.3, 4: 0.2, 3: 0.1}, f"no group: the levels' own weights: {w(none)}")
    off = build((), )
    check(w(off) == own, "option off: unchanged")
    sel = build((7, 8, 9), open_line_from=7, breadth_share=0.0, retire_after=10 ** 6)
    rng = random.Random(3)
    got: Counter = Counter()
    N = 4000
    for n in range(N):
        c, draw = sel.select(rng)
        key = 7 if int(c.level) >= 7 else int(c.level)
        got[key] += 1
        check(abs(draw["p_level"] - as_if_7[key]) < 1e-4, f"draw {n}: p_level {draw['p_level']} for key {key}")
        info = dict(sel.on_dispatch(c, draw, n))
        info.update(cid=int(c.cid), level=int(c.level))
        take(sel, info, n=n)
    share = {k: round(got[k] / N, 3) for k in sorted(got)}
    check(all(abs(share.get(k, 0.0) - as_if_7.get(k, 0.0)) < 0.03 for k in (3, 4, 5, 6, 7)), f"draw shares follow the weights: {share}")
    return {"weights": as_if_7, "shares": share}


def unit_fall_cut_params() -> Dict[str, Any]:
    """The fall cut's parameter (owner 2026-11-19): a finite number, only with the open line's K; off keeps the record v4's (no key); on it
    is recorded as a float and changes the fingerprint."""
    check(_refused(osel.OrderParams(fall_cut_y=-1000.0).check), "refused: the cut without the open line")
    for bad in (float("nan"), float("inf"), -float("inf"), True, "-1000"):
        check(_refused(osel.OrderParams(open_line_from=7, fall_cut_y=bad).check), f"refused: Y = {bad!r}")
    for ok in (-2850.0, -1172, 0, 3000.5):
        osel.OrderParams(open_line_from=7, fall_cut_y=ok).check()
    off, k7 = osel.OrderParams(open_line_from=7), osel.OrderParams(open_line_from=7, fall_cut_y=-1172)
    check("fall_cut_y" not in off.as_record() and "fall_cut_y" not in osel.OrderParams().as_record(), "off: no key in the record")
    check(k7.as_record()["fall_cut_y"] == -1172.0 and isinstance(k7.as_record()["fall_cut_y"], float), f"on: a float {k7.as_record()}")
    fp = {osel.params_fingerprint(osel.OrderParams(open_line_from=7, fall_cut_y=y)) for y in (-1172, -2850)}
    check(len(fp) == 2 and osel.params_fingerprint(off) not in fp, "Y changes the fingerprint")
    return {"fingerprint_cut": osel.params_fingerprint(k7)[:16]}


def unit_fall_cut_rule() -> Dict[str, Any]:
    """Pace.below_cut: at levels >= K only, strictly below Y, and (v6) not grounded: a state whose resource class is G is spared, every
    other class (A2, A1, A0, X) is cut; off (no Y, or no K) never."""
    on = osel.Pace(osel.OrderParams(open_line_from=7, fall_cut_y=-1000.0))
    check(osel.GROUNDED == O.mcell.RES_GROUNDED == "G", "the grounded class is m8_rd_cells'")
    check(on.below_cut(7, -1000.001, "A0") and not on.below_cut(7, -1000.0, "A0") and not on.below_cut(7, 5000.0, "A1") and on.below_cut(9, -2000.0, "A2"),
          "levels >= K: below Y (strict)")
    check(not on.below_cut(7, -2000.0, "G") and on.below_y(7, -2000.0, ) and all(on.below_cut(8, -2000.0, r) for r in ("A2", "A1", "A0", "X")),
          "a grounded state below Y is spared; every other class is cut")
    check(not any(on.below_cut(lv, -9000.0, "A0") or on.below_y(lv, -9000.0) for lv in range(7)), "levels below K: never")
    for p in (osel.OrderParams(), osel.OrderParams(open_line_from=7)):
        check(not any(osel.Pace(p).below_cut(lv, -1e9, "A0") for lv in range(10)), f"off: never ({p.as_record()})")
    return {"cut_y": on.cut_y, "from": on.open_from}


def unit_fall_cut_selector() -> Dict[str, Any]:
    """The cut in the selector: at levels >= K a cell whose representative is below Y and not grounded is neither active nor in the breadth
    pool; a cell above Y is, and (v6) a grounded cell below Y is; levels below K are unaffected whatever their y; a representative replaced
    by one above Y becomes drawable; the cut needs each cell's y."""
    s = Static(root=False)
    order = (0, 1, 2, 3, 4, 5, 9)
    low, mid, high = (s.add(order, t) for t in (600, 610, 620))
    ground = s.add(order, 630, res="G")                  # a grounded level-7 cell below Y
    for c in (low, mid, high, ground):
        s.breaks[c.cid] = B7
    six = s.add(order[:6], 400)                          # level 6, inside v3's window by its own tick (TickArrivals)
    ys = {low.cid: -2000.0, mid.cid: 100.0, high.cid: -999.0, six.cid: -5000.0, ground.cid: -2000.0}
    p = osel.OrderParams(open_line_from=7, fall_cut_y=-1000.0)
    try:
        osel.OrderSelector(s.a, p, niches=s.niches, breaks=s.breaks)
        raise AssertionError("a cut without y_of was accepted")
    except osel.OrderParamsError:
        pass
    sel = osel.OrderSelector(s.a, p, niches=s.niches, breaks=s.breaks, y_of=lambda cid: ys[int(cid)])
    check(not sel.is_active(low.cid) and sel.is_active(mid.cid) and sel.is_active(high.cid) and sel.is_active(six.cid) and sel.is_active(ground.cid),
          "airborne below Y at level 7: not active; above Y, grounded below Y, and level 6 at any y: active")
    check(low.cid not in sel.breadth_pool() and {mid.cid, high.cid, six.cid, ground.cid} <= set(sel.breadth_pool()),
          "the breadth pool excludes the airborne cell below Y, not the grounded one")
    check(sel.cut_undrawable() == {"7": 1}, f"the readout: {sel.cut_undrawable()}")
    got: Counter = Counter()
    for n in range(12):                                  # exploitation at level 7 (r >= 3/7) and breadth (u < 0.2)
        c, draw = sel.select(ScriptRng([0.5, 0.99]) if n % 2 else ScriptRng([0.1, 0.0]))
        got[int(c.cid)] += 1
        info = dict(sel.on_dispatch(c, draw, n))
        info.update(cid=int(c.cid), level=int(c.level))
        take(sel, info, n=n)
    check(got[low.cid] == 0 and got[mid.cid] and got[high.cid] and got[ground.cid], f"never drawn airborne below Y; the grounded one is: {dict(got)}")
    v, c2, niche = kept_child(s.a, s.niches[mid.cid], [], 590, int(low.key[0]))   # low's key, an earlier tick: a replacement
    check(v == REPLACED and c2.cid == low.cid, f"the replacement: {v} {c2.cid}")
    s.breaks[low.cid] = B7
    ys[low.cid] = 50.0
    info = send(sel, mid, 12)
    take(sel, info, kept=[(v, c2, s.niches[low.cid])], n=12)
    check(sel.is_active(low.cid) and low.cid in sel.breadth_pool() and sel.cut_undrawable() == {}, "a representative above Y is drawable again")
    off = s.selector(open_line_from=7)
    check(all(off.is_active(x.cid) for x in (low, mid, high, six, ground)), "without the cut every cell is active")
    return {"draws": dict(got)}


def unit_fall_cut_plan() -> Dict[str, Any]:
    """The cut in the plan and on the command line: off, no fall-cut key (the open line's plan as before); on, the keep rule states it; run
    refuses a different Y; --fall-cut-y=-2850 and --fall-cut-y -2850 both parse; the printed run command carries it."""
    import argparse

    lab = tmpdir("order_cut_plan_")
    try:
        fr_dir = write_fake_frontier(lab, 3000)
        k7 = osel.OrderParams(slack=200, open_line_from=7)
        cut = osel.OrderParams(slack=200, open_line_from=7, fall_cut_y=-1172.0)
        ep = O.engine_params(k7, rng_seed=3)
        P7 = O.build_plan(lab, fr_dir, lab / "order_k7", k7, ep, code="test")
        PC = O.build_plan(lab, fr_dir, lab / "order_cut", cut, O.engine_params(cut, rng_seed=3), code="test")
        check(not any(k.startswith("fall_cut") for k in P7["keep_rule"]) and "fall_cut_y" not in P7["params"], f"off: no fall-cut key {list(P7['keep_rule'])}")
        kr = PC["keep_rule"]
        check(kr["fall_cut_y"] == -1172.0 and kr["fall_cut_from"] == 7 and "y < -1172" in kr["fall_cut_rule"] and kr["fall_cut_inherited_undrawable"] == {}
              and PC["params"]["fall_cut_y"] == -1172.0, f"on: the keep rule states the cut: {kr}")
        strip = lambda P: {k: v for k, v in P.items() if k not in ("utc", "out", "keep_rule", "params", "params_fingerprint")}  # noqa: E731
        check(strip(P7) == strip(PC) and {k: v for k, v in kr.items() if not k.startswith("fall_cut")} == P7["keep_rule"], "nothing else in the plan changes")
        check(O.run_flag_problems(PC, cut, O.engine_params(cut, rng_seed=3), fr_dir) is None, "the same Y runs")
        other = osel.OrderParams(slack=200, open_line_from=7, fall_cut_y=-2850.0)
        check("selection parameters differ" in (O.run_flag_problems(PC, other, O.engine_params(other, rng_seed=3), fr_dir) or "")
              and "selection parameters differ" in (O.run_flag_problems(P7, cut, O.engine_params(cut, rng_seed=3), fr_dir) or ""), "a different Y, or none, is refused")
    finally:
        cleanup(lab)
    codes = []
    for argv in (["plan", "--frontier", "x", "--rng-seed", "1", "--open-line-from", "7", "--fall-cut-y=-2850", "--lab-root", str(lab)],
                 ["plan", "--frontier", "x", "--rng-seed", "1", "--open-line-from", "7", "--fall-cut-y", "-2850", "--lab-root", str(lab)]):
        try:
            O.main(argv)
            raise AssertionError("main returned on a missing lab")
        except SystemExit as exc:
            codes.append(exc.code)
    check(all(not isinstance(c_, int) for c_ in codes), f"both forms parse (the refusal is the lab root's, not argparse's): {codes}")
    a = argparse.Namespace(rng_seed=1, workers=3, max_ticks=10, max_wall_min=30.0, summary_every_s=60.0, max_cells=O.C.Params3.max_cells, max_dispatches=0,
                           min_commit_free_mb=None, override_reason="", goal=480, slack=200, open_line_from=7, fall_cut_y=-2850.0, hitter_record=True, resume_from=[])
    cmd = O.run_command(Path("C:/lab"), Path("C:/lab/f"), Path("C:/lab/order_x"), a)
    check(" --open-line-from 7 --fall-cut-y=-2850.0 --hitter-record" in cmd, f"the run command: {cmd}")
    return {"cmd_tail": cmd[-80:]}


# -- v7 (owner 2026-11-20): the record bound, the one-live-target exemption, the floor-direction key -------------------------------------------

V7_KEYS = ("record_bound", "fall_cut_spare_one_live", "floor_direction_key")


def unit_v7_params() -> Dict[str, Any]:
    """The v7 options: the record bound B is an integer tick >= 1 and needs K; the one-live exemption needs the fall cut; the direction key
    is on or off; off, none of them is in the parameter record (v6's record exactly); each one on changes the fingerprint."""
    for bad in ({"record_bound": 900}, {"open_line_from": 7, "record_bound": 0}, {"open_line_from": 7, "record_bound": 900.0},
                {"open_line_from": 7, "record_bound": True}, {"open_line_from": 7, "fall_cut_spare_one_live": True},
                {"open_line_from": 7, "fall_cut_y": -2700.0, "fall_cut_spare_one_live": 1}, {"floor_direction_key": 1}, {"floor_direction_key": "on"}):
        check(_refused(osel.OrderParams(**bad).check), f"refused: {bad}")
    base = {"slack": 200, "open_line_from": 7, "fall_cut_y": -2700.0}
    for p in (osel.OrderParams(), osel.OrderParams(**base)):
        check(not set(V7_KEYS) & set(p.as_record()), f"off: no v7 key in the record {sorted(p.as_record())}")
    ons = [osel.OrderParams(**dict(base, record_bound=900)), osel.OrderParams(**dict(base, fall_cut_spare_one_live=True)),
           osel.OrderParams(**dict(base, floor_direction_key=True))]
    for p, k in zip(ons, V7_KEYS):
        rec = p.as_record()
        check(set(rec) - set(osel.OrderParams(**base).as_record()) == {k}, f"on: only {k} is added: {rec}")
    check(ons[0].as_record()["record_bound"] == 900 and ons[1].as_record()["fall_cut_spare_one_live"] is True
          and ons[2].as_record()["floor_direction_key"] is True, "the values as given")
    fps = {osel.params_fingerprint(p) for p in ons} | {osel.params_fingerprint(osel.OrderParams(**base))}
    check(len(fps) == 4 and osel.params_fingerprint(osel.OrderParams(**dict(base, record_bound=901))) not in fps, "each option changes the fingerprint")
    return {"fingerprints": sorted(f[:12] for f in fps)}


def _bt(level: int, arrival: int, tick: int) -> List[int]:
    return [min(int(arrival), int(tick))] * int(level)


def unit_record_bound_rule() -> Dict[str, Any]:
    """Pace.past_bound: at levels >= K only, own tick >= B (B itself is past); Pace.continues: the arrival rule (with the open line) and not
    past B; with the bound off, continues is keeps_ticks on every state of a grid (the continuation is v6's)."""
    on = osel.Pace(osel.OrderParams(slack=200, open_line_from=7, record_bound=900))
    check(on.past_bound(7, 900) and on.past_bound(9, 3000) and not on.past_bound(7, 899) and not any(on.past_bound(lv, 5000) for lv in range(7)),
          "levels >= K, tick >= B")
    bt7 = [10, 20, 30, 40, 50, 60, 500]                  # 7th break by line(7) = 536 (slack 200): opened
    check(on.keeps_ticks(7, 950, bt7) and not on.continues(7, 950, bt7) and on.continues(7, 899, bt7) and on.keeps_ticks(7, 899, bt7),
          "a level-7 state inside the open line stops at a boundary past B, not before")
    n = 0
    for p in (osel.OrderParams(), osel.OrderParams(slack=200, open_line_from=7), osel.OrderParams(slack=200, open_line_from=7, fall_cut_y=-2700.0),
              osel.OrderParams(slack=200, open_line_from=7, fall_cut_y=-2700.0, fall_cut_spare_one_live=True, floor_direction_key=True)):
        pc = osel.Pace(p)
        for lv in range(10):
            for tick in (0, 100, 300, 536, 600, 899, 900, 901, 1500, 3600):
                for arr in (5, 200, 536, 537, 900):
                    bt = _bt(lv, arr, tick)
                    check(pc.continues(lv, tick, bt) == pc.keeps_ticks(lv, tick, bt), f"bound off: continues == keeps_ticks ({p.as_record()}, {lv}, {tick}, {arr})")
                    check(not pc.past_bound(lv, tick), "bound off: never past")
                    n += 1
    return {"grid_states": n}


def unit_record_bound_selector() -> Dict[str, Any]:
    """The bound in the selector: at levels >= K a cell whose own tick is >= B is neither active nor in the breadth pool, one below B is;
    levels below K are unaffected; the readout counts per level; a representative replaced by an earlier one below B is drawable again."""
    s = Static(root=False)
    order = (0, 1, 2, 3, 4, 5, 9)
    early, at_b, late = (s.add(order, t) for t in (600, 900, 1200))
    for c in (early, at_b, late):
        s.breaks[c.cid] = B7
    six = s.add(order[:6], 400)
    sel = s.selector(open_line_from=7, record_bound=900)
    check(sel.is_active(early.cid) and not sel.is_active(at_b.cid) and not sel.is_active(late.cid) and sel.is_active(six.cid),
          "tick >= B at level 7: not active; below B, and level 6: active")
    check(early.cid in sel.breadth_pool() and not {at_b.cid, late.cid} & set(sel.breadth_pool()), "the breadth pool excludes them")
    check(sel.bound_undrawable() == {"7": 2}, f"the readout: {sel.bound_undrawable()}")
    got: Counter = Counter()
    for n in range(12):
        c, draw = sel.select(ScriptRng([0.5, 0.99]) if n % 2 else ScriptRng([0.1, 0.0]))
        got[int(c.cid)] += 1
        info = dict(sel.on_dispatch(c, draw, n))
        info.update(cid=int(c.cid), level=int(c.level))
        take(sel, info, n=n)
    check(not got[at_b.cid] and not got[late.cid] and got[early.cid], f"never drawn past B: {dict(got)}")
    v, c2, _niche = kept_child(s.a, s.niches[early.cid], [], 650, int(late.key[0]))   # late's key, an earlier tick below B: a replacement
    check(v == REPLACED and c2.cid == late.cid, f"the replacement: {v} {c2.cid}")
    s.breaks[late.cid] = B7
    info = send(sel, early, 12)
    take(sel, info, kept=[(v, c2, s.niches[late.cid])], n=12)
    check(sel.is_active(late.cid) and late.cid in sel.breadth_pool() and sel.bound_undrawable() == {"7": 1}, "a representative below B is drawable again")
    off = s.selector(open_line_from=7)
    check(all(off.is_active(x.cid) for x in (early, at_b, late, six)) and off.bound_undrawable() == {}, "without the bound every cell is active")
    return {"draws": dict(got)}


def unit_one_live_rule() -> Dict[str, Any]:
    """The one-live-target exemption: with it on, Pace.below_cut spares a level-9 state below Y whatever its class, and still cuts levels
    7 and 8; off (or without the cut) v6's answers; in the selector an airborne level-9 cell below Y is drawable with it on, a level-8 one is
    not, and neither is without it."""
    on = osel.Pace(osel.OrderParams(open_line_from=7, fall_cut_y=-1000.0, fall_cut_spare_one_live=True))
    off = osel.Pace(osel.OrderParams(open_line_from=7, fall_cut_y=-1000.0))
    air = ("A2", "A1", "A0", "X")
    check(not any(on.below_cut(9, -2000.0, r) for r in air) and all(on.below_cut(lv, -2000.0, r) for lv in (7, 8) for r in air),
          "on: level 9 spared, levels 7 and 8 cut")
    check(all(off.below_cut(9, -2000.0, r) for r in air) and on.one_live(9) and not on.one_live(8) and not off.one_live(9), "off: v6's cut")
    check(all(on.below_cut(lv, y, r) == off.below_cut(lv, y, r) for lv in range(9) for y in (-5000.0, -1000.0, 0.0) for r in air + ("G",)),
          "below level 9 the two agree everywhere")
    s = Static(root=False)
    order9 = (0, 1, 2, 3, 4, 5, 9, 6, 7)
    c9, c8 = s.add(order9, 700), s.add(order9[:8], 690)
    s.breaks[c9.cid] = B7 + (600, 650)
    s.breaks[c8.cid] = B7 + (600,)
    ys = {c9.cid: -2000.0, c8.cid: -2000.0}
    mk = lambda **kw: osel.OrderSelector(s.a, osel.OrderParams(open_line_from=7, fall_cut_y=-1000.0, **kw), niches=s.niches, breaks=s.breaks,  # noqa: E731
                                         y_of=lambda cid: ys[int(cid)])
    sel_on, sel_off = mk(fall_cut_spare_one_live=True), mk()
    check(sel_on.is_active(c9.cid) and not sel_on.is_active(c8.cid) and c9.cid in sel_on.breadth_pool() and sel_on.cut_undrawable() == {"8": 1},
          f"on: the level-9 cell is drawable, the level-8 one is not: {sel_on.cut_undrawable()}")
    check(not sel_off.is_active(c9.cid) and not sel_off.is_active(c8.cid) and sel_off.cut_undrawable() == {"9": 1, "8": 1}, f"off: {sel_off.cut_undrawable()}")
    return {"on": sel_on.cut_undrawable(), "off": sel_off.cut_undrawable()}


def unit_direction_key() -> Dict[str, Any]:
    """The floor-direction key: the moving floor lines are the stage table's floor lines of the platform's group (line 19); the platform
    moves down exactly on the residues 90 ... 239 of its 300-tick period; two states on a moving floor at the same position with opposite
    directions get different keys, with the same direction the same key; other floors, airborne states and the option off keep today's key;
    re-keying is deterministic and idempotent; off reads an encoded floor field back as the line id."""
    import m7g_spatial as msp

    check(O.MOVING_FLOOR_LINES == (19,) and all(ln[2] == msp.PLATFORM_GROUP for ln in msp.EXPECTED_LINES if ln[0] in O.MOVING_FLOOR_LINES),
          f"the moving floor lines: {O.MOVING_FLOOR_LINES}")
    check([O.platform_direction(t) for t in range(300)] == ["up"] * 90 + ["down"] * 150 + ["up"] * 60, "down exactly on residues 90 ... 239")
    check(all(O.platform_direction(t) == O.platform_direction(t + 300 * m) for t in range(300) for m in (1, 2, 11)), "period 300")
    k = (9, 8, "G", 0b0000000010, 19)
    up, down = O.direction_key(k, 300, True), O.direction_key(k, 150, True)
    check(up != down and up[:4] == down[:4] == k[:4] and (up[4], down[4]) == (1019, 2019), f"opposite directions, different keys: {up} {down}")
    check(O.direction_key(k, 60, True) == up and O.direction_key(k, 239, True) == down, "the same direction, the same key")
    check(O.direction_key(up, 300, True) == up and O.direction_key(down, 150, True) == down and O.direction_key(up, 150, True) == down,
          "idempotent; an encoded key re-keyed from its tick")
    check(O.direction_key(k, 150, False) == k and O.direction_key(down, 150, False) == k and O.plain_floor(2019) == 19 and O.plain_floor(-1) == -1,
          "off: today's key, an encoded field read back")
    for other in ((9, 8, "G", 2, 4), (9, 8, "G", 2, 0), (9, 8, "A1", 2, -1), (9, 8, "X", 2, -1), (9, 8, "A0", 2, 19)):
        check(O.direction_key(other, 150, True) == other and O.direction_key(other, 150, False) == other, f"unchanged: {other}")
    check(O.direction_key(list(k), 150, True) == down and isinstance(O.direction_key(list(k), 150, True), tuple), "a list key: the same tuple")
    rnd = random.Random(5)
    keys = [(rnd.randint(-20, 20), rnd.randint(-12, 15), rnd.choice(("G", "A2", "A1", "A0", "X")), rnd.randint(0, 1023), rnd.choice((-1, 0, 4, 19)))
            for _ in range(2000)]
    ticks = [rnd.randint(0, 3600) for _ in keys]
    first = [O.direction_key(kk, t, True) for kk, t in zip(keys, ticks)]
    check(first == [O.direction_key(kk, t, True) for kk, t in zip(keys, ticks)] == [O.direction_key(f, t, True) for f, t in zip(first, ticks)],
          "deterministic and idempotent over 2,000 keys")
    rec = O.direction_key_record()
    check(rec["lines"] == [19] and rec["period"] == 300 and rec["down_residues"] == [90, 239] and "five-field" in rec["limit"], f"the record: {rec}")
    return {"up": list(up), "down": list(down), "encoded": sum(1 for f in first if int(f[4]) >= 1000)}


def unit_v7_plan() -> Dict[str, Any]:
    """The v7 options in the plan and on the command line: off, no v7 key and today's continuation text (the plan as before); on, the keep
    rule states the bound, the exemption and the direction key's definition, and the continuation text states the stop; run refuses a
    different B and a missing option; the printed run command carries the flags."""
    import argparse

    lab = tmpdir("order_v7_plan_")
    try:
        fr_dir = write_fake_frontier(lab, 3000)
        base = osel.OrderParams(slack=200, open_line_from=7, fall_cut_y=-1172.0)
        allv = osel.OrderParams(slack=200, open_line_from=7, fall_cut_y=-1172.0, fall_cut_spare_one_live=True, record_bound=900, floor_direction_key=True)
        PB = O.build_plan(lab, fr_dir, lab / "order_v6like", base, O.engine_params(base, rng_seed=3), code="test")
        PA = O.build_plan(lab, fr_dir, lab / "order_v7all", allv, O.engine_params(allv, rng_seed=3), code="test")
        v7kr = ("record_bound", "record_bound_from", "record_bound_rule", "record_bound_inherited_undrawable", "fall_cut_one_live",
                "fall_cut_inherited_one_live_spared", "floor_direction_key")
        check(not set(v7kr) & set(PB["keep_rule"]) and PB["continuation"] == O.CONT_RULE and not set(V7_KEYS) & set(PB["params"]),
              f"off: no v7 key, today's continuation {list(PB['keep_rule'])}")
        kr = PA["keep_rule"]
        check(kr["record_bound"] == 900 and kr["record_bound_from"] == 7 and "900 or later" in kr["record_bound_rule"] and kr["record_bound_inherited_undrawable"] == {}
              and "one live target" in kr["fall_cut_one_live"] and kr["fall_cut_inherited_one_live_spared"] == {} and kr["floor_direction_key"] == O.direction_key_record(),
              f"on: the keep rule states them: {kr}")
        check(PA["continuation"].startswith(O.CONT_RULE) and "record bound 900" in PA["continuation"], f"the continuation text: {PA['continuation'][-160:]}")
        strip = lambda P: {k: v for k, v in P.items() if k not in ("utc", "out", "keep_rule", "params", "params_fingerprint", "continuation")}  # noqa: E731
        check(strip(PB) == strip(PA) and {k: v for k, v in kr.items() if k not in v7kr} == PB["keep_rule"], "nothing else in the plan changes")
        check(O.run_flag_problems(PA, allv, O.engine_params(allv, rng_seed=3), fr_dir) is None, "the same options run")
        for other in (osel.OrderParams(slack=200, open_line_from=7, fall_cut_y=-1172.0, fall_cut_spare_one_live=True, record_bound=901, floor_direction_key=True),
                      osel.OrderParams(slack=200, open_line_from=7, fall_cut_y=-1172.0, fall_cut_spare_one_live=True, record_bound=900), base):
            check("selection parameters differ" in (O.run_flag_problems(PA, other, O.engine_params(other, rng_seed=3), fr_dir) or ""), f"refused: {other.as_record()}")
    finally:
        cleanup(lab)
    a = argparse.Namespace(rng_seed=1, workers=3, max_ticks=10, max_wall_min=30.0, summary_every_s=60.0, max_cells=O.C.Params3.max_cells, max_dispatches=0,
                           min_commit_free_mb=None, override_reason="", goal=480, slack=200, open_line_from=7, fall_cut_y=-2700.0, hitter_record=True, resume_from=[],
                           fall_cut_spare_one_live=True, record_bound=900, floor_direction_key=True, level_weights="", breadth_share=0.2, retire_after=300)
    cmd = O.run_command(Path("C:/lab"), Path("C:/lab/f"), Path("C:/lab/order_x"), a)
    check(" --fall-cut-y=-2700.0 --fall-cut-spare-one-live --record-bound 900 --floor-direction-key --hitter-record" in cmd, f"the run command: {cmd}")
    check(O.order_params_from_args(a) == osel.OrderParams(slack=200, open_line_from=7, fall_cut_y=-2700.0, fall_cut_spare_one_live=True, record_bound=900,
                                                          floor_direction_key=True), "the flags make the parameters")
    return {"cmd_tail": cmd[-110:]}


def unit_break_record() -> Dict[str, Any]:
    """E1: one entry per credited break (after the start tick), in break order, with the level it gave, Mario's position and the reach's
    fields at the break tick; None without a reach; prefix breaks are not credited; the job result is not changed."""
    import copy
    obs = lambda x, y, t: tuple([1, 99, t, t, 2, 1, 7, 1, float(x), float(y), 1.5, -2.0, 0.0, 1, 1, 18, 1])  # noqa: E731
    res = {"L": 100, "breaks_all": [(50, 3), (130, 5), (120, 1), (130, 2), (140, 9)],
           "reaches": [(110, (1, 2, "A1", 1000, -1), obs(10, 20, 110), b"\x01" * 32, b"\x02" * 32, False),
                       (120, (3, 4, "A1", 998, -1), obs(-300, 400, 120), b"\x03" * 32, b"\x04" * 32, False),
                       (130, (5, 6, "G", 974, 4), obs(-1650, 1200, 130), b"\x05" * 32, b"\x06" * 32, False)]}
    before = copy.deepcopy(res)
    br = O.break_record(res)
    check([(e["tick"], e["target"], e["level"]) for e in br] == [(120, 1, 2), (130, 2, 3), (130, 5, 4), (140, 9, 5)],
          f"credited breaks only, in break order, with the level: {[(e['tick'], e['target'], e['level']) for e in br]}")
    check(br[0]["x"] == -300.0 and br[0]["y"] == 400.0 and br[0]["obs"]["position_x"] == -300.0 and br[0]["key"] == [3, 4, "A1", 998, -1]
          and br[0]["record_digest"] == "03" * 32 and br[0]["chain"] == "04" * 32 and br[0]["terminal"] is False and len(br[0]["obs"]) == 17,
          f"the reach's fields at the break tick: {br[0]}")
    check(br[1]["x"] == br[2]["x"] == -1650.0 and br[1]["key"][4] == 4, "a same-tick pair shares the tick's reach")
    check(br[3] == {"tick": 140, "target": 9, "level": 5, "reach": None}, f"no reach at the break tick: {br[3]}")
    check(res == before and O.break_record({"L": 200, "breaks_all": res["breaks_all"], "reaches": res["reaches"]}) == [], "the result is unchanged; nothing after 200")
    return {"entries": len(br)}


# -- the hitter record (owner 2026-11-19; report-only) ------------------------------------------------------------------------------------


def _ent(hitlag: int = 0, weapons: Sequence[Tuple[int, int, int, int, int]] = (), live: int = 1, anomaly: int = 0, attack: int = 0, tick: int = 0) -> Dict[str, Any]:
    """A btt_entity_v1 object (weapons: (serial, kind, owned, attack_state, lifetime))."""
    return {"contract": "btt_entity_v1", "entity_schema": 1, "input_tick": tick, "scene_active": 1, "live": live, "anomaly_flags": anomaly,
            "fighter": {"valid": 1, "status_total_tics": 0, "hitlag_tics": hitlag, "jumps_max": 2, "attack_active": attack, "cliff_hold": 0,
                        "shield_active": 0, "fastfall": 0, "hitstun": 0},
            "weapon_total": len(weapons),
            "weapons": [{"serial": s, "kind": k, "owned": o, "lr": 1, "ga": 1, "lifetime": lt, "attack_state": a, "translate": [0.0, 0.0],
                         "velocity": [0.0, 0.0]} for s, k, o, a, lt in weapons]}


def _rep(tick: int, mask: int, entity: Optional[Mapping[str, Any]] = None, status: int = 10) -> Dict[str, Any]:
    """A reply with what the tracker reads: ok, the input tick, the status id, the live mask (and the entity object, when given)."""
    r: Dict[str, Any] = {"ok": True, "op": "step" if tick else "observe", "observation": {"input_tick": tick, "fighter_status_id": status},
                         "spatial": {"target_live_mask": mask}}
    if entity is not None:
        r["entity"] = entity
    return r


def unit_hitter_rule() -> Dict[str, Any]:
    """The hitter rule (order_worker.HITTER_RULE) on constructed pairs of entity objects: every kind, its fields and candidates; only zero
    tests and set membership (the attack flag alone is not a hit)."""
    def snap(**k: Any) -> Optional[Dict[str, Any]]:
        return OW.snapshot(_rep(1, 1023, _ent(**k)))

    first = {3: 40, 4: 55}
    fb, other = (3, 0, 1, 3, 58), (4, 0, 0, 3, 90)       # serial 3: the player's fireball; serial 4: another owner's weapon
    m = OW.classify(100, [2], snap(), snap(hitlag=5, attack=1), first)
    check(m["kind"] == "mario" and m["serial"] is None and m["evidence"]["hitlag"] == [0, 5] and m["targets"] == [2], f"a hitlag onset, nothing vanished: {m}")
    p = OW.classify(100, [2], snap(weapons=[fb]), snap(), first)
    check(p["kind"] == "projectile" and (p["serial"], p["owner"], p["first_tick"], p["weapon_kind"]) == (3, "mario", 40, 0)
          and p["evidence"]["vanished"][0]["attack_state"] == 3 and p["evidence"]["vanished"][0]["lifetime"] == 58, f"one weapon vanished: {p}")
    po = OW.classify(100, [2], snap(weapons=[fb, other]), snap(weapons=[fb]), first)
    check(po["kind"] == "projectile" and (po["serial"], po["owner"], po["first_tick"]) == (4, "other", 55), f"the one that vanished, with its owner: {po}")
    check(OW.classify(100, [2], snap(weapons=[fb]), snap(weapons=[fb]), first)["kind"] == "unseen", "no onset, nothing vanished: unseen")
    check(OW.classify(100, [2], snap(), snap(attack=1), first)["kind"] == "unseen", "the attack flag without a hitlag onset is not a hit")
    a1 = OW.classify(100, [2], snap(weapons=[fb]), snap(hitlag=5), first)
    a2 = OW.classify(100, [2], snap(weapons=[fb, other]), snap(), first)
    a3 = OW.classify(100, [2], snap(hitlag=4), snap(hitlag=3), first)
    check(a1["kind"] == a2["kind"] == a3["kind"] == "ambiguous" and [c["kind"] for c in a1["candidates"]] == ["mario", "projectile"]
          and [c["serial"] for c in a2["candidates"]] == [3, 4] and a1["serial"] is None and a3["why"] == "hitlag already running at j - 1",
          f"ambiguous: {a1['candidates']} {a2['candidates']} {a3['why']}")
    for prev, cur, why in ((None, snap(), "no entity object at j - 1"), (snap(), None, "no entity object at j"),
                           (snap(live=0), snap(), "entity not live at j - 1"), (snap(), snap(anomaly=1), "entity anomaly flags 0x1 at j")):
        u = OW.classify(100, [2], prev, cur, first)
        check(u["kind"] == "unavailable" and u["why"] == why and u["evidence"] is None, f"unavailable: {u}")
    bad = OW.snapshot({"entity": {"live": 1}})
    check(bad is not None and "error" in bad and OW.classify(100, [2], snap(), bad, first)["kind"] == "unavailable", f"a malformed object: {bad}")
    check(OW.classify(100, [2], snap(weapons=[(0, 0, 1, 3, 9)]), snap(), first)["first_tick"] is None, "serial 0 (the block's overflow value): no first tick")
    check(set(OW.KINDS) == {"mario", "projectile", "unseen", "ambiguous", "unavailable"}, f"the kinds: {OW.KINDS}")
    return {"kinds": list(OW.KINDS)}


class _FakeProc:
    def __init__(self, replies: Sequence[Any]):
        self.replies, self.failed = list(replies), False

    def observe(self) -> Any:
        return self.replies.pop(0)

    def step(self, b: int, x: int, y: int) -> Any:
        return self.replies.pop(0)

    def close(self) -> str:
        return "closed"


def unit_hitter_tracker() -> Dict[str, Any]:
    """The tracker follows the worker's break rule (a bit leaving the live mask, several targets on one tick), keeps each serial's first
    tick and never raises; the proxy hands every reply on without the entity object (so run 3's D6 check and detectors see an entity-off
    reply), refuses a tick-0 observe without one, passes an error reply through, and forwards attributes to the real process."""
    import types

    import run3_anomaly as ra

    m0 = 1023
    m1 = m0 & ~(1 << 4)
    m2 = m1 & ~(1 << 7) & ~(1 << 8)
    m3 = m2 & ~(1 << 9)
    tr = OW.HitterTracker()
    for r in (_rep(0, m0, _ent()), _rep(1, m0, _ent(weapons=[(1, 0, 1, 3, 60)])), _rep(2, m0, _ent(weapons=[(1, 0, 1, 3, 59)])),
              _rep(3, m1, _ent()),                                            # serial 1 gone with target 4
              _rep(4, m2, _ent(hitlag=6, attack=1)),                          # targets 7 and 8 on one tick, a hitlag onset
              {"ok": False, "op": "step", "error": "x"}, "not a reply",         # ignored / one counted error, never raised
              _rep(5, m2, None), _rep(6, m3, None)):                          # target 9 with no entity object
        tr.feed(r)
    res = tr.result()
    ev = res["events"]
    check([(e["tick"], e["targets"], e["kind"]) for e in ev] == [(3, [4], "projectile"), (4, [7, 8], "mario"), (6, [9], "unavailable")],
          f"the break ticks and kinds: {[(e['tick'], e['targets'], e['kind']) for e in ev]}")
    check(ev[0]["serial"] == 1 and ev[0]["first_tick"] == 1 and len(res["errors"]) == 1 and res["replies"] == 7, f"first tick, errors, replies: {ev[0]} {res}")
    e1 = _ent(weapons=[(1, 0, 1, 3, 9)])
    e1["weapons"][0]["velocity"] = [None, 0.0]                                 # what the transport sends for a NaN
    inner = _FakeProc([_rep(0, m0, _ent()), _rep(1, m0, e1)])
    hb = OW.HitterBackend(types.SimpleNamespace(acquire=lambda: inner, info=lambda: {"pid": 1}))
    proc = hb.acquire()
    hb.tracker = OW.HitterTracker()
    r0, r1 = proc.observe(), proc.step(0, 0, 0)
    check("entity" not in r0 and "entity" not in r1 and r1["spatial"] == {"target_live_mask": m0} and hb.tracker.replies == 2 and hb.tracker.first == {1: 1},
          "the replies go on without the entity object; the tracker saw both")
    check(ra.nonfinite_fields(r1) == [], "a null in the entity object never reaches run 3's D6 check")
    proc.failed = True
    check(inner.failed is True and proc.close() == "closed" and hb.info() == {"pid": 1}, "attributes reach the real process and backend")
    hb2 = OW.HitterBackend(types.SimpleNamespace(acquire=lambda: _FakeProc([_rep(0, m0, None)])))
    try:
        hb2.acquire().observe()
        missing = False
    except OW.EntityMissing:
        missing = True
    check(missing, "a tick-0 observe without the entity object is refused (the flag did not reach the process)")
    err = {"ok": False, "op": "observe", "error": "no_observation"}
    check(OW.HitterBackend(types.SimpleNamespace(acquire=lambda: _FakeProc([err]))).acquire().observe() is err, "an error reply passes through unchanged")
    base = {"rank": 0, "flags": {"SSB64_RL_SPATIAL": "1"}}
    s = OW.hitter_spec(base)
    check(s["flags"] == {"SSB64_RL_SPATIAL": "1", "SSB64_RL_ENTITY": "1"} and s[OW.SPEC_KEY] is True and base == {"rank": 0, "flags": {"SSB64_RL_SPATIAL": "1"}},
          f"the spec gains the entity flag, the given one is unchanged: {s}")
    return {"events": len(ev)}


def unit_hitter_break_record() -> Dict[str, Any]:
    """With the option every credited break entry gains HITTER_FIELDS (the worker's event for its tick and target, "unavailable" when the
    result holds none) and keeps every E1 field; without it the entries are E1's exactly (d_hitters ignored)."""
    obs = lambda x, y, t: tuple([1, 99, t, t, 2, 1, 7, 1, float(x), float(y), 1.5, -2.0, 0.0, 1, 1, 18, 1])  # noqa: E731
    ev = lambda t, tg, kind, **k: dict({"tick": t, "targets": tg, "kind": kind, "serial": None, "owner": None, "first_tick": None, "weapon_kind": None,  # noqa: E731
                                        "candidates": [], "why": None, "evidence": {"hitlag": [0, 0]}}, **k)
    res = {"L": 100, "breaks_all": [(50, 3), (130, 5), (120, 1), (130, 2), (140, 9)],
           "reaches": [(120, (3, 4, "A1", 998, -1), obs(-300, 400, 120), b"\x03" * 32, b"\x04" * 32, False),
                       (130, (5, 6, "G", 974, 4), obs(-1650, 1200, 130), b"\x05" * 32, b"\x06" * 32, False)],
           "d_hitters": {"contract": OW.HITTER_CONTRACT, "events": [ev(50, [3], "mario"), ev(120, [1], "projectile", serial=2, owner="mario", first_tick=90, weapon_kind=0),
                                                                   ev(130, [2, 5], "mario")], "replies": 141, "errors": []}}
    off = O.break_record(res)
    on = O.break_record(res, True)
    check(off == O.break_record({k: v for k, v in res.items() if k != "d_hitters"}) and not any(set(O.HITTER_FIELDS) & set(e) for e in off),
          "off: E1's entries exactly")
    check([{k: v for k, v in e.items() if k not in O.HITTER_FIELDS} for e in on] == off and all(set(O.HITTER_FIELDS) <= set(e) for e in on),
          "on: every E1 field unchanged, every hitter field present")
    check((on[0]["hitter"], on[0]["hitter_serial"], on[0]["hitter_owner"], on[0]["hitter_first_tick"], on[0]["hitter_weapon_kind"]) == ("projectile", 2, "mario", 90, 0),
          f"a projectile: {on[0]}")
    check(on[1]["hitter"] == on[2]["hitter"] == "mario" and on[1]["hitter_serial"] is None, "a same-tick pair shares its tick's event")
    check(on[3]["hitter"] == "unavailable" and on[3]["hitter_why"] == O.NO_HITTER_EVENT and on[3]["hitter_evidence"] is None, f"no event: {on[3]}")
    return {"entries": len(on)}


def unit_hitter_plan() -> Dict[str, Any]:
    """The option in the plan: off, no hitter_record key (the plan is v4's); on, this code's record and nothing else changes; run refuses
    a different flag either way, and a plan holding another hitter contract."""
    lab = tmpdir("order_hitter_plan_")
    try:
        fr_dir = write_fake_frontier(lab, 3000)
        dp = osel.OrderParams()
        ep = O.engine_params(dp, rng_seed=3)
        off = O.build_plan(lab, fr_dir, lab / "order_off", dp, ep, code="test")
        on = O.build_plan(lab, fr_dir, lab / "order_on", dp, ep, code="test", hitter_record=True)
        strip = lambda P: {k: v for k, v in P.items() if k not in ("utc", "out", "hitter_record")}  # noqa: E731
        check("hitter_record" not in off and on["hitter_record"] == O.hitter_plan_record() and strip(on) == strip(off), "the record only with the option")
        check(on["hitter_record"]["search_flags_added"] == {"SSB64_RL_ENTITY": "1"} and on["hitter_record"]["fields"] == list(O.HITTER_FIELDS), f"{on['hitter_record']}")
        check(O.run_flag_problems(off, dp, ep, fr_dir) is None and O.run_flag_problems(on, dp, ep, fr_dir, None, True) is None, "the same flag runs")
        check("--hitter-record" in (O.run_flag_problems(off, dp, ep, fr_dir, None, True) or "") and "--hitter-record" in (O.run_flag_problems(on, dp, ep, fr_dir) or ""),
              "a different flag is refused")
        other = dict(on, hitter_record=dict(on["hitter_record"], contract="order_hitter_v0"))
        check(O.run_flag_problems(other, dp, ep, fr_dir, None, True) is not None, "another hitter contract is refused")
        return {"plan_keys_on": len(on), "plan_keys_off": len(off)}
    finally:
        cleanup(lab)


def fake_hitter_class(tick: int, lost: int) -> int:
    """The synthetic hitter of a break tick (tests only): (tick + its lowest broken target) % 4 -> 0 mario, 1 projectile, 2 unseen, 3 both."""
    return (int(tick) + min(b for b in range(osel.TARGETS_TOTAL) if lost >> b & 1)) % 4


class FakeEntityProc:
    """A fake-game process whose ok observe / step replies gain a synthetic btt_entity_v1 object, a pure function of the replies' live
    masks: one live weapon (serial 1 from tick 0); at a break tick of class 0 or 3 the fighter's hitlag is 5 on that tick only; at class 1
    or 3 the live weapon is gone and the next serial appears on the same tick. Tests only (the fake game has no entity object)."""

    def __init__(self, proc: Any):
        object.__setattr__(self, "_proc", proc)
        object.__setattr__(self, "_st", {"mask": None, "serial": 1})

    def _add(self, reply: Any) -> Any:
        if not isinstance(reply, dict) or reply.get("ok") is not True or not isinstance(reply.get("observation"), dict) or not isinstance(reply.get("spatial"), dict):
            return reply
        st = self._st
        j, m = int(reply["observation"]["input_tick"]), int(reply["spatial"]["target_live_mask"])
        lost = 0 if st["mask"] is None else st["mask"] & ~m
        hitlag = 0
        if lost:
            c = fake_hitter_class(j, lost)
            hitlag = 5 if c in (0, 3) else 0
            st["serial"] += int(c in (1, 3))
        st["mask"] = m
        return dict(reply, entity=_ent(hitlag=hitlag, attack=int(hitlag > 0), weapons=[(st["serial"], 0, 1, 1, 100)], tick=j))

    def observe(self) -> Any:
        return self._add(self._proc.observe())

    def step(self, b: int, x: int, y: int) -> Any:
        return self._add(self._proc.step(b, x, y))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._proc, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._proc, name, value)


class FakeEntityBackend:
    """rl/m8_rd_worker.RealBackend on the fake game, its processes wrapped in FakeEntityProc when the spec's flags hold SSB64_RL_ENTITY=1
    (worker spec "backend": "order_search_tests:FakeEntityBackend"). Tests only."""

    def __init__(self, spec: Mapping[str, Any]):
        import m8_rd_worker as mw

        self._base = mw.RealBackend(spec)
        self._on = (spec.get("flags") or {}).get("SSB64_RL_ENTITY") == "1"

    def acquire(self, *a: Any, **k: Any) -> Any:
        p = self._base.acquire(*a, **k)
        return FakeEntityProc(p) if self._on else p

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)


def expected_fake_kind(tick: int, breaks: Mapping[int, int]) -> str:
    """The kind FakeEntityProc gives the break tick `tick` ({tick: lost mask} of the whole trajectory from tick 0): ambiguous when the
    tick before was a hitlag tick (class 0 or 3), else by its own class."""
    prev = breaks.get(int(tick) - 1)
    if prev is not None and fake_hitter_class(int(tick) - 1, prev) in (0, 3):
        return "ambiguous"
    return ("mario", "projectile", "unseen", "ambiguous")[fake_hitter_class(int(tick), breaks[int(tick)])]


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
    if a.get("dir_lines") is not None:                 # v7 tests only: a fake-world floor stands in for the moving floor (none in the fake game)
        O.MOVING_FLOOR_LINES = tuple(int(x) for x in a["dir_lines"])
    dp = osel.OrderParams(**(a.get("order") or {}))
    ep = O.engine_params(dp, **a["engine"])
    opened: List[str] = []
    if a.get("audit"):
        def hook(ev: str, args: Any) -> None:
            if ev == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
                opened.append(os.fsdecode(args[0]))
        sys.addaudithook(hook)
    plan = O.plan_and_write(lab, frontier, out, dp, ep, resume=[Path(x) for x in a.get("resume") or []], hitter_record=bool(a.get("hitter")))
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
            s = dict(r3t.worker_spec(lab, fk, rank, int(a["port_base"]), run_dir / "failures", flags), guard=g.LabGuard.spec(), run3_selfcheck=True)
            if a.get("fake_entity"):                   # the hitter record's tests: the fake game's replies gain a synthetic entity object
                s["backend"] = "order_search_tests:FakeEntityBackend"
            return s

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
    res = {"code": rc, "violations": g.LabGuard.violations[:3], "plan": {k: plan[k] for k in ("sources", "archive_id", "claim_threshold", "code", "resume", "pace")}}
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
                        "deep": read_jsonl(d / "deep_reaches.jsonl"), "report": (d / "report.md").read_text(encoding="utf-8") if (d / "report.md").is_file() else "",
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

    def inside(c: Mapping[str, Any]) -> bool:
        lv = int(c["level"])
        bt = sorted(int(t) for t, _i in (c["origin"].get("d_breaks") or []))
        if len(bt) != lv:
            return False
        a = bt[-1] if lv else 0
        return a <= int(lines[str(lv)]) and int(c["tick"]) <= int(lines[str(lv + 1)])

    check(kept and all(inside(c) for c in kept), "every kept cell records its break ticks and is inside the arrival rule (arrival <= line(L), tick <= line(L + 1))")
    later = [c for c in kept if int(c["level"]) > 0 and int(c["tick"]) > int(lines[str(c["level"])])]
    check(later, f"some kept cells are past line(L) (kept by the arrival rule only): {len(later)}")
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


def _finals(r: Mapping[str, Any]) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    for c in r["cells"]:
        if c.get("ev") in ("new", "replaced"):
            out[int(c["cid"])] = c
    return out


def e2e_e7_resume() -> Dict[str, Any]:
    """Resume (owner 2026-11-16): a night resumed from two D folders (A, and B = A's twin by the same seed) inherits A's final
    representatives through the keep rule (B's are all later), counts and retirement from zero, the folders' root equal to its own; the
    inherited cells replay their prefixes exactly (no mismatch); no milestone comes from an inherited cell; a tighter line drops cells by
    the arrival rule at the plan; changed folder files and differing roots are refused."""
    b = dbench()
    A, B = b.run("a"), b.run("b")
    R = b.run("resumed", resume=[str(A["out"]), str(B["out"])], order={"slack": 200}, engine=dict(E_ENGINE, max_dispatches=80, rng_seed=8))
    s, o = R["summary"], R["summary"]["order"]
    check(R["code"] == 0 and s["status"] == "DISPATCH_CAP" and not R["violations"], f"a clean resumed night: {R['code']} {s['status']} {s['stop']}")
    rz = R["plan"]["resume"]
    fa_ = {k: v for k, v in _finals(A).items() if (v["origin"] or {}).get("kind") != "root"}
    check(rz["counts"]["candidates"] == 2 * len(fa_) and rz["counts"]["dropped_rule"] == 0, f"every final representative of both folders is a candidate: {rz['counts']}")
    check(rz["counts"]["inherited"] + rz["counts"]["dropped_later"] + rz["counts"]["replaced_in_resume"] == rz["counts"]["candidates"]
          and rz["counts"]["dropped_later"] >= len(fa_), f"B's twin cells are all later (equal ticks): {rz['counts']}")
    res_rows = [c for c in R["cells"] if (c.get("origin") or {}).get("kind") == "resume"]
    check(len(res_rows) == rz["inserts"] and o["resume"]["open"]["cells"] == rz["counts"]["inherited"] and o["resume"]["root_equal"] is True,
          f"one cells.jsonl row per insertion, the plan's set, the root equal: {len(res_rows)} {o['resume']}")
    byd = {(int(c["origin"]["d_cid"]), c["digest"]) for c in res_rows}
    check(byd <= {(cid, c["digest"]) for cid, c in fa_.items()} and all(c["origin"]["folder"] == str(A["out"]) for c in res_rows),
          "the inherited representatives are A's final ones (B gives way on equal ticks)")
    check(all(len(c["origin"]["d_breaks"]) == int(c["level"]) for c in res_rows), "every inherited row carries its break ticks")
    w = s["work"]
    inh = {int(c["cid"]) for c in res_rows}
    from_inh = [x for x in _bursts(R) if int(x["cid"]) in inh]
    check(w["mismatches"] == 0 and w["tick0_unequal"] == 0 and len(from_inh) >= 10, f"inherited cells dispatched with exact prefixes: {len(from_inh)}, {w['mismatches']}")
    check(max(int(x["level"]) for x in from_inh) >= max(int(c["level"]) for c in res_rows) - 1, "the inherited deep levels are dispatched from the start")
    check(all(int(m["n"]) > 0 for m in R["milestones"]), f"no milestone at the open (inherited cells meet none): {[(m['milestone'], m['n']) for m in R['milestones']]}")
    check(all(int(m["tick"]) > int(m["inherited_until"]) for m in R["milestones"]),
          f"every milestone's break happened in one of the night's bursts (v3): {[(m['milestone'], m['tick'], m['inherited_until']) for m in R['milestones']]}")
    for lv, row in (o["scoreboard"]["levels"] or {}).items():
        for col in ("first_in_night", "best_in_night"):
            e = row.get(col)
            check(e is None or lv == "10" or int(e["tick"]) > int(e["inherited_until"]), f"level {lv} {col}: an in-night break only: {e}")
    th = s["throughput"]
    newn = sum(int(v) for v in o["scoreboard"]["new_cells_in_night_by_level"].values())
    want_h = newn / max(1e-9, s["phase_wall_s"]["search"] / 3600.0)
    check(abs(th["new_cells_per_h"] - want_h) <= max(1.0, 0.01 * want_h) and th.get("new_cells_per_h_basis"),
          f"new cells per hour exclude the inserted cells: {th['new_cells_per_h']} vs {newn} in-night")
    d0 = (_bursts(R)[0].get("draw") or {})
    check((d0.get("set_count"), d0.get("order_count")) == (0, 0) if d0.get("stream") in ("rank", "anchor") else d0.get("count") == 0,
          f"the selector's counts start from zero (the first draw): {d0}")
    sc = o["scoreboard"]
    check(sc["levels"] and any(v.get("inherited_best") for v in sc["levels"].values()) and sc["sets_orders"]["open"], "the scoreboard shows the inherited levels")
    dp = osel.OrderParams(slack=60)
    P = O.build_plan(b.lab, b.frontier, b.lab / "order_tight_preview", dp, O.engine_params(dp, rng_seed=9), code="preview", resume=[A["out"]])
    tc = P["resume"]["counts"]
    check(tc["dropped_rule"] > 0 and tc["inherited"] < rz["counts"]["inherited"], f"a tighter line (s = 60) drops cells by the arrival rule at the plan: {tc}")
    plan_r = dict(rz, folders=[dict(rz["folders"][0], files_sha256=dict(rz["folders"][0]["files_sha256"], **{"run/cells.jsonl": "0" * 64}))] + rz["folders"][1:])
    check("changed since the plan" in str(O.resume_check(plan_r, [A["out"], B["out"]])) and "not the plan's" in str(O.resume_check(rz, [B["out"], A["out"]])),
          "a changed folder file, or the folders in another order, refuses the run")
    twin = b.lab / "order_root_altered"
    if not twin.exists():
        import shutil
        shutil.copytree(A["out"], twin, ignore=shutil.ignore_patterns("traces", "workers", "milestones", "vw"))
        rj = json.loads((twin / "run" / "root.json").read_text(encoding="utf-8"))
        rj["reads"][0]["digest"] = "0" * 64
        (twin / "run" / "root.json").write_text(json.dumps(rj), encoding="utf-8")
    try:
        O.resume_selection([A["out"], twin], osel.Pace(osel.OrderParams()))
        raise AssertionError("folders with different roots were accepted")
    except O.SearchError as exc:
        check("roots differ" in str(exc), str(exc))
    return {"counts": rz["counts"], "per_level_res": rz["per_level_res"], "inherited_dispatches": len(from_inh), "tight": tc}


def e2e_e8_long_bursts() -> Dict[str, Any]:
    """Longer bursts (owner 2026-11-16): a burst continues at a boundary exactly when the state there is inside the arrival rule, up to
    max_segments segments; every recorded answer agrees with the job's exact break ticks (cont_mismatches 0)."""
    b = dbench()
    A = b.run("a")
    o = A["summary"]["order"]
    lines = {int(k): int(v) for k, v in o["plan"]["pace"]["lines"].items()}
    seg, mx = 120, int(E_ENGINE["max_segments"])
    check(o["continuation"]["checked"] > 0 and o["continuation"]["mismatches"] == 0, f"every boundary answer recomputed from the exact breaks: {o['continuation']}")
    longer = 0
    for x in _bursts(A):
        cont = x.get("cont") or []
        gos = [int(e[5]) for e in cont]
        if x["outcome"] == "out_of_words":
            check(x["segments"] == min(mx, 1 + sum(gos)) and (not gos or gos[:-1] == [1] * (len(gos) - 1)),
                  f"dispatch {x['n']}: segments {x['segments']} follow the answers {gos}")
        for e in cont:
            lv, arr, tick, go = e[2], e[3], e[4], int(e[5])
            if lv is None:
                continue
            inside = lv < 10 and arr <= lines[lv] and tick <= lines[min(lv + 1, 10)]
            check(go == int(inside) and tick == int(x["start_tick"]) + seg * int(e[0]), f"dispatch {x['n']} segment {e[0]}: {e}")
        longer += int(x["words_played"] > seg)
    check(longer > 0, f"some bursts are longer than one segment: {longer}")
    check(A["config"]["arm_params"]["window"] == seg, f"D's boundary window is one segment: {A['config']['arm_params']}")
    return {"longer": longer, "continuation": o["continuation"], "lengths": o["scoreboard"]["burst_lengths"]["all"]}


def e2e_e9_scoreboard() -> Dict[str, Any]:
    """The fixed scoreboard (owner 2026-11-16) is in summary.json and report.md, and its counts agree with the night's own rows."""
    b = dbench()
    A = b.run("a")
    sc = A["summary"]["order"]["scoreboard"]
    want = {"deepest_level", "levels", "sets_orders", "level6plus_cells", "break_attribution", "dispatches_by_level", "level6_dispatches_by_start_resource_class",
            "retirements", "deep_reaches", "burst_lengths", "continuation", "m1", "integrity", "lowest_free_commit_mb", "leftover_worker_folders",
            "level6_extents"}
    check(want <= set(sc) and "error" not in sc, f"every scoreboard field: missing {sorted(want - set(sc))}")
    n = len(_bursts(A))
    check(sum(sc["burst_lengths"]["all"].values()) == n and sum(sc["dispatches_by_level"].values()) == n, "burst lengths and dispatches by level count every dispatch")
    lv6 = [x for x in _bursts(A) if int(x["level"]) == 6]
    check(sum(sc["level6_dispatches_by_start_resource_class"].values()) == len(lv6), "level-6 dispatches by starting resource class")
    check(sc["deep_reaches"]["total"] == len(A["deep"]) and all(int(r["level"]) >= 7 for r in A["deep"]), f"deep reaches: {sc['deep_reaches']['total']} rows")
    brk = sum(len([t for t, _i in (x.get("breaks_after_start") or [])]) for x in _bursts(A))
    check(sum(d["breaks"] for d in sc["break_attribution"].values()) == brk and all(set(d["hitter"]) == {"unknown (entity off)"} for d in sc["break_attribution"].values()),
          f"every burst break attributed per level (hitter unknown, entity off): {brk}")
    m1 = sc["m1"]
    check(m1["official"]["line"] == 408 and m1["reference"]["line"] == 408 and m1["official"]["met"], f"M1 at both lines: {m1}")
    check(sc["integrity"]["mismatches"] == 0 and sc["leftover_worker_folders"] == [] and sc["lowest_free_commit_mb"] is not None, f"integrity: {sc['integrity']}")
    check("## Scoreboard" in A["report"], "report.md carries the scoreboard")
    return {k: sc[k] for k in ("deepest_level", "dispatches_by_level", "deep_reaches", "m1")}


def e2e_e10_extent() -> Dict[str, Any]:
    """The exploration-extent record (owner 2026-11-16): every burst row has it; its reach counts are the row's; inside is a subset of
    all; every cell the night kept lies inside its dispatch's "inside" extent; the scoreboard's level-6 extents fold the rows."""
    b = dbench()
    A = b.run("a")
    rows = _bursts(A)
    check(all("extent" in x for x in rows), "every burst row carries its extent")
    by_n = {int(x["n"]): x for x in rows}
    for x in rows:
        ext = x["extent"]
        check(sum(e["all"]["reaches"] for e in ext.values()) == int(x["reaches"]), f"dispatch {x['n']}: the extent counts every reach")
        for k, e in ext.items():
            a, i = e["all"], e.get("inside")
            if i is not None:
                check(i["reaches"] <= a["reaches"] and i["max_y"][0] <= a["max_y"][0] and i["min_x"][0] >= a["min_x"][0] and i["max_x"][0] <= a["max_x"][0],
                      f"dispatch {x['n']} {k}: inside within all")
    kept = 0
    for c in A["cells"]:
        o = c.get("origin") or {}
        if c.get("ev") not in ("new", "replaced") or o.get("kind") != "burst" or int(o.get("n", 0)) not in by_n:
            continue
        e = by_n[int(o["n"])]["extent"].get(f"{c['level']}|{c['key'][3]}", {}).get("inside")
        x_, y_ = float(c["end"][O.OBS_X]), float(c["end"][O.OBS_Y])
        check(e is not None and e["min_x"][0] <= x_ <= e["max_x"][0] and y_ <= e["max_y"][0], f"cell {c['cid']} lies inside its dispatch's extent: {e}")
        kept += 1
    sc = A["summary"]["order"]["scoreboard"]["level6_extents"]
    six = {}
    for x in rows:
        for e in x["extent"].values():
            if int(e["level"]) == 6:
                six[str(e["mask"])] = max(six.get(str(e["mask"]), -1e18), e["all"]["max_y"][0])
    check(set(six) <= set(sc) and all(sc[m]["bursts"]["all"]["max_y"][0] == v for m, v in six.items()), f"the scoreboard folds the level-6 rows: {sorted(six)}")
    check(all(sc[m]["kept_cells"] is None or sc[m]["kept_cells"]["cells"] > 0 for m in sc), "kept-cell extents per level-6 set")
    return {"rows": len(rows), "kept_checked": kept, "level6_sets": {m: {g_: (d.get("max_y"), d.get("min_x"), d.get("max_x")) for g_, d in sc[m]["bursts"].items()}
                                                                     for m in sorted(sc)[:3]}}


def _rows_rule(pace: osel.Pace, k: Optional[int], lv: int, tick: int, pairs: Sequence[Sequence[int]]) -> bool:
    return _v3_or_open(pace, lv, tick, sorted(int(t) for t, _i in pairs), k)


def _open7(b: DBench) -> Dict[str, Any]:
    """The open-line night, K = 7, slack 200 (E11's; E14 resumes from it). Its own port base: DBench adds 1,000 per night from 52,000, and
    in the whole suite this is the 13th night (65,000 + workers > 65,535); every later night names its own port base too."""
    return b.run("open7", order={"slack": 200, "open_line_from": 7}, engine=dict(E_ENGINE, max_dispatches=240, rng_seed=11), port_base=46000)


FAKE_CUT_Y = 50.0          # a test value on the fake game's "easy" world (floors at y -500, 0, 420, 500; falls below -1,400): not a night's


def _cut7(b: DBench, **extra: Any) -> Dict[str, Any]:
    """E11's night with the fall cut at FAKE_CUT_Y (E13; E15 adds the hitter record)."""
    name = "cut7" + ("_hit" if extra.get("hitter") else "")
    return b.run(name, order={"slack": 200, "open_line_from": 7, "fall_cut_y": FAKE_CUT_Y}, engine=dict(E_ENGINE, max_dispatches=240, rng_seed=11),
                 port_base=51000 if extra.get("hitter") else 49000, **extra)


def e2e_e11_open_line() -> Dict[str, Any]:
    """The open line, K = 7, goal 480, slack 200 (owner 2026-11-18), on the fake game: every kept cell is inside v3's rule or (level >= 7)
    has its 7th break by line(7) = 536; some level-7+ cells are kept past line(8) = 584 and dispatched; levels below 7 are inside v3's rule;
    exploitation at levels >= 7 is the fewest stream only, below 7 run 3's; every boundary answer follows the rule (0 mismatches); every
    burst row's break record lists its credited breaks with the reach's position; the milestones keep their lines."""
    b = dbench()
    K = 7
    A = _open7(b)
    s, o = A["summary"], A["summary"]["order"]
    check(A["code"] == 0 and s["status"] == "DISPATCH_CAP" and not A["violations"] and s["work"]["mismatches"] == 0, f"a clean night: {s['status']} {s['stop']}")
    pace = osel.Pace(osel.OrderParams(slack=200, open_line_from=K))
    kr = o["keep_rule"]
    check(kr["open_line_from"] == K and kr["archive_bound"] == 3600 and A["config"]["order_params"]["open_line_from"] == K, f"the open rule is recorded: {kr}")
    kept = [c for c in A["cells"] if c["ev"] in ("new", "replaced") and (c.get("origin") or {}).get("kind") == "burst"]
    check(all(_rows_rule(pace, K, int(c["level"]), int(c["tick"]), c["origin"]["d_breaks"]) for c in kept), "every kept cell: v3's rule, or level >= 7 with the 7th break by 536")
    check(all(_rows_rule(pace, None, int(c["level"]), int(c["tick"]), c["origin"]["d_breaks"]) for c in kept if int(c["level"]) < K), "levels below 7: v3's rule")
    past = [c for c in kept if int(c["level"]) >= K and int(c["tick"]) > pace.window_end(int(c["level"]))]
    check(past and max(int(c["tick"]) for c in past) > pace.line(10), f"level-7+ cells kept past v3's window, some past line(10) = 680: {len(past)}")
    by_cid = {int(c["cid"]) for c in past}
    rows = _bursts(A)
    from_past = [x for x in rows if int(x["cid"]) in by_cid and int(x["start_tick"]) > pace.window_end(int(x["level"]))]
    check(from_past, f"cells past v3's window are dispatched: {len(from_past)}")
    ex = [x for x in rows if x.get("stream") in ("rank", "anchor", "fewest")]
    check(all((x["stream"] == "fewest") == (int(x["draw"]["level"]) >= K) for x in ex) and any(x["stream"] == "fewest" for x in ex),
          f"exploitation: fewest at levels >= 7 only: {Counter((x['stream'], int(x['draw']['level']) >= K) for x in ex)}")
    seen: Counter = Counter()
    for x in rows:                                       # the fewest draw's count is the cell's earlier dispatches (any stream)
        if x.get("stream") == "fewest":
            check(int(x["draw"]["count"]) == seen[int(x["cid"])], f"dispatch {x['n']}: count {x['draw']['count']} vs {seen[int(x['cid'])]} earlier")
        seen[int(x["cid"])] += 1
    check(o["continuation"]["checked"] > 0 and o["continuation"]["mismatches"] == 0, f"boundary answers: {o['continuation']}")
    d_of = {c["digest"]: c["origin"].get("d_breaks") or [] for c in A["cells"] if c["ev"] in ("new", "replaced")}
    longer = answers = 0
    for x in rows:
        allp = sorted([tuple(p) for p in (x.get("breaks_after_start") or [])])
        pre = d_of[str(x["draw_id"]).rsplit("|", 1)[1]]  # the dispatched representative's break pairs (draw id = archive|family|digest)
        for e in x.get("cont") or []:
            if e[2] is None:
                continue
            p = [q for q in list(pre) + allp if int(q[0]) <= int(e[4])]
            check(len(p) == int(e[2]) and int(e[5]) == int(_rows_rule(pace, K, len(p), int(e[4]), p)), f"dispatch {x['n']} boundary {e}: the open rule by hand")
            answers += 1
        longer += int(int(x["level"]) >= K and int(x["words_played"]) > 120)
        br = x["break_record"]
        check([(e["tick"], e["target"]) for e in br] == [(int(t), int(i)) for t, i in allp], f"dispatch {x['n']}: one break-record entry per credited break")
        check(all(e.get("reach", 1) is None or (e["x"] == e["obs"]["position_x"] and e["y"] == e["obs"]["position_y"] and len(e["obs"]) == 17) for e in br),
              f"dispatch {x['n']}: positions on the break record")
        check(all(e["level"] == int(x["prefix_breaks"]) + j + 1 for j, e in enumerate(br)), f"dispatch {x['n']}: the levels count from tick 0")
    check(longer > 0, f"bursts from levels >= 7 run past one segment: {longer}")
    for m in o["milestones"]:
        if m["milestone"] != "clear_line":
            check(int(m["tick"]) <= int(m["line"]), f"milestone {m['milestone']} keeps its line: {m}")
    nbr = sum(len(x["break_record"]) for x in rows)
    return {"kept_past_window": len(past), "max_tick_past": max(int(c["tick"]) for c in past), "dispatched_past": len(from_past), "longer_7plus": longer, "answers": answers,
            "streams": dict(Counter(x.get("stream") for x in rows)), "break_record_entries": nbr,
            "levels": dict(Counter(int(c["level"]) for c in kept)), "milestones": [(m["milestone"], m["tick"]) for m in o["milestones"]]}


def _no_host(e: Mapping[str, Any]) -> Dict[str, Any]:
    """A break-record entry without the hitter fields and without host_frame (wall-clock dependent) in its observation."""
    out = {k: v for k, v in e.items() if k not in O.HITTER_FIELDS}
    if isinstance(out.get("obs"), dict):
        out["obs"] = {k: v for k, v in out["obs"].items() if k != "host_frame"}
    return out


def _same_decisions(A: Mapping[str, Any], H: Mapping[str, Any]) -> Dict[str, Any]:
    """Two same-seed nights, one with the hitter record (E12, E15): the same dispatch rows, draws, cells, milestones and verdicts, hourly
    records, root, extents, break-record fields (E1's), glitch counts; run 3's self-check on every result. Returns H's anomaly record."""
    check(det.dispatch_signature(A["dispatches"]) == det.dispatch_signature(H["dispatches"]), "the same dispatch rows (cell, k, draw id, words, outcome, kept, cont)")
    sel = lambda r: [(x["n"], x.get("stream"), x.get("group"), x.get("niche"), json.dumps(x.get("draw"), sort_keys=True)) for x in _bursts(r)]  # noqa: E731
    check(sel(A) == sel(H), "the same draws (stream, set, order, counts, rank)")
    check(det.cells_signature(A["cells"]) == det.cells_signature(H["cells"]), "the same cell rows")
    ms = lambda r: [{k: v for k, v in m.items() if k not in ("utc", "elapsed_s")} for m in r["milestones"]]  # noqa: E731
    check(ms(A) == ms(H) and [v["verdict"] for v in A["mver"]] == [v["verdict"] for v in H["mver"]], "the same milestones and verdicts")
    hs = lambda r: [json.dumps({k: v for k, v in h.items() if k not in HOURLY_VOLATILE}, sort_keys=True) for h in r["hourly"]]  # noqa: E731
    check(hs(A) == hs(H), "the same hourly records")
    rr = lambda r: [(x["digest"], x["chain"], x["key"], x["mask"]) for x in r["root"]["reads"]]  # noqa: E731
    check(rr(A) == rr(H), "the same tick-0 root")
    check([x.get("extent") for x in _bursts(A)] == [x.get("extent") for x in _bursts(H)], "the same extents")
    check([[_no_host(e) for e in x["break_record"]] for x in _bursts(A)] == [[_no_host(e) for e in x["break_record"]] for x in _bursts(H)],
          "the same break-record fields (E1's) on every row")
    ga, gh = A["summary"]["anomalies"], H["summary"]["anomalies"]
    check(ga == gh and "counts" in ga and ga["counts"], f"the same glitch / anomaly counts (run 3's detectors see entity-off replies): {ga} vs {gh}")
    check(gh["selfcheck"]["checked"] == len(_bursts(H)) and gh["selfcheck"]["failed"] == 0, f"run 3's rebuild from the replies it saw equals every result: {gh['selfcheck']}")
    return gh


def _hitter_kinds(H: Mapping[str, Any]) -> Tuple[int, Counter]:
    """Every credited break of a hitter-record night (E12, E15): the fields, the kind the synthetic entity object implies, a projectile's
    serial and first tick; the summary's counts and the scoreboard's attribution agree. Returns (credited breaks, kinds)."""
    d_of = {c["digest"]: c["origin"].get("d_breaks") or [] for c in H["cells"] if c["ev"] in ("new", "replaced")}
    kinds: Counter = Counter()
    n = 0
    for x in _bursts(H):
        lost: Dict[int, int] = {}
        for t, i in list(d_of[str(x["draw_id"]).rsplit("|", 1)[1]]) + [(e["tick"], e["target"]) for e in x["break_record"]]:
            lost[int(t)] = lost.get(int(t), 0) | (1 << int(i))
        for e in x["break_record"]:
            n += 1
            check(set(O.HITTER_FIELDS) <= set(e) and e["hitter"] in OW.KINDS, f"dispatch {x['n']}: the hitter fields {e}")
            want = expected_fake_kind(int(e["tick"]), lost)
            check(e["hitter"] == want, f"dispatch {x['n']} tick {e['tick']}: {e['hitter']} (the synthetic object implies {want}; {e.get('hitter_why')})")
            if e["hitter"] == "projectile":
                check(isinstance(e["hitter_serial"], int) and e["hitter_serial"] >= 1 and e["hitter_owner"] == "mario" and e["hitter_weapon_kind"] == 0
                      and isinstance(e["hitter_first_tick"], int) and 0 <= e["hitter_first_tick"] < int(e["tick"])
                      and e["hitter_evidence"]["vanished"][0]["serial"] == e["hitter_serial"], f"dispatch {x['n']}: a projectile's fields {e}")
            kinds[e["hitter"]] += 1
    hr = H["summary"]["order"]["hitter_record"]
    check(hr["credited_breaks"] == n and hr["by_kind"] == {k: kinds.get(k, 0) for k in OW.KINDS} and hr["jobs_without_record"] == 0 and hr["tracker_errors"] == 0
          and hr["jobs_with_record"] == len(_bursts(H)), f"the summary counts: {hr}")
    ba = H["summary"]["order"]["scoreboard"]["break_attribution"]
    sb_k: Counter = Counter()
    for d in ba.values():
        sb_k.update(d["hitter"])
    check(sb_k == kinds and "unknown (entity off)" not in sb_k, f"the scoreboard's break attribution: {dict(sb_k)}")
    return n, kinds


def e2e_e12_hitter_record() -> Dict[str, Any]:
    """The hitter record (owner 2026-11-19, report-only) on the fake game with a synthetic entity object: the same-seed night as E1's "a"
    with the option on makes the same decisions (dispatch rows, draws, cells, milestones, boundary answers, root, extents, break-record
    fields, hourly records, glitch counts); every credited break carries the hitter fields, each the kind the synthetic object implies
    (mario, projectile with its serial and first tick, unseen, ambiguous); the records and counts agree; with the option on and no entity
    object in the replies the open stops (the tick-0 reads fail)."""
    b = dbench()
    A = b.run("a")
    H = b.run("hit", hitter=True, fake_entity=True, port_base=47000)
    for r in (A, H):
        check(r["code"] == 0 and r["summary"]["status"] == "DISPATCH_CAP" and not r["violations"] and len(_bursts(r)) == 160,
              f"a clean 160-dispatch night: {r['code']} {r.get('summary', {}).get('status')} {r.get('summary', {}).get('stop')} {r['violations']}")
    gh = _same_decisions(A, H)
    check(all("hitter" not in e for x in _bursts(A) for e in x["break_record"]) and "hitter_record" not in A["config"] and "hitter_record" not in A["summary"]["order"],
          "option off: no hitter field, no record")
    n, kinds = _hitter_kinds(H)
    check(n > 0 and {"mario", "projectile", "unseen", "ambiguous"} <= set(kinds) and not kinds["unavailable"], f"every kind but unavailable occurs: {dict(kinds)}")
    check(H["config"]["hitter_record"]["search_flags"].get("SSB64_RL_ENTITY") == "1" and H["config"]["hitter_record"]["contract"] == OW.HITTER_CONTRACT
          and "## Hitter record" in H["report"], "config and report record the option")
    # the option on without an entity object in the replies: the open stops
    M = b.run("hit_missing", hitter=True, engine=dict(E_ENGINE, max_dispatches=10), port_base=48000)
    stop = json.dumps(M.get("summary", {}).get("stop"))
    check(M.get("summary", {}).get("status") == "SEARCH_INVALID" and "EntityMissing" in stop and not _bursts(M), f"no entity object: the open stops: {M.get('summary', {}).get('status')} {stop[:300]}")
    return {"credited_breaks": n, "kinds": dict(kinds), "dispatches": len(_bursts(H)), "glitch_counts": dict(gh["counts"]), "selfcheck": gh["selfcheck"]["checked"],
            "missing_stop": stop[:160]}


def _y(row: Mapping[str, Any]) -> float:
    return float(row["end"][O.OBS_Y])


def e2e_e13_fall_cut() -> Dict[str, Any]:
    """The fall cut and the draw group (owner 2026-11-19, v6) on the fake game: E11's night with the cut at FAKE_CUT_Y. Every cell kept
    tonight at a level >= 7 is at y >= Y or grounded, and grounded cells below Y are kept there, while levels below 7 keep cells below Y
    whatever their class; the reaches the cut did not keep are logged (deep reaches, reason fall_cut, never grounded) and counted, and the
    grounded reaches it spared are counted; every dispatch from a level >= 7 starts at y >= Y or grounded; every exploitation draw at levels
    >= 7 is the group draw, which is the fewest-dispatches cell among the group's cells kept by the ingested dispatches (ties: deeper level,
    earlier tick, cell id), and no set / order budget counts there; boundary answers follow the rule; the records state the cut."""
    b = dbench()
    K, Y = 7, FAKE_CUT_Y
    A = _cut7(b)
    s, o = A["summary"], A["summary"]["order"]
    check(A["code"] == 0 and s["status"] == "DISPATCH_CAP" and not A["violations"] and s["work"]["mismatches"] == 0 and len(_bursts(A)) == 240,
          f"a clean night: {s['status']} {s['stop']}")
    kr = o["keep_rule"]
    check(kr["fall_cut_y"] == Y and kr["fall_cut_from"] == K and A["config"]["order_params"]["fall_cut_y"] == Y and s["order"]["plan"]["params_fingerprint"]
          and "## Fall cut" in A["report"] and "draw group" in kr["open_rule"], f"the records state the cut and the group: {kr}")
    G = osel.GROUNDED
    kept = [c for c in A["cells"] if c["ev"] in ("new", "replaced") and (c.get("origin") or {}).get("kind") == "burst"]
    hi = [c for c in kept if int(c["level"]) >= K]
    hi_ground_below = [c for c in hi if _y(c) < Y]
    lo_below = [c for c in kept if int(c["level"]) < K and _y(c) < Y]
    check(hi and all(_y(c) >= Y or c["key"][2] == G for c in hi), f"every level-7+ cell kept tonight is at y >= {Y} or grounded: {len(hi)} cells")
    check(hi_ground_below, f"grounded level-7+ states below Y are kept: {len(hi_ground_below)}")
    check(lo_below and any(c["key"][2] != G for c in lo_below), f"levels below 7 keep states below Y, airborne too: {len(lo_below)}")
    cut_rows = [d for d in A["deep"] if d.get("reason") == "fall_cut"]
    check(cut_rows and all(d["verdict"] == O.cs.BEYOND and int(d["level"]) >= K and float(d["over"]) > 0 and d["key"][2] != G for d in cut_rows),
          f"the cut reaches are logged, none grounded: {len(cut_rows)}")
    fc = o["fall_cut"]
    check(fc["reaches_cut_total"] == len(cut_rows) == sum(int(v["count"]) for v in fc["reaches_cut"].values()) and fc["y"] == Y and fc["from_level"] == K,
          f"the readout counts them: {fc}")
    # the grounded reaches below Y that the pace line kept in its window reached the archive's keep rule: every deep row of a grounded
    # level-7+ reach whose key's y bucket is below 0 (so y < 0 < Y), not terminal and not a rule rejection, is one of the spared ones
    sure = [d for d in A["deep"] if d["key"][2] == G and int(d["key"][1]) < 0 and d["verdict"] != O.cs.TERMINAL and d.get("reason") is None]
    spared = sum(int(v) for v in fc["grounded_spared"].values())
    check(spared > 0 and spared >= len(sure), f"the grounded reaches below Y spared: {spared} (at least {len(sure)})")
    y_of = {c["digest"]: (_y(c), c["key"][2]) for c in A["cells"] if c["ev"] in ("new", "replaced")}
    rows = _bursts(A)
    starts = [y_of[str(x["draw_id"]).rsplit("|", 1)[1]] for x in rows if int(x["level"]) >= K]
    check(starts and all(yy >= Y or res == G for yy, res in starts), f"every level-7+ dispatch starts at y >= Y or grounded: {len(starts)}")
    fewest = [x for x in rows if x.get("stream") == "fewest"]
    check(fewest and all(x["draw"]["scope"] == "group" and int(x["draw"]["level"]) >= K and x["draw"]["draw_group_from"] == K for x in fewest)
          and not [x for x in rows if x.get("stream") in ("rank", "anchor") and int(x["draw"]["level"]) >= K], f"exploitation at levels >= 7: the group draw ({len(fewest)})")
    check(len({int(x["draw"]["level"]) for x in fewest}) >= 2, f"the group draws reach more than one level: {Counter(int(x['draw']['level']) for x in fewest)}")
    # the group minimum, rebuilt from the rows: the cells kept by the dispatches ingested before the selection (sched.ingested_through)
    by_n: Dict[int, List[Mapping[str, Any]]] = {}
    for c in kept:
        by_n.setdefault(int(c["origin"]["n"]), []).append(c)
    cnt: Counter = Counter()
    checked = 0
    for x in rows:
        if x.get("stream") == "fewest":
            upto = int(x["sched"]["ingested_through"])
            pool: Dict[int, Tuple[int, int]] = {}
            for n_ in sorted(k for k in by_n if k <= upto):
                for c in by_n[n_]:
                    if int(c["level"]) >= K:
                        pool[int(c["cid"])] = (int(c["level"]), int(c["tick"]))   # a later row of the same cell is its replacement
            if len(pool) == int(x["draw"]["draw_group_active"]):
                want = min(pool, key=lambda cid: (cnt[cid], -pool[cid][0], pool[cid][1], cid))
                check(int(x["cid"]) == want and int(x["draw"]["count"]) == cnt[int(x["cid"])], f"dispatch {x['n']}: cell {x['cid']}, the group's fewest is {want}")
                checked += 1
        cnt[int(x["cid"])] += 1
    check(checked >= len(fewest) // 2, f"the group minimum checked on {checked} of {len(fewest)} draws (the rest: retirement or an in-flight replacement)")
    lv_read = o["selection"]["levels"]
    check(all(not lv_read[lv]["set_count_max"] and lv_read[lv].get("draw_group") for lv in lv_read if int(lv) >= K)
          and not any(lv_read[lv].get("draw_group") for lv in lv_read if int(lv) < K) and o["selection"]["within_one_violations"] == []
          and o["selection"]["rotation"].get("group_draws") == len(fewest), f"no budget in the group: {[(lv, lv_read[lv]['set_count_max']) for lv in lv_read]}")
    check(not any("budget_counts_not_within_1" in h["flags"] for h in o["hourly_records"]) and all("fall_cut" in h for h in A["hourly"]), "hourly: no within-1 flag; the cut's readout")
    check(o["continuation"]["checked"] > 0 and o["continuation"]["mismatches"] == 0, f"boundary answers: {o['continuation']}")
    for m in o["milestones"]:
        if m["milestone"] != "clear_line":
            check(int(m["tick"]) <= int(m["line"]), f"milestone {m['milestone']} keeps its line: {m}")
    return {"kept_7plus": len(hi), "kept_7plus_grounded_below_y": len(hi_ground_below), "kept_below_y_under_7": len(lo_below), "cut_reaches": len(cut_rows),
            "grounded_spared": fc["grounded_spared"], "group_draws": len(fewest), "group_draw_levels": dict(Counter(int(x["draw"]["level"]) for x in fewest)),
            "minimum_checked": checked, "levels": dict(Counter(int(c["level"]) for c in kept))}


def e2e_e14_fall_cut_resume() -> Dict[str, Any]:
    """The cut on resume: a night with the cut resumed from E11's night (no cut) inherits the same set as without the cut (the cut drops no
    cell); the inherited airborne cells at levels >= 7 below Y are inserted but never dispatched; the grounded ones below Y are drawable; the
    plan's counts of both equal the open's / the rows'; the inherited cells above Y are dispatched."""
    b = dbench()
    A = _open7(b)
    order = {"slack": 200, "open_line_from": 7, "fall_cut_y": FAKE_CUT_Y}
    R = b.run("cut7_resumed", resume=[str(A["out"])], order=order, engine=dict(E_ENGINE, max_dispatches=120, rng_seed=8), port_base=50000)
    s, o = R["summary"], R["summary"]["order"]
    check(R["code"] == 0 and s["status"] == "DISPATCH_CAP" and not R["violations"] and s["work"]["mismatches"] == 0, f"a clean resumed night: {s['status']} {s['stop']}")
    dp0 = osel.OrderParams(slack=200, open_line_from=7)
    P0 = O.build_plan(b.lab, b.frontier, b.lab / "order_cut_preview_off", dp0, O.engine_params(dp0, rng_seed=8), code="preview", resume=[A["out"]])
    check(P0["resume"]["set_digest"] == R["plan"]["resume"]["set_digest"] and P0["resume"]["counts"] == R["plan"]["resume"]["counts"],
          "the cut drops no inherited cell: the same set as without it")
    G = osel.GROUNDED
    res_rows = [c for c in R["cells"] if (c.get("origin") or {}).get("kind") == "resume"]
    below = [c for c in res_rows if int(c["level"]) >= 7 and _y(c) < FAKE_CUT_Y and c["key"][2] != G]
    ground = [c for c in res_rows if int(c["level"]) >= 7 and _y(c) < FAKE_CUT_Y and c["key"][2] == G]
    above = [c for c in res_rows if int(c["level"]) >= 7 and _y(c) >= FAKE_CUT_Y]
    check(below and above and ground, f"inherited level-7+ cells: {len(below)} airborne below Y, {len(ground)} grounded below Y, {len(above)} above")
    lvc = lambda rows_: dict(sorted(Counter(str(c["level"]) for c in rows_).items(), key=lambda kv: -int(kv[0])))  # noqa: E731
    want = lvc(below)
    check(o["keep_rule"]["fall_cut_inherited_undrawable"] == want == o["fall_cut"]["inherited_undrawable_at_open"], f"the plan's and the open's count: {want} {o['fall_cut']}")
    check(o["keep_rule"]["fall_cut_inherited_grounded_spared"] == lvc(ground), f"the plan's grounded count: {o['keep_rule']['fall_cut_inherited_grounded_spared']}")
    rows = _bursts(R)
    started = {str(x["draw_id"]).rsplit("|", 1)[1] for x in rows}
    check(not ({c["digest"] for c in below} & started), "no dispatch from an inherited airborne cell below Y")
    check(({c["digest"] for c in above} | {c["digest"] for c in ground}) & started, "inherited cells above Y or grounded are dispatched")
    return {"inherited": len(res_rows), "below_airborne": len(below), "below_grounded": len(ground), "above": len(above), "undrawable": want,
            "grounded_dispatched": len({c["digest"] for c in ground} & started)}


def e2e_e15_fall_cut_hitter() -> Dict[str, Any]:
    """The hitter record with the new options on (open line 7, the cut, the level-wide draw): the same decisions as E13's night without it,
    every credited break carries the hitter fields of the synthetic entity object, and the cut's readout is the same."""
    b = dbench()
    A = _cut7(b)
    H = _cut7(b, hitter=True, fake_entity=True)
    for r in (A, H):
        check(r["code"] == 0 and r["summary"]["status"] == "DISPATCH_CAP" and not r["violations"] and len(_bursts(r)) == 240,
              f"a clean 240-dispatch night: {r['code']} {r.get('summary', {}).get('status')} {r.get('summary', {}).get('stop')} {r['violations']}")
    _same_decisions(A, H)
    n, kinds = _hitter_kinds(H)
    check(n > 0 and not kinds["unavailable"] and len(kinds) >= 2, f"credited breaks with their hitter: {dict(kinds)}")
    fa_, fh = A["summary"]["order"]["fall_cut"], H["summary"]["order"]["fall_cut"]
    check(fa_ == fh and fh["reaches_cut_total"] > 0, f"the same cut readout: {fa_} vs {fh}")
    return {"credited_breaks": n, "kinds": dict(kinds), "cut_reaches": fh["reaches_cut_total"]}


FAKE_CUT_Y_ALL = 1.0e6     # a test value above every position of the fake world: every state at a level >= 7 is below Y


def e2e_e16_clear_below_cut() -> Dict[str, Any]:
    """Clears and the cut (owner 2026-11-19): with Y above the whole fake world (every level-7+ state below Y, every airborne one cut, only
    grounded ones kept), clears still happen, with Mario airborne below Y at the clear tick, and none is cut, dropped or left unclaimed:
    the clear tick's reach is level 10 and terminal, so the keep wrapper's rules (the pace line, the cut: levels < 10, not terminal) never
    see it and the archive gives TERMINAL; every clear row is claimed (the claim comes from the job's outcome, not from the archive) and
    queued; every replayed claim is VERIFIED, at least one of them airborne below Y."""
    b = dbench()
    K, Y = 7, FAKE_CUT_Y_ALL
    A = b.run("clear_cut", order={"slack": 200, "open_line_from": K, "fall_cut_y": Y}, engine=dict(E_ENGINE, max_dispatches=240, rng_seed=11), port_base=52000)
    s, o = A["summary"], A["summary"]["order"]
    check(A["code"] == 0 and s["status"] == "DISPATCH_CAP" and not A["violations"] and s["work"]["mismatches"] == 0, f"a clean night: {s['status']} {s['stop']}")
    G = osel.GROUNDED
    kept7 = [c for c in A["cells"] if c["ev"] in ("new", "replaced") and (c.get("origin") or {}).get("kind") == "burst" and int(c["level"]) >= K]
    check(kept7 and all(c["key"][2] == G for c in kept7) and o["fall_cut"]["reaches_cut_total"] > 0, f"the cut at full strength: only grounded level-7+ cells kept ({len(kept7)})")
    rows = _bursts(A)
    clears = [x for x in rows if x.get("outcome") == "clear"]
    check(clears, "clears happen")
    deep10 = {(int(d["n"]), int(d["tick"])): d for d in A["deep"] if int(d["level"]) == osel.TARGETS_TOTAL}
    below_air = []
    for x in clears:
        t10 = int(x["claimed"]["completion_input_tick"])
        last = x["break_record"][-1]
        check(int(last["level"]) == osel.TARGETS_TOTAL and int(last["tick"]) == t10, f"dispatch {x['n']}: the 10th break at the claimed tick: {last}")
        d = deep10.get((int(x["n"]), t10))
        check(d is not None and d["verdict"] == O.cs.TERMINAL and d.get("reason") is None, f"dispatch {x['n']}: the clear's reach is TERMINAL, never cut: {d}")
        if last.get("reach", 1) is not None and float(last["y"]) < Y and last["key"][2] != G:
            check(last["terminal"] is True, f"dispatch {x['n']}: the clear tick's reach is terminal")
            below_air.append(x)
    check(below_air, f"clears with Mario airborne below Y at the clear tick: {len(below_air)} of {len(clears)}")
    cl = o["claims"]
    check(cl["claimed"] == len(clears) == s["work"]["clears_claimed"], f"every clear is claimed: {cl} vs {len(clears)} clear rows")
    ver = [v for v in A["verifications"] if v.get("kind") == "clear"]
    check(ver and all(v["verdict"] == O.fv.VERIFIED for v in ver) and len(ver) + int(cl["not_replayed"]) <= len(clears),
          f"every replayed claim is VERIFIED: {[(v['n'], v['verdict']) for v in ver]}; not replayed {cl['not_replayed']}")
    vn = {int(v["n"]) for v in ver}
    check(any(int(x["n"]) in vn for x in below_air), "at least one verified clear had Mario airborne below Y")
    return {"clears": len(clears), "airborne_below_y": len(below_air), "verified": sorted(vn), "not_replayed": cl["not_replayed"],
            "clear_y": [round(float(x["break_record"][-1]["y"]), 1) for x in below_air], "cut_reaches": o["fall_cut"]["reaches_cut_total"]}


# -- v7 on the fake game (owner 2026-11-20) -----------------------------------------------------------------------------------------------

FAKE_DIR_LINES = (4,)      # a test value: the fake world's main floor stands in for the moving floor line (the fake game has none)


def _kept_burst(r: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return [c for c in r["cells"] if c["ev"] in ("new", "replaced") and (c.get("origin") or {}).get("kind") == "burst"]


def _fake_bound(b: DBench) -> int:
    """A test value of B on the fake game: the median own tick of the level-7+ cells E11's night (same seed) kept, so that level-7+ reaches
    fall on both sides of it. Not a night's value."""
    ticks = sorted(int(c["tick"]) for c in _kept_burst(_open7(b)) if int(c["level"]) >= 7)
    check(len(ticks) >= 10, f"E11's night keeps level-7+ cells: {len(ticks)}")
    return ticks[len(ticks) // 2]


def _clean(r: Mapping[str, Any], n: Optional[int] = None) -> None:
    s = r.get("summary") or {}
    check(r["code"] == 0 and s.get("status") == "DISPATCH_CAP" and not r["violations"] and s["work"]["mismatches"] == 0 and (n is None or len(_bursts(r)) == n),
          f"a clean night: {r['code']} {s.get('status')} {s.get('stop')} {r['violations']}")


def e2e_e17_record_bound() -> Dict[str, Any]:
    """The record bound (owner 2026-11-20) on the fake game: E11's night with B (a test value, _fake_bound). Every level-7+ cell kept tonight
    has its own tick below B; the level-7+ reaches at or past B inside the arrival rule are logged (deep reaches, reason record_bound, over =
    tick - B) and counted; every dispatch from a level-7+ cell starts below B; every boundary whose state is at a level >= 7 at a tick >= B
    stops the burst, and some burst is stopped that way; boundary answers follow the rule (0 mismatches); levels below 7 keep v6's rule;
    every clear is claimed; the milestones keep their lines; plan, config, summary, hourly records and report state the bound."""
    b = dbench()
    K, B = 7, _fake_bound(b)
    A = b.run("bound7", order={"slack": 200, "open_line_from": K, "record_bound": B}, engine=dict(E_ENGINE, max_dispatches=240, rng_seed=11), port_base=36000)
    _clean(A, 240)
    s, o = A["summary"], A["summary"]["order"]
    kr = o["keep_rule"]
    check(kr["record_bound"] == B and kr["record_bound_from"] == K and A["config"]["order_params"]["record_bound"] == B and "## Record bound" in A["report"]
          and all("record_bound" in h for h in A["hourly"]) and f"record bound {B}" in A["config"]["continuation"], f"the records state the bound: {kr}")
    kept = _kept_burst(A)
    hi = [c for c in kept if int(c["level"]) >= K]
    check(hi and all(int(c["tick"]) < B for c in hi), f"every level-7+ cell kept tonight is below B = {B}: {len(hi)}")
    pace = osel.Pace(osel.OrderParams(slack=200, open_line_from=K))
    check(all(_rows_rule(pace, K, int(c["level"]), int(c["tick"]), c["origin"]["d_breaks"]) for c in kept if int(c["level"]) < K), "levels below 7: the rule as before")
    rows_b = [d for d in A["deep"] if d.get("reason") == "record_bound"]
    check(rows_b and all(d["verdict"] == O.cs.BEYOND and int(d["level"]) >= K and int(d["tick"]) >= B and int(d["over"]) == int(d["tick"]) - B for d in rows_b),
          f"the reaches past B are logged: {len(rows_b)}")
    rb = o["record_bound"]
    check(rb["reaches_not_kept_total"] == len(rows_b) == sum(int(v["count"]) for v in rb["reaches_not_kept"].values()) and rb["bound"] == B, f"the readout: {rb}")
    rows = _bursts(A)
    starts = [x for x in rows if int(x["level"]) >= K]
    check(starts and all(int(x["start_tick"]) < B for x in starts), f"every level-7+ dispatch starts below B: {len(starts)}")
    stops = past_go = 0
    for x in rows:
        for e in x.get("cont") or []:
            if e[2] is not None and int(e[2]) >= K and int(e[4]) >= B:
                past_go += int(bool(e[5]))
                stops += int(not e[5])
    check(stops > 0 and past_go == 0, f"bursts stop at their first boundary past B: {stops} stops, {past_go} went on")
    check(o["continuation"]["checked"] > 0 and o["continuation"]["mismatches"] == 0 and str(B) in o["continuation"]["rule"], f"boundary answers: {o['continuation']}")
    clears = [x for x in rows if x.get("outcome") == "clear"]
    check(o["claims"]["claimed"] == len(clears) == s["work"]["clears_claimed"], f"every clear is claimed: {o['claims']} vs {len(clears)}")
    for m in o["milestones"]:
        if m["milestone"] != "clear_line":
            check(int(m["tick"]) <= int(m["line"]), f"milestone {m['milestone']} keeps its line: {m}")
    return {"B": B, "kept_7plus": len(hi), "reaches_past_b": len(rows_b), "stops": stops, "dispatches_7plus": len(starts), "clears": len(clears),
            "levels": dict(Counter(int(c["level"]) for c in kept))}


def e2e_e18_one_live() -> Dict[str, Any]:
    """The one-live-target exemption (owner 2026-11-20): E16's night (Y above the whole fake world: every level-7+ state below Y) with the
    exemption on keeps airborne level-9 states (none without it) and still keeps only grounded level-7 and level-8 ones; the cut's readout
    counts the spared level-9 reaches and logs no level-9 cut; airborne level-9 cells are dispatched; every clear is claimed."""
    b = dbench()
    K, Y = 7, FAKE_CUT_Y_ALL
    C0 = b.run("clear_cut", order={"slack": 200, "open_line_from": K, "fall_cut_y": Y}, engine=dict(E_ENGINE, max_dispatches=240, rng_seed=11), port_base=52000)
    E = b.run("onelive", order={"slack": 200, "open_line_from": K, "fall_cut_y": Y, "fall_cut_spare_one_live": True}, engine=dict(E_ENGINE, max_dispatches=240, rng_seed=11),
              port_base=38000)
    _clean(E, 240)
    G = osel.GROUNDED
    air9 = [c for c in _kept_burst(E) if int(c["level"]) == 9 and c["key"][2] != G]
    check(air9, f"airborne level-9 states are kept with the exemption: {len(air9)}")
    check(not [c for c in _kept_burst(C0) if int(c["level"]) == 9 and c["key"][2] != G], "without it, none")
    check(all(c["key"][2] == G for c in _kept_burst(E) if int(c["level"]) in (7, 8)), "levels 7 and 8: only grounded states kept")
    fc = E["summary"]["order"]["fall_cut"]
    check(set(fc["one_live_spared"]) == {"9"} and int(fc["one_live_spared"]["9"]) > 0 and "9" not in fc["reaches_cut"]
          and not [d for d in E["deep"] if d.get("reason") == "fall_cut" and int(d["level"]) == 9], f"the readout: {fc}")
    check("one live target" in E["summary"]["order"]["keep_rule"]["fall_cut_one_live"] and "one live target" in E["report"], "the records state it")
    dig9 = {c["digest"] for c in air9}
    started = [x for x in _bursts(E) if str(x["draw_id"]).rsplit("|", 1)[1] in dig9]
    check(started, f"airborne level-9 cells are dispatched: {len(started)}")
    clears = [x for x in _bursts(E) if x.get("outcome") == "clear"]
    check(E["summary"]["order"]["claims"]["claimed"] == len(clears), f"every clear is claimed: {E['summary']['order']['claims']}")
    return {"air9_kept": len(air9), "spared": fc["one_live_spared"], "dispatched_air9": len(started), "clears": len(clears)}


def _dir_ok(c: Mapping[str, Any]) -> bool:
    """A kept row's key under the direction key with FAKE_DIR_LINES: a grounded state on such a line carries its tick's direction, every
    other key a plain floor field."""
    k = c["key"]
    if k[2] == osel.GROUNDED and O.plain_floor(int(k[4])) in FAKE_DIR_LINES:
        return int(k[4]) == O.plain_floor(int(k[4])) + O.DIR_FLOOR_OFFSET[O.platform_direction(int(c["tick"]))]
    return int(k[4]) < 1000


def _dir7(b: DBench) -> Dict[str, Any]:
    return b.run("dir7", order={"slack": 200, "open_line_from": 7, "floor_direction_key": True}, engine=dict(E_ENGINE, max_dispatches=240, rng_seed=11),
                 port_base=39000, dir_lines=list(FAKE_DIR_LINES))


def e2e_e19_direction_key() -> Dict[str, Any]:
    """The floor-direction key (owner 2026-11-20) on the fake game, with the fake main floor standing in for the moving line: every kept
    state grounded on it carries its tick's direction in the key, no other key is changed; states at the same position with opposite
    directions are kept as two cells; reaches are logged under the key the night keeps; the boundary answers follow the rule. Re-keying at
    the resume (zero ticks): two plans of the same resume give the same set; the re-keyed keys are the folder's stored keys (idempotent); a
    plain folder resumed with the option gets its moving-floor cells re-keyed from their ticks; with the option off the keys are plain."""
    b = dbench()
    D = _dir7(b)
    _clean(D, 240)
    o = D["summary"]["order"]
    rec = dict(O.direction_key_record(), lines=list(FAKE_DIR_LINES))
    check(o["keep_rule"]["floor_direction_key"] == rec and D["config"]["order_params"]["floor_direction_key"] is True and "## Floor-direction key" in D["report"],
          f"the records state the key: {o['keep_rule'].get('floor_direction_key')}")
    rows = [c for c in D["cells"] if c["ev"] in ("new", "replaced")]
    check(all(_dir_ok(c) for c in rows), "every kept key: the direction on the stand-in line, plain elsewhere")
    mf = [c for c in rows if c["key"][2] == osel.GROUNDED and int(c["key"][4]) >= 1000]
    pos: Dict[Tuple[Any, ...], set] = {}
    for c in mf:
        pos.setdefault(tuple(c["key"][:4]), set()).add(int(c["key"][4]))
    both = [p for p, fs in pos.items() if len(fs) == 2]
    check(mf and both, f"same position, opposite directions: two cells ({len(both)} positions of {len(pos)})")
    check(all(int(d["key"][4]) < 1000 or d["key"][2] == osel.GROUNDED for d in D["deep"])
          and all(_dir_ok({"key": d["key"], "tick": d["tick"]}) for d in D["deep"] if int(d["level"]) < osel.TARGETS_TOTAL), "the deep reaches carry the night's keys")
    check(o["continuation"]["mismatches"] == 0 and o["continuation"]["checked"] > 0, f"boundary answers: {o['continuation']}")
    fin: Dict[int, Mapping[str, Any]] = {}
    for c in rows:
        fin[int(c["cid"])] = c
    cnt = Counter(f"{int(c['level'])}|{'down' if int(c['key'][4]) >= 2000 else 'up'}" for c in fin.values() if c["key"][2] == osel.GROUNDED and int(c["key"][4]) >= 1000)
    check(o["floor_direction_key"]["cells_by_level_direction"] == {k: cnt[k] for k in sorted(cnt)}, f"the summary's counts: {o['floor_direction_key']}")
    saved = O.MOVING_FLOOR_LINES
    O.MOVING_FLOOR_LINES = FAKE_DIR_LINES
    try:
        on = osel.OrderParams(slack=200, open_line_from=7, floor_direction_key=True)
        off = osel.OrderParams(slack=200, open_line_from=7)
        P1, P2 = (O.build_plan(b.lab, b.frontier, b.lab / f"order_dir_preview_{i}", on, O.engine_params(on, rng_seed=5), code="preview", resume=[D["out"]])
                  for i in (1, 2))
        check(P1["resume"]["set_digest"] == P2["resume"]["set_digest"] and P1["resume"]["counts"] == P2["resume"]["counts"], "re-keying at the resume is deterministic")
        seq, _rec = O.resume_selection([D["out"]], osel.Pace(on))
        stored = {(c["digest"], int(c["tick"])): list(c["key"]) for c in fin.values()}
        check(all(e["key"] == stored[(e["cand"]["digest"], int(e["cand"]["tick"]))] for e in seq), "the re-keyed keys are the stored keys")
        fk = Counter(f"{int(c['level'])}|{'down' if int(k[4]) >= 2000 else 'up'}" for k, c in O.resume_finals(seq).items() if int(k[4]) >= 1000)
        check(P1["resume"]["floor_direction_cells"] == {k: fk[k] for k in sorted(fk, key=lambda s_: (-int(s_.split("|")[0]), s_))} and fk,
              f"the plan counts the inherited moving-floor cells: {P1['resume']['floor_direction_cells']}")
        seq_off, _r = O.resume_selection([D["out"]], osel.Pace(off))
        check(all(int(e["key"][4]) < 1000 for e in seq_off) and len(seq_off) <= len(seq), f"off: plain keys ({len(seq_off)} cells, {len(seq)} with the key)")
        A = _open7(b)
        seq_p, _r2 = O.resume_selection([A["out"]], osel.Pace(on))
        g4 = [e for e in seq_p if e["key"][2] == osel.GROUNDED and O.plain_floor(int(e["key"][4])) in FAKE_DIR_LINES]
        check(g4 and all(int(e["key"][4]) == O.plain_floor(int(e["key"][4])) + O.DIR_FLOOR_OFFSET[O.platform_direction(int(e["cand"]["tick"]))] for e in g4),
              f"a plain folder resumed with the key: its stand-in-floor cells re-keyed from their ticks ({len(g4)})")
    finally:
        O.MOVING_FLOOR_LINES = saved
    return {"moving_floor_cells": len(mf), "positions_both_directions": len(both), "resume_cells": len(seq), "resume_cells_off": len(seq_off),
            "plain_folder_rekeyed": len(g4)}


def e2e_e20_v7_hitter() -> Dict[str, Any]:
    """All three v7 options on (with the open line, the cut, a resume from E19's night and the stand-in moving line), with and without the
    hitter record: the same decisions (E12's checks), the hitter fields on every credited break, and the same bound and cut readouts; the
    resumed cells keep the keys E19's night stored; the inherited level-7+ cells at or past B stay in the archive, undrawable (the plan's
    count is the open's) and are never dispatched."""
    b = dbench()
    B = _fake_bound(b)
    D = _dir7(b)
    order = {"slack": 200, "open_line_from": 7, "fall_cut_y": FAKE_CUT_Y, "fall_cut_spare_one_live": True, "record_bound": B, "floor_direction_key": True}
    eng = dict(E_ENGINE, max_dispatches=160, rng_seed=12)
    A = b.run("v7all", order=order, resume=[str(D["out"])], engine=eng, port_base=41000, dir_lines=list(FAKE_DIR_LINES))
    H = b.run("v7all_hit", order=order, resume=[str(D["out"])], engine=eng, port_base=42000, dir_lines=list(FAKE_DIR_LINES), hitter=True, fake_entity=True)
    for r in (A, H):
        _clean(r, 160)
    _same_decisions(A, H)
    n, kinds = _hitter_kinds(H)
    check(n > 0 and not kinds["unavailable"], f"credited breaks with their hitter: {dict(kinds)}")
    oa, oh = A["summary"]["order"], H["summary"]["order"]
    check(oa["record_bound"] == oh["record_bound"] and oa["fall_cut"] == oh["fall_cut"] and oa["floor_direction_key"] == oh["floor_direction_key"], "the same v7 readouts")
    stored = {c["digest"]: list(c["key"]) for c in D["cells"] if c["ev"] in ("new", "replaced")}
    res_rows = [c for c in A["cells"] if (c.get("origin") or {}).get("kind") == "resume"]
    check(res_rows and all(c["key"] == stored[c["origin"]["d_digest"]] for c in res_rows), f"the resumed cells keep E19's keys: {len(res_rows)}")
    past = [c for c in res_rows if int(c["level"]) >= 7 and int(c["tick"]) >= B]
    lvc = dict(sorted(Counter(str(c["level"]) for c in past).items(), key=lambda kv: -int(kv[0])))
    check(past and oa["keep_rule"]["record_bound_inherited_undrawable"] == lvc == oa["record_bound"]["inherited_undrawable_at_open"],
          f"the inherited cells past B: plan {oa['keep_rule']['record_bound_inherited_undrawable']}, open {oa['record_bound']['inherited_undrawable_at_open']}, rows {lvc}")
    started = {str(x["draw_id"]).rsplit("|", 1)[1] for x in _bursts(A)}
    check(not ({c["digest"] for c in past} & started), "no dispatch from an inherited cell past B")
    return {"B": B, "credited_breaks": n, "kinds": dict(kinds), "inherited_past_b": lvc, "resumed": len(res_rows)}


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
    """T-M2: D's manifest covers its import closure (D's three modules and every run 3 file), hashes with LF line endings, is enforced at
    the open, and a change during the run is SEARCH_INVALID at the close."""
    import run3_manifest as rm

    b = dbench()
    A = b.run("a")
    oc = A["config"]["order_code"]
    files = set(oc["files"])
    run3 = set(rm.run3_code_manifest())
    d_own = {"tools/frs/order_search.py", "tools/frs/order_select.py", "tools/frs/order_worker.py"}
    check(oc["digest"] == oc["expected"] == A["plan"]["code"]["digest"] and d_own <= files and run3 <= files
          and len(files) == len(run3) + len(d_own), f"D's manifest: {len(files)} files = run 3's {len(run3)} + D's {len(d_own)}")
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
                                unit_u14_tree_sampler, unit_cont_window_rule, unit_burst_extent, unit_resume_lineage, unit_tm1_run3_digest,
                                unit_open_line_rule, unit_open_line_params, unit_open_line_draw, unit_open_line_plan, unit_break_record,
                                unit_hitter_rule, unit_hitter_tracker, unit_hitter_break_record, unit_hitter_plan, unit_group_fewest_draw, unit_group_weights,
                                unit_fall_cut_params, unit_fall_cut_rule, unit_fall_cut_selector, unit_fall_cut_plan,
                                unit_v7_params, unit_record_bound_rule, unit_record_bound_selector, unit_one_live_rule, unit_direction_key, unit_v7_plan)}

E2E = {f.__name__: f for f in (e2e_e1_same_seed, e2e_e2_root, e2e_e3_pace_budget, e2e_e4_milestone, e2e_e5_caps_stops, e2e_e6_exports,
                               e2e_e7_resume, e2e_e8_long_bursts, e2e_e9_scoreboard, e2e_e10_extent, e2e_u11_isolation, e2e_u13_no_human_input,
                               e2e_tm2_code_digest, e2e_e11_open_line, e2e_e12_hitter_record, e2e_e13_fall_cut, e2e_e14_fall_cut_resume,
                               e2e_e15_fall_cut_hitter, e2e_e16_clear_below_cut, e2e_e17_record_bound, e2e_e18_one_live, e2e_e19_direction_key,
                               e2e_e20_v7_hitter)}
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
