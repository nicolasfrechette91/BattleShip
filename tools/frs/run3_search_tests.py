#!/usr/bin/env python3
"""Step 5 tests (2026-11-05 session): the fused first dispatch (rl/frs_worker.FUSED_END_MODE), end records, run 3's engine core with
deterministic scheduling (tools/frs/run3_search.py) and the end-record merge (tools/frs/run3_archive.py). Zero native ticks: the in-process
tests use the stub world (rl/m8_rd_stub.py); the `fake` and `e2e` tests run fake game processes (rl/m8_rd_fakegame.py, the stub world
behind the real launcher and the M1d client) in guarded children. THE WORLD IS SYNTHETIC.

    python -B tools/frs/run3_search_tests.py            every test (several minutes)
    python -B tools/frs/run3_search_tests.py unit       the in-process tests only
    python -B tools/frs/run3_search_tests.py fake       the field-by-field test on the fake game (worker level)
    python -B tools/frs/run3_search_tests.py e2e        the engine runs on the fake game

The owner's conditions (2026-11-05):
    1 coverage   for EACH of the 17 observation fields of a cell's end record, alone, a minimal change of value (and of JSON type where
                 one exists) in the reply at the end of the prefix: the fused dispatch must detect it exactly when the stored-end
                 dispatch does. The comparison checks 16 of the 17 (host_frame is ignored by obs_diffs and absent from the record), so
                 the expected table is 16 detected in both modes and host_frame detected in neither (`fake_field_by_field`; the same
                 on records alone in `unit_digest_covers_compared_fields`)
    2 mismatch   a fused dispatch whose prefix does not reproduce: a prefix mismatch, the cell quarantined, no end record, no burst word,
                 the fake game stepped exactly L times, the dispatch row, event and log as run 2 writes them (`e2e_fused_mismatch`)
    3 run 2      a job without end_mode gives exactly the result of the worker before the change (`unit_run2_path_equals_pre_change`,
                 the pre-change file read from git); the existing suites are run separately
    4 O10 + D4   the stored end record is used by every later dispatch of the representative (full comparison); D4 accepts the archive;
                 two same-seed runs with fused first dispatches give the same dispatches, cells and end records (`e2e_fused_runs`)
    code digest  (2026-11-05) the run 3 manifest (tools/frs/run3_manifest.py) covers every run 3 file; a wrong recorded digest is
                 refused at the open; every run records it and finds it unchanged at the close (`unit_run3_manifest`,
                 `e2e_code_digest_refusal`, `_clean`)
    stored       (2026-11-05, before step 6) forced redraws: >= 30 later dispatches compare against a record stored in the run, and in a
                 second run >= 30 against records read from cells.jsonl, one of which has a single compared field changed: a prefix_end
                 mismatch naming that field, 0 burst words, L steps, quarantined (`e2e_stored_records`, `unit_end_record_import`)
"""
from __future__ import annotations

import copy
import gzip
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

