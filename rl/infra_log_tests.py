#!/usr/bin/env python3
"""INFRA_2026-11-04 fix 2: every game process writes its own port log, and its native error lines are kept.

Zero native ticks: every process here is rl/m8_rd_fakegame.py behind the REAL launcher (rl/battleship_process.py).

    python -B rl/infra_log_tests.py                  all tests
    python -B rl/infra_log_tests.py shared_log_legacy

Today every BattleShip process opens %APPDATA%\\BattleShip\\ssb64.log with truncation, so with parallel workers each boot
erases the other processes' lines. `shared_log_legacy` reproduces that with the fake game: worker A logs a native ERROR
line, worker B boots, and A's line is gone. `per_episode_logs` runs the same sequence with the fix (SSB64_LOG_PATH per
episode): both logs survive and A's ERROR line is kept by the launcher.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from battleship_process import LOG_PATH_ENV, NATIVE_LOG_SINK_DIR_ENV, BattleShipEpisode, LaunchConfig, build_child_env  # noqa: E402
from infra_testlib import check, cleanup, env_patch, fake_exe, run_suite, tmpdir, wait_for  # noqa: E402

ERROR_MARK = "SSB64 RL Step: ERROR: controller read"


def config(root: Path, exe: Path, *, error_at: int = 0, extra: Optional[Dict[str, str]] = None) -> LaunchConfig:
    env = {"FAKEGAME_BOOT_S": "0.1", "FAKEGAME_IDLE_S": "30", "FAKEGAME_PREF_DIR": str(root / "appdata")}
    if error_at:
        env["FAKEGAME_NATIVE_ERROR_AT_STEP"] = str(error_at)
    env.update(extra or {})
    return LaunchConfig(executable=exe, run_root=root / "episodes", startup_timeout=20.0, ready_timeout=20.0, request_timeout=10.0,
                        exit_timeout=10.0, terminate_timeout=5.0, kill_timeout=5.0, extra_env=env)


def setup(name: str) -> Dict[str, Any]:
    root = tmpdir(f"infra_{name}_")
    (root / "appdata").mkdir()
    return {"root": root, "exe": fake_exe(root), "shared": root / "appdata" / "ssb64.log"}


def text(path: Optional[Path]) -> str:
    return Path(path).read_text(encoding="utf-8") if path is not None and Path(path).is_file() else ""


def shared_log_legacy() -> Dict[str, Any]:
    """The bug as it is today (the launcher passes no SSB64_LOG_PATH): B's boot erases A's native ERROR line."""
    t = setup("shared")
    legacy = {LOG_PATH_ENV: ""}                                   # empty = unset for the native game and the fake
    a = BattleShipEpisode(config(t["root"], t["exe"], error_at=1, extra=legacy), index=1)
    b = BattleShipEpisode(config(t["root"], t["exe"], extra=legacy), index=2)
    try:
        a.start()
        a.client.step(0, 0, 0)
        check(wait_for(lambda: ERROR_MARK in text(t["shared"]), 5.0), "A's ERROR line reached the shared log")
        b.start()
        check(wait_for(lambda: f":{b.port} " in text(t["shared"]), 5.0), "B's boot wrote the shared log")
        lost = ERROR_MARK not in text(t["shared"])
        check(lost, "BUG REPRODUCED: B's boot truncated the shared log and A's ERROR line is gone")
        check(not a.paths.native_log_path.exists(), "with the legacy setting there is no per-episode log")
        return {"a_error_line_lost": lost, "shared_log_lines": len(text(t["shared"]).splitlines())}
    finally:
        b.close()
        a.close()
        cleanup(t["root"])


def per_episode_logs() -> Dict[str, Any]:
    """The fix: each episode has its own log; A's ERROR line survives B's boot and is kept by the launcher after close."""
    t = setup("per_episode")
    a = BattleShipEpisode(config(t["root"], t["exe"], error_at=1), index=1)
    b = BattleShipEpisode(config(t["root"], t["exe"]), index=2)
    try:
        a.start()
        a.client.step(0, 0, 0)
        b.start()
        b.client.step(0, 0, 0)
        la, lb = a.paths.native_log_path, b.paths.native_log_path
        check(la != lb and la.parent == a.paths.directory and lb.parent == b.paths.directory, "one log per episode directory")
        check(wait_for(lambda: ERROR_MARK in text(la), 5.0), "A's ERROR line is in A's own log after B booted")
        check(f":{a.port} " in text(la) and f":{b.port} " in text(lb) and f":{b.port} " not in text(la), "each log names only its own port")
        check(ERROR_MARK not in text(lb), "B's log holds none of A's lines")
        check(not t["shared"].exists(), "nothing was written to the shared log")
        check(any(ERROR_MARK in ln for ln in a.diagnostics()["native_log_flags"]), "the flagged line is in A's diagnostics while it runs")
        a.close()
        b.close()
        check(a.native_log_flags is not None and any(ERROR_MARK in ln for ln in a.native_log_flags), f"kept after close: {a.native_log_flags}")
        check(b.native_log_flags == [], f"B had nothing to flag: {b.native_log_flags}")
        return {"a_flags": len(a.native_log_flags), "b_flags": len(b.native_log_flags)}
    finally:
        b.close()
        a.close()
        cleanup(t["root"])


def sink_outlives_episode_dir() -> Dict[str, Any]:
    """With BATTLESHIP_NATIVE_LOG_SINK_DIR, the flagged lines are appended to the launcher's own sink file, with pid, port and
    nonce, and survive the removal of the episode directory (which the lab workers delete after every job)."""
    t = setup("sink")
    sink = t["root"] / "sink"
    try:
        with env_patch(**{NATIVE_LOG_SINK_DIR_ENV: str(sink)}):
            a = BattleShipEpisode(config(t["root"], t["exe"], error_at=2), index=1)
            with a:
                a.start()
                a.client.step(0, 0, 0)
                a.client.step(0, 0, 0)
            shutil.rmtree(a.paths.directory)
            f = sink / f"native_errors_{os.getpid()}.jsonl"
            rows = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()]
            check(len(rows) == 1 and ERROR_MARK in rows[0]["line"], f"one flagged line in the sink: {rows}")
            r = rows[0]
            check(r["child_pid"] == a.pid and r["port"] == a.port and r["launch_nonce"] == a.launch_nonce and r["launcher_pid"] == os.getpid(),
                  f"the sink row names its process: {r}")
            return {"sink_rows": len(rows)}
    finally:
        cleanup(t["root"])


def inherited_log_path_is_not_shared() -> Dict[str, Any]:
    """A SSB64_LOG_PATH in the launcher's own environment is never passed down (it would make children share a file again);
    an explicit LaunchConfig.extra_env value is."""
    root = tmpdir("infra_inherit_")
    try:
        from battleship_process import EpisodePaths

        paths = EpisodePaths(root, root / "s", root / "r", root / "l", native_log_path=root / "ssb64.log")
        with env_patch(**{LOG_PATH_ENV: str(root / "shared.log")}):
            env = build_child_env(LaunchConfig(executable=Path("x")), 30001, paths)
            check(env[LOG_PATH_ENV] == str(root / "ssb64.log"), f"the episode's own path wins over the inherited one: {env[LOG_PATH_ENV]}")
            env2 = build_child_env(LaunchConfig(executable=Path("x"), extra_env={LOG_PATH_ENV: str(root / "mine.log")}), 30001, paths)
            check(env2[LOG_PATH_ENV] == str(root / "mine.log"), "an explicit extra_env value is respected")
            legacy_paths = EpisodePaths(root, root / "s", root / "r", root / "l")
            env3 = build_child_env(LaunchConfig(executable=Path("x")), 30001, legacy_paths)
            check(LOG_PATH_ENV not in env3, "paths without a native log (older callers) set nothing")
        return {"ok": True}
    finally:
        cleanup(root)


TESTS = {
    "shared_log_legacy": shared_log_legacy,
    "per_episode_logs": per_episode_logs,
    "sink_outlives_episode_dir": sink_outlives_episode_dir,
    "inherited_log_path_is_not_shared": inherited_log_path_is_not_shared,
}

if __name__ == "__main__":
    sys.exit(run_suite("infra log tests", TESTS, sys.argv[1:]))
