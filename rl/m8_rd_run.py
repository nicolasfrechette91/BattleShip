"""M8-rd run engine: S0 / P1 / arm T / arm C / verification / decision / S2 close for one bounded session.

Design: docs/rl_m8_rd_proposal_2026-10-01.md (revision 2) as amended by docs/rl_m8_rd_amendment_2026-10-02.md.
The engine is environment-injected (`RunEnv`) so the same code runs against the real game or a synthetic native stand-in.

Budget accounting (amendment 1). Each arm is capped at 3,000,000 native ticks (valid from 1,500,000). A job's tick allowance
is reserved at dispatch (cap - committed - reserved), so concurrent jobs can never overshoot; the job that gets a smaller
allowance is cut there (mid-prefix or mid-burst) and only the ticks within it count. Jobs are committed in completion order;
their cumulative position is the arm's cumulative tick count. A job aborted at a wall cap is not committed.

Light top-level imports only: spawned workers re-import the launching script.
"""
from __future__ import annotations

import json
import multiprocessing
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from multiprocessing.connection import wait as mp_wait
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import m8_rd_archive as march  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_claims as mclaims  # noqa: E402
import m8_rd_explore as mx  # noqa: E402
import m8_rd_rule as mrule  # noqa: E402
import m8_rd_worker as mw  # noqa: E402

RUN_CONTRACT = "m8_rd_run_v1"
JOB_TIMEOUT_S = 900.0
WALL_CAP_GRACE_S = 20.0
PROGRESS_EVERY_S = 30.0
SELFTEST_ARCHIVE_ID = "m8_rd_selftest"


class CapStop(Exception):
    """A tick, wall, memory or process cap stopped a phase: the result is INCOMPLETE (never a mismatch)."""


class IntegrityStop(Exception):
    """An integrity failure: the session is INVALID."""


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def write_json(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, default=str) + "\n", encoding="utf-8")
    march.replace_retry(tmp, path)


def append_jsonl(path: Path, row: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, default=str, separators=(",", ":")) + "\n")


# -- configuration and environment ---------------------------------------------------------------------------------------------


@dataclass
class RunConfig:
    root: Path                                   # <repo>/runs/m8_rd (or a test directory)
    session_id: str = "rd1"
    archive_id: str = "m8_rd_a1"
    n_workers: int = 5
    burst_words: int = mx.BURST_WORDS
    horizon: int = mcell.HORIZON
    arm_tick_cap: int = mclaims.ARM_TICK_CAP
    min_arm_ticks: int = mclaims.MIN_ARM_TICKS
    p1_tick_cap: int = 10_000
    replay_tick_cap: int = 400_000
    wall_caps_s: Mapping[str, float] = field(default_factory=lambda: {"p1": 180.0, "T": 1560.0, "C": 1440.0, "verify": 420.0})
    global_cap_s: float = 3600.0
    checkpoint_every_s: float = 300.0
    max_battleship_processes: int = 10
    lifecycle_failure_limit: int = mrule.MAX_LIFECYCLE_FAILURES
    process_check_every_s: float = 5.0
    unresponsive_after_stop_s: float = 90.0          # a busy worker this long after a stop is terminated (the job object reaps its games)
    verify_threads: int = 3
    identity_k: int = 16
    arm_caps: Mapping[str, int] = field(default_factory=dict)      # test hook only: a per-arm cap (production: both 3,000,000)
    memory_caps_mb: Mapping[str, float] = field(default_factory=lambda: {
        "main_private": 3072, "tree_private": 9216, "tree_working_set": 4096, "system_available_min": 1024,
        "system_commit_free_min": 2048})

    def arm_cap(self, arm: str) -> int:
        return int(self.arm_caps.get(arm, self.arm_tick_cap))

    @property
    def session_dir(self) -> Path:
        return self.root / "sessions" / self.session_id

    @property
    def archive_dir(self) -> Path:
        return self.root / "archive"


@dataclass
class RunEnv:
    """Everything that touches the game or the machine, injected."""

    worker_spec: Callable[[int, RunConfig], Dict[str, Any]]
    replay: Callable[[Mapping[str, Any], int, str, int], Dict[str, Any]]            # (candidate, counted words, label, thread slot)
    analyse: mclaims.Analyser
    p1_inputs: Callable[[], List[Dict[str, Any]]]
    pins: Mapping[str, Any]
    tree_snapshot: Optional[Callable[[], Optional[Dict[str, Any]]]] = None
    private_mb: Optional[Callable[[], Optional[float]]] = None
    now: Callable[[], float] = time.monotonic
    sampler: Any = None                           # a started TreeSampler (breach attribute), or None
    log: Callable[[str], None] = field(default=lambda s: print(f"[m8_rd {time.strftime('%H:%M:%S')}] {s}", flush=True))
    provenance_violations: Callable[[], List[str]] = field(default=lambda: list(mw.ProvenanceGuard.violations))


