#!/usr/bin/env python3
"""Zero-tick tests of the trail-lead probe (tools/frs/trail_probe.py). No game process is started: the real lab import is read
(never written) for the candidate-rule and prefix checks; the synthetic stub world (rl/m8_rd_stub) stands in for the game in the
dispatch and verification checks; the guard checks run in child processes (an audit hook cannot be removed). The test process
never arms the lab guard and writes only under temporary folders, which it removes.

    python -B tools/frs/trail_probe_tests.py                 every test
    python -B tools/frs/trail_probe_tests.py real            the real-import checks only (reads <lab root>/import)
    python -B tools/frs/trail_probe_tests.py stub            the synthetic checks only
    python -B tools/frs/trail_probe_tests.py only <name>     the tests whose name contains <name>
    ... [--lab-root DIR]                                     the lab root of the real-import checks (default C:/BattleShip_lab)
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import types
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

assert sys.flags.dont_write_bytecode, "run with python -B"

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
RL = REPO / "rl"
sys.path.insert(0, str(RL))
sys.path.insert(0, str(HERE))

import frs_guard as g  # noqa: E402
import frs_tests as T  # noqa: E402
import frs_verify as fv  # noqa: E402
import m8_rd_cells as mcell  # noqa: E402
import m8_rd_stub as stub  # noqa: E402
import trail_probe as tp  # noqa: E402

EXPECTED_LEADS = 198                     # the owner's expected count on the sd2 import (the splice probe's 198 candidates)
TESTS: List[Tuple[str, str, Callable[[], Optional[Dict[str, Any]]]]] = []
CREATED: List[Path] = []
LAB = Path(g.DEFAULT_LAB_ROOT)
_REAL: Dict[str, Any] = {}


def real(fn: Callable[[], Optional[Dict[str, Any]]]) -> Callable[[], Optional[Dict[str, Any]]]:
    TESTS.append(("real", fn.__name__, fn))
    return fn


def synthetic(fn: Callable[[], Optional[Dict[str, Any]]]) -> Callable[[], Optional[Dict[str, Any]]]:
    TESTS.append(("stub", fn.__name__, fn))
    return fn


def check(cond: Any, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def tmpdir(tag: str) -> Path:
    p = Path(tempfile.mkdtemp(prefix=f"trail_probe_{tag}_"))
    CREATED.append(p)
    return p


def real_import() -> Dict[str, Any]:
    """The real import, loaded once per test session (read-only; the archive is never mutated)."""
    if not _REAL:
        imp = LAB / "import"
        check((imp / "import_manifest.json").is_file(), f"no lab import at {imp}")
        lab, meta, R = tp.load_all(LAB)
        P = tp.build_plan(lab, R)
        man = json.loads((imp / "import_manifest.json").read_text(encoding="utf-8"))
        _REAL.update({"lab": lab, "meta": meta, "R": R, "P": P, "manifest": man})
    return _REAL


# =============================================================================================================================================
# the real import (zero native ticks)
# =============================================================================================================================================


@real
def real_candidate_rule_reproduces_198() -> Dict[str, Any]:
    X = real_import()
    lab, R, P, man = X["lab"], X["R"], X["P"], X["manifest"]
    p, starts = P["plan"], P["starts"]
    check(p["leads"] == EXPECTED_LEADS, f"{p['leads']} leads, expected {EXPECTED_LEADS}")
    check(len(starts) == EXPECTED_LEADS and len({s["cid"] for s in starts}) == EXPECTED_LEADS, "one start per lead cell")
    check(all(s["gain"] >= 1 and s["lead_L"] < s["route_tick"] and s["gain"] == s["route_tick"] - s["lead_L"] for s in starts), "every lead arrives earlier")
    check(all(not s[tp.LEAD]["terminal"] and not s[tp.CONTROL]["terminal"] for s in starts), "no terminal start")
    check(all(s["route_tick"] < p["route"]["words"] for s in starts), "no start at the route's final tick")
    check(len({s["draw_id"] for s in starts}) == len(starts) and all(f"|{tp.KEY_FAMILY}|" in s["draw_id"] for s in starts), "one key family per lead cell")
    check(all(s["level"] == mcell.level_of_mask(s["key"][3]) for s in starts), "the start level is the key's level")
    ref = man["reference_expected"]
    check(p["route"]["completion_input_tick"] == ref["completion_input_tick"] and p["route"]["completion_time_passed"] == ref["completion_time_passed"]
          and p["route"]["words"] == ref["ticks"], "the route's clocks are the import manifest's")
    check(p["route"]["final_chain"] == ref["final_chain"], "the route's final chain (recomputed from its trace) is the import manifest's")
    check(sorted(int(k) for k in p["arrival_by_level"]) == list(range(mcell.TARGETS_TOTAL + 1)), "an arrival tick per level 0..10")
    check(p["arrival_by_level"][str(mcell.TARGETS_TOTAL)] == ref["completion_input_tick"], "level 10 is reached at the completion tick")
    b = tp.budget(p, 10)
    check(b["dispatches"] == 2 * 10 * EXPECTED_LEADS and b["prefix_ticks"] == 10 * sum(s["lead_L"] + s["route_tick"] for s in starts)
          and b["burst_ticks_max"] == b["dispatches"] * tp.ARM["segment_words"] * tp.ARM["max_segments"], "the budget arithmetic")
    check(tp.ARM == {"segment_words": 120, "max_segments": 4, "window": 20}, f"the arm is the lab's CONT arm, got {tp.ARM}")
    rows = [tp.start_row(s) for s in starts]
    check(all("words_hex" not in json.dumps(r) and r[tp.LEAD]["words"] == s["lead_L"] and r[tp.CONTROL]["words"] == s["route_tick"] for r, s in zip(rows, starts)),
          "starts rows carry lengths and digests, not words")
    return {"leads": p["leads"], "trail_cells": p["route"]["trail_cells"], "lineage_bursts": p["route"]["lineage_bursts"], "skipped": p["skipped"],
            "per_level": {lv: d["leads"] for lv, d in p["per_level"].items()}, "prefix_ticks_per_round": p["prefix_ticks_per_round"],
            "budget_10": b, "archive": lab.archive_id}


@real
def real_prefixes_reproduce_archive_chain_digests() -> Dict[str, Any]:
    X = real_import()
    lab, R, P = X["lab"], X["R"], X["P"]
    p, starts = P["plan"], P["starts"]
    # the lead start is the representative's stored prefix with the cell's stored end record, record digest and chain digest
    for s in starts:
        c = lab.cells[s["cid"]]
        a = s[tp.LEAD]
        check(a["words"] == lab.rep_words(*s["rep"]) and len(a["words"]) == c.L == s["lead_L"], f"cell {c.id}: the lead prefix is the representative's words")
        check(a["chain"] == bytes(c.chain) and a["end_digest"] == bytes(c.end_digest) and tuple(a["end"]) == tuple(c.end), f"cell {c.id}: the lead record")
    # the control start is the route's words up to j_r; its chain, record digest and end state are recomputed from the stored reference trace and
    # must equal the route's own win record in the archive (kept when the route's arrival was NEW or REPLACE at ingest, even where a faster
    # arrival later replaced the representative)
    wc = p["win_check"]
    check(wc["all"][1] > 0 and wc["all"][0] == wc["all"][1], f"the control records equal the route's own win records: {wc['all']}")
    check(wc["leads"][1] > 0 and wc["leads"][0] == wc["leads"][1], f"... for the lead cells with a win record: {wc['leads']}")
    g0 = p["gain0_stored_chain_equal"]
    check(g0["on_route"][1] > 0 and g0["on_route"][0] == g0["on_route"][1],
          f"route cells whose representative is the route's own trajectory: stored chain == route chain {g0}")
    check(g0["other_arrival"][1] + g0["on_route"][1] == p["route"]["trail_cells"] - p["leads"], f"every gain-0 cell is classified {g0}")
    tr = R["trace"]
    for s in starts:
        jr = s["route_tick"]
        b = s[tp.CONTROL]
        check(b["words"] == R["words"][:jr], "the control prefix is the route's words")
        check(b["chain"] == fv.chain_of(tr["initial"], tr["steps"][:jr]), "the control chain equals the lab's chain_of over the same ticks")
        check(b["chain"] != s[tp.LEAD]["chain"], "a lead and its control are different states")
        check(int(b["end"][mcell.I_INPUT_TICK]) == jr and int(s[tp.LEAD]["end"][mcell.I_INPUT_TICK]) == s["lead_L"], "the end records carry their own input tick")
    return {"win_check": wc, "gain0": g0, "starts": len(starts), "controls_with_win": sum(1 for s in starts if s["win_checked"])}


# =============================================================================================================================================
# the guard refusals
# =============================================================================================================================================


@synthetic
def guard_refusals() -> Dict[str, Any]:
    lab = tmpdir("lab")
    bad_out = [REPO / "trail_probe_x", REPO / "runs" / "trail_probe_x", REPO / "logs" / "trail_probe_x", lab / "runs" / "x", lab.parent / "elsewhere_x",
               Path("D:/BattleShip_runs_backup/x"), Path("D:/BattleShip_source_snapshots/x"), Path("D:/BattleShip_exe_archive/x")]
    for b in bad_out:
        try:
            g.validate_run_dir(b, lab)
            raise AssertionError(f"output folder {b} was accepted")
        except g.LabRootError:
            pass
    check(g.validate_run_dir(lab / "trail_probe_2026-01-01", lab) == lab / "trail_probe_2026-01-01", "an output folder inside the lab root is accepted")
    for b in [REPO, REPO / "lab", REPO / "runs" / "lab", Path("D:/BattleShip_runs_backup"), Path("D:/BattleShip_source_snapshots/x"),
              Path("D:/BattleShip_exe_archive"), Path("C:/")]:
        try:
            g.validate_lab_root(b)
            raise AssertionError(f"lab root {b} was accepted")
        except g.LabRootError:
            pass
    probe = REPO / "logs" / f"trail_probe_guard_{os.getpid()}.tmp"
    try:
        g.LabFS(lab).write_text(probe, "must never exist")
        raise AssertionError("LabFS wrote outside the lab root")
    except g.LabRootError:
        pass
    check(not probe.exists(), "no file was created in the checkout")
    exits = {}
    for argv in (["plan", "--lab-root", str(lab), "--out", str(REPO / "trail_probe_x")], ["plan", "--lab-root", str(lab), "--out", str(lab / "runs" / "x")],
                 ["plan", "--lab-root", str(REPO / "lab_x")], ["plan", "--lab-root", str(lab), "--workers", "6"], ["plan", "--lab-root", str(lab), "--per-start", "0"]):
        try:
            tp.main(argv)
            raise AssertionError(f"main accepted {argv}")
        except SystemExit as exc:
            exits[" ".join(argv[1:])] = str(exc)[:80]
    check(not g.LabGuard.installed, "the refusals happened before the guard was armed in this process")
    st = g.guard_selftest(lab)                                        # a child process arms the guard on the real checkout and evidence roots
    check(st["ok"], f"the guard self-test on the temporary lab root: {json.dumps(st, default=str)[:600]}")
    return {"refused_outputs": len(bad_out), "main_refusals": exits, "guard_child": st["child"]}


# =============================================================================================================================================
# the readings and the clear verdict (stub traces)
# =============================================================================================================================================


@synthetic
def pace_and_depth_from_results() -> Dict[str, Any]:
    key_new = (1, 1, "A2", 1023, -1)
    key_known = (2, 2, "G", 1023, 4)
    key_trail = (3, 3, "A1", 1023, -1)
    lab = types.SimpleNamespace(by_key={key_known: 7, key_trail: 8}, cells={7: types.SimpleNamespace(L=150), 8: types.SimpleNamespace(L=90)})
    arrival = {0: 0, 1: 12, 2: 70, 3: 150, 4: 170, 5: 400}
    st = {"pair": 3, "cid": 5, "level": 2, "gain": 20, "draw_id": "a|trail|5|1:2"}
    reach = lambda j, key: (j, key, (), b"", b"", False)  # noqa: E731
    res = {"L": 100, "words": bytes([1] * 50), "breaks_all": [(10, 0), (60, 1), (130, 2), (145, 3)], "end_reason": "length", "ticks": 150,
           "reaches": [reach(105, key_new), reach(120, key_known), reach(140, key_trail)], "segments": 1, "decisions": [], "tick0": {"equal": True},
           "prefix": {"host_frame_equal": False}, "result_json": None}
    row = tp.summarise_result(res, st, tp.LEAD, 4, arrival, {key_trail: 200}, lab)
    check(row["deepest"] == 4 and row["advanced"] and row["levels"] == {"3": 130, "4": 145} and row["pace"] == {"3": 20, "4": 25}, f"levels / pace {row}")
    check(row["pace_first"] == 20 and row["delta_first"] == 0 and row["prefix_breaks"] == 2 and row["prefix_level_ok"], "first-level pace and the prefix level")
    check(row["outcome"] == "out_of_words" and row["words_played"] == 50 and row["ticks"] == 150 and row["start_tick"] == 100, "end and lengths")
    check(row["new_keys"] == 1 and row["shortenings"] == 1 and row["max_gain"] == 30 and row["trail_ahead"] == 1 and row["max_ahead"] == 60, "archive readings")
    check(row["claimed"] is None and row["final_chain"] is None and row["words_hex"] == "01" * 50 and row["k"] == 4 and row["pair"] == 3, "no claim without a clear")
    res2 = dict(res, end_reason="clear", result_json={"completion_input_tick": 145, "completion_time_passed": 144}, final_chain="ab" * 32,
                breaks_all=res["breaks_all"] + [(146, 4)])
    row2 = tp.summarise_result(res2, st, tp.CONTROL, 0, arrival, {}, lab)
    check(row2["outcome"] == "clear" and row2["claimed"] == {"completion_input_tick": 145, "completion_time_passed": 144} and row2["final_chain"] == "ab" * 32
          and row2["deepest"] == 5 and row2["pace"]["5"] == 254, f"a clear row {row2['claimed']} {row2['pace']}")
    res3 = dict(res, end_reason="fall", breaks_all=res["breaks_all"][:2], reaches=[])
    row3 = tp.summarise_result(res3, st, tp.CONTROL, 1, arrival, {}, lab)
    check(row3["outcome"] == "fall" and not row3["advanced"] and row3["deepest"] == 2 and row3["pace_first"] is None and row3["delta_first"] is None, "a fall row")
    s = tp.summarise_rows([row, row2, row3, dict(row, arm=tp.CONTROL, deepest=3, pace={"3": -5}, pace_first=-5, delta_first=-5)], [], [{}] * 4,
                          {"expected": {"completion_input_tick": 400}})
    lv = s["per_level"]["2"]
    check(lv[tp.LEAD]["jobs"] == 1 and lv[tp.LEAD]["advanced_share"] == 1.0 and lv[tp.LEAD]["deepest"] == 4 and lv[tp.LEAD]["pace_first_mean"] == 20.0, f"{lv}")
    check(lv[tp.CONTROL]["jobs"] == 3 and lv[tp.CONTROL]["clears"] == 1 and lv[tp.CONTROL]["falls"] == 1 and lv[tp.CONTROL]["deepest"] == 5
          and lv[tp.CONTROL]["advanced"] == 2 and lv[tp.CONTROL]["pace_first_best"] == 20, f"{lv}")
    check(s["pairs"] == {"pairs": 1, "lead_deeper": 0, "equal": 0, "control_deeper": 1, "lead_only_advanced": 0, "control_only_advanced": 0, "both_advanced": 1}, f"{s['pairs']}")
    check(len(s["furthest_leads"]) == 1 and s["furthest_leads"][0]["deepest"] == 4 and s["clears"]["verified"] == 0, "furthest leads and no clear")
    md = tp.report_md(dict(s, mode="lab", status="COMPLETED", stop={"reason": "x"}, utc_start="2026-01-01T00:00:00Z", elapsed_s=1.0, phase_wall_s={},
                           config={"per_start": 1, "n_workers": 1, "max_ticks": 1, "max_wall_s": 1, "arm": "CONT", **tp.ARM},
                           work={"dispatches": 4, "jobs": 4, "queued_left": 0, "excluded_pairs": 0, "ticks_total": 0, "prefix_ticks": 0, "burst_ticks": 0,
                                 "reference_ticks": 0, "verify_ticks": 0, "boundaries": 0, "continued": 0}, reference={}, memory={}, integrity={}))
    check(md.startswith("# Trail-lead probe run (2026-01-01)") and "| 2 | lead | 1 |" in md and md.endswith("\n"), "the report renders")
    return {"row_keys": len(row), "levels": s["per_level"]["2"][tp.LEAD]["deepest"]}


@synthetic
def verdict_on_stub_traces() -> Dict[str, Any]:
    words, claim = T.stub_clear("easy")
    cand = {"pair": 0, "cid": 1, "level": 0, "arm": tp.LEAD, "k": 0, "words": words, "claim": claim, "start_tick": 0, "gain": 0}
    t = claim["completion_input_tick"]
    rows = {}
    rows["ok"] = tp.clear_row(cand, fv.verify_twice(T.stub_replay(), stub.analyse, words, claim, "c1", 0), t + 1)
    rows["same"] = tp.clear_row(cand, fv.verify_twice(T.stub_replay(), stub.analyse, words, claim, "c2", 0), t)
    rows["tamper"] = tp.clear_row(cand, fv.verify_twice(T.stub_replay(tamper_second=True), stub.analyse, words, claim, "c3", 0), t + 1)
    rows["error"] = tp.clear_row(cand, fv.verify_twice(T.stub_replay(fail=10), stub.analyse, words, claim, "c4", 0), t + 1)
    rows["clock"] = tp.clear_row(cand, fv.verify_twice(T.stub_replay(), stub.analyse, words, dict(claim, completion_input_tick=t - 1), "c5", 0), t + 1)
    rows["chain"] = tp.clear_row(cand, fv.verify_twice(T.stub_replay(), stub.analyse, words, dict(claim, chain="0" * 64), "c6", 0), t + 1)
    r = rows["ok"]
    check(r["verdict"] == fv.VERIFIED and r["faster_than_reference"] and r["chain_r1"] == r["chain_r2"] == claim["chain"] and r["clocks_r1"] == r["clocks_r2"] == [t, t - 1]
          and r["breaks_r1"] == r["breaks_r2"] and r["words_digest"] == claim["words_digest"] and r["words_hex"] == words.hex(), f"VERIFIED row {r['reasons']}")
    check(rows["same"]["verdict"] == fv.VERIFIED and not rows["same"]["faster_than_reference"], "a clear at the reference's tick is not faster")
    check(rows["tamper"]["verdict"] == fv.NONDETERMINISTIC and not rows["tamper"]["faster_than_reference"] and rows["tamper"]["chain_r1"] != rows["tamper"]["chain_r2"],
          "two replays that disagree are NONDETERMINISTIC and never a clear")
    check(rows["error"]["verdict"] == fv.ERROR and not rows["error"]["faster_than_reference"] and rows["error"]["chain_r1"] is None, "a replay that cannot run is ERROR")
    check(rows["clock"]["verdict"] == fv.NONDETERMINISTIC and rows["chain"]["verdict"] == fv.NONDETERMINISTIC, "a claim the replay does not reproduce is never a clear")
    s = tp.summarise_rows([], list(rows.values()), [], {"expected": {"completion_input_tick": t + 1}})
    check(s["clears"]["candidates"] == 6 and s["clears"]["verified"] == 2 and s["clears"]["faster_than_reference"] == 1
          and s["clears"]["best_verified"]["completion_input_tick"] == t and s["clears"]["best_verified"]["chain_r1"] == claim["chain"], f"{s['clears']}")
    return {"clear_ticks": t, "verdicts": {k: v["verdict"] for k, v in rows.items()}}


# =============================================================================================================================================
# the synthetic end-to-end run (stub world; the engine runs in a guarded child process with real spawned workers)
# =============================================================================================================================================


def lead_count(a: Any, b: Any) -> int:
    words = a.rep_words(*b.start_rep) + bytes(b.words)
    first, _w = tp.trail_of(a, tp.route_lineage(a, b.iteration, words))
    return sum(1 for cid, jr in first.items() if a.cells[cid].L < jr and not a.cells[cid].terminal and jr < len(words))


def build_synthetic_import(imp: Path, world: str = "easy") -> Dict[str, Any]:
    """A six-session archive explored IN the stub world (as rl/frs_tests.build_stub_import), written like sd2's closing archive, with the
    archive's clear that has the MOST lead cells as the reference route. THE WORLD IS SYNTHETIC."""
    import m8_rd_worker as mw
    import m8_sd2_select as s6

    ctx = T.stub_ctx(world)
    t0 = mw.run_tick0(ctx, {"pin": None})
    pin = {"obs": t0["obs"], "digest": t0["digest"], "chain": t0["chain"], "key": t0["key"], "lines": t0["lines"], "mask": t0["mask"]}
    a = s6.Archive6("stubL", floor_min=-2550.0)
    a.init_cell0(tuple(t0["key"]), t0["obs"], bytes.fromhex(t0["digest"]), bytes.fromhex(t0["chain"]))
    state = {"it": 0, "cum": 0}

    def drive(n: int) -> None:
        for _ in range(n):
            it = state["it"]
            c = a.dispatch(it, 0)
            res = mw.run_iterate(ctx, T.iterate_job(a, c, it, pin, a.draw_for(it)))
            a.ingest(dict(res, cum_before=state["cum"], session="syn"))
            state["cum"] += res["ticks"]
            state["it"] += 1

    far = T.syn_ref(3000)
    drive(60)
    a.begin_v2(state["it"], "lines")
    drive(40)
    a.begin_rd3(state["it"], "lines")
    drive(40)
    a.begin_rd4(state["it"], "lines")
    drive(40)
    a.begin_sd1(state["it"], "lines", dict(far, session="rd4"), 24)
    drive(40)
    a.begin_sd2(state["it"], "lines", dict(far, session="sd1"), 24)
    drive(60)
    best = None
    for _ in range(15):
        clears = [b for b in a.bursts if b.end_reason == "clear"]
        best = max(clears, key=lambda b: lead_count(a, b)) if clears else None
        if best is not None and lead_count(a, best) >= 3:
            break
        drive(40)
    check(best is not None and lead_count(a, best) >= 1, "the synthetic archive holds a clear with a lead cell on its trail")
    words = a.rep_words(*best.start_rep) + bytes(best.words)
    tr = stub.replay_trace(world, words)
    tr["extra_env"] = dict(fv.FLAGS_VERIFY)
    (imp / "archive").mkdir(parents=True)
    task = {"id": "synthetic_stub_world", "character": "none", "stage": "stub"}
    a.write_files(imp / "archive", {"pin_tick0": pin, "task": task, "checkpoint_seq": 1})
    ref = imp / "reference"
    ref.mkdir()
    meta = {"task": task, "schema": "m8_rd_route_v1", "session": "sd2", "native_action_digest": mcell.words_digest(words), "words": len(words),
            "candidate": {"kind": "clear", "cid": best.start_cell}, "iteration": best.iteration,
            "completion_clocks": {"completion_input_tick": tr["result"]["completion_input_tick"], "completion_time_passed": tr["result"]["completion_time_passed"]}}
    (ref / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    with open(ref / "actions.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for i, w in enumerate(words):
            bb, x, y = mcell.TRIPLES[w]
            f.write(json.dumps({"buttons": bb, "stick_x": x, "stick_y": y, "consumed_tick": i}) + "\n")
    with gzip.open(ref / "trace.json.gz", "wt", encoding="utf-8") as f:
        json.dump(tr, f)
    (imp / "import_manifest.json").write_text(json.dumps({"mode": "lab", "synthetic": True}), encoding="utf-8")
    return {"leads": lead_count(a, best), "cells": len(a.cells), "bursts": len(a.bursts), "reference_ticks": len(words), "clears": len(clears)}


RUN_CHILD = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, {rl!r}); sys.path.insert(0, {here!r})
import frs_guard as g
lab = Path({lab!r})
g.LabGuard.install(lab)
import frs_machine as fm, frs_run as fr, m8_rd_stub as stub, trail_probe as tp
out = Path({out!r}); run_dir = out / {run_name!r}
L = tp.plan_and_write(lab, out, stub.analyse)
env = fr.LabEnv(worker_spec=lambda rank: {{"rank": rank, "backend": "m8_rd_stub:StubBackend", "world": "easy", "inject": {{}},
                                           "failure_dir": str(run_dir / "failures"), "guard": g.LabGuard.spec()}},
                replay=lambda words, label, slot: stub.replay_trace("easy", words, label), analyse=stub.analyse,
                readiness=lambda: {{"ok": True, "problems": []}}, battleship_pids=lambda: [], snapshot=fm.tree_snapshot, import_problems=lambda: [],
                wait_no_battleship=lambda t: [], code_manifest=lambda: {{}}, backend="stub", sample_s=0.25, row_every_s=0.5,
                caps=dict(fm.CAPS_MB, main_private=1e9))
cfg = tp.ProbeConfig(lab_root=lab, out=out, run_dir=run_dir, per_start={per_start!r}, n_workers=2, max_ticks={max_ticks!r}, max_wall_s=240.0,
                     stop_grace_s=10.0, verify_floor_s=5.0, verify_s_per_clear=2.0, write_reserve_s=2.0, progress_every_s=2.0)
code = tp.Probe(cfg, env, L["lab"], L["meta"], L["R"], L["P"]).run()
print(json.dumps({{"code": code, "violations": g.LabGuard.violations[:3], "leads": L["P"]["plan"]["leads"]}}))
'''


def run_child(code: str, timeout: float = 400.0) -> Dict[str, Any]:
    r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=timeout, cwd=str(HERE))
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise AssertionError(f"child failed: {(r.stderr or r.stdout)[-2500:]}")


def read_jsonl(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


@synthetic
def stub_end_to_end() -> Dict[str, Any]:
    lab = tmpdir("lab")
    info = build_synthetic_import(lab / "import")
    out = lab / "trail_probe_test"
    # the plan refuses to overwrite a different start set, accepts the same one again
    out.mkdir()
    (out / "plan.json").write_text(json.dumps({"start_set_digest": "0" * 64}), encoding="utf-8")
    try:
        tp.plan_and_write(lab, out, stub.analyse)
        raise AssertionError("a different saved start set was overwritten")
    except tp.ProbeError:
        pass
    (out / "plan.json").unlink()
    L = tp.plan_and_write(lab, out, stub.analyse)
    L2 = tp.plan_and_write(lab, out, stub.analyse)
    p = L["P"]["plan"]
    check(p["leads"] == info["leads"] == L2["P"]["plan"]["leads"] and p["start_set_digest"] == L2["P"]["plan"]["start_set_digest"], "the plan is deterministic")
    g0 = p["gain0_stored_chain_equal"]
    check(p["win_check"]["all"][0] == p["win_check"]["all"][1] and g0["on_route"][0] == g0["on_route"][1],
          f"the synthetic control records equal the route's own win records {p['win_check']} {g0}")
    check(len(read_jsonl(out / "starts.jsonl")) == p["leads"], "starts.jsonl")
    per_start = 2
    res = run_child(RUN_CHILD.format(rl=str(RL), here=str(HERE), lab=str(lab), out=str(out), run_name="run", per_start=per_start, max_ticks=50_000_000))
    check(res["code"] == 0 and not res["violations"], f"the synthetic run: {res}")
    run_dir = out / "run"
    s = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    rows = read_jsonl(run_dir / "dispatches.jsonl")
    n = p["leads"]
    check(s["status"] == "COMPLETED" and s["work"]["dispatches"] == 2 * per_start * n == len(rows) and s["work"]["queued_left"] == 0, f"{s['status']} {s['work']}")
    check(s["reference"]["ok"] is True and s["integrity"]["guard_violations_main"] == [] and s["integrity"]["battleship_left"] == [], f"{s['reference']} {s['integrity']}")
    check(all(r["outcome"] in ("clear", "fall", "out_of_words", "horizon", "ended") for r in rows), f"outcomes {sorted({r['outcome'] for r in rows})}")
    check(all(r["prefix_level_ok"] and r["tick0_equal"] is True for r in rows), "every prefix reproduced its level and the tick-0 pin")
    by = {(r["pair"], r["k"], r["arm"]): r for r in rows}
    for pair in range(n):
        for k in range(per_start):
            a, b = by[(pair, k, tp.LEAD)], by[(pair, k, tp.CONTROL)]
            check(a["draw_id"] == b["draw_id"] and a["start_tick"] < b["start_tick"] and a["gain"] == b["gain"] == b["start_tick"] - a["start_tick"], "a pair")
            wa, wb = bytes.fromhex(a["words_hex"]), bytes.fromhex(b["words_hex"])
            m = min(len(wa), len(wb))
            check(m > 0 and wa[:m] == wb[:m], f"pair {pair} k {k}: the lead and its control play the same random words (common random numbers)")
            check(a["ticks"] == a["start_tick"] + a["words_played"] and b["ticks"] == b["start_tick"] + b["words_played"], "ticks = prefix + words played")
    for r in rows:
        check(r["deepest"] == r["level"] + len(r["breaks_after_start"]) and r["advanced"] == (r["deepest"] > r["level"]), "deepest from the breaks")
        for lv, t in r["levels"].items():
            check(r["pace"][lv] == p["arrival_by_level"][lv] - t, "pace against the route's arrival")
    clears = [r for r in rows if r["outcome"] == "clear"]
    vrows = read_jsonl(run_dir / "verifications.jsonl") if (run_dir / "verifications.jsonl").is_file() else []
    check(len(vrows) == len(clears) == s["clears"]["candidates"], f"every clear candidate was verified: {len(vrows)} of {len(clears)}")
    check(all(v["verdict"] == fv.VERIFIED and v["chain_r1"] == v["chain_r2"] and v["clocks_r1"] == v["clocks_r2"] for v in vrows), "stub clears replay identically")
    check(s["clears"]["verified"] == len(vrows) and s["unverified"] == [], f"{s['clears']}")
    for v in vrows:
        r = by[(v["pair"], v["k"], v["arm"])]
        check(v["completion_input_tick"] == r["claimed"]["completion_input_tick"] == r["ticks"] and v["words"] == r["ticks"], "the verified clock is the in-run claim")
    check((run_dir / "report.md").read_text(encoding="utf-8").startswith("# Trail-lead probe run ("), "report.md")
    check((run_dir / "config.json").is_file() and (run_dir / "memory.jsonl").is_file() and (run_dir / "reference.json").is_file(), "the run folder")
    # a tick cap stops the dispatches cleanly (exit 0, status TICK_CAP, summary written)
    res2 = run_child(RUN_CHILD.format(rl=str(RL), here=str(HERE), lab=str(lab), out=str(out), run_name="run_cap", per_start=per_start,
                                      max_ticks=int(info["reference_ticks"] * 3 + 100)))
    s2 = json.loads((out / "run_cap" / "summary.json").read_text(encoding="utf-8"))
    check(res2["code"] == 0 and s2["status"] == "TICK_CAP" and 0 < s2["work"]["dispatches"] < 2 * per_start * n and s2["work"]["queued_left"] > 0
          and s2["work"]["ticks_total"] <= info["reference_ticks"] * 3 + 100, f"the tick cap: {s2['status']} {s2['work']}")
    # a second run into the same run folder is refused (never overwritten): the engine refuses at open, nothing is launched
    res3 = run_child(RUN_CHILD.format(rl=str(RL), here=str(HERE), lab=str(lab), out=str(out), run_name="run", per_start=1, max_ticks=10 ** 6))
    check(res3["code"] == 2 and any(f.name.startswith("refused_") for f in out.iterdir()), f"an existing run folder is refused: {res3}")
    return {"synthetic": info, "dispatches": len(rows), "clears_verified": s["clears"]["verified"], "advanced": sum(1 for r in rows if r["advanced"]),
            "pairs": s["pairs"], "cap_dispatches": s2["work"]["dispatches"]}


# =============================================================================================================================================


def main(argv: Sequence[str]) -> int:
    global LAB
    args = list(argv[1:])
    if "--lab-root" in args:
        i = args.index("--lab-root")
        LAB = Path(args[i + 1])
        del args[i:i + 2]
    sel = args[0] if args else "all"
    pick = [t for t in TESTS if sel == "all" or t[0] == sel or (sel == "only" and len(args) > 1 and args[1] in t[1])]
    passed = 0
    t_all = time.perf_counter()
    for kind, name, fn in pick:
        t0 = time.perf_counter()
        try:
            info = fn()
            passed += 1
            extra = json.dumps(info, default=str, separators=(",", ":"))[:400] if info else ""
            print(f"PASS {name} ({time.perf_counter() - t0:.1f} s) {extra}", flush=True)
        except Exception as exc:  # noqa: BLE001 - reported per test
            print(f"FAIL {name} ({time.perf_counter() - t0:.1f} s): {type(exc).__name__}: {exc}"[:3000], flush=True)
            print(traceback.format_exc()[-2500:], flush=True)
    for p in CREATED:
        shutil.rmtree(p, ignore_errors=True)
    print(f"trail probe tests: {passed}/{len(pick)} passed in {time.perf_counter() - t_all:.0f} s")
    return 0 if passed == len(pick) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
