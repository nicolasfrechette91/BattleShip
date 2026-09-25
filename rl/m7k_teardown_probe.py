#!/usr/bin/env python3
"""M7k: probe for the one unexplained `leak_free: false` (two non-BattleShip job processes after the v3 PPO smoke).

    python rl/m7k_teardown_probe.py micro   [--iterations 400]      # no game: the trainer's end check in a loop
    python rl/m7k_teardown_probe.py smoke   [--repeats 6]           # bounded PPO smokes with an instrumented check
    python rl/m7k_teardown_probe.py suite   [--repeats 3]           # the full M7j game suite, instrumented
    python rl/m7k_teardown_probe.py files   [--episodes 40 --workers 4]   # who holds the game's files after close()

The trainer's end-of-run check (rl/m7_trainer.py) is:
    survivors = wait_until_no_process(BATTLESHIP_IMAGE, timeout=20.0)     # polls `tasklist` (a child process)
    job_pids  = [p for p in job.pids() if p != os.getpid() and pid_alive(p)]   # one instantaneous sample
`micro` repeats exactly that pair with no game running and records, for every job pid seen, its image name, parent
pid and how long it stays alive after the sample (Toolhelp snapshot + OpenProcess; no psutil). `smoke` runs the
M7j v3 PPO smoke configuration repeatedly in one process (as the M7j game suite does) with the job's pids() wrapped
by the same recorder. Nothing here changes a trainer, worker or reward code path. Outputs: runs/m7k/teardown/.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

RL_DIR = Path(__file__).resolve().parent
REPO_ROOT = RL_DIR.parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

OUT = REPO_ROOT / "runs" / "m7k" / "teardown"
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
TH32CS_SNAPPROCESS = 0x00000002


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]


_k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
_k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]


def process_table() -> Dict[int, Dict[str, Any]]:
    snap = _k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    table: Dict[int, Dict[str, Any]] = {}
    try:
        e = PROCESSENTRY32W()
        e.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = _k32.Process32FirstW(snap, ctypes.byref(e))
        while ok:
            table[int(e.th32ProcessID)] = {"name": e.szExeFile, "ppid": int(e.th32ParentProcessID)}
            ok = _k32.Process32NextW(snap, ctypes.byref(e))
    finally:
        _k32.CloseHandle(snap)
    return table


class Recorder:
    """Wraps KillOnCloseJob.pids(): every call records the live job pids with names, parents and survival time."""

    def __init__(self, job: Any):
        self.job = job
        self.orig = job.pids
        self.events: List[Dict[str, Any]] = []
        job.pids = self.pids

    def pids(self) -> List[int]:
        from m7_runtime import pid_alive

        t = time.perf_counter()
        pids = self.orig()
        table = process_table()
        me = os.getpid()
        live = [p for p in pids if p != me and pid_alive(p)]
        if live:
            ev = {"t_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "pids": [
                {"pid": p, **table.get(p, {"name": None, "ppid": None}),
                 "parent_name": (table.get(table.get(p, {}).get("ppid"), {}) or {}).get("name")} for p in live]}
            self.events.append(ev)
            threading.Thread(target=self._follow, args=(ev, live, t), daemon=True).start()
        return pids

    @staticmethod
    def _follow(ev: Dict[str, Any], live: List[int], t0: float) -> None:
        from m7_runtime import pid_alive

        alive = set(live)
        gone: Dict[int, float] = {}
        while alive and time.perf_counter() - t0 < 30.0:
            for p in list(alive):
                if not pid_alive(p):
                    gone[p] = round((time.perf_counter() - t0) * 1000.0, 1)
                    alive.discard(p)
            time.sleep(0.005)
        for d in ev["pids"]:
            d["alive_ms_after_sample"] = gone.get(d["pid"], ">30000")


def console_state() -> Dict[str, Any]:
    return {"console_window": bool(_k32.GetConsoleWindow()), "pid": os.getpid()}



# -- Windows Restart Manager: which process holds a file ------------------------------------------------------------

class _RM_UNIQUE_PROCESS(ctypes.Structure):
    _fields_ = [("dwProcessId", wintypes.DWORD), ("ProcessStartTime", wintypes.FILETIME)]


class _RM_PROCESS_INFO(ctypes.Structure):
    _fields_ = [("Process", _RM_UNIQUE_PROCESS), ("strAppName", ctypes.c_wchar * 256),
                ("strServiceShortName", ctypes.c_wchar * 64), ("ApplicationType", ctypes.c_int),
                ("AppStatus", wintypes.ULONG), ("TSSessionId", wintypes.DWORD), ("bRestartable", wintypes.BOOL)]


def file_holders(paths: Sequence[str]) -> List[Dict[str, Any]]:
    """Processes that currently have any of these files open (RmGetList); [] if none or on API failure."""
    rm = ctypes.WinDLL("rstrtmgr")
    session = wintypes.DWORD()
    key = ctypes.create_unicode_buffer(64)
    if rm.RmStartSession(ctypes.byref(session), 0, key) != 0:
        return [{"error": "RmStartSession"}]
    try:
        arr = (ctypes.c_wchar_p * len(paths))(*[str(x) for x in paths])
        if rm.RmRegisterResources(session, len(paths), arr, 0, None, 0, None) != 0:
            return [{"error": "RmRegisterResources"}]
        needed, count, reasons = wintypes.UINT(0), wintypes.UINT(16), wintypes.DWORD(0)
        info = (_RM_PROCESS_INFO * 16)()
        rc = rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), info, ctypes.byref(reasons))
        if rc != 0:
            return [{"error": f"RmGetList {rc}", "needed": int(needed.value)}]
        table = process_table()
        out = []
        for i in range(count.value):
            pid = int(info[i].Process.dwProcessId)
            t = table.get(pid, {})
            out.append({"pid": pid, "app": info[i].strAppName, "image": t.get("name"), "ppid": t.get("ppid"),
                        "parent_image": (table.get(t.get("ppid"), {}) or {}).get("name"), "type": int(info[i].ApplicationType)})
        return out
    finally:
        rm.RmEndSession(session)


def _files_episode(k: int, steps: int, root: str) -> Dict[str, Any]:
    """One short episode (neutral input), then: job processes, holders of the game's files, time until deletable."""
    from battleship_process import BattleShipEpisode, LaunchConfig
    from m7_runtime import PortCandidates, install_kill_on_close_job, pid_alive, prepare_worker_runtime, remove_worker_runtime

    job = install_kill_on_close_job()
    work = Path(root) / f"f{k:04d}"
    rt = work / "runtime"
    prepare_worker_runtime(rt, REPO_ROOT / "build-us" / "Release" / "BattleShip.exe")
    port, _ = PortCandidates(1 + k % 8).claim()
    cfg = LaunchConfig(executable=REPO_ROOT / "build-us" / "Release" / "BattleShip.exe", working_dir=rt,
                       run_root=work / "episodes", port=port, startup_timeout=30.0, ready_timeout=90.0,
                       request_timeout=15.0, exit_timeout=30.0,
                       extra_env={"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1"})
    ep = BattleShipEpisode(cfg, index=40000 + k)
    with ep:
        ep.start()
        for _ in range(steps):
            ep.client.step(0, 0, 0)
    t0 = time.perf_counter()
    game_pid = ep.pid
    table = process_table()
    me = os.getpid()
    job_live = [{"pid": p, **table.get(p, {"name": None, "ppid": None})} for p in job.pids() if p != me and pid_alive(p)]
    log = rt / "logs" / "BattleShip.log"
    holders = file_holders([str(log)]) if log.exists() else []
    attempts, locked_first = 0, None
    while True:
        attempts += 1
        try:
            remove_worker_runtime(rt)
            break
        except PermissionError as exc:
            locked_first = locked_first or str(getattr(exc, "filename", exc))
            if time.perf_counter() - t0 > 20:
                break
            time.sleep(0.02)
    return {"k": k, "game_pid": game_pid, "cleanup": ep.cleanup_action, "job_live_after_close": job_live,
            "holders_at_close": holders, "delete_attempts": attempts, "locked_file": locked_first,
            "deletable_after_ms": round((time.perf_counter() - t0) * 1000, 1)}


