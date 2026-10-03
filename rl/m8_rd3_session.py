#!/usr/bin/env python3
"""M8-rd3 session driver: one second-continuation session of archive m8_rd_a1 (rd1 and rd2 as closed) under the unchanged `m8_rd_select_v2`.

    python rl/m8_rd3_session.py status
    python rl/m8_rd3_session.py open-check               # zero ticks, writes nothing: R1-R5 against rd1's and rd2's trees
    python rl/m8_rd3_session.py preflight [--skip-unit]  # no game: tests, pins, D: coverage, readiness, approval
    python rl/m8_rd3_session.py approval-template        # prints the record a reviewer would write (never writes it)
    python rl/m8_rd3_session.py run                      # refused unless the preflight passes, including the approval
    python rl/m8_rd3_session.py verify-run               # read-only post-run verification
    python rl/m8_rd3_session.py report                   # the registered diagnostics beside rd2's and rd1's reference values

Design: docs/rl_m8_rd3_decisions_2026-10-02.md (the user's decisions for rd3 and the mechanical readings); the implementation record is docs/rl_m8_rd3_implementation.md. SCOPE: second
continuation of archive m8_rd_a1 (rd1 and rd2 as closed) under m8_rd_select_v2; one session, one set of keyed draws; no control arm; not a policy result, not a learning result, not a
comparison of v2 with v1.

rd1's tree (runs/m8_rd/) and rd2's tree (runs/m8_rd_rd2/) are only read; rd3 writes only under runs/m8_rd_rd3/. Light top-level imports only (spawned workers re-import this script).
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
import m8_rd3_rule as rule3  # noqa: E402
import m8_rd3_run as run3  # noqa: E402
import m8_rd3_select as s3  # noqa: E402

REPO_ROOT = ses1.REPO_ROOT
RL = ses1.RL
RUNS = ses1.RUNS
LOGS = ses1.LOGS
RD1_ROOT = RUNS / "m8_rd"
RD2_ROOT = RUNS / "m8_rd_rd2"
RD3_ROOT = RUNS / "m8_rd_rd3"
APPROVAL = REPO_ROOT / "docs" / "rl_m8_rd3_approval.json"
BACKUP_ROOT = ses1.BACKUP_ROOT
INCREMENT_RD1 = BACKUP_ROOT / rs.RD1_INCREMENT_NAME
INCREMENT_RD2 = BACKUP_ROOT / r3.RD2_INCREMENT_NAME
SNAPSHOT_ROOT = ses1.SNAPSHOT_ROOT
SESSION = "rd3"
GATE = "m8_rd3"
ARCHIVE_ID = "m8_rd_a1"
SCOPE = rule3.SCOPE
N_WORKERS = 5
RD1_EXPECT: Mapping[str, Any] = rs.RD1_FACTS
RD2_EXPECT: Mapping[str, Any] = r3.RD2_FACTS
CHECK_EXPECTED_OVERLAY = True                    # the registered closing-overlay figures (off only in the tests on synthetic trees)
EXECUTABLE = ses1.EXECUTABLE
EXE_DIR = ses1.EXE_DIR
FLAGS_EXPLORE = ses1.FLAGS_EXPLORE
FLAGS_VERIFY = ses1.FLAGS_VERIFY
READINESS = ses1.READINESS

NEW_CODE_FILES = ("m8_rd3_select.py", "m8_rd3_resume.py", "m8_rd3_run.py", "m8_rd3_session.py", "m8_rd3_rule.py", "m8_rd3_report.py", "m8_rd3_snapshot.py", "m8_rd3_tests.py")
CODE_FILES = tuple(ses2.CODE_FILES) + NEW_CODE_FILES
DOC_FILES = tuple(ses2.DOC_FILES) + ("docs/rl_m8_rd2_results_2026-10-02.md", "docs/rl_m8_rd3_decisions_2026-10-02.md", "docs/rl_m8_rd3_implementation.md")
RULE_SELF_TESTS = (("rule_self_test_rd1", "m8_rd_rule.py"), ("rule_self_test_rd2", "m8_rd2_rule.py"), ("rule_self_test_rd3", "m8_rd3_rule.py"))


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256_file(p: Path) -> str:
    return mw.sha256_file(Path(p))


def run_config(root: Optional[Path] = None, **over: Any) -> mrun.RunConfig:
    """The registered budgets and caps (decision 3, as rd2): exploration 50 min or 6,000,000 native ticks, valid from 2,000,000; the open phase (P1 and 16 identity replays) 70,000
    ticks / 4 min; verification 400,000 ticks / 6 min; a 60-minute hard cap from P1; memory caps as rd1's."""
    kw: Dict[str, Any] = dict(session_id=SESSION, archive_id=ARCHIVE_ID, n_workers=N_WORKERS)
    kw.update(over)
    return ses2.run_config(root=Path(root) if root is not None else RD3_ROOT, **kw)


