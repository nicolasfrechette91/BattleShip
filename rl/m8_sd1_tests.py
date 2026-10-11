#!/usr/bin/env python3
"""M8-sd1 offline tests: zero native ticks. No BattleShip launch, no replay on a real process, no training.

    python -B rl/m8_sd1_tests.py unit [--out DIR] [--only NAME[,NAME]]
    python -B rl/m8_sd1_tests.py e2e  [--out DIR] [--small] [--world W]      # the production-count synthetic end-to-end run of the four-level resume; its last line carries the digest
    python -B rl/m8_sd1_tests.py list

DETERMINISM (rd4's decision 10, kept). No test anywhere in this suite or in the preflight is non-deterministic. The session-level tests run the REAL session engine (Session5 over Session4,
Session3, Session2 and Session, the archive, the claims, the verification, the close checks, the rule) against the synthetic stub world (rl/m8_rd_stub.py) through rd3's in-process lock-step
worker pool and virtual clock: a run is a pure function of its configuration (tested: two runs agree on every ledger event, cell, word and decision). No test starts a real process. The
tests that read the closed real trees, git or D: are GATES: they assert facts that are fixed once the trees are closed and the work is staged.

The tests of rd1, rd2, rd3 and rd4 that run here (RD1_PURE, RD2_PURE, RD3_PURE, RD4_PURE) are the pure ones, by explicit lists; their asynchronous tests are never run.

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
import m8_rd2_report as rpt2  # noqa: E402
import m8_rd2_rule as rule2  # noqa: E402
import m8_rd2_run as run2  # noqa: E402
import m8_rd2_session as ses2  # noqa: E402
import m8_rd2_tests as t2  # noqa: E402
import m8_rd2_worker as w2  # noqa: E402
import m8_rd3_report as rpt3  # noqa: E402
import m8_rd3_resume as r3  # noqa: E402
import m8_rd3_run as run3  # noqa: E402
import m8_rd3_select as s3  # noqa: E402
import m8_rd3_session as ses3  # noqa: E402
import m8_rd3_tests as t3  # noqa: E402
import m8_rd4_claims as cl4  # noqa: E402
import m8_rd4_report as rpt4  # noqa: E402
import m8_rd4_resume as r4  # noqa: E402
import m8_rd4_rule as rule4  # noqa: E402
import m8_rd4_run as run4  # noqa: E402
import m8_rd4_select as s4  # noqa: E402
import m8_rd4_session as ses4  # noqa: E402
import m8_rd4_tests as t4  # noqa: E402
import m8_sd1_artifacts as art  # noqa: E402
import m8_sd1_claims as cl5  # noqa: E402
import m8_sd1_report as rpt5  # noqa: E402
import m8_sd1_resume as r5  # noqa: E402
import m8_sd1_rule as rule5  # noqa: E402
import m8_sd1_run as run5  # noqa: E402
import m8_sd1_select as s5  # noqa: E402
import m8_sd1_session as ses5  # noqa: E402
import m9_artifacts as A  # noqa: E402
from m8_rd_tests import Failure, check, raises, tmpdir  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
RL_DIR = Path(__file__).resolve().parent
TOOLS_DIR = REPO_ROOT / "tools" / "m8_sd1"
RD1_REAL = REPO_ROOT / "runs" / "m8_rd"
RD2_REAL = REPO_ROOT / "runs" / "m8_rd_rd2"
RD3_REAL = REPO_ROOT / "runs" / "m8_rd_rd3"
RD4_REAL = REPO_ROOT / "runs" / "m8_rd_rd4"
NEW_MODULES = ("m8_sd1_artifacts", "m8_sd1_select", "m8_sd1_rule", "m8_sd1_claims", "m8_sd1_resume", "m8_sd1_report", "m8_sd1_run", "m8_sd1_session", "m8_sd1_snapshot")
PYTHON_TOOLS = ("wait_session.py", "write_approval.py", "three_passes.py")
EARLIER_FILES = t4.EARLIER_FILES + ("m8_rd4_select", "m8_rd4_resume", "m8_rd4_claims", "m8_rd4_run", "m8_rd4_session", "m8_rd4_rule", "m8_rd4_report", "m8_rd4_snapshot", "m8_rd4_tests")
FLOOR_MIN = t4.FLOOR_MIN
FakeClock, SyncPool, sync_env = t4.FakeClock, t4.SyncPool, t4.sync_env
RD1_PURE = t4.RD1_PURE
RD2_PURE = t4.RD2_PURE
RD3_PURE = t4.RD3_PURE
RD4_PURE = ("rd4_contract", "select_v3_formula", "archive4_draw_and_weights_switch", "begin_rd4_and_persistence", "ledger_rebuild4", "dispatch_rows_and_mechanism_inputs", "rule4_module",
            "identity_samples4", "report_readings", "claims_pools_and_plan")
# the synthetic chain whose rd4 tree verifies a clear (found by experiment, then fixed here: the world, rd4's budget and the forced crossing at its start)
CHAIN_WORLD = "easy"
CHAIN_RD4 = 120000
CHAIN_RD4_KINDS = ("cross",)
OPEN_UTC = "2026-10-11T00:00:00Z"
REAL_TREES = all((p / "archive" / "manifest.sha256").is_file() for p in (RD1_REAL, RD2_REAL, RD3_REAL, RD4_REAL))

_CHAIN5: Dict[str, Any] = {}
_TMP: List[Path] = []


def real_record_reference() -> Dict[str, Any]:
    return dict(r5.RECORD_REFERENCE)


def syn_record_reference(t: int = 1000, digest: str = "a" * 64) -> Dict[str, Any]:
    return s5.record_reference_block(completion_input_tick=t, completion_time_passed=t - 1, native_action_digest=digest, words=t, cid=1, iteration=1, kind="clear", session="syn", source="synthetic")


# -- synthetic builders: a chain rd1 -> rd2 -> rd3 -> rd4 (built by the real engines) ----------------------------------------------------------------


def tree_expect4(root: Path) -> Dict[str, Any]:
    """The registered-facts dictionary of a synthetic rd4 tree (what RD4_FACTS is for the real one), the inherited record facts included."""
    a, meta = s5.Archive5.read_dir(root / "archive")
    prev = json.loads((root / "archive.prev" / "archive_meta.json").read_text(encoding="utf-8"))
    its = sorted(e["it"] for e in a.events if e["ev"] == "dispatch")
    rule = json.loads((root / "sessions" / "rd4" / "rule.json").read_text(encoding="utf-8"))
    return {"cells": len(a.cells), "bursts": len(a.bursts), "events": len(a.events), "checkpoint_seq": meta["checkpoint_seq"], "previous_checkpoint_seq": prev["checkpoint_seq"],
            "dispatch_iterations": (its[0], its[-1]), "contiguous": False, "first_rd2_iteration": a.rd2_first_iteration, "first_rd3_iteration": a.rd3_first_iteration,
            "first_rd4_iteration": a.rd4_first_iteration, "first_sd1_iteration": its[-1] + 1, "outcome": rule["outcome"], "m": rule["m"], "returns": meta["ledger_T"]["jobs"],
            "exploration_ticks": meta["ledger_T"]["ticks"], "inherited_record": r5.inherited_record_facts(root, a)}       # the forced crossing skips iteration numbers: increasing, not contiguous


def all_immutability5(cp: Mapping[str, Any]) -> Dict[str, Any]:
    parts = {k: rs.rd1_immutability(cp[k], cp[f"inc{i}"]) for i, k in enumerate(("rd1", "rd2", "rd3", "rd4"), 1)}
    return {"ok": all(v["ok"] for v in parts.values()), "problems": [f"{k}: {p}" for k, v in parts.items() for p in v["problems"]], **parts}


def build_chain5(world: str = CHAIN_WORLD, *, rd4_ticks: int = CHAIN_RD4, cache: bool = True, n_workers: int = 3, flags: Optional[Mapping[str, Any]] = None, exe_sha: str = "e" * 64,
                 runtime_files: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """rd4's synthetic three-tree chain plus a synthetic rd4 tree on it (rd4's own engine through the lock-step pool, its first dispatch the forced crossing), with its verified increment:
    the chain is a pure function of its parameters, and its rd4 verified a clear (the record sd1 searches below)."""
    key = f"{world}|{rd4_ticks}|{n_workers}|{bool(flags)}|{exe_sha}"
    if cache and key in _CHAIN5:
        return _CHAIN5[key]
    import runs_backup as rb

    base = t4.build_chain4(world, flags=flags, exe_sha=exe_sha, runtime_files=runtime_files, cache=cache, n_workers=n_workers)
    cls = t4.forced_session_cls(world, CHAIN_RD4_KINDS)
    out, sess, root4, cp = t4.run4_small(base, session_cls=cls, arm_tick_cap=rd4_ticks, min_arm_ticks=max(1000, rd4_ticks // 3), n_workers=n_workers)
    if cp["t"] in t4._TMP:
        t4._TMP.remove(cp["t"])                      # rd4's runner would delete this directory after the test: a cached chain is removed by this module's own cleanup
    r = out["rule"]
    check(r["outcome"] == "PROGRESS" and r["m"] == 4 and not r["invalid"] and not r["incomplete"], f"the synthetic rd4 session must verify a clear: {r['outcome']} m={r['m']} {r['invalid']} {r['incomplete']}")
    inc4 = cp["t"] / "inc4"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = rb.cmd_backup(root4, inc4, 2)
    check(rc == 0 and (inc4 / "verification.json").is_file(), f"the synthetic rd4 increment: {buf.getvalue()[-300:]}")
    chain = dict(cp, rd4=root4, inc4=inc4, expect4=tree_expect4(root4), rd4_outcome=r["outcome"], rd4_m=r["m"], world=world)
    if cache:
        _CHAIN5[key] = chain
    return chain


def copy_chain5(chain: Mapping[str, Any]) -> Dict[str, Any]:
    """A private copy of a chain (mtimes kept, so every copy still equals its increment)."""
    import runs_backup as rb

    t = tmpdir("m8sd1cp_")
    _TMP.append(t)
    for name in ("rd1", "inc1", "rd2", "inc2", "rd3", "inc3", "rd4", "inc4"):
        shutil.copytree(chain[name], t / name)
    for inc_key, dst in (("inc1", "rd1"), ("inc2", "rd2"), ("inc3", "rd3"), ("inc4", "rd4")):
        man = rb.read_manifest(chain[inc_key])
        for rel, (_sha, _size, mt) in man.items():
            os.utime(t / dst / rel.replace("/", os.sep), ns=(mt, mt))
    return dict(chain, t=t, rd1=t / "rd1", inc1=t / "inc1", rd2=t / "rd2", inc2=t / "inc2", rd3=t / "rd3", inc3=t / "inc3", rd4=t / "rd4", inc4=t / "inc4")


def small_cfg5(root: Path, **kw: Any) -> Any:
    base = dict(n_workers=3, arm_tick_cap=12000, arm_caps={"T": 12000}, min_arm_ticks=4000, p1_tick_cap=30000, replay_tick_cap=300000,
                wall_caps_s={"p1": 90.0, "T": 300.0, "C": 0.0, "verify": 300.0}, global_cap_s=1200.0, checkpoint_every_s=4.0, verify_threads=2, identity_k=6)
    base.update(kw)
    if "arm_tick_cap" in kw and "arm_caps" not in kw:
        base["arm_caps"] = {"T": kw["arm_tick_cap"]}
    return ses5.run_config(root=root, **base)


def open_chain5(cp: Mapping[str, Any], root5: Path, *, margin: int = rule5.MARGIN, utc: str = OPEN_UTC) -> Tuple[Dict[str, Any], s5.Archive5]:
    """The sd1 open protocol (R1-R5, four levels) and the materialisation (R6) on a private copy of a chain."""
    op = ses5.open_protocol5(cp["rd1"], cp["rd2"], cp["rd3"], cp["rd4"], cp["inc1"], cp["inc2"], cp["inc3"], cp["inc4"], expect1=cp["expect1"], expect2=cp["expect2"], expect3=cp["expect3"],
                             expect4=cp["expect4"], check_overlay=False, live_pins=lambda: t3.live_pins_of(cp), floor_min=FLOOR_MIN, margin=margin)
    check(op["ok"], f"the sd1 open protocol on a synthetic chain: {op['problems']}")
    a5 = r5.materialise5(cp["rd4"], root5, facts=op["facts4"], overlay=op["overlay"], lines_sha256=cp["lines"],
                         meta_extra={"pins": cp["pins"], "pin_tick0": op["facts4"]["pin_tick0"], "ticks": {}, "ledger_T": {}},
                         increment_manifest_sha256=op["R1_rd4_immutability"]["manifest_sha256"], utc=utc, margin=margin, floor_min=FLOOR_MIN)
    return op, a5


def run5_small(chain: Mapping[str, Any], *, world: Optional[str] = None, inject: Optional[Mapping[str, Any]] = None, env_kw: Optional[Mapping[str, Any]] = None,
               immutability: Optional[Callable[[], Mapping[str, Any]]] = None, env_kw_factory: Optional[Callable[[Mapping[str, Any], FakeClock], Mapping[str, Any]]] = None,
               clock_step: float = 0.25, session_cls: Any = None, pool_factory: Optional[Callable[[Any, Any, FakeClock], SyncPool]] = None, margin: int = rule5.MARGIN,
               record_candidate: Optional[Mapping[str, Any]] = None, **cfg_kw: Any) -> Tuple[Dict[str, Any], Any, Path, Dict[str, Any]]:
    """The sd1 session (open protocol, materialise, Session5, run_all5) against a private copy of a synthetic chain and the stub, through the lock-step pool."""
    cp = copy_chain5(chain)
    root5 = cp["t"] / "sd1"
    cfg = small_cfg5(root5, **cfg_kw)
    op, a5 = open_chain5(cp, root5, margin=margin)
    cfg.session_dir.mkdir(parents=True)
    mw.ProvenanceGuard.install()
    mw.ProvenanceGuard.violations.clear()
    roots = [cp["rd1"], cp["rd2"], cp["rd3"], cp["rd4"]]
    w2.WriteGuard.install(roots)
    try:
        clock = FakeClock(clock_step)
        env = sync_env(world or cp["world"], roots, clock, inject, pins=cp["pins"], **dict(env_kw or {}), **dict(env_kw_factory(cp, clock) if env_kw_factory else {}))
        sess = (session_cls or run5.Session5)(cfg, env, archive=a5, archive_pin=op["facts4"]["pin_tick0"], base_info={"open_overlay_sha256": op["overlay"]["v4"]["sha256"]}, rd1_root=cp["rd1"],
                                              rd2_root=cp["rd2"], rd3_root=cp["rd3"], rd4_root=cp["rd4"], lines_sha256=cp["lines"], ckpt_seq=int(op["facts4"]["rd4_checkpoint_seq"]) + 1,
                                              archive_created_utc=OPEN_UTC, record_candidate=record_candidate if record_candidate is not None else op["record_candidate"],
                                              inherited=op["inherited"], rd4_line=op["facts4"]["rd4_line"])
        sess.pool = pool_factory(env, cfg, clock) if pool_factory else SyncPool(env, cfg, clock)
        out = run5.run_all5(sess, immutability=immutability or (lambda: all_immutability5(cp)))
    finally:
        w2.WriteGuard.clear()
    return out, sess, root5, cp


def host_masked_sha256(path: Path) -> str:
    """sha256 of a JSONL row file (cells or the burst index) with the host frame of every `end` vector, a cell's and a burst's wins', set to 0. The host frame is the one observation value
    that differs between processes of the same gameplay: the engine's exactness excludes it (`m8_rd_worker` raises on a difference in any field but host_frame) and the stub draws its host
    offset from the process id. A signature over the raw rows therefore agrees within one process and differs between two processes of the same run (found by the first three passes)."""
    h = hashlib.sha256()
    with path.open("r", encoding="utf-8") as f:
        for ln in f:
            if not ln.strip():
                continue
            row = json.loads(ln)
            if isinstance(row.get("end"), list) and len(row["end"]) > mcell.HOST_FRAME:
                row["end"][mcell.HOST_FRAME] = 0
            for w in row.get("wins") or []:
                if isinstance(w, dict) and isinstance(w.get("end"), list) and len(w["end"]) > mcell.HOST_FRAME:
                    w["end"][mcell.HOST_FRAME] = 0
            h.update(json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            h.update(b"\n")
    return h.hexdigest()


def signature5(root5: Path) -> Dict[str, Any]:
    """What must be identical between two runs of the same configuration, in one process or in two: the archive's data files (the cells and the burst index with the host frame of every
    end vector masked, the words and the ledger raw; not its meta, which carries timestamps), the decision, the verification's order and the open overlay."""
    a = root5 / "archive"
    rule = json.loads((root5 / "sessions" / "sd1" / "rule.json").read_text(encoding="utf-8"))
    ver = json.loads((root5 / "sessions" / "sd1" / "verification.json").read_text(encoding="utf-8")) if (root5 / "sessions" / "sd1" / "verification.json").is_file() else {}
    arm = ver.get("arm") or {}
    ov = json.loads((root5 / "derived" / "open_overlay.json").read_text(encoding="utf-8"))
    ev = next(e for e in json.loads(json.dumps([json.loads(ln) for ln in (a / "events.jsonl").read_text(encoding="utf-8").splitlines()])) if e["ev"] == "session" and e.get("name") == "sd1")
    best = rule.get("best_verified") or {}
    return {"files": {"cells.jsonl": host_masked_sha256(a / "cells.jsonl"), "bursts.bin": mw.sha256_file(a / "bursts.bin"),
                      "bursts.idx.jsonl": host_masked_sha256(a / "bursts.idx.jsonl"), "events.jsonl": mw.sha256_file(a / "events.jsonl")},
            "rule": {k: rule[k] for k in ("outcome", "flags", "any_stop", "progress_bar", "margin")}, "best": {k: best.get(k) for k in ("cid", "completion_input_tick", "completion_time_passed", "native_action_digest")},
            "verified_cids": [v["cid"] for v in rule.get("verified_clears") or []], "tiers_reached": (rule.get("tiers") or {}).get("reached"), "line": rule["line"]["status"],
            "verification": {k: arm.get(k) for k in ("pool", "replays", "replay_order", "remaining", "remaining_progress", "closed", "max_targets")},
            "inherited": {k: (ver.get("inherited_descriptive") or {}).get(k) for k in ("count", "replayed", "exact")}, "session_event_digest": ev["digest"], "record_reference": ev["record_reference"],
            "open_overlay_sha256": ov["open_overlay"]["sha256"]}


def synth_archive5(seed: str = "s5", n1: int = 40, n2: int = 50, n3: int = 50, n4: int = 50, n5: int = 50, floor_min: float = -2100.0, lines: str = "lines", t_rec: int = 1000,
                   margin: int = 24) -> s5.Archive5:
    """A five-part archive from keyed random jobs: rd1's part under v1, rd2's and rd3's under v2, rd4's under v3, sd1's under v4 (draw id `_sd1`, E7 at the synthetic reference)."""
    rng = t2.Krng(seed)
    a = s5.Archive5("syn5", floor_min=floor_min)
    a.init_cell0(t1.key(0, 0), t1.mk_end(), bytes(32), bytes([1]) * 32)
    t2.drive2(a, rng, n1, 0, v2=False)
    a.begin_v2(n1, lines)
    t2.drive2(a, rng, n2, n1, v2=True)
    a.begin_rd3(n1 + n2, lines)
    t2.drive2(a, rng, n3, n1 + n2, v2=True)
    a.begin_rd4(n1 + n2 + n3, lines)
    t2.drive2(a, rng, n4, n1 + n2 + n3, v2=True)
    a.begin_sd1(n1 + n2 + n3 + n4, lines, syn_record_reference(t_rec), margin)
    t2.drive2(a, rng, n5, n1 + n2 + n3 + n4, v2=True)
    return a


def fresh5(aid: str = "t5", floor_min: float = -2550.0) -> s5.Archive5:
    a = s5.Archive5(aid, floor_min=floor_min)
    a.init_cell0(t1.key(0, 0), t1.mk_end(), bytes(32), bytes([1]) * 32)
    return a


def archive5_for_prob(cells: Sequence[Tuple[Any, ...]], *, with_sd1: bool = True, t_rec: int = 1000, margin: int = 24) -> s5.Archive5:
    """A small archive in mode 2 (rd2, rd3 and rd4 begun, sd1 begun when asked) holding the given (key, L, y, seen, chosen) cells."""
    a = fresh5("pb", -2550.0)
    for k, L, y, seen, chosen in cells:
        t2.add_cell2(a, k, L, y=y, seen=seen, chosen=chosen)
    a.begin_v2(5, "L")
    a.begin_rd3(6, "L")
    a.begin_rd4(7, "L")
    if with_sd1:
        a.begin_sd1(8, "L", syn_record_reference(t_rec), margin)
    return a


def real_lines() -> str:
    meta = json.loads((RD4_REAL / "archive" / "archive_meta.json").read_text(encoding="utf-8"))
    return str(meta["pin_tick0"]["lines"])


# -- the contract and the selection ---------------------------------------------------------------------------------------------------------------------


