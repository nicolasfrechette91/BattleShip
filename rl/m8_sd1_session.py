#!/usr/bin/env python3
"""M8-sd1 session driver: one speed-search session, the first time-directed continuation of archive m8_rd_a1 (rd1, rd2, rd3 and rd4 as closed) under `m8_rd_select_v4`.

    python -B rl/m8_sd1_session.py status
    python -B rl/m8_sd1_session.py open-check                        # zero ticks, writes nothing: R1-R5 against the four earlier trees
    python -B rl/m8_sd1_session.py preflight [--skip-unit]           # no game: tests, pins, D: coverage, readiness, approval
    python -B rl/m8_sd1_session.py approval-template                 # prints the record a reviewer would write (never writes it)
    python -B rl/m8_sd1_session.py run                               # refused unless the preflight passes, including the approval
    python -B rl/m8_sd1_session.py verify-run                        # read-only post-run verification
    python -B rl/m8_sd1_session.py report                            # the registered diagnostics beside rd4's, rd3's, rd2's and rd1's reference values
    python -B rl/m8_sd1_session.py check-results-record --path docs/rl_m8_sd1_results_<date>.md
    python -B rl/m8_sd1_session.py fingerprint                       # the sd1 source fingerprint (rl/m8_sd1_*.py and tools/m8_sd1/*)

Design: docs/rl_m8_sd1_proposal_2026-10-07.md as decided on 2026-10-11 (logs/m8_sd1_prep/phase1_plan.md). SCOPE: see rl/m8_sd1_rule.SCOPE. The earlier trees are only read; sd1 writes
only under runs/m8_rd_sd1/; the write guard covers every other tree under runs/. Light top-level imports only (spawned workers re-import this script).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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
import m8_rd_session as ses1  # noqa: E402
import m8_rd_worker as mw  # noqa: E402
import m8_rd2_session as ses2  # noqa: E402
import m8_rd2_worker as w2  # noqa: E402
import m8_rd3_resume as r3  # noqa: E402
import m8_rd4_resume as r4  # noqa: E402
import m8_rd4_session as ses4  # noqa: E402
import m8_sd1_artifacts as art  # noqa: E402
import m8_sd1_claims as cl5  # noqa: E402
import m8_sd1_resume as r5  # noqa: E402
import m8_sd1_rule as rule5  # noqa: E402
import m8_sd1_run as run5  # noqa: E402
import m8_sd1_select as s5  # noqa: E402

REPO_ROOT = ses1.REPO_ROOT
RL = ses1.RL
RUNS = ses1.RUNS
LOGS = ses1.LOGS
TOOLS = REPO_ROOT / "tools" / "m8_sd1"
RD1_ROOT = RUNS / "m8_rd"
RD2_ROOT = RUNS / "m8_rd_rd2"
RD3_ROOT = RUNS / "m8_rd_rd3"
RD4_ROOT = RUNS / "m8_rd_rd4"
SD1_ROOT = RUNS / "m8_rd_sd1"
APPROVAL = REPO_ROOT / "docs" / "rl_m8_sd1_approval.json"
BACKUP_ROOT = ses1.BACKUP_ROOT
INCREMENT_RD1 = BACKUP_ROOT / rs.RD1_INCREMENT_NAME
INCREMENT_RD2 = BACKUP_ROOT / r3.RD2_INCREMENT_NAME
INCREMENT_RD3 = BACKUP_ROOT / r4.RD3_INCREMENT_NAME
INCREMENT_RD4 = BACKUP_ROOT / r5.RD4_INCREMENT_NAME
SNAPSHOT_ROOT = ses1.SNAPSHOT_ROOT
SESSION = "sd1"
GATE = "m8_sd1"
ARCHIVE_ID = "m8_rd_a1"
SCOPE = rule5.SCOPE
N_WORKERS = 5
MARGIN = rule5.MARGIN
RECORD_REFERENCE = r5.RECORD_REFERENCE
RD1_EXPECT: Mapping[str, Any] = rs.RD1_FACTS
RD2_EXPECT: Mapping[str, Any] = r3.RD2_FACTS
RD3_EXPECT: Mapping[str, Any] = r4.RD3_FACTS
RD4_EXPECT: Mapping[str, Any] = r5.RD4_FACTS
CHECK_EXPECTED_OVERLAY = True                    # the registered overlay figures and digests (off only in the tests on synthetic trees)
EXECUTABLE = ses1.EXECUTABLE
EXE_DIR = ses1.EXE_DIR
FLAGS_EXPLORE = ses1.FLAGS_EXPLORE
FLAGS_VERIFY = ses1.FLAGS_VERIFY
READINESS = ses1.READINESS

NEW_CODE_FILES = ("m8_sd1_artifacts.py", "m8_sd1_select.py", "m8_sd1_rule.py", "m8_sd1_claims.py", "m8_sd1_resume.py", "m8_sd1_report.py", "m8_sd1_run.py", "m8_sd1_session.py",
                  "m8_sd1_snapshot.py", "m8_sd1_tests.py", "m9_artifacts.py", "m9_contract.py")
CODE_FILES = tuple(ses4.CODE_FILES) + NEW_CODE_FILES
TOOL_FILES = ("launch_detached.ps1", "wait_session.py", "write_approval.py", "three_passes.py", "independent_increment_check.ps1")
DOC_FILES = tuple(ses4.DOC_FILES) + ("docs/rl_m8_rd4_results_2026-10-03.md", "docs/rl_m8_sd1_proposal_2026-10-07.md")
RULE_SELF_TESTS = (("rule_self_test_rd1", "m8_rd_rule.py"), ("rule_self_test_rd2", "m8_rd2_rule.py"), ("rule_self_test_rd3", "m8_rd3_rule.py"), ("rule_self_test_rd4", "m8_rd4_rule.py"),
                   ("rule_self_test_sd1", "m8_sd1_rule.py"))
RESULTS_RECORD_RE = re.compile(r"^rl_m8_sd1_results_(?P<date>\d{4}-\d{2}-\d{2})\.md$")
RESULTS_RECORD_PREFIX = "rl_m8_sd1_results"
RESULTS_TITLE = "# M8-sd1 results ({date})"


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256_file(p: Path) -> str:
    return mw.sha256_file(Path(p))


def source_fingerprint(repo: Optional[Path] = None) -> str:
    """sha256 (16 hex) over the sd1 sources: rl/m8_sd1_*.py and tools/m8_sd1/* (name and bytes, sorted). The launch condition B0 checks it."""
    repo = Path(repo if repo is not None else REPO_ROOT)
    h = hashlib.sha256()
    files = sorted((repo / "rl").glob("m8_sd1_*.py")) + sorted(p for p in (repo / "tools" / "m8_sd1").glob("*") if p.is_file())
    for p in files:
        h.update(p.relative_to(repo).as_posix().encode())
        h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()[:16]


def run_config(root: Optional[Path] = None, **over: Any) -> mrun.RunConfig:
    """The registered budgets and caps (exactly rd4's): exploration 50 min or 6,000,000 native ticks, valid from 2,000,000; the open phase (P1, 16 identity replays, the record) 70,000
    ticks / 4 min; verification 400,000 ticks / 6 min; a 60-minute hard cap from P1; memory caps as rd1's."""
    kw: Dict[str, Any] = dict(session_id=SESSION, archive_id=ARCHIVE_ID, n_workers=N_WORKERS)
    kw.update(over)
    return ses2.run_config(root=Path(root) if root is not None else SD1_ROOT, **kw)


def caps() -> Dict[str, Any]:
    cfg = run_config()
    return {"exploration_tick_cap": cfg.arm_cap("T"), "min_exploration_ticks": cfg.min_arm_ticks, "open_tick_cap": cfg.p1_tick_cap, "replay_tick_cap": cfg.replay_tick_cap,
            "wall_caps_s": {k: v for k, v in cfg.wall_caps_s.items() if k != "C"}, "global_cap_s": cfg.global_cap_s, "checkpoint_every_s": cfg.checkpoint_every_s,
            "memory_caps_mb": dict(cfg.memory_caps_mb), "memory_sample_s": ses1.MEMORY_SAMPLE_S, "max_battleship_processes": cfg.max_battleship_processes,
            "lifecycle_failure_limit": cfg.lifecycle_failure_limit, "verify_threads": cfg.verify_threads, "identity_k": cfg.identity_k, "job_timeout_s": mrun.JOB_TIMEOUT_S,
            "wall_cap_grace_s": mrun.WALL_CAP_GRACE_S}


# -- identity and approval ---------------------------------------------------------------------------------------------------------------


def contract_digests5(lines_sha256: str) -> Dict[str, str]:
    """rd4's eight contract digests and sd1's selection contract `m8_rd_select_v4` (the registered change from v3)."""
    import m7q_status_table as st

    d = dict(ses4.contract_digests4(lines_sha256))
    d["m8_rd_select_v4"] = s5.select4_contract_digest(st.load_table()["sha256"], lines_sha256, None, RECORD_REFERENCE, MARGIN)
    return d


def _events(archive_dir: Path) -> List[Dict[str, Any]]:
    return ses4._events(archive_dir)


_BASE_CACHE: Dict[str, Dict[str, Any]] = {}


def base_identity5(rd1_dir: Optional[Path] = None, rd2_dir: Optional[Path] = None, rd3_dir: Optional[Path] = None, rd4_dir: Optional[Path] = None, inc1: Optional[Path] = None,
                   inc2: Optional[Path] = None, inc3: Optional[Path] = None, inc4: Optional[Path] = None) -> Dict[str, Any]:
    """What sd1 starts from: rd1's, rd2's and rd3's base identity (as rd4 pinned it) and rd4's closing archive, close record, D: increment and inherited record facts."""
    rd1_dir = RD1_ROOT if rd1_dir is None else rd1_dir
    rd2_dir = RD2_ROOT if rd2_dir is None else rd2_dir
    rd3_dir = RD3_ROOT if rd3_dir is None else rd3_dir
    rd4_dir = RD4_ROOT if rd4_dir is None else rd4_dir
    inc1 = INCREMENT_RD1 if inc1 is None else inc1
    inc2 = INCREMENT_RD2 if inc2 is None else inc2
    inc3 = INCREMENT_RD3 if inc3 is None else inc3
    inc4 = INCREMENT_RD4 if inc4 is None else inc4
    files = {n: march.sha256_file(Path(rd4_dir) / "archive" / n) for n in march.DATA_FILES}
    key = json.dumps(files, sort_keys=True)
    if key not in _BASE_CACHE:
        a, _m = s5.Archive5.read_dir(Path(rd4_dir) / "archive")
        _BASE_CACHE.clear()
        _BASE_CACHE[key] = r5.inherited_record_facts(Path(rd4_dir), a)
    inherited = _BASE_CACHE[key]
    meta = json.loads((Path(rd4_dir) / "archive" / "archive_meta.json").read_text(encoding="utf-8"))
    close_p = Path(rd4_dir) / "sessions" / "rd4" / "close.json"
    inc_m = Path(inc4) / "manifest.tsv.gz"
    return {"rd1_rd2_rd3": ses4.base_identity4(rd1_dir, rd2_dir, rd3_dir, inc1, inc2, inc3),
            "rd4_archive_files_sha256": files, "rd4_close_record_sha256": sha256_file(close_p) if close_p.is_file() else None, "rd4_increment": Path(inc4).name,
            "rd4_increment_manifest_sha256": sha256_file(inc_m) if inc_m.is_file() else None, "rd4_checkpoint_seq": meta.get("checkpoint_seq"),
            "rd4_session_events": [e for e in _events(Path(rd4_dir) / "archive") if e.get("ev") == "session"], "rd4_pins": meta.get("pins"),
            "pin_tick0_digest": (meta.get("pin_tick0") or {}).get("digest"), "lines_sha256": (meta.get("pin_tick0") or {}).get("lines"), "rd4_first_iteration": meta.get("rd4_first_iteration"),
            "first_sd1_iteration": r5.RD4_FACTS["first_sd1_iteration"], "inherited_record": inherited, "rd4_line": r5.rd4_line_status(Path(rd4_dir))}


def identity() -> Dict[str, Any]:
    dr = ses1.d_records_digest()
    base = base_identity5()
    lines = str(base["lines_sha256"])
    ov = r5.closing_overlay5(RD4_ROOT, RECORD_REFERENCE, MARGIN, expect_rd4=(r5.EXPECTED_RD4_CLOSE_OVERLAY if CHECK_EXPECTED_OVERLAY else {}),
                             expect_v4=(r5.EXPECTED_OPEN_OVERLAY5 if CHECK_EXPECTED_OVERLAY else {}))
    contracts = contract_digests5(lines)
    return {"gate": GATE, "scope": SCOPE, "milestone": "M8", "archive_id": ARCHIVE_ID, "session": SESSION, "line": "sd", "rule": rule5.RULE_ID, "rule_sha256": rule5.rule_digest(),
            "claims_contract": cl5.CLAIMS5_CONTRACT, "claims_digest": cl5.contract_digest(), "artifacts_contract": art.ARTIFACTS5_CONTRACT, "artifacts_digest": art.contract_digest(),
            "task": art.task_block(), "contracts": contracts,
            "key_strings": {"select_rd1": "m8_rd|<archive_id>|select|<iteration> (iterations 0..2174, rd1)",
                            "select_rd2": f"m8_rd|<archive_id>{s5.DRAW_SUFFIX_RD2}|select|<iteration> (iterations 2175..6211, rd2)",
                            "select_rd3": f"m8_rd|<archive_id>{s5.DRAW_SUFFIX_RD3}|select|<iteration> (iterations 6212..10405, rd3)",
                            "select_rd4": f"m8_rd|<archive_id>{s5.DRAW_SUFFIX_RD4}|select|<iteration> (iterations 10406..13885, rd4)",
                            "select_sd1": f"m8_rd|<archive_id>{s5.DRAW_SUFFIX}|select|<iteration> (iterations from 13886)",
                            "explore_sd1": f"m8_rd|<archive_id>{s5.DRAW_SUFFIX}|explore|<iteration>|<decision index>",
                            "identity_open": "m8_rd|<archive_id>|identity_open|sd1|<cell id>", "identity_close": "m8_rd|<archive_id>|identity_close|sd1|<cell id>"},
            "draws_sha256": s5.draws_digest(), "sd1_session_event_digest": contracts["m8_rd_select_v4"], "select_v4_changed_from": {"m8_rd_select_v3": contracts["m8_rd_select_v3"]},
            "select_v4_registered_changes": list(s5.REGISTERED_CHANGES), "select_v4_changes": list(s5.CHANGES_TEXT), "length_scale_v4": s5.LENGTH_SCALE_V4,
            "record_reference": dict(RECORD_REFERENCE), "margin": MARGIN, "progress_bar": rule5.PROGRESS_BAR, "tiers": {k: rule5.TIERS[k] for k in ("5_percent", "10_percent", "round_2000")},
            "inherited_descriptive_rule": "every clear-event trajectory of rd4's registry that no rd4 replay verified; replayed after the pool; reported only",
            "executable_sha256": sha256_file(EXECUTABLE) if EXECUTABLE.is_file() else None, "runtime_files": ses1.runtime_pins(), "flags": {"explore": FLAGS_EXPLORE, "verify": FLAGS_VERIFY},
            "p1": ses1.p1_pins(), "caps": caps(), "workers": N_WORKERS, "burst_words": mx.BURST_WORDS, "horizon": mcell.HORIZON, "readiness": READINESS, "base": base,
            "open_overlay": {"rd4_closing_sha256": ov["rd4_closing"]["sha256"], "v4_sha256": ov["v4"]["sha256"], "v4_counts_sha256": ses4.ses3._norm_sha(ov["v4"]["counts"]),
                             "expected_v4_counts": r5.EXPECTED_OPEN_OVERLAY5, "expected_rd4_counts": r5.EXPECTED_RD4_CLOSE_OVERLAY},
            "budgets": {"exploration": "50 min or 6,000,000 native ticks, valid from 2,000,000", "open": "70,000 ticks / 4 min (P1, 16 identity replays, the record re-verified)",
                        "verification": "400,000 ticks / 6 min (the pool fastest first, the inherited descriptive replays, 16 close identity replays)", "hard_cap": "60 min from P1"},
            "code": {**{f"rl/{f}": sha256_file(RL / f) for f in CODE_FILES if (RL / f).is_file()}, **{f"tools/m8_sd1/{f}": sha256_file(TOOLS / f) for f in TOOL_FILES if (TOOLS / f).is_file()}},
            "source_fingerprint": source_fingerprint(),
            "docs_sha256": {**{f: sha256_file(REPO_ROOT / f) for f in DOC_FILES if (REPO_ROOT / f).is_file()},
                            **{p.relative_to(REPO_ROOT).as_posix(): sha256_file(p) for p in sorted((REPO_ROOT / "docs").glob("rl_m8_sd1_prep_*.md"))}},
            "git_head": ses1.git("rev-parse", "HEAD").strip(), "d_records": {"folders": dr["folders"], "digest": dr["digest"]}}


def approval_status(path: Optional[Path] = None, want: Optional[Mapping[str, Any]] = None) -> Tuple[bool, str]:
    p = Path(APPROVAL if path is None else path)
    if p.is_file():
        try:
            rec = json.loads(p.read_text(encoding="utf-8-sig"))
        except ValueError:
            raise
        if isinstance(rec, Mapping) and str(rec.get("approval", "")).startswith("APPROVED") and not art.is_stamped(rec):
            return False, "the approval record carries no task block or created_utc (refused)"
    return ses1.approval_status(p, want if want is not None else identity())


# -- the protected trees -----------------------------------------------------------------------------------------------------------------------


def protected_runs_roots(runs: Optional[Path] = None, own: Optional[Path] = None) -> List[Path]:
    """Every existing tree under runs/ except sd1's own (O6): the write guard's roots."""
    runs = Path(RUNS if runs is None else runs)
    own = Path(SD1_ROOT if own is None else own)
    if not runs.is_dir():
        return []
    return sorted(p for p in runs.iterdir() if p.is_dir() and p.resolve() != own.resolve())


# -- the open protocol (zero native ticks) -----------------------------------------------------------------------------------------------------


def open_protocol5(rd1_dir: Optional[Path] = None, rd2_dir: Optional[Path] = None, rd3_dir: Optional[Path] = None, rd4_dir: Optional[Path] = None, inc1: Optional[Path] = None,
                   inc2: Optional[Path] = None, inc3: Optional[Path] = None, inc4: Optional[Path] = None, *, expect1: Optional[Mapping[str, Any]] = None, expect2: Optional[Mapping[str, Any]] = None,
                   expect3: Optional[Mapping[str, Any]] = None, expect4: Optional[Mapping[str, Any]] = None, check_overlay: Optional[bool] = None,
                   live_pins: Optional[Callable[[], Mapping[str, Any]]] = None, floor_min: Optional[float] = None, with_audit: bool = True, margin: int = MARGIN,
                   record_reference: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """R1-R5 at four levels: immutability of all four trees, the archive facts and audits (each with its own code), the pins (each session's own contract set), both overlays of rd4's
    closing archive, the inherited record facts, the record candidate and the inherited descriptive candidates read from rd4's registry. Writes nothing."""
    expect1 = RD1_EXPECT if expect1 is None else expect1
    expect2 = RD2_EXPECT if expect2 is None else expect2
    expect3 = RD3_EXPECT if expect3 is None else expect3
    expect4 = RD4_EXPECT if expect4 is None else expect4
    check_overlay = CHECK_EXPECTED_OVERLAY if check_overlay is None else check_overlay
    rd1_dir = Path(RD1_ROOT if rd1_dir is None else rd1_dir)
    rd2_dir = Path(RD2_ROOT if rd2_dir is None else rd2_dir)
    rd3_dir = Path(RD3_ROOT if rd3_dir is None else rd3_dir)
    rd4_dir = Path(RD4_ROOT if rd4_dir is None else rd4_dir)
    inc1 = INCREMENT_RD1 if inc1 is None else inc1
    inc2 = INCREMENT_RD2 if inc2 is None else inc2
    inc3 = INCREMENT_RD3 if inc3 is None else inc3
    inc4 = INCREMENT_RD4 if inc4 is None else inc4
    problems: List[str] = []
    out: Dict[str, Any] = {"problems": problems}
    keys = ("ok", "files", "manifest_files", "manifest_sha256", "bytes", "increment_record")

    def guard(label: str, fn: Callable[[], Any], default: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
            problems.append(f"{label}: {type(exc).__name__}: {exc}")
            return default

    imms: Dict[str, Dict[str, Any]] = {}
    for who, root, inc in (("rd1", rd1_dir, inc1), ("rd2", rd2_dir, inc2), ("rd3", rd3_dir, inc3), ("rd4", rd4_dir, inc4)):
        imm = guard(f"R1 ({who})", lambda root=root, inc=inc: rs.rd1_immutability(root, Path(inc)), {"ok": False, "problems": []})
        imms[who] = imm
        out[f"R1_{who}_immutability"] = {k: imm.get(k) for k in keys}
        problems += [f"R1 ({who}): {p}" for p in imm["problems"]]
    for who, E in (("rd1", expect1), ("rd2", expect2), ("rd3", expect3), ("rd4", expect4)):
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
    facts4 = guard("R2/R4 (rd4)", lambda: r5.rd4_archive_facts(rd1_dir, rd2_dir, rd3_dir, rd4_dir, lines, expect4, with_audit=with_audit), {"ok": False, "problems": []})
    out["R2_R4_rd4_archive"] = {k: facts4.get(k) for k in ("ok", "checkpoints", "counts", "dispatch_iterations", "audit", "close_record_sha256", "session_events", "digest_recomputed", "diag2",
                                                           "first_sd1_iteration", "rd4_checkpoint_seq", "inherited_record", "record_reference", "rd4_line")}
    problems += [f"R2/R4 (rd4): {p}" for p in facts4.get("problems", [])]
    out["facts1"], out["facts2"], out["facts3"], out["facts4"] = facts1, facts2, facts3, facts4
    pins_all = [f.get("pin_tick0") for f in (facts1, facts2, facts3, facts4)]
    if any(p != pins_all[0] for p in pins_all):
        problems.append("R2: the pinned tick-0 records of the four archives differ")
    rr = facts4.get("record_reference")
    if rr is not None and record_reference is not None and json.dumps(rr, sort_keys=True) != json.dumps(dict(record_reference), sort_keys=True):
        problems.append("R2: the record reference read from rd4's records differs from the pinned one")
    if facts1.get("pins") is not None and facts2.get("pins") is not None and facts3.get("pins") is not None and facts4.get("pins") is not None:
        now = dict(live_pins() if live_pins else {"executable_sha256": sha256_file(EXECUTABLE), "runtime_files": ses1.runtime_pins(), "contracts": ses4.contract_digests4(str(lines)),
                                                  "flags": {"explore": FLAGS_EXPLORE, "verify": FLAGS_VERIFY}})
        frozen_dir = rd1_dir / "archive" / "runtime"
        now4 = dict(now, contracts={k: v for k, v in dict(now["contracts"]).items() if k in facts4["pins"].get("contracts", {})})
        now3 = dict(now, contracts={k: v for k, v in dict(now["contracts"]).items() if k != "m8_rd_select_v3"})
        now1 = dict(now, contracts={k: v for k, v in dict(now["contracts"]).items() if k not in ("m8_rd_select_v2", "m8_rd_select_v3")})
        pp4 = rs.pin_problems(facts4["pins"], now4, frozen_dir, facts4["pins"].get("frozen_sha256") or {})
        pp3 = rs.pin_problems(facts3["pins"], now3, frozen_dir, facts3["pins"].get("frozen_sha256") or {})
        pp2 = rs.pin_problems(facts2["pins"], now3, frozen_dir, facts2["pins"].get("frozen_sha256") or {})
        pp1 = rs.pin_problems(facts1["pins"], now1, frozen_dir, facts1["pins"].get("frozen_sha256") or {})
        exe_only = pp4 == ["pin executable_sha256 differs"]
        out["R3_pins"] = {"problems": pp4, "rd3_problems": pp3, "rd2_problems": pp2, "rd1_problems": pp1, "executable_only": exe_only,
                          "contract_keys": {"rd1": len(facts1["pins"].get("contracts", {})), "rd2": len(facts2["pins"].get("contracts", {})), "rd3": len(facts3["pins"].get("contracts", {})),
                                            "rd4": len(facts4["pins"].get("contracts", {}))}}
        if exe_only:
            problems.append("R3: only the executable differs from the archive's pin: not an exploration session (a full re-verification of every carried cell is its own authorised session)")
        else:
            problems += [f"R3: {p}" for p in pp4]
        problems += [f"R3 (rd3's pins): {p}" for p in pp3]
        problems += [f"R3 (rd2's pins): {p}" for p in pp2]
        problems += [f"R3 (rd1's pins): {p}" for p in pp1]
    else:
        out["R3_pins"] = {"problems": ["the archives' pins could not be read"], "rd3_problems": [], "rd2_problems": [], "rd1_problems": [], "executable_only": False}
        problems.append("R3: the archives' pins could not be read")
    rr_use = dict(record_reference) if record_reference is not None else (rr if rr is not None else None)
    if rr_use is None:
        ov = {"ok": False, "problems": ["no record reference"], "rd4_closing": {"sha256": None, "counts": {}}, "v4": {"sha256": None, "counts": {}}}
        problems.append("R5: no record reference to bound the overlay")
    else:
        ov = guard("R5", lambda: r5.closing_overlay5(rd4_dir, rr_use, margin, expect_rd4=(r5.EXPECTED_RD4_CLOSE_OVERLAY if check_overlay else {}),
                                                     expect_v4=(r5.EXPECTED_OPEN_OVERLAY5 if check_overlay else {}), floor_min=floor_min,
                                                     rd4_sha256=(r5.RD4_CLOSING_OVERLAY_SHA256 if check_overlay else None), v4_sha256=(r5.SD1_OPEN_OVERLAY_SHA256 if check_overlay else None)),
                   {"ok": False, "problems": [], "rd4_closing": {"sha256": None, "counts": {}}, "v4": {"sha256": None, "counts": {}}})
        problems += [f"R5: {p}" for p in ov["problems"]]
    out["R5_overlay"] = {"ok": ov["ok"], "rd4_closing_sha256": ov["rd4_closing"]["sha256"], "v4_sha256": ov["v4"]["sha256"], "rd4_closing_counts": ov["rd4_closing"]["counts"], "v4_counts": ov["v4"]["counts"]}
    out["overlay"] = ov
    inh: List[Dict[str, Any]] = []
    if rr_use is not None:
        inh = guard("R2 (inherited descriptive)", lambda: cl5.inherited_unverified_clears(rd4_dir), [])
        rc = guard("R2 (record candidate)", lambda: cl5.record_candidate(rd4_dir, rr_use), {})
        out["record_candidate"] = rc
    else:
        out["record_candidate"] = {}
    out["inherited"] = inh
    out["inherited_summary"] = [{"iteration": c["iteration"], "rd4_cid": c["rd4_cid"], "registered_clear_tick": cl5.clear_tick(c), "words": len(bytes(c["words"]))} for c in inh]
    out["inherited_ticks"] = cl5.inherited_ticks(inh)
    out["ok"] = not problems
    return out


# -- preflight ---------------------------------------------------------------------------------------------------------------------------------


def _run_unit_suites() -> Tuple[Dict[str, Any], List[str]]:
    """sd1's own suite (deterministic by construction; it contains the explicit lists of the deterministic pure tests of rd1 to rd4) and the five rule self-tests."""
    problems: List[str] = []
    rep: Dict[str, Any] = {}
    r = subprocess.run([sys.executable, "-B", str(RL / "m8_sd1_tests.py"), "unit"], capture_output=True, text=True, cwd=REPO_ROOT)
    rep["unit_suite_sd1"] = (r.stdout.strip().splitlines() or [r.stderr[-300:]])[-1:]
    if r.returncode != 0:
        problems.append("unit_suite_sd1 failed")
    for key, f in RULE_SELF_TESTS:
        r = subprocess.run([sys.executable, "-B", str(RL / f), "self-test"], capture_output=True, text=True, cwd=REPO_ROOT)
        rep[key] = (r.stdout.strip().splitlines() or [r.stderr[-300:]])[-1:]
        if r.returncode != 0:
            problems.append(f"{key} failed")
    return rep, problems


def preflight(*, run_unit: bool = True) -> Dict[str, Any]:
    problems: List[str] = []
    rep: Dict[str, Any] = {"utc": utc(), "scope": SCOPE}
    if SD1_ROOT.exists():
        problems.append(f"{SD1_ROOT.relative_to(REPO_ROOT)} exists (never overwritten)")
    if run_unit:
        r, p = _run_unit_suites()
        rep.update(r)
        problems += p
    if not EXECUTABLE.is_file():
        problems.append(f"missing executable {EXECUTABLE}")
    missing_tools = [f for f in TOOL_FILES if not (TOOLS / f).is_file()]
    if missing_tools:
        problems.append(f"missing launch tools under tools/m8_sd1: {missing_tools}")
    ident = identity()
    rep["executable_sha256"] = ident["executable_sha256"]
    rep["git_head"] = ident["git_head"]
    rep["source_fingerprint"] = ident["source_fingerprint"]
    changed = ses1.tracked_changes()
    if changed:
        problems.append(f"tracked files differ from HEAD: {changed[:6]}")
    odd = ses1.untracked_not_new()
    if odd:
        problems.append(f"git status shows entries other than new files: {odd[:6]}")
    rep["git_status_new_files"] = sum(1 for ln in ses1.git("status", "--porcelain").splitlines() if ln.startswith("??"))
    for n, p in ident["p1"].items():
        if not (p["native_action_digest"] == p["recorded_digest"] == p["trace_action_digest"] and p["consumed_ticks_ok"] and p["trace_submitted"] == p["words"] and p["trace_flags"]
                and p["trace_flags"].get("SSB64_RL_SPATIAL") == "1"):
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
    op = open_protocol5(record_reference=RECORD_REFERENCE)
    rep["open_protocol"] = {k: v for k, v in op.items() if k not in ("overlay", "facts1", "facts2", "facts3", "facts4", "problems", "inherited", "record_candidate")}
    problems += op["problems"]
    rep["inherited_ticks"] = op["inherited_ticks"]
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
    ok, why = approval_status(APPROVAL, ident)
    rep["approval"] = why
    approval = json.loads(APPROVAL.read_text(encoding="utf-8-sig")) if APPROVAL.is_file() else None
    sok, swhy = ses1.snapshot_status(approval)
    rep["source_snapshot"] = swhy
    if not sok:
        problems.append(f"source snapshot: {swhy}")
    if not ok:
        problems.append(why)
    rep["protected_roots"] = [str(p.relative_to(REPO_ROOT)) for p in protected_runs_roots()]
    rep["problems"] = problems
    rep["ok"] = not problems
    return art.stamp(rep)


# -- the real environment ----------------------------------------------------------------------------------------------------------------------


def build_real_env5(cfg: mrun.RunConfig, frozen_dir: Path, frozen: Mapping[str, str], pins: Mapping[str, Any], sampler: Any = None, *, executable: Optional[Path] = None,
                    flags_explore: Optional[Mapping[str, str]] = None, flags_verify: Optional[Mapping[str, str]] = None, protected: Optional[Sequence[Path]] = None) -> mrun.RunEnv:
    """rd2's real environment (the frozen runtime is rd1's, read in place), with the write guard of every worker over every other tree under runs/."""
    env = ses2.build_real_env2(cfg, frozen_dir, frozen, pins, sampler, executable=executable if executable is not None else EXECUTABLE,
                               flags_explore=flags_explore if flags_explore is not None else FLAGS_EXPLORE, flags_verify=flags_verify if flags_verify is not None else FLAGS_VERIFY,
                               rd1_root=RD1_ROOT)
    inner = env.worker_spec
    roots = [str(p) for p in (protected if protected is not None else protected_runs_roots())]

    def worker_spec(rank: int, c: mrun.RunConfig) -> Dict[str, Any]:
        spec = inner(rank, c)
        spec["protected_roots"] = list(roots)
        return spec

    env.worker_spec = worker_spec
    return env


def earlier_trees_immutability() -> Dict[str, Any]:
    """R1 for all four earlier trees (each equals its D: increment): the callable the close checks run."""
    parts = {"rd1": rs.rd1_immutability(RD1_ROOT, INCREMENT_RD1), "rd2": rs.rd1_immutability(RD2_ROOT, INCREMENT_RD2), "rd3": rs.rd1_immutability(RD3_ROOT, INCREMENT_RD3),
             "rd4": rs.rd1_immutability(RD4_ROOT, INCREMENT_RD4)}
    return {"ok": all(v.get("ok") for v in parts.values()), "problems": [f"{k}: {p}" for k, v in parts.items() for p in v.get("problems", [])],
            **{k: {kk: v.get(kk) for kk in ("ok", "files", "manifest_sha256", "bytes")} for k, v in parts.items()}}


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
    roots = protected_runs_roots()
    w2.WriteGuard.install(roots)
    approval = json.loads(APPROVAL.read_text(encoding="utf-8-sig"))
    op = open_protocol5(record_reference=RECORD_REFERENCE)
    if not op["ok"]:
        print(json.dumps({k: v for k, v in op.items() if k not in ("overlay", "facts1", "facts2", "facts3", "facts4", "inherited", "record_candidate")}, indent=1, default=str))
        print("refused: the open protocol failed; nothing was created")
        return 2
    facts4 = op["facts4"]
    meta1 = json.loads((RD1_ROOT / "archive" / "archive_meta.json").read_text(encoding="utf-8"))
    pins1 = meta1["pins"]
    frozen_dir = RD1_ROOT / "archive" / "runtime"
    pins = {"executable_sha256": approval["executable_sha256"], "runtime_files": dict(pins1["runtime_files"]), "frozen_sha256": dict(pins1["frozen_sha256"]), "contracts": approval["contracts"],
            "flags": approval["flags"], "archive_id": ARCHIVE_ID, "approval_sha256": sha256_file(APPROVAL), "git_head": approval["git_head"], "rule_sha256": approval["rule_sha256"], "p1": approval["p1"]}
    cfg = run_config(**dict(overrides or {}))
    lines = str(facts4["lines_sha256"])
    created = utc()
    a5 = r5.materialise5(RD4_ROOT, cfg.root, facts=facts4, overlay=op["overlay"], lines_sha256=lines,
                         meta_extra={"pins": pins, "horizon": cfg.horizon, "burst_words": cfg.burst_words, "ticks": {}, "ledger_T": {"ticks": 0, "jobs": 0}, "pin_tick0": facts4["pin_tick0"],
                                     "first_new_cell": len(op["overlay"]["v4"]["rows"])},
                         increment_manifest_sha256=op["R1_rd4_immutability"]["manifest_sha256"], utc=created, margin=MARGIN)
    cfg.session_dir.mkdir(parents=True)
    shutil.copyfile(APPROVAL, cfg.session_dir / "approval_copy.json")
    rc = op["record_candidate"]
    import m8_sd1_report as rpt5

    art.write_json5(cfg.session_dir / "open.json", {
        "utc": created, "pins": pins, "preflight": {k: pf.get(k) for k in ("executable_sha256", "git_head", "source_fingerprint", "readiness", "backup", "approval", "source_snapshot", "unit_suite_sd1",
                                                                          "rule_self_test_rd1", "rule_self_test_rd2", "rule_self_test_rd3", "rule_self_test_rd4", "rule_self_test_sd1")},
        "open_protocol": {k: v for k, v in op.items() if k not in ("overlay", "facts1", "facts2", "facts3", "facts4", "inherited", "record_candidate")}, "caps": caps(),
        "record_reference": dict(RECORD_REFERENCE), "margin": MARGIN, "protected_roots": [str(p) for p in roots],
        "record_candidate_summary": {"iteration": rc.get("iteration"), "rd4_cid": rc.get("rd4_cid"), "words": len(bytes(rc.get("words", b""))), "pace": rpt5.record_pace(rc) if rc else {}},
        "inherited_record": facts4["inherited_record"], "rd4_line": facts4["rd4_line"], "identity": {k: v for k, v in identity().items() if k != "code"}})
    art.jsonl_header(cfg.session_dir / "memory_tree.jsonl", run5.SCHEMAS["memory_tree"])
    sampler = ses1.make_sampler(cfg.session_dir / "memory_tree.jsonl", cfg.memory_caps_mb)
    sampler.start()
    env = build_real_env5(cfg, frozen_dir, pins1["frozen_sha256"], pins, sampler, protected=roots)
    try:
        sess = run5.Session5(cfg, env, archive=a5, archive_pin=facts4["pin_tick0"], base_info={"rd1_root": str(RD1_ROOT), "rd2_root": str(RD2_ROOT), "rd3_root": str(RD3_ROOT), "rd4_root": str(RD4_ROOT),
                                                                                              "open_overlay_sha256": op["overlay"]["v4"]["sha256"]},
                             rd1_root=RD1_ROOT, rd2_root=RD2_ROOT, rd3_root=RD3_ROOT, rd4_root=RD4_ROOT, lines_sha256=lines, ckpt_seq=int(facts4["rd4_checkpoint_seq"]) + 1,
                             archive_created_utc=created, record_candidate=rc, inherited=op["inherited"], rd4_line=facts4["rd4_line"])
        out = run5.run_all5(sess, immutability=earlier_trees_immutability)
    finally:
        rep = sampler.stop()
        art.write_json5(cfg.session_dir / "memory_summary.json", rep)
    left = wait_until_no_process(BATTLESHIP_IMAGE, timeout=60.0)
    art.write_json5(cfg.session_dir / "leftover_processes.json", {"battleship_pids_after_the_run": left, "utc": utc()})
    print(json.dumps(out["rule"], indent=1, default=str)[:5000])
    if left:
        print(f"WARNING: BattleShip processes still alive after the run: {left}")
    return 0


def cmd_verify_run() -> int:
    import m8_sd1_report as rpt5

    rep = art.stamp(rpt5.verify_run5(SD1_ROOT, RD4_ROOT, RD3_ROOT, RD2_ROOT, RD1_ROOT, SESSION))
    print(json.dumps(rep, indent=1, default=str))
    return 0 if rep["ok"] else 1


def cmd_report() -> int:
    import m8_sd1_report as rpt5

    print(json.dumps(art.stamp(rpt5.full_report5(SD1_ROOT, RD4_ROOT, RD3_ROOT, RD2_ROOT, RD1_ROOT, SESSION)), indent=1, default=str))
    return 0


def cmd_open_check() -> int:
    op = open_protocol5(record_reference=RECORD_REFERENCE)
    print(json.dumps(art.stamp({k: v for k, v in op.items() if k not in ("overlay", "facts1", "facts2", "facts3", "facts4", "inherited", "record_candidate")}), indent=1, default=str))
    return 0 if op["ok"] else 1


def cmd_status() -> int:
    st = SD1_ROOT / "sessions" / SESSION / "state.json"
    out = {"sd1_root_exists": SD1_ROOT.exists(), "approval_present": APPROVAL.is_file(), "source_fingerprint": source_fingerprint(),
           "state": json.loads(st.read_text(encoding="utf-8-sig")) if st.is_file() else None}
    print(json.dumps(art.stamp(out), indent=1, default=str))
    return 0


def cmd_template() -> int:
    ident = identity()
    rec = dict(ident, approval="PENDING (a reviewer replaces this with APPROVED ... and fills the authorisation and the source snapshot entries; this command never writes the record)",
               revision=1, authorisation={"source": "<the user's message>", "authorised_on": "<YYYY-MM-DD>", "text": ["<what is authorised, once>"]},
               source_snapshot={"dest": "D:\\BattleShip_source_snapshots\\<date>_m8_sd1", "snapshot_json_sha256": "<sha256>", "result": "PASS", "files": "<n>", "git_head": ident["git_head"],
                                "independent_verification": "<tool verify and an independent PowerShell re-hash>"},
               backup_coverage_before_approval="<combined coverage record>")
    print(json.dumps(art.stamp(rec), indent=1, default=str))
    return 0


# -- the results record (the exact rule) ---------------------------------------------------------------------------------------------------------


def _real_date(s: str) -> bool:
    try:
        y, m, d = (int(x) for x in s.split("-"))
    except ValueError:
        return False
    import calendar

    return 1 <= m <= 12 and 1 <= d <= calendar.monthrange(y, m)[1]


def results_record_problems(path: Path, docs_dir: Optional[Path] = None) -> List[str]:
    """The exact rule: a regular file named rl_m8_sd1_results_<YYYY-MM-DD>.md (a real date) in docs/, non-empty, UTF-8 without NUL, ending with a newline, whose first line is
    `# M8-sd1 results (<that date>)` and which carries a `## ` section; and no other entry of docs/ whose name starts with rl_m8_sd1_results, in any case (a draft is refused)."""
    path = Path(path)
    docs = Path(docs_dir if docs_dir is not None else REPO_ROOT / "docs")
    problems: List[str] = []
    m = RESULTS_RECORD_RE.match(path.name)
    if m is None or not _real_date(m.group("date")):
        problems.append(f"the name {path.name!r} is not rl_m8_sd1_results_<YYYY-MM-DD>.md with a real date")
    if not path.is_file():
        problems.append(f"{path} is not a regular file")
        return problems
    if path.parent.resolve() != docs.resolve():
        problems.append(f"{path} is not directly under {docs}")
    raw = path.read_bytes()
    if not raw:
        problems.append("the record is empty")
        return problems
    if b"\x00" in raw:
        problems.append("the record holds a NUL byte")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        problems.append("the record is not UTF-8")
        return problems
    if not text.endswith("\n"):
        problems.append("the record does not end with a newline")
    lines = text.splitlines()
    want = RESULTS_TITLE.format(date=m.group("date")) if m else None
    if not lines or want is None or not lines[0].rstrip("\r").startswith(want):
        problems.append(f"the first line is not {want!r}")
    if not any(ln.startswith("## ") for ln in lines[1:]):
        problems.append("no `## ` section follows the title")
    if docs.is_dir():
        for p in sorted(docs.iterdir()):
            if p.name.lower().startswith(RESULTS_RECORD_PREFIX) and p.resolve() != path.resolve():
                problems.append(f"another entry of docs/ starts with {RESULTS_RECORD_PREFIX}: {p.name} (a draft or a second record is refused)")
    return problems


def cmd_check_results_record(path: Path) -> int:
    problems = results_record_problems(Path(path))
    print(json.dumps(art.stamp({"path": str(path), "ok": not problems, "problems": problems}), indent=1))
    return 0 if not problems else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("status", "verify-run", "approval-template", "run", "report", "open-check", "fingerprint"):
        sub.add_parser(n)
    p = sub.add_parser("preflight")
    p.add_argument("--skip-unit", action="store_true")
    c = sub.add_parser("check-results-record")
    c.add_argument("--path", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "status":
        return cmd_status()
    if a.cmd == "fingerprint":
        print(source_fingerprint())
        return 0
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
    if a.cmd == "check-results-record":
        return cmd_check_results_record(a.path)
    return cmd_run()


if __name__ == "__main__":
    sys.exit(main())
