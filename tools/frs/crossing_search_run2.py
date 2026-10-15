#!/usr/bin/env python3
"""Crossing search, run 2 (lab, exploratory, unregistered): the crossing search continued from run 1's archive instead of fresh seeds,
to find a clear faster than run 1's best verified clear. Everything of run 1 (tools/frs/crossing_search.py: the archive, the keep / replace
/ E7 logic, the selection terms, the CONT bursts, the dispatch and verification rows, the reports) is reused by import; run 1's tool is not
modified. The changes:

    resume          run 1's `run/cells.jsonl` holds every kept cell with its exact prefix; the FINAL representative of every cell (the last
                    row per cell id) is loaded, with the same cell ids, its key, tick, prefix words, chain and record digests, its later-
                    arrival count (`seen`, as last recorded) and its dispatch statistics (dispatches, breaks) rebuilt from run 1's dispatch
                    rows (by its key family and prefix digest). Cells beyond run 2's E7 bound are loaded too (ineligible, but a faster arrival
                    at their key replaces the representative and makes it a fresh start). Run 1's end records (the observation tuple at the
                    cell's tick, which the worker compares before every burst) are NOT on disk: every inherited cell is therefore checked
                    natively before its first burst, by a fresh-process replay of its prefix from tick 0 with the verify flags (run 1's seed
                    check: every tick under the tick contract, the episode live, the chain digest, the record digest, the cell key and the
                    level equal to run 1's record); the replay's last observation becomes the end record. Eagerly at the open for the deepest
                    eligible level(s) (and the earliest cells of every level) within a wall budget; lazily for every other cell on its first
                    draw (the draw is kept, the cell is checked on a lent worker, then dispatched); a cell whose prefix does not reproduce is
                    quarantined; more than `mismatch_limit` (3) quarantines (eager, lazy or the worker's own prefix check) is SEARCH_INVALID.
    E7 bound        from the best VERIFIED clear of run 1 (`run/verifications.jsonl`, the lowest completion_input_tick among VERIFIED rows,
                    required to be faster than the reference) minus the registered margin (rl/frs_run.MARGIN) minus one, through the
                    registered rule (m8_sd1_select.record_bound_max_L). Never a literal. Fixed for the run. That clear is replayed once at
                    the open in a fresh process and must reproduce exactly (clocks, chain, action digest, breaks).
    cleared starts  a representative whose dispatch produced a claimed clear has its selection weight multiplied by cleared_weight per clear
                    (default 0.1: a tenth after one clear, a hundredth after two; 0 = never drawn again). Run 1's evidence: 298 clears from
                    118 starts, 180 re-draw clears of which 151 repeated the clock, 15 were slower and 14 faster, one of them the run's
                    second-best clear (a 71-tick gain on the start's third dispatch): a strong down-weight, not a retirement. Run 1's own
                    cleared starts (still the final representative) are loaded with their clear count. A faster arrival lifts it.
    verification    a claimed clear is replayed (twice, from tick 0, fresh processes, verify flags) only when its claimed clock is faster
                    than the best verified clear so far (run 1's at the open, then run 2's); slower or equal claims are counted and recorded
                    (claims_not_replayed.jsonl, with their words) but not replayed. A verified faster clear becomes the new best; queued
                    slower claims are dropped. The reference (run 1's import) is still replayed at the open.
    key family      run 2's bursts draw from the key family `<archive id>|crossing2|<prefix digest>` (iteration 0, 1, ... per representative),
                    so no burst of run 1 is ever repeated whatever the dispatch count carried over.
    selection       run 1's level, novelty, seen, break-bonus and pace terms unchanged (same defaults), plus the cleared factor above.
    progress.md     rewritten at least every minute: the best verified clear against run 1's best and the reference, the deepest level with
                    its earliest tick, the cells per level, and the lineages (root seed of run 1) ahead of the best clear's pace at the two
                    deepest live levels.
    caps            wall (argument, default 480 min), ticks, cells, at most 5 workers with one standby each and lent workers for the checks
                    (at most 10 game processes), the lab's memory budget and projection, readiness at the registered thresholds.

    python -B tools/frs/crossing_search_run2.py plan --lab-root C:/BattleShip_lab --run1 C:/BattleShip_lab/crossing_2026-10-15 [--out DIR] ...
    python -B tools/frs/crossing_search_run2.py run  --lab-root ... --run1 DIR --out DIR [--workers 5] [--max-wall-min 480] ...

`plan` is zero native ticks; `run` is native. Writes only under the output folder (default <lab root>/crossing_<date>_run2) through the lab's
guard; the lab lock; readiness never lowered; nothing reads native RNG; process restart resets the episode (every check, burst and
verification replay is a fresh process from tick 0). No coordinate, target id, direction, cell id, route or census number is in any rule.
Zero-tick tests: tools/frs/crossing_search_run2_tests.py. Run with python -B.
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
from collections import deque
from dataclasses import dataclass
from itertools import accumulate
from pathlib import Path
from typing import Any, Deque, Dict, List, Mapping, Optional, Sequence, Set, Tuple

assert sys.flags.dont_write_bytecode, "run with python -B"

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "rl"))
sys.path.insert(0, str(HERE))

import crossing_search as cs  # noqa: E402
import frs_archive as fa  # noqa: E402
import frs_guard as g  # noqa: E402
import frs_machine as fm  # noqa: E402
import frs_report as frep  # noqa: E402
import frs_run as fr  # noqa: E402
import frs_verify as fv  # noqa: E402
import frs_worker as fw  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_sd2_select as s6  # noqa: E402

RUN2_CONTRACT = "frs_crossing_search_run2_v1"
KEY_FAMILY = "crossing2"
RUN1_FILES = ("plan.json", "run/config.json", "run/summary.json", "run/cells.jsonl", "run/dispatches.jsonl", "run/verifications.jsonl", "run/seeds.jsonl")
CLEAN_STATUSES = ("COMPLETED", "ARCHIVE_EMPTY", "TICK_CAP", "WALL_CAP", "CELLS_CAP", "DISPATCH_CAP", "MEMORY_BUDGET")
NOT_REPLAYED = "NOT_REPLAYED"
PACE_LEVELS = (mcell.TARGETS_TOTAL - 2, mcell.TARGETS_TOTAL - 1)          # the two deepest live levels
CHECK_LIMIT_TRIES = 8                                                    # draws per idle worker before it waits for a check
SearchError, Refused = cs.SearchError, cs.Refused


# -- parameters ---------------------------------------------------------------------------------------------------------------------------


@dataclass
class Params2(cs.Params):
    cleared_weight: float = 0.1     # weight factor per claimed clear of a representative (0 = never drawn again)
    check_slots: int = 2            # at most this many workers lent at once to the lazy checks and the clear verifications
    check_queue_max: int = 8        # pending lazy checks before the draws fall back to verified cells only
    eager_levels: int = 1           # the deepest eligible levels checked eagerly at the open (within eager_max_min)
    eager_max_min: float = 15.0     # wall budget of the eager checks (estimated from run 1's replay timings)
    canary_per_level: int = 1       # the earliest eligible cells of every level checked at the open
    reset_novelty: bool = False     # True: inherited cells start at fresh = 0 (their run 1 dispatches are kept as information only)
    check_error_limit: int = 10     # lazy or eager checks whose replay could not run (twice); one more is SEARCH_INCOMPLETE

    def check(self) -> None:
        super().check()
        if not 0.0 <= self.cleared_weight <= 1.0:
            raise SearchError("refused: --cleared-weight is in [0, 1]")
        if self.check_slots < 1 or self.check_queue_max < 1 or self.eager_levels < 0 or self.eager_max_min < 0 or self.canary_per_level < 0 or self.check_error_limit < 0:
            raise SearchError("refused: --check-slots and --check-queue-max are positive; --eager-levels, --eager-max-min, --canary-per-level and --check-error-limit are not negative")

    def as_dict(self) -> Dict[str, Any]:
        d = super().as_dict()
        d.update({"cleared_weight": self.cleared_weight, "check_slots": self.check_slots, "check_queue_max": self.check_queue_max, "eager_levels": self.eager_levels,
                  "eager_max_min": self.eager_max_min, "canary_per_level": self.canary_per_level, "reset_novelty": self.reset_novelty,
                  "check_error_limit": self.check_error_limit, "key_family": KEY_FAMILY})
        return d


# -- run 1's outputs (zero native ticks) ------------------------------------------------------------------------------------------------------


def read_jsonl_iter(p: Path):
    with open(p, encoding="utf-8") as f:
        for ln in f:
            if ln.strip():
                yield json.loads(ln)


def read_run1(run1_dir: Path) -> Dict[str, Any]:
    """Run 1's folder (read-only): its plan, run configuration and summary (checked: a clean stop, no integrity problem), the final
    representative of every cell with its prefix, the origin of every representative ever kept (for the lineage roots), the dispatch
    statistics per representative, every verification row and the seed replay timings."""
    d = Path(run1_dir)
    missing = [f for f in RUN1_FILES if not (d / f).is_file()]
    if missing:
        raise SearchError(f"refused: {d} is not a crossing search output folder (missing {missing})")
    plan = json.loads((d / "plan.json").read_text(encoding="utf-8"))
    config = json.loads((d / "run" / "config.json").read_text(encoding="utf-8"))
    summary = json.loads((d / "run" / "summary.json").read_text(encoding="utf-8"))
    for name, obj in (("plan.json", plan), ("run/config.json", config), ("run/summary.json", summary)):
        if obj.get("contract") != cs.SEARCH_CONTRACT or obj.get("mode") != "lab":
            raise SearchError(f"refused: {d / name} is not a {cs.SEARCH_CONTRACT} lab record")
    if summary.get("status") not in CLEAN_STATUSES:
        raise SearchError(f"refused: run 1 did not stop cleanly (status {summary.get('status')})")
    integ = summary.get("integrity") or {}
    if integ.get("guard_violations_main") or integ.get("lab_code_changed_during_run") or integ.get("reference_ok") is not True \
            or integ.get("lab_code_digest_end") != config.get("lab_code_digest") or integ.get("battleship_left"):
        raise SearchError(f"refused: run 1's integrity record is not clean: {integ}")
    if config.get("params") != plan.get("params") or config.get("seed_set_digest") != plan.get("seed_set_digest"):
        raise SearchError("refused: run 1's run configuration is not its plan's")
    final: Dict[int, Dict[str, Any]] = {}
    origins: Dict[Tuple[int, str], Dict[str, Any]] = {}
    rows = 0
    for r in read_jsonl_iter(d / "run" / "cells.jsonl"):
        rows += 1
        if r.get("ev") not in (cs.NEW, cs.REPLACED) or not r.get("words_hex"):
            raise SearchError(f"run 1 cells.jsonl row {rows}: not a kept representative with its words")
        cid = int(r["cid"])
        origins[(cid, str(r["digest"]))] = r["origin"]
        final[cid] = r
    if not final:
        raise SearchError("refused: run 1 kept no cell")
    disp: Dict[str, List[int]] = {}
    fit_rows: List[Tuple[float, float]] = []
    for r in read_jsonl_iter(d / "run" / "dispatches.jsonl"):
        if r.get("kind") != "burst":
            continue
        fam = str(r.get("draw_id", "")).split("|")
        if len(fam) != 3 or fam[1] != cs.KEY_FAMILY:
            raise SearchError(f"run 1 dispatch {r.get('n')}: its key family {r.get('draw_id')} is not run 1's")
        st = disp.setdefault(fam[2], [0, 0])
        st[0] += 1
        st[1] += int(bool(r.get("advanced")))
        if r.get("outcome") not in cs.BAD_OUTCOMES and r.get("wall_s") and r.get("ticks"):
            fit_rows.append((float(r["ticks"]), float(r["wall_s"])))
    verifications = list(read_jsonl_iter(d / "run" / "verifications.jsonl"))
    seeds = list(read_jsonl_iter(d / "run" / "seeds.jsonl"))
    return {"dir": d, "plan": plan, "config": config, "summary": summary, "final": final, "origins": origins, "rows": rows, "dispatch_stats": disp,
            "fit_rows": fit_rows, "verifications": verifications, "seed_rows": seeds}


def best_verified_of(verifications: Sequence[Mapping[str, Any]], ref_t: int) -> Dict[str, Any]:
    """The best VERIFIED clear of a crossing run: the lowest completion_input_tick (ties: the lowest completion_time_passed, then the first
    dispatch); its two replays must agree; it must be faster than the reference. Its level arrival ticks (the n-th break) are its pace."""
    ok = [v for v in verifications if v.get("kind") == "clear" and v.get("verdict") == fv.VERIFIED and v.get("completion_input_tick") is not None]
    if not ok:
        raise SearchError("refused: run 1 has no VERIFIED clear")
    b = min(ok, key=lambda v: (int(v["completion_input_tick"]), int(v["completion_time_passed"]), int(v["n"])))
    if b.get("chain_r1") != b.get("chain_r2") or b.get("clocks_r1") != b.get("clocks_r2") or b.get("breaks_r1") != b.get("breaks_r2"):
        raise SearchError(f"refused: the best verified clear's two replays disagree (dispatch {b.get('n')})")
    words = bytes.fromhex(b["words_hex"])
    if len(words) != int(b["words"]) or mcell.words_digest(words) != b["words_digest"] or len(words) != int(b["completion_input_tick"]):
        raise SearchError(f"refused: the best verified clear's words do not match its row (dispatch {b.get('n')})")
    if int(b["completion_input_tick"]) >= int(ref_t):
        raise SearchError(f"refused: run 1's best verified clear {b['completion_input_tick']} is not faster than the reference {ref_t}")
    breaks = sorted((int(t), int(i)) for t, i in b["breaks_r1"])
    arrival = {0: 0, **{lv: t for lv, t in cs.level_arrivals(0, breaks)}}
    if arrival.get(mcell.TARGETS_TOTAL) != int(b["completion_input_tick"]):
        raise SearchError("refused: the best verified clear's last break is not at its completion tick")
    return {"n": int(b["n"]), "cid": int(b["cid"]), "k": int(b["k"]), "level": int(b["level"]), "start_tick": int(b["start_tick"]),
            "completion_input_tick": int(b["completion_input_tick"]), "completion_time_passed": int(b["completion_time_passed"]), "chain": str(b["chain_r1"]),
            "words_digest": str(b["words_digest"]), "words": words, "breaks": [list(x) for x in breaks], "arrival": arrival, "source": "run1", "utc": b.get("utc"),
            "verified_in_run1": len(ok)}


def cleared_starts_of(verifications: Sequence[Mapping[str, Any]], final: Mapping[int, Mapping[str, Any]]) -> Dict[int, int]:
    """Clears per cell whose FINAL representative is the start that cleared (the clear's words begin with the representative's prefix)."""
    out: Dict[int, int] = {}
    for v in verifications:
        if v.get("kind") != "clear":
            continue
        r = final.get(int(v["cid"]))
        if r is None or int(r["tick"]) != int(v["start_tick"]):
            continue
        pre = bytes.fromhex(v["words_hex"])[:int(v["start_tick"])]
        if mcell.words_digest(pre) == r["digest"]:
            out[int(v["cid"])] = out.get(int(v["cid"]), 0) + 1
    return out


def root_of(origins: Mapping[Tuple[int, str], Mapping[str, Any]], cid: int, digest: str, memo: Dict[Tuple[int, str], int]) -> int:
    """The run 1 seed (frontier state id) a representative descends from, through the representatives its bursts were dispatched from."""
    key = (int(cid), str(digest))
    if key in memo:
        return memo[key]
    chain: List[Tuple[int, str]] = []
    cur = key
    while cur not in memo:
        o = origins.get(cur)
        if o is None:
            raise SearchError(f"representative {cur} has no recorded origin")
        chain.append(cur)
        if o.get("kind") == "seed":
            memo[cur] = int(o["fsid"])
            break
        if o.get("kind") != "burst":
            raise SearchError(f"representative {cur}: origin kind {o.get('kind')!r}")
        cur = (int(o["parent"]), str(o["parent_digest"]))
    r = memo[cur]
    for c in chain:
        memo[c] = r
    return r


_PRE = [f"{int(b)},{int(x)},{int(y)}," for b, x, y in mcell.TRIPLES]


def words_digest_bulk(words: bytes) -> str:
    """m8_rd_cells.words_digest's digest (sha256 over 'buttons,stick_x,stick_y,consumed_tick' lines) built as one byte string: the same stream,
    one hash update instead of one per word (the loader cross-checks it against the original on a sample at every load)."""
    pre = _PRE
    return hashlib.sha256("".join([pre[w] + str(i) + "\n" for i, w in enumerate(words)]).encode("ascii")).hexdigest()


def check_fit(seed_rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Wall of one fresh-process check from run 1's seed replays: startup plus stepping per tick (least squares)."""
    ok = [r for r in seed_rows if r.get("ok") and r.get("ticks") and r.get("stepping_s") is not None and r.get("startup_s") is not None]
    if len(ok) < 3:
        return {"available": False}
    f = fm.fit([float(r["ticks"]) for r in ok], [float(r["stepping_s"]) for r in ok])
    startup = sum(float(r["startup_s"]) for r in ok) / len(ok)
    per_tick = max(1e-6, f[1]) if f else sum(float(r["stepping_s"]) for r in ok) / sum(float(r["ticks"]) for r in ok)
    overhead = sum(float(r["wall_s"]) - float(r["startup_s"]) - float(r["stepping_s"]) for r in ok) / len(ok)
    return {"available": True, "replays": len(ok), "startup_s": round(startup, 3), "s_per_tick": round(per_tick, 6), "overhead_s": round(max(0.0, overhead), 3)}