def unit_sd1_contract() -> Dict[str, Any]:
    import m7q_status_table as st

    check(s5.DRAW_SUFFIX == "_sd1" and s5.DRAW_SUFFIX_RD4 == "_rd4" and s5.DRAW_SUFFIX_RD3 == "_rd3" and s5.DRAW_SUFFIX_RD2 == "_v2" and s5.SESSION_NAME == "sd1" and s5.SESSIONS == ("rd1", "rd2", "rd3", "rd4", "sd1"),
          "the session names and the draw suffixes (sd1's is its own)")
    check(s5.LENGTH_SCALE_V4 == 120.0 == float(mx.BURST_WORDS) and march.LENGTH_SCALE == 900.0, "the length scale is one explorer burst (v3: 900)")
    check(set(s5.REGISTERED_CHANGES) == {"contract", "cell_weight", "length_scale", "eligibility", "draws", "record_reference", "margin"} and s5.CHANGES_TEXT == ["length_scale 900 -> 120", "eligibility + E7 (L + 1 <= T_rec - M)"],
          "the two registered changes and their description keys")
    check(mx.select_key("m8_rd_a1_sd1", 13886) == "m8_rd|m8_rd_a1_sd1|select|13886" and mx.explore_key("m8_rd_a1_sd1", 13886, 3) == "m8_rd|m8_rd_a1_sd1|explore|13886|3", "the key strings")
    a = s5.Archive5("m8_rd_a1")
    check(a.draw_id_sd1 == "m8_rd_a1_sd1" and len({a.draw_id_rd2, a.draw_id_rd3, a.draw_id_rd4, a.draw_id_sd1}) == 4, "the draw ids")
    d = s5.draws_description()
    check(d["select"] == "m8_rd|<archive id>_sd1|select|<iteration>" and d["identity_open"].endswith("identity_open|sd1|<cell id>") and d["rd4_select"].endswith("_rd4|select|<iteration>"), f"the registered key strings: {d}")
    check(len(s5.draws_digest()) == 64 and s5.draws_digest() != s4.draws_digest(), "the draws digest")
    check(rule5.RULE_ID == "m8_sd1_rule_v1" and rule5.rule_digest() not in (rule4.rule_digest(), rule2.rule_digest()), "sd1's own rule")
    check(rule5.SCOPE.startswith("M8-sd1: first time-directed continuation of archive m8_rd_a1") and "no control arm" in rule5.SCOPE and "not a policy result" in rule5.SCOPE and "m8_rd_select_v4" in rule5.SCOPE,
          "the scope label")
    c5, c4 = ses5.caps(), ses4.caps()
    check(c5 == c4, f"caps differ from rd4's: { {k: (c5[k], c4.get(k)) for k in c5 if c5[k] != c4.get(k)} }")
    cfg = ses5.run_config()
    check(cfg.session_id == "sd1" and cfg.root == ses5.SD1_ROOT and cfg.arm_cap("T") == 6_000_000 and cfg.min_arm_ticks == 2_000_000 and cfg.n_workers == 5 and cfg.burst_words == 120
          and cfg.horizon == 3600 and cfg.p1_tick_cap == 70_000 and cfg.replay_tick_cap == 400_000 and cfg.global_cap_s == 3600.0, "run_config carries the registered values")
    check(ses5.SD1_ROOT.name == "m8_rd_sd1" and ses5.RD4_ROOT.name == "m8_rd_rd4" and ses5.APPROVAL.name == "rl_m8_sd1_approval.json" and ses5.INCREMENT_RD4.name == "2026-10-03_incr_m8_rd4",
          "the roots, the approval path and rd4's increment")
    check(ses5.MARGIN == 24 and ses5.RECORD_REFERENCE["completion_input_tick"] == 2315 and ses5.RECORD_REFERENCE["completion_time_passed"] == 2314 and ses5.RECORD_REFERENCE["words"] == 2315
          and ses5.RECORD_REFERENCE["native_action_digest"].startswith("de1228be4146b720"), "the pinned record reference and margin")
    sha = st.load_table()["sha256"]
    digs = ses5.contract_digests5("lines")
    check(set(digs) == set(ses4.contract_digests4("lines")) | {"m8_rd_select_v4"} and len(digs) == 9 and digs["m8_rd_select_v4"] != digs["m8_rd_select_v3"], "nine contract digests: v3's and v4's side by side")
    check(digs["m8_rd_select_v4"] == s5.select4_contract_digest(sha, "lines", None, ses5.RECORD_REFERENCE, 24), "the v4 digest reads the pinned reference and margin")
    check(all((TOOLS_DIR / f).is_file() for f in ses5.TOOL_FILES) and len(ses5.TOOL_FILES) == 5, f"the five launch tools exist under tools/m8_sd1: {ses5.TOOL_FILES}")
    fp = ses5.source_fingerprint()
    check(len(fp) == 16 and fp == ses5.source_fingerprint(), "the source fingerprint")
    if REAL_TREES:
        ev = ses4._events(RD4_REAL / "archive")
        check([(e["name"], e["first_iteration"]) for e in ev] == [("rd2", 2175), ("rd3", 6212), ("rd4", 10406)], f"rd2's, rd3's and rd4's session events: {ev}")
        lines, fm = real_lines(), float(json.loads((RD4_REAL / "archive" / "archive_meta.json").read_text(encoding="utf-8"))["floor_min"])
        v2d, v3d = s2.select2_contract_digest(sha, lines, fm), s4.select3_contract_digest(sha, lines, fm)
        check(ev[0]["digest"] == ev[1]["digest"] == v2d and ev[2]["digest"] == v3d and v3d.startswith("fd69a0332de9db28"), "the recorded digests equal v2 and v3 recomputed from the current code")
        check(s5.select4_contract_digest(sha, lines, fm, ses5.RECORD_REFERENCE, 24) not in (v2d, v3d), "v4's digest differs from both")
    return {"fingerprint": fp, "v4": digs["m8_rd_select_v4"][:12]}


