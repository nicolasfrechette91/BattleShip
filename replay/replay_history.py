#!/usr/bin/env python3
"""Saved-frame history for the replay viewer: step back through recently shown frames instantly.

The game only moves forward (no save states), but a replay is deterministic:
the frame shown for tick T is the same in every process that replays the
episode. So the viewer copies each rendered frame of the game window (plus
that tick's HUD data) into a bounded in-memory store right after the tick
returns, and Left/Right show stored frames over the game window without
touching the game. A tick that is not stored falls back to a rebuild: a fresh
process fast-forwarded to it (the frames of its last ticks are stored on the
way, so further steps back are instant again).

Tick -1 is the tick-0 state (the frame before the first input is consumed).
"live tick" is the last tick the game consumed (-1 before the first step).

Memory: frames are stored as RGB at (client width / scale) x (client height /
scale). For the default 960x720 window: scale 2 (half) = 518,400 B per frame,
so 10 s (600 frames) = 311 MB; scale 1 = 1.24 GB; scale 3 = 138 MB;
scale 4 = 78 MB. See history_bytes().
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

TICKS_PER_SECOND = 60
DEFAULT_SECONDS = 10.0
DEFAULT_SCALE = 2  # divisor: 2 = half resolution
CAPTURE_MODES = ("always", "slow")  # slow: only while paused/stepping, at <= 0.5x and near the end of jumps
FILTERS = ("smooth", "nearest")  # downscale: area-averaged (~4 ms CPU per frame at half res) or nearest (~0.4 ms)


@dataclass(frozen=True)
class HistoryConfig:
    seconds: float = DEFAULT_SECONDS  # 0 disables the history
    scale: int = DEFAULT_SCALE  # capture resolution = client size / scale (1..4)
    capture: str = "always"
    filter: str = "smooth"

    @property
    def frames(self) -> int:
        return max(0, int(round(self.seconds * TICKS_PER_SECOND)))

    @property
    def enabled(self) -> bool:
        return self.frames > 0


def frame_bytes(client_w: int, client_h: int, scale: int) -> int:
    return (client_w // scale) * (client_h // scale) * 3


def history_bytes(config: HistoryConfig, client_w: int = 960, client_h: int = 720) -> int:
    """Upper bound of the store's pixel memory for a full history."""
    return config.frames * frame_bytes(client_w, client_h, config.scale)


def bgrx_to_rgb(bgrx: bytes) -> bytes:
    """Top-down 32-bit BGRX (GDI DIB) -> packed RGB."""
    rgb = bytearray(len(bgrx) // 4 * 3)
    rgb[0::3] = bgrx[2::4]
    rgb[1::3] = bgrx[1::4]
    rgb[2::3] = bgrx[0::4]
    return bytes(rgb)


def ppm(width: int, height: int, rgb: bytes) -> bytes:
    """Binary PPM (P6): Tk's PhotoImage decodes it without any extra library."""
    return b"P6 %d %d 255\n" % (width, height) + rgb


@dataclass
class SavedFrame:
    tick: int  # consumed tick shown by this frame; -1 = tick-0 state
    width: int
    height: int
    rgb: bytes
    row: Any = None  # the Row whose input produced this frame (None for tick -1)
    observation: Dict[str, Any] = field(default_factory=dict)
    targets_broken: Optional[int] = None

    @property
    def nbytes(self) -> int:
        return len(self.rgb)


class FrameHistory:
    """Bounded tick -> SavedFrame store. Thread-safe: the engine thread adds, the UI thread reads.

    When full, the frame farthest from the anchor (the tick just added, i.e. where the game is) is dropped, so the
    store always holds the frames around the current position, also after a rebuild inserted older ticks."""

    def __init__(self, capacity: int):
        self.capacity = max(0, int(capacity))
        self._frames: Dict[int, SavedFrame] = {}
        self._lock = threading.Lock()

    def put(self, frame: SavedFrame) -> None:
        if self.capacity <= 0:
            return
        with self._lock:
            self._frames[frame.tick] = frame
            while len(self._frames) > self.capacity:
                oldest = min(self._frames)
                if frame.tick >= max(self._frames):  # normal playback: the oldest frame is the farthest one
                    victim = oldest
                else:
                    anchor = frame.tick
                    victim = max(self._frames, key=lambda t: (abs(t - anchor), -t))
                del self._frames[victim]

    def get(self, tick: int) -> Optional[SavedFrame]:
        with self._lock:
            return self._frames.get(tick)

    def __contains__(self, tick: int) -> bool:
        with self._lock:
            return tick in self._frames

    def __len__(self) -> int:
        with self._lock:
            return len(self._frames)

    def ticks(self) -> List[int]:
        with self._lock:
            return sorted(self._frames)

    @property
    def nbytes(self) -> int:
        with self._lock:
            return sum(f.nbytes for f in self._frames.values())

    def span(self) -> Optional[Tuple[int, int]]:
        with self._lock:
            return (min(self._frames), max(self._frames)) if self._frames else None

    def clear(self) -> None:
        with self._lock:
            self._frames.clear()


# -- navigation ------------------------------------------------------------------------------------------------------

# Plans returned by plan_view():
#   ("live", t)     show the live game (t == live tick)
#   ("saved", t)    show the stored frame of tick t
#   ("rebuild", t)  t is older than the live tick and not stored: fresh process + fast-forward to t
#   ("forward", t)  t is ahead of the live game: advance the game (step or fast-forward)
#   ("none", t)     nothing to do (before the tick-0 state, or past the last row)


def plan_view(target: int, live_tick: int, history: Optional[FrameHistory], last_tick: int) -> Tuple[str, int]:
    """Where tick `target` can be shown from. last_tick is the last replayable row."""
    if target < -1 or target > last_tick:
        return "none", target
    if target == live_tick:
        return "live", target
    if target > live_tick:
        return "forward", target
    if history is not None and target in history:
        return "saved", target
    return "rebuild", target


def plan_back(view_tick: Optional[int], live_tick: int, history: Optional[FrameHistory],
              last_tick: int) -> Tuple[str, int]:
    """One tick back from what is on screen (a stored frame, or the live game)."""
    current = live_tick if view_tick is None else view_tick
    return plan_view(current - 1, live_tick, history, last_tick)


def plan_forward(view_tick: Optional[int], live_tick: int, history: Optional[FrameHistory],
                 last_tick: int) -> Tuple[str, int]:
    """One tick forward from what is on screen; from the live game this is a real step."""
    current = live_tick if view_tick is None else view_tick
    return plan_view(current + 1, live_tick, history, last_tick)
