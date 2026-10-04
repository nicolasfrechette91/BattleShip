"""M9-g1 worker: one process slot (a cold-launched BattleShip, a staged start, a stepped episode) behind a command protocol.

A slot owns AT MOST ONE BattleShip process at a time and never reuses one: every start is a fresh process (the restart is the reset). The
worker core is a plain command handler, so the same code runs in a spawned worker process (a pipe loop) and in the in-process lock-step pool of
the tests (m9_pool.LocalPool).

    ("stage", {episode, lineage, tau})   launch, check the non-consuming tick-0 record against the pin, replay prefix words 0..tau-1 one `step`
                                         per tick, checking EVERY tick (consumed tick, input tick, record chain digest, v3 observation digest)
                                         against the registered tables of the lineage, park at input tick tau
                                         -> ("staged", {obs, tau, mask, targets_remaining, ...}) | ("stage_failed", {kind, ...})
    ("step", {word})                     one Track 1 word = exactly one native tick; the reply carries the v3 observation, the reward inputs and,
                                         on a native end, a fall or the horizon, the finalised episode (`final`): the process is closed
                                         -> ("stepped", {...}) | ("step_failed", {kind, ...})
    ("close", {})                        close a parked or active episode without finishing it -> ("closed", {...})
    ("report",) / ("stop",)

Integrity failures (any tick-0 / prefix / tick-contract mismatch) are `kind: mismatch` (the session is INVALID); a process death or timeout is
`kind: lifecycle` (recorded, the start is redrawn, at most three per phase). Native gameplay is authoritative; no hidden action, no savestate,
no native RNG. The backend is injectable (`spec["backend"] = "module:Class"`) for the synthetic world.
"""
from __future__ import annotations

import hashlib
import importlib
import os
import sys
import time
import traceback
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Mapping, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import m8_rd_cells as mcell  # noqa: E402
import m8_rd_worker as mw  # noqa: E402
import m9_artifacts as A  # noqa: E402
import m9_contract as C  # noqa: E402
import m9_lineages as L  # noqa: E402

WORKER_CONTRACT = "m9_worker_v1"
ABORT_POLL_TICKS = 16
TAIL_REPLIES = 48                        # raw replies kept for the evidence of a mismatch (a ring: staging never holds a whole prefix)
STATUS_FLAG_KEYS = {"SSB64_RL_ENTITY": "entity_diag", "SSB64_RL_TARGET_DIAG": "target_diag", "SSB64_RL_INPUT": "input_diag"}

MismatchError = mw.MismatchError
LifecycleFailure = mw.LifecycleFailure
Aborted = mw.Aborted


# -- the cold backend: no standby (a staging slot boots its own process) -----------------------------------------------------------------


