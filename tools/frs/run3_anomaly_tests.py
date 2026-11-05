#!/usr/bin/env python3
"""Step 4 tests (2026-11-04 session): D6 and anomaly keeping (tools/frs/run3_anomaly.py, tools/frs/run3_worker.py, the
tools/glitch/detect.py fixes). Zero native ticks: the in-process tests use the stub world (rl/m8_rd_stub.py); the end-to-end
tests run the REAL crossing-search engine in a guarded child with three workers whose game processes are rl/m8_rd_fakegame.py
behind the real launcher, as tools/frs/det_schedule_tests.py does. THE WORLD IS SYNTHETIC.

    python -B tools/frs/run3_anomaly_tests.py            all tests (a few minutes)
    python -B tools/frs/run3_anomaly_tests.py unit       the in-process tests only
    python -B tools/frs/run3_anomaly_tests.py e2e        the engine runs only

What they show:
    read-only       the proxy returns every reply object unchanged; run3_worker.run_job gives the same result as rl/frs_worker.run_job
                    on the same job (plus `glitch`); the engine with the run 3 workers gives the same dispatches, cells and verified
                    clears as the plain deterministic engine, and every burst's rebuild equals what the worker returned
    D6              a null in a burst reply (in the key or elsewhere) ends that burst before the tick, keeps the earlier reaches, and
                    the run goes on to its cap; the saved words replay to the same null at the same step
    detectors       real crossing vs corner pass vs near-vertex pass vs one-way fall; the hitlag freeze window; live breaks
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
RL = REPO / "rl"
GLITCH = REPO / "tools" / "glitch"
for _p in (RL, HERE, GLITCH):
    sys.path.insert(0, str(_p))

import detect as gd  # noqa: E402
import frs_worker as fw  # noqa: E402
import geometry as gm  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_explore as mx  # noqa: E402
import m8_rd_stub as stub  # noqa: E402
import m8_rd_worker as mw  # noqa: E402
import run3_anomaly as ra  # noqa: E402
import run3_worker as r3w  # noqa: E402
from infra_testlib import check, cleanup, fake_exe, free_port, run_suite, tmpdir  # noqa: E402

PARAMS = {"seeds": 12, "seed_order": "level", "level_decay": 0.5, "novelty_exp": 1.0, "seen_exp": 1.0, "bonus_exp": 1.0, "pace_exp": 0.5,
          "max_segments": 3, "retire_after": 0, "max_cells": 100000, "max_dispatches": 90, "rng_seed": 7}
NONFINITE_P = "0.05"       # per step, only beyond the deepest seed's tick (FAKEGAME_NONFINITE_MIN_STEP), which few bursts pass


# -- in-process helpers (stub world) ---------------------------------------------------------------------------------------------------------


class NullAt:
    """A stub backend whose processes replace one reply field with None at chosen (1-based) steps of chosen acquisitions."""

    def __init__(self, base: stub.StubBackend, at: Mapping[int, int], path: Tuple[str, ...]):
        self.base, self.at, self.path = base, dict(at), path

    def acquire(self, *a: Any, **k: Any) -> Any:
        p = self.base.acquire(*a, **k)
        n, at, path = p.n, self.at, self.path
        orig = p.step

        def step(b: int, x: int, y: int) -> Dict[str, Any]:
            r = orig(b, x, y)
            if at.get(n) == p.steps:
                r = json.loads(json.dumps(r))
                node = r
                for part in path[:-1]:
                    node = node[part]
                node[path[-1]] = None
            return r

        p.step = step
        return p

    def __getattr__(self, name: str) -> Any:
        return getattr(self.base, name)


def stub_ctx(backend: Any, run3: bool) -> Any:
    holder: Dict[str, Any] = {}
    if run3:
        backend = r3w._ProcInfoBackend(backend, holder)

    def ask(payload: Dict[str, Any]) -> Optional[bool]:
        go = int(payload["segment"]) < 2                     # continue once, then stop: two segments
        ctx = holder.get("ctx")
        if ctx is not None and getattr(ctx, "observer", None) is not None:
            ctx.observer.on_decision(payload, go, 0.0)
        return go

    ctx = fw.LabJobContext(backend, None, mcell.Classifier(), 0, None, ask)
    ctx.observer, ctx.last_proc_info = None, {}
    holder["ctx"] = ctx
    return ctx


def stub_jobs() -> List[Dict[str, Any]]:
    """A tick-0 job and two jobs from cells reached by it, built the way crossing_search.next_job builds them."""
    be = stub.StubBackend({"rank": 0, "world": "easy"})
    p = be.acquire()
    reply0, _rec, _rd, _chain, rep0 = mw._tick0(p, None)
    pin = {"obs": list(mcell.obs_tuple(reply0["observation"])), "digest": rep0["digest"]}
    arm = {"segment_words": 40, "max_segments": 3, "window": 40}
    base = {"kind": fw.JOB_KIND, "iteration": 0, "cell": 1, "rep": (1, 0), "words": b"", "end": tuple(mcell.obs_tuple(reply0["observation"])),
            "end_digest": b"", "chain": b"", "terminal": False, "pin": pin, "archive_id": "test|run3|root", "allowance": 120, **arm}
    first = fw.run_job(stub_ctx(stub.StubBackend({"rank": 0, "world": "easy"}), False), base)
    check(first.get("ok") and len(first["reaches"]) >= 3, f"the tick-0 stub job ran and reached cells: {str(first)[:300]}")
    jobs = [base]
    for idx, r in enumerate([first["reaches"][len(first["reaches"]) // 3], first["reaches"][2 * len(first["reaches"]) // 3]]):
        j, key, obs, rd, chain, _t = r
        jobs.append(dict(base, iteration=1 + idx, cell=10 + idx, rep=(10 + idx, j), words=bytes(first["words"][:j]), end=tuple(obs),
                         end_digest=bytes(rd), chain=bytes(chain), archive_id=f"test|run3|c{10 + idx}", allowance=j + 120))
    return jobs


def strip_extra(res: Mapping[str, Any]) -> Dict[str, Any]:
    drop = {"glitch", "run3_worker_contract", "run3_selfcheck", "wall_s", "step_s", "ask_s", "pid"}
    return {k: v for k, v in res.items() if k not in drop}


# -- unit tests ------------------------------------------------------------------------------------------------------------------------------


def unit_nonfinite_scan() -> Dict[str, Any]:
    r = stub.World(stub.WORLDS["easy"]).reply(stub.World(stub.WORLDS["easy"]).initial(), 50)
    check(ra.nonfinite_fields(r) == [], "a normal stub reply has no non-finite field")
    bad = json.loads(json.dumps(r))
    bad["observation"]["position_x"] = None
    bad["spatial"]["fighter"]["carry"] = [float("nan"), 0.0]
    bad["spatial"]["groups"] = [{"translate": [float("inf"), 0.0]}]
    f = ra.nonfinite_fields(bad)
    check("observation.position_x" in f and "spatial.fighter.carry[0]" in f and "spatial.groups[0].translate[0]" in f,
          f"null, NaN and inf are found with their paths: {f}")
    check(ra.nonfinite_fields({"observation": {}}) == ["spatial"], "a missing block is reported")
    return {"fields": f}


def unit_proxy_is_transparent() -> Dict[str, Any]:
    seen: List[Tuple[str, Any]] = []

    class Obs:
        def on_observe(self, reply: Any) -> None:
            seen.append(("observe", id(reply)))

        def on_step(self, i: int, triple: Any, reply: Any, dt: float) -> None:
            seen.append(("step", (i, triple, id(reply))))

    be = r3w.ObservedBackend(stub.StubBackend({"rank": 0, "world": "easy"}))
    be.observer = Obs()
    p = be.acquire()
    r0 = p.observe()
    r1 = p.step(*mcell.TRIPLES[3])
    p.failed = True
    check(seen == [("observe", id(r0)), ("step", (0, tuple(mcell.TRIPLES[3]), id(r1)))], f"the observer sees the same reply objects, in order: {seen}")
    check(p._proc.failed is True and p.mode == p._proc.mode, "attribute writes and reads reach the real process")
    return {"calls": len(seen)}


def unit_run_job_equals_frs_worker() -> Dict[str, Any]:
    """Read-only, in process: run3_worker.run_job == rl/frs_worker.run_job on the same jobs (minus timing and the added keys), and the
    observer's rebuild of each burst equals the worker's result."""
    out = []
    geo = ra.GeometryCache()
    for job in stub_jobs():
        a = fw.run_job(stub_ctx(stub.StubBackend({"rank": 0, "world": "easy"}), False), job)
        b = r3w.run_job(stub_ctx(stub.StubBackend({"rank": 0, "world": "easy"}), True), job, geo, selfcheck=True)
        check(a.get("ok") and b.get("ok"), f"both ran: {a.get('kind')} {b.get('kind')} {str(b.get('error'))[:200]}")
        check(strip_extra(a) == strip_extra(b), f"identical results for job {job['iteration']}: "
                                                f"{sorted(k for k in set(a) | set(b) if strip_extra(a).get(k) != strip_extra(b).get(k))}")
        check(b["run3_selfcheck"]["ok"], f"the observer's rebuild equals the worker's burst: {b['run3_selfcheck']}")
        check(b["glitch"]["contract"] == ra.ANOMALY_CONTRACT and b["glitch"]["error"] is None, f"the live scan ran: {b['glitch'].get('error')}")
        out.append({"L": a["L"], "words": len(a["words"]), "reaches": len(a["reaches"]), "events": len(b["glitch"]["events"]), "segments": a["segments"]})
    return {"jobs": out}


def unit_nonfinite_truncates_burst() -> Dict[str, Any]:
    """D6 in process: a null at burst step s (in the key, then in a non-key field) gives an ok burst truncated before s whose reaches,
    breaks and chain equal the full burst's up to that tick; a null in the prefix stays the prefix mismatch it always was."""
    geo = ra.GeometryCache()
    out = {}
    for job in stub_jobs()[1:]:
        full = fw.run_job(stub_ctx(stub.StubBackend({"rank": 0, "world": "easy"}), False), job)
        L, n = int(full["L"]), len(full["words"])
        s = L + n // 2 + 1                                       # 1-based step of the null, inside the burst
        for path in (("observation", "position_x"), ("observation", "air_velocity_y")):
            be = NullAt(stub.StubBackend({"rank": 0, "world": "easy"}), {1: s}, path)
            res = r3w.run_job(stub_ctx(be, True), job, geo)
            check(res.get("ok") and res["end_reason"] == "nonfinite", f"{path}: an ok burst ending 'nonfinite': {res.get('kind')} {str(res.get('error'))[:300]}")
            check(res["nonfinite"]["step"] == s - 1 and ".".join(("",) + path)[1:] in res["nonfinite"]["fields"], f"the step and field are recorded: {res['nonfinite']}")
            k = s - 1 - L                                        # burst words before the null
            check(bytes(res["words"]) == bytes(full["words"][:k]) and res["ticks"] == L + k, "the burst is cut just before the null")
            want = [r for r in full["reaches"] if int(r[0]) <= L + k]
            check([(r[0], tuple(r[1])) for r in res["reaches"]] == [(r[0], tuple(r[1])) for r in want], "the earlier reaches are kept, unchanged")
            check([list(b) for b in res["breaks_all"]] == [list(b) for b in full["breaks_all"] if int(b[0]) <= L + k], "the earlier breaks are kept")
            if want:
                check(bytes(res["reaches"][-1][4]) == bytes(want[-1][4]), "the chain at the last kept reach equals the full burst's")
            ev = res["nonfinite"]["event"]
            check(ev["schema"] == gd.EVENT_SCHEMA and ev["kind"] == "nonfinite" and ev["needs_replay"], f"a btt_glitch_event_v1 nonfinite event: {ev}")
            check(len(res["nonfinite"]["replies"]) == k + 1 and res["nonfinite"]["replies"][-1]["observation"].get(path[1], 0) is None,
                  "the replies from L to the null are kept for the replay file")
            out[f"job{job['iteration']}_{path[1]}"] = {"L": L, "null_step": s - 1, "kept_reaches": len(res["reaches"]), "of": len(full["reaches"])}
        be = NullAt(stub.StubBackend({"rank": 0, "world": "easy"}), {1: max(1, L // 2)}, ("observation", "position_x"))
        res = r3w.run_job(stub_ctx(be, True), job, geo)
        check(res.get("kind") == "mismatch" and res.get("mismatch") == "prefix_end", f"a null in the prefix is the prefix mismatch: {res.get('kind')} {res.get('mismatch')}")
    return out


def _scan(spec: List[Tuple[int, List[Tuple[int, int]], int]], path: List[Tuple[float, float, int]], extra: Optional[Dict[int, Any]] = None) -> gd.Detector:
    """tools/glitch/test_glitch.py's synthetic geometry and trace builders, then the offline detector."""
    import test_glitch as tg

    geo = gm.derive(tg.raw_from_lines(spec), "test")
    d = gd.Detector(tg.make_trace(geo, path, extra=extra), geo)
    d.run()
    return d


def unit_detector_rules() -> Dict[str, Any]:
    """Synthetic geometry (a solid block x 0..1000, y 0..1000; a one-way floor): what is emitted and what is only counted."""
    import test_glitch as tg

    block = tg.box(0, 0, 1000, 1000)
    oneway = [(gm.KIND_FLOOR, [(2000, 500), (3000, 500)], gm.VERTEX_COLL_PASS)]
    spec = tg.sorted_spec(block + oneway)
    # 1. a real crossing: the right point (x + 150) enters the left wall's face mid-height and ends behind it, inside its span
    d1 = _scan(spec, [(-200.0, 300.0, 1), (-170.0, 300.0, 1), (-140.0, 300.0, 1)])
    check(d1.counts.get("line_crossing", 0) >= 1, f"a real crossing is emitted: {d1.counts}")
    # 2. a corner pass: clamped on the wall plane (right point at x 0), rising past its top end
    d2 = _scan(spec, [(-150.0, 700.0, 1), (-150.0, 780.0, 1), (-130.0, 860.0, 1)])
    check(d2.counts.get("corner_pass", 0) >= 1 and "line_crossing" not in d2.counts, f"a corner pass is counted, not emitted: {d2.counts}")
    check("corner_pass_near_vertex" not in d2.counts, "a corner pass far from the vertex is not logged")
    # 3. the same pass through the vertex within float error: logged
    d3 = _scan(spec, [(-150.0, 700.0, 1), (-150.0, 810.0, 1), (-130.0, 830.0, 1)])
    near = [e for e in d3.events if e["kind"] == "corner_pass_near_vertex"]
    check(near and near[0]["evidence"]["distance"] <= gd.Params().vertex_eps, f"a pass through the convex vertex is logged: {d3.counts}")
    # 4. a fall through the one-way floor (bottom point from above to below, inside its span)
    d4 = _scan(spec, [(2500.0, 520.0, 1), (2500.0, 505.0, 1), (2500.0, 480.0, 1)])
    check(any(e["kind"] == "pass_through" for e in d4.events) and "line_crossing" not in d4.counts, f"a one-way fall is a pass_through event: {d4.counts}")
    return {"crossing": d1.counts.get("line_crossing"), "corner_pass": d2.counts.get("corner_pass"), "near": near[0]["evidence"]["distance"],
            "pass_through": d4.counts.get("pass_through")}


def unit_freeze_window() -> Dict[str, Any]:
    """An exactly unchanged position whose velocity predicts motion: hitlag only within hitlag_window (11) ticks of a break."""
    import test_glitch as tg

    spec = tg.sorted_spec(tg.box(-5000, -6000, 5000, -5500))
    W = gd.Params().hitlag_window
    out = {}
    for since, want in ((0, "freeze:after_break"), (W, "freeze:after_break"), (W + 1, "freeze:unexplained"), (None, "freeze:unexplained")):
        n = 30
        path = [(float(10 * i), 0.0, 1) for i in range(n)]
        path += [(path[-1][0], 0.0, 1)]                        # frozen at the last step, the recorded velocity still 10
        extra: Dict[int, Any] = {len(path) - 1: {"observation": {"air_velocity_x": 10.0}}}
        if since is not None:
            for i in range(len(path)):
                mask = 1 if i < len(path) - 1 - since else 0
                extra.setdefault(i, {}).setdefault("spatial", {})["target_live_mask"] = mask
        d = _scan(spec, path, extra)
        got = "freeze:after_break" if d.counts.get("freeze:after_break") else "freeze:unexplained" if d.counts.get("freeze:unexplained") else None
        check(got == want, f"since break {since}: {want} expected, got {got} ({d.counts})")
        out[str(since)] = got
    return out


def unit_live_scanner_equals_detector() -> Dict[str, Any]:
    """LiveScanner fed one reply at a time == Detector.run, on stored lab traces when the lab is present (skipped otherwise)."""
    import gzip

    traces = sorted(Path("C:/BattleShip_lab/splice_probe_2026-10-14/run/traces").glob("*.json.gz"))[:6]
    if not traces:
        return {"skipped": "no lab traces on this machine"}
    n = 0
    for p in traces:
        t = json.load(gzip.open(p, "rt", encoding="utf-8"))
        for live in (False, True):
            tr = t if not live else {"initial": {k: v for k, v in t["initial"].items() if k not in ("entity", "targets", "input")},
                                     "steps": [{k: v for k, v in r.items() if k not in ("entity", "targets", "input")} for r in t["steps"]]}
            d = gd.Detector(tr, source={"trace": p.name})
            d.run()
            ls = gd.LiveScanner(tr["initial"], source={"trace": p.name}, emit_from=0)
            for i, r in enumerate(tr["steps"]):
                ls.feed(i, r, stick_x=(r.get("input") or {}).get("stick_x"))
            sig = lambda evs: sorted((e["step"], e["kind"], json.dumps(e["evidence"], sort_keys=True, default=str)) for e in evs)
            check(sig(ls.finish()) == sig(d.events) and ls.counts == d.counts, f"{p.name} live={live}: the same events and counts")
            n += 1
    return {"pairs": n}


# -- end-to-end on the fake game (the real engine, launcher and pool) -------------------------------------------------------------------------


RUN_CHILD = r'''
import json, sys, types
from pathlib import Path
sys.path.insert(0, {rl!r}); sys.path.insert(0, {here!r})
import frs_guard as g
lab = Path({lab!r})
g.LabGuard.install(lab)
import frs_machine as fm, frs_run as fr, frs_verify as fv, m8_rd_stub as stub, crossing_search as cs, det_schedule as det
import run3_anomaly as ra, run3_worker as r3w
out = Path({out!r}); run_dir = out / "run"; frontier = Path({frontier!r}); exe = Path({exe!r})
params = cs.Params(**{params!r})
P = cs.plan_and_write(lab, frontier, out, params, stub.analyse)
flags = {flags!r}
worker_flags = dict(flags)
if {nonfinite!r}:
    worker_flags.update({{"FAKEGAME_NONFINITE_P": {nonfinite_p!r}, "FAKEGAME_NONFINITE_SEED": "11", "FAKEGAME_NONFINITE_FIELD": {field!r},
                         "FAKEGAME_NONFINITE_MIN_STEP": str(max(int(s["tick"]) for s in P["seeds"]) + 1)}})
frozen = {{"frozen_sha256": {frozen!r}, "exe_copy_sha256": {exe_copy!r}}}
spec = lambda rank: {{"rank": rank, "root": str(lab / ("run_w%d" % rank)), "executable": str(exe), "flags": dict(worker_flags),
                     "frozen_dir": str(exe.parent), "frozen_sha256": {frozen!r}, "port_base": {port_base!r}, "port_size": 250,
                     "timeouts": {{"startup": 30.0, "ready": 30.0, "request": 15.0, "exit": 15.0}}, "failure_dir": str(run_dir / "failures"),
                     "guard": g.LabGuard.spec(), "run3_selfcheck": True}}
env = fr.LabEnv(worker_spec=spec, replay=fv.make_real_replay(exe, lab / "run_replays", flags, frozen), analyse=stub.analyse,
                readiness=lambda: {{"ok": True, "problems": []}}, battleship_pids=lambda: [], snapshot=fm.tree_snapshot, import_problems=lambda: [],
                wait_no_battleship=lambda t: [], code_manifest=fr.code_manifest, backend="real", sample_s=0.25, row_every_s=0.5,
                caps=dict(fm.CAPS_MB, main_private=1e9))
cfg = cs.SearchConfig(lab_root=lab, out=out, run_dir=run_dir, frontier_dir=frontier, n_workers=3, max_ticks=10 ** 9, max_wall_s=600.0,
                      expect_code=None, stop_grace_s=60.0, verify_floor_s=5.0, verify_s_per_clear=2.0, write_reserve_s=2.0, progress_every_s=2.0,
                      seed_parallel=3)
if {run3!r}:
    # test-only: the pool class is chosen here; run 3's own open() (step 8) will start r3w.Run3Pool itself
    cs.fr = types.SimpleNamespace(**dict(vars(fr), FrsPool=r3w.Run3Pool))
    class Engine(det.DeterministicSchedule, ra.AnomalyIngest, cs.Search):
        pass
    engine = Engine(cfg, env, P, params, anomaly_build={{"exe": "fake", "platform": sys.platform}})
else:
    engine = det.DetSearch(cfg, env, P, params)
code = engine.run()
print(json.dumps({{"code": code, "violations": g.LabGuard.violations[:3], "worker_flags": worker_flags}}))
'''


def read_jsonl(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.is_file() else []


class Bench:
    def __init__(self) -> None:
        import crossing_search_tests as cst

        self.lab = tmpdir("run3_anomaly_lab_")
        self.frontier = cst.synthetic_frontier(self.lab)["out"]
        self.exe = fake_exe(self.lab / "fake")
        self.frozen = {n: mw.sha256_file(self.exe.parent / n) for n in mw.FROZEN_FILES}
        self.exe_copy = {n: mw.sha256_file(self.exe.parent / n) for n in (self.exe.name, "BattleShip.o2r", "f3d.o2r", "gamecontrollerdb.txt")}
        self.flags = {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1", "SSB64_RL_SPATIAL": "1", "FAKEGAME_WORLD": "easy",
                      "FAKEGAME_BOOT_S": "0.1", "FAKEGAME_IDLE_S": "60", "FAKEGAME_STEP_JITTER_S": "0.002"}
        self.port = 31000

    def run(self, name: str, *, run3: bool, nonfinite: bool = False, field: str = "observation.position_x") -> Dict[str, Any]:
        out = self.lab / f"out_{name}"
        self.port += 1000
        code = RUN_CHILD.format(rl=str(RL), here=str(HERE), lab=str(self.lab), out=str(out), frontier=str(self.frontier), exe=str(self.exe),
                                params=PARAMS, flags=self.flags, frozen=self.frozen, exe_copy=self.exe_copy, run3=run3, nonfinite=nonfinite,
                                nonfinite_p=NONFINITE_P, field=field, port_base=self.port)
        r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=1200, cwd=str(self.lab))
        try:
            res = json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            raise AssertionError(f"{name}: child failed: {(r.stderr or r.stdout)[-2500:]}")
        d = out / "run"
        res.update({"dir": d, "summary": json.loads((d / "summary.json").read_text(encoding="utf-8")),
                    "dispatches": read_jsonl(d / "dispatches.jsonl"), "cells": read_jsonl(d / "cells.jsonl"),
                    "verifications": read_jsonl(d / "verifications.jsonl"), "events": read_jsonl(d / "glitch_events.jsonl"),
                    "bursts": read_jsonl(d / "anomaly_bursts.jsonl"), "replays": sorted((d / "anomalies").glob("*.json.gz")) if (d / "anomalies").is_dir() else []})
        return res

    def close(self) -> None:
        if os.environ.get("RUN3_KEEP") == "1":
            print(f"kept: {self.lab}")
            return
        cleanup(self.lab)


_BENCH: Optional[Bench] = None


def bench() -> Bench:
    global _BENCH
    if _BENCH is None:
        _BENCH = Bench()
    return _BENCH


def _clean(r: Dict[str, Any]) -> None:
    check(r["code"] == 0 and not r["violations"], f"the run completed cleanly: {r['code']} {r['violations']} {r['summary'].get('status')} "
                                                   f"{r['summary'].get('stop')} (folder {r['dir']})")
    check(r["summary"]["status"] == "DISPATCH_CAP" and r["summary"]["work"]["dispatches"] == PARAMS["max_dispatches"],
          f"stopped at the dispatch cap: {r['summary']['status']} {r['summary']['work']['dispatches']}")


def e2e_engine_read_only() -> Dict[str, Any]:
    """The run 3 workers and the anomaly ingest change nothing: same seed, same dispatches, cells and verified clears as the plain
    deterministic engine; every burst's rebuild equals the worker's result; events carry their dispatch."""
    import det_schedule as det

    b = bench()
    plain = b.run("plain", run3=False)
    obs = b.run("run3", run3=True)
    for r in (plain, obs):
        _clean(r)
    check(det.dispatch_signature(plain["dispatches"]) == det.dispatch_signature(obs["dispatches"]), "the same dispatch sequence")
    check(det.cells_signature(plain["cells"]) == det.cells_signature(obs["cells"]), "the same cell events")
    vs = lambda r: sorted((v.get("n"), v.get("verdict"), v.get("completion_input_tick")) for v in r["verifications"])
    check(vs(plain) == vs(obs), "the same verified clears")
    an = obs["summary"].get("anomalies") or {}
    sc = an.get("selfcheck") or {}
    check(sc.get("checked", 0) >= PARAMS["max_dispatches"] - 3 and sc.get("failed") == 0, f"every burst's rebuild equals the worker's: {sc}")
    for e in obs["events"]:
        check(e["schema"] == gd.EVENT_SCHEMA and e["source"].get("n") and e["source"].get("words_digest") and e.get("build"), f"an event row with its dispatch: {e}")
    ns = {e["source"]["n"] for e in obs["events"]}
    check(ns == {x["n"] for x in obs["bursts"]}, "one anomaly_bursts row per burst with an event")
    check(not obs["replays"] and not any(d.get("outcome") == "nonfinite" for d in obs["dispatches"]), "no non-finite outcome without the injection")
    return {"dispatches": len(obs["dispatches"]), "cells": len(obs["cells"]), "verified": len(obs["verifications"]), "selfcheck": sc,
            "events": an.get("by_kind"), "bursts_with_events": an.get("bursts"), "scan_errors": an.get("scan_errors")}


def _replay_fake(exe_flags: Mapping[str, str], words: bytes) -> List[Dict[str, Any]]:
    """The saved words stepped from tick 0 in a fresh fake-game process (NDJSON protocol 1), every reply returned."""
    port = free_port()
    env = dict(os.environ, SSB64_RL_PORT=str(port), **{k: v for k, v in exe_flags.items()})
    p = subprocess.Popen([sys.executable, "-B", str(RL / "m8_rd_fakegame.py")], env=env, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 20.0
        while True:
            try:
                s = socket.create_connection(("127.0.0.1", port), timeout=2.0)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.05)
        f = s.makefile("rwb")

        def req(**kw: Any) -> Dict[str, Any]:
            f.write((json.dumps(dict(kw, protocol=1)) + "\n").encode("utf-8"))
            f.flush()
            return json.loads(f.readline().decode("utf-8"))

        while not req(op="status").get("can_step"):
            time.sleep(0.05)
        out = []
        for w in words:
            bb, x, y = mcell.TRIPLES[w]
            out.append(req(op="step", buttons=bb, stick_x=x, stick_y=y))
        s.close()
        return out
    finally:
        p.kill()
        p.wait(timeout=10)


def e2e_nonfinite_keeps_running() -> Dict[str, Any]:
    """D6 end to end: with nulls injected in burst replies (the key field), the run reaches its cap, every such burst is ingested up
    to the tick before, its anomaly is kept, and its saved words replay to the same null at the same step. Twice with the same seed:
    the same dispatches and the same anomalies (D4)."""
    import det_schedule as det
    import gzip

    b = bench()
    r1 = b.run("nan_a", run3=True, nonfinite=True)
    r2 = b.run("nan_b", run3=True, nonfinite=True)
    for r in (r1, r2):
        _clean(r)
    nan_rows = [d for d in r1["dispatches"] if d.get("outcome") == "nonfinite"]
    reach = max((int(d.get("start_tick") or 0) + int(d.get("words_played") or 0) for d in r1["dispatches"]), default=0)
    check(nan_rows, f"at least one burst met a null (p = {NONFINITE_P} per step from step {r1['worker_flags'].get('FAKEGAME_NONFINITE_MIN_STEP')}; "
                    f"the furthest burst reached tick {reach}): outcomes {sorted({d.get('outcome') for d in r1['dispatches']})}")
    check(len(r1["replays"]) == len(nan_rows) == (r1["summary"].get("anomalies") or {}).get("nonfinite"),
          f"one replay file per non-finite burst: {len(r1['replays'])} files, {len(nan_rows)} rows")
    check(all(d.get("kept") is not None for d in nan_rows), "the truncated bursts went through the engine's own ingest (kept counts recorded)")
    check(any(int(d.get("reaches") or 0) > 0 for d in nan_rows), f"reaches before the null were offered to the archive: "
                                                                 f"{[(d['n'], d.get('words_played'), d.get('reaches'), d.get('kept')) for d in nan_rows][:4]}")
    check(det.dispatch_signature(r1["dispatches"]) == det.dispatch_signature(r2["dispatches"]), "the same dispatches in both runs")
    sig = lambda r: sorted((x["n"], x["words_digest"], tuple(x["kinds"])) for x in r["bursts"])
    check(sig(r1) == sig(r2), "the same anomaly bursts in both runs")
    rec = json.load(gzip.open(r1["replays"][0], "rt", encoding="utf-8"))
    words = bytes.fromhex(rec["words_hex"])
    flags = dict(r1["worker_flags"])
    replies = _replay_fake(flags, words)
    bad = [i for i, rep in enumerate(replies) if ra.nonfinite_fields(rep)]
    check(bad == [len(words) - 1] and bad[0] == rec["step"], f"the saved words replay to the same null at the same step: {bad} vs {rec['step']}")
    return {"nonfinite_bursts": len(nan_rows), "replay_files": len(r1["replays"]), "replayed_null_at": bad[0], "words": len(words),
            "events": (r1["summary"].get("anomalies") or {}).get("by_kind")}


UNIT = {"unit_nonfinite_scan": unit_nonfinite_scan, "unit_proxy_is_transparent": unit_proxy_is_transparent,
        "unit_run_job_equals_frs_worker": unit_run_job_equals_frs_worker, "unit_nonfinite_truncates_burst": unit_nonfinite_truncates_burst,
        "unit_detector_rules": unit_detector_rules, "unit_freeze_window": unit_freeze_window,
        "unit_live_scanner_equals_detector": unit_live_scanner_equals_detector}
E2E = {"e2e_engine_read_only": e2e_engine_read_only, "e2e_nonfinite_keeps_running": e2e_nonfinite_keeps_running}

if __name__ == "__main__":
    args = sys.argv[1:]
    tests = dict(UNIT) if args[:1] == ["unit"] else dict(E2E) if args[:1] == ["e2e"] else dict(UNIT, **E2E)
    rest = [a for a in args if a not in ("unit", "e2e")]
    try:
        code = run_suite("run3 anomaly tests", tests, rest)
    finally:
        if _BENCH is not None:
            _BENCH.close()
    sys.exit(code)
