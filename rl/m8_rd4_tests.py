#!/usr/bin/env python3
"""M8-rd4 offline tests: zero native ticks. No BattleShip launch, no replay on a real process, no training.

    python rl/m8_rd4_tests.py unit [--out DIR] [--only NAME[,NAME]]
    python rl/m8_rd4_tests.py e2e  [--out DIR] [--small] [--world W] [--async]   # the production-count synthetic end-to-end run of the three-level resume
    python rl/m8_rd4_tests.py list
    python rl/m8_rd4_tests.py integration [--out DIR]   # NOT a gate: the fake game behind the real lifecycle code (real worker processes)

DETERMINISM (decision 10). No test anywhere in this suite or in the preflight is non-deterministic. The session-level tests run the REAL session engine (Session / Session2 / Session3 / Session4,
the archive, the claims, the verification, the close checks, the rule) against the synthetic stub world (rl/m8_rd_stub.py) through an in-process lock-step worker pool and a virtual clock (rd3's
`SyncPool` and `FakeClock`): a job completes when it is sent, results are returned in dispatch order, and time advances only with the engine's polls. A run is therefore a pure function of its
configuration (tested: two runs agree on every ledger event, cell, word and decision). No test in the suite depends on the scheduling of processes or on wall-clock time. The one test that starts real
processes (the fake game behind the real lifecycle code) is NOT in the suite or the preflight: it is the separate non-gating `integration` command. The tests that read the closed
real trees, git or D: are GATES, not hermetic tests: they assert facts that are fixed once the trees are closed and the work is staged, so they can fail when the state changes but cannot flake.

The tests of rd1, rd2 and rd3 that run here (RD1_PURE, RD2_PURE, RD3_PURE) are the pure ones, classified one by one (no thread, process, sleep or wall-clock dependence); their asynchronous tests are
never run.

Light top-level imports only (spawned workers re-import this script).
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import copy
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
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))

import m8_rd_archive as march  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_claims as mclaims  # noqa: E402
import m8_rd_explore as mx  # noqa: E402
import m8_rd_resume as rs  # noqa: E402
import m8_rd_run as mrun  # noqa: E402
import m8_rd_select2 as s2  # noqa: E402
import m8_rd_stub as stub  # noqa: E402
import m8_rd_tests as t1  # noqa: E402  (rd1's helpers and the pure tests)
import m8_rd_worker as mw  # noqa: E402
import m8_rd2_report as rpt2  # noqa: E402
import m8_rd2_rule as rule2  # noqa: E402
import m8_rd2_run as run2  # noqa: E402
import m8_rd2_session as ses2  # noqa: E402
import m8_rd2_tests as t2  # noqa: E402  (rd2's helpers and the pure tests)
import m8_rd2_worker as w2  # noqa: E402
import m8_rd3_report as rpt3  # noqa: E402
import m8_rd3_resume as r3  # noqa: E402
import m8_rd3_rule as rule3  # noqa: E402
import m8_rd3_run as run3  # noqa: E402
import m8_rd3_select as s3  # noqa: E402
import m8_rd3_session as ses3  # noqa: E402
import m8_rd3_tests as t3  # noqa: E402  (rd3's helpers, the lock-step pool and the pure tests)
import m8_rd4_claims as cl4  # noqa: E402
import m8_rd4_report as rpt4  # noqa: E402
import m8_rd4_resume as r4  # noqa: E402
import m8_rd4_rule as rule4  # noqa: E402
import m8_rd4_run as run4  # noqa: E402
import m8_rd4_select as s4  # noqa: E402
import m8_rd4_session as ses4  # noqa: E402
from m8_rd_tests import Failure, check, raises, tmpdir  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
RL_DIR = Path(__file__).resolve().parent
RD1_REAL = REPO_ROOT / "runs" / "m8_rd"
RD2_REAL = REPO_ROOT / "runs" / "m8_rd_rd2"
RD3_REAL = REPO_ROOT / "runs" / "m8_rd_rd3"
NEW_MODULES = ("m8_rd4_select", "m8_rd4_resume", "m8_rd4_claims", "m8_rd4_run", "m8_rd4_session", "m8_rd4_rule", "m8_rd4_report", "m8_rd4_snapshot")
EARLIER_FILES = t3.RD1_FILES + ("m8_rd3_select", "m8_rd3_resume", "m8_rd3_run", "m8_rd3_session", "m8_rd3_rule", "m8_rd3_report", "m8_rd3_snapshot", "m8_rd3_tests")
FLOOR_MIN = t3.FLOOR_MIN
FakeClock, SyncPool, sync_env = t3.FakeClock, t3.SyncPool, t3.sync_env
# the pure tests of rd1, rd2 and rd3 (no process, no thread, no sleep, no wall-clock assertion; data from keyed streams, the stub in process, or the closed real trees, read only)
RD1_PURE = t3.RD1_PURE
RD2_PURE = t3.RD2_PURE
RD3_PURE = ("archive3_draw_switch", "begin_rd3_and_persistence", "ledger_rebuild3", "rule3_module", "identity_samples3", "new_diagnostics", "audit3_edge_cases", "selection_draws_independent")
# the synthetic chain whose rd3 tree holds frontier cells and no inherited milestone (found by experiment, then fixed here: the world, the budgets of the three sessions)
CHAIN_WORLD = "easy"
CHAIN_RD1 = (10000, 7000)
CHAIN_RD2 = 5000
CHAIN_RD3 = 5000


# -- synthetic builders: a chain rd1 -> rd2 -> rd3 (built by the real engines) -------------------------------------------------------------------------


_CHAIN4: Dict[str, Any] = {}
_TMP: List[Path] = []                               # temporary directories of the running test (removed by the runner after it)


def tree_expect3(root: Path) -> Dict[str, Any]:
    """The registered-facts dictionary of a synthetic rd3 tree (what RD3_FACTS is for the real one): counts, checkpoints, iterations, the recorded decision and the ledger totals."""
    a, meta = s4.Archive4.read_dir(root / "archive")
    prev = json.loads((root / "archive.prev" / "archive_meta.json").read_text(encoding="utf-8"))
    its = sorted(e["it"] for e in a.events if e["ev"] == "dispatch")
    rule = json.loads((root / "sessions" / "rd3" / "rule.json").read_text(encoding="utf-8"))
    return {"cells": len(a.cells), "bursts": len(a.bursts), "events": len(a.events), "checkpoint_seq": meta["checkpoint_seq"], "previous_checkpoint_seq": prev["checkpoint_seq"],
            "dispatch_iterations": (its[0], its[-1]), "first_rd2_iteration": a.rd2_first_iteration, "first_rd3_iteration": a.rd3_first_iteration, "outcome": rule["outcome"], "m": rule["m"],
            "returns": meta["ledger_T"]["jobs"], "exploration_ticks": meta["ledger_T"]["ticks"], "inherited": r4.inherited_claim_facts(a)}


def all_immutability(cp: Mapping[str, Any]) -> Dict[str, Any]:
    a = rs.rd1_immutability(cp["rd1"], cp["inc1"])
    b = rs.rd1_immutability(cp["rd2"], cp["inc2"])
    c = rs.rd1_immutability(cp["rd3"], cp["inc3"])
    return {"ok": bool(a["ok"] and b["ok"] and c["ok"]), "problems": [f"rd1: {p}" for p in a["problems"]] + [f"rd2: {p}" for p in b["problems"]] + [f"rd3: {p}" for p in c["problems"]],
            "rd1": a, "rd2": b, "rd3": c}


def build_chain4(world: str = CHAIN_WORLD, *, rd1_caps: Tuple[int, int] = CHAIN_RD1, rd2_ticks: int = CHAIN_RD2, rd3_ticks: int = CHAIN_RD3, cache: bool = True, n_workers: int = 3,
                 flags: Optional[Mapping[str, Any]] = None, exe_sha: str = "e" * 64, runtime_files: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """A synthetic rd1 tree, a synthetic rd2 tree on it and a synthetic rd3 tree on that (each by its own real engine, through the lock-step pool), every tree with its verified increment: the chain
    is a pure function of its parameters."""
    key = f"{world}|{rd1_caps}|{rd2_ticks}|{rd3_ticks}|{n_workers}|{bool(flags)}|{exe_sha}"
    if cache and key in _CHAIN4:
        return _CHAIN4[key]
    import runs_backup as rb

    base = t3.build_chain(world, rd1_caps=rd1_caps, rd2_ticks=rd2_ticks, flags=flags, exe_sha=exe_sha, runtime_files=runtime_files, cache=cache, n_workers=n_workers)
    out, sess, root3, cp = t3.run3_small(base, arm_tick_cap=rd3_ticks, min_arm_ticks=max(1000, rd3_ticks // 3), n_workers=n_workers)
    if cp["t"] in t3._TMP:
        t3._TMP.remove(cp["t"])                      # rd3's runner would delete this directory after the test: a cached chain is removed by this module's own cleanup
    r = out["rule"]
    check(r["outcome"] in rule3.OUTCOMES and r["outcome"] not in ("INVALID", "INCOMPLETE") and not r["invalid"] and not r["incomplete"], f"the synthetic rd3 session: {r['outcome']} {r['invalid']} {r['incomplete']}")
    inc3 = cp["t"] / "inc3"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = rb.cmd_backup(root3, inc3, 2)
    check(rc == 0 and (inc3 / "verification.json").is_file(), f"the synthetic rd3 increment: {buf.getvalue()[-300:]}")
    chain = dict(cp, rd3=root3, inc3=inc3, expect3=tree_expect3(root3), rd3_outcome=r["outcome"], rd3_m=r["m"], rd2_outcome=base["rd2_outcome"], rd2_m=base["rd2_m"], world=world)
    if cache:
        _CHAIN4[key] = chain
    return chain


def copy_chain4(chain: Mapping[str, Any]) -> Dict[str, Any]:
    """A private copy of a chain (mtimes kept, so every copy still equals its increment)."""
    import runs_backup as rb

    t = tmpdir("m8r4cp_")
    _TMP.append(t)
    for name in ("rd1", "inc1", "rd2", "inc2", "rd3", "inc3"):
        shutil.copytree(chain[name], t / name)
    for inc_key, dst in (("inc1", "rd1"), ("inc2", "rd2"), ("inc3", "rd3")):
        man = rb.read_manifest(chain[inc_key])
        for rel, (_sha, _size, mt) in man.items():
            os.utime(t / dst / rel.replace("/", os.sep), ns=(mt, mt))
    return dict(chain, t=t, rd1=t / "rd1", inc1=t / "inc1", rd2=t / "rd2", inc2=t / "inc2", rd3=t / "rd3", inc3=t / "inc3")


def small_cfg4(root: Path, **kw: Any) -> Any:
    base = dict(n_workers=3, arm_tick_cap=12000, arm_caps={"T": 12000}, min_arm_ticks=4000, p1_tick_cap=20000, replay_tick_cap=300000,
                wall_caps_s={"p1": 90.0, "T": 300.0, "C": 0.0, "verify": 300.0}, global_cap_s=1200.0, checkpoint_every_s=4.0, verify_threads=2, identity_k=6)
    base.update(kw)
    if "arm_tick_cap" in kw and "arm_caps" not in kw:
        base["arm_caps"] = {"T": kw["arm_tick_cap"]}
    return ses4.run_config(root=root, **base)


def open_chain4(cp: Mapping[str, Any], root4: Path) -> Tuple[Dict[str, Any], s4.Archive4]:
    """The rd4 open protocol (R1-R5, three levels) and the materialisation (R6) on a private copy of a chain."""
    op = ses4.open_protocol4(cp["rd1"], cp["rd2"], cp["rd3"], cp["inc1"], cp["inc2"], cp["inc3"], expect1=cp["expect1"], expect2=cp["expect2"], expect3=cp["expect3"], check_overlay=False,
                             live_pins=lambda: t3.live_pins_of(cp), floor_min=FLOOR_MIN)
    check(op["ok"], f"the rd4 open protocol on a synthetic chain: {op['problems']}")
    a4 = r4.materialise4(cp["rd3"], root4, facts=op["facts3"], overlay=op["overlay"], lines_sha256=cp["lines"],
                         meta_extra={"pins": cp["pins"], "pin_tick0": op["facts3"]["pin_tick0"], "ticks": {}, "ledger_T": {}},
                         increment_manifest_sha256=op["R1_rd3_immutability"]["manifest_sha256"], utc="2026-10-03T00:00:00Z", floor_min=FLOOR_MIN)
    return op, a4


def run4_small(chain: Mapping[str, Any], *, world: Optional[str] = None, inject: Optional[Mapping[str, Any]] = None, env_kw: Optional[Mapping[str, Any]] = None,
               immutability: Optional[Callable[[], Mapping[str, Any]]] = None, env_kw_factory: Optional[Callable[[Mapping[str, Any], FakeClock], Mapping[str, Any]]] = None,
               clock_step: float = 0.25, session_cls: Any = None, pool_factory: Optional[Callable[[Any, Any, FakeClock], SyncPool]] = None,
               **cfg_kw: Any) -> Tuple[Dict[str, Any], Any, Path, Dict[str, Any]]:
    """The rd4 session (open protocol, materialise, Session4, run_all4) against a private copy of a synthetic chain and the stub, through the lock-step pool."""
    cp = copy_chain4(chain)
    root4 = cp["t"] / "rd4"
    cfg = small_cfg4(root4, **cfg_kw)
    op, a4 = open_chain4(cp, root4)
    cfg.session_dir.mkdir(parents=True)
    mw.ProvenanceGuard.install()
    mw.ProvenanceGuard.violations.clear()
    w2.WriteGuard.install([cp["rd1"], cp["rd2"], cp["rd3"]])
    try:
        clock = FakeClock(clock_step)
        env = sync_env(world or cp["world"], [cp["rd1"], cp["rd2"], cp["rd3"]], clock, inject, pins=cp["pins"], **dict(env_kw or {}),
                       **dict(env_kw_factory(cp, clock) if env_kw_factory else {}))
        sess = (session_cls or run4.Session4)(cfg, env, archive=a4, archive_pin=op["facts3"]["pin_tick0"], base_info={"overlay_sha256": op["overlay"]["sha256"]}, rd1_root=cp["rd1"],
                                              rd2_root=cp["rd2"], rd3_root=cp["rd3"], lines_sha256=cp["lines"], ckpt_seq=int(op["facts3"]["rd3_checkpoint_seq"]) + 1)
        sess.pool = pool_factory(env, cfg, clock) if pool_factory else SyncPool(env, cfg, clock)
        out = run4.run_all4(sess, immutability=immutability or (lambda: all_immutability(cp)))
    finally:
        w2.WriteGuard.clear()
    return out, sess, root4, cp


def signature(root4: Path) -> Dict[str, Any]:
    """What must be identical between two runs of the same configuration: the archive's data files (but its meta, which carries timestamps) and the decision."""
    a = root4 / "archive"
    rule = json.loads((root4 / "sessions" / "rd4" / "rule.json").read_text(encoding="utf-8"))
    return {"files": {n: mw.sha256_file(a / n) for n in ("cells.jsonl", "bursts.bin", "bursts.idx.jsonl", "events.jsonl")},
            "rule": {k: rule[k] for k in ("outcome", "m", "max_targets_verified", "progress_basis", "any_stop", "launch_capable_created")}, "mechanism": rule["mechanism"], "line": rule["line"]["status"]}


def synth_archive4(seed: str = "s4", n1: int = 40, n2: int = 50, n3: int = 50, n4: int = 50, floor_min: float = -2100.0, lines: str = "lines") -> s4.Archive4:
    """A four-part archive from keyed random jobs: rd1's part under v1, rd2's and rd3's under v2 (draw ids `_v2`, `_rd3`), rd4's under v3 (draw id `_rd4`)."""
    rng = t2.Krng(seed)
    a = s4.Archive4("syn4", floor_min=floor_min)
    a.init_cell0(t1.key(0, 0), t1.mk_end(), bytes(32), bytes([1]) * 32)
    t2.drive2(a, rng, n1, 0, v2=False)
    a.begin_v2(n1, lines)
    t2.drive2(a, rng, n2, n1, v2=True)
    a.begin_rd3(n1 + n2, lines)
    t2.drive2(a, rng, n3, n1 + n2, v2=True)
    a.begin_rd4(n1 + n2 + n3, lines)
    t2.drive2(a, rng, n4, n1 + n2 + n3, v2=True)
    return a


def fresh4(aid: str = "t4", floor_min: float = -2550.0) -> s4.Archive4:
    a = s4.Archive4(aid, floor_min=floor_min)
    a.init_cell0(t1.key(0, 0), t1.mk_end(), bytes(32), bytes([1]) * 32)
    return a


def archive_for_prob(cells: Sequence[Tuple[Any, ...]], *, with_rd4: bool = True) -> s4.Archive4:
    """A small archive in mode 2 (rd2 and rd3 begun, rd4 begun when asked) holding the given (key, L, y, seen, chosen) cells."""
    a = fresh4("pb", -2550.0)
    for k, L, y, seen, chosen in cells:
        t2.add_cell2(a, k, L, y=y, seen=seen, chosen=chosen)
    a.begin_v2(5, "L")
    a.begin_rd3(6, "L")
    if with_rd4:
        a.begin_rd4(7, "L")
    return a


# -- the contract and the selection ---------------------------------------------------------------------------------------------------------------------


def unit_rd4_contract() -> Dict[str, Any]:
    import m7q_status_table as st

    check(s4.DRAW_SUFFIX == "_rd4" and s4.DRAW_SUFFIX_RD3 == "_rd3" and s4.DRAW_SUFFIX_RD2 == "_v2" and s4.SESSION_NAME == "rd4" and s4.SESSION_NAME_RD3 == "rd3" and s4.SESSION_NAME_RD2 == "rd2",
          "the session names and the draw suffixes (rd4's is its own)")
    check(mx.select_key("m8_rd_a1_rd4", 10406) == "m8_rd|m8_rd_a1_rd4|select|10406", "the selection key string")
    check(mx.explore_key("m8_rd_a1_rd4", 10406, 3) == "m8_rd|m8_rd_a1_rd4|explore|10406|3", "the exploration key string")
    a = s4.Archive4("m8_rd_a1")
    check(a.draw_id_rd2 == "m8_rd_a1_v2" and a.draw_id_rd3 == "m8_rd_a1_rd3" and a.draw_id_rd4 == "m8_rd_a1_rd4" and len({a.draw_id_rd2, a.draw_id_rd3, a.draw_id_rd4}) == 3 and a.archive_id == "m8_rd_a1",
          "the draw ids")
    d = s4.draws_description()
    check(d["select"] == "m8_rd|<archive id>_rd4|select|<iteration>" and d["identity_open"].endswith("identity_open|rd4|<cell id>") and d["identity_close"].endswith("identity_close|rd4|<cell id>")
          and d["rd3_select"].endswith("_rd3|select|<iteration>"), f"the registered key strings: {d}")
    check(len(s4.draws_digest()) == 64 and s4.draws_digest() == s4.draws_digest() and s4.draws_digest() != s3.draws_digest(), "the draws digest")
    check(rule4.RULE_ID == "m8_rd4_rule_v1" and rule4.rule_digest() not in (rule3.rule_digest(), rule2.rule_digest()), "rd4's own rule")
    check(rule4.SCOPE.startswith("M8-rd4: third continuation of archive m8_rd_a1") and "no control arm" in rule4.SCOPE and "not a policy result" in rule4.SCOPE and "m8_rd_select_v3" in rule4.SCOPE, "the scope label")
    # the caps are rd2's and rd3's, number for number (decision 4)
    c4, c3, c2 = ses4.caps(), ses3.caps(), ses2.caps()
    check(c4 == c3 == c2, f"caps differ: { {k: (c4[k], c3[k], c2.get(k)) for k in c4 if c4[k] != c3[k] or c4[k] != c2.get(k)} }")
    cfg = ses4.run_config()
    check(cfg.session_id == "rd4" and cfg.root == ses4.RD4_ROOT and cfg.arm_cap("T") == 6_000_000 and cfg.min_arm_ticks == 2_000_000 and cfg.n_workers == 5 and cfg.burst_words == 120 and cfg.horizon == 3600
          and cfg.p1_tick_cap == 70_000 and cfg.replay_tick_cap == 400_000 and cfg.global_cap_s == 3600.0 and dict(cfg.wall_caps_s) == {"p1": 240.0, "T": 3000.0, "C": 0.0, "verify": 360.0},
          "run_config carries the registered values")
    check(ses4.RD4_ROOT.name == "m8_rd_rd4" and ses4.RD3_ROOT.name == "m8_rd_rd3" and ses4.RD2_ROOT.name == "m8_rd_rd2" and ses4.RD1_ROOT.name == "m8_rd" and ses4.APPROVAL.name == "rl_m8_rd4_approval.json",
          "the roots and the approval path")
    # v3 = v2 with exactly one change: the digest is built from v2's own description, a replica proved equal to v2's digest
    sha = st.load_table()["sha256"]
    check(s4.v2_replica_ok(sha, "lines") and s4.v2_replica_ok(sha, "other lines", -2000.0), "the replica of v2's description hashes exactly like v2's own digest")
    changed = s4.changed_keys(sha, "lines")
    check(changed == sorted(("contract", "cell_weight", "count_term", "draws")) and set(s4.REGISTERED_CHANGES) == set(changed), f"exactly the registered keys differ between v2 and v3: {changed}")
    d2, d3 = s4.select2_description(sha, "lines"), s4.select3_description(sha, "lines")
    same = [k for k in d2 if k not in s4.REGISTERED_CHANGES]
    check(same and all(d2[k] == d3[k] for k in same), "every other part of the contract is v2's, unchanged (eligibility, level weight, length factor, resource weights, descent doom, bound, replacement)")
    check(d3["cell_weight"] == "(1/sqrt(1+seen)) * 900 / (900 + L - L_min(level over eligible cells)) * w_res" and d3["count_term"]["exponent"] == 0.5 and d3["count_term"]["tuned"] is False and s4.COUNT_EXPONENT == 0.5,
          "the published exponent, not tuned")
    check(s4.select3_contract_digest(sha, "lines") != s2.select2_contract_digest(sha, "lines") and s4.select3_contract_digest(sha, "lines") != s4.select3_contract_digest(sha, "other lines"),
          "v3's digest differs from v2's and depends on the pinned line table")
    digs = ses4.contract_digests4("lines")
    check(set(digs) == {"m8_rd_cell_v1", "m8_rd_select_v1", "m8_rd_explore_v1", "m8_rd_claims_v1", "track1_btt_s9_b8_v1", "btt_action_class_table_v2", "m8_rd_select_v2", "m8_rd_select_v3"}
          and digs["m8_rd_select_v3"] != digs["m8_rd_select_v2"], "contract digests: v2's and v3's side by side")
    # the history ran v2 unchanged: the digests recorded by rd2's and rd3's own session events equal the digest recomputed from the current v2 code (the closed real trees, read only)
    if (RD3_REAL / "archive" / "events.jsonl").is_file():
        ev = ses3._events(RD3_REAL / "archive")
        check([(e["name"], e["first_iteration"]) for e in ev] == [("rd2", 2175), ("rd3", 6212)], f"rd2's and rd3's session events: {ev}")
        meta = json.loads((RD3_REAL / "archive" / "archive_meta.json").read_text(encoding="utf-8"))
        want = s2.select2_contract_digest(st.load_table()["sha256"], meta["pin_tick0"]["lines"], float(meta["floor_min"]))
        check(all(e["digest"] == want for e in ev), "rd2's and rd3's recorded selection digests equal the v2 digest recomputed from the current code")
        check(s4.select3_contract_digest(st.load_table()["sha256"], meta["pin_tick0"]["lines"], float(meta["floor_min"])) != want, "and v3's digest differs from it")
    return {"v3_digest": s4.select3_contract_digest(sha, "lines")[:12]}


