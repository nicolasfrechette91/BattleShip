"""M7g-b Phase H: the Stable-Baselines3 policy for `btt_policy_obs_v2_spatial` (identity, construction, checks).

Network identity `btt_policy_net_v2_multiinput_mlp64`:

    SB3 MultiInputPolicy (MultiInputActorCriticPolicy), share_features_extractor=True
    CombinedExtractor: every v2 key is a 1-D/2-D Box (never an image), so each key is flattened (nn.Flatten) and the
                       keys are concatenated in KEY_ORDER -> 525 features; the extractor has no parameters
    pi: Linear(525, 64) Tanh Linear(64, 64) Tanh -> action net Linear(64, 17) (MultiDiscrete [9, 8] logits)
    vf: Linear(525, 64) Tanh Linear(64, 64) Tanh -> value net Linear(64, 1)

It is the M7 control network (MlpPolicy, net_arch [64, 64], tanh) with only the input width changed (15 -> 525): the
one architecture adjustment the Dict observation strictly requires (SB3 rejects a Dict space under MlpPolicy). PPO
hyperparameters are not touched here.

VecNormalize: norm_obs=True with norm_obs_keys = NORMALIZED_KEYS (segment_geometry, state, target_geometry); the binary
keys segment_kind / target_live are never normalised; norm_reward=False; clip_obs 10.

Checkpoints: v2 models are fresh; a v1 (15-float Box) checkpoint is refused for v2 and vice versa
(assert_v2_checkpoint). Initialisation, forward passes, save/load and frozen evaluation only: nothing here learns.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping

import numpy as np

import m7g_obs as mo

NETWORK_ID = "btt_policy_net_v2_multiinput_mlp64"
POLICY = "MultiInputPolicy"
NET_ARCH = (64, 64)
ACTIVATION = "tanh"
CLIP_OBS = 10.0


def policy_kwargs() -> Dict[str, Any]:
    import torch

    return {"net_arch": {"pi": list(NET_ARCH), "vf": list(NET_ARCH)}, "activation_fn": torch.nn.Tanh}


def make_vecnormalize(venv: Any, *, training: bool = True, gamma: float = 0.999) -> Any:
    from stable_baselines3.common.vec_env import VecNormalize

    return VecNormalize(venv, training=training, norm_obs=True, norm_reward=False, clip_obs=CLIP_OBS, gamma=gamma,
                        norm_obs_keys=list(mo.NORMALIZED_KEYS))


def make_model(env: Any, *, seed: int = 0, **ppo_kwargs: Any) -> Any:
    """A freshly initialised PPO MultiInputPolicy model on `env` (no learning happens here)."""
    from stable_baselines3 import PPO

    return PPO(POLICY, env, policy_kwargs=policy_kwargs(), seed=seed, device="cpu", verbose=0, **ppo_kwargs)


def describe(model: Any) -> Dict[str, Any]:
    """Measured structure of a model's policy: parameter counts per module, feature width, layer shapes."""
    pol = model.policy
    counts = {name: int(sum(p.numel() for p in mod.parameters()))
              for name, mod in (("features_extractor", pol.features_extractor), ("mlp_extractor", pol.mlp_extractor),
                                ("action_net", pol.action_net), ("value_net", pol.value_net))}
    layers = {name: [list(p.shape) for p in mod.parameters()]
              for name, mod in (("policy_net", pol.mlp_extractor.policy_net), ("value_net_body", pol.mlp_extractor.value_net),
                                ("action_net", pol.action_net), ("value_head", pol.value_net))}
    return {"network_id": NETWORK_ID, "policy_class": type(pol).__name__,
            "features_extractor": type(pol.features_extractor).__name__,
            "features_dim": int(pol.features_extractor.features_dim), "parameters": int(sum(counts.values())),
            "parameters_by_module": counts, "layers": layers,
            "share_features_extractor": bool(pol.share_features_extractor),
            "activation": type(pol.mlp_extractor.policy_net[1]).__name__}


def assert_v2_checkpoint(model_zip: Path) -> None:
    """Refuse a checkpoint whose stored observation space is not the v2 Dict (e.g. any btt_policy_obs_v1 model)."""
    from stable_baselines3.common.save_util import load_from_zip_file

    data, _params, _vars = load_from_zip_file(str(model_zip), device="cpu", load_data=True)
    space = data.get("observation_space")
    expected = mo.make_observation_space()
    if space != expected:
        raise ValueError(f"{model_zip} was not trained on {mo.OBS_CONTRACT}: stored observation space {space}")


def normalized_view(vecnorm: Any, obs: Mapping[str, np.ndarray]) -> Dict[str, np.ndarray]:
    """VecNormalize's view of a batched Dict observation (continuous keys normalised, binary keys untouched)."""
    return vecnorm.normalize_obs({k: np.asarray(v) for k, v in obs.items()})
