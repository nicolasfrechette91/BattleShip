#!/usr/bin/env python3
"""Episode artifacts for the replay viewer: loading, expected outcome, replay tracking, MATCH/DESYNC.

Pure Python, no game process. An episode artifact is a directory written by
rl/run_artifacts.py (artifact_schema 1, action contract rlaction_native_v1):

    <episode dir>/metadata.json   labels, terminal, initial/final observation
    <episode dir>/actions.jsonl   {"sequence_index","buttons","stick_x","stick_y","consumed_tick"}

Every M7 episode starts in a fresh BattleShip process at native tick 0
(curriculum prefixes of M7h/M7m are ordinary rows at the start of
actions.jsonl), so replaying all rows in order from a fresh process
reproduces the episode. The comparison below uses only what metadata.json
recorded; it never inspects, logs or compares RNG state.

Nothing here writes below runs/.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
RL_DIR = REPO_ROOT / "rl"
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

METADATA_FILE = "metadata.json"
ACTIONS_FILE = "actions.jsonl"

# btt_native_failure_v1 (rl/btt_parallel.py is_native_failure): the first post-update
# observation with game_status == 5, btt_active == 1, targets_remaining > 0 and no
# native EpisodeEnded terminates the episode. The next submit would wedge the game.
GAME_STATUS_END = 5
TARGETS_TOTAL_DEFAULT = 10

# Stage geometry used by the trajectory summary (rl/m7g_fixture.py, rl/m7f_targets.py):
# the left region is position_x < -2100 (strict); the wall top / ledge L0 is y 3000.
LEFT_BOUNDARY_X = -2100.0
WALL_TOP_Y = 3000.0

# Observation fields that are not game state (rl/m7d_run.py _obs_equal, policy_excluded_fields).
OBS_EXCLUDED = ("host_frame",)

# Native N64 button bits (port/rl/rl.h RL_BUTTON_*), display names.
BUTTON_NAMES: Tuple[Tuple[int, str], ...] = (
    (0x8000, "A"), (0x4000, "B"), (0x2000, "Z"), (0x1000, "START"),
    (0x0800, "D-up"), (0x0400, "D-down"), (0x0200, "D-left"), (0x0100, "D-right"),
    (0x0020, "L"), (0x0010, "R"),
    (0x0008, "C-up"), (0x0004, "C-down"), (0x0002, "C-left"), (0x0001, "C-right"),
)


def button_name(buttons: int) -> str:
    names = [name for bit, name in BUTTON_NAMES if buttons & bit]
    return "+".join(names) if names else "none"


def stick_arrow(x: int, y: int) -> str:
    """Eight-way arrow for a stick position (y up is positive, N64 convention)."""
    if x == 0 and y == 0:
        return "·"  # middle dot: neutral
    import math

    octant = int(round(math.atan2(y, x) / (math.pi / 4))) % 8
    return "→↗↑↖←↙↓↘"[octant]


# -- loading ---------------------------------------------------------------------------------------


class EpisodeError(ValueError):
    """The path is not a readable, consistent episode artifact."""


@dataclass(frozen=True)
class Row:
    sequence_index: int
    buttons: int
    stick_x: int
    stick_y: int
    consumed_tick: Optional[int]


@dataclass
class Episode:
    directory: Path
    metadata: Dict[str, Any]
    rows: List[Row]

    @property
    def episode_id(self) -> str:
        return str(self.metadata.get("episode_id") or self.directory.name)

    @property
    def labels(self) -> Dict[str, Any]:
        labels = self.metadata.get("labels")
        return labels if isinstance(labels, dict) else {}

    @property
    def replay_rows(self) -> List[Row]:
        """Rows that were consumed natively. A lifecycle failure can leave a final row without a result
        (consumed_tick null); such a row never reached the game and is not replayed."""
        out: List[Row] = []
        for r in self.rows:
            if r.consumed_tick is None:
                break
            out.append(r)
        return out

    @property
    def targets_total(self) -> int:
        contracts = self.labels.get("contracts")
        if isinstance(contracts, dict) and isinstance(contracts.get("targets_total"), int):
            return int(contracts["targets_total"])
        init = self.metadata.get("initial_observation")
        if isinstance(init, dict) and isinstance(init.get("targets_remaining"), int):
            return int(init["targets_remaining"])
        return TARGETS_TOTAL_DEFAULT


def resolve_episode_dir(path: os.PathLike | str) -> Path:
    """Accept an episode directory or its actions.jsonl / metadata.json."""
    p = Path(path).expanduser()
    if p.is_file() and p.name in (ACTIONS_FILE, METADATA_FILE):
        p = p.parent
    if not p.is_dir():
        raise EpisodeError(f"not an episode directory or actions.jsonl: {path}")
    if not (p / ACTIONS_FILE).is_file():
        raise EpisodeError(f"{p} has no {ACTIONS_FILE}")
    if not (p / METADATA_FILE).is_file():
        raise EpisodeError(f"{p} has no {METADATA_FILE}")
    return p.resolve()


def load_episode(path: os.PathLike | str) -> Episode:
    """Read and validate an artifact with the project's own reader (rl/run_artifacts.read_artifact)."""
    from run_artifacts import ArtifactError, read_artifact  # imported lazily: it pulls in gymnasium when present

    directory = resolve_episode_dir(path)
    try:
        art = read_artifact(directory)
    except ArtifactError as exc:
        raise EpisodeError(str(exc)) from exc
    rows = [Row(a.sequence_index, int(a.buttons), int(a.stick_x), int(a.stick_y), a.consumed_tick)
            for a in art.actions]
    for r in rows:
        if r.consumed_tick is not None and r.consumed_tick != r.sequence_index:
            raise EpisodeError(
                f"row {r.sequence_index} has consumed_tick {r.consumed_tick}: not a tick-0 episode "
                "(every row i must be native tick i)")
    return Episode(directory, art.metadata, rows)


