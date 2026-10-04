#!/usr/bin/env python3
"""Replay browser: every indexed episode in one table (`replay_index.py gui`, or replay_gui.pyw without a console).

Character-agnostic: the character (and stage, when the data distinguishes stages) comes from what each run
recorded, "?" when it recorded nothing (replay_task.py); stage-specific milestones are tags from the stage's own
extractor (replay_tags.py). Filters apply as they change; the text search also matches tags; test / smoke /
equivalence episodes are hidden unless "Show tests" is on; "Best per run" keeps one row per run. Click a heading
to sort (default: most targets, then the earliest last-target break), drag a heading edge to resize. Double-click or Enter plays the
episode in the viewer (through replay_open.pyw, so start-up errors appear as a message box); the details card
has Play, Check (headless MATCH/DESYNC), Copy path and Open folder; "Check filtered" replays every listed episode
headless in the background (replay_game.CheckBatch). Reads the index only; Rescan runs the same incremental
read-only scan as `replay_index.py scan`.

The table is drawn on a Canvas, visible rows only: that is what lets one cell carry its own colors (end pills,
verdict marks; ttk.Treeview colors whole rows only) and keeps ~40k rows responsive. Standard library
only.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from collections import defaultdict
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Callable, Dict, List, Optional, Tuple

from replay_index import (DESCENDING_BY_DEFAULT, REPO_ROOT, SORT_KEYS, VIEWER, created_local, last_scan,
                          last_scan_report, matches_text, set_last_target)
from replay_task import UNKNOWN
from replay_widgets import (DARK_GREEN, DARK_RED, GREY_TEXT, HEAD_FONT, INK, UI_FONT, Tooltip, end_ellipsis,
                            middle_ellipsis, popup_tip)

OPENER = Path(__file__).resolve().with_name("replay_open.pyw")

ROW_H, HEAD_H, PADX = 28, 30, 10
FONT = ("Segoe UI", 9)
FONT_BOLD = ("Segoe UI", 9, "bold")
PILL_FONT = ("Segoe UI", 8, "bold")
BG, ZEBRA = "#ffffff", "#f6f7f9"
CLEAR_BG, CLEAR_ZEBRA = "#eefaf1", "#e5f5e9"  # subtle highlight for clears
SELECT_BG, SELECT_LINE = "#dbeafe", "#60a5fa"
HEAD_BG, GRID = "#eef0f3", "#d9dde3"
# End pills (background, text): clear green, fall muted red, timeout grey.
PILLS = {"clear": ("#16a34a", "#ffffff"), "fall": ("#f1d5d5", "#9b2c2c"), "timeout": ("#e3e6ea", "#4b5563"),
         "goal": ("#dbeafe", "#1e40af"), "aborted": ("#fdecc8", "#92400e"), "unknown": ("#f3f4f6", "#9ca3af"),
         "prefix": ("#e0e7ff", "#3730a3")}  # an M8 route that stops at an archive cell (the game did not end)
VERDICT_MARKS = {"MATCH": ("✔", DARK_GREEN), "DESYNC": ("✖", DARK_RED)}
NO_VERDICT = ("·", "#9ca3af")

# (key, title, width px, anchor, sort key, stretch weight)
COLUMNS: Tuple[Tuple[str, str, int, str, str, int], ...] = (
    ("targets", "Targets", 72, "e", "targets", 0),
    ("character", "Character", 96, "w", "character", 0),
    ("end", "End", 80, "center", "end", 0),
    ("last", "Last target", 118, "e", "last", 0),
    ("verdict", "Verdict", 62, "center", "verdict", 0),
    ("role", "Role", 84, "w", "role", 0),
    ("milestone", "Milestone", 88, "w", "milestone", 0),
    ("run", "Run", 260, "w", "run", 1),
    ("tags", "Tags", 150, "w", "tags", 0),  # tags are rare (4 episodes today): narrow, tooltip when cut
    ("created", "Created", 100, "w", "created", 0),
)

EPISODES_COLUMN = ("runeps", "Episodes", 84, "e", "episodes", 0)  # shown in "Best per run" only
CONFIRM_ABOVE = 50  # "Check filtered" asks first above this many episodes
CHECK_SECONDS = 4.5  # rough duration of one headless replay (launch + up to 3,600 ticks), for the estimate


def main(load_rows: Callable[[], List[Dict[str, Any]]], scan: Callable[..., Dict[str, Any]]) -> int:
    app = Browser(load_rows, scan)
    app.root.mainloop()
    return 0


def _sort_key(key: str):
    return (lambda r: r.get("run_count", 0)) if key == "episodes" else SORT_KEYS[key]


def sort_view(rows: List[Dict[str, Any]], key: str, desc: bool) -> List[Dict[str, Any]]:
    """Sort by `key`; ties keep the default order (most targets, then the earliest last-target break)."""
    rows = sorted(rows, key=SORT_KEYS["last"])
    rows.sort(key=SORT_KEYS["targets"], reverse=True)
    rows.sort(key=_sort_key(key), reverse=desc)
    return rows


def best_per_run(rows: List[Dict[str, Any]], all_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One row per run (milestone + run path, workers merged): the best episode by targets, then last-target tick.
    Each carries run_count (its run's episodes among `rows`) and run_count_text ("12", or "12 of 40" when filters
    hide some of the run's episodes)."""
    total: Dict[Tuple[str, str], int] = defaultdict(int)
    for r in all_rows:
        total[(r["milestone"], r["run"])] += 1
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[(r["milestone"], r["run"])].append(r)
    out = []
    for key, members in groups.items():
        best = sort_view(members, "targets", True)[0]
        n, t = len(members), total[key]
        best["run_count"], best["run_count_text"] = n, (f"{n:,}" if n == t else f"{n:,} of {t:,}")
        out.append(best)
    return out


