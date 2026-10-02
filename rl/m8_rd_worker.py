"""M8-rd worker: a lean native-process driver (no Gymnasium, no learning stack) on battleship_process / battleship_client /
m7_standby, plus the job functions every worker runs.

One worker process owns one BattleShip standby slot (m7_standby: the next process boots while the active one is stepped) and
runs jobs sent by the session over a pipe:

    tick0    pin / reproduce the tick-0 record (a non-consuming `observe`)
    iterate  return to an archive cell by replaying its words (checks against the pinned tick-0 record, the consumed tick of
             every word, the cell's end record and chain digest), then run a keyed explore burst; or only the return
    control  arm C: a keyed explore episode from a fresh process, no return
    trace    P1: replay pinned words and compare every reply's record digest with the pinned trace

Every native tick is exactly one `step` request, checked for consumed_tick == i and input_tick == i + 1. A process restart is
the only episode reset: one fresh process per job (standby promoted at tick 0, or a cold launch), closed after use. No hidden
action, no savestate, no native RNG. A lifecycle failure (process death, timeout) and an integrity failure (a mismatch or a
contract violation) are reported differently; an integrity failure preserves the job's raw replies.

The backend is injectable (`spec["backend"] = "module:Class"`) so the whole session can be exercised against a synthetic
native stand-in without a game.
"""
from __future__ import annotations

import gzip
import hashlib
import importlib
import json
import os
import shutil
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import m8_rd_cells as mcell  # noqa: E402
import m8_rd_explore as mx  # noqa: E402

WORKER_CONTRACT = "m8_rd_worker_v1"
STATUS_FLAG_ENV = {"SSB64_RL_NO_RENDER": "no_render", "SSB64_RAPHNET_DISABLE": "raphnet_disabled", "SSB64_RL_SPATIAL": "spatial_diag"}
FROZEN_FILES = ("BattleShip.cfg.json", "imgui.ini")
ABORT_POLL_TICKS = 16
FORBIDDEN_FRAGMENTS = ("rl/fixtures", "fixtures/m7g", "m7g/capture", "tas_input", "mario_743", ".btti")


class WorkerError(RuntimeError):
    pass


class MismatchError(WorkerError):
    """An integrity failure: a tick-0 / prefix / end / chain mismatch or a tick-contract violation. The session is INVALID."""

    def __init__(self, kind: str, detail: Mapping[str, Any]):
        super().__init__(f"{kind}: {json.dumps(detail, default=str)[:600]}")
        self.kind = kind
        self.detail = dict(detail)


class LifecycleFailure(WorkerError):
    """A process died, timed out or could not boot: not a mismatch. The iteration is recorded as failed and redrawn."""

    def __init__(self, outcome: str, message: str):
        super().__init__(f"{outcome}: {message}")
        self.outcome = outcome
        self.message = message


class Aborted(WorkerError):
    pass


# -- provenance guard: any open of a fixture / capture / TAS path is recorded (the session is INVALID) ------------------------


class ProvenanceGuard:
    violations: List[str] = []
    _installed = False

    @classmethod
    def install(cls) -> None:
        if cls._installed:
            return
        cls._installed = True
        sys.addaudithook(cls._hook)

    @classmethod
    def _hook(cls, event: str, args: Tuple[Any, ...]) -> None:
        if event != "open" or not args:
            return
        p = args[0]
        if isinstance(p, bytes):
            p = p.decode("utf-8", "replace")
        if not isinstance(p, (str, os.PathLike)):
            return
        s = str(p).replace("\\", "/").lower()
        for frag in FORBIDDEN_FRAGMENTS:
            if frag in s:
                cls.violations.append(s)
                return


# -- frozen runtime configuration ----------------------------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class FrozenRuntime:
    """The run's frozen BattleShip.cfg.json and imgui.ini (copied once at S0). Every launch replaces the private config copy
    that m7_runtime.prepare_worker_runtime made with the frozen copy and re-hashes both before the process starts, so no
    concurrent change of the user's live configuration can reach an archive run."""

    def __init__(self, directory: Path, expected: Mapping[str, str]):
        self.dir = Path(directory)
        self.expected = dict(expected)
        if set(self.expected) != set(FROZEN_FILES):
            raise WorkerError(f"frozen runtime must pin exactly {FROZEN_FILES}")

    def verify(self) -> None:
        for n, h in self.expected.items():
            if sha256_file(self.dir / n) != h:
                raise MismatchError("pin_drift", {"file": n, "dir": str(self.dir)})

    def install(self, runtime_dir: Path) -> Dict[str, str]:
        self.verify()
        out = {}
        for n, h in self.expected.items():
            dst = Path(runtime_dir) / n
            shutil.copyfile(self.dir / n, dst)
            got = sha256_file(dst)
            if got != h:
                raise MismatchError("pin_drift", {"file": n, "installed": got, "frozen": h})
            out[n] = got
        return out


