"""M9-g1 run engine: P1 / P2 / P3 / P4 / training / evaluation / verification / close for one bounded gate session.

Environment-injected (`RunEnv`): the same engine runs against the real game or the synthetic stand-in (rl/m9_stub, in-process lock-step pool, virtual
clock). Phases and caps are rl/m9_contract's. A cap or memory stop ends the session INCOMPLETE (never a mismatch); an integrity failure ends it INVALID
with no retry; a stop keeps everything written and relaunches nothing. Training is the only phase that learns; nothing learns in the others.

    P1  lineages        three replays of each of the two rd4 clears (two fresh, one promoted standby), every one exact and equal to the rd4 verifying
                        replay's chain; the v3 tables are registered
    P2  staging         12 keyed starts: the staged handover equals the registered tables; the first policy-word reply equals a cold replay's
    P3  split           2 min each of 4 + 6 and 2 + 8 slots under a random policy in the 2,250-2,310 window; the registered rule picks the split
    P4  tape control    the open-loop tape at the six landing states and at tick 0, 20 episodes each, under the evaluation's sticky keys
    train               the backward curriculum under PPO (the registered caps), checkpoints every 102,400 transitions
    eval                the frozen final policy: reach, paired tape (deeper landings), deterministic, tick 0, unperturbed diagnostic, fine grid
    verify              every counted clear is replayed exactly from tick 0
    close               identity of the executable and frozen configuration, the M8 trees, the metadata audit, leftover processes, the rule
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import m8_rd_cells as mcell  # noqa: E402
import m9_artifacts as A  # noqa: E402
import m9_contract as C  # noqa: E402
import m9_curriculum as CU  # noqa: E402
import m9_eval as E  # noqa: E402
import m9_lineages as L  # noqa: E402
import m9_rule as R  # noqa: E402
import m9_sticky as S  # noqa: E402
import m9_train as T  # noqa: E402
import m9_vec as V  # noqa: E402
import m9_verify as VF  # noqa: E402

RUN_CONTRACT = "m9_run_v1"


@dataclass
class RunConfig:
    root: Path
    wall_caps_s: Mapping[str, float] = field(default_factory=lambda: dict(C.WALL_CAPS_S))
    tick_caps: Mapping[str, int] = field(default_factory=lambda: dict(C.TICK_CAPS))
    global_cap_s: float = C.GLOBAL_CAP_S
    transition_cap: int = C.TRANSITION_CAP
    p2_starts: int = C.P2_STARTS
    p3_window_s: float = C.P3_WINDOW_S
    n_slots: int = C.N_SLOTS
    verify_threads: int = 8                              # replays overlap their boots; at most 8 BattleShip processes (the cap is 10)
    memory_caps_mb: Mapping[str, float] = field(default_factory=lambda: dict(C.MEMORY_CAPS_MB))
    max_battleship_processes: int = C.MAX_BATTLESHIP_PROCESSES
    checkpoint_every: int = C.CHECKPOINT_EVERY
    write_artifacts: bool = True
    first_clears: int = 20
    session_id: str = "g1"
    landings: Sequence[int] = C.LANDINGS                 # the registered six; a test may shorten the list (and the counts below)
    eval_n: int = C.EVAL_EPISODES
    tick0_n: int = C.TICK0_EPISODES
    fine_n: int = C.FINE_GRID_EPISODES
    fine_max_points: int = C.FINE_GRID_MAX_POINTS

    @property
    def session_dir(self) -> Path:
        return self.root / "session"


@dataclass
class RunEnv:
    """Everything that touches the game or the machine, injected."""

    make_pool: Callable[[str, Mapping[str, str]], Any]                                  # (phase tag, flags) -> a started pool
    replay: VF.ReplayFn
    analyse: VF.Analyser
    promoted_trace: Callable[[L.Lineage, Mapping[str, Any]], Dict[str, Any]]            # P1: a replay through a promoted standby
    lineages: Mapping[str, L.Lineage]
    route_traces: Mapping[str, Mapping[str, Any]]                                       # the rd4 verifying replays' raw replies (initial, steps)
    pin_tick0: Mapping[str, Any]
    make_model: Callable[[Any, int], Any]                                               # (vec env, n envs) -> a fresh model
    load_model: Callable[[Path], Any]                                                   # final checkpoint -> a frozen model
    now: Callable[[], float] = time.monotonic
    pipeline_cls: Any = None
    sampler: Any = None
    private_mb: Optional[Callable[[], Optional[float]]] = None
    earlier_trees: Optional[Callable[[], Mapping[str, Any]]] = None                     # the M8 trees equal their D: increments (the close check)
    identity_now: Optional[Callable[[], Mapping[str, Any]]] = None                     # executable / frozen configuration pins read now
    pins: Mapping[str, Any] = field(default_factory=dict)
    log: Callable[[str], None] = field(default=lambda s: print(f"[m9 {time.strftime('%H:%M:%S')}] {s}", flush=True))
    provenance_violations: Callable[[], List[str]] = field(default=lambda: [])
    leftover_processes: Optional[Callable[[], List[int]]] = None
    landings: Sequence[int] = C.LANDINGS


class Clock:
    """The session hard cap, the per-phase wall caps, the tree sampler's memory breach and process count."""

    def __init__(self, env: RunEnv, cfg: RunConfig):
        self.env, self.cfg = env, cfg
        self.t0 = env.now()
        self.phase: Optional[str] = None
        self.phase_t0 = self.t0
        self.phase_wall: Dict[str, float] = {}
        self._n = 0
        self.peak_mb = 0.0
        self._over: List[Any] = []

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

    def check(self) -> None:
        if self.elapsed() > self.cfg.global_cap_s:
            raise V.CapStop(f"session hard cap reached ({self.elapsed():.0f} s > {self.cfg.global_cap_s:.0f} s) in phase {self.phase}", valid=False)
        s = self.env.sampler
        if s is not None:
            if getattr(s, "breach", None):
                raise V.CapStop(str(s.breach), valid=False)
            last = getattr(s, "last", None)
            if last is not None and int(last.get("battleship", 0)) > self.cfg.max_battleship_processes:
                seq = last.get("seq")
                if not self._over or self._over[-1] != seq:
                    self._over.append(seq)
                if len(self._over) >= 2:                   # two DISTINCT samples above the cap (the steady state has no headroom)
                    raise V.CapStop(f"more than {self.cfg.max_battleship_processes} BattleShip processes ({last.get('battleship')})", valid=False)
            elif last is not None:
                self._over = []
        self._n += 1
        if self.env.private_mb is not None and self._n % 64 == 0:
            mb = self.env.private_mb()
            if mb is not None:
                self.peak_mb = max(self.peak_mb, mb)
                if mb > self.cfg.memory_caps_mb["main_private"]:
                    raise V.CapStop(f"memory cap: main process private {mb:.0f} MB > {self.cfg.memory_caps_mb['main_private']} MB", valid=False)
        if self.phase is not None and self.phase_elapsed() > self.cfg.wall_caps_s[self.phase]:
            raise V.CapStop(f"wall cap of phase {self.phase} reached ({self.phase_elapsed():.0f} s > {self.cfg.wall_caps_s[self.phase]:.0f} s)",
                            valid=self.phase in ("train", "eval"))

    def to_json(self) -> Dict[str, Any]:
        return {"elapsed_s": round(self.elapsed(), 1), "phase_wall_s": dict(self.phase_wall), "caps_s": dict(self.cfg.wall_caps_s), "global_cap_s": self.cfg.global_cap_s,
                "peak_main_private_mb": round(self.peak_mb, 1)}


