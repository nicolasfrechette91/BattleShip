#!/usr/bin/env python3
"""M8-rd2 session driver: one continuation session of the rd1 archive under `m8_rd_select_v2`.

    python rl/m8_rd2_session.py status
    python rl/m8_rd2_session.py open-check               # zero ticks, writes nothing: R1-R5 against rd1's tree and archive
    python rl/m8_rd2_session.py preflight [--skip-unit]  # no game: tests, pins, D: coverage, readiness, approval
    python rl/m8_rd2_session.py approval-template        # prints the record a reviewer would write (never writes it)
    python rl/m8_rd2_session.py run                      # refused unless the preflight passes, including the approval
    python rl/m8_rd2_session.py verify-run               # read-only post-run verification
    python rl/m8_rd2_session.py report                   # the registered diagnostics beside rd1's reference values

Design: docs/rl_m8_rd_continuation_proposal_2026-10-02.md (frozen) as decided in docs/rl_m8_rd2_decisions_2026-10-02.md; the
implementation record is docs/rl_m8_rd2_implementation.md. SCOPE: continuation of archive m8_rd_a1 under m8_rd_select_v2; one
session, one set of keyed draws; no control arm; not a policy result, not a learning result, not a comparison of v2 with v1.

rd1's tree (runs/m8_rd/) is only read; rd2 writes only under runs/m8_rd_rd2/. Light top-level imports only (spawned workers
re-import this script).
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
import m8_rd_claims as mclaims  # noqa: E402
import m8_rd_explore as mx  # noqa: E402
import m8_rd_resume as rs  # noqa: E402
import m8_rd_run as mrun  # noqa: E402
import m8_rd_select2 as s2  # noqa: E402
import m8_rd_session as ses1  # noqa: E402
import m8_rd_worker as mw  # noqa: E402
import m8_rd2_rule as rule2  # noqa: E402
import m8_rd2_run as run2  # noqa: E402
import m8_rd2_worker as w2  # noqa: E402

REPO_ROOT = ses1.REPO_ROOT
RL = ses1.RL
RUNS = ses1.RUNS
LOGS = ses1.LOGS
RD1_ROOT = RUNS / "m8_rd"
RD2_ROOT = RUNS / "m8_rd_rd2"
APPROVAL = REPO_ROOT / "docs" / "rl_m8_rd2_approval.json"
BACKUP_ROOT = ses1.BACKUP_ROOT
INCREMENT_RD1 = BACKUP_ROOT / rs.RD1_INCREMENT_NAME
SNAPSHOT_ROOT = ses1.SNAPSHOT_ROOT
SESSION = "rd2"
GATE = "m8_rd2"
ARCHIVE_ID = "m8_rd_a1"
SCOPE = rule2.SCOPE
N_WORKERS = 5
RD1_EXPECT: Mapping[str, Any] = rs.RD1_FACTS
CHECK_EXPECTED_OVERLAY = True                    # the proposal's section 2.4(d) figures (off only in the tests on synthetic archives)
EXECUTABLE = ses1.EXECUTABLE
EXE_DIR = ses1.EXE_DIR
FLAGS_EXPLORE = ses1.FLAGS_EXPLORE
FLAGS_VERIFY = ses1.FLAGS_VERIFY
READINESS = ses1.READINESS

NEW_CODE_FILES = ("m8_rd_select2.py", "m8_rd_resume.py", "m8_rd2_worker.py", "m8_rd2_run.py", "m8_rd2_session.py", "m8_rd2_rule.py",
                  "m8_rd2_report.py", "m8_rd2_snapshot.py", "m8_rd2_tests.py")
CODE_FILES = tuple(ses1.CODE_FILES) + NEW_CODE_FILES
DOC_FILES = ("docs/rl_m8_rd_proposal_2026-10-01.md", "docs/rl_m8_rd_amendment_2026-10-02.md", "docs/rl_m8_rd_implementation.md",
             "docs/rl_m8_rd1_results_2026-10-02.md", "docs/rl_m8_rd1_diagnosis_2026-10-02.md",
             "docs/rl_m8_rd_continuation_proposal_2026-10-02.md", "docs/rl_m8_rd2_decisions_2026-10-02.md",
             "docs/rl_m8_rd2_implementation.md")


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256_file(p: Path) -> str:
    return mw.sha256_file(Path(p))


def run_config(root: Optional[Path] = None, **over: Any) -> mrun.RunConfig:
    """The registered budgets and caps (decision 7): exploration 50 min or 6,000,000 native ticks, valid from 2,000,000; the open phase
    (P1 and 16 identity replays) 70,000 ticks / 4 min; verification 400,000 ticks / 6 min; a 60-minute hard cap from P1; memory caps as
    rd1's."""
    kw: Dict[str, Any] = dict(root=Path(root) if root is not None else RD2_ROOT, session_id=SESSION, archive_id=ARCHIVE_ID,
                              n_workers=N_WORKERS, arm_tick_cap=6_000_000, arm_caps={"T": 6_000_000}, min_arm_ticks=2_000_000,
                              p1_tick_cap=70_000, replay_tick_cap=400_000,
                              wall_caps_s={"p1": 240.0, "T": 3000.0, "C": 0.0, "verify": 360.0}, global_cap_s=3600.0)
    kw.update(over)
    return mrun.RunConfig(**kw)


