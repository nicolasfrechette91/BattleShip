"""M7h: frontier-restart curriculum `btt_curriculum_frontier_v1` - the pure part (no game, no SB3, no torch).

Contract: docs/rl_frontier_curriculum_m7h_proposal.md (revision 2). Registered settings (user approval 2026-09-24):
50/50 selection after automatic resets, prefixes of at most 3,000 ticks, 60-tick pre-fall exclusion, M7f cell key.

This module owns:
  * the cell key (floor(position_x / 300), floor(position_y / 300), targets_remaining) on live steps;
  * the episode report a worker sends at the end of every training episode (built by EpisodeTrace);
  * the parent-side Archive (first reach on policy rows, strictly-shorter replacement, per-episode policy-row visits,
    eligibility) and its serialization;
  * the Selector (its own seeded Python generator; never the global random, never native RNG);
  * the left-region classification (genuine new policy entry / re-entry from an exposed lineage / prefix-reproduced).

Actions are Track 1 indices 0..71 (stick * 8 + button), one byte each. A prefix is the first L actions of a recorded
training trajectory that starts at tick 0, so every prefix step i consumes native tick i.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

CONTRACT_ID = "btt_curriculum_frontier_v1"
REPORT_SCHEMA = "m7h_episode_report_v1"
ARCHIVE_SCHEMA = "m7h_archive_v1"
TICK0_PROBABILITY = 0.5
MAX_PREFIX_TICKS = 3000
PRE_FALL_EXCLUSION_TICKS = 60
CELL_SIZE = 300
LEFT_BOUNDARY_X = -2100.0          # the M7g-a / btt_eval_metrics_v1 left-region rule (strict)
HIGH_Y = 3000.0                    # training diagnostic: the lowest live position_x at position_y >= 3000 (section 6.1)
TARGETS_TOTAL = 10
HORIZON = 3600
STICK_STATES, BUTTON_STATES = 9, 8
TRACK1_ACTIONS = STICK_STATES * BUTTON_STATES

REGISTERED = {"contract": CONTRACT_ID, "tick0_probability": TICK0_PROBABILITY, "max_prefix_ticks": MAX_PREFIX_TICKS,
              "pre_fall_exclusion_ticks": PRE_FALL_EXCLUSION_TICKS, "cell_size": CELL_SIZE}

# start kinds (a worker records tick0 / archive_prefix / tick0_after_prefix_lifecycle_failure; the parent's selection
# log also distinguishes the initial reset and an empty archive)
START_TICK0 = "tick0"
START_TICK0_INITIAL = "tick0_initial"
START_TICK0_ARCHIVE_EMPTY = "tick0_archive_empty"
START_PREFIX = "archive_prefix"
START_TICK0_AFTER_FAILURE = "tick0_after_prefix_lifecycle_failure"

# The artifact label that marks prefix rows (recorder labels -> metadata.json "labels"). It is written BEFORE the first
# prefix row (kind archive_prefix_in_progress) and replaced when the phase ends: archive_prefix (complete, rows [0, L)
# are prefix rows) or archive_prefix_failed (a lifecycle failure; every recorded row is a prefix row). An artifact
# without the label never contains a prefix row. prefix_rows() is the one reader of this rule.
START_LABEL = "m7h_start"
START_PREFIX_IN_PROGRESS = "archive_prefix_in_progress"
START_PREFIX_FAILED = "archive_prefix_failed"

CLASS_GENUINE = "genuine_new_policy_entry"
CLASS_REENTRY = "policy_reentry_exposed_lineage"
CLASS_PREFIX = "prefix_reproduced"

END_FALL = "fall"
END_CLEAR = "clear"
END_HORIZON = "horizon"
NOT_INGESTED_ENDS = ("lifecycle_failure", "aborted")

OBSERVATION_FIELDS = ("observation_schema", "host_frame", "input_tick", "time_passed", "game_status", "btt_active",
                      "targets_remaining", "fighter_valid", "position_x", "position_y", "air_velocity_x",
                      "air_velocity_y", "ground_velocity_x", "facing_direction", "ground_air_state", "fighter_status_id",
                      "jumps_used")


class CurriculumError(RuntimeError):
    """A violated curriculum invariant (never silently tolerated)."""


def check_registered(settings: Mapping[str, Any]) -> Dict[str, Any]:
    """The settings of a profile's [curriculum] table, which must be exactly the registered ones."""
    s = dict(settings)
    if s != REGISTERED:
        raise CurriculumError(f"curriculum settings {s} differ from the registered M7h settings {REGISTERED}")
    return s


