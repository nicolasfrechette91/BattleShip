"""M8-rd synthetic native stand-in (tests only): a deterministic 2-D platformer that speaks the reply format of
SSB64_RL_SPATIAL=1 (observation, spatial block, step bookkeeping), so the whole session machinery (workers, archive, claims,
verification, rule, caps) can run at production counts without a game.

THE WORLD IS SYNTHETIC: nothing it produces says anything about Mario. It exercises code paths.

    StubBackend  the worker backend (`spec["backend"] = "m8_rd_stub:StubBackend"`): acquire() returns a parked tick-0 process
    replay_fn    the verification replay (same world, a trace in the m7f_trace format with every reply)
    analyse      a stand-in for m7n_crossing.analyse_trace over those replies

Injection (spec["inject"]): {"lifecycle_jobs": [n, ...]} raises a lifecycle failure on the n-th acquired process;
{"mismatch_job": n | [n, ...], "mismatch_tick": t} corrupts the reply of tick t of the n-th process (a list: those processes; an
integer: that one and every later one), an integrity failure at the end of a prefix that passes tick t;
{"bad_consumed_job": n} makes tick 5 of the n-th process report the wrong consumed_tick; {"provenance_job": n} records a
forbidden-path open;
{"slow_s": s} sleeps s seconds per acquire. host_frame carries a per-process offset: the real game's host_frame differs
between processes and nothing may depend on it.
"""
from __future__ import annotations

import hashlib
import math
import os
import sys
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import m8_rd_cells as mcell  # noqa: E402
import m8_rd_worker as mw  # noqa: E402

STUB_CONTRACT = "m8_rd_stub_v1"

WORLDS: Dict[str, Dict[str, Any]] = {
    # easy: every milestone is reachable by random play within a few thousand ticks (small end-to-end tests)
    "easy": {"vmax": 34.0, "acc": 4.0, "air_acc": 3.0, "gravity": 3.4, "jump_v": 52.0, "djump_v": 46.0, "upb_v": 62.0,
             "fall_y": -1400.0, "radius": 260.0, "wall_y": 600.0,
             "floors": [(4, -2600.0, 3000.0, 0.0), (1, 2400.0, 3600.0, 420.0), (0, -2600.0, -1400.0, 500.0),
                        (3, -4200.0, -2300.0, -500.0)],
             "targets": [(1500.0, 0.0), (-3000.0, -400.0), (900.0, 200.0), (2800.0, 380.0), (0.0, 0.0), (300.0, 100.0),
                         (-3300.0, 1000.0), (-300.0, 600.0), (-3100.0, -300.0), (2000.0, 0.0)]},
    # hard: production-count end-to-end (a clear is rare or absent)
    "hard": {"vmax": 24.0, "acc": 2.0, "air_acc": 1.5, "gravity": 3.2, "jump_v": 44.0, "djump_v": 38.0, "upb_v": 54.0,
             "fall_y": -1500.0, "radius": 150.0, "wall_y": 1500.0,
             "floors": [(4, -1900.0, 2300.0, 0.0), (1, 2100.0, 3300.0, 450.0), (0, -2100.0, -1200.0, 3000.0),
                        (3, -3900.0, -2700.0, -600.0)],
             "targets": [(1350.0, -300.0), (-3450.0, -500.0), (2700.0, 1500.0), (3500.0, 300.0), (0.0, -100.0),
                         (0.0, 300.0), (-3300.0, 3300.0), (0.0, 1650.0), (-3300.0, 600.0), (1650.0, -200.0)]},
    # calm: nothing happens (far targets, no fall): every episode runs to the horizon
    "calm": {"vmax": 20.0, "acc": 2.0, "air_acc": 1.5, "gravity": 3.2, "jump_v": 40.0, "djump_v": 34.0, "upb_v": 50.0,
             "fall_y": -1e9, "radius": 50.0, "wall_y": 1500.0, "floors": [(4, -1e9, 1e9, 0.0)],
             "targets": [(40000.0 + 100.0 * i, 40000.0) for i in range(10)]},
    # trivial: all ten targets overlap the start, so tick 1 clears the stage
    "trivial": {"vmax": 20.0, "acc": 2.0, "air_acc": 1.5, "gravity": 3.2, "jump_v": 40.0, "djump_v": 34.0, "upb_v": 50.0,
                "fall_y": -1e9, "radius": 300.0, "wall_y": 1500.0, "floors": [(4, -1e9, 1e9, 0.0)],
                "targets": [(float(10 * i - 40), 0.0) for i in range(10)]},
}