def unit_select_v3_formula() -> Dict[str, Any]:
    """The v3 cell weight against an independent formula; the count term reads `seen` only; v2's weights are untouched; the analytic probabilities."""
    mk = t2.mkey
    spec = [(mk(1, 1, "A2"), 100, 300.0, 0, 0), (mk(2, 1, "A2"), 400, 300.0, 3, 0), (mk(3, 1, "A1"), 700, 300.0, 8, 5), (mk(4, 1, "A0"), 1000, 300.0, 24, 1), (mk(5, 1, "G", 1023, 4), 250, 0.0, 99, 0),
            (mk(6, 1, "A2"), 100, 300.0, 3, 77)]
    a = archive_for_prob(spec)
    cells = [c for c in a.cells if c.id != 0 and c.level == 0]
    lmin = min(c.L for c in cells)
    for c, w in zip(cells, s4.v3_weights(cells)):
        want = (1.0 / math.sqrt(1 + c.seen)) * (900.0 / (900.0 + c.L - lmin)) * s2.W_RES[c.key[2]]
        check(abs(w - want) < 1e-15, f"cell {c.id}: v3 weight {w}, the independent formula {want}")
    # seen only: two cells equal in everything but `chosen` weigh the same under v3 and differently under v2
    p, q = cells[1], cells[5]
    check(p.seen == q.seen == 3 and p.chosen != q.chosen and p.L != q.L, "the two cells differ in L and chosen")
    a.cells[q.id].L = p.L
    a._version += 1
    w3 = dict(zip([c.id for c in cells], s4.v3_weights(cells)))
    w2 = dict(zip([c.id for c in cells], s2.Archive2.cell_weights(a, cells)))
    check(abs(w3[p.id] - w3[q.id]) < 1e-15 and abs(w2[p.id] - w2[q.id]) > 1e-3, "v3 ignores `chosen`; v2 does not")
    # the exponent is 1/2: weight(seen = 3) / weight(seen = 0) = 1/2 exactly (same L and resource)
    e = fresh4("e")
    r = s4.v3_weights([t2.add_cell2(e, mk(1, 1, "A2"), 100, y=0.0, seen=s) for s in (0, 3, 15)])
    check(abs(r[1] / r[0] - 0.5) < 1e-15 and abs(r[2] / r[0] - 0.25) < 1e-15, f"(1 + seen)^-1/2: {r}")
    # the generic cell_weights follows the flag; a v2-mode archive is v2's, byte for byte
    a._v3 = False
    check(a.cell_weights(cells) == s2.Archive2.cell_weights(a, cells), "with the flag off the weights are v2's")
    a._v3 = True
    check(a.cell_weights(cells) == s4.v3_weights(cells), "with the flag on the weights are v3's")
    a._v3 = False
    # analytic probabilities: level weights 1 / (1 + top - level), cell weights normalised within the level
    for mode in ("v2", "v3"):
        pr = a.probabilities(mode)
        check(abs(sum(pr.values()) - 1.0) < 1e-12, f"{mode}: probabilities sum to one")
    check(a.probabilities() == a.probabilities("v3") and not a._v3, "the default is v3 once rd4 has begun, and the flag is restored")
    b = archive_for_prob(spec, with_rd4=False)
    check(b.probabilities() == b.probabilities("v2"), "the default is v2 before rd4 begins")
    pr3 = a.probabilities("v3")
    levels = a.eligible_levels()
    check(sorted(levels) == [0], "one level in this archive")
    lv_cells = levels[0]
    lmin0 = min(c.L for c in lv_cells)
    ws = [(1.0 / math.sqrt(1 + c.seen)) * (900.0 / (900.0 + c.L - lmin0)) * s2.W_RES[c.key[2]] for c in lv_cells]
    for c, w in zip(lv_cells, ws):
        check(abs(pr3[c.id] - w / sum(ws)) < 1e-12, f"cell {c.id}: analytic probability")
    # two levels: 1 / (1 + top - level)
    c2 = t2.add_cell2(a, mk(0, 2, "A2", 1022), 500, y=600.0, seen=1)
    pr = a.probabilities("v3")
    lv = a.eligible_levels()
    tot = sum(1.0 / (1.0 + max(lv) - x) for x in lv)
    check(abs(sum(pr[c.id] for c in lv[c2.level]) - (1.0 / (1.0 + max(lv) - c2.level)) / tot) < 1e-12, "level mass 1 / (1 + top - level)")
    raises(s4.Select4Error, lambda: a.probabilities("v9"), "an unknown mode is refused")
    return {"cells": len(cells)}


def unit_archive4_draw_and_weights_switch() -> Dict[str, Any]:
    n1, n2, n3, n4 = 40, 50, 50, 50
    a = synth_archive4("sw", n1, n2, n3, n4)
    check(a.mode == 2 and a.rd2_first_iteration == n1 and a.rd3_first_iteration == n1 + n2 and a.rd4_first_iteration == n1 + n2 + n3 and a.first_iteration == n1 + n2 + n3 and a.draw_id == a.draw_id_rd4,
          "the four-part archive")
    for it, want in ((0, "syn4_v2"), (n1 - 1, "syn4_v2"), (n1, "syn4_v2"), (n1 + n2 - 1, "syn4_v2"), (n1 + n2, "syn4_rd3"), (n1 + n2 + n3 - 1, "syn4_rd3"), (n1 + n2 + n3, "syn4_rd4"),
                     (n1 + n2 + n3 + 1000, "syn4_rd4")):
        check(a.draw_for(it) == want, f"draw_for({it}) = {a.draw_for(it)}, expected {want}")
    check(a.iteration_ranges() == {"rd1": (0, n1 - 1), "rd2": (n1, n1 + n2 - 1), "rd3": (n1 + n2, n1 + n2 + n3 - 1), "rd4": (n1 + n2 + n3, n1 + n2 + n3 + n4 - 1)}, f"ranges {a.iteration_ranges()}")
    check([a.session_of_iteration(i) for i in (0, n1 - 1, n1, n1 + n2, n1 + n2 + n3, 10 ** 6)] == ["rd1", "rd1", "rd2", "rd3", "rd4", "rd4"], "session_of_iteration")
    nxt = n1 + n2 + n3 + n4
    keep_draw, keep_v3 = a.draw_id, a._v3

    def independent(it: int, draw: str, v3: bool) -> int:
        """The selection re-implemented here: keyed uniforms, level weights 1 / (1 + top - level), cell weights by the registered formulas."""
        levels = a.eligible_levels()
        top = max(levels)
        order = sorted(levels)
        wl = [1.0 / (1.0 + top - lv) for lv in order]
        u1, u2 = mx.uniforms(mx.select_key(draw, it))
        r, acc, level = u1 * sum(wl), 0.0, order[-1]
        for lv, w in zip(order, wl):
            acc += w
            if r < acc:
                level = lv
                break
        cells = levels[level]
        lmin = min(c.L for c in cells)
        if v3:
            ws = [(1.0 / math.sqrt(1 + c.seen)) * (900.0 / (900.0 + c.L - lmin)) * s2.W_RES[c.key[2]] for c in cells]
        else:
            ws = [(1.0 / math.sqrt(1 + c.chosen) + 1.0 / math.sqrt(1 + c.seen)) * (900.0 / (900.0 + c.L - lmin)) * s2.W_RES[c.key[2]] for c in cells]
        r, acc, want = u2 * sum(ws), 0.0, cells[-1]
        for c, w in zip(cells, ws):
            acc += w
            if r < acc:
                want = c
                break
        return want.id

    for it in range(nxt, nxt + 60):                                       # rd4 iterations: v3 weights, the rd4 draw
        check(a.select(it).id == independent(it, a.draw_id_rd4, True), f"iteration {it}: select differs from the independent v3 draw")
    for it in range(n1 + n2 + 5, n1 + n2 + 35):                           # rd3 iterations: v2 weights, the rd3 draw (selected on the CURRENT archive state, as a later reader would)
        check(a.select(it).id == independent(it, a.draw_id_rd3, False), f"iteration {it}: an rd3 iteration is not selected under v2 and the rd3 draw")
    for it in range(n1 + 3, n1 + 30):
        check(a.select(it).id == independent(it, a.draw_id_rd2, False), f"iteration {it}: an rd2 iteration is not selected under v2 and the rd2 draw")
    check(a.draw_id == keep_draw and a._v3 == keep_v3, "select restores the draw id and the weight flag")
    differ = sum(int(independent(it, a.draw_id_rd4, True) != independent(it, a.draw_id_rd4, False)) for it in range(nxt, nxt + 200))
    check(differ > 0, "v3's weights select differently from v2's on the same draws")
    differ2 = sum(int(independent(it, a.draw_id_rd4, True) != independent(it, a.draw_id_rd3, True)) for it in range(nxt, nxt + 200))
    check(differ2 > 0, "rd4's draws are not rd3's")
    w4 = list(mx.words(lambda i: mx.explore_key("syn4_rd4", 7000, i), 60))
    w3_ = list(mx.words(lambda i: mx.explore_key("syn4_rd3", 7000, i), 60))
    check(w4 != w3_ and len(w4) == 60, "the explorer draws are keyed by the session's draw id")
    b = fresh4("m1")
    check(b.mode == 1 and b.select(5).id == march.Archive.select(b, 5).id, "mode 1 is rd1's selection")
    return {"differ_of_200": differ}


def unit_begin_rd4_and_persistence() -> Dict[str, Any]:
    a = fresh4("br", -2550.0)
    raises(s4.Select4Error, lambda: a.begin_rd4(5, "L"), "rd4 cannot begin before rd2's and rd3's session events")
    t2.drive2(a, t2.Krng("br"), 20, 0, v2=False)
    a.begin_v2(20, "L")
    raises(s4.Select4Error, lambda: a.begin_rd4(5, "L"), "rd4 cannot begin before rd3's session event")
    t2.drive2(a, t2.Krng("br2"), 15, 20, v2=True)
    a.begin_rd3(35, "L")
    t2.drive2(a, t2.Krng("br3"), 12, 35, v2=True)
    raises(s4.Select4Error, lambda: a.begin_rd4(40, "L"), "reusing a dispatched iteration is refused")
    a.apply_dispatch(500, 0, 0)
    raises(s4.Select4Error, lambda: a.begin_rd4(600, "L"), "a pending dispatch blocks the switch")
    a.note_failure(500, "x")
    raises(s4.Select4Error, lambda: a.begin_rd4(600, "another line table"), "a selection contract that is not the one rd2 and rd3 ran is refused (the v2 digest differs)")
    n_ev = len(a.events)
    ev = a.begin_rd4(600, "L")
    check(ev["name"] == "rd4" and ev["first_iteration"] == 600 and ev["draw_suffix"] == "_rd4" and ev["select"] == "m8_rd_select_v3" and a.events[-1] == ev and len(a.events) == n_ev + 1, "one session event")
    sess = [e for e in a.events if e["ev"] == "session"]
    v2d = s2.select2_contract_digest(a.clf.table_sha256, "L", a.floor_min)
    check([e["name"] for e in sess] == ["rd2", "rd3", "rd4"] and sess[0]["digest"] == sess[1]["digest"] == v2d and sess[2]["digest"] != v2d
          and sess[2]["digest"] == s4.select3_contract_digest(a.clf.table_sha256, "L", a.floor_min) and sess[2]["changed_from"]["digest"] == v2d and sess[2]["changed_from"]["select"] == "m8_rd_select_v2",
          "rd4's digest is v3's, with v2's (the earlier sessions') recorded beside it")
    check(a.rd4_first_iteration == 600 and a.first_iteration == 600 and a.draw_id == a.draw_id_rd4 and a.rd2_first_iteration == 20 and a.rd3_first_iteration == 35, "state after the switch")
    raises(s4.Select4Error, lambda: a.begin_rd4(700, "L"), "a second switch is refused")
    # persistence: rd3-readable files before rd4, the prefix property and the reload
    t = tmpdir("m8r4p_")
    x = fresh4("br", -2550.0)
    t2.drive2(x, t2.Krng("br"), 20, 0, v2=False)
    x.begin_v2(20, "L")
    t2.drive2(x, t2.Krng("br2"), 15, 20, v2=True)
    x.begin_rd3(35, "L")
    t2.drive2(x, t2.Krng("br3"), 12, 35, v2=True)
    march.save_checkpoint(t / "rd3" / "archive", x, {"checkpoint_seq": 32, "why": "x"})
    y, meta_y = s4.Archive4.read_dir(t / "rd3" / "archive")
    check(y.rd4_first_iteration is None and y.rd3_first_iteration == 35 and y.draw_id == y.draw_id_rd3, "an rd3 closing archive loads as an Archive4 before rd4")
    check(s3.Archive3.read_dir(t / "rd3" / "archive")[0].rd3_first_iteration == 35, "rd3's own loader still reads it")
    y.begin_rd4(47, "L")
    t2.drive2(y, t2.Krng("br4"), 12, 47, v2=True)
    march.save_checkpoint(t / "rd4" / "archive", y, {"checkpoint_seq": 33, "why": "x"})
    pp = rs.prefix_property(t / "rd3" / "archive", t / "rd4" / "archive")
    check(pp["ok"] and pp["events.jsonl"]["lines"] == len(x.events) and pp["bursts.idx.jsonl"]["lines"] == len(x.bursts), f"rd4's files begin with rd3's closing bytes: {pp}")
    z, meta_z = s4.Archive4.read_dir(t / "rd4" / "archive")
    check(meta_z["schema"] == s2.ARCHIVE_SCHEMA_V2 and meta_z["archive4_contract"] == s4.ARCHIVE4_CONTRACT and meta_z["rd4_first_iteration"] == 47 and meta_z["rd3_first_iteration"] == 35
          and meta_z["draw_ids4"] == {"rd1": "br", "rd2": "br_v2", "rd3": "br_rd3", "rd4": "br_rd4"} and meta_z["select3_contract"] == "m8_rd_select_v3" and meta_z["floor_min"] == -2550.0,
          f"the rd4 directory is self-describing: { {k: meta_z.get(k) for k in ('archive4_contract', 'rd4_first_iteration', 'draw_ids4', 'select3_contract')} }")
    check(z.rd4_first_iteration == 47 and z.first_iteration == 47 and z.draw_id == "br_rd4" and z.mode == 2, "the reload knows the session switch")
    v3_ev = [e for e in z.events if e["ev"] == "session" and e["name"] == "rd4"]
    check(len(v3_ev) == 1 and meta_z["select3_digest"] == v3_ev[0]["digest"] == meta_z["select2_digest"] and meta_z["select2_contract"] == "m8_rd_select_v2",
          "the checkpoint names v3's digest unambiguously (`select3_digest`); rd2's writer's `select2_digest` is the LAST session's digest, which here is v3's")
    check([c.to_json() for c in z.cells] == [c.to_json() for c in y.cells] and z.diag2 == y.diag2 and z.desc == y.desc and z.bound == y.bound, "a reload reproduces cells, counters and derived flags")
    check(s4.audit4(z, "L")["ok"], "the reloaded four-part archive audits")
    check(s4.rebuild4(z, "L").events == z.events, "the rebuild reproduces the ledger")
    raises(s3.Select3Error, lambda: s3.Archive3.read_dir(t / "rd4" / "archive"), "rd3's loader refuses an rd4 archive (three session events): it cannot rebuild it")
    w, _m = s2.Archive2.read_dir(t / "rd4" / "archive")
    check(w.mode == 2 and w.first_iteration == 47, "rd2's loader reads the rd4 directory (mode 2; the last session's first iteration)")
    # adopt refuses archives that are not an rd3 archive
    v2only = s2.Archive2("br")
    v2only.init_cell0(t1.key(0, 0), t1.mk_end(), bytes(32), bytes([1]) * 32)
    raises(s4.Select4Error, lambda: s4.Archive4.adopt(v2only), "an archive with no session event is not an rd3 archive")
    only_rd2 = fresh4("o2")
    only_rd2.begin_v2(5, "L")
    raises(s4.Select4Error, lambda: s4.Archive4.adopt(only_rd2), "an rd2 archive (one session event) is not an rd3 archive")
    # the prefix property fails when rd3's bytes are not kept
    bad = t / "bad"
    shutil.copytree(t / "rd4" / "archive", bad)
    ev_p = bad / "events.jsonl"
    ev_p.write_bytes(ev_p.read_bytes().replace(b'"worker":0', b'"worker":1', 1))
    check(not rs.prefix_property(t / "rd3" / "archive", bad)["ok"], "a changed rd3 ledger line fails the prefix property")
    # atomic checkpoints: a crash at any step leaves a verifying, auditable checkpoint
    for crash in (None, "tmp_written", "tmp_verified", "current_moved", "new_installed"):
        root = t / f"ck_{crash}" / "archive"
        march.save_checkpoint(root, z, {"checkpoint_seq": 1})
        t2.drive2(z, t2.Krng(f"more{crash}"), 4, 200, v2=True)
        try:
            march.save_checkpoint(root, z, {"checkpoint_seq": 2}, crash_at=crash)
            check(crash is None, "unexpected success")
        except march.SimulatedCrash:
            check(crash is not None, "unexpected crash")
        d, m, rep = march.load_latest_verified(root)
        check(d is not None, f"no verified checkpoint after a crash at {crash}: {rep}")
        loaded, _mm = s4.Archive4.read_dir(d)
        check(s4.audit4(loaded, "L")["ok"] and m["checkpoint_seq"] == 2, f"crash {crash}: the newest complete checkpoint audits")
        z, _m3 = s4.Archive4.read_dir(t / "rd4" / "archive")
    shutil.rmtree(t, ignore_errors=True)
    return {"cells": len(a.cells)}


