#!/usr/bin/env python3
"""The S7 launch check as code: run WITHIN TWO MINUTES of tools/m8_sd2/launch_detached.ps1. It reads logs/m8_sd2_run/launch_record.txt (the pid, the UTC launch time, the session), and
prints EVERY condition with its result:

    record      the launch record exists and names this session
    alive       the recorded pid is alive (tasklist)
    age         the launch is at most --max-age-s seconds old (default 120: the S7 window)
    refused     neither session_stdout.txt nor session_stderr.txt contains the word "refused"
    traceback   neither contains "Traceback"
    game        the number of BattleShip processes (reported; the session's own cap is 10)

Exit codes: 0 every condition holds; 3 the ONLY failing condition is the age limit (the process is alive, nothing refused, no traceback: the check was run late); 1 any other failure
(a stop and a report, never a relaunch); 2 no launch record or another session's record. Appends its findings to logs/m8_sd2_run/s7_check.txt (never overwritten). Reads only.

    python -B -X utf8 tools/m8_sd2/check_launch.py --session sd2 [--repo <repo>] [--max-age-s 120]
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

EXIT_OK = 0
EXIT_OTHER_FAILURE = 1
EXIT_NO_RECORD = 2
EXIT_LATE_ONLY = 3
BAD_WORDS = (("refused", "refused"), ("traceback", "Traceback"))


def pid_alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    return f'"{pid}"' in out


def battleship_count() -> int:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq BattleShip.exe", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    return sum(1 for ln in out.splitlines() if ln.lower().startswith('"battleship.exe"'))


def check(repo: Path, session: str, max_age_s: float, now: float) -> dict:
    """Every condition with its result (pure given the files and the clock; the process queries are the only side reads)."""
    logs = repo / "logs" / f"m8_{session}_run"
    rec_p = logs / "launch_record.txt"
    out = {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "session": session, "record_path": str(rec_p), "conditions": {}, "exit": None, "verdict": None}
    c = out["conditions"]
    if not rec_p.is_file():
        c["record"] = {"ok": False, "detail": "no launch record"}
        out["exit"], out["verdict"] = EXIT_NO_RECORD, "NO_RECORD"
        return out
    rec = rec_p.read_text(encoding="utf-8-sig").strip()
    try:
        pid = int(rec.split("pid=")[1].split()[0])
        launched = rec.split(" at ")[1].split()[0]
        rec_session = rec.split("session=")[1].split()[0]
    except (IndexError, ValueError):
        c["record"] = {"ok": False, "detail": f"unparsable launch record: {rec[:120]}"}
        out["exit"], out["verdict"] = EXIT_NO_RECORD, "NO_RECORD"
        return out
    if rec_session != session:
        c["record"] = {"ok": False, "detail": f"the launch record is session {rec_session!r}'s"}
        out["exit"], out["verdict"] = EXIT_NO_RECORD, "NO_RECORD"
        return out
    c["record"] = {"ok": True, "detail": rec, "pid": pid, "launched_utc": launched}
    alive = pid_alive(pid)
    c["alive"] = {"ok": alive, "detail": f"pid {pid} {'alive' if alive else 'not found'}"}
    try:
        t_launch = datetime.strptime(launched, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
        age = now - t_launch
        c["age"] = {"ok": age <= max_age_s, "detail": f"{age:.0f} s since the launch (limit {max_age_s:.0f} s)", "age_s": round(age, 1)}
    except ValueError:
        c["age"] = {"ok": False, "detail": f"unparsable launch time {launched!r}"}
    for key, word in BAD_WORDS:
        hits = []
        for name in ("session_stdout.txt", "session_stderr.txt"):
            p = logs / name
            if p.is_file():
                for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
                    if word in ln:
                        hits.append(f"{name}: {ln.strip()[:200]}")
        c[key] = {"ok": not hits, "detail": hits[:3] if hits else f"no {word!r} in the session's stdout or stderr"}
    n = battleship_count()
    c["game"] = {"ok": True, "detail": f"{n} BattleShip process(es)", "count": n}
    failing = [k for k, v in c.items() if not v["ok"]]
    if not failing:
        out["exit"], out["verdict"] = EXIT_OK, "PASS"
    elif failing == ["age"]:
        out["exit"], out["verdict"] = EXIT_LATE_ONLY, "LATE_ONLY (the process is alive and nothing was refused, but the check ran after the S7 window)"
    else:
        out["exit"], out["verdict"] = EXIT_OTHER_FAILURE, f"FAIL ({', '.join(failing)}): stop and report; never relaunch"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", required=True, choices=["sd2"], help="the launched session (sd2)")
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    ap.add_argument("--max-age-s", type=float, default=120.0, help="the S7 window in seconds (default 120)")
    a = ap.parse_args()
    if not sys.flags.dont_write_bytecode:
        print("refused: run with python -B")
        return 2
    out = check(a.repo, a.session, a.max_age_s, time.time())
    lines = [f"S7 check {out['utc']} session={a.session}"]
    for k, v in out["conditions"].items():
        lines.append(f"  {k:<10} {'ok ' if v['ok'] else 'BAD'} {v['detail']}")
    lines.append(f"  verdict    {out['verdict']} (exit {out['exit']})")
    text = "\n".join(lines)
    print(text)
    logs = a.repo / "logs" / f"m8_{a.session}_run"
    if logs.is_dir():
        with open(logs / "s7_check.txt", "a", encoding="utf-8") as f:
            f.write(text + "\n" + json.dumps(out) + "\n")
    return int(out["exit"])


if __name__ == "__main__":
    sys.exit(main())