assert sys.flags.dont_write_bytecode, "run with python -B"

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
RL = REPO / "rl"
for _p in (RL, HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import frs_worker as fw  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_stub as stub  # noqa: E402
import m8_rd_worker as mw  # noqa: E402
import run3_archive as ar  # noqa: E402
import run3_worker as r3w  # noqa: E402
from infra_testlib import check, cleanup, fake_exe, run_suite, tmpdir  # noqa: E402

PRE_CHANGE_COMMIT = "39e20cacd41cea30a67e572aa57fc6be67938d37"     # the last commit of rl/frs_worker.py before the fused mode
HOST = mcell.HOST_FRAME
FIELDS = mcell.OBS_FIELDS
TIMING = ("wall_s", "step_s", "ask_s", "pid", "startup", "glitch", "run3_worker_contract", "run3_selfcheck")
RUN3_PARAMS = {"seeds": 1, "seed_order": "level", "level_decay": 0.5, "novelty_exp": 1.0, "seen_exp": 1.0, "bonus_exp": 1.0, "pace_exp": 0.5,
               "max_segments": 3, "retire_after": 0, "max_cells": 100000, "max_dispatches": 120, "rng_seed": 5, "cleared_weight": 0.1,
               "check_slots": 1, "check_queue_max": 4, "eager_levels": 0, "eager_max_min": 15.0, "canary_per_level": 1, "reset_novelty": False,
               "check_error_limit": 10}


def alter(v: Any, kind: str) -> Tuple[bool, Any]:
    """(applicable, the altered value): `value` the smallest change (int + 1, the next float up), `type` the same value in the other JSON
    number type (int -> float; an integral float -> int)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise AssertionError(f"an observation value of type {type(v).__name__}: {v!r}")
    if kind == "value":
        return True, (v + 1 if isinstance(v, int) else math.nextafter(v, math.inf))
    if isinstance(v, int):
        return True, float(v)
    return (True, int(v)) if float(v).is_integer() else (False, None)


def stub_cell_jobs() -> List[Dict[str, Any]]:
    import run3_anomaly_tests as rat

    return rat.stub_jobs()


def strip(res: Mapping[str, Any]) -> Dict[str, Any]:
    out = {k: v for k, v in res.items() if k not in TIMING}
    if isinstance(out.get("detail"), dict):
        out["detail"] = {k: v for k, v in out["detail"].items() if k != "preserved"}
    return out


# -- unit tests (in process, stub world) -----------------------------------------------------------------------------------------------------


def unit_digest_covers_compared_fields() -> Dict[str, Any]:
    """On records alone: a one-field change of the reply changes the record digest exactly when obs_diffs reports it (16 fields, value
    and JSON type); host_frame changes neither."""
    p = stub.StubBackend({"rank": 0, "world": "easy"}).acquire()
    p.observe()
    rep = None
    for i in range(37):
        rep = p.step(*mcell.TRIPLES[(7 * i + 3) % len(mcell.TRIPLES)])
    assert rep is not None
    check(set(mcell.record_of(rep)["o"]) == set(mcell.OBS_NO_HOST) and len(FIELDS) == 17 and len(mcell.OBS_NO_HOST) == 16,
          "the record holds the 16 non-host fields of the 17")
    base_t = mcell.obs_tuple(rep["observation"])
    base_d = mcell.record_digest(mcell.record_of(rep))
    rows = {}
    for f in FIELDS:
        for kind in ("value", "type"):
            ok, nv = alter(rep["observation"][f], kind)
            if not ok:
                continue
            r2 = copy.deepcopy(rep)
            r2["observation"][f] = nv
            digest_differs = mcell.record_digest(mcell.record_of(r2)) != base_d
            compared = bool(mcell.obs_diffs(mcell.obs_tuple(r2["observation"]), base_t))
            rows[f"{f}/{kind}"] = (digest_differs, compared)
            check(digest_differs == compared == (f != "host_frame"), f"{f} ({kind} {rep['observation'][f]!r} -> {nv!r}): digest differs {digest_differs}, "
                                                                     f"obs_diffs reports {compared}")
    return {"alterations": len(rows), "detected": sum(1 for d, _c in rows.values() if d), "host_frame": [k for k in rows if k.startswith("host_frame")]}


def unit_worker_refusals() -> Dict[str, Any]:
    """A malformed end mode is an error before any process is acquired."""
    jobs = stub_cell_jobs()
    cell = jobs[1]

    class Count:
        def __init__(self) -> None:
            self.base, self.n = stub.StubBackend({"rank": 0, "world": "easy"}), 0

        def acquire(self, *a: Any, **k: Any) -> Any:
            self.n += 1
            return self.base.acquire(*a, **k)

        def __getattr__(self, name: str) -> Any:
            return getattr(self.base, name)

    be = Count()
    ctx = fw.LabJobContext(be, None, mcell.Classifier(), 0, None, None)
    bad = {"fused with an end record": dict(cell, end_mode=fw.FUSED_END_MODE),
           "unknown end mode": dict(cell, end=None, end_mode="lazy"),
           "fused at tick 0": dict(jobs[0], end=None, end_mode=fw.FUSED_END_MODE)}
    out = {}
    for name, job in bad.items():
        res = fw.run_job(ctx, job)
        check(res["ok"] is False and res["kind"] == "error" and "bad end mode" in res["error"], f"{name}: {strip(res)}")
        out[name] = res["error"][:80]
    check(be.n == 0, f"no process was acquired for a refused job ({be.n})")
    return out


def unit_stub_fused_equals_stored() -> Dict[str, Any]:
    """Same cell, same key: the fused job's result is the stored-end job's except the prefix fields; the end record it returns equals the
    stored one in the 16 compared fields. The same through run3_worker.run_job, and for a D6 truncation of a fused dispatch."""
    import run3_anomaly as ra
    import run3_anomaly_tests as rat

    jobs = stub_cell_jobs()
    n = 0
    for job in jobs[1:]:
        fj = dict(job, end=None, end_mode=fw.FUSED_END_MODE)
        for runner in ("frs_worker", "run3_worker"):
            if runner == "frs_worker":
                a = fw.run_job(rat.stub_ctx(stub.StubBackend({"rank": 0, "world": "easy"}), False), job)
                b = fw.run_job(rat.stub_ctx(stub.StubBackend({"rank": 0, "world": "easy"}), False), fj)
            else:
                geo = ra.GeometryCache()
                a = r3w.run_job(rat.stub_ctx(stub.StubBackend({"rank": 0, "world": "easy"}), True), job, geo, True)
                b = r3w.run_job(rat.stub_ctx(stub.StubBackend({"rank": 0, "world": "easy"}), True), fj, geo, True)
            check(a["ok"] and b["ok"], f"{runner}: both ran: {str(strip(a))[:200]} / {str(strip(b))[:200]}")
            pa, pb = a.pop("prefix"), b.pop("prefix")
            check(strip(a) == strip(b), f"{runner}: everything but the prefix is equal")
            check(set(pa) == {"words", "cut", "terminal", "end_equal", "chain_equal", "end_digest_equal", "host_frame_equal"}, f"{runner}: stored prefix keys {sorted(pa)}")
            check(pb["end_mode"] == fw.FUSED_END_MODE and pb["chain_equal"] is True and pb["end_digest_equal"] is True and pb["end_equal"] is None
                  and pb["host_frame_equal"] is None and not mcell.obs_diffs(tuple(pb["end"]), tuple(job["end"])), f"{runner}: fused prefix {pb}")
            n += 1
    # D6 inside a fused dispatch: the truncated result carries the fused prefix and its end record
    job = jobs[1]
    L = len(job["words"])
    fj = dict(job, end=None, end_mode=fw.FUSED_END_MODE)
    be = rat.NullAt(stub.StubBackend({"rank": 0, "world": "easy"}), {1: L + 5}, ("observation", "position_x"))
    res = r3w.run_job(rat.stub_ctx(be, True), fj, ra.GeometryCache(), False)
    check(res["ok"] and res["end_reason"] == "nonfinite" and len(res["words"]) == 4 and res["prefix"]["end_mode"] == fw.FUSED_END_MODE
          and not mcell.obs_diffs(tuple(res["prefix"]["end"]), tuple(job["end"])), f"a D6 truncation of a fused dispatch: {str(strip(res))[:400]}")
    return {"pairs": n, "d6_words": len(res["words"])}


def _pre_change_worker() -> Any:
    r = subprocess.run(["git", "show", f"{PRE_CHANGE_COMMIT}:rl/frs_worker.py"], cwd=str(REPO), capture_output=True)
    if r.returncode != 0:
        return None
    d = tmpdir("frs_worker_pre_")
    p = d / "frs_worker_pre.py"
    p.write_bytes(r.stdout)
    saved = list(sys.path)
    try:
        spec = importlib.util.spec_from_file_location("frs_worker_pre", p)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
    finally:
        sys.path[:] = saved
        cleanup(d)
    return mod


def unit_run2_path_equals_pre_change() -> Dict[str, Any]:
    """Condition 3: every job without end_mode (ok, cut, terminal expected, each prefix mismatch) gives the same result from the worker
    after the change as from the file before it (git show PRE_CHANGE_COMMIT), timing fields aside."""
    import run3_anomaly_tests as rat

    old = _pre_change_worker()
    if old is None:
        return {"skipped": "git show failed (no git or no history)"}
    jobs = stub_cell_jobs()
    cell = jobs[1]
    end = list(cell["end"])
    end[mcell.OBS_INDEX["position_x"]] = math.nextafter(end[mcell.OBS_INDEX["position_x"]], math.inf)
    cases = {"tick0": jobs[0], "cell_a": jobs[1], "cell_b": jobs[2], "cut": dict(cell, allowance=len(cell["words"]) - 3),
             "end_field": dict(cell, end=tuple(end)), "end_type": dict(cell, end=tuple(float(v) if isinstance(v, int) and i != HOST else v for i, v in enumerate(cell["end"]))),
             "chain": dict(cell, chain=b"\x00" * 32), "end_digest": dict(cell, end_digest=b"\x00" * 32), "terminal": dict(cell, terminal=True),
             "host_frame_only": dict(cell, end=tuple(v + 7 if i == HOST else v for i, v in enumerate(cell["end"])))}
    kinds = {}
    for name, job in cases.items():
        a = old.run_job(rat.stub_ctx(stub.StubBackend({"rank": 0, "world": "easy"}), False), job)
        b = fw.run_job(rat.stub_ctx(stub.StubBackend({"rank": 0, "world": "easy"}), False), job)
        check(strip(a) == strip(b), f"{name}: the result differs from the pre-change worker:\n{str(strip(a))[:600]}\n{str(strip(b))[:600]}")
        kinds[name] = b.get("mismatch") or b.get("end_reason") or b.get("kind")
    check(kinds["end_field"] == kinds["end_type"] == kinds["chain"] == kinds["end_digest"] == "prefix_end" and kinds["terminal"] == "terminal_expected"
          and kinds["cut"] == "cut", f"the cases covered what they should: {kinds}")
    return {"cases": kinds, "pre_change": PRE_CHANGE_COMMIT[:10]}


def unit_merge_end_records() -> Dict[str, Any]:
    """run3_archive reads end records back: from NEW / REPLACED rows and from end_record rows (never a representative), by digest."""
    d = tmpdir("run3_ends_")
    try:
        e1 = [1, 50, 50, 49, 1, 1, 9, 1, 10.0, 20.0, 0.0, 0.0, 0.0, 1, 0, 10, 0]
        e2 = list(e1)
        e2[HOST] = 999
        rows1 = [{"cid": 1, "ev": "new", "key": [0, 0, "G", 1022, 3], "level": 1, "tick": 50, "digest": "d1"},
                 {"cid": 2, "ev": "new", "key": [1, 0, "A2", 1020, -1], "level": 2, "tick": 80, "digest": "d2"}]
        rows3 = [{"cid": 1, "ev": ar.END_RECORD_EV, "key": [0, 0, "G", 1022, 3], "level": 1, "tick": 50, "digest": "d1", "end": e1, "n": 4},
                 {"cid": 2, "ev": ar.END_RECORD_EV, "key": [1, 0, "A2", 1020, -1], "level": 2, "tick": 80, "digest": "d2", "end": e1, "n": 5},
                 {"cid": 2, "ev": "replaced", "key": [1, 0, "A2", 1020, -1], "level": 2, "tick": 70, "digest": "d2b", "end": e2, "n": 9},
                 {"cid": 1, "ev": ar.END_RECORD_EV, "key": [0, 0, "G", 1022, 3], "level": 1, "tick": 50, "digest": "d1", "end": e2, "n": 6}]
        a, b = d / "r1.jsonl", d / "r3.jsonl"
        a.write_text("".join(json.dumps(r) + "\n" for r in rows1), encoding="utf-8")
        b.write_text("".join(json.dumps(r) + "\n" for r in rows3), encoding="utf-8")
        cells, rep = ar.merged_cells([a, b])
        ar.require_consistent(rep)
        check(cells[1]["ev"] == "new" and cells[1]["end"] == e1 and cells[2]["digest"] == "d2b" and cells[2]["end"] == e2,
              f"end records attached by digest, an end_record row is never the representative: {cells}")
        check(rep["end_record_rows"] == 3 and rep["with_end_record"] == 2 and rep["multi_row_cells"] == 1 and not rep["end_conflicts"],
              f"report {rep}")
        bad = d / "bad.jsonl"
        e3 = list(e1)
        e3[mcell.OBS_INDEX["position_x"]] = 10.5
        bad.write_text(json.dumps(dict(rows3[0], end=e3)) + "\n", encoding="utf-8")
        _c, rep2 = ar.merged_cells([a, b, bad])
        check(rep2["end_conflicts"] == [1], f"two end records of one representative that differ in a compared field: {rep2['end_conflicts']}")
        try:
            ar.require_consistent(rep2)
            raise AssertionError("conflicting end records were accepted")
        except ar.ArchiveKeyError:
            pass
        return {"cells": len(cells), "end_record_rows": rep["end_record_rows"]}
    finally:
        cleanup(d)


def unit_d4_reads_no_lazy_check() -> Dict[str, Any]:
    """The number D4's refusal reads: run 2's archive counts its unchecked inherited cells; run 3's archive (adopted in place) has none,
    and counts them as end records pending instead."""
    import crossing_search_run2 as r2
    import crossing_search_run2_tests as r2t
    import crossing_search_tests as cst
    import run3_search as r3

    arrival = {lv: 100 * lv for lv in range(mcell.TARGETS_TOTAL + 1)}
    d_seed = mcell.words_digest(cst.words_for(500, 1))
    R1 = r2t.fake_run1([(0, 7, 500, 1, None), (1, 8, 640, 2, (0, d_seed)), (2, 9, 700, 3, None)], arrival)
    a = r2.ResumeArchive("arch", arrival, 800 - 24 - 1, r2.Params2())
    a.load_run1(R1, 1000 - 24 - 1, {}, reset_novelty=False)
    n2 = a.unverified_eligible()

    r3.adopt_archive(a)
    check(n2 > 0 and a.unverified_eligible() == 0 and a.end_pending() == n2 and all(a.dispatchable(c) == a.eligible(c) for c in a.cells),
          f"run 2 refuses {n2}, run 3 refuses {a.unverified_eligible()}, end records pending {a.end_pending()}")
    try:
        r3.adopt_archive(a)
        raise AssertionError("an archive was adopted twice")
    except r3.SearchError:
        pass
    return {"run2_unverified_eligible": n2, "run3_end_pending": a.end_pending()}


# -- fake game: shared setup ------------------------------------------------------------------------------------------------------------------

FLAGS = {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1", "SSB64_RL_SPATIAL": "1", "FAKEGAME_WORLD": "easy", "FAKEGAME_BOOT_S": "0.1",
         "FAKEGAME_IDLE_S": "60", "FAKEGAME_STEP_JITTER_S": "0.002"}
CHILD = ("import json, sys\nfrom pathlib import Path\nsys.path.insert(0, %r); sys.path.insert(0, %r)\nimport frs_guard as g\n"
         "g.LabGuard.install(Path(%r))\nimport run3_search_tests as T\nprint(json.dumps(T.%s(json.loads(%r)), default=str))\n")


def run_child(fn: str, lab: Path, args: Mapping[str, Any], timeout: float = 1500.0) -> Dict[str, Any]:
    code = CHILD % (str(RL), str(HERE), str(lab), fn, json.dumps(args))
    r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=timeout, cwd=str(lab))
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise AssertionError(f"{fn}: child failed: {(r.stderr or r.stdout)[-3000:]}")


def fake_setup(lab: Path) -> Dict[str, Any]:
    exe = fake_exe(lab / "fake")
    return {"exe": str(exe), "frozen": {n: mw.sha256_file(exe.parent / n) for n in mw.FROZEN_FILES},
            "exe_copy": {n: mw.sha256_file(exe.parent / n) for n in (exe.name, "BattleShip.o2r", "f3d.o2r", "gamecontrollerdb.txt")}}


def worker_spec(lab: Path, fk: Mapping[str, Any], rank: int, port_base: int, failure_dir: Path, flags: Mapping[str, str] = FLAGS) -> Dict[str, Any]:
    exe = Path(fk["exe"])
    return {"rank": rank, "root": str(lab / f"run_w{rank}"), "executable": str(exe), "flags": dict(flags), "frozen_dir": str(exe.parent),
            "frozen_sha256": dict(fk["frozen"]), "port_base": port_base, "port_size": 250,
            "timeouts": {"startup": 30.0, "ready": 30.0, "request": 15.0, "exit": 15.0}, "failure_dir": str(failure_dir)}


# -- fake game, worker level: the field-by-field table (condition 1) -------------------------------------------------------------------------


class Alter:
    """Hands out the real (fake-game) processes; at step `at` (1-based) of the next process acquired, one observation field of the reply is
    replaced before the worker sees it. Counts every step of every process."""

    def __init__(self, base: Any):
        self.base, self.plan, self.procs = base, None, []

    def acquire(self, *a: Any, **k: Any) -> Any:
        p = self.base.acquire(*a, **k)
        plan, st = self.plan, {"steps": 0, "altered": None}
        self.plan = None
        orig = p.step

        def step(b: int, x: int, y: int) -> Dict[str, Any]:
            r = orig(b, x, y)
            st["steps"] += 1
            if plan is not None and st["steps"] == plan["at"]:
                r = copy.deepcopy(r)
                was = r["observation"][plan["field"]]
                _ok, now = alter(was, plan["kind"])
                r["observation"][plan["field"]] = now
                st["altered"] = {"was": was, "now": now, "digest": mcell.record_digest(mcell.record_of(r)).hex()}
            return r

        p.step = step
        self.procs.append(st)
        return p

    def __getattr__(self, name: str) -> Any:
        return getattr(self.base, name)


def field_child(a: Mapping[str, Any]) -> Dict[str, Any]:
    import frs_guard as g

    backend = mw.make_backend(dict(a["spec"], guard=g.LabGuard.spec()))
    alt = Alter(backend)
    ctx = fw.LabJobContext(alt, None, mcell.Classifier(), 0, Path(a["spec"]["failure_dir"]), None)
    try:
        p = alt.acquire()
        reply0, _rec, _rd, _ch, rep0 = mw._tick0(p, None)
        p.close()
        pin = {"obs": list(mcell.obs_tuple(reply0["observation"])), "digest": rep0["digest"]}
        arm = {"segment_words": 40, "max_segments": 1, "window": 40}
        base = {"kind": fw.JOB_KIND, "iteration": 0, "cell": 1, "rep": (1, 0), "words": b"", "end": tuple(pin["obs"]), "end_digest": b"", "chain": b"",
                "terminal": False, "pin": pin, "archive_id": "test|run3|fields_root", "allowance": 40, **arm}
        first = fw.run_job(ctx, base)
        reach = [r for r in first["reaches"] if not r[5] and r[0] >= 10][-1]
        L, _key, obs, rd, chain, _t = reach
        cell = dict(base, cell=2, rep=(2, L), words=bytes(first["words"][:L]), end=tuple(obs), end_digest=bytes(rd), chain=bytes(chain),
                    archive_id="test|run3|fields_cell", allowance=L + 40)
        fused_job = dict(cell, end=None, end_mode=fw.FUSED_END_MODE)
        st, fu = fw.run_job(ctx, cell), fw.run_job(ctx, fused_job)
        norm = lambda rs: [(int(r[0]), list(r[1]), [v for i, v in enumerate(r[2]) if i != HOST], bytes(r[3]).hex(), bytes(r[4]).hex(), bool(r[5])) for r in rs]
        baseline = {"L": L, "stored_ok": st.get("ok"), "fused_ok": fu.get("ok"), "stored_prefix": sorted(st.get("prefix") or {}),
                    "fused_prefix": {k: v for k, v in (fu.get("prefix") or {}).items() if k != "end"},
                    "fused_end_diffs": sorted(mcell.obs_diffs(tuple(fu["prefix"]["end"]), tuple(obs))) if fu.get("ok") else None,
                    "same_burst": st.get("ok") and fu.get("ok") and bytes(st["words"]) == bytes(fu["words"]) and norm(st["reaches"]) == norm(fu["reaches"])
                    and st["final_chain"] == fu["final_chain"] and st["labels"] == fu["labels"], "burst_words": len(fu.get("words") or b"")}
        rows = []
        for i, f in enumerate(FIELDS):
            for kind in ("value", "type"):
                if not alter(obs[i], kind)[0]:
                    continue
                for mode, job in (("stored", cell), ("fused", fused_job)):
                    alt.plan = {"at": L, "field": f, "kind": kind}
                    res = fw.run_job(ctx, job)
                    s = alt.procs[-1]
                    det, pre = res.get("detail") or {}, res.get("prefix") or {}
                    rows.append({"field": f, "kind": kind, "mode": mode, "ok": bool(res.get("ok")), "result": res.get("kind"), "mismatch": res.get("mismatch"),
                                 "chain_equal": det.get("chain_equal"), "end_digest_equal": det.get("end_digest_equal"), "field_diffs": sorted(det.get("field_diffs") or {}),
                                 "steps": s["steps"], "burst_words": len(res.get("words") or b"") if res.get("ok") else 0,
                                 "was": (s["altered"] or {}).get("was"), "now": (s["altered"] or {}).get("now"),
                                 "digest_differs": (s["altered"] or {}).get("digest") != bytes(rd).hex() if s["altered"] else None,
                                 "host_frame_equal": pre.get("host_frame_equal"), "end_host": (pre.get("end") or [None] * len(FIELDS))[HOST]})
        n0 = len(alt.procs)
        refused = [fw.run_job(ctx, j).get("kind") for j in (dict(cell, end_mode=fw.FUSED_END_MODE), dict(fused_job, end_mode="lazy"),
                                                             dict(base, end=None, end_mode=fw.FUSED_END_MODE))]
        return {"baseline": baseline, "rows": rows, "refused": refused, "refused_acquired": len(alt.procs) - n0, "processes": len(alt.procs)}
    finally:
        backend.close()


def fake_field_by_field() -> Dict[str, Any]:
    """Condition 1 on the fake game: each field alone, at the end of the prefix, in both modes."""
    lab = tmpdir("run3_fields_")
    try:
        fk = fake_setup(lab)
        out = run_child("field_child", lab, {"spec": worker_spec(lab, fk, 0, 33000, lab / "failures")})
        b = out["baseline"]
        check(b["stored_ok"] and b["fused_ok"] and b["same_burst"] and b["fused_end_diffs"] == [] and "end_mode" not in b["stored_prefix"]
              and "end" not in b["stored_prefix"] and b["fused_prefix"]["end_mode"] == fw.FUSED_END_MODE, f"baseline: {b}")
        L = b["L"]
        table: Dict[str, Dict[str, str]] = {}
        for r in out["rows"]:
            t = table.setdefault(r["field"], {})
            t[f"{r['kind']}/{r['mode']}"] = ("detected: " + str(r["mismatch"])) if not r["ok"] else "not detected"
            t[f"{r['kind']}/digest"] = "changes" if r["digest_differs"] else "unchanged"
            if r["field"] != "host_frame":
                check(not r["ok"] and r["result"] == "mismatch" and r["steps"] == L and r["burst_words"] == 0 and r["digest_differs"] is True,
                      f"{r['field']} {r['kind']} {r['mode']}: {r}")
                if r["mode"] == "fused" and r["mismatch"] == "prefix_end":
                    check(r["chain_equal"] is False and r["end_digest_equal"] is False and r["field_diffs"] == [], f"fused prefix_end detail: {r}")
                if r["mode"] == "stored" and r["mismatch"] == "prefix_end":
                    check(r["field_diffs"] == [r["field"]], f"stored prefix_end names the field: {r}")
            else:
                check(r["ok"] and r["digest_differs"] is False and r["burst_words"] == 40, f"host_frame {r['kind']} {r['mode']}: {r}")
                check((r["mode"] == "stored" and r["host_frame_equal"] is False) or (r["mode"] == "fused" and r["end_host"] == r["now"] and r["host_frame_equal"] is None),
                      f"host_frame {r['kind']} {r['mode']}: {r}")
        for f in FIELDS:
            for kind in ("value", "type"):
                a_, b_ = table[f].get(f"{kind}/stored"), table[f].get(f"{kind}/fused")
                check(a_ == b_, f"{f} {kind}: stored {a_} vs fused {b_}")
        check(out["refused"] == ["error"] * 3 and out["refused_acquired"] == 0, f"refusals {out['refused']} acquired {out['refused_acquired']}")
        compared = [f for f in FIELDS if f != "host_frame"]
        det_v = sum(1 for f in compared if table[f]["value/fused"].startswith("detected"))
        det_t = [f for f in compared if "type/fused" in table[f]]
        print("\nfield | value: stored / fused / record digest | type: stored / fused / record digest")
        for f in FIELDS:
            t = table[f]
            print(f"{f} | {t['value/stored']} / {t['value/fused']} / {t['value/digest']} | "
                  + (f"{t['type/stored']} / {t['type/fused']} / {t['type/digest']}" if "type/fused" in t else "n/a (non-integral float)"))
        if os.environ.get("RUN3_TABLE_OUT"):
            Path(os.environ["RUN3_TABLE_OUT"]).write_text(json.dumps({"L": L, "table": table, "rows": out["rows"], "baseline": b}, indent=1, default=str), encoding="utf-8")
        check(det_v == 16 and all(table[f]["type/fused"].startswith("detected") for f in det_t), "16 / 16 compared fields detected")
        return {"L": L, "value_detected": f"{det_v}/16", "type_detected": f"{len(det_t)}/{len(det_t)}", "host_frame": "not detected in either mode",
                "processes": out["processes"], "kinds": sorted({r["mismatch"] for r in out["rows"] if r["mismatch"]})}
    finally:
        cleanup(lab)


# -- fake game, the engine (conditions 2 and 4) ----------------------------------------------------------------------------------------------


def engine_child(a: Mapping[str, Any]) -> Dict[str, Any]:
    import frs_guard as g
    import frs_machine as fm
    import frs_run as fr
    import frs_verify as fv
    import crossing_search as cs
    import crossing_search_run2 as r2
    import run3_search as r3

    lab, out, run1, exe = Path(a["lab"]), Path(a["out"]), Path(a["run1"]), Path(a["exe"])
    run_dir = out / "run"
    params = r2.Params2(**a["params"])
    P = r2.plan_and_write(lab, run1, out, params, stub.analyse)
    frozen = {"frozen_sha256": a["frozen"], "exe_copy_sha256": a["exe_copy"]}
    fk = {"exe": a["exe"], "frozen": a["frozen"]}

    def spec(rank: int) -> Dict[str, Any]:
        return dict(worker_spec(lab, fk, rank, int(a["port_base"]), run_dir / "failures"), guard=g.LabGuard.spec(), run3_selfcheck=True)

    env = fr.LabEnv(worker_spec=spec, replay=fv.make_real_replay(exe, lab / "run_replays", FLAGS, frozen), analyse=stub.analyse,
                    readiness=lambda: {"ok": True, "problems": []}, battleship_pids=lambda: [], snapshot=fm.tree_snapshot, import_problems=lambda: [],
                    wait_no_battleship=lambda t: [], code_manifest=fr.code_manifest, backend="real", sample_s=0.25, row_every_s=0.5,
                    caps=dict(fm.CAPS_MB, main_private=1e9))
    cfg = cs.SearchConfig(lab_root=lab, out=out, run_dir=run_dir, frontier_dir=run1, n_workers=3, max_ticks=10 ** 9, max_wall_s=900.0, expect_code=None,
                          stop_grace_s=60.0, verify_floor_s=5.0, verify_s_per_clear=2.0, write_reserve_s=2.0, progress_every_s=2.0, seed_parallel=3)
    if a.get("end_record_files"):
        P["end_record_files"] = list(a["end_record_files"])
    import run3_manifest as rm

    P["run3_code_digest"] = a["run3_code_digest"] if "run3_code_digest" in a else rm.code_digest(rm.run3_code_manifest())   # what the plan records
    cls, forced = r3.Run3Search, None
    if a.get("forced_k"):
        forced = forced_cells(P["archive"], int(a["forced_k"]))
        cls = forced_engine_class(forced)
    code = cls(cfg, env, P, params, anomaly_build={"exe": "fake", "platform": sys.platform}).run()
    return {"code": code, "violations": g.LabGuard.violations[:3], "forced": forced}


def forced_cells(archive: Any, k: int) -> List[int]:
    """Test only: the k deepest eligible cells (level desc, tick, cell id) of a freshly loaded archive."""
    return [c.cid for c in sorted((c for c in archive.cells if archive.eligible(c)), key=lambda c: (-c.level, c.tick, c.cid))][:k]


def forced_engine_class(forced: Sequence[int]) -> Any:
    """Test only: run 3's engine (D4 and anomaly keeping included) whose dispatch n draws forced[(n - 1) % k], skipping a cell that is
    no longer dispatchable (quarantined): redraws are forced, every cell is dispatched about max_dispatches / k times."""
    import det_schedule as det
    import run3_anomaly as ra
    import run3_search as r3

    cyc = list(forced)

    class ForcedCore(r3.Run3Core):
        def next_job(self, w: int) -> Optional[Dict[str, Any]]:
            n = self.c["dispatches"] + 1
            for j in range(len(cyc)):
                slot = (n - 1 + j) % len(cyc)
                c = self.archive.cells[cyc[slot]]
                if self.archive.dispatchable(c):
                    return self.build_job(w, c, {"forced": True, "slot": slot})
            self.mark("ARCHIVE_EMPTY", "no forced cell is dispatchable")
            return None

    class ForcedRun3(det.DeterministicSchedule, ra.AnomalyIngest, ForcedCore):
        pass

    return ForcedRun3


def read_jsonl(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.is_file() else []


class Bench:
    def __init__(self) -> None:
        import crossing_search_run2_tests as r2t

        # run 1's engine (no D4) makes the fixture: its outcome varies; run 2's helper needs a verified clear, so up to 3 fresh attempts
        self.fixture_attempts = []
        for _attempt in range(3):
            self.lab = tmpdir("run3_search_lab_")
            try:
                self.run1 = r2t.synthetic_run1(self.lab, max_dispatches=110)["out"]
                self.fixture_attempts.append("ok")
                break
            except AssertionError as exc:
                self.fixture_attempts.append(str(exc)[:120])
                cleanup(self.lab)
        else:
            raise AssertionError(f"no usable synthetic run 1 in 3 attempts: {self.fixture_attempts}")
        self.fk = fake_setup(self.lab)
        self.port = 34000
        self.runs: Dict[str, Dict[str, Any]] = {}

    def run(self, name: str, run1: Path, params: Mapping[str, Any] = RUN3_PARAMS, **extra: Any) -> Dict[str, Any]:
        if name in self.runs:
            return self.runs[name]
        out = self.lab / f"run3_{name}"
        self.port += 1000
        res = run_child("engine_child", self.lab, dict({"lab": str(self.lab), "out": str(out), "run1": str(run1), "exe": self.fk["exe"], "frozen": self.fk["frozen"],
                                                        "exe_copy": self.fk["exe_copy"], "params": dict(params), "port_base": self.port}, **extra))
        d = out / "run"
        res.update({"dir": d, "summary": json.loads((d / "summary.json").read_text(encoding="utf-8")), "config": json.loads((d / "config.json").read_text(encoding="utf-8")),
                    "dispatches": read_jsonl(d / "dispatches.jsonl"), "cells": read_jsonl(d / "cells.jsonl"), "log": read_jsonl(d / "run_log.jsonl"),
                    "bursts": read_jsonl(d / "anomaly_bursts.jsonl")})
        self.runs[name] = res
        return res

    def final1(self, run1: Optional[Path] = None) -> Dict[int, Dict[str, Any]]:
        last: Dict[int, Dict[str, Any]] = {}
        for r in read_jsonl((run1 or self.run1) / "run" / "cells.jsonl"):
            last[int(r["cid"])] = r
        return last

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


def _rep(row: Mapping[str, Any]) -> Tuple[int, str]:
    return int(row["cid"]), str(row["draw_id"]).split("|")[2]


def _clean(r: Mapping[str, Any], dispatches: int) -> None:
    import run3_search as r3

    s = r["summary"]
    check(r["code"] == 0 and not r["violations"] and s["status"] == "DISPATCH_CAP" and s["work"]["dispatches"] == dispatches and s["contract"] == r3.RUN3_CORE_CONTRACT,
          f"a clean stop at the dispatch cap: {r['code']} {r['violations']} {s['status']} {s['stop']} {s['work']['dispatches']} (folder {r['dir']})")
    code = r["config"]["run3"]["code"]
    check(code["digest"] == code["expected"] == s["integrity"]["run3_code_digest_end"] and not s["integrity"]["run3_code_changed_during_run"]
          and "tools/glitch/detect.py" in code["files"] and "tools/frs/run3_worker.py" in code["files"], "the run 3 code digest recorded and unchanged at the close")


def e2e_fused_runs() -> Dict[str, Any]:
    """Condition 4: fused first dispatches, end records stored and used by every later dispatch (full comparison), D4 accepted, two
    same-seed runs identical; every stored end record equals an independent fresh replay of the cell's words."""
    import det_schedule as det
    import run3_anomaly_tests as rat
    import run3_search as r3

    b = bench()
    A, B = b.run("a", b.run1), b.run("b", b.run1)
    for r in (A, B):
        _clean(r, RUN3_PARAMS["max_dispatches"])
        check((r["dir"] / "schedule.json").is_file() and r["config"]["scheduler"]["contract"] == det.SCHEDULE_CONTRACT
              and not [x for x in r["log"] if "deterministic scheduling refused" in x["msg"]], "D4 accepted the archive (schedule.json, no refusal)")
        check(r["summary"]["integrity"]["prefix_mismatches"] == 0 and all(d["outcome"] not in ("mismatch", "lifecycle", "aborted") and d["tick0_equal"] is True
                                                                           and d["prefix_level_ok"] for d in r["dispatches"]), "every prefix reproduced")
        check(all(d["draw_id"].split("|")[1] == r3.KEY_FAMILY for d in r["dispatches"]), "run 3's key family")
    check(det.dispatch_signature(A["dispatches"]) == det.dispatch_signature(B["dispatches"]), "the same dispatches in both runs")
    check(det.cells_signature(A["cells"]) == det.cells_signature(B["cells"]), "the same cell events (end_record rows included) in both runs")
    ends = lambda r: [(x["cid"], x["digest"], x["n"], [v for i, v in enumerate(x["end"]) if i != HOST]) for x in r["cells"] if x["ev"] == r3.END_RECORD_EV]
    check(ends(A) == ends(B), "the same end records (16 compared fields) in both runs")
    sig = lambda r: sorted((x["n"], x["words_digest"], tuple(x["kinds"])) for x in r["bursts"])
    check(sig(A) == sig(B), "the same anomaly bursts in both runs")
    final1 = b.final1()
    inherited = {(cid, r["digest"]) for cid, r in final1.items()}
    found = {(int(x["cid"]), x["digest"]) for x in A["cells"] if x["ev"] in ("new", "replaced")}
    end_at = {(int(x["cid"]), x["digest"]): int(x["n"]) for x in A["cells"] if x["ev"] == r3.END_RECORD_EV}
    check(len(end_at) == len([x for x in A["cells"] if x["ev"] == r3.END_RECORD_EV]), "at most one end record per representative")
    by_rep: Dict[Tuple[int, str], List[Dict[str, Any]]] = {}
    for d in sorted(A["dispatches"], key=lambda d: int(d["n"])):
        by_rep.setdefault(_rep(d), []).append(d)
    replaced_cids = {int(x["cid"]) for x in A["cells"] if x["ev"] == "replaced"}
    later_stored = repeats = stale = 0
    for rep, rows in by_rep.items():
        if rep in found:
            check(all(d["end_mode"] is None for d in rows), f"a cell found by run 3 is never fused: {rep}")
            continue
        check(rep in inherited and rows[0]["end_mode"] == fw.FUSED_END_MODE, f"an inherited representative's first dispatch is fused: {rep}")
        if rep not in end_at:
            # the only path that stores nothing: the cell was replaced (a faster arrival, ingested first) before this dispatch was ingested
            check(rep[0] in replaced_cids and all(d["end_mode"] == fw.FUSED_END_MODE for d in rows),
                  f"an inherited representative without an end record was replaced in the run: {rep} {[(d['n'], d['end_mode']) for d in rows]}")
            stale += len(rows)
            continue
        check(end_at[rep] == rows[0]["n"], f"its end record was stored by its first dispatch: {rep} {end_at[rep]} {[(d['n'], d['end_mode']) for d in rows]}")
        for d in rows[1:]:
            if d["end_mode"] is None:
                check(int(d["n"]) > end_at[rep], f"a stored-end dispatch after the end record: {rep} {d['n']} {end_at[rep]}")
                later_stored += 1
            else:
                repeats += 1
    current = {cid: r["digest"] for cid, r in final1.items()}
    for x in A["cells"]:
        if x["ev"] in ("new", "replaced"):
            current[int(x["cid"])] = x["digest"]
    still_inherited = {cid for (cid, dg) in end_at if current.get(cid) == dg}          # an inherited representative run 3 did not replace
    e3 = A["summary"]["run3"]["end_records"]
    check(e3["end_records"] == len(end_at) and e3["fused"] == sum(1 for d in A["dispatches"] if d["end_mode"])
          and e3["fused_repeat"] + e3["fused_stale"] == repeats + stale and e3["fused_stale"] >= stale and e3["fused_mismatch"] == 0 and e3["inherited_with_end_record"] == len(still_inherited),
          f"the end-record counts: {e3} (repeats {repeats}, stale {stale}, stored {len(end_at)}, still inherited {len(still_inherited)})")
    check(later_stored >= 1, "O10 exercised: at least one later dispatch of an inherited representative used its stored end record")
    check(all(x.get("end") is not None and len(x["end"]) == len(FIELDS) for x in A["cells"] if x["ev"] in ("new", "replaced")), "every NEW / REPLACED row carries its end record")
    cells, rep = ar.merged_cells([b.run1 / "run" / "cells.jsonl", A["dir"] / "cells.jsonl"])
    ar.require_consistent(rep)
    check(rep["with_end_record"] == len({c for c, _d in found} | still_inherited) and rep["end_record_rows"] == len(end_at)
          and all(cells[cid]["end"] is not None for cid in still_inherited), f"the merge reads them back: {rep}")
    replayed = []
    for (cid, dg), n in sorted(end_at.items(), key=lambda kv: kv[1])[:4]:
        words = bytes.fromhex(final1[cid]["words_hex"])
        replies = rat._replay_fake(FLAGS, words)
        row = next(x for x in A["cells"] if x["ev"] == r3.END_RECORD_EV and int(x["cid"]) == cid)
        diffs = mcell.obs_diffs(mcell.obs_tuple(replies[len(words) - 1]["observation"]), tuple(row["end"]))
        check(not diffs, f"cell {cid}: the stored end record differs from a fresh replay: {diffs}")
        replayed.append([cid, len(words)])
    return {"dispatches": len(A["dispatches"]), "fused": e3["fused"], "end_records": e3["end_records"], "fused_repeat": repeats, "fused_stale": stale,
            "later_stored_end": later_stored,
            "eligible_without_end_record": e3["eligible_without_end_record"], "inherited": e3["inherited"], "replayed": replayed,
            "verified": A["summary"]["clears"]["verified"], "det": A["summary"].get("schedule") or None}


def tamper(src: Path, dst: Path, fields: Mapping[int, str]) -> None:
    """A copy of a run 1 folder whose FINAL row of each given cell carries a wrong digest in the given field (chain or end_digest)."""
    shutil.copytree(src, dst)
    p = dst / "run" / "cells.jsonl"
    rows = read_jsonl(p)
    last = {int(r["cid"]): i for i, r in enumerate(rows)}
    for cid, f in fields.items():
        rows[last[cid]][f] = "00" * 32
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, separators=(",", ":")) + "\n")


