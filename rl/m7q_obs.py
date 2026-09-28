"""M7q: policy observation `btt_policy_obs_v4_input` (v3 + the native input state; fixed-scaled; character-independent).

A separately versioned policy observation for Track 1. `btt_policy_obs_v1`, `btt_policy_obs_v2_spatial`,
`btt_policy_obs_v3_entities` (rl/m7n_obs.py) and the opt-in `btt_policy_obs_v3_geo4` are untouched. v4 is the v3 Dict
with two changed keys; `projectiles`, `segment_geometry`, `segment_kind` and `targets` are v3's, byte-identical:

  action_class      float32 (23,)     one-hot of `btt_action_class_table_v2` (rl/m7q_status_table.py): v3's 20 classes
                                      with FallSpecial -> helpless, StopCeil -> air_lock and landing split into
                                      landing_free / landing_lag
  agent             float32 (45,)     indices 0-27 = v3's 28 fields in v3's order and scaling (bit-identical to v3),
                                      then 17 appended fields from the native `btt_input_state_v1` diagnostic
                                      (rl/m7q_input.py, SSB64_RL_INPUT=1) and one spatial contact bit:
                                        28 stick_x, 29 stick_y                     stick_range / 80
                                        30-36 hold_A, hold_B, hold_Z, hold_L, hold_R, hold_Cup, hold_Cleft
                                                                                   bits of button_hold after the R fold
                                        37 tap_x, 38 tap_y                         5-level tap freshness (TAP_LEVELS)
                                        39 z_age                                   min(tics_since_last_z, 10) / 10
                                        40 z_out                                   1 iff tics_since_last_z > 10
                                        41 anim_frame                              clip(anim_frame, 0, 240) / 60
                                        42 anim_speed                              clip(anim_speed, 0, 2) / 2
                                        43 aerial_lag_armed                        motion_flag1 != 0 AND the status is
                                                                                   an aerial attack (else 0)
                                        44 contact_edge                            mask_curr & MAP_FLAG_FLOOREDGE

Flat size 23 + 45 + 28 + 256 + 224 + 50 = 626. No running normalisation; masks, key order, the stale rule (info
`v4_stale`), the displacement rule, the reset re-observe and the world-state-not-route rule are v3's. Every appended
value is native state read after the game applied the action (never the agent's own action history); the diagnostic
carries the full values, the policy block only these bounded encodings. Design: docs/rl_observation_v4_proposal_2026-09-28.md.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import gymnasium as gym
import numpy as np
from gymnasium import spaces

import m7g_spatial as ms
import m7n_entity as ne
import m7n_obs as mn
import m7n_status_table as st1
import m7q_input as mi
import m7q_status_table as st2

OBS_CONTRACT = "btt_policy_obs_v4_input"
OBS_SCHEMA_VERSION = 1

STICK_SCALE = 80.0
TAP_LEVELS = {1: 1.0, 2: 0.75, 3: 0.5}       # 4..253 -> 0.25; 254 (outside the band / forced stale) -> 0; 0 -> 0 + anomaly
TAP_STALE_LEVEL = 0.25
Z_WINDOW = mi.Z_CANCEL_WINDOW                # 10: ages 0..10 distinct, z_out marks 11+
ANIM_FRAME_CAP = 240.0
ANIM_FRAME_SCALE = mn.PROGRESS_SCALE         # 60, as status_tics
ANIM_SPEED_CAP = 2.0
CONTACT_EDGE_BIT = 0x8000                    # MAP_FLAG_FLOOREDGE (mpdef.h), transported in spatial fighter.mask_curr

AGENT_KEY, ACTION_CLASS_KEY = mn.AGENT_KEY, mn.ACTION_CLASS_KEY
PROJECTILES_KEY, SEGMENT_GEOMETRY_KEY, SEGMENT_KIND_KEY, TARGETS_KEY = (mn.PROJECTILES_KEY, mn.SEGMENT_GEOMETRY_KEY,
                                                                         mn.SEGMENT_KIND_KEY, mn.TARGETS_KEY)
KEY_ORDER = mn.KEY_ORDER
HOLD_FIELDS = ("hold_A", "hold_B", "hold_Z", "hold_L", "hold_R", "hold_Cup", "hold_Cleft")
HOLD_BITS = mi.CONTRACT_BUTTONS   # same order as HOLD_FIELDS
APPENDED_FIELDS = ("stick_x", "stick_y", *HOLD_FIELDS, "tap_x", "tap_y", "z_age", "z_out", "anim_frame", "anim_speed",
                   "aerial_lag_armed", "contact_edge")
AGENT_FIELDS = mn.AGENT_FIELDS + APPENDED_FIELDS
V3_AGENT_COUNT = len(mn.AGENT_FIELDS)      # 28

SHAPES: Dict[str, Tuple[int, ...]] = dict(mn.SHAPES)
SHAPES[ACTION_CLASS_KEY] = (len(st2.CLASSES),)
SHAPES[AGENT_KEY] = (len(AGENT_FIELDS),)
FLAT_SIZE = int(sum(int(np.prod(s)) for s in SHAPES.values()))   # 626
MASK_COLUMNS = mn.MASK_COLUMNS
BINARY_KEYS = mn.BINARY_KEYS

ENTITY_EXTRA_ENV: Tuple[Tuple[str, str], ...] = mn.ENTITY_EXTRA_ENV + ((mi.INPUT_ENV, "1"),)
DEFAULT_CHARACTER = mn.DEFAULT_CHARACTER
FORBIDDEN_CONTENT = mn.FORBIDDEN_CONTENT + ("action mask", "ledge fields (none on this stage)", "tornado fields")

observation_digest = mn.observation_digest
flatten = mn.flatten
masked_rows_are_zero = mn.masked_rows_are_zero
character_of = mn.character_of


class ObservationV4Error(RuntimeError):
    """The v4 observation cannot be built (missing / inconsistent native data)."""


def make_observation_space() -> spaces.Dict:
    inf = np.inf
    return spaces.Dict({
        ACTION_CLASS_KEY: spaces.Box(0.0, 1.0, SHAPES[ACTION_CLASS_KEY], np.float32),
        AGENT_KEY: spaces.Box(-inf, inf, SHAPES[AGENT_KEY], np.float32),
        PROJECTILES_KEY: spaces.Box(-inf, inf, SHAPES[PROJECTILES_KEY], np.float32),
        SEGMENT_GEOMETRY_KEY: spaces.Box(-inf, inf, SHAPES[SEGMENT_GEOMETRY_KEY], np.float32),
        SEGMENT_KIND_KEY: spaces.Box(0.0, 1.0, SHAPES[SEGMENT_KIND_KEY], np.float32),
        TARGETS_KEY: spaces.Box(-inf, inf, SHAPES[TARGETS_KEY], np.float32),
    })


def tap_level(counter: int) -> float:
    """The 5-level tap encoding: 1 -> 1.0, 2 -> 0.75, 3 -> 0.5, 4..253 -> 0.25, 254 -> 0. Native 0 (impossible after
    fighter creation) also reads 0; the builder counts it as an anomaly."""
    c = int(counter)
    if c in TAP_LEVELS:
        return TAP_LEVELS[c]
    if 4 <= c < mi.TAP_MAX:
        return TAP_STALE_LEVEL
    return 0.0


def appended_fields(inp: mi.InputSnapshot, status_id: int, mask_curr: int, aerial_ids: Sequence[int]
                    ) -> Tuple[List[float], List[str]]:
    """The 17 appended agent values for one reply, plus anomaly strings (tap counter 0, forbidden button bit)."""
    anomalies: List[str] = []
    if inp.tap_stick_x == 0 or inp.tap_stick_y == 0:
        anomalies.append(f"tap counter 0 ({inp.tap_stick_x}, {inp.tap_stick_y})")
    if inp.button_hold & mi.FORBIDDEN_BUTTON_MASK:
        anomalies.append(f"forbidden button bit in 0x{inp.button_hold:04x}")
    t = int(inp.tics_since_last_z)
    speed = float(inp.anim_speed)
    frame = float(inp.anim_frame)
    values = [
        float(inp.stick_x) / STICK_SCALE, float(inp.stick_y) / STICK_SCALE,
        *[1.0 if inp.button_hold & bit else 0.0 for bit in HOLD_BITS],
        tap_level(inp.tap_stick_x), tap_level(inp.tap_stick_y),
        min(max(t, 0), Z_WINDOW) / float(Z_WINDOW), 1.0 if t > Z_WINDOW else 0.0,
        min(max(frame, 0.0), ANIM_FRAME_CAP) / ANIM_FRAME_SCALE,
        min(max(speed, 0.0), ANIM_SPEED_CAP) / ANIM_SPEED_CAP,
        1.0 if (int(inp.motion_flag1) != 0 and int(status_id) in aerial_ids) else 0.0,
        1.0 if int(mask_curr) & CONTACT_EDGE_BIT else 0.0,
    ]
    return values, anomalies


class InputObservationBuilder(mn.EntityObservationBuilder):
    """The v3 builder (which computes the v3 blocks and the v3 agent slice exactly as v3 does) plus the v4 action
    class and the 17 appended agent fields. Pure and deterministic given the reply sequence of the episode."""

    def __init__(self, lines: Sequence[ms.SpatialLine], classifier_v1: st1.ActionClassifier,
                 classifier_v2: st2.ActionClassifier, aerial_ids: Sequence[int]):
        super().__init__(lines, classifier_v1)
        self.classifier2 = classifier_v2
        self.aerial_ids = frozenset(int(i) for i in aerial_ids)
        self._last_obs4: Optional[Dict[str, np.ndarray]] = None
        self.input_anomalies: List[str] = []

    def reset_episode(self) -> None:
        super().reset_episode()
        self._last_obs4 = None
        self.input_anomalies = []
        if hasattr(self, "classifier2"):
            self.classifier2.unmapped_seen.clear()

    def build(self, observation: Mapping[str, Any], spatial: ms.SpatialSnapshot, entity: ne.EntitySnapshot,   # type: ignore[override]
              inp: Optional[mi.InputSnapshot] = None) -> Tuple[Dict[str, np.ndarray], bool]:
        """(v4 observation, stale). Stale = a teardown reply or an invalid fighter: the last complete v4 observation
        is repeated (the v3 blocks follow v3's own stale rule inside the base class)."""
        if inp is None:
            raise ObservationV4Error("v4 needs the input snapshot")
        tick = int(observation["input_tick"])
        if inp.input_tick != tick:
            raise ObservationV4Error(f"input snapshot {inp.input_tick} != observation {tick}")
        obs3, stale = super().build(observation, spatial, entity)
        if stale or not (inp.live and inp.valid):
            if self._last_obs4 is None:
                raise ObservationV4Error("no live reply in this episode yet")
            if not stale:
                self.stale_builds += 1
            return {k: v.copy() for k, v in self._last_obs4.items()}, True
        status_id = int(observation["fighter_status_id"])
        assert spatial.fighter is not None
        values, anomalies = appended_fields(inp, status_id, int(spatial.fighter.mask_curr), self.aerial_ids)
        self.input_anomalies += [f"tick {tick}: {a}" for a in anomalies]
        agent = np.concatenate([obs3[AGENT_KEY], np.array(values, dtype=np.float32)]).astype(np.float32)
        action_class = np.zeros(SHAPES[ACTION_CLASS_KEY], dtype=np.float32)
        action_class[self.classifier2.index(status_id)] = 1.0
        obs4 = dict(obs3)
        obs4[AGENT_KEY] = agent
        obs4[ACTION_CLASS_KEY] = action_class
        self._last_obs4 = obs4
        return {k: v.copy() for k, v in obs4.items()}, False


class EntityObsV4Wrapper(mn.EntityObsV3Wrapper):
    """EntityObsV3Wrapper whose builder is the v4 builder and whose replies must also carry the `input` object."""

    contract_id = OBS_CONTRACT

    def __init__(self, env: Any, *, base: Any, character: str = DEFAULT_CHARACTER, check_invariants: bool = False,
                 table: Optional[Dict[str, Any]] = None, table_v2: Optional[Dict[str, Any]] = None):
        super().__init__(env, base=base, character=character, check_invariants=check_invariants, table=table)
        self.observation_space = make_observation_space()
        self.table_v2 = table_v2 if table_v2 is not None else st2.load_table()
        self.classifier2 = st2.ActionClassifier(self.table_v2, character)
        self.aerial_ids = st2.aerial_attack_ids(self.table_v2)
        self._prev_input: Optional[mi.InputSnapshot] = None

    def _make_builder(self, lines: Sequence[ms.SpatialLine]) -> InputObservationBuilder:
        return InputObservationBuilder(lines, self.classifier, self.classifier2, self.aerial_ids)

    def _check_input(self, inp: mi.InputSnapshot, observation: Mapping[str, Any], where: str) -> None:
        if self.check_invariants:
            problems = mi.check_snapshot(inp, observation, prev=self._prev_input, prev_observation=self._prev_observation)
            if problems:
                self.invariant_problems.append({"where": where, "input_tick": inp.input_tick, "problems": problems})
        self._prev_input = inp

    def _info(self, info: Dict[str, Any], stale: bool) -> Dict[str, Any]:
        info["policy_observation_contract"] = self.contract_id
        info["v4_stale"] = stale
        info["v4_unmapped_status_ids"] = dict(self.classifier2.unmapped_seen)
        info["v4_projectile_overflow"] = self.builder.projectile_overflow if self.builder else 0
        info["v4_input_anomalies"] = len(self.builder.input_anomalies) if self.builder else 0
        return info

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        _state, info = self.env.reset(seed=seed, options=options)
        episode = self.base.episode
        if episode is None or episode.client is None:
            raise ObservationV4Error("no active episode after reset")
        self._capture(episode.client)
        reply = episode.client.request("observe")        # non-consuming: no tick, no clock
        reset_obs = mn._observation_fields(self.base.last_observe.observation)
        if reply.get("ok") is not True or reply.get("observation") != reset_obs:
            raise ObservationV4Error("the v4 re-observe does not match the reset observation "
                                     f"({reply.get('observation')} vs {reset_obs})")
        sp = ms.spatial_of(reply, expect_lines=True)
        en = ne.entity_of(reply)
        inp = mi.input_of(reply)
        self.builder = self._make_builder(sp.lines or ())
        self._prev_spatial = self._prev_entity = self._prev_observation = None
        self._prev_input = None
        self._static_targets = {i: sp.target_positions[i] for i in range(ms.TARGET_COUNT)
                                if i != ms.MOVING_TARGET_ID and sp.target_live_mask & (1 << i)}
        self._check_input(inp, reply["observation"], "reset")   # before _check: it reads _prev_observation of the prior reply
        self._check(sp, en, reply["observation"], "reset")
        obs, stale = self.builder.build(reply["observation"], sp, en, inp)
        self._last_obs = obs
        self.stale_steps = 0
        return obs, self._info(info, stale)

    def step(self, action: Any):
        self._last_reply = None
        _state, reward, terminated, truncated, info = self.env.step(action)
        if info.get("truncation_reason") == "episode_failure":
            return self._last_obs, reward, terminated, truncated, self._info(info, True)
        reply = self._last_reply
        result = self.base.last_step_result
        if reply is None or reply.get("op") != "step" or result is None or reply.get("step_count") != result.step_count:
            raise ObservationV4Error("no raw step reply paired with the collected step result")
        sp = ms.spatial_of(reply, expect_lines=False)
        en = ne.entity_of(reply)
        inp = mi.input_of(reply)
        self._check_input(inp, reply["observation"], f"step {result.step_count}")
        self._check(sp, en, reply["observation"], f"step {result.step_count}")
        assert self.builder is not None
        obs, stale = self.builder.build(reply["observation"], sp, en, inp)
        if stale:
            self.stale_steps += 1
        self._last_obs = obs
        return obs, reward, terminated, truncated, self._info(info, stale)


# -- contract, stacks ----------------------------------------------------------------------------------------


def contract_description() -> Dict[str, Any]:
    """The machine-readable v4 contract (also written to docs/rl_observation_v4_m7q.schema.json)."""
    d = mn.contract_description()
    table = st2.load_table()
    d["contract"] = OBS_CONTRACT
    d["schema_version"] = OBS_SCHEMA_VERSION
    d["derived_from"] = {"contract": mn.OBS_CONTRACT, "contract_sha256": mn.contract_digest(),
                         "unchanged_keys": [PROJECTILES_KEY, SEGMENT_GEOMETRY_KEY, SEGMENT_KIND_KEY, TARGETS_KEY],
                         "agent_prefix": f"indices 0-{V3_AGENT_COUNT - 1} bit-identical to {mn.OBS_CONTRACT}"}
    d["keys"][ACTION_CLASS_KEY] = dict(d["keys"][ACTION_CLASS_KEY], shape=list(SHAPES[ACTION_CLASS_KEY]),
                                       fields=list(st2.CLASSES), table=table["table_id"], table_sha256=table["sha256"],
                                       rule_changes=table["rule_changes"], character_dependent=table["character_dependent"])
    units = dict(d["keys"][AGENT_KEY]["units"])
    units.update({
        "stick_x, stick_y": f"native stick_range / {STICK_SCALE:g} (after the game's clamp)",
        ", ".join(HOLD_FIELDS): "bits of native button_hold after the R -> A+Z fold (0 / 1); never a scalar word",
        "tap_x, tap_y": "native tap counter: 1 -> 1.0, 2 -> 0.75, 3 -> 0.5, 4..253 -> 0.25, 254 -> 0 (outside the band or "
                        "forced stale); 0 -> 0 and counted as an anomaly (impossible per source)",
        "z_age": f"min(tics_since_last_z, {Z_WINDOW}) / {Z_WINDOW} (ages 0..{Z_WINDOW} distinct)",
        "z_out": f"1 iff tics_since_last_z > {Z_WINDOW} (outside the Z-cancel window, incl. the 65536 reset)",
        "anim_frame": f"clip(GObj anim_frame, 0, {ANIM_FRAME_CAP:g}) / {ANIM_FRAME_SCALE:g} (animation frames; frozen in hitlag)",
        "anim_speed": f"clip(DObj anim_speed, 0, {ANIM_SPEED_CAP:g}) / {ANIM_SPEED_CAP:g}",
        "aerial_lag_armed": "1 iff motion_flag1 != 0 and the status id is an aerial attack (nFTCommonStatusAttackAir*); "
                            "0 in every other status by definition",
        "contact_edge": "spatial mask_curr & 0x8000 (MAP_FLAG_FLOOREDGE) (0 / 1)",
    })
    d["keys"][AGENT_KEY] = dict(d["keys"][AGENT_KEY], shape=list(SHAPES[AGENT_KEY]), fields=list(AGENT_FIELDS), units=units)
    d["flat_size"] = FLAT_SIZE
    d["scaling"] = dict(d["scaling"], stick=STICK_SCALE, anim_speed_cap=ANIM_SPEED_CAP, anim_frame_cap=ANIM_FRAME_CAP,
                        z_window=Z_WINDOW, tap_levels={str(k): v for k, v in TAP_LEVELS.items()}, tap_stale=TAP_STALE_LEVEL)
    d["stale_rule"] = d["stale_rule"].replace("info['v3_stale']", "info['v4_stale']")
    d["input_rule"] = ("every appended value is native state captured after the game applied the action (never the "
                       "agent's own action history); full values stay in the diagnostic, only these bounded "
                       "encodings enter the policy block; motion_flag1 is interpreted only in aerial-attack statuses")
    d["character"] = dict(d["character"], validated_tables=list(st2.VALIDATED),
                          rule=d["character"]["rule"].replace("v3_unmapped_status_ids", "v4_unmapped_status_ids"),
                          character_dependent=table["character_dependent"])
    d["native_sources"] = dict(d["native_sources"], input={"diagnostic": mi.CONTRACT, "env": f"{mi.INPUT_ENV}=1"})
    d["excluded"] = list(FORBIDDEN_CONTENT)
    d["compatibility"] = ("fresh models only; a btt_policy_obs_v1, v2_spatial, v3_entities or v3_geo4 checkpoint is refused; "
                          "v3 stays available, byte-identical and the selected default")
    return d


def contract_digest() -> str:
    return hashlib.sha256(json.dumps(contract_description(), sort_keys=True).encode("utf-8")).hexdigest()


def m7q_contracts(horizon: int, reward: Any, character: str = DEFAULT_CHARACTER) -> Dict[str, Any]:
    """m7n_contracts with the v4 observation (every other contract unchanged)."""
    table = st2.load_table()
    c = mn.m7n_contracts(horizon, reward, character)
    c.update({"policy_observation_contract": OBS_CONTRACT,
              "policy_observation_shapes": {k: list(v) for k, v in SHAPES.items()},
              "policy_observation_contract_sha256": contract_digest(),
              "policy_observation_derived_from": mn.OBS_CONTRACT,
              "action_class_table": table["table_id"], "action_class_table_sha256": table["sha256"],
              "input_diagnostic_contract": mi.CONTRACT})
    return c


def build_worker_env_v4(spec: Any) -> Any:
    """The v3 worker stack (rl/m7n_obs.build_worker_env_v3) with EntityObsV4Wrapper in place of the v3 wrapper; the
    spec's extra_env must carry SSB64_RL_SPATIAL=1, SSB64_RL_ENTITY=1 and SSB64_RL_INPUT=1."""
    missing = [f"{k}={v}" for k, v in ENTITY_EXTRA_ENV if dict(spec.extra_env).get(k) != v]
    if missing:
        raise ValueError(f"v4 worker spec needs {missing} in extra_env")
    return mn.build_worker_env_v3(spec, wrapper_cls=EntityObsV4Wrapper, contracts_fn=m7q_contracts)


class M7qWorkerFactory:
    """Top-level, picklable factory (spawn-safe) for the v4 worker stack."""

    def __init__(self, spec: Any):
        self.spec = spec

    def __call__(self) -> Any:
        return build_worker_env_v4(self.spec)


if __name__ == "__main__":
    import sys
    from pathlib import Path

    if len(sys.argv) > 1 and sys.argv[1] == "schema":
        out = Path(__file__).resolve().parent.parent / "docs" / "rl_observation_v4_m7q.schema.json"
        out.write_text(json.dumps({"contract": contract_description(), "contract_sha256": contract_digest()}, indent=1)
                       + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {out} digest {contract_digest()[:16]} flat {FLAT_SIZE}")
    else:
        print(json.dumps({"contract": OBS_CONTRACT, "flat_size": FLAT_SIZE, "digest": contract_digest(),
                          "derived_from": mn.OBS_CONTRACT, "v3_digest": mn.contract_digest()}, indent=1))
