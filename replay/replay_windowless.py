#!/usr/bin/env python3
"""Support for the windowless launchers (replay_gui.pyw, replay_open.pyw).

Under pythonw there is no console: sys.stdout / sys.stderr are None. The
launchers therefore send all output to replay/_local/launcher.log (rotated at
2 MB), work from any current directory (they chdir to the repository root),
and report failures in a message box that points at the log.
"""

from __future__ import annotations

import datetime as _dt
import os
import sys
import traceback
from pathlib import Path
from typing import Callable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_DIR = REPO_ROOT / "replay" / "_local"
LOG_FILE = LOCAL_DIR / "launcher.log"
MAX_LOG_BYTES = 2 * 1024 * 1024


def setup(name: str) -> Path:
    """Redirect stdout/stderr to the launcher log and make the repository root the working directory."""
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if LOG_FILE.stat().st_size > MAX_LOG_BYTES:
            os.replace(LOG_FILE, LOG_FILE.with_suffix(".log.1"))
    except OSError:
        pass
    fp = open(LOG_FILE, "a", encoding="utf-8", buffering=1, errors="replace")
    sys.stdout = fp
    sys.stderr = fp
    os.chdir(REPO_ROOT)
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"==== {stamp} {name} pid {os.getpid()} argv {sys.argv[1:]}")
    return LOG_FILE


def log_offset() -> int:
    try:
        sys.stdout.flush()
        return LOG_FILE.stat().st_size
    except OSError:
        return 0


def log_since(offset: int, limit: int = 1500) -> str:
    try:
        sys.stdout.flush()
        with open(LOG_FILE, encoding="utf-8", errors="replace") as fp:
            fp.seek(offset)
            text = fp.read().strip()
    except OSError:
        return ""
    return text if len(text) <= limit else "..." + text[-limit:]


def message(title: str, text: str, *, error: bool = True) -> None:
    """A modal message box (the only visible output of a windowless launcher)."""
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        (messagebox.showerror if error else messagebox.showinfo)(title, text, parent=root)
        root.destroy()
    except Exception:  # noqa: BLE001 - no Tk: the log still has the text
        print(f"[{title}] {text}")


def run(name: str, fn: Callable[[], Optional[int]], *, title: str) -> None:
    """setup(), call fn(), show any unexpected exception, exit with fn's code."""
    setup(name)
    code: Optional[int] = 3
    try:
        code = fn()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 2)
    except BaseException as exc:  # noqa: BLE001
        traceback.print_exc()
        message(title, f"{type(exc).__name__}: {exc}\n\nDetails: {LOG_FILE}")
    print(f"==== {name} exit {code}")
    sys.stdout.flush()
    sys.exit(code or 0)
