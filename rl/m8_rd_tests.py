#!/usr/bin/env python3
"""M8-rd offline tests: zero native ticks. No BattleShip launch, no replay on a real process, no training.

    python rl/m8_rd_tests.py unit [--out DIR] [--only NAME[,NAME]]
    python rl/m8_rd_tests.py e2e  [--out DIR] [--small]      # the production-count synthetic end-to-end run
    python rl/m8_rd_tests.py list

The synthetic native stand-in is rl/m8_rd_stub.py (a deterministic platformer that speaks the SSB64_RL_SPATIAL=1 reply format);
it is driven through the REAL worker jobs, archive, claims, engine, rule and report code. Real recorded replies (the 400
random-play episodes of the action-hold probe and a recorded qualified-crossing replay) are read, never written. Approval is
tested against isolated temporary records, so the suite stays valid after a real approval record exists.

Light top-level imports only (spawned workers re-import this script when the e2e runs from it).
"""
from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import io
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m8_rd_archive as march  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_claims as mclaims  # noqa: E402
import m8_rd_explore as mx  # noqa: E402
import m8_rd_rule as mrule  # noqa: E402
import m8_rd_stub as stub  # noqa: E402
import m8_rd_worker as mw  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
RL_DIR = Path(__file__).resolve().parent
PROBE_DIR = REPO_ROOT / "runs" / "probes" / "action_hold" / "episodes"
M7P_CROSSING_TRACE = REPO_ROOT / "runs" / "m7p" / "addendum" / "crossings" / "replays" / "00_44619208" / "trace.json.gz"
M7P_CROSSING_ARTIFACT = (REPO_ROOT / "runs" / "m7p" / "campaign" / "_eval" / "m7p_geo4_s1" / "final" / "stochastic" / "workers" /
                         "w04" / "artifacts" / "episode_20260928T072129Z_44619208")
NEW_MODULES = ("m8_rd_cells", "m8_rd_explore", "m8_rd_archive", "m8_rd_claims", "m8_rd_rule", "m8_rd_worker", "m8_rd_run",
               "m8_rd_finish", "m8_rd_session", "m8_rd_report", "m8_rd_snapshot", "m8_rd_stub", "m8_rd_fakegame")


class Failure(AssertionError):
    pass


def check(cond: Any, msg: str) -> None:
    if not cond:
        raise Failure(msg)


def raises(exc: type, fn: Callable[[], Any], msg: str) -> Any:
    try:
        fn()
    except exc as e:
        return e
    raise Failure(msg)


def tmpdir(prefix: str = "m8t_") -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


# -- synthetic builders ----------------------------------------------------------------------------------------------------------


def mk_end(x: float = 0.0, y: float = 0.0, vx: float = 0.0, t: int = 0, status: int = 10, ga: int = 0, jumps: int = 0,
           targets: int = 10, host: int = 100) -> Tuple[Any, ...]:
    return (1, host, t, t, 1, 1, targets, 1, float(x), float(y), float(vx), 0.0, 0.0, 1, ga, status, jumps)


def key(bx: int, by: int, res: str = "G", mask: int = 1023, floor: int = 4) -> Tuple[int, int, str, int, int]:
    return (bx, by, res, mask, floor if res == "G" else -1)


def reach(j: int, k: Tuple[Any, ...], end: Optional[Tuple[Any, ...]] = None, terminal: bool = False
          ) -> Tuple[int, Tuple[Any, ...], Tuple[Any, ...], bytes, bytes, bool]:
    return (j, k, end or mk_end(t=j), bytes([j % 251]) * 32, bytes([(j * 7) % 251]) * 32, terminal)


def result(it: int, cell: march.Cell, words: bytes, reaches: Sequence[Any], end_reason: str = "length", cum: int = 0,
           worker: int = 0) -> Dict[str, Any]:
    return {"iteration": it, "cell": cell.id, "rep": (cell.burst, cell.offset), "L": cell.L, "words": bytes(words),
            "end_reason": end_reason, "ticks": cell.L + len(words), "reaches": list(reaches), "worker": worker,
            "session": "t", "cum_before": cum}


def fresh_archive(aid: str = "t") -> march.Archive:
    a = march.Archive(aid)
    a.init_cell0(key(0, 0), mk_end(), bytes(32), bytes([1]) * 32)
    return a


def add_cell(a: march.Archive, k: Tuple[Any, ...], L: int, *, doomed: bool = False, terminal: bool = False, chosen: int = 0,
             seen: int = 0) -> march.Cell:
    c = march.Cell(id=len(a.cells), key=k, level=mcell.level_of_mask(k[3]), L=L, burst=-1, offset=0, parent=0, end=mk_end(t=L),
                   end_digest=bytes(32), chain=bytes(32), doomed=doomed, terminal=terminal, chosen=chosen, seen=seen)
    a._add(c)
    return c


_CLF: Dict[str, Any] = {}


def classifier() -> mcell.Classifier:
    if "c" not in _CLF:
        _CLF["c"] = mcell.Classifier()
    return _CLF["c"]


def job_ctx(world: str = "easy", inject: Optional[Mapping[str, Any]] = None, abort: Any = None, failure_dir: Optional[Path] = None
            ) -> mw.JobContext:
    backend = stub.StubBackend({"rank": 0, "world": world, "inject": dict(inject or {})})
    return mw.JobContext(backend, abort, classifier(), 0, failure_dir)


def pin_from(ctx: mw.JobContext) -> Dict[str, Any]:
    r = mw.run_tick0(ctx, {"kind": "tick0", "pin": None})
    check(r["ok"], f"tick0 job failed: {r}")
    return {"obs": list(r["obs"]), "digest": r["digest"], "chain": r["chain"], "lines": r["lines"], "key": r["key"], "mask": r["mask"]}


def iterate_job(a: march.Archive, cell: march.Cell, pin: Mapping[str, Any], *, it: int, burst_words: int = 120,
                allowance: Optional[int] = None) -> Dict[str, Any]:
    want = cell.L + min(burst_words, mcell.HORIZON - cell.L)
    return {"kind": "iterate", "arm": "T", "iteration": it, "cell": cell.id, "rep": (cell.burst, cell.offset),
            "words": a.cell_words(cell), "end": cell.end, "end_digest": cell.end_digest, "chain": cell.chain, "pin": dict(pin),
            "archive_id": a.archive_id, "burst_words": burst_words, "allowance": want if allowance is None else allowance}


def drive_archive(world: str = "easy", n_iter: int = 40, aid: str = "tdrive", inject: Optional[Mapping[str, Any]] = None
                  ) -> Tuple[march.Archive, Dict[str, Any], mw.JobContext, int]:
    """The session's T-arm loop without processes: dispatch, a real worker iterate job on the stub, ingest."""
    ctx = job_ctx(world, inject)
    pin = pin_from(ctx)
    a = march.Archive(aid)
    a.init_cell0(tuple(pin["key"]), pin["obs"], bytes.fromhex(pin["digest"]), bytes.fromhex(pin["chain"]))
    cum = 0
    for it in range(n_iter):
        cell = a.dispatch(it, 0)
        res = mw.run_iterate(ctx, iterate_job(a, cell, pin, it=it))
        check(res["ok"], f"iteration {it} failed: {res}")
        a.ingest(dict(res, cum_before=cum, session="t"))
        cum += res["ticks"]
    return a, pin, ctx, cum


def recorded_episode(k: str = "k01", i: int = 0) -> Optional[Dict[str, Any]]:
    p = PROBE_DIR / k / f"ep{i:03d}.json.gz"
    if not p.is_file():
        return None
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return json.load(f)


# -- cells, record, chain, scanner -------------------------------------------------------------------------------------------------


def unit_cells_contract() -> Dict[str, Any]:
    import m7h_curriculum as mc
    import btt_learning as bl

    check(mcell.OBS_FIELDS == mc.OBSERVATION_FIELDS, "observation field order differs from m7h_curriculum")
    check(tuple(map(tuple, bl.TRACK1_STICK_TABLE)) == mcell.STICK_TABLE, "Track 1 stick table differs from btt_learning")
    check(tuple(int(b) for b in bl.TRACK1_BUTTON_TABLE) == mcell.BUTTON_TABLE, "Track 1 button table differs from btt_learning")
    check(mcell.TRIPLES == tuple(mc.track1_triple(i) for i in range(72)), "Track 1 triples differ from m7h_curriculum")
    check(mcell.TRACK1_WORDS == 72 and len(set(mcell.TRIPLES)) == 72, "72 distinct words")
    check(mcell.native_digest([(*mcell.TRIPLES[3], 0), (*mcell.TRIPLES[9], 1)]) == mc.native_digest(
        [(*mc.track1_triple(3), 0), (*mc.track1_triple(9), 1)]), "native digest")
    check(mcell.words_digest(bytes([3, 9])) == mc.prefix_digest(bytes([3, 9])), "words digest equals the M7h prefix digest")
    clf = classifier()
    by = {}
    for sid, cls in clf._by_id.items():
        by.setdefault(cls, sid)
    # resource class table (section 4.1)
    def rc(status: str, ga: int, jumps: int) -> str:
        return mcell.resource_class({"ground_air_state": ga, "jumps_used": jumps}, status)
    cases = [("idle_ground", 0, 0, "G"), ("dash_run", 0, 1, "G"), ("jump_squat", 0, 0, "G"), ("landing_lag", 0, 0, "G"),
             ("airborne", 1, 0, "A2"), ("airborne", 1, 1, "A2"), ("airborne", 1, 2, "A1"), ("attack_air", 1, 1, "A2"),
             ("attack_air", 1, 2, "A1"), ("special_n", 1, 1, "A2"), ("special_lw", 1, 2, "A1"), ("air_lock", 1, 2, "A1"),
             ("special_hi", 1, 2, "A0"), ("special_hi", 1, 1, "A0"), ("helpless", 1, 2, "A0"), ("helpless", 1, 0, "A0"),
             ("damage", 1, 0, "X"), ("damage", 0, 0, "X"), ("dead", 1, 2, "X"), ("appear_entry", 0, 0, "X"), ("other", 1, 0, "X"),
             ("unmapped", 0, 0, "X")]
    for status, ga, jumps, want in cases:
        check(rc(status, ga, jumps) == want, f"resource class of ({status}, ga {ga}, jumps {jumps}) is not {want}")
    # the key
    o = {"btt_active": 1, "fighter_valid": 1, "position_x": -300.0, "position_y": 599.9, "ground_air_state": 0, "jumps_used": 0,
         "fighter_status_id": by["idle_ground"], "targets_remaining": 9}
    sp = {"target_live_mask": 0b1111111110, "fighter": {"floor_line_id": 1}}
    check(mcell.cell_key(o, sp, clf) == (-1, 1, "G", 1022, 1), "key of a grounded step (floor of the native floor line)")
    o2 = dict(o, ground_air_state=1, jumps_used=2)
    check(mcell.cell_key(o2, sp, clf) == (-1, 1, "A1", 1022, -1), "floor is -1 when airborne")
    check(mcell.cell_key(dict(o, position_x=0.0, position_y=-0.1), sp, clf)[:2] == (0, -1), "floor division, no clipping")
    check(mcell.cell_key(dict(o, position_x=-300.0), sp, clf)[0] == -1 and mcell.cell_key(dict(o, position_x=-300.1), sp, clf)[0] == -2,
          "300-unit bins from the world origin")
    check(mcell.cell_key(dict(o, btt_active=0), sp, clf) is None and mcell.cell_key(dict(o, fighter_valid=0), sp, clf) is None,
          "no key on a non-live step")
    raises(mcell.CellError, lambda: mcell.cell_key(dict(o, targets_remaining=8), sp, clf), "mask / count disagreement accepted")
    check(clf.unmapped_seen == {} or all(isinstance(v, int) for v in clf.unmapped_seen.values()), "unmapped counter")
    check(clf.name(99999) == "unmapped" and clf.unmapped_seen.get(99999) == 1, "an id outside the table is the explicit class")
    # native failure rule and diffs
    nf = {"btt_active": 1, "game_status": 5, "targets_remaining": 3}
    check(mcell.is_native_failure(nf, 2) and not mcell.is_native_failure(nf, 6) and not mcell.is_native_failure(
        dict(nf, targets_remaining=0), 2), "btt_native_failure_v1")
    a, b = list(mcell.obs_tuple(dict.fromkeys(mcell.OBS_FIELDS, 0))), list(mcell.obs_tuple(dict.fromkeys(mcell.OBS_FIELDS, 0)))
    b[mcell.HOST_FRAME] = 5
    check(mcell.obs_diffs(a, b) == {}, "host_frame is ignored by the diff")
    b[mcell.I_X] = 0.0
    check("position_x" in mcell.obs_diffs(a, b), "1 != 1.0 is a type difference")
    d1, d2 = mcell.contract_digest(), mcell.contract_digest()
    check(d1 == d2 and len(d1) == 64 and len(mcell.track1_digest()) == 64, "digests")
    return {"track1_digest": mcell.track1_digest()[:12], "cell_contract": d1[:12]}


def unit_cells_on_recorded_replies() -> Dict[str, Any]:
    """Real replies of the 400-episode random-play probe: the key's cell count, the break table from the mask, the chain."""
    ep = recorded_episode("k01", 0)
    check(ep is not None, f"preserved probe data missing under {PROBE_DIR}")
    clf = classifier()
    steps, initial = ep["steps"], ep["initial"]
    rec0 = mcell.tick0_record(initial)
    check(len(rec0["l"]) == 64 and rec0["s"] == 2 and rec0["n"] == 0, "tick-0 record")
    h = mcell.chain_start(rec0)
    h2 = mcell.chain_start(mcell.tick0_record(initial))
    check(h == h2, "the chain start is deterministic")
    sc = mcell.BurstScanner(initial["spatial"]["target_live_mask"])
    keys = set()
    digests = []
    for s in steps:
        o, sp = s["observation"], s["spatial"]
        rd = mcell.record_digest(mcell.record_of(s))
        digests.append(rd)
        h = mcell.chain_next(h, rd)
        k = mcell.cell_key(o, sp, clf)
        if k is not None:
            keys.add(k)
        sc.feed(int(o["input_tick"]), o, sp, s["state"])
    # the break table from the mask equals the native target-identity table (consumed ticks)
    native = sorted((int(i), int(t)) for i, t in ep["record"]["stage"]["breaks"])
    online = sorted((i, j - 1) for j, i in sc.breaks)
    check(online == native, f"mask-derived breaks {online} differ from the native break table {native}")
    check(sc.t == len(native) and [t for _j, t in sc.t_events] == list(range(1, len(native) + 1)), "t events")
    check(mcell.words_digest(bytes(0)) == mcell.native_digest([]), "empty words digest")
    # words digest equals the probe's recorded native action digest (rows -> track1 words)
    idx = {t: i for i, t in enumerate(mcell.TRIPLES)}
    words = bytes(idx[(r[0], r[1], r[2])] for r in ep["rows"])
    check(mcell.words_digest(words) == ep["record"]["native_action_digest"], "words digest equals the recorded native digest")
    # tampering one reply changes the chain, host_frame does not
    s0 = dict(steps[10], observation=dict(steps[10]["observation"], host_frame=1))
    check(mcell.record_digest(mcell.record_of(s0)) == digests[10], "host_frame is not part of the record")
    s1 = dict(steps[10], observation=dict(steps[10]["observation"], position_x=steps[10]["observation"]["position_x"] + 0.5))
    check(mcell.record_digest(mcell.record_of(s1)) != digests[10], "a position change changes the record digest")
    return {"cells_in_ep000": len(keys), "ticks": len(steps), "breaks": native}


def unit_record_digests_across_flag_sets() -> Dict[str, Any]:
    """The per-tick record digests (observation without host_frame, spatial fighter / groups / mask / positions, state, step
    count) of two separate processes started with DIFFERENT diagnostic flag sets (entity + spatial + target; and those plus the
    input diagnostic, twice) are identical tick for tick: the exploration flags (spatial only) therefore reproduce the pinned
    traces' records. Preserved M7q equivalence traces, read only."""
    base = REPO_ROOT / "runs" / "m7q" / "_equiv"
    n_ticks = 0
    for name in ("fx_m7d_s0v1_fall6_double", "fx_m7e_s0_best6"):
        digs = []
        for d, suffix in (("entity_all", ""), ("input_all", ""), ("input_all_r2", "_r2")):
            p = base / d / f"{name}{suffix}.json.gz"
            check(p.is_file(), f"preserved trace missing: {p}")
            with gzip.open(p, "rt", encoding="utf-8") as f:
                tr = json.load(f)
            digs.append((mcell.record_digest(mcell.tick0_record(tr["initial"])), [mcell.record_digest(mcell.record_of(s)) for s in tr["steps"]]))
            n_ticks += len(tr["steps"])
        check(digs[0] == digs[1] == digs[2], f"{name}: record digests differ between flag sets or processes")
    return {"ticks_compared": n_ticks}


def unit_cell_count_on_probe_prefix() -> Dict[str, Any]:
    """The proposal's section 4.2 figure reproduced on the first five episodes of the hold-1 condition: 1,003 cells (the same
    code path measured 14,360 cells and 39 masks on all 400 episodes in preparation)."""
    clf = classifier()
    keys = set()
    for i in range(5):
        ep = recorded_episode("k01", i)
        check(ep is not None, "preserved probe data missing")
        for s in ep["steps"]:
            k = mcell.cell_key(s["observation"], s["spatial"], clf)
            if k is not None:
                keys.add(k)
    check(len(keys) == 1003, f"{len(keys)} cells on k01 ep000..004, expected 1,003")
    return {"cells": len(keys)}


# -- explore -----------------------------------------------------------------------------------------------------------------------


def unit_explore() -> Dict[str, Any]:
    check(mx.decision("k") == mx.decision("k"), "decisions are deterministic")
    seen_words, seen_holds = set(), {}
    N = 20000
    for i in range(N):
        w, k = mx.decision(f"u|{i}")
        check(0 <= w < 72 and k in mx.HOLD_CHOICES, "word / hold range")
        seen_words.add(w)
        seen_holds[k] = seen_holds.get(k, 0) + 1
    check(len(seen_words) == 72, "every one of the 72 words is drawn")
    for k, n in seen_holds.items():
        check(abs(n / N - 0.2) < 0.015, f"hold {k} drawn with frequency {n / N:.3f}, expected 0.2")
    us = [mx.uniforms(f"v|{i}") for i in range(20000)]
    for j in (0, 1):
        m = sum(u[j] for u in us) / len(us)
        check(abs(m - 0.5) < 0.01 and all(0.0 <= u[j] < 1.0 for u in us), f"uniform {j} mean {m:.4f}")
    check(mx.uniforms("a") != mx.uniforms("b"), "different keys give different draws")
    # the stream: exactly max_words words, holds clipped, holds are runs of one word
    for mw_ in (1, 2, 7, 120, 3600):
        ws = list(mx.words(lambda i: mx.explore_key("A", 5, i), mw_))
        check(len(ws) == mw_, f"stream length {len(ws)} != {mw_}")
    ws = list(mx.words(lambda i: mx.explore_key("A", 5, i), 120))
    runs = []
    for w in ws:
        if runs and runs[-1][0] == w:
            runs[-1][1] += 1
        else:
            runs.append([w, 1])
    expect = []
    t, idx = 0, 0
    while t < 120:
        w, k = mx.decision(mx.explore_key("A", 5, idx))
        k = min(k, 120 - t)
        expect.append((w, k))
        t += k
        idx += 1
    flat = []
    for w, k in expect:
        flat += [w] * k
    check(flat == ws, "the stream is the keyed decisions, each hold clipped at the end")
    check(list(mx.words(lambda i: mx.explore_key("A", 5, i), 50)) == ws[:50], "a shorter stream is a prefix")
    check(list(mx.words(lambda i: mx.explore_key("A", 6, i), 120)) != ws, "another iteration draws differently")
    check(list(mx.words(lambda i: mx.control_key(5, i), 120)) != ws, "control keys differ from explore keys")
    check(mx.select_key("a", 3) == "m8_rd|a|select|3" and mx.explore_key("a", 3, 4) == "m8_rd|a|explore|3|4"
          and mx.control_key(2, 9) == "m8_rd1|control|2|9", "key strings")
    mean_hold = sum(mx.HOLD_CHOICES) / 5
    check(abs(mean_hold - 6.2) < 1e-9, "mean hold length 6.2")
    return {"mean_hold": mean_hold, "contract": mx.contract_digest()[:12]}


