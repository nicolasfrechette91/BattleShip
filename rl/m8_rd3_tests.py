#!/usr/bin/env python3
"""M8-rd3 offline tests: zero native ticks. No BattleShip launch, no replay on a real process, no training.

    python rl/m8_rd3_tests.py unit [--out DIR] [--only NAME[,NAME]]
    python rl/m8_rd3_tests.py e2e  [--out DIR] [--small] [--world W] [--async]   # the production-count synthetic end-to-end run of the two-level resume
    python rl/m8_rd3_tests.py list

DETERMINISM (decisions I8). The session-level tests run the REAL session engine (Session / Session2 / Session3, the archive, the claims, the verification, the close checks, the
rule) against the synthetic stub world (rl/m8_rd_stub.py) through an in-process lock-step worker pool and a virtual clock: a job completes when it is sent, results are returned in
dispatch order, and time advances only with the engine's polls. A run is therefore a pure function of its configuration (tested: two runs agree on every ledger event, cell, word and
decision). No test depends on the scheduling of processes or on wall-clock time. The only tests that start real processes (the fake game behind the real lifecycle code) assert only
facts that hold under every schedule and never that a particular milestone, candidate or replay occurred.

The tests of rd1 and rd2 that run here (RD1_PURE, RD2_PURE) are the pure ones, classified one by one; their asynchronous tests are never run.

Light top-level imports only (spawned workers re-import this script).
"""
from __future__ import annotations

import argparse
import ast
import contextlib
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
from m8_rd_tests import Failure, check, raises, tmpdir  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
RL_DIR = Path(__file__).resolve().parent
RD1_REAL = REPO_ROOT / "runs" / "m8_rd"
RD2_REAL = REPO_ROOT / "runs" / "m8_rd_rd2"
NEW_MODULES = ("m8_rd3_select", "m8_rd3_resume", "m8_rd3_run", "m8_rd3_session", "m8_rd3_rule", "m8_rd3_report", "m8_rd3_snapshot")
RD1_FILES = ("m8_rd_cells", "m8_rd_explore", "m8_rd_archive", "m8_rd_claims", "m8_rd_rule", "m8_rd_worker", "m8_rd_run", "m8_rd_finish", "m8_rd_session", "m8_rd_report",
             "m8_rd_snapshot", "m8_rd_stub", "m8_rd_fakegame", "m8_rd_tests", "m8_rd_select2", "m8_rd_resume", "m8_rd2_worker", "m8_rd2_run", "m8_rd2_session", "m8_rd2_rule",
             "m8_rd2_report", "m8_rd2_snapshot", "m8_rd2_tests")
FLOOR_MIN = -600.0                                  # the synthetic worlds' lowest floor (the stub's floor 3)
# the pure tests of rd1 and rd2 (no process, no thread, no sleep, no wall-clock assertion; data from keyed streams, the stub in process, or the closed real trees, read only)
RD1_PURE = ("cells_contract", "cells_on_recorded_replies", "record_digests_across_flag_sets", "explore", "archive_ingest_rules", "archive_async_ingestion",
            "velocity_reversal_reading", "selection", "ledger_rebuild_and_audit", "checkpoint_atomicity", "coverage_set", "claims_ledger_rules", "claims_roundtrip_on_stub",
            "real_analysis_on_recorded_trace", "clear_facts", "worker_iterate_and_returns", "worker_horizon_fall_clear_control", "claims_batch_fill",
            "terminal_cells_are_returnable", "finish_error_keeps_the_clear", "rule_module", "clock_and_caps")
RD2_PURE = ("select2_contract", "bound_rule", "descent_tree_vs_reference", "descent_doom_semantics", "archive2_mode1_equals_v1", "select2_probabilities", "replacement_v2",
            "ledger_rebuild_v2", "begin_v2_and_persistence", "overlay", "iterate2_equals_iterate", "write_guard", "rule2_module", "report_on_rd1_reference",
            "open_overlay_on_rd1_reference", "budget_projection", "identity_samples")


# -- the deterministic engine: a virtual clock and an in-process lock-step worker pool ------------------------------------------------------------


class FakeClock:
    """Virtual time: it advances only when the engine polls the pool (a fixed step per poll)."""

    def __init__(self, step: float = 0.25):
        self.t = 1000.0
        self.step = float(step)

    def now(self) -> float:
        return self.t

    def tick(self) -> None:
        self.t += self.step


class SyncProc:
    exitcode = None

    def is_alive(self) -> bool:
        return True

    def terminate(self) -> None:
        pass

    def join(self, timeout: Optional[float] = None) -> None:
        pass


class SyncPool(mrun.WorkerPool):
    """The worker pool's interface, in process and in lock step. `send` runs the job to completion on the calling thread (the stub backend through the real `run_job`), `poll`
    returns the finished jobs in dispatch order and advances the virtual clock. The archive state at the dispatch of the k-th job of a round therefore excludes the ingestion of the
    earlier jobs of the round, exactly as with real workers that are all in flight."""

    def __init__(self, env: mrun.RunEnv, cfg: mrun.RunConfig, clock: FakeClock):
        super().__init__(env, cfg)
        self.clock = clock
        self.ctxs: List[Any] = []
        self.done: List[Tuple[int, str, Dict[str, Any]]] = []

    def start(self, n: int, timeout: float = 180.0) -> None:
        w2.register_jobs()
        clf = mcell.Classifier()
        for rank in range(n):
            spec = self.env.worker_spec(rank, self.cfg)
            backend = mw.make_backend(spec)
            fd = Path(spec["failure_dir"]) if spec.get("failure_dir") else None
            self.ctxs.append(mw.JobContext(backend, self.abort, clf, rank, fd))
            self.procs.append(SyncProc())
            self.conns.append(None)
        self.infos = [{"backend": "sync"} for _ in range(n)]

    def send(self, i: int, job: Dict[str, Any]) -> None:
        self.busy[i] = (job, self.env.now())
        res = mw.run_job(self.ctxs[i], job)
        res["provenance_violations"] = list(mw.ProvenanceGuard.violations)
        self.done.append((i, "result", res))

    def poll(self, timeout: float) -> List[Tuple[int, str, Dict[str, Any]]]:
        self.clock.tick()
        out, self.done = self.done, []
        for i, _k, _p in out:
            self.busy.pop(i, None)
        return out

    def retire(self, indices: Sequence[int], grace: float = 60.0) -> None:
        for i in indices:
            if i not in self.retired and i not in self.busy:
                self.retired.add(i)

    def kill_busy(self) -> List[int]:
        dead = list(self.busy)
        for i in dead:
            self.retired.add(i)
            self.busy.pop(i, None)
        return dead

    def stop(self, grace: float = 60.0) -> None:
        pass

    def reports(self, timeout: float = 20.0) -> List[Dict[str, Any]]:
        return [{} for _ in self.ctxs]


def sync_env(world: str, roots: Sequence[Path], clock: FakeClock, inject: Optional[Mapping[str, Any]] = None, *, pins: Optional[Mapping[str, Any]] = None,
             **kw: Any) -> mrun.RunEnv:
    def worker_spec(rank: int, cfg: Any) -> Dict[str, Any]:
        return {"rank": rank, "backend": "m8_rd_stub:StubBackend", "world": world, "inject": dict(inject or {}), "failure_dir": str(cfg.session_dir / "failures"),
                "protected_roots": [str(r) for r in roots]}

    def replay(cand: Mapping[str, Any], counted: int, label: str, slot: int) -> Dict[str, Any]:
        return stub.replay_trace(world, bytes(cand["words"][:counted]), label)

    return mrun.RunEnv(worker_spec=worker_spec, replay=replay, analyse=stub.analyse, p1_inputs=lambda: stub.p1_inputs(world), pins=dict(pins) if pins else {"stub": True},
                       now=clock.now, log=kw.pop("log", lambda s: None), **kw)


# -- synthetic builders: a chain rd1 -> rd2 (built by the real engines) ------------------------------------------------------------------------------


_CHAIN: Dict[str, Any] = {}
_TMP: List[Path] = []                               # temporary directories of the running test (removed by the runner after it)


def tree_expect2(root: Path) -> Dict[str, Any]:
    a, meta = s3.Archive3.read_dir(root / "archive")
    prev = json.loads((root / "archive.prev" / "archive_meta.json").read_text(encoding="utf-8"))
    its = sorted(e["it"] for e in a.events if e["ev"] == "dispatch")
    return {"cells": len(a.cells), "bursts": len(a.bursts), "events": len(a.events), "checkpoint_seq": meta["checkpoint_seq"], "previous_checkpoint_seq": prev["checkpoint_seq"],
            "dispatch_iterations": (its[0], its[-1]), "first_rd2_iteration": a.rd2_first_iteration}


def live_pins_of(chain: Mapping[str, Any]) -> Dict[str, Any]:
    p = chain["pins"]
    return {k: p[k] for k in ("executable_sha256", "runtime_files", "contracts", "flags")}


def both_immutability(cp: Mapping[str, Any]) -> Dict[str, Any]:
    a = rs.rd1_immutability(cp["rd1"], cp["inc1"])
    b = rs.rd1_immutability(cp["rd2"], cp["inc2"])
    return {"ok": bool(a["ok"] and b["ok"]), "problems": [f"rd1: {p}" for p in a["problems"]] + [f"rd2: {p}" for p in b["problems"]], "rd1": a, "rd2": b}


def build_chain(world: str = "hard", *, rd1_caps: Tuple[int, int] = (30000, 24000), rd2_ticks: int = 12000, flags: Optional[Mapping[str, Any]] = None, exe_sha: str = "e" * 64,
                runtime_files: Optional[Mapping[str, str]] = None, cache: bool = True, n_workers: int = 3) -> Dict[str, Any]:
    """A synthetic rd1 tree (rd1's own engine) and a synthetic rd2 tree (rd2's own engine on it), each with its verified increment, all through the lock-step pool: the chain is a pure
    function of its parameters."""
    key = f"{world}|{rd1_caps}|{rd2_ticks}|{bool(flags)}|{exe_sha}|{n_workers}"
    if cache and key in _CHAIN:
        return _CHAIN[key]
    import m8_rd_finish as fin
    import m8_rd_session as ses1
    import runs_backup as rb

    t = tmpdir("m8r3chain_")
    root1 = t / "rd1"
    rt = root1 / "archive" / "runtime"
    rt.mkdir(parents=True)
    (rt / "BattleShip.cfg.json").write_text(json.dumps({"CVars": {"frozen": "FROZEN-CONFIG"}}), encoding="utf-8")
    (rt / "imgui.ini").write_text("[frozen]\n", encoding="utf-8")
    frozen = {n: mw.sha256_file(rt / n) for n in mw.FROZEN_FILES}
    fl = dict(flags) if flags is not None else {"explore": ses1.FLAGS_EXPLORE, "verify": ses1.FLAGS_VERIFY}
    pins = {"executable_sha256": exe_sha, "runtime_files": dict(runtime_files or {"BattleShip.o2r": "a" * 64, "f3d.o2r": "b" * 64, "gamecontrollerdb.txt": "c" * 64}),
            "frozen_sha256": frozen, "contracts": ses1.contract_digests(), "flags": fl, "archive_id": "m8_rd_a1", "git_head": "0" * 40, "rule_sha256": "0" * 64, "p1": {},
            "approval_sha256": "0" * 64}
    t_cap, c_cap = rd1_caps
    cfg1 = t1.small_cfg(root1, arm_tick_cap=t_cap, min_arm_ticks=min(t_cap, c_cap) // 3, arm_caps={"T": t_cap, "C": c_cap}, n_workers=n_workers,
                        wall_caps_s={"p1": 90.0, "T": 300.0, "C": 300.0, "verify": 300.0}, global_cap_s=1200.0)
    clock = FakeClock()
    env1 = sync_env(world, [], clock, pins=pins)
    mw.ProvenanceGuard.install()
    mw.ProvenanceGuard.violations.clear()
    sess1 = mrun.Session(cfg1, env1)
    sess1.pool = SyncPool(env1, cfg1, clock)
    out1 = fin.run_all(sess1)
    check(out1["rule"]["outcome"] in ("PASS", "NULL", "INCONCLUSIVE") and not out1["rule"]["invalid"] and not out1["rule"]["incomplete"],
          f"the synthetic rd1 session: {out1['rule']['outcome']} {out1['rule']['invalid']} {out1['rule']['incomplete']}")
    inc1 = t / "inc1"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = rb.cmd_backup(root1, inc1, 2)
    check(rc == 0 and (inc1 / "verification.json").is_file(), f"the synthetic rd1 increment: {buf.getvalue()[-300:]}")
    lines = sess1.pin["lines"]
    expect1 = t2.tree_expect(root1)
    # rd2's pins carry the select_v2 contract digest, as the real rd2's did (rd1's predate it)
    pins2 = dict(pins, contracts=ses2.contract_digests2(str(lines)))
    chain: Dict[str, Any] = {"t": t, "rd1": root1, "inc1": inc1, "expect1": expect1, "pins": pins2, "pins_rd1": pins, "frozen": frozen, "lines": lines, "world": world,
                             "rd1_outcome": out1["rule"]["outcome"]}
    # rd2 on it
    root2 = t / "rd2"
    cfg2 = t2.small_cfg2(root2, n_workers=n_workers, arm_tick_cap=rd2_ticks, arm_caps={"T": rd2_ticks}, min_arm_ticks=rd2_ticks // 3, wall_caps_s={"p1": 90.0, "T": 300.0, "C": 0.0, "verify": 300.0},
                         global_cap_s=1200.0)
    op = ses2.open_protocol(root1, inc1, expect=expect1, check_overlay=False, live_pins=lambda: {k: pins[k] for k in ("executable_sha256", "runtime_files", "contracts", "flags")},
                            floor_min=FLOOR_MIN)
    check(op["ok"], f"rd2's open protocol on the synthetic rd1 tree: {op['problems']}")
    a2 = rs.materialise(root1, root2, facts=op["facts"], overlay=op["overlay"], lines_sha256=lines, meta_extra={"pins": pins2, "pin_tick0": op["facts"]["pin_tick0"], "ticks": {}, "ledger_T": {}},
                        increment_manifest_sha256=op["R1_rd1_immutability"]["manifest_sha256"], utc="2026-10-02T00:00:00Z", floor_min=FLOOR_MIN)
    cfg2.session_dir.mkdir(parents=True)
    w2.WriteGuard.install([root1])
    try:
        clock2 = FakeClock()
        env2 = sync_env(world, [root1], clock2, pins=pins2)
        sess2 = run2.Session2(cfg2, env2, archive=a2, archive_pin=op["facts"]["pin_tick0"], base_info={"overlay_sha256": op["overlay"]["sha256"]}, rd1_root=root1, lines_sha256=lines)
        sess2.pool = SyncPool(env2, cfg2, clock2)
        out2 = run2.run_all2(sess2, immutability=lambda: rs.rd1_immutability(root1, inc1))
    finally:
        w2.WriteGuard.clear()
    r2 = out2["rule"]
    check(r2["outcome"] in rule2.OUTCOMES and not r2["invalid"] and not r2["incomplete"], f"the synthetic rd2 session: {r2['outcome']} {r2['invalid']} {r2['incomplete']}")
    inc2 = t / "inc2"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = rb.cmd_backup(root2, inc2, 2)
    check(rc == 0 and (inc2 / "verification.json").is_file(), f"the synthetic rd2 increment: {buf.getvalue()[-300:]}")
    chain.update({"rd2": root2, "inc2": inc2, "expect2": tree_expect2(root2), "rd2_outcome": r2["outcome"], "rd2_m": r2["m"]})
    if cache:
        _CHAIN[key] = chain
    return chain


def copy_chain(chain: Mapping[str, Any]) -> Dict[str, Any]:
    """A private copy of a chain (mtimes kept, so every copy still equals its increment)."""
    import runs_backup as rb

    t = tmpdir("m8r3cp_")
    _TMP.append(t)
    for name in ("rd1", "inc1", "rd2", "inc2"):
        shutil.copytree(chain[name], t / name)
    for inc_key, dst in (("inc1", "rd1"), ("inc2", "rd2")):
        man = rb.read_manifest(chain[inc_key])
        for rel, (_sha, _size, mt) in man.items():
            os.utime(t / dst / rel.replace("/", os.sep), ns=(mt, mt))
    return dict(chain, t=t, rd1=t / "rd1", inc1=t / "inc1", rd2=t / "rd2", inc2=t / "inc2")


def small_cfg3(root: Path, **kw: Any) -> Any:
    base = dict(n_workers=3, arm_tick_cap=12000, arm_caps={"T": 12000}, min_arm_ticks=4000, p1_tick_cap=20000, replay_tick_cap=300000,
                wall_caps_s={"p1": 90.0, "T": 300.0, "C": 0.0, "verify": 300.0}, global_cap_s=1200.0, checkpoint_every_s=4.0, verify_threads=2, identity_k=6)
    base.update(kw)
    if "arm_tick_cap" in kw and "arm_caps" not in kw:
        base["arm_caps"] = {"T": kw["arm_tick_cap"]}
    return ses3.run_config(root=root, **base)


