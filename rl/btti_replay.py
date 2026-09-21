#!/usr/bin/env python3
"""Strict reader for BattleShip BTT text replays (``*.btti``).

The native reader is syNetReplayStartBTTSession (decomp/src/sys/netreplay.c).
It reads line by line, skips a line that starts with '#', '\\n' or '\\r', and
scans every other line as ``"%x,%d,%d"``: buttons in hex, then stick_x and
stick_y in decimal, with buttons <= 0xFFFF and both sticks in -128..127. That
is the whole format: the ``# ...`` header is plain comment text, there is no
row-count field and there is no other column.

This reader accepts exactly that shape. It is deliberately stricter than
sscanf where sscanf is lenient (embedded whitespace, a '+' sign, a "0x"
prefix, trailing text after the third field) and than Python's int() (digit
underscores, non-ASCII digits), so a malformed file fails here, before
anything is sent to BattleShip, instead of being half accepted.

It says nothing about the M1c button rule (zero or exactly one permitted
button); that rule stays with the server. Standard library only.
"""

from __future__ import annotations

import re
from typing import List, NamedTuple


class ReplayFormatError(ValueError):
    """The replay is not a well-formed .btti file; the message carries path:line."""


class ReplayRow(NamedTuple):
    """One raw player-0 controller frame in native representation."""

    buttons: int  # N64 button word, 0..0xFFFF
    stick_x: int  # native s8, -128..127
    stick_y: int  # native s8, -128..127


# Bounded digit counts keep pathological rows a plain "malformed" error; the
# range checks below still give the specific out-of-range messages.
_ROW = re.compile(r"([0-9A-Fa-f]{1,8}),(-?[0-9]{1,4}),(-?[0-9]{1,4})")


def read_btti_rows(path: str) -> List[ReplayRow]:
    """Parse ``path`` into rows, or raise ReplayFormatError (OSError if unreadable).

    Comment bytes are opaque, as they are natively, so undecodable comment
    text is tolerated; only row lines are validated.
    """
    rows: List[ReplayRow] = []
    with open(path, encoding="utf-8", errors="replace") as fp:
        for lineno, line in enumerate(fp, 1):
            text = line.rstrip("\n")  # universal newlines already folded CRLF into "\n"
            if text == "" or text.startswith("#"):
                continue
            match = _ROW.fullmatch(text)
            if match is None:
                raise ReplayFormatError(
                    f"{path}:{lineno}: expected buttons_hex,stick_x,stick_y, got {text[:40]!r}"
                )
            buttons, stick_x, stick_y = int(match[1], 16), int(match[2]), int(match[3])
            if buttons > 0xFFFF:
                raise ReplayFormatError(f"{path}:{lineno}: buttons 0x{buttons:X} exceed 0xFFFF")
            if not -128 <= stick_x <= 127:
                raise ReplayFormatError(f"{path}:{lineno}: stick_x {stick_x} outside -128..127")
            if not -128 <= stick_y <= 127:
                raise ReplayFormatError(f"{path}:{lineno}: stick_y {stick_y} outside -128..127")
            rows.append(ReplayRow(buttons, stick_x, stick_y))
    if not rows:
        raise ReplayFormatError(f"{path}: no input rows")
    return rows
