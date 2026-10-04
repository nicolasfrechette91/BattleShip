"""M9-g1: the slot pools.

`SlotPool` = N spawned worker processes (rl/m9_worker.worker_main), one BattleShip slot each, driven over pipes. `LocalPool` = the same
`WorkerCore` command handlers in the calling process, executed synchronously, with a virtual clock charged per native tick: a run is then a
pure function of its configuration (the rd3/rd4 lesson: no suite test depends on process scheduling). Both expose

    send(slot, message)         (cmd, job) as rl/m9_worker documents
    poll(timeout) -> [(slot, kind, payload)]     kinds: ready staged stage_failed stepped step_failed closed report fatal died
    alive(slot), reports(), stop()

Light top-level imports only: spawned workers re-import the launching script.
"""
from __future__ import annotations

import multiprocessing
import os
import sys
import time
from multiprocessing.connection import wait as mp_wait
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

POOL_CONTRACT = "m9_pool_v1"
Event = Tuple[int, str, Dict[str, Any]]


class SlotPool:
    def __init__(self, n: int, spec_fn: Callable[[int], Dict[str, Any]], *, now: Callable[[], float] = time.monotonic, name: str = "m9"):
        import m9_worker as w

        self.n, self.now = int(n), now
        self.ctx = multiprocessing.get_context("spawn")
        self.abort = self.ctx.Event()
        self.procs: List[Any] = []
        self.conns: List[Any] = []
        self.infos: List[Dict[str, Any]] = [{} for _ in range(n)]
        self.dead: set = set()
        self._ready: set = set()
        self.name = name
        for rank in range(self.n):
            parent, child = self.ctx.Pipe(duplex=True)
            p = self.ctx.Process(target=w.worker_main, args=(child, spec_fn(rank), self.abort), name=f"{name}-w{rank:02d}", daemon=True)
            p.start()
            child.close()
            self.procs.append(p)
            self.conns.append(parent)

    def wait_ready(self, timeout: float = 240.0) -> None:
        deadline = self.now() + timeout
        pending = set(range(self.n))
        while pending:
            if self.now() > deadline:
                raise TimeoutError(f"workers {sorted(pending)} not ready after {timeout:.0f} s")
            for i in list(pending):
                if self.conns[i].poll(0.05):
                    kind, payload = self.conns[i].recv()
                    if kind != "ready":
                        raise RuntimeError(f"worker {i} failed to start: {payload}")
                    self.infos[i] = payload
                    pending.discard(i)
                elif not self.procs[i].is_alive():
                    raise RuntimeError(f"worker {i} died during start (exit code {self.procs[i].exitcode})")

    def alive(self, slot: int) -> bool:
        return slot not in self.dead and self.procs[slot].is_alive()

    def send(self, slot: int, message: Tuple[Any, ...]) -> None:
        self.conns[slot].send(message)

    def poll(self, timeout: float) -> List[Event]:
        out: List[Event] = []
        live = [self.conns[i] for i in range(self.n) if i not in self.dead]
        if live:
            for c in mp_wait(live, timeout=timeout):
                i = self.conns.index(c)
                try:
                    kind, payload = c.recv()
                except (EOFError, OSError):
                    self.dead.add(i)
                    out.append((i, "died", {"exit_code": self.procs[i].exitcode}))
                    continue
                payload = dict(payload)
                payload.setdefault("slot", i)
                out.append((i, kind, payload))
        else:
            time.sleep(min(timeout, 0.05))
        for i in range(self.n):
            if i in self.dead or self.procs[i].is_alive():
                continue
            try:
                pending = self.conns[i].poll()
            except (OSError, EOFError, BrokenPipeError):         # a worker that exited between wait() and this peek: a broken pipe is a death
                pending = False
            if not pending:
                self.dead.add(i)
                out.append((i, "died", {"exit_code": self.procs[i].exitcode}))
        return out

    def reports(self, timeout: float = 20.0) -> List[Dict[str, Any]]:
        """Reports of idle workers (best effort: a worker mid-command answers after it)."""
        out: List[Dict[str, Any]] = []
        for i, c in enumerate(self.conns):
            try:
                if i in self.dead or not self.procs[i].is_alive():
                    out.append({})
                    continue
                c.send(("report",))
                if c.poll(timeout):
                    kind, payload = c.recv()
                    out.append(payload if kind == "report" else {})
                else:
                    out.append({})
            except (OSError, EOFError, BrokenPipeError):
                out.append({})
        return out

    def stop(self, grace: float = 60.0) -> None:
        self.abort.set()
        for i, c in enumerate(self.conns):
            try:
                if self.procs[i].is_alive():
                    c.send(("stop",))
            except (OSError, BrokenPipeError):
                pass
        deadline = time.monotonic() + grace
        for p in self.procs:
            p.join(max(0.0, deadline - time.monotonic()))
        for p in self.procs:
            if p.is_alive():
                p.terminate()
                p.join(10)
        for c in self.conns:
            try:
                c.close()
            except OSError:
                pass


class VirtualClock:
    """A clock that advances only when charged (tests): `rate` native ticks per virtual second across the whole pool."""

    def __init__(self, rate: float = 1800.0, start: float = 1000.0):
        self.t = float(start)
        self.rate = float(rate)

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += float(seconds)

    def charge_ticks(self, ticks: float) -> None:
        self.t += float(ticks) / self.rate


class LocalPool:
    """The in-process lock-step pool: every send is executed immediately by that slot's WorkerCore; the replies are queued in send order."""

    def __init__(self, cores: Sequence[Any], clock: Optional[VirtualClock] = None):
        self.cores = list(cores)
        self.n = len(self.cores)
        self.clock = clock or VirtualClock()
        self.queue: List[Event] = []
        self.dead: set = set()
        self.abort = None
        self.infos: List[Dict[str, Any]] = [{"backend": "local"} for _ in range(self.n)]
        self.sent = 0

    def wait_ready(self, timeout: float = 0.0) -> None:
        return None

    def alive(self, slot: int) -> bool:
        return slot not in self.dead

    def send(self, slot: int, message: Tuple[Any, ...]) -> None:
        kind, payload = self.cores[slot].handle(message)
        payload = dict(payload)
        payload.setdefault("slot", slot)
        self.sent += 1
        ticks = {"staged": payload.get("ticks", 0), "stepped": 1}.get(kind, 0)
        if message[0] == "stage" and kind == "stage_failed":
            ticks = 0
        self.clock.charge_ticks(ticks)
        self.queue.append((slot, kind, payload))

    def poll(self, timeout: float) -> List[Event]:
        if not self.queue:
            self.clock.advance(timeout)            # nothing in flight: time passes (a stuck caller reaches its wall cap, never hangs)
            return []
        out, self.queue = self.queue, []
        return out

    def reports(self, timeout: float = 0.0) -> List[Dict[str, Any]]:
        return [dict(c.handle(("report",))[1]) for c in self.cores]

    def stop(self, grace: float = 0.0) -> None:
        for c in self.cores:
            c.shutdown()