class PhaseFailed(Exception):
    pass


class Session:
    def __init__(self, cfg: RunConfig, env: RunEnv):
        self.cfg, self.env = cfg, env
        self.log = env.log
        self.clock = Clock(env, cfg)
        self.dir = cfg.session_dir
        self.root = cfg.root
        self.invalid: List[str] = []
        self.phases: Dict[str, bool] = {}
        self.notes: Dict[str, Any] = {}
        self.partial: Dict[str, Any] = {}                 # what a gate phase had measured when it stopped (written by `_partial_on_error`)
        self.tables: Dict[str, L.Tables] = {}
        self.landing_starts: List[int] = []
        self.split: Tuple[int, int] = C.SPLIT_DEFAULT
        self.p4_clears: List[Dict[str, Any]] = []
        self.p4_records: List[Dict[str, Any]] = []
        self.train_stop: Dict[str, Any] = {"valid_end": False, "reason": "training did not run"}
        self.eval_records: List[Dict[str, Any]] = []
        self.eval_clears: List[Dict[str, Any]] = []
        self.train_first_clears: List[Dict[str, Any]] = []
        self.verified: Dict[str, bool] = {}
        self.stop: Optional[Dict[str, Any]] = None
        self.curriculum: Optional[CU.Curriculum] = None

    # -- recording --------------------------------------------------------------------------------------------------------------

    def put(self, name: str, obj: Mapping[str, Any]) -> None:
        A.write_json(self.dir / f"{name}.json", A.stamp(dict(obj, scope=C.SCOPE)))

    def save_state(self, **extra: Any) -> None:
        try:
            A.write_json(self.dir / "state.json", A.stamp(dict({"utc": A.utc(), "phase": self.clock.phase, "phases": dict(self.phases), "clock": self.clock.to_json(),
                                                                "invalid": list(self.invalid), "scope": C.SCOPE}, **extra)))
        except (OSError, A.ArtifactError):
            pass

    @contextlib.contextmanager
    def pool(self, tag: str, flags: Mapping[str, str]) -> Iterator[Any]:
        pool = self.env.make_pool(tag, flags)
        try:
            yield pool
        finally:
            try:
                pool.stop()
            except Exception:                                          # noqa: BLE001
                pass

    def check_provenance(self) -> None:
        v = list(self.env.provenance_violations())
        if v:
            raise V.IntegrityStop("provenance or write-guard violation", {"violations": v[:5]})

    # -- the run ----------------------------------------------------------------------------------------------------------------

    def run(self) -> Dict[str, Any]:
        self.dir.mkdir(parents=True, exist_ok=True)
        steps: List[Tuple[str, Callable[[], bool]]] = [("p1", self.p1), ("p2", self.p2), ("p3", self.p3), ("p4", self.p4), ("train", self.train),
                                                       ("eval", self.evaluate), ("verify", self.verify)]
        try:
            for name, fn in steps:
                self.clock.begin(name)
                self.log(f"phase {name} begins (session clock {self.clock.elapsed():.0f} s)")
                self.save_state()
                ok = fn()
                self.clock.end()
                self.phases[name] = bool(ok)
                self.save_state()
                if not ok and name in ("p1", "p2", "p3", "p4"):
                    self.stop = {"phase": name, "reason": f"{name.upper()} did not pass", "valid": False}
                    break
        except V.IntegrityStop as exc:
            self.invalid.append(f"{exc.why}: {json.dumps(exc.detail, default=str)[:400]}")
            self.stop = {"phase": self.clock.phase, "reason": f"INTEGRITY: {exc.why}", "valid": False}
        except V.CapStop as exc:
            self.stop = {"phase": self.clock.phase, "reason": exc.reason, "valid": exc.valid}
            self.log(f"stop in phase {self.clock.phase}: {exc.reason}")
        except Exception as exc:                                       # noqa: BLE001 - a software error: recorded, INCOMPLETE, never silent
            self.stop = {"phase": self.clock.phase, "reason": f"software error: {type(exc).__name__}: {exc}", "valid": False, "trace": traceback.format_exc()[-3000:]}
            self.log(f"software error in phase {self.clock.phase}: {exc}")
        finally:
            self.clock.end()
        return self.finish()

    # -- P1 ---------------------------------------------------------------------------------------------------------------------

    def _partial_on_error(self, name: str, fn: Callable[[], bool]) -> bool:
        """Run a gate phase; a stop (cap, integrity, software error) leaves its partial record on disk, then propagates unchanged."""
        try:
            return fn()
        except Exception as exc:                                       # noqa: BLE001 - recorded, then re-raised
            part = self.partial.get(name)
            if name == "p1" and isinstance(part, dict):
                part = {n: len(v) for n, v in part.items()}
            try:
                self.put(name, {"ok": False, "partial": True, "error": f"{type(exc).__name__}: {str(exc)[:300]}", "partial_state": part})
            except Exception:                                          # noqa: BLE001 - the stop itself is what matters
                pass
            raise

    def p1(self) -> bool:
        return self._partial_on_error("p1", self._p1)

    def p2(self) -> bool:
        return self._partial_on_error("p2", self._p2)

    def p3(self) -> bool:
        return self._partial_on_error("p3", self._p3)

    def _p1(self) -> bool:
        cfg, env = self.cfg, self.env
        lin = dict(env.lineages)
        budget = V.TickBudget(int(cfg.tick_caps["p1"]))
        jobs = [(n, k) for n in lin for k in range(2)]
        traces: Dict[str, List[Dict[str, Any]]] = {n: [] for n in lin}
        self.partial["p1"] = traces
        lock = threading.Lock()

        def work(item: Tuple[str, int], slot: int) -> None:
            n, k = item
            tr = env.replay(lin[n].words, f"p1-{n}-{k}", slot)
            with lock:
                traces[n].append(tr)

        used = sum(3 * lin[n].length for n in lin)
        if used > cfg.tick_caps["p1"]:
            raise V.CapStop(f"P1 needs {used} ticks, cap {cfg.tick_caps['p1']}", valid=False)
        budget.consumed = used
        with ThreadPoolExecutor(max_workers=min(4, len(jobs))) as ex:
            futs = [ex.submit(work, j, i) for i, j in enumerate(jobs)]
            while not all(f.done() for f in futs):
                time.sleep(0.02)
                self.clock.check()
            for f in futs:
                f.result()
        promoted: Dict[str, Dict[str, Any]] = {}
        for n in lin:
            self.clock.check()
            promoted[n] = env.promoted_trace(lin[n], env.route_traces[n])
        out: Dict[str, Any] = {"lineages": {}}
        ok_all = True
        tdir = self.root / "lineages"
        for n, ln in lin.items():
            ev = L.p1_lineage(ln, env.route_traces[n], traces[n], env.analyse, env.pin_tick0, promoted=[promoted[n]], pipeline_cls=env.pipeline_cls, landings=C.LANDINGS)
            out["lineages"][n] = {"ok": ev["ok"], "problems": ev["problems"], "promotion_problems": ev["promotion_problems"], "replays": ev["replays"],
                                  "landing_starts": ev["landing_starts"]}
            if not ev["ok"]:
                ok_all = False
                if ev["problems"]:
                    self.invalid.append(f"P1 lineage {n}: {ev['problems'][:3]}")          # an inexact replay: INVALID, never a retry
                continue                                                                      # (a promotion that did not happen alone: P1 not passed, INCOMPLETE)
            sha = L.save_tables(tdir, n, ln.words, ev["chain"], ev["v3"])
            A.write_json(tdir / n / "registration.json", A.stamp(dict(ln.registration(), table_sha256=sha, landing_starts=ev["landing_starts"], p1_replays=len(ev["replays"]),
                                                                       chain_final=ev["chain"][-1].hex(), v3_final=ev["v3"][-1].hex())), overwrite=False)
            if n == C.TAPE_LINEAGE:
                self.landing_starts = list(ev["landing_starts"])
        out.update({"ok": ok_all, "ticks": budget.consumed, "tick_cap": cfg.tick_caps["p1"], "shared_prefix": C.SHARED_PREFIX})
        self.put("p1", out)
        if ok_all:
            self.tables = L.load_all_tables(tdir, list(lin))
            A.write_json(tdir / "registry.json", A.stamp({"lineages": list(lin), "landing_starts": self.landing_starts, "landings": list(C.LANDINGS),
                                                           "shared_prefix": C.SHARED_PREFIX, "pin_tick0": dict(env.pin_tick0)}), overwrite=False)
        return ok_all

    # -- P2 ---------------------------------------------------------------------------------------------------------------------

    def _p2(self) -> bool:
        cfg, env = self.cfg, self.env
        max_start = max(t.words.__len__() for t in self.tables.values()) - C.MIN_WORDS_AFTER_START
        jobs: List[V.StartJob] = []
        picks: List[Tuple[int, int]] = []
        for k in range(cfg.p2_starts):
            tau = min(max_start, int(S.uniform(f"m9|g1|p2|{k}|tau") * (max_start + 1)))
            word = int(S.uniform(f"m9|g1|p2|{k}|word") * 72) % 72
            picks.append((tau, word))
            jobs.append(V.StartJob(k, CU.Start(k, "p2", tau, C.TAPE_LINEAGE, tau <= C.SHARED_PREFIX, -1), None, driver="p2", kind="p2", job_id=f"p2-{k:02d}"))
        budget = V.TickBudget(int(cfg.tick_caps["p2"]))
        results: List[Dict[str, Any]] = []
        self.partial["p2"] = results
        colds: Dict[int, Any] = {}
        with self.pool("p2", C.FLAGS_TRAIN) as pool, ThreadPoolExecutor(max_workers=3) as ex:
            # at most 4 staged / parked / active processes plus 3 cold replays: never more than 10 BattleShip processes
            arena = V.Arena(pool, self.tables, T.ListSource(jobs), budget, now=env.now, guard=self.clock.check, max_procs=4, log=env.log)
            waiting: Dict[int, Tuple[int, V.EpisodeCtx]] = {}
            while len(results) < len(jobs):
                for slot, kind, payload in arena.pump(0.05):
                    if kind == "closed":
                        continue
                    if slot not in waiting:
                        continue
                    k, ctx = waiting.pop(slot)
                    if kind == "step_failed" and payload.get("kind") == "mismatch":
                        raise V.IntegrityStop(f"P2 step failed an integrity check: {payload.get('mismatch')}", payload)
                    if kind != "stepped":                         # a process that died or failed to step is a lifecycle failure (INCOMPLETE), never an inexact reply
                        raise V.CapStop(f"P2 first-step lifecycle failure ({kind}): {str(payload)[:200]}", valid=False)
                    tau, word = picks[k]
                    cold = colds[k].result()
                    steps = cold["steps"]
                    cold_digest = mcell.record_digest(mcell.record_of(steps[tau])).hex() if len(steps) > tau else None
                    tb = self.tables[ctx.lineage]
                    results.append({"k": k, "tau": tau, "word": word, "handover_chain_equal": ctx.staged["handover_chain"] == tb.chain[tau].hex(),
                                    "handover_v3_equal": ctx.staged["handover_v3"] == tb.v3[tau].hex(), "first_reply_digest": payload["record_digest"],
                                    "cold_reply_digest": cold_digest, "first_reply_equal": payload["record_digest"] == cold_digest, "ticks": tau + 1})
                    arena.release(slot)
                    pool.send(slot, ("close", {}))
                while arena.ready:
                    slot = arena.ready.popleft()
                    ctx = arena.activate(slot)
                    k = ctx.job.episode
                    tau, word = picks[k]
                    words = ctx.prefix + bytes([word])
                    colds[k] = ex.submit(env.replay, words, f"p2-cold-{k}", k % 8)       # up to 3 run at once; consecutive k give distinct port-block ranks
                    waiting[slot] = (k, ctx)
                    pool.send(slot, ("step", {"word": word}))
        ok = len(results) == len(jobs) and all(r["handover_chain_equal"] and r["handover_v3_equal"] and r["first_reply_equal"] for r in results)
        self.put("p2", {"ok": ok, "starts": results, "ticks": budget.consumed + sum(r["ticks"] for r in results), "tick_cap": cfg.tick_caps["p2"]})
        if not ok:
            self.invalid.append("P2: a staged handover or its first policy-word reply differs from the registered tables / the cold replay")
        return ok

    # -- P3 ---------------------------------------------------------------------------------------------------------------------

    def _p3(self) -> bool:
        cfg, env = self.cfg, self.env
        Vec = V.make_vec_env_class()
        share = int(cfg.tick_caps["p3"]) // 2             # R9 read for the measurement: each configuration may use half of the phase's native-tick cap
        rows: Dict[str, Dict[str, Any]] = {}
        self.partial["p3"] = rows
        with self.pool("p3", C.FLAGS_TRAIN) as pool:
            for active, staging in (C.SPLIT_DEFAULT, C.SPLIT_ALTERNATIVE):
                tag = f"{active}x{staging}"
                budget = V.TickBudget(share)
                src = T.WindowSource(tag, *C.P3_TAU_WINDOW)
                arena = V.Arena(pool, self.tables, src, budget, now=env.now, guard=self.clock.check, max_staging=pool.n - active, log=env.log)
                vec = Vec(arena, active)
                rng = np.random.default_rng(int.from_bytes(hashlib.sha256(f"m9|g1|p3|{tag}".encode()).digest()[:8], "big"))
                t0 = env.now()
                tr0 = vec.transitions
                window_end = "wall"
                try:
                    vec.reset()
                    while env.now() - t0 < cfg.p3_window_s:
                        acts = np.stack([rng.integers(0, 9, size=active), rng.integers(0, 8, size=active)], axis=1)
                        vec.step(acts)
                except V.CapStop as exc:
                    if not (exc.valid and exc.reason.startswith("native tick cap")):
                        raise                                 # a wall cap, a lifecycle limit or a dead worker is a stop, never a measurement
                    window_end = "tick_cap"                   # the registered valid end of the phase's budget: the rate is over the elapsed window
                dt = env.now() - t0
                n = vec.transitions - tr0
                sm = arena.summary()
                rows[tag] = {"active": active, "staging": staging, "window_s": round(dt, 2), "window_end": window_end, "tick_share": share, "transitions": n,
                             "transitions_per_s": round(n / max(dt, 1e-9), 3), "episodes": vec.episodes, "staged": sm["staged"], "wait_s": sm["wait_s"], "waits": sm["waits"],
                             "ticks": budget.consumed, "lifecycle_failures": sm["lifecycle_failures"], "stale_events": arena.stale_events,
                             "eligible": not sm["lifecycle_failures"] and n > 0}      # a window without one policy transition measured nothing
                arena.close_unfinished()
        d, a = rows["4x6"], rows["2x8"]
        choice, why = select_split(d, a)
        self.split = choice
        out = {"rows": rows, "choice": list(choice) if choice else None, "why": why, "rule": "2 + 8 only if eligible and its transitions/s >= %.2f x the eligible 4 + 6's; else 4 + 6; "
               "a configuration with a lifecycle failure is ineligible; neither eligible: P3 not passed" % C.SPLIT_SWITCH_RATIO, "ticks": sum(r["ticks"] for r in rows.values()),
               "tick_cap": cfg.tick_caps["p3"], "tick_cap_reading": "each configuration's window ends at the earlier of its wall window and half of the phase's native-tick cap; "
               "the rate is its policy transitions over its elapsed window (window_end says which)"}
        ok = choice is not None
        out["ok"] = ok
        self.put("p3", out)
        return ok

    # -- P4 ---------------------------------------------------------------------------------------------------------------------

    def p4(self) -> bool:
        cfg, env = self.cfg, self.env
        jobs = E.p4_jobs(cfg.landings, cfg.eval_n)
        budget = V.TickBudget(int(cfg.tick_caps["p4"]))
        rec = E.EvalRecorder(self.root / "p4", self.tables, phase="p4", now=env.now, write_artifacts=cfg.write_artifacts)
        with self.pool("p4", C.FLAGS_EVAL) as pool:
            arena = V.Arena(pool, self.tables, T.ListSource(jobs), budget, now=env.now, guard=self.clock.check, log=env.log)
            runner = E.EvalRunner(arena, self.tables, rec, now=env.now)
            res = runner.run()
            arena.close_unfinished()
        self.p4_records, self.p4_clears = rec.records, rec.clears
        complete = len(rec.records) == len(jobs) and res["stop"] is None
        clears = sum(1 for r in rec.records if r["clear"])
        per: Dict[str, List[int]] = {}
        for r in rec.records:
            d = per.setdefault(str(r["landing"]), [0, 0])
            d[0] += 1
            d[1] += int(r["clear"])
        self.put("p4", {"ok": complete, "episodes": len(rec.records), "planned": len(jobs), "tape_clears": clears, "per_landing": per, "run": res,
                        "note": "P4 passes on integrity and completion; the tape's clears are the control of the reach rule, never a pass condition"})
        if res["stop"] is not None and not complete:
            raise V.CapStop(f"P4 stopped before completion: {res['stop']['reason']}", valid=False)
        return complete

    # -- training ---------------------------------------------------------------------------------------------------------------

    def train(self) -> bool:
        cfg, env = self.cfg, self.env
        n_active, n_staging = self.split
        Vec = V.make_vec_env_class()
        cur = CU.Curriculum({n: len(t.words) for n, t in self.tables.items()})
        self.curriculum = cur
        run_dir = self.root / "training"
        run_dir.mkdir(parents=True, exist_ok=True)
        budget = V.TickBudget(int(cfg.tick_caps["train"]))
        rec = T.TrainRecorder(run_dir, cur, self.tables, now=env.now, write_artifacts=cfg.write_artifacts, first_clears=cfg.first_clears)
        with self.pool("train", C.FLAGS_TRAIN) as pool:
            arena = V.Arena(pool, self.tables, T.TrainSource(cur), budget, now=env.now, guard=self.clock.check, log=env.log)
            vec = Vec(arena, n_active, recorder=rec.on_episode, outcome=rec.on_outcome)
            model = env.make_model(vec, n_active)
            try:
                stop = T.train(model, vec, arena, cur, rec, run_dir=run_dir, guard=self.clock.check, now=env.now, transition_cap=cfg.transition_cap,
                               extra_meta={"split": [n_active, n_staging]})
            except Exception as exc:                                   # noqa: BLE001 - recorded (a software error), then re-raised
                try:
                    self.put("training_summary", {"valid_end": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}", "split": [n_active, n_staging],
                                                  "pointer_final": cur.pointer, "pointer_moves": cur.moves, "arena": arena.summary()})
                except Exception:                                      # noqa: BLE001
                    pass
                raise
            arena.close_unfinished()
            sm = arena.summary()
        self.train_first_clears = list(rec.first_clears)
        self.train_stop = stop
        self.notes["training_pointer"] = cur.pointer
        summary = {"stop": {k: v for k, v in stop.items() if k not in ("checkpoints", "detail")}, "valid_end": stop["valid_end"], "split": [n_active, n_staging],
                   "pointer_final": cur.pointer, "pointer_moves": cur.moves, "blocks": len(cur.blocks), "curriculum": cur.state(), "recorder": rec.summary(),
                   "arena": sm, "checkpoints": stop.get("checkpoints"), "final_checkpoint": stop.get("final"), "stale_events": arena.stale_events,
                   "transitions": stop.get("transitions"), "ticks": stop.get("ticks"), "entropy_note": "per-rollout entropy and explained variance are in training/rollouts.jsonl"}
        self.put("training_summary", summary)
        A.write_json(run_dir / "checkpoints.json", A.stamp({"checkpoints": stop.get("checkpoints"), "final": stop.get("final")}))
        if stop.get("integrity"):
            raise V.IntegrityStop(str(stop["reason"]), stop.get("detail") or {})
        if not stop["valid_end"]:
            raise V.CapStop(f"training stopped early: {stop['reason']}", valid=False)
        return True

    # -- evaluation ---------------------------------------------------------------------------------------------------------------

    def evaluate(self) -> bool:
        cfg, env = self.cfg, self.env
        run_dir = self.root / "eval"
        final_dir = self.root / "training" / "checkpoints" / "final"
        model = env.load_model(final_dir / "model.zip")
        models: Dict[str, Any] = {"final": model}
        pointer = self.curriculum.pointer if self.curriculum is not None else C.TAU0
        deeper = E.deeper_landings(self.landing_starts, pointer)
        landings = list(cfg.landings) + deeper
        fine = E.fine_grid(pointer, max_points=cfg.fine_max_points)
        jobs = E.evaluation_jobs(landings, fine, tape_landings=deeper, n=cfg.eval_n, tick0_n=cfg.tick0_n, fine_n=cfg.fine_n)
        mid = self._mid_checkpoint()
        if mid is not None:
            try:
                models["mid"] = env.load_model(self.root / "training" / "checkpoints" / mid["checkpoint"] / "model.zip")
            except Exception as exc:                                  # noqa: BLE001 - the 30-minute checkpoint is descriptive only: its failure never stops the gate
                self.notes["mid_checkpoint_error"] = f"{type(exc).__name__}: {exc}"[:300]
                mid = None
        if mid is not None:
            for lam in sorted(landings, reverse=True):
                for k in range(cfg.fine_n):
                    jobs.append(V.StartJob(len(jobs), E._start(len(jobs), lam, "landing"), S.eval_label("reach", lam, k), driver="policy", kind="reach_mid", tier=4,
                                           job_id=f"reach_mid-{lam}-{k:02d}", extra={"landing": lam, "k": k, "model": "mid"}))
        budget = V.TickBudget(int(cfg.tick_caps["eval"]))
        rec = E.EvalRecorder(run_dir, self.tables, phase="eval", now=env.now, write_artifacts=cfg.write_artifacts)
        with self.pool("eval", C.FLAGS_EVAL) as pool:
            arena = V.Arena(pool, self.tables, T.ListSource(jobs), budget, now=env.now, guard=self.clock.check, log=env.log)
            runner = E.EvalRunner(arena, self.tables, rec, models=models, now=env.now)
            res = runner.run()
            arena.close_unfinished()
        self.eval_records, self.eval_clears = rec.records, rec.clears
        self.notes["eval"] = {"planned": len(jobs), "completed": len(rec.records), "stop": res["stop"], "landings": landings, "deeper": deeper, "mid_checkpoint": mid}
        self.put("eval_run", {"run": res, "planned": len(jobs), "completed": len(rec.records), "landings": landings, "deeper_landings": deeper, "pointer_final": pointer,
                              "fine_points": fine, "mid_checkpoint": mid})
        if res["stop"] is not None and not res["stop"]["valid"]:
            raise V.CapStop(f"evaluation stopped early: {res['stop']['reason']}", valid=False)
        return True

    def _mid_checkpoint(self) -> Optional[Dict[str, Any]]:
        cps = [c for c in (self.train_stop.get("checkpoints") or []) if c.get("num_timesteps", 0) > 0 and c.get("wall_s") is not None]
        if not cps:
            return None
        return min(cps, key=lambda c: abs(float(c["wall_s"]) - 1800.0))

    # -- verification -------------------------------------------------------------------------------------------------------------

    def verify(self) -> bool:
        cfg, env = self.cfg, self.env
        jobs: List[VF.VerifyJob] = []
        seen = set()

        def add(rec: Mapping[str, Any], tier: int, group: str) -> None:
            if rec["id"] in seen:
                return
            seen.add(rec["id"])
            jobs.append(VF.VerifyJob(rec["id"], rec["words"], rec["online"], tau=rec["tau"], tier=tier, group=group, meta={"kind": rec.get("kind")}))

        for c in self.p4_clears:
            add(c, 0, "p4")
        for c in self.eval_clears:
            add(c, 0 if c["kind"] in ("reach", "reach_tape") else (3 if c["kind"] in ("fine", "reach_mid") else 2), "eval")
        for c in self.train_first_clears:
            add({"id": c["episode"], "words": c["words"], "online": c["online"], "tau": c["tau"], "kind": "train"}, 1, "train")
        out_dir = self.root / "verification"

        def on_result(job: VF.VerifyJob, res: Mapping[str, Any]) -> None:
            self.verified[job.id] = bool(res["exact"])
            A.append_jsonl(out_dir / "replays.jsonl", A.stamp({k: v for k, v in res.items() if k != "breaks"} | {"breaks_n": len(res["breaks"]), "kind": job.meta.get("kind")}))

        rep = VF.run_plan(jobs, env.replay, env.analyse, tick_cap=int(cfg.tick_caps["verify"]), wall_cap_s=float(cfg.wall_caps_s["verify"]), threads=cfg.verify_threads,
                          now=env.now, on_result=on_result, check=self.clock.check)
        self.notes["verification"] = {k: v for k, v in rep.items() if k != "results"}
        self.put("verification", {k: v for k, v in rep.items() if k != "results"} | {"planned": len(jobs)})
        if rep["inexact"]:
            self.invalid.append(f"an exact replay of a counted clear failed: {rep['inexact'][:5]}")
        if rep["errors"]:
            # a replay whose process could not launch or died is a lifecycle failure, not an integrity failure: its clear stays UNVERIFIED (never counted), and the
            # rule makes the gate INCOMPLETE if verifying it could change R
            self.notes["verification_errors"] = rep["errors"][:5]
        return not rep["inexact"]

    # -- the decision -------------------------------------------------------------------------------------------------------------

    def facts(self) -> Dict[str, Any]:
        agg = E.aggregate(self.p4_records + self.eval_records, self.verified)
        reach = {int(k): v for k, v in agg["reach"].items() if int(k) != 0}
        landings = list(self.cfg.landings) + list(self.notes.get("eval", {}).get("deeper", []))
        mid = [r for r in self.eval_records if r["eval_kind"] == "reach_mid"]
        mid_rows: Dict[int, Dict[str, Any]] = {}
        for r in mid:
            d = mid_rows.setdefault(int(r["landing"]), {"n": 0, "clears": 0, "verified": 0, "tape_n": 0, "tape_clears": 0, "tape_verified": 0})
            d["n"] += 1
            d["clears"] += int(r["clear"])
        return {"invalid": list(self.invalid), "phases": dict(self.phases), "training": {"valid_end": bool(self.train_stop.get("valid_end")), "stop": self.train_stop.get("reason")},
                "reach": reach, "unperturbed": {int(k): v for k, v in agg["unperturbed"].items() if int(k) != 0}, "fine": {int(k): v for k, v in agg["fine"].items()},
                "landings": landings, "tick0": agg["tick0"], "deterministic": agg["deterministic"], "mid_checkpoint_rows": mid_rows}

    def finish(self) -> Dict[str, Any]:
        env = self.env
        close: Dict[str, Any] = {"phase": "close"}
        self.clock.phase = None
        t_close = env.now()
        try:
            if env.earlier_trees is not None:
                et = dict(env.earlier_trees())
                close["earlier_trees"] = et
                if not et.get("ok"):
                    self.invalid.append(f"an M8 tree no longer equals its D: increment: {et.get('problems')}")
            if env.identity_now is not None:
                idn = dict(env.identity_now())
                close["identity"] = idn
                pins = dict(env.pins)
                diffs = {k: (idn.get(k), v) for k, v in pins.items() if k in idn and idn.get(k) != v}
                if diffs:
                    self.invalid.append(f"pin drift at the close: {sorted(diffs)}")
            v = list(env.provenance_violations())
            close["provenance_violations"] = v
            if v:
                self.invalid.append(f"provenance or write-guard violations: {v[:3]}")
            aud = A.audit_tree(self.root, skip_dirs=("workers", "vw"))
            close["metadata_audit"] = {"files": aud["files"], "jsonl_lines": aud["jsonl_lines"], "failures": aud["failures"][:10], "ok": aud["ok"]}
            if not aud["ok"]:
                self.invalid.append(f"artifacts without the task block or created_utc: {aud['failures'][:3]}")
            if env.leftover_processes is not None:
                left = env.leftover_processes()
                close["leftover_battleship_processes"] = left
        except Exception as exc:                                       # noqa: BLE001 - every close check runs in its own guard
            close["error"] = f"{type(exc).__name__}: {exc}"
            self.invalid.append(f"a close check failed to run: {close['error']}")
        facts = self.facts()
        facts["invalid"] = list(self.invalid)
        out = R.apply(facts)
        out["stop"] = self.stop
        out["facts"] = {k: v for k, v in facts.items() if k not in ("invalid",)}
        out["split"] = list(self.split) if self.split else None
        out["clock"] = self.clock.to_json()
        close["wall_s"] = round(env.now() - t_close, 2)
        self.put("close", close)
        self.put("rule", out)
        self.save_state(done=True, outcome=out["outcome"])
        return out


