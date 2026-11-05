#!/usr/bin/env python3
"""Run 3 lab worker: rl/frs_worker.py's `iterate_frs` job, unchanged, behind a transparent process proxy that shows every reply to
tools/frs/run3_anomaly.JobObserver (2026-11-04 session, step 4; SESSION_LOG_2026-11-04.md sections 8 and 9).

    proxy           `ObservedBackend` wraps the worker's backend; the process it hands out forwards observe / step / close and every
                    attribute to the real one, and returns each reply object unchanged (read-only). rl/frs_worker.py,
                    rl/m8_rd_worker.py and rl/m8_rd_cells.py are imported, never edited.
    D6              a null / NaN / inf in a burst reply raises run3_anomaly.NonFiniteReply inside the step; `run_job` turns it into the
                    burst truncated before that tick (`end_reason` "nonfinite", rebuilt by the observer with the worker's own
                    functions, plus the non-finite event and the replies from L): the engine ingests it like any burst, the run
                    goes on. Before this, the same reply raised TypeError in cell_key and stopped the whole run (review D6).
    events          every ok `iterate_frs` result carries `glitch` (the live detector events of the burst ticks).
    entry points    `worker_main` (rl/frs_worker.worker_main with the proxy, the decision recorder and this `run_job`) and
                    `Run3Pool` (rl/frs_run.FrsPool starting `worker_main`).

The job mapping (ok / mismatch / lifecycle / aborted / error) is rl/frs_worker.run_job's, plus the non-finite case.
"""
from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _p in (REPO / "rl", HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import frs_guard as g  # noqa: E402
import frs_run as fr  # noqa: E402
import frs_worker as fw  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_worker as mw  # noqa: E402
import run3_anomaly as ra  # noqa: E402

RUN3_WORKER_CONTRACT = "run3_worker_v1"


# -- the proxy -----------------------------------------------------------------------------------------------------------------------------


class ObservedProc:
    """Forwards everything to the real process; observe / step replies are shown to the job's observer first, then returned as is."""

    def __init__(self, proc: Any, owner: "ObservedBackend"):
        object.__setattr__(self, "_proc", proc)
        object.__setattr__(self, "_owner", owner)
        object.__setattr__(self, "_i", 0)

    def observe(self) -> Dict[str, Any]:
        reply = self._proc.observe()
        obs = self._owner.observer
        if obs is not None:
            obs.on_observe(reply)
        return reply

    def step(self, buttons: int, stick_x: int, stick_y: int) -> Dict[str, Any]:
        t0 = time.perf_counter()
        reply = self._proc.step(buttons, stick_x, stick_y)
        dt = time.perf_counter() - t0
        i = self._i
        object.__setattr__(self, "_i", i + 1)
        obs = self._owner.observer
        if obs is not None:
            obs.on_step(i, (int(buttons), int(stick_x), int(stick_y)), reply, dt)
        return reply

    def __getattr__(self, name: str) -> Any:
        return getattr(self._proc, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._proc, name, value)                     # e.g. `proc.failed = True` must reach the real process


class ObservedBackend:
    def __init__(self, backend: Any):
        self._backend = backend
        self.observer: Optional[ra.JobObserver] = None

    def acquire(self, *args: Any, **kwargs: Any) -> ObservedProc:
        return ObservedProc(self._backend.acquire(*args, **kwargs), self)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._backend, name)


class _Replay:
    """A stored observe reply served again, so mw._tick0 builds the same tick-0 report the job built."""

    def __init__(self, reply: Mapping[str, Any]):
        self.reply = reply

    def observe(self) -> Mapping[str, Any]:
        return self.reply


# -- the job ---------------------------------------------------------------------------------------------------------------------------------


