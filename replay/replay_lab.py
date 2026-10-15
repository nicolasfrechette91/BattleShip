#!/usr/bin/env python3
"""The fast-route lab (C:\\BattleShip_lab, unregistered) as an extra, read-only source of the replay browser.

The lab runner (tools/frs/*.py) works outside the checkout. Per run it writes <lab root>/<run>/run/, with

    verifications.jsonl   one row per clear candidate it replayed: the whole tick-0 word sequence (`words_hex`,
                          one Track 1 word per native tick, rl/m8_rd_cells.TRIPLES), `words_digest` (the M7
                          native_action_digest of those words), the verdict (VERIFIED = two exact fresh-process
                          replays from tick 0 whose record chains are equal), both completion clocks, each
                          replay's per-target break ticks, and where the candidate was found (dispatch n, cell
                          cid, iteration k)
    traces/clear_n<n>_c<cid>_k<k>_r1.json.gz   every reply of the first verifying replay (the shape of an M8
                          route's trace.json.gz: `initial` and `steps[]` with observations)

None of this is a registered run artifact under runs/, so every entry is labelled LAB (unregistered).

Adapter. A verified clear is addressed by its r1 trace file, the one per-clear file the lab writes, so nothing is
created anywhere. Loading it finds the clear's verification row, decodes the words with the lab's own alphabet,
refuses the clear unless the decoded digest equals the recorded `words_digest` (the viewer then plays exactly the
verified words), and describes it in the shape of an M8 route (replay_episode.ROUTE_SCHEMAS, schema
frs_lab_clear_v1, viewer-side only): the expected outcome is the recorded verification, the tick-0 and final
observations come from the trace, and the game runs with the lab's frozen config
(<lab root>/import/exe/BattleShip.cfg.json). The lab root is only read: no file, link or junction is created
under it or under runs/.

Root: `replay_index.py --lab-root PATH` / `--no-lab`; else the BATTLESHIP_LAB_ROOT environment variable (empty =
off); else C:\\BattleShip_lab when it exists. Lock: while <lab root>/lab.lock exists a lab run is active, and no
game replay is started (replay_game.GameProcess.launch, replay.py, the browser's Play / Check).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from replay_episode import (LAB_SCHEMA, NATIVE_ACTION_CONTRACT, TARGETS_TOTAL_DEFAULT, Episode, EpisodeError, Row,
                            action_digest)
from m8_rd_cells import TRACK1_CONTRACT, TRIPLES  # noqa: E402  rl/ (on sys.path through replay_episode), stdlib only

LAB_LABEL = "LAB (unregistered)"
LAB_ROLE = "lab"
DEFAULT_ROOT = Path("C:/BattleShip_lab")
ROOT_ENV = "BATTLESHIP_LAB_ROOT"
LOCK_NAME = "lab.lock"
VERIFICATIONS = "verifications.jsonl"
TRACES_DIR = "traces"
TRACE_RE = re.compile(r"^clear_n(?P<n>\d+)_c(?P<cid>\d+)_k(?P<k>\d+)_r(?P<r>\d+)\.json\.gz$")
IMPORT_CONFIG = ("import", "exe", "BattleShip.cfg.json")  # the lab's frozen runtime config (import/frozen_runtime.json)
# verification-row fields kept in the episode metadata (`lab`), for the viewer and `show`
ROW_FIELDS = ("n", "cid", "k", "level", "start_tick", "lead", "verdict", "chain_r1", "chain_r2", "clocks_r1", "clocks_r2",
              "gain_vs_reference", "reference_completion_input_tick", "wall_s", "utc", "phase")


# -- root and lock -------------------------------------------------------------------------------------------------


def lab_root(override: Optional[os.PathLike | str] = None) -> Optional[Path]:
    """The lab root to read, resolved, or None (off): `override`, else BATTLESHIP_LAB_ROOT (empty = off), else
    C:\\BattleShip_lab when it exists. A root that is not a directory is None."""
    if override is not None:
        p = Path(override).expanduser()
    else:
        env = os.environ.get(ROOT_ENV)
        if env is not None:
            if not env.strip():
                return None
            p = Path(env.strip()).expanduser()
        else:
            p = DEFAULT_ROOT
    return p.resolve() if p.is_dir() else None


def lab_lock(root: Optional[Path] = None) -> Optional[Path]:
    """<root>/lab.lock when it exists (a lab run is active), else None. root None = lab_root()."""
    root = lab_root() if root is None else Path(root)
    if root is None:
        return None
    lock = root / LOCK_NAME
    return lock if lock.exists() else None


def refusal(lock: Path) -> str:
    return f"a lab run is active ({lock} exists): no game replay is started while it runs"


# -- runs and verified clears --------------------------------------------------------------------------------------


def lab_runs(root: Path) -> List[Path]:
    """Run folders under the lab root, by name: <root>/<run>/run/ (or <root>/<run>/) holding verifications.jsonl."""
    try:
        children = sorted(p for p in Path(root).iterdir() if p.is_dir())
    except OSError:
        return []
    out: List[Path] = []
    for p in children:
        for d in (p / "run", p):
            if (d / VERIFICATIONS).is_file():
                out.append(d)
                break
    return out


def run_name(run_dir: Path) -> str:
    d = Path(run_dir)
    return d.parent.name if d.name == "run" else d.name


def trace_path(run_dir: Path, n: int, cid: int, k: int, r: int = 1) -> Path:
    return Path(run_dir) / TRACES_DIR / f"clear_n{n}_c{cid}_k{k}_r{r}.json.gz"


def is_lab_trace(path: os.PathLike | str) -> bool:
    """A lab clear's trace file: traces/clear_n<n>_c<cid>_k<k>_r<r>.json.gz beside the run's verifications.jsonl."""
    p = Path(path)
    return (bool(TRACE_RE.match(p.name)) and p.parent.name == TRACES_DIR
            and (p.parent.parent / VERIFICATIONS).is_file() and p.is_file())


def _int(v: Any) -> Optional[int]:
    return int(v) if isinstance(v, int) and not isinstance(v, bool) else None


def _is_verified_clear(v: Any) -> bool:
    return isinstance(v, dict) and v.get("kind") == "clear" and v.get("verdict") == "VERIFIED"


def _is_addressable(v: Mapping[str, Any]) -> bool:
    """The crossing-search record shape: the clear carries its words and the (dispatch n, cell cid, iteration k)
    identity that names its trace file. Older lab runs (smoke, trail probe) name their traces otherwise."""
    return (isinstance(v.get("words_hex"), str)
            and all(_int(v.get(key)) is not None for key in ("n", "cid", "k", "completion_input_tick")))


def read_clears(run_dir: Path) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """The run's verified clears, fastest first (completion_input_tick, then dispatch n), one per distinct word
    sequence (`finds` = how many verified rows carried the same words), with counts of what was skipped: rows
    that are not verified clears (`other`), verified clears in another record shape (`unaddressable`, see
    _is_addressable) and unparsable lines (a line still being written)."""
    path = Path(run_dir) / VERIFICATIONS
    by_digest: Dict[str, Dict[str, Any]] = {}
    stats = {"rows": 0, "verified": 0, "other": 0, "unaddressable": 0, "unparsable": 0, "unreadable": 0}
    try:
        with open(path, encoding="utf-8") as fp:
            for lineno, line in enumerate(fp, 1):
                if not line.strip():
                    continue
                stats["rows"] += 1
                try:
                    v = json.loads(line)
                except ValueError:
                    stats["unparsable"] += 1
                    continue
                if not _is_verified_clear(v):
                    stats["other"] += 1
                    continue
                if not _is_addressable(v):
                    stats["unaddressable"] += 1
                    continue
                stats["verified"] += 1
                digest = v["words_digest"] if isinstance(v.get("words_digest"), str) else v["words_hex"]
                if digest in by_digest:
                    by_digest[digest]["finds"] += 1
                    continue
                n, cid, k = (int(v[key]) for key in ("n", "cid", "k"))
                breaks = v.get("breaks_r1") if isinstance(v.get("breaks_r1"), list) else None
                by_digest[digest] = {
                    "run_dir": Path(run_dir), "run": run_name(run_dir), "verifications": path, "line": lineno,
                    "trace": trace_path(run_dir, n, cid, k), "n": n, "cid": cid, "k": k,
                    "words": _int(v.get("words")) if _int(v.get("words")) is not None else len(v["words_hex"]) // 2,
                    "words_digest": digest, "completion_input_tick": int(v["completion_input_tick"]),
                    "completion_time_passed": _int(v.get("completion_time_passed")),
                    "targets": len(breaks) if breaks else TARGETS_TOTAL_DEFAULT,
                    "level": _int(v.get("level")), "start_tick": _int(v.get("start_tick")), "lead": _int(v.get("lead")),
                    "gain": _int(v.get("gain_vs_reference")), "reference": _int(v.get("reference_completion_input_tick")),
                    "chains_equal": (v.get("chain_r1") == v.get("chain_r2")) if v.get("chain_r1") else None,
                    "utc": v["utc"] if isinstance(v.get("utc"), str) else "", "finds": 1,
                }
    except OSError:
        stats["unreadable"] = 1
    clears = sorted(by_digest.values(), key=lambda c: (c["completion_input_tick"], c["n"]))
    return clears, stats


# -- one clear as an episode ---------------------------------------------------------------------------------------


def decode_words(words_hex: str) -> Tuple[bytes, List[Row]]:
    """Track 1 words (one byte each) -> native rows, row i consuming tick i: rl/m8_rd_cells.TRIPLES, the table the
    lab stepped the game with."""
    try:
        words = bytes.fromhex(words_hex)
    except ValueError as exc:
        raise EpisodeError(f"words_hex is not hexadecimal: {exc}") from exc
    bad = next((w for w in words if w >= len(TRIPLES)), None)
    if bad is not None:
        raise EpisodeError(f"word {bad} is outside the {len(TRIPLES)}-word Track 1 alphabet ({TRACK1_CONTRACT})")
    return words, [Row(i, *TRIPLES[w], i) for i, w in enumerate(words)]


def _find_row(path: Path, n: int, cid: int, k: int) -> Tuple[Dict[str, Any], int]:
    try:
        with open(path, encoding="utf-8") as fp:
            for lineno, line in enumerate(fp, 1):
                if not line.strip():
                    continue
                try:
                    v = json.loads(line)
                except ValueError:
                    continue
                if isinstance(v, dict) and v.get("kind") == "clear" and \
                        (_int(v.get("n")), _int(v.get("cid")), _int(v.get("k"))) == (n, cid, k):
                    return v, lineno
    except OSError as exc:
        raise EpisodeError(f"{path}: {exc}") from exc
    raise EpisodeError(f"{path} has no clear row for dispatch {n}, cell {cid}, k {k}")


def import_config(run_dir: Path) -> Optional[Path]:
    """The lab's frozen runtime config, <lab root>/import/exe/BattleShip.cfg.json, found from the run folder."""
    d = Path(run_dir)
    for ancestor in (d.parent, d.parent.parent):
        p = ancestor.joinpath(*IMPORT_CONFIG)
        if p.is_file():
            return p
    return None


