#!/usr/bin/env python3
"""Frontier continuation search (lab, exploratory, unregistered): a focused, iterative search from the ahead-of-pace states the
trail-lead probe recorded (docs/frs_trail_probe_2026-10-14.md), to find out whether a clear can be finished from them faster than
the lab import's best verified clear (the reference).

Starts (generic rule, no hand-picking): every level arrival the trail-lead probe recorded (a dispatch's `levels` reading: the tick
at which it broke one more target) whose tick is strictly earlier than the reference clear's arrival at the same level, with its
exact prefix: the dispatch's start words (the lead cell's stored prefix or the route's words up to its arrival, rebuilt from the
import by the probe's own rule and checked against the probe's recorded digests) followed by the recorded burst words up to that
tick (re-derived from the probe's key family and iteration). One start per distinct word prefix, ordered by level (deepest first)
then lead. The arrival's cell key and end record are not in the probe's rows, so the run's first phase ("seed") re-derives every
start natively: its base prefix is replayed and the recorded burst words are played up to the arrival tick (every tick under the
tick contract); the reach at that tick gives the key, the end record, the record digest and the chain digest; the burst words
played must equal the recorded ones and the arrival must be a break at the recorded level. Seeded starts are deduplicated by cell
key, keeping the earliest arrival.

Rounds: each round dispatches B bursts (the lab's CONT arm unchanged: the m8_rd_explore_v1 keyed stream, 120-word segments, at
most three continuations under the F3 trigger read on the imported archive, which is never mutated) from every start in the
frontier; a start with a break record (one of its dispatches broke a target) gets B + bonus bursts (switch). Every reach of a
burst that is ahead of the reference pace at its level (its tick strictly below the reference's arrival at that level) is a
candidate for the next round, with its exact prefix and the reach's own end record (mode `reaches`; mode `breaks` keeps the
level arrivals only). Candidates are deduplicated by cell key over the whole run: the earliest arrival holds the key, a later
arrival at a held key is dropped, an earlier one supersedes the holder. The next frontier is the top F candidates by (level
descending, lead descending), after a share of F reserved for the best members of the previous frontier (one bad round cannot
wipe out progress); slots neither fills take the best remembered candidates (a bounded reserve, the memory budget). A start that
has made R dispatches without a break is retired (switch).

Clears: every claimed clear is replayed from tick 0 in a fresh process with the verify flags, twice, as soon as a worker can be
lent (rl/frs_verify.verify_twice, as the lab runner does), and counts only when both replays agree exactly with each other and
with the in-run claim; the candidates still pending at a stop are verified at the close. progress.md (rewritten every round,
every verification and every minute) reports every verified clear's completion_input_tick against the reference's.

No cell id, position, target id, tick value, route or census number is in this file: everything is read from the import and the
probe's outputs. Nothing reads native RNG. Process restart resets the episode: every dispatch and every verification replay is a
fresh process from tick 0.

    python -B tools/frs/frontier_search.py plan --lab-root C:/BattleShip_lab --probe DIR [--out DIR] [--bursts B --frontier F --share S ...]
    python -B tools/frs/frontier_search.py run  --lab-root ... --probe DIR --out DIR [--workers 5] [--max-wall-min 360] [--max-ticks N] ...

`plan` is zero native ticks (the starts, their checks, the budget projection, the run command); `run` is native. Writes only under
the output folder (default <lab root>/frontier_<date>) through the lab's guard (rl/frs_guard: refuses the checkout, any runs/
folder and the D: evidence roots; never reads runs/). Readiness at the registered thresholds, never lowered. At most 5 workers
with one standby each (at most 10 game processes; a lent worker holds one, so an in-run verification replay fits). The lab's
memory budget (a soft breach is a clean stop) and projection. Zero-tick tests: tools/frs/frontier_search_tests.py. Run with python -B.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import sys
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, List, Mapping, Optional, Sequence, Tuple

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
import trail_probe as tp  # noqa: E402

SEARCH_CONTRACT = "frs_frontier_search_v1"
KEY_FAMILY = "frontier"
ARM_NAME, ARM = tp.ARM_NAME, dict(tp.ARM)             # the lab's CONT arm, unchanged
LEAD, CONTROL = tp.LEAD, tp.CONTROL
SEED, BURST = "seed", "burst"
MODES = ("reaches", "breaks")
BAD_OUTCOMES = ("mismatch", "lifecycle", "aborted")
PROBE_FILES = ("plan.json", "starts.jsonl", "run/dispatches.jsonl")
EXIT = {"COMPLETED": 0, "FRONTIER_EMPTY": 0, "TICK_CAP": 0, "WALL_CAP": 0, "MEMORY_BUDGET": 0, "REFUSED": 2, "SEARCH_INVALID": 3,
        "SEARCH_INCOMPLETE": 4}
STATUS_RANK = {"COMPLETED": 0, "FRONTIER_EMPTY": 0, "TICK_CAP": 1, "WALL_CAP": 1, "MEMORY_BUDGET": 1, "SEARCH_INCOMPLETE": 2, "SEARCH_INVALID": 3}
HELD, LATER, SUPERSEDES = "held", "later", "supersedes"


class SearchError(RuntimeError):
    """A violated search invariant (zero-tick)."""


class Refused(Exception):
    """Open-phase refusal: nothing was launched."""


# -- parameters ---------------------------------------------------------------------------------------------------------------------------------


@dataclass
class Params:
    bursts: int = 4               # B: bursts per frontier start per round
    frontier: int = 32            # F: the frontier size
    share: float = 0.25           # the share of F reserved for the previous frontier's best members
    bonus: int = 4                # extra bursts per round for a start with a break record (0 = switch off)
    retire_after: int = 16        # dispatches without a break after which a start is retired (0 = switch off)
    candidates: str = "reaches"   # every reach ahead of pace, or the level arrivals only ("breaks")
    reserve: int = 2000           # remembered candidates kept with their prefixes beyond the frontier (the memory budget of the beam)
    max_rounds: int = 0           # 0 = until a cap

    def check(self) -> None:
        if self.bursts < 1 or self.frontier < 1 or self.bonus < 0 or self.retire_after < 0 or self.reserve < 0 or self.max_rounds < 0:
            raise SearchError("refused: --bursts and --frontier are positive; --bonus, --retire-after, --reserve and --max-rounds are not negative")
        if not 0.0 <= self.share < 1.0:
            raise SearchError("refused: --share is in [0, 1)")
        if self.candidates not in MODES:
            raise SearchError(f"refused: --candidates is one of {MODES}")

    def keep(self) -> int:
        """Slots of the next frontier reserved for the previous frontier's best members."""
        return min(self.frontier, int(math.ceil(self.share * self.frontier)))

    def as_dict(self) -> Dict[str, Any]:
        return {"bursts": self.bursts, "frontier": self.frontier, "share": self.share, "keep_slots": self.keep(), "bonus": self.bonus,
                "retire_after": self.retire_after, "candidates": self.candidates, "reserve": self.reserve, "max_rounds": self.max_rounds}

    def bursts_for(self, breaks: int) -> int:
        """Bursts a frontier start gets this round: B, plus the bonus when one of its dispatches has already broken a target (switch)."""
        return self.bursts + (self.bonus if self.bonus > 0 and int(breaks) > 0 else 0)


# -- the beam: starts, key dedup, selection (zero native ticks) ----------------------------------------------------------------------------------


@dataclass
class Start:
    sid: int
    level: int
    tick: int
    lead: int
    digest: str
    origin: Dict[str, Any]
    words: Optional[bytes]
    key: Optional[Tuple[int, int, str, int, int]] = None
    end: Optional[Tuple[Any, ...]] = None
    end_digest: Optional[bytes] = None
    chain: Optional[bytes] = None
    seed: Optional[Dict[str, Any]] = None       # a probe start before seeding: how to re-derive its record natively
    next_k: int = 0
    dispatched: int = 0
    breaks: int = 0                             # dispatches that broke at least one target
    since_break: int = 0
    bonus_dispatches: int = 0
    children: int = 0
    deepest_child: int = 0
    selected: int = 0                           # rounds in the frontier
    retired: Optional[str] = None
    superseded: Optional[int] = None
    dropped: Optional[str] = None

    def alive(self) -> bool:
        return self.key is not None and self.retired is None and self.superseded is None and self.dropped is None

    def order(self) -> Tuple[int, int, int, str]:
        return (-self.level, -self.lead, self.tick, self.digest)

    def draw_id(self, archive_id: str) -> str:
        return f"{archive_id}|{KEY_FAMILY}|{self.digest}"

    def row(self, *, words: bool = False) -> Dict[str, Any]:
        out = {"sid": self.sid, "level": self.level, "tick": self.tick, "lead": self.lead, "digest": self.digest, "origin": self.origin,
               "key": list(self.key) if self.key else None, "end_digest": self.end_digest.hex() if self.end_digest else None,
               "chain": self.chain.hex() if self.chain else None, "dispatched": self.dispatched, "breaks": self.breaks, "since_break": self.since_break,
               "bonus_dispatches": self.bonus_dispatches, "children": self.children, "deepest_child": self.deepest_child, "selected": self.selected,
               "retired": self.retired, "superseded": self.superseded, "dropped": self.dropped, "has_words": self.words is not None}
        if words and self.words is not None:
            out["words_hex"] = self.words.hex()
        if self.seed is not None:
            out["seed"] = {k: self.seed[k] for k in ("draw_id", "k", "base_words", "base_digest", "n")}
        return out