def unit_ledger_rebuild4() -> Dict[str, Any]:
    n1, n2, n3, n4 = 50, 60, 60, 70
    a = synth_archive4("lr4", n1, n2, n3, n4)
    check(len(a.cells) > 250 and len(a.bursts) == n1 + n2 + n3 + n4 and a.mode == 2, f"the synthetic four-part archive: {len(a.cells)} cells")
    check(all(len(b.reaches[0]) == 3 for b in a.bursts[:n1] if b.reaches) and any(len(b.reaches[0]) == 4 for b in a.bursts[n1:] if b.reaches), "reach rows: rd1's keep three elements, the later parts' four")
    aud = s4.audit4(a, "lines")
    check(aud["ok"], f"audit of a four-part archive: {aud['problems']}")
    check(aud["prefixes_reconstructed"] == len(a.cells) and aud["dispatch_rows"] == [], "every prefix reconstructs; no rows unless asked")
    rb = s4.rebuild4(a, "lines")
    check([c.to_json() for c in rb.cells] == [c.to_json() for c in a.cells] and rb.events == a.events and rb.diag2 == a.diag2 and rb.rd4_first_iteration == a.rd4_first_iteration, "the rebuild equals the archive")
    check(not s3.audit3(a, "lines")["ok"], "rd3's own audit cannot cross a third session event (which is why rebuild4 exists)")
    rd, rbd = a.reference_flags()
    check(rd == a.desc and rbd == a.bound, "the incremental flags equal the recomputation")
    t = tmpdir("m8r4lr_")
    a.write_files(t / "a", {"checkpoint_seq": 1})

    def load() -> s4.Archive4:
        b, _m = s4.Archive4.read_dir(t / "a")
        return b

    check(s4.audit4(load(), "lines")["ok"], "a saved and reloaded archive audits")
    first4 = n1 + n2 + n3
    b = load()
    k = next(i for i, e in enumerate(b.events) if e["ev"] == "dispatch" and e["it"] == first4 + 3)
    b.events[k]["cell"] = (b.events[k]["cell"] + 1) % len(b.cells)
    check(not s4.audit4(b, "lines")["ok"], "a changed rd4 selection is detected by the re-derived draw")
    b = load()
    b.events = [e for e in b.events if not (e["ev"] == "session" and e["name"] == "rd4")]
    check(not s4.audit4(b, "lines")["ok"], "a ledger without rd4's session event does not rebuild (the rd4 draws and weights are lost)")
    b = load()
    next(e for e in b.events if e["ev"] == "session" and e["name"] == "rd4")["first_iteration"] += 1
    check(not s4.audit4(b, "lines")["ok"], "a shifted rd4 first iteration is detected")
    b = load()
    idx = [i for i, e in enumerate(b.events) if e["ev"] == "session"]
    b.events[idx[1]], b.events[idx[2]] = b.events[idx[2]], b.events[idx[1]]
    check(not s4.audit4(b, "lines")["ok"], "swapped session events are detected")
    b = load()
    next(e for e in b.events if e["ev"] == "session" and e["name"] == "rd4")["digest"] = "0" * 64
    check(not s4.audit4(b, "lines")["ok"], "a tampered rd4 session digest is detected")
    b = load()
    next(e for e in b.events if e["ev"] == "session" and e["name"] == "rd4")["changed_from"]["digest"] = "0" * 64
    check(not s4.audit4(b, "lines")["ok"], "a tampered record of the v2 digest is detected")
    b = load()
    next(e for e in b.events if e["ev"] == "session" and e["name"] == "rd3")["digest"] = "0" * 64
    check(not s4.audit4(b, "lines")["ok"], "a tampered rd3 session digest is detected")
    check(not s4.audit4(load(), "other lines")["ok"], "a different pinned line table is detected through the session digests")
    b = load()
    next(e for e in b.events if e["ev"] == "session" and e["name"] == "rd4")["draw_suffix"] = "_rd3"
    check(not s4.audit4(b, "lines")["ok"], "a tampered draw suffix is detected")
    b = load()
    b.cells[len(b.cells) // 2].seen += 1
    check(not s4.audit4(b, "lines")["ok"], "a tampered `seen` counter (the v3 count term) is detected")
    b = load()
    v4b = next(x for x in b.bursts[first4 + 5:] if x.reaches)
    v4b.reaches[0][3] = 1 - v4b.reaches[0][3]
    check(not s4.audit4(b, "lines")["ok"], "a tampered bound bit in an rd4 burst is detected")
    b = load()
    b.diag2["revivals"] += 1
    check(not s4.audit4(b, "lines")["ok"], "a tampered v2 counter is detected")
    b = load()
    b.desc[7] = not b.desc[7]
    check(not s4.audit4(b, "lines")["ok"], "a tampered derived flag is detected against the recomputation")
    b = load()
    b.bursts[first4 + 2].start_rep = (900, 0)
    check(not s4.audit4(b, "lines")["ok"], "a lineage that points forward is detected")
    b = load()
    dup = next(e for e in b.events if e["ev"] == "dispatch" and e["it"] == first4 + 4)
    dup["it"] = first4 + 3
    check(not s4.audit4(b, "lines")["ok"], "a reused iteration is detected")
    b = load()
    ing = next(e for e in b.events if e["ev"] == "ingest" and e["burst"] >= 0)
    ing["burst"] = 10 ** 6
    r = s4.audit4(b, "lines")
    check(not r["ok"] and any("rebuild failed" in x for x in r["problems"]), f"a ledger naming a burst that does not exist is an audit failure, not an exception: {r['problems'][:2]}")

    # an rd4 part selected under the OLD weights (v2) does not audit under v3
    class OldWeights(s4.Archive4):
        def v3_for(self, iteration: int) -> bool:
            return False

    rng = t2.Krng("old")
    o = OldWeights("syn4", floor_min=-2100.0)
    o.init_cell0(t1.key(0, 0), t1.mk_end(), bytes(32), bytes([1]) * 32)
    t2.drive2(o, rng, n1, 0, v2=False)
    o.begin_v2(n1, "lines")
    t2.drive2(o, rng, n2, n1, v2=True)
    o.begin_rd3(n1 + n2, "lines")
    t2.drive2(o, rng, n3, n1 + n2, v2=True)
    o.begin_rd4(first4, "lines")
    t2.drive2(o, rng, n4, first4, v2=True)
    check(not s4.audit4(o, "lines")["ok"], "an rd4 part selected under v2's weights fails the audit under v3")
    shutil.rmtree(t, ignore_errors=True)
    return {"cells": len(a.cells), "wins": sum(len(x.wins) for x in a.bursts)}


def unit_dispatch_rows_and_mechanism_inputs() -> Dict[str, Any]:
    """The mechanism check's raw data: the audit's own rebuild reports, for every dispatch, the start cell's counters AT DISPATCH; they equal what a live driver sees."""
    n1, n2, n3 = 40, 40, 40
    rng = t2.Krng("rows")
    a = s4.Archive4("syn4", floor_min=-2100.0)
    a.init_cell0(t1.key(0, 0), t1.mk_end(), bytes(32), bytes([1]) * 32)
    t2.drive2(a, rng, n1, 0, v2=False)
    a.begin_v2(n1, "lines")
    t2.drive2(a, rng, n2, n1, v2=True)
    a.begin_rd3(n1 + n2, "lines")
    t2.drive2(a, rng, n3, n1 + n2, v2=True)
    first4 = n1 + n2 + n3
    n_open = len(a.cells)
    a.begin_rd4(first4, "lines")
    live: List[Dict[str, Any]] = []
    for it in range(first4, first4 + 120):
        cell = a.dispatch(it, 0)
        live.append({"it": it, "cell": cell.id, "seen": cell.seen, "chosen": cell.chosen - 1})            # `chosen` was incremented by the dispatch itself
        a.ingest(t2.synth_result(a, cell, it, rng, v2=True))
    aud = s4.audit4(a, "lines", collect_rows_from=first4)
    check(aud["ok"], f"audit: {aud['problems']}")
    rows = aud["dispatch_rows"]
    check([(r["it"], r["cell"], r["seen"], r["chosen"]) for r in rows] == [(r["it"], r["cell"], r["seen"], r["chosen"]) for r in live], "the audit's rows equal what a live driver saw at each dispatch")
    check(all(r["created_in"] in ("rd1", "rd2", "rd3", "rd4") for r in rows) and all(set(r) >= {"it", "cell", "seen", "chosen", "L", "level", "res", "floor", "x", "y", "created_it", "created_in", "key"} for r in rows),
          "each row carries what the readings need")
    allrows = s4.audit4(a, "lines", collect_rows_from=0)["dispatch_rows"]
    check(len(allrows) == n1 + n2 + n3 + 120 and [r["it"] for r in allrows] == sorted(r["it"] for r in allrows), "rows for every dispatch of every part when asked")
    mi = rpt4.mechanism_inputs(a, rows, first4, n_open)
    ret = rpt4.returns_by_iteration(a, first4)
    check(mi["returns"] == len(ret) == 120 and mi["seen_ge_8"] == sum(1 for r in live if r["seen"] >= 8) and mi["new_cells"] == len(a.cells) - n_open, f"mechanism inputs: {mi}")
    # a dispatch without an ingestion (an aborted job) is not a return and is not counted
    a2 = copy.deepcopy(a)
    a2.dispatch(first4 + 500, 0)
    mi2 = rpt4.mechanism_inputs(a2, rows + [dict(rows[-1], it=first4 + 500, seen=50)], first4, n_open)
    check(mi2 == mi, "a dispatch that was never ingested is not a return")
    # rule inputs carry the mechanism inputs and equal rd3's counts otherwise
    ins = rpt4.rule_inputs4(a, rows, first4, n_open)
    check(ins["returns"] == 120 and ins["seen_ge_8"] == mi["seen_ge_8"] and ins["new_cells"] == mi["new_cells"] and set(ins) >= {"below_floor", "dispatches", "fatal_returns", "launch_capable_created", "bound_violations", "top_level_median_L"},
          f"rule inputs: {sorted(ins)}")
    return {"seen_ge_8": mi["seen_ge_8"], "new_cells": mi["new_cells"]}


# -- the rule, the identity samples, the readings ---------------------------------------------------------------------------------------------------------


def unit_rule4_module() -> Dict[str, Any]:
    check(rule4.self_test() == [], "the rule's self-test")
    d = rule4.rule_digest()
    check(d == rule4.rule_digest() and len(d) == 64, "the rule digest")
    desc = rule4.rule_description()
    check(desc["control_arm"] is False and set(desc["stops"]) == set(rule4.STOPS) == {"S3", "S5", "S7"} and desc["order"] == ["INVALID", "INCOMPLETE", "PROGRESS", "NO_NEW_MILESTONE"],
          "no control arm, three carried stops, four outcomes")
    check(rule4.PROGRESS_MIN_M == 2 and rule4.LADDER == ("none", "L0", "crossing", "left_target", "clear"), "the registered progress threshold")
    check(rule4.MIN_EXPLORATION_TICKS == 2_000_000 and rule4.MAX_LIFECYCLE_FAILURES == 3 and rule4.TOP_LEVEL_MEDIAN_L_LIMIT == 3000, "the carried-over limits")
    check(rule4.SEEN_MIN == 8 and rule4.SEEN_SHARE_MAX_PER_MILLE == 450 and rule4.NEW_CELLS_MIN_PER_100_RETURNS == 174, "the registered mechanism thresholds")
    check("no guard" in json.dumps(desc["dilution"]) and desc["mechanism"]["exact"] == "integer arithmetic", "dilution is report-only; the mechanism check is exact")
    prior = {"rd1": {"m": 0}, "rd2": {"m": 1}, "rd3": {"m": 0}}
    kw = dict(invalid=[], incomplete=[], t=7, prior=prior, returns=100, seen_ge_8=10, new_cells=300, below_floor=0, dispatches=100, fatal_returns=0, launch_capable_created=10)
    r = rule4.apply(m=0, **kw)
    check(r["outcome"] == "NO_NEW_MILESTONE" and r["line"]["status"] == "RD5_LAST_SESSION" and r["highest_milestone"] == "none", f"no milestone: {r['outcome']} {r['line']['status']}")
    r = rule4.apply(m=2, **kw)
    check(r["outcome"] == "PROGRESS" and r["progress_basis"] == ["milestone:crossing"] and r["line"]["status"] == "MILESTONE_VERIFIED" and "rd5 may be proposed" in r["next"], f"a crossing: {r['outcome']}")
    return {"rule_digest": d[:12]}


def unit_identity_samples4() -> Dict[str, Any]:
    a = synth_archive4("is4", 50, 50, 40, 40, floor_min=-2100.0)
    s = run4.identity_sample_open(a, 16)
    ids = [c.id for c in s["cells"]]
    check(len(ids) == 16 and len(set(ids)) == 16 and 0 not in ids, f"sixteen distinct non-root cells: {len(ids)}")
    names = s["names"]
    check(names.count("highest_weight") <= 4 and names.count("keyed_launch_or_a2_high") <= 4 and names.count("keyed_eligible") <= 5, f"pool sizes: {names}")
    pr = a.probabilities()
    check(pr == a.probabilities("v3"), "the open sample reads the CURRENT (v3) probabilities")
    best = [cid for cid in sorted(pr, key=lambda i: (-pr[i], i)) if cid != 0][:4]
    check(all(b in ids for b in best), "the four highest-weight eligible cells are in the sample")
    check(s["cells"] == run4.identity_sample_open(a, 16)["cells"], "the open sample is a pure function of the archive")
    for lv in sorted({c.level for c in a.cells if c.id}, reverse=True)[:3]:
        short = min((c for c in a.cells if c.id and c.level == lv), key=lambda c: (c.L, c.id))
        check(short.id in ids, f"the shortest cell of level {lv} is in the sample")
    sc = run4.identity_sample_close(a, 16)
    check(len(sc["cells"]) == 16 and len({c.id for c in sc["cells"]}) == 16, "the close sample")
    check(run4.identity_sample_close(a, 16)["cells"] == sc["cells"], "the close sample is deterministic")
    check(sc["cells"] != s["cells"], "and a different keyed sample from the open one")
    o3, c3 = run3.identity_sample_open(a, 16), run3.identity_sample_close(a, 16)
    check([c.id for c in o3["cells"]] != ids and [c.id for c in c3["cells"]] != [c.id for c in sc["cells"]], "rd4's samples are keyed differently from rd3's")
    k4 = hashlib.sha256(f"m8_rd|{a.archive_id}|identity_open|rd4|5".encode()).digest()
    check(run4._kh(a, "identity_open|rd4", a.cells[5]) == k4, "the identity key string")
    small = fresh4("small")
    small.begin_v2(5, "L")
    small.begin_rd3(6, "L")
    small.begin_rd4(7, "L")
    check(run4.identity_sample_open(small, 16)["cells"] == [] and run4.identity_sample_close(small, 16)["cells"] == [], "an archive with only cell 0 has no sample")
    check(run4.OPEN_IDENTITY_BASE != run3.OPEN_IDENTITY_BASE and run4.CLOSE_IDENTITY_BASE != run3.CLOSE_IDENTITY_BASE, "rd4's identity iteration numbers are its own")
    return {"open_names": names}


def unit_report_readings() -> Dict[str, Any]:
    """The additional readings of decision 9, exactly, on hand-built rows."""
    def row(it: int, seen: int, created_in: str, x: float, y: float, res: str = "A2", floor: int = -1) -> Dict[str, Any]:
        return {"it": it, "cell": it, "seen": seen, "chosen": 0, "L": 100, "level": 7, "res": res, "floor": floor, "key": [0, 0, res, 1023, floor], "x": x, "y": y, "created_it": 0,
                "created_in": created_in, "terminal": False}

    rows = [row(1, 0, "rd1", 0.0, 0.0), row(2, 1, "rd2", 100.0, 0.0), row(3, 2, "rd3", -1700.0, 500.0), row(4, 3, "rd4", -1900.0, 500.0), row(5, 7, "rd4", -2200.0, 3000.0),
            row(6, 8, "rd4", -2500.0, 2000.0), row(7, 15, "rd3", -1500.0, 3000.0, "G", 0), row(8, 16, "rd2", 0.0, 0.0), row(9, 63, "rd1", -3000.0, 100.0), row(10, 64, "rd4", 0.0, 0.0),
            row(11, 500, "rd4", -1200.0, 3000.0, "G", 0)]
    sd = rpt4.seen_distribution(rows)
    check([sd[k]["dispatches"] for k in ("0-1", "2-3", "4-7", "8-15", "16-31", "32-63", "64+")] == [2, 2, 1, 2, 1, 1, 2], f"the seen buckets: {sd}")
    check(sd["seen_ge_8"] == {"dispatches": 6, "share": 6 / 11} and abs(sd["0-1"]["share"] - 2 / 11) < 1e-12, "seen >= 8 and the shares")
    yields = {1: 5, 2: 3, 3: 4, 4: 2, 5: 1, 6: 0, 7: 0, 8: 1, 9: 0, 10: 0, 11: 0}
    returned = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 8: 0, 9: 0, 10: 0, 11: 0}                     # iteration 7 was never ingested
    sy = rpt4.seen_distribution(rows, yields, returned)
    check(sy["0-1"]["returns"] == 2 and sy["0-1"]["new_cells_per_return"] == 4.0 and sy["8-15"]["returns"] == 1 and sy["8-15"]["new_cells_per_return"] == 0.0, f"new cells per return by class: {sy['8-15']}")
    cs = rpt4.creation_shares(rows)
    check({k: v["dispatches"] for k, v in cs.items()} == {"rd1": 2, "rd2": 2, "rd3": 2, "rd4": 5} and abs(cs["rd4"]["share"] - 5 / 11) < 1e-12, f"the share of returns by start-cell session of creation: {cs}")
    fr = rpt4.frontier_returns(rows)
    check(fr["left_of_wall_x_lt_-2100"]["dispatches"] == 3 and fr["left_of_wall_x_lt_-1800"]["dispatches"] == 4 and fr["left_of_wall_x_lt_-1650"]["dispatches"] == 5 and fr["wall_top_cells"]["dispatches"] == 2
          and fr["dispatches"] == 11, f"returns to left-of-wall and wall-top cells: {fr}")
    check(rpt4.bucket_name(0, 1) == "0-1" and rpt4.bucket_name(64, None) == "64+" and rpt4.bucket_name(5, 5) == "5", "bucket names")
    empty = rpt4.seen_distribution([])
    check(empty["seen_ge_8"] == {"dispatches": 0, "share": None} and rpt4.frontier_returns([])["wall_top_cells"]["share"] is None, "empty rows: no share")
    a = synth_archive4("rr", 20, 20, 20, 20)
    by = rpt4.session_rows(s4.audit4(a, "lines", collect_rows_from=0)["dispatch_rows"], a)
    check({k: len(v) for k, v in by.items()} == {"rd1": 20, "rd2": 20, "rd3": 20, "rd4": 20} and all(a.session_of_iteration(r["it"]) == k for k, v in by.items() for r in v), "rows grouped by the dispatching session")
    y = rpt4.new_cells_by_iteration(a)
    check(sum(y.values()) == sum(1 for b in a.bursts for w in b.wins if int(w["a"]) == march.ACTION_NEW) and set(y) == {b.iteration for b in a.bursts}, "new cells by iteration")
    return {"rows": len(rows)}


# -- claim-path safety (decision 6) -------------------------------------------------------------------------------------------------------------------------


