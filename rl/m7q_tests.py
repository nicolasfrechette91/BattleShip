"""M7q permanent tests: btt_input_state_v1 reader, the action-class table v2 and btt_policy_obs_v4_input.

Unit cases (no game):
    unit_contract            v4 space: keys, sorted order, shapes (23 / 45), flat 626, mask columns, digest == docs schema;
                             v1 / v2 / v3 / geo4 constants and digests unchanged; table v2 equals a fresh derivation,
                             differs from v1 in exactly the 11 registered common ids, Mario mapping, aerial ids, unmapped
    unit_input_parser        strict btt_input_state_v1 parsing (missing / extra keys, booleans, wrong contract refused);
                             check_snapshot flags tap 0, forbidden bits, a fold violation, a band mismatch, a Z jump
    unit_builder             synthetic replies: indices 0-27 bit-identical to the v3 builder; every appended encoding
                             (stick, the 7 hold bits incl. the R fold, the 5-level taps, z_age grid / z_out, anim clip,
                             aerial gating by status, contact_edge); stale rule; anomaly counting; masked rows zero
    unit_offline_traces      every M7q capture set with the input object (runs/m7q/_equiv/input_all*): parse, spatial +
                             entity + input invariants, v4 builds, contained / finite, masked rows zero, v3 slice equals the
                             v3 builder's chain, determinism across host modes and the repeat, no unmapped id, the landing
                             class of every recorded aerial landing equals the source rule evaluated on the landing tick's
                             own counter (flag1 of the last airborne tick, tics_since_last_z of the landing reply), with the
                             boundary coverage (previous counter 9 / 10, Z edge on the landing tick) reported, tick-0 record
    unit_landing_boundary    synthetic: the source rule of ftcommonattackair.c:63 at the Z boundary (previous counter 9, 10,
                             11 with and without a Z / R edge on the landing tick) and what the v4 encodings of the previous
                             tick (z_age, z_out) can and cannot tell about it
    unit_oracle              the action oracle (rl/m7q_equivalence.validate) holds on every input_all capture
    unit_sb3_dummy           synthetic Dict env: MultiInputPolicy init (parameter count 89,746), forward, save / reload
                             identical predictions, VecNormalize(norm_obs=False) is the identity, a v3 checkpoint refused
    unit_config              strict TOML / M7Config rejection on the v4 profile; v4 resolves with the three flags; v1 / v2 /
                             v3 profiles' flags and identity blocks unchanged
    unit_isolation           M7q modules never reference the crossing fixtures, route vocabulary, learn() or an action mask
Game cases (fresh BattleShip processes, one case at a time):
    game_wrapper_vs_raw      M5 stack + v4 wrapper (invariants on) on a horizon artifact and a fall artifact: 0 invariant
                             problems, stale only on a fall's terminal reply, first step consumes tick 0, every wrapper
                             observation equals the offline rebuild from a separate raw trace of the same actions
    game_standby_v4          worker stack v4 with one standby: cold_start then standby_promoted episodes give identical v4
                             observations; first step consumes tick 0; artifact labels record the v4 contract

Usage: python rl/m7q_tests.py [unit|game|<case> ...] [--root runs/m7q/_tests/m7q_<utc>]
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
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import gymnasium as gym  # noqa: E402
import numpy as np  # noqa: E402
from gymnasium import spaces  # noqa: E402

import m7g_spatial as ms  # noqa: E402
import m7n_entity as ne  # noqa: E402
import m7n_obs as mn  # noqa: E402
import m7n_status_table as st1  # noqa: E402
import m7q_equivalence as mqe  # noqa: E402
import m7q_input as mi  # noqa: E402
import m7q_obs as mq  # noqa: E402
import m7q_policy as mqp  # noqa: E402
import m7q_status_table as st2  # noqa: E402

REPO_ROOT = RL_DIR.parent
EXECUTABLE = REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"
EQUIV = REPO_ROOT / "runs" / "m7q" / "_equiv"
SCHEMA_DOC = REPO_ROOT / "docs" / "rl_observation_v4_m7q.schema.json"
FLAGS = {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1"}
V4_FLAGS = {**FLAGS, **dict(mq.ENTITY_EXTRA_ENV)}
ARTIFACT_HORIZON = "m7e_s0_best6"
ARTIFACT_FALL = "m7d_s0v1_det_fall"
V2_DIGEST = "dcfd14b276c3d9f38f180888c132febb67ace39797bdef2aefb185e024c8c0cb"
V3_DIGEST = "4ddc2933a41410ecf2009b464a706fc0e6e6de4fbad300608d04bd1d1f7b3297"
V1_TABLE_SHA = "97db115242c58c2a18b70c03adcdf4f2556728e501fe87858f9f7b1c83229ea4"
V4_PROFILE = RL_DIR / "configs" / "m7q" / "m7q_pilot_s0.toml"
V3_PROFILE = RL_DIR / "configs" / "m7n" / "m7n_s0_v3.toml"
V1_PROFILE = RL_DIR / "configs" / "m7g" / "m7g_s0_v1.toml"
V2_PROFILE = RL_DIR / "configs" / "m7g" / "m7g_s0_v2.toml"
V4_PARAMETERS = 89746   # v3's 87,186 + 20 extra inputs x 64 x 2 (pi and vf first layers)
EXPECTED_V2_CHANGES = {"31": "landing_free", "32": "landing_free", "58": "helpless", "59": "landing_lag", "66": "air_lock",
                       "214": "landing_lag", "215": "landing_lag", "216": "landing_lag", "217": "landing_lag",
                       "218": "landing_lag", "219": "landing_lag"}
# the audit's measured Mario landing-lag durations (docs/rl_mechanics_observation_audit_2026-09-28.md section 7.1)
LANDING_LAG_TICKS = {219: 14, 215: 30, 216: 15, 217: 40, 59: 25}   # LandingAirNull (nair) 14; fair 30; bair 15; uair 40; up-B 25
# (dair lands in LandingAirNull at 0.2 -> 35 ticks, indistinguishable by id from nair's 14: checked by speed below)


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

def _m7n_tests():
    import m7n_tests as nt

    return nt


def input_json(*, tick: int, stick: Tuple[int, int] = (0, 0), hold: int = 0, tap: int = 0, release: int = 0,
               taps: Tuple[int, int] = (254, 254), holds: Tuple[int, int] = (254, 254), z: int = 65536,
               anim_frame: float = 0.0, anim_speed: float = 1.0, flag1: int = 0, live: int = 1, valid: int = 1
               ) -> Dict[str, Any]:
    return {"contract": mi.CONTRACT, "input_schema": 1, "input_tick": tick, "scene_active": 1, "live": live, "valid": valid,
            "stick_x": stick[0], "stick_y": stick[1], "button_hold": hold, "button_tap": tap, "button_release": release,
            "tap_stick_x": taps[0], "tap_stick_y": taps[1], "hold_stick_x": holds[0], "hold_stick_y": holds[1],
            "tics_since_last_z": z, "anim_frame": anim_frame, "anim_speed": anim_speed, "motion_flag1": flag1}


def builders() -> Tuple[mn.EntityObservationBuilder, mq.InputObservationBuilder]:
    gt = _m7n_tests()._synth()
    lines = gt.pinned_lines()
    t1, t2 = st1.load_table(), st2.load_table()
    b3 = mn.EntityObservationBuilder(lines, st1.ActionClassifier(t1, "mario"))
    b4 = mq.InputObservationBuilder(lines, st1.ActionClassifier(t1, "mario"), st2.ActionClassifier(t2, "mario"),
                                    st2.aerial_attack_ids(t2))
    return b3, b4


# -- unit ---------------------------------------------------------------------------------------------------------

def unit_contract(s: Suite) -> Dict[str, Any]:
    import m7g_obs as mo
    import m7p_obs_geo4 as mgeo
    from btt_learning import POLICY_OBSERVATION_SIZE, make_policy_observation_space

    space = mq.make_observation_space()
    check(tuple(space.spaces.keys()) == mq.KEY_ORDER == mn.KEY_ORDER == tuple(sorted(mq.KEY_ORDER)), "key order")
    for k, shape in mq.SHAPES.items():
        b = space.spaces[k]
        check(isinstance(b, spaces.Box) and b.shape == shape and b.dtype == np.float32, f"{k} space")
    check(mq.SHAPES[mq.ACTION_CLASS_KEY] == (23,) and mq.SHAPES[mq.AGENT_KEY] == (45,), "changed shapes")
    for k in (mq.PROJECTILES_KEY, mq.SEGMENT_GEOMETRY_KEY, mq.SEGMENT_KIND_KEY, mq.TARGETS_KEY):
        check(mq.SHAPES[k] == mn.SHAPES[k], f"{k} shape changed")
    check(mq.FLAT_SIZE == 626 and sum(int(np.prod(v)) for v in mq.SHAPES.values()) == 626
          and 23 + 45 + 28 + 256 + 224 + 50 == 626, "flat size")
    check(len(mq.AGENT_FIELDS) == 45 and mq.AGENT_FIELDS[:28] == mn.AGENT_FIELDS and len(mq.APPENDED_FIELDS) == 17
          and len(st2.CLASSES) == 23, "field counts")
    check(mq.AGENT_FIELDS[17] == "status_id" and mq.AGENT_FIELDS[18] == "status_tics", "v3 raw status scalar position")
    check(mq.AGENT_FIELDS[28:] == ("stick_x", "stick_y", "hold_A", "hold_B", "hold_Z", "hold_L", "hold_R", "hold_Cup",
                                    "hold_Cleft", "tap_x", "tap_y", "z_age", "z_out", "anim_frame", "anim_speed",
                                    "aerial_lag_armed", "contact_edge"), f"appended order {mq.AGENT_FIELDS[28:]}")
    check(all(mq.MASK_COLUMNS[k] < mq.SHAPES[k][1] for k in mq.MASK_COLUMNS), "mask columns")
    doc = json.loads(SCHEMA_DOC.read_text(encoding="utf-8"))
    check(doc["contract_sha256"] == mq.contract_digest() and doc["contract"] == mq.contract_description(),
          "docs schema differs from the code contract (python rl/m7q_obs.py schema)")
    # v1 / v2 / v3 / geo4 unchanged
    check(POLICY_OBSERVATION_SIZE == 15 and make_policy_observation_space().shape == (15,), "v1 constants")
    check(mo.FLAT_SIZE == 525 and mo.contract_digest() == V2_DIGEST, f"v2 digest {mo.contract_digest()}")
    check(mn.FLAT_SIZE == 606 and mn.contract_digest() == V3_DIGEST, f"v3 digest {mn.contract_digest()}")
    check(mgeo.FLAT_SIZE == 606 and mgeo.contract_digest() != mn.contract_digest(), "geo4 identity")
    check(mq.contract_digest() not in (V2_DIGEST, V3_DIGEST, mgeo.contract_digest()), "v4 digest collides")
    # tables
    t1, t2 = st1.load_table(), st2.load_table()
    check(t1["sha256"] == V1_TABLE_SHA and t1 == st1.derive(), "table v1 changed")
    check(t2 == st2.derive() and t2["table_id"] == st2.TABLE_ID and t2["derived_from"] == st1.TABLE_ID, "table v2 derivation")
    diff = st2.diff_v1(t2)
    check({k: v["v2"] for k, v in diff["common"].items()} == EXPECTED_V2_CHANGES and diff["characters"] == {},
          f"v2 differs from v1 elsewhere than registered: {json.dumps(diff)[:600]}")
    clf = st2.ActionClassifier(t2, "mario")
    want = {10: "idle_ground", 20: "jump_squat", 22: "airborne", 26: "airborne", 27: "airborne", 58: "helpless",
            66: "air_lock", 31: "landing_free", 32: "landing_free", 214: "landing_lag", 219: "landing_lag",
            59: "landing_lag", 209: "attack_air", 213: "attack_air", 225: "special_hi", 226: "special_hi",
            227: "special_lw", 228: "special_lw", 152: "shield", 157: "roll"}
    got = {i: clf.name(i) for i in want}
    check(got == want, f"Mario v2 mapping {got}")
    check(st2.aerial_attack_ids(t2) == (209, 210, 211, 212, 213), f"aerial ids {st2.aerial_attack_ids(t2)}")
    check("59" in t2["character_dependent"] and t2["character_dependent"]["59"]["class"] == "landing_lag",
          "LandingFallSpecial not recorded as character-dependent")
    check(clf.name(9999) == st2.UNMAPPED and clf.unmapped_seen == {9999: 1} and clf.validated, "unmapped fallback")
    check(not st2.ActionClassifier(t2, "link").validated, "link validated")
    try:
        st2.ActionClassifier(t1, "mario")
        raise CaseFailure("v1 table accepted by the v2 classifier")
    except ValueError:
        pass
    return {"flat_size": mq.FLAT_SIZE, "digest": mq.contract_digest(), "table_v2_sha256": t2["sha256"],
            "v2_changes": EXPECTED_V2_CHANGES}


def unit_input_parser(s: Suite) -> Dict[str, Any]:
    good = input_json(tick=5, stick=(80, 0), hold=0x8000, tap=0x8000, taps=(1, 254), holds=(1, 254), z=3)
    snap = mi.parse_input(good)
    check(snap.tap_stick_x == 1 and snap.button_hold == 0x8000 and snap.tics_since_last_z == 3, "parse")
    refused: Dict[str, str] = {}
    bad = {"missing": {k: v for k, v in good.items() if k != "tap_stick_x"}, "extra": {**good, "x": 1},
           "bool": {**good, "valid": True}, "contract": {**good, "contract": "btt_input_state_v0"},
           "schema": {**good, "input_schema": 2}, "stick_range": {**good, "stick_x": 200}, "hold_range": {**good, "button_hold": 70000}}
    for name, obj in bad.items():
        try:
            mi.parse_input(obj)
            raise CaseFailure(f"{name}: accepted")
        except mi.InputError as exc:
            refused[name] = str(exc)[:80]
    obs = {"input_tick": 5, "fighter_valid": 1}
    check(mi.check_snapshot(snap, obs) == [], f"good snapshot flagged {mi.check_snapshot(snap, obs)}")
    flagged = {
        "tap_zero": mi.parse_input(input_json(tick=5, stick=(80, 0), taps=(0, 254), holds=(1, 254))),
        "forbidden": mi.parse_input(input_json(tick=5, hold=0x0004)),
        "fold": mi.parse_input(input_json(tick=5, hold=0x0010)),
        "band": mi.parse_input(input_json(tick=5, stick=(0, 0), taps=(3, 254), holds=(3, 254))),
        "tick": mi.parse_input(input_json(tick=6)),
    }
    for name, sn in flagged.items():
        check(mi.check_snapshot(sn, obs) != [], f"{name}: not flagged")
    prev = mi.parse_input(input_json(tick=4, z=7))
    jump = mi.parse_input(input_json(tick=5, z=20))
    check(mi.check_snapshot(jump, obs, prev=prev, prev_observation={"input_tick": 4, "fighter_status_id": 26}) != [],
          "Z timer jump not flagged")
    ok_next = mi.parse_input(input_json(tick=5, z=8))
    check(mi.check_snapshot(ok_next, obs, prev=prev, prev_observation={"input_tick": 4, "fighter_status_id": 26}) == [],
          "Z timer +1 flagged")
    check(mi.fold_buttons(0x0010) == 0xA010 and mi.fold_buttons(0x8000) == 0x8000, "fold")
    check(mi.step_tap_counter(254, 0, 80) == 1 and mi.step_tap_counter(1, 80, 80) == 2 and mi.step_tap_counter(254, 80, 80) == 254
          and mi.step_tap_counter(5, -80, 80) == 1 and mi.step_tap_counter(5, 80, 0) == 254, "tap counter rule")
    return {"refused": refused}


def unit_builder(s: Suite) -> Dict[str, Any]:
    nt = _m7n_tests()
    gt = nt._synth()
    b3, b4 = builders()
    space = mq.make_observation_space()
    o0 = nt.observation(0.0, -2550.0, 0)
    sp0 = gt.synth_snapshot(tick=0)
    en0 = ne.parse_entity(nt.entity_json(tick=0))
    in0 = mi.parse_input(input_json(tick=0))
    v3, st3 = b3.build(o0, sp0, en0)
    v4, st4 = b4.build(o0, sp0, en0, in0)
    check(not st3 and not st4 and space.contains(v4), "reset build")
    check(np.array_equal(v4[mq.AGENT_KEY][:28], v3[mn.AGENT_KEY]), "v3 slice not bit-identical")
    for k in (mq.PROJECTILES_KEY, mq.SEGMENT_GEOMETRY_KEY, mq.SEGMENT_KIND_KEY, mq.TARGETS_KEY):
        check(np.array_equal(v4[k], v3[k]), f"{k} differs from v3")
    app = v4[mq.AGENT_KEY][28:]
    check(app.tolist() == [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1.0, 1.0, 0, 0.5, 0, 0], f"tick-0 appended {app.tolist()}")
    check(v4[mq.ACTION_CLASS_KEY][st2.CLASS_INDEX["idle_ground"]] == 1.0 and v4[mq.ACTION_CLASS_KEY].sum() == 1.0, "class one-hot")
    # encodings, one reply each (status 209 = AttackAirN for the gating cases)
    cases = [
        ("R fold", input_json(tick=1, hold=0xA010, tap=0xA010, z=0), 10, {"hold_A": 1, "hold_Z": 1, "hold_R": 1, "z_age": 0.0, "z_out": 0}),
        ("A only", input_json(tick=1, hold=0x8000), 10, {"hold_A": 1, "hold_Z": 0, "hold_R": 0}),
        ("C-up", input_json(tick=1, hold=0x0008), 10, {"hold_Cup": 1, "hold_Cleft": 0}),
        ("stick", input_json(tick=1, stick=(-80, 80), taps=(1, 2), holds=(1, 2)), 10, {"stick_x": -1.0, "stick_y": 1.0, "tap_x": 1.0, "tap_y": 0.75}),
        ("tap3/stale", input_json(tick=1, stick=(80, 80), taps=(3, 9), holds=(3, 9)), 10, {"tap_x": 0.5, "tap_y": 0.25}),
        ("tap forced", input_json(tick=1, stick=(80, 80), taps=(254, 253), holds=(5, 5)), 10, {"tap_x": 0.0, "tap_y": 0.25}),
        ("z 10", input_json(tick=1, z=10), 10, {"z_age": 1.0, "z_out": 0}),
        ("z 11", input_json(tick=1, z=11), 10, {"z_age": 1.0, "z_out": 1}),
        ("z 4", input_json(tick=1, z=4), 10, {"z_age": 0.4, "z_out": 0}),
        ("anim", input_json(tick=1, anim_frame=30.0, anim_speed=0.5), 10, {"anim_frame": 0.5, "anim_speed": 0.25}),
        ("anim clip", input_json(tick=1, anim_frame=-3.0, anim_speed=3.0), 10, {"anim_frame": 0.0, "anim_speed": 1.0}),
        ("armed aerial", input_json(tick=1, flag1=50), 209, {"aerial_lag_armed": 1}),
        ("flag1 elsewhere", input_json(tick=1, flag1=1), 14, {"aerial_lag_armed": 0}),
        ("unarmed aerial", input_json(tick=1, flag1=0), 211, {"aerial_lag_armed": 0}),
    ]
    idx = {f: i for i, f in enumerate(mq.AGENT_FIELDS)}
    for name, inp_obj, status, want in cases:
        b4.reset_episode()
        o = nt.observation(0.0, -2550.0, 1, status=status, ga=1 if status >= 200 else 0)
        v, _ = b4.build(o, gt.synth_snapshot(tick=1), ne.parse_entity(nt.entity_json(tick=1)), mi.parse_input(inp_obj))
        got = {f: float(v[mq.AGENT_KEY][idx[f]]) for f in want}
        check(all(abs(got[f] - float(want[f])) < 1e-6 for f in want), f"{name}: {got} != {want}")
        check(space.contains(v) and all(np.isfinite(v[k]).all() for k in mq.KEY_ORDER), f"{name}: space")
    # contact_edge from the spatial mask
    b4.reset_episode()
    sp = gt.synth_snapshot(tick=1)
    sp_edge = replace(sp, fighter=replace(sp.fighter, mask_curr=sp.fighter.mask_curr | 0x8000))
    v, _ = b4.build(nt.observation(0.0, -2550.0, 1), sp_edge, ne.parse_entity(nt.entity_json(tick=1)), mi.parse_input(input_json(tick=1)))
    check(v[mq.AGENT_KEY][idx["contact_edge"]] == 1.0, "contact_edge")
    # classes for the new states, stale rule, anomaly counting
    b4.reset_episode()
    for status, cls in ((58, "helpless"), (66, "air_lock"), (31, "landing_free"), (219, "landing_lag")):
        v, _ = b4.build(nt.observation(0.0, -2550.0, 1, status=status), gt.synth_snapshot(tick=1),
                        ne.parse_entity(nt.entity_json(tick=1)), mi.parse_input(input_json(tick=1)))
        check(v[mq.ACTION_CLASS_KEY][st2.CLASS_INDEX[cls]] == 1.0, f"class {cls}")
    last = {k: a.copy() for k, a in v.items()}
    v_st, stale = b4.build(nt.observation(0.0, -2550.0, 2, valid=0), gt.synth_snapshot(tick=2, live=0),
                           ne.parse_entity(nt.entity_json(tick=2, live=0, valid=0)), mi.parse_input(input_json(tick=2, live=0, valid=0)))
    check(stale and all(np.array_equal(v_st[k], last[k]) for k in mq.KEY_ORDER), "stale rule")
    b4.reset_episode()
    b4.build(nt.observation(0.0, -2550.0, 1), gt.synth_snapshot(tick=1), ne.parse_entity(nt.entity_json(tick=1)),
             mi.parse_input(input_json(tick=1, stick=(80, 0), taps=(0, 254), holds=(1, 254))))
    check(len(b4.input_anomalies) == 1 and "tap counter 0" in b4.input_anomalies[0], f"anomaly {b4.input_anomalies}")
    check(mq.masked_rows_are_zero(v) == [], "masked rows")
    try:
        b4.build(nt.observation(0.0, -2550.0, 3), gt.synth_snapshot(tick=3), ne.parse_entity(nt.entity_json(tick=3)),
                 mi.parse_input(input_json(tick=4)))
        raise CaseFailure("mismatched input tick accepted")
    except mq.ObservationV4Error:
        pass
    return {"cases": [c[0] for c in cases]}


def _v3_chain(trace: Dict[str, Any]) -> List[str]:
    init = trace["initial"]
    sp0 = ms.spatial_of(init, expect_lines=True)
    b = mn.EntityObservationBuilder(sp0.lines or (), st1.ActionClassifier(st1.load_table(), "mario"))
    out = []
    for i, reply in enumerate([init] + list(trace.get("steps") or [])):
        sp = sp0 if i == 0 else ms.spatial_of(reply, expect_lines=False)
        obs, _ = b.build(reply["observation"], sp, ne.entity_of(reply))
        out.append(obs)
    return out


def _capture_files() -> List[Path]:
    dirs = sorted(p for p in EQUIV.glob("input_all*") if (p / "summary.json").is_file()) if EQUIV.is_dir() else []
    files: List[Path] = []
    for d in dirs:
        files += sorted(d.glob("*.json.gz"))
    check(files, "no M7q capture set with the input object (run m7q_equivalence.py capture --variant input_all)")
    return files


def unit_offline_traces(s: Suite) -> Dict[str, Any]:
    import m7f_trace as mt
    import m7g_equivalence as me

    files = _capture_files()
    t1, t2 = st1.load_table(), st2.load_table()
    aerial = set(st2.aerial_attack_ids(t2))
    space = mq.make_observation_space()
    idx = {f: i for i, f in enumerate(mq.AGENT_FIELDS)}
    chains: Dict[str, Dict[str, str]] = {}
    report: Dict[str, Any] = {}
    landing_checks = {"predicted": 0, "wrong": [], "durations": {}, "stopceil": 0, "boundary_prev_t": [],
                      "landing_tick_z_edges": []}
    tick0: Dict[str, Any] = {}
    for p in files:
        tr = mt.read_trace(p)
        init = tr["initial"]
        sp0 = ms.spatial_of(init, expect_lines=True)
        b = mq.InputObservationBuilder(sp0.lines or (), st1.ActionClassifier(t1, "mario"), st2.ActionClassifier(t2, "mario"), aerial)
        v3_obs = _v3_chain(tr)
        static = {i: sp0.target_positions[i] for i in range(10) if i != 2 and sp0.target_live_mask & (1 << i)}
        prev_sp = prev_en = prev_in = prev_o = None
        problems: List[str] = []
        stale = 0
        maxabs = 0.0
        h = hashlib.sha256()
        prev_obs4: Optional[Dict[str, np.ndarray]] = None
        prev_status: Optional[int] = None
        run_start: Dict[str, Any] = {}
        for i, reply in enumerate([init] + list(tr.get("steps") or [])):
            sp = sp0 if i == 0 else ms.spatial_of(reply, expect_lines=False)
            en = ne.entity_of(reply)
            inp = mi.input_of(reply)
            o = reply["observation"]
            if i == 0:
                tick0[p.name] = {"z": inp.tics_since_last_z, "hold": inp.button_hold, "taps": [inp.tap_stick_x, inp.tap_stick_y],
                                 "anim": [inp.anim_frame, inp.anim_speed], "status": o["fighter_status_id"]}
            problems += [f"{i}: {m}" for m in ms.check_snapshot(sp, o, prev=prev_sp, prev_observation=prev_o, static_targets=static)]
            problems += [f"{i}: {m}" for m in ne.check_snapshot(en, o, prev=prev_en, prev_observation=prev_o, jumps_max=2)]
            problems += [f"{i}: {m}" for m in mi.check_snapshot(inp, o, prev=prev_in, prev_observation=prev_o)]
            obs, stl = b.build(o, sp, en, inp)
            stale += stl
            if not space.contains(obs) or not all(np.isfinite(obs[k]).all() for k in mq.KEY_ORDER):
                problems.append(f"{i}: not contained / finite")
            problems += [f"{i}: {m}" for m in mq.masked_rows_are_zero(obs)]
            if not np.array_equal(obs[mq.AGENT_KEY][:28], v3_obs[i][mn.AGENT_KEY]) or any(
                    not np.array_equal(obs[k], v3_obs[i][k]) for k in (mq.PROJECTILES_KEY, mq.SEGMENT_GEOMETRY_KEY, mq.SEGMENT_KIND_KEY, mq.TARGETS_KEY)):
                problems.append(f"{i}: v3 slice differs from the v3 builder")
            maxabs = max(maxabs, max(float(np.abs(obs[k]).max()) for k in mq.KEY_ORDER))
            h.update(mq.observation_digest(obs).encode("ascii"))
            # landing classification (V6): at an aerial -> landing transition, the previous tick's bits predict the class
            status = int(o["fighter_status_id"])
            if not stl and prev_obs4 is not None and prev_in is not None and prev_status in aerial and status not in aerial \
                    and int(o.get("fighter_valid", 0)):
                armed = prev_obs4[mq.AGENT_KEY][idx["aerial_lag_armed"]] == 1.0   # flag1 of the last airborne tick
                t_land = int(inp.tics_since_last_z)   # the counter after the landing tick's input block = the value the check read
                cls = st2.CLASSES[int(np.argmax(obs[mq.ACTION_CLASS_KEY]))]
                if cls in ("landing_lag", "landing_free", "idle_ground"):
                    landing_checks["predicted"] += 1
                    z_edge = bool(inp.button_tap & mi.BUTTON_Z)
                    prev_t = int(prev_in.tics_since_last_z)
                    if prev_t in (9, 10):
                        landing_checks["boundary_prev_t"].append((p.name, i, prev_t, armed, z_edge, cls))
                    if z_edge:
                        landing_checks["landing_tick_z_edges"].append((p.name, i, prev_t, armed, cls))
                    expect = "landing_lag" if (armed and t_land > mi.Z_CANCEL_WINDOW) else ("landing_free", "idle_ground")
                    if (cls != expect) if isinstance(expect, str) else (cls not in expect):
                        landing_checks["wrong"].append(f"{p.name}@{i}: armed={armed} t_land={t_land} -> {cls}")
            if status == 66 and not stl:
                landing_checks["stopceil"] += 1
                if obs[mq.ACTION_CLASS_KEY][st2.CLASS_INDEX["air_lock"]] != 1.0:
                    problems.append(f"{i}: StopCeil not air_lock")
            # landing_lag run durations
            if status != prev_status:
                if prev_status in LANDING_LAG_TICKS and run_start:
                    n = i - run_start["i"]
                    key = str(prev_status) + (f"@{run_start['speed']:g}" if prev_status == 219 else "")
                    landing_checks["durations"].setdefault(key, []).append(n)
                run_start = {"i": i, "speed": float(inp.anim_speed)}
            prev_sp, prev_en, prev_in, prev_o, prev_obs4, prev_status = sp, en, inp, o, obs, status
        group = me.trace_group(p.name)
        chains.setdefault(group, {})[str(p.relative_to(REPO_ROOT))] = h.hexdigest()
        report[str(p.relative_to(REPO_ROOT))] = {"problems": problems[:5], "problem_count": len(problems), "stale": stale,
                                                 "max_abs": round(maxabs, 3), "unmapped": dict(b.classifier2.unmapped_seen),
                                                 "overflow": b.projectile_overflow, "anomalies": b.input_anomalies[:3],
                                                 "replies": i + 1}
    bad = {k: v for k, v in report.items() if v["problem_count"] or v["unmapped"] or v["overflow"] or v["anomalies"]}
    check(not bad, f"offline problems: {json.dumps(bad)[:900]}")
    det = {g: len(set(c.values())) == 1 for g, c in chains.items()}
    check(all(det.values()), f"v4 not deterministic across modes / repeats: {det}")
    check(all(v["stale"] <= 1 for v in report.values()), "stale steps")
    check(not landing_checks["wrong"], f"landing classification not predicted: {landing_checks['wrong'][:5]}")
    for key, ticks in landing_checks["durations"].items():
        sid = int(key.split("@")[0])
        want = LANDING_LAG_TICKS[sid]
        if "@" in key:   # LandingAirNull: 7 frames at the move's flag1 speed (nair 0.5 -> 14, dair 0.2 -> 35)
            want = round(7.0 / float(key.split("@")[1]))
        check(all(t == want or t == 1 for t in ticks), f"status {key} durations {ticks} != {want}")
    armed_boundary = [b for b in landing_checks["boundary_prev_t"] if b[3] and not b[4]]
    decisive_z = [b for b in landing_checks["landing_tick_z_edges"] if b[3] and b[2] >= mi.Z_CANCEL_WINDOW]
    return {"traces": len(report), "determinism_groups": {g: len(c) for g, c in chains.items()},
            "landing_transitions_predicted": landing_checks["predicted"], "landing_lag_durations": landing_checks["durations"],
            "stopceil_ticks": landing_checks["stopceil"], "tick0": tick0, "max_abs": max(v["max_abs"] for v in report.values()),
            "coverage": {"boundary_prev_t_9_or_10": landing_checks["boundary_prev_t"],
                         "armed_boundary_without_z": armed_boundary, "landing_tick_z_edges": landing_checks["landing_tick_z_edges"],
                         "decisive_landing_tick_z": decisive_z,
                         "note": "the Z boundary (previous counter 9 / 10 while armed, or a Z edge on the landing tick while "
                                 "armed with the counter already outside the window) is NOT exercised by the records when "
                                 "these lists are empty; unit_landing_boundary covers it synthetically"}}


def unit_oracle(s: Suite) -> Dict[str, Any]:
    dirs = sorted(p for p in EQUIV.glob("input_all*") if (p / "summary.json").is_file()) if EQUIV.is_dir() else []
    check(dirs, "no input_all capture set")
    r = mqe.validate(dirs)
    (s.dir("unit_oracle") / "validate.json").write_text(json.dumps(r, indent=1, default=str), encoding="utf-8")
    bad = {f"{Path(d).name}/{n}": v["problems"][:3] for d, sets in r["sets"].items() for n, v in sets.items()
           if v["problem_count"] or not v["oracle"]}
    check(not bad, f"oracle problems: {json.dumps(bad)[:900]}")
    counts = {k: sum(v["counts"][k] for sets in r["sets"].values() for v in sets.values())
              for k in ("oracle_ticks", "hitlag_ticks", "forced_tap_y", "forced_tap_x", "aerial_entries", "z_taps", "r_presses",
                        "anim_freeze_checks")}
    check(counts["oracle_ticks"] > 20000 and counts["forced_tap_y"] > 0 and counts["aerial_entries"] > 0
          and counts["z_taps"] > 0 and counts["hitlag_ticks"] > 0, f"oracle coverage {counts}")
    speeds = sorted({x for sets in r["sets"].values() for v in sets.values() for x in v["counts"]["speeds"]})
    return {"counts": counts, "speeds_seen": speeds, "sets": [Path(d).name for d in r["sets"]]}


def landing_lag_next_tick(prev_t: int, z_edge_on_landing_tick: bool, armed: bool) -> bool:
    """The source rule (ftmain.c:1510-1517 then ftcommonattackair.c:63) evaluated for a landing on the tick AFTER an
    observation whose Z counter is prev_t: the landing tick first advances the counter (0 on a Z / R edge, else +1,
    capped at 65536), then the landing check lags iff the aerial's flag1 is still set and the counter exceeds 10."""
    t = 0 if z_edge_on_landing_tick else min(prev_t + 1, mi.Z_TIMER_MAX)
    return armed and t > mi.Z_CANCEL_WINDOW


