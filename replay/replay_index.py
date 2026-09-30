#!/usr/bin/env python3
"""Index and browser for episode artifacts under runs/ (read-only), feeding the replay viewer.

    python replay/replay_index.py scan [--full] [--recent-minutes 5]
    python replay/replay_index.py list [filters] [--sort KEY[,KEY]] [--limit N] [--format table|paths|json]
    python replay/replay_index.py show N|EPISODE_ID|PATH
    python replay/replay_index.py play N|EPISODE_ID|PATH [viewer options...]
    python replay/replay_index.py check N|EPISODE_ID|PATH          (headless MATCH/DESYNC)
    python replay/replay_index.py gui                               (browser)
    replay\\replay_index.cmd ...                                     (Windows wrapper)

N is a row number of the last `list`. The cache is replay/_local/index.sqlite (schema 2; an older cache is dropped
and rebuilt by the next scan). A rescan re-reads only episode directories whose mtime changed, plus run-level
summary files whose mtime/size changed. Episode directories modified in the last few minutes, or without
metadata.json, are skipped: they may still be being written.

Character and stage come from what the run recorded (replay_task.py); "?" when it recorded neither.

Tags are stage-specific milestones (Mario's Break the Targets: "left entry @3001", "crossing"). They are not in
metadata.json: each stage's extractor in replay_tags.py reads the sidecar and summary files its runs write, the
index stores its facts per stage, and only the episode's own stage extractor turns them into tags. An episode
whose stage is not recorded has no tags.

The last target (tick of the last target break; the completion for a clear) comes from recorded per-target break
ticks (replay_breaks.py: evaluation.json, episodes.jsonl, gate traces, decision sidecars, this tool's MATCH
replays), never from replaying during a scan; "?" when unknown. Test / smoke / equivalence episodes (is_test) are
listed unless `list --no-tests`.
"""

from __future__ import annotations

import argparse
import datetime as _dt
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

from replay_episode import REPO_ROOT, TARGETS_TOTAL_DEFAULT, recorded_end, recorded_targets  # noqa: E402
import replay_breaks  # noqa: E402
from replay_tags import EXTRACTORS, Fact, extractor_for, summary_file_names  # noqa: E402
from replay_task import UNKNOWN, character_name, task_identity  # noqa: E402

RUNS_DIR = REPO_ROOT / "runs"
LOCAL_DIR = REPO_ROOT / "replay" / "_local"
INDEX_DB = LOCAL_DIR / "index.sqlite"
LAST_LIST = LOCAL_DIR / "last_list.json"
VERDICTS_FILE = LOCAL_DIR / "verdicts.jsonl"
VIEWER = Path(__file__).resolve().parent / "replay.py"
SCHEMA_VERSION = 3
TICKS_PER_SECOND = 60  # native ticks and the game's time_passed are both 1/60 s

# Directory names that never contain episode artifacts in any runs/ layout (per-process game dirs, runtime
# copies, logs, checkpoints). Pruned for speed; --no-prune walks everything.
PRUNE_NAMES = {"logs", "runtime", "runtime_gens", "episodes", "coordination", "checkpoints", "__pycache__"}
PRUNE_RE = re.compile(r"g\d+_a\d+$")

EPISODE_COLUMNS = (
    "path", "episode_id", "milestone", "run", "phase", "worker", "role", "run_id", "profile", "observation", "reward",
    "character", "stage", "task_source", "end_kind", "end_detail", "truncation", "rows", "steps", "targets",
    "targets_total", "cleared", "completion_tick", "completion_time", "last_tick", "final_x", "final_y",
    "prefix_rows", "created", "sidecars", "dir_mtime_ns", "meta_mtime_ns",
)


# -- database --------------------------------------------------------------------------------------------


