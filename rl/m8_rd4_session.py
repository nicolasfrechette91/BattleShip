#!/usr/bin/env python3
"""M8-rd4 session driver: one third-continuation session of archive m8_rd_a1 (rd1, rd2 and rd3 as closed) under `m8_rd_select_v3`.

    python rl/m8_rd4_session.py status
    python rl/m8_rd4_session.py open-check               # zero ticks, writes nothing: R1-R5 against the three earlier trees
    python rl/m8_rd4_session.py preflight [--skip-unit]  # no game: tests, pins, D: coverage, readiness, approval
    python rl/m8_rd4_session.py approval-template        # prints the record a reviewer would write (never writes it)
    python rl/m8_rd4_session.py run                      # refused unless the preflight passes, including the approval
    python rl/m8_rd4_session.py verify-run               # read-only post-run verification
    python rl/m8_rd4_session.py report                   # the registered diagnostics beside rd3's, rd2's and rd1's reference values

Design: docs/rl_m8_rd3_stop_review_2026-10-03.md (the candidate K1 and the call) as decided in docs/rl_m8_rd4_decisions_2026-10-03.md; the implementation record is
docs/rl_m8_rd4_implementation.md. SCOPE: third continuation of archive m8_rd_a1 (rd1, rd2 and rd3 as closed) under m8_rd_select_v3 (m8_rd_select_v2 with one change: the count term
(1 + seen)^-1/2); one session, one set of keyed draws; no control arm; not a policy result, not a learning result, not a comparison of v3 with v2.

The earlier trees (runs/m8_rd/, runs/m8_rd_rd2/, runs/m8_rd_rd3/) are only read; rd4 writes only under runs/m8_rd_rd4/. Light top-level imports only (spawned workers re-import this script).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))

import m8_rd_archive as march  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_explore as mx  # noqa: E402
import m8_rd_resume as rs  # noqa: E402
import m8_rd_run as mrun  # noqa: E402
import m8_rd_select2 as s2  # noqa: E402
import m8_rd_session as ses1  # noqa: E402
import m8_rd_worker as mw  # noqa: E402
import m8_rd2_session as ses2  # noqa: E402
import m8_rd2_worker as w2  # noqa: E402
import m8_rd3_resume as r3  # noqa: E402
import m8_rd3_session as ses3  # noqa: E402
import m8_rd4_claims as cl4  # noqa: E402
import m8_rd4_resume as r4  # noqa: E402
import m8_rd4_rule as rule4  # noqa: E402
import m8_rd4_run as run4  # noqa: E402
import m8_rd4_select as s4  # noqa: E402

REPO_ROOT = ses1.REPO_ROOT
RL = ses1.RL
RUNS = ses1.RUNS
LOGS = ses1.LOGS
RD1_ROOT = RUNS / "m8_rd"
RD2_ROOT = RUNS / "m8_rd_rd2"
RD3_ROOT = RUNS / "m8_rd_rd3"
RD4_ROOT = RUNS / "m8_rd_rd4"
APPROVAL = REPO_ROOT / "docs" / "rl_m8_rd4_approval.json"
BACKUP_ROOT = ses1.BACKUP_ROOT
INCREMENT_RD1 = BACKUP_ROOT / rs.RD1_INCREMENT_NAME
INCREMENT_RD2 = BACKUP_ROOT / r3.RD2_INCREMENT_NAME
INCREMENT_RD3 = BACKUP_ROOT / r4.RD3_INCREMENT_NAME
SNAPSHOT_ROOT = ses1.SNAPSHOT_ROOT
SESSION = "rd4"
GATE = "m8_rd4"
ARCHIVE_ID = "m8_rd_a1"
SCOPE = rule4.SCOPE
N_WORKERS = 5
RD1_EXPECT: Mapping[str, Any] = rs.RD1_FACTS
RD2_EXPECT: Mapping[str, Any] = r3.RD2_FACTS
RD3_EXPECT: Mapping[str, Any] = r4.RD3_FACTS
CHECK_EXPECTED_OVERLAY = True                    # the registered closing-overlay figures (off only in the tests on synthetic trees)
EXECUTABLE = ses1.EXECUTABLE
EXE_DIR = ses1.EXE_DIR
FLAGS_EXPLORE = ses1.FLAGS_EXPLORE
FLAGS_VERIFY = ses1.FLAGS_VERIFY
READINESS = ses1.READINESS

NEW_CODE_FILES = ("m8_rd4_select.py", "m8_rd4_resume.py", "m8_rd4_claims.py", "m8_rd4_run.py", "m8_rd4_session.py", "m8_rd4_rule.py", "m8_rd4_report.py", "m8_rd4_snapshot.py",
                  "m8_rd4_tests.py")
CODE_FILES = tuple(ses3.CODE_FILES) + NEW_CODE_FILES
DOC_FILES = tuple(ses3.DOC_FILES) + ("docs/rl_m8_rd3_results_2026-10-02.md", "docs/rl_m8_rd3_stop_review_2026-10-03.md", "docs/rl_m8_rd4_decisions_2026-10-03.md",
                                     "docs/rl_m8_rd4_implementation.md")
RULE_SELF_TESTS = (("rule_self_test_rd1", "m8_rd_rule.py"), ("rule_self_test_rd2", "m8_rd2_rule.py"), ("rule_self_test_rd3", "m8_rd3_rule.py"), ("rule_self_test_rd4", "m8_rd4_rule.py"))


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256_file(p: Path) -> str:
    return mw.sha256_file(Path(p))


def run_config(root: Optional[Path] = None, **over: Any) -> mrun.RunConfig:
    """The registered budgets and caps (decision 4, as rd2 and rd3): exploration 50 min or 6,000,000 native ticks, valid from 2,000,000; the open phase (P1 and 16 identity replays) 70,000
    ticks / 4 min; verification 400,000 ticks / 6 min; a 60-minute hard cap from P1; memory caps as rd1's."""
    kw: Dict[str, Any] = dict(session_id=SESSION, archive_id=ARCHIVE_ID, n_workers=N_WORKERS)
    kw.update(over)
    return ses2.run_config(root=Path(root) if root is not None else RD4_ROOT, **kw)


