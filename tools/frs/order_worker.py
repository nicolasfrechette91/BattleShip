#!/usr/bin/env python3
"""Option D's own search worker (owner 2026-11-19, report-only): run 3's lab worker (tools/frs/run3_worker.py) with the entity block on
(SSB64_RL_ENTITY=1) and a hitter record of every target break. Used only with order_search's --hitter-record; without it D starts
run3_worker.Run3Pool exactly as before. No frozen file is edited: run 3's proxy, observer, job and pool are imported and wrapped.

    layering        the real process (rl/m8_rd_worker backend) -> HitterProc (this module) -> run 3's ObservedProc (its JobObserver: D6, the
                    live detectors, the decisions) -> rl/frs_worker.run_iterate_frs. HitterProc reads the entity object of every observe /
                    step reply and hands the reply on WITHOUT it, so run 3's proxy, its observer and the worker see exactly the reply an
                    entity-off process gives: same chains, records, keys, breaks, boundary questions, glitch events and anomaly rows. The
                    tick-0 observe of every job must carry the entity object (a misconfigured flag fails the job, so the root reads stop
                    the open); the tracker itself never raises (a malformed object is a break of kind "unavailable").
    hitter rule     (HITTER_RULE; zero tests and set membership only, no threshold) at a break tick j (a bit leaving spatial.target_live_mask
                    between the replies of ticks j - 1 and j, the worker's own rule), from the entity objects of ticks j - 1 and j:
                      onset     the player fighter's hitlag_tics is 0 at j - 1 and > 0 at j (the game turns a connected attack into the
                                attacker's hitlag in the breaking update: itprocess.c:311, ftmain.c:4094-4134; tools/glitch/detect.py reads
                                the same onset);
                      vanished  weapons (any owner) listed at j - 1 and absent at j (a weapon that hits is destroyed in that update:
                                wpprocess.c wpProcessProcHitCollisions, Mario's fireball returns TRUE from its hit proc);
                    kind "mario" = onset and nothing vanished; "projectile" = no onset, hitlag 0 at j - 1 and exactly one weapon vanished
                    (its serial, owner, kind and the tick its serial first appeared in this job); "unseen" = neither (a weapon made and
                    destroyed inside the breaking update is never in a capture); "ambiguous" = onset with a vanished weapon, two or more
                    vanished, or hitlag already running at j - 1 (candidates listed); "unavailable" = no entity object, not live or an
                    anomaly flag at j - 1 or j. Census before the build (zero ticks, 1,850 stored entity-on traces, 666 distinct breaks):
                    mario 541, projectile 100, unseen 25, ambiguous 0.
    serials         the entity block's per-process spawn serial; every job is a fresh process from tick 0 and this proxy sees every reply
                    from the tick-0 observe on, so a weapon's first tick is the first reply that lists its serial (None for serial 0, the
                    block's overflow value).
    result          every ok iterate job carries `d_hitters`: one event per break tick of the job (prefix replay and burst, in tick order).
                    The main process (tools/frs/order_search.break_record) attaches them to the credited breaks. Read by no rule.
    reset (later)   an in-process soft reset would live here, in HitterBackend.acquire / HitterProc.close: hand out the same native
                    process again after a reset to tick 0 instead of a fresh one. It needs (1) a native reset op (none exists today:
                    protocol and executable change, frs_savestate_feasibility option C); (2) the job's tick-0 check unchanged (mw._tick0
                    compares the tick-0 record with the pin, so a reset process is accepted only when its tick 0 is the root's); (3) the
                    entity serial table restarting with the scene (sc1pbonusstage.c forgets it outside the scene) and a fresh
                    HitterTracker per job, as now; (4) the process identity in results (pid, mode, startup) marked as reused; (5) the
                    standby manager (m7_standby) told not to pre-launch while a process is reused; (6) the job's failure path (a
                    failed process is closed for good, never reset). Nothing of it is built.

Zero native ticks at import. Tests: tools/frs/order_search_tests.py (unit_hitter_*, e2e_e12_hitter_record).
"""
from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _p in (REPO / "rl", HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import frs_guard as g  # noqa: E402
import frs_worker as fw  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_worker as mw  # noqa: E402
import run3_anomaly as ra  # noqa: E402
import run3_worker as r3w  # noqa: E402

ORDER_WORKER_CONTRACT = "order_worker_v1"
HITTER_CONTRACT = "order_hitter_v1"
ENTITY_FLAGS = {"SSB64_RL_ENTITY": "1"}
SPEC_KEY = "d_hitter"
KINDS = ("mario", "projectile", "unseen", "ambiguous", "unavailable")
OWNER_PLAYER, OWNER_OTHER = "mario", "other"
HITTER_RULE = ("at a break tick j, from the entity objects of j - 1 and j: onset = the player fighter's hitlag_tics 0 at j - 1 and > 0 at j; "
               "vanished = weapons listed at j - 1 and absent at j. mario = onset, none vanished; projectile = no onset, hitlag 0 at j - 1, exactly "
               "one vanished (serial, owner, kind, first tick of the serial in the job); unseen = neither; ambiguous = onset with a vanished "
               "weapon, two or more vanished, or hitlag running at j - 1; unavailable = no entity object, not live or an anomaly flag")


class EntityMissing(RuntimeError):
    """The tick-0 observe of a job has no entity object although the hitter record is on (the flag did not reach the process)."""


# -- the hitter rule (pure) -------------------------------------------------------------------------------------------------------------------


def snapshot(reply: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """The fields the rule reads from one reply's entity object, or None when it has none. Never raises: a malformed object gives
    {"error": ...}."""
    en = reply.get("entity")
    if en is None:
        return None
    try:
        f = en["fighter"]
        weapons = {}
        for w in en["weapons"]:
            weapons[int(w["serial"])] = {"kind": int(w["kind"]), "owned": int(w["owned"]), "attack_state": int(w["attack_state"]),
                                         "lifetime": int(w["lifetime"])}
        o = reply.get("observation") or {}
        return {"live": int(en["live"]), "anomaly": int(en["anomaly_flags"]), "hitlag": int(f["hitlag_tics"]), "attack": int(f["attack_active"]),
                "weapons": weapons, "total": int(en["weapon_total"]), "status": o.get("fighter_status_id")}
    except (KeyError, TypeError, ValueError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}"[:200]}


def _weapon(serial: int, w: Mapping[str, Any], first: Mapping[int, int]) -> Dict[str, Any]:
    return {"serial": int(serial), "owner": OWNER_PLAYER if int(w["owned"]) else OWNER_OTHER, "weapon_kind": int(w["kind"]),
            "first_tick": None if int(serial) == 0 else first.get(int(serial))}


def classify(tick: int, targets: Sequence[int], prev: Optional[Mapping[str, Any]], cur: Optional[Mapping[str, Any]],
             first: Mapping[int, int]) -> Dict[str, Any]:
    """One break tick's hitter event (HITTER_RULE)."""
    ev: Dict[str, Any] = {"tick": int(tick), "targets": [int(t) for t in targets], "kind": None, "serial": None, "owner": None, "first_tick": None,
                          "weapon_kind": None, "candidates": [], "why": None, "evidence": None}
    for name, s in (("j - 1", prev), ("j", cur)):
        why = None
        if s is None:
            why = f"no entity object at {name}"
        elif "error" in s:
            why = f"entity object at {name} unreadable: {s['error']}"
        elif not s["live"]:
            why = f"entity not live at {name}"
        elif s["anomaly"]:
            why = f"entity anomaly flags {s['anomaly']:#x} at {name}"
        if why is not None:
            ev.update(kind="unavailable", why=why)
            return ev
    assert prev is not None and cur is not None
    vanished = sorted(s for s in prev["weapons"] if s not in cur["weapons"])
    onset = prev["hitlag"] == 0 and cur["hitlag"] > 0
    ev["evidence"] = {"hitlag": [prev["hitlag"], cur["hitlag"]], "attack_active": [prev["attack"], cur["attack"]],
                      "status": [prev["status"], cur["status"]], "weapons": [len(prev["weapons"]), len(cur["weapons"])],
                      "weapon_total": [prev["total"], cur["total"]],
                      "vanished": [dict(_weapon(s, prev["weapons"][s], first), attack_state=prev["weapons"][s]["attack_state"],
                                        lifetime=prev["weapons"][s]["lifetime"]) for s in vanished]}
    cands = ([{"kind": "mario"}] if onset or prev["hitlag"] > 0 else []) + [dict(_weapon(s, prev["weapons"][s], first), kind="projectile") for s in vanished]
    if prev["hitlag"] > 0:
        ev.update(kind="ambiguous", candidates=cands, why="hitlag already running at j - 1")
    elif onset and not vanished:
        ev["kind"] = "mario"
    elif onset:
        ev.update(kind="ambiguous", candidates=cands, why="hitlag onset and a weapon vanished")
    elif len(vanished) == 1:
        ev.update(_weapon(vanished[0], prev["weapons"][vanished[0]], first), kind="projectile")
    elif vanished:
        ev.update(kind="ambiguous", candidates=cands, why=f"{len(vanished)} weapons vanished")
    else:
        ev["kind"] = "unseen"
    return ev


class HitterTracker:
    """One job's replies in order (the tick-0 observe, then every step): break ticks by the live-target mask, the hitter event of each, the
    first tick of every weapon serial. feed() never raises; a failure is counted and the job goes on."""

    def __init__(self) -> None:
        self.prev: Optional[Dict[str, Any]] = None
        self.mask: Optional[int] = None
        self.first: Dict[int, int] = {}
        self.events: List[Dict[str, Any]] = []
        self.replies = 0
        self.errors: List[str] = []

    def feed(self, reply: Mapping[str, Any]) -> None:
        try:
            if reply.get("ok") is not True or not isinstance(reply.get("observation"), dict) or not isinstance(reply.get("spatial"), dict):
                return                                     # not a reply the job keeps (the worker raises on it)
            self.replies += 1
            tick = int(reply["observation"]["input_tick"])
            snap = snapshot(reply)
            if snap is not None and "error" not in snap:
                for s in snap["weapons"]:
                    if s != 0:
                        self.first.setdefault(s, tick)
            m = int(reply["spatial"]["target_live_mask"])
            if self.mask is not None and m != self.mask:
                lost = self.mask & ~m
                if lost:
                    self.events.append(classify(tick, [b for b in range(mcell.TARGETS_TOTAL) if lost >> b & 1], self.prev, snap, self.first))
            self.mask = m
            self.prev = snap
        except Exception as exc:  # noqa: BLE001 - a record, never a change to the job
            if len(self.errors) < 8:
                self.errors.append(f"{type(exc).__name__}: {exc}"[:200])

    def result(self) -> Dict[str, Any]:
        return {"contract": HITTER_CONTRACT, "events": list(self.events), "replies": self.replies, "errors": list(self.errors)}


# -- the proxy below run 3's ----------------------------------------------------------------------------------------------------------------


def _without_entity(reply: Mapping[str, Any]) -> Mapping[str, Any]:
    return {k: v for k, v in reply.items() if k != "entity"} if "entity" in reply else reply


class HitterProc:
    """Forwards everything to the real process; observe / step replies go to the job's tracker, then on without the entity object."""

    def __init__(self, proc: Any, owner: "HitterBackend"):
        object.__setattr__(self, "_proc", proc)
        object.__setattr__(self, "_owner", owner)

    def observe(self) -> Mapping[str, Any]:
        reply = self._proc.observe()
        if reply.get("ok") is True and isinstance(reply.get("observation"), dict) and "entity" not in reply:
            raise EntityMissing(f"the tick-0 observe has no entity object: {sorted(ENTITY_FLAGS)} did not reach the process")
        tr = self._owner.tracker
        if tr is not None:
            tr.feed(reply)
        return _without_entity(reply)

    def step(self, buttons: int, stick_x: int, stick_y: int) -> Mapping[str, Any]:
        reply = self._proc.step(buttons, stick_x, stick_y)
        tr = self._owner.tracker
        if tr is not None:
            tr.feed(reply)
        return _without_entity(reply)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._proc, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._proc, name, value)                     # e.g. `proc.failed = True` must reach the real process


class HitterBackend:
    """Wraps the worker's real backend; the process it hands out is a HitterProc. `tracker` is the current job's (None between jobs)."""

    def __init__(self, backend: Any):
        self._backend = backend
        self.tracker: Optional[HitterTracker] = None

    def acquire(self, *args: Any, **kwargs: Any) -> HitterProc:
        return HitterProc(self._backend.acquire(*args, **kwargs), self)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._backend, name)


