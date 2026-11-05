#!/usr/bin/env python3
"""Run 3 engine core (2026-11-05 session, step 5; SESSION_LOG_2026-11-04.md section 13): run 2's resume engine
(tools/frs/crossing_search_run2.ResumeSearch, imported, not edited) without its native checks, with the fused first dispatch, end records
on disk, deterministic scheduling (D4) and anomaly keeping. Zero native ticks in this module. The run itself (the plan of runs 1 + 2, the
command line, the reports, the step 7 rules) is step 8; until then the tests build the engine on run 2's plan of a synthetic run 1.

    end records     none is on disk for an inherited cell (SESSION_LOG section 12). Its first dispatch is FUSED (rl/frs_worker.FUSED_END_MODE):
                    the worker validates the prefix by the stored record digest and chain (which cover the 16 observation fields the
                    tuple comparison checks, value and JSON type; host_frame is excluded from both) and returns the observed end record.
                    The engine stores it at ingest, in dispatch order, and writes an `end_record` row to cells.jsonl. Every later
                    dispatch of that representative carries the end record and is compared field by field, as in run 2 (review O10).
                    A cell found by run 3 has its end record from the reach that made it: every NEW / REPLACED row carries `end`.
    mismatch        a fused dispatch whose prefix does not reproduce is run 2's `prefix_end` mismatch, raised before any burst word: the
                    dispatch row (outcome mismatch), the representative quarantined, the event logged, the mismatch limit; no end record.
    no checks       run 2's eager and lazy checks are not run: an inherited cell is eligible from the start and nothing waits on a lent
                    worker, so eligibility never depends on when a check finishes and DeterministicSchedule accepts the archive
                    (`Run3Archive.unverified_eligible` is 0 by construction).
    D4              `Run3Search(DeterministicSchedule, AnomalyIngest, Run3Core)`: keyed draws, in-order ingest, as-of answers.
    key family      `<archive id>|crossing3|<prefix digest>`, iteration 0, 1, ... per representative: no run 1 or run 2 burst is repeated.
    workers         tools/frs/run3_worker.Run3Pool (the transparent proxy, D6, the live detectors).

Two dispatches of one representative can both be fused (the second selected before the first is ingested). Both passed the digest check;
at ingest the second's end record must equal the stored one in the 16 compared fields (else SEARCH_INVALID: the prefix would not be
deterministic) and the first one stays.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Set

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _p in (REPO / "rl", HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import crossing_search as cs  # noqa: E402
import crossing_search_run2 as r2  # noqa: E402
import det_schedule as det  # noqa: E402
import frs_guard as g  # noqa: E402
import frs_machine as fm  # noqa: E402
import frs_run as fr  # noqa: E402
import frs_verify as fv  # noqa: E402
import frs_worker as fw  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import run3_anomaly as ra  # noqa: E402
import run3_worker as r3w  # noqa: E402

RUN3_CORE_CONTRACT = "frs_run3_core_v1"
KEY_FAMILY = "crossing3"
END_RECORD_EV = "end_record"
SearchError, Refused = cs.SearchError, cs.Refused


class Run3Archive(r2.ResumeArchive):
    """Run 2's archive where `verified` means: the representative's end record is known (stored by a run 3 dispatch, or found by run 3).
    Every eligible cell is dispatchable; one without an end record is dispatched fused."""

    def dispatchable(self, c: cs.Cell) -> bool:
        return self.eligible(c)

    def unverified_eligible(self) -> int:
        """Eligible cells that must be checked natively before their first dispatch: none in run 3."""
        return 0

    def end_pending(self) -> int:
        """Eligible cells whose end record is not known yet (their next dispatch is fused)."""
        return sum(1 for c in self.cells if self.eligible(c) and not c.verified)

    def store_end(self, c: cs.Cell, end: Sequence[Any]) -> None:
        c.end = tuple(end)
        c.verified = True
        self.counts["end_records"] = self.counts.get("end_records", 0) + 1
        self.touch(c)


def adopt_archive(archive: r2.ResumeArchive) -> Run3Archive:
    """Run 2's loaded archive as a Run3Archive, in place (same object, same cells): nothing dispatched or pending yet."""
    if type(archive) is not r2.ResumeArchive:
        raise SearchError(f"refused: the archive is a {type(archive).__name__}, not run 2's freshly loaded ResumeArchive")
    if any(getattr(c, "pending", False) for c in archive.cells) or archive.counts.get(cs.NEW) or archive.counts.get(cs.REPLACED):
        raise SearchError("refused: the archive has pending checks or cells kept by a search")
    archive.__class__ = Run3Archive
    archive.counts.setdefault("end_records", 0)
    return archive