def check_wall_s(fit: Mapping[str, Any], ticks: int) -> float:
    if not fit.get("available"):
        return 5.0 + ticks / 500.0
    return float(fit["startup_s"]) + float(fit["overhead_s"]) + float(fit["s_per_tick"]) * int(ticks)


# -- the resumed archive ------------------------------------------------------------------------------------------------------------------------


class ResumeArchive(cs.Archive):
    """Run 1's archive: inherited cells (checked natively before their first burst), run 2's cells, a verified-only draw and the cleared factor."""

    def __init__(self, archive_id: str, arrival: Mapping[Any, int], bound: int, params: Params2):
        super().__init__(archive_id, arrival, bound, params)
        self.p2 = params
        self._wv: Dict[int, List[float]] = {}
        self._nver: Dict[int, int] = {}
        self.root_by_rep: Dict[Tuple[int, str], int] = {}
        self.inherited = 0
        self.counts.update({"inherited": 0, "checked_ok": 0, "pending": 0})

    # -- cell attributes beyond run 1's -------------------------------------------------------------------------------------------------------

    @staticmethod
    def _init_extra(c: cs.Cell, *, inherited: bool, verified: bool, root: Optional[int]) -> None:
        c.inherited = inherited
        c.verified = verified
        c.pending = False
        c.cleared = 0
        c.root = root
        c.check_attempts = 0

    def eligible(self, c: cs.Cell) -> bool:
        if not super().eligible(c):
            return False
        if getattr(c, "pending", False):
            return False
        if getattr(c, "cleared", 0) and self.p2.cleared_weight <= 0.0:
            return False
        return True

    def dispatchable(self, c: cs.Cell) -> bool:
        return self.eligible(c) and bool(getattr(c, "verified", False))

    def cell_weight(self, c: cs.Cell) -> float:
        w = super().cell_weight(c)
        n = getattr(c, "cleared", 0)
        if n and 0.0 < self.p2.cleared_weight < 1.0:
            w *= self.p2.cleared_weight ** n
        return w

    def _apply(self, lv: int) -> None:
        d = self._dirty.get(lv)
        if not d:
            return
        w, wv = self._w[lv], self._wv[lv]
        n, nv = self._nelig.get(lv, 0), self._nver.get(lv, 0)
        for cid in d:
            pos = self._pos[cid]
            c = self.cells[cid]
            new = self.cell_weight(c) if self.eligible(c) else 0.0
            newv = new if getattr(c, "verified", False) else 0.0
            n += int(new > 0) - int(w[pos] > 0)
            nv += int(newv > 0) - int(wv[pos] > 0)
            w[pos], wv[pos] = new, newv
        self._nelig[lv], self._nver[lv] = n, nv
        d.clear()

    def keep(self, key: Sequence[Any], level: int, tick: int, words: bytes, end: Sequence[Any], end_digest: bytes, chain: bytes,
             origin: Mapping[str, Any], n_dispatch: int, *, self_key: Optional[Tuple[Any, ...]] = None, terminal: bool = False) -> Tuple[str, Optional[cs.Cell]]:
        verdict, c = super().keep(key, level, tick, words, end, end_digest, chain, origin, n_dispatch, self_key=self_key, terminal=terminal)
        if c is None or verdict not in (cs.NEW, cs.REPLACED):
            return verdict, c
        if verdict == cs.NEW:
            self._wv.setdefault(c.level, []).append(0.0)
        root = None
        if origin.get("kind") == "burst":
            root = self.root_by_rep.get((int(origin["parent"]), str(origin["parent_digest"])))
        if verdict == cs.NEW:
            self._init_extra(c, inherited=False, verified=True, root=root)
        else:
            if getattr(c, "pending", False):
                self.counts["pending"] -= 1
            c.inherited, c.verified, c.pending, c.cleared, c.root, c.check_attempts = False, True, False, 0, root, 0
        self.root_by_rep[(c.cid, c.digest)] = root
        self.touch(c)
        return verdict, c

    # -- loading run 1 ----------------------------------------------------------------------------------------------------------------------------

    def load_run1(self, R1: Mapping[str, Any], bound_run1: int, cleared: Mapping[int, int], *, reset_novelty: bool) -> Dict[str, Any]:
        """Every final representative of run 1 becomes a cell with the same id (checked against run 1's E7 bound, so cells beyond run 2's bound
        are kept as known keys, ineligible); run 1's own keep logic (crossing_search.Archive.keep) is mirrored here with the words digest built
        in bulk. Zero native ticks."""
        if self.cells:
            raise SearchError("the archive is not empty")
        final, origins, disp = R1["final"], R1["origins"], R1["dispatch_stats"]
        memo: Dict[Tuple[int, str], int] = {}
        cids = sorted(final)
        sample = {cids[0], cids[-1]} | set(cids[::500])
        for i, cid in enumerate(cids):
            r = final[cid]
            words = bytes.fromhex(r["words_hex"])
            k = fa.norm_key(r["key"])
            level, tick = int(r["level"]), int(r["tick"])
            if cid != i:
                raise SearchError(f"run 1 cell ids are not contiguous ({cid} at position {i})")
            if len(words) != tick or mcell.level_of_mask(k[3]) != level or level >= mcell.TARGETS_TOTAL:
                raise SearchError(f"run 1 cell {cid}: words {len(words)} / tick {tick} / level {level} / key level {mcell.level_of_mask(k[3])}")
            if tick > int(bound_run1):
                raise SearchError(f"run 1 cell {cid}: tick {tick} beyond run 1's bound {bound_run1}")
            digest = words_digest_bulk(words)
            if digest != r["digest"] or (cid in sample and mcell.words_digest(words) != digest):
                raise SearchError(f"run 1 cell {cid}: its words do not reproduce its digest")
            if k in self.by_key:
                raise SearchError(f"run 1 cell {cid}: a second cell at key {k}")
            c = cs.Cell(cid=len(self.cells), key=k, level=level, tick=tick, lead=self.lead_of(level, tick), words=words, end=(), end_digest=bytes.fromhex(r["end_digest"]),
                        chain=bytes.fromhex(r["chain"]), digest=digest, origin=dict(r["origin"]), created_at=0)
            if c.lead != int(r["lead"]) or len(c.end_digest) != 32 or len(c.chain) != 32:
                raise SearchError(f"run 1 cell {cid}: its lead or digests do not match its row")
            self.cells.append(c)
            self.by_key[k] = c.cid
            self.by_level.setdefault(level, []).append(c.cid)
            self._pos[c.cid] = len(self.by_level[level]) - 1
            self._w.setdefault(level, []).append(0.0)
            self._wv.setdefault(level, []).append(0.0)
            self.counts["cells"] += 1
            self.words_bytes += tick
            c.first_level_reach = self._note_earliest(c, 0)
            self._init_extra(c, inherited=True, verified=False, root=None)
            c.seen = int(r.get("seen") or 0)
            c.replaced = int(r.get("replaced") or 0)
            st = disp.get(c.digest) or [0, 0]
            c.dispatched = int(st[0])
            c.breaks = int(st[1])
            c.fresh = 0 if reset_novelty else int(st[0])
            c.cleared = int(cleared.get(cid, 0))
            c.root = root_of(origins, cid, c.digest, memo)
            self.root_by_rep[(c.cid, c.digest)] = c.root
            self.touch(c)
        self.inherited = len(self.cells)
        self.counts.update({"inherited": self.inherited, cs.NEW: 0, cs.REPLACED: 0, cs.LATER: 0, cs.SELF: 0, cs.BEYOND: 0, cs.TERMINAL: 0, cs.DEEP: 0})
        for e in self.earliest.values():
            e["inherited"] = True
        self.refresh()
        for lv in list(self.by_level):
            self._apply(lv)
        return {"inherited": self.inherited, "eligible": sum(1 for c in self.cells if self.eligible(c)), "cleared_starts": sum(1 for c in self.cells if c.cleared),
                "roots": len({c.root for c in self.cells}), "per_level": self.per_level2()}

    # -- states ------------------------------------------------------------------------------------------------------------------------------------

    def mark_pending(self, c: cs.Cell) -> None:
        c.pending = True
        self.counts["pending"] += 1
        self.touch(c)

    def mark_verified(self, c: cs.Cell, end: Sequence[Any]) -> None:
        c.end = tuple(end)
        c.verified = True
        if c.pending:
            c.pending = False
            self.counts["pending"] -= 1
        self.counts["checked_ok"] += 1
        self.touch(c)

    def unmark_pending(self, c: cs.Cell) -> None:
        if c.pending:
            c.pending = False
            self.counts["pending"] -= 1
        self.touch(c)

    def quarantine(self, c: cs.Cell, why: str) -> None:
        if getattr(c, "pending", False):
            c.pending = False
            self.counts["pending"] -= 1
        super().quarantine(c, why)

    def mark_cleared(self, c: cs.Cell) -> None:
        c.cleared = getattr(c, "cleared", 0) + 1
        self.touch(c)

    # -- selection: the verified-only draw ----------------------------------------------------------------------------------------------------------

    def levels_present2(self, verified_only: bool) -> List[int]:
        for lv in self.by_level:
            self._apply(lv)
        n = self._nver if verified_only else self._nelig
        return sorted(lv for lv in self.by_level if n.get(lv, 0) > 0)

    def level_weights2(self, verified_only: bool) -> Dict[int, float]:
        levels = self.levels_present2(verified_only)
        if not levels:
            return {}
        top = max(levels)
        return {lv: self.p.level_decay ** (top - lv) for lv in levels}

    def select2(self, rng: random.Random, verified_only: bool) -> Optional[Tuple[cs.Cell, Dict[str, Any]]]:
        """Run 1's draw (a level, then a cell by its weight) over the eligible cells, or over the verified eligible cells only."""
        lw = self.level_weights2(verified_only)
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
        w = (self._wv if verified_only else self._w).get(lv) or []
        cum = list(accumulate(w))
        tot = cum[-1] if cum else 0.0
        if tot <= 0:
            return None
        r2 = rng.random() * tot
        pos = min(bisect_right(cum, r2), len(w) - 1)
        while pos > 0 and w[pos] <= 0:
            pos -= 1
        c = self.cells[self.by_level[lv][pos]]
        return c, {"p_level": round(lw[lv] / total, 5), "w_share": round(w[pos] / tot, 6), "level_eligible": (self._nver if verified_only else self._nelig).get(lv, 0),
                   "levels": {str(k): round(v / total, 4) for k, v in lw.items()}, "verified_only": bool(verified_only)}

    # -- readings -------------------------------------------------------------------------------------------------------------------------------------

    def unverified_eligible(self) -> int:
        return sum(1 for c in self.cells if self.eligible(c) and not c.verified)

    def per_level2(self) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for lv in sorted(self.by_level, reverse=True):
            cs_ = [self.cells[i] for i in self.by_level[lv]]
            el = [c for c in cs_ if self.eligible(c)]
            out[str(lv)] = {"cells": len(cs_), "inherited": sum(1 for c in cs_ if c.inherited), "found_run2": sum(1 for c in cs_ if not c.inherited),
                            "eligible": len(el), "eligible_verified": sum(1 for c in el if c.verified), "eligible_unverified": sum(1 for c in el if not c.verified),
                            "pending": sum(1 for c in cs_ if c.pending), "cleared_starts": sum(1 for c in cs_ if c.cleared), "quarantined": sum(1 for c in cs_ if c.quarantined),
                            "beyond_bound": sum(1 for c in cs_ if c.tick > self.bound), "earliest_tick": min((c.tick for c in cs_), default=None),
                            "eligible_mean_tick": round(sum(c.tick for c in el) / len(el)) if el else None, "dispatches_run1": sum(c.dispatched for c in cs_ if c.inherited)}
        return out

    def ahead_of_pace(self, pace: Mapping[int, int], top: int = 8) -> Dict[str, Dict[str, Any]]:
        """Per deepest live level: the alive cells strictly ahead of the best clear's arrival at that level, by root lineage (run 1 seed)."""
        out: Dict[str, Dict[str, Any]] = {}
        for lv in PACE_LEVELS:
            p = pace.get(lv)
            if p is None:
                continue
            ahead = [c for c in self.cells if c.level == lv and c.alive() and c.tick < p]
            roots: Dict[Any, Dict[str, Any]] = {}
            for c in ahead:
                d = roots.setdefault(c.root, {"root": c.root, "cells": 0, "eligible": 0, "verified": 0, "earliest_tick": None, "dispatches": 0, "breaks": 0, "cleared": 0, "found_run2": 0})
                d["cells"] += 1
                d["eligible"] += int(self.eligible(c))
                d["verified"] += int(bool(c.verified))
                d["earliest_tick"] = c.tick if d["earliest_tick"] is None else min(d["earliest_tick"], c.tick)
                d["dispatches"] += c.dispatched
                d["breaks"] += c.breaks
                d["cleared"] += c.cleared
                d["found_run2"] += int(not c.inherited)
            ranked = sorted(roots.values(), key=lambda d: (-d["cells"], d["earliest_tick"] if d["earliest_tick"] is not None else 10 ** 9))
            out[str(lv)] = {"pace_tick": int(p), "cells_ahead": len(ahead), "eligible_ahead": sum(1 for c in ahead if self.eligible(c)),
                            "verified_ahead": sum(1 for c in ahead if c.verified), "found_run2_ahead": sum(1 for c in ahead if not c.inherited),
                            "earliest_tick": min((c.tick for c in ahead), default=None), "lineages": len(roots), "top": ranked[:top]}
        return out