class Clock:
    """The session hard cap (from P1) and the per-phase wall caps; the tree sampler's memory breach and the main process's
    private memory also raise CapStop."""

    def __init__(self, env: RunEnv, cfg: RunConfig):
        self.env, self.cfg = env, cfg
        self.t0 = env.now()
        self.phase: Optional[str] = None
        self.phase_t0 = self.t0
        self.phase_wall: Dict[str, float] = {}
        self.peak_mb = 0.0
        self._n = 0

    def begin(self, phase: str) -> None:
        self.end()
        self.phase, self.phase_t0 = phase, self.env.now()
        self.check()

    def end(self) -> None:
        if self.phase is not None:
            self.phase_wall[self.phase] = round(self.phase_wall.get(self.phase, 0.0) + self.env.now() - self.phase_t0, 2)
            self.phase = None

    def elapsed(self) -> float:
        return self.env.now() - self.t0

    def phase_elapsed(self) -> float:
        return self.env.now() - self.phase_t0

    def global_check(self) -> None:
        if self.elapsed() > self.cfg.global_cap_s:
            raise CapStop(f"session hard cap reached ({self.elapsed():.0f} s > {self.cfg.global_cap_s:.0f} s) in phase {self.phase}")
        s = self.env.sampler
        if s is not None and getattr(s, "breach", None):
            raise CapStop(s.breach)
        self._n += 1
        if self.env.private_mb is not None and self._n % 64 == 0:
            mb = self.env.private_mb()
            if mb is not None:
                self.peak_mb = max(self.peak_mb, mb)
                if mb > self.cfg.memory_caps_mb["main_private"]:
                    raise CapStop(f"memory cap: main process private {mb:.0f} MB > {self.cfg.memory_caps_mb['main_private']} MB")

    def check(self) -> None:
        self.global_check()
        if self.phase is not None and self.phase_elapsed() > self.cfg.wall_caps_s[self.phase]:
            raise CapStop(f"wall cap of phase {self.phase} reached ({self.phase_elapsed():.0f} s > "
                          f"{self.cfg.wall_caps_s[self.phase]:.0f} s)")

    def to_json(self) -> Dict[str, Any]:
        return {"elapsed_s": round(self.elapsed(), 1), "phase_wall_s": dict(self.phase_wall),
                "caps_s": dict(self.cfg.wall_caps_s), "global_cap_s": self.cfg.global_cap_s,
                "peak_main_private_mb": round(self.peak_mb, 1)}


# -- the worker pool ---------------------------------------------------------------------------------------------------------