def select_split(d: Mapping[str, Any], a: Mapping[str, Any]) -> Tuple[Optional[Tuple[int, int]], str]:
    """The registered process-split rule: 2 + 8 only if it is eligible and its measured policy transitions per second are at least 1.10 x the eligible
    4 + 6's; otherwise 4 + 6; a configuration with a lifecycle failure is ineligible; with neither eligible the split is undecided (P3 not passed)."""
    de, ae = bool(d["eligible"]), bool(a["eligible"])
    if not de and not ae:
        return None, "neither configuration is eligible (lifecycle failures)"
    if not de:
        return C.SPLIT_ALTERNATIVE, "4 + 6 had a lifecycle failure; 2 + 8 is the only eligible configuration"
    if not ae:
        return C.SPLIT_DEFAULT, "2 + 8 had a lifecycle failure; the default 4 + 6 stands"
    pct = int(round(C.SPLIT_SWITCH_RATIO * 100))                    # integer comparison: exactly 110 % chooses 2 + 8 (no float boundary)
    if float(a["transitions_per_s"]) * 100.0 >= pct * float(d["transitions_per_s"]):
        return C.SPLIT_ALTERNATIVE, f"2 + 8 measured {a['transitions_per_s']} transitions/s >= {C.SPLIT_SWITCH_RATIO} x 4 + 6's {d['transitions_per_s']}"
    return C.SPLIT_DEFAULT, f"2 + 8 measured {a['transitions_per_s']} transitions/s < {C.SPLIT_SWITCH_RATIO} x 4 + 6's {d['transitions_per_s']}; the default stands"


