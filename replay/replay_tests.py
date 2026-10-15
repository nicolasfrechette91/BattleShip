#!/usr/bin/env python3
"""Offline tests for the replay tools: no BattleShip process, no access to runs/.

    python replay/replay_tests.py

Every fixture is built in a temporary directory; the real index
(replay/_local/index.sqlite) and verdict log are never opened. The action-state
test reads the decomp status headers (read only); the panel test opens a
withdrawn Tk window. Exit code 0 when every test passes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import replay_index as ri  # noqa: E402
from replay_episode import (EpisodeError, ReplayTracker, action_digest, button_name, compare, load_episode,  # noqa: E402
                            recorded_end, stick_arrow)

TESTS: List[Callable[[], None]] = []


def test(fn: Callable[[], None]) -> Callable[[], None]:
    TESTS.append(fn)
    return fn


def obs(**kw: Any) -> Dict[str, Any]:
    base = {"observation_schema": 1, "host_frame": 64, "input_tick": 0, "time_passed": 0, "game_status": 1,
            "btt_active": 1, "targets_remaining": 10, "fighter_valid": 1, "position_x": 0.0, "position_y": -2550.0,
            "air_velocity_x": 0.0, "air_velocity_y": 0.0, "ground_velocity_x": 0.0, "facing_direction": -1,
            "ground_air_state": 0, "fighter_status_id": 10, "jumps_used": 0}
    base.update(kw)
    return base


def write_episode(d: Path, rows: List[Dict[str, Any]], *, labels: Dict[str, Any], terminal: Dict[str, Any],
                  final: Dict[str, Any], digest: Optional[str] = None) -> Path:
    d.mkdir(parents=True)
    with open(d / "actions.jsonl", "w", encoding="utf-8", newline="\n") as fp:
        for r in rows:
            fp.write(json.dumps(r) + "\n")
    from replay_episode import Row

    labels = dict(labels)
    labels.setdefault("native_action_digest", digest or action_digest(
        [Row(r["sequence_index"], r["buttons"], r["stick_x"], r["stick_y"], r["consumed_tick"]) for r in rows]))
    meta = {"artifact_schema": 1, "format": "battleship_btt_episode", "action_contract": "rlaction_native_v1",
            "episode_id": d.name, "labels": labels, "action_count": len(rows), "terminal": terminal,
            "initial_observation": obs(), "final_observation": final,
            "diagnostics": {"created_utc": "2026-09-29T00:00:00+00:00"}}
    with open(d / "metadata.json", "w", encoding="utf-8", newline="\n") as fp:
        json.dump(meta, fp)
    return d


def rows_of(n: int) -> List[Dict[str, Any]]:
    return [{"sequence_index": i, "buttons": 0x8000 if i % 2 else 0, "stick_x": -80, "stick_y": 0, "consumed_tick": i}
            for i in range(n)]


def age(path: Path, seconds: float = 3600.0) -> None:
    """Backdate a directory and its files (the scan skips recently modified episodes)."""
    t = time.time() - seconds
    for p in [*path.rglob("*"), path]:
        os.utime(p, (t, t))


def fall_episode(d: Path) -> Path:
    final = obs(input_tick=3, time_passed=2, game_status=5, targets_remaining=8, position_x=-2200.0)
    return write_episode(d, rows_of(3), labels={"role": "evaluation", "end_reason": "fall",
                                                "termination_reason": "native_failure", "targets_broken": 2},
                         terminal={"step_count": 3, "last_consumed_tick": 2, "targets_broken": 2}, final=final)


def feed(tr: ReplayTracker, ep, finals: List[Dict[str, Any]], state: str = "WaitingForAction") -> None:
    tr.feed_initial(obs())
    for i, (row, o) in enumerate(zip(ep.replay_rows, finals)):
        tr.feed_step(row, state if i == len(finals) - 1 else "WaitingForAction", i + 1, row.consumed_tick, o)


# -- replay_episode ------------------------------------------------------------------------------------------------


@test
def names_and_arrows() -> None:
    assert button_name(0) == "none" and button_name(0x8000) == "A" and button_name(0x0008) == "C-up"
    assert button_name(0x0002) == "C-left" and button_name(0x2000) == "Z" and button_name(0x8000 | 0x4000) == "A+B"
    assert stick_arrow(0, 0) == "·" and stick_arrow(80, 0) == "→" and stick_arrow(-80, 80) == "↖"
    assert stick_arrow(0, -80) == "↓" and stick_arrow(80, -80) == "↘"


@test
def recorded_end_kinds() -> None:
    assert recorded_end({"labels": {"cleared": True, "termination_reason": "native_clear"}})[0] == "clear"
    assert recorded_end({"labels": {"termination_reason": "native_failure", "end_reason": "fall"}})[0] == "fall"
    assert recorded_end({"labels": {"end_reason": "horizon", "truncation_reason": "max_episode_steps"}})[0] == "truncated"
    assert recorded_end({"labels": {"end_reason": "horizon", "truncation_reason": "goal_reached"}})[0] == "truncated"
    assert recorded_end({"terminal": {"end_reason": "clear", "ticks": 2351}}) == ("clear", "end_reason=clear")  # M9
    assert recorded_end({})[0] == "unknown"


@test
def fall_match_and_desyncs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ep = load_episode(fall_episode(Path(tmp) / "episode_x_fall"))
        good = [obs(input_tick=1, time_passed=0, targets_remaining=9), obs(input_tick=2, time_passed=1, targets_remaining=8),
                ep.metadata["final_observation"]]
        tr = ReplayTracker(ep)
        feed(tr, ep, good)
        v = compare(tr)
        assert tr.end_kind == "fall" and v.match, v.lines()
        assert tr.trajectory.target_break_ticks == [0, 1]
        assert tr.trajectory.first_left_entry == {"consumed_tick": 2, "x": -2200.0, "y": -2550.0}
        # a different final position is a DESYNC
        tr = ReplayTracker(ep)
        feed(tr, ep, good[:2] + [dict(good[2], position_x=-2199.5)])
        v = compare(tr)
        assert not v.match and [c.name for c in v.failures()] == ["final observation (host_frame excluded)"], v.lines()
        assert v.failures()[0].rows == [("position_x", -2200.0, -2199.5)]  # the table's rows, full precision
        assert v.failures()[0].got == "position_x: -2200.0 vs -2199.5"  # the CLI / verdict log text is unchanged
        # a fall one tick early (more rows remain) is a DESYNC on end/steps
        tr = ReplayTracker(ep)
        feed(tr, ep, [good[0], dict(good[2], input_tick=2, time_passed=1)])
        v = compare(tr)
        assert tr.end_kind == "fall" and not v.match
        assert {"steps", "fall tick (last consumed)"} <= {c.name for c in v.failures()}, v.lines()
        # host_frame differences never count
        tr = ReplayTracker(ep)
        feed(tr, ep, good[:2] + [dict(good[2], host_frame=999)])
        assert compare(tr).match


@test
def clock_mismatch_is_desync() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ep = load_episode(fall_episode(Path(tmp) / "episode_x_clock"))
        tr = ReplayTracker(ep)
        tr.feed_initial(obs())
        row = ep.replay_rows[0]
        tr.feed_step(row, "WaitingForAction", 1, 5, obs(input_tick=6))  # the game answered for another tick
        assert tr.first_mismatch and "consumed_tick 5" in tr.first_mismatch
        assert not compare(tr).match


@test
def clear_and_digest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        final = obs(input_tick=2, time_passed=1, targets_remaining=0, game_status=1)
        d = write_episode(Path(tmp) / "episode_x_clear", rows_of(2),
                          labels={"cleared": True, "termination_reason": "native_clear", "end_reason": "clear",
                                  "targets_broken": 10, "completion_time_passed": 1, "completion_input_tick": 2},
                          terminal={"step_count": 2, "last_consumed_tick": 1, "targets_broken": 10}, final=final)
        ep = load_episode(d / "actions.jsonl")  # the actions.jsonl path is accepted too
        tr = ReplayTracker(ep)
        feed(tr, ep, [obs(input_tick=1, targets_remaining=5), final], state="EpisodeEnded")
        v = compare(tr)
        assert tr.end_kind == "clear" and v.match, v.lines()
        names = {c.name for c in v.checks}
        assert {"completion time_passed", "completion input_tick"} <= names
        # a tampered actions.jsonl no longer matches labels.native_action_digest
        text = (d / "actions.jsonl").read_text(encoding="utf-8").replace('"stick_x": -80', '"stick_x": -79', 1)
        (d / "actions.jsonl").write_text(text, encoding="utf-8", newline="\n")
        ep2 = load_episode(d)
        tr = ReplayTracker(ep2)
        feed(tr, ep2, [obs(input_tick=1, targets_remaining=5), final], state="EpisodeEnded")
        v = compare(tr)
        assert not v.match and v.failures()[0].name.startswith("actions digest")


@test
def non_tick0_rows_are_refused() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rows = rows_of(2)
        rows[1]["consumed_tick"] = 7
        d = write_episode(Path(tmp) / "episode_x_offset", rows, labels={}, terminal={}, final=obs())
        try:
            load_episode(d)
        except EpisodeError as exc:
            assert "tick-0" in str(exc)
        else:
            raise AssertionError("an offset row was accepted")


# -- replay_index -----------------------------------------------------------------------------------------------------


@test
def location_split() -> None:
    assert ri.split_location("runs/m7s/gate/s2/U_phase_b/workers/w03/artifacts/episode_x") == \
        ("m7s", "gate/s2/U_phase_b", "U_phase_b", "w03")
    assert ri.split_location("runs/m7p/campaign/_eval/r/final/stochastic/workers/w04/artifacts/episode_y") == \
        ("m7p", "campaign/_eval/r/final/stochastic", "stochastic", "w04")
    assert ri.split_location("runs/m7a_pilot_n5/artifacts_learning_abc/episode_z") == ("m7a_pilot_n5", "", "", None)


MARIO = {"experiment": {"task_id": "ssb64_us_mario_btt_v1"}}


@test
def index_scan_incremental_and_tags() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "runs"
        db = Path(tmp) / "index.sqlite"
        verdicts = Path(tmp) / "verdicts.jsonl"
        stoch = root / "m7x" / "campaign" / "_eval" / "r1" / "final" / "stochastic"
        art = stoch / "workers" / "w00" / "artifacts"
        final = obs(input_tick=3, time_passed=2, game_status=5, targets_remaining=8, position_x=-2200.0)
        a = write_episode(art / "episode_20260929T000000Z_aaaaaaaa", rows_of(3), final=final,
                          labels={"role": "evaluation", "end_reason": "fall", "termination_reason": "native_failure",
                                  "targets_broken": 2, **MARIO},
                          terminal={"step_count": 3, "last_consumed_tick": 2, "targets_broken": 2})
        b = write_episode(art / "episode_20260929T000001Z_bbbbbbbb", rows_of(4),
                          labels={"role": "evaluation", "end_reason": "horizon", "truncation_reason": "max_episode_steps",
                                  "targets_broken": 4, **MARIO},
                          terminal={"step_count": 4, "last_consumed_tick": 3, "targets_broken": 4},
                          final=obs(input_tick=4, time_passed=3, targets_remaining=6, position_x=500.0))
        # no character recorded, final position left of the wall: no tag (the rule is Mario-stage geometry)
        u = fall_episode(root / "m7old" / "run" / "artifacts" / "episode_20260920T000000Z_uuuuuuuu")
        with open(stoch / "evaluation.json", "w", encoding="utf-8") as fp:
            json.dump({"episodes": [
                {"episode_id": b.name, "eval_metrics": {"first_left_entry": None, "min_live_x": -1650.0}},
                {"episode_id": a.name, "eval_metrics": {"first_left_entry": {"consumed_tick": 2}, "min_live_x": -2200.0}},
            ]}, fp)
        hidden = fall_episode(root / "m7x" / "runtime_gens" / "logs" / "episode_hidden")  # pruned directory names
        no_meta = art / "episode_20260929T000002Z_cccccccc"
        no_meta.mkdir()
        (no_meta / "actions.jsonl").write_text("", encoding="utf-8")
        age(root)
        fresh = fall_episode(art / "episode_20260929T000003Z_dddddddd")  # just written: skipped as recent
        s1 = ri.scan(root=root, db_path=db, progress=lambda m: None)
        assert s1["added_or_updated"] == 3 and s1["skipped_recent"] == 1 and s1["skipped_no_metadata"] == 1, s1
        rows = {r["episode_id"]: r for r in ri.load_rows(db_path=db, verdicts_path=verdicts)}
        assert set(rows) == {a.name, b.name, u.name}, rows.keys()
        assert hidden.name not in rows and fresh.name not in rows
        ra, rb, ru = rows[a.name], rows[b.name], rows[u.name]
        assert (ra["end_kind"], ra["targets"], ra["last_tick"], ra["worker"]) == ("fall", 2, 2, "w00")
        assert (ra["character"], ra["stage"], ra["character_name"]) == ("mario", "btt_mario", "Mario")
        assert ra["task_source"] == "labels.experiment.task_id"
        assert ra["tags"] == ["left entry @2"] and ra["tag_text"] == "left entry @2"
        assert dict(ra["tag_details"])["left entry"] == "yes at tick 2 (eval_metrics)"
        assert rb["tags"] == [] and dict(rb["tag_details"])["crossing"] == "no (no left entry)"
        assert (ru["character"], ru["stage"], ru["character_name"], ru["tags"]) == (None, None, "?", [])
        assert (ra["end_label"], rb["end_label"], rb["time_text"], ra["targets_total"]) == (
            "fall", "timeout", "3 · 0.1 s", 10)
        # filters: character (? = not recorded), tag, and the text search over tags
        base = dict(milestone=None, run=None, role=None, character=None, stage=None, end=None, min_targets=None,
                    max_targets=None, cleared=False, tag=None, replay=None, text=None)

        def pick(**kw):
            return {r["episode_id"] for r in ri.filter_rows(list(rows.values()), argparse.Namespace(**{**base, **kw}))}

        assert pick(character=["?"]) == {u.name} and pick(character=["mario"]) == {a.name, b.name}
        assert pick(tag="left entry") == {a.name} and pick(text="LEFT ENTRY") == {a.name}
        assert pick(end=["timeout"]) == {b.name} and pick(end=["truncated"]) == {b.name}
        assert [r["episode_id"] for r in ri.sort_rows(list(rows.values()), ri.DEFAULT_SORT, None)][0] == b.name
        assert (ra["last_target_text"], rb["last_target_text"], ru["is_test"], ra["is_test"]) == ("?", "?", False, False)
        # incremental: nothing changed -> nothing re-read; the recent one is picked up once it is old
        age(fresh)
        s2 = ri.scan(root=root, db_path=db, progress=lambda m: None)
        assert s2["added_or_updated"] == 1 and s2["unchanged"] == 3 and s2["summaries_read"] == 0, s2
        # a replay verdict (MATCH) outranks eval_metrics; a DESYNC verdict is shown but never used as evidence
        with open(verdicts, "w", encoding="utf-8") as fp:
            fp.write(json.dumps({"episode_dir": ra["path"], "verdict": "MATCH", "mode": "headless",
                                 "trajectory": {"first_left_entry": {"consumed_tick": 2}, "min_live_x": -2200.0}}) + "\n")
            fp.write(json.dumps({"episode_dir": rb["path"], "verdict": "DESYNC", "mode": "headless",
                                 "trajectory": {"first_left_entry": {"consumed_tick": 1}}}) + "\n")
        rows = {r["episode_id"]: r for r in ri.load_rows(db_path=db, verdicts_path=verdicts)}
        assert dict(rows[a.name]["tag_details"])["left entry"] == "yes at tick 2 (replay)"
        assert rows[a.name]["replay"] == "MATCH" and "replay" in rows[a.name]["tag_sources"]
        assert rows[b.name]["tags"] == [] and rows[b.name]["replay"] == "DESYNC"
        # a removed episode disappears on the next scan
        for p in sorted(b.rglob("*"), reverse=True):
            p.unlink()
        b.rmdir()
        s3 = ri.scan(root=root, db_path=db, progress=lambda m: None)
        assert s3["removed"] == 1, s3


@test
def old_index_schema_is_rebuilt() -> None:
    import sqlite3

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "index.sqlite"
        old = sqlite3.connect(db)
        old.executescript("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT); INSERT INTO meta VALUES "
                          "('schema', '1'), ('last_scan_utc', 'x'); CREATE TABLE episodes (path TEXT PRIMARY KEY, "
                          "left INTEGER); INSERT INTO episodes VALUES ('runs/x', 1); CREATE TABLE annotations (a);")
        old.commit()
        old.close()
        assert ri.load_rows(db_path=db, verdicts_path=Path(tmp) / "none.jsonl") == []  # dropped, rebuilt empty
        assert ri.last_scan(db) is None


@test
def task_identity_sources() -> None:
    from replay_task import CHARACTER_NAMES, KNOWN_CHARACTERS, TASKS, character_name, task_identity

    view = {"labels": {"experiment": {"compatibility_view": {"task.character": "mario", "task.stage": "btt_mario"},
                                      "task_id": "ssb64_us_mario_btt_v1"}}}
    assert task_identity(view) == ("mario", "btt_mario", "labels.experiment.compatibility_view task.*")
    only_id = task_identity({"labels": {"experiment": {"task_id": "ssb64_us_mario_btt_v1"}}})
    assert only_id == ("mario", "btt_mario", "labels.experiment.task_id")
    fox = task_identity({"labels": {"experiment": {"task_id": "ssb64_jp_fox_btt_v1"}}})
    assert fox == ("fox", "btt_fox", "labels.experiment.task_id (pattern)")
    assert task_identity({"labels": {"experiment": {"task_id": "ssb64_us_wario_btt_v1"}}}).character is None
    acc = {"format": "battleship_btt_episode", "labels": {"contracts": {"action_class_character": "mario"}}}
    assert task_identity(acc) == ("mario", "btt_mario", "labels.contracts.action_class_character")
    none = task_identity({"labels": {"role": "evaluation"}})
    assert none == (None, None, "not recorded") and character_name(none.character) == "?"
    assert character_name("donkey_kong") == "Donkey Kong" and set(CHARACTER_NAMES) == set(KNOWN_CHARACTERS)
    try:  # the local copies match rl/experiment_config (a heavy import: gymnasium, numpy)
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "rl"))
        import experiment_config as ec
    except ImportError:
        return
    assert tuple(ec.KNOWN_CHARACTERS) == KNOWN_CHARACTERS
    assert {k: (v["character"], v["stage"]) for k, v in ec.SUPPORTED_TASKS.items()} == TASKS


@test
def another_stage_adds_tags_without_touching_the_index() -> None:
    """A second stage's extractor (a stand-in for Fox) registers in replay_tags.EXTRACTORS; the index scans its
    summary file and shows its tags; Mario's facts (evaluation.json left entry) never reach a Fox episode."""
    import replay_tags

    class FoxTags(replay_tags.StageTags):
        stage = "btt_fox"
        summary_files = ("fox_summary.json",)

        def from_summary(self, path, rel):
            doc = json.loads(path.read_text(encoding="utf-8"))
            return [replay_tags.Fact(e, "fox_summary", rel(path), {"reflector": True}) for e in doc["reflector"]]

        def resolve(self, facts):
            return (["reflector"], [("reflector", "yes")]) if "fox_summary" in facts else ([], [])

    replay_tags.EXTRACTORS["btt_fox"] = FoxTags()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runs"
            art = root / "m9" / "run" / "artifacts"
            final = obs(input_tick=3, time_passed=2, game_status=5, targets_remaining=8, position_x=-2200.0)
            f = write_episode(art / "episode_20261001T000000Z_ffffffff", rows_of(3), final=final,
                              labels={"role": "evaluation", "end_reason": "fall",
                                      "termination_reason": "native_failure", "targets_broken": 2,
                                      "experiment": {"task_id": "ssb64_us_fox_btt_v1"}},
                              terminal={"step_count": 3, "last_consumed_tick": 2, "targets_broken": 2})
            (root / "m9" / "run" / "fox_summary.json").write_text(json.dumps({"reflector": [f.name]}),
                                                                  encoding="utf-8")
            (root / "m9" / "run" / "evaluation.json").write_text(json.dumps({"episodes": [
                {"episode_id": f.name, "eval_metrics": {"first_left_entry": {"consumed_tick": 1}}}]}),
                encoding="utf-8")
            age(root)
            ri.scan(root=root, db_path=Path(tmp) / "i.sqlite", progress=lambda m: None)
            (r,) = ri.load_rows(db_path=Path(tmp) / "i.sqlite", verdicts_path=Path(tmp) / "v.jsonl")
            assert (r["character_name"], r["stage"], r["tags"]) == ("Fox", "btt_fox", ["reflector"]), r
    finally:
        del replay_tags.EXTRACTORS["btt_fox"]


