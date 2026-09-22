#!/usr/bin/env python3
"""M7: host-side runtime utilities for parallel BattleShip training. Standard library only.

Everything here is Python-owned and outside the game. Nothing in M1-M6 changes:

- Per-worker isolated runtime directories. BattleShip (portable Windows
  build) resolves its app directory to the working directory ("."), so a
  worker whose processes run with cwd = its own runtime directory reads and
  writes a PRIVATE BattleShip.cfg.json, imgui.ini and logs/. The user's real
  build-us/Release/BattleShip.cfg.json is never opened by a worker process.
  Read-only files the game locates "cwd first, then the executable's
  directory" (f3d.o2r, BattleShip.o2r, gamecontrollerdb.txt, assets/) are
  deliberately NOT linked: the native fallback reads them from the
  executable directory. Only `.tcc/` (scripting include paths, resolved in
  the cwd only) gets a directory junction. See docs/rl_parallel_training_m7.md
  "Isolated worker directories" for the source-level proof.
- Rank-specific loopback port blocks below the OS dynamic (outgoing) port
  range, with a fresh candidate on every startup attempt.
- A Windows kill-on-close job object: every process started by the trainer
  (spawn workers and their BattleShip children) dies with the trainer, even
  when the trainer is killed hard.
- Process listing / liveness, system CPU times, file fingerprints, git and
  executable revisions.

No RNG inspection or control of the game exists here.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import random
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from battleship_process import loopback_port_is_free  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
IS_WINDOWS = platform.system() == "Windows"
BATTLESHIP_IMAGE = "BattleShip.exe" if IS_WINDOWS else "BattleShip"

# -- isolated worker runtime directories ------------------------------------------------------

USER_CONFIG_NAME = "BattleShip.cfg.json"
# Mutable files the game reads AND writes in its app directory (= cwd): every
# worker gets its own copy; nothing mutable is ever linked between workers.
PRIVATE_COPY_FILES: Tuple[str, ...] = (USER_CONFIG_NAME, "imgui.ini")
# Immutable directories resolved in the cwd only (no executable-dir
# fallback): a directory junction to the executable directory's copy.
JUNCTION_DIRS: Tuple[str, ...] = (".tcc",)
# Read-only files the game locates cwd-first with an executable-directory
# fallback (port/app_paths.cpp LocateExistingFile, libultraship
# LocateFileAcrossAppDirs): absent from the worker dir on purpose, required
# in the executable dir. BattleShip.o2r is intentionally not linked: if an
# asset re-extraction were ever triggered it would write the cwd path, and a
# hard link would carry that write into the user's archive.
EXE_DIR_FALLBACK_FILES: Tuple[str, ...] = ("f3d.o2r", "BattleShip.o2r", "gamecontrollerdb.txt")
# port/first_run.cpp FindBaseRom(): the ROM candidates probed from a boot
# with cwd C and executable directory E are C, E, E/.. (and C again).
ROM_BASENAME = "baserom.us"
ROM_EXTENSIONS: Tuple[str, ...] = ("z64", "n64", "v64")
RUNTIME_MANIFEST = "runtime_manifest.json"


class RuntimePreparationError(RuntimeError):
    """A worker runtime directory cannot be prepared safely."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def replace_with_retry(src: os.PathLike | str, dst: os.PathLike | str, *, timeout: float = 10.0) -> None:
    """os.replace with a bounded retry: on Windows another process (virus scanner, indexer) may briefly hold
    the destination open without delete sharing, which makes os.replace fail with PermissionError."""
    deadline = time.monotonic() + timeout
    delay = 0.005
    while True:
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.1)


def portable_path(path: Optional[os.PathLike | str]) -> Optional[str]:
    """Repo-relative POSIX path when inside the repository, otherwise the absolute path."""
    if path is None:
        return None
    p = Path(path)
    try:
        return p.resolve().relative_to(REPO_ROOT).as_posix()
    except (ValueError, OSError):
        return str(p)


def file_fingerprint(path: Path) -> Dict[str, Any]:
    """Byte identity (sha256, size) plus mtime of one file; used for the user's configuration."""
    p = Path(path)
    if not p.exists():
        return {"path": portable_path(p), "exists": False}
    st = p.stat()
    return {"path": portable_path(p), "exists": True, "size": st.st_size, "sha256": sha256_file(p),
            "mtime_ns": st.st_mtime_ns}


