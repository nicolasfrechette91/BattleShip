"""M9-g1: the policy-observation pipeline over raw replies (observation `btt_policy_obs_v3_entities`).

The v3 observation is a deterministic function of the reply sequence of an episode (displacement and target velocity read the previous
reply, projectile slots are sticky per spawn serial), so a staged start at tick tau feeds EVERY prefix reply to the builder, exactly as the
M7n prefix harness did (rl/tools/m7n_prefix_feasibility.py `Builder`): the policy sees what it would have seen had it played the prefix.
This module is that harness's `Builder` as a reusable class, plus the fixed digest of an observation (rl/m7n_obs.observation_digest).

`V3Pipeline(initial_reply)` is built from the non-consuming tick-0 `observe` reply (it carries the collision line table); `feed(reply)` takes
one raw `step` reply; `obs` is the dict of six float32 arrays for the latest reply. Heavy imports (numpy, gymnasium through rl/m7n_obs) are
inside the constructor, so a module that only needs digests stays light.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

OBS_PIPELINE_CONTRACT = "m9_obs_pipeline_v1"
_TABLE: Optional[Dict[str, Any]] = None


def _table() -> Dict[str, Any]:
    global _TABLE
    if _TABLE is None:
        import m7n_status_table as st

        _TABLE = st.load_table()
    return _TABLE


class V3Pipeline:
    def __init__(self, initial_reply: Mapping[str, Any]):
        import m7g_spatial as ms
        import m7n_entity as ne
        import m7n_obs as mn
        import m7n_status_table as st

        self.ms, self.ne, self.mn = ms, ne, mn
        sp = ms.spatial_of(initial_reply, expect_lines=True)
        en = ne.entity_of(initial_reply)
        self.classifier = st.ActionClassifier(_table(), mn.DEFAULT_CHARACTER)
        self.builder = mn.EntityObservationBuilder(sp.lines or (), self.classifier)
        self.obs, self.stale = self.builder.build(initial_reply["observation"], sp, en)

    def feed(self, reply: Mapping[str, Any]) -> None:
        sp = self.ms.spatial_of(reply, expect_lines=False)
        en = self.ne.entity_of(reply)
        self.obs, self.stale = self.builder.build(reply["observation"], sp, en)

    def digest(self) -> str:
        return self.mn.observation_digest(self.obs)

    def arrays(self) -> Dict[str, Any]:
        """The current observation as plain arrays (a copy: the builder returns copies already)."""
        return {k: v for k, v in self.obs.items()}


def observation_space() -> Any:
    import m7n_obs as mn

    return mn.make_observation_space()


def contract_description() -> Dict[str, Any]:
    import m7n_obs as mn

    return {"contract": OBS_PIPELINE_CONTRACT, "observation": mn.OBS_CONTRACT, "observation_digest": mn.contract_digest(), "flat_size": mn.FLAT_SIZE,
            "feeds": "the tick-0 observe reply, then every prefix reply and every policy-phase reply, in order"}
