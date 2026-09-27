"""M7n: the Stable-Baselines3 policy for `btt_policy_obs_v3_entities` (identity, construction, checks).

Network identity `btt_policy_net_v3_multiinput_mlp64`:

    SB3 MultiInputPolicy (MultiInputActorCriticPolicy), share_features_extractor=True
    CombinedExtractor: every v3 key is a 1-D/2-D Box (never an image), so each key is flattened and the keys are
                       concatenated in KEY_ORDER -> 606 features; the extractor has no parameters
    pi: Linear(606, 64) Tanh Linear(64, 64) Tanh -> action net Linear(64, 17) (MultiDiscrete [9, 8] logits)
    vf: Linear(606, 64) Tanh Linear(64, 64) Tanh -> value net Linear(64, 1)

It is the M7 control network (MlpPolicy, net_arch [64, 64], tanh) with only the input width changed (15 -> 606),
exactly as the M7g v2 network was (15 -> 525). PPO hyperparameters are not touched here.

VecNormalize: the v3 keys are pre-scaled by physical constants (rl/m7n_obs.py), so observation normalisation is OFF
(norm_obs=False: a masked row is exactly zero at the network input, and nothing of the run's statistics enters the
checkpoint); norm_reward=False as in every M7 run. The wrapper still exists so the trainer / evaluator stack, the
checkpoint set (vecnormalize.pkl) and the frozen-evaluation rule stay identical in shape.

Checkpoints: v3 models are fresh; a v1 or v2 checkpoint is refused for v3 and vice versa (assert_v3_checkpoint).
Initialisation, forward passes, save/load and frozen evaluation only: nothing here learns.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import m7n_obs as mn

NETWORK_ID = "btt_policy_net_v3_multiinput_mlp64"
POLICY = "MultiInputPolicy"
NET_ARCH = (64, 64)
ACTIVATION = "tanh"


def policy_kwargs() -> Dict[str, Any]:
    import torch

    return {"net_arch": {"pi": list(NET_ARCH), "vf": list(NET_ARCH)}, "activation_fn": torch.nn.Tanh}


def make_vecnormalize(venv: Any, *, training: bool = True, gamma: float = 0.999, clip_obs: float = 10.0) -> Any:
    from stable_baselines3.common.vec_env import VecNormalize

    return VecNormalize(venv, training=training, norm_obs=False, norm_reward=False, clip_obs=clip_obs, gamma=gamma)


def make_model(env: Any, *, seed: int = 0, **ppo_kwargs: Any) -> Any:
    """A freshly initialised PPO MultiInputPolicy model on `env` (no learning happens here)."""
    from stable_baselines3 import PPO

    return PPO(POLICY, env, policy_kwargs=policy_kwargs(), seed=seed, device="cpu", verbose=0, **ppo_kwargs)


def describe(model: Any) -> Dict[str, Any]:
    """Measured structure of a model's policy (the M7g describe, under the v3 network id)."""
    import m7g_policy as mp

    d = mp.describe(model)
    d["network_id"] = NETWORK_ID
    return d


def assert_v3_checkpoint(model_zip: Path) -> None:
    """Refuse a checkpoint whose stored observation space is not the v3 Dict (any v1 / v2 model)."""
    from stable_baselines3.common.save_util import load_from_zip_file

    data, _params, _vars = load_from_zip_file(str(model_zip), device="cpu", load_data=True)
    space = data.get("observation_space")
    expected = mn.make_observation_space()
    if space != expected:
        raise ValueError(f"{model_zip} was not trained on {mn.OBS_CONTRACT}: stored observation space {space}")