def hitter_spec(spec: Mapping[str, Any]) -> Dict[str, Any]:
    """A worker spec with the entity flag added to the search flags (when the spec has flags) and the hitter record on."""
    s = dict(spec)
    if "flags" in s:
        s["flags"] = dict(s["flags"], **ENTITY_FLAGS)
    s[SPEC_KEY] = True
    return s


# -- the job and the worker process ---------------------------------------------------------------------------------------------------------


def run_job(ctx: Any, job: Mapping[str, Any], geometry: ra.GeometryCache, selfcheck: bool, hb: HitterBackend) -> Dict[str, Any]:
    """run3_worker.run_job, with a fresh tracker for an iterate job; an ok result carries `d_hitters`."""
    tr = HitterTracker() if job.get("kind") == fw.JOB_KIND else None
    hb.tracker = tr
    try:
        res = r3w.run_job(ctx, job, geometry, selfcheck)
    finally:
        hb.tracker = None
    if tr is not None and res.get("ok"):
        res["d_hitters"] = tr.result()
        res["order_worker_contract"] = ORDER_WORKER_CONTRACT
    return res


def worker_main(conn: Any, spec: Mapping[str, Any], abort: Any) -> None:
    """run3_worker.worker_main (same protocol, same boundary question, same proxy and observer) with HitterBackend under run 3's proxy and
    this module's run_job."""
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
        hb = HitterBackend(mw.make_backend(spec))
        backend = r3w._ProcInfoBackend(hb, holder)
        failure_dir = Path(spec["failure_dir"]) if spec.get("failure_dir") else None
        ctx = fw.LabJobContext(backend, abort, classifier, int(spec["rank"]), failure_dir, ask)
        ctx.observer = None
        ctx.last_proc_info = {}
        holder["ctx"] = ctx
        geometry = ra.GeometryCache()
        selfcheck = bool(spec.get("run3_selfcheck"))
        conn.send(("ready", dict(backend.info(), contract=fw.FRS_WORKER_CONTRACT, run3_contract=r3w.RUN3_WORKER_CONTRACT,
                                 order_worker_contract=ORDER_WORKER_CONTRACT, hitter=HITTER_CONTRACT)))
        while not state["stop"]:
            msg = conn.recv()
            if msg[0] == "stop":
                break
            if msg[0] == "report":
                conn.send(("report", {"guard_violations": list(g.LabGuard.violations), "backend": getattr(backend, "report", lambda: {})()}))
                continue
            if msg[0] == "job":
                res = run_job(ctx, msg[1], geometry, selfcheck, hb)
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