# -- archive -------------------------------------------------------------------------------------------------------------------------


def unit_archive_ingest_rules() -> Dict[str, Any]:
    a = fresh_archive()
    c0 = a.cells[0]
    A, B, C, D = key(1, 0), key(2, 0), key(3, 0), key(4, 0)
    w0 = bytes([1] * 10)
    info = a.ingest(result(0, c0, w0, [reach(3, A), reach(5, B), reach(8, C)]))
    check(info["new"] == 3 and info["replaced"] == 0 and info["kept"] == 0, f"first burst {info}")
    cA, cB, cC = (a.cells[a.by_key[k]] for k in (A, B, C))
    check((cA.L, cB.L, cC.L) == (3, 5, 8) and cA.burst == cB.burst == cC.burst == 0, "representatives")
    check((cA.offset, cB.offset, cC.offset) == (3, 5, 8), "offsets within the burst")
    check(a.cell_words(cB) == w0[:5] and a.cell_words(cC) == w0[:8], "lineage words")
    check(c0.produced == 3 and all(c.seen == 1 for c in (cA, cB, cC)), "produced and seen")
    # burst 1 starts from A: B at 7 (longer: kept), D at 9 (new)
    w1 = bytes([2] * 10)
    info = a.ingest(result(1, cA, w1, [reach(7, B), reach(9, D)], cum=18))
    check(info == {"burst": 1, "new": 1, "replaced": 0, "kept": 1, "visited": 2, "new_ids": [4]}, f"second burst {info}")
    cD = a.cells[a.by_key[D]]
    check(cD.L == 9 and cD.parent == cA.id and cD.first_cum == 18 + 9, "D from A")
    expectD = w0[:3] + w1[:6]
    check(a.cell_words(cD) == expectD, "D's words are A's prefix plus the burst's first 6 words")
    check(cB.L == 5 and cB.burst == 0 and cB.seen == 2, "ties and longer reaches keep the incumbent; seen counts the visit")
    # burst 2 from cell 0 reaches B at 2 (strictly shorter): replace; the pinned start representative keeps D's lineage exact
    w2 = bytes([3] * 4)
    info = a.ingest(result(2, c0, w2, [reach(2, B)], cum=100))
    check(info["replaced"] == 1 and info["new"] == 0, "a strictly shorter reach replaces")
    check(cB.L == 2 and cB.burst == 2 and cB.replacements == 1 and a.cell_words(cB) == w2[:2], "B's new representative")
    check(a.cell_words(cD) == expectD, "an earlier lineage is untouched by a later replacement")
    # a burst started from B BEFORE and AFTER the replacement pins different start representatives
    info = a.ingest(result(3, cB, bytes([4] * 3), [reach(cB.L + 2, key(9, 9))], cum=200))
    check(a.bursts[-1].start_rep == (2, 2) and a.cell_words(a.cells[a.by_key[key(9, 9)]]) == w2[:2] + bytes([4] * 2), "pinned start")
    # tie: equal L, same doom status keeps the incumbent
    n_before = cB.replacements
    a.ingest(result(4, c0, bytes([5] * 4), [reach(2, B)], cum=300))
    check(cB.replacements == n_before and cB.burst == 2, "a tie keeps the incumbent")
    # doomed: a fall at tick 100, 60-tick window
    w3 = bytes([6] * 100)
    E, F, G = key(5, 1), key(6, 1), key(7, 1)
    a.ingest(result(5, c0, w3, [reach(39, F), reach(40, E), reach(100, G, terminal=True)], end_reason="fall", cum=400))
    cE, cF, cG = (a.cells[a.by_key[k]] for k in (E, F, G))
    check(not cF.doomed and cE.doomed and cG.doomed and cG.terminal, "doom: 100 - 40 = 60 is inside the window, 61 is not")
    check(not a.eligible(cE) and not a.eligible(cG) and a.eligible(cF), "doomed and terminal cells are not eligible")
    # a non-doomed (longer) reach beats a doomed one; a doomed reach never beats a non-doomed one
    a.ingest(result(6, c0, bytes([7] * 60), [reach(55, E)], end_reason="length", cum=500))
    check(not cE.doomed and cE.L == 55 and cE.replacements == 1, "a non-doomed reach beats a doomed one even if longer")
    a.ingest(result(7, c0, bytes([8] * 100), [reach(45, E)], end_reason="fall", cum=600))
    check(not cE.doomed and cE.L == 55, "a doomed reach never beats a non-doomed incumbent")
    # eligibility: X, L bound, terminal
    X = key(8, 1, "X")
    a.ingest(result(8, c0, bytes([9] * 5), [reach(4, X)], cum=700))
    check(not a.eligible(a.cells[a.by_key[X]]), "class X is not eligible")
    cl = add_cell(a, key(20, 20), march.MAX_ELIGIBLE_L)
    cl2 = add_cell(a, key(21, 20), march.MAX_ELIGIBLE_L + 1)
    check(a.eligible(cl) and not a.eligible(cl2), "L <= 3,600 - 120 is eligible, one more is not")
    check(a.eligible(a.cells[0]), "cell 0 is always eligible")
    # a job with no burst (cut inside the prefix) records an ingest event only
    n_b = len(a.bursts)
    a.ingest(result(9, cA, b"", [], end_reason="cut", cum=800))
    check(len(a.bursts) == n_b and a.events[-1]["burst"] == -1, "a cut prefix creates no burst")
    # contract violations
    bad = result(10, cA, bytes([1] * 5), [reach(cA.L + 9, key(30, 30))], cum=0)
    raises(march.ArchiveError, lambda: a.ingest(bad), "a reach outside the burst accepted")
    bad = result(11, cA, bytes([1] * 5), [reach(cA.L + 3, key(31, 31)), reach(cA.L + 2, key(32, 31))], cum=0)
    raises(march.ArchiveError, lambda: a.ingest(bad), "out-of-order reaches accepted")
    bad = dict(result(12, cA, bytes([1] * 5), [], cum=0), rep=(7, 7))
    raises(march.ArchiveError, lambda: a.ingest(bad), "a job that replayed another representative accepted")
    return {"cells": len(a.cells), "bursts": len(a.bursts)}


def dispatch_cell(a: march.Archive, cell: march.Cell, worker: int, start: int = 100) -> int:
    """Dispatch exactly `cell` through the real keyed selection: the first iteration number whose selection is that cell."""
    for it in range(start, start + 20000):
        if it not in a._pending and a.select(it).id == cell.id:
            a.dispatch(it, worker)
            return it
    raise Failure(f"no iteration selects cell {cell.id}")


def unit_archive_async_ingestion() -> Dict[str, Any]:
    """Ingestion is asynchronous: a cell may be replaced while a job that started from its OLDER representative is still
    running. The late result must be accepted against what was dispatched, pin that start representative, and stay exact."""
    a = fresh_archive("async")
    c0 = a.cells[0]
    A, B = key(1, 0), key(2, 0)
    it0 = dispatch_cell(a, c0, 0, 0)
    a.ingest(result(it0, c0, bytes([1] * 10), [reach(6, A), reach(9, B)]))
    cA = a.cells[a.by_key[A]]
    old_rep = (cA.burst, cA.offset)
    itA = dispatch_cell(a, cA, 1, 200)                              # a job starts from A's representative (burst 0, offset 6)
    check(a._pending[itA] == (cA.id, old_rep, 6), "the dispatch pins the representative")
    it2 = dispatch_cell(a, c0, 2, 400)                              # meanwhile another job from cell 0 finishes first
    a.ingest(result(it2, c0, bytes([2] * 5), [reach(3, A)], cum=50))
    check((cA.burst, cA.offset) == (1, 3) and cA.L == 3, "A's representative was replaced while the first job was in flight")
    late = dict(result(itA, cA, bytes([3] * 8), [reach(9, key(5, 5))], cum=80), rep=old_rep, L=6)
    a.ingest(late)
    nb = a.bursts[-1]
    check(nb.start_rep == old_rep and nb.start_L == 6 and a.cell_words(a.cells[a.by_key[key(5, 5)]]) == bytes([1] * 6) + bytes([3] * 3),
          "the late burst keeps the representative it actually replayed")
    itB = dispatch_cell(a, cA, 0, 600)
    raises(march.ArchiveError, lambda: a.ingest(dict(result(itB, cA, bytes([3] * 8), [], cum=90), rep=old_rep, L=6)),
           "a result for another representative than the dispatched one must be refused")
    itC = dispatch_cell(a, cA, 0, 800)
    raises(march.ArchiveError, lambda: a.ingest(dict(result(itC, c0, bytes([3] * 8), [], cum=90))), "a result for another cell must be refused")
    itD = dispatch_cell(a, cA, 0, 1000)
    a.note_failure(itD, "lifecycle")
    check(itD not in a._pending, "a failed iteration is no longer pending")
    aud = march.audit(a)
    check(aud["ok"], f"audit of an archive with a late ingestion: {aud['problems']}")
    return {"cells": len(a.cells)}


def unit_velocity_reversal_reading() -> Dict[str, Any]:
    a = fresh_archive()
    c0 = a.cells[0]
    K = key(3, 3, "A2")
    a.ingest(result(0, c0, bytes(20), [reach(10, K, mk_end(vx=20.0, ga=1, t=10))]))
    a.ingest(result(1, c0, bytes(20), [reach(8, K, mk_end(vx=-20.0, ga=1, t=8))], cum=20))      # shorter, opposite sign
    check(a.diag["velocity_reversals"] == 1, "an airborne replacement with opposite signs is counted")
    a.ingest(result(2, c0, bytes(20), [reach(6, K, mk_end(vx=-3.0, ga=1, t=6))], cum=40))       # |vx| < 6
    check(a.diag["velocity_reversals"] == 1, "|vx| < 6 is not counted")
    G = key(4, 3, "G")
    a.ingest(result(3, c0, bytes(20), [reach(10, G, mk_end(vx=20.0, t=10))], cum=60))
    a.ingest(result(4, c0, bytes(20), [reach(8, G, mk_end(vx=-20.0, t=8))], cum=80))
    check(a.diag["velocity_reversals"] == 1, "a grounded replacement is not counted")
    check(a.diag["velocity_reversal_examples"][0]["old_vx"] == 20.0, "the example is recorded")
    return {"reversals": a.diag["velocity_reversals"]}


def unit_selection() -> Dict[str, Any]:
    a = fresh_archive("sel")
    m = {0: 1023, 1: 1022, 2: 1020, 3: 1016}
    c1 = add_cell(a, key(1, 0, "G", m[0]), 100, chosen=3, seen=8)           # level 0
    c2 = add_cell(a, key(2, 0, "G", m[0]), 1000, chosen=0, seen=0)          # level 0
    c3 = add_cell(a, key(3, 0, "G", m[1]), 200, chosen=1, seen=1)           # level 1
    c4 = add_cell(a, key(4, 0, "G", m[1]), 1100, chosen=0, seen=2)          # level 1
    c5 = add_cell(a, key(5, 0, "A2", m[1]), 3300, chosen=0, seen=0)         # level 1
    c6 = add_cell(a, key(6, 0, "G", m[2]), 500, chosen=2, seen=3)           # level 2 (the only eligible one at the top)
    c7 = add_cell(a, key(7, 0, "G", m[2]), 600, doomed=True)                # ineligible
    c8 = add_cell(a, key(8, 0, "X", m[3]), 700)                             # level 3, class X: ineligible -> level 3 absent
    c9 = add_cell(a, key(9, 0, "G", m[3]), 800, terminal=True)              # ineligible
    top = 2
    elig = {0: [a.cells[0], c1, c2], 1: [c3, c4, c5], 2: [c6]}
    lw = {lv: 2.0 ** -(top - lv) for lv in elig}
    p: Dict[int, float] = {}
    for lv, cs in elig.items():
        lmin = min(c.L for c in cs)
        w = [(1 / math.sqrt(1 + c.chosen) + 1 / math.sqrt(1 + c.seen)) * 900 / (900 + c.L - lmin) for c in cs]
        for c, wi in zip(cs, w):
            p[c.id] = lw[lv] / sum(lw.values()) * wi / sum(w)
    check(abs(sum(p.values()) - 1.0) < 1e-12, "analytic probabilities sum to 1")
    N = 40000
    counts: Dict[int, int] = {}
    for i in range(N):
        cid = a.select(i).id
        counts[cid] = counts.get(cid, 0) + 1
    check(set(counts) <= set(p), f"an ineligible cell was selected: {set(counts) - set(p)}")
    for cid, pr in p.items():
        f = counts.get(cid, 0) / N
        check(abs(f - pr) <= 4.5 * math.sqrt(pr * (1 - pr) / N) + 1e-3, f"cell {cid}: frequency {f:.4f}, analytic {pr:.4f}")
    check(all(a.select(i).id == a.select(i).id for i in range(50)), "selection is a pure function of the state and the iteration")
    # the top level gets about half of the probability when every level below is present; a single level gets all of it
    b = fresh_archive("one")
    check(all(b.select(i).id == 0 for i in range(20)), "only cell 0: always cell 0")
    # novelty falls with chosen / seen; the length factor halves at +900
    wa = 1 / math.sqrt(1) + 1 / math.sqrt(1)
    wb = 1 / math.sqrt(1 + 3) + 1 / math.sqrt(1 + 8)
    check(wb < wa, "novelty weight decreases with counts")
    check(abs(900 / (900 + 900) - 0.5) < 1e-12, "length factor halves at +900")
    # dispatch increments chosen and logs; selection is keyed by the iteration only
    c = a.dispatch(5, 2)
    check(a.events[-1] == {"ev": "dispatch", "it": 5, "cell": c.id, "worker": 2, "L": c.L, "rep": [c.burst, c.offset]},
          "the dispatch is logged with the representative that was dispatched")
    return {"cells": len(a.cells), "levels_eligible": sorted(elig)}