def cmd_files(a: argparse.Namespace) -> Dict[str, Any]:
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor

    from m7_runtime import install_kill_on_close_job

    install_kill_on_close_job()
    root = OUT / f"files_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    root.mkdir(parents=True)
    ctx = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=a.workers, mp_context=ctx) as ex:
        res = list(ex.map(_files_episode, range(a.episodes), [a.steps] * a.episodes, [str(root)] * a.episodes))
    locked = [r for r in res if r["delete_attempts"] > 1]
    return {"mode": "files", "episodes": a.episodes, "workers": a.workers, "steps": a.steps,
            "locked_after_close": len(locked), "job_live_after_close": sum(1 for r in res if r["job_live_after_close"]),
            "holders_seen": sorted({(h.get("image") or h.get("app") or "?") for r in res for h in r["holders_at_close"]}),
            "job_names_seen": sorted({str(j.get("name")) for r in res for j in r["job_live_after_close"]}),
            "deletable_after_ms_max": max(r["deletable_after_ms"] for r in res), "results": res}


def cmd_micro(a: argparse.Namespace) -> Dict[str, Any]:
    from m7_runtime import install_kill_on_close_job, wait_until_no_process

    job = install_kill_on_close_job()
    rec = Recorder(job)
    t0 = time.perf_counter()
    for _ in range(a.iterations):
        wait_until_no_process("m7k_probe_no_such_image.exe", timeout=20.0)   # the trainer pair (tasklist child), no game
        job.pids()
    time.sleep(1.0)
    return {"mode": "micro", "iterations": a.iterations, "console": console_state(), "job_active": job.active,
            "samples_with_leftovers": len(rec.events), "events": rec.events[:50],
            "leftover_names": sorted({d["name"] for e in rec.events for d in e["pids"]}),
            "wall_s": round(time.perf_counter() - t0, 1)}