def unit_landing_boundary(s: Suite) -> Dict[str, Any]:
    nt = _m7n_tests()
    gt = nt._synth()
    _b3, b4 = builders()
    idx = {f: i for i, f in enumerate(mq.AGENT_FIELDS)}
    table: Dict[str, Any] = {}
    for prev_t in (8, 9, 10, 11, 12, mi.Z_TIMER_MAX):
        b4.reset_episode()
        v, _ = b4.build(nt.observation(0.0, -2550.0, 1, status=209, ga=1), gt.synth_snapshot(tick=1),
                        ne.parse_entity(nt.entity_json(tick=1)), mi.parse_input(input_json(tick=1, z=prev_t, flag1=50)))
        z_age, z_out, armed = (float(v[mq.AGENT_KEY][idx[k]]) for k in ("z_age", "z_out", "aerial_lag_armed"))
        row = {"z_age": z_age, "z_out": z_out, "armed": armed,
               "next_landing_lags_without_z": landing_lag_next_tick(prev_t, False, True),
               "next_landing_lags_with_z": landing_lag_next_tick(prev_t, True, True)}
        table[str(prev_t)] = row
        check(armed == 1.0, f"prev_t {prev_t}: armed")
        check(row["next_landing_lags_with_z"] is False, f"prev_t {prev_t}: a Z edge on the landing tick must cancel")
        # the source rule: the landing tick's counter is prev_t + 1, so prev_t >= 10 already lags without Z
        check(row["next_landing_lags_without_z"] == (prev_t >= mi.Z_CANCEL_WINDOW), f"prev_t {prev_t}: source rule")
        # what the previous tick's encodings say: z_age < 1.0 <=> prev_t <= 9 <=> the next landing is free even without Z;
        # z_age == 1.0 (prev_t >= 10) <=> the next landing lags unless Z / R is pressed on it; z_out only separates 10 from 11+
        check((z_age < 1.0) == (not row["next_landing_lags_without_z"]), f"prev_t {prev_t}: z_age boundary")
        check(z_out == (1.0 if prev_t > mi.Z_CANCEL_WINDOW else 0.0), f"prev_t {prev_t}: z_out")
    # unarmed: never lags, whatever the counter
    check(not landing_lag_next_tick(20, False, False) and not landing_lag_next_tick(11, False, False), "unarmed")
    return {"prev_t_table": table,
            "reading": "for a landing on the NEXT tick, z_age == 1.0 (previous counter >= 10) means it lags unless Z / R "
                       "is pressed on that tick; z_out (previous counter >= 11) is not the decision boundary"}