@test
def display_fields() -> None:
    import datetime as dt

    clear = {"end_kind": "clear", "completion_time": 446, "last_tick": 446, "end_detail": ""}
    assert ri.time_text(clear) == "7.43 s" and abs(ri.time_seconds(clear) - 446 / 60) < 1e-9
    assert ri.time_text({"end_kind": "fall", "completion_time": None, "last_tick": 2975}) == "2975 · 49.6 s"
    assert ri.time_text({"end_kind": "unknown", "completion_time": None, "last_tick": None}) == "–"
    labels = {"end_reason=horizon, truncation=max_episode_steps": "timeout",
              "end_reason=horizon, truncation=tick_quota": "timeout",
              "end_reason=horizon, truncation=goal_reached": "goal",
              "end_reason=aborted": "aborted", "end_reason=lifecycle_failure": "aborted"}
    for detail, want in labels.items():
        assert ri.end_label({"end_kind": "truncated", "end_detail": detail}) == want, detail
    assert ri.end_label({"end_kind": "unknown"}) == "unknown"
    local = dt.datetime(2026, 9, 27, 1, 22, tzinfo=dt.timezone.utc).astimezone()
    assert ri.created_text("2026-09-27T01:22:00+00:00") == f"{local:%b} {local.day} {local:%H:%M}"
    assert ri.created_text("") == "" and ri.created_text("garbage") == ""


# -- replay_history (saved frames) ------------------------------------------------------------------------------------


def saved(tick: int, nbytes: int = 12):
    from replay_history import SavedFrame

    return SavedFrame(tick=tick, width=2, height=2, rgb=bytes(nbytes))


@test
def history_config_and_memory() -> None:
    from replay_history import HistoryConfig, frame_bytes, history_bytes

    default = HistoryConfig()
    assert default.frames == 600 and default.scale == 2 and default.enabled and default.capture == "always"
    assert frame_bytes(960, 720, 2) == 480 * 360 * 3 == 518_400
    assert history_bytes(default, 960, 720) == 311_040_000  # the documented ~311 MB
    assert history_bytes(HistoryConfig(scale=1), 960, 720) == 1_244_160_000
    assert history_bytes(HistoryConfig(scale=4), 960, 720) == 77_760_000
    assert HistoryConfig(seconds=0).frames == 0 and not HistoryConfig(seconds=0).enabled
    assert HistoryConfig(seconds=2.5).frames == 150


@test
def history_eviction_keeps_frames_near_the_game() -> None:
    from replay_history import FrameHistory

    h = FrameHistory(3)
    for t in range(-1, 5):  # playback: the oldest ticks go first
        h.put(saved(t))
    assert h.ticks() == [2, 3, 4] and len(h) == 3 and h.nbytes == 36 and h.span() == (2, 4)
    h.put(saved(0))  # a rebuild inserts an older tick: the frame farthest from it goes
    assert h.ticks() == [0, 2, 3], h.ticks()
    h.put(saved(3, nbytes=99))  # replacing a tick keeps the count
    assert len(h) == 3 and h.get(3).nbytes == 99 and 2 in h and 4 not in h
    off = FrameHistory(0)
    off.put(saved(1))
    assert len(off) == 0 and off.get(1) is None