def trace_entry_landing(trace: Mapping[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    """The consumed ticks of the first over-wall entry (a live step entering x < -2,100 from the right at y >= 600, the stub analyser's rule) and of the first grounded tick on floor line 3 after it."""
    prev = (float(trace["initial"]["observation"]["position_x"]), float(trace["initial"]["observation"]["position_y"]))
    entry: Optional[int] = None
    land: Optional[int] = None
    for i, r in enumerate(trace["steps"]):
        o, sp = r["observation"], r["spatial"]
        x, y = float(o["position_x"]), float(o["position_y"])
        if prev[0] >= -2100.0 > x and entry is None and y >= 600.0:
            entry = i
        if entry is not None and land is None and int(o["ground_air_state"]) == 0 and int(sp["fighter"]["floor_line_id"]) == 3 and x < -2100.0:
            land = i
        prev = (x, y)
    return entry, land


def scan_labels(trace: Mapping[str, Any], prefix_len: int) -> Tuple[Dict[str, Any], List[Tuple[int, int]]]:
    """What the worker hands the ledger for one job: the burst scanner's labels over the POST-prefix part (absolute input ticks) and the break table of the whole trajectory."""
    steps = trace["steps"]
    start_mask = int(steps[prefix_len - 1]["spatial"]["target_live_mask"]) if prefix_len > 0 else int(trace["initial"]["spatial"]["target_live_mask"])
    sc = mcell.BurstScanner(start_mask)
    for r in steps[prefix_len:]:
        sc.feed(int(r["observation"]["input_tick"]), r["observation"], r["spatial"], int(r["state"]))
    whole = mcell.BurstScanner(int(trace["initial"]["spatial"]["target_live_mask"]))
    for r in steps:
        whole.feed(int(r["observation"]["input_tick"]), r["observation"], r["spatial"], int(r["state"]))
    return sc.labels(), list(whole.breaks)


def keyed_burst(draw: str, n: int, length: int = 120) -> bytes:
    return bytes(mx.words(lambda i: mx.explore_key(draw, n, i), length))


def scenario_ok(kind: str, world: str, a: s4.Archive4, c: march.Cell, burst: bytes) -> bool:
    """Whether a burst from an inherited cell is the claim case `kind`: a CROSSING (the over-wall entry lies in the inherited prefix, the landing on the left floor in the burst), a LEFT CONTINUATION
    that does not land and breaks nothing (an unqualified entry's continuation), or a WALL-TOP CONTINUATION (the burst's first tick is still on floor line 0)."""
    pre = a.cell_words(c)
    tr = stub.replay_trace(world, pre + burst)
    L = len(pre)
    if len(tr["steps"]) < L + 1:
        return False
    labels, _b = scan_labels(tr, L)
    if kind == "cross":
        e, l = trace_entry_landing(tr)
        return e is not None and l is not None and e < L < l and labels["first"]["left_live"] == L + 1
    if kind == "left_nolanding":
        f = labels["first"]
        return f["left_live"] == L + 1 and f["left_floor"] is None and f["left_break"] is None and f["clear"] is None
    if kind == "wall_continuation":
        f = labels["first"]
        return f["l0"] == L + 1
    raise ValueError(kind)


def inherited_cells(a: s4.Archive4, kind: str) -> List[march.Cell]:
    if kind in ("cross", "left_nolanding"):
        return [c for c in a.cells if float(c.end[mcell.I_X]) < mcell.LEFT_BOUNDARY_X and c.key[2] != mcell.RES_GROUNDED and not c.terminal]
    return [c for c in a.cells if c.key[2] == mcell.RES_GROUNDED and c.key[4] == mcell.L0_FLOOR_LINE]


def find_burst(world: str, a: s4.Archive4, kind: str, draw: str = "claims4", limit: int = 4000) -> Tuple[march.Cell, int, bytes]:
    """(an inherited start cell, n, the keyed burst) for a claim case, searched deterministically over the cells and the keyed streams (component-level tests)."""
    for n in range(limit):
        for c in inherited_cells(a, kind):
            burst = keyed_burst(draw, n)
            if scenario_ok(kind, world, a, c, burst):
                return c, n, burst
    raise Failure(f"no burst of the claim case {kind!r} found in {limit} keyed streams over {len(inherited_cells(a, kind))} inherited cells")


def find_forced_iteration(a: s4.Archive4, world: str, kind: str, start: int, limit: int = 60000) -> Tuple[int, march.Cell]:
    """The first iteration number n >= start whose SELECTION (on the archive as it stands) is an inherited cell for which the keyed burst under rd4's draw id is the claim case `kind`. Skipping
    numbers is allowed by the ledger (strictly increasing), so a session that dispatches n stays auditable: this forces the scenario without touching the selection."""
    ids = {c.id for c in inherited_cells(a, kind)}
    for n in range(start, start + limit):
        c = a.select(n)
        if c.id in ids and not c.terminal:
            burst = bytes(mx.words(lambda i: mx.explore_key(a.draw_for(n), n, i), min(mx.BURST_WORDS, mcell.HORIZON - c.L)))
            if scenario_ok(kind, world, a, c, burst):
                return n, c
    raise Failure(f"no iteration found for the claim case {kind!r}")


def forced_session_cls(world: str, kinds: Sequence[str], base: Any = None) -> Any:
    """A Session4 whose first dispatches are the claim cases `kinds`, in order (each at an iteration whose SELECTION is the wanted inherited cell). Test hook only."""
    base = base or run4.Session4

    class ForcedSession4(base):                                                                                  # type: ignore[valid-type, misc]
        def __init__(self, *a: Any, **k: Any) -> None:
            super().__init__(*a, **k)
            self.forced: List[Dict[str, Any]] = []

        def make_job(self, arm: str, w: int, remaining: int) -> Dict[str, Any]:
            if len(self.forced) < len(kinds):
                kind = kinds[len(self.forced)]
                n, c = find_forced_iteration(self.archive, world, kind, self.iteration)
                self.iteration = n
                self.forced.append({"kind": kind, "iteration": n, "cell": c.id, "L": c.L})
            return super().make_job(arm, w, remaining)

    return ForcedSession4


def candidate_for_iteration(sess: Any, iteration: int, kind: str) -> Optional[Dict[str, Any]]:
    return next((c for c in sess.ledgers["T"].candidates if c["iteration"] == iteration and c["kind"] == kind), None)


def fake_rep(cid: int, **flags: Any) -> Dict[str, Any]:
    out = {"cid": cid, "exact": True, "kind": "left", "l0": False, "crossing": False, "left_target": False, "clear": False, "t": 0, "problems": []}
    out.update(flags)
    return out


def ledger_with(specs: Sequence[Mapping[str, Any]]) -> mclaims.ArmLedger:
    """A frozen-engine ledger holding one job per spec: `first` events (left_live / left_floor / left_break / clear), optional t events."""
    led = mclaims.ArmLedger("T")
    for k, sp in enumerate(specs):
        cb = led.commit(100)
        first = {"l0": None, "left_live": None, "left_floor": None, "left_break": None, "clear": None}
        first.update(sp.get("first") or {})
        labels = {"t": sp.get("t", 3), "breaks": [], "t_events": list(sp.get("t_events") or []), "first": first}
        led.register(cum_before=cb, iteration=1000 + k, words=bytes([k % 72]) * 60, prefix_len=30, labels=labels, breaks=[], end_reason="length", t_end=sp.get("t", 3))
    return led


def unit_claims_pools_and_plan() -> Dict[str, Any]:
    check(cl4.INFO_REPLAY_MAX == 6 and cl4.POOL_ORDER == ("clear", "left_target", "crossing") and cl4.RAISE_EVENT == {"crossing": "left_floor", "left_target": "left_break", "clear": "clear"}, "registered constants")
    check(len(cl4.contract_digest()) == 64 and cl4.contract_digest() == cl4.contract_digest() and cl4.CLAIMS4_CONTRACT == "m8_rd4_claims_v1", "the claims contract digest")
    live = {"left_live": 31}
    land = {"left_live": 31, "left_floor": 40}
    brk = {"left_live": 31, "left_break": 35}
    both = {"left_live": 31, "left_floor": 45, "left_break": 36}
    clr = {"left_live": 31, "left_break": 35, "clear": 59}
    led = ledger_with([{"first": live}] * 40 + [{"first": land}, {"first": brk}])
    cands = {c["cid"]: c for c in led.candidates}
    check(all(cl4.is_descriptive(c) for c in cands.values() if c["first"] == live) and cl4.raises(cands[40]) == ["crossing"] and cl4.raises(cands[41]) == ["left_target"], "what each candidate can raise")
    check(cl4.raises(ledger_with([{"first": both}]).candidates[0]) == ["left_target", "crossing"], "a candidate with both events can raise both")
    kinds = {k: [c for c in ledger_with([{"first": clr}]).candidates if c["kind"] == k] for k in ("left", "clear")}
    check(set(cl4.raises(kinds["clear"][0])) == {"clear", "left_target"}, "a clear candidate can raise the clear")
    ps = cl4.pool_sizes(led, led.ticks)
    check(ps["left"] == 42 and ps["descriptive"] == 40 and ps["can_raise"] == {"clear": 0, "left_target": 1, "crossing": 1} and ps["t"] == 0 and ps["l0"] == 0, f"pool sizes: {ps}")
    # the flood: 40 descriptive candidates came first in discovery order; the can-raise ones (last) are replayed FIRST
    done: Dict[int, Dict[str, Any]] = {}
    todo, info = cl4.plan_replays4(led, led.ticks, done, batch=3)
    check(sorted(c["cid"] for c, _n in todo) == [40, 41], f"the can-raise candidates are replayed first and alone: {[c['cid'] for c, _n in todo]}")
    check(info["remaining"] == {"clear": 0, "left_target": 1, "crossing": 1} and cl4.max_m_unverified(info) == 3, f"remaining can-raise candidates: {info['remaining']}")
    for c, _n in todo:
        done[c["cid"]] = fake_rep(c["cid"])
    # every pool is now empty: only then the descriptive ones, at most INFO_REPLAY_MAX of them in total, in discovery order
    taken: List[int] = []
    for _round in range(6):
        todo, info = cl4.plan_replays4(led, led.ticks, done, batch=3)
        if not todo:
            break
        taken += [c["cid"] for c, _n in todo]
        for c, _n in todo:
            check(cl4.is_descriptive(c), "only descriptive entries are planned once the pools are empty")
            done[c["cid"]] = fake_rep(c["cid"])
    check(taken == list(range(6)) and info["descriptive_total"] == 40 and info["descriptive_replayed"] == 6 and info["descriptive_allowance"] == 6, f"six descriptive replays, in discovery order: {taken}")
    check(cl4.max_m_unverified(info) == 0, "unreplayed descriptive entries never count as 'could raise m'")
    # a candidate that is the LAST of hundreds is still verified: the flood cannot starve it
    flood = ledger_with([{"first": live}] * 300 + [{"first": land}])
    todo, _info = cl4.plan_replays4(flood, flood.ticks, {}, batch=3)
    check([c["cid"] for c, _n in todo] == [300], "a can-raise candidate after 300 descriptive ones is the only first replay")
    # satisfied milestones leave their pool: a verified crossing empties the crossing pool, the left-target pool stays
    led2 = ledger_with([{"first": land}, {"first": land}, {"first": brk}, {"first": clr}])
    done2 = {0: fake_rep(0, crossing=True)}
    todo, info = cl4.plan_replays4(led2, led2.ticks, done2, batch=9)
    check(info["satisfied"] == {"clear": False, "left_target": False, "crossing": True} and info["remaining"]["crossing"] == 0 and info["remaining"]["left_target"] >= 2, f"a verified crossing: {info}")
    check(1 not in [c["cid"] for c, _n in todo], "a second landing candidate is not replayed once the crossing is verified (it cannot raise m above the crossing)")
    check(cl4.max_m_unverified(info) >= 3, "but a left target or a clear could still raise m")
    # round-robin over the unsatisfied milestones, the maximum-targets candidate first
    led3 = ledger_with([{"first": live, "t": 4, "t_events": [(40, 4)]}, {"first": land}, {"first": brk}, {"first": clr}])
    todo, info = cl4.plan_replays4(led3, led3.ticks, {}, batch=4)
    kinds_ = [(c["kind"], c["cid"]) for c, _n in todo]
    check(kinds_[0][0] == "t" and info["t"] == 4, f"the maximum-targets candidate first: {kinds_}")
    check(len(todo) == len({c['cid'] for c, _n in todo}), "no candidate is planned twice")
    # nothing registered: nothing to plan
    check(cl4.plan_replays4(mclaims.ArmLedger("T"), 0, {}, batch=3)[0] == [], "an empty ledger plans nothing")
    # the l0 kind is never planned (the wall-top landing is rd2's)
    led4 = ledger_with([{"first": {"l0": 31}}])
    check(led4.l0_cid is not None and cl4.plan_replays4(led4, led4.ticks, {}, batch=3)[0] == [], "an l0 candidate is never replayed in rd4")
    return {"pools": ps["can_raise"]}


def unit_claim_cases_on_stub_traces() -> Dict[str, Any]:
    """Decision 6 at component level, with the registered analyser stand-in on real stub traces: the candidate registry, the replay plan, the exactness checks and the milestone credit for (a) a
    crossing whose ENTRY lies in an inherited prefix and whose LANDING lies in a new burst, (b) the continuation of an inherited left-of-wall cell that never lands, (c) the continuation of an
    inherited wall-top cell. None may be a false INVALID; (a) must be credited."""
    chain = build_chain4()
    world = chain["world"]
    a, _meta = s4.Archive4.read_dir(chain["rd3"] / "archive")
    # (a) the crossing
    c, n, burst = find_burst(world, a, "cross")
    pre = a.cell_words(c)
    L = len(pre)
    words = pre + burst
    tr = stub.replay_trace(world, words)
    e, l = trace_entry_landing(tr)
    check(e is not None and e < L < l, f"the entry ({e}) lies in the inherited prefix (length {L}) and the landing ({l}) in the new burst")
    labels, breaks = scan_labels(tr, L)
    f = labels["first"]
    check(f["left_floor"] == l + 1 and f["left_live"] == L + 1, f"the scanner over the post-prefix part: the landing is the burst's event, the left presence (a live step left of the wall at its first tick) is inherited: {f}")
    led = mclaims.ArmLedger("T")
    cb = led.commit(L + len(burst))
    led.register(cum_before=cb, iteration=7, words=words, prefix_len=L, labels=labels, breaks=breaks, end_reason="length", t_end=labels["t"])
    cand = next(x for x in led.candidates if x["kind"] == "left")
    check(cl4.raises(cand) == ["left_target", "crossing"] if f["left_break"] is not None else cl4.raises(cand) == ["crossing"], f"a can-raise candidate: {cl4.raises(cand)}")
    todo, info = cl4.plan_replays4(led, led.ticks, {}, batch=3)
    check(cand["cid"] in [x["cid"] for x, _n in todo], "the plan replays it")
    rep = mclaims.evaluate_replay(tr, cand, len(words), stub.analyse)
    check(rep["exact"] and not rep["problems"], f"an exact replay, no false INVALID: {rep['problems']}")
    check(rep["crossing"] and rep["first_qualified_entry"] == e and rep["first_qualified_entry"] < L, f"the crossing is credited with its entry in the inherited prefix: {rep['first_qualified_entry']} < {L}")
    check(rpt4.replay_verified_m([rep]) >= 2 and mclaims.milestone_level([rep]) >= 2, "m counts it")
    # the same candidate cut before its landing: exact, not credited, never INVALID
    stop = min(f[k] for k in ("left_floor", "left_break") if f[k] is not None)         # the burst's first event that could raise m (the landing, or a left-target break before it)
    cut = words[:stop - 1]                                                      # the same trajectory, cut one tick before it
    tr_cut = stub.replay_trace(world, cut)
    labels_c, breaks_c = scan_labels(tr_cut, L)
    led_c = mclaims.ArmLedger("T")
    led_c.register(cum_before=led_c.commit(len(cut)), iteration=8, words=cut, prefix_len=L, labels=labels_c, breaks=breaks_c, end_reason="cut", t_end=labels_c["t"])
    cand_c = next(x for x in led_c.candidates if x["kind"] == "left")
    check(cl4.is_descriptive(cand_c) and {k: v for k, v in cand_c["first"].items() if k != "l0"} == {"left_live": L + 1}, f"a burst cut before its first can-raise event carries only the inherited left presence: descriptive {cand_c['first']}")
    rep_c = mclaims.evaluate_replay(tr_cut, cand_c, len(cut), stub.analyse)
    check(rep_c["exact"] and not rep_c["crossing"] and rpt4.replay_verified_m([rep_c]) == 0, f"exact, not credited: {rep_c['problems']} {rep_c['crossing']}")
    # (b) the continuation of an inherited left cell that never lands
    cb_, nb_, burst_b = find_burst(world, a, "left_nolanding", draw="claims4b")
    pre_b = a.cell_words(cb_)
    words_b = pre_b + burst_b
    tr_b = stub.replay_trace(world, words_b)
    labels_b, breaks_b = scan_labels(tr_b, len(pre_b))
    led_b = mclaims.ArmLedger("T")
    led_b.register(cum_before=led_b.commit(len(words_b)), iteration=9, words=words_b, prefix_len=len(pre_b), labels=labels_b, breaks=breaks_b, end_reason="length", t_end=labels_b["t"])
    cand_b = next(x for x in led_b.candidates if x["kind"] == "left")
    check(cand_b["first"].get("left_live") == len(pre_b) + 1 and cl4.is_descriptive(cand_b), "the continuation carries its inherited left presence (a live step at its first tick) and is descriptive")
    rep_b = mclaims.evaluate_replay(tr_b, cand_b, len(words_b), stub.analyse)
    check(rep_b["exact"] and not rep_b["problems"] and not rep_b["crossing"], f"a continuation from an inherited left-of-wall prefix is exact and is not a false INVALID: {rep_b['problems']}")
    todo_b, info_b = cl4.plan_replays4(led_b, led_b.ticks, {}, batch=3)
    check([x["cid"] for x, _n in todo_b] == [cand_b["cid"]] and cl4.max_m_unverified(info_b) == 0, "it is replayed as a descriptive fact, and it can never make a session INCOMPLETE")
    # (c) the continuation of an inherited wall-top cell
    cw, nw, burst_w = find_burst(world, a, "wall_continuation", draw="claims4c")
    pre_w = a.cell_words(cw)
    words_w = pre_w + burst_w
    tr_w = stub.replay_trace(world, words_w)
    labels_w, breaks_w = scan_labels(tr_w, len(pre_w))
    check(labels_w["first"]["l0"] == len(pre_w) + 1, "the burst's first tick is still on floor line 0")
    led_w = mclaims.ArmLedger("T")
    led_w.register(cum_before=led_w.commit(len(words_w)), iteration=10, words=words_w, prefix_len=len(pre_w), labels=labels_w, breaks=breaks_w, end_reason="length", t_end=labels_w["t"])
    check(led_w.l0_cid is not None, "unsuppressed, the frozen ledger registers an l0 candidate")
    l0c = led_w.candidates[led_w.l0_cid]
    rep_l0 = mclaims.evaluate_replay(tr_w, l0c, len(l0c["words"]), stub.analyse)
    check(not rep_l0["exact"] and any("first wall-top landing at" in p for p in rep_l0["problems"]), f"the frozen engine fails such a candidate (the hazard): {rep_l0['problems']}")
    check(cl4.plan_replays4(led_w, led_w.ticks, {}, batch=3)[0] == [] or all(x["kind"] != "l0" for x, _n in cl4.plan_replays4(led_w, led_w.ticks, {}, batch=3)[0]), "rd4's plan never replays an l0 candidate")
    res = {"iteration": 10, "cell": cw.id, "L": len(pre_w), "labels": labels_w}
    supp, sighting = run4.suppress_wall_top_label(res, True)
    check(supp["labels"]["first"]["l0"] is None and sighting["start_cell_on_wall_top"] and sighting["first_tick_of_the_burst"], f"suppressed, with the sighting recorded: {sighting}")
    led_s = mclaims.ArmLedger("T")
    led_s.register(cum_before=led_s.commit(len(words_w)), iteration=10, words=words_w, prefix_len=len(pre_w), labels=supp["labels"], breaks=breaks_w, end_reason="length", t_end=labels_w["t"])
    check(led_s.l0_cid is None, "suppressed, there is no l0 candidate to fail")
    # the wall-top landing is never part of rd4's m: a replay's l0 flag (read over the whole trajectory) is ignored
    check(rpt4.replay_verified_m([fake_rep(0, l0=True)]) == 0, "a replay that stands on floor line 0 credits no level in rd4")
    return {"entry": e, "landing": l, "prefix": L}


# -- the resume protocol on a synthetic chain ---------------------------------------------------------------------------------------------------------


def open4(cp: Mapping[str, Any], *, expect3: Optional[Mapping[str, Any]] = None, live: Optional[Callable[[], Mapping[str, Any]]] = None, **kw: Any) -> Dict[str, Any]:
    return ses4.open_protocol4(cp["rd1"], cp["rd2"], cp["rd3"], cp["inc1"], cp["inc2"], cp["inc3"], expect1=cp["expect1"], expect2=cp["expect2"], expect3=expect3 if expect3 is not None else cp["expect3"],
                               check_overlay=False, live_pins=live or (lambda: t3.live_pins_of(cp)), floor_min=FLOOR_MIN, **kw)


def unit_resume_three_level_synthetic() -> Dict[str, Any]:
    chain = build_chain4()
    e3 = chain["expect3"]
    check(chain["rd3_outcome"] in rule3.OUTCOMES and e3["dispatch_iterations"][0] == 0 and e3["first_rd3_iteration"] == chain["expect2"]["dispatch_iterations"][1] + 1, "the synthetic chain")
    check(e3["inherited"]["grounded_cells_on_left_floor"] == 0 and e3["inherited"]["cells_with_a_left_target_broken"] == 0 and e3["inherited"]["wall_top_cell_ids"]
          and e3["inherited"]["cells_left_of_boundary"] > 0, f"the chain's inherited frontier: wall-top cells, left-of-wall cells, no milestone: {e3['inherited']}")
    op = open4(chain)
    check(op["ok"], f"the open protocol on a synthetic chain: {op['problems']}")
    check(all(op[f"R1_{w}_immutability"]["ok"] for w in ("rd1", "rd2", "rd3")) and op["R2_R4_rd1_archive"]["ok"] and op["R2_R4_rd2_archive"]["ok"] and op["R2_R4_rd3_archive"]["ok"]
          and not op["R3_pins"]["problems"] and not op["R3_pins"]["rd2_problems"] and not op["R3_pins"]["rd1_problems"] and op["R5_overlay"]["ok"] and op["R5_overlay"]["stored_close_counts_equal"], "R1-R5")
    f3 = op["facts3"]
    check(f3["first_rd4_iteration"] == e3["dispatch_iterations"][1] + 1 and f3["rd3_checkpoint_seq"] == e3["checkpoint_seq"] and f3["inherited"] == e3["inherited"], "iterations continue from rd3's last; the inherited facts")
    check([e["name"] for e in f3["session_events"]] == ["rd2", "rd3"] and all(e["digest"] == f3["digest_recomputed"] for e in f3["session_events"]), "rd2's and rd3's session digests equal the v2 digest recomputed")
    check(f3["audit"]["ok"] and f3["prefix_chain"]["ok"], "rd3's own audit (zero ticks) and the prefix chain")
    # R1: any change of any of the three trees is caught, and named by the tree
    for tree in ("rd1", "rd2", "rd3"):
        for what in ("byte", "mtime", "extra", "missing", "increment"):
            cp = copy_chain4(chain)
            root = cp[tree]
            target = root / "archive" / "cells.jsonl"
            if what == "byte":
                st = target.stat()
                raw = target.read_bytes()
                target.write_bytes(raw[:-2] + b"9\n")
                os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns))
            elif what == "mtime":
                os.utime(target, ns=(1, 2))
            elif what == "extra":
                (root / "stray.txt").write_text("x", encoding="utf-8")
            elif what == "missing":
                (root / "sessions" / tree / "state.json").unlink()
            else:
                rec_p = cp[{"rd1": "inc1", "rd2": "inc2", "rd3": "inc3"}[tree]] / "verification.json"
                rec = json.loads(rec_p.read_text(encoding="utf-8"))
                rec["result"] = "FAIL"
                rec_p.write_text(json.dumps(rec), encoding="utf-8")
            op2 = open4(cp)
            check(not op2["ok"] and any(p.startswith(f"R1 ({tree})") for p in op2["problems"]), f"R1 missed a change of {tree}'s tree: {what}: {op2['problems'][:3]}")
            for other in {"rd1", "rd2", "rd3"} - {tree}:
                check(not any(p.startswith(f"R1 ({other})") for p in op2["problems"]), f"R1 blamed {other} for a change of {tree}'s tree")
            shutil.rmtree(cp["t"], ignore_errors=True)
    # R2: wrong registered facts, a tampered close record, wrong counters, a changed pin
    for what, bad in (("cells", dict(e3, cells=e3["cells"] + 1)), ("checkpoint", dict(e3, checkpoint_seq=99)), ("first rd3 iteration", dict(e3, first_rd3_iteration=e3["first_rd3_iteration"] + 1)),
                      ("iterations", dict(e3, dispatch_iterations=(0, e3["dispatch_iterations"][1] + 1))), ("decision", dict(e3, outcome="PROGRESS" if e3["outcome"] != "PROGRESS" else "NO_NEW_MILESTONE")),
                      ("returns", dict(e3, returns=e3["returns"] + 1)), ("ticks", dict(e3, exploration_ticks=e3["exploration_ticks"] + 1)),
                      ("inherited facts", dict(e3, inherited=dict(e3["inherited"], cells_left_of_boundary=e3["inherited"]["cells_left_of_boundary"] + 1)))):
        f = r4.rd3_archive_facts(chain["rd1"], chain["rd2"], chain["rd3"], chain["lines"], bad, with_audit=False)
        check(not f["ok"], f"R2: a wrong {what} is refused")
    cp = copy_chain4(chain)
    close_p = cp["rd3"] / "sessions" / "rd3" / "close.json"
    d = json.loads(close_p.read_text(encoding="utf-8"))
    d["archive"]["manifest"]["cells.jsonl"] = "0" * 64
    close_p.write_text(json.dumps(d), encoding="utf-8")
    check(not r4.rd3_archive_facts(cp["rd1"], cp["rd2"], cp["rd3"], chain["lines"], e3, with_audit=False)["ok"], "R2: the archive must equal rd3's close record")
    d = json.loads(close_p.read_text(encoding="utf-8"))
    d["archive"]["manifest"]["cells.jsonl"] = mw.sha256_file(cp["rd3"] / "archive" / "cells.jsonl")
    d["archive"]["diag2"]["revivals"] += 1
    close_p.write_text(json.dumps(d), encoding="utf-8")
    f = r4.rd3_archive_facts(cp["rd1"], cp["rd2"], cp["rd3"], chain["lines"], e3, with_audit=False)
    check(not f["ok"] and any("diag2" in p for p in f["problems"]), "R2: the counters must equal rd3's close record")
    shutil.rmtree(cp["t"], ignore_errors=True)
    f = r4.rd3_archive_facts(chain["rd1"], chain["rd2"], chain["rd3"], "another line table", e3, with_audit=False)
    check(not f["ok"] and any("digest" in p for p in f["problems"]), "R2: rd2's and rd3's session digests must equal the digest recomputed from the contract and the pinned lines")
    # R3: the pins
    p = chain["pins"]
    live = t3.live_pins_of(chain)
    fz = chain["rd1"] / "archive" / "runtime"
    check(rs.pin_problems(p, live, fz, p["frozen_sha256"]) == [], "R3: equal pins")
    op3 = open4(chain, live=lambda: dict(t3.live_pins_of(chain), executable_sha256="0" * 64))
    check(not op3["ok"] and op3["R3_pins"]["executable_only"] and any("only the executable differs" in x for x in op3["problems"]), "R3: an executable-only difference refuses the exploration session")
    op4 = open4(chain, live=lambda: dict(t3.live_pins_of(chain), flags={"explore": {}, "verify": {}}))
    check(not op4["ok"] and any("R3" in x for x in op4["problems"]), "R3: the flags")
    # R5: the closing overlay of rd3's archive
    ov = r4.closing_overlay(chain["rd3"], expect={}, floor_min=FLOOR_MIN)
    check(ov["ok"] and ov["counts"] == ov["stored_close_counts"] and len(ov["rows"]) == e3["cells"] and "archive" not in ov, f"R5: the closing overlay reproduces rd3's record: {ov['problems']}")
    ov_b = r4.closing_overlay(chain["rd3"], expect={}, floor_min=FLOOR_MIN)
    check(ov["bytes"] == ov_b["bytes"] and ov["sha256"] == ov_b["sha256"], "and is reproducible")
    check(not r4.closing_overlay(chain["rd3"], expect={"cells": ov["counts"]["cells"] + 1}, floor_min=FLOOR_MIN)["ok"], "R5: a registered figure that differs is refused")
    cp = copy_chain4(chain)
    close_p = cp["rd3"] / "sessions" / "rd3" / "close.json"
    d = json.loads(close_p.read_text(encoding="utf-8"))
    d["archive"]["overlay_close"]["union"] += 1
    close_p.write_text(json.dumps(d), encoding="utf-8")
    check(not r4.closing_overlay(cp["rd3"], expect={}, floor_min=FLOOR_MIN)["ok"], "R5: the overlay must equal the counts rd3's close record stores")
    shutil.rmtree(cp["t"], ignore_errors=True)
    # the earlier sessions' recorded milestones, read from their own files, strictly
    pm = r4.prior_milestones(chain["rd1"], chain["rd2"], chain["rd3"])
    r3rec = json.loads((chain["rd3"] / "sessions" / "rd3" / "rule.json").read_text(encoding="utf-8"))
    check(pm["rd3"]["m"] == r3rec["m"] == chain["rd3_m"] and pm["rd3"]["source"] == "sessions/rd3/rule.json" and pm["rd2"]["m"] == chain["rd2_m"] and pm["rd1"] is not None, f"prior milestones: {pm}")
    check(r4.prior_milestones(chain["rd1"], chain["rd2"], chain["t"] / "nowhere")["rd3"] is None, "a missing record is None (and the rule refuses it)")
    cp = copy_chain4(chain)
    p3 = cp["rd3"] / "sessions" / "rd3" / "rule.json"
    dd = json.loads(p3.read_text(encoding="utf-8"))
    del dd["m"]
    p3.write_text(json.dumps(dd), encoding="utf-8")
    raises(KeyError, lambda: r4.prior_milestones(cp["rd1"], cp["rd2"], cp["rd3"]), "a recorded decision without its milestone is refused, never defaulted to zero")
    shutil.rmtree(cp["t"], ignore_errors=True)
    # the claim preconditions: facts that would make an rd4 credit arise from an inherited prefix are refused
    ok_f = r4.inherited_claim_facts(s4.Archive4.read_dir(chain["rd3"] / "archive")[0])
    check(r4.claim_precondition_problems(ok_f) == [], "the synthetic chain's inherited archive meets the preconditions")
    check(len(r4.claim_precondition_problems(dict(ok_f, grounded_cells_on_left_floor=2))) == 1 and len(r4.claim_precondition_problems(dict(ok_f, cells_with_a_left_target_broken=1, max_level=8))) == 2,
          "an inherited landing on the left floor, a broken left target or a level above seven is refused")
    # R6: materialise
    t = tmpdir("m8mat4_")
    root4 = t / "rd4"
    a4 = r4.materialise4(chain["rd3"], root4, facts=op["facts3"], overlay=op["overlay"], lines_sha256=chain["lines"], meta_extra={"pins": p, "pin_tick0": op["facts3"]["pin_tick0"], "ticks": {}, "ledger_T": {}},
                         increment_manifest_sha256="x" * 64, utc="2026-10-03T00:00:00Z", floor_min=FLOOR_MIN)
    check(a4.mode == 2 and a4.rd4_first_iteration == e3["dispatch_iterations"][1] + 1 and a4.first_iteration == a4.rd4_first_iteration and a4.draw_id == a4.draw_id_rd4, "materialised: mode 2, rd4 begun, iterations continue")
    for n in (*march.DATA_FILES, march.MANIFEST):
        check(mw.sha256_file(root4 / "base" / n) == mw.sha256_file(chain["rd3"] / "archive" / n), f"the base copy of {n} is byte-identical to rd3's closing file")
    check(mw.sha256_file(root4 / "derived" / "open_overlay.jsonl") == op["overlay"]["sha256"], "the stored overlay hashes to its digest")
    ob = json.loads((root4 / "derived" / "open_overlay.json").read_text(encoding="utf-8"))
    check(ob["sha256"] == op["overlay"]["sha256"] and ob["computed_twice_equal"], "the overlay record")
    base = json.loads((root4 / "derived" / "base.json").read_text(encoding="utf-8"))
    check(base["session_event"]["name"] == "rd4" and base["session_event"]["select"] == "m8_rd_select_v3" and base["rd3_increment_manifest_sha256"] == "x" * 64 and base["overlay_sha256"] == op["overlay"]["sha256"]
          and base["rd3_close_record_sha256"] == op["facts3"]["close_record_sha256"] and base["inherited"] == e3["inherited"], "the base record")
    d, meta, rep = march.load_latest_verified(root4 / "archive")
    check(d is not None and meta["checkpoint_seq"] == e3["checkpoint_seq"] + 1 and meta["schema"] == s2.ARCHIVE_SCHEMA_V2 and meta["why"] == "open", "the first rd4 checkpoint")
    check(r4.prefix_chain(chain["rd1"] / "archive", chain["rd2"] / "archive", chain["rd3"] / "archive", root4 / "archive")["ok"], "the prefix chain rd1 -> rd2 -> rd3 -> rd4 holds at the open")
    loaded, _m = s4.Archive4.read_dir(root4 / "archive")
    check(s4.audit4(loaded, chain["lines"])["ok"], "the materialised archive audits (four parts, no rd4 dispatch yet)")
    raises(r4.Resume4Error, lambda: r4.materialise4(chain["rd3"], root4, facts=op["facts3"], overlay=op["overlay"], lines_sha256=chain["lines"], meta_extra={}, increment_manifest_sha256="x", utc="u"),
           "an existing rd4 root is never overwritten")
    check(all_immutability(chain)["ok"], "all three earlier trees are still equal to their increments after the open")
    shutil.rmtree(t, ignore_errors=True)
    return {"cells": len(a4.cells)}


def unit_precondition_refuses_inherited_milestones() -> Dict[str, Any]:
    """A chain whose rd3 tree already holds a landing on the left floor and broken left targets (the hard stub world finds them) is refused at the open: the claim guard's precondition."""
    chain = build_chain4("hard", rd1_caps=(30000, 24000), rd2_ticks=12000, rd3_ticks=12000, cache=False)
    try:
        inh = chain["expect3"]["inherited"]
        check(inh["grounded_cells_on_left_floor"] > 0 and inh["cells_with_a_left_target_broken"] > 0, f"the hard chain holds inherited milestones: {inh}")
        op = open4(chain)
        check(not op["ok"] and any("stand on the left floor" in p for p in op["problems"]) and any("left target broken" in p for p in op["problems"]), f"refused for the inherited milestones: {op['problems']}")
        check(not any("R2/R4 (rd3): the inherited claim facts" in p for p in op["problems"]), "the registered inherited facts themselves were consistent: only the precondition refused")
    finally:
        shutil.rmtree(chain["t"], ignore_errors=True)
    return {}


# -- the session on a synthetic chain (deterministic engine) -------------------------------------------------------------------------------------------