def unit_ledger_rebuild_and_audit() -> Dict[str, Any]:
    a, pin, ctx, cum = drive_archive("easy", 60, "taud")
    check(len(a.cells) > 100 and len(a.bursts) == 60, f"the driven archive is too small: {len(a.cells)} cells")
    aud = march.audit(a)
    check(aud["ok"], f"audit of a driven archive: {aud['problems']}")
    check(aud["prefixes_reconstructed"] == len(a.cells), "every prefix reconstructs")
    rb = march.rebuild(a)
    check([c.to_json() for c in rb.cells] == [c.to_json() for c in a.cells], "the rebuild equals the archive exactly")
    check(rb.events == a.events and rb.diag == a.diag, "the rebuilt ledger and diagnostics are equal")
    st = a.stats()
    check(st["cells"] == len(a.cells) and st["bursts"] == 60 and st["masks"] >= 1, "stats")
    # tamper 1: a stored win record
    t = tmpdir()
    meta = {"checkpoint_seq": 1}
    a.write_files(t / "a", meta)
    b, _m = march.Archive.read_files(t / "a")
    cell_tamper = b.cells[len(b.cells) // 2]
    cell_tamper.chosen += 1
    check(not march.audit(b)["ok"], "a tampered chosen counter is detected by the rebuild")
    b, _m = march.Archive.read_files(t / "a")
    ev = next(e for e in b.events if e["ev"] == "dispatch" and e["cell"] != 0 and e["it"] > 5)
    ev["cell"] = 0
    check(not march.audit(b)["ok"], "a tampered selection is detected: the rebuild re-derives it")
    b, _m = march.Archive.read_files(t / "a")
    b.bursts[10].reaches[0][2] = (b.bursts[10].reaches[0][2] + 1) % 3
    check(not march.audit(b)["ok"], "a tampered insert / replace / keep action is detected")
    b, _m = march.Archive.read_files(t / "a")
    b.cells[5].L += 1
    check(not march.audit(b)["ok"], "a tampered cell length is detected")
    b, _m = march.Archive.read_files(t / "a")
    b.bursts[3].start_rep = (50, 0)
    check(not march.audit(b)["ok"], "a lineage that points forward is detected")
    shutil.rmtree(t, ignore_errors=True)
    return {"cells": len(a.cells), "wins": sum(len(b.wins) for b in a.bursts), "replacements": st["replacements"]}


def unit_checkpoint_atomicity() -> Dict[str, Any]:
    a1, pin, ctx, cum = drive_archive("easy", 12, "tck")
    n1 = len(a1.cells)
    out: Dict[str, Any] = {}
    for crash in (None, "tmp_written", "tmp_verified", "current_moved", "new_installed"):
        t = tmpdir()
        root = t / "archive"
        march.save_checkpoint(root, a1, {"checkpoint_seq": 1})
        a2, _p, _c, _cum = drive_archive("easy", 12, "tck")                     # identical, then extended below
        cum2 = 0
        for it in range(12, 24):
            cell = a2.dispatch(it, 0)
            res = mw.run_iterate(ctx, iterate_job(a2, cell, pin, it=it))
            a2.ingest(dict(res, cum_before=cum2, session="t"))
        n2 = len(a2.cells)
        check(n2 > n1, "the second archive is larger")
        try:
            march.save_checkpoint(root, a2, {"checkpoint_seq": 2}, crash_at=crash)
            check(crash is None, f"crash at {crash} did not raise")
        except march.SimulatedCrash:
            check(crash is not None, "unexpected crash")
        d, meta, rep = march.load_latest_verified(root)
        check(d is not None, f"no verified checkpoint after a crash at {crash}: {rep}")
        loaded, _m = march.Archive.read_files(d)
        seq = meta["checkpoint_seq"]
        check(len(loaded.cells) == (n2 if seq == 2 else n1), f"crash {crash}: the loaded checkpoint {seq} has {len(loaded.cells)} cells")
        check(march.audit(loaded)["ok"], f"crash {crash}: the loaded archive does not audit")
        check(seq == 2, f"crash at {crash}: the newest complete checkpoint (2) must be found, got {seq} from {d.name}")
        out[str(crash)] = {"found": d.name, "seq": seq}
        # tamper: one byte of cells.jsonl in the loaded directory is detected
        p = d / "cells.jsonl"
        raw = p.read_bytes()
        p.write_bytes(raw[:-3] + b"9\n" + raw[-1:] if len(raw) > 4 else raw)
        check(march.verify_manifest(d), "a modified data file is detected by the manifest")
        shutil.rmtree(t, ignore_errors=True)
    # nothing verifies -> None
    t = tmpdir()
    (t / "archive").mkdir()
    d, meta, rep = march.load_latest_verified(t / "archive")
    check(d is None and meta is None, "an empty directory has no checkpoint")
    shutil.rmtree(t, ignore_errors=True)
    return out


def unit_coverage_set() -> Dict[str, Any]:
    cs = march.CoverageSet()
    check(cs.visit(key(1, 1), 10, 5) and not cs.visit(key(1, 1), 20, 7), "first reach only")
    cs.visit(key(2, 1, "A2", 1022), 100, 40)
    cs.visit(key(3, 1, "G", 1020, 1), 200, 60)
    st = cs.stats()
    check(st["cells"] == 3 and st["masks"] == 3 and st["bins"] == 3, "stats")
    check(cs.stats(upto=100)["cells"] == 2, "within a comparison point")
    fr = cs.level_first_reach()
    check(fr[0] == {"cum": 10, "tick": 5} and fr[1]["cum"] == 100 and fr[2]["cum"] == 200, "first reach per level")
    return {"levels": sorted(fr)}


# -- claims: labelling, truncation, replay evaluation ---------------------------------------------------------------------------------


def labels(t_events=(), **first: Any) -> Dict[str, Any]:
    f = {"l0": None, "left_live": None, "left_floor": None, "left_break": None, "clear": None}
    f.update(first)
    return {"t": (t_events[-1][1] if t_events else 0), "breaks": [], "t_events": list(t_events), "first": f}


def unit_claims_ledger_rules() -> Dict[str, Any]:
    led = mclaims.ArmLedger("T")
    cb = led.commit(120)
    check(cb == 0 and led.ticks == 120, "cumulative start of the first job")
    led.register(cum_before=cb, iteration=0, words=bytes(120), prefix_len=0, labels=labels([(50, 1), (90, 2)]),
                 breaks=[(50, 3), (90, 4)], end_reason="length", t_end=2)
    cb = led.commit(100)
    check(cb == 120, "cumulative position of the second job")
    led.register(cum_before=cb, iteration=1, words=bytes(100), prefix_len=0, labels=labels([(40, 1), (95, 2), (97, 3)]),
                 breaks=[(40, 5), (95, 6), (97, 7)], end_reason="length", t_end=3)
    check([len(led.candidates[c]["words"]) for c in led.t_records[1]] == [50, 40], "t = 1: a strictly shorter trajectory is recorded")
    check([len(led.candidates[c]["words"]) for c in led.t_records[2]] == [90], "t = 2: a longer trajectory is not recorded")
    check([len(led.candidates[c]["words"]) for c in led.t_records[3]] == [97], "t = 3 recorded")
    cb = led.commit(160)
    check(cb == 220, "third job position")
    ids = led.register(cum_before=cb, iteration=2, words=bytes(160), prefix_len=0, labels=labels(
        [(150, 1)], l0=30, left_live=70, clear=160), breaks=[(150, 8)], end_reason="clear", t_end=1)
    kinds = [led.candidates[i]["kind"] for i in ids]
    check(kinds.count("l0") == 1 and kinds.count("left") == 1 and kinds.count("clear") == 1, f"candidates of a milestone job {kinds}")
    left = led.candidates[[i for i in ids if led.candidates[i]["kind"] == "left"][0]]
    l0 = led.candidates[led.l0_cid]
    check(left["event_j"] == 70 and len(left["words"]) == 160 and len(l0["words"]) == 30 and l0["event_j"] == 30,
          "a left candidate keeps the full trajectory, an l0 candidate stops at the landing")
    cb = led.commit(50)
    led.register(cum_before=cb, iteration=3, words=bytes(50), prefix_len=0, labels=labels(l0=10), breaks=[], end_reason="length", t_end=0)
    check(sum(1 for c in led.candidates if c["kind"] == "l0") == 1, "only the first wall-top landing is a candidate")
    # within the comparison point
    t, c, n = led.t_within(60)
    check(t == 1 and len(c["words"]) == 50 and n == 50, "T = 60: t = 1, the t = 1 trajectory of the first job")
    t, c, n = led.t_within(170)
    check(t == 2 and len(c["words"]) == 90, f"T = 170 gives t = {t}")
    t, c, n = led.t_within(250)
    check(t == 3 and len(c["words"]) == 97, "T = 250: t = 3")
    check(led.t_within(10)[0] == 0 and led.t_within(10)[1] is None, "nothing broken within T = 10")
    check(left["cum_before"] == 220, "the left candidate sits in the third job")
    check(led.counted_len(left, 285) is None and led.counted_len(left, 290) == 70 and led.counted_len(left, 300) == 80
          and led.counted_len(left, 5000) == 160,
          "a job straddling T is cut at T - cum_before; an event beyond T excludes it")
    check([len(x[0]["words"]) for x in led.within(100000, "clear")] == [160] and led.within(250, "clear") == [], "within() by kind")
    # planning
    done: Dict[int, Dict[str, Any]] = {}
    todo, info = mclaims.plan_replays(led, 100000, done, batch=3)
    check(todo[0][0]["kind"] == "t" and todo[0][0]["t"] == 3, "the max-t candidate comes first")
    check([x[0]["kind"] for x in todo] == ["t", "clear", "left"], f"plan order {[x[0]['kind'] for x in todo]}")
    check(info["remaining"] == {"clear": 1, "left_target": 1, "crossing": 1, "L0": 1} and not any(info["satisfied"].values()),
          f"remaining {info['remaining']}")
    done[todo[2][0]["cid"]] = {"exact": True, "l0": False, "crossing": False, "left_target": True, "clear": False}
    todo2, info2 = mclaims.plan_replays(led, 100000, done, batch=5)
    check(info2["satisfied"]["left_target"] and not info2["satisfied"]["crossing"] and info2["remaining"]["crossing"] == 0,
          "a replay credits every milestone it satisfies; an unqualified candidate is not retried")
    check(mclaims.milestone_level(list(done.values())) == 3, "m is the highest verified level")
    check(mclaims.milestone_level([{"exact": False, "l0": True, "crossing": True, "left_target": True, "clear": True}]) == 0,
          "an inexact replay credits nothing")
    check(mclaims.milestone_level([]) == 0 and mclaims.LADDER[mclaims.milestone_level([{"exact": True, "l0": True, "crossing": False,
          "left_target": False, "clear": False}])] == "L0", "ladder names")
    # the truncation: the same ledger, cut at T = 130, keeps only what happened within it
    check(led.within(130, "left") == [] and led.t_within(130)[0] == 2, "cut at 130")
    return {"candidates": len(led.candidates), "kinds": kinds}


def build_session_inproc(world: str = "easy", n_iter: int = 80, arm: str = "T") -> Tuple[Any, Any, Any]:
    """A Session (no processes) driven through its own make_job / commit with real worker iterate / control jobs."""
    import m8_rd_run as mrun

    root = tmpdir("m8s_")
    cfg = mrun.RunConfig(root=root, n_workers=1, arm_tick_cap=10 ** 9)
    env = mrun.RunEnv(worker_spec=lambda r, c: {}, replay=lambda *a: {}, analyse=stub.analyse, p1_inputs=lambda: [], pins={})
    sess = mrun.Session(cfg, env)
    ctx = job_ctx(world)
    sess.pin = pin_from(ctx)
    sess.init_archive()
    rows = cfg.session_dir / f"iterations_{arm}.jsonl"
    for _ in range(n_iter):
        job = sess.make_job(arm, 0, 10 ** 9)
        res = mw.run_iterate(ctx, job) if arm == "T" else mw.run_control(ctx, job)
        check(res["ok"], f"in-process job failed: {res}")
        sess.commit(arm, job, res, rows)
        sess.pool_job.pop(0, None)
    return sess, ctx, root


def unit_claims_roundtrip_on_stub() -> Dict[str, Any]:
    sess, ctx, root = build_session_inproc("easy", 120, "T")
    led = sess.ledgers["T"]
    kinds: Dict[str, int] = {}
    for c in led.candidates:
        kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
    check(kinds.get("t", 0) >= 3, f"too few t candidates {kinds}")
    check(kinds.get("l0", 0) == 1 and kinds.get("left", 0) >= 1, f"the easy stub world should produce a wall-top landing and a left visit: {kinds}")
    verified = 0
    for kind in ("t", "l0", "left", "clear"):
        for c in [x for x in led.candidates if x["kind"] == kind][:6]:
            n = len(c["words"])
            tr = stub.replay_trace("easy", bytes(c["words"]), "x")
            rep = mclaims.evaluate_replay(tr, c, n, stub.analyse)
            check(rep["exact"], f"candidate {c['cid']} ({kind}) is not exact: {rep['problems']}")
            if kind == "t":
                check(rep["t"] == c["t"], "a t candidate's replay breaks exactly t targets")
            if kind == "l0":
                check(rep["l0"] and rep["l0_tick"] == c["event_j"], "an l0 candidate's replay lands at the claimed tick")
            if kind == "clear":
                check(rep["clear"] and rep["clear_facts"]["all"], f"clear facts {rep['clear_facts']}")
            verified += 1
    # tampering
    c = [x for x in led.candidates if x["kind"] == "t"][-1]
    n = len(c["words"])
    tr = stub.replay_trace("easy", bytes(c["words"]), "x")
    bad = dict(tr, action_digest="0" * 64)
    check(not mclaims.evaluate_replay(bad, c, n, stub.analyse)["exact"], "a different action digest is inexact")
    check(not mclaims.evaluate_replay(dict(tr, consumed_tick_mismatch={"index": 1}), c, n, stub.analyse)["exact"], "a consumed-tick mismatch")
    check(not mclaims.evaluate_replay(dict(tr, unsent=3), c, n, stub.analyse)["exact"], "unsent words")
    c2 = dict(c, breaks=[(j + 1, i) for j, i in c["breaks"]])
    check(not mclaims.evaluate_replay(tr, c2, n, stub.analyse)["exact"], "an online break table that differs from the replay's")
    c3 = dict(c, t=c["t"] + 1)
    check(not mclaims.evaluate_replay(tr, c3, n, stub.analyse)["exact"], "a claimed t that the replay does not reproduce")
    lc = [x for x in led.candidates if x["kind"] == "l0"]
    if lc:
        c4 = dict(lc[0], event_j=lc[0]["event_j"] + 1)
        trl = stub.replay_trace("easy", bytes(lc[0]["words"]), "x")
        check(not mclaims.evaluate_replay(trl, c4, len(lc[0]["words"]), stub.analyse)["exact"], "a wrong claimed wall-top tick")
    shutil.rmtree(root, ignore_errors=True)
    # a clear: the trivial world clears at tick 1; control episodes register clear candidates whose replay satisfies all four facts
    sess2, ctx2, root2 = build_session_inproc("trivial", 4, "C")
    cl = [x for x in sess2.ledgers["C"].candidates if x["kind"] == "clear"]
    check(len(cl) == 4, f"four clears expected, got {len(cl)}")
    for c in cl:
        tr = stub.replay_trace("trivial", bytes(c["words"]), "x")
        rep = mclaims.evaluate_replay(tr, c, len(c["words"]), stub.analyse)
        check(rep["exact"] and rep["clear"] and rep["t"] == 10 and rep["clear_facts"]["completion_input_tick"] == len(c["words"]),
              f"a clear replay: {rep['problems']} {rep['clear_facts']}")
    shutil.rmtree(root2, ignore_errors=True)
    return {"verified_replays": verified, "kinds": kinds}


def unit_real_analysis_on_recorded_trace() -> Dict[str, Any]:
    """The registered analyser (m7n_crossing.analyse_trace) and evaluate_replay on a REAL recorded replay: the exact replay of
    M7p's seed-1 candidate A (a qualified crossing, a left-target break and a wall-top landing)."""
    import m7n_crossing as xc

    check(M7P_CROSSING_TRACE.is_file() and M7P_CROSSING_ARTIFACT.is_dir(), "the preserved M7p crossing replay is missing")
    with gzip.open(M7P_CROSSING_TRACE, "rt", encoding="utf-8") as f:
        tr = json.load(f)
    idx = {t: i for i, t in enumerate(mcell.TRIPLES)}
    words = bytearray()
    for line in (M7P_CROSSING_ARTIFACT / "actions.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        words.append(idx[(r["buttons"], r["stick_x"], r["stick_y"])])
    words = bytes(words)
    n = len(tr["steps"])
    check(n <= len(words), "the trace and the artifact line up")
    words = words[:n]
    scanner = mcell.BurstScanner(tr["initial"]["spatial"]["target_live_mask"])
    for r in tr["steps"]:
        scanner.feed(r["observation"]["input_tick"], r["observation"], r["spatial"], r["state"])
    lab = scanner.labels()
    cand = {"cid": 0, "arm": "T", "kind": "left", "iteration": 0, "cum_before": 0, "event_j": min(
        v for k, v in lab["first"].items() if k.startswith("left") and v is not None), "t": None, "words": words,
        "breaks": scanner.breaks, "first": lab["first"]}
    tr = dict(tr, action_digest=mcell.words_digest(words), unsent=0, consumed_tick_mismatch=None)
    rep = mclaims.evaluate_replay(tr, cand, n, xc.analyse_trace)
    check(rep["exact"], f"the real replay is not exact: {rep['problems']}")
    check(rep["crossing"] and rep["left_target"] and rep["l0"], f"milestones of the recorded crossing: {mclaims.levels_of(rep)}")
    check(not rep["clear"] and rep["t"] == len(scanner.breaks), "no clear; the break table equals the online one")
    check(lab["first"]["l0"] is not None and rep["l0_tick"] == lab["first"]["l0"], "the online wall-top tick equals the replay's")
    # truncation: the same replay cut before the crossing credits no crossing
    cut = (rep["first_qualified_entry"] or 10 ** 6)
    n2 = max(10, int(cut) - 5)
    tr2 = dict(tr, steps=tr["steps"][:n2], action_digest=mcell.words_digest(words[:n2]))
    cand2 = dict(cand, words=words[:n2], breaks=[b for b in scanner.breaks if b[0] <= n2])
    rep2 = mclaims.evaluate_replay(tr2, cand2, n2, xc.analyse_trace)
    check(rep2["exact"] and not rep2["crossing"], f"a replay cut before the crossing credits none: {rep2['problems']}")
    return {"words": n, "levels": mclaims.levels_of(rep), "entry_tick": rep["first_qualified_entry"], "breaks": rep["breaks"][:6]}


def unit_clear_facts() -> Dict[str, Any]:
    ok_trace = {"final_state": "EpisodeEnded", "steps": [{"observation": {"btt_active": 1, "targets_remaining": 0}}],
                "result": {"outcome": "clear", "targets_broken": 10, "completion_time_passed": 446, "completion_input_tick": 447}}
    f = mclaims.clear_facts(ok_trace, 10)
    check(f["all"] and f["completion_time_passed"] == 446 and f["completion_input_tick"] == 447, "all four facts")
    for name, tr, n in (("end reason", dict(ok_trace, final_state="WaitingForAction"), 10),
                        ("cleared flag", dict(ok_trace, result=dict(ok_trace["result"], outcome="fall")), 10),
                        ("ten targets", ok_trace, 9),
                        ("completion clock", dict(ok_trace, result=dict(ok_trace["result"], completion_input_tick=None)), 10),
                        ("no result", dict(ok_trace, result=None), 10)):
        check(not mclaims.clear_facts(tr, n)["all"], f"a clear without its {name} must not count")
    return {}


# -- worker jobs (in process, against the stub) ----------------------------------------------------------------------------------------


class Flag:
    def __init__(self, after: int = 0):
        self.n, self.after = 0, after

    def is_set(self) -> bool:
        self.n += 1
        return self.n > self.after


def unit_worker_iterate_and_returns() -> Dict[str, Any]:
    ctx = job_ctx("easy")
    pin = pin_from(ctx)
    a = march.Archive("w")
    a.init_cell0(tuple(pin["key"]), pin["obs"], bytes.fromhex(pin["digest"]), bytes.fromhex(pin["chain"]))
    c0 = a.cells[0]
    r0 = mw.run_iterate(ctx, iterate_job(a, c0, pin, it=0))
    check(r0["ok"] and r0["end_reason"] in ("length", "fall", "clear"), f"first burst {r0.get('end_reason')}")
    check(r0["ticks"] == len(r0["words"]) and r0["L"] == 0 and r0["prefix"]["words"] == 0, "ticks of a burst from cell 0")
    check(r0["tick0"]["equal"] and r0["labels"]["t"] == r0["t_end"], "tick-0 equal; the scanner's t")
    # determinism: the same keyed burst again (another process) is identical word for word and reply for reply
    r0b = mw.run_iterate(ctx, iterate_job(a, c0, pin, it=0))
    check(r0b["words"] == r0["words"] and [x[:2] for x in r0b["reaches"]] == [x[:2] for x in r0["reaches"]], "keyed bursts repeat")
    check([x[3:5] for x in r0b["reaches"]] == [x[3:5] for x in r0["reaches"]], "record digests and chains repeat across processes")
    a.ingest(dict(r0, cum_before=0, session="t"))
    cells = [c for c in a.cells if c.id and c.L >= 12]
    c = cells[len(cells) // 2]
    job = iterate_job(a, c, pin, it=1, burst_words=0)
    ret = mw.run_iterate(ctx, job)
    check(ret["ok"] and ret["prefix"]["end_equal"] and ret["prefix"]["chain_equal"] and ret["prefix"]["end_digest_equal"]
          and ret["end_reason"] == "length" and ret["words"] == b"" and ret["ticks"] == c.L, "a return verifies the end record and the chain")
    check(ret["prefix"]["host_frame_equal"] in (True, False), "host_frame is only reported")
    # tampering: the end observation, the end digest, the chain
    for what, mutate in (("end observation", lambda j: j.update(end=tuple(list(j["end"][:8]) + [j["end"][8] + 0.25] + list(j["end"][9:])))),
                         ("end digest", lambda j: j.update(end_digest=bytes(32))),
                         ("chain", lambda j: j.update(chain=bytes(32))),
                         ("integer type", lambda j: j.update(end=tuple(list(j["end"][:6]) + [float(j["end"][6])] + list(j["end"][7:]))))):
        j = dict(job)
        mutate(j)
        r = mw.run_job(ctx, j)
        check(not r["ok"] and r["kind"] == "mismatch" and r["mismatch"] == "prefix_end", f"a tampered {what} was not refused: {r}")
    # the tick-0 pin
    j = dict(job, pin=dict(pin, digest="0" * 64))
    r = mw.run_job(ctx, j)
    check(not r["ok"] and r["mismatch"] == "tick0", "a different pinned tick-0 record is refused")
    j = dict(job, pin=dict(pin, obs=pin["obs"][:8] + [pin["obs"][8] + 1.0] + pin["obs"][9:]))
    r = mw.run_job(ctx, j)
    check(not r["ok"] and r["mismatch"] == "tick0", "a different pinned tick-0 observation is refused")
    # a wrong word anywhere in the prefix changes the end record
    w = bytearray(job["words"])
    w[3] = (w[3] + 17) % 72
    r = mw.run_job(ctx, dict(job, words=bytes(w)))
    check(not r["ok"] and r["mismatch"] in ("prefix_end", "prefix_ended"), "a changed prefix word is refused")
    # allowance cuts
    L = c.L
    cut1 = mw.run_iterate(ctx, dict(job, allowance=L - 3, burst_words=120))
    check(cut1["ok"] and cut1["end_reason"] == "cut" and cut1["ticks"] == L - 3 and cut1["words"] == b"" and cut1["labels"] is None
          and cut1["prefix"]["cut"], "an allowance inside the prefix cuts the iteration there")
    cut2 = mw.run_iterate(ctx, dict(job, allowance=L + 17, burst_words=120))
    check(cut2["ok"], "a cut burst is a result")
    check(cut2["end_reason"] in ("fall", "clear", "ended") or (cut2["end_reason"] == "cut" and cut2["ticks"] == L + 17
                                                               and len(cut2["words"]) == 17),
          f"an allowance inside the burst cuts it there: {cut2['end_reason']} {cut2['ticks']}")
    # abort, lifecycle, contract violation, request errors
    r = mw.run_job(job_ctx("easy", abort=Flag(0)), job)
    check(not r["ok"] and r["kind"] == "aborted", "an abort flag ends the job")
    ctx2 = job_ctx("easy", inject={"lifecycle_jobs": [1]})
    r = mw.run_job(ctx2, iterate_job(a, c0, pin, it=0))
    check(not r["ok"] and r["kind"] == "lifecycle" and r["outcome"] == "premature_exit", "a process death is a lifecycle failure")
    ctx3 = job_ctx("easy", inject={"bad_consumed_job": 1}, failure_dir=tmpdir("m8f_"))
    r = mw.run_job(ctx3, iterate_job(a, c0, pin, it=0))
    check(not r["ok"] and r["kind"] == "mismatch" and r["mismatch"] == "consumed_tick", f"a consumed-tick violation: {r}")
    check(r["detail"].get("preserved") and Path(r["detail"]["preserved"]).is_file(), "the failed job's raw replies are preserved")
    with gzip.open(r["detail"]["preserved"], "rt", encoding="utf-8") as f:
        pres = json.load(f)
    check(len(pres["replies"]) == 5 and pres["kind"] == "consumed_tick", "the preserved record holds the replies up to the violation")
    r = mw.run_job(job_ctx("easy"), {"kind": "iterate", "bogus": 1})
    check(not r["ok"] and r["kind"] == "error", "an unexpected exception is a structured error")
    return {"L": L, "reach_count": len(r0["reaches"])}


def unit_worker_horizon_fall_clear_control() -> Dict[str, Any]:
    ctx = job_ctx("calm")
    pin = pin_from(ctx)
    a = march.Archive("cal")
    a.init_cell0(tuple(pin["key"]), pin["obs"], bytes.fromhex(pin["digest"]), bytes.fromhex(pin["chain"]))
    r = mw.run_iterate(ctx, iterate_job(a, a.cells[0], pin, it=0, burst_words=5000, allowance=10 ** 6))
    check(r["ok"] and r["end_reason"] == "horizon" and r["ticks"] == 3600 and len(r["words"]) == 3600,
          f"a burst is clipped at the 3,600-tick horizon: {r['end_reason']} {r['ticks']}")
    rc = mw.run_control(ctx, {"kind": "control", "episode": 0, "pin": pin, "allowance": 10 ** 6})
    check(rc["ok"] and rc["end_reason"] == "horizon" and rc["ticks"] == 3600 and rc["tick0"]["equal"], "a control episode runs to the horizon")
    check(all(len(x) == 2 for x in rc["reaches"]) and [x[0] for x in rc["reaches"]] == sorted({x[0] for x in rc["reaches"]}), "control reaches (j, key)")
    rc2 = mw.run_control(ctx, {"kind": "control", "episode": 0, "pin": pin, "allowance": 500})
    check(rc2["end_reason"] == "cut" and rc2["ticks"] == 500 and rc2["words"] == rc["words"][:500], "the allowance cuts a control episode")
    check(mw.run_control(ctx, {"kind": "control", "episode": 1, "pin": pin, "allowance": 10 ** 6})["words"] != rc["words"], "episodes differ")
    # a native failure ends the run at that tick
    ctx = job_ctx("easy")
    pin = pin_from(ctx)
    fall = None
    for ep in range(60):
        r = mw.run_control(ctx, {"kind": "control", "episode": ep, "pin": pin, "allowance": 10 ** 6})
        if r["end_reason"] == "fall":
            fall = r
            break
    check(fall is not None, "no episode fell in the easy world within 60 tries")
    tr = stub.replay_trace("easy", bytes(fall["words"]), "f")
    last = tr["steps"][-1]
    check(mcell.is_native_failure(last["observation"], last["state"]) and tr["unsent"] == 0 and fall["ticks"] == len(tr["steps"]),
          "the episode ended at the first native-failure reply, with no further step")
    check(all(not mcell.is_native_failure(s["observation"], s["state"]) for s in tr["steps"][:-1]), "no earlier native failure")
    # a clear is finished natively and reports both clocks
    ctx = job_ctx("trivial")
    pin = pin_from(ctx)
    r = mw.run_control(ctx, {"kind": "control", "episode": 0, "pin": pin, "allowance": 10 ** 6})
    check(r["ok"] and r["end_reason"] == "clear" and r["labels"]["first"]["clear"] == r["ticks"] and r["result_json"]["outcome"] == "clear",
          f"a clear: {r['end_reason']} {r['ticks']}")
    check(r["result_json"]["completion_input_tick"] == r["result_json"]["completion_time_passed"] + 1, "the two completion clocks")
    check(r["t_end"] == 10 and len(r["labels"]["breaks"]) == 10, "ten breaks")
    a = march.Archive("tri")
    a.init_cell0(tuple(pin["key"]), pin["obs"], bytes.fromhex(pin["digest"]), bytes.fromhex(pin["chain"]))
    ri = mw.run_iterate(ctx, iterate_job(a, a.cells[0], pin, it=0))
    check(ri["end_reason"] == "clear" and ri["reaches"][-1][5] is True, "the terminal reach of a clear is marked terminal")
    return {"horizon_ticks": 3600, "fall_ticks": fall["ticks"]}


def unit_worker_trace_and_reverify() -> Dict[str, Any]:
    import m8_rd_report as rpt

    ctx = job_ctx("easy")
    pin = pin_from(ctx)
    tin = stub.p1_inputs("easy")
    for t in tin:
        job = {"kind": "trace", "name": t["name"], "words": t["words"], "expected_digests": t["expected_digests"],
               "expected_host_frames": t["expected_host_frames"], "pin": pin, "allowance": len(t["words"])}
        r = mw.run_job(ctx, job)
        check(r["ok"] and r["native_action_digest"] == t["native_action_digest"], f"trace {t['name']}: {r.get('mismatch')}")
        check(0 <= r["host_frames_equal"] <= len(t["words"]), "host_frame equality is only counted and reported")
        bad = list(t["expected_digests"])
        bad[len(bad) // 2] = bytes(32)
        r = mw.run_job(ctx, dict(job, expected_digests=bad))
        check(not r["ok"] and r["mismatch"] == "trace", "a changed pinned reply digest is refused")
    # reverify (rebuilt-executable path): one replay per burst, every cell checked at its L
    a, pin, ctx, cum = drive_archive("easy", 25, "trv")
    jobs = rpt.reverify_plan(a)
    covered = sum(len(j["checks"]) for j in jobs)
    check(covered + 1 == len(a.cells), "every cell but cell 0 is checked exactly once")
    for j in jobs:
        j = dict(j, pin=pin)
        r = mw.run_job(ctx, j)
        check(r["ok"] and sorted(r["verified_cells"]) == sorted(c["cell"] for c in j["checks"]), f"reverify burst {j['burst']}: {r}")
    j = dict(jobs[len(jobs) // 2], pin=pin)
    checks = [dict(c) for c in j["checks"]]
    checks[-1] = dict(checks[-1], chain=bytes(32))
    r = mw.run_job(ctx, dict(j, checks=checks))
    check(not r["ok"] and r["mismatch"] == "reverify", "a changed chain stops the re-verification at that cell")
    proj = rpt.reverify_projection(Path(tempfile.gettempdir()) / "m8_no_such_root")
    check(not proj["ok"], "no archive, no projection")
    return {"bursts": len(jobs), "ticks": sum(len(j["words"]) for j in jobs)}


# -- the session: small end-to-end runs with real worker processes against the stub ----------------------------------------------------


def small_cfg(root: Path, **kw: Any) -> Any:
    import m8_rd_run as mrun

    base = dict(root=root, n_workers=3, arm_tick_cap=6000, min_arm_ticks=2000, p1_tick_cap=5000, replay_tick_cap=300000,
                wall_caps_s={"p1": 90.0, "T": 120.0, "C": 120.0, "verify": 120.0}, global_cap_s=600.0, checkpoint_every_s=4.0,
                verify_threads=2, identity_k=6)
    base.update(kw)
    return mrun.RunConfig(**base)


def stub_env(world: str = "easy", inject: Optional[Mapping[str, Any]] = None, **kw: Any) -> Any:
    import m8_rd_run as mrun

    def worker_spec(rank: int, cfg: Any) -> Dict[str, Any]:
        return {"rank": rank, "backend": "m8_rd_stub:StubBackend", "world": world, "inject": dict(inject or {}),
                "failure_dir": str(cfg.session_dir / "failures")}

    def replay(cand: Mapping[str, Any], counted: int, label: str, slot: int) -> Dict[str, Any]:
        return stub.replay_trace(world, bytes(cand["words"][:counted]), label)

    return mrun.RunEnv(worker_spec=worker_spec, replay=replay, analyse=stub.analyse, p1_inputs=lambda: stub.p1_inputs(world),
                       pins={"stub": True}, log=kw.pop("log", lambda s: None), **kw)


_SMALL: Dict[str, Any] = {}


def run_small(name: str, world: str = "easy", inject: Optional[Mapping[str, Any]] = None, env_kw: Optional[Mapping[str, Any]] = None,
              **cfg_kw: Any) -> Tuple[Dict[str, Any], Any, Path]:
    import m8_rd_finish as fin
    import m8_rd_run as mrun

    if name in _SMALL and not cfg_kw and not inject and not env_kw:
        return _SMALL[name]
    root = tmpdir(f"m8e_{name}_")
    cfg = small_cfg(root, **cfg_kw)
    mw.ProvenanceGuard.violations.clear()
    sess = mrun.Session(cfg, stub_env(world, inject, **dict(env_kw or {})))
    out = fin.run_all(sess)
    res = (out, sess, root)
    if not cfg_kw and not inject and not env_kw:
        _SMALL[name] = res
    return res


def unit_session_small_run() -> Dict[str, Any]:
    import m8_rd_report as rpt

    out, sess, root = run_small("base")
    rule, close = out["rule"], out["close"]
    check(rule["outcome"] in ("PASS", "NULL", "INCONCLUSIVE") and not rule["invalid"] and not rule["incomplete"],
          f"a complete small session: {rule['outcome']} {rule['invalid']} {rule['incomplete']}")
    check(sess.ledgers["T"].ticks == 6000 and sess.ledgers["C"].ticks == 6000, f"budgets {sess.ledgers['T'].ticks} {sess.ledgers['C'].ticks}")
    sd = sess.cfg.session_dir
    for f in ("p1.json", "arm_T.json", "arm_C.json", "verification.json", "rule.json", "close.json", "state.json",
              "iterations_T.jsonl", "iterations_C.jsonl", "ledger_T.json", "ledger_C.json", "coverage_C.json.gz",
              "candidates_T.jsonl.gz", "candidates_C.jsonl.gz"):
        check((sd / f).is_file(), f"missing {f}")
    p1 = json.loads((sd / "p1.json").read_text(encoding="utf-8"))
    check(p1["selftest"]["corrupted_refused"] and p1["selftest"]["refusal"] == "prefix_end" and len(p1["selftest"]["returned"]) == 3,
          "the P1 self-test returned three cells and refused the corrupted one")
    check(len(p1["traces"]) == 2 and all(isinstance(t["host_frames_equal"], int) for t in p1["traces"]), "P1 replayed both pinned traces")
    check(p1["tick0"]["host_frame_equal"] in (False, True) and p1["tick0"]["modes"] == ["standby_promoted"] * 2, "P1 tick-0 reproduced")
    check(close["audit"]["ok"] and close["audit"]["prefixes_reconstructed"] == close["audit"]["cells"], f"close audit {close['audit']}")
    vr = rpt.verify_run(root, "rd1")
    check(vr["ok"], f"verify-run: {vr['problems']}")
    rows = [json.loads(x) for x in (sd / "iterations_T.jsonl").read_text(encoding="utf-8").splitlines()]
    check(sum(r["ticks"] for r in rows if "ticks" in r) == 6000, "iteration rows add up to the arm's ticks")
    check(all(r["tick0_equal"] for r in rows if "ticks" in r), "tick-0 equal on every iteration")
    ver = json.loads((sd / "verification.json").read_text(encoding="utf-8"))
    check(ver["identity"]["ok"] and ver["identity"]["cells"] == 6 and ver["identity"]["verified"] == 6, f"identity replays {ver['identity']}")
    check(ver["comparison_point"]["T"] == 6000 and ver["replay_ticks"] > 0, "verification record")
    for arm in ("T", "C"):
        check(ver["arms"][arm]["claims"].get("t") is not None or ver["arms"][arm]["t"] == 0, f"arm {arm} verified a t claim")
    check(list((root / "routes").glob("*")), "routes were stored")
    r0 = sorted((root / "routes").glob("*"))[0]
    check((r0 / "actions.jsonl").is_file() and (r0 / "metadata.json").is_file() and (r0 / "trace.json.gz").is_file(), "route files")
    rep = rpt.build_report(root, "rd1")
    check(rep["comparison_point"] == 6000 and rep["arms"]["T"]["full"]["cells"] == len(sess.archive.cells) and
          rep["arms"]["C"]["full"]["cells"] == len(sess.coverage.keys), "the report's coverage equals the archive and the coverage set")
    check(rep["arms"]["T"]["within_T"]["cells"] == rep["arms"]["T"]["full"]["cells"], "within T = full when both arms have the same ticks")
    check(sess.archive.stats()["cells"] == rep["arms"]["T"]["archive"]["cells"], "archive stats")
    return {"outcome": rule["outcome"], "cells_T": len(sess.archive.cells), "cells_C": len(sess.coverage.keys),
            "m": [rule["m_T"], rule["m_C"]], "t": [rule["t_T"], rule["t_C"]]}


def unit_session_budget_exact_cut() -> Dict[str, Any]:
    out, sess, root = run_small("cut", n_workers=5, arm_tick_cap=7777, min_arm_ticks=2000)
    for arm in ("T", "C"):
        check(sess.ledgers[arm].ticks == 7777, f"arm {arm} committed {sess.ledgers[arm].ticks} ticks, not exactly 7,777")
        rows = [json.loads(x) for x in (sess.cfg.session_dir / f"iterations_{arm}.jsonl").read_text(encoding="utf-8").splitlines()]
        check(sum(r["ticks"] for r in rows if "ticks" in r) == 7777, f"arm {arm}: rows sum to the cap")
    cut = [r for r in (json.loads(x) for x in (sess.cfg.session_dir / "iterations_T.jsonl").read_text(encoding="utf-8").splitlines())
           if r.get("end_reason") == "cut"]
    check(len(cut) >= 1 and sess.ledgers["T"].cut_jobs == len(cut), f"the iteration in progress at the budget is cut there ({len(cut)})")
    check(out["rule"]["outcome"] in ("PASS", "NULL", "INCONCLUSIVE"), f"a complete session {out['rule']['outcome']} {out['rule']['incomplete']}")
    return {"T": sess.ledgers["T"].ticks, "cut_jobs": len(cut)}


def unit_session_truncation_at_the_slower_arm() -> Dict[str, Any]:
    """Amendment 1: arms capped separately (the test hook), compared at T = the slower arm's count; the faster arm's
    milestones count only if they happened within its first T cumulative ticks."""
    out, sess, root = run_small("trunc", arm_caps={"T": 9000, "C": 4000}, arm_tick_cap=9000, min_arm_ticks=2000)
    rule = out["rule"]
    check(sess.ledgers["T"].ticks == 9000 and sess.ledgers["C"].ticks == 4000, "the arms stopped at their own caps")
    check(rule["extra"]["comparison_point"] == 4000, f"the comparison point is the slower arm's tick count: {rule['extra']}")
    check(rule["outcome"] in ("PASS", "NULL", "INCONCLUSIVE"), f"valid: {rule['outcome']} {rule['incomplete']}")
    ver = json.loads((sess.cfg.session_dir / "verification.json").read_text(encoding="utf-8"))
    check(ver["comparison_point"]["slower"] == "C", "the slower arm is C")
    led = sess.ledgers["T"]
    replays = [json.loads(x) for x in (sess.cfg.session_dir / "verification" / "replays.jsonl").read_text(encoding="utf-8").splitlines()]
    t_reps = [r for r in replays if r["arm"] == "T"]
    check(t_reps, "arm T had candidates to verify")
    for r in t_reps:
        c = led.candidates[r["cid"]]
        check(c["cum_before"] + c["event_j"] <= 4000, f"a candidate beyond the comparison point was replayed: {c['cum_before']} + {c['event_j']}")
        check(r["counted"] <= 4000 - c["cum_before"] or r["counted"] == len(c["words"]) and c["cum_before"] + len(c["words"]) <= 4000,
              "the replayed words are cut at the comparison point")
        check(r["counted"] + c["cum_before"] <= 4000, "no replayed word lies beyond the first T cumulative ticks")
    t_claim, cand, n = led.t_within(4000)
    check(ver["arms"]["T"]["t"] == t_claim, f"the verified t of the faster arm equals its online t within T ({ver['arms']['T']['t']} vs {t_claim})")
    full_t = led.max_t_online
    check(full_t >= t_claim, "the unrestricted online maximum is at least the maximum within T")
    # the milestone ladder of the faster arm within T equals the ladder of the claims whose events lie within T
    for kind in ("left", "clear"):
        for c, n in led.within(4000, kind):
            check(c["cum_before"] + c["event_j"] <= 4000, "within() honours the comparison point")
    return {"T_online_max": full_t, "T_within_T": t_claim, "replays_T": len(t_reps)}


def unit_session_outcomes_and_stops() -> Dict[str, Any]:
    res: Dict[str, Any] = {}
    # below the minimum -> INCOMPLETE, named
    out, sess, _r = run_small("min", arm_tick_cap=3000, min_arm_ticks=5000)
    check(out["rule"]["outcome"] == "INCOMPLETE" and any("reached 3,000" in x for x in out["rule"]["incomplete"]),
          f"below the minimum: {out['rule']['outcome']} {out['rule']['incomplete']}")
    res["below_minimum"] = out["rule"]["outcome"]
    # lifecycle failures: up to three are redrawn, more is INCOMPLETE
    out, sess, _r = run_small("lc", inject={"lifecycle_jobs": [10]}, n_workers=2, arm_tick_cap=8000, min_arm_ticks=1000)
    check(sess.lifecycle_failures["T"] >= 1 and sess.lifecycle_failures["T"] <= 3 and sess.ledgers["T"].ticks == 8000,
          f"redrawn lifecycle failures {sess.lifecycle_failures}, ticks {sess.ledgers['T'].ticks}")
    check(out["rule"]["outcome"] in ("PASS", "NULL", "INCONCLUSIVE"), f"three or fewer lifecycle failures: {out['rule']['outcome']}")
    ev = [json.loads(x) for x in (sess.cfg.session_dir / "iterations_T.jsonl").read_text(encoding="utf-8").splitlines()]
    check(any(e.get("event") == "lifecycle_failure" for e in ev), "the failure is recorded in the ledger")
    check(any(e["ev"] == "fail" for e in sess.archive.events), "the archive ledger records the failed iteration")
    res["lifecycle_redrawn"] = sess.lifecycle_failures["T"]
    out, sess, _r = run_small("lc4", inject={"lifecycle_jobs": [10, 11, 12, 13]}, n_workers=2, arm_tick_cap=12000, min_arm_ticks=1000)
    check(out["rule"]["outcome"] == "INCOMPLETE" and any("lifecycle failures" in x for x in out["rule"]["incomplete"]),
          f"more than three lifecycle failures: {out['rule']['outcome']} {out['rule']['incomplete']}")
    res["lifecycle_over"] = out["rule"]["outcome"]
    # an integrity failure in a prefix -> INVALID, raw replies preserved
    out, sess, root = run_small("inv", inject={"mismatch_job": 10, "mismatch_tick": 5}, n_workers=2, arm_tick_cap=20000, min_arm_ticks=1000)
    check(out["rule"]["outcome"] == "INVALID" and any("prefix_end" in x for x in out["rule"]["invalid"]),
          f"an integrity mismatch: {out['rule']['outcome']} {out['rule']['invalid']}")
    check(list((sess.cfg.session_dir / "failures").glob("iterate_*")), "the failed iteration's raw replies are preserved")
    res["mismatch"] = out["rule"]["outcome"]
    # a provenance violation -> INVALID
    out, sess, _r = run_small("prov", inject={"provenance_job": 2}, n_workers=2, arm_tick_cap=4000, min_arm_ticks=1000)
    check(out["rule"]["outcome"] == "INVALID" and any("provenance" in x for x in out["rule"]["invalid"]),
          f"a provenance violation: {out['rule']['outcome']} {out['rule']['invalid']}")
    res["provenance"] = out["rule"]["outcome"]
    # a memory breach / a process-count breach -> INCOMPLETE, no second arm
    class LateBreach:
        def __init__(self) -> None:
            self.t0 = time.monotonic()

        @property
        def breach(self) -> Optional[str]:
            return "memory cap: process tree private 99999 MB > 9216 MB" if time.monotonic() - self.t0 > 2.5 else None

    out, sess, _r = run_small("mem", env_kw={"sampler": LateBreach()}, inject={"slow_s": 0.05}, n_workers=2, arm_tick_cap=10 ** 7,
                              min_arm_ticks=1000)
    check(out["rule"]["outcome"] == "INCOMPLETE" and any("memory cap" in x for x in out["rule"]["incomplete"]), "a memory breach is INCOMPLETE")
    check("C" not in sess.arm_records and sess.arm_records["T"]["stop"][0] == "cap", "a memory stop ends the arm and no second arm runs")
    res["memory"] = out["rule"]["outcome"]
    out, sess, _r = run_small("proc", env_kw={"tree_snapshot": lambda: {"battleship": 11}}, inject={"slow_s": 0.05}, n_workers=2,
                              arm_tick_cap=10 ** 6, min_arm_ticks=1000, process_check_every_s=0.05)
    check(out["rule"]["outcome"] == "INCOMPLETE" and any("11 BattleShip processes" in x for x in out["rule"]["incomplete"]),
          f"a process-count breach: {out['rule']['incomplete']}")
    res["processes"] = out["rule"]["outcome"]
    # the arm's wall cap: a valid, shorter arm (>= the minimum); the other arm is compared at its count
    out, sess, _r = run_small("wall", inject={"slow_s": 0.04}, n_workers=2, arm_tick_cap=10 ** 7, min_arm_ticks=500,
                              wall_caps_s={"p1": 90.0, "T": 2.0, "C": 2.0, "verify": 120.0}, global_cap_s=900.0)
    tT, tC = sess.ledgers["T"].ticks, sess.ledgers["C"].ticks
    check(sess.arm_records["T"]["stop"][0] == "wall_cap" and 500 <= tT < 10 ** 7, f"T stopped at its wall cap with {tT} ticks")
    check(out["rule"]["extra"]["comparison_point"] == min(tT, tC), "the comparison point is the slower arm")
    check(out["rule"]["outcome"] in ("PASS", "NULL", "INCONCLUSIVE") and not out["rule"]["incomplete"],
          f"a wall-capped arm at or above the minimum is valid: {out['rule']['outcome']} {out['rule']['incomplete']}")
    res["wall_cap"] = {"T": tT, "C": tC}
    return res


def unit_session_verification_cap() -> Dict[str, Any]:
    """The replay cap leaves candidates unverified; INCOMPLETE only when they could change the outcome."""
    out, sess, _r = run_small("rcap", replay_tick_cap=200, arm_tick_cap=6000, min_arm_ticks=2000)
    ver = json.loads((sess.cfg.session_dir / "verification.json").read_text(encoding="utf-8"))
    check(ver["cap_hit"] is not None, "the replay cap was hit")
    check(out["rule"]["outcome"] in ("INCOMPLETE", "PASS", "NULL", "INCONCLUSIVE"), "an outcome is recorded")
    if out["rule"]["outcome"] == "INCOMPLETE":
        check(ver.get("could_change_outcome") is True or any("maximum-targets candidate" in x for x in out["rule"]["incomplete"]),
              f"INCOMPLETE only when unverified candidates could change the outcome: {out['rule']['incomplete']}")
    else:
        check(ver.get("could_change_outcome") in (False, None), "a cap that cannot change the outcome is not INCOMPLETE")
    return {"outcome": out["rule"]["outcome"], "could_change": ver.get("could_change_outcome")}


# -- runtime pins, guards, approval, readiness ---------------------------------------------------------------------------------------


def unit_frozen_runtime_and_preserve() -> Dict[str, Any]:
    import m8_rd_session as ses

    t = tmpdir("m8fz_")
    exe = t / "exe"
    exe.mkdir()
    for n in ses.EXE_COPY_FILES:
        (exe / n).write_bytes(f"content of {n}".encode())
    (exe / "BattleShip.cfg.json").write_text(json.dumps({"CVars": {"gSettings": {"Other": 1}}}), encoding="utf-8")
    (exe / "imgui.ini").write_text("[Window]\nPos=1,1\n", encoding="utf-8")
    (exe / ".tcc").mkdir()
    (exe / ".tcc" / "inc.h").write_text("x", encoding="utf-8")
    (exe / "assets").mkdir()
    (exe / "assets" / "a.txt").write_text("a", encoding="utf-8")
    arch = t / "archive"
    rec = ses.preserve_runtime(arch, exe)
    rt = arch / "runtime"
    for n in ("BattleShip.cfg.json", "imgui.ini"):
        check(mw.sha256_file(rt / n) == rec["frozen_sha256"][n] == mw.sha256_file(exe / n), f"frozen {n}")
    check(all((rt / "exe" / n).is_file() for n in ses.EXE_COPY_FILES) and (rt / "exe" / ".tcc" / "inc.h").is_file()
          and (rt / "exe" / "assets" / "a.txt").is_file() and (rt / "frozen_runtime.json").is_file(), "the runnable copy")
    raises(RuntimeError, lambda: ses.preserve_runtime(arch, exe), "a second freeze must be refused")
    # the frozen copy replaces the private one and is re-hashed
    fz = mw.FrozenRuntime(rt, rec["frozen_sha256"])
    run = t / "rt1"
    run.mkdir()
    (run / "BattleShip.cfg.json").write_text("live changed config", encoding="utf-8")
    (run / "imgui.ini").write_text("live", encoding="utf-8")
    got = fz.install(run)
    check(got == rec["frozen_sha256"] and (run / "BattleShip.cfg.json").read_bytes() == (exe / "BattleShip.cfg.json").read_bytes(),
          "install replaces the private config with the frozen copy")
    (rt / "BattleShip.cfg.json").write_text("tampered", encoding="utf-8")
    e = raises(mw.MismatchError, lambda: fz.install(run), "a tampered frozen file must be refused")
    check(e.kind == "pin_drift", "pin drift")
    raises(mw.WorkerError, lambda: mw.FrozenRuntime(rt, {"BattleShip.cfg.json": "x"}), "the frozen set is exactly the two files")
    # a controller-rule CVar refuses the freeze
    t2 = tmpdir("m8fz2_")
    shutil.copytree(exe, t2 / "exe")
    (t2 / "exe" / "BattleShip.cfg.json").write_text(json.dumps({"CVars": {"gCasualRules": {"AutoZCancel": 1}}}), encoding="utf-8")
    raises(RuntimeError, lambda: ses.preserve_runtime(t2 / "archive", t2 / "exe"), "AutoZCancel set must refuse")
    shutil.rmtree(t, ignore_errors=True)
    shutil.rmtree(t2, ignore_errors=True)
    return {"files": sorted(rec["frozen_sha256"])}


def unit_controller_cvars() -> Dict[str, Any]:
    import m8_rd_session as ses

    t = tmpdir("m8cv_")
    cases = [({}, True), ({"CVars": {"gTapJumpDisabled": {"P1": 0, "P2": 0}}}, True),
             ({"CVars": {"gTapJumpDisabled": {"P1": 1}}}, False), ({"CVars": {"gCasualRules": {"AutoZCancel": 0}}}, True),
             ({"CVars": {"gCasualRules": {"AutoZCancel": 1}}}, False), ({"CVars": {"gCasualRules": {"FailedZCancelFlash": True}}}, False),
             ({"CVars": {"gUnrelated": {"X": 1}}}, True), ({"a": [{"AutoZCancel": 2}]}, False)]
    for i, (doc, ok) in enumerate(cases):
        p = t / f"c{i}.json"
        p.write_text(json.dumps(doc), encoding="utf-8")
        check((not ses.controller_cvar_problems(p)) == ok, f"case {i} {doc}: {ses.controller_cvar_problems(p)}")
    live = REPO_ROOT / "build-us" / "Release" / "BattleShip.cfg.json"
    if live.is_file():
        check(ses.controller_cvar_problems(live) == [], "the live configuration has no controller-rule CVar set")
    shutil.rmtree(t, ignore_errors=True)
    return {"cases": len(cases)}


def unit_provenance_guard() -> Dict[str, Any]:
    mw.ProvenanceGuard.install()
    mw.ProvenanceGuard.violations.clear()
    t = tmpdir("m8pg_")
    safe = t / "ok.txt"
    safe.write_text("x", encoding="utf-8")
    safe.read_text(encoding="utf-8")
    check(mw.ProvenanceGuard.violations == [], "an ordinary file is not a violation")
    bad = t / "rl" / "fixtures"
    bad.mkdir(parents=True)
    (bad / "f.txt").write_text("x", encoding="utf-8")
    (bad / "f.txt").read_text(encoding="utf-8")
    check(any("rl/fixtures" in v for v in mw.ProvenanceGuard.violations), "an open under rl/fixtures is recorded")
    mw.ProvenanceGuard.violations.clear()
    for frag, name in (("tas_input_2", "mario_743.btti"), ("g", "x.btti")):
        d = t / frag
        d.mkdir(exist_ok=True)
        (d / name).write_text("x", encoding="utf-8")
        (d / name).read_text(encoding="utf-8")
    check(len(mw.ProvenanceGuard.violations) >= 2, "TAS paths and .btti files are recorded")
    mw.ProvenanceGuard.violations.clear()
    # the registered analyser and the stage geometry open none of them
    import m7n_crossing as xc

    xc.geometry()
    check(mw.ProvenanceGuard.violations == [], f"the registered analyser opened a forbidden path: {mw.ProvenanceGuard.violations}")
    shutil.rmtree(t, ignore_errors=True)
    return {"fragments": len(mw.FORBIDDEN_FRAGMENTS)}


def unit_clock_and_caps() -> Dict[str, Any]:
    import m8_rd_run as mrun

    now = [0.0]
    cfg = small_cfg(tmpdir("m8c_"), global_cap_s=100.0, wall_caps_s={"p1": 10.0, "T": 50.0, "C": 40.0, "verify": 30.0})
    env = mrun.RunEnv(worker_spec=lambda r, c: {}, replay=lambda *a: {}, analyse=stub.analyse, p1_inputs=lambda: [], pins={},
                      now=lambda: now[0], private_mb=lambda: 100.0)
    clk = mrun.Clock(env, cfg)
    clk.begin("p1")
    now[0] = 9.9
    clk.check()
    now[0] = 10.1
    raises(mrun.CapStop, clk.check, "the P1 wall cap")
    clk.begin("T")
    now[0] = 59.9
    clk.check()
    now[0] = 60.2
    e = raises(mrun.CapStop, clk.check, "the arm wall cap")
    check(str(e).startswith("wall cap of phase T"), "the arm wall cap message")
    now[0] = 100.5
    e = raises(mrun.CapStop, clk.global_check, "the session hard cap")
    check("session hard cap" in str(e), "the 60-minute session cap is a distinct stop")
    env2 = mrun.RunEnv(worker_spec=lambda r, c: {}, replay=lambda *a: {}, analyse=stub.analyse, p1_inputs=lambda: [], pins={},
                       now=lambda: 0.0, private_mb=lambda: 5000.0)
    clk2 = mrun.Clock(env2, cfg)
    clk2._n = 63
    raises(mrun.CapStop, clk2.global_check, "main-process private memory over its cap")
    class B:
        breach = "memory cap: x"
    env3 = mrun.RunEnv(worker_spec=lambda r, c: {}, replay=lambda *a: {}, analyse=stub.analyse, p1_inputs=lambda: [], pins={},
                       now=lambda: 0.0, sampler=B())
    raises(mrun.CapStop, mrun.Clock(env3, cfg).global_check, "a tree-sampler breach")
    c = mrun.RunConfig(root=Path("x"))
    check(c.arm_tick_cap == 3_000_000 and c.min_arm_ticks == 1_500_000 and c.global_cap_s == 3600.0
          and dict(c.wall_caps_s) == {"p1": 180.0, "T": 1560.0, "C": 1440.0, "verify": 420.0}
          and c.replay_tick_cap == 400_000 and c.p1_tick_cap == 10_000 and c.n_workers == 5 and c.max_battleship_processes == 10
          and c.lifecycle_failure_limit == 3 and c.checkpoint_every_s == 300.0 and c.identity_k == 16 and c.verify_threads == 3
          and c.burst_words == 120 and c.horizon == 3600 and dict(c.memory_caps_mb) == {
              "main_private": 3072, "tree_private": 9216, "tree_working_set": 4096, "system_available_min": 1024,
              "system_commit_free_min": 2048}, "the registered caps (proposal 11.4 as amended)")
    check(c.arm_cap("T") == 3_000_000 and c.arm_cap("C") == 3_000_000, "production arm caps")
    return {}


def unit_approval_isolated() -> Dict[str, Any]:
    import m8_rd_session as ses

    want = ses.identity()
    t = tmpdir("m8ap_")
    p = t / "approval.json"
    ok, why = ses.approval_status(p, want)
    check(not ok and "no approval record" in why, "no record: refused")
    good = dict(want, approval="APPROVED by the test", revision=1)
    p.write_text(json.dumps(good), encoding="utf-8")
    check(ses.approval_status(p, want) == (True, "approved"), "a matching record is accepted")
    p.write_text(json.dumps(dict(good, approval="PENDING")), encoding="utf-8")
    check(not ses.approval_status(p, want)[0], "PENDING is refused")
    n = 0
    alter = {
        "rule_sha256": "0" * 64, "executable_sha256": "0" * 64, "scope": "other", "archive_id": "x", "workers": 4, "burst_words": 121,
        "horizon": 3599, "flags": {"explore": {}, "verify": {}}, "contracts": dict(want["contracts"], m8_rd_cell_v1="0" * 64),
        "key_strings": {"cell": "x"}, "runtime_files": {"BattleShip.o2r": "0" * 64}, "p1": {}, "readiness": {"min_available_mb": 1},
        "caps": dict(want["caps"], arm_tick_cap=2_999_999), "amendment": {"record": "x"}, "proposal_sha256": "0" * 64,
        "git_head": "0" * 40, "session": "rdX", "gate": "x", "milestone": "M9", "rule": "other",
    }
    for k, v in alter.items():
        p.write_text(json.dumps(dict(good, **{k: v})), encoding="utf-8")
        check(not ses.approval_status(p, want)[0], f"an altered {k} was accepted")
        n += 1
    for k in list(want["caps"]):
        caps = dict(want["caps"])
        caps[k] = {"x": 1}
        p.write_text(json.dumps(dict(good, caps=caps)), encoding="utf-8")
        check(not ses.approval_status(p, want)[0], f"an altered cap {k} was accepted")
        n += 1
    for f in list(want["code"]):
        code = dict(want["code"])
        code[f] = "0" * 64
        p.write_text(json.dumps(dict(good, code=code)), encoding="utf-8")
        check(not ses.approval_status(p, want)[0], f"an altered code hash for {f} was accepted")
        n += 1
    p.write_text(json.dumps(dict(good, d_records={"folders": ["2026-09-28"], "digest": "0" * 64})), encoding="utf-8")
    check(not ses.approval_status(p, want)[0], "an altered D: records digest")
    p.write_text(json.dumps({k: v for k, v in good.items() if k != "d_records"}), encoding="utf-8")
    check(not ses.approval_status(p, want)[0], "a record without the D: records")
    p.write_text("{not json", encoding="utf-8")
    raises(ValueError, lambda: ses.approval_status(p, want), "an unreadable record raises")
    check(not (t / "approval.json").is_dir() and ses.APPROVAL != p, "the repository path is untouched by the tests")
    # the snapshot entry: required by the preflight once an approval exists
    ok, why = ses.snapshot_status(dict(good, source_snapshot={"dest": str(t / "nosnap")}))
    check(not ok and "no snapshot.json" in why, "a missing source snapshot is refused")
    (t / "snap").mkdir()
    (t / "snap" / "snapshot.json").write_text(json.dumps({"result": "PASS"}), encoding="utf-8")
    h = mw.sha256_file(t / "snap" / "snapshot.json")
    check(ses.snapshot_status({"source_snapshot": {"dest": str(t / "snap"), "snapshot_json_sha256": h}})[0], "a PASS snapshot with its hash")
    check(not ses.snapshot_status({"source_snapshot": {"dest": str(t / "snap"), "snapshot_json_sha256": "0" * 64}})[0], "a wrong snapshot hash")
    (t / "snap" / "snapshot.json").write_text(json.dumps({"result": "FAIL"}), encoding="utf-8")
    check(not ses.snapshot_status({"source_snapshot": {"dest": str(t / "snap"), "snapshot_json_sha256": mw.sha256_file(
        t / "snap" / "snapshot.json")}})[0], "a snapshot whose record is not PASS")
    shutil.rmtree(t, ignore_errors=True)
    return {"altered_entries_refused": n}


def unit_readiness() -> Dict[str, Any]:
    import m8_rd_session as ses

    good_mem = lambda: {"available_mb": 8000.0, "commit_free_mb": 20000.0}      # noqa: E731
    good_disk = lambda p: 50.0                                                  # noqa: E731
    r = ses.readiness(good_mem, good_disk)
    check(r["ok"] and r["free_gib"] == {"C": 50.0, "D": 50.0}, f"a ready machine: {r['problems']}")
    check(not ses.readiness(lambda: {"available_mb": 4095.0, "commit_free_mb": 20000.0}, good_disk)["ok"], "available memory below the minimum")
    check(ses.readiness(lambda: {"available_mb": 4096.0, "commit_free_mb": 10240.0}, good_disk)["ok"], "at the minimums is ready")
    check(not ses.readiness(lambda: {"available_mb": 8000.0, "commit_free_mb": 10239.0}, good_disk)["ok"], "free commit below the minimum")
    check(not ses.readiness(lambda: None, good_disk)["ok"], "unknown memory is refused")
    check(not ses.readiness(good_mem, lambda p: 4.9)["ok"], "free disk below the minimum")
    def disk_c_low(p: Path) -> float:
        return 4.0 if str(p) == str(ses.REPO_ROOT) else 50.0
    r = ses.readiness(good_mem, disk_c_low)
    check(not r["ok"] and any("on C" in x for x in r["problems"]), "disk C alone")
    r = ses.readiness(good_mem, lambda p: (_ for _ in ()).throw(OSError("gone")))
    check(not r["ok"], "an unreadable disk is refused")
    check(ses.READINESS == {"min_available_mb": 4096, "min_commit_free_mb": 10240, "min_free_gib_c": 5.0, "min_free_gib_d": 5.0},
          "the registered readiness minimums")
    return {}


def unit_identity_and_pins() -> Dict[str, Any]:
    import m8_rd_session as ses

    a, b = ses.identity(), ses.identity()
    check(json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True), "the identity is stable")
    check(a["workers"] == 5 and a["burst_words"] == 120 and a["horizon"] == 3600 and a["caps"]["wall_caps_s"]["T"] == 1560.0
          and a["amendment"]["min_arm_ticks"] == 1_500_000 and a["amendment"]["arm_cap_ticks"] == 3_000_000, "registered numbers")
    check(set(a["contracts"]) == {"m8_rd_cell_v1", "m8_rd_select_v1", "m8_rd_explore_v1", "m8_rd_claims_v1", "track1_btt_s9_b8_v1",
                                  "btt_action_class_table_v2"}, "contract digests")
    for n, p in a["p1"].items():
        check(p["native_action_digest"] == p["recorded_digest"] == p["trace_action_digest"] and p["consumed_ticks_ok"], f"P1 trace {n}")
        check(p["trace_flags"].get("SSB64_RL_SPATIAL") == "1", f"P1 trace {n} was recorded with the spatial diagnostic")
    check({p["words"] for p in a["p1"].values()} == {3361, 2560}, "the two shortest pinned Track 1 artifacts")
    ins = ses.p1_inputs()
    check([len(i["words"]) for i in ins] == [3361, 2560] and all(len(i["expected_digests"]) == len(i["words"]) for i in ins), "P1 inputs")
    check(all(len(d) == 32 for i in ins for d in i["expected_digests"][:5]), "digests are 32 bytes")
    check(set(a["flags"]["verify"]) - set(a["flags"]["explore"]) == {"SSB64_RL_ENTITY", "SSB64_RL_TARGET_DIAG", "SSB64_RL_INPUT"},
          "verification replays add the entity, target and input diagnostics")
    check(a["flags"]["explore"] == {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1", "SSB64_RL_SPATIAL": "1"}, "exploration flags")
    check(sorted(a["runtime_files"]) == ["BattleShip.o2r", "f3d.o2r", "gamecontrollerdb.txt"], "pinned runtime files")
    for f in ses.CODE_FILES:
        if f.startswith("m8_rd_"):
            check(f"rl/{f}" in a["code"] or f in ("m8_rd_tests.py",), f"{f} is pinned")
    return {"code_files": len(a["code"])}


def unit_rule_module() -> Dict[str, Any]:
    check(mrule.self_test() == [], "the rule's self-test")
    d = mrule.rule_digest()
    check(d == mrule.rule_digest() and len(d) == 64, "the rule digest")
    check(mrule.MIN_ARM_TICKS == mclaims.MIN_ARM_TICKS == 1_500_000 and mclaims.ARM_TICK_CAP == 3_000_000, "the amendment's constants agree")
    check(mrule.LADDER == mclaims.LADDER, "one ladder")
    return {"rule_digest": d[:12]}


# -- static guards ----------------------------------------------------------------------------------------------------------------------


def unit_source_guard() -> Dict[str, Any]:
    """No M8-rd module reads fixtures, capture recordings, the TAS or any .btti file; none imports a learning framework or
    the random module (every draw is a keyed sha256 uniform)."""
    forbidden = ("rl/fixtures", "fixtures/m7g", "m7g/capture", "tas_input", "mario_743", ".btti", "btti_replay", "crossing_fixture",
                 "rl_crossing")
    bad_imports = {"random", "torch", "gymnasium", "stable_baselines3", "numpy", "pandas", "scipy", "sklearn"}
    hits: Dict[str, List[str]] = {}
    for name in NEW_MODULES:
        path = RL_DIR / f"{name}.py"
        raw_text = path.read_text(encoding="utf-8")
        text = raw_text.replace("\\", "/")
        lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("FORBIDDEN_FRAGMENTS")]
        body = "\n".join(lines)
        found = [f for f in forbidden if f in body]
        tree = ast.parse(raw_text)
        imports = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                imports |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module:
                imports.add(n.module.split(".")[0])
        found += [f"import {i}" for i in sorted(imports & bad_imports)]
        if found:
            hits[name] = found
    check(not hits, f"forbidden vocabulary or imports in M8-rd modules: {hits}")
    return {"modules": len(NEW_MODULES), "fragments": len(forbidden)}


def unit_import_isolation() -> Dict[str, Any]:
    code = ("import sys; sys.path.insert(0, r'%s'); " % RL_DIR +
            "import m8_rd_cells, m8_rd_explore, m8_rd_archive, m8_rd_claims, m8_rd_rule, m8_rd_worker, m8_rd_run, m8_rd_finish, "
            "m8_rd_session, m8_rd_report, m8_rd_stub; "
            "print(sorted(m for m in ('torch', 'numpy', 'gymnasium', 'stable_baselines3', 'm7u3_gate', 'm7f_trace', 'm7n_crossing', "
            "'m7g_fixture', 'btt_learning', 'm7h_curriculum') if m in sys.modules))")
    r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=120)
    check(r.stdout.strip() == "[]", f"the light modules imported heavy ones: {r.stdout.strip()} {r.stderr[-300:]}")
    return {}


def unit_tracked_files_unchanged() -> Dict[str, Any]:
    import m8_rd_session as ses

    check(ses.tracked_changes() == [], f"tracked files differ from HEAD: {ses.tracked_changes()[:5]}")
    check(ses.untracked_not_new() == [], f"git status shows more than new files: {ses.untracked_not_new()[:5]}")
    prop = REPO_ROOT / "docs" / "rl_m8_rd_proposal_2026-10-01.md"
    r = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", str(prop)], cwd=REPO_ROOT)
    check(r.returncode == 0, "the proposal differs from HEAD")
    return {}


def unit_snapshot_tool() -> Dict[str, Any]:
    t = tmpdir("m8sn_")
    dest = t / "snap"
    r = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_rd_snapshot.py"), "snapshot", "--dest", str(dest)], capture_output=True,
                       text=True, timeout=600)
    check(r.returncode == 0, f"snapshot: {r.stdout[-400:]} {r.stderr[-400:]}")
    rec = json.loads((dest / "snapshot.json").read_text(encoding="utf-8"))
    check(rec["result"] == "PASS" and rec["n_files"] > 20 and not rec["problems"] and not rec["identity_code_mismatch"],
          f"snapshot record: {rec['result']} {rec['problems']} {rec['identity_code_mismatch']}")
    names = {f["path"] for f in rec["files"]}
    check({"rl/m8_rd_cells.py", "rl/m8_rd_run.py", "docs/rl_m8_rd_proposal_2026-10-01.md"} <= names, "the snapshot holds the M8 code and the proposal")
    r = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_rd_snapshot.py"), "verify", "--dest", str(dest)], capture_output=True,
                       text=True, timeout=600)
    check(r.returncode == 0, f"verify: {r.stdout[-300:]}")
    r = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_rd_snapshot.py"), "snapshot", "--dest", str(dest)], capture_output=True,
                       text=True, timeout=60)
    check(r.returncode == 2, "an existing destination is never overwritten")
    victim = dest / "files" / "rl" / "m8_rd_cells.py"
    victim.write_bytes(victim.read_bytes() + b"\n#tampered\n")
    r = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_rd_snapshot.py"), "verify", "--dest", str(dest)], capture_output=True,
                       text=True, timeout=600)
    check(r.returncode == 1 and "m8_rd_cells.py" in r.stdout, "a tampered copy fails the verification")
    ps = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_rd_snapshot.py"), "powershell", "--dest", str(dest)], capture_output=True,
                        text=True, timeout=60)
    check("Get-FileHash" in ps.stdout, "the independent re-hash script is generated")
    shutil.rmtree(t, ignore_errors=True)
    return {"files": rec["n_files"]}