@test
def pixel_conversion_and_ppm() -> None:
    from replay_history import bgrx_to_rgb, ppm

    bgrx = bytes([1, 2, 3, 0, 10, 20, 30, 255])  # two pixels, GDI order B,G,R,X
    assert bgrx_to_rgb(bgrx) == bytes([3, 2, 1, 30, 20, 10])
    data = ppm(2, 1, bgrx_to_rgb(bgrx))
    assert data.startswith(b"P6 2 1 255\n") and data.endswith(bytes([3, 2, 1, 30, 20, 10]))
    try:
        import tkinter as tk

        root = tk.Tk()
    except Exception:  # noqa: BLE001 - no display: the byte-level checks above still ran
        return
    try:
        img = tk.PhotoImage(data=data, format="PPM")
        assert (img.width(), img.height()) == (2, 1)
        assert tuple(img.get(0, 0)) == (3, 2, 1) and tuple(img.get(1, 0)) == (30, 20, 10)
        assert img.zoom(2).width() == 4
    finally:
        root.destroy()


@test
def navigation_plans() -> None:
    from replay_history import FrameHistory, plan_back, plan_forward, plan_view

    h = FrameHistory(100)
    for t in range(40, 100):  # saved ticks 40..99, live game at 100, last row 3444
        h.put(saved(t))
    last = 3444
    assert plan_back(None, 100, h, last) == ("saved", 99)  # Left from the live game: instant
    assert plan_back(41, 100, h, last) == ("saved", 40)
    assert plan_back(40, 100, h, last) == ("rebuild", 39)  # older than the saved frames
    assert plan_forward(98, 100, h, last) == ("saved", 99)
    assert plan_forward(99, 100, h, last) == ("live", 100)  # back to the live game
    assert plan_forward(None, 100, h, last) == ("forward", 101)  # a real step
    assert plan_view(-1, 100, h, last) == ("rebuild", -1)  # tick-0 state not saved -> restart
    assert plan_back(-1, 100, h, last) == ("none", -2)
    assert plan_view(3000, 100, h, last) == ("forward", 3000)
    assert plan_view(3445, 100, h, last) == ("none", 3445)
    assert plan_back(None, -1, None, last) == ("none", -2)  # at the start, no history
    assert plan_back(None, 5, None, last) == ("rebuild", 4)  # history off: always rebuild


@test
def engine_capture_policy() -> None:
    from replay_game import ReplayEngine
    from replay_history import HistoryConfig

    with tempfile.TemporaryDirectory() as tmp:
        ep = load_episode(fall_episode(Path(tmp) / "episode_x_policy"))
        always = ReplayEngine(ep, history=HistoryConfig(seconds=10))
        assert always.history is not None and always.history.capacity == 600
        assert always._should_capture(5, paced=True) and always._should_capture(5, paced=False)
        always._jump_to = 1001  # fast-forward to tick 1000: only its last 600 ticks are kept
        assert not always._should_capture(400, paced=False) and always._should_capture(401, paced=False)
        slow = ReplayEngine(ep, history=HistoryConfig(seconds=10, capture="slow"))
        assert not slow._should_capture(5, paced=True)  # 1x playback
        assert slow._should_capture(5, paced=False)  # single step
        slow._speed = 0.5
        assert slow._should_capture(5, paced=True)
        off = ReplayEngine(ep, history=HistoryConfig(seconds=0))
        assert off.history is None and not off._should_capture(5, paced=False)


@test
def capture_worker_never_stores_a_doubtful_frame() -> None:
    """CaptureWorker._copy with a fake capturer: the timing rule that keeps a saved frame from showing tick k+1."""
    import collections
    import time as _time

    from replay_game import CAPTURE_SAFE_S, CaptureWorker
    from replay_history import FrameHistory, HistoryConfig

    class FakeCapturer:
        def __init__(self, frames, read_delay):
            self.frames, self.read_delay, self.last_read_time, self.calls = list(frames), read_delay, 0.0, 0

        def capture(self, hwnd, divisor):
            self.calls += 1
            data = self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]
            self.last_read_time = _time.perf_counter() + self.read_delay
            return 1, 1, data

    class FakeEngine:
        def __init__(self):
            self.history_config = HistoryConfig(seconds=1)
            self.history = FrameHistory(60)
            self._last_submit = (-2, 0.0)
            self.capture_ms = collections.deque(maxlen=10)
            self.stale_retries = self.late_drops = 0

    px = [bytes([i, i, i, 0]) for i in range(8)]
    e = FakeEngine()
    w = CaptureWorker(e)
    now = _time.perf_counter()
    w._copy(FakeCapturer([px[1]], 0.0), 1, None, {}, None, 0, now)  # on time
    assert 1 in e.history and e.late_drops == 0
    e._last_submit = (3, now)  # tick 3 already submitted
    w._copy(FakeCapturer([px[2]], CAPTURE_SAFE_S + 0.01), 2, None, {}, None, 0, now)  # read too late -> dropped
    assert 2 not in e.history and e.late_drops == 1
    e._last_submit = (3, _time.perf_counter() + 1.0)  # next tick not submitted before the (late) read: still safe
    w._copy(FakeCapturer([px[3]], CAPTURE_SAFE_S + 0.01), 3, None, {}, None, 0, _time.perf_counter())
    assert 3 in e.history and e.late_drops == 1
    fake = FakeCapturer([px[3], px[4]], 0.0)  # first read still shows tick 3 (stale) -> re-read
    e._last_submit = (4, _time.perf_counter())
    w._copy(fake, 4, None, {}, None, 0, _time.perf_counter())
    assert e.stale_retries == 1 and fake.calls == 2 and e.history.get(4).rgb == bytes([4, 4, 4])
    e._last_submit = (9, _time.perf_counter())
    idle = FakeCapturer([px[5]], 0.0)
    w._copy(idle, 5, None, {}, None, 0, _time.perf_counter() - 1.0)  # far behind: skipped without reading
    assert idle.calls == 0 and 5 not in e.history and e.late_drops == 2


@test
def capture_after_a_gap_waits_past_stale_reads() -> None:
    """Without the previous tick's copy a stale read cannot be recognized: the read then starts no earlier than
    CAPTURE_SETTLE_UNVERIFIED_S after the reply (and a verified one after CAPTURE_SETTLE_S)."""
    import collections
    import time as _time

    from replay_game import CAPTURE_SAFE_S, CAPTURE_SETTLE_S, CAPTURE_SETTLE_UNVERIFIED_S, CaptureWorker
    from replay_history import FrameHistory, HistoryConfig

    assert CAPTURE_SETTLE_S < CAPTURE_SETTLE_UNVERIFIED_S and CAPTURE_SETTLE_UNVERIFIED_S + 0.006 < CAPTURE_SAFE_S

    class Capturer:
        def __init__(self, data):
            self.data, self.at, self.last_read_time = data, None, 0.0

        def capture(self, hwnd, divisor):
            self.at = self.last_read_time = _time.perf_counter()
            return 1, 1, self.data

    class Engine:
        history_config = HistoryConfig(seconds=1)

        def __init__(self):
            self.history, self._last_submit = FrameHistory(60), (-2, 0.0)
            self.capture_ms, self.stale_retries, self.late_drops = collections.deque(maxlen=10), 0, 0

    e = Engine()
    w = CaptureWorker(e)
    for tick, data, prev_ok in ((7, b"\x07" * 4, False), (8, b"\x08" * 4, True), (10, b"\x0a" * 4, False)):
        c = Capturer(data)
        t_ready = _time.perf_counter()
        e._last_submit = (tick + 1, t_ready)  # playing: the next tick is submitted at once
        w._copy(c, tick, None, {}, None, 0, t_ready)
        waited = c.at - t_ready
        assert tick in e.history, tick
        if prev_ok:
            assert CAPTURE_SETTLE_S <= waited < CAPTURE_SETTLE_UNVERIFIED_S, (tick, waited)
        else:
            assert waited >= CAPTURE_SETTLE_UNVERIFIED_S, (tick, waited)


# -- viewer panel ----------------------------------------------------------------------------------------------------


@test
def action_state_names_from_decomp() -> None:
    """Common names from decomp/src/ft/ftdef.h, each character's own ids from ftchar/<dir>/<dir>.h (read only);
    ids 220+ are only named with the character known, otherwise they stay numbers."""
    from replay_status import coverage, load_errors, status_label, status_names

    names = status_names("mario")
    assert names, load_errors
    assert status_label(10) == "Wait (10)"  # nFTCommonStatusWait, not the ControlStart range marker
    assert status_label(26) == "Fall (26)" and status_label(24) == "JumpAerialF (24)"
    assert status_label(37) == "DamageHi1 (37)" and status_label(56) == "WallDamage (56)"  # marker aliases skipped
    assert status_label(62) == "DokanStart (62)"  # a real state whose own name ends in Start
    assert status_label(219) == "LandingAirNull (219)"
    assert status_label(225, "mario") == "SpecialHi (225)"  # Mario's own range
    assert status_label(225, "fox") == "SpecialN (225)"  # the same id is another state for Fox
    assert status_label(225) == "225"  # character unknown: never guessed
    assert status_label(224, "jigglypuff") == "JumpAerialF2 (224)"  # the decomp's odd ftStatus_purin_ prefix
    assert status_label(225, "wario") == "225" and "wario" in load_errors  # no table: common names only
    assert len(names) == 229 and max(names) == 228 and len(status_names()) == 220
    assert status_label(229, "mario") == "229" and status_label(None) == "-" and status_label("x") == "x"
    cov = coverage()
    assert len(cov) == 12 and all(n > 0 for n in cov.values()) and cov["mario"] == 9, cov


@test
def panel_texts() -> None:
    from replay_episode import Check, Row, Verdict
    from replay_ui import (BADGES, header_lines, live_columns, marker_groups, result_details, result_summary,
                           runs_relative, status_text, verdict_badge)

    s = {"episode_id": "episode_x", "role": "evaluation", "run_id": None, "profile": "m7p_geo4_s1",
         "observation": None, "reward": None, "end": "unknown", "end_detail": "not recorded", "targets_broken": None,
         "rows": 12, "rows_to_replay": 11, "prefix_rows": None}
    lines = header_lines(s)
    assert lines == ["character ? · role evaluation", "profile m7p_geo4_s1", "rows 12 (11 replayable)"], lines
    assert not any(bad in " ".join(lines) for bad in ("None", "not recorded", "unknown", "observation", "prefix"))
    s.update(end="fall", end_detail="end_reason=fall", targets_broken=6, rows_to_replay=12, prefix_rows=120)
    assert header_lines(s)[-1] == "recorded end fall (end_reason=fall) · targets 6 · rows 12 · prefix 120"
    with tempfile.TemporaryDirectory() as tmp:
        runs = Path(tmp) / "runs"
        (runs / "m7p" / "episode_x").mkdir(parents=True)
        assert runs_relative(str(runs / "m7p" / "episode_x"), runs) == ("runs" + os.sep, os.path.join("m7p", "episode_x"))
        assert runs_relative(str(Path(tmp) / "elsewhere"), runs) == ("", str(Path(tmp) / "elsewhere"))

    match = Verdict(True, [Check("end", True, "fall", "fall"), Check("steps", True, 3, 3)], ["digest: not recorded"])
    desync = Verdict(False, [Check("end", True, "fall", "fall"), Check("steps", False, 3, 2)], [])
    base = {"verdict": None, "verdict_detail": None, "error": None, "mismatch": None}
    assert verdict_badge(base) == BADGES["pending"]
    assert verdict_badge(dict(base, verdict="MATCH", verdict_detail=match)) == BADGES["MATCH"]
    assert verdict_badge(dict(base, mismatch="row 3: step_count 9")) == BADGES["DESYNC"]  # decided before the end
    assert verdict_badge(dict(base, error="stopped")) == BADGES["stopped"]
    text, _, details = result_summary(dict(base, verdict="MATCH", verdict_detail=match))
    assert text.startswith("✔ MATCH — 2 ok, 1 skipped") and details
    text, _, _ = result_summary(dict(base, verdict="DESYNC", verdict_detail=desync))
    assert text.startswith("✖ DESYNC — 1 failed, 1 ok, 0 skipped")
    assert [tag for _, tag, _ in result_details(dict(base, verdict_detail=match))] == ["ok", "ok", "skip"]
    line = "✖ steps: expected 3, got 2"
    assert result_details(dict(base, verdict_detail=desync))[1] == (line, "fail", line)  # no digest: no labels
    assert result_summary(base)[2] is False and result_details(base) == []

    ended = {"phase": "ended", "end_kind": "clear", "live_tick": 467, "verdict": "MATCH"}
    assert status_text(ended) == "■ ended: clear at tick 467"  # the panel: no verdict word (the badge has it)
    assert status_text(ended, verdict=True) == "■ MATCH: clear at tick 467"  # the HUD over the game window
    assert status_text(dict(ended, end_kind="rows_exhausted")) == "■ ended: truncated at tick 467"

    view = {"row": Row(12, 0x4000, 80, -80, 12), "observation": obs(position_x=-1234.56, fighter_status_id=26,
                                                                   time_passed=99),
            "tick": 12, "targets_broken": 3, "targets_total": 10, "rows": 3445}
    cols = live_columns(view)
    assert cols == {"tick": "12 / 3444", "stick": "↘ +80 -80", "button": "B", "targets": "3/10", "x": "-1234.6",
                    "y": "-2550.0", "status": "  Fall (26)"}, cols
    assert "t=" not in " ".join(cols.values()) and "99" not in " ".join(cols.values())
    cols = live_columns(dict(view, row=None, observation={}, tick=-1, targets_broken=None))
    assert cols["tick"] == "tick-0 state" and cols["stick"] == cols["x"] == "-" and cols["targets"] == "-/10"
    assert marker_groups([812, 1204, 1204, 3001]) == [(812, 1, 1), (1204, 2, 3), (3001, 4, 4)]
    assert marker_groups([]) == []