class _DictEnv(gym.Env):
    def __init__(self) -> None:
        self.observation_space = mq.make_observation_space()
        self.action_space = spaces.MultiDiscrete([9, 8])
        self._n = 0

    def _obs(self) -> Dict[str, np.ndarray]:
        rng = np.random.default_rng(self._n)
        o = {k: (rng.random(v.shape) * 0.5).astype(np.float32) for k, v in self.observation_space.spaces.items()}
        o[mq.ACTION_CLASS_KEY] = np.zeros(mq.SHAPES[mq.ACTION_CLASS_KEY], np.float32)
        o[mq.ACTION_CLASS_KEY][self._n % 23] = 1.0
        return o

    def reset(self, *, seed=None, options=None):
        self._n = 0
        return self._obs(), {}

    def step(self, a):
        self._n += 1
        return self._obs(), 0.0, False, self._n >= 50, {}


def unit_sb3_dummy(s: Suite) -> Dict[str, Any]:
    import torch
    from stable_baselines3.common.vec_env import DummyVecEnv

    torch.set_num_threads(1)
    d = s.dir("unit_sb3_dummy")
    venv = mqp.make_vecnormalize(DummyVecEnv([_DictEnv]))
    model = mqp.make_model(venv, seed=0, n_steps=64, batch_size=32)
    n_params = sum(p.numel() for p in model.policy.parameters())
    check(n_params == V4_PARAMETERS, f"parameters {n_params}")
    check(type(model.policy).__name__ == "MultiInputActorCriticPolicy", "policy class")
    obs = venv.reset()
    check(obs[mq.AGENT_KEY].shape == (1, 45) and obs[mq.ACTION_CLASS_KEY].shape == (1, 23), "vec obs shapes")
    raw = venv.venv.reset()
    check(all(np.array_equal(obs[k], np.asarray(raw[k])) for k in mq.KEY_ORDER), "VecNormalize(norm_obs=False) changed the observation")
    a1, _ = model.predict(obs, deterministic=True)
    model.save(str(d / "model.zip"))
    from stable_baselines3 import PPO

    m2 = PPO.load(str(d / "model.zip"), device="cpu")
    a2, _ = m2.predict(obs, deterministic=True)
    check(np.array_equal(a1, a2), "reload prediction differs")
    mqp.assert_v4_checkpoint(d / "model.zip")
    # a v3 model is refused
    import m7n_policy as mnp
    import m7n_tests as nt

    v3env = mnp.make_vecnormalize(DummyVecEnv([nt._DictEnv]))
    m3 = mnp.make_model(v3env, seed=0, n_steps=64, batch_size=32)
    m3.save(str(d / "v3_model.zip"))
    try:
        mqp.assert_v4_checkpoint(d / "v3_model.zip")
        raise CaseFailure("v3 checkpoint accepted as v4")
    except ValueError:
        pass
    desc = mqp.describe(model)
    check(desc["network_id"] == mqp.NETWORK_ID, "network id")
    return {"parameters": n_params, "network": desc.get("network_id")}


