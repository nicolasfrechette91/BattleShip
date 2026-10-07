#!/usr/bin/env python3
"""M9-g3: verified D: source snapshot of the exact code, configuration and documents approved for a g3 session.

    python -B rl/m9_g3_snapshot.py snapshot   --dest D:/BattleShip_source_snapshots/<date>_m9_g3_s1 [--session 1]
    python -B rl/m9_g3_snapshot.py snapshot   --dest D:/BattleShip_source_snapshots/<date>_m9_g3_s2 --session 2
    python -B rl/m9_g3_snapshot.py verify     --dest ...
    python -B rl/m9_g3_snapshot.py powershell --dest ... --out <file.ps1>     # the independent re-hash script

The procedure of rl/m9_g2_snapshot.py (the generic `verify` / `powershell` helpers of rl/m8_rd_snapshot.py are reused unchanged): `snapshot` hashes every
source file by reading the repository, copies it to <dest>/files/<repo path>, re-hashes the copy by reading it back from D:, re-hashes the source again,
and writes snapshot.json with result PASS only when all three agree for every file and the session's code identity equals the copies. The file set: the
rl/m9_g3_* sources and tests, the g3 decisions and implementation records, the stop review, the g2 and g1 records the session rests on, the authorised
edit (rl/m9_eval_tests.py, at its pinned digest), the preparation records under logs/m9_g3_prep, and every repository module the session imports. The
approval record is not in it (it names this snapshot). Nothing is deleted. Nothing is written under the repository.

A session k >= 2 snapshot (`--session 2`; S1 and H14 of the s2 review) adds the records a resumed session rests on (the s1 results record, the s1 launch
record, the s1 approval, the re-check record, the s2 pre-launch review and the s2 preparation decisions: rl/m9_g3_session.S2_DOC_FILES) and the s2
preparation logs under logs/m9_g3_s2_prep (a NEW directory: logs/m9_g3_prep holds s1's preparation and is never written again), and computes the
identity for that session (its resume_inputs block included).
"""
from __future__ import annotations

import argparse
import importlib
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import m8_rd_snapshot as snap1

REPO = snap1.REPO
RL = snap1.RL
sha = snap1.sha
git = snap1.git
git_state = snap1.git_state
utc = snap1.utc
LOG_DIRS = ("logs/m9_g3_prep",)
S2_LOG_DIRS = ("logs/m9_g3_s2_prep",)                  # k >= 2: the s2 preparation logs and tools (never logs/m9_g3_prep, which is s1's)
EXTRA = ["docs/rl_m9_g3_decisions_2026-10-06.md", "docs/rl_m9_g3_implementation.md", "docs/rl_m9_g2_stop_review_2026-10-06.md", "docs/rl_m9_g2_s1_results_2026-10-06.md",
         "docs/rl_m9_g2_s1_approval.json", "docs/rl_m9_g2_proposal_2026-10-04.md", "docs/rl_m9_g2_decisions_2026-10-05.md", "docs/rl_m9_g2_implementation.md",
         "docs/rl_m9_policy_proposal_2026-10-03.md", "docs/rl_m9_g1_decisions_2026-10-04.md", "docs/rl_m9_g1_implementation.md", "docs/rl_m9_g1_results_2026-10-04.md",
         "docs/rl_m9_g1_diagnosis_2026-10-04.md", "docs/rl_m9_g1_checkpoint_eval_plan_2026-10-04.md", "docs/rl_m8_rd4_results_2026-10-03.md", "rl/tools/runs_backup.py",
         "rl/data/m7n_action_classes_v1.json", "rl/data/m7n_action_classes_v2.json", "rl/m9_eval_tests.py"]
MODULES = ["m9_g3_session", "m9_g3_run", "m9_g3_train", "m9_g3_probe", "m9_g3_frontier", "m9_g3_rule", "m9_g3_report", "m9_g3_contract", "m9_g3_tests", "m9_g3_snapshot",
           "m9_g2_session", "m9_g2_run", "m9_g2_train", "m9_g2_probe", "m9_g2_frontier", "m9_g2_arena", "m9_g2_policy", "m9_g2_tape", "m9_g2_rule", "m9_g2_resume", "m9_g2_report",
           "m9_g2_contract", "m9_g2_stub", "m9_g2_tests", "m9_g2_snapshot", "m9_session", "m9_run", "m9_testenv", "m9_stub", "m9_eval_policy", "m7f_trace", "m7n_crossing", "m7u3_gate",
           "m7u_gate", "m7u2_gate", "m7s_gate", "m7_runtime", "m7_standby", "battleship_process", "battleship_client", "runs_backup", "m8_rd2_worker", "m7n_obs", "m7n_policy"]
EXTERNAL = snap1.EXTERNAL


def log_dirs(k: int = 1) -> List[str]:
    return list(LOG_DIRS) + (list(S2_LOG_DIRS) if int(k) >= 2 else [])


