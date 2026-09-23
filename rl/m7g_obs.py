"""M7g-b: policy observation `btt_policy_obs_v2_spatial` (structured segment/object representation).

A separately versioned policy observation for Track 1. `btt_policy_obs_v1` (rl/btt_learning.py) is untouched and
stays the frozen 15-value float32 adapter; v2 is a Gymnasium Dict whose `state` key IS that v1 vector (the very array
Track1PolicyWrapper returns, byte for byte) plus a structured description of the world built from the native
`btt_spatial_v1` diagnostic (rl/m7g_spatial.py, SSB64_RL_SPATIAL=1):

  segment_geometry  float32 (32, 8)  per collision segment, relative to Mario's TopN (position_x, position_y):
                                     first vertex dx, dy; second vertex dx, dy; closest point on the segment dx, dy;
                                     segment velocity x, y (the moving platform's last-update speed; 0 when static)
  segment_kind      float32 (32, 7)  binary: present, floor, ceiling, wall facing +x (solid on -x), wall facing -x
                                     (solid on +x), one-way (pass-through), moving
  state             float32 (15,)    btt_policy_obs_v1, unchanged
  target_geometry   float32 (10, 2)  per stable target ID (M7f), live target centre relative to Mario; 0 when broken
  target_live       float32 (10,)    binary: target i unbroken

Segments are the consecutive vertex pairs of the native collision lines in line-id order (Mario's stage: 20 lines ->
24 segments; slots 24..31 are padding with every value 0). The world state is described, never a route: no path,
preferred crossing, target order, gateway label, route distance, future platform position or reward term.

It is structured GLOBAL state: every segment and every live target is present whatever the camera shows (one camera
frame covers roughly 65 % of the stage height and never both ends, docs/rl_observation_v2_m7g.md section 2).

Normalisation: VecNormalize observation statistics for the continuous keys only (NORMALIZED_KEYS); the binary keys
are passed through. Reward normalisation stays off. v2 needs fresh models: a v1 checkpoint cannot load into v2.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import gymnasium as gym
import numpy as np
from gymnasium import spaces

import m7g_spatial as ms
from btt_learning import POLICY_FIELDS, POLICY_OBSERVATION_CONTRACT, POLICY_OBSERVATION_SIZE

OBS_CONTRACT = "btt_policy_obs_v2_spatial"
OBS_SCHEMA_VERSION = 1

STATE_KEY = "state"
SEGMENT_GEOMETRY_KEY = "segment_geometry"
SEGMENT_KIND_KEY = "segment_kind"
TARGET_GEOMETRY_KEY = "target_geometry"
TARGET_LIVE_KEY = "target_live"
# gymnasium sorts the keys of a plain-dict Dict space; SB3's CombinedExtractor concatenates in this order.
KEY_ORDER = (SEGMENT_GEOMETRY_KEY, SEGMENT_KIND_KEY, STATE_KEY, TARGET_GEOMETRY_KEY, TARGET_LIVE_KEY)
NORMALIZED_KEYS = (SEGMENT_GEOMETRY_KEY, STATE_KEY, TARGET_GEOMETRY_KEY)   # VecNormalize norm_obs_keys
BINARY_KEYS = (SEGMENT_KIND_KEY, TARGET_LIVE_KEY)                          # never normalised

SEGMENT_SLOTS = 32
SEGMENT_GEOMETRY_FIELDS = ("a_dx", "a_dy", "b_dx", "b_dy", "near_dx", "near_dy", "vel_x", "vel_y")
SEGMENT_KIND_FIELDS = ("present", "floor", "ceiling", "wall_facing_pos_x", "wall_facing_neg_x", "one_way", "moving")
TARGET_SLOTS = ms.TARGET_COUNT
TARGET_GEOMETRY_FIELDS = ("dx", "dy")
MARIO_REFERENCE = ("position_x", "position_y")   # TopN, the v1 position fields

SHAPES: Dict[str, Tuple[int, ...]] = {
    SEGMENT_GEOMETRY_KEY: (SEGMENT_SLOTS, len(SEGMENT_GEOMETRY_FIELDS)),
    SEGMENT_KIND_KEY: (SEGMENT_SLOTS, len(SEGMENT_KIND_FIELDS)),
    STATE_KEY: (POLICY_OBSERVATION_SIZE,),
    TARGET_GEOMETRY_KEY: (TARGET_SLOTS, len(TARGET_GEOMETRY_FIELDS)),
    TARGET_LIVE_KEY: (TARGET_SLOTS,),
}
FLAT_SIZE = int(sum(int(np.prod(s)) for s in SHAPES.values()))   # 525

# The native line types, in segment_kind column order 1..4.
_TYPE_COLUMN = {ms.LINE_FLOOR: 1, ms.LINE_CEIL: 2, ms.LINE_RWALL: 3, ms.LINE_LWALL: 4}

FORBIDDEN_CONTENT = ("optimal path", "preferred crossing", "target order", "TAS action", "'go left' indicator",
                     "gateway / region labels", "distance along a handcrafted route", "future platform positions",
                     "future game state", "reward shaping")


class ObservationV2Error(RuntimeError):
    """The v2 observation cannot be built (missing / inconsistent native spatial data)."""


def make_observation_space() -> spaces.Dict:
    inf = np.inf
    return spaces.Dict({
        SEGMENT_GEOMETRY_KEY: spaces.Box(-inf, inf, SHAPES[SEGMENT_GEOMETRY_KEY], np.float32),
        SEGMENT_KIND_KEY: spaces.Box(0.0, 1.0, SHAPES[SEGMENT_KIND_KEY], np.float32),
        STATE_KEY: spaces.Box(-inf, inf, SHAPES[STATE_KEY], np.float32),
        TARGET_GEOMETRY_KEY: spaces.Box(-inf, inf, SHAPES[TARGET_GEOMETRY_KEY], np.float32),
        TARGET_LIVE_KEY: spaces.Box(0.0, 1.0, SHAPES[TARGET_LIVE_KEY], np.float32),
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
    """The 525-float vector SB3's CombinedExtractor sees (keys in KEY_ORDER, each flattened C-order)."""
    return np.concatenate([np.asarray(obs[k], dtype=np.float32).reshape(-1) for k in KEY_ORDER])