def rom_candidates(runtime_dir: Path, executable: Path) -> List[Path]:
    exe_dir = Path(executable).resolve().parent
    bases = [Path(runtime_dir), exe_dir, exe_dir.parent]
    return [base / f"{ROM_BASENAME}.{ext}" for base in bases for ext in ROM_EXTENSIONS]


def _create_junction(target: Path, link: Path) -> str:
    if IS_WINDOWS:
        import _winapi  # CPython's own junction helper (used by its test suite); no shell, no mklink

        _winapi.CreateJunction(str(target), str(link))
        return "junction"
    os.symlink(str(target), str(link), target_is_directory=True)
    return "symlink"


def _is_link_like(path: Path) -> bool:
    isjunction = getattr(os.path, "isjunction", None)
    return path.is_symlink() or bool(isjunction and isjunction(path))


def prepare_worker_runtime(runtime_dir: Path, executable: Path) -> Dict[str, Any]:
    """Create one worker's private runtime directory. Refuses an existing directory.

    Contents: private byte copies of the mutable app-directory files that
    exist next to the executable, a junction per immutable cwd-only
    directory, nothing else. Returns the manifest (also written into the
    directory as runtime_manifest.json)."""
    runtime_dir = Path(runtime_dir)
    exe = Path(executable).resolve()
    exe_dir = exe.parent
    if not exe.is_file():
        raise RuntimePreparationError(f"executable not found: {exe}")
    for name in EXE_DIR_FALLBACK_FILES:
        if not (exe_dir / name).is_file():
            raise RuntimePreparationError(f"{name} missing next to the executable ({exe_dir}); the worker boot "
                                          "relies on the executable-directory fallback for it")
    found_roms = [str(p) for p in rom_candidates(runtime_dir, exe) if p.exists()]
    if found_roms:
        raise RuntimePreparationError(
            "a ROM is reachable from the worker boot path (port/first_run.cpp FindBaseRom); every worker would "
            f"re-extract assets into its private directory: {found_roms}")
    if runtime_dir.exists():
        raise RuntimePreparationError(f"worker runtime directory already exists: {runtime_dir}")
    runtime_dir.mkdir(parents=True)
    copies: List[Dict[str, Any]] = []
    for name in PRIVATE_COPY_FILES:
        src = exe_dir / name
        if not src.is_file():
            copies.append({"name": name, "source_exists": False})
            continue
        dst = runtime_dir / name
        shutil.copyfile(src, dst)  # content only; the source's attributes and timestamps are never touched
        copies.append({"name": name, "source_exists": True, "sha256": sha256_file(dst), "size": dst.stat().st_size,
                       "source_sha256": sha256_file(src)})
    links: List[Dict[str, Any]] = []
    for name in JUNCTION_DIRS:
        src = exe_dir / name
        if not src.is_dir():
            links.append({"name": name, "source_exists": False})
            continue
        kind = _create_junction(src, runtime_dir / name)
        links.append({"name": name, "kind": kind, "target": portable_path(src)})
    manifest = {
        "runtime_dir": portable_path(runtime_dir),
        "executable": portable_path(exe),
        "private_copies": copies,
        "links": links,
        "exe_dir_fallback_files": list(EXE_DIR_FALLBACK_FILES),
        "rom_candidates_checked": [portable_path(p) for p in rom_candidates(runtime_dir, exe)],
        "note": "cwd = runtime_dir; config/imgui/logs private; archives resolved from the executable directory",
    }
    with open(runtime_dir / RUNTIME_MANIFEST, "w", encoding="utf-8", newline="\n") as fp:
        json.dump(manifest, fp, indent=2)
        fp.write("\n")
    return manifest


def remove_worker_runtime(runtime_dir: Path) -> None:
    """Delete a runtime directory: links first (never their targets), then the private files."""
    runtime_dir = Path(runtime_dir)
    if not runtime_dir.exists():
        return
    for name in JUNCTION_DIRS:
        link = runtime_dir / name
        if _is_link_like(link):
            os.rmdir(link) if IS_WINDOWS else os.unlink(link)
    for child in runtime_dir.iterdir():
        if _is_link_like(child):
            raise RuntimePreparationError(f"unexpected link in {runtime_dir}: {child}; refusing to delete")
    shutil.rmtree(runtime_dir)


# Longest path M7 creates below a run or evaluation root, e.g.
# evaluations/t001024000_final/deterministic/workers/w00/episodes/episode_001_abcdefgh/battleship_stdout.log
M7_DEEPEST_SUFFIX = 112
WINDOWS_MAX_PATH = 259


