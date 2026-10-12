#!/usr/bin/env python3
"""M8-sd2 offline tests: zero native ticks. No BattleShip launch, no replay on a real process, no training.

    python -B rl/m8_sd2_tests.py unit [--out DIR] [--only NAME[,NAME]]
    python -B rl/m8_sd2_tests.py e2e  [--out DIR] [--small] [--world W]      # the production-count synthetic end-to-end run of the five-level resume; its last line carries the digest
    python -B rl/m8_sd2_tests.py list

DETERMINISM (rd4's decision 10, kept). No test anywhere in this suite or in the preflight is non-deterministic. The session-level tests run the REAL session engine (Session6 over Session5,
Session4, Session3, Session2 and Session, the archive, the claims, the verification, the close checks, the rule) against the synthetic stub world (rl/m8_rd_stub.py) through rd3's in-process
lock-step worker pool and virtual clock: a run is a pure function of its configuration (tested: two runs agree on every ledger event, cell, word and decision). No test starts a real
process. The tests that read the closed real trees, git or D: are GATES: they assert facts that are fixed once the trees are closed and the work is staged.

The synthetic chain adds a synthetic sd1 run (sd1's own engine, CHAIN_SD1 ticks in the easy world, found by experiment on 2026-10-12: it verifies a clear at 812 against the synthetic
record 878) on sd1's four-tree chain, so sd2's open protocol, both bounds, the inherited descriptive rule and the six-part audit are exercised end to end.

The tests of rd1, rd2, rd3, rd4 and sd1 that run here (RD1_PURE, RD2_PURE, RD3_PURE, RD4_PURE, SD1_PURE) are the pure ones, by explicit lists; their asynchronous tests are never run.

Light top-level imports only (spawned workers re-import this script).
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import copy
import gzip
import hashlib
import importlib.util
import inspect
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

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
import m8_rd_tests as t1  # noqa: E402
import m8_rd_worker as mw  # noqa: E402
import m8_rd2_rule as rule2  # noqa: E402
import m8_rd2_tests as t2  # noqa: E402
import m8_rd2_worker as w2  # noqa: E402
import m8_rd3_tests as t3  # noqa: E402
import m8_rd4_select as s4  # noqa: E402
import m8_rd4_tests as t4  # noqa: E402
import m8_sd1_artifacts as art5  # noqa: E402
import m8_sd1_claims as cl5  # noqa: E402
import m8_sd1_resume as r5  # noqa: E402
import m8_sd1_rule as rule5  # noqa: E402
import m8_sd1_select as s5  # noqa: E402
import m8_sd1_session as ses5  # noqa: E402
import m8_sd1_tests as t5  # noqa: E402
import m8_sd2_artifacts as art  # noqa: E402
import m8_sd2_claims as cl6  # noqa: E402
import m8_sd2_report as rpt6  # noqa: E402
import m8_sd2_resume as r6  # noqa: E402
import m8_sd2_rule as rule6  # noqa: E402
import m8_sd2_run as run6  # noqa: E402
import m8_sd2_select as s6  # noqa: E402
import m8_sd2_session as ses6  # noqa: E402
import m9_artifacts as A  # noqa: E402
from m8_rd_tests import Failure, check, raises, tmpdir  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
RL_DIR = Path(__file__).resolve().parent
TOOLS_DIR = REPO_ROOT / "tools" / "m8_sd2"
SD1_TOOLS_DIR = REPO_ROOT / "tools" / "m8_sd1"
RD1_REAL = REPO_ROOT / "runs" / "m8_rd"
RD2_REAL = REPO_ROOT / "runs" / "m8_rd_rd2"
RD3_REAL = REPO_ROOT / "runs" / "m8_rd_rd3"
RD4_REAL = REPO_ROOT / "runs" / "m8_rd_rd4"
SD1_REAL = REPO_ROOT / "runs" / "m8_rd_sd1"
REAL_ROOTS = (RD1_REAL, RD2_REAL, RD3_REAL, RD4_REAL, SD1_REAL)
NEW_MODULES = ("m8_sd2_artifacts", "m8_sd2_select", "m8_sd2_rule", "m8_sd2_claims", "m8_sd2_resume", "m8_sd2_report", "m8_sd2_run", "m8_sd2_session", "m8_sd2_snapshot")
PYTHON_TOOLS = ("wait_session.py", "write_approval.py", "three_passes.py", "check_launch.py", "copy_launch_evidence.py", "post_run_checks.py", "machine_sampler.py")
PS_TOOLS = ("launch_detached.ps1", "independent_increment_check.ps1")
SESSION_TOOLS = ("wait_session.py", "write_approval.py", "three_passes.py", "check_launch.py", "copy_launch_evidence.py", "post_run_checks.py")       # the tools that take --session
EARLIER_FILES = t5.EARLIER_FILES + ("m8_sd1_artifacts", "m8_sd1_select", "m8_sd1_rule", "m8_sd1_claims", "m8_sd1_resume", "m8_sd1_report", "m8_sd1_run", "m8_sd1_session", "m8_sd1_snapshot",
                                    "m8_sd1_tests")
FLOOR_MIN = t5.FLOOR_MIN
FakeClock, SyncPool, sync_env = t5.FakeClock, t5.SyncPool, t5.sync_env
RD1_PURE, RD2_PURE, RD3_PURE, RD4_PURE = t5.RD1_PURE, t5.RD2_PURE, t5.RD3_PURE, t5.RD4_PURE
SD1_PURE = ("select_v4_formula_and_digest", "record_bound_e7", "archive5_draw_and_mode_switch", "begin_sd1_and_persistence", "ledger_rebuild5", "claims5_pool_and_plan", "rule5_module",
            "artifacts5_stamping")
# the synthetic chain: sd1's chain (rd1 to rd4 by their own engines) plus a synthetic sd1 run that verifies a clear (found by experiment on 2026-10-12, then fixed here)
CHAIN_WORLD = "easy"
CHAIN_SD1 = 120000
OPEN_UTC = "2026-10-12T00:00:00Z"
REAL_TREES = all((p / "archive" / "manifest.sha256").is_file() for p in REAL_ROOTS)

_CHAIN6: Dict[str, Any] = {}
_TMP: List[Path] = []


def real_record_reference() -> Dict[str, Any]:
    return dict(r6.RECORD_REFERENCE6)


def syn_record_reference(t: int = 1000, digest: str = "a" * 64, session: str = "syn", cid: int = 1) -> Dict[str, Any]:
    return s6.record_reference_block(completion_input_tick=t, completion_time_passed=t - 1, native_action_digest=digest, words=t, cid=cid, iteration=1, kind="clear", session=session, source="synthetic")


# -- synthetic builders: a chain rd1 -> rd2 -> rd3 -> rd4 -> sd1 (built by the real engines) ------------------------------------------------------------


def tree_expect5(root5: Path) -> Dict[str, Any]:
    """The registered-facts dictionary of a synthetic sd1 tree (what SD1_FACTS is for the real one), the inherited record facts included."""
    a, meta = s6.Archive6.read_dir(root5 / "archive")
    prev = json.loads((root5 / "archive.prev" / "archive_meta.json").read_text(encoding="utf-8"))
    its = sorted(e["it"] for e in a.events if e["ev"] == "dispatch")
    sd = root5 / "sessions" / "sd1"
    rule = json.loads((sd / "rule.json").read_text(encoding="utf-8"))
    ev1 = next(e for e in a.events if e["ev"] == "session" and e.get("name") == "sd1")
    return {"cells": len(a.cells), "bursts": len(a.bursts), "events": len(a.events), "checkpoint_seq": meta["checkpoint_seq"], "previous_checkpoint_seq": prev["checkpoint_seq"],
            "dispatch_iterations": (its[0], its[-1]), "contiguous": False, "first_rd2_iteration": a.rd2_first_iteration, "first_rd3_iteration": a.rd3_first_iteration,
            "first_rd4_iteration": a.rd4_first_iteration, "first_sd1_iteration": a.sd1_first_iteration, "first_sd2_iteration": its[-1] + 1, "outcome": rule["outcome"],
            "line_status": rule["line"]["status"], "session_counts": rule["line"]["session_counts"], "returns": meta["ledger_T"]["jobs"], "exploration_ticks": meta["ledger_T"]["ticks"],
            "first_new_cell": meta["first_new_cell"], "sd1_cells_created": len(a.cells) - int(meta["first_new_cell"]), "sd1_record_reference": dict(ev1["record_reference"]),
            "sd1_margin": int(ev1["margin"]), "sd1_session_digest": ev1["digest"], "archive_created_utc": meta["created_utc"],
            "close_record_sha256": mw.sha256_file(sd / "close.json"), "rule_record_sha256": mw.sha256_file(sd / "rule.json"), "verification_record_sha256": mw.sha256_file(sd / "verification.json"),
            "inherited_record": r6.inherited_record_facts6(root5, a)}          # the forced crossing of the synthetic rd4 skips iteration numbers: increasing, not contiguous


def all_immutability6(cp: Mapping[str, Any]) -> Dict[str, Any]:
    parts = {k: rs.rd1_immutability(cp[k], cp[f"inc{i}"]) for i, k in enumerate(("rd1", "rd2", "rd3", "rd4", "sd1"), 1)}
    return {"ok": all(v["ok"] for v in parts.values()), "problems": [f"{k}: {p}" for k, v in parts.items() for p in v["problems"]], **parts}


def build_chain6(world: str = CHAIN_WORLD, *, sd1_ticks: int = CHAIN_SD1, cache: bool = True, n_workers: int = 3, flags: Optional[Mapping[str, Any]] = None, exe_sha: str = "e" * 64,
                 runtime_files: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """sd1's synthetic four-tree chain plus a synthetic sd1 tree on it (sd1's own engine through the lock-step pool), with its verified increment: the chain is a pure function of its
    parameters, and its sd1 verified a clear below the synthetic record (the record sd2 searches below)."""
    key = f"{world}|{sd1_ticks}|{n_workers}|{bool(flags)}|{exe_sha}"
    if cache and key in _CHAIN6:
        return _CHAIN6[key]
    import runs_backup as rb

    base = t5.build_chain5(world, flags=flags, exe_sha=exe_sha, runtime_files=runtime_files, cache=cache, n_workers=n_workers)
    out, sess, root5, cp = t5.run5_small(base, arm_tick_cap=sd1_ticks, min_arm_ticks=max(1000, sd1_ticks // 3), n_workers=n_workers)
    if cp["t"] in t5._TMP:
        t5._TMP.remove(cp["t"])                      # sd1's runner would delete this directory after the test: a cached chain is removed by this module's own cleanup
    r = out["rule"]
    check(r["outcome"] in ("PROGRESS", "RECORD_BELOW_MARGIN") and not r["invalid"] and not r["incomplete"] and r["best_verified"],
          f"the synthetic sd1 session must verify a clear below the synthetic record: {r['outcome']} {r['best_verified']} {r['invalid']} {r['incomplete']}")
    inc5 = cp["t"] / "inc5"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = rb.cmd_backup(root5, inc5, 2)
    check(rc == 0 and (inc5 / "verification.json").is_file(), f"the synthetic sd1 increment: {buf.getvalue()[-300:]}")
    chain = dict(cp, sd1=root5, inc5=inc5, expect5=tree_expect5(root5), sd1_outcome=r["outcome"], sd1_best=r["best_verified"]["completion_input_tick"], world=world)
    if cache:
        _CHAIN6[key] = chain
    return chain


def copy_chain6(chain: Mapping[str, Any]) -> Dict[str, Any]:
    """A private copy of a chain (mtimes kept, so every copy still equals its increment)."""
    import runs_backup as rb

    t = tmpdir("m8sd2cp_")
    _TMP.append(t)
    names = ("rd1", "inc1", "rd2", "inc2", "rd3", "inc3", "rd4", "inc4", "sd1", "inc5")
    for name in names:
        shutil.copytree(chain[name], t / name)
    for inc_key, dst in (("inc1", "rd1"), ("inc2", "rd2"), ("inc3", "rd3"), ("inc4", "rd4"), ("inc5", "sd1")):
        man = rb.read_manifest(chain[inc_key])
        for rel, (_sha, _size, mt) in man.items():
            os.utime(t / dst / rel.replace("/", os.sep), ns=(mt, mt))
    return dict(chain, t=t, **{n: t / n for n in names})


def small_cfg6(root: Path, **kw: Any) -> Any:
    base = dict(n_workers=3, arm_tick_cap=12000, arm_caps={"T": 12000}, min_arm_ticks=4000, p1_tick_cap=30000, replay_tick_cap=300000,
                wall_caps_s={"p1": 90.0, "T": 300.0, "C": 0.0, "verify": 300.0}, global_cap_s=1200.0, checkpoint_every_s=4.0, verify_threads=2, identity_k=6)
    base.update(kw)
    if "arm_tick_cap" in kw and "arm_caps" not in kw:
        base["arm_caps"] = {"T": kw["arm_tick_cap"]}
    return ses6.run_config(root=root, **base)


def open6(cp: Mapping[str, Any], *, expect5: Optional[Mapping[str, Any]] = None, live: Optional[Callable[[], Mapping[str, Any]]] = None, margin: int = rule6.MARGIN, **kw: Any) -> Dict[str, Any]:
    e5 = expect5 if expect5 is not None else cp["expect5"]
    rr = kw.pop("record_reference", e5["inherited_record"]["best_verified"])
    return ses6.open_protocol6(cp["rd1"], cp["rd2"], cp["rd3"], cp["rd4"], cp["sd1"], cp["inc1"], cp["inc2"], cp["inc3"], cp["inc4"], cp["inc5"], expect1=cp["expect1"], expect2=cp["expect2"],
                               expect3=cp["expect3"], expect4=cp["expect4"], expect5=e5, check_overlay=False, live_pins=live or (lambda: t3.live_pins_of(cp)), floor_min=FLOOR_MIN, margin=margin,
                               record_reference=rr, previous_record_reference=e5["sd1_record_reference"], previous_margin=e5["sd1_margin"], **kw)


def open_chain6(cp: Mapping[str, Any], root6: Path, *, margin: int = rule6.MARGIN, utc: str = OPEN_UTC) -> Tuple[Dict[str, Any], s6.Archive6]:
    """The sd2 open protocol (R1-R5, five levels) and the materialisation (R6) on a private copy of a chain."""
    op = open6(cp, margin=margin)
    check(op["ok"], f"the sd2 open protocol on a synthetic chain: {op['problems']}")
    rr = cp["expect5"]["inherited_record"]["best_verified"]
    a6 = r6.materialise6(cp["sd1"], root6, facts=op["facts5"], overlay=op["overlay"], lines_sha256=cp["lines"],
                         meta_extra={"pins": cp["pins"], "pin_tick0": op["facts5"]["pin_tick0"], "ticks": {}, "ledger_T": {}},
                         increment_manifest_sha256=op["R1_sd1_immutability"]["manifest_sha256"], utc=utc, margin=margin, record_reference=rr, floor_min=FLOOR_MIN)
    return op, a6


def run6_small(chain: Mapping[str, Any], *, world: Optional[str] = None, inject: Optional[Mapping[str, Any]] = None, env_kw: Optional[Mapping[str, Any]] = None,
               immutability: Optional[Callable[[], Mapping[str, Any]]] = None, env_kw_factory: Optional[Callable[[Mapping[str, Any], FakeClock], Mapping[str, Any]]] = None,
               clock_step: float = 0.25, session_cls: Any = None, pool_factory: Optional[Callable[[Any, Any, FakeClock], SyncPool]] = None, margin: int = rule6.MARGIN,
               record_candidate: Optional[Mapping[str, Any]] = None, **cfg_kw: Any) -> Tuple[Dict[str, Any], Any, Path, Dict[str, Any]]:
    """The sd2 session (open protocol, materialise, Session6, run_all6) against a private copy of a synthetic chain and the stub, through the lock-step pool."""
    cp = copy_chain6(chain)
    root6 = cp["t"] / "sd2"
    cfg = small_cfg6(root6, **cfg_kw)
    op, a6 = open_chain6(cp, root6, margin=margin)
    cfg.session_dir.mkdir(parents=True)
    mw.ProvenanceGuard.install()
    mw.ProvenanceGuard.violations.clear()
    roots = [cp["rd1"], cp["rd2"], cp["rd3"], cp["rd4"], cp["sd1"]]
    w2.WriteGuard.install(roots)
    try:
        clock = FakeClock(clock_step)
        env = sync_env(world or cp["world"], roots, clock, inject, pins=cp["pins"], **dict(env_kw or {}), **dict(env_kw_factory(cp, clock) if env_kw_factory else {}))
        sess = (session_cls or run6.Session6)(cfg, env, archive=a6, archive_pin=op["facts5"]["pin_tick0"], base_info={"open_overlay_sha256": op["overlay"]["v4"]["sha256"]}, rd1_root=cp["rd1"],
                                              rd2_root=cp["rd2"], rd3_root=cp["rd3"], rd4_root=cp["rd4"], sd1_root=cp["sd1"], lines_sha256=cp["lines"], ckpt_seq=int(op["facts5"]["sd1_checkpoint_seq"]) + 1,
                                              archive_created_utc=OPEN_UTC, record_candidate=record_candidate if record_candidate is not None else op["record_candidate"],
                                              inherited=op["inherited"], sd1_line=op["facts5"]["sd1_line"])
        sess.pool = pool_factory(env, cfg, clock) if pool_factory else SyncPool(env, cfg, clock)
        out = run6.run_all6(sess, immutability=immutability or (lambda: all_immutability6(cp)))
    finally:
        w2.WriteGuard.clear()
    return out, sess, root6, cp


host_masked_sha256 = t5.host_masked_sha256           # the host frame of every end vector masked, nothing else (sd1's fix of the e2e digest)


def signature6(root6: Path) -> Dict[str, Any]:
    """What must be identical between two runs of the same configuration, in one process or in two: the archive's data files (the cells and the burst index with the host frame of every
    end vector masked, the words and the ledger raw; not its meta, which carries timestamps), the decision, the verification's order, both overlays and both session digests."""
    a = root6 / "archive"
    rule = json.loads((root6 / "sessions" / "sd2" / "rule.json").read_text(encoding="utf-8"))
    ver_p = root6 / "sessions" / "sd2" / "verification.json"
    ver = json.loads(ver_p.read_text(encoding="utf-8")) if ver_p.is_file() else {}
    arm = ver.get("arm") or {}
    ov = json.loads((root6 / "derived" / "open_overlay.json").read_text(encoding="utf-8"))
    events = [json.loads(ln) for ln in (a / "events.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    ev2 = next(e for e in events if e["ev"] == "session" and e.get("name") == "sd2")
    ev1 = next(e for e in events if e["ev"] == "session" and e.get("name") == "sd1")
    best = rule.get("best_verified") or {}
    return {"files": {"cells.jsonl": host_masked_sha256(a / "cells.jsonl"), "bursts.bin": mw.sha256_file(a / "bursts.bin"),
                      "bursts.idx.jsonl": host_masked_sha256(a / "bursts.idx.jsonl"), "events.jsonl": mw.sha256_file(a / "events.jsonl")},
            "rule": {k: rule[k] for k in ("outcome", "flags", "any_stop", "progress_bar", "margin")}, "best": {k: best.get(k) for k in ("cid", "completion_input_tick", "completion_time_passed", "native_action_digest")},
            "verified_cids": [v["cid"] for v in rule.get("verified_clears") or []], "tiers_reached": (rule.get("tiers") or {}).get("reached"), "line": rule["line"]["status"],
            "verification": {k: arm.get(k) for k in ("pool", "replays", "replay_order", "remaining", "remaining_progress", "closed", "max_targets")},
            "inherited": {k: (ver.get("inherited_descriptive") or {}).get(k) for k in ("count", "replayed", "exact")},
            "sd2_session_event_digest": ev2["digest"], "sd1_session_event_digest": ev1["digest"], "record_reference": ev2["record_reference"], "previous_record_reference": ev1["record_reference"],
            "open_overlay_sha256": ov["open_overlay"]["sha256"], "sd1_closing_overlay_sha256": ov["sd1_closing_overlay"]["sha256"]}


def synth_archive6(seed: str = "s6", n1: int = 40, n2: int = 50, n3: int = 50, n4: int = 50, n5: int = 50, n6: int = 50, floor_min: float = -2100.0, lines: str = "lines", t_rec_sd1: int = 200,
                   t_rec: int = 150, margin: int = 24) -> s6.Archive6:
    """A six-part archive from keyed random jobs: rd1's part under v1, rd2's and rd3's under v2, rd4's under v3, sd1's under v4 at the first reference, sd2's under v4 at the second."""
    rng = t2.Krng(seed)
    a = s6.Archive6("syn6", floor_min=floor_min)
    a.init_cell0(t1.key(0, 0), t1.mk_end(), bytes(32), bytes([1]) * 32)
    t2.drive2(a, rng, n1, 0, v2=False)
    a.begin_v2(n1, lines)
    t2.drive2(a, rng, n2, n1, v2=True)
    a.begin_rd3(n1 + n2, lines)
    t2.drive2(a, rng, n3, n1 + n2, v2=True)
    a.begin_rd4(n1 + n2 + n3, lines)
    t2.drive2(a, rng, n4, n1 + n2 + n3, v2=True)
    a.begin_sd1(n1 + n2 + n3 + n4, lines, syn_record_reference(t_rec_sd1, session="rd4", cid=7), margin)
    t2.drive2(a, rng, n5, n1 + n2 + n3 + n4, v2=True)
    a.begin_sd2(n1 + n2 + n3 + n4 + n5, lines, syn_record_reference(t_rec, session="sd1", cid=9), margin)
    t2.drive2(a, rng, n6, n1 + n2 + n3 + n4 + n5, v2=True)
    return a


def fresh6(aid: str = "t6", floor_min: float = -2550.0) -> s6.Archive6:
    a = s6.Archive6(aid, floor_min=floor_min)
    a.init_cell0(t1.key(0, 0), t1.mk_end(), bytes(32), bytes([1]) * 32)
    return a


def archive6_for_prob(cells: Sequence[Tuple[Any, ...]], *, with_sd2: bool = True, t_rec_sd1: int = 1000, t_rec: int = 900, margin: int = 24) -> s6.Archive6:
    """A small archive in mode 2 (rd2, rd3, rd4 and sd1 begun, sd2 begun when asked) holding the given (key, L, y, seen, chosen) cells; sd1 begins at iteration 8, sd2 at 9."""
    a = fresh6("pb", -2550.0)
    for k, L, y, seen, chosen in cells:
        t2.add_cell2(a, k, L, y=y, seen=seen, chosen=chosen)
    a.begin_v2(5, "L")
    a.begin_rd3(6, "L")
    a.begin_rd4(7, "L")
    a.begin_sd1(8, "L", syn_record_reference(t_rec_sd1, session="rd4", cid=7), margin)
    if with_sd2:
        a.begin_sd2(9, "L", syn_record_reference(t_rec, session="sd1", cid=9), margin)
    return a


def real_lines() -> str:
    meta = json.loads((SD1_REAL / "archive" / "archive_meta.json").read_text(encoding="utf-8"))
    return str(meta["pin_tick0"]["lines"])


def real_floor_min() -> float:
    return float(json.loads((SD1_REAL / "archive" / "archive_meta.json").read_text(encoding="utf-8"))["floor_min"])




# -- the contract and the selection ---------------------------------------------------------------------------------------------------------------------


def unit_sd2_contract() -> Dict[str, Any]:
    import m7q_status_table as st

    check(s6.DRAW_SUFFIX == "_sd2" and s6.DRAW_SUFFIX_SD1 == "_sd1" and s6.DRAW_SUFFIX_RD4 == "_rd4" and s6.DRAW_SUFFIX_RD3 == "_rd3" and s6.DRAW_SUFFIX_RD2 == "_v2" and s6.SESSION_NAME == "sd2"
          and s6.SESSION_NAME_SD1 == "sd1" and s6.SESSIONS == ("rd1", "rd2", "rd3", "rd4", "sd1", "sd2"), "the session names and the draw suffixes (sd2's is its own)")
    check(s6.LENGTH_SCALE_V4 == 120.0 == s5.LENGTH_SCALE_V4 == float(mx.BURST_WORDS) and s6.SELECT4_CONTRACT == "m8_rd_select_v4" == s5.SELECT4_CONTRACT, "v4 unchanged: the scale, the contract name")
    check(s6.select4_description is s5.select4_description and s6.v4_weights is s5.v4_weights and s6.overlay_rows6 is s5.overlay_rows5 and s6.record_bound_max_L is s5.record_bound_max_L,
          "the selection contract, the weights and the overlays are sd1's functions, unchanged")
    check(mx.select_key("m8_rd_a1_sd2", 17557) == "m8_rd|m8_rd_a1_sd2|select|17557" and mx.explore_key("m8_rd_a1_sd2", 17557, 3) == "m8_rd|m8_rd_a1_sd2|explore|17557|3", "the key strings")
    a = s6.Archive6("m8_rd_a1")
    check(a.draw_id_sd2 == "m8_rd_a1_sd2" and len({a.draw_id_rd2, a.draw_id_rd3, a.draw_id_rd4, a.draw_id_sd1, a.draw_id_sd2}) == 5, "the draw ids")
    d = s6.draws_description()
    check(d["select"] == "m8_rd|<archive id>_sd2|select|<iteration>" and d["identity_open"].endswith("identity_open|sd2|<cell id>") and d["sd1_select"].endswith("_sd1|select|<iteration>")
          and d["rd4_select"].endswith("_rd4|select|<iteration>"), f"the registered key strings: {d}")
    check(len(s6.draws_digest()) == 64 and s6.draws_digest() != s5.draws_digest(), "the draws digest")
    check(rule6.RULE_ID == "m8_sd2_rule_v1" and rule6.rule_digest() not in (rule5.rule_digest(), rule2.rule_digest()), "sd2's own rule")
    check(rule6.SCOPE.startswith("M8-sd2: second time-directed continuation of archive m8_rd_a1") and "no control arm" in rule6.SCOPE and "not a policy result" in rule6.SCOPE and "m8_rd_select_v4 unchanged" in rule6.SCOPE
          and "sd1's verified clear" in rule6.SCOPE, "the scope label")
    c6, c5 = ses6.caps(), ses5.caps()
    check(c6 == c5 and c6 == t4.ses4.caps(), f"caps differ from sd1's and rd4's: { {k: (c6[k], c5.get(k)) for k in c6 if c6[k] != c5.get(k)} }")
    cfg = ses6.run_config()
    check(cfg.session_id == "sd2" and cfg.root == ses6.SD2_ROOT and cfg.arm_cap("T") == 6_000_000 and cfg.min_arm_ticks == 2_000_000 and cfg.n_workers == 5 and cfg.burst_words == 120
          and cfg.horizon == 3600 and cfg.p1_tick_cap == 70_000 and cfg.replay_tick_cap == 400_000 and cfg.global_cap_s == 3600.0, "run_config carries the registered values")
    check(ses6.SD2_ROOT.name == "m8_rd_sd2" and ses6.SD1_ROOT.name == "m8_rd_sd1" and ses6.APPROVAL.name == "rl_m8_sd2_approval.json" and ses6.INCREMENT_SD1.name == "2026-10-11_incr_m8_sd1"
          and ses6.INCREMENT_RD4.name == "2026-10-03_incr_m8_rd4", "the roots, the approval path and the increments")
    rr = ses6.RECORD_REFERENCE
    check(ses6.MARGIN == 24 == rule5.MARGIN and rr["completion_input_tick"] == 2086 and rr["completion_time_passed"] == 2085 and rr["words"] == 2086 and rr["session"] == "sd1" and rr["kind"] == "clear"
          and rr["native_action_digest"].startswith("a2a85903e704aab4"), "the pinned record reference and margin")
    check(ses6.PREVIOUS_RECORD_REFERENCE == r5.RECORD_REFERENCE and ses6.PREVIOUS_RECORD_REFERENCE["completion_input_tick"] == 2315 and ses6.PREVIOUS_MARGIN == 24, "the previous reference is sd1's")
    check(rule6.PROGRESS_BAR == 2062 and s6.record_bound_max_L(2086, 24) == 2061 and rule6.TIERS["5_percent"] == 1981 and rule6.TIERS["10_percent"] == 1877 and rule6.TIERS["round_1800"] == 1800, "the bar, E7's bound and the tiers")
    check(rule6.LINE_STATUSES == ("REPAIR_NEEDED", "NOT_STARTED", "COUNTED_INCOMPLETE", "SD3_AFTER_REVIEW_NEW_REFERENCE", "SD3_AFTER_REVIEW_WITH_REASON"), "the five line statuses")
    sha = st.load_table()["sha256"]
    digs = ses6.contract_digests6("lines")
    digs5 = ses5.contract_digests5("lines")
    check(set(digs) == set(digs5) and len(digs) == 9 and digs["m8_rd_select_v4"] != digs5["m8_rd_select_v4"] and digs["m8_rd_select_v4"] != digs["m8_rd_select_v3"]
          and {k: v for k, v in digs.items() if k != "m8_rd_select_v4"} == {k: v for k, v in digs5.items() if k != "m8_rd_select_v4"}, "nine contract digests: only v4's differs from sd1's")
    check(digs["m8_rd_select_v4"] == s6.select4_contract_digest(sha, "lines", None, rr, 24) and ses6.sd1_session_event_digest("lines") == digs5["m8_rd_select_v4"], "v4 at the new reference; sd1's at the old")
    check(all((TOOLS_DIR / f).is_file() for f in ses6.TOOL_FILES) and len(ses6.TOOL_FILES) == 9 and set(PYTHON_TOOLS) | set(PS_TOOLS) == set(ses6.TOOL_FILES), f"the nine launch tools exist under tools/m8_sd2: {ses6.TOOL_FILES}")
    check(len(ses6.NEW_CODE_FILES) == 10 and set(ses6.CODE_FILES) >= set(ses5.CODE_FILES) and "docs/rl_m8_sd1_approval.json" in ses6.DOC_FILES and "docs/rl_m8_sd2_proposal_2026-10-12.md" in ses6.DOC_FILES
          and "docs/rl_m8_sd1_results_2026-10-11.md" in ses6.DOC_FILES and len(ses6.RULE_SELF_TESTS) == 6, "the pinned code and documents extend sd1's")
    fp = ses6.source_fingerprint()
    check(len(fp) == 16 and fp == ses6.source_fingerprint() and fp != ses5.source_fingerprint(), "the source fingerprint")
    if REAL_TREES:
        ev = ses6._events(SD1_REAL / "archive")
        check([(e["name"], e["first_iteration"]) for e in ev] == [("rd2", 2175), ("rd3", 6212), ("rd4", 10406), ("sd1", 13886)], f"rd2's, rd3's, rd4's and sd1's session events: {ev}")
        lines, fm = real_lines(), real_floor_min()
        v2d, v3d = s2.select2_contract_digest(sha, lines, fm), s4.select3_contract_digest(sha, lines, fm)
        v4_sd1 = s6.select4_contract_digest(sha, lines, fm, ev[3]["record_reference"], ev[3]["margin"])
        check(ev[0]["digest"] == ev[1]["digest"] == v2d and ev[2]["digest"] == v3d and ev[3]["digest"] == v4_sd1 == r6.SD1_SESSION_DIGEST and v4_sd1.startswith("eb08059242eef123"),
              "the recorded digests equal v2, v3 and v4 at sd1's reference recomputed from the current code")
        v4_sd2 = s6.select4_contract_digest(sha, lines, fm, rr, 24)
        check(v4_sd2 not in (v2d, v3d, v4_sd1) and v4_sd2.startswith("8e09d332f16bb6cb"), f"v4 at the new reference differs from all three: {v4_sd2[:16]}")
    return {"fingerprint": fp, "v4": digs["m8_rd_select_v4"][:12]}


def unit_select_v4_reference_parametrisation() -> Dict[str, Any]:
    import m7q_status_table as st

    sha = st.load_table()["sha256"]
    lines = real_lines() if REAL_TREES else "lines"
    fm = real_floor_min() if REAL_TREES else None
    old, new = ses6.PREVIOUS_RECORD_REFERENCE, ses6.RECORD_REFERENCE
    check(s6.changed_description_keys(sha, lines, fm, old, new, 24) == ["record_reference"], f"the two descriptions differ in the record reference only: {s6.changed_description_keys(sha, lines, fm, old, new, 24)}")
    d_old, d_new = s6.select4_description(sha, lines, fm, old, 24), s6.select4_description(sha, lines, fm, new, 24)
    v3 = s4.select3_contract_digest(sha, lines, fm)
    for d in (d_old, d_new):
        check(hashlib.sha256(json.dumps(s6.restore_v3(d, sha, lines, fm), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest() == v3, "each description with the registered keys restored hashes to the real v3 digest")
    if REAL_TREES:
        check(v3.startswith("fd69a0332de9db28"), f"the real v3 digest: {v3[:16]}")
    dg_old, dg_new = s6.select4_contract_digest(sha, lines, fm, old, 24), s6.select4_contract_digest(sha, lines, fm, new, 24)
    check(dg_old != dg_new and dg_new != s6.select4_contract_digest(sha, lines, fm, new, 23) and dg_new != s6.select4_contract_digest(sha, "other", fm, new, 24), "the digest depends on the reference, the margin and the lines")
    txt = s6.reference_change_text(old, new)
    check(txt == "record_reference 2315/2314 (rd4 cid 239) -> 2086/2085 (sd1 cid 901)", f"the change text is built from the two reference blocks: {txt}")
    check(s6.reference_change_text(syn_record_reference(200, session="x", cid=3), syn_record_reference(150, session="y", cid=4)) == "record_reference 200/199 (x cid 3) -> 150/149 (y cid 4)", "generic")
    for t in (200, 2086, 2315):
        for m in (1, 24):
            for c in list(range(t - 60, t + 3)) + [None]:
                check(rule6.outcome_of(c, t, m) == rule5.outcome_of(c, t, m), f"outcome_of differs from sd1's at {(c, t, m)}")
    check(list(inspect.signature(rule6.outcome_of).parameters) == ["best_completion_input_tick", "t_rec", "margin"], "outcome_of's signature")
    for bad in (dict(new, completion_input_tick=2087), dict(new, native_action_digest="x"), {k: v for k, v in new.items() if k != "source"}, dict(new, words="2086")):
        raises(s5.Select5Error, lambda b=bad: s6.validate_record_reference(b), "a malformed record reference is refused")
    return {"v4_old": dg_old[:12], "v4_new": dg_new[:12]}


def unit_record_bound_by_session() -> Dict[str, Any]:
    mk = t2.mkey
    spec = [(mk(1, 1, "A2"), 100, 300.0, 0, 0), (mk(2, 1, "A2"), 875, 300.0, 0, 0), (mk(3, 1, "A2"), 876, 300.0, 0, 0), (mk(4, 1, "A1"), 975, 300.0, 1, 1), (mk(5, 1, "G", 1023, 4), 976, 0.0, 2, 0),
            (mk(6, 2, "A2", 1023 - 2), 990, 300.0, 0, 0), (mk(7, 2, "A2", 2), 900, 300.0, 0, 0), (mk(8, 1, "A2"), 950, 300.0, 0, 0)]          # mask 2: exactly one live target (X1)
    a = archive6_for_prob(spec, t_rec_sd1=1000, t_rec=900, margin=24)
    check(a.sd1_bound_max_L() == 975 and a.bound_max_L() == 875 and a.bound_for(8) == 975 and a.bound_for(9) == 875 and a.bound_for(10 ** 6) == 875 and a.bound_for(7) is None, "the two bounds by iteration")
    by_L = {c.L: c for c in a.cells if c.id}
    p_sd2 = a.probabilities("v4")
    p_sd1 = a.probabilities_at_bound(a.sd1_bound_max_L())
    p_v3 = a.probabilities("v3")
    check(by_L[875].id in p_sd2 and by_L[876].id not in p_sd2 and by_L[975].id not in p_sd2 and by_L[100].id in p_sd2, "under sd2's bound: L <= 875 eligible, 876 and 975 not")
    check(by_L[876].id in p_sd1 and by_L[975].id in p_sd1 and by_L[976].id not in p_sd1 and by_L[950].id in p_sd1, "under sd1's bound: L <= 975 eligible, 976 not")
    check(by_L[976].id in p_v3 and len(p_v3) > len(p_sd1) > len(p_sd2), "v3 ignores E7; sd1's bound excludes less than sd2's")
    x1 = by_L[900]
    check(mcell.popcount(x1.key[3]) == 1 and x1.id not in p_sd2 and x1.id in p_sd1, "X1 does not exempt from E7 at either bound")
    check(a.eligible(x1) and a.eligible(by_L[976]) and not a._v4, "outside v4 the same cells are eligible under v3 (the flag is off)")
    beyond_sd2 = {c.id for c in a.cells if c.id and c.L > 875}
    beyond_sd1 = {c.id for c in a.cells if c.id and c.L > 975}
    for it in range(9, 309):
        check(a.select(it).id not in beyond_sd2, f"iteration {it}: an sd2 draw selected a cell beyond sd2's bound")
    check(a.select(8).id not in beyond_sd1, "the sd1 iteration never selects a cell beyond sd1's bound")
    check(a._bound_L == 875, "select restores the current bound")
    v = a._version
    a._v4 = True
    a._bound_L = 975
    n_sd1 = sum(len(cs) for cs in a.eligible_levels().values())
    a._bound_L = 875
    n_sd2 = sum(len(cs) for cs in a.eligible_levels().values())
    a._v4 = False
    check(a._version == v and n_sd1 == n_sd2 + len(beyond_sd2) - len(beyond_sd1), f"the eligible-levels cache is keyed on the bound: {n_sd1} under sd1's, {n_sd2} under sd2's")
    b = archive6_for_prob(spec, with_sd2=False, t_rec_sd1=1000)
    check(b.sd2_first_iteration is None and b.bound_max_L() == 975 and b.bound_for(8) == 975 and b.bound_for(500) == 975, "before sd2 begins the current bound is sd1's")
    raises(s6.Select6Error, lambda: fresh6("y").sd1_bound_max_L(), "no sd1 bound before sd1 begins")
    return {"eligible_sd1_bound": n_sd1, "eligible_sd2_bound": n_sd2}


def unit_archive6_draw_and_mode_switch() -> Dict[str, Any]:
    n1, n2, n3, n4, n5, n6 = 40, 50, 50, 50, 50, 50
    a = synth_archive6("sw6", n1, n2, n3, n4, n5, n6, t_rec_sd1=200, t_rec=150, margin=24)
    f2, f3, f4, f5, f6 = n1, n1 + n2, n1 + n2 + n3, n1 + n2 + n3 + n4, n1 + n2 + n3 + n4 + n5
    check(a.mode == 2 and a.rd2_first_iteration == f2 and a.rd3_first_iteration == f3 and a.rd4_first_iteration == f4 and a.sd1_first_iteration == f5 and a.sd2_first_iteration == f6 and a.first_iteration == f6
          and a.draw_id == a.draw_id_sd2 and a.record_reference["completion_input_tick"] == 150 and a.sd1_record_reference["completion_input_tick"] == 200 and a.margin == 24
          and a.bound_max_L() == 125 and a.sd1_bound_max_L() == 175, "the six-part archive")
    for it, want in ((0, "syn6_v2"), (f2, "syn6_v2"), (f3, "syn6_rd3"), (f4, "syn6_rd4"), (f5 - 1, "syn6_rd4"), (f5, "syn6_sd1"), (f6 - 1, "syn6_sd1"), (f6, "syn6_sd2"), (f6 + 1000, "syn6_sd2")):
        check(a.draw_for(it) == want, f"draw_for({it}) = {a.draw_for(it)}, expected {want}")
    check(a.iteration_ranges() == {"rd1": (0, f2 - 1), "rd2": (f2, f3 - 1), "rd3": (f3, f4 - 1), "rd4": (f4, f5 - 1), "sd1": (f5, f6 - 1), "sd2": (f6, f6 + n6 - 1)}, f"ranges {a.iteration_ranges()}")
    check([a.session_of_iteration(i) for i in (0, f2, f3, f4, f5, f6, 10 ** 6)] == ["rd1", "rd2", "rd3", "rd4", "sd1", "sd2", "sd2"], "session_of_iteration")
    check(any(c.L > 125 for c in a.cells) and any(125 < c.L <= 175 for c in a.cells), "the synthetic archive holds cells between the bounds and beyond them (both bounds bind)")
    nxt = f6 + n6
    keep = (a.draw_id, a._v3, a._v4, a._bound_L)

    def independent(it: int, draw: str, mode: str, bound: Optional[int]) -> int:
        levels: Dict[int, List[march.Cell]] = {}
        for c in a.cells:
            ok = s2.Archive2.eligible(a, c) and (mode != "v4" or c.id == 0 or c.L <= int(bound))
            if ok:
                levels.setdefault(c.level, []).append(c)
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
        if mode == "v4":
            ws = [(1.0 / math.sqrt(1 + c.seen)) * (120.0 / (120.0 + c.L - lmin)) * s2.W_RES[c.key[2]] for c in cells]
        elif mode == "v3":
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

    for it in range(nxt, nxt + 60):
        check(a.select(it).id == independent(it, a.draw_id_sd2, "v4", 125), f"iteration {it}: select differs from the independent v4 draw at sd2's bound")
    for it in range(f5 + 3, f5 + 30):
        check(a.select(it).id == independent(it, a.draw_id_sd1, "v4", 175), f"iteration {it}: an sd1 iteration is not selected under v4 at sd1's bound and the sd1 draw")
    for it in range(f4 + 3, f4 + 20):
        check(a.select(it).id == independent(it, a.draw_id_rd4, "v3", None), f"iteration {it}: an rd4 iteration is not selected under v3 and the rd4 draw")
    check((a.draw_id, a._v3, a._v4, a._bound_L) == keep, "select restores the draw id, the flags and the bound")
    differ = sum(int(independent(it, a.draw_id_sd2, "v4", 125) != independent(it, a.draw_id_sd1, "v4", 125)) for it in range(nxt, nxt + 200))
    check(differ > 0, "sd2's draws are not sd1's")
    differ2 = sum(int(independent(it, a.draw_id_sd2, "v4", 125) != independent(it, a.draw_id_sd2, "v4", 175)) for it in range(nxt, nxt + 200))
    check(differ2 > 0, "the bound changes the selection on the same draws")
    w6 = list(mx.words(lambda i: mx.explore_key("syn6_sd2", 7000, i), 60))
    w5 = list(mx.words(lambda i: mx.explore_key("syn6_sd1", 7000, i), 60))
    check(w6 != w5 and len(w6) == 60, "the explorer draws are keyed by the session's draw id")
    return {"differ_of_200": differ, "cells": len(a.cells)}


def unit_begin_sd2_and_persistence() -> Dict[str, Any]:
    rr5, rr6 = syn_record_reference(1000, session="rd4", cid=7), syn_record_reference(900, session="sd1", cid=9)
    a = fresh6("bs", -2550.0)
    raises(s6.Select6Error, lambda: a.begin_sd2(5, "L", rr6, 24), "sd2 cannot begin before the earlier session events")
    t2.drive2(a, t2.Krng("bs"), 20, 0, v2=False)
    a.begin_v2(20, "L")
    t2.drive2(a, t2.Krng("bs2"), 15, 20, v2=True)
    a.begin_rd3(35, "L")
    t2.drive2(a, t2.Krng("bs3"), 12, 35, v2=True)
    a.begin_rd4(47, "L")
    t2.drive2(a, t2.Krng("bs4"), 12, 47, v2=True)
    raises(s6.Select6Error, lambda: a.begin_sd2(60, "L", rr6, 24), "sd2 cannot begin before sd1's session event")
    a.begin_sd1(59, "L", rr5, 24)
    check(a.sd1_record_reference == rr5 and a.sd1_margin == 24 and a.bound_for(59) == 975, "begin_sd1 records sd1's reference for the bound of sd1's part")
    t2.drive2(a, t2.Krng("bs5"), 12, 59, v2=True)
    raises(s6.Select6Error, lambda: a.begin_sd2(60, "L", rr6, 24), "reusing a dispatched iteration is refused")
    a.apply_dispatch(500, 0, 0)
    raises(s6.Select6Error, lambda: a.begin_sd2(600, "L", rr6, 24), "a pending dispatch blocks the switch")
    a.note_failure(500, "x")
    raises(s6.Select6Error, lambda: a.begin_sd2(600, "another line table", rr6, 24), "a selection contract that is not the one the earlier sessions ran is refused (the digests differ)")
    raises(s5.Select5Error, lambda: a.begin_sd2(600, "L", dict(rr6, words=999), 24), "a malformed reference is refused (by sd1's validator, unchanged)")
    raises(s6.Select6Error, lambda: a.begin_sd2(600, "L", rr6, 0), "a zero margin is refused")
    n_ev = len(a.events)
    ev = a.begin_sd2(600, "L", rr6, 24)
    v4_old = s6.select4_contract_digest(a.clf.table_sha256, "L", a.floor_min, rr5, 24)
    v4_new = s6.select4_contract_digest(a.clf.table_sha256, "L", a.floor_min, rr6, 24)
    check(ev["name"] == "sd2" and ev["first_iteration"] == 600 and ev["draw_suffix"] == "_sd2" and ev["select"] == "m8_rd_select_v4" and ev["record_reference"] == rr6 and ev["margin"] == 24
          and ev["length_scale"] == 120.0 and ev["digest"] == v4_new and ev["changed_from"] == {"select": "m8_rd_select_v4", "digest": v4_old, "changes": ["record_reference 1000/999 (rd4 cid 7) -> 900/899 (sd1 cid 9)"]}
          and a.events[-1] == ev and len(a.events) == n_ev + 1, f"one session event: {ev}")
    sess = [e for e in a.events if e["ev"] == "session"]
    check([e["name"] for e in sess] == ["rd2", "rd3", "rd4", "sd1", "sd2"] and sess[3]["digest"] == v4_old and sess[4]["digest"] == v4_new != v4_old, "sd2's digest is v4 at the new reference, sd1's at the old")
    check(a.sd2_first_iteration == 600 and a.first_iteration == 600 and a.draw_id == a.draw_id_sd2 and a.bound_max_L() == 875 and a.sd1_bound_max_L() == 975 and a.record_reference == rr6
          and a.sd1_record_reference == rr5 and a.margin == 24, "state after the switch: both references kept")
    raises(s6.Select6Error, lambda: a.begin_sd2(700, "L", rr6, 24), "a second switch is refused")
    t = tmpdir("m8sd2p_")
    x = fresh6("bs", -2550.0)
    t2.drive2(x, t2.Krng("bs"), 20, 0, v2=False)
    x.begin_v2(20, "L")
    t2.drive2(x, t2.Krng("bs2"), 15, 20, v2=True)
    x.begin_rd3(35, "L")
    t2.drive2(x, t2.Krng("bs3"), 12, 35, v2=True)
    x.begin_rd4(47, "L")
    t2.drive2(x, t2.Krng("bs4"), 12, 47, v2=True)
    x.begin_sd1(59, "L", rr5, 24)
    t2.drive2(x, t2.Krng("bs5"), 12, 59, v2=True)
    march.save_checkpoint(t / "sd1" / "archive", x, art5.stamp({"checkpoint_seq": 57, "why": "x"}, created_utc=OPEN_UTC))
    y, meta_y = s6.Archive6.read_dir(t / "sd1" / "archive")
    check(y.sd2_first_iteration is None and y.sd1_first_iteration == 59 and y.draw_id == y.draw_id_sd1 and y.record_reference == rr5 and y.sd1_record_reference == rr5 and y.bound_max_L() == 975,
          "an sd1 closing archive loads as an Archive6 before sd2 (the current bound is sd1's)")
    check(s5.Archive5.read_dir(t / "sd1" / "archive")[0].sd1_first_iteration == 59, "sd1's own loader still reads it")
    y.begin_sd2(71, "L", rr6, 24)
    t2.drive2(y, t2.Krng("bs6"), 12, 71, v2=True)
    march.save_checkpoint(t / "sd2" / "archive", y, art.stamp({"checkpoint_seq": 58, "why": "x"}, created_utc=OPEN_UTC))
    pp = rs.prefix_property(t / "sd1" / "archive", t / "sd2" / "archive")
    check(pp["ok"] and pp["events.jsonl"]["lines"] == len(x.events) and pp["bursts.idx.jsonl"]["lines"] == len(x.bursts), f"sd2's files begin with sd1's closing bytes: {pp}")
    z, meta_z = s6.Archive6.read_dir(t / "sd2" / "archive")
    check(meta_z["schema"] == s2.ARCHIVE_SCHEMA_V2 and meta_z["archive6_contract"] == s6.ARCHIVE6_CONTRACT and meta_z["archive5_contract"] == s5.ARCHIVE5_CONTRACT and meta_z["sd2_first_iteration"] == 71
          and meta_z["sd1_first_iteration"] == 59 and meta_z["draw_ids6"] == {"rd1": "bs", "rd2": "bs_v2", "rd3": "bs_rd3", "rd4": "bs_rd4", "sd1": "bs_sd1", "sd2": "bs_sd2"}
          and meta_z["select4_digest_sd2"] == v4_new and meta_z["select4_digest_sd1"] == v4_old == meta_z["select4_digest"] and meta_z["record_reference_sd2"] == rr6 == meta_z["record_reference"]
          and meta_z["record_reference_sd1"] == rr5 and meta_z["margin_sd2"] == 24 and meta_z["bound_L_by_session"] == {"sd1": 975, "sd2": 875} and meta_z["created_utc"] == OPEN_UTC and art.is_stamped(meta_z),
          "the sd2 directory is self-describing and stamped")
    check(z.sd2_first_iteration == 71 and z.draw_id == "bs_sd2" and z.record_reference == rr6 and z.sd1_record_reference == rr5 and z.bound_max_L() == 875 and z.sd1_bound_max_L() == 975 and z.mode == 2,
          "the reload knows both bounds")
    check([c.to_json() for c in z.cells] == [c.to_json() for c in y.cells] and z.diag2 == y.diag2 and z.desc == y.desc and z.bound == y.bound, "a reload reproduces cells, counters and derived flags")
    check(s6.audit6(z, "L")["ok"] and s6.rebuild6(z, "L").events == z.events, "the reloaded six-part archive audits and rebuilds")
    raises(s5.Select5Error, lambda: s5.Archive5.read_dir(t / "sd2" / "archive"), "sd1's loader refuses an sd2 archive (five session events): sd1's tools can never misread sd2's tree")
    raises(s4.Select4Error, lambda: s4.Archive4.read_dir(t / "sd2" / "archive"), "rd4's loader refuses it too")
    w, _m = s2.Archive2.read_dir(t / "sd2" / "archive")
    check(w.mode == 2 and w.first_iteration == 71, "rd2's loader reads the sd2 directory (mode 2; the last session's first iteration)")
    only_rd4 = fresh6("o4")
    only_rd4.begin_v2(5, "L")
    only_rd4.begin_rd3(6, "L")
    only_rd4.begin_rd4(7, "L")
    raises(s6.Select6Error, lambda: s6.Archive6.adopt(only_rd4), "an rd4 archive (three session events) is not an sd1 archive: sd2 continues sd1's closing archive")
    for crash in (None, "tmp_written", "tmp_verified", "current_moved", "new_installed"):
        root = t / f"ck_{crash}" / "archive"
        march.save_checkpoint(root, z, art.stamp({"checkpoint_seq": 1}, created_utc=OPEN_UTC))
        t2.drive2(z, t2.Krng(f"more{crash}"), 4, 200, v2=True)
        try:
            march.save_checkpoint(root, z, art.stamp({"checkpoint_seq": 2}, created_utc=OPEN_UTC), crash_at=crash)
            check(crash is None, "unexpected success")
        except march.SimulatedCrash:
            check(crash is not None, "unexpected crash")
        d, m, rep = march.load_latest_verified(root)
        check(d is not None, f"no verified checkpoint after a crash at {crash}: {rep}")
        loaded, mm = s6.Archive6.read_dir(d)
        check(s6.audit6(loaded, "L")["ok"] and m["checkpoint_seq"] == 2 and mm["created_utc"] == OPEN_UTC, f"crash {crash}: the newest complete checkpoint audits and keeps created_utc")
        z, _m3 = s6.Archive6.read_dir(t / "sd2" / "archive")
    shutil.rmtree(t, ignore_errors=True)
    return {"cells": len(a.cells)}


def unit_ledger_rebuild6() -> Dict[str, Any]:
    n1, n2, n3, n4, n5, n6 = 50, 60, 60, 60, 70, 70
    a = synth_archive6("lr6", n1, n2, n3, n4, n5, n6, t_rec_sd1=200, t_rec=150, margin=24)
    f5, f6 = n1 + n2 + n3 + n4, n1 + n2 + n3 + n4 + n5
    check(len(a.cells) > 300 and len(a.bursts) == f6 + n6 and a.mode == 2 and any(c.L > a.bound_max_L() for c in a.cells) and any(a.bound_max_L() < c.L <= a.sd1_bound_max_L() for c in a.cells),
          f"the synthetic six-part archive with both bounds binding: {len(a.cells)} cells")
    aud = s6.audit6(a, "lines")
    check(aud["ok"], f"audit of a six-part archive: {aud['problems']}")
    check(aud["prefixes_reconstructed"] == len(a.cells) and aud["dispatch_rows"] == [], "every prefix reconstructs; no rows unless asked")
    rows = s6.audit6(a, "lines", collect_rows_from=f6)["dispatch_rows"]
    check(len(rows) == n6 and all(r["created_in"] in s6.SESSIONS for r in rows) and any(r["created_in"] == "sd2" for r in rows) and any(r["created_in"] == "sd1" for r in rows), "the dispatch rows of sd2's part name the creating session")
    rb = s6.rebuild6(a, "lines")
    check([c.to_json() for c in rb.cells] == [c.to_json() for c in a.cells] and rb.events == a.events and rb.diag2 == a.diag2 and rb.sd2_first_iteration == f6 and rb.record_reference == a.record_reference
          and rb.sd1_record_reference == a.sd1_record_reference, "the rebuild equals the archive")
    check(not s5.audit5(a, "lines")["ok"], "sd1's own audit cannot cross a fifth session event (which is why rebuild6 exists)")
    t = tmpdir("m8sd2lr_")
    a.write_files(t / "a", art.stamp({"checkpoint_seq": 1}, created_utc=OPEN_UTC))

    def load() -> s6.Archive6:
        return s6.Archive6.read_dir(t / "a")[0]

    check(s6.audit6(load(), "lines")["ok"], "a saved and reloaded archive audits")
    b = load()
    k = next(i for i, e in enumerate(b.events) if e["ev"] == "dispatch" and e["it"] == f6 + 3)
    b.events[k]["cell"] = (b.events[k]["cell"] + 1) % len(b.cells)
    check(not s6.audit6(b, "lines")["ok"], "a changed sd2 selection is detected by the re-derived draw")
    b = load()
    k = next(i for i, e in enumerate(b.events) if e["ev"] == "dispatch" and e["it"] == f5 + 3)
    b.events[k]["cell"] = (b.events[k]["cell"] + 1) % len(b.cells)
    check(not s6.audit6(b, "lines")["ok"], "a changed sd1 selection is detected too (sd1's part rebuilds under sd1's bound)")
    for mutate, what in ((lambda e: e.__setitem__("digest", "0" * 64), "a tampered sd2 session digest"), (lambda e: e.__setitem__("margin", 23), "a tampered margin"),
                         (lambda e: e["record_reference"].__setitem__("completion_input_tick", 701) or e["record_reference"].__setitem__("words", 701), "a tampered record reference"),
                         (lambda e: e.__setitem__("draw_suffix", "_sd1"), "a tampered draw suffix"), (lambda e: e.__setitem__("first_iteration", e["first_iteration"] + 1), "a shifted first iteration"),
                         (lambda e: e["changed_from"].__setitem__("digest", "0" * 64), "a tampered record of sd1's digest"), (lambda e: e.__setitem__("length_scale", 900.0), "a tampered length scale"),
                         (lambda e: e["changed_from"].__setitem__("changes", ["x"]), "a tampered change text")):
        b = load()
        mutate(next(e for e in b.events if e["ev"] == "session" and e["name"] == "sd2"))
        check(not s6.audit6(b, "lines")["ok"], f"{what} is detected")
    b = load()
    next(e for e in b.events if e["ev"] == "session" and e["name"] == "sd1")["record_reference"]["completion_input_tick"] = 777
    check(not s6.audit6(b, "lines")["ok"], "a tampered sd1 reference (the bound of sd1's part) is detected")
    b = load()
    b.events = [e for e in b.events if not (e["ev"] == "session" and e["name"] == "sd2")]
    check(not s6.audit6(b, "lines")["ok"], "a ledger without sd2's session event does not rebuild")
    check(not s6.audit6(load(), "other lines")["ok"], "a different pinned line table is detected through the session digests")
    b = load()
    b.cells[len(b.cells) // 2].seen += 1
    check(not s6.audit6(b, "lines")["ok"], "a tampered `seen` counter is detected")

    class OldBound(s6.Archive6):
        def bound_for(self, iteration: int) -> Optional[int]:
            b_ = super().bound_for(iteration)
            return self.sd1_bound_max_L() if (b_ is not None and self.sd2_first_iteration is not None and int(iteration) >= self.sd2_first_iteration) else b_

    rng = t2.Krng("old")
    o = OldBound("syn6", floor_min=-2100.0)
    o.init_cell0(t1.key(0, 0), t1.mk_end(), bytes(32), bytes([1]) * 32)
    t2.drive2(o, rng, n1, 0, v2=False)
    o.begin_v2(n1, "lines")
    t2.drive2(o, rng, n2, n1, v2=True)
    o.begin_rd3(n1 + n2, "lines")
    t2.drive2(o, rng, n3, n1 + n2, v2=True)
    o.begin_rd4(n1 + n2 + n3, "lines")
    t2.drive2(o, rng, n4, n1 + n2 + n3, v2=True)
    o.begin_sd1(f5, "lines", syn_record_reference(200, session="rd4", cid=7), 24)
    t2.drive2(o, rng, n5, f5, v2=True)
    o.begin_sd2(f6, "lines", syn_record_reference(150, session="sd1", cid=9), 24)
    t2.drive2(o, rng, n6, f6, v2=True)
    check(not s6.audit6(o, "lines")["ok"], "an sd2 part selected under sd1's bound fails the audit under sd2's")
    shutil.rmtree(t, ignore_errors=True)
    return {"cells": len(a.cells), "bound_L": a.bound_max_L(), "sd1_bound_L": a.sd1_bound_max_L()}


# -- the resume protocol on a synthetic chain ------------------------------------------------------------------------------------------------------------


def unit_resume_five_level_synthetic() -> Dict[str, Any]:
    chain = build_chain6()
    e5 = chain["expect5"]
    rr = e5["inherited_record"]["best_verified"]
    rr_prev = e5["sd1_record_reference"]
    check(chain["sd1_outcome"] in ("PROGRESS", "RECORD_BELOW_MARGIN") and e5["first_sd2_iteration"] == e5["dispatch_iterations"][1] + 1 and rr["completion_input_tick"] == rr["words"] > 24
          and rr["completion_input_tick"] < rr_prev["completion_input_tick"] and rr["session"] == "sd1", f"the synthetic chain: {rr} below {rr_prev['completion_input_tick']}")
    check(e5["inherited_record"]["rd5_permitted"] is True and e5["inherited_record"]["level_10_L"] and e5["inherited_record"]["level_10_L"][0] == rr["completion_input_tick"]
          and e5["inherited_record"]["pred_outcome"] == chain["sd1_outcome"] and e5["inherited_record"]["pred_session_counts"] is True, "the inherited record facts")
    op = open6(chain)
    check(op["ok"], f"the open protocol on a synthetic chain: {op['problems']}")
    check(all(op[f"R1_{w}_immutability"]["ok"] for w in ("rd1", "rd2", "rd3", "rd4", "sd1")) and all(op[f"R2_R4_{w}_archive"]["ok"] for w in ("rd1", "rd2", "rd3", "rd4", "sd1"))
          and not op["R3_pins"]["problems"] and not op["R3_pins"]["sd1_problems"] and op["R5_overlay"]["ok"] and op["rd_levels"]["ok"], "R1-R5 at five levels")
    f5 = op["facts5"]
    check(f5["first_sd2_iteration"] == e5["first_sd2_iteration"] and f5["sd1_checkpoint_seq"] == e5["checkpoint_seq"] and f5["record_reference"] == rr and f5["sd1_line"]["rd5_permitted"] is True
          and f5["sd1_line"]["status"] == e5["line_status"] and f5["sd1_line"]["session_counts"] is True, "iterations continue from sd1's last; the record reference; the sd and rd lines")
    check([e["name"] for e in f5["session_events"]] == ["rd2", "rd3", "rd4", "sd1"] and f5["session_events"][3]["digest"] == f5["digest_recomputed"]["v4_sd1"] and f5["sd1_session_event"]["record_reference"] == rr_prev,
          "sd1's session digest equals v4 at sd1's own reference recomputed")
    check(f5["audit"]["ok"] and f5["prefix_chain"]["ok"], "sd1's audit with the six-part code (zero ticks) and the prefix chain of five")
    check(len(op["inherited"]) == len(e5["inherited_record"]["unverified_clear_trajectories"]) and all(c["kind"] == "clear" and c["inherited"] and c["pred_session"] == "sd1" for c in op["inherited"]),
          f"the inherited descriptive candidates by the rule: {len(op['inherited'])}")
    rc = op["record_candidate"]
    check(rc and len(rc["words"]) == rr["words"] and mcell.words_digest(rc["words"]) == rr["native_action_digest"] and rc["record"] and rc["pred_session"] == "sd1", "the record candidate")
    for tree in ("rd1", "rd2", "rd3", "rd4", "sd1"):
        for what in ("byte", "mtime", "extra", "missing", "increment"):
            cp = copy_chain6(chain)
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
                rec_p = cp[{"rd1": "inc1", "rd2": "inc2", "rd3": "inc3", "rd4": "inc4", "sd1": "inc5"}[tree]] / "verification.json"
                rec = json.loads(rec_p.read_text(encoding="utf-8"))
                rec["result"] = "FAIL"
                rec_p.write_text(json.dumps(rec), encoding="utf-8")
            op2 = open6(cp, with_audit=False)
            tag = f"R1 ({tree})"
            check(not op2["ok"] and any(tag in p for p in op2["problems"]), f"R1 missed a change of {tree}'s tree: {what}: {op2['problems'][:3]}")
            for other in {"rd1", "rd2", "rd3", "rd4", "sd1"} - {tree}:
                check(not any(f"R1 ({other})" in p for p in op2["problems"]), f"R1 blamed {other} for a change of {tree}'s tree")
            shutil.rmtree(cp["t"], ignore_errors=True)
    inh = e5["inherited_record"]
    for what, bad in (("cells", dict(e5, cells=e5["cells"] + 1)), ("checkpoint", dict(e5, checkpoint_seq=99)), ("first sd1 iteration", dict(e5, first_sd1_iteration=e5["first_sd1_iteration"] + 1)),
                      ("iterations", dict(e5, dispatch_iterations=(0, e5["dispatch_iterations"][1] + 1))), ("first sd2 iteration", dict(e5, first_sd2_iteration=e5["first_sd2_iteration"] + 1)),
                      ("decision", dict(e5, outcome="NO_SHORTER_CLEAR")), ("line status", dict(e5, line_status="REPAIR_NEEDED")), ("counted", dict(e5, session_counts=False)),
                      ("returns", dict(e5, returns=e5["returns"] + 1)), ("ticks", dict(e5, exploration_ticks=e5["exploration_ticks"] + 1)), ("first new cell", dict(e5, first_new_cell=e5["first_new_cell"] + 1)),
                      ("cells created", dict(e5, sd1_cells_created=e5["sd1_cells_created"] + 1)),
                      ("sd1's reference", dict(e5, sd1_record_reference=dict(rr_prev, completion_input_tick=rr_prev["completion_input_tick"] + 1, words=rr_prev["words"] + 1))),
                      ("sd1's margin", dict(e5, sd1_margin=23)), ("sd1's session digest", dict(e5, sd1_session_digest="0" * 64)), ("the archive's created_utc", dict(e5, archive_created_utc="2020-01-01T00:00:00Z")),
                      ("the close record hash", dict(e5, close_record_sha256="0" * 64)), ("the rule record hash", dict(e5, rule_record_sha256="0" * 64)),
                      ("best clear tick", dict(e5, inherited_record=dict(inh, best_verified=dict(rr, completion_input_tick=rr["completion_input_tick"] + 1, words=rr["words"] + 1)))),
                      ("an extra level-10 cell", dict(e5, inherited_record=dict(inh, level_10_L=list(inh["level_10_L"]) + [rr["completion_input_tick"] + 50]))),
                      ("the top level's shortest arrival", dict(e5, inherited_record=dict(inh, top_eligible_level=dict(inh["top_eligible_level"], min_L=inh["top_eligible_level"]["min_L"] - 1)))),
                      ("rd5", dict(e5, inherited_record=dict(inh, rd5_permitted=False))), ("the unverified trajectories", dict(e5, inherited_record=dict(inh, unverified_clear_trajectories=[{"iteration": 1, "first_clear": 1}])))):
        f = r6.sd1_archive_facts(chain["rd1"], chain["rd2"], chain["rd3"], chain["rd4"], chain["sd1"], chain["lines"], bad, with_audit=False)
        check(not f["ok"], f"R2: a wrong {what} is refused")
    cp = copy_chain6(chain)
    rp = cp["sd1"] / "sessions" / "sd1" / "verification" / "replays.jsonl"
    rows = [json.loads(ln) for ln in rp.read_text(encoding="utf-8").splitlines() if ln.strip()]
    rp.write_text("".join(json.dumps(dict(r, clear=False) if not r.get("header") else r) + "\n" for r in rows), encoding="utf-8")
    f = r6.sd1_archive_facts(cp["rd1"], cp["rd2"], cp["rd3"], cp["rd4"], cp["sd1"], chain["lines"], e5, with_audit=False)
    check(not f["ok"] and any("inherited record" in p or "no verified clear" in p or "could not be read" in p for p in f["problems"]), f"R2: without a verified clear there is no record reference: {f['problems'][:2]}")
    shutil.rmtree(cp["t"], ignore_errors=True)
    cp = copy_chain6(chain)
    close_p = cp["sd1"] / "sessions" / "sd1" / "close.json"
    d = json.loads(close_p.read_text(encoding="utf-8"))
    d["archive"]["manifest"]["cells.jsonl"] = "0" * 64
    close_p.write_text(json.dumps(d), encoding="utf-8")
    check(not r6.sd1_archive_facts(cp["rd1"], cp["rd2"], cp["rd3"], cp["rd4"], cp["sd1"], chain["lines"], e5, with_audit=False)["ok"], "R2: the archive must equal sd1's close record")
    shutil.rmtree(cp["t"], ignore_errors=True)
    f = r6.sd1_archive_facts(chain["rd1"], chain["rd2"], chain["rd3"], chain["rd4"], chain["sd1"], "another line table", e5, with_audit=False)
    check(not f["ok"] and any("digest" in p for p in f["problems"]), "R2: the session digests must equal the digests recomputed from the contracts and the pinned lines")
    op3 = open6(chain, live=lambda: dict(t3.live_pins_of(chain), executable_sha256="0" * 64), with_audit=False)
    check(not op3["ok"] and op3["R3_pins"]["executable_only_sd1"] and any("only the executable differs" in x for x in op3["problems"]), "R3: an executable-only difference refuses the exploration session")
    op4 = open6(chain, live=lambda: dict(t3.live_pins_of(chain), flags={"explore": {}, "verify": {}}), with_audit=False)
    check(not op4["ok"] and any("R3" in x for x in op4["problems"]), "R3: the flags")
    op5x = open6(chain, with_audit=False, record_reference=dict(rr, completion_input_tick=rr["completion_input_tick"] + 1, words=rr["words"] + 1))
    check(not op5x["ok"] and any("differs from the pinned one" in x for x in op5x["problems"]), "R2: a pinned reference that differs from sd1's records is refused")
    pm = e5["sd1_margin"]
    ov = r6.closing_overlay6(chain["sd1"], rr_prev, pm, rr, rule6.MARGIN, expect_sd1={}, expect_v4={}, floor_min=FLOOR_MIN)
    check(ov["ok"] and ov["sd1_closing"]["counts"] == ov["stored_close_counts"] and len(ov["v4"]["rows"]) == e5["cells"] and ov["v4"]["counts"]["bound_L"] == rr["completion_input_tick"] - 25
          and ov["sd1_closing"]["counts"]["bound_L"] == rr_prev["completion_input_tick"] - pm - 1, f"R5: both overlays: {ov['problems']}")
    ov_b = r6.closing_overlay6(chain["sd1"], rr_prev, pm, rr, rule6.MARGIN, expect_sd1={}, expect_v4={}, floor_min=FLOOR_MIN)
    check(ov["v4"]["sha256"] == ov_b["v4"]["sha256"] and ov["sd1_closing"]["sha256"] == ov_b["sd1_closing"]["sha256"] and ov["v4"]["sha256"] != ov["sd1_closing"]["sha256"], "reproducible, and the two overlays differ")
    c4 = ov["v4"]["counts"]
    check(c4["eligible_v4"] == c4["eligible_v3"] - c4["record_bound_among_v3_eligible"] and c4["record_bound_cells"] == sum(c4["record_bound_by_level"].values())
          and c4["eligible_v4"] <= ov["sd1_closing"]["counts"]["eligible_v4"], f"the v4 overlay's arithmetic; the tighter bound excludes at least as much: {c4}")
    check(not r6.closing_overlay6(chain["sd1"], rr_prev, pm, rr, rule6.MARGIN, expect_sd1={"cells": e5["cells"] + 1}, expect_v4={}, floor_min=FLOOR_MIN)["ok"], "R5: a registered sd1 figure that differs is refused")
    check(not r6.closing_overlay6(chain["sd1"], rr_prev, pm, rr, rule6.MARGIN, expect_sd1={}, expect_v4={"eligible_v4": -1}, floor_min=FLOOR_MIN)["ok"], "R5: a registered v4 figure that differs is refused")
    check(not r6.closing_overlay6(chain["sd1"], rr_prev, pm, rr, rule6.MARGIN, expect_sd1={}, expect_v4={}, floor_min=FLOOR_MIN, v4_sha256="0" * 64)["ok"], "R5: a pinned digest that differs is refused")
    check(not r6.closing_overlay6(chain["sd1"], rr_prev, pm, rr, rule6.MARGIN, expect_sd1={}, expect_v4={}, floor_min=FLOOR_MIN, sd1_sha256="0" * 64)["ok"], "R5: a pinned sd1 digest that differs is refused")
    pm6 = r6.prior_milestones6(chain["rd1"], chain["rd2"], chain["rd3"], chain["rd4"], chain["sd1"])
    check(pm6["sd1"]["outcome"] == chain["sd1_outcome"] and pm6["sd1"]["best_completion_input_tick"] == rr["completion_input_tick"] and pm6["sd1"]["source"] == "sessions/sd1/rule.json" and pm6["rd4"]["m"] == 4, f"prior milestones: {pm6}")
    check(r6.sd1_line_status(chain["t"] / "nowhere")["missing"] and r6.sd1_line_status(chain["sd1"])["rd5_permitted"] is True and r6.sd1_line_status(chain["sd1"])["status"] == e5["line_status"], "the sd line status is read, never defaulted")
    t = tmpdir("m8mat6_")
    roots = []
    for i in (1, 2):
        root = t / f"sd2_{i}"
        a6 = r6.materialise6(chain["sd1"], root, facts=op["facts5"], overlay=op["overlay"], lines_sha256=chain["lines"], meta_extra={"pins": chain["pins"], "pin_tick0": op["facts5"]["pin_tick0"], "ticks": {}, "ledger_T": {}},
                             increment_manifest_sha256="x" * 64, utc=OPEN_UTC, margin=rule6.MARGIN, record_reference=rr, floor_min=FLOOR_MIN)
        roots.append(root)
    check(a6.mode == 2 and a6.sd2_first_iteration == e5["first_sd2_iteration"] and a6.draw_id == a6.draw_id_sd2 and a6.record_reference == rr and a6.sd1_record_reference == rr_prev and a6.margin == 24,
          "materialised: mode 2, sd2 begun, both references")
    for n in (*march.DATA_FILES, march.MANIFEST):
        check((roots[0] / "archive" / n).read_bytes() == (roots[1] / "archive" / n).read_bytes(), f"two materialisations are byte-identical: {n}")
        check(mw.sha256_file(roots[0] / "base" / n) == mw.sha256_file(chain["sd1"] / "archive" / n), f"the base copy of {n} is byte-identical to sd1's closing file")
    root6 = roots[0]
    check(mw.sha256_file(root6 / "derived" / "open_overlay.jsonl") == op["overlay"]["v4"]["sha256"] and mw.sha256_file(root6 / "derived" / "sd1_closing_overlay.jsonl") == op["overlay"]["sd1_closing"]["sha256"],
          "the stored overlays hash to their digests")
    ob = json.loads((root6 / "derived" / "open_overlay.json").read_text(encoding="utf-8"))
    check(art.is_stamped(ob) and ob["created_utc"] == OPEN_UTC and ob["open_overlay"]["sha256"] == op["overlay"]["v4"]["sha256"] and ob["record_reference"] == rr and ob["previous_record_reference"] == rr_prev
          and ob["margin"] == 24, "the stamped overlay record")
    base = json.loads((root6 / "derived" / "base.json").read_text(encoding="utf-8"))
    check(art.is_stamped(base) and base["schema"] == "m8_sd2_base_v1" and base["session_event"]["name"] == "sd2" and base["session_event"]["select"] == "m8_rd_select_v4" and base["sd1_increment_manifest_sha256"] == "x" * 64
          and base["inherited_record"] == e5["inherited_record"] and base["sd1_line"]["rd5_permitted"] is True and base["sd1_session_event"]["name"] == "sd1", "the stamped base record")
    d, meta, rep = march.load_latest_verified(root6 / "archive")
    check(d is not None and meta["checkpoint_seq"] == e5["checkpoint_seq"] + 1 and meta["why"] == "open" and meta["session"] == "sd2" and meta["created_utc"] == OPEN_UTC and art.is_stamped(meta),
          "the first sd2 checkpoint is stamped with the materialisation time")
    check(r6.prefix_chain6(chain["rd1"] / "archive", chain["rd2"] / "archive", chain["rd3"] / "archive", chain["rd4"] / "archive", chain["sd1"] / "archive", root6 / "archive")["ok"], "the prefix chain of six holds at the open")
    loaded, _m = s6.Archive6.read_dir(root6 / "archive")
    check(s6.audit6(loaded, chain["lines"])["ok"], "the materialised archive audits (six parts, no sd2 dispatch yet)")
    arts = art.audit_tree6(root6)
    check(arts["ok"] and arts["exempt"] >= 5, f"every record of the materialised tree carries its stamp: {arts['failures']}")
    raises(r6.Resume6Error, lambda: r6.materialise6(chain["sd1"], root6, facts=op["facts5"], overlay=op["overlay"], lines_sha256=chain["lines"], meta_extra={}, increment_manifest_sha256="x", utc="u", margin=24, record_reference=rr),
           "an existing sd2 root is never overwritten")
    raises(r6.Resume6Error, lambda: r6.materialise6(chain["sd1"], t / "sd2_x", facts=op["facts5"], overlay=op["overlay"], lines_sha256=chain["lines"], meta_extra={}, increment_manifest_sha256="x", utc="u", margin=24,
                                                   record_reference=dict(rr, completion_input_tick=rr["completion_input_tick"] + 1, words=rr["words"] + 1)),
           "a reference other than the one read from sd1's records is refused")
    check(all_immutability6(chain)["ok"], "all five earlier trees are still equal to their increments after the open")
    shutil.rmtree(t, ignore_errors=True)
    return {"cells": len(a6.cells), "t_rec": rr["completion_input_tick"], "previous": rr_prev["completion_input_tick"], "inherited": len(op["inherited"])}


def unit_inherited_record_facts_refusal6() -> Dict[str, Any]:
    chain = build_chain6()
    inh = chain["expect5"]["inherited_record"]
    check(r6.record_fact_problems(inh, inh) == [], "the facts equal themselves")
    rr = inh["best_verified"]
    for what, bad in (("the best clear tick", dict(inh, best_verified=dict(rr, completion_input_tick=rr["completion_input_tick"] + 1, words=rr["words"] + 1))),
                      ("an extra level-10 cell", dict(inh, level_10_L=list(inh["level_10_L"]) + [9999])), ("a level's count", dict(inh, levels=dict(inh["levels"], **{"0": {"cells": 0, "min_L": 0}}))),
                      ("rd5", dict(inh, rd5_permitted=None if inh["rd5_permitted"] else True)), ("the unverified trajectories", dict(inh, unverified_clear_trajectories=inh["unverified_clear_trajectories"] + [{"iteration": 1, "first_clear": 1}])),
                      ("the verified clears", dict(inh, verified_clears=inh["verified_clears"] + [dict(inh["verified_clears"][0], cid=999)])), ("sd1's outcome", dict(inh, pred_outcome="INVALID")),
                      ("sd1's line", dict(inh, pred_line_status="x")), ("the wall-top cells", dict(inh, claim_facts=dict(inh["claim_facts"], wall_top_cell_ids=[1])))):
        check(r6.record_fact_problems(bad, inh) != [], f"{what} altered is refused")
    check(r6.record_fact_problems(dict(inh, best_verified=None), inh) != [], "no best clear is refused")
    out = {"synthetic": True}
    if REAL_TREES:
        a, _m = s6.Archive6.read_dir(SD1_REAL / "archive")
        facts = r6.inherited_record_facts6(SD1_REAL, a)
        probs = r6.record_fact_problems(facts, r6.INHERITED_RECORD6)
        check(probs == [], f"the real sd1 tree's inherited record facts equal the registered ones: {probs}")
        check(facts["best_verified"] == r6.RECORD_REFERENCE6 and facts["best_verified"]["completion_input_tick"] == 2086 and facts["best_verified"]["completion_time_passed"] == 2085, "the real record reference")
        check(facts["unverified_clear_trajectories"] == [] and facts["level_10_L"] == [2086, 2315, 2324, 2326, 2348] and facts["top_eligible_level"] == {"level": 9, "min_L": 1897, "min_cell": 30961}
              and facts["claim_facts"]["wall_top_cell_ids"] == [18318, 18767, 26944, 39911] and facts["inherited_descriptive"] == {"count": 3, "exact": 3, "inexact": 0, "ticks": 7013},
              f"the real facts: {facts['level_10_L']} {facts['top_eligible_level']} {facts['inherited_descriptive']}")
        check(r6.SD1_FACTS["cells"] == 44007 and r6.SD1_FACTS["first_sd2_iteration"] == 17557 and r6.SD1_FACTS["checkpoint_seq"] == 57 and r6.SD1_FACTS["sd1_record_reference"] == r5.RECORD_REFERENCE, "the registered sd1 facts")
        out = {"real": True, "levels": len(facts["levels"])}
    return out


def unit_open_protocol_real_trees6() -> Dict[str, Any]:
    """The open protocol R1-R5 on the real, closed rd1 to sd1 trees and their D: increments (read only): all five trees equal their increments, sd1's closing archive rebuilds under the six-part
    code (zero ticks), the four session digests equal v2, v3 and v4 at sd1's reference recomputed, the inherited record facts equal the registered ones, both overlays reproduce their pinned
    digests, zero inherited descriptive candidates, the record candidate's 2,086 words."""
    if not REAL_TREES:
        return {"skipped": "the closed real trees are not present"}
    check(all(p.is_dir() for p in (ses6.INCREMENT_RD1, ses6.INCREMENT_RD2, ses6.INCREMENT_RD3, ses6.INCREMENT_RD4, ses6.INCREMENT_SD1)), "the five D: increments are required")
    op = ses6.open_protocol6(record_reference=ses6.RECORD_REFERENCE, previous_record_reference=ses6.PREVIOUS_RECORD_REFERENCE)
    check(op["ok"], f"the open protocol on the real trees: {op['problems']}")
    r1 = {w: op[f"R1_{w}_immutability"] for w in ("rd1", "rd2", "rd3", "rd4", "sd1")}
    check(r1["rd1"]["files"] == 166 and r1["rd2"]["files"] == 62 and r1["rd3"]["files"] == 77 and r1["rd4"]["files"] == 93 and r1["sd1"]["files"] == 130 and r1["sd1"]["bytes"] == 211_061_918
          and r1["sd1"]["manifest_sha256"] == r6.SD1_INCREMENT_MANIFEST_SHA256 and r1["rd4"]["manifest_sha256"] == r5.RD4_INCREMENT_MANIFEST_SHA256, f"R1: { {k: (v['files'], v['bytes']) for k, v in r1.items()} }")
    f5 = op["R2_R4_sd1_archive"]
    check(f5["counts"] == {"cells": 44007, "bursts": 17554, "events": 35118} and f5["dispatch_iterations"] == [0, 17556] and f5["first_sd2_iteration"] == 17557 and f5["sd1_checkpoint_seq"] == 57
          and f5["audit"]["ok"] and f5["audit"]["cells"] == 44007, f"R2/R4 (sd1): { {k: f5[k] for k in ('counts', 'dispatch_iterations', 'first_sd2_iteration', 'sd1_checkpoint_seq')} }")
    check([e["name"] for e in f5["session_events"]] == ["rd2", "rd3", "rd4", "sd1"] and f5["session_events"][3]["digest"] == f5["digest_recomputed"]["v4_sd1"] == r6.SD1_SESSION_DIGEST
          and f5["digest_recomputed"]["v3"].startswith("fd69a0332de9db28"), "sd1's session digest equals v4 at sd1's reference recomputed")
    check(f5["record_reference"] == ses6.RECORD_REFERENCE and f5["sd1_line"]["status"] == "SD2_PROPOSABLE_NEW_REFERENCE" and f5["sd1_line"]["session_counts"] is True and f5["sd1_line"]["rd5_permitted"] is True,
          "the record reference and the lines")
    f4 = op["R2_R4_rd4_archive"]
    check(f4["counts"] == {"cells": 37312, "bursts": 13886, "events": 27775} and f4["audit"]["ok"], "R2/R4 (rd4) through sd1's protocol")
    check(op["R3_pins"]["contract_keys"] == {"rd1": 6, "rd2": 7, "rd3": 7, "rd4": 8, "sd1": 9}, f"each session's own contract set: {op['R3_pins']['contract_keys']}")
    ov = op["R5_overlay"]
    check(ov["ok"] and ov["sd1_closing_sha256"] == r6.SD1_CLOSING_OVERLAY_V4_SHA256 and ov["v4_sha256"] == r6.SD2_OPEN_OVERLAY_SHA256 and ov["v4_counts"]["eligible_v4"] == 24599
          and ov["v4_counts"]["record_bound_cells"] == 4697 and ov["v4_counts"]["record_bound_among_v3_eligible"] == 3242 and ov["sd1_closing_counts"]["eligible_v4"] == 27603,
          f"R5: both overlays reproduce their pinned digests: {ov['v4_counts']['eligible_v4']} {ov['v4_counts']['record_bound_cells']}")
    rl5 = op["rd_levels"]["R5_overlay"]
    check(rl5["v4_sha256"] == r5.SD1_OPEN_OVERLAY_SHA256 and rl5["rd4_closing_sha256"] == r5.RD4_CLOSING_OVERLAY_SHA256, "sd1's own open overlay of rd4's archive is reproduced too (sd1's inputs unchanged)")
    check(op["inherited"] == [] and op["inherited_ticks"] == 0 and len(op["record_candidate"]["words"]) == 2086 and op["record_candidate"]["pred_cid"] == 901, "zero inherited candidates; the record")
    return {"v4_overlay": ov["v4_sha256"][:12], "sd1_closing": ov["sd1_closing_sha256"][:12]}


def unit_write_guard_all_runs_roots6() -> Dict[str, Any]:
    t = tmpdir("m8wg6_")
    runs = t / "runs"
    names = ("m8_rd", "m8_rd_rd2", "m8_rd_rd3", "m8_rd_rd4", "m8_rd_sd1", "m9_g1", "m9_g3", "m7u")
    for n in names + ("m8_rd_sd2",):
        (runs / n).mkdir(parents=True)
        (runs / n / "f.txt").write_text("x", encoding="utf-8")
    own = runs / "m8_rd_sd2"
    roots = ses6.protected_runs_roots(runs, own)
    check([r.name for r in roots] == sorted(names), f"every tree under runs/ but sd2's own: {[r.name for r in roots]}")
    mw.ProvenanceGuard.install()
    w2.WriteGuard.install(roots)
    base = len(mw.ProvenanceGuard.violations)
    try:
        (own / "o.txt").write_text("z", encoding="utf-8")
        for r in roots:
            open(r / "f.txt", "rb").close()
        check(len(mw.ProvenanceGuard.violations) == base, "reads of the other trees and writes under sd2's own root are not violations")
        for r in roots:
            before = len(mw.ProvenanceGuard.violations)
            (r / "w.txt").write_text("a", encoding="utf-8")
            check(len(mw.ProvenanceGuard.violations) > before, f"the write guard missed a write under {r.name}")
            before = len(mw.ProvenanceGuard.violations)
            shutil.copyfile(own / "o.txt", r / "c.txt")
            check(len(mw.ProvenanceGuard.violations) > before, f"the write guard missed a copy into {r.name}")
    finally:
        w2.WriteGuard.clear()
        del mw.ProvenanceGuard.violations[base:]
        shutil.rmtree(t, ignore_errors=True)
    saved = ses5.ses2.build_real_env2
    try:
        ses5.ses2.build_real_env2 = lambda *a, **k: mrun.RunEnv(worker_spec=lambda rank, c: {"rank": rank}, replay=lambda *x: {}, analyse=lambda *x: {}, p1_inputs=lambda: [], pins={})
        spec = ses6.build_real_env6(ses6.run_config(), Path("x"), {}, {}, protected=[Path("a"), Path("b")]).worker_spec(0, ses6.run_config())
    finally:
        ses5.ses2.build_real_env2 = saved
    check(spec["protected_roots"] == ["a", "b"], f"the worker spec protects the given roots: {spec['protected_roots']}")
    real = ses6.protected_runs_roots()
    check(ses6.SD2_ROOT not in real and all(p.parent == ses6.RUNS for p in real) and (not REAL_TREES or ses6.SD1_ROOT in real), "the production roots are every tree under runs/ but sd2's (sd1's among them)")
    return {"roots": len(roots), "production_roots": len(real)}


# -- the claims plan --------------------------------------------------------------------------------------------------------------------------------------


def unit_claims6_pool_and_plan() -> Dict[str, Any]:
    check(cl6.BATCH == 3 and cl6.CLAIMS6_CONTRACT == "m8_sd2_claims_v1" and cl6.PREDECESSOR == "sd1" and len(cl6.contract_digest()) == 64 and cl6.contract_digest() != cl5.contract_digest(),
          "registered constants and digest")
    check(cl6.pool5 is cl5.pool5 and cl6.plan_replays5 is cl5.plan_replays5 and cl6.exactness5 is cl5.exactness5 and cl6.verified_clear_record is cl5.verified_clear_record and cl6.plan_inherited5 is cl5.plan_inherited5,
          "the plan is sd1's, unchanged")
    live = {"first": {"left_live": 31}}
    specs = [live] * 200 + [t5.clear_spec(59), t5.clear_spec(40), t5.clear_spec(55), t5.clear_spec(40), t5.clear_spec(58), {"first": {"l0": 31}}, {"first": {"left_live": 31}, "t": 7, "t_events": [(40, 7)]}]
    led = t4.ledger_with(specs)
    T = led.ticks
    pool = cl6.pool5(led, T, 60)
    check([cl6.clear_tick(c) for c, _n in pool] == [40, 40, 55, 58, 59] and [cl6.clear_tick(c) for c, _n in cl6.progress_pool5(led, T, 60, 5)] == [40, 40, 55], "the pool at the reference, the margin cuts the progress pool")
    todo, info = cl6.plan_replays5(led, T, {}, 60, 5, batch=3)
    check([cl6.clear_tick(c) for c, _n in todo] == [40, 40, 55] and info["pool"] == 5 and not info["closed"], "the first batch: the three fastest clears")
    ps = cl6.pool_sizes5(led, T, 2086, 24)
    check(ps["t_rec"] == 2086 and ps["margin"] == 24 and ps["pool"] == 5 and ps["left"] == 206, f"pool sizes at the real reference: {ps}")
    # the predecessor's registry files: a stamped header row and inherited replay rows are skipped by the readers
    t = tmpdir("m8cl6_")
    sd = t / "pred" / "sessions" / "sd1" / "verification"
    sd.mkdir(parents=True)
    rows = [art.header_row("m8_sd1_replays_v1"), {"cid": 901, "exact": True, "clear": True, "kind": "clear", "counted": 10, "clear_facts": {"completion_input_tick": 10, "completion_time_passed": 9}},
            {"cid": 100849, "exact": True, "clear": True, "kind": "clear", "inherited": True, "counted": 12}, {"cid": 7, "exact": False, "clear": False, "kind": "left"}]
    (sd / "replays.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    own = cl6.predecessor_replays(t / "pred", "sd1")
    check([r["cid"] for r in own] == [901, 7] and [r["cid"] for r in cl6.predecessor_replays(t / "pred", "sd1", include_inherited=True)] == [901, 100849, 7], "the header row and the inherited rows are skipped")
    with gzip.open(t / "pred" / "sessions" / "sd1" / "candidates_T.jsonl.gz", "wt", encoding="utf-8") as f:
        f.write(json.dumps(art.header_row("m8_sd1_candidates_v1")) + "\n")
        f.write(json.dumps({"cid": 901, "kind": "clear", "words_hex": bytes(range(10)).hex()}) + "\n")
    w = cl6.registry_words(t / "pred", "sd1")
    check(w == {901: bytes(range(10))}, "the header row of the candidates file is skipped")
    shutil.rmtree(t, ignore_errors=True)
    chain = build_chain6()
    tr = cl6.clear_trajectories6(chain["sd1"])
    unv = cl6.inherited_unverified_clears6(chain["sd1"])
    check(tr["predecessor"] == "sd1" and len(tr["jobs"]) >= 1 and tr["replays_exact_clear"] >= 1 and all("verified_by_predecessor" in j for j in tr["jobs"]), "the synthetic sd1 registry's trajectories")
    check([c["iteration"] for c in unv] == [j["iteration"] for j in tr["jobs"] if not j["verified_by_predecessor"]] and all(c["pred_session"] == "sd1" and c["inherited"] and c["cid"] >= cl6.INHERITED_CID_BASE for c in unv),
          "the unverified trajectories by the rule, fastest first")
    out = {"synthetic_unverified": len(unv)}
    if REAL_TREES:
        tr_real = cl6.clear_trajectories6(SD1_REAL)
        check([(j["iteration"], j["first_clear"], j["cids"], j["verified_by_predecessor"]) for j in tr_real["jobs"]] == [(15795, 2086, [900, 901], [901])] and tr_real["replays_exact_clear"] == 1,
              f"sd1's registry: one clear trajectory, verified by sd1: {tr_real['jobs']}")
        check(cl6.inherited_unverified_clears6(SD1_REAL) == [] and cl6.inherited_ticks([]) == 0, "zero inherited descriptive candidates on the real tree")
        check(all(j["iteration"] not in (12559, 12823, 12146) for j in tr_real["jobs"]), "rd4's three trajectories are not in sd1's registry: they are not replayed again")
        check([r["cid"] for r in cl6.predecessor_replays(SD1_REAL)] == [901] and len(cl6.predecessor_replays(SD1_REAL, include_inherited=True)) == 4, "sd1's own replay rows: one; with the inherited ones: four")
        out["real_trajectories"] = len(tr_real["jobs"])
    return out


def unit_clear_exactness6_on_stub_traces() -> Dict[str, Any]:
    """The record of the synthetic sd1 replayed through the stub world: exact, the four facts, the clock equal to the registered clear tick; and every way it can fail."""
    chain = build_chain6()
    rr = chain["expect5"]["inherited_record"]["best_verified"]
    cand = cl6.record_candidate6(chain["sd1"], rr)
    n = len(cand["words"])
    tr = stub.replay_trace(chain["world"], cand["words"])
    rep = mclaims.evaluate_replay(tr, cand, n, stub.analyse)
    check(rep["exact"] and rep["clear"] and cl6.exactness5(rep, cand) == [] and rep["clear_facts"]["completion_input_tick"] == rr["completion_input_tick"] == cl6.clear_tick(cand), f"the record replays exactly: {rep['problems']} {rep['clear_facts']}")
    check(cl6.exactness5(rep, dict(cand, first={"clear": rr["completion_input_tick"] + 1})) != [], "a registered clear tick that differs from the replay's clock is refused")
    rep_cut = mclaims.evaluate_replay(stub.replay_trace(chain["world"], cand["words"][:n - 1]), cand, n - 1, stub.analyse)
    check(rep_cut["exact"] and not rep_cut["clear"] and any("counted words" in p for p in cl6.exactness5(rep_cut, cand)), "one word short: exact over the counted words, not a clear claim")
    bad_words = bytes([(cand["words"][0] + 1) % 72]) + cand["words"][1:]
    rep_bad = mclaims.evaluate_replay(stub.replay_trace(chain["world"], bad_words), cand, n, stub.analyse)
    check(not rep_bad["exact"], "different words: inexact")
    inh = cl6.inherited_unverified_clears6(chain["sd1"])
    for c in inh:
        r = mclaims.evaluate_replay(stub.replay_trace(chain["world"], c["words"]), c, len(c["words"]), stub.analyse)
        irec = cl6.inherited_record6(r, c)
        check(irec["exact"] and irec["reported_only"] and irec["completion_input_tick"] == cl6.clear_tick(c) and irec["pred_cid"] == c["pred_cid"] and irec["pred_session"] == "sd1", f"an inherited trajectory replays exactly in the synthetic world: {irec}")
    bad_rec = cl6.inherited_record6({"exact": False, "problems": ["replay failed: x"], "clear": False, "clear_facts": {}, "counted": 0}, inh[0] if inh else dict(cand, pred_cid=1, pred_session="sd1"))
    check(not bad_rec["exact"] and bad_rec["reported_only"] and bad_rec["problems"], "an inexact inherited replay is a reported fact (flagged by the rule, never INVALID)")
    return {"record_words": n, "inherited": len(inh)}


def unit_inherited_descriptive_candidates6() -> Dict[str, Any]:
    src = (RL_DIR / "m8_sd2_claims.py").read_text(encoding="utf-8")
    for tok in ("901", "900", "15795", "2086", "2085", "849", "979", "656", "12559", "12823", "12146", "2324", "2341", "2348"):
        check(re.search(rf"(?<![0-9]){tok}(?![0-9])", src) is None, f"the claims module names the candidate or clock {tok}: the set must come from the registry by the rule")
    chain = build_chain6()
    tr = cl6.clear_trajectories6(chain["sd1"])
    inh = cl6.inherited_unverified_clears6(chain["sd1"])
    want = [j for j in tr["jobs"] if not j["verified_by_predecessor"]]
    check([c["iteration"] for c in inh] == [j["iteration"] for j in want] and all(c["kind"] == "clear" and len(c["words"]) == cl6.clear_tick(c) for c in inh), "the synthetic sd1's unverified clear trajectories, by the rule, fastest first")
    todo = cl6.plan_inherited5(inh, {}, batch=3)
    check([c["cid"] for c, _n in todo] == [c["cid"] for c in inh[:3]] and all(n == len(c["words"]) for c, n in todo) and cl6.plan_inherited5(inh, {c["cid"]: {} for c in inh}, batch=3) == [],
          "planned fastest first, each over its whole trajectory; nothing once all are replayed")
    out = {"synthetic_unverified": len(inh)}
    if REAL_TREES:
        check(cl6.inherited_unverified_clears6(SD1_REAL) == [], "the real registry: zero unverified clear trajectories")
        rc = cl6.record_candidate6(SD1_REAL, ses6.RECORD_REFERENCE)
        pace = rpt6.record_pace(rc)
        check(len(rc["words"]) == 2086 and mcell.words_digest(rc["words"]) == ses6.RECORD_REFERENCE["native_action_digest"] and rc["pred_cid"] == 901 and rc["pred_session"] == "sd1" and pace["10"] == 2086
              and len(pace) == 10 and pace["9"] < pace["10"], "the record candidate: 2,086 words hashing to the pinned digest; its pace is its own break table")
        raises(ValueError, lambda: cl6.record_candidate6(SD1_REAL, dict(ses6.RECORD_REFERENCE, cid=900, kind="left")), "a reference that names the left twin is refused")
        raises(ValueError, lambda: cl6.record_candidate6(SD1_REAL, dict(ses6.RECORD_REFERENCE, native_action_digest="0" * 64)), "a reference whose digest the words do not reproduce is refused")
        cap = ses6.caps()
        check(16 * mcell.HORIZON + 10 * 2086 <= cap["replay_tick_cap"], "16 identity replays and ten clear replays fit the verification cap")
        out["real_unverified"] = 0
    return out


# -- the rule and the session ------------------------------------------------------------------------------------------------------------------------------


def unit_rule6_module() -> Dict[str, Any]:
    check(rule6.self_test() == [], f"the rule's self-test: {rule6.self_test()}")
    d = rule6.rule_digest()
    check(d == rule6.rule_digest() and len(d) == 64 and d != rule5.rule_digest(), "the rule digest")
    desc = rule6.rule_description()
    check(desc["order"] == ["INVALID", "INCOMPLETE", "PROGRESS", "RECORD_BELOW_MARGIN", "NO_SHORTER_CLEAR"] and desc["control_arm"] is False and desc["mechanism_check"] == "none" and set(desc["stops"]) == {"S3", "S5", "S7"}
          and desc["predecessor"] == "sd1" and desc["line_statuses"] == list(rule6.LINE_STATUSES), "no control arm, no mechanism check, three carried stops, five outcomes, five line statuses")
    check(rule6.T_REC == 2086 and rule6.T_REC_TIME_PASSED == 2085 and rule6.MARGIN == 24 and rule6.PROGRESS_BAR == 2062 and rule6.TIERS["5_percent"] == 1981 and rule6.TIERS["10_percent"] == 1877
          and rule6.TIERS["round_1800"] == 1800 and rule6.TIER_ROUND_KEY == "round_1800", "the registered constants and tiers")
    check(rule6.TIERS["5_percent"] == math.floor(0.95 * 2086) and rule6.TIERS["10_percent"] == math.floor(0.90 * 2086), "the tiers derive from the reference alone")
    check(list(inspect.signature(rule6.outcome_of).parameters) == ["best_completion_input_tick", "t_rec", "margin"] and "tier" not in inspect.getsource(rule6.outcome_of).lower(), "outcome_of reads no tier")
    check(rule6.MIN_EXPLORATION_TICKS == 2_000_000 and rule6.MAX_LIFECYCLE_FAILURES == 3 and rule6.TOP_LEVEL_MEDIAN_L_LIMIT == 3000, "the carried-over limits")
    sd1_line = {"status": "SD2_PROPOSABLE_NEW_REFERENCE", "session_counts": True, "rd5_permitted": True, "source": "sessions/sd1/rule.json"}
    ls = rule6.line_status(outcome="INCOMPLETE", exploration_started=False, exploration_ticks=0, best=None, sd1_line=sd1_line)
    check(ls["status"] == "NOT_STARTED" and ls["session_counts"] is False and "logs/m8_sd2_run_not_started_" in ls["sd3"] and ls["rd_line"]["rd5_permitted_after_sd2"] is True and ls["sd_line"]["sd1_status"] == "SD2_PROPOSABLE_NEW_REFERENCE",
          f"NOT_STARTED carries the repeat procedure and the copied lines: {ls}")
    return {"rule_digest": d[:12]}


def unit_decide6_outcomes_and_stops() -> Dict[str, Any]:
    chain = build_chain6()
    rr = chain["expect5"]["inherited_record"]["best_verified"]
    t_rec = rr["completion_input_tick"]
    res: Dict[str, Any] = {}
    out, sess, _r, cp = run6_small(chain, arm_tick_cap=3000, min_arm_ticks=5000)
    r = out["rule"]
    check(r["outcome"] == "INCOMPLETE" and any("reached 3,000" in x for x in r["incomplete"]) and r["stops"]["S7"]["triggered"] and "S7" in r["any_stop"] and "S3" not in r["any_stop"], f"below the minimum: {r['incomplete']} {r['any_stop']}")
    check(r["line"]["status"] == "COUNTED_INCOMPLETE" and r["line"]["session_counts"] is True and r["exploration_started"] is True and r["line"]["sd_line"]["sd1_status"] == chain["expect5"]["line_status"],
          f"an INCOMPLETE session counts once exploration has started; sd1's line copied: {r['line']}")
    res["below_minimum"] = r["outcome"]
    out, sess, _r, cp = run6_small(chain, inject={"lifecycle_jobs": [10]}, n_workers=2, arm_tick_cap=8000, min_arm_ticks=1000)
    check(1 <= sess.lifecycle_failures["T"] <= 3 and sess.ledgers["T"].ticks == 8000 and out["rule"]["outcome"] != "INCOMPLETE", f"redrawn lifecycle failures {sess.lifecycle_failures}: {out['rule']['outcome']} {out['rule']['incomplete']}")
    check(any(e["ev"] == "fail" for e in sess.archive.events) and s6.audit6(sess.archive, chain["lines"])["ok"], "the ledger records the failed iteration and still audits")
    out, sess, _r, cp = run6_small(chain, inject={"lifecycle_jobs": [10, 11, 12, 13]}, n_workers=2, arm_tick_cap=12000, min_arm_ticks=1000)
    check(out["rule"]["outcome"] == "INCOMPLETE" and any("lifecycle failures" in x for x in out["rule"]["incomplete"]), f"more than three: {out['rule']['incomplete']}")
    out, sess, _r, cp = run6_small(chain, inject={"mismatch_job": 14, "mismatch_tick": 5}, n_workers=2, arm_tick_cap=20000, min_arm_ticks=1000)
    r = out["rule"]
    check(r["outcome"] == "INVALID" and any("prefix_end" in x for x in r["invalid"]) and r["line"]["status"] == "REPAIR_NEEDED" and r["line"]["session_counts"] is None, f"an integrity mismatch: {r['invalid']} {r['line']}")
    check(list((sess.cfg.session_dir / "failures").glob("iterate_*")), "the failed return's raw replies are preserved")
    res["mismatch"] = r["outcome"]
    out, sess, _r, cp = run6_small(chain, inject={"provenance_job": 10}, n_workers=2, arm_tick_cap=5000, min_arm_ticks=1000)
    check(out["rule"]["outcome"] == "INVALID" and any("provenance" in x or "guard violations" in x for x in out["rule"]["invalid"]), f"a provenance violation: {out['rule']['invalid']}")
    out, sess, _r, cp = run6_small(chain, arm_tick_cap=3000, min_arm_ticks=1000, immutability=lambda: {"ok": False, "problems": ["sd1: cells.jsonl differs"]})
    check(out["rule"]["outcome"] == "INVALID" and any("an earlier tree changed" in x for x in out["rule"]["invalid"]), f"a changed earlier tree: {out['rule']['invalid']}")
    for victim in ("rd1", "rd2", "rd3", "rd4", "sd1"):
        def writer(cp_: Mapping[str, Any], _clock: FakeClock, victim: str = victim) -> Mapping[str, Any]:
            done: List[int] = []

            def private_mb() -> float:
                if not done:
                    done.append(1)
                    (Path(cp_[victim]) / "archive" / "stray.txt").write_text("x", encoding="utf-8")
                return 100.0

            return {"private_mb": private_mb}

        out, sess, _r, cp = run6_small(chain, n_workers=2, arm_tick_cap=400000, min_arm_ticks=100, env_kw_factory=writer)
        check(out["rule"]["outcome"] == "INVALID" and any("protected root" in x for x in out["rule"]["invalid"]), f"a write under {victim}'s tree: {out['rule']['outcome']} {out['rule']['invalid']}")
        res[f"{victim}_write"] = out["rule"]["outcome"]

    def broken() -> Mapping[str, Any]:
        raise RuntimeError("injected immutability failure")

    out, sess, _r, cp = run6_small(chain, arm_tick_cap=3000, min_arm_ticks=1000, immutability=broken)
    cl = out["close"]
    check(out["rule"]["outcome"] == "INCOMPLETE" and any("earlier_trees_immutability could not run" in x for x in out["rule"]["incomplete"]) and "earlier_trees_immutability_error" in cl and cl["audit"]["ok"] and cl["prefix_chain"]["ok"],
          f"an erroring close check: {out['rule']['incomplete']}")

    class LateBreach:
        def __init__(self, clock: FakeClock) -> None:
            self.clock, self.t0 = clock, clock.now()

        @property
        def breach(self) -> Optional[str]:
            return "memory cap: process tree private 99999 MB > 9216 MB" if self.clock.now() - self.t0 > 2.5 else None

    out, sess, _r, cp = run6_small(chain, env_kw_factory=lambda cp_, clock_: {"sampler": LateBreach(clock_)}, n_workers=2, arm_tick_cap=10 ** 7, min_arm_ticks=1000)
    check(out["rule"]["outcome"] == "INCOMPLETE" and any("memory cap" in x for x in out["rule"]["incomplete"]), f"a memory breach: {out['rule']['incomplete']}")
    out, sess, _r, cp = run6_small(chain, env_kw={"tree_snapshot": lambda: {"battleship": 11}}, n_workers=2, arm_tick_cap=10 ** 6, min_arm_ticks=1000, process_check_every_s=0.05)
    check(out["rule"]["outcome"] == "INCOMPLETE" and any("11 BattleShip processes" in x for x in out["rule"]["incomplete"]), f"a process-count breach: {out['rule']['incomplete']}")
    out, sess, _r, cp = run6_small(chain, n_workers=2, arm_tick_cap=10 ** 7, min_arm_ticks=500, wall_caps_s={"p1": 90.0, "T": 2.0, "C": 0.0, "verify": 300.0}, global_cap_s=900.0)
    tT = sess.ledgers["T"].ticks
    check(sess.arm_records["T"]["stop"][0] == "wall_cap" and 500 <= tT < 10 ** 7 and not out["rule"]["incomplete"], f"a wall-capped exploration at or above the minimum is valid ({tT}): {out['rule']['incomplete']}")
    out, sess, _r, cp = run6_small(chain, replay_tick_cap=150, arm_tick_cap=12000, min_arm_ticks=2000, identity_k=0)
    ver = json.loads((sess.cfg.session_dir / "verification.json").read_text(encoding="utf-8"))
    check(ver["cap_hit"] is not None, "the replay cap was hit")
    if out["rule"]["outcome"] == "INCOMPLETE":
        check(any("pool candidate" in x for x in out["rule"]["incomplete"]) and ver["arm"]["best_verified"] is None and ver["arm"]["remaining_progress"] > 0, f"INCOMPLETE only with a progress candidate left unverified: {out['rule']['incomplete']}")
    else:
        check(ver["arm"]["remaining_progress"] == 0 or ver["arm"]["best_verified"] is not None, "a cap that cannot change the outcome is not INCOMPLETE")
    res["replay_cap"] = out["rule"]["outcome"]
    # every outcome through decide6 on a complete session, with constructed verified clears (the rule reads their clocks)
    out, sess, root6, cp = run6_small(chain, arm_tick_cap=6000, min_arm_ticks=2000)
    check(not out["rule"]["invalid"] and not out["rule"]["incomplete"], f"a complete small session: {out['rule']['outcome']}")
    loaded, _m = s6.Archive6.read_dir(root6 / "archive")
    rows = s6.audit6(loaded, chain["lines"], collect_rows_from=sess.first_iteration)["dispatch_rows"]
    mkv = lambda c, cid=1: {"cid": cid, "iteration": 1, "kind": "clear", "completion_input_tick": c, "completion_time_passed": c - 1, "native_action_digest": "b" * 64, "words": c, "registered_clear_tick": c}   # noqa: E731
    for clears, want, status in (([], "NO_SHORTER_CLEAR", "SD3_AFTER_REVIEW_WITH_REASON"), ([mkv(t_rec - 24)], "PROGRESS", "SD3_AFTER_REVIEW_NEW_REFERENCE"), ([mkv(t_rec - 23)], "RECORD_BELOW_MARGIN", "SD3_AFTER_REVIEW_NEW_REFERENCE"),
                                 ([mkv(t_rec - 1)], "RECORD_BELOW_MARGIN", "SD3_AFTER_REVIEW_NEW_REFERENCE"), ([mkv(t_rec)], "NO_SHORTER_CLEAR", "SD3_AFTER_REVIEW_WITH_REASON"),
                                 ([mkv(t_rec - 30, 7), mkv(t_rec - 60, 3), mkv(t_rec - 60, 2)], "PROGRESS", "SD3_AFTER_REVIEW_NEW_REFERENCE")):
        sess.invalid, sess.incomplete = [], []
        sess.verified = {"verified_clears": clears, "max_targets": 10 if clears else 0}
        rec = run6.decide6(sess, loaded, rows)
        check(rec["outcome"] == want and rec["line"]["status"] == status and rec["record_reference"]["completion_input_tick"] == t_rec and rec["margin"] == 24, f"decide6 with {[c['completion_input_tick'] for c in clears]}: {rec['outcome']} vs {want}")
        if clears:
            check(rec["best_verified"]["cid"] == min(clears, key=lambda c: (c["completion_input_tick"], c["cid"]))["cid"], "the best verified clear")
        check(rec["line"]["rd_line"]["rd5_permitted_after_sd2"] is True and rec["line"]["rd_line"]["consumed_by_sd2"] is False and rec["line"]["sd_line"]["sd1_session_counts"] is True
              and rec["line"]["review_required_before_sd3"] is True, "rd5 unchanged; sd1's line copied; the review requirement")
        check(rec["mechanism_check"] is None and rec["dilution"]["reported_only"] and rec["tiers"]["reported_only"] and rec["extra"]["previous_record_reference"] == chain["expect5"]["sd1_record_reference"],
              "no mechanism check; dilution and tiers reported only; the previous reference recorded")
    res["decide6"] = "ok"
    shutil.rmtree(cp["t"], ignore_errors=True)
    return res


def unit_session6_small_run() -> Dict[str, Any]:
    chain = build_chain6()
    e5 = chain["expect5"]
    rr = e5["inherited_record"]["best_verified"]
    out, sess, root, cp = run6_small(chain)
    rule, close = out["rule"], out["close"]
    check(not rule["invalid"] and not rule["incomplete"] and rule["outcome"] in ("PROGRESS", "RECORD_BELOW_MARGIN", "NO_SHORTER_CLEAR"), f"a complete small session: {rule['outcome']} {rule['invalid']} {rule['incomplete']}")
    check(sess.ledgers["T"].ticks == 12000, f"the exploration committed exactly its cap: {sess.ledgers['T'].ticks}")
    sd = sess.cfg.session_dir
    for f in ("p1.json", "identity_open.json", "record_open.json", "arm_T.json", "verification.json", "rule.json", "close.json", "state.json", "iterations_T.jsonl", "ledger_T.json", "candidates_T.jsonl.gz",
              "dispatch_rows.jsonl.gz", "wall_top_sightings.jsonl"):
        check((sd / f).is_file(), f"missing {f}")
    for f in ("p1.json", "identity_open.json", "record_open.json", "arm_T.json", "verification.json", "rule.json", "close.json", "state.json", "ledger_T.json"):
        rec = json.loads((sd / f).read_text(encoding="utf-8"))
        check(art.is_stamped(rec) and rec.get("scope", rule6.SCOPE) == rule6.SCOPE, f"{f} is stamped and carries sd2's scope")
    for f in ("iterations_T.jsonl", "candidates_T.jsonl.gz", "dispatch_rows.jsonl.gz", "wall_top_sightings.jsonl", "verification/replays.jsonl"):
        h, _rows = art.read_jsonl5(sd / f)
        check(h is not None and h["schema"].startswith("m8_sd2_"), f"{f} opens with its stamped header row (sd2's schema)")
    arts = art.audit_tree6(root)
    check(arts["ok"] and arts["files"] > 10 and arts["headers"] >= 5, f"every record of the tree carries its stamp: {arts['failures']}")
    check(close["artifacts"]["ok"] and close["archive"]["created_utc"] == OPEN_UTC, "the close checks audited the stamps; archive_meta keeps the materialisation time")
    for d in ("archive", "archive.prev"):
        m = json.loads((root / d / "archive_meta.json").read_text(encoding="utf-8"))
        check(m["created_utc"] == OPEN_UTC and art.is_stamped(m) and m["session"] in ("sd2",) and m["sd2_first_iteration"] == e5["first_sd2_iteration"], f"{d}/archive_meta.json keeps created_utc across checkpoints and names sd2")
    p1 = json.loads((sd / "p1.json").read_text(encoding="utf-8"))
    check(p1["tick0"]["equals_archive_pin"] and p1["selftest"]["corrupted_refused"] and len(p1["traces"]) == 2, "P1 against the archive's pin")
    io_ = json.loads((sd / "identity_open.json").read_text(encoding="utf-8"))
    check(io_["ok"] and io_["cells"] == 6 and io_["verified"] == 6, f"open identity replays: {io_}")
    ro = json.loads((sd / "record_open.json").read_text(encoding="utf-8"))
    check(ro["exact"] and ro["words"] == rr["words"] and ro["clear_facts"]["completion_input_tick"] == rr["completion_input_tick"] and ro["native_action_digest"] == rr["native_action_digest"], f"the record (sd1's clear) re-verified at the open: {ro}")
    ver = json.loads((sd / "verification.json").read_text(encoding="utf-8"))
    arm = ver["arm"]
    check(ver["identity"]["ok"] and ver["identity"]["verified"] == ver["identity"]["cells"] == 6 and ver["claims_digest"] == cl6.contract_digest() and ver["record_reference"] == rr and ver["margin"] == 24, "the verification record")
    led = sess.ledgers["T"]
    ticks_of = {c["cid"]: cl6.clear_tick(c) for c in led.candidates}
    order = arm["replay_order"]
    check(order == sorted(order, key=lambda cid: (ticks_of[cid], cid)) and all(led.candidates[cid]["kind"] == "clear" for cid in order), f"the pool was replayed fastest first, clear-kind only: {order}")
    check((arm["best_verified"] is not None) == arm["closed"] and arm["remaining_faster_than_best"] == 0, "the pool closes at the first exact replay")
    if arm["best_verified"]:
        b = arm["best_verified"]
        check(b["completion_input_tick"] == min(v["completion_input_tick"] for v in arm["verified_clears"]) and rule["outcome"] == rule6.outcome_of(b["completion_input_tick"], rr["completion_input_tick"], 24), "the best and the outcome")
        check((root / "routes" / "T_clear_best" / "metadata.json").is_file() and json.loads((root / "routes" / "T_clear_best" / "metadata.json").read_text(encoding="utf-8"))["completion_clocks"]["completion_input_tick"] == b["completion_input_tick"], "the best route is saved with its clocks")
    inh = ver["inherited_descriptive"]
    check(inh["count"] == len(sess.inherited) == len(e5["inherited_record"]["unverified_clear_trajectories"]) and inh["replayed"] == inh["count"] and inh["exact"] == inh["count"] and rule["flags"] == []
          and rule["inherited_descriptive"]["count"] == inh["count"] and "sd1's registry" in inh["rule"], f"the inherited descriptive replays (the rule's count on the synthetic registry), exact, reported: {inh}")
    for c in sess.inherited:
        check((root / "routes" / f"sd1_inherited_c{c['pred_cid']:04d}" / "metadata.json").is_file(), "an exact inherited replay is saved as a route named after the predecessor")
    check(close["audit"]["ok"] and close["prefix_chain"]["ok"] and close["prefix_chain"]["sd1_sd2"]["ok"] and close["earlier_trees_immutability"]["ok"] and not close["guard_violations"]
          and set(close["earlier_trees_immutability"]) >= {"rd1", "rd2", "rd3", "rd4", "sd1"}, f"close checks: {close.get('audit')} {close.get('prefix_chain', {}).get('ok')}")
    check(close["archive"]["checkpoint_seq"] == sess.ckpt_seq and sess.ckpt_seq > e5["checkpoint_seq"] + 1 and "overlay_close_v4" in close["archive"] and "overlay_close_v4_previous_bound" in close["archive"]
          and close["archive"]["overlay_close_v4"]["bound_L"] == rr["completion_input_tick"] - 25 and close["archive"]["overlay_close_v4_previous_bound"]["bound_L"] == e5["sd1_record_reference"]["completion_input_tick"] - 25,
          "the checkpoint sequence continues from sd1's; the v4 overlay at both bounds at the close")
    first = e5["dispatch_iterations"][1] + 1
    check(sess.first_iteration == first and sess.archive.sd2_first_iteration == first, "iterations continue after sd1's")
    its = [e["it"] for e in sess.archive.events if e["ev"] == "dispatch"]
    own = [i for i in its if i >= first]
    check(its == sorted(set(its)) and its[0] == 0 and own == list(range(first, first + len(own))) and len(own) > 0, "dispatch iterations are strictly increasing, never reused, and sd2's part is contiguous from its first")
    rows = art.rows_of(sd / "iterations_T.jsonl")
    check(sum(r["ticks"] for r in rows if "ticks" in r) == 12000 and all(r["tick0_equal"] for r in rows if "ticks" in r), "iteration rows add up; tick 0 equal everywhere")
    a = sess.archive
    bound = a.bound_max_L()
    for e in a.events:
        if e["ev"] == "dispatch" and e["it"] >= first:
            check(e["cell"] == 0 or e["L"] <= bound, f"an sd2 dispatch from a cell beyond the record bound: iteration {e['it']} L {e['L']}")
    aid = a.archive_id
    for b in a.bursts:
        draw = {"rd1": aid, "rd2": aid + "_v2", "rd3": aid + "_rd3", "rd4": aid + "_rd4", "sd1": aid + "_sd1", "sd2": aid + "_sd2"}[a.session_of_iteration(b.iteration)]
        want = bytes(w for _i, w in zip(range(len(b.words)), mx.words(lambda i, d=draw, it=b.iteration: mx.explore_key(d, it, i), mx.BURST_WORDS)))
        check(b.words == want, f"burst {b.id} (iteration {b.iteration}): the words are not the {draw} keyed stream")
    rep = rpt6.full_report6(root, cp["sd1"], cp["rd4"], cp["rd3"], cp["rd2"], cp["rd1"], "sd2")
    n_disp = sum(1 for e in a.events if e["ev"] == "dispatch" and e["it"] >= first)
    check(rep["sd2"]["dispatches"] == n_disp and rep["sd1_reference"]["dispatches"] == e5["returns"] and rep["record_reference"] == rr and rep["previous_record_reference"] == e5["sd1_record_reference"],
          "the report counts sd2's dispatches beside sd1's")
    for k in ("D7_efficiency", "D8_overlays", "readings", "mechanism_readings", "pace", "shortest_L_by_level", "left_floor_landings", "clears", "selection_at_the_open", "rule_inputs", "decision", "line"):
        check(k in rep, f"the report section {k}")
    e7 = rep["D8_overlays"]["E7"]
    check(e7["open"]["at_sd2_bound"]["record_bound_cells"] is not None and e7["open"]["at_sd1_bound"]["record_bound_cells"] is not None and e7["close"]["at_sd2_bound"]["record_bound_cells"] >= e7["close"]["at_sd1_bound"]["record_bound_cells"]
          and rep["clears"]["registered"]["count"] >= len(arm["verified_clears"]) and rep["decision"]["outcome"] == rule["outcome"], "the readings: E7 at both bounds")
    sel = rep["selection_at_the_open"]
    check(set(sel["v4"]["by_level"]) <= set(sel["v3"]["by_level"]) and set(sel["v4"]["by_level"]) <= set(sel["v4_previous_bound"]["by_level"]) and sel["bounds"]["v4"] < sel["bounds"]["v4_previous_bound"], "the three analytic readings at the open")
    if set(sel["v4"]["by_level"]) == set(sel["v3"]["by_level"]):
        check(all(abs(sel["v4"]["by_level"][k] - sel["v3"]["by_level"][k]) < 1e-9 for k in sel["v3"]["by_level"]), "the harmonic level shares are the same under v3 and v4 when the same levels have eligible cells")
    vr = rpt6.verify_run6(root, cp["sd1"], cp["rd4"], cp["rd3"], cp["rd2"], cp["rd1"], "sd2")
    check(vr["ok"], f"verify-run: {vr['problems']}")
    tmp = tmpdir("m8vr6_")
    shutil.copytree(root, tmp / "a")
    (tmp / "a" / "sessions" / "sd2" / "rule.json").unlink()
    check(not rpt6.verify_run6(tmp / "a", cp["sd1"], cp["rd4"], cp["rd3"], cp["rd2"], cp["rd1"], "sd2")["ok"], "no decision recorded is refused")
    shutil.copytree(root, tmp / "b")
    rp_ = tmp / "b" / "sessions" / "sd2" / "rule.json"
    d_ = json.loads(rp_.read_text(encoding="utf-8"))
    d_["outcome"] = "PROGRESS" if d_["outcome"] != "PROGRESS" else "NO_SHORTER_CLEAR"
    rp_.write_text(json.dumps(d_), encoding="utf-8")
    check(not rpt6.verify_run6(tmp / "b", cp["sd1"], cp["rd4"], cp["rd3"], cp["rd2"], cp["rd1"], "sd2")["ok"], "a recorded outcome the replays do not hold is refused")
    shutil.copytree(root, tmp / "c")
    rp_ = tmp / "c" / "sessions" / "sd2" / "rule.json"
    d_ = json.loads(rp_.read_text(encoding="utf-8"))
    d_["line"]["status"] = "REPAIR_NEEDED"
    rp_.write_text(json.dumps(d_), encoding="utf-8")
    check(not rpt6.verify_run6(tmp / "c", cp["sd1"], cp["rd4"], cp["rd3"], cp["rd2"], cp["rd1"], "sd2")["ok"], "a recorded line status the rule does not hold is refused")
    shutil.copytree(root, tmp / "d")
    (tmp / "d" / "sessions" / "sd2" / "unstamped.json").write_text("{\"x\": 1}\n", encoding="utf-8")
    v = rpt6.verify_run6(tmp / "d", cp["sd1"], cp["rd4"], cp["rd3"], cp["rd2"], cp["rd1"], "sd2")
    check(not v["ok"] and any("artifacts" in p for p in v["problems"]), "a record without its stamp is refused")
    shutil.copytree(root, tmp / "e")
    ip = tmp / "e" / "sessions" / "sd2" / "iterations_T.jsonl"
    ip.write_text("".join(ln + "\n" for ln in ip.read_text(encoding="utf-8").splitlines()[1:]), encoding="utf-8")
    check(not rpt6.verify_run6(tmp / "e", cp["sd1"], cp["rd4"], cp["rd3"], cp["rd2"], cp["rd1"], "sd2")["ok"], "a JSONL file without its header row is refused")
    shutil.copytree(root, tmp / "f")
    ep = tmp / "f" / "archive" / "events.jsonl"
    ep.write_bytes(ep.read_bytes().replace(b'"worker":0', b'"worker":1', 1))
    check(not rpt6.verify_run6(tmp / "f", cp["sd1"], cp["rd4"], cp["rd3"], cp["rd2"], cp["rd1"], "sd2")["ok"], "a changed archive file is refused")
    shutil.copytree(root, tmp / "g")
    ov_ = tmp / "g" / "derived" / "sd1_closing_overlay.jsonl"
    ov_.write_bytes(ov_.read_bytes() + b"\n")
    check(not rpt6.verify_run6(tmp / "g", cp["sd1"], cp["rd4"], cp["rd3"], cp["rd2"], cp["rd1"], "sd2")["ok"], "a changed sd1-closing overlay file is refused")
    shutil.rmtree(tmp, ignore_errors=True)
    check(all_immutability6(cp)["ok"] and all_immutability6(chain)["ok"], "the earlier trees are untouched")
    shutil.rmtree(cp["t"], ignore_errors=True)
    return {"outcome": rule["outcome"], "cells": len(a.cells), "pool": arm["pool"], "replays": arm["replays"], "best": arm["best_verified"] and arm["best_verified"]["completion_input_tick"], "t_rec": rr["completion_input_tick"],
            "inherited": inh["count"]}


def unit_session6_determinism() -> Dict[str, Any]:
    c1 = build_chain6(cache=False)
    c2 = build_chain6(cache=False)

    def chain_sig(c: Mapping[str, Any]) -> Dict[str, Any]:
        return {t: {n: mw.sha256_file(c[t] / "archive" / n) for n in ("cells.jsonl", "bursts.bin", "bursts.idx.jsonl", "events.jsonl")} for t in ("rd1", "rd2", "rd3", "rd4", "sd1")}

    check(chain_sig(c1) == chain_sig(c2) and c1["expect5"]["inherited_record"] == c2["expect5"]["inherited_record"], "two builds of the synthetic chain are byte-identical (cells, words, index, ledger, the record), sd1's tree included")
    o1, s1_, r1, cp1 = run6_small(c1)
    o2, s2_, r2, cp2 = run6_small(c1)
    sig1, sig2 = signature6(r1), signature6(r2)
    check(sig1 == sig2, f"two runs of the same sd2 session agree on the archive's data files, the decision, the replay order, both overlays and both session digests: {json.dumps(sig1)[:300]}")
    check(o1["rule"]["outcome"] == o2["rule"]["outcome"] and s1_.ledgers["T"].ticks == s2_.ledgers["T"].ticks and len(s1_.ledgers["T"].candidates) == len(s2_.ledgers["T"].candidates), "outcome, ticks and candidates agree")
    other = 0 if mcell.HOST_FRAME != 0 else 2
    tmp = Path(tempfile.mkdtemp(prefix="m8_sd2_host_"))
    for n in ("cells.jsonl", "bursts.idx.jsonl"):
        rows = [json.loads(ln) for ln in (r1 / "archive" / n).read_text(encoding="utf-8").splitlines() if ln.strip()]
        check(any(isinstance(r.get("end"), list) for r in rows) or any(r.get("wins") for r in rows), f"{n}: the rows carry end vectors")
        shifted = copy.deepcopy(rows)
        for row in shifted:
            if isinstance(row.get("end"), list):
                row["end"][mcell.HOST_FRAME] = int(row["end"][mcell.HOST_FRAME]) + 7
            for w in row.get("wins") or []:
                w["end"][mcell.HOST_FRAME] = int(w["end"][mcell.HOST_FRAME]) + 7
        (tmp / n).write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in shifted), encoding="utf-8")
        check(host_masked_sha256(tmp / n) == sig1["files"][n] and mw.sha256_file(tmp / n) != mw.sha256_file(r1 / "archive" / n), f"{n}: the signature ignores the host frame of every end vector")
        wrong = copy.deepcopy(rows)
        first = next(r for r in wrong if isinstance(r.get("end"), list) or r.get("wins"))
        vec = first["end"] if isinstance(first.get("end"), list) else first["wins"][0]["end"]
        vec[other] = vec[other] + 1
        (tmp / n).write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in wrong), encoding="utf-8")
        check(host_masked_sha256(tmp / n) != sig1["files"][n], f"{n}: the signature sees every other end field")
    shutil.rmtree(tmp, ignore_errors=True)
    for c in (c1, c2, cp1, cp2):
        shutil.rmtree(c["t"], ignore_errors=True)
    return {"files": len(sig1["files"]), "digest": hashlib.sha256(json.dumps(sig1, sort_keys=True).encode()).hexdigest()[:16]}


def unit_session6_inherited_continuations() -> Dict[str, Any]:
    """rd4's claim cases (a) and (b) under sd2: the continuation of an inherited left-of-wall cell that does not land and the continuation of an inherited wall-top cell are neither a false
    INVALID nor a replay (sd2's pool holds clears only); the wall-top sighting is recorded."""
    chain = build_chain6()
    world = chain["world"]
    cls = t4.forced_session_cls(world, ("left_nolanding", "wall_continuation"), base=run6.Session6)
    out, sess, root, cp = run6_small(chain, session_cls=cls, arm_tick_cap=12000, min_arm_ticks=4000)
    rule = out["rule"]
    check(not rule["invalid"] and not rule["incomplete"], f"a session that starts with the claim cases: {rule['outcome']} {rule['invalid']} {rule['incomplete']}")
    forced = {f["kind"]: f for f in sess.forced}
    n_open = chain["expect5"]["cells"]
    check(set(forced) == {"left_nolanding", "wall_continuation"} and all(f["cell"] < n_open for f in forced.values()), f"the two forced dispatches start from inherited cells: {forced}")
    led = sess.ledgers["T"]
    cand_b = t4.candidate_for_iteration(sess, forced["left_nolanding"]["iteration"], "left")
    check(cand_b is not None and t4.cl4.is_descriptive(cand_b), "the continuation of an inherited left cell registers a descriptive left candidate")
    ver = json.loads((sess.cfg.session_dir / "verification.json").read_text(encoding="utf-8"))
    check(cand_b["cid"] not in ver["arm"]["replay_order"] and all(led.candidates[cid]["kind"] == "clear" for cid in ver["arm"]["replay_order"]), "it is never replayed: the pool holds clears only")
    rows_s = art.rows_of(sess.cfg.session_dir / "wall_top_sightings.jsonl")
    row = next((x for x in rows_s if x["iteration"] == forced["wall_continuation"]["iteration"]), None)
    check(row is not None and row["start_cell_on_wall_top"] and row["first_tick_of_the_burst"], f"the wall-top continuation is recorded as a sighting: {rows_s}")
    check(led.l0_cid is None and not [c for c in led.candidates if c["kind"] == "l0"], "no wall-top candidate: the landing is rd2's, never claimed again")
    check(json.loads((sess.cfg.session_dir / "arm_T.json").read_text(encoding="utf-8"))["wall_top_sightings"]["from_a_wall_top_start"] >= 1, "the arm record counts it")
    check(rpt6.verify_run6(root, cp["sd1"], cp["rd4"], cp["rd3"], cp["rd2"], cp["rd1"], "sd2")["ok"], "verify-run")
    shutil.rmtree(cp["t"], ignore_errors=True)
    return {"outcome": rule["outcome"], "forced": sorted(forced)}


def unit_session6_record_replay_at_open() -> Dict[str, Any]:
    chain = build_chain6()
    op = open6(chain)
    rc = op["record_candidate"]
    out, sess, _r, cp = run6_small(chain, record_candidate=dict(rc, words=bytes([(rc["words"][0] + 1) % 72]) + rc["words"][1:]), arm_tick_cap=3000, min_arm_ticks=1000)
    r = out["rule"]
    check(r["outcome"] == "INVALID" and any("did not re-verify at the open" in x for x in r["invalid"]) and sess.iteration == sess.first_iteration, f"a record whose words differ from the pinned digest: INVALID before any dispatch: {r['invalid']}")
    ro = json.loads((sess.cfg.session_dir / "record_open.json").read_text(encoding="utf-8"))
    check(not ro["exact"] and ro["problems"] and ro["scope"] == rule6.SCOPE, "the open record names the problem")
    out, sess, _r, cp = run6_small(chain, record_candidate=dict(rc, first={"clear": rc["first"]["clear"] + 1}), arm_tick_cap=3000, min_arm_ticks=1000)
    check(out["rule"]["outcome"] == "INVALID" and any("differs from the registered clear tick" in x for x in out["rule"]["invalid"]), f"a clock that differs from the registered one: {out['rule']['invalid']}")
    out, sess, _r, cp = run6_small(chain, record_candidate=dict(rc, words=rc["words"] * 40), arm_tick_cap=3000, min_arm_ticks=1000)
    r = out["rule"]
    check(r["outcome"] == "INCOMPLETE" and any("beyond the open cap" in x for x in r["incomplete"]) and sess.iteration == sess.first_iteration and r["line"]["status"] == "NOT_STARTED" and r["line"]["session_counts"] is False
          and r["exploration_started"] is False, f"a record replay that does not fit the open cap: INCOMPLETE before any dispatch (NOT_STARTED, does not count), never INVALID: {r['incomplete']} {r['line']['status']}")
    shutil.rmtree(cp["t"], ignore_errors=True)
    return {"record_words": len(rc["words"])}


def unit_budget_projection6() -> Dict[str, Any]:
    caps = ses6.caps()
    check(caps == ses5.caps() and caps["wall_caps_s"] == {"p1": 240.0, "T": 3000.0, "verify": 360.0} and caps["global_cap_s"] == 3600.0 and caps["exploration_tick_cap"] == 6_000_000
          and caps["min_exploration_ticks"] == 2_000_000 and caps["open_tick_cap"] == 70_000 and caps["replay_tick_cap"] == 400_000 and caps["identity_k"] == 16, "every cap equals sd1's and rd4's")
    proj = rpt6.budget_projection(caps)
    check(proj["caps_s"]["sum"] == proj["caps_s"]["session_hard_cap"] == 3600.0 and proj["pessimistic"]["valid"] and proj["pessimistic"]["fits_hard_cap"] and proj["fits_hard_cap_without_trimming"], f"the pessimistic projection fits: {proj['pessimistic']}")
    record = ses6.RECORD_REFERENCE["words"]
    check(6208 + 16 * mcell.HORIZON + record <= caps["open_tick_cap"], "the open phase: P1, 16 identity replays at the horizon and the record fit 70,000 ticks")
    inherited = cl6.inherited_ticks(cl6.inherited_unverified_clears6(SD1_REAL)) if REAL_TREES else 0
    check(inherited + 16 * mcell.HORIZON + 10 * record <= caps["replay_tick_cap"], f"the verification: the inherited replays ({inherited}), 16 identity replays and ten clear replays fit 400,000 ticks")
    return {"pessimistic_s": proj["pessimistic"]["wall_s"]["total"], "inherited_ticks": inherited}


# -- the approval, the results record, the artifacts, the guards -----------------------------------------------------------------------------------------------


def _load_tool(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"sd2_tool_{name.replace('.py', '')}", TOOLS_DIR / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)                     # type: ignore[union-attr]
    return mod


def unit_approval_isolated6() -> Dict[str, Any]:
    want = ses6.identity()
    t = tmpdir("m8ap6_")
    p = t / "approval.json"
    ok, why = ses6.approval_status(p, want)
    check(not ok and "no approval record" in why, "no record: refused")
    good = art.stamp(dict(want, approval="APPROVED by the test", revision=1))
    p.write_text(json.dumps(good), encoding="utf-8")
    check(ses6.approval_status(p, want) == (True, "approved"), "a matching stamped record is accepted")
    p.write_text(json.dumps({k: v for k, v in good.items() if k not in ("task", "created_utc")}), encoding="utf-8")
    ok, why = ses6.approval_status(p, want)
    check(not ok and "task block" in why, "an approval without its stamp is refused")
    p.write_text(json.dumps(dict(good, approval="PENDING")), encoding="utf-8")
    check(not ses6.approval_status(p, want)[0], "PENDING is refused")
    n = 0
    alter = {"rule_sha256": "0" * 64, "claims_digest": "0" * 64, "artifacts_digest": "0" * 64, "executable_sha256": "0" * 64, "scope": "other", "archive_id": "x", "workers": 4, "burst_words": 121,
             "horizon": 3599, "flags": {"explore": {}, "verify": {}}, "contracts": dict(want["contracts"], m8_rd_select_v4="0" * 64), "key_strings": {"select_sd2": "x"}, "runtime_files": {"BattleShip.o2r": "0" * 64},
             "p1": {}, "readiness": {"min_available_mb": 1}, "git_head": "0" * 40, "session": "sdX", "predecessor": "rd4", "gate": "x", "line": "rd", "rule": "other", "draws_sha256": "0" * 64,
             "sd2_session_event_digest": "0" * 64, "sd1_session_event_digest": "0" * 64, "select_v4_changed_from": {"x": "0" * 64}, "length_scale_v4": 900.0,
             "record_reference": dict(want["record_reference"], completion_input_tick=2085, words=2085), "previous_record_reference": dict(want["previous_record_reference"], completion_input_tick=2314, words=2314),
             "margin": 23, "progress_bar": 2063, "record_bound_max_L": 2060, "tiers": {"5_percent": 1982}, "inherited_descriptive_rule": "none", "base": dict(want["base"], sd1_increment_manifest_sha256="0" * 64),
             "open_overlay": dict(want["open_overlay"], v4_sha256="0" * 64), "budgets": {"hard_cap": "61 min"}, "docs_sha256": {"docs/x.md": "0" * 64}, "source_fingerprint": "0" * 16,
             "task": {"id": "x", "character": "mario", "stage": "btt_mario"}, "line_statuses": ["x"]}
    for k, v in alter.items():
        check(k in want, f"the identity carries {k}")
        p.write_text(json.dumps(dict(good, **{k: v})), encoding="utf-8")
        check(not ses6.approval_status(p, want)[0], f"an altered {k} was accepted")
        n += 1
    for k in list(want["caps"]):
        caps = dict(want["caps"])
        caps[k] = {"x": 1}
        p.write_text(json.dumps(dict(good, caps=caps)), encoding="utf-8")
        check(not ses6.approval_status(p, want)[0], f"an altered cap {k} was accepted")
        n += 1
    for f in list(want["code"]):
        code = dict(want["code"])
        code[f] = "0" * 64
        p.write_text(json.dumps(dict(good, code=code)), encoding="utf-8")
        check(not ses6.approval_status(p, want)[0], f"an altered code hash for {f} was accepted")
        n += 1
    p.write_text(json.dumps(dict(good, d_records={"folders": ["2026-09-28"], "digest": "0" * 64})), encoding="utf-8")
    check(not ses6.approval_status(p, want)[0], "an altered D: records digest")
    check(ses6.APPROVAL != p and ses6.APPROVAL.name == "rl_m8_sd2_approval.json", "the repository path is untouched by the tests")
    check(set(want["contracts"]) == set(ses5.contract_digests5("x")) and want["rule"] == "m8_sd2_rule_v1" and want["workers"] == 5 and want["margin"] == 24 and want["progress_bar"] == 2062 and want["record_bound_max_L"] == 2061
          and want["record_reference"] == r6.RECORD_REFERENCE6 and want["previous_record_reference"] == r5.RECORD_REFERENCE and want["tiers"] == {"5_percent": 1981, "10_percent": 1877, "round_1800": 1800}
          and want["task"] == A.task_block() and want["line_statuses"] == list(rule6.LINE_STATUSES) and want["sd2_session_event_digest"] != want["sd1_session_event_digest"]
          and want["contracts"]["m8_rd_select_v4"] == want["sd2_session_event_digest"], "registered identity entries")
    base = want["base"]
    check(base["sd1_checkpoint_seq"] == 57 and base["sd1_increment"] == r6.SD1_INCREMENT_NAME and base["sd1_increment_manifest_sha256"] == r6.SD1_INCREMENT_MANIFEST_SHA256 and base["first_sd2_iteration"] == 17557
          and base["sd1_first_iteration"] == 13886 and base["sd1_line"]["rd5_permitted"] is True and base["sd1_line"]["status"] == "SD2_PROPOSABLE_NEW_REFERENCE"
          and [e["name"] for e in base["sd1_session_events"]] == ["rd2", "rd3", "rd4", "sd1"] and base["sd1_session_events"][3]["digest"] == want["sd1_session_event_digest"]
          and r6.record_fact_problems(base["inherited_record"], r6.INHERITED_RECORD6) == [] and base["rd1_to_rd4"]["rd4_checkpoint_seq"] == 45, "the base identity reads sd1's closed tree (the inherited record equals the registered one)")
    check(want["open_overlay"]["sd1_closing_v4_sha256"] == r6.SD1_CLOSING_OVERLAY_V4_SHA256 and want["open_overlay"]["v4_sha256"] == r6.SD2_OPEN_OVERLAY_SHA256
          and want["open_overlay"]["expected_v4_counts"] == r6.EXPECTED_OPEN_OVERLAY6 and want["open_overlay"]["expected_sd1_closing_counts"] == r6.EXPECTED_SD1_CLOSE_OVERLAY_V4, "both overlays are pinned")
    for f in ses6.NEW_CODE_FILES:
        check(f"rl/{f}" in want["code"], f"{f} is pinned")
    for f in ses6.TOOL_FILES:
        check(f"tools/m8_sd2/{f}" in want["code"], f"the tool {f} is pinned")
    check(all(f"rl/{f}" in want["code"] for f in ("m8_sd1_select.py", "m8_sd1_run.py", "m8_sd1_tests.py", "m8_rd4_select.py", "m8_rd_select2.py", "m8_rd_cells.py", "m8_rd_claims.py")), "rd1's to sd1's code is pinned too")
    check(all(d in want["docs_sha256"] for d in ("docs/rl_m8_sd1_approval.json", "docs/rl_m8_sd1_prep_2026-10-11.md", "docs/rl_m8_sd1_results_2026-10-11.md", "docs/rl_m8_sd2_proposal_2026-10-12.md")), "sd1's documents and the sd2 proposal are pinned")
    check(want["source_fingerprint"] == ses6.source_fingerprint(), "the identity carries the source fingerprint")
    # the approval writer's refusals, on isolated records (the repository's approval path is patched for the duration)
    wa = _load_tool("write_approval.py")
    check("no commit" in wa.S2_RULE and "runs_backup.py verify" in wa.S2_RULE and "new folder on D:" in wa.S2_RULE, "the S2 rule text")
    lc = wa.line_consequence()
    check(set(lc["if_this_session_is"]) == {"PROGRESS", "RECORD_BELOW_MARGIN", "NO_SHORTER_CLEAR", "COUNTED_INCOMPLETE", "NOT_STARTED", "INVALID"} and "never deleted" in lc["if_this_session_is"]["NOT_STARTED"]
          and "2,062" in lc["if_this_session_is"]["PROGRESS"] and "2,086" in lc["if_this_session_is"]["NO_SHORTER_CLEAR"] and lc["s2_rule"] == wa.S2_RULE and "review" in lc, f"the line consequence names every outcome, NOT_STARTED as its own row: {list(lc['if_this_session_is'])}")
    snap = t / "snap"
    snap.mkdir()
    auth = t / "auth.txt"
    auth.write_text("I authorise sd2 once.\n", encoding="utf-8")
    empty = t / "empty.txt"
    empty.write_text("\n\n", encoding="utf-8")
    saved_approval = wa.S.APPROVAL
    saved_argv = sys.argv
    codes: Dict[str, int] = {}
    try:
        wa.S.APPROVAL = t / "never.json"

        def run_wa(*args: str) -> int:
            sys.argv = ["write_approval.py", *args]
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                return wa.main()

        codes["no_snapshot"] = run_wa("--session", "sd2", "--snapshot", str(snap), "--independent", "x", "--authorisation-file", str(auth), "--authorised-on", "2026-10-13")
        (snap / "snapshot.json").write_text(json.dumps({"result": "FAIL", "tool": "m8_sd2_source_snapshot_v1", "git_head": want["git_head"], "source_fingerprint": want["source_fingerprint"], "n_files": 1}), encoding="utf-8")
        codes["not_pass"] = run_wa("--session", "sd2", "--snapshot", str(snap), "--independent", "x", "--authorisation-file", str(auth), "--authorised-on", "2026-10-13")
        (snap / "snapshot.json").write_text(json.dumps({"result": "PASS", "tool": "m8_sd1_source_snapshot_v1", "git_head": want["git_head"], "source_fingerprint": want["source_fingerprint"], "n_files": 1}), encoding="utf-8")
        codes["wrong_tool"] = run_wa("--session", "sd2", "--snapshot", str(snap), "--independent", "x", "--authorisation-file", str(auth), "--authorised-on", "2026-10-13")
        (snap / "snapshot.json").write_text(json.dumps({"result": "PASS", "tool": "m8_sd2_source_snapshot_v1", "git_head": want["git_head"], "source_fingerprint": want["source_fingerprint"], "n_files": 1}), encoding="utf-8")
        codes["empty_authorisation"] = run_wa("--session", "sd2", "--snapshot", str(snap), "--independent", "x", "--authorisation-file", str(empty), "--authorised-on", "2026-10-13")
        codes["bad_date"] = run_wa("--session", "sd2", "--snapshot", str(snap), "--independent", "x", "--authorisation-file", str(auth), "--authorised-on", "2026-13-01")
        (snap / "snapshot.json").write_text(json.dumps({"result": "PASS", "tool": "m8_sd2_source_snapshot_v1", "git_head": "0" * 40, "source_fingerprint": want["source_fingerprint"], "n_files": 1}), encoding="utf-8")
        codes["head_mismatch"] = run_wa("--session", "sd2", "--snapshot", str(snap), "--independent", "x", "--authorisation-file", str(auth), "--authorised-on", "2026-10-13")
        (snap / "snapshot.json").write_text(json.dumps({"result": "PASS", "tool": "m8_sd2_source_snapshot_v1", "git_head": want["git_head"], "source_fingerprint": "0" * 16, "n_files": 1}), encoding="utf-8")
        codes["fingerprint_mismatch"] = run_wa("--session", "sd2", "--snapshot", str(snap), "--independent", "x", "--authorisation-file", str(auth), "--authorised-on", "2026-10-13")
        (t / "exists.json").write_text("{}", encoding="utf-8")
        wa.S.APPROVAL = t / "exists.json"
        codes["existing"] = run_wa("--session", "sd2", "--snapshot", str(snap), "--independent", "x", "--authorisation-file", str(auth), "--authorised-on", "2026-10-13")
    finally:
        wa.S.APPROVAL = saved_approval
        sys.argv = saved_argv
    check(all(c == 2 for c in codes.values()) and not (t / "never.json").exists(), f"every refusal of the approval writer exits 2 and writes nothing: {codes}")
    shutil.rmtree(t, ignore_errors=True)
    return {"altered_entries_refused": n, "writer_refusals": sorted(codes)}


def unit_results_record_rule6() -> Dict[str, Any]:
    t = tmpdir("m8rr6_")
    docs = t / "docs"
    docs.mkdir()
    good = docs / "rl_m8_sd2_results_2026-10-13.md"
    body = "# M8-sd2 results (2026-10-13)\n\nsummary\n\n## 1. What was run\n\ntext\n"
    good.write_text(body, encoding="utf-8")
    check(ses6.results_record_problems(good, docs) == [], "a complete record with the exact name is accepted")
    bom_crlf = docs / "rl_m8_sd2_results_2026-10-14.md"
    bom_crlf.write_bytes(b"\xef\xbb\xbf" + body.replace("2026-10-13", "2026-10-14").replace("\n", "\r\n").encode("utf-8"))
    good.unlink()
    check(ses6.results_record_problems(bom_crlf, docs) == [], "a BOM and CRLF line ends are tolerated")
    bom_crlf.unlink()
    good.write_text(body, encoding="utf-8")
    bad_names = ("rl_m8_sd2_results_draft.md", "rl_m8_sd2_results_2026-10-13.md.tmp", "rl_m8_sd2_results_2026-10-13.md~", "rl_m8_sd2_results_2026-10-9.md", "rl_m8_sd2_results_2026-13-01.md",
                 "rl_m8_sd2_results_2026-02-30.md", "rl_m8_sd2_results_.md", "rl_m8_sd2_results.md", "RL_M8_SD2_RESULTS_2026-10-20.MD", "rl_m8_sd2_results_2026-10-21.MD", "rl_m8_sd2_results_2026-10-13.md.bak")
    check(len(bad_names) == 11, "eleven bad names")
    for bad_name in bad_names:                        # other dates: Windows names are case-insensitive
        p = docs / bad_name
        p.write_text(body, encoding="utf-8")
        probs = ses6.results_record_problems(good, docs)
        check(probs and all("another entry" in x for x in probs), f"{bad_name} beside the record is refused: {probs}")
        check(ses6.results_record_problems(p, docs) != [], f"{bad_name} is not a record")
        p.unlink()
    d = docs / "rl_m8_sd2_results_2026-10-15.md"
    d.mkdir()
    check(ses6.results_record_problems(good, docs) != [] and ses6.results_record_problems(d, docs) != [], "a directory with the registered name is refused")
    d.rmdir()
    second = docs / "rl_m8_sd2_results_2026-10-16.md"
    second.write_text(body.replace("2026-10-13", "2026-10-16"), encoding="utf-8")
    check(ses6.results_record_problems(good, docs) != [], "two complete records are refused")
    second.unlink()
    for what, content in (("empty", b""), ("no final newline", body.rstrip("\n").encode("utf-8")), ("a NUL byte", body.encode("utf-8") + b"\x00\n"), ("not UTF-8", b"\xff\xfe# M8\n## x\n"),
                          ("another date in the title", body.replace("(2026-10-13)", "(2026-10-12)").encode("utf-8")), ("the title alone", b"# M8-sd2 results (2026-10-13)\n"),
                          ("no title", b"text\n\n## 1\n\nx\n"), ("an sd1 title", b"# M8-sd1 results (2026-10-13)\n\n## 1\n\nx\n")):
        good.write_bytes(content)
        check(ses6.results_record_problems(good, docs) != [], f"{what} is refused")
    good.write_text(body, encoding="utf-8")
    (docs / "rl_m8_sd2_proposal_2026-10-12.md").write_text("x\n", encoding="utf-8")
    (docs / "rl_m8_sd1_results_2026-10-11.md").write_text("x\n", encoding="utf-8")
    check(ses6.results_record_problems(good, docs) == [], "the proposal's and sd1's record's names do not start with sd2's results prefix")
    r = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_sd2_session.py"), "check-results-record", "--path", str(t / "nowhere.md")], capture_output=True, text=True, timeout=300)
    check(r.returncode == 1 and '"ok": false' in r.stdout, "the CLI refuses a missing record")
    shutil.rmtree(t, ignore_errors=True)
    return {}


def unit_artifacts6_stamping() -> Dict[str, Any]:
    t = tmpdir("m8art6_")
    p = t / "a.json"
    art.write_json5(p, {"x": 1})
    rec = json.loads(p.read_text(encoding="utf-8"))
    check(art.is_stamped(rec) and rec["task"] == A.task_block() and list(rec)[:2] == ["task", "created_utc"] and rec["x"] == 1, "a written object carries the stamp first")
    first = rec["created_utc"]
    art.write_json5(p, {"x": 2, "y": 3})
    check(json.loads(p.read_text(encoding="utf-8"))["created_utc"] == first, "a rewrite keeps the first created_utc")
    check(art.write_json5 is art5.write_json5 and art.jsonl_header is art5.jsonl_header and art.read_jsonl5 is art5.read_jsonl5, "the writers are sd1's, unchanged")
    root = t / "tree"
    for d in ("archive", "archive.prev", "base", "derived", "routes/T_clear_best", "sessions/sd2/failures", "sessions/sd2/workers/w00", "sessions/sd2/vw/x", "sessions/sd2/verification"):
        (root / d).mkdir(parents=True)
    for d in ("archive", "archive.prev"):
        art.write_json5(root / d / "archive_meta.json", {"m": 1})
        for n in ("cells.jsonl", "bursts.idx.jsonl", "events.jsonl"):
            (root / d / n).write_text('{"row": 1}\n', encoding="utf-8")
    art.write_json5(root / "base" / "archive_meta.json", {"stamped_copy": 1})
    (root / "base" / "cells.jsonl").write_text('{"row": 1}\n', encoding="utf-8")
    (root / "derived" / "open_overlay.jsonl").write_text('{"id": 0}\n', encoding="utf-8")
    (root / "derived" / "sd1_closing_overlay.jsonl").write_text('{"id": 0}\n', encoding="utf-8")
    art.write_json5(root / "derived" / "open_overlay.json", {"sha256": "x"})
    art.write_json5(root / "derived" / "base.json", {"schema": "m8_sd2_base_v1"})
    (root / "routes" / "T_clear_best" / "actions.jsonl").write_text('{"sequence_index": 0}\n', encoding="utf-8")
    art.write_json5(root / "routes" / "T_clear_best" / "metadata.json", {"w": 1})
    (root / "sessions" / "sd2" / "failures" / "iterate_4_w03.json.gz").write_bytes(gzip.compress(b'{"raw": 1}'))
    (root / "sessions" / "sd2" / "workers" / "w00" / "x.json").write_text("{}", encoding="utf-8")
    (root / "sessions" / "sd2" / "vw" / "x" / "y.json").write_text("{}", encoding="utf-8")
    art.write_json5(root / "sessions" / "sd2" / "state.json", {"phase": "done"})
    art.append_jsonl5(root / "sessions" / "sd2" / "iterations_T.jsonl", {"ticks": 1}, "s3")
    art.write_jsonl_gz5(root / "sessions" / "sd2" / "dispatch_rows.jsonl.gz", [{"it": 1}], "s4")
    art.write_json_gz5(root / "sessions" / "sd2" / "verification" / "T_c0001_clear.json.gz", {"steps": []})
    aud = art.audit_tree6(root)
    check(aud["ok"] and aud["files"] == 9 and aud["headers"] == 2, f"a correctly stamped tree with the exact exemptions passes: {aud}")
    check(sorted(aud["exempt_files"]) == sorted(["archive/bursts.idx.jsonl", "archive/cells.jsonl", "archive/events.jsonl", "archive.prev/bursts.idx.jsonl", "archive.prev/cells.jsonl", "archive.prev/events.jsonl",
                                                "base/archive_meta.json", "base/cells.jsonl", "derived/open_overlay.jsonl", "derived/sd1_closing_overlay.jsonl", "routes/T_clear_best/actions.jsonl",
                                                "sessions/sd2/failures/iterate_4_w03.json.gz", "sessions/sd2/workers/w00/x.json", "sessions/sd2/vw/x/y.json"]), f"the exempt files, exactly: {aud['exempt_files']}")
    for rel, why in (("archive/cells.jsonl", "frozen"), ("base/anything.json", "byte copy"), ("derived/sd1_closing_overlay.jsonl", "digest-pinned"), ("derived/open_overlay.jsonl", "digest-pinned"),
                     ("routes/x/actions.jsonl", "M4"), ("sessions/sd2/failures/a.json", "frozen rd1 worker")):
        check(art.exempt_reason(rel) is not None and why.split()[0] in art.exempt_reason(rel), f"{rel} is exempt for its reason")
    for rel in ("archive/archive_meta.json", "derived/open_overlay.json", "derived/rd4_closing_overlay.jsonl", "routes/x/metadata.json", "sessions/sd2/state.json", "sessions/sd2/verification/t.json.gz", "launch/preflight.json", "derived/report.json"):
        check(art.exempt_reason(rel) is None, f"{rel} must carry the stamp (sd1's overlay row file name is not exempt under sd2's contract)")
    (root / "derived" / "rd4_closing_overlay.jsonl").write_text('{"id": 0}\n', encoding="utf-8")
    aud_x = art.audit_tree6(root)
    check(not aud_x["ok"] and any("rd4_closing_overlay.jsonl" in f for f in aud_x["failures"]), "an sd1-named overlay file in an sd2 tree is not exempt")
    (root / "derived" / "rd4_closing_overlay.jsonl").unlink()
    (root / "sessions" / "sd2" / "unstamped.json").write_text('{"x": 1}\n', encoding="utf-8")
    aud2 = art.audit_tree6(root)
    check(not aud2["ok"] and any("unstamped.json" in f for f in aud2["failures"]), "an unstamped object fails the audit")
    (root / "sessions" / "sd2" / "unstamped.json").unlink()
    (root / "sessions" / "sd2" / "noheader.jsonl").write_text('{"r": 1}\n', encoding="utf-8")
    aud3 = art.audit_tree6(root)
    check(not aud3["ok"] and any("noheader.jsonl" in f and "header" in f for f in aud3["failures"]), "a JSONL file without its header fails the audit")
    (root / "sessions" / "sd2" / "noheader.jsonl").unlink()
    (root / "archive" / "archive_meta.json").write_text('{"m": 1}\n', encoding="utf-8")
    check(not art.audit_tree6(root)["ok"], "an unstamped archive_meta.json fails the audit")
    check(art.contract_digest() == art.contract_digest() and len(art.contract_digest()) == 64 and art.ARTIFACTS6_CONTRACT == "m8_sd2_artifacts_v1" and art.contract_digest() != art5.contract_digest(), "the artifacts contract digest")
    shutil.rmtree(t, ignore_errors=True)
    return {"audited": aud["files"]}


def unit_task_block_pinned6() -> Dict[str, Any]:
    import experiment_config as ec
    import m9_contract as C

    tb = art.task_block()
    check(tb == {"id": "ssb64_us_mario_btt_v1", "character": "mario", "stage": "btt_mario"} and tb == A.task_block() == dict(C.TASK), "the task block")
    reg = ec.SUPPORTED_TASKS[tb["id"]]
    check(reg["character"] == tb["character"] and reg["stage"] == tb["stage"], "pinned to the project's task registry")
    check(A.REGISTERED_TASKS == {tb["id"]: {"character": "mario", "stage": "btt_mario"}}, "the M9 writer's registry")
    for mod in (ses6, run6, r6, rpt6):
        check(getattr(mod, "art").task_block() == tb, f"{mod.__name__} stamps with the task block")
    return tb


CENSUS_TOKENS = ("1960", "2066", "1898", "1966", "1911", "2213", "2298", "1838", "1339", "3900", "2700", "1950", "2250", "3750", "3450", "2550", "2100",            # sd1's list
                 "1897", "1776", "1237", "1942", "1943", "1968", "2040", "2059", "1850", "1964", "2301", "4697", "3242", "1021", "490", "3290", "3280", "2814", "1036", "3152", "4074", "3594",
                 "3452", "2883", "3771", "2128", "1694", "1738", "24599", "27603", "44007", "17554", "35118", "6695", "3671")                                       # the sd2 proposal's census and sd1's tree
INTEGRITY_LITERALS = ("SD1_FACTS", "INHERITED_RECORD6", "EXPECTED_SD1_CLOSE_OVERLAY_V4", "EXPECTED_OPEN_OVERLAY6", "SD1_CLOSING_OVERLAY_V4_SHA256", "SD2_OPEN_OVERLAY_SHA256", "RD4_FACTS", "INHERITED_RECORD",
                      "EXPECTED_OPEN_OVERLAY5", "EXPECTED_RD4_CLOSE_OVERLAY")
FORCED_HOOK_TOKENS = ("forced_session_cls", "find_forced_iteration", "ForcedSession", "find_burst", "scenario_ok", "inherited_cells(")


def unit_source_guard6() -> Dict[str, Any]:
    """No sd2 module or tool reads fixtures, recordings, the TAS or any .btti file; none imports a learning framework or the random module; no call that writes takes a path built from an
    earlier tree's root; no census number or stage coordinate enters the selection, claims, rule or run modules; the resume module's integrity literals are referenced by none of them; the
    tiers are read by no selection, claim or outcome; no production module or tool contains or can reach a forced-dispatch test hook."""
    forbidden = ("rl/fixtures", "fixtures/m7g", "m7g/capture", "tas_input", "mario_743", ".btti", "btti_replay", "crossing_fixture", "rl_crossing")
    bad_imports = {"random", "torch", "gymnasium", "stable_baselines3", "numpy", "pandas", "scipy", "sklearn"}
    write_attrs = {"write_text", "write_bytes", "mkdir", "unlink", "rmdir", "touch", "rename", "replace", "chmod"}
    copy_funcs = {"copyfile", "copy", "copy2", "copytree", "move"}
    writers = {"write_json", "write_json5", "append_jsonl", "append_jsonl5", "write_jsonl_gz5", "save_checkpoint", "write_files", "rmtree", "rmtree_retry", "remove_tree_retry", "replace_retry", "makedirs"}
    names_earlier = ("rd1_root", "RD1_ROOT", "rd1_archive_dir", "M8_ROOT", "rd2_root", "RD2_ROOT", "rd2_archive_dir", "rd1_dir", "rd2_dir", "RD1_REAL", "RD2_REAL", "rd3_root", "RD3_ROOT", "rd3_archive_dir",
                     "rd3_dir", "RD3_REAL", "rd4_root", "RD4_ROOT", "rd4_archive_dir", "rd4_dir", "RD4_REAL", "sd1_root", "SD1_ROOT", "sd1_dir", "SD1_REAL", "pred_dir")
    hits: Dict[str, List[str]] = {}
    sources = [(name, RL_DIR / f"{name}.py") for name in NEW_MODULES] + [(f"tools/{f}", TOOLS_DIR / f) for f in PYTHON_TOOLS]
    for name, pth in sources:
        raw = pth.read_text(encoding="utf-8")
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
        found += [f"forced-dispatch hook token {tok}" for tok in FORCED_HOOK_TOKENS if tok in raw]
        if found:
            hits[name] = found
    for f in PS_TOOLS:
        raw = (TOOLS_DIR / f).read_text(encoding="utf-8")
        found = [x for x in forbidden if x in raw.replace("\\", "/")] + [f"forced-dispatch hook token {tok}" for tok in FORCED_HOOK_TOKENS if tok in raw]
        if found:
            hits[f"tools/{f}"] = found
    check(not hits, f"forbidden vocabulary, imports, writes or test hooks in the sd2 modules or tools: {hits}")
    # no census number, no stage coordinate and no integrity literal in the modules that select, claim, decide or run (the registered constants are allowed)
    for name in ("m8_sd2_select", "m8_sd2_claims", "m8_sd2_rule", "m8_sd2_run"):
        raw = (RL_DIR / f"{name}.py").read_text(encoding="utf-8")
        code = "\n".join(ln.split("#", 1)[0] for ln in raw.splitlines())
        code = re.sub(r'"""[\s\S]*?"""', "", code)
        for tok in CENSUS_TOKENS:
            check(re.search(rf"(?<![0-9.\w]){tok}(?![0-9])", code) is None, f"{name}.py names the census or stage quantity {tok}")
        for lit in INTEGRITY_LITERALS:
            check(lit not in raw, f"{name}.py references the integrity literal {lit} (integrity facts are never selection inputs)")
    # the tiers: read by no selection or claim module, and by no outcome
    for name in ("m8_sd2_select", "m8_sd2_claims"):
        src = (RL_DIR / f"{name}.py").read_text(encoding="utf-8")
        check("tier" not in src.lower(), f"{name}.py reads the tiers")
    rule_src = (RL_DIR / "m8_sd2_rule.py").read_text(encoding="utf-8")
    tree = ast.parse(rule_src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "outcome_of")
    check(not any("tier" in ast.unparse(n).lower() for n in ast.walk(fn)), "outcome_of reads no tier")
    apply_fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "apply")
    outcome_stmt = next(n for n in apply_fn.body if isinstance(n, ast.If) and any(isinstance(x, ast.Assign) and ast.unparse(x.targets[0]) == "out" for x in ast.walk(n)))
    check("tier" not in ast.unparse(outcome_stmt).lower() and "outcome_of" in ast.unparse(outcome_stmt), "the outcome in apply is outcome_of's alone; no tier enters it")
    run_src = (RL_DIR / "m8_sd2_run.py").read_text(encoding="utf-8")
    check("tier_report" in run_src and "TIERS[" not in run_src, "the run engine reports the tiers and reads none")
    tests_src = (RL_DIR / "m8_sd2_tests.py").read_text(encoding="utf-8")
    for nd in ast.walk(ast.parse(tests_src)):
        if isinstance(nd, ast.Call):
            f = nd.func
            fname = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
            if fname in write_attrs | writers | copy_funcs and any(n in ast.unparse(nd) for n in ("RD1_REAL", "RD2_REAL", "RD3_REAL", "RD4_REAL", "SD1_REAL")):
                raise Failure(f"the tests write through a real tree's path: {ast.unparse(nd)[:100]}")
    # the tool's verify on earlier increments: only one code path, on the new increment
    prc_src = (TOOLS_DIR / "post_run_checks.py").read_text(encoding="utf-8")
    reaching: List[str] = []
    for fn_ in ast.parse(prc_src).body:
        if isinstance(fn_, ast.FunctionDef):
            for nd in ast.walk(fn_):
                if isinstance(nd, ast.Call) and ast.unparse(nd.func) in ("subprocess.run", "subprocess.Popen", "subprocess.call", "subprocess.check_output", "os.system") and "runs_backup" in ast.unparse(nd):
                    reaching.append(fn_.name)
    check(reaching == ["tool_verify_new_increment"] and '"verify", "--source", source_rel' in prc_src and 'source_rel = f"runs/m8_rd_{session}"' in prc_src,
          f"post_run_checks reaches the tool's verify through one function only, with --source naming the sd2 tree: {reaching}")
    return {"modules": len(NEW_MODULES), "tools": len(PYTHON_TOOLS)}


def unit_no_nondeterminism_in_sd2() -> Dict[str, Any]:
    banned_mods = {"random", "secrets", "uuid"}
    for pth in [RL_DIR / f"{n}.py" for n in NEW_MODULES] + [RL_DIR / "m8_sd2_tests.py"] + [TOOLS_DIR / f for f in PYTHON_TOOLS]:
        src = pth.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for nd in ast.walk(tree):
            if isinstance(nd, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in nd.names] if isinstance(nd, ast.Import) else [nd.module or ""]
                check(not any(n.split(".")[0] in banned_mods for n in names), f"{pth.name} imports a source of randomness")
            if isinstance(nd, ast.Call):
                call = ast.unparse(nd.func)
                check(call != "os.urandom" and not call.startswith("random."), f"{pth.name}: {call}")
                if pth.parent == RL_DIR and pth.name != "m8_sd2_tests.py":
                    check(call != "time.sleep", f"{pth.name}: a sleep in a module")
    src = (RL_DIR / "m8_sd2_tests.py").read_text(encoding="utf-8")
    for fn in ast.walk(ast.parse(src)):
        if isinstance(fn, ast.FunctionDef) and fn.name != "unit_no_nondeterminism_in_sd2":
            for nd in ast.walk(fn):
                if isinstance(nd, ast.Call) and ast.unparse(nd.func) == "check":
                    cond = ast.unparse(nd.args[0]) if nd.args else ""
                    check("time.time" not in cond and "perf_counter" not in cond and "datetime" not in cond, f"{fn.name}: an assertion reads the wall clock: {cond[:80]}")
                if isinstance(nd, ast.Call) and ast.unparse(nd.func) == "time.sleep":
                    check(fn.name == "unit_launcher_refusals_and_head_check", f"{fn.name}: a sleep in the suite (only the launcher test waits on a detached process)")
            # a sleep is never a fixed delay: it is the body of a `while time.time() < deadline and <not yet>` loop, and the statement right after the loop is the check that fails on timeout
            def is_sleep(node: ast.AST) -> bool:
                return isinstance(node, ast.Call) and ast.unparse(node.func) == "time.sleep"

            allowed: set = set()
            for body in (getattr(n, f) for n in ast.walk(fn) for f in ("body", "orelse", "finalbody") if isinstance(getattr(n, f, None), list)):
                for i, st in enumerate(body):
                    if isinstance(st, ast.While) and any(is_sleep(x) for x in ast.walk(st)):
                        check(ast.unparse(st.test).startswith("time.time() < deadline and "), f"{fn.name}: a polling loop without a deadline: {ast.unparse(st.test)[:80]}")
                        check(i + 1 < len(body) and isinstance(body[i + 1], ast.Expr) and isinstance(body[i + 1].value, ast.Call) and ast.unparse(body[i + 1].value.func) == "check",
                              f"{fn.name}: a polling loop not followed by the check that fails on timeout")
                        allowed |= {id(x.value) for x in st.body if isinstance(x, ast.Expr) and is_sleep(x.value)}
            stray = [ast.unparse(x) for x in ast.walk(fn) if is_sleep(x) and id(x) not in allowed]
            check(not stray, f"{fn.name}: a sleep outside a bounded polling loop (a fixed delay): {stray}")
            if fn.name == "unit_launcher_refusals_and_head_check":
                check(len(allowed) == 2, f"the launcher test has exactly its two bounded polling waits, found {len(allowed)}")
    pre = (RL_DIR / "m8_sd2_session.py").read_text(encoding="utf-8")
    check('"integration"' not in pre and "INTEGRATION" not in pre and "cmd_run6_with_fake_game" not in {n for n, _fn in TESTS}, "no real-process test anywhere in the suite or the preflight")
    return {"modules": len(NEW_MODULES)}


def unit_tracked_files_unchanged6() -> Dict[str, Any]:
    check(ses6.ses1.tracked_changes() == [], f"tracked files differ from HEAD: {ses6.ses1.tracked_changes()[:5]}")
    check(ses6.ses1.untracked_not_new() == [], f"git status shows more than new files: {ses6.ses1.untracked_not_new()[:5]}")
    for f in EARLIER_FILES:
        r = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", str(RL_DIR / f"{f}.py")], cwd=REPO_ROOT)
        check(r.returncode == 0, f"{f}.py differs from HEAD")
        r = subprocess.run(["git", "ls-files", "--error-unmatch", str(RL_DIR / f"{f}.py")], cwd=REPO_ROOT, capture_output=True)
        check(r.returncode == 0, f"{f}.py is not tracked")
    for f in ("m9_artifacts.py", "m9_contract.py"):
        r = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", str(RL_DIR / f)], cwd=REPO_ROOT)
        check(r.returncode == 0, f"{f} differs from HEAD (the M9 writer is imported unchanged)")
    for f in ses5.TOOL_FILES:
        r = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", str(SD1_TOOLS_DIR / f)], cwd=REPO_ROOT)
        check(r.returncode == 0, f"tools/m8_sd1/{f} differs from HEAD (sd1's tools are untouched)")
    for d in ses6.DOC_FILES:
        r = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", str(REPO_ROOT / d)], cwd=REPO_ROOT)
        check(r.returncode == 0, f"{d} differs from HEAD")
        r = subprocess.run(["git", "ls-files", "--error-unmatch", str(REPO_ROOT / d)], cwd=REPO_ROOT, capture_output=True)
        check(r.returncode == 0, f"{d} is not tracked")
    return {"earlier_files": len(EARLIER_FILES)}


def unit_snapshot_tool6() -> Dict[str, Any]:
    import m8_sd2_snapshot as snap6

    check(snap6.NEVER_IN_THE_SET == ("logs/m8_sd2_run",) and "logs/m8_sd2_prep" in snap6.LOG_DIRS and "logs/m8_sd1_prep" in snap6.LOG_DIRS and "tools/m8_sd1" in snap6.TOOLS_DIRS and "tools/m8_sd2" in snap6.TOOLS_DIRS,
          "the file set: both tool folders, both preparation logs, never the launch-day logs")
    t = tmpdir("m8sn6_")
    dest = t / "snap"
    r = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_sd2_snapshot.py"), "snapshot", "--dest", str(dest)], capture_output=True, text=True, timeout=1800)
    check(r.returncode == 0, f"snapshot: {r.stdout[-500:]} {r.stderr[-500:]}")
    rec = json.loads((dest / "snapshot.json").read_text(encoding="utf-8"))
    check(art.is_stamped(rec) and rec["result"] == "PASS" and rec["n_files"] > 60 and not rec["problems"] and not rec["identity_code_mismatch"] and not rec["identity_docs_mismatch"]
          and rec["tool"] == "m8_sd2_source_snapshot_v1" and rec["source_fingerprint"] == ses6.source_fingerprint() and rec["never_in_the_set"] == ["logs/m8_sd2_run"],
          f"snapshot record: {rec['result']} {rec['problems']} {rec['identity_code_mismatch']} {rec['identity_docs_mismatch']}")
    names = {f["path"] for f in rec["files"]}
    check({"rl/m8_sd2_select.py", "rl/m8_sd2_run.py", "rl/m8_sd2_rule.py", "rl/m8_sd2_claims.py", "rl/m8_sd2_resume.py", "rl/m8_sd1_select.py", "rl/m8_rd4_run.py", "rl/m8_rd_select2.py", "rl/m9_artifacts.py",
           "tools/m8_sd2/launch_detached.ps1", "tools/m8_sd2/wait_session.py", "tools/m8_sd2/write_approval.py", "tools/m8_sd2/three_passes.py", "tools/m8_sd2/independent_increment_check.ps1",
           "tools/m8_sd2/check_launch.py", "tools/m8_sd2/copy_launch_evidence.py", "tools/m8_sd2/post_run_checks.py", "tools/m8_sd2/machine_sampler.py", "tools/m8_sd1/launch_detached.ps1",
           "docs/rl_m8_sd2_proposal_2026-10-12.md", "docs/rl_m8_sd1_prep_2026-10-11.md", "docs/rl_m8_sd1_approval.json", "docs/rl_m8_sd1_results_2026-10-11.md", "docs/rl_m8_rd4_results_2026-10-03.md",
           "logs/m8_sd2_prep/phase1_plan.md", "logs/m8_sd1_prep/phase1_plan.md"} <= names, f"the snapshot holds the sd2 code, both tool folders, the documents, both plans and the earlier code: missing {sorted(set(['rl/m8_sd2_select.py']) - names)}")
    check(not any(n.startswith("logs/m8_sd2_run/") for n in names) and not any("__pycache__" in n for n in names), "the launch-day log directory is never in the set")
    r = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_sd2_snapshot.py"), "verify", "--dest", str(dest)], capture_output=True, text=True, timeout=1800)
    check(r.returncode == 0, f"verify: {r.stdout[-300:]}")
    vrec = [p for p in dest.glob("verify_*.json")]
    check(vrec and art.is_stamped(json.loads(vrec[0].read_text(encoding="utf-8"))), "the verification record is stamped")
    r = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_sd2_snapshot.py"), "snapshot", "--dest", str(dest)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 2, "an existing destination is never overwritten")
    victim = dest / "files" / "rl" / "m8_sd2_select.py"
    victim.write_bytes(victim.read_bytes() + b"\n#tampered\n")
    r = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_sd2_snapshot.py"), "verify", "--dest", str(dest)], capture_output=True, text=True, timeout=1800)
    check(r.returncode == 1 and "m8_sd2_select.py" in r.stdout, "a tampered copy fails the verification")
    ps = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_sd2_snapshot.py"), "powershell", "--dest", str(dest)], capture_output=True, text=True, timeout=60)
    check("Get-FileHash" in ps.stdout, "the independent re-hash script is generated")
    shutil.rmtree(t, ignore_errors=True)
    return {"files": rec["n_files"]}


def unit_import_isolation6() -> Dict[str, Any]:
    code = ("import sys; sys.path.insert(0, r'%s'); " % RL_DIR + "import m8_sd2_artifacts, m8_sd2_select, m8_sd2_rule, m8_sd2_claims, m8_sd2_resume, m8_sd2_report, m8_sd2_run, m8_sd2_session; "
            "print(sorted(m for m in ('torch', 'numpy', 'gymnasium', 'stable_baselines3', 'm7u3_gate', 'm7f_trace', 'm7n_crossing', 'm7g_fixture', 'btt_learning', 'm7h_curriculum') if m in sys.modules))")
    r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=120)
    check(r.stdout.strip() == "[]", f"the sd2 modules imported heavy ones: {r.stdout.strip()} {r.stderr[-300:]}")
    return {}