def open_chain3(cp: Mapping[str, Any], root3: Path) -> Tuple[Dict[str, Any], s3.Archive3]:
    """The rd3 open protocol (R1-R5, both levels) and the materialisation (R6) on a private copy of a chain."""
    op = ses3.open_protocol3(cp["rd1"], cp["rd2"], cp["inc1"], cp["inc2"], expect1=cp["expect1"], expect2=cp["expect2"], check_overlay=False,
                             live_pins=lambda: live_pins_of(cp), floor_min=FLOOR_MIN)
    check(op["ok"], f"the rd3 open protocol on a synthetic chain: {op['problems']}")
    a3 = r3.materialise3(cp["rd2"], root3, facts=op["facts2"], overlay=op["overlay"], lines_sha256=cp["lines"],
                         meta_extra={"pins": cp["pins"], "pin_tick0": op["facts2"]["pin_tick0"], "ticks": {}, "ledger_T": {}},
                         increment_manifest_sha256=op["R1_rd2_immutability"]["manifest_sha256"], utc="2026-10-02T00:00:00Z", floor_min=FLOOR_MIN)
    return op, a3


def run3_small(chain: Mapping[str, Any], *, world: Optional[str] = None, inject: Optional[Mapping[str, Any]] = None, env_kw: Optional[Mapping[str, Any]] = None,
               immutability: Optional[Callable[[], Mapping[str, Any]]] = None, env_kw_factory: Optional[Callable[[Mapping[str, Any], FakeClock], Mapping[str, Any]]] = None,
               clock_step: float = 0.25, session_cls: Any = None, pool_factory: Optional[Callable[[Any, Any, FakeClock], SyncPool]] = None,
               **cfg_kw: Any) -> Tuple[Dict[str, Any], Any, Path, Dict[str, Any]]:
    """The rd3 session (open protocol, materialise, Session3, run_all3) against a private copy of a synthetic chain and the stub, through the lock-step pool."""
    cp = copy_chain(chain)
    root3 = cp["t"] / "rd3"
    cfg = small_cfg3(root3, **cfg_kw)
    op, a3 = open_chain3(cp, root3)
    cfg.session_dir.mkdir(parents=True)
    mw.ProvenanceGuard.install()
    mw.ProvenanceGuard.violations.clear()
    w2.WriteGuard.install([cp["rd1"], cp["rd2"]])
    try:
        clock = FakeClock(clock_step)
        env = sync_env(world or cp["world"], [cp["rd1"], cp["rd2"]], clock, inject, pins=cp["pins"], **dict(env_kw or {}),
                       **dict(env_kw_factory(cp, clock) if env_kw_factory else {}))
        sess = (session_cls or run3.Session3)(cfg, env, archive=a3, archive_pin=op["facts2"]["pin_tick0"], base_info={"overlay_sha256": op["overlay"]["sha256"]}, rd1_root=cp["rd1"],
                                              rd2_root=cp["rd2"], lines_sha256=cp["lines"], ckpt_seq=int(op["facts2"]["rd2_checkpoint_seq"]) + 1)
        sess.pool = pool_factory(env, cfg, clock) if pool_factory else SyncPool(env, cfg, clock)
        out = run3.run_all3(sess, immutability=immutability or (lambda: both_immutability(cp)))
    finally:
        w2.WriteGuard.clear()
    return out, sess, root3, cp


def signature(root3: Path) -> Dict[str, Any]:
    """What must be identical between two runs of the same configuration: the archive's data files (but its meta, which carries timestamps) and the decision."""
    a = root3 / "archive"
    rule = json.loads((root3 / "sessions" / "rd3" / "rule.json").read_text(encoding="utf-8"))
    return {"files": {n: mw.sha256_file(a / n) for n in ("cells.jsonl", "bursts.bin", "bursts.idx.jsonl", "events.jsonl")},
            "rule": {k: rule[k] for k in ("outcome", "m", "max_targets_verified", "progress_basis", "any_stop", "dilution", "launch_capable_created")}}


def synth_archive3(seed: str = "s3", n1: int = 40, n2: int = 50, n3: int = 50, floor_min: float = -2100.0, lines: str = "lines") -> s3.Archive3:
    """A three-part archive from keyed random jobs: rd1's part under v1, rd2's under v2 (draw id _v2), rd3's under v2 with the rd3 draws."""
    rng = t2.Krng(seed)
    a = s3.Archive3("syn3", floor_min=floor_min)
    a.init_cell0(t1.key(0, 0), t1.mk_end(), bytes(32), bytes([1]) * 32)
    t2.drive2(a, rng, n1, 0, v2=False)
    a.begin_v2(n1, lines)
    t2.drive2(a, rng, n2, n1, v2=True)
    a.begin_rd3(n1 + n2, lines)
    t2.drive2(a, rng, n3, n1 + n2, v2=True)
    return a


def fresh3(aid: str = "t3", floor_min: float = -2550.0) -> s3.Archive3:
    a = s3.Archive3(aid, floor_min=floor_min)
    a.init_cell0(t1.key(0, 0), t1.mk_end(), bytes(32), bytes([1]) * 32)
    return a


# -- the contract, the archive, the ledger ---------------------------------------------------------------------------------------------------------


def unit_rd3_contract() -> Dict[str, Any]:
    check(s3.DRAW_SUFFIX == "_rd3" and s3.DRAW_SUFFIX_RD2 == "_v2" and s3.SESSION_NAME == "rd3" and s3.SESSION_NAME_RD2 == "rd2", "the session names and the draw suffixes")
    check(mx.select_key("m8_rd_a1_rd3", 6212) == "m8_rd|m8_rd_a1_rd3|select|6212", "the selection key string")
    check(mx.explore_key("m8_rd_a1_rd3", 6212, 3) == "m8_rd|m8_rd_a1_rd3|explore|6212|3", "the exploration key string")
    a = s3.Archive3("m8_rd_a1")
    check(a.draw_id_rd2 == "m8_rd_a1_v2" and a.draw_id_rd3 == "m8_rd_a1_rd3" and a.draw_id_rd2 != a.draw_id_rd3 and a.archive_id == "m8_rd_a1", "the draw ids")
    d = s3.draws_description()
    check(d["select"] == "m8_rd|<archive id>_rd3|select|<iteration>" and d["identity_open"].endswith("identity_open|rd3|<cell id>") and d["identity_close"].endswith("identity_close|rd3|<cell id>"),
          f"the registered key strings: {d}")
    check(len(s3.draws_digest()) == 64 and s3.draws_digest() == s3.draws_digest(), "the draws digest")
    check(rule3.rule_digest() != rule2.rule_digest() and rule3.RULE_ID == "m8_rd3_rule_v1", "rd3's own rule")
    check(rule3.SCOPE.startswith("M8-rd3: second continuation of archive m8_rd_a1") and "no control arm" in rule3.SCOPE and "not a policy result" in rule3.SCOPE, "the scope label")
    # the caps are rd2's, number for number (decision 3)
    c3, c2 = ses3.caps(), ses2.caps()
    check(c3 == c2, f"caps differ from rd2's: { {k: (c3[k], c2[k]) for k in c3 if c3[k] != c2.get(k)} }")
    cfg = ses3.run_config()
    check(cfg.session_id == "rd3" and cfg.root == ses3.RD3_ROOT and cfg.arm_cap("T") == 6_000_000 and cfg.min_arm_ticks == 2_000_000 and cfg.n_workers == 5 and cfg.burst_words == 120
          and cfg.horizon == 3600 and cfg.p1_tick_cap == 70_000 and cfg.replay_tick_cap == 400_000 and cfg.global_cap_s == 3600.0
          and dict(cfg.wall_caps_s) == {"p1": 240.0, "T": 3000.0, "C": 0.0, "verify": 360.0}, "run_config carries the registered values")
    check(ses3.RD3_ROOT.name == "m8_rd_rd3" and ses3.RD2_ROOT.name == "m8_rd_rd2" and ses3.RD1_ROOT.name == "m8_rd" and ses3.APPROVAL.name == "rl_m8_rd3_approval.json",
          "the roots and the approval path")
    # the selection is unchanged: the contract digest recomputed from the current code equals the one in rd2's own session event (the closed real tree, read only)
    if (RD2_REAL / "archive" / "events.jsonl").is_file():
        ev = ses3._events(RD2_REAL / "archive")
        check(len(ev) == 1 and ev[0]["name"] == "rd2" and ev[0]["first_iteration"] == 2175, f"rd2's session event: {ev}")
        import m7q_status_table as st

        meta = json.loads((RD2_REAL / "archive" / "archive_meta.json").read_text(encoding="utf-8"))
        want = s2.select2_contract_digest(st.load_table()["sha256"], meta["pin_tick0"]["lines"], float(meta["floor_min"]))
        check(ev[0]["digest"] == want, "rd2's recorded selection digest equals the digest recomputed from the current code: the selection is unchanged")
    return {"digest": s3.draws_digest()[:12]}


def unit_archive3_draw_switch() -> Dict[str, Any]:
    n1, n2, n3 = 40, 50, 50
    a = synth_archive3("sw", n1, n2, n3)
    check(a.mode == 2 and a.rd2_first_iteration == n1 and a.rd3_first_iteration == n1 + n2 and a.first_iteration == n1 + n2 and a.draw_id == a.draw_id_rd3, "the three-part archive")
    for it, want in ((0, "syn3_v2"), (n1 - 1, "syn3_v2"), (n1, "syn3_v2"), (n1 + n2 - 1, "syn3_v2"), (n1 + n2, "syn3_rd3"), (n1 + n2 + 1000, "syn3_rd3")):
        check(a.draw_for(it) == want, f"draw_for({it}) = {a.draw_for(it)}, expected {want}")
    check(a.iteration_ranges() == {"rd1": (0, n1 - 1), "rd2": (n1, n1 + n2 - 1), "rd3": (n1 + n2, n1 + n2 + n3 - 1)}, f"iteration ranges {a.iteration_ranges()}")
    # the selection is rd2's, byte for byte: Archive3.select equals Archive2.select with the iteration's draw id set by hand, and never leaves the draw id changed
    nxt = n1 + n2 + n3
    keep = a.draw_id
    for it in range(nxt, nxt + 40):
        got = a.select(it)
        a.draw_id = a.draw_id_rd3
        ref = s2.Archive2.select(a, it)
        a.draw_id = keep
        check(got.id == ref.id, f"iteration {it}: Archive3.select {got.id} differs from Archive2.select under the rd3 draw id {ref.id}")
    check(a.draw_id == keep, "select restores the draw id")
    differ = 0
    for it in range(nxt, nxt + 80):
        a.draw_id = a.draw_id_rd2
        old = s2.Archive2.select(a, it)
        a.draw_id = keep
        differ += int(old.id != a.select(it).id)
    check(differ > 0, "the rd3 draws are not the rd2 draws (the same iterations select differently)")
    # an iteration before rd3's first uses rd2's draws
    a.draw_id = a.draw_id_rd2
    ref_old = s2.Archive2.select(a, n1 + 3)
    a.draw_id = keep
    check(a.select(n1 + 3).id == ref_old.id, "an rd2 iteration is selected under the rd2 draw id")
    # mode 1 ignores the draw id: rd1's selection key is the archive id
    b = fresh3("m1")
    check(b.mode == 1 and b.select(5).id == march.Archive.select(b, 5).id, "mode 1 is rd1's selection")
    # rd3's explorer stream differs from rd2's for the same iteration
    w_rd3 = list(mx.words(lambda i: mx.explore_key("syn3_rd3", 7000, i), 60))
    w_rd2 = list(mx.words(lambda i: mx.explore_key("syn3_v2", 7000, i), 60))
    check(w_rd3 != w_rd2 and len(w_rd3) == 60, "the explorer draws are keyed by the session's draw id")
    return {"differ_of_80": differ}


def unit_begin_rd3_and_persistence() -> Dict[str, Any]:
    a = fresh3("br", -2550.0)
    raises(s3.Select3Error, lambda: a.begin_rd3(5, "L"), "rd3 cannot begin before rd2's session event")
    t2.drive2(a, t2.Krng("br"), 20, 0, v2=False)
    a.begin_v2(20, "L")
    t2.drive2(a, t2.Krng("br2"), 15, 20, v2=True)
    raises(s3.Select3Error, lambda: a.begin_rd3(30, "L"), "reusing a dispatched iteration is refused")
    a.apply_dispatch(500, 0, 0)
    raises(s3.Select3Error, lambda: a.begin_rd3(600, "L"), "a pending dispatch blocks the switch")
    a.note_failure(500, "x")
    raises(s3.Select3Error, lambda: a.begin_rd3(600, "another line table"), "a selection contract that is not rd2's is refused (the digest differs)")
    n_ev = len(a.events)
    ev = a.begin_rd3(600, "L")
    check(ev["name"] == "rd3" and ev["first_iteration"] == 600 and ev["draw_suffix"] == "_rd3" and ev["select"] == "m8_rd_select_v2" and a.events[-1] == ev and len(a.events) == n_ev + 1,
          "one session event")
    sess = [e for e in a.events if e["ev"] == "session"]
    check([e["name"] for e in sess] == ["rd2", "rd3"] and sess[0]["digest"] == sess[1]["digest"], "rd3's digest equals rd2's: the selection is unchanged")
    check(a.rd3_first_iteration == 600 and a.first_iteration == 600 and a.draw_id == a.draw_id_rd3 and a.rd2_first_iteration == 20, "state after the switch")
    raises(s3.Select3Error, lambda: a.begin_rd3(700, "L"), "a second switch is refused")
    # persistence: rd2-readable files, the prefix property and the reload
    t = tmpdir("m8r3p_")
    x = fresh3("br", -2550.0)
    t2.drive2(x, t2.Krng("br"), 20, 0, v2=False)
    x.begin_v2(20, "L")
    t2.drive2(x, t2.Krng("br2"), 15, 20, v2=True)
    march.save_checkpoint(t / "rd2" / "archive", x, {"checkpoint_seq": 20, "why": "x"})
    y, meta_y = s3.Archive3.read_dir(t / "rd2" / "archive")
    check(y.rd3_first_iteration is None and y.rd2_first_iteration == 20 and y.draw_id == y.draw_id_rd2, "an rd2 closing archive loads as an Archive3 before rd3")
    y.begin_rd3(35, "L")
    t2.drive2(y, t2.Krng("br3"), 12, 35, v2=True)
    march.save_checkpoint(t / "rd3" / "archive", y, {"checkpoint_seq": 21, "why": "x"})
    pp = rs.prefix_property(t / "rd2" / "archive", t / "rd3" / "archive")
    check(pp["ok"] and pp["events.jsonl"]["lines"] == len(x.events) and pp["bursts.idx.jsonl"]["lines"] == len(x.bursts), f"rd3's files begin with rd2's closing bytes: {pp}")
    z, meta_z = s3.Archive3.read_dir(t / "rd3" / "archive")
    check(meta_z["schema"] == s2.ARCHIVE_SCHEMA_V2 and meta_z["archive3_contract"] == s3.ARCHIVE3_CONTRACT and meta_z["rd2_first_iteration"] == 20 and meta_z["rd3_first_iteration"] == 35
          and meta_z["draw_ids"] == {"rd1": "br", "rd2": "br_v2", "rd3": "br_rd3"} and meta_z["floor_min"] == -2550.0, f"the rd3 directory is self-describing: {meta_z}")
    check(z.rd3_first_iteration == 35 and z.first_iteration == 35 and z.draw_id == "br_rd3" and z.mode == 2, "the reload knows the session switch")
    check([c.to_json() for c in z.cells] == [c.to_json() for c in y.cells] and z.diag2 == y.diag2 and z.desc == y.desc and z.bound == y.bound, "a reload reproduces cells, counters and derived flags")
    check(s3.audit3(z, "L")["ok"], "the reloaded three-part archive audits")
    check(s3.rebuild3(z, "L").events == z.events, "the rebuild reproduces the ledger")
    w, _m = s2.Archive2.read_dir(t / "rd3" / "archive")
    check(w.mode == 2 and w.first_iteration == 35, "rd2's loader reads the rd3 directory (mode 2; the last session's first iteration)")
    # adopt refuses archives that are not an rd2 archive (no session event, or an unexpected sequence)
    v1only = s2.Archive2("br")
    v1only.init_cell0(t1.key(0, 0), t1.mk_end(), bytes(32), bytes([1]) * 32)
    raises(s3.Select3Error, lambda: s3.Archive3.adopt(v1only), "an archive with no session event is not an rd2 archive")
    # the prefix property fails when rd2's bytes are not kept
    bad = t / "bad"
    shutil.copytree(t / "rd3" / "archive", bad)
    ev_p = bad / "events.jsonl"
    raw = ev_p.read_bytes()
    ev_p.write_bytes(raw.replace(b'"worker":0', b'"worker":1', 1))
    check(not rs.prefix_property(t / "rd2" / "archive", bad)["ok"], "a changed rd2 ledger line fails the prefix property")
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
        loaded, _mm = s3.Archive3.read_dir(d)
        check(s3.audit3(loaded, "L")["ok"] and m["checkpoint_seq"] == 2, f"crash {crash}: the newest complete checkpoint audits")
        z, _m3 = s3.Archive3.read_dir(t / "rd3" / "archive")
    shutil.rmtree(t, ignore_errors=True)
    return {"cells": len(a.cells)}


