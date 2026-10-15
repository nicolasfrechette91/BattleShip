#!/usr/bin/env python3
"""Crossing search (lab, exploratory, unregistered): a cell-based exploration from the fast states the frontier continuation
search found (docs/frs_frontier_2026-10-14.md), to get across to the other side of the stage and finish a clear faster than the
lab import's best verified clear (the reference).

Seeds (generic rule, no hand-picking): among the frontier search's states (every member of its frontier files, each with its
exact prefix, cell key and end-record digests), those at the deepest level the search's OWN bursts reached ahead of the
reference's pace (read from its dispatch rows: a level arrival with a positive pace), and at the level below it; one state per
cell key (the earliest arrival); ordered by (level, lead) or by lead alone; the top S. Every seed's prefix is re-derived at zero
ticks from the frontier's rows (the parent's prefix plus the keyed burst to the arrival, back to the probe start) and, at the
run's open, replayed from tick 0 in a fresh process: the chain digest, the record digest and the cell key at its last tick must
equal the frontier's record, every tick under the tick contract; the reach gives the state's end record.

Archive: every reach of a burst (the first visit of a cell key inside the job) is kept with its exact prefix when its key is
new to the archive (a new cell) or its tick is strictly below the cell's representative (a faster arrival replaces the
representative, which becomes a fresh start); a later arrival at a known key only counts as a visit (`seen`); a reach past the
E7 bound (it can no longer beat the reference minus the registered margin) is never kept; the burst's own start key and
terminal reaches are skipped. Intermediate states that break no target become starts this way (the chain mechanism of the
record's own crossing, docs/frs_crossing_2026-10-14.md section 1.2).

Selection (every idle worker draws one start): first a level, with weight decay^(deepest eligible level - level) (the deepest
level 1, the next `decay`, ...), then a cell within the level with weight

    (1 + fresh)^-novelty  x  (1 + seen)^-seen_exp  x  (1 + breaks)^bonus_exp  x  slack^pace_exp

(fresh = dispatches since the representative was set, seen = later arrivals at the key, breaks = dispatches of the cell that
broke a target, slack = E7 bound - tick + 1). Only generic quantities: level, novelty, arrival count, break record, arrival time.
No coordinate, target id, direction, cell id, route or census number is in this file. The seen penalty and the break bonus are
switches (on by default); retirement is off by default (the novelty term is a soft retirement). Bursts: the lab's CONT explorer
(the m8_rd_explore_v1 keyed stream, 120-word segments, continuation under the F3 trigger read on this run's own archive), with
the maximum number of segments as an argument.

Clears: every claimed clear is replayed from tick 0 in a fresh process with the verify flags, twice, as soon as a worker can be
lent (rl/frs_verify.verify_twice), and counts only when both replays agree exactly with each other and with the in-run claim;
candidates still pending at a stop are verified at the close. progress.md (rewritten at least every minute and on every event)
shows at the top every verified clear against the reference, the deepest level reached with its earliest tick, and the cells
per level.

    python -B tools/frs/crossing_search.py plan --lab-root C:/BattleShip_lab --frontier DIR [--out DIR] [--seeds S ...]
    python -B tools/frs/crossing_search.py run  --lab-root ... --frontier DIR --out DIR [--workers 5] [--max-wall-min 420] ...

`plan` is zero native ticks; `run` is native. Writes only under the output folder (default <lab root>/crossing_<date>) through the
lab's guard (rl/frs_guard: refuses the checkout, any runs/ folder and the D: evidence roots; never reads runs/); the lab lock;
readiness at the registered thresholds, never lowered; at most 5 workers with one standby each (at most 10 game processes);
the lab's memory budget (a soft breach is a clean stop) and projection; a tick cap, a wall cap, a cells cap. Nothing reads
native RNG. Process restart resets the episode: every seed replay, every burst and every verification replay is a fresh process
from tick 0. Zero-tick tests: tools/frs/crossing_search_tests.py. Run with python -B.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import random
import sys
import threading
import time
import traceback
from bisect import bisect_right
from dataclasses import dataclass, field
from itertools import accumulate
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

assert sys.flags.dont_write_bytecode, "run with python -B"

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "rl"))
sys.path.insert(0, str(HERE))

import frs_archive as fa  # noqa: E402
import frs_guard as g  # noqa: E402
import frs_machine as fm  # noqa: E402
import frs_report as frep  # noqa: E402
import frs_run as fr  # noqa: E402
import frs_verify as fv  # noqa: E402
import frs_worker as fw  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_rule as mrule  # noqa: E402
import m8_rd_run as mrun  # noqa: E402
import m8_sd2_select as s6  # noqa: E402

SEARCH_CONTRACT = "frs_crossing_search_v1"
KEY_FAMILY = "crossing"
FRONTIER_CONTRACT = "frs_frontier_search_v1"
FRONTIER_KEY_FAMILY = "frontier"
ARM_NAME = "CONT"
ARM_BASE: Dict[str, int] = dict(fr.ARMS[ARM_NAME])         # segment words 120, max segments 4, F3 window 20: the lab's CONT arm
MARGIN = fr.MARGIN                                         # E7's registered margin
FRONTIER_FILES = ("plan.json", "starts.jsonl", "run/config.json", "run/dispatches.jsonl")
FRONTIER_DIR = "run/frontier"
BAD_OUTCOMES = ("mismatch", "lifecycle", "aborted")
END_NAMES = {"clear": "clear", "fall": "fall", "length": "out_of_words", "horizon": "horizon", "ended": "ended", "cut": "cut"}
SEED_ORDERS = ("level", "lead")
NEW, REPLACED, LATER, SELF, BEYOND, TERMINAL, DEEP = "new", "replaced", "later", "self", "beyond", "terminal", "deep"
EXIT = {"COMPLETED": 0, "ARCHIVE_EMPTY": 0, "TICK_CAP": 0, "WALL_CAP": 0, "CELLS_CAP": 0, "DISPATCH_CAP": 0, "MEMORY_BUDGET": 0, "REFUSED": 2,
        "SEARCH_INVALID": 3, "SEARCH_INCOMPLETE": 4}
STATUS_RANK = {"COMPLETED": 0, "ARCHIVE_EMPTY": 0, "TICK_CAP": 1, "WALL_CAP": 1, "CELLS_CAP": 1, "DISPATCH_CAP": 1, "MEMORY_BUDGET": 1,
               "SEARCH_INCOMPLETE": 2, "SEARCH_INVALID": 3}
SEEN_BUCKETS = ((0, 2), (3, 5), (6, 15), (16, 10 ** 9))
CELL_OVERHEAD_BYTES = 1400                                 # Python objects around the words of one cell (estimate for the plan's projection)


class SearchError(RuntimeError):
    """A violated search invariant (zero-tick)."""


class Refused(Exception):
    """Open-phase refusal: nothing was launched."""


# -- parameters -------------------------------------------------------------------------------------------------------------------------


@dataclass
class Params:
    seeds: int = 48                 # S: the top S states of the seed rule
    seed_order: str = "level"       # level: (level desc, lead desc); lead: lead desc over both levels
    level_decay: float = 0.5        # level draw: weight decay^(deepest eligible level - level)
    novelty_exp: float = 1.0        # within a level: (1 + dispatches since the representative was set)^-novelty_exp
    seen_exp: float = 1.0           # (1 + later arrivals at the key)^-seen_exp; 0 = switch off
    bonus_exp: float = 1.0          # (1 + dispatches that broke a target)^bonus_exp; 0 = switch off
    pace_exp: float = 0.5           # (E7 bound - tick + 1)^pace_exp: earlier arrivals weigh more
    max_segments: int = 6           # CONT continuation: at most max_segments - 1 continuations (the lab arm's 4)
    retire_after: int = 0           # a cell with this many dispatches, no break and no new cell is retired; 0 = off
    max_cells: int = 600_000        # a clean stop when the archive holds this many cells (a backstop behind the memory budget)
    max_dispatches: int = 0         # a clean stop after this many dispatches; 0 = none
    rng_seed: int = 1               # the Python experiment seed of the draws (never a native seed)

    def check(self) -> None:
        if self.seeds < 1 or self.max_segments < 1 or self.max_cells < 1 or self.retire_after < 0 or self.max_dispatches < 0:
            raise SearchError("refused: --seeds, --max-segments and --max-cells are positive; --retire-after and --max-dispatches are not negative")
        if self.seed_order not in SEED_ORDERS:
            raise SearchError(f"refused: --seed-order is one of {SEED_ORDERS}")
        if not 0.0 < self.level_decay <= 1.0:
            raise SearchError("refused: --level-decay is in (0, 1]")
        for name in ("novelty_exp", "seen_exp", "bonus_exp", "pace_exp"):
            if getattr(self, name) < 0.0:
                raise SearchError(f"refused: --{name.replace('_', '-')} is not negative")

    def arm(self) -> Dict[str, int]:
        return dict(ARM_BASE, max_segments=int(self.max_segments))

    def as_dict(self) -> Dict[str, Any]:
        return {"seeds": self.seeds, "seed_order": self.seed_order, "level_decay": self.level_decay, "novelty_exp": self.novelty_exp,
                "seen_exp": self.seen_exp, "bonus_exp": self.bonus_exp, "pace_exp": self.pace_exp, "max_segments": self.max_segments,
                "retire_after": self.retire_after, "max_cells": self.max_cells, "max_dispatches": self.max_dispatches, "rng_seed": self.rng_seed}


# -- the archive: cells, keep / replace, E7, selection (zero native ticks) -----------------------------------------------------------------


@dataclass
class Cell:
    cid: int
    key: Tuple[int, int, str, int, int]
    level: int
    tick: int
    lead: int
    words: Optional[bytes]
    end: Tuple[Any, ...]
    end_digest: bytes
    chain: bytes
    digest: str
    origin: Dict[str, Any]
    created_at: int                                  # the dispatch count when the cell (or its current representative) was kept
    seen: int = 0                                    # later arrivals at the key
    dispatched: int = 0
    fresh: int = 0                                   # dispatches since the representative was set
    breaks: int = 0                                  # dispatches that broke at least one target
    new_children: int = 0                            # new cells its dispatches created
    replaced: int = 0                                # how often the representative was replaced by a faster arrival
    quarantined: Optional[str] = None
    retired: Optional[str] = None
    next_k: int = 0
    first_level_reach: bool = False                  # the first arrival ever at its level in this run
    previous: Optional[Dict[str, Any]] = None        # the representative a faster arrival replaced (tick, digest, origin)

    def alive(self) -> bool:
        return self.words is not None and self.quarantined is None and self.retired is None

    def draw_id(self, archive_id: str) -> str:
        return f"{archive_id}|{KEY_FAMILY}|{self.digest}"

    def row(self, *, words: bool = False) -> Dict[str, Any]:
        out = {"cid": self.cid, "key": list(self.key), "level": self.level, "tick": self.tick, "lead": self.lead, "digest": self.digest,
               "end_digest": self.end_digest.hex(), "chain": self.chain.hex(), "origin": self.origin, "created_at": self.created_at, "seen": self.seen,
               "dispatched": self.dispatched, "fresh": self.fresh, "breaks": self.breaks, "new_children": self.new_children, "replaced": self.replaced,
               "quarantined": self.quarantined, "retired": self.retired, "has_words": self.words is not None}
        if words and self.words is not None:
            out["words_hex"] = self.words.hex()
        return out


class Archive:
    """Every state the search knows, keyed by its cell key; the representative of a key is its earliest arrival."""

    def __init__(self, archive_id: str, arrival: Mapping[Any, int], bound: int, params: Params):
        self.archive_id = str(archive_id)
        self.arrival = {int(k): int(v) for k, v in arrival.items()}
        self.bound = int(bound)
        self.p = params
        self.cells: List[Cell] = []
        self.by_key: Dict[Tuple[int, int, str, int, int], int] = {}
        self.by_level: Dict[int, List[int]] = {}
        self.counts = {"cells": 0, NEW: 0, REPLACED: 0, LATER: 0, SELF: 0, BEYOND: 0, TERMINAL: 0, DEEP: 0, "quarantined": 0, "retired": 0, "freed": 0}
        self.earliest: Dict[int, Dict[str, Any]] = {}
        self.words_bytes = 0
        # the cached selection weights per level (aligned with by_level), recomputed only for the cells touched since the last draw
        self._w: Dict[int, List[float]] = {}
        self._pos: Dict[int, int] = {}
        self._dirty: Dict[int, set] = {}
        self._nelig: Dict[int, int] = {}

    # -- readings ------------------------------------------------------------------------------------------------------------------------

    def lead_of(self, level: int, tick: int) -> int:
        return int(self.arrival.get(int(level), 0)) - int(tick)

    def slack_of(self, tick: int) -> int:
        return self.bound - int(tick) + 1

    def eligible(self, c: Cell) -> bool:
        return c.alive() and c.level < mcell.TARGETS_TOTAL and c.tick <= self.bound

    def eligible_cids(self, level: int) -> List[int]:
        return [i for i in self.by_level.get(int(level), []) if self.eligible(self.cells[i])]

    def levels_present(self) -> List[int]:
        for lv in self.by_level:
            self._apply(lv)
        return sorted(lv for lv in self.by_level if self._nelig.get(lv, 0) > 0)

    def touch(self, c: Cell) -> None:
        """A cell whose statistics or eligibility changed: its cached weight is recomputed at the next draw."""
        self._dirty.setdefault(c.level, set()).add(c.cid)

    def refresh(self) -> None:
        for lv, cids in self.by_level.items():
            self._dirty.setdefault(lv, set()).update(cids)

    def _apply(self, lv: int) -> None:
        d = self._dirty.get(lv)
        if not d:
            return
        w = self._w[lv]
        n = self._nelig.get(lv, 0)
        for cid in d:
            pos = self._pos[cid]
            old = w[pos]
            c = self.cells[cid]
            new = self.cell_weight(c) if self.eligible(c) else 0.0
            w[pos] = new
            n += int(new > 0) - int(old > 0)
        self._nelig[lv] = n
        d.clear()

    def deepest(self) -> Optional[Dict[str, Any]]:
        if not self.earliest:
            return None
        lv = max(self.earliest)
        return dict(self.earliest[lv], level=lv, reference=self.arrival.get(lv))

    def continuation_decision(self, reaches: Sequence[Sequence[Any]]) -> Dict[str, Any]:
        """F3's trigger on this run's archive: any reported reach (j, key) whose key is new, or whose j is strictly below the representative."""
        new = shorter = n = 0
        gain = 0
        for j, k in reaches:
            n += 1
            cid = self.by_key.get(fa.norm_key(k))
            if cid is None:
                new += 1
                continue
            gg = self.cells[cid].tick - int(j)
            if gg > 0:
                shorter += 1
                gain = max(gain, gg)
        return {"reaches": n, "new": new, "shorter": shorter, "max_gain": gain, "go": (new + shorter) > 0, "cells": len(self.cells)}

    # -- keeping -------------------------------------------------------------------------------------------------------------------------

    def _note_earliest(self, c: Cell, n_dispatch: int) -> bool:
        e = self.earliest.get(c.level)
        first = e is None
        if first or c.tick < e["tick"]:
            self.earliest[c.level] = {"tick": c.tick, "cid": c.cid, "lead": c.lead, "at_dispatch": n_dispatch, "utc": g.utc()}
        return first

    def keep(self, key: Sequence[Any], level: int, tick: int, words: bytes, end: Sequence[Any], end_digest: bytes, chain: bytes,
             origin: Mapping[str, Any], n_dispatch: int, *, self_key: Optional[Tuple[Any, ...]] = None, terminal: bool = False) -> Tuple[str, Optional[Cell]]:
        """(verdict, the cell kept or replaced). NEW: the key is new; REPLACED: an earlier arrival than the representative; LATER: a later
        arrival (a visit, nothing kept); SELF: the burst's own start key; BEYOND: past the E7 bound; TERMINAL; DEEP: a cleared mask."""
        k = fa.norm_key(key)
        tick, level = int(tick), int(level)
        if terminal:
            self.counts[TERMINAL] += 1
            return TERMINAL, None
        if level >= mcell.TARGETS_TOTAL:
            self.counts[DEEP] += 1
            return DEEP, None
        if mcell.level_of_mask(k[3]) != level:
            raise SearchError(f"a key's level {mcell.level_of_mask(k[3])} is not the reach's level {level}")
        if len(words) != tick:
            raise SearchError(f"a cell's words are its tick ({len(words)} vs {tick})")
        if self_key is not None and k == self_key:
            self.counts[SELF] += 1
            return SELF, None
        if tick > self.bound:
            self.counts[BEYOND] += 1
            return BEYOND, None
        cid = self.by_key.get(k)
        if cid is None:
            c = Cell(cid=len(self.cells), key=k, level=level, tick=tick, lead=self.lead_of(level, tick), words=bytes(words), end=tuple(end),
                     end_digest=bytes(end_digest), chain=bytes(chain), digest=mcell.words_digest(words), origin=dict(origin), created_at=int(n_dispatch))
            self.cells.append(c)
            self.by_key[k] = c.cid
            self.by_level.setdefault(level, []).append(c.cid)
            self._pos[c.cid] = len(self.by_level[level]) - 1
            self._w.setdefault(level, []).append(0.0)
            self.touch(c)
            self.counts["cells"] += 1
            self.counts[NEW] += 1
            self.words_bytes += tick
            c.first_level_reach = self._note_earliest(c, n_dispatch)
            return NEW, c
        c = self.cells[cid]
        c.seen += 1
        self.touch(c)
        if tick >= c.tick:
            self.counts[LATER] += 1
            return LATER, c
        if c.words is not None:
            self.words_bytes -= len(c.words)
        c.previous = {"tick": c.tick, "digest": c.digest, "origin": dict(c.origin), "dispatched": c.dispatched, "fresh": c.fresh, "quarantined": c.quarantined, "retired": c.retired}
        c.tick, c.lead, c.words, c.end, c.end_digest, c.chain = tick, self.lead_of(level, tick), bytes(words), tuple(end), bytes(end_digest), bytes(chain)
        c.digest = mcell.words_digest(words)
        c.origin = dict(origin)
        c.created_at = int(n_dispatch)
        c.fresh = 0
        c.next_k = 0                                     # a new representative is a new key family: its iterations start at 0
        c.replaced += 1
        c.quarantined = None
        c.retired = None
        self.words_bytes += tick
        self.counts[REPLACED] += 1
        self._note_earliest(c, n_dispatch)
        return REPLACED, c

    def quarantine(self, c: Cell, why: str) -> None:
        c.quarantined = why[:200]
        if c.words is not None:
            self.words_bytes -= len(c.words)
            c.words = None
        self.counts["quarantined"] += 1
        self.touch(c)

    def retire_check(self, c: Cell, why_prefix: str) -> bool:
        r = self.p.retire_after
        if r <= 0 or not c.alive() or c.breaks > 0 or c.new_children > 0 or c.fresh < r:
            return False
        c.retired = f"{why_prefix}: {c.fresh} dispatches without a break or a new cell"
        if c.words is not None:
            self.words_bytes -= len(c.words)
            c.words = None
        self.counts["retired"] += 1
        self.touch(c)
        return True

    # -- selection -----------------------------------------------------------------------------------------------------------------------

    def level_weights(self) -> Dict[int, float]:
        levels = self.levels_present()
        if not levels:
            return {}
        top = max(levels)
        return {lv: self.p.level_decay ** (top - lv) for lv in levels}

    def cell_weight(self, c: Cell) -> float:
        p = self.p
        w = (1.0 + c.fresh) ** (-p.novelty_exp)
        if p.seen_exp > 0:
            w *= (1.0 + c.seen) ** (-p.seen_exp)
        if p.bonus_exp > 0:
            w *= (1.0 + c.breaks) ** p.bonus_exp
        if p.pace_exp > 0:
            w *= float(max(1, self.slack_of(c.tick))) ** p.pace_exp
        return w

    def select(self, rng: random.Random) -> Optional[Tuple[Cell, Dict[str, Any]]]:
        """One start: a level by the level weights, then a cell by its weight. Returns the cell and the draw's shares (for the record)."""
        lw = self.level_weights()
        if not lw:
            return None
        levels = sorted(lw)
        total = sum(lw.values())
        r = rng.random() * total
        lv = levels[-1]
        acc = 0.0
        for cand in levels:
            acc += lw[cand]
            if r < acc:
                lv = cand
                break
        self._apply(lv)
        w = self._w.get(lv) or []
        cum = list(accumulate(w))
        tot = cum[-1] if cum else 0.0
        if tot <= 0:
            return None
        r2 = rng.random() * tot
        pos = min(bisect_right(cum, r2), len(w) - 1)
        while pos > 0 and w[pos] <= 0:                                   # never a zero-weight entry (a float corner case only)
            pos -= 1
        c = self.cells[self.by_level[lv][pos]]
        return c, {"p_level": round(lw[lv] / total, 5), "w_share": round(w[pos] / tot, 6), "level_eligible": self._nelig.get(lv, 0),
                   "levels": {str(k): round(v / total, 4) for k, v in lw.items()}}

    # -- stats ---------------------------------------------------------------------------------------------------------------------------

    def per_level(self) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for lv in sorted(self.by_level, reverse=True):
            cs = [self.cells[i] for i in self.by_level[lv]]
            el = [c for c in cs if self.eligible(c)]
            e = self.earliest.get(lv) or {}
            out[str(lv)] = {"cells": len(cs), "eligible": len(el), "alive": sum(1 for c in cs if c.alive()), "dispatched_cells": sum(1 for c in cs if c.dispatched),
                            "dispatches": sum(c.dispatched for c in cs), "cells_with_breaks": sum(1 for c in cs if c.breaks), "replaced": sum(c.replaced for c in cs),
                            "seen_total": sum(c.seen for c in cs), "earliest_tick": e.get("tick"), "reference": self.arrival.get(lv),
                            "best_lead": (self.arrival.get(lv, 0) - e["tick"]) if e else None, "max_dispatched": max((c.dispatched for c in cs), default=0),
                            "quarantined": sum(1 for c in cs if c.quarantined), "retired": sum(1 for c in cs if c.retired)}
        return out

    def stats(self) -> Dict[str, Any]:
        alive = sum(1 for c in self.cells if c.alive())
        return dict(self.counts, alive=alive, eligible=sum(1 for c in self.cells if self.eligible(c)), words_mb=round(self.words_bytes / 2 ** 20, 1),
                    deepest_level=max(self.earliest) if self.earliest else None, levels=len(self.by_level))