def card_fields(r: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Key / value lines of the details card; empty and None values are left out."""
    created = created_local(r["created"])
    verdict = f"{r['replay']} ({r['replay_mode']})" if r.get("replay") and r.get("replay_mode") else r.get("replay")
    end = r["end_label"] + (f" ({r['end_detail']})" if r.get("end_detail") not in (None, "", "not recorded") else "")
    pairs: List[Tuple[str, Any]] = [
        ("character", r["character_name"] if r["character"] else f"{UNKNOWN} (not recorded)"),
        ("stage", r.get("stage")),
        ("recorded in", r.get("task_source") if r["character"] else None),
        ("role", r.get("role")), ("run", r.get("run")), ("run id", r.get("run_id")), ("worker", r.get("worker")),
        ("profile", r.get("profile")), ("observation", r.get("observation")), ("reward", r.get("reward")),
        ("end", end),
        ("targets", f"{r['targets']}/{r['targets_total']}" if r.get("targets") is not None else None),
        ("last target", f"{r['last_target_text']} ({r['last_target_source']})"),
        ("end tick", r["time_text"] if r["time_text"] != "–" else None),
        ("steps", r.get("steps")), ("prefix rows", r.get("prefix_rows")),
        ("created", (f"{created:%Y-%m-%d %H:%M:%S} (local"
                     + (", metadata.json file time: no recorded creation time)" if r.get("created_source") == "file time"
                        else ")")) if created else None),
        ("artifact", r.get("format") if r.get("format") not in (None, "battleship_btt_episode") else None),
        ("verdict", verdict),
        ("test episode", "yes (hidden unless Show tests)" if r.get("is_test") else None),
        *r.get("tag_details", []),
        ("sidecars", (r.get("sidecars") or "").replace(",", ", ")),
    ]
    return [(k, str(v)) for k, v in pairs if v not in (None, "", "None")]


class Table(tk.Frame):
    """A read-only table drawn on a Canvas: visible rows only, per-cell colors, sortable and resizable headings."""

    def __init__(self, parent, *, on_select: Callable[[Optional[Dict[str, Any]]], None],
                 on_activate: Callable[[], None], on_sort: Callable[[str], None]):
        super().__init__(parent, bg=GRID, highlightthickness=0)
        self.on_select, self.on_activate, self.on_sort = on_select, on_activate, on_sort
        self.font = tkfont.Font(font=FONT)
        self.font_bold = tkfont.Font(font=FONT_BOLD)
        self.pill_font = tkfont.Font(font=PILL_FONT)
        self.columns = list(COLUMNS)
        self.merge_workers = False  # "Best per run": the Run cell is the run itself, workers merged
        self.widths = {c[0]: c[2] for c in (*COLUMNS, EPISODES_COLUMN)}
        self.rows: List[Dict[str, Any]] = []
        self.top = 0
        self.sel: Optional[int] = None
        self.sort_key, self.sort_desc = "targets", True
        self._x: List[Tuple[str, int, int]] = []  # (key, x0, x1) of each column, as drawn
        self._fit: Dict[Tuple[str, int, str], str] = {}  # (text, px, mode) -> shortened text
        self._tips: Dict[Tuple[int, str], str] = {}  # (row index, column) -> tooltip text of the visible cells
        self._tip: Optional[tk.Toplevel] = None
        self._tip_after: Optional[str] = None
        self._tip_cell: Optional[Tuple[int, str]] = None
        self._drag: Optional[Tuple[str, int, int]] = None  # (column, start x, start width) while resizing
        self.head = tk.Canvas(self, height=HEAD_H, bg=HEAD_BG, highlightthickness=0, bd=0)
        self.body = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0, takefocus=1)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self._yview)
        self.head.grid(row=0, column=0, sticky="ew")
        self.body.grid(row=1, column=0, sticky="nsew")
        self.vbar.grid(row=0, column=1, rowspan=2, sticky="ns")
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        b = self.body
        b.bind("<Configure>", lambda e: self.redraw())
        b.bind("<Button-1>", self._click)
        b.bind("<Double-1>", lambda e: (self._click(e), self.on_activate()))
        b.bind("<MouseWheel>", lambda e: self.scroll(-3 if e.delta > 0 else 3))
        self.head.bind("<MouseWheel>", lambda e: self.scroll(-3 if e.delta > 0 else 3))
        b.bind("<Motion>", self._motion)
        b.bind("<Leave>", lambda e: self._hide_tip())
        for key, delta in (("<Up>", -1), ("<Down>", 1), ("<Prior>", "page-"), ("<Next>", "page+"),
                           ("<Home>", "home"), ("<End>", "end")):
            b.bind(key, lambda e, d=delta: self._key(d))
        b.bind("<Return>", lambda e: self.on_activate())
        h = self.head
        h.bind("<Motion>", self._head_motion)
        h.bind("<Button-1>", self._head_press)
        h.bind("<B1-Motion>", self._head_drag)
        h.bind("<ButtonRelease-1>", self._head_release)

    # -- data / geometry -------------------------------------------------------------------------------------

    def set_rows(self, rows: List[Dict[str, Any]], keep: Optional[str] = None) -> None:
        """New content; the row whose path is `keep` stays selected (and visible) when still present."""
        self.rows = rows
        self.sel = next((i for i, r in enumerate(rows) if r["path"] == keep), None) if keep else None
        self.top = max(0, min(self.top, len(rows) - self.visible()))
        if self.sel is not None:
            self._show_row(self.sel)
        self.redraw()

    def visible(self) -> int:
        return max(1, self.body.winfo_height() // ROW_H)

    def _layout(self) -> None:
        """Column x ranges: fixed widths, extra width shared by the stretch columns."""
        total = max(self.body.winfo_width(), 1)
        weights = sum(c[5] for c in self.columns) or 1
        fixed = sum(self.widths[c[0]] for c in self.columns)
        extra = max(0, total - fixed)
        x, out = 0, []
        for key, _, _, _, _, stretch in self.columns:
            w = self.widths[key] + extra * stretch // weights
            out.append((key, x, x + w))
            x += w
        self._x = out

    def _yview(self, *args) -> None:
        n = len(self.rows)
        if args[0] == "moveto":
            self.top = int(float(args[1]) * n)
        elif args[0] == "scroll":
            step = int(args[1]) * (self.visible() if args[2] == "pages" else 1)
            self.top += step
        self.top = max(0, min(self.top, max(0, n - self.visible())))
        self.redraw()

    def scroll(self, rows: int) -> None:
        self._yview("scroll", rows, "units")

    def _show_row(self, i: int) -> None:
        if i < self.top:
            self.top = i
        elif i >= self.top + self.visible():
            self.top = i - self.visible() + 1

    # -- drawing -------------------------------------------------------------------------------------------------

    def _short(self, text: str, px: int, mode: str = "end", font: Optional[tkfont.Font] = None) -> str:
        key = (text, px, mode + ("b" if font is self.font_bold else ""))
        if key not in self._fit:
            measure = (font or self.font).measure
            self._fit[key] = (middle_ellipsis(text, px, measure, sep="/") if mode == "middle"
                              else end_ellipsis(text, px, measure))
            if len(self._fit) > 20000:
                self._fit.clear()
        return self._fit[key]

    def redraw(self) -> None:
        self._layout()
        self._draw_head()
        c = self.body
        c.delete("all")
        self._tips = {}
        n = len(self.rows)
        width = self._x[-1][2] if self._x else c.winfo_width()
        end = min(n, self.top + self.visible() + 1)
        for i in range(self.top, end):
            r = self.rows[i]
            y0 = (i - self.top) * ROW_H
            clear = r["end_label"] == "clear"
            bg = SELECT_BG if i == self.sel else (CLEAR_ZEBRA if clear else ZEBRA) if i % 2 else (
                CLEAR_BG if clear else BG)
            c.create_rectangle(0, y0, max(width, c.winfo_width()), y0 + ROW_H, fill=bg, outline="")
            if i == self.sel:
                c.create_rectangle(0, y0, 3, y0 + ROW_H, fill=SELECT_LINE, outline="")
            for key, x0, x1 in self._x:
                self._cell(c, key, r, i, x0, x1, y0)
        if n == 0:
            c.create_text(c.winfo_width() // 2, 40, text="No episodes match these filters.", fill=GREY_TEXT,
                          font=FONT)
        self.vbar.set(self.top / n if n else 0, min(1.0, (self.top + self.visible()) / n) if n else 1)

    def _text(self, c, x0, x1, y0, text, anchor="w", color=INK, font=None, mode="end", tip_key=None) -> None:
        room = x1 - x0 - 2 * PADX
        shown = self._short(text, room, mode, font)
        if tip_key is not None and shown != text:
            self._tips[tip_key] = text
        x = {"w": x0 + PADX, "e": x1 - PADX, "center": (x0 + x1) // 2}[anchor]
        c.create_text(x, y0 + ROW_H // 2, text=shown, anchor={"w": "w", "e": "e", "center": "center"}[anchor],
                      fill=color, font=font or self.font)

    def _cell(self, c: tk.Canvas, key: str, r: Dict[str, Any], i: int, x0: int, x1: int, y0: int) -> None:
        mid = y0 + ROW_H // 2
        if key == "targets":
            t, total = r["targets"], r["targets_total"] or 10
            self._text(c, x0, x1, y0, f"{t if t is not None else '-'}/{total}", anchor="e",
                       font=self.font_bold if t == total else None)
        elif key == "character":
            self._text(c, x0, x1, y0, r["character_name"], color=GREY_TEXT if not r["character"] else INK)
        elif key == "end":
            label = r["end_label"] if r["end_label"] != "unknown" else "?"
            bg, fg = PILLS.get(r["end_label"], PILLS["unknown"])
            w, h = min(x1 - x0 - 8, self.pill_font.measure(label) + 16), 18
            cx = (x0 + x1) // 2
            px0, px1, py0, py1 = cx - w // 2, cx + w // 2, mid - h // 2, mid + h // 2
            c.create_oval(px0, py0, px0 + h, py1, fill=bg, outline=bg)
            c.create_oval(px1 - h, py0, px1, py1, fill=bg, outline=bg)
            c.create_rectangle(px0 + h // 2, py0, px1 - h // 2, py1, fill=bg, outline=bg)
            c.create_text(cx, mid, text=label, fill=fg, font=self.pill_font)
        elif key == "last":
            clear = r["end_label"] == "clear"
            known = r["last_target_tick"] is not None
            self._text(c, x0, x1, y0, r["last_target_text"], anchor="e", font=self.font_bold if clear else None,
                       color=DARK_GREEN if clear else INK if known else GREY_TEXT)
        elif key == "runeps":
            self._text(c, x0, x1, y0, r.get("run_count_text", ""), anchor="e")
        elif key == "verdict":
            mark, color = VERDICT_MARKS.get(r["replay"], NO_VERDICT)
            c.create_text((x0 + x1) // 2, mid, text=mark, fill=color, font=("Segoe UI Symbol", 11, "bold"))
        elif key == "role":
            self._text(c, x0, x1, y0, r["role"] or "", color=GREY_TEXT)
        elif key == "milestone":
            self._text(c, x0, x1, y0, r["milestone"])
        elif key == "run":
            run = r["run"] + (f"/{r['worker']}" if r["worker"] and not self.merge_workers else "")
            self._text(c, x0, x1, y0, run or "-", mode="middle")
            self._tips[(i, key)] = r["path"].replace("/", os.sep)  # the full episode path
        elif key == "tags":
            self._text(c, x0, x1, y0, r["tag_text"], color="#1d4ed8", tip_key=(i, key))
        elif key == "created":
            self._text(c, x0, x1, y0, r["created_text"], color=GREY_TEXT)

    def _draw_head(self) -> None:
        h = self.head
        h.delete("all")
        width = max(h.winfo_width(), self._x[-1][2] if self._x else 0)
        h.create_rectangle(0, 0, width, HEAD_H, fill=HEAD_BG, outline="")
        h.create_line(0, HEAD_H - 1, width, HEAD_H - 1, fill=GRID)
        for key, title, _, anchor, sort_key, _ in self.columns:
            x0, x1 = next((a, b) for k, a, b in self._x if k == key)
            arrow = (" ▼" if self.sort_desc else " ▲") if sort_key == self.sort_key else ""
            x = {"w": x0 + PADX, "e": x1 - PADX, "center": (x0 + x1) // 2}[anchor]
            h.create_text(x, HEAD_H // 2, text=title + arrow, anchor={"w": "w", "e": "e", "center": "center"}[anchor],
                          fill=INK, font=self.font_bold)
            h.create_line(x1 - 1, 7, x1 - 1, HEAD_H - 7, fill=GRID)

    # -- interaction ---------------------------------------------------------------------------------------------

    def row_at(self, y: int) -> Optional[int]:
        i = self.top + y // ROW_H
        return i if 0 <= i < len(self.rows) else None

    def column_at(self, x: int) -> Optional[str]:
        return next((k for k, a, b in self._x if a <= x < b), None)

    def select(self, i: Optional[int]) -> None:
        self.sel = i
        if i is not None:
            self._show_row(i)
        self.redraw()
        self.on_select(self.rows[i] if i is not None else None)

    def selected(self) -> Optional[Dict[str, Any]]:
        return self.rows[self.sel] if self.sel is not None and self.sel < len(self.rows) else None

    def _click(self, e) -> None:
        self.body.focus_set()
        i = self.row_at(e.y)
        if i is not None:
            self.select(i)

    def _key(self, d) -> str:
        n = len(self.rows)
        if not n:
            return "break"
        cur = self.sel if self.sel is not None else -1
        target = {"page-": cur - self.visible(), "page+": cur + self.visible(), "home": 0, "end": n - 1}.get(
            d, cur + d if isinstance(d, int) else cur)
        self.select(max(0, min(n - 1, target)))
        return "break"

    def _motion(self, e) -> None:
        i, col = self.row_at(e.y), self.column_at(e.x)
        cell = (i, col) if i is not None and col is not None and (i, col) in self._tips else None
        if cell == self._tip_cell:
            return
        self._hide_tip()
        self._tip_cell = cell
        if cell is not None:
            text = self._tips[cell]
            self._tip_after = self.after(350, lambda: self._show_tip(text, e.x_root + 14, e.y_root + 16))

    def _show_tip(self, text: str, x: int, y: int) -> None:
        self._tip_after = None
        self._tip = popup_tip(self.body, text, x, y)

    def _hide_tip(self) -> None:
        if self._tip_after is not None:
            self.after_cancel(self._tip_after)
            self._tip_after = None
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None
        self._tip_cell = None

    def _edge(self, x: int) -> Optional[str]:
        """The column whose right edge is under x (resize handle), if any."""
        return next((k for k, a, b in self._x if abs(x - b) <= 4), None)

    def _head_motion(self, e) -> None:
        self.head.configure(cursor="sb_h_double_arrow" if self._edge(e.x) else "hand2")

    def _head_press(self, e) -> None:
        edge = self._edge(e.x)
        if edge:
            self._drag = (edge, e.x, self.widths[edge])
            return
        col = self.column_at(e.x)
        if col is not None:
            self.on_sort(next(c[4] for c in self.columns if c[0] == col))

    def _head_drag(self, e) -> None:
        if self._drag:
            key, x0, w0 = self._drag
            self.widths[key] = max(40, w0 + e.x - x0)
            self.redraw()

    def _head_release(self, _e) -> None:
        self._drag = None


class Browser:
    def __init__(self, load_rows, scan):
        self.load_rows_fn, self.scan_fn = load_rows, scan
        self.rows: List[Dict[str, Any]] = []
        self.view: List[Dict[str, Any]] = []
        self.sort_key, self.sort_desc = "targets", True
        self.children: List[subprocess.Popen] = []
        self._scanning = False
        self._search_after: Optional[str] = None
        self.batch = None  # the running "Check filtered" (replay_game.CheckBatch), if any
        # Worker threads (scan, checks) never touch Tk: they post callbacks here, the Tk thread runs them (_drain).
        self._events: "queue.Queue[Callable[[], None]]" = queue.Queue()
        self._draining = False
        self._checking_one = False  # a single-episode Check is running
        self.batch_factory = None  # tests replace it; default: replay_game.CheckBatch
        self.root = tk.Tk()
        self.root.title("Replay browser - runs/")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.geometry("1440x860")
        self.root.minsize(1000, 560)
        self._build()
        self.reload()

    # -- layout ---------------------------------------------------------------------------------------------------

    def _build(self) -> None:
        root = self.root
        style = ttk.Style(root)
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("Card.TLabel", background="#ffffff")

        bar = ttk.Frame(root)
        bar.pack(fill="x", padx=12, pady=(10, 6))
        self.vars: Dict[str, tk.StringVar] = {}
        self.combos: Dict[str, ttk.Combobox] = {}
        self.stage_box = ttk.Frame(bar)

        def combo(parent, label, name, values, width=10):
            box = ttk.Frame(parent)
            ttk.Label(box, text=label, font=UI_FONT, foreground=GREY_TEXT).pack(anchor="w")
            v = tk.StringVar(value=values[0])
            cb = ttk.Combobox(box, textvariable=v, values=values, width=width, state="readonly")
            cb.pack()
            cb.bind("<<ComboboxSelected>>", lambda e: self.apply())
            self.vars[name], self.combos[name] = v, cb
            return box

        combo(bar, "Milestone", "milestone", ["any"], 13).pack(side="left", padx=(0, 8))
        combo(bar, "Character", "character", ["any"], 13).pack(side="left", padx=(0, 8))
        self.stage_box = combo(bar, "Stage", "stage", ["any"], 13)  # packed only when stages vary per character
        self._stage_anchor = combo(bar, "Role", "role", ["any", "training", "evaluation"], 10)
        self._stage_anchor.pack(side="left", padx=(0, 8))
        combo(bar, "End", "end", ["any", "clear", "fall", "timeout", "goal", "aborted", "prefix", "unknown"], 9).pack(
            side="left", padx=(0, 8))
        combo(bar, "Min targets", "min_targets", ["any"] + [str(i) for i in range(1, 11)], 6).pack(
            side="left", padx=(0, 8))
        combo(bar, "Verdict", "verdict", ["any", "MATCH", "DESYNC", "none"], 8).pack(side="left", padx=(0, 8))
        toggles = ttk.Frame(bar)
        toggles.pack(side="left", padx=(0, 8))
        self.show_tests = tk.BooleanVar(value=False)
        self.best_run = tk.BooleanVar(value=False)
        tests = ttk.Checkbutton(toggles, text="Show tests", variable=self.show_tests, command=self.apply)
        tests.pack(anchor="w")
        Tooltip(tests, "Test / smoke / equivalence episodes: roles test and m6_equivalence, no role recorded,\n"
                       "and every _-prefixed milestone folder (smoke, regression, preflight, debug runs)")
        best = ttk.Checkbutton(toggles, text="Best per run", variable=self.best_run, command=self.apply)
        best.pack(anchor="w")
        Tooltip(best, "One row per run: its best episode by targets, then last-target tick")
        search = ttk.Frame(bar)
        search.pack(side="left", padx=(4, 8))
        ttk.Label(search, text="Search (path, run, profile, tags)", font=UI_FONT, foreground=GREY_TEXT).pack(anchor="w")
        self.vars["text"] = tk.StringVar()
        entry = ttk.Entry(search, textvariable=self.vars["text"], width=30)
        entry.pack()
        self.vars["text"].trace_add("write", lambda *a: self._search_changed())
        entry.bind("<Escape>", lambda e: self.vars["text"].set(""))
        reset = ttk.Frame(bar)
        reset.pack(side="left")
        ttk.Label(reset, text=" ", font=UI_FONT).pack()
        ttk.Button(reset, text="Reset", width=6, command=self.reset_filters).pack()
        self.count = tk.StringVar()
        right = ttk.Frame(bar)
        right.pack(side="right", anchor="s")
        tk.Label(right, textvariable=self.count, font=("Segoe UI", 10, "bold"), fg=INK).pack(anchor="e")
        self.check_btn = ttk.Button(right, text="Check filtered…", command=self.check_filtered)
        self.check_btn.pack(anchor="e", pady=(2, 0))
        Tooltip(self.check_btn, "Headless MATCH/DESYNC replay of every listed episode, in the background\n"
                                "(one BattleShip process at a time; results go to the verdict column)")

        self.table = Table(root, on_select=self.show_card, on_activate=self.play, on_sort=self.sort_by)
        self.table.pack(fill="both", expand=True, padx=12)

        # Details card (key / value, like the viewer's header) with the actions.
        card = tk.Frame(root, bg="#ffffff", highlightthickness=1, highlightbackground=GRID)
        card.pack(fill="x", padx=12, pady=(8, 6))
        top = tk.Frame(card, bg="#ffffff")
        top.pack(fill="x", padx=12, pady=(8, 2))
        self.card_title = tk.Label(top, text="Select an episode", font=HEAD_FONT, fg=INK, bg="#ffffff", anchor="w")
        self.card_title.pack(side="left")
        self.buttons: List[ttk.Button] = []
        for text, cmd in (("Open folder", self.open_folder), ("Copy path", self.copy_path),
                          ("Check (headless)", self.check), ("▶ Play", self.play)):
            btn = ttk.Button(top, text=text, command=cmd, state="disabled")
            btn.pack(side="right", padx=(6, 0))
            self.buttons.append(btn)
        self.card_path = tk.Label(card, text="", font=UI_FONT, fg=GREY_TEXT, bg="#ffffff", anchor="w", width=1)
        self.card_path.pack(fill="x", padx=12)
        self.card_path.bind("<Configure>", lambda e: self._fit_card_path())
        self.card_path_tip = Tooltip(self.card_path, "")
        self._card_path_text = ""
        self.card_grid = tk.Frame(card, bg="#ffffff")
        self.card_grid.pack(fill="x", padx=12, pady=(4, 10))
        self._path_font = tkfont.Font(font=UI_FONT)

        status = ttk.Frame(root)
        status.pack(fill="x", padx=12, pady=(0, 8))
        self.status = tk.StringVar()
        ttk.Label(status, textvariable=self.status, font=UI_FONT, foreground=INK).pack(side="left")
        ttk.Button(status, text="Rescan", width=8, command=self.rescan).pack(side="right")
        self.index_info = tk.StringVar()
        ttk.Label(status, textvariable=self.index_info, font=UI_FONT, foreground=GREY_TEXT).pack(side="right", padx=8)

    # -- data -----------------------------------------------------------------------------------------------------

    def reload(self) -> None:
        keep = self.table.selected()
        self.rows = self.load_rows_fn()
        chars = sorted({r["character"] or UNKNOWN for r in self.rows}, key=lambda c: (c == UNKNOWN, c))
        self.combos["milestone"].configure(values=["any"] + sorted({r["milestone"] for r in self.rows}))
        self.combos["character"].configure(values=["any"] + chars)
        stages_by_char: Dict[str, set] = {}
        for r in self.rows:
            stages_by_char.setdefault(r["character"] or UNKNOWN, set()).add(r["stage"] or UNKNOWN)
        # The stage filter only when the data distinguishes stages (some character with several stages).
        if any(len(s) > 1 for c, s in stages_by_char.items() if c != UNKNOWN):
            self.combos["stage"].configure(values=["any"] + sorted({s for v in stages_by_char.values() for s in v}))
            self.stage_box.pack(side="left", padx=(0, 8), before=self._stage_anchor)
        else:
            self.vars["stage"].set("any")
            self.stage_box.pack_forget()
        stamp = last_scan()
        when = created_local(stamp) if stamp else None
        self.index_info.set(f"index: {len(self.rows):,} episodes"
                            + (f", scanned {when:%b} {when.day} {when:%H:%M}" if when else ", not scanned yet"))
        report = last_scan_report().get("not_indexed")
        if report and not self.status.get():
            self.status.set(f"last scan, not indexed: {report}")
        self.apply(keep=keep["path"] if keep else None)

    def rescan(self, first_time: bool = False) -> None:
        """Incremental read-only scan in a background thread; the table reloads when it finishes."""
        if self._scanning:
            return
        self._scanning = True
        head = ("building the index (read-only; several minutes for ~40k episodes)"
                if first_time or not self.rows else "refreshing the index (read-only, incremental)")
        self.status.set(head + "...")

        def progress(line: str) -> None:
            self._post(lambda: self.status.set(f"{head}: {line.strip()}"))

        def work():
            try:
                stats = self.scan_fn(progress=progress)
                msg = (f"index refreshed: {stats['added_or_updated']} new/updated, {stats['removed']} removed, "
                       f"{stats['wall_s']} s" + (f" · not indexed: {stats['not_indexed']}"
                                                if stats.get("not_indexed") else ""))
            except Exception as exc:  # noqa: BLE001
                msg = f"scan failed: {exc}"
            print(msg)

            def done():
                self._scanning = False
                self.reload()
                self.status.set(msg)
            self._post(done)

        threading.Thread(target=work, daemon=True).start()
        self._start_draining()

    def filtered(self) -> List[Dict[str, Any]]:
        v = {k: var.get() for k, var in self.vars.items()}
        text = v["text"].strip()
        min_t = None if v["min_targets"] == "any" else int(v["min_targets"])
        out = []
        for r in self.rows:
            if v["milestone"] != "any" and r["milestone"] != v["milestone"]:
                continue
            if v["character"] != "any" and (r["character"] or UNKNOWN) != v["character"]:
                continue
            if v["stage"] != "any" and (r["stage"] or UNKNOWN) != v["stage"]:
                continue
            if v["role"] != "any" and r["role"] != v["role"]:
                continue
            if v["end"] != "any" and r["end_label"] != v["end"]:
                continue
            if min_t is not None and (r["targets"] is None or r["targets"] < min_t):
                continue
            if v["verdict"] != "any" and (r["replay"] or "none") != v["verdict"]:
                continue
            if not self.show_tests.get() and r["is_test"]:
                continue
            if text and not matches_text(r, text):
                continue
            out.append(r)
        return out

    def apply(self, keep: Optional[str] = None) -> None:
        if keep is None:
            cur = self.table.selected()
            keep = cur["path"] if cur else None
        if self._search_after is not None:  # a pending debounced search is covered by this pass
            self.root.after_cancel(self._search_after)
            self._search_after = None
        rows = self.filtered()
        best = self.best_run.get()
        if not best and self.sort_key == "episodes":
            self.sort_key, self.sort_desc = "targets", True
        self.view = sort_view(best_per_run(rows, self.rows) if best else rows, self.sort_key, self.sort_desc)
        cols = list(COLUMNS)
        if best:
            cols.insert([c[0] for c in cols].index("run") + 1, EPISODES_COLUMN)
        self.table.columns = cols
        self.table.merge_workers = best
        self.table.sort_key, self.table.sort_desc = self.sort_key, self.sort_desc
        self.table.set_rows(self.view, keep=keep)
        hidden = sum(1 for r in self.rows if r["is_test"]) if not self.show_tests.get() else 0
        tests = f" ({hidden:,} tests hidden)" if hidden else ""
        self.count.set(f"{len(self.view):,} runs (best of {len(rows):,} episodes){tests}" if best
                       else f"{len(self.view):,} of {len(self.rows):,} episodes{tests}")
        self.show_card(self.table.selected())

    def _search_changed(self) -> None:
        if self._search_after is not None:
            self.root.after_cancel(self._search_after)
        self._search_after = self.root.after(150, self._search_apply)

    def _search_apply(self) -> None:
        self._search_after = None
        self.apply()

    def reset_filters(self) -> None:
        for name, var in self.vars.items():
            var.set("" if name == "text" else "any")
        self.show_tests.set(False)
        self.best_run.set(False)
        self.apply()

    def sort_by(self, key: str) -> None:
        if key == self.sort_key:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key, self.sort_desc = key, key in DESCENDING_BY_DEFAULT
        self.apply()

    # -- details card -----------------------------------------------------------------------------------------------

    def show_card(self, r: Optional[Dict[str, Any]]) -> None:
        for w in self.card_grid.winfo_children():
            w.destroy()
        for b in self.buttons:
            b.configure(state="normal" if r else "disabled")
        if r is None:
            self.card_title.configure(text="Select an episode")
            self._card_path_text = ""
            self.card_path_tip.text = ""
            self._fit_card_path()
            return
        self.card_title.configure(text=r["episode_id"])
        full = str(REPO_ROOT / r["path"])
        self._card_path_text = r["path"].replace("/", os.sep)
        self.card_path_tip.text = full
        self._fit_card_path()
        fields = card_fields(r)
        per_col = (len(fields) + 2) // 3
        for n, (k, val) in enumerate(fields):
            col, row = divmod(n, per_col)
            tk.Label(self.card_grid, text=k, font=UI_FONT, fg=GREY_TEXT, bg="#ffffff", anchor="nw").grid(
                row=row, column=2 * col, sticky="nw", padx=(0 if col == 0 else 24, 8))
            tk.Label(self.card_grid, text=val, font=UI_FONT, fg=INK, bg="#ffffff", anchor="nw", justify="left",
                     wraplength=360).grid(row=row, column=2 * col + 1, sticky="nw")
        for c in range(6):
            self.card_grid.columnconfigure(c, weight=1 if c % 2 else 0)

    def _fit_card_path(self) -> None:
        text = middle_ellipsis(self._card_path_text, self.card_path.winfo_width() - 6, self._path_font.measure)
        if self.card_path.cget("text") != text:
            self.card_path.configure(text=text)

    # -- actions --------------------------------------------------------------------------------------------------

    def selected(self) -> Optional[Dict[str, Any]]:
        return self.table.selected()

    def _spawn(self, extra: List[str], capture: bool) -> Optional[subprocess.Popen]:
        r = self.selected()
        if r is None:
            self.status.set("select an episode first")
            return None
        path = str(REPO_ROOT / r["path"])
        kw: Dict[str, Any] = {"cwd": str(REPO_ROOT)}
        if capture:  # headless check: read its report
            kw.update(stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            argv = [sys.executable, str(VIEWER), path, *extra]
        else:  # windowed viewer through the windowless opener: start-up errors become message boxes
            argv = [sys.executable, str(OPENER), path, *extra]
        p = subprocess.Popen(argv, **kw)
        self.children.append(p)
        return p

    def play(self) -> None:
        r = self.selected()
        if self._spawn([], capture=False):
            self.status.set(f"viewer started: {r['episode_id']}")

    def check(self) -> None:
        r = self.selected()
        p = self._spawn(["--check"], capture=True)
        if p is None:
            return
        self.status.set(f"headless replay of {r['episode_id']} running...")

        def wait():
            out, _ = p.communicate()
            last = [ln for ln in out.splitlines() if ln.startswith(("MATCH", "DESYNC", "error"))]
            msg = last[-1] if last else f"check exited with code {p.returncode}"
            self._post(lambda: (setattr(self, "_checking_one", False), self.status.set(msg), self.reload()))

        self._checking_one = True
        threading.Thread(target=wait, daemon=True).start()
        self._start_draining()

    def _post(self, fn: Callable[[], None]) -> None:
        """From any thread: run fn on the Tk thread."""
        self._events.put(fn)

    def _drain(self) -> None:
        """Tk thread: run the posted callbacks; keep polling while a scan or a check is running."""
        self._draining = False
        while True:
            try:
                fn = self._events.get_nowait()
            except queue.Empty:
                break
            fn()
        if self.batch is not None or self._scanning or self._checking_one:
            self._start_draining()

    def _start_draining(self) -> None:
        if not self._draining:
            self._draining = True
            self.root.after(100, self._drain)

    def _confirm(self, n: int) -> bool:
        minutes = n * CHECK_SECONDS / 60
        return messagebox.askyesno(
            "Check filtered episodes",
            f"Replay {n:,} episodes headless to check MATCH / DESYNC?\n\n"
            f"About {minutes:.0f} min ({CHECK_SECONDS:g} s each, one BattleShip process at a time). "
            "runs/ is only read; verdicts go to replay/_local/verdicts.jsonl. You can cancel at any time.",
            parent=self.root)

    def check_filtered(self) -> None:
        """Start (or cancel) a background headless check of every episode now listed."""
        if self.batch is not None:
            self.batch.cancel()
            self.status.set("cancelling the check...")
            return
        rows = list(self.view)
        if not rows:
            self.status.set("nothing to check: no episode is listed")
            return
        if len(rows) > CONFIRM_ABOVE and not self._confirm(len(rows)):
            return
        self._batch_rows = {str(REPO_ROOT / r["path"]): r for r in rows}
        self._batch_n = len(rows)
        factory = self.batch_factory
        if factory is None:
            from replay_game import CheckBatch as factory
        post = self._post
        self.batch = factory([REPO_ROOT / r["path"] for r in rows],
                             on_start=lambda i, path: post(lambda: self._batch_start(i, path)),
                             on_result=lambda i, path, res: post(lambda: self._batch_result(i, path, res)),
                             on_done=lambda b: post(lambda: self._batch_done(b)))
        self.check_btn.configure(text="Cancel check")
        self.batch.start()
        self._start_draining()

    def _batch_counts(self) -> str:
        c = self.batch.counts if self.batch is not None else {}
        failed = c.get("error", 0) + c.get("incomplete", 0)
        return f"{c.get('MATCH', 0)} MATCH · {c.get('DESYNC', 0)} DESYNC" + (f" · {failed} failed" if failed else "")

    def _batch_start(self, i: int, path: Path) -> None:
        if self.batch is not None:
            self.status.set(f"checking {i + 1:,}/{self._batch_n:,}: {Path(path).name} · {self._batch_counts()}")

    def _batch_result(self, _i: int, path: Path, res: Dict[str, Any]) -> None:
        r = self._batch_rows.get(str(path))
        if r is not None and res["verdict"] in ("MATCH", "DESYNC"):
            r["replay"], r["replay_mode"] = res["verdict"], "headless"
            ticks = (res.get("trajectory") or {}).get("target_break_ticks")
            if res["verdict"] == "MATCH" and r["last_target_tick"] is None and isinstance(ticks, list):
                set_last_target(r, {"replay": ticks})  # a replay fills in an unknown last target
            self.table.redraw()
            if self.table.selected() is r:
                self.show_card(r)

    def _batch_done(self, b) -> None:
        done, n = b.finished_count, self._batch_n
        counts = self._batch_counts()
        self.batch = None
        self.check_btn.configure(text="Check filtered…")
        self.reload()  # verdicts, tags and last targets from the index, as recorded
        self.status.set(f"check {'cancelled after' if b.state == 'cancelled' else 'finished:'} {done:,} of {n:,} "
                        f"episodes · {counts}")

    def close(self) -> None:
        if self._search_after is not None:
            self.root.after_cancel(self._search_after)
        if self.batch is not None:
            self.batch.cancel()
            self.batch.join(20)
        self.root.destroy()

    def copy_path(self) -> None:
        r = self.selected()
        if r:
            self.root.clipboard_clear()
            self.root.clipboard_append(str(REPO_ROOT / r["path"]))
            self.status.set("path copied")

    def open_folder(self) -> None:
        r = self.selected()
        if r and hasattr(os, "startfile"):
            os.startfile(str(REPO_ROOT / r["path"]))  # read-only use: opens Explorer on the folder