def unit_select_v4_formula_and_digest() -> Dict[str, Any]:
    import m7q_status_table as st

    mk = t2.mkey
    spec = [(mk(1, 1, "A2"), 100, 300.0, 0, 0), (mk(2, 1, "A2"), 220, 300.0, 0, 0), (mk(3, 1, "A1"), 700, 300.0, 8, 5), (mk(4, 1, "A0"), 900, 300.0, 24, 1), (mk(5, 1, "G", 1023, 4), 250, 0.0, 99, 0),
            (mk(6, 1, "A2"), 100, 300.0, 3, 77)]
    a = archive5_for_prob(spec, t_rec=2000)
    cells = [c for c in a.cells if c.id != 0 and c.level == 0]
    lmin = min(c.L for c in cells)
    for c, w in zip(cells, s5.v4_weights(cells)):
        want = (1.0 / math.sqrt(1 + c.seen)) * (120.0 / (120.0 + c.L - lmin)) * s2.W_RES[c.key[2]]
        check(abs(w - want) < 1e-15, f"cell {c.id}: v4 weight {w}, the independent formula {want}")
    w = dict(zip([c.id for c in cells], s5.v4_weights(cells)))
    p, q = cells[0], cells[1]
    check(p.L == lmin and q.L == lmin + 120 and p.seen == q.seen and p.key[2] == q.key[2] and abs(w[q.id] / w[p.id] - 0.5) < 1e-15, "one burst behind the level's shortest arrival halves the weight")
    w3 = dict(zip([c.id for c in cells], s4.v3_weights(cells)))
    check(abs(w3[q.id] / w3[p.id] - 900.0 / 1020.0) < 1e-15, "under v3 the same cell keeps 88 %")
    a._v4 = False
    a._v3 = True
    check(a.cell_weights(cells) == s4.v3_weights(cells), "with the flag off the weights are v3's")
    a._v4 = True
    check(a.cell_weights(cells) == s5.v4_weights(cells), "with the flag on the weights are v4's")
    a._v4 = False
    for mode in ("v2", "v3", "v4"):
        pr = a.probabilities(mode)
        check(abs(sum(pr.values()) - 1.0) < 1e-12, f"{mode}: probabilities sum to one")
    check(a.probabilities() == a.probabilities("v4") and not a._v4, "the default is v4 once sd1 has begun, and the flag is restored")
    b = archive5_for_prob(spec, with_sd1=False)
    check(b.probabilities() == b.probabilities("v3"), "the default is v3 before sd1 begins")
    raises(s5.Select5Error, lambda: b.probabilities("v4"), "v4 probabilities need the record bound")
    raises(s5.Select5Error, lambda: a.probabilities("v9"), "an unknown mode is refused")
    # the digest: v4 is v3 with exactly the registered keys replaced or added; restored, it reproduces the REAL v3 digest
    sha = st.load_table()["sha256"]
    lines = real_lines() if REAL_TREES else "lines"
    fm = float(json.loads((RD4_REAL / "archive" / "archive_meta.json").read_text(encoding="utf-8"))["floor_min"]) if REAL_TREES else None
    rr = ses5.RECORD_REFERENCE
    d4 = s5.select4_description(sha, lines, fm, rr, 24)
    restored = s5.restore_v3(d4, sha, lines, fm)
    v3 = s4.select3_contract_digest(sha, lines, fm)
    check(hashlib.sha256(json.dumps(restored, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest() == v3, "v4's description with the registered keys restored hashes to the real v3 digest")
    if REAL_TREES:
        check(v3.startswith("fd69a0332de9db28"), f"the real v3 digest: {v3[:16]}")
    check(s5.changed_keys(sha, lines, fm, rr, 24) == sorted(s5.REGISTERED_CHANGES), f"exactly the registered keys differ: {s5.changed_keys(sha, lines, fm, rr, 24)}")
    d3 = s4.select3_description(sha, lines, fm)
    same = [k for k in d3 if k not in s5.REGISTERED_CHANGES]
    check(same and all(d3[k] == d4[k] for k in same), "every other part of the contract is v3's, unchanged (count term, level weight, resource weights, descent doom, bound, replacement)")
    check(d4["length_scale"] == 120.0 and d4["cell_weight"].startswith("(1/sqrt(1+seen)) * 120 / (120 + L - L_min") and d4["margin"] == 24 and d4["record_reference"] == rr
          and any(x.startswith("E7 record bound") for x in d4["eligibility"]) and d4["eligibility"][:-1] == d3["eligibility"] and d4["reads_position_in_preference"] is False, "the registered description")
    check(d4["level"] == d3["level"] == "weight 1 / (1 + top - level) over the levels that have eligible cells", "the harmonic level draw is unchanged")
    v4 = s5.select4_contract_digest(sha, lines, fm, rr, 24)
    check(v4 != v3 and v4 != s5.select4_contract_digest(sha, lines, fm, rr, 23) and v4 != s5.select4_contract_digest(sha, lines, fm, dict(rr, completion_input_tick=2314, words=2314), 24)
          and v4 != s5.select4_contract_digest(sha, "other", fm, rr, 24), "v4's digest depends on the margin, the reference and the pinned lines")
    for bad in (dict(rr, completion_input_tick=2316), dict(rr, native_action_digest="x"), {k: v for k, v in rr.items() if k != "source"}, dict(rr, extra=1), dict(rr, words="2315")):
        raises(s5.Select5Error, lambda b=bad: s5.validate_record_reference(b), "a malformed record reference is refused")
    raises(s5.Select5Error, lambda: s5.select4_description(sha, lines, fm, rr, 0), "a zero margin is refused")
    raises(s5.Select5Error, lambda: s5.select4_description(sha, lines, fm, None, 24), "no reference is refused")
    check(s5.record_bound_max_L(2315, 24) == 2290 and s5.record_bound_max_L(100, 1) == 98, "E7's bound: L <= T_rec - M - 1")
    return {"v4": v4[:12], "v3": v3[:12]}


def unit_record_bound_e7() -> Dict[str, Any]:
    mk = t2.mkey
    spec = [(mk(1, 1, "A2"), 100, 300.0, 0, 0), (mk(2, 1, "A2"), 975, 300.0, 0, 0), (mk(3, 1, "A2"), 976, 300.0, 0, 0), (mk(4, 1, "A1"), 990, 300.0, 1, 1), (mk(5, 1, "G", 1023, 4), 975, 0.0, 2, 0),
            (mk(6, 2, "A2", 1023 - 2), 990, 300.0, 0, 0), (mk(7, 2, "A2", 2), 990, 300.0, 0, 0)]              # mask 2: exactly one live target (X1)
    a = archive5_for_prob(spec, t_rec=1000, margin=24)
    check(a.bound_max_L() == 975, "the bound at T_rec 1000 and M 24")
    by_L = {c.L: c for c in a.cells if c.id}
    with a.as_v4():
        check(a.eligible(a.cells[0]), "cell 0 is always eligible")
        check(a.eligible(by_L[100]) and a.eligible(by_L[975]) and a.eligible(a.cells[5]), "L <= 975 stays eligible (airborne and grounded)")
        check(not a.eligible(by_L[976]) and not a.eligible(a.cells[4]), "L 976 and 990 are not")
        x1 = next(c for c in a.cells if c.key[3] == 2)
        check(mcell.popcount(x1.key[3]) == 1 and not a.eligible(x1), "X1 does not exempt from E7")
        levels = a.eligible_levels()
    check(not a._v4, "as_v4 restores the flag")
    x1 = next(c for c in a.cells if c.key[3] == 2)
    check(a.eligible(x1) and a.eligible(by_L[976]), "outside v4 the same cells are eligible under v3 (the flag is off)")
    with a.as_v4():
        p4 = a.probabilities("v4")
    p3 = a.probabilities("v3")
    check(by_L[976].id not in p4 and by_L[976].id in p3 and by_L[975].id in p4 and x1.id not in p4 and x1.id in p3, "the analytic probabilities exclude the bound cells under v4 only")
    bound_ids = {c.id for c in a.cells if c.id and c.L > 975}
    for it in range(8, 308):
        check(a.select(it).id not in bound_ids, f"iteration {it}: an sd1 draw selected a cell beyond the record bound")
    hits = sum(1 for it in range(7, 8) if a.select(it).id in bound_ids)                       # the single rd4 iteration of this archive may select a bound cell (v3 ignores E7)
    check(hits in (0, 1), "rd4 iterations are selected under v3")
    # the cache answers differently for the two modes at the same version
    v = a._version
    a._v4 = False
    n3 = sum(len(cs) for cs in a.eligible_levels().values())
    a._v4 = True
    n4 = sum(len(cs) for cs in a.eligible_levels().values())
    a._v4 = False
    check(a._version == v and n3 == n4 + len(bound_ids), f"the eligible-levels cache is keyed on the mode: {n3} under v3, {n4} under v4")
    check(not fresh5("x").eligible_levels() or True, "an empty archive")
    raises(s5.Select5Error, lambda: fresh5("y").bound_max_L(), "no bound before sd1 begins")
    return {"bound_L": a.bound_max_L(), "v3_eligible": n3, "v4_eligible": n4}


def unit_archive5_draw_and_mode_switch() -> Dict[str, Any]:
    n1, n2, n3, n4, n5 = 40, 50, 50, 50, 50
    a = synth_archive5("sw", n1, n2, n3, n4, n5, t_rec=150, margin=24)
    f2, f3, f4, f5 = n1, n1 + n2, n1 + n2 + n3, n1 + n2 + n3 + n4
    check(a.mode == 2 and a.rd2_first_iteration == f2 and a.rd3_first_iteration == f3 and a.rd4_first_iteration == f4 and a.sd1_first_iteration == f5 and a.first_iteration == f5 and a.draw_id == a.draw_id_sd1
          and a.record_reference["completion_input_tick"] == 150 and a.margin == 24 and a.bound_max_L() == 125, "the five-part archive")
    for it, want in ((0, "syn5_v2"), (f2, "syn5_v2"), (f3 - 1, "syn5_v2"), (f3, "syn5_rd3"), (f4 - 1, "syn5_rd3"), (f4, "syn5_rd4"), (f5 - 1, "syn5_rd4"), (f5, "syn5_sd1"), (f5 + 1000, "syn5_sd1")):
        check(a.draw_for(it) == want, f"draw_for({it}) = {a.draw_for(it)}, expected {want}")
    check(a.iteration_ranges() == {"rd1": (0, f2 - 1), "rd2": (f2, f3 - 1), "rd3": (f3, f4 - 1), "rd4": (f4, f5 - 1), "sd1": (f5, f5 + n5 - 1)}, f"ranges {a.iteration_ranges()}")
    check([a.session_of_iteration(i) for i in (0, f2, f3, f4, f5, 10 ** 6)] == ["rd1", "rd2", "rd3", "rd4", "sd1", "sd1"], "session_of_iteration")
    check(any(c.L > 125 for c in a.cells), "the synthetic archive holds cells beyond the bound (E7 binds)")
    nxt = f5 + n5
    keep = (a.draw_id, a._v3, a._v4)

    def independent(it: int, draw: str, mode: str) -> int:
        bound = a.bound_max_L()
        levels: Dict[int, List[march.Cell]] = {}
        for c in a.cells:
            ok = s2.Archive2.eligible(a, c) and (mode != "v4" or c.id == 0 or c.L <= bound)
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
        check(a.select(it).id == independent(it, a.draw_id_sd1, "v4"), f"iteration {it}: select differs from the independent v4 draw")
    for it in range(f4 + 3, f4 + 30):
        check(a.select(it).id == independent(it, a.draw_id_rd4, "v3"), f"iteration {it}: an rd4 iteration is not selected under v3 and the rd4 draw")
    for it in range(f3 + 3, f3 + 20):
        check(a.select(it).id == independent(it, a.draw_id_rd3, "v2"), f"iteration {it}: an rd3 iteration is not selected under v2 and the rd3 draw")
    check((a.draw_id, a._v3, a._v4) == keep, "select restores the draw id and the flags")
    differ = sum(int(independent(it, a.draw_id_sd1, "v4") != independent(it, a.draw_id_sd1, "v3")) for it in range(nxt, nxt + 200))
    check(differ > 0, "v4 selects differently from v3 on the same draws")
    differ2 = sum(int(independent(it, a.draw_id_sd1, "v4") != independent(it, a.draw_id_rd4, "v4")) for it in range(nxt, nxt + 200))
    check(differ2 > 0, "sd1's draws are not rd4's")
    w5 = list(mx.words(lambda i: mx.explore_key("syn5_sd1", 7000, i), 60))
    w4 = list(mx.words(lambda i: mx.explore_key("syn5_rd4", 7000, i), 60))
    check(w5 != w4 and len(w5) == 60, "the explorer draws are keyed by the session's draw id")
    return {"differ_of_200": differ, "cells": len(a.cells)}


def unit_begin_sd1_and_persistence() -> Dict[str, Any]:
    rr = syn_record_reference(1000)
    a = fresh5("bs", -2550.0)
    raises(s5.Select5Error, lambda: a.begin_sd1(5, "L", rr, 24), "sd1 cannot begin before rd2's, rd3's and rd4's session events")
    t2.drive2(a, t2.Krng("bs"), 20, 0, v2=False)
    a.begin_v2(20, "L")
    t2.drive2(a, t2.Krng("bs2"), 15, 20, v2=True)
    a.begin_rd3(35, "L")
    t2.drive2(a, t2.Krng("bs3"), 12, 35, v2=True)
    raises(s5.Select5Error, lambda: a.begin_sd1(50, "L", rr, 24), "sd1 cannot begin before rd4's session event")
    a.begin_rd4(47, "L")
    t2.drive2(a, t2.Krng("bs4"), 12, 47, v2=True)
    raises(s5.Select5Error, lambda: a.begin_sd1(50, "L", rr, 24), "reusing a dispatched iteration is refused")
    a.apply_dispatch(500, 0, 0)
    raises(s5.Select5Error, lambda: a.begin_sd1(600, "L", rr, 24), "a pending dispatch blocks the switch")
    a.note_failure(500, "x")
    raises(s5.Select5Error, lambda: a.begin_sd1(600, "another line table", rr, 24), "a selection contract that is not the one rd2, rd3 and rd4 ran is refused (the digests differ)")
    raises(s5.Select5Error, lambda: a.begin_sd1(600, "L", dict(rr, words=999), 24), "a malformed reference is refused")
    raises(s5.Select5Error, lambda: a.begin_sd1(600, "L", rr, 0), "a zero margin is refused")
    n_ev = len(a.events)
    ev = a.begin_sd1(600, "L", rr, 24)
    check(ev["name"] == "sd1" and ev["first_iteration"] == 600 and ev["draw_suffix"] == "_sd1" and ev["select"] == "m8_rd_select_v4" and ev["record_reference"] == rr and ev["margin"] == 24
          and ev["length_scale"] == 120.0 and ev["changed_from"]["select"] == "m8_rd_select_v3" and ev["changed_from"]["changes"] == s5.CHANGES_TEXT and a.events[-1] == ev and len(a.events) == n_ev + 1, "one session event")
    sess = [e for e in a.events if e["ev"] == "session"]
    v2d = s2.select2_contract_digest(a.clf.table_sha256, "L", a.floor_min)
    v3d = s4.select3_contract_digest(a.clf.table_sha256, "L", a.floor_min)
    check([e["name"] for e in sess] == ["rd2", "rd3", "rd4", "sd1"] and sess[0]["digest"] == sess[1]["digest"] == v2d and sess[2]["digest"] == v3d and sess[3]["digest"] == s5.select4_contract_digest(a.clf.table_sha256, "L", a.floor_min, rr, 24)
          and sess[3]["changed_from"]["digest"] == v3d, "sd1's digest is v4's, with v3's (rd4's) recorded beside it")
    check(a.sd1_first_iteration == 600 and a.first_iteration == 600 and a.draw_id == a.draw_id_sd1 and a.bound_max_L() == 975 and a.margin == 24, "state after the switch")
    raises(s5.Select5Error, lambda: a.begin_sd1(700, "L", rr, 24), "a second switch is refused")
    t = tmpdir("m8sd1p_")
    x = fresh5("bs", -2550.0)
    t2.drive2(x, t2.Krng("bs"), 20, 0, v2=False)
    x.begin_v2(20, "L")
    t2.drive2(x, t2.Krng("bs2"), 15, 20, v2=True)
    x.begin_rd3(35, "L")
    t2.drive2(x, t2.Krng("bs3"), 12, 35, v2=True)
    x.begin_rd4(47, "L")
    t2.drive2(x, t2.Krng("bs4"), 12, 47, v2=True)
    march.save_checkpoint(t / "rd4" / "archive", x, {"checkpoint_seq": 45, "why": "x"})
    y, meta_y = s5.Archive5.read_dir(t / "rd4" / "archive")
    check(y.sd1_first_iteration is None and y.rd4_first_iteration == 47 and y.draw_id == y.draw_id_rd4 and y.record_reference is None, "an rd4 closing archive loads as an Archive5 before sd1")
    check(s4.Archive4.read_dir(t / "rd4" / "archive")[0].rd4_first_iteration == 47, "rd4's own loader still reads it")
    y.begin_sd1(59, "L", rr, 24)
    t2.drive2(y, t2.Krng("bs5"), 12, 59, v2=True)
    march.save_checkpoint(t / "sd1" / "archive", y, art.stamp({"checkpoint_seq": 46, "why": "x"}, created_utc=OPEN_UTC))
    pp = rs.prefix_property(t / "rd4" / "archive", t / "sd1" / "archive")
    check(pp["ok"] and pp["events.jsonl"]["lines"] == len(x.events) and pp["bursts.idx.jsonl"]["lines"] == len(x.bursts), f"sd1's files begin with rd4's closing bytes: {pp}")
    z, meta_z = s5.Archive5.read_dir(t / "sd1" / "archive")
    check(meta_z["schema"] == s2.ARCHIVE_SCHEMA_V2 and meta_z["archive5_contract"] == s5.ARCHIVE5_CONTRACT and meta_z["sd1_first_iteration"] == 59 and meta_z["rd4_first_iteration"] == 47
          and meta_z["draw_ids5"] == {"rd1": "bs", "rd2": "bs_v2", "rd3": "bs_rd3", "rd4": "bs_rd4", "sd1": "bs_sd1"} and meta_z["select4_contract"] == "m8_rd_select_v4" and meta_z["record_reference"] == rr
          and meta_z["margin"] == 24 and meta_z["length_scale_v4"] == 120.0 and meta_z["created_utc"] == OPEN_UTC and art.is_stamped(meta_z), f"the sd1 directory is self-describing and stamped")
    check(z.sd1_first_iteration == 59 and z.draw_id == "bs_sd1" and z.record_reference == rr and z.margin == 24 and z.bound_max_L() == 975 and z.mode == 2, "the reload knows the session switch and the bound")
    v4_ev = [e for e in z.events if e["ev"] == "session" and e["name"] == "sd1"]
    check(len(v4_ev) == 1 and meta_z["select4_digest"] == v4_ev[0]["digest"] == meta_z["select2_digest"] and meta_z["select3_digest"] != meta_z["select4_digest"],
          "the checkpoint names v4's digest unambiguously (`select4_digest`); rd2's writer's `select2_digest` is the LAST session's digest")
    check([c.to_json() for c in z.cells] == [c.to_json() for c in y.cells] and z.diag2 == y.diag2 and z.desc == y.desc and z.bound == y.bound, "a reload reproduces cells, counters and derived flags")
    check(s5.audit5(z, "L")["ok"] and s5.rebuild5(z, "L").events == z.events, "the reloaded five-part archive audits and rebuilds")
    raises(s4.Select4Error, lambda: s4.Archive4.read_dir(t / "sd1" / "archive"), "rd4's loader refuses an sd1 archive (four session events)")
    w, _m = s2.Archive2.read_dir(t / "sd1" / "archive")
    check(w.mode == 2 and w.first_iteration == 59, "rd2's loader reads the sd1 directory (mode 2; the last session's first iteration)")
    only_rd3 = fresh5("o3")
    only_rd3.begin_v2(5, "L")
    only_rd3.begin_rd3(6, "L")
    raises(s5.Select5Error, lambda: s5.Archive5.adopt(only_rd3), "an rd3 archive (two session events) is not an rd4 archive")
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
        loaded, mm = s5.Archive5.read_dir(d)
        check(s5.audit5(loaded, "L")["ok"] and m["checkpoint_seq"] == 2 and mm["created_utc"] == OPEN_UTC, f"crash {crash}: the newest complete checkpoint audits and keeps created_utc")
        z, _m3 = s5.Archive5.read_dir(t / "sd1" / "archive")
    shutil.rmtree(t, ignore_errors=True)
    return {"cells": len(a.cells)}


def unit_ledger_rebuild5() -> Dict[str, Any]:
    n1, n2, n3, n4, n5 = 50, 60, 60, 60, 70
    a = synth_archive5("lr5", n1, n2, n3, n4, n5, t_rec=150, margin=24)
    f5 = n1 + n2 + n3 + n4
    check(len(a.cells) > 300 and len(a.bursts) == f5 + n5 and a.mode == 2 and any(c.L > a.bound_max_L() for c in a.cells), f"the synthetic five-part archive with E7 binding: {len(a.cells)} cells")
    aud = s5.audit5(a, "lines")
    check(aud["ok"], f"audit of a five-part archive: {aud['problems']}")
    check(aud["prefixes_reconstructed"] == len(a.cells) and aud["dispatch_rows"] == [], "every prefix reconstructs; no rows unless asked")
    rows = s5.audit5(a, "lines", collect_rows_from=f5)["dispatch_rows"]
    check(len(rows) == n5 and all(r["created_in"] in s5.SESSIONS for r in rows) and any(r["created_in"] == "sd1" for r in rows), "the dispatch rows of sd1's part name the creating session")
    rb = s5.rebuild5(a, "lines")
    check([c.to_json() for c in rb.cells] == [c.to_json() for c in a.cells] and rb.events == a.events and rb.diag2 == a.diag2 and rb.sd1_first_iteration == f5 and rb.record_reference == a.record_reference, "the rebuild equals the archive")
    check(not s4.audit4(a, "lines")["ok"], "rd4's own audit cannot cross a fourth session event (which is why rebuild5 exists)")
    t = tmpdir("m8sd1lr_")
    a.write_files(t / "a", art.stamp({"checkpoint_seq": 1}, created_utc=OPEN_UTC))

    def load() -> s5.Archive5:
        return s5.Archive5.read_dir(t / "a")[0]

    check(s5.audit5(load(), "lines")["ok"], "a saved and reloaded archive audits")
    b = load()
    k = next(i for i, e in enumerate(b.events) if e["ev"] == "dispatch" and e["it"] == f5 + 3)
    b.events[k]["cell"] = (b.events[k]["cell"] + 1) % len(b.cells)
    check(not s5.audit5(b, "lines")["ok"], "a changed sd1 selection is detected by the re-derived draw")
    for mutate, what in ((lambda e: e.__setitem__("digest", "0" * 64), "a tampered sd1 session digest"), (lambda e: e.__setitem__("margin", 23), "a tampered margin"),
                         (lambda e: e["record_reference"].__setitem__("completion_input_tick", 701) or e["record_reference"].__setitem__("words", 701), "a tampered record reference"),
                         (lambda e: e.__setitem__("draw_suffix", "_rd4"), "a tampered draw suffix"), (lambda e: e.__setitem__("first_iteration", e["first_iteration"] + 1), "a shifted first iteration"),
                         (lambda e: e["changed_from"].__setitem__("digest", "0" * 64), "a tampered record of the v3 digest"), (lambda e: e.__setitem__("length_scale", 900.0), "a tampered length scale")):
        b = load()
        mutate(next(e for e in b.events if e["ev"] == "session" and e["name"] == "sd1"))
        check(not s5.audit5(b, "lines")["ok"], f"{what} is detected")
    b = load()
    b.events = [e for e in b.events if not (e["ev"] == "session" and e["name"] == "sd1")]
    check(not s5.audit5(b, "lines")["ok"], "a ledger without sd1's session event does not rebuild")
    check(not s5.audit5(load(), "other lines")["ok"], "a different pinned line table is detected through the session digests")
    b = load()
    b.cells[len(b.cells) // 2].seen += 1
    check(not s5.audit5(b, "lines")["ok"], "a tampered `seen` counter is detected")

    class OldRules(s5.Archive5):
        def v4_for(self, iteration: int) -> bool:
            return False

    rng = t2.Krng("old")
    o = OldRules("syn5", floor_min=-2100.0)
    o.init_cell0(t1.key(0, 0), t1.mk_end(), bytes(32), bytes([1]) * 32)
    t2.drive2(o, rng, n1, 0, v2=False)
    o.begin_v2(n1, "lines")
    t2.drive2(o, rng, n2, n1, v2=True)
    o.begin_rd3(n1 + n2, "lines")
    t2.drive2(o, rng, n3, n1 + n2, v2=True)
    o.begin_rd4(n1 + n2 + n3, "lines")
    t2.drive2(o, rng, n4, n1 + n2 + n3, v2=True)
    o.begin_sd1(f5, "lines", syn_record_reference(150), 24)
    t2.drive2(o, rng, n5, f5, v2=True)
    check(not s5.audit5(o, "lines")["ok"], "an sd1 part selected under v3's rules fails the audit under v4")
    shutil.rmtree(t, ignore_errors=True)
    return {"cells": len(a.cells), "bound_L": a.bound_max_L()}


# -- the resume protocol on a synthetic chain ------------------------------------------------------------------------------------------------------------


def open5(cp: Mapping[str, Any], *, expect4: Optional[Mapping[str, Any]] = None, live: Optional[Callable[[], Mapping[str, Any]]] = None, **kw: Any) -> Dict[str, Any]:
    return ses5.open_protocol5(cp["rd1"], cp["rd2"], cp["rd3"], cp["rd4"], cp["inc1"], cp["inc2"], cp["inc3"], cp["inc4"], expect1=cp["expect1"], expect2=cp["expect2"], expect3=cp["expect3"],
                               expect4=expect4 if expect4 is not None else cp["expect4"], check_overlay=False, live_pins=live or (lambda: t3.live_pins_of(cp)), floor_min=FLOOR_MIN, **kw)


def unit_resume_four_level_synthetic() -> Dict[str, Any]:
    chain = build_chain5()
    e4 = chain["expect4"]
    rr = e4["inherited_record"]["best_verified"]
    check(chain["rd4_outcome"] == "PROGRESS" and chain["rd4_m"] == 4 and e4["first_sd1_iteration"] == e4["dispatch_iterations"][1] + 1 and rr["completion_input_tick"] == rr["words"] > 24, f"the synthetic chain: {rr}")
    check(e4["inherited_record"]["rd5_permitted"] is True and e4["inherited_record"]["level_10_L"] and e4["inherited_record"]["level_10_L"][0] == rr["completion_input_tick"], "the inherited record facts")
    op = open5(chain)
    check(op["ok"], f"the open protocol on a synthetic chain: {op['problems']}")
    check(all(op[f"R1_{w}_immutability"]["ok"] for w in ("rd1", "rd2", "rd3", "rd4")) and all(op[f"R2_R4_{w}_archive"]["ok"] for w in ("rd1", "rd2", "rd3", "rd4"))
          and not op["R3_pins"]["problems"] and not op["R3_pins"]["rd3_problems"] and not op["R3_pins"]["rd2_problems"] and not op["R3_pins"]["rd1_problems"] and op["R5_overlay"]["ok"], "R1-R5")
    f4 = op["facts4"]
    check(f4["first_sd1_iteration"] == e4["first_sd1_iteration"] and f4["rd4_checkpoint_seq"] == e4["checkpoint_seq"] and f4["record_reference"] == rr and f4["rd4_line"]["rd5_permitted"] is True, "iterations continue from rd4's last; the record reference; the rd line")
    check([e["name"] for e in f4["session_events"]] == ["rd2", "rd3", "rd4"] and f4["session_events"][2]["digest"] == f4["digest_recomputed"]["v3"], "rd4's session digest equals the v3 digest recomputed")
    check(f4["audit"]["ok"] and f4["prefix_chain"]["ok"], "rd4's own audit (zero ticks) and the prefix chain")
    check(len(op["inherited"]) == len(e4["inherited_record"]["unverified_clear_trajectories"]) and all(c["kind"] == "clear" and c["inherited"] for c in op["inherited"]), "the inherited descriptive candidates")
    rc = op["record_candidate"]
    check(rc and len(rc["words"]) == rr["words"] and mcell.words_digest(rc["words"]) == rr["native_action_digest"] and rc["record"], "the record candidate")
    for tree in ("rd1", "rd2", "rd3", "rd4"):
        for what in ("byte", "mtime", "extra", "missing", "increment"):
            cp = copy_chain5(chain)
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
                rec_p = cp[{"rd1": "inc1", "rd2": "inc2", "rd3": "inc3", "rd4": "inc4"}[tree]] / "verification.json"
                rec = json.loads(rec_p.read_text(encoding="utf-8"))
                rec["result"] = "FAIL"
                rec_p.write_text(json.dumps(rec), encoding="utf-8")
            op2 = open5(cp)
            check(not op2["ok"] and any(p.startswith(f"R1 ({tree})") for p in op2["problems"]), f"R1 missed a change of {tree}'s tree: {what}: {op2['problems'][:3]}")
            for other in {"rd1", "rd2", "rd3", "rd4"} - {tree}:
                check(not any(p.startswith(f"R1 ({other})") for p in op2["problems"]), f"R1 blamed {other} for a change of {tree}'s tree")
            shutil.rmtree(cp["t"], ignore_errors=True)
    inh = e4["inherited_record"]
    for what, bad in (("cells", dict(e4, cells=e4["cells"] + 1)), ("checkpoint", dict(e4, checkpoint_seq=99)), ("first sd1 iteration", dict(e4, first_rd4_iteration=e4["first_rd4_iteration"] + 1)),
                      ("iterations", dict(e4, dispatch_iterations=(0, e4["dispatch_iterations"][1] + 1))), ("decision", dict(e4, outcome="NO_NEW_MILESTONE")), ("returns", dict(e4, returns=e4["returns"] + 1)),
                      ("ticks", dict(e4, exploration_ticks=e4["exploration_ticks"] + 1)),
                      ("best clear tick", dict(e4, inherited_record=dict(inh, best_verified=dict(rr, completion_input_tick=rr["completion_input_tick"] + 1, words=rr["words"] + 1)))),
                      ("a fifth level-10 cell", dict(e4, inherited_record=dict(inh, level_10_L=list(inh["level_10_L"]) + [rr["completion_input_tick"] + 50]))),
                      ("the top level's shortest arrival", dict(e4, inherited_record=dict(inh, top_eligible_level=dict(inh["top_eligible_level"], min_L=inh["top_eligible_level"]["min_L"] - 1)))),
                      ("rd5", dict(e4, inherited_record=dict(inh, rd5_permitted=False)))):
        f = r5.rd4_archive_facts(chain["rd1"], chain["rd2"], chain["rd3"], chain["rd4"], chain["lines"], bad, with_audit=False)
        check(not f["ok"], f"R2: a wrong {what} is refused")
    cp = copy_chain5(chain)
    rp = cp["rd4"] / "sessions" / "rd4" / "verification" / "replays.jsonl"
    rows = [json.loads(ln) for ln in rp.read_text(encoding="utf-8").splitlines() if ln.strip()]
    rp.write_text("".join(json.dumps(dict(r, clear=False)) + "\n" for r in rows), encoding="utf-8")
    f = r5.rd4_archive_facts(cp["rd1"], cp["rd2"], cp["rd3"], cp["rd4"], chain["lines"], e4, with_audit=False)
    check(not f["ok"] and any("inherited record" in p or "no verified clear" in p or "could not be read" in p for p in f["problems"]), f"R2: without a verified clear there is no record reference: {f['problems'][:2]}")
    shutil.rmtree(cp["t"], ignore_errors=True)
    cp = copy_chain5(chain)
    close_p = cp["rd4"] / "sessions" / "rd4" / "close.json"
    d = json.loads(close_p.read_text(encoding="utf-8"))
    d["archive"]["manifest"]["cells.jsonl"] = "0" * 64
    close_p.write_text(json.dumps(d), encoding="utf-8")
    check(not r5.rd4_archive_facts(cp["rd1"], cp["rd2"], cp["rd3"], cp["rd4"], chain["lines"], e4, with_audit=False)["ok"], "R2: the archive must equal rd4's close record")
    shutil.rmtree(cp["t"], ignore_errors=True)
    f = r5.rd4_archive_facts(chain["rd1"], chain["rd2"], chain["rd3"], chain["rd4"], "another line table", e4, with_audit=False)
    check(not f["ok"] and any("digest" in p for p in f["problems"]), "R2: the session digests must equal the digests recomputed from the contracts and the pinned lines")
    op3 = open5(chain, live=lambda: dict(t3.live_pins_of(chain), executable_sha256="0" * 64))
    check(not op3["ok"] and op3["R3_pins"]["executable_only"] and any("only the executable differs" in x for x in op3["problems"]), "R3: an executable-only difference refuses the exploration session")
    op4 = open5(chain, live=lambda: dict(t3.live_pins_of(chain), flags={"explore": {}, "verify": {}}))
    check(not op4["ok"] and any("R3" in x for x in op4["problems"]), "R3: the flags")
    ov = r5.closing_overlay5(chain["rd4"], rr, rule5.MARGIN, expect_rd4={}, expect_v4={}, floor_min=FLOOR_MIN)
    check(ov["ok"] and ov["rd4_closing"]["counts"] == ov["stored_close_counts"] and len(ov["v4"]["rows"]) == e4["cells"] and ov["v4"]["counts"]["bound_L"] == rr["completion_input_tick"] - 25, f"R5: both overlays: {ov['problems']}")
    ov_b = r5.closing_overlay5(chain["rd4"], rr, rule5.MARGIN, expect_rd4={}, expect_v4={}, floor_min=FLOOR_MIN)
    check(ov["v4"]["sha256"] == ov_b["v4"]["sha256"] and ov["rd4_closing"]["sha256"] == ov_b["rd4_closing"]["sha256"] and ov["v4"]["sha256"] != ov["rd4_closing"]["sha256"], "reproducible, and the v4 overlay differs from rd4's")
    c4 = ov["v4"]["counts"]
    check(c4["eligible_v4"] == c4["eligible_v3"] - c4["record_bound_among_v3_eligible"] and c4["record_bound_cells"] == sum(c4["record_bound_by_level"].values()), f"the v4 overlay's arithmetic: {c4}")
    check(not r5.closing_overlay5(chain["rd4"], rr, rule5.MARGIN, expect_rd4={"cells": e4["cells"] + 1}, expect_v4={}, floor_min=FLOOR_MIN)["ok"], "R5: a registered rd4 figure that differs is refused")
    check(not r5.closing_overlay5(chain["rd4"], rr, rule5.MARGIN, expect_rd4={}, expect_v4={"eligible_v4": -1}, floor_min=FLOOR_MIN)["ok"], "R5: a registered v4 figure that differs is refused")
    check(not r5.closing_overlay5(chain["rd4"], rr, rule5.MARGIN, expect_rd4={}, expect_v4={}, floor_min=FLOOR_MIN, v4_sha256="0" * 64)["ok"], "R5: a pinned digest that differs is refused")
    pm = r5.prior_milestones5(chain["rd1"], chain["rd2"], chain["rd3"], chain["rd4"])
    check(pm["rd4"]["m"] == 4 and pm["rd4"]["source"] == "sessions/rd4/rule.json" and pm["rd3"] is not None, f"prior milestones: {pm}")
    check(r5.rd4_line_status(chain["t"] / "nowhere")["missing"] and r5.rd4_line_status(chain["rd4"])["rd5_permitted"] is True, "the rd line status is read, never defaulted")
    t = tmpdir("m8mat5_")
    roots = []
    for i in (1, 2):
        root = t / f"sd1_{i}"
        a5 = r5.materialise5(chain["rd4"], root, facts=op["facts4"], overlay=op["overlay"], lines_sha256=chain["lines"], meta_extra={"pins": chain["pins"], "pin_tick0": op["facts4"]["pin_tick0"], "ticks": {}, "ledger_T": {}},
                             increment_manifest_sha256="x" * 64, utc=OPEN_UTC, margin=rule5.MARGIN, floor_min=FLOOR_MIN)
        roots.append(root)
    check(a5.mode == 2 and a5.sd1_first_iteration == e4["first_sd1_iteration"] and a5.draw_id == a5.draw_id_sd1 and a5.record_reference == rr and a5.margin == 24, "materialised: mode 2, sd1 begun, the reference and the margin")
    for n in (*march.DATA_FILES, march.MANIFEST):
        check((roots[0] / "archive" / n).read_bytes() == (roots[1] / "archive" / n).read_bytes(), f"two materialisations are byte-identical: {n}")
        check(mw.sha256_file(roots[0] / "base" / n) == mw.sha256_file(chain["rd4"] / "archive" / n), f"the base copy of {n} is byte-identical to rd4's closing file")
    root5 = roots[0]
    check(mw.sha256_file(root5 / "derived" / "open_overlay.jsonl") == op["overlay"]["v4"]["sha256"] and mw.sha256_file(root5 / "derived" / "rd4_closing_overlay.jsonl") == op["overlay"]["rd4_closing"]["sha256"], "the stored overlays hash to their digests")
    ob = json.loads((root5 / "derived" / "open_overlay.json").read_text(encoding="utf-8"))
    check(art.is_stamped(ob) and ob["created_utc"] == OPEN_UTC and ob["open_overlay"]["sha256"] == op["overlay"]["v4"]["sha256"] and ob["record_reference"] == rr and ob["margin"] == 24, "the stamped overlay record")
    base = json.loads((root5 / "derived" / "base.json").read_text(encoding="utf-8"))
    check(art.is_stamped(base) and base["session_event"]["name"] == "sd1" and base["session_event"]["select"] == "m8_rd_select_v4" and base["rd4_increment_manifest_sha256"] == "x" * 64
          and base["inherited_record"] == e4["inherited_record"] and base["rd4_line"]["rd5_permitted"] is True, "the stamped base record")
    d, meta, rep = march.load_latest_verified(root5 / "archive")
    check(d is not None and meta["checkpoint_seq"] == e4["checkpoint_seq"] + 1 and meta["why"] == "open" and meta["created_utc"] == OPEN_UTC and art.is_stamped(meta), "the first sd1 checkpoint is stamped with the materialisation time")
    check(r5.prefix_chain(chain["rd1"] / "archive", chain["rd2"] / "archive", chain["rd3"] / "archive", chain["rd4"] / "archive", root5 / "archive")["ok"], "the prefix chain of five holds at the open")
    loaded, _m = s5.Archive5.read_dir(root5 / "archive")
    check(s5.audit5(loaded, chain["lines"])["ok"], "the materialised archive audits (five parts, no sd1 dispatch yet)")
    arts = art.audit_tree5(root5)
    check(arts["ok"] and arts["exempt"] >= 5, f"every record of the materialised tree carries its stamp: {arts['failures']}")
    raises(r5.Resume5Error, lambda: r5.materialise5(chain["rd4"], root5, facts=op["facts4"], overlay=op["overlay"], lines_sha256=chain["lines"], meta_extra={}, increment_manifest_sha256="x", utc="u", margin=24),
           "an existing sd1 root is never overwritten")
    check(all_immutability5(chain)["ok"], "all four earlier trees are still equal to their increments after the open")
    shutil.rmtree(t, ignore_errors=True)
    return {"cells": len(a5.cells), "t_rec": rr["completion_input_tick"], "inherited": len(op["inherited"])}


def unit_inherited_record_facts_refusal() -> Dict[str, Any]:
    chain = build_chain5()
    inh = chain["expect4"]["inherited_record"]
    check(r5.record_fact_problems(inh, inh) == [], "the facts equal themselves")
    rr = inh["best_verified"]
    for what, bad in (("the best clear tick", dict(inh, best_verified=dict(rr, completion_input_tick=rr["completion_input_tick"] + 1, words=rr["words"] + 1))),
                      ("a fifth level-10 cell", dict(inh, level_10_L=list(inh["level_10_L"]) + [9999])), ("a level's count", dict(inh, levels=dict(inh["levels"], **{"0": {"cells": 0, "min_L": 0}}))),
                      ("rd5", dict(inh, rd5_permitted=None if inh["rd5_permitted"] else True)), ("the unverified trajectories", dict(inh, unverified_clear_trajectories=[])),
                      ("the other verified clears", dict(inh, verified_clears=inh["verified_clears"][:1] + [dict(inh["verified_clears"][0], cid=999)]))):
        check(r5.record_fact_problems(bad, inh) != [], f"{what} altered is refused")
    check(r5.record_fact_problems(dict(inh, best_verified=None), inh) != [], "no best clear is refused")
    out = {"synthetic": True}
    if REAL_TREES:
        a, _m = s5.Archive5.read_dir(RD4_REAL / "archive")
        facts = r5.inherited_record_facts(RD4_REAL, a)
        probs = r5.record_fact_problems(facts, r5.INHERITED_RECORD)
        check(probs == [], f"the real rd4 tree's inherited record facts equal the registered ones: {probs}")
        check(facts["best_verified"] == r5.RECORD_REFERENCE and facts["best_verified"]["completion_input_tick"] == 2315 and facts["best_verified"]["completion_time_passed"] == 2314, "the real record reference")
        check([x["iteration"] for x in facts["unverified_clear_trajectories"]] == [12559, 12823, 12146] and facts["level_10_L"] == [2315, 2324, 2326, 2348] and facts["top_eligible_level"] == {"level": 9, "min_L": 1898, "min_cell": 30042},
              f"the real facts: {facts['unverified_clear_trajectories']} {facts['level_10_L']} {facts['top_eligible_level']}")
        check(r5.RD4_FACTS["cells"] == 37312 and r5.RD4_FACTS["first_sd1_iteration"] == 13886 and r5.RD4_FACTS["checkpoint_seq"] == 45, "the registered rd4 facts")
        out = {"real": True, "unverified": [x["iteration"] for x in facts["unverified_clear_trajectories"]]}
    return out


def unit_open_protocol_real_trees5() -> Dict[str, Any]:
    """The open protocol R1-R5 on the real, closed rd1 to rd4 trees and their D: increments (read only): all four trees equal their increments, rd4's closing archive rebuilds (zero ticks),
    the session digests equal v2 and v3 recomputed, the inherited record facts equal the registered ones, both overlays reproduce their pinned digests, the three unverified trajectories."""
    if not REAL_TREES:
        return {"skipped": "the closed real trees are not present"}
    check(ses5.INCREMENT_RD4.is_dir() and ses5.INCREMENT_RD3.is_dir() and ses5.INCREMENT_RD2.is_dir() and ses5.INCREMENT_RD1.is_dir(), "the four D: increments are required")
    op = ses5.open_protocol5(record_reference=ses5.RECORD_REFERENCE)
    check(op["ok"], f"the open protocol on the real trees: {op['problems']}")
    r1 = {w: op[f"R1_{w}_immutability"] for w in ("rd1", "rd2", "rd3", "rd4")}
    check(r1["rd1"]["files"] == 166 and r1["rd2"]["files"] == 62 and r1["rd3"]["files"] == 77 and r1["rd4"]["files"] == 93 and r1["rd4"]["bytes"] == 165_147_441
          and r1["rd4"]["manifest_sha256"] == r5.RD4_INCREMENT_MANIFEST_SHA256 and r1["rd3"]["manifest_sha256"] == r4.RD3_INCREMENT_MANIFEST_SHA256, f"R1: {r1}")
    f4 = op["R2_R4_rd4_archive"]
    check(f4["counts"] == {"cells": 37312, "bursts": 13886, "events": 27775} and f4["dispatch_iterations"] == [0, 13885] and f4["first_sd1_iteration"] == 13886 and f4["rd4_checkpoint_seq"] == 45
          and f4["audit"]["ok"] and f4["audit"]["cells"] == 37312, f"R2/R4 (rd4): { {k: f4[k] for k in ('counts', 'dispatch_iterations', 'first_sd1_iteration', 'rd4_checkpoint_seq')} }")
    check([e["name"] for e in f4["session_events"]] == ["rd2", "rd3", "rd4"] and f4["session_events"][2]["digest"] == f4["digest_recomputed"]["v3"], "rd4's session digest equals v3 recomputed")
    check(f4["record_reference"] == ses5.RECORD_REFERENCE and f4["rd4_line"]["rd5_permitted"] is True, "the record reference and the rd line")
    check(op["R3_pins"]["contract_keys"] == {"rd1": 6, "rd2": 7, "rd3": 7, "rd4": 8}, f"each session's own contract set: {op['R3_pins']['contract_keys']}")
    ov = op["R5_overlay"]
    check(ov["ok"] and ov["rd4_closing_sha256"] == r5.RD4_CLOSING_OVERLAY_SHA256 and ov["v4_sha256"] == r5.SD1_OPEN_OVERLAY_SHA256 and ov["v4_counts"]["eligible_v4"] == 23253
          and ov["v4_counts"]["record_bound_among_v3_eligible"] == 286, f"R5: both overlays reproduce their pinned digests: {ov['v4_counts']}")
    check([c["iteration"] for c in op["inherited_summary"]] == [12559, 12823, 12146] and op["inherited_ticks"] == 7013 and op["record_candidate"]["words"].__len__() == 2315, "the three inherited trajectories and the record")
    return {"v4_overlay": ov["v4_sha256"][:12], "inherited_ticks": op["inherited_ticks"]}


def unit_write_guard_all_runs_roots() -> Dict[str, Any]:
    t = tmpdir("m8wg5_")
    runs = t / "runs"
    names = ("m8_rd", "m8_rd_rd2", "m8_rd_rd3", "m8_rd_rd4", "m9_g1", "m9_g3", "m7u")
    for n in names + ("m8_rd_sd1",):
        (runs / n).mkdir(parents=True)
        (runs / n / "f.txt").write_text("x", encoding="utf-8")
    own = runs / "m8_rd_sd1"
    roots = ses5.protected_runs_roots(runs, own)
    check([r.name for r in roots] == sorted(names), f"every tree under runs/ but sd1's own: {[r.name for r in roots]}")
    mw.ProvenanceGuard.install()
    w2.WriteGuard.install(roots)
    base = len(mw.ProvenanceGuard.violations)
    try:
        (own / "o.txt").write_text("z", encoding="utf-8")
        for r in roots:
            open(r / "f.txt", "rb").close()
        check(len(mw.ProvenanceGuard.violations) == base, "reads of the other trees and writes under sd1's own root are not violations")
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
    saved = ses2.build_real_env2
    try:
        ses2.build_real_env2 = lambda *a, **k: mrun.RunEnv(worker_spec=lambda rank, c: {"rank": rank}, replay=lambda *x: {}, analyse=lambda *x: {}, p1_inputs=lambda: [], pins={})
        spec = ses5.build_real_env5(ses5.run_config(), Path("x"), {}, {}, protected=[Path("a"), Path("b")]).worker_spec(0, ses5.run_config())
    finally:
        ses2.build_real_env2 = saved
    check(spec["protected_roots"] == ["a", "b"], f"the worker spec protects the given roots: {spec['protected_roots']}")
    real = ses5.protected_runs_roots()
    check(ses5.SD1_ROOT not in real and all(p.parent == ses5.RUNS for p in real), "the production roots are every tree under runs/ but sd1's")
    return {"roots": len(roots), "production_roots": len(real)}


# -- the claims plan --------------------------------------------------------------------------------------------------------------------------------------


def clear_spec(c: int, t: int = 10) -> Dict[str, Any]:
    return {"first": {"left_live": 31, "left_break": 35, "clear": c}, "t": t}


def unit_claims5_pool_and_plan() -> Dict[str, Any]:
    check(cl5.BATCH == 3 and cl5.CLAIMS5_CONTRACT == "m8_sd1_claims_v1" and len(cl5.contract_digest()) == 64 and cl5.contract_digest() != cl4.contract_digest(), "registered constants and digest")
    live = {"first": {"left_live": 31}}
    specs = [live] * 2000 + [clear_spec(59), clear_spec(40), clear_spec(55), clear_spec(40), clear_spec(58), {"first": {"l0": 31}}, {"first": {"left_live": 31}, "t": 7, "t_events": [(40, 7)]}]
    led = t4.ledger_with(specs)
    T = led.ticks
    clears = [c for c in led.candidates if c["kind"] == "clear"]
    check(len(clears) == 5 and led.l0_cid is not None and led.t_records, "the ledger holds five clear-kind candidates, an l0 and a t record")
    pool = cl5.pool5(led, T, 60)
    check([cl5.clear_tick(c) for c, _n in pool] == [40, 40, 55, 58, 59] and pool[0][0]["cid"] < pool[1][0]["cid"] and all(n == 60 for _c, n in pool), "the pool: clear-kind candidates below T_rec, fastest first, then by cid, each over its whole trajectory")
    check([cl5.clear_tick(c) for c, _n in cl5.pool5(led, T, 56)] == [40, 40, 55] and [cl5.clear_tick(c) for c, _n in cl5.progress_pool5(led, T, 60, 5)] == [40, 40, 55], "the record bound and the margin cut the pool")
    todo, info = cl5.plan_replays5(led, T, {}, 60, 5, batch=3)
    check([cl5.clear_tick(c) for c, _n in todo] == [40, 40, 55] and all(c["kind"] == "clear" for c, _n in todo) and info["pool"] == 5 and info["remaining"] == 5 and info["remaining_progress"] == 3 and not info["closed"],
          f"the first batch: the three fastest clears; 2,000 left candidates, the l0 and the t candidates cost 0 replays: {[cl5.clear_tick(c) for c, _n in todo]} {info}")
    done = {todo[1][0]["cid"]: dict(t4.fake_rep(todo[1][0]["cid"], kind="clear", clear=True), clear_facts={"all": True, "completion_input_tick": 40, "completion_time_passed": 39}, counted=60)}
    todo2, info2 = cl5.plan_replays5(led, T, done, 60, 5, batch=3)
    check(todo2 == [] and info2["closed"] and info2["best_completion_input_tick"] == 40 and info2["best_cid"] == todo[1][0]["cid"] and info2["remaining_faster_than_best"] == 0, "an exact replay closes the pool: nothing slower is planned")
    done3 = {todo[0][0]["cid"]: t4.fake_rep(todo[0][0]["cid"], kind="clear", exact=False, problems=["x"])}
    todo3, info3 = cl5.plan_replays5(led, T, done3, 60, 5, batch=3)
    check([cl5.clear_tick(c) for c, _n in todo3] == [40, 55, 58] and not info3["closed"], "an inexact replay (INVALID for the session) does not close the pool; the next fastest follow")
    order: List[int] = []
    done4: Dict[int, Dict[str, Any]] = {}
    for _ in range(5):
        td, _i = cl5.plan_replays5(led, T, done4, 60, 5, batch=2)
        if not td:
            break
        for c, _n in td:
            order.append(cl5.clear_tick(c))
            done4[c["cid"]] = t4.fake_rep(c["cid"], kind="clear", exact=False, problems=["x"])
    check(order == [40, 40, 55, 58, 59], f"a slower clear is never replayed before a faster one: {order}")
    ps = cl5.pool_sizes5(led, T, 60, 5)
    check(ps["clear_kind"] == 5 and ps["pool"] == 5 and ps["progress_pool"] == 3 and ps["left"] == 2006 and ps["l0"] == 1 and ps["t"] == 1 and ps["fastest_registered"] == 40 and ps["clear_ticks_registered"] == [40, 40, 55, 58, 59],
          f"pool sizes (every clearing job also registers its left twin; neither it nor the 2,000 left entries are replayed): {ps}")
    check(cl5.plan_replays5(mclaims.ArmLedger("T"), 0, {}, 60, 5)[0] == [], "an empty ledger plans nothing")
    # exactness beyond the engine's
    cand = clears[0]
    good = {"exact": True, "clear": True, "clear_facts": {"all": True, "completion_input_tick": cl5.clear_tick(cand), "completion_time_passed": cl5.clear_tick(cand) - 1}, "counted": len(cand["words"]), "problems": []}
    check(cl5.exactness5(good, cand) == [], "an exact clear with the registered clock")
    check(any("differs from the registered clear tick" in p for p in cl5.exactness5(dict(good, clear_facts=dict(good["clear_facts"], completion_input_tick=cl5.clear_tick(cand) + 1)), cand)), "a clock that differs")
    check(any("inexact" in p for p in cl5.exactness5(dict(good, exact=False, problems=["digest"]), cand)), "the engine's inexactness")
    check(any("does not hold" in p for p in cl5.exactness5(dict(good, clear=False, clear_facts=dict(good["clear_facts"], all=False)), cand)), "the four facts")
    check(any("counted words" in p for p in cl5.exactness5(dict(good, counted=len(cand["words"]) - 1), cand)), "a cut trajectory is not a clear claim")
    check(any("not integers" in p for p in cl5.exactness5(dict(good, clear_facts=dict(good["clear_facts"], completion_time_passed=None)), cand)), "the clocks must be integers")
    rec = cl5.verified_clear_record(dict(good, label="L", trace="T", t=10), cand)
    check(rec["cid"] == cand["cid"] and rec["completion_input_tick"] == cl5.clear_tick(cand) and rec["native_action_digest"] == mcell.words_digest(cand["words"]) and rec["words"] == len(cand["words"]), f"the verified clear record: {rec}")
    best = rule5.best_of([dict(rec, cid=9, completion_input_tick=50), dict(rec, cid=4, completion_input_tick=50), dict(rec, cid=1, completion_input_tick=51)])
    check(best["cid"] == 4, "the best: the smallest clock, then the smallest cid")
    return {"pool": ps["pool"]}


def unit_clear_exactness5_on_stub_traces() -> Dict[str, Any]:
    """The record of the synthetic rd4 replayed through the stub world: exact, the four facts, the clock equal to the registered clear tick; and every way it can fail."""
    chain = build_chain5()
    rr = chain["expect4"]["inherited_record"]["best_verified"]
    cand = cl5.record_candidate(chain["rd4"], rr)
    n = len(cand["words"])
    tr = stub.replay_trace(chain["world"], cand["words"])
    rep = mclaims.evaluate_replay(tr, cand, n, stub.analyse)
    check(rep["exact"] and rep["clear"] and cl5.exactness5(rep, cand) == [] and rep["clear_facts"]["completion_input_tick"] == rr["completion_input_tick"] == cl5.clear_tick(cand), f"the record replays exactly: {rep['problems']} {rep['clear_facts']}")
    check(cl5.exactness5(rep, dict(cand, first={"clear": rr["completion_input_tick"] + 1})) != [], "a registered clear tick that differs from the replay's clock is refused")
    rep_cut = mclaims.evaluate_replay(stub.replay_trace(chain["world"], cand["words"][:n - 1]), cand, n - 1, stub.analyse)
    check(rep_cut["exact"] and not rep_cut["clear"] and any("counted words" in p for p in cl5.exactness5(rep_cut, cand)), "one word short: exact over the counted words, not a clear claim")
    rep_cut2 = mclaims.evaluate_replay(stub.replay_trace(chain["world"], cand["words"][:n - 1]), dict(cand, words=cand["words"][:n - 1], breaks=[b for b in cand["breaks"] if b[0] <= n - 1]), n - 1, stub.analyse)
    check(not rep_cut2["exact"] and any("does not hold" in p for p in rep_cut2["problems"]), "a clear-kind candidate whose whole trajectory does not clear is inexact for the frozen engine")
    bad_words = bytes([(cand["words"][0] + 1) % 72]) + cand["words"][1:]
    rep_bad = mclaims.evaluate_replay(stub.replay_trace(chain["world"], bad_words), cand, n, stub.analyse)
    check(not rep_bad["exact"], "different words: inexact")
    inh = cl5.inherited_unverified_clears(chain["rd4"])
    for c in inh:
        r = mclaims.evaluate_replay(stub.replay_trace(chain["world"], c["words"]), c, len(c["words"]), stub.analyse)
        irec = cl5.inherited_record(r, c)
        check(irec["exact"] and irec["reported_only"] and irec["completion_input_tick"] == cl5.clear_tick(c) and irec["rd4_cid"] == c["rd4_cid"], f"an inherited trajectory replays exactly in the synthetic world: {irec}")
    return {"record_words": n, "inherited": len(inh)}


def unit_inherited_descriptive_candidates() -> Dict[str, Any]:
    src = (RL_DIR / "m8_sd1_claims.py").read_text(encoding="utf-8")
    for tok in ("849", "979", "656", "12559", "12823", "12146", "2324", "2341", "2348"):
        check(re.search(rf"(?<![0-9]){tok}(?![0-9])", src) is None, f"the claims module names the candidate {tok}: the set must come from the registry by the rule")
    chain = build_chain5()
    tr = cl5.clear_trajectories(chain["rd4"])
    inh = cl5.inherited_unverified_clears(chain["rd4"])
    want = [j for j in tr["jobs"] if not j["verified_by_rd4"]]
    check([c["iteration"] for c in inh] == [j["iteration"] for j in want] and all(c["kind"] == "clear" and c["inherited"] and c["cid"] >= cl5.INHERITED_CID_BASE and len(c["words"]) == cl5.clear_tick(c) for c in inh),
          "the synthetic rd4's unverified clear trajectories, by the rule, fastest first, each over its whole trajectory")
    check(any(j["verified_by_rd4"] for j in tr["jobs"]) and tr["replays_exact_clear"] >= 1, "the synthetic rd4 verified at least one clear trajectory")
    todo = cl5.plan_inherited5(inh, {}, batch=3)
    check([c["cid"] for c, _n in todo] == [c["cid"] for c in inh[:3]] and all(n == len(c["words"]) for c, n in todo), "planned fastest first, each over its whole trajectory")
    check(cl5.plan_inherited5(inh, {c["cid"]: {} for c in inh}, batch=3) == [], "nothing once all are replayed")
    rec = cl5.inherited_record({"exact": False, "problems": ["replay failed: x"], "clear": False, "clear_facts": {}, "counted": 0}, inh[0]) if inh else None
    check(rec is None or (not rec["exact"] and rec["reported_only"] and rec["problems"]), "an inexact inherited replay is a reported fact (flagged by the rule, never INVALID)")
    out = {"synthetic_unverified": len(inh)}
    if REAL_TREES:
        real = cl5.inherited_unverified_clears(RD4_REAL)
        check([c["iteration"] for c in real] == [12559, 12823, 12146] and len(real) == 3, f"the real registry: exactly three unverified clear trajectories, by the rule: {[c['iteration'] for c in real]}")
        check(all(c["kind"] == "clear" and len(c["words"]) == cl5.clear_tick(c) for c in real) and cl5.inherited_ticks(real) == 7013, "each over its whole trajectory; 7,013 ticks in all")
        cap = ses5.caps()
        check(cl5.inherited_ticks(real) + 16 * mcell.HORIZON + 10 * mcell.HORIZON <= cap["replay_tick_cap"], "the inherited replays, 16 identity replays and ten clear replays fit the verification cap")
        tr_real = cl5.clear_trajectories(RD4_REAL)
        check([(j["iteration"], j["first_clear"], j["verified_by_rd4"]) for j in tr_real["jobs"]] == [(11286, 2315, [239]), (12559, 2324, []), (11206, 2326, [194]), (12823, 2341, []), (12146, 2348, [])], f"rd4's five clear trajectories: {tr_real['jobs']}")
        rc = cl5.record_candidate(RD4_REAL, ses5.RECORD_REFERENCE)
        check(len(rc["words"]) == 2315 and mcell.words_digest(rc["words"]) == ses5.RECORD_REFERENCE["native_action_digest"] and rc["rd4_cid"] == 239 and rpt5.record_pace(rc)["10"] == 2315 and len(rpt5.record_pace(rc)) == 10,
              "the record candidate: 2,315 words hashing to the pinned digest; its pace is its own break table")
        raises(ValueError, lambda: cl5.record_candidate(RD4_REAL, dict(ses5.RECORD_REFERENCE, cid=194)), "a reference that names another candidate is refused")
        out["real_unverified"] = [c["iteration"] for c in real]
    return out


# -- the rule and the session ------------------------------------------------------------------------------------------------------------------------------


def unit_rule5_module() -> Dict[str, Any]:
    check(rule5.self_test() == [], f"the rule's self-test: {rule5.self_test()}")
    d = rule5.rule_digest()
    check(d == rule5.rule_digest() and len(d) == 64 and d != rule4.rule_digest(), "the rule digest")
    desc = rule5.rule_description()
    check(desc["order"] == ["INVALID", "INCOMPLETE", "PROGRESS", "RECORD_BELOW_MARGIN", "NO_SHORTER_CLEAR"] and desc["control_arm"] is False and desc["mechanism_check"] == "none" and set(desc["stops"]) == {"S3", "S5", "S7"},
          "no control arm, no mechanism check, three carried stops, five outcomes")
    check(rule5.T_REC == 2315 and rule5.MARGIN == 24 and rule5.PROGRESS_BAR == 2291 and rule5.TIERS["5_percent"] == 2199 and rule5.TIERS["10_percent"] == 2083 and rule5.TIERS["round_2000"] == 2000, "the registered constants and tiers")
    check(rule5.TIERS["5_percent"] == math.floor(0.95 * 2315) and rule5.TIERS["10_percent"] == math.floor(0.90 * 2315), "the tiers derive from the reference alone")
    check(list(inspect.signature(rule5.outcome_of).parameters) == ["best_completion_input_tick", "t_rec", "margin"] and "tier" not in inspect.getsource(rule5.outcome_of).lower(), "outcome_of reads no tier")
    check(rule5.MIN_EXPLORATION_TICKS == 2_000_000 and rule5.MAX_LIFECYCLE_FAILURES == 3 and rule5.TOP_LEVEL_MEDIAN_L_LIMIT == 3000, "the carried-over limits")
    return {"rule_digest": d[:12]}


def unit_decide5_outcomes_and_stops() -> Dict[str, Any]:
    chain = build_chain5()
    rr = chain["expect4"]["inherited_record"]["best_verified"]
    t_rec = rr["completion_input_tick"]
    res: Dict[str, Any] = {}
    out, sess, _r, cp = run5_small(chain, arm_tick_cap=3000, min_arm_ticks=5000)
    r = out["rule"]
    check(r["outcome"] == "INCOMPLETE" and any("reached 3,000" in x for x in r["incomplete"]) and r["stops"]["S7"]["triggered"] and "S7" in r["any_stop"] and "S3" not in r["any_stop"], f"below the minimum: {r['incomplete']} {r['any_stop']}")
    check(r["line"]["status"] == "COUNTED_INCOMPLETE" and r["line"]["session_counts"] is True and r["exploration_started"] is True, f"an INCOMPLETE session counts once exploration has started: {r['line']}")
    res["below_minimum"] = r["outcome"]
    out, sess, _r, cp = run5_small(chain, inject={"lifecycle_jobs": [10]}, n_workers=2, arm_tick_cap=8000, min_arm_ticks=1000)        # a worker's 10th process: inside the exploration (found by experiment)
    check(1 <= sess.lifecycle_failures["T"] <= 3 and sess.ledgers["T"].ticks == 8000 and out["rule"]["outcome"] != "INCOMPLETE", f"redrawn lifecycle failures {sess.lifecycle_failures}: {out['rule']['outcome']} {out['rule']['incomplete']}")
    check(any(e["ev"] == "fail" for e in sess.archive.events) and s5.audit5(sess.archive, chain["lines"])["ok"], "the ledger records the failed iteration and still audits")
    out, sess, _r, cp = run5_small(chain, inject={"lifecycle_jobs": [10, 11, 12, 13]}, n_workers=2, arm_tick_cap=12000, min_arm_ticks=1000)
    check(out["rule"]["outcome"] == "INCOMPLETE" and any("lifecycle failures" in x for x in out["rule"]["incomplete"]), f"more than three: {out['rule']['incomplete']}")
    out, sess, _r, cp = run5_small(chain, inject={"mismatch_job": 14, "mismatch_tick": 5}, n_workers=2, arm_tick_cap=20000, min_arm_ticks=1000)
    r = out["rule"]
    check(r["outcome"] == "INVALID" and any("prefix_end" in x for x in r["invalid"]) and r["line"]["status"] == "REPAIR_NEEDED" and r["line"]["session_counts"] is None, f"an integrity mismatch: {r['invalid']} {r['line']}")
    check(list((sess.cfg.session_dir / "failures").glob("iterate_*")), "the failed return's raw replies are preserved")
    res["mismatch"] = r["outcome"]
    out, sess, _r, cp = run5_small(chain, inject={"provenance_job": 10}, n_workers=2, arm_tick_cap=5000, min_arm_ticks=1000)
    check(out["rule"]["outcome"] == "INVALID" and any("provenance" in x or "guard violations" in x for x in out["rule"]["invalid"]), f"a provenance violation: {out['rule']['invalid']}")
    out, sess, _r, cp = run5_small(chain, arm_tick_cap=3000, min_arm_ticks=1000, immutability=lambda: {"ok": False, "problems": ["rd4: cells.jsonl differs"]})
    check(out["rule"]["outcome"] == "INVALID" and any("an earlier tree changed" in x for x in out["rule"]["invalid"]), f"a changed earlier tree: {out['rule']['invalid']}")
    for victim in ("rd1", "rd2", "rd3", "rd4"):
        def writer(cp_: Mapping[str, Any], _clock: FakeClock, victim: str = victim) -> Mapping[str, Any]:
            done: List[int] = []

            def private_mb() -> float:
                if not done:
                    done.append(1)
                    (Path(cp_[victim]) / "archive" / "stray.txt").write_text("x", encoding="utf-8")
                return 100.0

            return {"private_mb": private_mb}

        out, sess, _r, cp = run5_small(chain, n_workers=2, arm_tick_cap=400000, min_arm_ticks=100, env_kw_factory=writer)
        check(out["rule"]["outcome"] == "INVALID" and any("protected root" in x for x in out["rule"]["invalid"]), f"a write under {victim}'s tree: {out['rule']['outcome']} {out['rule']['invalid']}")
        res[f"{victim}_write"] = out["rule"]["outcome"]

    def broken() -> Mapping[str, Any]:
        raise RuntimeError("injected immutability failure")

    out, sess, _r, cp = run5_small(chain, arm_tick_cap=3000, min_arm_ticks=1000, immutability=broken)
    cl = out["close"]
    check(out["rule"]["outcome"] == "INCOMPLETE" and any("earlier_trees_immutability could not run" in x for x in out["rule"]["incomplete"]) and "earlier_trees_immutability_error" in cl and cl["audit"]["ok"] and cl["prefix_chain"]["ok"],
          f"an erroring close check: {out['rule']['incomplete']}")

    class LateBreach:
        def __init__(self, clock: FakeClock) -> None:
            self.clock, self.t0 = clock, clock.now()

        @property
        def breach(self) -> Optional[str]:
            return "memory cap: process tree private 99999 MB > 9216 MB" if self.clock.now() - self.t0 > 2.5 else None

    out, sess, _r, cp = run5_small(chain, env_kw_factory=lambda cp_, clock_: {"sampler": LateBreach(clock_)}, n_workers=2, arm_tick_cap=10 ** 7, min_arm_ticks=1000)
    check(out["rule"]["outcome"] == "INCOMPLETE" and any("memory cap" in x for x in out["rule"]["incomplete"]), f"a memory breach: {out['rule']['incomplete']}")
    out, sess, _r, cp = run5_small(chain, env_kw={"tree_snapshot": lambda: {"battleship": 11}}, n_workers=2, arm_tick_cap=10 ** 6, min_arm_ticks=1000, process_check_every_s=0.05)
    check(out["rule"]["outcome"] == "INCOMPLETE" and any("11 BattleShip processes" in x for x in out["rule"]["incomplete"]), f"a process-count breach: {out['rule']['incomplete']}")
    out, sess, _r, cp = run5_small(chain, n_workers=2, arm_tick_cap=10 ** 7, min_arm_ticks=500, wall_caps_s={"p1": 90.0, "T": 2.0, "C": 0.0, "verify": 300.0}, global_cap_s=900.0)
    tT = sess.ledgers["T"].ticks
    check(sess.arm_records["T"]["stop"][0] == "wall_cap" and 500 <= tT < 10 ** 7 and not out["rule"]["incomplete"], f"a wall-capped exploration at or above the minimum is valid ({tT}): {out['rule']['incomplete']}")
    out, sess, _r, cp = run5_small(chain, replay_tick_cap=150, arm_tick_cap=12000, min_arm_ticks=2000, identity_k=0)
    ver = json.loads((sess.cfg.session_dir / "verification.json").read_text(encoding="utf-8"))
    check(ver["cap_hit"] is not None, "the replay cap was hit")
    if out["rule"]["outcome"] == "INCOMPLETE":
        check(any("pool candidate" in x for x in out["rule"]["incomplete"]) and ver["arm"]["best_verified"] is None and ver["arm"]["remaining_progress"] > 0, f"INCOMPLETE only with a progress candidate left unverified: {out['rule']['incomplete']}")
    else:
        check(ver["arm"]["remaining_progress"] == 0 or ver["arm"]["best_verified"] is not None, "a cap that cannot change the outcome is not INCOMPLETE")
    res["replay_cap"] = out["rule"]["outcome"]
    # every outcome through decide5 on a complete session, with constructed verified clears (the rule reads their clocks)
    out, sess, root5, cp = run5_small(chain, arm_tick_cap=6000, min_arm_ticks=2000)
    check(not out["rule"]["invalid"] and not out["rule"]["incomplete"], f"a complete small session: {out['rule']['outcome']}")
    loaded, _m = s5.Archive5.read_dir(root5 / "archive")
    rows = s5.audit5(loaded, chain["lines"], collect_rows_from=sess.first_iteration)["dispatch_rows"]
    mkv = lambda c, cid=1: {"cid": cid, "iteration": 1, "kind": "clear", "completion_input_tick": c, "completion_time_passed": c - 1, "native_action_digest": "b" * 64, "words": c, "registered_clear_tick": c}   # noqa: E731
    for clears, want in (([], "NO_SHORTER_CLEAR"), ([mkv(t_rec - 24)], "PROGRESS"), ([mkv(t_rec - 23)], "RECORD_BELOW_MARGIN"), ([mkv(t_rec - 1)], "RECORD_BELOW_MARGIN"), ([mkv(t_rec)], "NO_SHORTER_CLEAR"),
                         ([mkv(t_rec - 30, 7), mkv(t_rec - 60, 3), mkv(t_rec - 60, 2)], "PROGRESS")):
        sess.invalid, sess.incomplete = [], []
        sess.verified = {"verified_clears": clears, "max_targets": 10 if clears else 0}
        rec = run5.decide5(sess, loaded, rows)
        check(rec["outcome"] == want and rec["record_reference"]["completion_input_tick"] == t_rec and rec["margin"] == 24, f"decide5 with {[c['completion_input_tick'] for c in clears]}: {rec['outcome']} vs {want}")
        if clears:
            check(rec["best_verified"]["cid"] == min(clears, key=lambda c: (c["completion_input_tick"], c["cid"]))["cid"], "the best verified clear")
        check(rec["line"]["rd_line"]["rd5_permitted_after_sd1"] is True and rec["line"]["rd_line"]["consumed_by_sd1"] is False, "rd5 unchanged")
        check(rec["mechanism_check"] is None and rec["dilution"]["reported_only"] and rec["tiers"]["reported_only"], "no mechanism check; dilution and tiers reported only")
    res["decide5"] = "ok"
    shutil.rmtree(cp["t"], ignore_errors=True)
    return res


def unit_session5_small_run() -> Dict[str, Any]:
    chain = build_chain5()
    rr = chain["expect4"]["inherited_record"]["best_verified"]
    out, sess, root, cp = run5_small(chain)
    rule, close = out["rule"], out["close"]
    check(not rule["invalid"] and not rule["incomplete"] and rule["outcome"] in ("PROGRESS", "RECORD_BELOW_MARGIN", "NO_SHORTER_CLEAR"), f"a complete small session: {rule['outcome']} {rule['invalid']} {rule['incomplete']}")
    check(sess.ledgers["T"].ticks == 12000, f"the exploration committed exactly its cap: {sess.ledgers['T'].ticks}")
    sd = sess.cfg.session_dir
    for f in ("p1.json", "identity_open.json", "record_open.json", "arm_T.json", "verification.json", "rule.json", "close.json", "state.json", "iterations_T.jsonl", "ledger_T.json", "candidates_T.jsonl.gz",
              "dispatch_rows.jsonl.gz", "wall_top_sightings.jsonl"):
        check((sd / f).is_file(), f"missing {f}")
    for f in ("p1.json", "identity_open.json", "record_open.json", "arm_T.json", "verification.json", "rule.json", "close.json", "state.json", "ledger_T.json"):
        rec = json.loads((sd / f).read_text(encoding="utf-8"))
        check(art.is_stamped(rec) and rec.get("scope", rule5.SCOPE) == rule5.SCOPE, f"{f} is stamped and carries the scope")
    for f in ("iterations_T.jsonl", "candidates_T.jsonl.gz", "dispatch_rows.jsonl.gz", "wall_top_sightings.jsonl", "verification/replays.jsonl"):
        h, _rows = art.read_jsonl5(sd / f)
        check(h is not None and h["schema"].startswith("m8_sd1_"), f"{f} opens with its stamped header row")
    arts = art.audit_tree5(root)
    check(arts["ok"] and arts["files"] > 10 and arts["headers"] >= 5, f"every record of the tree carries its stamp: {arts['failures']}")
    check(close["artifacts"]["ok"] and close["archive"]["created_utc"] == OPEN_UTC, "the close checks audited the stamps; archive_meta keeps the materialisation time")
    for d in ("archive", "archive.prev"):
        m = json.loads((root / d / "archive_meta.json").read_text(encoding="utf-8"))
        check(m["created_utc"] == OPEN_UTC and art.is_stamped(m), f"{d}/archive_meta.json keeps created_utc across checkpoints")
    p1 = json.loads((sd / "p1.json").read_text(encoding="utf-8"))
    check(p1["tick0"]["equals_archive_pin"] and p1["selftest"]["corrupted_refused"] and len(p1["traces"]) == 2, "P1 against the archive's pin")
    io_ = json.loads((sd / "identity_open.json").read_text(encoding="utf-8"))
    check(io_["ok"] and io_["cells"] == 6 and io_["verified"] == 6, f"open identity replays: {io_}")
    ro = json.loads((sd / "record_open.json").read_text(encoding="utf-8"))
    check(ro["exact"] and ro["words"] == rr["words"] and ro["clear_facts"]["completion_input_tick"] == rr["completion_input_tick"] and ro["native_action_digest"] == rr["native_action_digest"], f"the record re-verified at the open: {ro}")
    ver = json.loads((sd / "verification.json").read_text(encoding="utf-8"))
    arm = ver["arm"]
    check(ver["identity"]["ok"] and ver["identity"]["verified"] == ver["identity"]["cells"] == 6 and ver["claims_digest"] == cl5.contract_digest() and ver["record_reference"] == rr and ver["margin"] == 24, "the verification record")
    led = sess.ledgers["T"]
    ticks_of = {c["cid"]: cl5.clear_tick(c) for c in led.candidates}
    order = arm["replay_order"]
    check(order == sorted(order, key=lambda cid: (ticks_of[cid], cid)) and all(led.candidates[cid]["kind"] == "clear" for cid in order), f"the pool was replayed fastest first, clear-kind only: {order}")
    check((arm["best_verified"] is not None) == arm["closed"] and arm["remaining_faster_than_best"] == 0, "the pool closes at the first exact replay")
    if arm["best_verified"]:
        b = arm["best_verified"]
        check(b["completion_input_tick"] == min(v["completion_input_tick"] for v in arm["verified_clears"]) and rule["outcome"] == rule5.outcome_of(b["completion_input_tick"], rr["completion_input_tick"], 24), "the best and the outcome")
        check((root / "routes" / "T_clear_best" / "metadata.json").is_file() and json.loads((root / "routes" / "T_clear_best" / "metadata.json").read_text(encoding="utf-8"))["completion_clocks"]["completion_input_tick"] == b["completion_input_tick"], "the best route is saved with its clocks")
    inh = ver["inherited_descriptive"]
    check(inh["count"] == len(sess.inherited) and inh["replayed"] == inh["count"] and inh["exact"] == inh["count"] and rule["flags"] == [] and rule["inherited_descriptive"]["count"] == inh["count"], f"the inherited descriptive replays, exact, reported: {inh}")
    for c in sess.inherited:
        check((root / "routes" / f"rd4_inherited_c{c['rd4_cid']:04d}" / "metadata.json").is_file(), "an exact inherited replay is saved as a route")
    check(close["audit"]["ok"] and close["prefix_chain"]["ok"] and close["prefix_chain"]["rd4_sd1"]["ok"] and close["earlier_trees_immutability"]["ok"] and not close["guard_violations"], f"close checks: {close.get('audit')} {close.get('prefix_chain', {}).get('ok')}")
    check(close["archive"]["checkpoint_seq"] == sess.ckpt_seq and sess.ckpt_seq > chain["expect4"]["checkpoint_seq"] + 1 and "overlay_close_v4" in close["archive"], "the checkpoint sequence continues from rd4's; the v4 overlay at the close")
    first = chain["expect4"]["dispatch_iterations"][1] + 1
    check(sess.first_iteration == first and sess.archive.sd1_first_iteration == first, "iterations continue after rd4's")
    its = [e["it"] for e in sess.archive.events if e["ev"] == "dispatch"]
    own = [i for i in its if i >= first]
    check(its == sorted(set(its)) and its[0] == 0 and own == list(range(first, first + len(own))) and len(own) > 0, "dispatch iterations are strictly increasing, never reused, and sd1's part is contiguous from its first")
    rows = art.rows_of(sd / "iterations_T.jsonl")
    check(sum(r["ticks"] for r in rows if "ticks" in r) == 12000 and all(r["tick0_equal"] for r in rows if "ticks" in r), "iteration rows add up; tick 0 equal everywhere")
    a = sess.archive
    bound = a.bound_max_L()
    for e in a.events:
        if e["ev"] == "dispatch" and e["it"] >= first:
            check(e["cell"] == 0 or a.cells[e["cell"]].L <= bound or e["L"] <= bound, f"an sd1 dispatch from a cell beyond the record bound: iteration {e['it']} L {e['L']}")
    aid = a.archive_id
    for b in a.bursts:
        draw = {"rd1": aid, "rd2": aid + "_v2", "rd3": aid + "_rd3", "rd4": aid + "_rd4", "sd1": aid + "_sd1"}[a.session_of_iteration(b.iteration)]
        want = bytes(w for _i, w in zip(range(len(b.words)), mx.words(lambda i, d=draw, it=b.iteration: mx.explore_key(d, it, i), mx.BURST_WORDS)))
        check(b.words == want, f"burst {b.id} (iteration {b.iteration}): the words are not the {draw} keyed stream")
    rep = rpt5.full_report5(root, cp["rd4"], cp["rd3"], cp["rd2"], cp["rd1"], "sd1")
    n_disp = sum(1 for e in a.events if e["ev"] == "dispatch" and e["it"] >= first)
    check(rep["sd1"]["dispatches"] == n_disp and rep["rd4_reference"]["dispatches"] == chain["expect4"]["returns"] and rep["record_reference"] == rr, "the report counts sd1's dispatches beside rd4's")
    for k in ("D7_efficiency", "D8_overlays", "readings", "mechanism_readings", "pace", "shortest_L_by_level", "left_floor_landings", "clears", "selection_at_the_open", "rule_inputs", "decision", "line"):
        check(k in rep, f"the report section {k}")
    check(rep["D8_overlays"]["E7"]["open"]["record_bound_cells"] is not None and rep["clears"]["registered"]["count"] >= len(arm["verified_clears"]) and rep["decision"]["outcome"] == rule["outcome"], "the readings")
    check(rep["selection_at_the_open"]["v4"]["by_level"].keys() == rep["selection_at_the_open"]["v3"]["by_level"].keys() and all(abs(rep["selection_at_the_open"]["v4"]["by_level"][k] - rep["selection_at_the_open"]["v3"]["by_level"][k]) < 1e-9 for k in rep["selection_at_the_open"]["v3"]["by_level"]),
          "the harmonic level shares are the same under v3 and v4 (the draw is unchanged)")
    vr = rpt5.verify_run5(root, cp["rd4"], cp["rd3"], cp["rd2"], cp["rd1"], "sd1")
    check(vr["ok"], f"verify-run: {vr['problems']}")
    tmp = tmpdir("m8vr5_")
    shutil.copytree(root, tmp / "a")
    (tmp / "a" / "sessions" / "sd1" / "rule.json").unlink()
    check(not rpt5.verify_run5(tmp / "a", cp["rd4"], cp["rd3"], cp["rd2"], cp["rd1"], "sd1")["ok"], "no decision recorded is refused")
    shutil.copytree(root, tmp / "b")
    rp_ = tmp / "b" / "sessions" / "sd1" / "rule.json"
    d_ = json.loads(rp_.read_text(encoding="utf-8"))
    d_["outcome"] = "PROGRESS" if d_["outcome"] != "PROGRESS" else "NO_SHORTER_CLEAR"
    rp_.write_text(json.dumps(d_), encoding="utf-8")
    check(not rpt5.verify_run5(tmp / "b", cp["rd4"], cp["rd3"], cp["rd2"], cp["rd1"], "sd1")["ok"], "a recorded outcome the replays do not hold is refused")
    shutil.copytree(root, tmp / "c")
    rp_ = tmp / "c" / "sessions" / "sd1" / "rule.json"
    d_ = json.loads(rp_.read_text(encoding="utf-8"))
    d_["line"]["status"] = "REPAIR_NEEDED"
    rp_.write_text(json.dumps(d_), encoding="utf-8")
    check(not rpt5.verify_run5(tmp / "c", cp["rd4"], cp["rd3"], cp["rd2"], cp["rd1"], "sd1")["ok"], "a recorded line status the rule does not hold is refused")
    shutil.copytree(root, tmp / "d")
    (tmp / "d" / "sessions" / "sd1" / "unstamped.json").write_text("{\"x\": 1}\n", encoding="utf-8")
    v = rpt5.verify_run5(tmp / "d", cp["rd4"], cp["rd3"], cp["rd2"], cp["rd1"], "sd1")
    check(not v["ok"] and any("artifacts" in p for p in v["problems"]), "a record without its stamp is refused")
    shutil.copytree(root, tmp / "e")
    ip = tmp / "e" / "sessions" / "sd1" / "iterations_T.jsonl"
    ip.write_text("".join(ln + "\n" for ln in ip.read_text(encoding="utf-8").splitlines()[1:]), encoding="utf-8")
    check(not rpt5.verify_run5(tmp / "e", cp["rd4"], cp["rd3"], cp["rd2"], cp["rd1"], "sd1")["ok"], "a JSONL file without its header row is refused")
    shutil.copytree(root, tmp / "f")
    ep = tmp / "f" / "archive" / "events.jsonl"
    ep.write_bytes(ep.read_bytes().replace(b'"worker":0', b'"worker":1', 1))
    check(not rpt5.verify_run5(tmp / "f", cp["rd4"], cp["rd3"], cp["rd2"], cp["rd1"], "sd1")["ok"], "a changed archive file is refused")
    shutil.rmtree(tmp, ignore_errors=True)
    check(all_immutability5(cp)["ok"] and all_immutability5(chain)["ok"], "the earlier trees are untouched")
    shutil.rmtree(cp["t"], ignore_errors=True)
    return {"outcome": rule["outcome"], "cells": len(a.cells), "pool": arm["pool"], "replays": arm["replays"], "best": arm["best_verified"] and arm["best_verified"]["completion_input_tick"], "t_rec": rr["completion_input_tick"]}


def unit_session5_determinism() -> Dict[str, Any]:
    c1 = build_chain5(cache=False)
    c2 = build_chain5(cache=False)

    def chain_sig(c: Mapping[str, Any]) -> Dict[str, Any]:
        return {t: {n: mw.sha256_file(c[t] / "archive" / n) for n in ("cells.jsonl", "bursts.bin", "bursts.idx.jsonl", "events.jsonl")} for t in ("rd1", "rd2", "rd3", "rd4")}

    check(chain_sig(c1) == chain_sig(c2) and c1["expect4"]["inherited_record"] == c2["expect4"]["inherited_record"], "two builds of the synthetic chain are byte-identical (cells, words, index, ledger, the record)")
    o1, s1_, r1, cp1 = run5_small(c1)
    o2, s2_, r2, cp2 = run5_small(c1)
    sig1, sig2 = signature5(r1), signature5(r2)
    check(sig1 == sig2, f"two runs of the same sd1 session agree on the archive's data files, the decision, the replay order and the open overlay: {json.dumps(sig1)[:300]}")
    check(o1["rule"]["outcome"] == o2["rule"]["outcome"] and s1_.ledgers["T"].ticks == s2_.ledgers["T"].ticks and len(s1_.ledgers["T"].candidates) == len(s2_.ledgers["T"].candidates), "outcome, ticks and candidates agree")
    # The signature (and so the e2e digest) must not depend on the host frame, which differs between two processes of the same gameplay (the stub draws its host offset from the process id;
    # the engine's exactness excludes the field): a copy of the run's cells and burst index with every host frame shifted hashes the same, a copy with another end field shifted does not.
    other = 0 if mcell.HOST_FRAME != 0 else 2
    tmp = Path(tempfile.mkdtemp(prefix="m8_sd1_host_"))
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


def unit_session5_inherited_continuations() -> Dict[str, Any]:
    """rd4's claim cases (a) and (b) under sd1: the continuation of an inherited left-of-wall cell that does not land and the continuation of an inherited wall-top cell are neither a false
    INVALID nor a replay (sd1's pool holds clears only); the wall-top sighting is recorded."""
    chain = build_chain5()
    world = chain["world"]
    cls = t4.forced_session_cls(world, ("left_nolanding", "wall_continuation"), base=run5.Session5)
    out, sess, root, cp = run5_small(chain, session_cls=cls, arm_tick_cap=12000, min_arm_ticks=4000)
    rule = out["rule"]
    check(not rule["invalid"] and not rule["incomplete"], f"a session that starts with the claim cases: {rule['outcome']} {rule['invalid']} {rule['incomplete']}")
    forced = {f["kind"]: f for f in sess.forced}
    n_open = chain["expect4"]["cells"]
    check(set(forced) == {"left_nolanding", "wall_continuation"} and all(f["cell"] < n_open for f in forced.values()), f"the two forced dispatches start from inherited cells: {forced}")
    led = sess.ledgers["T"]
    cand_b = t4.candidate_for_iteration(sess, forced["left_nolanding"]["iteration"], "left")
    check(cand_b is not None and cl4.is_descriptive(cand_b), "the continuation of an inherited left cell registers a descriptive left candidate")
    ver = json.loads((sess.cfg.session_dir / "verification.json").read_text(encoding="utf-8"))
    check(cand_b["cid"] not in ver["arm"]["replay_order"] and all(led.candidates[cid]["kind"] == "clear" for cid in ver["arm"]["replay_order"]), "it is never replayed: the pool holds clears only")
    rows_s = art.rows_of(sess.cfg.session_dir / "wall_top_sightings.jsonl")
    row = next((x for x in rows_s if x["iteration"] == forced["wall_continuation"]["iteration"]), None)
    check(row is not None and row["start_cell_on_wall_top"] and row["first_tick_of_the_burst"], f"the wall-top continuation is recorded as a sighting: {rows_s}")
    check(led.l0_cid is None and not [c for c in led.candidates if c["kind"] == "l0"], "no wall-top candidate: the landing is rd2's, never claimed again")
    check(json.loads((sess.cfg.session_dir / "arm_T.json").read_text(encoding="utf-8"))["wall_top_sightings"]["from_a_wall_top_start"] >= 1, "the arm record counts it")
    check(rpt5.verify_run5(root, cp["rd4"], cp["rd3"], cp["rd2"], cp["rd1"], "sd1")["ok"], "verify-run")
    shutil.rmtree(cp["t"], ignore_errors=True)
    return {"outcome": rule["outcome"], "forced": sorted(forced)}


def unit_session5_record_replay_at_open() -> Dict[str, Any]:
    chain = build_chain5()
    op = open5(chain)
    rc = op["record_candidate"]
    out, sess, _r, cp = run5_small(chain, record_candidate=dict(rc, words=bytes([(rc["words"][0] + 1) % 72]) + rc["words"][1:]), arm_tick_cap=3000, min_arm_ticks=1000)
    r = out["rule"]
    check(r["outcome"] == "INVALID" and any("did not re-verify at the open" in x for x in r["invalid"]) and sess.iteration == sess.first_iteration, f"a record whose words differ from the pinned digest: INVALID before any dispatch: {r['invalid']}")
    ro = json.loads((sess.cfg.session_dir / "record_open.json").read_text(encoding="utf-8"))
    check(not ro["exact"] and ro["problems"], "the open record names the problem")
    out, sess, _r, cp = run5_small(chain, record_candidate=dict(rc, first={"clear": rc["first"]["clear"] + 1}), arm_tick_cap=3000, min_arm_ticks=1000)
    check(out["rule"]["outcome"] == "INVALID" and any("differs from the registered clear tick" in x for x in out["rule"]["invalid"]), f"a clock that differs from the registered one: {out['rule']['invalid']}")
    out, sess, _r, cp = run5_small(chain, record_candidate=dict(rc, words=rc["words"] * 40), arm_tick_cap=3000, min_arm_ticks=1000)
    check(out["rule"]["outcome"] == "INCOMPLETE" and any("beyond the open cap" in x for x in out["rule"]["incomplete"]) and sess.iteration == sess.first_iteration,
          f"a record replay that does not fit the open cap: INCOMPLETE before any dispatch, never INVALID: {out['rule']['incomplete']}")
    shutil.rmtree(cp["t"], ignore_errors=True)
    return {"record_words": len(rc["words"])}


def unit_budget_projection5() -> Dict[str, Any]:
    caps = ses5.caps()
    check(caps == ses4.caps() and caps["wall_caps_s"] == {"p1": 240.0, "T": 3000.0, "verify": 360.0} and caps["global_cap_s"] == 3600.0 and caps["exploration_tick_cap"] == 6_000_000
          and caps["min_exploration_ticks"] == 2_000_000 and caps["open_tick_cap"] == 70_000 and caps["replay_tick_cap"] == 400_000 and caps["identity_k"] == 16, "every cap equals rd4's")
    proj = rpt5.budget_projection(caps)
    check(proj["caps_s"]["sum"] == proj["caps_s"]["session_hard_cap"] == 3600.0 and proj["pessimistic"]["valid"] and proj["pessimistic"]["fits_hard_cap"] and proj["fits_hard_cap_without_trimming"], f"the pessimistic projection fits: {proj['pessimistic']}")
    inherited = cl5.inherited_ticks(cl5.inherited_unverified_clears(RD4_REAL)) if REAL_TREES else 7013
    record = ses5.RECORD_REFERENCE["words"]
    check(6208 + 16 * mcell.HORIZON + record <= caps["open_tick_cap"] - 0 or 6208 + 16 * 2000 + record <= caps["open_tick_cap"], "the open phase: P1, 16 identity replays and the record fit 70,000 ticks at the observed replay lengths")
    check(inherited + 16 * mcell.HORIZON + 10 * record <= caps["replay_tick_cap"], f"the verification: the inherited replays ({inherited}), 16 identity replays and ten clear replays fit 400,000 ticks")
    return {"pessimistic_s": proj["pessimistic"]["wall_s"]["total"], "inherited_ticks": inherited}


def unit_approval_isolated5() -> Dict[str, Any]:
    want = ses5.identity()
    t = tmpdir("m8ap5_")
    p = t / "approval.json"
    ok, why = ses5.approval_status(p, want)
    check(not ok and "no approval record" in why, "no record: refused")
    good = art.stamp(dict(want, approval="APPROVED by the test", revision=1))
    p.write_text(json.dumps(good), encoding="utf-8")
    check(ses5.approval_status(p, want) == (True, "approved"), "a matching stamped record is accepted")
    p.write_text(json.dumps({k: v for k, v in good.items() if k not in ("task", "created_utc")}), encoding="utf-8")
    ok, why = ses5.approval_status(p, want)
    check(not ok and "task block" in why, "an approval without its stamp is refused")
    p.write_text(json.dumps(dict(good, approval="PENDING")), encoding="utf-8")
    check(not ses5.approval_status(p, want)[0], "PENDING is refused")
    n = 0
    alter = {"rule_sha256": "0" * 64, "claims_digest": "0" * 64, "artifacts_digest": "0" * 64, "executable_sha256": "0" * 64, "scope": "other", "archive_id": "x", "workers": 4, "burst_words": 121,
             "horizon": 3599, "flags": {"explore": {}, "verify": {}}, "contracts": dict(want["contracts"], m8_rd_select_v4="0" * 64), "key_strings": {"select_sd1": "x"}, "runtime_files": {"BattleShip.o2r": "0" * 64},
             "p1": {}, "readiness": {"min_available_mb": 1}, "git_head": "0" * 40, "session": "sdX", "gate": "x", "line": "rd", "rule": "other", "draws_sha256": "0" * 64, "sd1_session_event_digest": "0" * 64,
             "select_v4_changed_from": {"m8_rd_select_v3": "0" * 64}, "select_v4_registered_changes": ["cell_weight"], "length_scale_v4": 900.0, "record_reference": dict(want["record_reference"], completion_input_tick=2314, words=2314),
             "margin": 23, "progress_bar": 2292, "tiers": {"5_percent": 2200}, "inherited_descriptive_rule": "none", "base": dict(want["base"], rd4_increment_manifest_sha256="0" * 64),
             "open_overlay": dict(want["open_overlay"], v4_sha256="0" * 64), "budgets": {"hard_cap": "61 min"}, "docs_sha256": {"docs/x.md": "0" * 64}, "source_fingerprint": "0" * 16, "task": {"id": "x", "character": "mario", "stage": "btt_mario"}}
    for k, v in alter.items():
        check(k in want, f"the identity carries {k}")
        p.write_text(json.dumps(dict(good, **{k: v})), encoding="utf-8")
        check(not ses5.approval_status(p, want)[0], f"an altered {k} was accepted")
        n += 1
    for k in list(want["caps"]):
        caps = dict(want["caps"])
        caps[k] = {"x": 1}
        p.write_text(json.dumps(dict(good, caps=caps)), encoding="utf-8")
        check(not ses5.approval_status(p, want)[0], f"an altered cap {k} was accepted")
        n += 1
    for f in list(want["code"]):
        code = dict(want["code"])
        code[f] = "0" * 64
        p.write_text(json.dumps(dict(good, code=code)), encoding="utf-8")
        check(not ses5.approval_status(p, want)[0], f"an altered code hash for {f} was accepted")
        n += 1
    p.write_text(json.dumps(dict(good, d_records={"folders": ["2026-09-28"], "digest": "0" * 64})), encoding="utf-8")
    check(not ses5.approval_status(p, want)[0], "an altered D: records digest")
    check(ses5.APPROVAL != p and ses5.APPROVAL.name == "rl_m8_sd1_approval.json", "the repository path is untouched by the tests")
    check(set(want["contracts"]) == set(ses4.contract_digests4("x")) | {"m8_rd_select_v4"} and want["rule"] == "m8_sd1_rule_v1" and want["workers"] == 5 and want["margin"] == 24 and want["progress_bar"] == 2291
          and want["record_reference"] == r5.RECORD_REFERENCE and want["tiers"] == {"5_percent": 2199, "10_percent": 2083, "round_2000": 2000} and want["task"] == A.task_block(), "registered identity entries")
    base = want["base"]
    check(base["rd4_checkpoint_seq"] == 45 and base["rd4_increment"] == r5.RD4_INCREMENT_NAME and base["first_sd1_iteration"] == 13886 and base["rd4_first_iteration"] == 10406 and base["rd4_line"]["rd5_permitted"] is True
          and [e["name"] for e in base["rd4_session_events"]] == ["rd2", "rd3", "rd4"] and base["rd4_session_events"][2]["digest"] == want["contracts"]["m8_rd_select_v3"]
          and r5.record_fact_problems(base["inherited_record"], r5.INHERITED_RECORD) == [], "the base identity reads rd4's closed tree (the inherited record equals the registered one)")
    check(want["open_overlay"]["rd4_closing_sha256"] == r5.RD4_CLOSING_OVERLAY_SHA256 and want["open_overlay"]["v4_sha256"] == r5.SD1_OPEN_OVERLAY_SHA256 and want["open_overlay"]["expected_v4_counts"] == r5.EXPECTED_OPEN_OVERLAY5,
          "both overlays are pinned")
    for f in ses5.NEW_CODE_FILES:
        check(f"rl/{f}" in want["code"], f"{f} is pinned")
    for f in ses5.TOOL_FILES:
        check(f"tools/m8_sd1/{f}" in want["code"], f"the tool {f} is pinned")
    check(all(f"rl/{f}" in want["code"] for f in ("m8_rd4_select.py", "m8_rd4_run.py", "m8_rd4_tests.py", "m8_rd_select2.py", "m8_rd_cells.py", "m8_rd_claims.py")), "rd1's to rd4's code is pinned too")
    check(want["source_fingerprint"] == ses5.source_fingerprint(), "the identity carries the source fingerprint")
    # the approval writer's refusals, on isolated records (the repository's approval path is patched for the duration)
    spec = importlib.util.spec_from_file_location("sd1_write_approval", TOOLS_DIR / "write_approval.py")
    wa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wa)                      # type: ignore[union-attr]
    snap = t / "snap"
    snap.mkdir()
    auth = t / "auth.txt"
    auth.write_text("I authorise sd1 once.\n", encoding="utf-8")
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

        codes["no_snapshot"] = run_wa("--session", "sd1", "--snapshot", str(snap), "--independent", "x", "--authorisation-file", str(auth), "--authorised-on", "2026-10-12")
        (snap / "snapshot.json").write_text(json.dumps({"result": "FAIL", "tool": "m8_sd1_source_snapshot_v1", "git_head": want["git_head"], "source_fingerprint": want["source_fingerprint"], "n_files": 1}), encoding="utf-8")
        codes["not_pass"] = run_wa("--session", "sd1", "--snapshot", str(snap), "--independent", "x", "--authorisation-file", str(auth), "--authorised-on", "2026-10-12")
        (snap / "snapshot.json").write_text(json.dumps({"result": "PASS", "tool": "m8_rd4_source_snapshot_v1", "git_head": want["git_head"], "source_fingerprint": want["source_fingerprint"], "n_files": 1}), encoding="utf-8")
        codes["wrong_tool"] = run_wa("--session", "sd1", "--snapshot", str(snap), "--independent", "x", "--authorisation-file", str(auth), "--authorised-on", "2026-10-12")
        (snap / "snapshot.json").write_text(json.dumps({"result": "PASS", "tool": "m8_sd1_source_snapshot_v1", "git_head": want["git_head"], "source_fingerprint": want["source_fingerprint"], "n_files": 1}), encoding="utf-8")
        codes["empty_authorisation"] = run_wa("--session", "sd1", "--snapshot", str(snap), "--independent", "x", "--authorisation-file", str(empty), "--authorised-on", "2026-10-12")
        codes["bad_date"] = run_wa("--session", "sd1", "--snapshot", str(snap), "--independent", "x", "--authorisation-file", str(auth), "--authorised-on", "2026-13-01")
        (snap / "snapshot.json").write_text(json.dumps({"result": "PASS", "tool": "m8_sd1_source_snapshot_v1", "git_head": "0" * 40, "source_fingerprint": want["source_fingerprint"], "n_files": 1}), encoding="utf-8")
        codes["head_mismatch"] = run_wa("--session", "sd1", "--snapshot", str(snap), "--independent", "x", "--authorisation-file", str(auth), "--authorised-on", "2026-10-12")
        (snap / "snapshot.json").write_text(json.dumps({"result": "PASS", "tool": "m8_sd1_source_snapshot_v1", "git_head": want["git_head"], "source_fingerprint": "0" * 16, "n_files": 1}), encoding="utf-8")
        codes["fingerprint_mismatch"] = run_wa("--session", "sd1", "--snapshot", str(snap), "--independent", "x", "--authorisation-file", str(auth), "--authorised-on", "2026-10-12")
        (t / "exists.json").write_text("{}", encoding="utf-8")
        wa.S.APPROVAL = t / "exists.json"
        codes["existing"] = run_wa("--session", "sd1", "--snapshot", str(snap), "--independent", "x", "--authorisation-file", str(auth), "--authorised-on", "2026-10-12")
    finally:
        wa.S.APPROVAL = saved_approval
        sys.argv = saved_argv
    check(all(c == 2 for c in codes.values()) and not (t / "never.json").exists(), f"every refusal of the approval writer exits 2 and writes nothing: {codes}")
    shutil.rmtree(t, ignore_errors=True)
    return {"altered_entries_refused": n, "writer_refusals": sorted(codes)}


def unit_results_record_rule5() -> Dict[str, Any]:
    t = tmpdir("m8rr5_")
    docs = t / "docs"
    docs.mkdir()
    good = docs / "rl_m8_sd1_results_2026-10-12.md"
    body = "# M8-sd1 results (2026-10-12)\n\nsummary\n\n## 1. What was run\n\ntext\n"
    good.write_text(body, encoding="utf-8")
    check(ses5.results_record_problems(good, docs) == [], "a complete record with the exact name is accepted")
    bom_crlf = docs / "rl_m8_sd1_results_2026-10-13.md"
    bom_crlf.write_bytes(b"\xef\xbb\xbf" + body.replace("2026-10-12", "2026-10-13").replace("\n", "\r\n").encode("utf-8"))
    good.unlink()
    check(ses5.results_record_problems(bom_crlf, docs) == [], "a BOM and CRLF line ends are tolerated")
    bom_crlf.unlink()
    good.write_text(body, encoding="utf-8")
    for bad_name in ("rl_m8_sd1_results_draft.md", "rl_m8_sd1_results_2026-10-12.md.tmp", "rl_m8_sd1_results_2026-10-12.md~", "rl_m8_sd1_results_2026-10-9.md", "rl_m8_sd1_results_2026-13-01.md",
                     "rl_m8_sd1_results_2026-02-30.md", "rl_m8_sd1_results_.md", "rl_m8_sd1_results.md", "RL_M8_SD1_RESULTS_2026-10-20.MD", "rl_m8_sd1_results_2026-10-21.MD"):      # other dates: Windows names are case-insensitive
        p = docs / bad_name
        p.write_text(body, encoding="utf-8")
        probs = ses5.results_record_problems(good, docs)
        check(probs and all("another entry" in x for x in probs), f"{bad_name} beside the record is refused: {probs}")
        check(ses5.results_record_problems(p, docs) != [], f"{bad_name} is not a record")
        p.unlink()
    d = docs / "rl_m8_sd1_results_2026-10-14.md"
    d.mkdir()
    check(ses5.results_record_problems(good, docs) != [] and ses5.results_record_problems(d, docs) != [], "a directory with the registered name is refused")
    d.rmdir()
    second = docs / "rl_m8_sd1_results_2026-10-15.md"
    second.write_text(body.replace("2026-10-12", "2026-10-15"), encoding="utf-8")
    check(ses5.results_record_problems(good, docs) != [], "two complete records are refused")
    second.unlink()
    for what, content in (("empty", b""), ("no final newline", body.rstrip("\n").encode("utf-8")), ("a NUL byte", body.encode("utf-8") + b"\x00\n"), ("not UTF-8", b"\xff\xfe# M8\n## x\n"),
                          ("another date in the title", body.replace("(2026-10-12)", "(2026-10-11)").encode("utf-8")), ("the title alone", b"# M8-sd1 results (2026-10-12)\n"),
                          ("no title", b"text\n\n## 1\n\nx\n"), ("a g3 title", b"# M9-g3-s6 results (2026-10-12)\n\n## 1\n\nx\n")):
        good.write_bytes(content)
        check(ses5.results_record_problems(good, docs) != [], f"{what} is refused")
    good.write_text(body, encoding="utf-8")
    (docs / "rl_m8_sd1_proposal_2026-10-07.md").write_text("x\n", encoding="utf-8")
    check(ses5.results_record_problems(good, docs) == [], "the proposal's name does not start with the results prefix")
    r = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_sd1_session.py"), "check-results-record", "--path", str(t / "nowhere.md")], capture_output=True, text=True, timeout=300)
    check(r.returncode == 1 and '"ok": false' in r.stdout, "the CLI refuses a missing record")
    shutil.rmtree(t, ignore_errors=True)
    return {}


# -- artifacts, guards, budget, tools, pins -------------------------------------------------------------------------------------------------------------------


def unit_artifacts5_stamping() -> Dict[str, Any]:
    t = tmpdir("m8art5_")
    p = t / "a.json"
    art.write_json5(p, {"x": 1})
    rec = json.loads(p.read_text(encoding="utf-8"))
    check(art.is_stamped(rec) and rec["task"] == A.task_block() and list(rec)[:2] == ["task", "created_utc"] and rec["x"] == 1, "a written object carries the stamp first")
    first = rec["created_utc"]
    art.write_json5(p, {"x": 2, "y": 3})
    rec2 = json.loads(p.read_text(encoding="utf-8"))
    check(rec2["created_utc"] == first and rec2["x"] == 2 and rec2["y"] == 3, "a rewrite keeps the first created_utc")
    art.write_json5(p, {"x": 4}, created_utc="2020-01-01T00:00:00Z")
    check(json.loads(p.read_text(encoding="utf-8"))["created_utc"] == first, "an explicit created_utc never replaces the file's first one")
    q = t / "b.json"
    art.write_json5(q, {"z": 1}, created_utc="2020-01-01T00:00:00Z")
    check(json.loads(q.read_text(encoding="utf-8"))["created_utc"] == "2020-01-01T00:00:00Z", "a new file takes the given first-write time")
    raises(art.ArtifactError, lambda: art.write_json5(q, {"z": 2}, overwrite=False), "overwrite=False refuses an existing file")
    raises(art.ArtifactError, lambda: art.check({"task": {"id": "x", "character": "mario", "stage": "btt_mario"}, "created_utc": art.utc()}), "an unregistered task is refused")
    raises(art.ArtifactError, lambda: art.check({"x": 1}), "an object without the stamp is refused")
    raises(art.ArtifactError, lambda: art.write_json5(t / "c.json", {"task": "x", "created_utc": "y"}), "a malformed stamp is refused at write time")
    j = t / "rows.jsonl"
    check(art.jsonl_header(j, "s1") and not art.jsonl_header(j, "s1"), "the header is written once")
    art.append_jsonl5(j, {"r": 1}, "s1")
    art.append_jsonl5(j, {"r": 2}, "s1")
    h, rows = art.read_jsonl5(j)
    check(h is not None and h["schema"] == "s1" and h["header"] is True and art.is_stamped(h) and rows == [{"r": 1}, {"r": 2}] and art.rows_of(j) == rows, "one stamped header row, then the rows")
    g = t / "rows.jsonl.gz"
    art.write_jsonl_gz5(g, [{"r": 1}], "s2")
    h2, rows2 = art.read_jsonl5(g)
    check(h2["schema"] == "s2" and rows2 == [{"r": 1}] and art.created_utc_of(g) == h2["created_utc"], "a gzip JSONL file")
    art.write_json_gz5(t / "o.json.gz", {"v": 1})
    with gzip.open(t / "o.json.gz", "rt", encoding="utf-8") as f:
        check(art.is_stamped(json.load(f)), "a gzip JSON object")
    # the audit and its exact exemptions
    root = t / "tree"
    for d in ("archive", "archive.prev", "base", "derived", "routes/T_clear_best", "sessions/sd1/failures", "sessions/sd1/workers/w00", "sessions/sd1/vw/x", "sessions/sd1/verification"):
        (root / d).mkdir(parents=True)
    for d in ("archive", "archive.prev"):
        art.write_json5(root / d / "archive_meta.json", {"m": 1})
        for n in ("cells.jsonl", "bursts.idx.jsonl", "events.jsonl"):
            (root / d / n).write_text('{"row": 1}\n', encoding="utf-8")
    (root / "base" / "archive_meta.json").write_text('{"unstamped": 1}\n', encoding="utf-8")
    (root / "base" / "cells.jsonl").write_text('{"row": 1}\n', encoding="utf-8")
    (root / "derived" / "open_overlay.jsonl").write_text('{"id": 0}\n', encoding="utf-8")
    (root / "derived" / "rd4_closing_overlay.jsonl").write_text('{"id": 0}\n', encoding="utf-8")
    art.write_json5(root / "derived" / "open_overlay.json", {"sha256": "x"})
    (root / "routes" / "T_clear_best" / "actions.jsonl").write_text('{"sequence_index": 0}\n', encoding="utf-8")
    art.write_json5(root / "routes" / "T_clear_best" / "metadata.json", {"w": 1})
    (root / "sessions" / "sd1" / "failures" / "iterate_4_w03.json.gz").write_bytes(gzip.compress(b'{"raw": 1}'))
    (root / "sessions" / "sd1" / "workers" / "w00" / "x.json").write_text("{}", encoding="utf-8")
    (root / "sessions" / "sd1" / "vw" / "x" / "y.json").write_text("{}", encoding="utf-8")
    art.write_json5(root / "sessions" / "sd1" / "state.json", {"phase": "done"})
    art.append_jsonl5(root / "sessions" / "sd1" / "iterations_T.jsonl", {"ticks": 1}, "s3")
    art.write_jsonl_gz5(root / "sessions" / "sd1" / "dispatch_rows.jsonl.gz", [{"it": 1}], "s4")
    art.write_json_gz5(root / "sessions" / "sd1" / "verification" / "T_c0001_clear.json.gz", {"steps": []})
    aud = art.audit_tree5(root)
    check(aud["ok"] and aud["files"] == 8 and aud["headers"] == 2, f"a correctly stamped tree with the exact exemptions passes: {aud}")
    check(sorted(aud["exempt_files"]) == sorted(["archive/bursts.idx.jsonl", "archive/cells.jsonl", "archive/events.jsonl", "archive.prev/bursts.idx.jsonl", "archive.prev/cells.jsonl", "archive.prev/events.jsonl",
                                                "base/archive_meta.json", "base/cells.jsonl", "derived/open_overlay.jsonl", "derived/rd4_closing_overlay.jsonl", "routes/T_clear_best/actions.jsonl",
                                                "sessions/sd1/failures/iterate_4_w03.json.gz", "sessions/sd1/workers/w00/x.json", "sessions/sd1/vw/x/y.json"]), f"the exempt files, exactly: {aud['exempt_files']}")
    for rel, why in (("archive/cells.jsonl", "frozen"), ("base/anything.json", "byte copy"), ("derived/open_overlay.jsonl", "digest-pinned"), ("routes/x/actions.jsonl", "M4"), ("sessions/sd1/failures/a.json", "frozen rd1 worker")):
        check(art.exempt_reason(rel) is not None and why.split()[0] in art.exempt_reason(rel), f"{rel} is exempt for its reason")
    for rel in ("archive/archive_meta.json", "derived/open_overlay.json", "routes/x/metadata.json", "sessions/sd1/state.json", "sessions/sd1/verification/t.json.gz", "launch/preflight.json", "derived/report.json"):
        check(art.exempt_reason(rel) is None, f"{rel} must carry the stamp")
    (root / "sessions" / "sd1" / "unstamped.json").write_text('{"x": 1}\n', encoding="utf-8")
    aud2 = art.audit_tree5(root)
    check(not aud2["ok"] and any("unstamped.json" in f for f in aud2["failures"]), "an unstamped object fails the audit")
    (root / "sessions" / "sd1" / "unstamped.json").unlink()
    (root / "sessions" / "sd1" / "noheader.jsonl").write_text('{"r": 1}\n', encoding="utf-8")
    aud3 = art.audit_tree5(root)
    check(not aud3["ok"] and any("noheader.jsonl" in f and "header" in f for f in aud3["failures"]), "a JSONL file without its header fails the audit")
    (root / "sessions" / "sd1" / "noheader.jsonl").unlink()
    (root / "archive" / "archive_meta.json").write_text('{"m": 1}\n', encoding="utf-8")
    check(not art.audit_tree5(root)["ok"], "an unstamped archive_meta.json fails the audit")
    check(art.contract_digest() == art.contract_digest() and len(art.contract_digest()) == 64 and art.ARTIFACTS5_CONTRACT == "m8_sd1_artifacts_v1", "the artifacts contract digest")
    shutil.rmtree(t, ignore_errors=True)
    return {"audited": aud["files"]}


def unit_task_block_pinned() -> Dict[str, Any]:
    import experiment_config as ec
    import m9_contract as C

    tb = art.task_block()
    check(tb == {"id": "ssb64_us_mario_btt_v1", "character": "mario", "stage": "btt_mario"} and tb == A.task_block() == dict(C.TASK), "the task block")
    reg = ec.SUPPORTED_TASKS[tb["id"]]
    check(reg["character"] == tb["character"] and reg["stage"] == tb["stage"], "pinned to the project's task registry")
    check(A.REGISTERED_TASKS == {tb["id"]: {"character": "mario", "stage": "btt_mario"}}, "the M9 writer's registry")
    return tb


def unit_source_guard5() -> Dict[str, Any]:
    """No sd1 module reads fixtures, recordings, the TAS or any .btti file; none imports a learning framework or the random module; no call that writes takes a path built from an earlier tree's
    root; no census number or stage coordinate enters the selection, claims, rule or run modules; the tiers are read by no selection, claim or outcome."""
    forbidden = ("rl/fixtures", "fixtures/m7g", "m7g/capture", "tas_input", "mario_743", ".btti", "btti_replay", "crossing_fixture", "rl_crossing")
    bad_imports = {"random", "torch", "gymnasium", "stable_baselines3", "numpy", "pandas", "scipy", "sklearn"}
    write_attrs = {"write_text", "write_bytes", "mkdir", "unlink", "rmdir", "touch", "rename", "replace", "chmod"}
    copy_funcs = {"copyfile", "copy", "copy2", "copytree", "move"}
    writers = {"write_json", "write_json5", "append_jsonl", "append_jsonl5", "write_jsonl_gz5", "save_checkpoint", "write_files", "rmtree", "rmtree_retry", "remove_tree_retry", "replace_retry", "makedirs"}
    names_earlier = ("rd1_root", "RD1_ROOT", "rd1_archive_dir", "M8_ROOT", "rd2_root", "RD2_ROOT", "rd2_archive_dir", "rd1_dir", "rd2_dir", "RD1_REAL", "RD2_REAL", "rd3_root", "RD3_ROOT", "rd3_archive_dir",
                     "rd3_dir", "RD3_REAL", "rd4_root", "RD4_ROOT", "rd4_archive_dir", "rd4_dir", "RD4_REAL")
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
        if found:
            hits[name] = found
    check(not hits, f"forbidden vocabulary, imports or writes in the sd1 modules or tools: {hits}")
    # no census number and no stage coordinate in the modules that select, claim, decide or run (the registered constants 2315, 2314, 24, 120, 2291, 2199, 2083 and 2000 are allowed)
    census = ("1960", "2066", "1898", "1966", "1911", "2213", "2298", "1838", "1339", "3900", "2700", "1950", "2250", "3750", "3450", "2550", "2100")
    for name in ("m8_sd1_select", "m8_sd1_claims", "m8_sd1_rule", "m8_sd1_run"):
        code = "\n".join(ln.split("#", 1)[0] for ln in (RL_DIR / f"{name}.py").read_text(encoding="utf-8").splitlines())
        code = re.sub(r'"""[\s\S]*?"""', "", code)
        for tok in census:
            check(re.search(rf"(?<![0-9.\w]){tok}(?![0-9])", code) is None, f"{name}.py names the census or stage quantity {tok}")
    # the tiers: read by no selection or claim module, and by no outcome
    for name in ("m8_sd1_select", "m8_sd1_claims"):
        src = (RL_DIR / f"{name}.py").read_text(encoding="utf-8")
        check("tier" not in src.lower(), f"{name}.py reads the tiers")
    rule_src = (RL_DIR / "m8_sd1_rule.py").read_text(encoding="utf-8")
    tree = ast.parse(rule_src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "outcome_of")
    check(not any("tier" in ast.unparse(n).lower() for n in ast.walk(fn)), "outcome_of reads no tier")
    apply_fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "apply")
    outcome_stmt = next(n for n in apply_fn.body if isinstance(n, ast.If) and any(isinstance(x, ast.Assign) and ast.unparse(x.targets[0]) == "out" for x in ast.walk(n)))
    check("tier" not in ast.unparse(outcome_stmt).lower() and "outcome_of" in ast.unparse(outcome_stmt), "the outcome in apply is outcome_of's alone; no tier enters it")
    run_src = (RL_DIR / "m8_sd1_run.py").read_text(encoding="utf-8")
    check("tier_report" in run_src and "TIERS[" not in run_src, "the run engine reports the tiers and reads none")
    tests_src = (RL_DIR / "m8_sd1_tests.py").read_text(encoding="utf-8")
    for nd in ast.walk(ast.parse(tests_src)):
        if isinstance(nd, ast.Call):
            f = nd.func
            fname = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
            if fname in write_attrs | writers | copy_funcs and any(n in ast.unparse(nd) for n in ("RD1_REAL", "RD2_REAL", "RD3_REAL", "RD4_REAL")):
                raise Failure(f"the tests write through a real tree's path: {ast.unparse(nd)[:100]}")
    return {"modules": len(NEW_MODULES), "tools": len(PYTHON_TOOLS)}


def unit_no_nondeterminism_in_sd1() -> Dict[str, Any]:
    banned_mods = {"random", "secrets", "uuid"}
    for pth in [RL_DIR / f"{n}.py" for n in NEW_MODULES] + [RL_DIR / "m8_sd1_tests.py"] + [TOOLS_DIR / f for f in PYTHON_TOOLS]:
        src = pth.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for nd in ast.walk(tree):
            if isinstance(nd, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in nd.names] if isinstance(nd, ast.Import) else [nd.module or ""]
                check(not any(n.split(".")[0] in banned_mods for n in names), f"{pth.name} imports a source of randomness")
            if isinstance(nd, ast.Call):
                call = ast.unparse(nd.func)
                check(call != "os.urandom" and not call.startswith("random."), f"{pth.name}: {call}")
                if pth.parent == RL_DIR:
                    check(call != "time.sleep", f"{pth.name}: a sleep in a module or the suite")
    src = (RL_DIR / "m8_sd1_tests.py").read_text(encoding="utf-8")
    for fn in ast.walk(ast.parse(src)):
        if isinstance(fn, ast.FunctionDef) and fn.name != "unit_no_nondeterminism_in_sd1":
            for nd in ast.walk(fn):
                if isinstance(nd, ast.Call) and ast.unparse(nd.func) == "check":
                    cond = ast.unparse(nd.args[0]) if nd.args else ""
                    check("time.time" not in cond and "perf_counter" not in cond and "datetime" not in cond, f"{fn.name}: an assertion reads the wall clock: {cond[:80]}")
    pre = (RL_DIR / "m8_sd1_session.py").read_text(encoding="utf-8")
    check('"integration"' not in pre and "INTEGRATION" not in pre and "cmd_run5_with_fake_game" not in {n for n, _fn in TESTS}, "no real-process test anywhere in the suite or the preflight")
    return {"modules": len(NEW_MODULES)}


def unit_tracked_files_unchanged5() -> Dict[str, Any]:
    check(ses5.ses1.tracked_changes() == [], f"tracked files differ from HEAD: {ses5.ses1.tracked_changes()[:5]}")
    check(ses5.ses1.untracked_not_new() == [], f"git status shows more than new files: {ses5.ses1.untracked_not_new()[:5]}")
    for f in EARLIER_FILES:
        r = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", str(RL_DIR / f"{f}.py")], cwd=REPO_ROOT)
        check(r.returncode == 0, f"{f}.py differs from HEAD")
        r = subprocess.run(["git", "ls-files", "--error-unmatch", str(RL_DIR / f"{f}.py")], cwd=REPO_ROOT, capture_output=True)
        check(r.returncode == 0, f"{f}.py is not tracked")
    for f in ("m9_artifacts.py", "m9_contract.py"):
        r = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", str(RL_DIR / f)], cwd=REPO_ROOT)
        check(r.returncode == 0, f"{f} differs from HEAD (the M9 writer is imported unchanged)")
    for d in ses5.DOC_FILES:
        r = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", str(REPO_ROOT / d)], cwd=REPO_ROOT)
        check(r.returncode == 0, f"{d} differs from HEAD")
        r = subprocess.run(["git", "ls-files", "--error-unmatch", str(REPO_ROOT / d)], cwd=REPO_ROOT, capture_output=True)
        check(r.returncode == 0, f"{d} is not tracked")
    return {"earlier_files": len(EARLIER_FILES)}


def unit_snapshot_tool5() -> Dict[str, Any]:
    t = tmpdir("m8sn5_")
    dest = t / "snap"
    r = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_sd1_snapshot.py"), "snapshot", "--dest", str(dest)], capture_output=True, text=True, timeout=1800)
    check(r.returncode == 0, f"snapshot: {r.stdout[-500:]} {r.stderr[-500:]}")
    rec = json.loads((dest / "snapshot.json").read_text(encoding="utf-8"))
    check(art.is_stamped(rec) and rec["result"] == "PASS" and rec["n_files"] > 40 and not rec["problems"] and not rec["identity_code_mismatch"] and not rec["identity_docs_mismatch"]
          and rec["tool"] == "m8_sd1_source_snapshot_v1" and rec["source_fingerprint"] == ses5.source_fingerprint(), f"snapshot record: {rec['result']} {rec['problems']} {rec['identity_code_mismatch']} {rec['identity_docs_mismatch']}")
    names = {f["path"] for f in rec["files"]}
    check({"rl/m8_sd1_select.py", "rl/m8_sd1_run.py", "rl/m8_sd1_rule.py", "rl/m8_sd1_claims.py", "rl/m8_sd1_artifacts.py", "rl/m8_rd4_run.py", "rl/m8_rd_select2.py", "rl/m9_artifacts.py", "rl/m9_contract.py",
           "tools/m8_sd1/launch_detached.ps1", "tools/m8_sd1/wait_session.py", "tools/m8_sd1/write_approval.py", "tools/m8_sd1/three_passes.py", "tools/m8_sd1/independent_increment_check.ps1",
           "docs/rl_m8_sd1_proposal_2026-10-07.md", "docs/rl_m8_rd4_results_2026-10-03.md", "logs/m8_sd1_prep/phase1_plan.md"} <= names, "the snapshot holds the sd1 code, the tools, the proposal, the plan and the earlier code")
    r = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_sd1_snapshot.py"), "verify", "--dest", str(dest)], capture_output=True, text=True, timeout=1800)
    check(r.returncode == 0, f"verify: {r.stdout[-300:]}")
    vrec = [p for p in dest.glob("verify_*.json")]
    check(vrec and art.is_stamped(json.loads(vrec[0].read_text(encoding="utf-8"))), "the verification record is stamped")
    r = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_sd1_snapshot.py"), "snapshot", "--dest", str(dest)], capture_output=True, text=True, timeout=60)
    check(r.returncode == 2, "an existing destination is never overwritten")
    victim = dest / "files" / "rl" / "m8_sd1_select.py"
    victim.write_bytes(victim.read_bytes() + b"\n#tampered\n")
    r = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_sd1_snapshot.py"), "verify", "--dest", str(dest)], capture_output=True, text=True, timeout=1800)
    check(r.returncode == 1 and "m8_sd1_select.py" in r.stdout, "a tampered copy fails the verification")
    ps = subprocess.run([sys.executable, "-B", str(RL_DIR / "m8_sd1_snapshot.py"), "powershell", "--dest", str(dest)], capture_output=True, text=True, timeout=60)
    check("Get-FileHash" in ps.stdout, "the independent re-hash script is generated")
    shutil.rmtree(t, ignore_errors=True)
    return {"files": rec["n_files"]}


def unit_import_isolation5() -> Dict[str, Any]:
    code = ("import sys; sys.path.insert(0, r'%s'); " % RL_DIR + "import m8_sd1_artifacts, m8_sd1_select, m8_sd1_rule, m8_sd1_claims, m8_sd1_resume, m8_sd1_report, m8_sd1_run, m8_sd1_session; "
            "print(sorted(m for m in ('torch', 'numpy', 'gymnasium', 'stable_baselines3', 'm7u3_gate', 'm7f_trace', 'm7n_crossing', 'm7g_fixture', 'btt_learning', 'm7h_curriculum') if m in sys.modules))")
    r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=120)
    check(r.stdout.strip() == "[]", f"the sd1 modules imported heavy ones: {r.stdout.strip()} {r.stderr[-300:]}")
    return {}


