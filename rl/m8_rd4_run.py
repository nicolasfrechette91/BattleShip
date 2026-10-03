"""M8-rd4 run engine: the open (P1 against the archive's pin, identity replays), single-arm exploration under `m8_rd_select_v3` with rd4's keyed draws, verification with the claim-path
guards, the close checks of the three-level continuation, the decision under `m8_rd4_rule_v1`.

It subclasses rd3's `Session3` (itself a subclass of rd2's `Session2` and rd1's `Session`; all unchanged) and overrides what is specific to the third continuation: the archive is an `Archive4`
(draw id and weights by iteration), the identity samples use rd4's keys, the records carry rd4's scope, the verification plans its replays with `m8_rd4_claims` (the guard against a flood of
inherited left-of-wall candidates), the close checks audit the four-part ledger and the prefix chain rd1 -> rd2 -> rd3 -> rd4 and require ALL THREE earlier trees to be unchanged, and the decision
applies the registered rule, the mechanism check and the line budget. Every write goes under rd4's own root; the write guard turns any write under an earlier tree into an INVALID stop.

The wall-top label is suppressed exactly as in rd3 (`m8_rd3_run.suppress_wall_top_label`, applied in `Session3.commit`, which Session4 inherits): a burst that continues from a prefix standing on floor
line 0 must not register an `l0` candidate (the frozen engine would judge its replay inexact: a false INVALID). Left-of-wall continuations need no suppression (see rl/m8_rd4_claims.py).

Light top-level imports only: spawned workers re-import the launching script.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import queue
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
import m8_rd4_claims as cl4  # noqa: E402
import m8_rd4_report as rpt4  # noqa: E402
import m8_rd4_resume as r4  # noqa: E402
import m8_rd4_rule as rule4  # noqa: E402
import m8_rd4_select as s4  # noqa: E402
from m8_rd_run import CapStop, IntegrityStop, append_jsonl, utc, write_json  # noqa: E402

RUN4_CONTRACT = "m8_rd4_run_v1"
OPEN_IDENTITY_BASE = 6_000_000
CLOSE_IDENTITY_BASE = 7_000_000
SESSION_ID = "rd4"
WorkerPool4 = run2.WorkerPool2                          # the same pool (it spawns the rd2 worker, which takes the protected roots from the worker spec)
WriteGuard = w2.WriteGuard
identity_job = run2.identity_job
suppress_wall_top_label = run3.suppress_wall_top_label


# -- identity samples (rd2's and rd3's designs, rd4's keys) -------------------------------------------------------------------------------------------


def _kh(a: march.Archive, tag: str, c: march.Cell) -> bytes:
    return hashlib.sha256(f"m8_rd|{a.archive_id}|{tag}|{c.id}".encode()).digest()


def identity_sample_open(a: s4.Archive4, k: int = 16) -> Dict[str, Any]:
    """The open identity replays: the shortest cell of each of the top three levels; the four highest-weight (v3) eligible cells at the open; four keyed-random cells among the launch-capable and
    the A2-at-y>=0 cells (keys `m8_rd|<archive id>|identity_open|rd4|<cell id>`); five keyed-random eligible cells; topped up from the keyed eligible cells to K when a pool runs short."""
    cells = [c for c in a.cells if c.id != 0]
    chosen: List[Tuple[str, march.Cell]] = []

    def add(name: str, c: march.Cell) -> None:
        if all(c.id != x.id for _n, x in chosen) and len(chosen) < k:
            chosen.append((name, c))

    for lv in sorted({c.level for c in cells}, reverse=True)[:3]:
        pool = [c for c in cells if c.level == lv]
        add(f"top_level_{lv}", min(pool, key=lambda c: (c.L, c.id)))
    probs = a.probabilities() if a.mode == 2 else {}
    for cid in [i for i in sorted(probs, key=lambda i: (-probs[i], i)) if i != 0][:4]:           # cell 0 is covered by P1
        add("highest_weight", a.cells[cid])
    hi = [c for c in cells if rpt2.is_launch_capable(c.key[2], float(c.end[mcell.I_Y])) or (c.key[2] == mcell.RES_A2 and float(c.end[mcell.I_Y]) >= 0)]
    n0 = len(chosen)
    for c in sorted(hi, key=lambda c: _kh(a, "identity_open|rd4", c)):
        if len(chosen) >= n0 + 4:
            break
        add("keyed_launch_or_a2_high", c)
    elig = sorted((c for c in cells if a.eligible(c)), key=lambda c: _kh(a, "identity_open|rd4", c))
    n0 = len(chosen)
    for c in elig:
        if len(chosen) >= n0 + 5:
            break
        add("keyed_eligible", c)
    for c in elig:
        add("keyed_eligible_topup", c)
    return {"cells": [c for _n, c in chosen], "names": [n for n, _c in chosen]}


def identity_sample_close(a: march.Archive, k: int = 16) -> Dict[str, Any]:
    """The close identity replays: the milestone cells first (the shortest wall-top, left-of-wall and left-target-broken cells), the shortest cell of each of the top three levels, then
    keyed-random cells (`m8_rd|<archive id>|identity_close|rd4|<cell id>`)."""
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
    for c in sorted((c for c in cells if all(c.id != x.id for _n, x in chosen)), key=lambda c: _kh(a, "identity_close|rd4", c)):
        if len(chosen) >= k:
            break
        chosen.append(("keyed_random", c))
    return {"cells": [c for _n, c in chosen[:k]], "names": [n for n, _c in chosen[:k]]}


# -- the session -------------------------------------------------------------------------------------------------------------------------------------


class Session4(run3.Session3):
    def __init__(self, cfg: mrun.RunConfig, env: mrun.RunEnv, *, archive: s4.Archive4, archive_pin: Mapping[str, Any], base_info: Mapping[str, Any], rd1_root: Path, rd2_root: Path,
                 rd3_root: Path, lines_sha256: str, ckpt_seq: int):
        if archive.rd4_first_iteration is None:
            raise RuntimeError("rd4 opens an archive that has begun rd4 (the materialised checkpoint)")
        run2.Session2.__init__(self, cfg, env, archive=archive, archive_pin=archive_pin, base_info=base_info, rd1_root=rd1_root, lines_sha256=lines_sha256)
        self.rd2_root = Path(rd2_root)
        self.rd3_root = Path(rd3_root)
        self.ckpt_seq = int(ckpt_seq)                        # the materialised checkpoint (open) is sequence 33
        self.first_iteration = int(archive.rd4_first_iteration)
        self.iteration = self.first_iteration
        self.first_new_cell = len(archive.cells)
        self.wall_top_sightings: List[Dict[str, Any]] = []
        self.live_seen = {"dispatches": 0, "seen_ge_8": 0}
        self.state["scope"] = rule4.SCOPE

    # -- open ----------------------------------------------------------------------------------------------------------------------

    def p1(self) -> None:
        """P1 against the ARCHIVE's pin: the tick-0 record of two processes equals `pin_tick0`; the two pinned Track 1 traces word for word; the return self-test in a scratch archive
        including the refused corrupted end record."""
        cfg = self.cfg
        self.clock.begin("p1")
        self.state["phase"] = "p1"
        rec: Dict[str, Any] = {"started_utc": utc(), "scope": rule4.SCOPE, "pin": "the archive's pin_tick0"}
        pin = dict(self.archive_pin)
        first = self.run_batch([{"kind": "tick0", "pin": pin}], "p1", "p1", cfg.p1_tick_cap)[0]
        if not first.get("ok"):
            raise self._p1_failure("tick0 against the archive pin", first)
        second = self.run_batch([{"kind": "tick0", "pin": pin}], "p1", "p1", cfg.p1_tick_cap)[0]
        if not second.get("ok"):
            raise self._p1_failure("tick0 reproduction", second)
        self.pin = pin
        rec["tick0"] = {"digest": pin["digest"], "lines_digest": pin["lines"], "modes": [first["mode"], second["mode"]],
                        "host_frames": [first["tick0"]["host_frame"], second["tick0"]["host_frame"]],
                        "host_frame_equal": second["tick0"].get("host_frame_equal"), "equals_archive_pin": True}
        self.log(f"P1 tick-0 record equals the archive pin {pin['digest'][:12]} (modes {rec['tick0']['modes']})")
        traces = self.env.p1_inputs()
        jobs = [{"kind": "trace", "name": t["name"], "words": t["words"], "expected_digests": t["expected_digests"],
                 "expected_host_frames": t.get("expected_host_frames"), "pin": pin, "allowance": len(t["words"])} for t in traces]
        selftest = self.selftest_prepare()
        results = self.run_batch(jobs + selftest["burst_jobs"], "p1", "p1", cfg.p1_tick_cap)
        trace_res = results[:len(traces)]
        for t, r in zip(traces, trace_res):
            if not r.get("ok"):
                raise self._p1_failure(f"trace {t['name']}", r)
            if r["native_action_digest"] != t["native_action_digest"]:
                raise IntegrityStop(f"P1 trace {t['name']}: native action digest {r['native_action_digest'][:12]} differs from "
                                    f"the pinned {t['native_action_digest'][:12]}")
        rec["traces"] = [{"name": r["name"], "words": r["words"], "native_action_digest": r["native_action_digest"],
                          "host_frames_equal": r["host_frames_equal"], "end_reason": r["end_reason"], "mode": r["mode"]} for r in trace_res]
        burst = results[len(traces)]
        if not burst.get("ok"):
            raise self._p1_failure("self-test burst", burst)
        rec["selftest"] = self.selftest_returns(burst, selftest)
        rec["ticks"] = self.ticks["p1"]
        rec["finished_utc"] = utc()
        self.p1_record = rec
        write_json(self.dir / "p1.json", rec)
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
        self.open_identity_record = {"scope": rule4.SCOPE, "cells": len(jobs), "names": samp["names"], "cell_ids": [c.id for c in samp["cells"]], "verified": okn,
                                     "ticks": sum(int(r.get("ticks", 0)) for r in results), "ok": okn == len(jobs), "utc": utc()}
        write_json(self.dir / "identity_open.json", self.open_identity_record)
        self.save_state(open_identity="PASS")
        self.log(f"open identity replays: {okn} / {len(jobs)} returned exactly ({self.ticks['p1']} open ticks)")

    # -- exploration ------------------------------------------------------------------------------------------------------------------

    def make_job(self, arm: str, w: int, remaining: int) -> Dict[str, Any]:
        assert arm == "T", "rd4 has one arm"
        cfg = self.cfg
        it = self.iteration
        self.iteration += 1
        assert self.archive is not None
        t0 = time.perf_counter()
        cell = self.archive.dispatch(it, w)
        self.select_s += time.perf_counter() - t0
        self.live_seen["dispatches"] += 1
        self.live_seen["seen_ge_8"] += int(cell.seen >= rule4.SEEN_MIN)
        want = cell.L + min(cfg.burst_words, cfg.horizon - cell.L)
        job = {"kind": w2.JOB_KIND, "arm": "T", "iteration": it, "cell": cell.id, "rep": (cell.burst, cell.offset),
               "words": self.archive.cell_words(cell), "end": cell.end, "end_digest": cell.end_digest, "chain": cell.chain,
               "terminal": cell.terminal, "pin": self.pin, "archive_id": self.archive.draw_for(it), "burst_words": cfg.burst_words,
               "allowance": min(want, remaining), "level": cell.level, "L": cell.L}
        self.pool_job[w] = job
        return job

    def finish_arm_record(self, rec: Dict[str, Any]) -> None:
        rec["scope"] = rule4.SCOPE
        rec["select_s"] = round(self.select_s, 3)
        rec["first_iteration"] = self.first_iteration
        rec["next_iteration"] = self.iteration
        rec["dispatches"] = self.iteration - self.first_iteration
        rec["live_seen_at_dispatch"] = dict(self.live_seen)
        rec["pools"] = cl4.pool_sizes(self.ledgers["T"], self.ledgers["T"].ticks)           # visible even when the verification is skipped (an INCOMPLETE exploration)
        rec["wall_top_sightings"] = {"bursts": len(self.wall_top_sightings), "from_a_wall_top_start": sum(1 for x in self.wall_top_sightings if x["start_cell_on_wall_top"]),
                                     "from_another_start": sum(1 for x in self.wall_top_sightings if not x["start_cell_on_wall_top"])}
        write_json(self.dir / "arm_T.json", rec)


# -- verification ----------------------------------------------------------------------------------------------------------------------------------


def verify_phase4(sess: Session4) -> Dict[str, Any]:
    """rd3's verification with the replay plan of `m8_rd4_claims`: the can-raise candidates first (round-robin over the unsatisfied milestones, discovery order), the maximum-targets candidate
    always, a few descriptive left entries last; the INCOMPLETE test reads only candidates that could raise m."""
    cfg, env = sess.cfg, sess.env
    sess.state["phase"] = "verify"
    led = sess.ledgers["T"]
    T = led.ticks                                              # every candidate of the session counts
    if led.ticks < cfg.min_arm_ticks:
        sess.incomplete.append(f"exploration reached {led.ticks:,} native ticks (< {cfg.min_arm_ticks:,})")
    rec: Dict[str, Any] = {"scope": rule4.SCOPE, "started_utc": utc(), "exploration_ticks": T, "arm": None, "identity": None, "cap_hit": None, "pools": cl4.pool_sizes(led, T),
                           "claims_contract": cl4.CLAIMS4_CONTRACT, "claims_digest": cl4.contract_digest()}
    sess.log(f"verification: {len(led.candidates)} candidates over {T:,} exploration ticks; pools {rec['pools']}")
    sess.clock.begin("verify")
    sess.pool.retire(list(range(cfg.verify_threads, cfg.n_workers)))
    vdir = sess.dir / "verification"
    done: Dict[int, Dict[str, Any]] = {}
    cap_hit: List[str] = []
    free_slots: "queue.Queue[int]" = queue.Queue()
    for s_ in range(cfg.verify_threads):
        free_slots.put(s_)

    def run_one(cand: Mapping[str, Any], counted: int) -> Dict[str, Any]:
        slot = free_slots.get()
        label = f"T_c{cand['cid']:04d}_{cand['kind']}"
        try:
            try:
                trace = env.replay(cand, counted, label, slot)
            except Exception as exc:  # noqa: BLE001
                return {"cid": cand["cid"], "arm": "T", "kind": cand["kind"], "counted": counted, "exact": False, "error": True, "label": label,
                        "problems": [f"replay failed: {type(exc).__name__}: {exc}"], "t": 0, "l0": False, "crossing": False,
                        "left_target": False, "clear": False}
            fin._save_trace(vdir / f"{label}.json.gz", trace)
            rep = mclaims.evaluate_replay(trace, cand, counted, env.analyse)
            rep["label"] = label
            rep["trace"] = f"{label}.json.gz"
            rep["raises"] = cl4.raises(cand)
            rep["descriptive"] = cl4.is_descriptive(cand)
            return rep
        finally:
            free_slots.put(slot)

    def claims() -> None:
        with ThreadPoolExecutor(max_workers=cfg.verify_threads) as ex:
            while True:
                try:
                    sess.clock.check()
                except CapStop as exc:
                    cap_hit.append(f"claims: {exc}")
                    return
                todo, _info = cl4.plan_replays4(led, T, done, batch=cfg.verify_threads)
                if not todo:
                    return
                need = sum(n for _c, n in todo)
                with sess.tick_lock:
                    if sess.ticks["replays"] + need > cfg.replay_tick_cap:
                        cap_hit.append(f"claims: replay cap {cfg.replay_tick_cap:,} ticks ({sess.ticks['replays']:,} used, {need:,} more needed)")
                        return
                    sess.ticks["replays"] += need
                futs = [(c, ex.submit(run_one, c, n)) for c, n in todo]
                for c, f in futs:
                    r = f.result()
                    done[c["cid"]] = r
                    append_jsonl(vdir / "replays.jsonl", {k: v for k, v in r.items() if k not in ("breaks",)})

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

    t_claims = threading.Thread(target=guarded, args=(claims,), name="m8rd4-claims")
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
    for r in reps:
        if not r["exact"]:
            if r.get("error"):
                sess.incomplete.append(f"candidate {r['cid']}: {r['problems'][0][:200]}")
            else:
                sess.stop_invalid(f"candidate {r['cid']} ({r['kind']}): inexact replay: {r['problems'][:2]}")
    t_claimed, t_cand, _t_n = led.t_within(T)
    t_rep = next((r for r in reps if t_cand is not None and r["cid"] == t_cand["cid"]), None)
    t_verified = t_claimed if (t_cand is not None and t_rep is not None and t_rep["exact"]) else 0
    max_targets = max(t_verified, rpt4.replay_verified_t(reps))
    m = rpt4.replay_verified_m(reps)                           # crossing / left target / clear; the wall-top landing is rd2's and is not re-claimed (suppress_wall_top_label)
    _todo, info = cl4.plan_replays4(led, T, done, batch=99)
    mmu = cl4.max_m_unverified(info)
    verified: Dict[str, Any] = {"ticks": led.ticks, "t_claimed_online": t_claimed, "t": t_verified, "max_targets": max_targets, "m": m, "milestone": mclaims.LADDER[m],
                                "replays": len(reps), "remaining_unverified": info["remaining"], "max_m_unverified": mmu, "satisfied": info["satisfied"], "claims": {},
                                "descriptive": {k: info[k] for k in ("descriptive_total", "descriptive_replayed", "descriptive_allowance")}}
    for name in ("t",) + tuple(n for n in fin.MILESTONE_CLAIMS if n != "L0"):
        if name == "t":
            first = t_rep if (t_rep is not None and t_rep["exact"]) else None
        else:
            first = next((r for r in sorted(reps, key=lambda x: x["cid"]) if r["exact"] and mclaims.levels_of(r)[name]), None)
        if first is not None:
            verified["claims"][name] = {"cid": first["cid"], "kind": first["kind"], "counted": first["counted"], "trace": first["trace"],
                                        "label": first["label"], "t": first["t"],
                                        "clear_facts": first.get("clear_facts") if name == "clear" else None,
                                        "first_qualified_entry": first.get("first_qualified_entry") if name == "crossing" else None}
            fin.save_route(sess, "T", name, led, first, vdir)
    rec["arm"] = verified
    rec["cap_hit"] = cap_hit or None
    if t_cand is not None and t_rep is None:
        rec["max_t_candidate_unverified"] = True
    if cap_hit and not sess.invalid and mmu > m:
        sess.incomplete.append(f"a candidate that could raise m ({mclaims.LADDER[mmu]}) was left unverified at a cap: {cap_hit}")
    rec["replay_ticks"] = sess.ticks["replays"]
    rec["finished_utc"] = utc()
    write_json(sess.dir / "verification.json", rec)
    sess.verification = rec
    sess.verified = verified
    sess.clock.end()
    return rec


# -- close checks (zero native ticks), decision --------------------------------------------------------------------------------------------------


def close_checks(sess: Session4, immutability: Callable[[], Mapping[str, Any]]) -> Tuple[Dict[str, Any], Optional[s4.Archive4], Optional[List[Dict[str, Any]]]]:
    """After the session clock: the final atomic save, the ledger audit of the four parts (which also yields the dispatch rows of the mechanism check), the prefix chain rd1 -> rd2 -> rd3 ->
    rd4, all three earlier trees' immutability and the write guard. Any failed check is INVALID. Each check runs in its own guard, so a software error in one (recorded, and INCOMPLETE) can
    never hide the others. `immutability` is a callable returning {"ok", "problems", ...}. Returns the close record, the reloaded final archive (None if it could not be loaded) and the dispatch
    rows of rd4 (None if the audit could not run)."""
    cfg = sess.cfg
    close: Dict[str, Any] = {"scope": rule4.SCOPE, "started_utc": utc()}
    loaded: Optional[s4.Archive4] = None
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
        def final_load() -> s4.Archive4:
            sess.checkpoint("final")
            a, _m = s4.Archive4.read_dir(cfg.archive_dir)
            return a

        loaded = attempt("final_checkpoint", final_load)
        if loaded is not None:
            aud = attempt("audit", lambda: s4.audit4(loaded, sess.lines_sha256, collect_rows_from=sess.first_iteration))
            if aud is not None:
                rows = aud.pop("dispatch_rows")
                close["audit"] = aud
                if not aud["ok"]:
                    sess.stop_invalid(f"close audit: {aud['problems'][:2]}")
                sess.log(f"close audit: ok {aud['ok']} cells {aud['cells']} bursts {aud['bursts']}")
                try:
                    p = sess.dir / "dispatch_rows.jsonl.gz"
                    with gzip.open(p, "wt", encoding="utf-8") as f:
                        for r_ in rows:
                            f.write(json.dumps(r_, separators=(",", ":")) + "\n")
                    close["dispatch_rows_file"] = p.name
                except OSError as exc:
                    close["dispatch_rows_error"] = f"{type(exc).__name__}: {exc}"
                close["live_seen_at_dispatch"] = {"live": dict(sess.live_seen), "ledger": {"dispatches": len(rows), "seen_ge_8": sum(1 for r_ in rows if int(r_["seen"]) >= rule4.SEEN_MIN)}}
            info = attempt("archive_record", lambda: {
                "stats": loaded.stats(), "manifest": {n: march.sha256_file(cfg.archive_dir / n) for n in march.DATA_FILES},
                "checkpoint_seq": sess.ckpt_seq, "diag2": loaded.diag2 | {"bound_violations": len(loaded.diag2["bound_violations"])},
                "overlay_close": s2.overlay_counts(loaded, s2.overlay_rows(loaded))})
            if info is not None:
                close["archive"] = info
        pp = attempt("prefix_chain", lambda: r4.prefix_chain(sess.rd1_root / "archive", sess.rd2_root / "archive", sess.rd3_root / "archive", cfg.archive_dir))
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
    close["finished_utc"] = utc()
    return close, loaded, rows


def decide4(sess: Session4, loaded: Optional[s4.Archive4], rows: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    v = sess.verified
    m = v["m"] if v else 0
    t = v["max_targets"] if v else 0
    if v is None and not sess.invalid and not sess.incomplete:
        sess.incomplete.append("the session ended before the claims were verified")
    if sess.ledgers["T"].ticks < sess.cfg.min_arm_ticks:
        reason = f"exploration reached {sess.ledgers['T'].ticks:,} native ticks (< {sess.cfg.min_arm_ticks:,})"
        if reason not in sess.incomplete:
            sess.incomplete.append(reason)
    if loaded is not None and rows is not None:
        ins = rpt4.rule_inputs4(loaded, rows, sess.first_iteration, sess.first_new_cell)
    else:
        ins = {"below_floor": 0, "dispatches": 0, "fatal_returns": 0, "returns": 0, "launch_capable_created": 0, "bound_violations": 0, "top_level_median_L": None, "seen_ge_8": 0,
               "new_cells": 0}
    prior = r4.prior_milestones(sess.rd1_root, sess.rd2_root, sess.rd3_root)
    started = bool(sess.iteration > sess.first_iteration)
    extra = {"verified": v is not None, "exploration_ticks": sess.ledgers["T"].ticks, "rule_inputs": ins, "first_iteration": sess.first_iteration,
             "first_new_cell": sess.first_new_cell, "prior_sessions_read_from": {k: (p or {}).get("source") for k, p in prior.items()}}
    rec = rule4.apply(invalid=sess.invalid, incomplete=sorted(set(sess.incomplete)), m=m, t=t, prior=prior, extra=extra, claims_verified=v is not None, exploration_started=started,
                      exploration_ticks=sess.ledgers["T"].ticks, **ins)
    write_json(sess.dir / "rule.json", rec)
    sess.log(f"DECISION {rec['outcome']}: m {rec['m']} max targets {rec['max_targets_verified']} mechanism {rec['mechanism']['verdict']} "
             f"(seen>=8 {ins['seen_ge_8']}/{ins['returns']}, new cells {ins['new_cells']}) line {rec['line']['status']} stops {rec['any_stop']} "
             f"below-floor {ins['below_floor']}/{ins['dispatches']} fatal {ins['fatal_returns']}/{ins['returns']} invalid {rec['invalid'][:2]} incomplete {rec['incomplete'][:2]}")
    return rec


def run_all4(sess: Session4, immutability: Callable[[], Mapping[str, Any]]) -> Dict[str, Any]:
    """The whole session after S0: open (P1 + identity), exploration, verification, then the close checks and the decision. Every stop is a recorded outcome; nothing is retried."""
    cfg = sess.cfg
    sess.save_state(phase="start")
    try:
        sess.clock.begin("p1")
        sess.pool.start(cfg.n_workers)
        sess.p1()
        sess.open_identity()
        rec = sess.run_arm("T")
        sess.finish_arm_record(rec)
        if not sess.invalid and not sess.incomplete:
            verify_phase4(sess)
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
    loaded: Optional[s4.Archive4] = None
    rows: Optional[List[Dict[str, Any]]] = None
    try:
        close, loaded, rows = close_checks(sess, immutability)
    except Exception as exc:  # noqa: BLE001
        close = {"scope": rule4.SCOPE, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-2000:]}
        sess.incomplete.append(f"close error: {type(exc).__name__}: {exc}")
    try:
        write_json(sess.dir / "close.json", close)
    except Exception as exc:  # noqa: BLE001
        sess.log(f"close.json: {type(exc).__name__}: {exc}")
    try:
        rule_record = decide4(sess, loaded, rows)
    except Exception as exc:  # noqa: BLE001 - a decision record is ALWAYS written
        sess.incomplete.append(f"decision error: {type(exc).__name__}: {exc}")
        sess.log(f"DECISION ERROR: {type(exc).__name__}: {exc}\n{traceback.format_exc()[-1500:]}")
        rule_record = rule4.apply(invalid=sess.invalid, incomplete=sorted(set(sess.incomplete)), m=0, t=0, below_floor=0, dispatches=0, fatal_returns=0, returns=0, seen_ge_8=0,
                                  new_cells=0, launch_capable_created=0, prior={"rd1": {"m": 0}, "rd2": {"m": 1}, "rd3": {"m": 0}}, claims_verified=False,
                                  exploration_started=bool(sess.iteration > sess.first_iteration), exploration_ticks=sess.ledgers["T"].ticks,
                                  extra={"decision_error": f"{type(exc).__name__}: {exc}", "prior_sessions_read_from": "the registered values (the recorded files could not be read)"})
        write_json(sess.dir / "rule.json", rule_record)
    sess.save_state(phase="done", decision=rule_record["outcome"])
    return {"rule": rule_record, "close": close}