def load_clear(trace: os.PathLike | str) -> Episode:
    """The verified clear addressed by its trace file, as a route-like episode whose rows are exactly the verified
    words: the decoded native_action_digest must equal the recorded words_digest. Raises EpisodeError otherwise."""
    trace = Path(trace).resolve()
    m = TRACE_RE.match(trace.name)
    if not m or trace.parent.name != TRACES_DIR:
        raise EpisodeError(f"not a lab clear trace ({TRACES_DIR}/clear_n<n>_c<cid>_k<k>_r1.json.gz): {trace}")
    run_dir = trace.parent.parent
    n, cid, k = (int(m.group(g)) for g in ("n", "cid", "k"))
    row, lineno = _find_row(run_dir / VERIFICATIONS, n, cid, k)
    if row.get("verdict") != "VERIFIED":
        raise EpisodeError(f"clear n{n} c{cid} k{k} is {row.get('verdict')!r}, not VERIFIED: only verified lab clears "
                           "are replayed")
    if not isinstance(row.get("words_hex"), str):
        raise EpisodeError(f"clear n{n} c{cid} k{k} has no words_hex")
    words, rows = decode_words(row["words_hex"])
    if _int(row.get("words")) not in (None, len(words)):
        raise EpisodeError(f"words {row.get('words')!r} != {len(words)} decoded words")
    digest = action_digest(rows)
    recorded = row.get("words_digest")
    if isinstance(recorded, str) and recorded != digest:
        raise EpisodeError(f"decoded words digest {digest[:16]} != recorded words_digest {recorded[:16]}: "
                           "not the verified words")
    completion_tick = _int(row.get("completion_input_tick"))
    if completion_tick is None or completion_tick < 1:
        raise EpisodeError(f"clear n{n} c{cid} k{k}: completion_input_tick {row.get('completion_input_tick')!r}")
    breaks = row.get("breaks_r1") if isinstance(row.get("breaks_r1"), list) else []
    name = run_name(run_dir)
    config = import_config(run_dir)
    metadata: Dict[str, Any] = {
        "schema": LAB_SCHEMA, "episode_id": f"lab_{name}_n{n}_c{cid}_k{k}", "session": name, "arm": LAB_ROLE,
        "claim": "clear", "native_action_digest": digest, "words": len(words), "action_contract": NATIVE_ACTION_CONTRACT,
        "track1_contract": TRACK1_CONTRACT, "track1_words_hex": row["words_hex"],
        "runtime_config": str(config) if config is not None else None,
        "lab": {"label": LAB_LABEL, "run": name, "verifications": str(run_dir / VERIFICATIONS), "line": lineno,
                "trace": str(trace), **{key: row.get(key) for key in ROW_FIELDS}},
        # the verifying replay: the clear registers on the completion input tick (the last consumed tick + 1)
        "replay": {"exact": True, "t": len(breaks) or TARGETS_TOTAL_DEFAULT, "clear": True,
                   "label": f"{LAB_LABEL} clear n{n} c{cid} k{k}", "breaks": breaks,
                   "terminal": {"kind": "clear", "submitted": completion_tick, "last_consumed_tick": completion_tick - 1}},
        "completion_clocks": {"completion_input_tick": completion_tick,
                              "completion_time_passed": _int(row.get("completion_time_passed"))},
    }
    return Episode(trace, metadata, rows)