class WorkerPool:
    def __init__(self, env: RunEnv, cfg: RunConfig):
        self.env, self.cfg = env, cfg
        self.ctx = multiprocessing.get_context("spawn")
        self.abort = self.ctx.Event()
        self.procs: List[Any] = []
        self.conns: List[Any] = []
        self.infos: List[Dict[str, Any]] = []
        self.busy: Dict[int, Tuple[Dict[str, Any], float]] = {}        # worker -> (job, sent at)
        self.retired: set = set()

    def start(self, n: int, timeout: float = 180.0) -> None:
        for rank in range(n):
            parent, child = self.ctx.Pipe(duplex=True)
            spec = self.env.worker_spec(rank, self.cfg)
            p = self.ctx.Process(target=mw.worker_main, args=(child, spec, self.abort), name=f"m8rd-w{rank:02d}", daemon=True)
            p.start()
            child.close()
            self.procs.append(p)
            self.conns.append(parent)
        deadline = self.env.now() + timeout
        pending = set(range(n))
        self.infos = [{} for _ in range(n)]
        while pending:
            if self.env.now() > deadline:
                raise CapStop(f"workers {sorted(pending)} not ready after {timeout:.0f} s")
            for i in list(pending):
                if self.conns[i].poll(0.1):
                    kind, payload = self.conns[i].recv()
                    if kind != "ready":
                        raise CapStop(f"worker {i} failed to start: {payload}")
                    self.infos[i] = payload
                    pending.discard(i)
                elif not self.procs[i].is_alive():
                    raise CapStop(f"worker {i} died during start (exit code {self.procs[i].exitcode})")

    def idle(self) -> List[int]:
        return [i for i in range(len(self.procs)) if i not in self.busy and i not in self.retired and self.procs[i].is_alive()]

    def send(self, i: int, job: Dict[str, Any]) -> None:
        self.conns[i].send(("job", job))
        self.busy[i] = (job, self.env.now())

    def poll(self, timeout: float) -> List[Tuple[int, str, Dict[str, Any]]]:
        """Completed jobs: [(worker, kind, payload)]; a dead worker with a job in flight is reported as kind 'died'."""
        out: List[Tuple[int, str, Dict[str, Any]]] = []
        conns = [self.conns[i] for i in self.busy]
        if conns:
            for c in mp_wait(conns, timeout=timeout):
                i = self.conns.index(c)
                try:
                    kind, payload = c.recv()
                except (EOFError, OSError):
                    out.append((i, "died", {"exit_code": self.procs[i].exitcode}))
                    self.busy.pop(i, None)
                    continue
                self.busy.pop(i, None)
                out.append((i, kind, payload))
        else:
            time.sleep(min(timeout, 0.05))
        for i in list(self.busy):
            if not self.procs[i].is_alive() and not self.conns[i].poll():
                out.append((i, "died", {"exit_code": self.procs[i].exitcode}))
                self.busy.pop(i, None)
        return out

    def retire(self, indices: Sequence[int], grace: float = 60.0) -> None:
        """Stop some workers (their standby processes close with them) to free BattleShip processes for the verification."""
        for i in indices:
            if i in self.retired or i in self.busy:
                continue
            try:
                self.conns[i].send(("stop",))
            except (OSError, BrokenPipeError):
                pass
            self.retired.add(i)
        deadline = time.monotonic() + grace
        for i in indices:
            self.procs[i].join(max(0.0, deadline - time.monotonic()))
            if self.procs[i].is_alive():
                self.procs[i].terminate()
                self.procs[i].join(10)

    def kill_busy(self) -> List[int]:
        """Terminate the workers that are still busy (after a stop that they did not honour). Returns their indices."""
        out = []
        for i in list(self.busy):
            try:
                self.procs[i].terminate()
            except OSError:
                pass
            self.retired.add(i)
            self.busy.pop(i, None)
            out.append(i)
        return out

    def oldest_age(self) -> float:
        now = self.env.now()
        return max((now - t for _j, t in self.busy.values()), default=0.0)

    def stop(self, grace: float = 60.0) -> None:
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

    def reports(self, timeout: float = 20.0) -> List[Dict[str, Any]]:
        out = []
        for i, c in enumerate(self.conns):
            try:
                if i in self.busy or not self.procs[i].is_alive():
                    out.append({})
                    continue
                c.send(("report",))
                out.append(c.recv()[1] if c.poll(timeout) else {})
            except (OSError, EOFError, BrokenPipeError):
                out.append({})
        return out


# -- the session ---------------------------------------------------------------------------------------------------------------