def unit_ledger_rebuild3() -> Dict[str, Any]:
    n1, n2, n3 = 50, 60, 70
    a = synth_archive3("lr3", n1, n2, n3)
    check(len(a.cells) > 200 and len(a.bursts) == n1 + n2 + n3 and a.mode == 2, f"the synthetic three-part archive: {len(a.cells)} cells")
    check(all(len(b.reaches[0]) == 3 for b in a.bursts[:n1] if b.reaches) and any(len(b.reaches[0]) == 4 for b in a.bursts[n1:] if b.reaches), "reach rows: rd1's keep three elements, rd2's and rd3's four")
    aud = s3.audit3(a, "lines")
    check(aud["ok"], f"audit of a three-part archive: {aud['problems']}")
    check(aud["prefixes_reconstructed"] == len(a.cells), "every prefix reconstructs")
    rb = s3.rebuild3(a, "lines")
    check([c.to_json() for c in rb.cells] == [c.to_json() for c in a.cells] and rb.events == a.events and rb.diag2 == a.diag2 and rb.rd3_first_iteration == a.rd3_first_iteration,
          "the rebuild equals the archive")
    raises(s2.Select2Error, lambda: s2.audit2(a, "lines"), "rd2's own audit cannot cross a second session event (which is why rebuild3 exists)")
    rd, rbd = a.reference_flags()
    check(rd == a.desc and rbd == a.bound, "the incremental flags equal the recomputation")
    t = tmpdir("m8r3lr_")
    a.write_files(t / "a", {"checkpoint_seq": 1})

    def load() -> s3.Archive3:
        b, _m = s3.Archive3.read_dir(t / "a")
        return b

    check(s3.audit3(load(), "lines")["ok"], "a saved and reloaded archive audits")
    # tampering is detected
    b = load()
    k = next(i for i, e in enumerate(b.events) if e["ev"] == "dispatch" and e["it"] == n1 + n2 + 3)
    b.events[k]["cell"] = (b.events[k]["cell"] + 1) % len(b.cells)
    check(not s3.audit3(b, "lines")["ok"], "a changed rd3 selection is detected by the re-derived draw")
    b = load()
    b.events = [e for e in b.events if not (e["ev"] == "session" and e["name"] == "rd3")]
    check(not s3.audit3(b, "lines")["ok"], "a ledger without rd3's session event does not rebuild (the rd3 draws are lost)")
    b = load()
    sev = next(e for e in b.events if e["ev"] == "session" and e["name"] == "rd3")
    sev["first_iteration"] += 1
    check(not s3.audit3(b, "lines")["ok"], "a shifted rd3 first iteration is detected")
    b = load()
    i2 = next(i for i, e in enumerate(b.events) if e["ev"] == "session" and e["name"] == "rd2")
    i3 = next(i for i, e in enumerate(b.events) if e["ev"] == "session" and e["name"] == "rd3")
    b.events[i2], b.events[i3] = b.events[i3], b.events[i2]
    check(not s3.audit3(b, "lines")["ok"], "swapped session events are detected")
    b = load()
    next(e for e in b.events if e["ev"] == "session" and e["name"] == "rd3")["digest"] = "0" * 64
    check(not s3.audit3(b, "lines")["ok"], "a tampered rd3 session digest is detected")
    check(not s3.audit3(load(), "other lines")["ok"], "a different pinned line table is detected through the session digests")
    b = load()
    next(e for e in b.events if e["ev"] == "session" and e["name"] == "rd3")["draw_suffix"] = "_v2"
    check(not s3.audit3(b, "lines")["ok"], "a tampered draw suffix is detected")
    b = load()
    b.cells[len(b.cells) // 2].chosen += 1
    check(not s3.audit3(b, "lines")["ok"], "a tampered counter is detected")
    b = load()
    v3b = next(x for x in b.bursts[n1 + n2 + 5:] if x.reaches)
    v3b.reaches[0][3] = 1 - v3b.reaches[0][3]
    check(not s3.audit3(b, "lines")["ok"], "a tampered bound bit in an rd3 burst is detected")
    b = load()
    b.diag2["revivals"] += 1
    check(not s3.audit3(b, "lines")["ok"], "a tampered v2 counter is detected")
    b = load()
    b.desc[7] = not b.desc[7]
    check(not s3.audit3(b, "lines")["ok"], "a tampered derived flag is detected against the recomputation")
    b = load()
    b.bursts[n1 + n2 + 2].start_rep = (900, 0)
    check(not s3.audit3(b, "lines")["ok"], "a lineage that points forward is detected")
    b = load()
    dup = next(e for e in b.events if e["ev"] == "dispatch" and e["it"] == n1 + n2 + 4)
    dup["it"] = n1 + n2 + 3
    check(not s3.audit3(b, "lines")["ok"], "a reused iteration is detected")
    shutil.rmtree(t, ignore_errors=True)
    return {"cells": len(a.cells), "wins": sum(len(x.wins) for x in a.bursts)}


def unit_rule3_module() -> Dict[str, Any]:
    check(rule3.self_test() == [], "the rule's self-test")
    d = rule3.rule_digest()
    check(d == rule3.rule_digest() and len(d) == 64, "the rule digest")
    desc = rule3.rule_description()
    check(desc["control_arm"] is False and set(desc["stops"]) == set(rule3.STOPS) and desc["order"] == ["INVALID", "INCOMPLETE", "PROGRESS", "NO_NEW_MILESTONE"], "no control arm, seven stops, four outcomes")
    check(rule3.PROGRESS_MIN_M == 2 and rule3.PROGRESS_MIN_TARGETS == 8 and rule3.LADDER == ("none", "L0", "crossing", "left_target", "clear"), "the registered progress thresholds")
    check(rule3.MIN_EXPLORATION_TICKS == 2_000_000 and rule3.MAX_LIFECYCLE_FAILURES == 3 and rule3.TOP_LEVEL_MEDIAN_L_LIMIT == 3000, "the carried-over limits")
    prior = {"rd1": {"m": 0}, "rd2": {"m": 1}}
    r = rule3.apply(invalid=[], incomplete=[], m=1, t=7, below_floor=0, dispatches=100, fatal_returns=0, returns=100, launch_capable_created=10, prior=prior)
    check(r["outcome"] == "NO_NEW_MILESTONE" and r["any_stop"] == ["S2"] and r["highest_milestone"] == "L0" and r["max_targets_verified"] == 7, f"a wall-top landing and seven targets: {r['outcome']} {r['any_stop']}")
    r = rule3.apply(invalid=[], incomplete=[], m=2, t=7, below_floor=0, dispatches=100, fatal_returns=0, returns=100, launch_capable_created=10, prior=prior)
    check(r["outcome"] == "PROGRESS" and r["progress_basis"] == ["milestone:crossing"] and not r["any_stop"] and "further session" in r["next"], f"a crossing: {r['outcome']} {r['any_stop']}")
    return {"rule_digest": d[:12]}


def unit_identity_samples3() -> Dict[str, Any]:
    a = synth_archive3("is3", 50, 50, 40, floor_min=-2100.0)
    s = run3.identity_sample_open(a, 16)
    ids = [c.id for c in s["cells"]]
    check(len(ids) == 16 and len(set(ids)) == 16 and 0 not in ids, f"sixteen distinct non-root cells: {len(ids)}")
    names = s["names"]
    check(names.count("highest_weight") <= 4 and names.count("keyed_launch_or_a2_high") <= 4 and names.count("keyed_eligible") <= 5, f"pool sizes: {names}")
    pr = a.probabilities()
    best = [cid for cid in sorted(pr, key=lambda i: (-pr[i], i)) if cid != 0][:4]
    check(all(b in ids for b in best), "the four highest-weight v2-eligible cells are in the sample")
    check(s["cells"] == run3.identity_sample_open(a, 16)["cells"], "the open sample is a pure function of the archive")
    for lv in sorted({c.level for c in a.cells if c.id}, reverse=True)[:3]:
        short = min((c for c in a.cells if c.id and c.level == lv), key=lambda c: (c.L, c.id))
        check(short.id in ids, f"the shortest cell of level {lv} is in the sample")
    sc = run3.identity_sample_close(a, 16)
    check(len(sc["cells"]) == 16 and len({c.id for c in sc["cells"]}) == 16, "the close sample")
    check(run3.identity_sample_close(a, 16)["cells"] == sc["cells"], "the close sample is deterministic")
    check(sc["cells"] != s["cells"], "and a different keyed sample from the open one")
    # rd3's keys are not rd2's: the keyed parts of the samples differ from rd2's samples of the same archive
    o2 = run2.identity_sample_open(a, 16)
    check([c.id for c in o2["cells"]] != ids, "the rd3 open sample is keyed differently from rd2's")
    check([c.id for c in run2.identity_sample_close(a, 16)["cells"]] != [c.id for c in sc["cells"]], "the rd3 close sample is keyed differently from rd2's")
    k3 = hashlib.sha256(f"m8_rd|{a.archive_id}|identity_open|rd3|5".encode()).digest()
    check(run3._kh(a, "identity_open|rd3", a.cells[5]) == k3, "the identity key string")
    small = fresh3("small")
    small.begin_v2(5, "L")
    check(run3.identity_sample_open(small, 16)["cells"] == [] and run3.identity_sample_close(small, 16)["cells"] == [], "an archive with only cell 0 has no sample")
    return {"open_names": names}


# -- the diagnostics -----------------------------------------------------------------------------------------------------------------------------------


def unit_new_diagnostics() -> Dict[str, Any]:
    check(abs(rpt3.seg_distance(0.0, 5.0, (-10.0, 0.0), (10.0, 0.0)) - 5.0) < 1e-12, "a point above the middle of a segment")
    check(abs(rpt3.seg_distance(13.0, 4.0, (-10.0, 0.0), (10.0, 0.0)) - 5.0) < 1e-12, "a point beyond an end: the distance to the endpoint")
    check(abs(rpt3.seg_distance(-10.0, 0.0, (-10.0, 0.0), (10.0, 0.0))) < 1e-12 and abs(rpt3.seg_distance(1.0, 1.0, (3.0, 5.0), (3.0, 5.0)) - math.hypot(2.0, 4.0)) < 1e-12,
          "a point on a segment; a degenerate segment")
    seg = rpt3.left_floor_segment()
    check(seg == ((-3900.0, -1950.0), (-2700.0, -1950.0)), f"floor line 3 of the pinned line table: {seg}")
    check(rpt3.LEFT_FLOOR_LINE == 3 and rpt3.WALL_FACE_X == -1650.0 and rpt3.LEFT_X_THRESHOLDS == (-1650.0, -1800.0, -2100.0), "the registered readings")
    a = fresh3("nd", -2550.0)
    wt1 = t2.add_cell2(a, t2.mkey(-6, 10, "G", 1023, 0), 900, y=3000.0)             # x = -1700 on floor line 0
    wt2 = t2.add_cell2(a, t2.mkey(-5, 10, "G", 1020, 0), 1500, y=3000.0)            # x = -1400 on floor line 0
    g4 = t2.add_cell2(a, t2.mkey(0, -9, "G", 1023, 4), 300, y=-2550.0)              # x = 100 on the main floor
    near = t2.add_cell2(a, t2.mkey(-10, -6, "A2", 1023), 700, y=-1900.0)            # x = -2900, 50 above floor line 3
    far = t2.add_cell2(a, t2.mkey(-9, 5, "A2", 1023), 800, y=1500.0)                # x = -2600
    t2.add_cell2(a, t2.mkey(3, 3, "A1", 1023), 900, y=1000.0)
    for c in (wt1, wt1, wt2, g4):
        t2.dispatch_to(a, c)
    d = rpt3.new_diagnostics(a, 0, None)
    wt = d["wall_top"]
    check(wt["cells"] == 2 and wt["cell_ids"] == [wt1.id, wt2.id] and wt["dispatches_from"] == 3 and wt["dispatches"] == 4 and wt["shortest_L"] == 900 and abs(wt["highest_y"] - 3000.0) < 1e-9,
          f"wall-top cells and the dispatches from them: {wt}")
    lw = d["left_of_wall_face"]
    check(lw["x_lt_-1650"] == 3 and lw["x_lt_-1800"] == 2 and lw["x_lt_-2100"] == 2 and lw["leftmost_cell"] == near.id and abs(lw["leftmost_x"] + 2900.0) < 1e-9, f"cells left of the wall face: {lw}")
    lf = d["left_floor_approach"]
    check(abs(lf["min_distance_all"] - 50.0) < 1e-9 and lf["nearest_cell"] == near.id and lf["nearest_class"] == "A2" and abs(lf["min_distance_a2a1"] - 50.0) < 1e-9
          and lf["nearest_a2a1_cell"] == near.id and lf["floor_line"] == 3, f"the closest approach to the left floor: {lf}")
    # a range of iterations restricts only the dispatches, never the cells
    d2 = rpt3.new_diagnostics(a, 1000, 1000)
    check(d2["wall_top"]["cells"] == 2 and d2["wall_top"]["dispatches"] == 1 and d2["wall_top"]["dispatches_from"] == 1, f"a one-iteration range: {d2['wall_top']}")
    # the selection probability at the open, analytic: cell 0 (L 0) and one wall-top cell (L 900) in one level: weights 2 and 1
    b = fresh3("nd2", -2550.0)
    w = t2.add_cell2(b, t2.mkey(-6, 10, "G", 1023, 0), 900, y=3000.0)
    pr = rpt3.open_selection_probabilities(b)
    check(pr["wall_top_cells"] == 1 and pr["eligible"] == 1 and abs(pr["total_probability"] - 1.0 / 3.0) < 1e-12 and abs(pr["per_cell"][str(w.id)]["probability"] - 1.0 / 3.0) < 1e-12
          and pr["per_cell"][str(w.id)]["eligible"] is True, f"the analytic probability of a wall-top cell: {pr}")
    w.doomed = True
    b._version += 1
    pr2 = rpt3.open_selection_probabilities(b)
    check(pr2["eligible"] == 0 and pr2["total_probability"] == 0.0 and pr2["per_cell"][str(w.id)]["eligible"] is False, "a doomed wall-top cell has no probability")
    w.doomed = False
    w.terminal = True
    b._version += 1
    check(rpt3.open_selection_probabilities(b)["eligible"] == 0, "a terminal wall-top cell has no probability")
    # rule inputs count bound violations of rd3's bursts only
    c = synth_archive3("ri", 30, 30, 30)
    c.diag2["bound_violations"] = [{"burst": 1, "iteration": 10, "reach_tick": 3, "key": [], "last_grounded_tick": 4}, {"burst": 70, "iteration": 70, "reach_tick": 3, "key": [], "last_grounded_tick": 4}]
    ins = rpt3.rule_inputs3(c, 60, 0)
    check(ins["bound_violations"] == 1 and set(ins) >= {"below_floor", "dispatches", "fatal_returns", "returns", "launch_capable_created", "top_level_median_L"}, f"rule inputs: {ins}")
    check(rpt3.replay_verified_t([{"exact": True, "t": 5}, {"exact": False, "t": 9}, {"exact": True, "t": 7}]) == 7 and rpt3.replay_verified_t([]) == 0, "the verified maximum counts exact replays only")
    return {"wall_top_dispatches": wt["dispatches_from"]}


def unit_report3_on_real_rd2() -> Dict[str, Any]:
    """rd3's reference column for rd2 and rd1 equals what rd2's own report stored (the closed real trees, read only), and the new readings of the real archive."""
    check((RD2_REAL / "archive" / "manifest.sha256").is_file() and (RD1_REAL / "archive" / "manifest.sha256").is_file(), "the closed rd1 and rd2 trees are required")
    stored = json.loads((RD2_REAL / "derived" / "report_after_run.json").read_text(encoding="utf-8-sig"))
    a2, _m = s3.Archive3.read_dir(RD2_REAL / "archive")
    a1, _m1 = s2.Archive2.read_dir(RD1_REAL / "archive")
    rng = a2.iteration_ranges()
    check(rng == {"rd1": (0, 2174), "rd2": (2175, 6211), "rd3": (None, None)}, f"rd2's closing archive: {rng}")
    ref2 = rpt2.diagnostics(a2, 2175, 6211, first_new_cell=len(a1.cells))
    ref1 = rpt2.diagnostics(a1, 0, 2174, first_new_cell=0)

    def norm(x: Any) -> Any:
        d = json.loads(json.dumps(x, default=str))
        d.pop("iterations", None)                       # rd2's own report recorded its range open-ended; the readings are what is compared
        return d

    check(norm(ref2) == norm(stored["rd2"]), "rd2's reference column equals the diagnostics rd2 stored")
    check(norm(ref1) == norm(stored["rd1_reference"]), "rd1's reference column equals the one rd2 stored")
    reg = ref2["D1_regions"]
    check([reg[k]["n"] for k in ("below", "beside", "onlow", "onhigh")] == [829, 622, 1772, 814] and ref2["dispatches"] == 4037 and ref2["D4_supply"]["launch_capable_cells"] == 509
          and ref2["D4_supply"]["launch_capable_cells_created"] == 495, "rd2's published figures (829 / 622 / 1,772 / 814; 509 launch-capable cells, 495 created)")
    nd = rpt3.new_diagnostics(a2, 2175, 6211)
    wt = nd["wall_top"]
    check(wt["cells"] == 2 and wt["cell_ids"] == [18318, 18767] and wt["shortest_L"] == 1694 and wt["dispatches_from"] == 0 and wt["dispatches"] == 4037 and abs(wt["highest_y"] - 3000.0) < 1e-6,
          f"the real wall-top cells at rd2's close: {wt}")
    lw = nd["left_of_wall_face"]
    check(lw["x_lt_-1650"] == 14 and lw["x_lt_-1800"] == 8 and lw["x_lt_-2100"] == 0 and lw["leftmost_cell"] == 18319 and abs(lw["leftmost_x"] + 1876.1640625) < 1e-6,
          f"cells left of the wall face at rd2's close: {lw}")
    lf = nd["left_floor_approach"]
    check(abs(lf["min_distance_all"] - 1051.0563383642084) < 1e-6 and lf["nearest_cell"] == 17833 and lf["nearest_class"] == "A0" and abs(lf["min_distance_a2a1"] - 1054.1281852310183) < 1e-6
          and lf["nearest_a2a1_cell"] == 9405, f"the closest approach to the left floor at rd2's close: {lf}")
    pr = rpt3.open_selection_probabilities(a2)
    check(pr["wall_top_cells"] == 2 and pr["eligible"] == 2 and abs(pr["total_probability"] - 0.0006843080079355592) < 1e-12 and pr["eligible_cells"] == 11794 and pr["top_eligible_level"] == 7
          and all(v["chosen"] == 0 for v in pr["per_cell"].values()), f"the selection probability of the wall-top cells at the open: {pr['total_probability']}")
    check(abs(sum(a2.probabilities().values()) - 1.0) < 1e-9, "the analytic probabilities of the archive as materialised sum to one")
    return {"wall_top_cells": wt["cells"], "wall_top_probability": pr["total_probability"], "left_of_face": lw["x_lt_-1650"], "left_floor_min_distance": lf["min_distance_all"]}


# -- the resume protocol on a synthetic chain ---------------------------------------------------------------------------------------------------------


def unit_resume_two_level_synthetic() -> Dict[str, Any]:
    chain = build_chain()
    check(chain["rd2_outcome"] in rule2.OUTCOMES and chain["expect2"]["first_rd2_iteration"] == chain["expect1"]["dispatch_iterations"][1] + 1, "the synthetic chain")
    op = ses3.open_protocol3(chain["rd1"], chain["rd2"], chain["inc1"], chain["inc2"], expect1=chain["expect1"], expect2=chain["expect2"], check_overlay=False,
                             live_pins=lambda: live_pins_of(chain), floor_min=FLOOR_MIN)
    check(op["ok"], f"the open protocol on a synthetic chain: {op['problems']}")
    check(op["R1_rd1_immutability"]["ok"] and op["R1_rd2_immutability"]["ok"] and op["R2_R4_rd1_archive"]["ok"] and op["R2_R4_rd2_archive"]["ok"] and not op["R3_pins"]["problems"]
          and not op["R3_pins"]["rd1_problems"] and op["R5_overlay"]["ok"] and op["R5_overlay"]["stored_close_counts_equal"], "R1-R5")
    check(op["facts2"]["first_rd3_iteration"] == chain["expect2"]["dispatch_iterations"][1] + 1 and op["facts2"]["rd2_checkpoint_seq"] == chain["expect2"]["checkpoint_seq"], "iterations continue from rd2's last")
    # R1: any change of either tree is caught, and named by the tree
    for tree in ("rd1", "rd2"):
        for what in ("byte", "mtime", "extra", "missing", "increment"):
            cp = copy_chain(chain)
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
                rec_p = cp["inc1" if tree == "rd1" else "inc2"] / "verification.json"
                rec = json.loads(rec_p.read_text(encoding="utf-8"))
                rec["result"] = "FAIL"
                rec_p.write_text(json.dumps(rec), encoding="utf-8")
            op2 = ses3.open_protocol3(cp["rd1"], cp["rd2"], cp["inc1"], cp["inc2"], expect1=chain["expect1"], expect2=chain["expect2"], check_overlay=False,
                                      live_pins=lambda: live_pins_of(chain), floor_min=FLOOR_MIN)
            check(not op2["ok"] and any(p.startswith(f"R1 ({tree})") for p in op2["problems"]), f"R1 missed a change of {tree}'s tree: {what}: {op2['problems'][:3]}")
            other = "rd2" if tree == "rd1" else "rd1"
            check(not any(p.startswith(f"R1 ({other})") for p in op2["problems"]), f"R1 blamed {other} for a change of {tree}'s tree")
            shutil.rmtree(cp["t"], ignore_errors=True)
    # R2: wrong expectations, a tampered close record, a wrong diag2, a changed pin
    for what, bad in (("cells", dict(chain["expect2"], cells=chain["expect2"]["cells"] + 1)), ("checkpoint", dict(chain["expect2"], checkpoint_seq=99)),
                      ("first iteration", dict(chain["expect2"], first_rd2_iteration=chain["expect2"]["first_rd2_iteration"] + 1)),
                      ("iterations", dict(chain["expect2"], dispatch_iterations=(0, chain["expect2"]["dispatch_iterations"][1] + 1)))):
        f = r3.rd2_archive_facts(chain["rd1"], chain["rd2"], chain["lines"], bad)
        check(not f["ok"], f"R2: a wrong {what} is refused")
    cp = copy_chain(chain)
    close_p = cp["rd2"] / "sessions" / "rd2" / "close.json"
    d = json.loads(close_p.read_text(encoding="utf-8"))
    d["archive"]["manifest"]["cells.jsonl"] = "0" * 64
    close_p.write_text(json.dumps(d), encoding="utf-8")
    check(not r3.rd2_archive_facts(cp["rd1"], cp["rd2"], chain["lines"], chain["expect2"])["ok"], "R2: the archive must equal rd2's close record")
    d = json.loads(close_p.read_text(encoding="utf-8"))
    d["archive"]["manifest"]["cells.jsonl"] = mw.sha256_file(cp["rd2"] / "archive" / "cells.jsonl")
    d["archive"]["diag2"]["revivals"] += 1
    close_p.write_text(json.dumps(d), encoding="utf-8")
    f = r3.rd2_archive_facts(cp["rd1"], cp["rd2"], chain["lines"], chain["expect2"])
    check(not f["ok"] and any("diag2" in p for p in f["problems"]), "R2: the counters must equal rd2's close record")
    shutil.rmtree(cp["t"], ignore_errors=True)
    f = r3.rd2_archive_facts(chain["rd1"], chain["rd2"], "another line table", chain["expect2"])
    check(not f["ok"] and any("digest" in p for p in f["problems"]), "R2: rd2's session digest must equal the digest recomputed from the contract and the pinned lines")
    # R3: the pins
    p = chain["pins"]
    live = live_pins_of(chain)
    fz = chain["rd1"] / "archive" / "runtime"
    check(rs.pin_problems(p, live, fz, p["frozen_sha256"]) == [], "R3: equal pins")
    check(rs.pin_problems(p, dict(live, executable_sha256="0" * 64), fz, p["frozen_sha256"]) == ["pin executable_sha256 differs"], "R3: only the executable differs -> reported alone")
    op3 = ses3.open_protocol3(chain["rd1"], chain["rd2"], chain["inc1"], chain["inc2"], expect1=chain["expect1"], expect2=chain["expect2"], check_overlay=False,
                              live_pins=lambda: dict(live_pins_of(chain), executable_sha256="0" * 64), floor_min=FLOOR_MIN)
    check(not op3["ok"] and op3["R3_pins"]["executable_only"] and any("only the executable differs" in x for x in op3["problems"]), "R3: an executable-only difference refuses the exploration session")
    op4 = ses3.open_protocol3(chain["rd1"], chain["rd2"], chain["inc1"], chain["inc2"], expect1=chain["expect1"], expect2=chain["expect2"], check_overlay=False,
                              live_pins=lambda: dict(live_pins_of(chain), flags={"explore": {}, "verify": {}}), floor_min=FLOOR_MIN)
    check(not op4["ok"] and any("R3" in x for x in op4["problems"]), "R3: the flags")
    # R5: the closing overlay
    ov = r3.closing_overlay(chain["rd2"], expect={}, floor_min=FLOOR_MIN)
    check(ov["ok"] and ov["counts"] == ov["stored_close_counts"] and len(ov["rows"]) == chain["expect2"]["cells"] and "archive" not in ov, f"R5: the closing overlay reproduces rd2's record: {ov['problems']}")
    ov_b = r3.closing_overlay(chain["rd2"], expect={}, floor_min=FLOOR_MIN)
    check(ov["bytes"] == ov_b["bytes"] and ov["sha256"] == ov_b["sha256"], "and is reproducible")
    check(not r3.closing_overlay(chain["rd2"], expect={"cells": ov["counts"]["cells"] + 1}, floor_min=FLOOR_MIN)["ok"], "R5: a registered figure that differs is refused")
    cp = copy_chain(chain)
    close_p = cp["rd2"] / "sessions" / "rd2" / "close.json"
    d = json.loads(close_p.read_text(encoding="utf-8"))
    d["archive"]["overlay_close"]["union"] += 1
    close_p.write_text(json.dumps(d), encoding="utf-8")
    check(not r3.closing_overlay(cp["rd2"], expect={}, floor_min=FLOOR_MIN)["ok"], "R5: the overlay must equal the counts rd2's close record stores")
    shutil.rmtree(cp["t"], ignore_errors=True)
    # the earlier sessions' recorded milestones
    pm = r3.prior_milestones(chain["rd1"], chain["rd2"])
    r1rec = json.loads((chain["rd1"] / "sessions" / "rd1" / "rule.json").read_text(encoding="utf-8"))
    check(pm["rd1"]["m"] == max(r1rec["m_T"], r1rec["m_C"]) and pm["rd1"]["source"] == "sessions/rd1/rule.json" and pm["rd2"]["m"] == chain["rd2_m"]
          and pm["rd2"]["source"] == "sessions/rd2/rule.json", f"prior milestones: {pm}")
    check(r3.prior_milestones(chain["rd1"], chain["t"] / "nowhere") == {"rd1": pm["rd1"], "rd2": None}, "a missing record is None (and the rule refuses it)")
    # R6: materialise
    t = tmpdir("m8mat3_")
    root3 = t / "rd3"
    a3 = r3.materialise3(chain["rd2"], root3, facts=op["facts2"], overlay=op["overlay"], lines_sha256=chain["lines"], meta_extra={"pins": p, "pin_tick0": op["facts2"]["pin_tick0"], "ticks": {}, "ledger_T": {}},
                         increment_manifest_sha256="x" * 64, utc="2026-10-02T00:00:00Z", floor_min=FLOOR_MIN)
    check(a3.mode == 2 and a3.rd3_first_iteration == chain["expect2"]["dispatch_iterations"][1] + 1 and a3.first_iteration == a3.rd3_first_iteration, "materialised: mode 2, rd3 begun, iterations continue")
    for n in (*march.DATA_FILES, march.MANIFEST):
        check(mw.sha256_file(root3 / "base" / n) == mw.sha256_file(chain["rd2"] / "archive" / n), f"the base copy of {n} is byte-identical to rd2's closing file")
    check(mw.sha256_file(root3 / "derived" / "open_overlay.jsonl") == op["overlay"]["sha256"], "the stored overlay hashes to its digest")
    ob = json.loads((root3 / "derived" / "open_overlay.json").read_text(encoding="utf-8"))
    check(ob["sha256"] == op["overlay"]["sha256"] and ob["computed_twice_equal"], "the overlay record")
    base = json.loads((root3 / "derived" / "base.json").read_text(encoding="utf-8"))
    check(base["session_event"]["name"] == "rd3" and base["rd2_increment_manifest_sha256"] == "x" * 64 and base["overlay_sha256"] == op["overlay"]["sha256"]
          and base["rd2_close_record_sha256"] == op["facts2"]["close_record_sha256"], "the base record")
    d, meta, rep = march.load_latest_verified(root3 / "archive")
    check(d is not None and meta["checkpoint_seq"] == chain["expect2"]["checkpoint_seq"] + 1 and meta["schema"] == s2.ARCHIVE_SCHEMA_V2 and meta["why"] == "open", "the first rd3 checkpoint")
    check(r3.prefix_chain(chain["rd1"] / "archive", chain["rd2"] / "archive", root3 / "archive")["ok"], "the prefix chain rd1 -> rd2 -> rd3 holds at the open")
    loaded, _m = s3.Archive3.read_dir(root3 / "archive")
    check(s3.audit3(loaded, chain["lines"])["ok"], "the materialised archive audits (three parts, no rd3 dispatch yet)")
    raises(r3.Resume3Error, lambda: r3.materialise3(chain["rd2"], root3, facts=op["facts2"], overlay=op["overlay"], lines_sha256=chain["lines"], meta_extra={}, increment_manifest_sha256="x",
                                                    utc="u"), "an existing rd3 root is never overwritten")
    # nothing was written under either earlier tree by any of this
    check(both_immutability(chain)["ok"], "both earlier trees are still equal to their increments after the open")
    shutil.rmtree(t, ignore_errors=True)
    return {"cells": len(a3.cells)}


# -- the session on a synthetic chain (deterministic engine) -------------------------------------------------------------------------------------------


def unit_session3_small_run() -> Dict[str, Any]:
    chain = build_chain()
    out, sess, root, cp = run3_small(chain)
    rule, close = out["rule"], out["close"]
    check(not rule["invalid"] and not rule["incomplete"] and rule["outcome"] in rule3.OUTCOMES and rule["outcome"] not in ("INVALID", "INCOMPLETE"),
          f"a complete small session: {rule['outcome']} {rule['invalid']} {rule['incomplete']}")
    check(sess.ledgers["T"].ticks == 12000, f"the exploration committed exactly its cap: {sess.ledgers['T'].ticks}")
    sd = sess.cfg.session_dir
    for f in ("p1.json", "identity_open.json", "arm_T.json", "verification.json", "rule.json", "close.json", "state.json", "iterations_T.jsonl", "ledger_T.json", "candidates_T.jsonl.gz"):
        check((sd / f).is_file(), f"missing {f}")
    p1 = json.loads((sd / "p1.json").read_text(encoding="utf-8"))
    check(p1["tick0"]["equals_archive_pin"] and p1["selftest"]["corrupted_refused"] and len(p1["traces"]) == 2, "P1 against the archive's pin")
    io_ = json.loads((sd / "identity_open.json").read_text(encoding="utf-8"))
    check(io_["ok"] and io_["cells"] == 6 and io_["verified"] == 6, f"open identity replays: {io_}")
    ver = json.loads((sd / "verification.json").read_text(encoding="utf-8"))
    check(ver["identity"]["ok"] and ver["identity"]["verified"] == ver["identity"]["cells"] == 6, f"close identity replays {ver['identity']}")
    check(close["audit"]["ok"] and close["prefix_chain"]["ok"] and close["earlier_trees_immutability"]["ok"] and not close["guard_violations"], f"close checks: {close}")
    check(close["archive"]["checkpoint_seq"] == sess.ckpt_seq and sess.ckpt_seq > chain["expect2"]["checkpoint_seq"] + 1, "the checkpoint sequence continues from rd2's")
    # iterations continue from rd2's last, never reused
    first = chain["expect2"]["dispatch_iterations"][1] + 1
    check(sess.first_iteration == first and sess.archive.rd3_first_iteration == first, "iterations continue after rd2's")
    its = [e["it"] for e in sess.archive.events if e["ev"] == "dispatch"]
    check(its == list(range(its[0], its[-1] + 1)) and its[0] == 0 and its.count(first) == 1, "dispatch iterations are contiguous and never reused")
    rows = [json.loads(x) for x in (sd / "iterations_T.jsonl").read_text(encoding="utf-8").splitlines()]
    check(sum(r["ticks"] for r in rows if "ticks" in r) == 12000 and all(r["tick0_equal"] for r in rows if "ticks" in r), "iteration rows add up; tick 0 equal everywhere")
    a = sess.archive
    rng = a.iteration_ranges()
    check(rng["rd3"][0] == first and rng["rd2"][1] == first - 1 and rng["rd1"][1] == chain["expect2"]["first_rd2_iteration"] - 1, f"the three ranges: {rng}")
    # the rd3 bursts carry the session name and the diagnostics; reach rows: rd1's three elements, rd2's and rd3's four
    b3 = [b for b in a.bursts if b.iteration >= first]
    check(b3 and all(b.ground_runs is not None and b.session == "rd3" for b in b3), "rd3 bursts carry ground runs and the session name")
    check(all(len(b.reaches[0]) == 4 for b in a.bursts if b.reaches and b.iteration >= rng["rd2"][0]) and all(len(b.reaches[0]) == 3 for b in a.bursts if b.reaches and b.iteration < rng["rd2"][0]),
          "reach rows: rd1's keep three elements, rd2's and rd3's have four")
    # every burst of every part was explored under its own session's draw id (the words are the keyed stream's prefix)
    aid = a.archive_id
    for b in a.bursts:
        draw = aid if b.iteration < rng["rd2"][0] else (aid + "_v2" if b.iteration < first else aid + "_rd3")
        want = bytes(w for _i, w in zip(range(len(b.words)), mx.words(lambda i, d=draw, it=b.iteration: mx.explore_key(d, it, i), mx.BURST_WORDS)))
        check(b.words == want, f"burst {b.id} (iteration {b.iteration}): the words are not the {draw} keyed stream")
    # the report
    rep = rpt3.full_report3(root, cp["rd2"], cp["rd1"], "rd3")
    n_disp3 = sum(1 for e in a.events if e["ev"] == "dispatch" and e["it"] >= first)
    check(rep["rd3"]["dispatches"] == n_disp3 and rep["rd3"]["returns"] == rep["rule_inputs"]["returns"] and rep["iteration_ranges"]["rd3"][0] == first, "the report counts rd3's dispatches")
    for k in ("D7_efficiency", "D8_v2_mechanism", "upb_start_heights", "ground_runs", "new", "selection_probability_at_the_open", "rd2_reference", "rd1_reference"):
        check(k in rep, f"the report section {k}")
    check(set(rep["new"]) == {"rd3", "rd2_reference", "rd1_reference"} and set(rep["new"]["rd3"]) == {"wall_top", "left_of_wall_face", "left_floor_approach"}, "the new readings in the three columns")
    check(rep["rd2_reference"]["dispatches"] == sum(1 for e in a.events if e["ev"] == "dispatch" and rng["rd2"][0] <= e["it"] <= rng["rd2"][1]), "rd2's reference column counts rd2's dispatches")
    check(rep["rd1_reference"]["dispatches"] == rng["rd2"][0], "rd1's reference column counts rd1's dispatches")
    check(abs(rep["D7_efficiency"]["prefix_share"] - sess.arm_records["T"]["prefix_ticks"] / 12000) < 1e-9, "D7 prefix share")
    refs = rep["D7_efficiency_references"]
    check(refs["rd2"] is not None and refs["rd1"] is not None and refs["rd2"]["returns"] == rep["rd2_reference"]["returns"] and refs["rd1"]["returns"] == rep["rd1_reference"]["returns"]
          and refs["rd2"]["ticks"] == json.loads((cp["rd2"] / "sessions" / "rd2" / "arm_T.json").read_text(encoding="utf-8"))["ticks"], "D7 carries rd2's and rd1's reference columns")
    d8r = rep["D8_v2_mechanism_rd2_reference"]
    check(d8r["close"]["eligible_v2"] == rep["D8_v2_mechanism"]["open"]["eligible_v2"] and d8r["counters"] == rep["D8_v2_mechanism"]["counters_rd2_close"], "D8's rd2 reference is rd2's own close, which is rd3's open")
    check(rep["D9_max_targets"]["rd2"] == json.loads((cp["rd2"] / "sessions" / "rd2" / "verification.json").read_text(encoding="utf-8"))["arm"]["t"], "D9's rd2 value is rd2's verified maximum")
    check(rep["D9_max_targets"]["verified_in_rd3"] == rule["max_targets_verified"], "D9's rd3 value is the rule's maximum")
    check(rule["extra"]["rule_inputs"] == rep["rule_inputs"], "the rule inputs equal the report's")
    d8 = rep["D8_v2_mechanism"]
    check(d8["counters_rd3"] == {k: d8["counters_cumulative"][k] - d8["counters_rd2_close"].get(k, 0) for k in d8["counters_cumulative"]}, "rd3's counters are the difference to rd2's closing record")
    # the selection probability at the open is that of the archive as materialised
    a_open, _m = s3.Archive3.read_dir(cp["rd2"] / "archive")
    check(rep["selection_probability_at_the_open"] == rpt3.open_selection_probabilities(a_open), "the open probabilities are those of rd2's closing archive")
    # verify-run
    vr = rpt3.verify_run3(root, cp["rd2"], cp["rd1"], "rd3")
    check(vr["ok"], f"verify-run: {vr['problems']}")
    for f in ("p1.json", "identity_open.json", "arm_T.json", "verification.json", "rule.json", "close.json", "state.json"):
        check(json.loads((sd / f).read_text(encoding="utf-8")).get("scope") == rule3.SCOPE, f"the scope label is carried by {f}")
    # verify-run refuses a session with no recorded decision, no close record, or an m / t the exact replays do not hold
    tmp = tmpdir("m8vr3_")
    shutil.copytree(root, tmp / "a")
    (tmp / "a" / "sessions" / "rd3" / "rule.json").unlink()
    vr2 = rpt3.verify_run3(tmp / "a", cp["rd2"], cp["rd1"], "rd3")
    check(not vr2["ok"] and any("no rule.json" in p for p in vr2["problems"]), f"no decision recorded: {vr2['problems']}")
    shutil.copytree(root, tmp / "b")
    (tmp / "b" / "sessions" / "rd3" / "close.json").unlink()
    check(not rpt3.verify_run3(tmp / "b", cp["rd2"], cp["rd1"], "rd3")["ok"], "no close record is refused")
    for key, bad in (("m", lambda v: 4 if v != 4 else 0), ("max_targets_verified", lambda v: 9 if v != 9 else 0)):
        shutil.copytree(root, tmp / f"c_{key}")
        rp_ = tmp / f"c_{key}" / "sessions" / "rd3" / "rule.json"
        d_ = json.loads(rp_.read_text(encoding="utf-8"))
        d_[key] = bad(d_[key])
        rp_.write_text(json.dumps(d_), encoding="utf-8")
        check(not rpt3.verify_run3(tmp / f"c_{key}", cp["rd2"], cp["rd1"], "rd3")["ok"], f"a recorded {key} that the exact replays do not hold is refused")
    shutil.copytree(root, tmp / "d")
    ap_ = tmp / "d" / "archive" / "events.jsonl"
    raw = ap_.read_bytes()
    ap_.write_bytes(raw.replace(b'"worker":0', b'"worker":1', 1))
    check(not rpt3.verify_run3(tmp / "d", cp["rd2"], cp["rd1"], "rd3")["ok"], "a changed archive file is refused")
    shutil.rmtree(tmp, ignore_errors=True)
    # both earlier trees are untouched
    check(both_immutability(cp)["ok"] and both_immutability(chain)["ok"], "the earlier trees are untouched")
    shutil.rmtree(cp["t"], ignore_errors=True)
    return {"outcome": rule["outcome"], "cells": len(a.cells), "ticks": 12000, "m": rule["m"], "t": rule["max_targets_verified"]}


def unit_session3_refuses_unbegun_archive() -> Dict[str, Any]:
    chain = build_chain()
    cp = copy_chain(chain)
    a2, _m = s3.Archive3.read_dir(cp["rd2"] / "archive")
    clock = FakeClock()
    env = sync_env(chain["world"], [], clock)
    cfg = small_cfg3(cp["t"] / "rd3x")
    raises(RuntimeError, lambda: run3.Session3(cfg, env, archive=a2, archive_pin={"digest": "0" * 64}, base_info={}, rd1_root=cp["rd1"], rd2_root=cp["rd2"], lines_sha256=chain["lines"], ckpt_seq=21),
           "an archive that has not begun rd3 is refused")
    shutil.rmtree(cp["t"], ignore_errors=True)
    return {}


def unit_session3_outcomes_and_stops() -> Dict[str, Any]:
    chain = build_chain()
    res: Dict[str, Any] = {}
    # below the registered minimum: INCOMPLETE
    out, sess, _r, cp = run3_small(chain, arm_tick_cap=3000, min_arm_ticks=5000)
    check(out["rule"]["outcome"] == "INCOMPLETE" and any("reached 3,000" in x for x in out["rule"]["incomplete"]), f"below the minimum: {out['rule']['incomplete']}")
    check(out["rule"]["stops"]["S7"]["triggered"], "S7 on INCOMPLETE")
    res["below_minimum"] = out["rule"]["outcome"]
    # a lifecycle failure is redrawn (up to three); more than three is INCOMPLETE
    out, sess, _r, cp = run3_small(chain, inject={"lifecycle_jobs": [14]}, n_workers=2, arm_tick_cap=8000, min_arm_ticks=1000)
    check(1 <= sess.lifecycle_failures["T"] <= 3 and sess.ledgers["T"].ticks == 8000 and out["rule"]["outcome"] != "INCOMPLETE", f"redrawn lifecycle failures {sess.lifecycle_failures}: {out['rule']['outcome']}")
    check(any(e["ev"] == "fail" for e in sess.archive.events) and s3.audit3(sess.archive, chain["lines"])["ok"], "the ledger records the failed iteration and still audits")
    res["lifecycle_redrawn"] = sess.lifecycle_failures["T"]
    out, sess, _r, cp = run3_small(chain, inject={"lifecycle_jobs": [14, 15, 16, 17]}, n_workers=2, arm_tick_cap=12000, min_arm_ticks=1000)
    check(out["rule"]["outcome"] == "INCOMPLETE" and any("lifecycle failures" in x for x in out["rule"]["incomplete"]), f"more than three: {out['rule']['incomplete']}")
    res["lifecycle_over"] = out["rule"]["outcome"]
    # an integrity mismatch and a provenance violation: INVALID
    out, sess, _r, cp = run3_small(chain, inject={"mismatch_job": 14, "mismatch_tick": 5}, n_workers=2, arm_tick_cap=20000, min_arm_ticks=1000)
    check(out["rule"]["outcome"] == "INVALID" and any("prefix_end" in x for x in out["rule"]["invalid"]), f"an integrity mismatch: {out['rule']['invalid']}")
    check(list((sess.cfg.session_dir / "failures").glob("iterate_*")), "the failed return's raw replies are preserved")
    check(not out["rule"]["stops"]["S2"]["triggered"], "S2 is not evaluable on an INVALID session")
    res["mismatch"] = out["rule"]["outcome"]
    out, sess, _r, cp = run3_small(chain, inject={"provenance_job": 14}, n_workers=2, arm_tick_cap=5000, min_arm_ticks=1000)
    check(out["rule"]["outcome"] == "INVALID" and any("provenance" in x for x in out["rule"]["invalid"]), f"a provenance violation: {out['rule']['invalid']}")
    res["provenance"] = out["rule"]["outcome"]
    # an earlier tree changed at the close: INVALID, named by the tree
    out, sess, _r, cp = run3_small(chain, arm_tick_cap=3000, min_arm_ticks=1000, immutability=lambda: {"ok": False, "problems": ["rd2: cells.jsonl differs"]})
    check(out["rule"]["outcome"] == "INVALID" and any("an earlier tree changed" in x for x in out["rule"]["invalid"]), f"a changed earlier tree: {out['rule']['invalid']}")
    res["earlier_tree_changed"] = out["rule"]["outcome"]
    # a write under either earlier tree is a guard violation: INVALID (the write happens in the session process, through the clock's memory probe)
    for victim in ("rd1", "rd2"):
        def writer(cp_: Mapping[str, Any], _clock: FakeClock, victim: str = victim) -> Mapping[str, Any]:
            done: List[int] = []

            def private_mb() -> float:
                if not done:
                    done.append(1)
                    (Path(cp_[victim]) / "archive" / "stray.txt").write_text("x", encoding="utf-8")
                return 100.0

            return {"private_mb": private_mb}

        out, sess, _r, cp = run3_small(chain, n_workers=2, arm_tick_cap=400000, min_arm_ticks=100, env_kw_factory=writer)
        check(out["rule"]["outcome"] == "INVALID" and any("protected root" in x for x in out["rule"]["invalid"]), f"a write under {victim}'s tree: {out['rule']['outcome']} {out['rule']['invalid']}")
        res[f"{victim}_write"] = out["rule"]["outcome"]
    # a software error in one close check is recorded (INCOMPLETE) and cannot hide the others
    def broken() -> Mapping[str, Any]:
        raise RuntimeError("injected immutability failure")

    out, sess, _r, cp = run3_small(chain, arm_tick_cap=3000, min_arm_ticks=1000, immutability=broken)
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

    out, sess, _r, cp = run3_small(chain, env_kw_factory=lambda cp_, clock_: {"sampler": LateBreach(clock_)}, n_workers=2, arm_tick_cap=10 ** 7, min_arm_ticks=1000)
    check(out["rule"]["outcome"] == "INCOMPLETE" and any("memory cap" in x for x in out["rule"]["incomplete"]), f"a memory breach: {out['rule']['incomplete']}")
    res["memory"] = out["rule"]["outcome"]
    out, sess, _r, cp = run3_small(chain, env_kw={"tree_snapshot": lambda: {"battleship": 11}}, n_workers=2, arm_tick_cap=10 ** 6, min_arm_ticks=1000, process_check_every_s=0.05)
    check(out["rule"]["outcome"] == "INCOMPLETE" and any("11 BattleShip processes" in x for x in out["rule"]["incomplete"]), f"a process-count breach: {out['rule']['incomplete']}")
    res["processes"] = out["rule"]["outcome"]
    # the exploration's wall cap (virtual seconds): valid at or above the minimum, a cut at the cap
    out, sess, _r, cp = run3_small(chain, n_workers=2, arm_tick_cap=10 ** 7, min_arm_ticks=500, wall_caps_s={"p1": 90.0, "T": 2.0, "C": 0.0, "verify": 300.0}, global_cap_s=900.0)
    tT = sess.ledgers["T"].ticks
    check(sess.arm_records["T"]["stop"][0] == "wall_cap" and 500 <= tT < 10 ** 7 and not out["rule"]["incomplete"], f"a wall-capped exploration at or above the minimum is valid ({tT}): {out['rule']['incomplete']}")
    res["wall_cap"] = tT
    # the replay cap: INCOMPLETE only when an unverified candidate could change the outcome (no identity replays here, so the cap acts on the claims alone)
    out, sess, _r, cp = run3_small(chain, replay_tick_cap=150, arm_tick_cap=12000, min_arm_ticks=2000, identity_k=0)
    ver = json.loads((sess.cfg.session_dir / "verification.json").read_text(encoding="utf-8"))
    check(ver["cap_hit"] is not None, "the replay cap was hit")
    if out["rule"]["outcome"] == "INCOMPLETE":
        check(any("could raise m" in x or "could reach" in x for x in out["rule"]["incomplete"]), f"INCOMPLETE only with a reason: {out['rule']['incomplete']}")
    else:
        check(ver["arm"]["max_m_unverified"] <= ver["arm"]["m"] and not (ver["arm"]["t_claimed_online"] >= 8 and ver["arm"]["max_targets"] < 8), "a cap that cannot change the outcome is not INCOMPLETE")
    res["replay_cap"] = out["rule"]["outcome"]
    # a software error in the verification is recorded, never swallowed
    return res


def unit_session3_milestones_and_stops() -> Dict[str, Any]:
    """Real sessions of the engine on two stub worlds: the recorded decision is exactly the registered rule applied to the verified m and t (recomputed independently), whatever the
    outcome is, and both PROGRESS bases and NO_NEW_MILESTONE are reached by some deterministic configuration."""
    seen: Dict[str, Any] = {}
    for world in ("easy", "hard", "calm"):
        chain = build_chain(world, rd1_caps=(30000, 24000), rd2_ticks=12000)
        out, sess, root, cp = run3_small(chain, arm_tick_cap=60000, min_arm_ticks=20000)
        rule = out["rule"]
        check(rule["outcome"] in ("PROGRESS", "NO_NEW_MILESTONE") and not rule["invalid"] and not rule["incomplete"], f"{world}: {rule['outcome']} {rule['invalid']} {rule['incomplete']}")
        v = sess.verified
        again = rule3.apply(invalid=[], incomplete=[], m=v["m"], t=v["max_targets"], prior=r3.prior_milestones(cp["rd1"], cp["rd2"]), **rule["extra"]["rule_inputs"])
        for k in ("outcome", "m", "max_targets_verified", "progress_basis", "any_stop", "highest_milestone"):
            check(again[k] == rule[k], f"{world}: the recorded {k} {rule[k]} differs from the rule applied to the verified m and t {again[k]}")
        check((rule["outcome"] == "PROGRESS") == (v["m"] >= 2 or v["max_targets"] >= 8), f"{world}: PROGRESS iff m >= 2 or t >= 8")
        check(rule["stops"]["S2"]["triggered"] == (max(rule["prior_sessions"]["rd1"]["m"], rule["prior_sessions"]["rd2"]["m"], v["m"]) < 2), f"{world}: S2 follows the three sessions' milestones")
        vr = rpt3.verify_run3(root, cp["rd2"], cp["rd1"], "rd3")
        check(vr["ok"], f"{world}: verify-run: {vr['problems']}")
        reps = [json.loads(x) for x in (root / "sessions" / "rd3" / "verification" / "replays.jsonl").read_text(encoding="utf-8").splitlines()]
        check(rpt3.replay_verified_m(reps) == rule["m"] and rpt3.replay_verified_t(reps) == rule["max_targets_verified"], f"{world}: m and t recomputed from the replay records")
        check(rule["m"] != 1 and not (root / "routes" / "T_L0").exists(), f"{world}: the wall-top landing is never claimed in rd3")
        for name in ("crossing", "left_target", "clear", "t"):
            r = root / "routes" / f"T_{name}"
            if name in v["claims"]:
                check((r / "actions.jsonl").is_file() and (r / "metadata.json").is_file(), f"{world}: the route of {name} is saved")
        seen[world] = {"outcome": rule["outcome"], "m": v["m"], "t": v["max_targets"], "basis": rule["progress_basis"], "stops": rule["any_stop"]}
        shutil.rmtree(cp["t"], ignore_errors=True)
    check("NO_NEW_MILESTONE" in {v["outcome"] for v in seen.values()}, f"some deterministic configuration ends in NO_NEW_MILESTONE: {seen}")
    check("PROGRESS" in {v["outcome"] for v in seen.values()}, f"some deterministic configuration ends in PROGRESS: {seen}")
    return seen


def unit_session3_determinism() -> Dict[str, Any]:
    """Two independent builds of the same chain and two runs of the same rd3 session agree on every ledger event, cell, word and decision."""
    c1 = build_chain("hard", cache=False)
    c2 = build_chain("hard", cache=False)

    def chain_sig(c: Mapping[str, Any]) -> Dict[str, Any]:
        return {t: {n: mw.sha256_file(c[t] / "archive" / n) for n in ("cells.jsonl", "bursts.bin", "bursts.idx.jsonl", "events.jsonl")} for t in ("rd1", "rd2")}

    check(chain_sig(c1) == chain_sig(c2), "two builds of the synthetic chain are byte-identical (cells, words, index, ledger)")
    o1, s1_, r1, cp1 = run3_small(c1)
    o2, s2_, r2, cp2 = run3_small(c1)
    sig1, sig2 = signature(r1), signature(r2)
    check(sig1 == sig2, "two runs of the same rd3 session agree on the archive's data files and on the decision")
    check(o1["rule"]["outcome"] == o2["rule"]["outcome"] and s1_.ledgers["T"].ticks == s2_.ledgers["T"].ticks and len(s1_.ledgers["T"].candidates) == len(s2_.ledgers["T"].candidates),
          "outcome, ticks and candidates agree")
    for c in (c1, c2, cp1, cp2):
        shutil.rmtree(c["t"], ignore_errors=True)
    return {"files": len(sig1["files"])}


# -- guards, budget, approval, pins ---------------------------------------------------------------------------------------------------------------------


def unit_write_guard_two_roots() -> Dict[str, Any]:
    t = tmpdir("m8wg3_")
    p1_, p2_, other = t / "rd1", t / "rd2", t / "rd3"
    for d in (p1_, p2_, other):
        d.mkdir()
        (d / "f.txt").write_text("x", encoding="utf-8")
    mw.ProvenanceGuard.install()
    w2.WriteGuard.install([p1_, p2_])
    base = len(mw.ProvenanceGuard.violations)
    try:
        (other / "o.txt").write_text("z", encoding="utf-8")
        shutil.copyfile(p1_ / "f.txt", other / "copy1.txt")
        shutil.copyfile(p2_ / "f.txt", other / "copy2.txt")
        open(p1_ / "f.txt", "rb").close()
        open(p2_ / "f.txt", "rb").close()
        check(len(mw.ProvenanceGuard.violations) == base, "reads of both earlier trees and writes under rd3's own root are not violations")
        for name, root in (("rd1", p1_), ("rd2", p2_)):
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
    return {"roots": 2}


def unit_budget_projection3() -> Dict[str, Any]:
    caps = ses3.caps()
    check(caps["wall_caps_s"] == {"p1": 240.0, "T": 3000.0, "verify": 360.0} and caps["global_cap_s"] == 3600.0, f"the registered wall caps: {caps['wall_caps_s']}")
    check(caps["exploration_tick_cap"] == 6_000_000 and caps["min_exploration_ticks"] == 2_000_000 and caps["open_tick_cap"] == 70_000 and caps["replay_tick_cap"] == 400_000
          and caps["identity_k"] == 16 and caps["max_battleship_processes"] == 10, "the registered tick caps")
    check(caps["memory_caps_mb"] == {"main_private": 3072, "tree_private": 9216, "tree_working_set": 4096, "system_available_min": 1024, "system_commit_free_min": 2048}, "memory caps as rd1's and rd2's")
    check(caps == ses2.caps(), "every cap equals rd2's")
    proj = rpt3.budget_projection(caps)
    check(proj["caps_s"]["sum"] == proj["caps_s"]["session_hard_cap"] == 3600.0, "the phase caps sum to the session cap")
    check(proj["pessimistic"]["valid"] and proj["pessimistic"]["fits_hard_cap"] and proj["every_cap_binding"]["equals_hard_cap"] and proj["fits_hard_cap_without_trimming"],
          f"the pessimistic projection fits without trimming: {proj['pessimistic']}")
    check(proj["pessimistic"]["wall_s"]["total"] <= 3600.0 and proj["expected"]["wall_s"]["total"] <= proj["pessimistic"]["wall_s"]["total"], "expected <= pessimistic <= cap")
    check(proj["expected"]["exploration_ticks"] > 2_000_000 and not proj["expected"]["tick_cap_binds"], "the expected exploration is valid and the wall cap binds first")
    return {"pessimistic_s": proj["pessimistic"]["wall_s"]["total"], "expected_ticks": round(proj["expected"]["exploration_ticks"]), "pessimistic_ticks": proj["pessimistic"]["exploration_ticks"]}


def unit_approval_isolated3() -> Dict[str, Any]:
    want = ses3.identity()
    t = tmpdir("m8ap3_")
    p = t / "approval.json"
    ok, why = ses3.approval_status(p, want)
    check(not ok and "no approval record" in why, "no record: refused")
    good = dict(want, approval="APPROVED by the test", revision=1)
    p.write_text(json.dumps(good), encoding="utf-8")
    check(ses3.approval_status(p, want) == (True, "approved"), "a matching record is accepted")
    p.write_text(json.dumps(dict(good, approval="PENDING")), encoding="utf-8")
    check(not ses3.approval_status(p, want)[0], "PENDING is refused")
    n = 0
    alter = {"rule_sha256": "0" * 64, "executable_sha256": "0" * 64, "scope": "other", "archive_id": "x", "workers": 4, "burst_words": 121, "horizon": 3599,
             "flags": {"explore": {}, "verify": {}}, "contracts": dict(want["contracts"], m8_rd_select_v2="0" * 64), "key_strings": {"select_rd3": "x"},
             "runtime_files": {"BattleShip.o2r": "0" * 64}, "p1": {}, "readiness": {"min_available_mb": 1}, "git_head": "0" * 40, "session": "rdX", "gate": "x", "milestone": "M9",
             "rule": "other", "draws_sha256": "0" * 64, "rd3_session_event_digest": "0" * 64,
             "base": dict(want["base"], rd2_increment_manifest_sha256="0" * 64), "open_overlay": {"sha256": "0" * 64}, "budgets": {"hard_cap": "61 min"},
             "docs_sha256": {"docs/x.md": "0" * 64}}
    for k, v in alter.items():
        p.write_text(json.dumps(dict(good, **{k: v})), encoding="utf-8")
        check(not ses3.approval_status(p, want)[0], f"an altered {k} was accepted")
        n += 1
    for k in list(want["base"]):
        b = dict(want["base"])
        b[k] = "altered"
        p.write_text(json.dumps(dict(good, base=b)), encoding="utf-8")
        check(not ses3.approval_status(p, want)[0], f"an altered base entry {k} was accepted")
        n += 1
    for k in list(want["caps"]):
        caps = dict(want["caps"])
        caps[k] = {"x": 1}
        p.write_text(json.dumps(dict(good, caps=caps)), encoding="utf-8")
        check(not ses3.approval_status(p, want)[0], f"an altered cap {k} was accepted")
        n += 1
    for f in list(want["code"]):
        code = dict(want["code"])
        code[f] = "0" * 64
        p.write_text(json.dumps(dict(good, code=code)), encoding="utf-8")
        check(not ses3.approval_status(p, want)[0], f"an altered code hash for {f} was accepted")
        n += 1
    p.write_text(json.dumps(dict(good, d_records={"folders": ["2026-09-28"], "digest": "0" * 64})), encoding="utf-8")
    check(not ses3.approval_status(p, want)[0], "an altered D: records digest")
    p.write_text("{not json", encoding="utf-8")
    raises(ValueError, lambda: ses3.approval_status(p, want), "an unreadable record raises")
    check(ses3.APPROVAL != p and ses3.APPROVAL.name == "rl_m8_rd3_approval.json", "the repository path is untouched by the tests")
    check(set(want["contracts"]) == {"m8_rd_cell_v1", "m8_rd_select_v1", "m8_rd_explore_v1", "m8_rd_claims_v1", "track1_btt_s9_b8_v1", "btt_action_class_table_v2", "m8_rd_select_v2"}, "contract digests")
    check(want["rule"] == "m8_rd3_rule_v1" and want["workers"] == 5 and want["horizon"] == 3600 and want["base"]["rd2_checkpoint_seq"] == 20
          and want["base"]["rd2_increment"] == r3.RD2_INCREMENT_NAME and want["base"]["first_rd3_iteration"] == 6212 and want["rd3_session_event_digest"] == want["contracts"]["m8_rd_select_v2"]
          and want["base"]["rd2_session_event"]["name"] == "rd2" and want["base"]["rd2_session_event"]["digest"] == want["contracts"]["m8_rd_select_v2"],
          "registered identity entries (rd3's session digest is the selection digest rd2 recorded)")
    check(want["open_overlay"]["expected_counts"] == r3.EXPECTED_CLOSE_OVERLAY and len(want["open_overlay"]["sha256"]) == 64, "the open overlay is pinned")
    for f in ses3.NEW_CODE_FILES:
        check(f"rl/{f}" in want["code"] or not (RL_DIR / f).is_file(), f"{f} is pinned")
    check(all(f"rl/{f}" in want["code"] for f in ("m8_rd_select2.py", "m8_rd2_run.py", "m8_rd2_tests.py", "m8_rd_tests.py", "m8_rd_cells.py")), "rd1's and rd2's code is pinned too")
    shutil.rmtree(t, ignore_errors=True)
    return {"altered_entries_refused": n}


def unit_import_isolation3() -> Dict[str, Any]:
    code = ("import sys; sys.path.insert(0, r'%s'); " % RL_DIR + "import m8_rd3_select, m8_rd3_resume, m8_rd3_run, m8_rd3_session, m8_rd3_rule, m8_rd3_report; "
            "print(sorted(m for m in ('torch', 'numpy', 'gymnasium', 'stable_baselines3', 'm7u3_gate', 'm7f_trace', 'm7n_crossing', 'm7g_fixture', 'btt_learning', "
            "'m7h_curriculum') if m in sys.modules))")
    r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=120)
    check(r.stdout.strip() == "[]", f"the rd3 modules imported heavy ones: {r.stdout.strip()} {r.stderr[-300:]}")
    return {}


