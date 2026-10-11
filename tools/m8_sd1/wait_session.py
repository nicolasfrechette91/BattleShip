#!/usr/bin/env python3
"""Waits for the detached M8-sd1 session: polls runs/m8_rd_sd1/sessions/sd1/state.json and the launched pid (logs/m8_sd1_run/launch_record.txt), prints one progress line per change to
logs/m8_sd1_run/wait_log.txt, and exits when the session recorded `done` and the process has exited (or the hard timeout passed). Reads only. The repository root is resolved from this
file's location (tools/m8_sd1/) or given with --repo:

    python -B -X utf8 tools/m8_sd1/wait_session.py --session sd1 [--repo <repo>] [--hours 2.5]
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def pid_alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", required=True, choices=["sd1"], help="the session to wait for (sd1)")
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    ap.add_argument("--hours", type=float, default=2.5)
    a = ap.parse_args()
    if not sys.flags.dont_write_bytecode:
        print("refused: run with python -B")
        return 2
    repo = a.repo
    state_p = repo / "runs" / "m8_rd_sd1" / "sessions" / "sd1" / "state.json"
    logs = repo / "logs" / "m8_sd1_run"
    log_p = logs / "wait_log.txt"
    rec_p = logs / "launch_record.txt"
    if not rec_p.is_file():
        print(json.dumps({"error": f"no launch record at {rec_p} (was the session launched with launch_detached.ps1 -Session sd1 -Repo <repo>?)"}))
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
            time.sleep(30)
            st2 = json.loads(state_p.read_text(encoding="utf-8-sig")) if state_p.is_file() else None
            if not (st2 and st2.get("phase") == "done"):
                print(json.dumps({"error": "the process exited without a done state", **line}))
                return 1
        time.sleep(60)
    print(json.dumps({"error": "hard timeout", **(last or {})}))
    return 1


if __name__ == "__main__":
    sys.exit(main())
