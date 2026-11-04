#!/usr/bin/env python3
"""Tests for tools/analysis (no game, no lab folder needed).

    python -B tools/analysis/analysis_tests.py

records_*   the committed records parse into the expected numbers, and every consistency check between a record's tables and
            its own totals holds
lab_*       run2_lab.py on a handcrafted run folder whose answers are known
charts_*    every chart renders from the records dataset
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "rl"))

import run2_lab as lab  # noqa: E402
import run2_records as rec  # noqa: E402
from infra_testlib import check, cleanup, run_suite  # noqa: E402


def records_values() -> Dict[str, Any]:
    d = rec.build()
    bad = [c for c in d["checks"] if not c["ok"]]
    check(not bad, f"every consistency check holds: {bad}")
    h = d["hourly"]["rows"]
    check(h[0]["dispatches"] == 4145 and h[-1]["ticks"] == 5.23e6, "hour 1 and hour 8 rows")
    v = d["totals"]["values"]
    check(v["dispatches"] == 39309 and v["ticks"]["prefix"] == 46603859 and v["check_worker_s"] == 19772 and v["wall_s"] == 28505, "run totals")
    b = d["best_timeline"]["rows"]
    check([r["best"] for r in b] == [1352, 1261, 1245] and [r["elapsed_min"] for r in b] == [22, 255, 441], "best clear timeline")
    pt = d["bests_breaks"]["per_target_earliest_among_bests"]["values"]
    check(pt["4"]["earliest"] == 28 and pt["4"]["in_clear"] == "1,352" and pt["6"]["earliest"] == 1042, "per-target earliest among the bests")
    check(d["bests_breaks"]["breaks"]["1,885"][-1]["tick"] == 1885 and d["bests_breaks"]["breaks"]["1,261"][7]["tick"] == 1042, "the 'same as' rows expand")
    ch = {r["link"]: r["first_dispatched_at"] - r["created_at"] for r in d["chain_1245"]["rows"] if r["created_run"] == "run 2"}
    check(ch[10] == 4596 and ch[8] == 267, f"chain waits {ch}")
    w = d["worker_time"]
    check(w["evidence"] == "inferred" and w["range"]["low"]["per_job_s"] == 3.123 and abs(w["derived_shares"]["checks_share_of_worker_time"] - 0.1387) < 1e-4,
          "the inferred worker-time model and its derived check share")
    check(d["orders"]["prefixes_per_level"]["10"] == 5 and d["orders"]["level7"][0]["dispatches"] == 6341, "orders")
    return {"checks": len(d["checks"])}


def write_jsonl(p: Path, rows: Any) -> None:
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def synthetic_run(root: Path) -> Path:
    run = root / "run"
    run.mkdir(parents=True)
    write_jsonl(run / "cells.jsonl", [
        {"ev": "new", "cid": 0, "key": [0, 0, "G", 1023, 1], "level": 0, "tick": 0, "n": 0},
        {"ev": "new", "cid": 1, "key": [1, 0, "A2", 1022, -1], "level": 1, "tick": 50, "n": 1},
        {"ev": "new", "cid": 2, "key": [2, 1, "A2", 1020, -1], "level": 2, "tick": 120, "n": 2},
        {"ev": "replaced", "cid": 2, "key": [2, 1, "A2", 1020, -1], "level": 2, "tick": 100, "n": 1500},
        *[{"ev": "new", "cid": 10 + i, "key": [i % 3, 0, "A1", 1020, -1], "level": 2, "tick": 300 + i, "n": 3} for i in range(12)],
        {"ev": "new", "cid": 99, "key": [400, 0, "A1", 1020, -1], "level": 2, "tick": 999, "n": 4},
    ])
    write_jsonl(run / "dispatches.jsonl", [
        {"kind": "burst", "n": 1, "cid": 0, "level": 0, "outcome": "length", "advanced": True, "breaks_after_start": [[50, 4]], "wall_s": 2.0,
         "step_s": 1.5, "ask_s": 0.1, "ticks": 120, "words_played": 120, "prefix_level_ok": True, "tick0_equal": True},
        {"kind": "burst", "n": 2, "cid": 1, "level": 1, "outcome": "fall", "advanced": True, "breaks_after_start": [[118, 5], [120, 7]], "wall_s": 3.0,
         "step_s": 2.0, "ask_s": 0.0, "ticks": 170, "words_played": 120, "prefix_level_ok": True, "tick0_equal": True},
        {"kind": "burst", "n": 1500, "cid": 1, "level": 1, "outcome": "clear", "advanced": True, "breaks_after_start": [[100, 5]], "wall_s": 1.0,
         "step_s": 0.5, "ask_s": 0.0, "ticks": 200, "words_played": 150, "prefix_level_ok": False, "tick0_equal": True},
    ])
    write_jsonl(run / "verifications.jsonl", [
        {"verdict": "VERIFIED", "n": 1500, "completion_input_tick": 900, "wall_s": 4.0, "breaks_r1": [[t, i] for i, t in enumerate(range(80, 900, 82))][:10]},
        {"verdict": "NONDETERMINISTIC", "n": 7, "completion_input_tick": 800, "wall_s": 4.0, "breaks_r1": []},
    ])
    write_jsonl(run / "checks.jsonl", [{"wall_s": 5.0}])
    (run / "summary.json").write_text(json.dumps({"status": "WALL_CAP", "elapsed_s": 10.0}), encoding="utf-8")
    (run / "config.json").write_text(json.dumps({"n_workers": 2}), encoding="utf-8")
    return run


def lab_on_synthetic_folder() -> Dict[str, Any]:
    root = Path(tempfile.mkdtemp(prefix="analysis_lab_"))
    try:
        A = lab.analyse(synthetic_run(root))
        check(A["per_target"]["4"] == {"tick": 50, "dispatch": 1, "source": "burst"}, f"target 4 from the burst: {A['per_target']['4']}")
        check(A["per_target"]["5"]["tick"] == 100 and A["per_target"]["5"]["dispatch"] == 1500, "the later, faster burst wins")
        check(A["per_target"]["0"]["source"] == "verified clear" and A["per_target"]["0"]["tick"] == 80, "a target only a verified clear broke")
        check(len(A["orders"]) == 1 and A["orders"][0]["fastest"] == 900 and A["orders"][0]["clears"] == 1, "only VERIFIED rows make orders")
        sg = A["oddities"]["short_gaps"]
        check(len(sg) == 1 and sg[0]["gap"] == 2 and sg[0]["dispatch"] == 2, f"one short gap: {sg}")
        check(A["oddities"]["integrity_flags"] == [{"dispatch": 1500, "prefix_level_ok": False}], f"integrity flags: {A['oddities']['integrity_flags']}")
        check(any(o["cid"] == 99 and o["axis"] == "x" for o in A["oddities"]["position_outliers"]), "the far bucket is an outlier")
        w = A["worker_time"]
        check(w["job_clock_s"] == 6.0 and w["checks_s"] == 5.0 and w["verification_s"] == 8.0 and w["worker_s"] == 20.0 and w["outside_job_clock_s"] == 1.0,
              f"worker time arithmetic: {w}")
        ot = {r["window"]: r for r in A["over_time"]["rows"]}
        check(ot[1]["dispatches"] == 2 and ot[1]["new_cells"] == 15 and ot[2]["replacements"] == 1 and ot[2]["clears"] == 1, f"windows: {ot}")
        check([list(x) for x in A["earliest"]["2"]] == [[2, 120], [1500, 100]] and A["stall"]["level"] == 2 and A["stall"]["since_last"] == 0, f"earliest and stall: {A['earliest']} {A['stall']}")
        return {"targets": len(A["per_target"])}
    finally:
        cleanup(root)


def lab_refuses_writing_into_the_run() -> Dict[str, Any]:
    root = Path(tempfile.mkdtemp(prefix="analysis_lab_"))
    try:
        run = synthetic_run(root)
        r = subprocess.run([sys.executable, "-B", str(HERE / "run2_lab.py"), "--run", str(run), "--out", str(run), "--no-charts"], capture_output=True, text=True)
        check(r.returncode == 2 and "refused" in r.stderr, f"refused: {r.returncode} {r.stderr}")
        check(not (run / "lab_analysis.json").exists(), "nothing written in the run folder")
        return {"refused": True}
    finally:
        cleanup(root)


def charts_render() -> Dict[str, Any]:
    root = Path(tempfile.mkdtemp(prefix="analysis_charts_"))
    try:
        data = root / "d.json"
        r = subprocess.run([sys.executable, "-B", str(HERE / "run2_records.py"), "--out", str(data)], capture_output=True, text=True)
        check(r.returncode == 0, r.stdout + r.stderr)
        r = subprocess.run([sys.executable, "-B", str(HERE / "run2_charts.py"), "--data", str(data), "--out", str(root)], capture_output=True, text=True)
        check(r.returncode == 0, r.stderr[-800:])
        pngs = sorted(p.name for p in root.glob("*.png"))
        check(len(pngs) == 10 and all((root / p).stat().st_size > 20000 for p in pngs), f"ten charts: {pngs}")
        return {"charts": len(pngs)}
    finally:
        cleanup(root)


TESTS = {"records_values": records_values, "lab_on_synthetic_folder": lab_on_synthetic_folder,
         "lab_refuses_writing_into_the_run": lab_refuses_writing_into_the_run, "charts_render": charts_render}

if __name__ == "__main__":
    sys.exit(run_suite("analysis tests", TESTS, sys.argv[1:]))
