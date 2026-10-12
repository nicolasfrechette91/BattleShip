#!/usr/bin/env python3
"""The N4 rule as code: copies the launch-day evidence into the finished sd2 tree, ONCE, so that only stamped sd2-tool JSON reaches runs/m8_rd_sd2/launch/ and derived/.

    python -B -X utf8 tools/m8_sd2/copy_launch_evidence.py --session sd2 [--repo <repo>]

What it does, in order (reads logs/m8_sd2_run/, writes runs/m8_rd_sd2/launch/ and derived/, then one verify-run output under logs/m8_sd2_run/):
    1. refuses unless runs/m8_rd_sd2/sessions/sd2/state.json says `done`, logs/m8_sd2_run/verify_run.json exists, is stamped and says ok, logs/m8_sd2_run/report.json exists and is
       stamped, the approval docs/rl_m8_sd2_approval.json exists and names a snapshot whose snapshot.json exists, and neither runs/m8_rd_sd2/launch/ nor derived/verify_run.json exists yet
       (the copies are made once; the tree is never written again afterwards);
    2. copies verify_run.json and report.json into derived/;
    3. copies every other file of logs/m8_sd2_run/ (relative paths kept) into launch/; a file with a JSON-like name (.json, .jsonl, .json.gz, .jsonl.gz) whose content is not a valid stamped
       record (an object with the task block and created_utc; a JSONL file whose first row is a stamped header) is copied with `.txt` appended, so the tree's stamp audit stays clean;
    4. copies the approval's snapshot record as launch/source_snapshot_record.json and the snapshot's verify_*.json records into launch/;
    5. runs `rl/m8_sd2_session.py verify-run` again, writing logs/m8_sd2_run/verify_run_after_copies.json, and requires ok.
Prints what it did. Exit 0 only when every step held; 2 when refused (nothing copied); 1 when the final verify-run did not say ok.
"""
import argparse
import gzip
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

STAMPED_SUFFIXES = (".json", ".jsonl", ".json.gz", ".jsonl.gz")


def _is_stamped_obj(obj: Any) -> bool:
    return isinstance(obj, dict) and isinstance(obj.get("task"), dict) and set(obj["task"]) == {"id", "character", "stage"} and isinstance(obj.get("created_utc"), str) and obj["created_utc"].endswith("Z")


def valid_stamped_record(p: Path) -> bool:
    """A JSON object carrying the stamp at its top level, or a JSONL file whose first non-empty row is a stamped header row."""
    name = p.name
    try:
        if name.endswith(".jsonl") or name.endswith(".jsonl.gz"):
            opener = gzip.open if name.endswith(".gz") else open
            with opener(p, "rt", encoding="utf-8") as f:
                for ln in f:
                    if ln.strip():
                        row = json.loads(ln)
                        return _is_stamped_obj(row) and row.get("header") is True and isinstance(row.get("schema"), str)
            return False
        if name.endswith(".json.gz"):
            with gzip.open(p, "rt", encoding="utf-8") as f:
                return _is_stamped_obj(json.load(f))
        return _is_stamped_obj(json.loads(p.read_text(encoding="utf-8-sig")))
    except (OSError, ValueError, UnicodeDecodeError):
        return False


def is_json_like(name: str) -> bool:
    return name.endswith(STAMPED_SUFFIXES) and not name.endswith(".tmp")


