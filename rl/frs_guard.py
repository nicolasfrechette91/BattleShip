"""Fast-route lab (frs): the lab-root guard, the write / read audit hook, LF file writers and the one-workload lock (standard library only).

Lab mode writes ONLY under the lab root (default C:/BattleShip_lab) and, after the one-time import, never reads a registered tree:

    G1  validate_lab_root   the root is absolute and resolved; refused when it equals or lies inside the checkout, when any path component is
                            `runs` (any case), when it lies under (or contains) one of the D: evidence roots, or when it contains the checkout
    G2  LabGuard writes     every write-type audit event (write-mode open, mkdir, rename / replace, remove, rmdir, rmtree, copy, move, link,
                            symlink, truncate, utime, chmod, junction) on a path outside the lab root raises PermissionError (the write never
                            happens) and is recorded as a violation
    G3  LabGuard reads      open / listdir / scandir under <checkout>/runs, under the D: evidence roots, or of a path holding a provenance fragment
                            (the TAS, the fixtures, the human recordings) raise PermissionError and are recorded; only the import command reads
                            its explicit list of source files

The hook is installed in the main process, in every worker and therefore around every verification replay. An audit hook cannot be removed:
the tests run the hook in child processes. Design: logs/frs_prep/phase1_plan.md sections 1 and 7.
"""
from __future__ import annotations

import ctypes
import datetime as dt
import hashlib
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import m8_rd_worker as mw  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DEFAULT_LAB_ROOT = Path("C:/BattleShip_lab")
EVIDENCE_ROOTS = (Path("D:/BattleShip_runs_backup"), Path("D:/BattleShip_source_snapshots"), Path("D:/BattleShip_exe_archive"))
# m8_rd_worker.FORBIDDEN_FRAGMENTS (the fixtures, the captures, the TAS) plus the human recordings (audit C9); read, never edited
FORBIDDEN_FRAGMENTS = tuple(mw.FORBIDDEN_FRAGMENTS) + ("replay/recordings",)
WRITE_EVENTS_ONE = ("os.mkdir", "os.remove", "os.rmdir", "os.truncate", "os.utime", "os.chmod", "os.chown", "os.chflags", "shutil.rmtree")
WRITE_EVENTS_DST = ("os.rename", "shutil.copyfile", "shutil.copymode", "shutil.copystat", "shutil.copytree", "shutil.move", "os.link",
                    "os.symlink", "_winapi.CreateJunction")
READ_EVENTS = ("os.listdir", "os.scandir")


class LabRootError(RuntimeError):
    """The lab root (or a run folder) is refused by G1."""


# -- paths ------------------------------------------------------------------------------------------------------------------------------------


def _str(p: Any) -> Optional[str]:
    try:
        if isinstance(p, os.PathLike):
            p = os.fspath(p)
        if isinstance(p, bytes):
            p = p.decode("utf-8", "replace")
        if not isinstance(p, str) or not p:
            return None
        if p.startswith("\\\\?\\"):
            p = p[4:]
        return p
    except (TypeError, ValueError):
        return None


def norm(p: Any) -> Optional[str]:
    """Absolute, normalised, case-folded path string (no filesystem access)."""
    s = _str(p)
    return os.path.normcase(os.path.abspath(s)) if s is not None else None


def real(p: Any) -> Optional[str]:
    s = _str(p)
    try:
        return os.path.normcase(os.path.realpath(s)) if s is not None else None
    except (OSError, ValueError):
        return None


def under(child: Optional[str], parent: Optional[str]) -> bool:
    """`child` equals `parent` or lies inside it (both normalised)."""
    if not child or not parent:
        return False
    if child == parent:
        return True
    return child.startswith(parent.rstrip("\\/") + os.sep)


def forms(p: Any) -> List[str]:
    out = []
    for f in (norm(p), real(p)):
        if f and f not in out:
            out.append(f)
    return out


def has_runs_component(p: Any) -> bool:
    return any(part.lower() == "runs" for f in forms(p) for part in Path(f).parts)


