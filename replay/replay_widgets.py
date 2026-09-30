#!/usr/bin/env python3
"""Small Tk pieces shared by the viewer panel (replay_ui.py) and the browser (replay_browser.py): colors and fonts,
tooltips, and text shortening that keeps what matters visible."""

from __future__ import annotations

import os
import tkinter as tk
from typing import Callable

# Light panel palette.
INK = "#111827"
GREY_TEXT = "#6b7280"
DARK_GREEN, DARK_RED, DARK_AMBER, DARK_CYAN = "#15803d", "#b91c1c", "#b45309", "#0e7490"
UI_FONT = ("Segoe UI", 9)
SMALL = ("Segoe UI", 8)
HEAD_FONT = ("Segoe UI", 11, "bold")


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
        if self.tip is not None or not self.text:
            return
        self.tip = popup_tip(self.widget, self.text, self.widget.winfo_rootx(),
                             self.widget.winfo_rooty() + self.widget.winfo_height() + 2)

    def hide(self, _event=None) -> None:
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None


def middle_ellipsis(text: str, max_px: int, measure: Callable[[str], int], sep: str = os.sep) -> str:
    """`text` if it fits in max_px pixels, else head + '…' + tail: the tail always keeps the last path component
    (e.g. the episode folder), the head is as long as still fits."""
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


def end_ellipsis(text: str, max_px: int, measure: Callable[[str], int]) -> str:
    """`text` cut at the end with '…' so it fits in max_px pixels."""
    if measure(text) <= max_px:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if measure(text[:mid] + "…") <= max_px:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + "…" if lo else ""