def unit_session4_small_run() -> Dict[str, Any]:
    chain = build_chain4()
    out, sess, root, cp = run4_small(chain)
    rule, close = out["rule"], out["close"]
    check(not rule["invalid"] and not rule["incomplete"] and rule["outcome"] in ("PROGRESS", "NO_NEW_MILESTONE"), f"a complete small session: {rule['outcome']} {rule['invalid']} {rule['incomplete']}")
    check(sess.ledgers["T"].ticks == 12000, f"the exploration committed exactly its cap: {sess.ledgers['T'].ticks}")
    sd = sess.cfg.session_dir
    for f in ("p1.json", "identity_open.json", "arm_T.json", "verification.json", "rule.json", "close.json", "state.json", "iterations_T.jsonl", "ledger_T.json", "candidates_T.jsonl.gz", "dispatch_rows.jsonl.gz"):
        check((sd / f).is_file(), f"missing {f}")
    p1 = json.loads((sd / "p1.json").read_text(encoding="utf-8"))
    check(p1["tick0"]["equals_archive_pin"] and p1["selftest"]["corrupted_refused"] and len(p1["traces"]) == 2, "P1 against the archive's pin")
    io_ = json.loads((sd / "identity_open.json").read_text(encoding="utf-8"))
    check(io_["ok"] and io_["cells"] == 6 and io_["verified"] == 6, f"open identity replays: {io_}")
    ver = json.loads((sd / "verification.json").read_text(encoding="utf-8"))
    check(ver["identity"]["ok"] and ver["identity"]["verified"] == ver["identity"]["cells"] == 6, f"close identity replays {ver['identity']}")
    check(ver["claims_digest"] == cl4.contract_digest() and set(ver["pools"]) >= {"left", "can_raise", "descriptive", "t", "l0"}, "the verification record names the claims contract and the pools")
    check(close["audit"]["ok"] and close["prefix_chain"]["ok"] and close["earlier_trees_immutability"]["ok"] and not close["guard_violations"], f"close checks: {close}")
    check(close["archive"]["checkpoint_seq"] == sess.ckpt_seq and sess.ckpt_seq > chain["expect3"]["checkpoint_seq"] + 1, "the checkpoint sequence continues from rd3's")
    check(close["live_seen_at_dispatch"]["live"] == close["live_seen_at_dispatch"]["ledger"], f"the live counters equal the ledger replay's: {close['live_seen_at_dispatch']}")
    first = chain["expect3"]["dispatch_iterations"][1] + 1
    check(sess.first_iteration == first and sess.archive.rd4_first_iteration == first, "iterations continue after rd3's")
    its = [e["it"] for e in sess.archive.events if e["ev"] == "dispatch"]
    check(its == list(range(its[0], its[-1] + 1)) and its[0] == 0 and its.count(first) == 1, "dispatch iterations are contiguous and never reused")
    rows = [json.loads(x) for x in (sd / "iterations_T.jsonl").read_text(encoding="utf-8").splitlines()]
    check(sum(r["ticks"] for r in rows if "ticks" in r) == 12000 and all(r["tick0_equal"] for r in rows if "ticks" in r), "iteration rows add up; tick 0 equal everywhere")
    a = sess.archive
    rng = a.iteration_ranges()
    check(rng["rd4"][0] == first and rng["rd3"][1] == first - 1 and rng["rd2"][1] == chain["expect3"]["first_rd3_iteration"] - 1 and rng["rd1"][1] == chain["expect2"]["first_rd2_iteration"] - 1, f"the four ranges: {rng}")
    b4 = [b for b in a.bursts if b.iteration >= first]
    check(b4 and all(b.ground_runs is not None and b.session == "rd4" for b in b4), "rd4 bursts carry ground runs and the session name")
    check(all(len(b.reaches[0]) == 4 for b in a.bursts if b.reaches and b.iteration >= rng["rd2"][0]) and all(len(b.reaches[0]) == 3 for b in a.bursts if b.reaches and b.iteration < rng["rd2"][0]),
          "reach rows: rd1's keep three elements, rd2's, rd3's and rd4's have four")
    # every burst of every part was explored under its own session's draw id (the words are the keyed stream's prefix)
    aid = a.archive_id
    for b in a.bursts:
        part = a.session_of_iteration(b.iteration)
        draw = {"rd1": aid, "rd2": aid + "_v2", "rd3": aid + "_rd3", "rd4": aid + "_rd4"}[part]
        want = bytes(w for _i, w in zip(range(len(b.words)), mx.words(lambda i, d=draw, it=b.iteration: mx.explore_key(d, it, i), mx.BURST_WORDS)))
        check(b.words == want, f"burst {b.id} (iteration {b.iteration}): the words are not the {draw} keyed stream")
    # the report
    rep = rpt4.full_report4(root, cp["rd3"], cp["rd2"], cp["rd1"], "rd4")
    n_disp4 = sum(1 for e in a.events if e["ev"] == "dispatch" and e["it"] >= first)
    check(rep["rd4"]["dispatches"] == n_disp4 and rep["rd4"]["returns"] == rep["rule_inputs"]["returns"] and rep["iteration_ranges"]["rd4"][0] == first, "the report counts rd4's dispatches")
    for k in ("D7_efficiency", "D8_mechanism_and_v2_flags", "upb_start_heights", "ground_runs", "new", "selection_probability_at_the_open", "rd3_reference", "rd2_reference", "rd1_reference", "decision9", "mechanism",
              "mechanism_references", "D9_max_targets", "claims"):
        check(k in rep, f"the report section {k}")
    check(set(rep["new"]) == {"rd4", "rd3_reference", "rd2_reference", "rd1_reference"} and set(rep["new"]["rd4"]) == {"wall_top", "left_of_wall_face", "left_floor_approach"}, "the new readings in the four columns")
    check(rep["rd3_reference"]["dispatches"] == sum(1 for e in a.events if e["ev"] == "dispatch" and rng["rd3"][0] <= e["it"] <= rng["rd3"][1]), "rd3's reference column counts rd3's dispatches")
    check(rep["rd2_reference"]["dispatches"] == sum(1 for e in a.events if e["ev"] == "dispatch" and rng["rd2"][0] <= e["it"] <= rng["rd2"][1]) and rep["rd1_reference"]["dispatches"] == rng["rd2"][0],
          "rd2's and rd1's reference columns count their dispatches")
    check(abs(rep["D7_efficiency"]["prefix_share"] - sess.arm_records["T"]["prefix_ticks"] / 12000) < 1e-9, "D7 prefix share")
    refs = rep["D7_efficiency_references"]
    check(all(refs[k] is not None for k in ("rd3", "rd2", "rd1")) and refs["rd3"]["returns"] == rep["rd3_reference"]["returns"] and refs["rd3"]["ticks"] == json.loads((cp["rd3"] / "sessions" / "rd3" / "arm_T.json").read_text(
        encoding="utf-8"))["ticks"], "D7 carries rd3's, rd2's and rd1's reference columns")
    d8 = rep["D8_mechanism_and_v2_flags"]
    check(d8["counters_rd4"] == {k: d8["counters_cumulative"][k] - d8["counters_rd3_close"].get(k, 0) for k in d8["counters_cumulative"]}, "rd4's counters are the difference to rd3's closing record")
    check(rep["rule_inputs"] == rule["extra"]["rule_inputs"] and rep["mechanism"]["verdict"] == rule["mechanism"]["verdict"], "the report's rule inputs and mechanism check equal the rule's")
    d9 = rep["D9_max_targets"]
    check(d9["verified_in_rd4"] == rule["max_targets_verified"], "D9's rd4 value is the rule's maximum")
    d9d = rep["decision9"]
    check(set(d9d) == {"frontier_returns", "returns_by_start_cell_session", "seen_distribution"} and set(d9d["frontier_returns"]) == {"rd4", "rd3", "rd2", "rd1"}, "the readings of decision 9 in four columns")
    check(d9d["frontier_returns"]["rd4"]["dispatches"] == n_disp4 and d9d["returns_by_start_cell_session"]["rd4"]["rd1"]["dispatches"] + d9d["returns_by_start_cell_session"]["rd4"]["rd2"]["dispatches"]
          + d9d["returns_by_start_cell_session"]["rd4"]["rd3"]["dispatches"] + d9d["returns_by_start_cell_session"]["rd4"]["rd4"]["dispatches"] == n_disp4, "returns by start-cell session add up")
    a_open, _m = s4.Archive4.read_dir(cp["rd3"] / "archive")
    check(rep["selection_probability_at_the_open"] == rpt4.open_selection_probabilities4(a_open) and set(rep["selection_probability_at_the_open"]) == {"v2", "v3"}
          and rep["selection_probability_at_the_open"]["v3"]["total_probability"] == sum(a_open.probabilities("v3").get(c.id, 0.0) for c in rpt3.wall_top_cells(a_open)),
          "the open probabilities are those of rd3's closing archive, under v2 and under v3")
    # verify-run
    vr = rpt4.verify_run4(root, cp["rd3"], cp["rd2"], cp["rd1"], "rd4")
    check(vr["ok"], f"verify-run: {vr['problems']}")
    for f in ("p1.json", "identity_open.json", "arm_T.json", "verification.json", "rule.json", "close.json", "state.json"):
        check(json.loads((sd / f).read_text(encoding="utf-8")).get("scope") == rule4.SCOPE, f"the scope label is carried by {f}")
    # verify-run refuses a session with no recorded decision, no close record, or a decision the exact replays and the ledger do not hold
    tmp = tmpdir("m8vr4_")
    shutil.copytree(root, tmp / "a")
    (tmp / "a" / "sessions" / "rd4" / "rule.json").unlink()
    vr2 = rpt4.verify_run4(tmp / "a", cp["rd3"], cp["rd2"], cp["rd1"], "rd4")
    check(not vr2["ok"] and any("no rule.json" in p for p in vr2["problems"]), f"no decision recorded: {vr2['problems']}")
    shutil.copytree(root, tmp / "b")
    (tmp / "b" / "sessions" / "rd4" / "close.json").unlink()
    check(not rpt4.verify_run4(tmp / "b", cp["rd3"], cp["rd2"], cp["rd1"], "rd4")["ok"], "no close record is refused")
    for key, bad in (("m", lambda v: 4 if v != 4 else 0), ("max_targets_verified", lambda v: 9 if v != 9 else 0)):
        shutil.copytree(root, tmp / f"c_{key}")
        rp_ = tmp / f"c_{key}" / "sessions" / "rd4" / "rule.json"
        d_ = json.loads(rp_.read_text(encoding="utf-8"))
        d_[key] = bad(d_[key])
        rp_.write_text(json.dumps(d_), encoding="utf-8")
        check(not rpt4.verify_run4(tmp / f"c_{key}", cp["rd3"], cp["rd2"], cp["rd1"], "rd4")["ok"], f"a recorded {key} that the exact replays do not hold is refused")
    def tamper_seen(d: Dict[str, Any]) -> None:
        d["mechanism"]["seen_ge_8"] += 1

    def tamper_verdict(d: Dict[str, Any]) -> None:
        d["mechanism"]["verdict"] = "MECHANISM_FAILS" if d["mechanism"]["verdict"] == "MECHANISM_HOLDS" else "MECHANISM_HOLDS"

    def tamper_line(d: Dict[str, Any]) -> None:
        d["line"]["status"] = "LINE_ENDS_MECHANISM_FAILED" if d["line"]["status"] != "LINE_ENDS_MECHANISM_FAILED" else "RD5_LAST_SESSION"

    for key, mut in (("mechanism seen_ge_8", tamper_seen), ("mechanism verdict", tamper_verdict), ("line status", tamper_line)):
        shutil.copytree(root, tmp / f"d_{key.replace(' ', '_')}")
        rp_ = tmp / f"d_{key.replace(' ', '_')}" / "sessions" / "rd4" / "rule.json"
        d_ = json.loads(rp_.read_text(encoding="utf-8"))
        mut(d_)
        rp_.write_text(json.dumps(d_), encoding="utf-8")
        check(not rpt4.verify_run4(tmp / f"d_{key.replace(' ', '_')}", cp["rd3"], cp["rd2"], cp["rd1"], "rd4")["ok"], f"a recorded {key} that the ledger does not hold is refused")
    shutil.copytree(root, tmp / "e")
    ap_ = tmp / "e" / "archive" / "events.jsonl"
    ap_.write_bytes(ap_.read_bytes().replace(b'"worker":0', b'"worker":1', 1))
    check(not rpt4.verify_run4(tmp / "e", cp["rd3"], cp["rd2"], cp["rd1"], "rd4")["ok"], "a changed archive file is refused")
    shutil.rmtree(tmp, ignore_errors=True)
    check(all_immutability(cp)["ok"] and all_immutability(chain)["ok"], "the earlier trees are untouched")
    shutil.rmtree(cp["t"], ignore_errors=True)
    return {"outcome": rule["outcome"], "cells": len(a.cells), "ticks": 12000, "m": rule["m"], "t": rule["max_targets_verified"], "mechanism": rule["mechanism"]["verdict"]}


def unit_session4_refuses_unbegun_archive() -> Dict[str, Any]:
    chain = build_chain4()
    cp = copy_chain4(chain)
    a3, _m = s4.Archive4.read_dir(cp["rd3"] / "archive")
    clock = FakeClock()
    env = sync_env(chain["world"], [], clock)
    cfg = small_cfg4(cp["t"] / "rd4x")
    raises(RuntimeError, lambda: run4.Session4(cfg, env, archive=a3, archive_pin={"digest": "0" * 64}, base_info={}, rd1_root=cp["rd1"], rd2_root=cp["rd2"], rd3_root=cp["rd3"], lines_sha256=chain["lines"],
                                               ckpt_seq=33), "an archive that has not begun rd4 is refused")
    shutil.rmtree(cp["t"], ignore_errors=True)
    return {}


def unit_session4_outcomes_and_stops() -> Dict[str, Any]:
    chain = build_chain4()
    res: Dict[str, Any] = {}
    # below the registered minimum: INCOMPLETE; exploration started, so the session counts
    out, sess, _r, cp = run4_small(chain, arm_tick_cap=3000, min_arm_ticks=5000)
    r = out["rule"]
    check(r["outcome"] == "INCOMPLETE" and any("reached 3,000" in x for x in r["incomplete"]) and r["stops"]["S7"]["triggered"], f"below the minimum: {r['incomplete']}")
    check(r["line"]["session_counts"] is True and r["exploration_started"] is True and r["line"]["status"] in ("RD5_LAST_SESSION", "LINE_ENDS_MECHANISM_FAILED"),
          f"an INCOMPLETE session counts once exploration has started: {r['line']}")
    res["below_minimum"] = r["outcome"]
    # a lifecycle failure is redrawn (up to three); more than three is INCOMPLETE
    out, sess, _r, cp = run4_small(chain, inject={"lifecycle_jobs": [14]}, n_workers=2, arm_tick_cap=8000, min_arm_ticks=1000)
    check(1 <= sess.lifecycle_failures["T"] <= 3 and sess.ledgers["T"].ticks == 8000 and out["rule"]["outcome"] != "INCOMPLETE", f"redrawn lifecycle failures {sess.lifecycle_failures}: {out['rule']['outcome']}")
    check(any(e["ev"] == "fail" for e in sess.archive.events) and s4.audit4(sess.archive, chain["lines"])["ok"], "the ledger records the failed iteration and still audits")
    res["lifecycle_redrawn"] = sess.lifecycle_failures["T"]
    out, sess, _r, cp = run4_small(chain, inject={"lifecycle_jobs": [14, 15, 16, 17]}, n_workers=2, arm_tick_cap=12000, min_arm_ticks=1000)
    check(out["rule"]["outcome"] == "INCOMPLETE" and any("lifecycle failures" in x for x in out["rule"]["incomplete"]), f"more than three: {out['rule']['incomplete']}")
    res["lifecycle_over"] = out["rule"]["outcome"]
    # an integrity mismatch and a provenance violation: INVALID (the budget is not guessed)
    out, sess, _r, cp = run4_small(chain, inject={"mismatch_job": 14, "mismatch_tick": 5}, n_workers=2, arm_tick_cap=20000, min_arm_ticks=1000)
    r = out["rule"]
    check(r["outcome"] == "INVALID" and any("prefix_end" in x for x in r["invalid"]), f"an integrity mismatch: {r['invalid']}")
    check(list((sess.cfg.session_dir / "failures").glob("iterate_*")), "the failed return's raw replies are preserved")
    check(r["line"]["status"] == "REPAIR_NEEDED" and r["line"]["rd5_permitted"] is None and r["line"]["session_counts"] is None, f"INVALID: repair, the budget is not guessed: {r['line']}")
    res["mismatch"] = r["outcome"]
    out, sess, _r, cp = run4_small(chain, inject={"provenance_job": 14}, n_workers=2, arm_tick_cap=5000, min_arm_ticks=1000)
    check(out["rule"]["outcome"] == "INVALID" and any("provenance" in x for x in out["rule"]["invalid"]), f"a provenance violation: {out['rule']['invalid']}")
    res["provenance"] = out["rule"]["outcome"]
    # an earlier tree changed at the close: INVALID, named by the tree
    out, sess, _r, cp = run4_small(chain, arm_tick_cap=3000, min_arm_ticks=1000, immutability=lambda: {"ok": False, "problems": ["rd3: cells.jsonl differs"]})
    check(out["rule"]["outcome"] == "INVALID" and any("an earlier tree changed" in x for x in out["rule"]["invalid"]), f"a changed earlier tree: {out['rule']['invalid']}")
    res["earlier_tree_changed"] = out["rule"]["outcome"]
    # a write under any of the three earlier trees is a guard violation: INVALID (the write happens in the session process, through the clock's memory probe)
    for victim in ("rd1", "rd2", "rd3"):
        def writer(cp_: Mapping[str, Any], _clock: FakeClock, victim: str = victim) -> Mapping[str, Any]:
            done: List[int] = []

            def private_mb() -> float:
                if not done:
                    done.append(1)
                    (Path(cp_[victim]) / "archive" / "stray.txt").write_text("x", encoding="utf-8")
                return 100.0

            return {"private_mb": private_mb}

        out, sess, _r, cp = run4_small(chain, n_workers=2, arm_tick_cap=400000, min_arm_ticks=100, env_kw_factory=writer)
        check(out["rule"]["outcome"] == "INVALID" and any("protected root" in x for x in out["rule"]["invalid"]), f"a write under {victim}'s tree: {out['rule']['outcome']} {out['rule']['invalid']}")
        res[f"{victim}_write"] = out["rule"]["outcome"]
    # a software error in one close check is recorded (INCOMPLETE) and cannot hide the others
    def broken() -> Mapping[str, Any]:
        raise RuntimeError("injected immutability failure")

    out, sess, _r, cp = run4_small(chain, arm_tick_cap=3000, min_arm_ticks=1000, immutability=broken)
    cl = out["close"]
    check(out["rule"]["outcome"] == "INCOMPLETE" and any("earlier_trees_immutability could not run" in x for x in out["rule"]["incomplete"]), f"an erroring close check: {out['rule']['incomplete']}")
    check("earlier_trees_immutability_error" in cl and cl["audit"]["ok"] and cl["prefix_chain"]["ok"], "the other close checks still ran")
    res["close_check_error"] = out["rule"]["outcome"]

    # a memory breach and a process-count breach: INCOMPLETE (virtual time, so the moment is exact)
    class LateBreach:
        def __init__(self, clock: FakeClock) -> None:
            self.clock, self.t0 = clock, clock.now()

        @property
        def breach(self) -> Optional[str]:
            return "memory cap: process tree private 99999 MB > 9216 MB" if self.clock.now() - self.t0 > 2.5 else None

    out, sess, _r, cp = run4_small(chain, env_kw_factory=lambda cp_, clock_: {"sampler": LateBreach(clock_)}, n_workers=2, arm_tick_cap=10 ** 7, min_arm_ticks=1000)
    check(out["rule"]["outcome"] == "INCOMPLETE" and any("memory cap" in x for x in out["rule"]["incomplete"]), f"a memory breach: {out['rule']['incomplete']}")
    res["memory"] = out["rule"]["outcome"]
    out, sess, _r, cp = run4_small(chain, env_kw={"tree_snapshot": lambda: {"battleship": 11}}, n_workers=2, arm_tick_cap=10 ** 6, min_arm_ticks=1000, process_check_every_s=0.05)
    check(out["rule"]["outcome"] == "INCOMPLETE" and any("11 BattleShip processes" in x for x in out["rule"]["incomplete"]), f"a process-count breach: {out['rule']['incomplete']}")
    res["processes"] = out["rule"]["outcome"]
    # the exploration's wall cap (virtual seconds): valid at or above the minimum, a cut at the cap
    out, sess, _r, cp = run4_small(chain, n_workers=2, arm_tick_cap=10 ** 7, min_arm_ticks=500, wall_caps_s={"p1": 90.0, "T": 2.0, "C": 0.0, "verify": 300.0}, global_cap_s=900.0)
    tT = sess.ledgers["T"].ticks
    check(sess.arm_records["T"]["stop"][0] == "wall_cap" and 500 <= tT < 10 ** 7 and not out["rule"]["incomplete"], f"a wall-capped exploration at or above the minimum is valid ({tT}): {out['rule']['incomplete']}")
    res["wall_cap"] = tT
    # the replay cap: INCOMPLETE only when an unverified candidate could change the outcome (no identity replays here, so the cap acts on the claims alone)
    out, sess, _r, cp = run4_small(chain, replay_tick_cap=150, arm_tick_cap=12000, min_arm_ticks=2000, identity_k=0)
    ver = json.loads((sess.cfg.session_dir / "verification.json").read_text(encoding="utf-8"))
    check(ver["cap_hit"] is not None, "the replay cap was hit")
    if out["rule"]["outcome"] == "INCOMPLETE":
        check(any("could raise m" in x for x in out["rule"]["incomplete"]), f"INCOMPLETE only with a reason: {out['rule']['incomplete']}")
    else:
        check(ver["arm"]["max_m_unverified"] <= ver["arm"]["m"], "a cap that cannot change the outcome is not INCOMPLETE")
    res["replay_cap"] = out["rule"]["outcome"]
    return res


def unit_session4_mechanism_and_line() -> Dict[str, Any]:
    """The mechanism check and the line budget in real sessions of the engine: the recorded verdict equals the check applied to the ledger replay's own readings, in a world where it holds and in one
    where it fails; the line status follows."""
    seen: Dict[str, Any] = {}
    for world, rd1, rd2, rd3, want in (("easy", CHAIN_RD1, CHAIN_RD2, CHAIN_RD3, "MECHANISM_HOLDS"), ("calm", (9000, 6000), 4000, 4000, "MECHANISM_FAILS")):
        chain = build_chain4(world, rd1_caps=rd1, rd2_ticks=rd2, rd3_ticks=rd3, cache=(world == "easy"))
        out, sess, root, cp = run4_small(chain, arm_tick_cap=12000, min_arm_ticks=4000)
        r = out["rule"]
        check(not r["invalid"] and not r["incomplete"] and r["outcome"] in ("PROGRESS", "NO_NEW_MILESTONE"), f"{world}: {r['outcome']} {r['invalid']} {r['incomplete']}")
        a = sess.archive
        aud = s4.audit4(a, chain["lines"], collect_rows_from=sess.first_iteration)
        mi = rpt4.mechanism_inputs(a, aud["dispatch_rows"], sess.first_iteration, sess.first_new_cell)
        again = rule4.mechanism(**mi)
        check(again == r["mechanism"] and r["mechanism"]["verdict"] == want, f"{world}: the recorded mechanism check {r['mechanism']} vs the ledger replay's {again} (expected {want})")
        ret = r["extra"]["rule_inputs"]
        check(ret["returns"] == mi["returns"] and ret["seen_ge_8"] == mi["seen_ge_8"] and ret["new_cells"] == mi["new_cells"], "the rule inputs are the mechanism inputs")
        # the line status follows (decision 7): a verified milestone outranks the check; no milestone and a failed check ends the line
        m = r["m"]
        if m >= 2:
            check(r["line"]["status"] == "MILESTONE_VERIFIED" and not r["line"]["line_ends"], f"{world}: a verified milestone outranks the mechanism check")
        elif want == "MECHANISM_FAILS":
            check(r["line"]["status"] == "LINE_ENDS_MECHANISM_FAILED" and r["line"]["line_ends"] and r["line"]["rd5_permitted"] is False, f"{world}: a failed check with no milestone ends the line")
        else:
            check(r["line"]["status"] == "RD5_LAST_SESSION" and r["line"]["rd5_permitted"] is True, f"{world}: no milestone and a holding check: rd5 is the last session")
        check(rpt4.verify_run4(root, cp["rd3"], cp["rd2"], cp["rd1"], "rd4")["ok"], f"{world}: verify-run")
        rep = rpt4.full_report4(root, cp["rd3"], cp["rd2"], cp["rd1"], "rd4")
        check(rep["mechanism"] == r["mechanism"], f"{world}: the report's mechanism check equals the rule's")
        seen[world] = {"outcome": r["outcome"], "m": m, "mechanism": r["mechanism"]["verdict"], "line": r["line"]["status"], "seen8": mi["seen_ge_8"], "returns": mi["returns"], "new_cells": mi["new_cells"]}
        shutil.rmtree(cp["t"], ignore_errors=True)
        if world != "easy":
            shutil.rmtree(chain["t"], ignore_errors=True)
    check(seen["calm"]["seen8"] > 0, f"the calm world's returns do start from cells seen 8 or more times: {seen['calm']}")
    return seen


