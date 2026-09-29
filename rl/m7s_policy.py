"""M7s stage 1: the goal-conditioned return policy `btt_gcsl_policy_v1`, its matched initialisation, per-episode action
sampling (common random numbers for R and U), the GCSL training step and the initialisation diagnostics.

Network: v3 trunk 606 -> 64 tanh | bounded goal branch 14 -> 32 tanh (weights at orthogonal gain sqrt(2) * GOAL_GAIN)
-> joint 96 -> 64 tanh -> heads 64 -> 9 (stick) and 64 -> 8 (button). No critic, no reward. One parameter set per seed
from a torch.Generator seeded with sha256("m7s1|init|seed"); R starts from it, U loads the same file and never updates.
Design: docs/rl_goal_exploration_design_2026-09-28.md (revision 3, sections 3, 4.3 and 7).
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import torch as th
from torch import nn

import m7n_obs as mn
import m7s_goal as mg

POLICY_CONTRACT = "btt_gcsl_policy_v1"
V3_DIM = mn.FLAT_SIZE              # 606
TRUNK = 64
GOAL_UNITS = 32
JOINT = 64
STICK_STATES = 9
BUTTON_STATES = 8
GAIN = math.sqrt(2.0)
HEAD_GAIN = 0.01
GOAL_GAIN = 1.0                    # registered kappa of the goal branch (orthogonal gain sqrt(2) * GOAL_GAIN)
LEARNING_RATE = 3e-4
BATCH = 512
STEPS_PER_CHUNK = 100
CHUNK_TICKS = 5120
MAX_GRAD_NORM = 0.5
SENSITIVITY_RANGE = (0.1, 10.0)    # registered: goal / state sensitivity ratio of the joint layer at initialisation
SATURATION = 0.95
GOAL_BLIND_TV = 0.01             # goal-blind flag: action TV for a goal swap below this after training (fixed before any
                                 # live run; rule m7s1_return_rule_v2 refuses a pass for a goal-blind R)


class GoalPolicy(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.trunk = nn.Linear(V3_DIM, TRUNK)
        self.goal = nn.Linear(mg.GOAL_DIM, GOAL_UNITS)
        self.joint = nn.Linear(TRUNK + GOAL_UNITS, JOINT)
        self.stick = nn.Linear(JOINT, STICK_STATES)
        self.button = nn.Linear(JOINT, BUTTON_STATES)

    def features(self, v3: th.Tensor, goal: th.Tensor) -> Dict[str, th.Tensor]:
        h1 = th.tanh(self.trunk(v3))
        g1 = th.tanh(self.goal(goal))
        z = self.joint(th.cat([h1, g1], dim=-1))
        return {"h1": h1, "g1": g1, "z": z, "h2": th.tanh(z)}

    def forward(self, v3: th.Tensor, goal: th.Tensor) -> Tuple[th.Tensor, th.Tensor]:
        h2 = self.features(v3, goal)["h2"]
        return self.stick(h2), self.button(h2)


def init_policy(seed: int, *, goal_gain: float = GOAL_GAIN) -> GoalPolicy:
    """The seed's single initial parameter set (identical for R and U)."""
    gen = th.Generator().manual_seed(mg.seed_int("init", seed) % (2 ** 63))
    p = GoalPolicy()
    with th.no_grad():
        for layer, gain in ((p.trunk, GAIN), (p.goal, GAIN * goal_gain), (p.joint, GAIN), (p.stick, HEAD_GAIN),
                            (p.button, HEAD_GAIN)):
            nn.init.orthogonal_(layer.weight, gain=gain, generator=gen)
            layer.bias.zero_()
    return p


def parameter_digest(policy: nn.Module) -> str:
    h = hashlib.sha256()
    for name, t in sorted(policy.state_dict().items()):
        h.update(name.encode("utf-8"))
        h.update(t.detach().cpu().contiguous().numpy().tobytes())
    return h.hexdigest()


def save_policy(path: Path, policy: GoalPolicy, meta: Mapping[str, Any]) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = parameter_digest(policy)
    th.save({"contract": POLICY_CONTRACT, "state_dict": policy.state_dict(), "digest": digest, "meta": dict(meta)}, path)
    return digest


def load_policy(path: Path) -> Tuple[GoalPolicy, Dict[str, Any]]:
    doc = th.load(Path(path), map_location="cpu", weights_only=False)
    if doc.get("contract") != POLICY_CONTRACT:
        raise mg.GoalContractError(f"{path}: not a {POLICY_CONTRACT} file")
    p = GoalPolicy()
    p.load_state_dict(doc["state_dict"])
    if parameter_digest(p) != doc["digest"]:
        raise mg.GoalContractError(f"{path}: parameter digest mismatch")
    return p, dict(doc.get("meta") or {}, digest=doc["digest"])