def e2e_fused_mismatch() -> Dict[str, Any]:
    """Condition 2: two inherited cells whose stored chain / record digest is wrong. Their (fused) first dispatch ends as a prefix
    mismatch before any burst word, the fake game stepped exactly L times, the cell is quarantined and never dispatched again, no end
    record is written, the dispatch row, event and log are run 2's, the run goes on to its cap."""
    import run3_search as r3

    b = bench()
    A = b.run("a", b.run1)
    first = []
    for d in sorted(A["dispatches"], key=lambda d: int(d["n"])):
        if d["end_mode"] == fw.FUSED_END_MODE and d["cid"] not in first:
            first.append(int(d["cid"]))
        if len(first) == 2:
            break
    c1, c2 = first
    bad = b.lab / "crossing_syn_tampered"
    tamper(b.run1, bad, {c1: "chain", c2: "end_digest"})
    C = b.run("c", bad)
    _clean(C, RUN3_PARAMS["max_dispatches"])
    final1 = b.final1()
    s, e3 = C["summary"], C["summary"]["run3"]["end_records"]
    replaced_later = []
    for cid, field in ((c1, "chain_equal"), (c2, "end_digest_equal")):
        bad_rep = (cid, final1[cid]["digest"])
        rows = [d for d in C["dispatches"] if _rep(d) == bad_rep]
        check(len(rows) == 1, f"cell {cid}: the tampered representative dispatched once, then never again: {[(d['n'], d['outcome']) for d in rows]}")
        d = rows[0]
        det_ = json.loads(d["detail"])
        check(d["outcome"] == "mismatch" and d["mismatch"] == "prefix_end" and d["end_mode"] == fw.FUSED_END_MODE and d["words_played"] == 0 and d["ticks"] == 0
              and det_[field] is False and det_["end_mode"] == fw.FUSED_END_MODE, f"cell {cid}: the dispatch row {d}")
        check(not [x for x in C["cells"] if int(x["cid"]) == cid and (x["ev"] == r3.END_RECORD_EV or x["digest"] == bad_rep[1])],
              f"cell {cid}: no end record and no row for the tampered representative")
        # crossing_search's rule (unchanged): the quarantine is the representative's; a faster arrival at the key later is a new representative
        for x in [x for x in C["cells"] if int(x["cid"]) == cid]:
            check(x["ev"] == "replaced" and x["n"] > d["n"] and x["origin"]["kind"] == "burst" and (x.get("previous") or {}).get("quarantined")
                  and x["end"] is not None, f"cell {cid}: a later row is a run 3 replacement of the quarantined representative: {x}")
            replaced_later.append([cid, x["n"], x["tick"], final1[cid]["tick"]])
        check(any(f"cell {cid} (level" in x["msg"] and "quarantined: its prefix did not reproduce (prefix_end)" in x["msg"] for x in C["log"]), f"cell {cid}: the event in run_log.jsonl")
    check(s["archive"]["quarantined"] == 2 and s["work"]["mismatches"] == 2 and e3["fused_mismatch"] == 2, f"two quarantines: {s['archive']} {s['work']['mismatches']} {e3}")
    pres = sorted((C["dir"] / "failures").glob("*.json.gz"))
    check(pres, "the failed prefixes were preserved")
    for p in pres:
        rec = json.load(gzip.open(p, "rt", encoding="utf-8"))
        cid = int(rec["job"]["cell"])
        check(rec["kind"] == "prefix_end" and cid in (c1, c2) and len(rec["replies"]) == int(final1[cid]["tick"]) and rec["job"].get("end") is None,
              f"{p.name}: the fake game stepped exactly L times ({len(rec['replies'])} vs {final1[cid]['tick']})")
    n_bad = min(int(d["n"]) for d in C["dispatches"] if d["outcome"] == "mismatch")
    pre = lambda r: [(d["n"], d["cid"], d["draw_id"], d["words_hex"]) for d in sorted(r["dispatches"], key=lambda d: int(d["n"])) if int(d["n"]) < n_bad]
    check(pre(A) == pre(C), "up to the first mismatch the tampered run draws what the clean run drew")
    return {"cells": [c1, c2], "first_mismatch_n": n_bad, "preserved": len(pres), "quarantined": s["archive"]["quarantined"], "status": s["status"],
            "replaced_later": replaced_later}