def unit_tools6_parsers() -> Dict[str, Any]:
    """Every tool has an argument parser with required arguments; its refusals are exits; the fingerprint of the three-passes tool equals the session's; the preparation-record rule."""
    out: Dict[str, Any] = {}
    for f in SESSION_TOOLS:
        r = subprocess.run([sys.executable, "-B", str(TOOLS_DIR / f), "--help"], capture_output=True, text=True, timeout=300)
        check(r.returncode == 0 and "--session" in r.stdout and "required" not in r.stderr, f"{f} --help: {r.returncode} {r.stderr[-200:]}")
        r = subprocess.run([sys.executable, "-B", str(TOOLS_DIR / f)], capture_output=True, text=True, timeout=300)
        check(r.returncode == 2 and "required" in r.stderr, f"{f} without its required arguments exits 2: {r.returncode} {r.stderr[-200:]}")
        r = subprocess.run([sys.executable, "-B", str(TOOLS_DIR / f), "--session", "sd1"], capture_output=True, text=True, timeout=300)
        check(r.returncode == 2 and "invalid choice" in r.stderr, f"{f} refuses another session: {r.stderr[-200:]}")
        out[f] = "parser ok"
    r = subprocess.run([sys.executable, "-B", str(TOOLS_DIR / "machine_sampler.py"), "--help"], capture_output=True, text=True, timeout=300)
    check(r.returncode == 0 and "--once" in r.stdout and "--baseline-claude" in r.stdout, "the sampler's parser")
    r = subprocess.run([sys.executable, "-B", str(TOOLS_DIR / "machine_sampler.py")], capture_output=True, text=True, timeout=300)
    check(r.returncode == 2 and "required" in r.stderr, "the sampler needs its arguments")
    t = tmpdir("m8tools6_")
    for never in ("tools/m8_sd2/never", "tools/m8_sd1/never", "logs/m8_rd4_prep/x", "logs/m8_sd1_prep/x"):
        r = subprocess.run([sys.executable, "-B", str(TOOLS_DIR / "three_passes.py"), "--session", "sd2", "--out", never], capture_output=True, text=True, timeout=300)
        check(r.returncode == 2 and "never written again" in r.stdout, f"three_passes refuses {never}")
    (t / "passes.json").write_text("{}", encoding="utf-8")
    r = subprocess.run([sys.executable, "-B", str(TOOLS_DIR / "three_passes.py"), "--session", "sd2", "--out", str(t)], capture_output=True, text=True, timeout=300)
    check(r.returncode == 2 and "never overwritten" in r.stdout, "three_passes refuses to overwrite passes.json")
    tp = _load_tool("three_passes.py")
    repo_a = t / "repo_a"
    (repo_a / "docs").mkdir(parents=True)
    check(tp.refused_output_dir(repo_a, repo_a / "logs" / "m8_sd2_prep" / "x") == "", "before the preparation record exists, logs/m8_sd2_prep may receive the passes (the preparation itself)")
    (repo_a / "docs" / "rl_m8_sd2_prep_2026-10-12.md").write_text("x\n", encoding="utf-8")
    why = tp.refused_output_dir(repo_a, repo_a / "logs" / "m8_sd2_prep" / "x")
    check("never written again once a preparation record" in why, f"once a preparation record exists, logs/m8_sd2_prep is refused: {why}")
    check(tp.refused_output_dir(repo_a, repo_a / "logs" / "m8_sd2_run" / "partB" / "three_passes") == "" and "never written again" in tp.refused_output_dir(repo_a, repo_a / "tools" / "m8_sd2" / "x"), "the launch-day directory is allowed; the tool folder never")
    r = subprocess.run([sys.executable, "-B", str(TOOLS_DIR / "three_passes.py"), "--session", "sd2", "--out", "logs/m8_sd2_prep/zz", "--repo", str(repo_a)], capture_output=True, text=True, timeout=300)
    check(r.returncode == 2 and "preparation record" in r.stdout, "the CLI applies the preparation-record rule")
    env_no_b = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
    r = subprocess.run([sys.executable, str(TOOLS_DIR / "wait_session.py"), "--session", "sd2", "--repo", str(t)], capture_output=True, text=True, timeout=300, env=env_no_b)
    check(r.returncode == 2 and "python -B" in r.stdout, f"the tools refuse to run without -B: {r.returncode} {r.stdout[-200:]}")
    r = subprocess.run([sys.executable, "-B", str(TOOLS_DIR / "wait_session.py"), "--session", "sd2", "--repo", str(t)], capture_output=True, text=True, timeout=300)
    check(r.returncode == 1 and "no launch record" in r.stdout, "wait_session refuses a repository without a launch record")
    r = subprocess.run([sys.executable, "-B", str(TOOLS_DIR / "wait_session.py"), "--help"], capture_output=True, text=True, timeout=300)
    check("default 3.5" in r.stdout and "--poll-s" in r.stdout, "the waiter's default limit is 3.5 hours and it offers a poll interval")
    check(tp.fingerprint(REPO_ROOT) == ses6.source_fingerprint() and tp.GIT_GATE == "tracked_files_unchanged6" and "logs/m8_sd1_prep" in tp.NEVER_WRITTEN_AGAIN and "tools/m8_sd2" in tp.NEVER_WRITTEN_AGAIN
          and "logs/m8_sd2_prep" not in tp.NEVER_WRITTEN_AGAIN, "the tool's fingerprint equals the session's, over rl/m8_sd2_*.py and tools/m8_sd2/*; the never-written list")
    for f in PS_TOOLS:
        src = (TOOLS_DIR / f).read_text(encoding="utf-8")
        check("param(" in src and src.count("Mandatory=$true") >= 2, f"{f} declares mandatory parameters")
    launcher = (TOOLS_DIR / "launch_detached.ps1").read_text(encoding="utf-8")
    check("ValidateSet('sd2')" in launcher and "git_head" in launcher and "rev-parse HEAD" in launcher and "m8_rd_sd1" in launcher and "rl/m8_sd2_session.py" in launcher, "the launcher accepts sd2 only, checks HEAD against the approval and the predecessor's record")
    check((TOOLS_DIR / "independent_increment_check.ps1").read_bytes() == (SD1_TOOLS_DIR / "independent_increment_check.ps1").read_bytes(), "the independent re-hash script is sd1's (rd4's), byte for byte")
    shutil.rmtree(t, ignore_errors=True)
    return out