@test
def desync_root_cause_and_observation_table() -> None:
    from replay_episode import DIGEST_CHECK, Check, Verdict
    from replay_ui import middle_ellipsis, result_details, result_summary

    rows = [("air_velocity_x", 0.0, 1.9999990463256836), ("fighter_status_id", 0, 27),
            ("position_x", -2186.0, -1467.7998046875)]
    checks = [Check(DIGEST_CHECK, False, "af661e295cd1a843", "489fa7dc580de62e"), Check("steps", True, 3445, 3445),
              Check("end", False, "fall", "truncated"),
              Check("final observation (host_frame excluded)", False, "identical", "...", rows)]
    snap = {"verdict": "DESYNC", "verdict_detail": Verdict(False, checks, ["x: not recorded"]), "error": None,
            "mismatch": None}
    text, _, _ = result_summary(snap)
    assert text == ("✖ DESYNC — likely root cause: actions.jsonl differs from the recording (actions digest); "
                    "2 downstream failures, 1 ok, 1 skipped"), text
    lines = result_details(snap)
    shown = [s for s, _, _ in lines]
    tags = [t for _, t, _ in lines]
    assert shown[0].startswith("✖ likely root cause · actions digest") and tags[0] == "root"
    assert shown[2] == "✖ downstream · end: expected fall, got truncated" and tags[2] == "downstream"
    assert shown[3] == "✖ downstream · final observation (host_frame excluded): 3 fields differ"
    table = lines[4:8]
    assert [t for _, t, _ in table] == ["table_head", "table", "table", "table"]
    assert table[0][0].split() == ["field", "expected", "got"]
    assert table[1][0].split() == ["air_velocity_x", "0.000", "2.000"]  # shown: 3 decimals
    assert table[2][0].split() == ["fighter_status_id", "0", "27"]  # ints as they are
    assert table[3][0].split() == ["position_x", "-2186.000", "-1467.800"]
    assert len({len(s) for s, _, _ in table}) == 1  # aligned columns
    assert table[1][2] == "    air_velocity_x\t0.0\t1.9999990463256836"  # copied: full precision, tab-separated
    assert table[3][2] == "    position_x\t-2186.0\t-1467.7998046875"
    assert tags[-1] == "skip"
    # digest fine: no root-cause wording, failures are plain
    plain = dict(snap, verdict_detail=Verdict(False, [Check(DIGEST_CHECK, True, "a", "a")] + checks[1:], []))
    assert "root cause" not in result_summary(plain)[0]
    assert not any(t in ("root", "downstream") for _, t, _ in result_details(plain))

    sep = os.sep
    path = sep.join(["runs", "m7p", "campaign", "_eval", "m7p_geo4_s1", "episode_20260928T072129Z_44619208"])
    assert middle_ellipsis(path, len(path), len) == path  # fits: unchanged
    short = middle_ellipsis(path, 50, len)
    assert len(short) <= 50 and short.startswith("runs" + sep + "m7p") and "…" in short
    assert short.endswith(sep + "episode_20260928T072129Z_44619208")  # the episode folder stays whole
    assert middle_ellipsis(path, 10, len) == "…" + sep + "episode_20260928T072129Z_44619208"  # the folder wins
    assert middle_ellipsis("episode_only", 3, len) == "episode_only"


@test
def target_prepass_marks_break_ticks() -> None:
    from replay_episode import Row
    from replay_game import TargetPrepass, _Cancelled

    class Tracker:
        def __init__(self):
            self.initial, self.targets_broken = obs(targets_remaining=10), 0

    with tempfile.TemporaryDirectory() as tmp:
        ep = load_episode(fall_episode(Path(tmp) / "episode_x_prepass"))
        p = TargetPrepass(ep)
        tr = Tracker()
        for tick, broken in ((0, 0), (1, 0), (2, 1), (3, 1), (4, 3)):  # two targets on one tick
            tr.targets_broken = broken
            p._on_step(Row(tick, 0, 0, 0, tick), tr)
        assert p.break_ticks == [2, 4, 4] and p.state == "running"
        p.cancel()  # no process yet: only the flag
        try:
            p._on_step(Row(5, 0, 0, 0, 5), tr)
            raise AssertionError("a cancelled pre-pass must stop at the next step")
        except _Cancelled:
            pass


@test
def stale_session_cleanup_spares_a_session_being_created() -> None:
    """The marker pre-pass creates its session while the engine cleans up: a folder whose session.json is not
    written yet belongs to the pid in its name."""
    import replay_game

    with tempfile.TemporaryDirectory() as tmp:
        saved_dir = replay_game.SESSIONS_DIR
        replay_game.SESSIONS_DIR = Path(tmp)
        try:
            ours = Path(tmp) / f"20260929T000000Z_{os.getpid()}_abcdefgh_markers"
            dead = Path(tmp) / "20260929T000000Z_4000000000_abcdefgh"  # no such pid
            ours.mkdir()
            dead.mkdir()
            removed = replay_game.cleanup_stale_sessions()
            assert ours.is_dir() and not dead.exists() and removed == [dead.name], removed
        finally:
            replay_game.SESSIONS_DIR = saved_dir


@test
def viewer_panel_is_stable_and_result_expands() -> None:
    """The real ViewerUI (unstarted engine, withdrawn window): changing values never changes the panel size, the
    result stays one line on MATCH, opens by itself on DESYNC and toggles on click, markers are drawn."""
    from replay_episode import Check, Row, Verdict
    from replay_game import ReplayEngine

    try:
        import tkinter as tk

        tk.Tk().destroy()
    except Exception:  # noqa: BLE001 - no display
        return
    import replay_ui

    class Prepass:
        state, break_ticks, seconds, error = "done", [1, 2, 2], 0.5, None

    with tempfile.TemporaryDirectory() as tmp:
        ep = load_episode(fall_episode(Path(tmp) / "episode_x_panel"))
        engine = ReplayEngine(ep)
        ui = replay_ui.ViewerUI(engine, summary={"episode_id": ep.episode_id, "directory": str(ep.directory),
                                                 "rows": 3}, hud=False, prepass=Prepass())
        ui.root.withdraw()
        try:
            base = engine.snapshot()

            def show(snap):
                engine.snapshot = lambda: snap
                ui._update_panel(snap, ui._view(snap))
                ui._update_result(snap)
                ui._draw_markers(force=True)
                ui.root.update_idletasks()
                return ui.root.winfo_reqwidth(), {k: c.winfo_reqwidth() for k, c in ui.cells.items()}

            short = dict(base, phase="playing", last_row=Row(0, 0, 0, 0, 0), live_tick=0, achieved_tps=60.0,
                         observation=obs(position_x=1.0, fighter_status_id=10), targets_broken=0)
            long_ = dict(base, phase="jumping", last_row=Row(2, 0xFFFF, -80, 80, 2), live_tick=2, jump_to=3,
                         observation=obs(position_x=-12345.67, position_y=-99999.9, fighter_status_id=59),
                         targets_broken=10, rebuilding=True, rebuild_to=2, message="speed 4x requested; " * 8)
            w1, cells1 = show(short)
            w2, cells2 = show(long_)
            assert (w1, cells1) == (w2, cells2), (w1, w2, cells1, cells2)
            assert ui.cells["status"].cget("text") == "  LandingFallSpecial (59)"  # longest common name still fits
            match = Verdict(True, [Check("end", True, "fall", "fall")], [])
            show(dict(short, phase="ended", end_kind="fall", verdict="MATCH", verdict_detail=match))
            assert ui.badge.cget("text") == "MATCH" and not ui.result.winfo_manager()
            assert "MATCH" not in ui.status.get() and ui.result_line.cget("text").startswith("▸ ✔ MATCH")
            ui._toggle_result()
            assert ui.result.winfo_manager() and ui.result_line.cget("text").startswith("▾ ")
            ui._toggle_result()
            assert not ui.result.winfo_manager()
            desync = Verdict(False, [Check("steps", False, 3, 2)], [])
            show(dict(short, phase="ended", end_kind="fall", verdict="DESYNC", verdict_detail=desync))
            assert ui.badge.cget("text") == "DESYNC" and ui.result.winfo_manager()  # opened by itself
            assert "expected 3, got 2" in ui.result.get("1.0", "end")
            assert len(ui.markers.find_all()) == 2 * 2  # two groups (tick 1; ticks 2+2): a triangle and a label each
            assert "3 target markers (pre-pass 0.5 s)" in ui._diag_text()
            assert {"<Enter>", "<Leave>", "<Button-1>"} <= set(ui.markers.tag_bind("m2"))
            ui._marker_enter(2, 2, 3, -3000, -3000)  # off screen
            tip = ui._marker_tip.winfo_children()[0].cget("text")
            assert tip == "Targets 2-3 broken at tick 2\nclick to jump there", tip
            jumped = []
            ui.jump = jumped.append
            ui._marker_click(1)
            assert jumped == [1] and ui._marker_tip is None

            # Observation table: shown rounded, copied at full precision (all lines, or the selected ones).
            rows = [("air_velocity_x", 0.0, 1.9999990463256836), ("position_x", -2186.0, -1467.7998046875)]
            table = Verdict(False, [Check("final observation (host_frame excluded)", False, "identical", "...",
                                          rows)], [])
            show(dict(short, phase="ended", end_kind="fall", verdict="DESYNC", verdict_detail=table))
            shown = ui.result.get("1.0", "end")
            assert "2.000" in shown and "-1467.800" in shown and "1.99999" not in shown, shown
            everything = ui._result_copy_text(selected=False)
            assert "1.9999990463256836" in everything and "-1467.7998046875" in everything
            assert ui._result_copy_text(selected=True) == ""  # nothing selected
            ui.result.tag_add("sel", "3.4", "4.0")  # part of line 3 (the first table row) up to the start of line 4
            assert ui._result_copy_text() == "    air_velocity_x\t0.0\t1.9999990463256836"
            ui.result.tag_remove("sel", "1.0", "end")

            # The path: middle ellipsis keeps the episode folder, the tooltip has the full path.
            ui._fit_path(120)
            assert "…" in ui.path_label.cget("text") and ui.path_label.cget("text").endswith(ep.directory.name)
            ui._fit_path(5000)
            assert ui.path_label.cget("text") == ui.path_text
            assert ui.path_tip.text.startswith(str(ep.directory))
        finally:
            ui.root.destroy()