# -- the plan (zero native ticks) ------------------------------------------------------------------------------------------------------------------


def archive_set_digest(final: Mapping[int, Mapping[str, Any]], best: Mapping[str, Any], bound: int) -> str:
    h = hashlib.sha256()
    for cid in sorted(final):
        r = final[cid]
        h.update(f"{cid}:{r['digest']}:{r['tick']}:{r['level']};".encode())
    h.update(f"best:{best['words_digest']}:{best['completion_input_tick']};bound:{bound}".encode())
    return h.hexdigest()


def throughput_fit2(fit_rows: Sequence[Tuple[float, float]], summary: Mapping[str, Any], config: Mapping[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"jobs": len(fit_rows)}
    f = fm.fit([x for x, _ in fit_rows], [y for _, y in fit_rows]) if len(fit_rows) >= 3 else None
    if f is None:
        return out
    mean_wall = sum(y for _, y in fit_rows) / len(fit_rows)
    out.update({"wall_s_fixed": round(f[0], 3), "wall_s_per_tick": round(f[1], 6), "mean_wall_s": round(mean_wall, 3)})
    n_workers = int(config.get("n_workers") or 0)
    wall = float((summary.get("phase_wall_s") or {}).get("search") or 0.0)
    jobs = int((summary.get("work") or {}).get("jobs") or 0)
    if n_workers and wall > 0 and jobs:
        measured = 3600.0 * jobs / wall
        ideal = n_workers * 3600.0 / mean_wall
        out.update({"run1_workers": n_workers, "run1_jobs_per_h": round(measured, 1), "run1_ideal_jobs_per_h": round(ideal, 1), "efficiency": round(min(1.0, measured / ideal), 4)})
    return out


def projection2(fit: Mapping[str, Any], cfit: Mapping[str, Any], per_level: Mapping[str, Mapping[str, Any]], params: Params2, n_workers: int, hours: float,
                summary1: Mapping[str, Any]) -> Dict[str, Any]:
    """Expected dispatches per hour (run 1's per-job wall fit on the level draw's expected prefix), the lazy-check capacity (run 1's replay fit),
    and the main-process memory at `hours` from run 1's measured growth per new cell."""
    if "wall_s_fixed" not in fit:
        return {"available": False}
    eff = float(fit.get("efficiency") or 0.75)
    levels = sorted((int(lv) for lv, d in per_level.items() if d.get("eligible")), reverse=True)
    if not levels:
        return {"available": False}
    top = levels[0]
    lw = {lv: params.level_decay ** (top - lv) for lv in levels}
    tot = sum(lw.values())
    prefix = sum(lw[lv] / tot * float(per_level[str(lv)]["eligible_mean_tick"] or 0) for lv in levels)
    burst = float((summary1.get("throughput") or {}).get("mean_burst_words") or cs.ARM_BASE["segment_words"])
    tpj = prefix + burst
    wall_job = float(fit["wall_s_fixed"]) + float(fit["wall_s_per_tick"]) * tpj
    rows = []
    for workers in sorted({n_workers, max(1, n_workers - params.check_slots)}, reverse=True):
        jobs_h = eff * workers * 3600.0 / wall_job
        rows.append({"burst_workers": workers, "dispatches_per_h": round(jobs_h), "ticks_per_h": round(jobs_h * tpj), "dispatches_over_wall": round(jobs_h * hours)})
    unverified = sum(int(d.get("eligible_unverified") or 0) for d in per_level.values())
    check_s = check_wall_s(cfit, int(prefix))
    checks_h = params.check_slots * 3600.0 / check_s
    mem1 = summary1.get("memory") or {}
    proj1 = mem1.get("projection") or {}
    peak1 = (mem1.get("peak") or {}).get("main_private_mb")
    per_1k = proj1.get("mb_per_1000_new_cells")
    new_cells_h = float((summary1.get("throughput") or {}).get("new_cells_per_h") or 0.0)
    soft = fm.soft_budget()["main_private"]
    mem = {"run1_main_mb_with_archive": peak1, "run1_mb_per_1000_new_cells": per_1k, "run1_new_cells_per_h": new_cells_h,
           "projected_new_cells": round(new_cells_h * hours), "soft_budget_main_mb": soft}
    if peak1 is not None and per_1k is not None:
        mem["projected_main_mb"] = round(float(peak1) + float(per_1k) * new_cells_h * hours / 1000.0)
        mem["note"] = "run 1's main process held this archive at its end; run 2 starts there (plus per-cell attributes) and grows at run 1's rate; measured at the open"
    return {"available": True, "hours": hours, "efficiency": eff, "expected_prefix_ticks": round(prefix), "expected_burst_words": round(burst), "wall_s_per_job": round(wall_job, 2),
            "rows": rows, "checks": {"unverified_eligible": unverified, "wall_s_per_check": round(check_s, 2), "checks_per_h_capacity": round(checks_h), "slots": params.check_slots},
            "memory": mem, "note": "a projection from run 1's measured fits, not a measurement"}


def build_plan(lab_root: Path, run1_dir: Path, params: Params2, analyse: fv.Analyse = fv.real_analyse) -> Dict[str, Any]:
    """Zero native ticks: the reference, run 1's outputs, the best verified clear and the E7 bound, the archive loaded (eligibility per level,
    cleared starts, lineage roots), the fits and the projection."""
    params.check()
    R, meta = cs.read_reference(lab_root, analyse)
    R1 = read_run1(run1_dir)
    p1 = R1["plan"]
    arrival = {int(k): int(v) for k, v in R["arrival"].items()}
    ref_t = int(R["expected"]["completion_input_tick"])
    if {str(k): v for k, v in arrival.items()} != {str(k): int(v) for k, v in p1["arrival_by_level"].items()}:
        raise SearchError("refused: run 1's arrival ticks per level are not the reference's")
    if p1["route"]["digest"] != R["meta"]["native_action_digest"] or p1.get("archive_id") != meta["archive_id"]:
        raise SearchError("refused: run 1's reference route or archive id is not the import's")
    if int(p1["e7"]["reference_completion_input_tick"]) != ref_t or int(p1["e7"]["margin"]) != cs.MARGIN:
        raise SearchError("refused: run 1's E7 block is not the registered reference and margin")
    best = best_verified_of(R1["verifications"], ref_t)
    bound = s6.record_bound_max_L(best["completion_input_tick"], cs.MARGIN)
    bound_run1 = int(p1["e7"]["bound_max_L"])
    if bound >= bound_run1:
        raise SearchError(f"refused: run 2's bound {bound} is not below run 1's {bound_run1}")
    cleared = cleared_starts_of(R1["verifications"], R1["final"])
    archive = ResumeArchive(meta["archive_id"], arrival, bound, params)
    load = archive.load_run1(R1, bound_run1, cleared, reset_novelty=params.reset_novelty)
    cfit = check_fit(R1["seed_rows"])
    eager = eager_plan(archive, params, cfit)
    fit = throughput_fit2(R1["fit_rows"], R1["summary"], R1["config"])
    digest = archive_set_digest(R1["final"], best, bound)
    s1 = R1["summary"]
    plan = {"mode": "lab", "contract": RUN2_CONTRACT, "utc": g.utc(), "archive_id": meta["archive_id"], "key_family": KEY_FAMILY,
            "rule": "crossing run 2: run 1's final representatives resumed with the same cell ids; E7 bound = run 1's best VERIFIED clear minus the registered "
                    "margin minus one (m8_sd1_select.record_bound_max_L); inherited cells checked natively (run 1's seed check) eagerly for the deepest eligible "
                    f"level(s) and lazily on first draw; cleared starts weighted by cleared_weight per claimed clear; claims replayed only when faster than the best; "
                    f"bursts from the key family {KEY_FAMILY}",
            "run1": {"dir": str(R1["dir"]), "contract": p1["contract"], "utc_start": s1.get("utc_start"), "utc_end": s1.get("utc_end"), "status": s1.get("status"),
                     "lab_code_digest": R1["config"].get("lab_code_digest"), "search_file_sha256": R1["config"].get("search_file_sha256"), "params": p1.get("params"),
                     "seed_set_digest": p1.get("seed_set_digest"), "cells": len(R1["final"]), "cell_rows": R1["rows"], "dispatches": (s1.get("work") or {}).get("dispatches"),
                     "clears_verified": (s1.get("clears") or {}).get("verified"), "e7_bound": bound_run1, "best_verified": {k: best[k] for k in ("n", "cid", "k", "level", "start_tick",
                                                                                                                                       "completion_input_tick", "completion_time_passed", "chain", "words_digest", "utc")}},
            "route": {k: p1["route"][k] for k in ("words", "digest", "completion_input_tick", "completion_time_passed", "final_chain")},
            "arrival_by_level": {str(k): v for k, v in arrival.items()},
            "e7": {"reference_completion_input_tick": ref_t, "run1_best_completion_input_tick": best["completion_input_tick"], "margin": cs.MARGIN, "bound_max_L": bound,
                   "bound_run1": bound_run1, "origin": "the registered rule (m8_sd1_select.record_bound_max_L) on run 1's best VERIFIED clear (run/verifications.jsonl)"},
            "best_pace": {str(k): v for k, v in best["arrival"].items()}, "params": params.as_dict(), "arm": {cs.ARM_NAME: params.arm()}, "arm_base": cs.ARM_BASE,
            "flags_explore": fv.FLAGS_EXPLORE, "flags_verify": fv.FLAGS_VERIFY,
            "archive": {"inherited": load["inherited"], "eligible": load["eligible"], "cleared_starts": load["cleared_starts"], "roots": load["roots"], "per_level": load["per_level"],
                        "cleared_starts_rows": sum(cleared.values()), "ahead_of_pace": archive.ahead_of_pace(best["arrival"])},
            "eager": eager, "check_fit": cfit, "throughput_fit": fit, "archive_set_digest": digest, "seed_set_digest": digest, "seeds": 0, "seed_ticks": 0, "frontier": None}
    return {"plan": plan, "seeds": [], "R": R, "meta": meta, "bound": bound, "bound_run1": bound_run1, "best": best, "R1": R1, "archive": archive, "cleared": cleared}


def eager_plan(archive: ResumeArchive, params: Params2, cfit: Mapping[str, Any]) -> Dict[str, Any]:
    """The cells checked at the open: the eligible unverified cells of the deepest `eager_levels` eligible levels (earliest first) and the
    `canary_per_level` earliest eligible unverified cells of every level, within the wall budget at seed_parallel replays."""
    levels = archive.levels_present2(False)
    deep = set(levels[-params.eager_levels:]) if params.eager_levels > 0 else set()
    canaries: List[cs.Cell] = []
    rest: List[cs.Cell] = []
    for lv in levels:
        cells = sorted((archive.cells[i] for i in archive.by_level[lv] if archive.eligible(archive.cells[i]) and not archive.cells[i].verified), key=lambda c: (c.tick, c.cid))
        canaries += cells[:params.canary_per_level]
        if lv in deep:
            rest += cells[params.canary_per_level:]
    order = sorted(canaries, key=lambda c: (-c.level, c.tick, c.cid)) + sorted(rest, key=lambda c: (-c.level, c.tick, c.cid))
    parallel = max(1, cs.SearchConfig.seed_parallel)
    budget = 60.0 * params.eager_max_min
    kept: List[cs.Cell] = []
    est = 0.0
    truncated = 0
    for c in order:                                                     # the canaries first, then the deep levels earliest first, within the budget
        w = check_wall_s(cfit, c.tick)
        if kept and (est + w) / parallel > budget:
            truncated += 1
            continue
        kept.append(c)
        est += w
    return {"levels_deep": sorted(deep), "canary_per_level": params.canary_per_level, "cells": len(kept), "ticks": sum(c.tick for c in kept), "truncated": truncated,
            "estimated_wall_min": round(est / parallel / 60.0, 1), "budget_min": params.eager_max_min, "parallel": parallel,
            "per_level": {str(lv): sum(1 for c in kept if c.level == lv) for lv in sorted({c.level for c in kept}, reverse=True)}, "cids": [c.cid for c in kept]}


# -- the engine -----------------------------------------------------------------------------------------------------------------------------------


class ResumeSearch(cs.Search):
    def __init__(self, cfg: cs.SearchConfig, env: fr.LabEnv, P: Mapping[str, Any], params: Params2):
        super().__init__(cfg, env, P, params)
        self.p2 = params
        self.archive: ResumeArchive = P["archive"]
        self.R1 = P["R1"]
        self.bound_run1 = int(P["bound_run1"])
        self.best: Dict[str, Any] = dict(P["best"])
        self.best_run1 = dict(P["best"])
        self.best_history: List[Dict[str, Any]] = []
        self.check_queue: Deque[Dict[str, Any]] = deque()
        self.ready: Deque[Tuple[int, str, Dict[str, Any]]] = deque()
        self.slots: Dict[int, Dict[str, Any]] = {}
        self.lent_set: Set[int] = set()
        self.verify_inflight = False
        self.not_replayed: List[Dict[str, Any]] = []
        self.not_replayed_clocks: Dict[str, int] = {}
        self.check_rows: List[Dict[str, Any]] = []
        self.anchor: Dict[str, Any] = {}
        self.eager: Dict[str, Any] = {}
        self.clf = mcell.Classifier()
        self.c.update({"check_ticks": 0, "anchor_ticks": 0, "checks_eager": 0, "checks_lazy": 0, "checks_ok": 0, "checks_quarantined": 0, "checks_error": 0,
                       "checks_stale": 0, "claims_not_replayed": 0, "ready_dropped": 0, "draws_unverified": 0, "verified_only_draws": 0, "worker_waits": 0})

    # -- readings ---------------------------------------------------------------------------------------------------------------------------------

    def used_ticks(self) -> int:
        return super().used_ticks() + self.c["check_ticks"] + self.c["anchor_ticks"]

    def should_replay(self, cand: Mapping[str, Any]) -> bool:
        claimed = cand["claim"].get("completion_input_tick")
        t = int(claimed) if claimed is not None else len(cand["words"])
        return t < int(self.best["completion_input_tick"])

    def replayable(self) -> List[Dict[str, Any]]:
        return [c for c in self.vqueue if self.should_replay(c)]

    def verify_ticks_pending(self) -> int:
        n = 2 * sum(len(c["words"]) for c in self.replayable())
        n += sum(len(it["words"]) for it in self.check_queue)
        for box in self.slots.values():
            n += (2 * len(box["cand"]["words"])) if box["kind"] == "verify" else len(box["item"]["words"])
        return n

    def dispatch_deadline(self) -> float:
        cfg = self.cfg
        pending = len(self.replayable()) + (1 if self.verify_inflight else 0)
        reserve = cfg.stop_grace_s + cfg.write_reserve_s + max(cfg.verify_floor_s, cfg.verify_s_per_clear * (-(-pending // cfg.verify_parallel)))
        return self.t0 + cfg.max_wall_s - reserve

    # -- open -------------------------------------------------------------------------------------------------------------------------------------------

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
        if not self.archive.cells:
            raise Refused("no cell: run 1's archive is empty")
        self.code = env.code_manifest()
        self.code_dig = fr.code_digest(self.code)
        if cfg.expect_code and self.code_dig != cfg.expect_code:
            raise Refused(f"lab code digest {self.code_dig[:16]} differs from run 1's {cfg.expect_code[:16]}")
        self.fs.mkdir(self.dir)
        self.fs.write_json(self.dir / "config.json", self.config_record(ready))
        self.sampler = fm.Sampler(lambda r: self.fs.append_jsonl(self.dir / "memory.jsonl", r), interval=env.sample_s, row_every=env.row_every_s,
                                  caps=env.caps or fm.CAPS_MB, soft=env.soft, snapshot=env.snapshot, now=env.now,
                                  extra=lambda: {"cells": len(self.archive.cells), "phase": self.phase, "dispatches": self.c["dispatches"], "jobs": self.c["jobs"],
                                                 "words_mb": round(self.archive.words_bytes / 2 ** 20, 1), "pending_checks": len(self.check_queue)}).start()
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
        self.log(f"reference clear replayed exactly: {row['completion_input_tick']} / {row['completion_time_passed']} in {row.get('stepping_s')} s")
        self.phase = "anchor"
        self.anchor_phase()
        if self.stopping:
            return
        self.phase = "seed"
        self.eager_phase()
        if self.stopping:
            return
        if not self.archive.levels_present2(False):
            self.mark("SEARCH_INCOMPLETE", "no eligible cell after the open")
            return
        self.pool = fr.FrsPool(env.worker_spec, env.now)
        self.pool.start(cfg.n_workers)
        self.phase_wall["open"] = round(env.now() - self.t0, 1)
        pl = self.archive.per_level2()
        self.log(f"open done in {self.phase_wall['open']:.0f} s; {cfg.n_workers} workers ready; {self.archive.inherited:,} inherited cells, eligible per level "
                 f"{json.dumps({lv: d['eligible'] for lv, d in pl.items()})}, verified {json.dumps({lv: d['eligible_verified'] for lv, d in pl.items()})}; E7 bound {self.bound} "
                 f"(run 1's best {self.best['completion_input_tick']}); params {self.p.as_dict()}; arm {cs.ARM_NAME} {self.arm}")
        self.write_progress()

    def anchor_phase(self) -> None:
        """Run 1's best verified clear replayed once from tick 0 in a fresh process with the verify flags: it must reproduce exactly."""
        env = self.env
        b = self.best
        words = bytes(b["words"])
        t = env.now()
        tr, errors = fv.replay_with_retry(env.replay, words, "run1_best", 0)
        row = fv.evaluate(tr, words, env.analyse)
        fv.save_trace(self.dir / "traces" / "run1_best.json.gz", tr)
        self.c["anchor_ticks"] += int(row.get("ticks") or 0)
        differs = [k for k, want in (("outcome", "clear"), ("completion_input_tick", b["completion_input_tick"]), ("completion_time_passed", b["completion_time_passed"]),
                                     ("final_chain", b["chain"]), ("action_digest", b["words_digest"]), ("breaks", b["breaks"]), ("ticks", len(words)))
                   if row.get(k) != want] + ([] if row.get("ticks_ok") else ["ticks_ok"])
        self.anchor = {"ok": not differs and row.get("outcome") == "clear", "differs": differs, "errors": errors, "completion_input_tick": row.get("completion_input_tick"),
                       "completion_time_passed": row.get("completion_time_passed"), "final_chain": row.get("final_chain"), "ticks": row.get("ticks"), "startup_s": row.get("startup_s"),
                       "stepping_s": row.get("stepping_s"), "wall_s": round(env.now() - t, 2), "run1_dispatch": b["n"], "run1_cid": b["cid"], "run1_k": b["k"], "words_digest": b["words_digest"]}
        self.fs.write_json(self.dir / "run1_best.json", self.anchor)
        if not self.anchor["ok"]:
            if row.get("outcome") == "error":
                self.mark("SEARCH_INCOMPLETE", f"run 1's best verified clear could not be replayed: {errors[:2]}")
            else:
                self.mark("SEARCH_INVALID", f"run 1's best verified clear did not replay exactly: {differs}")
            return
        self.log(f"run 1's best verified clear replayed exactly: {row['completion_input_tick']} / {row['completion_time_passed']} (chain {str(row['final_chain'])[:16]}); "
                 f"E7 bound {self.bound} = {b['completion_input_tick']} - {cs.MARGIN} - 1")

    # -- checks of inherited cells (fresh-process replays, run 1's seed check) -------------------------------------------------------------------

    def check_item(self, c: cs.Cell, draw: Optional[Mapping[str, Any]], kind: str) -> Dict[str, Any]:
        assert c.words is not None
        return {"kind": kind, "cid": c.cid, "digest": c.digest, "tick": c.tick, "level": c.level, "lead": c.lead, "words": bytes(c.words), "chain": c.chain.hex(),
                "end_digest": c.end_digest.hex(), "key": list(c.key), "draw": dict(draw) if draw else None, "n": self.c["dispatches"]}

    def run_check(self, item: Mapping[str, Any], slot: int) -> Dict[str, Any]:
        t = self.env.now()
        try:
            tr, errors = fv.replay_with_retry(self.env.replay, item["words"], f"check_c{item['cid']}", slot)
            out = cs.seed_check(tr, item["words"], item, self.env.analyse, self.clf)
            out["errors"] = errors
            if not out.get("ok") and tr is not None:
                fv.save_trace(self.dir / "traces" / f"check_fail_c{item['cid']}_{g.utc_compact()}.json.gz", tr)
        except Exception as exc:  # noqa: BLE001 - a crashed check is an error row, never a verified cell
            out = {"ok": False, "why": "the replay did not run", "error": f"{type(exc).__name__}: {exc}"[:300], "ticks": 0}
        out["wall_s"] = round(self.env.now() - t, 2)
        return out

    def on_check_done(self, item: Mapping[str, Any], out: Mapping[str, Any]) -> None:
        c = self.archive.cells[int(item["cid"])]
        self.c["check_ticks"] += int(out.get("ticks") or 0)
        self.c["checks_eager" if item["kind"] == "eager" else "checks_lazy"] += 1
        row = {"kind": item["kind"], "cid": c.cid, "digest": item["digest"], "level": item["level"], "tick": item["tick"], "lead": item["lead"], "ok": bool(out.get("ok")),
               "why": out.get("why"), "ticks": out.get("ticks"), "ticks_ok": out.get("ticks_ok"), "chain_equal": out.get("chain_equal"), "end_digest_equal": out.get("end_digest_equal"),
               "key_equal": out.get("key_equal"), "level_equal": out.get("level_equal"), "errors": out.get("errors"), "wall_s": out.get("wall_s"), "startup_s": out.get("startup_s"),
               "stepping_s": out.get("stepping_s"), "n": self.c["dispatches"], "utc": g.utc()}
        if c.digest != item["digest"]:
            row["stale"] = True
            self.c["checks_stale"] += 1
            self.fs.append_jsonl(self.dir / "checks.jsonl", row)
            return
        if out.get("ok"):
            self.archive.mark_verified(c, out["end"])
            self.c["checks_ok"] += 1
            if item["draw"] is not None and self.archive.dispatchable(c):
                self.ready.append((c.cid, c.digest, dict(item["draw"])))
        elif out.get("why") == "the replay did not run":
            self.c["checks_error"] += 1
            c.check_attempts += 1
            self.archive.unmark_pending(c)
            if c.check_attempts >= 2:
                c.retired = f"check: the replay did not run twice ({out.get('error') or out.get('errors')})"[:200]
                self.archive.words_bytes -= len(c.words or b"")
                c.words = None
                self.archive.counts["retired"] += 1
                self.archive.touch(c)
            self.log(f"check of cell {c.cid} (level {c.level}, tick {c.tick}) could not run: {out.get('error') or out.get('errors')}")
        else:
            self.c["checks_quarantined"] += 1
            self.c["mismatches"] += 1
            self.archive.quarantine(c, f"check: {out.get('why')}")
            self.event(f"cell {c.cid} (level {c.level}, tick {c.tick}) quarantined: its prefix did not reproduce run 1's record ({out.get('why')})")
            if self.c["mismatches"] > self.cfg.mismatch_limit:
                self.mark("SEARCH_INVALID", f"{self.c['mismatches']} quarantines > {self.cfg.mismatch_limit}", abort=True)
        self.check_rows.append({k: row[k] for k in ("kind", "cid", "level", "tick", "ok", "why")})
        self.fs.append_jsonl(self.dir / "checks.jsonl", row)

    def eager_phase(self) -> None:
        """The eager checks at the open (up to seed_parallel fresh processes at once, before any worker is started)."""
        cfg, env = self.cfg, self.env
        t = env.now()
        plan = self.plan["eager"]
        items = [self.check_item(self.archive.cells[cid], None, "eager") for cid in plan["cids"] if self.archive.cells[cid].alive() and not self.archive.cells[cid].verified]
        lock = threading.Lock()
        queue = list(items)
        results: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []

        def worker(slot: int) -> None:
            while True:
                with lock:
                    if not queue or self.stopping:
                        return
                    it = queue.pop(0)
                out = self.run_check(it, slot)
                with lock:
                    results.append((it, out))

        n = max(1, min(cfg.seed_parallel, len(queue)))
        ths = [threading.Thread(target=worker, args=(i,), daemon=True, name=f"crossing2-eager-{i}") for i in range(n)] if queue else []
        for th in ths:
            th.start()
        for th in ths:
            th.join()
        for it, out in results:
            self.on_check_done(it, out)
            if self.stopping:
                break
        self.eager = {"planned": len(items), "done": len(results), "ok": sum(1 for _it, o in results if o.get("ok")), "quarantined": sum(1 for _it, o in results if not o.get("ok") and o.get("why") != "the replay did not run"),
                      "errors": sum(1 for _it, o in results if o.get("why") == "the replay did not run"), "ticks": sum(int(o.get("ticks") or 0) for _it, o in results),
                      "wall_s": round(env.now() - t, 1), "levels": plan["levels_deep"], "per_level": plan["per_level"], "estimated_wall_min": plan["estimated_wall_min"]}
        self.seed_stats = {"seeds": len(items), "ok": self.eager["ok"], "dropped": self.eager["quarantined"] + self.eager["errors"], "reasons": {}, "ticks": self.eager["ticks"],
                           "wall_s": self.eager["wall_s"], "kind": "eager checks of inherited cells"}
        self.phase_wall["seed"] = self.eager["wall_s"]
        self.log(f"eager checks done in {self.eager['wall_s']:.0f} s: {self.eager['ok']} of {len(items)} reproduced ({self.eager['quarantined']} quarantined, {self.eager['errors']} errors), "
                 f"{self.eager['ticks']:,} ticks")

    # -- the search loop with lent workers -----------------------------------------------------------------------------------------------------------

    def search_phase(self) -> None:
        self.t_search = self.env.now()
        self.phase = "search"
        pool = self.pool
        assert pool is not None
        while not self.stopping:
            for w, kind, payload in pool.poll2(0.2, self.on_boundary):
                self.handle(w, kind, payload)
            self.checks()
            self.service_slots()
            if self.stopping:
                break
            for w in pool.idle():
                if w in self.lent_set or self.stopping:
                    continue
                job = self.next_job(w)
                if job is None:
                    break
                pool.send(w, job)
            self.progress()
        self.search_wall = self.env.now() - self.t_search
        self.drain()

    def checks(self) -> None:
        super().checks()
        if not self.stopping and self.c["checks_error"] > self.p2.check_error_limit:
            self.mark("SEARCH_INCOMPLETE", f"{self.c['checks_error']} checks could not run > {self.p2.check_error_limit}", abort=True)

    def next_slot_work(self) -> Optional[Tuple[str, Dict[str, Any]]]:
        if not self.verify_inflight:
            while self.vqueue:
                cand = self.vqueue[0]
                if self.should_replay(cand):
                    return "verify", self.vqueue.pop(0)
                self.record_not_replayed(self.vqueue.pop(0), "slower than or equal to the best verified clear at decision")
        if self.check_queue:
            return "check", self.check_queue.popleft()
        return None

    def service_slots(self) -> None:
        for w, box in list(self.slots.items()):
            if box["thread"].is_alive():
                continue
            del self.slots[w]
            self.lent_set.discard(w)
            if box["kind"] == "verify":
                self.verify_inflight = False
                self.on_verified(box["cand"], box["out"])
            else:
                self.on_check_done(box["item"], box["out"])
        if self.stopping or self.pool is None:
            return
        while len(self.slots) < self.p2.check_slots:
            idle = [w for w in self.pool.idle() if w not in self.lent_set]
            if not idle:
                return
            work = self.next_slot_work()
            if work is None:
                return
            self.start_slot(idle[0], work)

    def start_slot(self, w: int, work: Tuple[str, Dict[str, Any]]) -> None:
        kind, payload = work
        box: Dict[str, Any] = {"kind": kind, "t0": self.env.now()}
        if kind == "verify":
            box["cand"] = payload
            self.verify_inflight = True

            def run_v() -> None:
                box["out"] = self.verify_candidate(payload, w)
            target = run_v
        else:
            box["item"] = payload

            def run_c() -> None:
                box["out"] = self.run_check(payload, w)
            target = run_c
        box["thread"] = threading.Thread(target=target, name=f"crossing2-slot-{w}", daemon=True)
        self.lent_set.add(w)
        self.slots[w] = box
        box["thread"].start()

    def record_not_replayed(self, cand: Mapping[str, Any], why: str) -> None:
        claimed = cand["claim"].get("completion_input_tick")
        row = {"mode": "lab", "kind": "claim", "verdict": NOT_REPLAYED, "why": why, "n": cand["n"], "cid": cand["cid"], "k": cand["k"], "level": cand["level"], "start_tick": cand["start_tick"],
               "lead": cand["lead"], "claimed_completion_input_tick": claimed, "claimed_completion_time_passed": cand["claim"].get("completion_time_passed"), "words": len(cand["words"]),
               "words_digest": cand["claim"]["words_digest"], "chain_claimed": cand["claim"].get("chain"), "best_at_decision": self.best["completion_input_tick"],
               "reference_completion_input_tick": self.ref_t, "utc": g.utc(), "words_hex": bytes(cand["words"]).hex()}
        self.c["claims_not_replayed"] += 1
        key = str(claimed if claimed is not None else len(cand["words"]))
        self.not_replayed_clocks[key] = self.not_replayed_clocks.get(key, 0) + 1
        self.not_replayed.append({k: row[k] for k in ("n", "cid", "k", "level", "start_tick", "claimed_completion_input_tick", "words_digest", "best_at_decision", "utc")})
        self.fs.append_jsonl(self.dir / "claims_not_replayed.jsonl", row)

    # -- dispatch -----------------------------------------------------------------------------------------------------------------------------------------

    def build_job(self, w: int, c: cs.Cell, draw: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        cfg = self.cfg
        assert c.words is not None and c.verified and len(c.end) == len(mcell.OBS_FIELDS)
        max_words = self.arm["segment_words"] * self.arm["max_segments"]
        want = c.tick + min(max_words, mcell.HORIZON - c.tick)
        if self.used_ticks() + self.reserved + want + self.verify_ticks_pending() > cfg.max_ticks:
            self.mark("TICK_CAP", f"the tick cap {cfg.max_ticks:,} would be exceeded by the next dispatch")
            return None
        k = c.next_k
        c.next_k += 1
        draw_id = f"{self.archive.archive_id}|{KEY_FAMILY}|{c.digest}"
        job = {"kind": fw.JOB_KIND, "iteration": k, "cell": c.cid, "rep": (c.cid, c.tick), "words": bytes(c.words), "end": tuple(c.end), "end_digest": bytes(c.end_digest),
               "chain": bytes(c.chain), "terminal": False, "pin": self.pin, "archive_id": draw_id, "allowance": int(want), **self.arm}
        self.c["dispatches"] += 1
        self.inflight[w] = {"n": self.c["dispatches"], "cid": c.cid, "k": k, "level": c.level, "tick": c.tick, "lead": c.lead, "draw_id": draw_id, "draw": dict(draw),
                            "fresh": c.fresh, "seen": c.seen, "breaks": c.breaks, "digest": c.digest, "words": bytes(c.words), "reserved": int(want), "cont": [],
                            "root": c.root, "inherited": c.inherited, "cleared": c.cleared}
        self.reserved += int(want)
        return job

    def next_job(self, w: int) -> Optional[Dict[str, Any]]:
        tries = 0
        while True:
            while self.ready:
                cid, digest, draw = self.ready.popleft()
                c = self.archive.cells[cid]
                if c.digest != digest or not self.archive.dispatchable(c):
                    self.c["ready_dropped"] += 1
                    continue
                return self.build_job(w, c, draw)
            verified_only = len(self.check_queue) >= self.p2.check_queue_max
            pick = self.archive.select2(self.rng, verified_only)
            if pick is None:
                if verified_only or self.check_queue or any(b["kind"] == "check" for b in self.slots.values()) or self.archive.unverified_eligible():
                    self.c["worker_waits"] += 1
                    return None
                self.mark("ARCHIVE_EMPTY", "no eligible cell is left to dispatch from")
                return None
            c, draw = pick
            self.c["verified_only_draws"] += int(verified_only)
            if c.verified:
                return self.build_job(w, c, draw)
            self.c["draws_unverified"] += 1
            self.archive.mark_pending(c)
            self.check_queue.append(self.check_item(c, draw, "lazy"))
            tries += 1
            if tries >= CHECK_LIMIT_TRIES:
                self.c["worker_waits"] += 1
                return None

    def commit(self, info: Mapping[str, Any], c: cs.Cell, res: Mapping[str, Any]) -> None:
        super().commit(info, c, res)
        n = len(res["words"])
        if cs.END_NAMES.get(str(res["end_reason"]), str(res["end_reason"])) == "clear" and n > 0 and c.digest == info["digest"]:
            self.archive.mark_cleared(c)

    # -- verification: only claims faster than the best ----------------------------------------------------------------------------------------------------

    def set_best(self, row: Mapping[str, Any]) -> None:
        breaks = sorted((int(t), int(i)) for t, i in (row.get("breaks_r1") or []))
        arrival = {0: 0, **{lv: t for lv, t in cs.level_arrivals(0, breaks)}}
        prev = self.best
        self.best = {"n": row["n"], "cid": row["cid"], "k": row["k"], "level": row["level"], "start_tick": row["start_tick"], "completion_input_tick": int(row["completion_input_tick"]),
                     "completion_time_passed": int(row["completion_time_passed"]), "chain": row["chain_r1"], "words_digest": row["words_digest"], "breaks": [list(b) for b in breaks],
                     "arrival": arrival, "source": "run2", "utc": row.get("utc"), "words": None}
        self.best_history.append({"completion_input_tick": self.best["completion_input_tick"], "completion_time_passed": self.best["completion_time_passed"], "n": row["n"], "cid": row["cid"],
                                  "k": row["k"], "start_tick": row["start_tick"], "level": row["level"], "chain": row["chain_r1"], "words_digest": row["words_digest"], "utc": row.get("utc"),
                                  "previous_best": prev["completion_input_tick"], "gain": prev["completion_input_tick"] - self.best["completion_input_tick"], "elapsed_s": round(self.elapsed(), 1)})

    def on_verified(self, cand: Mapping[str, Any], out: Mapping[str, Any]) -> None:
        super().on_verified(cand, out)
        row = self.vrows[-1]
        row["gain_vs_run1_best"] = (self.best_run1["completion_input_tick"] - int(row["completion_input_tick"])) if row["verdict"] == fv.VERIFIED and row.get("completion_input_tick") is not None else None
        if row["verdict"] == fv.VERIFIED and int(row["completion_input_tick"]) < int(self.best["completion_input_tick"]):
            self.set_best(row)
            self.event(f"NEW BEST verified clear: {self.best['completion_input_tick']} / {self.best['completion_time_passed']} (run 1's best {self.best_run1['completion_input_tick']}, "
                       f"reference {self.ref_t}) from dispatch {row['n']} cell {row['cid']} k {row['k']}; pace {json.dumps({str(k): v for k, v in self.best['arrival'].items() if k in PACE_LEVELS})}")
            keep = []
            for cnd in self.vqueue:
                if self.should_replay(cnd):
                    keep.append(cnd)
                else:
                    self.record_not_replayed(cnd, "a faster clear was verified while it was queued")
            self.vqueue = keep
        self.write_progress()

    # -- close -----------------------------------------------------------------------------------------------------------------------------------------------

    def close(self) -> None:
        deadline = self.env.now() + 120.0
        for w, box in list(self.slots.items()):
            box["thread"].join(timeout=max(1.0, deadline - self.env.now()))
            if box["thread"].is_alive():
                if box["kind"] == "verify":
                    self.unverified.append({"n": box["cand"]["n"], "cid": box["cand"]["cid"], "k": box["cand"]["k"], "words": len(box["cand"]["words"]), "why": "the in-run verification did not return"})
                continue
            del self.slots[w]
            if box["kind"] == "verify":
                self.verify_inflight = False
                self.on_verified(box["cand"], box["out"])
            else:
                self.on_check_done(box["item"], box["out"])
        self.lent_set.clear()
        keep = []
        for cnd in self.vqueue:
            if self.should_replay(cnd):
                keep.append(cnd)
            else:
                self.record_not_replayed(cnd, "slower than or equal to the best verified clear at the close")
        self.vqueue = keep
        for it in self.check_queue:
            self.archive.unmark_pending(self.archive.cells[int(it["cid"])])
        self.check_queue.clear()
        super().close()

    # -- records ----------------------------------------------------------------------------------------------------------------------------------------------

    def config_record(self, ready: Mapping[str, Any]) -> Dict[str, Any]:
        c, p = self.cfg, self.plan
        return {"mode": "lab", "contract": RUN2_CONTRACT, "utc": g.utc(), "search_file_sha256": g.sha256_file(Path(__file__).resolve()), "run1_search_file_sha256": g.sha256_file(Path(cs.__file__).resolve()),
                "lab_code_digest": self.code_dig, "lab_code_files": len(self.code), "expect_code": c.expect_code, "arm": cs.ARM_NAME, "arm_params": self.arm, "arm_base": cs.ARM_BASE,
                "params": self.p.as_dict(), "key_family": KEY_FAMILY, "n_workers": c.n_workers, "max_ticks": c.max_ticks, "max_wall_s": c.max_wall_s, "job_timeout_s": c.job_timeout_s,
                "mismatch_limit": c.mismatch_limit, "lifecycle_limit": c.lifecycle_limit, "verify_parallel_close": c.verify_parallel, "seed_parallel": c.seed_parallel,
                "max_battleship_processes": fm.MAX_BATTLESHIP, "memory_caps_mb": dict(self.env.caps or fm.CAPS_MB), "memory_soft_budget_mb": dict(self.env.soft or fm.soft_budget(self.env.caps or fm.CAPS_MB)),
                "readiness": ready, "flags_explore": fv.FLAGS_EXPLORE, "flags_verify": fv.FLAGS_VERIFY, "backend": self.env.backend, "import": str(Path(c.lab_root) / "import"),
                "run1": p["run1"], "archive_set_digest": p["archive_set_digest"], "reference": p["route"], "e7": p["e7"], "best_pace": p["best_pace"], "archive_at_plan": p["archive"],
                "eager": p["eager"],
                "origins": {"arm": "the lab's CONT arm (rl/frs_run.ARMS) with max_segments as an argument (run 1)", "archive": "run 1's run/cells.jsonl: the final representative per cell id",
                            "end_records": "not on disk: recovered by a fresh-process verify-flag replay of the prefix (run 1's seed check), eagerly or lazily before the first burst",
                            "draw_id": f"<archive id>|{KEY_FAMILY}|<prefix words digest>, iteration k = 0.. per representative (a new family: no run 1 burst is repeated)",
                            "selection": "run 1's level draw and (1+fresh)^-nov (1+seen)^-seen (1+breaks)^bonus slack^pace, times cleared_weight^clears (this file)",
                            "e7": "the registered rule on run 1's best VERIFIED clear and the registered margin (never lowered)",
                            "verification": "a claim is replayed (twice, fresh processes, verify flags) only when faster than the best verified clear so far",
                            "caps": f"owner, 2026-10-15: at most {c.max_wall_s / 60.0:g} minutes, {c.max_ticks:,} ticks, {self.p.max_cells:,} cells, 10 game processes",
                            "readiness": "registered thresholds, never lowered", "rng": "Python experiment seed (the draws)"}}

    def summary(self) -> Dict[str, Any]:
        s = super().summary()
        s["contract"] = RUN2_CONTRACT
        s["config"].pop("frontier", None)
        s["config"]["key_family"] = KEY_FAMILY
        s["config"]["run1"] = self.plan["run1"]
        verified = self.verified_clears()
        faster = [v for v in verified if int(v["completion_input_tick"]) < int(self.best_run1["completion_input_tick"])]
        s["run2"] = {"best": {k: v for k, v in self.best.items() if k != "words"}, "best_run1": {k: v for k, v in self.best_run1.items() if k != "words"}, "best_history": list(self.best_history),
                     "faster_than_run1": len(faster), "gain_vs_run1_best": (self.best_run1["completion_input_tick"] - self.best["completion_input_tick"]) if faster else 0,
                     "reference_completion_input_tick": self.ref_t, "e7": self.plan["e7"], "anchor": self.anchor, "eager": self.eager,
                     "checks": {k: self.c[k] for k in ("checks_eager", "checks_lazy", "checks_ok", "checks_quarantined", "checks_error", "checks_stale", "check_ticks")},
                     "check_queue": len(self.check_queue), "ready": len(self.ready), "lent": sorted(self.lent_set), "pending": self.archive.counts.get("pending", 0),
                     "claims": {"claimed": self.c["clears_claimed"], "replayed": len(self.vrows), "not_replayed": self.c["claims_not_replayed"],
                                "not_replayed_clocks": dict(sorted(self.not_replayed_clocks.items(), key=lambda kv: int(kv[0]))), "last_not_replayed": self.not_replayed[-12:]},
                     "cleared_starts": sum(1 for c in self.archive.cells if c.cleared), "inherited": self.archive.inherited, "per_level": self.archive.per_level2(),
                     "ahead_of_pace": self.archive.ahead_of_pace(self.best["arrival"]), "draws": {k: self.c[k] for k in ("draws_unverified", "verified_only_draws", "worker_waits", "ready_dropped")}}
        return s

    def write_summary(self) -> Dict[str, Any]:
        if self.sampler is not None:
            self.sampler.stop()
        s = self.summary()
        self.fs.write_text(self.dir / "summary.json", frep.compact_json(s), atomic=True)
        self.fs.write_text(self.dir / "report.md", report_md2(s), atomic=True)
        self.fs.write_text(self.dir / "progress.md", progress_md2(s, final=True), atomic=True)
        return s

    def write_progress(self) -> None:
        try:
            self.fs.write_text(self.dir / "progress.md", progress_md2(self.summary(), final=False), atomic=True)
        except (OSError, g.LabRootError):
            pass


# -- rendering ----------------------------------------------------------------------------------------------------------------------------------------


def _best_lines(s: Mapping[str, Any]) -> List[str]:
    r2 = s["run2"]
    b, b1 = r2["best"], r2["best_run1"]
    ref = r2["reference_completion_input_tick"]
    lines = [f"Best verified clear so far: **{frep.fmt(b['completion_input_tick'])} / {frep.fmt(b['completion_time_passed'])}** ({'run 2, dispatch ' + str(b['n']) + ', cell ' + str(b['cid']) + ', k ' + str(b['k']) if b.get('source') == 'run2' else 'run 1, dispatch ' + str(b['n']) + ', cell ' + str(b['cid'])}; "
             f"chain `{str(b['chain'])[:16]}…`). Against run 1's best {frep.fmt(b1['completion_input_tick'])}: "
             f"{'FASTER by ' + str(b1['completion_input_tick'] - b['completion_input_tick']) + ' ticks' if b['completion_input_tick'] < b1['completion_input_tick'] else 'no faster clear verified yet'}. "
             f"Against the reference {frep.fmt(ref)}: faster by {frep.fmt(ref - b['completion_input_tick'])} ticks. Run 2 clears verified faster than run 1's best: {r2['faster_than_run1']}.",
             f"Pace of the best clear (arrival tick per level): {json.dumps({k: v for k, v in b['arrival'].items()})}. E7 bound {frep.fmt(r2['e7']['bound_max_L'])} "
             f"(= run 1's best {frep.fmt(r2['e7']['run1_best_completion_input_tick'])} - {r2['e7']['margin']} - 1; run 1's bound was {frep.fmt(r2['e7']['bound_run1'])})."]
    if r2["best_history"]:
        lines += ["", "| new best | previous | gain | dispatch, cell, k | start tick | level | chain | utc | elapsed |", "|---|---|---|---|---|---|---|---|---|"]
        for h in r2["best_history"]:
            lines.append(f"| {frep.fmt(h['completion_input_tick'])} / {frep.fmt(h['completion_time_passed'])} | {frep.fmt(h['previous_best'])} | {h['gain']} | {h['n']}, {h['cid']}, {h['k']} | {frep.fmt(h['start_tick'])} | "
                         f"{h['level']} | `{str(h['chain'])[:16]}…` | {h['utc']} | {frep.fmt(h['elapsed_s'] / 60.0, 0)} min |")
    return lines


def _pace_lines(s: Mapping[str, Any]) -> List[str]:
    r2 = s["run2"]
    lines = ["| level | best clear's arrival | cells ahead | eligible | verified | found by run 2 | earliest tick | lineages (root seed: cells, earliest, dispatches, breaks, cleared, run 2 cells) |",
             "|---|---|---|---|---|---|---|---|"]
    for lv, d in sorted(r2["ahead_of_pace"].items(), key=lambda kv: -int(kv[0])):
        tops = "; ".join(f"{t['root']}: {t['cells']}, {frep.fmt(t['earliest_tick'])}, {t['dispatches']}, {t['breaks']}, {t['cleared']}, {t['found_run2']}" for t in d["top"])
        lines.append(f"| {lv} | {frep.fmt(d['pace_tick'])} | {frep.fmt(d['cells_ahead'])} | {frep.fmt(d['eligible_ahead'])} | {frep.fmt(d['verified_ahead'])} | {frep.fmt(d['found_run2_ahead'])} | "
                     f"{frep.fmt(d['earliest_tick'])} | {d['lineages']} lineages: {tops} |")
    return lines


def _level2_lines(s: Mapping[str, Any]) -> List[str]:
    lines = ["| level | cells | inherited | found by run 2 | eligible | verified | unverified | pending | cleared starts | quarantined | beyond the bound | earliest tick | eligible mean tick | run 1 dispatches |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for lv, d in s["run2"]["per_level"].items():
        lines.append(f"| {lv} | {frep.fmt(d['cells'])} | {frep.fmt(d['inherited'])} | {frep.fmt(d['found_run2'])} | {frep.fmt(d['eligible'])} | {frep.fmt(d['eligible_verified'])} | {frep.fmt(d['eligible_unverified'])} | "
                     f"{d['pending']} | {d['cleared_starts']} | {d['quarantined']} | {frep.fmt(d['beyond_bound'])} | {frep.fmt(d['earliest_tick'])} | {frep.fmt(d['eligible_mean_tick'])} | {frep.fmt(d['dispatches_run1'])} |")
    return lines


def _check_lines(s: Mapping[str, Any]) -> List[str]:
    r2 = s["run2"]
    ck, cl, e = r2["checks"], r2["claims"], r2["eager"] or {}
    return [f"Inherited cells {frep.fmt(r2['inherited'])}; checks (fresh-process replays of inherited prefixes): eager {frep.fmt(ck['checks_eager'])} (planned {e.get('planned')}, "
            f"{frep.fmt(e.get('wall_s'), 0)} s), lazy {frep.fmt(ck['checks_lazy'])}; ok {frep.fmt(ck['checks_ok'])}, quarantined {ck['checks_quarantined']}, could not run {ck['checks_error']}, "
            f"stale {ck['checks_stale']}; {frep.fmt(ck['check_ticks'])} ticks; queue {r2['check_queue']}, ready {r2['ready']}, pending {r2['pending']}, lent workers {r2['lent']}. "
            f"Draws: unverified {frep.fmt(r2['draws']['draws_unverified'])}, verified-only {frep.fmt(r2['draws']['verified_only_draws'])}, worker waits {frep.fmt(r2['draws']['worker_waits'])}, "
            f"ready dropped {r2['draws']['ready_dropped']}.",
            f"Claims: {frep.fmt(cl['claimed'])} claimed, {frep.fmt(cl['replayed'])} replayed, {frep.fmt(cl['not_replayed'])} not replayed (slower than or equal to the best); not-replayed clocks "
            f"{json.dumps(cl['not_replayed_clocks'])}. Cleared starts (down-weighted by cleared_weight per clear): {frep.fmt(r2['cleared_starts'])}. "
            f"Run 1's best clear replayed exactly at the open: {r2['anchor'].get('ok')}."]


def progress_md2(s: Mapping[str, Any], *, final: bool) -> str:
    w, th, mem, ar = s["work"], s["throughput"], s["memory"], s["archive"]
    peak = mem.get("peak") or {}
    state = f"**{s['status']}** ({s['stop']['reason']})" if final or s["stop"]["reason"] else "**RUNNING**"
    lines = [f"# Crossing search run 2: progress ({s['utc_start'][:10]})", "",
             f"{'Final. ' if final else ''}Status {state}. Updated {s['utc_end']}; elapsed {s['elapsed_s'] / 60.0:.0f} of {s['config']['max_wall_s'] / 60.0:g} min. "
             f"Dispatches {frep.fmt(w['dispatches'])} (jobs {frep.fmt(w['jobs'])}, advanced {frep.fmt(w['advanced'])}, falls {frep.fmt(w['falls'])}); "
             f"ticks {frep.fmt(w['ticks_total'])} of {frep.fmt(s['config']['max_ticks'])}; {frep.fmt(th['jobs_per_h'], 0)} jobs / h, {frep.fmt(th['ticks_per_h'])} ticks / h, "
             f"continuation {frep.fmt(th['continuation_rate'], 3)}. Cells {frep.fmt(ar['cells'])} (inherited {frep.fmt(s['run2']['inherited'])}, eligible {frep.fmt(ar['eligible'])}, new {frep.fmt(ar['new'])}, "
             f"replaced {frep.fmt(ar['replaced'])}, later arrivals {frep.fmt(ar['later'])}, beyond the E7 bound {frep.fmt(ar['beyond'])}, quarantined {ar['quarantined']}, retired "
             f"{ar['retired']}), words {frep.fmt(mem.get('words_mb'), 1)} MB. Main process {frep.fmt(peak.get('main_private_mb'), 0)} MB peak, tree {frep.fmt(peak.get('tree_private_mb'), 0)} MB, "
             f"BattleShip processes {peak.get('battleship')} peak.",
             f"Params: {json.dumps(s['config']['params'])}; arm {s['config']['arm']} (segments {s['config']['segment_words']} x {s['config']['max_segments']}, F3 window "
             f"{s['config']['window']}); key family {s['config']['key_family']}. Reference clear replayed exactly at open: {s['reference'].get('ok')} "
             f"({frep.fmt(s['reference'].get('completion_input_tick'))} / {frep.fmt(s['reference'].get('completion_time_passed'))}).", "",
             "## Best verified clear", ""] + _best_lines(s)
    lines += ["", "## Deepest level and earliest ticks", ""] + cs._deepest_lines(s)
    lines += ["", "## Cells per level", ""] + _level2_lines(s) + [""] + cs._level_lines(s)
    lines += ["", "## Lineages ahead of the best clear's pace", ""] + _pace_lines(s)
    lines += ["", "## Verified clears (replayed claims)", ""] + cs._clear_lines(s)
    lines += ["", "## Checks and claims", ""] + _check_lines(s)
    lines += ["", "## Effects of the signals", ""] + cs._effect_lines(s)
    lines += ["", "## Recent events", ""] + [f"- {e}" for e in reversed(s.get("events") or [])][:25]
    lines += ["", f"Memory projection: {json.dumps(mem.get('projection'), default=str)[:500]}", ""]
    return "\n".join(lines)


def report_md2(s: Mapping[str, Any]) -> str:
    w, th, mem, cl, ar, r2 = s["work"], s["throughput"], s["memory"], s["clears"], s["archive"], s["run2"]
    peak = mem.get("peak") or {}
    lines = [f"# Crossing search run 2 ({s['utc_start'][:10]})", "",
             f"Lab, exploratory, unregistered (mode lab). Status **{s['status']}** ({s['stop']['reason']}). Resumed from run 1 ({s['config']['run1']['dir']}, {frep.fmt(s['config']['run1']['cells'])} cells, "
             f"best verified {frep.fmt(s['config']['run1']['best_verified']['completion_input_tick'])}). Arm {s['config']['arm']} (segments {s['config']['segment_words']} x "
             f"{s['config']['max_segments']}, F3 window {s['config']['window']}); params {json.dumps(s['config']['params'])}; {s['config']['n_workers']} workers.", "",
             "| measure | value |", "|---|---|",
             f"| wall / open / eager checks / search / drain / close | {frep.fmt(s['elapsed_s'], 0)} s / {frep.fmt(s['phase_wall_s'].get('open'), 0)} s / {frep.fmt(s['phase_wall_s'].get('seed'), 0)} s / "
             f"{frep.fmt(s['phase_wall_s'].get('search'), 0)} s / {frep.fmt(s['phase_wall_s'].get('drain'), 0)} s / {frep.fmt(s['phase_wall_s'].get('close'), 0)} s |",
             f"| dispatches / jobs / advanced / falls | {frep.fmt(w['dispatches'])} / {frep.fmt(w['jobs'])} / {frep.fmt(w['advanced'])} / {frep.fmt(w['falls'])} |",
             f"| ticks: total / prefix / burst / checks / anchor / reference / verification | {frep.fmt(w['ticks_total'])} / {frep.fmt(w['prefix_ticks'])} / {frep.fmt(w['burst_ticks'])} / "
             f"{frep.fmt(w['check_ticks'])} / {frep.fmt(w['anchor_ticks'])} / {frep.fmt(w['reference_ticks'])} / {frep.fmt(w['verify_ticks'])} |",
             f"| throughput: jobs / h, ticks / h, new cells / h, continuation rate, mean ticks per job, mean burst words | {frep.fmt(th['jobs_per_h'], 0)} / {frep.fmt(th['ticks_per_h'])} / "
             f"{frep.fmt(th['new_cells_per_h'], 0)} / {frep.fmt(th['continuation_rate'], 3)} ({w['continued']} of {w['boundaries']}) / {frep.fmt(th['mean_ticks_per_job'], 0)} / "
             f"{frep.fmt(th['mean_burst_words'], 0)} |",
             f"| cells: inherited / new / replaced / later / self / beyond E7 / terminal / quarantined / retired / eligible | {frep.fmt(r2['inherited'])} / {frep.fmt(ar['new'])} / {frep.fmt(ar['replaced'])} / "
             f"{frep.fmt(ar['later'])} / {frep.fmt(ar['self'])} / {frep.fmt(ar['beyond'])} / {frep.fmt(ar['terminal'])} / {ar['quarantined']} / {ar['retired']} / {frep.fmt(ar['eligible'])} |",
             f"| reference clear / run 1's best clear replayed exactly at open | {s['reference'].get('ok')} / {r2['anchor'].get('ok')} |",
             f"| claims: claimed / replayed / verified / not replayed / faster than run 1's best ({frep.fmt(r2['best_run1']['completion_input_tick'])}) | {r2['claims']['claimed']} / {r2['claims']['replayed']} / "
             f"{cl['verified']} / {r2['claims']['not_replayed']} / {r2['faster_than_run1']} |",
             f"| main process MB peak / tree MB peak / BattleShip peak / words MB | {frep.fmt(peak.get('main_private_mb'), 0)} / {frep.fmt(peak.get('tree_private_mb'), 0)} / "
             f"{peak.get('battleship')} / {frep.fmt(mem.get('words_mb'), 1)} |",
             f"| memory projection | {json.dumps(mem.get('projection'), default=str)[:400]} |",
             "", "## Best verified clear", ""] + _best_lines(s) + ["", "## Clears (replayed claims)", ""] + cs._clear_lines(s)
    lines += ["", "## Deepest level and earliest ticks", ""] + cs._deepest_lines(s) + ["", "## Cells per level", ""] + _level2_lines(s) + [""] + cs._level_lines(s)
    lines += ["", "## Lineages ahead of the best clear's pace", ""] + _pace_lines(s) + ["", "## Checks and claims", ""] + _check_lines(s)
    lines += ["", "## Effects of the signals", ""] + cs._effect_lines(s) + ["", "## Events", ""] + [f"- {e}" for e in (s.get("events") or [])]
    lines += ["", f"Eager checks: {json.dumps(r2['eager'], default=str)}", "", f"Integrity: {json.dumps(s['integrity'], separators=(',', ':'), default=str)}", ""]
    return "\n".join(lines)


# -- commands -----------------------------------------------------------------------------------------------------------------------------------------


def params_from_args(a: argparse.Namespace) -> Params2:
    p = Params2(seeds=1, seed_order="level", level_decay=a.level_decay, novelty_exp=a.novelty_exp, seen_exp=0.0 if a.no_seen_penalty else a.seen_exp,
                bonus_exp=0.0 if a.no_break_bonus else a.bonus_exp, pace_exp=a.pace_exp, max_segments=a.max_segments, retire_after=a.retire_after, max_cells=a.max_cells,
                max_dispatches=a.max_dispatches, rng_seed=a.rng_seed, cleared_weight=a.cleared_weight, check_slots=a.check_slots, check_queue_max=a.check_queue_max,
                eager_levels=a.eager_levels, eager_max_min=a.eager_max_min, canary_per_level=a.canary_per_level, reset_novelty=bool(a.reset_novelty), check_error_limit=a.check_error_limit)
    p.check()
    return p


def plan_and_write(lab_root: Path, run1_dir: Path, out: Path, params: Params2, analyse: fv.Analyse = fv.real_analyse) -> Dict[str, Any]:
    """Zero native ticks: the plan written as plan.json (a different archive set is never overwritten) and resume.json (the per-level readings)."""
    P = build_plan(Path(lab_root), Path(run1_dir), params, analyse)
    fs = g.LabFS(lab_root)
    saved = Path(out) / "plan.json"
    if saved.is_file():
        old = json.loads(saved.read_text(encoding="utf-8"))
        if old.get("archive_set_digest") != P["plan"]["archive_set_digest"]:
            raise SearchError(f"refused: {saved} exists with a different archive set ({str(old.get('archive_set_digest'))[:16]})")
    fs.mkdir(Path(out))
    fs.write_json(saved, P["plan"])
    return P


def run_command(lab_root: Path, run1: Path, out: Path, a: argparse.Namespace) -> str:
    return (f"python -B tools/frs/crossing_search_run2.py run --lab-root {Path(lab_root).as_posix()} --run1 {Path(run1).as_posix()} --out {Path(out).as_posix()} "
            f"--workers {a.workers} --level-decay {a.level_decay:g} --novelty-exp {a.novelty_exp:g} --seen-exp {a.seen_exp:g} --bonus-exp {a.bonus_exp:g} --pace-exp {a.pace_exp:g} "
            f"--max-segments {a.max_segments} --retire-after {a.retire_after} --cleared-weight {a.cleared_weight:g} --check-slots {a.check_slots} --check-queue-max {a.check_queue_max} "
            f"--eager-levels {a.eager_levels} --eager-max-min {a.eager_max_min:g} --canary-per-level {a.canary_per_level} --check-error-limit {a.check_error_limit} "
            f"--max-cells {a.max_cells} --rng-seed {a.rng_seed} --max-ticks {a.max_ticks} --max-wall-min {a.max_wall_min:g}"
            + (" --no-seen-penalty" if a.no_seen_penalty else "") + (" --no-break-bonus" if a.no_break_bonus else "") + (" --reset-novelty" if a.reset_novelty else "")
            + (f" --max-dispatches {a.max_dispatches}" if a.max_dispatches else ""))


def cmd_plan(lab_root: Path, run1: Path, out: Path, a: argparse.Namespace) -> int:
    params = params_from_args(a)
    P = plan_and_write(lab_root, run1, out, params)
    p = P["plan"]
    print(json.dumps({k: p[k] for k in ("run1", "e7", "best_pace", "archive_set_digest")}, separators=(",", ":"), default=str))
    print(json.dumps({"params": p["params"], "arm": p["arm"], "eager": {k: v for k, v in p["eager"].items() if k != "cids"}, "check_fit": p["check_fit"]}, separators=(",", ":"), default=str))
    for lv, d in p["archive"]["per_level"].items():
        print("level", lv, json.dumps(d, separators=(",", ":"), default=str))
    print("archive", json.dumps({k: p["archive"][k] for k in ("inherited", "eligible", "cleared_starts", "cleared_starts_rows", "roots")}))
    for lv, d in p["archive"]["ahead_of_pace"].items():
        print("ahead of the best clear's pace at level", lv, json.dumps(d, separators=(",", ":"), default=str))
    proj = projection2(p["throughput_fit"], p["check_fit"], p["archive"]["per_level"], params, a.workers, a.max_wall_min / 60.0, P["R1"]["summary"])
    print("throughput fit", json.dumps(p["throughput_fit"], separators=(",", ":")))
    print("projection", json.dumps(proj, separators=(",", ":")))
    print(f"lab code digest now {fr.code_digest(fr.code_manifest())[:16]}; run 1's {str(p['run1'].get('lab_code_digest'))[:16]}")
    print(f"wrote {Path(out) / 'plan.json'}")
    print("run with:", run_command(lab_root, run1, out, a))
    return 0


def cmd_run(lab_root: Path, run1: Path, out: Path, a: argparse.Namespace) -> int:
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
    P = build_plan(lab_root, run1, params)
    old = json.loads(saved.read_text(encoding="utf-8"))
    if old.get("archive_set_digest") != P["plan"]["archive_set_digest"]:
        print("refused: the archive set differs from the saved plan")
        return 2
    if old.get("params") != params.as_dict():
        print(f"refused: the parameters differ from the saved plan's ({old.get('params')})")
        return 2
    if a.check_slots > a.workers:
        print("refused: --check-slots is at most --workers")
        return 2
    install_kill_on_close_job()
    cfg = cs.SearchConfig(lab_root=Path(lab_root), out=Path(out), run_dir=run_dir, frontier_dir=Path(run1), n_workers=a.workers, max_ticks=a.max_ticks,
                          max_wall_s=60.0 * a.max_wall_min, expect_code=P["R1"]["config"].get("lab_code_digest"))
    code = ResumeSearch(cfg, fl.real_env(Path(lab_root), run_dir), P, params).run()
    print(f"exit {code}: {run_dir / 'report.md'} (progress: {run_dir / 'progress.md'})")
    return code


def default_run1(lab: Path) -> Optional[Path]:
    """The newest crossing search output folder under the lab root (by name) that is not itself a run 2 folder."""
    hits = sorted(p for p in lab.glob("crossing_*") if p.is_dir() and not p.name.endswith("_run2") and all((p / f).is_file() for f in RUN1_FILES))
    return hits[-1] if hits else None


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("command", choices=("plan", "run"))
    ap.add_argument("--lab-root", default=str(g.DEFAULT_LAB_ROOT))
    ap.add_argument("--run1", default=None, help="run 1's output folder (default: the newest crossing_* under the lab root that is not a run 2)")
    ap.add_argument("--out", default=None, help="default <lab root>/crossing_<date>_run2")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--level-decay", type=float, default=cs.Params.level_decay)
    ap.add_argument("--novelty-exp", type=float, default=cs.Params.novelty_exp)
    ap.add_argument("--seen-exp", type=float, default=cs.Params.seen_exp)
    ap.add_argument("--no-seen-penalty", action="store_true")
    ap.add_argument("--bonus-exp", type=float, default=cs.Params.bonus_exp)
    ap.add_argument("--no-break-bonus", action="store_true")
    ap.add_argument("--pace-exp", type=float, default=cs.Params.pace_exp)
    ap.add_argument("--max-segments", type=int, default=cs.Params.max_segments)
    ap.add_argument("--retire-after", type=int, default=cs.Params.retire_after)
    ap.add_argument("--cleared-weight", type=float, default=Params2.cleared_weight, help="weight factor per claimed clear of a representative (0 = never drawn again)")
    ap.add_argument("--check-slots", type=int, default=Params2.check_slots, help="workers lent at once to the inherited-cell checks and the clear verifications")
    ap.add_argument("--check-queue-max", type=int, default=Params2.check_queue_max)
    ap.add_argument("--eager-levels", type=int, default=Params2.eager_levels, help="the deepest eligible levels checked at the open")
    ap.add_argument("--eager-max-min", type=float, default=Params2.eager_max_min)
    ap.add_argument("--canary-per-level", type=int, default=Params2.canary_per_level)
    ap.add_argument("--reset-novelty", action="store_true", help="inherited cells start at fresh = 0")
    ap.add_argument("--check-error-limit", type=int, default=Params2.check_error_limit)
    ap.add_argument("--max-cells", type=int, default=cs.Params.max_cells)
    ap.add_argument("--max-dispatches", type=int, default=cs.Params.max_dispatches)
    ap.add_argument("--rng-seed", type=int, default=cs.Params.rng_seed)
    ap.add_argument("--max-ticks", type=int, default=cs.SearchConfig.max_ticks)
    ap.add_argument("--max-wall-min", type=float, default=480.0)
    a = ap.parse_args(argv)
    try:
        lab = g.validate_lab_root(Path(a.lab_root))
        out = g.validate_run_dir(Path(a.out) if a.out else lab / f"crossing_{dt.date.today().isoformat()}_run2", lab)
        run1 = Path(a.run1) if a.run1 else default_run1(lab)
        if run1 is None:
            raise SystemExit("refused: no crossing search output folder (pass --run1)")
        run1 = g.validate_run_dir(run1, lab)
    except g.LabRootError as exc:
        raise SystemExit(str(exc))
    missing = [f for f in RUN1_FILES if not (run1 / f).is_file()]
    if missing:
        raise SystemExit(f"refused: {run1} is not a crossing search output folder (missing {missing})")
    if g.norm(out) == g.norm(run1) or g.under(g.norm(out), g.norm(run1)):
        raise SystemExit("refused: the output folder is run 1's folder (never written)")
    if not 1 <= a.workers <= 5:
        raise SystemExit("refused: 1 to 5 workers (one standby each: at most 10 game processes)")
    if not 1 <= a.check_slots <= a.workers:
        raise SystemExit("refused: --check-slots is 1 to --workers")
    if a.max_ticks < 1 or a.max_wall_min <= 0:
        raise SystemExit("refused: --max-ticks and --max-wall-min are positive")
    try:
        params_from_args(a)
    except SearchError as exc:
        raise SystemExit(str(exc))
    if not (lab / "import" / "import_manifest.json").is_file():
        raise SystemExit("refused: no lab import (rl/frs_lab.py import first)")
    g.LabGuard.install(lab)
    lock = g.LabLock(lab, f"crossing_search_run2 {a.command}")
    try:
        lock.acquire()
    except g.LabRootError as exc:
        print(str(exc))
        return 2
    try:
        if a.command == "plan":
            return cmd_plan(lab, run1, out, a)
        return cmd_run(lab, run1, out, a)
    except SearchError as exc:
        print(str(exc))
        return 3
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