# -- actions, cells, digests ----------------------------------------------------------------------------------


def encode_track1(stick: int, button: int) -> int:
    if not (0 <= int(stick) < STICK_STATES and 0 <= int(button) < BUTTON_STATES):
        raise CurriculumError(f"not a Track 1 action: stick {stick} button {button}")
    return int(stick) * BUTTON_STATES + int(button)


def decode_track1(index: int) -> Tuple[int, int]:
    if not 0 <= int(index) < TRACK1_ACTIONS:
        raise CurriculumError(f"not a Track 1 action index: {index}")
    return divmod(int(index), BUTTON_STATES)


def _get(obs: Any, name: str) -> Any:
    return obs[name] if isinstance(obs, Mapping) else getattr(obs, name)


def is_live(obs: Any) -> bool:
    return int(_get(obs, "fighter_valid")) == 1 and int(_get(obs, "btt_active")) == 1


def cell_of(obs: Any) -> Optional[Tuple[int, int, int]]:
    """The M7f cell of a live post-update observation; None when the step is not live."""
    if not is_live(obs):
        return None
    return (math.floor(float(_get(obs, "position_x")) / CELL_SIZE), math.floor(float(_get(obs, "position_y")) / CELL_SIZE),
            int(_get(obs, "targets_remaining")))


def is_left(obs: Any) -> bool:
    return is_live(obs) and float(_get(obs, "position_x")) < LEFT_BOUNDARY_X


def observation_dict(obs: Any) -> Dict[str, Any]:
    return {k: _get(obs, k) for k in OBSERVATION_FIELDS}


def observation_diffs(a: Mapping[str, Any], b: Mapping[str, Any], *, ignore: Sequence[str] = ("host_frame",)
                      ) -> Dict[str, Tuple[Any, Any]]:
    """Field differences of two observations (exact; host_frame is reported separately by callers)."""
    return {k: (a.get(k), b.get(k)) for k in OBSERVATION_FIELDS if k not in ignore and a.get(k) != b.get(k)}


def native_digest(rows: Iterable[Tuple[int, int, int, int]]) -> str:
    """The M7 native_action_digest: sha256 over 'buttons,stick_x,stick_y,consumed_tick\\n' lines."""
    h = hashlib.sha256()
    for b, x, y, t in rows:
        h.update(f"{int(b)},{int(x)},{int(y)},{int(t)}\n".encode("ascii"))
    return h.hexdigest()


def track1_triple(index: int) -> Tuple[int, int, int]:
    """(buttons, stick_x, stick_y) of a Track 1 index (the canonical native triple)."""
    from btt_learning import TRACK1_BUTTON_TABLE, TRACK1_STICK_TABLE

    stick, button = decode_track1(index)
    x, y = TRACK1_STICK_TABLE[stick]
    return int(TRACK1_BUTTON_TABLE[button]), int(x), int(y)


def prefix_digest(actions: bytes) -> str:
    """Digest of the first len(actions) rows of a tick-0 trajectory (row i consumes tick i)."""
    return native_digest((*track1_triple(a), i) for i, a in enumerate(actions))