class SpatialObservationBuilder:
    """Builds v2 observations for one episode. Constructed from the reset observe's line table, which must equal the
    pinned stage table (the contract is specific to Mario's Break the Targets). Pure and deterministic: the output
    depends only on (v1 state, paired observation, spatial snapshot) plus, on a teardown reply (live = 0, only the
    terminal reply of a fall), the last live dynamic snapshot, which is then held."""

    def __init__(self, lines: Sequence[ms.SpatialLine]):
        problems = ms.expected_table_problems(lines)
        if problems:
            raise ObservationV2Error(f"native collision table differs from the {OBS_CONTRACT} stage table: {problems}")
        segs = ms.static_segments(lines)
        if len(segs) > SEGMENT_SLOTS:
            raise ObservationV2Error(f"{len(segs)} segments exceed the {SEGMENT_SLOTS} slots")
        n = len(segs)
        self.segment_count = n
        self.segment_index = tuple((line, piece) for line, piece, *_ in segs)
        # Per segment (as stored, float32-exact values as Python floats): group, a, b, direction b - a, |b - a|^2.
        # Untranslated rows never change, so their direction and squared length are precomputed; a translated group's
        # rows are recomputed from the float32 world vertices each reply.
        self._segs: List[Tuple[int, float, float, float, float, float, float, float]] = []
        for _line, _piece, _typ, grp, _flags, a, b in segs:
            ax, ay, bx, by = (float(np.float32(c)) for c in (a[0], a[1], b[0], b[1]))
            vx, vy = bx - ax, by - ay
            if vx == 0.0 and vy == 0.0:
                raise ObservationV2Error("zero-length collision segment")
            self._segs.append((int(grp), ax, ay, bx, by, vx, vy, vx * vx + vy * vy))
        self._group_rows: Dict[int, List[int]] = {}
        for i, s in enumerate(self._segs):
            self._group_rows.setdefault(s[0], []).append(i)
        self._padding = [0.0] * ((SEGMENT_SLOTS - n) * len(SEGMENT_GEOMETRY_FIELDS))
        kind = np.zeros(SHAPES[SEGMENT_KIND_KEY], dtype=np.float32)
        for i, (_line, _piece, typ, _group, flags, _a, _b) in enumerate(segs):
            kind[i, 0] = 1.0
            kind[i, _TYPE_COLUMN[typ]] = 1.0
            kind[i, 5] = 1.0 if flags & ms.VERTEX_PASS else 0.0
        self._kind_static = kind
        self._last_dynamic: Optional[Tuple[Tuple[ms.SpatialGroup, ...], int, Tuple[Tuple[float, float], ...]]] = None
        self.stale_builds = 0

    def build(self, state: np.ndarray, observation: Mapping[str, Any],
              snap: ms.SpatialSnapshot) -> Tuple[Dict[str, np.ndarray], bool]:
        """(v2 observation, stale) for one reply. `state` is the v1 vector of the same reply (kept as is)."""
        state = np.asarray(state)
        if state.dtype != np.float32 or state.shape != SHAPES[STATE_KEY]:
            raise ObservationV2Error(f"state must be the float32 (15,) v1 vector, got {state.dtype} {state.shape}")
        if snap.input_tick != int(observation["input_tick"]):
            raise ObservationV2Error(f"spatial input_tick {snap.input_tick} != observation {observation['input_tick']}")
        if snap.live:
            dyn = (snap.groups, snap.target_live_mask, snap.target_positions)
            self._last_dynamic = dyn
            stale = False
        else:
            if self._last_dynamic is None:
                raise ObservationV2Error("no live spatial snapshot in this episode yet")
            dyn = self._last_dynamic
            stale = True
            self.stale_builds += 1
        groups, live_mask, positions = dyn
        px, py = float(observation[MARIO_REFERENCE[0]]), float(observation[MARIO_REFERENCE[1]])

        # Translated groups: world vertex = float32 stored vertex + float32 group translate, exactly as the game forms
        # it (mpCollisionGetVertexPositionID); every other group is stored in world coordinates.
        f32 = np.float32
        moving: Dict[int, Tuple[float, float, float, float]] = {}
        kind = self._kind_static.copy()
        for g in groups:
            if g.present and g.translated and g.id in self._group_rows:
                moving[g.id] = (g.translate[0], g.translate[1], g.speed[0], g.speed[1])
                kind[self._group_rows[g.id], 6] = 1.0
        # Relative geometry in float64 (Python floats), cast once to float32: a - p, b - p and the closest point
        # (a - p) + clamp(-((a - p) . (b - a)) / |b - a|^2, 0, 1) * (b - a); the segment velocity.
        out: List[float] = []
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
            out += (rax, ray, bx - px, by - py, rax + t * vx, ray + t * vy, sx, sy)
        out += self._padding
        seg = np.array(out, dtype=np.float32).reshape(SHAPES[SEGMENT_GEOMETRY_KEY])

        tg: List[float] = []
        lv: List[float] = []
        for i in range(TARGET_SLOTS):
            if live_mask >> i & 1:
                x, y = positions[i]
                tg += (x - px, y - py)
                lv.append(1.0)
            else:
                tg += (0.0, 0.0)
                lv.append(0.0)
        tgeo = np.array(tg, dtype=np.float32).reshape(SHAPES[TARGET_GEOMETRY_KEY])
        live = np.array(lv, dtype=np.float32)
        obs = {SEGMENT_GEOMETRY_KEY: seg, SEGMENT_KIND_KEY: kind, STATE_KEY: state.copy(),
               TARGET_GEOMETRY_KEY: tgeo, TARGET_LIVE_KEY: live}
        return obs, stale