def check_path_budget(root: Path, suffix: int = M7_DEEPEST_SUFFIX) -> None:
    """Fail early when the deepest M7 file below `root` would exceed the Windows MAX_PATH limit."""
    if not IS_WINDOWS:
        return
    length = len(str(Path(root).resolve())) + suffix
    if length > WINDOWS_MAX_PATH:
        raise RuntimePreparationError(
            f"run root {Path(root).resolve()} is too deep: M7 files below it reach ~{length} characters "
            f"(Windows MAX_PATH {WINDOWS_MAX_PATH}); use a shorter --runs-dir")


# -- loopback port blocks ---------------------------------------------------------------------------

PORT_BLOCK_BASE = 30000
PORT_BLOCK_SIZE = 250
PORT_BLOCK_MAX_RANKS = 32  # 30000..37999
DEFAULT_DYNAMIC_PORT_START = 49152


def dynamic_port_range() -> Dict[str, Any]:
    """The OS range used for outgoing (ephemeral) ports; best effort, with the IANA default as fallback."""
    try:
        if IS_WINDOWS:
            out = subprocess.run(["netsh", "int", "ipv4", "show", "dynamicport", "tcp"], capture_output=True,
                                 text=True, timeout=15, check=False).stdout
            start = re.search(r"Start Port\s*:\s*(\d+)", out)
            count = re.search(r"Number of Ports\s*:\s*(\d+)", out)
            if start and count:
                s, n = int(start.group(1)), int(count.group(1))
                return {"start": s, "end": s + n - 1, "source": "netsh"}
        else:
            with open("/proc/sys/net/ipv4/ip_local_port_range", encoding="utf-8") as fp:
                s, e = (int(v) for v in fp.read().split())
                return {"start": s, "end": e, "source": "/proc"}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return {"start": DEFAULT_DYNAMIC_PORT_START, "end": 65535, "source": "default"}


def port_block(rank: int, base: int = PORT_BLOCK_BASE, size: int = PORT_BLOCK_SIZE) -> range:
    if not 0 <= rank < PORT_BLOCK_MAX_RANKS:
        raise ValueError(f"rank {rank} outside 0..{PORT_BLOCK_MAX_RANKS - 1}")
    start = base + rank * size
    return range(start, start + size)


def validate_port_blocks(ranks: Sequence[int], base: int = PORT_BLOCK_BASE, size: int = PORT_BLOCK_SIZE) -> Dict[str, Any]:
    """Blocks must be disjoint, valid and entirely below the dynamic range (no ephemeral collision)."""
    dyn = dynamic_port_range()
    blocks = {int(r): port_block(int(r), base, size) for r in ranks}
    used: set = set()
    for r, blk in blocks.items():
        if blk.start < 1024 or blk.stop - 1 > 65535:
            raise ValueError(f"port block of rank {r} ({blk.start}..{blk.stop - 1}) is not a valid unprivileged range")
        if blk.stop - 1 >= dyn["start"] and blk.start <= dyn["end"]:
            raise ValueError(f"port block of rank {r} ({blk.start}..{blk.stop - 1}) overlaps the dynamic range "
                             f"{dyn['start']}..{dyn['end']}")
        if used.intersection(blk):
            raise ValueError(f"port block of rank {r} overlaps another rank")
        used.update(blk)
    return {"dynamic_range": dyn, "blocks": {r: [b.start, b.stop - 1] for r, b in blocks.items()}}


class PortExhausted(RuntimeError):
    pass


class PortCandidates:
    """One worker's candidate sequence inside its own block.

    Every claim() moves to a NEW candidate (a startup attempt never reuses the
    previous attempt's port) and returns the first one that passes M2's
    exclusive-bind probe. Ports held by a process that is still shutting down,
    by TIME_WAIT leftovers that block a bind, by OS exclusions or by an
    unrelated application are skipped and reported. The start offset is
    random per worker (Python RNG, host side only) so consecutive runs do
    not walk the same ports."""

    def __init__(self, rank: int, base: int = PORT_BLOCK_BASE, size: int = PORT_BLOCK_SIZE,
                 start_offset: Optional[int] = None, host: str = "127.0.0.1"):
        self.block = port_block(rank, base, size)
        self.host = host
        self._cursor = (random.SystemRandom().randrange(size) if start_offset is None else int(start_offset)) % size
        self.claims = 0

    def _next(self) -> int:
        port = self.block.start + self._cursor
        self._cursor = (self._cursor + 1) % len(self.block)
        return port

    def claim(self) -> Tuple[int, List[int]]:
        busy: List[int] = []
        for _ in range(len(self.block)):
            port = self._next()
            if loopback_port_is_free(port, self.host):
                self.claims += 1
                return port, busy
            busy.append(port)
        raise PortExhausted(f"no bindable port in {self.block.start}..{self.block.stop - 1}")


