"""M8-rd2 worker: the `iterate2` job (pure additions to rd1's worker; rl/m8_rd_worker.py stays byte-identical).

`iterate2` IS rd1's `iterate` job: it runs `m8_rd_worker.run_iterate` unchanged, behind a recording proxy that sees every step reply
of the process and summarises the burst's ticks (never the prefix's) into the two diagnostic fields of decision 5:

    ground_runs      [[first tick, last tick], ...]   the exact runs of live ticks with ground_air_state == 0, tick = input_tick
    res_transitions  [[tick, from, to, x, y], ...]    every change of the resource class (G / A2 / A1 / A0 / X) of the live ticks;
                                                      the first burst tick compares with the class at the end of the prefix

Both are measured, never read by the selection, the explorer, the cell key or any check; the job's words, reaches, labels, ticks,
end reason and every integrity check are exactly those of `iterate` for the same job (tested: the two results are identical but for
the two new fields). Light top-level imports only: spawned workers re-import this module.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Mapping, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import m8_rd_cells as mcell  # noqa: E402
import m8_rd_worker as mw  # noqa: E402

WORKER2_CONTRACT = "m8_rd2_worker_v1"
JOB_KIND = "iterate2"


class WriteGuard:
    """An audit hook that records any write-type event whose path lies under a protected root (rd1's tree). A violation is appended to
    the provenance guard's list, so the existing per-result check stops the session as INVALID. Reads are never recorded. Installed in
    the session process and in every worker."""

    roots: List[str] = []
    _installed = False
    _WRITE_FLAGS = getattr(os, "O_WRONLY", 1) | getattr(os, "O_RDWR", 2) | getattr(os, "O_CREAT", 0x100) | getattr(os, "O_TRUNC", 0x200) | getattr(os, "O_APPEND", 8)

    @staticmethod
    def _norm(p: Any) -> Optional[str]:
        try:
            if isinstance(p, os.PathLike):
                p = os.fspath(p)
            if isinstance(p, bytes):
                p = p.decode("utf-8", "replace")
            if not isinstance(p, str):
                return None
            if p.startswith("\\\\?\\"):
                p = p[4:]               # the extended-length prefix
            return os.path.normcase(os.path.abspath(p))
        except (OSError, ValueError, TypeError):
            return None

    @classmethod
    def install(cls, roots: Any) -> None:
        for r in roots:
            n = cls._norm(r)
            if n and n not in cls.roots:
                cls.roots.append(n)
        if not cls._installed:
            cls._installed = True
            sys.addaudithook(cls._hook)

    @classmethod
    def clear(cls) -> None:
        cls.roots.clear()

    @classmethod
    def _under(cls, p: Any) -> bool:
        n = cls._norm(p)
        return bool(n) and any(n == r or n.startswith(r + os.sep) for r in cls.roots)

    @classmethod
    def _hook(cls, event: str, args: Any) -> None:
        if not cls.roots:
            return
        try:
            cls._check(event, args)
        except Exception:  # noqa: BLE001 - an audit hook must never raise into the audited call
            return

    @classmethod
    def _check(cls, event: str, args: Any) -> None:
        paths: List[Any] = []
        if event == "open" and args:
            mode = args[1] if len(args) > 1 else None
            flags = args[2] if len(args) > 2 else 0
            if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & cls._WRITE_FLAGS):
                paths = [args[0]]
        elif event in ("os.remove", "os.rmdir", "os.mkdir", "os.truncate", "os.utime", "os.chmod", "shutil.rmtree", "os.symlink", "os.link") and args:
            paths = [args[0]]
        elif event in ("os.rename", "shutil.move", "shutil.copyfile", "shutil.copy", "shutil.copy2", "shutil.copytree") and len(args) >= 2:
            paths = [args[1]] + ([args[0]] if event in ("os.rename", "shutil.move") else [])
        if any(cls._under(p) for p in paths):
            mw.ProvenanceGuard.violations.append(f"a write under a protected root (rd1's tree): {event} {paths[0]}")


class TickRecorder:
    """Per-tick summaries over the ticks after the prefix (tick j > L, j = the reply's input_tick)."""

    def __init__(self, prefix_len: int, clf: Any):
        self.L = int(prefix_len)
        self.clf = clf
        self.ground_runs: List[List[int]] = []
        self.res_transitions: List[List[Any]] = []
        self._run_start: Optional[int] = None
        self._run_end: Optional[int] = None
        self._prev: Optional[str] = None

    def note(self, rep: Mapping[str, Any]) -> None:
        try:
            self._note(rep)
        except (KeyError, TypeError, ValueError, AttributeError):
            return                      # a malformed reply is rd1's `bad_reply` mismatch, raised by its own check right after this one

    def _note(self, rep: Mapping[str, Any]) -> None:
        o = rep["observation"]
        j = int(o["input_tick"])
        live = mcell.is_live(o)
        cls: Optional[str] = None
        grounded = False
        if live:
            cls = mcell.resource_class(o, self.clf.name(int(o["fighter_status_id"])))
            grounded = int(o["ground_air_state"]) == 0
        if j > self.L:
            if grounded:
                if self._run_start is None:
                    self._run_start = j
                self._run_end = j
            elif self._run_start is not None:
                self.ground_runs.append([self._run_start, int(self._run_end or self._run_start)])
                self._run_start = None
            if cls is not None and self._prev is not None and cls != self._prev:
                self.res_transitions.append([j, self._prev, cls, float(o["position_x"]), float(o["position_y"])])
        if cls is not None:
            self._prev = cls

    def finish(self) -> None:
        if self._run_start is not None:
            self.ground_runs.append([self._run_start, int(self._run_end or self._run_start)])
            self._run_start = None


class RecordingProc:
    """A process proxy: every step reply is shown to the recorder before it is returned; everything else is delegated."""

    def __init__(self, proc: Any, rec: TickRecorder):
        object.__setattr__(self, "_proc", proc)
        object.__setattr__(self, "_rec", rec)

    def step(self, buttons: int, stick_x: int, stick_y: int) -> Dict[str, Any]:
        rep = self._proc.step(buttons, stick_x, stick_y)
        self._rec.note(rep)
        return rep

    def __getattr__(self, name: str) -> Any:
        return getattr(self._proc, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._proc, name, value)


class RecordingBackend:
    def __init__(self, backend: Any, rec: TickRecorder):
        self._backend = backend
        self._rec = rec

    def acquire(self, *args: Any, **kwargs: Any) -> RecordingProc:
        return RecordingProc(self._backend.acquire(*args, **kwargs), self._rec)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._backend, name)


def run_iterate2(ctx: mw.JobContext, job: Mapping[str, Any]) -> Dict[str, Any]:
    rec = TickRecorder(len(bytes(job["words"])), ctx.clf)
    ctx2 = mw.JobContext(RecordingBackend(ctx.backend, rec), ctx.abort, ctx.clf, ctx.rank, ctx.failure_dir)
    res = mw.run_iterate(ctx2, dict(job, kind="iterate"))
    rec.finish()
    res["ground_runs"] = rec.ground_runs
    res["res_transitions"] = rec.res_transitions
    res["worker_contract"] = WORKER2_CONTRACT
    return res


def register_jobs() -> None:
    """Add `iterate2` to the worker's job table (in the worker process only; the rd1 module's file is untouched)."""
    mw.JOBS[JOB_KIND] = run_iterate2


def worker_main2(conn: Any, spec: Mapping[str, Any], abort: Any) -> None:
    """Entry point of one spawned rd2 worker: rd1's `worker_main` with the `iterate2` job registered and the write guard installed."""
    register_jobs()
    if spec.get("protected_roots"):
        WriteGuard.install(spec["protected_roots"])
    mw.worker_main(conn, spec, abort)
