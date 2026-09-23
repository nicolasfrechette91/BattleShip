"""M7f: the `btt_target_identity_v1` diagnostic contract, Python side.

Pure functions only (no process, no socket): strict parsing of the native `targets` object (see
docs/rl_target_identity_m7f.md and port/rl/rl.h RLTargetDiag), per-reply validation against the paired observation,
loss-less derivation of target-break events from consecutive post-update masks, and descriptive stage-region labels
for natively measured positions.

The diagnostic is never a policy input: nothing here is imported by the Gym/SB3 stack, the 15-value
`btt_policy_obs_v1` adapter or the reward contracts.

Self-test:  python rl/m7f_targets.py --self-test
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

CONTRACT_ID = "btt_target_identity_v1"
TARGET_SCHEMA = 1
DIAG_ENV = "SSB64_RL_TARGET_DIAG"
STATUS_KEY = "target_diag"
REPLY_KEY = "targets"
RESULT_KEY = "target_identity"
TARGET_COUNT = 10
FULL_MASK = (1 << TARGET_COUNT) - 1

ANOMALY_BITS = {
    0: "spawn_overflow",
    1: "unknown_break",
    2: "repeat_break",
    3: "count_guard",
    4: "link_mismatch",
}

TOP_KEYS = ("contract", "target_schema", "input_tick", "scene_active", "scene_entries", "spawn_count",
            "remaining_mask", "break_count", "anomaly_flags", "link_checked", "link_live_targets", "link_unmatched",
            "records")
GAME_STATUS_GO = 1
RECORD_KEYS = ("id", "animated", "spawn", "break_order", "break_input_tick", "break_time_passed", "break")

# Stage geometry of Mario's Bonus 1 map (relocData file 124 MPVertexData, decomp/src/relocData/
# 124_GRBonus1MarioFile2.c): the tall wall spans x -2100..-1800 (y -2850..3000); the start floor spans x -1800..2100 at
# y -2550 with the 1P spawn at (0, -2547); a raised block starts at x 2100; the moving platform is at x 2700.
WALL_LEFT_FACE_X = -2100.0
WALL_RIGHT_FACE_X = -1800.0
RIGHT_BLOCK_X = 2100.0
REGIONS = ("left_of_wall", "central", "right", "upper_right_moving")


class TargetContractError(ValueError):
    """The reply does not carry a valid btt_target_identity_v1 object (old executable, flag off, wrong schema)."""


@dataclass(frozen=True)
class TargetRecord:
    id: int
    animated: int
    spawn: Tuple[float, float, float]
    break_order: int
    break_input_tick: int
    break_time_passed: int
    break_pos: Tuple[float, float, float]


@dataclass(frozen=True)
class TargetSnapshot:
    input_tick: int
    scene_active: int
    scene_entries: int
    spawn_count: int
    remaining_mask: int
    break_count: int
    anomaly_flags: int
    link_checked: int
    link_live_targets: int
    link_unmatched: int
    records: Tuple[TargetRecord, ...]

    @property
    def remaining_ids(self) -> List[int]:
        return mask_ids(self.remaining_mask)

    @property
    def broken_mask(self) -> int:
        """Derived, never transmitted: spawned targets minus the authoritative remaining mask."""
        return ((1 << self.spawn_count) - 1) & ~self.remaining_mask


def mask_ids(mask: int) -> List[int]:
    return [i for i in range(TARGET_COUNT) if mask & (1 << i)]


def popcount(mask: int) -> int:
    return bin(mask & FULL_MASK).count("1")


def anomaly_names(flags: int) -> List[str]:
    return [name for bit, name in ANOMALY_BITS.items() if flags & (1 << bit)] + \
           ([f"unknown_bits_0x{flags & ~0x1F:x}"] if flags & ~0x1F else [])


def _int(obj: Mapping[str, Any], key: str) -> int:
    v = obj.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise TargetContractError(f"{key} must be an integer, got {v!r}")
    return v


def _vec(obj: Mapping[str, Any], key: str) -> Tuple[float, float, float]:
    v = obj.get(key)
    if not isinstance(v, list) or len(v) != 3 or not all(isinstance(x, (int, float)) and not isinstance(x, bool)
                                                         for x in v):
        raise TargetContractError(f"{key} must be [x, y, z], got {v!r}")
    return float(v[0]), float(v[1]), float(v[2])


def parse_targets(obj: Any) -> TargetSnapshot:
    """Strict parse of a reply's `targets` object. Raises TargetContractError on any deviation."""
    if not isinstance(obj, dict):
        raise TargetContractError(f"'{REPLY_KEY}' missing or not an object (diagnostic off or pre-M7f executable)")
    if obj.get("contract") != CONTRACT_ID:
        raise TargetContractError(f"unsupported target contract {obj.get('contract')!r} (expected {CONTRACT_ID})")
    if _int(obj, "target_schema") != TARGET_SCHEMA:
        raise TargetContractError(f"unsupported target_schema {obj.get('target_schema')!r}")
    if set(obj) != set(TOP_KEYS):
        raise TargetContractError(f"targets keys differ: missing={sorted(set(TOP_KEYS) - set(obj))} "
                                  f"extra={sorted(set(obj) - set(TOP_KEYS))}")
    spawn_count = _int(obj, "spawn_count")
    if not 0 <= spawn_count <= TARGET_COUNT:
        raise TargetContractError(f"spawn_count {spawn_count} out of range")
    recs = obj.get("records")
    if not isinstance(recs, list) or len(recs) != spawn_count:
        raise TargetContractError(f"records must be a list of spawn_count={spawn_count} entries")
    records: List[TargetRecord] = []
    for i, r in enumerate(recs):
        if not isinstance(r, dict) or set(r) != set(RECORD_KEYS):
            raise TargetContractError(f"record {i} keys differ: {sorted(r) if isinstance(r, dict) else r!r}")
        if _int(r, "id") != i:
            raise TargetContractError(f"record {i} has id {r.get('id')!r}; records must be in ID order")
        records.append(TargetRecord(id=i, animated=_int(r, "animated"), spawn=_vec(r, "spawn"),
                                    break_order=_int(r, "break_order"), break_input_tick=_int(r, "break_input_tick"),
                                    break_time_passed=_int(r, "break_time_passed"), break_pos=_vec(r, "break")))
    mask = _int(obj, "remaining_mask")
    if mask & ~((1 << spawn_count) - 1):
        raise TargetContractError(f"remaining_mask 0x{mask:x} has bits beyond spawn_count {spawn_count}")
    return TargetSnapshot(input_tick=_int(obj, "input_tick"), scene_active=_int(obj, "scene_active"),
                          scene_entries=_int(obj, "scene_entries"), spawn_count=spawn_count, remaining_mask=mask,
                          break_count=_int(obj, "break_count"), anomaly_flags=_int(obj, "anomaly_flags"),
                          link_checked=_int(obj, "link_checked"), link_live_targets=_int(obj, "link_live_targets"),
                          link_unmatched=_int(obj, "link_unmatched"), records=tuple(records))


