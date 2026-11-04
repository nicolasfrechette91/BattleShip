#!/usr/bin/env python3
"""INFRA_2026-11-04 fix 3: deterministic scheduling (tools/frs/det_schedule.py; REVIEW_2026-11-03.md D4).

Zero native ticks. The end-to-end tests run the REAL crossing-search engine (tools/frs/crossing_search.py) in a guarded child
process, with three workers whose game processes are rl/m8_rd_fakegame.py behind the real launcher. Every burst, seed check,
reference replay and verification goes through a launched fake process. The fake adds wall-clock noise to every step
(FAKEGAME_STEP_JITTER_S), so jobs finish in a different order from run to run.

    python -B tools/frs/det_schedule_tests.py              all tests (about 2 to 4 minutes)
    python -B tools/frs/det_schedule_tests.py unit         the fast unit tests only
    python -B tools/frs/det_schedule_tests.py e2e          the end-to-end runs only

`same_seed_same_dispatches` is the requirement: two runs with the same seed produce the same dispatch sequence, the same
cell events and the same verified clears. `plain_engine_for_reference` runs the unmodified engine twice on the same inputs and
REPORTS whether its dispatch sequences diverged. It is not a pass condition (an unlucky schedule can coincide by chance), but
it shows what the fix removes.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
RL = REPO / "rl"
sys.path.insert(0, str(RL))
sys.path.insert(0, str(HERE))

import crossing_search as cs  # noqa: E402
import det_schedule as det  # noqa: E402
import m8_rd_worker as mw  # noqa: E402
import m8_rd_stub as stub  # noqa: E402
from infra_testlib import check, cleanup, fake_exe, run_suite, tmpdir  # noqa: E402

PARAMS = {"seeds": 12, "seed_order": "level", "level_decay": 0.5, "novelty_exp": 1.0, "seen_exp": 1.0, "bonus_exp": 1.0, "pace_exp": 0.5,
          "max_segments": 3, "retire_after": 0, "max_cells": 100000, "max_dispatches": 90, "rng_seed": 7}

RUN_CHILD = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, {rl!r}); sys.path.insert(0, {here!r})
import frs_guard as g
lab = Path({lab!r})
g.LabGuard.install(lab)
import frs_machine as fm, frs_run as fr, frs_verify as fv, m8_rd_stub as stub, crossing_search as cs, det_schedule as det
out = Path({out!r}); run_dir = out / {run_name!r}; frontier = Path({frontier!r}); exe = Path({exe!r})
params = cs.Params(**{params!r})
P = cs.plan_and_write(lab, frontier, out, params, stub.analyse)
flags = {flags!r}
frozen = {{"frozen_sha256": {frozen!r}, "exe_copy_sha256": {exe_copy!r}}}
spec = lambda rank: {{"rank": rank, "root": str(lab / ({run_name!r} + "_w%d" % rank)), "executable": str(exe), "flags": dict(flags),
                     "frozen_dir": str(exe.parent), "frozen_sha256": {frozen!r}, "port_base": 30000, "port_size": 250,
                     "timeouts": {{"startup": 30.0, "ready": 30.0, "request": 15.0, "exit": 15.0}}, "failure_dir": str(run_dir / "failures"),
                     "guard": g.LabGuard.spec()}}
env = fr.LabEnv(worker_spec=spec, replay=fv.make_real_replay(exe, lab / ({run_name!r} + "_replays"), flags, frozen), analyse=stub.analyse,
                readiness=lambda: {{"ok": True, "problems": []}}, battleship_pids=lambda: [], snapshot=fm.tree_snapshot, import_problems=lambda: [],
                wait_no_battleship=lambda t: [], code_manifest=fr.code_manifest, backend="real", sample_s=0.25, row_every_s=0.5,
                caps=dict(fm.CAPS_MB, main_private=1e9))
cfg = cs.SearchConfig(lab_root=lab, out=out, run_dir=run_dir, frontier_dir=frontier, n_workers=3, max_ticks=10 ** 9, max_wall_s=600.0,
                      expect_code=None, stop_grace_s=60.0, verify_floor_s=5.0, verify_s_per_clear=2.0, write_reserve_s=2.0, progress_every_s=2.0,
                      seed_parallel=3)
engine = det.DetSearch if {deterministic!r} else cs.Search
code = engine(cfg, env, P, params).run()
print(json.dumps({{"code": code, "violations": g.LabGuard.violations[:3]}}))
'''


def read_jsonl(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.is_file() else []


class Bench:
    """One synthetic frontier (the frontier engine on the stub world) and one fake executable, shared by every run."""

    def __init__(self) -> None:
        import crossing_search_tests as cst

        self.lab = tmpdir("det_sched_lab_")
        syn = cst.synthetic_frontier(self.lab)
        self.frontier = syn["out"]
        self.exe = fake_exe(self.lab / "fake")
        self.frozen = {n: mw.sha256_file(self.exe.parent / n) for n in mw.FROZEN_FILES}
        self.exe_copy = {n: mw.sha256_file(self.exe.parent / n) for n in (self.exe.name, "BattleShip.o2r", "f3d.o2r", "gamecontrollerdb.txt")}
        self.flags = {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1", "SSB64_RL_SPATIAL": "1", "FAKEGAME_WORLD": "easy",
                      "FAKEGAME_BOOT_S": "0.1", "FAKEGAME_IDLE_S": "60", "FAKEGAME_STEP_JITTER_S": "0.002"}

    def run(self, name: str, *, deterministic: bool, seed: int) -> Dict[str, Any]:
        out = self.lab / f"out_{name}"
        params = dict(PARAMS, rng_seed=seed)
        code = RUN_CHILD.format(rl=str(RL), here=str(HERE), lab=str(self.lab), out=str(out), run_name="run", frontier=str(self.frontier), exe=str(self.exe),
                                params=params, flags=self.flags, frozen=self.frozen, exe_copy=self.exe_copy, deterministic=deterministic)
        # cwd = the lab root: on POSIX shutil.rmtree removes by dir_fd, and the lab guard resolves those bare names against the
        # working directory (a POSIX-only false positive of rl/frs_guard.py, noted in INFRA_2026-11-04.md)
        r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=1200, cwd=str(self.lab))
        try:
            res = json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            raise AssertionError(f"{name}: child failed: {(r.stderr or r.stdout)[-2500:]}")
        run_dir = out / "run"
        res.update({"dir": run_dir, "summary": json.loads((run_dir / "summary.json").read_text(encoding="utf-8")),
                    "dispatches": read_jsonl(run_dir / "dispatches.jsonl"), "cells": read_jsonl(run_dir / "cells.jsonl"),
                    "verifications": read_jsonl(run_dir / "verifications.jsonl"),
                    "config": json.loads((run_dir / "config.json").read_text(encoding="utf-8")) if (run_dir / "config.json").is_file() else {}})
        return res

    def close(self) -> None:
        if os.environ.get("DET_KEEP") == "1":
            print(f"kept: {self.lab}")
            return
        cleanup(self.lab)


_BENCH: Optional[Bench] = None


def bench() -> Bench:
    global _BENCH
    if _BENCH is None:
        _BENCH = Bench()
    return _BENCH


def verified_set(res: Dict[str, Any]) -> List[Any]:
    return sorted((v.get("n"), v.get("verdict"), v.get("completion_input_tick")) for v in res["verifications"])


def completion_orders_differ(res: Dict[str, Any]) -> bool:
    """True when at least two jobs finished out of dispatch order: the rows are written in completion order for the plain
    engine, and in dispatch order for the deterministic one, so this reads how the run actually scheduled."""
    ns = [int(r["n"]) for r in res["dispatches"] if r.get("kind", "burst") == "burst"]
    return ns != sorted(ns)


# -- unit tests (no process) ---------------------------------------------------------------------------------------------------------------


def unit_keyed_random() -> Dict[str, Any]:
    a, b = det.KeyedRandom(7, "arch"), det.KeyedRandom(7, "arch")
    a.begin(12)
    xs = [a.random() for _ in range(4)]
    b.begin(11)
    b.random()
    b.begin(12)
    ys = [b.random() for _ in range(4)]
    check(xs == ys, "the draws of dispatch 12 do not depend on anything drawn before")
    check(len(set(xs)) == 4 and all(0.0 <= x < 1.0 for x in xs), "distinct uniforms in [0, 1)")
    c = det.KeyedRandom(8, "arch")
    c.begin(12)
    check(c.random() != xs[0], "another seed draws differently")
    try:
        a.choice([1, 2])
        raise AssertionError("an undeclared generator method was allowed")
    except AttributeError:
        pass
    return {"draw0": xs[0]}


def unit_asof_index() -> Dict[str, Any]:
    ix = det.AsOfIndex()
    k1, k2 = (1, 2, "G", 1023, 3), (0, 0, "A2", 1022, -1)
    ix.record(k1, 0, 500, new=True)
    ix.record(k2, 4, 300, new=True)
    ix.record(k1, 9, 450, new=False)                               # a faster arrival replaced the representative at dispatch 9
    check(ix.tick_asof(k1, 0) == 500 and ix.tick_asof(k1, 8) == 500 and ix.tick_asof(k1, 9) == 450, "a key's tick as of each moment")
    check(ix.tick_asof(k2, 3) is None and ix.tick_asof(k2, 4) == 300, "a key that did not exist yet")
    check(ix.cells_asof(0) == 1 and ix.cells_asof(4) == 2 and ix.cells_asof(100) == 2, "cell counts as of each moment")
    try:
        ix.record(k2, 3, 250, new=False)
        raise AssertionError("an out-of-order ingest was accepted")
    except RuntimeError:
        pass
    return {"ok": True}


def unit_asof_decision_matches_archive() -> Dict[str, Any]:
    """continuation_asof at the latest sequence equals the engine's own continuation_decision on the same archive."""
    import random

    rnd = random.Random(1)
    params = cs.Params()
    arch = cs.Archive("arch", {}, 10 ** 6, params)
    ix = det.AsOfIndex()
    keys = []
    for n in range(1, 400):
        key = (rnd.randrange(8), rnd.randrange(4), rnd.choice(["G", "A2", "A1"]), 1023 - (1 << rnd.randrange(3)), rnd.randrange(-1, 3))
        lv = 10 - bin(key[3]).count("1")
        tick = rnd.randrange(50, 2000)
        verdict, c = arch.keep(key, lv, tick, bytes(tick), (0,), b"", b"", {"kind": "test"}, n)
        if verdict in (cs.NEW, cs.REPLACED):
            ix.record(c.key, n, c.tick, new=verdict == cs.NEW)
        keys.append(key)

    class Probe(det.DeterministicSchedule):
        def __init__(self) -> None:  # only the as-of machinery, no engine
            self._asof = ix

    probe = Probe()
    for _ in range(200):
        reaches = [(rnd.randrange(50, 2000), rnd.choice(keys) if rnd.random() < 0.8 else (99, 99, "G", 1, 1)) for _ in range(rnd.randrange(1, 6))]
        want = arch.continuation_decision(reaches)
        got = probe.continuation_asof(reaches, 10 ** 9)
        check(got == want, f"as-of decision {got} != archive decision {want}")
    return {"cells": len(arch.cells)}


