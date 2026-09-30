#!/usr/bin/env python3
"""Tk control panel, HUD overlay and saved-frame view for the replay viewer (standard library only).

The game renders in its own window; the viewer never draws into it. The HUD
is a separate borderless, click-through, color-keyed tk window kept on top of
the game window's client area (tick, stick direction, button, targets broken,
playback state). The control panel is an ordinary tk window.

Stepping back uses the saved-frame history (replay_history.py): a stored frame
of an earlier tick is shown in a click-through window over the game window,
framed in cyan, while the HUD shows "SAVED FRAME tick N" and the live tick. The
game itself is not touched until playback resumes past the saved frames or a
tick older than the history is requested ("rebuilding to tick N": fresh
process + fast-forward). All game control goes through ReplayEngine commands;
the UI only reads engine snapshots and the history.

Panel layout, top to bottom: verdict badge + recorded-episode header, the
live state in fixed-width columns, the playback status, the timeline (with
target-break markers from TargetPrepass when one is given), the controls
(media buttons | speed | tick + Jump), a one-line result that expands to
every check, and a grey footer with the keys and the saved-frame diagnostics.
Every text that changes while playing has a fixed width, so the window never
resizes or shifts under the cursor.
"""

from __future__ import annotations

import math
import os
import re
import subprocess
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import ttk
from typing import Any, Dict, List, Optional, Tuple

import replay_win32 as win32
from replay_episode import DIGEST_CHECK, REPO_ROOT, Check, Verdict, button_name, stick_arrow
from replay_game import SPEEDS, MAX_RENDERED_SPEED, ReplayEngine, TargetPrepass, load_state, save_state
from replay_history import SavedFrame, plan_back, plan_forward, plan_view, ppm
from replay_status import status_label

POLL_MS = 33
REVIEW_PLAY_MS = 8
HUD_KEY = "#010101"  # color key: pixels of exactly this color are transparent
HUD_W, HUD_H = 330, 160
FONT = ("Consolas", 11)
FONT_BIG = ("Consolas", 12, "bold")
GREEN, RED, AMBER, WHITE, CYAN = "#4ade80", "#f87171", "#fbbf24", "#f5f5f5", "#22d3ee"
REVIEW_BANNER_BG = "#0e4a5a"
RUNS_DIR = REPO_ROOT / "runs"

# Panel (light background) colors and fonts.
UI_FONT = ("Segoe UI", 9)
SMALL = ("Segoe UI", 8)
HEAD_FONT = ("Segoe UI", 11, "bold")
MONO = ("Consolas", 11)
MONO_SMALL = ("Consolas", 10)
GREY_TEXT = "#6b7280"
INK = "#111827"
DARK_GREEN, DARK_RED, DARK_AMBER, DARK_CYAN = "#15803d", "#b91c1c", "#b45309", "#0e7490"
BADGE_GREY = "#9ca3af"
MARKER = "#d97706"
# Badge (text, background): the verdict, shown once.
BADGES = {"MATCH": ("MATCH", DARK_GREEN), "DESYNC": ("DESYNC", DARK_RED), "pending": ("PENDING", BADGE_GREY),
          "stopped": ("STOPPED", "#57534e")}
# Live-state columns: (key, header, width in characters, anchor).
COLUMNS: Tuple[Tuple[str, str, int, str], ...] = (
    ("tick", "TICK", 13, "w"), ("stick", "STICK", 11, "w"), ("button", "BUTTON", 9, "w"),
    ("targets", "TARGETS", 8, "w"), ("x", "X", 9, "e"), ("y", "Y", 9, "e"), ("status", "  ACTION STATE", 26, "w"),
)
KEYS_HELP = "Space play/pause · ← , back · → . step · + − speed · R restart · G jump · Q quit · other keys in the game window can desync"
RESULT_WIDTH = 96  # characters of the expanded check list


def speed_label(v: float) -> str:
    return f"{v:g}x" + (" (capped at 1x)" if v > MAX_RENDERED_SPEED else "")


def tick_label(tick: int) -> str:
    return "tick-0 state" if tick < 0 else f"tick {tick}"