def require_diag_status(status_reply: Mapping[str, Any]) -> None:
    if status_reply.get(STATUS_KEY) is not True:
        raise TargetContractError(f"status reports {STATUS_KEY}={status_reply.get(STATUS_KEY)!r}: the executable does "
                                  f"not provide {CONTRACT_ID} or {DIAG_ENV}=1 was not effective")


def region_of(record: TargetRecord) -> str:
    x = record.spawn[0]
    if record.animated:
        return "upper_right_moving"
    if x < WALL_LEFT_FACE_X:
        return "left_of_wall"
    if WALL_RIGHT_FACE_X < x < RIGHT_BLOCK_X:
        return "central"
    if x > RIGHT_BLOCK_X:
        return "right"
    return "unclassified"


def mapping_of(snapshot: TargetSnapshot) -> List[Dict[str, Any]]:
    """The initial ID -> position -> region table of one episode (static fields only)."""
    return [{"id": r.id, "animated": r.animated, "spawn": list(r.spawn), "region": region_of(r)}
            for r in snapshot.records]


def static_signature(snapshot: TargetSnapshot) -> str:
    """Stable JSON of the static part of the table (IDs, spawn positions, animated flags); for cross-run equality."""
    return json.dumps(mapping_of(snapshot), sort_keys=True, separators=(",", ":"))