def truncated_result(ctx: Any, job: Mapping[str, Any], obs: ra.JobObserver, proc_info: Mapping[str, Any], t_job: float) -> Dict[str, Any]:
    """The `iterate_frs` result of a burst that met a non-finite reply: the burst up to the tick before it, as run_iterate_frs records
    a burst (same functions), `end_reason` "nonfinite", plus the non-finite record."""
    L = obs.L
    _r0, _rec0, _rd0, _chain0, tick0 = mw._tick0(_Replay(obs.tick0), job["pin"])
    rb = obs.rebuild(ctx.clf)
    seg = int(job["segment_words"])
    n = len(rb["words"])
    prefix: Dict[str, Any] = {"words": L, "cut": False, "terminal": False}
    if L > 0:
        end_t = mcell.obs_tuple((obs.last_prefix or {})["observation"])
        prefix.update({"end_equal": True, "chain_equal": True, "end_digest_equal": True,
                       "host_frame_equal": end_t[mcell.HOST_FRAME] == tuple(job["end"])[mcell.HOST_FRAME]})
    nf = dict(obs.nonfinite or {})
    replies = list(obs.burst_replies) + [nf.pop("reply", None)]
    res: Dict[str, Any] = {"ok": True, "kind": fw.JOB_KIND, "iteration": job["iteration"], "cell": job["cell"], "rep": tuple(job["rep"]), "L": L,
                           "mode": proc_info.get("mode"), "startup": proc_info.get("startup"), "pid": proc_info.get("pid"), "worker": ctx.rank,
                           "tick0": tick0, "result_json": None, "exit_code": None, "worker_contract": fw.FRS_WORKER_CONTRACT,
                           "decisions": list(obs.decisions), "segments": -(-n // seg) if n else 0, "prefix": prefix, "words": rb["words"],
                           "end_reason": "nonfinite", "ticks": L + n, "reaches": rb["reaches"], "labels": rb["labels"],
                           "breaks_all": rb["breaks_all"], "t_end": rb["t_end"], "finish_error": None, "ask_s": round(obs.ask_s, 4),
                           "final_chain": rb["final_chain"],
                           "nonfinite": dict(nf, event=obs.nonfinite_event(), replies=replies)}
    return mw._stamp(res, t_job, {"step_s": obs.step_s})


def run_job(ctx: Any, job: Mapping[str, Any], geometry: ra.GeometryCache, selfcheck: bool = False) -> Dict[str, Any]:
    """One job; every outcome is a structured dict (rl/frs_worker.run_job's mapping, plus the non-finite truncation)."""
    obs = ra.JobObserver(job, geometry) if job.get("kind") == fw.JOB_KIND else None
    ctx.backend.observer = obs
    ctx.observer = obs
    t_job = time.perf_counter()
    try:
        try:
            res = fw.JOBS[job["kind"]](ctx, job)
        except ra.NonFiniteReply:
            assert obs is not None
            res = truncated_result(ctx, job, obs, ctx.last_proc_info, t_job)
    except mw.MismatchError as exc:
        return {"ok": False, "kind": "mismatch", "job_kind": job.get("kind"), "mismatch": exc.kind, "detail": exc.detail,
                "iteration": job.get("iteration"), "cell": job.get("cell"), "worker": ctx.rank}
    except mw.LifecycleFailure as exc:
        return {"ok": False, "kind": "lifecycle", "job_kind": job.get("kind"), "outcome": exc.outcome, "message": exc.message,
                "iteration": job.get("iteration"), "cell": job.get("cell"), "worker": ctx.rank}
    except mw.Aborted:
        return {"ok": False, "kind": "aborted", "job_kind": job.get("kind"), "worker": ctx.rank, "iteration": job.get("iteration"),
                "cell": job.get("cell")}
    except mcell.CellError as exc:
        return {"ok": False, "kind": "mismatch", "job_kind": job.get("kind"), "mismatch": "cell_contract", "detail": {"message": str(exc)},
                "iteration": job.get("iteration"), "cell": job.get("cell"), "worker": ctx.rank}
    except Exception as exc:  # noqa: BLE001 - structured, surfaced by the runner as an error stop
        return {"ok": False, "kind": "error", "job_kind": job.get("kind"), "error": f"{type(exc).__name__}: {exc}",
                "trace": traceback.format_exc()[-3000:], "worker": ctx.rank, "iteration": job.get("iteration"), "cell": job.get("cell")}
    finally:
        ctx.backend.observer = None
        ctx.observer = None
    if obs is not None and res.get("ok"):
        res["glitch"] = obs.glitch()
        res["run3_worker_contract"] = RUN3_WORKER_CONTRACT
        if selfcheck and res.get("end_reason") != "nonfinite":
            res["run3_selfcheck"] = obs.selfcheck(res, ctx.clf)
    return res


class _ProcInfoBackend(ObservedBackend):
    """Also remembers the identity of the last process handed out (mode, startup, pid) for a truncated result."""

    def __init__(self, backend: Any, ctx_holder: Dict[str, Any]):
        super().__init__(backend)
        self._holder = ctx_holder

    def acquire(self, *args: Any, **kwargs: Any) -> ObservedProc:
        p = super().acquire(*args, **kwargs)
        ctx = self._holder.get("ctx")
        if ctx is not None:
            ctx.last_proc_info = {"mode": getattr(p, "mode", None), "startup": getattr(p, "startup", None), "pid": getattr(p, "pid", None)}
        return p


# -- the worker process -----------------------------------------------------------------------------------------------------------------------


def worker_main(conn: Any, spec: Mapping[str, Any], abort: Any) -> None:
    """rl/frs_worker.worker_main with the proxy, the decision recorder and this module's run_job (protocol unchanged)."""
    if spec.get("guard"):
        g.LabGuard.install_from_spec(spec["guard"])
    backend = None
    state = {"stop": False}
    holder: Dict[str, Any] = {}

    def ask(payload: Dict[str, Any]) -> Optional[bool]:
        t0 = time.perf_counter()
        conn.send(("boundary", payload))
        deadline = time.monotonic() + float(spec.get("answer_timeout_s", fw.ANSWER_TIMEOUT_S))
        go: Optional[bool] = None
        while True:
            if abort is not None and abort.is_set():
                raise mw.Aborted("session abort during a boundary")
            if conn.poll(0.2):
                msg = conn.recv()
                if msg[0] == "continue":
                    a = msg[1]
                    if int(a.get("iteration", -1)) == int(payload["iteration"]) and int(a.get("segment", -1)) == int(payload["segment"]):
                        go = bool(a.get("go"))
                        break
                    continue
                if msg[0] == "stop":
                    state["stop"] = True
                    raise mw.Aborted("stop during a boundary")
                continue
            if time.monotonic() > deadline:
                break
        ctx = holder.get("ctx")
        if ctx is not None and getattr(ctx, "observer", None) is not None:
            ctx.observer.on_decision(payload, go, time.perf_counter() - t0)
        return go

    try:
        classifier = mcell.Classifier()
        backend = _ProcInfoBackend(mw.make_backend(spec), holder)
        failure_dir = Path(spec["failure_dir"]) if spec.get("failure_dir") else None
        ctx = fw.LabJobContext(backend, abort, classifier, int(spec["rank"]), failure_dir, ask)
        ctx.observer = None
        ctx.last_proc_info = {}
        holder["ctx"] = ctx
        geometry = ra.GeometryCache()
        selfcheck = bool(spec.get("run3_selfcheck"))
        conn.send(("ready", dict(backend.info(), contract=fw.FRS_WORKER_CONTRACT, run3_contract=RUN3_WORKER_CONTRACT)))
        while not state["stop"]:
            msg = conn.recv()
            if msg[0] == "stop":
                break
            if msg[0] == "report":
                conn.send(("report", {"guard_violations": list(g.LabGuard.violations), "backend": getattr(backend, "report", lambda: {})()}))
                continue
            if msg[0] == "job":
                res = run_job(ctx, msg[1], geometry, selfcheck)
                res["guard_violations"] = list(g.LabGuard.violations)
                res["provenance_violations"] = list(mw.ProvenanceGuard.violations)
                conn.send(("result", res))
    except (EOFError, BrokenPipeError):
        pass
    except BaseException as exc:  # noqa: BLE001
        try:
            conn.send(("fatal", {"error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-3000:]}))
        except (OSError, BrokenPipeError):
            pass
    finally:
        if backend is not None:
            try:
                backend.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            conn.close()
        except OSError:
            pass


class Run3Pool(fr.FrsPool):
    """rl/frs_run.FrsPool starting this module's worker_main (everything else inherited)."""

    def start(self, n: int, timeout: float = 180.0) -> None:
        for rank in range(n):
            parent, child = self.ctx.Pipe(duplex=True)
            spec = self.env.worker_spec(rank, self.cfg)
            p = self.ctx.Process(target=worker_main, args=(child, spec, self.abort), name=f"run3-w{rank:02d}", daemon=True)
            p.start()
            child.close()
            self.procs.append(p)
            self.conns.append(parent)
        deadline = self.env.now() + timeout
        pending = set(range(n))
        self.infos = [{} for _ in range(n)]
        while pending:
            if self.env.now() > deadline:
                raise fr.mrun.CapStop(f"workers {sorted(pending)} not ready after {timeout:.0f} s")
            for i in list(pending):
                if self.conns[i].poll(0.1):
                    kind, payload = self.conns[i].recv()
                    if kind != "ready":
                        raise fr.mrun.CapStop(f"worker {i} failed to start: {payload}")
                    self.infos[i] = payload
                    pending.discard(i)
                elif not self.procs[i].is_alive():
                    raise fr.mrun.CapStop(f"worker {i} died during start (exit code {self.procs[i].exitcode})")