def unit_end_record_import() -> Dict[str, Any]:
    """end_records reads every stored record by (cell id, words digest); the archive attaches only those of its own representatives."""
    import crossing_search_run2 as r2
    import crossing_search_run2_tests as r2t
    import crossing_search_tests as cst
    import run3_search as r3

    arrival = {lv: 100 * lv for lv in range(mcell.TARGETS_TOTAL + 1)}
    R1 = r2t.fake_run1([(0, 7, 500, 1, None), (1, 8, 640, 2, None), (2, 9, 700, 3, None)], arrival)
    a = r2.ResumeArchive("arch", arrival, 800 - 24 - 1, r2.Params2())
    a.load_run1(R1, 1000 - 24 - 1, {}, reset_novelty=False)
    r3.adopt_archive(a)
    c0, c1, c2 = a.cells
    e = [1, 500, 500, 499, 1, 1, 3, 1, 10.0, 20.0, 0.0, 0.0, 0.0, 1, 0, 10, 0]
    d = tmpdir("run3_import_")
    try:
        f = d / "cells.jsonl"
        rows = [{"ev": ar.END_RECORD_EV, "cid": 0, "digest": c0.digest, "end": e, "n": 3},
                {"ev": ar.END_RECORD_EV, "cid": 1, "digest": "f" * 64, "end": e, "n": 4},            # a representative replaced since
                {"ev": "new", "cid": 9, "digest": "a" * 64, "end": e, "n": 5, "key": [0, 0, "G", 1, 1], "level": 9, "tick": 900},
                {"ev": "replaced", "cid": 2, "digest": c2.digest, "end": e, "n": 6, "key": list(c2.key), "level": 9, "tick": 700}]
        f.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        ends, rep = ar.end_records([f])
        check(rep["records"] == 4 and rep["end_record_rows"] == 2 and not rep["end_conflicts"] and len(rep["files"][0]["sha256"]) == 64, f"report {rep}")
        before = a.end_pending()
        n = a.import_end_records(ends)
        check(n == 2 and c0.verified and tuple(c0.end) == tuple(e) and not c1.verified and c2.verified and a.end_pending() == before - 2
              and a.counts["end_records_imported"] == 2 and a.counts["end_records"] == 0, f"attached {n}; pending {before} -> {a.end_pending()}")
        g2 = d / "bad.jsonl"
        e2 = list(e)
        e2[mcell.OBS_INDEX["jumps_used"]] = 1
        g2.write_text(json.dumps(dict(rows[0], end=e2)) + "\n", encoding="utf-8")
        check(ar.end_records([f, g2])[1]["end_conflicts"] == [0], "two records of one representative that differ are reported")
        return {"records": rep["records"], "attached": n}
    finally:
        cleanup(d)