@test
def target_break_sources_and_last_target() -> None:
    """Recorded break ticks (evaluation.json, episodes.jsonl, gate trace, decisions sidecar, MATCH replays) and the
    last-target rules: exact count, curriculum prefix, clear = completion, 0 targets, otherwise unknown."""
    import gzip

    import replay_breaks as rbk

    rel = lambda p: Path(p).name  # noqa: E731
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "evaluation.json").write_text(json.dumps({"episodes": [
            {"episode_id": "e1", "target_break_ticks": [30, 10, 20]},
            {"episode_id": "e2", "eval_metrics": {"target_breaks": [{"consumed_tick": 5}, {"consumed_tick": 7}]}},
            {"episode_id": "e3"}]}), encoding="utf-8")
        with open(d / "episodes.jsonl", "w", encoding="utf-8") as fp:
            fp.write(json.dumps({"episode_id": "e4", "target_break_ticks": [100]}) + "\n{not json\n")
        assert rbk.from_summary(d / "evaluation.json", rel) == [("e1", "evaluation", "evaluation.json", [10, 20, 30]),
                                                                ("e2", "evaluation", "evaluation.json", [5, 7])]
        assert rbk.from_summary(d / "episodes.jsonl", rel) == [("e4", "episodes_log", "episodes.jsonl", [100])]
        with gzip.open(d / "gate_trace.json.gz", "wt", encoding="utf-8") as fp:
            json.dump({"fields": ["t", "live", "targets"], "rows": [[-1, 1, 10], [0, 1, 10], [1, 1, 9], [2, 1, 7]]}, fp)
        with gzip.open(d / "decisions.json.gz", "wt", encoding="utf-8") as fp:
            json.dump({"signature_fields": ["live", "targets"], "signatures": [[1, 10], [1, 10], [1, 9], [1, 9]]}, fp)
        got = rbk.from_episode(d, "e5", ["gate_trace.json.gz", "decisions.json.gz"], rel)
        assert got == [("e5", "gate_trace", "gate_trace.json.gz", [1, 2, 2]),  # two targets on tick 2
                       ("e5", "decisions", "decisions.json.gz", [1])], got  # row t + 1 = after consumed tick t
    match = {"verdict": "MATCH", "trajectory": {"target_break_ticks": [3, 9]}}
    assert rbk.from_replay(match, "e6")[3] == [3, 9] and rbk.from_replay(dict(match, verdict="DESYNC"), "e6") is None

    base = {"targets": 3, "end_kind": "fall", "completion_tick": None, "completion_time": None, "prefix_rows": None}
    assert rbk.last_target(base, {"evaluation": [10, 20, 3008]}) == (3008, "3008 · 50.1 s", "evaluation")
    assert rbk.last_target(base, {"evaluation": [10, 20]}) == (None, "?", "not recorded")  # count differs
    assert rbk.last_target(base, {"evaluation": [1, 2, 3], "replay": [4, 5, 6]})[2] == "replay"  # replay first
    assert rbk.last_target(base, {"episodes_log": [], "decisions": [7, 8, 9]})[0] == 9
    prefix = dict(base, prefix_rows=500)
    assert rbk.last_target(prefix, {"episodes_log": [600, 900]})[0] == 900  # the missing break is the prefix's
    assert rbk.last_target(prefix, {"episodes_log": []})[1] == "?"  # every break inside the prefix
    assert rbk.last_target(prefix, {"episodes_log": [400, 900]})[1] == "?"  # a tick inside the prefix: not trusted
    clear = dict(base, targets=10, end_kind="clear", completion_tick=447, completion_time=446)
    assert rbk.last_target(clear, {}) == (446, "446 · 7.43 s", "completion")
    assert rbk.last_target(dict(base, targets=0), {}) == (None, "–", "no target broken")
    assert rbk.last_target(dict(base, targets=None), {"evaluation": [1]})[1] == "?"


@test
def browser_filters_sort_and_card() -> None:
    """The real browser on a temporary index (withdrawn window): default order (targets, then last-target tick),
    tests hidden by default, live filters with "N of M", tag search, the stage filter only when stages vary, the
    details card without empty fields, the run tooltip, keyboard selection, heading sort, best per run."""
    try:
        import tkinter as tk

        tk.Tk().destroy()
    except Exception:  # noqa: BLE001 - no display
        return
    import replay_browser as rbw

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "runs"
        art = root / "m7x" / "r1" / "artifacts"
        fin = obs(input_tick=3, time_passed=2, game_status=5, targets_remaining=4, position_x=-2200.0)
        clear = write_episode(art / "episode_20260929T000000Z_clear000", rows_of(3), final=obs(targets_remaining=0),
                              labels={"role": "evaluation", "cleared": True, "termination_reason": "native_clear",
                                      "completion_time_passed": 446, "completion_input_tick": 447,
                                      "targets_broken": 10, **MARIO},
                              terminal={"step_count": 3, "last_consumed_tick": 446, "targets_broken": 10})
        left = write_episode(art / "episode_20260929T000001Z_left0000", rows_of(3), final=fin,
                             labels={"role": "evaluation", "end_reason": "fall", "termination_reason": "native_failure",
                                     "targets_broken": 6, **MARIO},
                             terminal={"step_count": 3, "last_consumed_tick": 3001, "targets_broken": 6})
        slow = write_episode(art / "episode_20260929T000002Z_slow0000", rows_of(3), final=obs(targets_remaining=4),
                             labels={"role": "training", "end_reason": "horizon", "truncation_reason": "max_episode_steps",
                                     "targets_broken": 6, **MARIO},
                             terminal={"step_count": 3, "last_consumed_tick": 3600, "targets_broken": 6})
        unknown = write_episode(art / "episode_20260929T000003Z_unkn0000", rows_of(3), final=obs(targets_remaining=4),
                                labels={"role": "training", "end_reason": "horizon",
                                        "truncation_reason": "max_episode_steps", "targets_broken": 6, **MARIO},
                                terminal={"step_count": 3, "last_consumed_tick": 3600, "targets_broken": 6})
        old = fall_episode(root / "m7old" / "artifacts" / "episode_20260920T000000Z_old00000")
        test = write_episode(root / "m7x" / "r2" / "artifacts" / "episode_20260929T000009Z_test0000", rows_of(3),
                             final=fin, labels={"role": "test", "end_reason": "fall", "targets_broken": 7, **MARIO},
                             terminal={"step_count": 3, "last_consumed_tick": 2, "targets_broken": 7})
        smoke = write_episode(root / "_m7_smoke" / "artifacts" / "episode_20260929T000010Z_smok0000", rows_of(3),
                              final=fin, labels={"role": "training", "end_reason": "fall", "targets_broken": 8},
                              terminal={"step_count": 3, "last_consumed_tick": 2, "targets_broken": 8})
        (root / "m7x" / "r1" / "evaluation.json").write_text(json.dumps({"episodes": [
            {"episode_id": left.name, "target_break_ticks": [10, 20, 30, 40, 50, 2500],
             "eval_metrics": {"first_left_entry": {"consumed_tick": 3001}}},
            {"episode_id": slow.name, "target_break_ticks": [1, 2, 3, 4, 5, 3000]}]}), encoding="utf-8")
        age(root)
        db = Path(tmp) / "i.sqlite"
        ri.scan(root=root, db_path=db, progress=lambda m: None)
        b = rbw.Browser(lambda: ri.load_rows(db_path=db, verdicts_path=Path(tmp) / "v.jsonl"),
                        lambda **kw: {})
        b.root.withdraw()
        try:
            ids = [r["episode_id"] for r in b.view]
            # targets desc, then last-target tick asc (unknown last); tests hidden
            assert ids == [clear.name, left.name, slow.name, unknown.name, old.name], ids
            assert [r["last_target_text"] for r in b.view[:4]] == ["446 · 7.43 s", "2500 · 41.7 s", "3000 · 50.0 s",
                                                                   "?"]
            assert b.count.get() == "5 of 7 episodes (2 tests hidden)" and not b.stage_box.winfo_manager()
            assert "tags" not in [c[0] for c in rbw.COLUMNS]  # tags stay in the card and the search only
            roles = b.combos["role"].cget("values")  # the recorded roles, not a fixed list
            assert roles[0] == "any" and {"training", "evaluation", "test"} <= set(roles), roles
            b.show_tests.set(True)
            b.apply()
            assert {r["episode_id"] for r in b.view} >= {test.name, smoke.name} and b.count.get() == "7 of 7 episodes"
            b.show_tests.set(False)
            assert b.combos["character"].cget("values")[-1] == "?"
            b.vars["character"].set("?")
            b.apply()
            assert [r["episode_id"] for r in b.view] == [old.name] and b.count.get().startswith("1 of 7 episodes")
            b.reset_filters()
            b.vars["text"].set("LEFT entry @3001")
            b.apply()
            assert [r["episode_id"] for r in b.view] == [left.name]
            b.vars["end"].set("clear")
            b.apply()
            assert b.view == []
            b.reset_filters()
            b.table.select(0)
            fields = dict(rbw.card_fields(b.table.selected()))
            assert fields["character"] == "Mario" and fields["last target"] == "446 · 7.43 s (completion)"
            assert fields["end"].startswith("clear") and "worker" not in fields and "test episode" not in fields
            assert not any(v in ("None", "") for v in fields.values())
            assert b.card_title.cget("text") == clear.name and str(b.buttons[0].cget("state")) == "normal"
            assert (0, "run") in b.table._tips and b.table._tips[(0, "run")].endswith(clear.name)
            old_fields = dict(rbw.card_fields(next(r for r in b.rows if r["episode_id"] == old.name)))
            assert old_fields["character"] == "? (not recorded)" and "stage" not in old_fields
            b.table._key(1)
            assert b.table.selected()["episode_id"] == left.name
            b.sort_by("last")  # ascending: 446 (clear), 2500, 3000, then the unknowns
            assert [r["episode_id"] for r in b.view][:3] == [clear.name, left.name, slow.name]
            assert b.table.selected()["episode_id"] == left.name  # the selection survives re-sorting
            b.sort_by("targets")
            # best per run: m7x/r1 -> the clear (4 episodes), m7old -> its only one
            b.best_run.set(True)
            b.apply()
            assert [(r["episode_id"], r["run_count_text"]) for r in b.view] == [(clear.name, "4"), (old.name, "1")]
            assert "runeps" in [c[0] for c in b.table.columns] and b.count.get().startswith("2 runs (best of 5")
            b.vars["min_targets"].set("6")
            b.apply()
            assert [(r["episode_id"], r["run_count_text"]) for r in b.view] == [(clear.name, "4")]
            b.vars["role"].set("training")
            b.apply()
            assert [(r["episode_id"], r["run_count_text"]) for r in b.view] == [(slow.name, "2 of 4")]
            b.reset_filters()
            assert "runeps" not in [c[0] for c in b.table.columns]
        finally:
            b.root.destroy()