def unit_report_readings() -> Dict[str, Any]:
    import m8_rd_report as rpt

    out, sess, root = run_small("base")
    rep = rpt.build_report(root, "rd1")
    t = rep["arms"]["T"]["full"]
    check(t["cells"] == len(sess.archive.cells) and t["masks"] == sess.archive.stats()["masks"], "T coverage")
    check(set(t) >= {"cells", "masks", "bins", "resource", "cells_by_level", "first_reach_by_level", "best_y_with_x_le_-1200",
                     "l1_contact_cells", "wall_top_cells", "left_of_wall_cells", "launch_capable_cells",
                     "launch_capable_cells_x_le_600"}, "the reported readings are present")
    check(rep["arms"]["T"]["velocity_reversals"]["velocity_reversals"] == sess.archive.diag["velocity_reversals"], "velocity reversals")
    check("prefix_share" in rep["return_overhead"], "return overhead")
    proj = rpt.reverify_projection(root)
    check(proj["ok"] and proj["cells"] == len(sess.archive.cells) and proj["projected_native_ticks"] > 0, f"reverify projection {proj}")
    jobs = rpt.reverify_plan(sess.archive)
    check(sum(len(j["checks"]) for j in jobs) + 1 == len(sess.archive.cells), "the re-verification plan covers every cell")
    return {"projected_ticks": proj["projected_native_ticks"]}