# -- per-episode validation and event derivation ------------------------------------------------------


@dataclass
class TraceCheck:
    problems: List[str] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    initial: Optional[TargetSnapshot] = None
    final: Optional[TargetSnapshot] = None
    mask_changes: List[Dict[str, Any]] = field(default_factory=list)
    snapshots_checked: int = 0

    def fail(self, message: str) -> None:
        if len(self.problems) < 50:
            self.problems.append(message)

    @property
    def ok(self) -> bool:
        return not self.problems


def check_snapshot(where: str, snap: TargetSnapshot, observation: Mapping[str, Any], chk: TraceCheck, *,
                   expect_spawned: bool = True) -> None:
    """Invariants of one reply: pairing stamp, mask vs targets_remaining, link walk, no anomalies."""
    chk.snapshots_checked += 1
    if snap.input_tick != observation.get("input_tick"):
        chk.fail(f"{where}: targets.input_tick {snap.input_tick} != observation.input_tick "
                 f"{observation.get('input_tick')} (pairing)")
    if snap.anomaly_flags:
        chk.fail(f"{where}: anomaly_flags {anomaly_names(snap.anomaly_flags)}")
    if expect_spawned:
        if snap.spawn_count != TARGET_COUNT:
            chk.fail(f"{where}: spawn_count {snap.spawn_count} != {TARGET_COUNT}")
        if snap.scene_entries != 1:
            chk.fail(f"{where}: scene_entries {snap.scene_entries} != 1")
    if observation.get("btt_active") == 1:
        if snap.scene_active != 1:
            chk.fail(f"{where}: scene_active {snap.scene_active} while btt_active 1")
        if popcount(snap.remaining_mask) != observation.get("targets_remaining"):
            chk.fail(f"{where}: popcount(mask)={popcount(snap.remaining_mask)} != targets_remaining "
                     f"{observation.get('targets_remaining')}")
        if snap.link_checked:
            if snap.link_live_targets != popcount(snap.remaining_mask) or snap.link_unmatched != 0:
                chk.fail(f"{where}: link walk live={snap.link_live_targets} unmatched={snap.link_unmatched} vs mask "
                         f"{popcount(snap.remaining_mask)}")
        elif observation.get("game_status") == GAME_STATUS_GO:
            # the cross-check may only be skipped once the scene task has ended (objects ejected), never in play
            chk.fail(f"{where}: link cross-check skipped during Go status")
    elif snap.link_checked:
        chk.fail(f"{where}: link cross-check ran outside the BTT scene")
    broken = [r for r in snap.records if r.break_order]
    if len(broken) != snap.break_count or snap.break_count != popcount(snap.broken_mask):
        chk.fail(f"{where}: break_count {snap.break_count}, records with break_order {len(broken)}, broken bits "
                 f"{popcount(snap.broken_mask)}")
    if sorted(r.break_order for r in broken) != list(range(1, len(broken) + 1)):
        chk.fail(f"{where}: break_order values {sorted(r.break_order for r in broken)} are not 1..{len(broken)}")
    for r in snap.records:
        in_mask = bool(snap.remaining_mask & (1 << r.id))
        if in_mask == bool(r.break_order):
            chk.fail(f"{where}: target {r.id} mask bit {int(in_mask)} disagrees with break_order {r.break_order}")