def _observation_fields(observation: Any) -> Dict[str, Any]:
    """Observation dataclass or dict -> plain dict of the 17 native fields."""
    if isinstance(observation, Mapping):
        return dict(observation)
    import dataclasses
    return dataclasses.asdict(observation)


class SpatialObsV2Wrapper(gym.Wrapper):
    """Directly above Track1PolicyWrapper: v1 vector in, v2 Dict out. Reads the native `spatial` objects from the raw
    replies of the episode's own client (an instance attribute shadows client.request; no inherited file changes),
    issues one extra non-consuming `observe` per reset (the reset observe happens below this layer, before any
    shadow can exist) and cross-checks it against the reset observation. Fails loudly when the spatial object is
    missing (e.g. a process booted without SSB64_RL_SPATIAL=1, which standby readiness does not check)."""

    def __init__(self, env: Any, *, base: Any, check_invariants: bool = False):
        super().__init__(env)
        self.base = base
        self.observation_space = make_observation_space()
        self.check_invariants = check_invariants
        self.builder: Optional[SpatialObservationBuilder] = None
        self._last_reply: Optional[Dict[str, Any]] = None
        self._client: Any = None
        self._last_obs: Optional[Dict[str, np.ndarray]] = None
        self._prev_snap: Optional[ms.SpatialSnapshot] = None
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

    def _check(self, snap: ms.SpatialSnapshot, observation: Mapping[str, Any], where: str) -> None:
        if not self.check_invariants:
            return
        problems = ms.check_snapshot(snap, observation, prev=self._prev_snap, prev_observation=self._prev_observation,
                                     static_targets=self._static_targets)
        if problems:
            self.invariant_problems.append({"where": where, "input_tick": snap.input_tick, "problems": problems})
        self._prev_snap = snap
        self._prev_observation = dict(observation)

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        state, info = self.env.reset(seed=seed, options=options)
        episode = self.base.episode
        if episode is None or episode.client is None:
            raise ObservationV2Error("no active episode after reset")
        self._capture(episode.client)
        reply = episode.client.request("observe")        # non-consuming: no tick, no clock
        reset_obs = _observation_fields(self.base.last_observe.observation)
        if reply.get("ok") is not True or reply.get("observation") != reset_obs:
            raise ObservationV2Error("the v2 re-observe does not match the reset observation "
                                     f"({reply.get('observation')} vs {reset_obs})")
        snap = ms.spatial_of(reply, expect_lines=True)
        self.builder = SpatialObservationBuilder(snap.lines or ())
        self._prev_snap = None
        self._prev_observation = None
        self._static_targets = {i: snap.target_positions[i] for i in range(ms.TARGET_COUNT)
                                if i != ms.MOVING_TARGET_ID and snap.target_live_mask & (1 << i)}
        self._check(snap, reply["observation"], "reset")
        obs, _stale = self.builder.build(state, reply["observation"], snap)
        self._last_obs = obs
        self.stale_steps = 0
        info["policy_observation_contract"] = OBS_CONTRACT
        info["policy_observation_state_contract"] = POLICY_OBSERVATION_CONTRACT
        info["spatial_stale"] = False
        return obs, info

    def step(self, action: Any):
        self._last_reply = None
        state, reward, terminated, truncated, info = self.env.step(action)
        if info.get("truncation_reason") == "episode_failure":
            # Track1PolicyWrapper's EpisodeFailure path: nothing was consumed; repeat the cached observation.
            info["policy_observation_contract"] = OBS_CONTRACT
            return self._last_obs, reward, terminated, truncated, info
        reply = self._last_reply
        result = self.base.last_step_result
        if reply is None or reply.get("op") != "step" or result is None or reply.get("step_count") != result.step_count:
            raise ObservationV2Error("no raw step reply paired with the collected step result")
        snap = ms.spatial_of(reply, expect_lines=False, lean=not self.check_invariants)
        self._check(snap, reply["observation"], f"step {result.step_count}")
        assert self.builder is not None
        obs, stale = self.builder.build(state, reply["observation"], snap)
        if stale:
            self.stale_steps += 1
        self._last_obs = obs
        info["policy_observation_contract"] = OBS_CONTRACT
        info["spatial_stale"] = stale
        return obs, reward, terminated, truncated, info