class Session:
    def __init__(self, cfg: RunConfig, env: RunEnv):
        self.cfg, self.env = cfg, env
        self.log = env.log
        self.clock = Clock(env, cfg)
        self.pool = WorkerPool(env, cfg)
        self.dir = cfg.session_dir
        self.invalid: List[str] = []
        self.incomplete: List[str] = []
        self.state: Dict[str, Any] = {"contract": RUN_CONTRACT, "session": cfg.session_id, "phase": "init", "started_utc": utc()}
        self.pin: Optional[Dict[str, Any]] = None             # the pinned tick-0 record
        self.archive: Optional[march.Archive] = None
        self.ledgers = {"T": mclaims.ArmLedger("T"), "C": mclaims.ArmLedger("C")}
        self.coverage = march.CoverageSet()
        self.arm_records: Dict[str, Dict[str, Any]] = {}
        self.ticks = {"p1": 0, "T": 0, "C": 0, "replays": 0}
        self.iteration = 0
        self.episode = 0
        self.ckpt_seq = 0
        self.lifecycle_failures = {"T": 0, "C": 0, "p1": 0}
        self.reaches_seen = 0
        self.rows_dir = self.dir
        self.vel_reversals = {"count": 0, "examples": []}
        self.p1_record: Dict[str, Any] = {}
        self.pool_job: Dict[int, Dict[str, Any]] = {}
        self.tick_lock = threading.Lock()

    # -- bookkeeping -------------------------------------------------------------------------------------------------------------

    def save_state(self, **extra: Any) -> None:
        self.state.update(extra, clock=self.clock.to_json(), ticks=dict(self.ticks), utc=utc(),
                          invalid=list(self.invalid), incomplete=list(self.incomplete),
                          lifecycle_failures=dict(self.lifecycle_failures))
        write_json(self.dir / "state.json", self.state)

    def stop_invalid(self, why: str) -> None:
        self.invalid.append(why)
        self.log(f"INVALID: {why}")

    def check_provenance(self, res: Mapping[str, Any]) -> None:
        v = list(res.get("provenance_violations") or []) + self.env.provenance_violations()
        if v:
            raise IntegrityStop(f"provenance violation: a fixture / capture / TAS path was opened: {sorted(set(v))[:3]}")

    # -- P1: identity --------------------------------------------------------------------------------------------------------------

    def run_batch(self, jobs: Sequence[Dict[str, Any]], phase: str, tick_phase: str, cap_ticks: int
                  ) -> List[Dict[str, Any]]:
        """Run jobs on the idle workers (dynamic assignment), return results in job order. Any non-ok result is returned as is;
        the caller decides what it means. Tick use is checked against the cap BEFORE a job is sent."""
        results: List[Optional[Dict[str, Any]]] = [None] * len(jobs)
        queue = list(range(len(jobs)))
        assigned: Dict[int, int] = {}
        while queue or self.pool.busy:
            self.clock.check()
            for w in self.pool.idle():
                if not queue:
                    break
                k = queue.pop(0)
                need = int(jobs[k].get("allowance", len(jobs[k].get("words") or b"") or 0))
                with self.tick_lock:
                    if self.ticks[tick_phase] + need > cap_ticks:
                        raise CapStop(f"native-tick cap of {tick_phase}: {self.ticks[tick_phase]} + {need} > {cap_ticks}")
                    self.ticks[tick_phase] += need
                assigned[w] = k
                self.pool.send(w, dict(jobs[k]))
            for w, kind, payload in self.pool.poll(0.25):
                k = assigned.pop(w)
                if kind == "died":
                    raise CapStop(f"worker {w} died: {payload}")
                if kind == "fatal":
                    raise CapStop(f"worker {w}: {payload}")
                results[k] = payload
                self.check_provenance(payload)
                used = int(payload.get("ticks", 0)) if payload.get("ok") else 0
                need = int(jobs[k].get("allowance", len(jobs[k].get("words") or b"") or 0))
                with self.tick_lock:
                    self.ticks[tick_phase] += used - need     # replace the reservation by the real use
            if self.pool.oldest_age() > JOB_TIMEOUT_S:
                self.pool.abort.set()
                raise CapStop(f"a job has been in flight for more than {JOB_TIMEOUT_S:.0f} s")
        return [r for r in results if r is not None]

    def p1(self) -> None:
        cfg = self.cfg
        self.clock.begin("p1")
        self.state["phase"] = "p1"
        rec: Dict[str, Any] = {"started_utc": utc()}
        # 1. tick-0 record: pinned from one process, reproduced by a second (the standby-promoted one)
        first = self.run_batch([{"kind": "tick0", "pin": None}], "p1", "p1", cfg.p1_tick_cap)[0]
        if not first.get("ok"):
            raise self._p1_failure("tick0 pin", first)
        pin = {"obs": list(first["obs"]), "digest": first["digest"], "chain": first["chain"], "lines": first["lines"],
               "key": first["key"], "mask": first["mask"]}
        second = self.run_batch([{"kind": "tick0", "pin": pin}], "p1", "p1", cfg.p1_tick_cap)[0]
        if not second.get("ok"):
            raise self._p1_failure("tick0 reproduction", second)
        self.pin = pin
        rec["tick0"] = {"digest": pin["digest"], "lines_digest": pin["lines"], "modes": [first["mode"], second["mode"]],
                        "host_frames": [first["tick0"]["host_frame"], second["tick0"]["host_frame"]],
                        "host_frame_equal": second["tick0"].get("host_frame_equal")}
        self.log(f"P1 tick-0 record pinned {pin['digest'][:12]} (modes {rec['tick0']['modes']})")
        # 2. the pinned Track 1 traces, word for word
        traces = self.env.p1_inputs()
        jobs = [{"kind": "trace", "name": t["name"], "words": t["words"], "expected_digests": t["expected_digests"],
                 "expected_host_frames": t.get("expected_host_frames"), "pin": pin, "allowance": len(t["words"])}
                for t in traces]
        # 3. the return self-test in a scratch archive
        selftest = self.selftest_prepare()
        results = self.run_batch(jobs + selftest["burst_jobs"], "p1", "p1", cfg.p1_tick_cap)
        trace_res = results[:len(traces)]
        for t, r in zip(traces, trace_res):
            if not r.get("ok"):
                raise self._p1_failure(f"trace {t['name']}", r)
            if r["native_action_digest"] != t["native_action_digest"]:
                raise IntegrityStop(f"P1 trace {t['name']}: native action digest {r['native_action_digest'][:12]} differs from "
                                    f"the pinned {t['native_action_digest'][:12]}")
        rec["traces"] = [{"name": r["name"], "words": r["words"], "native_action_digest": r["native_action_digest"],
                          "host_frames_equal": r["host_frames_equal"], "end_reason": r["end_reason"], "mode": r["mode"]}
                         for r in trace_res]
        burst = results[len(traces)]
        if not burst.get("ok"):
            raise self._p1_failure("self-test burst", burst)
        rec["selftest"] = self.selftest_returns(burst, selftest)
        rec["ticks"] = self.ticks["p1"]
        rec["finished_utc"] = utc()
        self.p1_record = rec
        write_json(self.dir / "p1.json", rec)
        self.save_state(p1="PASS")
        self.log(f"P1 passed: {self.ticks['p1']} native ticks")

    def _p1_failure(self, what: str, res: Mapping[str, Any]) -> Exception:
        if res.get("kind") == "mismatch":
            return IntegrityStop(f"P1 {what}: {res.get('mismatch')} {json.dumps(res.get('detail'), default=str)[:400]}")
        if res.get("kind") == "aborted":
            return CapStop(f"P1 {what} aborted")
        self.lifecycle_failures["p1"] += 1
        return CapStop(f"P1 {what}: {res.get('kind')} {res.get('outcome') or res.get('error')} {res.get('message') or ''}"[:400])

    def selftest_prepare(self) -> Dict[str, Any]:
        assert self.pin is not None
        a = march.Archive(SELFTEST_ARCHIVE_ID)
        key = tuple(self.pin["key"])
        a.init_cell0(key, self.pin["obs"], bytes.fromhex(self.pin["digest"]), bytes.fromhex(self.pin["chain"]))
        c0 = a.dispatch(0, 0)
        job = {"kind": "iterate", "arm": "P1", "iteration": 0, "cell": c0.id, "rep": (c0.burst, c0.offset), "words": b"",
               "end": c0.end, "end_digest": c0.end_digest, "chain": c0.chain, "pin": self.pin,
               "archive_id": SELFTEST_ARCHIVE_ID, "burst_words": self.cfg.burst_words, "allowance": self.cfg.burst_words}
        return {"archive": a, "burst_jobs": [job]}

    def selftest_returns(self, burst: Mapping[str, Any], st: Mapping[str, Any]) -> Dict[str, Any]:
        a: march.Archive = st["archive"]
        res = dict(burst, cum_before=0, session=self.cfg.session_id)
        info = a.ingest(res)
        cells = [c for c in a.cells if c.id != 0 and c.L >= 8 and not c.terminal]
        if len(cells) < 3:
            cells = [c for c in a.cells if c.id != 0 and not c.terminal]
        if len(cells) < 3:
            raise CapStop(f"P1 self-test: the keyed burst produced only {len(cells)} usable cells")
        cells.sort(key=lambda c: (c.L, c.id))
        picks = [cells[0], cells[len(cells) // 2], cells[-1]]
        jobs = []
        for n, c in enumerate(picks, 1):
            jobs.append({"kind": "iterate", "arm": "P1", "iteration": n, "cell": c.id, "rep": (c.burst, c.offset),
                         "words": a.cell_words(c), "end": c.end, "end_digest": c.end_digest, "chain": c.chain, "pin": self.pin,
                         "archive_id": SELFTEST_ARCHIVE_ID, "burst_words": 0, "allowance": c.L})
        bad = picks[1]
        corrupted = list(bad.end)
        corrupted[mcell.I_X] = float(corrupted[mcell.I_X]) + 1.0
        jobs.append({"kind": "iterate", "arm": "P1", "iteration": 4, "cell": bad.id, "rep": (bad.burst, bad.offset),
                     "words": a.cell_words(bad), "end": tuple(corrupted), "end_digest": bad.end_digest, "chain": bad.chain,
                     "pin": self.pin, "archive_id": SELFTEST_ARCHIVE_ID, "burst_words": 0, "allowance": bad.L})
        out = self.run_batch(jobs, "p1", "p1", self.cfg.p1_tick_cap)
        for r, c in zip(out[:3], picks):
            if not r.get("ok"):
                raise self._p1_failure(f"self-test return of cell {c.id}", r)
            if not (r["prefix"].get("end_equal") and r["prefix"].get("chain_equal")):
                raise IntegrityStop(f"P1 self-test: return of cell {c.id} did not verify")
        refused = out[3]
        if refused.get("ok") or refused.get("kind") != "mismatch" or refused.get("mismatch") != "prefix_end":
            raise IntegrityStop(f"P1 self-test: a corrupted end record was NOT refused: {json.dumps(refused, default=str)[:300]}")
        return {"cells_from_burst": info["new"], "returned": [{"cell": c.id, "L": c.L, "key": list(c.key)} for c in picks],
                "corrupted_refused": True, "refusal": refused["mismatch"], "refusal_fields": sorted(
                    (refused.get("detail") or {}).get("field_diffs", {}))}

    # -- arms ----------------------------------------------------------------------------------------------------------------------

    def init_archive(self) -> None:
        assert self.pin is not None
        a = march.Archive(self.cfg.archive_id)
        a.init_cell0(tuple(self.pin["key"]), self.pin["obs"], bytes.fromhex(self.pin["digest"]), bytes.fromhex(self.pin["chain"]))
        self.archive = a

    def checkpoint(self, why: str) -> None:
        assert self.archive is not None
        self.ckpt_seq += 1
        meta = {"checkpoint_seq": self.ckpt_seq, "why": why, "utc": utc(), "session": self.cfg.session_id,
                "pins": dict(self.env.pins), "horizon": self.cfg.horizon, "burst_words": self.cfg.burst_words,
                "ticks": dict(self.ticks), "ledger_T": {"ticks": self.ledgers["T"].ticks, "jobs": self.ledgers["T"].jobs},
                "velocity_reversals": dict(self.vel_reversals), "pin_tick0": self.pin}
        march.save_checkpoint(self.cfg.archive_dir, self.archive, meta)

    def run_arm(self, arm: str) -> Dict[str, Any]:
        assert self.pin is not None
        cfg = self.cfg
        arm_phase = arm
        ledger = self.ledgers[arm]
        cap = cfg.arm_cap(arm)
        self.clock.begin(arm_phase)
        self.state["phase"] = f"arm_{arm}"
        t0 = self.env.now()
        reserved: Dict[int, int] = {}
        stop: Optional[Tuple[str, str]] = None
        stop_at = None
        rows_path = self.dir / f"iterations_{arm}.jsonl"
        last_progress = last_ckpt = t0
        aborted = discarded = 0
        modes: Dict[str, int] = {}
        prefix_ticks = 0
        first_minutes: List[Tuple[float, int]] = []
        last_snap = 0.0
        over_count, over_seq, snap_n = 0, None, 0
        while True:
            now = self.env.now()
            try:
                # the session cap and the job timeout are checked even after a stop; the arm's wall cap and the process
                # count only while the arm still runs
                self.clock.global_check()
                if self.pool.oldest_age() > JOB_TIMEOUT_S:
                    raise CapStop(f"a job has been in flight for more than {JOB_TIMEOUT_S:.0f} s")
                if stop is None:
                    if now - t0 > cfg.wall_caps_s[arm]:
                        raise CapStop(f"wall cap of arm {arm} reached ({now - t0:.0f} s)")
                    if self.env.tree_snapshot is not None and now - last_snap >= cfg.process_check_every_s:
                        last_snap = now
                        snap = self.env.tree_snapshot()
                        if snap is not None and snap.get("battleship", 0) > cfg.max_battleship_processes:
                            snap_n += 1
                            seq = snap.get("seq", snap_n)
                            if seq != over_seq:                 # two DISTINCT samples above the cap (a transient is not a stop)
                                over_seq = seq
                                over_count += 1
                            if over_count >= 2:
                                raise CapStop(f"{snap['battleship']} BattleShip processes > {cfg.max_battleship_processes}")
                        else:
                            over_count = 0
            except CapStop as exc:
                kind = "wall_cap" if str(exc).startswith("wall cap of arm") else "cap"
                if stop is None or (kind == "cap" and stop[0] == "wall_cap"):
                    stop = (kind, str(exc))
                    stop_at = now
                    if kind == "cap":
                        self.incomplete.append(str(exc))
                    self.log(f"arm {arm}: stop requested: {exc}")
            if stop is not None and stop_at is not None and self.pool.busy and now - stop_at > cfg.unresponsive_after_stop_s:
                dead = self.pool.kill_busy()
                reserved.clear()
                self.incomplete.append(f"workers {dead} did not return {cfg.unresponsive_after_stop_s:.0f} s after the stop and were terminated")
                self.log(f"arm {arm}: terminated unresponsive workers {dead}")
            if stop is not None:
                grace = WALL_CAP_GRACE_S if stop[0] == "wall_cap" else 0.0
                if now - (stop_at or now) >= grace and not self.pool.abort.is_set():
                    self.pool.abort.set()
            committed = ledger.ticks
            if stop is None and not self.pool.busy and not self.pool.idle():
                stop = ("cap", "no live worker is left")
                stop_at = now
                self.incomplete.append(stop[1])
                self.log(f"arm {arm}: {stop[1]}")
            if stop is None:
                for w in self.pool.idle():
                    remaining = cap - committed - sum(reserved.values())
                    if remaining <= 0:
                        break
                    job = self.make_job(arm, w, remaining)
                    reserved[w] = int(job["allowance"])
                    self.pool.send(w, job)
            if not self.pool.busy and (stop is not None or cap - ledger.ticks - sum(reserved.values()) <= 0):
                break
            for w, kind, payload in self.pool.poll(0.25):
                job = self.pool_job.pop(w, None)
                reserved.pop(w, None)
                if kind in ("died", "fatal"):
                    stop = stop or ("cap", f"worker {w} {kind}: {payload}")
                    stop_at = stop_at or now
                    self.pool.abort.set()
                    self.incomplete.append(f"worker {w} {kind}: {str(payload)[:200]}")
                    continue
                try:
                    self.check_provenance(payload)
                except IntegrityStop as exc:
                    self.stop_invalid(str(exc))
                    stop = stop or ("invalid", str(exc))
                    stop_at = stop_at or now
                    self.pool.abort.set()
                    continue
                if payload.get("ok"):
                    self.commit(arm, job, payload, rows_path)
                    modes[payload["mode"]] = modes.get(payload["mode"], 0) + 1
                    prefix_ticks += int(payload.get("L", 0)) if arm == "T" and not payload["prefix"].get("cut") else 0
                    if len(first_minutes) < 6 and now - t0 >= 60 * (len(first_minutes) + 1):
                        first_minutes.append((round(now - t0, 1), ledger.ticks))
                    continue
                k = payload.get("kind")
                if k == "mismatch":
                    why = f"arm {arm} iteration {payload.get('iteration')}: {payload.get('mismatch')} {json.dumps(payload.get('detail'), default=str)[:500]}"
                    self.stop_invalid(why)
                    stop = stop or ("invalid", why)
                    stop_at = stop_at or now
                    self.pool.abort.set()
                elif k == "lifecycle":
                    self.lifecycle_failures[arm] += 1
                    if self.archive is not None and arm == "T":
                        self.archive.note_failure(payload.get("iteration", -1), f"{payload.get('outcome')}: {payload.get('message')}")
                    append_jsonl(rows_path, {"event": "lifecycle_failure", "arm": arm, "worker": w,
                                             "iteration": payload.get("iteration"), "outcome": payload.get("outcome"),
                                             "message": str(payload.get("message"))[:300]})
                    self.log(f"arm {arm}: lifecycle failure {payload.get('outcome')} (worker {w}); redrawing")
                    if self.lifecycle_failures[arm] > cfg.lifecycle_failure_limit:
                        why = f"more than {cfg.lifecycle_failure_limit} lifecycle failures in arm {arm}"
                        self.incomplete.append(why)
                        stop = stop or ("lifecycle", why)
                        stop_at = stop_at or now
                        self.pool.abort.set()
                elif k == "aborted":
                    aborted += 1
                    discarded += 1
                else:
                    why = f"arm {arm}: worker error {str(payload.get('error'))[:300]}"
                    self.incomplete.append(why)
                    self.log(why + "\n" + str(payload.get("trace", ""))[-800:])
                    stop = stop or ("error", why)
                    stop_at = stop_at or now
                    self.pool.abort.set()
            now = self.env.now()
            if arm == "T" and now - last_ckpt >= cfg.checkpoint_every_s:
                try:
                    self.checkpoint("periodic")
                except OSError as exc:                              # a locked file is retried; the next interval tries again
                    self.log(f"periodic checkpoint failed ({type(exc).__name__}: {exc}); will retry")
                last_ckpt = now
            if now - last_progress >= PROGRESS_EVERY_S:
                last_progress = now
                cells = len(self.archive.cells) if (arm == "T" and self.archive) else len(self.coverage.keys)
                self.log(f"arm {arm}: {ledger.ticks:,} ticks ({ledger.ticks / max(1e-9, now - t0):,.0f}/s) jobs {ledger.jobs} "
                         f"cells {cells} in flight {len(self.pool.busy)} max_t {ledger.max_t_online} "
                         f"elapsed {now - t0:.0f}s phase cap {cfg.wall_caps_s[arm]:.0f}s")
                try:
                    self.save_state()
                except OSError as exc:
                    self.log(f"state save failed ({type(exc).__name__}: {exc})")
        self.pool.abort.clear()
        wall = self.env.now() - t0
        if arm == "T":
            self.checkpoint("arm_end")
        rec = {"arm": arm, "ticks": ledger.ticks, "jobs": ledger.jobs, "cut_jobs": ledger.cut_jobs, "wall_s": round(wall, 2),
               "stop": list(stop) if stop else ["budget", f"{ledger.ticks:,} ticks"], "aborted_jobs": aborted,
               "lifecycle_failures": self.lifecycle_failures[arm], "ticks_per_s": round(ledger.ticks / max(1e-9, wall), 1),
               "start_modes": modes, "prefix_ticks": prefix_ticks, "rate_by_minute": first_minutes,
               "reached_budget": ledger.ticks >= cap, "max_t_online": ledger.max_t_online,
               "candidates": len(ledger.candidates)}
        self.arm_records[arm] = rec
        write_json(self.dir / f"arm_{arm}.json", rec)
        self.save_arm_artifacts(arm)
        self.log(f"arm {arm} done: {ledger.ticks:,} ticks in {wall:.0f} s, stop {rec['stop']}")
        return rec

    def save_arm_artifacts(self, arm: str) -> None:
        """The arm's committed-job log, candidate registry (words included, gzip) and, for arm C, its coverage cells: enough to
        recompute every within-T reading offline."""
        import gzip

        led = self.ledgers[arm]
        write_json(self.dir / f"ledger_{arm}.json", {"arm": arm, "ticks": led.ticks, "jobs": led.jobs, "cut_jobs": led.cut_jobs,
                                                     "job_log": led.job_log, "t_records": {str(t): v for t, v in led.t_records.items()},
                                                     "l0_cid": led.l0_cid, "candidates": [
                                                         {k: v for k, v in c.items() if k != "words"} | {"length": len(c["words"])}
                                                         for c in led.candidates]})
        with gzip.open(self.dir / f"candidates_{arm}.jsonl.gz", "wt", encoding="utf-8") as f:
            for c in led.candidates:
                f.write(json.dumps({"cid": c["cid"], "kind": c["kind"], "words_hex": bytes(c["words"]).hex()}) + "\n")
        if arm == "C":
            with gzip.open(self.dir / "coverage_C.json.gz", "wt", encoding="utf-8") as f:
                json.dump([[list(k), c, t] for k, (c, t) in self.coverage.keys.items()], f, separators=(",", ":"))

    def make_job(self, arm: str, w: int, remaining: int) -> Dict[str, Any]:
        cfg = self.cfg
        if arm == "T":
            it = self.iteration
            self.iteration += 1
            assert self.archive is not None
            cell = self.archive.dispatch(it, w)
            want = cell.L + min(cfg.burst_words, cfg.horizon - cell.L)
            job = {"kind": "iterate", "arm": "T", "iteration": it, "cell": cell.id, "rep": (cell.burst, cell.offset),
                   "words": self.archive.cell_words(cell), "end": cell.end, "end_digest": cell.end_digest, "chain": cell.chain,
                   "terminal": cell.terminal, "pin": self.pin, "archive_id": cfg.archive_id, "burst_words": cfg.burst_words,
                   "allowance": min(want, remaining), "level": cell.level, "L": cell.L}
        else:
            ep = self.episode
            self.episode += 1
            job = {"kind": "control", "arm": "C", "episode": ep, "pin": self.pin, "allowance": min(cfg.horizon, remaining)}
        self.pool_job[w] = job
        return job

    def commit(self, arm: str, job: Mapping[str, Any], res: Mapping[str, Any], rows_path: Path) -> None:
        ledger = self.ledgers[arm]
        cum_before = ledger.commit(res["ticks"])
        self.ticks[arm] = ledger.ticks
        cut = res["end_reason"] == "cut"
        if cut:
            ledger.cut_jobs += 1
        row: Dict[str, Any] = {"arm": arm, "worker": res["worker"], "cum_before": cum_before, "ticks": res["ticks"],
                               "end_reason": res["end_reason"], "mode": res["mode"], "wall_s": res["wall_s"],
                               "step_s": res["step_s"], "wait_s": res["startup"].get("wait_s"),
                               "t_end": res["t_end"], "tick0_equal": bool(res["tick0"].get("equal", True))}
        if arm == "T":
            r = dict(res, cum_before=cum_before, session=self.cfg.session_id)
            info = self.archive.ingest(r)
            self._count_reversals()
            row.update({"iteration": res["iteration"], "cell": res["cell"], "level": job.get("level"), "L": res["L"],
                        "burst_ticks": len(res["words"]), "burst": info["burst"], "new": info["new"],
                        "replaced": info["replaced"], "kept": info["kept"], "prefix": res["prefix"]})
            words_all = bytes(job["words"]) + bytes(res["words"])
            if res.get("labels") is not None and res["words"]:
                ledger.register(cum_before=cum_before, iteration=res["iteration"], words=words_all, prefix_len=int(res["L"]),
                                labels=res["labels"], breaks=res["breaks_all"], end_reason=res["end_reason"], t_end=res["t_end"])
            else:
                ledger.job_log.append((cum_before, int(res["ticks"]), int(res["t_end"])))
        else:
            for j, key in res["reaches"]:
                self.coverage.visit(tuple(key), cum_before + j, j)
            row.update({"episode": res["episode"]})
            ledger.register(cum_before=cum_before, iteration=res["episode"], words=bytes(res["words"]), prefix_len=0,
                            labels=res["labels"], breaks=res["breaks_all"], end_reason=res["end_reason"], t_end=res["t_end"])
        append_jsonl(rows_path, row)

    def _count_reversals(self) -> None:
        assert self.archive is not None
        d = self.archive.diag
        self.vel_reversals = {"count": d["velocity_reversals"], "examples": list(d["velocity_reversal_examples"])}
