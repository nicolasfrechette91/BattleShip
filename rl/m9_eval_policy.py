"""M9-g1 checkpoint evaluation: a pinned, read-only M9-g1 checkpoint as a weight-only policy, with keyed action sampling and NO optimizer.

Plan: docs/rl_m9_g1_checkpoint_eval_plan_2026-10-04.md (section 4). Nothing here learns.

* `install_optimizer_guard()` replaces `torch.optim.Optimizer.__init__` with a function that raises, BEFORE any checkpoint is read: no optimizer
  object can be built in a process that evaluates (an SB3 policy class or the SB3 model loader would build one, so neither is used).
* `PinnedPolicy(name, zip_path, pin)` reads the checkpoint's bytes once, refuses them unless their sha256 equals the pin, and loads only the
  `policy.pth` tensor state dict (`torch.load(weights_only=True)`). The network is rebuilt from Stable-Baselines3's own building blocks, exactly the
  M7n v3 network (rl/m7n_policy): `MlpExtractor` 606 -> [64, 64] tanh for pi and vf, `Linear(64, 17)` (MultiDiscrete [9, 8] logits) and
  `Linear(64, 1)`; `MultiCategoricalDistribution([9, 8])` gives the argmax (`mode()`) and the entropy, as SB3's `predict` does; the sampling
  probabilities are the softmax of each logit split (equal to SB3's distribution probabilities to float32 rounding). The checkpoint file is never
  written; the parameters never require gradients.
* Deterministic word: the argmax of each distribution (SB3's `mode()`), word = stick * 8 + button.
* Stochastic word: each dimension is drawn by inverse CDF from a Python-side keyed sha256 uniform (`rl/m9_sticky.uniform`),
  key `m9|g1eval|act|<mode>|<tau>|<k>|<tick>|<stick|button>`; the key does not name the checkpoint (common random numbers across checkpoints).
  The draw is the same distribution as SB3's sampling; only the source of the uniforms differs (keyed, reproducible, never the native RNG).
* Every observation is evaluated alone (batch of one, one torch thread), so a decision is a pure function of (checkpoint, observation, key).
"""
from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

import m9_sticky as S

POLICY_CONTRACT = "m9_eval_policy_v1"
OBS_FLAT = 606
DIMS = (9, 8)
STATE_KEYS = ("mlp_extractor.policy_net.0.weight", "mlp_extractor.policy_net.0.bias", "mlp_extractor.policy_net.2.weight", "mlp_extractor.policy_net.2.bias",
              "mlp_extractor.value_net.0.weight", "mlp_extractor.value_net.0.bias", "mlp_extractor.value_net.2.weight", "mlp_extractor.value_net.2.bias",
              "action_net.weight", "action_net.bias", "value_net.weight", "value_net.bias")
ACTION_KEY = "m9|g1eval|act|{mode}|{tau}|{k}|{tick}|{dim}"
MODES = ("sticky", "unperturbed")


class OptimizerForbidden(RuntimeError):
    """An optimizer was about to be built in an evaluation process."""


class PinError(RuntimeError):
    """A checkpoint's bytes differ from its pin, or its state dict is not the registered network."""


def install_optimizer_guard() -> None:
    """Make every optimizer construction in this process raise (idempotent)."""
    import torch

    init = torch.optim.Optimizer.__init__
    if getattr(init, "_m9_eval_guard", False):
        return

    def _refuse(self: Any, *a: Any, **k: Any) -> None:
        raise OptimizerForbidden(f"an optimizer ({type(self).__name__}) was about to be built in an evaluation process: forbidden")

    _refuse._m9_eval_guard = True                                 # type: ignore[attr-defined]
    torch.optim.Optimizer.__init__ = _refuse                      # type: ignore[assignment]


def guard_installed() -> bool:
    import torch

    return bool(getattr(torch.optim.Optimizer.__init__, "_m9_eval_guard", False))


def action_key(mode: str, tau: int, k: int, tick: int, dim: str) -> str:
    if mode not in MODES:
        raise ValueError(f"unknown sampling mode {mode!r}")
    if dim not in ("stick", "button"):
        raise ValueError(f"unknown dimension {dim!r}")
    return ACTION_KEY.format(mode=mode, tau=int(tau), k=int(k), tick=int(tick), dim=dim)