def caps() -> Dict[str, Any]:
    cfg = run_config()
    return {"exploration_tick_cap": cfg.arm_cap("T"), "min_exploration_ticks": cfg.min_arm_ticks, "open_tick_cap": cfg.p1_tick_cap,
            "replay_tick_cap": cfg.replay_tick_cap, "wall_caps_s": {k: v for k, v in cfg.wall_caps_s.items() if k != "C"},
            "global_cap_s": cfg.global_cap_s, "checkpoint_every_s": cfg.checkpoint_every_s, "memory_caps_mb": dict(cfg.memory_caps_mb),
            "memory_sample_s": ses1.MEMORY_SAMPLE_S, "max_battleship_processes": cfg.max_battleship_processes,
            "lifecycle_failure_limit": cfg.lifecycle_failure_limit, "verify_threads": cfg.verify_threads, "identity_k": cfg.identity_k,
            "job_timeout_s": mrun.JOB_TIMEOUT_S, "wall_cap_grace_s": mrun.WALL_CAP_GRACE_S}


# -- identity and approval ---------------------------------------------------------------------------------------------------------------


def contract_digests4(lines_sha256: str) -> Dict[str, str]:
    """rd2's contract digests (cell, select v1, explore, claims, Track 1, status table, select v2) and rd4's selection contract `m8_rd_select_v3` (the registered change from v2)."""
    import m7q_status_table as st

    d = dict(ses2.contract_digests2(lines_sha256))
    d["m8_rd_select_v3"] = s4.select3_contract_digest(st.load_table()["sha256"], lines_sha256)
    return d


def _events(archive_dir: Path) -> List[Dict[str, Any]]:
    return ses3._events(archive_dir)


def base_identity4(rd1_dir: Optional[Path] = None, rd2_dir: Optional[Path] = None, rd3_dir: Optional[Path] = None, inc1: Optional[Path] = None, inc2: Optional[Path] = None,
                   inc3: Optional[Path] = None) -> Dict[str, Any]:
    """What rd4 starts from: rd1's and rd2's base identity (as rd3 pinned it) and rd3's closing archive, close record and D: increment."""
    rd1_dir = RD1_ROOT if rd1_dir is None else rd1_dir                    # resolved at call time (the tests patch the module paths)
    rd2_dir = RD2_ROOT if rd2_dir is None else rd2_dir
    rd3_dir = RD3_ROOT if rd3_dir is None else rd3_dir
    inc1 = INCREMENT_RD1 if inc1 is None else inc1
    inc2 = INCREMENT_RD2 if inc2 is None else inc2
    inc3 = INCREMENT_RD3 if inc3 is None else inc3
    meta = json.loads((Path(rd3_dir) / "archive" / "archive_meta.json").read_text(encoding="utf-8"))
    close_p = Path(rd3_dir) / "sessions" / "rd3" / "close.json"
    inc_m = Path(inc3) / "manifest.tsv.gz"
    return {"rd1_and_rd2": ses3.base_identity3(rd1_dir, rd2_dir, inc1, inc2),
            "rd3_archive_files_sha256": {n: march.sha256_file(Path(rd3_dir) / "archive" / n) for n in march.DATA_FILES},
            "rd3_close_record_sha256": sha256_file(close_p) if close_p.is_file() else None, "rd3_increment": Path(inc3).name,
            "rd3_increment_manifest_sha256": sha256_file(inc_m) if inc_m.is_file() else None, "rd3_checkpoint_seq": meta.get("checkpoint_seq"),
            "rd3_session_events": [e for e in _events(Path(rd3_dir) / "archive") if e.get("ev") == "session"], "rd3_pins": meta.get("pins"),
            "pin_tick0_digest": (meta.get("pin_tick0") or {}).get("digest"), "lines_sha256": (meta.get("pin_tick0") or {}).get("lines"),
            "rd3_first_iteration": meta.get("rd3_first_iteration"), "first_rd4_iteration": r4.RD3_FACTS["first_rd4_iteration"], "inherited": r4.INHERITED_FACTS}


