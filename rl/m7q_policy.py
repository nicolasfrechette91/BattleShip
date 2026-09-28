"""M7q: the Stable-Baselines3 policy for `btt_policy_obs_v4_input` (identity, construction, checks).

Network identity `btt_policy_net_v4_multiinput_mlp64`: the M7n network (rl/m7n_policy.py: MultiInputPolicy,
CombinedExtractor flattening every key, pi / vf Linear(626, 64) Tanh Linear(64, 64) Tanh, tanh) with only the input
width changed (606 -> 626). PPO hyperparameters are not touched here. VecNormalize: norm_obs=False, norm_reward=False
exactly as v3 (the keys are pre-scaled). Checkpoints: v4 models are fresh; a v1 / v2 / v3 / geo4 checkpoint is refused
(assert_v4_checkpoint). Nothing here learns.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import m7n_policy as mnp
import m7q_obs as mq

NETWORK_ID = "btt_policy_net_v4_multiinput_mlp64"
POLICY = mnp.POLICY
NET_ARCH = mnp.NET_ARCH
ACTIVATION = mnp.ACTIVATION

policy_kwargs = mnp.policy_kwargs
make_vecnormalize = mnp.make_vecnormalize
make_model = mnp.make_model


def describe(model: Any) -> Dict[str, Any]:
    """Measured structure of a model's policy (the M7g describe, under the v4 network id)."""
    import m7g_policy as mp

    d = mp.describe(model)
    d["network_id"] = NETWORK_ID
    return d


def assert_v4_checkpoint(model_zip: Path) -> None:
    """Refuse a checkpoint whose stored observation space is not the v4 Dict (any v1 / v2 / v3 / geo4 model)."""
    from stable_baselines3.common.save_util import load_from_zip_file

    data, _params, _vars = load_from_zip_file(str(model_zip), device="cpu", load_data=True)
    space = data.get("observation_space")
    expected = mq.make_observation_space()
    if space != expected:
        raise ValueError(f"{model_zip} was not trained on {mq.OBS_CONTRACT}: stored observation space {space}")