def e2e_stored_records() -> Dict[str, Any]:
    """Forced redraws (8 cells in a fixed cycle, 48 dispatches). Run x: each cell's first dispatch is fused and stores its record; every
    later dispatch compares against it. Run y imports x's records from a copy of x's cells.jsonl in which ONE compared field of ONE record
    was changed: every dispatch compares against a record read from disk; the corrupted one is a prefix_end mismatch naming that field,
    with 0 burst words, the fake game stepped exactly L times, and the cell is quarantined."""
    import run3_search as r3

    b = bench()
    params = dict(RUN3_PARAMS, max_dispatches=48)
    X = b.run("x", b.run1, params, forced_k=8)
    _clean(X, 48)
    forced = X["forced"]
    final1 = b.final1()
    check(len(forced) == 8 and len({_rep(d) for d in X["dispatches"]}) >= 8, f"8 forced cells: {forced}")
    end_at = {(int(x["cid"]), x["digest"]): int(x["n"]) for x in X["cells"] if x["ev"] == r3.END_RECORD_EV}
    rows = sorted(X["dispatches"], key=lambda d: int(d["n"]))
    check(all(d["outcome"] not in ("mismatch", "lifecycle", "aborted") for d in rows), "every prefix of run x reproduced")
    for cid in forced:
        first = next(d for d in rows if int(d["cid"]) == cid)
        check(first["end_mode"] == fw.FUSED_END_MODE and end_at.get(_rep(first)) == int(first["n"]), f"cell {cid}: its first dispatch is fused and stores the record")
    in_run = [d for d in rows if d["end_mode"] is None and _rep(d) in end_at and int(d["n"]) > end_at[_rep(d)]]
    check(len(in_run) >= 30, f"later dispatches compared against a record stored in the run: {len(in_run)}")
    # one compared field of one stored record changed in a copy of x's cells.jsonl
    victim = forced[2]
    vrep = (victim, final1[victim]["digest"])
    field = "position_x"
    xi = mcell.OBS_INDEX[field]
    cells_x = read_jsonl(X["dir"] / "cells.jsonl")
    hit = [i for i, x in enumerate(cells_x) if x["ev"] == r3.END_RECORD_EV and (int(x["cid"]), x["digest"]) == vrep]
    check(len(hit) == 1, f"the victim's end_record row: {hit}")
    true_v = cells_x[hit[0]]["end"][xi]
    cells_x[hit[0]]["end"][xi] = math.nextafter(true_v, math.inf)
    cdir = b.lab / "x_corrupted" / "run"            # beside a copy of x's summary.json: end records come only from a run that stopped cleanly
    cdir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(X["dir"] / "summary.json", cdir / "summary.json")
    corrupted = cdir / "cells.jsonl"
    with open(corrupted, "w", encoding="utf-8", newline="\n") as fh:
        for x in cells_x:
            fh.write(json.dumps(x, separators=(",", ":")) + "\n")
    Y = b.run("y", b.run1, params, forced_k=8, end_record_files=[str(corrupted)])
    _clean(Y, 48)
    check(Y["forced"] == forced, "the same forced cells")
    e3 = Y["summary"]["run3"]["end_records"]
    imp = Y["config"]["run3"]["end_import"]
    check(e3["imported"] == 8 and e3["fused"] == 0 and imp["files"][0]["sha256"] == mw.sha256_file(corrupted), f"8 records imported, nothing fused: {e3} {imp}")
    vrows = [d for d in Y["dispatches"] if _rep(d) == vrep]
    check(len(vrows) == 1, f"the corrupted cell dispatched once, then never again: {[(d['n'], d['outcome']) for d in vrows]}")
    d = vrows[0]
    det_ = json.loads(d["detail"])
    check(d["outcome"] == "mismatch" and d["mismatch"] == "prefix_end" and d["end_mode"] is None and d["words_played"] == 0 and d["ticks"] == 0
          and list(det_["field_diffs"]) == [field] and det_["chain_equal"] is True and det_["end_digest_equal"] is True
          and det_["field_diffs"][field] == [true_v, math.nextafter(true_v, math.inf)], f"the corrupted record is detected: {d}")
    check(Y["summary"]["archive"]["quarantined"] == 1 and Y["summary"]["work"]["mismatches"] == 1
          and any(f"cell {victim} (level" in x["msg"] and "quarantined: its prefix did not reproduce (prefix_end)" in x["msg"] for x in Y["log"]),
          "quarantined, counted and logged as run 2 does")
    pres = [json.load(gzip.open(p, "rt", encoding="utf-8")) for p in sorted((Y["dir"] / "failures").glob("*.json.gz"))]
    check(len(pres) == 1 and int(pres[0]["job"]["cell"]) == victim and len(pres[0]["replies"]) == int(final1[victim]["tick"]),
          f"the fake game stepped exactly L = {final1[victim]['tick']} times: {[len(p['replies']) for p in pres]}")
    imported = {(cid, final1[cid]["digest"]) for cid in forced}
    from_disk = [x for x in Y["dispatches"] if x["end_mode"] is None and _rep(x) in imported and _rep(x) != vrep]
    check(len(from_disk) >= 30 and all(x["outcome"] not in ("mismatch", "lifecycle", "aborted") for x in from_disk),
          f"dispatches compared against a record read from disk: {len(from_disk)}")
    return {"fixture_attempts": len(b.fixture_attempts), "forced": forced, "x_fused": X["summary"]["run3"]["end_records"]["fused"], "x_later_stored": len(in_run), "y_imported": e3["imported"],
            "y_from_disk": len(from_disk), "victim": [victim, field, int(final1[victim]["tick"])], "y_mismatch_n": d["n"]}