def unit_config(s: Suite) -> Dict[str, Any]:
    import experiment_config as ec
    import m7_trainer as tr

    base4 = V4_PROFILE.read_text(encoding="utf-8")
    mutations = {
        "v4_with_normalisation": (base4, "normalize_observations = false", "normalize_observations = true", "normalize_observations"),
        "v4_with_MlpPolicy": (base4, 'policy = "MultiInputPolicy"', 'policy = "MlpPolicy"', "ppo.policy"),
        "v4_other_net_arch": (base4, "net_arch = [64, 64]", "net_arch = [128, 128]", "ppo.net_arch"),
        "v4_input_flag_in_toml": (base4, "[environment]", "[environment]\ninput = true", "unknown key"),
        "unknown_observation": (base4, 'observation = "btt_policy_obs_v4_input"', 'observation = "btt_policy_obs_v4"',
                                "contracts.observation"),
    }
    rejected: Dict[str, str] = {}
    for name, (base, old, new, needle) in mutations.items():
        check(base.count("\n" + old) == 1, f"{name}: {old!r} is not one TOML line of the profile")
        text = base.replace("\n" + old, "\n" + new, 1)
        try:
            ec.parse_toml_text(text, source_path=f"<{name}>")
            raise CaseFailure(f"{name}: accepted")
        except ec.ConfigError as exc:
            check(needle in str(exc), f"{name}: message lacks {needle!r}: {exc}")
            rejected[name] = str(exc).splitlines()[1].strip()[:160] if len(str(exc).splitlines()) > 1 else str(exc)[:160]
    e4 = ec.load_experiment(V4_PROFILE)
    c4 = tr.config_from_experiment(e4)
    check(c4.observation_v4 and not c4.observation_v3 and not c4.norm_obs and c4.policy == "MultiInputPolicy"
          and dict(c4.extra_env) == V4_FLAGS, f"v4 trainer config {c4.extra_env}")
    bad = {"v4_norm_obs": replace(c4, norm_obs=True, experiment=None),
           "v4_without_input_flag": replace(c4, extra_env=tuple({**FLAGS, **dict(mn.ENTITY_EXTRA_ENV)}.items()), experiment=None),
           "v4_MlpPolicy": replace(c4, policy="MlpPolicy", experiment=None),
           "v4_net_arch_128": replace(c4, net_arch=(128, 128), experiment=None)}
    for name, cfg in bad.items():
        try:
            cfg.validate()
            raise CaseFailure(f"M7Config {name}: accepted")
        except ValueError as exc:
            rejected[f"M7Config.{name}"] = str(exc)[:160]
    ident = e4.policy_observation()
    check(ident["contract"] == mq.OBS_CONTRACT and ident["flat_size"] == 626 and ident["norm_obs_keys"] == []
          and ident["action_class_table_sha256"] == st2.load_table()["sha256"] and ident["network_id"] == mqp.NETWORK_ID
          and ident["input_diagnostic_contract"] == mi.CONTRACT and ident["native_flags"] == dict(mq.ENTITY_EXTRA_ENV), f"v4 identity {ident}")
    contracts = tr.run_contracts(c4)
    check(contracts["policy_observation_contract"] == mq.OBS_CONTRACT and contracts["action_class_table"] == st2.TABLE_ID
          and contracts["input_diagnostic_contract"] == mi.CONTRACT and contracts["entity_diagnostic_contract"] == ne.CONTRACT
          and contracts["reward_contract"] == "btt_reward_v2" if "reward_contract" in contracts else True, f"run contracts {contracts}")
    # v1 / v2 / v3 unchanged
    e1, e2, e3 = ec.load_experiment(V1_PROFILE), ec.load_experiment(V2_PROFILE), ec.load_experiment(V3_PROFILE)
    check(dict(e1.extra_env) == FLAGS and dict(e2.extra_env) == {**FLAGS, ms.SPATIAL_ENV: "1"}
          and dict(e3.extra_env) == {**FLAGS, **dict(mn.ENTITY_EXTRA_ENV)}, "v1 / v2 / v3 flags changed")
    check(e1.policy_observation() is None and e2.policy_observation()["contract"] == "btt_policy_obs_v2_spatial"
          and e3.policy_observation()["contract"] == mn.OBS_CONTRACT and e3.policy_observation()["contract_sha256"] == V3_DIGEST
          and e3.policy_observation()["flat_size"] == 606, "v1 / v2 / v3 identity blocks changed")
    c3 = tr.config_from_experiment(e3)
    check(c3.observation_v3 and not c3.observation_v4 and tr.run_contracts(c3)["policy_observation_contract"] == mn.OBS_CONTRACT,
          "v3 trainer config changed")
    return {"rejected": rejected, "v4_flags": dict(c4.extra_env)}


