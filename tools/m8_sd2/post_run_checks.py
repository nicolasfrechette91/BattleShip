#!/usr/bin/env python3
"""The S3 rule as code: after the sd2 run and its own increment, re-hash EVERY registered increment INDEPENDENTLY (tools/m8_sd2/independent_increment_check.ps1: PowerShell Get-FileHash,
no repository module) against its source tree, run R1 over the five M8 trees through the session code, and the combined runs/ coverage. It never invokes `rl/tools/runs_backup.py verify` on
an earlier increment (that command rewrites the increment's verification.json): with --tool-verify it runs the tool's verify ONLY on the unique folder ending in `_incr_m8_rd_sd2`, with
`--source runs/m8_rd_sd2`; zero or two such folders refuse.

    python -B -X utf8 tools/m8_sd2/post_run_checks.py --session sd2 [--repo <repo>] [--backup-root D:/BattleShip_runs_backup] [--tool-verify]

Registered increment = a folder of the backup root whose verification.json says PASS and whose `source` is a tree under <repo>/runs that exists; every other folder is listed as skipped
with its reason. Outputs: logs/m8_sd2_run/post_increments/<folder>.txt (one per re-hash) and the stamped logs/m8_sd2_run/post_run_checks.json. Exit 0 only when every re-hash is PASS, R1
holds and the coverage shows 0 uncovered (and the tool's verify, when asked, is PASS); 1 otherwise; 2 when refused.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

PS1 = Path(__file__).resolve().with_name("independent_increment_check.ps1")


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def registered_increments(repo: Path, backup_root: Path) -> Dict[str, Any]:
    """The increments to re-hash and the folders skipped, each with its reason."""
    runs = (repo / "runs").resolve()
    out: Dict[str, Any] = {"increments": [], "skipped": []}
    if not backup_root.is_dir():
        out["skipped"].append({"folder": str(backup_root), "why": "no backup root"})
        return out
    for d in sorted(p for p in backup_root.iterdir() if p.is_dir()):
        rec_p = d / "verification.json"
        if not rec_p.is_file():
            out["skipped"].append({"folder": d.name, "why": "no verification.json"})
            continue
        try:
            rec = json.loads(rec_p.read_text(encoding="utf-8-sig"))
        except ValueError:
            out["skipped"].append({"folder": d.name, "why": "verification.json is not JSON"})
            continue
        if rec.get("result") != "PASS":
            out["skipped"].append({"folder": d.name, "why": f"record result {rec.get('result')!r}"})
            continue
        src = Path(str(rec.get("source", "")))
        try:
            rel = src.resolve().relative_to(runs)
        except (ValueError, OSError):
            out["skipped"].append({"folder": d.name, "why": f"source {src} is not a tree under {runs}"})
            continue
        if not src.is_dir():
            out["skipped"].append({"folder": d.name, "why": f"source {src} does not exist"})
            continue
        out["increments"].append({"folder": d.name, "dest": str(d), "source": str(src), "source_rel": rel.as_posix(), "files": rec.get("files"), "manifest_sha256": rec.get("manifest_sha256")})
    return out


def independent_rehash(source: Path, dest: Path, ps1: Path = PS1) -> Dict[str, Any]:
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(ps1), "-Source", str(source), "-Dest", str(dest)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    lines = [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
    last = lines[-1] if lines else ""
    fields = dict(kv.split("=", 1) for kv in last.split() if "=" in kv) if last.startswith("checked=") else {}
    return {"exit": r.returncode, "last_line": last, "fields": fields, "result": fields.get("result"), "pass": fields.get("result") == "PASS" and r.returncode == 0,
            "stderr": (r.stderr or "")[-400:], "output": r.stdout}


def r1_check(repo: Path) -> Dict[str, Any]:
    """R1 over the five M8 trees through the session code (patched by the tests)."""
    sys.path.insert(0, str(repo / "rl"))
    sys.path.insert(0, str(repo / "rl" / "tools"))
    import m8_sd2_session as S

    return S.earlier_trees_immutability()


def coverage_check(repo: Path) -> Dict[str, Any]:
    """The combined runs/ coverage (every runs/ file in the base backup or an increment; patched by the tests)."""
    sys.path.insert(0, str(repo / "rl"))
    sys.path.insert(0, str(repo / "rl" / "tools"))
    import m8_rd_session as ses1

    c = ses1.combined_coverage()
    return {k: c.get(k) for k in ("ok", "reason", "source_files", "uncovered", "skipped")} | {"increments": len(c.get("increments") or [])}


def sd2_increment(backup_root: Path, session: str) -> List[Path]:
    return sorted(p for p in backup_root.iterdir() if p.is_dir() and p.name.endswith(f"_incr_m8_rd_{session}")) if backup_root.is_dir() else []


def tool_verify_new_increment(repo: Path, dest: Path, session: str) -> Dict[str, Any]:
    """The tool's verify on the NEW increment only, with --source naming the sd2 tree (the only increment the tool's verify ever touches after the run)."""
    source_rel = f"runs/m8_rd_{session}"
    r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(repo / "rl" / "tools" / "runs_backup.py"), "verify", "--source", source_rel, "--dest", str(dest)], cwd=str(repo),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    last = ([ln for ln in (r.stdout or "").splitlines() if ln.strip()] or [""])[-1]
    return {"dest": str(dest), "source": source_rel, "exit": r.returncode, "last_line": last[:300], "pass": r.returncode == 0 and "verification PASS" in last}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", required=True, choices=["sd2"], help="the finished session (sd2)")
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    ap.add_argument("--backup-root", type=Path, default=Path(r"D:\BattleShip_runs_backup"))
    ap.add_argument("--tool-verify", action="store_true", help="also run runs_backup.py verify on the unique new sd2 increment (never on any other)")
    ap.add_argument("--ps1", type=Path, default=PS1, help="the independent re-hash script (default: the sibling independent_increment_check.ps1)")
    a = ap.parse_args()
    if not sys.flags.dont_write_bytecode:
        print("refused: run with python -B")
        return 2
    repo, backup_root = a.repo, a.backup_root
    logs = repo / "logs" / f"m8_{a.session}_run"
    if not logs.is_dir():
        print(f"refused: {logs} does not exist (the launch-day log directory)")
        return 2
    if not a.ps1.is_file():
        print(f"refused: no re-hash script at {a.ps1}")
        return 2
    new_inc = sd2_increment(backup_root, a.session)
    if a.tool_verify and len(new_inc) != 1:
        print(f"refused: --tool-verify needs exactly one folder ending in _incr_m8_rd_{a.session} under {backup_root}, found {[p.name for p in new_inc]}")
        return 2
    reg = registered_increments(repo, backup_root)
    out_dir = logs / "post_increments"
    out_dir.mkdir(parents=True, exist_ok=True)
    results: List[Dict[str, Any]] = []
    for inc in reg["increments"]:
        res = independent_rehash(Path(inc["source"]), Path(inc["dest"]), a.ps1)
        (out_dir / f"{inc['folder']}.txt").write_text(res.pop("output"), encoding="utf-8")
        results.append(dict(inc, **res))
        print(f"{'PASS' if res['pass'] else 'FAIL'} {inc['folder']:<40} {res['last_line'][:140]}", flush=True)
    r1 = r1_check(repo)
    cov = coverage_check(repo)
    tv: Optional[Dict[str, Any]] = tool_verify_new_increment(repo, new_inc[0], a.session) if a.tool_verify else None
    ok = all(r["pass"] for r in results) and bool(results) and bool(r1.get("ok")) and cov.get("uncovered") == 0 and bool(cov.get("ok")) and (tv is None or tv["pass"])
    rec = {"utc": utc(), "session": a.session, "backup_root": str(backup_root), "independent_rehash": results, "skipped": reg["skipped"], "r1_five_trees": r1, "coverage": cov,
           "tool_verify_new_increment": tv, "never_tool_verify_on_earlier_increments": True, "ok": ok}
    try:
        sys.path.insert(0, str(repo / "rl"))
        import m8_sd2_artifacts as art

        art.write_json5(logs / "post_run_checks.json", rec)
    except Exception as exc:  # noqa: BLE001 - the record is still printed
        (logs / "post_run_checks.json.txt").write_text(json.dumps(rec, indent=1, default=str), encoding="utf-8")
        print(f"note: the stamped record could not be written ({type(exc).__name__}: {exc}); a plain copy was written as post_run_checks.json.txt")
    print(json.dumps({"increments_rehashed": len(results), "all_pass": all(r["pass"] for r in results), "skipped": len(reg["skipped"]), "r1_ok": r1.get("ok"),
                      "coverage": {k: cov.get(k) for k in ("ok", "uncovered", "source_files", "increments")}, "tool_verify": tv and tv["pass"], "ok": ok}, indent=1, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
