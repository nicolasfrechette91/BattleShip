"""M8-rd: the verification phase, the decision and the S2 close of a session (continuation of m8_rd_run.Session).

Verification (proposal section 7.4, 11.2, 11.4): after both arms, the comparison point T = the slower arm's cumulative tick
count; the claims of each arm within T are verified by fresh-process replays from tick 0 (<= 3 concurrent replays, all four
read-only diagnostics, every raw reply kept) in discovery order per milestone until one qualifies, together with the close
identity replays (K = 16 archive cells returned from fresh processes with the section 7.3 checks). The replay cap is 400,000
ticks for both. An inexact replay is INVALID; unverified candidates left at a cap make the session INCOMPLETE only when they
could change the outcome.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import queue
import shutil
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import m8_rd_archive as march
import m8_rd_cells as mcell
import m8_rd_claims as mclaims
import m8_rd_rule as mrule
import m8_rd_run as mrun
from m8_rd_run import CapStop, IntegrityStop, Session, append_jsonl, utc, write_json

IDENTITY_ITERATION_BASE = 1_000_000
MILESTONE_CLAIMS = ("clear", "left_target", "crossing", "L0")


def identity_sample(archive: march.Archive, k: int) -> Dict[str, Any]:
    """The close identity replays' cells: the milestone cells first (the shortest wall-top cell, the shortest left-of-wall
    cell, the shortest cell with a left target broken, and the shortest cell of each of the top three progress levels),
    then keyed random cells (sha256 of 'm8_rd|<archive id>|identity|<cell id>') up to K. Cell 0 is covered by P1."""
    cells = [c for c in archive.cells if c.id != 0]
    chosen: List[Tuple[str, march.Cell]] = []

    def shortest(pred, name: str) -> None:
        pool = [c for c in cells if pred(c) and all(c.id != x.id for _n, x in chosen)]
        if pool:
            chosen.append((name, min(pool, key=lambda c: (c.L, c.id))))

    shortest(lambda c: c.key[2] == mcell.RES_GROUNDED and c.key[4] == mcell.L0_FLOOR_LINE, "wall_top")
    shortest(lambda c: c.key[0] <= -8, "left_of_wall")
    shortest(lambda c: any(not (c.key[3] >> i) & 1 for i in mcell.LEFT_TARGET_IDS), "left_target_broken")
    top = sorted({c.level for c in cells}, reverse=True)[:3]
    for lv in top:
        shortest(lambda c, lv=lv: c.level == lv, f"top_level_{lv}")
    rest = sorted((c for c in cells if all(c.id != x.id for _n, x in chosen)),
                  key=lambda c: hashlib.sha256(f"m8_rd|{archive.archive_id}|identity|{c.id}".encode()).digest())
    for c in rest:
        if len(chosen) >= k:
            break
        chosen.append(("keyed_random", c))
    return {"cells": [c for _n, c in chosen[:k]], "names": [n for n, _c in chosen[:k]]}


def _save_trace(path: Path, trace: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fp:
        json.dump(trace, fp, separators=(",", ":"), default=str)


def verify_phase(sess: Session) -> Dict[str, Any]:
    cfg, env = sess.cfg, sess.env
    sess.state["phase"] = "verify"
    led_T, led_C = sess.ledgers["T"], sess.ledgers["C"]
    cp = mrule.comparison_point(led_T.ticks, led_C.ticks, cfg.min_arm_ticks)
    T = cp["T"]
    sess.incomplete.extend(cp["incomplete"])
    rec: Dict[str, Any] = {"comparison_point": cp, "started_utc": utc(), "arms": {}, "identity": None, "cap_hit": None}
    sess.log(f"verification: comparison point T = {T:,} (slower arm {cp['slower']}); arm T {led_T.ticks:,}, arm C {led_C.ticks:,}")
    sess.clock.begin("verify")
    sess.pool.retire(list(range(cfg.verify_threads, cfg.n_workers)))
    vdir = sess.dir / "verification"
    done: Dict[str, Dict[int, Dict[str, Any]]] = {"T": {}, "C": {}}
    cap_hit: List[str] = []
    free_slots: "queue.Queue[int]" = queue.Queue()
    for s_ in range(cfg.verify_threads):
        free_slots.put(s_)

    def run_one(arm: str, cand: Mapping[str, Any], counted: int) -> Dict[str, Any]:
        slot = free_slots.get()                    # a replay slot is one port-block rank: never two live replays on one
        label = f"{arm}_c{cand['cid']:04d}_{cand['kind']}"
        try:
            return _run_one(arm, cand, counted, slot, label)
        finally:
            free_slots.put(slot)

    def _run_one(arm: str, cand: Mapping[str, Any], counted: int, slot: int, label: str) -> Dict[str, Any]:
        try:
            trace = env.replay(cand, counted, label, slot)
        except Exception as exc:  # noqa: BLE001
            return {"cid": cand["cid"], "arm": arm, "kind": cand["kind"], "counted": counted, "exact": False, "error": True,
                    "label": label,
                    "problems": [f"replay failed: {type(exc).__name__}: {exc}"], "t": 0, "l0": False, "crossing": False,
                    "left_target": False, "clear": False}
        _save_trace(vdir / f"{label}.json.gz", trace)
        rep = mclaims.evaluate_replay(trace, cand, counted, env.analyse)
        rep["label"] = label
        rep["trace"] = str((vdir / f"{label}.json.gz").name)
        return rep

    def claims() -> None:
        with ThreadPoolExecutor(max_workers=cfg.verify_threads) as ex:
            def run_batch(items: Sequence[Tuple[str, Dict[str, Any], int]]) -> bool:
                """Replay one batch ((arm, candidate, counted words)); False when a cap stopped it."""
                try:
                    sess.clock.check()
                except CapStop as exc:
                    cap_hit.append(f"claims: {exc}")
                    return False
                need = sum(n for _a, _c, n in items)
                with sess.tick_lock:
                    if sess.ticks["replays"] + need > cfg.replay_tick_cap:
                        cap_hit.append(f"claims: replay cap {cfg.replay_tick_cap:,} ticks "
                                       f"({sess.ticks['replays']:,} used, {need:,} more needed)")
                        return False
                    sess.ticks["replays"] += need
                futs = [(a, c, ex.submit(run_one, a, c, n)) for a, c, n in items]
                for a, c, f in futs:
                    r = f.result()
                    done[a][c["cid"]] = r
                    append_jsonl(vdir / "replays.jsonl", {k: v for k, v in r.items() if k not in ("breaks",)})
                return True

            # 1. each arm's maximum-targets candidate first (so a cap can never leave one arm's t unverified because the
            #    other arm's milestone pools came first), then 2. the milestone pools, one batch per arm in turn
            first = []
            for arm in ("T", "C"):
                _t, tc, tn = sess.ledgers[arm].t_within(T)
                if tc is not None:
                    first.append((arm, tc, tn))
            if first and not run_batch(first):
                return
            active = ["T", "C"]
            while active:
                for arm in list(active):
                    todo, _info = mclaims.plan_replays(sess.ledgers[arm], T, done[arm], batch=cfg.verify_threads)
                    if not todo:
                        active.remove(arm)
                        continue
                    if not run_batch([(arm, c, n) for c, n in todo]):
                        return

    ident_out: Dict[str, Any] = {}

    def identity() -> None:
        arch = sess.archive
        if arch is None or len(arch.cells) <= 1:
            ident_out.update({"cells": 0, "ok": True, "note": "no cell beyond cell 0"})
            return
        samp = identity_sample(arch, cfg.identity_k)
        jobs = []
        for n, c in enumerate(samp["cells"]):
            jobs.append({"kind": "iterate", "arm": "ID", "iteration": IDENTITY_ITERATION_BASE + n, "cell": c.id,
                         "rep": (c.burst, c.offset), "words": arch.cell_words(c), "end": c.end, "end_digest": c.end_digest,
                         "chain": c.chain, "terminal": c.terminal, "pin": sess.pin, "archive_id": cfg.archive_id, "burst_words": 0, "allowance": c.L})
        try:
            results = sess.run_batch(jobs, "verify", "replays", cfg.replay_tick_cap)
        except CapStop as exc:
            cap_hit.append(f"identity replays: {exc}")
            return
        bad = [r for r in results if not r.get("ok")]
        okn = sum(1 for r in results if r.get("ok") and r["prefix"].get("end_equal") and r["prefix"].get("chain_equal", True))
        ident_out.update({"cells": len(jobs), "names": samp["names"], "verified": okn, "ok": not bad,
                          "cell_ids": [c.id for c in samp["cells"]], "failures": [
                              {k: r.get(k) for k in ("kind", "mismatch", "detail", "outcome", "message")} for r in bad]})
        for r in bad:
            if r.get("kind") == "mismatch":
                sess.stop_invalid(f"identity replay: {r.get('mismatch')} {json.dumps(r.get('detail'), default=str)[:300]}")
            else:
                sess.incomplete.append(f"identity replay: {r.get('kind')} {r.get('outcome') or r.get('error')}")

    errors: List[str] = []

    def guarded(fn) -> None:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{fn.__name__}: {type(exc).__name__}: {exc}\n{traceback.format_exc()[-1500:]}")

    t_claims = threading.Thread(target=guarded, args=(claims,), name="m8rd-claims")
    t_claims.start()
    try:
        guarded(identity)
    finally:
        t_claims.join()
    if errors:
        raise CapStop("verification error: " + errors[0][:600])
    rec["identity"] = ident_out
    if cap_hit:
        sess.log(f"verification stopped at a cap: {cap_hit}")
    # per-arm results
    verified: Dict[str, Dict[str, Any]] = {}
    t_unverified: List[str] = []
    for arm in ("T", "C"):
        led = sess.ledgers[arm]
        reps = list(done[arm].values())
        for r in reps:
            if not r["exact"]:
                if r.get("error"):
                    sess.incomplete.append(f"arm {arm}: {r['problems'][0][:200]}")
                else:
                    sess.stop_invalid(f"arm {arm} candidate {r['cid']} ({r['kind']}): inexact replay: {r['problems'][:2]}")
        t_claimed, t_cand, t_n = led.t_within(T)
        t_rep = next((r for r in reps if t_cand is not None and r["cid"] == t_cand["cid"]), None)
        if t_cand is not None and (t_rep is None or not t_rep["exact"]):
            t_verified = 0
            if t_rep is None:
                cap_hit.append(f"arm {arm}: the max-t candidate was not replayed")
                t_unverified.append(arm)
        else:
            t_verified = t_claimed if t_cand is not None else 0
        m = mclaims.milestone_level(reps)
        _todo, info = mclaims.plan_replays(led, T, done[arm], batch=99)
        remaining_levels = [mclaims.ladder_index(name) for name, n in info["remaining"].items() if n > 0
                            and not info["satisfied"][name]]
        verified[arm] = {"ticks": led.ticks, "t_claimed_online": t_claimed, "t": t_verified, "m": m,
                         "milestone": mclaims.LADDER[m], "replays": len(reps),
                         "remaining_unverified": info["remaining"], "max_m_unverified": max(remaining_levels, default=0),
                         "satisfied": info["satisfied"], "claims": {}}
        for name in ("t",) + MILESTONE_CLAIMS:
            first = None
            if name == "t":
                first = t_rep if (t_rep is not None and t_rep["exact"]) else None
            else:
                first = next((r for r in sorted(reps, key=lambda x: x["cid"]) if r["exact"] and mclaims.levels_of(r)[name]), None)
            if first is not None:
                verified[arm]["claims"][name] = {"cid": first["cid"], "kind": first["kind"], "counted": first["counted"],
                                                 "trace": first["trace"], "label": first["label"], "t": first["t"],
                                                 "clear_facts": first.get("clear_facts") if name == "clear" else None,
                                                 "first_qualified_entry": first.get("first_qualified_entry")
                                                 if name == "crossing" else None}
                save_route(sess, arm, name, led, first, vdir)
        rec["arms"][arm] = verified[arm]
    rec["cap_hit"] = cap_hit or None
    if t_unverified and not sess.invalid:
        sess.incomplete.append(f"the maximum-targets candidate of arm(s) {t_unverified} was left unverified at a cap")
    if cap_hit and not sess.invalid:
        unv = {a: verified[a]["max_m_unverified"] for a in ("T", "C")}
        changes = mrule.could_change(verified["T"]["m"], verified["C"]["m"], verified["T"]["t"], verified["C"]["t"],
                                     unv["T"], unv["C"])
        rec["could_change_outcome"] = changes
        if changes:
            sess.incomplete.append(f"candidates that could change the outcome were left unverified at a cap: {cap_hit}")
    rec["replay_ticks"] = sess.ticks["replays"]
    rec["finished_utc"] = utc()
    write_json(sess.dir / "verification.json", rec)
    sess.verification = rec
    sess.verified = verified
    sess.clock.end()
    return rec


def save_route(sess: Session, arm: str, claim: str, led: mclaims.ArmLedger, rep: Mapping[str, Any], vdir: Path) -> None:
    """routes/<arm>_<claim>/: actions.jsonl (M4 canonical form), metadata.json, trace.json.gz (every raw reply of the
    verification replay, all four diagnostics), both completion clocks for a clear."""
    cand = led.candidates[rep["cid"]]
    n = int(rep["counted"])
    words = bytes(cand["words"][:n])
    d = sess.cfg.root / "routes" / f"{arm}_{claim}"
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "actions.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for i, w in enumerate(words):
            b, x, y = mcell.TRIPLES[w]
            f.write(json.dumps({"sequence_index": i, "buttons": b, "stick_x": x, "stick_y": y, "consumed_tick": i},
                               separators=(",", ":")) + "\n")
    src = vdir / rep["trace"]
    if src.is_file():
        shutil.copy2(src, d / "trace.json.gz")
    meta = {"schema": "m8_rd_route_v1", "arm": arm, "claim": claim, "session": sess.cfg.session_id,
            "native_action_digest": mcell.words_digest(words), "words": n, "candidate": {k: v for k, v in cand.items()
                                                                                         if k not in ("words", "breaks")},
            "iteration": cand["iteration"], "replay": {k: v for k, v in rep.items() if k not in ("breaks",)},
            "track1_words_hex": words.hex(), "action_contract": "rlaction_native_v1"}
    if claim == "clear":
        meta["completion_clocks"] = {"completion_time_passed": rep["clear_facts"].get("completion_time_passed"),
                                     "completion_input_tick": rep["clear_facts"].get("completion_input_tick"),
                                     "note": "two distinct clocks; never collapsed, completion_input_tick never decremented"}
    write_json(d / "metadata.json", meta)


def decide(sess: Session) -> Dict[str, Any]:
    v = getattr(sess, "verified", None)
    if v is None:
        m_T = m_C = t_T = t_C = 0
        extra = {"verified": False}
        if not sess.invalid and not sess.incomplete:
            sess.incomplete.append("the session ended before the claims were verified")
    else:
        m_T, m_C, t_T, t_C = v["T"]["m"], v["C"]["m"], v["T"]["t"], v["C"]["t"]
        extra = {"verified": True}
    cp = mrule.comparison_point(sess.ledgers["T"].ticks, sess.ledgers["C"].ticks, sess.cfg.min_arm_ticks)
    extra.update({"comparison_point": cp["T"], "ticks": {"T": sess.ledgers["T"].ticks, "C": sess.ledgers["C"].ticks}})
    rec = mrule.apply(invalid=sess.invalid, incomplete=sorted(set(sess.incomplete)), m_T=m_T, m_C=m_C, t_T=t_T, t_C=t_C,
                      extra=extra)
    write_json(sess.dir / "rule.json", rec)
    sess.log(f"DECISION {rec['outcome']}: m(T) {rec['milestone_T']} m(C) {rec['milestone_C']} t(T) {t_T} t(C) {t_C} "
             f"invalid {rec['invalid'][:2]} incomplete {rec['incomplete'][:2]}")
    return rec


def close_session(sess: Session, rule_record: Mapping[str, Any]) -> Dict[str, Any]:
    """S2 (zero native ticks): final atomic save, offline audit, the close record."""
    cfg = sess.cfg
    close: Dict[str, Any] = {"started_utc": utc(), "outcome": rule_record["outcome"]}
    if sess.archive is not None:
        sess.checkpoint("final")
        loaded, _meta = march.Archive.read_files(cfg.archive_dir)
        aud = march.audit(loaded)
        close["audit"] = aud
        close["archive"] = {"stats": loaded.stats(), "manifest": {n: march.sha256_file(cfg.archive_dir / n) for n in march.DATA_FILES},
                            "checkpoint_seq": sess.ckpt_seq}
        close["velocity_reversals"] = dict(sess.vel_reversals)
        sess.log(f"close audit: ok {aud['ok']} cells {aud['cells']} bursts {aud['bursts']} problems {aud['problems'][:2]}")
    close["coverage_C"] = sess.coverage.stats()
    close["ledgers"] = {a: {"ticks": l.ticks, "jobs": l.jobs, "candidates": len(l.candidates)} for a, l in sess.ledgers.items()}
    close["finished_utc"] = utc()
    write_json(sess.dir / "close.json", close)
    return close


def run_all(sess: Session) -> Dict[str, Any]:
    """The whole session after S0: P1, arm T, arm C, verification, the decision, the close. Every stop is a recorded outcome."""
    cfg = sess.cfg
    sess.save_state(phase="start")
    try:
        sess.clock.begin("p1")
        sess.pool.start(cfg.n_workers)
        sess.p1()
        sess.init_archive()
        sess.run_arm("T")
        if not sess.invalid and not sess.incomplete:
            sess.run_arm("C")
        if not sess.invalid and not sess.incomplete and sess.arm_records.get("T") and sess.arm_records.get("C"):
            verify_phase(sess)
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
    rule_record = decide(sess)
    try:
        close = close_session(sess, rule_record)
    except Exception as exc:  # noqa: BLE001
        close = {"error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-2000:]}
        write_json(sess.dir / "close.json", close)
    sess.save_state(phase="done", decision=rule_record["outcome"])
    return {"rule": rule_record, "close": close}