class Run3Core(r2.ResumeSearch):
    """Run 2's engine without native checks, with fused first dispatches and end records (see the module docstring)."""

    def __init__(self, cfg: cs.SearchConfig, env: Any, P: Mapping[str, Any], params: r2.Params2):
        super().__init__(cfg, env, P, params)
        self.archive = adopt_archive(self.archive)
        self.fused_n: Set[int] = set()
        self.c.update({"fused": 0, "fused_ok": 0, "fused_mismatch": 0, "fused_repeat": 0, "fused_stale": 0, "fused_cut": 0, "end_records": 0})

    # -- open: run 2's, without the eager checks, with run 3's workers --------------------------------------------------------------------

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
            raise Refused("no cell: the inherited archive is empty")
        self.code = env.code_manifest()
        self.code_dig = fr.code_digest(self.code)
        if cfg.expect_code and self.code_dig != cfg.expect_code:
            raise Refused(f"lab code digest {self.code_dig[:16]} differs from the expected {cfg.expect_code[:16]}")
        self.fs.mkdir(self.dir)
        self.fs.write_json(self.dir / "config.json", self.config_record(ready))
        self.sampler = fm.Sampler(lambda r: self.fs.append_jsonl(self.dir / "memory.jsonl", r), interval=env.sample_s, row_every=env.row_every_s,
                                  caps=env.caps or fm.CAPS_MB, soft=env.soft, snapshot=env.snapshot, now=env.now,
                                  extra=lambda: {"cells": len(self.archive.cells), "phase": self.phase, "dispatches": self.c["dispatches"], "jobs": self.c["jobs"],
                                                 "words_mb": round(self.archive.words_bytes / 2 ** 20, 1), "fused": self.c["fused"]}).start()
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
        self.eager = {"planned": 0, "done": 0, "ok": 0, "quarantined": 0, "errors": 0, "ticks": 0, "wall_s": 0.0, "levels": [], "per_level": {},
                      "estimated_wall_min": 0.0, "run3": "no native check: every inherited cell is validated by its first (fused) dispatch"}
        self.seed_stats = {"seeds": 0, "ok": 0, "dropped": 0, "reasons": {}, "ticks": 0, "wall_s": 0.0, "kind": "none (run 3: fused first dispatches)"}
        self.phase_wall["seed"] = 0.0
        if not self.archive.levels_present2(False):
            self.mark("SEARCH_INCOMPLETE", "no eligible cell after the open")
            return
        self.pool = r3w.Run3Pool(env.worker_spec, env.now)
        self.pool.start(cfg.n_workers)
        self.phase_wall["open"] = round(env.now() - self.t0, 1)
        pl = self.archive.per_level2()
        self.log(f"open done in {self.phase_wall['open']:.0f} s; {cfg.n_workers} workers ready; {self.archive.inherited:,} inherited cells, eligible per level "
                 f"{json.dumps({lv: d['eligible'] for lv, d in pl.items()})}, without an end record {self.archive.end_pending():,}; E7 bound {self.bound}; "
                 f"params {self.p.as_dict()}; arm {cs.ARM_NAME} {self.arm}")
        self.write_progress()

    # -- dispatch ---------------------------------------------------------------------------------------------------------------------------

    def next_job(self, w: int) -> Optional[Dict[str, Any]]:
        pick = self.archive.select2(self.rng, False)
        if pick is None:
            self.mark("ARCHIVE_EMPTY", "no eligible cell is left to dispatch from")
            return None
        c, draw = pick
        return self.build_job(w, c, draw)

    def build_job(self, w: int, c: cs.Cell, draw: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        cfg = self.cfg
        fused = not c.verified
        assert c.words is not None and c.tick > 0 and (fused or len(c.end) == len(mcell.OBS_FIELDS))
        max_words = self.arm["segment_words"] * self.arm["max_segments"]
        want = c.tick + min(max_words, mcell.HORIZON - c.tick)
        if self.used_ticks() + self.reserved + want + self.verify_ticks_pending() > cfg.max_ticks:
            self.mark("TICK_CAP", f"the tick cap {cfg.max_ticks:,} would be exceeded by the next dispatch")
            return None
        k = c.next_k
        c.next_k += 1
        draw_id = f"{self.archive.archive_id}|{KEY_FAMILY}|{c.digest}"
        job = {"kind": fw.JOB_KIND, "iteration": k, "cell": c.cid, "rep": (c.cid, c.tick), "words": bytes(c.words), "end": None if fused else tuple(c.end),
               "end_digest": bytes(c.end_digest), "chain": bytes(c.chain), "terminal": False, "pin": self.pin, "archive_id": draw_id, "allowance": int(want), **self.arm}
        if fused:
            job["end_mode"] = fw.FUSED_END_MODE
        self.c["dispatches"] += 1
        n = self.c["dispatches"]
        self.inflight[w] = {"n": n, "cid": c.cid, "k": k, "level": c.level, "tick": c.tick, "lead": c.lead, "draw_id": draw_id, "draw": dict(draw),
                            "fresh": c.fresh, "seen": c.seen, "breaks": c.breaks, "digest": c.digest, "words": bytes(c.words), "reserved": int(want), "cont": [],
                            "root": c.root, "inherited": c.inherited, "cleared": c.cleared, "fused": fused}
        if fused:
            self.fused_n.add(n)
            self.c["fused"] += 1
        self.reserved += int(want)
        return job

    # -- ingest -----------------------------------------------------------------------------------------------------------------------------

    def handle(self, w: Any, kind: str, payload: Dict[str, Any]) -> None:
        info = self.inflight.get(w)
        fused = bool(info is not None and info.get("fused"))
        super().handle(w, kind, payload)
        if fused and isinstance(payload, dict) and not payload.get("ok") and payload.get("kind") == "mismatch":
            self.c["fused_mismatch"] += 1

    def commit(self, info: Mapping[str, Any], c: cs.Cell, res: Mapping[str, Any]) -> None:
        if info.get("fused"):
            self.store_fused_end(info, c, res)
        super().commit(info, c, res)

    def store_fused_end(self, info: Mapping[str, Any], c: cs.Cell, res: Mapping[str, Any]) -> None:
        pre = res.get("prefix") or {}
        if pre.get("cut"):                                   # the allowance cut the prefix: nothing was checked at L, nothing to store
            self.c["fused_cut"] += 1
            return
        if pre.get("end_mode") != fw.FUSED_END_MODE or pre.get("chain_equal") is not True or pre.get("end_digest_equal") is not True:
            raise SearchError(f"dispatch {info['n']}: a fused dispatch returned without its fused prefix check: {json.dumps(pre, default=str)[:300]}")
        end = tuple(pre["end"])
        if len(end) != len(mcell.OBS_FIELDS):
            raise SearchError(f"dispatch {info['n']}: the end record has {len(end)} fields")
        self.c["fused_ok"] += 1
        if c.digest != info["digest"]:                       # the representative was replaced while this dispatch ran: the record is the old one's
            self.c["fused_stale"] += 1
            return
        if c.verified:                                       # an earlier fused dispatch of this representative stored it first (dispatch order)
            self.c["fused_repeat"] += 1
            diffs = mcell.obs_diffs(end, c.end)
            if diffs:
                self.mark("SEARCH_INVALID", f"dispatch {info['n']}: cell {c.cid}'s prefix reproduced its digest but not its stored end record: {diffs}", abort=True)
            return
        self.archive.store_end(c, end)
        self.c["end_records"] += 1
        row = {"ev": END_RECORD_EV, "cid": c.cid, "key": list(c.key), "level": c.level, "tick": c.tick, "digest": c.digest, "end_digest": c.end_digest.hex(),
               "chain": c.chain.hex(), "end": list(c.end), "n": int(info["n"]), "utc": g.utc()}
        with self._lock:
            self.fs.append_jsonl(self.dir / "cells.jsonl", row)

    def emit_cell(self, verdict: str, c: cs.Cell, info: Optional[Mapping[str, Any]], previous: Optional[Mapping[str, Any]] = None) -> None:
        """crossing_search.Search.emit_cell plus the cell's end record (`end`, the 17 observation values at its tick)."""
        row = {"ev": verdict, "cid": c.cid, "key": list(c.key), "level": c.level, "tick": c.tick, "lead": c.lead, "slack": self.archive.slack_of(c.tick), "digest": c.digest,
               "end_digest": c.end_digest.hex(), "chain": c.chain.hex(), "origin": c.origin, "n": self.c["dispatches"], "seen": c.seen, "replaced": c.replaced,
               "first_at_level": c.first_level_reach if verdict == cs.NEW else False, "utc": g.utc(), "words_hex": c.words.hex() if c.words is not None else None,
               "end": list(c.end) if c.verified and c.end else None}
        if previous:
            row["previous"] = dict(previous)
        with self._lock:
            self.fs.append_jsonl(self.dir / "cells.jsonl", row)

    def emit(self, row: Dict[str, Any]) -> None:
        n = row.get("n")
        if row.get("kind", "burst") == "burst" and isinstance(n, int):
            row["end_mode"] = fw.FUSED_END_MODE if n in self.fused_n else None
        super().emit(row)

    # -- records ----------------------------------------------------------------------------------------------------------------------------

    def end_record_stats(self) -> Dict[str, Any]:
        inh = [c for c in self.archive.cells if c.inherited]
        out = {k: self.c[k] for k in ("fused", "fused_ok", "fused_mismatch", "fused_repeat", "fused_stale", "fused_cut", "end_records")}
        out.update({"inherited": len(inh), "inherited_with_end_record": sum(1 for c in inh if c.verified), "eligible_without_end_record": self.archive.end_pending()})
        return out

    def config_record(self, ready: Mapping[str, Any]) -> Dict[str, Any]:
        rec = super().config_record(ready)
        rec["contract"] = RUN3_CORE_CONTRACT
        rec["run3_core_file_sha256"] = g.sha256_file(Path(__file__).resolve())
        rec["key_family"] = KEY_FAMILY
        rec["eager"] = None
        rec["origins"]["end_records"] = ("not on disk for inherited cells: each one's first dispatch is fused (rl/frs_worker.FUSED_END_MODE, record digest and chain "
                                         "at L) and its observed end record is stored at ingest as an end_record row of cells.jsonl")
        rec["origins"]["draw_id"] = f"<archive id>|{KEY_FAMILY}|<prefix words digest>, iteration k = 0.. per representative (a new family)"
        rec["run3"] = {"contract": RUN3_CORE_CONTRACT, "end_mode": fw.FUSED_END_MODE, "end_record_ev": END_RECORD_EV, "checks": "none (no eager or lazy check)",
                       "workers": r3w.RUN3_WORKER_CONTRACT}
        return rec

    def summary(self) -> Dict[str, Any]:
        s = super().summary()
        s["contract"] = RUN3_CORE_CONTRACT
        s["config"]["key_family"] = KEY_FAMILY
        s["run3"] = {"end_records": self.end_record_stats()}
        return s


class Run3Search(det.DeterministicSchedule, ra.AnomalyIngest, Run3Core):
    """Run 3's engine: deterministic scheduling (D4), anomaly keeping, fused first dispatches."""