def check_trace(initial_reply: Mapping[str, Any], step_replies: Sequence[Mapping[str, Any]]) -> TraceCheck:
    """Validate a whole episode (the tick-0 observe reply plus every step reply, in order) and derive the break
    events losslessly from consecutive masks. Never raises for content problems; returns them."""
    chk = TraceCheck()
    try:
        prev = parse_targets(initial_reply.get(REPLY_KEY))
    except TargetContractError as exc:
        chk.fail(f"initial: {exc}")
        return chk
    chk.initial = prev
    init_obs = initial_reply.get("observation") or {}
    check_snapshot("initial", prev, init_obs, chk)
    if prev.remaining_mask != FULL_MASK or prev.break_count != 0:
        chk.fail(f"initial: remaining_mask 0x{prev.remaining_mask:x} break_count {prev.break_count} (expected all "
                 "ten active, none broken)")
    static0 = static_signature(prev)
    seen_orders: Dict[int, int] = {}
    for i, reply in enumerate(step_replies):
        where = f"step {i}"
        try:
            snap = parse_targets(reply.get(REPLY_KEY))
        except TargetContractError as exc:
            chk.fail(f"{where}: {exc}")
            return chk
        obs = reply.get("observation") or {}
        consumed = reply.get("consumed_tick")
        check_snapshot(where, snap, obs, chk)
        if static_signature(snap) != static0:
            chk.fail(f"{where}: static target table changed (IDs / spawn positions / animated flags)")
        if snap.remaining_mask & ~prev.remaining_mask:
            chk.fail(f"{where}: target(s) {mask_ids(snap.remaining_mask & ~prev.remaining_mask)} became active again")
        for r_prev, r in zip(prev.records, snap.records):
            if r_prev.break_order and (r_prev.break_order, r_prev.break_input_tick, r_prev.break_time_passed,
                                       r_prev.break_pos) != (r.break_order, r.break_input_tick,
                                                             r.break_time_passed, r.break_pos):
                chk.fail(f"{where}: break record of target {r.id} changed after its break")
        cleared = prev.remaining_mask & ~snap.remaining_mask
        if cleared:
            ids = mask_ids(cleared)
            chk.mask_changes.append({"step_index": i, "consumed_tick": consumed, "input_tick": obs.get("input_tick"),
                                     "remaining_mask": snap.remaining_mask, "cleared_ids": ids})
            for tid in ids:
                rec = snap.records[tid]
                ev = {"target_id": tid, "consumed_tick": consumed, "input_tick": obs.get("input_tick"),
                      "step_index": i, "break_order": rec.break_order,
                      "native_break_input_tick": rec.break_input_tick,
                      "native_break_time_passed": rec.break_time_passed, "break_pos": list(rec.break_pos)}
                if rec.break_input_tick != obs.get("input_tick") or consumed is None or \
                        rec.break_input_tick != consumed + 1:
                    chk.fail(f"{where}: target {tid} native break_input_tick {rec.break_input_tick} vs consumed "
                             f"{consumed} / input_tick {obs.get('input_tick')}")
                if rec.break_time_passed != obs.get("time_passed"):
                    chk.fail(f"{where}: target {tid} native break_time_passed {rec.break_time_passed} vs "
                             f"observation time_passed {obs.get('time_passed')}")
                if rec.break_order in seen_orders:
                    chk.fail(f"{where}: break_order {rec.break_order} reused by targets {seen_orders[rec.break_order]} "
                             f"and {tid}")
                seen_orders[rec.break_order] = tid
                chk.events.append(ev)
        prev = snap
    chk.final = prev
    orders = [e["break_order"] for e in chk.events]
    if orders != sorted(orders):
        chk.fail(f"events are not in native break order: {orders}")
    # Same-tick breaks happen in link (= spawn) order inside one update; the native order must reflect that.
    by_tick: Dict[Any, List[Dict[str, Any]]] = {}
    for e in chk.events:
        by_tick.setdefault(e["consumed_tick"], []).append(e)
    for tick, evs in by_tick.items():
        if len(evs) > 1 and [e["target_id"] for e in sorted(evs, key=lambda e: e["break_order"])] != \
                sorted(e["target_id"] for e in evs):
            chk.fail(f"same-tick breaks at {tick} not in ascending ID order: {[(e['target_id'], e['break_order']) for e in evs]}")
    return chk


