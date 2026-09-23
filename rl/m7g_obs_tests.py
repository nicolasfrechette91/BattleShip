"""M7g-b permanent tests: btt_spatial_v1 native diagnostic reader and btt_policy_obs_v2_spatial.

Unit cases (no game):
    unit_contract            v2 space: keys, order, shapes, dtypes, bounds, 525 flat values, normalised vs binary keys,
                             contract description / digest; v1 constants and space unchanged
    unit_stage_table         the pinned native line table equals the decomp stage source (rl/m7g_fixture.py's geometry
                             decoder, geometry only) and, when present, the native tables of the M7g-b captures
    unit_parser              strict btt_spatial_v1 parsing: a valid object parses; missing / extra keys, booleans as
                             integers, wrong contract, lines in a step reply, out-of-order ids are refused
    unit_builder             segment / target encoding on synthetic snapshots: 24 segments + 8 padding rows, kind
                             flags, relative vertices, closest points, platform translate and velocity, broken
                             targets, teardown hold-last, errors; state copied byte for byte
    unit_invariants          m7g_spatial.check_snapshot flags corrupted snapshots (speed, carry, target 2, masks)
    unit_isolation           observation modules never reference the crossing fixtures or route vocabulary, never
                             call .learn(), and v2 keys / fields carry no route information
    unit_sb3_dummy           in-memory synthetic env: MultiInputPolicy init, parameter count, forward pass,
                             VecNormalize key handling (binary keys raw), save / reload identical predictions, frozen
                             evaluation keeps statistics, a v1 checkpoint is refused for v2
    unit_offline_traces      (when the M7g-b capture sets exist) every spatial object valid, v2 deterministic
Game cases (fresh BattleShip processes, one at a time unless stated):
    game_wrapper_vs_raw      M5 stack + v2 wrapper on a historical Track 1 artifact (3,600 actions): v2 state bytes
                             == v1, zero invariant problems, every v2 observation equals the one rebuilt offline from a
                             separate raw-reply trace of the same actions
    game_standby_v2          M7 worker stack v2 (build_worker_env_v2) with one standby: cold_start then
                             standby_promoted episodes of the same actions give identical v2 observations; first step
                             consumes tick 0; artifact labels record the v2 contract
    game_sb3_real            the real game env through DummyVecEnv + VecNormalize(norm_obs_keys): PPO init, forward
                             passes, statistics update only for continuous keys, save / reload, frozen evaluation
    game_n5_standby_bench    N=5 workers with standby (<= 10 processes): v1 vs v2 random Track 1 actions,
                             transitions per second, process count, cleanup

Usage: python rl/m7g_obs_tests.py [unit|game|<case> ...] [--root runs/m7g_obs/_tests_<utc>]
Exit 0 all pass, 1 any failure. Nothing here trains a model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import gymnasium as gym  # noqa: E402
import numpy as np  # noqa: E402
from gymnasium import spaces  # noqa: E402

import m7g_obs as mo  # noqa: E402
import m7g_spatial as ms  # noqa: E402

REPO_ROOT = RL_DIR.parent
EXECUTABLE = REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"
EQUIV = REPO_ROOT / "runs" / "m7g_obs" / "_equiv"
FLAGS = {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1"}
BENCH_VEC_STEPS = 8000        # per arm: 40,000 transitions at N=5
ARTIFACT = "m7e_s0_best6"      # a historical M7e evaluation episode (Track 1, 3,600 actions, horizon)
V1_FIELDS = ("input_tick", "time_passed", "game_status", "btt_active", "targets_remaining", "fighter_valid",
             "position_x", "position_y", "air_velocity_x", "air_velocity_y", "ground_velocity_x", "facing_direction",
             "ground_air_state", "fighter_status_id", "jumps_used")


class CaseFailure(AssertionError):
    pass


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise CaseFailure(msg)


class Suite:
    def __init__(self, root: Path):
        self.root = root

    def dir(self, name: str) -> Path:
        d = self.root / name
        d.mkdir(parents=True, exist_ok=False)
        return d


# -- synthetic data ---------------------------------------------------------------------------------------------

def pinned_lines() -> List[ms.SpatialLine]:
    return [ms.SpatialLine(i, t, g, f, len(v), v) for i, t, g, f, v in ms.EXPECTED_LINES]


STATIC_TARGETS = {0: (-1350.0, -2250.0), 1: (-3450.0, -2550.0), 3: (4950.0, -1800.0), 4: (5e-06, -900.0),
                  5: (2e-05, 300.0), 6: (-3300.0, 3300.0), 7: (0.0, 1650.0), 8: (-3300.0, 600.0),
                  9: (1650.0, -2250.0)}


def synth_snapshot(*, tick: int = 0, platform_y: float = 2150.927, speed_y: float = 17.3, mask: int = 1023,
                   live: int = 1, lines: bool = False) -> ms.SpatialSnapshot:
    groups = (ms.SpatialGroup(0, 1, 0, 0, (0.0, 0.0), (0.0, 0.0)), ms.SpatialGroup(1, 1, 0, 0, (0.0, 0.0), (0.0, 0.0)),
              ms.SpatialGroup(2, 1, 0, 1, (2700.0, platform_y), (0.0, speed_y)))
    pos = []
    for i in range(10):
        if not mask & (1 << i):
            pos.append((0.0, 0.0))
        elif i == 2:
            pos.append((2700.0, platform_y + 600.0))
        else:
            pos.append(STATIC_TARGETS[i])
    fighter = ms.SpatialFighter(1, 4, 0, 0, 0, 0, 0.0, (0.0, 0.0), (320.0, 190.0, 0.0, 150.0))
    return ms.SpatialSnapshot(tick, 1, live, 61 + tick, 0, ms.MAP_BOUNDS, ms.CAMERA_BOUNDS, groups, fighter, mask,
                              tuple(pos), tuple(pinned_lines()) if lines else None)


def synth_json(snap: ms.SpatialSnapshot, *, with_lines: bool) -> Dict[str, Any]:
    j: Dict[str, Any] = {
        "contract": ms.CONTRACT, "spatial_schema": 1, "input_tick": snap.input_tick, "scene_active": snap.scene_active,
        "live": snap.live, "update_tic": snap.update_tic, "anomaly_flags": snap.anomaly_flags,
        "map_bounds": list(snap.map_bounds), "camera_bounds": list(snap.camera_bounds),
        "groups": [{"id": g.id, "present": g.present, "status": g.status, "translated": g.translated,
                    "translate": list(g.translate), "speed": list(g.speed)} for g in snap.groups],
        "fighter": {"valid": 1, "floor_line_id": 4, "ceil_line_id": 0, "lwall_line_id": 0, "rwall_line_id": 0,
                    "mask_curr": 0, "floor_dist": 0.0, "carry": [0.0, 0.0], "coll": [320.0, 190.0, 0.0, 150.0]},
        "target_live_mask": snap.target_live_mask, "target_positions": [list(p) for p in snap.target_positions]}
    if with_lines:
        j["lines"] = [{"id": i, "type": t, "group": g, "flags": f, "vertex_total": len(v), "vertices": [list(p) for p in v]}
                      for i, t, g, f, v in ms.EXPECTED_LINES]
    return j


def v1_state(x: float, y: float, tick: int = 0, targets: int = 10) -> Tuple[np.ndarray, Dict[str, Any]]:
    obs = {"input_tick": tick, "time_passed": tick, "game_status": 1, "btt_active": 1, "targets_remaining": targets,
           "fighter_valid": 1, "position_x": x, "position_y": y, "air_velocity_x": 0.0, "air_velocity_y": 0.0,
           "ground_velocity_x": 0.0, "facing_direction": 1, "ground_air_state": 0, "fighter_status_id": 10,
           "jumps_used": 0}
    from btt_learning import policy_observation

    return policy_observation(obs), obs


# -- unit ---------------------------------------------------------------------------------------------------------

def unit_contract(s: Suite) -> Dict[str, Any]:
    import btt_learning as bl

    space = mo.make_observation_space()
    check(tuple(space.spaces.keys()) == mo.KEY_ORDER == tuple(sorted(mo.KEY_ORDER)), f"key order {list(space.spaces)}")
    expect = {"segment_geometry": ((32, 8), -np.inf, np.inf), "segment_kind": ((32, 7), 0.0, 1.0),
              "state": ((15,), -np.inf, np.inf), "target_geometry": ((10, 2), -np.inf, np.inf),
              "target_live": ((10,), 0.0, 1.0)}
    for k, (shape, lo, hi) in expect.items():
        b = space.spaces[k]
        check(isinstance(b, spaces.Box) and b.shape == shape and b.dtype == np.float32
              and np.all(b.low == lo) and np.all(b.high == hi), f"{k}: {b}")
    check(mo.FLAT_SIZE == 525 and set(mo.NORMALIZED_KEYS) | set(mo.BINARY_KEYS) == set(mo.KEY_ORDER)
          and not set(mo.NORMALIZED_KEYS) & set(mo.BINARY_KEYS), "normalised / binary key partition")
    check(mo.OBS_CONTRACT == "btt_policy_obs_v2_spatial" != bl.POLICY_OBSERVATION_CONTRACT, "contract ids")
    # v1 frozen: id, 15 fields in declaration order, float32 Box(15)
    check(bl.POLICY_OBSERVATION_CONTRACT == "btt_policy_obs_v1" and bl.POLICY_FIELDS == V1_FIELDS
          and bl.POLICY_OBSERVATION_SIZE == 15, f"v1 contract changed: {bl.POLICY_FIELDS}")
    v1s = bl.make_policy_observation_space()
    check(v1s.shape == (15,) and v1s.dtype == np.float32 and space.spaces["state"] == v1s, "state key == v1 space")
    desc = mo.contract_description()
    check(json.loads(json.dumps(desc)) == desc and desc["keys"]["state"]["byte_identical_to_v1"], "description")
    schema_path = REPO_ROOT / "docs" / "rl_observation_v2_m7g.schema.json"
    if schema_path.is_file():
        doc = json.loads(schema_path.read_text(encoding="utf-8"))
        check(doc.get("contract") == desc, "docs schema's contract block differs from contract_description()")
        check(doc.get("contract_sha256") == mo.contract_digest(), "docs schema's contract digest is stale")
    return {"contract_sha256": mo.contract_digest(), "flat_size": mo.FLAT_SIZE}


def unit_stage_table(s: Suite) -> Dict[str, Any]:
    import m7g_fixture as fx   # the stage-geometry decoder only (no crossing data is read)

    geo = fx.decode_stage_geometry()
    decoded = tuple((ln.index, fx.LINE_KINDS.index(ln.kind), ln.group, ln.flags, tuple(ln.points)) for ln in geo.lines)
    check(decoded == ms.EXPECTED_LINES, "pinned table != decomp stage source decode")
    natives = 0
    for p in sorted(EQUIV.glob("post_spatial*/tas_*.json.gz")) if EQUIV.is_dir() else []:
        import m7f_trace as mt

        snap = ms.spatial_of(mt.read_trace(p)["initial"], expect_lines=True)
        check(not ms.expected_table_problems(snap.lines or ()), f"{p}: native table differs")
        natives += 1
    segs = ms.static_segments(pinned_lines())
    check(len(segs) == 24 and [ln for ln, *_ in segs].count(14) == 3 and [ln for ln, *_ in segs].count(16) == 3,
          "24 segments (lines 14 and 16 have three pieces)")
    return {"decoded_lines": len(decoded), "native_tables_checked": natives, "segments": len(segs)}


def unit_parser(s: Suite) -> Dict[str, Any]:
    good = synth_json(synth_snapshot(), with_lines=True)
    snap = ms.parse_spatial(good, expect_lines=True)
    check(snap.lines is not None and len(snap.lines) == 20 and snap.target_live_mask == 1023, "valid object")
    step = synth_json(synth_snapshot(), with_lines=False)
    check(ms.parse_spatial(step, expect_lines=False).lines is None, "step object")
    refused = 0
    bad_cases: List[Tuple[str, Callable[[Dict[str, Any]], None]]] = [
        ("missing key", lambda j: j.pop("live")),
        ("extra key", lambda j: j.__setitem__("route", 1)),
        ("bool as int", lambda j: j.__setitem__("live", True)),
        ("wrong contract", lambda j: j.__setitem__("contract", "btt_spatial_v0")),
        ("float as int", lambda j: j.__setitem__("input_tick", 1.0)),
        ("non-finite", lambda j: j["groups"][2].__setitem__("translate", [2700.0, float("nan")])),
        ("group order", lambda j: j["groups"].reverse()),
        ("mask range", lambda j: j.__setitem__("target_live_mask", 2048)),
        ("targets short", lambda j: j["target_positions"].pop()),
        ("line id order", lambda j: j["lines"].reverse()),
        ("line vertices", lambda j: j["lines"][0].__setitem__("vertices", [])),
    ]
    for name, mutate in bad_cases:
        j = json.loads(json.dumps(good))
        mutate(j)
        try:
            ms.parse_spatial(j, expect_lines=True)
        except ms.SpatialError:
            refused += 1
            continue
        raise CaseFailure(f"parser accepted: {name}")
    try:
        ms.parse_spatial(good, expect_lines=False)
        raise CaseFailure("lines accepted in a step reply")
    except ms.SpatialError:
        refused += 1
    try:
        ms.spatial_of({"op": "step"}, expect_lines=False)
        raise CaseFailure("missing spatial object accepted")
    except ms.SpatialError:
        refused += 1
    try:
        ms.require_spatial_status({"ok": True})
        raise CaseFailure("status without spatial_diag accepted")
    except ms.SpatialError:
        refused += 1
    return {"refused": refused}


def unit_builder(s: Suite) -> Dict[str, Any]:
    b = mo.SpatialObservationBuilder(pinned_lines())
    check(b.segment_count == 24 and b.segment_index[23] == (19, 0), f"segments {b.segment_count} {b.segment_index[23]}")
    state, obs = v1_state(-1650.0, 0.0)
    snap = synth_snapshot(platform_y=2400.0, speed_y=-12.5, mask=0b1111111011)   # target 2 broken
    o, stale = b.build(state, obs, snap)
    check(not stale and mo.make_observation_space().contains(o), "space containment")
    check(o["state"].tobytes() == state.tobytes() and o["state"] is not state, "state copied byte for byte")
    seg, kind = o["segment_geometry"], o["segment_kind"]
    check(np.all(seg[24:] == 0) and np.all(kind[24:] == 0), "padding rows zero")
    check(np.all(kind[:24, 0] == 1) and np.all(kind[:24, 1:5].sum(axis=1) == 1), "present + exactly one type")
    one_way = {i for i in range(24) if kind[i, 5]}
    moving = {i for i in range(24) if kind[i, 6]}
    check(one_way == {2, 23} and moving == {23}, f"one-way {one_way} moving {moving}")
    # L13 (right face of the tall wall, x -1800 from y 2700 down to -2550): Mario at (-1650, 0) -> closest (-150, 0)
    check(np.allclose(seg[13], [-150, 2700, -150, -2550, -150, 0, 0, 0], atol=1e-6), f"L13 row {seg[13]}")
    # L0 ledge top (-2100..-1200, 3000): Mario's x lies inside its span, so the closest point is straight above
    check(np.array_equal(seg[0, 4:6], np.array([0.0, 3000.0], np.float32)), f"L0 closest {seg[0, 4:6]}")
    # L1 raised right step (2100..3300, -450): Mario is left of it, so the closest point is its left end (2100, -450)
    check(np.array_equal(seg[1, 4:6], np.array([3750.0, -450.0], np.float32)), f"L1 closest {seg[1, 4:6]}")
    # platform: local (600, 300)..(-600, 300) + (2700, 2400) -> (3300, 2700)..(2100, 2700), velocity (0, -12.5)
    check(np.array_equal(seg[23], np.array([4950, 2700, 3750, 2700, 3750, 2700, 0, -12.5], np.float32)),
          f"platform row {seg[23]}")
    check(np.all(seg[:23, 6:8] == 0), "static segments have zero velocity")
    check(o["target_live"].tolist() == [1, 1, 0, 1, 1, 1, 1, 1, 1, 1] and np.all(o["target_geometry"][2] == 0),
          f"broken target 2: {o['target_live']} {o['target_geometry'][2]}")
    check(np.allclose(o["target_geometry"][6], [-3300 + 1650, 3300]), f"target 6 {o['target_geometry'][6]}")
    # a standing floor contact: Mario on L4 at (0, -2550) -> L4 closest point (0, 0)
    st2, ob2 = v1_state(0.0, -2550.0)
    o2, _ = b.build(st2, ob2, synth_snapshot())
    check(np.array_equal(o2["segment_geometry"][4, 4:6], np.zeros(2, np.float32)), "standing on L4 -> near (0, 0)")
    # determinism and purity
    o3, _ = b.build(st2, ob2, synth_snapshot())
    check(mo.observation_digest(o2) == mo.observation_digest(o3), "repeat build differs")
    # teardown hold-last
    dead = synth_snapshot(tick=0, live=0, mask=0, platform_y=0.0)
    o4, stale4 = b.build(st2, ob2, dead)
    check(stale4 and b.stale_builds == 1 and np.array_equal(o4["target_live"], o3["target_live"])
          and np.array_equal(o4["segment_geometry"], o3["segment_geometry"]), "teardown holds the last live snapshot")
    fresh = mo.SpatialObservationBuilder(pinned_lines())
    for bad, msg in ((lambda: fresh.build(st2, ob2, dead), "first snapshot not live"),
                     (lambda: fresh.build(st2.astype(np.float64), ob2, synth_snapshot()), "float64 state"),
                     (lambda: fresh.build(st2, {**ob2, "input_tick": 5}, synth_snapshot()), "tick mismatch")):
        try:
            bad()
            raise CaseFailure(f"builder accepted: {msg}")
        except mo.ObservationV2Error:
            pass
    wrong = pinned_lines()
    wrong[0] = ms.SpatialLine(0, 0, 1, 0, 2, ((-2100.0, 3000.0), (-1100.0, 3000.0)))
    try:
        mo.SpatialObservationBuilder(wrong)
        raise CaseFailure("builder accepted a different stage table")
    except mo.ObservationV2Error:
        pass
    flat = mo.flatten(o)
    check(flat.shape == (525,) and flat.dtype == np.float32, "flatten")
    return {"digest_example": mo.observation_digest(o2)}


def unit_invariants(s: Suite) -> Dict[str, Any]:
    st, obs = v1_state(0.0, -2550.0, tick=10, targets=10)
    prev = synth_snapshot(tick=9, platform_y=2000.0, speed_y=17.0)
    good = synth_snapshot(tick=10, platform_y=2017.0, speed_y=17.0)
    check(ms.check_snapshot(good, obs, prev=prev, static_targets=STATIC_TARGETS) == [], "good snapshot flagged")
    cases = {
        "speed": synth_snapshot(tick=10, platform_y=2017.0, speed_y=16.0),
        "tick": synth_snapshot(tick=11, platform_y=2017.0, speed_y=17.0),
        "mask": synth_snapshot(tick=10, platform_y=2017.0, speed_y=17.0, mask=0b0111111111),
    }
    flagged = {k: bool(ms.check_snapshot(v, obs, prev=prev, static_targets=STATIC_TARGETS)) for k, v in cases.items()}
    moved = synth_snapshot(tick=10, platform_y=2017.0, speed_y=17.0)
    pos = list(moved.target_positions)
    pos[2] = (2700.0, 2617.5)
    pos[5] = (0.0, 301.0)
    moved = ms.SpatialSnapshot(**{**moved.__dict__, "target_positions": tuple(pos)})
    probs = ms.check_snapshot(moved, obs, prev=prev, static_targets=STATIC_TARGETS)
    flagged["target2+static"] = sum("target 2" in p or "target 5" in p for p in probs) == 2
    anomaly = ms.SpatialSnapshot(**{**good.__dict__, "anomaly_flags": 1 << 4})
    flagged["anomaly"] = any("target_mismatch" in p for p in ms.check_snapshot(anomaly, obs))
    # carry: grounded on line 19 in two consecutive replies must carry the platform speed
    plat_obs = {**obs, "ground_air_state": 0, "position_y": float(np.float32(np.float32(2017.0) + np.float32(300.0)))}
    f19 = ms.SpatialFighter(1, 19, 0, 0, 0, 0x800, 0.0, (0.0, 0.0), (320.0, 190.0, 0.0, 150.0))
    on_prev = ms.SpatialSnapshot(**{**prev.__dict__, "fighter": f19})
    on_now = ms.SpatialSnapshot(**{**good.__dict__, "fighter": f19})
    flagged["carry"] = any("carry" in p for p in ms.check_snapshot(on_now, plat_obs, prev=on_prev,
                                                                   prev_observation=plat_obs))
    flagged["landing_not_flagged"] = not any("carry" in p for p in ms.check_snapshot(on_now, plat_obs, prev=prev,
                                                                                     prev_observation=obs))
    check(all(flagged.values()), f"invariants not flagged: {flagged}")
    return flagged


def unit_isolation(s: Suite) -> Dict[str, Any]:
    files = ["m7g_obs.py", "m7g_spatial.py", "m7g_policy.py", "m7g_representations.py", "m7g_equivalence.py"]
    fixture_ref = re.compile(r"m7g_(fixture|capture|crossing)|fixtures['\"\s,/\\()]*m7g|lower_precision|"
                             r"upper_moving_platform|crossing_fixture", re.IGNORECASE)
    offenders = [f for f in files if fixture_ref.search((RL_DIR / f).read_text(encoding="utf-8"))]
    check(not offenders, f"observation modules reference the crossing fixtures: {offenders}")
    learn = [f for f in files if re.search(r"\.learn\(", (RL_DIR / f).read_text(encoding="utf-8"))]
    check(not learn, f".learn( in {learn}")
    vocab = re.compile(r"route|gateway|order|optimal|preferred|cross|left_region|goal|reward|tas|future", re.IGNORECASE)
    names = list(mo.KEY_ORDER) + list(mo.SEGMENT_GEOMETRY_FIELDS) + list(mo.SEGMENT_KIND_FIELDS) + \
        list(mo.TARGET_GEOMETRY_FIELDS)
    leaks = [n for n in names if vocab.search(n)]
    check(not leaks, f"route vocabulary in observation keys / fields: {leaks}")
    # the builder's inputs: the v1 vector, the paired observation's position / tick, the native snapshot; nothing else
    import inspect

    params = list(inspect.signature(mo.SpatialObservationBuilder.build).parameters)
    check(params == ["self", "state", "observation", "snap"], f"builder inputs {params}")
    src = inspect.getsource(mo.SpatialObservationBuilder.build)
    used = {a or b or c for a, b, c in re.findall(
        r"observation\[(?:\"([a-z_]+)\"|'([a-z_]+)'|(MARIO_REFERENCE\[\d\]))\]", src)}
    check(used == {"input_tick", "MARIO_REFERENCE[0]", "MARIO_REFERENCE[1]"} and "observation.get" not in src
          and src.count("observation[") == len(re.findall(
              r"observation\[(?:\"[a-z_]+\"|'[a-z_]+'|MARIO_REFERENCE\[\d\])\]", src)),
          f"observation fields read by the builder: {used}")
    return {"checked_files": files, "names": len(names)}


class SyntheticV2Env(gym.Env):
    """In-memory env with the v2 space: Mario moves by the stick, targets break by proximity. No game."""

    metadata: Dict[str, Any] = {}

    def __init__(self, horizon: int = 40):
        self.observation_space = mo.make_observation_space()
        self.action_space = spaces.MultiDiscrete([9, 8])
        self.horizon = horizon
        self.builder = mo.SpatialObservationBuilder(pinned_lines())

    def _obs(self) -> Dict[str, np.ndarray]:
        py = 1500.0 + 1800.0 * (0.5 - 0.5 * np.cos(np.pi * (self.t % 300) / 150.0))
        state, obs = v1_state(self.x, self.y, tick=self.t, targets=bin(self.mask).count("1"))
        o, _ = self.builder.build(state, obs, synth_snapshot(tick=self.t, platform_y=float(py), mask=self.mask))
        return o

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        super().reset(seed=seed)
        self.t, self.x, self.y, self.mask = 0, 0.0, -2550.0, 1023
        return self._obs(), {}

    def step(self, action):
        from btt_learning import TRACK1_STICK_TABLE

        sx, sy = TRACK1_STICK_TABLE[int(action[0])]
        self.x += sx * 0.5
        self.y = min(max(self.y + sy * 0.5, -2550.0), 3000.0)
        self.t += 1
        r = 0.0
        for i, (tx, ty) in STATIC_TARGETS.items():
            if self.mask & (1 << i) and abs(tx - self.x) < 150 and abs(ty - self.y) < 300:
                self.mask &= ~(1 << i)
                r += 1.0
        return self._obs(), r, False, self.t >= self.horizon, {}


def unit_sb3_dummy(s: Suite) -> Dict[str, Any]:
    import torch
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

    import m7g_policy as mp

    torch.set_num_threads(1)
    d = s.dir("unit_sb3_dummy")
    venv = mp.make_vecnormalize(DummyVecEnv([lambda: SyntheticV2Env(), lambda: SyntheticV2Env()]))
    check(set(venv.obs_rms.keys()) == set(mo.NORMALIZED_KEYS), f"obs_rms keys {list(venv.obs_rms)}")
    check(venv.observation_space == mo.make_observation_space(), "VecNormalize changed the space (image conversion?)")
    model = mp.make_model(venv, seed=3, n_steps=16, batch_size=16)
    desc = mp.describe(model)
    check(desc["policy_class"] == "MultiInputActorCriticPolicy" and desc["features_extractor"] == "CombinedExtractor"
          and desc["features_dim"] == 525 and desc["parameters"] == 76818
          and desc["parameters_by_module"]["features_extractor"] == 0 and desc["activation"] == "Tanh",
          f"network {desc}")
    obs = venv.reset()
    raw = venv.get_original_obs()
    for k in mo.BINARY_KEYS:
        check(np.array_equal(obs[k], raw[k]), f"binary key {k} was normalised")
    for _ in range(20):
        act, _ = model.predict(obs, deterministic=False)
        obs, _r, _d, _i = venv.step(act)
    counts = {k: float(v.count) for k, v in venv.obs_rms.items()}
    check(all(c > 20 for c in counts.values()), f"statistics not updated: {counts}")
    with torch.no_grad():
        t_obs, _ = model.policy.obs_to_tensor(obs)
        values = model.policy.predict_values(t_obs).numpy()
    model.save(d / "model.zip")
    venv.save(str(d / "vecnormalize.pkl"))
    mp.assert_v2_checkpoint(d / "model.zip")
    # reload: identical deterministic actions and values on identical normalised observations
    venv2 = VecNormalize.load(str(d / "vecnormalize.pkl"), DummyVecEnv([lambda: SyntheticV2Env(), lambda: SyntheticV2Env()]))
    venv2.training = False
    venv2.norm_reward = False
    model2 = PPO.load(d / "model.zip", env=venv2, device="cpu")
    with torch.no_grad():
        check(np.array_equal(model2.policy.predict_values(model2.policy.obs_to_tensor(obs)[0]).numpy(), values),
              "values differ after reload")
    a1, _ = model.predict(obs, deterministic=True)
    a2, _ = model2.predict(obs, deterministic=True)
    check(np.array_equal(a1, a2), "deterministic actions differ after reload")
    # frozen evaluation: statistics unchanged while stepping
    before = {k: (v.mean.copy(), v.var.copy(), float(v.count)) for k, v in venv2.obs_rms.items()}
    o2 = venv2.reset()
    for _ in range(15):
        a, _ = model2.predict(o2, deterministic=True)
        o2, _r, _d, _i = venv2.step(a)
    after = {k: (v.mean, v.var, float(v.count)) for k, v in venv2.obs_rms.items()}
    check(all(np.array_equal(before[k][0], after[k][0]) and np.array_equal(before[k][1], after[k][1])
              and before[k][2] == after[k][2] for k in before), "frozen VecNormalize statistics changed")
    # a v1 (Box(15)) checkpoint is refused for v2, and cannot be loaded onto a v2 environment
    from btt_learning import make_policy_observation_space

    class V1Env(gym.Env):
        observation_space = make_policy_observation_space()
        action_space = spaces.MultiDiscrete([9, 8])

        def reset(self, *, seed=None, options=None):
            return np.zeros(15, np.float32), {}

        def step(self, a):
            return np.zeros(15, np.float32), 0.0, False, True, {}

    v1 = PPO("MlpPolicy", DummyVecEnv([V1Env]), n_steps=16, batch_size=16, device="cpu", seed=0)
    v1.save(d / "v1_model.zip")
    try:
        mp.assert_v2_checkpoint(d / "v1_model.zip")
        raise CaseFailure("a v1 checkpoint passed the v2 check")
    except ValueError:
        pass
    try:
        PPO.load(d / "v1_model.zip", env=venv2, device="cpu")
        raise CaseFailure("a v1 checkpoint loaded onto a v2 environment")
    except (ValueError, KeyError, AssertionError):
        pass
    return {"network": desc, "obs_rms_counts": counts}


def unit_offline_traces(s: Suite) -> Dict[str, Any]:
    import m7g_equivalence as me

    dirs = sorted(p for p in EQUIV.glob("post_spatial*") if (p / "summary.json").is_file()) if EQUIV.is_dir() else []
    if not dirs:
        return {"skipped": f"no M7g-b capture sets under {EQUIV} (run m7g_equivalence.py capture)"}
    r = me.validate(dirs)
    bad = {Path(d).name + "/" + n: v["problems"][:2] for d, sets in r["sets"].items() for n, v in sets.items()
           if v["problem_count"] or v["state_bytes_mismatch"] or not v["v2_contained"]}
    check(not bad and all(g["identical"] for g in r["v2_determinism"].values()), f"offline validation: {bad}")
    return {"sets": [p.name for p in dirs], "groups": {k: v["runs"] for k, v in r["v2_determinism"].items()}}


# -- game -----------------------------------------------------------------------------------------------------------

def _artifact_track1(name: str = ARTIFACT) -> Tuple[List[Tuple[int, int, int, Optional[int]]], List[np.ndarray]]:
    import m7f_trace as mt
    from btt_learning import native_to_track1

    acts, _md = mt.artifact_actions(REPO_ROOT / dict(mt.FIXTURE_ARTIFACTS)[name])
    return acts, [np.array(native_to_track1(b, x, y)) for b, x, y, _ in acts]


def _m5_v2_env(root: Path, *, check_invariants: bool = True) -> Tuple[Any, Any]:
    import btt_learning as bl

    cfg = bl.LearningEnvConfig(executable=str(EXECUTABLE), artifact_root=root / "artifacts",
                               episodes_root=root / "episodes", max_episode_steps=3600,
                               extra_env={**FLAGS, ms.SPATIAL_ENV: "1"})
    env = bl.make_learning_env(cfg)
    return env, mo.SpatialObsV2Wrapper(env, base=env.base_env, check_invariants=check_invariants)


def game_wrapper_vs_raw(s: Suite) -> Dict[str, Any]:
    import m7f_trace as mt
    import m7g_equivalence as me
    from btt_learning import policy_observation

    d = s.dir("game_wrapper_vs_raw")
    acts, t1 = _artifact_track1()
    env, v2 = _m5_v2_env(d / "wrapper")
    digests: List[str] = []
    try:
        o, info = v2.reset()
        check(info["policy_observation_contract"] == mo.OBS_CONTRACT and v2.base.last_observe.step_count == 0,
              "reset contract / step count")
        digests.append(mo.observation_digest(o))
        state_mismatch = 0
        steps = 0
        for a in t1:
            o, _r, term, trunc, info = v2.step(a)
            steps += 1
            if o["state"].tobytes() != policy_observation(info["m3_observation"]).tobytes():
                state_mismatch += 1
            digests.append(mo.observation_digest(o))
            if term or trunc:
                break
        problems = list(v2.invariant_problems)
    finally:
        env.close()
    check(state_mismatch == 0 and not problems, f"state mismatches {state_mismatch}, invariant problems {problems[:3]}")
    raw = mt.run_stepping_trace("raw", EXECUTABLE, acts, d / "raw", extra_env={**FLAGS, ms.SPATIAL_ENV: "1"})
    obs_list, _stale, meta = me.v2_observations(raw)
    offline = [mo.observation_digest(x) for x in obs_list]
    check(len(offline) == len(digests) and offline == digests,
          f"wrapper vs offline v2 differ (first at {next((i for i, (x, y) in enumerate(zip(offline, digests)) if x != y), None)})")
    from m7_runtime import list_processes_named

    check(not list_processes_named(), "leftover BattleShip")
    chain = hashlib.sha256("".join(digests).encode("ascii")).hexdigest()
    return {"steps": steps, "v2_observations": len(digests), "chain": chain, "stale": sum(_stale),
            "raw_meta": meta}


def _v2_worker_specs(base: Path, n: int, run_id: str, *, v2: bool, standby: bool, **kw: Any) -> Tuple[List[Any], Path]:
    from btt_parallel import RunCoordinator, WorkerFactory, WorkerSpec, initial_coordination_state
    from m7_runtime import prepare_worker_runtime

    coord = base / "coordination"
    RunCoordinator.create(coord, initial_coordination_state(run_id, "test", None))
    extra = tuple(FLAGS.items()) + (mo.SPATIAL_EXTRA_ENV if v2 else ())
    factories = []
    for rank in range(n):
        wd = base / "workers" / f"w{rank:02d}"
        prepare_worker_runtime(wd / "runtime", EXECUTABLE)
        spec = WorkerSpec(rank=rank, run_id=run_id, role="test", worker_dir=str(wd.resolve()),
                          coordination_dir=str(coord.resolve()), executable=str(EXECUTABLE), horizon=3600,
                          extra_env=extra, standby_preboot=standby, standby_count=1 if standby else 0, **kw)
        factories.append(mo.M7gWorkerFactory(spec) if v2 else WorkerFactory(spec))
    return factories, coord


def game_standby_v2(s: Suite) -> Dict[str, Any]:
    from m7_runtime import list_processes_named
    from run_artifacts import read_artifact

    d = s.dir("game_standby_v2")
    _acts, t1 = _artifact_track1()
    factories, _coord = _v2_worker_specs(d, 1, "m7g_standby_v2", v2=True, standby=True, preserve_all=True)
    env = factories[0]()
    episodes = []
    try:
        for ep in range(2):
            o, info = env.reset()
            chain = hashlib.sha256()
            chain.update(mo.observation_digest(o).encode())
            reset_digest = mo.observation_digest(o)
            first_consumed = None
            n = 0
            for a in t1:
                o, _r, term, trunc, info = env.step(a)
                if first_consumed is None:
                    first_consumed = env.base.last_step_result.consumed_tick
                chain.update(mo.observation_digest(o).encode())
                n += 1
                if term or trunc:
                    break
            episodes.append({"mode": info.get("m7_episode", {}).get("startup_mode") or
                             (env.base.current_startup or {}).get("mode"), "steps": n, "chain": chain.hexdigest(),
                             "reset_digest": reset_digest, "first_consumed_tick": first_consumed,
                             "stale": env.env.env.stale_steps})
    finally:
        env.close()
    modes = [e["mode"] for e in episodes]
    check(modes == ["cold_start", "standby_promoted"], f"modes {modes}")
    check(episodes[0]["chain"] == episodes[1]["chain"] and episodes[0]["reset_digest"] == episodes[1]["reset_digest"],
          "cold vs promoted v2 observations differ")
    check(all(e["first_consumed_tick"] == 0 for e in episodes), f"first consumed ticks {episodes}")
    arts = sorted((d / "workers" / "w00" / "artifacts").iterdir())
    labels = [read_artifact(a).metadata["labels"]["contracts"]["policy_observation_contract"] for a in arts]
    check(len(arts) == 2 and labels == [mo.OBS_CONTRACT] * 2, f"artifact labels {labels}")
    check(not list_processes_named(), "leftover BattleShip")
    return {"episodes": episodes}


def game_sb3_real(s: Suite) -> Dict[str, Any]:
    import torch
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

    import m7g_policy as mp
    from m7_runtime import list_processes_named

    torch.set_num_threads(1)
    d = s.dir("game_sb3_real")
    holder: Dict[str, Any] = {}

    def make():
        env, v2 = _m5_v2_env(d / f"env{len(holder)}", check_invariants=True)
        holder[len(holder)] = env
        return v2

    venv = mp.make_vecnormalize(DummyVecEnv([make]))
    out: Dict[str, Any] = {}
    try:
        model = mp.make_model(venv, seed=0)
        out["network"] = mp.describe(model)
        obs = venv.reset()
        raw = venv.get_original_obs()
        check(all(np.array_equal(obs[k], raw[k]) for k in mo.BINARY_KEYS), "binary keys normalised")
        check(raw["state"].shape == (1, 15) and raw["target_live"].sum() == 10, "reset observation")
        with torch.no_grad():
            actions, values, logp = model.policy(model.policy.obs_to_tensor(obs)[0])
        out["first_forward"] = {"action": actions.numpy().tolist(), "value": float(values[0, 0])}
        for _ in range(200):
            a, _ = model.predict(obs, deterministic=True)
            obs, _r, done, _i = venv.step(a)
        counts = {k: float(v.count) for k, v in venv.obs_rms.items()}
        check(set(counts) == set(mo.NORMALIZED_KEYS) and all(c >= 200 for c in counts.values()), f"counts {counts}")
        model.save(d / "model.zip")
        venv.save(str(d / "vecnormalize.pkl"))
        mp.assert_v2_checkpoint(d / "model.zip")
        frozen = VecNormalize.load(str(d / "vecnormalize.pkl"), venv.venv)
        frozen.training = False
        frozen.norm_reward = False
        model2 = PPO.load(d / "model.zip", env=frozen, device="cpu")
        o = frozen.reset()
        before = {k: float(v.count) for k, v in frozen.obs_rms.items()}
        same = 0
        for _ in range(100):
            a1, _ = model.predict(o, deterministic=True)
            a2, _ = model2.predict(o, deterministic=True)
            same += int(np.array_equal(a1, a2))
            o, _r, _d, _i = frozen.step(a2)
        check(same == 100, f"reloaded model disagrees on {100 - same}/100 observations")
        check({k: float(v.count) for k, v in frozen.obs_rms.items()} == before, "frozen statistics changed")
        out["obs_rms_counts"] = counts
    finally:
        venv.close()
        for env in holder.values():
            env.close()
    check(not list_processes_named(), "leftover BattleShip")
    return out


def _bench_arm(root: Path, v2: bool, steps: int, seed: int) -> Dict[str, Any]:
    from m7_runtime import list_processes_named
    from m7_vec_env import M7SubprocVecEnv

    factories, _coord = _v2_worker_specs(root, 5, f"m7g_bench_{'v2' if v2 else 'v1'}", v2=v2, standby=True)
    venv = M7SubprocVecEnv(factories, step_timeout=240.0)
    rng = np.random.default_rng(seed)       # Python-side action sampling only
    peak = 0
    try:
        obs = venv.reset()
        t0 = time.perf_counter()
        episodes = 0
        for i in range(steps):
            acts = np.stack([rng.integers(0, 9, 5), rng.integers(0, 8, 5)], axis=1)
            obs, _r, dones, _infos = venv.step(acts)
            episodes += int(dones.sum())
            if i % 250 == 0:
                peak = max(peak, len(list_processes_named()))
        dt = time.perf_counter() - t0
    finally:
        venv.close()
    left = list_processes_named()
    from btt_parallel import LatencyHistogram

    reports = [r for r in venv.worker_reports().values() if r]
    native = LatencyHistogram.merged([r.get("native_step_hist") for r in reports])
    service = LatencyHistogram.merged([r.get("service_hist") for r in reports])
    return {"v2": v2, "vec_steps": steps, "transitions": steps * 5, "seconds": round(dt, 2),
            "transitions_per_s": round(steps * 5 / dt, 1), "episodes_finished": episodes,
            "peak_processes": peak, "leftover": left,
            "worker_native_step_mean_ms": round(native["sum_s"] / max(native["n"], 1) * 1e3, 4),
            "worker_service_mean_ms": round(service["sum_s"] / max(service["n"], 1) * 1e3, 4),
            "worker_python_overhead_mean_ms": round((service["sum_s"] / max(service["n"], 1)
                                                     - native["sum_s"] / max(native["n"], 1)) * 1e3, 4),
            "obs_keys": sorted(obs.keys()) if isinstance(obs, dict) else [str(np.shape(obs))]}


def game_n5_standby_bench(s: Suite) -> Dict[str, Any]:
    d = s.dir("game_n5_standby_bench")
    arms = []
    for rep, v2 in ((0, False), (0, True), (1, True), (1, False)):
        arms.append(_bench_arm(d / f"{'v2' if v2 else 'v1'}_{rep}", v2, BENCH_VEC_STEPS, seed=rep))
    for a in arms:
        check(a["peak_processes"] <= 10 and not a["leftover"], f"processes: {a}")
    v1 = [a["transitions_per_s"] for a in arms if not a["v2"]]
    v2 = [a["transitions_per_s"] for a in arms if a["v2"]]
    per = {k: {"v1": round(float(np.mean([a[k] for a in arms if not a["v2"]])), 4),
               "v2": round(float(np.mean([a[k] for a in arms if a["v2"]])), 4)}
           for k in ("worker_native_step_mean_ms", "worker_service_mean_ms", "worker_python_overhead_mean_ms")}
    return {"arms": arms, "v1_mean": round(float(np.mean(v1)), 1), "v2_mean": round(float(np.mean(v2)), 1),
            "v2_relative": round(float(np.mean(v2)) / float(np.mean(v1)), 4), "worker_times": per,
            "note": "random Track 1 actions, no policy inference, no learning: environment-side throughput only"}


UNIT_CASES: Dict[str, Callable[[Suite], Dict[str, Any]]] = {
    "unit_contract": unit_contract, "unit_stage_table": unit_stage_table, "unit_parser": unit_parser,
    "unit_builder": unit_builder, "unit_invariants": unit_invariants, "unit_isolation": unit_isolation,
    "unit_sb3_dummy": unit_sb3_dummy, "unit_offline_traces": unit_offline_traces,
}
GAME_CASES: Dict[str, Callable[[Suite], Dict[str, Any]]] = {
    "game_wrapper_vs_raw": game_wrapper_vs_raw, "game_standby_v2": game_standby_v2, "game_sb3_real": game_sb3_real,
    "game_n5_standby_bench": game_n5_standby_bench,
}
ALL_CASES = {**UNIT_CASES, **GAME_CASES}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cases", nargs="*", help="case names, 'unit' or 'game' (default: all)")
    ap.add_argument("--root", default=None)
    args = ap.parse_args(argv)
    names: List[str] = []
    for c in args.cases or list(ALL_CASES):
        names += list(UNIT_CASES) if c == "unit" else list(GAME_CASES) if c == "game" else [c]
    unknown = [n for n in names if n not in ALL_CASES]
    if unknown:
        ap.error(f"unknown cases {unknown}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = (Path(args.root) if args.root else REPO_ROOT / "runs" / "m7g_obs" / f"_tests_{stamp}").resolve()
    root.mkdir(parents=True, exist_ok=True)
    if any(n in GAME_CASES for n in names):
        import os

        from m7_runtime import install_kill_on_close_job

        leaked = sorted(k for k in os.environ if k.upper().startswith("SSB64_"))
        if leaked:
            raise SystemExit(f"SSB64_* variables in the environment would leak into every child: {leaked}")
        install_kill_on_close_job()
    suite = Suite(root)
    results: Dict[str, Any] = {}
    for name in names:
        t0 = time.perf_counter()
        try:
            details = ALL_CASES[name](suite)
            results[name] = {"status": "PASS", "seconds": round(time.perf_counter() - t0, 1), "details": details}
        except Exception as exc:
            results[name] = {"status": "FAIL", "seconds": round(time.perf_counter() - t0, 1),
                             "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()[-2000:]}
        print(f"{results[name]['status']}  {name}  ({results[name]['seconds']} s)"
              + (f"  {results[name].get('error')}" if results[name]["status"] != "PASS" else ""), flush=True)
    ok = all(r["status"] == "PASS" for r in results.values())
    (root / "m7g_obs_tests_results.json").write_text(json.dumps({"schema": "battleship_m7g_obs_tests_v1", "utc": stamp,
                                                                 "results": results, "ok": ok}, indent=1, default=str)
                                                     + "\n", encoding="utf-8", newline="\n")
    print(f"m7g_obs_tests: {sum(r['status'] == 'PASS' for r in results.values())}/{len(results)} PASS -> {root}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
