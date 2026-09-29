#!/usr/bin/env python3
"""BattleShip episode replay viewer.

    python replay/replay.py <episode dir | actions.jsonl> [options]
    replay\\replay.cmd <episode dir | actions.jsonl> [options]        (Windows wrapper)

Launches BattleShip windowed from the same fresh tick-0 state training uses,
submits row T of actions.jsonl as the input of native tick T (one native
update per row) and shows it at up to 60 fps, with a control panel and a HUD
overlay on the game window. At the end it compares the replayed outcome with
metadata.json and prints MATCH or DESYNC.

    --check          no window: replay headless (training's no-render mode) as
                     fast as possible, print MATCH/DESYNC and exit
    --play           start playing immediately (default: paused at tick 0)
    --speed S        0.25, 0.5, 1, 2 or 4 (rendered playback is capped at 1x)
    --start-tick N   fast-forward to tick N first
    --exit-at-end    close everything after the verdict (scripted runs)

Exit codes: 0 MATCH, 1 DESYNC, 2 bad arguments or artifact, 3 BattleShip
failed or the replay did not reach the end.

Keys (control panel, or the game window while it has focus): Space play/pause,
Right or . single step, + / - speed, R restart, G jump, Q / Esc quit.
Do not press other keys in the game window (Ctrl+R resets the game, the Esc
menu can change gameplay settings); either would desync the replay.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from replay_episode import EpisodeError, episode_summary, format_verdict, load_episode  # noqa: E402
from replay_game import (DEFAULT_EXE, SPEEDS, Geometry, ReplayEngine, ReplayRuntimeError, check_episode,  # noqa: E402
                         executable_identity, load_state, record_verdict)

EXIT_MATCH, EXIT_DESYNC, EXIT_USAGE, EXIT_RUNTIME = 0, 1, 2, 3


def parse_size(text: str) -> tuple:
    try:
        w, h = (int(v) for v in text.lower().split("x"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected WIDTHxHEIGHT, got {text!r}")
    if w < 320 or h < 240:
        raise argparse.ArgumentTypeError("the window must be at least 320x240")
    return w, h


def parse_speed(text: str) -> float:
    v = float(text)
    if v not in SPEEDS:
        raise argparse.ArgumentTypeError(f"speed must be one of {', '.join(f'{s:g}' for s in SPEEDS)}")
    return v


def main(argv=None) -> int:
    for name in ("stdout", "stderr"):  # pythonw has no console streams; the launchers redirect them to a log
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n\n", 2)[2])
    ap.add_argument("episode", help="episode directory or its actions.jsonl")
    ap.add_argument("--check", action="store_true", help="headless replay + MATCH/DESYNC, no window")
    ap.add_argument("--play", action="store_true", help="start playing immediately")
    ap.add_argument("--speed", type=parse_speed, default=1.0)
    ap.add_argument("--start-tick", type=int, default=None)
    ap.add_argument("--exit-at-end", action="store_true")
    ap.add_argument("--size", type=parse_size, default=None, help="game window client size, e.g. 960x720")
    ap.add_argument("--no-hud", action="store_true", help="control panel only, no overlay on the game window")
    ap.add_argument("--exe", type=Path, default=DEFAULT_EXE, help=f"BattleShip executable (default {DEFAULT_EXE})")
    ap.add_argument("--keep-session", action="store_true", help="keep replay/_local/sessions/<id> for debugging")
    args = ap.parse_args(argv)

    try:
        ep = load_episode(args.episode)
    except EpisodeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if not args.exe.is_file():
        print(f"error: executable not found: {args.exe}", file=sys.stderr)
        return EXIT_USAGE
    s = episode_summary(ep)
    print(f"episode {s['episode_id']}  role={s['role']} run={s['run_id']} profile={s['profile']}")
    print(f"  {s['directory']}")
    print(f"  recorded: end={s['end']} ({s['end_detail']}), targets={s['targets_broken']}, "
          f"rows={s['rows']} (replayable {s['rows_to_replay']}), prefix rows={s['prefix_rows']}")
    sys.stdout.flush()

    if args.check:
        try:
            verdict, tracker = check_episode(ep, executable=args.exe, keep_session=args.keep_session)
        except (ReplayRuntimeError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_RUNTIME
        print(format_verdict(ep, tracker, verdict))
        try:
            record_verdict(ep, tracker, verdict, mode="headless", exe=executable_identity(args.exe))
        except OSError as exc:
            print(f"note: verdict not recorded: {exc}")
        if not tracker.ended:
            return EXIT_RUNTIME
        return EXIT_MATCH if verdict.match else EXIT_DESYNC

    geometry = Geometry()
    saved = load_state().get("game_window")
    if isinstance(saved, dict):
        geometry = Geometry(**{k: saved.get(k) for k in ("width", "height", "x", "y")})
    if args.size:
        geometry.width, geometry.height = args.size

    engine = ReplayEngine(ep, executable=args.exe, speed=args.speed, play=args.play, start_tick=args.start_tick,
                          geometry=geometry, keep_session=args.keep_session)
    try:
        import replay_ui
    except ImportError as exc:  # tkinter missing
        print(f"error: the viewer needs tkinter ({exc}); use --check for a headless replay", file=sys.stderr)
        return EXIT_USAGE
    ui = replay_ui.ViewerUI(engine, summary=s, hud=not args.no_hud, exit_at_end=args.exit_at_end)
    engine.start()
    try:
        ui.run()
    finally:
        engine.send("quit")
        engine.finished.wait(30)
    if engine.error:
        return EXIT_RUNTIME
    if engine.verdict is None:
        print(f"INCOMPLETE: stopped at tick {engine.cursor - 1} of {len(engine.rows)} rows (no verdict)")
        return EXIT_RUNTIME
    return EXIT_MATCH if engine.verdict.match else EXIT_DESYNC


if __name__ == "__main__":
    sys.exit(main())