def break_ticks(events: Sequence[Mapping[str, Any]]) -> List[int]:
    """The historical `target_break_ticks` representation (consumed tick repeated per target)."""
    return sorted(int(e["consumed_tick"]) for e in events)


# -- self-test ----------------------------------------------------------------------------------------


def _synthetic(mask: int, breaks: Mapping[int, Tuple[int, int]], input_tick: int, *, anomalies: int = 0,
               link: Optional[int] = None, link_checked: int = 1) -> Dict[str, Any]:
    recs = []
    for i in range(TARGET_COUNT):
        order, bit = breaks.get(i, (0, 0))
        recs.append({"id": i, "animated": 1 if i == 2 else 0, "spawn": [float(i * 100 - 3500), 0.0, 0.0],
                     "break_order": order, "break_input_tick": bit, "break_time_passed": max(0, bit - 1),
                     "break": [0.0, 0.0, 0.0]})
    live = (popcount(mask) if link is None else link) if link_checked else 0
    return {"contract": CONTRACT_ID, "target_schema": 1, "input_tick": input_tick, "scene_active": 1,
            "scene_entries": 1, "spawn_count": TARGET_COUNT, "remaining_mask": mask, "break_count": len(breaks),
            "anomaly_flags": anomalies, "link_checked": link_checked, "link_live_targets": live, "link_unmatched": 0,
            "records": recs}


def _obs(input_tick: int, remaining: int, game_status: int = GAME_STATUS_GO) -> Dict[str, Any]:
    # the synthetic native records set break_time_passed = input_tick - 1, as time_passed does while the timer runs
    return {"input_tick": input_tick, "btt_active": 1, "targets_remaining": remaining, "game_status": game_status,
            "time_passed": max(0, input_tick - 1)}