def prefix_rows(labels: Mapping[str, Any], rows: int) -> Tuple[int, str]:
    """(L, kind) of one recorded episode from its artifact labels and its number of action rows: rows [0, L) were
    replayed by the prefix phase, rows [L, rows) were chosen by the policy. Raises CurriculumError on any label that
    does not determine L exactly.

        no m7h_start label                      L = 0          (a tick-0 start; every row is a policy row)
        archive_prefix                          L = prefix_length, 1 <= L <= rows
        archive_prefix_in_progress / _failed    L = rows       (the phase never completed; rows <= planned length)
    """
    st = labels.get(START_LABEL)
    rows = int(rows)
    if st is None:
        return 0, START_TICK0
    kind = st.get("kind")
    if kind == START_PREFIX:
        n = int(st["prefix_length"])
        if not 1 <= n <= min(rows, MAX_PREFIX_TICKS):
            raise CurriculumError(f"{START_LABEL}: prefix_length {n} with {rows} rows")
        return n, kind
    if kind in (START_PREFIX_IN_PROGRESS, START_PREFIX_FAILED):
        planned = int(st["prefix_length_planned"])
        if rows > planned or (kind == START_PREFIX_FAILED and st.get("rows_before_failure") not in (None, rows)):
            raise CurriculumError(f"{START_LABEL}: {kind} with {rows} rows (planned {planned}, "
                                  f"before failure {st.get('rows_before_failure')})")
        return rows, kind
    raise CurriculumError(f"{START_LABEL}: unknown kind {kind!r}")


def classify(prefix_left_steps: int, first_policy_left_step: Optional[int], lineage_left_exposed: bool) -> Optional[str]:
    """The section-4 class of an episode (None when it has no live left step)."""
    if prefix_left_steps > 0:
        return CLASS_PREFIX
    if first_policy_left_step is None:
        return None
    return CLASS_REENTRY if lineage_left_exposed else CLASS_GENUINE


# -- the worker-side trace of one episode ---------------------------------------------------------------------


@dataclass
class EpisodeTrace:
    """Every row of one training episode from tick 0 (prefix rows first), built in the worker."""

    reset_observation: Dict[str, Any]
    reset_step_count: int
    prefix_length: int = 0
    actions: bytearray = field(default_factory=bytearray)
    consumed_ok: bool = True
    rows_digest: Any = field(default_factory=hashlib.sha256)
    seen: set = field(default_factory=set)
    first_reach: List[List[Any]] = field(default_factory=list)      # [[cell], row index, observation dict]
    policy_cells: Dict[Tuple[int, int, int], int] = field(default_factory=dict)
    prefix_left_steps: int = 0
    first_policy_left_step: Optional[int] = None
    any_left: bool = False
    min_x_high: Dict[str, Optional[float]] = field(default_factory=lambda: {"policy": None, "prefix": None})
    last_observation: Optional[Dict[str, Any]] = None
    failed: bool = False

    @property
    def rows(self) -> int:
        return len(self.actions)

    def add_row(self, index: int, native: Tuple[int, int, int], consumed_tick: Optional[int], obs: Any, *,
                prefix: bool) -> None:
        row = len(self.actions)
        if consumed_tick is None or int(consumed_tick) != row:
            self.consumed_ok = False
        self.actions.append(int(index))
        self.rows_digest.update(f"{native[0]},{native[1]},{native[2]},{consumed_tick}\n".encode("ascii"))
        od = observation_dict(obs)
        self.last_observation = od
        c = cell_of(od)
        left = is_left(od)
        if c is not None and float(od["position_y"]) >= HIGH_Y:
            k = "prefix" if prefix else "policy"
            x = float(od["position_x"])
            self.min_x_high[k] = x if self.min_x_high[k] is None else min(self.min_x_high[k], x)
        if left:
            self.any_left = True
            if prefix:
                self.prefix_left_steps += 1
            elif self.first_policy_left_step is None:
                self.first_policy_left_step = row
        if c is None:
            return
        if not prefix:
            self.policy_cells[c] = self.policy_cells.get(c, 0) + 1
            if c not in self.seen:
                self.first_reach.append([list(c), row, od])
        self.seen.add(c)

    def report(self, *, start: Mapping[str, Any], summary: Mapping[str, Any], run_id: str, rank: int) -> Dict[str, Any]:
        lineage = bool(start.get("lineage_left_exposed", False))
        cls = classify(self.prefix_left_steps, self.first_policy_left_step, lineage)
        end = summary.get("end_reason")
        return {
            "schema": REPORT_SCHEMA, "contract": CONTRACT_ID, "run_id": run_id, "rank": int(rank),
            "worker_episode": summary.get("worker_episode"), "episode_id": summary.get("episode_id"),
            "start": dict(start), "actions": bytes(self.actions), "rows": self.rows,
            "consumed_ticks_ok": bool(self.consumed_ok), "full_digest": self.rows_digest.hexdigest(),
            "tracker_digest": summary.get("native_action_digest"),
            "end_reason": end, "last_consumed_tick": summary.get("last_consumed_tick"),
            "failure_tick": summary.get("last_consumed_tick") if end == END_FALL else None,
            "first_reach": self.first_reach, "policy_cells": [list(c) for c in self.policy_cells],
            "left": {"any_left": self.any_left, "prefix_left_steps": self.prefix_left_steps,
                     "first_policy_left_step": self.first_policy_left_step},
            "min_x_at_high_y": dict(self.min_x_high),
            "lineage_left_exposed": lineage, "class": cls,
        }