# -- the launch path's untested paths U1-U6 (zero native ticks; temporary layouts) -----------------------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=str(cwd), capture_output=True, text=True).stdout.strip()


def _launcher(repo: Path, session: str = "sd2") -> subprocess.CompletedProcess:
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(TOOLS_DIR / "launch_detached.ps1"), "-Session", session, "-Repo", str(repo)],
                          capture_output=True, text=True, timeout=300)


def unit_launcher_refusals_and_head_check() -> Dict[str, Any]:
    """U1: every refusal of launch_detached.ps1 on a temporary layout exits non-zero and creates nothing; the HEAD check refuses an approval written at another commit; the positive path starts a
    stub rl/m8_sd2_session.py (which only writes a done state) and records the pid, the time, the session and HEAD."""
    if not shutil.which("powershell") or not shutil.which("git"):
        return {"skipped": "powershell or git not available"}
    t = tmpdir("m8launch6_")
    repo = t / "repo"
    (repo / "rl").mkdir(parents=True)
    (repo / "docs").mkdir()
    stub = ("import json, sys\nfrom pathlib import Path\nroot = Path(__file__).resolve().parents[1]\nsd = root / 'runs' / 'm8_rd_sd2' / 'sessions' / 'sd2'\nsd.mkdir(parents=True)\n"
            "(sd / 'state.json').write_text(json.dumps({'phase': 'done', 'session': 'sd2', 'argv': sys.argv[1:]}), encoding='utf-8')\nprint('stub run done', sys.argv[1:])\n")
    (repo / "rl" / "m8_sd2_session.py").write_text(stub, encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "rl/m8_sd2_session.py")
    _git(repo, "commit", "-q", "-m", "stub")
    head = _git(repo, "rev-parse", "HEAD")
    check(len(head) == 40, f"a temporary git repository: {head}")
    pred = repo / "runs" / "m8_rd_sd1" / "sessions" / "sd1"
    pred.mkdir(parents=True)
    (pred / "rule.json").write_text("{}", encoding="utf-8")
    approval = repo / "docs" / "rl_m8_sd2_approval.json"

    def no_logs() -> bool:
        return not (repo / "logs").exists() and not (repo / "runs" / "m8_rd_sd2").exists()

    codes: Dict[str, int] = {}
    r = _launcher(t / "not_a_repo")
    codes["not_the_checkout"] = r.returncode
    check(r.returncode != 0 and "not the BattleShip checkout" in (r.stdout + r.stderr) and not (t / "not_a_repo" / "logs").exists(), "a repository that is not the checkout is refused")
    r = _launcher(repo)
    codes["no_approval"] = r.returncode
    check(r.returncode != 0 and "no approval record" in (r.stdout + r.stderr) and no_logs(), "no approval: refused, nothing created")
    approval.write_text(json.dumps({"approval": "APPROVED test", "git_head": "0" * 40}), encoding="utf-8")
    r = _launcher(repo)
    codes["head_mismatch"] = r.returncode
    check(r.returncode != 0 and "differs from the approval's git_head" in (r.stdout + r.stderr) and no_logs(), "an approval written at another HEAD is refused (S2), nothing created")
    approval.write_text(json.dumps({"approval": "APPROVED test"}), encoding="utf-8")
    r = _launcher(repo)
    codes["no_head_in_approval"] = r.returncode
    check(r.returncode != 0 and "carries no git_head" in (r.stdout + r.stderr) and no_logs(), "an approval without git_head is refused")
    approval.write_text(json.dumps({"approval": "APPROVED test", "git_head": head}), encoding="utf-8")
    (pred / "rule.json").unlink()
    r = _launcher(repo)
    codes["no_predecessor"] = r.returncode
    check(r.returncode != 0 and "no sd1 decision record" in (r.stdout + r.stderr) and no_logs(), "no sd1 rule record: refused")
    (pred / "rule.json").write_text("{}", encoding="utf-8")
    (repo / "runs" / "m8_rd_sd2").mkdir()
    r = _launcher(repo)
    codes["run_root_exists"] = r.returncode
    check(r.returncode != 0 and "never overwritten" in (r.stdout + r.stderr) and not (repo / "logs").exists(), "an existing run root: refused")
    (repo / "runs" / "m8_rd_sd2").rmdir()
    (repo / "logs" / "m8_sd2_run").mkdir(parents=True)
    (repo / "logs" / "m8_sd2_run" / "session_stdout.txt").write_text("", encoding="utf-8")
    r = _launcher(repo)
    codes["session_log_exists"] = r.returncode
    check(r.returncode != 0 and "never relaunched" in (r.stdout + r.stderr) and not (repo / "runs" / "m8_rd_sd2").exists(), "an existing session log: refused")
    shutil.rmtree(repo / "logs")
    r = _launcher(repo, "sd1")
    codes["other_session"] = r.returncode
    check(r.returncode != 0 and no_logs(), "another session name is refused by the parameter set")
    r = _launcher(repo)
    codes["positive"] = r.returncode
    rec_p = repo / "logs" / "m8_sd2_run" / "launch_record.txt"
    check(r.returncode == 0 and rec_p.is_file(), f"the positive path launches: {r.returncode} {(r.stdout + r.stderr)[-300:]}")
    rec = rec_p.read_text(encoding="utf-8-sig").strip()
    check(rec.startswith("launched pid=") and " session=sd2 " in rec + " " and f"head={head}" in rec and "launched pid=" in r.stdout, f"the launch record: {rec}")
    state_p = repo / "runs" / "m8_rd_sd2" / "sessions" / "sd2" / "state.json"
    stdout_p = repo / "logs" / "m8_sd2_run" / "session_stdout.txt"
    deadline = time.time() + 60                       # a bounded polling wait for the detached process; the check right after it fails the test on timeout (never a fixed delay)
    while time.time() < deadline and not state_p.is_file():
        time.sleep(0.5)
    check(state_p.is_file() and json.loads(state_p.read_text(encoding="utf-8")).get("phase") == "done", "the detached stub ran to its done state within 60 s")
    deadline = time.time() + 30
    while time.time() < deadline and "stub run done" not in stdout_p.read_text(encoding="utf-8", errors="replace"):
        time.sleep(0.5)
    check("stub run done" in stdout_p.read_text(encoding="utf-8", errors="replace") and "'run'" in stdout_p.read_text(encoding="utf-8", errors="replace"),
          f"the stub received `run` and its stdout was captured within 30 s: {stdout_p.read_text(encoding='utf-8', errors='replace')[:120]}")
    r = _launcher(repo)
    codes["second_launch"] = r.returncode
    check(r.returncode != 0 and "never relaunched" in (r.stdout + r.stderr), "a second launch is refused (the session log exists)")
    shutil.rmtree(t, ignore_errors=True)
    return codes


