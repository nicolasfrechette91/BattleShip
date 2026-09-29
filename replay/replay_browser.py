#!/usr/bin/env python3
"""Tk table browser over the replay index (started by `replay_index.py gui`).

Filter, sort by clicking a column heading, double-click (or Enter / Play) to
open the episode in the viewer (through replay_open.pyw, so start-up errors
appear as a message box), Check for a headless MATCH/DESYNC replay. Reads the
index only; Rescan runs the same incremental read-only scan as
`replay_index.py scan`. replay_gui.pyw starts it without a console.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Dict, List, Optional

from pathlib import Path

from replay_index import REPO_ROOT, SORT_KEYS, VIEWER, left_text, tri

OPENER = Path(__file__).resolve().with_name("replay_open.pyw")
MAX_ROWS = 5000
COLUMNS = (
    ("targets", "tgt", 44, "targets"), ("end", "end", 70, "end"), ("tick", "tick", 56, "last_tick"),
    ("left", "left", 80, "left"), ("cross", "cross", 50, "crossing"), ("replay", "replay", 62, None),
    ("role", "role", 76, None), ("milestone", "milestone", 70, "milestone"), ("run", "run", 280, None),
    ("worker", "wkr", 40, None), ("episode", "episode", 250, None), ("created", "created", 150, "created"),
)


def main(load_rows: Callable[[], List[Dict[str, Any]]], scan: Callable[..., Dict[str, Any]]) -> int:
    app = Browser(load_rows, scan)
    app.root.mainloop()
    return 0


class Browser:
    def __init__(self, load_rows, scan):
        self.load_rows_fn, self.scan_fn = load_rows, scan
        self.rows: List[Dict[str, Any]] = []
        self.view: List[Dict[str, Any]] = []
        self.sort_key, self.sort_desc = "targets", True
        self.children: List[subprocess.Popen] = []
        self._scanning = False
        self.root = tk.Tk()
        self.root.title("Replay browser - runs/")
        self.root.geometry("1400x760")
        self._build()
        self.reload()

    # -- layout ---------------------------------------------------------------------------------------------------

    def _build(self) -> None:
        f = ttk.Frame(self.root)
        f.pack(fill="x", padx=8, pady=6)
        self.vars: Dict[str, tk.StringVar] = {}

        def combo(label, name, values, width=11):
            ttk.Label(f, text=label).pack(side="left")
            v = tk.StringVar(value=values[0])
            cb = ttk.Combobox(f, textvariable=v, values=values, width=width, state="readonly")
            cb.pack(side="left", padx=(2, 10))
            cb.bind("<<ComboboxSelected>>", lambda e: self.apply())
            self.vars[name] = v
            return cb

        self.milestone_cb = combo("milestone", "milestone", ["any"], 12)
        combo("role", "role", ["any", "training", "evaluation"])
        combo("end", "end", ["any", "clear", "fall", "truncated"], 9)
        combo("min targets", "min_targets", ["any"] + [str(i) for i in range(11)], 5)
        combo("left entry", "left", ["any", "yes", "no", "?"], 5)
        combo("crossing", "crossing", ["any", "yes", "no", "?"], 5)
        combo("replay", "replay", ["any", "MATCH", "DESYNC", "none"], 8)
        ttk.Label(f, text="text").pack(side="left")
        self.vars["text"] = tk.StringVar()
        e = ttk.Entry(f, textvariable=self.vars["text"], width=22)
        e.pack(side="left", padx=2)
        e.bind("<Return>", lambda ev: self.apply())
        ttk.Button(f, text="Apply", command=self.apply).pack(side="left", padx=4)
        ttk.Button(f, text="Rescan", command=self.rescan).pack(side="left")

        t = ttk.Frame(self.root)
        t.pack(fill="both", expand=True, padx=8)
        self.tree = ttk.Treeview(t, columns=[c[0] for c in COLUMNS], show="headings", selectmode="browse")
        for cid, title, width, key in COLUMNS:
            self.tree.heading(cid, text=title, command=(lambda k=key: self.sort_by(k)) if key else "")
            self.tree.column(cid, width=width, stretch=cid in ("run", "episode"),
                             anchor="e" if cid in ("targets", "tick") else "w")
        sb = ttk.Scrollbar(t, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self.play())
        self.tree.bind("<Return>", lambda e: self.play())
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.show_selected())

        b = ttk.Frame(self.root)
        b.pack(fill="x", padx=8, pady=6)
        ttk.Button(b, text="Play (windowed)", command=self.play).pack(side="left")
        ttk.Button(b, text="Check (headless MATCH/DESYNC)", command=self.check).pack(side="left", padx=6)
        ttk.Button(b, text="Copy path", command=self.copy_path).pack(side="left")
        ttk.Button(b, text="Open folder", command=self.open_folder).pack(side="left", padx=6)
        self.status = tk.StringVar()
        ttk.Label(b, textvariable=self.status).pack(side="left", padx=12)
        self.detail = tk.Text(self.root, height=5, font=("Consolas", 9), state="disabled")
        self.detail.pack(fill="x", padx=8, pady=(0, 8))

    # -- data -----------------------------------------------------------------------------------------------------

    def reload(self) -> None:
        self.rows = self.load_rows_fn()
        milestones = sorted({r["milestone"] for r in self.rows})
        self.milestone_cb.configure(values=["any"] + milestones)
        self.apply()

    def rescan(self, first_time: bool = False) -> None:
        """Incremental read-only scan in a background thread; the table reloads when it finishes."""
        if self._scanning:
            return
        self._scanning = True
        head = ("building the index for the first time (read-only; several minutes for ~40k episodes)"
                if first_time else "refreshing the index (read-only, incremental)")
        self.status.set(head + "...")

        def progress(line: str) -> None:
            self.root.after(0, lambda: self.status.set(f"{head}: {line.strip()}"))

        def work():
            try:
                stats = self.scan_fn(progress=progress)
                msg = (f"index refreshed: {stats['added_or_updated']} new/updated, {stats['removed']} removed, "
                       f"{stats['skipped_recent']} still being written (skipped), {stats['wall_s']} s")
            except Exception as exc:  # noqa: BLE001
                msg = f"scan failed: {exc}"
            print(msg)

            def done():
                self._scanning = False
                self.reload()
                self.status.set(msg)
            self.root.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    def apply(self) -> None:
        v = {k: var.get() for k, var in self.vars.items()}
        out = []
        for r in self.rows:
            if v["milestone"] != "any" and r["milestone"] != v["milestone"]:
                continue
            if v["role"] != "any" and r["role"] != v["role"]:
                continue
            if v["end"] != "any" and r["end_kind"] != v["end"]:
                continue
            if v["min_targets"] != "any" and (r["targets"] is None or r["targets"] < int(v["min_targets"])):
                continue
            if v["left"] != "any" and tri(r["left"]) != v["left"]:
                continue
            if v["crossing"] != "any" and tri(r["crossing"]) != v["crossing"]:
                continue
            if v["replay"] != "any" and (r["replay"] or "none") != v["replay"]:
                continue
            text = v["text"].strip().lower()
            if text and text not in (r["path"] + " " + (r["run_id"] or "") + " " + (r["profile"] or "")).lower():
                continue
            out.append(r)
        out.sort(key=SORT_KEYS[self.sort_key], reverse=self.sort_desc)
        self.view = out
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(out[:MAX_ROWS]):
            tick = r["completion_tick"] if r["end_kind"] == "clear" else r["last_tick"]
            self.tree.insert("", "end", iid=str(i), values=(
                r["targets"] if r["targets"] is not None else "-", r["end_kind"], tick if tick is not None else "-",
                left_text(r), tri(r["crossing"]), r["replay"] or "-", r["role"] or "", r["milestone"], r["run"],
                r["worker"] or "", r["episode_id"], r["created"]))
        more = f" (first {MAX_ROWS} shown)" if len(out) > MAX_ROWS else ""
        self.status.set(f"{len(out)} of {len(self.rows)} episodes{more}; sorted by {self.sort_key}"
                        f"{' desc' if self.sort_desc else ''}")

    def sort_by(self, key: str) -> None:
        if key == self.sort_key:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key, self.sort_desc = key, key in ("targets", "left", "crossing", "created", "last_tick")
        self.apply()

    # -- actions --------------------------------------------------------------------------------------------------

    def selected(self) -> Optional[Dict[str, Any]]:
        sel = self.tree.selection()
        return self.view[int(sel[0])] if sel else None

    def show_selected(self) -> None:
        r = self.selected()
        if r is None:
            return
        lines = [
            r["path"],
            f"{r['role']}  run_id {r['run_id']}  profile {r['profile']}  observation {r['observation']}  "
            f"reward {r['reward']}",
            f"end {r['end_kind']} ({r['end_detail']})  targets {r['targets']}  steps {r['steps']}  "
            f"completion tick {r['completion_tick']}  prefix rows {r['prefix_rows']}",
            f"left entry {left_text(r)} (source {r['left_source'] or '-'})  min x {r['min_x']}  crossing "
            f"{tri(r['crossing'])} (source {r['crossing_source'] or '-'})  replay {r['replay'] or '-'}  "
            f"sidecars {r['sidecars'] or '-'}",
        ]
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("end", "\n".join(lines))
        self.detail.configure(state="disabled")

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
        if self._spawn([], capture=False):
            self.status.set("viewer started")

    def check(self) -> None:
        p = self._spawn(["--check"], capture=True)
        if p is None:
            return
        self.status.set("headless replay running...")

        def wait():
            out, _ = p.communicate()
            last = [ln for ln in out.splitlines() if ln.startswith(("MATCH", "DESYNC", "error"))]
            self.root.after(0, lambda: (self._show_text(out), self.status.set(last[-1] if last else f"exit {p.returncode}"),
                                        self.reload()))

        threading.Thread(target=wait, daemon=True).start()

    def _show_text(self, text: str) -> None:
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("end", text)
        self.detail.configure(state="disabled")

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
