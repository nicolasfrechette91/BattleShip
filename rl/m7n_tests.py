"""M7n permanent tests: btt_entity_v1 reader, the action-class table and btt_policy_obs_v3_entities.

Unit cases (no game):
    unit_contract            v3 space: keys, sorted order, shapes, dtypes, bounds, 638 flat values, mask columns, digest ==
                             docs/rl_observation_v3_m7n.schema.json; v1 / v2 constants and digests unchanged; the
                             action-class table equals a fresh derivation and maps Mario's ids as registered; the
                             unmapped fallback and per-character lookup
    unit_entity_parser       strict btt_entity_v1 parsing (the probe / capture objects parse; missing / extra keys, booleans
                             as integers, wrong contract, too many weapons refused); check_snapshot flags corrupted streams
    unit_builder             synthetic replies: masks (broken target, empty slot, padding) exactly zero; displacement and
                             target velocity from consecutive replies; sticky projectile slots, ownership filter, overflow
                             count; stale (teardown) replies repeat the last observation; action classes and the unmapped
                             counter; the ledge column; finite and contained
    unit_offline_traces      every M7n capture set (runs/m7n/_equiv/entity_all*) and the probe trace: every reply parses,
                             spatial + entity invariants hold, v3 builds, masked rows zero, finite, deterministic across
                             host modes and repeats, no unmapped id
    unit_sb3_dummy           synthetic Dict env: MultiInputPolicy init (parameter count), forward, save / reload identical
                             predictions, VecNormalize(norm_obs=False) is the identity, v1 / v2 checkpoints refused
    unit_config              strict TOML / M7Config rejection of inconsistent v3 choices; v1 / v2 profiles' flags unchanged;
                             the four M7n profiles resolve (pilot cap 40,960; campaign 3,072,000)
    unit_inference_timing    forward-pass timing (batch 5 and 512) of fresh v1 and v3 models, torch_threads = 1
    unit_isolation           M7n modules never reference the crossing fixtures, route vocabulary or learn()
    unit_rule                the registered decision rule's synthetic self-test (gates, boundaries, ties, integrity, incomplete,
                             undefined T, crossings); the superseded v1 rule byte-preserved
    unit_crossing            the gate-2 crossing criterion on synthetic traces (off-stage fall, qualified landing, ...)
    unit_matrix              the campaign matrix: registered values, Phase K proof, evaluation plan and census, directories
Game cases (fresh BattleShip processes, one case at a time):
    game_wrapper_vs_raw      M5 stack + v3 wrapper (invariants on) on a historical horizon artifact and on a fall artifact:
                             0 invariant problems, stale only on a fall's terminal reply, every wrapper observation equals
                             the offline rebuild from a separate raw trace of the same actions (a second process)
    game_standby_v3          worker stack v3 with one standby: cold_start then standby_promoted episodes give identical v3
                             observations; first step consumes tick 0; artifact labels record the v3 contract
    game_sb3_real            the real game through DummyVecEnv + VecNormalize(norm_obs=False): PPO init, 200 forward
                             passes, observations pass through unchanged, save / reload, frozen evaluation
    game_n5_standby_bench    N=5 workers with standby (<= 10 processes): v1 vs v3 random Track 1 actions, transitions/s

Usage: python rl/m7n_tests.py [unit|game|<case> ...] [--root runs/m7n/_tests/m7n_<utc>]
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
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))

import gymnasium as gym  # noqa: E402
import numpy as np  # noqa: E402
from gymnasium import spaces  # noqa: E402

import m7g_spatial as ms  # noqa: E402
import m7n_entity as ne  # noqa: E402
import m7n_obs as mn  # noqa: E402
import m7n_policy as mnp  # noqa: E402
import m7n_status_table as st  # noqa: E402

REPO_ROOT = RL_DIR.parent
EXECUTABLE = REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"
EQUIV = REPO_ROOT / "runs" / "m7n" / "_equiv"
PROBE = REPO_ROOT / "runs" / "m7n" / "_probe" / "tas_entity.json.gz"
SCHEMA_DOC = REPO_ROOT / "docs" / "rl_observation_v3_m7n.schema.json"
FLAGS = {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1"}
V3_FLAGS = {**FLAGS, **dict(mn.ENTITY_EXTRA_ENV)}
BENCH_VEC_STEPS = 8000
ARTIFACT_HORIZON = "m7e_s0_best6"
ARTIFACT_FALL = "m7d_s0v1_det_fall"
V2_DIGEST = "dcfd14b276c3d9f38f180888c132febb67ace39797bdef2aefb185e024c8c0cb"
PROFILES = {"pilot": RL_DIR / "configs" / "m7n" / "pilot" / "m7n_pilot_s0.toml",
            **{f"s{s}": RL_DIR / "configs" / "m7n" / f"m7n_s{s}_v3.toml" for s in (0, 1, 2)}}
V1_PROFILE = RL_DIR / "configs" / "m7g" / "m7g_s0_v1.toml"
V2_PROFILE = RL_DIR / "configs" / "m7g" / "m7g_s0_v2.toml"


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

def _synth():
    import m7g_obs_tests as gt

    return gt


def entity_json(*, tick: int, status_tics: int = 0, weapons: Sequence[Dict[str, Any]] = (), live: int = 1,
                valid: int = 1, jumps_max: int = 2, hitlag: int = 0, flags: Dict[str, int] = {}) -> Dict[str, Any]:
    f = {"valid": valid, "status_total_tics": status_tics, "hitlag_tics": hitlag, "jumps_max": jumps_max,
         "attack_active": 0, "cliff_hold": 0, "shield_active": 0, "fastfall": 0, "hitstun": 0}
    f.update(flags)
    return {"contract": ne.CONTRACT, "entity_schema": 1, "input_tick": tick, "scene_active": 1, "live": live,
            "anomaly_flags": 0, "fighter": f, "weapon_total": len(weapons), "weapons": list(weapons)}


def weapon_json(serial: int, x: float, y: float, *, owned: int = 1, lifetime: int = 139, vx: float = 49.8,
                vy: float = -5.6, attack_state: int = 3, kind: int = 0) -> Dict[str, Any]:
    return {"serial": serial, "kind": kind, "owned": owned, "lr": 1, "ga": 1, "lifetime": lifetime,
            "attack_state": attack_state, "translate": [x, y], "velocity": [vx, vy]}


def observation(x: float, y: float, tick: int = 0, *, targets: int = 10, status: int = 10, ga: int = 0,
                jumps_used: int = 0, valid: int = 1) -> Dict[str, Any]:
    return {"input_tick": tick, "time_passed": tick, "game_status": 1, "btt_active": 1, "targets_remaining": targets,
            "fighter_valid": valid, "position_x": x, "position_y": y, "air_velocity_x": 0.0, "air_velocity_y": 0.0,
            "ground_velocity_x": 0.0, "facing_direction": 1, "ground_air_state": ga, "fighter_status_id": status,
            "jumps_used": jumps_used}


def builder(character: str = "mario") -> mn.EntityObservationBuilder:
    gt = _synth()
    return mn.EntityObservationBuilder(gt.pinned_lines(), st.ActionClassifier(st.load_table(), character))


# -- unit ---------------------------------------------------------------------------------------------------------

def unit_contract(s: Suite) -> Dict[str, Any]:
    import m7g_obs as mo
    from btt_learning import POLICY_OBSERVATION_SIZE, make_policy_observation_space

    space = mn.make_observation_space()
    check(tuple(space.spaces.keys()) == mn.KEY_ORDER == tuple(sorted(mn.KEY_ORDER)), "key order")
    for k, shape in mn.SHAPES.items():
        b = space.spaces[k]
        check(isinstance(b, spaces.Box) and b.shape == shape and b.dtype == np.float32, f"{k} space")
    check(mn.FLAT_SIZE == 606 and sum(int(np.prod(v)) for v in mn.SHAPES.values()) == 606, "flat size")
    check(len(mn.AGENT_FIELDS) == 28 and len(st.CLASSES) == 20 and len(mn.SEGMENT_KIND_FIELDS) == 7, "field counts")
    check(all(mn.MASK_COLUMNS[k] < mn.SHAPES[k][1] for k in mn.MASK_COLUMNS), "mask columns")
    doc = json.loads(SCHEMA_DOC.read_text(encoding="utf-8"))
    check(doc["contract_sha256"] == mn.contract_digest() and doc["contract"] == mn.contract_description(),
          "docs schema differs from the code contract (python rl/m7n_obs.py schema)")
    # v1 / v2 unchanged
    check(POLICY_OBSERVATION_SIZE == 15 and make_policy_observation_space().shape == (15,), "v1 constants")
    check(mo.FLAT_SIZE == 525 and mo.contract_digest() == V2_DIGEST, f"v2 digest {mo.contract_digest()}")
    # the action-class table
    table = st.load_table()
    check(table == st.derive(), "the stored action-class table differs from a fresh derivation")
    clf = st.ActionClassifier(table, "mario")
    want = {10: "idle_ground", 18: "idle_ground", 20: "jump_squat", 28: "crouch_pass", 152: "shield", 157: "roll",
            223: "special_n", 224: "special_n", 225: "special_hi", 226: "special_hi", 227: "special_lw", 4: "dead",
            5: "appear_entry", 220: "attack_ground", 221: "appear_entry"}
    got = {i: clf.name(i) for i in want}
    check(got == want, f"Mario mapping {got}")
    check(table["special_start"] == 220 and clf.name(9999) == st.UNMAPPED and clf.unmapped_seen == {9999: 1},
          "unmapped fallback")
    link = st.ActionClassifier(table, "link")
    check(link.name(225) != "special_hi" or table["characters"]["link"]["names"]["225"].endswith("SpecialHi"),
          "another character's id must be looked up in its own table")
    check(not link.validated and clf.validated, "validation flags")
    try:
        st.ActionClassifier(table, "boss")
        raise CaseFailure("unknown character accepted")
    except ValueError:
        pass
    return {"flat_size": mn.FLAT_SIZE, "digest": mn.contract_digest(), "table_sha256": table["sha256"],
            "link_225": link.name(225), "mario_classes": got}


def unit_entity_parser(s: Suite) -> Dict[str, Any]:
    import m7f_trace as mt

    base = entity_json(tick=5, weapons=[weapon_json(1, 100.0, 200.0)])
    snap = ne.parse_entity(base)
    check(snap.input_tick == 5 and snap.weapons[0].serial == 1 and snap.fighter.jumps_max == 2, "parse")
    parsed_probe = 0
    if PROBE.is_file():
        tr = mt.read_trace(PROBE)
        for reply in [tr["initial"]] + tr["steps"]:
            ne.entity_of(reply)
            parsed_probe += 1
    bad: Dict[str, Any] = {}
    bad["missing_key"] = {k: v for k, v in base.items() if k != "live"}
    bad["extra_key"] = {**base, "extra": 1}
    bad["bool_live"] = {**base, "live": True}
    bad["wrong_contract"] = {**base, "contract": "btt_entity_v0"}
    bad["too_many_weapons"] = {**base, "weapons": [weapon_json(i, 0.0, 0.0) for i in range(9)]}
    bad["weapon_extra_key"] = {**base, "weapons": [{**weapon_json(1, 0.0, 0.0), "z": 0}]}
    bad["fighter_missing"] = {**base, "fighter": {k: v for k, v in base["fighter"].items() if k != "hitstun"}}
    for name, obj in bad.items():
        try:
            ne.parse_entity(obj)
            raise CaseFailure(f"{name}: accepted")
        except ne.EntityError:
            pass
    # invariants
    o0, o1 = observation(0.0, 0.0, 0, status=10), observation(0.0, 0.0, 1, status=10)
    e0 = ne.parse_entity(entity_json(tick=0, status_tics=3, weapons=[weapon_json(1, 0.0, 0.0, lifetime=100)]))
    ok = ne.check_snapshot(ne.parse_entity(entity_json(tick=1, status_tics=4, weapons=[weapon_json(1, 0.0, 0.0, lifetime=99)])),
                           o1, prev=e0, prev_observation=o0, jumps_max=2)
    check(ok == [], f"valid stream flagged {ok}")
    flagged = {
        "tics_jump": ne.check_snapshot(ne.parse_entity(entity_json(tick=1, status_tics=6)), o1, prev=e0, prev_observation=o0),
        "lifetime_rose": ne.check_snapshot(ne.parse_entity(entity_json(tick=1, status_tics=4,
                                                                         weapons=[weapon_json(1, 0.0, 0.0, lifetime=120)])),
                                           o1, prev=e0, prev_observation=o0),
        "dup_serial": ne.check_snapshot(ne.parse_entity(entity_json(tick=1, status_tics=4,
                                                                      weapons=[weapon_json(1, 0.0, 0.0), weapon_json(1, 1.0, 0.0)])),
                                        o1, prev=e0, prev_observation=o0),
        "tick_pair": ne.check_snapshot(ne.parse_entity(entity_json(tick=7)), o1),
        "jumps_max": ne.check_snapshot(ne.parse_entity(entity_json(tick=1, jumps_max=3)), o1, jumps_max=2),
        "status_change_tics": ne.check_snapshot(ne.parse_entity(entity_json(tick=1, status_tics=2)),
                                                observation(0.0, 0.0, 1, status=20), prev=e0, prev_observation=o0),
    }
    check(all(v for v in flagged.values()), f"invariants not flagged: {[k for k, v in flagged.items() if not v]}")
    reentry = ne.check_snapshot(ne.parse_entity(entity_json(tick=1, status_tics=0)), o1, prev=e0, prev_observation=o0)
    check(reentry == [], f"same-status re-entry (tics 0) flagged {reentry}")
    return {"rejected": sorted(bad), "flagged": {k: v[0] for k, v in flagged.items()}, "probe_replies": parsed_probe}


def unit_builder(s: Suite) -> Dict[str, Any]:
    gt = _synth()
    b = builder()
    space = mn.make_observation_space()
    L, V = mn.LENGTH_SCALE, mn.VELOCITY_SCALE
    sp0 = gt.synth_snapshot(tick=0, platform_y=2000.0, speed_y=0.0)
    o0 = observation(0.0, -2550.0, 0)
    obs0, stale0 = b.build(o0, sp0, ne.parse_entity(entity_json(tick=0)))
    check(not stale0 and space.contains(obs0) and mn.masked_rows_are_zero(obs0) == [], "reset observation")
    check(float(obs0["targets"][:, 4].sum()) == 10 and np.all(obs0["targets"][:, 2:4] == 0)
          and np.all(obs0["agent"][2:4] == 0), "reset: all live, no velocity / displacement")
    check(obs0["action_class"][st.CLASS_INDEX["idle_ground"]] == 1 and obs0["action_class"].sum() == 1, "class one-hot")
    check(np.all(obs0["segment_kind"][24:] == 0) and np.all(obs0["segment_geometry"][24:] == 0), "padding")
    check(float(obs0["agent"][16]) == 1.0 and float(obs0["agent"][25]) == 1.0, "jumps_left / targets_left")
    # second reply: Mario moved, platform moved, target 9 broken, a fireball spawned
    sp1 = gt.synth_snapshot(tick=1, platform_y=2017.3, speed_y=17.3, mask=1023 & ~(1 << 9))
    o1 = observation(30.0, -2540.0, 1, targets=9, status=224, ga=1, jumps_used=1)
    e1 = ne.parse_entity(entity_json(tick=1, status_tics=0, weapons=[weapon_json(1, 130.0, -2500.0),
                                                                    weapon_json(2, 0.0, 0.0, owned=0)]))
    obs1, stale1 = b.build(o1, sp1, e1)
    check(not stale1 and space.contains(obs1) and mn.masked_rows_are_zero(obs1) == [], "second observation")
    check(np.allclose(obs1["agent"][2:4], [30.0 / V, 10.0 / V]), f"displacement {obs1['agent'][2:4]}")
    check(np.allclose(obs1["targets"][2, 2:4], [0.0, 17.3 / V], atol=1e-6) and np.all(obs1["targets"][0, 2:4] == 0),
          f"target 2 velocity {obs1['targets'][2]}")
    check(np.all(obs1["targets"][9] == 0) and obs1["targets"][9, 4] == 0, "broken target row not zero")
    check(np.allclose(obs1["segment_geometry"][23, 7], 17.3 / V), "platform row velocity")
    check(obs1["projectiles"][0, 0] == 1 and np.allclose(obs1["projectiles"][0, 1:3], [100.0 / L, 40.0 / L])
          and np.allclose(obs1["projectiles"][0, 3:5], [49.8 / V, -5.6 / V]) and obs1["projectiles"][0, 5] == 1
          and np.isclose(obs1["projectiles"][0, 6], 139 / 140) and np.all(obs1["projectiles"][1:] == 0),
          f"projectile row {obs1['projectiles']}")
    check(obs1["action_class"][st.CLASS_INDEX["special_n"]] == 1 and float(obs1["agent"][16]) == 0.5
          and float(obs1["agent"][10]) == 0.0, "class / jumps / grounded on reply 1")
    # sticky slots: serials 3 and 4 join (slots 1, 2); serial 1 despawns; serial 5 takes slot 0; 6, 7 -> slot 3 + overflow
    e2 = ne.parse_entity(entity_json(tick=2, status_tics=1, weapons=[weapon_json(1, 0.0, 0.0, lifetime=138),
                                                                    weapon_json(3, 0.0, 0.0), weapon_json(4, 0.0, 0.0)]))
    sp2 = gt.synth_snapshot(tick=2, platform_y=2034.6, speed_y=17.3, mask=1023 & ~(1 << 9))
    obs2, _ = b.build(observation(30.0, -2540.0, 2, targets=9, status=224, ga=1), sp2, e2)
    check([int(v) for v in obs2["projectiles"][:, 0]] == [1, 1, 1, 0], f"slots {obs2['projectiles'][:, 0]}")
    e3 = ne.parse_entity(entity_json(tick=3, status_tics=2, weapons=[weapon_json(3, 0.0, 0.0, lifetime=138),
                                                                    weapon_json(4, 0.0, 0.0, lifetime=138),
                                                                    weapon_json(5, 0.0, 0.0), weapon_json(6, 0.0, 0.0),
                                                                    weapon_json(7, 0.0, 0.0)]))
    sp3 = gt.synth_snapshot(tick=3, platform_y=2051.9, speed_y=17.3, mask=1023 & ~(1 << 9))
    obs3, _ = b.build(observation(30.0, -2540.0, 3, targets=9, status=224, ga=1), sp3, e3)
    check([int(v) for v in obs3["projectiles"][:, 0]] == [1, 1, 1, 1] and b.projectile_overflow == 1
          and b._slots == {3: 1, 4: 2, 5: 0, 6: 3}, f"sticky slots {b._slots} overflow {b.projectile_overflow}")
    # stale: teardown reply repeats the last observation
    obs4, stale4 = b.build(observation(0.0, 0.0, 4, valid=0), gt.synth_snapshot(tick=4, live=0),
                           ne.parse_entity(entity_json(tick=4, live=0, valid=0)))
    check(stale4 and all(np.array_equal(obs4[k], obs3[k]) for k in mn.KEY_ORDER), "stale reply")
    # unmapped id counted; tick pairing enforced
    obs5, _ = b.build(observation(30.0, -2540.0, 5, status=9999), gt.synth_snapshot(tick=5), ne.parse_entity(entity_json(tick=5)))
    check(obs5["action_class"][st.CLASS_INDEX[st.UNMAPPED]] == 1 and b.classifier.unmapped_seen == {9999: 1}, "unmapped")
    try:
        b.build(observation(0.0, 0.0, 6), gt.synth_snapshot(tick=5), ne.parse_entity(entity_json(tick=6)))
        raise CaseFailure("tick mismatch accepted")
    except mn.ObservationV3Error:
        pass
    # the digest depends on every key
    d1 = mn.observation_digest(obs1)
    mutated = {k: v.copy() for k, v in obs1.items()}
    mutated["targets"][0, 0] += 1e-3
    check(mn.observation_digest(mutated) != d1 and mn.flatten(obs1).shape == (mn.FLAT_SIZE,), "digest / flatten")
    return {"agent_reply1": np.round(obs1["agent"], 4).tolist(), "slots": dict(b._slots),
            "overflow": b.projectile_overflow, "stale_builds": b.stale_builds}


def unit_offline_traces(s: Suite) -> Dict[str, Any]:
    import m7f_trace as mt
    import m7g_equivalence as me

    dirs = sorted(p for p in EQUIV.glob("entity_all*") if (p / "summary.json").is_file()) if EQUIV.is_dir() else []
    files = [PROBE] if PROBE.is_file() else []
    for d in dirs:
        files += sorted(d.glob("*.json.gz"))
    check(files, "no M7n capture set or probe trace (run m7n_equivalence.py capture --variant entity_all)")
    table = st.load_table()
    space = mn.make_observation_space()
    chains: Dict[str, Dict[str, str]] = {}
    report: Dict[str, Any] = {}
    for p in files:
        tr = mt.read_trace(p)
        clf = st.ActionClassifier(table, "mario")
        init = tr["initial"]
        sp0 = ms.spatial_of(init, expect_lines=True)
        b = mn.EntityObservationBuilder(sp0.lines or (), clf)
        static = {i: sp0.target_positions[i] for i in range(10) if i != 2 and sp0.target_live_mask & (1 << i)}
        prev_sp = prev_en = prev_o = None
        problems: List[str] = []
        stale = 0
        maxabs = 0.0
        h = hashlib.sha256()
        for i, reply in enumerate([init] + list(tr.get("steps") or [])):
            sp = sp0 if i == 0 else ms.spatial_of(reply, expect_lines=False)
            en = ne.entity_of(reply)
            o = reply["observation"]
            problems += [f"{i}: {m}" for m in ms.check_snapshot(sp, o, prev=prev_sp, prev_observation=prev_o, static_targets=static)]
            problems += [f"{i}: {m}" for m in ne.check_snapshot(en, o, prev=prev_en, prev_observation=prev_o, jumps_max=2)]
            obs, stl = b.build(o, sp, en)
            stale += stl
            if not space.contains(obs) or not all(np.isfinite(obs[k]).all() for k in mn.KEY_ORDER):
                problems.append(f"{i}: not contained / finite")
            problems += [f"{i}: {m}" for m in mn.masked_rows_are_zero(obs)]
            maxabs = max(maxabs, max(float(np.abs(obs[k]).max()) for k in mn.KEY_ORDER))
            h.update(mn.observation_digest(obs).encode("ascii"))
            prev_sp, prev_en, prev_o = sp, en, o
        group = me.trace_group(p.name) if p != PROBE else "tas"
        chains.setdefault(group, {})[str(p.relative_to(REPO_ROOT))] = h.hexdigest()
        report[str(p.relative_to(REPO_ROOT))] = {"problems": problems[:5], "problem_count": len(problems), "stale": stale,
                                                 "max_abs": round(maxabs, 3), "unmapped": dict(clf.unmapped_seen),
                                                 "overflow": b.projectile_overflow, "replies": i + 1}
    bad = {k: v for k, v in report.items() if v["problem_count"] or v["unmapped"] or v["overflow"]}
    check(not bad, f"offline problems: {json.dumps(bad)[:800]}")
    det = {g: len(set(c.values())) == 1 for g, c in chains.items()}
    check(all(det.values()), f"v3 not deterministic across modes / repeats: {det}")
    falls = {k: v["stale"] for k, v in report.items() if "fall" in k}
    check(all(v <= 1 for v in report.values() for v in [v["stale"]]), f"stale steps {falls}")
    return {"traces": len(report), "determinism_groups": {g: len(c) for g, c in chains.items()}, "stale_by_trace": falls,
            "max_abs": max(v["max_abs"] for v in report.values())}


def unit_rule(s: Suite) -> Dict[str, Any]:
    """The registered decision rule: schema, digest, every synthetic gate / boundary / tie / integrity / incomplete case."""
    import io
    from contextlib import redirect_stdout

    import m7n_analysis as na

    rule = na.load_rule()
    check(rule["schema"] == "m7n_decision_rule_v2" and len(rule["gates_in_order"]) == 6, "rule document")
    v1_sha = hashlib.sha256(na.RULE_DOC_V1.read_bytes()).hexdigest()
    check(v1_sha == rule["supersedes"]["sha256"] == "9f5c0fd9eeb33e971148e6774e1d12140dc3318141c164a2829631d629001574",
          f"the superseded v1 rule is not byte-preserved: {v1_sha}")
    check(json.loads(na.RULE_DOC_V1.read_text(encoding="utf-8"))["schema"] == "m7n_decision_rule_v1", "v1 schema")
    check(rule["crossing_verification"]["criterion"] == "btt_qualified_crossing_v1" and "undefined_quantities" in rule,
          "corrections present")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = na.self_test()
    lines = buf.getvalue().splitlines()
    check(rc == 0, "rule self-test failed: " + " | ".join(l for l in lines if "FAIL" in l))
    P = na.params(rule)
    check(P["seeds"] == (0, 1, 2) and P["episodes_per_seed"] == 100 and P["left_ids"] == (1, 6, 8)
          and P["targets_diff_min"] == "1/2", f"parameters {P}")
    cases = sum(1 for l in lines if l.startswith("[PASS]"))
    check(cases >= 46, f"only {cases} synthetic cases")
    return {"rule_sha256": rule["_sha256"], "v1_sha256": v1_sha, "cases": cases}


def unit_crossing(s: Suite) -> Dict[str, Any]:
    """btt_qualified_crossing_v1 on synthetic traces: the M7h off-stage fall, a qualified landing, an airborne-only
    crossing, a landing on the failure step, visits, unmatched ground, candidates and document inputs."""
    import io
    from contextlib import redirect_stdout

    import m7n_crossing as xc

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = xc.self_test()
    lines = buf.getvalue().splitlines()
    check(rc == 0, "crossing self-test failed: " + " | ".join(l for l in lines if "FAIL" in l))
    crit = xc.criterion_description()
    check(crit["geometry"]["left_side_floor_lines"] == [3] and crit["geometry"]["left_boundary_x"] == -2100.0
          and crit["geometry"]["wall_top_y"] == 3000.0, f"geometry {crit['geometry']}")
    return {"cases": sum(1 for l in lines if l.startswith("[PASS]")), "criterion": crit["criterion"]}


def unit_matrix(s: Suite) -> Dict[str, Any]:
    """The campaign matrix: three fresh v3 runs, registered values, the Phase K proof, the evaluation plan and census,
    the directory plan; the campaign root never touches the pilot, control or historical trees."""
    import m7n_matrix as nm

    specs = nm.matrix()
    check([x.name for x in specs] == ["m7n_s0_v3", "m7n_s1_v3", "m7n_s2_v3"] and [x.seed for x in specs] == [0, 1, 2], "matrix")
    out: Dict[str, Any] = {}
    for spec in specs:
        exp = nm.load_run(spec)
        checks = nm.arm_checks(spec, exp)
        bad = [k for k, ok in checks.items() if not ok]
        check(not bad, f"{spec.name}: {bad}")
        proof = nm.phase_k_proof(spec, exp)
        check(proof["ok"], f"{spec.name}: Phase K proof {proof}")
        plan = nm.evaluation_plan(spec, exp)
        eps = sum(int(p["deterministic_episodes"]) + int(p["stochastic_episodes"]) for p in plan)
        check(len(plan) == 11 and eps == 985 and plan[0]["label"] == "initial" and plan[-1]["label"] == "final"
              and plan[-1]["num_timesteps"] == 3_072_000 and all(p["starts"] == "tick0_only" for p in plan)
              and all(dict(p["extra_env"]) == dict(nm.V3_FLAGS, **nm.DIAG_FLAG) for p in plan), f"plan {len(plan)} / {eps}")
        out[spec.name] = {"checks": len(checks), "plan_labels": len(plan), "plan_episodes": eps}
    census = nm.census_plan()
    check(census["episodes"] == 2955 and census["per_run"] == 985, f"census {census}")
    dplan = nm.check_directory_plan()
    check(dplan["ok"] and not dplan["existing"], f"directory plan {dplan}")
    fp = nm.code_fingerprint()
    check(any(k.endswith("m7n_analysis.py") for k in fp["per_file"]) and any(k.endswith("decision_rule.json") for k in fp["per_file"])
          and any(k.startswith("rl/data/") for k in fp["per_file"]), "fingerprint file set")
    obs = nm.observation_identity()
    check(obs["contract_sha256"] == mn.contract_digest() and obs["flat_size"] == 606, "observation identity")
    check(any(k.endswith("decision_rule_v2.json") for k in fp["per_file"]), "v2 rule fingerprinted")
    check(nm.approval_status("0" * 64)["approval"].startswith("PENDING"), "an approval for another rule digest is PENDING")
    return dict(out, census=census, fingerprint_files=fp["files"], directory_root=dplan["root"])


class _DictEnv(gym.Env):
    def __init__(self) -> None:
        self.observation_space = mn.make_observation_space()
        self.action_space = spaces.MultiDiscrete([9, 8])
        self._rng = np.random.default_rng(0)

    def _obs(self) -> Dict[str, np.ndarray]:
        return {k: self._rng.standard_normal(s).astype(np.float32) for k, s in mn.SHAPES.items()}

    def reset(self, *, seed=None, options=None):
        return self._obs(), {}

    def step(self, a):
        return self._obs(), 0.0, False, False, {}


def unit_sb3_dummy(s: Suite) -> Dict[str, Any]:
    import torch
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

    import m7g_obs as mo
    from btt_learning import make_policy_observation_space

    torch.set_num_threads(1)
    d = s.dir("unit_sb3_dummy")
    venv = mnp.make_vecnormalize(DummyVecEnv([_DictEnv]))
    model = mnp.make_model(venv, seed=0, n_steps=16, batch_size=16)
    desc = mnp.describe(model)
    expected = 2 * (mn.FLAT_SIZE * 64 + 64 + 64 * 64 + 64) + (64 * 17 + 17) + (64 + 1)
    check(desc["parameters"] == expected and desc["features_dim"] == mn.FLAT_SIZE, f"network {desc}")
    obs = venv.reset()
    raw = venv.get_original_obs()
    check(all(np.array_equal(obs[k], raw[k]) for k in mn.KEY_ORDER), "VecNormalize(norm_obs=False) changed an observation")
    check(vars(venv).get("obs_rms") is None and not venv.norm_obs, "statistics exist")
    for _ in range(20):
        a, _ = model.predict(obs, deterministic=True)
        obs, _r, _d, _i = venv.step(a)
    model.save(d / "model.zip")
    venv.save(str(d / "vecnormalize.pkl"))
    mnp.assert_v3_checkpoint(d / "model.zip")
    frozen = VecNormalize.load(str(d / "vecnormalize.pkl"), venv.venv)
    frozen.training = False
    model2 = PPO.load(d / "model.zip", env=frozen, device="cpu")
    o = frozen.reset()
    same = sum(int(np.array_equal(model.predict(o, deterministic=True)[0], model2.predict(o, deterministic=True)[0]))
               for _ in range(50))
    check(same == 50, f"reloaded model disagrees on {50 - same}/50")
    # v1 and v2 checkpoints refused

    class V1Env(gym.Env):
        observation_space = make_policy_observation_space()
        action_space = spaces.MultiDiscrete([9, 8])

        def reset(self, *, seed=None, options=None):
            return np.zeros(15, np.float32), {}

        def step(self, a):
            return np.zeros(15, np.float32), 0.0, False, True, {}

    class V2Env(gym.Env):
        observation_space = mo.make_observation_space()
        action_space = spaces.MultiDiscrete([9, 8])

        def reset(self, *, seed=None, options=None):
            return {k: np.zeros(v, np.float32) for k, v in mo.SHAPES.items()}, {}

        def step(self, a):
            return {k: np.zeros(v, np.float32) for k, v in mo.SHAPES.items()}, 0.0, False, True, {}

    refused = {}
    for name, env, pol in (("v1", V1Env, "MlpPolicy"), ("v2", V2Env, "MultiInputPolicy")):
        m = PPO(pol, DummyVecEnv([env]), n_steps=16, batch_size=16, device="cpu", seed=0)
        m.save(d / f"{name}_model.zip")
        try:
            mnp.assert_v3_checkpoint(d / f"{name}_model.zip")
            raise CaseFailure(f"a {name} checkpoint passed the v3 check")
        except ValueError:
            refused[name] = True
        try:
            PPO.load(d / f"{name}_model.zip", env=venv, device="cpu")
            raise CaseFailure(f"a {name} checkpoint loaded onto a v3 environment")
        except (ValueError, KeyError, AssertionError):
            pass
    return {"network": desc, "expected_parameters": expected, "refused": refused}


def unit_config(s: Suite) -> Dict[str, Any]:
    import experiment_config as ec
    import m7_trainer as tr

    base3 = PROFILES["s0"].read_text(encoding="utf-8")
    mutations = {
        "v3_with_normalisation": (base3, "normalize_observations = false", "normalize_observations = true", "normalize_observations"),
        "v3_with_MlpPolicy": (base3, 'policy = "MultiInputPolicy"', 'policy = "MlpPolicy"', "ppo.policy"),
        "v3_other_net_arch": (base3, "net_arch = [64, 64]", "net_arch = [128, 128]", "ppo.net_arch"),
        "v3_relu": (base3, 'activation = "tanh"', 'activation = "relu"', "ppo.activation"),
        "v3_entity_flag_in_toml": (base3, "[environment]", "[environment]\nentity = true", "unknown key"),
        "v3_reward_normalisation": (base3, "normalize_rewards = false", "normalize_rewards = true", "normalize_rewards"),
        "unknown_observation": (base3, 'observation = "btt_policy_obs_v3_entities"', 'observation = "btt_policy_obs_v3"',
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
            rejected[name] = str(exc).splitlines()[1].strip()[:160]
    e3 = ec.load_experiment(PROFILES["s0"])
    c3 = tr.config_from_experiment(e3)
    check(c3.observation_v3 and not c3.norm_obs and c3.policy == "MultiInputPolicy"
          and dict(c3.extra_env) == {**FLAGS, **dict(mn.ENTITY_EXTRA_ENV)}, f"v3 trainer config {c3.extra_env}")
    bad = {"v3_norm_obs": replace(c3, norm_obs=True, experiment=None),
           "v3_without_flags": replace(c3, extra_env=tuple(FLAGS.items()), experiment=None),
           "v3_MlpPolicy": replace(c3, policy="MlpPolicy", experiment=None),
           "v3_net_arch_128": replace(c3, net_arch=(128, 128), experiment=None)}
    for name, cfg in bad.items():
        try:
            cfg.validate()
            raise CaseFailure(f"M7Config {name}: accepted")
        except ValueError as exc:
            rejected[f"M7Config.{name}"] = str(exc)[:160]
    # v1 / v2 unchanged: flags and identity blocks
    e1, e2 = ec.load_experiment(V1_PROFILE), ec.load_experiment(V2_PROFILE)
    check(dict(e1.extra_env) == FLAGS and dict(e2.extra_env) == {**FLAGS, ms.SPATIAL_ENV: "1"}, "v1 / v2 flags changed")
    check(e1.policy_observation() is None and e2.policy_observation()["contract"] == "btt_policy_obs_v2_spatial",
          "v1 / v2 identity blocks changed")
    ident = e3.policy_observation()
    check(ident["contract"] == mn.OBS_CONTRACT and ident["norm_obs_keys"] == [] and ident["flat_size"] == 606
          and ident["action_class_table_sha256"] == st.load_table()["sha256"], f"v3 identity {ident}")
    totals = {k: int(ec.load_experiment(p).values["run.total_transitions"]) for k, p in PROFILES.items()}
    check(totals == {"pilot": 40960, "s0": 3072000, "s1": 3072000, "s2": 3072000}, f"totals {totals}")
    seeds = {k: int(ec.load_experiment(p).values["run.base_seed"]) for k, p in PROFILES.items()}
    check(seeds == {"pilot": 0, "s0": 0, "s1": 1, "s2": 2}, f"seeds {seeds}")
    contracts = tr.run_contracts(c3)
    check(contracts["policy_observation_contract"] == mn.OBS_CONTRACT and contracts["action_class_character"] == "mario"
          and contracts["entity_diagnostic_contract"] == ne.CONTRACT, "run contracts")
    return {"rejected": rejected, "totals": totals, "v3_flags": dict(c3.extra_env)}


def unit_inference_timing(s: Suite) -> Dict[str, Any]:
    import torch
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv

    from btt_learning import make_policy_observation_space

    torch.set_num_threads(1)

    class V1Env(gym.Env):
        observation_space = make_policy_observation_space()
        action_space = spaces.MultiDiscrete([9, 8])

        def reset(self, *, seed=None, options=None):
            return np.zeros(15, np.float32), {}

        def step(self, a):
            return np.zeros(15, np.float32), 0.0, False, True, {}

    out: Dict[str, Any] = {}
    for name, env, pol, kw in (("v1", V1Env, "MlpPolicy", {"net_arch": {"pi": [64, 64], "vf": [64, 64]},
                                                             "activation_fn": torch.nn.Tanh}),
                               ("v3", _DictEnv, "MultiInputPolicy", mnp.policy_kwargs())):
        venv = DummyVecEnv([env])
        model = PPO(pol, venv, policy_kwargs=kw, device="cpu", seed=0, n_steps=16, batch_size=16)
        res = {}
        for batch in (5, 512):
            sample = [venv.observation_space.sample() for _ in range(batch)]
            if isinstance(sample[0], dict):
                obs = {k: np.stack([x[k] for x in sample]) for k in sample[0]}
            else:
                obs = np.stack(sample)
            t, _ = model.policy.obs_to_tensor(obs)
            with torch.no_grad():
                for _ in range(5):
                    model.policy(t)
                t0 = time.perf_counter()
                for _ in range(50):
                    model.policy(t)
                res[f"forward_batch_{batch}_ms"] = round((time.perf_counter() - t0) / 50 * 1e3, 3)
        res["parameters"] = int(sum(p.numel() for p in model.policy.parameters()))
        out[name] = res
    return out


def unit_isolation(s: Suite) -> Dict[str, Any]:
    files = ["m7n_obs.py", "m7n_entity.py", "m7n_policy.py", "m7n_status_table.py", "m7n_equivalence.py"]
    fixture_ref = re.compile(r"m7g_(fixture|capture|crossing)|fixtures['\"\s,/\\()]*m7g|lower_precision|"
                             r"upper_moving_platform|\.learn\(|tas_input|optimal[_ ]path|preferred[_ ]crossing|"
                             r"go[_ ]left|target[_ ]order", re.I)
    hits = {}
    for f in files:
        text = (RL_DIR / f).read_text(encoding="utf-8")
        found = sorted({m.group(0) for m in fixture_ref.finditer(text)})
        # the docstrings name the forbidden vocabulary in FORBIDDEN_CONTENT / the excluded list only
        found = [x for x in found if x.lower() not in ("optimal path", "preferred crossing", "target order", "go left")]
        if found:
            hits[f] = found
    check(not hits, f"forbidden references {hits}")
    return {"files": files}


# -- game -----------------------------------------------------------------------------------------------------------

def _artifact_track1(name: str) -> Tuple[List[Tuple[int, int, int, Optional[int]]], List[np.ndarray]]:
    import m7f_trace as mt
    from btt_learning import native_to_track1

    acts, _md = mt.artifact_actions(REPO_ROOT / dict(mt.FIXTURE_ARTIFACTS)[name])
    return acts, [np.array(native_to_track1(b, x, y)) for b, x, y, _ in acts]


def _m5_v3_env(root: Path, *, check_invariants: bool = True) -> Tuple[Any, Any]:
    import btt_learning as bl

    cfg = bl.LearningEnvConfig(executable=str(EXECUTABLE), artifact_root=root / "artifacts",
                               episodes_root=root / "episodes", max_episode_steps=3600, extra_env=dict(V3_FLAGS))
    env = bl.make_learning_env(cfg)
    return env, mn.EntityObsV3Wrapper(env, base=env.base_env, check_invariants=check_invariants)


def _offline_v3(trace: Dict[str, Any]) -> List[str]:
    init = trace["initial"]
    sp0 = ms.spatial_of(init, expect_lines=True)
    b = mn.EntityObservationBuilder(sp0.lines or (), st.ActionClassifier(st.load_table(), "mario"))
    out = []
    for i, reply in enumerate([init] + list(trace.get("steps") or [])):
        sp = sp0 if i == 0 else ms.spatial_of(reply, expect_lines=False)
        obs, _ = b.build(reply["observation"], sp, ne.entity_of(reply))
        out.append(mn.observation_digest(obs))
    return out


def game_wrapper_vs_raw(s: Suite) -> Dict[str, Any]:
    import m7f_trace as mt
    from m7_runtime import list_processes_named

    d = s.dir("game_wrapper_vs_raw")
    out: Dict[str, Any] = {}
    for name in (ARTIFACT_HORIZON, ARTIFACT_FALL):
        acts, t1 = _artifact_track1(name)
        env, v3 = _m5_v3_env(d / f"wrapper_{name}")
        digests: List[str] = []
        stale_at: List[int] = []
        try:
            o, info = v3.reset()
            check(info["policy_observation_contract"] == mn.OBS_CONTRACT and v3.base.last_observe.step_count == 0
                  and info["v3_stale"] is False, "reset contract / step count")
            digests.append(mn.observation_digest(o))
            steps = 0
            first_consumed = None
            end = None
            for a in t1:
                o, _r, term, trunc, info = v3.step(a)
                steps += 1
                if first_consumed is None:
                    first_consumed = v3.base.last_step_result.consumed_tick
                if info.get("v3_stale"):
                    stale_at.append(steps)
                digests.append(mn.observation_digest(o))
                if term or trunc:
                    end = info.get("termination_reason") or info.get("truncation_reason")
                    break
            problems = list(v3.invariant_problems)
            unmapped = info.get("v3_unmapped_status_ids")
        finally:
            env.close()
        check(not problems, f"{name}: invariant problems {problems[:3]}")
        check(first_consumed == 0, f"{name}: first consumed tick {first_consumed}")
        check(not unmapped, f"{name}: unmapped ids {unmapped}")
        check(all(x == steps for x in stale_at), f"{name}: stale steps {stale_at} (only a terminal reply may be stale)")
        raw = mt.run_stepping_trace("raw", EXECUTABLE, acts, d / f"raw_{name}", extra_env=dict(V3_FLAGS))
        offline = _offline_v3(raw)
        check(len(offline) == len(digests) and offline == digests,
              f"{name}: wrapper vs offline v3 differ (first at "
              f"{next((i for i, (x, y) in enumerate(zip(offline, digests)) if x != y), None)}; {len(offline)} vs {len(digests)})")
        out[name] = {"steps": steps, "end": end, "stale_steps": stale_at,
                     "chain": hashlib.sha256("".join(digests).encode("ascii")).hexdigest()}
    check(not list_processes_named(), "leftover BattleShip")
    return out


def _worker_specs(base: Path, n: int, run_id: str, *, v3: bool, standby: bool, **kw: Any) -> Tuple[List[Any], Path]:
    from btt_parallel import RunCoordinator, WorkerFactory, WorkerSpec, initial_coordination_state
    from m7_runtime import prepare_worker_runtime

    coord = base / "coordination"
    RunCoordinator.create(coord, initial_coordination_state(run_id, "test", None))
    extra = tuple(FLAGS.items()) + (mn.ENTITY_EXTRA_ENV if v3 else ())
    factories = []
    for rank in range(n):
        wd = base / "workers" / f"w{rank:02d}"
        prepare_worker_runtime(wd / "runtime", EXECUTABLE)
        spec = WorkerSpec(rank=rank, run_id=run_id, role="test", worker_dir=str(wd.resolve()),
                          coordination_dir=str(coord.resolve()), executable=str(EXECUTABLE), horizon=3600,
                          extra_env=extra, standby_preboot=standby, standby_count=1 if standby else 0, **kw)
        factories.append(mn.M7nWorkerFactory(spec) if v3 else WorkerFactory(spec))
    return factories, coord


def game_standby_v3(s: Suite) -> Dict[str, Any]:
    from m7_runtime import list_processes_named
    from run_artifacts import read_artifact

    d = s.dir("game_standby_v3")
    _acts, t1 = _artifact_track1(ARTIFACT_HORIZON)
    factories, _coord = _worker_specs(d, 1, "m7n_standby_v3", v3=True, standby=True, preserve_all=True)
    env = factories[0]()
    episodes = []
    try:
        for _ep in range(2):
            o, info = env.reset()
            chain = hashlib.sha256()
            chain.update(mn.observation_digest(o).encode())
            first_consumed = None
            n = 0
            for a in t1:
                o, _r, term, trunc, info = env.step(a)
                if first_consumed is None:
                    first_consumed = env.base.last_step_result.consumed_tick
                chain.update(mn.observation_digest(o).encode())
                n += 1
                if term or trunc:
                    break
            episodes.append({"mode": info.get("m7_episode", {}).get("startup_mode") or
                             (env.base.current_startup or {}).get("mode"), "steps": n, "chain": chain.hexdigest(),
                             "first_consumed_tick": first_consumed, "stale": env.env.env.stale_steps})
    finally:
        env.close()
    modes = [e["mode"] for e in episodes]
    check(modes == ["cold_start", "standby_promoted"], f"modes {modes}")
    check(episodes[0]["chain"] == episodes[1]["chain"], "cold vs promoted v3 observations differ")
    check(all(e["first_consumed_tick"] == 0 for e in episodes), f"first consumed ticks {episodes}")
    arts = sorted((d / "workers" / "w00" / "artifacts").iterdir())
    labels = [read_artifact(a).metadata["labels"]["contracts"] for a in arts]
    check(len(arts) == 2 and all(lb["policy_observation_contract"] == mn.OBS_CONTRACT
                                 and lb["action_class_table_sha256"] == st.load_table()["sha256"] for lb in labels),
          f"artifact labels {labels}")
    check(not list_processes_named(), "leftover BattleShip")
    return {"episodes": episodes}


def game_sb3_real(s: Suite) -> Dict[str, Any]:
    import torch
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

    from m7_runtime import list_processes_named

    torch.set_num_threads(1)
    d = s.dir("game_sb3_real")
    holder: Dict[str, Any] = {}

    def make():
        env, v3 = _m5_v3_env(d / f"env{len(holder)}", check_invariants=True)
        holder[len(holder)] = env
        return v3

    venv = mnp.make_vecnormalize(DummyVecEnv([make]))
    out: Dict[str, Any] = {}
    try:
        model = mnp.make_model(venv, seed=0)
        out["network"] = mnp.describe(model)
        obs = venv.reset()
        raw = venv.get_original_obs()
        check(all(np.array_equal(obs[k], raw[k]) for k in mn.KEY_ORDER), "VecNormalize changed an observation")
        check(raw["targets"][0, :, 4].sum() == 10 and raw["agent"].shape == (1, 28), "reset observation")
        with torch.no_grad():
            actions, values, _logp = model.policy(model.policy.obs_to_tensor(obs)[0])
        out["first_forward"] = {"action": actions.numpy().tolist(), "value": float(values[0, 0])}
        for _ in range(200):
            a, _ = model.predict(obs, deterministic=False)
            obs, _r, _done, _i = venv.step(a)
        check(all(np.isfinite(obs[k]).all() for k in mn.KEY_ORDER), "non-finite observation from the game")
        model.save(d / "model.zip")
        venv.save(str(d / "vecnormalize.pkl"))
        mnp.assert_v3_checkpoint(d / "model.zip")
        frozen = VecNormalize.load(str(d / "vecnormalize.pkl"), venv.venv)
        frozen.training = False
        frozen.norm_reward = False
        model2 = PPO.load(d / "model.zip", env=frozen, device="cpu")
        o = frozen.reset()
        same = 0
        for _ in range(100):
            a1, _ = model.predict(o, deterministic=True)
            a2, _ = model2.predict(o, deterministic=True)
            same += int(np.array_equal(a1, a2))
            o, _r, _d, _i = frozen.step(a2)
        check(same == 100, f"reloaded model disagrees on {100 - same}/100 observations")
        problems = [p for env in holder.values() for p in getattr(env, "invariant_problems", [])]
        out["invariant_problems"] = len(problems)
    finally:
        venv.close()
        for env in holder.values():
            env.close()
    check(not list_processes_named(), "leftover BattleShip")
    return out


def _bench_arm(root: Path, v3: bool, steps: int, seed: int) -> Dict[str, Any]:
    from m7_runtime import list_processes_named
    from m7_vec_env import M7SubprocVecEnv

    factories, _coord = _worker_specs(root, 5, f"m7n_bench_{'v3' if v3 else 'v1'}", v3=v3, standby=True)
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
    return {"v3": v3, "vec_steps": steps, "transitions": steps * 5, "seconds": round(dt, 2),
            "transitions_per_s": round(steps * 5 / dt, 1), "episodes_finished": episodes,
            "peak_processes": peak, "leftover": left,
            "worker_native_step_mean_ms": round(native["sum_s"] / max(native["n"], 1) * 1e3, 4),
            "worker_service_mean_ms": round(service["sum_s"] / max(service["n"], 1) * 1e3, 4),
            "worker_python_overhead_mean_ms": round((service["sum_s"] / max(service["n"], 1)
                                                     - native["sum_s"] / max(native["n"], 1)) * 1e3, 4)}


def game_n5_standby_bench(s: Suite) -> Dict[str, Any]:
    d = s.dir("game_n5_standby_bench")
    arms = []
    for rep, v3 in ((0, False), (0, True), (1, True), (1, False)):
        arms.append(_bench_arm(d / f"{'v3' if v3 else 'v1'}_{rep}", v3, BENCH_VEC_STEPS, seed=rep))
    for a in arms:
        check(a["peak_processes"] <= 10 and not a["leftover"], f"processes: {a}")
    v1 = [a["transitions_per_s"] for a in arms if not a["v3"]]
    v3 = [a["transitions_per_s"] for a in arms if a["v3"]]
    per = {k: {"v1": round(float(np.mean([a[k] for a in arms if not a["v3"]])), 4),
               "v3": round(float(np.mean([a[k] for a in arms if a["v3"]])), 4)}
           for k in ("worker_native_step_mean_ms", "worker_service_mean_ms", "worker_python_overhead_mean_ms")}
    rel = float(np.mean(v3)) / float(np.mean(v1))
    check(rel >= 0.80, f"v3 environment throughput {rel:.3f} of v1 (< 0.80)")
    return {"arms": arms, "v1_mean": round(float(np.mean(v1)), 1), "v3_mean": round(float(np.mean(v3)), 1),
            "v3_relative": round(rel, 4), "worker_times": per,
            "note": "random Track 1 actions, no policy inference, no learning: environment-side throughput only"}


UNIT_CASES: Dict[str, Callable[[Suite], Dict[str, Any]]] = {
    "unit_contract": unit_contract, "unit_entity_parser": unit_entity_parser, "unit_builder": unit_builder,
    "unit_offline_traces": unit_offline_traces, "unit_sb3_dummy": unit_sb3_dummy, "unit_config": unit_config,
    "unit_inference_timing": unit_inference_timing, "unit_isolation": unit_isolation, "unit_rule": unit_rule,
    "unit_matrix": unit_matrix, "unit_crossing": unit_crossing,
}
GAME_CASES: Dict[str, Callable[[Suite], Dict[str, Any]]] = {
    "game_wrapper_vs_raw": game_wrapper_vs_raw, "game_standby_v3": game_standby_v3, "game_sb3_real": game_sb3_real,
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
    root = (Path(args.root) if args.root else REPO_ROOT / "runs" / "m7n" / "_tests" / f"m7n_{stamp}").resolve()
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
    (root / "m7n_tests_results.json").write_text(json.dumps({"schema": "battleship_m7n_tests_v1", "utc": stamp,
                                                             "results": results, "ok": ok}, indent=1, default=str)
                                                 + "\n", encoding="utf-8", newline="\n")
    print(f"m7n_tests: {sum(r['status'] == 'PASS' for r in results.values())}/{len(results)} PASS -> {root}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