def unit_waiter_exits() -> Dict[str, Any]:
    """U2: wait_session.py's error exits on temporary layouts (short polls): no record; another session's record; a dead pid with a done state (exit 0); a dead pid without a done state; the hard limit."""
    t = tmpdir("m8wait6_")
    logs = t / "logs" / "m8_sd2_run"
    logs.mkdir(parents=True)
    sd = t / "runs" / "m8_rd_sd2" / "sessions" / "sd2"
    sd.mkdir(parents=True)
    tool = TOOLS_DIR / "wait_session.py"

    def run(*extra: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", "-X", "utf8", str(tool), "--session", "sd2", "--repo", str(t), "--poll-s", "1", *extra], capture_output=True, text=True, timeout=300)

    r = run()
    check(r.returncode == 1 and "no launch record" in r.stdout, f"no launch record: {r.stdout[-200:]}")
    (logs / "launch_record.txt").write_text("launched pid=99999999 at 2026-10-12T00:00:00Z session=sd1\n", encoding="utf-8")
    r = run()
    check(r.returncode == 1 and "not 'sd2'" in r.stdout, f"another session's record: {r.stdout[-200:]}")
    (logs / "launch_record.txt").write_text("﻿launched pid=99999999 at 2026-10-12T00:00:00Z session=sd2 head=abc\n", encoding="utf-8")
    (sd / "state.json").write_text(json.dumps({"phase": "done", "session": "sd2", "decision": "NO_SHORTER_CLEAR"}), encoding="utf-8")
    r = run()
    check(r.returncode == 0 and '"done": true' in r.stdout and '"decision": "NO_SHORTER_CLEAR"' in r.stdout, f"a done state with the process gone: exit 0: {r.stdout[-200:]}")
    check((logs / "wait_log.txt").is_file() and len((logs / "wait_log.txt").read_text(encoding="utf-8").splitlines()) >= 1, "one progress line per change")
    (sd / "state.json").write_text(json.dumps({"phase": "verify", "session": "sd2"}), encoding="utf-8")
    r = run()
    check(r.returncode == 1 and "exited without a done state" in r.stdout, f"a dead process without a done state: {r.stdout[-200:]}")
    (sd / "state.json").unlink()
    r = run("--hours", "0.0006")
    check(r.returncode == 1 and "hard timeout" in r.stdout and "the waiter's own limit" in r.stdout, f"the hard limit ends the waiter only: {r.stdout[-200:]}")
    r = run("--poll-s", "0.5")
    check(r.returncode == 2 and "at least 1 second" in r.stdout, "a poll interval below one second is refused")
    shutil.rmtree(t, ignore_errors=True)
    return {"cases": 6}


def unit_check_launch_tool() -> Dict[str, Any]:
    """U3: check_launch.py prints every condition and exits 0 (all hold), 3 (only the age limit fails), 1 (any other failure) or 2 (no record), each case on a temporary layout."""
    cl = _load_tool("check_launch.py")
    t = tmpdir("m8s7_")
    logs = t / "logs" / "m8_sd2_run"
    logs.mkdir(parents=True)
    me = os.getpid()
    now = time.time()
    fresh = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 10))
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 600))
    codes: Dict[str, int] = {}

    def record(pid: int, when: str, session: str = "sd2") -> None:
        (logs / "launch_record.txt").write_text(f"launched pid={pid} at {when} session={session} head=abc\n", encoding="utf-8")

    def cli() -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", "-X", "utf8", str(TOOLS_DIR / "check_launch.py"), "--session", "sd2", "--repo", str(t)], capture_output=True, text=True, timeout=300)

    r = cli()
    codes["no_record"] = r.returncode
    check(r.returncode == 2 and "NO_RECORD" in r.stdout, f"no record: exit 2: {r.stdout}")
    (logs / "session_stdout.txt").write_text("", encoding="utf-8")
    (logs / "session_stderr.txt").write_text("", encoding="utf-8")
    record(me, fresh)
    r = cli()
    codes["all_hold"] = r.returncode
    check(r.returncode == 0 and "PASS" in r.stdout and all(k in r.stdout for k in ("record", "alive", "age", "refused", "traceback", "game")), f"a fresh launch of a live pid: exit 0 with every condition printed: {r.stdout}")
    record(me, old)
    r = cli()
    codes["late_only"] = r.returncode
    check(r.returncode == 3 and "LATE_ONLY" in r.stdout, f"only the age limit fails: exit 3: {r.stdout}")
    record(me, fresh)
    (logs / "session_stdout.txt").write_text("refused: preflight problems\n", encoding="utf-8")
    r = cli()
    codes["refused_word"] = r.returncode
    check(r.returncode == 1 and "FAIL (refused)" in r.stdout and "preflight problems" in r.stdout, f"a refusal in stdout: exit 1 with the line quoted: {r.stdout}")
    (logs / "session_stdout.txt").write_text("", encoding="utf-8")
    (logs / "session_stderr.txt").write_text("Traceback (most recent call last):\n  boom\n", encoding="utf-8")
    r = cli()
    codes["traceback"] = r.returncode
    check(r.returncode == 1 and "FAIL (traceback)" in r.stdout, f"a traceback in stderr: exit 1: {r.stdout}")
    (logs / "session_stderr.txt").write_text("", encoding="utf-8")
    record(99999999, fresh)
    r = cli()
    codes["dead_pid"] = r.returncode
    check(r.returncode == 1 and "FAIL (alive)" in r.stdout, f"a dead pid: exit 1: {r.stdout}")
    record(99999999, old)
    (logs / "session_stdout.txt").write_text("refused\n", encoding="utf-8")
    r = cli()
    codes["late_and_other"] = r.returncode
    check(r.returncode == 1 and "FAIL (" in r.stdout and "age" in r.stdout, f"late AND another failure: exit 1, not 3: {r.stdout}")
    (logs / "session_stdout.txt").write_text("", encoding="utf-8")
    record(me, fresh, "sd1")
    r = cli()
    codes["other_session"] = r.returncode
    check(r.returncode == 2, "another session's record: exit 2")
    lines = (logs / "s7_check.txt").read_text(encoding="utf-8").splitlines()
    check(sum(1 for ln in lines if ln.startswith("S7 check ")) == 8 and sum(1 for ln in lines if ln.startswith("{")) == 8, "every check appended its text and its JSON record to s7_check.txt")
    # the pure logic with a controlled clock
    record(me, fresh)
    res = cl.check(t, "sd2", 120.0, now)
    check(res["exit"] == cl.EXIT_OK and res["conditions"]["age"]["age_s"] >= 9, "check() with a controlled clock")
    res = cl.check(t, "sd2", 5.0, now)
    check(res["exit"] == cl.EXIT_LATE_ONLY, "a shorter window makes the same launch late")
    check(cl.EXIT_OK == 0 and cl.EXIT_OTHER_FAILURE == 1 and cl.EXIT_NO_RECORD == 2 and cl.EXIT_LATE_ONLY == 3, "the exit codes")
    shutil.rmtree(t, ignore_errors=True)
    return codes