def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    db_path = Path(db_path or INDEX_DB)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    row = db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
    if row is None or int(row[0]) != SCHEMA_VERSION:  # older cache: rebuilt by the next scan
        db.executescript("DROP TABLE IF EXISTS episodes; DROP TABLE IF EXISTS summaries; "
                         "DROP TABLE IF EXISTS annotations; DROP TABLE IF EXISTS facts; DROP TABLE IF EXISTS breaks; "
                         "DELETE FROM meta WHERE key = 'last_scan_utc';")
        db.execute("INSERT OR REPLACE INTO meta VALUES ('schema', ?)", (str(SCHEMA_VERSION),))
    cols = ", ".join(f"{c} {'TEXT PRIMARY KEY' if c == 'path' else ''}" for c in EPISODE_COLUMNS)
    db.execute(f"CREATE TABLE IF NOT EXISTS episodes ({cols})")
    db.execute("CREATE TABLE IF NOT EXISTS summaries (path TEXT PRIMARY KEY, mtime_ns INTEGER, size INTEGER)")
    # Stage-specific facts from replay_tags extractors; `data` is the extractor's own JSON.
    # Recorded per-target break ticks (replay_breaks.py), one row per (episode, source).
    db.execute("CREATE TABLE IF NOT EXISTS breaks (episode_id TEXT, source TEXT, source_path TEXT, ticks TEXT, "
               "PRIMARY KEY (episode_id, source))")
    db.execute("CREATE TABLE IF NOT EXISTS facts (episode_id TEXT, stage TEXT, source TEXT, source_path TEXT, "
               "data TEXT, PRIMARY KEY (episode_id, stage, source))")
    # forget() deletes by source path on every re-read episode / summary file: without these, each is a full scan.
    db.execute("CREATE INDEX IF NOT EXISTS facts_source_path ON facts (source_path)")
    db.execute("CREATE INDEX IF NOT EXISTS breaks_source_path ON breaks (source_path)")
    db.commit()
    return db


def last_scan(db_path: Optional[Path] = None) -> Optional[str]:
    db = connect(db_path)
    row = db.execute("SELECT value FROM meta WHERE key='last_scan_utc'").fetchone()
    db.close()
    return row[0] if row else None


# -- metadata -> row ---------------------------------------------------------------------------------------


def rel(path: Path) -> str:
    try:
        return Path(path).relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return Path(path).as_posix()


def split_location(rel_path: str) -> Tuple[str, str, str, Optional[str]]:
    """(milestone, run, phase, worker) from runs/<milestone>/<run...>/[workers/wNN/]artifacts*/<episode>."""
    parts = rel_path.split("/")
    if "runs" in parts:  # runs/... inside the repository, or .../runs/... (a scan root elsewhere)
        parts = parts[parts.index("runs") + 1:]
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
    initial = meta.get("initial_observation") if isinstance(meta.get("initial_observation"), dict) else {}
    kind, detail = recorded_end(meta)
    task = task_identity(meta)
    path = rel(d)
    milestone, run, phase, worker = split_location(path)
    observation = _get(labels, "contracts", "policy_observation_contract") or _get(exp, "policy_observation",
                                                                                    "contract")
    live = final.get("fighter_valid") == 1 and final.get("btt_active") == 1
    return {
        "path": path,
        "episode_id": str(meta.get("episode_id") or d.name),
        "milestone": milestone, "run": run, "phase": phase, "worker": worker,
        "role": labels.get("role"), "run_id": labels.get("run_id"),
        "profile": exp.get("name") or exp.get("environment_profile"),
        "observation": observation,
        "reward": labels.get("reward_contract"),
        "character": task.character, "stage": task.stage, "task_source": task.source,
        "end_kind": kind, "end_detail": detail,
        "truncation": labels.get("truncation_reason", terminal.get("truncation_reason")),
        "rows": _int(meta.get("action_count")),
        "steps": _int(terminal.get("step_count")),
        "targets": recorded_targets(meta),
        "targets_total": _int(_get(labels, "contracts", "targets_total")) or _int(initial.get("targets_remaining"))
        or TARGETS_TOTAL_DEFAULT,
        "cleared": 1 if labels.get("cleared", terminal.get("cleared")) is True else 0,
        "completion_tick": _int(labels.get("completion_input_tick")),
        "completion_time": _int(labels.get("completion_time_passed")),
        "last_tick": _int(terminal.get("last_consumed_tick")),
        "final_x": _float(final.get("position_x")) if live else None,
        "final_y": _float(final.get("position_y")) if live else None,
        "prefix_rows": _int(_get(labels, "m7h_start", "prefix_length")),
        "created": _get(meta, "diagnostics", "created_utc") or "",
        "sidecars": ",".join(sorted(n for n in names if n not in ("actions.jsonl", "metadata.json"))),
        "dir_mtime_ns": dir_mtime, "meta_mtime_ns": meta_mtime,
    }


def store_breaks(db: sqlite3.Connection, breaks: List[replay_breaks.Break]) -> None:
    db.executemany("INSERT OR REPLACE INTO breaks VALUES (?, ?, ?, ?)",
                   [(eid, src, path, json.dumps(ticks, separators=(",", ":"))) for eid, src, path, ticks in breaks])


