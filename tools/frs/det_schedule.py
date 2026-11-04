"""Deterministic scheduling for the crossing-search engines (INFRA_2026-11-04.md, fix 3; REVIEW_2026-11-03.md D4).

The engines (tools/frs/crossing_search.py and the classes built on it) draw starts from one stateful random.Random and
ingest finished jobs in completion order, so two runs with the same seed diverge as soon as two jobs finish in a different
order. `DeterministicSchedule` is a mixin that makes the dispatch sequence a function of (plan, parameters, seed, lag) only.
Wall-clock timing still decides throughput, but not which cell is drawn or what the archive holds:

    keyed draws     every uniform the selection draws for dispatch n is sha256(SCHEDULE_KEY.format(seed, archive id, n, i))
                    (i = 0, 1, ... within that dispatch), a drop-in for random.Random.random(); no generator state exists,
                    so a run (or a resumed one) needs only the seed, which is written to config.json and schedule.json
    in-order ingest a finished job's result is buffered; results are ingested strictly in dispatch order, and dispatch n is
                    selected only after exactly the results of dispatches 1 .. n - lag - 1 are ingested (lag = the
                    reorder window, default 2 x workers). An idle worker waits while an earlier straggler holds the window.
    as-of answers   a CONT boundary question of dispatch n is answered against the archive as it was when n was selected
                    (an index of every new and replaced key with its ingest sequence), not as it is when the question arrives
    stop            the dispatch cap is enforced in next_job (the engines could overshoot it by up to workers - 1), and a
                    stop for a cap no longer forces "do not continue" on in-flight jobs; only an abort does

Tie-breaking (documented here, unchanged in behaviour):
    equal ticks     Archive.keep keeps the incumbent on an equal-tick arrival (`tick >= c.tick` is LATER). With in-order ingest
                    the incumbent is the arrival from the lowest dispatch number, and within one burst the earliest tick
                    (reaches are ingested sorted by tick), so "first come" is now a deterministic rule
    draws           a level is chosen by walking the sorted levels; a cell by bisecting the cumulative weights in the
                    level's insertion (cell id) order; both are pure functions of the keyed uniform
    verification    candidates are queued at ingest and sorted by (claimed tick, dispatch number)

Scope: the run-1 engine (crossing_search.Search) as is. Run 2's lazy re-checks of inherited cells change eligibility when a
check finishes (wall-clock), so `DeterministicSchedule` refuses an engine whose archive still needs them; once end records are
stored (the run 3 tool) the refusal does not apply. Nothing here touches a native process, the words, the keys or the
verification of clears. Standard library only.
"""
from __future__ import annotations

import bisect
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import crossing_search as cs
import frs_archive as fa

SCHEDULE_CONTRACT = "det_schedule_v1"
SCHEDULE_KEY = "det_select_v1|{seed}|{archive_id}|{n}|{i}"


class KeyedRandom:
    """The only method the selection uses, random(), as a keyed function of (seed, archive id, dispatch, draw index)."""

    def __init__(self, seed: int, archive_id: str):
        self.seed = int(seed)
        self.archive_id = str(archive_id)
        self.n = 0
        self.i = 0

    def begin(self, n: int) -> None:
        self.n, self.i = int(n), 0

    def random(self) -> float:
        key = SCHEDULE_KEY.format(seed=self.seed, archive_id=self.archive_id, n=self.n, i=self.i)
        self.i += 1
        return int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big") / 2.0 ** 64

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(f"KeyedRandom has no {name!r}: the selection may only call random()")


@dataclass(frozen=True)
class _Ingest:
    """The key under which a buffered result is handed back to the engine's handle(); prints as the worker index."""

    w: Any
    n: int

    def __str__(self) -> str:
        return str(self.w)


class AsOfIndex:
    """Every key's (ingest sequence, tick) history, so a question can be answered against the archive of an earlier moment.
    Sequence = the dispatch number whose result was being ingested (0 for cells that existed before the search)."""

    def __init__(self) -> None:
        self.seqs: Dict[Tuple[Any, ...], List[int]] = {}
        self.ticks: Dict[Tuple[Any, ...], List[int]] = {}
        self.new_seqs: List[int] = []

    def record(self, key: Sequence[Any], seq: int, tick: int, *, new: bool) -> None:
        k = fa.norm_key(key)
        s, t = self.seqs.setdefault(k, []), self.ticks.setdefault(k, [])
        if s and seq < s[-1]:
            raise RuntimeError(f"out-of-order ingest: sequence {seq} after {s[-1]}")
        s.append(int(seq))
        t.append(int(tick))
        if new:
            self.new_seqs.append(int(seq))

    def tick_asof(self, key: Sequence[Any], seq: int) -> Optional[int]:
        k = fa.norm_key(key)
        s = self.seqs.get(k)
        if not s:
            return None
        pos = bisect.bisect_right(s, int(seq))
        return self.ticks[k][pos - 1] if pos else None

    def cells_asof(self, seq: int) -> int:
        return bisect.bisect_right(self.new_seqs, int(seq))

    def sync(self, archive: Any) -> int:
        """Record every archive cell this index has not seen as existing at sequence 0 (inherited or seed cells)."""
        added = 0
        for c in archive.cells:
            if fa.norm_key(c.key) not in self.seqs:
                self.record(c.key, 0, c.tick, new=True)
                added += 1
        return added


