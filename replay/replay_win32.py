#!/usr/bin/env python3
"""Small ctypes helpers for the replay viewer (Windows only; every function degrades to a no-op elsewhere).

Used to find the BattleShip window of a process, keep the HUD overlay on top
of its client area, make the overlay click-through, read hotkeys while the
game window has focus, and lower the game's CPU priority while the viewer is
paused. Nothing here touches the game's memory or input.
"""

from __future__ import annotations

import ctypes
import sys
from typing import List, Optional, Tuple

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsIconic.argtypes = [wintypes.HWND]
    _user32.IsWindow.argtypes = [wintypes.HWND]
    _user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    _user32.GetAncestor.restype = wintypes.HWND
    _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    _user32.GetAsyncKeyState.restype = ctypes.c_short
    _user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _GetWindowLong = getattr(_user32, "GetWindowLongPtrW", _user32.GetWindowLongW)
    _SetWindowLong = getattr(_user32, "SetWindowLongPtrW", _user32.SetWindowLongW)
    _GetWindowLong.argtypes = [wintypes.HWND, ctypes.c_int]
    _GetWindowLong.restype = ctypes.c_ssize_t
    _SetWindowLong.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    _SetWindowLong.restype = ctypes.c_ssize_t
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
GA_ROOT = 2
PROCESS_SET_INFORMATION = 0x0200
IDLE_PRIORITY_CLASS = 0x00000040
NORMAL_PRIORITY_CLASS = 0x00000020

VK = {"space": 0x20, "right": 0x27, "left": 0x25, "plus": 0xBB, "minus": 0xBD, "add": 0x6B, "subtract": 0x6D,
      "period": 0xBE}


def find_process_window(pid: int) -> Optional[int]:
    """The largest visible top-level window owned by pid (BattleShip has exactly one)."""
    if not IS_WINDOWS or pid is None:
        return None
    found: List[Tuple[int, int]] = []

    def callback(hwnd, _lparam):
        owner = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and _user32.IsWindowVisible(hwnd):
            r = wintypes.RECT()
            _user32.GetWindowRect(hwnd, ctypes.byref(r))
            found.append(((r.right - r.left) * (r.bottom - r.top), int(hwnd)))
        return True

    _user32.EnumWindows(_WNDENUMPROC(callback), 0)
    if not found:
        return None
    return max(found)[1]


def is_window(hwnd: Optional[int]) -> bool:
    return bool(IS_WINDOWS and hwnd and _user32.IsWindow(hwnd))


def is_minimized(hwnd: Optional[int]) -> bool:
    return bool(IS_WINDOWS and hwnd and _user32.IsIconic(hwnd))


def client_rect_on_screen(hwnd: Optional[int]) -> Optional[Tuple[int, int, int, int]]:
    """(x, y, width, height) of the client area in screen coordinates."""
    if not is_window(hwnd):
        return None
    r = wintypes.RECT()
    if not _user32.GetClientRect(hwnd, ctypes.byref(r)):
        return None
    p = wintypes.POINT(0, 0)
    if not _user32.ClientToScreen(hwnd, ctypes.byref(p)):
        return None
    return int(p.x), int(p.y), int(r.right - r.left), int(r.bottom - r.top)


def window_rect(hwnd: Optional[int]) -> Optional[Tuple[int, int, int, int]]:
    """(left, top, right, bottom) of the whole window in screen coordinates."""
    if not is_window(hwnd):
        return None
    r = wintypes.RECT()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return int(r.left), int(r.top), int(r.right), int(r.bottom)


SHELL_CLASSES = ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd")


def class_name(hwnd: Optional[int]) -> str:
    if not is_window(hwnd):
        return ""
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def is_shell_window(hwnd: Optional[int]) -> bool:
    """Desktop and taskbar: focusing them does not cover the game window."""
    return class_name(hwnd) in SHELL_CLASSES


def rects_intersect(a: Optional[Tuple[int, int, int, int]], b: Optional[Tuple[int, int, int, int]]) -> bool:
    if a is None or b is None:
        return False
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def foreground_root() -> Optional[int]:
    if not IS_WINDOWS:
        return None
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return None
    root = _user32.GetAncestor(hwnd, GA_ROOT)
    return int(root or hwnd)


def root_of(hwnd: Optional[int]) -> Optional[int]:
    if not is_window(hwnd):
        return None
    return int(_user32.GetAncestor(hwnd, GA_ROOT) or hwnd)


def make_click_through(hwnd: Optional[int]) -> bool:
    """Mouse clicks pass through the overlay to the game window; the overlay never takes focus."""
    if not is_window(hwnd):
        return False
    style = _GetWindowLong(hwnd, GWL_EXSTYLE)
    _SetWindowLong(hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
    return True


def key_down(name: str) -> bool:
    if not IS_WINDOWS:
        return False
    return bool(_user32.GetAsyncKeyState(VK[name]) & 0x8000)


def set_priority(pid: Optional[int], idle: bool) -> bool:
    """IDLE priority while paused (the parked host loop spins with SSB64_FREEZE_PACING=0), NORMAL otherwise.
    Scheduling priority cannot change game logic: every tick is gated by the stepping protocol."""
    if not IS_WINDOWS or not pid:
        return False
    handle = _kernel32.OpenProcess(PROCESS_SET_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        return bool(_kernel32.SetPriorityClass(handle, IDLE_PRIORITY_CLASS if idle else NORMAL_PRIORITY_CLASS))
    finally:
        _kernel32.CloseHandle(handle)
