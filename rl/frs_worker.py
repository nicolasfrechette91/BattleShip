"""Fast-route lab (frs) worker: the `iterate_frs` job (rd1's `iterate` plus in-process burst continuation) and the worker loop.

`iterate_frs` follows `m8_rd_worker.run_iterate` step for step (its helpers `_tick0`, `_step`, `_finish_proc`, `_stamp`, `_preserve` and the
cell / chain / scanner code are imported, never edited): return to a cell by replaying its words (tick-0 pin, consumed tick of every word, the
cell's end record and chain at L), then explore the keyed stream of `m8_rd_explore_v1`. The burst is the first n words of

    words(explore_key(<lab draw id>, <iteration>, .), min(segment_words * max_segments, horizon - L, allowance - L))

At each segment boundary (n a multiple of segment_words, the episode still live) the worker sends the reaches of the last `window` words to
the main process and waits for its answer: continue = keep stepping THE SAME PROCESS (one longer episode; every step still checks
consumed_tick == i, input_tick == i + 1 and step_count == i + 1; no reset, no savestate). With max_segments = 1 nothing is asked and the
result equals `run_iterate`'s (tested). The whole job is returned, and ingested, as one burst. Light top-level imports only (spawned workers
re-import the main module). Design: logs/frs_prep/phase1_plan.md sections 3 and 4.

Fused first dispatch (run 3 only, 2026-11-05; SESSION_LOG_2026-11-04.md section 13): a job with `end_mode` == FUSED_END_MODE carries no end
record (`end` None) because none is on disk for the cell. At L the record digest and the chain are compared as always; the tuple comparison
is skipped (it compares 16 of the 17 fields, host_frame ignored; the record digest covers those 16, value and JSON type, tested field by
field in tools/frs/run3_search_tests.py) and the observed 17-field tuple is returned in `prefix["end"]` for the engine to store. A
difference is the same `prefix_end` mismatch, raised before any burst word. A job without `end_mode` (every run 1 and run 2 job) takes the
unchanged path.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import frs_guard as g  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_explore as mx  # noqa: E402
import m8_rd_worker as mw  # noqa: E402

FRS_WORKER_CONTRACT = "frs_worker_v1"
EXPLORE_CONT_CONTRACT = "frs_explore_cont_v1"
JOB_KIND = "iterate_frs"
ANSWER_TIMEOUT_S = 60.0
FUSED_END_MODE = "fused_first_dispatch_v1"


def fused_prefix(end_t: Tuple[Any, ...]) -> Dict[str, Any]:
    """The prefix fields of a fused first dispatch whose record digest and chain matched: the tuple was not compared (nothing stored to compare
    with), so end_equal and host_frame_equal are None; `end` is the observed end record."""
    return {"end_mode": FUSED_END_MODE, "end_equal": None, "chain_equal": True, "end_digest_equal": True, "host_frame_equal": None,
            "end": list(end_t)}


def explore_description(segment_words: int, max_segments: int, window: int) -> Dict[str, Any]:
    return {"contract": EXPLORE_CONT_CONTRACT, "base": mx.EXPLORE_CONTRACT, "base_digest": mx.contract_digest(),
            "segment_words": int(segment_words), "max_segments": int(max_segments), "window_words": int(window),
            "burst": "the first n words of words(explore_key(<lab draw id>, <iteration>, .), min(segment_words * max_segments, horizon - L, "
                     "allowance - L)); n is a multiple of segment_words unless the episode ended, fell, reached the horizon or was cut",
            "trigger": "at a segment boundary: continue iff a reach (first visit of its key in the job) of the last window_words words has a key "
                       "new to the archive or a tick strictly below the incumbent's L; doom is assigned at ingest, where the job is one burst",
            "process": "a continued job is one longer episode in the same process (no reset, no savestate); the next job is a new process"}


def explore_digest(desc: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(desc, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


class LabJobContext(mw.JobContext):
    """rd1's job context plus the boundary question (`ask`: payload -> True / False / None for no answer)."""

    def __init__(self, backend: Any, abort: Any, classifier: Any, rank: int, failure_dir: Optional[Path],
                 ask: Optional[Callable[[Dict[str, Any]], Optional[bool]]] = None):
        super().__init__(backend, abort, classifier, rank, failure_dir)
        self.ask_fn = ask

    def ask(self, payload: Dict[str, Any]) -> Optional[bool]:
        if self.ask_fn is None:
            return False
        return self.ask_fn(payload)


