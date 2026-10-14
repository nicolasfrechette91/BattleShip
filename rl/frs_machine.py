"""Fast-route lab (frs): machine measurements, readiness with the REGISTERED thresholds, the memory sampler (soft budget + registered hard caps)
and the memory projection (standard library + ctypes; Windows measurements, None elsewhere).

    readiness        available memory, free commit, free disk: m8_rd_session.READINESS, never lowered; a refusal is a stop
    caps             m8_rd_run.RunConfig().memory_caps_mb and max_battleship_processes (registered), the hard caps
    soft budget      each cap minus a fixed headroom (maxima) or plus it (minima): exploration stops cleanly before any cap (review M5)
    projection       main-process MB against archive cells (least squares), growth per explore hour, projected MB at 8 / 24 / 48 h

Design: logs/frs_prep/phase1_plan.md section 6.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import m8_rd_run as mrun  # noqa: E402
import m8_rd_session as ses  # noqa: E402

READINESS: Dict[str, float] = dict(ses.READINESS)
_RC = mrun.RunConfig(root=Path("."))
CAPS_MB: Dict[str, float] = dict(_RC.memory_caps_mb)
MAX_BATTLESHIP = int(_RC.max_battleship_processes)
# headroom between the soft budget and each registered cap (lab constants; origin: the close needs room for the archive write and the replays)
HEADROOM_MB: Dict[str, float] = {"main_private": 512, "tree_private": 1024, "tree_working_set": 512, "system_available_min": 512,
                                 "system_commit_free_min": 1024}
MINIMA = ("system_available_min", "system_commit_free_min")
SAMPLE_S = 5.0
ROW_EVERY_S = 30.0


def soft_budget(caps: Mapping[str, float] = CAPS_MB, headroom: Mapping[str, float] = HEADROOM_MB) -> Dict[str, float]:
    return {k: (float(v) + float(headroom[k]) if k in MINIMA else float(v) - float(headroom[k])) for k, v in caps.items()}


# -- measurements ---------------------------------------------------------------------------------------------------------------------------------


class _MEMSTAT(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


class _PMC(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t), ("PrivateUsage", ctypes.c_size_t)]


def memory_status() -> Optional[Dict[str, float]]:
    if os.name != "nt":
        return None
    m = _MEMSTAT()
    m.dwLength = ctypes.sizeof(_MEMSTAT)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
        return None
    return {"available_mb": m.ullAvailPhys / 2 ** 20, "commit_free_mb": m.ullAvailPageFile / 2 ** 20, "total_mb": m.ullTotalPhys / 2 ** 20}


def _k32() -> Any:
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    return k32


def main_private_mb() -> Optional[float]:
    if os.name != "nt":
        return None
    k32 = _k32()
    pmc = _PMC()
    pmc.cb = ctypes.sizeof(_PMC)
    if not k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
        return None
    return pmc.PrivateUsage / 2 ** 20


def tree_snapshot(root_pid: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Private bytes and working set of this process and every descendant (workers, BattleShip, standbys), the BattleShip count among them,
    and the system available memory / free commit. None off Windows or on failure."""
    if os.name != "nt":
        return None
    try:
        from ctypes import wintypes

        class PE(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                        ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                        ("szExeFile", ctypes.c_wchar * 260)]

        k32 = _k32()
        k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PE)]
        k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PE)]
        snap = k32.CreateToolhelp32Snapshot(0x2, 0)
        if snap in (None, wintypes.HANDLE(-1).value, -1):
            return None
        parent_of: Dict[int, int] = {}
        name_of: Dict[int, str] = {}
        try:
            pe = PE()
            pe.dwSize = ctypes.sizeof(PE)
            ok = k32.Process32FirstW(snap, ctypes.byref(pe))
            while ok:
                parent_of[int(pe.th32ProcessID)] = int(pe.th32ParentProcessID)
                name_of[int(pe.th32ProcessID)] = str(pe.szExeFile)
                ok = k32.Process32NextW(snap, ctypes.byref(pe))
        finally:
            k32.CloseHandle(snap)
        root = int(root_pid if root_pid is not None else os.getpid())
        children: Dict[int, List[int]] = {}
        for pid, ppid in parent_of.items():
            if pid != ppid:
                children.setdefault(ppid, []).append(pid)
        tree, stack = [], [root]
        while stack:
            p = stack.pop()
            if p in tree:
                continue
            tree.append(p)
            stack.extend(children.get(p, []))
        priv = ws = 0.0
        main = 0.0
        for pid in tree:
            h = k32.OpenProcess(0x1000, False, pid)
            if not h:
                continue
            try:
                pmc = _PMC()
                pmc.cb = ctypes.sizeof(_PMC)
                if k32.K32GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb):
                    priv += pmc.PrivateUsage / 2 ** 20
                    ws += pmc.WorkingSetSize / 2 ** 20
                    if pid == root:
                        main = pmc.PrivateUsage / 2 ** 20
            finally:
                k32.CloseHandle(h)
        mem = memory_status() or {}
        return {"main_private_mb": round(main, 1), "tree_private_mb": round(priv, 1), "tree_working_set_mb": round(ws, 1),
                "processes": len(tree), "battleship": sum(1 for p in tree if name_of.get(p, "").lower() == "battleship.exe"),
                "system_available_mb": round(mem.get("available_mb", 0.0), 1), "system_commit_free_mb": round(mem.get("commit_free_mb", 0.0), 1)}
    except Exception:  # noqa: BLE001 - a measurement fault is reported as no sample, never raised into the run
        return None


