"""M7n: policy observation `btt_policy_obs_v3_entities` (fixed-scaled, masked entity rows; character-independent).

A separately versioned policy observation for Track 1. `btt_policy_obs_v1` (rl/btt_learning.py) and
`btt_policy_obs_v2_spatial` (rl/m7g_obs.py) are untouched. v3 is a Gymnasium Dict built from the paired native
observation (the 17-key M1b reply), the `btt_spatial_v1` diagnostic (rl/m7g_spatial.py, SSB64_RL_SPATIAL=1) and the
`btt_entity_v1` diagnostic (rl/m7n_entity.py, SSB64_RL_ENTITY=1):

  action_class      float32 (20,)     one-hot class of the fighter status id (rl/m7n_status_table.py, character-
                                      independent classes; an id absent from the character's table -> `unmapped`)
  agent             float32 (28,)     the agent: position, displacement since the previous reply, self velocities,
                                      moving-floor carry, facing, grounded, contacts, floor distance, jumps left,
                                      raw status id, action progress, hitlag, flags, clock, targets left, diamond
  projectiles       float32 (4, 7)    the agent's own live weapons in sticky slots: present, dx, dy, vx, vy,
                                      hitbox_active, life
  segment_geometry  float32 (32, 8)   as v2 (endpoints, closest point, velocity relative to the agent), scaled
  segment_kind      float32 (32, 7)   as v2 (present, floor, ceiling, wall +x, wall -x, one-way, moving)
  targets           float32 (10, 5)   per stable target ID: dx, dy, vx, vy (position change since the previous
                                      reply), live

Every length is divided by LENGTH_SCALE (2,000 native units), every velocity by VELOCITY_SCALE (50 units / tick), the
clock by TIME_SCALE (3,600 ticks) and action progress / hitlag by PROGRESS_SCALE (60 ticks). There is NO running
normalisation: a masked row (broken target, empty projectile slot, padding segment) is exactly zero at the network
input and stays zero whatever the run's statistics are; the same value means the same thing on every character and
stage. Ordering is stable (segment = native line id then vertex pair; target = M7f stable ID; projectile = sticky slot
assigned in spawn-serial order). The world state is described, never a route: no path, preferred crossing, target
order, gateway label, route distance, phase, period or future position.

Character independence: the agent's fields are relative to its own TopN or scaled by physical constants; the character
enters only through jumps_max, the collision diamond, the action-class table (looked up for the task's character; other
characters' ids are never mapped through another character's names) and the projectile kinds that appear. Only Mario's
table is validated (rl/m7n_status_table.VALIDATED); the builder records the character and counts unmapped ids.
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
import m7n_status_table as st

OBS_CONTRACT = "btt_policy_obs_v3_entities"
OBS_SCHEMA_VERSION = 1

LENGTH_SCALE = 2000.0     # native units per unit of every dx / dy / position / distance
VELOCITY_SCALE = 50.0     # native units per tick per unit of every velocity / displacement
TIME_SCALE = 3600.0       # ticks (the training horizon) per unit of the clock
PROGRESS_SCALE = 60.0     # ticks per unit of action progress / hitlag
STATUS_ID_SCALE = 256.0
STATUS_TICS_CAP = 240
HITLAG_CAP = 60
FLOOR_DIST_CAP = 8000.0
PROJECTILE_LIFE_SCALE = 140.0   # Mario's fireball lifetime; any weapon's remaining lifetime is clipped to [0, 1]

AGENT_KEY = "agent"
ACTION_CLASS_KEY = "action_class"
PROJECTILES_KEY = "projectiles"
SEGMENT_GEOMETRY_KEY = "segment_geometry"
SEGMENT_KIND_KEY = "segment_kind"
TARGETS_KEY = "targets"
# gymnasium sorts the keys of a plain-dict Dict space; SB3's CombinedExtractor concatenates in this order.
KEY_ORDER = (ACTION_CLASS_KEY, AGENT_KEY, PROJECTILES_KEY, SEGMENT_GEOMETRY_KEY, SEGMENT_KIND_KEY, TARGETS_KEY)

AGENT_FIELDS = ("pos_x", "pos_y", "disp_x", "disp_y", "air_vel_x", "air_vel_y", "ground_vel_x", "carry_x", "carry_y",
                "facing", "grounded", "contact_floor", "contact_ceil", "contact_lwall", "contact_rwall", "floor_dist",
                "jumps_left", "status_id", "status_tics", "hitlag", "attack_active", "cliff_hold", "shield_active",
                "fastfall", "time", "targets_left", "diamond_top", "diamond_width")
SEGMENT_GEOMETRY_FIELDS = ("a_dx", "a_dy", "b_dx", "b_dy", "near_dx", "near_dy", "vel_x", "vel_y")
SEGMENT_KIND_FIELDS = ("present", "floor", "ceiling", "wall_facing_pos_x", "wall_facing_neg_x", "one_way", "moving")
TARGET_FIELDS = ("dx", "dy", "vx", "vy", "live")
PROJECTILE_FIELDS = ("present", "dx", "dy", "vx", "vy", "hitbox_active", "life")

SEGMENT_SLOTS = 32
TARGET_SLOTS = ms.TARGET_COUNT
PROJECTILE_SLOTS = 4

SHAPES: Dict[str, Tuple[int, ...]] = {
    ACTION_CLASS_KEY: (len(st.CLASSES),),
    AGENT_KEY: (len(AGENT_FIELDS),),
    PROJECTILES_KEY: (PROJECTILE_SLOTS, len(PROJECTILE_FIELDS)),
    SEGMENT_GEOMETRY_KEY: (SEGMENT_SLOTS, len(SEGMENT_GEOMETRY_FIELDS)),
    SEGMENT_KIND_KEY: (SEGMENT_SLOTS, len(SEGMENT_KIND_FIELDS)),
    TARGETS_KEY: (TARGET_SLOTS, len(TARGET_FIELDS)),
}
FLAT_SIZE = int(sum(int(np.prod(s)) for s in SHAPES.values()))   # 606
MASK_COLUMNS = {SEGMENT_KIND_KEY: 0, TARGETS_KEY: 4, PROJECTILES_KEY: 0}   # the validity column of each masked key
BINARY_KEYS = (ACTION_CLASS_KEY, SEGMENT_KIND_KEY)

_TYPE_COLUMN = {ms.LINE_FLOOR: 1, ms.LINE_CEIL: 2, ms.LINE_RWALL: 3, ms.LINE_LWALL: 4}
_CONTACT_BITS = (ms.CONTACT_FLOOR, ms.CONTACT_CEIL, ms.CONTACT_LWALL, ms.CONTACT_RWALL)

ENTITY_EXTRA_ENV: Tuple[Tuple[str, str], ...] = ((ms.SPATIAL_ENV, "1"), (ne.ENTITY_ENV, "1"))
DEFAULT_CHARACTER = "mario"

FORBIDDEN_CONTENT = ("optimal path", "preferred crossing", "target order", "TAS action", "'go left' indicator",
                     "gateway / region labels", "distance along a handcrafted route", "future platform positions",
                     "platform phase or period", "future game state", "reward shaping")


class ObservationV3Error(RuntimeError):
    """The v3 observation cannot be built (missing / inconsistent native data)."""


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


def observation_digest(obs: Mapping[str, np.ndarray]) -> str:
    """sha256 over the keys in KEY_ORDER: name, dtype, shape and raw bytes (the determinism fingerprint)."""
    h = hashlib.sha256()
    for key in KEY_ORDER:
        a = np.ascontiguousarray(obs[key])
        h.update(f"{key}|{a.dtype.str}|{a.shape}|".encode("ascii"))
        h.update(a.tobytes())
    return h.hexdigest()


def flatten(obs: Mapping[str, np.ndarray]) -> np.ndarray:
    """The 606-float vector SB3's CombinedExtractor sees (keys in KEY_ORDER, each flattened C-order)."""
    return np.concatenate([np.asarray(obs[k], dtype=np.float32).reshape(-1) for k in KEY_ORDER])