def action_digest(rows: List[Row]) -> str:
    """labels.native_action_digest (rl/btt_parallel.py M7EpisodeTracker): sha256 over
    'buttons,stick_x,stick_y,consumed_tick\\n' per row, prefix rows included."""
    h = hashlib.sha256()
    for r in rows:
        h.update(f"{r.buttons},{r.stick_x},{r.stick_y},{r.consumed_tick}\n".encode("ascii"))
    return h.hexdigest()


def is_fall(observation: Mapping[str, Any], episode_ended: bool) -> bool:
    return (not episode_ended
            and int(observation.get("btt_active", 0)) == 1
            and int(observation.get("game_status", 0)) == GAME_STATUS_END
            and int(observation.get("targets_remaining", 0)) > 0)


def is_live(observation: Mapping[str, Any]) -> bool:
    return int(observation.get("fighter_valid", 0)) == 1 and int(observation.get("btt_active", 0)) == 1


# -- expected outcome ------------------------------------------------------------------------------


@dataclass
class Expected:
    end_kind: str  # clear | fall | truncated | unknown
    end_detail: str
    rows_to_replay: int
    steps: Optional[int]
    last_consumed_tick: Optional[int]
    targets_broken: Optional[int]  # total, prefix rows included
    completion_time_passed: Optional[int]
    completion_input_tick: Optional[int]
    initial_observation: Optional[Dict[str, Any]]
    final_observation: Optional[Dict[str, Any]]
    recorded_digest: Optional[str]
    file_digest: str


def _int_or_none(value: Any) -> Optional[int]:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def recorded_end(metadata: Mapping[str, Any]) -> Tuple[str, str]:
    """(kind, detail) of a recorded episode: kind is clear | fall | truncated | unknown."""
    labels = metadata.get("labels") if isinstance(metadata.get("labels"), dict) else {}
    terminal = metadata.get("terminal") if isinstance(metadata.get("terminal"), dict) else {}
    termination = labels.get("termination_reason", terminal.get("termination_reason"))
    truncation = labels.get("truncation_reason", terminal.get("truncation_reason"))
    end_reason = labels.get("end_reason", terminal.get("end_reason"))
    cleared = labels.get("cleared", terminal.get("cleared"))
    if cleared is True or termination == "native_clear":
        kind = "clear"
    elif termination == "native_failure" or end_reason == "fall":
        kind = "fall"
    elif truncation is not None or end_reason is not None:
        kind = "truncated"
    else:
        kind = "unknown"
    detail = ", ".join(f"{k}={v}" for k, v in (("end_reason", end_reason), ("termination", termination),
                                                 ("truncation", truncation)) if v is not None) or "not recorded"
    return kind, detail