def unit_copy_launch_evidence_tool() -> Dict[str, Any]:
    """U5: copy_launch_evidence.py on a temporary tree: stamped JSON kept, unstamped JSON-like files copied as .txt, derived/ holding exactly two files, the snapshot records copied, the final
    verify-run patched; the refusals (not done, verify_run not ok, missing report, no approval, an existing launch/)."""
    cle = _load_tool("copy_launch_evidence.py")
    t = tmpdir("m8copy6_")
    repo = t / "repo"
    logs = repo / "logs" / "m8_sd2_run"
    root = repo / "runs" / "m8_rd_sd2"
    (logs / "partB" / "three_passes").mkdir(parents=True)
    (root / "sessions" / "sd2").mkdir(parents=True)
    (repo / "docs").mkdir()
    snap = t / "snap"
    snap.mkdir()
    art.write_json5(snap / "snapshot.json", {"tool": "m8_sd2_source_snapshot_v1", "result": "PASS"})
    art.write_json5(snap / "verify_2026-10-13T000000Z.json", {"result": "PASS"})
    art.write_json5(repo / "docs" / "rl_m8_sd2_approval.json", {"approval": "APPROVED test", "source_snapshot": {"dest": str(snap)}})
    art.write_json5(root / "sessions" / "sd2" / "state.json", {"phase": "verify"})
    art.write_json5(logs / "verify_run.json", {"ok": True, "problems": []})
    art.write_json5(logs / "report.json", {"sd2": {}})
    art.write_json5(logs / "preflight_full.json", {"ok": True})
    art.write_json5(logs / "partB" / "three_passes" / "passes.json", {"verdict": "THREE_CONSECUTIVE_PASSES"})
    (logs / "b2_line.json").write_text('{"hand": "capture"}\n', encoding="utf-8")
    (logs / "machine_samples.jsonl").write_text('{"t": 1}\n{"t": 2}\n', encoding="utf-8")
    (logs / "wait_log.txt").write_text("x\n", encoding="utf-8")
    (logs / "s7_check.txt").write_text("S7\n", encoding="utf-8")
    art.append_jsonl5(logs / "rows_ok.jsonl", {"r": 1}, "s")
    with gzip.open(logs / "trace_ok.json.gz", "wt", encoding="utf-8") as f:
        json.dump(art.stamp({"steps": []}), f)
    with gzip.open(logs / "trace_bad.json.gz", "wt", encoding="utf-8") as f:
        json.dump({"steps": []}, f)
    calls: List[Tuple[Path, Path]] = []

    def fake_verify(repo_: Path, out: Path) -> Tuple[int, Optional[bool]]:
        calls.append((repo_, out))
        out.write_text(json.dumps(art.stamp({"ok": True})), encoding="utf-8")
        return 0, True

    cle.run_verify_run = fake_verify
    saved_argv = sys.argv

    def run_cle() -> int:
        sys.argv = ["copy_launch_evidence.py", "--session", "sd2", "--repo", str(repo)]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cle.main()
        run_cle.out = buf.getvalue()           # type: ignore[attr-defined]
        return code

    try:
        check(run_cle() == 2 and "not done" in run_cle.out and not (root / "launch").exists(), "a session that is not done is refused")        # type: ignore[attr-defined]
        art.write_json5(root / "sessions" / "sd2" / "state.json", {"phase": "done"})
        art.write_json5(logs / "verify_run.json", {"ok": False, "problems": ["x"]})
        check(run_cle() == 2 and "does not say ok" in run_cle.out, "a verify-run that does not say ok is refused")                            # type: ignore[attr-defined]
        art.write_json5(logs / "verify_run.json", {"ok": True, "problems": []})
        (logs / "report.json").rename(logs / "report_moved.json")
        check(run_cle() == 2 and "report.json" in run_cle.out, "a missing report is refused")                                                 # type: ignore[attr-defined]
        (logs / "report_moved.json").rename(logs / "report.json")
        (repo / "docs" / "rl_m8_sd2_approval.json").rename(repo / "docs" / "approval_moved.json")
        check(run_cle() == 2 and "no approval" in run_cle.out, "a missing approval is refused")                                               # type: ignore[attr-defined]
        (repo / "docs" / "approval_moved.json").rename(repo / "docs" / "rl_m8_sd2_approval.json")
        code = run_cle()
        check(code == 0 and calls and calls[0] == (repo, logs / "verify_run_after_copies.json"), f"the positive path: exit 0 and verify-run run once afterwards: {run_cle.out[-300:]}")   # type: ignore[attr-defined]
        check(sorted(p.name for p in (root / "derived").iterdir()) == ["report.json", "verify_run.json"], "derived/ holds exactly verify_run.json and report.json")
        launch = root / "launch"
        names = sorted(p.relative_to(launch).as_posix() for p in launch.rglob("*") if p.is_file())
        check("preflight_full.json" in names and "partB/three_passes/passes.json" in names and "rows_ok.jsonl" in names and "trace_ok.json.gz" in names, f"stamped records are kept as they are: {names}")
        check("b2_line.json.txt" in names and "machine_samples.jsonl.txt" in names and "trace_bad.json.gz.txt" in names and "b2_line.json" not in names, f"unstamped JSON-like files become .txt: {names}")
        check("wait_log.txt" in names and "s7_check.txt" in names and "verify_run.json" not in names and "report.json" not in names, "text files are copied; the two derived records are not duplicated")
        check("source_snapshot_record.json" in names and "snapshot_verify_2026-10-13T000000Z.json" in names, "the snapshot record and its verification are copied")
        aud = art.audit_tree6(root)
        check(aud["ok"], f"the tree's stamp audit stays clean after the copies: {aud['failures']}")
        check(run_cle() == 2 and "made once" in run_cle.out, "a second run is refused (launch/ exists)")                                        # type: ignore[attr-defined]
    finally:
        sys.argv = saved_argv
    check(cle.valid_stamped_record(logs / "preflight_full.json") and not cle.valid_stamped_record(logs / "b2_line.json") and cle.valid_stamped_record(logs / "rows_ok.jsonl")
          and not cle.valid_stamped_record(logs / "machine_samples.jsonl") and cle.is_json_like("a.jsonl.gz") and not cle.is_json_like("a.json.tmp") and not cle.is_json_like("a.txt"), "the stamp test")
    shutil.rmtree(t, ignore_errors=True)
    return {"launch_files": len(names)}