def identity() -> Dict[str, Any]:
    dr = ses1.d_records_digest()
    base = base_identity4()
    lines = str(base["lines_sha256"])
    ov = r4.closing_overlay(RD3_ROOT, expect=(r4.EXPECTED_CLOSE_OVERLAY if CHECK_EXPECTED_OVERLAY else {}))
    contracts = contract_digests4(lines)
    return {"gate": GATE, "scope": SCOPE, "milestone": "M8", "archive_id": ARCHIVE_ID, "session": SESSION, "rule": rule4.RULE_ID, "rule_sha256": rule4.rule_digest(),
            "claims_digest": cl4.contract_digest(), "contracts": contracts,
            "key_strings": {"select_rd1": "m8_rd|<archive_id>|select|<iteration> (iterations 0..2174, rd1)",
                            "select_rd2": f"m8_rd|<archive_id>{s4.DRAW_SUFFIX_RD2}|select|<iteration> (iterations 2175..6211, rd2)",
                            "select_rd3": f"m8_rd|<archive_id>{s4.DRAW_SUFFIX_RD3}|select|<iteration> (iterations 6212..10405, rd3)",
                            "select_rd4": f"m8_rd|<archive_id>{s4.DRAW_SUFFIX}|select|<iteration> (iterations from 10406)",
                            "explore_rd4": f"m8_rd|<archive_id>{s4.DRAW_SUFFIX}|explore|<iteration>|<decision index>",
                            "identity_open": "m8_rd|<archive_id>|identity_open|rd4|<cell id>", "identity_close": "m8_rd|<archive_id>|identity_close|rd4|<cell id>"},
            "draws_sha256": s4.draws_digest(), "rd4_session_event_digest": contracts["m8_rd_select_v3"], "select_v3_changed_from": {"m8_rd_select_v2": contracts["m8_rd_select_v2"]},
            "select_v3_registered_changes": list(s4.REGISTERED_CHANGES), "count_exponent": s4.COUNT_EXPONENT,
            "executable_sha256": sha256_file(EXECUTABLE) if EXECUTABLE.is_file() else None, "runtime_files": ses1.runtime_pins(),
            "flags": {"explore": FLAGS_EXPLORE, "verify": FLAGS_VERIFY}, "p1": ses1.p1_pins(), "caps": caps(), "workers": N_WORKERS,
            "burst_words": mx.BURST_WORDS, "horizon": mcell.HORIZON, "readiness": READINESS, "base": base,
            "open_overlay": {"sha256": ov["sha256"], "counts_sha256": ses3._norm_sha(ov["counts"]), "expected_counts": r4.EXPECTED_CLOSE_OVERLAY},
            "mechanism_check": {"seen_ge_8_share_max": rule4.SEEN_SHARE_MAX_PER_MILLE / 1000, "seen_min": rule4.SEEN_MIN, "new_cells_per_return_min": rule4.NEW_CELLS_MIN_PER_100_RETURNS / 100},
            "line_budget": rule4.BUDGET,
            "budgets": {"exploration": "50 min or 6,000,000 native ticks, valid from 2,000,000", "open": "70,000 ticks / 4 min",
                        "verification": "400,000 ticks / 6 min", "hard_cap": "60 min from P1"},
            "code": {f"rl/{f}": sha256_file(RL / f) for f in CODE_FILES if (RL / f).is_file()},
            "docs_sha256": {f: sha256_file(REPO_ROOT / f) for f in DOC_FILES if (REPO_ROOT / f).is_file()},
            "git_head": ses1.git("rev-parse", "HEAD").strip(), "d_records": {"folders": dr["folders"], "digest": dr["digest"]}}


def approval_status(path: Optional[Path] = None, want: Optional[Mapping[str, Any]] = None) -> Tuple[bool, str]:
    return ses1.approval_status(Path(APPROVAL if path is None else path), want if want is not None else identity())


# -- the open protocol (zero native ticks) -----------------------------------------------------------------------------------------------------