def caps() -> Dict[str, Any]:
    cfg = run_config()
    return {"exploration_tick_cap": cfg.arm_cap("T"), "min_exploration_ticks": cfg.min_arm_ticks, "open_tick_cap": cfg.p1_tick_cap,
            "replay_tick_cap": cfg.replay_tick_cap, "wall_caps_s": {k: v for k, v in cfg.wall_caps_s.items() if k != "C"},
            "global_cap_s": cfg.global_cap_s, "checkpoint_every_s": cfg.checkpoint_every_s, "memory_caps_mb": dict(cfg.memory_caps_mb),
            "memory_sample_s": ses1.MEMORY_SAMPLE_S, "max_battleship_processes": cfg.max_battleship_processes,
            "lifecycle_failure_limit": cfg.lifecycle_failure_limit, "verify_threads": cfg.verify_threads, "identity_k": cfg.identity_k,
            "job_timeout_s": mrun.JOB_TIMEOUT_S, "wall_cap_grace_s": mrun.WALL_CAP_GRACE_S}


# -- identity and approval ---------------------------------------------------------------------------------------------------------------


def base_identity3(rd1_dir: Optional[Path] = None, rd2_dir: Optional[Path] = None, inc1: Optional[Path] = None, inc2: Optional[Path] = None) -> Dict[str, Any]:
    """What rd3 starts from: rd1's base identity (as rd2 pinned it) and rd2's closing archive, close record and D: increment."""
    rd1_dir = RD1_ROOT if rd1_dir is None else rd1_dir                    # resolved at call time (the tests patch the module paths)
    rd2_dir = RD2_ROOT if rd2_dir is None else rd2_dir
    inc1 = INCREMENT_RD1 if inc1 is None else inc1
    inc2 = INCREMENT_RD2 if inc2 is None else inc2
    meta = json.loads((Path(rd2_dir) / "archive" / "archive_meta.json").read_text(encoding="utf-8"))
    close_p = Path(rd2_dir) / "sessions" / "rd2" / "close.json"
    inc_m = Path(inc2) / "manifest.tsv.gz"
    return {"rd1": ses2.base_identity(rd1_dir, inc1),
            "rd2_archive_files_sha256": {n: march.sha256_file(Path(rd2_dir) / "archive" / n) for n in march.DATA_FILES},
            "rd2_close_record_sha256": sha256_file(close_p) if close_p.is_file() else None, "rd2_increment": Path(inc2).name,
            "rd2_increment_manifest_sha256": sha256_file(inc_m) if inc_m.is_file() else None, "rd2_checkpoint_seq": meta.get("checkpoint_seq"),
            "rd2_session_event": next((e for e in _events(Path(rd2_dir) / "archive") if e.get("ev") == "session"), None),
            "rd2_pins": meta.get("pins"), "pin_tick0_digest": (meta.get("pin_tick0") or {}).get("digest"), "lines_sha256": (meta.get("pin_tick0") or {}).get("lines"),
            "rd2_first_iteration": meta.get("first_iteration"), "first_rd3_iteration": r3.RD2_FACTS["first_rd3_iteration"]}