@test
def browser_check_filtered() -> None:
    """Check filtered with a stand-in runner: the verdict column and an unknown last target update per result,
    the confirmation above CONFIRM_ABOVE episodes, cancel, and the reload at the end."""
    try:
        import tkinter as tk

        tk.Tk().destroy()
    except Exception:  # noqa: BLE001 - no display
        return
    import replay_browser as rbw

    class FakeBatch:
        made: List["FakeBatch"] = []

        def __init__(self, paths, on_start, on_result, on_done):
            self.paths, self.on_start, self.on_result, self.on_done = paths, on_start, on_result, on_done
            self.counts, self.finished_count, self.state, self.cancelled = {}, 0, "running", False
            FakeBatch.made.append(self)

        def start(self):
            pass

        def step(self, verdict, ticks=None):
            i = self.finished_count
            self.on_start(i, self.paths[i])
            self.counts[verdict] = self.counts.get(verdict, 0) + 1
            self.finished_count += 1
            self.on_result(i, self.paths[i], {"verdict": verdict, "trajectory": {"target_break_ticks": ticks or []},
                                              "error": None})

        def finish(self):
            self.state = "cancelled" if self.cancelled else "done"
            self.on_done(self)

        def cancel(self):
            self.cancelled = True

        def join(self, _timeout=None):
            pass

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "runs"
        art = root / "m7x" / "r1" / "artifacts"
        eps = [write_episode(art / f"episode_20260929T00000{i}Z_chk{i}0000", rows_of(3), final=obs(targets_remaining=8),
                             labels={"role": "evaluation", "end_reason": "horizon",
                                     "truncation_reason": "max_episode_steps", "targets_broken": 2, **MARIO},
                             terminal={"step_count": 3, "last_consumed_tick": 3599, "targets_broken": 2})
               for i in range(3)]
        age(root)
        db = Path(tmp) / "i.sqlite"
        ri.scan(root=root, db_path=db, progress=lambda m: None)
        b = rbw.Browser(lambda: ri.load_rows(db_path=db, verdicts_path=Path(tmp) / "v.jsonl"), lambda **kw: {})
        b.root.withdraw()
        b.batch_factory = FakeBatch
        asked = []
        b._confirm = lambda n: asked.append(n) or False
        saved_limit = rbw.CONFIRM_ABOVE
        try:
            rbw.CONFIRM_ABOVE = 2
            b.check_filtered()  # 3 listed > 2: asks, and "no" starts nothing
            assert asked == [3] and b.batch is None and not FakeBatch.made
            rbw.CONFIRM_ABOVE = 50
            assert all(r["last_target_text"] == "?" for r in b.view)
            b.check_filtered()
            batch = FakeBatch.made[-1]
            assert b.batch is batch and b.check_btn.cget("text") == "Cancel check" and len(batch.paths) == 3
            batch.step("MATCH", [100, 200])
            b._drain()
            r0 = next(r for r in b.rows if str(ri.REPO_ROOT / r["path"]) == str(batch.paths[0]))
            assert r0["replay"] == "MATCH" and r0["last_target_text"] == "200 · 3.3 s"  # filled in by the replay
            assert "checking 1/3" in b.status.get() and "1 MATCH" in b.status.get()
            batch.step("DESYNC")
            b._drain()
            b.check_filtered()  # the button now cancels
            assert batch.cancelled and "cancelling" in b.status.get()
            batch.finish()
            b._drain()
            assert b.batch is None and b.check_btn.cget("text") == "Check filtered…"
            assert b.status.get() == "check cancelled after 2 of 3 episodes · 1 MATCH · 1 DESYNC", b.status.get()
        finally:
            rbw.CONFIRM_ABOVE = saved_limit
            b.root.destroy()