def open_protocol4(rd1_dir: Optional[Path] = None, rd2_dir: Optional[Path] = None, rd3_dir: Optional[Path] = None, inc1: Optional[Path] = None, inc2: Optional[Path] = None,
                   inc3: Optional[Path] = None, *, expect1: Optional[Mapping[str, Any]] = None, expect2: Optional[Mapping[str, Any]] = None, expect3: Optional[Mapping[str, Any]] = None,
                   check_overlay: Optional[bool] = None, live_pins: Optional[Callable[[], Mapping[str, Any]]] = None, floor_min: Optional[float] = None,
                   with_audit: bool = True) -> Dict[str, Any]:
    """R1-R5 at three levels: immutability of all three trees, the archive facts and audits (rd1's with rd1's own code, rd2's with rd2's, rd3's with rd3's), the pins, the closing overlay of
    rd3's archive computed twice and its figures, the claim preconditions of the inherited archive. Writes nothing."""
    expect1 = RD1_EXPECT if expect1 is None else expect1
    expect2 = RD2_EXPECT if expect2 is None else expect2
    expect3 = RD3_EXPECT if expect3 is None else expect3
    check_overlay = CHECK_EXPECTED_OVERLAY if check_overlay is None else check_overlay
    rd1_dir = Path(RD1_ROOT if rd1_dir is None else rd1_dir)             # resolved at call time (the tests patch the module paths)
    rd2_dir = Path(RD2_ROOT if rd2_dir is None else rd2_dir)
    rd3_dir = Path(RD3_ROOT if rd3_dir is None else rd3_dir)
    inc1 = INCREMENT_RD1 if inc1 is None else inc1
    inc2 = INCREMENT_RD2 if inc2 is None else inc2
    inc3 = INCREMENT_RD3 if inc3 is None else inc3
    problems: List[str] = []
    out: Dict[str, Any] = {"problems": problems}
    keys = ("ok", "files", "manifest_files", "manifest_sha256", "bytes", "increment_record")

    def guard(label: str, fn: Callable[[], Any], default: Dict[str, Any]) -> Dict[str, Any]:
        """A section that raises (a tampered archive file whose manifest no longer verifies, an unreadable record) refuses the session with a recorded problem; it never aborts the protocol."""
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
            problems.append(f"{label}: {type(exc).__name__}: {exc}")
            return default

    imms: Dict[str, Dict[str, Any]] = {}
    for who, root, inc in (("rd1", rd1_dir, inc1), ("rd2", rd2_dir, inc2), ("rd3", rd3_dir, inc3)):
        imm = guard(f"R1 ({who})", lambda root=root, inc=inc: rs.rd1_immutability(root, Path(inc)), {"ok": False, "problems": []})
        imms[who] = imm
        out[f"R1_{who}_immutability"] = {k: imm.get(k) for k in keys}
        problems += [f"R1 ({who}): {p}" for p in imm["problems"]]
    # the registered anchors of the increments (only the keys a registered fact set carries are checked: the synthetic trees carry none of them)
    for who, E in (("rd1", expect1), ("rd2", expect2), ("rd3", expect3)):
        imm = imms[who]
        for ek, ik in (("files", "files"), ("bytes", "bytes"), ("increment_manifest_sha256", "manifest_sha256")):
            if ek in E and imm.get(ik) != E[ek]:
                problems.append(f"R1 ({who}): the increment's {ik} {imm.get(ik)!r} differs from the registered {E[ek]!r}")
    if expect1 is rs.RD1_FACTS and imms["rd1"].get("manifest_sha256") != rs.RD1_INCREMENT_MANIFEST_SHA256:
        problems.append(f"R1 (rd1): the increment's manifest {imms['rd1'].get('manifest_sha256')!r} differs from the registered {rs.RD1_INCREMENT_MANIFEST_SHA256!r}")
    facts1 = guard("R2/R4 (rd1)", lambda: rs.rd1_archive_facts(rd1_dir, expect1), {"ok": False, "problems": []})
    out["R2_R4_rd1_archive"] = {k: facts1.get(k) for k in ("ok", "checkpoints", "counts", "dispatch_iterations", "audit", "select_digest", "close_record_sha256")}
    problems += [f"R2/R4 (rd1): {p}" for p in facts1.get("problems", [])]
    lines = (facts1.get("pin_tick0") or {}).get("lines")
    facts2 = guard("R2/R4 (rd2)", lambda: r3.rd2_archive_facts(rd1_dir, rd2_dir, lines, expect2, with_audit=with_audit), {"ok": False, "problems": []})
    out["R2_R4_rd2_archive"] = {k: facts2.get(k) for k in ("ok", "checkpoints", "counts", "dispatch_iterations", "audit", "close_record_sha256", "session_event", "digest_recomputed", "diag2",
                                                           "first_rd3_iteration", "rd2_checkpoint_seq")}
    problems += [f"R2/R4 (rd2): {p}" for p in facts2.get("problems", [])]
    facts3 = guard("R2/R4 (rd3)", lambda: r4.rd3_archive_facts(rd1_dir, rd2_dir, rd3_dir, lines, expect3, with_audit=with_audit), {"ok": False, "problems": []})
    out["R2_R4_rd3_archive"] = {k: facts3.get(k) for k in ("ok", "checkpoints", "counts", "dispatch_iterations", "audit", "close_record_sha256", "session_events", "digest_recomputed", "diag2",
                                                           "first_rd4_iteration", "rd3_checkpoint_seq", "inherited")}
    problems += [f"R2/R4 (rd3): {p}" for p in facts3.get("problems", [])]
    out["facts1"], out["facts2"], out["facts3"] = facts1, facts2, facts3
    if facts1.get("pin_tick0") != facts2.get("pin_tick0") or facts2.get("pin_tick0") != facts3.get("pin_tick0"):
        problems.append("R2: the pinned tick-0 records of the three archives differ")
    if facts1.get("pins") is not None and facts2.get("pins") is not None and facts3.get("pins") is not None:
        now = dict(live_pins() if live_pins else {"executable_sha256": sha256_file(EXECUTABLE), "runtime_files": ses1.runtime_pins(),
                                                  "contracts": ses2.contract_digests2(str(lines)), "flags": {"explore": FLAGS_EXPLORE, "verify": FLAGS_VERIFY}})
        frozen_dir = rd1_dir / "archive" / "runtime"
        pp3 = rs.pin_problems(facts3["pins"], now, frozen_dir, facts3["pins"].get("frozen_sha256") or {})
        pp2 = rs.pin_problems(facts2["pins"], now, frozen_dir, facts2["pins"].get("frozen_sha256") or {})
        now1 = dict(now, contracts={k: v for k, v in dict(now["contracts"]).items() if k != "m8_rd_select_v2"})      # rd1's pins predate m8_rd_select_v2
        pp1 = rs.pin_problems(facts1["pins"], now1, frozen_dir, facts1["pins"].get("frozen_sha256") or {})
        exe_only = pp3 == ["pin executable_sha256 differs"]
        out["R3_pins"] = {"problems": pp3, "rd2_problems": pp2, "rd1_problems": pp1, "executable_only": exe_only}
        if exe_only:
            problems.append("R3: only the executable differs from the archive's pin: not an exploration session (a full re-verification of every carried cell is its own authorised session)")
        else:
            problems += [f"R3: {p}" for p in pp3]
        problems += [f"R3 (rd2's pins): {p}" for p in pp2]
        problems += [f"R3 (rd1's pins): {p}" for p in pp1]
    else:
        out["R3_pins"] = {"problems": ["the archives' pins could not be read"], "rd2_problems": [], "rd1_problems": [], "executable_only": False}
        problems.append("R3: the archives' pins could not be read")
    ov = guard("R5", lambda: r4.closing_overlay(rd3_dir, expect=(r4.EXPECTED_CLOSE_OVERLAY if check_overlay else {}), floor_min=floor_min),
               {"ok": False, "problems": [], "sha256": None, "counts": {}, "rows": [], "bytes": b""})
    out["R5_overlay"] = {"ok": ov["ok"], "sha256": ov["sha256"], "counts": ov["counts"], "stored_close_counts_equal": ov["counts"] == ov.get("stored_close_counts")}
    problems += [f"R5: {p}" for p in ov["problems"]]
    if check_overlay and ov.get("sha256") is not None and ov["sha256"] != r4.CLOSING_OVERLAY_SHA256:
        problems.append(f"R5: the closing overlay's sha256 {ov['sha256']} differs from the registered {r4.CLOSING_OVERLAY_SHA256}")
    out["overlay"] = ov
    out["ok"] = not problems
    return out