class ColdBackend(mw.RealBackend):
    """rl/m8_rd_worker.RealBackend's launch machinery (frozen configuration, executable pin, port blocks, readiness proof, evidence of failed
    launches) with the standby removed: `acquire()` always cold-launches. RealBackend itself is used unchanged by P1's promoted replay."""

    def __init__(self, spec: Mapping[str, Any]):                 # noqa: D107 - replicates RealBackend.__init__ minus the standby
        import threading

        from m7_runtime import PortCandidates

        self.spec = dict(spec)
        self.rank = int(spec["rank"])
        self.root = Path(spec["root"])
        self.executable = Path(spec["executable"])
        self.flags = dict(spec["flags"])
        self.frozen = mw.FrozenRuntime(Path(spec["frozen_dir"]), spec["frozen_sha256"])
        self.exe_pin: Dict[str, str] = {}
        if spec.get("exe_sha256"):
            self.exe_pin[str(self.executable)] = str(spec["exe_sha256"])
            for n, h in (spec.get("runtime_sha256") or {}).items():
                self.exe_pin[str(self.executable.parent / n)] = str(h)
        self.runtime_root = self.root / "rt"
        self.episodes_root = self.root / "ep"
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self.episodes_root.mkdir(parents=True, exist_ok=True)
        self.timeouts = dict(startup=60.0, ready=180.0, request=30.0, exit=30.0)
        self.timeouts.update(spec.get("timeouts") or {})
        self.expected_flags = {mw.STATUS_FLAG_ENV[k]: v == "1" for k, v in self.flags.items() if k in mw.STATUS_FLAG_ENV}
        self.expected_flags.update({STATUS_FLAG_KEYS[k]: v == "1" for k, v in self.flags.items() if k in STATUS_FLAG_KEYS})
        self.ports = PortCandidates(self.rank, int(spec.get("port_base", 30000)), int(spec.get("port_size", 250)))
        self._lock = threading.Lock()
        self._gen = 0
        self._dirs: Dict[int, List[Tuple[str, str]]] = {}
        self.records: List[Dict[str, Any]] = []
        self.counts = {"cold": 0, "failed_attempts": 0}
        self.standby = None

    def acquire(self, wait_timeout: float = 0.0) -> Any:
        from battleship_process import EpisodeFailure

        t0 = time.perf_counter()
        attempts: List[Dict[str, Any]] = []
        ep, gen = None, None
        for attempt in range(1, 4):
            gen = self._next_gen()
            try:
                out = self._launch_episode(gen, attempt)
                ep = out.episode
                break
            except EpisodeFailure as exc:
                self.counts["failed_attempts"] += 1
                attempts.append({"attempt": attempt, "outcome": exc.outcome.value, "message": exc.message[:200]})
        if ep is None:
            raise LifecycleFailure("startup_failure", f"cold launch failed 3 times: {attempts}")
        self.counts["cold"] += 1
        startup = {"mode": "cold", "generation": gen, "attempts": attempts, "wait_s": round(time.perf_counter() - t0, 4)}
        return mw.RealProc(self, ep, gen, "cold", startup)

    def report(self) -> Dict[str, Any]:
        return {"counts": dict(self.counts)}

    def close(self) -> Dict[str, Any]:
        with self._lock:
            gens = list(self._dirs)
        for g in gens:
            self.cleanup_generation(g)
        return {"closed": True}


def make_backend(spec: Mapping[str, Any]) -> Any:
    target = spec.get("backend")
    if not target:
        return ColdBackend(spec)
    mod, _, cls = str(target).partition(":")
    return getattr(importlib.import_module(mod), cls)(spec)


def make_pipeline_cls(spec: Mapping[str, Any]) -> Any:
    target = spec.get("obs_pipeline")
    if not target:
        import m9_obs

        return m9_obs.V3Pipeline
    mod, _, cls = str(target).partition(":")
    return getattr(importlib.import_module(mod), cls)


# -- one episode ---------------------------------------------------------------------------------------------------------------------------


class Ep:
    """The state of the episode a slot currently holds (parked at tau, or active)."""

    def __init__(self, proc: Any, pipe: Any, scanner: Any, chain: bytes, tau: int, label: Any):
        self.proc, self.pipe, self.scanner, self.chain = proc, pipe, scanner, chain
        self.tau, self.j, self.label = int(tau), int(tau), label
        self.t0 = time.perf_counter()
        self.native_s = 0.0
        self.build_s = 0.0
        self.last_obs: Optional[Mapping[str, Any]] = None
        self.last_state = mcell.STATE_WAITING
        self.finished = False