# -- stacks ----------------------------------------------------------------------------------------------------

SPATIAL_EXTRA_ENV: Tuple[Tuple[str, str], ...] = ((ms.SPATIAL_ENV, "1"),)


def contract_description() -> Dict[str, Any]:
    """The machine-readable v2 contract (also written to docs/rl_observation_v2_m7g.schema.json)."""
    return {
        "contract": OBS_CONTRACT,
        "schema_version": OBS_SCHEMA_VERSION,
        "space": "gymnasium.spaces.Dict",
        "key_order": list(KEY_ORDER),
        "keys": {
            SEGMENT_GEOMETRY_KEY: {"shape": list(SHAPES[SEGMENT_GEOMETRY_KEY]), "dtype": "float32",
                                   "bounds": ["-inf", "inf"], "fields": list(SEGMENT_GEOMETRY_FIELDS),
                                   "units": "native world units (TopN-relative); velocity in world units per tick",
                                   "normalized": True},
            SEGMENT_KIND_KEY: {"shape": list(SHAPES[SEGMENT_KIND_KEY]), "dtype": "float32", "bounds": [0.0, 1.0],
                               "fields": list(SEGMENT_KIND_FIELDS), "values": "binary 0/1", "normalized": False},
            STATE_KEY: {"shape": [POLICY_OBSERVATION_SIZE], "dtype": "float32", "bounds": ["-inf", "inf"],
                        "fields": list(POLICY_FIELDS), "contract": POLICY_OBSERVATION_CONTRACT,
                        "byte_identical_to_v1": True, "normalized": True},
            TARGET_GEOMETRY_KEY: {"shape": list(SHAPES[TARGET_GEOMETRY_KEY]), "dtype": "float32",
                                  "bounds": ["-inf", "inf"], "fields": list(TARGET_GEOMETRY_FIELDS),
                                  "units": "native world units (TopN-relative)", "rows": "M7f stable target IDs 0..9",
                                  "normalized": True},
            TARGET_LIVE_KEY: {"shape": [TARGET_SLOTS], "dtype": "float32", "bounds": [0.0, 1.0],
                              "values": "binary 0/1", "rows": "M7f stable target IDs 0..9", "normalized": False},
        },
        "flat_size": FLAT_SIZE,
        "segments": {"slots": SEGMENT_SLOTS, "order": "native collision line id, then vertex-pair index",
                     "count_on_stage": 24, "padding": "slots >= count: every geometry and kind value 0",
                     "mario_reference": "TopN (position_x, position_y) of the paired v1 observation",
                     "world_vertex_rule": "float32 stored vertex + float32 group translate when the group is "
                                          "translated (mpCollisionGetVertexPositionID)",
                     "relative_geometry": "float64 then one cast to float32: a - p, b - p, (a - p) + clamp(((p - a) . "
                                          "(b - a)) / |b - a|^2, 0, 1) * (b - a), with p the Mario reference"},
        "inactive_encoding": {"broken_target": "target_geometry row 0, target_live 0",
                              "teardown_reply": "native live = 0 (only the terminal reply of a fall): the last live "
                                                "platform / target state is held and info['spatial_stale'] is true"},
        "normalization": {"vecnormalize_norm_obs_keys": list(NORMALIZED_KEYS), "unnormalized_binary_keys":
                          list(BINARY_KEYS), "clip_obs": 10.0, "reward_normalization": False},
        "world": {"coordinates": "native world units, x right, y up", "map_bounds_blast_zone": list(ms.MAP_BOUNDS),
                  "camera_bounds": list(ms.CAMERA_BOUNDS), "static_extent": {"x": [-3900, 3300], "y": [-4050, 3000]},
                  "platform_surface_y": [1800, 3600], "normalization": "no fixed scaling; VecNormalize running "
                                                                          "statistics on the continuous keys"},
        "native_source": {"diagnostic": ms.CONTRACT, "env": f"{ms.SPATIAL_ENV}=1", "status_key": ms.STATUS_KEY},
        "information_class": "structured global state (more than one camera frame shows)",
        "excluded": list(FORBIDDEN_CONTENT),
        "compatibility": "fresh models only; never load a btt_policy_obs_v1 checkpoint; v1 stays available and "
                         "byte-identical",
    }