# -- preflight ---------------------------------------------------------------------------------------------------------------------------------


def _run_unit_suites() -> Tuple[Dict[str, Any], List[str]]:
    """rd4's own suite (deterministic by construction; it contains the explicit lists of the deterministic pure tests of rd1, rd2 and rd3) and the four rule self-tests. The earlier suites'
    asynchronous tests are never run."""
    problems: List[str] = []
    rep: Dict[str, Any] = {}
    r = subprocess.run([sys.executable, "-B", str(RL / "m8_rd4_tests.py"), "unit"], capture_output=True, text=True, cwd=REPO_ROOT)
    rep["unit_suite_rd4"] = (r.stdout.strip().splitlines() or [r.stderr[-300:]])[-1:]
    if r.returncode != 0:
        problems.append("unit_suite_rd4 failed")
    for key, f in RULE_SELF_TESTS:
        r = subprocess.run([sys.executable, "-B", str(RL / f), "self-test"], capture_output=True, text=True, cwd=REPO_ROOT)
        rep[key] = (r.stdout.strip().splitlines() or [r.stderr[-300:]])[-1:]
        if r.returncode != 0:
            problems.append(f"{key} failed")
    return rep, problems


def preflight(*, run_unit: bool = True) -> Dict[str, Any]:
    problems: List[str] = []
    rep: Dict[str, Any] = {"utc": utc(), "scope": SCOPE}
    if RD4_ROOT.exists():
        problems.append(f"{RD4_ROOT.relative_to(REPO_ROOT)} exists (never overwritten)")
    if run_unit:
        r, p = _run_unit_suites()
        rep.update(r)
        problems += p
    if not EXECUTABLE.is_file():
        problems.append(f"missing executable {EXECUTABLE}")
    ident = identity()
    rep["executable_sha256"] = ident["executable_sha256"]
    rep["git_head"] = ident["git_head"]
    changed = ses1.tracked_changes()
    if changed:
        problems.append(f"tracked files differ from HEAD: {changed[:6]}")
    odd = ses1.untracked_not_new()
    if odd:
        problems.append(f"git status shows entries other than new files: {odd[:6]}")
    rep["git_status_new_files"] = sum(1 for ln in ses1.git("status", "--porcelain").splitlines() if ln.startswith("??"))
    for n, p in ident["p1"].items():
        if not (p["native_action_digest"] == p["recorded_digest"] == p["trace_action_digest"] and p["consumed_ticks_ok"]
                and p["trace_submitted"] == p["words"] and p["trace_flags"] and p["trace_flags"].get("SSB64_RL_SPATIAL") == "1"):
            problems.append(f"pinned P1 trace {n} is not consistent: {p}")
    rep["p1"] = {n: {k: p[k] for k in ("words", "native_action_digest")} for n, p in ident["p1"].items()}
    cvars = ses1.controller_cvar_problems(EXE_DIR / "BattleShip.cfg.json")
    rep["controller_cvars"] = cvars or "absent or zero"
    if cvars:
        problems.append(f"controller-rule CVars set in BattleShip.cfg.json: {cvars}")
    try:
        import m7q_status_table as st

        st.load_table()
        rep["status_table"] = "digest verified"
    except Exception as exc:  # noqa: BLE001
        problems.append(f"status table: {type(exc).__name__}: {exc}")
    op = open_protocol4()
    rep["open_protocol"] = {k: v for k, v in op.items() if k not in ("overlay", "facts1", "facts2", "facts3", "problems")}
    problems += op["problems"]
    cov = ses1.combined_coverage()
    rep["backup"] = {k: cov.get(k) for k in ("ok", "reason", "source_files", "uncovered", "increments", "skipped")}
    if not cov.get("ok"):
        problems.append(f"backup prerequisite not met: {cov.get('reason')}")
    procs = ses1.game_processes()
    if procs:
        problems.append(f"BattleShip already running: {procs}")
    rd = ses1.readiness()
    rep["readiness"] = rd
    problems += [f"readiness: {p}" for p in rd["problems"]]
    ok, why = ses1.approval_status(APPROVAL, ident)
    rep["approval"] = why
    approval = json.loads(APPROVAL.read_text(encoding="utf-8")) if APPROVAL.is_file() else None
    sok, swhy = ses1.snapshot_status(approval)
    rep["source_snapshot"] = swhy
    if not sok:
        problems.append(f"source snapshot: {swhy}")
    if not ok:
        problems.append(why)
    rep["problems"] = problems
    rep["ok"] = not problems
    return rep


