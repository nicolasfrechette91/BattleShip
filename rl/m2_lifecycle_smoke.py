#!/usr/bin/env python3
"""M2 lifecycle failure-path checks for rl/battleship_process.py.

Each case drives one BattleShipEpisode into a specific failure and checks the
classification and that cleanup left no process behind. Cases that need no
game use this Python interpreter as a stand-in executable; the others launch
the real BattleShip (build-us/Release/BattleShip.exe by default) and rely
only on existing native behaviour (the SSB64_MAX_FRAMES clean-exit debug aid
in port/port.cpp). No native hook exists for these tests.

    python rl/m2_lifecycle_smoke.py                      # every case
    python rl/m2_lifecycle_smoke.py child_env startup_failure startup_timeout   # no game needed

Cases:
  child_env          the child environment is isolated and the parent's is untouched
  startup_failure    the child exits before any transport exists (exit code preserved)
  startup_timeout    the child lives but never listens; cleanup terminates it
  readiness_timeout  real game: transport up, still Inactive at a short deadline; cleanup terminates it
  abort_mid_episode  real game: fresh, a few steps, then the context is left early; cleanup terminates it
  premature_exit     real game with SSB64_MAX_FRAMES: exits mid-episode with code 0, still a failure;
                     cleanup finds it already gone

Exit status is 0 only if every requested case passed. Standard library only.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Callable, Dict, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from battleship_client import BattleShipError, Button, StepState  # noqa: E402
from battleship_process import (  # noqa: E402
    BattleShipEpisode,
    EpisodeFailure,
    EpisodeOutcome,
    EpisodePaths,
    LaunchConfig,
    allocate_loopback_port,
    build_child_env,
    loopback_port_is_free,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXECUTABLE = REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"
NEUTRAL = (int(Button.NONE), 0, 0)


def log(message: str) -> None:
    print(message, flush=True)


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def expect_failure(fn: Callable[[], object], outcome: EpisodeOutcome) -> EpisodeFailure:
    try:
        fn()
    except EpisodeFailure as exc:
        expect(exc.outcome == outcome, f"expected {outcome.value}, got {exc.outcome.value}: {exc}")
        return exc
    raise AssertionError(f"expected {outcome.value}, but the call succeeded")


def python_config(args: argparse.Namespace, code: str, **overrides: object) -> LaunchConfig:
    """This interpreter as the child, running `code`; no transport ever appears."""
    fields = dict(
        executable=Path(sys.executable),
        arguments=("-c", code),
        working_dir=Path(tempfile.gettempdir()),
        run_root=args.run_root,
        startup_timeout=5.0,
        poll_interval=0.05,
    )
    fields.update(overrides)
    return LaunchConfig(**fields)


def game_config(args: argparse.Namespace, **overrides: object) -> LaunchConfig:
    fields = dict(
        executable=Path(args.exe),
        run_root=args.run_root,
        startup_timeout=args.startup_timeout,
        ready_timeout=args.ready_timeout,
        request_timeout=args.request_timeout,
        exit_timeout=args.exit_timeout,
    )
    fields.update(overrides)
    return LaunchConfig(**fields)


def check_gone(episode: BattleShipEpisode, expected_action: str) -> None:
    expect(not episode.alive, f"pid {episode.pid} still alive after cleanup")
    expect(
        episode.cleanup_action == expected_action,
        f"cleanup_action is {episode.cleanup_action}, expected {expected_action}",
    )
    again = episode.close()
    expect(again == expected_action, f"second close() returned {again}, expected {expected_action} (idempotent)")
    if episode.port is not None:
        expect(loopback_port_is_free(episode.port), f"port {episode.port} still accepts connections after cleanup")
    log(f"  cleanup={episode.cleanup_action} exit_code={episode.exit_code} pid={episode.pid} gone; close() idempotent")


# -- cases ------------------------------------------------------------------------


def case_child_env(args: argparse.Namespace) -> None:
    """build_child_env: mandatory settings, replay removed, parent untouched."""
    port = allocate_loopback_port()
    expect(1 <= port <= 65535 and loopback_port_is_free(port), f"allocated port {port} unusable")
    directory = Path(tempfile.mkdtemp(prefix="env_", dir=str(args.run_root)))
    paths = EpisodePaths(directory, directory / "save.bin", directory / "result.json", directory / "log.txt")
    config = LaunchConfig(executable=Path(sys.executable), extra_env={"SSB64_MAX_FRAMES": "5", "SSB64_RL_PORT": "1"})

    parent_before = dict(os.environ)
    saved = {k: os.environ.get(k) for k in ("SSB64_BTT_INPUT", "SSB64_MAX_FRAMES", "SSB64_RL_EXIT_ON_END")}
    os.environ["SSB64_BTT_INPUT"] = "inherited_replay.btti"  # simulate stale shell state
    os.environ["SSB64_RL_EXIT_ON_END"] = "0"
    try:
        env = build_child_env(config, port, paths)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    expect(dict(os.environ) == parent_before, "the parent environment was changed")
    expect("SSB64_BTT_INPUT" not in env, "SSB64_BTT_INPUT reached the child environment")
    expect(env["SSB64_RL_BTT"] == "1" and env["SSB64_RL_STEP"] == "1", "RL boot / stepping not set")
    expect(env["SSB64_RL_PORT"] == str(port), "extra_env must not override the episode port")
    expect(env["SSB64_RL_EXIT_ON_END"] == "1", "inherited SSB64_RL_EXIT_ON_END=0 must be overridden")
    expect(env["SSB64_SAVE_PATH"] == str(paths.save_path), "save path not isolated")
    expect(env["SSB64_RL_RESULT_PATH"] == str(paths.result_path), "result path not isolated")
    expect(env["SSB64_MAX_FRAMES"] == "5", "an explicit extra_env value must pass through")
    log(f"  port={port} mandatory keys set, SSB64_BTT_INPUT removed, parent environment unchanged")


def case_startup_failure(args: argparse.Namespace) -> None:
    """Child exits with code 3 before any transport: startup_failure, exit code kept."""
    config = python_config(args, "import sys; sys.exit(3)")
    with BattleShipEpisode(config, index=101) as episode:
        failure = expect_failure(episode.start, EpisodeOutcome.STARTUP_FAILURE)
        expect(failure.exit_code == 3, f"exit code {failure.exit_code}, expected 3")
        expect(episode.paths is not None and episode.paths.log_path.exists(), "no process log was created")
        log(f"  {failure.outcome.value} exit_code={failure.exit_code} reported before the 5 s startup deadline")
    check_gone(episode, "already_exited")


def case_startup_timeout(args: argparse.Namespace) -> None:
    """Child lives but never listens: startup_timeout at the deadline, then terminate()."""
    config = python_config(args, "import time; time.sleep(120)", startup_timeout=2.0)
    started = time.monotonic()
    with BattleShipEpisode(config, index=102) as episode:
        failure = expect_failure(episode.start, EpisodeOutcome.STARTUP_TIMEOUT)
        waited = time.monotonic() - started
        expect(1.5 <= waited <= 10.0, f"startup_timeout after {waited:.1f} s, expected about 2 s")
        expect(episode.alive, "the child should still be alive when startup_timeout is raised")
        log(f"  {failure.outcome.value} after {waited:.1f} s with pid {episode.pid} alive")
    check_gone(episode, "terminated")


def case_readiness_timeout(args: argparse.Namespace) -> None:
    """Real game: transport reachable, still Inactive at a 0.25 s readiness deadline."""
    config = game_config(args, ready_timeout=0.25)
    with BattleShipEpisode(config, index=103) as episode:
        failure = expect_failure(episode.start, EpisodeOutcome.READINESS_TIMEOUT)
        expect(episode.client is not None and "transport" in episode.timeline, "transport stage did not complete")
        expect(episode.alive, "the game should still be alive when readiness_timeout is raised")
        log(f"  {failure.outcome.value}: transport up after {episode.seconds('launched', 'transport'):.1f} s, "
            f"pid {episode.pid} alive")
    check_gone(episode, "terminated")


def case_abort_mid_episode(args: argparse.Namespace) -> None:
    """Real game: fresh episode, five neutral steps, then leave the context early."""
    config = game_config(args)
    with BattleShipEpisode(config, index=104) as episode:
        fresh = episode.start()
        expect(fresh.state == StepState.WAITING_FOR_ACTION and fresh.step_count == 0, f"not fresh: {fresh}")
        assert episode.client is not None
        last = None
        for tick in range(5):
            last = episode.client.step(*NEUTRAL)
            expect(last.consumed_tick == tick, f"consumed_tick {last.consumed_tick}, expected {tick}")
            expect(last.observation.input_tick == tick + 1, f"input_tick {last.observation.input_tick}")
        assert last is not None
        expect(last.step_count == 5, f"step_count {last.step_count}, expected 5")
        expect(episode.alive, "the game should be alive mid-episode")
        log(f"  fresh after {episode.seconds('launched', 'fresh'):.1f} s; 5 steps consumed ticks 0..4; leaving the "
            f"context with pid {episode.pid} parked")
    check_gone(episode, "terminated")
    assert episode.paths is not None
    expect(not episode.paths.result_path.exists(), "an aborted episode must not have a result JSON")
    log("  no result JSON was written for the aborted episode")


def case_premature_exit(args: argparse.Namespace) -> None:
    """Real game capped with SSB64_MAX_FRAMES: exits mid-episode with code 0, still a failure."""
    config = game_config(args, extra_env={"SSB64_MAX_FRAMES": str(args.max_frames)})
    with BattleShipEpisode(config, index=105) as episode:
        fresh = episode.start()
        expect(fresh.step_count == 0, f"not fresh: {fresh}")
        assert episode.client is not None
        steps = 0
        failure: Optional[EpisodeFailure] = None
        deadline = time.monotonic() + args.ready_timeout
        while failure is None:
            expect(time.monotonic() < deadline, f"the frame cap never ended the process after {steps} steps")
            try:
                result = episode.client.step(*NEUTRAL)
                steps += 1
                expect(result.state != StepState.EPISODE_ENDED, "neutral input must not clear the stage")
            except BattleShipError as exc:
                failure = episode.classify_step_failure(exc)
        expect(failure.outcome == EpisodeOutcome.PREMATURE_EXIT, f"expected premature_exit, got {failure}")
        expect(failure.exit_code == 0, f"exit code {failure.exit_code}, expected the clean-exit code 0")
        expect(not episode.alive, "premature_exit must only be reported once the process is gone")
        log(f"  {failure.outcome.value} after {steps} steps with exit_code=0 (classified as failure, not completion)")
    check_gone(episode, "already_exited")
    assert episode.paths is not None
    expect(not episode.paths.result_path.exists(), "no result JSON may exist without a clear")
    log("  no result JSON was written; finish() was never reached")


CASES: Dict[str, Callable[[argparse.Namespace], None]] = {
    "child_env": case_child_env,
    "startup_failure": case_startup_failure,
    "startup_timeout": case_startup_timeout,
    "readiness_timeout": case_readiness_timeout,
    "abort_mid_episode": case_abort_mid_episode,
    "premature_exit": case_premature_exit,
}
GAME_CASES = {"readiness_timeout", "abort_mid_episode", "premature_exit"}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cases", nargs="*", choices=sorted(CASES), help="cases to run, in order (default: all)")
    parser.add_argument("--exe", default=str(DEFAULT_EXECUTABLE), help="BattleShip executable (default: %(default)s)")
    parser.add_argument("--run-dir", default=None, help="parent of the per-case directories (default: a new temp dir)")
    parser.add_argument("--startup-timeout", type=float, default=60.0)
    parser.add_argument("--ready-timeout", type=float, default=180.0)
    parser.add_argument("--request-timeout", type=float, default=30.0)
    parser.add_argument("--exit-timeout", type=float, default=30.0)
    parser.add_argument("--max-frames", type=int, default=600,
                        help="SSB64_MAX_FRAMES for premature_exit; must exceed the boot frames (default: %(default)s)")
    args = parser.parse_args(argv)
    names = args.cases or list(CASES)
    args.run_root = Path(args.run_dir) if args.run_dir else Path(tempfile.mkdtemp(prefix="battleship_m2_smoke_"))
    if any(name in GAME_CASES for name in names) and not Path(args.exe).is_file():
        log(f"ERROR: executable not found: {args.exe}")
        return 2

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
    log(f"run_dir={args.run_root}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