def unit_source_guard3() -> Dict[str, Any]:
    """No rd3 module reads fixtures, recordings, the TAS or any .btti file; none imports a learning framework or the random module; and no call that writes can take a path built
    from rd1's or rd2's root (both earlier trees are read-only)."""
    forbidden = ("rl/fixtures", "fixtures/m7g", "m7g/capture", "tas_input", "mario_743", ".btti", "btti_replay", "crossing_fixture", "rl_crossing")
    bad_imports = {"random", "torch", "gymnasium", "stable_baselines3", "numpy", "pandas", "scipy", "sklearn"}
    write_attrs = {"write_text", "write_bytes", "mkdir", "unlink", "rmdir", "touch", "rename", "replace", "chmod"}
    copy_funcs = {"copyfile", "copy", "copy2", "copytree", "move"}
    writers = {"write_json", "append_jsonl", "save_checkpoint", "write_files", "rmtree", "rmtree_retry", "remove_tree_retry", "replace_retry", "makedirs"}
    names_earlier = ("rd1_root", "RD1_ROOT", "rd1_archive_dir", "M8_ROOT", "rd2_root", "RD2_ROOT", "rd2_archive_dir", "rd1_dir", "rd2_dir", "RD1_REAL", "RD2_REAL")
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
    check(not hits, f"forbidden vocabulary, imports or writes in the rd3 modules: {hits}")
    # the tests file itself never opens a real tree for writing either: the only real paths it names are RD1_REAL / RD2_REAL, read through loaders
    tests_src = (RL_DIR / "m8_rd3_tests.py").read_text(encoding="utf-8")
    for nd in ast.walk(ast.parse(tests_src)):
        if isinstance(nd, ast.Call):
            f = nd.func
            fname = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
            if fname in write_attrs | writers | copy_funcs and any(n in ast.unparse(nd) for n in ("RD1_REAL", "RD2_REAL")):
                raise Failure(f"the tests write through a real tree's path: {ast.unparse(nd)[:100]}")
    return {"modules": len(NEW_MODULES)}