def contract_digest() -> str:
    return hashlib.sha256(json.dumps(contract_description(), sort_keys=True).encode("utf-8")).hexdigest()


def m7g_contracts(horizon: int, reward: Any) -> Dict[str, Any]:
    """m7_contracts with the v2 observation (every other contract unchanged)."""
    from btt_parallel import m7_contracts

    c = dict(m7_contracts(horizon, reward))
    c.update({"policy_observation_contract": OBS_CONTRACT,
              "policy_observation_state_contract": POLICY_OBSERVATION_CONTRACT,
              "policy_observation_keys": list(KEY_ORDER),
              "policy_observation_shapes": {k: list(v) for k, v in SHAPES.items()},
              "policy_observation_contract_sha256": contract_digest(),
              "spatial_diagnostic_contract": ms.CONTRACT})
    return c


def _tracker_class() -> Any:
    import btt_parallel as bp

    class M7gEpisodeTracker(bp.M7EpisodeTracker):
        """M7EpisodeTracker whose artifact labels record the v2 observation contract (nothing else changes)."""

        def labels_for_new_episode(self) -> Dict[str, Any]:
            labels = super().labels_for_new_episode()
            labels["contracts"] = m7g_contracts(self.env.max_episode_steps or 0, self.reward)
            return labels

    return M7gEpisodeTracker


