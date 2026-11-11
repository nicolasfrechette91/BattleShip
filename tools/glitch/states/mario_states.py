#!/usr/bin/env python3
"""Mario's state machine, statically and in traces (no ROM, no game).

  extract  [--decomp DIR] [--out STEM]            static status/transition table -> STEM.json + STEM.md
  detect   --trace T [--trace T ...] | --trace-dir D [--table JSON | --decomp DIR] [--out FILE]
                                                   state-machine signals over lab traces -> btt_glitch_event_v1 JSONL

Outputs go to the Git-ignored logs/glitch/states/ by default. The table is for detecting and explaining what an agent
did; it names no place on the stage and proposes no input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import decomp_states as ds  # noqa: E402
import state_detect as sd  # noqa: E402

REPO = HERE.parent.parent.parent
OUT = REPO / "logs" / "glitch" / "states"


def _decomp(path: Optional[str]) -> Path:
    root = Path(path) if path else REPO / "decomp"
    if not (root / "src" / "ft" / "ftmain.c").exists():
        raise SystemExit(f"{root} has no src/ft/ftmain.c: run `git submodule update --init decomp` first")
    return root


def cmd_extract(a: argparse.Namespace) -> int:
    table = ds.build_table(_decomp(a.decomp))
    stem = Path(a.out) if a.out else OUT / "mario_states"
    stem.parent.mkdir(parents=True, exist_ok=True)
    stem.with_suffix(".json").write_text(json.dumps(table, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")
    stem.with_suffix(".md").write_text(ds.render_markdown(table), encoding="utf-8", newline="\n")
    reach = [s for s in table["statuses"].values() if s["btt"].get("reachable")]
    print(f"wrote {stem.with_suffix('.json')} and {stem.with_suffix('.md')}: {len(table['statuses'])} statuses, "
          f"{len(reach)} reachable in BTT, {len(table['edges'])} edges, {len(table['problems'])} problems")
    return 1 if table["problems"] else 0


def load_table(a: argparse.Namespace) -> Dict[str, Any]:
    if a.table:
        return json.loads(Path(a.table).read_text(encoding="utf-8"))
    return ds.build_table(_decomp(a.decomp))


def cmd_detect(a: argparse.Namespace) -> int:
    import geometry as gm  # tools/glitch/geometry.py (open_json)
    paths = [Path(p) for p in a.trace or []]
    if a.trace_dir:
        paths += sorted(Path(a.trace_dir).rglob("*.json.gz")) + sorted(Path(a.trace_dir).rglob("*.json"))
    if not paths:
        raise SystemExit("give --trace or --trace-dir")
    table = load_table(a)
    out = Path(a.out) if a.out else OUT / "state_events.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    summaries: List[Dict[str, Any]] = []
    with out.open("w", encoding="utf-8", newline="\n") as f:
        for path in paths:
            try:
                tr = gm.open_json(path)
            except (OSError, ValueError) as exc:
                summaries.append({"trace": str(path), "error": str(exc)})
                continue
            if not isinstance(tr, dict) or "steps" not in tr:
                continue
            src = {"trace": str(path), **{k: tr[k] for k in ("label", "mode") if k in tr}}
            events, summary = sd.scan(tr, table, source=src)
            for ev in events:
                f.write(json.dumps(ev, separators=(",", ":")) + "\n")
            summaries.append(summary)
    out.with_suffix(".summary.json").write_text(json.dumps(summaries, indent=1) + "\n", encoding="utf-8", newline="\n")
    total = sum(s.get("events", 0) for s in summaries)
    print(f"wrote {out}: {total} events from {len(summaries)} traces")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("extract")
    s.add_argument("--decomp")
    s.add_argument("--out", help="output stem (without suffix)")
    s.set_defaults(fn=cmd_extract)
    s = sub.add_parser("detect")
    s.add_argument("--trace", action="append")
    s.add_argument("--trace-dir")
    s.add_argument("--table", help="table JSON from `extract` (else it is rebuilt from --decomp)")
    s.add_argument("--decomp")
    s.add_argument("--out")
    s.set_defaults(fn=cmd_detect)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