def write_route(d: Path, *, session: str = "rd4", words: int = 3, clear: bool = True) -> Path:
    """A minimal M8 route folder (metadata m8_rd_route_v1 + actions.jsonl + trace.json.gz) whose trace is the
    exact replay of its rows: targets break on ticks 0 and 2 (10 -> 8)."""
    import gzip

    from replay_episode import Row

    d.mkdir(parents=True)
    rows = [{"sequence_index": i, "buttons": 0x8000 if i % 2 else 0, "stick_x": 80, "stick_y": 0, "consumed_tick": i}
            for i in range(words)]
    with open(d / "actions.jsonl", "w", encoding="utf-8", newline="\n") as fp:
        for r in rows:
            fp.write(json.dumps(r) + "\n")
    remaining = [9, 9, 8][:words]
    steps = [{"consumed_tick": i, "state_name": "WaitingForAction", "step_count": i + 1,
              "observation": obs(input_tick=i + 1, time_passed=i, targets_remaining=remaining[i],
                                 position_x=-2200.0 if i == 2 else 0.0)} for i in range(words)]
    if clear:
        steps[-1]["state_name"] = "EpisodeEnded"
    with gzip.open(d / "trace.json.gz", "wt", encoding="utf-8") as fp:
        json.dump({"initial": {"observation": obs()}, "steps": steps}, fp)
    digest = action_digest([Row(r["sequence_index"], r["buttons"], r["stick_x"], r["stick_y"], r["consumed_tick"])
                            for r in rows])
    term = ({"kind": "clear", "submitted": words, "last_consumed_tick": words - 1} if clear else
            {"kind": "sequence_end", "submitted": words, "last_consumed_tick": words - 1})
    meta = {"schema": "m8_rd_route_v1", "arm": "T", "claim": "clear" if clear else "t", "session": session,
            "native_action_digest": digest, "words": words, "action_contract": "rlaction_native_v1",
            "replay": {"exact": True, "t": 2, "l0": True, "l0_tick": 1, "crossing": True,
                       "first_qualified_entry": 2, "left_target": True, "left_target_breaks": [[6, 2]],
                       "clear": clear, "terminal": term, "label": "T_c0001_left",
                       "clear_facts": {"completion_time_passed": words - 1, "completion_input_tick": words}}}
    (d / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    return d


@test
def m8_routes_load_and_check() -> None:
    """M8 routes (metadata m8_rd_route_v1, no labels / terminal / observations) open in the viewer; their
    expected outcome is the verifying replay (trace.json.gz); feeding that replay gives MATCH, a changed row
    DESYNC; folder names repeat across runs, so the id is route_<session>_<folder>."""
    from replay_episode import ReplayTracker, artifact_format, compare, expected_outcome, load_route_trace

    with tempfile.TemporaryDirectory() as tmp:
        d = write_route(Path(tmp) / "runs" / "m8_rd_rd4" / "routes" / "T_t", clear=False)
        ep = load_episode(d)
        assert ep.episode_id == "route_rd4_T_t" and artifact_format(ep.metadata) == "m8_rd_route_v1"
        e = expected_outcome(ep)
        assert (e.end_kind, e.steps, e.last_consumed_tick, e.targets_broken) == ("truncated", 3, 2, 2)
        assert e.recorded_digest == e.file_digest and e.initial_observation and e.final_observation
        assert e.completion_time_passed is None  # not a clear: no completion clocks expected

        def replay(episode):
            tr = ReplayTracker(episode)
            trace = load_route_trace(episode.directory)
            tr.feed_initial(trace["initial"]["observation"])
            for row, s in zip(episode.replay_rows, trace["steps"]):
                tr.feed_step(row, s["state_name"], s["step_count"], s["consumed_tick"], s["observation"])
                if tr.ended:
                    break
            return compare(tr), tr

        v, tr = replay(ep)
        assert v.match and not v.skipped and tr.end_kind == "rows_exhausted", v.lines()
        assert tr.trajectory.target_break_ticks == [0, 2]
        c = load_episode(write_route(Path(tmp) / "runs" / "m8_rd_rd4" / "routes" / "T_clear"))
        v, _ = replay(c)
        assert v.match and expected_outcome(c).completion_input_tick == 3, v.lines()
        lines = (c.directory / "actions.jsonl").read_text(encoding="utf-8").splitlines()
        lines[1] = lines[1].replace('"stick_x": 80', '"stick_x": -80')
        (c.directory / "actions.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        v, _ = replay(load_episode(c.directory))
        assert not v.match and [x.name for x in v.failures()][0].startswith("actions digest")
        bad = write_route(Path(tmp) / "runs" / "m8_rd" / "routes" / "T_bad")
        meta = json.loads((bad / "metadata.json").read_text(encoding="utf-8"))
        (bad / "metadata.json").write_text(json.dumps(dict(meta, words=99)), encoding="utf-8")
        try:
            load_episode(bad)
            raise AssertionError("a route whose words differ from its rows must be refused")
        except EpisodeError:
            pass


@test
def scan_reports_what_it_does_not_index() -> None:
    """Archive folders, actions without metadata, unrecognized metadata formats and still-being-written folders
    are counted with an example path (scan output, browser status, meta last_scan_report). A route is listed
    with its own fields; an unrecognized format is listed, not hidden as a test."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "runs"
        route = write_route(root / "m8_rd_rd4" / "routes" / "T_clear")
        for name in ("archive", "archive.prev", "base"):
            (root / "m8_rd_rd4" / name).mkdir(parents=True)
            (root / "m8_rd_rd4" / name / "cells.jsonl").write_text("{}\n", encoding="utf-8")
            (root / "m8_rd_rd4" / name / "bursts.bin").write_bytes(b"\x00")
        orphan = root / "m9" / "loose" / "ep1"
        orphan.mkdir(parents=True)
        (orphan / "actions.jsonl").write_text("", encoding="utf-8")
        odd = root / "m9" / "odd" / "ep2"
        odd.mkdir(parents=True)
        (odd / "actions.jsonl").write_text("", encoding="utf-8")
        (odd / "metadata.json").write_text(json.dumps({"schema": "future_v9", "role": None}), encoding="utf-8")
        roleless = fall_episode(root / "m7x" / "regress" / "artifacts" / "episode_20260929T000000Z_nrole000")
        meta = json.loads((roleless / "metadata.json").read_text(encoding="utf-8"))
        meta["labels"].pop("role")
        (roleless / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        age(root)
        db = Path(tmp) / "i.sqlite"
        s = ri.scan(root=root, db_path=db, progress=lambda m: None)
        assert s["archives"] == 3 and s["skipped_no_metadata"] == 1 and s["unrecognized"] == 1, s
        text = s["not_indexed"]
        assert "3 exploration archive folders" in text and "m8_rd_rd4/archive" in text, text
        assert "1 folders with actions.jsonl but no metadata.json, e.g." in text and "m9/loose/ep1" in text
        assert "1 episodes with an unrecognized metadata format" in text and "m9/odd/ep2" in text
        assert ri.last_scan_report(db)["not_indexed"] == text
        rows = {r["episode_id"]: r for r in ri.load_rows(db_path=db, verdicts_path=Path(tmp) / "v.jsonl")}
        r = rows["route_rd4_T_clear"]
        assert (r["role"], r["format"], r["end_label"], r["targets"], r["is_test"]) == (
            "route", "m8_rd_route_v1", "clear", 2, False)
        assert r["created_source"] == "file time" and r["created"].startswith("20")
        assert r["character_name"] == "?" and r["tags"] == ["wall top @1", "crossing @2", "left target @2", "clear"]
        assert r["last_target_text"] == "2 · 0.03 s" and r["last_target_source"] == "completion"
        assert rows["ep2"]["format"] == "unrecognized (future_v9)" and not rows["ep2"]["is_test"]
        assert rows[roleless.name]["is_test"]  # the known format without a role stays a test
        seq = write_route(root / "m8_rd_rd3" / "routes" / "T_t", session="rd3", clear=False)
        age(seq)
        ri.scan(root=root, db_path=db, progress=lambda m: None)
        r3 = next(r for r in ri.load_rows(db_path=db, verdicts_path=Path(tmp) / "v.jsonl")
                  if r["episode_id"] == "route_rd3_T_t")
        assert (r3["end_label"], r3["last_target_text"], r3["last_target_source"]) == ("prefix", "2 · 0.0 s",
                                                                                       "route_trace")


# -- added folders (sources.json): extra read-only roots scanned like runs/ ---------------------------------------


@test
def added_folders_are_tracked_scanned_and_removable() -> None:
    """A folder of episode artifacts outside runs/ can be added (sources.json), is scanned read-only with its name
    as the milestone and the path inside it as the run, its verdicts are found although record_verdict keys them
    with backslashes, and removing it drops its episodes from the index; runs/, folders holding runs/ and lab
    folders are refused; a folder gone from disk keeps its rows and is reported. The browser's Sources dialog
    lists runs/ and the added folders with counts; Remove and Add folder work through it."""
    import shutil

    import replay_browser as rbw

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp).resolve()
        runs = base / "runs"
        fall_episode(runs / "m7x" / "r1" / "artifacts" / "episode_20260929T000000Z_aaaaaaaa")
        extra = base / "old_runs"
        a = fall_episode(extra / "m7y" / "artifacts" / "episode_20260929T000000Z_bbbbbbbb")
        c = fall_episode(extra / "m7z" / "episode_20260929T000000Z_cccccccc")
        lab = base / "labx" / "run"
        lab.mkdir(parents=True)
        (lab / "verifications.jsonl").write_text("", encoding="utf-8")
        age(base)
        sources, db, verdicts = base / "sources.json", base / "i.sqlite", base / "v.jsonl"
        for bad, text in ((base / "nothing", "not a directory"), (ri.REPO_ROOT, "holds runs/"),
                          (base / "labx", "lab records"), (lab, "lab records")):
            try:
                ri.add_source(bad, sources)
                raise AssertionError(f"{bad} must be refused")
            except ri.SourceError as exc:
                assert text in str(exc), exc
        assert ri.load_sources(sources) == []
        assert ri.add_source(extra, sources) == extra and ri.add_source(str(extra), sources) == extra  # once
        assert ri.load_sources(sources) == [extra] and json.loads(sources.read_text(encoding="utf-8"))["version"] == 1
        with open(verdicts, "w", encoding="utf-8", newline="\n") as fp:  # keyed as record_verdict writes it
            fp.write(json.dumps({"episode_dir": str(a), "verdict": "MATCH", "mode": "headless"}) + "\n")
        stats = ri.scan_all(runs_root=runs, sources_path=sources, db_path=db, progress=lambda m: None)
        assert (stats["episodes_seen"], stats["sources"], stats["missing_sources"]) == (3, 1, 0), stats
        rows = {r["episode_id"]: r for r in ri.load_rows(db_path=db, verdicts_path=verdicts)}
        assert (rows[a.name]["milestone"], rows[a.name]["run"], rows[a.name]["path"]) == ("old_runs (added)", "m7y",
                                                                                          a.as_posix())
        assert (rows[c.name]["milestone"], rows[c.name]["run"]) == ("old_runs (added)", "m7z")
        assert rows[a.name]["replay"] == "MATCH" and not rows[a.name]["is_test"]
        assert rows["episode_20260929T000000Z_aaaaaaaa"]["milestone"] == "m7x"
        entries = ri.source_entries(list(rows.values()), None, sources_path=sources)
        assert [(e["kind"].split(",")[0], e["count"], e["removable"], e["missing"]) for e in entries] == [
            ("runs/ (built in", 1, False, False), ("added folder", 2, True, False)], entries

        b = rbw.Browser(lambda: ri.load_rows(db_path=db, verdicts_path=verdicts),
                        lambda **kw: ri.scan_all(runs_root=runs, sources_path=sources, db_path=db,
                                                 progress=lambda m: None),
                        sources_path=sources, db_path=db)
        b.root.withdraw()
        try:
            assert b.root.title().endswith("+  1 added folder") and len(b.rows) == 3, b.root.title()
            d = b.open_sources(visible=False)
            assert b.open_sources(visible=False) is d and d.listbox.size() == 2
            assert str(d.remove_btn.cget("state")) == "disabled"
            d.listbox.selection_set(1)
            d._selection_changed()
            assert str(d.remove_btn.cget("state")) == "normal" and d.selected()["removable"]
            assert b.remove_folder(extra, confirm=False) == 2
            assert ri.load_sources(sources) == [] and len(b.rows) == 1 and d.listbox.size() == 1
            assert "added" not in b.root.title() and b.status.get().startswith("removed ")
            assert b.add_folder(base / "labx") is None and b.status.get().startswith("not added:")
            assert b.add_folder(extra) == extra and b.root.title().endswith("+  1 added folder")
            deadline = time.time() + 10  # the refresh runs in a thread and posts its result to the Tk queue:
            while b._scanning and time.time() < deadline:  # drain it here (no event pumping: other tests' stale
                b._drain() if not b._events.empty() else time.sleep(0.02)  # timers would fire) ...
            for after_id in b.root.tk.call("after", "info"):  # ... and cancel the poll rescan() scheduled
                b.root.after_cancel(after_id)
            assert not b._scanning and len(b.rows) == 3 and d.listbox.size() == 2, b.status.get()
            d.close()
            assert not d.alive() and b.open_sources(visible=False) is not d
        finally:
            b.root.destroy()
        shutil.rmtree(extra)  # the folder disappears: its rows stay, the scan reports it
        stats = ri.scan_all(runs_root=runs, sources_path=sources, db_path=db, progress=lambda m: None)
        assert stats["missing_sources"] == 1 and "1 added folders not found" in stats["not_indexed"], stats
        assert len(ri.load_rows(db_path=db, verdicts_path=verdicts)) == 3
        assert ri.remove_source(extra, sources, db) == 2 and len(ri.load_rows(db_path=db, verdicts_path=verdicts)) == 1
        assert not (base / "labx" / "sources.json").exists() and sorted(p.name for p in runs.rglob("*.json")) == [
            "metadata.json"]  # nothing written into the scanned folders


# -- M9 artifacts: the role is labels.phase, the end is terminal.end_reason with terminal.completion ---------------


def write_m9_episode(d: Path, *, phase: str, kind: str, end_reason: str, rows: int, targets: int,
                     prefix: Optional[int] = None) -> Path:
    """An M9 artifact (rl/m9_* tooling): a standard artifact (schema 1, rlaction_native_v1) whose metadata has no
    labels.role, cleared flag, completion labels or observations, but labels.phase + labels.m9_kind, terminal
    {end_reason, ticks, targets_broken, completion (the native result record of a clear)} and m9
    {native_action_digest, prefix_words}."""
    from replay_episode import Row

    d.mkdir(parents=True)
    acts = rows_of(rows)
    with open(d / "actions.jsonl", "w", encoding="utf-8", newline="\n") as fp:
        for r in acts:
            fp.write(json.dumps(r) + "\n")
    digest = action_digest([Row(r["sequence_index"], r["buttons"], r["stick_x"], r["stick_y"], r["consumed_tick"])
                            for r in acts])
    completion = ({"result_schema": 1, "outcome": "clear", "targets_broken": targets,
                   "completion_time_passed": rows - 1, "completion_input_tick": rows} if end_reason == "clear" else {})
    meta = {"artifact_schema": 1, "format": "battleship_btt_episode", "action_contract": "rlaction_native_v1",
            "episode_id": d.name, "action_count": rows, "actions_with_result": rows, "status": end_reason,
            "labels": {"experiment": {"task_id": "ssb64_us_mario_btt_v1", "gate": "m9_g1", "milestone": "M9"},
                       "m9_kind": kind, "phase": phase},
            "terminal": {"end_reason": end_reason, "ticks": rows, "targets_broken": targets, "completion": completion},
            "m9": {"native_action_digest": digest, "prefix_words": prefix, "kind": kind},
            "initial_observation": None, "final_observation": None,
            "diagnostics": {"created_utc": "2026-10-07T16:48:37Z", "wall_s": None}}
    with open(d / "metadata.json", "w", encoding="utf-8", newline="\n") as fp:
        json.dump(meta, fp)
    return d


@test
def m9_artifacts_are_runs_with_clears() -> None:
    """M9 artifacts record no labels.role, cleared flag or completion labels: the role is labels.phase (so the
    tests rule does not hide them), the profile labels.m9_kind, the end terminal.end_reason (clear | fall |
    horizon) with a clear's clocks in terminal.completion, steps and last tick from actions_with_result and
    terminal.ticks, the digest and prefix under m9. The viewer expects the same facts."""
    from replay_episode import episode_summary, expected_outcome

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "runs"
        clear = write_m9_episode(root / "m9_g1" / "artifacts" / "fine-2100-06", phase="eval", kind="fine",
                                 end_reason="clear", rows=5, targets=10, prefix=2)
        horizon = write_m9_episode(root / "m9_g3" / "s2" / "artifacts" / "train-0000042", phase="train", kind="train",
                                   end_reason="horizon", rows=6, targets=9)
        fall = write_m9_episode(root / "m9_g3" / "s2" / "artifacts" / "audit_sticky-2128-03", phase="audit",
                                kind="audit_sticky", end_reason="fall", rows=4, targets=8)
        age(root)
        db = Path(tmp) / "i.sqlite"
        ri.scan(root=root, db_path=db, progress=lambda m: None)
        rows = {r["episode_id"]: r for r in ri.load_rows(db_path=db, verdicts_path=Path(tmp) / "v.jsonl")}
        c = rows["fine-2100-06"]
        assert (c["role"], c["profile"], c["end_label"], c["cleared"], c["is_test"]) == ("eval", "fine", "clear", 1,
                                                                                         False), c
        assert (c["completion_tick"], c["completion_time"], c["steps"], c["last_tick"], c["prefix_rows"]) == (5, 4, 5, 4, 2)
        assert (c["character_name"], c["stage"], c["targets"], c["format"]) == ("Mario", "btt_mario", 10,
                                                                                 "battleship_btt_episode")
        assert (c["last_target_text"], c["last_target_source"], c["time_text"]) == ("4 · 0.07 s", "completion", "0.07 s")
        assert (c["milestone"], c["run"], c["created_text"] != "") == ("m9_g1", "", True)
        h = rows["train-0000042"]
        assert (h["role"], h["profile"], h["end_label"], h["cleared"], h["completion_tick"], h["is_test"]) == (
            "train", "train", "timeout", 0, None, False)
        assert (h["steps"], h["last_tick"], h["prefix_rows"], h["time_text"], h["run"]) == (6, 5, None, "5 · 0.1 s", "s2")
        f = rows["audit_sticky-2128-03"]
        assert (f["role"], f["profile"], f["end_label"], f["last_tick"], f["targets"]) == ("audit", "audit_sticky",
                                                                                           "fall", 3, 8)
        assert not any(r["is_test"] for r in rows.values())
        ep = load_episode(clear)
        e = expected_outcome(ep)
        assert (e.end_kind, e.steps, e.last_consumed_tick, e.targets_broken, e.completion_input_tick,
                e.completion_time_passed) == ("clear", 5, 4, 10, 5, 4)
        assert e.recorded_digest == e.file_digest and e.initial_observation is None and e.final_observation is None
        s = episode_summary(ep)
        assert (s["role"], s["profile"], s["prefix_rows"], s["end"], s["character"]) == ("eval", "fine", 2, "clear",
                                                                                         "mario")
        assert recorded_end(load_episode(horizon).metadata) == ("truncated", "end_reason=horizon")
        assert recorded_end(load_episode(fall).metadata) == ("fall", "end_reason=fall")


# -- replay_lab: the fast-route lab as a read-only source ----------------------------------------------------------


def write_lab_clear(run_dir: Path, *, n: int, cid: int, k: int, words: List[int], verdict: str = "VERIFIED",
                    digest: Optional[str] = None, trace: bool = True) -> Dict[str, Any]:
    """One lab verification row (appended to run_dir/verifications.jsonl, the lab's own format) for a tick-0 word
    sequence that clears on its last word, plus its r1 trace: the initial reply and one reply per word, the last
    one EpisodeEnded with 0 targets left (10 targets, breaking evenly)."""
    import gzip

    from m8_rd_cells import words_digest

    run_dir.mkdir(parents=True, exist_ok=True)
    seq = bytes(words)
    t = len(seq)
    remaining = [10 - (i + 1) * 10 // t for i in range(t)]
    breaks = [[i, target] for i in range(t) for target in range(remaining[i - 1] if i else 10, remaining[i], -1)]
    row = {"mode": "lab", "kind": "clear", "n": n, "cid": cid, "k": k, "level": 9, "start_tick": 1, "lead": 5,
           "words": t, "words_hex": seq.hex(), "words_digest": digest or words_digest(seq), "verdict": verdict,
           "reasons": [], "completion_input_tick": t, "completion_time_passed": t - 1, "chain_r1": "ab" * 32,
           "chain_r2": "ab" * 32, "clocks_r1": [t, t - 1], "clocks_r2": [t, t - 1], "breaks_r1": breaks,
           "breaks_r2": breaks, "gain_vs_reference": 1885 - t, "reference_completion_input_tick": 1885,
           "utc": "2026-10-15T20:19:45Z", "phase": "search"}
    with open(run_dir / "verifications.jsonl", "a", encoding="utf-8", newline="\n") as fp:
        fp.write(json.dumps(row, separators=(",", ":")) + "\n")
    if trace:
        (run_dir / "traces").mkdir(exist_ok=True)
        steps = [{"consumed_tick": i, "state_name": "EpisodeEnded" if i == t - 1 else "WaitingForAction",
                  "step_count": i + 1, "observation": obs(input_tick=i + 1, time_passed=i, targets_remaining=remaining[i],
                                                         game_status=5 if i == t - 1 else 1)} for i in range(t)]
        with gzip.open(run_dir / "traces" / f"clear_n{n}_c{cid}_k{k}_r1.json.gz", "wt", encoding="utf-8") as fp:
            json.dump({"label": f"clear_n{n}_c{cid}_k{k}_r1", "initial": {"observation": obs()}, "steps": steps,
                       "submitted": t, "action_digest": row["words_digest"]}, fp)
    return row


@test
def lab_source_lists_and_plays_verified_clears() -> None:
    """The lab's verified clears (verifications.jsonl + r1 traces, read-only) are browser rows labelled
    LAB (unregistered), fastest first, one per distinct word sequence; a clear loads from its trace path with
    rows decoded from its exact words (digest-checked), its expected outcome is the recorded verification, and
    feeding that replay gives MATCH; a tampered digest, an unverified row and a stranger file are refused."""
    import replay_browser as rbw
    import replay_lab
    from m8_rd_cells import TRIPLES
    from replay_episode import (ReplayTracker, artifact_format, episode_summary, expected_outcome, is_route,
                                load_route_trace, resolve_episode_dir)
    from replay_game import recorded_runtime_config

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve() / "lab"
        crossing = root / "crossing_x" / "run"
        config = root / "import" / "exe" / "BattleShip.cfg.json"
        config.parent.mkdir(parents=True)
        config.write_text("{}", encoding="utf-8")
        write_lab_clear(crossing, n=5, cid=2, k=0, words=[0x33, 0x3F, 0x00, 0x2F])  # 4 words
        fast = write_lab_clear(crossing, n=7, cid=3, k=1, words=[0x33, 0x3F, 0x05])  # 3 words: the fastest
        write_lab_clear(crossing, n=9, cid=3, k=2, words=[0x33, 0x3F, 0x05])  # the same words, found again
        write_lab_clear(crossing, n=11, cid=4, k=0, words=[1, 2], verdict="MISMATCH")  # not verified: never listed
        write_lab_clear(crossing, n=13, cid=5, k=0, words=[1, 2, 3], digest="0" * 64)  # recorded digest != its words
        with open(crossing / "verifications.jsonl", "a", encoding="utf-8", newline="\n") as fp:
            fp.write('{"mode":"lab","kind":"seed","n":12}\n{"mode":"lab","kind":"clear","n":99')  # other kind; partial
        smoke = root / "smoke_x" / "run"
        write_lab_clear(smoke, n=1, cid=0, k=0, words=[0x33, 0x3F], trace=False)  # verified, but no r1 trace
        with open(smoke / "verifications.jsonl", "a", encoding="utf-8", newline="\n") as fp:  # an older record shape
            fp.write(json.dumps({"mode": "lab", "kind": "clear", "verdict": "VERIFIED", "words": 2, "words_hex": "333f",
                                 "completion_input_tick": 2}) + "\n")
        (root / "frontier_x" / "run").mkdir(parents=True)  # a lab run without verifications
        with open(Path(tmp) / "v.jsonl", "w", encoding="utf-8", newline="\n") as fp:  # this tool's own replay of one
            fp.write(json.dumps({"episode_dir": str(crossing / "traces" / "clear_n5_c2_k0_r1.json.gz"),
                                 "verdict": "MATCH", "mode": "headless"}) + "\n")

        scan = replay_lab.scan_lab(root, ri.load_verdicts(Path(tmp) / "v.jsonl"))
        assert (scan["runs"], scan["verified"], scan["distinct"], scan["listed"], scan["no_trace"],
                scan["unaddressable"], scan["unparsable"]) == (2, 5, 4, 3, 1, 1, 1), scan
        rows = scan["rows"]
        assert [r["episode_id"] for r in rows] == [  # fastest first (3, 3, 4 words), then by dispatch
            "lab_crossing_x_n7_c3_k1", "lab_crossing_x_n13_c5_k0", "lab_crossing_x_n5_c2_k0"]
        by_id = {r["episode_id"]: r for r in rows}
        r = rows[0]
        assert r["milestone"] == replay_lab.LAB_LABEL == "LAB (unregistered)" and r["role"] == "lab" and r["lab"]
        assert (r["format"], r["end_label"], r["cleared"], r["targets"], r["targets_total"]) == (
            "frs_lab_clear_v1", "clear", 1, 10, 10)
        assert (r["completion_tick"], r["completion_time"], r["steps"], r["rows"], r["last_tick"]) == (3, 2, 3, 3, 2)
        assert (r["last_target_text"], r["last_target_source"], r["time_text"]) == ("2 · 0.03 s", "completion", "0.03 s")
        trace = crossing / "traces" / "clear_n7_c3_k1_r1.json.gz"
        assert r["path"] == trace.as_posix() and not r["is_test"] and r["character_name"] == "?"
        assert (r["run"], r["run_id"], r["worker"], r["created_text"] != "") == ("crossing_x", "crossing_x", None, True)
        assert r["profile"].startswith("LAB (unregistered)") and ri.matches_text(r, "lab (unreg")
        details = dict(r["tag_details"])
        assert details["found"] == "dispatch 7, cell 3, k 1; the same words were verified 2 times", details
        assert details["gain"] == "1882 input ticks faster than the reference (1885)" and r["tags"] == []
        slow = by_id["lab_crossing_x_n5_c2_k0"]
        assert (slow["replay"], slow["replay_mode"], r["replay"]) == ("MATCH", "headless", None)
        assert "3 verified clears in 2 lab runs" in scan["text"] and "1 without an r1 trace" in scan["text"]
        assert "1 repeat finds" in scan["text"] and "1 unparsable" in scan["text"], scan["text"]
        assert "1 verified clears in another record shape" in scan["text"], scan["text"]
        assert replay_lab.scan_lab(root / "missing")["rows"] == [] and replay_lab.lab_runs(root / "missing") == []
        db = Path(tmp) / "i.sqlite"
        merged = ri.load_rows_and_lab(root, db_path=db, verdicts_path=Path(tmp) / "v.jsonl")
        assert [x["episode_id"] for x in merged] == [x["episode_id"] for x in rows]  # an empty index + the lab
        assert ri.load_rows_and_lab(None, db_path=db, verdicts_path=Path(tmp) / "v.jsonl") == []
        best = rbw.best_per_run(rows, rows)
        assert len(best) == 1 and best[0] is r and best[0]["run_count_text"] == "3"

        assert replay_lab.is_lab_trace(trace) and not replay_lab.is_lab_trace(crossing / "verifications.jsonl")
        assert resolve_episode_dir(trace) == trace
        ep = load_episode(trace)
        assert ep.episode_id == "lab_crossing_x_n7_c3_k1" and is_route(ep.metadata) and ep.directory == trace
        assert artifact_format(ep.metadata) == "frs_lab_clear_v1" and ep.metadata["runtime_config"] == str(config)
        assert [(x.buttons, x.stick_x, x.stick_y, x.consumed_tick) for x in ep.rows] == [
            (*TRIPLES[w], i) for i, w in enumerate([0x33, 0x3F, 0x05])]
        assert ep.rows[0].stick_x == -80 and ep.rows[0].stick_y == -80 and ep.rows[0].buttons == 0x0008  # word 0x33
        assert recorded_end(ep.metadata) == ("clear", "lab claim clear, terminal clear")
        assert recorded_runtime_config(ep) == config
        e = expected_outcome(ep)
        assert (e.end_kind, e.steps, e.last_consumed_tick, e.targets_broken, e.completion_input_tick,
                e.completion_time_passed) == ("clear", 3, 2, 10, 3, 2)
        assert e.recorded_digest == e.file_digest == fast["words_digest"] and e.initial_observation and e.final_observation
        s = episode_summary(ep)
        assert (s["role"], s["run_id"], s["profile"]) == ("lab", "crossing_x", "LAB (unregistered) clear n7 c3 k1")
        tr = ReplayTracker(ep)
        doc = load_route_trace(ep.directory)
        tr.feed_initial(doc["initial"]["observation"])
        for row, step in zip(ep.replay_rows, doc["steps"]):
            tr.feed_step(row, step["state_name"], step["step_count"], step["consumed_tick"], step["observation"])
            if tr.ended:
                break
        v = compare(tr)
        assert v.match and not v.skipped and tr.end_kind == "clear" and len(v.checks) == 10, v.lines()
        assert tr.trajectory.target_break_ticks == [0, 0, 0, 1, 1, 1, 2, 2, 2, 2]
        for bad, text in ((crossing / "traces" / "clear_n13_c5_k0_r1.json.gz", "not the verified words"),
                          (crossing / "traces" / "clear_n11_c4_k0_r1.json.gz", "not VERIFIED"),
                          (crossing / "verifications.jsonl", "not an episode directory")):
            try:
                load_episode(bad)
                raise AssertionError(f"{bad.name} must be refused")
            except EpisodeError as exc:
                assert text in str(exc), exc
        assert sorted(p.name for p in root.rglob("*") if p.is_file() and p.suffix not in (".jsonl", ".gz", ".json")) == []


@test
def lab_lock_refuses_game_replays() -> None:
    """While <lab root>/lab.lock exists no game replay starts: the viewer exits with the usage code before loading
    anything, every GameProcess.launch raises (no session files), and the browser's Play / Check set a status and
    spawn nothing. The root comes from the override, else BATTLESHIP_LAB_ROOT (empty = off)."""
    import replay
    import replay_browser as rbw
    import replay_lab
    from replay_game import GameProcess, ReplayRuntimeError

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve() / "lab"
        root.mkdir()
        assert replay_lab.lab_root(root) == root and replay_lab.lab_root(root / "missing") is None
        assert replay_lab.lab_lock(root) is None
        previous = os.environ.get(replay_lab.ROOT_ENV)
        try:
            os.environ[replay_lab.ROOT_ENV] = str(root)
            assert replay_lab.lab_root() == root and replay_lab.lab_lock() is None
            (root / "lab.lock").write_text("pid 1\n", encoding="utf-8")
            assert replay_lab.lab_lock() == replay_lab.lab_lock(root) == root / "lab.lock"
            import contextlib
            import io

            with contextlib.redirect_stderr(io.StringIO()) as err:
                codes = replay.main([str(root / "nothing"), "--check"]), replay.main([str(root / "nothing")])
            assert codes == (2, 2) and err.getvalue().count("a lab run is active") == 2, (codes, err.getvalue())
            game = GameProcess(root / "BattleShip.exe", root / "session", headless=True, base_config=root / "cfg.json")
            try:
                game.launch()
                raise AssertionError("launch must refuse while lab.lock exists")
            except ReplayRuntimeError as exc:
                assert "lab run is active" in str(exc) and "lab.lock" in str(exc), exc
            assert not (root / "session").exists() and game.process is None
            run = root / "crossing_x" / "run"
            write_lab_clear(run, n=1, cid=1, k=0, words=[0x33, 0x3F])
            b = rbw.Browser(lambda: replay_lab.rows(root), lambda **kw: {}, lab_root=root,
                            sources_path=root / "sources.json")
            b.root.withdraw()
            try:
                assert b.root.title().endswith(f"LAB (unregistered) {root}") and b.index_info.get().endswith(
                    "lab: 1 verified clears"), (b.root.title(), b.index_info.get())
                b.table.select(0)
                assert b.selected()["episode_id"] == "lab_crossing_x_n1_c1_k0"
                assert b._spawn([], capture=False) is None and b.children == []
                assert b.status.get().startswith("replay refused: a lab run is active"), b.status.get()
                b.check_filtered()
                assert b.batch is None and b.status.get().startswith("replay refused")
            finally:
                b.root.destroy()
            os.environ[replay_lab.ROOT_ENV] = ""
            assert replay_lab.lab_root() is None and replay_lab.lab_lock() is None  # empty = the lab is off
        finally:
            if previous is None:
                os.environ.pop(replay_lab.ROOT_ENV, None)
            else:
                os.environ[replay_lab.ROOT_ENV] = previous


def main() -> int:
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
