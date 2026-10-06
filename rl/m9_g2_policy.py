"""M9-g2: the frozen policy of an attempt or of the close audit: a weight-only copy of the live network, keyed inverse-CDF sampling, no optimizer.

`FrozenPolicy` is the g1 checkpoint evaluation's pinned policy (rl/m9_eval_policy: the SB3 building blocks `MlpExtractor` 606 -> [64, 64] tanh,
`Linear(64, 17)`, `Linear(64, 1)`, `MultiCategoricalDistribution([9, 8])`, the inverse CDF, the 12 registered state keys) built from a state dict instead
of a model.zip, and WITHOUT the process-wide optimizer guard: the training session keeps its live Adam optimizer in the same process. The frozen copy is
written once to disk (`torch.save` of the 12 tensors); its sha256 is the recorded snapshot digest, and the policy that runs is loaded back from that file.

Decisions: one observation per forward pass, one torch thread; argmax per dimension for a deterministic word; the stochastic word is drawn by inverse CDF
on `rl/m9_sticky.uniform(<key>|stick)` and `(<key>|button)`, where <key> is the probe or audit action key (decision R1). Nothing here learns.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

import numpy as np

import m9_eval_policy as POL
import m9_sticky as S

POLICY_CONTRACT = "m9_g2_policy_v1"
STATE_KEYS = POL.STATE_KEYS
OBS_FLAT = POL.OBS_FLAT
DIMS = POL.DIMS


class SnapshotError(RuntimeError):
    pass


def state_dict_of(model: Any) -> Dict[str, Any]:
    """The 12 registered tensors of a live SB3 model's policy, detached and copied (CPU)."""
    sd = {k: v.detach().cpu().clone() for k, v in model.policy.state_dict().items()}
    if tuple(sorted(sd)) != tuple(sorted(STATE_KEYS)):
        raise SnapshotError(f"the live policy's state keys {sorted(sd)} are not the registered v3 network's")
    return sd


def save_snapshot(sd: Mapping[str, Any], path: Path) -> Dict[str, Any]:
    """Write the state dict with torch.save; return its sha256 and size (the recorded snapshot digest)."""
    import torch

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    torch.save(dict(sd), buf)
    raw = buf.getvalue()
    path.write_bytes(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def load_snapshot(path: Path, pin_sha256: Optional[str] = None) -> Dict[str, Any]:
    import torch

    raw = Path(path).read_bytes()
    got = hashlib.sha256(raw).hexdigest()
    if pin_sha256 is not None and got != pin_sha256:
        raise SnapshotError(f"snapshot {path}: sha256 {got} differs from the pin {pin_sha256}")
    sd = torch.load(io.BytesIO(raw), map_location="cpu", weights_only=True)
    if tuple(sorted(sd)) != tuple(sorted(STATE_KEYS)):
        raise SnapshotError(f"snapshot {path}: keys {sorted(sd)} are not the registered v3 network's")
    return sd


class FrozenPolicy:
    """A weight-only policy evaluated one observation at a time (one torch thread); every stochastic draw is keyed."""

    def __init__(self, name: str, sd: Mapping[str, Any], sha256: str):
        import torch

        torch.set_num_threads(1)
        net = POL._net()
        net.load_state_dict(dict(sd), strict=True)
        net.eval()
        for p in net.parameters():
            p.requires_grad_(False)
        self.name, self.net, self.sha256 = name, net, sha256
        self.decisions = 0

    @classmethod
    def from_file(cls, name: str, path: Path, pin_sha256: Optional[str] = None) -> "FrozenPolicy":
        sd = load_snapshot(path, pin_sha256)
        return cls(name, sd, pin_sha256 or hashlib.sha256(Path(path).read_bytes()).hexdigest())

    def _forward(self, flat: np.ndarray) -> Tuple[Any, Any, float]:
        import torch

        x = np.asarray(flat, dtype=np.float32).reshape(1, OBS_FLAT)
        with torch.no_grad():
            logits, v = self.net(torch.from_numpy(x))
            ps = torch.softmax(logits[0, :DIMS[0]], dim=-1)
            pb = torch.softmax(logits[0, DIMS[0]:], dim=-1)
        return ps.numpy().astype(np.float64), pb.numpy().astype(np.float64), float(v[0])

    def value(self, flat: np.ndarray) -> float:
        return self._forward(flat)[2]

    def entropy(self, flat: np.ndarray) -> float:
        """ln-nats entropy of the joint (the sum of the two categoricals' entropies, as SB3's MultiCategoricalDistribution.entropy)."""
        ps, pb, _v = self._forward(flat)
        h = 0.0
        for p in (ps, pb):
            q = p[p > 0]
            h -= float(np.sum(q * np.log(q)))
        return h

    def stats(self, flat: np.ndarray) -> Dict[str, float]:
        ps, pb, v = self._forward(flat)
        h = 0.0
        for p in (ps, pb):
            q = p[p > 0]
            h -= float(np.sum(q * np.log(q)))
        return {"v": round(v, 4), "h": round(h, 4), "top_word_p": round(float(ps.max() * pb.max()), 5)}

    def argmax_word(self, flat: np.ndarray) -> int:
        ps, pb, _v = self._forward(flat)
        self.decisions += 1
        return int(np.argmax(ps)) * 8 + int(np.argmax(pb))

    def sample_word(self, flat: np.ndarray, key: str) -> int:
        """stick = inverse CDF on uniform(key|stick), button = inverse CDF on uniform(key|button); word = stick * 8 + button."""
        ps, pb, _v = self._forward(flat)
        s = POL.inverse_cdf(ps, S.uniform(key + "|stick"))
        b = POL.inverse_cdf(pb, S.uniform(key + "|button"))
        self.decisions += 1
        return s * 8 + b


def flatten_obs(obs: Mapping[str, Any]) -> np.ndarray:
    """The 606-float vector (rl/m7n_obs.flatten's order) from a dict of the six v3 arrays."""
    import m7n_obs as mn

    return mn.flatten(obs)


def contract_description() -> Dict[str, Any]:
    return {"contract": POLICY_CONTRACT, "network": POL.contract_description()["network"], "snapshot": "torch.save of the 12 registered tensors; sha256 of the file is the digest",
            "deterministic": "argmax per dimension", "stochastic": "inverse CDF on keyed sha256 uniforms (<key>|stick, <key>|button)", "batch": "one observation per forward pass, one torch thread"}