class Beam:
    """Every state the search knows, keyed by its exact words (digest) and by its cell key (the earliest arrival holds the key)."""

    def __init__(self, archive_id: str, arrival: Mapping[Any, int], params: Params):
        self.archive_id = str(archive_id)
        self.arrival = {int(k): int(v) for k, v in arrival.items()}
        self.p = params
        self.starts: List[Start] = []
        self.by_digest: Dict[str, int] = {}
        self.holder: Dict[Tuple[int, int, str, int, int], int] = {}
        self.frontier: List[int] = []
        self.best: Dict[int, Dict[str, Any]] = {}
        self.counts = {"states": 0, "same_words": 0, "placed": 0, "held": 0, "later": 0, "supersedes": 0, "evicted": 0, "retired": 0}

    def lead_of(self, level: int, tick: int) -> Optional[int]:
        a = self.arrival.get(int(level))
        return None if a is None else a - int(tick)

    def new_start(self, words: bytes, level: int, tick: int, origin: Mapping[str, Any], seed: Optional[Dict[str, Any]] = None) -> Tuple[Start, bool]:
        """(the start of these exact words, whether it is new). The level must be live and the tick strictly ahead of the reference."""
        words = bytes(words)
        if len(words) != int(tick) or int(level) >= mcell.TARGETS_TOTAL:
            raise SearchError(f"a start's words are its tick ({len(words)} vs {tick}) and its level is live ({level})")
        lead = self.lead_of(level, tick)
        if lead is None or lead <= 0:
            raise SearchError(f"a start is strictly ahead of the reference at its level (level {level}, tick {tick}, lead {lead})")
        d = mcell.words_digest(words)
        sid = self.by_digest.get(d)
        if sid is not None:
            self.counts["same_words"] += 1
            return self.starts[sid], False
        s = Start(sid=len(self.starts), level=int(level), tick=int(tick), lead=int(lead), digest=d, origin=dict(origin), words=words,
                  seed=dict(seed) if seed else None)
        self.starts.append(s)
        self.by_digest[d] = s.sid
        self.counts["states"] += 1
        return s, True

    def place(self, s: Start, key: Sequence[Any], end: Sequence[Any], end_digest: bytes, chain: bytes) -> str:
        """Record the state's native identity and settle its cell key: HELD (first arrival), SUPERSEDES (earlier than the holder, which is
        superseded) or LATER (dropped: a later arrival at a held key)."""
        k = fa.norm_key(key)
        if mcell.level_of_mask(k[3]) != s.level:
            raise SearchError(f"start {s.sid}: the key's level {mcell.level_of_mask(k[3])} is not the start's {s.level}")
        s.key, s.end, s.end_digest, s.chain = k, tuple(end), bytes(end_digest), bytes(chain)
        self.counts["placed"] += 1
        h = self.holder.get(k)
        if h is None:
            self.holder[k] = s.sid
            verdict = HELD
        else:
            other = self.starts[h]
            if s.tick < other.tick:
                other.superseded = s.sid                              # its prefix is freed by the round's sweep (a burst of it may still be in flight)
                self.holder[k] = s.sid
                verdict = SUPERSEDES
            else:
                s.dropped = f"later arrival at a key held by start {h} (tick {other.tick})"
                s.words = None
                verdict = LATER
        self.counts[verdict] += 1
        if verdict != LATER:
            b = self.best.get(s.level)
            if b is None or s.lead > b["lead"]:
                self.best[s.level] = {"lead": s.lead, "tick": s.tick, "sid": s.sid, "origin": s.origin}
        return verdict

    def candidates(self, parent: Start, res: Mapping[str, Any], rnd: int, k: int) -> Tuple[List[Start], Dict[str, int]]:
        """The reaches of a burst that are ahead of the reference pace at their level, as placed starts (the exact prefix is the parent's words
        plus the burst's words up to the reach; the end record is the reach's own)."""
        assert parent.words is not None
        L, burst = len(parent.words), bytes(res["words"])
        break_ticks = {int(t) for t, _i in res["breaks_all"] if int(t) > L}
        c = {"reaches": 0, "ahead": 0, "same_words": 0, "held": 0, "later": 0, "supersedes": 0, "terminal": 0}
        out: List[Start] = []
        for r in sorted(res["reaches"], key=lambda r: int(r[0])):
            j, key, obs, rd, chain, terminal = int(r[0]), fa.norm_key(r[1]), tuple(r[2]), bytes(r[3]), bytes(r[4]), bool(r[5])
            c["reaches"] += 1
            lv = mcell.level_of_mask(key[3])
            if terminal or lv >= mcell.TARGETS_TOTAL:
                c["terminal"] += int(terminal)
                continue
            if self.p.candidates == "breaks" and j not in break_ticks:
                continue
            lead = self.lead_of(lv, j)
            if lead is None or lead <= 0 or not L < j <= L + len(burst):
                continue
            c["ahead"] += 1
            h = self.holder.get(key)
            if h is not None and j >= self.starts[h].tick:           # a later arrival at a held key: dropped before any state is kept for it
                c[LATER] += 1
                self.counts[LATER] += 1
                continue
            s, fresh = self.new_start(parent.words + burst[:j - L], lv, j, {"kind": BURST, "parent": parent.sid, "round": rnd, "k": k})
            if not fresh:
                c["same_words"] += 1
                continue
            verdict = self.place(s, key, obs, rd, chain)
            c[verdict] += 1
            if verdict != LATER:
                out.append(s)
                parent.children += 1
                parent.deepest_child = max(parent.deepest_child, lv)
        return out, c

    def select(self, cands: Sequence[Start], prev: Sequence[int]) -> List[int]:
        """The next frontier: the previous frontier's best members in the reserved share, then the round's candidates by (level, lead), then the
        rest of the previous frontier, then the reserve; every member alive; F at most."""
        p = self.p
        prev_ok = sorted((self.starts[i] for i in prev if self.starts[i].alive() and self.starts[i].words is not None), key=Start.order)
        keep = prev_ok[:p.keep()]
        chosen: Dict[int, Start] = {s.sid: s for s in keep}
        for s in sorted(cands, key=Start.order):
            if len(chosen) >= p.frontier:
                break
            if s.alive() and s.words is not None and s.sid not in chosen:
                chosen[s.sid] = s
        for pool in (prev_ok, self.reserve(exclude=chosen)):
            for s in pool:
                if len(chosen) >= p.frontier:
                    break
                if s.sid not in chosen:
                    chosen[s.sid] = s
        out = [s.sid for s in sorted(chosen.values(), key=Start.order)]
        for i in out:
            self.starts[i].selected += 1
        self.frontier = out
        return out

    def reserve(self, exclude: Mapping[int, Any] = {}) -> List[Start]:
        return sorted((s for s in self.starts if s.alive() and s.words is not None and s.sid not in exclude and s.sid not in self.frontier),
                      key=Start.order)

    def evict(self) -> int:
        """Keep the reserve within the budget: the worst-ordered remembered states lose their prefixes (their keys stay held)."""
        n = 0
        for s in self.reserve()[self.p.reserve:]:
            s.words = None
            n += 1
        self.counts["evicted"] += n
        return n

    def retire(self, rnd: int) -> List[Start]:
        if self.p.retire_after <= 0:
            return []
        out = []
        for i in self.frontier:
            s = self.starts[i]
            if s.alive() and s.since_break >= self.p.retire_after:
                s.retired = f"round {rnd}: {s.since_break} dispatches without a break"
                self.counts["retired"] += 1
                out.append(s)
        return out

    def sweep(self) -> int:
        """Free the prefixes of the states that are no longer alive (retired, superseded, dropped); their keys and readings stay."""
        n = 0
        for s in self.starts:
            if s.words is not None and not s.alive() and (s.key is not None or s.dropped is not None):      # never an unseeded initial start
                s.words = None
                n += 1
        return n

    def initial(self) -> List[Start]:
        return sorted((s for s in self.starts if s.seed is not None), key=Start.order)

    def per_level(self, sids: Sequence[int]) -> Dict[str, Dict[str, Any]]:
        per: Dict[int, Dict[str, Any]] = {}
        for i in sids:
            s = self.starts[i]
            d = per.setdefault(s.level, {"starts": 0, "best_lead": None, "best_tick": None, "with_breaks": 0})
            d["starts"] += 1
            d["with_breaks"] += int(s.breaks > 0)
            if d["best_lead"] is None or s.lead > d["best_lead"]:
                d["best_lead"], d["best_tick"] = s.lead, s.tick
        return {str(lv): d for lv, d in sorted(per.items(), key=lambda kv: -kv[0])}

    def best_by_level(self) -> Dict[str, Dict[str, Any]]:
        return {str(lv): dict(b, reference=self.arrival.get(lv)) for lv, b in sorted(self.best.items(), key=lambda kv: -kv[0])}

    def stats(self) -> Dict[str, Any]:
        alive = sum(1 for s in self.starts if s.alive())
        return dict(self.counts, alive=alive, with_words=sum(1 for s in self.starts if s.words is not None), frontier=len(self.frontier),
                    reserve=len(self.reserve()), deepest_level=max((s.level for s in self.starts if s.key is not None), default=None))


# -- the probe's outputs and the initial starts (zero native ticks) -------------------------------------------------------------------------------