# -- processes ------------------------------------------------------------------------------------------

_STILL_ACTIVE = 259
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROCESS_TERMINATE = 0x0001
_SYNCHRONIZE = 0x00100000

if IS_WINDOWS:
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                ctypes.POINTER(wintypes.DWORD)]
    _k32.GetSystemTimes.argtypes = [ctypes.c_void_p] * 3
    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _k32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                               ctypes.POINTER(wintypes.DWORD)]
    _k32.GetCurrentProcess.restype = wintypes.HANDLE
    _k32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]


def pid_alive(pid: Optional[int]) -> bool:
    if pid is None:
        return False
    if IS_WINDOWS:
        handle = _k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not _k32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == _STILL_ACTIVE
        finally:
            _k32.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def process_image_name(pid: int) -> Optional[str]:
    if IS_WINDOWS:
        handle = _k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return None
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            if not _k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return None
            return Path(buf.value).name
        finally:
            _k32.CloseHandle(handle)
    try:
        return Path(os.readlink(f"/proc/{pid}/exe")).name
    except OSError:
        return None


def kill_pid(pid: int, expected_image: Optional[str] = None) -> bool:
    """Terminate a process; with expected_image, only if its image name still matches (pid reuse guard)."""
    if expected_image is not None and process_image_name(pid) != expected_image:
        return False
    if IS_WINDOWS:
        handle = _k32.OpenProcess(_PROCESS_TERMINATE | _SYNCHRONIZE, False, int(pid))
        if not handle:
            return False
        try:
            return bool(_k32.TerminateProcess(handle, 1))
        finally:
            _k32.CloseHandle(handle)
    try:
        os.kill(int(pid), 9)
        return True
    except OSError:
        return False


def list_processes_named(name: str = BATTLESHIP_IMAGE) -> Optional[List[int]]:
    """Machine-wide pids with this image name; None if the listing itself failed."""
    try:
        if IS_WINDOWS:
            out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
                                 capture_output=True, text=True, timeout=20, check=False).stdout
            pids = []
            for line in out.splitlines():
                cols = [c.strip('"') for c in line.split('","')]
                if len(cols) >= 2 and cols[0].strip('"') == name:
                    pids.append(int(cols[1]))
            return pids
        out = subprocess.run(["pgrep", "-x", name], capture_output=True, text=True, timeout=20, check=False).stdout
        return [int(v) for v in out.split()]
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def wait_until_no_process(name: str = BATTLESHIP_IMAGE, timeout: float = 15.0) -> List[int]:
    """Poll until no process with this image name exists (or the timeout); returns the survivors."""
    deadline = time.monotonic() + timeout
    while True:
        pids = list_processes_named(name) or []
        if not pids or time.monotonic() >= deadline:
            return pids
        time.sleep(0.25)


def system_cpu_times() -> Optional[Dict[str, float]]:
    """Machine-wide CPU seconds summed over all logical CPUs: busy and total (for utilisation deltas)."""
    try:
        if IS_WINDOWS:
            idle, kernel, user = (ctypes.c_uint64(), ctypes.c_uint64(), ctypes.c_uint64())
            if not _k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
                return None
            i, k, u = idle.value / 1e7, kernel.value / 1e7, user.value / 1e7
            total = k + u  # kernel time includes idle time on Windows
            return {"busy_s": total - i, "total_s": total}
        with open("/proc/stat", encoding="utf-8") as fp:
            parts = [float(v) for v in fp.readline().split()[1:]]
        clk = os.sysconf("SC_CLK_TCK")
        idle = (parts[3] + parts[4]) / clk
        total = sum(parts) / clk
        return {"busy_s": total - idle, "total_s": total}
    except (OSError, ValueError):
        return None


def cpu_utilisation(before: Optional[Dict[str, float]], after: Optional[Dict[str, float]]) -> Optional[float]:
    if not before or not after:
        return None
    total = after["total_s"] - before["total_s"]
    if total <= 0:
        return None
    return round((after["busy_s"] - before["busy_s"]) / total, 4)


