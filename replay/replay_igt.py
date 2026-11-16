#!/usr/bin/env python3
"""Frame count -> the time the game's own timer shows (Smash 64, 60 frames per second).

The in-game timer does not round frames / 60. Its hundredths digit comes from a six-entry table, so it is always one
of 0, 1, 3, 5, 7, 9:

    whole seconds = frames // 60
    tenths        = (frames % 60) // 6
    hundredths    = (0, 1, 3, 5, 7, 9)[frames % 6]

Integers only: no float, no rounding. Every displayed time in the replay tools goes through frames_to_igt(); sorting
and filtering use the integer frame counts, never this text.
"""

from __future__ import annotations

FRAMES_PER_SECOND = 60
HUNDREDTHS = (0, 1, 3, 5, 7, 9)


def frames_to_igt(frames: int) -> str:
    """'SS.hh' as the game's timer shows it: 899 -> '14.99', 901 -> '15.01', 446 -> '7.43'. Seconds are not folded
    into minutes (3008 -> '50.13', 7200 -> '120.00')."""
    if isinstance(frames, bool) or not isinstance(frames, int):
        raise TypeError(f"frames must be an int, got {type(frames).__name__}")
    if frames < 0:
        raise ValueError(f"frames must be >= 0, got {frames}")
    return f"{frames // FRAMES_PER_SECOND}.{(frames % FRAMES_PER_SECOND) // 6}{HUNDREDTHS[frames % 6]}"