def remove_tree_retry(path: Path, *, runtime: bool = False, attempts: int = 24, delay: float = 0.25) -> bool:
    """Remove a runtime or episode directory after its process is gone (Windows may hold files briefly)."""
    from m7_runtime import remove_worker_runtime

    path = Path(path)
    for _ in range(attempts):
        try:
            if not path.exists():
                return True
            if runtime:
                remove_worker_runtime(path)
            else:
                shutil.rmtree(path)
            return True
        except OSError:
            time.sleep(delay)
    return not path.exists()


# -- the real backend ----------------------------------------------------------------------------------------------------------


class RealProc:
    """One BattleShip process parked at tick 0 (promoted standby or cold launch)."""

    def __init__(self, backend: "RealBackend", episode: Any, generation: int, mode: str, startup: Dict[str, Any]):
        self.backend = backend
        self.ep = episode
        self.generation = generation
        self.mode = mode
        self.startup = startup
        self.pid = episode.pid
        self.closed = False
        self.failed = False          # set when the job on this process failed: its native log is kept as evidence

    def observe(self) -> Dict[str, Any]:
        from battleship_client import BattleShipError

        try:
            return self.ep.client.request("observe")
        except BattleShipError as exc:
            raise self._classify(exc)

    def step(self, buttons: int, stick_x: int, stick_y: int) -> Dict[str, Any]:
        from battleship_client import BattleShipError

        try:
            return self.ep.client.request("step", buttons=int(buttons), stick_x=int(stick_x), stick_y=int(stick_y))
        except BattleShipError as exc:
            raise self._classify(exc)

    def _classify(self, exc: Exception) -> Exception:
        from battleship_process import EpisodeOutcome

        self.failed = True
        fail = self.ep.classify_step_failure(exc)
        if fail.outcome == EpisodeOutcome.REQUEST_REJECTED:
            return MismatchError("request_rejected", {"detail": str(fail)[:500]})
        return LifecycleFailure(fail.outcome.value, fail.message)

    def finish(self, reply: Mapping[str, Any]) -> Dict[str, Any]:
        """After a terminal EpisodeEnded reply: wait for the native clean exit and load the result JSON."""
        from battleship_client import Observation, StepResult, StepState
        from battleship_process import EpisodeFailure

        sr = StepResult(state=StepState(reply["state"]), state_name=reply["state_name"], step_count=reply["step_count"],
                        consumed_tick=reply["consumed_tick"], observation=Observation.from_wire(reply["observation"]))
        try:
            done = self.ep.finish(sr)
        except EpisodeFailure as exc:
            raise LifecycleFailure(exc.outcome.value, exc.message)
        return {"exit_code": done.exit_code, "result": dict(done.result)}

    def close(self) -> str:
        if self.closed:
            return "already_closed"
        self.closed = True
        action = "close_error"
        try:
            action = self.ep.close()
        except Exception as exc:  # noqa: BLE001 - reported, never raised from cleanup
            action = f"cleanup_failure: {exc}"
        self.backend.cleanup_generation(self.generation, keep_episode=self.failed)
        return action


