#!/usr/bin/env python3
"""M8-rd1: verified D: source snapshot of the exact code, configuration and documents approved for the run.

    python rl/m8_rd_snapshot.py snapshot --dest D:\\BattleShip_source_snapshots\\<date>_m8_rd1
    python rl/m8_rd_snapshot.py verify   --dest D:\\BattleShip_source_snapshots\\<date>_m8_rd1
    python rl/m8_rd_snapshot.py powershell --dest ... --out <file.ps1>     # the independent re-hash script

`snapshot` hashes every source file by reading the repository, copies it to <dest>/files/<repo path>, re-hashes the copy by
reading it back from D:, re-hashes the source again (unchanged during the copy), and writes snapshot.json with result PASS
only when all three agree for every file and the code identity of the session equals the copies. The file set is: the M8
sources and tests, the proposal, the amendment, the implementation record, the preparation records, and every repository module
the session imports (collected from sys.modules after importing its modules and their function-level imports). The approval
record is not in it: it names this snapshot, and it is copied into the session's open record instead. `verify` re-reads the copy
and the repository and compares both with snapshot.json (it never rewrites snapshot.json; it writes verify_<utc>.json).
Nothing is deleted. Nothing is written under the repository.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

REPO = Path(__file__).resolve().parent.parent
RL = REPO / "rl"
EXTRA = ["docs/rl_m8_rd_proposal_2026-10-01.md", "docs/rl_m8_rd_amendment_2026-10-02.md", "docs/rl_m8_rd_implementation.md",
         "docs/rl_model_planning_m7u3_implementation.md",
         "docs/rl_model_planning_m7u3_gate_approval.json", "docs/rl_frontier_curriculum_m7h_proposal.md",
         "rl/data/m7n_action_classes_v2.json", "rl/tools/runs_backup.py"]
LOG_DIR = "logs/m8_rd_prep"
MODULES = ["m8_rd_session", "m8_rd_finish", "m8_rd_report", "m8_rd_stub", "m8_rd_fakegame", "m8_rd_tests", "m7f_trace", "m7n_crossing", "m7u3_gate",
           "m7u_gate", "m7u2_gate", "m7s_gate", "m7_runtime", "m7_standby", "battleship_process", "battleship_client",
           "m7q_status_table", "m7h_curriculum", "runs_backup"]
EXTERNAL = [Path(r"C:\Users\kill_\Bureau\gitRepo\Smash_pc_port\guide.md")]


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True).stdout.strip()


def git_state(rel: str) -> str:
    out = subprocess.run(["git", "status", "--porcelain", "--ignored", "--", rel], cwd=REPO, capture_output=True, text=True).stdout
    return out[:2] if out else "  "


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
    import m8_rd_session as session

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
        files.append({"path": rel, "size": src.stat().st_size, "sha256_source": before, "sha256_copy_reread": copy,
                      "sha256_source_after": after, "equal": ok, "git": git_state(rel)})
    by_path = {f["path"]: f["sha256_copy_reread"] for f in files}
    ident_mismatch = [k for k, v in identity["code"].items() if by_path.get(k) != v]
    external = []
    for p in EXTERNAL:
        if p.is_file():
            dst = dest / "external" / p.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
            external.append({"path": str(p), "sha256": sha(p), "sha256_copy_reread": sha(dst), "note": "outside the repository"})
    shutil.copy2(Path(__file__), dest / Path(__file__).name)
    exe = REPO / "build-us" / "Release" / "BattleShip.exe"
    rec = {"tool": "m8_rd_source_snapshot_v1", "tool_sha256": sha(Path(__file__)), "created_utc": utc(), "repo": str(REPO),
           "dest": str(dest), "git_head": git("rev-parse", "HEAD"),
           "git_status_rl_docs": git("status", "--porcelain", "--", "rl", "docs").splitlines(),
           "executable": {"path": str(exe), "sha256": sha(exe), "size": exe.stat().st_size, "note": "hashed, not copied (build output)"},
           "identity": identity, "identity_code_mismatch": ident_mismatch, "files": files, "n_files": len(files),
           "bytes": sum(f["size"] for f in files), "external": external, "problems": problems,
           "result": "PASS" if not problems and not ident_mismatch and identity["executable_sha256"] == sha(exe)
           and all(e["sha256"] == e["sha256_copy_reread"] for e in external) else "FAIL",
           "wall_s": round(time.time() - t0, 1),
           "note": "copy on another disk of the same machine; hashes read from the repository before and after the copy, "
                   "and from the D: copy by reading it back"}
    (dest / "snapshot.json").write_text(json.dumps(rec, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: rec[k] for k in ("result", "n_files", "bytes", "problems", "identity_code_mismatch", "git_head", "wall_s")},
                     default=str))
    print(f"snapshot.json sha256 {sha(dest / 'snapshot.json')}")
    return 0 if rec["result"] == "PASS" else 1


def cmd_verify(dest: Path) -> int:
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
    out = {"verified_utc": utc(), "snapshot_sha256": sha(dest / "snapshot.json"), "files": len(rec["files"]),
           "mismatches": bad, "extra_files": extra, "external_mismatches": ext_bad,
           "executable_equal": sha(exe) == rec["executable"]["sha256"],
           "result": "PASS" if not bad and not extra and not ext_bad and sha(exe) == rec["executable"]["sha256"] else "FAIL"}
    (dest / f"verify_{out['verified_utc'].replace(':', '')}.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out))
    return 0 if out["result"] == "PASS" else 1


def powershell_script(dest: Path) -> str:
    return f"""$dest='{dest}'
$repo='{REPO}'
$rec=Get-Content "$dest\\snapshot.json" -Raw | ConvertFrom-Json
$bad=0;$n=0
foreach($f in $rec.files){{
  $c=(Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $dest ('files\\'+($f.path -replace '/','\\'))) ).Hash.ToLower()
  $s=(Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $repo ($f.path -replace '/','\\'))).Hash.ToLower()
  $n++
  if(-not ($c -eq $s -and $c -eq $f.sha256_source)){{ $bad++; "MISMATCH $($f.path)" }}
}}
foreach($e in $rec.external){{
  $c=(Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $dest ('external\\'+(Split-Path $e.path -Leaf)))).Hash.ToLower()
  $n++
  if($c -ne $e.sha256){{ $bad++; "MISMATCH external $($e.path)" }}
}}
$exe=(Get-FileHash -Algorithm SHA256 "$repo\\build-us\\Release\\BattleShip.exe").Hash.ToLower()
"checked=$n bad=$bad exe=$exe exe_ok=$($exe -eq $rec.executable.sha256) result=$($rec.result) snapshot_json=$((Get-FileHash -Algorithm SHA256 "$dest\\snapshot.json").Hash.ToLower())"
"""


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
    text = powershell_script(a.dest)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