# -- end-to-end on the fake game -----------------------------------------------------------------------------------------------------------


def same_seed_same_dispatches() -> Dict[str, Any]:
    b = bench()
    r1 = b.run("det_a", deterministic=True, seed=7)
    r2 = b.run("det_b", deterministic=True, seed=7)
    for r in (r1, r2):
        check(r["code"] == 0 and not r["violations"], f"the run completed cleanly: {r['code']} {r['violations']} {r['summary'].get('status')} "
                                                       f"{r['summary'].get('stop')} (folder {r['dir']})")
        check(r["summary"]["status"] == "DISPATCH_CAP" and r["summary"]["work"]["dispatches"] == PARAMS["max_dispatches"],
              f"stopped exactly at the dispatch cap: {r['summary']['status']} {r['summary']['work']['dispatches']}")
        sched = r["config"].get("scheduler") or {}
        check(sched.get("contract") == det.SCHEDULE_CONTRACT and sched.get("seed") == 7 and sched.get("lag") == 6,
              f"the scheduler (seed, key, lag) is saved with the run: {sched}")
        check((r["dir"] / "schedule.json").is_file(), "schedule.json is written")
        check(all("sched" in d for d in r["dispatches"] if d.get("kind", "burst") == "burst"), "every dispatch row names its draw")
    s1, s2 = det.dispatch_signature(r1["dispatches"]), det.dispatch_signature(r2["dispatches"])
    check(len(s1) == PARAMS["max_dispatches"] and s1 == s2, f"the same dispatch sequence ({len(s1)} vs {len(s2)} rows; "
                                                           f"first difference at {next((i for i, (x, y) in enumerate(zip(s1, s2)) if x != y), None)})")
    check(det.cells_signature(r1["cells"]) == det.cells_signature(r2["cells"]), "the same cell events, in the same order")
    check(verified_set(r1) == verified_set(r2), f"the same verified clears: {verified_set(r1)[:4]} vs {verified_set(r2)[:4]}")
    check(r1["summary"]["archive"] == r2["summary"]["archive"], "the same final archive counts")
    other = b.run("det_seed8", deterministic=True, seed=8)
    check(det.dispatch_signature(other["dispatches"]) != s1, "another seed gives another sequence (the seed is what decides)")
    stats = [json.loads((r["dir"] / "schedule_stats.jsonl").read_text(encoding="utf-8").splitlines()[-1]) for r in (r1, r2)]
    check(any(st["arrived_out_of_order"] > 0 for st in stats), f"jobs really finished out of dispatch order in these runs: {stats}")
    return {"arrived_out_of_order": [st["arrived_out_of_order"] for st in stats], "dispatches": len(s1), "cells": len(r1["cells"]), "verified": len(r1["verifications"]),
            "clears_claimed": r1["summary"]["work"].get("clears_claimed"), "cont_answers": sum(len(d.get("cont") or []) for d in r1["dispatches"])}