def validate_lab_root(path: Any, repo: Path = REPO, evidence: Sequence[Path] = EVIDENCE_ROOTS) -> Path:
    """G1. Returns the absolute lab root; raises LabRootError with the reason."""
    s = _str(path)
    if s is None or not Path(s).is_absolute():
        raise LabRootError(f"refused: the lab root must be an absolute path, got {path!r}")
    lab = forms(s)
    rep = forms(repo)
    if len(Path(lab[0]).parts) <= 1:
        raise LabRootError(f"refused: the lab root {s} is a drive root")
    if has_runs_component(s):
        raise LabRootError(f"refused: the lab root {s} is under a folder named runs")
    for a in lab:
        for r in rep:
            if under(a, r):
                raise LabRootError(f"refused: the lab root {s} is inside the checkout {repo}")
            if under(r, a):
                raise LabRootError(f"refused: the lab root {s} contains the checkout {repo}")
        for e in evidence:
            for ef in forms(e):
                if under(a, ef) or under(ef, a):
                    raise LabRootError(f"refused: the lab root {s} overlaps the evidence root {e}")
    return Path(os.path.abspath(s))


def validate_run_dir(run_dir: Any, lab_root: Path) -> Path:
    s = _str(run_dir)
    if s is None or not Path(s).is_absolute():
        raise LabRootError(f"refused: the run folder must be an absolute path, got {run_dir!r}")
    if has_runs_component(s):
        raise LabRootError(f"refused: the run folder {s} is under a folder named runs")
    if not any(under(a, b) and a != b for a in forms(s) for b in forms(lab_root)):
        raise LabRootError(f"refused: the run folder {s} is not inside the lab root {lab_root}")
    return Path(os.path.abspath(s))


# -- the audit hook -----------------------------------------------------------------------------------------------------------------------------


class LabGuard:
    """G2 + G3 as one audit hook (class state: one guard per process)."""

    lab: List[str] = []
    banned_reads: List[str] = []
    allowed_reads: set = set()
    violations: List[str] = []
    installed = False
    _local = threading.local()
    _WRITE_FLAGS = getattr(os, "O_WRONLY", 1) | getattr(os, "O_RDWR", 2) | getattr(os, "O_CREAT", 0x100) | getattr(os, "O_TRUNC", 0x200) \
        | getattr(os, "O_APPEND", 8)

    @classmethod
    def install(cls, lab_root: Any, *, repo: Path = REPO, evidence: Sequence[Path] = EVIDENCE_ROOTS,
                allowed_reads: Iterable[Any] = ()) -> None:
        """Arm the guard. `allowed_reads` (the import command only) are exact files readable despite G3."""
        if cls.installed:
            raise RuntimeError("the lab guard is already installed in this process")
        cls.lab = forms(lab_root)
        cls.banned_reads = forms(Path(repo) / "runs") + [f for e in evidence for f in forms(e)]
        cls.allowed_reads = {f for p in allowed_reads for f in forms(p)}
        cls.installed = True
        sys.addaudithook(cls._hook)

    @classmethod
    def spec(cls) -> Dict[str, Any]:
        """What a spawned worker needs to arm the same guard."""
        return {"lab": list(cls.lab), "banned_reads": list(cls.banned_reads)}

    @classmethod
    def install_from_spec(cls, spec: Mapping[str, Any]) -> None:
        if cls.installed:
            return
        cls.lab = list(spec["lab"])
        cls.banned_reads = list(spec["banned_reads"])
        cls.allowed_reads = set()
        cls.installed = True
        sys.addaudithook(cls._hook)

    @staticmethod
    def is_null_device(p: Any) -> bool:
        """The OS null device (subprocess.DEVNULL opens it read-write for every process launch): not a file, in no folder."""
        s = _str(p)
        if s is None:
            return False
        s = s.replace("/", "\\").lower() if os.name == "nt" else s
        dev = os.devnull.lower() if os.name == "nt" else os.devnull
        return s in (dev, "\\\\.\\" + dev) if os.name == "nt" else s == dev

    @classmethod
    def inside_lab(cls, p: Any) -> bool:
        if cls.is_null_device(p):
            return True
        n = norm(p)
        if any(under(n, r) for r in cls.lab):
            return True
        r = real(p)
        return any(under(r, x) for x in cls.lab)

    @classmethod
    def read_banned(cls, p: Any) -> Optional[str]:
        n = norm(p)
        if n is None:
            return None
        if n in cls.allowed_reads:
            return None
        if any(under(n, b) for b in cls.banned_reads):
            return "registered tree"
        s = n.replace("\\", "/").lower()
        for frag in FORBIDDEN_FRAGMENTS:
            if frag in s:
                return f"provenance fragment {frag}"
        return None

    @classmethod
    def _refuse(cls, why: str) -> None:
        cls.violations.append(why[:400])
        raise PermissionError(f"frs lab guard: {why}")

    @classmethod
    def _hook(cls, event: str, args: Any) -> None:
        if getattr(cls._local, "busy", False):
            return
        cls._local.busy = True
        try:
            cls._check(event, args)
        finally:
            cls._local.busy = False

    @classmethod
    def _check(cls, event: str, args: Any) -> None:
        if not args:
            return
        if event == "open":
            p = args[0]
            if isinstance(p, int):
                return
            mode = args[1] if len(args) > 1 else None
            flags = args[2] if len(args) > 2 else 0
            write = (isinstance(mode, str) and any(c in mode for c in "wax+")) or \
                    (mode is None and isinstance(flags, int) and bool(flags & cls._WRITE_FLAGS))
            why = cls.read_banned(p)
            if why:
                cls._refuse(f"read refused ({why}): {_str(p)}")
            if write and not cls.inside_lab(p):
                cls._refuse(f"write refused (outside the lab root): open {_str(p)}")
            return
        if event in READ_EVENTS:
            why = cls.read_banned(args[0])
            if why:
                cls._refuse(f"read refused ({why}): {event} {_str(args[0])}")
            return
        if event in WRITE_EVENTS_ONE:
            if isinstance(args[0], int):
                return
            if not cls.inside_lab(args[0]):
                cls._refuse(f"write refused (outside the lab root): {event} {_str(args[0])}")
            return
        if event in WRITE_EVENTS_DST and len(args) >= 2:
            paths = [args[1]] + ([args[0]] if event in ("os.rename", "shutil.move") else [])
            for p in paths:
                if isinstance(p, int):
                    continue
                if not cls.inside_lab(p):
                    cls._refuse(f"write refused (outside the lab root): {event} {_str(p)}")


