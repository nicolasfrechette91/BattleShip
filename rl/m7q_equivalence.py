"""M7q: gameplay equivalence of the executable carrying the `btt_input_state_v1` diagnostic, and the action oracle.

Reuses the M7f / M7g / M7n trace machinery (fresh process per trace, raw replies of status / observe / every step, the
native 468-row replay) against the pinned reference sets (runs/m7g_obs/_equiv/post_off, runs/m7n/_equiv/entity_all),
read-only.

    capture  --out DIR --variant off|entity_all|input|input_all [--repeat-tag _r2]
    compare  REF CAND [--ignore input|input_entity] [--tag _r2]   every reply / result / native line identical except
                                                                  the listed additive objects (and their status keys)
    validate DIR [DIR ...] [--json F]                             parse every input object; input invariants; the
                                                                  ACTION ORACLE (see below); tick-0 record

Variants: off = nothing (strict vs M7g post_off); entity_all = the M7n flags (strict vs M7n entity_all, entity object
included); input = SSB64_RL_INPUT=1 alone (vs post_off ignoring the input object); input_all = all four diagnostics
(vs M7n entity_all ignoring only the input object). Writes only below --out / --json. Never trains.

The oracle (docs/rl_observation_v4_proposal_2026-09-28.md V4 / V5): from the SUBMITTED ACTIONS ALONE (the TAS rows or
the pinned artifact's recorded actions, re-read by trace label) predict per tick the folded button_hold, the tap and
release edges (OR-accumulated across hitlag, read from the entity object), the stick, the tap counters (20-band rule
with the forced 254 at the observed status transitions: jump, aerial jump, dash, pass, fast-fall edge) and the Z timer
(0 on a Z / R edge, +1, 65536 at an observed aerial-attack entry); every prediction must equal the native value.
Rules the first validation pass added (all source-backed): (1) on the tick the fighter's OWN attack lands
(hitlag_tics rises from 0), the game clears that tick's tap and release edges after setting hitlag
(ftmain.c:4157 in ftMainProcParams), so the press of the hit tick itself is lost, not delayed; (2) a jump that fires
in proc_update (KneeBend -> JumpF/B, tap_stick_y forced 254) can be followed in the same tick's proc_interrupt by an
aerial attack / special, so any KneeBend -> airborne transition forces tap_stick_y; (3) a fast fall set in
proc_physics and a heavy landing in proc_map of the same tick clear is_fastfall again, so a LandingHeavy entry accepts
either the natural counter or 254; (4) the hitlag countdown precedes the animation step, so the animation advances
again on the tick whose previous hitlag_tics was 1. Animation freeze is checked for previous hitlag_tics >= 2;
status_total_tics must advance on every hitlag tick. The oracle stops at the first reply whose status is below
nFTCommonStatusControlStart (a native failure's dead / rebirth statuses re-initialise the input block); (5) the Turn
status re-injects an A or B press made on its first frame as a tap on a later frame (ftcommonturn.c
ftCommonTurnProcInterrupt: `button_tap |= turn.button_mask`), so while the previous status is Turn an observed tap may
carry extra A / B bits that are currently held. Nothing here reads, logs or compares native RNG state.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import m7f_trace as mt  # noqa: E402
import m7g_equivalence as me  # noqa: E402
import m7g_spatial as ms  # noqa: E402
import m7n_entity as ne  # noqa: E402
import m7n_equivalence as mne  # noqa: E402
import m7q_input as mi  # noqa: E402
import m7q_status_table as st2  # noqa: E402

REPO_ROOT = RL_DIR.parent
M7G_OFF = mne.M7G_OFF
M7N_ENTITY_ALL = REPO_ROOT / "runs" / "m7n" / "_equiv" / "entity_all"
VARIANTS: Dict[str, Dict[str, str]] = {
    "off": {},
    "entity_all": dict(mne.VARIANTS["entity_all"]),
    "input": {mi.INPUT_ENV: "1"},
    "input_all": {mi.INPUT_ENV: "1", ne.ENTITY_ENV: "1", ms.SPATIAL_ENV: "1", mt.TARGET_DIAG_ENV: "1"},
}
INPUT_KEYS = (mi.REPLY_KEY, mi.STATUS_KEY)
INPUT_ENTITY_KEYS = INPUT_KEYS + mne.ENTITY_KEYS

# Status ids (common range) whose ENTRY forces a tap counter to 254 (ftcommonjump.c:98, ftcommonjumpaerial.c:172,
# ftcommondash.c:120, ftcommonpass.c:31) and the aerial attacks whose entry sets the Z timer to 65536
# (ftcommonattackair.c:220). Looked up by enumerator name in the v2 table so no id is typed by hand.
FORCE_TAP_Y_ENTRIES = ("nFTCommonStatusJumpF", "nFTCommonStatusJumpB", "nFTCommonStatusJumpAerialF",
                       "nFTCommonStatusJumpAerialB", "nFTCommonStatusPass", "nFTCommonStatusGuardPass")
FORCE_TAP_X_ENTRIES = ("nFTCommonStatusDash",)
KNEEBEND_STATUSES = ("nFTCommonStatusKneeBend", "nFTCommonStatusGuardKneeBend")
LANDING_HEAVY = ("nFTCommonStatusLandingHeavy",)
CONTROL_START = "nFTCommonStatusControlStart"
TURN_STATUSES = ("nFTCommonStatusTurn",)


def _ids_by_name(table: Dict[str, Any], names: Sequence[str]) -> Tuple[int, ...]:
    by_name = {n: int(i) for i, n in table["common_names"].items()}
    missing = [n for n in names if n not in by_name]
    if missing:
        raise ValueError(f"enumerators {missing} not in the v2 table")
    return tuple(by_name[n] for n in names)


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
    summary["schema"] = "battleship_m7q_input_trace_set_v1"
    (Path(out) / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    return summary


def _strip(reply: Optional[Mapping[str, Any]], ignore: Sequence[str]) -> Optional[Dict[str, Any]]:
    return None if reply is None else {k: v for k, v in reply.items() if k not in ignore}


def compare(ref_dir: Path, cand_dir: Path, *, ignore: Sequence[str] = (), tag: str = "") -> Dict[str, Any]:
    """Every reference reply equals the candidate reply minus the ignored additive keys (value AND JSON type); with
    ignore=() the comparison is strict. When the input keys are ignored, every candidate reply must carry the input
    object and the status must say input_diag: true."""
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
        for reply_key, status_key in ((mi.REPLY_KEY, mi.STATUS_KEY), (ne.REPLY_KEY, ne.STATUS_KEY)):
            if status_key in ignore and cand.get("status", {}).get(status_key) is not True:
                problems.append(f"candidate status lacks {status_key}")
            if reply_key in ignore:
                missing = sum(1 for s in [cand.get("initial")] + list(cand.get("steps") or []) if reply_key not in s)
                if missing:
                    problems.append(f"{missing} candidate replies without a {reply_key} object")
        r = mt.compare_stepping(ref, {**cand, "label": ref.get("label"), "status": ref.get("status"),
                                      "initial": _strip(cand.get("initial"), ignore),
                                      "steps": [_strip(s, ignore) for s in cand.get("steps") or []]},
                                ignore=(), ignore_result=())
        problems += r["problems"]
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


def trace_actions(trace: Mapping[str, Any]) -> List[mt.Action]:
    """The actions the trace submitted, re-read by label (never stored in the trace itself)."""
    label = str(trace.get("label") or "")
    base = label[:-3] if label.endswith("_r2") else label
    if base.startswith("tas_"):
        acts = mt.tas_actions()
    elif base.startswith("fx_"):
        rel = dict(mt.FIXTURE_ARTIFACTS).get(base[3:])
        if rel is None:
            raise ValueError(f"trace label {label!r}: unknown fixture artifact")
        acts, _md = mt.artifact_actions(REPO_ROOT / rel)
    else:
        raise ValueError(f"trace label {label!r}: cannot re-derive its actions")
    submitted = int(trace.get("submitted") or len(trace.get("steps") or []))
    acts = acts[:submitted]
    if mt.action_digest(acts, [s["consumed_tick"] for s in trace["steps"][:submitted]]) != trace.get("action_digest"):
        raise ValueError(f"trace label {label!r}: re-derived actions do not match the trace's action digest")
    return acts


def _clamp80(v: int) -> int:
    return max(-80, min(80, int(v)))


def validate_trace(trace: Mapping[str, Any], *, table: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Input invariants of every reply plus the action oracle when the actions can be re-derived. Entity-dependent
    checks (hitlag accumulation, animation freeze) run only when the entity object is present."""
    table = table or st2.load_table()
    force_y = set(_ids_by_name(table, FORCE_TAP_Y_ENTRIES))
    force_x = set(_ids_by_name(table, FORCE_TAP_X_ENTRIES))
    aerials = set(st2.aerial_attack_ids(table))
    kneebend = set(_ids_by_name(table, KNEEBEND_STATUSES))
    landing_heavy = set(_ids_by_name(table, LANDING_HEAVY))
    control_start = _ids_by_name(table, (CONTROL_START,))[0]
    turn = set(_ids_by_name(table, TURN_STATUSES))
    problems: List[str] = []
    replies = [trace["initial"]] + list(trace.get("steps") or [])
    try:
        actions: Optional[List[mt.Action]] = trace_actions(trace)
    except Exception as exc:   # noqa: BLE001 -- reported, never hidden
        actions = None
        problems.append(f"oracle skipped: {exc}")
    has_entity = all(ne.REPLY_KEY in r for r in replies)
    init = mi.input_of(replies[0])
    tick0 = {"tics_since_last_z": init.tics_since_last_z, "button_hold": init.button_hold, "stick": [init.stick_x, init.stick_y],
             "taps": [init.tap_stick_x, init.tap_stick_y], "anim_frame": init.anim_frame, "anim_speed": init.anim_speed,
             "motion_flag1": init.motion_flag1, "status": replies[0]["observation"]["fighter_status_id"]}
    counts = {"replies": len(replies), "oracle_ticks": 0, "hitlag_ticks": 0, "forced_tap_y": 0, "forced_tap_x": 0,
              "aerial_entries": 0, "z_taps": 0, "r_presses": 0, "speeds": set(), "status_changes": 0, "anim_freeze_checks": 0,
              "hit_ticks": 0, "jump_transitions": 0, "turn_reinjections": 0, "oracle_stopped_at": None}
    prev = init
    prev_o = replies[0]["observation"]
    prev_en = ne.entity_of(replies[0]) if has_entity else None
    for i, reply in enumerate(replies[1:], start=1):
        snap = mi.input_of(reply)
        o = reply["observation"]
        for m in mi.check_snapshot(snap, o, prev=prev, prev_observation=prev_o):
            problems.append(f"reply {i} (tick {o['input_tick']}): {m}")
        en = ne.entity_of(reply) if has_entity else None
        if not (snap.live and snap.valid):
            prev, prev_o, prev_en = snap, o, en
            continue
        status, prev_status = int(o["fighter_status_id"]), int(prev_o["fighter_status_id"])
        if status != prev_status:
            counts["status_changes"] += 1
        counts["speeds"].add(round(float(snap.anim_speed), 4))
        if status < control_start and counts["oracle_stopped_at"] is None:
            counts["oracle_stopped_at"] = i - 1   # a dead / rebirth status: the input block is re-initialised natively
        if actions is not None and i - 1 < len(actions) and counts["oracle_stopped_at"] is None:
            buttons, sx, sy, _expected = actions[i - 1]
            counts["oracle_ticks"] += 1
            hold = mi.expected_hold_word(buttons)
            if buttons & mi.BUTTON_R:
                counts["r_presses"] += 1
            if snap.button_hold != hold:
                problems.append(f"tick {i - 1}: button_hold 0x{snap.button_hold:04x} != folded action 0x{hold:04x}")
            ex_sx, ex_sy = _clamp80(sx), _clamp80(sy)
            if (snap.stick_x, snap.stick_y) != (ex_sx, ex_sy):
                problems.append(f"tick {i - 1}: stick {(snap.stick_x, snap.stick_y)} != action {(ex_sx, ex_sy)}")
            tap_mask = mi.expected_taps(prev.button_hold, hold)
            rel_mask = mi.expected_releases(prev.button_hold, hold)
            in_hitlag = prev_en is not None and prev_en.fighter.hitlag_tics > 0
            if in_hitlag:
                counts["hitlag_ticks"] += 1
                tap_mask |= prev.button_tap
                rel_mask |= prev.button_release
            hit_tick = (en is not None and prev_en is not None and en.fighter.hitlag_tics > 0
                        and prev_en.fighter.hitlag_tics == 0)
            if hit_tick:
                counts["hit_ticks"] += 1
                tap_mask = rel_mask = 0   # ftmain.c:4157: the landing hit clears this tick's edges after setting hitlag
            if has_entity and snap.button_tap != tap_mask:
                extra = snap.button_tap & ~tap_mask & 0xFFFF
                reinjected = (prev_status in turn and extra != 0 and (extra & ~(mi.BUTTON_A | mi.BUTTON_B)) == 0
                              and (extra & hold) == extra and (snap.button_tap & tap_mask) == tap_mask)
                if reinjected:
                    counts["turn_reinjections"] += 1   # ftcommonturn.c: the Turn status re-injects its first-frame A / B press
                else:
                    problems.append(f"tick {i - 1}: button_tap 0x{snap.button_tap:04x} != expected 0x{tap_mask:04x} (hitlag {in_hitlag})")
            if has_entity and snap.button_release != rel_mask:
                problems.append(f"tick {i - 1}: button_release 0x{snap.button_release:04x} != expected 0x{rel_mask:04x}")
            # tap counters: the band rule from the previous tick's stick (the game's stick_prev) and this tick's,
            # then the forced 254 at an observed entry of a forcing status / the fast-fall edge (same tick).
            ex_tx = mi.step_tap_counter(prev.tap_stick_x, prev.stick_x, ex_sx)
            ex_ty = mi.step_tap_counter(prev.tap_stick_y, prev.stick_y, ex_sy)
            if status in force_x and status != prev_status:
                ex_tx = mi.TAP_MAX
                counts["forced_tap_x"] += 1
            forced_y = (status in force_y and status != prev_status)
            if en is not None and prev_en is not None and en.fighter.fastfall and not prev_en.fighter.fastfall:
                forced_y = True
            if prev_status in kneebend and status not in kneebend and int(o["ground_air_state"]) != 0:
                forced_y = True   # the jump fired in proc_update; a later transition of the same tick hid JumpF/B
                counts["jump_transitions"] += 1
            if forced_y:
                ex_ty = mi.TAP_MAX
                counts["forced_tap_y"] += 1
            accept_y = {ex_ty}
            if status in landing_heavy and status != prev_status:
                accept_y.add(mi.TAP_MAX)   # a fast fall set and landed in the same tick leaves no fastfall edge to see
            if snap.tap_stick_x != ex_tx or snap.tap_stick_y not in accept_y:
                problems.append(f"tick {i - 1}: tap counters {(snap.tap_stick_x, snap.tap_stick_y)} != oracle "
                                f"{(ex_tx, sorted(accept_y))} (status {prev_status} -> {status})")
            # Z timer: 0 on a Z / R edge this tick, else +1 capped; 65536 at an observed aerial-attack entry.
            z_edge = bool((hold & ~prev.button_hold) & mi.BUTTON_Z) or (in_hitlag and bool(prev.button_tap & mi.BUTTON_Z))
            if has_entity or not in_hitlag:
                ex_z = 0 if z_edge else min(prev.tics_since_last_z + 1, mi.Z_TIMER_MAX)
                if status in aerials and status != prev_status:
                    ex_z = mi.Z_TIMER_MAX
                    counts["aerial_entries"] += 1
                if z_edge:
                    counts["z_taps"] += 1
                if snap.tics_since_last_z != ex_z:
                    problems.append(f"tick {i - 1}: tics_since_last_z {snap.tics_since_last_z} != oracle {ex_z}")
            # animation freeze during hitlag (the countdown precedes the animation step: frozen while the previous
            # reply's hitlag_tics >= 2); status_total_tics still advancing on every hitlag tick
            if in_hitlag and status == prev_status and en is not None and prev_en is not None:
                if prev_en.fighter.hitlag_tics >= 2:
                    counts["anim_freeze_checks"] += 1
                    if snap.anim_frame != prev.anim_frame:
                        problems.append(f"tick {i - 1}: anim_frame advanced {prev.anim_frame} -> {snap.anim_frame} during hitlag")
                if en.fighter.status_total_tics != prev_en.fighter.status_total_tics + 1:
                    problems.append(f"tick {i - 1}: status_total_tics did not advance during hitlag")
        prev, prev_o, prev_en = snap, o, en
    counts["speeds"] = sorted(counts["speeds"])
    return {"problems": problems[:60], "problem_count": len(problems), "counts": counts, "tick0": tick0,
            "has_entity": has_entity, "oracle": actions is not None}


def validate(dirs: Sequence[Path]) -> Dict[str, Any]:
    table = st2.load_table()
    report: Dict[str, Any] = {"sets": {}}
    for d in dirs:
        d = Path(d)
        report["sets"][str(d)] = {p.name: validate_trace(mt.read_trace(p), table=table) for p in sorted(d.glob("*.json.gz"))}
    report["all_valid"] = all(s["problem_count"] == 0 and s["oracle"] for sets in report["sets"].values()
                              for s in sets.values())
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
    k.add_argument("--ignore", default="", help="'input' or 'input_entity' (the additive objects and status keys)")
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
        ignore = INPUT_KEYS if args.ignore == "input" else INPUT_ENTITY_KEYS if args.ignore == "input_entity" else ()
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
            if s["problem_count"] or not s["oracle"]:
                print(f"  {Path(d).name}/{name}: {s['problems'][:3]}")
    return 0 if r["all_valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