def forget(db: sqlite3.Connection, source_path: str, like: bool = False) -> None:
    """Drop the facts and break ticks read from one file (or, with like=True, from files under a directory).
    Both lookups use the source_path indexes: '/' + 1 == '0', so [dir/, dir0) is exactly the paths under dir/."""
    for table in ("facts", "breaks"):
        if like:
            db.execute(f"DELETE FROM {table} WHERE source_path >= ? AND source_path < ?",
                       (source_path + "/", source_path + "0"))
        else:
            db.execute(f"DELETE FROM {table} WHERE source_path = ?", (source_path,))


def store_facts(db: sqlite3.Connection, stage: str, facts: List[Fact]) -> None:
    db.executemany("INSERT OR REPLACE INTO facts VALUES (?, ?, ?, ?, ?)",
                   [(f.episode_id, stage, f.source, f.source_path, json.dumps(f.data, separators=(",", ":")))
                    for f in facts])


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
    summary_names = set(summary_file_names()) | set(replay_breaks.SUMMARY_FILES)
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
            elif e.name in summary_names:
                st = e.stat()
                summaries_seen[rel(Path(e.path))] = (st.st_mtime_ns, st.st_size, Path(e.path))
    for p, (mtime, size, full_path) in summaries_seen.items():
        if full or summaries_cached.get(p) != (mtime, size):
            forget(db, p)
            if full_path.name in replay_breaks.SUMMARY_FILES:
                store_breaks(db, replay_breaks.from_summary(full_path, rel))
            for ex in EXTRACTORS.values():
                if full_path.name in ex.summary_files:
                    store_facts(db, ex.stage, ex.from_summary(full_path, rel))
            db.execute("INSERT OR REPLACE INTO summaries VALUES (?, ?, ?)", (p, mtime, size))
            stats["summaries_read"] += 1
    root_rel = rel(root)
    for p in cached:
        if p not in seen and (p == root_rel or p.startswith(root_rel + "/")):
            db.execute("DELETE FROM episodes WHERE path = ?", (p,))
            forget(db, p, like=True)
            stats["removed"] += 1
    for p in summaries_cached:
        if p not in summaries_seen and (p.startswith(root_rel + "/")):
            forget(db, p)
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
    forget(db, p, like=True)  # this episode's own files
    store_breaks(db, replay_breaks.from_episode(d, row["episode_id"], by_name.keys(), rel))
    ex = extractor_for(row["stage"])
    if ex is not None:
        store_facts(db, ex.stage, ex.from_episode(d, meta, by_name.keys(), rel))
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


def end_label(r: Dict[str, Any]) -> str:
    """clear | fall | timeout (step limit / tick quota) | goal (M7s goal reached) | aborted | unknown."""
    kind = r.get("end_kind")
    if kind in ("clear", "fall"):
        return kind
    if kind == "truncated":
        detail = r.get("end_detail") or ""
        if "goal_reached" in detail:
            return "goal"
        if "aborted" in detail or "lifecycle_failure" in detail:
            return "aborted"
        return "timeout"
    return "unknown"


def time_seconds(r: Dict[str, Any]) -> Optional[float]:
    """Completion time for a clear (the game's time_passed), else the end tick, in seconds."""
    if r.get("end_kind") == "clear" and r.get("completion_time") is not None:
        return r["completion_time"] / TICKS_PER_SECOND
    if r.get("last_tick") is not None:
        return r["last_tick"] / TICKS_PER_SECOND
    return None


def time_text(r: Dict[str, Any]) -> str:
    """'7.43 s' for a clear; '2975 · 49.6 s' (end tick · seconds) otherwise."""
    if r.get("end_kind") == "clear" and r.get("completion_time") is not None:
        return f"{r['completion_time'] / TICKS_PER_SECOND:.2f} s"
    if r.get("last_tick") is not None:
        return f"{r['last_tick']} · {r['last_tick'] / TICKS_PER_SECOND:.1f} s"
    return "–"