def plain_engine_for_reference() -> Dict[str, Any]:
    """The unmodified engine, same inputs, twice: reported, not asserted (see the module docstring)."""
    b = bench()
    p1 = b.run("plain_a", deterministic=False, seed=7)
    p2 = b.run("plain_b", deterministic=False, seed=7)
    for r in (p1, p2):
        check(r["code"] == 0 and not r["violations"], f"the plain run completed: {r['code']} {r['violations']}")
    s1, s2 = det.dispatch_signature(p1["dispatches"]), det.dispatch_signature(p2["dispatches"])
    first = next((i for i, (x, y) in enumerate(zip(s1, s2)) if x != y), None)
    return {"plain_runs_identical": s1 == s2, "first_difference_at_dispatch": (first + 1) if first is not None else None,
            "plain_dispatches": [len(s1), len(s2)], "completed_out_of_order": [completion_orders_differ(p1), completion_orders_differ(p2)]}


UNIT = {"unit_keyed_random": unit_keyed_random, "unit_asof_index": unit_asof_index, "unit_asof_decision_matches_archive": unit_asof_decision_matches_archive}
E2E = {"same_seed_same_dispatches": same_seed_same_dispatches, "plain_engine_for_reference": plain_engine_for_reference}

if __name__ == "__main__":
    args = sys.argv[1:]
    tests = dict(UNIT) if args[:1] == ["unit"] else dict(E2E) if args[:1] == ["e2e"] else dict(UNIT, **E2E)
    rest = [a for a in args if a not in ("unit", "e2e")]
    try:
        code = run_suite("det schedule tests", tests, rest)
    finally:
        if _BENCH is not None:
            _BENCH.close()
    sys.exit(code)