def budget_projection() -> Dict[str, Any]:
    """The wall budget of the whole session: the registered phase caps and the global cap; the pessimistic case (every cap binding, each phase's grace and the
    pool spawns) and an expected case from measured throughputs. A projection, not a promise."""
    caps = C.WALL_CAPS_S
    phases_sum = sum(caps.values())
    spawn_s = 4 * 15.0                                    # four pool spawns (P2/P3, P4, training, evaluation) at about 15 s each, pessimistic
    grace = C.WALL_CAP_GRACE_S * len(C.PHASES)
    pessimistic = phases_sum + spawn_s + grace
    expected = {"p1": 60, "p2": 60, "p3": 280, "p4": 240, "train": 3600, "eval": 900, "verify": 300, "close": 120}
    return {"phase_caps_s": dict(caps), "sum_of_caps_s": phases_sum, "pessimistic_total_s": pessimistic, "pessimistic_total_min": round(pessimistic / 60, 1),
            "global_cap_s": C.GLOBAL_CAP_S, "fits_global_cap_pessimistic": pessimistic <= C.GLOBAL_CAP_S, "slack_pessimistic_s": C.GLOBAL_CAP_S - pessimistic,
            "expected_total_s": sum(expected.values()), "expected_phases_s": expected,
            "note": "the training, evaluation and verification phases end by their wall caps; the session clock starts at the session object and counts the pool spawns"}
