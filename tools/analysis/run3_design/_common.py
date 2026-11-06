"""Shared helpers of the run 3 design analyses (read-only on the lab; zero native ticks; standard library only).

Every script takes --lab (default C:/BattleShip_lab) and --out (default <repo>/logs/run3_design, Git-ignored) and writes nothing
anywhere else.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "frs"))
sys.path.insert(0, str(REPO / "rl"))

RUN1 = "crossing_2026-10-15/run"
RUN2 = "crossing_2026-10-15_run2/run"
MARGIN = 24                       # E7's registered margin (rl/frs_run.MARGIN)
BOUND_RUN3 = 1245 - MARGIN - 1    # 1,220: run 3's eligibility bound, fixed for the run (MINOR table)
RUN2_BEST_STEPS = [(813, 1352), (19643, 1261), (36236, 1245)]   # run 2's verified bests: (dispatch n of the claim, ticks)
RUN1_BEST = 1429


def parse(doc: str) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=doc.strip().splitlines()[0])
    ap.add_argument("--lab", default="C:/BattleShip_lab", help="the lab root (read only)")
    ap.add_argument("--out", default=str(REPO / "logs" / "run3_design"), help="where the JSON results go")
    a = ap.parse_args()
    a.lab = Path(a.lab)
    a.out = Path(a.out)
    a.out.mkdir(parents=True, exist_ok=True)
    a.r1 = a.lab / RUN1
    a.r2 = a.lab / RUN2
    return a


def rows(p: Path) -> Iterator[Dict[str, Any]]:
    with open(p, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def bursts(run: Path, by_n: bool = False) -> List[Dict[str, Any]]:
    """The run's burst dispatch rows, in file (ingest) order, or sorted by dispatch number."""
    d = [x for x in rows(run / "dispatches.jsonl") if x.get("kind", "burst") == "burst"]
    return sorted(d, key=lambda x: x["n"]) if by_n else d


def dump(a: argparse.Namespace, name: str, obj: Any) -> Path:
    p = a.out / name
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=1, default=lambda o: list(o) if isinstance(o, (tuple, set)) else str(o))
    print(f"\nwritten: {p}")
    return p


def gkey(g: Tuple[Any, ...]) -> str:
    return "|".join(str(x) for x in g)