def _events(archive_dir: Path) -> List[Dict[str, Any]]:
    out = []
    for ln in (Path(archive_dir) / "events.jsonl").read_text(encoding="utf-8").splitlines():
        if '"session"' in ln:
            out.append(json.loads(ln))
    return out


def identity() -> Dict[str, Any]:
    dr = ses1.d_records_digest()
    base = base_identity3()
    lines = str(base["lines_sha256"])
    ov = r3.closing_overlay(RD2_ROOT, expect=(r3.EXPECTED_CLOSE_OVERLAY if CHECK_EXPECTED_OVERLAY else {}))
    contracts = ses2.contract_digests2(lines)
    return {"gate": GATE, "scope": SCOPE, "milestone": "M8", "archive_id": ARCHIVE_ID, "session": SESSION, "rule": rule3.RULE_ID, "rule_sha256": rule3.rule_digest(),
            "contracts": contracts,
            "key_strings": {"select_rd1": "m8_rd|<archive_id>|select|<iteration> (iterations 0..2174, rd1)",
                            "select_rd2": f"m8_rd|<archive_id>{s3.DRAW_SUFFIX_RD2}|select|<iteration> (iterations 2175..6211, rd2)",
                            "select_rd3": f"m8_rd|<archive_id>{s3.DRAW_SUFFIX}|select|<iteration> (iterations from 6212)",
                            "explore_rd3": f"m8_rd|<archive_id>{s3.DRAW_SUFFIX}|explore|<iteration>|<decision index>",
                            "identity_open": "m8_rd|<archive_id>|identity_open|rd3|<cell id>", "identity_close": "m8_rd|<archive_id>|identity_close|rd3|<cell id>"},
            "draws_sha256": s3.draws_digest(), "rd3_session_event_digest": contracts["m8_rd_select_v2"],
            "executable_sha256": sha256_file(EXECUTABLE) if EXECUTABLE.is_file() else None, "runtime_files": ses1.runtime_pins(),
            "flags": {"explore": FLAGS_EXPLORE, "verify": FLAGS_VERIFY}, "p1": ses1.p1_pins(), "caps": caps(), "workers": N_WORKERS,
            "burst_words": mx.BURST_WORDS, "horizon": mcell.HORIZON, "readiness": READINESS, "base": base,
            "open_overlay": {"sha256": ov["sha256"], "counts_sha256": _norm_sha(ov["counts"]), "expected_counts": r3.EXPECTED_CLOSE_OVERLAY},
            "budgets": {"exploration": "50 min or 6,000,000 native ticks, valid from 2,000,000", "open": "70,000 ticks / 4 min",
                        "verification": "400,000 ticks / 6 min", "hard_cap": "60 min from P1"},
            "code": {f"rl/{f}": sha256_file(RL / f) for f in CODE_FILES if (RL / f).is_file()},
            "docs_sha256": {f: sha256_file(REPO_ROOT / f) for f in DOC_FILES if (REPO_ROOT / f).is_file()},
            "git_head": ses1.git("rev-parse", "HEAD").strip(), "d_records": {"folders": dr["folders"], "digest": dr["digest"]}}


