"""State-machine signals over recorded lab traces (STATE_MACHINE_CANDIDATES.md section 5).

Read-only: it consumes the per-tick replies already recorded (observation, btt_entity_v1, btt_input_state_v1,
btt_spatial_v1, btt_target_identity_v1) and the static table of tools/glitch/states/decomp_states.py, and emits
btt_glitch_event_v1 objects (GLITCH_CANDIDATES.md section 3.3) through tools/glitch/detect.py's Detector.emit.

Ordinary mechanics are counted (summary "counts"); only departures from what the code allows become events. Every
signal is generic: no route, coordinate, target id or input sequence is built in.

Tick convention (port/rl/rl_step.cpp): step i consumed input tick i; its reply is captured after that tick's update.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

DETECTOR = {"name": "tools/glitch/states/state_detect.py", "version": 1}

BUTTON_A, BUTTON_B, BUTTON_Z, BUTTON_L, BUTTON_R = 0x8000, 0x4000, 0x2000, 0x0020, 0x0010
BUTTON_C = 0x000F
MAP_FLAG_CEIL = 0x400

STATUS_WAIT, STATUS_LANDING_LIGHT, STATUS_LANDING_HEAVY = 10, 31, 32
STATUS_FALLSPECIAL, STATUS_LANDING_FALLSPECIAL = 58, 59
STATUS_STOPCEIL = 66
AERIALS = range(209, 214)
LANDING_AIR = range(214, 220)          # LandingAirN..LandingAirLw, LandingAirNull
TORNADO_GROUND, TORNADO_AIR = 227, 228
DEAD = {0, 1, 2, 3}
SMOOTH_LANDING_TICS_MAX = 10           # FTCOMMON_ATTACKAIR_SMOOTHLANDING_TICS_MAX (src/ft/ftcommon.h:361)
SKIP_LANDING_VEL_Y = -20.0             # FTCOMMON_ATTACKAIR_SKIPLANDING_VEL_Y_MAX (src/ft/ftcommon.h:362)


def displayed_time(time_passed: int) -> str:
    """The Break the Targets clock as drawn by sc1PBonusStageTimerProcUpdate (src/sc/sc1pmode/sc1pbonusstage.c:1727):
    float division by 36000, 3600, 600, 60, 6 and 277/500 ticks, one digit each."""
    units = [36000.0, 3600.0, 600.0, 60.0, 6.0, 0.554]
    t = float(min(time_passed, 59 * 3600 + 59 * 60 + 59))
    digits = []
    for u in units:
        d = int(t / u)
        t -= d * u
        digits.append(d)
    return f"{digits[0]}{digits[1]}:{digits[2]}{digits[3]}.{digits[4]}{digits[5]}"


class _Table:
    def __init__(self, table: Mapping[str, Any]):
        self.raw = table
        self.st = {int(k): v for k, v in table["statuses"].items()}
        self.edges: Dict[int, Set[int]] = {}
        self.edge_via: Dict[Tuple[int, int], Set[str]] = {}
        for e in table["edges"]:
            self.edges.setdefault(int(e["from"]), set()).add(int(e["to"]))
            self.edge_via.setdefault((int(e["from"]), int(e["to"])), set()).add(e["via"])

    def name(self, sid: int) -> str:
        s = self.st.get(sid)
        return s["name"] if s else str(sid)

    def listed(self, a: int, b: int) -> bool:
        return b in self.edges.get(a, ()) or b in DEAD

    def chain(self, a: int, b: int) -> Optional[List[int]]:
        """a -> x -> b through table edges within one tick (a status set in proc_update has its proc_interrupt run in
        the same update: src/ft/ftmain.c:1636-1643)."""
        for x in sorted(self.edges.get(a, ())):
            if b in self.edges.get(x, ()):
                return [a, x, b]
        return None

    def entry_frames(self, sid: int, prev_frame: Optional[float], prev_speed: Optional[float]) -> List[float]:
        s = self.st.get(sid)
        if not s:
            return []
        out: Set[float] = set()
        for e in s["entry"]:
            if e.get("fkind_guard"):
                continue
            if e["continuation"]:
                if prev_frame is not None:
                    out.add(round(prev_frame + (prev_speed or 1.0), 4))
                    out.add(round(prev_frame, 4))
                continue
            base = e.get("frame_begin_value") or 0.0
            out.add(round(base + (1.0 if e["double_advance"] else 0.0), 4))
        return sorted(out)

    def anim_len(self, sid: int) -> Optional[int]:
        a = (self.st.get(sid) or {}).get("motion", {}).get("anim") or {}
        return None if a.get("loops") else a.get("length_last_joint")

    def has_anim(self, sid: int) -> bool:
        a = (self.st.get(sid) or {}).get("motion", {}).get("anim")
        return bool(a) and not a.get("missing") and a.get("joints", 0) > 0

    def loops(self, sid: int) -> bool:
        a = (self.st.get(sid) or {}).get("motion", {}).get("anim") or {}
        return bool(a.get("loops"))

    def update_only_targets(self, sid: int) -> Set[int]:
        """Targets reached only through proc_update (the animation-end exits)."""
        s = self.st.get(sid)
        if not s:
            return set()
        upd = {int(t) for t in ((s["exits"].get("update") or {}).get("targets") or {})}
        other: Set[int] = set()
        for k in ("interrupt", "physics", "map"):
            other |= {int(t) for t in ((s["exits"].get(k) or {}).get("targets") or {})}
        return upd - other

    def script_frame(self, sid: int, event: str, value: Optional[int] = None) -> Optional[int]:
        sc = (self.st.get(sid) or {}).get("script") or {}
        for e in sc.get("events", []):
            if e["event"] == event and (value is None or e.get("value") == value):
                return e["frame"]
        return None


def _input(s: Any) -> Dict[str, Any]:
    return {"stick": [s.stick_x, s.stick_y], "button_tap": f"0x{s.button_tap:04X}", "button_hold": f"0x{s.button_hold:04X}",
            "square_gate_corner": abs(s.stick_x) == 80 and abs(s.stick_y) == 80}


def run_signals(det: Any, table: Mapping[str, Any]) -> None:
    """Append the state-machine events and counts to a tools/glitch/detect.py Detector."""
    T = _Table(table)
    live = [s for s in det.states if s.live]
    counts = det.counts

    def count(key: str) -> None:
        counts[key] = counts.get(key, 0) + 1

    def emit(kind: str, mech: Sequence[str], a: Any, b: Any, score: float, evidence: Dict[str, Any], **kw: Any) -> None:
        evidence.setdefault("input", _input(b))
        evidence.setdefault("status_names", [T.name(a.status), T.name(b.status)])
        det.emit(kind, mech, a, b, score, 0, evidence, detector=DETECTOR, **kw)

    have_input = any(s.has_input_block for s in live)
    if not have_input:
        count("states:no_input_block")

    # per-instance bookkeeping
    inst_start: Optional[Any] = live[0] if live else None
    expended = False                      # Mario Tornado charge spent since the last landing (is_expend_tornado)
    tornado_flag2 = T.script_frame(TORNADO_AIR, "flag2", 1)
    completion_tick: Optional[int] = None
    for s in live:
        if s.targets_remaining == 0 and s.consumed_tick is not None:
            completion_tick = int(s.consumed_tick)
            break

    for a, b in zip(live, live[1:]):
        if b.index != a.index + 1:
            inst_start = b
            continue
        changed = a.status != b.status
        reentered = (not changed) and b.status_tics is not None and a.status_tics is not None and b.status_tics <= a.status_tics
        frozen = (a.hitlag or 0) > 0 or (b.hitlag or 0) > 0

        # CLK timer: time_passed advances once per consumed tick from tick 0, and stops on the completion tick
        if b.time_passed is not None and b.consumed_tick is not None:
            expected = int(b.consumed_tick) if completion_tick is None else min(int(b.consumed_tick), completion_tick)
            if b.time_passed != expected:
                emit("timer_tick_mismatch", ["CLK"], a, b, abs(b.time_passed - expected),
                     {"key": [b.time_passed, expected], "time_passed": b.time_passed, "expected": expected,
                      "displayed": displayed_time(b.time_passed)})

        # S1 transitions
        if changed or reentered:
            if changed and not T.listed(a.status, b.status):
                ch = T.chain(a.status, b.status)
                if ch:
                    count("chain:" + ">".join(T.name(x) for x in ch))
                else:
                    emit("status_transition_unlisted", ["S1"], a, b, 1.0,
                         {"key": [a.status, b.status], "from": a.status, "to": b.status,
                          "from_tics": a.status_tics, "to_tics": b.status_tics})
            else:
                count(f"transition:{T.name(a.status)}>{T.name(b.status)}")
            # S2 entry frame
            if have_input and b.anim_frame is not None and T.has_anim(b.status) and not frozen:
                allowed = T.entry_frames(b.status, a.anim_frame, a.anim_speed)
                af = round(b.anim_frame, 4)
                if allowed and af not in allowed and af > 0 and not T.loops(b.status):
                    emit("entry_frame_unexpected", ["S2"], a, b, min(abs(af - x) for x in allowed),
                         {"key": [b.status, af], "anim_frame": af, "allowed": allowed, "status_tics": b.status_tics})
                else:
                    count("entry:" + ("+1" if af == 1.0 else "cont" if af not in (0.0, 1.0) else "0"))
            # S2 instance duration on an animation-end exit
            if inst_start is not None and changed and b.status in T.update_only_targets(a.status):
                L = T.anim_len(a.status)
                if L and inst_start.anim_frame is not None and a.anim_speed:
                    expect = math.ceil(round((L - inst_start.anim_frame) / a.anim_speed, 6))
                    got = b.index - inst_start.index
                    lag = sum(1 for s in det.states[inst_start.index + 1:b.index + 2] if (s.hitlag or 0) > 0)
                    if got + 0 < expect and lag == 0:
                        emit("status_shorter_than_nominal", ["S2"], a, b, expect - got,
                             {"key": [a.status, got], "status": a.status, "observed_ticks": got, "nominal_ticks": expect,
                              "anim_frames": L, "entry_anim_frame": inst_start.anim_frame})
                    else:
                        count("instance_ok" if got == expect else "instance_longer")
            inst_start = b
        elif (have_input and not frozen and a.anim_frame is not None and b.anim_frame is not None and b.anim_speed
              and T.has_anim(b.status)):
            # S2 animation clock inside one instance
            d = b.anim_frame - a.anim_frame
            if b.anim_frame > 0 and d >= 0 and abs(d - b.anim_speed) > 1e-3 and not T.loops(b.status):
                emit("anim_clock_skew", ["S2"], a, b, abs(d - b.anim_speed),
                     {"key": [b.status, a.anim_frame], "delta": d, "anim_speed": b.anim_speed,
                      "anim_frame": [a.anim_frame, b.anim_frame]})

        # S10 jump counter
        if a.jumps_used is not None and b.jumps_used is not None:
            if a.ga == 1 and b.ga == 1 and b.jumps_used < a.jumps_used:
                emit("jumps_restored_in_air", ["S10"], a, b, a.jumps_used - b.jumps_used,
                     {"key": [a.jumps_used, b.jumps_used], "jumps_used": [a.jumps_used, b.jumps_used]})
            jmax = b.jumps_max or 2
            if b.jumps_used > jmax:
                emit("jumps_over_max", ["S10"], a, b, b.jumps_used - jmax, {"key": [b.jumps_used], "jumps_used": b.jumps_used,
                                                                           "jumps_max": jmax})
            if b.jumps_used != a.jumps_used:
                count(f"jumps:{a.jumps_used}>{b.jumps_used}@{T.name(b.status)}")

        # S3 Mario Tornado charge (is_expend_tornado is not recorded: tracked from its causes)
        if a.ga == 1 and b.ga == 0:
            if expended:
                count("tornado:charge_reset_by_landing")
            expended = False
        if b.status == TORNADO_AIR and tornado_flag2 is not None and b.anim_frame is not None and b.anim_frame >= tornado_flag2:
            expended = True
        if b.status == TORNADO_AIR and a.status in (TORNADO_GROUND, TORNADO_AIR) and (b.button_tap & BUTTON_B) and b.vy - a.vy > 10.0:
            count("tornado:rise_tap")
            if expended and a.ga == 1:
                emit("special_limit_rearm_unexpected", ["S3"], a, b, b.vy - a.vy,
                     {"key": [b.index], "dvy": b.vy - a.vy, "note": "B-tap rise while the tornado charge is spent"})

        # S4/S5 landing branches (aerials, FallSpecial)
        if a.ga == 1 and b.ga == 0:
            if a.status in AERIALS and have_input:
                flag1 = b.motion_flag1 or 0
                z_late = (b.tics_since_last_z if b.tics_since_last_z is not None else 1 << 16) > SMOOTH_LANDING_TICS_MAX
                if flag1 != 0 and z_late:
                    expect = set(LANDING_AIR)
                    branch = "lag"
                elif b.vy > SKIP_LANDING_VEL_Y:
                    expect, branch = {STATUS_WAIT}, ("zcancel_skip" if flag1 else "skip")
                else:
                    expect, branch = {STATUS_LANDING_LIGHT, STATUS_LANDING_HEAVY}, ("zcancel" if flag1 else "normal")
                count(f"landing:{branch}")
                if b.status not in expect and b.status not in DEAD:
                    emit("landing_branch_mismatch", ["S4"], a, b, 1.0,
                         {"key": [a.status, b.status], "branch_expected": branch, "expected": sorted(expect),
                          "motion_flag1": flag1, "tics_since_last_z": b.tics_since_last_z, "vel_y": b.vy})
            if a.status == STATUS_FALLSPECIAL:
                count(f"landing:fallspecial>{T.name(b.status)}")
                if b.status == STATUS_WAIT:
                    emit("fallspecial_landing_lag_skipped", ["S5", "S4"], a, b, 1.0,
                         {"key": [b.index], "vel_y": b.vy, "note": "Mario's FallSpecial comes from the Super Jump Punch, "
                                                                   "which asks for LandingFallSpecial (is_goto_landing TRUE)"})
            if b.status == STATUS_WAIT and b.vy > SKIP_LANDING_VEL_Y and b.carry != (0.0, 0.0):
                count("landing:skip_on_moving_line")

        # S6 hitlag around target breaks
        if a.target_mask is not None and b.target_mask is not None:
            cleared = int(a.target_mask) & ~int(b.target_mask)
            if cleared:
                weapons = bool(a.weapons or b.weapons)
                body = bool(a.attack_active or b.attack_active)
                if (a.hitlag or 0) > 1:
                    emit("break_during_hitlag", ["S6"], a, b, a.hitlag,
                         {"key": [cleared], "targets_mask": cleared, "hitlag_before": a.hitlag})
                if body and not weapons and (b.hitlag or 0) == 0:
                    emit("break_hitlag_mismatch", ["S6"], a, b, 1.0,
                         {"key": [cleared, "no_hitlag"], "targets_mask": cleared, "hitlag": b.hitlag,
                          "note": "body hitbox active, no weapon, no hitlag after the break"})
                elif weapons and not body and (b.hitlag or 0) > 0:
                    emit("break_hitlag_mismatch", ["S6"], a, b, b.hitlag,
                         {"key": [cleared, "hitlag"], "targets_mask": cleared, "hitlag": b.hitlag,
                          "note": "only a weapon could hit, yet Mario is in hitlag"})
                count(f"break:hitlag={b.hitlag or 0}")

        # S8 ceiling contact with the vertical velocity kept
        if b.mask & MAP_FLAG_CEIL and b.vy > 0 and abs(b.y - a.y) < 1.0 and a.mask & MAP_FLAG_CEIL:
            count("ceiling:velocity_kept_tick")
        if changed and b.status == STATUS_STOPCEIL:
            count("ceiling:stopceil")

        # S7 stale motion flag 1 at entry
        if (changed or reentered) and have_input and (b.motion_flag1 or 0) != 0:
            st = T.st.get(b.status) or {}
            if "flag1" in st.get("stale_flag_candidates", []):
                f1 = T.script_frame(b.status, "flag1")
                if f1 is None or (b.anim_frame is not None and f1 > b.anim_frame):
                    emit("stale_flag_at_entry", ["S7"], a, b, b.motion_flag1,
                         {"key": [b.status], "flag": "flag1", "value": b.motion_flag1, "script_sets_flag1_at": f1})

    # S8 runs of ceiling contact with rising velocity (an ordinary mechanic that looks like a hover)
    run: List[Any] = []
    for a, b in zip(live, live[1:]):
        if b.mask & MAP_FLAG_CEIL and b.vy > 0 and abs(b.y - a.y) < 1.0:
            run.append(b)
        else:
            if len(run) >= 3:
                emit("ceiling_velocity_kept", ["S8"], run[0], run[-1], len(run),
                     {"key": [run[0].index], "ticks": len(run), "vel_y": [run[0].vy, run[-1].vy]}, tick_to=run[-1].index)
            run = []
    if len(run) >= 3:
        emit("ceiling_velocity_kept", ["S8"], run[0], run[-1], len(run),
             {"key": [run[0].index], "ticks": len(run), "vel_y": [run[0].vy, run[-1].vy]}, tick_to=run[-1].index)

    if completion_tick is not None:
        counts["completion_tick"] = completion_tick
        last = next((s for s in live if s.consumed_tick == completion_tick), None)
        if last is not None and last.time_passed is not None:
            counts["completion_time_passed"] = last.time_passed
            counts["completion_displayed"] = displayed_time(last.time_passed)  # type: ignore[assignment]


def scan(trace: Mapping[str, Any], table: Mapping[str, Any], source: Optional[Mapping[str, Any]] = None
         ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    import detect  # tools/glitch/detect.py
    import geometry as gm
    p = detect.Params(state_table=table, only_states=True)
    try:
        geo = gm.lines_from_trace_reply(trace.get("initial") or {})
    except gm.GeometryError:
        # the state signals need no geometry: a placeholder line keeps the event format (geometry_sha256) defined
        geo = gm.lines_from_trace_reply({"spatial": {"lines": [{"id": 0, "type": 0, "group": 1, "flags": 0,
                                                                "vertices": [[0, -100000], [1, -100000]]}]}})
    det = detect.Detector(trace, geo, p, source)
    summary = det.run()
    return det.events, summary