def unit_tracked_files_unchanged3() -> Dict[str, Any]:
    import m8_rd_session as ses1

    check(ses1.tracked_changes() == [], f"tracked files differ from HEAD: {ses1.tracked_changes()[:5]}")
    check(ses1.untracked_not_new() == [], f"git status shows more than new files: {ses1.untracked_not_new()[:5]}")
    for f in RD1_FILES:
        r = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", str(RL_DIR / f"{f}.py")], cwd=REPO_ROOT)
        check(r.returncode == 0, f"{f}.py differs from HEAD")
        r = subprocess.run(["git", "ls-files", "--error-unmatch", str(RL_DIR / f"{f}.py")], cwd=REPO_ROOT, capture_output=True)
        check(r.returncode == 0, f"{f}.py is not tracked")
    for d in ses3.DOC_FILES:
        if d in ("docs/rl_m8_rd3_decisions_2026-10-02.md", "docs/rl_m8_rd3_implementation.md"):
            continue
        r = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", str(REPO_ROOT / d)], cwd=REPO_ROOT)
        check(r.returncode == 0, f"{d} differs from HEAD")
    return {"earlier_files": len(RD1_FILES)}


def unit_snapshot_tool3() -> Dict[str, Any]:
    t = tmpdir("m8sn3_")
    dest = t / "snap"
    r = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_rd3_snapshot.py"), "snapshot", "--dest", str(dest)], capture_output=True, text=True, timeout=900)
    check(r.returncode == 0, f"snapshot: {r.stdout[-500:]} {r.stderr[-500:]}")
    rec = json.loads((dest / "snapshot.json").read_text(encoding="utf-8"))
    check(rec["result"] == "PASS" and rec["n_files"] > 30 and not rec["problems"] and not rec["identity_code_mismatch"] and not rec["identity_docs_mismatch"],
          f"snapshot record: {rec['result']} {rec['problems']} {rec['identity_code_mismatch']} {rec['identity_docs_mismatch']}")
    names = {f["path"] for f in rec["files"]}
    check({"rl/m8_rd3_select.py", "rl/m8_rd3_run.py", "rl/m8_rd3_rule.py", "rl/m8_rd_select2.py", "rl/m8_rd2_run.py", "rl/m8_rd_cells.py", "docs/rl_m8_rd_continuation_proposal_2026-10-02.md",
           "docs/rl_m8_rd3_decisions_2026-10-02.md"} <= names, "the snapshot holds the rd1, rd2 and rd3 code and the decisions")
    r = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_rd3_snapshot.py"), "verify", "--dest", str(dest)], capture_output=True, text=True, timeout=900)
    check(r.returncode == 0, f"verify: {r.stdout[-300:]}")
    r = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_rd3_snapshot.py"), "snapshot", "--dest", str(dest)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 2, "an existing destination is never overwritten")
    victim = dest / "files" / "rl" / "m8_rd3_select.py"
    victim.write_bytes(victim.read_bytes() + b"\n#tampered\n")
    r = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_rd3_snapshot.py"), "verify", "--dest", str(dest)], capture_output=True, text=True, timeout=900)
    check(r.returncode == 1 and "m8_rd3_select.py" in r.stdout, "a tampered copy fails the verification")
    ps = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_rd3_snapshot.py"), "powershell", "--dest", str(dest)], capture_output=True, text=True, timeout=60)
    check("Get-FileHash" in ps.stdout, "the independent re-hash script is generated")
    shutil.rmtree(t, ignore_errors=True)
    return {"files": rec["n_files"]}