# -- the real environment ----------------------------------------------------------------------------------------------------------------------


def build_real_env4(cfg: mrun.RunConfig, frozen_dir: Path, frozen: Mapping[str, str], pins: Mapping[str, Any], sampler: Any = None, *, executable: Optional[Path] = None,
                    flags_explore: Optional[Mapping[str, str]] = None, flags_verify: Optional[Mapping[str, str]] = None) -> mrun.RunEnv:
    """rd2's real environment (the frozen runtime is rd1's, read in place; never re-frozen from the live configuration), with the write guard of every worker over ALL THREE earlier trees."""
    env = ses2.build_real_env2(cfg, frozen_dir, frozen, pins, sampler, executable=executable if executable is not None else EXECUTABLE,
                               flags_explore=flags_explore if flags_explore is not None else FLAGS_EXPLORE,
                               flags_verify=flags_verify if flags_verify is not None else FLAGS_VERIFY, rd1_root=RD1_ROOT)
    inner = env.worker_spec
    protected = [str(RD1_ROOT), str(RD2_ROOT), str(RD3_ROOT)]

    def worker_spec(rank: int, c: mrun.RunConfig) -> Dict[str, Any]:
        spec = inner(rank, c)
        spec["protected_roots"] = list(protected)
        return spec

    env.worker_spec = worker_spec
    return env