# -- LF writers that refuse paths outside the lab root ------------------------------------------------------------------------------------------


class LabFS:
    def __init__(self, lab_root: Path):
        self.root = Path(lab_root)
        self._forms = forms(self.root)

    def check(self, p: Path) -> Path:
        if not any(under(f, r) for f in forms(p) for r in self._forms):
            raise LabRootError(f"refused: {p} is outside the lab root {self.root}")
        return Path(p)

    def mkdir(self, p: Path) -> Path:
        self.check(p).mkdir(parents=True, exist_ok=True)
        return Path(p)

    def write_text(self, p: Path, text: str, *, atomic: bool = False) -> None:
        p = self.check(p)
        p.parent.mkdir(parents=True, exist_ok=True)
        if "\r" in text:
            text = text.replace("\r\n", "\n").replace("\r", "\n")
        if not atomic:
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            return
        tmp = p.with_name(p.name + ".tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)

    def write_json(self, p: Path, obj: Any, *, atomic: bool = True, indent: Optional[int] = 1) -> None:
        self.write_text(p, json.dumps(obj, indent=indent, default=str) + "\n", atomic=atomic)

    def append_jsonl(self, p: Path, row: Mapping[str, Any]) -> None:
        p = self.check(p)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")


# -- hashing ----------------------------------------------------------------------------------------------------------------------------------


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def tree_files(root: Path) -> List[Path]:
    return sorted(p for p in Path(root).rglob("*") if p.is_file())


def utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_compact() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# -- processes and the lock -----------------------------------------------------------------------------------------------------------------------


def pid_alive(pid: int) -> bool:
    """True when a process with this id is running. Never signals it (os.kill would terminate it on Windows)."""
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    k32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    h = k32.OpenProcess(0x1000, 0, int(pid))           # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = ctypes.c_ulong(0)
        if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
            return False
        return code.value == 259                          # STILL_ACTIVE
    finally:
        k32.CloseHandle(h)


class LabLock:
    """lab.lock in the lab root: one lab workload at a time. A lock whose process is gone is taken over and reported."""

    def __init__(self, lab_root: Path, what: str):
        self.path = Path(lab_root) / "lab.lock"
        self.what = what
        self.stale: Optional[Dict[str, Any]] = None
        self.held = False

    def acquire(self) -> None:
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    cur = json.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    cur = {"pid": -1}
                if pid_alive(int(cur.get("pid", -1))):
                    raise LabRootError(f"refused: another lab workload holds {self.path}: {cur}")
                self.stale = cur
                os.remove(self.path)
                continue
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps({"pid": os.getpid(), "utc": utc(), "what": self.what, "replaced_stale": self.stale}) + "\n")
            self.held = True
            return
        raise LabRootError(f"refused: cannot take {self.path}")

    def release(self) -> None:
        if not self.held:
            return
        try:
            cur = json.loads(self.path.read_text(encoding="utf-8"))
            if int(cur.get("pid", -1)) == os.getpid():
                os.remove(self.path)
        except (OSError, ValueError):
            pass
        self.held = False