class Hud:
    """Borderless overlay window following the game window's client area."""

    def __init__(self, root: tk.Tk):
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        try:
            self.win.attributes("-transparentcolor", HUD_KEY)
        except tk.TclError:
            pass
        self.win.configure(bg=HUD_KEY)
        self.canvas = tk.Canvas(self.win, width=HUD_W, height=HUD_H, bg=HUD_KEY, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.win.geometry(f"{HUD_W}x{HUD_H}+-2000+-2000")
        self.visible = True
        self.hwnd: Optional[int] = None
        self._clicked_through = False
        self._last_geom = ""

    def ensure_click_through(self) -> None:
        if self._clicked_through:
            return
        self.win.update_idletasks()
        try:
            self.hwnd = int(self.win.wm_frame(), 16)
        except (tk.TclError, ValueError):
            self.hwnd = None
        self._clicked_through = win32.make_click_through(self.hwnd)

    def show(self, x: int, y: int) -> None:
        geom = f"{HUD_W}x{HUD_H}+{x}+{y}"
        if not self.visible:
            self.win.deiconify()
            self.visible = True
        if geom != self._last_geom:
            self.win.geometry(geom)
            # Apply the move before re-asserting topmost: with the click-through styles set, a -topmost change
            # issued while the geometry request is still pending makes Tk drop the move.
            self.win.update_idletasks()
            self._last_geom = geom
            self.win.attributes("-topmost", True)

    def raise_above(self) -> None:
        self.win.lift()
        self.win.attributes("-topmost", True)

    def hide(self) -> None:
        if self.visible:
            self.win.withdraw()
            self.visible = False

    def _text(self, x: int, y: int, text: str, color: str = WHITE, font=FONT) -> None:
        for dx, dy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            self.canvas.create_text(x + dx, y + dy, text=text, fill="#000000", anchor="nw", font=font)
        self.canvas.create_text(x, y, text=text, fill=color, anchor="nw", font=font)

    def draw(self, view: Dict[str, Any]) -> None:
        c = self.canvas
        c.delete("all")
        y0 = 4
        if view["review"]:
            # Unmistakable: a solid banner (not color-keyed) naming the saved tick and where the live game is.
            c.create_rectangle(0, 0, HUD_W, 24, fill=REVIEW_BANNER_BG, outline=CYAN, width=2)
            c.create_text(8, 4, anchor="nw", fill=CYAN, font=FONT_BIG,
                          text=f"◀ SAVED FRAME  {tick_label(view['tick'])}")
            c.create_text(HUD_W - 6, 5, anchor="ne", fill=WHITE, font=FONT, text=f"live {view['live_tick']}")
            y0 = 28
        row = view["row"]
        obs = view["observation"]
        self._text(8, y0, f"{tick_label(view['tick'])}  / {view['rows'] - 1}", CYAN if view["review"] else WHITE,
                   FONT_BIG)
        if row is not None:
            self._text(8, y0 + 22, f"stick {stick_arrow(row.stick_x, row.stick_y)} ({row.stick_x:+d},{row.stick_y:+d})")
            self._text(8, y0 + 42, f"button {button_name(row.buttons)}", AMBER if row.buttons else WHITE)
        else:
            self._text(8, y0 + 22, "stick -")
            self._text(8, y0 + 42, "button -")
        tb, tt = view["targets_broken"], view["targets_total"]
        self._text(8, y0 + 62, f"targets {tb if tb is not None else '-'}/{tt}")
        self._text(8, y0 + 108, view["status"], view["status_color"])  # below x / y: long statuses don't overlap
        # stick diagram
        cx, cy, r = HUD_W - 40, y0 + 40, 26
        c.create_oval(cx - r - 1, cy - r - 1, cx + r + 1, cy + r + 1, outline="#000000", width=3)
        c.create_oval(cx - r, cy - r, cx + r, cy + r, outline=WHITE, width=1)
        c.create_line(cx - r, cy, cx + r, cy, fill="#777777")
        c.create_line(cx, cy - r, cx, cy + r, fill="#777777")
        if row is not None:
            sx, sy = row.stick_x / 80.0, row.stick_y / 80.0
            norm = math.hypot(sx, sy)
            if norm > 1:
                sx, sy = sx / norm, sy / norm
            px, py = cx + sx * r, cy - sy * r
            c.create_line(cx, cy, px, py, fill=AMBER, width=2)
            c.create_oval(px - 5, py - 5, px + 5, py + 5, fill=AMBER, outline="#000000")
        if obs:
            self._text(HUD_W - 118, y0 + 72, f"x {obs.get('position_x', 0):8.1f}")
            self._text(HUD_W - 118, y0 + 90, f"y {obs.get('position_y', 0):8.1f}")


class ReviewOverlay:
    """A click-through window exactly over the game's client area showing one saved frame, framed in cyan."""

    BORDER = 4

    def __init__(self, root: tk.Tk):
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg="#000000")
        self.canvas = tk.Canvas(self.win, bg="#000000", highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.win.withdraw()
        self.visible = False
        self.hwnd: Optional[int] = None
        self._image: Optional[tk.PhotoImage] = None
        self._key: Optional[tuple] = None
        self._geom = ""

    def show(self, frame: SavedFrame, rect: tuple) -> bool:
        """Display `frame` over rect; True when the window (re)appeared or moved (the HUD must be raised again)."""
        x, y, w, h = rect
        changed = False
        key = (frame.tick, w, h)
        if key != self._key:
            img = tk.PhotoImage(data=ppm(frame.width, frame.height, frame.rgb), format="PPM")
            factor = max(1, int(round(w / frame.width))) if frame.width else 1
            self._image = img.zoom(factor) if factor > 1 else img
            c = self.canvas
            c.delete("all")
            c.create_image(0, 0, image=self._image, anchor="nw")
            b = self.BORDER
            c.create_rectangle(b // 2, b // 2, w - b // 2, h - b // 2, outline=CYAN, width=b)
            self._key = key
        geom = f"{w}x{h}+{x}+{y}"
        if not self.visible:
            self.win.deiconify()
            self.visible = True
            changed = True
            self.win.update_idletasks()
            if self.hwnd is None:
                try:
                    self.hwnd = int(self.win.wm_frame(), 16)
                    win32.make_click_through(self.hwnd)
                except (tk.TclError, ValueError):
                    self.hwnd = None
        if geom != self._geom:
            self.win.geometry(geom)
            self.win.update_idletasks()
            self._geom = geom
            self.win.attributes("-topmost", True)
            changed = True
        return changed

    def hide(self) -> None:
        if self.visible:
            self.win.withdraw()
            self.visible = False


def status_text(snap: Dict[str, Any], *, verdict: bool = False) -> str:
    """Playback state. The verdict word is only included on request (the HUD over the game window); the panel
    shows it once, in the badge."""
    phase = snap["phase"]
    if snap.get("rebuilding") and phase in ("booting", "jumping"):
        target = snap.get("rebuild_to")
        if phase == "booting":
            return f"⟲ rebuilding to {tick_label(target)}: starting BattleShip"
        return f"⟲ rebuilding to {tick_label(target)} ({max(snap['live_tick'], 0)}/{target})"
    if phase == "playing":
        tps = snap["achieved_tps"]
        rate = f" {tps:4.1f} ticks/s" if tps else ""
        return f"▶ {speed_label(snap['speed'])}{rate}"
    if phase == "paused":
        return "❚❚ paused"
    if phase == "jumping":
        return f"» fast-forward to tick {snap['jump_to'] - 1}"
    if phase == "booting":
        return "starting BattleShip..."
    if phase == "ended":
        kind = {"rows_exhausted": "truncated"}.get(snap["end_kind"], snap["end_kind"])  # the checks' word
        where = f"{kind} at {tick_label(snap['live_tick'])}"
        return f"■ {snap['verdict'] or '?'}: {where}" if verdict else f"■ ended: {where}"
    if phase == "error":
        return "BattleShip stopped - press Restart"
    return phase


def status_color(snap: Dict[str, Any]) -> str:
    if snap.get("rebuilding"):
        return AMBER
    if snap["phase"] == "ended":
        return GREEN if snap["verdict"] == "MATCH" else RED
    if snap["phase"] == "error" or snap["mismatch"]:
        return RED
    return WHITE


# -- panel texts (pure functions of the summary / snapshot; tested in replay_tests.py) -------------------------


def _recorded(value: Any) -> bool:
    return value is not None and value != "" and value != "not recorded" and value != "unknown"


def header_lines(s: Dict[str, Any]) -> List[str]:
    """The recorded-episode lines under the episode id, without fields that are None or not recorded."""
    def join(pairs):
        return " · ".join(f"{k} {v}" for k, v in pairs if _recorded(v))
    end = s.get("end") if _recorded(s.get("end")) else None
    if end and _recorded(s.get("end_detail")):
        end = f"{end} ({s['end_detail']})"
    rows = s.get("rows")
    if rows is not None and s.get("rows_to_replay") not in (None, rows):
        rows = f"{rows} ({s['rows_to_replay']} replayable)"
    lines = [join((("role", s.get("role")), ("run", s.get("run_id")), ("profile", s.get("profile")))),
             join((("observation", s.get("observation")), ("reward", s.get("reward")))),
             join((("recorded end", end), ("targets", s.get("targets_broken")), ("rows", rows),
                   ("prefix", s.get("prefix_rows") or None)))]
    return [line for line in lines if line]


def runs_relative(directory: str, runs_dir: Path = RUNS_DIR) -> Tuple[str, str]:
    """("runs\\", path inside runs) for an episode under runs/, else ("", the full path)."""
    try:
        return "runs" + os.sep, str(Path(directory).resolve().relative_to(Path(runs_dir).resolve()))
    except ValueError:
        return "", str(directory)


def verdict_badge(snap: Dict[str, Any]) -> Tuple[str, str]:
    """(text, background). A per-row clock mismatch already decides DESYNC before the end."""
    if snap.get("verdict") in BADGES:
        return BADGES[snap["verdict"]]
    if snap.get("mismatch"):
        return BADGES["DESYNC"]
    if snap.get("error"):
        return BADGES["stopped"]
    return BADGES["pending"]


def fmt_value(v: Any) -> str:
    """Shown value: floats to 3 decimals."""
    return f"{v:.3f}" if isinstance(v, float) else str(v)


def full_value(v: Any) -> str:
    """Copied value: full precision (a float's repr round-trips exactly)."""
    return repr(v) if isinstance(v, float) else str(v)


def root_cause(v: Verdict) -> Optional[Check]:
    """The failed actions-digest check, if any: actions.jsonl then differs from what the recorded run submitted,
    so the replay fed other inputs and every other failure most likely follows from that."""
    return next((c for c in v.checks if c.name == DIGEST_CHECK and not c.ok), None)


def result_summary(snap: Dict[str, Any]) -> Tuple[str, str, bool]:
    """(one-line summary, color, has details)."""
    v = snap.get("verdict_detail")
    if snap.get("error"):
        return "✖ BattleShip stopped: no verdict", DARK_RED, True
    if v is not None:
        ok = sum(1 for c in v.checks if c.ok)
        failed = len(v.checks) - ok
        if root_cause(v) is not None:
            down = failed - 1
            return (f"✖ DESYNC — likely root cause: actions.jsonl differs from the recording (actions digest); "
                    f"{down} downstream failure{'' if down == 1 else 's'}, {ok} ok, {len(v.skipped)} skipped",
                    DARK_RED, True)
        parts = ([f"{failed} failed"] if failed else []) + [f"{ok} ok", f"{len(v.skipped)} skipped"]
        return (f"{'✔' if v.match else '✖'} {v.word} — {', '.join(parts)}  (replay vs metadata.json)",
                DARK_GREEN if v.match else DARK_RED, True)
    if snap.get("mismatch"):
        return f"✖ clocks differ from the recording at {snap['mismatch']}", DARK_RED, False
    return "Checks against metadata.json run when the episode ends.", GREY_TEXT, False


def observation_table(rows: List[Tuple[str, Any, Any]]) -> List[Tuple[str, str, str]]:
    """field / expected / got lines (shown text, tag, copied text): floats shown to 3 decimals, copied at full
    precision, tab-separated."""
    shown = [("field", "expected", "got")] + [(k, fmt_value(a), fmt_value(b)) for k, a, b in rows]
    w = [max(len(r[i]) for r in shown) for i in range(3)]
    out = [(f"    {shown[0][0]:<{w[0]}}  {shown[0][1]:>{w[1]}}  {shown[0][2]:>{w[2]}}", "table_head",
            "    field\texpected\tgot")]
    for (k, a, b), (_, sa, sb) in zip(rows, shown[1:]):
        out.append((f"    {k:<{w[0]}}  {sa:>{w[1]}}  {sb:>{w[2]}}", "table",
                    f"    {k}\t{full_value(a)}\t{full_value(b)}"))
    return out


def result_details(snap: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    """(shown text, tag, copied text) lines of the expanded result: every check, then the skipped ones. With a
    failed actions digest, that check is marked as the likely root cause and the other failures as downstream.
    An observation mismatch is a field / expected / got table."""
    if snap.get("error"):
        return [(snap["error"], "fail", snap["error"])]
    v = snap.get("verdict_detail")
    if v is None:
        return []
    root = root_cause(v)
    out: List[Tuple[str, str, str]] = []
    for c in v.checks:
        if c.ok:
            line = f"✔ {c.name}: {c.got}"
            out.append((line, "ok", line))
            continue
        role, tag = ("", "fail") if root is None else (
            ("likely root cause · ", "root") if c is root else ("downstream · ", "downstream"))
        if c.rows:
            line = f"✖ {role}{c.name}: {len(c.rows)} field{'' if len(c.rows) == 1 else 's'} differ"
            out.append((line, tag, line))
            out += observation_table(c.rows)
        else:
            line = f"✖ {role}{c.name}: expected {c.expected}, got {c.got}"
            out.append((line, tag, line))
    out += [(f"– skipped: {s}", "skip", f"– skipped: {s}") for s in v.skipped]
    return out


def middle_ellipsis(text: str, max_px: int, measure, sep: str = os.sep) -> str:
    """`text` if it fits in max_px pixels, else head + '…' + tail: the tail always keeps the last path component
    (the episode folder), the head is as long as still fits."""
    if measure(text) <= max_px:
        return text
    cut = text.rstrip(sep).rfind(sep)
    if cut <= 0:
        return text  # a single component: nothing to elide around
    tail = text[cut:]
    lo, hi = 0, cut
    while lo < hi:  # largest head length that fits
        mid = (lo + hi + 1) // 2
        if measure(text[:mid] + "…" + tail) <= max_px:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + "…" + tail


def live_columns(view: Dict[str, Any]) -> Dict[str, str]:
    """Texts of the fixed-width live-state columns (tick, stick, button, targets, x, y, action state)."""
    row, obs = view["row"], view["observation"] or {}
    tick = view["tick"]
    tb, tt = view["targets_broken"], view["targets_total"]
    x, y = obs.get("position_x"), obs.get("position_y")
    return {
        "tick": tick_label(tick) if tick < 0 else f"{tick} / {view['rows'] - 1}",
        "stick": f"{stick_arrow(row.stick_x, row.stick_y)} {row.stick_x:+d} {row.stick_y:+d}" if row else "-",
        "button": button_name(row.buttons) if row else "-",
        "targets": f"{tb if tb is not None else '-'}/{tt}",
        "x": f"{x:.1f}" if isinstance(x, (int, float)) else "-",
        "y": f"{y:.1f}" if isinstance(y, (int, float)) else "-",
        "status": "  " + status_label(obs.get("fighter_status_id")),
    }


def marker_groups(break_ticks: List[int]) -> List[Tuple[int, int, int]]:
    """(tick, first target number, last target number) per tick where targets broke."""
    groups: List[Tuple[int, int, int]] = []
    for n, tick in enumerate(break_ticks, start=1):
        if groups and groups[-1][0] == tick:
            groups[-1] = (tick, groups[-1][1], n)
        else:
            groups.append((tick, n, n))
    return groups


def popup_tip(parent: tk.Widget, text: str, x: int, y: int) -> tk.Toplevel:
    """A small borderless hint window at screen position (x, y)."""
    tip = tk.Toplevel(parent)
    tip.overrideredirect(True)
    tip.attributes("-topmost", True)
    tk.Label(tip, text=text, bg="#ffffe0", fg=INK, relief="solid", bd=1, font=SMALL, padx=4, justify="left").pack()
    tip.geometry(f"+{x}+{y}")
    return tip


class Tooltip:
    """A small hint under a widget while the pointer is over it."""

    def __init__(self, widget: tk.Widget, text: str):
        self.widget, self.text, self.tip = widget, text, None
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")

    def show(self, _event=None) -> None:
        if self.tip is not None:
            return
        self.tip = popup_tip(self.widget, self.text, self.widget.winfo_rootx(),
                             self.widget.winfo_rooty() + self.widget.winfo_height() + 2)

    def hide(self, _event=None) -> None:
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None


class ViewerUI:
    def __init__(self, engine: ReplayEngine, *, summary: Dict[str, Any], hud: bool = True, exit_at_end: bool = False,
                 prepass: Optional[TargetPrepass] = None):
        self.engine = engine
        self.history = engine.history
        self.last_tick = len(engine.rows) - 1
        self.summary = summary
        self.exit_at_end = exit_at_end
        self.prepass = prepass
        self.root = tk.Tk()
        self.root.title(f"Replay - {summary['episode_id']}")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.review = ReviewOverlay(self.root)
        self.hud = Hud(self.root) if hud else None
        self.view_tick: Optional[int] = None  # None = live game; else the saved tick shown
        self._review_play: Optional[tuple] = None  # (t0, start tick) while playing through saved frames
        self._pending_back = False
        self._note = ""
        self._closing = False
        self._end_seen = False
        self._result_key: Optional[tuple] = None
        self._result_open = False
        self._result_has_details = False
        self._copy_lines: List[str] = []  # full-precision text of each line of the check list
        self._markers_drawn: Optional[tuple] = None
        self._marker_tip: Optional[tk.Toplevel] = None
        self._seeking = False
        self._panel_placed = False
        self._keys_prev: Dict[str, bool] = {}
        self._repeat_at: Dict[str, float] = {}
        self._build()
        # Only the position is restored: the height follows the content (collapsed or expanded result).
        saved = load_state().get("panel_geometry")
        m = re.search(r"([+-]-?\d+[+-]-?\d+)$", saved) if isinstance(saved, str) else None
        if m:
            try:
                self.root.geometry(m.group(1))
                self._panel_placed = True
            except tk.TclError:
                pass

    # -- layout -----------------------------------------------------------------------------------------

    def _build(self) -> None:
        s = self.summary
        root = self.root
        root.minsize(640, 1)
        style = ttk.Style(root)
        style.configure("Media.TButton", font=("Segoe UI Symbol", 12), padding=(4, 1))
        pad = {"padx": 10}

        # Header: verdict badge (shown once, here) + the recorded episode.
        head = ttk.Frame(root)
        head.pack(fill="x", padx=10, pady=(10, 6))
        self.badge = tk.Label(head, text=BADGES["pending"][0], bg=BADGES["pending"][1], fg="white", width=9,
                              font=("Segoe UI", 13, "bold"), padx=6, pady=8)
        self.badge.grid(row=0, column=0, rowspan=5, sticky="nw", padx=(0, 12))
        ttk.Label(head, text=s["episode_id"], font=HEAD_FONT).grid(row=0, column=1, sticky="w")
        lines = header_lines(s)
        for i, text in enumerate(lines, start=1):
            ttk.Label(head, text=text, font=UI_FONT, foreground=GREY_TEXT).grid(row=i, column=1, sticky="w")
        where = ttk.Frame(head)
        where.grid(row=len(lines) + 1, column=1, sticky="ew", pady=(3, 0))
        # The path (relative to runs\) with a middle ellipsis when it does not fit, so the episode folder name
        # stays visible; the full path is in the tooltip and right-click copies it.
        prefix, rel = runs_relative(s["directory"])
        self.path_text = prefix + rel
        self._path_font = tkfont.Font(root=root, font=UI_FONT)
        self.path_label = tk.Label(where, text=self.path_text, font=UI_FONT, fg=INK, anchor="w", width=1)
        self.path_label.pack(side="left", fill="x", expand=True)
        self.path_label.bind("<Configure>", lambda e: self._fit_path())
        self.path_label.bind("<Button-3>", lambda e: self._copy_path())
        self.path_tip = Tooltip(self.path_label, f"{s['directory']}\n(right-click copies the full path)")
        ttk.Button(where, text="Open folder", takefocus=False, command=self._open_folder).pack(side="left", padx=(6, 0))
        head.columnconfigure(1, weight=1)

        ttk.Separator(root).pack(fill="x", **pad)

        # Live state: fixed-width columns, so nothing shifts while playing.
        live = tk.Frame(root)
        live.pack(fill="x", padx=10, pady=(6, 0))
        self.cells: Dict[str, tk.Label] = {}
        for col, (key, title, width, anchor) in enumerate(COLUMNS):
            tk.Label(live, text=title, font=("Consolas", 8), fg=GREY_TEXT, anchor=anchor, padx=0).grid(
                row=0, column=col, sticky="ew")
            cell = tk.Label(live, text="-", font=MONO, fg=INK, width=width, anchor=anchor, padx=0)
            cell.grid(row=1, column=col, sticky="ew")
            self.cells[key] = cell
        # Playback status (fixed width, two lines for a message).
        self.status = tk.StringVar(value="starting...")
        self.message = tk.StringVar(value="")
        self.status_label = tk.Label(root, textvariable=self.status, font=("Segoe UI", 10, "bold"), fg=INK,
                                     anchor="w", width=80)
        self.status_label.pack(fill="x", padx=10, pady=(6, 0))
        tk.Label(root, textvariable=self.message, font=UI_FONT, fg=GREY_TEXT, anchor="nw", justify="left",
                 width=100, height=1).pack(fill="x", padx=10)

        # Timeline + target-break markers (TargetPrepass).
        self.seek = tk.Scale(root, from_=0, to=max(0, self.last_tick), orient="horizontal", showvalue=True,
                             resolution=1, length=600, takefocus=0, highlightthickness=0)
        self.seek.pack(fill="x", padx=10)
        self.seek.bind("<ButtonPress-1>", lambda e: setattr(self, "_seeking", True))
        self.seek.bind("<ButtonRelease-1>", self._seek_release)
        self.markers = tk.Canvas(root, height=18, highlightthickness=0, bd=0)
        self.markers.pack(fill="x", padx=10)
        self.seek.bind("<Configure>", lambda e: self._draw_markers(force=True), add="+")

        # Controls: media buttons | speed | tick + Jump.
        bar = ttk.Frame(root)
        bar.pack(fill="x", padx=10, pady=(2, 6))
        media = ttk.Frame(bar)
        media.pack(side="left")
        self.restart_btn = ttk.Button(media, text="⏮", width=3, style="Media.TButton", takefocus=False,
                                      command=self.restart)
        back = ttk.Button(media, text="◀❚", width=3, style="Media.TButton", takefocus=False, command=self.step_back)
        self.play_btn = ttk.Button(media, text="▶", width=4, style="Media.TButton", takefocus=False,
                                   command=self.toggle)
        step = ttk.Button(media, text="❚▶", width=3, style="Media.TButton", takefocus=False, command=self.step_forward)
        for btn, tip in ((self.restart_btn, "Restart from the tick-0 state (R)"),
                         (back, "Back one tick: saved frame, or rebuild when older (← or ,)"),
                         (self.play_btn, "Play / pause (Space)"), (step, "Step one tick (→ or .)")):
            btn.pack(side="left", padx=(0, 2))
            Tooltip(btn, tip)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Label(bar, text="Speed", font=UI_FONT).pack(side="left")
        self.speed = ttk.Combobox(bar, width=16, state="readonly", takefocus=False, values=[speed_label(v) for v in SPEEDS])
        self.speed.current(SPEEDS.index(self.engine.speed) if self.engine.speed in SPEEDS else 2)
        self.speed.bind("<<ComboboxSelected>>", lambda e: self._set_speed(SPEEDS[self.speed.current()]))
        self.speed.pack(side="left", padx=(4, 0))
        Tooltip(self.speed, "+ / − (above 1x only saved-frame playback is faster)")
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Label(bar, text="Tick", font=UI_FONT).pack(side="left")
        self.jump_entry = ttk.Entry(bar, width=7)
        self.jump_entry.pack(side="left", padx=4)
        self.jump_entry.bind("<Return>", self._jump_from_entry)
        jump = ttk.Button(bar, text="Jump", takefocus=False, command=self._jump_from_entry)
        jump.pack(side="left")
        Tooltip(jump, "Show this tick (G focuses the field; -1 = the tick-0 state)")

        # Result: one line, expands to every check (automatically on DESYNC).
        ttk.Separator(root).pack(fill="x", **pad)
        self.result_line = tk.Label(root, text="", font=UI_FONT, fg=GREY_TEXT, anchor="w", justify="left", width=100,
                                    cursor="arrow")
        self.result_line.pack(fill="x", padx=10, pady=(4, 2))
        self.result_line.bind("<Button-1>", lambda e: self._toggle_result())
        self.result_line.bind("<Configure>", lambda e: self.result_line.configure(wraplength=max(200, e.width - 8)))
        self.result = tk.Text(root, height=1, width=RESULT_WIDTH, font=MONO_SMALL, wrap="word", state="disabled",
                              relief="flat", bg="#f9fafb", padx=6, pady=4)
        self.result.tag_configure("ok", foreground=DARK_GREEN)
        self.result.tag_configure("fail", foreground=DARK_RED)
        self.result.tag_configure("root", foreground=DARK_RED, font=("Consolas", 10, "bold"))
        self.result.tag_configure("downstream", foreground="#9f5f5f")
        self.result.tag_configure("table_head", foreground=GREY_TEXT)
        self.result.tag_configure("table", foreground=INK)
        self.result.tag_configure("skip", foreground=GREY_TEXT)
        # Copying from the list gives the full-precision lines (the table shows floats to 3 decimals).
        self.result.bind("<Button-1>", lambda e: self.result.focus_set(), add="+")
        self.result.bind("<<Copy>>", lambda e: self._copy_result(selected=True))
        menu = tk.Menu(root, tearoff=0)
        menu.add_command(label="Copy selected lines (full precision)", command=lambda: self._copy_result(selected=True))
        menu.add_command(label="Copy all checks (full precision)", command=lambda: self._copy_result(selected=False))
        self.result.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

        # Footer: keys (left) and saved-frame / capture / marker diagnostics (right), small and grey.
        self.footer = tk.Frame(root)
        self.footer.pack(fill="x", side="bottom", padx=10, pady=(0, 6))
        tk.Label(self.footer, text=KEYS_HELP, font=SMALL, fg=GREY_TEXT, anchor="w").pack(side="top", anchor="w")
        self.diag = tk.StringVar(value="")
        tk.Label(self.footer, textvariable=self.diag, font=SMALL, fg=GREY_TEXT, anchor="w", width=110).pack(
            side="top", anchor="w")
        self._update_result(self.engine.snapshot())

        for seq, fn in (("<space>", lambda e: self.toggle()),
                        ("<Right>", lambda e: self.step_forward()), ("<period>", lambda e: self.step_forward()),
                        ("<Left>", lambda e: self.step_back()), ("<comma>", lambda e: self.step_back()),
                        ("<plus>", lambda e: self._bump_speed(+1)), ("<equal>", lambda e: self._bump_speed(+1)),
                        ("<KP_Add>", lambda e: self._bump_speed(+1)),
                        ("<minus>", lambda e: self._bump_speed(-1)), ("<KP_Subtract>", lambda e: self._bump_speed(-1)),
                        ("r", lambda e: self.restart()), ("R", lambda e: self.restart()),
                        ("g", lambda e: self._focus_jump()), ("G", lambda e: self._focus_jump()),
                        ("q", lambda e: self.close()), ("<Escape>", lambda e: self.close())):
            self.root.bind(seq, self._shortcut(fn))

    def _shortcut(self, fn):
        def handler(event):
            if event.widget is self.jump_entry and event.keysym not in ("Escape",):
                return None
            if event.widget is self.speed:
                return None
            fn(event)
            return "break"
        return handler

    # -- navigation ---------------------------------------------------------------------------------------

    def _live_tick(self, snap: Optional[Dict[str, Any]] = None) -> int:
        return (snap or self.engine.snapshot())["live_tick"]

    def _busy(self, snap: Dict[str, Any]) -> bool:
        return snap["phase"] in ("booting", "jumping")

    def _enter_review(self, tick: int) -> None:
        self.view_tick = tick
        self._note = ""

    def _exit_review(self) -> None:
        self.view_tick = None
        self._review_play = None

    def _rebuild(self, tick: int) -> None:
        """Older than the saved frames: fresh process + fast-forward (the engine shows 'rebuilding to tick N')."""
        self._exit_review()
        self.engine.send("jump", tick)

    def _apply(self, plan: tuple) -> None:
        kind, tick = plan
        if kind == "saved":
            self._enter_review(tick)
        elif kind == "live":
            self._exit_review()
        elif kind == "rebuild":
            self._rebuild(tick)
        elif kind == "forward":
            self._exit_review()
            self.engine.send("step" if tick == self._live_tick() + 1 else "jump", tick)
        else:
            self._note = "already at the tick-0 state" if tick < 0 else "already at the last row"
        self._refresh()

    def step_back(self) -> None:
        snap = self.engine.snapshot()
        if self._busy(snap):
            return
        self._review_play = None
        if snap["phase"] == "playing":  # stop the game first, then step back from where it stopped
            self.engine.send("pause")
            self._pending_back = True
            return
        self._apply(plan_back(self.view_tick, snap["live_tick"], self.history, self.last_tick))

    def step_forward(self) -> None:
        snap = self.engine.snapshot()
        if self._busy(snap):
            return
        self._review_play = None
        if self.view_tick is None:
            self.engine.send("step")
            return
        self._apply(plan_forward(self.view_tick, snap["live_tick"], self.history, self.last_tick))

    def toggle(self) -> None:
        if self.view_tick is None:
            self.engine.send("toggle")
        elif self._review_play is None:  # play forward through the saved frames, then hand over to the game
            self._review_play = (time.perf_counter(), self.view_tick)
            self.root.after(REVIEW_PLAY_MS, self._review_step)
        else:
            self._review_play = None

    def jump(self, tick: int) -> None:
        snap = self.engine.snapshot()
        tick = max(-1, min(int(tick), self.last_tick))
        self._review_play = None
        self._apply(plan_view(tick, snap["live_tick"], self.history, self.last_tick))

    def restart(self) -> None:
        self._exit_review()
        self.engine.send("restart")

    def _review_step(self) -> None:
        """Playback through saved frames at the selected speed (any speed: nothing is rendered by the game)."""
        if self._review_play is None or self.view_tick is None or self._closing:
            return
        t0, start = self._review_play
        snap = self.engine.snapshot()
        live = snap["live_tick"]
        target = start + int((time.perf_counter() - t0) * 60.0 * self.engine.speed)
        if target >= live:  # caught up: continue with the live game
            self._exit_review()
            if snap["phase"] == "paused":
                self.engine.send("play")
            return
        if target != self.view_tick:
            if self.history is not None and target in self.history:
                self.view_tick = target
                self._refresh()
            else:
                self._review_play = None
                self._note = f"no saved frame for tick {target}: press Right or Jump"
                return
        self.root.after(REVIEW_PLAY_MS, self._review_step)

    # -- actions ------------------------------------------------------------------------------------------

    def _set_speed(self, v: float) -> None:
        self.engine.send("speed", v)
        self.speed.current(SPEEDS.index(v))
        if self._review_play is not None and self.view_tick is not None:  # keep the position, change the pace
            self._review_play = (time.perf_counter(), self.view_tick)
        self.root.focus_set()

    def _bump_speed(self, delta: int) -> None:
        i = SPEEDS.index(self.engine.speed) if self.engine.speed in SPEEDS else 2
        self._set_speed(SPEEDS[max(0, min(len(SPEEDS) - 1, i + delta))])

    def _focus_jump(self) -> None:
        self.jump_entry.focus_set()
        self.jump_entry.select_range(0, "end")

    def _jump_from_entry(self, _event=None) -> None:
        text = self.jump_entry.get().strip()
        try:
            tick = int(text)
        except ValueError:
            self._note = f"jump: '{text}' is not a tick number"
            return
        self.jump(tick)
        self.root.focus_set()

    def _seek_release(self, _event) -> None:
        self._seeking = False
        self.jump(int(self.seek.get()))

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        try:
            save_state({"panel_geometry": self.root.geometry()})
        except OSError:
            pass
        self.engine.send("quit")
        self.root.after(50, self.root.destroy)

    # -- polling ------------------------------------------------------------------------------------------

    def run(self) -> None:
        self.root.after(POLL_MS, self._poll)
        self.root.mainloop()

    def _poll(self) -> None:
        if self._closing:
            return
        snap = self.engine.snapshot()
        if self.view_tick is not None and self._busy(snap):  # a rebuild / fast-forward replaces the review
            self._exit_review()
        if self._pending_back and snap["phase"] in ("paused", "ended", "error"):
            self._pending_back = False
            self.step_back()
            snap = self.engine.snapshot()
        view = self._view(snap)
        self._update_panel(snap, view)
        self._update_overlays(snap, view)
        self._game_hotkeys()
        self._draw_markers()
        if snap["phase"] == "ended" and not self._end_seen:
            self._end_seen = True
            if self.exit_at_end:
                self.root.after(1500, self.close)
        elif snap["phase"] != "ended" and self._end_seen:
            self._end_seen = False
        if self._update_result(snap) and snap["error"] and self.exit_at_end:  # BattleShip stopped
            self.root.after(1500, self.close)
        if self.engine.finished.is_set():
            if self.exit_at_end or not snap["error"]:
                self.close()
                return
        self.root.after(POLL_MS, self._poll)

    def _view(self, snap: Dict[str, Any]) -> Dict[str, Any]:
        """What the HUD and panel describe: the saved frame on screen, or the live game."""
        frame = self.history.get(self.view_tick) if (self.history is not None and self.view_tick is not None) else None
        if self.view_tick is not None and frame is None:  # evicted meanwhile: back to live
            self._exit_review()
        if frame is not None:
            playing = self._review_play is not None
            return {"review": True, "frame": frame, "tick": frame.tick, "live_tick": snap["live_tick"],
                    "row": frame.row, "observation": frame.observation, "targets_broken": frame.targets_broken,
                    "targets_total": snap["targets_total"], "rows": snap["rows"],
                    "status": (f"▶ saved frames {speed_label(self.engine.speed).split(' ')[0]}" if playing
                               else "◀ saved frame (game paused)"),
                    "status_color": CYAN}
        row = snap["last_row"]
        return {"review": False, "frame": None, "tick": row.sequence_index if row is not None else -1,
                "live_tick": snap["live_tick"], "row": row, "observation": snap["observation"],
                "targets_broken": snap["targets_broken"], "targets_total": snap["targets_total"], "rows": snap["rows"],
                "status": status_text(snap, verdict=True), "status_color": status_color(snap)}

    def _update_panel(self, snap: Dict[str, Any], view: Dict[str, Any]) -> None:
        if view["review"]:
            how = (f"playing saved frames at {speed_label(self.engine.speed).split(' ')[0]}"
                   if self._review_play is not None else "game paused")
            self.status.set(f"◀ SAVED FRAME {tick_label(view['tick'])} — live game at "
                            f"{tick_label(view['live_tick'])} ({how})")
            self.status_label.configure(fg=DARK_CYAN)
        else:
            self.status.set(status_text(snap))
            fg = DARK_AMBER if snap.get("rebuilding") else DARK_RED if snap["phase"] == "error" else INK
            self.status_label.configure(fg=fg)
        tick_color = DARK_CYAN if view["review"] else INK
        for key, text in live_columns(view).items():
            cell = self.cells[key]
            if cell.cget("text") != text:
                cell.configure(text=text)
        if self.cells["tick"].cget("fg") != tick_color:
            self.cells["tick"].configure(fg=tick_color)
        self.message.set(self._note or snap["message"])
        text, bg = verdict_badge(snap)
        if self.badge.cget("text") != text:
            self.badge.configure(text=text, bg=bg)
        self.diag.set(self._diag_text())
        playing = snap["phase"] == "playing" or self._review_play is not None
        self.play_btn.configure(text="❚❚" if playing else "▶")
        if not self._seeking:
            self.seek.set(max(view["tick"], 0))

    def _diag_text(self) -> str:
        """Footer diagnostics: saved frames, memory, capture cost, markers."""
        h = self.history
        if h is None:
            parts = ["saved frames off (--history-seconds 0)"]
        else:
            cfg = self.engine.history_config
            span = h.span()
            cost = sorted(self.engine.capture_ms)
            parts = [f"saved frames {len(h)}/{h.capacity}", f"{h.nbytes / 1e6:.0f} MB", f"1/{cfg.scale} res",
                     f"ticks {span[0] if span[0] >= 0 else 'tick-0 state'}..{span[1]}" if span else "none yet"]
            if cost:
                parts.append(f"capture {cost[len(cost) // 2]:.1f} ms/frame")
        p = self.prepass
        if p is not None:
            parts.append({"running": "target markers: headless pre-pass running",
                          "done": f"{len(p.break_ticks)} target markers (pre-pass {p.seconds or 0:.1f} s)",
                          "failed": f"no target markers ({p.error})", "cancelled": "target markers cancelled"}
                         .get(p.state, p.state))
        return " · ".join(parts)

    def _update_result(self, snap: Dict[str, Any]) -> bool:
        """Refresh the one-line result (and the check list) when the verdict, the error or the first mismatch
        changes. Opens the list on DESYNC and on an error. True when something changed."""
        key = (id(snap.get("verdict_detail")), snap.get("error"), snap.get("mismatch"))
        if key == self._result_key:
            return False
        self._result_key = key
        text, color, has_details = result_summary(snap)
        self._result_has_details = has_details
        t = self.result
        t.configure(state="normal")
        t.delete("1.0", "end")
        lines = result_details(snap)
        self._copy_lines = [copy for _, _, copy in lines]
        for i, (line, tag, _) in enumerate(lines):
            t.insert("end", line + ("\n" if i < len(lines) - 1 else ""), tag)
        t.configure(state="disabled",
                    height=max(1, min(24, sum(1 + len(line) // RESULT_WIDTH for line, _, _ in lines))))
        desync = snap.get("error") or (snap.get("verdict") == "DESYNC")
        self._set_result_open(bool(desync) or (self._result_open and has_details), text, color)
        return True

    def _toggle_result(self) -> None:
        if self._result_has_details:
            text, color, _ = result_summary(self.engine.snapshot())
            self._set_result_open(not self._result_open, text, color)

    def _set_result_open(self, open_: bool, text: str, color: str) -> None:
        open_ = open_ and self._result_has_details
        if self._result_has_details:
            text = ("▾ " if open_ else "▸ ") + text + ("" if open_ else "   (click for every check)")
        self.result_line.configure(text=text, fg=color, cursor="hand2" if self._result_has_details else "arrow")
        self._result_open = open_
        packed = bool(self.result.winfo_manager())
        if open_ and not packed:
            self.result.pack(fill="x", padx=10, pady=(0, 6), after=self.result_line)
        elif packed and not open_:
            self.result.pack_forget()
        else:
            return
        self._fit_height()

    def _fit_height(self) -> None:
        """Let the window take the height of its content (the user's width is kept)."""
        root = self.root
        width = root.winfo_width()
        root.geometry("")
        root.update_idletasks()
        if width > root.winfo_reqwidth():
            root.geometry(f"{width}x{root.winfo_reqheight()}")

    def _open_folder(self) -> None:
        directory = self.summary["directory"]
        try:
            if hasattr(os, "startfile"):
                os.startfile(directory)  # Explorer (Windows)
            else:
                subprocess.Popen(["xdg-open", directory])
        except OSError as exc:
            self._note = f"could not open the folder: {exc}"

    def _fit_path(self, width: Optional[int] = None) -> None:
        width = self.path_label.winfo_width() if width is None else width
        text = middle_ellipsis(self.path_text, width - 6, self._path_font.measure)
        if self.path_label.cget("text") != text:
            self.path_label.configure(text=text)

    def _copy_path(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self.summary["directory"])
        self._note = "full path copied"

    def _result_copy_text(self, selected: bool = True) -> str:
        """Full-precision text of the check-list lines the selection touches (every line when selected=False)."""
        lines = self._copy_lines
        if selected:
            sel = self.result.tag_ranges("sel")
            if not sel:
                return ""
            first, end = str(sel[0]), str(sel[-1])
            a, b = int(first.split(".")[0]), int(end.split(".")[0])
            if end.endswith(".0") and b > a:  # the selection stops at the start of line b: b is not included
                b -= 1
            lines = lines[a - 1:b]
        return "\n".join(lines)

    def _copy_result(self, selected: bool = True) -> str:
        text = self._result_copy_text(selected)
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        return "break"  # never Tk's own copy, which would take the rounded text

    def _marker_enter(self, tick: int, first: int, last: int, x_root: int, y_root: int) -> None:
        self._marker_leave()
        what = f"Target {first}" if first == last else f"Targets {first}-{last}"
        self._marker_tip = popup_tip(self.markers, f"{what} broken at tick {tick}\nclick to jump there",
                                     x_root + 12, y_root + 14)
        self.markers.configure(cursor="hand2")

    def _marker_leave(self) -> None:
        if self._marker_tip is not None:
            self._marker_tip.destroy()
            self._marker_tip = None
        self.markers.configure(cursor="")

    def _marker_click(self, tick: int) -> None:
        self._marker_leave()
        self.jump(tick)

    def _draw_markers(self, force: bool = False) -> None:
        """Target-break markers under the timeline, aligned with the slider: a tooltip names the target and the
        tick, a click jumps there."""
        p = self.prepass
        ticks = tuple(p.break_ticks) if (p is not None and p.state == "done") else ()
        key = (ticks, self.seek.winfo_width(), self.markers.winfo_width())
        if not force and key == self._markers_drawn:
            return
        self._markers_drawn = key
        self._marker_leave()
        c = self.markers
        c.delete("all")
        if not ticks or self.last_tick <= 0:
            return
        dx = self.seek.winfo_rootx() - c.winfo_rootx()
        for tick, first, last in marker_groups(list(ticks)):
            x = self.seek.coords(tick)[0] + dx
            label = str(first) if first == last else f"{first}-{last}"
            tag = f"m{tick}"
            c.create_polygon(x, 1, x - 6, 9, x + 6, 9, fill=MARKER, outline="", tags=tag)
            c.create_text(x, 9, text=label, anchor="n", fill=MARKER, font=("Segoe UI", 7, "bold"), tags=tag)
            c.tag_bind(tag, "<Button-1>", lambda e, t=tick: self._marker_click(t))
            c.tag_bind(tag, "<Enter>", lambda e, t=tick, f=first, la=last: self._marker_enter(t, f, la, e.x_root,
                                                                                              e.y_root))
            c.tag_bind(tag, "<Leave>", lambda e: self._marker_leave())

    def _update_overlays(self, snap: Dict[str, Any], view: Dict[str, Any]) -> None:
        game = self.engine.game_window()
        if not self._panel_placed and game:
            rect = win32.client_rect_on_screen(game)
            if rect:
                x = min(rect[0] + rect[2] + 16, max(0, self.root.winfo_screenwidth() - self.root.winfo_width() - 8))
                self.root.geometry(f"+{x}+{max(0, rect[1] - 30)}")
                self._panel_placed = True
        rect = win32.client_rect_on_screen(game) if game else None
        fg = win32.foreground_root()
        ours = {game, win32.root_of(self.root.winfo_id()), self.review.hwnd}
        if self.hud is not None:
            self.hud.ensure_click_through()
            ours.add(self.hud.hwnd)
        # The overlays are topmost: hide them only while another application's focused window overlaps the game
        # window (focus on another monitor keeps them visible).
        covered = (fg is not None and fg not in ours and not win32.is_shell_window(fg)
                   and win32.rects_intersect(win32.window_rect(fg), win32.window_rect(game)))
        hidden = rect is None or win32.is_minimized(game) or covered
        raise_hud = False
        if view["review"] and not hidden:
            raise_hud = self.review.show(view["frame"], rect)
        else:
            self.review.hide()
        if self.hud is None:
            return
        if hidden:
            self.hud.hide()
            return
        self.hud.draw(view)
        self.hud.show(rect[0] + 6, rect[1] + 6)
        if raise_hud:
            self.hud.raise_above()

    def _refresh(self) -> None:
        """Redraw panel and overlays now (saved-frame playback does not wait for the next poll)."""
        snap = self.engine.snapshot()
        view = self._view(snap)
        self._update_panel(snap, view)
        self._update_overlays(snap, view)

    def _game_hotkeys(self) -> None:
        """Hotkeys while the GAME window has focus (tk never sees those key events)."""
        game = self.engine.game_window()
        if not game or win32.foreground_root() != game:
            self._keys_prev.clear()
            return
        now = time.monotonic()
        for name, action in (("space", "toggle"), ("right", "fwd"), ("period", "fwd"), ("left", "back"),
                             ("comma", "back"), ("plus", "+"), ("add", "+"), ("minus", "-"), ("subtract", "-")):
            down = win32.key_down(name)
            was = self._keys_prev.get(name, False)
            self._keys_prev[name] = down
            fire = down and not was
            if down and was and action in ("fwd", "back") and now >= self._repeat_at.get(name, 0.0):
                fire = True  # held: repeat
            if not fire:
                continue
            if action in ("fwd", "back"):
                self._repeat_at[name] = now + (0.35 if not was else 0.05)
                (self.step_forward if action == "fwd" else self.step_back)()
            elif action == "toggle":
                self.toggle()
            else:
                self._bump_speed(+1 if action == "+" else -1)
