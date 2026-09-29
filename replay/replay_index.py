#!/usr/bin/env python3
"""Index and browser for episode artifacts under runs/ (read-only), feeding the replay viewer.

    python replay/replay_index.py scan [--full] [--recent-minutes 5]
    python replay/replay_index.py list [filters] [--sort KEY[,KEY]] [--limit N] [--format table|paths|json]
    python replay/replay_index.py show N|EPISODE_ID|PATH
    python replay/replay_index.py play N|EPISODE_ID|PATH [viewer options...]
    python replay/replay_index.py check N|EPISODE_ID|PATH          (headless MATCH/DESYNC)
    python replay/replay_index.py gui                               (sortable, filterable table)
    replay\\replay_index.cmd ...                                     (Windows wrapper)

N is a row number of the last `list`. The cache is replay/_local/index.sqlite.
A rescan re-reads only episode directories whose mtime changed, plus summary
files (evaluation.json, crossing_verification.json, census.json) whose
mtime/size changed. Episode directories modified in the last few minutes, or
without metadata.json, are skipped: they may still be being written.

Left entry (first live tick with position_x < -2100) and qualified crossing
(btt_qualified_crossing_v1) are NOT in metadata.json. They are taken from the
best available per-episode source, in this order:

    replay       replay/_local/verdicts.jsonl (this tool's own replays; MATCH only)   exact, yes/no
    gate_trace   gate_trace.json.gz in the episode dir (M7r evaluations)            exact, yes/no
    eval_metrics evaluation.json -> eval_metrics.first_left_entry (M7g-K..M7r evals) exact, yes/no
    census       runs/m7p/addendum/walltop_census/census.json                         exact, yes/no
    reward_v3    labels.reward_v3 (M7j/M7k/M7l)                                        exact, yes/no
    m7s_goals    m7s_goals.json.gz cells (x bins aligned to -2100)                     exact, yes/no
    crossing_verification.json records (candidates only)                             yes only
    final_obs    final observation live and x < -2100                                  yes only

Everything else is "?" (unknown). Crossing yes/no comes from
crossing_verification.json or the census; "no left entry" implies no crossing.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from replay_episode import LEFT_BOUNDARY_X, REPO_ROOT, recorded_end, recorded_targets  # noqa: E402

RUNS_DIR = REPO_ROOT / "runs"
LOCAL_DIR = REPO_ROOT / "replay" / "_local"
INDEX_DB = LOCAL_DIR / "index.sqlite"
LAST_LIST = LOCAL_DIR / "last_list.json"
VERDICTS_FILE = LOCAL_DIR / "verdicts.jsonl"
VIEWER = Path(__file__).resolve().parent / "replay.py"
SCHEMA_VERSION = 1

# Directory names that never contain episode artifacts in any runs/ layout (per-process game dirs, runtime
# copies, logs, checkpoints). Pruned for speed; --no-prune walks everything.
PRUNE_NAMES = {"logs", "runtime", "runtime_gens", "episodes", "coordination", "checkpoints", "__pycache__"}
PRUNE_RE = re.compile(r"g\d+_a\d+$")
SUMMARY_FILES = ("evaluation.json", "crossing_verification.json", "census.json")
EPISODE_SIDECARS = ("gate_trace.json.gz", "m7s_goals.json.gz")
M7S_LEFT_MAX_I = 5  # btt_goal_cell_v1: i = floor((x + 3900) / 300); i <= 5  <=>  x < -2100 exactly

EXACT_SOURCES = ("replay", "gate_trace", "eval_metrics", "census", "reward_v3", "m7s_goals")
POSITIVE_SOURCES = ("crossing_verification", "final_obs")

EPISODE_COLUMNS = (
    "path", "episode_id", "milestone", "run", "phase", "worker", "role", "run_id", "profile", "observation", "reward",
    "end_kind", "end_detail", "truncation", "rows", "steps", "targets", "cleared", "completion_tick",
    "completion_time", "last_tick", "final_x", "final_y", "prefix_rows", "created", "sidecars", "dir_mtime_ns",
    "meta_mtime_ns",
)


# -- database --------------------------------------------------------------------------------------------


def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    db_path = Path(db_path or INDEX_DB)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    row = db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
    if row is None or int(row[0]) != SCHEMA_VERSION:
        db.executescript("DROP TABLE IF EXISTS episodes; DROP TABLE IF EXISTS summaries; "
                         "DROP TABLE IF EXISTS annotations;")
        db.execute("INSERT OR REPLACE INTO meta VALUES ('schema', ?)", (str(SCHEMA_VERSION),))
    cols = ", ".join(f"{c} {'TEXT PRIMARY KEY' if c == 'path' else ''}" for c in EPISODE_COLUMNS)
    db.execute(f"CREATE TABLE IF NOT EXISTS episodes ({cols})")
    db.execute("CREATE TABLE IF NOT EXISTS summaries (path TEXT PRIMARY KEY, mtime_ns INTEGER, size INTEGER)")
    db.execute("CREATE TABLE IF NOT EXISTS annotations (episode_id TEXT, source TEXT, source_path TEXT, "
               "left_entry INTEGER, left_tick INTEGER, min_x REAL, crossing INTEGER, "
               "PRIMARY KEY (episode_id, source))")
    db.commit()
    return db


# -- metadata -> row ---------------------------------------------------------------------------------------


def rel(path: Path) -> str:
    try:
        return Path(path).relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return Path(path).as_posix()


def split_location(rel_path: str) -> Tuple[str, str, str, Optional[str]]:
    """(milestone, run, phase, worker) from runs/<milestone>/<run...>/[workers/wNN/]artifacts*/<episode>."""
    parts = rel_path.split("/")
    if parts and parts[0] == "runs":
        parts = parts[1:]
    milestone = parts[0] if parts else ""
    middle = parts[1:-1]
    worker = None
    if middle and middle[-1].startswith("artifacts"):
        middle = middle[:-1]
    if len(middle) >= 2 and middle[-2] == "workers":
        worker = middle[-1]
        middle = middle[:-2]
    run = "/".join(middle)
    phase = middle[-1] if middle else ""
    return milestone, run, phase, worker


def _get(d: Any, *keys: str) -> Any:
    for k in keys:
        d = d.get(k) if isinstance(d, dict) else None
    return d


def _int(v: Any) -> Optional[int]:
    return int(v) if isinstance(v, int) and not isinstance(v, bool) else None


def _float(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def episode_row(d: Path, meta: Dict[str, Any], names: Iterable[str], dir_mtime: int, meta_mtime: int) -> Dict[str, Any]:
    labels = meta.get("labels") if isinstance(meta.get("labels"), dict) else {}
    terminal = meta.get("terminal") if isinstance(meta.get("terminal"), dict) else {}
    exp = labels.get("experiment") if isinstance(labels.get("experiment"), dict) else {}
    final = meta.get("final_observation") if isinstance(meta.get("final_observation"), dict) else {}
    kind, detail = recorded_end(meta)
    path = rel(d)
    milestone, run, phase, worker = split_location(path)
    observation = _get(labels, "contracts", "policy_observation_contract") or _get(exp, "policy_observation",
                                                                                    "contract")
    return {
        "path": path,
        "episode_id": str(meta.get("episode_id") or d.name),
        "milestone": milestone, "run": run, "phase": phase, "worker": worker,
        "role": labels.get("role"), "run_id": labels.get("run_id"),
        "profile": exp.get("name") or exp.get("environment_profile"),
        "observation": observation,
        "reward": labels.get("reward_contract"),
        "end_kind": kind, "end_detail": detail,
        "truncation": labels.get("truncation_reason", terminal.get("truncation_reason")),
        "rows": _int(meta.get("action_count")),
        "steps": _int(terminal.get("step_count")),
        "targets": recorded_targets(meta),
        "cleared": 1 if labels.get("cleared", terminal.get("cleared")) is True else 0,
        "completion_tick": _int(labels.get("completion_input_tick")),
        "completion_time": _int(labels.get("completion_time_passed")),
        "last_tick": _int(terminal.get("last_consumed_tick")),
        "final_x": _float(final.get("position_x")) if final.get("fighter_valid") == 1 and final.get("btt_active") == 1
        else None,
        "final_y": _float(final.get("position_y")) if final.get("fighter_valid") == 1 and final.get("btt_active") == 1
        else None,
        "prefix_rows": _int(_get(labels, "m7h_start", "prefix_length")),
        "created": _get(meta, "diagnostics", "created_utc") or "",
        "sidecars": ",".join(sorted(n for n in names if n not in ("actions.jsonl", "metadata.json"))),
        "dir_mtime_ns": dir_mtime, "meta_mtime_ns": meta_mtime,
    }


# -- per-episode annotations --------------------------------------------------------------------------------


def annotations_from_episode(d: Path, meta: Dict[str, Any], names: Iterable[str]) -> List[Dict[str, Any]]:
    """Left-entry facts derivable from the episode directory itself."""
    eid = str(meta.get("episode_id") or d.name)
    out: List[Dict[str, Any]] = []
    rv3 = _get(meta, "labels", "reward_v3")
    if isinstance(rv3, dict) and isinstance(rv3.get("entry_counts"), dict):
        first = rv3.get("first_entry") if isinstance(rv3.get("first_entry"), dict) else None
        n = sum(int(v) for v in rv3["entry_counts"].values() if isinstance(v, int))
        out.append({"episode_id": eid, "source": "reward_v3", "source_path": rel(d / "metadata.json"),
                    "left_entry": 1 if (n > 0 or first) else 0,
                    "left_tick": _int(first.get("consumed_tick")) if first else None, "min_x": None, "crossing": None})
    final = meta.get("final_observation") if isinstance(meta.get("final_observation"), dict) else {}
    if final.get("fighter_valid") == 1 and final.get("btt_active") == 1 and \
            isinstance(final.get("position_x"), (int, float)) and final["position_x"] < LEFT_BOUNDARY_X:
        out.append({"episode_id": eid, "source": "final_obs", "source_path": rel(d / "metadata.json"),
                    "left_entry": 1, "left_tick": None, "min_x": None, "crossing": None})
    names = set(names)
    if "gate_trace.json.gz" in names:
        try:
            with gzip.open(d / "gate_trace.json.gz", "rt", encoding="utf-8") as fp:
                doc = json.load(fp)
            f = {k: i for i, k in enumerate(doc["fields"])}
            first_t, min_x = None, None
            for row in doc["rows"]:
                if not row[f["live"]] or row[f["t"]] is None or row[f["t"]] < 0:
                    continue
                x = float(row[f["pos_x"]])
                min_x = x if min_x is None else min(min_x, x)
                if first_t is None and x < LEFT_BOUNDARY_X:
                    first_t = int(row[f["t"]])
            out.append({"episode_id": eid, "source": "gate_trace", "source_path": rel(d / "gate_trace.json.gz"),
                        "left_entry": 1 if first_t is not None else 0, "left_tick": first_t, "min_x": min_x,
                        "crossing": None})
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            pass
    if "m7s_goals.json.gz" in names:
        try:
            with gzip.open(d / "m7s_goals.json.gz", "rt", encoding="utf-8") as fp:
                doc = json.load(fp)
            first_t = None
            for t, cell in enumerate(doc.get("cells") or []):
                if isinstance(cell, str) and cell:
                    if int(cell.split(",")[0]) <= M7S_LEFT_MAX_I:
                        first_t = t
                        break
            out.append({"episode_id": eid, "source": "m7s_goals", "source_path": rel(d / "m7s_goals.json.gz"),
                        "left_entry": 1 if first_t is not None else 0, "left_tick": first_t, "min_x": None,
                        "crossing": None})
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            pass
    return out


def annotations_from_summary(path: Path) -> List[Dict[str, Any]]:
    """Left-entry / crossing facts from a run-level summary file."""
    try:
        with open(path, encoding="utf-8") as fp:
            doc = json.load(fp)
    except (OSError, ValueError):
        return []
    out: List[Dict[str, Any]] = []
    src = rel(path)
    if path.name == "evaluation.json":
        for e in doc.get("episodes") or []:
            m = e.get("eval_metrics") if isinstance(e, dict) else None
            if not isinstance(m, dict) or "first_left_entry" not in m or not e.get("episode_id"):
                continue
            first = m.get("first_left_entry") if isinstance(m.get("first_left_entry"), dict) else None
            out.append({"episode_id": e["episode_id"], "source": "eval_metrics", "source_path": src,
                        "left_entry": 1 if first else 0, "left_tick": _int(first.get("consumed_tick")) if first else None,
                        "min_x": _float(m.get("min_live_x")), "crossing": None})
    elif path.name == "crossing_verification.json":
        for r in doc.get("records") or []:
            if not isinstance(r, dict) or not r.get("episode_id"):
                continue
            a = r.get("analysis") if isinstance(r.get("analysis"), dict) else {}
            first = a.get("first_left_entry") if isinstance(a.get("first_left_entry"), dict) else None
            exact = r.get("exact")
            exact_ok = exact.get("ok") if isinstance(exact, dict) else exact
            out.append({"episode_id": r["episode_id"], "source": "crossing_verification", "source_path": src,
                        "left_entry": 1 if first else None, "left_tick": _int(first.get("consumed_tick")) if first else None,
                        "min_x": _float(a.get("min_x")) if not isinstance(a.get("min_x"), dict)
                        else _float(a["min_x"].get("x")),
                        "crossing": (1 if r.get("qualified_crossing") else 0) if exact_ok is not False else None})
    elif path.name == "census.json":
        for e in doc.get("episodes") or []:
            if not isinstance(e, dict) or not e.get("episode_id") or not e.get("exact_replay", True):
                continue
            out.append({"episode_id": e["episode_id"], "source": "census", "source_path": src,
                        "left_entry": 1 if (e.get("left_entries") or 0) > 0 else 0,
                        "left_tick": _int(e.get("first_left_entry_tick")), "min_x": _float(e.get("min_x")),
                        "crossing": 1 if e.get("qualified_crossing") else 0})
    return out


def upsert_annotations(db: sqlite3.Connection, rows: List[Dict[str, Any]]) -> None:
    db.executemany("INSERT OR REPLACE INTO annotations VALUES (:episode_id, :source, :source_path, :left_entry, "
                   ":left_tick, :min_x, :crossing)", rows)


# -- scan --------------------------------------------------------------------------------------------------------


def _is_link(entry: os.DirEntry) -> bool:
    try:
        return entry.is_symlink() or bool(getattr(os.path, "isjunction", lambda p: False)(entry.path))
    except OSError:
        return True


def scan(*, root: Path = RUNS_DIR, full: bool = False, recent_minutes: float = 5.0, prune: bool = True,
         progress=print, db_path: Optional[Path] = None) -> Dict[str, Any]:
    """Walk runs/ (read-only) and bring the index up to date. Returns counts."""
    t0 = time.monotonic()
    db = connect(db_path)
    cached = {r["path"]: (r["dir_mtime_ns"], r["meta_mtime_ns"])
              for r in db.execute("SELECT path, dir_mtime_ns, meta_mtime_ns FROM episodes")}
    summaries_cached = {r["path"]: (r["mtime_ns"], r["size"]) for r in db.execute("SELECT * FROM summaries")}
    horizon_ns = time.time_ns() - int(recent_minutes * 60e9)
    stats = {"episodes_seen": 0, "added_or_updated": 0, "unchanged": 0, "skipped_recent": 0, "skipped_no_metadata": 0,
             "unreadable": 0, "removed": 0, "summaries_read": 0, "dirs_listed": 0}
    seen: set = set()
    summaries_seen: Dict[str, Tuple[int, int, Path]] = {}
    stack: List[Tuple[Path, int]] = [(root, 0)]
    last_report = time.monotonic()
    while stack:
        d, d_mtime = stack.pop()
        try:
            with os.scandir(d) as it:
                entries = list(it)
        except OSError:
            continue
        stats["dirs_listed"] += 1
        if time.monotonic() - last_report > 5:
            progress(f"  ... {stats['dirs_listed']} directories, {stats['episodes_seen']} episodes")
            last_report = time.monotonic()
        by_name = {e.name: e for e in entries}
        if "actions.jsonl" in by_name:
            _index_episode(db, d, d_mtime, by_name, cached, horizon_ns, full, stats, seen)
            continue
        artifacts_dir = d.name.startswith("artifacts")
        for e in entries:
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if is_dir:
                if _is_link(e) or (prune and (e.name in PRUNE_NAMES or PRUNE_RE.match(e.name))):
                    continue
                mtime = e.stat(follow_symlinks=False).st_mtime_ns  # free on Windows (from the listing)
                if artifacts_dir and e.name.startswith("episode_") and not full:
                    p = rel(Path(e.path))
                    if p in cached and cached[p][0] == mtime:  # write-once artifact, unchanged directory
                        seen.add(p)
                        stats["episodes_seen"] += 1
                        stats["unchanged"] += 1
                        continue
                stack.append((Path(e.path), mtime))
            elif e.name in SUMMARY_FILES:
                st = e.stat()
                summaries_seen[rel(Path(e.path))] = (st.st_mtime_ns, st.st_size, Path(e.path))
    for p, (mtime, size, full_path) in summaries_seen.items():
        if full or summaries_cached.get(p) != (mtime, size):
            db.execute("DELETE FROM annotations WHERE source_path = ?", (p,))
            upsert_annotations(db, annotations_from_summary(full_path))
            db.execute("INSERT OR REPLACE INTO summaries VALUES (?, ?, ?)", (p, mtime, size))
            stats["summaries_read"] += 1
    root_rel = rel(root)
    for p in cached:
        if p not in seen and (p == root_rel or p.startswith(root_rel + "/")):
            db.execute("DELETE FROM episodes WHERE path = ?", (p,))
            stats["removed"] += 1
    for p in summaries_cached:
        if p not in summaries_seen and (p.startswith(root_rel + "/")):
            db.execute("DELETE FROM annotations WHERE source_path = ?", (p,))
            db.execute("DELETE FROM summaries WHERE path = ?", (p,))
    db.execute("INSERT OR REPLACE INTO meta VALUES ('last_scan_utc', ?)",
               (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),))
    db.commit()
    db.close()
    stats["wall_s"] = round(time.monotonic() - t0, 1)
    return stats


def _index_episode(db, d: Path, d_mtime: int, by_name: Dict[str, os.DirEntry], cached, horizon_ns: int,
                   full: bool, stats: Dict[str, Any], seen: set) -> None:
    p = rel(d)
    if "metadata.json" not in by_name:
        stats["skipped_no_metadata"] += 1
        return
    try:
        if not d_mtime:
            d_mtime = d.stat().st_mtime_ns
        meta_mtime = by_name["metadata.json"].stat().st_mtime_ns
        newest = max(d_mtime, meta_mtime, by_name["actions.jsonl"].stat().st_mtime_ns)
    except OSError:
        stats["unreadable"] += 1
        return
    if newest > horizon_ns:
        stats["skipped_recent"] += 1
        return
    seen.add(p)
    stats["episodes_seen"] += 1
    if not full and cached.get(p) == (d_mtime, meta_mtime):
        stats["unchanged"] += 1
        return
    try:
        with open(d / "metadata.json", encoding="utf-8") as fp:
            meta = json.load(fp)
        if not isinstance(meta, dict):
            raise ValueError("metadata.json is not an object")
    except (OSError, ValueError):
        stats["unreadable"] += 1
        seen.discard(p)
        return
    row = episode_row(d, meta, by_name.keys(), d_mtime, meta_mtime)
    db.execute(f"INSERT OR REPLACE INTO episodes VALUES ({', '.join(':' + c for c in EPISODE_COLUMNS)})", row)
    db.execute("DELETE FROM annotations WHERE episode_id = ? AND source IN ('reward_v3', 'final_obs', 'gate_trace', "
               "'m7s_goals')", (row["episode_id"],))
    upsert_annotations(db, annotations_from_episode(d, meta, by_name.keys()))
    stats["added_or_updated"] += 1


# -- query --------------------------------------------------------------------------------------------------------


def load_verdicts(path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """Latest replay verdict per episode directory (this tool's own replays)."""
    out: Dict[str, Dict[str, Any]] = {}
    try:
        with open(path or VERDICTS_FILE, encoding="utf-8") as fp:
            for line in fp:
                try:
                    v = json.loads(line)
                except ValueError:
                    continue
                if isinstance(v, dict) and v.get("episode_dir"):
                    out[v["episode_dir"]] = v
    except OSError:
        pass
    return out


def load_rows(db_path: Optional[Path] = None, verdicts_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Every indexed episode with resolved left entry / crossing / replay verdict."""
    db = connect(db_path)
    rows = [dict(r) for r in db.execute("SELECT * FROM episodes")]
    notes: Dict[str, List[Dict[str, Any]]] = {}
    for a in db.execute("SELECT * FROM annotations"):
        notes.setdefault(a["episode_id"], []).append(dict(a))
    db.close()
    verdicts = load_verdicts(verdicts_path)
    for r in rows:
        ann = {a["source"]: a for a in notes.get(r["episode_id"], [])}
        v = verdicts.get(r["path"])
        r["replay"] = v.get("verdict") if v else None
        r["replay_mode"] = v.get("mode") if v else None
        if v and v.get("verdict") == "MATCH" and isinstance(v.get("trajectory"), dict):
            t = v["trajectory"]
            first = t.get("first_left_entry")
            ann["replay"] = {"source": "replay", "source_path": rel(VERDICTS_FILE), "left_entry": 1 if first else 0,
                             "left_tick": first.get("consumed_tick") if first else None,
                             "min_x": t.get("min_live_x"), "crossing": None}
        r["left"], r["left_tick"], r["left_source"], r["min_x"] = None, None, None, None
        for s in EXACT_SOURCES + POSITIVE_SOURCES:
            a = ann.get(s)
            if a is None or a["left_entry"] is None:
                continue
            if s in POSITIVE_SOURCES and not a["left_entry"]:
                continue
            r["left"], r["left_tick"], r["left_source"] = bool(a["left_entry"]), a["left_tick"], s
            break
        for s in EXACT_SOURCES + ("crossing_verification",):
            a = ann.get(s)
            if a is not None and a.get("min_x") is not None:
                r["min_x"] = a["min_x"]
                break
        r["crossing"], r["crossing_source"] = None, None
        for s in ("crossing_verification", "census"):
            a = ann.get(s)
            if a is not None and a.get("crossing") is not None:
                r["crossing"], r["crossing_source"] = bool(a["crossing"]), s
                break
        if r["crossing"] is None and r["left"] is False:
            r["crossing"], r["crossing_source"] = False, "no left entry"
        r["sources"] = sorted(ann)
    return rows


SORT_KEYS = {
    "targets": lambda r: r["targets"] if r["targets"] is not None else -1,
    "left": lambda r: {True: 2, None: 1, False: 0}[r["left"]],
    "left_tick": lambda r: r["left_tick"] if r["left_tick"] is not None else 10 ** 9,
    "crossing": lambda r: {True: 2, None: 1, False: 0}[r["crossing"]],
    "completion": lambda r: r["completion_tick"] if r["completion_tick"] is not None else 10 ** 9,
    "end": lambda r: {"clear": 0, "fall": 1, "truncated": 2}.get(r["end_kind"], 3),
    "last_tick": lambda r: r["last_tick"] if r["last_tick"] is not None else -1,
    "steps": lambda r: r["steps"] if r["steps"] is not None else -1,
    "min_x": lambda r: r["min_x"] if r["min_x"] is not None else 10 ** 9,
    "created": lambda r: r["created"] or "",
    "path": lambda r: r["path"],
    "milestone": lambda r: r["milestone"],
}
DESCENDING_BY_DEFAULT = {"targets", "left", "crossing", "created", "last_tick", "steps"}


def tri(value: Optional[bool]) -> str:
    return {True: "yes", False: "no", None: "?"}[value]


def filter_rows(rows: List[Dict[str, Any]], args: argparse.Namespace) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        if args.milestone and not any(r["milestone"] == m or r["milestone"].startswith(m) for m in args.milestone):
            continue
        if args.run and args.run.lower() not in (r["run"] or "").lower():
            continue
        if args.role and r["role"] != args.role:
            continue
        if args.end and r["end_kind"] not in args.end:
            continue
        if args.min_targets is not None and (r["targets"] is None or r["targets"] < args.min_targets):
            continue
        if args.max_targets is not None and (r["targets"] is None or r["targets"] > args.max_targets):
            continue
        if args.cleared and not r["cleared"]:
            continue
        if args.left and tri(r["left"]) not in args.left:
            continue
        if args.crossing and tri(r["crossing"]) not in args.crossing:
            continue
        if args.replay and (r["replay"] or "none").lower() not in args.replay:
            continue
        if args.text and args.text.lower() not in (r["path"] + " " + (r["run_id"] or "") + " " +
                                                   (r["profile"] or "")).lower():
            continue
        out.append(r)
    return out


def sort_rows(rows: List[Dict[str, Any]], spec: str, reverse: Optional[bool]) -> List[Dict[str, Any]]:
    keys = [k.strip() for k in spec.split(",") if k.strip()]
    for k in reversed(keys):
        desc = k.startswith("-")
        name = k.lstrip("+-")
        if name not in SORT_KEYS:
            raise SystemExit(f"unknown sort key {name!r}; choose from {', '.join(SORT_KEYS)}")
        if not k.startswith(("+", "-")):
            desc = name in DESCENDING_BY_DEFAULT
        if reverse:
            desc = not desc
        rows.sort(key=SORT_KEYS[name], reverse=desc)
    return rows


def left_text(r: Dict[str, Any]) -> str:
    if r["left"] and r["left_tick"] is not None:
        return f"yes@{r['left_tick']}"
    return tri(r["left"])


def print_table(rows: List[Dict[str, Any]]) -> None:
    head = f"{'#':>4}  {'tgt':>3}  {'end':<9} {'tick':>5}  {'left':<9} {'cross':<5} {'replay':<6} {'role':<5} {'where':<52} episode"
    print(head)
    print("-" * len(head))
    for i, r in enumerate(rows, 1):
        tick = r["completion_tick"] if r["end_kind"] == "clear" else r["last_tick"]
        where = f"{r['milestone']}/{r['run']}" + (f" {r['worker']}" if r["worker"] else "")
        if len(where) > 52:
            where = "..." + where[-49:]
        role = (r["role"] or "")[:5]
        print(f"{i:>4}  {r['targets'] if r['targets'] is not None else '-':>3}  {r['end_kind']:<9} "
              f"{tick if tick is not None else '-':>5}  {left_text(r):<9} {tri(r['crossing']):<5} "
              f"{(r['replay'] or '-'):<6} {role:<5} {where:<52} {r['episode_id']}")


def save_last_list(rows: List[Dict[str, Any]]) -> None:
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    with open(LAST_LIST, "w", encoding="utf-8", newline="\n") as fp:
        json.dump([r["path"] for r in rows], fp)


def resolve_target(token: str) -> Path:
    """A row number from the last list, an episode id (or unique suffix), or a path."""
    if token.isdigit():
        try:
            paths = json.loads(LAST_LIST.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            paths = []
        n = int(token)
        if 1 <= n <= len(paths):
            return REPO_ROOT / paths[n - 1]
        if len(token) < 6:  # too short to be an episode-id suffix
            raise SystemExit(f"row {n} is not in the last list (1..{len(paths)})" if paths
                             else "no previous `list` to take a row number from")
    p = Path(token)
    if p.exists():
        return p.resolve()
    db = connect()
    hits = [r["path"] for r in db.execute("SELECT path FROM episodes WHERE episode_id = ? OR episode_id LIKE ?",
                                          (token, f"%{token}"))]
    db.close()
    if len(hits) == 1:
        return REPO_ROOT / hits[0]
    if not hits:
        raise SystemExit(f"no indexed episode matches {token!r}")
    raise SystemExit(f"{token!r} matches {len(hits)} episodes; use a row number or the path")


def run_viewer(path: Path, extra: List[str]) -> int:
    return subprocess.call([sys.executable, str(VIEWER), str(path), *extra])


# -- commands ------------------------------------------------------------------------------------------------------


def add_filters(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--milestone", "-m", action="append", help="runs/<milestone> prefix, e.g. m7p (repeatable)")
    ap.add_argument("--run", help="substring of the run path, e.g. geo4_s1/final")
    ap.add_argument("--role", choices=("training", "evaluation"))
    ap.add_argument("--end", action="append", choices=("clear", "fall", "truncated", "unknown"))
    ap.add_argument("--min-targets", type=int)
    ap.add_argument("--max-targets", type=int)
    ap.add_argument("--cleared", action="store_true")
    ap.add_argument("--left", action="append", choices=("yes", "no", "?"), help="left entry (x < -2100)")
    ap.add_argument("--crossing", action="append", choices=("yes", "no", "?"), help="btt_qualified_crossing_v1")
    ap.add_argument("--replay", action="append", choices=("match", "desync", "none"))
    ap.add_argument("--text", help="substring of path / run_id / profile")


def cmd_scan(args) -> int:
    print(f"scanning {rel(Path(args.root).resolve())} (read-only){' - full rescan' if args.full else ''} ...")
    stats = scan(root=Path(args.root).resolve(), full=args.full, recent_minutes=args.recent_minutes,
                 prune=not args.no_prune)
    print("  " + ", ".join(f"{k} {v}" for k, v in stats.items()))
    return 0


def cmd_list(args) -> int:
    if args.scan or not INDEX_DB.exists():
        cmd_scan(argparse.Namespace(root=RUNS_DIR, full=False, recent_minutes=args.recent_minutes, no_prune=False))
    rows = sort_rows(filter_rows(load_rows(), args), args.sort, args.reverse)
    total = len(rows)
    if args.limit:
        rows = rows[:args.limit]
    save_last_list(rows)
    if args.format == "paths":
        for r in rows:
            print(r["path"])
    elif args.format == "json":
        print(json.dumps(rows, indent=1, default=str))
    else:
        print_table(rows)
        print(f"{len(rows)} of {total} matching episodes shown (index {INDEX_DB.relative_to(REPO_ROOT).as_posix()}); "
              "play one with: replay_index play N")
    return 0


def cmd_show(args) -> int:
    path = resolve_target(args.target)
    p = rel(path)
    rows = [r for r in load_rows() if r["path"] == p]
    if not rows:
        print(f"{p} is not indexed (run `scan`)")
        return 1
    r = rows[0]
    for k in ("episode_id", "path", "milestone", "run", "phase", "worker", "role", "run_id", "profile", "observation",
              "reward", "end_kind", "end_detail", "rows", "steps", "targets", "cleared", "completion_tick",
              "completion_time", "last_tick", "final_x", "final_y", "prefix_rows", "created", "sidecars"):
        print(f"  {k:<16} {r[k]}")
    print(f"  {'left entry':<16} {left_text(r)} (source {r['left_source'] or '-'}), min x {r['min_x']}")
    print(f"  {'crossing':<16} {tri(r['crossing'])} (source {r['crossing_source'] or '-'})")
    print(f"  {'replay':<16} {r['replay'] or '-'} {('(' + r['replay_mode'] + ')') if r['replay_mode'] else ''}")
    print(f"  {'sources':<16} {', '.join(r['sources']) or '-'}")
    return 0


def cmd_play(args, extra: List[str]) -> int:
    return run_viewer(resolve_target(args.target), extra)


def cmd_check(args, extra: List[str]) -> int:
    return run_viewer(resolve_target(args.target), ["--check", *extra])


def cmd_gui(args) -> int:
    import replay_browser

    return replay_browser.main(load_rows, scan)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Index / browse episode artifacts under runs/ for the replay viewer.",
                                 epilog=__doc__.split("\n\n", 2)[2], formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="update the cached index (incremental)")
    s.add_argument("--full", action="store_true", help="re-read every episode and summary file")
    s.add_argument("--recent-minutes", type=float, default=5.0, help="skip episodes modified this recently (default 5)")
    s.add_argument("--no-prune", action="store_true", help="also walk logs/runtime/episodes/... directories")
    s.add_argument("--root", default=str(RUNS_DIR), help="scan only this subtree (default runs/)")
    lp = sub.add_parser("list", help="filter + sort the index")
    add_filters(lp)
    lp.add_argument("--sort", default="targets,left,created",
                    help=f"comma-separated keys, prefix - or + to force order: {', '.join(SORT_KEYS)}")
    lp.add_argument("--reverse", action="store_true")
    lp.add_argument("--limit", type=int, default=40, help="rows to show (0 = all)")
    lp.add_argument("--format", choices=("table", "paths", "json"), default="table")
    lp.add_argument("--scan", action="store_true", help="incremental scan first")
    lp.add_argument("--recent-minutes", type=float, default=5.0)
    for name, helptext in (("show", "details of one episode"), ("play", "open it in the viewer (extra options pass "
                                                                        "through)"),
                           ("check", "headless MATCH/DESYNC replay")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("target", help="row number of the last list, episode id (or unique suffix), or path")
    sub.add_parser("gui", help="table browser")
    args, extra = ap.parse_known_args(argv)
    if extra and args.cmd not in ("play", "check"):
        ap.error(f"unrecognized arguments: {' '.join(extra)}")
    if args.cmd == "scan":
        return cmd_scan(args)
    if args.cmd == "list":
        return cmd_list(args)
    if args.cmd == "show":
        return cmd_show(args)
    if args.cmd == "play":
        return cmd_play(args, extra)
    if args.cmd == "check":
        return cmd_check(args, extra)
    return cmd_gui(args)


if __name__ == "__main__":
    sys.exit(main())