def caps() -> Dict[str, Any]:
    cfg = run_config()
    return {"exploration_tick_cap": cfg.arm_cap("T"), "min_exploration_ticks": cfg.min_arm_ticks, "open_tick_cap": cfg.p1_tick_cap,
            "replay_tick_cap": cfg.replay_tick_cap, "wall_caps_s": {k: v for k, v in cfg.wall_caps_s.items() if k != "C"},
            "global_cap_s": cfg.global_cap_s, "checkpoint_every_s": cfg.checkpoint_every_s, "memory_caps_mb": dict(cfg.memory_caps_mb),
            "memory_sample_s": ses1.MEMORY_SAMPLE_S, "max_battleship_processes": cfg.max_battleship_processes,
            "lifecycle_failure_limit": cfg.lifecycle_failure_limit, "verify_threads": cfg.verify_threads, "identity_k": cfg.identity_k,
            "job_timeout_s": mrun.JOB_TIMEOUT_S, "wall_cap_grace_s": mrun.WALL_CAP_GRACE_S}


# -- identity and approval ---------------------------------------------------------------------------------------------------------------


def contract_digests2(lines_sha256: str) -> Dict[str, str]:
    import m7q_status_table as st

    d = dict(ses1.contract_digests())
    d["m8_rd_select_v2"] = s2.select2_contract_digest(st.load_table()["sha256"], lines_sha256)
    return d


def base_identity(rd1_root: Optional[Path] = None, increment: Optional[Path] = None) -> Dict[str, Any]:
    rd1_root = RD1_ROOT if rd1_root is None else rd1_root            # resolved at call time (the tests patch the module paths)
    increment = INCREMENT_RD1 if increment is None else increment
    meta = json.loads((Path(rd1_root) / "archive" / "archive_meta.json").read_text(encoding="utf-8"))
    close_p = Path(rd1_root) / "sessions" / "rd1" / "close.json"
    inc_m = Path(increment) / "manifest.tsv.gz"
    return {"rd1_archive_files_sha256": {n: march.sha256_file(Path(rd1_root) / "archive" / n) for n in march.DATA_FILES},
            "rd1_close_record_sha256": sha256_file(close_p) if close_p.is_file() else None, "rd1_increment": Path(increment).name,
            "rd1_increment_manifest_sha256": sha256_file(inc_m) if inc_m.is_file() else None, "rd1_checkpoint_seq": meta.get("checkpoint_seq"),
            "pin_tick0_digest": (meta.get("pin_tick0") or {}).get("digest"), "lines_sha256": (meta.get("pin_tick0") or {}).get("lines"),
            "rd1_pins": meta.get("pins"), "rd1_first_rd2_iteration": rs.RD1_FACTS["first_rd2_iteration"]}