def build_worker_env_v2(spec: Any) -> Any:
    """The M7 worker stack of btt_parallel.build_worker_env with SpatialObsV2Wrapper directly above
    Track1PolicyWrapper (every other layer, argument and order identical). The spec's extra_env must contain
    SSB64_RL_SPATIAL=1, so every standby generation boots with the diagnostic too.

    M7BattleShipBTTEnv -> M7RewardWrapper -> EpisodeRecordingWrapper -> Track1PolicyWrapper -> SpatialObsV2Wrapper
    -> EpisodeStatsWrapper -> M7WorkerWrapper"""
    import random

    import btt_parallel as bp

    if dict(spec.extra_env).get(ms.SPATIAL_ENV) != "1":
        raise ValueError(f"v2 worker spec needs {ms.SPATIAL_ENV}=1 in extra_env")
    random.seed(spec.worker_seed)            # Python-side reproducibility only; never reaches the game
    np.random.seed(spec.worker_seed % (2 ** 32))
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
    tracker = _tracker_class()(run_id=spec.run_id, role=spec.role, rank=spec.rank,
                               coordinator=bp.RunCoordinator(spec.coordination_dir), artifact_root=paths["artifacts"],
                               ledger_path=paths["ledger"], env=base, reward=spec.reward_contract,
                               retain_failed_cap=spec.retain_failed_cap, preserve_all=spec.preserve_all,
                               experiment=spec.experiment)
    rewarded = bp.M7RewardWrapper(base, spec.reward_contract, tracker)
    recording = bp.EpisodeRecordingWrapper(rewarded, paths["artifacts"],
                                           detectors=[bp.PositionDeltaDetector(spec.position_delta_threshold)],
                                           labels=tracker.labels_for_new_episode,
                                           on_episode_end=tracker.on_episode_end, targets_total=bp.TARGETS_TOTAL)
    track1 = bp.Track1PolicyWrapper(recording)
    v2 = SpatialObsV2Wrapper(track1, base=base)
    stats = bp.EpisodeStatsWrapper(v2)
    return bp.M7WorkerWrapper(stats, spec=spec, base=base, tracker=tracker, recording=recording)


class M7gWorkerFactory:
    """Top-level, picklable factory (spawn-safe) for the v2 worker stack."""

    def __init__(self, spec: Any):
        self.spec = spec

    def __call__(self) -> Any:
        return build_worker_env_v2(self.spec)