def created_local(created_utc: str) -> Optional[_dt.datetime]:
    try:
        dt = _dt.datetime.fromisoformat(created_utc.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt.astimezone()


def created_text(created_utc: str) -> str:
    """Local time, short: 'Sep 27 03:22'."""
    dt = created_local(created_utc)
    return f"{dt:%b} {dt.day} {dt:%H:%M}" if dt else ""


TEST_ROLES = ("test", "m6_equivalence")


def is_test(r: Dict[str, Any]) -> bool:
    """Test / smoke / equivalence episodes, hidden by default in the browser: roles test and m6_equivalence, no
    role recorded (all in regression and test folders), and every `_`-prefixed milestone folder (the repository's
    smoke / regression / preflight / debug runs, whose roles are ordinary training / evaluation)."""
    return r["role"] in TEST_ROLES or r["role"] is None or r["milestone"].startswith("_")


def set_last_target(r: Dict[str, Any], sources: Dict[str, List[int]]) -> None:
    r["last_target_tick"], r["last_target_text"], r["last_target_source"] = replay_breaks.last_target(r, sources)


def load_rows(db_path: Optional[Path] = None, verdicts_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Every indexed episode with its tags (from its own stage's facts), replay verdict and display fields."""
    db = connect(db_path)
    rows = [dict(r) for r in db.execute("SELECT * FROM episodes")]
    facts: Dict[Tuple[str, str], Dict[str, Fact]] = {}
    for f in db.execute("SELECT * FROM facts"):
        try:
            data = json.loads(f["data"])
        except (TypeError, ValueError):
            continue
        facts.setdefault((f["episode_id"], f["stage"]), {})[f["source"]] = Fact(f["episode_id"], f["source"],
                                                                                f["source_path"], data)
    breaks: Dict[str, Dict[str, List[int]]] = {}
    for b in db.execute("SELECT * FROM breaks"):
        try:
            breaks.setdefault(b["episode_id"], {})[b["source"]] = json.loads(b["ticks"])
        except (TypeError, ValueError):
            continue
    db.close()
    verdicts = load_verdicts(verdicts_path)
    for r in rows:
        v = verdicts.get(r["path"])
        r["replay"] = v.get("verdict") if v else None
        r["replay_mode"] = v.get("mode") if v else None
        r["character_name"] = character_name(r["character"])
        r["end_label"] = end_label(r)
        r["time_s"] = time_seconds(r)
        r["time_text"] = time_text(r)
        r["is_test"] = is_test(r)
        mine_breaks = dict(breaks.get(r["episode_id"], {}))
        replay_break = replay_breaks.from_replay(v, r["episode_id"]) if v else None
        if replay_break is not None:
            mine_breaks["replay"] = replay_break[3]
        set_last_target(r, mine_breaks)
        r["created_text"] = created_text(r["created"])
        r["tags"], r["tag_details"], r["tag_sources"] = [], [], []
        ex = extractor_for(r["stage"])
        if ex is not None:
            mine = dict(facts.get((r["episode_id"], ex.stage), {}))
            fact = ex.from_replay(v, r["episode_id"]) if v else None
            if fact is not None:
                mine[fact.source] = fact
            r["tags"], r["tag_details"] = ex.resolve(mine)
            r["tag_sources"] = sorted(mine)
        r["tag_text"] = " · ".join(r["tags"])
    return rows


def _num(v: Optional[float], missing: float) -> float:
    return v if v is not None else missing


SORT_KEYS = {
    "targets": lambda r: _num(r["targets"], -1),
    "last": lambda r: _num(r["last_target_tick"], 10 ** 9),  # last target broken (the clear for a clear)
    "character": lambda r: (r["character"] is None, r["character_name"]),
    "stage": lambda r: (r["stage"] is None, r["stage"] or ""),
    "end": lambda r: {"clear": 0, "goal": 1, "fall": 2, "timeout": 3, "aborted": 4}.get(r["end_label"], 5),
    "verdict": lambda r: {"MATCH": 0, "DESYNC": 1}.get(r["replay"], 2),
    "role": lambda r: r["role"] or "~",
    "milestone": lambda r: r["milestone"],
    "run": lambda r: r["run"],
    "tags": lambda r: (-len(r["tags"]), r["tag_text"]),
    "created": lambda r: r["created"] or "",
    "completion": lambda r: _num(r["completion_tick"], 10 ** 9),
    "last_tick": lambda r: _num(r["last_tick"], -1),
    "steps": lambda r: _num(r["steps"], -1),
    "path": lambda r: r["path"],
}
DESCENDING_BY_DEFAULT = {"targets", "created", "last_tick", "steps"}
DEFAULT_SORT = "targets,last"  # most targets first, then the earliest last-target break


def matches_text(r: Dict[str, Any], text: str) -> bool:
    """Case-insensitive substring of path, run id, profile or tags."""
    return text.lower() in " ".join((r["path"], r["run_id"] or "", r["profile"] or "", r["tag_text"])).lower()


def filter_rows(rows: List[Dict[str, Any]], args: argparse.Namespace) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        if args.milestone and not any(r["milestone"] == m or r["milestone"].startswith(m) for m in args.milestone):
            continue
        if args.run and args.run.lower() not in (r["run"] or "").lower():
            continue
        if args.role and r["role"] != args.role:
            continue
        if args.character and (r["character"] or UNKNOWN) not in args.character:
            continue
        if args.stage and (r["stage"] or UNKNOWN) not in args.stage:
            continue
        if args.end and r["end_kind"] not in args.end and r["end_label"] not in args.end:
            continue
        if args.min_targets is not None and (r["targets"] is None or r["targets"] < args.min_targets):
            continue
        if args.max_targets is not None and (r["targets"] is None or r["targets"] > args.max_targets):
            continue
        if args.cleared and not r["cleared"]:
            continue
        if args.tag and not any(args.tag.lower() in t.lower() for t in r["tags"]):
            continue
        if args.replay and (r["replay"] or "none").lower() not in args.replay:
            continue
        if getattr(args, "no_tests", False) and r["is_test"]:
            continue
        if args.text and not matches_text(r, args.text):
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


def print_table(rows: List[Dict[str, Any]]) -> None:
    head = (f"{'#':>4}  {'tgt':>5}  {'character':<10} {'end':<8} {'last target':>15}  {'rep':<3} {'role':<5} {'where':<46} "
            f"{'tags':<28} episode")
    print(head)
    print("-" * len(head))
    marks = {"MATCH": "ok", "DESYNC": "X"}
    for i, r in enumerate(rows, 1):
        where = f"{r['milestone']}/{r['run']}" + (f" {r['worker']}" if r["worker"] else "")
        if len(where) > 46:
            where = "..." + where[-43:]
        tgt = f"{r['targets'] if r['targets'] is not None else '-'}/{r['targets_total']}"
        print(f"{i:>4}  {tgt:>5}  {r['character_name'][:10]:<10} {r['end_label']:<8} {r['last_target_text']:>15}  "
              f"{marks.get(r['replay'], '.'):<3} {(r['role'] or '')[:5]:<5} {where:<46} {r['tag_text'][:28]:<28} "
              f"{r['episode_id']}")


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
    ap.add_argument("--character", action="append", help="e.g. mario, or ? for not recorded (repeatable)")
    ap.add_argument("--stage", action="append", help="e.g. btt_mario, or ? for not recorded (repeatable)")
    ap.add_argument("--end", action="append",
                    choices=("clear", "fall", "truncated", "timeout", "goal", "aborted", "unknown"))
    ap.add_argument("--min-targets", type=int)
    ap.add_argument("--max-targets", type=int)
    ap.add_argument("--cleared", action="store_true")
    ap.add_argument("--tag", help="substring of a tag, e.g. 'left entry' or crossing")
    ap.add_argument("--replay", action="append", choices=("match", "desync", "none"))
    ap.add_argument("--text", help="substring of path / run_id / profile / tags")
    ap.add_argument("--no-tests", action="store_true",
                    help="hide test / smoke / equivalence episodes (roles test, m6_equivalence, none; _ folders)")


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
              "reward", "character", "stage", "task_source", "end_kind", "end_detail", "rows", "steps", "targets",
              "targets_total", "cleared", "completion_tick", "completion_time", "last_tick", "prefix_rows", "created",
              "sidecars"):
        print(f"  {k:<16} {r[k]}")
    print(f"  {'last target':<16} {r['last_target_text']} ({r['last_target_source']})")
    print(f"  {'end tick':<16} {r['time_text']}")
    print(f"  {'test episode':<16} {'yes' if r['is_test'] else 'no'}")
    print(f"  {'tags':<16} {r['tag_text'] or '-'}")
    for k, v in r["tag_details"]:
        print(f"    {k:<14} {v}")
    print(f"  {'replay':<16} {r['replay'] or '-'} {('(' + r['replay_mode'] + ')') if r['replay_mode'] else ''}")
    print(f"  {'tag sources':<16} {', '.join(r['tag_sources']) or '-'}")
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
    lp.add_argument("--sort", default=DEFAULT_SORT,
                    help=f"comma-separated keys, prefix - or + to force order: {', '.join(SORT_KEYS)} "
                         f"(default {DEFAULT_SORT}: most targets, then earliest last target)")
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