# -- the closed real trees (read only) -----------------------------------------------------------------------------------------------------------------


CLOSING_OVERLAY_SHA256 = "551a723bdd94d1f5fd3a8293e5f68b22b8fe0397cdb28e7c1091378b9461ba1b"      # the closing v2 overlay of rd2's archive, as computed at the preparation


def unit_open_protocol_real_trees() -> Dict[str, Any]:
    """The open protocol R1-R5 on the real, closed rd1 and rd2 trees and their D: increments (read only): both trees equal their increments, rd2's closing archive rebuilds and its
    session digest equals the one recomputed from the current selection contract, and the closing v2 overlay reproduces rd2's record exactly."""
    check((RD2_REAL / "archive" / "manifest.sha256").is_file() and ses3.INCREMENT_RD2.is_dir() and ses3.INCREMENT_RD1.is_dir(), "the closed rd2 tree and both D: increments are required")
    op = ses3.open_protocol3()
    check(op["ok"], f"the open protocol on the real trees: {op['problems']}")
    check(op["R1_rd1_immutability"]["files"] == 166 and op["R1_rd2_immutability"]["files"] == 62 and op["R1_rd2_immutability"]["bytes"] == 66_759_098
          and op["R1_rd2_immutability"]["manifest_sha256"] == r3.RD2_INCREMENT_MANIFEST_SHA256, f"R1: {op['R1_rd1_immutability']} {op['R1_rd2_immutability']}")
    f2 = op["R2_R4_rd2_archive"]
    check(f2["counts"] == {"cells": 19062, "bursts": 6212, "events": 12425} and f2["dispatch_iterations"] == [0, 6211] and f2["first_rd3_iteration"] == 6212 and f2["rd2_checkpoint_seq"] == 20
          and f2["audit"]["ok"] and f2["audit"]["cells"] == 19062 and f2["session_event"]["digest"] == f2["digest_recomputed"], f"R2/R4: {f2}")
    check(f2["diag2"] == {"bound_violations": 0, "doomed_incumbent_replacements": 4002, "newly_descent_doomed": 6859, "revivals": 4312}, "rd2's counters")
    ov = op["R5_overlay"]
    check(ov["ok"] and ov["stored_close_counts_equal"] and ov["sha256"] == CLOSING_OVERLAY_SHA256 and ov["counts"]["eligible_v2"] == 11794 and ov["counts"]["cells"] == 19062,
          f"R5: the closing overlay reproduces rd2's record: {ov['sha256']} {ov['counts']['eligible_v2']}")
    return {"overlay": ov["sha256"][:12], "cells": f2["counts"]["cells"]}