def identity() -> Dict[str, Any]:
    dr = ses1.d_records_digest()
    base = base_identity()
    lines = str(base["lines_sha256"])
    ov = rs.build_overlay(RD1_ROOT / "archive")
    return {"gate": GATE, "scope": SCOPE, "milestone": "M8", "archive_id": ARCHIVE_ID, "session": SESSION, "rule": rule2.RULE_ID,
            "rule_sha256": rule2.rule_digest(), "contracts": contract_digests2(lines),
            "key_strings": {"select_rd1": "m8_rd|<archive_id>|select|<iteration> (iterations 0..2174, rd1)",
                            "select_v2": f"m8_rd|<archive_id>{s2.DRAW_SUFFIX}|select|<iteration> (iterations from 2175)",
                            "explore_v2": f"m8_rd|<archive_id>{s2.DRAW_SUFFIX}|explore|<iteration>|<decision index>",
                            "identity_open": "m8_rd|<archive_id>|identity_open|rd2|<cell id>",
                            "identity_close": "m8_rd|<archive_id>|identity_close|rd2|<cell id>"},
            "executable_sha256": sha256_file(EXECUTABLE) if EXECUTABLE.is_file() else None, "runtime_files": ses1.runtime_pins(),
            "flags": {"explore": FLAGS_EXPLORE, "verify": FLAGS_VERIFY}, "p1": ses1.p1_pins(), "caps": caps(), "workers": N_WORKERS,
            "burst_words": mx.BURST_WORDS, "horizon": mcell.HORIZON, "readiness": READINESS, "base": base,
            "open_overlay": {"sha256": ov["sha256"], "expected_counts": rs.EXPECTED_OPEN},
            "budgets": {"exploration": "50 min or 6,000,000 native ticks, valid from 2,000,000", "open": "70,000 ticks / 4 min",
                        "verification": "400,000 ticks / 6 min", "hard_cap": "60 min from P1"},
            "code": {f"rl/{f}": sha256_file(RL / f) for f in CODE_FILES if (RL / f).is_file()},
            "docs_sha256": {f: sha256_file(REPO_ROOT / f) for f in DOC_FILES if (REPO_ROOT / f).is_file()},
            "git_head": ses1.git("rev-parse", "HEAD").strip(), "d_records": {"folders": dr["folders"], "digest": dr["digest"]}}


def approval_status(path: Optional[Path] = None, want: Optional[Mapping[str, Any]] = None) -> Tuple[bool, str]:
    return ses1.approval_status(Path(APPROVAL if path is None else path), want if want is not None else identity())


# -- the open protocol (zero native ticks) -------------------------------------------------------------------------------------------------


