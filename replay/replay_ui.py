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
"""

from __future__ import annotations

import math
import time
import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, Optional

import replay_win32 as win32
from replay_episode import button_name, stick_arrow
from replay_game import SPEEDS, MAX_RENDERED_SPEED, ReplayEngine, load_state, save_state
from replay_history import SavedFrame, plan_back, plan_forward, plan_view, ppm

POLL_MS = 33
REVIEW_PLAY_MS = 8
HUD_KEY = "#010101"  # color key: pixels of exactly this color are transparent
HUD_W, HUD_H = 330, 146
FONT = ("Consolas", 11)
FONT_BIG = ("Consolas", 12, "bold")
GREEN, RED, AMBER, WHITE, CYAN = "#4ade80", "#f87171", "#fbbf24", "#f5f5f5", "#22d3ee"
REVIEW_BANNER_BG = "#0e4a5a"


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
        self._text(8, y0 + 86, view["status"], view["status_color"])
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


def status_text(snap: Dict[str, Any]) -> str:
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
        v = snap["verdict"] or "?"
        return f"■ end {snap['end_kind']} - {v}"
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


class ViewerUI:
    def __init__(self, engine: ReplayEngine, *, summary: Dict[str, Any], hud: bool = True, exit_at_end: bool = False):
        self.engine = engine
        self.history = engine.history
        self.last_tick = len(engine.rows) - 1
        self.summary = summary
        self.exit_at_end = exit_at_end
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
        self._last_error: Optional[str] = None
        self._seeking = False
        self._panel_placed = False
        self._keys_prev: Dict[str, bool] = {}
        self._repeat_at: Dict[str, float] = {}
        self._build()
        saved = load_state().get("panel_geometry")
        if isinstance(saved, str):
            try:
                self.root.geometry(saved)
                self._panel_placed = True
            except tk.TclError:
                pass

    # -- layout -----------------------------------------------------------------------------------------

    def _build(self) -> None:
        s = self.summary
        root = self.root
        root.minsize(600, 440)
        pad = {"padx": 8, "pady": 3}
        info = ttk.LabelFrame(root, text="Recorded episode")
        info.pack(fill="x", **pad)
        lines = [
            s["episode_id"],
            f"role {s['role']}   run {s['run_id']}   profile {s['profile']}",
            f"observation {s['observation']}   reward {s['reward']}",
            f"end {s['end']} ({s['end_detail']})   targets {s['targets_broken']}   rows {s['rows']}"
            + (f"   prefix {s['prefix_rows']}" if s["prefix_rows"] else ""),
        ]
        for i, text in enumerate(lines):
            ttk.Label(info, text=text, font=FONT_BIG if i == 0 else None).pack(anchor="w", padx=6)
        path = ttk.Entry(info)
        path.insert(0, s["directory"])
        path.configure(state="readonly")
        path.pack(fill="x", padx=6, pady=(2, 6))

        now = ttk.LabelFrame(root, text="Replay")
        now.pack(fill="x", **pad)
        self.status = tk.StringVar(value="starting...")
        self.detail = tk.StringVar(value="")
        self.history_line = tk.StringVar(value="")
        self.status_label = tk.Label(now, textvariable=self.status, font=FONT_BIG, anchor="w")
        self.status_label.pack(fill="x", padx=6)
        ttk.Label(now, textvariable=self.detail, font=FONT).pack(anchor="w", padx=6)
        ttk.Label(now, textvariable=self.history_line, font=("Segoe UI", 8)).pack(anchor="w", padx=6)
        self.seek = tk.Scale(now, from_=0, to=max(0, self.last_tick), orient="horizontal",
                             showvalue=True, resolution=1, length=520, takefocus=0)
        self.seek.pack(fill="x", padx=6)
        self.seek.bind("<ButtonPress-1>", lambda e: setattr(self, "_seeking", True))
        self.seek.bind("<ButtonRelease-1>", self._seek_release)

        bar = ttk.Frame(root)
        bar.pack(fill="x", **pad)
        ttk.Button(bar, text="Restart (R)", takefocus=False, command=self.restart).pack(side="left")
        ttk.Button(bar, text="◀ Back (←)", takefocus=False, command=self.step_back).pack(side="left", padx=(4, 0))
        self.play_btn = ttk.Button(bar, text="Play (Space)", width=13, takefocus=False, command=self.toggle)
        self.play_btn.pack(side="left", padx=4)
        ttk.Button(bar, text="Step (→)", takefocus=False, command=self.step_forward).pack(side="left")
        ttk.Label(bar, text="  speed").pack(side="left")
        self.speed = ttk.Combobox(bar, width=16, state="readonly", takefocus=False, values=[speed_label(v) for v in SPEEDS])
        self.speed.current(SPEEDS.index(self.engine.speed) if self.engine.speed in SPEEDS else 2)
        self.speed.bind("<<ComboboxSelected>>", lambda e: self._set_speed(SPEEDS[self.speed.current()]))
        self.speed.pack(side="left", padx=4)
        ttk.Label(bar, text="  tick").pack(side="left")
        self.jump_entry = ttk.Entry(bar, width=7)
        self.jump_entry.pack(side="left", padx=2)
        self.jump_entry.bind("<Return>", self._jump_from_entry)
        ttk.Button(bar, text="Jump (G)", takefocus=False, command=self._jump_from_entry).pack(side="left")

        res = ttk.LabelFrame(root, text="Result (replayed vs metadata.json)")
        res.pack(fill="both", expand=True, **pad)
        self.result = tk.Text(res, height=10, font=FONT, wrap="word", state="disabled")
        self.result.tag_configure("match", foreground="#15803d", font=FONT_BIG)
        self.result.tag_configure("desync", foreground="#b91c1c", font=FONT_BIG)
        self.result.pack(fill="both", expand=True, padx=4, pady=4)
        ttk.Label(root, text="Keys: Space play/pause, ← or , back, → or . step, + / - speed, R restart, "
                             "G jump, Q quit. Don't use other keys in the game window.",
                  font=("Segoe UI", 8)).pack(anchor="w", padx=8)

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
        if snap["phase"] == "ended" and not self._end_seen:
            self._end_seen = True
            self._show_result(snap)
            if self.exit_at_end:
                self.root.after(1500, self.close)
        elif snap["phase"] != "ended" and self._end_seen:
            self._end_seen = False
            self._show_result(snap)
        if snap["error"] != self._last_error:  # BattleShip stopped (or a restart cleared the error)
            self._last_error = snap["error"]
            self._show_result(snap)
            if snap["error"] and self.exit_at_end:
                self.root.after(1500, self.close)
        if self.engine.finished.is_set():
            if snap["error"]:
                self._show_result(snap)
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
                "status": status_text(snap), "status_color": status_color(snap)}

    def _update_panel(self, snap: Dict[str, Any], view: Dict[str, Any]) -> None:
        if view["review"]:
            self.status.set(f"SAVED FRAME {tick_label(view['tick'])}  (live game at {tick_label(view['live_tick'])})"
                            f"   |   {view['status']}")
            self.status_label.configure(fg="#0e7490")
        else:
            self.status.set(f"{tick_label(view['tick'])}  of {snap['rows'] - 1}   |   {view['status']}")
            self.status_label.configure(fg="#b45309" if snap.get("rebuilding") else "#000000")
        row, obs = view["row"], view["observation"]
        parts = []
        if row is not None:
            parts.append(f"stick {stick_arrow(row.stick_x, row.stick_y)} ({row.stick_x:+d},{row.stick_y:+d})  "
                         f"button {button_name(row.buttons)}")
        tb = view["targets_broken"]
        parts.append(f"targets {tb if tb is not None else '-'}/{view['targets_total']}")
        if obs:
            parts.append(f"x {obs.get('position_x', 0):.1f} y {obs.get('position_y', 0):.1f} "
                         f"status {obs.get('fighter_status_id')} t={obs.get('time_passed')}")
        msg = self._note or snap["error"] or snap["message"]
        self.detail.set("   ".join(parts) + (f"\n{msg}" if msg else ""))
        self.history_line.set(self._history_text())
        playing = snap["phase"] == "playing" or self._review_play is not None
        self.play_btn.configure(text="Pause (Space)" if playing else "Play (Space)")
        if not self._seeking:
            self.seek.set(max(view["tick"], 0))

    def _history_text(self) -> str:
        h = self.history
        if h is None:
            return "saved frames: off (--history-seconds 0)"
        cfg = self.engine.history_config
        span = h.span()
        cost = sorted(self.engine.capture_ms)
        median = f", capture {cost[len(cost) // 2]:.1f} ms/frame" if cost else ""
        where = f"ticks {tick_label(span[0])}..{span[1]}" if span else "none yet"
        return (f"saved frames: {len(h)}/{h.capacity} ({h.nbytes / 1e6:.0f} MB, 1/{cfg.scale} resolution), "
                f"{where}{median}")

    def _show_result(self, snap: Dict[str, Any]) -> None:
        t = self.result
        t.configure(state="normal")
        t.delete("1.0", "end")
        if snap["error"]:
            t.insert("end", "ERROR\n", "desync")
            t.insert("end", snap["error"] + "\n")
        elif snap["verdict"]:
            t.insert("end", f"{snap['verdict']}\n", "match" if snap["verdict"] == "MATCH" else "desync")
            t.insert("end", "\n".join(snap["verdict_lines"]) + "\n")
        t.configure(state="disabled")

    def _update_overlays(self, snap: Dict[str, Any], view: Dict[str, Any]) -> None:
        game = self.engine.game_window()
        if not self._panel_placed and game:
            rect = win32.client_rect_on_screen(game)
            if rect:
                x = min(rect[0] + rect[2] + 16, max(0, self.root.winfo_screenwidth() - 660))
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