def unit_claim_cases_session() -> Dict[str, Any]:
    """Decision 6 at session level. The first dispatches of a REAL rd4 session are claim cases from INHERITED cells (each at an iteration number whose selection is that cell, so the ledger stays
    auditable): the continuation of an inherited left cell that does not land, the continuation of an inherited wall-top cell, and a burst from an inherited over-wall cell that lands on the left
    floor (the ENTRY lies in the inherited prefix, the LANDING in the new burst). Everything else is the engine's: registration, the replay plan, the exact replays, the close audit, the rule."""
    chain = build_chain4()
    world = chain["world"]
    cls = forced_session_cls(world, ("left_nolanding", "wall_continuation", "cross"))
    out, sess, root, cp = run4_small(chain, session_cls=cls, arm_tick_cap=12000, min_arm_ticks=4000)
    rule, close = out["rule"], out["close"]
    check(rule["outcome"] == "PROGRESS" and rule["m"] >= 2 and not rule["invalid"] and not rule["incomplete"], f"a session that starts with the claim cases: {rule['outcome']} m={rule['m']} {rule['invalid']} {rule['incomplete']}")
    check(close["audit"]["ok"] and rpt4.verify_run4(root, cp["rd3"], cp["rd2"], cp["rd1"], "rd4")["ok"], "the ledger (with its skipped iteration numbers) audits, and verify-run passes")
    its = [e["it"] for e in sess.archive.events if e["ev"] == "dispatch" and e["it"] >= sess.first_iteration]
    check(its == sorted(set(its)) and (any(b - a_ > 1 for a_, b in zip(its, its[1:])) or its[0] > sess.first_iteration), "the forced dispatches skipped iteration numbers (strictly increasing, never reused)")
    forced = {f["kind"]: f for f in sess.forced}
    n_open = chain["expect3"]["cells"]
    check(set(forced) == {"left_nolanding", "wall_continuation", "cross"} and all(f["cell"] < n_open for f in forced.values()), f"the three forced dispatches start from inherited cells: {forced}")
    ev = {e["it"]: e for e in sess.archive.events if e["ev"] == "dispatch"}
    check(all(ev[f["iteration"]]["cell"] == f["cell"] for f in forced.values()), "the ledger's dispatch events are those cells")
    led = sess.ledgers["T"]
    ver = json.loads((sess.cfg.session_dir / "verification.json").read_text(encoding="utf-8"))
    # (a) the crossing: entry in the inherited prefix, landing in the new burst, credited by the session's own verification
    fc = forced["cross"]
    cand = candidate_for_iteration(sess, fc["iteration"], "left")
    check(cand is not None and cand["first"].get("left_floor") is not None and cand["first"]["left_live"] == fc["L"] + 1, f"the burst registered a can-raise left candidate whose left presence is inherited: {cand and cand['first']}")
    raisers = [c["cid"] for c in led.candidates if "crossing" in cl4.raises(c)]
    check(cand["cid"] == min(raisers), "it is the first can-raise candidate in discovery order (the engine replays it first)")
    claim = ver["arm"]["claims"]["crossing"]
    check(claim["cid"] == cand["cid"] and claim["first_qualified_entry"] is not None and claim["first_qualified_entry"] < fc["L"], f"the verified crossing is that candidate, with its entry in the inherited prefix: {claim}")
    with gzip.open(sess.cfg.session_dir / "verification" / f"{claim['label']}.json.gz", "rt", encoding="utf-8") as fp:
        trace = json.load(fp)
    e, l = trace_entry_landing(trace)
    check(e == claim["first_qualified_entry"] and e < fc["L"] < l, f"entry {e} < the inherited prefix {fc['L']} < landing {l} (the landing is in the rd4 burst)")
    reps = [json.loads(x) for x in (sess.cfg.session_dir / "verification" / "replays.jsonl").read_text(encoding="utf-8").splitlines()]
    check(all(r["exact"] for r in reps) and rpt4.replay_verified_m(reps) == rule["m"], "every replay is exact, and m is what the replays hold")
    # (b) the left continuation that never lands: replayed as a descriptive fact, exact, never an INVALID
    fl = forced["left_nolanding"]
    cand_b = candidate_for_iteration(sess, fl["iteration"], "left")
    check(cand_b is not None and cl4.is_descriptive(cand_b), "the continuation of an inherited left cell registers a descriptive candidate")
    rep_b = next((r for r in reps if r["cid"] == cand_b["cid"]), None)
    check(rep_b is not None and rep_b["exact"] and not rep_b["crossing"], f"it was replayed: exact, not a crossing: {rep_b and rep_b['problems']}")
    # (c) the wall-top continuation: a sighting, no l0 candidate, no false INVALID
    fw = forced["wall_continuation"]
    rows_s = [json.loads(x) for x in (sess.cfg.session_dir / "wall_top_sightings.jsonl").read_text(encoding="utf-8").splitlines()]
    row = next((x for x in rows_s if x["iteration"] == fw["iteration"]), None)
    check(row is not None and row["start_cell_on_wall_top"] and row["first_tick_of_the_burst"], f"the wall-top continuation is recorded as a sighting: {rows_s}")
    check(led.l0_cid is None and not [c for c in led.candidates if c["kind"] == "l0"] and not (root / "routes" / "T_L0").exists(), "no wall-top candidate, no wall-top route: the landing is rd2's, never claimed again")
    check(json.loads((sess.cfg.session_dir / "arm_T.json").read_text(encoding="utf-8"))["wall_top_sightings"]["from_a_wall_top_start"] >= 1, "the arm record counts it")
    check(rule["line"]["status"] == "MILESTONE_VERIFIED" and rule["highest_milestone"] in ("crossing", "left_target", "clear"), f"the line status: {rule['line']['status']}")
    check(all_immutability(cp)["ok"], "the earlier trees are untouched")
    shutil.rmtree(cp["t"], ignore_errors=True)
    return {"entry": e, "landing": l, "prefix": fc["L"], "m": rule["m"]}


def unit_verification_capacity_flood() -> Dict[str, Any]:
    """The capacity hazard: every return to the growing set of left-of-wall cells registers a `left` candidate, hundreds in a session; the frozen plan would replay them in discovery order and spend the
    replay cap (shared with the close identity replays) before reaching a candidate that can raise m. rd4's plan replays the can-raise candidates first and bounds the descriptive ones."""
    chain = build_chain4()
    world = chain["world"]
    a_open, _m = s4.Archive4.read_dir(chain["rd3"] / "archive")
    c, n, burst = find_burst(world, a_open, "cross", draw="claims4flood")
    cross_words = a_open.cell_words(c) + burst
    tr_x = stub.replay_trace(world, cross_words)
    lab_x, brk_x = scan_labels(tr_x, len(a_open.cell_words(c)))
    flood_words: List[Tuple[bytes, List[Tuple[int, int]]]] = []
    for k in range(300):
        w = bytes(mx.words(lambda i, k=k: mx.explore_key("flood4", k, i), 250))
        tr = stub.replay_trace(world, w)
        if tr["unsent"]:
            continue                                                            # the stage was cleared inside the sequence: not a replayable candidate
        _l, brk = scan_labels(tr, 0)
        flood_words.append((w, brk))
    cap = 60_000
    descriptive_ticks = sum(len(w) for w, _b in flood_words)
    check(len(flood_words) >= 290 and descriptive_ticks > cap, f"the 300 descriptive candidates alone would need {descriptive_ticks:,} replay ticks, more than the cap {cap:,}")

    class Flood(run4.Session4):
        def run_arm(self, arm: str) -> Dict[str, Any]:
            rec = super().run_arm(arm)
            led = self.ledgers["T"]
            for w, brk in flood_words:
                led.register(cum_before=0, iteration=self.first_iteration, words=w, prefix_len=0, labels={"t": 0, "breaks": [], "t_events": [], "first": {"l0": None, "left_live": 5, "left_floor": None,
                                                                                                                                                       "left_break": None, "clear": None}},
                             breaks=brk, end_reason="length", t_end=0)
            led.register(cum_before=0, iteration=self.first_iteration, words=cross_words, prefix_len=len(a_open.cell_words(c)), labels=lab_x, breaks=brk_x, end_reason="length", t_end=lab_x["t"])
            return rec

    out, sess, root, cp = run4_small(chain, session_cls=Flood, replay_tick_cap=cap, arm_tick_cap=12000, min_arm_ticks=4000)
    rule = out["rule"]
    led = sess.ledgers["T"]
    target = max(c_["cid"] for c_ in led.candidates if c_["kind"] == "left")
    check(not rule["invalid"] and not rule["incomplete"], f"the flooded session is neither INVALID nor INCOMPLETE: {rule['outcome']} {rule['invalid']} {rule['incomplete']}")
    ver = json.loads((sess.cfg.session_dir / "verification.json").read_text(encoding="utf-8"))
    check(ver["cap_hit"] is None and sess.ticks["replays"] < cap, f"the replay cap was not hit: {sess.ticks['replays']:,} of {cap:,}")
    check(ver["pools"]["descriptive"] >= 300 and ver["arm"]["descriptive"]["descriptive_replayed"] <= cl4.INFO_REPLAY_MAX, f"descriptive entries: {ver['pools']['descriptive']} registered, at most {cl4.INFO_REPLAY_MAX} replayed")
    reps = [json.loads(x) for x in (sess.cfg.session_dir / "verification" / "replays.jsonl").read_text(encoding="utf-8").splitlines()]
    check(any(r["cid"] == target for r in reps) and ver["arm"]["claims"].get("crossing", {}).get("cid") == target and rule["m"] >= 2 and rule["outcome"] == "PROGRESS",
          f"the last candidate in discovery order was verified: crossing claim {ver['arm']['claims'].get('crossing')}")
    check(len(reps) <= 2 + cl4.INFO_REPLAY_MAX + sum(1 for c_ in led.candidates if cl4.raises(c_)), f"{len(reps)} replays, not hundreds")
    # the same ledger under the FROZEN plan (replay everything in discovery order): the target is reached only after a flood of ticks beyond the cap
    done: Dict[int, Dict[str, Any]] = {}
    ticks = 0
    for _round in range(400):
        todo, _info = mclaims.plan_replays(led, led.ticks, done, batch=3)
        hit = False
        for cand, cnt in todo:
            ticks += cnt
            done[cand["cid"]] = fake_rep(cand["cid"])
            hit = hit or cand["cid"] == target
        if hit or not todo:
            break
    check(ticks > cap, f"under the frozen plan the can-raise candidate is reached only after {ticks:,} replay ticks (> the cap {cap:,}): the hazard")
    shutil.rmtree(cp["t"], ignore_errors=True)
    return {"replays": len(reps), "frozen_plan_ticks": ticks}


def unit_session4_determinism() -> Dict[str, Any]:
    """Two independent builds of the same chain and two runs of the same rd4 session agree on every ledger event, cell, word and decision."""
    c1 = build_chain4(cache=False)
    c2 = build_chain4(cache=False)

    def chain_sig(c: Mapping[str, Any]) -> Dict[str, Any]:
        return {t: {n: mw.sha256_file(c[t] / "archive" / n) for n in ("cells.jsonl", "bursts.bin", "bursts.idx.jsonl", "events.jsonl")} for t in ("rd1", "rd2", "rd3")}

    check(chain_sig(c1) == chain_sig(c2), "two builds of the synthetic chain are byte-identical (cells, words, index, ledger)")
    o1, s1_, r1, cp1 = run4_small(c1)
    o2, s2_, r2, cp2 = run4_small(c1)
    sig1, sig2 = signature(r1), signature(r2)
    check(sig1 == sig2, "two runs of the same rd4 session agree on the archive's data files, the decision, the mechanism check and the line status")
    check(o1["rule"]["outcome"] == o2["rule"]["outcome"] and s1_.ledgers["T"].ticks == s2_.ledgers["T"].ticks and len(s1_.ledgers["T"].candidates) == len(s2_.ledgers["T"].candidates), "outcome, ticks and candidates agree")
    for c in (c1, c2, cp1, cp2):
        shutil.rmtree(c["t"], ignore_errors=True)
    return {"files": len(sig1["files"])}


# -- guards, budget, approval, pins ---------------------------------------------------------------------------------------------------------------------------


def unit_write_guard_three_roots() -> Dict[str, Any]:
    t = tmpdir("m8wg4_")
    roots = {"rd1": t / "rd1", "rd2": t / "rd2", "rd3": t / "rd3"}
    other = t / "rd4"
    for d in (*roots.values(), other):
        d.mkdir()
        (d / "f.txt").write_text("x", encoding="utf-8")
    mw.ProvenanceGuard.install()
    w2.WriteGuard.install(list(roots.values()))
    base = len(mw.ProvenanceGuard.violations)
    try:
        (other / "o.txt").write_text("z", encoding="utf-8")
        for name, root in roots.items():
            shutil.copyfile(root / "f.txt", other / f"copy_{name}.txt")
            open(root / "f.txt", "rb").close()
        check(len(mw.ProvenanceGuard.violations) == base, "reads of all three earlier trees and writes under rd4's own root are not violations")
        for name, root in roots.items():
            before = len(mw.ProvenanceGuard.violations)
            (root / "w.txt").write_text("a", encoding="utf-8")
            check(len(mw.ProvenanceGuard.violations) > before, f"the write guard missed a write under {name}'s tree")
            before = len(mw.ProvenanceGuard.violations)
            shutil.copyfile(other / "o.txt", root / "c.txt")
            check(len(mw.ProvenanceGuard.violations) > before, f"the write guard missed a copy into {name}'s tree")
            before = len(mw.ProvenanceGuard.violations)
            os.remove(root / "f.txt")
            check(len(mw.ProvenanceGuard.violations) > before, f"the write guard missed a removal under {name}'s tree")
    finally:
        w2.WriteGuard.clear()
        del mw.ProvenanceGuard.violations[base:]
        shutil.rmtree(t, ignore_errors=True)
    # the real environment's worker spec protects all three roots (the inner builder is replaced by a stub: no process, no file is touched)
    saved = ses2.build_real_env2
    try:
        ses2.build_real_env2 = lambda *a, **k: mrun.RunEnv(worker_spec=lambda rank, c: {"rank": rank}, replay=lambda *x: {}, analyse=lambda *x: {}, p1_inputs=lambda: [], pins={})
        spec = ses4.build_real_env4(ses4.run_config(), Path("x"), {}, {}).worker_spec(0, ses4.run_config())
    finally:
        ses2.build_real_env2 = saved
    check(sorted(spec["protected_roots"]) == sorted(str(r) for r in (ses4.RD1_ROOT, ses4.RD2_ROOT, ses4.RD3_ROOT)), f"the worker spec protects the three earlier trees: {spec['protected_roots']}")
    return {"roots": 3}


def unit_budget_projection4() -> Dict[str, Any]:
    caps = ses4.caps()
    check(caps["wall_caps_s"] == {"p1": 240.0, "T": 3000.0, "verify": 360.0} and caps["global_cap_s"] == 3600.0, f"the registered wall caps: {caps['wall_caps_s']}")
    check(caps["exploration_tick_cap"] == 6_000_000 and caps["min_exploration_ticks"] == 2_000_000 and caps["open_tick_cap"] == 70_000 and caps["replay_tick_cap"] == 400_000
          and caps["identity_k"] == 16 and caps["max_battleship_processes"] == 10, "the registered tick caps")
    check(caps["memory_caps_mb"] == {"main_private": 3072, "tree_private": 9216, "tree_working_set": 4096, "system_available_min": 1024, "system_commit_free_min": 2048}, "memory caps as rd1's, rd2's and rd3's")
    check(caps == ses3.caps() == ses2.caps(), "every cap equals rd2's and rd3's")
    proj = rpt4.budget_projection(caps)
    check(proj["caps_s"]["sum"] == proj["caps_s"]["session_hard_cap"] == 3600.0, "the phase caps sum to the session cap")
    check(proj["pessimistic"]["valid"] and proj["pessimistic"]["fits_hard_cap"] and proj["every_cap_binding"]["equals_hard_cap"] and proj["fits_hard_cap_without_trimming"],
          f"the pessimistic projection fits without trimming: {proj['pessimistic']}")
    check(proj["pessimistic"]["wall_s"]["total"] <= 3600.0 and proj["expected"]["wall_s"]["total"] <= proj["pessimistic"]["wall_s"]["total"], "expected <= pessimistic <= cap")
    check(proj["expected"]["exploration_ticks"] > 2_000_000 and not proj["expected"]["tick_cap_binds"], "the expected exploration is valid and the wall cap binds first")
    return {"pessimistic_s": proj["pessimistic"]["wall_s"]["total"], "expected_ticks": round(proj["expected"]["exploration_ticks"]), "pessimistic_ticks": proj["pessimistic"]["exploration_ticks"]}


def unit_approval_isolated4() -> Dict[str, Any]:
    want = ses4.identity()
    t = tmpdir("m8ap4_")
    p = t / "approval.json"
    ok, why = ses4.approval_status(p, want)
    check(not ok and "no approval record" in why, "no record: refused")
    good = dict(want, approval="APPROVED by the test", revision=1)
    p.write_text(json.dumps(good), encoding="utf-8")
    check(ses4.approval_status(p, want) == (True, "approved"), "a matching record is accepted")
    p.write_text(json.dumps(dict(good, approval="PENDING")), encoding="utf-8")
    check(not ses4.approval_status(p, want)[0], "PENDING is refused")
    n = 0
    alter = {"rule_sha256": "0" * 64, "claims_digest": "0" * 64, "executable_sha256": "0" * 64, "scope": "other", "archive_id": "x", "workers": 4, "burst_words": 121, "horizon": 3599,
             "flags": {"explore": {}, "verify": {}}, "contracts": dict(want["contracts"], m8_rd_select_v3="0" * 64), "key_strings": {"select_rd4": "x"},
             "runtime_files": {"BattleShip.o2r": "0" * 64}, "p1": {}, "readiness": {"min_available_mb": 1}, "git_head": "0" * 40, "session": "rdX", "gate": "x", "milestone": "M9",
             "rule": "other", "draws_sha256": "0" * 64, "rd4_session_event_digest": "0" * 64, "select_v3_changed_from": {"m8_rd_select_v2": "0" * 64}, "select_v3_registered_changes": ["cell_weight"],
             "count_exponent": 0.6, "base": dict(want["base"], rd3_increment_manifest_sha256="0" * 64), "open_overlay": {"sha256": "0" * 64}, "mechanism_check": {"seen_min": 7},
             "line_budget": "three sessions", "budgets": {"hard_cap": "61 min"}, "docs_sha256": {"docs/x.md": "0" * 64}}
    for k, v in alter.items():
        check(k in want, f"the identity carries {k}")
        p.write_text(json.dumps(dict(good, **{k: v})), encoding="utf-8")
        check(not ses4.approval_status(p, want)[0], f"an altered {k} was accepted")
        n += 1
    for k in list(want["base"]):
        b = dict(want["base"])
        b[k] = "altered"
        p.write_text(json.dumps(dict(good, base=b)), encoding="utf-8")
        check(not ses4.approval_status(p, want)[0], f"an altered base entry {k} was accepted")
        n += 1
    for k in list(want["caps"]):
        caps = dict(want["caps"])
        caps[k] = {"x": 1}
        p.write_text(json.dumps(dict(good, caps=caps)), encoding="utf-8")
        check(not ses4.approval_status(p, want)[0], f"an altered cap {k} was accepted")
        n += 1
    for f in list(want["code"]):
        code = dict(want["code"])
        code[f] = "0" * 64
        p.write_text(json.dumps(dict(good, code=code)), encoding="utf-8")
        check(not ses4.approval_status(p, want)[0], f"an altered code hash for {f} was accepted")
        n += 1
    p.write_text(json.dumps(dict(good, d_records={"folders": ["2026-09-28"], "digest": "0" * 64})), encoding="utf-8")
    check(not ses4.approval_status(p, want)[0], "an altered D: records digest")
    p.write_text("{not json", encoding="utf-8")
    raises(ValueError, lambda: ses4.approval_status(p, want), "an unreadable record raises")
    check(ses4.APPROVAL != p and ses4.APPROVAL.name == "rl_m8_rd4_approval.json", "the repository path is untouched by the tests")
    check(set(want["contracts"]) == {"m8_rd_cell_v1", "m8_rd_select_v1", "m8_rd_explore_v1", "m8_rd_claims_v1", "track1_btt_s9_b8_v1", "btt_action_class_table_v2", "m8_rd_select_v2", "m8_rd_select_v3"},
          "contract digests")
    base = want["base"]
    check(want["rule"] == "m8_rd4_rule_v1" and want["workers"] == 5 and want["horizon"] == 3600 and base["rd3_checkpoint_seq"] == 32 and base["rd3_increment"] == r4.RD3_INCREMENT_NAME
          and base["first_rd4_iteration"] == 10406 and base["rd3_first_iteration"] == 6212 and base["inherited"] == r4.INHERITED_FACTS and want["rd4_session_event_digest"] == want["contracts"]["m8_rd_select_v3"]
          and want["select_v3_changed_from"] == {"m8_rd_select_v2": want["contracts"]["m8_rd_select_v2"]} and [e["name"] for e in base["rd3_session_events"]] == ["rd2", "rd3"]
          and all(e["digest"] == want["contracts"]["m8_rd_select_v2"] for e in base["rd3_session_events"]), "registered identity entries (rd2's and rd3's session digests are the v2 digest; rd4's is v3's)")
    check(want["open_overlay"]["expected_counts"] == r4.EXPECTED_CLOSE_OVERLAY and want["open_overlay"]["sha256"] == r4.CLOSING_OVERLAY_SHA256, "the open overlay is pinned")
    check(want["mechanism_check"] == {"seen_ge_8_share_max": 0.45, "seen_min": 8, "new_cells_per_return_min": 1.74} and want["line_budget"] == rule4.BUDGET, "the mechanism check and the line budget are pinned")
    for f in ses4.NEW_CODE_FILES:
        check(f"rl/{f}" in want["code"] or not (RL_DIR / f).is_file(), f"{f} is pinned")
    check(all(f"rl/{f}" in want["code"] for f in ("m8_rd_select2.py", "m8_rd2_run.py", "m8_rd3_run.py", "m8_rd3_tests.py", "m8_rd2_tests.py", "m8_rd_tests.py", "m8_rd_cells.py", "m8_rd_claims.py")),
          "rd1's, rd2's and rd3's code is pinned too")
    shutil.rmtree(t, ignore_errors=True)
    return {"altered_entries_refused": n}


def unit_import_isolation4() -> Dict[str, Any]:
    code = ("import sys; sys.path.insert(0, r'%s'); " % RL_DIR + "import m8_rd4_select, m8_rd4_resume, m8_rd4_claims, m8_rd4_run, m8_rd4_session, m8_rd4_rule, m8_rd4_report; "
            "print(sorted(m for m in ('torch', 'numpy', 'gymnasium', 'stable_baselines3', 'm7u3_gate', 'm7f_trace', 'm7n_crossing', 'm7g_fixture', 'btt_learning', "
            "'m7h_curriculum') if m in sys.modules))")
    r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=120)
    check(r.stdout.strip() == "[]", f"the rd4 modules imported heavy ones: {r.stdout.strip()} {r.stderr[-300:]}")
    return {}


def unit_source_guard4() -> Dict[str, Any]:
    """No rd4 module reads fixtures, recordings, the TAS or any .btti file; none imports a learning framework or the random module; and no call that writes can take a path built from an earlier
    tree's root (all three earlier trees are read-only)."""
    forbidden = ("rl/fixtures", "fixtures/m7g", "m7g/capture", "tas_input", "mario_743", ".btti", "btti_replay", "crossing_fixture", "rl_crossing")
    bad_imports = {"random", "torch", "gymnasium", "stable_baselines3", "numpy", "pandas", "scipy", "sklearn"}
    write_attrs = {"write_text", "write_bytes", "mkdir", "unlink", "rmdir", "touch", "rename", "replace", "chmod"}
    copy_funcs = {"copyfile", "copy", "copy2", "copytree", "move"}
    writers = {"write_json", "append_jsonl", "save_checkpoint", "write_files", "rmtree", "rmtree_retry", "remove_tree_retry", "replace_retry", "makedirs"}
    names_earlier = ("rd1_root", "RD1_ROOT", "rd1_archive_dir", "M8_ROOT", "rd2_root", "RD2_ROOT", "rd2_archive_dir", "rd1_dir", "rd2_dir", "RD1_REAL", "RD2_REAL", "rd3_root", "RD3_ROOT", "rd3_archive_dir",
                     "rd3_dir", "RD3_REAL")
    hits: Dict[str, List[str]] = {}
    for name in NEW_MODULES:
        raw = (RL_DIR / f"{name}.py").read_text(encoding="utf-8")
        body = "\n".join(ln for ln in raw.replace("\\", "/").splitlines() if not ln.lstrip().startswith("FORBIDDEN_FRAGMENTS"))
        found = [f for f in forbidden if f in body]
        tree = ast.parse(raw)
        imports = set()
        for nd in ast.walk(tree):
            if isinstance(nd, ast.Import):
                imports |= {a.name.split(".")[0] for a in nd.names}
            elif isinstance(nd, ast.ImportFrom) and nd.module:
                imports.add(nd.module.split(".")[0])
        found += [f"import {i}" for i in sorted(imports & bad_imports)]

        def mentions_earlier(node: ast.AST) -> bool:
            return any(n in ast.unparse(node) for n in names_earlier)

        for nd in ast.walk(tree):
            if not isinstance(nd, ast.Call):
                continue
            f = nd.func
            fname = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
            if isinstance(f, ast.Attribute) and fname in write_attrs and mentions_earlier(f.value):
                found.append(f"write call on an earlier tree's path: {ast.unparse(nd)[:80]}")
            if fname in writers and nd.args and mentions_earlier(nd.args[0]):
                found.append(f"write call with an earlier tree's path: {ast.unparse(nd)[:80]}")
            if fname in copy_funcs and len(nd.args) >= 2 and mentions_earlier(nd.args[1]):
                found.append(f"copy into an earlier tree's path: {ast.unparse(nd)[:80]}")
            if fname == "open" and len(nd.args) >= 2 and nd.args[0] and mentions_earlier(nd.args[0]):
                mode = ast.unparse(nd.args[1])
                if any(c in mode for c in "wax+"):
                    found.append(f"open for write on an earlier tree's path: {ast.unparse(nd)[:80]}")
        if found:
            hits[name] = found
    check(not hits, f"forbidden vocabulary, imports or writes in the rd4 modules: {hits}")
    # the tests file itself never opens a real tree for writing either: the only real paths it names are RD1_REAL / RD2_REAL / RD3_REAL, read through loaders
    tests_src = (RL_DIR / "m8_rd4_tests.py").read_text(encoding="utf-8")
    for nd in ast.walk(ast.parse(tests_src)):
        if isinstance(nd, ast.Call):
            f = nd.func
            fname = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
            if fname in write_attrs | writers | copy_funcs and any(n in ast.unparse(nd) for n in ("RD1_REAL", "RD2_REAL", "RD3_REAL")):
                raise Failure(f"the tests write through a real tree's path: {ast.unparse(nd)[:100]}")
    return {"modules": len(NEW_MODULES)}


