#!/usr/bin/env python3
"""Action-state names for `fighter_status_id` (FTStruct::status_id, port/rl/rl.h), read from the decomp headers.

    decomp/src/ft/ftdef.h                     typedef enum FTCommonStatus    ids 0..219, shared by every fighter
    decomp/src/ft/ftchar/<dir>/<dir>.h        typedef enum ft<Char>Status    ids 220.., the character's own states
                                                                             (specials, entries, ...)

<dir> comes from rl/m7n_status_table.CHARACTER_DIRS (mario -> ftmario, donkey_kong -> ftdonkey, jigglypuff ->
ftpurin, ...); the headers are only read, with that module's parse_enum (the parser the M7n/M7q action-class tables
were derived with). Ids from 220 up mean different states for different characters (220 is Mario's Attack13 and
another character's own first state), so they are only named with the episode's character known; with the
character unknown ("?") or its header unreadable, they stay raw numbers. Common ids are always named.

Display names drop the enum prefix. Where several enumerators share a value, the range markers (`...Start` /
`...End` aliases such as nFTCommonStatusControlStart) give way to the state's own name, so 10 is "Wait".

    python replay/replay_status.py [character]    # print the table (common only without a character)
    python replay/replay_status.py --characters   # which characters have a table
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
RL_DIR = REPO_ROOT / "rl"
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

FT_DIR = REPO_ROOT / "decomp" / "src" / "ft"
COMMON_HEADER = FT_DIR / "ftdef.h"

_common: Optional[Dict[str, int]] = None  # enumerator -> value of FTCommonStatus
_names: Dict[Optional[str], Dict[int, str]] = {}  # character (None = common only) -> id -> name
load_errors: Dict[Optional[str], str] = {}


def _display_names(values: Dict[str, int], prefix: str) -> Dict[int, str]:
    by_value: Dict[int, list] = {}
    for name, value in values.items():  # declaration order
        by_value.setdefault(value, []).append(re.sub(prefix, "", name, count=1))
    out = {}
    for value, names in by_value.items():
        own = [n for n in names if not re.search(r"(Start|End)$", n)] if len(names) > 1 else names
        out[value] = (own or names)[0]
    return out


def character_header(character: str) -> Optional[Path]:
    from m7n_status_table import CHARACTER_DIRS  # read-only mapping

    d = CHARACTER_DIRS.get(character)
    return FT_DIR / "ftchar" / d / f"{d}.h" if d else None


def _common_values() -> Dict[str, int]:
    global _common
    if _common is None:
        from m7n_status_table import parse_enum

        _common = parse_enum(COMMON_HEADER.read_text(encoding="utf-8", errors="replace"), "FTCommonStatus")
    return _common


def derive(character: Optional[str] = None) -> Dict[int, str]:
    """Common names, plus the character's own ids (>= nFTCommonStatusSpecialStart) when a character is given."""
    from m7n_status_table import parse_enum

    common = _common_values()
    special_start = common["nFTCommonStatusSpecialStart"]
    names = _display_names({k: v for k, v in common.items() if v < special_start}, r"^nFTCommonStatus")
    if character:
        header = character_header(character)
        if header is None:
            raise KeyError(f"no decomp header known for character {character!r}")
        text = header.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"typedef\s+enum\s+(ft\w+Status)\s*\{", text)
        if not m:
            raise ValueError(f"{header.name}: no ft<Char>Status enum")
        own = parse_enum(text, m.group(1), known=common)
        # (one decomp enumerator, Jigglypuff's ftStatus_purin_JumpAerialF2, uses a different prefix style)
        names.update(_display_names({k: v for k, v in own.items() if v >= special_start},
                                    r"^(?:nFT\w+?Status|ftStatus_[a-z]+_)"))
    return names


def status_names(character: Optional[str] = None) -> Dict[int, str]:
    """id -> name for this character (parsed once). Common names only when the character is unknown or its header
    cannot be read (load_errors says why); empty only when the common header itself is unreadable."""
    if character not in _names:
        try:
            _names[character] = derive(character)
        except (OSError, ValueError, KeyError, ImportError) as exc:
            load_errors[character] = f"{type(exc).__name__}: {exc}"
            _names[character] = status_names(None) if character else {}
    return _names[character]


def status_label(status_id, character: Optional[str] = None) -> str:
    """'Wait (10)', 'SpecialHi (225)' with the character's own names, or just the number when unnamed."""
    if status_id is None:
        return "-"
    try:
        sid = int(status_id)
    except (TypeError, ValueError):
        return str(status_id)
    name = status_names(character).get(sid)
    return f"{name} ({sid})" if name else str(sid)


def coverage() -> Dict[str, int]:
    """Character -> number of own named states (0 = no usable table)."""
    from m7n_status_table import CHARACTER_DIRS

    common = len(status_names(None))
    return {c: len(status_names(c)) - common if c not in load_errors else 0 for c in CHARACTER_DIRS}


if __name__ == "__main__":
    if sys.argv[1:] == ["--characters"]:
        for c, n in coverage().items():
            print(f"{c:15s} {n:3d} own states  {character_header(c).relative_to(REPO_ROOT).as_posix()}"
                  f"{'  ' + load_errors[c] if c in load_errors else ''}")
        sys.exit(0)
    table = status_names(sys.argv[1] if len(sys.argv) > 1 else None)
    if not table:
        print(f"no names: {load_errors}", file=sys.stderr)
        sys.exit(1)
    for sid in sorted(table):
        print(f"{sid:4d}  {table[sid]}")
