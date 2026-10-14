"""Fast-route lab (frs): the run report. `summary.json` (compact, one top-level key per line, "mode": "lab"), `report.md` (the same as a short
human table) and one row of the lab index (the lab copy `<lab root>/frs_lab_index.md`; the owner copies rows into docs/frs_lab_index.md and
commits them weekly). A clear is reported only when VERIFIED (two exact fresh-process replays from tick 0); everything else is a candidate.
Design: logs/frs_prep/phase1_plan.md section 8.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

SUMMARY_SCHEMA = "frs_lab_summary_v1"
INDEX_COLUMNS = ("run", "utc start", "arm", "label", "import", "wall min", "explore min", "status", "best verified clear (input / passed)",
                 "verified", "dispatches", "burst ticks", "new cells", "dispatches / h", "peak main MB", "MB / 1k new cells",
                 "continuation rate", "quarantines", "folder")
INDEX_TITLE = "# Fast-route lab index"
INDEX_INTRO = ("One row per lab run (exploratory, unregistered). Written by the runner into the lab root's copy of this file; the owner copies the "
               "rows here and commits them weekly. A clear appears only when verified by two exact fresh-process replays from tick 0.")


def compact_json(obj: Mapping[str, Any]) -> str:
    """One top-level key per line (compact values): short enough to read in the morning, still plain JSON."""
    lines = [f" {json.dumps(k)}: {json.dumps(v, separators=(',', ':'), default=str)}" for k, v in obj.items()]
    return "{\n" + ",\n".join(lines) + "\n}\n"


def best_verified(verifications: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    clears = [v for v in verifications if v.get("kind") == "clear" and v.get("verdict") == "VERIFIED"]
    if not clears:
        return None
    b = min(clears, key=lambda v: (v["completion_input_tick"], v["completion_time_passed"], v["iteration"]))
    return {"completion_input_tick": b["completion_input_tick"], "completion_time_passed": b["completion_time_passed"],
            "iteration": b["iteration"], "burst": b.get("burst"), "words_digest": b.get("words_digest"), "replays": 2,
            "final_chain": b.get("final_chain")}


def fmt(x: Any, nd: int = 0) -> str:
    if x is None:
        return "-"
    if isinstance(x, float):
        return f"{x:,.{nd}f}"
    if isinstance(x, int):
        return f"{x:,}"
    return str(x)


def index_header() -> str:
    return (f"{INDEX_TITLE}\n\n{INDEX_INTRO}\n\n| " + " | ".join(INDEX_COLUMNS) + " |\n|" + "|".join("---" for _ in INDEX_COLUMNS) + "|\n")


def index_row(s: Mapping[str, Any]) -> str:
    b = s["clears"].get("best_verified")
    best = f"{b['completion_input_tick']:,} / {b['completion_time_passed']:,}" if b else "none"
    w, t, a, m, c = s["work"], s["throughput"], s["archive"], s["memory"], s["continuation"]
    cells = [s["run_id"], s["utc_start"], s["arm"], s["label"], (s["start"].get("import_digest") or "none")[:12], fmt(round(s["config"]["wall_s"] / 60.0, 1), 1),
             fmt(round(s["phase_wall_s"].get("explore", 0.0) / 60.0, 1), 1), s["status"], best,
             f"{s['clears']['verified']} of {s['clears']['candidates']}", fmt(w["dispatches"]), fmt(w["burst_ticks"]), fmt(a["new_cells"]),
             fmt(t["dispatches_per_h"], 0), fmt((m.get("peak") or {}).get("main_private_mb"), 0),
             fmt((m.get("projection") or {}).get("mb_per_1000_new_cells"), 1),
             ("-" if c["boundaries"] == 0 else f"{c['continued']} / {c['boundaries']} ({100.0 * c['continued'] / c['boundaries']:.1f} %)"),
             str(s["quarantine"]["count"]), s["folder"]]
    return "| " + " | ".join(str(x).replace("|", "/") for x in cells) + " |\n"


def report_md(s: Mapping[str, Any]) -> str:
    b = s["clears"].get("best_verified")
    w, t, a, m, c = s["work"], s["throughput"], s["archive"], s["memory"], s["continuation"]
    pr = m.get("projection") or {}
    lines: List[str] = [f"# Lab run {s['run_id']}", "",
                        f"Exploratory and unregistered (mode lab). Arm **{s['arm']}**, label `{s['label']}`, status **{s['status']}** "
                        f"({s['stop']['reason']}).", "",
                        "| measure | value |", "|---|---|",
                        f"| wall limit / open / explore / close | {fmt(s['config']['wall_s'] / 60.0, 1)} min / {fmt(s['phase_wall_s'].get('open'), 0)} s / "
                        f"{fmt(s['phase_wall_s'].get('explore'), 0)} s / {fmt(s['phase_wall_s'].get('close'), 0)} s |",
                        f"| best verified clear (completion_input_tick / completion_time_passed) | "
                        f"{(fmt(b['completion_input_tick']) + ' / ' + fmt(b['completion_time_passed'])) if b else 'none'} |",
                        f"| clear candidates / verified / not verified | {s['clears']['candidates']} / {s['clears']['verified']} / "
                        f"{s['clears']['candidates'] - s['clears']['verified']} |",
                        f"| reference clear re-verified in-run | {s['clears']['reference']} |",
                        f"| dispatches / committed jobs / cut | {fmt(w['dispatches'])} / {fmt(w['jobs'])} / {fmt(w['cut_jobs'])} |",
                        f"| ticks / prefix / burst | {fmt(w['ticks'])} / {fmt(w['prefix_ticks'])} / {fmt(w['burst_ticks'])} |",
                        f"| new cells / replacements | {fmt(a['new_cells'])} / {fmt(a['replacements'])} |",
                        f"| per explore hour: dispatches / burst ticks / new cells | {fmt(t['dispatches_per_h'], 0)} / {fmt(t['burst_ticks_per_h'], 0)} / "
                        f"{fmt(t['new_cells_per_h'], 0)} |",
                        f"| continuation: boundaries / continued | {c['boundaries']} / {c['continued']} |",
                        f"| burst length (words) of the jobs | {json.dumps(c['jobs_by_words'])} |",
                        f"| quarantines | {s['quarantine']['count']} |",
                        f"| main process MB: load / peak | {fmt(pr.get('load_main_mb'), 0)} / {fmt((m.get('peak') or {}).get('main_private_mb'), 0)} |",
                        f"| bytes per cell at load / MB per 1,000 new cells | {fmt(pr.get('bytes_per_cell_at_load'))} / {fmt(pr.get('mb_per_1000_new_cells'), 1)} |",
                        f"| projected main MB after 8 / 24 / 48 h of exploration | {json.dumps(pr.get('projected_main_mb'))} |",
                        f"| hours to the memory budget / to the cap | {fmt(pr.get('hours_to_soft_budget'), 1)} / {fmt(pr.get('hours_to_cap'), 1)} |",
                        f"| tree peaks: private / working set MB, BattleShip processes | {fmt((m.get('peak') or {}).get('tree_private_mb'), 0)} / "
                        f"{fmt((m.get('peak') or {}).get('tree_working_set_mb'), 0)} / {(m.get('peak') or {}).get('battleship')} |",
                        "", "Fastest arrival per level (archive's shortest L at that level; the reference clear's arrival beside it):", "",
                        "| level | start | end | change | reference |", "|---|---|---|---|---|"]
    ref = s["archive"].get("reference_arrival") or {}
    for lv, (st, en) in a["fastest_arrival"].items():
        lines.append(f"| {lv} | {fmt(st)} | {fmt(en)} | {fmt(None if st is None or en is None else en - st)} | {fmt(ref.get(lv))} |")
    lines += ["", "Verifications (every clear candidate, twice from tick 0 in fresh processes with the verify flags):", "",
              "| kind | iteration | words | verdict | completion_input_tick / time_passed | reasons |", "|---|---|---|---|---|---|"]
    for v in s["clears"]["rows"]:
        lines.append(f"| {v['kind']} | {fmt(v.get('iteration'))} | {fmt(v.get('words'))} | {v['verdict']} | "
                     f"{fmt(v.get('completion_input_tick'))} / {fmt(v.get('completion_time_passed'))} | {'; '.join(v.get('reasons') or [])[:160]} |")
    if s["clears"].get("unverified"):
        lines.append(f"\nCandidates NOT verified before the close deadline (never clears): {json.dumps(s['clears']['unverified'])}")
    lines += ["", f"Integrity: {json.dumps(s['integrity'], separators=(',', ':'))}", ""]
    return "\n".join(lines)


def append_index(index_path: Path, summary: Mapping[str, Any], write_text: Any) -> str:
    """Append one row to the lab copy of the index (created with the tracked file's header when absent)."""
    text = Path(index_path).read_text(encoding="utf-8") if Path(index_path).is_file() else index_header()
    if not text.endswith("\n"):
        text += "\n"
    row = index_row(summary)
    write_text(Path(index_path), text + row)
    return row
