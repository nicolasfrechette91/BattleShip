#!/usr/bin/env python3
"""Waits for the detached M8-sd2 session: polls runs/m8_rd_sd2/sessions/sd2/state.json and the launched pid (logs/m8_sd2_run/launch_record.txt), prints one progress line per change to
logs/m8_sd2_run/wait_log.txt, and exits when the session recorded `done` and the process has exited (or the hard limit passed: the limit ends THE WAITER only, never the session). Reads only.
The repository root is resolved from this file's location (tools/m8_sd2/) or given with --repo:

    python -B -X utf8 tools/m8_sd2/wait_session.py --session sd2 [--repo <repo>] [--hours 3.5] [--poll-s 60]
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_HOURS = 3.5                                # sd1's review lesson N7: the limit fits a 90-minute process with room; it never ends the session


def pid_alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", required=True, choices=["sd2"], help="the session to wait for (sd2)")
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    ap.add_argument("--hours", type=float, default=DEFAULT_HOURS, help=f"the waiter's own limit in hours (default {DEFAULT_HOURS}); it ends the waiter only")
    ap.add_argument("--poll-s", type=float, default=60.0, help="seconds between polls (default 60; the tests use a short interval)")
    a = ap.parse_args()
    if not sys.flags.dont_write_bytecode:
        print("refused: run with python -B")
        return 2
    if a.poll_s < 1.0:
        print("refused: --poll-s is at least 1 second")
        return 2
    repo = a.repo
    state_p = repo / "runs" / "m8_rd_sd2" / "sessions" / "sd2" / "state.json"
    logs = repo / "logs" / "m8_sd2_run"
    log_p = logs / "wait_log.txt"
    rec_p = logs / "launch_record.txt"
    if not rec_p.is_file():
        print(json.dumps({"error": f"no launch record at {rec_p} (was the session launched with launch_detached.ps1 -Session sd2 -Repo <repo>?)"}))
        return 1
    rec = rec_p.read_text(encoding="utf-8-sig")
    pid = int(rec.split("pid=")[1].split()[0])
    rec_session = rec.split("session=")[1].split()[0] if "session=" in rec else None
    if rec_session != a.session:
        print(json.dumps({"error": f"the launch record is session {rec_session!r}'s, not {a.session!r}'s"}))
        return 1
    t0 = time.time()
    last = None
    while time.time() - t0 < a.hours * 3600:
        st = None
        if state_p.is_file():
            try:
                st = json.loads(state_p.read_text(encoding="utf-8-sig"))
            except Exception:                                        # noqa: BLE001 - a partial write; read again next poll
                st = None
        alive = pid_alive(pid)
        done = bool(st and st.get("phase") == "done")
        line = {"t_min": round((time.time() - t0) / 60, 1), "alive": alive, "session": (st or {}).get("session"), "phase": (st or {}).get("phase"), "ticks": (st or {}).get("ticks"),
                "elapsed_s": ((st or {}).get("clock") or {}).get("elapsed_s"), "done": done, "decision": (st or {}).get("decision"), "invalid": (st or {}).get("invalid"),
                "incomplete": (st or {}).get("incomplete")}
        if line != last:
            with open(log_p, "a", encoding="utf-8") as f:
                f.write(json.dumps(line) + "\n")
            last = line
        if done and not alive:
            print(json.dumps(line))
            return 0
        if not alive and st is None and time.time() - t0 > 2400:
            print(json.dumps({"error": "the process exited before any state record", **line}))
            return 1
        if not alive and st is not None and not done:
            time.sleep(min(30.0, a.poll_s))
            st2 = json.loads(state_p.read_text(encoding="utf-8-sig")) if state_p.is_file() else None
            if not (st2 and st2.get("phase") == "done"):
                print(json.dumps({"error": "the process exited without a done state", **line}))
                return 1
        time.sleep(a.poll_s)
    print(json.dumps({"error": "hard timeout (the waiter's own limit; the session, if alive, continues)", **(last or {})}))
    return 1


if __name__ == "__main__":
    sys.exit(main())
