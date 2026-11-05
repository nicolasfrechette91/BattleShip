#!/usr/bin/env python3
"""Tests of tools/frs/run3_archive.py (merged keys, explicit unknown group). Zero native ticks.

    python -B tools/frs/run3_archive_tests.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "rl"))

import run3_archive as ar  # noqa: E402
from infra_testlib import check, cleanup, run_suite, tmpdir  # noqa: E402

R1 = Path("C:/BattleShip_lab/crossing_2026-10-15/run")
R2 = Path("C:/BattleShip_lab/crossing_2026-10-15_run2/run")


def _write(p: Path, rows: Any) -> Path:
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return p


def unit_merge_and_refusals() -> Dict[str, Any]:
    d = tmpdir("run3_archive_")
    try:
        a = _write(d / "a.jsonl", [{"cid": 1, "ev": "new", "key": [0, 0, "G", 1022, 3], "level": 1, "tick": 50},
                                   {"cid": 2, "ev": "new", "key": [1, 0, "A2", 1020, -1], "level": 2, "tick": 80}])
        b = _write(d / "b.jsonl", [{"cid": 2, "ev": "replaced", "key": [1, 0, "A2", 1020, -1], "level": 2, "tick": 70},
                                   {"cid": 3, "ev": "new", "key": [2, 1, "G", 1016, 4], "level": 3, "tick": 120}])
        cells, rep = ar.merged_cells([a, b])
        check(sorted(cells) == [1, 2, 3] and cells[2]["tick"] == 70 and cells[2]["source"].endswith("b.jsonl"), "the last row per cell wins, across files")
        check(rep["multi_row_cells"] == 1 and not rep["mask_conflicts"] and not rep["missing_keys"], f"report: {rep}")
        ar.require_consistent(rep)
        bad = _write(d / "c.jsonl", [{"cid": 1, "ev": "replaced", "key": [0, 0, "G", 1021, 3], "level": 1, "tick": 40}])
        _cells, rep2 = ar.merged_cells([a, bad])
        check(rep2["mask_conflicts"] == [1], f"a cell whose rows carry different masks is found: {rep2['mask_conflicts']}")
        try:
            ar.require_consistent(rep2)
            raise AssertionError("an inconsistent archive was accepted")
        except ar.ArchiveKeyError:
            pass
        lv = _write(d / "d.jsonl", [{"cid": 9, "ev": "new", "key": [0, 0, "G", 1023, 3], "level": 4, "tick": 10}])
        check(ar.merged_cells([lv])[1]["level_conflicts"] == [9], "a mask that disagrees with its level is found")
        check(ar.group_of(9, None) == (9, ar.UNKNOWN) and ar.group_of(9, {"key": None}) == (9, ar.UNKNOWN), "an unknown cell is the explicit unknown group")
        tab = ar.group_table([{"cid": 3, "level": 3, "outcome": "fall"}, {"cid": 77, "level": 3, "outcome": "clear"}], cells)
        check({(g["level"], g["mask"]) for g in tab} == {(3, 1016), (3, ar.UNKNOWN)}, f"a dispatch of an unknown cell is never merged into a group: {tab}")
        return {"cells": len(cells)}
    finally:
        cleanup(d)


def lab_runs_1_and_2() -> Dict[str, Any]:
    """The real archive (when the lab is on this machine): consistent, and run 2's level-9 groups as the records state."""
    if not (R1 / "cells.jsonl").is_file() or not (R2 / "cells.jsonl").is_file():
        return {"skipped": "no lab runs on this machine"}
    cells, rep = ar.merged_cells([R1 / "cells.jsonl", R2 / "cells.jsonl"])
    ar.require_consistent(rep)
    with open(R2 / "dispatches.jsonl", encoding="utf-8") as f:
        tab = ar.group_table((json.loads(x) for x in f), cells)
    l9 = {g["mask"]: g["dispatches"] for g in tab if g["level"] == 9}
    check(l9 == {64: 8078, 2: 8027, 256: 4879}, f"run 2's level-9 groups: {l9}")
    check(not [g for g in tab if g["mask"] == ar.UNKNOWN], "no unknown group with the merged keys")
    return {"cells": rep["cells"], "rows": rep["rows"], "level9": l9}


if __name__ == "__main__":
    sys.exit(run_suite("run3 archive tests", {"unit_merge_and_refusals": unit_merge_and_refusals, "lab_runs_1_and_2": lab_runs_1_and_2},
                       sys.argv[1:]))