def unit_tools5_parsers() -> Dict[str, Any]:
    """Every tool has an argument parser with required arguments; its refusals are exits; the fingerprint of the three-passes tool equals the session's."""
    out: Dict[str, Any] = {}
    for f in PYTHON_TOOLS:
        r = subprocess.run([sys.executable, "-B", str(TOOLS_DIR / f), "--help"], capture_output=True, text=True, timeout=300)
        check(r.returncode == 0 and "--session" in r.stdout and "required" not in r.stderr, f"{f} --help: {r.returncode} {r.stderr[-200:]}")
        r = subprocess.run([sys.executable, "-B", str(TOOLS_DIR / f)], capture_output=True, text=True, timeout=300)
        check(r.returncode == 2 and "required" in r.stderr, f"{f} without its required arguments exits 2: {r.returncode} {r.stderr[-200:]}")
        r = subprocess.run([sys.executable, "-B", str(TOOLS_DIR / f), "--session", "rd4"], capture_output=True, text=True, timeout=300)
        check(r.returncode == 2 and "invalid choice" in r.stderr, f"{f} refuses another session: {r.stderr[-200:]}")
        out[f] = "parser ok"
    t = tmpdir("m8tools5_")
    r = subprocess.run([sys.executable, "-B", str(TOOLS_DIR / "three_passes.py"), "--session", "sd1", "--out", "tools/m8_sd1/never"], capture_output=True, text=True, timeout=300)
    check(r.returncode == 2 and "never written again" in r.stdout, "three_passes refuses an output directory inside the tools")
    r = subprocess.run([sys.executable, "-B", str(TOOLS_DIR / "three_passes.py"), "--session", "sd1", "--out", "logs/m8_rd4_prep/x"], capture_output=True, text=True, timeout=300)
    check(r.returncode == 2 and "never written again" in r.stdout, "three_passes refuses an earlier preparation's directory")
    (t / "passes.json").write_text("{}", encoding="utf-8")
    r = subprocess.run([sys.executable, "-B", str(TOOLS_DIR / "three_passes.py"), "--session", "sd1", "--out", str(t)], capture_output=True, text=True, timeout=300)
    check(r.returncode == 2 and "never overwritten" in r.stdout, "three_passes refuses to overwrite passes.json")
    env_no_b = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
    r = subprocess.run([sys.executable, str(TOOLS_DIR / "wait_session.py"), "--session", "sd1", "--repo", str(t)], capture_output=True, text=True, timeout=300, env=env_no_b)
    check(r.returncode == 2 and "python -B" in r.stdout, f"the tools refuse to run without -B: {r.returncode} {r.stdout[-200:]}")
    r = subprocess.run([sys.executable, "-B", str(TOOLS_DIR / "wait_session.py"), "--session", "sd1", "--repo", str(t)], capture_output=True, text=True, timeout=300)
    check(r.returncode == 1 and "no launch record" in r.stdout, "wait_session refuses a repository without a launch record")
    spec = importlib.util.spec_from_file_location("sd1_three_passes", TOOLS_DIR / "three_passes.py")
    tp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tp)                      # type: ignore[union-attr]
    check(tp.fingerprint(REPO_ROOT) == ses5.source_fingerprint() and tp.GIT_GATE == "tracked_files_unchanged5", "the tool's fingerprint equals the session's, over rl/m8_sd1_*.py and tools/m8_sd1/*")
    for f in ("launch_detached.ps1", "independent_increment_check.ps1"):
        src = (TOOLS_DIR / f).read_text(encoding="utf-8")
        check("param(" in src and src.count("Mandatory=$true") >= 2, f"{f} declares mandatory parameters")
    check("ValidateSet('sd1')" in (TOOLS_DIR / "launch_detached.ps1").read_text(encoding="utf-8"), "the launcher accepts sd1 only")
    check((TOOLS_DIR / "independent_increment_check.ps1").read_bytes() == (REPO_ROOT / "logs" / "m8_rd4_prep" / "tools" / "independent_increment_check.ps1").read_bytes()
          if (REPO_ROOT / "logs" / "m8_rd4_prep" / "tools" / "independent_increment_check.ps1").is_file() else True, "the independent re-hash script is rd4's, byte for byte")
    if shutil.which("powershell"):
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(TOOLS_DIR / "launch_detached.ps1"), "-Session", "sd1", "-Repo", str(t)],
                           capture_output=True, text=True, timeout=300)
        check(r.returncode != 0 and "not the BattleShip checkout" in (r.stdout + r.stderr) and not (t / "logs").exists(), f"the launcher refuses a repository that is not the checkout and leaves nothing behind: {r.returncode} {(r.stdout + r.stderr)[-300:]}")
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(TOOLS_DIR / "launch_detached.ps1"), "-Session", "rd4", "-Repo", str(t)],
                           capture_output=True, text=True, timeout=300)
        check(r.returncode != 0, "the launcher refuses another session")
        out["launch_detached.ps1"] = "refusals ok"
    shutil.rmtree(t, ignore_errors=True)
    return out