def status_ids() -> Dict[str, int]:
    clf = mcell.Classifier()
    by: Dict[str, int] = {}
    for sid, cls in sorted(clf._by_id.items()):
        by.setdefault(cls, sid)
    return by


_STATUS = status_ids()
_LINES = [{"id": i, "type": 0, "group": 1, "flags": 0, "vertex_total": 2, "vertices": [[float(i), 0.0], [float(i) + 1, 0.0]]}
          for i in range(20)]
_WORD = {t: i for i, t in enumerate(mcell.TRIPLES)}
_GROUPS = [{"id": g, "present": 1, "speed": [0.0, 0.0], "status": 0, "translate": [0.0, 0.0], "translated": 0} for g in range(3)]


class World:
    def __init__(self, params: Mapping[str, Any]):
        self.p = dict(params)
        self.floors = [tuple(f) for f in self.p["floors"]]
        self.targets = [tuple(t) for t in self.p["targets"]]
        self.positions = [[float(x), float(y)] for x, y in self.targets]

    def initial(self) -> List[Any]:
        # x, y, vx, vy, ground, floor, jumps, status, upb_ticks, helpless, used_upb, a_prev, mask, t, ended, fell
        return [0.0, 0.0, 0.0, 0.0, 1, 4, 0, "idle_ground", 0, False, False, False, (1 << 10) - 1, 0, False, False]

    def advance(self, s: List[Any], word: int) -> None:
        p = self.p
        b, sx, sy = mcell.TRIPLES[word]
        x, y, vx, vy, ground, floor, jumps, status, upb, helpless, used, a_prev, mask, t, _e, _f = s
        a_now = bool(b & 0x8000)
        edge = a_now and not a_prev
        tgt = sx / 80.0 * p["vmax"]
        acc = p["acc"] if ground else p["air_acc"]
        vx += max(-acc, min(acc, tgt - vx))
        landed = False
        if edge and ground:
            vy, ground, floor, jumps, status = p["jump_v"], 0, -1, 1, "airborne"
        elif edge and not ground and jumps < 2 and not helpless and upb == 0:
            vy, jumps, status = p["djump_v"], 2, "airborne"
        if (b & 0x4000) and sy >= 40 and not helpless and not used and upb == 0:
            upb, used, jumps, ground, floor, status = 12, True, 2, 0, -1, "special_hi"
        if upb > 0:
            vy = p["upb_v"]
            upb -= 1
            if upb == 0:
                helpless, status = True, "helpless"
        elif not ground:
            vy = max(vy - p["gravity"], -60.0)
        ny = y + (vy if not ground else 0.0)
        nx = x + vx
        if ground:
            fl = next((f for f in self.floors if f[0] == floor), None)
            if fl is None or not (fl[1] <= nx <= fl[2]):
                ground, floor, status, jumps = 0, -1, "airborne", max(jumps, 1)
                vy = 0.0
        else:
            if vy <= 0:
                for fid, x0, x1, fy in self.floors:
                    if y >= fy - 1e-9 and ny <= fy and x0 <= nx <= x1:
                        ny, vy, ground, floor, jumps, helpless, used, landed = fy, 0.0, 1, fid, 0, False, False, True
                        status = "landing_free"
                        break
        if ground and not landed:
            status = "dash_run" if abs(vx) > 6 else "idle_ground"
        x, y = nx, ny
        for i, (tx, ty) in enumerate(self.targets):
            if (mask >> i) & 1 and math.hypot(tx - x, ty - y) < p["radius"]:
                mask &= ~(1 << i)
        fell = y < p["fall_y"]
        if fell:
            status = "dead"
        s[:] = [x, y, vx, vy, ground, floor, jumps, status, upb, helpless, used, a_now, mask, t + 1, mask == 0, fell]

    def reply(self, s: Sequence[Any], host_off: int, *, observe: bool = False) -> Dict[str, Any]:
        x, y, vx, vy, ground, floor, jumps, status, _u, _h, _used, _a, mask, t, ended, fell = s
        gs = 5 if (fell or ended) else 1
        obs = {"observation_schema": 1, "host_frame": host_off + t, "input_tick": t, "time_passed": max(0, t - 1), "game_status": gs,
               "btt_active": 1, "targets_remaining": mcell.popcount(mask), "fighter_valid": 1, "position_x": x,
               "position_y": y, "air_velocity_x": 0.0 if ground else vx, "air_velocity_y": vy,
               "ground_velocity_x": vx if ground else 0.0, "facing_direction": 1 if vx >= 0 else -1,
               "ground_air_state": int(not ground), "fighter_status_id": _STATUS[status], "jumps_used": jumps}
        sp = {"contract": "btt_spatial_v1", "spatial_schema": 1, "input_tick": t, "scene_active": 1, "live": 1,
              "update_tic": t + 62, "anomaly_flags": 0, "map_bounds": [9600, -9600, 9600, -9600],
              "camera_bounds": [5000, -5000, 5000, -5000], "groups": _GROUPS,
              "fighter": {"valid": 1, "floor_line_id": floor if ground else 4, "ceil_line_id": 0, "lwall_line_id": 0,
                          "rwall_line_id": 0, "mask_curr": 0, "floor_dist": 0.0 if ground else y, "carry": [0.0, 0.0],
                          "coll": [320.0, 190.0, 0.0, 150.0]},
              "target_live_mask": mask, "target_positions": self.positions}
        if observe:
            sp = dict(sp, lines=_LINES)
        state = mcell.STATE_ENDED if ended else mcell.STATE_WAITING
        r = {"ok": True, "op": "observe" if observe else "step", "protocol": 1, "state": state,
             "state_name": "EpisodeEnded" if ended else "WaitingForAction", "step_count": t, "observation": obs, "spatial": sp}
        if observe:
            r["can_step"] = True
        else:
            r["consumed_tick"] = t - 1
            r["step_schema"] = 1
        return r