def unit_verify_run_detects_tampering() -> Dict[str, Any]:
    import m8_rd_report as rpt

    out, sess, root = run_small("base")
    t = tmpdir("m8vr_")
    shutil.copytree(root, t / "root")
    base = rpt.verify_run(t / "root", "rd1")
    check(base["ok"], f"a copy verifies: {base['problems']}")
    rp = t / "root" / "sessions" / "rd1" / "rule.json"
    d = json.loads(rp.read_text(encoding="utf-8"))
    d["outcome"] = "PASS" if d["outcome"] != "PASS" else "NULL"
    rp.write_text(json.dumps(d), encoding="utf-8")
    check(not rpt.verify_run(t / "root", "rd1")["ok"], "an altered rule record is detected")
    rp.write_text(json.dumps(json.loads((root / "sessions" / "rd1" / "rule.json").read_text(encoding="utf-8"))), encoding="utf-8")
    act = sorted((t / "root" / "routes").glob("*"))[0] / "actions.jsonl"
    act.write_text(act.read_text(encoding="utf-8").replace('"stick_x":0', '"stick_x":1', 1), encoding="utf-8")
    check(not rpt.verify_run(t / "root", "rd1")["ok"], "an altered route is detected")
    shutil.rmtree(t, ignore_errors=True)
    return {}