def disk_free_gib(p: Path) -> float:
    return shutil.disk_usage(p).free / 2 ** 30


def battleship_pids() -> Optional[List[int]]:
    from m7_runtime import BATTLESHIP_IMAGE, list_processes_named

    return list_processes_named(BATTLESHIP_IMAGE)


def readiness(lab_root: Path, *, memory: Callable[[], Optional[Mapping[str, float]]] = memory_status,
              disk: Callable[[Path], float] = disk_free_gib) -> Dict[str, Any]:
    """The registered readiness rule (m8_rd_session.readiness) on the checkout's drive, the D: drive and the lab root's drive. A problem is a
    refusal; the thresholds are never lowered."""
    problems: List[str] = []
    mem = memory()
    if mem is None:
        problems.append("memory status unavailable")
    else:
        if mem["available_mb"] < READINESS["min_available_mb"]:
            problems.append(f"available memory {mem['available_mb']:.0f} MB < {READINESS['min_available_mb']} MB")
        if mem["commit_free_mb"] < READINESS["min_commit_free_mb"]:
            problems.append(f"free commit {mem['commit_free_mb']:.0f} MB < {READINESS['min_commit_free_mb']} MB")
    free: Dict[str, float] = {}
    drives = [("C", Path(ses.REPO_ROOT), "min_free_gib_c"), ("D", Path(ses.BACKUP_ROOT.anchor or ses.BACKUP_ROOT), "min_free_gib_d")]
    lab_anchor = Path(Path(lab_root).anchor or lab_root)
    if os.path.normcase(str(lab_anchor)) not in {os.path.normcase(str(Path(p).anchor or p)) for _, p, _ in drives}:
        drives.append(("lab", lab_anchor, "min_free_gib_c"))
    for name, p, key in drives:
        try:
            free[name] = round(disk(Path(p)), 1)
        except OSError as exc:
            problems.append(f"free disk of {name}: unreadable ({exc})")
            continue
        if free[name] < READINESS[key]:
            problems.append(f"free disk on {name}: {free[name]} GiB < {READINESS[key]} GiB")
    return {"ok": not problems, "problems": problems, "memory": mem, "free_gib": free, "thresholds": dict(READINESS)}


# -- the sampler --------------------------------------------------------------------------------------------------------------------------------