class WorkerCore:
    def __init__(self, spec: Mapping[str, Any], backend: Any, abort: Any = None):
        self.spec = dict(spec)
        self.rank = int(spec["rank"])
        self.backend = backend
        self.abort = abort
        self.pin: Optional[Mapping[str, Any]] = spec.get("pin_tick0")
        self.pipeline_cls = make_pipeline_cls(spec)
        self.tables: Optional[Dict[str, L.Tables]] = None
        self.failure_dir = Path(spec["failure_dir"]) if spec.get("failure_dir") else None
        self.ep: Optional[Ep] = None
        self.tail: Deque[Mapping[str, Any]] = deque(maxlen=TAIL_REPLIES)
        self.stats = {"staged": 0, "stage_failed": 0, "episodes": 0, "native_ticks": 0}

    # -- tables ---------------------------------------------------------------------------------------------------------------------

    def _tables(self) -> Dict[str, L.Tables]:
        if self.tables is None:
            self.tables = L.load_all_tables(Path(self.spec["lineage_dir"]), list(self.spec["lineages"]))
        return self.tables

    # -- helpers --------------------------------------------------------------------------------------------------------------------

    def _check_abort(self, i: int) -> None:
        if i % ABORT_POLL_TICKS == 0 and self.abort is not None and self.abort.is_set():
            raise Aborted("session abort")

    def _step(self, proc: Any, i: int, word: int) -> Tuple[Mapping[str, Any], Mapping[str, Any], float]:
        b, x, y = mcell.TRIPLES[int(word)]
        t0 = time.perf_counter()
        rep = proc.step(b, x, y)
        dt = time.perf_counter() - t0
        self.tail.append(rep)
        o = rep.get("observation")
        if rep.get("ok") is not True or rep.get("op") != "step" or not isinstance(o, dict) or "spatial" not in rep:
            raise MismatchError("bad_reply", {"tick": i, "keys": sorted(rep)[:20]})
        if rep["consumed_tick"] != i or o["input_tick"] != i + 1 or rep["step_count"] != i + 1:
            raise MismatchError("consumed_tick", {"tick": i, "consumed_tick": rep["consumed_tick"], "input_tick": o["input_tick"], "step_count": rep["step_count"]})
        return rep, o, dt

    def _preserve(self, kind: str, job: Mapping[str, Any], exc: MismatchError) -> Optional[str]:
        if self.failure_dir is None:
            return None
        try:
            name = f"{kind}_{job.get('episode', 'x')}_w{self.rank:02d}.json.gz"
            A.write_json_gz(self.failure_dir / name, A.stamp({"kind": exc.kind, "detail": exc.detail, "job": dict(job), "worker": self.rank,
                                                              "last_replies": list(self.tail)}))
            return str(self.failure_dir / name)
        except (OSError, A.ArtifactError):
            return None

    def _release(self) -> None:
        ep = self.ep
        self.ep = None
        if ep is not None and ep.proc is not None:
            try:
                ep.proc.close()
            except Exception:                                     # noqa: BLE001 - cleanup never raises into the protocol
                pass

    # -- stage ----------------------------------------------------------------------------------------------------------------------

    def stage(self, job: Mapping[str, Any]) -> Tuple[str, Dict[str, Any]]:
        if self.ep is not None:
            self._release()
        tabs = self._tables()
        name, tau = str(job["lineage"]), int(job["tau"])
        tb = tabs[name]
        if not 0 <= tau <= len(tb.words) - C.MIN_WORDS_AFTER_START:
            raise MismatchError("bad_start", {"lineage": name, "tau": tau, "words": len(tb.words)})
        self.tail.clear()
        t_job = time.perf_counter()
        proc = self.backend.acquire()
        boot_s = time.perf_counter() - t_job
        try:
            if self.abort is not None and self.abort.is_set():
                raise Aborted("session abort")
            reply0, _rec0, _rd0, chain, tick0 = mw._tick0(proc, self.pin)
            if chain != tb.chain[0]:
                raise MismatchError("tick0_chain", {"chain": chain.hex(), "registered": tb.chain[0].hex()})
            pipe = self.pipeline_cls(reply0)
            if bytes.fromhex(pipe.digest()) != tb.v3[0]:
                raise MismatchError("tick0_v3", {"digest": pipe.digest(), "registered": tb.v3[0].hex()})
            mask = int(reply0["spatial"]["target_live_mask"])
            native_s = build_s = 0.0
            o = reply0["observation"]
            for i in range(tau):
                self._check_abort(i)
                rep, o, dt = self._step(proc, i, tb.words[i])
                native_s += dt
                if rep["state"] != mcell.STATE_WAITING or mcell.is_native_failure(o, rep["state"]):
                    raise MismatchError("prefix_ended", {"tick": i, "state": rep.get("state_name"), "game_status": o["game_status"]})
                chain = mcell.chain_next(chain, mcell.record_digest(mcell.record_of(rep)))
                if chain != tb.chain[i + 1]:
                    raise MismatchError("prefix_chain", {"tick": i + 1, "chain": chain.hex(), "registered": tb.chain[i + 1].hex()})
                t1 = time.perf_counter()
                pipe.feed(rep)
                if bytes.fromhex(pipe.digest()) != tb.v3[i + 1]:
                    raise MismatchError("prefix_v3", {"tick": i + 1, "digest": pipe.digest(), "registered": tb.v3[i + 1].hex()})
                build_s += time.perf_counter() - t1
                mask = int(rep["spatial"]["target_live_mask"])
            ep = Ep(proc, pipe, mcell.BurstScanner(mask), chain, tau, job.get("label"))
            ep.native_s, ep.build_s, ep.last_obs = native_s, build_s, o
            self.ep = ep
            self.stats["staged"] += 1
            self.stats["native_ticks"] += tau
            return "staged", {"ok": True, "episode": job["episode"], "lineage": name, "tau": tau, "obs": pipe.arrays(), "mask": mask,
                              "targets_remaining": int(o["targets_remaining"]), "input_tick": int(o["input_tick"]), "handover_chain": chain.hex(),
                              "handover_v3": pipe.digest(), "mode": proc.mode, "startup": proc.startup, "pid": proc.pid, "worker": self.rank,
                              "boot_s": round(boot_s, 3), "native_s": round(native_s, 3), "build_s": round(build_s, 3),
                              "wall_s": round(time.perf_counter() - t_job, 3), "ticks": tau, "tick0": tick0,
                              "first_obs_tuple": list(mcell.obs_tuple(o))}
        except BaseException:
            try:
                proc.failed = True
            except Exception:                                     # noqa: BLE001
                pass
            try:
                proc.close()
            except Exception:                                     # noqa: BLE001
                pass
            raise

    # -- step -----------------------------------------------------------------------------------------------------------------------

    def step(self, job: Mapping[str, Any]) -> Tuple[str, Dict[str, Any]]:
        ep = self.ep
        if ep is None or ep.finished:
            raise MismatchError("no_episode", {"worker": self.rank})
        word, i = int(job["word"]), ep.j
        rep, o, dt = self._step(ep.proc, i, word)
        ep.native_s += dt
        j = i + 1
        rd = mcell.record_digest(mcell.record_of(rep))
        ep.chain = mcell.chain_next(ep.chain, rd)
        sp = rep["spatial"]
        ep.scanner.feed(j, o, sp, rep["state"])
        t1 = time.perf_counter()
        ep.pipe.feed(rep)
        ep.build_s += time.perf_counter() - t1
        ep.j = j
        ep.last_obs = o
        state = rep["state"]
        ended = state == mcell.STATE_ENDED
        fell = mcell.is_native_failure(o, state)
        clear = ended and int(o["btt_active"]) == 1 and int(o["targets_remaining"]) == 0
        end: Optional[str] = None
        if ended:
            end = "clear" if clear else "ended"
        elif fell:
            end = "fall"
        elif j >= C.HORIZON:
            end = "horizon"
        out: Dict[str, Any] = {"ok": True, "obs": ep.pipe.arrays(), "record_digest": rd.hex(), "j": j, "consumed_tick": int(rep["consumed_tick"]), "end": end, "clear": bool(clear),
                               "ended": ended, "fell": fell, "targets_remaining": int(o["targets_remaining"]), "btt_active": int(o["btt_active"]),
                               "position": [float(o["position_x"]), float(o["position_y"])], "worker": self.rank, "final": None}
        if end is not None:
            out["final"] = self._finalise(ep, rep, end, ended)
        self.stats["native_ticks"] += 1
        return "stepped", out

    def _finalise(self, ep: Ep, rep: Mapping[str, Any], end: str, ended: bool) -> Dict[str, Any]:
        info = mw._finish_proc(ep.proc, rep if ended else None, ended)
        ep.finished = True
        try:
            action = ep.proc.close()
        except Exception as exc:                                   # noqa: BLE001
            action = f"close_error: {exc}"
        self.ep = None
        self.stats["episodes"] += 1
        labels = ep.scanner.labels()
        b = getattr(ep.pipe, "builder", None)
        return {"end_reason": end, "ticks": ep.j, "tau": ep.tau, "policy_ticks": ep.j - ep.tau, "chain_final": ep.chain.hex(),
                "end_obs": list(mcell.obs_tuple(ep.last_obs)) if ep.last_obs is not None else None, "breaks": [list(x) for x in ep.scanner.breaks],
                "labels": {"t": labels["t"], "t_events": [list(x) for x in labels["t_events"]], "first": labels["first"]},
                "result": info.get("result"), "exit_code": info.get("exit_code"), "finish_error": info.get("finish_error"), "close": action,
                "native_s": round(ep.native_s, 3), "build_s": round(ep.build_s, 3), "wall_s": round(time.perf_counter() - ep.t0, 3),
                "stale_builds": int(getattr(b, "stale_builds", 0)), "projectile_overflow": int(getattr(b, "projectile_overflow", 0)), "mode": ep.proc.mode,
                "pid": ep.proc.pid}

    def close(self, job: Mapping[str, Any]) -> Tuple[str, Dict[str, Any]]:
        had = self.ep is not None
        self._release()
        return "closed", {"ok": True, "had_episode": had, "worker": self.rank}

    # -- dispatch -------------------------------------------------------------------------------------------------------------------

    def handle(self, msg: Tuple[Any, ...]) -> Tuple[str, Dict[str, Any]]:
        """One command -> one structured reply; never raises."""
        cmd = msg[0]
        job: Mapping[str, Any] = msg[1] if len(msg) > 1 else {}
        fail_kind = {"stage": "stage_failed", "step": "step_failed"}.get(cmd, "closed")
        try:
            if cmd == "stage":
                return self.stage(job)
            if cmd == "step":
                return self.step(job)
            if cmd == "close":
                return self.close(job)
            if cmd == "report":
                return "report", {"stats": dict(self.stats), "backend": getattr(self.backend, "report", lambda: {})(),
                                  "provenance_violations": list(mw.ProvenanceGuard.violations), "worker": self.rank}
            return "error", {"ok": False, "error": f"unknown command {cmd!r}", "worker": self.rank}
        except MismatchError as exc:
            self.stats["stage_failed"] += int(cmd == "stage")
            self._release()
            return fail_kind, {"ok": False, "kind": "mismatch", "mismatch": exc.kind, "detail": exc.detail, "worker": self.rank,
                               "episode": job.get("episode"), "preserved": self._preserve(cmd, job, exc)}
        except mcell.CellError as exc:
            self.stats["stage_failed"] += int(cmd == "stage")
            self._release()
            return fail_kind, {"ok": False, "kind": "mismatch", "mismatch": "cell_contract", "detail": {"message": str(exc)}, "worker": self.rank,
                               "episode": job.get("episode"), "preserved": None}
        except LifecycleFailure as exc:
            self.stats["stage_failed"] += int(cmd == "stage")
            self._release()
            return fail_kind, {"ok": False, "kind": "lifecycle", "outcome": exc.outcome, "message": exc.message, "worker": self.rank, "episode": job.get("episode")}
        except Aborted:
            self._release()
            return fail_kind, {"ok": False, "kind": "aborted", "worker": self.rank, "episode": job.get("episode")}
        except Exception as exc:                                  # noqa: BLE001 - structured, surfaced by the session as an error stop
            self._release()
            return fail_kind, {"ok": False, "kind": "error", "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-3000:],
                               "worker": self.rank, "episode": job.get("episode")}

    def shutdown(self) -> None:
        self._release()
        try:
            self.backend.close()
        except Exception:                                         # noqa: BLE001
            pass


