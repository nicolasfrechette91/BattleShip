#!/usr/bin/env python3
"""Charts for RUN2_ANALYSIS.md, from docs/analysis/run2/run2_records.json (built by run2_records.py from committed records).

    python -B tools/analysis/run2_charts.py [--data docs/analysis/run2/run2_records.json] [--out docs/analysis/run2]

Each chart's subtitle names its evidence level (recorded / derived / inferred) and its record.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

import chartstyle as cs  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DEFAULT_DATA = REPO / "docs" / "analysis" / "run2" / "run2_records.json"
THOUSANDS = FuncFormatter(lambda v, _p: f"{v:,.0f}")


def src(d: Dict[str, Any]) -> str:
    s = d["source"]
    return f"{d['evidence']} · {s['doc'].replace('docs/', '')}, {s['section']}"


def hourly(D: Dict[str, Any], out: Path) -> str:
    h = D["hourly"]
    rows = h["rows"]
    hours = [f"{r['hour']}" + ("*" if r["hour"] == len(rows) else "") for r in rows]
    panels = [("dispatches", "Dispatches per hour"), ("new_cells", "New cells per hour"), ("replacements", "Faster arrivals per hour"),
              ("breaks", "Bursts that broke a target, per hour"), ("clears_claimed", "Clears claimed per hour")]
    fig, axes = plt.subplots(2, 3, figsize=(11, 5.6))
    for ax, (key, title) in zip(axes.flat, panels):
        ax.bar(hours, [r[key] for r in rows], width=0.62, color=cs.BLUE)
        ax.set_title(title)
        ax.yaxis.set_major_formatter(THOUSANDS)
        cs.ygrid(ax)
        ax.set_xlabel("search hour (* = last 46 min)")
    ax = axes.flat[5]
    vals = h["checks_per_utc_hour"]["values"]
    ax.bar([str(i + 1) for i in range(len(vals))], vals, width=0.62, color=cs.BLUE)
    ax.set_title("Inherited-cell re-checks per hour")
    ax.set_xlabel("UTC hour from launch (includes the open)")
    cs.ygrid(ax)
    cs.header(fig, "Run 2 over time: the dispatch rate rose as re-checks fell; breaks and new cells stayed flat",
              f"{src(h)} · 39,309 dispatches, 4,550 new cells, 71,237 replacements in 466 min")
    cs.save(fig, out / "run2_hourly.png")
    return "run2_hourly.png"


def best_timeline(D: Dict[str, Any], out: Path) -> str:
    b = D["best_timeline"]
    end_min = round(D["totals"]["values"]["wall_s"] / 60)
    xs, ys = [0], [b["start_best"]]
    for r in b["rows"]:
        xs.append(r["elapsed_min"])
        ys.append(r["best"])
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.step(xs + [end_min], ys + [ys[-1]], where="post", color=cs.BLUE, lw=1.8)
    ax.plot(xs[1:], ys[1:], "o", color=cs.BLUE, ms=6, mec=cs.SURFACE, mew=1.5)
    ax.plot([0], [ys[0]], "o", color=cs.SURFACE, ms=6, mec=cs.BLUE, mew=1.5)
    ax.annotate("1,429 (run 1's best, imported)", (0, ys[0]), xytext=(6, 6), textcoords="offset points", color=cs.INK2, fontsize=9)
    for r in b["rows"]:
        h, mnt = divmod(r["elapsed_min"], 60)
        when = f"{h} h {mnt:02d}" if h else f"{mnt} min"
        ax.annotate(f"{r['best']:,} at {when}\ndispatch {r['dispatch']:,}, −{r['gain']}", (r["elapsed_min"], r["best"]), xytext=(6, 6),
                    textcoords="offset points", color=cs.INK, fontsize=9)
    ax.set_xlim(-8, end_min + 75)
    ax.set_ylim(1200, 1470)
    ax.set_xlabel("minutes since launch")
    ax.set_ylabel("best verified clear (input ticks)")
    ax.yaxis.set_major_formatter(THOUSANDS)
    cs.ygrid(ax)
    cs.header(fig, "Best verified clear: three gains, the last 16 ticks after 7 h 21", src(b))
    cs.save(fig, out / "run2_best_timeline.png", top=0.8, bottom=0.14)
    return "run2_best_timeline.png"


def earliest(D: Dict[str, Any], out: Path) -> str:
    e = {r["level"]: r for r in D["earliest_per_level"]["rows"]}
    total = D["totals"]["values"]["dispatches"]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    for color, lv in ((cs.SERIES[0], 9), (cs.SERIES[1], 8)):
        r = e[lv]
        xs, ys = [0], [r["run1"]]
        for imp in r["improvements"]:
            xs.append(imp["dispatch"])
            ys.append(imp["tick"])
        ax.step(xs + [total], ys + [ys[-1]], where="post", color=color, lw=1.8, label=f"level {lv}")
        ax.plot(xs[1:], ys[1:], "o", color=color, ms=6, mec=cs.SURFACE, mew=1.5)
        ax.annotate(f"level {lv}: {ys[-1]:,}", (total, ys[-1]), xytext=(4, -3), textcoords="offset points", color=cs.INK, fontsize=9, va="center")
    ax.set_xlim(-500, total * 1.12)
    ax.set_xlabel("run 2 dispatch")
    ax.set_ylabel("earliest arrival (input tick)")
    ax.xaxis.set_major_formatter(THOUSANDS)
    ax.yaxis.set_major_formatter(THOUSANDS)
    ax.legend(loc="upper right", ncol=2)
    cs.ygrid(ax)
    cs.header(fig, "Earliest arrivals at levels 8 and 9: after dispatch 2,723 they improved by 21 ticks in all",
              f"{src(D['earliest_per_level'])}")
    cs.save(fig, out / "run2_earliest_arrival.png", top=0.8, bottom=0.14)
    return "run2_earliest_arrival.png"


def level9_groups(D: Dict[str, Any], out: Path) -> str:
    g = D["level9_groups"]
    rows = g["rows"]
    names = [r["group"] for r in rows][::-1]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.2), sharey=True)
    for ax, key, title in ((axes[0], "dispatches", "Level-9 dispatches"), (axes[1], "clears", "Clears claimed")):
        vals = [r[key] for r in rows][::-1]
        ax.barh(names, vals, height=0.55, color=cs.BLUE)
        for y, v in enumerate(vals):
            ax.annotate(f"{v:,}", (v, y), xytext=(4, 0), textcoords="offset points", va="center", color=cs.INK, fontsize=9)
        ax.set_title(title)
        ax.xaxis.set_major_formatter(THOUSANDS)
        ax.set_xlim(0, max(vals) * 1.22)
        cs.xgrid(ax)
    cs.header(fig, "At level 9 the group with target 6 left took the most dispatches and never cleared", src(g))
    cs.save(fig, out / "run2_level9_groups.png", top=0.72, bottom=0.12)
    return "run2_level9_groups.png"


def chain(D: Dict[str, Any], out: Path) -> str:
    c = D["chain_1245"]
    rows = [r for r in c["rows"] if r["created_run"] == "run 2"]
    fig, ax = plt.subplots(figsize=(9.5, 3.9))
    labels = []
    for y, r in enumerate(rows):
        ax.plot([r["created_at"], r["first_dispatched_at"]], [y, y], color=cs.BLUE_LIGHT, lw=5, solid_capstyle="round")
        ax.plot([r["created_at"]], [y], "o", color=cs.SURFACE, mec=cs.BLUE, mew=1.5, ms=6)
        ax.plot([r["first_dispatched_at"]], [y], "o", color=cs.BLUE, mec=cs.SURFACE, mew=1.5, ms=7)
        wait = r["first_dispatched_at"] - r["created_at"]
        ax.annotate(f"waited {wait:,}", (r["first_dispatched_at"], y), xytext=(7, 0), textcoords="offset points", va="center", fontsize=9, color=cs.INK)
        labels.append(f"link {r['link']} (level {r['level_tick'].split(':')[0]}, tick {r['level_tick'].split(':')[1].strip()})")
    ax.set_yticks(range(len(rows)), labels)
    ax.invert_yaxis()
    ax.set_xlabel("run 2 dispatch counter  (○ cell created · ● first dispatched)")
    ax.xaxis.set_major_formatter(THOUSANDS)
    ax.set_xlim(13500, 39500)
    cs.xgrid(ax)
    cs.header(fig, "The 1,245's chain: each link waited hundreds to thousands of dispatches to be drawn once",
              "recorded · frs_strategy_2026-10-16.md, section 5 · link 5 (created in run 1) is not shown")
    cs.save(fig, out / "run2_chain_waits.png", top=0.8, bottom=0.14)
    return "run2_chain_waits.png"


def ticks(D: Dict[str, Any], out: Path) -> str:
    t = D["totals"]["values"]["ticks"]
    parts = [("prefix replay (return to a cell)", t["prefix"]), ("inherited-cell re-checks", t["checks"]), ("bursts (exploration)", t["burst"]),
             ("verification, reference, anchor", t["verification"] + t["reference"] + t["anchor"])]
    fig, ax = plt.subplots(figsize=(9, 2.9))
    names = [p[0] for p in parts][::-1]
    vals = [p[1] / 1e6 for p in parts][::-1]
    ax.barh(names, vals, height=0.55, color=cs.BLUE)
    for y, (v, p) in enumerate(zip(vals, [p[1] for p in parts][::-1])):
        pct = 100 * p / t["all"]
        ax.annotate(f"{v:,.2f} M ({pct:.1f} %)" if pct >= 0.1 else f"{p:,} ticks (<0.1 %)", (v, y), xytext=(4, 0), textcoords="offset points",
                    va="center", fontsize=9, color=cs.INK)
    ax.set_xlim(0, max(vals) * 1.3)
    ax.set_xlabel("game ticks (millions)")
    cs.xgrid(ax)
    cs.header(fig, "Where run 2's 54.1 M game ticks went: 86 % replaying prefixes, 6.6 % exploring",
              f"recorded (shares derived) · {D['totals']['source']['doc'].replace('docs/', '')}, {D['totals']['source']['section']}")
    cs.save(fig, out / "run2_ticks.png", top=0.72, bottom=0.18)
    return "run2_ticks.png"


def worker_time(D: Dict[str, Any], out: Path) -> str:
    w = D["worker_time"]
    lo, hi = w["range"]["low"], w["range"]["high"]
    items = [("prefix stepping", lo["prefix_stepping_s"], hi["prefix_stepping_s"]), ("burst stepping", lo["burst_stepping_s"], hi["burst_stepping_s"]),
             ("native game frames (inside stepping)", lo["of_which_native_frames_s"], hi["of_which_native_frames_s"]),
             ("boot wait, close, transfer, selection", hi["rest_s"], lo["rest_s"])]
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 3.4), gridspec_kw={"width_ratios": [2.2, 1]})
    ax = axes[0]
    names = [i[0] for i in items][::-1]
    a = [i[1] for i in items][::-1]
    b = [i[2] for i in items][::-1]
    ax.barh(names, a, height=0.55, color=cs.BLUE)
    ax.barh(names, [y - x for x, y in zip(a, b)], left=a, height=0.55, color=cs.BLUE_LIGHT)
    for y, (x1, x2) in enumerate(zip(a, b)):
        ax.annotate(f"{x1:.2f}–{x2:.2f} s" if abs(x2 - x1) > 0.005 else f"{x1:.2f} s", (x2, y), xytext=(4, 0), textcoords="offset points", va="center",
                    fontsize=9, color=cs.INK)
    ax.set_xlim(0, max(b) * 1.35)
    ax.set_title(f"Seconds per job (of {lo['per_job_s']:.2f} s) · INFERRED")
    ax.set_xlabel("seconds (dark = low estimate, light = range to high)")
    cs.xgrid(ax)
    ax = axes[1]
    share = w["derived_shares"]["checks_share_of_worker_time"]
    ax.barh(["jobs", "inherited-cell re-checks"], [100 * (1 - share), 100 * share], height=0.55, color=cs.BLUE)
    for y, v in enumerate([100 * (1 - share), 100 * share]):
        ax.annotate(f"{v:.1f} %", (v, y), xytext=(4, 0), textcoords="offset points", va="center", fontsize=9, color=cs.INK)
    ax.set_xlim(0, 118)
    ax.invert_yaxis()
    ax.set_title("Share · derived")
    ax.set_xlabel("% of 5 × 28,505 worker-seconds")
    cs.xgrid(ax)
    cs.header(fig, "Worker time: about half of each job is stepping, under a quarter of that is the game itself",
              "INFERRED: run 2's totals × per-tick costs measured in sd2 and the lab smoke run (1.12–1.38 ms per tick, 0.28 ms native frame)")
    cs.save(fig, out / "run2_worker_time.png", top=0.72, bottom=0.18)
    return "run2_worker_time.png"


def bests_progress(D: Dict[str, Any], out: Path) -> str:
    b = D["bests_breaks"]["breaks"]
    pick = [("1,245", "1,245 (run 2 best)"), ("1,352", "1,352 (run 2)"), ("1,429", "1,429 (run 1 best)"), ("1,885", "1,885 (registered)")]
    fig, ax = plt.subplots(figsize=(9.5, 4.4))
    for color, (k, label) in zip(cs.SERIES, pick):
        br = b[k]
        xs = [0] + [x["tick"] for x in br]
        ys = list(range(len(xs)))
        ax.step(xs, ys, where="post", color=color, lw=1.8, label=label)
        above = k != "1,352"                                   # 1,352 and 1,429 end 77 ticks apart: one label above, one below
        ax.annotate(label.split(" ")[0], (xs[-1], ys[-1]), xytext=(4, 5 if above else -14), textcoords="offset points", fontsize=9, color=cs.INK)
    ax.set_xlabel("input tick")
    ax.set_ylabel("targets broken")
    ax.set_yticks(range(0, 11, 2))
    ax.set_xlim(-20, 2000)
    ax.set_ylim(-0.3, 11.2)
    ax.xaxis.set_major_formatter(THOUSANDS)
    ax.legend(loc="lower right")
    cs.ygrid(ax)
    cs.header(fig, "The 1,245 gains on the right side (7 targets by 639) and loses most time crossing to target 6",
              src(D["bests_breaks"]))
    cs.save(fig, out / "run2_bests_progress.png", top=0.8, bottom=0.13)
    return "run2_bests_progress.png"


def level7_prefixes(D: Dict[str, Any], out: Path) -> str:
    o = D["orders"]
    rows = o["level7"]
    fig, ax = plt.subplots(figsize=(9.5, 4.4))
    ax.set_xscale("log")
    ax.scatter([r["dispatches"] for r in rows], [r["fastest_arrival"] for r in rows], s=46, color=cs.BLUE, edgecolors=cs.SURFACE, linewidths=1.5, zorder=3)
    notes = {"4, 0, 5, 7, 9, 3, 2": "the 1,245's order", "4, 5, 9, 7, 0, 3, 2": "the 1,429's order", "0, 4, 9, 5, 3, 7, 2": "the reference's order",
             "4, 0, 5, 7, 9, 2, 3": None, "0, 4, 5, 7, 9, 3, 2": None}
    for r in rows:
        if r["prefix"] in notes:
            text = r["prefix"] + (f"  ({notes[r['prefix']]})" if notes[r["prefix"]] else "")
            ax.annotate(text, (r["dispatches"], r["fastest_arrival"]), xytext=(7, -3), textcoords="offset points", fontsize=8.5, color=cs.INK)
    ax.set_xlabel("dispatches from states with exactly this order (log scale)")
    ax.set_ylabel("fastest level-7 arrival (input tick)")
    ax.xaxis.set_major_formatter(THOUSANDS)
    ax.yaxis.set_major_formatter(THOUSANDS)
    ax.set_xlim(10, 30000)
    cs.ygrid(ax)
    cs.header(fig, "Level-7 target orders: two took 9,152 of 15,371 dispatches; nine got 16 to 48 each",
              f"{src(o)} · one dot per order prefix at level 7")
    cs.save(fig, out / "run2_level7_orders.png", top=0.8, bottom=0.13)
    return "run2_level7_orders.png"


def segments(D: Dict[str, Any], out: Path) -> str:
    s = D["segments_1245"]
    rows = s["rows"]
    fig, ax = plt.subplots(figsize=(9.5, 4.6))
    ys = list(range(len(rows)))
    h = 0.36
    ax.barh([y - h / 2 - 0.02 for y in ys], [r["clear"] for r in rows], height=h, color=cs.SERIES[0], label="the 1,245's own ticks")
    ax.barh([y + h / 2 + 0.02 for y in ys], [r["best"] for r in rows], height=h, color=cs.SERIES[1], label="fastest observed anywhere")
    for y, r in zip(ys, rows):
        if r["room"] >= 50:
            ax.annotate(f"room {r['room']}", (r["clear"], y - h / 2), xytext=(4, 0), textcoords="offset points", va="center", fontsize=9, color=cs.INK)
    ax.set_yticks(ys, [r["pair"] for r in rows])
    ax.invert_yaxis()
    ax.set_xlabel("ticks from the previous break")
    ax.legend(loc="lower right")
    cs.xgrid(ax)
    cs.header(fig, "The 1,245, segment by segment: 324 of its 580 ticks of room are in 3 → 2 and 2 → 6",
              f"{src(s)} · a composite of best segments is not a route")
    cs.save(fig, out / "run2_segments.png", top=0.8, bottom=0.12)
    return "run2_segments.png"


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--out", type=Path, default=DEFAULT_DATA.parent)
    a = ap.parse_args(argv)
    D = json.loads(a.data.read_text(encoding="utf-8"))
    cs.apply()
    a.out.mkdir(parents=True, exist_ok=True)
    made = [fn(D, a.out) for fn in (hourly, best_timeline, earliest, level9_groups, chain, ticks, worker_time, bests_progress, level7_prefixes, segments)]
    print("wrote " + ", ".join(made))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