def open_protocol(rd1_root: Optional[Path] = None, increment: Optional[Path] = None, *, expect: Optional[Mapping[str, Any]] = None,
                  check_overlay: Optional[bool] = None, live_pins: Optional[Callable[[], Mapping[str, Any]]] = None,
                  floor_min: Optional[float] = None) -> Dict[str, Any]:
    """R1-R5: immutability, the archive's own facts and audit, the pins, the overlay computed twice and its figures. Writes nothing."""
    expect = RD1_EXPECT if expect is None else expect
    check_overlay = CHECK_EXPECTED_OVERLAY if check_overlay is None else check_overlay
    rd1_root = Path(RD1_ROOT if rd1_root is None else rd1_root)           # resolved at call time (the tests patch the module paths)
    increment = INCREMENT_RD1 if increment is None else increment
    problems: List[str] = []
    out: Dict[str, Any] = {"problems": problems}
    imm = rs.rd1_immutability(rd1_root, Path(increment))
    out["R1_rd1_immutability"] = {k: imm.get(k) for k in ("ok", "files", "manifest_files", "manifest_sha256", "bytes", "increment_record")}
    problems += [f"R1: {p}" for p in imm["problems"]]
    facts = rs.rd1_archive_facts(rd1_root, expect)
    out["R2_R4_archive"] = {k: facts.get(k) for k in ("ok", "checkpoints", "counts", "dispatch_iterations", "audit", "select_digest", "close_record_sha256")}
    problems += [f"R2/R4: {p}" for p in facts.get("problems", [])]
    out["facts"] = facts
    if facts.get("pins") is not None:
        now = dict(live_pins() if live_pins else {"executable_sha256": sha256_file(EXECUTABLE), "runtime_files": ses1.runtime_pins(),
                                                  "contracts": ses1.contract_digests(),
                                                  "flags": {"explore": FLAGS_EXPLORE, "verify": FLAGS_VERIFY}})
        pp = rs.pin_problems(facts["pins"], now, rd1_root / "archive" / "runtime", facts["pins"].get("frozen_sha256") or {})
        exe_only = pp == ["pin executable_sha256 differs"]
        out["R3_pins"] = {"problems": pp, "executable_only": exe_only}
        if exe_only:
            problems.append("R3: only the executable differs from the archive's pin: not an exploration session (decision 11: a full "
                            "re-verification of every carried cell is its own authorised session)")
        else:
            problems += [f"R3: {p}" for p in pp]
    ov = rs.build_overlay(rd1_root / "archive", floor_min)
    out["R5_overlay"] = {"ok": ov["ok"], "sha256": ov["sha256"], "counts": ov["counts"]}
    problems += [f"R5: {p}" for p in ov["problems"]]
    if check_overlay:
        diffs = rs.expected_open_problems(ov["counts"])
        out["R5_overlay"]["differs_from_the_proposal"] = diffs
        problems += [f"R5: {d}" for d in diffs]
    out["overlay"] = ov
    out["ok"] = not problems
    return out


# -- preflight -------------------------------------------------------------------------------------------------------------------------


def _run_unit_suites() -> Tuple[Dict[str, Any], List[str]]:
    """The rd1 suite (it must still pass), the rd2 suite and both rule self-tests, the two suites in parallel."""
    problems: List[str] = []
    rep: Dict[str, Any] = {}
    procs = {"unit_suite_rd1": subprocess.Popen([sys.executable, "-B", str(RL / "m8_rd_tests.py"), "unit"], stdout=subprocess.PIPE,
                                                stderr=subprocess.PIPE, text=True, cwd=REPO_ROOT),
             "unit_suite_rd2": subprocess.Popen([sys.executable, "-B", str(RL / "m8_rd2_tests.py"), "unit"], stdout=subprocess.PIPE,
                                                stderr=subprocess.PIPE, text=True, cwd=REPO_ROOT)}
    for key, p in procs.items():
        out, err = p.communicate()
        rep[key] = (out.strip().splitlines() or [err[-300:]])[-1:]
        if p.returncode != 0:
            problems.append(f"{key} failed")
    for cmd, key in (([sys.executable, "-B", str(RL / "m8_rd_rule.py"), "self-test"], "rule_self_test_rd1"),
                     ([sys.executable, "-B", str(RL / "m8_rd2_rule.py"), "self-test"], "rule_self_test_rd2")):
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)
        rep[key] = (r.stdout.strip().splitlines() or [r.stderr[-300:]])[-1:]
        if r.returncode != 0:
            problems.append(f"{key} failed")
    return rep, problems


def preflight(*, run_unit: bool = True) -> Dict[str, Any]:
    problems: List[str] = []
    rep: Dict[str, Any] = {"utc": utc(), "scope": SCOPE}
    if RD2_ROOT.exists():
        problems.append(f"{RD2_ROOT.relative_to(REPO_ROOT)} exists (never overwritten)")
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
    op = open_protocol()
    rep["open_protocol"] = {k: v for k, v in op.items() if k not in ("overlay", "facts", "problems")}
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


# -- the real environment ----------------------------------------------------------------------------------------------------------------