def _norm_sha(v: Any) -> str:
    import hashlib

    return hashlib.sha256(json.dumps(v, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def approval_status(path: Optional[Path] = None, want: Optional[Mapping[str, Any]] = None) -> Tuple[bool, str]:
    return ses1.approval_status(Path(APPROVAL if path is None else path), want if want is not None else identity())


# -- the open protocol (zero native ticks) -----------------------------------------------------------------------------------------------------


def open_protocol3(rd1_dir: Optional[Path] = None, rd2_dir: Optional[Path] = None, inc1: Optional[Path] = None, inc2: Optional[Path] = None, *,
                   expect1: Optional[Mapping[str, Any]] = None, expect2: Optional[Mapping[str, Any]] = None, check_overlay: Optional[bool] = None,
                   live_pins: Optional[Callable[[], Mapping[str, Any]]] = None, floor_min: Optional[float] = None, with_audit: bool = True) -> Dict[str, Any]:
    """R1-R5 at two levels: immutability of both trees, the archive facts and audits (rd1's with rd1's own code, rd2's with rd2's own code), the pins, the closing overlay of rd2's
    archive computed twice and its figures. Writes nothing."""
    expect1 = RD1_EXPECT if expect1 is None else expect1
    expect2 = RD2_EXPECT if expect2 is None else expect2
    check_overlay = CHECK_EXPECTED_OVERLAY if check_overlay is None else check_overlay
    rd1_dir = Path(RD1_ROOT if rd1_dir is None else rd1_dir)             # resolved at call time (the tests patch the module paths)
    rd2_dir = Path(RD2_ROOT if rd2_dir is None else rd2_dir)
    inc1 = INCREMENT_RD1 if inc1 is None else inc1
    inc2 = INCREMENT_RD2 if inc2 is None else inc2
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

    imm1 = guard("R1 (rd1)", lambda: rs.rd1_immutability(rd1_dir, Path(inc1)), {"ok": False, "problems": []})
    out["R1_rd1_immutability"] = {k: imm1.get(k) for k in keys}
    problems += [f"R1 (rd1): {p}" for p in imm1["problems"]]
    imm2 = guard("R1 (rd2)", lambda: rs.rd1_immutability(rd2_dir, Path(inc2)), {"ok": False, "problems": []})
    out["R1_rd2_immutability"] = {k: imm2.get(k) for k in keys}
    problems += [f"R1 (rd2): {p}" for p in imm2["problems"]]
    # the registered anchors of both increments (only the keys a registered fact set carries are checked: the synthetic trees carry none of them)
    for who, imm, E in (("rd1", imm1, expect1), ("rd2", imm2, expect2)):
        for ek, ik in (("files", "files"), ("bytes", "bytes"), ("increment_manifest_sha256", "manifest_sha256")):
            if ek in E and imm.get(ik) != E[ek]:
                problems.append(f"R1 ({who}): the increment's {ik} {imm.get(ik)!r} differs from the registered {E[ek]!r}")
    if expect1 is rs.RD1_FACTS and imm1.get("manifest_sha256") != rs.RD1_INCREMENT_MANIFEST_SHA256:
        problems.append(f"R1 (rd1): the increment's manifest {imm1.get('manifest_sha256')!r} differs from the registered {rs.RD1_INCREMENT_MANIFEST_SHA256!r}")
    facts1 = guard("R2/R4 (rd1)", lambda: rs.rd1_archive_facts(rd1_dir, expect1), {"ok": False, "problems": []})
    out["R2_R4_rd1_archive"] = {k: facts1.get(k) for k in ("ok", "checkpoints", "counts", "dispatch_iterations", "audit", "select_digest", "close_record_sha256")}
    problems += [f"R2/R4 (rd1): {p}" for p in facts1.get("problems", [])]
    lines = (facts1.get("pin_tick0") or {}).get("lines")
    facts2 = guard("R2/R4 (rd2)", lambda: r3.rd2_archive_facts(rd1_dir, rd2_dir, lines, expect2, with_audit=with_audit), {"ok": False, "problems": []})
    out["R2_R4_rd2_archive"] = {k: facts2.get(k) for k in ("ok", "checkpoints", "counts", "dispatch_iterations", "audit", "close_record_sha256", "session_event", "digest_recomputed",
                                                           "diag2", "first_rd3_iteration", "rd2_checkpoint_seq")}
    problems += [f"R2/R4 (rd2): {p}" for p in facts2.get("problems", [])]
    out["facts1"], out["facts2"] = facts1, facts2
    if facts1.get("pin_tick0") != facts2.get("pin_tick0"):
        problems.append("R2: rd2's pinned tick-0 record differs from rd1's")
    if facts1.get("pins") is not None and facts2.get("pins") is not None:
        now = dict(live_pins() if live_pins else {"executable_sha256": sha256_file(EXECUTABLE), "runtime_files": ses1.runtime_pins(),
                                                  "contracts": ses2.contract_digests2(str(lines)), "flags": {"explore": FLAGS_EXPLORE, "verify": FLAGS_VERIFY}})
        frozen_dir = rd1_dir / "archive" / "runtime"
        pp2 = rs.pin_problems(facts2["pins"], now, frozen_dir, facts2["pins"].get("frozen_sha256") or {})
        now1 = dict(now, contracts={k: v for k, v in dict(now["contracts"]).items() if k != "m8_rd_select_v2"})      # rd1's pins predate m8_rd_select_v2
        pp1 = rs.pin_problems(facts1["pins"], now1, frozen_dir, facts1["pins"].get("frozen_sha256") or {})
        exe_only = pp2 == ["pin executable_sha256 differs"]
        out["R3_pins"] = {"problems": pp2, "rd1_problems": pp1, "executable_only": exe_only}
        if exe_only:
            problems.append("R3: only the executable differs from the archive's pin: not an exploration session (a full re-verification of every carried cell is its own authorised session)")
        else:
            problems += [f"R3: {p}" for p in pp2]
        problems += [f"R3 (rd1's pins): {p}" for p in pp1]
    else:
        out["R3_pins"] = {"problems": ["the archives' pins could not be read"], "rd1_problems": [], "executable_only": False}
        problems.append("R3: the archives' pins could not be read")
    ov = guard("R5", lambda: r3.closing_overlay(rd2_dir, expect=(r3.EXPECTED_CLOSE_OVERLAY if check_overlay else {}), floor_min=floor_min),
               {"ok": False, "problems": [], "sha256": None, "counts": {}, "rows": [], "bytes": b""})
    out["R5_overlay"] = {"ok": ov["ok"], "sha256": ov["sha256"], "counts": ov["counts"], "stored_close_counts_equal": ov["counts"] == ov.get("stored_close_counts")}
    problems += [f"R5: {p}" for p in ov["problems"]]
    out["overlay"] = ov
    out["ok"] = not problems
    return out


# -- preflight ---------------------------------------------------------------------------------------------------------------------------------


def _run_unit_suites() -> Tuple[Dict[str, Any], List[str]]:
    """rd3's own suite (deterministic by construction; it contains the explicit lists of the deterministic pure tests of rd1 and rd2) and the three rule self-tests. rd1's and rd2's
    whole suites are NOT run: they contain asynchronous tests (rd2's `cmd_run_with_fake_game` is the known flaky one)."""
    problems: List[str] = []
    rep: Dict[str, Any] = {}
    r = subprocess.run([sys.executable, "-B", str(RL / "m8_rd3_tests.py"), "unit"], capture_output=True, text=True, cwd=REPO_ROOT)
    rep["unit_suite_rd3"] = (r.stdout.strip().splitlines() or [r.stderr[-300:]])[-1:]
    if r.returncode != 0:
        problems.append("unit_suite_rd3 failed")
    for key, f in RULE_SELF_TESTS:
        r = subprocess.run([sys.executable, "-B", str(RL / f), "self-test"], capture_output=True, text=True, cwd=REPO_ROOT)
        rep[key] = (r.stdout.strip().splitlines() or [r.stderr[-300:]])[-1:]
        if r.returncode != 0:
            problems.append(f"{key} failed")
    return rep, problems


def preflight(*, run_unit: bool = True) -> Dict[str, Any]:
    problems: List[str] = []
    rep: Dict[str, Any] = {"utc": utc(), "scope": SCOPE}
    if RD3_ROOT.exists():
        problems.append(f"{RD3_ROOT.relative_to(REPO_ROOT)} exists (never overwritten)")
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
    op = open_protocol3()
    rep["open_protocol"] = {k: v for k, v in op.items() if k not in ("overlay", "facts1", "facts2", "problems")}
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


def build_real_env3(cfg: mrun.RunConfig, frozen_dir: Path, frozen: Mapping[str, str], pins: Mapping[str, Any], sampler: Any = None, *, executable: Optional[Path] = None,
                    flags_explore: Optional[Mapping[str, str]] = None, flags_verify: Optional[Mapping[str, str]] = None) -> mrun.RunEnv:
    """rd2's real environment (the frozen runtime is rd1's, read in place; never re-frozen from the live configuration), with the write guard of every worker over BOTH earlier trees."""
    env = ses2.build_real_env2(cfg, frozen_dir, frozen, pins, sampler, executable=executable if executable is not None else EXECUTABLE,
                               flags_explore=flags_explore if flags_explore is not None else FLAGS_EXPLORE,
                               flags_verify=flags_verify if flags_verify is not None else FLAGS_VERIFY, rd1_root=RD1_ROOT)
    inner = env.worker_spec
    protected = [str(RD1_ROOT), str(RD2_ROOT)]

    def worker_spec(rank: int, c: mrun.RunConfig) -> Dict[str, Any]:
        spec = inner(rank, c)
        spec["protected_roots"] = list(protected)
        return spec

    env.worker_spec = worker_spec
    return env


def earlier_trees_immutability() -> Dict[str, Any]:
    """R1 for both earlier trees (rd1's and rd2's files each equal their D: increment): the callable the close checks run."""
    a = rs.rd1_immutability(RD1_ROOT, INCREMENT_RD1)
    b = rs.rd1_immutability(RD2_ROOT, INCREMENT_RD2)
    return {"ok": bool(a.get("ok") and b.get("ok")), "problems": [f"rd1: {p}" for p in a.get("problems", [])] + [f"rd2: {p}" for p in b.get("problems", [])],
            "rd1": {k: a.get(k) for k in ("ok", "files", "manifest_sha256", "bytes")}, "rd2": {k: b.get(k) for k in ("ok", "files", "manifest_sha256", "bytes")}}


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
    w2.WriteGuard.install([RD1_ROOT, RD2_ROOT])
    approval = json.loads(APPROVAL.read_text(encoding="utf-8"))
    # S0 (outside the clock, zero native ticks): the open protocol once more, then materialise rd3's tree
    op = open_protocol3()
    if not op["ok"]:
        print(json.dumps({k: v for k, v in op.items() if k not in ("overlay", "facts1", "facts2")}, indent=1, default=str))
        print("refused: the open protocol failed; nothing was created")
        return 2
    facts1, facts2 = op["facts1"], op["facts2"]
    meta1 = json.loads((RD1_ROOT / "archive" / "archive_meta.json").read_text(encoding="utf-8"))
    pins1 = meta1["pins"]
    frozen_dir = RD1_ROOT / "archive" / "runtime"
    pins = {"executable_sha256": approval["executable_sha256"], "runtime_files": dict(pins1["runtime_files"]), "frozen_sha256": dict(pins1["frozen_sha256"]),
            "contracts": approval["contracts"], "flags": approval["flags"], "archive_id": ARCHIVE_ID, "approval_sha256": sha256_file(APPROVAL),
            "git_head": approval["git_head"], "rule_sha256": approval["rule_sha256"], "p1": approval["p1"]}
    cfg = run_config(**dict(overrides or {}))
    lines = str(facts2["lines_sha256"])
    a3 = r3.materialise3(RD2_ROOT, cfg.root, facts=facts2, overlay=op["overlay"], lines_sha256=lines,
                         meta_extra={"pins": pins, "horizon": cfg.horizon, "burst_words": cfg.burst_words, "ticks": {}, "ledger_T": {"ticks": 0, "jobs": 0},
                                     "pin_tick0": facts2["pin_tick0"], "first_new_cell": len(op["overlay"]["rows"])},
                         increment_manifest_sha256=op["R1_rd2_immutability"]["manifest_sha256"], utc=utc())
    import m8_rd3_report as rpt3

    open_probs = rpt3.open_selection_probabilities(a3)
    cfg.session_dir.mkdir(parents=True)
    shutil.copyfile(APPROVAL, cfg.session_dir / "approval_copy.json")
    mrun.write_json(cfg.session_dir / "open.json", {
        "utc": utc(), "pins": pins, "preflight": {k: pf.get(k) for k in ("executable_sha256", "git_head", "readiness", "backup", "approval", "source_snapshot", "unit_suite_rd3",
                                                                       "rule_self_test_rd1", "rule_self_test_rd2", "rule_self_test_rd3")},
        "open_protocol": {k: v for k, v in op.items() if k not in ("overlay", "facts1", "facts2")}, "caps": caps(), "wall_top_selection_at_the_open": open_probs,
        "identity": {k: v for k, v in identity().items() if k != "code"}})
    sampler = ses1.make_sampler(cfg.session_dir / "memory_tree.jsonl", cfg.memory_caps_mb)
    sampler.start()
    env = build_real_env3(cfg, frozen_dir, pins1["frozen_sha256"], pins, sampler)
    try:
        sess = run3.Session3(cfg, env, archive=a3, archive_pin=facts2["pin_tick0"], base_info={"rd1_root": str(RD1_ROOT), "rd2_root": str(RD2_ROOT),
                                                                                              "overlay_sha256": op["overlay"]["sha256"]},
                             rd1_root=RD1_ROOT, rd2_root=RD2_ROOT, lines_sha256=lines, ckpt_seq=int(facts2["rd2_checkpoint_seq"]) + 1)
        out = run3.run_all3(sess, immutability=earlier_trees_immutability)
    finally:
        rep = sampler.stop()
        mrun.write_json(cfg.session_dir / "memory_summary.json", rep)
    left = wait_until_no_process(BATTLESHIP_IMAGE, timeout=60.0)
    mrun.write_json(cfg.session_dir / "leftover_processes.json", {"battleship_pids_after_the_run": left, "utc": utc()})
    print(json.dumps(out["rule"], indent=1, default=str)[:4000])
    if left:
        print(f"WARNING: BattleShip processes still alive after the run: {left}")
    return 0


def cmd_verify_run() -> int:
    import m8_rd3_report as rpt3

    rep = rpt3.verify_run3(RD3_ROOT, RD2_ROOT, RD1_ROOT, SESSION)
    print(json.dumps(rep, indent=1, default=str))
    return 0 if rep["ok"] else 1


def cmd_report() -> int:
    import m8_rd3_report as rpt3

    print(json.dumps(rpt3.full_report3(RD3_ROOT, RD2_ROOT, RD1_ROOT, SESSION), indent=1, default=str))
    return 0


def cmd_open_check() -> int:
    op = open_protocol3()
    print(json.dumps({k: v for k, v in op.items() if k not in ("overlay", "facts1", "facts2")}, indent=1, default=str))
    return 0 if op["ok"] else 1


def cmd_status() -> int:
    st = RD3_ROOT / "sessions" / SESSION / "state.json"
    out = {"rd3_root_exists": RD3_ROOT.exists(), "approval_present": APPROVAL.is_file(), "state": json.loads(st.read_text(encoding="utf-8")) if st.is_file() else None}
    print(json.dumps(out, indent=1, default=str))
    return 0


def cmd_template() -> int:
    ident = identity()
    rec = dict(ident, approval="PENDING (a reviewer replaces this with APPROVED ... and fills the authorisation and the source snapshot entries; this command never writes the record)",
               revision=1, authorisation={"source": "<the user's message>", "text": ["<what is authorised, once>"]},
               source_snapshot={"dest": "D:\\BattleShip_source_snapshots\\<date>_m8_rd3", "snapshot_json_sha256": "<sha256>", "result": "PASS", "files": "<n>",
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