def unit_post_run_checks_tool() -> Dict[str, Any]:
    """U6: post_run_checks.py on a temporary layout: the independent re-hash of every registered increment (one tampered tree FAILs), the skipped folders with their reasons, the refusal of
    --tool-verify without exactly one sd2 increment, R1 and the coverage patched; the tool's verify is reachable through one function only."""
    if not shutil.which("powershell"):
        return {"skipped": "powershell not available"}
    import runs_backup as rb

    prc = _load_tool("post_run_checks.py")
    t = tmpdir("m8post6_")
    repo = t / "repo"
    logs = repo / "logs" / "m8_sd2_run"
    logs.mkdir(parents=True)
    backup = t / "D"
    backup.mkdir()
    for name in ("treeA", "treeB"):
        d = repo / "runs" / name / "archive"
        d.mkdir(parents=True)
        (d / "a.txt").write_text(f"{name} a\n", encoding="utf-8")
        (d / "b.bin").write_bytes(bytes(range(64)))
        with contextlib.redirect_stdout(io.StringIO()):
            check(rb.cmd_backup(repo / "runs" / name, backup / f"2026-10-12_incr_{name}", 2) == 0, f"the synthetic increment of {name}")
    (backup / "no_record").mkdir()
    (backup / "2026-10-12_incr_fail").mkdir()
    (backup / "2026-10-12_incr_fail" / "verification.json").write_text(json.dumps({"result": "FAIL", "source": str(repo / "runs" / "treeA")}), encoding="utf-8")
    (backup / "2026-10-12_incr_gone").mkdir()
    (backup / "2026-10-12_incr_gone" / "verification.json").write_text(json.dumps({"result": "PASS", "source": str(repo / "runs" / "gone")}), encoding="utf-8")
    (backup / "2026-10-12_incr_outside").mkdir()
    (backup / "2026-10-12_incr_outside" / "verification.json").write_text(json.dumps({"result": "PASS", "source": str(t)}), encoding="utf-8")
    reg = prc.registered_increments(repo, backup)
    check([i["folder"] for i in reg["increments"]] == ["2026-10-12_incr_treeA", "2026-10-12_incr_treeB"] and {s["folder"] for s in reg["skipped"]} == {"no_record", "2026-10-12_incr_fail", "2026-10-12_incr_gone", "2026-10-12_incr_outside"},
          f"the registered increments and the skipped folders: {reg}")
    orig_tool_verify = prc.tool_verify_new_increment
    prc.r1_check = lambda repo_: {"ok": True, "patched": True}
    prc.coverage_check = lambda repo_: {"ok": True, "uncovered": 0, "source_files": 4, "increments": 2}
    saved_argv = sys.argv

    def run_prc(*extra: str) -> Tuple[int, str]:
        sys.argv = ["post_run_checks.py", "--session", "sd2", "--repo", str(repo), "--backup-root", str(backup), *extra]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = prc.main()
        return code, buf.getvalue()

    try:
        code, out = run_prc()
        check(code == 0 and out.count("PASS 2026-10-12_incr_tree") == 2, f"two untampered increments re-hash PASS: {out[-400:]}")
        rec = json.loads((logs / "post_run_checks.json").read_text(encoding="utf-8"))
        check(art.is_stamped(rec) and rec["ok"] and len(rec["independent_rehash"]) == 2 and all(r["pass"] for r in rec["independent_rehash"]) and len(rec["skipped"]) == 4 and rec["r1_five_trees"]["patched"]
              and rec["tool_verify_new_increment"] is None and rec["never_tool_verify_on_earlier_increments"] is True and (logs / "post_increments" / "2026-10-12_incr_treeA.txt").is_file(), "the stamped record")
        (repo / "runs" / "treeB" / "archive" / "a.txt").write_text("tampered\n", encoding="utf-8")
        code, out = run_prc()
        check(code == 1 and "FAIL 2026-10-12_incr_treeB" in out and "PASS 2026-10-12_incr_treeA" in out, f"a tampered tree makes its re-hash FAIL and the tool exit 1: {out[-400:]}")
        code, out = run_prc("--tool-verify")
        check(code == 2 and "exactly one folder" in out, "the tool's verify with no sd2 increment is refused")
        (backup / "2026-10-12_incr_m8_rd_sd2").mkdir()
        (backup / "2026-10-13_incr_m8_rd_sd2").mkdir()
        code, out = run_prc("--tool-verify")
        check(code == 2 and "exactly one folder" in out, "the tool's verify with two sd2 increments is refused")
        shutil.rmtree(backup / "2026-10-13_incr_m8_rd_sd2")
        seen: List[Path] = []
        prc.tool_verify_new_increment = lambda repo_, dest, session: (seen.append(dest) or {"dest": str(dest), "source": f"runs/m8_rd_{session}", "exit": 0, "last_line": "verification PASS", "pass": True})
        (repo / "runs" / "treeB" / "archive" / "a.txt").write_text("treeB a\n", encoding="utf-8")
        code, out = run_prc("--tool-verify")
        check(code == 0 and seen == [backup / "2026-10-12_incr_m8_rd_sd2"], "with exactly one sd2 increment the tool's verify is asked on that folder only")
    finally:
        sys.argv = saved_argv
    src = inspect.getsource(orig_tool_verify)
    check('"verify", "--source", source_rel' in src and 'source_rel = f"runs/m8_rd_{session}"' in src, "the tool's verify names the sd2 tree as its source")
    shutil.rmtree(t, ignore_errors=True)
    return {"increments": 2, "skipped": 4}


