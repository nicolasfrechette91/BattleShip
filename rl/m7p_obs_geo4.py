"""M7p (opt-in diagnostic contract): `btt_policy_obs_v3_geo4` = btt_policy_obs_v3_entities with ONE change.

The `segment_geometry` key (32 rows x 8 columns) is scaled by a factor 1/4 relative to v3:

    columns a_dx, a_dy, b_dx, b_dy, near_dx, near_dy   native units / 8,000   (v3: / 2,000)
    columns vel_x, vel_y                               native units per tick / 200   (v3: / 50)

Nothing else changes: `segment_kind` (binary flags, incl. present / moving), `agent` (positions, floor_dist and the
diamond stay / 2,000; velocities / 50), `targets`, `projectiles` and `action_class` are byte-identical to v3; masking,
key order, shapes (flat 606), the stale and displacement rules, the action-class table and the two native diagnostics
are v3's. No running normalisation (norm_obs must stay False). Network: btt_policy_net_v3_multiinput_mlp64 unchanged.

Selectable only by naming the contract in a profile's [contracts].observation; v3 stays the selected default and every
existing profile, record and fingerprint is unchanged. Checkpoints of the two contracts are never interchangeable
(different contract id and digest).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Sequence

import m7g_spatial as ms
import m7n_obs as mn

OBS_CONTRACT = "btt_policy_obs_v3_geo4"
OBS_SCHEMA_VERSION = 1
GEOMETRY_SCALE_FACTOR = 4.0
SEGMENT_LENGTH_SCALE = mn.LENGTH_SCALE * GEOMETRY_SCALE_FACTOR       # 8,000
SEGMENT_VELOCITY_SCALE = mn.VELOCITY_SCALE * GEOMETRY_SCALE_FACTOR   # 200
CHANGED_KEY = mn.SEGMENT_GEOMETRY_KEY
CHANGED_LENGTH_COLUMNS = ("a_dx", "a_dy", "b_dx", "b_dy", "near_dx", "near_dy")
CHANGED_VELOCITY_COLUMNS = ("vel_x", "vel_y")
UNCHANGED_KEYS = tuple(k for k in mn.KEY_ORDER if k != CHANGED_KEY)
ENTITY_EXTRA_ENV = mn.ENTITY_EXTRA_ENV
KEY_ORDER = mn.KEY_ORDER
SHAPES = mn.SHAPES
FLAT_SIZE = mn.FLAT_SIZE
make_observation_space = mn.make_observation_space
flatten = mn.flatten


def make_builder(lines: Sequence[ms.SpatialLine], classifier: Any) -> mn.EntityObservationBuilder:
    return mn.EntityObservationBuilder(lines, classifier, segment_length_scale=SEGMENT_LENGTH_SCALE,
                                       segment_velocity_scale=SEGMENT_VELOCITY_SCALE)


class EntityObsGeo4Wrapper(mn.EntityObsV3Wrapper):
    """EntityObsV3Wrapper whose builder scales the segment_geometry block by 1/4 (everything else inherited)."""

    contract_id = OBS_CONTRACT

    def _make_builder(self, lines: Sequence[ms.SpatialLine]) -> mn.EntityObservationBuilder:
        return make_builder(lines, self.classifier)


def contract_description() -> Dict[str, Any]:
    d = mn.contract_description()
    d["contract"] = OBS_CONTRACT
    d["schema_version"] = OBS_SCHEMA_VERSION
    d["derived_from"] = {"contract": mn.OBS_CONTRACT, "contract_sha256": mn.contract_digest(),
                         "only_change": f"{CHANGED_KEY}: length columns {list(CHANGED_LENGTH_COLUMNS)} / {SEGMENT_LENGTH_SCALE:g} "
                                        f"(v3 / {mn.LENGTH_SCALE:g}); velocity columns {list(CHANGED_VELOCITY_COLUMNS)} / "
                                        f"{SEGMENT_VELOCITY_SCALE:g} (v3 / {mn.VELOCITY_SCALE:g}); factor {GEOMETRY_SCALE_FACTOR:g}",
                         "unchanged_keys": list(UNCHANGED_KEYS)}
    d["keys"][CHANGED_KEY] = dict(d["keys"][CHANGED_KEY],
                                  units=f"native units (TopN-relative) / {SEGMENT_LENGTH_SCALE:g}; velocity / {SEGMENT_VELOCITY_SCALE:g}")
    d["scaling"] = dict(d["scaling"], segment_geometry={"length": SEGMENT_LENGTH_SCALE, "velocity": SEGMENT_VELOCITY_SCALE})
    d["compatibility"] = ("fresh models only; a btt_policy_obs_v1, v2_spatial or v3_entities checkpoint is refused; v3 stays "
                          "available, byte-identical and the selected default")
    return d


def contract_digest() -> str:
    return hashlib.sha256(json.dumps(contract_description(), sort_keys=True).encode("utf-8")).hexdigest()


def m7p_contracts(horizon: int, reward: Any, character: str = mn.DEFAULT_CHARACTER) -> Dict[str, Any]:
    c = mn.m7n_contracts(horizon, reward, character)
    c.update({"policy_observation_contract": OBS_CONTRACT, "policy_observation_contract_sha256": contract_digest(),
              "policy_observation_derived_from": mn.OBS_CONTRACT})
    return c


def build_worker_env_geo4(spec: Any) -> Any:
    return mn.build_worker_env_v3(spec, wrapper_cls=EntityObsGeo4Wrapper, contracts_fn=m7p_contracts)


class M7pWorkerFactory:
    """Top-level, picklable factory (spawn-safe) for the geo4 worker stack."""

    def __init__(self, spec: Any):
        self.spec = spec

    def __call__(self) -> Any:
        return build_worker_env_geo4(self.spec)


if __name__ == "__main__":
    print(json.dumps({"contract": OBS_CONTRACT, "flat_size": FLAT_SIZE, "digest": contract_digest(),
                      "derived_from": mn.OBS_CONTRACT, "v3_digest": mn.contract_digest()}, indent=1))