# -- browser rows --------------------------------------------------------------------------------------------------


def _row(c: Mapping[str, Any], path: str, verdict: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """One browser row (the index's episode columns plus its display fields) for a verified clear."""
    from replay_index import created_text, end_label, set_last_target, time_seconds, time_text  # it imports us
    from replay_task import character_name

    n, cid, k = c["n"], c["cid"], c["k"]
    tick = c["completion_input_tick"]
    r: Dict[str, Any] = {
        "path": path, "episode_id": f"lab_{c['run']}_n{n}_c{cid}_k{k}", "milestone": LAB_LABEL, "run": c["run"],
        "phase": c["run"], "worker": None, "role": LAB_ROLE, "run_id": c["run"],
        "profile": f"{LAB_LABEL} · clear n{n} c{cid} k{k}", "observation": None, "reward": None,
        "character": None, "stage": None, "task_source": "not recorded",
        "end_kind": "clear", "end_detail": "lab verification VERIFIED: two exact fresh-process replays from tick 0",
        "truncation": None, "rows": c["words"], "steps": tick, "targets": c["targets"],
        "targets_total": TARGETS_TOTAL_DEFAULT, "cleared": 1, "completion_tick": tick,
        "completion_time": c["completion_time_passed"], "last_tick": tick - 1, "final_x": None, "final_y": None,
        "prefix_rows": None, "created": c["utc"], "sidecars": "", "dir_mtime_ns": 0, "meta_mtime_ns": 0,
        "format": LAB_SCHEMA, "created_source": "lab verification", "lab": True,
    }
    r["replay"] = verdict.get("verdict") if verdict else None
    r["replay_mode"] = verdict.get("mode") if verdict else None
    r["character_name"] = character_name(None)
    r["end_label"] = end_label(r)
    r["time_s"] = time_seconds(r)
    r["time_text"] = time_text(r)
    r["is_test"] = False
    set_last_target(r, {})
    r["created_text"] = created_text(r["created"])
    r["tags"], r["tag_sources"], r["tag_text"] = [], [], ""
    chains = {True: "equal", False: "DIFFER", None: "not recorded"}[c["chains_equal"]]
    found = f"dispatch {n}, cell {cid}, k {k}" + (f"; the same words were verified {c['finds']} times" if c["finds"] > 1 else "")
    details = [
        ("lab", f"{LAB_LABEL}: an exploratory lab run, not a registered run artifact"),
        ("verified", f"two exact fresh-process replays from tick 0 (record chains {chains})"),
        ("found", found),
        ("level / start tick", f"{c['level']} / {c['start_tick']}" + (f" (lead {c['lead']})" if c["lead"] is not None else "")),
    ]
    if c["gain"] is not None and c["reference"] is not None:
        details.append(("gain", f"{c['gain']} input ticks faster than the reference ({c['reference']})"))
    details += [("words digest", c["words_digest"][:16] + "…"), ("verifications", str(c["verifications"]))]
    r["tag_details"] = details
    return r


def scan_lab(root: Optional[Path] = None, verdicts: Optional[Mapping[str, Mapping[str, Any]]] = None) -> Dict[str, Any]:
    """Browser rows for every verified lab clear with an r1 trace, fastest first, plus counts and a status line.
    root None = lab_root(); `verdicts` is replay_index.load_verdicts() (this tool's own replays of lab clears are
    keyed by the trace path)."""
    root = lab_root() if root is None else Path(root)
    out: Dict[str, Any] = {"root": root, "rows": [], "runs": 0, "verified": 0, "distinct": 0, "listed": 0,
                           "no_trace": 0, "unaddressable": 0, "unparsable": 0, "text": ""}
    if root is None:
        return out
    verdicts = verdicts or {}
    for run_dir in lab_runs(root):
        clears, stats = read_clears(run_dir)
        out["runs"] += 1
        out["verified"] += stats["verified"]
        out["distinct"] += len(clears)
        out["unaddressable"] += stats["unaddressable"]
        out["unparsable"] += stats["unparsable"]
        for c in clears:
            if not c["trace"].is_file():
                out["no_trace"] += 1
                continue
            path = c["trace"].as_posix()
            out["rows"].append(_row(c, path, verdicts.get(str(c["trace"])) or verdicts.get(path)))
    out["listed"] = len(out["rows"])
    parts = [f"{LAB_LABEL}: {out['listed']:,} verified clears in {out['runs']} lab runs under {root}"]
    if out["verified"] != out["distinct"]:
        parts.append(f"{out['verified'] - out['distinct']} repeat finds of the same words merged")
    if out["no_trace"]:
        parts.append(f"{out['no_trace']} without an r1 trace, not listed")
    if out["unaddressable"]:
        parts.append(f"{out['unaddressable']} verified clears in another record shape (no dispatch / cell / k "
                     "identity), not listed")
    if out["unparsable"]:
        parts.append(f"{out['unparsable']} unparsable lines (still being written?)")
    out["text"] = "; ".join(parts)
    return out


def rows(root: Optional[Path] = None, verdicts: Optional[Mapping[str, Mapping[str, Any]]] = None) -> List[Dict[str, Any]]:
    return scan_lab(root, verdicts)["rows"]