class RealBackend:
    def __init__(self, spec: Mapping[str, Any]):
        from battleship_process import EpisodeFailure
        from m7_runtime import PortCandidates
        from m7_standby import StandbyManager

        self.spec = dict(spec)
        self.rank = int(spec["rank"])
        self.root = Path(spec["root"])
        self.executable = Path(spec["executable"])
        self.flags = dict(spec["flags"])
        self.frozen = FrozenRuntime(Path(spec["frozen_dir"]), spec["frozen_sha256"])
        # the pinned executable and the read-only runtime files it resolves: re-hashed before EVERY launch, so a rebuild or an
        # asset change during a session is an integrity stop (pin drift), never a silently different process
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
        self.expected_flags = {STATUS_FLAG_ENV[k]: v == "1" for k, v in self.flags.items() if k in STATUS_FLAG_ENV}
        self.ports = PortCandidates(self.rank, int(spec.get("port_base", 30000)), int(spec.get("port_size", 250)))
        self._lock = threading.Lock()
        self._gen = 0
        self._dirs: Dict[int, List[Tuple[str, str]]] = {}
        self.records: List[Dict[str, Any]] = []
        self.counts = {"promoted": 0, "cold_fallback": 0, "failed_attempts": 0}
        self.standby = StandbyManager(rank=self.rank, launch_fn=self._standby_launch, startup_attempts=3,
                                      join_timeout=float(self.timeouts["request"]) + float(self.timeouts["exit"]) + 5.0,
                                      request_timeout=float(self.timeouts["request"]))
        self._launch_next_standby()

    # -- generations -----------------------------------------------------------------------------------------------------------

    def _next_gen(self) -> int:
        with self._lock:
            self._gen += 1
            return self._gen

    def _launch_next_standby(self) -> None:
        from m7_standby import StandbyState

        if self.standby.state == StandbyState.NO_STANDBY:
            self.standby.launch(self._next_gen(), profile={"flags": dict(self.flags)})

    def _claim_port(self) -> Tuple[int, List[int]]:
        with self._lock:
            return self.ports.claim()

    def _launch_episode(self, generation: int, attempt: int, manager: Any = None) -> Any:
        """One launch attempt: private runtime dir (+ frozen config), launch, boot, readiness proven by non-consuming requests."""
        from battleship_client import BattleShipError, Observation, Observe, StepState
        from battleship_process import BattleShipEpisode, EpisodeFailure, EpisodeOutcome, LaunchConfig
        from m7_runtime import prepare_worker_runtime
        from m7_standby import LaunchOutcome, verify_readiness

        for path, want in self.exe_pin.items():
            got = sha256_file(Path(path))
            if got != want:
                raise MismatchError("pin_drift", {"file": path, "sha256": got, "pinned": want})
        port, busy = self._claim_port()
        runtime = self.runtime_root / f"g{generation:04d}a{attempt}"
        last_exc: Optional[BaseException] = None
        for k in range(4):
            try:
                prepare_worker_runtime(runtime, self.executable)         # copies the live config; the frozen copy replaces it below
                last_exc = None
                break
            except OSError as exc:                                       # a sharing violation on a file another program holds
                last_exc = exc
                remove_tree_retry(runtime, runtime=True)
                time.sleep(0.4 * (k + 1))
        if last_exc is not None:
            raise EpisodeFailure(EpisodeOutcome.STARTUP_FAILURE, f"cannot prepare the worker runtime: {last_exc}")
        with self._lock:
            self._dirs.setdefault(generation, []).append((str(runtime), ""))
        installed = self.frozen.install(runtime)
        cfg = LaunchConfig(executable=self.executable, working_dir=runtime, run_root=self.episodes_root, port=port,
                           startup_timeout=self.timeouts["startup"], ready_timeout=self.timeouts["ready"],
                           request_timeout=self.timeouts["request"], exit_timeout=self.timeouts["exit"],
                           extra_env=dict(self.flags))
        ep = BattleShipEpisode(cfg, index=generation)
        ep.m8_busy_ports = busy  # type: ignore[attr-defined]
        try:
            ep.launch()
            if manager is not None:
                manager.note_inflight(ep.process, ep.pid, port)
            if ep.paths is not None:
                with self._lock:
                    self._dirs.setdefault(generation, []).append(("", str(ep.paths.directory)))
            ep.wait_for_transport()
            ep.wait_for_fresh_episode()
            try:
                raw = ep.client.request("observe")
                status = ep.client.request("status")
            except BattleShipError as exc:
                raise ep.classify_step_failure(exc) from exc
            ob = Observe(state=StepState(raw["state"]), state_name=raw["state_name"], can_step=bool(raw["can_step"]),
                         step_count=raw["step_count"], observation=Observation.from_wire(raw["observation"]))
            flags = {k: status.get(k) for k in self.expected_flags}
            proof = verify_readiness(ob, flags, self.expected_flags, mcell.TARGETS_TOTAL)
            ep.m8_frozen_hashes = installed  # type: ignore[attr-defined]
            return LaunchOutcome(episode=ep, observe=ob, proof=proof, runtime_dir=str(runtime))
        except EpisodeFailure as exc:
            try:
                ep.close()
            except EpisodeFailure:
                pass
            exc.diagnostics.update({"port": port, "busy_ports_skipped": busy, "runtime_dir": str(runtime)})
            remove_tree_retry(runtime, runtime=True)          # the failed attempt's episode directory (its log) is kept as evidence
            raise
        except BaseException:
            try:
                ep.close()
            except Exception:  # noqa: BLE001
                pass
            remove_tree_retry(runtime, runtime=True)
            raise

    def _standby_launch(self, generation: int, attempt: int, manager: Any) -> Any:
        return self._launch_episode(generation, attempt, manager)

    def cleanup_generation(self, generation: int, keep: bool = False, keep_episode: bool = False) -> None:
        """Remove a generation's runtime directory and, unless `keep_episode`, its episode directory (the native log of a failed
        process is kept as evidence)."""
        with self._lock:
            dirs = self._dirs.pop(generation, [])
        if keep:
            return
        for runtime, episode in dirs:
            if runtime:
                remove_tree_retry(Path(runtime), runtime=True)
            if episode and not keep_episode:
                remove_tree_retry(Path(episode))

    # -- acquisition -------------------------------------------------------------------------------------------------------------

    def acquire(self, wait_timeout: float = 120.0) -> RealProc:
        from battleship_process import EpisodeFailure

        t0 = time.perf_counter()
        got = self.standby.acquire(wait_timeout, targets_total=mcell.TARGETS_TOTAL)
        if got.kind == "ready":
            rec = got.record
            ep = rec.episode
            self.standby.promoted(None)
            self.counts["promoted"] += 1
            startup = {"mode": "standby_promoted", "generation": rec.generation, "standby_startup_s": rec.startup_s,
                       "ready_before_promotion_s": rec.ready_before_promotion_s, "wait_s": round(got.waited_s, 4)}
            gen = rec.generation
        else:
            if got.kind == "starting_error":
                err = got.record.error if got.record else None
                if err and "MismatchError" in err and "pin_drift" in err:
                    raise MismatchError("pin_drift", {"standby_error": err[:600]})
                raise WorkerError(f"standby launcher raised unexpectedly: {err}")
            attempts = []
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
                self._launch_next_standby()
                raise LifecycleFailure("startup_failure", f"cold launch failed 3 times: {attempts}")
            self.counts["cold_fallback"] += 1
            startup = {"mode": "cold_fallback", "reason": got.kind, "generation": gen, "attempts": attempts,
                       "wait_s": round(time.perf_counter() - t0, 4)}
        self._launch_next_standby()
        return RealProc(self, ep, gen, startup["mode"], startup)

    def info(self) -> Dict[str, Any]:
        return {"pid": os.getpid(), "rank": self.rank, "backend": "real", "executable": str(self.executable)}

    def report(self) -> Dict[str, Any]:
        r = self.standby.report()
        return {"counts": dict(self.counts), "standby": {k: r[k] for k in ("counts", "startup_s", "exposed_wait_s",
                                                                          "ready_before_promotion_s")}}

    def close(self) -> Dict[str, Any]:
        out = self.standby.close()
        with self._lock:
            gens = list(self._dirs)
        for g in gens:
            self.cleanup_generation(g)
        return out