def unit_machine_sampler_once() -> Dict[str, Any]:
    t = tmpdir("m8samp6_")
    r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(TOOLS_DIR / "machine_sampler.py"), "--out", str(t / "s.jsonl"), "--alerts", str(t / "a.txt"), "--baseline-claude", "", "--once"],
                       capture_output=True, text=True, timeout=300)
    check(r.returncode == 0, f"one sample: {r.returncode} {r.stderr[-200:]}")
    rows = [json.loads(ln) for ln in (t / "s.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    check(len(rows) == 1 and set(rows[0]) >= {"t", "available_mb", "commit_free_mb", "counts", "battleship", "claude", "python", "other", "alerts"} and isinstance(rows[0]["battleship"], int), f"the sample's keys: {sorted(rows[0])}")
    ms = _load_tool("machine_sampler.py")
    check("battleship.exe" in ms.WATCH and "node.exe" in ms.ALERT and "msedge.exe" in ms.ALERT and "kill" not in (TOOLS_DIR / "machine_sampler.py").read_text(encoding="utf-8").lower().replace("never kills", ""),
          "the watched and alerted names; the sampler never kills")
    shutil.rmtree(t, ignore_errors=True)
    return {"keys": len(rows[0])}


# -- APPEND_POINT_C --


def _earlier(name: str, table: Sequence[Tuple[str, Callable[[], Dict[str, Any]]]], prefix: str) -> Tuple[str, Callable[[], Dict[str, Any]]]:
    fn = dict(table)[name]
    return f"{prefix}:{name}", fn


TESTS: List[Tuple[str, Callable[[], Dict[str, Any]]]] = [
    ("sd2_contract", unit_sd2_contract), ("select_v4_reference_parametrisation", unit_select_v4_reference_parametrisation), ("record_bound_by_session", unit_record_bound_by_session),
    ("archive6_draw_and_mode_switch", unit_archive6_draw_and_mode_switch), ("begin_sd2_and_persistence", unit_begin_sd2_and_persistence), ("ledger_rebuild6", unit_ledger_rebuild6),
    ("resume_five_level_synthetic", unit_resume_five_level_synthetic), ("inherited_record_facts_refusal6", unit_inherited_record_facts_refusal6),
    ("write_guard_all_runs_roots6", unit_write_guard_all_runs_roots6), ("claims6_pool_and_plan", unit_claims6_pool_and_plan), ("clear_exactness6_on_stub_traces", unit_clear_exactness6_on_stub_traces),
    ("inherited_descriptive_candidates6", unit_inherited_descriptive_candidates6), ("rule6_module", unit_rule6_module), ("decide6_outcomes_and_stops", unit_decide6_outcomes_and_stops),
    ("session6_small_run", unit_session6_small_run), ("session6_determinism", unit_session6_determinism), ("session6_inherited_continuations", unit_session6_inherited_continuations),
    ("session6_record_replay_at_open", unit_session6_record_replay_at_open), ("budget_projection6", unit_budget_projection6), ("approval_isolated6", unit_approval_isolated6),
    ("results_record_rule6", unit_results_record_rule6),
    ("artifacts6_stamping", unit_artifacts6_stamping), ("task_block_pinned6", unit_task_block_pinned6), ("source_guard6", unit_source_guard6), ("no_nondeterminism_in_sd2", unit_no_nondeterminism_in_sd2),
    ("tracked_files_unchanged6", unit_tracked_files_unchanged6), ("snapshot_tool6", unit_snapshot_tool6), ("import_isolation6", unit_import_isolation6), ("tools6_parsers", unit_tools6_parsers),
    ("launcher_refusals_and_head_check", unit_launcher_refusals_and_head_check), ("waiter_exits", unit_waiter_exits), ("check_launch_tool", unit_check_launch_tool),
    ("copy_launch_evidence_tool", unit_copy_launch_evidence_tool), ("post_run_checks_tool", unit_post_run_checks_tool), ("machine_sampler_once", unit_machine_sampler_once),
    ("open_protocol_real_trees6", unit_open_protocol_real_trees6),
] + [_earlier(n, t5.TESTS, "sd1") for n in SD1_PURE] + [_earlier(n, t4.TESTS, "rd4") for n in RD4_PURE] + [_earlier(n, t3.TESTS, "rd3") for n in RD3_PURE] + [_earlier(n, t1.TESTS, "rd1") for n in RD1_PURE] \
    + [_earlier(n, t2.TESTS, "rd2") for n in RD2_PURE]


def _cleanup() -> None:
    while _TMP:
        shutil.rmtree(_TMP.pop(), ignore_errors=True)
    t5._cleanup()


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
    for rec in list(_CHAIN6.values()) + list(t5._CHAIN5.values()) + list(t4._CHAIN4.values()) + list(t3._CHAIN.values()):
        shutil.rmtree(rec["t"], ignore_errors=True)
    for rec in getattr(t2, "_SYN", {}).values():
        shutil.rmtree(rec["t"], ignore_errors=True)
    total = passed + len(failed)
    if out is not None:
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "m8_sd2_unit.json").write_text(json.dumps({"passed": passed, "total": total, "failed": failed, "wall_s": round(time.perf_counter() - t_all, 1), "results": results}, indent=1,
                                                         default=str) + "\n", encoding="utf-8")
    print(f"{passed} / {total} passed (unit); wall {time.perf_counter() - t_all:.0f} s")
    return 0 if not failed else 1


# -- the production-count synthetic end-to-end run ---------------------------------------------------------------------------------------------------------------


def e2e_digest(root6: Path) -> str:
    """sha256 (16 hex) of the run's signature: the four data files' hashes (the host frame masked), both session events, both overlay digests, the rule record's registered fields, the
    verification's pools and replay order, the inherited counts, the line status. Wall-clock and memory readings are excluded."""
    return hashlib.sha256(json.dumps(signature6(root6), sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def e2e(out: Path, small: bool = False, world: str = CHAIN_WORLD) -> int:
    """The sd2 session at the registered counts (6,000,000 exploration ticks valid from 2,000,000, five workers, 16 identity replays, the registered caps) against a synthetic five-tree chain
    (rd1, rd2, rd3, rd4 and sd1 by their own real engines, each with its verified increment, sd1 carrying a verified clear below the synthetic record) and the stub, through the lock-step pool
    and the virtual clock: the five-level resume (R1-R6), both overlays, the selection `m8_rd_select_v4` under sd2's draws at the new bound, P1 against the archive's pin, the open identity
    replays and the record (sd1's clear) re-verified, the fastest-first verification of the clear pool, the inherited descriptive replays by the rule, the close audit of the six-part ledger,
    the prefix chain of six, the stamp audit and verify-run, with rd4's claim cases (a) and (b) as the session's first dispatches. The run is a pure function of its configuration; its digest
    is the last line printed. The world is synthetic: the outcome says nothing about Mario."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    problems: List[str] = []
    t0 = time.perf_counter()
    chain = build_chain6(world, cache=False)
    e5 = chain["expect5"]
    rr = e5["inherited_record"]["best_verified"]
    print(f"[e2e] synthetic chain built in {time.perf_counter() - t0:.0f} s: rd1 {chain['expect1']['cells']} cells, rd2 {chain['expect2']['cells']}, rd3 {chain['expect3']['cells']}, rd4 {chain['expect4']['cells']}, "
          f"sd1 {e5['cells']} cells; sd1 {chain['sd1_outcome']} at {chain['sd1_best']}; the record {rr['completion_input_tick']} / {rr['completion_time_passed']} (previous {e5['sd1_record_reference']['completion_input_tick']}); "
          f"{len(e5['inherited_record']['unverified_clear_trajectories'])} unverified trajectories", flush=True)
    cp = copy_chain6(chain)
    root6 = out / "sd2"
    if root6.exists():
        shutil.rmtree(root6)
    kw: Dict[str, Any] = dict(checkpoint_every_s=20.0)
    if small:
        kw.update(arm_tick_cap=200000, arm_caps={"T": 200000}, min_arm_ticks=60000, p1_tick_cap=70000)
    cfg = ses6.run_config(root=root6, **kw)
    op, a6 = open_chain6(cp, root6)
    cfg.session_dir.mkdir(parents=True)
    mw.ProvenanceGuard.install()
    mw.ProvenanceGuard.violations.clear()
    roots = [cp["rd1"], cp["rd2"], cp["rd3"], cp["rd4"], cp["sd1"]]
    w2.WriteGuard.install(roots)
    logs: List[str] = []

    def log(s: str) -> None:
        line = f"[e2e {time.strftime('%H:%M:%S')}] {s}"
        logs.append(line)
        print(line, flush=True)

    clock = FakeClock()
    env = sync_env(world, roots, clock, pins=cp["pins"], log=log)
    try:
        import m7u_gate as g1

        env.private_mb = g1.private_mb
    except Exception:  # noqa: BLE001
        pass
    t1_ = time.perf_counter()
    cls = t4.forced_session_cls(world, ("left_nolanding", "wall_continuation"), base=run6.Session6)
    sess = cls(cfg, env, archive=a6, archive_pin=op["facts5"]["pin_tick0"], base_info={"open_overlay_sha256": op["overlay"]["v4"]["sha256"]}, rd1_root=cp["rd1"], rd2_root=cp["rd2"], rd3_root=cp["rd3"],
               rd4_root=cp["rd4"], sd1_root=cp["sd1"], lines_sha256=cp["lines"], ckpt_seq=int(op["facts5"]["sd1_checkpoint_seq"]) + 1, archive_created_utc=OPEN_UTC, record_candidate=op["record_candidate"],
               inherited=op["inherited"], sd1_line=op["facts5"]["sd1_line"])
    sess.pool = SyncPool(env, cfg, clock)
    res = run6.run_all6(sess, immutability=lambda: all_immutability6(cp))
    wall = time.perf_counter() - t1_
    w2.WriteGuard.clear()
    rule, close = res["rule"], res["close"]
    vr = rpt6.verify_run6(root6, cp["sd1"], cp["rd4"], cp["rd3"], cp["rd2"], cp["rd1"], "sd2")
    report = rpt6.full_report6(root6, cp["sd1"], cp["rd4"], cp["rd3"], cp["rd2"], cp["rd1"], "sd2")
    want = cfg.arm_cap("T")
    if sess.ledgers["T"].ticks != want:
        problems.append(f"exploration ticks {sess.ledgers['T'].ticks} != {want}")
    if rule["outcome"] in ("INVALID", "INCOMPLETE"):
        problems.append(f"outcome {rule['outcome']}: {rule['invalid']} {rule['incomplete']}")
    if not vr["ok"]:
        problems.append(f"verify-run: {vr['problems']}")
    for k in ("audit", "prefix_chain", "earlier_trees_immutability", "artifacts"):
        if not close.get(k, {}).get("ok"):
            problems.append(f"close {k}: {close.get(k)}")
    if mw.ProvenanceGuard.violations:
        problems.append(f"guard violations {mw.ProvenanceGuard.violations[:2]}")
    if not all_immutability6(cp)["ok"]:
        problems.append("a synthetic earlier tree changed")
    ver = json.loads((root6 / "sessions" / "sd2" / "verification.json").read_text(encoding="utf-8"))
    io_ = sess.open_identity_record
    if not (io_.get("ok") and io_.get("cells") == 16 and ver["identity"].get("verified") == ver["identity"].get("cells") == 16):
        problems.append(f"identity replays: open {io_.get('verified')}/{io_.get('cells')}, close {ver['identity']}")
    if not sess.record_open_record.get("exact"):
        problems.append(f"the record did not re-verify at the open: {sess.record_open_record}")
    if sess.first_iteration != e5["dispatch_iterations"][1] + 1:
        problems.append("iterations do not continue from sd1's last")
    arm = ver["arm"]
    led = sess.ledgers["T"]
    ticks_of = {c["cid"]: cl6.clear_tick(c) for c in led.candidates}
    order = arm["replay_order"]
    if order != sorted(order, key=lambda cid: (ticks_of[cid], cid)) or any(led.candidates[cid]["kind"] != "clear" for cid in order):
        problems.append(f"the pool was not replayed fastest first, clear-kind only: {order}")
    if (arm["best_verified"] is not None) != arm["closed"] or arm["remaining_faster_than_best"] != 0:
        problems.append("the pool did not close at the first exact replay")
    inh = ver["inherited_descriptive"]
    if inh["count"] != len(e5["inherited_record"]["unverified_clear_trajectories"]) or inh["replayed"] != inh["count"] or inh["exact"] != inh["count"] or rule["flags"]:
        problems.append(f"the inherited descriptive replays (the rule's count on the synthetic registry): {inh} flags {rule['flags']}")
    forced = {f["kind"]: f for f in sess.forced}
    if set(forced) != {"left_nolanding", "wall_continuation"} or any(f["cell"] >= e5["cells"] for f in forced.values()):
        problems.append(f"the forced dispatches are not the two inherited cells: {forced}")
    else:
        rows_s = art.rows_of(root6 / "sessions" / "sd2" / "wall_top_sightings.jsonl")
        row = next((x for x in rows_s if x["iteration"] == forced["wall_continuation"]["iteration"]), None)
        if not (row and row["start_cell_on_wall_top"] and row["first_tick_of_the_burst"]) or led.l0_cid is not None:
            problems.append(f"the wall-top continuation: {row} l0 {led.l0_cid}")
        cand_b = t4.candidate_for_iteration(sess, forced["left_nolanding"]["iteration"], "left")
        if cand_b is None or cand_b["cid"] in order:
            problems.append("the left continuation was replayed or not registered")
    again = rule6.apply(invalid=[], incomplete=[], verified_clears=arm["verified_clears"], t_rec=rr["completion_input_tick"], t_rec_time_passed=rr["completion_time_passed"], margin=rule6.MARGIN, exploration_started=True,
                        exploration_ticks=led.ticks, inherited_descriptive=inh["records"], sd1_line=op["facts5"]["sd1_line"], max_targets=arm["max_targets"], **{k: rule["extra"]["rule_inputs"][k] for k in
                        ("returns", "dispatches", "below_floor", "fatal_returns", "launch_capable_created", "bound_violations", "top_level_median_L")})
    for k in ("outcome", "flags", "any_stop"):
        if again[k] != rule[k]:
            problems.append(f"the recorded {k} {rule[k]} differs from the rule applied to the verified clears {again[k]}")
    if again["line"]["status"] != rule["line"]["status"]:
        problems.append("the recorded line status differs from the rule's")
    digest = e2e_digest(root6)
    best = rule.get("best_verified") or {}
    summary = {"small": small, "world": world, "engine": "lock-step pool, virtual clock", "wall_s": round(wall, 1), "outcome": rule["outcome"], "best_verified": {k: best.get(k) for k in ("cid", "completion_input_tick", "completion_time_passed")},
               "record_reference": rr["completion_input_tick"], "previous_record_reference": e5["sd1_record_reference"]["completion_input_tick"], "margin": rule6.MARGIN, "verified_clears": len(arm["verified_clears"]),
               "tiers_reached": (rule.get("tiers") or {}).get("reached"), "flags": rule["flags"], "stops": rule["any_stop"], "line": rule["line"]["status"], "ticks": led.ticks, "stop": sess.arm_records["T"]["stop"],
               "cells_open": e5["cells"], "cells_close": len(sess.archive.cells), "bursts": len(sess.archive.bursts), "candidates": len(led.candidates), "pools": ver.get("pools"), "pool": arm["pool"], "replays": arm["replays"],
               "replay_order": order, "inherited": {k: inh[k] for k in ("count", "replayed", "exact", "ticks")}, "forced": forced, "phase_wall_s": sess.clock.to_json()["phase_wall_s"], "peak_main_private_mb": sess.clock.peak_mb,
               "verify_run": vr["ok"], "replay_ticks": sess.ticks["replays"], "open_ticks": sess.ticks["p1"], "open_identity": io_, "identity_close": ver["identity"], "record_open": {k: sess.record_open_record.get(k) for k in ("exact", "words")},
               "audit": close.get("audit"), "artifacts": close.get("artifacts"), "prefix_chain": {k: close.get("prefix_chain", {}).get(k) for k in ("ok", "problems")}, "archive_stats": sess.archive.stats(),
               "rule_inputs": rule["extra"]["rule_inputs"], "overlay_open": op["overlay"]["v4"]["counts"], "overlay_close_v4": close.get("archive", {}).get("overlay_close_v4"),
               "E7": report["D8_overlays"]["E7"], "pace": report["pace"]["sd2"], "selection_at_the_open": {m_: report["selection_at_the_open"][m_]["top_level_mass"] for m_ in ("v3", "v4_previous_bound", "v4")},
               "dilution": rule["dilution"]["verdict"], "digest": digest, "problems": problems}
    (out / "e2e.json").write_text(json.dumps(art.stamp(summary), indent=1, default=str) + "\n", encoding="utf-8")
    (out / "e2e.log").write_text("\n".join(logs) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("open_identity", "identity_close", "archive_stats", "rule_inputs", "overlay_open", "overlay_close_v4", "pace", "forced")}, indent=1, default=str))
    shutil.rmtree(chain["t"], ignore_errors=True)
    shutil.rmtree(cp["t"], ignore_errors=True)
    if not problems:
        shutil.rmtree(root6, ignore_errors=True)               # the synthetic sd2 tree is large and says nothing about Mario; e2e.json and e2e.log are the record
    print("E2E PASS" if not problems else f"E2E FAIL: {problems}")
    print(json.dumps({"e2e": "PASS" if not problems else "FAIL", "digest": digest if not problems else None, "outcome": rule["outcome"], "problems": problems}), flush=True)
    return 0 if not problems else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("unit", "e2e", "list"))
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--only", default=None)
    ap.add_argument("--small", action="store_true")
    ap.add_argument("--world", default=CHAIN_WORLD, choices=sorted(stub.WORLDS))
    a = ap.parse_args(argv)
    if a.cmd == "list":
        for name, _fn in TESTS:
            print(name)
        return 0
    if a.cmd == "unit":
        return run_unit(a.only.split(",") if a.only else None, a.out or Path(tempfile.mkdtemp(prefix="m8_unit6_")))
    return e2e(a.out or Path(tempfile.mkdtemp(prefix="m8_e2e6_")), small=a.small, world=a.world)


if __name__ == "__main__":
    sys.exit(main())
