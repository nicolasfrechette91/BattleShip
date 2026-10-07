#!/usr/bin/env python3
"""M9-g3 session driver: one session of the g3 line (the replenishing controlled frontier).

    python -B rl/m9_g3_session.py status [--session 1]
    python -B rl/m9_g3_session.py preflight [--skip-unit] [--session 1]   # no game: tests, pins, the seven protected trees, the reused tape, D: coverage, readiness, budget, approval
    python -B rl/m9_g3_session.py approval-template [--session 1]         # prints the record a reviewer would write (never writes it)
    python -B rl/m9_g3_session.py run [--session 1]                       # refused unless the preflight passes, including the approval
    python -B rl/m9_g3_session.py verify-run [--session 1]                # read-only post-run verification of the recorded session
    python -B rl/m9_g3_session.py report [--session 1]                    # the reported readings of the recorded session

Design: docs/rl_m9_g2_stop_review_2026-10-06.md (section 3) as decided in docs/rl_m9_g3_decisions_2026-10-06.md. The session writes only runs/m9_g3/s<k>/;
the four M8 trees, runs/m9_g1, runs/m9_g1_eval, runs/m9_g2/s1 and every other g3 session tree are read-only and must stay byte-identical to their D:
increments. The tape baseline is runs/m9_g2/s1/session/tape_baseline.json, read by digest. Light top-level imports only (spawned workers re-import this
script). Session s1 is the only one this file is run for in this preparation; s >= 2 needs its own approval, its predecessor's recorded increment and the
resume inputs (g2 decision R14).

The ONE authorised edit of a tracked file (decision 9: the fragment assembly in rl/m9_eval_tests.py) is pinned below by its digest before and after; the
preflight tolerates exactly that modified tracked file at exactly that digest and nothing else.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))

import m8_rd_resume as rs  # noqa: E402
import m8_rd_session as ses1  # noqa: E402
import m9_artifacts as A  # noqa: E402
import m9_contract as C  # noqa: E402
import m9_g2_contract as G2  # noqa: E402
import m9_g2_session as S2  # noqa: E402
import m9_g3_contract as G  # noqa: E402
import m9_g3_rule as R  # noqa: E402
import m9_session as G1  # noqa: E402

REPO_ROOT = ses1.REPO_ROOT
RL = ses1.RL
RUNS = ses1.RUNS
LINE_ROOT = RUNS / "m9_g3"
EXECUTABLE = ses1.EXECUTABLE
BACKUP_ROOT = ses1.BACKUP_ROOT
G2_S1_ROOT = RUNS / "m9_g2" / "s1"
G2_S1_INCREMENT = BACKUP_ROOT / "2026-10-06_incr_m9_g2_s1"
G2_S1_FACTS = {"files": 9779, "bytes": 988_807_605, "increment_manifest_sha256": "4ad2c3dc240ef1bbbce9dfe1c924efa9936d0a1ce5db51df099ce4736fd8b45f"}
TREES: Tuple[Tuple[str, Path, Path, Mapping[str, Any]], ...] = tuple(S2.TREES) + (("m9_g2_s1", G2_S1_ROOT, G2_S1_INCREMENT, G2_S1_FACTS),)
TAPE_SOURCE = REPO_ROOT / G.TAPE_REUSE["source"]
TAPE_RECORDS = REPO_ROOT / G.TAPE_REUSE["records"]
CODE_FILES = ("m9_g3_contract.py", "m9_g3_frontier.py", "m9_g3_rule.py", "m9_g3_probe.py", "m9_g3_train.py", "m9_g3_run.py", "m9_g3_report.py", "m9_g3_session.py", "m9_g3_snapshot.py",
              "m9_g3_tests.py", "m9_eval_tests.py") + tuple(S2.CODE_FILES)
DOC_FILES = ("docs/rl_m9_g3_decisions_2026-10-06.md", "docs/rl_m9_g3_implementation.md", "docs/rl_m9_g2_stop_review_2026-10-06.md", "docs/rl_m9_g2_s1_results_2026-10-06.md") + tuple(S2.DOC_FILES)
SNAPSHOT_DEST_DEFAULT = Path(r"D:\BattleShip_source_snapshots\2026-10-06_m9_g3_s1")
# decision 9: the ONE authorised edit of a tracked file (two lines of its own source guard assembled from fragments); pinned by digest before and after
AUTHORISED_TRACKED_EDITS: Dict[str, Dict[str, str]] = {
    "rl/m9_eval_tests.py": {"sha256_before": "05c6765f5694eb08b18b081cab4e585ad34d0bbe3813b50c59b4a49f0f03c9d8", "sha256_after": "7151c34bee4c6e9cd20697d902dc8e8e10a8e4eeee67cee93f429acbe12edb84",
                            "what": "decision 9 (the stop review's option a): the six forbidden literals of its own source guard assembled from fragments; two lines; nothing else"},
}


def run_root(k: int) -> Path:
    return LINE_ROOT / f"s{int(k)}"


def approval_path(k: int) -> Path:
    return REPO_ROOT / "docs" / f"rl_m9_g3_s{int(k)}_approval.json"


APPROVAL = approval_path(1)
RUN_ROOT = run_root(1)


def utc() -> str:
    return A.utc()


def sha256_file(p: Path) -> str:
    return G1.sha256_file(Path(p))


# -- the protected trees -------------------------------------------------------------------------------------------------------------


def trees_state(k: int = 1) -> Dict[str, Any]:
    """Each of the seven protected trees equals its D: increment (paths, sizes, mtimes, sha256; the increment's own record PASS) with the registered counts."""
    out: Dict[str, Any] = {}
    for name, root, inc, expect in TREES:
        imm = rs.rd1_immutability(root, inc)
        probs = list(imm.get("problems", []))
        for ek, ik in (("files", "files"), ("bytes", "bytes"), ("increment_manifest_sha256", "manifest_sha256")):
            if imm.get(ik) != expect[ek]:
                probs.append(f"the increment's {ik} {imm.get(ik)!r} differs from the registered {expect[ek]!r}")
        out[name] = {"ok": bool(imm.get("ok")) and not probs, "files": imm.get("files"), "bytes": imm.get("bytes"), "manifest_sha256": imm.get("manifest_sha256"), "increment": inc.name, "problems": probs}
    out["ok"] = all(v["ok"] for kk, v in out.items() if kk != "ok")
    return out


def earlier_trees(k: int = 1) -> Dict[str, Any]:
    s = trees_state(k)
    return {"ok": s["ok"], "problems": [f"{kk}: {p}" for kk, v in s.items() if kk != "ok" for p in v["problems"]], **{kk: {x: v[x] for x in ("ok", "files", "manifest_sha256", "bytes")} for kk, v in s.items() if kk != "ok"}}


def write_guard_roots(k: int = 1) -> List[Path]:
    """Every tree the session or a worker must never write: each other directory under runs/ (the M8 trees, runs/m9_g1, runs/m9_g1_eval, runs/m9_g2), every other g3 session tree, rl/, docs/."""
    roots = [p for p in RUNS.iterdir() if p.is_dir() and p.name != LINE_ROOT.name]
    if LINE_ROOT.is_dir():
        roots += [p for p in LINE_ROOT.iterdir() if p.is_dir() and p.name != f"s{int(k)}"]
    roots += [RL, REPO_ROOT / "docs"]
    return roots


# -- the reused tape and the authorised edit ------------------------------------------------------------------------------------------------


def tape_reuse_spec() -> Dict[str, Any]:
    return {"path": str(TAPE_SOURCE), "file_sha256": G.TAPE_REUSE["file_sha256"], "content_sha256": G.TAPE_REUSE["content_sha256"], "executable_sha256": G.TAPE_REUSE["measured_with_executable_sha256"]}


def tape_reuse_problems() -> List[str]:
    """The reused table exists at its registered path with the registered file and content digests, is pinned at every landing, and was measured with the executable now."""
    import m9_g2_tape as TP

    out: List[str] = []
    if not TAPE_SOURCE.is_file():
        return [f"the reused tape baseline {TAPE_SOURCE} is missing"]
    if sha256_file(TAPE_SOURCE) != G.TAPE_REUSE["file_sha256"]:
        out.append("the reused tape baseline's file sha256 differs from the registered")
    tb = json.loads(TAPE_SOURCE.read_text(encoding="utf-8"))
    if TP.table_digest(tb) != tb.get("sha256") or tb.get("sha256") != G.TAPE_REUSE["content_sha256"]:
        out.append("the reused tape baseline's content digest differs from the registered")
    if not tb.get("pinned") or any(not v.get("pinned") or v.get("B") is None for v in dict(tb.get("landings") or {}).values()):
        out.append("the reused tape baseline is not pinned at every landing")
    if EXECUTABLE.is_file() and sha256_file(EXECUTABLE) != G.TAPE_REUSE["measured_with_executable_sha256"]:
        out.append("the executable differs from the one the reused tape baseline was measured with")
    if not TAPE_RECORDS.is_file():
        out.append(f"the measuring session's T0 records {TAPE_RECORDS} are missing (the drift check needs them)")
    return out


def git_problems() -> Tuple[List[str], Dict[str, Any]]:
    """Tracked files equal HEAD except the authorised edits at their pinned post-edit digests; git status shows nothing but new files and those edits."""
    problems: List[str] = []
    changed = ses1.tracked_changes()
    seen: Dict[str, Any] = {}
    for rel in changed:
        auth = AUTHORISED_TRACKED_EDITS.get(rel)
        now = sha256_file(REPO_ROOT / rel) if (REPO_ROOT / rel).is_file() else None
        if auth is None:
            problems.append(f"tracked file differs from HEAD and is not an authorised edit: {rel}")
        elif now != auth["sha256_after"]:
            problems.append(f"the authorised edit {rel} is not at its pinned digest ({str(now)[:16]} != {auth['sha256_after'][:16]})")
        seen[rel] = {"sha256_now": now, "authorised": auth is not None, "at_pinned_digest": auth is not None and now == auth["sha256_after"]}
    for ln in ses1.untracked_not_new():
        rel = ln[3:].strip()
        if not (ln.startswith(" M") and rel in AUTHORISED_TRACKED_EDITS):
            problems.append(f"git status shows an entry other than a new file or the authorised edit: {ln}")
    return problems, {"tracked_changes": seen, "authorised_edits": {k: v["sha256_after"] for k, v in AUTHORISED_TRACKED_EDITS.items()}}


# -- identity and approval ------------------------------------------------------------------------------------------------------------


def identity(k: int = 1) -> Dict[str, Any]:
    import m9_g3_frontier as F
    import m9_g3_run as RUN3

    dr = ses1.d_records_digest()
    pins = G1.archive_pins()
    return {"gate": G.GATE, "line": G.LINE_ID, "session": int(k), "scope": G.SCOPE, "milestone": G.MILESTONE, "task": dict(G.TASK), "contract_sha256": G.contract_digest(),
            "line_contract_sha256": G.line_contract_digest(), "rules": {"frontier": G.FRONTIER_RULE_ID, "frontier_sha256": F.contract_digest(), "tape": G.TAPE_RULE_ID, "s1": G.S1_RULE_ID,
                                                                       "s1_sha256": R.s1_rule_digest(), "line": G.LINE_RULE_ID, "line_sha256": R.line_rule_digest()},
            "spacing": {"unit": G.SPACING_UNIT, "cap": G.SPACING_CAP, "need": {str(f): G.spacing_need(f) for f in range(8)}}, "line_budget": {str(kk): v for kk, v in sorted(G.LINE_BUDGET.items())},
            "g2_contract_sha256": G2.contract_digest(), "g2_line_contract_sha256": G2.line_contract_digest(), "g1_contract_sha256": C.contract_digest(), "key_strings": dict(G.KEYS),
            "tape_reuse": dict(G.TAPE_REUSE), "authorised_tracked_edits": {kk: dict(v) for kk, v in AUTHORISED_TRACKED_EDITS.items()},
            "executable_sha256": sha256_file(EXECUTABLE) if EXECUTABLE.is_file() else None, "runtime_files": ses1.runtime_pins(),
            "frozen_sha256": G1.frozen_pins(), "archive_pins": {"executable_sha256": pins.get("executable_sha256"), "frozen_sha256": pins.get("frozen_sha256"), "runtime_files": pins.get("runtime_files")},
            "flags": {"train": C.FLAGS_TRAIN, "eval": C.FLAGS_EVAL, "verify": C.FLAGS_VERIFY}, "lineages": G1.lineage_facts(),
            "trees": {kk: {x: v[x] for x in ("files", "bytes", "manifest_sha256", "increment")} for kk, v in trees_state(k).items() if kk != "ok"},
            "caps": {"wall_caps_s": dict(G.WALL_CAPS_S), "tick_caps": dict(G.TICK_CAPS), "transition_cap": G.TRANSITION_CAP, "global_cap_s": G.GLOBAL_CAP_S, "memory_caps_mb": dict(G.MEMORY_CAPS_MB),
                     "max_battleship_processes": G.MAX_BATTLESHIP_PROCESSES, "split": list(G.SPLIT), "probe_slots": G.PROBE_SLOTS},
            "budget": RUN3.budget_projection(), "ppo": dict(G.PPO), "readiness": ses1.READINESS, "code": {f"rl/{f}": sha256_file(RL / f) for f in CODE_FILES if (RL / f).is_file()},
            "docs_sha256": {f: sha256_file(REPO_ROOT / f) for f in DOC_FILES if (REPO_ROOT / f).is_file()}, "git_head": ses1.git("rev-parse", "HEAD").strip(),
            "d_records": {"folders": dr["folders"], "digest": dr["digest"]}}


def approval_status(k: int = 1, path: Optional[Path] = None, want: Optional[Mapping[str, Any]] = None) -> Tuple[bool, str]:
    return ses1.approval_status(Path(approval_path(k) if path is None else path), want if want is not None else identity(k))


# -- preflight ----------------------------------------------------------------------------------------------------------------------------


def _run_unit_suites() -> Tuple[Dict[str, Any], List[str]]:
    import subprocess

    problems: List[str] = []
    rep: Dict[str, Any] = {}
    r = subprocess.run([sys.executable, "-B", str(RL / "m9_g3_tests.py"), "unit"], capture_output=True, text=True, cwd=REPO_ROOT)
    rep["unit_suite_m9_g3"] = (r.stdout.strip().splitlines() or [r.stderr[-300:]])[-1:]
    if r.returncode != 0:
        problems.append("unit_suite_m9_g3 failed")
    r = subprocess.run([sys.executable, "-B", str(RL / "m9_g3_rule.py"), "self-test"], capture_output=True, text=True, cwd=REPO_ROOT)
    rep["rule_self_test_m9_g3"] = (r.stdout.strip().splitlines() or [r.stderr[-300:]])[-1:]
    if r.returncode != 0:
        problems.append("rule_self_test_m9_g3 failed")
    return rep, problems


def preflight(k: int = 1, *, run_unit: bool = True) -> Dict[str, Any]:
    import m9_g3_run as RUN3

    problems: List[str] = []
    rep: Dict[str, Any] = {"utc": utc(), "scope": G.SCOPE, "gate": G.GATE, "session": int(k)}
    if not sys.flags.dont_write_bytecode:
        problems.append("python was not started with -B (a compiled module written under rl/ would be a write-guard violation)")
    root = run_root(k)
    if root.exists():
        problems.append(f"{root.relative_to(REPO_ROOT)} exists (never overwritten)")
    if int(k) != 1:
        problems.append("only session 1 is prepared by this preflight; a later session needs its predecessor's recorded increment and resume inputs (g2 decision R14)")
    if run_unit:
        r, p = _run_unit_suites()
        rep.update(r)
        problems += p
    if not EXECUTABLE.is_file():
        problems.append(f"missing executable {EXECUTABLE}")
    ident = identity(k)
    rep["executable_sha256"] = ident["executable_sha256"]
    rep["git_head"] = ident["git_head"]
    gp, ginfo = git_problems()
    rep["git"] = ginfo
    problems += gp
    rep["git_status_new_files"] = [ln[3:] for ln in ses1.git("status", "--porcelain").splitlines() if ln.startswith("??")]
    pins = G1.pins_problems()
    rep["pins"] = pins or "executable, runtime files and frozen configuration equal the archive's pins"
    problems += pins
    tp = tape_reuse_problems()
    rep["tape_reuse"] = tp or f"the reused tape baseline equals its registered digests ({G.TAPE_REUSE['file_sha256'][:16]} / {G.TAPE_REUSE['content_sha256'][:16]}), pinned, measured with the executable now"
    problems += [f"tape reuse: {p}" for p in tp]
    cvars = ses1.controller_cvar_problems(G1.EXE_DIR / "BattleShip.cfg.json")
    rep["controller_cvars"] = cvars or "absent or zero"
    if cvars:
        problems.append(f"controller-rule CVars set in BattleShip.cfg.json: {cvars}")
    try:
        import m7n_status_table as st

        st.load_table()
        rep["status_table"] = "digest verified"
    except Exception as exc:                                         # noqa: BLE001
        problems.append(f"status table: {type(exc).__name__}: {exc}")
    ts = trees_state(k)
    rep["trees"] = {kk: (v if kk == "ok" else {x: v[x] for x in ("ok", "files", "bytes", "manifest_sha256", "increment", "problems")}) for kk, v in ts.items()}
    if not ts["ok"]:
        problems += [f"tree {kk}: {p}" for kk, v in ts.items() if kk != "ok" for p in v["problems"]]
    try:
        import m9_lineages as L

        lins = L.load_registered(REPO_ROOT)
        rep["lineages"] = {n: {"words": ln.length, "native_action_digest": ln.native_action_digest[:16]} for n, ln in lins.items()}
    except Exception as exc:                                         # noqa: BLE001
        problems.append(f"lineages: {type(exc).__name__}: {exc}")
    cov = ses1.combined_coverage()
    rep["backup"] = {kk: cov.get(kk) for kk in ("ok", "reason", "source_files", "uncovered", "increments", "skipped")}
    if not cov.get("ok"):
        problems.append(f"backup prerequisite not met: {cov.get('reason')}")
    procs = ses1.game_processes()
    if procs:
        problems.append(f"BattleShip already running: {procs}")
    rd = ses1.readiness()
    rep["readiness"] = rd
    problems += [f"readiness: {p}" for p in rd["problems"]]
    bp = RUN3.budget_projection()
    rep["budget"] = bp
    if not bp["fits_global_cap_pessimistic"]:
        problems.append("the pessimistic projection does not fit the 145-minute session cap")
    ok, why = approval_status(k, approval_path(k), ident)
    rep["approval"] = why
    ap = approval_path(k)
    approval = json.loads(ap.read_text(encoding="utf-8")) if ap.is_file() else None
    if approval is not None:
        try:
            A.check(approval, "the approval record")
        except A.ArtifactError as exc:
            problems.append(f"approval record metadata: {exc}")
    sok, swhy = ses1.snapshot_status(approval)
    rep["source_snapshot"] = swhy
    if not sok:
        problems.append(f"source snapshot: {swhy}")
    if not ok:
        problems.append(why)
    rep["problems"] = problems
    rep["ok"] = not problems
    return rep


# -- the real run --------------------------------------------------------------------------------------------------------------------------


def real_hooks() -> Any:
    """g2's real hooks (the frozen snapshots, the probe and audit policies, PPO.load for a resume, the v3 flattening), unchanged."""
    return S2.real_hooks()


def cmd_run(k: int = 1) -> int:
    from m7_runtime import BATTLESHIP_IMAGE, install_kill_on_close_job, wait_until_no_process

    import m8_rd2_worker as w2
    import m8_rd_worker as mw
    import m9_g3_run as RUN3

    pf = preflight(k)
    if not pf["ok"]:
        print(json.dumps(A.stamp(pf), indent=1, default=str))
        print("refused: preflight problems (see above); nothing was launched")
        return 2
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    install_kill_on_close_job()
    mw.ProvenanceGuard.install()
    w2.WriteGuard.install(write_guard_roots(k))
    root = run_root(k)
    ap = approval_path(k)
    cfg = RUN3.G3Config(root=root, session=int(k), session_id=f"s{int(k)}", landings=G.LANDINGS, tape_reuse=tape_reuse_spec(), tape_source_records=TAPE_RECORDS,
                        open_record={"approval_sha256": sha256_file(ap), "preflight": {kk: pf.get(kk) for kk in ("executable_sha256", "git_head", "git", "readiness", "backup", "approval", "source_snapshot",
                                                                                                                  "unit_suite_m9_g3", "rule_self_test_m9_g3", "trees", "pins", "tape_reuse", "budget")},
                                     "identity": {kk: v for kk, v in identity(k).items() if kk not in ("code", "docs_sha256", "lineages", "trees", "budget")}})
    root.mkdir(parents=True)
    cfg.session_dir.mkdir(parents=True)
    shutil.copyfile(ap, cfg.session_dir / "approval_copy.json")
    sampler = G1.make_sampler(cfg.session_dir / "memory_tree.jsonl", cfg.memory_caps_mb)
    sampler.start()
    out: Dict[str, Any] = {}
    try:
        env = G1.build_real_env(cfg, sampler, run_root=root, protect=write_guard_roots(k))
        env.earlier_trees = lambda: earlier_trees(k)
        env.landings = G.LANDINGS
        sess = RUN3.G3Session(cfg, env, real_hooks())
        out = sess.run()
    finally:
        rep = sampler.stop()
        A.write_json(cfg.session_dir / "memory_summary.json", A.stamp(rep))
    left = wait_until_no_process(BATTLESHIP_IMAGE, timeout=60.0)
    A.write_json(cfg.session_dir / "leftover_processes.json", A.stamp({"battleship_pids_after_the_run": left}))
    print(json.dumps({kk: out.get(kk) for kk in ("outcome", "D", "R", "reasons", "line", "route_mastered_ticks", "frontier")}, indent=1, default=str)[:4000])
    if left:
        print(f"WARNING: BattleShip processes still alive after the run: {left}")
    return 0


def cmd_verify_run(k: int = 1) -> int:
    import m9_g3_report as RPT

    rep = RPT.verify_run(run_root(k))
    print(json.dumps(A.stamp(rep), indent=1, default=str))
    return 0 if rep["ok"] else 1


def cmd_report(k: int = 1) -> int:
    import m9_g3_report as RPT

    print(json.dumps(A.stamp(RPT.full_report(run_root(k))), indent=1, default=str))
    return 0


def cmd_status(k: int = 1) -> int:
    st = run_root(k) / "session" / "state.json"
    print(json.dumps({"run_root_exists": run_root(k).exists(), "approval_present": approval_path(k).is_file(), "state": json.loads(st.read_text(encoding="utf-8")) if st.is_file() else None},
                     indent=1, default=str))
    return 0


def cmd_template(k: int = 1) -> int:
    ident = identity(k)
    rec = dict(ident, approval="PENDING (a reviewer replaces this with APPROVED ... and fills the authorisation and the source snapshot entries; this command never writes the record)",
               revision=1, authorisation={"source": "<the user's message>", "text": ["<what is authorised, once>"]},
               source_snapshot={"dest": str(SNAPSHOT_DEST_DEFAULT), "snapshot_json_sha256": "<sha256>", "result": "PASS", "files": "<n>", "git_head": ident["git_head"],
                                "independent_verification": "<tool verify and an independent PowerShell re-hash>"},
               task=dict(G.TASK), created_utc=utc())
    print(json.dumps(rec, indent=1, default=str))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("status", "verify-run", "approval-template", "run", "report", "preflight"):
        p = sub.add_parser(n)
        p.add_argument("--session", type=int, default=1)
        if n == "preflight":
            p.add_argument("--skip-unit", action="store_true")
    a = ap.parse_args(argv)
    k = int(a.session)
    if a.cmd == "status":
        return cmd_status(k)
    if a.cmd == "preflight":
        rep = preflight(k, run_unit=not a.skip_unit)
        print(json.dumps(A.stamp(rep), indent=1, default=str))
        return 0 if rep["ok"] else 1
    if a.cmd == "approval-template":
        return cmd_template(k)
    if a.cmd == "verify-run":
        return cmd_verify_run(k)
    if a.cmd == "report":
        return cmd_report(k)
    return cmd_run(k)


if __name__ == "__main__":
    sys.exit(main())
