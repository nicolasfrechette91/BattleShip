#!/usr/bin/env python3
"""Three consecutive passes of the M8-sd2 unit suite and the production-count synthetic end-to-end run, with no change to any sd2 source (rl/m8_sd2_*.py, tools/m8_sd2/*) in between
(Part B condition B1). The sd2 source fingerprint is taken before and after every pass; the e2e's digest (its last output line) must be the same three times; outputs go to --out
(required; never a directory that is never written again: the earlier preparations' logs and the tool folders, all inside the source snapshot's file set; `logs/m8_sd2_prep` is refused
once a preparation record `docs/rl_m8_sd2_prep_*.md` exists, since from then on that folder is never written again). It refuses to overwrite an existing passes.json. Reads and runs only.
argparse: --help prints this text and runs nothing.

    python -B -X utf8 tools/m8_sd2/three_passes.py --session sd2 --out logs/m8_sd2_run/partB/three_passes [--repo <repo>] [--allow-git-gate]

--allow-git-gate (a PREPARATION round on an uncommitted tree only; never for a launch session's Part B): a unit pass whose ONLY failing test is the git-state gate
`tracked_files_unchanged6` (which fails by construction while the prepared files are uncommitted and the tree carries other changes) is accepted and the verdict says so:
THREE_CONSECUTIVE_PASSES_EXCEPT_THE_GIT_GATE. Every failing test name is recorded in passes.json either way.
"""
import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

NEVER_WRITTEN_AGAIN = ("logs/m8_rd_prep", "logs/m8_rd2_prep", "logs/m8_rd3_prep", "logs/m8_rd4_prep", "logs/m8_sd1_prep", "tools/m8_sd1", "tools/m8_sd2", "logs/m9_g3_prep",
                       "logs/m9_g3_s2_prep", "logs/m9_g3_resume_tools", "logs/m9_g3_resume_k_prep")
PREP_LOGS = "logs/m8_sd2_prep"                      # written during the preparation; never again once the preparation record exists
PREP_RECORD_GLOB = "docs/rl_m8_sd2_prep_*.md"
GIT_GATE = "tracked_files_unchanged6"


def fingerprint(repo: Path) -> str:
    """sha256 (16 hex) over the sd2 sources: rl/m8_sd2_*.py and tools/m8_sd2/* (repo-relative name and bytes, sorted); equal to rl/m8_sd2_session.source_fingerprint (tested)."""
    h = hashlib.sha256()
    files = sorted((repo / "rl").glob("m8_sd2_*.py")) + sorted(p for p in (repo / "tools" / "m8_sd2").glob("*") if p.is_file())
    for p in files:
        h.update(p.relative_to(repo).as_posix().encode())
        h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()[:16]


def refused_output_dir(repo: Path, out_dir: Path) -> str:
    """Why `out_dir` may not receive the passes (empty string: it may)."""
    never = list(NEVER_WRITTEN_AGAIN)
    if list(repo.glob(PREP_RECORD_GLOB)):
        never.append(PREP_LOGS)
    for n in never:
        try:
            out_dir.resolve().relative_to((repo / n).resolve())
        except ValueError:
            continue
        if n == PREP_LOGS:
            return f"{out_dir} is inside {n}, which is never written again once a preparation record ({PREP_RECORD_GLOB}) exists"
        return f"{out_dir} is inside {n}, which is never written again"
    return ""


def run(repo: Path, cmd: list, out: Path) -> dict:
    t0 = time.time()
    r = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True, encoding="utf-8", errors="replace")
    out.write_text(r.stdout + ("\n--- stderr ---\n" + r.stderr if r.stderr.strip() else ""), encoding="utf-8")
    lines = [ln for ln in r.stdout.strip().splitlines() if ln.strip()]
    last = lines[-1:] or [""]
    failed = [ln.split()[1].rstrip(":") for ln in lines if ln.startswith("FAIL ") and len(ln.split()) > 1]
    digest = None
    passed = None
    try:
        if last[0].startswith("{"):
            digest = json.loads(last[0]).get("digest")
    except ValueError:
        digest = None
    for ln in lines:
        if " passed (unit)" in ln:
            passed = ln.split(" passed (unit)")[0].strip()
    return {"returncode": r.returncode, "wall_s": round(time.time() - t0, 1), "last_line": last[0][:600], "failed": failed, "digest": digest, "unit_passed": passed}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", required=True, choices=["sd2"], help="the session these passes are the Part B evidence of (sd2)")
    ap.add_argument("--out", type=Path, required=True, help="the output directory (new; never one of the directories that are never written again)")
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    ap.add_argument("--allow-git-gate", action="store_true", help="preparation rounds only: accept a unit pass whose only failing test is the git-state gate")
    a = ap.parse_args()
    if not sys.flags.dont_write_bytecode:
        print("refused: run with python -B")
        return 2
    repo = a.repo
    out_dir = a.out if a.out.is_absolute() else repo / a.out
    why = refused_output_dir(repo, out_dir)
    if why:
        print(f"refused: {why}")
        return 2
    if (out_dir / "passes.json").exists():
        print(f"refused: {out_dir / 'passes.json'} exists (never overwritten; give --out a new directory)")
        return 2
    sys.path.insert(0, str(repo / "rl"))
    import m8_sd2_artifacts as art

    out_dir.mkdir(parents=True, exist_ok=True)
    fp_start = fingerprint(repo)
    (out_dir / "fingerprint_start.txt").write_text(fp_start + "\n", encoding="utf-8")
    results = []
    ok = True
    git_gate_only = False
    for i in (1, 2, 3):
        fp0 = fingerprint(repo)
        unit = run(repo, [sys.executable, "-B", "-X", "utf8", str(repo / "rl" / "m8_sd2_tests.py"), "unit"], out_dir / f"pass{i}_unit.txt")
        e2e = run(repo, [sys.executable, "-B", "-X", "utf8", str(repo / "rl" / "m8_sd2_tests.py"), "e2e"], out_dir / f"pass{i}_e2e.txt")
        fp1 = fingerprint(repo)
        unit_ok = unit["returncode"] == 0
        if not unit_ok and a.allow_git_gate and unit["failed"] == [GIT_GATE]:
            unit_ok, git_gate_only = True, True
        row = {"pass": i, "fingerprint_before": fp0, "fingerprint_after": fp1, "unit": unit, "e2e": e2e, "unchanged": fp0 == fp1 == fp_start, "unit_accepted": unit_ok,
               "unit_accepted_despite_the_git_gate": unit_ok and unit["returncode"] != 0}
        results.append(row)
        print(json.dumps(row), flush=True)
        if not unit_ok or e2e["returncode"] or not row["unchanged"] or not e2e["digest"]:
            ok = False
            break
    digests = [r["e2e"].get("digest") for r in results]
    done = ok and len(results) == 3 and len(set(digests)) == 1 and digests[0] is not None
    verdict = "THREE_CONSECUTIVE_PASSES" if done and not git_gate_only else ("THREE_CONSECUTIVE_PASSES_EXCEPT_THE_GIT_GATE" if done else "NOT_THREE_CONSECUTIVE_PASSES")
    art.write_json5(out_dir / "passes.json", {"session": a.session, "fingerprint": fp_start, "allow_git_gate": bool(a.allow_git_gate), "passes": results, "verdict": verdict,
                                              "all_passed_three_consecutive_times": done and not git_gate_only, "e2e_digests": digests, "e2e_digest": digests[0] if done else None},
                    overwrite=False)
    print(verdict, flush=True)
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
