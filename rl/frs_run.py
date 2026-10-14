"""Fast-route lab (frs) run engine: one lab run of one arm, unattended, bounded by its wall limit.

    open     readiness (registered thresholds) and no BattleShip process (a refusal launches nothing), the import pins, the code snapshot (and the
             night's expected code digest), the lab archive (sd2's closing archive, E6 off), the lab session event, the memory sampler, N workers
    explore  dispatch v4 selections to idle workers; answer segment boundaries (CONT); ingest every job as one burst; quarantine stale prefixes;
             verify every clear twice from tick 0 in fresh processes on a borrowed worker slot (the reference clear first); stop cleanly at the
             explore deadline or the memory budget, at once on an integrity problem
    drain    no new job; boundaries answered no; in-flight jobs finish (grace), then abort
    close    workers stopped; remaining candidates verified (up to 5 at once) before the close deadline; every lab burst re-derived from its keys;
             the closing archive; code re-hash; summary.json, report.md, one index row

Statuses (exit codes): COMPLETED 0, MEMORY_BUDGET 0, REFUSED 2, LAB_INVALID 3, LAB_INCOMPLETE 4. Everything the run writes is under the lab
root. Design: logs/frs_prep/phase1_plan.md sections 3 to 8.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
import types
from dataclasses import dataclass, field
from multiprocessing.connection import wait as mp_wait
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import frs_archive as fa  # noqa: E402
import frs_guard as g  # noqa: E402
import frs_machine as fm  # noqa: E402
import frs_report as frep  # noqa: E402
import frs_verify as fv  # noqa: E402
import frs_worker as fw  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_explore as mx  # noqa: E402
import m8_rd_rule as mrule  # noqa: E402
import m8_rd_run as mrun  # noqa: E402

RUN_CONTRACT = "frs_lab_run_v1"
F3_WINDOW = 20                    # the analysis's F3 window: the last 20 words of a length-ended segment
CONT_MAX_SEGMENTS = 4             # at most three continuations (the proposal's R4): at most 480 words
MARGIN = 24                       # E7's margin M (sd1's and sd2's registered margin)
QUARANTINE_LIMIT = 3              # quarantines per run; one more is LAB_INVALID (owner, 2026-10-14)
ARMS: Dict[str, Dict[str, int]] = {"CONTROL": {"segment_words": mx.BURST_WORDS, "max_segments": 1, "window": F3_WINDOW},
                                   "CONT": {"segment_words": mx.BURST_WORDS, "max_segments": CONT_MAX_SEGMENTS, "window": F3_WINDOW}}
ORIGINS = {"segment_words": "m8_rd_explore_v1 BURST_WORDS (one explorer burst)", "max_segments": "CONTROL 1 (sd2); CONT 4 (proposal R4: <= 3 continuations)",
           "window": "the fast-route analysis's F3 (last 20 words)", "margin": "sd1 / sd2 registered E7 margin", "e6": "off for every lab arm (decision Q5)",
           "reference": "the imported best verified clear (sd2), fixed for the run (owner, 2026-10-14)", "n_workers": "N = 5 (sd2)",
           "quarantine_limit": "owner, 2026-10-14", "lifecycle_limit": "m8_rd_rule.MAX_LIFECYCLE_FAILURES (registered)",
           "job_timeout_s": "m8_rd_run.JOB_TIMEOUT_S (registered)", "memory": "registered caps minus fixed headroom (frs_machine)",
           "draw_id": "<archive id>_frs_<label>: shared by the two arms of a label pair (owner, 2026-10-14)"}
STATUS_RANK = {"COMPLETED": 0, "MEMORY_BUDGET": 1, "LAB_INCOMPLETE": 2, "LAB_INVALID": 3}
EXIT = {"COMPLETED": 0, "MEMORY_BUDGET": 0, "REFUSED": 2, "LAB_INVALID": 3, "LAB_INCOMPLETE": 4}
CODE_MODULES = ("frs_guard", "frs_machine", "frs_archive", "frs_worker", "frs_verify", "frs_report", "frs_run", "frs_lab", "m7f_trace", "m7n_crossing",
                "battleship_process", "battleship_client", "m7_standby", "m7_runtime")


# -- code snapshot -----------------------------------------------------------------------------------------------------------------------------


def code_manifest(repo: Path = g.REPO) -> Dict[str, str]:
    """{repo-relative path: sha256} of every rl/ module a lab run imports, determined in a FRESH interpreter (the same set for the planner and
    the runner, whatever the caller imported)."""
    code = ("import json, sys; sys.path.insert(0, %r); import importlib; [importlib.import_module(m) for m in %r]; "
            "print(json.dumps(sorted({m.__file__ for m in list(sys.modules.values()) if getattr(m, '__file__', None)})))"
            % (str(Path(repo) / "rl"), list(CODE_MODULES)))
    r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, cwd=str(Path(repo) / "rl"), timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"the code manifest could not be computed: {r.stderr[-800:]}")
    rl = os.path.normcase(str((Path(repo) / "rl").resolve()))
    out: Dict[str, str] = {}
    for f in json.loads(r.stdout.strip().splitlines()[-1]):
        p = Path(f).resolve()
        if os.path.normcase(str(p)).startswith(rl + os.sep):
            out[p.relative_to(Path(repo).resolve()).as_posix()] = g.sha256_file(p)
    for p in sorted((Path(repo) / "rl").glob("frs_*.py")):
        out.setdefault(p.relative_to(Path(repo)).as_posix(), g.sha256_file(p))
    return dict(sorted(out.items()))


def code_digest(manifest: Mapping[str, str]) -> str:
    return g.sha256_text(json.dumps(dict(sorted(manifest.items())), separators=(",", ":")))


# -- configuration and the injected environment -----------------------------------------------------------------------------------------------


@dataclass
class LabRunConfig:
    lab_root: Path
    run_dir: Path
    run_id: str
    arm: str
    label: str
    wall_s: float
    open_reserve_s: float = 240.0
    close_reserve_s: float = 360.0
    n_workers: int = 5
    margin: int = MARGIN
    quarantine_limit: int = QUARANTINE_LIMIT
    lifecycle_limit: int = mrule.MAX_LIFECYCLE_FAILURES
    tick_cap: int = 50_000_000
    job_timeout_s: float = mrun.JOB_TIMEOUT_S
    drain_grace_s: float = 30.0
    stop_grace_s: float = 60.0
    close_write_reserve_s: float = 120.0
    progress_every_s: float = 60.0
    verify_parallel_close: int = 5
    expect_code: Optional[str] = None
    import_dir: Optional[Path] = None

    @property
    def explore_s(self) -> float:
        return max(0.0, self.wall_s - self.open_reserve_s - self.close_reserve_s)

    @property
    def imp(self) -> Path:
        return Path(self.import_dir) if self.import_dir is not None else Path(self.lab_root) / "import"


@dataclass
class LabEnv:
    """Everything that touches the game or the machine (the real one is built by frs_lab; the tests inject the stub world)."""

    worker_spec: Callable[[int], Dict[str, Any]]
    replay: fv.ReplayFn
    analyse: fv.Analyse
    readiness: Callable[[], Dict[str, Any]]
    battleship_pids: Callable[[], Optional[List[int]]]
    snapshot: Callable[[], Optional[Dict[str, Any]]]
    import_problems: Callable[[], List[str]]
    wait_no_battleship: Callable[[float], List[int]]
    code_manifest: Callable[[], Dict[str, str]]
    backend: str = "real"
    now: Callable[[], float] = time.monotonic
    log: Callable[[str], None] = field(default=lambda s: print(f"[frs {time.strftime('%H:%M:%S')}] {s}", flush=True))
    sample_s: float = fm.SAMPLE_S
    row_every_s: float = fm.ROW_EVERY_S
    caps: Optional[Mapping[str, float]] = None
    soft: Optional[Mapping[str, float]] = None


# -- the worker pool --------------------------------------------------------------------------------------------------------------------------


class FrsPool(mrun.WorkerPool):
    """rd1's pool, spawning the lab worker; `poll2` answers segment boundaries (without ending the job) and returns finished jobs."""

    def __init__(self, spec_fn: Callable[[int], Dict[str, Any]], now: Callable[[], float]):
        super().__init__(types.SimpleNamespace(worker_spec=lambda rank, cfg: spec_fn(rank), now=now), None)

    def start(self, n: int, timeout: float = 180.0) -> None:
        for rank in range(n):
            parent, child = self.ctx.Pipe(duplex=True)
            spec = self.env.worker_spec(rank, self.cfg)
            p = self.ctx.Process(target=fw.worker_main, args=(child, spec, self.abort), name=f"frs-w{rank:02d}", daemon=True)
            p.start()
            child.close()
            self.procs.append(p)
            self.conns.append(parent)
        deadline = self.env.now() + timeout
        pending = set(range(n))
        self.infos = [{} for _ in range(n)]
        while pending:
            if self.env.now() > deadline:
                raise mrun.CapStop(f"workers {sorted(pending)} not ready after {timeout:.0f} s")
            for i in list(pending):
                if self.conns[i].poll(0.1):
                    kind, payload = self.conns[i].recv()
                    if kind != "ready":
                        raise mrun.CapStop(f"worker {i} failed to start: {payload}")
                    self.infos[i] = payload
                    pending.discard(i)
                elif not self.procs[i].is_alive():
                    raise mrun.CapStop(f"worker {i} died during start (exit code {self.procs[i].exitcode})")

    def poll2(self, timeout: float, on_boundary: Callable[[int, Dict[str, Any]], None]) -> List[Tuple[int, str, Dict[str, Any]]]:
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
                if kind == "boundary":
                    on_boundary(i, payload)
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