# -- the REAL lifecycle code against a fake game process ---------------------------------------------------------------------------------


def fake_game_setup(prefix: str = "m8fg_") -> Dict[str, Any]:
    """A temporary 'executable directory' whose BattleShip.cmd starts rl/m8_rd_fakegame.py (the M1d protocol over the stub
    world), plus a frozen runtime that differs from the 'live' configuration beside the executable."""
    t = tmpdir(prefix)
    exe_dir = t / "exe"
    exe_dir.mkdir()
    for n in ("f3d.o2r", "BattleShip.o2r", "gamecontrollerdb.txt"):
        (exe_dir / n).write_bytes(b"fake")
    (exe_dir / "BattleShip.cfg.json").write_text(json.dumps({"CVars": {"live": "LIVE-CONFIG"}}), encoding="utf-8")
    (exe_dir / "imgui.ini").write_text("[live]\n", encoding="utf-8")
    cmd = exe_dir / "BattleShip.cmd"
    cmd.write_text(f'@"{sys.executable}" -B "{RL_DIR / "m8_rd_fakegame.py"}"\r\n', encoding="utf-8")
    frozen = t / "frozen"
    frozen.mkdir()
    (frozen / "BattleShip.cfg.json").write_text(json.dumps({"CVars": {"frozen": "FROZEN-CONFIG"}}), encoding="utf-8")
    (frozen / "imgui.ini").write_text("[frozen]\n", encoding="utf-8")
    hashes = {n: mw.sha256_file(frozen / n) for n in mw.FROZEN_FILES}
    return {"t": t, "exe_dir": exe_dir, "cmd": cmd, "frozen": frozen, "hashes": hashes, "log": t / "fake.log",
            "live_hash": mw.sha256_file(exe_dir / "BattleShip.cfg.json")}


def fake_flags(fg: Mapping[str, Any], world: str, **extra: str) -> Dict[str, str]:
    f = {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1", "SSB64_RL_SPATIAL": "1", "FAKEGAME_WORLD": world,
         "FAKEGAME_LOG": str(fg["log"]), "FAKEGAME_BOOT_S": "0.2"}
    f.update(extra)
    return f


def fake_spec(fg: Mapping[str, Any], flags: Mapping[str, str], rank: int = 20, **extra: Any) -> Dict[str, Any]:
    spec = {"rank": rank, "root": str(fg["t"] / f"w{rank}"), "executable": str(fg["cmd"]), "flags": dict(flags),
            "frozen_dir": str(fg["frozen"]), "frozen_sha256": dict(fg["hashes"]), "port_base": 30000, "port_size": 250,
            "timeouts": {"startup": 30.0, "ready": 30.0, "request": 15.0, "exit": 15.0}, "failure_dir": str(fg["t"] / "fail")}
    spec.update(extra)
    return spec


def wait_dead(pids: Sequence[int], seconds: float = 20.0) -> List[int]:
    from m7_runtime import pid_alive

    deadline = time.monotonic() + seconds
    alive = [p for p in pids if pid_alive(p)]
    while alive and time.monotonic() < deadline:
        time.sleep(0.3)
        alive = [p for p in pids if pid_alive(p)]
    return alive


def fake_log(fg: Mapping[str, Any]) -> List[Dict[str, Any]]:
    p = Path(fg["log"])
    rows = []
    for x in (p.read_text(encoding="utf-8").splitlines() if p.is_file() else []):
        try:
            rows.append(json.loads(x))
        except ValueError:                                # a process that is still writing its line
            pass
    return rows


