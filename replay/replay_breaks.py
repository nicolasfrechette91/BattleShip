#!/usr/bin/env python3
"""When each target broke: the recorded per-target break ticks, and the "last target" shown by the browser.

Break ticks are native consumed ticks (the tick whose update broke the target), one entry per target. They are
not in metadata.json; the index collects them from files the runs already wrote, read-only, never by replaying:

    evaluation      evaluation.json    episodes[].target_break_ticks (else eval_metrics.target_breaks)
    episodes_log    episodes.jsonl     target_break_ticks of every episode a trainer / evaluator logged
    gate_trace      gate_trace.json.gz per-tick "targets" (remaining) column (M7r evaluations)
    decisions       decisions.json.gz  per-tick signature field "targets" (M7r commit sidecars)
    replay          replay/_local/verdicts.jsonl, this tool's MATCH replays (added at load time)

Last target of an episode, first rule that applies:

    0 targets                   "–"   nothing broke
    clear                       completion: consumed tick labels.completion_input_tick - 1 (the row's
                                completion_tick - 1), seconds from the game's time_passed (the clear IS the last
                                break)
    a source whose tick count equals the recorded targets (sources tried in the order replay, evaluation,
                                episodes_log, gate_trace, decisions): its last tick
    an M7h/M7m curriculum episode whose source lists only the policy phase (all ticks at or after the prefix,
                                fewer than the targets): its last tick; the missing breaks are the prefix's
    otherwise                   "?"   unknown (e.g. every break inside a curriculum prefix, or no source)
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

TICKS_PER_SECOND = 60
SUMMARY_FILES = ("evaluation.json", "episodes.jsonl")
EPISODE_FILES = ("gate_trace.json.gz", "decisions.json.gz")
PRIORITY = ("replay", "evaluation", "episodes_log", "gate_trace", "decisions")

Break = Tuple[str, str, str, List[int]]  # (episode_id, source, source_path, ticks)


def _ticks(v: Any) -> Optional[List[int]]:
    if isinstance(v, list) and all(isinstance(t, int) and not isinstance(t, bool) for t in v):
        return list(v)
    return None


def from_summary(path: Path, rel: Callable[[Path], str]) -> List[Break]:
    out: List[Break] = []
    src = rel(path)
    try:
        if path.name == "episodes.jsonl":
            with open(path, encoding="utf-8") as fp:
                for line in fp:
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    ticks = _ticks(e.get("target_break_ticks")) if isinstance(e, dict) else None
                    if ticks is not None and e.get("episode_id"):
                        out.append((e["episode_id"], "episodes_log", src, ticks))
        elif path.name == "evaluation.json":
            with open(path, encoding="utf-8") as fp:
                doc = json.load(fp)
            for e in (doc.get("episodes") or []) if isinstance(doc, dict) else []:
                if not isinstance(e, dict) or not e.get("episode_id"):
                    continue
                ticks = _ticks(e.get("target_break_ticks"))
                m = e.get("eval_metrics")
                if ticks is None and isinstance(m, dict) and isinstance(m.get("target_breaks"), list):
                    ticks = _ticks([b.get("consumed_tick") for b in m["target_breaks"] if isinstance(b, dict)])
                if ticks is not None:
                    out.append((e["episode_id"], "evaluation", src, sorted(ticks)))
    except (OSError, ValueError):
        return []
    return out


def _drops(values: Iterable[Tuple[int, int]]) -> List[int]:
    """Ticks where a remaining-targets count went down, repeated per target."""
    out, prev = [], None
    for tick, remaining in values:
        if prev is not None and remaining < prev:
            out += [tick] * (prev - remaining)
        prev = remaining
    return out


def from_episode(d: Path, episode_id: str, names: Iterable[str], rel: Callable[[Path], str]) -> List[Break]:
    names = set(names)
    out: List[Break] = []
    if "gate_trace.json.gz" in names:
        try:
            with gzip.open(d / "gate_trace.json.gz", "rt", encoding="utf-8") as fp:
                doc = json.load(fp)
            f = doc["fields"]
            k, t = f.index("targets"), f.index("t")
            out.append((episode_id, "gate_trace", rel(d / "gate_trace.json.gz"),
                        _drops((row[t], row[k]) for row in doc["rows"] if row[k] is not None)))
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            pass
    if "decisions.json.gz" in names:
        try:
            with gzip.open(d / "decisions.json.gz", "rt", encoding="utf-8") as fp:
                doc = json.load(fp)
            k = doc["signature_fields"].index("targets")
            # row 0 = the tick-0 observe reply; row t + 1 = the reply after consumed tick t
            out.append((episode_id, "decisions", rel(d / "decisions.json.gz"),
                        _drops((i - 1, s[k]) for i, s in enumerate(doc["signatures"]))))
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            pass
    return out


def from_replay(verdict: Mapping[str, Any], episode_id: str) -> Optional[Break]:
    t = verdict.get("trajectory")
    if verdict.get("verdict") != "MATCH" or not isinstance(t, dict):
        return None
    ticks = _ticks(t.get("target_break_ticks"))
    return (episode_id, "replay", "replay/_local/verdicts.jsonl", ticks) if ticks is not None else None


def last_target(r: Mapping[str, Any], sources: Mapping[str, List[int]]) -> Tuple[Optional[int], str, str]:
    """(consumed tick of the last break or None, text, source). Text: '3008 · 50.1 s', '446 · 7.43 s' for a
    clear, '–' when no target broke, '?' when unknown."""
    targets = r.get("targets")
    if targets == 0:
        return None, "–", "no target broken"
    if r.get("end_kind") == "clear" and r.get("completion_tick") is not None:
        tick = r["completion_tick"] - 1  # completion_input_tick - 1 = the consumed tick of the final break
        secs = (r["completion_time"] if r.get("completion_time") is not None else tick) / TICKS_PER_SECOND
        return tick, f"{tick} · {secs:.2f} s", "completion"
    if targets is None:
        return None, "?", "targets not recorded"
    prefix = r.get("prefix_rows") or 0
    for s in PRIORITY:
        ticks = sources.get(s)
        if not ticks:
            continue
        if len(ticks) == targets or (prefix and len(ticks) < targets and min(ticks) >= prefix):
            tick = max(ticks)
            return tick, f"{tick} · {tick / TICKS_PER_SECOND:.1f} s", s
    return None, "?", "not recorded"
