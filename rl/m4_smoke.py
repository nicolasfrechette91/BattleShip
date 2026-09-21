#!/usr/bin/env python3
"""M4 smoke validation of rl/run_artifacts.py: episode artifacts and anomaly recording.

Nothing here trains or optimises. The synthetic cases need no game; the
others launch the real BattleShip (build-us/Release/BattleShip.exe by
default) through the frozen M3 environment and prove the artifact round
trip against the authoritative 7.43 s baseline.

    python rl/m4_smoke.py                            # every case, in order
    python rl/m4_smoke.py detector_synthetic recorder_synthetic   # no game needed

Cases:
  detector_synthetic   position-delta detector on synthetic observation pairs: small movement and the legitimate
                       Mario Up-B magnitude (about 215.525 units) -> no event at the default 250, large one-tick X
                       delta -> event, large Y delta -> event, invalid fighter on either side -> no event (validity
                       is the explicit flag, never inferred from zeros), custom thresholds 10 / 200 / 1000 still
                       work, an event marks the episode for preservation, recording continues after it
  recorder_synthetic   recorder/artifact format without a game: exact native values and consumed ticks survive
                       write -> read, discard writes nothing, every preservation reason is representable,
                       schema/contract validation rejects bad artifacts, labels for M5 are stored verbatim
  wrapper_discard      real game: a bounded random-action episode through EpisodeRecordingWrapper with the
                       default detector is NOT preserved -> nothing written, the trajectory discarded; the
                       wrapper changed nothing about stepping (consumed ticks 0..N-1)
  baseline_roundtrip   real game: the 7.43 s baseline through the wrapper with a manual preservation mark ->
                       artifact with 447 rows, preserved for the manual reason only (the default 250-unit
                       detector must not fire on the legitimate Up-B move at tick 148); read back; resubmitted
                       through a fresh M3 environment AND a fresh raw M1d client: 447 actions, last
                       consumed_tick 446, completion 446 / 447, step_count 447, targets 0, 21 source rows never
                       submitted
  anomaly_live         real game: a deliberately low threshold (1 unit) on a scripted walk raises
                       large_position_delta events from ordinary movement; the episode continues, is
                       preserved automatically and the written artifact holds the COMPLETE trajectory
                       (actions before and after the first event), with the events in metadata.json

Every game case checks that no BattleShip process is left behind. Exit
status: 0 all requested cases passed, 1 otherwise, 2 bad usage.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from battleship_client import Button, Observation, StepResult, StepState  # noqa: E402
from battleship_env import DEFAULT_EXECUTABLE, ENV_CONTRACT, BattleShipBTTEnv, native_to_action  # noqa: E402
from battleship_process import BattleShipEpisode, LaunchConfig  # noqa: E402
from btti_replay import read_btti_rows  # noqa: E402
from m1e_replay_regression import (  # noqa: E402
    COMPLETION_CONSUMED_TICK,
    COMPLETION_INPUT_TICK,
    COMPLETION_STEPS,
    COMPLETION_TIME_PASSED,
    DEFAULT_REPLAY,
    MAX_TARGETS,
    SOURCE_ROWS,
    check_completion,
    check_step,
)
from m2_restart_regression import EXPECTED_RESULT  # noqa: E402
from run_artifacts import (  # noqa: E402
    ACTIONS_FILE,
    ARTIFACT_SCHEMA,
    DEFAULT_POSITION_DELTA_THRESHOLD,
    METADATA_FILE,
    NATIVE_ACTION_CONTRACT,
    AnomalyEvent,
    ArtifactError,
    EpisodeRecorder,
    EpisodeRecordingWrapper,
    EpisodeStatus,
    PositionDeltaDetector,
    PreservationReason,
    RecordedAction,
    read_artifact,
    resubmit_actions,
)


def log(message: str) -> None:
    print(message, flush=True)


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


# -- process accounting -----------------------------------------------------------------


def count_battleship_processes(executable: Path) -> Optional[int]:
    name = executable.name
    try:
        if platform.system() == "Windows":
            out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
                                 capture_output=True, text=True, timeout=15, check=False).stdout
            return sum(1 for line in out.splitlines() if line.startswith(f'"{name}"'))
        out = subprocess.run(["pgrep", "-c", "-x", name], capture_output=True, text=True, timeout=15, check=False).stdout
        return int(out.strip() or 0)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def check_no_leak(before: Optional[int], executable: Path) -> None:
    after = count_battleship_processes(executable)
    if before is not None and after is not None:
        expect(after <= before, f"{executable.name} count rose from {before} to {after}")
    log(f"  {executable.name} processes: before={before} after={after}")


# -- synthetic helpers ---------------------------------------------------------------------


def obs(x: float, y: float, *, valid: int = 1, btt: int = 1, tick: int = 1) -> Observation:
    return Observation(
        observation_schema=1, host_frame=100 + tick, input_tick=tick, time_passed=max(tick - 1, 0), game_status=1,
        btt_active=btt, targets_remaining=10, fighter_valid=valid, position_x=x, position_y=y,
        air_velocity_x=0.0, air_velocity_y=0.0, ground_velocity_x=0.0, facing_direction=-1, ground_air_state=0,
        fighter_status_id=0, jumps_used=0,
    )


def result_for(index: int, observation: Observation, state: StepState = StepState.WAITING_FOR_ACTION) -> StepResult:
    return StepResult(state, "EpisodeEnded" if state == StepState.EPISODE_ENDED else "WaitingForAction",
                      index + 1, index, observation)


# -- cases -----------------------------------------------------------------------------------


def case_detector_synthetic(args: argparse.Namespace) -> None:
    d = PositionDeltaDetector()
    expect(d.threshold == DEFAULT_POSITION_DELTA_THRESHOLD == 250.0, f"default threshold {d.threshold}")
    expect(d.compare(None, obs(0, 0)) == [], "first observation must not raise")
    expect(d.compare(obs(0, 0), obs(150, 0, tick=2)) == [], "150 units in x is below 250")
    expect(d.compare(obs(0, 0), obs(-299.9, 299.9, tick=2)) == [], "299.9 on both axes is below 250")
    # Calibration: about 215.525 units vertically in one tick is legitimate
    # Mario Up-B movement (baseline tick 148) and must not fire by default.
    expect(d.compare(obs(2435.5, 717.0), obs(2431.5, 717.0 + 215.525, tick=2)) == [],
           "the legitimate Mario Up-B one-tick move (about 215.525 units) must be below the default threshold")
    ev = d.compare(obs(0, 0), obs(350, 0, tick=2))
    expect(len(ev) == 1 and ev[0]["axes"] == ["x"] and ev[0]["delta"] == [350.0, 0.0], f"large x: {ev}")
    ev = d.compare(obs(0, 0), obs(0, -400, tick=2))
    expect(len(ev) == 1 and ev[0]["axes"] == ["y"] and ev[0]["delta"] == [0.0, -400.0], f"large y: {ev}")
    ev = d.compare(obs(100, 100), obs(-250, 500, tick=2))
    expect(len(ev) == 1 and ev[0]["axes"] == ["x", "y"], f"both axes: {ev}")
    expect(ev[0]["threshold"] == 250.0 and ev[0]["previous_position"] == [100.0, 100.0]
           and ev[0]["current_position"] == [-250.0, 500.0], f"event evidence incomplete: {ev[0]}")
    expect(d.event_name == "large_position_delta", f"event name must stay descriptive: {d.event_name}")
    # Explicit validity: a zero position with fighter_valid 0 is not "at the origin".
    expect(d.compare(obs(0, 0, valid=0), obs(900, 0, tick=2)) == [], "previous invalid fighter must not compare")
    expect(d.compare(obs(900, 0), obs(0, 0, valid=0, tick=2)) == [], "current invalid fighter must not compare")
    expect(d.compare(obs(900, 0, btt=0), obs(0, 0, tick=2)) == [], "btt inactive must not compare")
    # Configurable threshold: custom values keep working beside the default.
    tight = PositionDeltaDetector(threshold=10.0)
    expect(tight.compare(obs(0, 0), obs(11, 0, tick=2))[0]["threshold"] == 10.0, "tight threshold not applied")
    old = PositionDeltaDetector(threshold=200.0)
    expect(old.compare(obs(0, 0), obs(0, 215.525, tick=2))[0]["threshold"] == 200.0,
           "a custom 200 threshold must still fire on a 215.525 move")
    expect(PositionDeltaDetector(threshold=1000.0).compare(obs(0, 0), obs(600, 600, tick=2)) == [], "loose threshold")
    for bad in (0, -1):
        try:
            PositionDeltaDetector(threshold=bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"threshold {bad} accepted")
    log("  default 250: small/299.9/Up-B 215.525 -> no event; 350 x/-400 y/both axes -> event; invalid fighter and "
        "inactive btt -> no comparison; custom thresholds 10, 200 and 1000 applied; 0 and -1 rejected")

    # An event marks the episode; recording continues; the artifact holds everything.
    rec = EpisodeRecorder(source_action_contract=ENV_CONTRACT, initial=None, detectors=[PositionDeltaDetector(200.0)])
    expect(not rec.preserved, "fresh recorder must not be preserved")
    rec.record_step(0, 0, 0, result_for(0, obs(0, -2547, tick=1)))
    rec.record_step(0, -60, 0, result_for(1, obs(-30, -2547, tick=2)))
    raised = rec.record_step(0, -60, 0, result_for(2, obs(-330, -2547, tick=3)))
    expect(len(raised) == 1 and raised[0].event == "large_position_delta" and raised[0].sequence_index == 2
           and raised[0].tick == 2, f"event {raised}")
    expect(rec.preserved and rec.marks[0].reason == "anomaly", f"anomaly must preserve: {rec.marks}")
    for i in range(3, 8):  # the episode goes on; nothing is rejected or changed
        rec.record_step(int(Button.B), 40, -40, result_for(i, obs(-330 + i, -2547, tick=i + 1)))
    rec.finish_from_step(result_for(7, obs(-323, -2547, tick=8)), EpisodeStatus.TRUNCATED, targets_total=10)
    directory = rec.write(args.run_root)
    art = read_artifact(directory)
    expect(len(art.actions) == 8 and art.actions[7] == RecordedAction(7, int(Button.B), 40, -40, 7),
           f"complete trajectory expected: {art.actions}")
    expect(art.metadata["anomaly_events"][0]["event"] == "large_position_delta"
           and art.metadata["anomaly_events"][0]["details"]["delta"] == [-250.0, 0.0], "event not stored")
    expect("glitch" not in json.dumps(art.metadata).lower(), "artifact must not label the event a glitch")
    log(f"  event at sequence_index 2 preserved the run; 5 further actions recorded; artifact {directory.name} has all 8 rows")


def case_recorder_synthetic(args: argparse.Namespace) -> None:
    labels = {"episode_number": 1234, "checkpoint_label": "ppo_step_00100000", "best_targets_broken": 7,
              "best_completion_time_passed": None}
    initial = None
    rec = EpisodeRecorder(episode_id="synthetic_roundtrip", source_action_contract=ENV_CONTRACT, labels=labels,
                          initial=initial, diagnostics={"pid": 4242, "port": 5555})
    triples = [(int(Button.NONE), 0, 0), (int(Button.A), -80, 80), (int(Button.C_UP), 127, -128),
               (int(Button.Z), 1, -1), (int(Button.B), 0, 0)]
    for i, (b, x, y) in enumerate(triples):
        rec.record_step(b, x, y, result_for(i, obs(float(i), float(-i), tick=i + 1)))
    rec.preserve(PreservationReason.MANUAL, "smoke")
    rec.preserve("periodic_milestone", "every 100 episodes")
    rec.preserve(PreservationReason.NEW_BEST_TARGET_COUNT)
    rec.preserve(PreservationReason.NEW_FASTEST_COMPLETED_RUN)
    rec.preserve(PreservationReason.MAJOR_PERFORMANCE_IMPROVEMENT)
    rec.finish_from_step(result_for(4, obs(4.0, -4.0, tick=5, ), StepState.EPISODE_ENDED), EpisodeStatus.TERMINAL,
                         targets_total=10, extra={"exit_code": 0})
    directory = rec.write(args.run_root)
    expect((directory / METADATA_FILE).is_file() and (directory / ACTIONS_FILE).is_file(), "files missing")
    art = read_artifact(directory)
    m = art.metadata
    expect(m["artifact_schema"] == ARTIFACT_SCHEMA and m["action_contract"] == NATIVE_ACTION_CONTRACT
           and m["source_action_contract"] == ENV_CONTRACT, f"contracts: {m}")
    expect([(a.buttons, a.stick_x, a.stick_y, a.consumed_tick) for a in art.actions]
           == [(b, x, y, i) for i, (b, x, y) in enumerate(triples)], "native values or consumed ticks changed")
    expect(m["labels"] == labels, "labels not stored verbatim")
    expect([r["reason"] for r in m["preservation_reasons"]]
           == ["manual", "periodic_milestone", "new_best_target_count", "new_fastest_completed_run",
               "major_performance_improvement"], f"reasons {m['preservation_reasons']}")
    expect(m["status"] == "terminal" and m["terminal"]["completion_time_passed"] == 4
           and m["terminal"]["completion_input_tick"] == 5 and m["terminal"]["last_consumed_tick"] == 4, f"terminal {m['terminal']}")
    expect(m["action_count"] == 5 and m["actions_with_result"] == 5, "counts")
    expect("rng" not in json.dumps(m).lower() and "seed" not in json.dumps(m).lower(), "no RNG metadata allowed")
    expect(m["diagnostics"]["pid"] == 4242 and "created_utc" in m["diagnostics"], "diagnostics")
    raw_rows = (directory / ACTIONS_FILE).read_text(encoding="utf-8").splitlines()
    expect(json.loads(raw_rows[2]) == {"sequence_index": 2, "buttons": 8, "stick_x": 127, "stick_y": -128, "consumed_tick": 2},
           f"row shape {raw_rows[2]}")
    log(f"  write/read exact over {len(triples)} native triples incl. int8 limits; all six reasons representable; metadata complete")

    # Uninteresting episode: discarded, nothing written, refuses to write.
    boring = EpisodeRecorder(episode_id="synthetic_boring", source_action_contract=ENV_CONTRACT)
    for i in range(3):
        boring.record_step(0, 0, 0, result_for(i, obs(0, 0, tick=i + 1)))
    boring.finish(EpisodeStatus.TRUNCATED)
    expect(not boring.preserved, "unmarked episode must not be preserved")
    try:
        boring.write(args.run_root)
    except RuntimeError:
        pass
    else:
        raise AssertionError("write() of an unpreserved episode must be refused")
    boring.discard()
    expect(boring.action_count == 0 and not (Path(args.run_root) / "synthetic_boring").exists(), "discard left data")
    log("  unpreserved episode: write refused, discard() dropped the trajectory, no directory created")

    # Validation of bad artifacts.
    bad = Path(tempfile.mkdtemp(prefix="bad_", dir=str(args.run_root)))
    (bad / ACTIONS_FILE).write_text('{"sequence_index":0,"buttons":0,"stick_x":0,"stick_y":0,"consumed_tick":0}\n', encoding="utf-8")
    (bad / METADATA_FILE).write_text(json.dumps({"artifact_schema": 99, "action_contract": NATIVE_ACTION_CONTRACT, "action_count": 1}), encoding="utf-8")
    for label, meta in (("schema 99", {"artifact_schema": 99, "action_contract": NATIVE_ACTION_CONTRACT, "action_count": 1}),
                        ("wrong contract", {"artifact_schema": 1, "action_contract": "other", "action_count": 1}),
                        ("count mismatch", {"artifact_schema": 1, "action_contract": NATIVE_ACTION_CONTRACT, "action_count": 2})):
        (bad / METADATA_FILE).write_text(json.dumps(meta), encoding="utf-8")
        try:
            read_artifact(bad)
        except ArtifactError:
            pass
        else:
            raise AssertionError(f"{label} accepted")
    log("  read_artifact rejects wrong schema, wrong contract and row-count mismatch")


def make_env(args: argparse.Namespace, **overrides: Any) -> BattleShipBTTEnv:
    fields: Dict[str, Any] = dict(executable=Path(args.exe), run_root=args.run_root, startup_timeout=args.startup_timeout,
                                  ready_timeout=args.ready_timeout, request_timeout=args.request_timeout,
                                  exit_timeout=args.exit_timeout)
    max_steps = overrides.pop("max_episode_steps", None)
    fields.update(overrides)
    return BattleShipBTTEnv(LaunchConfig(**fields), max_episode_steps=max_steps)


def case_wrapper_discard(args: argparse.Namespace) -> None:
    before = count_battleship_processes(Path(args.exe))
    artifacts = Path(tempfile.mkdtemp(prefix="artifacts_discard_", dir=str(args.run_root)))
    env = EpisodeRecordingWrapper(make_env(args, max_episode_steps=args.random_steps), artifacts, targets_total=MAX_TARGETS)
    seen_end: List[EpisodeRecorder] = []
    snapshots: List[Dict[str, Any]] = []

    def at_end(rec: EpisodeRecorder) -> None:
        # The wrapper discards an unpreserved recorder right after this hook,
        # so the trajectory is inspected here, at the M5 decision point.
        seen_end.append(rec)
        snapshots.append({"status": rec.status, "action_count": rec.action_count,
                          "ticks_ok": all(a.consumed_tick == a.sequence_index for a in rec.actions),
                          "events": list(rec.events), "preserved": rec.preserved})

    env.on_episode_end = at_end
    try:
        observation, info = env.reset(seed=args.seed)
        env.action_space.seed(args.seed)
        expect(env.recorder is not None and env.recorder.active and env.recorder.initial_observation is not None,
               "recorder not started with the reset observation")
        expect(env.recorder.initial_observation.input_tick == 0, "initial observation is not the pre-tick-0 snapshot")
        t0 = time.monotonic()
        for i in range(args.random_steps):
            if i == 5:
                # A caller-side rejection (out-of-domain Gym action) is not an
                # episode failure: nothing is sent and recording must go on.
                try:
                    env.step({"button": 0, "stick_x": 81, "stick_y": 0})
                except ValueError:
                    pass
                else:
                    raise AssertionError("stick_x 81 must be rejected by the M3 action domain")
                expect(env.recorder is not None and env.recorder.active and env.recorder.action_count == 5,
                       "a rejected action must leave the recorder active and unchanged")
            action = env.action_space.sample()
            observation, reward, terminated, truncated, info = env.step(action)
            expect(info["consumed_tick"] == i and int(observation["input_tick"]) == i + 1, f"pairing broken at {i}")
            expect(not terminated, "random actions must not clear the stage in this bound")
        wall = time.monotonic() - t0
        expect(truncated, "expected truncation at the bound")
        expect(len(snapshots) == 1 and snapshots[0]["status"] == EpisodeStatus.TRUNCATED, "on_episode_end not called with truncated")
        snap = snapshots[0]
        expect(snap["action_count"] == args.random_steps and snap["ticks_ok"],
               f"recorded trajectory does not match the consumed ticks: {snap}")
        events = snap["events"]
        if events:
            # A default-threshold event preserves the run by design; this case
            # only proves the discard path, so it needs an event-free episode.
            log("  NOTE: default-threshold events on this random episode (recorded, not judged):")
            for e in events:
                log(f"    {e.event} sequence_index={e.sequence_index} tick={e.tick} delta={e.details['delta']}")
            expect(snap["preserved"] and len(env.written) == 1, "an event must preserve the episode")
            log(f"  {args.random_steps} random steps in {wall:.1f}s: preserved for 'anomaly' (discard path not exercised on this seed)")
        else:
            expect(not snap["preserved"], "an event-free unmarked episode must not be preserved")
            expect(env.discarded == 1 and env.written == [] and not any(artifacts.iterdir()), "an unpreserved episode was written")
            expect(seen_end[0].action_count == 0, "discard() did not drop the trajectory")
            log(f"  {args.random_steps} random steps in {wall:.1f}s with the default detector "
                f"({DEFAULT_POSITION_DELTA_THRESHOLD:g} units): no events; not preserved -> discarded, nothing written "
                f"under {artifacts.name}")
    finally:
        env.close()
    check_no_leak(before, Path(args.exe))


def feed_baseline_through_env(env: Any, rows: Sequence[Any], after_reset: Optional[Callable[[], None]] = None) -> Dict[str, Any]:
    observation, info = env.reset()
    if after_reset is not None:
        after_reset()
    pid = info["pid"]
    previous = None
    sent = 0
    terminated = truncated = False
    for row_index, row in enumerate(rows):
        observation, reward, terminated, truncated, info = env.step(native_to_action(row.buttons, row.stick_x, row.stick_y))
        sent += 1
        result = env.unwrapped.last_step_result
        check_step(row_index, result, previous)
        previous = result.observation
        if terminated:
            check_completion(row_index, result)
            break
    expect(terminated and not truncated, "baseline did not terminate natively")
    for key, value in EXPECTED_RESULT.items():
        expect(info["result"].get(key) == value, f"result JSON {key} is {info['result'].get(key)!r}, expected {value!r}")
    return {"pid": pid, "sent": sent, "last_consumed_tick": info["consumed_tick"], "input_tick": int(observation["input_tick"]),
            "time_passed": int(observation["time_passed"]), "targets_remaining": int(observation["targets_remaining"]),
            "step_count": info["step_count"], "exit_code": info["exit_code"]}


def expect_baseline(values: Dict[str, Any], label: str) -> None:
    expect(values["sent"] == COMPLETION_STEPS and values["step_count"] == COMPLETION_STEPS, f"{label}: steps {values}")
    expect(values["last_consumed_tick"] == COMPLETION_CONSUMED_TICK, f"{label}: last consumed_tick {values}")
    expect(values["input_tick"] == COMPLETION_INPUT_TICK, f"{label}: completion input_tick {values}")
    expect(values["time_passed"] == COMPLETION_TIME_PASSED, f"{label}: completion time_passed {values}")
    expect(values["targets_remaining"] == 0, f"{label}: targets remain {values}")
    log(f"  {label}: pid={values['pid']} actions={values['sent']} last_consumed_tick={values['last_consumed_tick']} "
        f"completion_time_passed={values['time_passed']} completion_input_tick={values['input_tick']} "
        f"step_count={values['step_count']} targets_remaining={values['targets_remaining']} "
        f"exit_code={values.get('exit_code')} rows_unsent={SOURCE_ROWS - values['sent']}")


def case_baseline_roundtrip(args: argparse.Namespace) -> None:
    before = count_battleship_processes(Path(args.exe))
    rows = read_btti_rows(args.replay)
    expect(len(rows) == SOURCE_ROWS, f"{len(rows)} replay rows, expected {SOURCE_ROWS}")
    artifacts = Path(tempfile.mkdtemp(prefix="artifacts_baseline_", dir=str(args.run_root)))

    # 1. Capture: the baseline through the M3 wrapper, marked manually right after reset().
    env = EpisodeRecordingWrapper(make_env(args), artifacts, targets_total=MAX_TARGETS,
                                  labels={"episode_number": 0, "checkpoint_label": "scripted_baseline_7.43"})
    try:
        captured = feed_baseline_through_env(env, rows, after_reset=lambda: env.preserve(
            PreservationReason.MANUAL, "M4 smoke: tracked 7.43 s baseline"))
        expect_baseline(captured, "capture (M3 wrapper)")
        expect(len(env.written) == 1 and env.last_artifact_dir is not None, f"artifact not written: {env.written}")
        artifact_dir = env.last_artifact_dir
    finally:
        env.close()
    check_no_leak(before, Path(args.exe))

    # 2. Read back and check the metadata against the authoritative values.
    art = read_artifact(artifact_dir)
    m = art.metadata
    expect(len(art.actions) == COMPLETION_STEPS, f"{len(art.actions)} rows, expected {COMPLETION_STEPS}")
    expect([(a.buttons, a.stick_x, a.stick_y) for a in art.actions] == [(r.buttons, r.stick_x, r.stick_y) for r in rows[:COMPLETION_STEPS]],
           "recorded native values differ from the submitted replay rows")
    expect([a.consumed_tick for a in art.actions] == list(range(COMPLETION_STEPS)), "consumed ticks are not 0..446")
    expect(m["status"] == "terminal" and m["terminal"]["completion_time_passed"] == COMPLETION_TIME_PASSED
           and m["terminal"]["completion_input_tick"] == COMPLETION_INPUT_TICK and m["terminal"]["step_count"] == COMPLETION_STEPS
           and m["terminal"]["last_consumed_tick"] == COMPLETION_CONSUMED_TICK and m["terminal"]["targets_remaining"] == 0
           and m["terminal"]["targets_broken"] == MAX_TARGETS and m["terminal"]["exit_code"] == 0, f"terminal metadata {m['terminal']}")
    expect(m["preservation_reasons"][0]["reason"] == "manual" and m["source_action_contract"] == ENV_CONTRACT
           and m["labels"]["checkpoint_label"] == "scripted_baseline_7.43", "metadata fields")
    # Calibration expectation: the default threshold (250) was set above the
    # legitimate Mario Up-B move of about 215.525 units at baseline tick 148
    # (which the earlier 200 default recorded), so the baseline must now be
    # preserved for the manual reason alone. Any event is printed in full.
    reasons = [r["reason"] for r in m["preservation_reasons"]]
    for e in m["anomaly_events"]:
        d = e["details"]
        log(f"  default-threshold event on the baseline: {e['event']} sequence_index={e['sequence_index']} "
            f"tick={e['tick']} axes={d['axes']} delta={d['delta']} positions {d['previous_position']} -> {d['current_position']} "
            f"status {d['previous_fighter_status_id']}->{d['current_fighter_status_id']} air={d['current_ground_air_state']}")
    expect(m["detectors"] == [{"name": "position_delta", "config": {"threshold": DEFAULT_POSITION_DELTA_THRESHOLD}}],
           f"baseline capture must use the default detector: {m['detectors']}")
    expect(m["anomaly_events"] == [] and reasons == ["manual"],
           f"the baseline must not trigger the default {DEFAULT_POSITION_DELTA_THRESHOLD:g}-unit detector "
           f"(Mario Up-B at tick 148 is about 215.525 units): events={m['anomaly_events']} reasons={reasons}")
    log(f"  artifact {artifact_dir.name}: {len(art.actions)} rows, terminal {m['terminal']['completion_time_passed']}/"
        f"{m['terminal']['completion_input_tick']}, events={len(m['anomaly_events'])} (default threshold "
        f"{DEFAULT_POSITION_DELTA_THRESHOLD:g}; Up-B at tick 148 below it), reasons={reasons}, "
        f"rows_unsent={SOURCE_ROWS - len(art.actions)}")

    # 3. Replay through a fresh M3 environment (Gym path), from the artifact's rows only.
    env2 = make_env(args)
    try:
        observation, info = env2.reset()
        previous = None
        sent = 0
        terminated = truncated = False
        for a in art.actions:
            observation, reward, terminated, truncated, info = env2.step(native_to_action(a.buttons, a.stick_x, a.stick_y))
            sent += 1
            result = env2.last_step_result
            check_step(a.sequence_index, result, previous)
            expect(result.consumed_tick == a.consumed_tick, f"row {a.sequence_index}: consumed_tick {result.consumed_tick} != recorded {a.consumed_tick}")
            previous = result.observation
            if terminated:
                check_completion(a.sequence_index, result)
                break
        expect(terminated, "artifact replay through the env did not terminate")
        for key, value in EXPECTED_RESULT.items():
            expect(info["result"].get(key) == value, f"env replay result JSON {key} is {info['result'].get(key)!r}")
        expect_baseline({"pid": info["pid"], "sent": sent, "last_consumed_tick": info["consumed_tick"],
                         "input_tick": int(observation["input_tick"]), "time_passed": int(observation["time_passed"]),
                         "targets_remaining": int(observation["targets_remaining"]), "step_count": info["step_count"],
                         "exit_code": info["exit_code"]}, "replay (M3 env from artifact)")
    finally:
        env2.close()
    check_no_leak(before, Path(args.exe))

    # 4. Replay through a fresh raw M1d client (M2 process + resubmit_actions).
    config = LaunchConfig(executable=Path(args.exe), run_root=args.run_root, startup_timeout=args.startup_timeout,
                          ready_timeout=args.ready_timeout, request_timeout=args.request_timeout, exit_timeout=args.exit_timeout)
    with BattleShipEpisode(config, index=901) as episode:
        fresh = episode.start()
        expect(fresh.step_count == 0, "raw replay process not fresh")
        assert episode.client is not None
        previous_obs: List[Optional[Observation]] = [None]

        def check(a: RecordedAction, r: StepResult) -> None:
            check_step(a.sequence_index, r, previous_obs[0])
            previous_obs[0] = r.observation

        results = resubmit_actions(episode.client, art.actions, on_result=check)
        terminal = results[-1]
        expect(terminal.state == StepState.EPISODE_ENDED, f"raw replay did not end: {terminal.state_name}")
        check_completion(len(results) - 1, terminal)
        done = episode.finish(terminal)
        for key, value in EXPECTED_RESULT.items():
            expect(done.result.get(key) == value, f"raw replay result JSON {key} is {done.result.get(key)!r}")
        expect_baseline({"pid": episode.pid, "sent": len(results), "last_consumed_tick": terminal.consumed_tick,
                         "input_tick": terminal.observation.input_tick, "time_passed": terminal.observation.time_passed,
                         "targets_remaining": terminal.observation.targets_remaining, "step_count": terminal.step_count,
                         "exit_code": done.exit_code}, "replay (raw M1d client from artifact)")
    check_no_leak(before, Path(args.exe))


def case_anomaly_live(args: argparse.Namespace) -> None:
    """A low threshold turns ordinary walking into recorded events; nothing about the episode changes."""
    before = count_battleship_processes(Path(args.exe))
    artifacts = Path(tempfile.mkdtemp(prefix="artifacts_anomaly_", dir=str(args.run_root)))
    steps = 40
    env = EpisodeRecordingWrapper(make_env(args, max_episode_steps=steps), artifacts,
                                  detectors=[PositionDeltaDetector(threshold=args.live_threshold)], targets_total=MAX_TARGETS)
    try:
        observation, info = env.reset()
        first_event_index: Optional[int] = None
        for i in range(steps):
            # Walk left on the enclosed start floor (walls on both sides, no edge): stick x = -60, no buttons.
            observation, reward, terminated, truncated, info = env.step({"button": 0, "stick_x": -60, "stick_y": 0})
            expect(info["consumed_tick"] == i, f"pairing broken at {i}")
            expect(not terminated, "walking must not clear the stage")
            assert env.recorder is not None or truncated
            if first_event_index is None and env.recorder is not None and env.recorder.events:
                first_event_index = env.recorder.events[0].sequence_index
            if first_event_index is None and truncated:
                break
        expect(truncated, "expected truncation at the bound")
        expect(len(env.written) == 1, f"anomaly episode must be written once: {env.written}")
        art = read_artifact(env.written[0])
        m = art.metadata
        events = m["anomaly_events"]
        expect(len(events) >= 1 and events[0]["event"] == "large_position_delta", f"no event recorded: {events[:1]}")
        expect(all(e["details"]["threshold"] == float(args.live_threshold) for e in events), "threshold not recorded")
        expect(len(art.actions) == steps and art.actions[-1].consumed_tick == steps - 1, "trajectory incomplete after the event")
        expect(events[0]["sequence_index"] < steps - 1, "the episode must continue after the first event")
        expect(m["preservation_reasons"][0]["reason"] == "anomaly" and m["status"] == "truncated", f"{m['preservation_reasons']} {m['status']}")
        log(f"  threshold {args.live_threshold} unit(s): {len(events)} large_position_delta event(s), first at sequence_index "
            f"{events[0]['sequence_index']} (delta {events[0]['details']['delta']}); episode continued to {steps} steps; "
            f"artifact holds all {len(art.actions)} rows; preserved for reason 'anomaly'")
    finally:
        env.close()
    check_no_leak(before, Path(args.exe))


CASES: Dict[str, Callable[[argparse.Namespace], None]] = {
    "detector_synthetic": case_detector_synthetic,
    "recorder_synthetic": case_recorder_synthetic,
    "wrapper_discard": case_wrapper_discard,
    "baseline_roundtrip": case_baseline_roundtrip,
    "anomaly_live": case_anomaly_live,
}
GAME_CASES = {"wrapper_discard", "baseline_roundtrip", "anomaly_live"}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cases", nargs="*", choices=sorted(CASES), help="cases to run, in order (default: all)")
    parser.add_argument("--exe", default=str(DEFAULT_EXECUTABLE))
    parser.add_argument("--run-dir", default=None, help="parent of episode and artifact directories (default: a new temp dir)")
    parser.add_argument("--replay", default=str(DEFAULT_REPLAY))
    parser.add_argument("--random-steps", type=int, default=60)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--live-threshold", type=float, default=1.0, help="position-delta threshold of anomaly_live (default: %(default)s)")
    parser.add_argument("--startup-timeout", type=float, default=60.0)
    parser.add_argument("--ready-timeout", type=float, default=180.0)
    parser.add_argument("--request-timeout", type=float, default=30.0)
    parser.add_argument("--exit-timeout", type=float, default=30.0)
    args = parser.parse_args(argv)
    names = list(dict.fromkeys(args.cases)) or list(CASES)
    args.run_root = Path(args.run_dir) if args.run_dir else Path(tempfile.mkdtemp(prefix="battleship_m4_smoke_"))
    args.run_root.mkdir(parents=True, exist_ok=True)
    if any(name in GAME_CASES for name in names) and not Path(args.exe).is_file():
        log(f"ERROR: executable not found: {args.exe}")
        return 2
    baseline = count_battleship_processes(Path(args.exe))
    log(f"{Path(args.exe).name} processes before the run: {baseline}")
    failures = 0
    for name in names:
        log(f"[{name}]")
        started = time.monotonic()
        try:
            CASES[name](args)
        except Exception as exc:  # noqa: BLE001 - report every failure kind
            failures += 1
            log(f"FAIL {name} ({time.monotonic() - started:.1f}s): {exc}")
            traceback.print_exc()
        else:
            log(f"PASS {name} ({time.monotonic() - started:.1f}s)")
    final = count_battleship_processes(Path(args.exe))
    log(f"{Path(args.exe).name} processes after the run: {final}")
    if baseline is not None and final is not None and final > baseline:
        failures += 1
        log("FAIL cleanup: BattleShip process count rose during the run")
    log(f"run_dir={args.run_root}")
    log(f"M4 {'PASS' if failures == 0 else 'FAIL'} cases={len(names)} failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