class StubProc:
    def __init__(self, backend: "StubBackend", n: int, mode: str):
        self.backend = backend
        self.world = backend.world
        self.n = n
        self.state = self.world.initial()
        self.host_off = 40 + (hashlib.sha256(f"{os.getpid()}|{n}".encode()).digest()[0] % 60)
        self.mode = mode
        self.startup = {"mode": mode, "wait_s": 0.0}
        self.pid = os.getpid() * 1000 + n
        self.inject = backend.inject
        self.closed = False
        self.steps = 0

    def observe(self) -> Dict[str, Any]:
        return self.world.reply(self.state, self.host_off, observe=True)

    def step(self, b: int, x: int, y: int) -> Dict[str, Any]:
        if self.n in (self.inject.get("lifecycle_jobs") or []) and self.steps == 3:
            raise mw.LifecycleFailure("premature_exit", "injected process death")
        word = _WORD[(b, x, y)]
        self.world.advance(self.state, word)
        self.steps += 1
        r = self.world.reply(self.state, self.host_off)
        mj = self.inject.get("mismatch_job")
        if mj is not None and (self.n in mj if isinstance(mj, (list, tuple)) else self.n >= int(mj))                 and self.steps == int(self.inject.get("mismatch_tick", 20)):
            r = dict(r, observation=dict(r["observation"], position_x=r["observation"]["position_x"] + 1.0))
        if self.inject.get("bad_consumed_job") == self.n and self.steps == 5:
            r = dict(r, consumed_tick=r["consumed_tick"] + 1)
        return r

    def finish(self, reply: Mapping[str, Any]) -> Dict[str, Any]:
        if self.inject.get("finish_fail_job") == self.n:
            raise mw.LifecycleFailure("exit_timeout", "injected: the process did not exit after the terminal result")
        t = reply["observation"]["input_tick"]
        return {"exit_code": 0, "result": {"result_schema": 1, "outcome": "clear", "targets_broken": 10,
                                           "completion_time_passed": t - 1, "completion_input_tick": t,
                                           "time_passed_final": t - 1, "input_cursor_final": t, "host_frames": t + 60}}

    def close(self) -> str:
        self.closed = True
        return "terminated"


class StubBackend:
    def __init__(self, spec: Mapping[str, Any]):
        self.spec = dict(spec)
        self.rank = int(spec["rank"])
        self.world = World(WORLDS[spec.get("world", "easy")])
        self.inject = dict(spec.get("inject") or {})
        self.n = 0
        self.slow = float(self.inject.get("slow_s", 0.0))

    def acquire(self, wait_timeout: float = 0.0) -> StubProc:
        self.n += 1
        if self.inject.get("hang_job") == self.n:
            time.sleep(600.0)
        if self.slow:
            time.sleep(self.slow)
        if self.inject.get("provenance_job") == self.n:
            mw.ProvenanceGuard.violations.append("injected/" + "rl/" + "fix" + "tures/x")
        return StubProc(self, self.n, "standby_promoted")

    def info(self) -> Dict[str, Any]:
        return {"pid": os.getpid(), "rank": self.rank, "backend": "stub"}

    def report(self) -> Dict[str, Any]:
        return {"acquired": self.n}

    def close(self) -> Dict[str, Any]:
        return {"closed": True}


