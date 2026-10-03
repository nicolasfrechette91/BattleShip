#!/usr/bin/env python3
"""M8-rd4: verified D: source snapshot of the exact code, configuration and documents approved for the run.

    python rl/m8_rd4_snapshot.py snapshot --dest D:/BattleShip_source_snapshots/<date>_m8_rd4
    python rl/m8_rd4_snapshot.py verify   --dest D:/BattleShip_source_snapshots/<date>_m8_rd4
    python rl/m8_rd4_snapshot.py powershell --dest ... --out <file.ps1>     # the independent re-hash script

The same procedure as rl/m8_rd3_snapshot.py, rl/m8_rd2_snapshot.py and rl/m8_rd_snapshot.py (all unchanged and reused for the byte-exact comparison helpers): `snapshot` hashes every
source file by reading the repository, copies it to <dest>/files/<repo path>, re-hashes the copy by reading it back from D:, re-hashes the source again, and writes snapshot.json with
result PASS only when all three agree for every file and the code identity of the rd4 session equals the copies. The file set is the M8 sources and tests (rd1's, rd2's, rd3's and rd4's), the
proposals, decisions, reviews and implementation records, the preparation records, and every repository module the rd4 session imports. The approval record is not in it: it names this snapshot.
Nothing is deleted. Nothing is written under the repository.
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
import m8_rd3_snapshot as snap3

REPO = snap1.REPO
RL = snap1.RL
sha = snap1.sha
git = snap1.git
git_state = snap1.git_state
utc = snap1.utc
LOG_DIR = "logs/m8_rd4_prep"
EXTRA = list(snap3.EXTRA) + ["docs/rl_m8_rd3_results_2026-10-02.md", "docs/rl_m8_rd3_stop_review_2026-10-03.md", "docs/rl_m8_rd4_decisions_2026-10-03.md", "docs/rl_m8_rd4_implementation.md"]
MODULES = list(snap3.MODULES) + ["m8_rd4_session", "m8_rd4_run", "m8_rd4_rule", "m8_rd4_report", "m8_rd4_select", "m8_rd4_resume", "m8_rd4_claims", "m8_rd4_tests"]
EXTERNAL = snap1.EXTERNAL


def file_set() -> List[str]:
    sys.path.insert(0, str(RL))
    sys.path.insert(0, str(RL / "tools"))
    for m in MODULES:
        importlib.import_module(m)
    rels = {e for e in EXTRA if (REPO / e).is_file()}
    logd = REPO / LOG_DIR
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


def cmd_snapshot(dest: Path) -> int:
    if dest.exists():
        print(f"refused: {dest} exists (never overwritten)")
        return 2
    t0 = time.time()
    rels = file_set()
    sys.path.insert(0, str(RL))
    import m8_rd4_session as session

    identity = session.identity()
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
    external = []
    for p in EXTERNAL:
        if p.is_file():
            dst = dest / "external" / p.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
            external.append({"path": str(p), "sha256": sha(p), "sha256_copy_reread": sha(dst), "note": "outside the repository"})
    shutil.copy2(Path(__file__), dest / Path(__file__).name)
    exe = REPO / "build-us" / "Release" / "BattleShip.exe"
    rec = {"tool": "m8_rd4_source_snapshot_v1", "tool_sha256": sha(Path(__file__)), "created_utc": utc(), "repo": str(REPO), "dest": str(dest), "git_head": git("rev-parse", "HEAD"),
           "git_status_rl_docs": git("status", "--porcelain", "--", "rl", "docs").splitlines(),
           "executable": {"path": str(exe), "sha256": sha(exe), "size": exe.stat().st_size, "note": "hashed, not copied (build output)"},
           "identity": identity, "identity_code_mismatch": ident_mismatch, "identity_docs_mismatch": docs_mismatch, "files": files, "n_files": len(files),
           "bytes": sum(f["size"] for f in files), "external": external, "problems": problems,
           "result": "PASS" if not problems and not ident_mismatch and not docs_mismatch and identity["executable_sha256"] == sha(exe)
           and all(e["sha256"] == e["sha256_copy_reread"] for e in external) else "FAIL",
           "wall_s": round(time.time() - t0, 1),
           "note": "copy on another disk of the same machine; hashes read from the repository before and after the copy, and from the D: copy by reading it back"}
    (dest / "snapshot.json").write_text(json.dumps(rec, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: rec[k] for k in ("result", "n_files", "bytes", "problems", "identity_code_mismatch", "identity_docs_mismatch", "git_head", "wall_s")}, default=str))
    print(f"snapshot.json sha256 {sha(dest / 'snapshot.json')}")
    return 0 if rec["result"] == "PASS" else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("snapshot", "verify", "powershell"))
    ap.add_argument("--dest", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    if a.command == "snapshot":
        return cmd_snapshot(a.dest)
    if a.command == "verify":
        return snap1.cmd_verify(a.dest)           # the rd1 tool's verify is generic: it re-reads every file named in snapshot.json
    text = snap1.powershell_script(a.dest)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(RL))
    sys.exit(main())
