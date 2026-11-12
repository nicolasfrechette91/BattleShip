#!/usr/bin/env python3
"""Option D tests (docs/frs_option_d_design_2026-11-11.md section 9). Zero native ticks: no ROM, no game process. Phase 1 covers the
selection (tools/frs/order_select.py) with pure in-process tests (a fake archive and a fake burst oracle, U2 to U12) and the run 3
manifest check (T-M1).

    python -B tools/frs/order_search_tests.py            every test
    python -B tools/frs/order_search_tests.py unit       the in-process tests only
    python -B tools/frs/order_search_tests.py <name>...  the named tests
"""
from __future__ import annotations

import hashlib
import json
import random
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

assert sys.flags.dont_write_bytecode, "run with python -B"

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
RL = REPO / "rl"
for _p in (RL, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import order_select as osel  # noqa: E402
import run3_select as rs  # noqa: E402
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
        row = {"outcome": "clear" if claim else "end", "claimed": claim, "advanced": bool(breaks), "levels": {}}
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
    return {"groups": sorted(rs.glabel(g) for g in sel.gall)}


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
    check(sel.set_count[W4] == 0 and sel.order_count[sel.group[k_deep[1].cid]] == 0, "a newcomer with no sibling in the rotation starts at 0")
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
    return {"set_counts": {osel.slabel(k): int(v) for k, v in sorted(sel.set_count.items())}, "dstat": dict(sel.dstat)}


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
        sel = s.selector(retire_after=4)              # small R: retirements, leaves and returns happen in 3,000 dispatches
        runs.append((s, sel, run_fake(sel, s.a, Game(pm), random.Random(20261112), 3000)))
    (s0, a, q0), (_s1, b, q1) = runs
    check(len(q0) == 3000 and q0 == q1, "the same dispatch sequence (cell, stream, level, rank, kept cells, milestones, retirements) with the labels permuted")
    check({(lv, Game.pm(m, perm)): v for (lv, m), v in a.set_count.items()} == dict(b.set_count), "the same set counts, relabelled")
    check({(lv, Game.pm(m, perm), _plabel(lb, perm)): v for (lv, m, lb), v in a.order_count.items()} == dict(b.order_count),
          "the same order counts, relabelled")
    check(a.milestones.records() == b.milestones.records() and a.retired == b.retired and a.pace.rejected.summary() == b.pace.rejected.summary(),
          "the same milestones, retirements and rejected reaches")
    check(dict(a.stale) == dict(b.stale) and dict(a.bcount) == dict(b.bcount), "the same staleness and breadth counts")
    streams = Counter(x[2] for x in q0)
    per_level = a.level_readout()
    many = max(v["sets"] for v in per_level.values())
    check(streams["breadth"] and streams["rank"] and streams["anchor"] and a.dstat["retired"] > 0 and a.milestones.met and many >= 3,
          f"a non-trivial run: streams {dict(streams)}, retired {a.dstat['retired']}, milestones {sorted(a.milestones.met)}, sets at one level {many}")
    return {"streams": dict(streams), "cells": len(s0.a.cells), "retired": a.dstat["retired"], "milestones": sorted(a.milestones.met),
            "deepest": max(c.level for c in s0.a.cells), "rotation": {k: int(v) for k, v in sorted(a.dstat.items())}}


UNIT = {f.__name__: f for f in (unit_u1_pace_line, unit_u2_rejected_readout, unit_u2_group_move, unit_u3_root_and_niches, unit_u4_set_then_order,
                                unit_u4_ties, unit_u4_cell_draw_is_run3s, unit_u5_newcomers, unit_u6_level_weights, unit_u7_retirement,
                                unit_u8_milestones, unit_u9_claims, unit_u10_params, unit_u12_relabelling, unit_tm1_run3_digest)}

if __name__ == "__main__":
    args = sys.argv[1:]
    groups = {"unit": UNIT}
    tests = dict(groups[args[0]]) if args[:1] and args[0] in groups else dict(UNIT)
    rest = [x for x in args if x not in groups]
    sys.exit(run_suite("option D tests", tests, rest))