class OrderPool(r3w.Run3Pool):
    """run3_worker.Run3Pool starting this module's worker_main with hitter_spec specs (everything else inherited)."""

    def __init__(self, spec_fn: Any, now: Any):
        super().__init__(lambda rank: hitter_spec(spec_fn(rank)), now)

    def start(self, n: int, timeout: float = 180.0) -> None:
        for rank in range(n):
            parent, child = self.ctx.Pipe(duplex=True)
            spec = self.env.worker_spec(rank, self.cfg)
            p = self.ctx.Process(target=worker_main, args=(child, spec, self.abort), name=f"order-w{rank:02d}", daemon=True)
            p.start()
            child.close()
            self.procs.append(p)
            self.conns.append(parent)
        deadline = self.env.now() + timeout
        pending = set(range(n))
        self.infos = [{} for _ in range(n)]
        while pending:
            if self.env.now() > deadline:
                raise r3w.fr.mrun.CapStop(f"workers {sorted(pending)} not ready after {timeout:.0f} s")
            for i in list(pending):
                if self.conns[i].poll(0.1):
                    kind, payload = self.conns[i].recv()
                    if kind != "ready":
                        raise r3w.fr.mrun.CapStop(f"worker {i} failed to start: {payload}")
                    self.infos[i] = payload
                    pending.discard(i)
                elif not self.procs[i].is_alive():
                    raise r3w.fr.mrun.CapStop(f"worker {i} died during start (exit code {self.procs[i].exitcode})")