def recorded_targets(metadata: Mapping[str, Any]) -> Optional[int]:
    """Targets broken over the whole episode (prefix rows included): terminal.targets_broken, else labels
    (labels count the policy phase only when an M7h/M7m prefix exists)."""
    labels = metadata.get("labels") if isinstance(metadata.get("labels"), dict) else {}
    terminal = metadata.get("terminal") if isinstance(metadata.get("terminal"), dict) else {}
    targets = _int_or_none(terminal.get("targets_broken"))
    if targets is None and not labels.get("m7h_start"):
        targets = _int_or_none(labels.get("targets_broken"))
    return targets


def expected_outcome(ep: Episode) -> Expected:
    m, labels = ep.metadata, ep.labels
    terminal = m.get("terminal") if isinstance(m.get("terminal"), dict) else {}
    kind, detail = recorded_end(m)
    targets = recorded_targets(m)
    return Expected(
        end_kind=kind,
        end_detail=detail,
        rows_to_replay=len(ep.replay_rows),
        steps=_int_or_none(terminal.get("step_count")),
        last_consumed_tick=_int_or_none(terminal.get("last_consumed_tick")),
        targets_broken=targets,
        completion_time_passed=_int_or_none(labels.get("completion_time_passed")),
        completion_input_tick=_int_or_none(labels.get("completion_input_tick")),
        initial_observation=m.get("initial_observation") if isinstance(m.get("initial_observation"), dict) else None,
        final_observation=m.get("final_observation") if isinstance(m.get("final_observation"), dict) else None,
        recorded_digest=labels.get("native_action_digest") if isinstance(labels.get("native_action_digest"), str)
        else None,
        file_digest=action_digest(ep.rows),
    )


# -- replay tracking -------------------------------------------------------------------------------


@dataclass
class Trajectory:
    """Per-episode facts accumulated from the step replies (live ticks only)."""

    min_live_x: Optional[float] = None
    max_live_y: Optional[float] = None
    first_left_entry: Optional[Dict[str, Any]] = None  # first live step with position_x < -2100
    left_region_steps: int = 0
    steps_at_or_above_wall_top: int = 0
    target_break_ticks: List[int] = field(default_factory=list)  # consumed_tick of each targets_remaining drop

    def as_dict(self) -> Dict[str, Any]:
        return {
            "min_live_x": self.min_live_x,
            "max_live_y": self.max_live_y,
            "first_left_entry": self.first_left_entry,
            "left_region_steps": self.left_region_steps,
            "steps_at_or_above_wall_top": self.steps_at_or_above_wall_top,
            "target_break_ticks": list(self.target_break_ticks),
        }