# -- the parent-side archive ----------------------------------------------------------------------------------


@dataclass
class Entry:
    cell: Tuple[int, int, int]
    prefix: bytes
    digest: str
    end_observation: Dict[str, Any]
    source: Dict[str, Any]
    lineage_left_exposed: bool
    eligible: bool
    ineligible_reason: Optional[str]
    visits: int = 0
    selected: int = 0
    replaced: int = 0
    inserted_seq: int = 0

    @property
    def length(self) -> int:
        return len(self.prefix)

    def to_json(self) -> Dict[str, Any]:
        return {"cell": list(self.cell), "length": self.length, "digest": self.digest,
                "end_observation": self.end_observation, "source": self.source,
                "lineage_left_exposed": self.lineage_left_exposed, "eligible": self.eligible,
                "ineligible_reason": self.ineligible_reason, "visits": self.visits, "selected": self.selected,
                "replaced": self.replaced, "inserted_seq": self.inserted_seq}


def eligibility(length: int, end_reason: Optional[str], last_consumed_tick: Optional[int], *,
                max_prefix: int = MAX_PREFIX_TICKS, fall_window: int = PRE_FALL_EXCLUSION_TICKS) -> Tuple[bool, Optional[str]]:
    """1 <= L <= 3000; the source did not end at or before step L-1; a source fall more than 60 ticks after step L-1."""
    if not 1 <= length <= max_prefix:
        return False, f"length {length} outside 1..{max_prefix}"
    if last_consumed_tick is not None and int(last_consumed_tick) <= length - 1:
        return False, f"the source ended at tick {last_consumed_tick}, within the prefix"
    if end_reason == END_FALL and last_consumed_tick is not None and int(last_consumed_tick) - (length - 1) <= fall_window:
        return False, f"source fall at tick {last_consumed_tick}, {int(last_consumed_tick) - (length - 1)} ticks after the cell"
    return True, None