class DeterministicSchedule:
    """Mixin: `class DetSearch(DeterministicSchedule, crossing_search.Search)`. See the module docstring."""

    det_lag_default_factor = 2

    def __init__(self, *args: Any, det_lag: Optional[int] = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        n_workers = int(getattr(self.cfg, "n_workers", 1))
        self.det_lag = int(det_lag) if det_lag is not None else self.det_lag_default_factor * n_workers
        if self.det_lag < 0:
            raise cs.SearchError("refused: the reorder window (det_lag) is not negative")
        self.rng = KeyedRandom(self.p.rng_seed, self.archive.archive_id)
        self._det_buf: Dict[int, Tuple[Any, str, Dict[str, Any], Dict[str, Any]]] = {}
        self._det_next = 1
        self._det_meta: Dict[int, Dict[str, Any]] = {}
        self._asof = AsOfIndex()
        self.det_stats = {"waits": 0, "ingested": 0, "buffered_max": 0, "asof_answers": 0, "arrived_out_of_order": 0, "max_arrived": 0}
        orig_keep = self.archive.keep

        def keep(key: Sequence[Any], level: int, tick: int, words: bytes, end: Sequence[Any], end_digest: bytes, chain: bytes,
                 origin: Mapping[str, Any], n_dispatch: int, **kw: Any) -> Tuple[str, Optional[Any]]:
            verdict, c = orig_keep(key, level, tick, words, end, end_digest, chain, origin, n_dispatch, **kw)
            if verdict in (cs.NEW, cs.REPLACED) and c is not None:
                self._asof.record(c.key, int(n_dispatch), int(c.tick), new=verdict == cs.NEW)
            return verdict, c

        self.archive.keep = keep  # an instance attribute shadows Archive.keep for this run only

    # -- what the run records about the scheduler ----------------------------------------------------------------------------------------

    def schedule_record(self) -> Dict[str, Any]:
        return {"contract": SCHEDULE_CONTRACT, "seed": int(self.p.rng_seed), "archive_id": self.archive.archive_id, "lag": self.det_lag,
                "draw_key": SCHEDULE_KEY, "ingest": "dispatch order; dispatch n selected after exactly the results of 1 .. n - lag - 1",
                "continuation": "answered against the archive as of dispatch n's selection",
                "tie_breaking": {"equal_tick": "the incumbent (lowest dispatch, then earliest tick in its burst) stays",
                                 "level": "sorted levels, cumulative weights", "cell": "cumulative weights in cell-id order, bisect",
                                 "verification": "sorted by (claimed tick, dispatch)"}}

    def config_record(self, ready: Mapping[str, Any]) -> Dict[str, Any]:
        rec = super().config_record(ready)
        rec["scheduler"] = self.schedule_record()
        return rec

    def emit(self, row: Dict[str, Any]) -> None:
        n = row.get("n")
        if isinstance(n, int) and n in self._det_meta:
            row["sched"] = dict(self._det_meta[n])
        super().emit(row)

    # -- the search ----------------------------------------------------------------------------------------------------------------------

    def search_phase(self) -> None:
        unverified = getattr(self.archive, "unverified_eligible", None)
        if callable(unverified) and unverified() > 0:
            self.mark("SEARCH_INVALID", f"deterministic scheduling refused: {unverified()} eligible cells still need a lazy check (their "
                                        "completion time would decide eligibility); store end records first", abort=True)
            return
        self._asof.sync(self.archive)
        self.fs.write_json(self.dir / "schedule.json", self.schedule_record())
        super().search_phase()

    def next_job(self, w: int) -> Optional[Dict[str, Any]]:
        n = self.c["dispatches"] + 1
        if self.p.max_dispatches and n > self.p.max_dispatches:
            self.mark("DISPATCH_CAP", f"{self.c['dispatches']:,} dispatches >= the dispatch cap {self.p.max_dispatches:,}")
            return None
        through = n - self.det_lag - 1
        while self._det_next <= through:
            item = self._det_buf.pop(self._det_next, None)
            if item is None:
                self.det_stats["waits"] += 1
                return None                              # an earlier dispatch is still running: wait for it, in order
            self._det_ingest(item)
        self.rng.begin(n)
        job = super().next_job(w)
        if job is not None:
            self._det_meta[n] = {"n": n, "draws": self.rng.i, "ingested_through": max(0, through), "lag": self.det_lag}
        return job

    def handle(self, w: Any, kind: str, payload: Dict[str, Any]) -> None:
        if isinstance(w, _Ingest) or kind in ("died", "fatal"):
            super().handle(w, kind, payload)
            return
        info = self.inflight.pop(w, None)
        if info is None:
            super().handle(w, kind, payload)             # not in flight: the engine's own SEARCH_INVALID path
            return
        n = int(info["n"])
        if n < self.det_stats["max_arrived"]:
            self.det_stats["arrived_out_of_order"] += 1      # a later dispatch finished first: what the buffer exists for
        self.det_stats["max_arrived"] = max(self.det_stats["max_arrived"], n)
        self._det_buf[n] = (w, kind, payload, info)
        self.det_stats["buffered_max"] = max(self.det_stats["buffered_max"], len(self._det_buf))

    def _det_ingest(self, item: Tuple[Any, str, Dict[str, Any], Dict[str, Any]]) -> None:
        w, kind, payload, info = item
        n = int(info["n"])
        if n != self._det_next:
            raise cs.SearchError(f"out-of-order ingest: dispatch {n}, expected {self._det_next}")
        key = _Ingest(w, n)
        self.inflight[key] = info
        super().handle(key, kind, payload)
        self._det_next = n + 1
        self.det_stats["ingested"] += 1

    def _det_flush(self) -> None:
        """At the end: ingest everything buffered, in dispatch order. A dispatch that never returned (an abort) leaves a gap,
        which is skipped; only then can the archive differ from another run, and the run's own status says why."""
        for n in sorted(self._det_buf):
            if n < self._det_next:
                continue
            self._det_next = n
            self._det_ingest(self._det_buf.pop(n))

    def drain(self) -> None:
        super().drain()
        self._det_flush()

    def close(self) -> None:
        self._det_flush()
        try:
            self.fs.append_jsonl(self.dir / "schedule_stats.jsonl", dict(self.det_stats, next=self._det_next))
        except Exception:  # noqa: BLE001 - statistics only
            pass
        super().close()

    def on_boundary(self, w: int, payload: Dict[str, Any]) -> None:
        """cs.Search.on_boundary with two changes: the decision is taken against the archive as of the dispatch's selection,
        and only an abort (not a stop for a cap) forces "do not continue", so in-flight jobs end as they would have."""
        info = self.inflight.get(w)
        aborting = self.pool is not None and self.pool.abort.is_set()
        if aborting or info is None or info["k"] != int(payload["iteration"]):
            d: Dict[str, Any] = {"go": False, "stopping": True}
        else:
            d = self.continuation_asof(payload["reaches"], int(info["n"]) - self.det_lag - 1)
            self.det_stats["asof_answers"] += 1
        go = bool(d["go"])
        self.c["boundaries"] += 1
        self.c["continued"] += int(go)
        if info is not None:
            info["cont"].append([int(payload["segment"]), len(payload["reaches"]), d.get("new"), d.get("shorter"), d.get("max_gain"), int(go)])
        try:
            self.pool.conns[w].send(("continue", {"iteration": payload["iteration"], "segment": payload["segment"], "go": go}))
        except (OSError, BrokenPipeError):
            pass

    def continuation_asof(self, reaches: Sequence[Sequence[Any]], seq: int) -> Dict[str, Any]:
        """Archive.continuation_decision against the archive as of ingest sequence `seq` (same fields, same rule)."""
        new = shorter = n = 0
        gain = 0
        for j, k in reaches:
            n += 1
            t = self._asof.tick_asof(k, seq)
            if t is None:
                new += 1
                continue
            gg = t - int(j)
            if gg > 0:
                shorter += 1
                gain = max(gain, gg)
        return {"reaches": n, "new": new, "shorter": shorter, "max_gain": gain, "go": (new + shorter) > 0, "cells": self._asof.cells_asof(seq)}


class DetSearch(DeterministicSchedule, cs.Search):
    """The run-1 engine with deterministic scheduling."""


def dispatch_signature(rows: Sequence[Mapping[str, Any]]) -> List[Tuple[Any, ...]]:
    """The wall-clock-free projection of a run's dispatches.jsonl that two deterministic runs must share, in dispatch order."""
    out = []
    for r in sorted((r for r in rows if r.get("kind", "burst") == "burst"), key=lambda r: int(r["n"])):
        out.append((int(r["n"]), r.get("cid"), r.get("k"), r.get("draw_id"), r.get("start_tick"), r.get("words_hex"), r.get("outcome"),
                    json.dumps(r.get("kept"), sort_keys=True), json.dumps(r.get("cont"), sort_keys=True)))
    return out


def cells_signature(rows: Sequence[Mapping[str, Any]]) -> List[Tuple[Any, ...]]:
    """The wall-clock-free projection of a run's cells.jsonl (every NEW / REPLACED event, in the order written)."""
    return [(r.get("ev"), r.get("cid"), json.dumps(r.get("key")), r.get("tick"), r.get("digest"), r.get("n")) for r in rows]