def unit_run3_manifest() -> Dict[str, Any]:
    """The run 3 code manifest: deterministic; every run 3 file outside rl/ (tools/frs, tools/glitch) and the rl/ files run 3 imports, each
    of those in the lab manifest too; on a copied tree, a one-line edit to tools/glitch/detect.py changes the digest and only that file."""
    import frs_run as fr
    import run3_manifest as rm

    m1, m2 = rm.run3_code_manifest(), rm.run3_code_manifest()
    check(m1 == m2, "deterministic")
    must = {f"tools/frs/{n}.py" for n in ("run3_search", "run3_worker", "run3_anomaly", "run3_archive", "run3_manifest", "det_schedule", "crossing_search",
                                         "crossing_search_run2")} | {f"tools/glitch/{n}.py" for n in ("detect", "analysis", "geometry", "vpk0")} \
        | {"rl/frs_worker.py", "rl/m8_rd_cells.py", "rl/m8_rd_worker.py", "rl/battleship_process.py", "rl/port_lease.py", "rl/battleship_client.py",
           "rl/m7_standby.py", "rl/m7f_trace.py", "rl/m7q_status_table.py", "rl/m7f_targets.py", "rl/m7g_spatial.py"}
    check(must <= set(m1), f"missing: {sorted(must - set(m1))}")
    check(not [k for k in m1 if "test" in Path(k).name or k.startswith("runs/")], f"no test or evidence file: {[k for k in m1 if 'test' in k]}")
    stems = {Path(k).stem for k in m1}
    open_lazy = {n: w for n, w in rm.lazy_imports(m1).items() if n not in stems and n not in rm.LAZY_EXCLUDED}
    check(not open_lazy, f"a function-level import of a repository module is neither in the manifest nor excluded: {open_lazy}")
    check(tuple(fr.CODE_MODULES) == rm.LAB_RUNTIME_MODULES, "the lab runner's module list is run 3's too")
    lab = fr.code_manifest()
    not_in_run3 = sorted(set(lab) - set(m1))
    check(not_in_run3 == ["rl/frs_tests.py"] and all(m1[k] == lab[k] for k in set(lab) & set(m1)),
          f"every lab-manifest file but the lab's own tests is in run 3's, with the same hash: {not_in_run3}")
    d = tmpdir("run3_manifest_")
    try:
        for sub in ("rl", "tools/frs", "tools/glitch"):
            (d / sub).mkdir(parents=True)
            for f in (REPO / sub).glob("*.py"):
                shutil.copy2(f, d / sub / f.name)
        c1 = rm.run3_code_manifest(d)
        check(c1 == m1, "the copied tree gives the same manifest")
        p = d / "tools" / "glitch" / "detect.py"
        p.write_bytes(p.read_bytes() + b"\n# probe\n")
        c2 = rm.run3_code_manifest(d)
        check(rm.code_digest(c2) != rm.code_digest(c1) and [k for k in c1 if c1[k] != c2.get(k)] == ["tools/glitch/detect.py"]
              and rm.changed_files(c1, d) == ["tools/glitch/detect.py"], "an edit to the live scanner changes the digest, and only that file")
    finally:
        cleanup(d)
    return {"files": len(m1), "digest": rm.code_digest(m1)[:16], "outside_rl": len([k for k in m1 if not k.startswith("rl/")]),
            "rl_not_in_lab_manifest": sorted(set(m1) - set(lab)), "lazy_excluded": sorted(rm.LAZY_EXCLUDED)}


