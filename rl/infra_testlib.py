"""Shared helpers for the INFRA_2026-11-04 test suites (tests only; standard library only).

A fake 'executable directory' whose BattleShip entry point starts rl/m8_rd_fakegame.py: the M1d protocol over the
synthetic stub world, behind the REAL launcher (rl/battleship_process.py). THE WORLD IS SYNTHETIC: no game is run.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

RL_DIR = Path(__file__).resolve().parent
IS_WINDOWS = sys.platform == "win32"


class CheckFailed(AssertionError):
    pass


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise CheckFailed(msg)


def tmpdir(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def fake_exe(root: Path) -> Path:
    """The fake executable inside `root/exe`, with the read-only runtime files the worker runtime expects beside it.

    POSIX: a shell script that `exec`s the interpreter, so the launcher's child pid is the fake game's pid.
    Windows: a .cmd wrapper (as rl/m8_rd_tests.py uses); there the child pid is cmd.exe's, not the fake game's."""
    exe_dir = Path(root) / "exe"
    exe_dir.mkdir(parents=True, exist_ok=True)
    for n in ("f3d.o2r", "BattleShip.o2r", "gamecontrollerdb.txt"):
        (exe_dir / n).write_bytes(b"fake")
    (exe_dir / "BattleShip.cfg.json").write_text(json.dumps({"CVars": {}}), encoding="utf-8")
    (exe_dir / "imgui.ini").write_text("[fake]\n", encoding="utf-8")
    game = RL_DIR / "m8_rd_fakegame.py"
    if IS_WINDOWS:
        exe = exe_dir / "BattleShip.cmd"
        exe.write_text(f'@"{sys.executable}" -B "{game}"\r\n', encoding="utf-8")
    else:
        exe = exe_dir / "BattleShip"
        exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" -B "{game}" "$@"\n', encoding="utf-8")
        exe.chmod(0o755)
    return exe


def free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])
    finally:
        s.close()


def read_events(path: Path) -> List[Dict[str, Any]]:
    rows = []
    p = Path(path)
    for line in (p.read_text(encoding="utf-8").splitlines() if p.is_file() else []):
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    return rows


def wait_for(pred: Callable[[], bool], seconds: float, step: float = 0.05) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(step)
    return pred()


def run_suite(name: str, tests: Mapping[str, Callable[[], Dict[str, Any]]], argv: List[str]) -> int:
    """Run the named tests (all when argv is empty); print one PASS / FAIL line each and a summary."""
    chosen = [a for a in argv if not a.startswith("-")] or list(tests)
    unknown = [a for a in chosen if a not in tests]
    if unknown:
        print(f"unknown tests: {unknown}; known: {list(tests)}")
        return 2
    passed = 0
    t_all = time.monotonic()
    for t in chosen:
        t0 = time.monotonic()
        try:
            info = tests[t]()
            passed += 1
            print(f"PASS {t} ({time.monotonic() - t0:.1f} s) {json.dumps(info, default=str, sort_keys=True)[:400]}")
        except Exception as exc:  # noqa: BLE001 - every failure is reported, the suite continues
            print(f"FAIL {t} ({time.monotonic() - t0:.1f} s): {type(exc).__name__}: {exc}")
            traceback.print_exc()
    print(f"\n{name}: {passed}/{len(chosen)} passed in {time.monotonic() - t_all:.0f} s")
    return 0 if passed == len(chosen) else 1


def cleanup(path: Optional[Path]) -> None:
    if path is not None:
        shutil.rmtree(path, ignore_errors=True)


def env_patch(**values: Optional[str]) -> "EnvPatch":
    return EnvPatch(values)


class EnvPatch:
    def __init__(self, values: Mapping[str, Optional[str]]):
        self.values = dict(values)
        self.saved: Dict[str, Optional[str]] = {}

    def __enter__(self) -> "EnvPatch":
        for k, v in self.values.items():
            self.saved[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return self

    def __exit__(self, *exc: Any) -> None:
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
