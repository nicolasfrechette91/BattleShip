#!/usr/bin/env python3
"""Tick-0 frame-count probe (REVIEW_2026-11-03.md, finding D9). NATIVE: it boots the game; run it only with the owner's go.

Boots N fresh BattleShip processes, one after another, through the real lifecycle code (rl/m7f_trace.run_stepping_trace: private
runtime directory, M2 launcher, the explore flags of rl/m8_rd_session.FLAGS_EXPLORE). Each one is observed once at tick 0 with no
action submitted, then terminated. It reports the observation's `host_frame` at tick 0, which is the number of host frames the game
ran before the first controller read. The pinned tick-0 record excludes `host_frame`, but in a fresh process it should be a
constant. A changing value points to a boot path that depends on timing. Nothing here reads, logs or compares native RNG state.

    python -B tools/audit/tick0_frame_probe.py --exe C:/BattleShip_lab/import/exe/BattleShip.exe \
        --out C:/BattleShip_lab/probes/tick0_frames_<date> --boots 10

Writes only under --out, which must not exist yet. Exit code 0: constant; 1: not constant; 2: refused.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "rl"))


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--exe", required=True, type=Path, help="the pinned executable (its directory holds the frozen config)")
    ap.add_argument("--out", required=True, type=Path, help="new output folder (refused if it exists)")
    ap.add_argument("--boots", type=int, default=10, help="number of fresh processes (default 10)")
    a = ap.parse_args(argv)
    out = a.out.resolve()
    if out.exists():
        print(f"refused: {out} exists", file=sys.stderr)
        return 2
    if a.boots < 2:
        print("refused: --boots must be at least 2", file=sys.stderr)
        return 2
    if ROOT in out.parents or out == ROOT:
        print(f"refused: --out lies inside the checkout {ROOT}", file=sys.stderr)
        return 2

    import m7f_trace as trace
    import m8_rd_session as session

    out.mkdir(parents=True)
    rows = []
    for i in range(a.boots):
        tr = trace.run_stepping_trace(f"tick0_{i}", a.exe, [], out / f"boot_{i:02d}", extra_env=session.FLAGS_EXPLORE)
        o = tr["initial"]["observation"]
        row = {"boot": i, "host_frame": o["host_frame"], "input_tick": o["input_tick"], "time_passed": o["time_passed"],
               "startup_s": tr["startup_s"], "cleanup": tr["cleanup"]}
        rows.append(row)
        print(json.dumps(row), flush=True)
    frames = [r["host_frame"] for r in rows]
    summary = {"exe": str(a.exe), "boots": a.boots, "host_frame_at_tick0": frames, "constant": len(set(frames)) == 1,
               "all_input_tick_0": all(r["input_tick"] == 0 for r in rows)}
    with open(out / "summary.json", "w", encoding="utf-8", newline="\n") as fp:
        json.dump(summary, fp, indent=2)
        fp.write("\n")
    print(json.dumps(summary))
    return 0 if summary["constant"] and summary["all_input_tick_0"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
