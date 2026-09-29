#!/usr/bin/env python3
"""Tk control panel and HUD overlay for the replay viewer (standard library only).

The game renders in its own window; the viewer never draws into it. The HUD
is a separate borderless, click-through, color-keyed tk window kept on top of
the game window's client area (tick, stick direction, button, targets broken,
playback state). The control panel is an ordinary tk window. All game control
goes through ReplayEngine commands; the UI only reads engine snapshots.
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

POLL_MS = 33
HUD_KEY = "#010101"  # color key: pixels of exactly this color are transparent
HUD_W, HUD_H = 330, 118
FONT = ("Consolas", 11)
FONT_BIG = ("Consolas", 12, "bold")
GREEN, RED, AMBER, WHITE = "#4ade80", "#f87171", "#fbbf24", "#f5f5f5"


def speed_label(v: float) -> str:
    return f"{v:g}x" + (" (capped at 1x)" if v > MAX_RENDERED_SPEED else "")


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

    def hide(self) -> None:
        if self.visible:
            self.win.withdraw()
            self.visible = False

    def _text(self, x: int, y: int, text: str, color: str = WHITE, font=FONT) -> None:
        for dx, dy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            self.canvas.create_text(x + dx, y + dy, text=text, fill="#000000", anchor="nw", font=font)
        self.canvas.create_text(x, y, text=text, fill=color, anchor="nw", font=font)

    def draw(self, snap: Dict[str, Any]) -> None:
        c = self.canvas
        c.delete("all")
        row = snap["last_row"]
        obs = snap["observation"]
        tick = f"tick {row.sequence_index}" if row is not None else "tick - (tick-0 state)"
        self._text(8, 4, f"{tick}  / {snap['rows'] - 1}", font=FONT_BIG)
        if row is not None:
            arrow = stick_arrow(row.stick_x, row.stick_y)
            self._text(8, 26, f"stick {arrow} ({row.stick_x:+d},{row.stick_y:+d})")
            self._text(8, 46, f"button {button_name(row.buttons)}",
                       AMBER if row.buttons else WHITE)
        else:
            self._text(8, 26, "stick -")
            self._text(8, 46, "button -")
        tb, tt = snap["targets_broken"], snap["targets_total"]
        self._text(8, 66, f"targets {tb if tb is not None else '-'}/{tt}")
        self._text(8, 90, status_text(snap), status_color(snap))
        # stick diagram
        cx, cy, r = HUD_W - 40, 44, 26
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
            self._text(HUD_W - 118, 76, f"x {obs.get('position_x', 0):8.1f}")
            self._text(HUD_W - 118, 94, f"y {obs.get('position_y', 0):8.1f}")


def status_text(snap: Dict[str, Any]) -> str:
    phase = snap["phase"]
    if phase == "playing":
        tps = snap["achieved_tps"]
        rate = f" {tps:4.1f} ticks/s" if tps else ""
        return f"▶ {speed_label(snap['speed'])}{rate}"
    if phase == "paused":
        return "❚❚ paused"
    if phase == "jumping":
        return f"» jump to tick {snap['jump_to'] - 1}"
    if phase == "booting":
        return "starting BattleShip..."
    if phase == "ended":
        v = snap["verdict"] or "?"
        return f"■ end {snap['end_kind']} - {v}"
    if phase == "error":
        return "BattleShip stopped - press Restart"
    return phase


def status_color(snap: Dict[str, Any]) -> str:
    if snap["phase"] == "ended":
        return GREEN if snap["verdict"] == "MATCH" else RED
    if snap["phase"] == "error" or snap["mismatch"]:
        return RED
    return WHITE


class ViewerUI:
    def __init__(self, engine: ReplayEngine, *, summary: Dict[str, Any], hud: bool = True, exit_at_end: bool = False):
        self.engine = engine
        self.summary = summary
        self.exit_at_end = exit_at_end
        self.root = tk.Tk()
        self.root.title(f"Replay - {summary['episode_id']}")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.hud = Hud(self.root) if hud else None
        self._closing = False
        self._end_seen = False
        self._last_error: Optional[str] = None
        self._seeking = False
        self._panel_placed = False
        self._keys_prev: Dict[str, bool] = {}
        self._repeat_at = 0.0
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
        root.minsize(560, 420)
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
        ttk.Label(now, textvariable=self.status, font=FONT_BIG).pack(anchor="w", padx=6)
        ttk.Label(now, textvariable=self.detail, font=FONT).pack(anchor="w", padx=6)
        self.seek = tk.Scale(now, from_=0, to=max(0, len(self.engine.rows) - 1), orient="horizontal",
                             showvalue=True, resolution=1, length=520, takefocus=0)
        self.seek.pack(fill="x", padx=6)
        self.seek.bind("<ButtonPress-1>", lambda e: setattr(self, "_seeking", True))
        self.seek.bind("<ButtonRelease-1>", self._seek_release)

        bar = ttk.Frame(root)
        bar.pack(fill="x", **pad)
        ttk.Button(bar, text="Restart (R)", takefocus=False, command=lambda: self.engine.send("restart")).pack(side="left")
        self.play_btn = ttk.Button(bar, text="Play (Space)", width=13, takefocus=False,
                                   command=lambda: self.engine.send("toggle"))
        self.play_btn.pack(side="left", padx=4)
        ttk.Button(bar, text="Step (→)", takefocus=False, command=lambda: self.engine.send("step")).pack(side="left")
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
        self.result = tk.Text(res, height=11, font=FONT, wrap="word", state="disabled")
        self.result.tag_configure("match", foreground="#15803d", font=FONT_BIG)
        self.result.tag_configure("desync", foreground="#b91c1c", font=FONT_BIG)
        self.result.pack(fill="both", expand=True, padx=4, pady=4)
        ttk.Label(root, text="Keys: Space play/pause, → or . step, + / - speed, R restart, G jump, Q quit. "
                             "Don't use other keys in the game window.", font=("Segoe UI", 8)).pack(anchor="w", padx=8)

        for seq, fn in (("<space>", lambda e: self.engine.send("toggle")),
                        ("<Right>", lambda e: self.engine.send("step")),
                        ("<period>", lambda e: self.engine.send("step")),
                        ("<plus>", lambda e: self._bump_speed(+1)), ("<equal>", lambda e: self._bump_speed(+1)),
                        ("<KP_Add>", lambda e: self._bump_speed(+1)),
                        ("<minus>", lambda e: self._bump_speed(-1)), ("<KP_Subtract>", lambda e: self._bump_speed(-1)),
                        ("r", lambda e: self.engine.send("restart")), ("R", lambda e: self.engine.send("restart")),
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

    # -- actions ------------------------------------------------------------------------------------------

    def _set_speed(self, v: float) -> None:
        self.engine.send("speed", v)
        self.speed.current(SPEEDS.index(v))
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
            self.detail.set(f"jump: '{text}' is not a tick number")
            return
        self.engine.send("jump", tick)
        self.root.focus_set()

    def _seek_release(self, _event) -> None:
        self._seeking = False
        self.engine.send("jump", int(self.seek.get()))

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
        self._update_panel(snap)
        self._update_hud(snap)
        self._game_hotkeys(snap)
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

    def _update_panel(self, snap: Dict[str, Any]) -> None:
        row = snap["last_row"]
        tick = row.sequence_index if row is not None else None
        self.status.set(f"{'tick ' + str(tick) if tick is not None else 'tick-0 state'}  of {snap['rows'] - 1}"
                        f"   |   {status_text(snap)}")
        obs = snap["observation"]
        parts = []
        if row is not None:
            parts.append(f"stick {stick_arrow(row.stick_x, row.stick_y)} ({row.stick_x:+d},{row.stick_y:+d})  "
                         f"button {button_name(row.buttons)}")
        tb = snap["targets_broken"]
        parts.append(f"targets {tb if tb is not None else '-'}/{snap['targets_total']}")
        if obs:
            parts.append(f"x {obs.get('position_x', 0):.1f} y {obs.get('position_y', 0):.1f} "
                         f"status {obs.get('fighter_status_id')} t={obs.get('time_passed')}")
        msg = snap["error"] or snap["message"]
        self.detail.set("   ".join(parts) + (f"\n{msg}" if msg else ""))
        self.play_btn.configure(text="Pause (Space)" if snap["phase"] == "playing" else "Play (Space)")
        if not self._seeking:
            self.seek.set(tick if tick is not None else 0)

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

    def _update_hud(self, snap: Dict[str, Any]) -> None:
        hud = self.hud
        game = self.engine.game_window()
        if not self._panel_placed and game:
            rect = win32.client_rect_on_screen(game)
            if rect:
                x = min(rect[0] + rect[2] + 16, max(0, self.root.winfo_screenwidth() - 640))
                self.root.geometry(f"+{x}+{max(0, rect[1] - 30)}")
                self._panel_placed = True
        if hud is None:
            return
        hud.ensure_click_through()
        rect = win32.client_rect_on_screen(game) if game else None
        fg = win32.foreground_root()
        ours = {game, win32.root_of(self.root.winfo_id()), hud.hwnd}
        # The HUD is topmost: hide it only while another application's focused window overlaps the game window
        # (focus on another monitor keeps it visible).
        covered = (fg is not None and fg not in ours and not win32.is_shell_window(fg)
                   and win32.rects_intersect(win32.window_rect(fg), win32.window_rect(game)))
        if rect is None or win32.is_minimized(game) or covered:
            hud.hide()
            return
        hud.draw(snap)
        hud.show(rect[0] + 6, rect[1] + 6)

    def _game_hotkeys(self, snap: Dict[str, Any]) -> None:
        """Hotkeys while the GAME window has focus (tk never sees those key events)."""
        game = self.engine.game_window()
        if not game or win32.foreground_root() != game:
            self._keys_prev.clear()
            return
        now = time.monotonic()
        for name, action in (("space", "toggle"), ("right", "step"), ("period", "step"),
                             ("plus", "+"), ("add", "+"), ("minus", "-"), ("subtract", "-")):
            down = win32.key_down(name)
            was = self._keys_prev.get(name, False)
            self._keys_prev[name] = down
            fire = down and not was
            if down and was and action == "step" and now >= self._repeat_at:
                fire = True
            if not fire:
                continue
            if action == "step":
                self._repeat_at = now + (0.35 if not was else 0.05)
                self.engine.send("step")
            elif action == "toggle":
                self.engine.send("toggle")
            else:
                self._bump_speed(+1 if action == "+" else -1)