class Archive:
    """Cells of this run's own finished training episodes; insertion-ordered; deterministic given the ingest order."""

    def __init__(self, run_id: str, *, max_prefix: int = MAX_PREFIX_TICKS, fall_window: int = PRE_FALL_EXCLUSION_TICKS):
        self.run_id = run_id
        self.max_prefix = int(max_prefix)
        self.fall_window = int(fall_window)
        self.entries: Dict[Tuple[int, int, int], Entry] = {}
        self.ingest_seq = 0
        self.stats: Dict[str, int] = {"reports": 0, "ingested": 0, "skipped_end": 0, "inserted": 0, "replaced": 0,
                                      "digest_mismatch": 0, "consumed_tick_mismatch": 0}
        self.classes: Dict[str, int] = {}

    def eligible(self) -> List[Entry]:
        return [e for e in self.entries.values() if e.eligible]

    def ingest(self, report: Mapping[str, Any], *, tracker_digest: Optional[str] = None) -> Dict[str, Any]:
        """One finished episode's report. Refuses a report of another run or a trajectory whose two independent
        digests disagree (the worker's rows vs the tracker's note_step/note_prefix_step digest)."""
        self.stats["reports"] += 1
        if report.get("schema") != REPORT_SCHEMA or report.get("contract") != CONTRACT_ID:
            raise CurriculumError(f"not an M7h report: {report.get('schema')} / {report.get('contract')}")
        if report.get("run_id") != self.run_id:
            raise CurriculumError(f"report of run {report.get('run_id')!r} offered to the archive of {self.run_id!r}")
        cls = report.get("class")
        if cls:
            self.classes[cls] = self.classes.get(cls, 0) + 1
        want = tracker_digest if tracker_digest is not None else report.get("tracker_digest")
        if want is not None and report.get("full_digest") != want:
            self.stats["digest_mismatch"] += 1
            raise CurriculumError(f"episode {report.get('episode_id')}: trajectory digest {report.get('full_digest')} "
                                  f"!= tracker digest {want}")
        if report.get("end_reason") in NOT_INGESTED_ENDS:
            self.stats["skipped_end"] += 1
            return {"ingested": False, "reason": report.get("end_reason")}
        if not report.get("consumed_ticks_ok"):
            self.stats["consumed_tick_mismatch"] += 1
            raise CurriculumError(f"episode {report.get('episode_id')}: consumed ticks are not 0..n-1")
        self.stats["ingested"] += 1
        self.ingest_seq += 1
        actions: bytes = bytes(report["actions"])
        start = report.get("start") or {}
        exposed = bool(report.get("lineage_left_exposed")) or bool((report.get("left") or {}).get("any_left"))
        source = {"run_id": report["run_id"], "episode_id": report.get("episode_id"), "rank": report.get("rank"),
                  "worker_episode": report.get("worker_episode"), "start_kind": start.get("kind"),
                  "start_prefix_digest": start.get("prefix_digest"), "full_digest": report.get("full_digest"),
                  "end_reason": report.get("end_reason"), "last_consumed_tick": report.get("last_consumed_tick")}
        inserted = replaced = 0
        for cell_list, row, obs in report.get("first_reach") or []:
            cell = tuple(int(v) for v in cell_list)
            length = int(row) + 1
            if length > len(actions):
                raise CurriculumError(f"first reach at row {row} beyond the {len(actions)} recorded actions")
            ok, why = eligibility(length, report.get("end_reason"), report.get("last_consumed_tick"),
                                  max_prefix=self.max_prefix, fall_window=self.fall_window)
            prefix = actions[:length]
            existing = self.entries.get(cell)
            if existing is None:
                self.entries[cell] = Entry(cell, prefix, prefix_digest(prefix), dict(obs), dict(source), exposed, ok, why,
                                           inserted_seq=self.ingest_seq)
                inserted += 1
            elif length < existing.length:
                existing.prefix, existing.digest, existing.end_observation = prefix, prefix_digest(prefix), dict(obs)
                existing.source, existing.lineage_left_exposed = dict(source), exposed
                existing.eligible, existing.ineligible_reason = ok, why
                existing.replaced += 1
                replaced += 1
        for cell_list in report.get("policy_cells") or []:
            cell = tuple(int(v) for v in cell_list)
            if cell in self.entries:
                self.entries[cell].visits += 1
        self.stats["inserted"] += inserted
        self.stats["replaced"] += replaced
        return {"ingested": True, "inserted": inserted, "replaced": replaced}

    # -- persistence ----------------------------------------------------------------------------------------

    def to_json(self) -> Dict[str, Any]:
        offsets, pos = [], 0
        for e in self.entries.values():
            offsets.append([pos, e.length])
            pos += e.length
        return {"schema": ARCHIVE_SCHEMA, "contract": CONTRACT_ID, "run_id": self.run_id, "max_prefix": self.max_prefix,
                "fall_window": self.fall_window, "ingest_seq": self.ingest_seq, "stats": dict(self.stats),
                "classes": dict(self.classes), "cells": len(self.entries), "eligible": len(self.eligible()),
                "entries": [dict(e.to_json(), prefix_offset=o) for e, o in zip(self.entries.values(), offsets)]}

    def prefixes_blob(self) -> bytes:
        return b"".join(e.prefix for e in self.entries.values())

    @classmethod
    def from_json(cls, data: Mapping[str, Any], blob: bytes) -> "Archive":
        a = cls(data["run_id"], max_prefix=data["max_prefix"], fall_window=data["fall_window"])
        a.ingest_seq, a.stats, a.classes = int(data["ingest_seq"]), dict(data["stats"]), dict(data["classes"])
        for d in data["entries"]:
            off, n = d["prefix_offset"]
            prefix = bytes(blob[off:off + n])
            if prefix_digest(prefix) != d["digest"]:
                raise CurriculumError(f"archive entry {d['cell']}: prefix bytes do not match digest")
            cell = tuple(d["cell"])
            a.entries[cell] = Entry(cell, prefix, d["digest"], d["end_observation"], d["source"], d["lineage_left_exposed"],
                                    d["eligible"], d["ineligible_reason"], d["visits"], d["selected"], d["replaced"],
                                    d["inserted_seq"])
        return a


