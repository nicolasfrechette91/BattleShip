#!/usr/bin/env python3
"""Glitch-candidate tools for Mario's Break the Targets (see GLITCH_CANDIDATES.md).

Subcommands (outputs default to the Git-ignored logs/glitch/):

  extract  --rom PATH [--version us|jp]       ROM -> geometry JSON; cross-checks the asset yamls and the decomp source
  decomp                                       decomp relocData source -> geometry JSON (no ROM)
  analyze  [--geometry G | --decomp | --trace T] [--trace T] [--ecb top,center,bottom,width]
                                               candidate checks -> JSON + Markdown (names places: detection only)
  compare  --geometry G --trace T              ROM line table against the table the port loaded natively
  detect   --trace T [--trace T ...] | --trace-dir D [--geometry G] [--states TABLE|decomp]
                                               per-tick anomaly events (btt_glitch_event_v1 JSONL)

Read-only towards the game, the ROM and the lab folders. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import analysis  # noqa: E402
import detect  # noqa: E402
import geometry as gm  # noqa: E402

REPO = HERE.parent.parent
OUT = REPO / "logs" / "glitch"


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {path}")


def _decomp_geometry() -> gm.Geometry:
    stage_c, header_c = gm.default_decomp_paths(REPO)
    if not stage_c.exists():
        raise SystemExit(f"{stage_c} not found: run `git submodule update --init decomp` first")
    return gm.derive(gm.parse_decomp_source(stage_c, header_c), origin="decomp-source")


def cmd_extract(a: argparse.Namespace) -> int:
    rom = Path(a.rom).read_bytes()
    geo, report = gm.extract_from_rom(rom, a.version, None if a.no_yaml_check else REPO, a.header_file)
    stage_c, _ = gm.default_decomp_paths(REPO)
    if stage_c.exists() and not a.no_decomp_check:
        ref = _decomp_geometry()
        diffs = gm.compare_lines(geo, ref)
        same_raw = geo.raw is not None and ref.raw is not None and (
            [(v.x, v.y, v.flags) for v in geo.raw.vertices] == [(v.x, v.y, v.flags) for v in ref.raw.vertices]
            and geo.raw.vertex_ids == ref.raw.vertex_ids and geo.raw.links == ref.raw.links)
        report["checks"].append({"check": "geometry equals the decomp source decode", "ok": not diffs and same_raw,
                                 "line_diffs": diffs[:20]})
        header_ref = {k: v for k, v in ref.header.items() if k in geo.header}
        if header_ref:
            report["checks"].append({"check": "header bounds equal the decomp source", "ok": header_ref == {k: geo.header[k] for k in header_ref}})
    out = Path(a.out) if a.out else OUT / f"geometry_{report['version']}.json"
    data = geo.to_json()
    data["extraction_report"] = report
    _write_json(out, data)
    for c in report["checks"]:
        print(("OK   " if c["ok"] else "FAIL ") + c["check"])
    print(f"{len(geo.lines)} lines; geometry sha256 {geo.sha256()}")
    return 0 if all(c["ok"] for c in report["checks"]) else 1


def cmd_decomp(a: argparse.Namespace) -> int:
    geo = _decomp_geometry()
    _write_json(Path(a.out) if a.out else OUT / "geometry_decomp.json", geo.to_json())
    print(f"{len(geo.lines)} lines; geometry sha256 {geo.sha256()}")
    return 0


def _trace_context(path: Optional[str]) -> Tuple[Optional[dict], Dict[int, Tuple[float, float, float, float]], List[Tuple[int, float, float, bool]]]:
    if not path:
        return None, {}, []
    tr = gm.open_json(Path(path))
    ranges: Dict[int, List[float]] = {}
    for reply in [tr.get("initial") or {}] + list(tr.get("steps") or []):
        for g in (reply.get("spatial") or {}).get("groups") or []:
            if int(g.get("translated", 0)) != 1:
                continue
            x, y = float(g["translate"][0]), float(g["translate"][1])
            r = ranges.setdefault(int(g["id"]), [x, x, y, y])
            r[0], r[1], r[2], r[3] = min(r[0], x), max(r[1], x), min(r[2], y), max(r[3], y)
    targets = [(int(t["id"]), float(t["spawn"][0]), float(t["spawn"][1]), bool(t.get("animated")))
               for t in ((tr.get("initial") or {}).get("targets") or {}).get("records") or []]
    return tr, {k: tuple(v) for k, v in ranges.items()}, targets


def cmd_analyze(a: argparse.Namespace) -> int:
    tr, ranges, targets = _trace_context(a.trace)
    if a.geometry:
        geo = gm.load_geometry_json(Path(a.geometry))
    elif a.decomp:
        geo = _decomp_geometry()
    elif tr is not None:
        geo = gm.lines_from_trace_reply(tr.get("initial") or {})
    else:
        raise SystemExit("give --geometry, --decomp or --trace")
    for spec in a.group_range or []:
        gid, x0, x1, y0, y1 = spec.split(":")
        ranges[int(gid)] = (float(x0), float(x1), float(y0), float(y1))
    if a.ecb:
        ecb = analysis.Ecb.parse(a.ecb)
    else:
        vals = gm.mario_ecb_from_decomp(REPO)
        if tr is not None:
            for reply in [tr.get("initial") or {}] + list(tr.get("steps") or [])[:1]:
                coll = ((reply.get("spatial") or {}).get("fighter") or {}).get("coll")
                if coll:
                    vals = tuple(float(v) for v in coll)
        if vals is None:
            raise SystemExit("no ECB: pass --ecb top,center,bottom,width")
        ecb = analysis.Ecb(*vals)
    result = analysis.run_all(geo, ecb, ranges, targets, a.target_half_extent, a.target_reach)
    stem = Path(a.out) if a.out else OUT / f"candidates_{geo.origin.replace(':', '_')}"
    _write_json(stem.with_suffix(".json"), result)
    md = stem.with_suffix(".md")
    md.write_text(analysis.to_markdown(result), encoding="utf-8", newline="\n")
    print(f"wrote {md}")
    for chk, c in result["summary"].items():
        print(f"  {chk:22s} " + ", ".join(f"{k} {v}" for k, v in sorted(c.items())))
    return 0


def cmd_compare(a: argparse.Namespace) -> int:
    geo = gm.load_geometry_json(Path(a.geometry))
    tr = gm.open_json(Path(a.trace))
    native = gm.lines_from_trace_reply(tr.get("initial") or {})
    diffs = gm.compare_lines(geo, native)
    if diffs:
        print("DIFFERENT: the port loaded another line table than the ROM holds (a PC-only geometry difference):")
        for d in diffs:
            print("  " + d)
        return 1
    print(f"SAME: {len(geo.lines)} lines, kinds, groups, vertices and first-vertex flags match the native table")
    return 0


def cmd_detect(a: argparse.Namespace) -> int:
    paths = [Path(p) for p in a.trace or []]
    if a.trace_dir:
        paths += sorted(Path(a.trace_dir).rglob("*.json.gz")) + sorted(Path(a.trace_dir).rglob("*.json"))
    if not paths:
        raise SystemExit("give --trace or --trace-dir")
    geo = gm.load_geometry_json(Path(a.geometry)) if a.geometry else None
    state_table = None
    if a.states:
        if a.states == "decomp":
            sys.path.insert(0, str(HERE / "states"))
            import decomp_states  # tools/glitch/states/decomp_states.py
            state_table = decomp_states.build_table(REPO / "decomp")
        else:
            state_table = json.loads(Path(a.states).read_text(encoding="utf-8"))
    p = detect.Params(snap_threshold=a.snap_threshold, cross_margin=a.cross_margin, body_reach=a.body_reach,
                      weapon_radius=a.weapon_radius, target_half_extent=a.target_half_extent, all_snaps=a.all_snaps,
                      state_table=state_table)
    out = Path(a.out) if a.out else OUT / "events.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    summaries = []
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
            try:
                events, summary = detect.scan(tr, geo, p, src)
            except gm.GeometryError as exc:
                summaries.append({"trace": str(path), "error": str(exc)})
                continue
            for ev in events:
                f.write(json.dumps(ev, separators=(",", ":")) + "\n")
            summaries.append(summary)
    _write_json(out.with_suffix(".summary.json"), summaries)
    total = sum(s.get("events", 0) for s in summaries)
    print(f"wrote {out}: {total} events from {len(summaries)} traces")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("extract")
    s.add_argument("--rom", required=True)
    s.add_argument("--version", choices=sorted(gm.VERSIONS))
    s.add_argument("--header-file", type=int)
    s.add_argument("--out")
    s.add_argument("--no-decomp-check", action="store_true")
    s.add_argument("--no-yaml-check", action="store_true", help="skip the yamls/<version> offset cross-check (synthetic ROMs)")
    s.set_defaults(fn=cmd_extract)
    s = sub.add_parser("decomp")
    s.add_argument("--out")
    s.set_defaults(fn=cmd_decomp)
    s = sub.add_parser("analyze")
    s.add_argument("--geometry")
    s.add_argument("--decomp", action="store_true")
    s.add_argument("--trace", help="lab trace: moving-group ranges, target spawns, ECB (and lines when no --geometry)")
    s.add_argument("--group-range", action="append", help="ID:xmin:xmax:ymin:ymax translate range of a moving group")
    s.add_argument("--ecb")
    s.add_argument("--target-half-extent", type=float, default=150.0)
    s.add_argument("--target-reach", type=float, default=100.0, help="hitbox radius added to the target box")
    s.add_argument("--out", help="output stem (without suffix)")
    s.set_defaults(fn=cmd_analyze)
    s = sub.add_parser("compare")
    s.add_argument("--geometry", required=True)
    s.add_argument("--trace", required=True)
    s.set_defaults(fn=cmd_compare)
    s = sub.add_parser("detect")
    s.add_argument("--trace", action="append")
    s.add_argument("--trace-dir")
    s.add_argument("--geometry")
    s.add_argument("--out")
    s.add_argument("--snap-threshold", type=float, default=1.0)
    s.add_argument("--cross-margin", type=float, default=0.01)
    s.add_argument("--body-reach", type=float, default=500.0)
    s.add_argument("--weapon-radius", type=float, default=100.0)
    s.add_argument("--target-half-extent", type=float, default=150.0)
    s.add_argument("--all-snaps", action="store_true")
    s.add_argument("--states", help="also run the state-machine signals: a table JSON from "
                                    "tools/glitch/states/mario_states.py extract, or 'decomp' to build it now")
    s.set_defaults(fn=cmd_detect)
    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except gm.GeometryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
