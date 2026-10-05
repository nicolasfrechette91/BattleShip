#!/usr/bin/env python3
"""M9-g1 checkpoint evaluation: the session driver (diagnostic only; no training, no optimizer).

    python -B rl/m9_eval_session.py status
    python -B rl/m9_eval_session.py preflight [--skip-unit]   # no game: tests, pins, checkpoint digests, the M8 and M9-g1 trees, D: coverage, readiness, approval
    python -B rl/m9_eval_session.py approval-template         # prints the record a reviewer would write (never writes it)
    python -B rl/m9_eval_session.py run                       # refused unless the preflight passes, including the approval
    python -B rl/m9_eval_session.py verify-run                # read-only re-derivation of the recorded evaluation
    python -B rl/m9_eval_session.py report                    # the recorded outcome and readings

Plan: docs/rl_m9_g1_checkpoint_eval_plan_2026-10-04.md. Writes only runs/m9_g1_eval/. runs/m9_g1/ and the four M8 trees are read-only and must stay
byte-identical to their D: increments (checked at the preflight and at the close). Light top-level imports only (spawned workers re-import modules).
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
import m9_eval_ckpt as K  # noqa: E402
import m9_eval_policy as POL  # noqa: E402
import m9_session as G1  # noqa: E402

REPO_ROOT = ses1.REPO_ROOT
RL = ses1.RL
RUNS = ses1.RUNS
RUN_ROOT = RUNS / K.RUN_NAME
APPROVAL = REPO_ROOT / "docs" / "rl_m9_g1_eval_approval.json"
EXECUTABLE = ses1.EXECUTABLE
BACKUP_ROOT = ses1.BACKUP_ROOT
G1_ROOT = RUNS / "m9_g1"
G1_INCREMENT = BACKUP_ROOT / "2026-10-04_incr_m9_g1"
G1_FACTS = {"files": 2740, "bytes": 354_131_925, "increment_manifest_sha256": "92ba5481acbb0ab9c0a17e19dffeb48965e68197feb6a44064524ccdf2419eac"}
TREES: Tuple[Tuple[str, Path, Path, Mapping[str, Any]], ...] = tuple(G1.M8_TREES) + (("m9_g1", G1_ROOT, G1_INCREMENT, G1_FACTS),)
SNAPSHOT_DEST_DEFAULT = Path(r"D:\BattleShip_source_snapshots\2026-10-04_m9_g1_eval")
CODE_FILES = ("m9_eval_policy.py", "m9_eval_ckpt.py", "m9_eval_session.py", "m9_eval_snapshot.py", "m9_eval_tests.py") + tuple(G1.CODE_FILES)
DOC_FILES = (K.PLAN_DOC, "docs/rl_m9_policy_proposal_2026-10-03.md", "docs/rl_m9_g1_decisions_2026-10-04.md", "docs/rl_m9_g1_implementation.md",
             "docs/rl_m9_g1_results_2026-10-04.md")


def utc() -> str:
    return A.utc()


def sha256_file(p: Path) -> str:
    return G1.sha256_file(Path(p))


# -- the protected trees -------------------------------------------------------------------------------------------------------------------


def trees_state() -> Dict[str, Any]:
    """Each protected tree equals its D: increment (paths, sizes, mtimes, sha256; the increment's own record PASS) with the registered counts."""
    out: Dict[str, Any] = {}
    for name, root, inc, expect in TREES:
        imm = rs.rd1_immutability(root, inc)
        probs = list(imm.get("problems", []))
        for ek, ik in (("files", "files"), ("bytes", "bytes"), ("increment_manifest_sha256", "manifest_sha256")):
            if imm.get(ik) != expect[ek]:
                probs.append(f"the increment's {ik} {imm.get(ik)!r} differs from the registered {expect[ek]!r}")
        out[name] = {"ok": bool(imm.get("ok")) and not probs, "files": imm.get("files"), "bytes": imm.get("bytes"), "manifest_sha256": imm.get("manifest_sha256"),
                     "increment": inc.name, "problems": probs}
    out["ok"] = all(v["ok"] for k, v in out.items() if k != "ok")
    return out


def earlier_trees() -> Dict[str, Any]:
    s = trees_state()
    return {"ok": s["ok"], "problems": [f"{k}: {p}" for k, v in s.items() if k != "ok" for p in v["problems"]],
            **{k: {kk: v[kk] for kk in ("ok", "files", "manifest_sha256", "bytes")} for k, v in s.items() if k != "ok"}}


def write_guard_roots() -> List[Path]:
    """Every tree the session or a worker must never write: each other directory under runs/ (runs/m9_g1 and the M8 trees included), rl/, docs/."""
    roots = [p for p in RUNS.iterdir() if p.is_dir() and p.name != K.RUN_NAME]
    roots += [RL, REPO_ROOT / "docs"]
    return roots


# -- identity and approval ------------------------------------------------------------------------------------------------------------------


def identity() -> Dict[str, Any]:
    import m9_curriculum as CU
    import m9_sticky as S

    dr = ses1.d_records_digest()
    pins = G1.archive_pins()
    lf = G1.lineage_facts()
    return {"evaluation": K.EVAL_ID, "scope": K.SCOPE, "milestone": C.MILESTONE, "task": dict(C.TASK), "contract_sha256": K.contract_digest(),
            "description": K.description(), "policy_contract": POL.contract_description(), "sticky_contract": S.contract_description()["contract"],
            "m9_contract_sha256": C.contract_digest(), "m9_curriculum_sha256": CU.contract_digest(),
            "executable_sha256": sha256_file(EXECUTABLE) if EXECUTABLE.is_file() else None, "runtime_files": ses1.runtime_pins(), "frozen_sha256": G1.frozen_pins(),
            "archive_pins": {"executable_sha256": pins.get("executable_sha256"), "frozen_sha256": pins.get("frozen_sha256"), "runtime_files": pins.get("runtime_files")},
            "lineage": lf.get(K.LINEAGE), "pin_tick0": lf.get("pin_tick0"),
            "trees": {k: {kk: v[kk] for kk in ("files", "bytes", "manifest_sha256", "increment")} for k, v in trees_state().items() if k != "ok"},
            "budget": K.budget_projection(), "readiness": ses1.READINESS, "code": {f"rl/{f}": sha256_file(RL / f) for f in CODE_FILES if (RL / f).is_file()},
            "docs_sha256": {f: sha256_file(REPO_ROOT / f) for f in DOC_FILES if (REPO_ROOT / f).is_file()}, "git_head": ses1.git("rev-parse", "HEAD").strip(),
            "d_records": {"folders": dr["folders"], "digest": dr["digest"]}}


def approval_status(path: Optional[Path] = None, want: Optional[Mapping[str, Any]] = None) -> Tuple[bool, str]:
    return ses1.approval_status(Path(APPROVAL if path is None else path), want if want is not None else identity())


# -- preflight --------------------------------------------------------------------------------------------------------------------------------


def _run_unit_suite() -> Tuple[Dict[str, Any], List[str]]:
    import subprocess

    r = subprocess.run([sys.executable, "-B", str(RL / "m9_eval_tests.py"), "unit"], capture_output=True, text=True, cwd=REPO_ROOT)
    rep = {"unit_suite_m9_eval": (r.stdout.strip().splitlines() or [r.stderr[-300:]])[-1:]}
    return rep, ([] if r.returncode == 0 else ["unit_suite_m9_eval failed"])


def preflight(*, run_unit: bool = True) -> Dict[str, Any]:
    problems: List[str] = []
    rep: Dict[str, Any] = {"utc": utc(), "scope": K.SCOPE}
    if not sys.flags.dont_write_bytecode:
        problems.append("python was not started with -B (a compiled module written under rl/ would be a write-guard violation)")
    if RUN_ROOT.exists():
        problems.append(f"{RUN_ROOT.relative_to(REPO_ROOT)} exists (never overwritten)")
    if run_unit:
        r, p = _run_unit_suite()
        rep.update(r)
        problems += p
    if not EXECUTABLE.is_file():
        problems.append(f"missing executable {EXECUTABLE}")
    pp = POL.pin_problems(K.CHECKPOINTS, REPO_ROOT)
    rep["checkpoint_pins"] = pp or f"{len(K.CHECKPOINTS)} checkpoint digests equal their pins"
    problems += [f"checkpoint pin: {p}" for p in pp]
    ident = identity()
    rep["executable_sha256"] = ident["executable_sha256"]
    rep["git_head"] = ident["git_head"]
    changed = ses1.tracked_changes()
    if changed:
        problems.append(f"tracked files differ from HEAD: {changed[:6]}")
    odd = ses1.untracked_not_new()
    if odd:
        problems.append(f"git status shows entries other than new files: {odd[:6]}")
    rep["git_status_new_files"] = [ln[3:] for ln in ses1.git("status", "--porcelain").splitlines() if ln.startswith("??")]
    pins = G1.pins_problems()
    rep["pins"] = pins or "executable, runtime files and frozen configuration equal the archive's pins"
    problems += pins
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
    ts = trees_state()
    rep["trees"] = {k: (v if k == "ok" else {kk: v[kk] for kk in ("ok", "files", "bytes", "manifest_sha256", "increment", "problems")}) for k, v in ts.items()}
    if not ts["ok"]:
        problems += [f"tree {k}: {p}" for k, v in ts.items() if k != "ok" for p in v["problems"]]
    if not (G1_ROOT / "lineages" / K.LINEAGE / "registration.json").is_file():
        problems.append("the registered T_clear tables of runs/m9_g1 are missing")
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
    bp = K.budget_projection()
    rep["budget"] = bp
    if not bp["fits"]:
        problems.append("the pessimistic projection does not fit the 45-minute session cap")
    ok, why = approval_status(APPROVAL, ident)
    rep["approval"] = why
    approval = json.loads(APPROVAL.read_text(encoding="utf-8")) if APPROVAL.is_file() else None
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


# -- the real run ------------------------------------------------------------------------------------------------------------------------------


def build_session(cfg: K.EvalConfig, sampler: Any = None) -> K.EvalSession:
    import m7n_obs as mn
    import m9_lineages as L

    lin = L.load_registered(REPO_ROOT)
    lineages = {K.LINEAGE: lin[K.LINEAGE]}
    traces = {K.LINEAGE: L.load_route_trace(REPO_ROOT, lin[K.LINEAGE])}
    env = G1.build_real_env(cfg, sampler, run_root=RUN_ROOT, protect=write_guard_roots(), lineages_override=lineages, route_traces_override=traces)
    return K.EvalSession(cfg, env, prepare_tables=lambda dest: K.copy_registered_tables(G1_ROOT / "lineages", dest, (K.LINEAGE,)),
                         load_policies=lambda: POL.load_policies(cfg.checkpoints, cfg.checkpoint_root), flatten=mn.flatten, earlier_trees=earlier_trees)


def cmd_run() -> int:
    from m7_runtime import BATTLESHIP_IMAGE, install_kill_on_close_job, wait_until_no_process

    import m8_rd2_worker as w2
    import m8_rd_worker as mw

    pf = preflight()
    if not pf["ok"]:
        print(json.dumps(A.stamp(pf), indent=1, default=str))
        print("refused: preflight problems (see above); nothing was launched")
        return 2
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    POL.install_optimizer_guard()
    install_kill_on_close_job()
    mw.ProvenanceGuard.install()
    w2.WriteGuard.install(write_guard_roots())
    cfg = K.EvalConfig(root=RUN_ROOT, checkpoint_root=REPO_ROOT)
    RUN_ROOT.mkdir(parents=True)
    cfg.session_dir.mkdir(parents=True)
    shutil.copyfile(APPROVAL, cfg.session_dir / "approval_copy.json")
    A.write_json(cfg.session_dir / "open.json", A.stamp({"utc": utc(), "scope": K.SCOPE, "approval_sha256": sha256_file(APPROVAL), "pins": G1.identity_now(),
                                                         "preflight": {k: pf.get(k) for k in ("executable_sha256", "git_head", "readiness", "backup", "approval", "source_snapshot",
                                                                                              "unit_suite_m9_eval", "trees", "pins", "checkpoint_pins", "budget")},
                                                         "description": K.description(), "optimizer_guard": POL.guard_installed()}))
    sampler = G1.make_sampler(cfg.session_dir / "memory_tree.jsonl", cfg.memory_caps_mb)
    sampler.start()
    out: Dict[str, Any] = {}
    try:
        sess = build_session(cfg, sampler)
        out = sess.run()
    finally:
        rep = sampler.stop()
        A.write_json(cfg.session_dir / "memory_summary.json", A.stamp(rep))
    left = wait_until_no_process(BATTLESHIP_IMAGE, timeout=60.0)
    A.write_json(cfg.session_dir / "leftover_processes.json", A.stamp({"battleship_pids_after_the_run": left}))
    print(json.dumps({"status": out.get("status"), "stop": out.get("stop"), "total_ticks": out.get("total_ticks"), "readings": {k: (v.get("reading") if isinstance(v, dict) and "reading" in v else v)
                                                                                                                             for k, v in (out.get("readings") or {}).items()}},
                     indent=1, default=str)[:4000])
    if left:
        print(f"WARNING: BattleShip processes still alive after the run: {left}")
    return 0


# -- read-only verification of the recorded run --------------------------------------------------------------------------------------------------


def _canon(obj: Any) -> str:
    """A JSON object as it reads back from disk (integer keys become strings), dumped with sorted keys: the comparison of a re-derived value with a record."""
    return json.dumps(json.loads(json.dumps(obj, default=str)), sort_keys=True)


def verify_run(root: Path = RUN_ROOT, cfg: Optional[K.EvalConfig] = None, *, check_pins: bool = True) -> Dict[str, Any]:
    """Re-derive the recorded evaluation from its own records: every sticky mask from its key, words = registered prefix + submitted words, the cells and the
    readings from the episode and replay records, the metadata audit, the checkpoint pins. Reads only. `cfg` / `check_pins` exist for the synthetic tests."""
    import hashlib

    import m8_rd_cells as mcell
    import m9_lineages as L
    import m9_sticky as S

    problems: List[str] = []
    eps = A.read_jsonl(root / "eval" / "episodes.jsonl")
    reps = A.read_jsonl(root / "verification" / "replays.jsonl") if (root / "verification" / "replays.jsonl").is_file() else []
    out_rec = A.read_json(root / "session" / "outcome.json")
    tb = L.load_tables(root / "lineages", K.LINEAGE)
    cfg = cfg if cfg is not None else K.EvalConfig(root=root)
    want_jobs = {j.job_id: j for j in K.build_jobs(cfg)}
    seen = set()
    for r in eps:
        jid = r["episode"]
        if jid in seen:
            problems.append(f"{jid}: recorded twice")
        seen.add(jid)
        j = want_jobs.get(jid)
        if j is None:
            problems.append(f"{jid}: not a planned job")
            continue
        if r["label"] != j.label or int(r["tau"]) != int(j.start.tau) or r["deterministic"] != j.deterministic or r["model"] != j.extra.get("model"):
            problems.append(f"{jid}: label / tau / mode / model differ from the plan")
        tau = int(r["tau"])
        prefix = tb.words[:tau]
        if hashlib.sha256(prefix).hexdigest() != r["prefix_sha256"]:
            problems.append(f"{jid}: prefix digest differs from the registered T_clear prefix")
        sub, smp, mask = bytes.fromhex(r["submitted_hex"]), bytes.fromhex(r["sampled_hex"]), bytes.fromhex(r["sticky_mask_hex"])
        pr = S.check_record(r["label"], tau, smp, sub, mask, prefix[-1] if tau > 0 else None)
        problems += [f"{jid}: {p}" for p in pr]
        if r["driver"] == "tape":
            tape = S.Tape(tb.words)
            for i, (w, m) in enumerate(zip(smp, mask)):
                if w != tape.word(tau + i):
                    problems.append(f"{jid}: tape word {tau + i} is not the trunk's")
                    break
        if mcell.words_digest(prefix + sub) != r["native_action_digest"]:
            problems.append(f"{jid}: native action digest differs from prefix + submitted words")
    missing = sorted(set(want_jobs) - seen)
    verified = {x["id"]: bool(x["exact"]) for x in reps}
    recorded_unverified = set(out_rec.get("unverified_clears") or [])
    for r in eps:
        if r["clear"] and r["episode"] not in verified and r["episode"] not in recorded_unverified:
            problems.append(f"{r['episode']}: a clear without a replay record and not recorded as unverified")
    if recorded_unverified and out_rec.get("status") not in ("PARTIAL", "INCOMPLETE", "INVALID"):
        problems.append("unverified clears are recorded but the status claims completeness")
    agg = K.aggregate(eps, verified, cfg)
    rd = K.readings(agg, K.roles(cfg))
    if _canon(rd) != _canon(out_rec.get("readings")):
        problems.append("the readings re-derived from the records differ from the recorded outcome")
    if _canon(agg) != _canon(out_rec.get("aggregate")):
        problems.append("the cells re-derived from the records differ from the recorded outcome")
    aud = A.audit_tree(root, skip_dirs=("workers", "vw", "derived"))
    if not aud["ok"]:
        problems.append(f"metadata audit: {aud['failures'][:3]}")
    if check_pins:
        pp = POL.pin_problems(K.CHECKPOINTS, REPO_ROOT)
        problems += [f"checkpoint pin now: {p}" for p in pp]
    return {"ok": not problems, "problems": problems[:50], "episodes": len(eps), "planned": len(want_jobs), "missing_jobs": len(missing), "replays": len(reps),
            "inexact_replays": [x["id"] for x in reps if not x["exact"]], "status_recorded": out_rec.get("status"), "metadata_audit": {k: aud[k] for k in ("files", "jsonl_lines", "ok")}}


def cmd_verify_run() -> int:
    rep = verify_run(RUN_ROOT)
    print(json.dumps(A.stamp(rep), indent=1, default=str))
    return 0 if rep["ok"] else 1


def cmd_report() -> int:
    out = A.read_json(RUN_ROOT / "session" / "outcome.json")
    print(json.dumps(A.stamp({k: out.get(k) for k in ("status", "stop", "phases", "ticks", "total_ticks", "clock", "incomplete_cells", "missing_cells", "verification", "readings")}),
                     indent=1, default=str))
    return 0


def cmd_status() -> int:
    st = RUN_ROOT / "session" / "state.json"
    print(json.dumps({"run_root_exists": RUN_ROOT.exists(), "approval_present": APPROVAL.is_file(), "state": json.loads(st.read_text(encoding="utf-8")) if st.is_file() else None},
                     indent=1, default=str))
    return 0


def cmd_template() -> int:
    ident = identity()
    rec = dict(ident, approval="PENDING (a reviewer replaces this with APPROVED ... and fills the authorisation and the source snapshot entries; this command never writes the record)",
               revision=1, authorisation={"source": "<the user's message>", "text": ["<what is authorised, once>"]},
               source_snapshot={"dest": str(SNAPSHOT_DEST_DEFAULT), "snapshot_json_sha256": "<sha256>", "result": "PASS", "files": "<n>", "git_head": ident["git_head"],
                                "independent_verification": "<tool verify and an independent PowerShell re-hash>"},
               task=dict(C.TASK), created_utc=utc())
    print(json.dumps(rec, indent=1, default=str))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("status", "verify-run", "approval-template", "run", "report"):
        sub.add_parser(n)
    p = sub.add_parser("preflight")
    p.add_argument("--skip-unit", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "status":
        return cmd_status()
    if a.cmd == "preflight":
        rep = preflight(run_unit=not a.skip_unit)
        print(json.dumps(A.stamp(rep), indent=1, default=str))
        return 0 if rep["ok"] else 1
    if a.cmd == "approval-template":
        return cmd_template()
    if a.cmd == "verify-run":
        return cmd_verify_run()
    if a.cmd == "report":
        return cmd_report()
    return cmd_run()


if __name__ == "__main__":
    sys.exit(main())