# -- the guard self-test (self-check step 3): the hook runs in a child process; the parent checks and cleans up --------------------------------


def _selftest_child(lab_root: str, write_probe: str, read_probe: str, frag_probe: str) -> Dict[str, Any]:
    """Runs IN THE CHILD: arms the guard on the real checkout and the real evidence roots, then attempts each operation."""
    LabGuard.install(Path(lab_root))
    out: Dict[str, Any] = {}

    def attempt(name: str, fn: Any) -> None:
        try:
            fn()
            out[name] = "allowed"
        except PermissionError as exc:
            out[name] = "refused" if "frs lab guard" in str(exc) else f"PermissionError: {exc}"[:200]
        except OSError as exc:
            out[name] = type(exc).__name__

    lab_probe = Path(lab_root) / f"guard_probe_{os.getpid()}.tmp"
    attempt("write_inside_lab", lambda: open(lab_probe, "w").close())
    attempt("remove_inside_lab", lambda: os.remove(lab_probe))
    attempt("write_checkout", lambda: open(write_probe, "w").close())
    attempt("read_runs", lambda: open(read_probe, "rb").close())
    attempt("list_runs", lambda: os.listdir(Path(read_probe).parent))
    attempt("read_fragment", lambda: open(frag_probe, "rb").close())
    out["evidence_classified"] = {str(e): bool(LabGuard.read_banned(e / "probe")) and not LabGuard.inside_lab(e / "probe") for e in EVIDENCE_ROOTS}
    out["violations"] = len(LabGuard.violations)
    return out


def guard_selftest(lab_root: Path, repo: Path = REPO) -> Dict[str, Any]:
    """Self-check step 3 (run in the parent, unguarded): a child process arms the guard and attempts a write under the git-ignored logs/, a read
    and a listing of runs/ and a read of a provenance fragment; the parent then confirms that no probe file was created (and removes it if it was)."""
    import subprocess

    tag = f"{os.getpid()}_{utc_compact()}"
    write_probe = Path(repo) / "logs" / f"frs_guard_probe_{tag}.tmp"
    read_probe = Path(repo) / "runs" / f"frs_guard_probe_{tag}.json"
    frag_probe = Path(repo) / "replay" / "recordings" / f"frs_guard_probe_{tag}.json"
    r = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "selftest-child", str(lab_root), str(write_probe), str(read_probe),
                        str(frag_probe)], capture_output=True, text=True, cwd=str(lab_root), timeout=120)
    try:
        child = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        child = {"error": (r.stderr or r.stdout)[-600:]}
    created = write_probe.exists()
    if created:
        os.remove(write_probe)
    want = {"write_inside_lab": "allowed", "remove_inside_lab": "allowed", "write_checkout": "refused", "read_runs": "refused",
            "list_runs": "refused", "read_fragment": "refused"}
    ok = (all(child.get(k) == v for k, v in want.items()) and not created and all((child.get("evidence_classified") or {}).values())
          and len(child.get("evidence_classified") or {}) == len(EVIDENCE_ROOTS) and child.get("violations") == 4)
    return {"ok": bool(ok), "child": child, "write_probe_created": created, "expected": want}


if __name__ == "__main__":
    if len(sys.argv) == 6 and sys.argv[1] == "selftest-child":
        print(json.dumps(_selftest_child(*sys.argv[2:6])))
        sys.exit(0)
    print("usage: python -B rl/frs_guard.py selftest-child <lab_root> <write_probe> <read_probe> <fragment_probe>  (used by the self-check)")
    sys.exit(2)