def masked_rows_are_zero(obs: Mapping[str, np.ndarray]) -> List[str]:
    """Problems if any row whose validity column is 0 has a non-zero value (the neutral-absence rule)."""
    p: List[str] = []
    for key, col in MASK_COLUMNS.items():
        a = np.asarray(obs[key])
        for i in range(a.shape[0]):
            if a[i, col] == 0.0 and np.any(a[i] != 0.0):
                p.append(f"{key}[{i}] masked but non-zero: {a[i].tolist()}")
    return p


class EntityObservationBuilder:
    """Builds v3 observations for one episode from (native observation, spatial snapshot, entity snapshot). Pure and
    deterministic given the reply sequence of the episode: the previous reply's agent and target positions feed the
    displacement / velocity columns, and projectile slots are sticky per spawn serial. Any collision table with at
    most SEGMENT_SLOTS segments is accepted (the pinned-Mario check is a task validation, not a contract term)."""

    def __init__(self, lines: Sequence[ms.SpatialLine], classifier: st.ActionClassifier, *,
                 segment_length_scale: float = LENGTH_SCALE, segment_velocity_scale: float = VELOCITY_SCALE):
        # M7p (opt-in): the segment_geometry block may use its own fixed scale; the defaults reproduce v3 exactly.
        self._seg_length_scale = float(segment_length_scale)
        self._seg_velocity_scale = float(segment_velocity_scale)
        segs = ms.static_segments(lines)
        if not segs:
            raise ObservationV3Error("empty collision table")
        if len(segs) > SEGMENT_SLOTS:
            raise ObservationV3Error(f"{len(segs)} segments exceed the {SEGMENT_SLOTS} slots")
        self.classifier = classifier
        self.segment_count = len(segs)
        self._segs: List[Tuple[int, float, float, float, float, float, float, float]] = []
        for _line, _piece, _typ, grp, _flags, a, b in segs:
            ax, ay, bx, by = (float(np.float32(c)) for c in (a[0], a[1], b[0], b[1]))
            vx, vy = bx - ax, by - ay
            if vx == 0.0 and vy == 0.0:
                raise ObservationV3Error("zero-length collision segment")
            self._segs.append((int(grp), ax, ay, bx, by, vx, vy, vx * vx + vy * vy))
        self._group_rows: Dict[int, List[int]] = {}
        for i, s in enumerate(self._segs):
            self._group_rows.setdefault(s[0], []).append(i)
        self._padding = [0.0] * ((SEGMENT_SLOTS - len(segs)) * len(SEGMENT_GEOMETRY_FIELDS))
        kind = np.zeros(SHAPES[SEGMENT_KIND_KEY], dtype=np.float32)
        for i, (_line, _piece, typ, _group, flags, _a, _b) in enumerate(segs):
            kind[i, 0] = 1.0
            kind[i, _TYPE_COLUMN[typ]] = 1.0
            kind[i, 5] = 1.0 if flags & ms.VERTEX_PASS else 0.0
        self._kind_static = kind
        self.reset_episode()

    def reset_episode(self) -> None:
        self._prev_pos: Optional[Tuple[float, float]] = None
        self._prev_targets: Dict[int, Tuple[float, float]] = {}
        self._slots: Dict[int, int] = {}          # spawn serial -> sticky projectile slot
        self._last_obs: Optional[Dict[str, np.ndarray]] = None
        self.stale_builds = 0
        self.projectile_overflow = 0
        self.classifier.unmapped_seen.clear()

    def build(self, observation: Mapping[str, Any], spatial: ms.SpatialSnapshot, entity: ne.EntitySnapshot
              ) -> Tuple[Dict[str, np.ndarray], bool]:
        """(v3 observation, stale) for one reply. Stale = the reply is a teardown (native live = 0, only the terminal
        reply of a fall) or the fighter is not valid: the last complete observation is repeated."""
        tick = int(observation["input_tick"])
        if spatial.input_tick != tick or entity.input_tick != tick:
            raise ObservationV3Error(f"snapshots {spatial.input_tick} / {entity.input_tick} != observation {tick}")
        if spatial.fighter is None:
            raise ObservationV3Error("spatial snapshot from a lean parse: v3 needs the fighter block")
        if not (spatial.live and entity.live and int(observation.get("fighter_valid", 0)) == 1
                and spatial.fighter.valid and entity.fighter.valid):
            if self._last_obs is None:
                raise ObservationV3Error("no live reply in this episode yet")
            self.stale_builds += 1
            return {k: v.copy() for k, v in self._last_obs.items()}, True
        L, V = LENGTH_SCALE, VELOCITY_SCALE
        px, py = float(observation["position_x"]), float(observation["position_y"])

        # -- agent -------------------------------------------------------------------------------------------
        sf, ef = spatial.fighter, entity.fighter
        if self._prev_pos is None:
            disp = (0.0, 0.0)
        else:
            disp = ((px - self._prev_pos[0]) / V, (py - self._prev_pos[1]) / V)
        jumps_max = int(ef.jumps_max)
        jumps_left = (jumps_max - int(observation["jumps_used"])) / jumps_max if jumps_max > 0 else 0.0
        floor_dist = min(max(float(sf.floor_dist), -FLOOR_DIST_CAP), FLOOR_DIST_CAP) / L
        agent = [
            px / L, py / L, disp[0], disp[1],
            float(observation["air_velocity_x"]) / V, float(observation["air_velocity_y"]) / V,
            float(observation["ground_velocity_x"]) / V, sf.carry[0] / V, sf.carry[1] / V,
            float(int(observation["facing_direction"])), 1.0 if int(observation["ground_air_state"]) == 0 else 0.0,
            *[1.0 if sf.mask_curr & bit else 0.0 for bit in _CONTACT_BITS],
            floor_dist, min(max(jumps_left, 0.0), 1.0),
            int(observation["fighter_status_id"]) / STATUS_ID_SCALE,
            min(int(ef.status_total_tics), STATUS_TICS_CAP) / PROGRESS_SCALE,
            min(int(ef.hitlag_tics), HITLAG_CAP) / PROGRESS_SCALE,
            float(ef.attack_active), float(ef.cliff_hold), float(ef.shield_active), float(ef.fastfall),
            int(observation["time_passed"]) / TIME_SCALE, int(observation["targets_remaining"]) / 10.0,
            sf.coll[0] / L, sf.coll[3] / L,
        ]
        action_class = np.zeros(SHAPES[ACTION_CLASS_KEY], dtype=np.float32)
        action_class[self.classifier.index(int(observation["fighter_status_id"]))] = 1.0

        # -- segments (the v2 geometry, scaled) -------------------------------------------------------------------
        f32 = np.float32
        moving: Dict[int, Tuple[float, float, float, float]] = {}
        kind = self._kind_static.copy()
        for g in spatial.groups:
            if g.present and g.translated and g.id in self._group_rows:
                moving[g.id] = (g.translate[0], g.translate[1], g.speed[0], g.speed[1])
                kind[self._group_rows[g.id], 6] = 1.0
        out: List[float] = []
        SL, SV = self._seg_length_scale, self._seg_velocity_scale   # == L, V unless an opt-in contract set them
        for grp, ax, ay, bx, by, vx, vy, vv in self._segs:
            sx = sy = 0.0
            if grp in moving:
                tx, ty, sx, sy = moving[grp]
                ax = float(f32(ax) + f32(tx))
                ay = float(f32(ay) + f32(ty))
                bx = float(f32(bx) + f32(tx))
                by = float(f32(by) + f32(ty))
                vx, vy = bx - ax, by - ay
                vv = vx * vx + vy * vy
            rax, ray = ax - px, ay - py
            t = -(rax * vx + ray * vy) / vv
            t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
            out += (rax / SL, ray / SL, (bx - px) / SL, (by - py) / SL, (rax + t * vx) / SL, (ray + t * vy) / SL,
                    sx / SV, sy / SV)
        out += self._padding
        seg = np.array(out, dtype=np.float32).reshape(SHAPES[SEGMENT_GEOMETRY_KEY])

        # -- targets -------------------------------------------------------------------------------------------
        tg: List[float] = []
        now_targets: Dict[int, Tuple[float, float]] = {}
        for i in range(TARGET_SLOTS):
            if spatial.target_live_mask >> i & 1:
                x, y = spatial.target_positions[i]
                prev = self._prev_targets.get(i)
                vx_t, vy_t = ((x - prev[0]) / V, (y - prev[1]) / V) if prev is not None else (0.0, 0.0)
                tg += ((x - px) / L, (y - py) / L, vx_t, vy_t, 1.0)
                now_targets[i] = (x, y)
            else:
                tg += (0.0, 0.0, 0.0, 0.0, 0.0)
        targets = np.array(tg, dtype=np.float32).reshape(SHAPES[TARGETS_KEY])

        # -- projectiles (own weapons, sticky slots in spawn-serial order) -------------------------------------
        owned = ne.owned_weapons(entity)
        live_serials = {w.serial for w in owned}
        for serial in [s for s in self._slots if s not in live_serials]:
            del self._slots[serial]
        proj = np.zeros(SHAPES[PROJECTILES_KEY], dtype=np.float32)
        for w in owned:
            slot = self._slots.get(w.serial)
            if slot is None:
                free = [s for s in range(PROJECTILE_SLOTS) if s not in self._slots.values()]
                if not free:
                    self.projectile_overflow += 1
                    continue
                slot = free[0]
                self._slots[w.serial] = slot
            life = min(max(float(w.lifetime), 0.0), PROJECTILE_LIFE_SCALE) / PROJECTILE_LIFE_SCALE
            proj[slot] = np.array([1.0, (w.translate[0] - px) / L, (w.translate[1] - py) / L, w.velocity[0] / V,
                                   w.velocity[1] / V, 1.0 if w.attack_state != 0 else 0.0, life], dtype=np.float32)

        obs = {ACTION_CLASS_KEY: action_class, AGENT_KEY: np.array(agent, dtype=np.float32),
               PROJECTILES_KEY: proj, SEGMENT_GEOMETRY_KEY: seg, SEGMENT_KIND_KEY: kind, TARGETS_KEY: targets}
        self._prev_pos = (px, py)
        self._prev_targets = now_targets
        self._last_obs = obs
        return {k: v.copy() for k, v in obs.items()}, False