# -- the frontier search's outputs and the seed rule (zero native ticks) -----------------------------------------------------------------


def read_jsonl(p: Path) -> List[Dict[str, Any]]:
    with open(p, encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def read_reference(lab_root: Path, analyse: fv.Analyse = fv.real_analyse) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """The imported best verified clear (rl/frs_verify.load_reference) with its arrival tick per level (level n = its n-th break), and the
    archive meta of the import (the tick-0 pin, the archive id) read from archive_meta.json (the archive itself is not loaded)."""
    imp = Path(lab_root) / "import"
    R = fv.load_reference(imp / "reference", analyse)
    if R["problems"]:
        raise SearchError(f"reference: {R['problems']}")
    breaks = sorted((int(t), int(i)) for t, i in R["expected"]["breaks"])
    R["arrival"] = {0: 0, **{n + 1: t for n, (t, _i) in enumerate(breaks)}}
    meta = json.loads((imp / "archive" / "archive_meta.json").read_text(encoding="utf-8"))
    if not meta.get("pin_tick0") or not meta.get("archive_id"):
        raise SearchError("refused: the import's archive_meta.json carries no tick-0 pin or archive id")
    return R, meta


def slim_row(r: Mapping[str, Any]) -> Dict[str, Any]:
    keep = ("round", "kind", "sid", "k", "level", "start_tick", "draw_id", "outcome", "words_played", "ticks", "wall_s", "levels", "pace", "advanced",
            "decisions", "words_hex")
    return {k: r.get(k) for k in keep}


def read_frontier(frontier_dir: Path) -> Dict[str, Any]:
    """The frontier search's outputs (read-only): its plan, its run configuration, its probe starts, every frontier member ever written
    (with its exact prefix) and its dispatch rows (slimmed)."""
    fd = Path(frontier_dir)
    missing = [f for f in FRONTIER_FILES if not (fd / f).is_file()]
    if missing or not (fd / FRONTIER_DIR).is_dir():
        raise SearchError(f"refused: {fd} is not a frontier search output folder (missing {missing or [FRONTIER_DIR]})")
    plan = json.loads((fd / "plan.json").read_text(encoding="utf-8"))
    if plan.get("contract") != FRONTIER_CONTRACT or plan.get("mode") != "lab":
        raise SearchError(f"refused: {fd / 'plan.json'} is not a {FRONTIER_CONTRACT} plan")
    config = json.loads((fd / "run" / "config.json").read_text(encoding="utf-8"))
    starts = {int(r["sid"]): r for r in read_jsonl(fd / "starts.jsonl")}
    states: Dict[int, Dict[str, Any]] = {}
    files = sorted((fd / FRONTIER_DIR).glob("round_*.jsonl"))
    if not files:
        raise SearchError(f"refused: {fd / FRONTIER_DIR} holds no frontier file")
    for f in files:
        for r in read_jsonl(f):
            if not r.get("has_words") or not r.get("words_hex") or not r.get("key"):
                continue
            prev = states.get(int(r["sid"]))
            if prev is None:
                states[int(r["sid"])] = {k: r[k] for k in ("sid", "level", "tick", "lead", "digest", "origin", "key", "end_digest", "chain", "words_hex")}
                states[int(r["sid"])]["first_file"] = f.name
            elif prev["digest"] != r["digest"] or prev["key"] != r["key"] or prev["tick"] != r["tick"]:
                raise SearchError(f"frontier state {r['sid']} differs between frontier files ({prev['first_file']}, {f.name})")
    rows: List[Dict[str, Any]] = []
    with open(fd / "run" / "dispatches.jsonl", encoding="utf-8") as fh:
        for ln in fh:
            if ln.strip():
                rows.append(slim_row(json.loads(ln)))
    summary = {}
    if (fd / "run" / "summary.json").is_file():
        summary = json.loads((fd / "run" / "summary.json").read_text(encoding="utf-8"))
    return {"dir": fd, "plan": plan, "config": config, "starts": starts, "states": states, "rows": rows, "summary": summary, "frontier_files": len(files)}


def deepest_burst_level(rows: Sequence[Mapping[str, Any]]) -> Tuple[Optional[int], Dict[str, int]]:
    """The deepest live level at which a burst of the frontier search arrived strictly ahead of the reference (its `pace` reading), and the
    count of such arrivals per level."""
    per: Dict[int, int] = {}
    for r in rows:
        if r.get("kind") != "burst" or r.get("outcome") in BAD_OUTCOMES:
            continue
        for lv, pace in (r.get("pace") or {}).items():
            if int(lv) < mcell.TARGETS_TOTAL and int(pace) > 0:
                per[int(lv)] = per.get(int(lv), 0) + 1
    return (max(per) if per else None), {str(k): v for k, v in sorted(per.items(), reverse=True)}


def seed_rule(F: Mapping[str, Any], arrival: Mapping[int, int], bound: int, params: Params) -> Dict[str, Any]:
    """crossing_seed_v1: the frontier states at the deepest level its own bursts reached ahead of pace and at the level below it, one per
    cell key (the earliest arrival), ordered, the top S; each checked (words = tick, digest, lead, key level, within the E7 bound)."""
    D, per_arrival = deepest_burst_level(F["rows"])
    if D is None:
        raise SearchError("refused: no burst of the frontier search arrived ahead of the reference at any level")
    levels = [D, D - 1] if D - 1 >= 0 else [D]
    pool = [s for s in F["states"].values() if int(s["level"]) in levels]
    by_key: Dict[Tuple[int, int, str, int, int], Dict[str, Any]] = {}
    for s in sorted(pool, key=lambda s: (int(s["tick"]), int(s["sid"]))):
        by_key.setdefault(fa.norm_key(s["key"]), s)
    cands = list(by_key.values())
    if params.seed_order == "level":
        cands.sort(key=lambda s: (-int(s["level"]), -int(s["lead"]), int(s["tick"]), int(s["sid"])))
    else:
        cands.sort(key=lambda s: (-int(s["lead"]), -int(s["level"]), int(s["tick"]), int(s["sid"])))
    chosen = cands[:params.seeds]
    seeds: List[Dict[str, Any]] = []
    for s in chosen:
        words = bytes.fromhex(s["words_hex"])
        lv, t = int(s["level"]), int(s["tick"])
        k = fa.norm_key(s["key"])
        if len(words) != t or mcell.words_digest(words) != s["digest"]:
            raise SearchError(f"frontier state {s['sid']}: its words are not its tick or its digest")
        if mcell.level_of_mask(k[3]) != lv or lv >= mcell.TARGETS_TOTAL:
            raise SearchError(f"frontier state {s['sid']}: the key's level is not the state's")
        lead = int(arrival[lv]) - t
        if lead != int(s["lead"]) or lead <= 0:
            raise SearchError(f"frontier state {s['sid']}: lead {s['lead']} is not the reference's {lead} (or not ahead)")
        if t > bound:
            raise SearchError(f"frontier state {s['sid']}: tick {t} is past the E7 bound {bound}")
        seeds.append({"fsid": int(s["sid"]), "level": lv, "tick": t, "lead": lead, "slack": bound - t + 1, "digest": s["digest"], "key": list(k),
                      "end_digest": s["end_digest"], "chain": s["chain"], "origin": s["origin"], "words": words, "first_file": s["first_file"]})
    per_level_pool: Dict[str, Dict[str, Any]] = {}
    for s in cands:
        d = per_level_pool.setdefault(str(s["level"]), {"keys": 0, "states": 0, "best_lead": None, "best_tick": None})
        d["keys"] += 1
    for s in pool:
        per_level_pool[str(s["level"])]["states"] += 1
    for s in cands:
        d = per_level_pool[str(s["level"])]
        if d["best_lead"] is None or int(s["lead"]) > d["best_lead"]:
            d["best_lead"], d["best_tick"] = int(s["lead"]), int(s["tick"])
    digest = hashlib.sha256("".join(f"{s['fsid']}:{s['digest']}:{s['level']}:{s['tick']};" for s in seeds).encode()).hexdigest()
    return {"deepest_burst_level": D, "burst_ahead_arrivals_per_level": per_arrival, "levels": levels, "pool_states": len(pool), "pool_keys": len(cands),
            "per_level_pool": dict(sorted(per_level_pool.items(), key=lambda kv: -int(kv[0]))), "seeds": seeds, "seed_set_digest": digest}


def seed_provenance(seed: Mapping[str, Any], F: Mapping[str, Any], archive_id: str) -> Dict[str, Any]:
    """Zero-tick re-derivation of a seed's prefix from the frontier's own rows: each burst link's words re-derive from the frontier's key family
    and iteration, the child's prefix is the parent's plus the burst to the arrival, back to a probe start whose digest the frontier's
    starts.jsonl records."""
    rows = F.setdefault("_rows_index", None)
    if rows is None:
        rows = {(int(r["round"]), int(r["sid"]), int(r["k"])): r for r in F["rows"] if r.get("kind") == "burst" and r.get("words_hex") is not None}
        F["_rows_index"] = rows
    words, origin, sid, depth = bytes(seed["words"]), dict(seed["origin"]), int(seed["fsid"]), 0
    tick = len(words)
    while origin.get("kind") == "burst":
        parent = F["states"].get(int(origin["parent"]))
        if parent is None:
            raise SearchError(f"seed {seed['fsid']}: its parent {origin['parent']} is in no frontier file")
        row = rows.get((int(origin["round"]), int(origin["parent"]), int(origin["k"])))
        if row is None:
            raise SearchError(f"seed {seed['fsid']}: no dispatch row for parent {origin['parent']} round {origin['round']} k {origin['k']}")
        burst = bytes.fromhex(row["words_hex"])
        pw = bytes.fromhex(parent["words_hex"])
        off = tick - int(parent["tick"])
        if not 1 <= off <= len(burst) or len(pw) != int(parent["tick"]):
            raise SearchError(f"seed {seed['fsid']}: the arrival at {tick} is outside its parent's burst ({parent['tick']} + {len(burst)})")
        want_draw = f"{archive_id}|{FRONTIER_KEY_FAMILY}|{parent['digest']}"
        if row["draw_id"] != want_draw:
            raise SearchError(f"seed {seed['fsid']}: the burst's key family {row['draw_id']} is not {want_draw}")
        if fa.stream_words(row["draw_id"], int(origin["k"]), len(burst)) != burst:
            raise SearchError(f"seed {seed['fsid']}: the recorded burst of parent {origin['parent']} k {origin['k']} does not re-derive from its key family")
        if words != pw + burst[:off]:
            raise SearchError(f"seed {seed['fsid']}: its prefix is not its parent's prefix plus the burst to the arrival")
        words, tick, sid, origin, depth = pw, int(parent["tick"]), int(parent["sid"]), dict(parent["origin"]), depth + 1
    if origin.get("kind") != "probe":
        raise SearchError(f"seed {seed['fsid']}: the lineage ends in an origin of kind {origin.get('kind')!r}")
    root = F["starts"].get(sid)
    if root is None or root["digest"] != mcell.words_digest(words) or int(root["tick"]) != tick:
        raise SearchError(f"seed {seed['fsid']}: its probe root {sid} is not the frontier's recorded start")
    return {"depth": depth, "root_sid": sid, "root_tick": tick, "root_origin": origin}


def throughput_fit(rows: Sequence[Mapping[str, Any]], summary: Mapping[str, Any], config: Mapping[str, Any]) -> Dict[str, Any]:
    """Per-job wall = a + b * ticks (least squares over the frontier's finished bursts) and its main-loop efficiency."""
    ok = [r for r in rows if r.get("kind") == "burst" and r.get("outcome") not in BAD_OUTCOMES and r.get("wall_s") and r.get("ticks")]
    out: Dict[str, Any] = {"jobs": len(ok)}
    f = fm.fit([float(r["ticks"]) for r in ok], [float(r["wall_s"]) for r in ok]) if len(ok) >= 3 else None
    if f is None:
        return out
    a, b = f
    mean_wall = sum(float(r["wall_s"]) for r in ok) / len(ok)
    out.update({"wall_s_fixed": round(a, 3), "wall_s_per_tick": round(b, 6), "mean_wall_s": round(mean_wall, 3),
                "mean_burst_words": round(sum(int(r["words_played"]) for r in ok) / len(ok), 1)})
    n_workers = int(config.get("n_workers") or 0)
    wall = float((summary.get("phase_wall_s") or {}).get("search") or 0.0)
    jobs = int((summary.get("work") or {}).get("burst_jobs") or 0)
    if n_workers and wall > 0 and jobs:
        measured = 3600.0 * jobs / wall
        ideal = n_workers * 3600.0 / mean_wall
        out.update({"frontier_workers": n_workers, "frontier_jobs_per_h": round(measured, 1), "frontier_ideal_jobs_per_h": round(ideal, 1),
                    "efficiency": round(min(1.0, measured / ideal), 4)})
    return out


def projection(fit: Mapping[str, Any], seeds: Sequence[Mapping[str, Any]], params: Params, bound: int, n_workers: int, hours: float) -> Dict[str, Any]:
    """Expected dispatches and ticks per hour from the frontier's fit, for the seeds' mean prefix and for the midpoint between it and the E7
    bound (the archive's cells arrive later than the seeds), at three burst lengths; and the archive's memory per cell (an estimate)."""
    if "wall_s_fixed" not in fit or not seeds:
        return {"available": False}
    eff = float(fit.get("efficiency") or 0.85)
    seed_mean = sum(s["tick"] for s in seeds) / len(seeds)
    mid = (seed_mean + bound) / 2.0
    seg = ARM_BASE["segment_words"]
    rows = []
    for prefix_name, prefix in (("seed_mean", seed_mean), ("midpoint_to_bound", mid)):
        for burst in (seg, seg * max(1, params.max_segments // 2), seg * params.max_segments):
            tpj = prefix + burst
            wall_job = float(fit["wall_s_fixed"]) + float(fit["wall_s_per_tick"]) * tpj
            jobs_h = eff * n_workers * 3600.0 / wall_job
            rows.append({"prefix": prefix_name, "prefix_ticks": round(prefix), "burst_words": burst, "ticks_per_job": round(tpj), "wall_s_per_job": round(wall_job, 2),
                         "dispatches_per_h": round(jobs_h), "ticks_per_h": round(jobs_h * tpj), "dispatches_over_wall": round(jobs_h * hours)})
    bytes_per_cell = round(mid + CELL_OVERHEAD_BYTES)
    return {"available": True, "efficiency": eff, "workers": n_workers, "hours": hours, "seed_mean_prefix": round(seed_mean), "rows": rows,
            "seed_ticks": sum(s["tick"] for s in seeds),
            "memory": {"bytes_per_cell_estimate": bytes_per_cell, "mb_at_cells": {str(n): round(n * bytes_per_cell / 2 ** 20) for n in (20000, 50000, 100000, params.max_cells)},
                       "max_cells": params.max_cells, "note": "words plus Python overhead per cell; the run measures the main process and projects from its own samples"},
            "note": "a projection from the frontier search's per-job wall fit, not a measurement; continuation lengthens bursts, the archive's cells lengthen prefixes"}


def build_search_plan(lab_root: Path, frontier_dir: Path, params: Params, analyse: fv.Analyse = fv.real_analyse) -> Dict[str, Any]:
    """Zero native ticks: the reference, the frontier's outputs, the seed rule, every seed's provenance, the fit and the projection."""
    params.check()
    R, meta = read_reference(lab_root, analyse)
    F = read_frontier(frontier_dir)
    fp = F["plan"]
    arrival = {int(k): int(v) for k, v in R["arrival"].items()}
    if {str(k): int(v) for k, v in fp["arrival_by_level"].items()} != {str(k): v for k, v in arrival.items()}:
        raise SearchError("refused: the frontier's arrival ticks per level are not the reference's")
    if fp["route"]["digest"] != R["meta"]["native_action_digest"] or int(fp["route"]["words"]) != len(R["words"]):
        raise SearchError("refused: the frontier's route is not the import's reference clear")
    if fp.get("archive_id") != meta["archive_id"]:
        raise SearchError("refused: the frontier's archive id is not the import's")
    ref_t = int(R["expected"]["completion_input_tick"])
    bound = s6.record_bound_max_L(ref_t, MARGIN)
    S = seed_rule(F, arrival, bound, params)
    prov = [seed_provenance(s, F, meta["archive_id"]) for s in S["seeds"]]
    for s, pv in zip(S["seeds"], prov):
        s["lineage"] = pv
    per: Dict[str, Dict[str, Any]] = {}
    for s in S["seeds"]:
        d = per.setdefault(str(s["level"]), {"seeds": 0, "best_lead": None, "best_tick": None, "worst_lead": None, "reference": arrival[s["level"]], "top": []})
        d["seeds"] += 1
        if d["best_lead"] is None or s["lead"] > d["best_lead"]:
            d["best_lead"], d["best_tick"] = s["lead"], s["tick"]
        d["worst_lead"] = s["lead"] if d["worst_lead"] is None else min(d["worst_lead"], s["lead"])
        if len(d["top"]) < 8:
            d["top"].append({"fsid": s["fsid"], "tick": s["tick"], "lead": s["lead"], "origin_kind": s["origin"].get("kind"), "lineage_depth": s["lineage"]["depth"]})
    fit = throughput_fit(F["rows"], F["summary"], F["config"])
    plan = {"mode": "lab", "contract": SEARCH_CONTRACT, "utc": g.utc(), "archive_id": meta["archive_id"],
            "rule": "crossing_seed_v1: the frontier search's states (its frontier files) at the deepest level its own bursts reached ahead of the reference "
                    "(a dispatch row's level arrival with pace > 0) and at the level below it; one state per cell key (earliest arrival); ordered by "
                    f"{'(level desc, lead desc)' if params.seed_order == 'level' else 'lead desc'}; the top S; each prefix re-derived from the frontier's rows "
                    "back to its probe start at zero ticks and replayed natively at the run's open",
            "frontier": {"dir": str(F["dir"]), "contract": fp["contract"], "utc": fp.get("utc"), "start_set_digest": fp.get("start_set_digest"),
                         "lab_code_digest": F["config"].get("lab_code_digest"), "search_file_sha256": F["config"].get("search_file_sha256"),
                         "params": fp.get("params"), "arm": F["config"].get("arm_params"), "frontier_files": F["frontier_files"], "states_with_words": len(F["states"]),
                         "rows": len(F["rows"]), "status": (F["summary"] or {}).get("status")},
            "route": {k: fp["route"][k] for k in ("words", "digest", "completion_input_tick", "completion_time_passed", "final_chain")},
            "arrival_by_level": {str(k): v for k, v in arrival.items()}, "e7": {"reference_completion_input_tick": ref_t, "margin": MARGIN, "bound_max_L": bound,
                                                                                 "origin": "sd1 / sd2 registered E7 (m8_sd1_select.record_bound_max_L)"},
            "params": params.as_dict(), "arm": {ARM_NAME: params.arm()}, "arm_base": ARM_BASE, "flags_explore": fv.FLAGS_EXPLORE, "flags_verify": fv.FLAGS_VERIFY,
            "seed_rule": {k: S[k] for k in ("deepest_burst_level", "burst_ahead_arrivals_per_level", "levels", "pool_states", "pool_keys", "per_level_pool")},
            "seeds": len(S["seeds"]), "seed_ticks": sum(s["tick"] for s in S["seeds"]), "seed_set_digest": S["seed_set_digest"],
            "lineage_depth": {"max": max((p["depth"] for p in prov), default=0), "mean": round(sum(p["depth"] for p in prov) / max(1, len(prov)), 2)},
            "per_level": dict(sorted(per.items(), key=lambda kv: -int(kv[0]))), "throughput_fit": fit}
    return {"plan": plan, "seeds": S["seeds"], "R": R, "meta": meta, "F": F, "bound": bound}


def seed_row(s: Mapping[str, Any]) -> Dict[str, Any]:
    """One seeds.jsonl row of the plan: identity, lengths, digests, lineage; no raw words."""
    return {k: s[k] for k in ("fsid", "level", "tick", "lead", "slack", "digest", "key", "end_digest", "chain", "origin", "first_file", "lineage")}


# -- per-dispatch readings ----------------------------------------------------------------------------------------------------------------


def level_arrivals(level: int, breaks: Sequence[Sequence[int]]) -> List[Tuple[int, int]]:
    by_tick: Dict[int, int] = {}
    for t, _i in breaks:
        by_tick[int(t)] = by_tick.get(int(t), 0) + 1
    out: List[Tuple[int, int]] = []
    lv = int(level)
    for t in sorted(by_tick):
        lv += by_tick[t]
        out.append((lv, t))
    return out


def dispatch_row(info: Mapping[str, Any], c: Cell, res: Mapping[str, Any], arrival: Mapping[int, int]) -> Dict[str, Any]:
    L, n = int(res["L"]), len(res["words"])
    breaks = sorted((int(t), int(i)) for t, i in res["breaks_all"])
    pre = [b for b in breaks if b[0] <= L]
    post = [b for b in breaks if b[0] > L]
    levels = {str(lv): t for lv, t in level_arrivals(len(pre), post)}
    pace = {lv: int(arrival[int(lv)]) - t for lv, t in levels.items() if int(lv) in arrival}
    end = END_NAMES.get(str(res["end_reason"]), str(res["end_reason"]))
    rj = res.get("result_json") or {}
    return {"kind": "burst", "n": info["n"], "cid": c.cid, "k": info["k"], "level": info["level"], "start_tick": L, "lead": info["lead"], "draw_id": info["draw_id"],
            "draw": info.get("draw"), "cell_fresh": info.get("fresh"), "cell_seen": info.get("seen"), "cell_breaks": info.get("breaks"), "outcome": end,
            "words_played": n, "ticks": int(res["ticks"]), "deepest": len(pre) + len(post), "advanced": len(post) > 0, "breaks_after_start": [list(b) for b in post],
            "levels": levels, "pace": pace, "prefix_breaks": len(pre), "prefix_level_ok": len(pre) == int(info["level"]), "reaches": len(res["reaches"]),
            "segments": res.get("segments"), "decisions": res.get("decisions"), "tick0_equal": (res.get("tick0") or {}).get("equal"),
            "prefix_host_frame_equal": (res.get("prefix") or {}).get("host_frame_equal"), "mode": res.get("mode"), "worker": res.get("worker"),
            "wall_s": res.get("wall_s"), "step_s": res.get("step_s"), "ask_s": res.get("ask_s"), "words_hex": bytes(res["words"]).hex(),
            "final_chain": res.get("final_chain") if end == "clear" else None,
            "claimed": {"completion_input_tick": rj.get("completion_input_tick"), "completion_time_passed": rj.get("completion_time_passed")} if end == "clear" else None}


def clear_row(cand: Mapping[str, Any], out: Mapping[str, Any], ref_t: int) -> Dict[str, Any]:
    """One verifications.jsonl row from rl/frs_verify.verify_twice's result. Only a VERIFIED row is ever a clear."""
    r1, r2 = out.get("r1") or {}, out.get("r2") or {}
    cit = out.get("completion_input_tick")
    return {"mode": "lab", "kind": "clear", "n": cand["n"], "cid": cand["cid"], "k": cand["k"], "level": cand["level"], "start_tick": cand["start_tick"],
            "lead": cand["lead"], "words": len(cand["words"]), "words_hex": bytes(cand["words"]).hex(), "words_digest": cand["claim"]["words_digest"],
            "verdict": out["verdict"], "reasons": list(out.get("reasons") or []), "completion_input_tick": cit, "completion_time_passed": out.get("completion_time_passed"),
            "chain_r1": r1.get("final_chain"), "chain_r2": r2.get("final_chain"), "clocks_r1": [r1.get("completion_input_tick"), r1.get("completion_time_passed")],
            "clocks_r2": [r2.get("completion_input_tick"), r2.get("completion_time_passed")], "breaks_r1": r1.get("breaks"), "breaks_r2": r2.get("breaks"),
            "claim": dict(cand["claim"]), "errors": out.get("errors"), "wall_s": out.get("wall_s"),
            "faster_than_reference": bool(out["verdict"] == fv.VERIFIED and cit is not None and int(cit) < int(ref_t)),
            "gain_vs_reference": (int(ref_t) - int(cit)) if (out["verdict"] == fv.VERIFIED and cit is not None) else None,
            "reference_completion_input_tick": int(ref_t)}


def seed_check(trace: Optional[Mapping[str, Any]], words: bytes, seed: Mapping[str, Any], analyse: fv.Analyse, clf: mcell.Classifier) -> Dict[str, Any]:
    """A seed's fresh-process replay from tick 0 against the frontier's record: every tick under the tick contract, the episode live at its last
    tick, the chain digest, the record digest and the cell key at that tick equal to the record, the breaks equal to the level; the end record
    (the observation tuple at the last tick) is returned for the worker's prefix check."""
    ev = fv.evaluate(trace, words, analyse)
    out: Dict[str, Any] = {"ok": False, "ticks": ev.get("ticks"), "ticks_ok": ev.get("ticks_ok"), "outcome": ev.get("outcome"), "startup_s": ev.get("startup_s"),
                           "stepping_s": ev.get("stepping_s")}
    if trace is None or ev["outcome"] == "error":
        out["why"] = "the replay did not run"
        return out
    steps = trace.get("steps") or []
    if len(steps) != len(words) or not ev["ticks_ok"] or not ev["action_digest_ok"]:
        out["why"] = f"the prefix did not replay under the tick contract ({len(steps)} of {len(words)} ticks, ticks_ok {ev['ticks_ok']}, digest_ok {ev['action_digest_ok']})"
        return out
    last = steps[-1]
    o, sp = last["observation"], last["spatial"]
    if int(last["state"]) != mcell.STATE_WAITING or mcell.is_native_failure(o, last["state"]):
        out["why"] = f"the episode is not live at the seed's tick (state {last.get('state_name')}, game_status {o.get('game_status')})"
        return out
    chain = fv.chain_of(trace["initial"], steps)
    rd = mcell.record_digest(mcell.record_of(last))
    key = mcell.cell_key(o, sp, clf)
    out.update({"chain_equal": chain.hex() == seed["chain"], "end_digest_equal": rd.hex() == seed["end_digest"], "key_equal": key is not None and fa.norm_key(key) == fa.norm_key(seed["key"]),
                "breaks": ev.get("targets"), "level_equal": int(ev.get("targets") or -1) == int(seed["level"])})
    if not (out["chain_equal"] and out["end_digest_equal"] and out["key_equal"] and out["level_equal"]):
        out["why"] = "the replayed state differs from the frontier's record (" + ", ".join(k for k in ("chain_equal", "end_digest_equal", "key_equal", "level_equal") if not out[k]) + ")"
        return out
    out.update({"ok": True, "end": mcell.obs_tuple(o), "key": list(fa.norm_key(key))})
    return out


# -- the engine ---------------------------------------------------------------------------------------------------------------------------------


@dataclass
class SearchConfig:
    lab_root: Path
    out: Path
    run_dir: Path
    frontier_dir: Path
    n_workers: int = 5
    max_ticks: int = 80_000_000
    max_wall_s: float = 420 * 60.0
    expect_code: Optional[str] = None            # the frontier's lab code digest: the run refuses to start on other lab code
    job_timeout_s: float = mrun.JOB_TIMEOUT_S
    stop_grace_s: float = 60.0
    verify_parallel: int = 5
    seed_parallel: int = 5
    mismatch_limit: int = 3
    seed_failure_limit: int = 3
    lifecycle_limit: int = mrule.MAX_LIFECYCLE_FAILURES
    progress_every_s: float = 60.0
    write_reserve_s: float = 60.0
    verify_s_per_clear: float = 30.0
    verify_floor_s: float = 180.0


class Search:
    def __init__(self, cfg: SearchConfig, env: fr.LabEnv, P: Mapping[str, Any], params: Params):
        self.cfg, self.env, self.p = cfg, env, params
        self.plan: Dict[str, Any] = dict(P["plan"])
        self.seeds: List[Dict[str, Any]] = list(P["seeds"])
        self.R = P["R"]
        self.meta = P["meta"]
        self.bound = int(P["bound"])
        self.arm = params.arm()
        self.fs = g.LabFS(cfg.lab_root)
        self.dir = Path(cfg.run_dir)
        self.pin = dict(self.meta["pin_tick0"])
        self.arrival: Dict[int, int] = {int(k): int(v) for k, v in self.R["arrival"].items()}
        self.ref_t = int(self.R["expected"]["completion_input_tick"])
        self.archive = Archive(self.meta["archive_id"], self.arrival, self.bound, params)
        self.rng = random.Random(int(params.rng_seed))
        self.t0 = env.now()
        self.utc_start = g.utc()
        self.phase = "open"
        self.phase_wall: Dict[str, float] = {}
        self.status = "COMPLETED"
        self.stop_reason: Optional[str] = None
        self.stopping = False
        self.notes: List[str] = []
        self.pool: Optional[fr.FrsPool] = None
        self.sampler: Optional[fm.Sampler] = None
        self.inflight: Dict[int, Dict[str, Any]] = {}
        self.seed_rows: List[Dict[str, Any]] = []
        self.seed_stats = {"seeds": 0, "ok": 0, "dropped": 0, "reasons": {}, "ticks": 0, "wall_s": 0.0}
        self.c = {"dispatches": 0, "jobs": 0, "ticks": 0, "prefix_ticks": 0, "burst_ticks": 0, "seed_ticks": 0, "reference_ticks": 0, "verify_ticks": 0,
                  "mismatches": 0, "lifecycle_failures": 0, "aborted": 0, "tick0_unequal": 0, "boundaries": 0, "continued": 0, "advanced": 0, "falls": 0,
                  "reaches": 0, "clears_claimed": 0}
        self.per_level: Dict[str, Dict[str, int]] = {}
        self.effects = {"bonus": {"with_breaks": [0, 0, 0], "without": [0, 0, 0]}, "seen": {f"{a}-{b if b < 10 ** 9 else 'up'}": [0, 0, 0] for a, b in SEEN_BUCKETS},
                        "fresh": {"0": [0, 0, 0], "1-3": [0, 0, 0], "4-15": [0, 0, 0], "16-up": [0, 0, 0]}, "segments": {}}
        self.reserved = 0
        self.vqueue: List[Dict[str, Any]] = []
        self.vrows: List[Dict[str, Any]] = []
        self.vthread: Optional[threading.Thread] = None
        self.vbox: Dict[str, Any] = {}
        self.lent: Optional[int] = None
        self.unverified: List[Dict[str, Any]] = []
        self.reference: Dict[str, Any] = {}
        self.code: Dict[str, str] = {}
        self.code_dig = ""
        self.integrity: Dict[str, Any] = {}
        self.search_wall = 0.0
        self.t_search = self.t0
        self.events: List[str] = []
        self._last_progress = self.t0
        self._lock = threading.Lock()

    # -- bookkeeping --------------------------------------------------------------------------------------------------------------------------

    def log(self, s: str) -> None:
        self.env.log(f"crossing: {s}")
        try:
            self.fs.append_jsonl(self.dir / "run_log.jsonl", {"t_s": round(self.env.now() - self.t0, 1), "phase": self.phase, "n": self.c["dispatches"], "msg": s[:2000]})
        except (OSError, g.LabRootError):
            pass

    def event(self, s: str) -> None:
        self.events.append(f"{g.utc()} n {self.c['dispatches']:,}: {s}"[:300])
        self.events = self.events[-40:]
        self.log(s)

    def mark(self, status: str, reason: str, *, abort: bool = False) -> None:
        if STATUS_RANK[status] > STATUS_RANK[self.status]:
            self.status = status
        self.notes.append(f"{status}: {reason}"[:600])
        if not self.stopping:
            self.stopping = True
            self.stop_reason = reason[:600]
        if abort and self.pool is not None:
            self.pool.abort.set()
        if status not in ("COMPLETED",):
            self.log(f"{status}: {reason}")

    def elapsed(self) -> float:
        return self.env.now() - self.t0

    def used_ticks(self) -> int:
        return self.c["ticks"] + self.c["seed_ticks"] + self.c["reference_ticks"] + self.c["verify_ticks"]

    def verify_ticks_pending(self) -> int:
        n = 2 * sum(len(c["words"]) for c in self.vqueue)
        if self.vthread is not None and self.vbox.get("cand") is not None:
            n += 2 * len(self.vbox["cand"]["words"])
        return n

    def dispatch_deadline(self) -> float:
        cfg = self.cfg
        pending = len(self.vqueue) + (1 if self.vthread is not None else 0)
        reserve = cfg.stop_grace_s + cfg.write_reserve_s + max(cfg.verify_floor_s, cfg.verify_s_per_clear * (-(-pending // cfg.verify_parallel)))
        return self.t0 + cfg.max_wall_s - reserve

    def verified_clears(self) -> List[Dict[str, Any]]:
        return [v for v in self.vrows if v["verdict"] == fv.VERIFIED]

    # -- run --------------------------------------------------------------------------------------------------------------------------------------

    def run(self) -> int:
        try:
            self.open()
        except Refused as exc:
            self.fs.write_json(self.cfg.out / f"refused_{g.utc_compact()}.json", {"mode": "lab", "utc": g.utc(), "reason": str(exc)})
            print(f"REFUSED: {exc}", flush=True)
            if self.sampler is not None:
                self.sampler.stop()
            return EXIT["REFUSED"]
        except Exception as exc:  # noqa: BLE001 - an open failure after launching is a closed, reported stop
            self.mark("SEARCH_INCOMPLETE", f"open failed: {type(exc).__name__}: {exc}", abort=True)
            self.log(traceback.format_exc()[-2000:])
        else:
            if not self.stopping:
                try:
                    self.search_phase()
                except Exception as exc:  # noqa: BLE001
                    self.mark("SEARCH_INCOMPLETE", f"search error: {type(exc).__name__}: {exc}", abort=True)
                    self.log(traceback.format_exc()[-2000:])
        try:
            self.close()
        except Exception as exc:  # noqa: BLE001
            self.mark("SEARCH_INCOMPLETE", f"close error: {type(exc).__name__}: {exc}")
            self.log(traceback.format_exc()[-2000:])
            try:
                self.write_summary()
            except Exception:  # noqa: BLE001
                self.log(traceback.format_exc()[-2000:])
        return EXIT[self.status]

    # -- open: checks, the reference, the seeds (fresh-process replays), the workers ---------------------------------------------------------

    def open(self) -> None:
        cfg, env = self.cfg, self.env
        if self.dir.exists():
            raise Refused(f"{self.dir} exists (a run folder is never overwritten)")
        ready = env.readiness()
        if not ready["ok"]:
            raise Refused(f"readiness: {ready['problems']}")
        pids = env.battleship_pids()
        if pids is None or pids:
            raise Refused(f"BattleShip processes already running (or unreadable): {pids}")
        bad = env.import_problems()
        if bad:
            raise Refused(f"import pins: {bad[:6]}")
        if not self.seeds:
            raise Refused("no seed: the seed rule selected no frontier state")
        self.code = env.code_manifest()
        self.code_dig = fr.code_digest(self.code)
        if cfg.expect_code and self.code_dig != cfg.expect_code:
            raise Refused(f"lab code digest {self.code_dig[:16]} differs from the frontier's {cfg.expect_code[:16]}")
        self.fs.mkdir(self.dir)
        self.fs.write_json(self.dir / "config.json", self.config_record(ready))
        self.sampler = fm.Sampler(lambda r: self.fs.append_jsonl(self.dir / "memory.jsonl", r), interval=env.sample_s, row_every=env.row_every_s,
                                  caps=env.caps or fm.CAPS_MB, soft=env.soft, snapshot=env.snapshot, now=env.now,
                                  extra=lambda: {"cells": len(self.archive.cells), "phase": self.phase, "dispatches": self.c["dispatches"], "jobs": self.c["jobs"],
                                                 "words_mb": round(self.archive.words_bytes / 2 ** 20, 1)}).start()
        self.phase = "reference"
        words = self.R["words"]
        tr, errors = fv.replay_with_retry(env.replay, words, "reference", 0)
        row = fv.evaluate(tr, words, env.analyse)
        fv.save_trace(self.dir / "traces" / "reference.json.gz", tr)
        chk = fv.reference_check(row, self.R)
        self.c["reference_ticks"] += int(row.get("ticks") or 0)
        self.reference = {"ok": bool(chk["ok"]), "differs": chk["differs"], "errors": errors, "completion_input_tick": row.get("completion_input_tick"),
                          "completion_time_passed": row.get("completion_time_passed"), "final_chain": row.get("final_chain"), "ticks": row.get("ticks"),
                          "startup_s": row.get("startup_s"), "stepping_s": row.get("stepping_s")}
        self.fs.write_json(self.dir / "reference.json", self.reference)
        if not chk["ok"]:
            if row.get("outcome") == "error":
                self.mark("SEARCH_INCOMPLETE", f"the reference clear could not be replayed: {errors[:2]}")
            else:
                self.mark("SEARCH_INVALID", f"the reference clear did not replay exactly: {chk['differs']}")
            return
        self.log(f"reference clear replayed exactly: {row['completion_input_tick']} / {row['completion_time_passed']} in {row.get('stepping_s')} s; E7 bound {self.bound}")
        self.phase = "seed"
        self.seed_phase()
        if self.stopping:
            return
        if not self.archive.levels_present():
            self.mark("SEARCH_INCOMPLETE", "no seed reproduced its frontier record")
            return
        self.pool = fr.FrsPool(env.worker_spec, env.now)
        self.pool.start(cfg.n_workers)
        self.phase_wall["open"] = round(env.now() - self.t0, 1)
        self.log(f"open done in {self.phase_wall['open']:.0f} s; {cfg.n_workers} workers ready; {self.seed_stats['ok']} of {self.seed_stats['seeds']} seeds in the archive; "
                 f"params {self.p.as_dict()}; arm {ARM_NAME} {self.arm}")
        self.write_progress()

    def config_record(self, ready: Mapping[str, Any]) -> Dict[str, Any]:
        c = self.cfg
        return {"mode": "lab", "contract": SEARCH_CONTRACT, "utc": g.utc(), "search_file_sha256": g.sha256_file(Path(__file__).resolve()),
                "lab_code_digest": self.code_dig, "lab_code_files": len(self.code), "expect_code": c.expect_code, "arm": ARM_NAME, "arm_params": self.arm,
                "arm_base": ARM_BASE, "params": self.p.as_dict(), "n_workers": c.n_workers, "max_ticks": c.max_ticks, "max_wall_s": c.max_wall_s,
                "job_timeout_s": c.job_timeout_s, "mismatch_limit": c.mismatch_limit, "seed_failure_limit": c.seed_failure_limit, "lifecycle_limit": c.lifecycle_limit,
                "verify_parallel_close": c.verify_parallel, "seed_parallel": c.seed_parallel, "max_battleship_processes": fm.MAX_BATTLESHIP,
                "memory_caps_mb": dict(self.env.caps or fm.CAPS_MB), "memory_soft_budget_mb": dict(self.env.soft or fm.soft_budget(self.env.caps or fm.CAPS_MB)),
                "readiness": ready, "flags_explore": fv.FLAGS_EXPLORE, "flags_verify": fv.FLAGS_VERIFY, "backend": self.env.backend,
                "import": str(Path(c.lab_root) / "import"), "frontier": self.plan["frontier"], "seed_set_digest": self.plan["seed_set_digest"],
                "seeds": self.plan["seeds"], "seed_ticks": self.plan["seed_ticks"], "reference": self.plan["route"], "e7": self.plan["e7"],
                "origins": {"arm": "the lab's CONT arm (rl/frs_run.ARMS) with max_segments as an argument", "seeds": "crossing_seed_v1 (this file) on the frontier's files",
                            "draw_id": "<archive id>|crossing|<prefix words digest>, iteration k = the representative's dispatch count (0.. per representative)",
                            "selection": "level draw decay^(deepest - level), then (1+fresh)^-nov (1+seen)^-seen (1+breaks)^bonus slack^pace (this file)",
                            "e7": "the registered rule, reference and margin (never lowered)", "caps": f"owner, 2026-10-15: at most {c.max_wall_s / 60.0:g} minutes, "
                            f"{c.max_ticks:,} ticks, {self.p.max_cells:,} cells", "readiness": "registered thresholds, never lowered", "rng": "Python experiment seed (the draws)"}}

    def seed_phase(self) -> None:
        """Every seed replayed from tick 0 in a fresh process (up to seed_parallel at once, before any worker is started) and checked against
        the frontier's record; the ones that reproduce enter the archive with the end record the replay gives."""
        cfg, env = self.cfg, self.env
        t = env.now()
        clf = mcell.Classifier()
        lock = threading.Lock()
        queue = list(enumerate(self.seeds))
        results: List[Tuple[int, Dict[str, Any], Dict[str, Any]]] = []

        def worker(slot: int) -> None:
            while True:
                with lock:
                    if not queue or self.stopping:
                        return
                    i, s = queue.pop(0)
                t1 = env.now()
                try:
                    tr, errors = fv.replay_with_retry(env.replay, s["words"], f"seed_{s['fsid']}", slot)
                    out = seed_check(tr, s["words"], s, env.analyse, clf)
                    out["errors"] = errors
                except Exception as exc:  # noqa: BLE001 - a crashed seed replay drops the seed, never the run
                    out = {"ok": False, "why": f"{type(exc).__name__}: {exc}"[:300], "ticks": 0}
                out["wall_s"] = round(env.now() - t1, 2)
                with lock:
                    results.append((i, s, out))

        n = max(1, min(cfg.seed_parallel, len(queue)))
        ths = [threading.Thread(target=worker, args=(i,), daemon=True, name=f"crossing-seed-{i}") for i in range(n)]
        for th in ths:
            th.start()
        for th in ths:
            th.join()
        self.seed_stats["seeds"] = len(self.seeds)
        for i, s, out in sorted(results, key=lambda x: x[0]):
            self.c["seed_ticks"] += int(out.get("ticks") or 0)
            row = {"kind": "seed", "fsid": s["fsid"], "level": s["level"], "tick": s["tick"], "lead": s["lead"], "digest": s["digest"], "origin": s["origin"],
                   "lineage_depth": s["lineage"]["depth"], "ok": bool(out.get("ok")), "why": out.get("why"), "ticks": out.get("ticks"), "ticks_ok": out.get("ticks_ok"),
                   "chain_equal": out.get("chain_equal"), "end_digest_equal": out.get("end_digest_equal"), "key_equal": out.get("key_equal"), "level_equal": out.get("level_equal"),
                   "errors": out.get("errors"), "wall_s": out.get("wall_s"), "startup_s": out.get("startup_s"), "stepping_s": out.get("stepping_s"), "utc": g.utc()}
            if out.get("ok"):
                verdict, c = self.archive.keep(s["key"], s["level"], s["tick"], s["words"], out["end"], bytes.fromhex(s["end_digest"]), bytes.fromhex(s["chain"]),
                                               {"kind": "seed", "fsid": s["fsid"], "frontier_origin": s["origin"], "lineage_depth": s["lineage"]["depth"]}, 0)
                row["verdict"], row["cid"] = verdict, c.cid if c else None
                if c is not None and verdict in (NEW, REPLACED):
                    self.emit_cell(verdict, c, None, previous=c.previous if verdict == REPLACED else None)
                self.seed_stats["ok"] += 1
            else:
                self.seed_stats["dropped"] += 1
                why = str(out.get("why"))[:60]
                self.seed_stats["reasons"][why] = self.seed_stats["reasons"].get(why, 0) + 1
                self.log(f"seed {s['fsid']} (level {s['level']}, tick {s['tick']}) dropped: {out.get('why')}")
                if self.seed_stats["dropped"] > cfg.seed_failure_limit:
                    self.mark("SEARCH_INVALID", f"{self.seed_stats['dropped']} seeds did not reproduce the frontier's record > {cfg.seed_failure_limit}")
            self.seed_rows.append(row)
            self.fs.append_jsonl(self.dir / "seeds.jsonl", row)
        self.seed_stats["ticks"] = self.c["seed_ticks"]
        self.seed_stats["wall_s"] = round(env.now() - t, 1)
        self.seed_stats["per_level"] = self.archive.per_level()
        self.phase_wall["seed"] = self.seed_stats["wall_s"]
        self.log(f"seed done in {self.seed_stats['wall_s']:.0f} s: {self.seed_stats['ok']} of {self.seed_stats['seeds']} seeds reproduced ({self.seed_stats['dropped']} dropped), "
                 f"{self.c['seed_ticks']:,} ticks; per level {json.dumps({lv: d['cells'] for lv, d in self.archive.per_level().items()})}")

    # -- the search: every idle worker draws a start ----------------------------------------------------------------------------------------------

    def search_phase(self) -> None:
        self.t_search = self.env.now()
        self.phase = "search"
        pool = self.pool
        assert pool is not None
        while not self.stopping:
            for w, kind, payload in pool.poll2(0.2, self.on_boundary):
                self.handle(w, kind, payload)
            self.checks()
            self.verification_step()
            if self.stopping:
                break
            for w in pool.idle():
                if w == self.lent or self.stopping:
                    continue
                job = self.next_job(w)
                if job is None:
                    break
                pool.send(w, job)
            self.progress()
        self.search_wall = self.env.now() - self.t_search
        self.drain()

    def checks(self) -> None:
        s, pool, cfg = self.sampler, self.pool, self.cfg
        assert s is not None and pool is not None
        if self.stopping:
            return
        if s.hard_breach:
            self.mark("SEARCH_INCOMPLETE", s.hard_breach, abort=True)
        elif s.proc_breach:
            self.mark("SEARCH_INCOMPLETE", s.proc_breach, abort=True)
        elif g.LabGuard.violations:
            self.mark("SEARCH_INVALID", f"guard violation in the main process: {g.LabGuard.violations[:2]}", abort=True)
        elif s.soft_breach:
            self.mark("MEMORY_BUDGET", s.soft_breach)
        elif self.env.now() >= self.dispatch_deadline():
            self.mark("WALL_CAP", f"the wall cap {cfg.max_wall_s / 60.0:g} min is reached (minus the close reserve)")
        elif len(self.archive.cells) >= self.p.max_cells:
            self.mark("CELLS_CAP", f"the archive holds {len(self.archive.cells):,} cells >= the cells cap {self.p.max_cells:,}")
        elif self.p.max_dispatches and self.c["dispatches"] >= self.p.max_dispatches:
            self.mark("DISPATCH_CAP", f"{self.c['dispatches']:,} dispatches >= the dispatch cap {self.p.max_dispatches:,}")
        elif pool.oldest_age() > cfg.job_timeout_s:
            self.mark("SEARCH_INCOMPLETE", f"a job has been in flight for more than {cfg.job_timeout_s:.0f} s", abort=True)
        elif not [i for i, pr in enumerate(pool.procs) if pr.is_alive() and i not in pool.retired]:
            self.mark("SEARCH_INCOMPLETE", "no live worker is left", abort=True)

    def next_job(self, w: int) -> Optional[Dict[str, Any]]:
        cfg = self.cfg
        pick = self.archive.select(self.rng)
        if pick is None:
            self.mark("ARCHIVE_EMPTY", "no eligible cell is left to dispatch from")
            return None
        c, draw = pick
        assert c.words is not None
        max_words = self.arm["segment_words"] * self.arm["max_segments"]
        want = c.tick + min(max_words, mcell.HORIZON - c.tick)
        if self.used_ticks() + self.reserved + want + self.verify_ticks_pending() > cfg.max_ticks:
            self.mark("TICK_CAP", f"the tick cap {cfg.max_ticks:,} would be exceeded by the next dispatch")
            return None
        k = c.next_k
        c.next_k += 1
        draw_id = c.draw_id(self.archive.archive_id)
        job = {"kind": fw.JOB_KIND, "iteration": k, "cell": c.cid, "rep": (c.cid, c.tick), "words": bytes(c.words), "end": tuple(c.end), "end_digest": bytes(c.end_digest),
               "chain": bytes(c.chain), "terminal": False, "pin": self.pin, "archive_id": draw_id, "allowance": int(want), **self.arm}
        self.c["dispatches"] += 1
        self.inflight[w] = {"n": self.c["dispatches"], "cid": c.cid, "k": k, "level": c.level, "tick": c.tick, "lead": c.lead, "draw_id": draw_id, "draw": draw,
                            "fresh": c.fresh, "seen": c.seen, "breaks": c.breaks, "digest": c.digest, "words": bytes(c.words), "reserved": int(want), "cont": []}
        self.reserved += int(want)
        return job

    def on_boundary(self, w: int, payload: Dict[str, Any]) -> None:
        info = self.inflight.get(w)
        aborting = self.pool is not None and self.pool.abort.is_set()
        if aborting or self.stopping or info is None or info["k"] != int(payload["iteration"]):
            d: Dict[str, Any] = {"go": False, "stopping": True}
        else:
            d = self.archive.continuation_decision(payload["reaches"])
        go = bool(d["go"])
        self.c["boundaries"] += 1
        self.c["continued"] += int(go)
        if info is not None:
            info["cont"].append([int(payload["segment"]), len(payload["reaches"]), d.get("new"), d.get("shorter"), d.get("max_gain"), int(go)])
        try:
            self.pool.conns[w].send(("continue", {"iteration": payload["iteration"], "segment": payload["segment"], "go": go}))
        except (OSError, BrokenPipeError):
            pass

    def emit(self, row: Dict[str, Any]) -> None:
        with self._lock:
            self.fs.append_jsonl(self.dir / "dispatches.jsonl", row)

    def emit_cell(self, verdict: str, c: Cell, info: Optional[Mapping[str, Any]], previous: Optional[Mapping[str, Any]] = None) -> None:
        row = {"ev": verdict, "cid": c.cid, "key": list(c.key), "level": c.level, "tick": c.tick, "lead": c.lead, "slack": self.archive.slack_of(c.tick), "digest": c.digest,
               "end_digest": c.end_digest.hex(), "chain": c.chain.hex(), "origin": c.origin, "n": self.c["dispatches"], "seen": c.seen, "replaced": c.replaced,
               "first_at_level": c.first_level_reach if verdict == NEW else False, "utc": g.utc(), "words_hex": c.words.hex() if c.words is not None else None}
        if previous:
            row["previous"] = dict(previous)
        with self._lock:
            self.fs.append_jsonl(self.dir / "cells.jsonl", row)

    def handle(self, w: int, kind: str, payload: Dict[str, Any]) -> None:
        info = self.inflight.pop(w, None)
        if info is not None:
            self.reserved -= info["reserved"]
        if kind in ("died", "fatal"):
            self.mark("SEARCH_INCOMPLETE", f"worker {w} {kind}: {json.dumps(payload, default=str)[:300]}", abort=True)
            return
        if payload.get("guard_violations") or payload.get("provenance_violations"):
            self.mark("SEARCH_INVALID", f"worker {w} guard / provenance violation: "
                                        f"{(payload.get('guard_violations') or payload.get('provenance_violations'))[:2]}", abort=True)
        if info is None:
            self.mark("SEARCH_INVALID", f"worker {w} returned a job that was not in flight")
            return
        c = self.archive.cells[info["cid"]]
        if payload.get("ok"):
            self.commit(info, c, payload)
            return
        kd = payload.get("kind")
        base = {"kind": "burst", "n": info["n"], "cid": c.cid, "k": info["k"], "level": info["level"], "start_tick": info["tick"], "lead": info["lead"], "draw_id": info["draw_id"],
                "advanced": False, "deepest": info["level"], "ticks": 0, "words_played": 0}
        if kd == "mismatch":
            self.emit(dict(base, outcome="mismatch", mismatch=payload.get("mismatch"), detail=json.dumps(payload.get("detail"), default=str)[:800]))
            if payload.get("mismatch") in fa.QUARANTINE_KINDS:
                self.c["mismatches"] += 1
                if c.digest == info["digest"]:                     # the representative in flight is still the cell's: quarantine it
                    self.archive.quarantine(c, f"n {info['n']}: prefix mismatch {payload.get('mismatch')}")
                self.event(f"cell {c.cid} (level {c.level}, tick {info['tick']}) quarantined: its prefix did not reproduce ({payload.get('mismatch')})")
                if self.c["mismatches"] > self.cfg.mismatch_limit:
                    self.mark("SEARCH_INVALID", f"{self.c['mismatches']} prefix mismatches > {self.cfg.mismatch_limit}", abort=True)
            else:
                self.mark("SEARCH_INVALID", f"cell {c.cid} k {info['k']}: mismatch {payload.get('mismatch')} {json.dumps(payload.get('detail'), default=str)[:400]}", abort=True)
        elif kd == "lifecycle":
            self.c["lifecycle_failures"] += 1
            self.emit(dict(base, outcome="lifecycle", detail=str(payload.get("message"))[:300]))
            self.log(f"lifecycle failure {payload.get('outcome')} on worker {w}: {str(payload.get('message'))[:200]}")
            if self.c["lifecycle_failures"] > self.cfg.lifecycle_limit:
                self.mark("SEARCH_INCOMPLETE", f"more than {self.cfg.lifecycle_limit} lifecycle failures", abort=True)
        elif kd == "aborted":
            self.c["aborted"] += 1
            self.emit(dict(base, outcome="aborted"))
        else:
            self.mark("SEARCH_INCOMPLETE", f"worker {w} error: {str(payload.get('error'))[:300]}", abort=True)
            self.log(str(payload.get("trace", ""))[-1500:])

    @staticmethod
    def _bucket(table: Mapping[str, List[int]], value: int, kind: str) -> Optional[List[int]]:
        if kind == "seen":
            for (a, b), key in zip(SEEN_BUCKETS, table):
                if a <= value <= b:
                    return table[key]
            return None
        for key, (a, b) in zip(table, ((0, 0), (1, 3), (4, 15), (16, 10 ** 9))):
            if a <= value <= b:
                return table[key]
        return None

    def commit(self, info: Mapping[str, Any], c: Cell, res: Mapping[str, Any]) -> None:
        row = dispatch_row(info, c, res, self.arrival)
        row["cont"] = list(info["cont"])
        n = len(res["words"])
        self.c["jobs"] += 1
        self.c["ticks"] += int(res["ticks"])
        self.c["burst_ticks"] += n
        self.c["prefix_ticks"] += int(res["ticks"]) - n
        self.c["reaches"] += len(res["reaches"])
        if not (res.get("tick0") or {}).get("equal", True):
            self.c["tick0_unequal"] += 1
        advanced = bool(row["advanced"])
        same_rep = c.digest == info["digest"]
        if same_rep:
            c.dispatched += 1
            c.fresh += 1
            if advanced:
                c.breaks += 1
            self.archive.touch(c)
        if advanced:
            self.c["advanced"] += 1
        if row["outcome"] == "fall":
            self.c["falls"] += 1
        seg = self.arm["segment_words"]
        bucket = str(-(-n // seg) * seg) if n else "0"
        self.effects["segments"][bucket] = self.effects["segments"].get(bucket, 0) + 1
        pl = self.per_level.setdefault(str(info["level"]), {"jobs": 0, "advanced": 0, "falls": 0, "clears": 0, "new_cells": 0, "replaced": 0, "later": 0, "deepest": int(info["level"]),
                                                             "continued": 0, "boundaries": 0})
        pl["jobs"] += 1
        pl["advanced"] += int(advanced)
        pl["falls"] += int(row["outcome"] == "fall")
        pl["clears"] += int(row["outcome"] == "clear")
        pl["deepest"] = max(pl["deepest"], int(row["deepest"]))
        for _s, _r, _n, _sh, _g, go in info["cont"]:
            pl["boundaries"] += 1
            pl["continued"] += int(go)
        kept = {NEW: 0, REPLACED: 0, LATER: 0, SELF: 0, BEYOND: 0, TERMINAL: 0, DEEP: 0, "cids": [], "deepest_new": None, "first_at_level": []}
        parent_words = bytes(info["words"])                     # the exact prefix the job replayed (the cell's representative may have changed in flight)
        if n > 0:
            if len(parent_words) != int(res["L"]):
                raise SearchError(f"dispatch {info['n']}: the job's words ({len(parent_words)}) are not its prefix length ({res['L']})")
            burst = bytes(res["words"])
            L = int(res["L"])
            for r in sorted(res["reaches"], key=lambda r: int(r[0])):
                j, key, obs, rd, chain, terminal = int(r[0]), fa.norm_key(r[1]), tuple(r[2]), bytes(r[3]), bytes(r[4]), bool(r[5])
                if not L < j <= L + len(burst):
                    raise SearchError(f"a reach at tick {j} is outside the burst ({L} + {len(burst)})")
                lv = mcell.level_of_mask(key[3])
                verdict, cell = self.archive.keep(key, lv, j, parent_words + burst[:j - L], obs, rd, chain,
                                                  {"kind": "burst", "parent": c.cid, "k": info["k"], "offset": j - L, "n": info["n"], "parent_digest": info["digest"]},
                                                  info["n"], self_key=c.key, terminal=terminal)
                kept[verdict] += 1
                if verdict in (NEW, REPLACED) and cell is not None:
                    kept["cids"].append(cell.cid)
                    if verdict == NEW:
                        c.new_children += 1
                        pl["new_cells"] += 1
                        kept["deepest_new"] = lv if kept["deepest_new"] is None else max(kept["deepest_new"], lv)
                        if cell.first_level_reach:
                            kept["first_at_level"].append(lv)
                            self.event(f"first arrival at level {lv}: tick {j} (reference {self.arrival.get(lv)}, lead {cell.lead}) from cell {c.cid} k {info['k']}, cell {cell.cid}")
                        self.emit_cell(NEW, cell, info)
                    else:
                        pl["replaced"] += 1
                        self.emit_cell(REPLACED, cell, info, previous=cell.previous)
                elif verdict == LATER:
                    pl["later"] += 1
        row["kept"] = {k: v for k, v in kept.items() if k != "cids"}
        row["kept"]["cids"] = kept["cids"][:64]
        eff_b = self.effects["bonus"]["with_breaks" if int(info["breaks"]) > 0 else "without"]
        eff_b[0] += 1
        eff_b[1] += int(advanced)
        eff_b[2] += kept[NEW]
        for kind_, val in (("seen", int(info["seen"])), ("fresh", int(info["fresh"]))):
            b = self._bucket(self.effects[kind_], val, kind_)
            if b is not None:
                b[0] += 1
                b[1] += int(advanced)
                b[2] += kept[NEW]
        if same_rep and self.archive.retire_check(c, f"n {info['n']}"):
            self.event(f"cell {c.cid} (level {c.level}, tick {c.tick}) retired: {c.retired}")
        self.emit(row)
        if row["outcome"] == "clear" and n > 0:
            words = bytes(parent_words) + bytes(res["words"])
            claim = {"words_digest": mcell.words_digest(words), "completion_input_tick": row["claimed"]["completion_input_tick"],
                     "completion_time_passed": row["claimed"]["completion_time_passed"], "chain": res.get("final_chain")}
            self.c["clears_claimed"] += 1
            self.vqueue.append({"kind": "clear", "n": info["n"], "cid": c.cid, "k": info["k"], "level": info["level"], "start_tick": int(res["L"]), "lead": info["lead"],
                                "words": words, "claim": claim})
            self.vqueue.sort(key=lambda cand: (cand["claim"]["completion_input_tick"] or 10 ** 9, cand["n"]))
            self.event(f"clear candidate: dispatch {info['n']} cell {c.cid} (level {info['level']}, tick {res['L']}) k {info['k']}, {len(words):,} words (claimed "
                       f"{claim['completion_input_tick']} / {claim['completion_time_passed']}, reference {self.ref_t}); queued for verification")
            self.write_progress()

    def progress(self, force: bool = False) -> None:
        now = self.env.now()
        if not force and now - self._last_progress < self.cfg.progress_every_s:
            return
        self._last_progress = now
        mb = (self.sampler.last or {}).get("main_private_mb") if self.sampler else None
        ex = max(1e-9, now - self.t_search)
        dp = self.archive.deepest() or {}
        self.log(f"t {self.elapsed():.0f}s dispatches {self.c['dispatches']:,} jobs {self.c['jobs']:,} ({3600.0 * self.c['jobs'] / ex:,.0f}/h) advanced {self.c['advanced']:,} "
                 f"ticks {self.used_ticks():,} ({3600.0 * self.c['ticks'] / ex / 1e6:.2f} M/h) cont {self.c['continued']}/{self.c['boundaries']} cells {len(self.archive.cells):,} "
                 f"(eligible {self.archive.stats()['eligible']:,}) deepest {dp.get('level')} at {dp.get('tick')} clears claimed {self.c['clears_claimed']} verified "
                 f"{len(self.verified_clears())} in flight {len(self.pool.busy) if self.pool else 0} main MB {mb}")
        try:
            self.fs.write_json(self.dir / "state.json", {"mode": "lab", "utc": g.utc(), "phase": self.phase, "elapsed_s": round(self.elapsed(), 1), "counters": self.c,
                                                          "status": self.status, "stop": self.stop_reason, "verification_queue": len(self.vqueue), "verifications": len(self.vrows),
                                                          "archive": self.archive.stats(), "deepest": dp})
            self.write_progress()
        except OSError:
            pass

    # -- verification: a clear is replayed twice from tick 0 as soon as a worker can be lent ----------------------------------------------------

    def verify_candidate(self, cand: Mapping[str, Any], slot: int) -> Dict[str, Any]:
        label = f"clear_n{cand['n']}_c{cand['cid']}_k{cand['k']}"
        try:
            out = fv.verify_twice(self.env.replay, self.env.analyse, cand["words"], cand["claim"], label, slot, trace_dir=self.dir / "traces")
        except Exception as exc:  # noqa: BLE001 - a crashed verification is an ERROR row, never a clear
            out = {"label": label, "verdict": fv.ERROR, "reasons": [f"{type(exc).__name__}: {exc}"[:300]], "r1": {}, "r2": {}, "errors": [], "words": len(cand["words"]), "wall_s": None}
        return out

    def on_verified(self, cand: Mapping[str, Any], out: Mapping[str, Any]) -> None:
        r1, r2 = out.get("r1") or {}, out.get("r2") or {}
        self.c["verify_ticks"] += int(r1.get("ticks") or 0) + int(r2.get("ticks") or 0)
        row = clear_row(cand, out, self.ref_t)
        row["utc"] = g.utc()
        row["phase"] = self.phase
        self.vrows.append(row)
        self.fs.append_jsonl(self.dir / "verifications.jsonl", row)
        self.event(f"verification of dispatch {cand['n']} cell {cand['cid']} k {cand['k']}: {out['verdict']} {out.get('completion_input_tick')} / {out.get('completion_time_passed')} "
                   f"(reference {self.ref_t}; {'FASTER by ' + str(row['gain_vs_reference']) if row['faster_than_reference'] else 'not faster'})")
        if out["verdict"] == fv.NONDETERMINISTIC:
            self.mark("SEARCH_INVALID", f"dispatch {cand['n']} cell {cand['cid']} k {cand['k']}: a claimed clear did not replay exactly: {row['reasons'][:2]}")
        self.write_progress()

    def verification_step(self) -> None:
        if self.vthread is not None and not self.vthread.is_alive():
            self.vthread = None
            self.on_verified(self.vbox["cand"], self.vbox["out"])
            self.vbox = {}
        if self.vthread is None and self.vqueue and not self.stopping:
            if self.lent is None:
                idle = [w for w in self.pool.idle()] if self.pool else []
                if idle:
                    self.lent = idle[0]
            if self.lent is not None and self.lent not in self.pool.busy:
                cand = self.vqueue.pop(0)
                self.vbox = {"cand": cand}

                def work() -> None:
                    self.vbox["out"] = self.verify_candidate(cand, 0)

                self.vthread = threading.Thread(target=work, name="crossing-verify", daemon=True)
                self.vthread.start()
        elif self.vthread is None and not self.vqueue and self.lent is not None:
            self.lent = None

    # -- drain, close -----------------------------------------------------------------------------------------------------------------------------

    def drain(self) -> None:
        cfg, env, pool = self.cfg, self.env, self.pool
        assert pool is not None
        self.phase = "drain"
        t = env.now()
        while pool.busy and env.now() - t < cfg.stop_grace_s and not pool.abort.is_set():
            for w, kind, payload in pool.poll2(0.2, self.on_boundary):
                self.handle(w, kind, payload)
        if pool.busy:
            pool.abort.set()
            while pool.busy and env.now() - t < 2 * cfg.stop_grace_s:
                for w, kind, payload in pool.poll2(0.2, self.on_boundary):
                    self.handle(w, kind, payload)
        if pool.busy:
            dead = pool.kill_busy()
            for w in dead:
                self.inflight.pop(w, None)
            self.mark("SEARCH_INCOMPLETE", f"workers {dead} did not return after the stop and were terminated")
        self.phase_wall["drain"] = round(env.now() - t, 1)

    def close(self) -> None:
        cfg, env = self.cfg, self.env
        if not self.search_wall and self.t_search != self.t0:
            self.search_wall = env.now() - self.t_search
        self.phase = "close"
        t = env.now()
        if self.pool is not None:
            self.pool.stop(grace=60.0)
        left = env.wait_no_battleship(60.0)
        if self.vthread is not None:
            self.vthread.join(timeout=120.0)
            if not self.vthread.is_alive():
                self.on_verified(self.vbox["cand"], self.vbox["out"])
            else:
                self.unverified.append({"n": self.vbox["cand"]["n"], "cid": self.vbox["cand"]["cid"], "k": self.vbox["cand"]["k"], "words": len(self.vbox["cand"]["words"]),
                                        "why": "the in-run verification did not return"})
            self.vthread = None
        self.close_verifications()
        changed = [rel for rel, h in self.code.items() if (g.REPO / rel).is_file() and g.sha256_file(g.REPO / rel) != h]
        self.integrity.update({"guard_violations_main": list(g.LabGuard.violations)[:5], "lab_code_changed_during_run": changed,
                               "lab_code_digest_end": fr.code_digest(env.code_manifest()) if self.code else None, "lab_code_digest_expected": cfg.expect_code,
                               "battleship_left": left, "tick0_unequal_jobs": self.c["tick0_unequal"], "prefix_mismatches": self.c["mismatches"],
                               "seed_failures": self.seed_stats["dropped"], "reference_ok": self.reference.get("ok")})
        if left:
            self.mark("SEARCH_INCOMPLETE", f"BattleShip processes still alive after the close: {left}")
        self.phase_wall["close"] = round(env.now() - t, 1)
        self.write_summary()
        self.log(f"done: {self.status} ({self.stop_reason}); summary {self.dir / 'summary.json'}")

    def close_verifications(self) -> None:
        deadline = self.t0 + self.cfg.max_wall_s - self.cfg.write_reserve_s
        if not self.vqueue:
            return
        self.phase = "verify"
        lock = threading.Lock()
        queue = list(self.vqueue)
        self.vqueue = []
        results: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []

        def worker(slot: int) -> None:
            while True:
                with lock:
                    if not queue or self.env.now() >= deadline:
                        return
                    cand = queue.pop(0)
                out = self.verify_candidate(cand, slot)
                with lock:
                    results.append((cand, out))

        n = max(1, min(self.cfg.verify_parallel, len(queue)))
        ths = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(n)]
        for th in ths:
            th.start()
        for th in ths:
            th.join(timeout=max(1.0, deadline - self.env.now() + 180.0))
        for cand, out in results:
            self.on_verified(cand, out)
        self.unverified += [{"n": c["n"], "cid": c["cid"], "k": c["k"], "words": len(c["words"]), "claim": c["claim"], "why": "the close deadline"} for c in queue]
        if self.unverified:
            self.log(f"{len(self.unverified)} clear candidates NOT verified before the deadline (never clears)")

    # -- the summary, the report and the progress file --------------------------------------------------------------------------------------------

    def summary(self) -> Dict[str, Any]:
        mem = self.sampler.report() if self.sampler is not None else {}
        series = [r for r in (self.sampler.series if self.sampler else []) if r.get("phase") in ("search", "seed")]
        soft_main = float((self.env.soft or fm.soft_budget(self.env.caps or fm.CAPS_MB))["main_private"])
        cap_main = float((self.env.caps or fm.CAPS_MB)["main_private"])
        wall = self.search_wall if self.search_wall else max(0.0, self.env.now() - self.t_search)
        proj = fm.projection(series, load_mb=float(series[0]["main_private_mb"]) if series else None, load_cells=int(series[0]["cells"]) if series else 0,
                             explore_s=wall, soft_main_mb=soft_main, cap_main_mb=cap_main)
        ex_h = max(1e-9, wall / 3600.0)
        verified = self.verified_clears()
        best = min(verified, key=lambda v: (v["completion_input_tick"], v["completion_time_passed"]), default=None)
        eff = {k: {kk: {"jobs": v[0], "advanced": v[1], "new_cells": v[2], "advanced_share": round(v[1] / v[0], 4) if v[0] else None,
                        "new_cells_per_job": round(v[2] / v[0], 2) if v[0] else None} for kk, v in d.items()} if k != "segments" else dict(sorted(d.items(), key=lambda kv: int(kv[0])))
               for k, d in self.effects.items()}
        return {"mode": "lab", "contract": SEARCH_CONTRACT, "status": self.status, "stop": {"reason": self.stop_reason, "notes": self.notes[:12]},
                "utc_start": self.utc_start, "utc_end": g.utc(), "folder": str(self.dir), "phase_wall_s": dict(self.phase_wall, search=round(wall, 1)),
                "elapsed_s": round(self.elapsed(), 1),
                "config": {"params": self.p.as_dict(), "n_workers": self.cfg.n_workers, "max_ticks": self.cfg.max_ticks, "max_wall_s": self.cfg.max_wall_s, "arm": ARM_NAME,
                           **self.arm, "lab_code_digest": self.code_dig, "backend": self.env.backend, "seed_set_digest": self.plan["seed_set_digest"],
                           "frontier": self.plan["frontier"], "e7": self.plan["e7"]},
                "work": dict(self.c, ticks_total=self.used_ticks(), in_flight=len(self.inflight)),
                "throughput": {"jobs_per_h": round(self.c["jobs"] / ex_h, 1), "ticks_per_h": round(self.c["ticks"] / ex_h), "burst_ticks_per_h": round(self.c["burst_ticks"] / ex_h),
                               "new_cells_per_h": round(self.archive.counts[NEW] / ex_h, 1), "continuation_rate": round(self.c["continued"] / self.c["boundaries"], 4) if self.c["boundaries"] else None,
                               "mean_ticks_per_job": round(self.c["ticks"] / self.c["jobs"], 1) if self.c["jobs"] else None,
                               "mean_burst_words": round(self.c["burst_ticks"] / self.c["jobs"], 1) if self.c["jobs"] else None},
                "seed": {k: v for k, v in self.seed_stats.items()}, "archive": self.archive.stats(), "per_level": self.archive.per_level(),
                "dispatch_per_level": dict(sorted(self.per_level.items(), key=lambda kv: -int(kv[0]))), "deepest": self.archive.deepest(),
                "earliest_by_level": {str(lv): dict(e, reference=self.arrival.get(lv), lead=self.arrival.get(lv, 0) - e["tick"]) for lv, e in sorted(self.archive.earliest.items(), reverse=True)},
                "effects": eff, "reference": dict(self.reference, completion_input_tick_expected=self.ref_t),
                "clears": {"candidates": len(self.vrows) + len(self.unverified), "verified": len(verified), "faster_than_reference": sum(1 for v in verified if v["faster_than_reference"]),
                           "reference_completion_input_tick": self.ref_t,
                           "best_verified": None if best is None else {k: best[k] for k in ("n", "cid", "k", "level", "start_tick", "completion_input_tick", "completion_time_passed",
                                                                                              "gain_vs_reference", "chain_r1", "chain_r2", "words_digest")},
                           "rows": [{k: v.get(k) for k in ("n", "cid", "k", "level", "start_tick", "lead", "words", "verdict", "completion_input_tick", "completion_time_passed",
                                                           "gain_vs_reference", "chain_r1", "chain_r2", "clocks_r1", "clocks_r2", "words_digest", "faster_than_reference", "reasons", "utc")}
                                    for v in self.vrows]},
                "unverified": self.unverified, "events": list(self.events),
                "memory": {"peak": mem.get("peak"), "soft_breach": mem.get("soft_breach"), "hard_breach": mem.get("hard_breach"), "proc_breach": mem.get("proc_breach"),
                           "soft_budget_mb": mem.get("soft_budget_mb"), "projection": proj, "words_mb": round(self.archive.words_bytes / 2 ** 20, 1)},
                "integrity": self.integrity}

    def write_summary(self) -> Dict[str, Any]:
        if self.sampler is not None:
            self.sampler.stop()
        s = self.summary()
        self.fs.write_text(self.dir / "summary.json", frep.compact_json(s), atomic=True)
        self.fs.write_text(self.dir / "report.md", report_md(s), atomic=True)
        self.fs.write_text(self.dir / "progress.md", progress_md(s, final=True), atomic=True)
        return s

    def write_progress(self) -> None:
        try:
            self.fs.write_text(self.dir / "progress.md", progress_md(self.summary(), final=False), atomic=True)
        except (OSError, g.LabRootError):
            pass


# -- rendering --------------------------------------------------------------------------------------------------------------------------------


def _clear_lines(s: Mapping[str, Any]) -> List[str]:
    cl = s["clears"]
    ref = frep.fmt(cl["reference_completion_input_tick"])
    lines = [f"Reference clear: {ref} input ticks. Clears: {cl['candidates']} claimed, {cl['verified']} verified (two exact fresh-process replays from tick 0 each), "
             f"{cl['faster_than_reference']} faster than the reference; pending verification: {s['work'].get('clears_claimed', 0) - cl['candidates']}.", ""]
    if cl["rows"]:
        lines += ["| found (dispatch, cell, k) | level / start tick | verdict | replay 1: completion_input_tick / completion_time_passed | replay 2 | against the reference | replay 1 chain | replay 2 chain | utc |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for v in cl["rows"]:
            vs = "-" if v.get("gain_vs_reference") is None else (f"{v['gain_vs_reference']} ticks FASTER" if v["gain_vs_reference"] > 0 else f"{-v['gain_vs_reference']} ticks slower"
                                                                 if v["gain_vs_reference"] < 0 else "equal")
            lines.append(f"| {v['n']}, {v['cid']}, {v['k']} | {v['level']} / {frep.fmt(v['start_tick'])} | {v['verdict']} | {frep.fmt(v['clocks_r1'][0])} / {frep.fmt(v['clocks_r1'][1])} | "
                         f"{frep.fmt(v['clocks_r2'][0])} / {frep.fmt(v['clocks_r2'][1])} | {vs} | `{v['chain_r1']}` | `{v['chain_r2']}` | {v.get('utc')} |")
    else:
        lines.append("No verified clear yet.")
    if s.get("unverified"):
        lines.append(f"\nCandidates NOT verified (never clears): {json.dumps(s['unverified'], default=str)[:800]}")
    return lines


def _deepest_lines(s: Mapping[str, Any]) -> List[str]:
    dp = s.get("deepest") or {}
    lines = [f"Deepest level reached: **{dp.get('level', '-')}** at tick {frep.fmt(dp.get('tick'))} (reference arrival {frep.fmt(dp.get('reference'))}, lead {frep.fmt(dp.get('lead'))}; "
             f"cell {dp.get('cid')}, found at dispatch {frep.fmt(dp.get('at_dispatch'))}).", "",
             "| level | earliest tick | reference | lead | cell | at dispatch | utc |", "|---|---|---|---|---|---|---|"]
    for lv, e in (s.get("earliest_by_level") or {}).items():
        lines.append(f"| {lv} | {frep.fmt(e.get('tick'))} | {frep.fmt(e.get('reference'))} | {frep.fmt(e.get('lead'))} | {e.get('cid')} | {frep.fmt(e.get('at_dispatch'))} | {e.get('utc')} |")
    return lines


def _level_lines(s: Mapping[str, Any]) -> List[str]:
    lines = ["| level | cells | eligible | with breaks | replaced | dispatches | advanced | falls | clears | new cells | later arrivals | continued / boundaries | earliest tick (lead) | max dispatches of a cell |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    levels = sorted({int(lv) for lv in s["per_level"]} | {int(lv) for lv in s["dispatch_per_level"]}, reverse=True)
    for lv in levels:
        a = s["per_level"].get(str(lv)) or {}
        d = s["dispatch_per_level"].get(str(lv)) or {}
        lines.append(f"| {lv} | {frep.fmt(a.get('cells', 0))} | {frep.fmt(a.get('eligible', 0))} | {a.get('cells_with_breaks', 0)} | {a.get('replaced', 0)} | {frep.fmt(d.get('jobs', 0))} | "
                     f"{d.get('advanced', 0)} | {d.get('falls', 0)} | {d.get('clears', 0)} | {frep.fmt(d.get('new_cells', 0))} | {frep.fmt(d.get('later', 0))} | "
                     f"{d.get('continued', 0)} / {d.get('boundaries', 0)} | {frep.fmt(a.get('earliest_tick'))} ({frep.fmt(a.get('best_lead'))}) | {a.get('max_dispatched', 0)} |")
    return lines


def _effect_lines(s: Mapping[str, Any]) -> List[str]:
    e = s["effects"]
    lines = ["| signal | bucket | jobs | advanced (share) | new cells per job |", "|---|---|---|---|---|"]
    for name in ("bonus", "seen", "fresh"):
        for b, d in e[name].items():
            lines.append(f"| {name} | {b} | {frep.fmt(d['jobs'])} | {d['advanced']} ({frep.fmt(d['advanced_share'], 4)}) | {frep.fmt(d['new_cells_per_job'], 2)} |")
    lines.append(f"\nBurst lengths (jobs by words bucket): {json.dumps(e['segments'])}")
    return lines


def progress_md(s: Mapping[str, Any], *, final: bool) -> str:
    w, th, mem, ar = s["work"], s["throughput"], s["memory"], s["archive"]
    peak = mem.get("peak") or {}
    state = f"**{s['status']}** ({s['stop']['reason']})" if final or s["stop"]["reason"] else "**RUNNING**"
    lines = [f"# Crossing search: progress ({s['utc_start'][:10]})", "",
             f"{'Final. ' if final else ''}Status {state}. Updated {s['utc_end']}; elapsed {s['elapsed_s'] / 60.0:.0f} of {s['config']['max_wall_s'] / 60.0:g} min. "
             f"Dispatches {frep.fmt(w['dispatches'])} (jobs {frep.fmt(w['jobs'])}, advanced {frep.fmt(w['advanced'])}, falls {frep.fmt(w['falls'])}); "
             f"ticks {frep.fmt(w['ticks_total'])} of {frep.fmt(s['config']['max_ticks'])}; {frep.fmt(th['jobs_per_h'], 0)} jobs / h, {frep.fmt(th['ticks_per_h'])} ticks / h, "
             f"continuation {frep.fmt(th['continuation_rate'], 3)}. Cells {frep.fmt(ar['cells'])} (eligible {frep.fmt(ar['eligible'])}, new {frep.fmt(ar['new'])}, replaced "
             f"{frep.fmt(ar['replaced'])}, later arrivals {frep.fmt(ar['later'])}, beyond the E7 bound {frep.fmt(ar['beyond'])}, quarantined {ar['quarantined']}, retired "
             f"{ar['retired']}), words {frep.fmt(mem.get('words_mb'), 1)} MB. Main process {frep.fmt(peak.get('main_private_mb'), 0)} MB peak, tree {frep.fmt(peak.get('tree_private_mb'), 0)} MB, "
             f"BattleShip processes {peak.get('battleship')} peak.",
             f"Params: {json.dumps(s['config']['params'])}; arm {s['config']['arm']} (segments {s['config']['segment_words']} x {s['config']['max_segments']}, F3 window "
             f"{s['config']['window']}). Reference clear replayed exactly at open: {s['reference'].get('ok')} ({frep.fmt(s['reference'].get('completion_input_tick'))} / "
             f"{frep.fmt(s['reference'].get('completion_time_passed'))}); E7 bound {frep.fmt(s['config']['e7'].get('bound_max_L'))}.", "",
             "## Verified clears", ""] + _clear_lines(s) + ["", "## Deepest level and earliest ticks", ""] + _deepest_lines(s) + ["", "## Cells per level", ""] + _level_lines(s)
    lines += ["", "## Effects of the signals", ""] + _effect_lines(s)
    lines += ["", "## Recent events", ""] + [f"- {e}" for e in reversed(s.get("events") or [])][:25]
    lines += ["", f"Seed: {json.dumps({k: v for k, v in s['seed'].items() if k != 'per_level'}, default=str)}",
              f"Memory projection: {json.dumps(mem.get('projection'), default=str)[:500]}", ""]
    return "\n".join(lines)


def report_md(s: Mapping[str, Any]) -> str:
    w, th, mem, cl, ar = s["work"], s["throughput"], s["memory"], s["clears"], s["archive"]
    peak = mem.get("peak") or {}
    lines = [f"# Crossing search run ({s['utc_start'][:10]})", "",
             f"Lab, exploratory, unregistered (mode lab). Status **{s['status']}** ({s['stop']['reason']}). Arm {s['config']['arm']} (segments {s['config']['segment_words']} x "
             f"{s['config']['max_segments']}, F3 window {s['config']['window']}); params {json.dumps(s['config']['params'])}; {s['config']['n_workers']} workers.", "",
             "| measure | value |", "|---|---|",
             f"| wall / open / seed / search / drain / close | {frep.fmt(s['elapsed_s'], 0)} s / {frep.fmt(s['phase_wall_s'].get('open'), 0)} s / {frep.fmt(s['phase_wall_s'].get('seed'), 0)} s / "
             f"{frep.fmt(s['phase_wall_s'].get('search'), 0)} s / {frep.fmt(s['phase_wall_s'].get('drain'), 0)} s / {frep.fmt(s['phase_wall_s'].get('close'), 0)} s |",
             f"| dispatches / jobs / advanced / falls | {frep.fmt(w['dispatches'])} / {frep.fmt(w['jobs'])} / {frep.fmt(w['advanced'])} / {frep.fmt(w['falls'])} |",
             f"| ticks: total / prefix / burst / seed / reference / verification | {frep.fmt(w['ticks_total'])} / {frep.fmt(w['prefix_ticks'])} / {frep.fmt(w['burst_ticks'])} / "
             f"{frep.fmt(w['seed_ticks'])} / {frep.fmt(w['reference_ticks'])} / {frep.fmt(w['verify_ticks'])} |",
             f"| throughput: jobs / h, ticks / h, new cells / h, continuation rate, mean ticks per job, mean burst words | {frep.fmt(th['jobs_per_h'], 0)} / {frep.fmt(th['ticks_per_h'])} / "
             f"{frep.fmt(th['new_cells_per_h'], 0)} / {frep.fmt(th['continuation_rate'], 3)} ({w['continued']} of {w['boundaries']}) / {frep.fmt(th['mean_ticks_per_job'], 0)} / "
             f"{frep.fmt(th['mean_burst_words'], 0)} |",
             f"| seeds / reproduced / dropped | {s['seed']['seeds']} / {s['seed']['ok']} / {s['seed']['dropped']} |",
             f"| cells / new / replaced / later / self / beyond E7 / terminal / quarantined / retired / eligible | {frep.fmt(ar['cells'])} / {frep.fmt(ar['new'])} / {frep.fmt(ar['replaced'])} / "
             f"{frep.fmt(ar['later'])} / {frep.fmt(ar['self'])} / {frep.fmt(ar['beyond'])} / {frep.fmt(ar['terminal'])} / {ar['quarantined']} / {ar['retired']} / {frep.fmt(ar['eligible'])} |",
             f"| reference clear replayed exactly at open | {s['reference'].get('ok')} ({frep.fmt(s['reference'].get('completion_input_tick'))} / "
             f"{frep.fmt(s['reference'].get('completion_time_passed'))}) |",
             f"| clear candidates / verified / faster than the reference ({frep.fmt(cl['reference_completion_input_tick'])}) | {cl['candidates']} / {cl['verified']} / {cl['faster_than_reference']} |",
             f"| main process MB peak / tree MB peak / BattleShip peak / words MB | {frep.fmt(peak.get('main_private_mb'), 0)} / {frep.fmt(peak.get('tree_private_mb'), 0)} / "
             f"{peak.get('battleship')} / {frep.fmt(mem.get('words_mb'), 1)} |",
             f"| memory projection | {json.dumps(mem.get('projection'), default=str)[:400]} |",
             "", "## Clears", ""] + _clear_lines(s) + ["", "## Deepest level and earliest ticks", ""] + _deepest_lines(s) + ["", "## Cells per level", ""] + _level_lines(s)
    lines += ["", "## Effects of the signals", ""] + _effect_lines(s) + ["", "## Events", ""] + [f"- {e}" for e in (s.get("events") or [])]
    lines += ["", f"Seed: {json.dumps(s['seed'], default=str)}", "", f"Integrity: {json.dumps(s['integrity'], separators=(',', ':'), default=str)}", ""]
    return "\n".join(lines)


# -- commands ---------------------------------------------------------------------------------------------------------------------------------


def params_from_args(a: argparse.Namespace) -> Params:
    p = Params(seeds=a.seeds, seed_order=a.seed_order, level_decay=a.level_decay, novelty_exp=a.novelty_exp, seen_exp=0.0 if a.no_seen_penalty else a.seen_exp,
               bonus_exp=0.0 if a.no_break_bonus else a.bonus_exp, pace_exp=a.pace_exp, max_segments=a.max_segments, retire_after=a.retire_after, max_cells=a.max_cells,
               max_dispatches=a.max_dispatches, rng_seed=a.rng_seed)
    p.check()
    return p


def plan_and_write(lab_root: Path, frontier_dir: Path, out: Path, params: Params, analyse: fv.Analyse = fv.real_analyse) -> Dict[str, Any]:
    """Zero native ticks: the seeds and their checks, written as plan.json and seeds.jsonl (a different seed set is never overwritten)."""
    P = build_search_plan(Path(lab_root), Path(frontier_dir), params, analyse)
    fs = g.LabFS(lab_root)
    saved = Path(out) / "plan.json"
    if saved.is_file():
        old = json.loads(saved.read_text(encoding="utf-8"))
        if old.get("seed_set_digest") != P["plan"]["seed_set_digest"]:
            raise SearchError(f"refused: {saved} exists with a different seed set ({str(old.get('seed_set_digest'))[:16]})")
    fs.mkdir(Path(out))
    fs.write_json(saved, P["plan"])
    fs.write_text(Path(out) / "seeds.jsonl", "".join(json.dumps(seed_row(s), separators=(",", ":"), default=str) + "\n" for s in P["seeds"]))
    return P


def run_command(lab_root: Path, frontier: Path, out: Path, a: argparse.Namespace) -> str:
    return (f"python -B tools/frs/crossing_search.py run --lab-root {Path(lab_root).as_posix()} --frontier {Path(frontier).as_posix()} --out {Path(out).as_posix()} "
            f"--workers {a.workers} --seeds {a.seeds} --seed-order {a.seed_order} --level-decay {a.level_decay:g} --novelty-exp {a.novelty_exp:g} --seen-exp {a.seen_exp:g} "
            f"--bonus-exp {a.bonus_exp:g} --pace-exp {a.pace_exp:g} --max-segments {a.max_segments} --retire-after {a.retire_after} --max-cells {a.max_cells} "
            f"--rng-seed {a.rng_seed} --max-ticks {a.max_ticks} --max-wall-min {a.max_wall_min:g}"
            + (" --no-seen-penalty" if a.no_seen_penalty else "") + (" --no-break-bonus" if a.no_break_bonus else "")
            + (f" --max-dispatches {a.max_dispatches}" if a.max_dispatches else ""))


def cmd_plan(lab_root: Path, frontier: Path, out: Path, a: argparse.Namespace) -> int:
    params = params_from_args(a)
    P = plan_and_write(lab_root, frontier, out, params)
    p = P["plan"]
    print(json.dumps({k: p[k] for k in ("seeds", "seed_ticks", "seed_rule", "lineage_depth", "seed_set_digest", "e7")}, separators=(",", ":"), default=str))
    print(json.dumps({"frontier": p["frontier"], "route": p["route"], "params": p["params"], "arm": p["arm"]}, separators=(",", ":"), default=str))
    for lv, d in p["per_level"].items():
        print("level", lv, json.dumps(d, separators=(",", ":"), default=str))
    proj = projection(p["throughput_fit"], P["seeds"], params, P["bound"], a.workers, a.max_wall_min / 60.0)
    print("throughput fit", json.dumps(p["throughput_fit"], separators=(",", ":")))
    print("projection", json.dumps(proj, separators=(",", ":")))
    print(f"lab code digest now {fr.code_digest(fr.code_manifest())[:16]}; the frontier's {str(p['frontier'].get('lab_code_digest'))[:16]}")
    print(f"wrote {Path(out) / 'plan.json'} and {Path(out) / 'seeds.jsonl'}")
    print("run with:", run_command(lab_root, frontier, out, a))
    return 0


def cmd_run(lab_root: Path, frontier: Path, out: Path, a: argparse.Namespace) -> int:
    import frs_lab as fl
    from m7_runtime import install_kill_on_close_job

    run_dir = Path(out) / "run"
    if run_dir.exists():
        print(f"refused: {run_dir} exists (never overwritten)")
        return 2
    saved = Path(out) / "plan.json"
    if not saved.is_file():
        print(f"refused: no {saved}: run `plan` first")
        return 2
    params = params_from_args(a)
    P = build_search_plan(lab_root, frontier, params)
    old = json.loads(saved.read_text(encoding="utf-8"))
    if old.get("seed_set_digest") != P["plan"]["seed_set_digest"]:
        print("refused: the seed set differs from the saved plan")
        return 2
    if old.get("params") != params.as_dict():
        print(f"refused: the parameters differ from the saved plan's ({old.get('params')})")
        return 2
    install_kill_on_close_job()
    cfg = SearchConfig(lab_root=Path(lab_root), out=Path(out), run_dir=run_dir, frontier_dir=Path(frontier), n_workers=a.workers, max_ticks=a.max_ticks,
                       max_wall_s=60.0 * a.max_wall_min, expect_code=P["F"]["config"].get("lab_code_digest"))
    code = Search(cfg, fl.real_env(Path(lab_root), run_dir), P, params).run()
    print(f"exit {code}: {run_dir / 'report.md'} (progress: {run_dir / 'progress.md'})")
    return code


def default_frontier(lab: Path) -> Optional[Path]:
    """The newest frontier search output folder under the lab root (by name), if any."""
    hits = sorted(p for p in lab.glob("frontier_*") if p.is_dir() and all((p / f).is_file() for f in FRONTIER_FILES) and (p / FRONTIER_DIR).is_dir())
    return hits[-1] if hits else None


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("command", choices=("plan", "run"))
    ap.add_argument("--lab-root", default=str(g.DEFAULT_LAB_ROOT))
    ap.add_argument("--frontier", default=None, help="the frontier search's output folder (default: the newest frontier_* under the lab root)")
    ap.add_argument("--out", default=None, help="default <lab root>/crossing_<date>")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--seeds", type=int, default=Params.seeds, help="S: the top S states of the seed rule")
    ap.add_argument("--seed-order", choices=SEED_ORDERS, default=Params.seed_order)
    ap.add_argument("--level-decay", type=float, default=Params.level_decay, help="level draw weight decay^(deepest eligible level - level)")
    ap.add_argument("--novelty-exp", type=float, default=Params.novelty_exp, help="(1 + dispatches since the representative was set)^-exp")
    ap.add_argument("--seen-exp", type=float, default=Params.seen_exp, help="(1 + later arrivals at the key)^-exp")
    ap.add_argument("--no-seen-penalty", action="store_true")
    ap.add_argument("--bonus-exp", type=float, default=Params.bonus_exp, help="(1 + dispatches that broke a target)^exp")
    ap.add_argument("--no-break-bonus", action="store_true")
    ap.add_argument("--pace-exp", type=float, default=Params.pace_exp, help="(E7 bound - tick + 1)^exp")
    ap.add_argument("--max-segments", type=int, default=Params.max_segments, help="CONT continuation: at most this many 120-word segments per burst")
    ap.add_argument("--retire-after", type=int, default=Params.retire_after, help="retire a cell after this many dispatches without a break or a new cell (0 = off)")
    ap.add_argument("--max-cells", type=int, default=Params.max_cells)
    ap.add_argument("--max-dispatches", type=int, default=Params.max_dispatches)
    ap.add_argument("--rng-seed", type=int, default=Params.rng_seed, help="the Python experiment seed of the draws (never a native seed)")
    ap.add_argument("--max-ticks", type=int, default=SearchConfig.max_ticks)
    ap.add_argument("--max-wall-min", type=float, default=420.0)
    a = ap.parse_args(argv)
    try:
        lab = g.validate_lab_root(Path(a.lab_root))
        out = g.validate_run_dir(Path(a.out) if a.out else lab / f"crossing_{dt.date.today().isoformat()}", lab)
        frontier = Path(a.frontier) if a.frontier else default_frontier(lab)
        if frontier is None:
            raise SystemExit("refused: no frontier search output folder (pass --frontier)")
        frontier = g.validate_run_dir(frontier, lab)
    except g.LabRootError as exc:
        raise SystemExit(str(exc))
    missing = [f for f in FRONTIER_FILES if not (frontier / f).is_file()]
    if missing or not (frontier / FRONTIER_DIR).is_dir():
        raise SystemExit(f"refused: {frontier} is not a frontier search output folder (missing {missing or [FRONTIER_DIR]})")
    if not 1 <= a.workers <= 5:
        raise SystemExit("refused: 1 to 5 workers (one standby each: at most 10 game processes)")
    if a.max_ticks < 1 or a.max_wall_min <= 0:
        raise SystemExit("refused: --max-ticks and --max-wall-min are positive")
    try:
        params_from_args(a)
    except SearchError as exc:
        raise SystemExit(str(exc))
    if not (lab / "import" / "import_manifest.json").is_file():
        raise SystemExit("refused: no lab import (rl/frs_lab.py import first)")
    g.LabGuard.install(lab)
    lock = g.LabLock(lab, f"crossing_search {a.command}")
    try:
        lock.acquire()
    except g.LabRootError as exc:
        print(str(exc))
        return 2
    try:
        if a.command == "plan":
            return cmd_plan(lab, frontier, out, a)
        return cmd_run(lab, frontier, out, a)
    except SearchError as exc:
        print(str(exc))
        return 3
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