def unit_isolation(s: Suite) -> Dict[str, Any]:
    files = ["m7q_obs.py", "m7q_input.py", "m7q_policy.py", "m7q_status_table.py", "m7q_equivalence.py"]
    fixture_ref = re.compile(r"m7g_(fixture|capture|crossing)|fixtures['\"\s,/\\()]*m7g|lower_precision|"
                             r"upper_moving_platform|\.learn\(|tas_input|optimal[_ ]path|preferred[_ ]crossing|"
                             r"go[_ ]left|target[_ ]order|action_mask|valid_actions|invalid_action", re.I)
    hits = {}
    for f in files:
        text = (RL_DIR / f).read_text(encoding="utf-8")
        found = sorted({m.group(0) for m in fixture_ref.finditer(text)})
        found = [x for x in found if x.lower() not in ("optimal path", "preferred crossing", "target order", "go left", "action mask")]
        if found:
            hits[f] = found
    check(not hits, f"forbidden references {hits}")
    # the native fill reads no RNG state
    fill = (REPO_ROOT / "decomp" / "src" / "sc" / "sc1pmode" / "sc1pbonusstage.c").read_text(encoding="utf-8", errors="replace")
    body = fill[fill.index("void rlGameFillInput"):fill.index("#endif", fill.index("void rlGameFillInput"))]
    check(not re.search(r"syUtilsRand|gSYRandom|Random|seed", body), "the input fill mentions RNG")
    return {"files": files}


