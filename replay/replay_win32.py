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
import time
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
      "period": 0xBE, "comma": 0xBC}


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


def raise_current_thread_priority() -> bool:
    """THREAD_PRIORITY_ABOVE_NORMAL for the calling thread of this (viewer) process only."""
    if not IS_WINDOWS:
        return False
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentThread.restype = wintypes.HANDLE
    k32.SetThreadPriority.argtypes = [wintypes.HANDLE, ctypes.c_int]
    return bool(k32.SetThreadPriority(k32.GetCurrentThread(), 1))


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


# -- frame capture (saved-frame history) ---------------------------------------------------------------------------

PW_CLIENTONLY = 0x1
PW_RENDERFULLCONTENT = 0x2  # Windows 8.1+: the composed image, also for OpenGL/DirectX windows and occluded windows
COLORONCOLOR = 3  # nearest-pixel downscale (fast)
HALFTONE = 4  # area-averaged downscale (smoother)
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0

if IS_WINDOWS:
    _gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

    class _BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    class _BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

    _user32.GetDC.argtypes = [wintypes.HWND]
    _user32.GetDC.restype = wintypes.HDC
    _user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    _user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    _gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    _gdi32.CreateCompatibleDC.restype = wintypes.HDC
    _gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(_BITMAPINFO), wintypes.UINT,
                                        ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
    _gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    _gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    _gdi32.SelectObject.restype = wintypes.HGDIOBJ
    _gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    _gdi32.DeleteDC.argtypes = [wintypes.HDC]
    _gdi32.SetStretchBltMode.argtypes = [wintypes.HDC, ctypes.c_int]
    _gdi32.SetBrushOrgEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
    _gdi32.StretchBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                  wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    _gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HDC,
                              ctypes.c_int, ctypes.c_int, wintypes.DWORD]


class WindowCapturer:
    """Copies a window's client area into memory, downscaled by an integer divisor, as top-down 32-bit BGRX pixels.

    The window is read with one GDI BitBlt from its own DC into a full-size bitmap (~5 ms for 960x720 here;
    byte-identical to PrintWindow(PW_RENDERFULLCONTENT) for the OpenGL game window, measured; other windows on top,
    such as the HUD, are not included). `last_read_time` is taken right after that read: only the read has to beat
    the next frame. The downscale (StretchBlt, memory to memory) happens afterwards. PrintWindow is the fallback
    when the read fails or comes back black; it costs ~16 ms (it waits for DWM). GDI objects are reused; use one
    instance per thread."""

    def __init__(self, stretch_mode: int = HALFTONE) -> None:
        self.stretch_mode = stretch_mode
        self.fallbacks = 0
        self.last_read_time = 0.0  # time.perf_counter() right after the window was read
        self._key: Optional[Tuple[int, int, int]] = None
        self._objects: List[Tuple[int, int, int]] = []  # (dc, bitmap, old object)
        self._full: Optional[Tuple[int, int]] = None  # (dc, bits pointer), client size
        self._small: Optional[Tuple[int, int]] = None  # (dc, bits pointer), target size (divisor > 1)

    def _dib(self, screen_dc: int, w: int, h: int) -> Tuple[int, int]:
        bmi = _BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h  # top-down rows
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bits = ctypes.c_void_p()
        bmp = _gdi32.CreateDIBSection(screen_dc, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
        dc = _gdi32.CreateCompatibleDC(screen_dc)
        if not bmp or not dc or not bits.value:
            raise OSError("CreateDIBSection failed")
        old = _gdi32.SelectObject(dc, bmp)
        self._objects.append((dc, bmp, old))
        return dc, bits.value

    def _prepare(self, cw: int, ch: int, divisor: int) -> None:
        if self._key == (cw, ch, divisor):
            return
        self.close()
        screen_dc = _user32.GetDC(None)
        try:
            self._full = self._dib(screen_dc, cw, ch)
            if divisor > 1:
                self._small = self._dib(screen_dc, cw // divisor, ch // divisor)
                _gdi32.SetStretchBltMode(self._small[0], self.stretch_mode)
                _gdi32.SetBrushOrgEx(self._small[0], 0, 0, None)
        finally:
            _user32.ReleaseDC(None, screen_dc)
        self._key = (cw, ch, divisor)

    def _result(self, cw: int, ch: int, divisor: int) -> Tuple[int, int, bytes]:
        assert self._full is not None
        if divisor == 1:
            _gdi32.GdiFlush()
            return cw, ch, ctypes.string_at(self._full[1], cw * ch * 4)
        assert self._small is not None
        w, h = cw // divisor, ch // divisor
        _gdi32.StretchBlt(self._small[0], 0, 0, w, h, self._full[0], 0, 0, cw, ch, SRCCOPY)
        _gdi32.GdiFlush()
        return w, h, ctypes.string_at(self._small[1], w * h * 4)

    def capture(self, hwnd: Optional[int], divisor: int = 1) -> Optional[Tuple[int, int, bytes]]:
        """(width, height, BGRX bytes) of the client area / divisor, or None (no window, minimized, failure)."""
        if not IS_WINDOWS or not is_window(hwnd) or is_minimized(hwnd):
            return None
        r = wintypes.RECT()
        if not _user32.GetClientRect(hwnd, ctypes.byref(r)):
            return None
        cw, ch = int(r.right - r.left), int(r.bottom - r.top)
        divisor = max(1, int(divisor))
        if cw < divisor or ch < divisor:
            return None
        self._prepare(cw, ch, divisor)
        assert self._full is not None
        src = _user32.GetDC(hwnd)
        if src:
            try:
                ok = _gdi32.BitBlt(self._full[0], 0, 0, cw, ch, src, 0, 0, SRCCOPY)
                _gdi32.GdiFlush()
                self.last_read_time = time.perf_counter()
            finally:
                _user32.ReleaseDC(hwnd, src)
            if ok and (any(ctypes.string_at(self._full[1], 4096)) or self._probe_rows(cw, ch)):  # not all black
                return self._result(cw, ch, divisor)
        # Fallback: the composed image through DWM (slow, but also works where the window DC does not).
        self.fallbacks += 1
        if not _user32.PrintWindow(hwnd, self._full[0], PW_CLIENTONLY | PW_RENDERFULLCONTENT):
            return None
        self.last_read_time = time.perf_counter()
        return self._result(cw, ch, divisor)

    def _probe_rows(self, cw: int, ch: int) -> bool:
        """True if any of 16 rows spread over the full bitmap has a non-black pixel."""
        assert self._full is not None
        row = cw * 4
        for k in range(16):
            y = (ch - 1) * k // 15
            if any(ctypes.string_at(self._full[1] + y * row, row)):
                return True
        return False

    def close(self) -> None:
        for dc, bmp, old in self._objects:
            _gdi32.SelectObject(dc, old)
            _gdi32.DeleteObject(bmp)
            _gdi32.DeleteDC(dc)
        self._objects = []
        self._full = self._small = None
        self._key = None