def unit_no_nondeterminism_in_rd4() -> Dict[str, Any]:
    """Decision 10: no test anywhere in the rd4 suite or modules is non-deterministic. The suite uses keyed sha256 streams, the virtual clock and the lock-step pool; the only wall-clock readings are
    timings written to records (never asserted except as generous upper bounds); the only real-process test (the fake game) is NOT in the suite or the preflight but in the separate non-gating
    `integration` command. Enforced here by scanning the sources: no `random`, `secrets`, `uuid` or `os.urandom`, no sleep, no `datetime.now`/`time.time` inside an assertion of the tests, and the
    fake-game test is absent from the suite."""
    banned_mods = {"random", "secrets", "uuid"}
    for pth in [RL_DIR / f"{n}.py" for n in NEW_MODULES] + [RL_DIR / "m8_rd4_tests.py"]:
        src = pth.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for nd in ast.walk(tree):
            if isinstance(nd, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in nd.names] if isinstance(nd, ast.Import) else [nd.module or ""]
                check(not any(n.split(".")[0] in banned_mods for n in names), f"{pth.name} imports a source of randomness")
            if isinstance(nd, ast.Call):
                call = ast.unparse(nd.func)
                check(call not in ("time.sleep", "os.urandom") and not call.startswith("random."), f"{pth.name}: {call}")
    src = (RL_DIR / "m8_rd4_tests.py").read_text(encoding="utf-8")
    for fn in ast.walk(ast.parse(src)):
        if isinstance(fn, ast.FunctionDef) and fn.name != "unit_no_nondeterminism_in_rd4":
            for nd in ast.walk(fn):
                if isinstance(nd, ast.Call) and ast.unparse(nd.func) == "check":
                    cond = ast.unparse(nd.args[0]) if nd.args else ""
                    check("time.time" not in cond and "perf_counter" not in cond and "datetime" not in cond, f"{fn.name}: an assertion reads the wall clock: {cond[:80]}")
    check("cmd_run4_with_fake_game" not in {n for n, _fn in TESTS} and "cmd_run4_with_fake_game" in {n for n, _fn in INTEGRATION},
          "the one test that starts real worker processes is not in the suite (and so not in the preflight): it is the separate, non-gating `integration` command")
    pre = (RL_DIR / "m8_rd4_session.py").read_text(encoding="utf-8")
    check('"integration"' not in pre and "INTEGRATION" not in pre, "the preflight does not run the integration command")
    return {"modules": len(NEW_MODULES)}


def unit_tracked_files_unchanged4() -> Dict[str, Any]:
    import m8_rd_session as ses1

    check(ses1.tracked_changes() == [], f"tracked files differ from HEAD: {ses1.tracked_changes()[:5]}")
    check(ses1.untracked_not_new() == [], f"git status shows more than new files: {ses1.untracked_not_new()[:5]}")
    for f in EARLIER_FILES:
        r = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", str(RL_DIR / f"{f}.py")], cwd=REPO_ROOT)
        check(r.returncode == 0, f"{f}.py differs from HEAD")
        r = subprocess.run(["git", "ls-files", "--error-unmatch", str(RL_DIR / f"{f}.py")], cwd=REPO_ROOT, capture_output=True)
        check(r.returncode == 0, f"{f}.py is not tracked")
    new_docs = ("docs/rl_m8_rd4_decisions_2026-10-03.md", "docs/rl_m8_rd4_implementation.md")
    for d in ses4.DOC_FILES:
        if d in new_docs:
            continue
        r = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", str(REPO_ROOT / d)], cwd=REPO_ROOT)
        check(r.returncode == 0, f"{d} differs from HEAD")
        r = subprocess.run(["git", "ls-files", "--error-unmatch", str(REPO_ROOT / d)], cwd=REPO_ROOT, capture_output=True)
        check(r.returncode == 0, f"{d} is not tracked")
    return {"earlier_files": len(EARLIER_FILES)}


def unit_snapshot_tool4() -> Dict[str, Any]:
    t = tmpdir("m8sn4_")
    dest = t / "snap"
    r = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_rd4_snapshot.py"), "snapshot", "--dest", str(dest)], capture_output=True, text=True, timeout=1800)
    check(r.returncode == 0, f"snapshot: {r.stdout[-500:]} {r.stderr[-500:]}")
    rec = json.loads((dest / "snapshot.json").read_text(encoding="utf-8"))
    check(rec["result"] == "PASS" and rec["n_files"] > 30 and not rec["problems"] and not rec["identity_code_mismatch"] and not rec["identity_docs_mismatch"],
          f"snapshot record: {rec['result']} {rec['problems']} {rec['identity_code_mismatch']} {rec['identity_docs_mismatch']}")
    names = {f["path"] for f in rec["files"]}
    check({"rl/m8_rd4_select.py", "rl/m8_rd4_run.py", "rl/m8_rd4_rule.py", "rl/m8_rd4_claims.py", "rl/m8_rd3_run.py", "rl/m8_rd_select2.py", "rl/m8_rd2_run.py", "rl/m8_rd_cells.py",
           "docs/rl_m8_rd_continuation_proposal_2026-10-02.md", "docs/rl_m8_rd3_stop_review_2026-10-03.md", "docs/rl_m8_rd3_results_2026-10-02.md"} <= names,
          "the snapshot holds the rd1, rd2, rd3 and rd4 code and the reviews")
    if (REPO_ROOT / "docs" / "rl_m8_rd4_decisions_2026-10-03.md").is_file():
        check("docs/rl_m8_rd4_decisions_2026-10-03.md" in names, "and the rd4 decisions")
    r = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_rd4_snapshot.py"), "verify", "--dest", str(dest)], capture_output=True, text=True, timeout=1800)
    check(r.returncode == 0, f"verify: {r.stdout[-300:]}")
    r = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_rd4_snapshot.py"), "snapshot", "--dest", str(dest)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 2, "an existing destination is never overwritten")
    victim = dest / "files" / "rl" / "m8_rd4_select.py"
    victim.write_bytes(victim.read_bytes() + b"\n#tampered\n")
    r = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_rd4_snapshot.py"), "verify", "--dest", str(dest)], capture_output=True, text=True, timeout=1800)
    check(r.returncode == 1 and "m8_rd4_select.py" in r.stdout, "a tampered copy fails the verification")
    ps = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_rd4_snapshot.py"), "powershell", "--dest", str(dest)], capture_output=True, text=True, timeout=60)
    check("Get-FileHash" in ps.stdout, "the independent re-hash script is generated")
    shutil.rmtree(t, ignore_errors=True)
    return {"files": rec["n_files"]}


# -- the closed real trees (read only) -----------------------------------------------------------------------------------------------------------------


def unit_open_protocol_real_trees4() -> Dict[str, Any]:
    """The open protocol R1-R5 on the real, closed rd1, rd2 and rd3 trees and their D: increments (read only): all three trees equal their increments, rd3's closing archive rebuilds (zero ticks) and
    its session digests equal the v2 digest recomputed from the current contract, the inherited archive meets the claim preconditions, and the closing overlay reproduces rd3's record exactly."""
    check((RD3_REAL / "archive" / "manifest.sha256").is_file() and ses4.INCREMENT_RD3.is_dir() and ses4.INCREMENT_RD2.is_dir() and ses4.INCREMENT_RD1.is_dir(), "the closed rd3 tree and the three D: increments are required")
    op = ses4.open_protocol4()
    check(op["ok"], f"the open protocol on the real trees: {op['problems']}")
    r1 = {w: op[f"R1_{w}_immutability"] for w in ("rd1", "rd2", "rd3")}
    check(r1["rd1"]["files"] == 166 and r1["rd2"]["files"] == 62 and r1["rd3"]["files"] == 77 and r1["rd3"]["bytes"] == 114_026_700 and r1["rd3"]["manifest_sha256"] == r4.RD3_INCREMENT_MANIFEST_SHA256
          and r1["rd2"]["manifest_sha256"] == r3.RD2_INCREMENT_MANIFEST_SHA256 and r1["rd1"]["manifest_sha256"] == rs.RD1_INCREMENT_MANIFEST_SHA256, f"R1: {r1}")
    f3 = op["R2_R4_rd3_archive"]
    check(f3["counts"] == {"cells": 26371, "bursts": 10406, "events": 20814} and f3["dispatch_iterations"] == [0, 10405] and f3["first_rd4_iteration"] == 10406 and f3["rd3_checkpoint_seq"] == 32
          and f3["audit"]["ok"] and f3["audit"]["cells"] == 26371, f"R2/R4 (rd3): {f3}")
    check(all(e["digest"] == f3["digest_recomputed"] for e in f3["session_events"]) and [e["name"] for e in f3["session_events"]] == ["rd2", "rd3"], "rd2's and rd3's session digests equal the v2 digest recomputed")
    check(f3["diag2"] == {"bound_violations": 0, "doomed_incumbent_replacements": 8004, "newly_descent_doomed": 12883, "revivals": 8472}, "rd3's counters")
    check(f3["inherited"] == r4.INHERITED_FACTS and f3["inherited"]["wall_top_cell_ids"] == [18318, 18767] and f3["inherited"]["cells_left_of_boundary"] == 54, f"the inherited claim facts: {f3['inherited']}")
    ov = op["R5_overlay"]
    check(ov["ok"] and ov["stored_close_counts_equal"] and ov["sha256"] == r4.CLOSING_OVERLAY_SHA256 and ov["counts"]["eligible_v2"] == 16610 and ov["counts"]["cells"] == 26371,
          f"R5: the closing overlay reproduces rd3's record: {ov['sha256']} {ov['counts']['eligible_v2']}")
    return {"overlay": ov["sha256"][:12], "cells": f3["counts"]["cells"]}


def unit_report4_on_real_rd3() -> Dict[str, Any]:
    """The reference columns of rd4's report, recomputed from the real closed archives, equal what rd3 stored; the ledger replay's seen-at-dispatch readings and the selection estimates reproduce the stop
    review's independent figures (its sections 1.2 and 3.3); the v3 weights on the real archive at the open."""
    check((RD3_REAL / "archive" / "manifest.sha256").is_file() and (RD2_REAL / "archive" / "manifest.sha256").is_file() and (RD1_REAL / "archive" / "manifest.sha256").is_file(), "the closed trees are required")
    stored = json.loads((RD3_REAL / "derived" / "report_after_run.json").read_text(encoding="utf-8-sig"))
    base, meta = s4.Archive4.read_dir(RD3_REAL / "archive")
    a2, _m2 = s2.Archive2.read_dir(RD2_REAL / "archive")
    a1, _m1 = s2.Archive2.read_dir(RD1_REAL / "archive")
    rng = base.iteration_ranges()
    check(rng == {"rd1": (0, 2174), "rd2": (2175, 6211), "rd3": (6212, 10405), "rd4": (None, None)}, f"rd3's closing archive: {rng}")
    ref3 = rpt2.diagnostics(base, 6212, 10405, first_new_cell=len(a2.cells))

    def norm(x: Any) -> Any:
        d = json.loads(json.dumps(x, default=str))
        d.pop("iterations", None)
        return d

    check(norm(ref3) == norm(stored["rd3"]), "rd3's reference column equals the diagnostics rd3 stored")
    check(norm(rpt2.diagnostics(a2, 2175, 6211, first_new_cell=len(a1.cells))) == norm(stored["rd2_reference"]), "rd2's reference column equals the one rd3 stored")
    check(norm(rpt2.diagnostics(a1, 0, 2174, first_new_cell=0)) == norm(stored["rd1_reference"]), "rd1's reference column equals the one rd3 stored")
    check([ref3["D1_regions"][k]["n"] for k in ("below", "beside", "onlow", "onhigh")] == [946, 740, 1611, 897] and ref3["returns"] == 4194 and ref3["D4_supply"]["launch_capable_cells_created"] == 109, "rd3's published figures")
    lines = str(meta["pin_tick0"]["lines"])
    aud = s4.audit4(base, lines, collect_rows_from=0)
    check(aud["ok"] and aud["cells"] == 26371 and aud["events"] == 20814, f"audit4 on the REAL rd3 closing archive (rd1 under v1, rd2 and rd3 under v2): {aud['problems']}")
    rows = aud["dispatch_rows"]
    check(len(rows) == 10406, f"one row per dispatch: {len(rows)}")
    by = rpt4.session_rows(rows, base)
    check({k: len(v) for k, v in by.items()} == {"rd1": 2175, "rd2": 4037, "rd3": 4194, "rd4": 0}, "rows by session")
    sd3 = rpt4.seen_distribution(by["rd3"])
    check([sd3[k]["dispatches"] for k in ("0-1", "2-3", "4-7", "8-15", "16-31", "32-63", "64+")] == [600, 821, 971, 936, 667, 177, 22], f"rd3's seen-at-dispatch distribution equals the stop review's 'real' row: {sd3}")
    check(sd3["seen_ge_8"]["dispatches"] == 1802, "1,802 of rd3's 4,194 dispatches started from a cell seen 8 or more times")
    cs3 = rpt4.creation_shares(by["rd3"])
    check([cs3[k]["dispatches"] for k in ("rd1", "rd2", "rd3", "rd4")] == [1361, 2234, 599, 0], f"rd3's dispatches by the start cell's session of creation equal the stop review's table: {cs3}")
    cs2 = rpt4.creation_shares(by["rd2"])
    check([cs2[k]["dispatches"] for k in ("rd1", "rd2")] == [2077, 1960], "and rd2's")
    mech = rule4.mechanism(returns=4194, seen_ge_8=1802, new_cells=len(base.cells) - len(a2.cells))
    check(mech["verdict"] == "MECHANISM_HOLDS" and abs(mech["new_cells_per_return"] - 7309 / 4194) < 1e-12, f"rd3's own readings: {mech['seen_ge_8_share']:.4f} of returns from seen >= 8, {mech['new_cells_per_return']:.4f} new cells per return")
    # the selection estimates at the rd4 open (the stop review's section 3.3), exactly
    fp = ses4.open_frontier_probabilities(base)
    check(abs(fp["left_of_wall_eligible"]["v2"] - 0.007022974984103937) < 1e-12 and abs(fp["left_of_wall_eligible"]["v3"] - 0.010580037339991535) < 1e-12 and fp["left_of_wall_eligible"]["cells"] == 47,
          f"47 eligible left-of-wall cells: 0.70 % under v2, 1.06 % under v3 per dispatch: {fp['left_of_wall_eligible']}")
    check(abs(fp["wall_top_cells"]["v2"] - 0.00043552675553680867) < 1e-12 and abs(fp["wall_top_cells"]["v3"] - 0.0006523641495922712) < 1e-12 and fp["wall_top_cells"]["cells"] == 2,
          f"the wall-top cells: 0.044 % under v2, 0.065 % under v3: {fp['wall_top_cells']}")
    check(abs(fp["seen_ge_8_eligible"]["v2"] - 0.48459729295517295) < 1e-12 and abs(fp["seen_ge_8_eligible"]["v3"] - 0.41464731207575034) < 1e-12, f"mass on cells seen 8 or more times: 48.5 % -> 41.5 %: {fp['seen_ge_8_eligible']}")
    p2, p3 = base.probabilities("v2"), base.probabilities("v3")
    check(abs(sum(p2.values()) - 1.0) < 1e-9 and abs(sum(p3.values()) - 1.0) < 1e-9 and set(p2) == set(p3) and len(p3) == 16610, "both distributions are over the 16,610 eligible cells and sum to one")
    check(base.probabilities() == base.probabilities("v2") and base.rd4_first_iteration is None, "an archive that has not begun rd4 is v2's by default")
    return {"seen_ge_8_rd3": sd3["seen_ge_8"]["dispatches"], "left_v2_v3": [fp["left_of_wall_eligible"]["v2"], fp["left_of_wall_eligible"]["v3"]]}


# -- `cmd_run` against a fake game (real lifecycle code, real worker processes; invariants only) -----------------------------------------------------------


def unit_cmd_run4_with_fake_game() -> Dict[str, Any]:
    """NOT part of the suite or the preflight (decision 10: it starts real worker processes, so its pass depends on process scheduling; it is the non-gating `integration` command).
    `run`'s own sequence against the REAL lifecycle code and a fake game, on a synthetic chain: the open protocol (R1-R5 at three levels), materialise, rd1's frozen runtime read in place, the
    whole-process-tree sampler, the real worker processes, the close checks. Only the preflight (tested on its own) and the kill-on-close job are replaced. The assertions hold under every schedule:
    the outcome is any registered one but INVALID (an INCOMPLETE is accepted only for a cap of the registered kinds). The four-diagnostics flag set of the verification replays is checked by a
    DIRECT replay of a constructed object through the real replay path."""
    import m7_runtime
    import m8_rd_session as ses1

    fg = t1.fake_game_setup("m8cr4_")
    t = fg["t"]
    (fg["exe_dir"] / "config.yml").write_text("fake: true\n", encoding="utf-8")
    fx = t1.fake_flags(fg, "easy")
    fv = dict(fx, SSB64_RL_ENTITY="1", SSB64_RL_TARGET_DIAG="1", SSB64_RL_INPUT="1")
    saved1 = {k: getattr(ses1, k) for k in ("EXECUTABLE", "EXE_DIR", "RUNTIME_FILES", "p1_inputs")}
    keys4 = ("RD1_ROOT", "RD2_ROOT", "RD3_ROOT", "RD4_ROOT", "APPROVAL", "INCREMENT_RD1", "INCREMENT_RD2", "INCREMENT_RD3", "EXECUTABLE", "EXE_DIR", "FLAGS_EXPLORE", "FLAGS_VERIFY", "N_WORKERS",
             "RD1_EXPECT", "RD2_EXPECT", "RD3_EXPECT", "CHECK_EXPECTED_OVERLAY", "preflight")
    saved4 = {k: getattr(ses4, k) for k in keys4}
    saved_job = m7_runtime.install_kill_on_close_job
    saved_prep = m7_runtime.prepare_worker_runtime
    saved_env2 = ses2.build_real_env2
    chain: Optional[Dict[str, Any]] = None
    try:
        ses1.EXECUTABLE = fg["cmd"]
        ses1.EXE_DIR = fg["exe_dir"]
        ses1.RUNTIME_FILES = ("BattleShip.o2r", "f3d.o2r", "gamecontrollerdb.txt")
        ses1.p1_inputs = lambda: stub.p1_inputs("easy", (200, 150))
        exe_sha = mw.sha256_file(fg["cmd"])
        rt_pins = ses1.runtime_pins()
        chain = build_chain4(CHAIN_WORLD, rd1_caps=CHAIN_RD1, rd2_ticks=CHAIN_RD2, rd3_ticks=CHAIN_RD3, flags={"explore": fx, "verify": fv}, exe_sha=exe_sha, runtime_files=rt_pins, cache=False)
        approval = {"approval": "APPROVED by the test", "revision": 1, "executable_sha256": exe_sha, "contracts": ses4.contract_digests4(chain["lines"]), "flags": {"explore": fx, "verify": fv},
                    "git_head": "0" * 40, "rule_sha256": rule4.rule_digest(), "p1": {}}
        (t / "approval.json").write_text(json.dumps(approval), encoding="utf-8")
        ses4.RD1_ROOT, ses4.RD2_ROOT, ses4.RD3_ROOT, ses4.RD4_ROOT = chain["rd1"], chain["rd2"], chain["rd3"], t / "rd4"
        ses4.APPROVAL, ses4.INCREMENT_RD1, ses4.INCREMENT_RD2, ses4.INCREMENT_RD3 = t / "approval.json", chain["inc1"], chain["inc2"], chain["inc3"]
        ses4.EXECUTABLE, ses4.EXE_DIR, ses4.FLAGS_EXPLORE, ses4.FLAGS_VERIFY = fg["cmd"], fg["exe_dir"], fx, fv
        ses4.N_WORKERS = 2
        ses4.RD1_EXPECT, ses4.RD2_EXPECT, ses4.RD3_EXPECT = chain["expect1"], chain["expect2"], chain["expect3"]
        ses4.CHECK_EXPECTED_OVERLAY = False
        ses4.preflight = lambda **k: {"ok": True, "problems": [], "executable_sha256": exe_sha, "git_head": "0" * 40}
        m7_runtime.install_kill_on_close_job = lambda: None

        def build(*a: Any, **k: Any) -> Any:
            env = saved_env2(*a, **k)
            env.analyse = stub.analyse                                   # the fake game has no target diagnostic
            return env

        ses2.build_real_env2 = build
        rc = ses4.cmd_run(overrides=dict(arm_tick_cap=3000, arm_caps={"T": 3000}, min_arm_ticks=1000, verify_threads=2, identity_k=4,
                                         wall_caps_s={"p1": 240.0, "T": 600.0, "C": 0.0, "verify": 600.0}, global_cap_s=1800.0, p1_tick_cap=20000))
        check(rc == 0, "cmd_run returned 0")
        root = t / "rd4"
        sd = root / "sessions" / "rd4"
        for f in ("open.json", "approval_copy.json", "p1.json", "identity_open.json", "rule.json", "close.json", "memory_summary.json", "memory_tree.jsonl", "state.json", "arm_T.json"):
            check((sd / f).is_file(), f"missing {f}")
        rule = json.loads((sd / "rule.json").read_text(encoding="utf-8"))
        check(rule["outcome"] in rule4.OUTCOMES and rule["outcome"] != "INVALID" and not rule["invalid"], f"cmd_run's session: {rule['outcome']} {rule['invalid']}")
        if rule["outcome"] == "INCOMPLETE":
            check(all(any(w in x for w in ("wall cap", "reached", "hard cap", "memory cap", "in flight", "BattleShip processes", "not ready")) for x in rule["incomplete"]),
                  f"an INCOMPLETE only for a cap or a lifecycle limit: {rule['incomplete']}")
        else:
            check(json.loads((sd / "arm_T.json").read_text(encoding="utf-8"))["ticks"] == 3000, "a complete session explored exactly its cap")
        op = json.loads((sd / "open.json").read_text(encoding="utf-8"))
        check(op["pins"]["approval_sha256"] == mw.sha256_file(t / "approval.json") and op["pins"]["executable_sha256"] == exe_sha, "the open record pins the approval and the executable")
        check((sd / "approval_copy.json").read_bytes() == (t / "approval.json").read_bytes(), "a verbatim copy of the approval")
        o = op["open_protocol"]
        check(all(o[f"R1_{w}_immutability"]["ok"] for w in ("rd1", "rd2", "rd3")) and o["R5_overlay"]["ok"] and o["R2_R4_rd3_archive"]["ok"], "the open record holds R1-R5 at three levels")
        check("wall_top_cells" in op["frontier_selection_at_the_open"] and op["frontier_selection_at_the_open"]["wall_top_cells"]["v3"] >= 0.0 and op["inherited_claim_facts"] == chain["expect3"]["inherited"],
              "the open record holds the frontier selection probabilities and the inherited claim facts")
        check((root / "base" / "events.jsonl").read_bytes() == (chain["rd3"] / "archive" / "events.jsonl").read_bytes(), "rd4's base ledger is rd3's closing ledger, byte for byte")
        log = t1.fake_log(fg)
        frozen_h = chain["frozen"]["BattleShip.cfg.json"]
        check(log and all(x["cfg_sha256"] == frozen_h for x in log), f"every process read rd1's FROZEN configuration ({len(log)} launches)")
        check(all(x["cfg_sha256"] != fg["live_hash"] for x in log), "no process read the live configuration")
        check(t1.wait_dead([x["pid"] for x in log], 30.0) == [], "no fake game process survived the run")
        check(all_immutability(chain)["ok"], "all three earlier trees are byte-identical to their increments after the run")
        # the four-diagnostics flag set of the verification replays: a direct replay of a constructed candidate through the real replay path
        meta1 = json.loads((chain["rd1"] / "archive" / "archive_meta.json").read_text(encoding="utf-8"))
        cfg = ses4.run_config(root=t / "rd4")
        env = ses4.build_real_env4(cfg, chain["rd1"] / "archive" / "runtime", meta1["pins"]["frozen_sha256"], {"executable_sha256": exe_sha, "runtime_files": meta1["pins"]["runtime_files"]})
        env.analyse = stub.analyse
        words = bytes(int.from_bytes(hashlib.sha256(f"direct|{i}".encode()).digest()[:4], "big") % 72 for i in range(40))
        before = len(t1.fake_log(fg))
        trace = env.replay({"cid": 77, "kind": "t", "words": words}, 40, "direct_replay", 0)
        after = t1.fake_log(fg)
        check(len(after) == before + 1, f"the direct replay launched one process ({before} -> {len(after)})")
        fl = after[-1]["flags"]
        check(all(fl.get(k) == "1" for k in ("SSB64_RL_SPATIAL", "SSB64_RL_ENTITY", "SSB64_RL_TARGET_DIAG", "SSB64_RL_INPUT", "SSB64_RL_NO_RENDER", "SSB64_RAPHNET_DISABLE")),
              f"the verification replay ran with the four diagnostics: {fl}")
        check(after[-1]["cfg_sha256"] == frozen_h and trace["submitted"] + trace["unsent"] == 40 and trace["consumed_tick_mismatch"] is None, "the direct replay read the frozen configuration and kept the tick contract")
        check(t1.wait_dead([x["pid"] for x in after], 30.0) == [], "no replay process survived")
        # the command refuses when the preflight does, before creating anything
        ses4.preflight = lambda **k: {"ok": False, "problems": ["x"]}
        ses4.RD4_ROOT = t / "rd4_never"
        check(ses4.cmd_run() == 2 and not (t / "rd4_never").exists(), "a failing preflight refuses before anything is created")
    finally:
        ses2.build_real_env2 = saved_env2
        for k, v in saved4.items():
            setattr(ses4, k, v)
        for k, v in saved1.items():
            setattr(ses1, k, v)
        m7_runtime.install_kill_on_close_job = saved_job
        m7_runtime.prepare_worker_runtime = saved_prep
        w2.WriteGuard.clear()
        shutil.rmtree(t, ignore_errors=True)
        if chain is not None:
            shutil.rmtree(chain["t"], ignore_errors=True)
    return {"launches": len(log), "outcome": rule["outcome"]}


