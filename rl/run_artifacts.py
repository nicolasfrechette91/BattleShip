#!/usr/bin/env python3
"""M4: reproducible episode artifacts and non-invasive anomaly recording.

The authoritative artifact of an episode is the exact controller trajectory
that was submitted to the frozen M1d / M1c stepping path: for every accepted
step the native RLAction triple (N64 button word, int8 stick x, int8 stick y)
exactly as the `step` request carried it, plus the `consumed_tick` the paired
result reported. Nothing model-specific is needed to reproduce the run: a
Gym action index, a Track 1 bin or a policy checkpoint may all change later,
the native triple cannot. No video, no screenshots, no state dumps, no RNG
metadata and no Python replay checksum (the native replay checksum stays with
M0 / M1).

Artifact layout (schema ARTIFACT_SCHEMA):

    <root>/<episode_id>/
        metadata.json     one object: schema, contracts, identity, labels,
                          preservation reasons, action count, terminal
                          status and values, anomaly events, diagnostics
        actions.jsonl     one object per submitted action, in order:
                          {"sequence_index": i, "buttons": B, "stick_x": X,
                           "stick_y": Y, "consumed_tick": T}

Retention: nothing is written unless the episode was marked for
preservation (EpisodeRecorder.preserve) with one of the PreservationReason
values; an unmarked episode is discarded for the cost of dropping a list.
M5 supplies the training-side facts (episode number, checkpoint label,
current best metrics) through `labels` and its own retention decision; the
format does not change for that.

Anomaly detection is observational only. Detectors look at consecutive
observations and emit events; an event marks the episode for preservation
and is stored in the metadata. Detectors never touch the action, the
environment, the reward or the episode's continuation, and an event is
described as what was measured ("large_position_delta"), never as a
confirmed glitch.

Two integration paths, both optional and both outside the environment class:

    raw M1d client:   recorder = EpisodeRecorder(...)
                      i = recorder.record_action(buttons, sx, sy)
                      result = client.step(buttons, sx, sy)
                      recorder.record_result(result)      # pairs consumed_tick, runs detectors
    M3 Gymnasium:     env = EpisodeRecordingWrapper(BattleShipBTTEnv(...), artifact_root)
                      (records env.last_step_result / info["native_action"] after each step)

Standard library only; the Gymnasium wrapper is defined only if gymnasium
imports.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from battleship_client import BattleShipClient, Observation, Observe, StepResult, StepState  # noqa: E402

ARTIFACT_SCHEMA = 1
ARTIFACT_FORMAT = "battleship_btt_episode"
METADATA_FILE = "metadata.json"
ACTIONS_FILE = "actions.jsonl"

# What one actions.jsonl row means: the RLAction triple of protocol 1's
# `step` op, verbatim (buttons: N64 word 0..0xFFFF, sticks: int8), i.e. the
# native M1c controller contract, independent of any higher-level mapping.
NATIVE_ACTION_CONTRACT = "rlaction_native_v1"

# Default one-tick position-delta threshold, game units per native tick.
# Calibration (2026-09-21): about 215.525 units of vertical movement in one
# native tick has been observed as legitimate Mario Up-B behaviour on the
# tracked 7.43 s baseline (tick 148), so the earlier default of 200 fired on
# normal play. 250 is a PRESERVATION HEURISTIC for the current Mario-only
# Break the Targets environment: exceeding it means "worth keeping and
# looking at", never "glitch". It is not a universal definition of anything;
# other characters may need other thresholds, and character-specific
# profiles are deliberately not implemented. Always overridable per detector.
DEFAULT_POSITION_DELTA_THRESHOLD = 250.0


class PreservationReason(str, Enum):
    MANUAL = "manual"
    PERIODIC_MILESTONE = "periodic_milestone"
    NEW_BEST_TARGET_COUNT = "new_best_target_count"
    NEW_FASTEST_COMPLETED_RUN = "new_fastest_completed_run"
    MAJOR_PERFORMANCE_IMPROVEMENT = "major_performance_improvement"
    ANOMALY = "anomaly"


class EpisodeStatus(str, Enum):
    ACTIVE = "active"          # still being recorded
    TERMINAL = "terminal"      # native EpisodeEnded collected (targets_remaining 0)
    TRUNCATED = "truncated"    # Python-owned bound (max_episode_steps)
    ABORTED = "aborted"        # caller stopped early (reset / close mid-episode)
    FAILED = "failed"          # process / transport / lifecycle failure raised
    UNKNOWN = "unknown"        # finish() was never called before writing


class ArtifactError(ValueError):
    """Malformed or inconsistent artifact on disk."""


class ReplayMismatch(RuntimeError):
    """A resubmitted action did not reproduce the recorded consumed_tick."""


# -- records ----------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordedAction:
    sequence_index: int
    buttons: int
    stick_x: int
    stick_y: int
    consumed_tick: Optional[int] = None  # from the paired step result; None if the step never returned

    def to_json(self) -> Dict[str, Any]:
        return {"sequence_index": self.sequence_index, "buttons": self.buttons, "stick_x": self.stick_x,
                "stick_y": self.stick_y, "consumed_tick": self.consumed_tick}

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "RecordedAction":
        try:
            ct = data.get("consumed_tick")
            return cls(int(data["sequence_index"]), int(data["buttons"]), int(data["stick_x"]), int(data["stick_y"]),
                       None if ct is None else int(ct))
        except (KeyError, TypeError, ValueError) as exc:
            raise ArtifactError(f"bad action row {data!r}: {exc}") from exc


@dataclass(frozen=True)
class AnomalyEvent:
    detector: str            # detector name, e.g. "position_delta"
    event: str               # what was measured, e.g. "large_position_delta" (never "glitch")
    sequence_index: int      # index of the recorded action whose result exposed it (-1: initial observation)
    tick: Optional[int]      # consumed_tick of that step, when known
    details: Dict[str, Any]  # detector-specific evidence (positions, deltas, threshold, ...)

    def to_json(self) -> Dict[str, Any]:
        return asdict(self)


def observation_to_json(observation: Optional[Observation]) -> Optional[Dict[str, Any]]:
    return None if observation is None else asdict(observation)


# -- anomaly detectors ---------------------------------------------------------------------


class ObservationDetector:
    """Base class: compares consecutive observations, returns events, changes nothing.

    Subclasses implement compare(). They receive the previous and current
    M1b observations of the same process; `previous` is None for the first
    observation after reset. Detectors must only read the observations."""

    name = "detector"

    def reset(self) -> None:
        """Called at the start of every episode."""

    def compare(self, previous: Optional[Observation], current: Observation) -> List[Dict[str, Any]]:
        """Return zero or more event detail dicts; each becomes an AnomalyEvent with self.event_name."""
        raise NotImplementedError

    event_name = "anomaly"


class PositionDeltaDetector(ObservationDetector):
    """One-native-tick fighter position delta above a configurable threshold.

    dx = current.position_x - previous.position_x, dy likewise. Only pairs
    where BOTH observations carry an explicitly valid fighter (fighter_valid
    == 1) inside an active BTT battle (btt_active == 1) are compared; zeros
    are never taken to mean 'the fighter is at the origin'. The threshold is
    a recording heuristic: exceeding it means 'worth preserving and looking
    at', not 'glitch'. The default (DEFAULT_POSITION_DELTA_THRESHOLD, 250)
    sits above the roughly 215.525-unit one-tick vertical move of Mario's
    Up-B, which is legitimate; it is specific to the current Mario-only BTT
    environment and any caller may pass another value.

    Observational only: it reads two observations and returns event details.
    It never modifies, clamps or rejects an action, never terminates an
    episode, and has no path into rewards, stepping, physics or replay."""

    name = "position_delta"
    event_name = "large_position_delta"

    def __init__(self, threshold: float = DEFAULT_POSITION_DELTA_THRESHOLD):
        if not (threshold > 0):
            raise ValueError("threshold must be > 0")
        self.threshold = float(threshold)

    def compare(self, previous: Optional[Observation], current: Observation) -> List[Dict[str, Any]]:
        if previous is None:
            return []
        if not (previous.fighter_valid == 1 and current.fighter_valid == 1
                and previous.btt_active == 1 and current.btt_active == 1):
            return []
        dx = float(current.position_x) - float(previous.position_x)
        dy = float(current.position_y) - float(previous.position_y)
        axes = [axis for axis, d in (("x", dx), ("y", dy)) if abs(d) > self.threshold]
        if not axes:
            return []
        return [{
            "axes": axes,
            "previous_input_tick": previous.input_tick,
            "current_input_tick": current.input_tick,
            "previous_position": [float(previous.position_x), float(previous.position_y)],
            "current_position": [float(current.position_x), float(current.position_y)],
            "delta": [dx, dy],
            "threshold": self.threshold,
            "previous_fighter_status_id": previous.fighter_status_id,
            "current_fighter_status_id": current.fighter_status_id,
            "previous_ground_air_state": previous.ground_air_state,
            "current_ground_air_state": current.ground_air_state,
        }]


def default_detectors() -> List[ObservationDetector]:
    """The detectors enabled by default in M4: the position-delta detector at DEFAULT_POSITION_DELTA_THRESHOLD (250)."""
    return [PositionDeltaDetector(DEFAULT_POSITION_DELTA_THRESHOLD)]


# -- recorder -------------------------------------------------------------------------------------


@dataclass
class PreservationMark:
    reason: str
    note: Optional[str]
    sequence_index: int  # number of actions recorded when the mark was made

    def to_json(self) -> Dict[str, Any]:
        return {"reason": self.reason, "note": self.note, "sequence_index": self.sequence_index}


class EpisodeRecorder:
    """Records one episode's exact submitted native actions, paired consumed
    ticks, anomaly events and terminal facts; writes an artifact only when
    preserved. Cheap: a list append per action, a few comparisons per result.

    Lifecycle: construct (episode starts) -> record_action / record_result
    per step -> preserve(reason) any time -> finish(status) -> write(root) or
    discard(). `labels` is free-form training metadata (episode number,
    checkpoint label, best metrics); it is stored, never interpreted."""

    def __init__(
        self,
        *,
        episode_id: Optional[str] = None,
        source_action_contract: Optional[str] = None,
        labels: Optional[Mapping[str, Any]] = None,
        detectors: Optional[Iterable[ObservationDetector]] = None,
        initial: Optional[Observe] = None,
        diagnostics: Optional[Mapping[str, Any]] = None,
    ):
        self.episode_id = episode_id or make_episode_id()
        self.source_action_contract = source_action_contract
        self.labels: Dict[str, Any] = dict(labels or {})
        self.detectors: List[ObservationDetector] = list(default_detectors() if detectors is None else detectors)
        self.diagnostics: Dict[str, Any] = dict(diagnostics or {})
        self.actions: List[RecordedAction] = []
        self.events: List[AnomalyEvent] = []
        self.marks: List[PreservationMark] = []
        self.status = EpisodeStatus.ACTIVE
        self.terminal: Dict[str, Any] = {}
        self.initial_observation: Optional[Observation] = initial.observation if initial is not None else None
        self.final_observation: Optional[Observation] = None
        self.finish_note: Optional[str] = None
        self.created_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._t0 = time.monotonic()
        self._wall_s: Optional[float] = None
        self._previous: Optional[Observation] = self.initial_observation
        self._pending: Optional[int] = None  # sequence_index awaiting its result
        for d in self.detectors:
            d.reset()
        if self.initial_observation is not None:
            self._run_detectors(-1, None, self.initial_observation)

    # -- properties -------------------------------------------------------------------------

    @property
    def preserved(self) -> bool:
        return bool(self.marks)

    @property
    def action_count(self) -> int:
        return len(self.actions)

    @property
    def active(self) -> bool:
        return self.status == EpisodeStatus.ACTIVE

    # -- recording -----------------------------------------------------------------------

    def record_action(self, buttons: int, stick_x: int, stick_y: int) -> int:
        """Record the canonical native triple that is about to be (or was just) submitted.

        Returns the sequence index. Values are stored exactly; no validation
        beyond integer types, because the server is the authority on legality
        and a rejected action never produces a result (record_result is then
        not called and consumed_tick stays None)."""
        if not self.active:
            raise RuntimeError(f"recorder is {self.status.value}; cannot record")
        for name, value in (("buttons", buttons), ("stick_x", stick_x), ("stick_y", stick_y)):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an int, got {type(value).__name__}")
        index = len(self.actions)
        self.actions.append(RecordedAction(index, int(buttons), int(stick_x), int(stick_y), None))
        self._pending = index
        return index

    def record_result(self, result: StepResult) -> List[AnomalyEvent]:
        """Pair the last recorded action with its step result and run the detectors.

        Returns the events raised by this observation (already stored and
        already used to mark the episode for preservation)."""
        if not self.active:
            raise RuntimeError(f"recorder is {self.status.value}; cannot record")
        if self._pending is None:
            raise RuntimeError("record_result without a preceding record_action")
        index = self._pending
        self._pending = None
        a = self.actions[index]
        self.actions[index] = RecordedAction(a.sequence_index, a.buttons, a.stick_x, a.stick_y, int(result.consumed_tick))
        events = self._run_detectors(index, self._previous, result.observation)
        self._previous = result.observation
        self.final_observation = result.observation
        return events

    def record_step(self, buttons: int, stick_x: int, stick_y: int, result: StepResult) -> List[AnomalyEvent]:
        """record_action + record_result for callers that already have the result."""
        self.record_action(buttons, stick_x, stick_y)
        return self.record_result(result)

    def preserve(self, reason: PreservationReason | str, note: Optional[str] = None) -> None:
        """Mark this episode for preservation. Any number of reasons may accumulate."""
        value = PreservationReason(reason).value
        self.marks.append(PreservationMark(value, note, len(self.actions)))

    def note_event(self, event: AnomalyEvent) -> None:
        """Store an externally produced event (e.g. from a training-side trigger) and preserve."""
        self.events.append(event)
        self.preserve(PreservationReason.ANOMALY, f"{event.detector}:{event.event} at sequence_index {event.sequence_index}")

    def finish(self, status: EpisodeStatus | str, *, terminal: Optional[Mapping[str, Any]] = None,
               note: Optional[str] = None) -> None:
        """Freeze the recorder with the episode's end status and terminal facts."""
        if not self.active:
            return
        self.status = EpisodeStatus(status)
        self.finish_note = note
        self._wall_s = time.monotonic() - self._t0
        if terminal:
            self.terminal.update(terminal)
        if self.final_observation is not None and "targets_remaining" not in self.terminal:
            o = self.final_observation
            self.terminal.setdefault("targets_remaining", o.targets_remaining if o.btt_active == 1 else None)
            self.terminal.setdefault("input_tick", o.input_tick)
            self.terminal.setdefault("time_passed", o.time_passed)
        if self.actions:
            self.terminal.setdefault("last_consumed_tick", self.actions[-1].consumed_tick)

    def finish_from_step(self, result: StepResult, status: EpisodeStatus | str, *, targets_total: Optional[int] = None,
                         extra: Optional[Mapping[str, Any]] = None) -> None:
        """finish() with the terminal facts taken from the last step result.

        For the native terminal state (EpisodeEnded) the observation of that
        result is the completion snapshot: completion_time_passed and
        completion_input_tick are two clocks sampled together and are stored
        separately; neither is derived from the other."""
        o = result.observation
        terminal: Dict[str, Any] = {
            "state_name": result.state_name,
            "step_count": result.step_count,
            "last_consumed_tick": result.consumed_tick,
            "input_tick": o.input_tick,
            "time_passed": o.time_passed,
            "targets_remaining": o.targets_remaining if o.btt_active == 1 else None,
        }
        if targets_total is not None and o.btt_active == 1:
            terminal["targets_broken"] = int(targets_total) - int(o.targets_remaining)
        if result.state == StepState.EPISODE_ENDED:
            terminal["completion_time_passed"] = o.time_passed
            terminal["completion_input_tick"] = o.input_tick
        if extra:
            terminal.update(extra)
        self.finish(status, terminal=terminal)

    # -- output --------------------------------------------------------------------------------

    def metadata(self) -> Dict[str, Any]:
        return {
            "artifact_schema": ARTIFACT_SCHEMA,
            "format": ARTIFACT_FORMAT,
            "action_contract": NATIVE_ACTION_CONTRACT,
            "source_action_contract": self.source_action_contract,
            "episode_id": self.episode_id,
            "labels": self.labels,
            "preserved": self.preserved,
            "preservation_reasons": [m.to_json() for m in self.marks],
            "action_count": len(self.actions),
            "actions_with_result": sum(1 for a in self.actions if a.consumed_tick is not None),
            "status": (self.status if self.status != EpisodeStatus.ACTIVE else EpisodeStatus.UNKNOWN).value,
            "finish_note": self.finish_note,
            "terminal": self.terminal,
            "anomaly_events": [e.to_json() for e in self.events],
            "detectors": [{"name": d.name, "config": {k: v for k, v in vars(d).items() if not k.startswith("_")}}
                          for d in self.detectors],
            "initial_observation": observation_to_json(self.initial_observation),
            "final_observation": observation_to_json(self.final_observation),
            "diagnostics": {  # operational only: never inputs to replay determinism
                "created_utc": self.created_utc,
                "wall_s": None if self._wall_s is None else round(self._wall_s, 3),
                **self.diagnostics,
            },
        }

    def write(self, root: os.PathLike | str, *, force: bool = False) -> Path:
        """Write <root>/<episode_id>/ with metadata.json and actions.jsonl.

        Refuses an unpreserved episode unless force=True (the caller then
        takes responsibility for keeping an uninteresting run)."""
        if not self.preserved and not force:
            raise RuntimeError("episode is not marked for preservation; call preserve(reason) or discard()")
        directory = Path(root) / self.episode_id
        directory.mkdir(parents=True, exist_ok=False)
        with open(directory / ACTIONS_FILE, "w", encoding="utf-8", newline="\n") as fp:
            for a in self.actions:
                fp.write(json.dumps(a.to_json(), separators=(",", ":")) + "\n")
        tmp = directory / (METADATA_FILE + ".tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as fp:
            json.dump(self.metadata(), fp, indent=2)
            fp.write("\n")
        os.replace(tmp, directory / METADATA_FILE)
        return directory

    def discard(self) -> None:
        """Drop the trajectory. The cost of an uninteresting episode."""
        self.actions = []
        self.events = []
        self.marks = []
        self._previous = None

    # -- internals -----------------------------------------------------------------------------

    def _run_detectors(self, sequence_index: int, previous: Optional[Observation], current: Observation) -> List[AnomalyEvent]:
        raised: List[AnomalyEvent] = []
        tick = self.actions[sequence_index].consumed_tick if 0 <= sequence_index < len(self.actions) else None
        for d in self.detectors:
            for details in d.compare(previous, current):
                event = AnomalyEvent(d.name, d.event_name, sequence_index, tick, dict(details))
                self.events.append(event)
                self.preserve(PreservationReason.ANOMALY, f"{d.name}:{d.event_name} at sequence_index {sequence_index}")
                raised.append(event)
        return raised


def make_episode_id() -> str:
    return f"episode_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"


# -- reading and resubmitting ------------------------------------------------------------------


@dataclass(frozen=True)
class EpisodeArtifact:
    directory: Path
    metadata: Dict[str, Any]
    actions: List[RecordedAction]

    @property
    def episode_id(self) -> str:
        return str(self.metadata.get("episode_id"))


def read_artifact(directory: os.PathLike | str) -> EpisodeArtifact:
    """Read and validate an artifact directory. Raises ArtifactError on any inconsistency."""
    d = Path(directory)
    try:
        with open(d / METADATA_FILE, encoding="utf-8") as fp:
            metadata = json.load(fp)
    except (OSError, ValueError) as exc:
        raise ArtifactError(f"{d / METADATA_FILE}: {exc}") from exc
    if not isinstance(metadata, dict):
        raise ArtifactError(f"{d / METADATA_FILE}: not an object")
    if metadata.get("artifact_schema") != ARTIFACT_SCHEMA:
        raise ArtifactError(f"artifact_schema {metadata.get('artifact_schema')!r}, expected {ARTIFACT_SCHEMA}")
    if metadata.get("action_contract") != NATIVE_ACTION_CONTRACT:
        raise ArtifactError(f"action_contract {metadata.get('action_contract')!r}, expected {NATIVE_ACTION_CONTRACT}")
    actions: List[RecordedAction] = []
    try:
        with open(d / ACTIONS_FILE, encoding="utf-8") as fp:
            for lineno, line in enumerate(fp):
                if not line.strip():
                    continue
                row = json.loads(line)
                a = RecordedAction.from_json(row)
                if a.sequence_index != len(actions):
                    raise ArtifactError(f"{d / ACTIONS_FILE}:{lineno + 1}: sequence_index {a.sequence_index}, expected {len(actions)}")
                actions.append(a)
    except (OSError, ValueError) as exc:
        raise ArtifactError(f"{d / ACTIONS_FILE}: {exc}") from exc
    if metadata.get("action_count") != len(actions):
        raise ArtifactError(f"metadata action_count {metadata.get('action_count')!r} != {len(actions)} rows")
    return EpisodeArtifact(d, metadata, actions)


def resubmit_actions(client: BattleShipClient, actions: Sequence[RecordedAction], *,
                     on_result: Optional[Callable[[RecordedAction, StepResult], None]] = None,
                     stop_at_episode_end: bool = True) -> List[StepResult]:
    """Submit recorded native actions through the raw M1d client, in order.

    Each result's consumed_tick must equal the recorded one where a value was
    recorded (ReplayMismatch otherwise). Stops after a result with state
    EpisodeEnded (M1c is terminal there); remaining actions are not sent."""
    results: List[StepResult] = []
    for a in actions:
        result = client.step(a.buttons, a.stick_x, a.stick_y)
        if a.consumed_tick is not None and result.consumed_tick != a.consumed_tick:
            raise ReplayMismatch(f"sequence_index {a.sequence_index}: consumed_tick {result.consumed_tick}, recorded {a.consumed_tick}")
        results.append(result)
        if on_result is not None:
            on_result(a, result)
        if stop_at_episode_end and result.state == StepState.EPISODE_ENDED:
            break
    return results


# -- Gymnasium wrapper (optional) ---------------------------------------------------------------------

try:
    import gymnasium as _gym
except ImportError:  # pragma: no cover - the raw-client path stays usable without gymnasium
    _gym = None

if _gym is not None:

    def _native_triple(action: Any) -> Optional[tuple]:
        """The exact RLAction triple BattleShipBTTEnv submits for a Gym action (pure conversion)."""
        try:
            from battleship_env import action_to_native  # local import: keeps this module usable without the env
            native = action_to_native(action)
        except Exception:  # noqa: BLE001 - an unconvertible action was never sent
            return None
        return (int(native.buttons), int(native.stick_x), int(native.stick_y))

    class EpisodeRecordingWrapper(_gym.Wrapper):
        """Optional recorder around BattleShipBTTEnv; the environment class is untouched.

        After every env.step() it reads the canonical native triple the
        environment submitted (info["native_action"], the exact RLAction of
        the `step` request) and the paired StepResult (env.last_step_result),
        and feeds them to the current EpisodeRecorder. reset() starts a new
        recorder with the reset observation; a terminated, truncated, failed
        or abandoned episode is finished, handed to `on_episode_end`
        (M5 hook: inspect recorder, call recorder.preserve(...) for best-run
        or periodic reasons, or leave it), then written under artifact_root if
        preserved, otherwise discarded. Anomaly events preserve automatically.

        The wrapper never changes actions, observations, rewards,
        termination or timing; recording cost is a list append and the
        detectors' comparisons per step."""

        def __init__(
            self,
            env: Any,
            artifact_root: os.PathLike | str,
            *,
            detectors: Optional[Iterable[ObservationDetector]] = None,
            labels: Optional[Callable[[], Mapping[str, Any]] | Mapping[str, Any]] = None,
            on_episode_end: Optional[Callable[[EpisodeRecorder], None]] = None,
            targets_total: Optional[int] = None,
        ):
            super().__init__(env)
            self.artifact_root = Path(artifact_root)
            self._detectors = None if detectors is None else list(detectors)
            self._labels = labels
            self.on_episode_end = on_episode_end
            self.targets_total = targets_total
            self.recorder: Optional[EpisodeRecorder] = None
            self.last_artifact_dir: Optional[Path] = None
            self.written: List[Path] = []
            self.discarded = 0

        # -- Gymnasium API -----------------------------------------------------------------------

        def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
            self._close_recorder(EpisodeStatus.ABORTED, note="reset() before the episode ended")
            observation, info = self.env.reset(seed=seed, options=options)
            labels = self._labels() if callable(self._labels) else self._labels
            contract = getattr(self.env.unwrapped, "ENV_CONTRACT", None) or info.get("env_contract")
            self.recorder = EpisodeRecorder(
                source_action_contract=contract,
                labels=labels,
                detectors=self._detectors,
                initial=getattr(self.env.unwrapped, "last_observe", None),
                diagnostics={"pid": info.get("pid"), "port": info.get("port"), "episode_index": info.get("episode_index")},
            )
            return observation, info

        def step(self, action):
            recorder = self.recorder
            if recorder is None or not recorder.active:
                return self.env.step(action)  # not recording: pass through unchanged
            inner = self.env.unwrapped
            before = getattr(inner, "last_step_result", None)
            try:
                observation, reward, terminated, truncated, info = self.env.step(action)
            except Exception as exc:  # noqa: BLE001 - re-raised; the trajectory is preserved first when the episode is over
                if getattr(inner, "phase", None) == "active":
                    # A caller-side rejection (ValueError for an out-of-domain
                    # Gym action, BattleShipEnvError): nothing was sent, the
                    # episode goes on, the recorder is untouched.
                    raise
                # The environment has disposed of the process. If this step's
                # result was collected before the failure (e.g. the terminal
                # EpisodeEnded result followed by an M2 finish() failure), it
                # is paired here so the artifact keeps every consumed action.
                after = getattr(inner, "last_step_result", None)
                if after is not None and after is not before:
                    triple = _native_triple(action)
                    if triple is not None:
                        recorder.record_step(*triple, after)
                outcome = getattr(exc, "outcome", None)
                note = f"{type(exc).__name__}: {getattr(outcome, 'value', outcome) or 'episode failed'}"
                recorder.finish(EpisodeStatus.FAILED, note=note)
                self._end_recorder()
                raise
            native = info.get("native_action")
            result = getattr(inner, "last_step_result", None)
            if native is not None and result is not None:
                recorder.record_step(int(native.buttons), int(native.stick_x), int(native.stick_y), result)
            if terminated:
                assert result is not None
                recorder.finish_from_step(result, EpisodeStatus.TERMINAL, targets_total=self.targets_total,
                                          extra={"exit_code": info.get("exit_code")})
                self._end_recorder()
            elif truncated:
                assert result is not None
                recorder.finish_from_step(result, EpisodeStatus.TRUNCATED, targets_total=self.targets_total,
                                          extra={"truncation_reason": info.get("truncation_reason")})
                self._end_recorder()
            return observation, reward, terminated, truncated, info

        def close(self):
            self._close_recorder(EpisodeStatus.ABORTED, note="close() before the episode ended")
            return self.env.close()

        # -- recorder control ---------------------------------------------------------------------------

        def preserve(self, reason: PreservationReason | str, note: Optional[str] = None) -> None:
            """Mark the current episode (manual, periodic, best-run, ...)."""
            if self.recorder is None:
                raise RuntimeError("no episode is being recorded; call reset() first")
            self.recorder.preserve(reason, note)

        # -- internals ------------------------------------------------------------------------------------

        def _close_recorder(self, status: EpisodeStatus, note: str) -> None:
            if self.recorder is not None and self.recorder.active:
                self.recorder.finish(status, note=note)
                self._end_recorder()

        def _end_recorder(self) -> None:
            recorder = self.recorder
            if recorder is None:
                return
            if self.on_episode_end is not None:
                self.on_episode_end(recorder)
            if recorder.preserved:
                self.last_artifact_dir = recorder.write(self.artifact_root)
                self.written.append(self.last_artifact_dir)
            else:
                recorder.discard()
                self.discarded += 1
