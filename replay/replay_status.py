#!/usr/bin/env python3
"""Action-state names for `fighter_status_id` (FTStruct::status_id, port/rl/rl.h), read from the decomp headers.

    decomp/src/ft/ftdef.h                    typedef enum FTCommonStatus   ids 0..219, every fighter
    decomp/src/ft/ftchar/ftmario/ftmario.h   typedef enum ftMarioStatus    ids 220.. (Mario's own states)

The headers are only read (with rl/m7n_status_table.parse_enum, the parser the M7n/M7q action-class tables were
derived with). Display names drop the enum prefix. Where several enumerators share a value, the range markers
(`...Start` / `...End` aliases such as nFTCommonStatusControlStart) give way to the state's own name, so 10 is
"Wait", not "ControlStart". Any id without a name (another character's range, or headers missing) shows as the raw
number only.

    python replay/replay_status.py          # print the table
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
MARIO_HEADER = FT_DIR / "ftchar" / "ftmario" / "ftmario.h"

_names: Optional[Dict[int, str]] = None
load_error: Optional[str] = None


def _display_names(values: Dict[str, int], prefix: str) -> Dict[int, str]:
    by_value: Dict[int, list] = {}
    for name, value in values.items():  # declaration order
        by_value.setdefault(value, []).append(re.sub(prefix, "", name, count=1))
    out = {}
    for value, names in by_value.items():
        own = [n for n in names if not re.search(r"(Start|End)$", n)] if len(names) > 1 else names
        out[value] = (own or names)[0]
    return out


def derive() -> Dict[int, str]:
    from m7n_status_table import parse_enum  # read-only helper; no table file is read or written

    common = parse_enum(COMMON_HEADER.read_text(encoding="utf-8", errors="replace"), "FTCommonStatus")
    special_start = common["nFTCommonStatusSpecialStart"]
    names = _display_names({k: v for k, v in common.items() if v < special_start}, r"^nFTCommonStatus")
    mario = parse_enum(MARIO_HEADER.read_text(encoding="utf-8", errors="replace"), "ftMarioStatus", known=common)
    names.update(_display_names({k: v for k, v in mario.items() if v >= special_start}, r"^nFTMarioStatus"))
    return names


def status_names() -> Dict[int, str]:
    """id -> name, parsed once; empty when the headers cannot be read (load_error says why)."""
    global _names, load_error
    if _names is None:
        try:
            _names = derive()
        except (OSError, ValueError, KeyError, ImportError) as exc:
            _names, load_error = {}, f"{type(exc).__name__}: {exc}"
    return _names


def status_label(status_id) -> str:
    """'Wait (10)', or just the number when the id has no name."""
    if status_id is None:
        return "-"
    try:
        sid = int(status_id)
    except (TypeError, ValueError):
        return str(status_id)
    name = status_names().get(sid)
    return f"{name} ({sid})" if name else str(sid)


if __name__ == "__main__":
    table = status_names()
    if not table:
        print(f"no names: {load_error}", file=sys.stderr)
        sys.exit(1)
    for sid in sorted(table):
        print(f"{sid:4d}  {table[sid]}")