# -- verification replay and analysis stand-ins ----------------------------------------------------------------------------


def replay_trace(world_name: str, words: bytes, label: str = "stub") -> Dict[str, Any]:
    """A trace in the m7f_trace format (`initial`, one raw reply per submitted word, the digest, the result on a clear)."""
    world = World(WORLDS[world_name])
    s = world.initial()
    host_off = 77
    initial = world.reply(s, host_off, observe=True)
    steps: List[Dict[str, Any]] = []
    rows = []
    final = "WaitingForAction"
    result = None
    for i, w in enumerate(words):
        world.advance(s, w)
        r = world.reply(s, host_off)
        steps.append(r)
        b, x, y = mcell.TRIPLES[w]
        rows.append((b, x, y, r["consumed_tick"]))
        if r["state"] == mcell.STATE_ENDED:
            final = "EpisodeEnded"
            t = r["observation"]["input_tick"]
            result = {"result_schema": 1, "outcome": "clear", "targets_broken": 10, "completion_time_passed": t - 1,
                      "completion_input_tick": t, "time_passed_final": t - 1, "input_cursor_final": t, "host_frames": t + 60}
            break
    return {"label": label, "initial": initial, "steps": steps, "submitted": len(steps), "unsent": len(words) - len(steps),
            "consumed_tick_mismatch": None, "final_state": final, "exit_code": 0 if result else None, "result": result,
            "action_digest": mcell.native_digest(rows)}


def analyse(initial: Mapping[str, Any], steps: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Stand-in for m7n_crossing.analyse_trace: the break table from the mask, a left-target break, and a 'qualified
    crossing' = a live step left of x = -2100 entered at or above the stub wall height, followed by a landing on floor 3."""
    prev_mask = int(initial["spatial"]["target_live_mask"])
    breaks: List[Tuple[int, int]] = []
    prev = (float(initial["observation"]["position_x"]), float(initial["observation"]["position_y"]))
    entry_tick: Optional[int] = None
    qualified = False
    for r in steps:
        o, sp = r["observation"], r["spatial"]
        m = int(sp["target_live_mask"])
        if m != prev_mask:
            for i in range(10):
                if (prev_mask & ~m) >> i & 1:
                    breaks.append((i, int(r["consumed_tick"])))
            prev_mask = m
        x, y = float(o["position_x"]), float(o["position_y"])
        if prev[0] >= -2100.0 > x and entry_tick is None and y >= 600.0:
            entry_tick = int(r["consumed_tick"])
        if entry_tick is not None and int(o["ground_air_state"]) == 0 and int(sp["fighter"]["floor_line_id"]) == 3 and x < -2100.0:
            qualified = True
        prev = (x, y)
    left = [(i, t) for i, t in breaks if i in mcell.LEFT_TARGET_IDS]
    return {"breaks": breaks, "qualified_crossing": qualified, "left_target_break": bool(left), "left_target_breaks": left,
            "first_qualified_entry": {"consumed_tick": entry_tick} if qualified else None, "route": "stub", "terminal": None}


def p1_inputs(world_name: str, n_words: Sequence[int] = (300, 220)) -> List[Dict[str, Any]]:
    """Synthetic pinned traces for P1: keyed words, the digest of every reply's record and the host frames."""
    out = []
    for k, n in enumerate(n_words):
        words = bytes(int.from_bytes(hashlib.sha256(f"stubtrace|{k}|{i}".encode()).digest()[:4], "big") % 72 for i in range(n))
        world = World(WORLDS[world_name])
        s = world.initial()
        digests, hosts, rows = [], [], []
        for i, w in enumerate(words):
            world.advance(s, w)
            r = world.reply(s, 77)
            digests.append(mcell.record_digest(mcell.record_of(r)))
            hosts.append(r["observation"]["host_frame"])
            b, x, y = mcell.TRIPLES[w]
            rows.append((b, x, y, r["consumed_tick"]))
            if r["state"] == mcell.STATE_ENDED or r["observation"]["game_status"] == 5:
                words = words[:i + 1]
                break
        out.append({"name": f"stub_trace_{k}", "words": words, "expected_digests": digests, "expected_host_frames": hosts,
                    "native_action_digest": mcell.native_digest(rows)})
    return out