def unit_real_backend_with_fake_game() -> Dict[str, Any]:
    """RealBackend / RealProc / the standby lifecycle / the frozen configuration / finish() on a clear / cold fallback /
    lifecycle failure / readiness contract, all through real processes (a fake game behind the real M1d client)."""
    fg = fake_game_setup()
    out: Dict[str, Any] = {}
    # 1. the easy world: standby promotion, a keyed burst, a return, tamper refusal, frozen config, cleanup
    backend = mw.RealBackend(fake_spec(fg, fake_flags(fg, "easy")))
    ctx = mw.JobContext(backend, None, classifier(), 20, fg["t"] / "fail")
    pin = pin_from(ctx)
    check(pin["digest"] and len(pin["obs"]) == 17, "tick-0 record through the real client")
    a = march.Archive("rb")
    a.init_cell0(tuple(pin["key"]), pin["obs"], bytes.fromhex(pin["digest"]), bytes.fromhex(pin["chain"]))
    r0 = mw.run_iterate(ctx, iterate_job(a, a.cells[0], pin, it=0))
    check(r0["ok"] and r0["mode"] == "standby_promoted", f"a burst through a promoted standby: {r0.get('mode')} {r0.get('kind')} {r0.get('message')}")
    # the same keyed burst through the stub in process: identical words, keys, record digests and chains
    sctx = job_ctx("easy")
    spin = pin_from(sctx)
    rs = mw.run_iterate(sctx, iterate_job(a, a.cells[0], spin, it=0))
    check(r0["words"] == rs["words"] and [x[:2] for x in r0["reaches"]] == [x[:2] for x in rs["reaches"]]
          and [x[3:5] for x in r0["reaches"]] == [x[3:5] for x in rs["reaches"]],
          "a real-lifecycle burst equals the in-process burst word for word, record for record")
    a.ingest(dict(r0, cum_before=0, session="t"))
    c = [x for x in a.cells if x.id and x.L >= 12][-1]
    ret = mw.run_iterate(ctx, iterate_job(a, c, pin, it=1, burst_words=0))
    check(ret["ok"] and ret["prefix"]["end_equal"] and ret["prefix"]["chain_equal"], f"a return through real processes: {ret.get('kind')}")
    bad = dict(iterate_job(a, c, pin, it=2, burst_words=0), chain=bytes(32))
    r = mw.run_job(ctx, bad)
    check(not r["ok"] and r["mismatch"] == "prefix_end" and Path(r["detail"]["preserved"]).is_file(), "a tampered chain is refused; the replies are preserved")
    # cold fallback: asking for a process while the standby is still booting, with no patience
    p1 = backend.acquire(wait_timeout=0.0)
    check(p1.mode == "cold_fallback", f"no patience -> a cold launch: {p1.mode}")
    p1.close()
    log = fake_log(fg)
    check(len(log) >= 5 and all(x["cfg_sha256"] == fg["hashes"]["BattleShip.cfg.json"] for x in log),
          "every launched process read the FROZEN configuration")
    check(all(x["cfg_sha256"] != fg["live_hash"] for x in log), "no process read the live configuration")
    check(all(x["flags"].get("SSB64_RL_SPATIAL") == "1" and x["flags"].get("SSB64_RAPHNET_DISABLE") == "1" for x in log), "flags reached the game")
    pids = [x["pid"] for x in log]
    rep = backend.report()
    check(rep["counts"]["promoted"] >= 3 and rep["counts"]["cold_fallback"] == 1, f"standby accounting {rep['counts']}")
    backend.close()
    check(wait_dead(pids) == [], f"fake game processes survived the close: {wait_dead(pids, 0)}")
    check(not [d for d in (fg["t"] / "w20" / "rt").glob("*")], "runtime directories are removed after use")
    check(len(list((fg["t"] / "w20" / "ep").glob("*"))) == 1, "the only episode directory left is the failed job's (its native log is evidence)")
    out["easy"] = {"launches": len(log), "counts": rep["counts"]}
    # 2. a clear is finished natively (both clocks) and the result JSON is read
    fg2 = fake_game_setup("m8fg2_")
    backend = mw.RealBackend(fake_spec(fg2, fake_flags(fg2, "trivial"), rank=21))
    ctx = mw.JobContext(backend, None, classifier(), 21, fg2["t"] / "fail")
    pin2 = pin_from(ctx)
    rc = mw.run_control(ctx, {"kind": "control", "episode": 0, "pin": pin2, "allowance": 3600})
    check(rc["ok"] and rc["end_reason"] == "clear" and rc["result_json"]["outcome"] == "clear" and rc["exit_code"] == 0
          and rc["result_json"]["completion_input_tick"] == rc["ticks"], f"a native clear through the real client: {rc.get('kind')} {rc.get('message')}")
    backend.close()
    out["clear"] = {"ticks": rc["ticks"]}
    # 3. a process that dies mid-run is a lifecycle failure; the worker survives and the next job works
    fg3 = fake_game_setup("m8fg3_")
    backend = mw.RealBackend(fake_spec(fg3, fake_flags(fg3, "easy", FAKEGAME_DIE_AT_STEP="5"), rank=22))
    ctx = mw.JobContext(backend, None, classifier(), 22, fg3["t"] / "fail")
    r = mw.run_job(ctx, {"kind": "control", "episode": 0, "pin": None, "allowance": 100})
    check(not r["ok"] and r["kind"] in ("lifecycle", "mismatch"), f"a dying process: {r}")
    if r["kind"] == "mismatch":                                        # pin=None -> the tick-0 record is simply pinned elsewhere
        raise Failure(f"unexpected mismatch {r}")
    check(r["outcome"] in ("premature_exit", "transport_failure", "episode_timeout"), f"the failure is classified: {r['outcome']}")
    backend.close()
    out["death"] = r["outcome"]
    # 4. the readiness contract: a game whose status disagrees with the expected flags never becomes a process
    fg4 = fake_game_setup("m8fg4_")
    backend = mw.RealBackend(fake_spec(fg4, fake_flags(fg4, "easy", FAKEGAME_LIE_SPATIAL="1"), rank=23,
                                       timeouts={"startup": 20.0, "ready": 20.0, "request": 10.0, "exit": 10.0}))
    ctx = mw.JobContext(backend, None, classifier(), 23, fg4["t"] / "fail")
    r = mw.run_job(ctx, {"kind": "tick0", "pin": None})
    check(not r["ok"] and r["kind"] == "lifecycle" and r["outcome"] == "startup_failure", f"a game that lies about its flags is refused: {r}")
    backend.close()
    out["readiness"] = r["outcome"]
    # 5. pin drift: a frozen file changed after S0 is refused at the next launch
    fg5 = fake_game_setup("m8fg5_")
    backend = mw.RealBackend(fake_spec(fg5, fake_flags(fg5, "easy"), rank=24))
    ctx = mw.JobContext(backend, None, classifier(), 24, fg5["t"] / "fail")
    pin5 = pin_from(ctx)                                                 # the first process is the booted standby
    (fg5["frozen"] / "BattleShip.cfg.json").write_text("tampered", encoding="utf-8")
    r = mw.run_job(ctx, {"kind": "tick0", "pin": pin5})                  # promoted from the standby launched BEFORE the change
    r2 = mw.run_job(ctx, {"kind": "tick0", "pin": pin5})                 # the standby launched AFTER the change failed its install
    check(r["ok"], "the standby launched before the change is still a valid process")
    check(not r2["ok"] and (r2.get("mismatch") == "pin_drift" or r2.get("kind") in ("mismatch", "error", "lifecycle")),
          f"a launch after the frozen file changed must not succeed: {r2}")
    check(r2.get("mismatch") == "pin_drift", f"pin drift is an integrity failure: {r2}")
    backend.close()
    out["pin_drift"] = r2.get("mismatch")
    # 6. the executable and the runtime files are re-hashed before every launch
    fg6 = fake_game_setup("m8fg6_")
    exe_h = mw.sha256_file(fg6["cmd"])
    rt_h = {n: mw.sha256_file(fg6["exe_dir"] / n) for n in ("BattleShip.o2r", "f3d.o2r", "gamecontrollerdb.txt")}
    backend = mw.RealBackend(fake_spec(fg6, fake_flags(fg6, "easy"), rank=25, exe_sha256=exe_h, runtime_sha256=rt_h))
    ctx = mw.JobContext(backend, None, classifier(), 25, fg6["t"] / "fail")
    pin6 = pin_from(ctx)
    r = mw.run_job(ctx, {"kind": "tick0", "pin": pin6})
    check(r["ok"], "matching executable and runtime pins launch normally")
    (fg6["exe_dir"] / "f3d.o2r").write_bytes(b"changed asset")                # an asset changes mid-session
    r = mw.run_job(ctx, {"kind": "tick0", "pin": pin6})                         # (the standby booted before the change is promoted)
    r = mw.run_job(ctx, {"kind": "tick0", "pin": pin6})
    check(not r["ok"] and r.get("mismatch") == "pin_drift", f"a changed runtime file is a pin drift: {r}")
    backend.close()
    fg7 = fake_game_setup("m8fg7_")
    backend = mw.RealBackend(fake_spec(fg7, fake_flags(fg7, "easy"), rank=26, exe_sha256="0" * 64))
    ctx = mw.JobContext(backend, None, classifier(), 26, fg7["t"] / "fail")
    r = mw.run_job(ctx, {"kind": "tick0", "pin": None})
    check(not r["ok"] and r.get("mismatch") == "pin_drift", f"a different executable is a pin drift: {r}")
    backend.close()
    out["exe_pin"] = r.get("mismatch")
    for f in (fg, fg2, fg3, fg4, fg5, fg6, fg7):
        shutil.rmtree(f["t"], ignore_errors=True)
    return out


def unit_session_real_backend_fake_game() -> Dict[str, Any]:
    """The whole engine with the REAL backend (processes, standby, frozen config) and the REAL replay path (m7f_trace's
    stepping trace through the real client) against the fake game; verification, close and verify-run included."""
    import m8_rd_finish as fin
    import m8_rd_report as rpt
    import m8_rd_run as mrun
    import m8_rd_session as ses
    import m7_runtime

    fg = fake_game_setup("m8fgs_")
    root = fg["t"] / "run"
    cfg = small_cfg(root, n_workers=2, arm_tick_cap=2500, min_arm_ticks=1000, verify_threads=2, identity_k=4,
                    wall_caps_s={"p1": 120.0, "T": 150.0, "C": 150.0, "verify": 150.0}, global_cap_s=900.0)
    cfg.archive_dir.mkdir(parents=True)
    shutil.copytree(fg["frozen"], cfg.archive_dir / "runtime")
    fx = fake_flags(fg, "easy")
    fv = dict(fx, SSB64_RL_ENTITY="1", SSB64_RL_TARGET_DIAG="1", SSB64_RL_INPUT="1")
    orig = m7_runtime.prepare_worker_runtime
    try:
        env = ses.build_real_env(cfg, fg["hashes"], {"fake": True}, executable=fg["cmd"], flags_explore=fx, flags_verify=fv)
        env.analyse = stub.analyse                                       # the fake game has no target diagnostic
        env.p1_inputs = lambda: stub.p1_inputs("easy", (200, 150))
        env.log = lambda s: None
        sess = mrun.Session(cfg, env)
        res = fin.run_all(sess)
    finally:
        m7_runtime.prepare_worker_runtime = orig
    rule, close = res["rule"], res["close"]
    check(rule["outcome"] in ("PASS", "NULL", "INCONCLUSIVE") and not rule["invalid"] and not rule["incomplete"],
          f"a complete session through real processes: {rule['outcome']} {rule['invalid']} {rule['incomplete']}")
    check(sess.ledgers["T"].ticks == 2500 and sess.ledgers["C"].ticks == 2500, "budgets through real processes")
    check(close["audit"]["ok"], f"close audit {close['audit']}")
    log = fake_log(fg)
    frozen_h = fg["hashes"]["BattleShip.cfg.json"]
    check(len(log) > 20 and all(x["cfg_sha256"] == frozen_h for x in log), f"every process (exploration AND verification replays) read the frozen configuration ({len(log)})")
    verify_launches = [x for x in log if x["flags"].get("SSB64_RL_TARGET_DIAG") == "1"]
    check(verify_launches, "the verification replays ran with the four read-only diagnostics")
    vr = rpt.verify_run(root, "rd1")
    check(vr["ok"], f"verify-run: {vr['problems']}")
    check(wait_dead([x["pid"] for x in log], 30.0) == [], "no fake game process survived the session")
    modes = sess.arm_records["T"]["start_modes"]
    check(modes.get("standby_promoted", 0) > 0, f"standby promotions in arm T: {modes}")
    check(not list((root / "sessions" / "rd1" / "workers").rglob("g0*a*")), "every generation's runtime directory was removed")
    out = {"launches": len(log), "modes_T": modes, "outcome": rule["outcome"], "cells": len(sess.archive.cells)}
    shutil.rmtree(fg["t"], ignore_errors=True)
    return out


def unit_terminal_cells_are_returnable() -> Dict[str, Any]:
    """The close identity replays include terminal cells: the last tick of such a prefix is the reply of a native failure (or a
    clear). That end is expected there and a mismatch anywhere else."""
    a, pin, ctx, cum = drive_archive("easy", 90, "term")
    terms = [c for c in a.cells if c.terminal]
    check(len(terms) >= 2, f"no terminal cell in 90 iterations of the easy world ({len(terms)})")
    for c in terms[:3]:
        job = dict(iterate_job(a, c, pin, it=900 + c.id, burst_words=0), terminal=True)
        r = mw.run_job(ctx, job)
        check(r["ok"] and r["prefix"]["terminal"] and r["prefix"]["end_equal"] and r["prefix"]["chain_equal"] and r["ticks"] == c.L,
              f"a terminal cell is returned and verified at its last tick: {r}")
        r = mw.run_job(ctx, dict(job, terminal=False))
        check(not r["ok"] and r["mismatch"] == "prefix_ended", "an unexpected end inside a non-terminal prefix is refused")
    nonterm = [c for c in a.cells if not c.terminal and c.id and c.L >= 5][0]
    r = mw.run_job(ctx, dict(iterate_job(a, nonterm, pin, it=990, burst_words=0), terminal=True))
    check(not r["ok"] and r["mismatch"] == "terminal_expected", "a cell flagged terminal whose replay does not end is refused")
    # a clear is a terminal cell too: the process is finished natively (exit code, result JSON)
    a2, pin2, ctx2, _cum = drive_archive("trivial", 3, "term2")
    cl = [c for c in a2.cells if c.terminal]
    check(cl, "the trivial world clears at tick 1")
    r = mw.run_job(ctx2, dict(iterate_job(a2, cl[0], pin2, it=950, burst_words=0), terminal=True))
    check(r["ok"] and r["prefix"]["terminal"] and r["exit_code"] == 0 and r["result_json"]["outcome"] == "clear", f"a clear cell: {r}")
    # a terminal cell is never selected: it is not eligible
    check(all(not a.eligible(c) for c in terms), "terminal cells are not eligible")
    return {"terminal_cells": len(terms)}


# -- the independent review's findings: each fix has a test ------------------------------------------------------------------------------


def unit_windows_retries() -> Dict[str, Any]:
    """A file briefly held by a scanner (PermissionError on os.replace / rmtree) is retried, not fatal."""
    import m8_rd_run as mrun

    real = os.replace
    calls = {"n": 0}

    def flaky(src: Any, dst: Any) -> None:
        calls["n"] += 1
        if calls["n"] <= 3:
            raise PermissionError("held by another process")
        real(src, dst)

    t = tmpdir("m8rt_")
    os.replace = flaky
    try:
        mrun.write_json(t / "a.json", {"x": 1})
    finally:
        os.replace = real
    check(json.loads((t / "a.json").read_text(encoding="utf-8")) == {"x": 1} and calls["n"] == 4, "write_json retried the replace")
    os.replace = lambda s, d: (_ for _ in ()).throw(PermissionError("always"))
    try:
        raises(PermissionError, lambda: march.replace_retry(t / "a.json", t / "b.json", timeout=0.3), "a permanent lock must raise after the timeout")
    finally:
        os.replace = real
    # a checkpoint survives two locked replaces
    a, pin, ctx, cum = drive_archive("easy", 6, "rtry")
    calls["n"] = 0
    os.replace = flaky
    try:
        march.save_checkpoint(t / "archive", a, {"checkpoint_seq": 1})
    finally:
        os.replace = real
    d, meta, _rep = march.load_latest_verified(t / "archive")
    check(d is not None and meta["checkpoint_seq"] == 1 and calls["n"] > 3, "the checkpoint was written after the locks cleared")
    shutil.rmtree(t, ignore_errors=True)
    return {"replace_calls": calls["n"]}


def unit_claims_batch_fill() -> Dict[str, Any]:
    led = mclaims.ArmLedger("T")
    for k in range(6):
        cb = led.commit(100)
        led.register(cum_before=cb, iteration=k, words=bytes(100), prefix_len=0, labels=labels(left_live=20), breaks=[],
                     end_reason="length", t_end=0)
    todo, info = mclaims.plan_replays(led, 10 ** 6, {}, batch=3)
    check([c["cid"] for c, _n in todo] == [0, 1, 2], f"crossing and left_target advance through the shared pool together: {[c['cid'] for c, _n in todo]}")
    done = {0: {"exact": True, "l0": False, "crossing": False, "left_target": False, "clear": False},
            1: {"exact": True, "l0": False, "crossing": False, "left_target": False, "clear": False},
            2: {"exact": True, "l0": False, "crossing": False, "left_target": False, "clear": False}}
    todo, info = mclaims.plan_replays(led, 10 ** 6, done, batch=3)
    check([c["cid"] for c, _n in todo] == [3, 4, 5] and info["remaining"]["crossing"] == 3, "the next batch continues in discovery order")
    return {}


def unit_finish_error_keeps_the_clear() -> Dict[str, Any]:
    ctx = job_ctx("trivial", inject={"finish_fail_job": 2})
    pin = pin_from(ctx)                                       # acquisition 1
    r = mw.run_control(ctx, {"kind": "control", "episode": 0, "pin": pin, "allowance": 3600})      # acquisition 2: finish() fails
    check(r["ok"] and r["end_reason"] == "clear" and r["labels"]["first"]["clear"] == r["ticks"] and r["result_json"] is None
          and r["finish_error"] and "exit_timeout" in r["finish_error"], f"a failed native exit must not lose the clear: {r.get('kind')}")
    cand_words = r["words"]
    tr = stub.replay_trace("trivial", cand_words, "x")
    check(tr["result"]["outcome"] == "clear", "the clear is still verifiable by its own replay")
    return {"ticks": r["ticks"]}


def unit_process_count_debounce() -> Dict[str, Any]:
    reads = {"n": 0}

    def once_over() -> Dict[str, Any]:
        reads["n"] += 1
        return {"battleship": 11 if reads["n"] == 1 else 10, "seq": reads["n"]}

    out, sess, _r = run_small("dbo", env_kw={"tree_snapshot": once_over}, inject={"slow_s": 0.02}, n_workers=2, arm_tick_cap=6000,
                              min_arm_ticks=1000, process_check_every_s=0.05)
    check(reads["n"] >= 3, f"the process count was sampled repeatedly ({reads['n']})")
    check(out["rule"]["outcome"] in ("PASS", "NULL", "INCONCLUSIVE") and not out["rule"]["incomplete"],
          f"one transient sample above the cap is not a stop: {out['rule']['outcome']} {out['rule']['incomplete']}")
    out, sess, _r = run_small("dbo2", env_kw={"tree_snapshot": lambda: {"battleship": 11}}, inject={"slow_s": 0.05}, n_workers=2,
                              arm_tick_cap=10 ** 6, min_arm_ticks=1000, process_check_every_s=0.05)
    check(out["rule"]["outcome"] == "INCOMPLETE" and any("11 BattleShip processes" in x for x in out["rule"]["incomplete"]),
          f"two distinct samples above the cap stop the session: {out['rule']['incomplete']}")
    return {}


def unit_unresponsive_worker_is_terminated() -> Dict[str, Any]:
    import m8_rd_run as mrun

    saved = mrun.WALL_CAP_GRACE_S
    mrun.WALL_CAP_GRACE_S = 0.3
    try:
        t0 = time.monotonic()
        out, sess, _r = run_small("hang", inject={"hang_job": 12, "slow_s": 0.03}, n_workers=2, arm_tick_cap=10 ** 7, min_arm_ticks=100,
                                  wall_caps_s={"p1": 90.0, "T": 1.5, "C": 1.5, "verify": 60.0}, global_cap_s=300.0,
                                  unresponsive_after_stop_s=2.0)
        wall = time.monotonic() - t0
    finally:
        mrun.WALL_CAP_GRACE_S = saved
    check(out["rule"]["outcome"] == "INCOMPLETE" and any("did not return" in x for x in out["rule"]["incomplete"]),
          f"an unresponsive worker after a stop: {out['rule']['outcome']} {out['rule']['incomplete']}")
    check(wall < 60.0, f"the session did not hang on the unresponsive worker ({wall:.0f} s)")
    return {"wall_s": round(wall, 1)}