class ReplayTracker:
    """Checks every step reply against its row and accumulates the replayed outcome.

    feed_initial() takes the tick-0 `observe` observation, feed_step() one step
    reply (state name, step_count, consumed_tick, observation dict). The
    tracker never talks to the game."""

    def __init__(self, ep: Episode):
        self.ep = ep
        self.expected = expected_outcome(ep)
        self.initial: Optional[Dict[str, Any]] = None
        self.last: Optional[Dict[str, Any]] = None  # last observation
        self.steps = 0
        self.last_consumed_tick: Optional[int] = None
        self.end_kind: Optional[str] = None  # clear | fall | rows_exhausted
        self.first_mismatch: Optional[str] = None
        self.trajectory = Trajectory()
        self._prev_remaining: Optional[int] = None

    @property
    def ended(self) -> bool:
        return self.end_kind is not None

    @property
    def targets_broken(self) -> Optional[int]:
        obs = self.last or self.initial
        if obs is None:
            return None
        return self.ep.targets_total - int(obs.get("targets_remaining", self.ep.targets_total))

    def feed_initial(self, observation: Dict[str, Any]) -> None:
        self.initial = dict(observation)
        self._prev_remaining = int(observation.get("targets_remaining", 0))

    def feed_step(self, row: Row, state_name: str, step_count: int, consumed_tick: int,
                  observation: Dict[str, Any]) -> None:
        index = self.steps
        self.steps += 1
        self.last = dict(observation)
        self.last_consumed_tick = consumed_tick
        if self.first_mismatch is None:
            problems = []
            if row.consumed_tick is not None and consumed_tick != row.consumed_tick:
                problems.append(f"consumed_tick {consumed_tick} (recorded {row.consumed_tick})")
            if step_count != index + 1:
                problems.append(f"step_count {step_count} (expected {index + 1})")
            if int(observation.get("input_tick", -1)) != consumed_tick + 1:
                problems.append(f"input_tick {observation.get('input_tick')} (expected {consumed_tick + 1})")
            if problems:
                self.first_mismatch = f"row {row.sequence_index}: " + ", ".join(problems)
        remaining = int(observation.get("targets_remaining", 0))
        if self._prev_remaining is not None and remaining < self._prev_remaining:
            self.trajectory.target_break_ticks.extend([consumed_tick] * (self._prev_remaining - remaining))
        self._prev_remaining = remaining
        if is_live(observation):
            t = self.trajectory
            x, y = float(observation["position_x"]), float(observation["position_y"])
            t.min_live_x = x if t.min_live_x is None else min(t.min_live_x, x)
            t.max_live_y = y if t.max_live_y is None else max(t.max_live_y, y)
            if x < LEFT_BOUNDARY_X:
                t.left_region_steps += 1
                if t.first_left_entry is None:
                    t.first_left_entry = {"consumed_tick": consumed_tick, "x": x, "y": y}
            if y >= WALL_TOP_Y:
                t.steps_at_or_above_wall_top += 1
        ended = state_name == "EpisodeEnded"
        if ended:
            self.end_kind = "clear"
        elif is_fall(observation, ended):
            self.end_kind = "fall"
        elif self.steps >= self.expected.rows_to_replay:
            self.end_kind = "rows_exhausted"


# -- comparison ----------------------------------------------------------------------------------


DIGEST_CHECK = "actions digest (file vs labels.native_action_digest)"
ABSENT = "<absent>"


@dataclass
class Check:
    name: str
    ok: bool
    expected: Any
    got: Any
    # Observation checks: every differing field as (field, expected value, got value), full precision.
    rows: Optional[List[Tuple[str, Any, Any]]] = None


@dataclass
class Verdict:
    match: bool
    checks: List[Check]
    skipped: List[str]

    @property
    def word(self) -> str:
        return "MATCH" if self.match else "DESYNC"

    def failures(self) -> List[Check]:
        return [c for c in self.checks if not c.ok]

    def lines(self) -> List[str]:
        out = []
        for c in self.checks:
            mark = "ok  " if c.ok else "FAIL"
            if c.ok:
                out.append(f"  {mark} {c.name}: {c.got}")
            else:
                out.append(f"  {mark} {c.name}: expected {c.expected}, got {c.got}")
        for s in self.skipped:
            out.append(f"  skip {s}")
        return out


def observation_diff_rows(expected: Mapping[str, Any], got: Mapping[str, Any]) -> List[Tuple[str, Any, Any]]:
    """(field, expected, got) for every differing field (type or value), host_frame excluded, sorted by field."""
    keys = sorted((set(expected) | set(got)) - set(OBS_EXCLUDED))
    rows = []
    for k in keys:
        a, b = expected.get(k, ABSENT), got.get(k, ABSENT)
        if type(a) is not type(b) or a != b:
            rows.append((k, a, b))
    return rows


def observation_diffs(expected: Mapping[str, Any], got: Mapping[str, Any]) -> List[str]:
    return [f"{k}: {a!r} vs {b!r}" for k, a, b in observation_diff_rows(expected, got)]