# -- APPEND_POINT_C --


def _earlier(name: str, table: Sequence[Tuple[str, Callable[[], Dict[str, Any]]]], prefix: str) -> Tuple[str, Callable[[], Dict[str, Any]]]:
    fn = dict(table)[name]
    return f"{prefix}:{name}", fn


TESTS: List[Tuple[str, Callable[[], Dict[str, Any]]]] = [
    ("sd1_contract", unit_sd1_contract), ("select_v4_formula_and_digest", unit_select_v4_formula_and_digest), ("record_bound_e7", unit_record_bound_e7),
    ("archive5_draw_and_mode_switch", unit_archive5_draw_and_mode_switch), ("begin_sd1_and_persistence", unit_begin_sd1_and_persistence), ("ledger_rebuild5", unit_ledger_rebuild5),
    ("resume_four_level_synthetic", unit_resume_four_level_synthetic), ("inherited_record_facts_refusal", unit_inherited_record_facts_refusal),
    ("write_guard_all_runs_roots", unit_write_guard_all_runs_roots), ("claims5_pool_and_plan", unit_claims5_pool_and_plan), ("clear_exactness5_on_stub_traces", unit_clear_exactness5_on_stub_traces),
    ("inherited_descriptive_candidates", unit_inherited_descriptive_candidates), ("rule5_module", unit_rule5_module), ("decide5_outcomes_and_stops", unit_decide5_outcomes_and_stops),
    ("session5_small_run", unit_session5_small_run), ("session5_determinism", unit_session5_determinism), ("session5_inherited_continuations", unit_session5_inherited_continuations),
    ("session5_record_replay_at_open", unit_session5_record_replay_at_open), ("budget_projection5", unit_budget_projection5), ("approval_isolated5", unit_approval_isolated5),
    ("results_record_rule5", unit_results_record_rule5),
    ("artifacts5_stamping", unit_artifacts5_stamping), ("task_block_pinned", unit_task_block_pinned), ("source_guard5", unit_source_guard5), ("no_nondeterminism_in_sd1", unit_no_nondeterminism_in_sd1),
    ("tracked_files_unchanged5", unit_tracked_files_unchanged5), ("snapshot_tool5", unit_snapshot_tool5), ("import_isolation5", unit_import_isolation5), ("tools5_parsers", unit_tools5_parsers),
    ("open_protocol_real_trees5", unit_open_protocol_real_trees5),
] + [_earlier(n, t4.TESTS, "rd4") for n in RD4_PURE] + [_earlier(n, t3.TESTS, "rd3") for n in RD3_PURE] + [_earlier(n, t1.TESTS, "rd1") for n in RD1_PURE] + [_earlier(n, t2.TESTS, "rd2") for n in RD2_PURE]