def _observation_fields(observation: Any) -> Dict[str, Any]:
    if isinstance(observation, Mapping):
        return dict(observation)
    import dataclasses
    return dataclasses.asdict(observation)


def character_of(experiment: Optional[Mapping[str, Any]]) -> str:
    """The task character of an experiment summary block (task_id ssb64_<version>_<character>_btt_v1); Mario when
    absent (the only bootable task)."""
    task = str((experiment or {}).get("task_id") or "")
    parts = task.split("_")
    if len(parts) >= 4 and parts[0] == "ssb64" and parts[-2] == "btt":
        return "_".join(parts[2:-2])
    return DEFAULT_CHARACTER


class EntityObsV3Wrapper(gym.Wrapper):
    """Directly above Track1PolicyWrapper: v1 vector in (ignored except for the paired native fields), v3 Dict out.
    Reads the native `spatial` and `entity` objects from the raw replies of the episode's own client (an instance
    attribute shadows client.request; no inherited file changes), issues one extra non-consuming `observe` per reset
    and cross-checks it against the reset observation. Fails loudly when either object is missing."""

    contract_id: str = OBS_CONTRACT   # an opt-in subclass (M7p) reports its own contract id in info

    def __init__(self, env: Any, *, base: Any, character: str = DEFAULT_CHARACTER, check_invariants: bool = False,
                 table: Optional[Dict[str, Any]] = None):
        super().__init__(env)
        self.base = base
        self.observation_space = make_observation_space()
        self.check_invariants = check_invariants
        self.table = table if table is not None else st.load_table()
        self.classifier = st.ActionClassifier(self.table, character)
        self.builder: Optional[EntityObservationBuilder] = None
        self._last_reply: Optional[Dict[str, Any]] = None
        self._client: Any = None
        self._last_obs: Optional[Dict[str, np.ndarray]] = None
        self._prev_spatial: Optional[ms.SpatialSnapshot] = None
        self._prev_entity: Optional[ne.EntitySnapshot] = None
        self._prev_observation: Optional[Dict[str, Any]] = None
        self._static_targets: Optional[Dict[int, Tuple[float, float]]] = None
        self.invariant_problems: List[Dict[str, Any]] = []
        self.stale_steps = 0

    def _capture(self, client: Any) -> None:
        if self._client is client:
            return
        original = client.request

        def request(op: str, **payload: Any) -> Dict[str, Any]:
            reply = original(op, **payload)
            self._last_reply = reply
            return reply

        client.request = request
        self._client = client

    def _check(self, sp: ms.SpatialSnapshot, en: ne.EntitySnapshot, observation: Mapping[str, Any], where: str) -> None:
        if self.check_invariants:
            problems = ms.check_snapshot(sp, observation, prev=self._prev_spatial, prev_observation=self._prev_observation,
                                         static_targets=self._static_targets)
            problems += ne.check_snapshot(en, observation, prev=self._prev_entity, prev_observation=self._prev_observation)
            if problems:
                self.invariant_problems.append({"where": where, "input_tick": sp.input_tick, "problems": problems})
        self._prev_spatial, self._prev_entity, self._prev_observation = sp, en, dict(observation)

    def _make_builder(self, lines: Sequence[ms.SpatialLine]) -> EntityObservationBuilder:
        """The episode's builder (v3 scaling); an opt-in subclass may return a differently scaled builder."""
        return EntityObservationBuilder(lines, self.classifier)

    def _info(self, info: Dict[str, Any], stale: bool) -> Dict[str, Any]:
        info["policy_observation_contract"] = self.contract_id
        info["v3_stale"] = stale
        info["v3_unmapped_status_ids"] = dict(self.classifier.unmapped_seen)
        info["v3_projectile_overflow"] = self.builder.projectile_overflow if self.builder else 0
        return info

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        _state, info = self.env.reset(seed=seed, options=options)
        episode = self.base.episode
        if episode is None or episode.client is None:
            raise ObservationV3Error("no active episode after reset")
        self._capture(episode.client)
        reply = episode.client.request("observe")        # non-consuming: no tick, no clock
        reset_obs = _observation_fields(self.base.last_observe.observation)
        if reply.get("ok") is not True or reply.get("observation") != reset_obs:
            raise ObservationV3Error("the v3 re-observe does not match the reset observation "
                                     f"({reply.get('observation')} vs {reset_obs})")
        sp = ms.spatial_of(reply, expect_lines=True)
        en = ne.entity_of(reply)
        self.builder = self._make_builder(sp.lines or ())
        self._prev_spatial = self._prev_entity = self._prev_observation = None
        self._static_targets = {i: sp.target_positions[i] for i in range(ms.TARGET_COUNT)
                                if i != ms.MOVING_TARGET_ID and sp.target_live_mask & (1 << i)}
        self._check(sp, en, reply["observation"], "reset")
        obs, stale = self.builder.build(reply["observation"], sp, en)
        self._last_obs = obs
        self.stale_steps = 0
        return obs, self._info(info, stale)

    def step(self, action: Any):
        self._last_reply = None
        _state, reward, terminated, truncated, info = self.env.step(action)
        if info.get("truncation_reason") == "episode_failure":
            # Track1PolicyWrapper's EpisodeFailure path: nothing was consumed; repeat the cached observation.
            return self._last_obs, reward, terminated, truncated, self._info(info, True)
        reply = self._last_reply
        result = self.base.last_step_result
        if reply is None or reply.get("op") != "step" or result is None or reply.get("step_count") != result.step_count:
            raise ObservationV3Error("no raw step reply paired with the collected step result")
        sp = ms.spatial_of(reply, expect_lines=False)
        en = ne.entity_of(reply)
        self._check(sp, en, reply["observation"], f"step {result.step_count}")
        assert self.builder is not None
        obs, stale = self.builder.build(reply["observation"], sp, en)
        if stale:
            self.stale_steps += 1
        self._last_obs = obs
        return obs, reward, terminated, truncated, self._info(info, stale)


