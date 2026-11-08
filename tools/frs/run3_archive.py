#!/usr/bin/env python3
"""Run 3 archive helpers (2026-11-04 session; SESSION_LOG_2026-11-04.md sections 7.3 and 11): cell keys merged across every run an
archive inherits, and the (level, mask) group of a cell. Zero native ticks; reads cells.jsonl files only.

    merged keys     the cells.jsonl files in inheritance order (run 1, then run 2, ...); the LAST row per cell id is its current
                    representative. A run writes only its own NEW / REPLACED rows, so a cell inherited and never rewritten exists only
                    in an earlier run's file: run 2's 1,906 dispatches of 1,490 such cells had no mask in run 2's file alone.
    refusals        `require_consistent` refuses an archive in which a cell's rows carry different masks or keys, a row's mask
                    disagrees with its level, or a cell has no key. Measured on runs 1 + 2: 37,294 cells, 181,657 rows, 0 of each.
    group           (level, mask) of a cell; a cell with no key is the explicit group UNKNOWN, never merged into another one.
    end records     (2026-11-05, step 5) run 3 writes the end record of a cell (the 17 observation values at its tick) in its NEW / REPLACED
                    rows (`end`) and, for an inherited cell, in an `end_record` row after its first (fused) dispatch. An `end_record` row
                    never replaces the representative: it is attached to the representative with the same words digest. Two end records
                    of one representative that differ in a compared field (all but host_frame) are refused (`end_conflicts`).
                    `end_records` reads them for a later run (or a resumed one) to import by (cell id, words digest).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

_RL = Path(__file__).resolve().parents[2] / "rl"
if str(_RL) not in sys.path:
    sys.path.insert(0, str(_RL))

import m8_rd_cells as mcell  # noqa: E402

UNKNOWN = "unknown"
CLEAN_STATUSES = ("COMPLETED", "ARCHIVE_EMPTY", "TICK_CAP", "WALL_CAP", "CELLS_CAP", "DISPATCH_CAP", "MEMORY_BUDGET")
END_RECORD_EV = "end_record"
TARGETS_TOTAL = 10


class ArchiveKeyError(RuntimeError):
    pass


def level_of_mask(mask: int) -> int:
    return TARGETS_TOTAL - bin(int(mask)).count("1")


def merged_cells(cells_files: Sequence[Path]) -> Tuple[Dict[int, Dict[str, Any]], Dict[str, Any]]:
    """{cell id: its last row (source, ev, key, level, tick, digest, end)} over the files in order, and the consistency report."""
    last: Dict[int, Dict[str, Any]] = {}
    ends: Dict[int, Dict[str, Any]] = {}
    masks: Dict[int, set] = {}
    keys: Dict[int, set] = {}
    nrows: Dict[int, int] = {}
    report: Dict[str, Any] = {"files": [str(p) for p in cells_files], "rows": 0, "rows_per_file": {}, "level_conflicts": [],
                              "missing_keys": [], "end_record_rows": 0, "end_conflicts": []}
    for src in cells_files:
        n = 0
        with open(src, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                c = json.loads(line)
                n += 1
                cid = int(c["cid"])
                if c.get("ev") == END_RECORD_EV:
                    report["end_record_rows"] += 1
                    _note_end(ends, report, cid, c["digest"], c["end"])
                    continue
                key = tuple(c["key"]) if c.get("key") else None
                row = {"source": str(src), "ev": c.get("ev"), "key": key, "level": int(c["level"]), "tick": int(c["tick"]),
                       "digest": c.get("digest"), "end": None}
                if c.get("end") is not None:
                    _note_end(ends, report, cid, c.get("digest"), c["end"])
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
    for cid, row in last.items():
        row["end"] = ends.get(cid, {}).get(row["digest"])
    report["cells"] = len(last)
    report["with_end_record"] = sum(1 for row in last.values() if row["end"] is not None)
    report["end_conflicts"] = sorted(set(report["end_conflicts"]))
    report["multi_row_cells"] = sum(1 for n in nrows.values() if n > 1)
    report["mask_conflicts"] = sorted(cid for cid, s in masks.items() if len(s) > 1)
    report["key_conflicts"] = sorted(cid for cid, s in keys.items() if len(s) > 1)
    report["missing_keys"] = sorted(set(report["missing_keys"]) - set(keys))
    report["level_conflicts"] = sorted(set(report["level_conflicts"]))
    return last, report


def _note_end(ends: Dict[int, Dict[str, Any]], report: Dict[str, Any], cid: int, digest: Any, end: Sequence[Any]) -> None:
    """Keep the first end record of a representative; a later one must equal it in every compared field."""
    if len(end) != len(mcell.OBS_FIELDS):
        raise ArchiveKeyError(f"cell {cid}: an end record with {len(end)} fields")
    have = ends.setdefault(cid, {})
    if digest in have:
        if mcell.obs_diffs(tuple(end), tuple(have[digest])):
            report["end_conflicts"].append(cid)
        return
    have[digest] = list(end)


def require_consistent(report: Mapping[str, Any]) -> None:
    bad = {k: len(report[k]) for k in ("mask_conflicts", "key_conflicts", "level_conflicts", "missing_keys", "end_conflicts") if report.get(k)}
    if bad:
        raise ArchiveKeyError(f"refused: the merged archive is not consistent: {bad} (first cells: "
                              f"{ {k: list(report[k])[:5] for k in bad} })")


def end_records(cells_files: Sequence[Path]) -> Tuple[Dict[Tuple[int, str], List[Any]], Dict[str, Any]]:
    """{(cell id, words digest): end record} from every `end` a cells.jsonl row carries (end_record rows and NEW / REPLACED rows), the
    first per representative, and a report (files with sha256, records, end_conflicts). A run imports the records whose (cell, digest)
    is a representative of its archive: a record of a representative that was replaced since is never attached to the new one."""
    ends: Dict[int, Dict[str, Any]] = {}
    report: Dict[str, Any] = {"files": [], "rows": 0, "end_record_rows": 0, "end_conflicts": []}
    for src in cells_files:
        h = hashlib.sha256()
        with open(src, "rb") as f:
            data = f.read()
        h.update(data)
        n = 0
        for line in data.decode("utf-8").splitlines():
            if not line.strip():
                continue
            c = json.loads(line)
            n += 1
            if c.get("end") is None:
                continue
            report["end_record_rows"] += int(c.get("ev") == END_RECORD_EV)
            _note_end(ends, report, int(c["cid"]), c.get("digest"), c["end"])
        report["files"].append({"path": str(src), "sha256": h.hexdigest(), "rows": n})
        report["rows"] += n
    out = {(cid, str(dg)): end for cid, by in ends.items() for dg, end in by.items()}
    report["records"] = len(out)
    report["end_conflicts"] = sorted(set(report["end_conflicts"]))
    return out, report


def end_record_source_problems(cells_files: Sequence[Path], accepted: Iterable[Any] = ()) -> List[str]:
    """Why each cells.jsonl file may not give end records to a later run (owner 2026-11-06): its run folder must have stopped with a clean
    status (not SEARCH_INVALID, SEARCH_INCOMPLETE or CLAIMS_FROZEN), unless the owner's decision names that folder (`accepted`: run
    folders or their parent output folders, as recorded in the plan)."""
    import os

    acc = {os.path.normcase(str(Path(a).resolve())) for a in accepted}
    out: List[str] = []
    for f in cells_files:
        run = Path(f).resolve().parent
        sp = run / "summary.json"
        if not sp.is_file():
            out.append(f"{f}: no summary.json beside it (a run that did not close)")
            continue
        status = json.loads(sp.read_text(encoding="utf-8")).get("status")
        if status in CLEAN_STATUSES:
            continue
        if os.path.normcase(str(run)) in acc or os.path.normcase(str(run.parent)) in acc:
            continue
        out.append(f"{f}: its run stopped with status {status} and no plan flag names it")
    return out


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