def read_jsonl(p: Path) -> List[Dict[str, Any]]:
    with open(p, encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def level_arrivals(level: int, breaks: Sequence[Sequence[int]]) -> List[Tuple[int, int]]:
    """[(level, tick)] of the states a break table produces after a start at `level`: the level after every break of a tick (two targets broken
    on one tick make one state at the deeper level; the intermediate level is no state), in tick order."""
    by_tick: Dict[int, int] = {}
    for t, _i in breaks:
        by_tick[int(t)] = by_tick.get(int(t), 0) + 1
    out: List[Tuple[int, int]] = []
    lv = int(level)
    for t in sorted(by_tick):
        lv += by_tick[t]
        out.append((lv, t))
    return out


def read_probe(probe_dir: Path) -> Dict[str, Any]:
    """The trail-lead probe's outputs: its plan, its starts (lengths and digests) and its dispatch rows (read-only)."""
    probe_dir = Path(probe_dir)
    missing = [f for f in PROBE_FILES if not (probe_dir / f).is_file()]
    if missing:
        raise SearchError(f"refused: {probe_dir} is not a trail-lead probe output folder (missing {missing})")
    plan = json.loads((probe_dir / "plan.json").read_text(encoding="utf-8"))
    if plan.get("contract") != tp.PROBE_CONTRACT or plan.get("mode") != "lab":
        raise SearchError(f"refused: {probe_dir / 'plan.json'} is not a {tp.PROBE_CONTRACT} plan")
    starts = {int(r["pair"]): r for r in read_jsonl(probe_dir / "starts.jsonl")}
    rows = read_jsonl(probe_dir / "run" / "dispatches.jsonl")
    config = summary = {}
    if (probe_dir / "run" / "config.json").is_file():
        config = json.loads((probe_dir / "run" / "config.json").read_text(encoding="utf-8"))
    if (probe_dir / "run" / "summary.json").is_file():
        summary = json.loads((probe_dir / "run" / "summary.json").read_text(encoding="utf-8"))
    return {"dir": probe_dir, "plan": plan, "starts": starts, "rows": rows, "config": config, "summary": summary}


def throughput_fit(rows: Sequence[Mapping[str, Any]], summary: Mapping[str, Any], config: Mapping[str, Any]) -> Dict[str, Any]:
    """Per-job wall = a + b * ticks (least squares over the probe's finished jobs) and the probe's main-loop efficiency (measured jobs per
    hour against the per-worker ideal), for the budget projection."""
    ok = [r for r in rows if r.get("outcome") not in BAD_OUTCOMES and r.get("wall_s") and r.get("ticks")]
    out: Dict[str, Any] = {"jobs": len(ok)}
    f = fm.fit([float(r["ticks"]) for r in ok], [float(r["wall_s"]) for r in ok]) if len(ok) >= 3 else None
    if f is None:
        return out
    a, b = f
    mean_wall = sum(float(r["wall_s"]) for r in ok) / len(ok)
    out.update({"wall_s_fixed": round(a, 3), "wall_s_per_tick": round(b, 6), "mean_wall_s": round(mean_wall, 3),
                "mean_burst_words": round(sum(int(r["words_played"]) for r in ok) / len(ok), 1),
                "mean_reaches_per_job": round(sum(int(r.get("reaches") or 0) for r in ok) / len(ok), 1)})
    n_workers = int(config.get("n_workers") or 0)
    wall = float((summary.get("phase_wall_s") or {}).get("dispatch") or 0.0)
    jobs = int((summary.get("work") or {}).get("jobs") or 0)
    if n_workers and wall > 0 and jobs:
        measured = 3600.0 * jobs / wall
        ideal = n_workers * 3600.0 / mean_wall
        out.update({"probe_workers": n_workers, "probe_jobs_per_h": round(measured, 1), "probe_ideal_jobs_per_h": round(ideal, 1),
                    "efficiency": round(min(1.0, measured / ideal), 4)})
    return out


def projection(fit: Mapping[str, Any], beam: Beam, params: Params, n_workers: int, hours: float) -> Dict[str, Any]:
    """Expected dispatches, rounds and ticks per hour and over the wall, from the probe's throughput fit and the frontier's prefix lengths."""
    if "wall_s_fixed" not in fit:
        return {"available": False}
    top = sorted(beam.initial(), key=Start.order)[:params.frontier]
    prefix = sum(s.tick for s in top) / len(top) if top else 0.0
    ticks_per_job = prefix + float(fit["mean_burst_words"])
    wall_job = float(fit["wall_s_fixed"]) + float(fit["wall_s_per_tick"]) * ticks_per_job
    eff = float(fit.get("efficiency") or 0.85)
    jobs_h = eff * n_workers * 3600.0 / wall_job
    per_round = params.frontier * params.bursts
    return {"available": True, "frontier_mean_prefix_ticks": round(prefix), "ticks_per_job": round(ticks_per_job), "wall_s_per_job_per_worker": round(wall_job, 2),
            "efficiency": eff, "workers": n_workers, "dispatches_per_h": round(jobs_h), "ticks_per_h": round(jobs_h * ticks_per_job),
            "dispatches_per_round_base": per_round, "dispatches_per_round_all_bonus": params.frontier * (params.bursts + params.bonus),
            "rounds_per_h_base": round(jobs_h / per_round, 1), "hours": hours, "dispatches_over_wall": round(jobs_h * hours),
            "ticks_over_wall": round(jobs_h * ticks_per_job * hours),
            "seed_ticks": sum(s.tick for s in beam.initial()), "note": "the frontier moves deeper over the run, so prefixes lengthen and jobs slow"}


def build_search_plan(lab: Any, R: Mapping[str, Any], probe: Mapping[str, Any], params: Params) -> Dict[str, Any]:
    """The initial starts from the probe's rows (zero native ticks) and their checks: the probe's start set is this import's, every base
    prefix has the recorded digest, every recorded burst re-derives from its key family and iteration, every continuation before the
    arrival was a go, every start is strictly ahead of the reference at a live level."""
    params.check()
    P = tp.build_plan(lab, R)
    pp = probe["plan"]
    if pp.get("start_set_digest") != P["plan"]["start_set_digest"]:
        raise SearchError("refused: the probe's start set is not this import's (start_set_digest differs)")
    if pp["route"]["digest"] != R["meta"]["native_action_digest"] or pp["route"]["words"] != len(R["words"]):
        raise SearchError("refused: the probe's route is not the import's reference clear")
    arrival = {str(k): int(v) for k, v in R["arrival"].items()}
    if {str(k): int(v) for k, v in pp["arrival_by_level"].items()} != arrival:
        raise SearchError("refused: the probe's arrival ticks per level are not the reference's")
    by_pair = {int(s["pair"]): s for s in P["starts"]}
    beam = Beam(lab.archive_id, R["arrival"], params)
    st = {"rows": len(probe["rows"]), "usable_rows": 0, "level_arrivals": 0, "multi_break_ticks": 0, "ahead": 0, "clears_excluded": 0, "behind_or_equal": 0,
          "same_words": 0, "pairs_used": set(), "bursts_rederived": 0}
    for row in sorted(probe["rows"], key=lambda r: (int(r["pair"]), str(r["arm"]), int(r["k"]))):
        if row.get("outcome") in BAD_OUTCOMES:
            continue
        st["usable_rows"] += 1
        pair, arm, k = int(row["pair"]), str(row["arm"]), int(row["k"])
        s0, rec = by_pair.get(pair), probe["starts"].get(pair)
        if s0 is None or rec is None or arm not in (LEAD, CONTROL):
            raise SearchError(f"probe row pair {pair} {arm} k {k}: no such start")
        base = bytes(s0[arm]["words"])
        if int(rec["cid"]) != int(s0["cid"]) or int(row["cid"]) != int(s0["cid"]) or rec[arm]["words_digest"] != mcell.words_digest(base) \
                or int(rec[arm]["words"]) != len(base) or int(row["start_tick"]) != len(base) or rec[arm]["chain"] != bytes(s0[arm]["chain"]).hex():
            raise SearchError(f"probe row pair {pair} {arm}: the rebuilt base prefix does not match the probe's recorded start")
        if row.get("draw_id") != s0["draw_id"]:
            raise SearchError(f"probe row pair {pair} {arm}: the key family differs from the rebuilt start's")
        burst = bytes.fromhex(row["words_hex"])
        if len(burst) != int(row["words_played"]):
            raise SearchError(f"probe row pair {pair} {arm} k {k}: words_hex is not words_played")
        arrivals = level_arrivals(int(row["level"]), row.get("breaks_after_start") or [])
        if not arrivals:
            continue
        if fa.stream_words(s0["draw_id"], k, len(burst)) != burst:
            raise SearchError(f"probe row pair {pair} {arm} k {k}: the recorded burst does not re-derive from its key family")
        st["bursts_rederived"] += 1
        st["multi_break_ticks"] += len(row["breaks_after_start"]) - len(arrivals)
        for lv, t in arrivals:
            if int((row.get("levels") or {}).get(str(lv), -1)) != t:
                raise SearchError(f"probe row pair {pair} {arm} k {k}: the break table and the levels reading disagree at level {lv}")
            st["level_arrivals"] += 1
            if lv >= mcell.TARGETS_TOTAL:
                st["clears_excluded"] += 1
                continue
            lead = beam.lead_of(lv, t)
            if lead is None or lead <= 0:
                st["behind_or_equal"] += 1
                continue
            n = t - len(base)
            if not 1 <= n <= len(burst):
                raise SearchError(f"probe row pair {pair} {arm} k {k}: level {lv} at tick {t} is outside the burst")
            if not all(bool(d.get("go")) for d in (row.get("decisions") or []) if int(d["words"]) < n):
                raise SearchError(f"probe row pair {pair} {arm} k {k}: a continuation before tick {t} was not a go")
            st["ahead"] += 1
            st["pairs_used"].add(pair)
            s, fresh = beam.new_start(base + burst[:n], lv, t, {"kind": "probe", "pair": pair, "arm": arm, "k": k, "cid": int(row["cid"]), "start_tick": len(base)},
                                      seed={"draw_id": s0["draw_id"], "k": k, "base": base, "base_words": len(base), "base_digest": mcell.words_digest(base),
                                            "end": tuple(s0[arm]["end"]), "end_digest": bytes(s0[arm]["end_digest"]), "chain": bytes(s0[arm]["chain"]), "n": n})
            if not fresh:
                st["same_words"] += 1
    st["pairs_used"] = len(st["pairs_used"])
    initial = beam.initial()
    per: Dict[int, Dict[str, Any]] = {}
    for s in initial:
        d = per.setdefault(s.level, {"starts": 0, "best_lead": None, "best_tick": None, "reference": beam.arrival[s.level], "top": []})
        d["starts"] += 1
        if d["best_lead"] is None or s.lead > d["best_lead"]:
            d["best_lead"], d["best_tick"] = s.lead, s.tick
        if len(d["top"]) < 5:
            d["top"].append({"sid": s.sid, "tick": s.tick, "lead": s.lead, "origin": s.origin})
    digest = hashlib.sha256("".join(f"{s.sid}:{s.digest}:{s.level}:{s.tick};" for s in initial).encode()).hexdigest()
    fit = throughput_fit(probe["rows"], probe["summary"], probe["config"])
    plan = {"mode": "lab", "contract": SEARCH_CONTRACT, "utc": g.utc(), "archive_id": lab.archive_id,
            "rule": "frontier_start_v1: every level arrival recorded by the trail-lead probe with tick < the reference's arrival at that level, at a live "
                    "level, with its exact prefix (the probe start's rebuilt base words + the recorded burst words up to the arrival); one start per "
                    "distinct prefix; cell-key dedup (earliest arrival) after the native seed; order (level desc, lead desc)",
            "probe": {"dir": str(probe["dir"]), "contract": pp["contract"], "utc": pp.get("utc"), "start_set_digest": pp["start_set_digest"],
                      "leads": pp.get("leads"), "rows": len(probe["rows"]), "lab_code_digest": probe["config"].get("lab_code_digest"),
                      "probe_file_sha256": probe["config"].get("probe_file_sha256")},
            "route": {k: pp["route"][k] for k in ("words", "digest", "completion_input_tick", "completion_time_passed", "final_chain")},
            "arrival_by_level": arrival, "params": params.as_dict(), "arm": {ARM_NAME: ARM}, "flags_explore": fv.FLAGS_EXPLORE, "flags_verify": fv.FLAGS_VERIFY,
            "starts": len(initial), "seed_ticks": sum(s.tick for s in initial), "stats": st,
            "per_level": {str(lv): d for lv, d in sorted(per.items(), key=lambda kv: -kv[0])}, "start_set_digest": digest, "throughput_fit": fit}
    return {"plan": plan, "beam": beam, "P": P}


def start_row(s: Start) -> Dict[str, Any]:
    """One starts.jsonl row: identity, lengths and digests, no raw words."""
    return s.row(words=False)


def load_all(lab_root: Path, analyse: fv.Analyse = fv.real_analyse) -> Tuple[Any, Dict[str, Any], Dict[str, Any]]:
    return tp.load_all(Path(lab_root), analyse)


# -- per-dispatch readings -------------------------------------------------------------------------------------------------------------------


def dispatch_row(info: Mapping[str, Any], s: Start, res: Mapping[str, Any], arrival: Mapping[int, int]) -> Dict[str, Any]:
    """One dispatches.jsonl row from a finished job: the start's identity, the levels reached with their ticks and pace (the reference's
    arrival minus the dispatch's; positive = ahead), the end reason, the words played, the claim of a clear."""
    L, n = int(res["L"]), len(res["words"])
    breaks = sorted((int(t), int(i)) for t, i in res["breaks_all"])
    pre = [b for b in breaks if b[0] <= L]
    post = [b for b in breaks if b[0] > L]
    seed = info["kind"] == SEED                       # a seed's prefix is the probe start's base, its burst ends at the arrival: the level after both is the start's
    levels = {str(lv): t for lv, t in level_arrivals(len(pre), post)}          # one state per break tick, at the level after every break of that tick
    pace = {lv: int(arrival[int(lv)]) - t for lv, t in levels.items() if int(lv) in arrival}
    end = tp.END_NAMES.get(str(res["end_reason"]), str(res["end_reason"]))
    rj = res.get("result_json") or {}
    return {"round": info["round"], "kind": info["kind"], "sid": s.sid, "k": info["k"], "bonus": bool(info.get("bonus")), "level": s.level, "start_tick": L,
            "lead": s.lead, "draw_id": info["draw_id"], "outcome": end, "words_played": n, "ticks": int(res["ticks"]), "deepest": len(pre) + len(post),
            "advanced": len(post) > 0, "breaks_after_start": [list(b) for b in post], "levels": levels, "pace": pace,
            "prefix_breaks": len(pre), "prefix_level_ok": (len(pre) + len(post) == s.level) if seed else (len(pre) == s.level), "reaches": len(res["reaches"]),
            "segments": res.get("segments"),
            "decisions": res.get("decisions"), "tick0_equal": (res.get("tick0") or {}).get("equal"),
            "prefix_host_frame_equal": (res.get("prefix") or {}).get("host_frame_equal"), "mode": res.get("mode"), "worker": res.get("worker"),
            "wall_s": res.get("wall_s"), "step_s": res.get("step_s"), "ask_s": res.get("ask_s"), "words_hex": bytes(res["words"]).hex(),
            "final_chain": res.get("final_chain") if end == "clear" else None,
            "claimed": {"completion_input_tick": rj.get("completion_input_tick"), "completion_time_passed": rj.get("completion_time_passed")}
            if end == "clear" else None}


def clear_row(cand: Mapping[str, Any], out: Mapping[str, Any], ref_t: int) -> Dict[str, Any]:
    """One verifications.jsonl row from rl/frs_verify.verify_twice's result: both replays' clocks, chain digests and break tables, the verdict,
    and whether a VERIFIED clear is faster than the reference. Only a VERIFIED row is ever a clear."""
    r1, r2 = out.get("r1") or {}, out.get("r2") or {}
    cit = out.get("completion_input_tick")
    return {"mode": "lab", "kind": "clear", "round": cand["round"], "sid": cand["sid"], "k": cand["k"], "level": cand["level"], "start_tick": cand["start_tick"],
            "lead": cand["lead"], "words": len(cand["words"]), "words_hex": bytes(cand["words"]).hex(), "words_digest": cand["claim"]["words_digest"],
            "verdict": out["verdict"], "reasons": list(out.get("reasons") or []), "completion_input_tick": cit,
            "completion_time_passed": out.get("completion_time_passed"), "chain_r1": r1.get("final_chain"), "chain_r2": r2.get("final_chain"),
            "clocks_r1": [r1.get("completion_input_tick"), r1.get("completion_time_passed")],
            "clocks_r2": [r2.get("completion_input_tick"), r2.get("completion_time_passed")], "breaks_r1": r1.get("breaks"), "breaks_r2": r2.get("breaks"),
            "claim": dict(cand["claim"]), "errors": out.get("errors"), "wall_s": out.get("wall_s"),
            "faster_than_reference": bool(out["verdict"] == fv.VERIFIED and cit is not None and int(cit) < int(ref_t)),
            "gain_vs_reference": (int(ref_t) - int(cit)) if (out["verdict"] == fv.VERIFIED and cit is not None) else None,
            "reference_completion_input_tick": int(ref_t)}


# -- the engine --------------------------------------------------------------------------------------------------------------------------------


@dataclass
class SearchConfig:
    lab_root: Path
    out: Path
    run_dir: Path
    probe_dir: Path
    n_workers: int = 5
    max_ticks: int = 60_000_000
    max_wall_s: float = 360 * 60.0
    expect_code: Optional[str] = None            # the probe's lab code digest: the run refuses to start on other lab code
    job_timeout_s: float = mrun.JOB_TIMEOUT_S
    stop_grace_s: float = 60.0
    verify_parallel: int = 5
    mismatch_limit: int = 3
    seed_failure_limit: int = 3
    lifecycle_limit: int = mrule.MAX_LIFECYCLE_FAILURES
    progress_every_s: float = 60.0
    write_reserve_s: float = 60.0
    verify_s_per_clear: float = 30.0             # wall reserved per pending clear at the close (two fresh-process replays); an estimate, never a cap
    verify_floor_s: float = 180.0


class Search:
    def __init__(self, cfg: SearchConfig, env: fr.LabEnv, lab: Any, meta: Mapping[str, Any], R: Mapping[str, Any], plan: Mapping[str, Any], params: Params):
        self.cfg, self.env, self.lab, self.R, self.p = cfg, env, lab, R, params
        self.plan: Dict[str, Any] = dict(plan["plan"])
        self.beam: Beam = plan["beam"]
        self.fs = g.LabFS(cfg.lab_root)
        self.dir = Path(cfg.run_dir)
        self.pin = dict(meta["pin_tick0"])
        self.arrival: Dict[int, int] = {int(k): int(v) for k, v in R["arrival"].items()}
        self.ref_t = int(R["expected"]["completion_input_tick"])
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
        self.queue: Deque[Tuple[str, int, int, bool]] = deque()
        self.inflight: Dict[int, Dict[str, Any]] = {}
        self.round = 0
        self.round_t = self.t0
        self.round_cands: List[Start] = []
        self.round_c: Dict[str, Any] = {}
        self.rounds: List[Dict[str, Any]] = []
        self.seed_stats = {"starts": 0, "ok": 0, "dropped": 0, "held": 0, "later": 0, "supersedes": 0, "reasons": {}}
        self.c = {"dispatches": 0, "jobs": 0, "seed_jobs": 0, "burst_jobs": 0, "bonus_jobs": 0, "ticks": 0, "prefix_ticks": 0, "burst_ticks": 0,
                  "reference_ticks": 0, "verify_ticks": 0, "mismatches": 0, "seed_failures": 0, "lifecycle_failures": 0, "aborted": 0, "skipped": 0,
                  "tick0_unequal": 0, "boundaries": 0, "continued": 0, "advanced": 0, "bonus_advanced": 0, "base_jobs": 0, "base_advanced": 0,
                  "ahead_reaches": 0, "placed": 0, "clears_claimed": 0}
        self.per_level: Dict[str, Dict[str, int]] = {}
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
        self._last_progress = self.t0
        self._lock = threading.Lock()

    # -- bookkeeping ------------------------------------------------------------------------------------------------------------------------

    def log(self, s: str) -> None:
        self.env.log(f"frontier: {s}")
        try:
            self.fs.append_jsonl(self.dir / "run_log.jsonl", {"t_s": round(self.env.now() - self.t0, 1), "phase": self.phase, "round": self.round, "msg": s[:2000]})
        except (OSError, g.LabRootError):
            pass

    def mark(self, status: str, reason: str, *, abort: bool = False) -> None:
        if STATUS_RANK[status] > STATUS_RANK[self.status]:
            self.status = status
        self.notes.append(f"{status}: {reason}"[:600])
        if not self.stopping:
            self.stopping = True
            self.stop_reason = reason[:600]
        if abort and self.pool is not None:
            self.pool.abort.set()
        if status not in ("COMPLETED", "FRONTIER_EMPTY"):
            self.log(f"{status}: {reason}")

    def elapsed(self) -> float:
        return self.env.now() - self.t0

    def used_ticks(self) -> int:
        return self.c["ticks"] + self.c["reference_ticks"] + self.c["verify_ticks"]

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

    # -- run ------------------------------------------------------------------------------------------------------------------------------------

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

    # -- open -------------------------------------------------------------------------------------------------------------------------------------

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
        if not self.beam.initial():
            raise Refused("no start: the probe recorded no level arrival ahead of the reference")
        self.code = env.code_manifest()
        self.code_dig = fr.code_digest(self.code)
        if cfg.expect_code and self.code_dig != cfg.expect_code:
            raise Refused(f"lab code digest {self.code_dig[:16]} differs from the probe's {cfg.expect_code[:16]}")
        self.fs.mkdir(self.dir)
        self.fs.write_json(self.dir / "config.json", self.config_record(ready))
        self.sampler = fm.Sampler(lambda r: self.fs.append_jsonl(self.dir / "memory.jsonl", r), interval=env.sample_s, row_every=env.row_every_s,
                                  caps=env.caps or fm.CAPS_MB, soft=env.soft, snapshot=env.snapshot, now=env.now,
                                  extra=lambda: {"cells": len(self.beam.starts), "phase": self.phase, "round": self.round, "dispatches": self.c["dispatches"],
                                                 "jobs": self.c["jobs"]}).start()
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
        self.pool = fr.FrsPool(env.worker_spec, env.now)
        self.pool.start(cfg.n_workers)
        self.phase_wall["open"] = round(env.now() - self.t0, 1)
        self.log(f"open done in {self.phase_wall['open']:.0f} s; {cfg.n_workers} workers ready; {len(self.beam.initial())} initial starts to seed; "
                 f"params {self.p.as_dict()}; arm {ARM_NAME} {ARM}")
        self.write_progress()

    def config_record(self, ready: Mapping[str, Any]) -> Dict[str, Any]:
        c = self.cfg
        return {"mode": "lab", "contract": SEARCH_CONTRACT, "utc": g.utc(), "search_file_sha256": g.sha256_file(Path(__file__).resolve()),
                "probe_file_sha256": g.sha256_file(Path(tp.__file__).resolve()), "lab_code_digest": self.code_dig, "lab_code_files": len(self.code),
                "expect_code": c.expect_code, "arm": ARM_NAME, "arm_params": ARM, "params": self.p.as_dict(), "n_workers": c.n_workers, "max_ticks": c.max_ticks,
                "max_wall_s": c.max_wall_s, "job_timeout_s": c.job_timeout_s, "mismatch_limit": c.mismatch_limit, "seed_failure_limit": c.seed_failure_limit,
                "lifecycle_limit": c.lifecycle_limit, "verify_parallel_close": c.verify_parallel, "max_battleship_processes": fm.MAX_BATTLESHIP,
                "memory_caps_mb": dict(self.env.caps or fm.CAPS_MB), "memory_soft_budget_mb": dict(self.env.soft or fm.soft_budget(self.env.caps or fm.CAPS_MB)),
                "readiness": ready, "flags_explore": fv.FLAGS_EXPLORE, "flags_verify": fv.FLAGS_VERIFY, "backend": self.env.backend,
                "import": str(Path(c.lab_root) / "import"), "probe": self.plan["probe"], "start_set_digest": self.plan["start_set_digest"],
                "starts": self.plan["starts"], "seed_ticks": self.plan["seed_ticks"], "reference": self.plan["route"],
                "origins": {"arm": "the lab's CONT arm (rl/frs_run.ARMS), unchanged", "starts": "frontier_start_v1 (this file) on the probe's rows",
                            "draw_id": "<archive id>|frontier|<prefix words digest>, iteration k = the start's dispatch count (seeds: the probe's own key family and k)",
                            "caps": f"owner, 2026-10-14: at most {c.max_wall_s / 60.0:g} minutes and {c.max_ticks:,} ticks", "readiness": "registered thresholds, never lowered",
                            "params": "owner-approved arguments (B, F, share, bonus, retirement, candidate mode, reserve)"}}

    # -- the search: seed, then rounds ---------------------------------------------------------------------------------------------------------

    def search_phase(self) -> None:
        self.t_search = self.env.now()
        self.phase = SEED
        self.round = 0
        self.round_t = self.env.now()
        for s in self.beam.initial():
            self.queue.append((SEED, s.sid, int(s.seed["k"]), False))
        self.run_queue()
        if self.stopping and self.seed_stats["ok"] == 0:
            return
        self.finish_seed()
        while not self.stopping:
            self.round += 1
            self.phase = "round"
            self.round_t = self.env.now()
            self.round_cands = []
            self.round_c = {"reaches": 0, "ahead": 0, "same_words": 0, "held": 0, "later": 0, "supersedes": 0, "terminal": 0, "dispatches": 0, "jobs": 0,
                            "bonus_jobs": 0, "advanced": 0, "bonus_advanced": 0, "clears": 0, "ticks": 0, "skipped": 0}
            bonus_starts = 0
            for sid in list(self.beam.frontier):
                s = self.beam.starts[sid]
                n_bursts = self.p.bursts_for(s.breaks)
                bonus_starts += int(n_bursts > self.p.bursts)
                for i in range(n_bursts):
                    self.queue.append((BURST, sid, s.next_k, i >= self.p.bursts))
                    s.next_k += 1
            self.round_c["bonus_starts"] = bonus_starts
            self.round_c["frontier_in"] = len(self.beam.frontier)
            self.round_c["per_level_in"] = self.beam.per_level(self.beam.frontier)
            self.log(f"round {self.round}: {len(self.beam.frontier)} starts ({bonus_starts} with a break record), {len(self.queue)} bursts queued; "
                     f"per level {json.dumps({lv: d['starts'] for lv, d in self.round_c['per_level_in'].items()})}")
            self.run_queue()
            self.finish_round()
            if not self.stopping and self.p.max_rounds and self.round >= self.p.max_rounds:
                self.mark("COMPLETED", f"{self.p.max_rounds} rounds done")
            elif not self.stopping and not self.beam.frontier:
                self.mark("FRONTIER_EMPTY", "no start left to dispatch from (every known state retired, superseded or dropped)")
        self.search_wall = self.env.now() - self.t_search

    def run_queue(self) -> None:
        """Dispatch the queue through the pool until it is empty and nothing is in flight (or a stop is marked, then drain)."""
        pool = self.pool
        assert pool is not None
        while True:
            for w, kind, payload in pool.poll2(0.2, self.on_boundary):
                self.handle(w, kind, payload)
            self.checks()
            self.verification_step()
            if self.stopping:
                break
            if not self.queue and not pool.busy:
                break
            for w in pool.idle():
                if w == self.lent:
                    continue
                job = self.next_job(w)
                if job is None:
                    break
                pool.send(w, job)
            self.progress()
        if self.stopping:
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
        elif pool.oldest_age() > cfg.job_timeout_s:
            self.mark("SEARCH_INCOMPLETE", f"a job has been in flight for more than {cfg.job_timeout_s:.0f} s", abort=True)
        elif not [i for i, pr in enumerate(pool.procs) if pr.is_alive() and i not in pool.retired]:
            self.mark("SEARCH_INCOMPLETE", "no live worker is left", abort=True)

    def next_job(self, w: int) -> Optional[Dict[str, Any]]:
        cfg = self.cfg
        while self.queue:
            kind, sid, k, bonus = self.queue[0]
            s = self.beam.starts[sid]
            if kind == SEED:
                if s.seed is None or s.dropped is not None:
                    self.queue.popleft()
                    self.c["skipped"] += 1
                    continue
                sd = s.seed
                words, end, ed, ch, draw, want = sd["base"], sd["end"], sd["end_digest"], sd["chain"], sd["draw_id"], s.tick
            else:
                if not s.alive() or s.words is None:
                    self.queue.popleft()
                    self.c["skipped"] += 1
                    self.round_c["skipped"] = self.round_c.get("skipped", 0) + 1
                    continue
                words, end, ed, ch, draw = s.words, s.end, s.end_digest, s.chain, s.draw_id(self.beam.archive_id)
                want = s.tick + min(ARM["segment_words"] * ARM["max_segments"], mcell.HORIZON - s.tick)
            if self.used_ticks() + self.reserved + want + self.verify_ticks_pending() > cfg.max_ticks:
                self.mark("TICK_CAP", f"the tick cap {cfg.max_ticks:,} would be exceeded by the next dispatch")
                return None
            self.queue.popleft()
            job = {"kind": fw.JOB_KIND, "iteration": k, "cell": sid, "rep": (sid, s.tick), "words": bytes(words), "end": tuple(end), "end_digest": bytes(ed),
                   "chain": bytes(ch), "terminal": False, "pin": self.pin, "archive_id": draw, "allowance": int(want), **ARM}
            self.inflight[w] = {"kind": kind, "sid": sid, "k": k, "bonus": bonus, "round": self.round, "draw_id": draw, "reserved": int(want), "cont": []}
            self.reserved += int(want)
            self.c["dispatches"] += 1
            if kind == BURST:
                self.round_c["dispatches"] += 1
            return job
        return None

    def on_boundary(self, w: int, payload: Dict[str, Any]) -> None:
        info = self.inflight.get(w)
        aborting = self.pool is not None and self.pool.abort.is_set()
        if aborting or info is None or info["k"] != int(payload["iteration"]):
            d: Dict[str, Any] = {"go": False, "stopping": True}
        elif info["kind"] == SEED:
            d = {"go": True, "seed": True}                     # a seed replays the recorded words: every boundary before the arrival was a go
        else:
            d = self.lab.continuation_decision(payload["reaches"])
        go = bool(d["go"])
        if info is not None and info["kind"] == BURST:            # the continuation rate is the explorer's (a seed replays recorded words)
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
        s = self.beam.starts[info["sid"]]
        if payload.get("ok"):
            self.commit(info, s, payload)
            return
        kd = payload.get("kind")
        base = {"round": info["round"], "kind": info["kind"], "sid": s.sid, "k": info["k"], "bonus": bool(info["bonus"]), "level": s.level, "start_tick": s.tick,
                "lead": s.lead, "draw_id": info["draw_id"], "advanced": False, "deepest": s.level, "ticks": 0, "words_played": 0}
        if kd == "mismatch":
            self.emit(dict(base, outcome="mismatch", mismatch=payload.get("mismatch"), detail=json.dumps(payload.get("detail"), default=str)[:800]))
            if payload.get("mismatch") in fa.QUARANTINE_KINDS:
                self.c["mismatches"] += 1
                if info["kind"] == SEED:
                    self.drop_seed(s, f"base prefix {payload.get('mismatch')}")
                else:
                    s.retired = f"round {info['round']}: prefix mismatch {payload.get('mismatch')}"
                    s.words = None
                    self.beam.counts["retired"] += 1
                self.log(f"start {s.sid} (level {s.level}, tick {s.tick}) quarantined: its prefix did not reproduce ({payload.get('mismatch')})")
                if self.c["mismatches"] > self.cfg.mismatch_limit:
                    self.mark("SEARCH_INVALID", f"{self.c['mismatches']} prefix mismatches > {self.cfg.mismatch_limit}", abort=True)
            else:
                self.mark("SEARCH_INVALID", f"start {s.sid} {info['kind']} k {info['k']}: mismatch {payload.get('mismatch')} "
                                            f"{json.dumps(payload.get('detail'), default=str)[:400]}", abort=True)
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

    def drop_seed(self, s: Start, why: str) -> None:
        s.dropped = f"seed: {why}"
        s.words = None
        self.c["seed_failures"] += 1
        self.seed_stats["dropped"] += 1
        self.seed_stats["reasons"][why[:60]] = self.seed_stats["reasons"].get(why[:60], 0) + 1
        if self.c["seed_failures"] > self.cfg.seed_failure_limit:
            self.mark("SEARCH_INVALID", f"{self.c['seed_failures']} seeds did not reproduce the probe's record > {self.cfg.seed_failure_limit}", abort=True)

    def commit(self, info: Mapping[str, Any], s: Start, res: Mapping[str, Any]) -> None:
        row = dispatch_row(info, s, res, self.arrival)
        row["cont"] = list(info["cont"])
        n = len(res["words"])
        self.c["jobs"] += 1
        self.c["ticks"] += int(res["ticks"])
        self.c["burst_ticks"] += n
        self.c["prefix_ticks"] += int(res["ticks"]) - n
        if not (res.get("tick0") or {}).get("equal", True):
            self.c["tick0_unequal"] += 1
        if info["kind"] == SEED:
            self.c["seed_jobs"] += 1
            row["seed"] = self.seed_result(s, res)
            self.emit(row)
            return
        self.c["burst_jobs"] += 1
        self.round_c["jobs"] += 1
        self.round_c["ticks"] += int(res["ticks"])
        s.dispatched += 1
        advanced = bool(row["advanced"])
        if advanced:
            s.breaks += 1
            s.since_break = 0
            self.c["advanced"] += 1
            self.round_c["advanced"] += 1
        else:
            s.since_break += 1
        if info["bonus"]:
            s.bonus_dispatches += 1
            self.c["bonus_jobs"] += 1
            self.round_c["bonus_jobs"] += 1
            self.c["bonus_advanced"] += int(advanced)
            self.round_c["bonus_advanced"] += int(advanced)
        else:
            self.c["base_jobs"] += 1
            self.c["base_advanced"] += int(advanced)
        pl = self.per_level.setdefault(str(s.level), {"jobs": 0, "advanced": 0, "falls": 0, "clears": 0, "ahead_reaches": 0, "placed": 0, "deepest": s.level})
        pl["jobs"] += 1
        pl["advanced"] += int(advanced)
        pl["falls"] += int(row["outcome"] == "fall")
        pl["clears"] += int(row["outcome"] == "clear")
        pl["deepest"] = max(pl["deepest"], int(row["deepest"]))
        cands: List[Start] = []
        if s.words is not None and n > 0:
            cands, c = self.beam.candidates(s, res, info["round"], info["k"])
            for key, v in c.items():
                self.round_c[key] = self.round_c.get(key, 0) + v
            self.c["ahead_reaches"] += c["ahead"]
            self.c["placed"] += c["held"] + c["supersedes"]
            pl["ahead_reaches"] += c["ahead"]
            pl["placed"] += c["held"] + c["supersedes"]
            row["candidates"] = {"ahead": c["ahead"], "held": c["held"], "supersedes": c["supersedes"], "later": c["later"], "same_words": c["same_words"],
                                 "sids": [x.sid for x in cands][:64], "deepest": max((x.level for x in cands), default=None)}
            self.round_cands.extend(cands)
        self.emit(row)
        if row["outcome"] == "clear" and n > 0:
            words = bytes(s.words or b"") + bytes(res["words"])
            claim = {"words_digest": mcell.words_digest(words), "completion_input_tick": row["claimed"]["completion_input_tick"],
                     "completion_time_passed": row["claimed"]["completion_time_passed"], "chain": res.get("final_chain")}
            self.c["clears_claimed"] += 1
            self.round_c["clears"] += 1
            self.vqueue.append({"kind": "clear", "round": info["round"], "sid": s.sid, "k": info["k"], "level": s.level, "start_tick": s.tick, "lead": s.lead,
                                "words": words, "claim": claim})
            self.vqueue.sort(key=lambda c: (c["claim"]["completion_input_tick"] or 10 ** 9, c["round"], c["sid"], c["k"]))
            self.log(f"clear candidate: round {info['round']} start {s.sid} (level {s.level}, tick {s.tick}) k {info['k']}, {len(words):,} words (claimed "
                     f"{claim['completion_input_tick']} / {claim['completion_time_passed']}, reference {self.ref_t}); queued for verification")
            self.write_progress()

    def seed_result(self, s: Start, res: Mapping[str, Any]) -> Dict[str, Any]:
        """The seed replayed the probe start's base prefix and the recorded burst words up to the arrival tick: the words played must be the
        recorded ones, the arrival a break at the recorded level, and the reach at that tick gives the state's key and end record."""
        sd = s.seed
        assert sd is not None and s.words is not None
        out: Dict[str, Any] = {"ok": False, "n": sd["n"], "played": len(res["words"])}
        played = bytes(res["words"])
        if played != s.words[len(sd["base"]):]:
            out["why"] = "the burst words played differ from the recorded ones"
        elif s.tick not in {int(t) for t, _i in res["breaks_all"]}:
            out["why"] = f"no break at the recorded arrival tick (end {res['end_reason']})"
        else:
            hit = [r for r in res["reaches"] if int(r[0]) == s.tick]
            if not hit:
                out["why"] = f"no reach at the recorded arrival tick (end {res['end_reason']})"
            else:
                j, key, obs, rd, chain, terminal = hit[0]
                k = fa.norm_key(key)
                if terminal:
                    out["why"] = "the arrival state is terminal"
                elif mcell.level_of_mask(k[3]) != s.level:
                    out["why"] = f"the arrival's level {mcell.level_of_mask(k[3])} is not the recorded {s.level}"
                else:
                    verdict = self.beam.place(s, k, tuple(obs), bytes(rd), bytes(chain))
                    out.update({"ok": True, "verdict": verdict, "key": list(k)})
        if out["ok"]:
            self.seed_stats["ok"] += 1
            self.seed_stats[out["verdict"]] += 1
        else:
            self.drop_seed(s, out["why"])
            self.log(f"seed of start {s.sid} (level {s.level}, tick {s.tick}, {s.origin}) dropped: {out['why']}")
        s.seed = dict(sd, base=b"")                                   # the base prefix is not needed again (the start's own words are its prefix)
        return out

    def finish_seed(self) -> None:
        self.seed_stats["starts"] = len(self.beam.initial())
        seeded = [s for s in self.beam.initial() if s.alive()]
        self.beam.select(seeded, [])
        self.beam.evict()
        self.write_frontier(1)
        row = {"round": 0, "kind": SEED, "utc": g.utc(), "wall_s": round(self.env.now() - self.round_t, 1), "starts": self.seed_stats["starts"],
               "seeded": self.seed_stats["ok"], "dropped": self.seed_stats["dropped"], "held": self.seed_stats["held"], "later": self.seed_stats["later"],
               "supersedes": self.seed_stats["supersedes"], "distinct_keys": len({s.key for s in seeded}), "reasons": self.seed_stats["reasons"],
               "frontier_out": len(self.beam.frontier), "per_level_out": self.beam.per_level(self.beam.frontier), "reserve": len(self.beam.reserve()),
               "best_by_level": self.beam.best_by_level(), "ticks": self.c["ticks"], "dispatches": self.c["seed_jobs"]}
        self.rounds.append(row)
        self.fs.append_jsonl(self.dir / "rounds.jsonl", row)
        self.log(f"seed done in {row['wall_s']:.0f} s: {row['seeded']} of {row['starts']} starts seeded ({row['dropped']} dropped), {row['distinct_keys']} distinct "
                 f"keys ({row['later']} later arrivals dropped, {row['supersedes']} superseded); frontier 1 = {row['frontier_out']} starts, reserve {row['reserve']}; "
                 f"per level {json.dumps({lv: d['starts'] for lv, d in row['per_level_out'].items()})}")
        self.write_progress()
        if not self.beam.frontier and not self.stopping:
            self.mark("FRONTIER_EMPTY", "no seeded start holds a key")

    def finish_round(self) -> None:
        rc = self.round_c
        retired = self.beam.retire(self.round)
        prev = list(self.beam.frontier)
        prev_alive = sum(1 for i in prev if self.beam.starts[i].alive())
        nxt = self.beam.select(self.round_cands, prev)
        evicted = self.beam.evict()
        swept = self.beam.sweep()
        kept = [i for i in nxt if i in prev]
        deepest = max((s.level for s in self.round_cands if s.alive()), default=None)
        best_round: Dict[str, Any] = {}
        for s in self.round_cands:
            if not s.alive():
                continue
            b = best_round.get(str(s.level))
            if b is None or s.lead > b["lead"]:
                best_round[str(s.level)] = {"lead": s.lead, "tick": s.tick, "sid": s.sid, "parent": s.origin.get("parent")}
        row = {"round": self.round, "kind": BURST, "utc": g.utc(), "wall_s": round(self.env.now() - self.round_t, 1), "frontier_in": rc.get("frontier_in"),
               "per_level_in": rc.get("per_level_in"), "bonus_starts": rc.get("bonus_starts"), "dispatches": rc.get("dispatches", 0), "jobs": rc.get("jobs", 0),
               "bonus_jobs": rc.get("bonus_jobs", 0), "advanced": rc.get("advanced", 0), "bonus_advanced": rc.get("bonus_advanced", 0), "skipped": rc.get("skipped", 0),
               "reaches": rc.get("reaches", 0), "ahead": rc.get("ahead", 0), "same_words": rc.get("same_words", 0), "held": rc.get("held", 0),
               "supersedes": rc.get("supersedes", 0), "later": rc.get("later", 0), "candidates": sum(1 for s in self.round_cands if s.alive()),
               "deepest_candidate": deepest, "best_by_level_round": dict(sorted(best_round.items(), key=lambda kv: -int(kv[0]))),
               "clears_claimed": rc.get("clears", 0), "retired": [{"sid": s.sid, "level": s.level, "tick": s.tick, "dispatched": s.dispatched} for s in retired],
               "frontier_out": len(nxt), "kept_from_previous": len(kept), "previous_alive": prev_alive, "per_level_out": self.beam.per_level(nxt),
               "reserve": len(self.beam.reserve()), "evicted": evicted, "swept": swept, "best_by_level": self.beam.best_by_level(), "ticks": rc.get("ticks", 0),
               "ticks_total": self.used_ticks(),
               "elapsed_s": round(self.elapsed(), 1), "beam": self.beam.stats()}
        self.rounds.append(row)
        self.fs.append_jsonl(self.dir / "rounds.jsonl", row)
        self.write_frontier(self.round + 1)
        self.log(f"round {self.round} done in {row['wall_s']:.0f} s: {row['jobs']} jobs, {row['advanced']} advanced, {row['ahead']} ahead reaches -> {row['candidates']} "
                 f"candidates (deepest {deepest}), {len(retired)} retired, frontier {row['frontier_out']} ({len(kept)} kept), reserve {row['reserve']}; "
                 f"per level {json.dumps({lv: d['starts'] for lv, d in row['per_level_out'].items()})}; clears verified {len(self.verified_clears())}")
        self.write_progress()

    def write_frontier(self, rnd: int) -> None:
        """The frontier that round `rnd` will dispatch from, with every member's exact prefix (hex) and end record digests."""
        rows = [self.beam.starts[i].row(words=True) for i in self.beam.frontier]
        self.fs.write_text(self.dir / "frontier" / f"round_{rnd:04d}.jsonl", "".join(json.dumps(r, separators=(",", ":"), default=str) + "\n" for r in rows))

    def progress(self, force: bool = False) -> None:
        now = self.env.now()
        if not force and now - self._last_progress < self.cfg.progress_every_s:
            return
        self._last_progress = now
        mb = (self.sampler.last or {}).get("main_private_mb") if self.sampler else None
        ex = max(1e-9, now - self.t_search)
        self.log(f"t {self.elapsed():.0f}s round {self.round} dispatches {self.c['dispatches']:,} jobs {self.c['jobs']:,} ({3600.0 * self.c['jobs'] / ex:,.0f}/h) "
                 f"advanced {self.c['advanced']:,} ticks {self.used_ticks():,} ({3600.0 * self.c['ticks'] / ex / 1e6:.2f} M/h) cont {self.c['continued']}/{self.c['boundaries']} "
                 f"states {len(self.beam.starts):,} clears claimed {self.c['clears_claimed']} verified {len(self.verified_clears())} queued {len(self.queue):,} "
                 f"in flight {len(self.pool.busy) if self.pool else 0} main MB {mb}")
        try:
            self.fs.write_json(self.dir / "state.json", {"mode": "lab", "utc": g.utc(), "phase": self.phase, "round": self.round, "elapsed_s": round(self.elapsed(), 1),
                                                          "counters": self.c, "status": self.status, "stop": self.stop_reason, "queued": len(self.queue),
                                                          "verification_queue": len(self.vqueue), "verifications": len(self.vrows), "beam": self.beam.stats()})
            self.write_progress()
        except OSError:
            pass

    # -- verification: a clear is replayed twice from tick 0 as soon as a worker can be lent (the lab runner's path) -------------------------------

    def verify_candidate(self, cand: Mapping[str, Any], slot: int) -> Dict[str, Any]:
        label = f"clear_r{cand['round']}_s{cand['sid']}_k{cand['k']}"
        try:
            out = fv.verify_twice(self.env.replay, self.env.analyse, cand["words"], cand["claim"], label, slot, trace_dir=self.dir / "traces")
        except Exception as exc:  # noqa: BLE001 - a crashed verification is an ERROR row, never a clear
            out = {"label": label, "verdict": fv.ERROR, "reasons": [f"{type(exc).__name__}: {exc}"[:300]], "r1": {}, "r2": {}, "errors": [],
                   "words": len(cand["words"]), "wall_s": None}
        return out

    def on_verified(self, cand: Mapping[str, Any], out: Mapping[str, Any]) -> None:
        r1, r2 = out.get("r1") or {}, out.get("r2") or {}
        self.c["verify_ticks"] += int(r1.get("ticks") or 0) + int(r2.get("ticks") or 0)
        row = clear_row(cand, out, self.ref_t)
        row["utc"] = g.utc()
        row["phase"] = self.phase
        self.vrows.append(row)
        self.fs.append_jsonl(self.dir / "verifications.jsonl", row)
        self.log(f"verification of round {cand['round']} start {cand['sid']} k {cand['k']}: {out['verdict']} {out.get('completion_input_tick')} / "
                 f"{out.get('completion_time_passed')} (reference {self.ref_t}; {'FASTER by ' + str(row['gain_vs_reference']) if row['faster_than_reference'] else 'not faster'})")
        if out["verdict"] == fv.NONDETERMINISTIC:
            self.mark("SEARCH_INVALID", f"round {cand['round']} start {cand['sid']} k {cand['k']}: a claimed clear did not replay exactly: {row['reasons'][:2]}")
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

                self.vthread = threading.Thread(target=work, name="frontier-verify", daemon=True)
                self.vthread.start()
        elif self.vthread is None and not self.vqueue and self.lent is not None:
            self.lent = None

    # -- drain, close ----------------------------------------------------------------------------------------------------------------------------

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
        self.phase_wall["drain"] = round(self.phase_wall.get("drain", 0.0) + env.now() - t, 1)

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
                self.unverified.append({"round": self.vbox["cand"]["round"], "sid": self.vbox["cand"]["sid"], "k": self.vbox["cand"]["k"],
                                        "words": len(self.vbox["cand"]["words"]), "why": "the in-run verification did not return"})
            self.vthread = None
        self.close_verifications()
        changed = [rel for rel, h in self.code.items() if (g.REPO / rel).is_file() and g.sha256_file(g.REPO / rel) != h]
        self.integrity.update({"guard_violations_main": list(g.LabGuard.violations)[:5], "lab_code_changed_during_run": changed,
                               "lab_code_digest_end": fr.code_digest(env.code_manifest()) if self.code else None, "lab_code_digest_expected": cfg.expect_code,
                               "battleship_left": left, "tick0_unequal_jobs": self.c["tick0_unequal"], "prefix_mismatches": self.c["mismatches"],
                               "seed_failures": self.c["seed_failures"], "reference_ok": self.reference.get("ok")})
        if left:
            self.mark("SEARCH_INCOMPLETE", f"BattleShip processes still alive after the close: {left}")
        self.phase_wall["close"] = round(env.now() - t, 1)
        self.write_summary()
        self.log(f"done: {self.status} ({self.stop_reason}); summary {self.dir / 'summary.json'}")

    def close_verifications(self) -> None:
        """Every pending clear candidate, up to verify_parallel at once (no worker is alive now), before the wall deadline."""
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
        self.unverified += [{"round": c["round"], "sid": c["sid"], "k": c["k"], "words": len(c["words"]), "claim": c["claim"], "why": "the close deadline"}
                            for c in queue]
        if self.unverified:
            self.log(f"{len(self.unverified)} clear candidates NOT verified before the deadline (never clears)")

    # -- the summary, the report and the progress file ------------------------------------------------------------------------------------------

    def summary(self) -> Dict[str, Any]:
        mem = self.sampler.report() if self.sampler is not None else {}
        series = [r for r in (self.sampler.series if self.sampler else []) if r.get("phase") in (SEED, "round")]
        soft_main = float((self.env.soft or fm.soft_budget(self.env.caps or fm.CAPS_MB))["main_private"])
        cap_main = float((self.env.caps or fm.CAPS_MB)["main_private"])
        wall = self.search_wall if self.search_wall else max(0.0, self.env.now() - self.t_search)
        proj = fm.projection(series, load_mb=float(series[0]["main_private_mb"]) if series else None, load_cells=len(self.lab.cells), explore_s=wall,
                             soft_main_mb=soft_main, cap_main_mb=cap_main)
        ex_h = max(1e-9, wall / 3600.0)
        verified = self.verified_clears()
        best = min(verified, key=lambda v: (v["completion_input_tick"], v["completion_time_passed"]), default=None)
        bj, ba, sj, sa = self.c["bonus_jobs"], self.c["bonus_advanced"], self.c["base_jobs"], self.c["base_advanced"]
        retired = [s for s in self.beam.starts if s.retired]
        return {"mode": "lab", "contract": SEARCH_CONTRACT, "status": self.status, "stop": {"reason": self.stop_reason, "notes": self.notes[:12]},
                "utc_start": self.utc_start, "utc_end": g.utc(), "folder": str(self.dir), "phase_wall_s": dict(self.phase_wall, search=round(wall, 1)),
                "elapsed_s": round(self.elapsed(), 1),
                "config": {"params": self.p.as_dict(), "n_workers": self.cfg.n_workers, "max_ticks": self.cfg.max_ticks, "max_wall_s": self.cfg.max_wall_s, "arm": ARM_NAME,
                           **ARM, "lab_code_digest": self.code_dig, "backend": self.env.backend, "start_set_digest": self.plan["start_set_digest"],
                           "probe": self.plan["probe"]},
                "work": dict(self.c, ticks_total=self.used_ticks(), queued_left=len(self.queue), rounds=self.round),
                "throughput": {"jobs_per_h": round(self.c["jobs"] / ex_h, 1), "ticks_per_h": round(self.c["ticks"] / ex_h), "burst_ticks_per_h": round(self.c["burst_ticks"] / ex_h),
                               "rounds_per_h": round(self.round / ex_h, 2), "continuation_rate": round(self.c["continued"] / self.c["boundaries"], 4) if self.c["boundaries"] else None},
                "seed": dict(self.seed_stats), "rounds": self.rounds, "per_level": dict(sorted(self.per_level.items(), key=lambda kv: -int(kv[0]))),
                "best_by_level": self.beam.best_by_level(), "frontier_final": self.beam.per_level(self.beam.frontier), "beam": self.beam.stats(),
                "effects": {"bonus": {"on": self.p.bonus > 0, "jobs": bj, "advanced": ba, "share": round(ba / bj, 4) if bj else None, "base_jobs": sj, "base_advanced": sa,
                                      "base_share": round(sa / sj, 4) if sj else None, "starts_with_breaks": sum(1 for s in self.beam.starts if s.breaks > 0)},
                            "retire": {"on": self.p.retire_after > 0, "starts": len(retired), "dispatches_consumed": sum(s.dispatched for s in retired),
                                       "with_breaks": sum(1 for s in retired if s.breaks > 0), "by_level": dict(sorted({str(lv): sum(1 for s in retired if s.level == lv)
                                                                                                                     for lv in {s.level for s in retired}}.items(), key=lambda kv: -int(kv[0])))}},
                "reference": dict(self.reference, completion_input_tick_expected=self.ref_t),
                "clears": {"candidates": len(self.vrows) + len(self.unverified), "verified": len(verified), "faster_than_reference": sum(1 for v in verified if v["faster_than_reference"]),
                           "reference_completion_input_tick": self.ref_t,
                           "best_verified": None if best is None else {k: best[k] for k in ("round", "sid", "k", "level", "start_tick", "completion_input_tick",
                                                                                              "completion_time_passed", "gain_vs_reference", "chain_r1", "chain_r2", "words_digest")},
                           "rows": [{k: v.get(k) for k in ("round", "sid", "k", "level", "start_tick", "lead", "words", "verdict", "completion_input_tick", "completion_time_passed",
                                                           "gain_vs_reference", "chain_r1", "chain_r2", "clocks_r1", "clocks_r2", "words_digest", "faster_than_reference", "reasons", "utc")}
                                    for v in self.vrows]},
                "unverified": self.unverified,
                "memory": {"peak": mem.get("peak"), "soft_breach": mem.get("soft_breach"), "hard_breach": mem.get("hard_breach"), "proc_breach": mem.get("proc_breach"),
                           "soft_budget_mb": mem.get("soft_budget_mb"), "projection": proj},
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


# -- rendering ---------------------------------------------------------------------------------------------------------------------------------


def _clear_lines(s: Mapping[str, Any]) -> List[str]:
    cl = s["clears"]
    lines = [f"Clears: {cl['candidates']} claimed, {cl['verified']} verified (two exact fresh-process replays from tick 0), {cl['faster_than_reference']} faster than the "
             f"reference ({frep.fmt(cl['reference_completion_input_tick'])}).", "",
             "| found (round, start, k) | level / start tick | verdict | completion_input_tick / completion_time_passed | against the reference | replay 1 chain | replay 2 chain | utc |",
             "|---|---|---|---|---|---|---|---|"]
    for v in cl["rows"]:
        vs = "-" if v.get("gain_vs_reference") is None else (f"{v['gain_vs_reference']} ticks FASTER" if v["gain_vs_reference"] > 0 else f"{-v['gain_vs_reference']} ticks slower"
                                                             if v["gain_vs_reference"] < 0 else "equal")
        lines.append(f"| {v['round']}, {v['sid']}, {v['k']} | {v['level']} / {frep.fmt(v['start_tick'])} | {v['verdict']} | {frep.fmt(v['clocks_r1'][0])} / {frep.fmt(v['clocks_r1'][1])} "
                     f"(replay 2: {frep.fmt(v['clocks_r2'][0])} / {frep.fmt(v['clocks_r2'][1])}) | {vs} | `{v['chain_r1']}` | `{v['chain_r2']}` | {v.get('utc')} |")
    if s.get("unverified"):
        lines.append(f"\nCandidates NOT verified (never clears): {json.dumps(s['unverified'], default=str)[:800]}")
    return lines


def _level_lines(s: Mapping[str, Any]) -> List[str]:
    lines = ["| level | reference arrival | best lead ever (tick) | from | frontier now: starts / best lead | dispatches from this level: jobs / advanced / falls / clears | ahead reaches / placed |",
             "|---|---|---|---|---|---|---|"]
    levels = sorted({int(lv) for lv in s["best_by_level"]} | {int(lv) for lv in s["frontier_final"]} | {int(lv) for lv in s["per_level"]}, reverse=True)
    for lv in levels:
        b = s["best_by_level"].get(str(lv)) or {}
        f = s["frontier_final"].get(str(lv)) or {}
        p = s["per_level"].get(str(lv)) or {}
        lines.append(f"| {lv} | {frep.fmt(b.get('reference'))} | {frep.fmt(b.get('lead'))} ({frep.fmt(b.get('tick'))}) | {json.dumps(b.get('origin'), default=str) if b else '-'} | "
                     f"{f.get('starts', 0)} / {frep.fmt(f.get('best_lead'))} | {p.get('jobs', 0)} / {p.get('advanced', 0)} / {p.get('falls', 0)} / {p.get('clears', 0)} | "
                     f"{p.get('ahead_reaches', 0)} / {p.get('placed', 0)} |")
    return lines


def _round_lines(rounds: Sequence[Mapping[str, Any]], last: Optional[int] = None) -> List[str]:
    lines = ["| round | frontier in (per level) | bonus starts | jobs (bonus) | advanced | ahead reaches | candidates | deepest candidate | best lead at the deepest level this round | retired | frontier out (kept) | reserve | clears claimed | wall s |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    rows = list(rounds)
    if last is not None and len(rows) > last:
        rows = rows[-last:]
    for r in rows:
        if r.get("kind") == SEED:
            lines.append(f"| 0 (seed) | {r['starts']} initial starts | - | {r['dispatches']} | - | - | {r['seeded']} seeded, {r['dropped']} dropped, {r['distinct_keys']} keys | "
                         f"{max((int(k) for k in r['per_level_out']), default='-')} | - | - | {r['frontier_out']} | {r['reserve']} | - | {frep.fmt(r['wall_s'], 0)} |")
            continue
        pl_in = ", ".join(f"{lv}: {d['starts']}" for lv, d in (r.get("per_level_in") or {}).items())
        dc = r.get("deepest_candidate")
        bl = (r.get("best_by_level_round") or {}).get(str(dc)) if dc is not None else None
        lines.append(f"| {r['round']} | {r['frontier_in']} ({pl_in}) | {r['bonus_starts']} | {r['jobs']} ({r['bonus_jobs']}) | {r['advanced']} | {r['ahead']} | {r['candidates']} | "
                     f"{frep.fmt(dc)} | {frep.fmt(bl['lead']) + ' (tick ' + frep.fmt(bl['tick']) + ')' if bl else '-'} | {len(r['retired'])} | {r['frontier_out']} ({r['kept_from_previous']}) | "
                     f"{r['reserve']} | {r['clears_claimed']} | {frep.fmt(r['wall_s'], 0)} |")
    return lines


def progress_md(s: Mapping[str, Any], *, final: bool) -> str:
    w, th, mem = s["work"], s["throughput"], s["memory"]
    peak = mem.get("peak") or {}
    state = f"**{s['status']}** ({s['stop']['reason']})" if final or s["stop"]["reason"] else "**RUNNING**"
    lines = [f"# Frontier continuation search: progress ({s['utc_start'][:10]})", "",
             f"{'Final. ' if final else ''}Status {state}. Updated {s['utc_end']}; elapsed {s['elapsed_s'] / 60.0:.0f} of {s['config']['max_wall_s'] / 60.0:g} min. "
             f"Round {w['rounds']}; dispatches {frep.fmt(w['dispatches'])} (seed {frep.fmt(w['seed_jobs'])}, bursts {frep.fmt(w['burst_jobs'])}, bonus {frep.fmt(w['bonus_jobs'])}); "
             f"ticks {frep.fmt(w['ticks_total'])} of {frep.fmt(s['config']['max_ticks'])}; {frep.fmt(th['jobs_per_h'], 0)} jobs / h, {frep.fmt(th['ticks_per_h'])} ticks / h, "
             f"{frep.fmt(th['rounds_per_h'], 1)} rounds / h. States known {frep.fmt(s['beam']['states'])} (alive {frep.fmt(s['beam']['alive'])}, frontier {s['beam']['frontier']}, "
             f"reserve {s['beam']['reserve']}, retired {s['beam']['retired']}). Main process {frep.fmt(peak.get('main_private_mb'), 0)} MB peak, tree "
             f"{frep.fmt(peak.get('tree_private_mb'), 0)} MB, BattleShip processes {peak.get('battleship')} peak.",
             f"Params: {json.dumps(s['config']['params'])}. Reference clear replayed exactly at open: {s['reference'].get('ok')} "
             f"({frep.fmt(s['reference'].get('completion_input_tick'))} / {frep.fmt(s['reference'].get('completion_time_passed'))}).", "",
             "## Verified clears", ""] + _clear_lines(s) + ["", "## Levels", ""] + _level_lines(s) + ["", "## Rounds (last 30)", ""] + _round_lines(s["rounds"], 30)
    lines += ["", f"Seed: {json.dumps(s['seed'], default=str)}", f"Effects: {json.dumps(s['effects'], default=str)}", ""]
    return "\n".join(lines)


def report_md(s: Mapping[str, Any]) -> str:
    w, th, mem, cl = s["work"], s["throughput"], s["memory"], s["clears"]
    peak = mem.get("peak") or {}
    lines = [f"# Frontier continuation search run ({s['utc_start'][:10]})", "",
             f"Lab, exploratory, unregistered (mode lab). Status **{s['status']}** ({s['stop']['reason']}). Arm {s['config']['arm']} (segments {s['config']['segment_words']} x "
             f"{s['config']['max_segments']}, F3 window {s['config']['window']}); params {json.dumps(s['config']['params'])}; {s['config']['n_workers']} workers.", "",
             "| measure | value |", "|---|---|",
             f"| wall / open / search / drain / close | {frep.fmt(s['elapsed_s'], 0)} s / {frep.fmt(s['phase_wall_s'].get('open'), 0)} s / {frep.fmt(s['phase_wall_s'].get('search'), 0)} s / "
             f"{frep.fmt(s['phase_wall_s'].get('drain'), 0)} s / {frep.fmt(s['phase_wall_s'].get('close'), 0)} s |",
             f"| rounds / dispatches / jobs (seed, bursts, bonus) / skipped / queued left | {w['rounds']} / {frep.fmt(w['dispatches'])} / {frep.fmt(w['jobs'])} ({frep.fmt(w['seed_jobs'])}, "
             f"{frep.fmt(w['burst_jobs'])}, {frep.fmt(w['bonus_jobs'])}) / {w['skipped']} / {frep.fmt(w['queued_left'])} |",
             f"| ticks: total / prefix / burst / reference / verification | {frep.fmt(w['ticks_total'])} / {frep.fmt(w['prefix_ticks'])} / {frep.fmt(w['burst_ticks'])} / "
             f"{frep.fmt(w['reference_ticks'])} / {frep.fmt(w['verify_ticks'])} |",
             f"| throughput: jobs / h, ticks / h, rounds / h, continuation rate | {frep.fmt(th['jobs_per_h'], 0)} / {frep.fmt(th['ticks_per_h'])} / {frep.fmt(th['rounds_per_h'], 2)} / "
             f"{frep.fmt(th['continuation_rate'], 3)} ({w['continued']} of {w['boundaries']}) |",
             f"| seed: starts / seeded / dropped / distinct keys (later, superseded) | {s['seed']['starts']} / {s['seed']['ok']} / {s['seed']['dropped']} / "
             f"{s['seed']['held'] + s['seed']['supersedes']} ({s['seed']['later']}, {s['seed']['supersedes']}) |",
             f"| states known / placed / alive / retired / superseded / evicted | {frep.fmt(s['beam']['states'])} / {frep.fmt(s['beam']['placed'])} / {frep.fmt(s['beam']['alive'])} / "
             f"{s['beam']['retired']} / {s['beam']['supersedes']} / {frep.fmt(s['beam']['evicted'])} |",
             f"| dispatches that advanced: all / base / bonus | {frep.fmt(w['advanced'])} of {frep.fmt(w['burst_jobs'])} / {s['effects']['bonus']['base_advanced']} of "
             f"{s['effects']['bonus']['base_jobs']} / {s['effects']['bonus']['advanced']} of {s['effects']['bonus']['jobs']} |",
             f"| retired starts / their dispatches / with a break record | {s['effects']['retire']['starts']} / {s['effects']['retire']['dispatches_consumed']} / "
             f"{s['effects']['retire']['with_breaks']} |",
             f"| reference clear replayed exactly at open | {s['reference'].get('ok')} ({frep.fmt(s['reference'].get('completion_input_tick'))} / "
             f"{frep.fmt(s['reference'].get('completion_time_passed'))}) |",
             f"| clear candidates / verified / faster than the reference ({frep.fmt(cl['reference_completion_input_tick'])}) | {cl['candidates']} / {cl['verified']} / "
             f"{cl['faster_than_reference']} |",
             f"| main process MB peak / tree MB peak / BattleShip peak / projection | {frep.fmt(peak.get('main_private_mb'), 0)} / {frep.fmt(peak.get('tree_private_mb'), 0)} / "
             f"{peak.get('battleship')} / {json.dumps(mem.get('projection'), default=str)[:300]} |",
             "", "## Clears", ""] + _clear_lines(s) + ["", "## Levels", ""] + _level_lines(s) + ["", "## Rounds", ""] + _round_lines(s["rounds"])
    lines += ["", f"Seed: {json.dumps(s['seed'], default=str)}", "", f"Integrity: {json.dumps(s['integrity'], separators=(',', ':'), default=str)}", ""]
    return "\n".join(lines)


# -- commands ----------------------------------------------------------------------------------------------------------------------------------


def params_from_args(a: argparse.Namespace) -> Params:
    p = Params(bursts=a.bursts, frontier=a.frontier, share=a.share, bonus=0 if a.no_bonus else a.bonus, retire_after=0 if a.no_retire else a.retire_after,
               candidates=a.candidates, reserve=a.reserve, max_rounds=a.max_rounds)
    p.check()
    return p


def plan_and_write(lab_root: Path, probe_dir: Path, out: Path, params: Params, analyse: fv.Analyse = fv.real_analyse) -> Dict[str, Any]:
    """Zero native ticks: the initial starts and their checks, written as plan.json and starts.jsonl (a different start set is never overwritten)."""
    lab, meta, R = load_all(lab_root, analyse)
    probe = read_probe(probe_dir)
    S = build_search_plan(lab, R, probe, params)
    fs = g.LabFS(lab_root)
    saved = Path(out) / "plan.json"
    if saved.is_file():
        old = json.loads(saved.read_text(encoding="utf-8"))
        if old.get("start_set_digest") != S["plan"]["start_set_digest"]:
            raise SearchError(f"refused: {saved} exists with a different start set ({str(old.get('start_set_digest'))[:16]})")
    fs.mkdir(Path(out))
    fs.write_json(saved, S["plan"])
    fs.write_text(Path(out) / "starts.jsonl", "".join(json.dumps(start_row(s), separators=(",", ":"), default=str) + "\n" for s in S["beam"].initial()))
    return {"lab": lab, "meta": meta, "R": R, "probe": probe, "S": S}


def run_command(lab_root: Path, probe: Path, out: Path, a: argparse.Namespace) -> str:
    return (f"python -B tools/frs/frontier_search.py run --lab-root {Path(lab_root).as_posix()} --probe {Path(probe).as_posix()} --out {Path(out).as_posix()} "
            f"--workers {a.workers} --bursts {a.bursts} --frontier {a.frontier} --share {a.share:g} --bonus {a.bonus} --retire-after {a.retire_after} "
            f"--candidates {a.candidates} --reserve {a.reserve} --max-ticks {a.max_ticks} --max-wall-min {a.max_wall_min:g}"
            + (" --no-bonus" if a.no_bonus else "") + (" --no-retire" if a.no_retire else "") + (f" --max-rounds {a.max_rounds}" if a.max_rounds else ""))


def cmd_plan(lab_root: Path, probe: Path, out: Path, a: argparse.Namespace) -> int:
    params = params_from_args(a)
    L = plan_and_write(lab_root, probe, out, params)
    p = L["S"]["plan"]
    print(json.dumps({k: p[k] for k in ("starts", "seed_ticks", "stats", "start_set_digest")}, separators=(",", ":"), default=str))
    print(json.dumps({"probe": p["probe"], "route": p["route"], "params": p["params"]}, separators=(",", ":"), default=str))
    for lv, d in p["per_level"].items():
        print("level", lv, json.dumps(d, separators=(",", ":"), default=str))
    proj = projection(p["throughput_fit"], L["S"]["beam"], params, a.workers, a.max_wall_min / 60.0)
    print("throughput fit", json.dumps(p["throughput_fit"], separators=(",", ":")))
    print("projection", json.dumps(proj, separators=(",", ":")))
    print(f"lab code digest now {fr.code_digest(fr.code_manifest())[:16]}; the probe's {str(p['probe'].get('lab_code_digest'))[:16]}")
    print(f"wrote {Path(out) / 'plan.json'} and {Path(out) / 'starts.jsonl'}")
    print("run with:", run_command(lab_root, probe, out, a))
    return 0


def cmd_run(lab_root: Path, probe: Path, out: Path, a: argparse.Namespace) -> int:
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
    lab, meta, R = load_all(lab_root)
    pr = read_probe(probe)
    S = build_search_plan(lab, R, pr, params)
    old = json.loads(saved.read_text(encoding="utf-8"))
    if old.get("start_set_digest") != S["plan"]["start_set_digest"]:
        print("refused: the start set differs from the saved plan")
        return 2
    if old.get("params") != params.as_dict():
        print(f"refused: the parameters differ from the saved plan's ({old.get('params')})")
        return 2
    install_kill_on_close_job()
    cfg = SearchConfig(lab_root=Path(lab_root), out=Path(out), run_dir=run_dir, probe_dir=Path(probe), n_workers=a.workers, max_ticks=a.max_ticks,
                       max_wall_s=60.0 * a.max_wall_min, expect_code=pr["config"].get("lab_code_digest"))
    code = Search(cfg, fl.real_env(Path(lab_root), run_dir), lab, meta, R, S, params).run()
    print(f"exit {code}: {run_dir / 'report.md'} (progress: {run_dir / 'progress.md'})")
    return code


def default_probe(lab: Path) -> Optional[Path]:
    """The newest trail-lead probe output folder under the lab root (by name), if any."""
    hits = sorted(p for p in lab.glob("trail_probe_*") if p.is_dir() and all((p / f).is_file() for f in PROBE_FILES))
    return hits[-1] if hits else None


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("command", choices=("plan", "run"))
    ap.add_argument("--lab-root", default=str(g.DEFAULT_LAB_ROOT))
    ap.add_argument("--probe", default=None, help="the trail-lead probe's output folder (default: the newest trail_probe_* under the lab root)")
    ap.add_argument("--out", default=None, help="default <lab root>/frontier_<date>")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--bursts", type=int, default=Params.bursts, help="B: bursts per frontier start per round")
    ap.add_argument("--frontier", type=int, default=Params.frontier, help="F: the frontier size")
    ap.add_argument("--share", type=float, default=Params.share, help="the share of F reserved for the previous frontier's best members")
    ap.add_argument("--bonus", type=int, default=Params.bonus, help="extra bursts per round for a start with a break record")
    ap.add_argument("--no-bonus", action="store_true")
    ap.add_argument("--retire-after", type=int, default=Params.retire_after, help="dispatches without a break after which a start is retired")
    ap.add_argument("--no-retire", action="store_true")
    ap.add_argument("--candidates", choices=MODES, default=Params.candidates)
    ap.add_argument("--reserve", type=int, default=Params.reserve)
    ap.add_argument("--max-rounds", type=int, default=0)
    ap.add_argument("--max-ticks", type=int, default=SearchConfig.max_ticks)
    ap.add_argument("--max-wall-min", type=float, default=360.0)
    a = ap.parse_args(argv)
    try:
        lab = g.validate_lab_root(Path(a.lab_root))
        out = g.validate_run_dir(Path(a.out) if a.out else lab / f"frontier_{dt.date.today().isoformat()}", lab)
        probe = Path(a.probe) if a.probe else default_probe(lab)
        if probe is None:
            raise SystemExit("refused: no trail-lead probe output folder (pass --probe)")
        probe = g.validate_run_dir(probe, lab)
    except g.LabRootError as exc:
        raise SystemExit(str(exc))
    missing = [f for f in PROBE_FILES if not (probe / f).is_file()]
    if missing:
        raise SystemExit(f"refused: {probe} is not a trail-lead probe output folder (missing {missing})")
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
    lock = g.LabLock(lab, f"frontier_search {a.command}")
    try:
        lock.acquire()
    except g.LabRootError as exc:
        print(str(exc))
        return 2
    try:
        if a.command == "plan":
            return cmd_plan(lab, probe, out, a)
        return cmd_run(lab, probe, out, a)
    except (SearchError, tp.ProbeError) as exc:
        print(str(exc))
        return 3
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