def breach(snap: Mapping[str, Any], limits: Mapping[str, float], what: str) -> Optional[str]:
    """The first limit a snapshot violates (None within every limit). `what` names the limit set (soft budget or registered cap)."""
    if snap["main_private_mb"] > limits["main_private"]:
        return f"{what}: main process private {snap['main_private_mb']:.0f} MB > {limits['main_private']:.0f} MB"
    if snap["tree_private_mb"] > limits["tree_private"]:
        return f"{what}: process tree private {snap['tree_private_mb']:.0f} MB > {limits['tree_private']:.0f} MB"
    if snap["tree_working_set_mb"] > limits["tree_working_set"]:
        return f"{what}: process tree working set {snap['tree_working_set_mb']:.0f} MB > {limits['tree_working_set']:.0f} MB"
    if snap["system_available_mb"] < limits["system_available_min"]:
        return f"{what}: system available {snap['system_available_mb']:.0f} MB < {limits['system_available_min']:.0f} MB"
    if snap["system_commit_free_mb"] < limits["system_commit_free_min"]:
        return f"{what}: system free commit {snap['system_commit_free_mb']:.0f} MB < {limits['system_commit_free_min']:.0f} MB"
    return None


class Sampler:
    """Samples the process tree every `interval` seconds; remembers the first soft-budget breach, the first registered-cap breach and a
    BattleShip count above the cap in two distinct consecutive samples; appends a row (with the archive size from `extra`) every `row_every`
    seconds. A sampler fault never stops the run."""

    def __init__(self, write_row: Callable[[Dict[str, Any]], None], *, interval: float = SAMPLE_S, row_every: float = ROW_EVERY_S,
                 caps: Mapping[str, float] = CAPS_MB, soft: Optional[Mapping[str, float]] = None, max_battleship: int = MAX_BATTLESHIP,
                 snapshot: Callable[[], Optional[Dict[str, Any]]] = tree_snapshot, extra: Callable[[], Mapping[str, Any]] = lambda: {},
                 now: Callable[[], float] = time.monotonic):
        self.write_row, self.interval, self.row_every = write_row, float(interval), float(row_every)
        self.caps, self.soft = dict(caps), dict(soft if soft is not None else soft_budget(caps))
        self.max_battleship, self.snapshot, self.extra, self.now = int(max_battleship), snapshot, extra, now
        self.t0 = now()
        self.soft_breach: Optional[str] = None
        self.hard_breach: Optional[str] = None
        self.proc_breach: Optional[str] = None
        self.peak = {"main_private_mb": 0.0, "tree_private_mb": 0.0, "tree_working_set_mb": 0.0, "processes": 0, "battleship": 0,
                     "system_available_min_mb": float("inf"), "system_commit_free_min_mb": float("inf")}
        self.samples = 0
        self.series: List[Dict[str, Any]] = []
        self.last: Optional[Dict[str, Any]] = None
        self._over = 0
        self._last_row = -1e18
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def sample(self) -> Optional[Dict[str, Any]]:
        snap = self.snapshot()
        if snap is None:
            return None
        t = round(self.now() - self.t0, 1)
        with self._lock:
            self.samples += 1
            for k in ("main_private_mb", "tree_private_mb", "tree_working_set_mb", "processes", "battleship"):
                self.peak[k] = max(self.peak[k], snap.get(k, 0))
            self.peak["system_available_min_mb"] = min(self.peak["system_available_min_mb"], snap["system_available_mb"])
            self.peak["system_commit_free_min_mb"] = min(self.peak["system_commit_free_min_mb"], snap["system_commit_free_mb"])
            hard = breach(snap, self.caps, "registered memory cap")
            if hard and self.hard_breach is None:
                self.hard_breach = hard
            soft = breach(snap, self.soft, "memory budget")
            if soft and self.soft_breach is None:
                self.soft_breach = soft
            if snap.get("battleship", 0) > self.max_battleship:
                self._over += 1
                if self._over >= 2 and self.proc_breach is None:
                    self.proc_breach = f"{snap['battleship']} BattleShip processes > {self.max_battleship} in two consecutive samples"
            else:
                self._over = 0
            self.last = dict(snap, t_s=t)
            if self.now() - self._last_row >= self.row_every:
                self._last_row = self.now()
                row = dict(snap, t_s=t, **dict(self.extra()))
                self.series.append(row)
                try:
                    self.write_row(row)
                except OSError:
                    pass
        return snap

    def start(self) -> "Sampler":
        def loop() -> None:
            while not self._stop.is_set():
                try:
                    self.sample()
                except Exception:  # noqa: BLE001 - never stops the run
                    pass
                self._stop.wait(self.interval)

        self._thread = threading.Thread(target=loop, name="frs-sampler", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> Dict[str, Any]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=15)
        try:
            self._last_row = -1e18
            self.sample()                     # a final row
        except Exception:  # noqa: BLE001
            pass
        return self.report()

    def report(self) -> Dict[str, Any]:
        peak = {k: (None if v in (float("inf"),) else round(v, 1) if isinstance(v, float) else v) for k, v in self.peak.items()}
        return {"samples": self.samples, "peak": peak, "soft_breach": self.soft_breach, "hard_breach": self.hard_breach,
                "proc_breach": self.proc_breach, "interval_s": self.interval, "soft_budget_mb": self.soft, "caps_mb": self.caps}


