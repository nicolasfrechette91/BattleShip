#!/usr/bin/env python3
"""Machine sampler for an M8-sd2 launch day (the N2 rule as a tracked tool; read only; standard library only; sd1's hand script of 2026-10-11 with an argument parser and --once).

Every --interval seconds (default 30): one JSON line appended to --out (opened in append mode and closed at once), with the local time, available memory, free commit, and the watched
processes (node, playwright, vmmem / vmmemWSL, WSL hosts, idea64, browsers, video tools, BattleShip, python, claude). A claude.exe pid not in the baseline is classified once through CIM
(Claude Code CLI or desktop helper). Any watched condition also appends one line to --alerts (opened and closed at once). It never kills or closes anything. With --once it writes one
sample and exits (the testable form).

    python -B -X utf8 tools/m8_sd2/machine_sampler.py --out logs/m8_sd2_run/machine_samples.jsonl --alerts logs/m8_sd2_run/machine_alerts.txt \\
        --baseline-claude <pid,pid,...> [--baseline-quiet <pid,...>] [--interval 30] [--once]
"""
import argparse
import csv
import ctypes
import io
import json
import subprocess
import sys
import time


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def memory():
    m = MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return round(m.ullAvailPhys / 2 ** 20), round(m.ullAvailPageFile / 2 ** 20)


def tasklist():
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, errors="replace").stdout
    rows = []
    for r in csv.reader(io.StringIO(out)):
        if len(r) >= 5:
            try:
                ws = int(r[4].replace("\xa0", "").replace(",", "").replace(" ", "").replace("K", "")) // 1024
            except ValueError:
                ws = None
            rows.append((r[0], int(r[1]), ws))
    return rows


def classify(pid):
    cmd = ("$x = Get-CimInstance Win32_Process -Filter 'ProcessId=%d'; if ($x) { $c = [string]$x.CommandLine; "
           "if ($c -like '*claude-code*') { 'claude-code' } elseif ($c -match '--type=([a-z-]+)') { 'desktop-' + $matches[1] } else { 'desktop-main-or-other' } } else { 'gone' }" % pid)
    try:
        return subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=60).stdout.strip() or "unknown"
    except Exception as exc:  # noqa: BLE001
        return f"error {type(exc).__name__}"


WATCH = ("node.exe", "vmmem", "vmmemwsl", "wsl.exe", "wslhost.exe", "idea64.exe", "chrome.exe", "msedge.exe", "firefox.exe", "avidemux", "battleship.exe", "python.exe", "pythonw.exe",
         "claude.exe", "openshot", "obs64.exe", "vlc.exe")
ALERT = ("node.exe", "vmmem", "vmmemwsl", "idea64.exe", "chrome.exe", "msedge.exe", "firefox.exe", "avidemux", "obs64.exe", "openshot")


def append(path, line):
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def sample(known, quiet):
    """One sample: the record to append and the alert lines (pure given the process table and the memory readings)."""
    t = time.strftime("%Y-%m-%dT%H:%M:%S")
    avail, commit = memory()
    rows = tasklist()
    watched = [(n, p, w) for (n, p, w) in rows if any(n.lower().startswith(k) or k in n.lower() for k in WATCH) or "playwright" in n.lower()]
    alerts = []
    for n, p, w in watched:
        ln = n.lower()
        if p not in quiet and ("playwright" in ln or any(ln.startswith(k) for k in ALERT)):
            alerts.append(f"{n} pid {p} ws {w} MB")
        if ln == "claude.exe" and p not in known:
            known[p] = classify(p)
            if known[p] == "claude-code":
                alerts.append(f"NEW Claude Code process pid {p} ws {w} MB")
    counts = {}
    for n, _p, _w in watched:
        counts[n] = counts.get(n, 0) + 1
    rec = {"t": t, "available_mb": avail, "commit_free_mb": commit, "counts": counts,
           "battleship": len([1 for n, _p, _w in watched if n.lower() == "battleship.exe"]),
           "claude": [[p, w, known.get(p)] for n, p, w in watched if n.lower() == "claude.exe"],
           "python": [[p, w] for n, p, w in watched if n.lower() in ("python.exe", "pythonw.exe")],
           "other": [[n, p, w] for n, p, w in watched if n.lower() not in ("claude.exe", "python.exe", "pythonw.exe", "battleship.exe")],
           "alerts": alerts}
    return t, rec, alerts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="the JSONL sample file (appended, one line per sample)")
    ap.add_argument("--alerts", required=True, help="the alert file (appended, one line per alert)")
    ap.add_argument("--baseline-claude", required=True, help="comma-separated claude.exe pids present at the baseline (never alerted; an empty string for none)")
    ap.add_argument("--baseline-quiet", default="", help="comma-separated pids of other watched processes present at the baseline (recorded, never alerted)")
    ap.add_argument("--interval", type=float, default=30.0)
    ap.add_argument("--once", action="store_true", help="one sample, then exit")
    a = ap.parse_args()
    known = {int(x): "baseline" for x in a.baseline_claude.split(",") if x.strip()}
    quiet = {int(x) for x in a.baseline_quiet.split(",") if x.strip()}
    while True:
        try:
            t, rec, alerts = sample(known, quiet)
        except Exception as exc:  # noqa: BLE001
            append(a.out, json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "error": f"{type(exc).__name__}: {exc}"}))
            if a.once:
                return 1
            time.sleep(a.interval)
            continue
        append(a.out, json.dumps(rec))
        for x in alerts:
            append(a.alerts, f"{t} {x}")
        if a.once:
            return 0
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main())