def self_test() -> int:
    bad: List[str] = []

    def expect(cond: bool, name: str) -> None:
        if not cond:
            bad.append(name)

    # parse errors
    for name, obj in [("missing", None), ("contract", {**_synthetic(FULL_MASK, {}, 0), "contract": "x"}),
                      ("schema", {**_synthetic(FULL_MASK, {}, 0), "target_schema": 2}),
                      ("extra_key", {**_synthetic(FULL_MASK, {}, 0), "extra": 1}),
                      ("mask_bits", {**_synthetic(FULL_MASK, {}, 0), "remaining_mask": 1 << 12}),
                      ("bool_int", {**_synthetic(FULL_MASK, {}, 0), "input_tick": True})]:
        try:
            parse_targets(obj)
            bad.append(f"parse_{name}_accepted")
        except TargetContractError:
            pass
    try:
        require_diag_status({"no_render": True})
        bad.append("status_without_flag_accepted")
    except TargetContractError:
        pass
    snap = parse_targets(_synthetic(FULL_MASK, {}, 0))
    expect(snap.broken_mask == 0 and snap.remaining_ids == list(range(10)), "derived_masks")
    expect([region_of(r) for r in snap.records][:3] == ["left_of_wall", "left_of_wall", "upper_right_moving"],
           "regions_synthetic")
    # a clean episode: tick 0 -> id 4 breaks at consumed 5, ids 1 and 7 break together at consumed 9
    init = {"observation": _obs(0, 10), REPLY_KEY: _synthetic(FULL_MASK, {}, 0)}
    steps = []
    brk: Dict[int, Tuple[int, int]] = {}
    mask = FULL_MASK
    for t in range(12):
        if t == 5:
            mask &= ~(1 << 4)
            brk[4] = (1, t + 1)
        if t == 9:
            mask &= ~((1 << 1) | (1 << 7))
            brk[1] = (2, t + 1)
            brk[7] = (3, t + 1)
        steps.append({"consumed_tick": t, "observation": _obs(t + 1, popcount(mask)),
                      REPLY_KEY: _synthetic(mask, dict(brk), t + 1)})
    chk = check_trace(init, steps)
    expect(chk.ok, f"clean_trace {chk.problems}")
    expect([(e["target_id"], e["consumed_tick"], e["input_tick"]) for e in chk.events] ==
           [(4, 5, 6), (1, 9, 10), (7, 9, 10)], "events")
    expect(break_ticks(chk.events) == [5, 9, 9], "break_ticks_repr")
    # violations: resurrection, pairing stamp, count mismatch, anomaly, wrong native tick, same-tick order
    bad_steps = [dict(s) for s in steps]
    bad_steps[7] = {**steps[7], REPLY_KEY: _synthetic(FULL_MASK, {}, 8)}
    expect(any("became active again" in p for p in check_trace(init, bad_steps).problems), "resurrection")
    bad_steps = [dict(s) for s in steps]
    bad_steps[3] = {**steps[3], REPLY_KEY: {**steps[3][REPLY_KEY], "input_tick": 99}}
    expect(any("pairing" in p for p in check_trace(init, bad_steps).problems), "pairing")
    bad_steps = [dict(s) for s in steps]
    bad_steps[6] = {**steps[6], "observation": _obs(7, 10)}
    expect(any("popcount" in p for p in check_trace(init, bad_steps).problems), "count_mismatch")
    bad_steps = [dict(s) for s in steps]
    bad_steps[2] = {**steps[2], REPLY_KEY: _synthetic(FULL_MASK, {}, 3, anomalies=1 << 2)}
    expect(any("repeat_break" in p for p in check_trace(init, bad_steps).problems), "anomaly")
    bad_steps = [dict(s) for s in steps]
    wrong = dict(brk)
    wrong[4] = (1, 42)
    bad_steps[5] = {**steps[5], REPLY_KEY: _synthetic(FULL_MASK & ~(1 << 4), {4: (1, 42)}, 6)}
    expect(any("native break_input_tick" in p for p in check_trace(init, bad_steps[:6]).problems), "native_tick")
    swapped = dict(brk)
    swapped[1], swapped[7] = (3, 10), (2, 10)
    bad_steps = [dict(s) for s in steps]
    for k in range(9, 12):
        bad_steps[k] = {**steps[k], REPLY_KEY: _synthetic(steps[k][REPLY_KEY]["remaining_mask"], swapped, k + 1)}
    expect(any("ascending ID order" in p for p in check_trace(init, bad_steps).problems), "same_tick_order")
    expect(any("link walk" in p for p in check_trace(
        {"observation": _obs(0, 10), REPLY_KEY: _synthetic(FULL_MASK, {}, 0, link=9)}, []).problems), "link_walk")
    # the cross-check may be skipped after the scene task ended (status End/Set), never during Go
    ended = check_trace(init, steps[:3] + [{"consumed_tick": 3, "observation": _obs(4, 10, game_status=7),
                                            REPLY_KEY: _synthetic(FULL_MASK, {}, 4, link_checked=0)}])
    expect(ended.ok, f"teardown_skip_allowed {ended.problems}")
    expect(any("skipped during Go" in p for p in check_trace(init, steps[:3] + [
        {"consumed_tick": 3, "observation": _obs(4, 10), REPLY_KEY: _synthetic(FULL_MASK, {}, 4, link_checked=0)}]
    ).problems), "skip_during_go")
    bad_steps = [dict(s) for s in steps]
    bad_steps[5] = {**steps[5], "observation": {**steps[5]["observation"], "time_passed": 99}}
    expect(any("break_time_passed" in p for p in check_trace(init, bad_steps[:6]).problems), "time_passed")
    total = 26
    print(f"m7f_targets self-test: {'PASS' if not bad else 'FAIL'} ({total} cases, {len(bad)} failed) {bad}")
    return 0 if not bad else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