def run_iterate_frs(ctx: LabJobContext, job: Mapping[str, Any]) -> Dict[str, Any]:
    """Return to a cell (replay its words, checks at tick 0 and at L) and explore a keyed burst of one or more segments from it."""
    t_job = time.perf_counter()
    words: bytes = bytes(job["words"])
    L = len(words)
    allowance = int(job["allowance"])
    seg, max_seg, window = int(job["segment_words"]), int(job["max_segments"]), int(job["window"])
    if seg < 1 or max_seg < 1 or window < 1:
        raise mw.WorkerError(f"bad segment parameters {seg} / {max_seg} / {window}")
    fused = job.get("end_mode") == FUSED_END_MODE
    if job.get("end_mode") not in (None, FUSED_END_MODE) or (fused and (job.get("end") is not None or L == 0)):
        raise mw.WorkerError(f"bad end mode {job.get('end_mode')!r}: a fused first dispatch has L > 0 and no end record")
    stats = {"step_s": 0.0, "ask_s": 0.0}
    raw: List[Mapping[str, Any]] = []
    proc = ctx.backend.acquire()
    ended = False
    try:
        if ctx.abort is not None and ctx.abort.is_set():
            raise mw.Aborted("session abort")
        reply0, rec0, rd0, chain, tick0 = mw._tick0(proc, job["pin"])
        mask = int(reply0["spatial"]["target_live_mask"])
        prefix_breaks: List[Tuple[int, int]] = []
        n_pre = min(L, allowance)
        rep = o = sp = None
        rd = rd0
        expect_terminal = bool(job.get("terminal"))
        prefix_terminal = False
        for i in range(n_pre):
            mw._check_abort(ctx, i)
            rep, o, sp = mw._step(ctx, proc, i, words[i], raw, stats)
            rd = mcell.record_digest(mcell.record_of(rep))
            chain = mcell.chain_next(chain, rd)
            if rep["state"] != mcell.STATE_WAITING or mcell.is_native_failure(o, rep["state"]):
                if expect_terminal and i == L - 1:
                    prefix_terminal = True
                    ended = rep["state"] == mcell.STATE_ENDED
                else:
                    raise mw.MismatchError("prefix_ended", {"tick": i, "state": rep.get("state_name"), "game_status": o["game_status"],
                                                            "expected_terminal": expect_terminal})
            m = int(sp["target_live_mask"])
            if m != mask:
                for b in range(mcell.TARGETS_TOTAL):
                    if (mask & ~m) >> b & 1:
                        prefix_breaks.append((i + 1, b))
                mask = m
        res: Dict[str, Any] = {"ok": True, "kind": JOB_KIND, "iteration": job["iteration"], "cell": job["cell"], "rep": tuple(job["rep"]),
                               "L": L, "mode": proc.mode, "startup": proc.startup, "pid": proc.pid, "worker": ctx.rank, "tick0": tick0,
                               "result_json": None, "exit_code": None, "worker_contract": FRS_WORKER_CONTRACT, "decisions": [],
                               "segments": 0}
        if n_pre < L:
            res.update({"words": b"", "end_reason": "cut", "ticks": n_pre, "reaches": [], "labels": None, "breaks_all": [],
                        "t_end": mcell.level_of_mask(mask), "prefix": {"words": n_pre, "cut": True}})
            return mw._stamp(res, t_job, stats)
        prefix = {"words": L, "cut": False, "terminal": prefix_terminal}
        if expect_terminal and not prefix_terminal:
            raise mw.MismatchError("terminal_expected", {"cell": job["cell"], "L": L, "why": "the prefix did not end the episode"})
        if fused:
            chain_ok = chain == bytes(job["chain"])
            digest_ok = rd == bytes(job["end_digest"])
            if not chain_ok or not digest_ok:
                raise mw.MismatchError("prefix_end", {"cell": job["cell"], "L": L, "end_mode": FUSED_END_MODE, "field_diffs": None,
                                                      "chain_equal": chain_ok, "end_digest_equal": digest_ok})
            prefix.update(fused_prefix(mcell.obs_tuple(o)))
        elif L > 0:
            end_t = mcell.obs_tuple(o)
            diffs = mcell.obs_diffs(end_t, tuple(job["end"]))
            chain_ok = chain == bytes(job["chain"])
            digest_ok = rd == bytes(job["end_digest"])
            if diffs or not chain_ok or not digest_ok:
                raise mw.MismatchError("prefix_end", {"cell": job["cell"], "L": L, "field_diffs": {k: list(v) for k, v in diffs.items()},
                                                      "chain_equal": chain_ok, "end_digest_equal": digest_ok})
            prefix.update({"end_equal": True, "chain_equal": True, "end_digest_equal": True,
                           "host_frame_equal": end_t[mcell.HOST_FRAME] == job["end"][mcell.HOST_FRAME]})
        res["prefix"] = prefix
        total = 0 if prefix_terminal else max(0, min(seg * max_seg, mcell.HORIZON - L, allowance - L))
        scanner = mcell.BurstScanner(mask)
        burst = bytearray()
        reaches: List[Tuple[int, Tuple[Any, ...], Tuple[Any, ...], bytes, bytes, bool]] = []
        seen_keys: set = set()
        end_reason = None
        stopped_at_boundary = False
        decisions: List[Dict[str, Any]] = []
        archive_id, iteration = job["archive_id"], int(job["iteration"])
        for w in mx.words(lambda idx: mx.explore_key(archive_id, iteration, idx), total):
            i = L + len(burst)
            mw._check_abort(ctx, i)
            rep, o, sp = mw._step(ctx, proc, i, w, raw, stats)
            burst.append(w)
            j = i + 1
            rd = mcell.record_digest(mcell.record_of(rep))
            chain = mcell.chain_next(chain, rd)
            state = rep["state"]
            ended = state == mcell.STATE_ENDED
            fell = mcell.is_native_failure(o, state)
            key = mcell.cell_key(o, sp, ctx.clf)
            if key is not None and key not in seen_keys:
                seen_keys.add(key)
                reaches.append((j, key, mcell.obs_tuple(o), rd, chain, ended or fell))
            scanner.feed(j, o, sp, state)
            if ended or fell:
                end_reason = ("clear" if scanner.first["clear"] is not None else "ended") if ended else "fall"
                break
            if j >= mcell.HORIZON:
                end_reason = "horizon"
                break
            n = len(burst)
            if n % seg == 0 and n < total:
                lo = L + n - window
                payload = {"iteration": iteration, "cell": job["cell"], "segment": n // seg, "words": n, "L": L,
                           "reaches": [[rj, list(rk)] for rj, rk, *_r in reaches if rj > lo]}
                t_ask = time.perf_counter()
                go = ctx.ask(payload)
                stats["ask_s"] += time.perf_counter() - t_ask
                decisions.append({"segment": n // seg, "words": n, "in_window": len(payload["reaches"]), "go": bool(go), "answered": go is not None})
                if not go:
                    stopped_at_boundary = True
                    break
        if end_reason is None:
            end_reason = "length" if (stopped_at_boundary or len(burst) >= seg * max_seg) else "cut"
        info = mw._finish_proc(proc, rep if ended else None, ended)
        res.update({"words": bytes(burst), "end_reason": end_reason, "ticks": L + len(burst), "reaches": reaches,
                    "labels": scanner.labels(), "breaks_all": prefix_breaks + scanner.breaks, "t_end": scanner.t,
                    "result_json": info["result"], "exit_code": info["exit_code"], "finish_error": info.get("finish_error"),
                    "decisions": decisions, "segments": -(-len(burst) // seg) if burst else 0, "ask_s": round(stats["ask_s"], 4),
                    "final_chain": chain.hex()})
        return mw._stamp(res, t_job, stats)
    except mw.MismatchError as exc:
        proc.failed = True
        exc.detail["preserved"] = mw._preserve(ctx, job, raw, exc)
        raise
    finally:
        proc.close()


JOBS: Dict[str, Callable[[Any, Mapping[str, Any]], Dict[str, Any]]] = {"tick0": mw.run_tick0, JOB_KIND: run_iterate_frs}


def run_job(ctx: LabJobContext, job: Mapping[str, Any]) -> Dict[str, Any]:
    """One job; every outcome is a structured dict (ok / mismatch / lifecycle / aborted / error), never an exception (rd1's mapping)."""
    try:
        return JOBS[job["kind"]](ctx, job)
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


def worker_main(conn: Any, spec: Mapping[str, Any], abort: Any) -> None:
    """Entry point of one spawned lab worker. The lab guard is armed first. Protocol: ("job", dict) -> ("result", dict); during a job the
    worker may send ("boundary", payload) and waits for ("continue", {"iteration", "segment", "go"}); ("stop",) -> exits."""
    if spec.get("guard"):
        g.LabGuard.install_from_spec(spec["guard"])
    backend = None
    state = {"stop": False}

    def ask(payload: Dict[str, Any]) -> Optional[bool]:
        conn.send(("boundary", payload))
        deadline = time.monotonic() + float(spec.get("answer_timeout_s", ANSWER_TIMEOUT_S))
        while True:
            if abort is not None and abort.is_set():
                raise mw.Aborted("session abort during a boundary")
            if conn.poll(0.2):
                msg = conn.recv()
                if msg[0] == "continue":
                    a = msg[1]
                    if int(a.get("iteration", -1)) == int(payload["iteration"]) and int(a.get("segment", -1)) == int(payload["segment"]):
                        return bool(a.get("go"))
                    continue
                if msg[0] == "stop":
                    state["stop"] = True
                    raise mw.Aborted("stop during a boundary")
                continue
            if time.monotonic() > deadline:
                return None

    try:
        classifier = mcell.Classifier()
        backend = mw.make_backend(spec)
        failure_dir = Path(spec["failure_dir"]) if spec.get("failure_dir") else None
        ctx = LabJobContext(backend, abort, classifier, int(spec["rank"]), failure_dir, ask)
        conn.send(("ready", dict(backend.info(), contract=FRS_WORKER_CONTRACT)))
        while not state["stop"]:
            msg = conn.recv()
            if msg[0] == "stop":
                break
            if msg[0] == "report":
                conn.send(("report", {"guard_violations": list(g.LabGuard.violations), "backend": getattr(backend, "report", lambda: {})()}))
                continue
            if msg[0] == "job":
                res = run_job(ctx, msg[1])
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