# -- the worker process --------------------------------------------------------------------------------------------------------------


def worker_main(conn: Any, spec: Mapping[str, Any], abort: Any) -> None:
    """Entry point of one spawned slot worker. Protocol: (cmd, job) -> (kind, payload); ("stop",) exits."""
    import m8_rd2_worker as w2

    sys.dont_write_bytecode = True                    # modules imported later by this worker never write a .pyc under the write-protected rl/
    mw.ProvenanceGuard.install()
    if spec.get("protected_roots"):
        w2.WriteGuard.install(spec["protected_roots"])
    core: Optional[WorkerCore] = None
    try:
        backend = make_backend(spec)
        core = WorkerCore(spec, backend, abort)
        conn.send(("ready", dict(backend.info() if hasattr(backend, "info") else {}, contract=WORKER_CONTRACT, pid=os.getpid())))
        while True:
            msg = conn.recv()
            if msg[0] == "stop":
                break
            kind, payload = core.handle(msg)
            payload["provenance_violations"] = list(mw.ProvenanceGuard.violations)
            conn.send((kind, payload))
    except (EOFError, BrokenPipeError):
        pass
    except BaseException as exc:                                   # noqa: BLE001
        try:
            conn.send(("fatal", {"error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-3000:]}))
        except (OSError, BrokenPipeError):
            pass
    finally:
        if core is not None:
            core.shutdown()
        try:
            conn.close()
        except OSError:
            pass