def build_real_env2(cfg: mrun.RunConfig, frozen_dir: Path, frozen: Mapping[str, str], pins: Mapping[str, Any], sampler: Any = None, *,
                    executable: Optional[Path] = None, flags_explore: Optional[Mapping[str, str]] = None,
                    flags_verify: Optional[Mapping[str, str]] = None, rd1_root: Optional[Path] = None) -> mrun.RunEnv:
    """The real environment. The frozen runtime is rd1's (read in place, never re-frozen from the live configuration); the executable
    and the flag sets are parameters for the tests that drive the real lifecycle code against a fake game."""
    import m7_runtime

    exe = Path(executable) if executable is not None else EXECUTABLE
    fx = dict(flags_explore if flags_explore is not None else FLAGS_EXPLORE)
    fv = dict(flags_verify if flags_verify is not None else FLAGS_VERIFY)
    frozen_rt = mw.FrozenRuntime(Path(frozen_dir), frozen)
    orig_prepare = m7_runtime.prepare_worker_runtime

    def frozen_prepare(runtime_dir: Any, executable: Any) -> Any:
        manifest = orig_prepare(runtime_dir, executable)
        frozen_rt.install(Path(runtime_dir))          # the verification replays use the frozen configuration too
        manifest["frozen_config"] = True
        return manifest

    m7_runtime.prepare_worker_runtime = frozen_prepare
    guard_roots = [str(rd1_root if rd1_root is not None else RD1_ROOT)]

    def worker_spec(rank: int, c: mrun.RunConfig) -> Dict[str, Any]:
        return {"rank": rank, "root": str(c.session_dir / "workers" / f"w{rank:02d}"), "executable": str(exe), "flags": dict(fx),
                "frozen_dir": str(frozen_dir), "frozen_sha256": dict(frozen), "exe_sha256": pins.get("executable_sha256"),
                "runtime_sha256": dict(pins.get("runtime_files") or {}), "port_base": 30000, "port_size": 250,
                "failure_dir": str(c.session_dir / "failures"), "protected_roots": guard_roots}

    def replay(cand: Mapping[str, Any], counted: int, label: str, slot: int) -> Dict[str, Any]:
        import m7f_trace as tr

        words = bytes(cand["words"][:counted])
        actions = [(*mcell.TRIPLES[w], i) for i, w in enumerate(words)]
        work = cfg.session_dir / "vw" / f"s{slot}_{label}"
        trace = tr.run_stepping_trace(label, exe, actions, work, extra_env=dict(fv), index=9000 + int(cand["cid"]), rank=8 + int(slot))
        mw.remove_tree_retry(work / "runtime", runtime=True)
        mw.remove_tree_retry(work / "episodes")
        return trace

    def analyse(initial: Mapping[str, Any], steps: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
        import m7n_crossing as xc

        return xc.analyse_trace(initial, steps)

    tree_snapshot = None
    private_mb = None
    try:
        import m7u_gate as g1

        private_mb = g1.private_mb
    except Exception:  # noqa: BLE001
        pass
    if sampler is not None:
        tree_snapshot = lambda: getattr(sampler, "last", None)      # noqa: E731 - the sampler thread's latest tree sample
    return mrun.RunEnv(worker_spec=worker_spec, replay=replay, analyse=analyse, p1_inputs=ses1.p1_inputs, pins=dict(pins),
                       tree_snapshot=tree_snapshot, private_mb=private_mb, sampler=sampler)


# -- commands --------------------------------------------------------------------------------------------------------------------------


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
    w2.WriteGuard.install([RD1_ROOT])
    approval = json.loads(APPROVAL.read_text(encoding="utf-8"))
    # S0 (outside the clock, zero native ticks): the open protocol once more, then materialise rd2's tree
    op = open_protocol()
    if not op["ok"]:
        print(json.dumps({k: v for k, v in op.items() if k not in ("overlay", "facts")}, indent=1, default=str))
        print("refused: the open protocol failed; nothing was created")
        return 2
    facts = op["facts"]
    meta1 = json.loads((RD1_ROOT / "archive" / "archive_meta.json").read_text(encoding="utf-8"))
    pins1 = meta1["pins"]
    frozen_dir = RD1_ROOT / "archive" / "runtime"
    pins = {"executable_sha256": approval["executable_sha256"], "runtime_files": dict(pins1["runtime_files"]),
            "frozen_sha256": dict(pins1["frozen_sha256"]), "contracts": approval["contracts"], "flags": approval["flags"],
            "archive_id": ARCHIVE_ID, "approval_sha256": sha256_file(APPROVAL), "git_head": approval["git_head"],
            "rule_sha256": approval["rule_sha256"], "p1": approval["p1"]}
    cfg = run_config(**dict(overrides or {}))
    lines = str(meta1["pin_tick0"]["lines"])
    a2 = rs.materialise(RD1_ROOT, cfg.root, facts=facts, overlay=op["overlay"], lines_sha256=lines,
                        meta_extra={"pins": pins, "horizon": cfg.horizon, "burst_words": cfg.burst_words, "ticks": {},
                                    "ledger_T": {"ticks": 0, "jobs": 0}, "pin_tick0": meta1["pin_tick0"],
                                    "first_new_cell": len(op["overlay"]["rows"])},
                        increment_manifest_sha256=op["R1_rd1_immutability"]["manifest_sha256"], utc=utc())
    cfg.session_dir.mkdir(parents=True)
    shutil.copyfile(APPROVAL, cfg.session_dir / "approval_copy.json")
    mrun.write_json(cfg.session_dir / "open.json", {
        "utc": utc(), "pins": pins, "preflight": {k: pf.get(k) for k in ("executable_sha256", "git_head", "readiness", "backup", "approval",
                                                                         "source_snapshot", "unit_suite_rd1", "unit_suite_rd2")},
        "open_protocol": {k: v for k, v in op.items() if k not in ("overlay", "facts")}, "caps": caps(),
        "identity": {k: v for k, v in identity().items() if k != "code"}})
    sampler = ses1.make_sampler(cfg.session_dir / "memory_tree.jsonl", cfg.memory_caps_mb)
    sampler.start()
    env = build_real_env2(cfg, frozen_dir, pins1["frozen_sha256"], pins, sampler)
    try:
        sess = run2.Session2(cfg, env, archive=a2, archive_pin=meta1["pin_tick0"], base_info={"rd1_root": str(RD1_ROOT), "overlay_sha256": op["overlay"]["sha256"]},
                             rd1_root=RD1_ROOT, lines_sha256=lines)
        out = run2.run_all2(sess, immutability=lambda: rs.rd1_immutability(RD1_ROOT, INCREMENT_RD1))
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
    import m8_rd2_report as rpt

    rep = rpt.verify_run(RD2_ROOT, RD1_ROOT, SESSION)
    print(json.dumps(rep, indent=1, default=str))
    return 0 if rep["ok"] else 1


def cmd_report() -> int:
    import m8_rd2_report as rpt

    print(json.dumps(rpt.full_report(RD2_ROOT, RD1_ROOT, SESSION), indent=1, default=str))
    return 0


def cmd_open_check() -> int:
    op = open_protocol()
    print(json.dumps({k: v for k, v in op.items() if k not in ("overlay", "facts")}, indent=1, default=str))
    return 0 if op["ok"] else 1


def cmd_status() -> int:
    st = RD2_ROOT / "sessions" / SESSION / "state.json"
    out = {"rd2_root_exists": RD2_ROOT.exists(), "approval_present": APPROVAL.is_file(),
           "state": json.loads(st.read_text(encoding="utf-8")) if st.is_file() else None}
    print(json.dumps(out, indent=1, default=str))
    return 0


def cmd_template() -> int:
    ident = identity()
    rec = dict(ident, approval="PENDING (a reviewer replaces this with APPROVED ... and fills the authorisation and the source "
                               "snapshot entries; this command never writes the record)",
               revision=1, authorisation={"source": "<the user's message>", "text": ["<what is authorised, once>"]},
               source_snapshot={"dest": "D:\\BattleShip_source_snapshots\\<date>_m8_rd2", "snapshot_json_sha256": "<sha256>", "result": "PASS",
                                "files": "<n>", "git_head": ident["git_head"],
                                "independent_verification": "<tool verify and an independent PowerShell re-hash>"},
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
