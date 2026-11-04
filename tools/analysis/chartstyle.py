"""Shared chart style for tools/analysis (matplotlib, light surface, static PNG for markdown).

Tokens from the validated reference palette (categorical order validated with the data-viz palette script: every adjacent
pair passes CVD and normal-vision separation; slots 3 to 5 sit under 3:1 contrast on the surface, so every chart that uses
them carries direct labels, and RUN2_ANALYSIS.md repeats each chart's numbers in a table).
"""
from __future__ import annotations

from typing import Any, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
BLUE = SERIES[0]
BLUE_LIGHT = "#9ec5f4"     # sequential step 200: the "range" extension of a bar


def apply() -> None:
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "font.family": "sans-serif", "font.size": 9.5, "text.color": INK, "axes.labelcolor": INK2, "axes.titlecolor": INK,
        "axes.titlesize": 10.5, "axes.titleweight": "bold", "axes.titlelocation": "left", "axes.titlepad": 8,
        "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelcolor": INK2, "ytick.labelcolor": INK2,
        "axes.edgecolor": BASELINE, "axes.linewidth": 0.8, "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": False, "grid.color": GRID, "grid.linewidth": 0.6, "grid.linestyle": "-",
        "lines.linewidth": 1.6, "lines.markersize": 6, "legend.frameon": False, "legend.fontsize": 9,
        "xtick.major.size": 0, "ytick.major.size": 0, "xtick.major.pad": 4, "ytick.major.pad": 4,
    })


def ygrid(ax: Any) -> None:
    ax.grid(True, axis="y")
    ax.set_axisbelow(True)
    ax.spines["left"].set_visible(False)


def xgrid(ax: Any) -> None:
    ax.grid(True, axis="x")
    ax.set_axisbelow(True)
    ax.spines["left"].set_visible(False)


HEADER_IN = 0.72   # inches reserved at the top of every figure for the title and the subtitle


def header(fig: Any, title: str, subtitle: str) -> None:
    """Figure title in primary ink, the evidence level and source in secondary ink, placed in inches from the top edge so
    short and tall figures get the same band."""
    h = fig.get_figheight()
    fig.text(0.012, 1 - 0.10 / h, title, ha="left", va="top", fontsize=12, fontweight="bold", color=INK)
    fig.text(0.012, 1 - 0.40 / h, subtitle, ha="left", va="top", fontsize=9, color=INK2)


def save(fig: Any, path: Any, top: Optional[float] = None, bottom: Optional[float] = None) -> None:
    """Lay the axes out below the header band (tight_layout sizes the margins to the tick labels), then write a 2x PNG.
    `top` and `bottom` are accepted for older callers and ignored: the band is HEADER_IN inches."""
    fig.tight_layout(rect=(0, 0, 1, 1 - HEADER_IN / fig.get_figheight()))
    fig.savefig(path, dpi=200)
    plt.close(fig)