# -- job machinery -------------------------------------------------------------------------------------------------------------


class JobContext:
    def __init__(self, backend: Any, abort: Any, classifier: Any, rank: int, failure_dir: Optional[Path]):
        self.backend = backend
        self.abort = abort
        self.clf = classifier
        self.rank = rank
        self.failure_dir = failure_dir


def _check_abort(ctx: JobContext, i: int) -> None:
    if i % ABORT_POLL_TICKS == 0 and ctx.abort is not None and ctx.abort.is_set():
        raise Aborted("session abort")


def _step(ctx: JobContext, proc: Any, i: int, word: int, raw: List[Mapping[str, Any]], stats: Dict[str, float]
          ) -> Tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    """Submit word i as one `step` and check the tick contract. Returns (reply, observation, spatial)."""
    b, x, y = mcell.TRIPLES[word]
    t0 = time.perf_counter()
    rep = proc.step(b, x, y)
    stats["step_s"] += time.perf_counter() - t0
    raw.append(rep)
    o = rep.get("observation")
    if rep.get("ok") is not True or rep.get("op") != "step" or not isinstance(o, dict) or "spatial" not in rep:
        raise MismatchError("bad_reply", {"tick": i, "keys": sorted(rep)[:20]})
    if rep["consumed_tick"] != i or o["input_tick"] != i + 1 or rep["step_count"] != i + 1:
        raise MismatchError("consumed_tick", {"tick": i, "consumed_tick": rep["consumed_tick"], "input_tick": o["input_tick"],
                                              "step_count": rep["step_count"]})
    return rep, o, rep["spatial"]


