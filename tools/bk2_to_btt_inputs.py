#!/usr/bin/env python3
"""Convert a BizHawk N64 BK2 input log to BattleShip's BTT text format."""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
import zipfile


BUTTON_BITS = {
    4: 0x0800,   # D-pad up
    5: 0x0400,   # D-pad down
    6: 0x0200,   # D-pad left
    7: 0x0100,   # D-pad right
    8: 0x1000,   # Start
    9: 0x2000,   # Z
    10: 0x4000,  # B
    11: 0x8000,  # A
    12: 0x0008,  # C-up
    13: 0x0004,  # C-down
    14: 0x0002,  # C-left
    15: 0x0001,  # C-right
    16: 0x0020,  # L
    17: 0x0010,  # R
}

SSB64_STICK_LIMIT = 80

ROW_RE = re.compile(
    r"^\|(?P<console>[^|]*)\|\s*(?P<x>[+-]?\d+)\s*,\s*"
    r"(?P<y>[+-]?\d+)\s*,(?P<flags>[^|]*)\|$"
)


def active(flag: str) -> bool:
    return flag != "."


def resolve_axis(numeric: int, negative: bool, positive: bool) -> int:
    """Resolve BizHawk's virtual analog direction buttons.

    BizHawk evaluates the negative direction first when both virtual
    directions are asserted. This matters for TAS input: mario_raw.bk2 holds
    Left+Right on frame 61, and the emulated game receives Left for that row.

    Smash 64 clamps the usable N64 stick range to +/-80. Clamp numeric input
    too because BattleShip injects these values after the normal controller
    processing stage where that clamp would ordinarily occur.
    """
    if negative:
        value = -128
    elif positive:
        value = 127
    else:
        value = numeric

    return max(-SSB64_STICK_LIMIT, min(SSB64_STICK_LIMIT, value))


def parse_row(line: str, movie_frame: int) -> tuple[int, int, int]:
    match = ROW_RE.match(line.rstrip("\r\n"))
    if not match:
        raise ValueError(f"frame {movie_frame}: unsupported input row: {line.rstrip()!r}")

    console = match.group("console")
    if any(ch != "." for ch in console):
        raise ValueError(f"frame {movie_frame}: Reset/Power is asserted inside the selected range")

    flags = match.group("flags")
    if len(flags) != 18:
        raise ValueError(f"frame {movie_frame}: expected 18 P1 flags, got {len(flags)}")

    x = int(match.group("x"))
    y = int(match.group("y"))
    if not (-128 <= x <= 127 and -128 <= y <= 127):
        raise ValueError(f"frame {movie_frame}: analog value outside signed-byte range")

    # P1 A Up, Down, Left, Right occupy flag positions 0..3.
    x = resolve_axis(x, active(flags[2]), active(flags[3]))
    y = resolve_axis(y, active(flags[1]), active(flags[0]))

    buttons = 0
    for index, bit in BUTTON_BITS.items():
        if active(flags[index]):
            buttons |= bit
    return buttons, x, y


def read_bk2_rows(path: pathlib.Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        try:
            text = archive.read("Input Log.txt").decode("utf-8-sig")
        except KeyError as exc:
            raise ValueError("BK2 has no 'Input Log.txt'") from exc

    rows: list[str] = []
    in_input = False
    for line in text.splitlines():
        if line == "[Input]":
            in_input = True
        elif line == "[/Input]":
            in_input = False
        elif in_input and line.startswith("|"):
            rows.append(line)
    if not rows:
        raise ValueError("BK2 input log contains no frame rows")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_bk2", type=pathlib.Path)
    parser.add_argument("output_btti", type=pathlib.Path)
    parser.add_argument("--start", type=int, default=0, help="first BK2 movie frame (default: 0)")
    parser.add_argument("--frames", type=int, help="number of rows to export (default: all remaining)")
    args = parser.parse_args()

    try:
        rows = read_bk2_rows(args.input_bk2)
        if args.start < 0 or args.start > len(rows):
            raise ValueError(f"--start must be between 0 and {len(rows)}")
        stop = len(rows) if args.frames is None else args.start + args.frames
        if args.frames is not None and args.frames <= 0:
            raise ValueError("--frames must be positive")
        if stop > len(rows):
            raise ValueError(f"requested range ends at {stop}, but movie has {len(rows)} rows")

        converted = [parse_row(rows[i], i) for i in range(args.start, stop)]
        args.output_btti.parent.mkdir(parents=True, exist_ok=True)
        with args.output_btti.open("w", encoding="ascii", newline="\n") as output:
            output.write("# BattleShip BTT input v1\n")
            output.write(f"# source={args.input_bk2.name} start={args.start} frames={len(converted)}\n")
            output.write("# buttons_hex,stick_x,stick_y\n")
            for buttons, stick_x, stick_y in converted:
                output.write(f"{buttons:04X},{stick_x},{stick_y}\n")
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    non_neutral = sum(item != (0, 0, 0) for item in converted)
    print(
        f"wrote {len(converted)} frames ({non_neutral} non-neutral) "
        f"from BK2 [{args.start}, {stop}) to {args.output_btti}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