def compare(tracker: ReplayTracker) -> Verdict:
    """MATCH iff every check that metadata.json supports agrees exactly."""
    e = tracker.expected
    checks: List[Check] = []
    skipped: List[str] = []

    if e.recorded_digest is not None:
        checks.append(Check(DIGEST_CHECK, e.file_digest == e.recorded_digest, e.recorded_digest[:16],
                            e.file_digest[:16]))
    else:
        skipped.append("actions digest: labels.native_action_digest not recorded")

    if e.initial_observation is not None and tracker.initial is not None:
        rows = observation_diff_rows(e.initial_observation, tracker.initial)
        diffs = observation_diffs(e.initial_observation, tracker.initial)
        checks.append(Check("initial observation (tick 0, host_frame excluded)", not diffs,
                            "identical", "; ".join(diffs) if diffs else "identical", rows or None))
    else:
        skipped.append("initial observation: not recorded")

    checks.append(Check("per-row clocks (consumed_tick, step_count, input_tick)", tracker.first_mismatch is None,
                        "consistent", tracker.first_mismatch or "consistent"))

    got_kind = {"clear": "clear", "fall": "fall", "rows_exhausted": "truncated"}.get(tracker.end_kind or "", "incomplete")
    if e.end_kind != "unknown":
        checks.append(Check("end", got_kind == e.end_kind, f"{e.end_kind} ({e.end_detail})", got_kind))
    else:
        skipped.append("end kind: not recorded")

    if e.steps is not None:
        checks.append(Check("steps", tracker.steps == e.steps, e.steps, tracker.steps))
    if e.last_consumed_tick is not None:
        label = {"fall": "fall tick (last consumed)", "clear": "clear tick (last consumed)"}.get(
            e.end_kind, "last consumed tick")
        checks.append(Check(label, tracker.last_consumed_tick == e.last_consumed_tick,
                            e.last_consumed_tick, tracker.last_consumed_tick))

    if e.targets_broken is not None:
        checks.append(Check("targets broken", tracker.targets_broken == e.targets_broken,
                            e.targets_broken, tracker.targets_broken))
    else:
        skipped.append("targets broken: not recorded")

    if e.end_kind == "clear":
        obs = tracker.last or {}
        if e.completion_time_passed is not None:
            checks.append(Check("completion time_passed", obs.get("time_passed") == e.completion_time_passed,
                                e.completion_time_passed, obs.get("time_passed")))
        if e.completion_input_tick is not None:
            checks.append(Check("completion input_tick", obs.get("input_tick") == e.completion_input_tick,
                                e.completion_input_tick, obs.get("input_tick")))

    if e.final_observation is not None and tracker.last is not None:
        rows = observation_diff_rows(e.final_observation, tracker.last)
        diffs = observation_diffs(e.final_observation, tracker.last)
        checks.append(Check("final observation (host_frame excluded)", not diffs, "identical",
                            "; ".join(diffs[:6]) + (" ..." if len(diffs) > 6 else "") if diffs else "identical",
                            rows or None))
    elif e.final_observation is None:
        skipped.append("final observation: not recorded")

    return Verdict(match=all(c.ok for c in checks), checks=checks, skipped=skipped)


def format_verdict(ep: Episode, tracker: ReplayTracker, verdict: Verdict) -> str:
    head = f"{verdict.word}  {ep.episode_id}  ({tracker.steps} steps replayed, end={tracker.end_kind or 'incomplete'})"
    return "\n".join([head, *verdict.lines()])


def episode_summary(ep: Episode) -> Dict[str, Any]:
    """A short description of the recorded episode for the viewer panel."""
    labels = ep.labels
    exp = labels.get("experiment") if isinstance(labels.get("experiment"), dict) else {}
    contracts = labels.get("contracts") if isinstance(labels.get("contracts"), dict) else {}
    e = expected_outcome(ep)
    start = labels.get("m7h_start") if isinstance(labels.get("m7h_start"), dict) else None
    observation = contracts.get("policy_observation_contract")
    if not observation and isinstance(exp.get("policy_observation"), dict):
        observation = exp["policy_observation"].get("contract")
    return {
        "episode_id": ep.episode_id,
        "directory": str(ep.directory),
        "role": labels.get("role"),
        "run_id": labels.get("run_id"),
        "profile": exp.get("name") or exp.get("environment_profile"),
        "observation": observation,
        "reward": labels.get("reward_contract"),
        "rows": len(ep.rows),
        "rows_to_replay": e.rows_to_replay,
        "prefix_rows": start.get("prefix_length") if start else None,
        "end": e.end_kind,
        "end_detail": e.end_detail,
        "targets_broken": e.targets_broken,
        "completion_input_tick": e.completion_input_tick,
        "last_consumed_tick": e.last_consumed_tick,
    }


def load_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)