def _tick0(proc: Any, pin: Optional[Mapping[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any], bytes, bytes, Dict[str, Any]]:
    """Observe (non-consuming), build the tick-0 record, compare with the pinned one. Returns (reply, record, digest, chain,
    report). Raises MismatchError on a difference in any field but host_frame."""
    reply = proc.observe()
    if reply.get("ok") is not True or reply.get("step_count") != 0 or reply["observation"]["input_tick"] != 0 \
            or reply["state"] != mcell.STATE_WAITING:
        raise MismatchError("tick0", {"state": reply.get("state_name"), "step_count": reply.get("step_count"),
                                      "input_tick": reply["observation"].get("input_tick")})
    rec = mcell.tick0_record(reply)
    rd = mcell.record_digest(rec)
    chain = mcell.chain_start(rec)
    obs = mcell.obs_tuple(reply["observation"])
    rep = {"digest": rd.hex(), "chain": chain.hex(), "host_frame": obs[mcell.HOST_FRAME], "lines": rec["l"]}
    if pin is not None:
        diffs = mcell.obs_diffs(obs, tuple(pin["obs"]))
        if diffs or rd.hex() != pin["digest"]:
            raise MismatchError("tick0", {"field_diffs": {k: list(v) for k, v in diffs.items()},
                                          "digest": rd.hex(), "pinned": pin["digest"]})
        rep["equal"] = True
        rep["host_frame_equal"] = obs[mcell.HOST_FRAME] == pin["obs"][mcell.HOST_FRAME]
    return reply, rec, rd, chain, rep


def _preserve(ctx: JobContext, job: Mapping[str, Any], raw: List[Mapping[str, Any]], exc: MismatchError) -> Optional[str]:
    if ctx.failure_dir is None:
        return None
    try:
        ctx.failure_dir.mkdir(parents=True, exist_ok=True)
        name = f"{job.get('kind')}_{job.get('iteration', job.get('episode', 'x'))}_w{ctx.rank:02d}.json.gz"
        path = ctx.failure_dir / name
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump({"kind": exc.kind, "detail": exc.detail, "job": {k: (v.hex() if isinstance(v, bytes) else v)
                                                                       for k, v in job.items() if k != "words"},
                       "words_hex": bytes(job.get("words") or b"").hex(), "replies": raw}, f, default=str)
        return str(path)
    except OSError:
        return None


def _finish_proc(proc: Any, rep: Optional[Mapping[str, Any]], ended: bool) -> Dict[str, Any]:
    """After a terminal EpisodeEnded reply: the native exit and result JSON. A failure here must not lose the trajectory (a
    clear): it is reported as `finish_error` and the claim is verified by its own replay."""
    info: Dict[str, Any] = {"result": None, "exit_code": None}
    if ended and rep is not None:
        try:
            info.update(proc.finish(rep))
        except LifecycleFailure as exc:
            proc.failed = True
            info["finish_error"] = f"{exc.outcome}: {exc.message}"[:300]
    return info


def run_tick0(ctx: JobContext, job: Mapping[str, Any]) -> Dict[str, Any]:
    t0 = time.perf_counter()
    proc = ctx.backend.acquire()
    try:
        reply, rec, rd, chain, rep = _tick0(proc, job.get("pin"))
        obs = mcell.obs_tuple(reply["observation"])
        key = mcell.cell_key(reply["observation"], reply["spatial"], ctx.clf)
        return {"ok": True, "kind": "tick0", "obs": list(obs), "digest": rep["digest"], "chain": rep["chain"],
                "lines": rep["lines"], "key": list(key) if key else None, "tick0": rep, "mode": proc.mode,
                "startup": proc.startup, "pid": proc.pid, "wall_s": round(time.perf_counter() - t0, 3), "ticks": 0,
                "mask": reply["spatial"]["target_live_mask"]}
    finally:
        proc.close()


def run_iterate(ctx: JobContext, job: Mapping[str, Any]) -> Dict[str, Any]:
    """Return to a cell (replay its words, checks at tick 0 and at L) and explore a keyed burst from it."""
    t_job = time.perf_counter()
    words: bytes = bytes(job["words"])
    L = len(words)
    allowance = int(job["allowance"])
    stats = {"step_s": 0.0}
    raw: List[Mapping[str, Any]] = []
    proc = ctx.backend.acquire()
    last: Optional[Mapping[str, Any]] = None
    ended = False
    try:
        if ctx.abort is not None and ctx.abort.is_set():
            raise Aborted("session abort")
        reply0, rec0, rd0, chain, tick0 = _tick0(proc, job["pin"])
        mask = int(reply0["spatial"]["target_live_mask"])
        prefix_breaks: List[Tuple[int, int]] = []
        n_pre = min(L, allowance)
        rep = o = sp = None
        rd = rd0
        expect_terminal = bool(job.get("terminal"))         # the cell's own reach was the native end (a fall or a clear)
        prefix_terminal = False
        for i in range(n_pre):
            _check_abort(ctx, i)
            rep, o, sp = _step(ctx, proc, i, words[i], raw, stats)
            rd = mcell.record_digest(mcell.record_of(rep))
            chain = mcell.chain_next(chain, rd)
            if rep["state"] != mcell.STATE_WAITING or mcell.is_native_failure(o, rep["state"]):
                if expect_terminal and i == L - 1:
                    prefix_terminal = True
                    ended = rep["state"] == mcell.STATE_ENDED
                else:
                    raise MismatchError("prefix_ended", {"tick": i, "state": rep.get("state_name"), "game_status": o["game_status"],
                                                         "expected_terminal": expect_terminal})
            m = int(sp["target_live_mask"])
            if m != mask:
                for b in range(mcell.TARGETS_TOTAL):
                    if (mask & ~m) >> b & 1:
                        prefix_breaks.append((i + 1, b))
                mask = m
        res: Dict[str, Any] = {"ok": True, "kind": "iterate", "iteration": job["iteration"], "cell": job["cell"],
                               "rep": tuple(job["rep"]), "L": L, "mode": proc.mode, "startup": proc.startup, "pid": proc.pid,
                               "worker": ctx.rank, "tick0": tick0, "result_json": None, "exit_code": None}
        if n_pre < L:                                # the allowance ended inside the prefix: the iteration is cut there
            res.update({"words": b"", "end_reason": "cut", "ticks": n_pre, "reaches": [], "labels": None, "breaks_all": [],
                        "t_end": mcell.level_of_mask(mask), "prefix": {"words": n_pre, "cut": True}})
            return _stamp(res, t_job, stats)
        prefix = {"words": L, "cut": False, "terminal": prefix_terminal}
        if expect_terminal and not prefix_terminal:
            raise MismatchError("terminal_expected", {"cell": job["cell"], "L": L, "why": "the prefix did not end the episode"})
        if L > 0:
            end_t = mcell.obs_tuple(o)
            diffs = mcell.obs_diffs(end_t, tuple(job["end"]))
            chain_ok = chain == bytes(job["chain"])
            digest_ok = rd == bytes(job["end_digest"])
            if diffs or not chain_ok or not digest_ok:
                raise MismatchError("prefix_end", {"cell": job["cell"], "L": L, "field_diffs": {k: list(v) for k, v in diffs.items()},
                                                   "chain_equal": chain_ok, "end_digest_equal": digest_ok})
            prefix.update({"end_equal": True, "chain_equal": True, "end_digest_equal": True,
                           "host_frame_equal": end_t[mcell.HOST_FRAME] == job["end"][mcell.HOST_FRAME]})
        res["prefix"] = prefix
        burst_len = 0 if prefix_terminal else max(0, min(int(job["burst_words"]), mcell.HORIZON - L, allowance - L))
        scanner = mcell.BurstScanner(mask)
        burst = bytearray()
        reaches: List[Tuple[int, Tuple[Any, ...], Tuple[Any, ...], bytes, bytes, bool]] = []
        seen_keys: set = set()
        end_reason = None
        archive_id, iteration = job["archive_id"], int(job["iteration"])
        for w in mx.words(lambda idx: mx.explore_key(archive_id, iteration, idx), burst_len):
            i = L + len(burst)
            _check_abort(ctx, i)
            rep, o, sp = _step(ctx, proc, i, w, raw, stats)
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
            last = rep
        if end_reason is None:
            end_reason = "length" if len(burst) >= int(job["burst_words"]) else "cut"
        info = _finish_proc(proc, rep if ended else None, ended)
        res.update({"words": bytes(burst), "end_reason": end_reason, "ticks": L + len(burst), "reaches": reaches,
                    "labels": scanner.labels(), "breaks_all": prefix_breaks + scanner.breaks, "t_end": scanner.t,
                    "result_json": info["result"], "exit_code": info["exit_code"], "finish_error": info.get("finish_error")})
        return _stamp(res, t_job, stats)
    except MismatchError as exc:
        proc.failed = True
        exc.detail["preserved"] = _preserve(ctx, job, raw, exc)
        raise
    finally:
        proc.close()


def run_control(ctx: JobContext, job: Mapping[str, Any]) -> Dict[str, Any]:
    """Arm C: one keyed explore episode from a fresh tick-0 process, run to the native end, a fall or the horizon (or the
    allowance). Nothing is replayed, nothing is selected."""
    t_job = time.perf_counter()
    stats = {"step_s": 0.0}
    raw: List[Mapping[str, Any]] = []
    proc = ctx.backend.acquire()
    ended = False
    rep = None
    try:
        reply0, rec0, rd0, chain, tick0 = _tick0(proc, job["pin"])
        scanner = mcell.BurstScanner(int(reply0["spatial"]["target_live_mask"]))
        episode = int(job["episode"])
        max_words = max(0, min(mcell.HORIZON, int(job["allowance"])))
        buf = bytearray()
        reaches: List[Tuple[int, Tuple[Any, ...]]] = []
        seen_keys: set = set()
        end_reason = None
        for w in mx.words(lambda idx: mx.control_key(episode, idx), max_words):
            i = len(buf)
            _check_abort(ctx, i)
            rep, o, sp = _step(ctx, proc, i, w, raw, stats)
            buf.append(w)
            j = i + 1
            state = rep["state"]
            ended = state == mcell.STATE_ENDED
            fell = mcell.is_native_failure(o, state)
            key = mcell.cell_key(o, sp, ctx.clf)
            if key is not None and key not in seen_keys:
                seen_keys.add(key)
                reaches.append((j, key))
            scanner.feed(j, o, sp, state)
            if ended or fell:
                end_reason = ("clear" if scanner.first["clear"] is not None else "ended") if ended else "fall"
                break
            if j >= mcell.HORIZON:
                end_reason = "horizon"
                break
        if end_reason is None:
            end_reason = "horizon" if len(buf) >= mcell.HORIZON else "cut"
        info = _finish_proc(proc, rep if ended else None, ended)
        res = {"ok": True, "kind": "control", "episode": episode, "words": bytes(buf), "end_reason": end_reason,
               "ticks": len(buf), "reaches": reaches, "labels": scanner.labels(), "breaks_all": list(scanner.breaks),
               "t_end": scanner.t, "mode": proc.mode, "startup": proc.startup, "pid": proc.pid, "worker": ctx.rank,
               "tick0": tick0, "result_json": info["result"], "exit_code": info["exit_code"],
               "finish_error": info.get("finish_error")}
        return _stamp(res, t_job, stats)
    except MismatchError as exc:
        proc.failed = True
        exc.detail["preserved"] = _preserve(ctx, job, raw, exc)
        raise
    finally:
        proc.close()


def run_trace(ctx: JobContext, job: Mapping[str, Any]) -> Dict[str, Any]:
    """P1: replay pinned words word for word; every reply's record digest must equal the pinned trace's."""
    t_job = time.perf_counter()
    words = bytes(job["words"])
    expected: Sequence[bytes] = job["expected_digests"]
    stats = {"step_s": 0.0}
    raw: List[Mapping[str, Any]] = []
    proc = ctx.backend.acquire()
    rep = None
    ended = False
    try:
        _r0, _rec0, _rd0, chain, tick0 = _tick0(proc, job["pin"])
        host_equal = 0
        ref_hosts = job.get("expected_host_frames")
        rows = []
        end_reason = "length"
        for i, w in enumerate(words):
            _check_abort(ctx, i)
            rep, o, sp = _step(ctx, proc, i, w, raw, stats)
            rd = mcell.record_digest(mcell.record_of(rep))
            if rd != bytes(expected[i]):
                raise MismatchError("trace", {"tick": i, "digest": rd.hex(), "pinned": bytes(expected[i]).hex(),
                                              "name": job.get("name")})
            if ref_hosts is not None and o["host_frame"] == ref_hosts[i]:
                host_equal += 1
            b, x, y = mcell.TRIPLES[w]
            rows.append((b, x, y, rep["consumed_tick"]))
            state = rep["state"]
            ended = state == mcell.STATE_ENDED
            fell = mcell.is_native_failure(o, state)
            if (ended or fell) and i != len(words) - 1:
                raise MismatchError("trace", {"tick": i, "why": "the episode ended before the last pinned word"})
            if ended:
                end_reason = "ended"
            elif fell:
                end_reason = "fall"
        info = _finish_proc(proc, rep if ended else None, ended)
        res = {"ok": True, "kind": "trace", "name": job.get("name"), "words": len(words), "ticks": len(words),
               "native_action_digest": mcell.native_digest(rows), "host_frames_equal": host_equal,
               "end_reason": end_reason, "mode": proc.mode, "startup": proc.startup, "pid": proc.pid, "worker": ctx.rank,
               "tick0": tick0, "result_json": info["result"]}
        return _stamp(res, t_job, stats)
    except MismatchError as exc:
        exc.detail["preserved"] = _preserve(ctx, job, raw, exc)
        raise
    finally:
        proc.close()


def _stamp(res: Dict[str, Any], t_job: float, stats: Mapping[str, float]) -> Dict[str, Any]:
    res["wall_s"] = round(time.perf_counter() - t_job, 4)
    res["step_s"] = round(stats["step_s"], 4)
    return res


def run_reverify(ctx: JobContext, job: Mapping[str, Any]) -> Dict[str, Any]:
    """Rebuilt-executable path (section 7.2): replay one burst's trajectory from tick 0 once and check every listed cell at its
    L along that replay (observation, record digest, chain). Stops at the first mismatch; nothing is dropped or re-pinned."""
    t_job = time.perf_counter()
    words = bytes(job["words"])
    checks = {int(c["L"]): c for c in job["checks"]}
    stats = {"step_s": 0.0}
    raw: List[Mapping[str, Any]] = []
    proc = ctx.backend.acquire()
    try:
        _r0, _rec0, _rd0, chain, tick0 = _tick0(proc, job["pin"])
        verified: List[int] = []
        for i, w in enumerate(words):
            _check_abort(ctx, i)
            rep, o, sp = _step(ctx, proc, i, w, raw, stats)
            rd = mcell.record_digest(mcell.record_of(rep))
            chain = mcell.chain_next(chain, rd)
            c = checks.get(i + 1)
            if c is not None:
                diffs = mcell.obs_diffs(mcell.obs_tuple(o), tuple(c["end"]))
                if diffs or rd != bytes(c["end_digest"]) or chain != bytes(c["chain"]):
                    raise MismatchError("reverify", {"cell": c["cell"], "L": i + 1, "field_diffs": {k: list(v) for k, v in diffs.items()},
                                                     "end_digest_equal": rd == bytes(c["end_digest"]),
                                                     "chain_equal": chain == bytes(c["chain"])})
                verified.append(int(c["cell"]))
        res = {"ok": True, "kind": "reverify", "burst": job.get("burst"), "words": len(words), "ticks": len(words),
               "verified_cells": verified, "mode": proc.mode, "startup": proc.startup, "pid": proc.pid, "worker": ctx.rank,
               "tick0": tick0}
        return _stamp(res, t_job, stats)
    except MismatchError as exc:
        exc.detail["preserved"] = _preserve(ctx, job, raw, exc)
        raise
    finally:
        proc.close()


JOBS: Dict[str, Callable[[JobContext, Mapping[str, Any]], Dict[str, Any]]] = {
    "tick0": run_tick0, "iterate": run_iterate, "control": run_control, "trace": run_trace, "reverify": run_reverify}


def run_job(ctx: JobContext, job: Mapping[str, Any]) -> Dict[str, Any]:
    """Run one job; every outcome is a structured dict (ok / mismatch / lifecycle / aborted / error), never an exception."""
    try:
        return JOBS[job["kind"]](ctx, job)
    except MismatchError as exc:
        return {"ok": False, "kind": "mismatch", "job_kind": job.get("kind"), "mismatch": exc.kind, "detail": exc.detail,
                "iteration": job.get("iteration", job.get("episode")), "worker": ctx.rank}
    except LifecycleFailure as exc:
        return {"ok": False, "kind": "lifecycle", "job_kind": job.get("kind"), "outcome": exc.outcome, "message": exc.message,
                "iteration": job.get("iteration", job.get("episode")), "worker": ctx.rank}
    except Aborted:
        return {"ok": False, "kind": "aborted", "job_kind": job.get("kind"), "worker": ctx.rank,
                "iteration": job.get("iteration", job.get("episode"))}
    except mcell.CellError as exc:
        return {"ok": False, "kind": "mismatch", "job_kind": job.get("kind"), "mismatch": "cell_contract",
                "detail": {"message": str(exc)}, "iteration": job.get("iteration", job.get("episode")), "worker": ctx.rank}
    except Exception as exc:  # noqa: BLE001 - structured, surfaced by the session as an error stop
        return {"ok": False, "kind": "error", "job_kind": job.get("kind"), "error": f"{type(exc).__name__}: {exc}",
                "trace": traceback.format_exc()[-3000:], "worker": ctx.rank}


# -- the worker process ------------------------------------------------------------------------------------------------------


def make_backend(spec: Mapping[str, Any]) -> Any:
    target = spec.get("backend")
    if not target:
        return RealBackend(spec)
    mod, _, cls = str(target).partition(":")
    return getattr(importlib.import_module(mod), cls)(spec)


def worker_main(conn: Any, spec: Mapping[str, Any], abort: Any) -> None:
    """Entry point of one spawned worker. Protocol: ("job", dict) -> ("result", dict); ("stop",) -> exits."""
    ProvenanceGuard.install()
    backend = None
    try:
        classifier = mcell.Classifier()
        backend = make_backend(spec)
        failure_dir = Path(spec["failure_dir"]) if spec.get("failure_dir") else None
        ctx = JobContext(backend, abort, classifier, int(spec["rank"]), failure_dir)
        conn.send(("ready", dict(backend.info(), contract=WORKER_CONTRACT)))
        while True:
            msg = conn.recv()
            if msg[0] == "stop":
                break
            if msg[0] == "report":
                conn.send(("report", {"provenance_violations": list(ProvenanceGuard.violations),
                                      "backend": getattr(backend, "report", lambda: {})()}))
                continue
            if msg[0] == "job":
                res = run_job(ctx, msg[1])
                res["provenance_violations"] = list(ProvenanceGuard.violations)
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