# -- kill-on-close job object ----------------------------------------------------------------------------

if IS_WINDOWS:
    class _BasicLimit(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _IoCounters(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes",
                                                    "OtherBytes")]

    class _ExtendedLimit(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _BasicLimit), ("IoInfo", _IoCounters),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JobObjectBasicProcessIdList = 3
_JobObjectExtendedLimitInformation = 9


@dataclass
class KillOnCloseJob:
    """A job object holding the current process and everything it starts afterwards.

    The handle is held for the life of the process: when the process exits
    for any reason (normal exit, exception, Ctrl+C, TerminateProcess), the
    last handle closes and Windows kills every process still in the job.
    Nested jobs are supported from Windows 8 on (the shell may already run us
    inside one; verified in M7 Phase A)."""

    handle: Any = None
    active: bool = False
    reason: Optional[str] = None
    already_in_job: Optional[bool] = None
    notes: List[str] = field(default_factory=list)

    def pids(self) -> List[int]:
        if not (IS_WINDOWS and self.active):
            return []
        count = 1024

        class _List(ctypes.Structure):
            _fields_ = [("NumberOfAssignedProcesses", wintypes.DWORD), ("NumberOfProcessIdsInList", wintypes.DWORD),
                        ("ProcessIdList", ctypes.c_size_t * count)]

        buf = _List()
        if not _k32.QueryInformationJobObject(self.handle, _JobObjectBasicProcessIdList, ctypes.byref(buf),
                                              ctypes.sizeof(buf), None):
            return []
        return [int(buf.ProcessIdList[i]) for i in range(buf.NumberOfProcessIdsInList)]

    def describe(self) -> Dict[str, Any]:
        return {"active": self.active, "reason": self.reason, "already_in_job": self.already_in_job,
                "kill_on_job_close": self.active}


_JOB: Optional[KillOnCloseJob] = None


def install_kill_on_close_job() -> KillOnCloseJob:
    """Idempotent. Puts the current process into a new kill-on-close job (Windows only)."""
    global _JOB
    if _JOB is not None:
        return _JOB
    job = KillOnCloseJob()
    if not IS_WINDOWS:
        job.reason = "not Windows: no job object (children are reaped by the explicit cleanup only)"
        _JOB = job
        return job
    in_job = wintypes.BOOL()
    if _k32.IsProcessInJob(_k32.GetCurrentProcess(), None, ctypes.byref(in_job)):
        job.already_in_job = bool(in_job.value)
    handle = _k32.CreateJobObjectW(None, None)
    if not handle:
        job.reason = f"CreateJobObjectW failed ({ctypes.get_last_error()})"
        _JOB = job
        return job
    info = _ExtendedLimit()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not _k32.SetInformationJobObject(handle, _JobObjectExtendedLimitInformation, ctypes.byref(info),
                                        ctypes.sizeof(info)):
        job.reason = f"SetInformationJobObject failed ({ctypes.get_last_error()})"
        _k32.CloseHandle(handle)
        _JOB = job
        return job
    if not _k32.AssignProcessToJobObject(handle, _k32.GetCurrentProcess()):
        job.reason = f"AssignProcessToJobObject failed ({ctypes.get_last_error()})"
        _k32.CloseHandle(handle)
        _JOB = job
        return job
    job.handle = handle  # deliberately never closed: closing it is what kills the job
    job.active = True
    job.reason = "kill-on-close job installed"
    _JOB = job
    return job


def current_job() -> Optional[KillOnCloseJob]:
    return _JOB


# -- revisions ----------------------------------------------------------------------------------------------


def _git(args: Sequence[str], cwd: Path = REPO_ROOT) -> Optional[str]:
    try:
        r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=30, check=False)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def repository_revisions() -> Dict[str, Any]:
    """Parent HEAD, dirty file list, and each submodule's checked-out commit (best effort)."""
    head = (_git(["rev-parse", "HEAD"]) or "").strip() or None
    status = _git(["status", "--porcelain"])
    dirty = None if status is None else [line for line in status.splitlines() if line.strip()]
    subs: List[Dict[str, Any]] = []
    for line in (_git(["submodule", "status"]) or "").splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            sha = parts[0].lstrip("+-U")
            subs.append({"path": parts[1], "commit": sha, "describe": parts[2].strip("()") if len(parts) > 2 else None,
                         "differs_from_index": line.startswith("+")})
    return {"head": head, "dirty": None if dirty is None else bool(dirty), "dirty_files": dirty, "submodules": subs}