# -- the runner ----------------------------------------------------------------------------------------------------------------------------------


class Refused(Exception):
    """Open-phase refusal: nothing was launched."""


class Runner:
    def __init__(self, cfg: LabRunConfig, env: LabEnv):
        if cfg.arm not in ARMS:
            raise ValueError(f"unknown arm {cfg.arm!r}; arms are {sorted(ARMS)}")
        self.cfg, self.env = cfg, env
        self.arm = dict(ARMS[cfg.arm])
        self.fs = g.LabFS(cfg.lab_root)
        self.dir = Path(cfg.run_dir)
        self.t0 = env.now()
        self.phase = "open"
        self.phase_wall: Dict[str, float] = {}
        self.status = "COMPLETED"
        self.stop_reason: Optional[str] = None
        self.notes: List[str] = []
        self.stopping = False
        self.pool: Optional[FrsPool] = None
        self.sampler: Optional[fm.Sampler] = None
        self.lab: Optional[fa.LabArchive] = None
        self.inflight: Dict[int, Dict[str, Any]] = {}
        self.vqueue: List[Dict[str, Any]] = []
        self.vrows: List[Dict[str, Any]] = []
        self.vthread: Optional[threading.Thread] = None
        self.vbox: Dict[str, Any] = {}
        self.lent: Optional[int] = None
        self.reference_ok: Optional[bool] = None
        self.quarantines: List[Dict[str, Any]] = []
        self.c = {"dispatches": 0, "jobs": 0, "ticks": 0, "prefix_ticks": 0, "burst_ticks": 0, "cut_jobs": 0, "new_cells": 0, "replacements": 0,
                  "lifecycle_failures": 0, "aborted": 0, "tick0_unequal": 0}
        self.end_reasons: Dict[str, int] = {}
        self.jobs_by_words: Dict[str, int] = {}
        self.cont_level: Dict[str, List[int]] = {}
        self.cont_segment: Dict[str, List[int]] = {}
        self.timing = {"select_s": 0.0, "ingest_s": 0.0, "answer_s": 0.0}
        self.reserved = 0
        self.cum = 0
        self.next_it = 0
        self.explore_wall = 0.0
        self.cells_at_stop: Optional[int] = None
        self.code: Dict[str, str] = {}
        self.code_dig = ""
        self.start: Dict[str, Any] = {}
        self.ref: Dict[str, Any] = {}
        self.pin: Dict[str, Any] = {}
        self.unverified: List[Dict[str, Any]] = []
        self.integrity: Dict[str, Any] = {}
        self.load_mb: Optional[float] = None
        self._last_progress = self.t0
        self.utc_start = g.utc()
        self.t_explore = self.t0

    # -- bookkeeping --------------------------------------------------------------------------------------------------------------------------

    def log(self, s: str) -> None:
        self.env.log(f"{self.cfg.run_id}: {s}")
        try:
            self.fs.append_jsonl(self.dir / "run_log.jsonl", {"t_s": round(self.env.now() - self.t0, 1), "phase": self.phase, "msg": s[:2000]})
        except (OSError, g.LabRootError):
            pass

    def mark(self, status: str, reason: str, *, abort: bool = False) -> None:
        if STATUS_RANK[status] > STATUS_RANK[self.status]:
            self.status = status
        self.notes.append(f"{status}: {reason}"[:600])
        if not self.stopping:
            self.stopping = True
            self.stop_reason = reason[:600]
            if self.phase == "explore":
                self.explore_wall = self.env.now() - self.t_explore
                self.cells_at_stop = len(self.lab.cells) if self.lab else None
        if abort and self.pool is not None:
            self.pool.abort.set()
        if status != "COMPLETED":
            self.log(f"{status}: {reason}")

    def elapsed(self) -> float:
        return self.env.now() - self.t0

    # -- run ------------------------------------------------------------------------------------------------------------------------------------

    def run(self) -> int:
        try:
            self.open()
        except Refused as exc:
            self.fs.write_json(self.dir / "refused.json", {"mode": "lab", "utc": g.utc(), "run_id": self.cfg.run_id, "reason": str(exc)})
            self.log(f"REFUSED: {exc}")
            if self.sampler is not None:
                self.sampler.stop()
            return EXIT["REFUSED"]
        except Exception as exc:  # noqa: BLE001 - an open failure after launching is a closed, reported LAB_INCOMPLETE
            self.mark("LAB_INCOMPLETE", f"open failed: {type(exc).__name__}: {exc}", abort=True)
            self.log(traceback.format_exc()[-2000:])
        else:
            try:
                self.explore()
                self.drain()
            except Exception as exc:  # noqa: BLE001
                self.mark("LAB_INCOMPLETE", f"runner error: {type(exc).__name__}: {exc}", abort=True)
                self.log(traceback.format_exc()[-2000:])
        try:
            self.close()
        except Exception as exc:  # noqa: BLE001
            self.mark("LAB_INCOMPLETE", f"close error: {type(exc).__name__}: {exc}")
            self.log(traceback.format_exc()[-2000:])
            try:
                self.write_summary()
            except Exception:  # noqa: BLE001
                self.log(traceback.format_exc()[-2000:])
        return EXIT[self.status]

    # -- open -------------------------------------------------------------------------------------------------------------------------------------

    def open(self) -> None:
        cfg, env = self.cfg, self.env
        if self.dir.exists():
            raise Refused(f"{self.dir} exists (a run folder is never overwritten)")
        self.fs.mkdir(self.dir)
        ready = env.readiness()
        if not ready["ok"]:
            raise Refused(f"readiness: {ready['problems']}")
        pids = env.battleship_pids()
        if pids is None or pids:
            raise Refused(f"BattleShip processes already running (or unreadable): {pids}")
        bad = env.import_problems()
        if bad:
            raise Refused(f"import pins: {bad[:6]}")
        self.code = env.code_manifest()
        self.code_dig = code_digest(self.code)
        if cfg.expect_code and cfg.expect_code != self.code_dig:
            raise Refused(f"code digest {self.code_dig[:16]} differs from the night's {cfg.expect_code[:16]}")
        for rel in self.code:
            src = g.REPO / rel
            dst = self.dir / "code" / rel
            self.fs.mkdir(dst.parent)
            shutil.copyfile(src, dst)
        self.fs.write_json(self.dir / "code" / "manifest.json", {"digest": self.code_dig, "files": self.code})
        self.sampler = fm.Sampler(lambda r: self.fs.append_jsonl(self.dir / "memory.jsonl", r), interval=env.sample_s, row_every=env.row_every_s,
                                  caps=env.caps or fm.CAPS_MB, soft=env.soft, snapshot=env.snapshot, now=env.now,
                                  extra=lambda: {"cells": len(self.lab.cells) if self.lab else None,
                                                 "bursts": len(self.lab.bursts) if self.lab else None, "phase": self.phase}).start()
        t = env.now()
        lab, meta, a6 = fa.LabArchive.read_import(cfg.imp / "archive", e6=False)
        del a6
        load_s = env.now() - t
        self.load_mb = fm.main_private_mb()
        self.ref = fv.load_reference(cfg.imp / "reference", env.analyse)
        if self.ref["problems"]:
            raise Refused(f"reference: {self.ref['problems']}")
        rr = fa.record_reference_from_route(self.ref["meta"], "import/reference/metadata.json")
        self.pin = dict(meta["pin_tick0"])
        draw = fa.draw_id_for(lab.archive_id, cfg.label)
        desc = fw.explore_description(self.arm["segment_words"], self.arm["max_segments"], self.arm["window"])
        ev = lab.begin_lab(run_id=cfg.run_id, draw_id=draw, record_reference=rr, margin=cfg.margin,
                           explore={"contract": desc["contract"], "digest": fw.explore_digest(desc), **self.arm})
        self.lab = lab
        self.next_it = int(ev["first_iteration"])
        self.cum = max((b.cum_before + b.ticks for b in lab.bursts), default=0)
        probs = lab.lab_probabilities()
        per: Dict[str, List[float]] = {}
        for cid, p in probs.items():
            d = per.setdefault(str(lab.cells[cid].level), [0, 0.0])
            d[0] += 1
            d[1] += p
        breaks = [int(t) for t, _i in self.ref["expected"]["breaks"]]
        self.start = {"import_digest": self.import_digest(), "cells": len(lab.cells), "bursts": len(lab.bursts), "events": len(lab.events),
                      "first_iteration": self.next_it, "draw_id": draw, "bound_max_L": lab.lab_bound_L, "e6": lab.e6,
                      "reference": {k: rr[k] for k in ("completion_input_tick", "completion_time_passed", "native_action_digest", "cid", "session")},
                      "eligible": len(probs), "eligible_by_level": {k: [v[0], round(v[1], 5)] for k, v in sorted(per.items(), key=lambda kv: int(kv[0]))},
                      "fastest_arrival": lab.fastest_arrival(), "reference_arrival": {str(i + 1): t for i, t in enumerate(sorted(breaks))},
                      "load_s": round(load_s, 1), "load_main_mb": round(self.load_mb, 1) if self.load_mb else None}
        self.start["reference_arrival"]["0"] = 0
        self.fs.write_json(self.dir / "config.json", self.config_record())
        self.log(f"archive loaded in {load_s:.1f} s: {len(lab.cells):,} cells, {len(lab.bursts):,} bursts, bound L <= {lab.lab_bound_L}, "
                 f"eligible {len(probs):,}, E6 {'on' if lab.e6 else 'off'}, draw id {draw}")
        self.vqueue.append({"kind": "reference", "iteration": None, "cell": None, "burst": None, "words": self.ref["words"],
                            "claim": {"words_digest": self.ref["meta"]["native_action_digest"],
                                      "completion_input_tick": self.ref["expected"]["completion_input_tick"],
                                      "completion_time_passed": self.ref["expected"]["completion_time_passed"],
                                      "chain": self.ref["expected"]["final_chain"]}, "claimed_len": len(self.ref["words"])})
        self.pool = FrsPool(env.worker_spec, env.now)
        self.pool.start(cfg.n_workers)
        self.phase_wall["open"] = round(env.now() - self.t0, 1)
        self.log(f"open done in {self.phase_wall['open']:.0f} s; {cfg.n_workers} workers ready; arm {cfg.arm} {self.arm}")

    def import_digest(self) -> str:
        p = self.cfg.imp / "import_manifest.json"
        return g.sha256_file(p) if p.is_file() else "none"

    def config_record(self) -> Dict[str, Any]:
        c = self.cfg
        return {"mode": "lab", "contract": RUN_CONTRACT, "run_id": c.run_id, "arm": c.arm, "label": c.label, "utc": g.utc(),
                "arm_params": self.arm, "wall_s": c.wall_s, "open_reserve_s": c.open_reserve_s, "close_reserve_s": c.close_reserve_s,
                "explore_s": c.explore_s, "n_workers": c.n_workers, "margin": c.margin, "e6": False, "quarantine_limit": c.quarantine_limit,
                "lifecycle_limit": c.lifecycle_limit, "tick_cap": c.tick_cap, "job_timeout_s": c.job_timeout_s, "drain_grace_s": c.drain_grace_s,
                "max_battleship_processes": fm.MAX_BATTLESHIP, "memory_caps_mb": dict(self.env.caps or fm.CAPS_MB),
                "memory_soft_budget_mb": dict(self.env.soft or fm.soft_budget(self.env.caps or fm.CAPS_MB)), "readiness": dict(fm.READINESS),
                "flags_explore": fv.FLAGS_EXPLORE, "flags_verify": fv.FLAGS_VERIFY, "backend": self.env.backend, "code_digest": self.code_dig,
                "expect_code": c.expect_code, "import": str(c.imp), "start": self.start, "origins": ORIGINS}

    # -- explore ---------------------------------------------------------------------------------------------------------------------------------

    def explore(self) -> None:
        cfg, env = self.cfg, self.env
        assert self.pool is not None and self.lab is not None and self.sampler is not None
        self.phase = "explore"
        self.t_explore = env.now()
        deadline = min(self.t_explore + cfg.explore_s, self.t0 + cfg.wall_s - cfg.close_reserve_s)
        while not self.stopping:
            for w, kind, payload in self.pool.poll2(0.2, self.on_boundary):
                self.handle(w, kind, payload)
            if self.stopping:
                break
            now = env.now()
            s = self.sampler
            if s.hard_breach:
                self.mark("LAB_INCOMPLETE", s.hard_breach, abort=True)
            elif s.proc_breach:
                self.mark("LAB_INCOMPLETE", s.proc_breach, abort=True)
            elif g.LabGuard.violations:
                self.mark("LAB_INVALID", f"guard violation in the main process: {g.LabGuard.violations[:2]}", abort=True)
            elif s.soft_breach:
                self.mark("MEMORY_BUDGET", s.soft_breach)
            elif now >= deadline:
                self.mark("COMPLETED", "explore deadline")
            elif self.pool.oldest_age() > cfg.job_timeout_s:
                self.mark("LAB_INCOMPLETE", f"a job has been in flight for more than {cfg.job_timeout_s:.0f} s", abort=True)
            elif not [i for i, pr in enumerate(self.pool.procs) if pr.is_alive() and i not in self.pool.retired]:
                self.mark("LAB_INCOMPLETE", "no live worker is left", abort=True)
            if self.stopping:
                break
            self.verification_step()
            for w in self.pool.idle():
                if w == self.lent or self.stopping:
                    continue
                job = self.make_job(w)
                if job is None:
                    break
                self.pool.send(w, job)
            self.progress()
        if not self.explore_wall:
            self.explore_wall = env.now() - self.t_explore
        self.phase_wall["explore"] = round(self.explore_wall, 1)

    def progress(self, force: bool = False) -> None:
        now = self.env.now()
        if not force and now - self._last_progress < self.cfg.progress_every_s:
            return
        self._last_progress = now
        lab = self.lab
        ex = max(1e-9, now - self.t_explore)
        cb = sum(v[0] for v in self.cont_level.values())
        cc = sum(v[1] for v in self.cont_level.values())
        mb = (self.sampler.last or {}).get("main_private_mb") if self.sampler else None
        nv = sum(1 for v in self.vrows if v["kind"] == "clear" and v["verdict"] == fv.VERIFIED)
        self.log(f"t {self.elapsed():.0f}s dispatches {self.c['dispatches']:,} jobs {self.c['jobs']:,} ({3600.0 * self.c['jobs'] / ex:,.0f}/h) "
                 f"cells {len(lab.cells) if lab else 0:,} new {self.c['new_cells']:,} burst ticks {self.c['burst_ticks']:,} cont {cc}/{cb} "
                 f"clears verified {nv} queued {len(self.vqueue)} quarantines {len(self.quarantines)} main MB {mb} in flight {len(self.pool.busy) if self.pool else 0}")
        try:
            self.fs.write_json(self.dir / "state.json", {"mode": "lab", "utc": g.utc(), "phase": self.phase, "elapsed_s": round(self.elapsed(), 1),
                                                          "counters": self.c, "status": self.status, "stop": self.stop_reason,
                                                          "verifications": len(self.vrows), "queue": len(self.vqueue)})
        except OSError:
            pass

    def make_job(self, w: int) -> Optional[Dict[str, Any]]:
        lab = self.lab
        assert lab is not None
        it = self.next_it
        t = time.perf_counter()
        cell = lab.dispatch(it, w)
        words = lab.cell_words(cell)
        self.timing["select_s"] += time.perf_counter() - t
        self.next_it += 1
        max_words = self.arm["segment_words"] * self.arm["max_segments"]
        want = cell.L + min(max_words, mcell.HORIZON - cell.L)
        allowance = min(want, self.cfg.tick_cap - self.c["ticks"] - self.reserved)
        if allowance <= cell.L:
            lab.note_failure(it, "tick cap")
            self.mark("LAB_INCOMPLETE", f"the safety tick cap {self.cfg.tick_cap:,} is reached")
            return None
        job = {"kind": fw.JOB_KIND, "iteration": it, "cell": cell.id, "rep": (cell.burst, cell.offset), "words": words, "end": cell.end,
               "end_digest": cell.end_digest, "chain": cell.chain, "terminal": cell.terminal, "pin": self.pin, "archive_id": lab.draw_for(it),
               "allowance": allowance, **self.arm}
        self.inflight[w] = {"it": it, "cell": cell.id, "level": cell.level, "L": cell.L, "words": words, "reserved": allowance, "cont": []}
        self.reserved += allowance
        self.c["dispatches"] += 1
        return job

    def on_boundary(self, w: int, payload: Dict[str, Any]) -> None:
        t = time.perf_counter()
        info = self.inflight.get(w)
        if self.stopping or info is None or info["it"] != int(payload["iteration"]):
            d: Dict[str, Any] = {"go": False, "stopping": True}
        else:
            d = self.lab.continuation_decision(payload["reaches"])
        go = bool(d["go"])
        if info is not None:
            info["cont"].append([int(payload["segment"]), len(payload["reaches"]), d.get("new"), d.get("shorter"), d.get("max_gain"), int(go)])
        try:
            self.pool.conns[w].send(("continue", {"iteration": payload["iteration"], "segment": payload["segment"], "go": go}))
        except (OSError, BrokenPipeError):
            pass
        self.timing["answer_s"] += time.perf_counter() - t

    def handle(self, w: int, kind: str, payload: Dict[str, Any]) -> None:
        lab = self.lab
        info = self.inflight.pop(w, None)
        if info is not None:
            self.reserved -= info["reserved"]
        if kind in ("died", "fatal"):
            if info is not None:
                lab.note_failure(info["it"], f"worker {kind}")
            self.mark("LAB_INCOMPLETE", f"worker {w} {kind}: {json.dumps(payload, default=str)[:300]}", abort=True)
            return
        if payload.get("guard_violations") or payload.get("provenance_violations"):
            self.mark("LAB_INVALID", f"worker {w} guard / provenance violation: "
                                     f"{(payload.get('guard_violations') or payload.get('provenance_violations'))[:2]}", abort=True)
        if payload.get("ok"):
            self.commit(w, info, payload)
            return
        k = payload.get("kind")
        it = info["it"] if info else payload.get("iteration")
        if it is not None and int(it) in lab._pending:
            if k == "mismatch" and payload.get("mismatch") in fa.QUARANTINE_KINDS and info is not None:
                lab.quarantine(info["cell"], info["it"], str(payload["mismatch"]))
                row = {"mode": "lab", "iteration": info["it"], "cell": info["cell"], "level": info["level"], "L": info["L"],
                       "kind": payload["mismatch"], "detail": json.dumps(payload.get("detail"), default=str)[:800], "worker": w, "utc": g.utc()}
                self.quarantines.append(row)
                self.fs.append_jsonl(self.dir / "quarantine.jsonl", row)
                self.log(f"quarantined cell {info['cell']} (L {info['L']}): {payload['mismatch']}")
                if len(self.quarantines) > self.cfg.quarantine_limit:
                    self.mark("LAB_INVALID", f"{len(self.quarantines)} quarantines > {self.cfg.quarantine_limit}", abort=True)
                return
            lab.note_failure(int(it), f"{k}: {payload.get('mismatch') or payload.get('outcome') or payload.get('error')}"[:200])
        if k == "mismatch":
            self.mark("LAB_INVALID", f"iteration {it}: mismatch {payload.get('mismatch')} {json.dumps(payload.get('detail'), default=str)[:400]}",
                      abort=True)
        elif k == "lifecycle":
            self.c["lifecycle_failures"] += 1
            self.log(f"lifecycle failure {payload.get('outcome')} on worker {w}: {str(payload.get('message'))[:200]}")
            if self.c["lifecycle_failures"] > self.cfg.lifecycle_limit:
                self.mark("LAB_INCOMPLETE", f"more than {self.cfg.lifecycle_limit} lifecycle failures", abort=True)
        elif k == "aborted":
            self.c["aborted"] += 1
        else:
            self.mark("LAB_INCOMPLETE", f"worker {w} error: {str(payload.get('error'))[:300]}", abort=True)
            self.log(str(payload.get("trace", ""))[-1500:])

    def commit(self, w: int, info: Optional[Dict[str, Any]], res: Mapping[str, Any]) -> None:
        lab = self.lab
        if info is None:
            self.mark("LAB_INVALID", f"worker {w} returned a job that was not in flight")
            return
        cum_before = self.cum
        self.cum += int(res["ticks"])
        t = time.perf_counter()
        ing = lab.ingest(dict(res, cum_before=cum_before, session=self.cfg.run_id))
        self.timing["ingest_s"] += time.perf_counter() - t
        n = len(res["words"])
        seg = self.arm["segment_words"]
        self.c["jobs"] += 1
        self.c["ticks"] += int(res["ticks"])
        self.c["burst_ticks"] += n
        self.c["new_cells"] += int(ing["new"])
        self.c["replacements"] += int(ing["replaced"])
        self.c["prefix_ticks"] += int(res["ticks"]) - n
        if res["end_reason"] == "cut":
            self.c["cut_jobs"] += 1
        if not res["tick0"].get("equal", True):
            self.c["tick0_unequal"] += 1
        self.end_reasons[res["end_reason"]] = self.end_reasons.get(res["end_reason"], 0) + 1
        bucket = str(-(-n // seg) * seg) if n else "0"
        self.jobs_by_words[bucket] = self.jobs_by_words.get(bucket, 0) + 1
        lv = str(info["level"])
        for seg_i, _inw, _new, _sh, _g, go in info["cont"]:
            a = self.cont_level.setdefault(lv, [0, 0])
            a[0] += 1
            a[1] += go
            b = self.cont_segment.setdefault(str(seg_i), [0, 0])
            b[0] += 1
            b[1] += go
        self.fs.append_jsonl(self.dir / "iterations.jsonl", {
            "it": info["it"], "w": w, "cell": info["cell"], "lv": info["level"], "L": info["L"], "n": n, "end": res["end_reason"],
            "new": ing["new"], "repl": ing["replaced"], "burst": ing["burst"], "ticks": res["ticks"], "wall": res.get("wall_s"),
            "step": res.get("step_s"), "ask": res.get("ask_s"), "mode": res.get("mode"), "cont": info["cont"]})
        if res["end_reason"] == "clear" and n > 0:
            words = bytes(info["words"]) + bytes(res["words"])
            rj = res.get("result_json") or {}
            self.vqueue.append({"kind": "clear", "iteration": info["it"], "cell": info["cell"], "burst": ing["burst"], "words": words,
                                "claim": {"words_digest": mcell.words_digest(words), "completion_input_tick": rj.get("completion_input_tick"),
                                          "completion_time_passed": rj.get("completion_time_passed"), "chain": res.get("final_chain")},
                                "claimed_len": len(words), "provenance": lab.lineage_provenance(ing["burst"])})
            self.vqueue.sort(key=lambda c: (c["kind"] != "reference", c["claimed_len"]))
            self.log(f"clear candidate: iteration {info['it']}, {len(words):,} words (claimed {rj.get('completion_input_tick')} / "
                     f"{rj.get('completion_time_passed')}); queued for verification")

    # -- verification ------------------------------------------------------------------------------------------------------------------------

    def verify_candidate(self, cand: Mapping[str, Any], slot: int) -> Dict[str, Any]:
        label = "reference" if cand["kind"] == "reference" else f"clear_it{cand['iteration']}"
        try:
            out = fv.verify_twice(self.env.replay, self.env.analyse, cand["words"], cand["claim"], label, slot, trace_dir=self.dir / "traces")
        except Exception as exc:  # noqa: BLE001 - a crashed verification is an ERROR row, never a clear
            out = {"label": label, "verdict": fv.ERROR, "reasons": [f"{type(exc).__name__}: {exc}"[:300]], "r1": {}, "r2": {}, "errors": [],
                   "words": len(cand["words"]), "wall_s": None}
        if cand["kind"] == "reference" and out["verdict"] == fv.VERIFIED:
            out["reference_check"] = fv.reference_check(out["r1"], self.ref)
        return out

    def on_verified(self, cand: Mapping[str, Any], out: Mapping[str, Any]) -> None:
        verdict = out["verdict"]
        reasons = list(out.get("reasons") or [])
        prov = cand.get("provenance")
        if cand["kind"] == "clear" and verdict == fv.VERIFIED and not (prov or {}).get("ok"):
            verdict = fv.NOT_VERIFIED
            reasons.append(f"word provenance failed: {prov}")
            self.mark("LAB_INVALID", f"iteration {cand['iteration']}: a clear whose words do not re-derive from their keys", abort=True)
        row = {"mode": "lab", "kind": cand["kind"], "iteration": cand.get("iteration"), "cell": cand.get("cell"), "burst": cand.get("burst"),
               "words": len(cand["words"]), "words_digest": cand["claim"]["words_digest"], "verdict": verdict, "reasons": reasons,
               "completion_input_tick": out.get("completion_input_tick"), "completion_time_passed": out.get("completion_time_passed"),
               "final_chain": (out.get("r1") or {}).get("final_chain"), "claim": {k: v for k, v in cand["claim"].items()},
               "provenance": prov, "reference_check": out.get("reference_check"), "errors": out.get("errors"), "wall_s": out.get("wall_s"),
               "utc": g.utc(), "phase": self.phase}
        self.vrows.append(row)
        self.fs.append_jsonl(self.dir / "verifications.jsonl", row)
        if cand["kind"] == "reference":
            ok = verdict == fv.VERIFIED and bool((out.get("reference_check") or {}).get("ok"))
            self.reference_ok = ok
            self.log(f"reference clear re-verified in-run: {verdict} {'exact' if ok else reasons[:2]}")
            if not ok:
                if verdict == fv.ERROR:
                    self.mark("LAB_INCOMPLETE", "the reference clear could not be replayed", abort=True)
                else:
                    self.mark("LAB_INVALID", f"the reference clear did not replay exactly: {reasons[:2]} {out.get('reference_check')}", abort=True)
            return
        self.log(f"verification of iteration {cand['iteration']}: {verdict} {out.get('completion_input_tick')} / {out.get('completion_time_passed')}")
        if verdict == fv.NONDETERMINISTIC:
            self.mark("LAB_INVALID", f"iteration {cand['iteration']}: a claimed clear did not replay exactly: {reasons[:2]}", abort=True)

    def verification_step(self) -> None:
        if self.vthread is not None and not self.vthread.is_alive():
            self.vthread = None
            self.on_verified(self.vbox["cand"], self.vbox["out"])
        if self.vthread is None and self.vqueue and not self.stopping:
            if self.lent is None:
                idle = self.pool.idle()
                if idle:
                    self.lent = idle[0]
            if self.lent is not None and self.lent not in self.pool.busy:
                cand = self.vqueue.pop(0)
                self.vbox = {"cand": cand}

                def work() -> None:
                    self.vbox["out"] = self.verify_candidate(cand, 0)

                self.vthread = threading.Thread(target=work, name="frs-verify", daemon=True)
                self.vthread.start()
        elif self.vthread is None and not self.vqueue and self.lent is not None:
            self.lent = None

    # -- drain and close -----------------------------------------------------------------------------------------------------------------------

    def drain(self) -> None:
        cfg, env = self.cfg, self.env
        self.phase = "drain"
        t = env.now()
        if self.pool is not None:
            while self.pool.busy and env.now() - t < cfg.drain_grace_s and not self.pool.abort.is_set():
                for w, kind, payload in self.pool.poll2(0.2, self.on_boundary):
                    self.handle(w, kind, payload)
            if self.pool.busy:
                self.pool.abort.set()
                while self.pool.busy and env.now() - t < cfg.drain_grace_s + cfg.stop_grace_s:
                    for w, kind, payload in self.pool.poll2(0.2, self.on_boundary):
                        self.handle(w, kind, payload)
            if self.pool.busy:
                dead = self.pool.kill_busy()
                for w in dead:
                    info = self.inflight.pop(w, None)
                    if info is not None:
                        self.lab.note_failure(info["it"], "worker terminated after the stop")
                self.mark("LAB_INCOMPLETE", f"workers {dead} did not return after the stop and were terminated")
        if self.vthread is not None:
            self.vthread.join(timeout=max(30.0, cfg.close_reserve_s / 2))
            if not self.vthread.is_alive():
                self.vthread = None
                self.on_verified(self.vbox["cand"], self.vbox["out"])
        self.phase_wall["drain"] = round(env.now() - t, 1)

    def close(self) -> None:
        cfg, env = self.cfg, self.env
        self.phase = "close"
        t = env.now()
        if self.pool is not None:
            self.pool.stop(grace=60.0)
        left = env.wait_no_battleship(60.0)
        if self.vthread is not None:
            self.vthread.join(timeout=120.0)
            if not self.vthread.is_alive():
                self.on_verified(self.vbox["cand"], self.vbox["out"])
            self.vthread = None
        lab = self.lab
        if lab is not None:
            for it in list(lab._pending):
                lab.note_failure(it, "not returned before the close")
            self.close_verifications()
            tp = env.now()
            bad = [b.id for b in lab.lab_bursts() if not lab.provenance(b)]
            prov_s = env.now() - tp
            if bad:
                self.mark("LAB_INVALID", f"{len(bad)} lab bursts do not re-derive from their keys: {bad[:5]}")
            tw = env.now()
            lab.write_lab(self.dir / "archive", {"mode_lab_run": self.cfg.run_id, "utc": g.utc(), "checkpoint_seq": 1, "pin_tick0": self.pin,
                                                 "task": (self.ref.get("meta") or {}).get("task"), "status": self.status})
            self.integrity.update({"lab_bursts_rederived": len(lab.lab_bursts()), "lab_bursts_bad": len(bad), "provenance_s": round(prov_s, 1),
                                   "archive_write_s": round(env.now() - tw, 1)})
        changed = [rel for rel, h in self.code.items() if (g.REPO / rel).is_file() and g.sha256_file(g.REPO / rel) != h]
        self.integrity.update({"guard_violations_main": list(g.LabGuard.violations)[:5], "code_changed_during_run": changed,
                               "battleship_left": left, "tick0_unequal_jobs": self.c["tick0_unequal"], "reference_ok": self.reference_ok})
        if left:
            self.mark("LAB_INCOMPLETE", f"BattleShip processes still alive after the close: {left}")
        if self.reference_ok is None and lab is not None and self.status in ("COMPLETED", "MEMORY_BUDGET"):
            self.mark("LAB_INCOMPLETE", "the reference clear was not re-verified")
        self.phase_wall["close"] = round(env.now() - t, 1)
        self.write_summary()
        self.log(f"done: {self.status} ({self.stop_reason}); summary {self.dir / 'summary.json'}")

    def close_verifications(self) -> None:
        """Remaining candidates, up to verify_parallel_close at once (no worker is alive now), before the close deadline."""
        deadline = self.t0 + self.cfg.wall_s - self.cfg.close_write_reserve_s
        if not self.vqueue:
            return
        lock = threading.Lock()
        results: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
        queue = list(self.vqueue)
        self.vqueue = []

        def worker(slot: int) -> None:
            while True:
                with lock:
                    if not queue or self.env.now() >= deadline:
                        return
                    cand = queue.pop(0)
                out = self.verify_candidate(cand, slot)
                with lock:
                    results.append((cand, out))

        n = max(1, min(self.cfg.verify_parallel_close, len(queue)))
        ths = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(n)]
        for th in ths:
            th.start()
        for th in ths:
            th.join(timeout=max(1.0, deadline - self.env.now() + 120.0))
        for cand, out in results:
            self.on_verified(cand, out)
        self.unverified = [{"kind": c["kind"], "iteration": c.get("iteration"), "words": len(c["words"])} for c in queue]
        if any(c["kind"] == "reference" for c in queue):
            self.reference_ok = False if self.reference_ok is None else self.reference_ok

    # -- the summary ----------------------------------------------------------------------------------------------------------------------------

    def write_summary(self) -> Dict[str, Any]:
        lab = self.lab
        mem = self.sampler.stop() if self.sampler is not None else {}
        ex_h = max(1e-9, self.explore_wall / 3600.0)
        series = [r for r in (self.sampler.series if self.sampler else []) if r.get("phase") == "explore"]
        soft_main = float((self.env.soft or fm.soft_budget(self.env.caps or fm.CAPS_MB))["main_private"])
        cap_main = float((self.env.caps or fm.CAPS_MB)["main_private"])
        proj = fm.projection(series, load_mb=self.load_mb, load_cells=int(self.start.get("cells") or 0), explore_s=self.explore_wall,
                             soft_main_mb=soft_main, cap_main_mb=cap_main)
        fa_start = self.start.get("fastest_arrival") or {}
        fa_end = lab.fastest_arrival() if lab else {}
        levels = sorted(set(fa_start) | set(fa_end), key=int)
        clears = [v for v in self.vrows if v["kind"] == "clear"]
        nv = sum(1 for v in clears if v["verdict"] == fv.VERIFIED)
        cb = sum(v[0] for v in self.cont_level.values())
        cc = sum(v[1] for v in self.cont_level.values())
        jobs = max(1, self.c["jobs"])
        s = {"mode": "lab", "schema": frep.SUMMARY_SCHEMA, "run_id": self.cfg.run_id, "arm": self.cfg.arm, "label": self.cfg.label, "status": self.status,
             "stop": {"reason": self.stop_reason, "notes": self.notes[:12]}, "utc_start": self.utc_start, "utc_end": g.utc(),
             "folder": str(self.dir), "phase_wall_s": dict(self.phase_wall, explore=round(self.explore_wall, 1)),
             "config": {"wall_s": self.cfg.wall_s, "explore_s_planned": self.cfg.explore_s, **self.arm, "n_workers": self.cfg.n_workers,
                        "margin": self.cfg.margin, "e6": False, "draw_id": self.start.get("draw_id"), "code_digest": self.code_dig, "backend": self.env.backend},
             "start": {k: self.start.get(k) for k in ("import_digest", "cells", "bursts", "first_iteration", "bound_max_L", "reference", "eligible",
                                                       "load_s", "load_main_mb")},
             "work": dict(self.c, end_reasons=self.end_reasons),
             "throughput": {"dispatches_per_h": round(self.c["dispatches"] / ex_h, 1), "jobs_per_h": round(self.c["jobs"] / ex_h, 1),
                            "ticks_per_h": round(self.c["ticks"] / ex_h), "burst_ticks_per_h": round(self.c["burst_ticks"] / ex_h),
                            "new_cells_per_h": round(self.c["new_cells"] / ex_h, 1), "burst_share": round(self.c["burst_ticks"] / max(1, self.c["ticks"]), 4),
                            "select_ms_per_dispatch": round(1000.0 * self.timing["select_s"] / max(1, self.c["dispatches"]), 2),
                            "ingest_ms_per_job": round(1000.0 * self.timing["ingest_s"] / jobs, 2),
                            "answer_ms_total": round(1000.0 * self.timing["answer_s"], 1)},
             "archive": {"new_cells": self.c["new_cells"], "replacements": self.c["replacements"], "cells_end": len(lab.cells) if lab else None,
                         "bursts_end": len(lab.bursts) if lab else None, "cells_at_explore_stop": self.cells_at_stop,
                         "fastest_arrival": {lv: [fa_start.get(lv), fa_end.get(lv)] for lv in levels},
                         "reference_arrival": self.start.get("reference_arrival")},
             "continuation": {"boundaries": cb, "continued": cc, "rate": round(cc / cb, 4) if cb else None,
                              "by_level": {k: v for k, v in sorted(self.cont_level.items(), key=lambda kv: int(kv[0]))},
                              "by_boundary": dict(sorted(self.cont_segment.items())), "jobs_by_words": dict(sorted(self.jobs_by_words.items(), key=lambda kv: int(kv[0])))},
             "clears": {"candidates": len(clears) + len(self.unverified), "verified": nv, "best_verified": frep.best_verified(self.vrows),
                        "reference": ("exact" if self.reference_ok else "FAILED" if self.reference_ok is False else "not run"),
                        "rows": [{k: v.get(k) for k in ("kind", "iteration", "words", "verdict", "completion_input_tick", "completion_time_passed", "reasons")}
                                 for v in self.vrows], "unverified": self.unverified},
             "quarantine": {"count": len(self.quarantines), "limit": self.cfg.quarantine_limit,
                            "cells": [{k: q[k] for k in ("cell", "L", "level", "kind")} for q in self.quarantines]},
             "memory": {"peak": mem.get("peak"), "soft_breach": mem.get("soft_breach"), "hard_breach": mem.get("hard_breach"),
                        "proc_breach": mem.get("proc_breach"), "soft_budget_mb": mem.get("soft_budget_mb"), "projection": proj},
             "integrity": self.integrity}
        self.fs.write_text(self.dir / "summary.json", frep.compact_json(s), atomic=True)
        self.fs.write_text(self.dir / "report.md", frep.report_md(s), atomic=True)
        try:
            frep.append_index(Path(self.cfg.lab_root) / "frs_lab_index.md", s, lambda p, txt: self.fs.write_text(p, txt, atomic=True))
        except OSError as exc:
            self.log(f"index row not written: {exc}")
        return s

