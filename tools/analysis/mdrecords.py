"""Read numbers out of the repository's committed markdown records (standard library only).

The lab's raw run folders (C:/BattleShip_lab/...) are not in the repository; the committed records under docs/ summarise
them in markdown tables and sentences. These helpers find a table by a line of text that precedes it and turn its cells into
numbers, so every figure in RUN2_ANALYSIS.md can be traced to a record, section and row.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"


class RecordError(ValueError):
    pass


def read(doc: str) -> str:
    p = DOCS / doc
    if not p.is_file():
        raise RecordError(f"record not found: {p}")
    return p.read_text(encoding="utf-8")


def table_after(text: str, anchor: str, *, occurrence: int = 1) -> List[Dict[str, str]]:
    """The first markdown table after the line containing `anchor` (its `occurrence`-th match), as dicts keyed by header."""
    lines = text.splitlines()
    hits = [i for i, ln in enumerate(lines) if anchor in ln]
    if len(hits) < occurrence:
        raise RecordError(f"anchor not found: {anchor!r}")
    i = hits[occurrence - 1] + 1
    while i < len(lines) and not lines[i].lstrip().startswith("|"):
        i += 1
    if i >= len(lines):
        raise RecordError(f"no table after {anchor!r}")
    rows: List[List[str]] = []
    while i < len(lines) and lines[i].lstrip().startswith("|"):
        cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells if c):
            rows.append(cells)
        i += 1
    header, body = rows[0], rows[1:]
    return [dict(zip(header, r)) for r in body]


def strip_md(s: str) -> str:
    return re.sub(r"[*`]", "", s).strip()


def num(s: str) -> float:
    """'4,145' -> 4145; '5.51 M' -> 5510000; '**1,051**' -> 1051; '21.5 %' -> 21.5."""
    t = strip_md(s).replace(",", "").replace("%", "").strip()
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*([MKk])?", t)
    if not m:
        raise RecordError(f"not a number: {s!r}")
    v = float(m.group(1))
    return v * {"M": 1e6, "K": 1e3, "k": 1e3}.get(m.group(2) or "", 1.0)


def ints(s: str) -> List[int]:
    """Every integer in a string, thousands separators allowed: 'level 9: 477, 8: 726' -> [9, 477, 8, 726]."""
    return [int(x.replace(",", "")) for x in re.findall(r"\d{1,3}(?:,\d{3})+|\d+", s)]


def sentence(text: str, pattern: str, flags: int = re.S | re.I) -> re.Match:
    """Search running text with its line breaks and indentation collapsed to single spaces (records wrap long sentences)."""
    m = re.search(pattern, re.sub(r"\s+", " ", text), flags)
    if not m:
        raise RecordError(f"pattern not found: {pattern!r}")
    return m


def source(doc: str, section: str, note: str = "") -> Dict[str, Any]:
    d = {"doc": f"docs/{doc}", "section": section}
    if note:
        d["note"] = note
    return d


def first(rows: Sequence[Dict[str, str]], col: str, value: str) -> Optional[Dict[str, str]]:
    for r in rows:
        if strip_md(r.get(col, "")) == value:
            return r
    return None