def e2e_code_digest_refusal() -> Dict[str, Any]:
    """A recorded run 3 code digest that is not the tree's: refused at the open, nothing launched, no run folder."""
    b = bench()
    out = b.lab / "run3_refused"
    res = run_child("engine_child", b.lab, {"lab": str(b.lab), "out": str(out), "run1": str(b.run1), "exe": b.fk["exe"], "frozen": b.fk["frozen"],
                                            "exe_copy": b.fk["exe_copy"], "params": dict(RUN3_PARAMS), "port_base": 39000, "run3_code_digest": "0" * 64})
    refused = sorted(out.glob("refused_*.json"))
    check(res["code"] == 2 and refused and not (out / "run").exists(), f"refused before the open: {res} {refused}")
    why = json.loads(refused[0].read_text(encoding="utf-8"))["reason"]
    check("run 3 code digest" in why, f"the reason names the run 3 code digest: {why}")
    return {"code": res["code"], "reason": why[:120]}


UNIT = {"unit_digest_covers_compared_fields": unit_digest_covers_compared_fields, "unit_worker_refusals": unit_worker_refusals,
        "unit_stub_fused_equals_stored": unit_stub_fused_equals_stored, "unit_run2_path_equals_pre_change": unit_run2_path_equals_pre_change,
        "unit_merge_end_records": unit_merge_end_records, "unit_d4_reads_no_lazy_check": unit_d4_reads_no_lazy_check,
        "unit_end_record_import": unit_end_record_import, "unit_run3_manifest": unit_run3_manifest}
FAKE = {"fake_field_by_field": fake_field_by_field}
E2E = {"e2e_code_digest_refusal": e2e_code_digest_refusal, "e2e_fused_runs": e2e_fused_runs, "e2e_fused_mismatch": e2e_fused_mismatch,
       "e2e_stored_records": e2e_stored_records}

if __name__ == "__main__":
    args = sys.argv[1:]
    groups = {"unit": UNIT, "fake": FAKE, "e2e": E2E}
    tests = dict(groups[args[0]]) if args[:1] and args[0] in groups else dict(UNIT, **FAKE, **E2E)
    rest = [x for x in args if x not in groups]
    try:
        code = run_suite("run3 search tests", tests, rest)
    finally:
        if _BENCH is not None:
            _BENCH.close()
    sys.exit(code)