# -- contract, stacks ----------------------------------------------------------------------------------------


def contract_description() -> Dict[str, Any]:
    """The machine-readable v3 contract (also written to docs/rl_observation_v3_m7n.schema.json)."""
    table = st.load_table()
    return {
        "contract": OBS_CONTRACT,
        "schema_version": OBS_SCHEMA_VERSION,
        "space": "gymnasium.spaces.Dict",
        "key_order": list(KEY_ORDER),
        "keys": {
            ACTION_CLASS_KEY: {"shape": list(SHAPES[ACTION_CLASS_KEY]), "dtype": "float32", "bounds": [0.0, 1.0],
                               "fields": list(st.CLASSES), "values": "one-hot", "table": table["table_id"],
                               "table_sha256": table["sha256"], "unmapped_class": st.UNMAPPED},
            AGENT_KEY: {"shape": list(SHAPES[AGENT_KEY]), "dtype": "float32", "bounds": ["-inf", "inf"],
                        "fields": list(AGENT_FIELDS),
                        "units": {"pos_*, floor_dist, diamond_*": f"native units / {LENGTH_SCALE:g}",
                                  "disp_*, *_vel_*, carry_*": f"native units per tick / {VELOCITY_SCALE:g}",
                                  "facing": "-1, 0, 1", "grounded, contact_*, attack_active, cliff_hold, "
                                  "shield_active, fastfall": "0 / 1", "jumps_left": "(jumps_max - jumps_used) / jumps_max",
                                  "status_id": f"raw id / {STATUS_ID_SCALE:g}",
                                  "status_tics": f"min(status_total_tics, {STATUS_TICS_CAP}) / {PROGRESS_SCALE:g}",
                                  "hitlag": f"min(hitlag_tics, {HITLAG_CAP}) / {PROGRESS_SCALE:g}",
                                  "time": f"time_passed / {TIME_SCALE:g}", "targets_left": "targets_remaining / 10"}},
            PROJECTILES_KEY: {"shape": list(SHAPES[PROJECTILES_KEY]), "dtype": "float32", "bounds": ["-inf", "inf"],
                              "fields": list(PROJECTILE_FIELDS), "rows": "sticky slots; a weapon keeps its slot for its "
                              "life; a new spawn takes the lowest free slot in ascending spawn serial; with no free slot "
                              "it is dropped and counted (info v3_projectile_overflow)", "ownership": "the agent's own "
                              "weapons only (owner == the player fighter)", "velocity": "native WPStruct vel_air (no "
                              "estimate): unaffected by creation / destruction", "life": f"min(lifetime, {PROJECTILE_LIFE_SCALE:g}) / "
                              f"{PROJECTILE_LIFE_SCALE:g}", "mask_column": MASK_COLUMNS[PROJECTILES_KEY]},
            SEGMENT_GEOMETRY_KEY: {"shape": list(SHAPES[SEGMENT_GEOMETRY_KEY]), "dtype": "float32",
                                   "bounds": ["-inf", "inf"], "fields": list(SEGMENT_GEOMETRY_FIELDS),
                                   "units": f"native units (TopN-relative) / {LENGTH_SCALE:g}; velocity / {VELOCITY_SCALE:g}"},
            SEGMENT_KIND_KEY: {"shape": list(SHAPES[SEGMENT_KIND_KEY]), "dtype": "float32", "bounds": [0.0, 1.0],
                               "fields": list(SEGMENT_KIND_FIELDS), "values": "binary 0/1",
                               "mask_column": MASK_COLUMNS[SEGMENT_KIND_KEY]},
            TARGETS_KEY: {"shape": list(SHAPES[TARGETS_KEY]), "dtype": "float32", "bounds": ["-inf", "inf"],
                          "fields": list(TARGET_FIELDS), "rows": "M7f stable target IDs 0..9",
                          "units": f"dx, dy: native units / {LENGTH_SCALE:g}; vx, vy: (position - previous reply's "
                          f"position) / {VELOCITY_SCALE:g}, 0 at reset, on a row's first live reply and on a stale reply",
                          "mask_column": MASK_COLUMNS[TARGETS_KEY]},
        },
        "flat_size": FLAT_SIZE,
        "scaling": {"length": LENGTH_SCALE, "velocity": VELOCITY_SCALE, "time": TIME_SCALE, "progress": PROGRESS_SCALE,
                    "running_normalization": False, "clipping": None},
        "masks": {"rule": "a row whose validity column is 0 is all zeros at the network input (no normalisation can "
                          "move it)", "columns": dict(MASK_COLUMNS)},
        "segments": {"slots": SEGMENT_SLOTS, "order": "native collision line id, then vertex-pair index",
                     "padding": "slots >= count: every geometry and kind value 0", "accepts": "any table with <= 32 "
                     "segments (the pinned Mario table is a task validation, not a contract term)",
                     "mario_reference": "TopN (position_x, position_y) of the paired observation",
                     "world_vertex_rule": "float32 stored vertex + float32 group translate when the group is "
                                          "translated (mpCollisionGetVertexPositionID)"},
        "stale_rule": "native live = 0 or fighter invalid (the terminal reply of a fall): the last complete "
                      "observation is repeated and info['v3_stale'] is true",
        "displacement_rule": "agent disp_* = TopN change since the previous reply / velocity scale; 0 at reset",
        "character": {"default": DEFAULT_CHARACTER, "validated_tables": list(st.VALIDATED),
                      "rule": "status ids are looked up in the task character's own table; ids outside it map to "
                              f"{st.UNMAPPED!r} and are counted (info v3_unmapped_status_ids)"},
        "native_sources": {"observation": "btt_m1b schema 1", "spatial": {"diagnostic": ms.CONTRACT, "env": f"{ms.SPATIAL_ENV}=1"},
                           "entity": {"diagnostic": ne.CONTRACT, "env": f"{ne.ENTITY_ENV}=1"}},
        "information_class": "structured global state (more than one camera frame shows)",
        "excluded": list(FORBIDDEN_CONTENT),
        "compatibility": "fresh models only; a btt_policy_obs_v1 or btt_policy_obs_v2_spatial checkpoint is refused; "
                         "v1 and v2 stay available and byte-identical",
    }