def file_set(k: int = 1) -> List[str]:
    sys.path.insert(0, str(RL))
    sys.path.insert(0, str(RL / "tools"))
    for m in MODULES:
        importlib.import_module(m)
    extra = list(EXTRA)
    if int(k) >= 2:
        import m9_g3_session as session

        extra += list(session.S2_DOC_FILES)
    rels = {e for e in extra if (REPO / e).is_file()}
    for ld in log_dirs(k):
        logd = REPO / ld
        if logd.is_dir():
            rels |= {p.relative_to(REPO).as_posix() for p in logd.rglob("*") if p.is_file()}
    for mod in list(sys.modules.values()):
        f = getattr(mod, "__file__", None)
        if not f:
            continue
        try:
            rel = Path(f).resolve().relative_to(REPO.resolve())
        except ValueError:
            continue
        if rel.parts[0] == "rl" and Path(f).suffix == ".py":
            rels.add(rel.as_posix())
    return sorted(rels)


def cmd_snapshot(dest: Path, k: int = 1) -> int:
    if dest.exists():
        print(f"refused: {dest} exists (never overwritten)")
        return 2
    t0 = time.time()
    sys.path.insert(0, str(RL))
    import m9_g3_session as session

    identity = session.identity(int(k))
    rels = sorted(set(file_set(int(k))) | set(identity["code"]) | set(identity["docs_sha256"]))
    files: List[Dict[str, Any]] = []
    problems: List[str] = []
    for rel in rels:
        src = REPO / rel
        before = sha(src)
        dst = dest / "files" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copy = sha(dst)
        after = sha(src)
        ok = before == copy == after
        if not ok:
            problems.append(rel)
        files.append({"path": rel, "size": src.stat().st_size, "sha256_source": before, "sha256_copy_reread": copy, "sha256_source_after": after, "equal": ok, "git": git_state(rel)})
    by_path = {f["path"]: f["sha256_copy_reread"] for f in files}
    ident_mismatch = [k for k, v in identity["code"].items() if by_path.get(k) != v]
    docs_mismatch = [k for k, v in identity["docs_sha256"].items() if by_path.get(k) != v]
    edit_mismatch = [k for k, v in session.AUTHORISED_TRACKED_EDITS.items() if by_path.get(k) != v["sha256_after"]]
    external = []
    for p in EXTERNAL:
        if p.is_file():
            dst = dest / "external" / p.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
            external.append({"path": str(p), "sha256": sha(p), "sha256_copy_reread": sha(dst), "note": "outside the repository"})
    shutil.copy2(Path(__file__), dest / Path(__file__).name)
    exe = REPO / "build-us" / "Release" / "BattleShip.exe"
    rec = {"task": dict(session.G.TASK), "created_utc": utc(), "tool": "m9_g3_source_snapshot_v1", "tool_sha256": sha(Path(__file__)), "repo": str(REPO), "dest": str(dest), "session": int(k),
           "log_dirs": log_dirs(int(k)),
           "git_head": git("rev-parse", "HEAD"), "git_status_rl_docs": git("status", "--porcelain", "--", "rl", "docs").splitlines(),
           "authorised_tracked_edits": {k: dict(v) for k, v in session.AUTHORISED_TRACKED_EDITS.items()}, "authorised_edit_mismatch": edit_mismatch,
           "executable": {"path": str(exe), "sha256": sha(exe), "size": exe.stat().st_size, "note": "hashed, not copied (build output)"},
           "identity": identity, "identity_code_mismatch": ident_mismatch, "identity_docs_mismatch": docs_mismatch, "files": files, "n_files": len(files),
           "bytes": sum(f["size"] for f in files), "external": external, "problems": problems,
           "result": "PASS" if not problems and not ident_mismatch and not docs_mismatch and not edit_mismatch and identity["executable_sha256"] == sha(exe)
           and all(e["sha256"] == e["sha256_copy_reread"] for e in external) else "FAIL",
           "wall_s": round(time.time() - t0, 1),
           "note": "copy on another disk of the same machine; hashes read from the repository before and after the copy, and from the D: copy by reading it back"}
    (dest / "snapshot.json").write_text(json.dumps(rec, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({kk: rec[kk] for kk in ("session", "result", "n_files", "bytes", "problems", "identity_code_mismatch", "identity_docs_mismatch", "authorised_edit_mismatch", "git_head", "wall_s")}, default=str))
    print(f"snapshot.json sha256 {sha(dest / 'snapshot.json')}")
    return 0 if rec["result"] == "PASS" else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("snapshot", "verify", "powershell"))
    ap.add_argument("--dest", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--session", type=int, default=1)
    a = ap.parse_args(argv)
    if not sys.flags.dont_write_bytecode:
        print("refused: run with python -B (no compiled module may be written under rl/)")
        return 2
    if a.command == "snapshot":
        return cmd_snapshot(a.dest, int(a.session))
    if a.command == "verify":
        return snap1.cmd_verify(a.dest)
    text = snap1.powershell_script(a.dest)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(RL))
    sys.exit(main())
