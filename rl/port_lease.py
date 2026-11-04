"""Machine-wide exclusive leases on loopback ports (INFRA_2026-11-04.md, fix 1; REVIEW_2026-11-03.md D3).

The M2 launcher reserves a port, closes the reservation and lets the child bind it. Between the close and the bind, any other
launcher on the machine that probes the same port finds it free and may launch beside it. That is the window this module
closes for every launcher that uses it: a port is handed to a child only while its launcher holds a lease file created
with O_CREAT | O_EXCL in one shared directory, so two launchers can never hold the same port at once, whatever process,
worker or tool they run in. The lease is released after the child is gone.

A lease does not stop an unrelated program from binding the port. That case is caught by the launch-nonce handshake in
battleship_process.py, which is the actual guarantee that a client only ever steps its own game.

Standard library only (the M1/M2 rule). Leases whose holder process is gone, or that are older than STALE_AFTER_S, are
reclaimed. Directory: $BATTLESHIP_PORT_LEASE_DIR, else <system temp>/battleship_port_leases.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

LEASE_DIR_ENV = "BATTLESHIP_PORT_LEASE_DIR"
STALE_AFTER_S = 24 * 3600.0


def _lab_guard() -> Any:
    """The lab guard class when it is installed in this process (rl/frs_guard.py), else None. Looked up, never imported:
    this module stays standard library only and usable outside the lab."""
    mod = sys.modules.get("frs_guard")
    guard = getattr(mod, "LabGuard", None) if mod is not None else None
    if guard is not None and getattr(guard, "installed", False) and getattr(guard, "lab", None):
        return guard
    return None


def lease_dir() -> Path:
    """$BATTLESHIP_PORT_LEASE_DIR, else <system temp>/battleship_port_leases. Under the lab guard (which refuses and records
    every write outside the lab root) the leases live in <lab root>/port_leases instead, unless the variable already points
    inside the lab root: every lab process (main, workers, verification replays) arms the same guard, so they share it."""
    d = os.environ.get(LEASE_DIR_ENV)
    guard = _lab_guard()
    if guard is not None:
        if d and guard.inside_lab(d):
            return Path(d)
        return Path(guard.lab[0]) / "port_leases"
    return Path(d) if d else Path(tempfile.gettempdir()) / "battleship_port_leases"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5  # access denied: it exists
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259  # STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class PortLease:
    """One held lease. release() is idempotent and removes the file only if it is still this lease's."""

    def __init__(self, port: int, path: Path, token: str):
        self.port = int(port)
        self.path = Path(path)
        self.token = token
        self.released = False

    def note_child(self, child_pid: int) -> None:
        """Record the child's pid in the lease (diagnostics only; ownership stays with the launcher's pid)."""
        rec = read_lease(self.path)
        if rec is None or rec.get("token") != self.token:
            return
        rec["child_pid"] = int(child_pid)
        tmp = self.path.with_name(self.path.name + f".{self.token}.tmp")
        try:
            tmp.write_text(json.dumps(rec), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:  # a reader holding the file open on Windows: the note is diagnostics only
            try:
                tmp.unlink()
            except OSError:
                pass

    def release(self) -> None:
        if self.released:
            return
        self.released = True
        rec = read_lease(self.path)
        if rec is not None and rec.get("token") == self.token:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass

    def __repr__(self) -> str:
        return f"PortLease(port={self.port}, path={str(self.path)!r}, released={self.released})"


def lease_path(port: int, directory: Optional[Path] = None) -> Path:
    return Path(directory or lease_dir()) / f"port_{int(port)}.lease"


def read_lease(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def holder(port: int, directory: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """The live lease record on `port`, or None when it is free (a stale lease counts as free)."""
    p = lease_path(port, directory)
    rec = read_lease(p)
    if rec is None:
        return None if not p.exists() else {"unreadable": True}
    return None if _stale(rec) else rec


def _stale(rec: Dict[str, Any]) -> bool:
    if rec.get("unreadable"):
        return False
    if time.time() - float(rec.get("created", 0.0)) > STALE_AFTER_S:
        return True
    return not _pid_alive(int(rec.get("pid", 0)))


def try_acquire(port: int, *, owner: str = "", directory: Optional[Path] = None) -> Optional[PortLease]:
    """Take the lease on `port`, or return None when a live launcher holds it. A stale lease is reclaimed once."""
    d = Path(directory or lease_dir())
    d.mkdir(parents=True, exist_ok=True)
    p = lease_path(port, d)
    token = uuid.uuid4().hex
    rec = {"port": int(port), "pid": os.getpid(), "token": token, "owner": str(owner)[:200], "created": time.time(), "child_pid": None}
    for attempt in range(2):
        try:
            fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            old = read_lease(p)
            if attempt == 0 and old is not None and _stale(old):
                try:
                    p.unlink()
                except FileNotFoundError:
                    pass
                continue
            if attempt == 0 and old is None:
                # unreadable: either being written right now, or a torn file left by a crash; give the writer a moment
                time.sleep(0.05)
                old = read_lease(p)
                if old is None and p.exists() and time.time() - p.stat().st_mtime > 5.0:
                    try:
                        p.unlink()
                    except FileNotFoundError:
                        pass
                    continue
            return None
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(rec))
        return PortLease(port, p, token)
    return None