def contract_digest() -> str:
    return hashlib.sha256(json.dumps(contract_description(), sort_keys=True).encode("utf-8")).hexdigest()


def m7n_contracts(horizon: int, reward: Any, character: str = DEFAULT_CHARACTER) -> Dict[str, Any]:
    """m7_contracts with the v3 observation (every other contract unchanged)."""
    from btt_parallel import m7_contracts

    table = st.load_table()
    c = dict(m7_contracts(horizon, reward))
    c.update({"policy_observation_contract": OBS_CONTRACT,
              "policy_observation_keys": list(KEY_ORDER),
              "policy_observation_shapes": {k: list(v) for k, v in SHAPES.items()},
              "policy_observation_contract_sha256": contract_digest(),
              "action_class_table": table["table_id"], "action_class_table_sha256": table["sha256"],
              "action_class_character": character,
              "spatial_diagnostic_contract": ms.CONTRACT, "entity_diagnostic_contract": ne.CONTRACT})
    return c


def _tracker_class(character: str, contracts_fn: Any = None) -> Any:
    import btt_parallel as bp

    contracts = contracts_fn or m7n_contracts   # M7p: an opt-in contract records its own contract block

    class M7nEpisodeTracker(bp.M7EpisodeTracker):
        """M7EpisodeTracker whose artifact labels record the v3 observation contract (nothing else changes)."""

        def labels_for_new_episode(self) -> Dict[str, Any]:
            labels = super().labels_for_new_episode()
            labels["contracts"] = contracts(self.env.max_episode_steps or 0, self.reward, character)
            return labels

    return M7nEpisodeTracker


