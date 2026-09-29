#!/usr/bin/env python3
"""Offline tests for the replay tools: no BattleShip process, no access to runs/.

    python replay/replay_tests.py

Every fixture is built in a temporary directory; the real index
(replay/_local/index.sqlite) and verdict log are never opened. Exit code 0
when every test passes.
"""

from __future__ import annotations

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


@test
def index_scan_incremental_and_sources() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "runs"
        db = Path(tmp) / "index.sqlite"
        verdicts = Path(tmp) / "verdicts.jsonl"
        stoch = root / "m7x" / "campaign" / "_eval" / "r1" / "final" / "stochastic"
        art = stoch / "workers" / "w00" / "artifacts"
        a = fall_episode(art / "episode_20260929T000000Z_aaaaaaaa")
        b = write_episode(art / "episode_20260929T000001Z_bbbbbbbb", rows_of(4),
                          labels={"role": "evaluation", "end_reason": "horizon", "truncation_reason": "max_episode_steps",
                                  "targets_broken": 4},
                          terminal={"step_count": 4, "last_consumed_tick": 3, "targets_broken": 4},
                          final=obs(input_tick=4, time_passed=3, targets_remaining=6, position_x=500.0))
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
        assert s1["added_or_updated"] == 2 and s1["skipped_recent"] == 1 and s1["skipped_no_metadata"] == 1, s1
        rows = {r["episode_id"]: r for r in ri.load_rows(db_path=db, verdicts_path=verdicts)}
        assert set(rows) == {a.name, b.name}, rows.keys()
        assert hidden.name not in rows and fresh.name not in rows
        ra, rb = rows[a.name], rows[b.name]
        assert (ra["end_kind"], ra["targets"], ra["last_tick"], ra["worker"]) == ("fall", 2, 2, "w00")
        assert (ra["left"], ra["left_tick"], ra["left_source"]) == (True, 2, "eval_metrics")
        assert (rb["left"], rb["left_source"], rb["crossing"]) == (False, "eval_metrics", False)
        # incremental: nothing changed -> nothing re-read; the recent one is picked up once it is old
        age(fresh)
        s2 = ri.scan(root=root, db_path=db, progress=lambda m: None)
        assert s2["added_or_updated"] == 1 and s2["unchanged"] == 2 and s2["summaries_read"] == 0, s2
        # a replay verdict (MATCH) outranks eval_metrics; a DESYNC verdict is shown but never used as evidence
        with open(verdicts, "w", encoding="utf-8") as fp:
            fp.write(json.dumps({"episode_dir": ra["path"], "verdict": "MATCH", "mode": "headless",
                                 "trajectory": {"first_left_entry": {"consumed_tick": 2}, "min_live_x": -2200.0}}) + "\n")
            fp.write(json.dumps({"episode_dir": rb["path"], "verdict": "DESYNC", "mode": "headless",
                                 "trajectory": {"first_left_entry": {"consumed_tick": 1}}}) + "\n")
        rows = {r["episode_id"]: r for r in ri.load_rows(db_path=db, verdicts_path=verdicts)}
        assert rows[a.name]["left_source"] == "replay" and rows[a.name]["replay"] == "MATCH"
        assert rows[b.name]["left"] is False and rows[b.name]["replay"] == "DESYNC"
        # a removed episode disappears on the next scan
        for p in sorted(b.rglob("*"), reverse=True):
            p.unlink()
        b.rmdir()
        s3 = ri.scan(root=root, db_path=db, progress=lambda m: None)
        assert s3["removed"] == 1, s3


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