def inverse_cdf(probs: Sequence[float], u: float) -> int:
    """The smallest index i with u < p_0 + ... + p_i (probabilities in float64, renormalised); the last index with positive mass if rounding leaves u above the sum."""
    p = np.asarray(probs, dtype=np.float64)
    if p.ndim != 1 or p.size == 0 or not np.all(np.isfinite(p)) or np.any(p < 0):
        raise ValueError("probabilities must be a finite non-negative vector")
    s = float(p.sum())
    if s <= 0:
        raise ValueError("probabilities sum to zero")
    c = np.cumsum(p / s)
    i = int(np.searchsorted(c, float(u), side="right"))
    if i >= p.size:
        i = int(np.flatnonzero(p > 0)[-1])
    return i


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _net() -> Any:
    import torch
    from stable_baselines3.common.distributions import MultiCategoricalDistribution
    from stable_baselines3.common.torch_layers import MlpExtractor

    class Net(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.mlp_extractor = MlpExtractor(OBS_FLAT, net_arch={"pi": [64, 64], "vf": [64, 64]}, activation_fn=torch.nn.Tanh, device="cpu")
            self.action_net = torch.nn.Linear(64, sum(DIMS))
            self.value_net = torch.nn.Linear(64, 1)
            self.dist = MultiCategoricalDistribution(list(DIMS))

        def forward(self, x: Any) -> Tuple[Any, Any]:
            pi, vf = self.mlp_extractor(x)
            return self.action_net(pi), self.value_net(vf).squeeze(-1)

    return Net()


class PinnedPolicy:
    """One pinned checkpoint, read-only, evaluated without any optimizer."""

    def __init__(self, name: str, zip_path: Path, pin_sha256: str):
        import torch

        install_optimizer_guard()
        torch.set_num_threads(1)
        raw = Path(zip_path).read_bytes()
        got = sha256_bytes(raw)
        if got != pin_sha256:
            raise PinError(f"{name}: model.zip sha256 {got} differs from the pin {pin_sha256}")
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            sd = torch.load(io.BytesIO(z.read("policy.pth")), map_location="cpu", weights_only=True)
        if tuple(sorted(sd)) != tuple(sorted(STATE_KEYS)):
            raise PinError(f"{name}: policy.pth keys {sorted(sd)} are not the registered v3 network's")
        net = _net()
        net.load_state_dict(sd, strict=True)
        net.eval()
        for p in net.parameters():
            p.requires_grad_(False)
        self.name, self.path, self.sha256, self.net = name, Path(zip_path), got, net
        self.decisions = 0

    def _dist(self, flat: np.ndarray) -> Tuple[Any, float]:
        import torch

        x = np.asarray(flat, dtype=np.float32).reshape(1, OBS_FLAT)
        with torch.no_grad():
            logits, v = self.net(torch.from_numpy(x))
            d = self.net.dist.proba_distribution(logits)
        return d, float(v[0])

    def value(self, flat: np.ndarray) -> float:
        return self._dist(flat)[1]

    def probabilities(self, flat: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """The two categorical distributions: softmax of each logit split (float32, as torch's Categorical computes its probs), as float64."""
        import torch

        x = np.asarray(flat, dtype=np.float32).reshape(1, OBS_FLAT)
        with torch.no_grad():
            pi, _vf = self.net.mlp_extractor(torch.from_numpy(x))
            logits = self.net.action_net(pi)[0]
            ps = torch.softmax(logits[:DIMS[0]], dim=-1)
            pb = torch.softmax(logits[DIMS[0]:], dim=-1)
        return ps.numpy().astype(np.float64), pb.numpy().astype(np.float64)

    def argmax_word(self, flat: np.ndarray) -> int:
        d, _v = self._dist(flat)
        m = d.mode()[0]
        self.decisions += 1
        return int(m[0]) * 8 + int(m[1])

    def sample_word(self, flat: np.ndarray, mode: str, tau: int, k: int, tick: int) -> int:
        ps, pb = self.probabilities(flat)
        s = inverse_cdf(ps, S.uniform(action_key(mode, tau, k, tick, "stick")))
        b = inverse_cdf(pb, S.uniform(action_key(mode, tau, k, tick, "button")))
        self.decisions += 1
        return s * 8 + b

    def entropy(self, flat: np.ndarray) -> float:
        d, _v = self._dist(flat)
        return float(d.entropy()[0])


def load_policies(entries: Sequence[Mapping[str, Any]], root: Path) -> Dict[str, PinnedPolicy]:
    """{name: PinnedPolicy} for entries {name, path (relative to root), sha256}; any pin mismatch raises before anything runs."""
    out: Dict[str, PinnedPolicy] = {}
    for e in entries:
        out[str(e["name"])] = PinnedPolicy(str(e["name"]), Path(root) / str(e["path"]), str(e["sha256"]))
    return out


def pin_problems(entries: Sequence[Mapping[str, Any]], root: Path) -> List[str]:
    """The pins checked by reading the bytes (no torch import): one problem per missing or differing checkpoint."""
    out: List[str] = []
    for e in entries:
        p = Path(root) / str(e["path"])
        if not p.is_file():
            out.append(f"{e['name']}: missing {p}")
            continue
        got = sha256_bytes(p.read_bytes())
        if got != e["sha256"]:
            out.append(f"{e['name']}: sha256 {got} differs from the pin {e['sha256']}")
    return out


def contract_description() -> Dict[str, Any]:
    return {"contract": POLICY_CONTRACT, "network": "SB3 MlpExtractor 606 -> [64, 64] tanh (pi, vf), Linear(64, 17), Linear(64, 1); MultiCategoricalDistribution([9, 8])",
            "loading": "model.zip sha256 == pin; policy.pth only (torch.load weights_only=True); no PPO, no policy class, no optimizer (guarded)",
            "deterministic": "argmax per dimension (SB3 mode())", "stochastic": "inverse CDF of each dimension on keyed sha256 uniforms",
            "action_key": ACTION_KEY, "batch": "one observation per forward pass, one torch thread"}