# -- `cmd_run` against a fake game (real lifecycle code, real worker processes; invariants only) ---------------------------------------------------------


def unit_cmd_run3_with_fake_game() -> Dict[str, Any]:
    """`run`'s own sequence against the REAL lifecycle code and a fake game, on a synthetic chain: the open protocol (R1-R5 at both levels), materialise, rd1's frozen runtime read in
    place, the whole-process-tree sampler, the real worker processes, the close checks. Only the preflight (tested on its own) and the kill-on-close job are replaced. The
    assertions hold under every schedule: the outcome is any registered one but INVALID (an INCOMPLETE is accepted only for a cap of the registered kinds), and no assertion
    needs a candidate, a milestone or a verification replay to have occurred. The four-diagnostics flag set of the verification replays is checked by a DIRECT replay of a
    constructed candidate through the real replay path."""
    import m7_runtime
    import m8_rd_session as ses1

    fg = t1.fake_game_setup("m8cr3_")
    t = fg["t"]
    (fg["exe_dir"] / "config.yml").write_text("fake: true\n", encoding="utf-8")
    fx = t1.fake_flags(fg, "easy")
    fv = dict(fx, SSB64_RL_ENTITY="1", SSB64_RL_TARGET_DIAG="1", SSB64_RL_INPUT="1")
    saved1 = {k: getattr(ses1, k) for k in ("EXECUTABLE", "EXE_DIR", "RUNTIME_FILES", "p1_inputs")}
    keys3 = ("RD1_ROOT", "RD2_ROOT", "RD3_ROOT", "APPROVAL", "INCREMENT_RD1", "INCREMENT_RD2", "EXECUTABLE", "EXE_DIR", "FLAGS_EXPLORE", "FLAGS_VERIFY", "N_WORKERS", "RD1_EXPECT",
             "RD2_EXPECT", "CHECK_EXPECTED_OVERLAY", "preflight")
    saved3 = {k: getattr(ses3, k) for k in keys3}
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
        chain = build_chain("easy", rd1_caps=(16000, 12000), rd2_ticks=8000, flags={"explore": fx, "verify": fv}, exe_sha=exe_sha, runtime_files=rt_pins, cache=False)
        approval = {"approval": "APPROVED by the test", "revision": 1, "executable_sha256": exe_sha, "contracts": chain["pins"]["contracts"], "flags": {"explore": fx, "verify": fv},
                    "git_head": "0" * 40, "rule_sha256": rule3.rule_digest(), "p1": {}}
        (t / "approval.json").write_text(json.dumps(approval), encoding="utf-8")
        ses3.RD1_ROOT, ses3.RD2_ROOT, ses3.RD3_ROOT = chain["rd1"], chain["rd2"], t / "rd3"
        ses3.APPROVAL, ses3.INCREMENT_RD1, ses3.INCREMENT_RD2 = t / "approval.json", chain["inc1"], chain["inc2"]
        ses3.EXECUTABLE, ses3.EXE_DIR, ses3.FLAGS_EXPLORE, ses3.FLAGS_VERIFY = fg["cmd"], fg["exe_dir"], fx, fv
        ses3.N_WORKERS = 2
        ses3.RD1_EXPECT, ses3.RD2_EXPECT = chain["expect1"], chain["expect2"]
        ses3.CHECK_EXPECTED_OVERLAY = False
        ses3.preflight = lambda **k: {"ok": True, "problems": [], "executable_sha256": exe_sha, "git_head": "0" * 40}
        m7_runtime.install_kill_on_close_job = lambda: None

        def build(*a: Any, **k: Any) -> Any:
            env = saved_env2(*a, **k)
            env.analyse = stub.analyse                                   # the fake game has no target diagnostic
            return env

        ses2.build_real_env2 = build
        rc = ses3.cmd_run(overrides=dict(arm_tick_cap=3000, arm_caps={"T": 3000}, min_arm_ticks=1000, verify_threads=2, identity_k=4,
                                         wall_caps_s={"p1": 240.0, "T": 600.0, "C": 0.0, "verify": 600.0}, global_cap_s=1800.0, p1_tick_cap=20000))
        check(rc == 0, "cmd_run returned 0")
        root = t / "rd3"
        sd = root / "sessions" / "rd3"
        for f in ("open.json", "approval_copy.json", "p1.json", "identity_open.json", "rule.json", "close.json", "memory_summary.json", "memory_tree.jsonl", "state.json", "arm_T.json"):
            check((sd / f).is_file(), f"missing {f}")
        rule = json.loads((sd / "rule.json").read_text(encoding="utf-8"))
        check(rule["outcome"] in rule3.OUTCOMES and rule["outcome"] != "INVALID" and not rule["invalid"], f"cmd_run's session: {rule['outcome']} {rule['invalid']}")
        if rule["outcome"] == "INCOMPLETE":
            check(all(any(w in x for w in ("wall cap", "reached", "hard cap", "memory cap", "in flight", "BattleShip processes", "not ready")) for x in rule["incomplete"]),
                  f"an INCOMPLETE only for a cap or a lifecycle limit: {rule['incomplete']}")
        else:
            check(sd.joinpath("arm_T.json").is_file() and json.loads(sd.joinpath("arm_T.json").read_text(encoding="utf-8"))["ticks"] == 3000, "a complete session explored exactly its cap")
        op = json.loads((sd / "open.json").read_text(encoding="utf-8"))
        check(op["pins"]["approval_sha256"] == mw.sha256_file(t / "approval.json") and op["pins"]["executable_sha256"] == exe_sha, "the open record pins the approval and the executable")
        check((sd / "approval_copy.json").read_bytes() == (t / "approval.json").read_bytes(), "a verbatim copy of the approval")
        o = op["open_protocol"]
        check(o["R1_rd1_immutability"]["ok"] and o["R1_rd2_immutability"]["ok"] and o["R5_overlay"]["ok"] and o["R2_R4_rd2_archive"]["ok"], "the open record holds R1-R5 at both levels")
        check("wall_top_cells" in op["wall_top_selection_at_the_open"] and op["wall_top_selection_at_the_open"]["total_probability"] >= 0.0, "the open record holds the wall-top selection probability")
        check((root / "base" / "events.jsonl").read_bytes() == (chain["rd2"] / "archive" / "events.jsonl").read_bytes(), "rd3's base ledger is rd2's closing ledger, byte for byte")
        log = t1.fake_log(fg)
        frozen_h = chain["frozen"]["BattleShip.cfg.json"]
        check(log and all(x["cfg_sha256"] == frozen_h for x in log), f"every process read rd1's FROZEN configuration ({len(log)} launches)")
        check(all(x["cfg_sha256"] != fg["live_hash"] for x in log), "no process read the live configuration")
        check(t1.wait_dead([x["pid"] for x in log], 30.0) == [], "no fake game process survived the run")
        check(both_immutability(chain)["ok"], "both earlier trees are byte-identical to their increments after the run")
        # the four-diagnostics flag set of the verification replays: a direct replay of a constructed candidate through the real replay path
        meta1 = json.loads((chain["rd1"] / "archive" / "archive_meta.json").read_text(encoding="utf-8"))
        cfg = ses3.run_config(root=t / "rd3")
        env = ses3.build_real_env3(cfg, chain["rd1"] / "archive" / "runtime", meta1["pins"]["frozen_sha256"], {"executable_sha256": exe_sha, "runtime_files": meta1["pins"]["runtime_files"]})
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
        ses3.preflight = lambda **k: {"ok": False, "problems": ["x"]}
        ses3.RD3_ROOT = t / "rd3_never"
        check(ses3.cmd_run() == 2 and not (t / "rd3_never").exists(), "a failing preflight refuses before anything is created")
    finally:
        ses2.build_real_env2 = saved_env2
        for k, v in saved3.items():
            setattr(ses3, k, v)
        for k, v in saved1.items():
            setattr(ses1, k, v)
        m7_runtime.install_kill_on_close_job = saved_job
        m7_runtime.prepare_worker_runtime = saved_prep
        w2.WriteGuard.clear()
        shutil.rmtree(t, ignore_errors=True)
        if chain is not None:
            shutil.rmtree(chain["t"], ignore_errors=True)
    return {"launches": len(log), "outcome": rule["outcome"]}


# -- the wall-top label, the unverified claims, strict records ------------------------------------------------------------------------------------------


class InjectL0Pool(SyncPool):
    """A lock-step pool that makes the first rd3 burst look like one that stood on floor line 0 right after its prefix (as a burst from a wall-top cell does)."""

    target_iteration: Optional[int] = None

    def send(self, i: int, job: Dict[str, Any]) -> None:
        super().send(i, job)
        if self.target_iteration is not None and job.get("iteration") == self.target_iteration and job.get("kind") == "iterate2":
            res = self.done[-1][2]
            if res.get("ok") and res.get("words") and res.get("labels") is not None:
                res["labels"]["first"]["l0"] = len(bytes(job["words"])) + 1


def unit_wall_top_label_suppressed() -> Dict[str, Any]:
    """A burst that continues from a prefix standing on floor line 0 would create an `l0` candidate that the frozen claims engine replays against the first line-0 tick of the WHOLE
    trajectory (the prefix's): inexact, a false INVALID. rd3 removes the label before the job is committed, records the sighting and never claims the landing."""
    import copy
    import m8_rd_claims as mclaims

    first = {"l0": 121, "left_live": None, "left_floor": None, "left_break": None, "clear": None}
    res = {"iteration": 7000, "cell": 5, "L": 120, "labels": {"t": 3, "breaks": [], "t_events": [], "first": dict(first)}}
    out, sighting = run3.suppress_wall_top_label(res, True)
    check(out["labels"]["first"]["l0"] is None and res["labels"]["first"]["l0"] == 121 and out is not res, "the label is removed from a copy; the input is untouched")
    check(sighting == {"iteration": 7000, "cell": 5, "L": 120, "post_prefix_tick": 121, "start_cell_on_wall_top": True, "first_tick_of_the_burst": True}, f"the sighting: {sighting}")
    out2, sighting2 = run3.suppress_wall_top_label(dict(res, labels=dict(res["labels"], first=dict(first, l0=None))), False)
    check(sighting2 is None and out2["labels"]["first"]["l0"] is None, "no landing, no sighting")
    out3, sighting3 = run3.suppress_wall_top_label({"iteration": 1, "labels": None}, False)
    check(sighting3 is None, "a result without labels (a cut job) is left alone")
    _o, s4 = run3.suppress_wall_top_label(dict(res, labels=dict(res["labels"], first=dict(first, l0=150))), False)
    check(s4["start_cell_on_wall_top"] is False and s4["first_tick_of_the_burst"] is False, "a landing found afresh is told apart from a continuation")
    # the hazard in the frozen engine: a trajectory whose PREFIX stands on line 0 (tick 20) and whose burst lands again (tick 31)
    world = "hard"
    neutral = mcell.TRIPLES.index((0, 0, 0))
    words = bytes([neutral]) * 40
    tr = stub.replay_trace(world, words)
    steps = copy.deepcopy(tr["steps"])
    for tick in (20, 31):
        steps[tick - 1]["observation"]["ground_air_state"] = 0
        steps[tick - 1]["spatial"]["fighter"]["floor_line_id"] = mcell.L0_FLOOR_LINE
    trace = dict(tr, steps=steps)
    led = mclaims.ArmLedger("T")
    cb = led.commit(100)
    labels = {"t": 10, "breaks": [], "t_events": [], "first": dict(first, l0=31)}
    led.register(cum_before=cb, iteration=1, words=words, prefix_len=30, labels=labels, breaks=[], end_reason="length", t_end=10)
    check(led.l0_cid is not None, "unsuppressed, the ledger registers an l0 candidate")
    cand = led.candidates[led.l0_cid]
    rep = mclaims.evaluate_replay(trace, cand, len(cand["words"]), stub.analyse)
    check(not rep["exact"] and any("first wall-top landing at 20, claimed 31" in p for p in rep["problems"]), f"the frozen engine fails such a candidate: {rep['problems']}")
    led2 = mclaims.ArmLedger("T")
    cb = led2.commit(100)
    suppressed, _s = run3.suppress_wall_top_label({"iteration": 1, "cell": 1, "L": 30, "labels": labels}, True)
    led2.register(cum_before=cb, iteration=1, words=words, prefix_len=30, labels=suppressed["labels"], breaks=[], end_reason="length", t_end=10)
    check(led2.l0_cid is None and not [c for c in led2.candidates if c["kind"] == "l0"], "suppressed, there is no l0 candidate to fail")
    # the milestone of rd3 never counts the wall-top landing
    reps = [{"exact": True, "l0": True, "crossing": False, "left_target": False, "clear": False, "t": 7}, {"exact": False, "l0": True, "crossing": True, "left_target": True, "clear": True, "t": 9},
            {"exact": True, "l0": True, "crossing": True, "left_target": False, "clear": False, "t": 7}]
    check(rpt3.replay_verified_m(reps[:1]) == 0 and rpt3.replay_verified_m(reps[:2]) == 0 and rpt3.replay_verified_m(reps) == 2 and rpt3.replay_verified_m([]) == 0,
          "m counts crossing / left target / clear of exact replays only, never the wall-top landing")
    # the whole session: the first rd3 burst is made to look like a wall-top continuation
    chain = build_chain()
    first_it = chain["expect2"]["dispatch_iterations"][1] + 1

    class Pool(InjectL0Pool):
        target_iteration = first_it

    def pool_factory(env: Any, cfg: Any, clock: FakeClock) -> SyncPool:
        return Pool(env, cfg, clock)

    out, sess, root, cp = run3_small(chain, pool_factory=pool_factory)
    rule = out["rule"]
    check(rule["outcome"] in ("PROGRESS", "NO_NEW_MILESTONE") and not rule["invalid"] and not rule["incomplete"], f"the session with a wall-top sighting: {rule['outcome']} {rule['invalid']}")
    sd = sess.cfg.session_dir
    rows = [json.loads(x) for x in (sd / "wall_top_sightings.jsonl").read_text(encoding="utf-8").splitlines()]
    check(len(rows) == 1 and rows[0]["iteration"] == first_it and rows[0]["first_tick_of_the_burst"], f"the sighting is recorded, never claimed: {rows}")
    check(json.loads((sd / "arm_T.json").read_text(encoding="utf-8"))["wall_top_sightings"]["bursts"] == 1, "the arm record counts the sighting")
    check(sess.ledgers["T"].l0_cid is None and not (root / "routes" / "T_L0").exists(), "no wall-top claim, no wall-top route")
    check(rpt3.verify_run3(root, cp["rd2"], cp["rd1"], "rd3")["ok"], "verify-run")
    # without the suppression (rd1's commit) the same session is INVALID: the false inexact replay
    class Unsuppressed(run3.Session3):
        commit = mrun.Session.commit

    out_u, sess_u, _r, _cp = run3_small(chain, pool_factory=pool_factory, session_cls=Unsuppressed)
    check(out_u["rule"]["outcome"] == "INVALID" and any("inexact replay" in x and "first wall-top landing" in x for x in out_u["rule"]["invalid"]),
          f"without the suppression the session is a false INVALID: {out_u['rule']['outcome']} {out_u['rule']['invalid']}")
    return {"sightings": len(rows)}


def unit_session3_unverified_claims() -> Dict[str, Any]:
    """A claim of eight targets that cannot be (or is not) verified never reaches PROGRESS: left unverified at the replay cap it is INCOMPLETE; replayed and not reproduced it is INVALID."""
    chain = build_chain()

    class WithT8(run3.Session3):
        def run_arm(self, arm: str) -> Dict[str, Any]:
            rec = super().run_arm(arm)
            led = self.ledgers["T"]
            labels = {"t": 8, "breaks": [], "t_events": [(150, 8)], "first": {"l0": None, "left_live": None, "left_floor": None, "left_break": None, "clear": None}}
            led.register(cum_before=0, iteration=self.first_iteration, words=bytes([mcell.TRIPLES.index((0, 0, 0))]) * 200, prefix_len=0, labels=labels, breaks=[], end_reason="length", t_end=8)
            return rec

    out, sess, _r, _cp = run3_small(chain, session_cls=WithT8, replay_tick_cap=100, identity_k=0, arm_tick_cap=6000, min_arm_ticks=2000)
    rule = out["rule"]
    check(rule["outcome"] == "INCOMPLETE" and any("could reach 8 targets" in x for x in rule["incomplete"]) and rule["outcome"] != "PROGRESS", f"an unverified claim of eight targets at the cap: {rule['outcome']} {rule['incomplete']}")
    out, sess, _r, _cp = run3_small(chain, session_cls=WithT8, identity_k=0, arm_tick_cap=6000, min_arm_ticks=2000)
    rule = out["rule"]
    check(rule["outcome"] == "INVALID" and any("inexact replay" in x for x in rule["invalid"]) and rule["max_targets_verified"] < 8, f"a claim the replay does not reproduce: {rule['outcome']} {rule['invalid']}")
    return {}