def unit_real_backend_retry_and_evidence() -> Dict[str, Any]:
    import m7_runtime

    fg = fake_game_setup("m8fr_")
    orig = m7_runtime.prepare_worker_runtime
    calls = {"n": 0}

    def flaky(runtime_dir: Any, executable: Any) -> Any:
        calls["n"] += 1
        if calls["n"] <= 2:
            os.makedirs(runtime_dir, exist_ok=True)         # a half-made directory, as a failed copy would leave
            raise PermissionError("the live configuration is held by another program")
        return orig(runtime_dir, executable)

    m7_runtime.prepare_worker_runtime = flaky
    try:
        backend = mw.RealBackend(fake_spec(fg, fake_flags(fg, "easy"), rank=27))
        ctx = mw.JobContext(backend, None, classifier(), 27, fg["t"] / "fail")
        pin = pin_from(ctx)
        check(pin["digest"], "a sharing violation while preparing a runtime is retried")
        check(calls["n"] >= 3, f"prepare_worker_runtime was retried ({calls['n']})")
    finally:
        m7_runtime.prepare_worker_runtime = orig
    backend.close()
    # the native log of a failed process is kept as evidence; its runtime directory is removed
    fg2 = fake_game_setup("m8fr2_")
    backend = mw.RealBackend(fake_spec(fg2, fake_flags(fg2, "easy", FAKEGAME_DIE_AT_STEP="5"), rank=28))
    ctx = mw.JobContext(backend, None, classifier(), 28, fg2["t"] / "fail")
    r = mw.run_job(ctx, {"kind": "control", "episode": 0, "pin": None, "allowance": 100})
    check(not r["ok"] and r["kind"] == "lifecycle", f"the process died: {r}")
    logs = list((fg2["t"] / "w28" / "ep").glob("episode_*/battleship_stdout.log"))
    check(logs, "the failed process's native log is kept")
    backend.close()
    for f in (fg, fg2):
        shutil.rmtree(f["t"], ignore_errors=True)
    return {"prepare_calls": calls["n"], "kept_logs": len(logs)}


# -- cmd_run (S0, the sampler, the real environment, the whole engine) against the fake game ------------------------------------------------


def unit_cmd_run_with_fake_game() -> Dict[str, Any]:
    """The `run` command's own sequence in a temporary root with the fake game: S0 (the frozen runtime and the preserved
    runnable copy), the whole-process-tree sampler, build_real_env, run_all, the memory summary and the open record. Only the
    preflight (tested on its own) and the kill-on-close job are replaced."""
    import m8_rd_session as ses
    import m7_runtime

    fg = fake_game_setup("m8cr_")
    t = fg["t"]
    (fg["exe_dir"] / "config.yml").write_text("fake: true\n", encoding="utf-8")
    ident = ses.identity()
    approval = dict(ident, approval="APPROVED by the test", revision=1,
                    executable_sha256=mw.sha256_file(fg["cmd"]))
    (t / "approval.json").write_text(json.dumps(approval), encoding="utf-8")
    keys = ("M8_ROOT", "EXECUTABLE", "EXE_DIR", "APPROVAL", "FLAGS_EXPLORE", "FLAGS_VERIFY", "N_WORKERS", "p1_inputs", "preflight",
            "EXE_COPY_FILES", "EXE_COPY_DIRS", "RUNTIME_FILES", "build_real_env")
    saved = {k: getattr(ses, k) for k in keys}
    saved_job = m7_runtime.install_kill_on_close_job
    saved_prep = m7_runtime.prepare_worker_runtime
    try:
        ses.M8_ROOT = t / "runs_m8"
        ses.EXECUTABLE = fg["cmd"]
        ses.EXE_DIR = fg["exe_dir"]
        ses.APPROVAL = t / "approval.json"
        ses.FLAGS_EXPLORE = fake_flags(fg, "easy")
        ses.FLAGS_VERIFY = dict(ses.FLAGS_EXPLORE, SSB64_RL_ENTITY="1", SSB64_RL_TARGET_DIAG="1", SSB64_RL_INPUT="1")
        ses.N_WORKERS = 2
        ses.p1_inputs = lambda: stub.p1_inputs("easy", (200, 150))
        ses.preflight = lambda **k: {"ok": True, "problems": [], "executable_sha256": approval["executable_sha256"],
                                     "git_head": approval["git_head"]}
        ses.EXE_COPY_FILES = ("BattleShip.cmd", "BattleShip.o2r", "f3d.o2r", "gamecontrollerdb.txt", "config.yml")
        ses.EXE_COPY_DIRS = ()
        ses.RUNTIME_FILES = ("BattleShip.o2r", "f3d.o2r", "gamecontrollerdb.txt")
        m7_runtime.install_kill_on_close_job = lambda: None
        real_build = ses.build_real_env

        def build_with_stub_analyser(*a: Any, **k: Any) -> Any:
            env = real_build(*a, **k)
            env.analyse = stub.analyse                                   # the fake game has no target diagnostic
            return env

        ses.build_real_env = build_with_stub_analyser
        import m8_rd_finish as fin                                       # noqa: F401 (imported by cmd_run)
        approval["runtime_files"] = ses.runtime_pins()
        (t / "approval.json").write_text(json.dumps(approval), encoding="utf-8")
        rc = ses.cmd_run(overrides=dict(arm_tick_cap=2500, min_arm_ticks=1000, verify_threads=2, identity_k=4,
                                        wall_caps_s={"p1": 120.0, "T": 150.0, "C": 150.0, "verify": 150.0}, global_cap_s=900.0))
    finally:
        for k, v in saved.items():
            setattr(ses, k, v)
        m7_runtime.install_kill_on_close_job = saved_job
        m7_runtime.prepare_worker_runtime = saved_prep
    check(rc == 0, "cmd_run returned 0")
    root = t / "runs_m8"
    sd = root / "sessions" / "rd1"
    for f in ("open.json", "approval_copy.json", "p1.json", "rule.json", "close.json", "memory_summary.json", "memory_tree.jsonl", "state.json"):
        check((sd / f).is_file(), f"missing {f}")
    rule = json.loads((sd / "rule.json").read_text(encoding="utf-8"))
    check(rule["outcome"] in ("PASS", "NULL", "INCONCLUSIVE") and not rule["invalid"] and not rule["incomplete"],
          f"cmd_run's session: {rule['outcome']} {rule['invalid']} {rule['incomplete']}")
    rt = root / "archive" / "runtime"
    fr = json.loads((rt / "frozen_runtime.json").read_text(encoding="utf-8"))
    check(all((rt / "exe" / n).is_file() for n in ("BattleShip.cmd", "BattleShip.o2r", "f3d.o2r", "gamecontrollerdb.txt", "config.yml")),
          "the runnable copy of the pinned executable was preserved")
    check(fr["frozen_sha256"]["BattleShip.cfg.json"] == fg["live_hash"], "S0 froze the live configuration of that moment")
    op = json.loads((sd / "open.json").read_text(encoding="utf-8"))
    check(op["pins"]["approval_sha256"] == mw.sha256_file(t / "approval.json") and op["pins"]["executable_sha256"] == approval["executable_sha256"],
          "the open record pins the approval and the executable")
    check((sd / "approval_copy.json").read_bytes() == (t / "approval.json").read_bytes(), "a verbatim copy of the approval")
    ms = json.loads((sd / "memory_summary.json").read_text(encoding="utf-8"))
    check(ms["samples"] >= 1 and ms["breach"] is None and ms["peak"]["main_private_mb"] > 0, f"the tree sampler ran: {ms}")
    log = fake_log(fg)
    check(log and all(x["cfg_sha256"] == fr["frozen_sha256"]["BattleShip.cfg.json"] for x in log), "every process read the frozen configuration")
    check(wait_dead([x["pid"] for x in log], 30.0) == [], "no fake game process survived the run")
    # the command refuses when the preflight does
    ses.preflight = lambda **k: {"ok": False, "problems": ["x"]}
    try:
        check(ses.cmd_run() == 2, "a failing preflight refuses before anything is created")
    finally:
        ses.preflight = saved["preflight"]
    shutil.rmtree(t, ignore_errors=True)
    return {"launches": len(log), "outcome": rule["outcome"]}


# -- the registry and the CLI --------------------------------------------------------------------------------------------------------


TESTS: List[Tuple[str, Callable[[], Dict[str, Any]]]] = [
    ("cells_contract", unit_cells_contract), ("cells_on_recorded_replies", unit_cells_on_recorded_replies),
    ("cell_count_on_probe_prefix", unit_cell_count_on_probe_prefix),
    ("record_digests_across_flag_sets", unit_record_digests_across_flag_sets), ("explore", unit_explore),
    ("archive_ingest_rules", unit_archive_ingest_rules), ("archive_async_ingestion", unit_archive_async_ingestion),
    ("velocity_reversal_reading", unit_velocity_reversal_reading),
    ("selection", unit_selection), ("ledger_rebuild_and_audit", unit_ledger_rebuild_and_audit),
    ("checkpoint_atomicity", unit_checkpoint_atomicity), ("coverage_set", unit_coverage_set),
    ("claims_ledger_rules", unit_claims_ledger_rules), ("claims_roundtrip_on_stub", unit_claims_roundtrip_on_stub),
    ("real_analysis_on_recorded_trace", unit_real_analysis_on_recorded_trace), ("clear_facts", unit_clear_facts),
    ("worker_iterate_and_returns", unit_worker_iterate_and_returns),
    ("worker_horizon_fall_clear_control", unit_worker_horizon_fall_clear_control),
    ("worker_trace_and_reverify", unit_worker_trace_and_reverify),
    ("session_small_run", unit_session_small_run), ("session_budget_exact_cut", unit_session_budget_exact_cut),
    ("session_truncation_at_the_slower_arm", unit_session_truncation_at_the_slower_arm),
    ("session_outcomes_and_stops", unit_session_outcomes_and_stops), ("session_verification_cap", unit_session_verification_cap),
    ("frozen_runtime_and_preserve", unit_frozen_runtime_and_preserve), ("controller_cvars", unit_controller_cvars),
    ("provenance_guard", unit_provenance_guard), ("clock_and_caps", unit_clock_and_caps),
    ("approval_isolated", unit_approval_isolated), ("readiness", unit_readiness), ("identity_and_pins", unit_identity_and_pins),
    ("rule_module", unit_rule_module), ("source_guard", unit_source_guard), ("import_isolation", unit_import_isolation),
    ("tracked_files_unchanged", unit_tracked_files_unchanged), ("report_readings", unit_report_readings),
    ("verify_run_detects_tampering", unit_verify_run_detects_tampering),
    ("terminal_cells_are_returnable", unit_terminal_cells_are_returnable), ("windows_retries", unit_windows_retries),
    ("claims_batch_fill", unit_claims_batch_fill), ("finish_error_keeps_the_clear", unit_finish_error_keeps_the_clear),
    ("process_count_debounce", unit_process_count_debounce),
    ("unresponsive_worker_is_terminated", unit_unresponsive_worker_is_terminated),
    ("real_backend_with_fake_game", unit_real_backend_with_fake_game),
    ("real_backend_retry_and_evidence", unit_real_backend_retry_and_evidence),
    ("cmd_run_with_fake_game", unit_cmd_run_with_fake_game),
    ("session_real_backend_fake_game", unit_session_real_backend_fake_game), ("snapshot_tool", unit_snapshot_tool),
]


def run_unit(only: Optional[Sequence[str]] = None, out: Optional[Path] = None) -> int:
    passed, failed = 0, []
    results: Dict[str, Any] = {}
    t_all = time.perf_counter()
    for name, fn in TESTS:
        if only and name not in only:
            continue
        t0 = time.perf_counter()
        try:
            detail = fn()
            results[name] = {"ok": True, "s": round(time.perf_counter() - t0, 1), "detail": detail}
            passed += 1
            print(f"PASS {name} ({time.perf_counter() - t0:.1f} s)", flush=True)
        except Exception as exc:  # noqa: BLE001
            results[name] = {"ok": False, "s": round(time.perf_counter() - t0, 1), "error": f"{type(exc).__name__}: {exc}",
                             "trace": traceback.format_exc()[-2500:]}
            failed.append(name)
            print(f"FAIL {name}: {type(exc).__name__}: {exc}\n{traceback.format_exc()[-1800:]}", flush=True)
    total = passed + len(failed)
    if out is not None:
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "m8_rd_unit.json").write_text(json.dumps({"passed": passed, "total": total, "failed": failed,
                                                         "wall_s": round(time.perf_counter() - t_all, 1), "results": results},
                                                        indent=1, default=str) + "\n", encoding="utf-8")
    print(f"{passed} / {total} passed (unit); wall {time.perf_counter() - t_all:.0f} s")
    return 0 if not failed else 1


# -- the production-count synthetic end-to-end run ------------------------------------------------------------------------------------


def e2e(out: Path, small: bool = False, world: str = "hard") -> int:
    """run_all at the registered counts (three million ticks per arm, five workers, the registered caps) against the stub: every
    phase, the real archive, the real checkpoints, the whole-tree memory sampler, the truncation at the slower arm, the replay
    verification, the rule, the close audit and verify-run. The world is synthetic: the outcome says nothing about Mario."""
    import m8_rd_finish as fin
    import m8_rd_report as rpt
    import m8_rd_run as mrun
    import m8_rd_session as ses

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    root = out / "run"
    if root.exists():
        shutil.rmtree(root)
    kw: Dict[str, Any] = dict(checkpoint_every_s=30.0)
    if small:
        kw.update(arm_tick_cap=60000, min_arm_ticks=20000, arm_caps={"T": 60000, "C": 40000})
    else:
        kw.update(arm_caps={"T": 3_000_000, "C": 2_700_000})
    cfg = mrun.RunConfig(root=root, **kw)
    sampler = ses.make_sampler(out / "memory_tree.jsonl", cfg.memory_caps_mb)
    sampler.start()
    mw.ProvenanceGuard.install()
    logs: List[str] = []

    def log(s: str) -> None:
        line = f"[e2e {time.strftime('%H:%M:%S')}] {s}"
        logs.append(line)
        print(line, flush=True)

    def worker_spec(rank: int, c: Any) -> Dict[str, Any]:
        return {"rank": rank, "backend": "m8_rd_stub:StubBackend", "world": world, "failure_dir": str(c.session_dir / "failures")}

    def replay(cand: Mapping[str, Any], counted: int, label: str, slot: int) -> Dict[str, Any]:
        return stub.replay_trace(world, bytes(cand["words"][:counted]), label)

    env = mrun.RunEnv(worker_spec=worker_spec, replay=replay, analyse=stub.analyse, p1_inputs=lambda: stub.p1_inputs(world),
                      pins={"stub": True, "world": world}, tree_snapshot=lambda: getattr(sampler, "last", None), sampler=sampler,
                      log=log)
    try:
        import m7u_gate as g1

        env.private_mb = g1.private_mb
    except Exception:  # noqa: BLE001
        pass
    t0 = time.perf_counter()
    sess = mrun.Session(cfg, env)
    res = fin.run_all(sess)
    wall = time.perf_counter() - t0
    mem = sampler.stop()
    rule, close = res["rule"], res["close"]
    vr = rpt.verify_run(root, "rd1")
    report = rpt.build_report(root, "rd1")
    problems: List[str] = []
    T_ticks, C_ticks = sess.ledgers["T"].ticks, sess.ledgers["C"].ticks
    want_T, want_C = cfg.arm_cap("T"), cfg.arm_cap("C")
    if (T_ticks, C_ticks) != (want_T, want_C):
        problems.append(f"arm ticks {T_ticks} / {C_ticks} != {want_T} / {want_C}")
    if rule["outcome"] in ("INVALID", "INCOMPLETE"):
        problems.append(f"outcome {rule['outcome']}: {rule['invalid']} {rule['incomplete']}")
    if rule["extra"]["comparison_point"] != min(want_T, want_C):
        problems.append("comparison point is not the slower arm's count")
    if not vr["ok"]:
        problems.append(f"verify-run: {vr['problems']}")
    if not close.get("audit", {}).get("ok"):
        problems.append(f"close audit: {close.get('audit')}")
    if mem["breach"]:
        problems.append(f"memory sampler breach {mem['breach']}")
    ver = json.loads((root / "sessions" / "rd1" / "verification.json").read_text(encoding="utf-8"))
    replays = [json.loads(x) for x in (root / "sessions" / "rd1" / "verification" / "replays.jsonl").read_text(encoding="utf-8").splitlines()]
    point = rule["extra"]["comparison_point"]
    for r in replays:
        c = sess.ledgers[r["arm"]].candidates[r["cid"]]
        if c["cum_before"] + c["event_j"] > point or c["cum_before"] + r["counted"] > point:
            problems.append(f"a replayed candidate lies beyond the comparison point: {r['label']}")
    if sess.ledgers["T"].ticks > point:
        cut_t = sess.ledgers["T"].t_within(point)[0]
        if ver["arms"]["T"]["t"] != cut_t:
            problems.append(f"arm T verified t {ver['arms']['T']['t']} != its online t within T {cut_t}")
    summary = {"small": small, "world": world, "wall_s": round(wall, 1), "outcome": rule["outcome"], "m": [rule["m_T"], rule["m_C"]],
               "t": [rule["t_T"], rule["t_C"]], "ticks": {"T": T_ticks, "C": C_ticks}, "comparison_point": point,
               "cells_T": len(sess.archive.cells), "bursts_T": len(sess.archive.bursts), "cells_C": len(sess.coverage.keys),
               "candidates": {a: len(l.candidates) for a, l in sess.ledgers.items()},
               "arm_wall_s": {a: r["wall_s"] for a, r in sess.arm_records.items()},
               "ticks_per_s": {a: r["ticks_per_s"] for a, r in sess.arm_records.items()},
               "stops": {a: r["stop"] for a, r in sess.arm_records.items()},
               "phase_wall_s": sess.clock.to_json()["phase_wall_s"], "peak_main_private_mb": mem["peak"]["main_private_mb"],
               "peak_tree_private_mb": mem["peak"]["tree_private_mb"], "peak_tree_working_set_mb": mem["peak"]["tree_working_set_mb"],
               "peak_processes": mem["peak"]["processes"], "memory_samples": mem["samples"],
               "main_private_mb_clock": sess.clock.peak_mb, "verify_run": vr["ok"], "replays": len(replays),
               "replay_ticks": sess.ticks["replays"], "identity": ver["identity"],
               "audit": close.get("audit"), "archive_stats": sess.archive.stats(),
               "velocity_reversals": sess.vel_reversals["count"], "lifecycle_failures": sess.lifecycle_failures,
               "milestones": {a: {"m": ver["arms"][a]["milestone"], "t": ver["arms"][a]["t"]} for a in ("T", "C")},
               "problems": problems}
    (out / "e2e.json").write_text(json.dumps(summary, indent=1, default=str) + "\n", encoding="utf-8")
    (out / "e2e.log").write_text("\n".join(logs) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=1, default=str))
    print("E2E PASS" if not problems else f"E2E FAIL: {problems}")
    return 0 if not problems else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("unit", "e2e", "list"))
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--only", default=None)
    ap.add_argument("--small", action="store_true")
    ap.add_argument("--world", default="hard", choices=sorted(stub.WORLDS))
    a = ap.parse_args(argv)
    if a.cmd == "list":
        for name, _fn in TESTS:
            print(name)
        return 0
    if a.cmd == "unit":
        return run_unit(a.only.split(",") if a.only else None, a.out or Path(tempfile.mkdtemp(prefix="m8_unit_")))
    return e2e(a.out or Path(tempfile.mkdtemp(prefix="m8_e2e_")), small=a.small, world=a.world)


if __name__ == "__main__":
    sys.exit(main())
