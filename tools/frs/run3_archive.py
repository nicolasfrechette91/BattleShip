#!/usr/bin/env python3
"""Run 3 archive helpers (2026-11-04 session; SESSION_LOG_2026-11-04.md sections 7.3 and 11): cell keys merged across every run an
archive inherits, and the (level, mask) group of a cell. Zero native ticks; reads cells.jsonl files only.

    merged keys     the cells.jsonl files in inheritance order (run 1, then run 2, ...); the LAST row per cell id is its current
                    representative. A run writes only its own NEW / REPLACED rows, so a cell inherited and never rewritten exists only
                    in an earlier run's file: run 2's 1,906 dispatches of 1,490 such cells had no mask in run 2's file alone.
    refusals        `require_consistent` refuses an archive in which a cell's rows carry different masks or keys, a row's mask
                    disagrees with its level, or a cell has no key. Measured on runs 1 + 2: 37,294 cells, 181,657 rows, 0 of each.
    group           (level, mask) of a cell; a cell with no key is the explicit group UNKNOWN, never merged into another one.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

UNKNOWN = "unknown"
TARGETS_TOTAL = 10


class ArchiveKeyError(RuntimeError):
    pass


def level_of_mask(mask: int) -> int:
    return TARGETS_TOTAL - bin(int(mask)).count("1")


def merged_cells(cells_files: Sequence[Path]) -> Tuple[Dict[int, Dict[str, Any]], Dict[str, Any]]:
    """{cell id: its last row (source, ev, key, level, tick, digest)} over the files in order, and the consistency report."""
    last: Dict[int, Dict[str, Any]] = {}
    masks: Dict[int, set] = {}
    keys: Dict[int, set] = {}
    nrows: Dict[int, int] = {}
    report: Dict[str, Any] = {"files": [str(p) for p in cells_files], "rows": 0, "rows_per_file": {}, "level_conflicts": [],
                              "missing_keys": []}
    for src in cells_files:
        n = 0
        with open(src, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                c = json.loads(line)
                n += 1
                cid = int(c["cid"])
                key = tuple(c["key"]) if c.get("key") else None
                row = {"source": str(src), "ev": c.get("ev"), "key": key, "level": int(c["level"]), "tick": int(c["tick"]),
                       "digest": c.get("digest")}
                last[cid] = row
                nrows[cid] = nrows.get(cid, 0) + 1
                if key is None:
                    report["missing_keys"].append(cid)
                    continue
                masks.setdefault(cid, set()).add(int(key[3]))
                keys.setdefault(cid, set()).add(key)
                if level_of_mask(key[3]) != row["level"]:
                    report["level_conflicts"].append(cid)
        report["rows_per_file"][str(src)] = n
        report["rows"] += n
    report["cells"] = len(last)
    report["multi_row_cells"] = sum(1 for n in nrows.values() if n > 1)
    report["mask_conflicts"] = sorted(cid for cid, s in masks.items() if len(s) > 1)
    report["key_conflicts"] = sorted(cid for cid, s in keys.items() if len(s) > 1)
    report["missing_keys"] = sorted(set(report["missing_keys"]) - set(keys))
    report["level_conflicts"] = sorted(set(report["level_conflicts"]))
    return last, report


def require_consistent(report: Mapping[str, Any]) -> None:
    bad = {k: len(report[k]) for k in ("mask_conflicts", "key_conflicts", "level_conflicts", "missing_keys") if report.get(k)}
    if bad:
        raise ArchiveKeyError(f"refused: the merged archive is not consistent: {bad} (first cells: "
                              f"{ {k: list(report[k])[:5] for k in bad} })")


def group_of(level: int, cell: Optional[Mapping[str, Any]]) -> Tuple[int, Any]:
    """(level, live-target mask) of a cell, or (level, UNKNOWN) when the cell or its key is unknown: never another group."""
    if cell is None or not cell.get("key"):
        return int(level), UNKNOWN
    return int(level), int(cell["key"][3])


def group_table(dispatch_rows: Iterable[Mapping[str, Any]], cells: Mapping[int, Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Dispatches, breaking bursts, falls and claimed clears per (level, mask) group, from dispatch rows and the merged keys."""
    out: Dict[Tuple[int, Any], Dict[str, Any]] = {}
    for d in dispatch_rows:
        if d.get("kind", "burst") != "burst":
            continue
        lv, mask = group_of(int(d["level"]), cells.get(int(d["cid"])))
        g = out.setdefault((lv, mask), {"level": lv, "mask": mask, "dispatches": 0, "broke": 0, "falls": 0, "clears": 0})
        g["dispatches"] += 1
        g["broke"] += int(bool(d.get("breaks_after_start")))
        g["falls"] += int(d.get("outcome") == "fall")
        g["clears"] += int(d.get("outcome") == "clear")
    return sorted(out.values(), key=lambda g: (-g["level"], -g["dispatches"]))