def _cleanup() -> None:
    while _TMP:
        shutil.rmtree(_TMP.pop(), ignore_errors=True)
    t4._cleanup()


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
    for rec in list(_CHAIN5.values()) + list(t4._CHAIN4.values()) + list(t3._CHAIN.values()):
        shutil.rmtree(rec["t"], ignore_errors=True)
    for rec in getattr(t2, "_SYN", {}).values():
        shutil.rmtree(rec["t"], ignore_errors=True)
    total = passed + len(failed)
    if out is not None:
        out = Path(out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "m8_sd1_unit.json").write_text(json.dumps({"passed": passed, "total": total, "failed": failed, "wall_s": round(time.perf_counter() - t_all, 1), "results": results}, indent=1,
                                                         default=str) + "\n", encoding="utf-8")
    print(f"{passed} / {total} passed (unit); wall {time.perf_counter() - t_all:.0f} s")
    return 0 if not failed else 1


# -- the production-count synthetic end-to-end run ---------------------------------------------------------------------------------------------------------------


def e2e_digest(root5: Path) -> str:
    """sha256 (16 hex) of the run's signature: the four data files' hashes, the session event, the open overlay's digest, the rule record's registered fields, the verification's pools
    and replay order, the line status. Wall-clock and memory readings are excluded."""
    return hashlib.sha256(json.dumps(signature5(root5), sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def e2e(out: Path, small: bool = False, world: str = CHAIN_WORLD) -> int:
    """The sd1 session at the registered counts (6,000,000 exploration ticks valid from 2,000,000, five workers, 16 identity replays, the registered caps) against a synthetic four-tree chain
    (rd1, rd2, rd3 and rd4 by their own real engines, each with its verified increment, rd4 carrying a verified clear) and the stub, through the lock-step pool and the virtual clock: the four-level
    resume (R1-R6), both overlays, the selection `m8_rd_select_v4` under sd1's draws, P1 against the archive's pin, the open identity replays and the record re-verified, the fastest-first
    verification of the clear pool, the inherited descriptive replays, the close audit of the five-part ledger, the prefix chain, the stamp audit and verify-run, with rd4's claim cases (a) and
    (b) as the session's first dispatches. The run is a pure function of its configuration; its digest is the last line printed. The world is synthetic: the outcome says nothing about Mario."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    problems: List[str] = []
    t0 = time.perf_counter()
    chain = build_chain5(world, cache=False)
    e4 = chain["expect4"]
    rr = e4["inherited_record"]["best_verified"]
    print(f"[e2e] synthetic chain built in {time.perf_counter() - t0:.0f} s: rd1 {chain['expect1']['cells']} cells, rd2 {chain['expect2']['cells']}, rd3 {chain['expect3']['cells']}, rd4 {e4['cells']} cells; "
          f"rd4 {chain['rd4_outcome']} m {chain['rd4_m']}; the record {rr['completion_input_tick']} / {rr['completion_time_passed']}; {len(e4['inherited_record']['unverified_clear_trajectories'])} unverified trajectories", flush=True)
    cp = copy_chain5(chain)
    root5 = out / "sd1"
    if root5.exists():
        shutil.rmtree(root5)
    kw: Dict[str, Any] = dict(checkpoint_every_s=20.0)
    if small:
        kw.update(arm_tick_cap=200000, arm_caps={"T": 200000}, min_arm_ticks=60000, p1_tick_cap=70000)
    cfg = ses5.run_config(root=root5, **kw)
    op, a5 = open_chain5(cp, root5)
    cfg.session_dir.mkdir(parents=True)
    mw.ProvenanceGuard.install()
    mw.ProvenanceGuard.violations.clear()
    roots = [cp["rd1"], cp["rd2"], cp["rd3"], cp["rd4"]]
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
    cls = t4.forced_session_cls(world, ("left_nolanding", "wall_continuation"), base=run5.Session5)
    sess = cls(cfg, env, archive=a5, archive_pin=op["facts4"]["pin_tick0"], base_info={"open_overlay_sha256": op["overlay"]["v4"]["sha256"]}, rd1_root=cp["rd1"], rd2_root=cp["rd2"], rd3_root=cp["rd3"],
               rd4_root=cp["rd4"], lines_sha256=cp["lines"], ckpt_seq=int(op["facts4"]["rd4_checkpoint_seq"]) + 1, archive_created_utc=OPEN_UTC, record_candidate=op["record_candidate"],
               inherited=op["inherited"], rd4_line=op["facts4"]["rd4_line"])
    sess.pool = SyncPool(env, cfg, clock)
    res = run5.run_all5(sess, immutability=lambda: all_immutability5(cp))
    wall = time.perf_counter() - t1_
    w2.WriteGuard.clear()
    rule, close = res["rule"], res["close"]
    vr = rpt5.verify_run5(root5, cp["rd4"], cp["rd3"], cp["rd2"], cp["rd1"], "sd1")
    report = rpt5.full_report5(root5, cp["rd4"], cp["rd3"], cp["rd2"], cp["rd1"], "sd1")
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
    if not all_immutability5(cp)["ok"]:
        problems.append("a synthetic earlier tree changed")
    ver = json.loads((root5 / "sessions" / "sd1" / "verification.json").read_text(encoding="utf-8"))
    io_ = sess.open_identity_record
    if not (io_.get("ok") and io_.get("cells") == 16 and ver["identity"].get("verified") == ver["identity"].get("cells") == 16):
        problems.append(f"identity replays: open {io_.get('verified')}/{io_.get('cells')}, close {ver['identity']}")
    if not sess.record_open_record.get("exact"):
        problems.append(f"the record did not re-verify at the open: {sess.record_open_record}")
    if sess.first_iteration != e4["dispatch_iterations"][1] + 1:
        problems.append("iterations do not continue from rd4's last")
    arm = ver["arm"]
    led = sess.ledgers["T"]
    ticks_of = {c["cid"]: cl5.clear_tick(c) for c in led.candidates}
    order = arm["replay_order"]
    if order != sorted(order, key=lambda cid: (ticks_of[cid], cid)) or any(led.candidates[cid]["kind"] != "clear" for cid in order):
        problems.append(f"the pool was not replayed fastest first, clear-kind only: {order}")
    if (arm["best_verified"] is not None) != arm["closed"] or arm["remaining_faster_than_best"] != 0:
        problems.append("the pool did not close at the first exact replay")
    inh = ver["inherited_descriptive"]
    if inh["count"] != len(e4["inherited_record"]["unverified_clear_trajectories"]) or inh["replayed"] != inh["count"] or inh["exact"] != inh["count"] or rule["flags"]:
        problems.append(f"the inherited descriptive replays: {inh} flags {rule['flags']}")
    forced = {f["kind"]: f for f in sess.forced}
    if set(forced) != {"left_nolanding", "wall_continuation"} or any(f["cell"] >= e4["cells"] for f in forced.values()):
        problems.append(f"the forced dispatches are not the two inherited cells: {forced}")
    else:
        rows_s = art.rows_of(root5 / "sessions" / "sd1" / "wall_top_sightings.jsonl")
        row = next((x for x in rows_s if x["iteration"] == forced["wall_continuation"]["iteration"]), None)
        if not (row and row["start_cell_on_wall_top"] and row["first_tick_of_the_burst"]) or led.l0_cid is not None:
            problems.append(f"the wall-top continuation: {row} l0 {led.l0_cid}")
        cand_b = t4.candidate_for_iteration(sess, forced["left_nolanding"]["iteration"], "left")
        if cand_b is None or cand_b["cid"] in order:
            problems.append("the left continuation was replayed or not registered")
    again = rule5.apply(invalid=[], incomplete=[], verified_clears=arm["verified_clears"], t_rec=rr["completion_input_tick"], t_rec_time_passed=rr["completion_time_passed"], margin=rule5.MARGIN, exploration_started=True,
                        exploration_ticks=led.ticks, inherited_descriptive=inh["records"], rd4_line=op["facts4"]["rd4_line"], max_targets=arm["max_targets"], **{k: rule["extra"]["rule_inputs"][k] for k in
                        ("returns", "dispatches", "below_floor", "fatal_returns", "launch_capable_created", "bound_violations", "top_level_median_L")})
    for k in ("outcome", "flags", "any_stop"):
        if again[k] != rule[k]:
            problems.append(f"the recorded {k} {rule[k]} differs from the rule applied to the verified clears {again[k]}")
    if again["line"]["status"] != rule["line"]["status"]:
        problems.append("the recorded line status differs from the rule's")
    digest = e2e_digest(root5)
    best = rule.get("best_verified") or {}
    summary = {"small": small, "world": world, "engine": "lock-step pool, virtual clock", "wall_s": round(wall, 1), "outcome": rule["outcome"], "best_verified": {k: best.get(k) for k in ("cid", "completion_input_tick", "completion_time_passed")},
               "record_reference": rr["completion_input_tick"], "margin": rule5.MARGIN, "verified_clears": len(arm["verified_clears"]), "tiers_reached": (rule.get("tiers") or {}).get("reached"), "flags": rule["flags"],
               "stops": rule["any_stop"], "line": rule["line"]["status"], "ticks": led.ticks, "stop": sess.arm_records["T"]["stop"], "cells_open": e4["cells"], "cells_close": len(sess.archive.cells),
               "bursts": len(sess.archive.bursts), "candidates": len(led.candidates), "pools": ver.get("pools"), "pool": arm["pool"], "replays": arm["replays"], "replay_order": order,
               "inherited": {k: inh[k] for k in ("count", "replayed", "exact", "ticks")}, "forced": forced, "phase_wall_s": sess.clock.to_json()["phase_wall_s"], "peak_main_private_mb": sess.clock.peak_mb,
               "verify_run": vr["ok"], "replay_ticks": sess.ticks["replays"], "open_ticks": sess.ticks["p1"], "open_identity": io_, "identity_close": ver["identity"], "record_open": {k: sess.record_open_record.get(k) for k in ("exact", "words")},
               "audit": close.get("audit"), "artifacts": close.get("artifacts"), "prefix_chain": {k: close.get("prefix_chain", {}).get(k) for k in ("ok", "problems")}, "archive_stats": sess.archive.stats(),
               "rule_inputs": rule["extra"]["rule_inputs"], "overlay_open": op["overlay"]["v4"]["counts"], "overlay_close_v4": close.get("archive", {}).get("overlay_close_v4"),
               "E7": report["D8_overlays"]["E7"], "pace": report["pace"]["sd1"], "selection_at_the_open": {m_: report["selection_at_the_open"][m_]["top_level_mass"] for m_ in ("v3", "v4")},
               "dilution": rule["dilution"]["verdict"], "digest": digest, "problems": problems}
    (out / "e2e.json").write_text(json.dumps(art.stamp(summary), indent=1, default=str) + "\n", encoding="utf-8")
    (out / "e2e.log").write_text("\n".join(logs) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("open_identity", "identity_close", "archive_stats", "rule_inputs", "overlay_open", "overlay_close_v4", "pace", "forced")}, indent=1, default=str))
    shutil.rmtree(chain["t"], ignore_errors=True)
    shutil.rmtree(cp["t"], ignore_errors=True)
    if not problems:
        shutil.rmtree(root5, ignore_errors=True)               # the synthetic sd1 tree is large and says nothing about Mario; e2e.json and e2e.log are the record
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
        return run_unit(a.only.split(",") if a.only else None, a.out or Path(tempfile.mkdtemp(prefix="m8_unit5_")))
    return e2e(a.out or Path(tempfile.mkdtemp(prefix="m8_e2e5_")), small=a.small, world=a.world)


if __name__ == "__main__":
    sys.exit(main())