def unit_scanner_vs_analyser_on_real_traces() -> Dict[str, Any]:
    """The claim that a `left` candidate without `left_floor`, `left_break` or `clear` cannot raise m rests on the burst scanner's landing label (`floor_line_id` of a grounded live tick) being a superset
    of the analyser's landing (`m7g_fixture.classify_ground` against the decoded geometry). The synthetic stub states the two rules identically, so this test reads the REAL stored verification traces of
    rd1, rd2 and rd3 (read only) and asserts the agreement on every grounded live step: L<n> <-> floor line n, moving_platform <-> line 19, and never an unmatched ground."""
    import m7g_fixture as fx

    files = sorted(p for r in (REPO_ROOT / "runs" / "m8_rd" / "sessions" / "rd1", REPO_ROOT / "runs" / "m8_rd_rd2" / "sessions" / "rd2", REPO_ROOT / "runs" / "m8_rd_rd3" / "sessions" / "rd3")
                   for p in (r / "verification").glob("*.json.gz"))
    if not files:
        return {"skipped": "the stored verification traces are not present (historical run data is not in a fresh clone)"}
    geo = fx.decode_stage_geometry()
    seen: Dict[Tuple[Optional[str], int], int] = {}
    for p in files:
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            tr_ = json.load(fh)
        for st in tr_["steps"]:
            o = st["observation"]
            if o.get("fighter_valid") == 1 and o.get("btt_active") == 1 and o.get("ground_air_state") == 0:
                key = (fx.classify_ground(geo, o), int(st["spatial"]["fighter"]["floor_line_id"]))
                seen[key] = seen.get(key, 0) + 1
    check(sum(seen.values()) >= 1000, f"too few grounded steps to compare: {sum(seen.values())}")
    for (cls, line), n in seen.items():
        ok = (cls == f"L{line}") or (cls == "moving_platform" and line == 19)
        check(ok, f"the analyser's {cls} and the scanner's floor line {line} disagree on {n} steps")
    return {"traces": len(files), "grounded_steps": sum(seen.values()), "pairs": {f"{c}|{l}": n for (c, l), n in sorted(seen.items(), key=lambda kv: str(kv[0]))}}


def unit_registry_has_no_inherited_milestone_events() -> Dict[str, Any]:
    """The registry-level claim precondition (review finding 6), on the REAL rd1, rd2 and rd3 candidate registries (read only), and its refusal on constructed ones."""
    roots = (REPO_ROOT / "runs" / "m8_rd", REPO_ROOT / "runs" / "m8_rd_rd2", REPO_ROOT / "runs" / "m8_rd_rd3")
    if all((r / "sessions").is_dir() for r in roots):
        facts = r4.registry_milestone_events(*roots)
        check(r4.registry_precondition_problems(facts) == [], f"the real registries hold a milestone event: {facts}")
        check(all(facts[k] is not None and facts[k]["candidates"] > 0 for k in ("rd1", "rd2", "rd3")), f"a registry is empty: {facts}")
    good = {"rd1": {"left_floor": 0, "left_break": 0, "clear": 0, "candidates": 3}, "rd2": {"left_floor": 0, "left_break": 0, "clear": 0, "candidates": 3},
            "rd3": {"left_floor": 0, "left_break": 0, "clear": 0, "candidates": 3}}
    check(r4.registry_precondition_problems(good) == [], "a registry without milestone events passes")
    for k in ("left_floor", "left_break", "clear"):
        bad_ = {n: dict(v) for n, v in good.items()}
        bad_["rd2"][k] = 1
        check(len(r4.registry_precondition_problems(bad_)) == 1, f"a registry with a {k} event is refused")
    check(len(r4.registry_precondition_problems(dict(good, rd3=None))) == 1, "a missing registry is refused")
    t = tmpdir("m8reg4_")
    for name in ("rd1", "rd2", "rd3"):
        (t / name / "sessions" / name).mkdir(parents=True)
    (t / "rd1" / "sessions" / "rd1" / "ledger_T.json").write_text(json.dumps({"candidates": [{"kind": "t", "first": {}}, {"kind": "left", "first": {"left_live": 5}}]}), encoding="utf-8")
    (t / "rd2" / "sessions" / "rd2" / "ledger_T.json").write_text(json.dumps({"candidates": [{"kind": "left", "first": {"left_live": 5, "left_floor": 9}}]}), encoding="utf-8")
    f = r4.registry_milestone_events(t / "rd1", t / "rd2", t / "rd3")
    check(f["rd1"] == {"left_floor": 0, "left_break": 0, "clear": 0, "candidates": 2} and f["rd2"]["left_floor"] == 1 and f["rd3"] is None, f"the registry reader: {f}")
    return {"checked_real": all((r / "sessions").is_dir() for r in roots)}


# -- the registry and the CLI ----------------------------------------------------------------------------------------------------------------------------------


def _earlier(name: str, table: Sequence[Tuple[str, Callable[[], Dict[str, Any]]]], prefix: str) -> Tuple[str, Callable[[], Dict[str, Any]]]:
    fn = dict(table)[name]
    return f"{prefix}:{name}", fn


TESTS: List[Tuple[str, Callable[[], Dict[str, Any]]]] = [
    ("rd4_contract", unit_rd4_contract), ("select_v3_formula", unit_select_v3_formula), ("archive4_draw_and_weights_switch", unit_archive4_draw_and_weights_switch),
    ("begin_rd4_and_persistence", unit_begin_rd4_and_persistence), ("ledger_rebuild4", unit_ledger_rebuild4), ("dispatch_rows_and_mechanism_inputs", unit_dispatch_rows_and_mechanism_inputs),
    ("rule4_module", unit_rule4_module), ("identity_samples4", unit_identity_samples4), ("report_readings", unit_report_readings), ("claims_pools_and_plan", unit_claims_pools_and_plan),
    ("claim_cases_on_stub_traces", unit_claim_cases_on_stub_traces), ("resume_three_level_synthetic", unit_resume_three_level_synthetic),
    ("precondition_refuses_inherited_milestones", unit_precondition_refuses_inherited_milestones), ("session4_small_run", unit_session4_small_run),
    ("session4_refuses_unbegun_archive", unit_session4_refuses_unbegun_archive), ("session4_outcomes_and_stops", unit_session4_outcomes_and_stops),
    ("session4_mechanism_and_line", unit_session4_mechanism_and_line), ("claim_cases_session", unit_claim_cases_session), ("verification_capacity_flood", unit_verification_capacity_flood),
    ("session4_determinism", unit_session4_determinism), ("write_guard_three_roots", unit_write_guard_three_roots), ("budget_projection4", unit_budget_projection4),
    ("approval_isolated4", unit_approval_isolated4), ("import_isolation4", unit_import_isolation4), ("source_guard4", unit_source_guard4), ("no_nondeterminism_in_rd4", unit_no_nondeterminism_in_rd4),
    ("tracked_files_unchanged4", unit_tracked_files_unchanged4), ("snapshot_tool4", unit_snapshot_tool4), ("open_protocol_real_trees4", unit_open_protocol_real_trees4),
    ("report4_on_real_rd3", unit_report4_on_real_rd3), ("scanner_vs_analyser_on_real_traces", unit_scanner_vs_analyser_on_real_traces),
    ("registry_has_no_inherited_milestone_events", unit_registry_has_no_inherited_milestone_events),
] + [_earlier(n, t3.TESTS, "rd3") for n in RD3_PURE] + [_earlier(n, t1.TESTS, "rd1") for n in RD1_PURE] + [_earlier(n, t2.TESTS, "rd2") for n in RD2_PURE]


# NOT part of the suite, the preflight or any Part B condition: tests that start real processes (decision 10). Run with `python rl/m8_rd4_tests.py integration`.
INTEGRATION: List[Tuple[str, Callable[[], Dict[str, Any]]]] = [("cmd_run4_with_fake_game", unit_cmd_run4_with_fake_game)]


def _cleanup() -> None:
    while _TMP:
        shutil.rmtree(_TMP.pop(), ignore_errors=True)
    while t3._TMP:
        shutil.rmtree(t3._TMP.pop(), ignore_errors=True)


def run_unit(only: Optional[Sequence[str]] = None, out: Optional[Path] = None, table: Optional[Sequence[Tuple[str, Callable[[], Dict[str, Any]]]]] = None) -> int:
    passed, failed = 0, []
    results: Dict[str, Any] = {}
    t_all = time.perf_counter()
    for name, fn in (TESTS if table is None else table):
        if only and name not in only:
            continue
        t0 = time.perf_counter()
        try:
            detail = fn()
            results[name] = {"ok": True, "s": round(time.perf_counter() - t0, 1), "detail": detail}
            passed += 1
            print(f"PASS {name} ({time.perf_counter() - t0:.1f} s)", flush=True)
        except Exception as exc:  # noqa: BLE001
            results[name] = {"ok": False, "s": round(time.perf_counter() - t0, 1), "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-2500:]}
            failed.append(name)
            print(f"FAIL {name}: {type(exc).__name__}: {exc}\n{traceback.format_exc()[-1800:]}", flush=True)
        finally:
            _cleanup()
    for rec in list(_CHAIN4.values()) + list(t3._CHAIN.values()):
        shutil.rmtree(rec["t"], ignore_errors=True)
    for rec in getattr(t2, "_SYN", {}).values():
        shutil.rmtree(rec["t"], ignore_errors=True)
    total = passed + len(failed)
    if out is not None:
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "m8_rd4_unit.json").write_text(json.dumps({"passed": passed, "total": total, "failed": failed, "wall_s": round(time.perf_counter() - t_all, 1), "results": results}, indent=1,
                                                         default=str) + "\n", encoding="utf-8")
    print(f"{passed} / {total} passed (unit); wall {time.perf_counter() - t_all:.0f} s")
    return 0 if not failed else 1


# -- the production-count synthetic end-to-end run ---------------------------------------------------------------------------------------------------------------


def e2e(out: Path, small: bool = False, world: str = CHAIN_WORLD, use_async: bool = False) -> int:
    """The rd4 session at the registered counts (6,000,000 exploration ticks valid from 2,000,000, five workers, the registered caps and memory checks) against a synthetic chain (a synthetic rd1
    tree, a synthetic rd2 tree and a synthetic rd3 tree, each built by its own real engine, each with its verified increment) and the stub: the three-level resume (R1-R6), the closing v2 overlay of
    rd3's archive (the overlay at rd4's open), the selection `m8_rd_select_v3` under rd4's draws, P1 against the archive's pin, the open and close identity replays, the replacement and the
    descent-doom tree, the rule with the mechanism check and the line budget, the close audit of the four-part ledger, the prefix chain and verify-run, and the CLAIM CASES of decision 6: the
    session's first dispatches are (a) the continuation of an inherited left-of-wall cell that does not land, (b) the continuation of an inherited wall-top cell and (c) a burst from an inherited
    over-wall cell that lands on the left floor (the entry lies in the inherited prefix, the landing in the new burst). The default engine is the lock-step pool and the virtual clock: the run is a
    pure function of its configuration. `use_async` runs the real worker processes (a measurement run, not part of the suite). The world is synthetic: the outcome says nothing about Mario."""
    import m8_rd_session as ses1

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    problems: List[str] = []
    t0 = time.perf_counter()
    chain = build_chain4(world, cache=False)
    print(f"[e2e] synthetic chain built in {time.perf_counter() - t0:.0f} s: rd1 {chain['expect1']['cells']} cells, rd2 {chain['expect2']['cells']} cells, rd3 {chain['expect3']['cells']} cells, "
          f"rd2 outcome {chain['rd2_outcome']}, rd3 outcome {chain['rd3_outcome']}; inherited frontier {chain['expect3']['inherited']}", flush=True)
    root4 = out / "rd4"
    if root4.exists():
        shutil.rmtree(root4)
    kw: Dict[str, Any] = dict(checkpoint_every_s=20.0 if not use_async else 30.0)
    if small:
        kw.update(arm_tick_cap=200000, arm_caps={"T": 200000}, min_arm_ticks=60000, p1_tick_cap=70000)
    cfg = ses4.run_config(root=root4, **kw)
    op, a4 = open_chain4(chain, root4)
    cfg.session_dir.mkdir(parents=True)
    mw.ProvenanceGuard.install()
    mw.ProvenanceGuard.violations.clear()
    w2.WriteGuard.install([chain["rd1"], chain["rd2"], chain["rd3"]])
    logs: List[str] = []

    def log(s: str) -> None:
        line = f"[e2e {time.strftime('%H:%M:%S')}] {s}"
        logs.append(line)
        print(line, flush=True)

    clock = FakeClock()
    env = sync_env(world, [chain["rd1"], chain["rd2"], chain["rd3"]], clock, pins=chain["pins"], log=log)
    sampler = None
    try:
        import m7u_gate as g1

        env.private_mb = g1.private_mb
    except Exception:  # noqa: BLE001
        pass
    if use_async:
        env.now = time.monotonic
        sampler = ses1.make_sampler(out / "memory_tree.jsonl", cfg.memory_caps_mb)
        sampler.start()
        env.sampler = sampler
        env.tree_snapshot = lambda: getattr(sampler, "last", None)
    t1_ = time.perf_counter()
    cls = forced_session_cls(world, ("left_nolanding", "wall_continuation", "cross"))
    sess = cls(cfg, env, archive=a4, archive_pin=op["facts3"]["pin_tick0"], base_info={"overlay_sha256": op["overlay"]["sha256"]}, rd1_root=chain["rd1"], rd2_root=chain["rd2"], rd3_root=chain["rd3"],
               lines_sha256=chain["lines"], ckpt_seq=int(op["facts3"]["rd3_checkpoint_seq"]) + 1)
    if not use_async:
        sess.pool = SyncPool(env, cfg, clock)
    res = run4.run_all4(sess, immutability=lambda: all_immutability(chain))
    wall = time.perf_counter() - t1_
    mem = sampler.stop() if sampler is not None else None
    w2.WriteGuard.clear()
    rule, close = res["rule"], res["close"]
    vr = rpt4.verify_run4(root4, chain["rd3"], chain["rd2"], chain["rd1"], "rd4")
    report = rpt4.full_report4(root4, chain["rd3"], chain["rd2"], chain["rd1"], "rd4")
    want = cfg.arm_cap("T")
    if sess.ledgers["T"].ticks != want:
        problems.append(f"exploration ticks {sess.ledgers['T'].ticks} != {want}")
    if rule["outcome"] in ("INVALID", "INCOMPLETE"):
        problems.append(f"outcome {rule['outcome']}: {rule['invalid']} {rule['incomplete']}")
    if not vr["ok"]:
        problems.append(f"verify-run: {vr['problems']}")
    if not close.get("audit", {}).get("ok"):
        problems.append(f"close audit: {close.get('audit')}")
    if not close.get("prefix_chain", {}).get("ok"):
        problems.append(f"prefix chain: {close.get('prefix_chain')}")
    if not close.get("earlier_trees_immutability", {}).get("ok"):
        problems.append(f"earlier trees: {close.get('earlier_trees_immutability')}")
    if mem is not None and mem["breach"]:
        problems.append(f"memory sampler breach {mem['breach']}")
    if mw.ProvenanceGuard.violations:
        problems.append(f"guard violations {mw.ProvenanceGuard.violations[:2]}")
    if not all_immutability(chain)["ok"]:
        problems.append("a synthetic earlier tree changed")
    ver = json.loads((root4 / "sessions" / "rd4" / "verification.json").read_text(encoding="utf-8"))
    io_ = sess.open_identity_record
    if not (io_.get("ok") and io_.get("cells") == 16 and ver["identity"].get("verified") == ver["identity"].get("cells") == 16):
        problems.append(f"identity replays: open {io_.get('verified')}/{io_.get('cells')}, close {ver['identity']}")
    if sess.first_iteration != chain["expect3"]["dispatch_iterations"][1] + 1:
        problems.append("iterations do not continue from rd3's last")
    v = sess.verified or {"m": 0, "max_targets": 0}
    prior = r4.prior_milestones(chain["rd1"], chain["rd2"], chain["rd3"])
    again = rule4.apply(invalid=[], incomplete=[], m=v["m"], t=v["max_targets"], prior=prior, **rule["extra"]["rule_inputs"])
    for k in ("outcome", "m", "max_targets_verified", "any_stop"):
        if again[k] != rule[k]:
            problems.append(f"the recorded {k} {rule[k]} differs from the rule applied to the verified m and t {again[k]}")
    if again["mechanism"] != rule["mechanism"] or again["line"]["status"] != rule["line"]["status"]:
        problems.append("the recorded mechanism check or line status differs from the rule applied to the registered counts")
    # the claim cases of decision 6, through the session's own claims path
    forced = {f["kind"]: f for f in sess.forced}
    claim_cases: Dict[str, Any] = {"forced": forced}
    n_open = chain["expect3"]["cells"]
    if set(forced) != {"left_nolanding", "wall_continuation", "cross"} or any(f["cell"] >= n_open for f in forced.values()):
        problems.append(f"the forced dispatches are not the three inherited cells: {forced}")
    else:
        led = sess.ledgers["T"]
        cand = candidate_for_iteration(sess, forced["cross"]["iteration"], "left")
        claim = (ver["arm"]["claims"] or {}).get("crossing")
        if cand is None or claim is None or claim["cid"] != cand["cid"]:
            problems.append(f"the crossing from the inherited over-wall cell was not the verified crossing: {claim} vs {cand and cand['cid']}")
        else:
            with gzip.open(root4 / "sessions" / "rd4" / "verification" / f"{claim['label']}.json.gz", "rt", encoding="utf-8") as fp:
                trace = json.load(fp)
            e, l = trace_entry_landing(trace)
            claim_cases["crossing"] = {"entry_consumed_tick": e, "landing_consumed_tick": l, "inherited_prefix_words": forced["cross"]["L"], "cid": cand["cid"]}
            if not (e is not None and l is not None and e == claim["first_qualified_entry"] and e < forced["cross"]["L"] < l):
                problems.append(f"the crossing is not 'entry in the inherited prefix, landing in the new burst': {claim_cases['crossing']}")
        cand_b = candidate_for_iteration(sess, forced["left_nolanding"]["iteration"], "left")
        reps = [json.loads(x) for x in (root4 / "sessions" / "rd4" / "verification" / "replays.jsonl").read_text(encoding="utf-8").splitlines()]
        rep_b = next((r for r in reps if cand_b is not None and r["cid"] == cand_b["cid"]), None)
        claim_cases["left_continuation"] = {"candidate": cand_b["cid"] if cand_b else None, "replayed_exact": bool(rep_b and rep_b["exact"])}
        if not (cand_b and cl4.is_descriptive(cand_b) and rep_b and rep_b["exact"]):
            problems.append(f"the left continuation was not replayed exactly as a descriptive candidate: {claim_cases['left_continuation']}")
        rows_s = [json.loads(x) for x in (root4 / "sessions" / "rd4" / "wall_top_sightings.jsonl").read_text(encoding="utf-8").splitlines()]
        row = next((x for x in rows_s if x["iteration"] == forced["wall_continuation"]["iteration"]), None)
        claim_cases["wall_top_continuation"] = {"sighting": row, "sightings_total": len(rows_s), "l0_candidates": sum(1 for c in led.candidates if c["kind"] == "l0")}
        if not (row and row["start_cell_on_wall_top"] and row["first_tick_of_the_burst"]) or claim_cases["wall_top_continuation"]["l0_candidates"]:
            problems.append(f"the wall-top continuation: {claim_cases['wall_top_continuation']}")
    peak_mb = None
    try:
        import m7u_gate as g1b

        peak_mb = g1b.private_mb()
    except Exception:  # noqa: BLE001
        pass
    summary = {"small": small, "world": world, "engine": "async real worker processes" if use_async else "lock-step pool, virtual clock", "wall_s": round(wall, 1),
               "outcome": rule["outcome"], "m": rule["m"], "max_targets": rule["max_targets_verified"], "progress_basis": rule["progress_basis"], "stops": rule["any_stop"],
               "mechanism": rule["mechanism"], "line": rule["line"], "claim_cases": claim_cases,
               "ticks": sess.ledgers["T"].ticks, "exploration_wall_s_real_or_virtual": sess.arm_records["T"]["wall_s"], "stop": sess.arm_records["T"]["stop"],
               "cells_open": chain["expect3"]["cells"], "cells_close": len(sess.archive.cells), "bursts": len(sess.archive.bursts),
               "candidates": len(sess.ledgers["T"].candidates), "pools": ver.get("pools"), "phase_wall_s": sess.clock.to_json()["phase_wall_s"], "peak_main_private_mb": sess.clock.peak_mb,
               "main_private_mb_at_end": peak_mb, "memory_tree_peak": (mem or {}).get("peak"), "verify_run": vr["ok"], "replay_ticks": sess.ticks["replays"],
               "replays": ver["arm"]["replays"], "open_identity": io_, "identity_close": ver["identity"], "audit": close.get("audit"),
               "prefix_chain": {k: close.get("prefix_chain", {}).get(k) for k in ("ok", "problems")},
               "archive_stats": sess.archive.stats(), "diag2": {k: (len(x) if isinstance(x, list) else x) for k, x in sess.archive.diag2.items()}, "lifecycle_failures": sess.lifecycle_failures,
               "rule_inputs": rule["extra"]["rule_inputs"], "overlay_open": op["overlay"]["counts"], "overlay_close": close.get("archive", {}).get("overlay_close"),
               "wall_top_cells": report["new"]["rd4"]["wall_top"]["cells"], "dilution": rule["dilution"]["verdict"],
               "selection_probability_at_the_open": {m_: report["selection_probability_at_the_open"][m_]["total_probability"] for m_ in ("v2", "v3")}, "problems": problems}
    (out / "e2e.json").write_text(json.dumps(summary, indent=1, default=str) + "\n", encoding="utf-8")
    (out / "e2e.log").write_text("\n".join(logs) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=1, default=str))
    shutil.rmtree(chain["t"], ignore_errors=True)
    if not problems:
        shutil.rmtree(root4, ignore_errors=True)               # the synthetic rd4 tree is large and says nothing about Mario; e2e.json and e2e.log are the record
    print("E2E PASS" if not problems else f"E2E FAIL: {problems}")
    return 0 if not problems else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("unit", "e2e", "list", "integration"))
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--only", default=None)
    ap.add_argument("--small", action="store_true")
    ap.add_argument("--async", dest="use_async", action="store_true")
    ap.add_argument("--world", default=CHAIN_WORLD, choices=sorted(stub.WORLDS))
    a = ap.parse_args(argv)
    if a.cmd == "list":
        for name, _fn in TESTS:
            print(name)
        return 0
    if a.cmd == "unit":
        return run_unit(a.only.split(",") if a.only else None, a.out or Path(tempfile.mkdtemp(prefix="m8_unit4_")))
    if a.cmd == "integration":
        return run_unit(None, a.out or Path(tempfile.mkdtemp(prefix="m8_integration4_")), table=INTEGRATION)
    return e2e(a.out or Path(tempfile.mkdtemp(prefix="m8_e2e4_")), small=a.small, world=a.world, use_async=a.use_async)


if __name__ == "__main__":
    sys.exit(main())