def cmd_smoke(a: argparse.Namespace) -> Dict[str, Any]:
    import m7j_tests as mt
    from m7_runtime import install_kill_on_close_job
    from m7_smoke import Suite
    from m7_trainer import config_from_experiment, run_training

    job = install_kill_on_close_job()
    rec = Recorder(job)
    root = OUT / f"smoke_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    root.mkdir(parents=True)
    suite = Suite(root)
    runs = []
    for k in range(a.repeats):
        n0 = len(rec.events)
        exp = mt._derive(suite, mt.PILOT_TOML, f"probe_{k}", **mt.SMOKE)
        s = run_training(config_from_experiment(exp))
        runs.append({"run": k, "status": s["status"], "leak_free": s["cleanup"]["leak_free"],
                     "job_processes_after": s["cleanup"]["job_processes_after"], "events": rec.events[n0:]})
        print(json.dumps({"run": k, "leak_free": s["cleanup"]["leak_free"], "job": s["cleanup"]["job_processes_after"]}),
              flush=True)
    time.sleep(1.0)
    return {"mode": "smoke", "repeats": a.repeats, "console": console_state(), "runs": runs,
            "leak_free_false": sum(1 for r in runs if not r["leak_free"]),
            "leftover_names": sorted({d["name"] for r in runs for e in r["events"] for d in e["pids"]})}


def cmd_suite(a: argparse.Namespace) -> Dict[str, Any]:
    """The full M7j game suite (the original failure's context) with the recorder on the shared job object."""
    import m7j_tests as mt
    from m7_runtime import install_kill_on_close_job

    job = install_kill_on_close_job()
    rec = Recorder(job)
    rounds = []
    for k in range(a.repeats):
        n0 = len(rec.events)
        rc = mt.main(["game", "--root", str(OUT / f"suite_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_r{k}")])
        rounds.append({"round": k, "exit": rc, "events": rec.events[n0:]})
        print(json.dumps({"round": k, "exit": rc, "leftover_samples": len(rec.events) - n0}), flush=True)
    time.sleep(1.0)
    return {"mode": "suite", "repeats": a.repeats, "console": console_state(), "rounds": rounds,
            "failed_rounds": sum(1 for r in rounds if r["exit"]),
            "leftover_names": sorted({d["name"] for r in rounds for e in r["events"] for d in e["pids"]})}


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("micro")
    m.add_argument("--iterations", type=int, default=400)
    s = sub.add_parser("smoke")
    s.add_argument("--repeats", type=int, default=6)
    u = sub.add_parser("suite")
    u.add_argument("--repeats", type=int, default=3)
    fl = sub.add_parser("files")
    fl.add_argument("--episodes", type=int, default=40)
    fl.add_argument("--workers", type=int, default=4)
    fl.add_argument("--steps", type=int, default=300)
    a = p.parse_args(argv)
    r = {"micro": cmd_micro, "smoke": cmd_smoke, "suite": cmd_suite, "files": cmd_files}[a.cmd](a)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{a.cmd}_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
    path.write_text(json.dumps(r, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in r.items() if k not in ("events", "runs", "rounds", "results")}, indent=1))
    print(f"written {path}")
    return 0


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    sys.exit(main())
