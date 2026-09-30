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
