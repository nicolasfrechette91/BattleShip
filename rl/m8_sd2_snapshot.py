#!/usr/bin/env python3
"""M8-sd2: verified D: source snapshot of the exact code, configuration, tools and documents approved for the run.

    python -B rl/m8_sd2_snapshot.py snapshot --dest D:/BattleShip_source_snapshots/<date>_m8_sd2
    python -B rl/m8_sd2_snapshot.py verify   --dest D:/BattleShip_source_snapshots/<date>_m8_sd2
    python -B rl/m8_sd2_snapshot.py powershell --dest ... --out <file.ps1>     # the independent re-hash script

The same procedure as rl/m8_sd1_snapshot.py (rd1's helpers reused for the byte-exact comparison): `snapshot` hashes every source file by reading the repository, copies it to
<dest>/files/<repo path>, re-hashes the copy by reading it back from D:, re-hashes the source again, and writes a STAMPED snapshot.json with result PASS only when all three agree for every
file and the code identity of the sd2 session (its rl/ modules and the tools under tools/m8_sd2/) equals the copies. The file set is sd1's (the M8 sources and tests rd1 to sd1, sd1's tools,
the proposals, decisions, reviews, implementation and results records, sd1's preparation logs) plus the sd2 modules, the tools under tools/m8_sd2/, the sd2 preparation logs
(logs/m8_sd2_prep/), sd1's preparation record, approval and results record, the sd2 proposal and the sd2 preparation record (docs/rl_m8_sd2_prep_*.md), and every repository module the
sd2 session imports. NEVER the launch-day logs (logs/m8_sd2_run/): nothing written on launch day can make the snapshot refuse. The approval record is not in it: it names this snapshot.
`verify` re-reads the copy and the repository and writes a stamped verify_<utc>.json. Nothing is deleted. Nothing is written under the repository.
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
import m8_sd1_snapshot as snap5

REPO = snap1.REPO
RL = snap1.RL
sha = snap1.sha
git = snap1.git
git_state = snap1.git_state
utc = snap1.utc
TOOL_ID = "m8_sd2_source_snapshot_v1"
LOG_DIRS = (snap5.LOG_DIR, "logs/m8_sd2_prep")
TOOLS_DIRS = (snap5.TOOLS_DIR, "tools/m8_sd2")
NEVER_IN_THE_SET = ("logs/m8_sd2_run",)
EXTRA = list(snap5.EXTRA) + ["docs/rl_m8_sd1_prep_2026-10-11.md", "docs/rl_m8_sd1_approval.json", "docs/rl_m8_sd1_results_2026-10-11.md", "docs/rl_m8_sd2_proposal_2026-10-12.md"]
EXTRA_GLOBS = list(snap5.EXTRA_GLOBS) + ["docs/rl_m8_sd2_prep_*.md"]
MODULES = list(snap5.MODULES) + ["m8_sd2_artifacts", "m8_sd2_select", "m8_sd2_rule", "m8_sd2_claims", "m8_sd2_resume", "m8_sd2_report", "m8_sd2_run", "m8_sd2_session", "m8_sd2_tests"]
EXTERNAL = snap1.EXTERNAL


def file_set() -> List[str]:
    sys.path.insert(0, str(RL))
    sys.path.insert(0, str(RL / "tools"))
    for m in MODULES:
        importlib.import_module(m)
    rels = {e for e in EXTRA if (REPO / e).is_file()}
    for g in EXTRA_GLOBS:
        rels |= {p.relative_to(REPO).as_posix() for p in REPO.glob(g) if p.is_file()}
    for d in (*LOG_DIRS, *TOOLS_DIRS):
        dd = REPO / d
        if dd.is_dir():
            rels |= {p.relative_to(REPO).as_posix() for p in dd.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
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
    out = sorted(rels)
    bad = [r for r in out if any(r == n or r.startswith(n + "/") for n in NEVER_IN_THE_SET)]
    if bad:
        raise RuntimeError(f"the launch-day log directory is never in the snapshot set: {bad[:3]}")
    return out


def cmd_snapshot(dest: Path) -> int:
    if dest.exists():
        print(f"refused: {dest} exists (never overwritten)")
        return 2
    t0 = time.time()
    rels = file_set()
    sys.path.insert(0, str(RL))
    import m8_sd2_artifacts as art
    import m8_sd2_session as session

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
    rec = art.stamp({"tool": TOOL_ID, "tool_sha256": sha(Path(__file__)), "created_utc": utc(), "repo": str(REPO), "dest": str(dest), "git_head": git("rev-parse", "HEAD"),
                     "git_status_rl_docs_tools": git("status", "--porcelain", "--", "rl", "docs", "tools").splitlines(),
                     "executable": {"path": str(exe), "sha256": sha(exe), "size": exe.stat().st_size, "note": "hashed, not copied (build output)"},
                     "identity": identity, "identity_code_mismatch": ident_mismatch, "identity_docs_mismatch": docs_mismatch, "source_fingerprint": identity.get("source_fingerprint"),
                     "files": files, "n_files": len(files), "bytes": sum(f["size"] for f in files), "external": external, "problems": problems, "never_in_the_set": list(NEVER_IN_THE_SET),
                     "result": "PASS" if not problems and not ident_mismatch and not docs_mismatch and identity["executable_sha256"] == sha(exe)
                     and all(e["sha256"] == e["sha256_copy_reread"] for e in external) else "FAIL",
                     "wall_s": round(time.time() - t0, 1),
                     "note": "copy on another disk of the same machine; hashes read from the repository before and after the copy, and from the D: copy by reading it back"})
    (dest / "snapshot.json").write_text(json.dumps(rec, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: rec[k] for k in ("result", "n_files", "bytes", "problems", "identity_code_mismatch", "identity_docs_mismatch", "git_head", "source_fingerprint", "wall_s")}, default=str))
    print(f"snapshot.json sha256 {sha(dest / 'snapshot.json')}")
    return 0 if rec["result"] == "PASS" else 1


def cmd_verify(dest: Path) -> int:
    """rd1's generic verification (every file named in snapshot.json re-read from the copy and the repository), with a stamped record."""
    sys.path.insert(0, str(RL))
    import m8_sd2_artifacts as art

    rec = json.loads((dest / "snapshot.json").read_text(encoding="utf-8"))
    bad = []
    for f in rec["files"]:
        c = sha(dest / "files" / f["path"])
        s = sha(REPO / f["path"])
        if not (c == s == f["sha256_copy_reread"] == f["sha256_source"]):
            bad.append({"path": f["path"], "copy": c, "source": s, "recorded": f["sha256_source"]})
    on_disk = sorted(p.relative_to(dest / "files").as_posix() for p in (dest / "files").rglob("*") if p.is_file())
    extra = sorted(set(on_disk) - {f["path"] for f in rec["files"]})
    ext_bad = [e["path"] for e in rec.get("external", []) if sha(Path(e["path"])) != e["sha256"]]
    exe = REPO / "build-us" / "Release" / "BattleShip.exe"
    out = art.stamp({"verified_utc": utc(), "snapshot_sha256": sha(dest / "snapshot.json"), "files": len(rec["files"]), "mismatches": bad, "extra_files": extra, "external_mismatches": ext_bad,
                     "executable_equal": sha(exe) == rec["executable"]["sha256"],
                     "result": "PASS" if not bad and not extra and not ext_bad and sha(exe) == rec["executable"]["sha256"] else "FAIL"})
    (dest / f"verify_{out['verified_utc'].replace(':', '')}.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out))
    return 0 if out["result"] == "PASS" else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("snapshot", "verify", "powershell"))
    ap.add_argument("--dest", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    if a.command == "snapshot":
        return cmd_snapshot(a.dest)
    if a.command == "verify":
        return cmd_verify(a.dest)
    text = snap1.powershell_script(a.dest)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(RL))
    sys.exit(main())
