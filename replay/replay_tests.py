#!/usr/bin/env python3
"""Offline tests for the replay tools: no BattleShip process, no access to runs/.

    python replay/replay_tests.py

Every fixture is built in a temporary directory; the real index
(replay/_local/index.sqlite) and verdict log are never opened. The action-state
test reads the decomp status headers (read only); the panel test opens a
withdrawn Tk window. Exit code 0 when every test passes.
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
    """Names come from decomp/src/ft/ftdef.h + ftchar/ftmario/ftmario.h (read only); unknown ids stay numbers."""
    from replay_status import load_error, status_label, status_names

    names = status_names()
    assert names, load_error
    assert status_label(10) == "Wait (10)"  # nFTCommonStatusWait, not the ControlStart range marker
    assert status_label(26) == "Fall (26)" and status_label(24) == "JumpAerialF (24)"
    assert status_label(37) == "DamageHi1 (37)" and status_label(56) == "WallDamage (56)"  # marker aliases skipped
    assert status_label(62) == "DokanStart (62)"  # a real state whose own name ends in Start
    assert status_label(219) == "LandingAirNull (219)" and status_label(225) == "SpecialHi (225)"  # Mario's range
    assert len(names) == 229 and max(names) == 228
    assert status_label(229) == "229" and status_label(None) == "-" and status_label("x") == "x"


@test
def panel_texts() -> None:
    from replay_episode import Check, Row, Verdict
    from replay_ui import (BADGES, header_lines, live_columns, marker_groups, result_details, result_summary,
                           runs_relative, status_text, verdict_badge)

    s = {"episode_id": "episode_x", "role": "evaluation", "run_id": None, "profile": "m7p_geo4_s1",
         "observation": None, "reward": None, "end": "unknown", "end_detail": "not recorded", "targets_broken": None,
         "rows": 12, "rows_to_replay": 11, "prefix_rows": None}
    lines = header_lines(s)
    assert lines == ["role evaluation · profile m7p_geo4_s1", "rows 12 (11 replayable)"], lines
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