# -- game -----------------------------------------------------------------------------------------------------------

def _artifact_track1(name: str) -> Tuple[List[Tuple[int, int, int, Optional[int]]], List[np.ndarray]]:
    return _m7n_tests()._artifact_track1(name)


def _m5_v4_env(root: Path, *, check_invariants: bool = True) -> Tuple[Any, Any]:
    import btt_learning as bl

    cfg = bl.LearningEnvConfig(executable=str(EXECUTABLE), artifact_root=root / "artifacts",
                               episodes_root=root / "episodes", max_episode_steps=3600, extra_env=dict(V4_FLAGS))
    env = bl.make_learning_env(cfg)
    return env, mq.EntityObsV4Wrapper(env, base=env.base_env, check_invariants=check_invariants)


def _offline_v4(trace: Dict[str, Any]) -> List[str]:
    init = trace["initial"]
    sp0 = ms.spatial_of(init, expect_lines=True)
    t2 = st2.load_table()
    b = mq.InputObservationBuilder(sp0.lines or (), st1.ActionClassifier(st1.load_table(), "mario"),
                                   st2.ActionClassifier(t2, "mario"), st2.aerial_attack_ids(t2))
    out = []
    for i, reply in enumerate([init] + list(trace.get("steps") or [])):
        sp = sp0 if i == 0 else ms.spatial_of(reply, expect_lines=False)
        obs, _ = b.build(reply["observation"], sp, ne.entity_of(reply), mi.input_of(reply))
        out.append(mq.observation_digest(obs))
    return out


