#!/usr/bin/env python3
"""M7u preparation: READ-ONLY clock-consistency check of the exogenous track on existing captures.

Checks that the moving platform group's translate / speed and the moving target's position are identical, tick for
tick, across captures driven by different word sequences, i.e. that they are a function of the clock and not of the
agent's actions. Reads `runs/m7q/_equiv/input_all/*.json.gz` (recorded raw replies; nothing is launched or replayed).
The TAS traces are used here only as additional read-only validation evidence; no capture of any kind becomes training
data. The gate repeats the same check on its own training episodes before training (rl/m7u_gate.py).

    python rl/tools/m7u_track_check.py [--out logs/m7u_track_check]
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import m7g_spatial as ms  # noqa: E402
import m7u_state as us  # noqa: E402

REPO_ROOT = HERE.parent.parent
SOURCE = REPO_ROOT / "runs" / "m7q" / "_equiv" / "input_all"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO_ROOT / "logs" / "m7u_track_check"))
    a = ap.parse_args(argv)
    out = Path(a.out)
    if (REPO_ROOT / "runs") in out.resolve().parents:
        print("refused: outputs never go under runs/")
        return 2
    traces, episodes = [], []
    offset_dev = 0.0
    for p in sorted(SOURCE.glob("*.json.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as fp:
            d = json.load(fp)
        rows = np.stack([us.row_from_reply(d["initial"])] + [us.row_from_reply(r) for r in d["steps"]])
        v = rows[rows[:, us.F["valid"]] == 1.0]
        live2 = ~np.isnan(v[:, us.F["t2_y"]])
        if live2.any():
            offset_dev = max(offset_dev, float(np.abs(v[live2, us.F["t2_y"]] - v[live2, us.F["grp_ty"]]
                                                      - ms.MOVING_TARGET_OFFSET_Y).max()))
        kind = "tas_validation_only" if p.name.startswith("tas_") else "track1_policy_or_random"
        traces.append({"trace": p.name, "kind": kind, "rows": int(len(rows)), "valid_rows": int(len(v)),
                       "action_digest": d.get("action_digest"),
                       "world_equal_pinned": us.world_digest(us.static_world(d["initial"]))
                       == us.world_digest(us.static_world_pinned())})
        episodes.append(rows)
    track, problems = us.build_clock_track(episodes)
    compared = 0
    cols = [us.F[c] for c in us.TRACK_COLUMNS]
    for rows in episodes:
        v = rows[rows[:, us.F["valid"]] == 1.0]
        compared += len(v)
    distinct_words = len({t["action_digest"] for t in traces})
    rep = {"tool": "m7u_track_check_v1", "source": str(SOURCE.relative_to(REPO_ROOT)), "traces": traces,
           "distinct_word_sequences": distinct_words, "ticks_covered": int(track.covered.sum()),
           "ticks_compared": compared, "problems": problems, "track_sha256": track.digest(),
           "moving_target_offset_max_deviation": offset_dev,
           "world_equal_pinned_all": all(t["world_equal_pinned"] for t in traces),
           "ok": not problems and all(t["world_equal_pinned"] for t in traces) and distinct_words >= 2,
           "note": "read-only; nothing launched or replayed; no capture is training data"}
    out.mkdir(parents=True, exist_ok=True)
    (out / "track_check.json").write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("ok", "distinct_word_sequences", "ticks_covered", "ticks_compared",
                                          "moving_target_offset_max_deviation", "world_equal_pinned_all")}
                     | {"problems": problems[:5]}))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