# -- acting ---------------------------------------------------------------------------------------------------------------


def action_probs(policy: GoalPolicy, v3: np.ndarray, goal: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    with th.no_grad():
        ls, lb = policy(th.as_tensor(v3, dtype=th.float32), th.as_tensor(goal, dtype=th.float32))
        return (th.softmax(ls.double(), dim=-1).numpy(), th.softmax(lb.double(), dim=-1).numpy())


def sample_actions(ps: np.ndarray, pb: np.ndarray, generators: Sequence[Optional[np.random.Generator]]) -> np.ndarray:
    """One (stick, button) per row by inverse CDF with that row's episode generator (two uniforms per tick, drawn in
    the same order for every policy: common random numbers). A row with generator None gets (0, 0) and is not used."""
    out = np.zeros((len(ps), 2), dtype=np.int64)
    for i, g in enumerate(generators):
        if g is None:
            continue
        u = g.random(2)
        out[i, 0] = min(int(np.searchsorted(np.cumsum(ps[i]), u[0] * ps[i].sum(), side="right")), STICK_STATES - 1)
        out[i, 1] = min(int(np.searchsorted(np.cumsum(pb[i]), u[1] * pb[i].sum(), side="right")), BUTTON_STATES - 1)
    return out


# -- learning -------------------------------------------------------------------------------------------------------------


class GCSLTrainer:
    """Cross-entropy on both heads over relabelled own examples; STEPS_PER_CHUNK Adam steps per CHUNK_TICKS ticks."""

    def __init__(self, policy: GoalPolicy, seed: int) -> None:
        self.policy = policy
        self.opt = th.optim.Adam(policy.parameters(), lr=LEARNING_RATE)
        self.rng = mg.generator("relabel", seed)
        self.gradient_steps = 0
        self.samples = 0
        self.chunks: List[Dict[str, Any]] = []

    def train_chunk(self, episodes: Sequence[mg.EpisodeData], *, steps: int = STEPS_PER_CHUNK,
                    batch: int = BATCH) -> Dict[str, Any]:
        self.policy.train()
        losses, acc_s, acc_b, hs = [], [], [], []
        origins: Dict[str, int] = {}
        for _ in range(int(steps)):
            ex = mg.sample_examples(episodes, batch, self.rng)
            ls, lb = self.policy(th.as_tensor(ex["obs"]), th.as_tensor(ex["goal"]))
            ts, tb = th.as_tensor(ex["stick"]), th.as_tensor(ex["button"])
            loss = nn.functional.cross_entropy(ls, ts) + nn.functional.cross_entropy(lb, tb)
            self.opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(self.policy.parameters(), MAX_GRAD_NORM)
            self.opt.step()
            self.gradient_steps += 1
            self.samples += len(ts)
            losses.append(float(loss.detach()))
            acc_s.append(float((ls.argmax(-1) == ts).float().mean()))
            acc_b.append(float((lb.argmax(-1) == tb).float().mean()))
            hs.append(float(np.mean(ex["h"])))
            for eid in set(ex["episode"].tolist()):
                origins[eid] = 1
        self.policy.eval()
        with th.no_grad():   # diagnostics on the last batch: saturation and goal sensitivity (shuffled goals)
            v, g = th.as_tensor(ex["obs"]), th.as_tensor(ex["goal"])
            f = self.policy.features(v, g)
            perm = th.as_tensor(self.rng.permutation(len(g)))
            ps0, pb0 = (th.softmax(x, -1) for x in self.policy(v, g))
            ps1, pb1 = (th.softmax(x, -1) for x in self.policy(v, g[perm]))
            tv = float(0.25 * ((ps0 - ps1).abs().sum(-1) + (pb0 - pb1).abs().sum(-1)).mean())
        rec_diag = {"trunk_sat95": round(float((f["h1"].abs() > SATURATION).float().mean()), 4),
                    "goal_sat95": round(float((f["g1"].abs() > SATURATION).float().mean()), 4),
                    "joint_sat95": round(float((f["h2"].abs() > SATURATION).float().mean()), 4),
                    "action_tv_goal_shuffle": round(tv, 5)}
        rec = {"chunk": len(self.chunks) + 1, "gradient_steps": self.gradient_steps, "samples": self.samples,
               **rec_diag,
               "loss_mean": round(float(np.mean(losses)), 5), "loss_first": round(losses[0], 5),
               "loss_last": round(losses[-1], 5), "acc_stick": round(float(np.mean(acc_s)), 4),
               "acc_button": round(float(np.mean(acc_b)), 4), "h_mean": round(float(np.mean(hs)), 1),
               "episodes_available": len(episodes), "episodes_sampled": len(origins)}
        self.chunks.append(rec)
        return rec


# -- goal-sensitivity diagnostics (design section 7: at initialisation and after training) ------------------------------


def goal_sensitivity(policy: GoalPolicy, v3: np.ndarray, pos: np.ndarray, ticks: np.ndarray, goal_pool: Sequence[mg.Cell],
                     *, pairs: int = 2000, seed: int = 0) -> Dict[str, Any]:
    """On real v3 observations: saturation, goal-branch share of the joint pre-activation, goal / state sensitivity
    ratio of the joint output, and the action total-variation distance for a goal swap."""
    rng = np.random.default_rng(seed)
    m = len(v3)
    goals = [goal_pool[int(k)] for k in rng.integers(len(goal_pool), size=m)]
    feat = np.stack([mg.goal_features(g, pos[i, 0], pos[i, 1], mg.HORIZON - int(ticks[i])) for i, g in enumerate(goals)])
    with th.no_grad():
        f = policy.features(th.as_tensor(v3, dtype=th.float32), th.as_tensor(feat))
        w = policy.joint.weight
        state_part = f["h1"] @ w[:, :TRUNK].T
        goal_part = f["g1"] @ w[:, TRUNK:].T
        share = float((goal_part ** 2).sum() / ((state_part ** 2).sum() + (goal_part ** 2).sum()))
        i = rng.integers(m, size=pairs)
        j = rng.integers(m, size=pairs)
        g2 = [goal_pool[int(k)] for k in rng.integers(len(goal_pool), size=pairs)]
        feat_i = th.as_tensor(feat[i])
        feat_i_other = th.as_tensor(np.stack([mg.goal_features(g2[k], pos[i[k], 0], pos[i[k], 1],
                                                              mg.HORIZON - int(ticks[i[k]])) for k in range(pairs)]))
        vi, vj = th.as_tensor(v3[i], dtype=th.float32), th.as_tensor(v3[j], dtype=th.float32)
        h_base = policy.features(vi, feat_i)["h2"]
        h_goal = policy.features(vi, feat_i_other)["h2"]
        h_state = policy.features(vj, feat_i)["h2"]
        d_goal = float((h_base - h_goal).norm(dim=-1).mean())
        d_state = float((h_base - h_state).norm(dim=-1).mean())
        ps0, pb0 = (th.softmax(x, -1) for x in policy(vi, feat_i))
        ps1, pb1 = (th.softmax(x, -1) for x in policy(vi, feat_i_other))
        tv = float(0.5 * ((ps0 - ps1).abs().sum(-1) + (pb0 - pb1).abs().sum(-1)).mean() / 2.0)
    ratio = d_goal / d_state if d_state > 0 else float("inf")
    return {"states": int(m), "pairs": int(pairs), "goal_pool": len(goal_pool),
            "trunk_saturation": round(float((f["h1"].abs() > SATURATION).float().mean()), 4),
            "goal_branch_saturation": round(float((f["g1"].abs() > SATURATION).float().mean()), 4),
            "joint_saturation": round(float((f["h2"].abs() > SATURATION).float().mean()), 4),
            "goal_share_of_joint_preactivation": round(share, 4),
            "joint_change_goal_swap": round(d_goal, 5), "joint_change_state_swap": round(d_state, 5),
            "goal_state_sensitivity_ratio": round(ratio, 4),
            "sensitivity_in_registered_range": bool(SENSITIVITY_RANGE[0] <= ratio <= SENSITIVITY_RANGE[1]),
            "action_tv_goal_swap": round(tv, 6), "goal_gain": GOAL_GAIN}


init_diagnostics = goal_sensitivity     # the initialisation check uses the same measurement


def contract_description() -> Dict[str, Any]:
    return {"contract": POLICY_CONTRACT, "v3_dim": V3_DIM, "goal_dim": mg.GOAL_DIM, "trunk": TRUNK,
            "goal_units": GOAL_UNITS, "joint": JOINT, "heads": [STICK_STATES, BUTTON_STATES], "activation": "tanh",
            "init": {"orthogonal_gain": GAIN, "goal_gain": GOAL_GAIN, "head_gain": HEAD_GAIN, "bias": 0.0,
                     "generator": "torch.Generator seeded with sha256('m7s1|init|seed')"},
            "training": {"loss": "cross-entropy stick + button", "optimizer": "Adam", "learning_rate": LEARNING_RATE,
                         "batch": BATCH, "steps_per_chunk": STEPS_PER_CHUNK, "chunk_ticks": CHUNK_TICKS,
                         "max_grad_norm": MAX_GRAD_NORM},
            "sampling": "stochastic; inverse CDF with two uniforms per tick from the episode's registered generator",
            "sensitivity_range": list(SENSITIVITY_RANGE), "goal_blind_tv": GOAL_BLIND_TV}


def contract_digest() -> str:
    import json

    return hashlib.sha256(json.dumps(contract_description(), sort_keys=True).encode("utf-8")).hexdigest()