def build_worker_env_v3(spec: Any, *, wrapper_cls: Any = None, contracts_fn: Any = None) -> Any:
    """The M7 worker stack of btt_parallel.build_worker_env with EntityObsV3Wrapper directly above Track1PolicyWrapper
    (every other layer, argument and order identical to the v2 stack of rl/m7g_obs.py). The spec's extra_env must
    contain SSB64_RL_SPATIAL=1 and SSB64_RL_ENTITY=1, so every standby generation boots with both diagnostics.

    M7BattleShipBTTEnv -> M7RewardWrapper -> EpisodeRecordingWrapper -> Track1PolicyWrapper -> EntityObsV3Wrapper
    -> EpisodeStatsWrapper -> M7WorkerWrapper"""
    import random

    import btt_parallel as bp

    missing = [f"{k}={v}" for k, v in ENTITY_EXTRA_ENV if dict(spec.extra_env).get(k) != v]
    if missing:
        raise ValueError(f"v3 worker spec needs {missing} in extra_env")
    random.seed(spec.worker_seed)            # Python-side reproducibility only; never reaches the game
    np.random.seed(spec.worker_seed % (2 ** 32))
    character = character_of(spec.experiment)
    paths = spec.paths()
    if not (paths["runtime"] / "runtime_manifest.json").is_file():
        raise RuntimeError(f"worker runtime directory not prepared: {paths['runtime']}")
    for key in ("episodes", "artifacts"):
        paths[key].mkdir(parents=True, exist_ok=True)
    launch = bp.LaunchConfig(
        executable=bp.Path(spec.executable), working_dir=paths["runtime"], run_root=paths["episodes"],
        startup_timeout=spec.startup_timeout, ready_timeout=spec.ready_timeout, request_timeout=spec.request_timeout,
        exit_timeout=spec.exit_timeout, extra_env=dict(spec.extra_env))
    ports = bp.PortCandidates(spec.rank, spec.port_block_base, spec.port_block_size)
    base = bp.M7BattleShipBTTEnv(launch, max_episode_steps=spec.horizon, rank=spec.rank, ports=ports,
                                 startup_attempts=spec.startup_attempts,
                                 detect_native_failure=spec.detect_native_failure,
                                 standby=spec.standby, generation_runtime_root=paths["runtime_gens"],
                                 profile=spec.profile(), standby_fault=spec.standby_fault,
                                 retain_failed_cap=spec.retain_failed_cap)
    tracker = _tracker_class(character, contracts_fn)(run_id=spec.run_id, role=spec.role, rank=spec.rank,
                                        coordinator=bp.RunCoordinator(spec.coordination_dir),
                                        artifact_root=paths["artifacts"], ledger_path=paths["ledger"], env=base,
                                        reward=spec.reward_contract, retain_failed_cap=spec.retain_failed_cap,
                                        preserve_all=spec.preserve_all, experiment=spec.experiment)
    rewarded = bp.make_reward_wrapper(base, spec, tracker)   # M7o: dispatches the opt-in exploration wrapper; v2 unchanged
    recording = bp.EpisodeRecordingWrapper(rewarded, paths["artifacts"],
                                           detectors=[bp.PositionDeltaDetector(spec.position_delta_threshold)],
                                           labels=tracker.labels_for_new_episode,
                                           on_episode_end=tracker.on_episode_end, targets_total=bp.TARGETS_TOTAL)
    track1 = bp.Track1PolicyWrapper(recording)
    v3 = (wrapper_cls or EntityObsV3Wrapper)(track1, base=base, character=character)
    stats = bp.EpisodeStatsWrapper(v3)
    return bp.M7WorkerWrapper(stats, spec=spec, base=base, tracker=tracker, recording=recording)


class M7nWorkerFactory:
    """Top-level, picklable factory (spawn-safe) for the v3 worker stack."""

    def __init__(self, spec: Any):
        self.spec = spec

    def __call__(self) -> Any:
        return build_worker_env_v3(self.spec)


if __name__ == "__main__":
    import sys
    from pathlib import Path

    if len(sys.argv) > 1 and sys.argv[1] == "schema":
        out = Path(__file__).resolve().parent.parent / "docs" / "rl_observation_v3_m7n.schema.json"
        out.write_text(json.dumps({"contract": contract_description(), "contract_sha256": contract_digest()}, indent=1)
                       + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {out} digest {contract_digest()[:16]} flat {FLAT_SIZE}")
    else:
        print(json.dumps({"contract": OBS_CONTRACT, "flat_size": FLAT_SIZE, "digest": contract_digest()}, indent=1))
