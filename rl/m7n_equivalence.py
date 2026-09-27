"""M7n: gameplay equivalence of the executable carrying the `btt_entity_v1` diagnostic.

Reuses the M7f / M7g trace machinery (rl/m7f_trace.py, rl/m7g_equivalence.py: fresh process per trace, raw replies of
status / observe / every step, the native 468-row replay) and compares against the M7g reference sets captured with
executable 1e7c62a0 (runs/m7g_obs/_equiv/post_off: every diagnostic off; post_spatial_diag: SSB64_RL_SPATIAL=1 +
SSB64_RL_TARGET_DIAG=1), read-only.

    capture  --out DIR --variant off|spatial_diag|entity|entity_all [--repeat-tag _r2]
    compare  REF CAND [--ignore entity] [--tag _r2]        every reply / result / native line identical except the
                                                            listed additive objects (and their status booleans)
    validate DIR [DIR ...]                                  parse every entity object; entity invariants; weapons

Variants: off = nothing (strict comparison with M7g post_off proves the executable unchanged with the flag unset);
spatial_diag = the M7g flags (strict comparison with M7g post_spatial_diag proves the M7f / M7g objects unchanged);
entity = SSB64_RL_ENTITY=1 alone (vs post_off, ignoring the entity object); entity_all = all three diagnostics (vs
post_spatial_diag, ignoring the entity object). Writes only below --out / --json. Never trains.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import m7f_trace as mt  # noqa: E402
import m7g_equivalence as me  # noqa: E402
import m7g_spatial as ms  # noqa: E402
import m7n_entity as ne  # noqa: E402

REPO_ROOT = RL_DIR.parent
M7G_OFF = REPO_ROOT / "runs" / "m7g_obs" / "_equiv" / "post_off"
M7G_SPATIAL_DIAG = REPO_ROOT / "runs" / "m7g_obs" / "_equiv" / "post_spatial_diag"
VARIANTS: Dict[str, Dict[str, str]] = {
    "off": {},
    "spatial_diag": {ms.SPATIAL_ENV: "1", mt.TARGET_DIAG_ENV: "1"},
    "entity": {ne.ENTITY_ENV: "1"},
    "entity_all": {ne.ENTITY_ENV: "1", ms.SPATIAL_ENV: "1", mt.TARGET_DIAG_ENV: "1"},
}
ENTITY_KEYS = (ne.REPLY_KEY, ne.STATUS_KEY)


def capture(executable: Path, out: Path, variant: str, **kw: Any) -> Dict[str, Any]:
    """rl/m7g_equivalence.capture with this module's variants (the M7g function reads its VARIANTS table)."""
    saved = dict(me.VARIANTS)
    me.VARIANTS.clear()
    me.VARIANTS.update(VARIANTS)
    try:
        summary = me.capture(executable, out, variant, **kw)
    finally:
        me.VARIANTS.clear()
        me.VARIANTS.update(saved)
    summary["schema"] = "battleship_m7n_entity_trace_set_v1"
    (Path(out) / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    return summary


def _strip(reply: Optional[Mapping[str, Any]], ignore: Sequence[str]) -> Optional[Dict[str, Any]]:
    return None if reply is None else {k: v for k, v in reply.items() if k not in ignore}


def compare(ref_dir: Path, cand_dir: Path, *, ignore: Sequence[str] = (), tag: str = "") -> Dict[str, Any]:
    """Every reference reply equals the candidate reply minus the ignored additive keys (value AND JSON type),
    including status mode booleans, result JSON, exit codes, digests and the native replay lines. With ignore=() the
    comparison is strict."""
    ref_dir, cand_dir = Path(ref_dir), Path(cand_dir)
    report: Dict[str, Any] = {"reference": str(ref_dir), "candidate": str(cand_dir), "ignored_keys": list(ignore),
                              "comparisons": {}}
    for p in sorted(ref_dir.glob("*.json.gz")):
        q = cand_dir / me._tagged(p.name, tag)
        if not q.is_file():
            report["comparisons"][p.name] = {"identical": False, "problems": ["missing in candidate"]}
            continue
        ref, cand = mt.read_trace(p), mt.read_trace(q)
        problems: List[str] = []
        if not mt._typed_equal(ref.get("status"), _strip(cand.get("status"), ignore)):
            problems.append(f"status differs: {ref.get('status')} vs {_strip(cand.get('status'), ignore)}")
        if ne.STATUS_KEY in ignore and cand.get("status", {}).get(ne.STATUS_KEY) is not True:
            problems.append("candidate status lacks entity_diag")
        r = mt.compare_stepping(ref, {**cand, "label": ref.get("label"), "status": ref.get("status"),
                                      "initial": _strip(cand.get("initial"), ignore),
                                      "steps": [_strip(s, ignore) for s in cand.get("steps") or []]},
                                ignore=(), ignore_result=())
        problems += r["problems"]
        if ne.REPLY_KEY in ignore:
            missing = sum(1 for s in [cand.get("initial")] + list(cand.get("steps") or []) if ne.REPLY_KEY not in s)
            if missing:
                problems.append(f"{missing} candidate replies without an entity object")
        report["comparisons"][p.name] = {"identical": not problems, "problems": problems,
                                         "steps_compared": r["steps_compared"]}
    for p in sorted(ref_dir.glob("native*.json")):
        q = cand_dir / me._tagged(p.name, tag)
        if q.is_file():
            report["comparisons"][p.name] = mt.compare_native(json.loads(p.read_text(encoding="utf-8")),
                                                              json.loads(q.read_text(encoding="utf-8")),
                                                              ignore_result_keys=())
    report["all_identical"] = bool(report["comparisons"]) and all(c["identical"] for c in
                                                                   report["comparisons"].values())
    return report


def validate_trace(trace: Mapping[str, Any]) -> Dict[str, Any]:
    """Entity invariants of every reply of one trace (rl/m7n_entity.check_snapshot) plus weapon statistics."""
    problems: List[str] = []
    prev = prev_obs = None
    counts = {"replies": 0, "live": 0, "weapon_rows": 0, "owned_rows": 0, "max_weapon_total": 0, "serials": set(),
              "status_changes": 0, "reset_values": set(), "kinds": set()}
    for i, reply in enumerate([trace["initial"]] + list(trace.get("steps") or [])):
        snap = ne.entity_of(reply)
        obs = reply["observation"]
        counts["replies"] += 1
        counts["live"] += int(snap.live)
        for msg in ne.check_snapshot(snap, obs, prev=prev, prev_observation=prev_obs, jumps_max=2):
            problems.append(f"reply {i} (tick {obs['input_tick']}): {msg}")
        if prev_obs is not None and prev_obs["fighter_status_id"] != obs["fighter_status_id"]:
            counts["status_changes"] += 1
            counts["reset_values"].add(snap.fighter.status_total_tics)
        counts["weapon_rows"] += len(snap.weapons)
        counts["owned_rows"] += sum(w.owned for w in snap.weapons)
        counts["max_weapon_total"] = max(counts["max_weapon_total"], snap.weapon_total)
        counts["serials"].update(w.serial for w in snap.weapons)
        counts["kinds"].update(w.kind for w in snap.weapons)
        prev, prev_obs = snap, obs
    counts["serials"] = len(counts["serials"])
    counts["reset_values"] = sorted(counts["reset_values"])
    counts["kinds"] = sorted(counts["kinds"])
    return {"problems": problems[:50], "problem_count": len(problems), "counts": counts}


def validate(dirs: Sequence[Path]) -> Dict[str, Any]:
    report: Dict[str, Any] = {"sets": {}}
    for d in dirs:
        d = Path(d)
        sets = {p.name: validate_trace(mt.read_trace(p)) for p in sorted(d.glob("*.json.gz"))}
        report["sets"][str(d)] = sets
    report["all_valid"] = all(s["problem_count"] == 0 for sets in report["sets"].values() for s in sets.values())
    return report


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture")
    c.add_argument("--exe", type=Path, default=mt.DEFAULT_EXE)
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--variant", choices=sorted(VARIANTS), required=True)
    c.add_argument("--modes", default=",".join(mt.MODES))
    c.add_argument("--no-fixtures", action="store_true")
    c.add_argument("--no-native", action="store_true")
    c.add_argument("--repeat-tag", default="")
    k = sub.add_parser("compare")
    k.add_argument("reference", type=Path)
    k.add_argument("candidate", type=Path)
    k.add_argument("--ignore", default="", help="'entity' to ignore the additive entity object and status key")
    k.add_argument("--tag", default="")
    k.add_argument("--json", type=Path)
    v = sub.add_parser("validate")
    v.add_argument("dirs", type=Path, nargs="+")
    v.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "capture":
        s = capture(args.exe, args.out, args.variant, modes=args.modes.split(","), fixtures=not args.no_fixtures,
                    native=not args.no_native, repeat_tag=args.repeat_tag)
        print(json.dumps({k: s[k] for k in ("executable_sha256", "variant", "leftover_battleship")}))
        return 0
    if args.cmd == "compare":
        ignore = ENTITY_KEYS if args.ignore == "entity" else ()
        r = compare(args.reference, args.candidate, ignore=ignore, tag=args.tag)
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(r, indent=1) + "\n", encoding="utf-8")
        n = sum(c["identical"] for c in r["comparisons"].values())
        print(f"{'IDENTICAL' if r['all_identical'] else 'DIFFERENT'}: {n}/{len(r['comparisons'])}")
        for name, c in r["comparisons"].items():
            if not c["identical"]:
                print(f"  {name}: {c['problems'][:2]}")
        return 0 if r["all_identical"] else 1
    r = validate(args.dirs)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(r, indent=1, default=str) + "\n", encoding="utf-8")
    print(f"{'VALID' if r['all_valid'] else 'PROBLEMS'}")
    for d, sets in r["sets"].items():
        for name, s in sets.items():
            if s["problem_count"]:
                print(f"  {Path(d).name}/{name}: {s['problems'][:2]}")
    return 0 if r["all_valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