def game_wrapper_vs_raw(s: Suite) -> Dict[str, Any]:
    import m7f_trace as mt
    from m7_runtime import list_processes_named

    d = s.dir("game_wrapper_vs_raw")
    out: Dict[str, Any] = {}
    for name in (ARTIFACT_HORIZON, ARTIFACT_FALL):
        acts, t1 = _artifact_track1(name)
        env, v4 = _m5_v4_env(d / f"wrapper_{name}")
        digests: List[str] = []
        stale_at: List[int] = []
        try:
            o, info = v4.reset()
            check(info["policy_observation_contract"] == mq.OBS_CONTRACT and v4.base.last_observe.step_count == 0
                  and info["v4_stale"] is False and o[mq.AGENT_KEY].shape == (45,), "reset contract / step count")
            check(v4.base.last_observe.observation.input_tick == 0, "reset observe tick")
            digests.append(mq.observation_digest(o))
            steps = 0
            first_consumed = None
            end = None
            first_hold = None
            for a in t1:
                o, _r, term, trunc, info = v4.step(a)
                steps += 1
                if first_consumed is None:
                    first_consumed = v4.base.last_step_result.consumed_tick
                    first_hold = o[mq.AGENT_KEY][30:37].tolist()
                if info.get("v4_stale"):
                    stale_at.append(steps)
                digests.append(mq.observation_digest(o))
                if term or trunc:
                    end = info.get("termination_reason") or info.get("truncation_reason")
                    break
            problems = list(v4.invariant_problems)
            unmapped = info.get("v4_unmapped_status_ids")
            anomalies = info.get("v4_input_anomalies")
        finally:
            env.close()
        check(not problems, f"{name}: invariant problems {problems[:3]}")
        check(first_consumed == 0, f"{name}: first consumed tick {first_consumed}")
        check(not unmapped and not anomalies, f"{name}: unmapped ids {unmapped} / anomalies {anomalies}")
        check(all(x == steps for x in stale_at), f"{name}: stale steps {stale_at} (only a terminal reply may be stale)")
        raw = mt.run_stepping_trace("raw", EXECUTABLE, acts, d / f"raw_{name}", extra_env=dict(V4_FLAGS))
        offline = _offline_v4(raw)
        check(len(offline) == len(digests) and offline == digests,
              f"{name}: wrapper vs offline v4 differ (first at "
              f"{next((i for i, (x, y) in enumerate(zip(offline, digests)) if x != y), None)}; {len(offline)} vs {len(digests)})")
        out[name] = {"steps": steps, "end": end, "stale_steps": stale_at, "first_hold_bits": first_hold,
                     "chain": hashlib.sha256("".join(digests).encode("ascii")).hexdigest()}
    check(not list_processes_named(), "leftover BattleShip")
    return out