def earlier_trees_immutability() -> Dict[str, Any]:
    """R1 for all three earlier trees (each equals its D: increment): the callable the close checks run."""
    a = rs.rd1_immutability(RD1_ROOT, INCREMENT_RD1)
    b = rs.rd1_immutability(RD2_ROOT, INCREMENT_RD2)
    c = rs.rd1_immutability(RD3_ROOT, INCREMENT_RD3)
    return {"ok": bool(a.get("ok") and b.get("ok") and c.get("ok")),
            "problems": [f"rd1: {p}" for p in a.get("problems", [])] + [f"rd2: {p}" for p in b.get("problems", [])] + [f"rd3: {p}" for p in c.get("problems", [])],
            "rd1": {k: a.get(k) for k in ("ok", "files", "manifest_sha256", "bytes")}, "rd2": {k: b.get(k) for k in ("ok", "files", "manifest_sha256", "bytes")},
            "rd3": {k: c.get(k) for k in ("ok", "files", "manifest_sha256", "bytes")}}


def open_frontier_probabilities(a: s4.Archive4) -> Dict[str, Any]:
    """The analytic selection probability, at the open and per dispatch, of the frontier cells under v2 (the rule rd3 ran) and v3 (the rule rd4 runs): wall-top cells, eligible left-of-wall cells,
    cells seen 8 or more times. A reading, never an input of the selection."""
    p2, p3 = a.probabilities("v2"), a.probabilities("v3")
    wall = [c.id for c in a.cells if c.key[2] == mcell.RES_GROUNDED and c.key[4] == mcell.L0_FLOOR_LINE]
    left = [c.id for c in a.cells if float(c.end[mcell.I_X]) < mcell.LEFT_BOUNDARY_X and a.eligible(c)]
    seen8 = [c.id for c in a.cells if c.seen >= rule4.SEEN_MIN and a.eligible(c)]

    def tot(p: Mapping[int, float], ids: Sequence[int]) -> float:
        return sum(p.get(i, 0.0) for i in ids)

    return {"wall_top_cells": {"cells": len(wall), "v2": tot(p2, wall), "v3": tot(p3, wall)}, "left_of_wall_eligible": {"cells": len(left), "v2": tot(p2, left), "v3": tot(p3, left)},
            "seen_ge_8_eligible": {"cells": len(seen8), "v2": tot(p2, seen8), "v3": tot(p3, seen8)}, "eligible_cells": len(p3),
            "note": "analytic probability per dispatch under the archive as materialised (v3 = the rule rd4 runs, v2 = rd3's, same archive)"}


# -- commands ----------------------------------------------------------------------------------------------------------------------------------


def cmd_run(overrides: Optional[Mapping[str, Any]] = None) -> int:
    """`overrides` (RunConfig fields) exists for the tests of this command only; the session passes none."""
    from m7_runtime import BATTLESHIP_IMAGE, install_kill_on_close_job, wait_until_no_process

    pf = preflight()
    if not pf["ok"]:
        print(json.dumps(pf, indent=1, default=str))
        print("refused: preflight problems (see above); nothing was launched")
        return 2
    install_kill_on_close_job()
    mw.ProvenanceGuard.install()
    w2.WriteGuard.install([RD1_ROOT, RD2_ROOT, RD3_ROOT])
    approval = json.loads(APPROVAL.read_text(encoding="utf-8"))
    # S0 (outside the clock, zero native ticks): the open protocol once more, then materialise rd4's tree
    op = open_protocol4()
    if not op["ok"]:
        print(json.dumps({k: v for k, v in op.items() if k not in ("overlay", "facts1", "facts2", "facts3")}, indent=1, default=str))
        print("refused: the open protocol failed; nothing was created")
        return 2
    facts3 = op["facts3"]
    meta1 = json.loads((RD1_ROOT / "archive" / "archive_meta.json").read_text(encoding="utf-8"))
    pins1 = meta1["pins"]
    frozen_dir = RD1_ROOT / "archive" / "runtime"
    pins = {"executable_sha256": approval["executable_sha256"], "runtime_files": dict(pins1["runtime_files"]), "frozen_sha256": dict(pins1["frozen_sha256"]),
            "contracts": approval["contracts"], "flags": approval["flags"], "archive_id": ARCHIVE_ID, "approval_sha256": sha256_file(APPROVAL),
            "git_head": approval["git_head"], "rule_sha256": approval["rule_sha256"], "p1": approval["p1"]}
    cfg = run_config(**dict(overrides or {}))
    lines = str(facts3["lines_sha256"])
    a4 = r4.materialise4(RD3_ROOT, cfg.root, facts=facts3, overlay=op["overlay"], lines_sha256=lines,
                         meta_extra={"pins": pins, "horizon": cfg.horizon, "burst_words": cfg.burst_words, "ticks": {}, "ledger_T": {"ticks": 0, "jobs": 0},
                                     "pin_tick0": facts3["pin_tick0"], "first_new_cell": len(op["overlay"]["rows"])},
                         increment_manifest_sha256=op["R1_rd3_immutability"]["manifest_sha256"], utc=utc())
    open_probs = open_frontier_probabilities(a4)
    cfg.session_dir.mkdir(parents=True)
    shutil.copyfile(APPROVAL, cfg.session_dir / "approval_copy.json")
    mrun.write_json(cfg.session_dir / "open.json", {
        "utc": utc(), "pins": pins, "preflight": {k: pf.get(k) for k in ("executable_sha256", "git_head", "readiness", "backup", "approval", "source_snapshot", "unit_suite_rd4",
                                                                       "rule_self_test_rd1", "rule_self_test_rd2", "rule_self_test_rd3", "rule_self_test_rd4")},
        "open_protocol": {k: v for k, v in op.items() if k not in ("overlay", "facts1", "facts2", "facts3")}, "caps": caps(), "frontier_selection_at_the_open": open_probs,
        "inherited_claim_facts": facts3["inherited"], "identity": {k: v for k, v in identity().items() if k != "code"}})
    sampler = ses1.make_sampler(cfg.session_dir / "memory_tree.jsonl", cfg.memory_caps_mb)
    sampler.start()
    env = build_real_env4(cfg, frozen_dir, pins1["frozen_sha256"], pins, sampler)
    try:
        sess = run4.Session4(cfg, env, archive=a4, archive_pin=facts3["pin_tick0"], base_info={"rd1_root": str(RD1_ROOT), "rd2_root": str(RD2_ROOT), "rd3_root": str(RD3_ROOT),
                                                                                              "overlay_sha256": op["overlay"]["sha256"]},
                             rd1_root=RD1_ROOT, rd2_root=RD2_ROOT, rd3_root=RD3_ROOT, lines_sha256=lines, ckpt_seq=int(facts3["rd3_checkpoint_seq"]) + 1)
        out = run4.run_all4(sess, immutability=earlier_trees_immutability)
    finally:
        rep = sampler.stop()
        mrun.write_json(cfg.session_dir / "memory_summary.json", rep)
    left = wait_until_no_process(BATTLESHIP_IMAGE, timeout=60.0)
    mrun.write_json(cfg.session_dir / "leftover_processes.json", {"battleship_pids_after_the_run": left, "utc": utc()})
    print(json.dumps(out["rule"], indent=1, default=str)[:5000])
    if left:
        print(f"WARNING: BattleShip processes still alive after the run: {left}")
    return 0


