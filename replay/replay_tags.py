#!/usr/bin/env python3
"""Stage-specific tags (milestones such as "left entry @3001", "crossing") from files the runs already wrote.

One extractor per stage, registered in EXTRACTORS. The index (replay_index.py) never interprets these files itself:

    at scan time   extractor.from_episode(dir, metadata, file names)   for every episode of the extractor's stage
                   extractor.from_summary(path)                        for every run-level file named in
                                                                       extractor.summary_files, wherever it is
    at load time   extractor.from_replay(verdict)                       this tool's own replays (verdicts.jsonl)
                   extractor.resolve(facts) -> (tags, details)          tags for the table, details for the card

A fact is (source, source_path, data): `data` is whatever the extractor needs (stored as JSON), so the index needs
no stage-specific columns. Facts are kept per stage and only the episode's own stage extractor ever sees them; an
episode whose character / stage is not recorded (replay_task.py) gets no tags. Adding a stage means one StageTags
subclass here and one EXTRACTORS entry; the index and the browser do not change.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from replay_episode import LEFT_BOUNDARY_X


@dataclass
class Fact:
    episode_id: str
    source: str
    source_path: str
    data: Dict[str, Any] = field(default_factory=dict)


Details = List[Tuple[str, str]]  # (key, value) lines for the browser's details card


class StageTags:
    """Base extractor: no files, no tags."""

    stage = ""
    summary_files: Tuple[str, ...] = ()  # run-level file names from_summary understands

    def from_episode(self, d: Path, meta: Mapping[str, Any], names: Iterable[str], rel: Callable[[Path], str]
                     ) -> List[Fact]:
        return []

    def from_summary(self, path: Path, rel: Callable[[Path], str]) -> List[Fact]:
        return []

    def from_replay(self, verdict: Mapping[str, Any], episode_id: str) -> Optional[Fact]:
        return None

    def resolve(self, facts: Mapping[str, Fact]) -> Tuple[List[str], Details]:
        return [], []


def _int(v: Any) -> Optional[int]:
    return int(v) if isinstance(v, int) and not isinstance(v, bool) else None


def _float(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _left(source: str, source_path: str, eid: str, left_entry, left_tick=None, min_x=None, crossing=None) -> Fact:
    return Fact(eid, source, source_path, {"left_entry": left_entry, "left_tick": left_tick, "min_x": min_x,
                                           "crossing": crossing})


class MarioBTT(StageTags):
    """Mario's Break the Targets: left entry (first live tick with x < -2100, the left region past the wall) and
    qualified crossing (btt_qualified_crossing_v1).

    Left entry, best source first (exact yes/no, then sources that can only say yes):
        replay       replay/_local/verdicts.jsonl (this tool's MATCH replays)
        gate_trace   gate_trace.json.gz (M7r evaluations)
        eval_metrics evaluation.json -> eval_metrics.first_left_entry (M7g-K..M7r)
        census       runs/m7p/addendum/walltop_census/census.json
        reward_v3    labels.reward_v3 (M7j/M7k/M7l)
        m7s_goals    m7s_goals.json.gz cells (x bins aligned with -2100)
        crossing_verification.json records (yes only), final_obs (final observation live and x < -2100; yes only)
    Crossing: crossing_verification.json, then the census; "no left entry" implies no crossing.
    """

    stage = "btt_mario"
    summary_files = ("evaluation.json", "crossing_verification.json", "census.json")
    EXACT = ("replay", "gate_trace", "eval_metrics", "census", "reward_v3", "m7s_goals")
    POSITIVE = ("crossing_verification", "final_obs")
    M7S_LEFT_MAX_I = 5  # btt_goal_cell_v1: i = floor((x + 3900) / 300); i <= 5  <=>  x < -2100 exactly

    def from_episode(self, d, meta, names, rel):
        eid = str(meta.get("episode_id") or d.name)
        labels = meta.get("labels") if isinstance(meta.get("labels"), dict) else {}
        out: List[Fact] = []
        rv3 = labels.get("reward_v3")
        if isinstance(rv3, dict) and isinstance(rv3.get("entry_counts"), dict):
            first = rv3.get("first_entry") if isinstance(rv3.get("first_entry"), dict) else None
            n = sum(int(v) for v in rv3["entry_counts"].values() if isinstance(v, int))
            out.append(_left("reward_v3", rel(d / "metadata.json"), eid, 1 if (n > 0 or first) else 0,
                             _int(first.get("consumed_tick")) if first else None))
        final = meta.get("final_observation") if isinstance(meta.get("final_observation"), dict) else {}
        if final.get("fighter_valid") == 1 and final.get("btt_active") == 1 and \
                isinstance(final.get("position_x"), (int, float)) and final["position_x"] < LEFT_BOUNDARY_X:
            out.append(_left("final_obs", rel(d / "metadata.json"), eid, 1))
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
                out.append(_left("gate_trace", rel(d / "gate_trace.json.gz"), eid, 1 if first_t is not None else 0,
                                 first_t, min_x))
            except (OSError, ValueError, KeyError, TypeError, IndexError):
                pass
        if "m7s_goals.json.gz" in names:
            try:
                with gzip.open(d / "m7s_goals.json.gz", "rt", encoding="utf-8") as fp:
                    doc = json.load(fp)
                first_t = None
                for t, cell in enumerate(doc.get("cells") or []):
                    if isinstance(cell, str) and cell and int(cell.split(",")[0]) <= self.M7S_LEFT_MAX_I:
                        first_t = t
                        break
                out.append(_left("m7s_goals", rel(d / "m7s_goals.json.gz"), eid, 1 if first_t is not None else 0,
                                 first_t))
            except (OSError, ValueError, KeyError, TypeError, IndexError):
                pass
        return out

    def from_summary(self, path, rel):
        try:
            with open(path, encoding="utf-8") as fp:
                doc = json.load(fp)
        except (OSError, ValueError):
            return []
        if not isinstance(doc, dict):
            return []
        out: List[Fact] = []
        src = rel(path)
        if path.name == "evaluation.json":
            for e in doc.get("episodes") or []:
                m = e.get("eval_metrics") if isinstance(e, dict) else None
                if not isinstance(m, dict) or "first_left_entry" not in m or not e.get("episode_id"):
                    continue
                first = m.get("first_left_entry") if isinstance(m.get("first_left_entry"), dict) else None
                out.append(_left("eval_metrics", src, e["episode_id"], 1 if first else 0,
                                 _int(first.get("consumed_tick")) if first else None, _float(m.get("min_live_x"))))
        elif path.name == "crossing_verification.json":
            for r in doc.get("records") or []:
                if not isinstance(r, dict) or not r.get("episode_id"):
                    continue
                a = r.get("analysis") if isinstance(r.get("analysis"), dict) else {}
                first = a.get("first_left_entry") if isinstance(a.get("first_left_entry"), dict) else None
                exact = r.get("exact")
                exact_ok = exact.get("ok") if isinstance(exact, dict) else exact
                min_x = a.get("min_x")
                out.append(_left("crossing_verification", src, r["episode_id"], 1 if first else None,
                                 _int(first.get("consumed_tick")) if first else None,
                                 _float(min_x.get("x")) if isinstance(min_x, dict) else _float(min_x),
                                 (1 if r.get("qualified_crossing") else 0) if exact_ok is not False else None))
        elif path.name == "census.json":
            for e in doc.get("episodes") or []:
                if not isinstance(e, dict) or not e.get("episode_id") or not e.get("exact_replay", True):
                    continue
                out.append(_left("census", src, e["episode_id"], 1 if (e.get("left_entries") or 0) > 0 else 0,
                                 _int(e.get("first_left_entry_tick")), _float(e.get("min_x")),
                                 1 if e.get("qualified_crossing") else 0))
        return out

    def from_replay(self, verdict, episode_id):
        t = verdict.get("trajectory")
        if verdict.get("verdict") != "MATCH" or not isinstance(t, dict):
            return None  # a DESYNC replay is shown, never used as evidence
        first = t.get("first_left_entry") if isinstance(t.get("first_left_entry"), dict) else None
        return _left("replay", "replay/_local/verdicts.jsonl", episode_id, 1 if first else 0,
                     _int(first.get("consumed_tick")) if first else None, _float(t.get("min_live_x")))

    def resolve(self, facts):
        left = left_tick = left_source = None
        for s in self.EXACT + self.POSITIVE:
            f = facts.get(s)
            if f is None or f.data.get("left_entry") is None or (s in self.POSITIVE and not f.data["left_entry"]):
                continue
            left, left_tick, left_source = bool(f.data["left_entry"]), f.data.get("left_tick"), s
            break
        min_x = next((facts[s].data["min_x"] for s in self.EXACT + ("crossing_verification",)
                      if s in facts and facts[s].data.get("min_x") is not None), None)
        crossing = crossing_source = None
        for s in ("crossing_verification", "census"):
            if s in facts and facts[s].data.get("crossing") is not None:
                crossing, crossing_source = bool(facts[s].data["crossing"]), s
                break
        if crossing is None and left is False:
            crossing, crossing_source = False, "no left entry"
        tags = []
        if left:
            tags.append(f"left entry @{left_tick}" if left_tick is not None else "left entry")
        if crossing:
            tags.append("crossing")
        details: Details = [
            ("left entry", ("unknown" if left is None else
                            f"{'yes' if left else 'no'}{f' at tick {left_tick}' if left and left_tick is not None else ''}"
                            f" ({left_source})")),
            ("crossing", "unknown" if crossing is None else f"{'yes' if crossing else 'no'} ({crossing_source})"),
        ]
        if min_x is not None:
            details.append(("min x", f"{min_x:.1f}"))
        return tags, details


EXTRACTORS: Dict[str, StageTags] = {e.stage: e for e in (MarioBTT(),)}


def extractor_for(stage: Optional[str]) -> Optional[StageTags]:
    return EXTRACTORS.get(stage) if stage else None


def summary_file_names() -> Tuple[str, ...]:
    return tuple(sorted({n for e in EXTRACTORS.values() for n in e.summary_files}))
