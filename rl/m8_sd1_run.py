"""M8-sd1 run engine: the open (P1 against the archive's pin, identity replays, the record re-verified in full), single-arm exploration under `m8_rd_select_v4` with sd1's keyed draws,
the fastest-first verification of the clear pool with the inherited descriptive replays after it, the close checks of the four-level continuation, the decision under `m8_sd1_rule_v1`.

It subclasses rd4's `Session4` (itself a subclass of rd3's `Session3`, rd2's `Session2` and rd1's `Session`; all unchanged) and overrides what is specific to the speed session: the archive
is an `Archive5` (draw id, weights and E7 by iteration), the identity samples use sd1's keys and v4's weights, the open replays the inherited record as a claim (the four facts and both
clocks, O2), the verification plans its replays with `m8_sd1_claims` (fastest first; the inherited descriptive candidates after the pool, reported only), the close checks audit the five-part
ledger and the prefix chain rd1 -> rd2 -> rd3 -> rd4 -> sd1, require ALL FOUR earlier trees unchanged and audit the stamps of every record, and the decision applies the registered rule.
Every record sd1 writes carries the task block and `created_utc` (rl/m8_sd1_artifacts.py); every JSONL file opens with its stamped header row. Every write goes under sd1's own root;
the write guard turns any write under any other runs/ tree into an INVALID stop.

The wall-top label is suppressed exactly as in rd3 and rd4 (`m8_rd3_run.suppress_wall_top_label`, applied in `Session3.commit`, inherited). Light top-level imports only: spawned workers
re-import the launching script.
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import shutil
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import m8_rd_archive as march  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_claims as mclaims  # noqa: E402
import m8_rd_finish as fin  # noqa: E402
import m8_rd_run as mrun  # noqa: E402
import m8_rd_select2 as s2  # noqa: E402
import m8_rd_worker as mw  # noqa: E402
import m8_rd2_report as rpt2  # noqa: E402
import m8_rd2_run as run2  # noqa: E402
import m8_rd2_worker as w2  # noqa: E402
import m8_rd3_run as run3  # noqa: E402
import m8_rd4_run as run4  # noqa: E402
import m8_sd1_artifacts as art  # noqa: E402
import m8_sd1_claims as cl5  # noqa: E402
import m8_sd1_report as rpt5  # noqa: E402
import m8_sd1_resume as r5  # noqa: E402
import m8_sd1_rule as rule5  # noqa: E402
import m8_sd1_select as s5  # noqa: E402
from m8_rd_run import CapStop, IntegrityStop, utc  # noqa: E402

RUN5_CONTRACT = "m8_sd1_run_v1"
OPEN_IDENTITY_BASE = 8_000_000
CLOSE_IDENTITY_BASE = 9_000_000
SESSION_ID = "sd1"
SCHEMAS = {"iterations": "m8_sd1_iterations_v1", "sightings": "m8_sd1_wall_top_sightings_v1", "replays": "m8_sd1_replays_v1", "candidates": "m8_sd1_candidates_v1",
           "dispatch_rows": "m8_sd1_dispatch_rows_v1", "memory_tree": "m8_sd1_memory_tree_v1"}
WorkerPool5 = run2.WorkerPool2
WriteGuard = w2.WriteGuard
identity_job = run2.identity_job
suppress_wall_top_label = run3.suppress_wall_top_label
write_json5 = art.write_json5


# -- identity samples (rd4's designs, sd1's keys, v4's weights) ------------------------------------------------------------------------------------------------


def _kh(a: march.Archive, tag: str, c: march.Cell) -> bytes:
    return hashlib.sha256(f"m8_rd|{a.archive_id}|{tag}|{c.id}".encode()).digest()


def identity_sample_open(a: s5.Archive5, k: int = 16) -> Dict[str, Any]:
    """The open identity replays: the shortest cell of each of the top three levels (the record's terminal cell among them); the four highest-weight v4-eligible cells at the open; four
    keyed-random cells among the launch-capable and the A2-at-y>=0 cells (keys `m8_rd|<archive id>|identity_open|sd1|<cell id>`); five keyed-random v4-eligible cells; topped up to K."""
    with a.as_v4():
        cells = [c for c in a.cells if c.id != 0]
        chosen: List[Tuple[str, march.Cell]] = []

        def add(name: str, c: march.Cell) -> None:
            if all(c.id != x.id for _n, x in chosen) and len(chosen) < k:
                chosen.append((name, c))

        for lv in sorted({c.level for c in cells}, reverse=True)[:3]:
            pool = [c for c in cells if c.level == lv]
            add(f"top_level_{lv}", min(pool, key=lambda c: (c.L, c.id)))
        probs = a.probabilities() if a.mode == 2 else {}
        for cid in [i for i in sorted(probs, key=lambda i: (-probs[i], i)) if i != 0][:4]:
            add("highest_weight", a.cells[cid])
        hi = [c for c in cells if rpt2.is_launch_capable(c.key[2], float(c.end[mcell.I_Y])) or (c.key[2] == mcell.RES_A2 and float(c.end[mcell.I_Y]) >= 0)]
        n0 = len(chosen)
        for c in sorted(hi, key=lambda c: _kh(a, "identity_open|sd1", c)):
            if len(chosen) >= n0 + 4:
                break
            add("keyed_launch_or_a2_high", c)
        elig = sorted((c for c in cells if a.eligible(c)), key=lambda c: _kh(a, "identity_open|sd1", c))
        n0 = len(chosen)
        for c in elig:
            if len(chosen) >= n0 + 5:
                break
            add("keyed_eligible", c)
        for c in elig:
            add("keyed_eligible_topup", c)
        return {"cells": [c for _n, c in chosen], "names": [n for n, _c in chosen]}


def identity_sample_close(a: march.Archive, k: int = 16) -> Dict[str, Any]:
    """The close identity replays: the milestone cells first (the shortest wall-top, left-of-wall and left-target-broken cells), the shortest cell of each of the top three levels (the record
    and the top level's shortest arrival among them), then keyed-random cells (`m8_rd|<archive id>|identity_close|sd1|<cell id>`)."""
    cells = [c for c in a.cells if c.id != 0]
    chosen: List[Tuple[str, march.Cell]] = []

    def shortest(pred: Any, name: str) -> None:
        pool = [c for c in cells if pred(c) and all(c.id != x.id for _n, x in chosen)]
        if pool:
            chosen.append((name, min(pool, key=lambda c: (c.L, c.id))))

    shortest(lambda c: c.key[2] == mcell.RES_GROUNDED and c.key[4] == mcell.L0_FLOOR_LINE, "wall_top")
    shortest(lambda c: c.key[0] <= -8, "left_of_wall")
    shortest(lambda c: any(not (c.key[3] >> i) & 1 for i in mcell.LEFT_TARGET_IDS), "left_target_broken")
    for lv in sorted({c.level for c in cells}, reverse=True)[:3]:
        shortest(lambda c, lv=lv: c.level == lv, f"top_level_{lv}")
    for c in sorted((c for c in cells if all(c.id != x.id for _n, x in chosen)), key=lambda c: _kh(a, "identity_close|sd1", c)):
        if len(chosen) >= k:
            break
        chosen.append(("keyed_random", c))
    return {"cells": [c for _n, c in chosen[:k]], "names": [n for n, _c in chosen[:k]]}


# -- the session -----------------------------------------------------------------------------------------------------------------------------------------


class Session5(run4.Session4):
    def __init__(self, cfg: mrun.RunConfig, env: mrun.RunEnv, *, archive: s5.Archive5, archive_pin: Mapping[str, Any], base_info: Mapping[str, Any], rd1_root: Path, rd2_root: Path,
                 rd3_root: Path, rd4_root: Path, lines_sha256: str, ckpt_seq: int, archive_created_utc: str, record_candidate: Mapping[str, Any],
                 inherited: Sequence[Mapping[str, Any]], rd4_line: Mapping[str, Any]):
        if archive.sd1_first_iteration is None or archive.record_reference is None or archive.margin is None:
            raise RuntimeError("sd1 opens an archive that has begun sd1 (the materialised checkpoint with the record reference and the margin)")
        run2.Session2.__init__(self, cfg, env, archive=archive, archive_pin=archive_pin, base_info=base_info, rd1_root=rd1_root, lines_sha256=lines_sha256)
        self.rd2_root = Path(rd2_root)
        self.rd3_root = Path(rd3_root)
        self.rd4_root = Path(rd4_root)
        self.ckpt_seq = int(ckpt_seq)                        # the materialised checkpoint (open) is sequence 46
        self.first_iteration = int(archive.sd1_first_iteration)
        self.iteration = self.first_iteration
        self.first_new_cell = len(archive.cells)
        self.wall_top_sightings: List[Dict[str, Any]] = []
        self.live_seen = {"dispatches": 0, "seen_ge_8": 0}
        self.archive_created_utc = str(archive_created_utc)
        self.record_reference = dict(archive.record_reference)
        self.t_rec = int(self.record_reference["completion_input_tick"])
        self.t_rec_time_passed = int(self.record_reference["completion_time_passed"])
        self.margin = int(archive.margin)
        self.record_candidate = dict(record_candidate)
        self.inherited = [dict(c) for c in inherited]
        self.rd4_line = dict(rd4_line)
        self.inherited_records: List[Dict[str, Any]] = []
        self.record_open_record: Dict[str, Any] = {}
        self.state["scope"] = rule5.SCOPE
        self.state["record_reference"] = self.record_reference
        self.state["margin"] = self.margin

    # -- stamped bookkeeping -------------------------------------------------------------------------------------------------------------

    def save_state(self, **extra: Any) -> None:
        self.state.update(extra, clock=self.clock.to_json(), ticks=dict(self.ticks), utc=utc(), invalid=list(self.invalid), incomplete=list(self.incomplete),
                          lifecycle_failures=dict(self.lifecycle_failures))
        write_json5(self.dir / "state.json", self.state)

    def checkpoint(self, why: str) -> None:
        assert self.archive is not None
        self.ckpt_seq += 1
        meta = {"checkpoint_seq": self.ckpt_seq, "why": why, "utc": utc(), "session": self.cfg.session_id, "pins": dict(self.env.pins), "horizon": self.cfg.horizon,
                "burst_words": self.cfg.burst_words, "ticks": dict(self.ticks), "ledger_T": {"ticks": self.ledgers["T"].ticks, "jobs": self.ledgers["T"].jobs},
                "velocity_reversals": dict(self.vel_reversals), "pin_tick0": self.archive_pin, "base": self.base_info, "first_new_cell": self.first_new_cell}
        march.save_checkpoint(self.cfg.archive_dir, self.archive, art.stamp(meta, created_utc=self.archive_created_utc))

    def prepare_session_files(self) -> None:
        """The stamped header rows of the session's JSONL files, before the engine appends to them."""
        art.jsonl_header(self.dir / "iterations_T.jsonl", SCHEMAS["iterations"])
        art.jsonl_header(self.dir / "wall_top_sightings.jsonl", SCHEMAS["sightings"])
        art.jsonl_header(self.dir / "verification" / "replays.jsonl", SCHEMAS["replays"])

    # -- open ----------------------------------------------------------------------------------------------------------------------

    def p1(self) -> None:
        """P1 against the ARCHIVE's pin: the tick-0 record of two processes equals `pin_tick0`; the two pinned Track 1 traces word for word; the return self-test in a scratch archive
        including the refused corrupted end record."""
        cfg = self.cfg
        self.clock.begin("p1")
        self.state["phase"] = "p1"
        rec: Dict[str, Any] = {"started_utc": utc(), "scope": rule5.SCOPE, "pin": "the archive's pin_tick0"}
        pin = dict(self.archive_pin)
        first = self.run_batch([{"kind": "tick0", "pin": pin}], "p1", "p1", cfg.p1_tick_cap)[0]
        if not first.get("ok"):
            raise self._p1_failure("tick0 against the archive pin", first)
        second = self.run_batch([{"kind": "tick0", "pin": pin}], "p1", "p1", cfg.p1_tick_cap)[0]
        if not second.get("ok"):
            raise self._p1_failure("tick0 reproduction", second)
        self.pin = pin
        rec["tick0"] = {"digest": pin["digest"], "lines_digest": pin["lines"], "modes": [first["mode"], second["mode"]],
                        "host_frames": [first["tick0"]["host_frame"], second["tick0"]["host_frame"]], "host_frame_equal": second["tick0"].get("host_frame_equal"), "equals_archive_pin": True}
        self.log(f"P1 tick-0 record equals the archive pin {pin['digest'][:12]} (modes {rec['tick0']['modes']})")
        traces = self.env.p1_inputs()
        jobs = [{"kind": "trace", "name": t["name"], "words": t["words"], "expected_digests": t["expected_digests"], "expected_host_frames": t.get("expected_host_frames"), "pin": pin,
                 "allowance": len(t["words"])} for t in traces]
        selftest = self.selftest_prepare()
        results = self.run_batch(jobs + selftest["burst_jobs"], "p1", "p1", cfg.p1_tick_cap)
        trace_res = results[:len(traces)]
        for t, r in zip(traces, trace_res):
            if not r.get("ok"):
                raise self._p1_failure(f"trace {t['name']}", r)
            if r["native_action_digest"] != t["native_action_digest"]:
                raise IntegrityStop(f"P1 trace {t['name']}: native action digest {r['native_action_digest'][:12]} differs from the pinned {t['native_action_digest'][:12]}")
        rec["traces"] = [{"name": r["name"], "words": r["words"], "native_action_digest": r["native_action_digest"], "host_frames_equal": r["host_frames_equal"], "end_reason": r["end_reason"],
                          "mode": r["mode"]} for r in trace_res]
        burst = results[len(traces)]
        if not burst.get("ok"):
            raise self._p1_failure("self-test burst", burst)
        rec["selftest"] = self.selftest_returns(burst, selftest)
        rec["ticks"] = self.ticks["p1"]
        rec["finished_utc"] = utc()
        self.p1_record = rec
        write_json5(self.dir / "p1.json", rec)
        self.save_state(p1="PASS")
        self.log(f"P1 passed: {self.ticks['p1']} native ticks")

    def open_identity(self) -> None:
        """K identity returns of archive cells from fresh processes, each with the four checks of every return. Any mismatch is INVALID."""
        cfg = self.cfg
        samp = identity_sample_open(self.archive, cfg.identity_k)
        jobs = [identity_job(self.archive, c, self.pin, OPEN_IDENTITY_BASE + n, self.archive.draw_id) for n, c in enumerate(samp["cells"])]
        results = self.run_batch(jobs, "p1", "p1", cfg.p1_tick_cap)
        bad = [r for r in results if not r.get("ok")]
        for r in bad:
            if r.get("kind") == "mismatch":
                raise IntegrityStop(f"open identity replay: {r.get('mismatch')} {json.dumps(r.get('detail'), default=str)[:400]}")
        if bad:
            raise CapStop(f"open identity replay: {bad[0].get('kind')} {bad[0].get('outcome') or bad[0].get('error')}")
        okn = sum(1 for r in results if r["prefix"].get("end_equal", True) and r["prefix"].get("chain_equal", True))
        self.open_identity_record = {"scope": rule5.SCOPE, "cells": len(jobs), "names": samp["names"], "cell_ids": [c.id for c in samp["cells"]], "verified": okn,
                                     "ticks": sum(int(r.get("ticks", 0)) for r in results), "ok": okn == len(jobs), "utc": utc()}
        write_json5(self.dir / "identity_open.json", self.open_identity_record)
        self.save_state(open_identity="PASS")
        self.log(f"open identity replays: {okn} / {len(jobs)} returned exactly ({self.ticks['p1']} open ticks)")

    def open_record_replay(self) -> None:
        """The inherited record re-verified in full at the open (O2): one fresh-process replay of its registered words from tick 0 as a claim, with the engine's exactness, the four clear
        facts and both clocks equal to the pinned reference. Any difference is INVALID; a replay that could not run is INCOMPLETE."""
        cfg = self.cfg
        cand = self.record_candidate
        n = len(bytes(cand["words"]))
        with self.tick_lock:
            if self.ticks["p1"] + n > cfg.p1_tick_cap:
                raise CapStop(f"the record's open replay needs {n:,} ticks beyond the open cap ({self.ticks['p1']:,} used of {cfg.p1_tick_cap:,})")
            self.ticks["p1"] += n
        self.clock.check()
        label = "record_open"
        try:
            trace = self.env.replay(cand, n, label, 0)
        except Exception as exc:  # noqa: BLE001
            raise CapStop(f"the record's open replay failed: {type(exc).__name__}: {exc}")
        trace = art.stamp(dict(trace))
        fin._save_trace(self.dir / "verification" / f"{label}.json.gz", trace)
        rep = mclaims.evaluate_replay(trace, cand, n, self.env.analyse)
        rep["label"] = label
        rep["trace"] = f"{label}.json.gz"
        problems = cl5.exactness5(rep, cand)
        facts = rep.get("clear_facts") or {}
        if not problems and (facts.get("completion_input_tick") != self.t_rec or facts.get("completion_time_passed") != self.t_rec_time_passed):
            problems.append(f"the replay's clocks {facts.get('completion_input_tick')} / {facts.get('completion_time_passed')} differ from the pinned reference {self.t_rec} / {self.t_rec_time_passed}")
        digest = mcell.words_digest(bytes(cand["words"]))
        if digest != self.record_reference["native_action_digest"]:
            problems.append("the record candidate's words do not hash to the pinned reference digest")
        self.record_open_record = {"scope": rule5.SCOPE, "label": label, "words": n, "native_action_digest": digest, "record_reference": self.record_reference, "exact": not problems,
                                   "problems": problems, "clear_facts": facts, "t": rep.get("t"), "ticks": n, "utc": utc()}
        write_json5(self.dir / "record_open.json", self.record_open_record)
        if problems:
            raise IntegrityStop(f"the record reference did not re-verify at the open: {problems[:2]}")
        self.save_state(record_open="PASS")
        self.log(f"the record re-verified at the open: {n} words, clocks {facts.get('completion_input_tick')} / {facts.get('completion_time_passed')} ({self.ticks['p1']} open ticks)")

    # -- exploration ------------------------------------------------------------------------------------------------------------------

    def run_arm(self, arm: str) -> Dict[str, Any]:
        self.prepare_session_files()
        return super().run_arm(arm)

    def make_job(self, arm: str, w: int, remaining: int) -> Dict[str, Any]:
        assert arm == "T", "sd1 has one arm"
        cfg = self.cfg
        it = self.iteration
        self.iteration += 1
        assert self.archive is not None
        t0 = time.perf_counter()
        cell = self.archive.dispatch(it, w)
        self.select_s += time.perf_counter() - t0
        self.live_seen["dispatches"] += 1
        self.live_seen["seen_ge_8"] += int(cell.seen >= rpt5.SEEN_MIN)
        want = cell.L + min(cfg.burst_words, cfg.horizon - cell.L)
        job = {"kind": w2.JOB_KIND, "arm": "T", "iteration": it, "cell": cell.id, "rep": (cell.burst, cell.offset), "words": self.archive.cell_words(cell), "end": cell.end,
               "end_digest": cell.end_digest, "chain": cell.chain, "terminal": cell.terminal, "pin": self.pin, "archive_id": self.archive.draw_for(it), "burst_words": cfg.burst_words,
               "allowance": min(want, remaining), "level": cell.level, "L": cell.L}
        self.pool_job[w] = job
        return job

    def save_arm_artifacts(self, arm: str) -> None:
        led = self.ledgers[arm]
        write_json5(self.dir / f"ledger_{arm}.json", {"arm": arm, "ticks": led.ticks, "jobs": led.jobs, "cut_jobs": led.cut_jobs, "job_log": led.job_log,
                                                      "t_records": {str(t): v for t, v in led.t_records.items()}, "l0_cid": led.l0_cid,
                                                      "candidates": [{k: v for k, v in c.items() if k != "words"} | {"length": len(c["words"])} for c in led.candidates]})
        art.write_jsonl_gz5(self.dir / f"candidates_{arm}.jsonl.gz", ({"cid": c["cid"], "kind": c["kind"], "words_hex": bytes(c["words"]).hex()} for c in led.candidates), SCHEMAS["candidates"])

    def finish_arm_record(self, rec: Dict[str, Any]) -> None:
        rec["scope"] = rule5.SCOPE
        rec["select_s"] = round(self.select_s, 3)
        rec["first_iteration"] = self.first_iteration
        rec["next_iteration"] = self.iteration
        rec["dispatches"] = self.iteration - self.first_iteration
        rec["live_seen_at_dispatch"] = dict(self.live_seen)
        rec["pools"] = cl5.pool_sizes5(self.ledgers["T"], self.ledgers["T"].ticks, self.t_rec, self.margin)      # visible even when the verification is skipped
        rec["wall_top_sightings"] = {"bursts": len(self.wall_top_sightings), "from_a_wall_top_start": sum(1 for x in self.wall_top_sightings if x["start_cell_on_wall_top"]),
                                     "from_another_start": sum(1 for x in self.wall_top_sightings if not x["start_cell_on_wall_top"])}
        write_json5(self.dir / "arm_T.json", rec)


# -- verification ----------------------------------------------------------------------------------------------------------------------------------


def save_route5(sess: Session5, name: str, cand: Mapping[str, Any], rep: Mapping[str, Any], vdir: Path) -> None:
    """routes/<name>/: actions.jsonl (M4 canonical form), stamped metadata.json, trace.json.gz (every raw reply of the verification replay, stamped), both completion clocks."""
    n = int(rep["counted"])
    words = bytes(cand["words"][:n])
    d = sess.cfg.root / "routes" / name
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "actions.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for i, w in enumerate(words):
            b, x, y = mcell.TRIPLES[w]
            f.write(json.dumps({"sequence_index": i, "buttons": b, "stick_x": x, "stick_y": y, "consumed_tick": i}, separators=(",", ":")) + "\n")
    src = vdir / rep["trace"]
    if src.is_file():
        shutil.copy2(src, d / "trace.json.gz")
    meta = {"schema": "m8_rd_route_v1", "arm": "T", "claim": "clear", "route": name, "session": sess.cfg.session_id, "native_action_digest": mcell.words_digest(words), "words": n,
            "candidate": {k: v for k, v in cand.items() if k not in ("words", "breaks")}, "iteration": cand["iteration"], "replay": {k: v for k, v in rep.items() if k not in ("breaks",)},
            "track1_words_hex": words.hex(), "action_contract": "rlaction_native_v1",
            "completion_clocks": {"completion_time_passed": (rep.get("clear_facts") or {}).get("completion_time_passed"), "completion_input_tick": (rep.get("clear_facts") or {}).get("completion_input_tick"),
                                  "note": "two distinct clocks; never collapsed, completion_input_tick never decremented"}}
    write_json5(d / "metadata.json", meta)


def verify_phase5(sess: Session5) -> Dict[str, Any]:
    """The clear pool fastest first (three at a time) until the first exact replay, then the inherited descriptive replays (reported only), with the close identity replays in parallel."""
    cfg, env = sess.cfg, sess.env
    sess.state["phase"] = "verify"
    led = sess.ledgers["T"]
    T = led.ticks
    t_rec, margin = sess.t_rec, sess.margin
    if led.ticks < cfg.min_arm_ticks:
        sess.incomplete.append(f"exploration reached {led.ticks:,} native ticks (< {cfg.min_arm_ticks:,})")
    rec: Dict[str, Any] = {"scope": rule5.SCOPE, "started_utc": utc(), "exploration_ticks": T, "record_reference": sess.record_reference, "margin": margin, "arm": None, "identity": None,
                           "inherited_descriptive": None, "cap_hit": None, "pools": cl5.pool_sizes5(led, T, t_rec, margin), "claims_contract": cl5.CLAIMS5_CONTRACT, "claims_digest": cl5.contract_digest()}
    sess.log(f"verification: {len(led.candidates)} candidates over {T:,} exploration ticks; pools {rec['pools']}")
    sess.clock.begin("verify")
    sess.pool.retire(list(range(cfg.verify_threads, cfg.n_workers)))
    vdir = sess.dir / "verification"
    art.jsonl_header(vdir / "replays.jsonl", SCHEMAS["replays"])
    done: Dict[int, Dict[str, Any]] = {}
    done_inh: Dict[int, Dict[str, Any]] = {}
    cands_by_cid = {c["cid"]: c for c in led.candidates}
    cap_hit: List[str] = []
    free_slots: "queue.Queue[int]" = queue.Queue()
    for s_ in range(cfg.verify_threads):
        free_slots.put(s_)

    def run_one(cand: Mapping[str, Any], counted: int) -> Dict[str, Any]:
        slot = free_slots.get()
        label = f"rd4_c{cand['rd4_cid']:04d}_clear_inherited" if cand.get("inherited") else f"T_c{cand['cid']:04d}_{cand['kind']}"
        try:
            try:
                trace = env.replay(cand, counted, label, slot)
            except Exception as exc:  # noqa: BLE001
                return {"cid": cand["cid"], "arm": "T", "kind": cand["kind"], "counted": counted, "exact": False, "error": True, "label": label, "inherited": bool(cand.get("inherited")),
                        "problems": [f"replay failed: {type(exc).__name__}: {exc}"], "t": 0, "l0": False, "crossing": False, "left_target": False, "clear": False, "clear_facts": {},
                        "exactness5": [f"replay failed: {type(exc).__name__}: {exc}"]}
            trace = art.stamp(dict(trace))
            fin._save_trace(vdir / f"{label}.json.gz", trace)
            rep = mclaims.evaluate_replay(trace, cand, counted, env.analyse)
            rep["label"] = label
            rep["trace"] = f"{label}.json.gz"
            rep["inherited"] = bool(cand.get("inherited"))
            rep["exactness5"] = cl5.exactness5(rep, cand)
            return rep
        finally:
            free_slots.put(slot)

    def batch(todo: Sequence[Tuple[Dict[str, Any], int]], ex: ThreadPoolExecutor, sink: Dict[int, Dict[str, Any]]) -> bool:
        try:
            sess.clock.check()
        except CapStop as exc:
            cap_hit.append(f"claims: {exc}")
            return False
        need = sum(n for _c, n in todo)
        with sess.tick_lock:
            if sess.ticks["replays"] + need > cfg.replay_tick_cap:
                cap_hit.append(f"claims: replay cap {cfg.replay_tick_cap:,} ticks ({sess.ticks['replays']:,} used, {need:,} more needed)")
                return False
            sess.ticks["replays"] += need
        futs = [(c, ex.submit(run_one, c, n)) for c, n in todo]
        for c, f in futs:
            r = f.result()
            sink[c["cid"]] = r
            art.append_jsonl5(vdir / "replays.jsonl", {k: v for k, v in r.items() if k not in ("breaks",)}, SCHEMAS["replays"])
        return True

    def claims() -> None:
        with ThreadPoolExecutor(max_workers=cfg.verify_threads) as ex:
            while True:                                                   # the pool, fastest first, until the first exact replay
                todo, _info = cl5.plan_replays5(led, T, done, t_rec, margin, batch=cfg.verify_threads)
                if not todo:
                    break
                if not batch(todo, ex, done):
                    return
            while True:                                                   # the inherited descriptive replays, after the pool (reported only)
                todo = cl5.plan_inherited5(sess.inherited, done_inh, batch=cfg.verify_threads)
                if not todo:
                    return
                if not batch(todo, ex, done_inh):
                    return

    ident_out: Dict[str, Any] = {}

    def identity() -> None:
        arch = sess.archive
        samp = identity_sample_close(arch, cfg.identity_k)
        jobs = [identity_job(arch, c, sess.pin, CLOSE_IDENTITY_BASE + n, arch.draw_id) for n, c in enumerate(samp["cells"])]
        try:
            results = sess.run_batch(jobs, "verify", "replays", cfg.replay_tick_cap)
        except CapStop as exc:
            cap_hit.append(f"identity replays: {exc}")
            return
        bad = [r for r in results if not r.get("ok")]
        okn = sum(1 for r in results if r.get("ok") and r["prefix"].get("end_equal", True) and r["prefix"].get("chain_equal", True))
        ident_out.update({"cells": len(jobs), "names": samp["names"], "verified": okn, "ok": not bad, "cell_ids": [c.id for c in samp["cells"]],
                          "failures": [{k: r.get(k) for k in ("kind", "mismatch", "detail", "outcome", "message")} for r in bad]})
        for r in bad:
            if r.get("kind") == "mismatch":
                sess.stop_invalid(f"close identity replay: {r.get('mismatch')} {json.dumps(r.get('detail'), default=str)[:300]}")
            else:
                sess.incomplete.append(f"close identity replay: {r.get('kind')} {r.get('outcome') or r.get('error')}")

    errors: List[str] = []

    def guarded(fn: Any) -> None:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{fn.__name__}: {type(exc).__name__}: {exc}\n{traceback.format_exc()[-1500:]}")

    t_claims = threading.Thread(target=guarded, args=(claims,), name="m8sd1-claims")
    t_claims.start()
    try:
        guarded(identity)
    finally:
        t_claims.join()
    if errors:
        raise CapStop("verification error: " + errors[0][:600])
    rec["identity"] = ident_out
    if not sess.invalid and (not ident_out or ident_out.get("verified") != ident_out.get("cells")):
        sess.incomplete.append("the close identity replays did not complete" + (f": {cap_hit}" if cap_hit else ""))
    if cap_hit:
        sess.log(f"verification stopped at a cap: {cap_hit}")
    reps = list(done.values())
    verified: List[Dict[str, Any]] = []
    for r in reps:
        cand = cands_by_cid[r["cid"]]
        if r.get("error"):
            sess.incomplete.append(f"candidate {r['cid']}: {r['problems'][0][:200]}")
            continue
        if not r["exact"]:
            sess.stop_invalid(f"candidate {r['cid']} ({r['kind']}): inexact replay: {r['problems'][:2]}")
            continue
        if r["exactness5"]:
            sess.stop_invalid(f"candidate {r['cid']} ({r['kind']}): {r['exactness5'][:2]}")
            continue
        verified.append(cl5.verified_clear_record(r, cand))
    best = rule5.best_of(verified)
    _todo, info = cl5.plan_replays5(led, T, done, t_rec, margin, batch=99)
    inh_records = [cl5.inherited_record(done_inh[c["cid"]], c) for c in sess.inherited if c["cid"] in done_inh]
    verified_rec: Dict[str, Any] = {"ticks": led.ticks, "t_claimed_online": led.max_t_online, "max_targets": rpt5.replay_verified_t(reps), "pool": info["pool"], "replays": len(reps),
                                    "replay_order": [int(c) for c in done], "verified_clears": verified, "best_verified": best, "remaining": info["remaining"],
                                    "remaining_progress": info["remaining_progress"], "closed": info["closed"], "remaining_faster_than_best": info["remaining_faster_than_best"],
                                    "tiers": rule5.tier_report(None if best is None else int(best["completion_input_tick"]), t_rec), "claims": {}}
    if best is not None:
        bc = cands_by_cid[best["cid"]]
        verified_rec["claims"]["clear"] = {"cid": best["cid"], "kind": bc["kind"], "counted": len(bytes(bc["words"])), "trace": done[best["cid"]]["trace"], "label": done[best["cid"]]["label"],
                                           "t": done[best["cid"]]["t"], "clear_facts": done[best["cid"]].get("clear_facts"), "completion_input_tick": best["completion_input_tick"],
                                           "completion_time_passed": best["completion_time_passed"]}
        save_route5(sess, "T_clear_best", bc, done[best["cid"]], vdir)
        for v in verified:
            if v["cid"] != best["cid"]:
                save_route5(sess, f"T_clear_c{v['cid']:04d}", cands_by_cid[v["cid"]], done[v["cid"]], vdir)
    for c in sess.inherited:
        r = done_inh.get(c["cid"])
        if r is not None and r.get("exact") and not r.get("exactness5"):
            save_route5(sess, f"rd4_inherited_c{c['rd4_cid']:04d}", c, r, vdir)
    rec["arm"] = verified_rec
    rec["inherited_descriptive"] = {"count": len(sess.inherited), "replayed": len(inh_records), "exact": sum(1 for x in inh_records if x["exact"]), "records": inh_records,
                                    "ticks": cl5.inherited_ticks(sess.inherited), "rule": "every clear-event trajectory of rd4's registry that no rd4 replay verified; reported facts only"}
    rec["cap_hit"] = cap_hit or None
    if cap_hit and not sess.invalid and best is None and info["remaining_progress"] > 0:
        sess.incomplete.append(f"{info['remaining_progress']} pool candidate(s) with a registered clear tick at or below {t_rec - margin} were left unverified at a cap before any exact clear replay: {cap_hit}")
    rec["replay_ticks"] = sess.ticks["replays"]
    rec["finished_utc"] = utc()
    write_json5(sess.dir / "verification.json", rec)
    sess.verification = rec
    sess.verified = verified_rec
    sess.inherited_records = inh_records
    sess.clock.end()
    return rec


# -- close checks (zero native ticks), decision --------------------------------------------------------------------------------------------------


def close_checks5(sess: Session5, immutability: Callable[[], Mapping[str, Any]]) -> Tuple[Dict[str, Any], Optional[s5.Archive5], Optional[List[Dict[str, Any]]]]:
    """After the session clock: the final atomic save, the ledger audit of the five parts (which also yields the dispatch rows), the prefix chain rd1 -> rd2 -> rd3 -> rd4 -> sd1, all four earlier
    trees' immutability, the write guard, and the stamp audit of every record written so far. Any failed check is INVALID. Each check runs in its own guard."""
    cfg = sess.cfg
    close: Dict[str, Any] = {"scope": rule5.SCOPE, "started_utc": utc()}
    loaded: Optional[s5.Archive5] = None
    rows: Optional[List[Dict[str, Any]]] = None

    def attempt(name: str, fn: Any) -> Any:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
            close[f"{name}_error"] = f"{type(exc).__name__}: {exc}"
            sess.incomplete.append(f"close check {name} could not run: {type(exc).__name__}: {exc}")
            sess.log(f"close check {name}: {type(exc).__name__}: {exc}\n{traceback.format_exc()[-1200:]}")
            return None

    if sess.archive is not None:
        def final_load() -> s5.Archive5:
            sess.checkpoint("final")
            a, m = s5.Archive5.read_dir(cfg.archive_dir)
            if m.get("created_utc") != sess.archive_created_utc or not art.is_stamped(m):
                sess.stop_invalid(f"archive_meta.json's created_utc {m.get('created_utc')!r} is not the materialisation's {sess.archive_created_utc!r}")
            return a

        loaded = attempt("final_checkpoint", final_load)
        if loaded is not None:
            aud = attempt("audit", lambda: s5.audit5(loaded, sess.lines_sha256, collect_rows_from=sess.first_iteration))
            if aud is not None:
                rows = aud.pop("dispatch_rows")
                close["audit"] = aud
                if not aud["ok"]:
                    sess.stop_invalid(f"close audit: {aud['problems'][:2]}")
                sess.log(f"close audit: ok {aud['ok']} cells {aud['cells']} bursts {aud['bursts']}")
                try:
                    p = sess.dir / "dispatch_rows.jsonl.gz"
                    art.write_jsonl_gz5(p, rows, SCHEMAS["dispatch_rows"])
                    close["dispatch_rows_file"] = p.name
                except OSError as exc:
                    close["dispatch_rows_error"] = f"{type(exc).__name__}: {exc}"
                close["live_seen_at_dispatch"] = {"live": dict(sess.live_seen), "ledger": {"dispatches": len(rows), "seen_ge_8": sum(1 for r_ in rows if int(r_["seen"]) >= rpt5.SEEN_MIN)}}

            def archive_record() -> Dict[str, Any]:
                with loaded.as_v4():
                    stats = loaded.stats()
                rows5 = s5.overlay_rows5(loaded, sess.t_rec, sess.margin)
                return {"stats": stats, "manifest": {n: march.sha256_file(cfg.archive_dir / n) for n in march.DATA_FILES}, "checkpoint_seq": sess.ckpt_seq,
                        "diag2": loaded.diag2 | {"bound_violations": len(loaded.diag2["bound_violations"])}, "overlay_close": s2.overlay_counts(loaded, s2.overlay_rows(loaded)),
                        "overlay_close_v4": s5.overlay_counts5(loaded, rows5, sess.t_rec, sess.margin), "created_utc": sess.archive_created_utc}

            info = attempt("archive_record", archive_record)
            if info is not None:
                close["archive"] = info
        pp = attempt("prefix_chain", lambda: r5.prefix_chain(sess.rd1_root / "archive", sess.rd2_root / "archive", sess.rd3_root / "archive", sess.rd4_root / "archive", cfg.archive_dir))
        if pp is not None:
            close["prefix_chain"] = pp
            if not pp["ok"]:
                sess.stop_invalid(f"prefix chain: {pp['problems'][:2]}")
            sess.log(f"prefix chain {pp['ok']}")
    imm = attempt("earlier_trees_immutability", immutability)
    if imm is not None:
        close["earlier_trees_immutability"] = imm
        if not imm.get("ok"):
            sess.stop_invalid(f"an earlier tree changed: {imm.get('problems', [])[:2]}")
    wv = [v for v in mw.ProvenanceGuard.violations]
    close["guard_violations"] = wv
    if wv:
        sess.stop_invalid(f"guard violations: {wv[:2]}")
    arts = attempt("artifacts", lambda: art.audit_tree5(cfg.root))
    if arts is not None:
        close["artifacts"] = {k: arts[k] for k in ("ok", "files", "headers", "exempt", "failures")}
        if not arts["ok"]:
            sess.stop_invalid(f"records without their stamp: {arts['failures'][:2]}")
    close["finished_utc"] = utc()
    return close, loaded, rows


def decide5(sess: Session5, loaded: Optional[s5.Archive5], rows: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    v = sess.verified
    verified_clears = list(v["verified_clears"]) if v else []
    if v is None and not sess.invalid and not sess.incomplete:
        sess.incomplete.append("the session ended before the claims were verified")
    if sess.ledgers["T"].ticks < sess.cfg.min_arm_ticks:
        reason = f"exploration reached {sess.ledgers['T'].ticks:,} native ticks (< {sess.cfg.min_arm_ticks:,})"
        if reason not in sess.incomplete:
            sess.incomplete.append(reason)
    if loaded is not None and rows is not None:
        ins = rpt5.rule_inputs5(loaded, rows, sess.first_iteration, sess.first_new_cell)
    else:
        ins = {"below_floor": 0, "dispatches": 0, "fatal_returns": 0, "returns": 0, "launch_capable_created": 0, "bound_violations": 0, "top_level_median_L": None, "seen_ge_8_reading": 0,
               "new_cells_reading": 0}
    started = bool(sess.iteration > sess.first_iteration)
    extra = {"verified": v is not None, "exploration_ticks": sess.ledgers["T"].ticks, "rule_inputs": ins, "first_iteration": sess.first_iteration, "first_new_cell": sess.first_new_cell,
             "record_open": {k: sess.record_open_record.get(k) for k in ("exact", "clear_facts", "words")}, "open_identity": {k: sess.open_identity_record.get(k) for k in ("cells", "verified", "ok")},
             "prior_sessions_read_from": "sessions/<rd>/rule.json of rd1, rd2, rd3 and rd4"}
    rec = rule5.apply(invalid=sess.invalid, incomplete=sorted(set(sess.incomplete)), verified_clears=verified_clears, t_rec=sess.t_rec, t_rec_time_passed=sess.t_rec_time_passed, margin=sess.margin,
                      exploration_started=started, exploration_ticks=sess.ledgers["T"].ticks, returns=ins["returns"], dispatches=ins["dispatches"], below_floor=ins["below_floor"],
                      fatal_returns=ins["fatal_returns"], launch_capable_created=ins["launch_capable_created"], bound_violations=ins["bound_violations"], top_level_median_L=ins["top_level_median_L"],
                      inherited_descriptive=sess.inherited_records, rd4_line=sess.rd4_line, claims_verified=v is not None, max_targets=(v["max_targets"] if v else 0),
                      t_claimed_online=sess.ledgers["T"].max_t_online, extra=extra)
    write_json5(sess.dir / "rule.json", rec)
    b = rec["best_verified"]
    sess.log(f"DECISION {rec['outcome']}: best verified {b and (b['completion_input_tick'], b['completion_time_passed'])} against {sess.t_rec} - {sess.margin} = {sess.t_rec - sess.margin}; "
             f"{len(verified_clears)} verified clears; flags {rec['flags']}; line {rec['line']['status']}; stops {rec['any_stop']}; invalid {rec['invalid'][:2]} incomplete {rec['incomplete'][:2]}")
    return rec


def run_all5(sess: Session5, immutability: Callable[[], Mapping[str, Any]]) -> Dict[str, Any]:
    """The whole session after S0: open (P1 + identity + the record re-verified), exploration, verification, then the close checks and the decision. Every stop is a recorded outcome;
    nothing is retried."""
    cfg = sess.cfg
    sess.save_state(phase="start")
    try:
        sess.clock.begin("p1")
        sess.pool.start(cfg.n_workers)
        sess.p1()
        sess.open_identity()
        sess.open_record_replay()
        rec = sess.run_arm("T")
        sess.finish_arm_record(rec)
        if not sess.invalid and not sess.incomplete:
            verify_phase5(sess)
    except IntegrityStop as exc:
        sess.stop_invalid(str(exc))
    except CapStop as exc:
        sess.incomplete.append(str(exc))
        sess.log(f"INCOMPLETE: {exc}")
    except Exception as exc:  # noqa: BLE001 - a software error is recorded, never swallowed
        sess.incomplete.append(f"session error: {type(exc).__name__}: {exc}")
        sess.log(f"SESSION ERROR: {type(exc).__name__}: {exc}\n{traceback.format_exc()[-2500:]}")
    finally:
        sess.clock.end()
        try:
            sess.pool.abort.set()
            sess.pool.stop()
        except Exception as exc:  # noqa: BLE001
            sess.log(f"pool stop: {type(exc).__name__}: {exc}")
    loaded: Optional[s5.Archive5] = None
    rows: Optional[List[Dict[str, Any]]] = None
    try:
        close, loaded, rows = close_checks5(sess, immutability)
    except Exception as exc:  # noqa: BLE001
        close = {"scope": rule5.SCOPE, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-2000:]}
        sess.incomplete.append(f"close error: {type(exc).__name__}: {exc}")
    try:
        write_json5(sess.dir / "close.json", close)
    except Exception as exc:  # noqa: BLE001
        sess.log(f"close.json: {type(exc).__name__}: {exc}")
    try:
        rule_record = decide5(sess, loaded, rows)
    except Exception as exc:  # noqa: BLE001 - a decision record is ALWAYS written
        sess.incomplete.append(f"decision error: {type(exc).__name__}: {exc}")
        sess.log(f"DECISION ERROR: {type(exc).__name__}: {exc}\n{traceback.format_exc()[-1500:]}")
        rule_record = rule5.apply(invalid=sess.invalid, incomplete=sorted(set(sess.incomplete)), verified_clears=[], t_rec=sess.t_rec, t_rec_time_passed=sess.t_rec_time_passed, margin=sess.margin,
                                  exploration_started=bool(sess.iteration > sess.first_iteration), exploration_ticks=sess.ledgers["T"].ticks, returns=0, dispatches=0, below_floor=0, fatal_returns=0,
                                  launch_capable_created=0, rd4_line=sess.rd4_line, claims_verified=False, extra={"decision_error": f"{type(exc).__name__}: {exc}"})
        write_json5(sess.dir / "rule.json", rule_record)
    sess.save_state(phase="done", decision=rule_record["outcome"])
    return {"rule": rule_record, "close": close}