def cmd_verify_run() -> int:
    import m8_rd4_report as rpt4

    rep = rpt4.verify_run4(RD4_ROOT, RD3_ROOT, RD2_ROOT, RD1_ROOT, SESSION)
    print(json.dumps(rep, indent=1, default=str))
    return 0 if rep["ok"] else 1


def cmd_report() -> int:
    import m8_rd4_report as rpt4

    print(json.dumps(rpt4.full_report4(RD4_ROOT, RD3_ROOT, RD2_ROOT, RD1_ROOT, SESSION), indent=1, default=str))
    return 0


def cmd_open_check() -> int:
    op = open_protocol4()
    print(json.dumps({k: v for k, v in op.items() if k not in ("overlay", "facts1", "facts2", "facts3")}, indent=1, default=str))
    return 0 if op["ok"] else 1


def cmd_status() -> int:
    st = RD4_ROOT / "sessions" / SESSION / "state.json"
    out = {"rd4_root_exists": RD4_ROOT.exists(), "approval_present": APPROVAL.is_file(), "state": json.loads(st.read_text(encoding="utf-8")) if st.is_file() else None}
    print(json.dumps(out, indent=1, default=str))
    return 0


def cmd_template() -> int:
    ident = identity()
    rec = dict(ident, approval="PENDING (a reviewer replaces this with APPROVED ... and fills the authorisation and the source snapshot entries; this command never writes the record)",
               revision=1, authorisation={"source": "<the user's message>", "text": ["<what is authorised, once>"]},
               source_snapshot={"dest": "D:\\BattleShip_source_snapshots\\<date>_m8_rd4", "snapshot_json_sha256": "<sha256>", "result": "PASS", "files": "<n>",
                                "git_head": ident["git_head"], "independent_verification": "<tool verify and an independent PowerShell re-hash>"},
               backup_coverage_before_approval="<combined coverage record>")
    print(json.dumps(rec, indent=1, default=str))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("status", "verify-run", "approval-template", "run", "report", "open-check"):
        sub.add_parser(n)
    p = sub.add_parser("preflight")
    p.add_argument("--skip-unit", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "status":
        return cmd_status()
    if a.cmd == "preflight":
        rep = preflight(run_unit=not a.skip_unit)
        print(json.dumps(rep, indent=1, default=str))
        return 0 if rep["ok"] else 1
    if a.cmd == "approval-template":
        return cmd_template()
    if a.cmd == "verify-run":
        return cmd_verify_run()
    if a.cmd == "report":
        return cmd_report()
    if a.cmd == "open-check":
        return cmd_open_check()
    return cmd_run()


if __name__ == "__main__":
    sys.exit(main())