# -- the projection ---------------------------------------------------------------------------------------------------------------------------------


def fit(xs: Sequence[float], ys: Sequence[float]) -> Optional[Tuple[float, float]]:
    """Least squares y = a + b x (None with fewer than three points or no spread in x)."""
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return my - b * mx, b


def projection(series: Sequence[Mapping[str, Any]], *, load_mb: Optional[float], load_cells: int, explore_s: float,
               soft_main_mb: float, cap_main_mb: float, horizons_h: Sequence[float] = (8.0, 24.0, 48.0)) -> Dict[str, Any]:
    """Memory per cell and the projection for longer runs, from the explore-phase rows (t_s, cells, main_private_mb)."""
    rows = [r for r in series if r.get("cells") is not None and r.get("main_private_mb")]
    out: Dict[str, Any] = {"load_main_mb": round(load_mb, 1) if load_mb else None,
                           "bytes_per_cell_at_load": round(load_mb * 2 ** 20 / load_cells) if load_mb and load_cells else None,
                           "rows": len(rows)}
    if len(rows) < 2 or explore_s <= 0:
        return out
    c0, c1 = int(rows[0]["cells"]), int(rows[-1]["cells"])
    m0, m1 = float(rows[0]["main_private_mb"]), float(rows[-1]["main_private_mb"])
    hours = explore_s / 3600.0
    cells_per_h = (c1 - c0) / hours
    f = fit([float(r["cells"]) for r in rows], [float(r["main_private_mb"]) for r in rows])
    per_cell = f[1] if f else ((m1 - m0) / (c1 - c0) if c1 > c0 else None)
    out.update({"new_cells": c1 - c0, "cells_per_explore_h": round(cells_per_h, 1),
                "mb_per_1000_new_cells": round(per_cell * 1000, 2) if per_cell is not None else None,
                "main_mb_explore_start": round(m0, 1), "main_mb_explore_end": round(m1, 1),
                "growth_mb_per_explore_h_direct": round((m1 - m0) / hours, 1)})
    if per_cell is None:
        return out
    g = max(per_cell * cells_per_h, (m1 - m0) / hours)            # the larger of the fitted and the direct growth (conservative)
    out["growth_mb_per_explore_h"] = round(g, 1)
    out["projected_main_mb"] = {f"{h:g}h": round(m0 + g * h, 0) for h in horizons_h}
    out["hours_to_soft_budget"] = round((soft_main_mb - m1) / g + hours, 1) if g > 0 else None
    out["hours_to_cap"] = round((cap_main_mb - m1) / g + hours, 1) if g > 0 else None
    return out