def unit_strict_records() -> Dict[str, Any]:
    chain = build_chain()
    cp = copy_chain(chain)
    p = cp["rd2"] / "sessions" / "rd2" / "rule.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    del d["m"]
    p.write_text(json.dumps(d), encoding="utf-8")
    raises(KeyError, lambda: r3.prior_milestones(cp["rd1"], cp["rd2"]), "a recorded decision without its milestone is refused, never defaulted to zero")
    p1_ = cp["rd1"] / "sessions" / "rd1" / "rule.json"
    d = json.loads(p1_.read_text(encoding="utf-8"))
    del d["m_T"]
    p1_.write_text(json.dumps(d), encoding="utf-8")
    raises(KeyError, lambda: r3.prior_milestones(cp["rd1"], cp["rd2"]), "rd1's record without an arm's milestone is refused")
    shutil.rmtree(cp["t"], ignore_errors=True)
    # the registered anchors of the increments and of rd2's record
    op = ses3.open_protocol3(chain["rd1"], chain["rd2"], chain["inc1"], chain["inc2"], expect1=chain["expect1"], expect2=dict(chain["expect2"], files=chain["expect2"].get("files", 0) + 1),
                             check_overlay=False, live_pins=lambda: live_pins_of(chain), floor_min=FLOOR_MIN)
    check(not op["ok"] and any(x.startswith("R1 (rd2): the increment's files") for x in op["problems"]), f"a wrong registered file count: {op['problems'][:2]}")
    op = ses3.open_protocol3(chain["rd1"], chain["rd2"], chain["inc1"], chain["inc2"], expect1=chain["expect1"], expect2=dict(chain["expect2"], increment_manifest_sha256="0" * 64),
                             check_overlay=False, live_pins=lambda: live_pins_of(chain), floor_min=FLOOR_MIN)
    check(not op["ok"] and any("manifest" in x for x in op["problems"]), "a wrong registered increment manifest")
    f = r3.rd2_archive_facts(chain["rd1"], chain["rd2"], chain["lines"], dict(chain["expect2"], outcome="PROGRESS_CLEAR" if chain["rd2_outcome"] != "PROGRESS_CLEAR" else "NONE", m=9), with_audit=False)
    check(not f["ok"] and any("recorded decision" in x for x in f["problems"]), f"rd2's recorded decision is checked against the registered one: {f['problems']}")
    f = r3.rd2_archive_facts(chain["rd1"], chain["rd2"], chain["lines"], dict(chain["expect2"], returns=1, exploration_ticks=1), with_audit=False)
    check(not f["ok"] and any("ledger totals" in x for x in f["problems"]), "rd2's ledger totals are checked")
    # the real registered facts carry all the anchors
    for k in ("files", "bytes", "increment_manifest_sha256", "outcome", "m", "returns", "exploration_ticks"):
        check(k in r3.RD2_FACTS, f"RD2_FACTS carries {k}")
    return {}


def unit_audit3_edge_cases() -> Dict[str, Any]:
    n1, n2, n3 = 30, 30, 30
    a = synth_archive3("ed", n1, n2, n3)
    t = tmpdir("m8r3ed_")
    a.write_files(t / "a", {"checkpoint_seq": 1})

    def load() -> s3.Archive3:
        b, _m = s3.Archive3.read_dir(t / "a")
        return b

    b = load()
    ing = next(e for e in b.events if e["ev"] == "ingest" and e["burst"] >= 0)
    ing["burst"] = 10 ** 6
    r = s3.audit3(b, "lines")
    check(not r["ok"] and any("rebuild failed" in x for x in r["problems"]), f"a ledger naming a burst that does not exist is an audit failure, not an exception: {r['problems'][:2]}")
    b = load()
    k = next(i for i, e in enumerate(b.events) if e["ev"] == "session" and e["name"] == "rd3")
    j = next(i for i, e in enumerate(b.events) if i > k and e["ev"] == "dispatch")
    b.events[j]["it"] = n1 + n2 - 1 - 0
    r = s3.audit3(b, "lines")
    check(not r["ok"], "a dispatch after rd3's session event below its first iteration is detected")
    check(any("lies before the first iteration" in x or "reused" in x or "rebuild failed" in x for x in r["problems"]), f"named: {r['problems'][:3]}")
    shutil.rmtree(t, ignore_errors=True)
    return {}


def unit_selection_draws_independent() -> Dict[str, Any]:
    """Archive3.select against an independent re-implementation of the v2 draw (keyed uniforms, level weights 1 / (1 + top - level), the archive's own cell weights), per part."""
    a = synth_archive3("ind", 40, 50, 50)
    nxt = 140
    levels = a.eligible_levels()
    top = max(levels)
    order = sorted(levels)
    wl = [1.0 / (1.0 + top - lv) for lv in order]
    n_checked = 0
    for it, draw in [(i, a.draw_id_rd3) for i in range(nxt, nxt + 60)] + [(i, a.draw_id_rd2) for i in range(60, 90)]:
        u1, u2 = mx.uniforms(mx.select_key(draw, it))
        r, acc, level = u1 * sum(wl), 0.0, order[-1]
        for lv, w in zip(order, wl):
            acc += w
            if r < acc:
                level = lv
                break
        cells = levels[level]
        ws = a.cell_weights(cells)
        r, acc, want = u2 * sum(ws), 0.0, cells[-1]
        for c, w in zip(cells, ws):
            acc += w
            if r < acc:
                want = c
                break
        check(a.select(it).id == want.id, f"iteration {it}: select {a.select(it).id}, the independent draw under {draw} says {want.id}")
        n_checked += 1
    return {"checked": n_checked}


# -- the registry and the CLI ----------------------------------------------------------------------------------------------------------------------------


def _earlier(name: str, table: Sequence[Tuple[str, Callable[[], Dict[str, Any]]]], prefix: str) -> Tuple[str, Callable[[], Dict[str, Any]]]:
    fn = dict(table)[name]
    return f"{prefix}:{name}", fn


TESTS: List[Tuple[str, Callable[[], Dict[str, Any]]]] = [
    ("rd3_contract", unit_rd3_contract), ("archive3_draw_switch", unit_archive3_draw_switch), ("begin_rd3_and_persistence", unit_begin_rd3_and_persistence),
    ("ledger_rebuild3", unit_ledger_rebuild3), ("rule3_module", unit_rule3_module), ("identity_samples3", unit_identity_samples3), ("new_diagnostics", unit_new_diagnostics),
    ("report3_on_real_rd2", unit_report3_on_real_rd2), ("resume_two_level_synthetic", unit_resume_two_level_synthetic), ("session3_small_run", unit_session3_small_run),
    ("session3_refuses_unbegun_archive", unit_session3_refuses_unbegun_archive), ("session3_outcomes_and_stops", unit_session3_outcomes_and_stops),
    ("session3_milestones_and_stops", unit_session3_milestones_and_stops), ("session3_determinism", unit_session3_determinism), ("write_guard_two_roots", unit_write_guard_two_roots),
    ("budget_projection3", unit_budget_projection3), ("approval_isolated3", unit_approval_isolated3), ("import_isolation3", unit_import_isolation3),
    ("source_guard3", unit_source_guard3), ("wall_top_label_suppressed", unit_wall_top_label_suppressed), ("session3_unverified_claims", unit_session3_unverified_claims),
    ("strict_records", unit_strict_records), ("audit3_edge_cases", unit_audit3_edge_cases), ("selection_draws_independent", unit_selection_draws_independent), ("tracked_files_unchanged3", unit_tracked_files_unchanged3), ("snapshot_tool3", unit_snapshot_tool3),
    ("open_protocol_real_trees", unit_open_protocol_real_trees), ("cmd_run3_with_fake_game", unit_cmd_run3_with_fake_game),
] + [_earlier(n, t1.TESTS, "rd1") for n in RD1_PURE] + [_earlier(n, t2.TESTS, "rd2") for n in RD2_PURE]


def _cleanup() -> None:
    while _TMP:
        shutil.rmtree(_TMP.pop(), ignore_errors=True)


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
            results[name] = {"ok": False, "s": round(time.perf_counter() - t0, 1), "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-2500:]}
            failed.append(name)
            print(f"FAIL {name}: {type(exc).__name__}: {exc}\n{traceback.format_exc()[-1800:]}", flush=True)
        finally:
            _cleanup()
    for rec in _CHAIN.values():
        shutil.rmtree(rec["t"], ignore_errors=True)
    for rec in getattr(t2, "_SYN", {}).values():
        shutil.rmtree(rec["t"], ignore_errors=True)
    total = passed + len(failed)
    if out is not None:
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "m8_rd3_unit.json").write_text(json.dumps({"passed": passed, "total": total, "failed": failed, "wall_s": round(time.perf_counter() - t_all, 1), "results": results}, indent=1,
                                                         default=str) + "\n", encoding="utf-8")
    print(f"{passed} / {total} passed (unit); wall {time.perf_counter() - t_all:.0f} s")
    return 0 if not failed else 1


# -- the production-count synthetic end-to-end run ---------------------------------------------------------------------------------------------------------


def e2e(out: Path, small: bool = False, world: str = "hard", use_async: bool = False) -> int:
    """The rd3 session at the registered counts (6,000,000 exploration ticks valid from 2,000,000, five workers, the registered caps and memory checks) against a synthetic chain (a
    synthetic rd1 tree, a synthetic rd2 tree built on it by rd2's own engine, both with their verified increments) and the stub: the two-level resume (R1-R6), the closing overlay of
    rd2's archive, P1 against the archive's pin, the open and close identity replays, the unchanged v2 selection under rd3's draws, the replacement and the descent-doom tree, the rule,
    the close audit of the three-part ledger, the prefix chain and verify-run. The default engine is the lock-step pool and the virtual clock: the run is a pure function of its
    configuration. `use_async` runs the real worker processes (invariants only; a measurement run, not part of the suite). The world is synthetic: the outcome says nothing about Mario."""
    import m8_rd_session as ses1

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    problems: List[str] = []
    t0 = time.perf_counter()
    chain = build_chain(world, rd1_caps=(60000, 40000) if small else (600000, 480000), rd2_ticks=100000 if small else 1_500_000, cache=False, n_workers=5)
    print(f"[e2e] synthetic chain built in {time.perf_counter() - t0:.0f} s: rd1 {chain['expect1']['cells']} cells, rd2 {chain['expect2']['cells']} cells, rd2 outcome {chain['rd2_outcome']}", flush=True)
    root3 = out / "rd3"
    if root3.exists():
        shutil.rmtree(root3)
    kw: Dict[str, Any] = dict(checkpoint_every_s=20.0 if not use_async else 30.0)
    if small:
        kw.update(arm_tick_cap=200000, arm_caps={"T": 200000}, min_arm_ticks=60000, p1_tick_cap=70000)
    cfg = ses3.run_config(root=root3, **kw)
    op, a3 = open_chain3(chain, root3)
    cfg.session_dir.mkdir(parents=True)
    mw.ProvenanceGuard.install()
    mw.ProvenanceGuard.violations.clear()
    w2.WriteGuard.install([chain["rd1"], chain["rd2"]])
    logs: List[str] = []

    def log(s: str) -> None:
        line = f"[e2e {time.strftime('%H:%M:%S')}] {s}"
        logs.append(line)
        print(line, flush=True)

    clock = FakeClock()
    env = sync_env(world, [chain["rd1"], chain["rd2"]], clock, pins=chain["pins"], log=log)
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
    sess = run3.Session3(cfg, env, archive=a3, archive_pin=op["facts2"]["pin_tick0"], base_info={"overlay_sha256": op["overlay"]["sha256"]}, rd1_root=chain["rd1"], rd2_root=chain["rd2"],
                         lines_sha256=chain["lines"], ckpt_seq=int(op["facts2"]["rd2_checkpoint_seq"]) + 1)
    if not use_async:
        sess.pool = SyncPool(env, cfg, clock)
    res = run3.run_all3(sess, immutability=lambda: both_immutability(chain))
    wall = time.perf_counter() - t1_
    mem = sampler.stop() if sampler is not None else None
    w2.WriteGuard.clear()
    rule, close = res["rule"], res["close"]
    vr = rpt3.verify_run3(root3, chain["rd2"], chain["rd1"], "rd3")
    report = rpt3.full_report3(root3, chain["rd2"], chain["rd1"], "rd3")
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
    if not both_immutability(chain)["ok"]:
        problems.append("a synthetic earlier tree changed")
    ver = json.loads((root3 / "sessions" / "rd3" / "verification.json").read_text(encoding="utf-8"))
    io_ = sess.open_identity_record
    if not (io_.get("ok") and io_.get("cells") == 16 and ver["identity"].get("verified") == ver["identity"].get("cells") == 16):
        problems.append(f"identity replays: open {io_.get('verified')}/{io_.get('cells')}, close {ver['identity']}")
    if sess.first_iteration != chain["expect2"]["dispatch_iterations"][1] + 1:
        problems.append("iterations do not continue from rd2's last")
    v = sess.verified or {"m": 0, "max_targets": 0}
    prior = r3.prior_milestones(chain["rd1"], chain["rd2"])
    again = rule3.apply(invalid=[], incomplete=[], m=v["m"], t=v["max_targets"], prior=prior, **rule["extra"]["rule_inputs"])
    for k in ("outcome", "m", "max_targets_verified", "any_stop"):
        if again[k] != rule[k]:
            problems.append(f"the recorded {k} {rule[k]} differs from the rule applied to the verified m and t {again[k]}")
    peak_mb = None
    try:
        import m7u_gate as g1b

        peak_mb = g1b.private_mb()
    except Exception:  # noqa: BLE001
        pass
    summary = {"small": small, "world": world, "engine": "async real worker processes" if use_async else "lock-step pool, virtual clock", "wall_s": round(wall, 1),
               "outcome": rule["outcome"], "m": rule["m"], "max_targets": rule["max_targets_verified"], "progress_basis": rule["progress_basis"], "stops": rule["any_stop"],
               "ticks": sess.ledgers["T"].ticks, "exploration_wall_s_real_or_virtual": sess.arm_records["T"]["wall_s"], "stop": sess.arm_records["T"]["stop"],
               "cells_open": len(a3.cells) if False else chain["expect2"]["cells"], "cells_close": len(sess.archive.cells), "bursts": len(sess.archive.bursts),
               "candidates": len(sess.ledgers["T"].candidates), "phase_wall_s": sess.clock.to_json()["phase_wall_s"], "peak_main_private_mb": sess.clock.peak_mb,
               "main_private_mb_at_end": peak_mb, "memory_tree_peak": (mem or {}).get("peak"), "verify_run": vr["ok"], "replay_ticks": sess.ticks["replays"],
               "open_identity": io_, "identity_close": ver["identity"], "audit": close.get("audit"), "prefix_chain": {k: close.get("prefix_chain", {}).get(k) for k in ("ok", "problems")},
               "archive_stats": sess.archive.stats(), "diag2": {k: (len(x) if isinstance(x, list) else x) for k, x in sess.archive.diag2.items()}, "lifecycle_failures": sess.lifecycle_failures,
               "rule_inputs": rule["extra"]["rule_inputs"], "overlay_open": op["overlay"]["counts"], "overlay_close": close.get("archive", {}).get("overlay_close"),
               "wall_top_cells": report["new"]["rd3"]["wall_top"]["cells"], "dilution": rule["dilution"]["verdict"], "problems": problems}
    (out / "e2e.json").write_text(json.dumps(summary, indent=1, default=str) + "\n", encoding="utf-8")
    (out / "e2e.log").write_text("\n".join(logs) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=1, default=str))
    shutil.rmtree(chain["t"], ignore_errors=True)
    if not problems:
        shutil.rmtree(root3, ignore_errors=True)               # the synthetic rd3 tree is large and says nothing about Mario; e2e.json and e2e.log are the record
    print("E2E PASS" if not problems else f"E2E FAIL: {problems}")
    return 0 if not problems else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("unit", "e2e", "list"))
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--only", default=None)
    ap.add_argument("--small", action="store_true")
    ap.add_argument("--async", dest="use_async", action="store_true")
    ap.add_argument("--world", default="hard", choices=sorted(stub.WORLDS))
    a = ap.parse_args(argv)
    if a.cmd == "list":
        for name, _fn in TESTS:
            print(name)
        return 0
    if a.cmd == "unit":
        return run_unit(a.only.split(",") if a.only else None, a.out or Path(tempfile.mkdtemp(prefix="m8_unit3_")))
    return e2e(a.out or Path(tempfile.mkdtemp(prefix="m8_e2e3_")), small=a.small, world=a.world, use_async=a.use_async)


if __name__ == "__main__":
    sys.exit(main())