def game_standby_v4(s: Suite) -> Dict[str, Any]:
    from btt_parallel import RunCoordinator, WorkerSpec, initial_coordination_state
    from m7_runtime import list_processes_named, prepare_worker_runtime
    from run_artifacts import read_artifact

    d = s.dir("game_standby_v4")
    _acts, t1 = _artifact_track1(ARTIFACT_HORIZON)
    coord = d / "coordination"
    RunCoordinator.create(coord, initial_coordination_state("m7q_standby_v4", "test", None))
    wd = d / "workers" / "w00"
    prepare_worker_runtime(wd / "runtime", EXECUTABLE)
    spec = WorkerSpec(rank=0, run_id="m7q_standby_v4", role="test", worker_dir=str(wd.resolve()),
                      coordination_dir=str(coord.resolve()), executable=str(EXECUTABLE), horizon=3600,
                      extra_env=tuple(V4_FLAGS.items()), standby_preboot=True, standby_count=1, preserve_all=True)
    env = mq.M7qWorkerFactory(spec)()
    episodes = []
    try:
        for _ep in range(2):
            o, info = env.reset()
            chain = hashlib.sha256()
            chain.update(mq.observation_digest(o).encode())
            first_consumed = None
            n = 0
            for a in t1:
                o, _r, term, trunc, info = env.step(a)
                if first_consumed is None:
                    first_consumed = env.base.last_step_result.consumed_tick
                chain.update(mq.observation_digest(o).encode())
                n += 1
                if term or trunc:
                    break
            episodes.append({"mode": info.get("m7_episode", {}).get("startup_mode") or
                             (env.base.current_startup or {}).get("mode"), "steps": n, "chain": chain.hexdigest(),
                             "first_consumed_tick": first_consumed})
    finally:
        env.close()
    modes = [e["mode"] for e in episodes]
    check(modes == ["cold_start", "standby_promoted"], f"modes {modes}")
    check(episodes[0]["chain"] == episodes[1]["chain"], "cold vs promoted v4 observations differ")
    check(all(e["first_consumed_tick"] == 0 for e in episodes), f"first consumed ticks {episodes}")
    arts = sorted((wd / "artifacts").iterdir())
    labels = [read_artifact(a).metadata["labels"]["contracts"] for a in arts]
    check(len(arts) == 2 and all(lb["policy_observation_contract"] == mq.OBS_CONTRACT
                                 and lb["action_class_table_sha256"] == st2.load_table()["sha256"]
                                 and lb["input_diagnostic_contract"] == mi.CONTRACT for lb in labels),
          f"artifact labels {labels}")
    check(not list_processes_named(), "leftover BattleShip")
    return {"episodes": episodes}


UNIT_CASES = {"unit_contract": unit_contract, "unit_input_parser": unit_input_parser, "unit_builder": unit_builder,
              "unit_offline_traces": unit_offline_traces, "unit_landing_boundary": unit_landing_boundary,
              "unit_oracle": unit_oracle, "unit_sb3_dummy": unit_sb3_dummy,
              "unit_config": unit_config, "unit_isolation": unit_isolation}
GAME_CASES = {"game_wrapper_vs_raw": game_wrapper_vs_raw, "game_standby_v4": game_standby_v4}
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
    root = (Path(args.root) if args.root else REPO_ROOT / "runs" / "m7q" / "_tests" / f"m7q_{stamp}").resolve()
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
    (root / "m7q_tests_results.json").write_text(json.dumps({"schema": "battleship_m7q_tests_v1", "utc": stamp,
                                                             "results": results, "ok": ok}, indent=1, default=str)
                                                 + "\n", encoding="utf-8", newline="\n")
    print(f"m7q_tests: {sum(r['status'] == 'PASS' for r in results.values())}/{len(results)} PASS -> {root}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