def run_verify_run(repo: Path, out_path: Path) -> Tuple[int, Optional[bool]]:
    """`rl/m8_sd2_session.py verify-run` in a fresh process; its stdout (a stamped JSON record) goes to `out_path`. Returns (exit code, ok)."""
    r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(repo / "rl" / "m8_sd2_session.py"), "verify-run"], cwd=str(repo), capture_output=True, text=True, encoding="utf-8", errors="replace")
    out_path.write_text(r.stdout, encoding="utf-8")
    try:
        ok = bool(json.loads(r.stdout).get("ok"))
    except ValueError:
        ok = None
    return r.returncode, ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", required=True, choices=["sd2"], help="the finished session (sd2)")
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    a = ap.parse_args()
    if not sys.flags.dont_write_bytecode:
        print("refused: run with python -B")
        return 2
    repo = a.repo
    logs = repo / "logs" / f"m8_{a.session}_run"
    root = repo / "runs" / f"m8_rd_{a.session}"
    state_p = root / "sessions" / a.session / "state.json"
    approval_p = repo / "docs" / f"rl_m8_{a.session}_approval.json"
    refusals: List[str] = []
    if not state_p.is_file():
        refusals.append(f"no session state at {state_p}")
    else:
        try:
            if json.loads(state_p.read_text(encoding="utf-8-sig")).get("phase") != "done":
                refusals.append("the session state is not done")
        except ValueError:
            refusals.append("the session state is not JSON")
    vr, rp = logs / "verify_run.json", logs / "report.json"
    if not vr.is_file() or not valid_stamped_record(vr):
        refusals.append(f"{vr} is missing or not a stamped record")
    else:
        try:
            if not json.loads(vr.read_text(encoding="utf-8-sig")).get("ok"):
                refusals.append("verify_run.json does not say ok")
        except ValueError:
            refusals.append("verify_run.json is not JSON")
    if not rp.is_file() or not valid_stamped_record(rp):
        refusals.append(f"{rp} is missing or not a stamped record")
    snap_dir: Optional[Path] = None
    if not approval_p.is_file():
        refusals.append(f"no approval at {approval_p}")
    else:
        try:
            snap_dir = Path(str((json.loads(approval_p.read_text(encoding="utf-8-sig")).get("source_snapshot") or {}).get("dest", "")))
            if not (snap_dir / "snapshot.json").is_file():
                refusals.append(f"the approval's snapshot {snap_dir} has no snapshot.json")
        except ValueError:
            refusals.append("the approval is not JSON")
    if (root / "launch").exists():
        refusals.append(f"{root / 'launch'} exists (the copies are made once)")
    if (root / "derived" / "verify_run.json").exists():
        refusals.append(f"{root / 'derived' / 'verify_run.json'} exists (the copies are made once)")
    if refusals:
        print(json.dumps({"refused": refusals}, indent=1))
        return 2
    done: Dict[str, Any] = {"derived": [], "launch": [], "renamed_unstamped": [], "snapshot": []}
    (root / "derived").mkdir(parents=True, exist_ok=True)
    for src in (vr, rp):
        shutil.copy2(src, root / "derived" / src.name)
        done["derived"].append(src.name)
    launch = root / "launch"
    launch.mkdir(parents=True)
    for p in sorted(logs.rglob("*")):
        if not p.is_file() or p in (vr, rp):
            continue
        rel = p.relative_to(logs)
        dst = launch / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if is_json_like(p.name) and not valid_stamped_record(p):
            dst = dst.with_name(dst.name + ".txt")
            done["renamed_unstamped"].append(rel.as_posix())
        shutil.copy2(p, dst)
        done["launch"].append(dst.relative_to(launch).as_posix())
    assert snap_dir is not None
    shutil.copy2(snap_dir / "snapshot.json", launch / "source_snapshot_record.json")
    done["snapshot"].append("source_snapshot_record.json")
    for p in sorted(snap_dir.glob("verify_*.json")):
        shutil.copy2(p, launch / f"snapshot_{p.name}")
        done["snapshot"].append(f"snapshot_{p.name}")
    code, ok = run_verify_run(repo, logs / "verify_run_after_copies.json")
    done["verify_run_after_copies"] = {"exit": code, "ok": ok, "output": str(logs / "verify_run_after_copies.json")}
    print(json.dumps(done, indent=1))
    return 0 if (code == 0 and ok) else 1


if __name__ == "__main__":
    sys.exit(main())