# -- selection ----------------------------------------------------------------------------------------------------


def weight(visits: int) -> float:
    return 1.0 / math.sqrt(1.0 + float(visits))


class Selector:
    """The 50/50 start draw after an automatic reset, then a visit-weighted eligible cell. Own generator only."""

    def __init__(self, run_seed: int, *, tick0_probability: float = TICK0_PROBABILITY):
        material = hashlib.sha256(f"{CONTRACT_ID}|{int(run_seed)}".encode("ascii")).digest()
        self.rng = random.Random(int.from_bytes(material[:8], "big"))
        self.p0 = float(tick0_probability)
        self.draws = 0

    def select(self, archive: Archive) -> Tuple[str, Optional[Entry], Dict[str, float]]:
        u1 = self.rng.random()
        self.draws += 1
        if u1 < self.p0:
            return START_TICK0, None, {"u1": u1}
        eligible = archive.eligible()
        if not eligible:
            return START_TICK0_ARCHIVE_EMPTY, None, {"u1": u1}
        u2 = self.rng.random()
        self.draws += 1
        weights = [weight(e.visits) for e in eligible]
        target = u2 * math.fsum(weights)
        acc = 0.0
        chosen = eligible[-1]
        for e, w in zip(eligible, weights):
            acc += w
            if target < acc:
                chosen = e
                break
        return START_PREFIX, chosen, {"u1": u1, "u2": u2}

    def state_json(self) -> Dict[str, Any]:
        version, internal, gauss = self.rng.getstate()
        return {"version": version, "internal": list(internal), "gauss_next": gauss, "draws": self.draws}


def prefix_spec(entry: Entry, run_id: str) -> Dict[str, Any]:
    """What the parent sends to a worker's run_prefix_phase (plain, picklable)."""
    return {"contract": CONTRACT_ID, "run_id": run_id, "prefix": bytes(entry.prefix), "prefix_digest": entry.digest,
            "cell": list(entry.cell), "end_observation": dict(entry.end_observation), "source": dict(entry.source),
            "lineage_left_exposed": bool(entry.lineage_left_exposed)}


def dumps(data: Any) -> str:
    return json.dumps(data, indent=1, sort_keys=False, default=lambda o: o.hex() if isinstance(o, (bytes, bytearray)) else str(o))
