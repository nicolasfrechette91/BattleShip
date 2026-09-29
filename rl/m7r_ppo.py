"""M7r: semi-Markov PPO for the commitment action contract (opt-in; the per-tick arm keeps M7PPO unchanged).

Design: docs/rl_temporal_control_design_2026-09-28.md, revision 3, section 4.

    R_j = sum_{i < tau_j} gamma^i r_{t_j + i}                           (per-tick rewards of decision j)
    delta_j = R_j + gamma^tau_j V(s_{j+1}) (1 - done_j) - V(s_j)          (truncation: gamma^tau V(terminal) in R_j)
    A_j = delta_j + (gamma lambda)^tau_j (1 - done_j) A_{j+1};  returns = A + V

with the per-tick gamma = 0.999 and lambda = 0.995 of M7n, so every tau = 1 is SB3's per-tick PPO exactly
(`self_test` checks this against SB3's own buffer). This keeps the baseline's credit horizon in game time; it does not
by itself solve delayed credit across a long crossing.

Native-tick accounting: `n_steps` is the number of native ticks each environment contributes per rollout (1,024).
At the start of every rollout each worker's executor receives that quota (`commit_begin_rollout`); the option that
would cross it ends at it (reason rollout_boundary); a worker whose quota is used up answers further vector steps with
an idle reply (no request sent, no tick consumed) that is never stored. `num_timesteps` counts native ticks, so
checkpoints, budgets and the M7 callbacks see exactly the per-tick arm's tick counts. Every rollout keeps 100 gradient
steps (10 near-equal minibatches x 10 epochs, whatever the number of decisions).
"""
from __future__ import annotations

import math
from typing import Any, Dict, Generator, List, Optional, Sequence, Tuple

import numpy as np
import torch as th
from gymnasium import spaces
from stable_baselines3.common.buffers import BaseBuffer
from stable_baselines3.common.type_aliases import DictRolloutBufferSamples
from stable_baselines3.common.utils import obs_as_tensor

import m7r_commit as mc
from m7_trainer import M7PPO

ACCOUNTING_SCHEMA = "btt_commit_rollout_accounting_v1"


def smdp_gae(rewards: Sequence[float], values: Sequence[float], taus: Sequence[int], dones: Sequence[bool],
             last_value: float, gamma: float, lam: float) -> Tuple[np.ndarray, np.ndarray]:
    """Advantages and returns of ONE environment's decision sequence (in order). `dones[j]` = decision j ended its
    episode (the next stored decision starts a new one); `last_value` = V of the observation after the last one."""
    n = len(rewards)
    adv = np.zeros(n, dtype=np.float32)
    last = 0.0
    for j in reversed(range(n)):
        nonterminal = 0.0 if dones[j] else 1.0
        next_v = last_value if j == n - 1 else float(values[j + 1])
        g = gamma ** int(taus[j])
        delta = float(rewards[j]) + g * next_v * nonterminal - float(values[j])
        last = delta + g * (lam ** int(taus[j])) * nonterminal * last
        adv[j] = last
    return adv, adv + np.asarray(values, dtype=np.float32)


def discounted_decision_reward(tick_rewards: Sequence[float], gamma: float) -> float:
    return float(sum((gamma ** i) * float(r) for i, r in enumerate(tick_rewards)))


class SMDPDictRolloutBuffer(BaseBuffer):
    """Variable number of decisions per environment; GAE per environment sequence; flat minibatches like SB3's
    DictRolloutBuffer (random permutation from NumPy's global generator, as SB3 does)."""

    def __init__(self, buffer_size: int, observation_space: spaces.Space, action_space: spaces.Space,
                 device: Any = "auto", gae_lambda: float = 1.0, gamma: float = 0.99, n_envs: int = 1):
        super().__init__(buffer_size, observation_space, action_space, device, n_envs=n_envs)
        self.gamma, self.gae_lambda = gamma, gae_lambda
        self.minibatches: Optional[int] = None   # CommitPPO.train: exactly this many minibatches per epoch
        self.reset()

    def reset(self) -> None:
        super().reset()
        self.per_env: List[Dict[str, list]] = [{"obs": [], "actions": [], "rewards": [], "taus": [], "dones": [],
                                                "values": [], "log_probs": []} for _ in range(self.n_envs)]
        self.size = 0
        self.generator_ready = False
        self.observations: Dict[str, np.ndarray] = {}
        self.actions = self.values = self.log_probs = self.advantages = self.returns = np.zeros(0, dtype=np.float32)
        self.taus = np.zeros(0, dtype=np.int64)

    def add_decision(self, env: int, obs: Dict[str, np.ndarray], action: np.ndarray, reward: float, tau: int,
                     done: bool, value: float, log_prob: float) -> None:
        e = self.per_env[env]
        e["obs"].append({k: np.array(v, copy=True) for k, v in obs.items()})
        e["actions"].append(np.array(action, copy=True))
        e["rewards"].append(float(reward))
        e["taus"].append(int(tau))
        e["dones"].append(bool(done))
        e["values"].append(float(value))
        e["log_probs"].append(float(log_prob))
        self.size += 1

    def compute_returns_and_advantage(self, last_values: Sequence[float]) -> None:
        obs_keys = list(self.observation_space.spaces.keys())  # type: ignore[attr-defined]
        adv_all, ret_all, parts = [], [], {k: [] for k in ("actions", "values", "log_probs", "taus")}
        obs_parts: Dict[str, list] = {k: [] for k in obs_keys}
        for i, e in enumerate(self.per_env):
            if not e["rewards"]:
                continue
            adv, ret = smdp_gae(e["rewards"], e["values"], e["taus"], e["dones"], float(last_values[i]),
                                self.gamma, self.gae_lambda)
            adv_all.append(adv)
            ret_all.append(ret)
            parts["actions"].append(np.stack(e["actions"]))
            parts["values"].append(np.asarray(e["values"], dtype=np.float32))
            parts["log_probs"].append(np.asarray(e["log_probs"], dtype=np.float32))
            parts["taus"].append(np.asarray(e["taus"], dtype=np.int64))
            for k in obs_keys:
                obs_parts[k].append(np.stack([o[k] for o in e["obs"]]))
        self.advantages = np.concatenate(adv_all).astype(np.float32)
        self.returns = np.concatenate(ret_all).astype(np.float32)
        self.actions = np.concatenate(parts["actions"])
        self.values = np.concatenate(parts["values"])
        self.log_probs = np.concatenate(parts["log_probs"])
        self.taus = np.concatenate(parts["taus"])
        self.observations = {k: np.concatenate(v).astype(np.float32) for k, v in obs_parts.items()}
        self.full = True
        self.generator_ready = True

    def get(self, batch_size: Optional[int] = None) -> Generator[DictRolloutBufferSamples, None, None]:
        assert self.full and self.generator_ready, "compute_returns_and_advantage first"
        n = len(self.advantages)
        indices = np.random.permutation(n)
        if self.minibatches is not None:   # exactly k near-equal minibatches (sizes differ by at most one)
            for chunk in np.array_split(indices, min(int(self.minibatches), n)):
                yield self._get_samples(chunk)
            return
        batch_size = n if batch_size is None else int(batch_size)
        start = 0
        while start < n:
            yield self._get_samples(indices[start:start + batch_size])
            start += batch_size

    def _get_samples(self, batch_inds: np.ndarray, env: Any = None) -> DictRolloutBufferSamples:  # type: ignore[override]
        return DictRolloutBufferSamples(
            observations={k: self.to_torch(v[batch_inds]) for k, v in self.observations.items()},
            actions=self.to_torch(self.actions[batch_inds].astype(np.float32, copy=False)),
            old_values=self.to_torch(self.values[batch_inds].flatten()),
            old_log_prob=self.to_torch(self.log_probs[batch_inds].flatten()),
            advantages=self.to_torch(self.advantages[batch_inds].flatten()),
            returns=self.to_torch(self.returns[batch_inds].flatten()),
        )


class CommitPPO(M7PPO):
    """M7PPO with semi-Markov rollouts over the commitment executor (see the module docstring)."""

    m7r_minibatches: int = 10

    def __init__(self, *args: Any, m7r_minibatches: int = 10, **kwargs: Any):
        kwargs.setdefault("rollout_buffer_class", SMDPDictRolloutBuffer)
        super().__init__(*args, **kwargs)
        self.m7r_minibatches = int(m7r_minibatches)
        self.m7r_rollouts: List[Dict[str, Any]] = []
        self.m7r_cumulative = {"ticks": 0, "decisions": 0, "gradient_steps": 0, "optimizer_samples": 0}

    def _excluded_save_params(self) -> List[str]:
        return super()._excluded_save_params() + ["m7r_rollouts", "m7r_cumulative"]

    # -- collection ---------------------------------------------------------------------------------------------

    def collect_rollouts(self, env: Any, callback: Any, rollout_buffer: Any, n_rollout_steps: int) -> bool:
        assert self._last_obs is not None, "No previous observation was provided"
        if not isinstance(rollout_buffer, SMDPDictRolloutBuffer):
            raise mc.CommitError("CommitPPO needs the SMDPDictRolloutBuffer")
        self.policy.set_training_mode(False)
        n_envs = env.num_envs
        quota = int(n_rollout_steps)
        rollout_buffer.reset()
        env.env_method("commit_begin_rollout", quota)
        callback.on_rollout_start()
        ticks = np.zeros(n_envs, dtype=np.int64)
        decisions = np.zeros(n_envs, dtype=np.int64)
        idle = 0
        last_done = np.zeros(n_envs, dtype=bool)
        tau_hist: Dict[int, int] = {}
        reasons: Dict[str, int] = {}
        d_use: Dict[int, int] = {}
        mode_use: Dict[str, int] = {m: 0 for m in mc.MODES}
        while (ticks < quota).any():
            with th.no_grad():
                obs_tensor = obs_as_tensor(self._last_obs, self.device)  # type: ignore[arg-type]
                actions, values, log_probs = self.policy(obs_tensor)
            actions = actions.cpu().numpy()
            new_obs, rewards, dones, infos = env.step(actions)
            stepped = 0
            for i in range(n_envs):
                c = infos[i].get("commit") or {}
                if c.get("idle"):
                    if ticks[i] < quota:
                        raise mc.CommitError(f"env {i} answered idle with {quota - ticks[i]} ticks of quota left")
                    idle += 1
                    continue
                if ticks[i] >= quota:
                    raise mc.CommitError(f"env {i} consumed ticks beyond its rollout quota")
                tau = int(c["tau"])
                reward = discounted_decision_reward(c["tick_rewards"], self.gamma)
                if abs(sum(c["tick_rewards"]) - float(rewards[i])) > 1e-6:
                    raise mc.CommitError(f"env {i}: per-tick rewards do not sum to the decision reward")
                if dones[i] and infos[i].get("terminal_observation") is not None \
                        and infos[i].get("TimeLimit.truncated", False):
                    terminal_obs = self.policy.obs_to_tensor(infos[i]["terminal_observation"])[0]
                    with th.no_grad():
                        terminal_value = float(self.policy.predict_values(terminal_obs)[0])  # type: ignore[arg-type]
                    reward += (self.gamma ** tau) * terminal_value
                obs_i = {k: v[i] for k, v in self._last_obs.items()}  # type: ignore[union-attr]
                rollout_buffer.add_decision(i, obs_i, actions[i], reward, tau, bool(dones[i]), float(values[i]),
                                            float(log_probs[i]))
                ticks[i] += tau
                decisions[i] += 1
                stepped += tau
                last_done[i] = bool(dones[i])
                tau_hist[tau] = tau_hist.get(tau, 0) + 1
                reasons[str(c["reason"])] = reasons.get(str(c["reason"]), 0) + 1
                opt = c.get("option") or {}
                d_use[int(opt.get("d", 0))] = d_use.get(int(opt.get("d", 0)), 0) + 1
                mode_use[str(opt.get("mode"))] = mode_use.get(str(opt.get("mode")), 0) + 1
            self.num_timesteps += stepped
            callback.update_locals(locals())
            if not callback.on_step():
                return False
            self._update_info_buffer([inf for inf in infos if not (inf.get("commit") or {}).get("idle")],
                                     np.array([d for d, inf in zip(dones, infos)
                                               if not (inf.get("commit") or {}).get("idle")]))
            self._last_obs = new_obs  # type: ignore[assignment]
            self._last_episode_starts = dones
        if (ticks != quota).any():
            raise mc.CommitError(f"rollout tick accounting: {ticks.tolist()} != {quota} per environment")
        left = env.env_method("commit_end_rollout")
        if any(int(v) != 0 for v in left):
            raise mc.CommitError(f"executor quotas not used up at the rollout end: {left}")
        with th.no_grad():
            last_values = self.policy.predict_values(obs_as_tensor(self._last_obs, self.device))  # type: ignore[arg-type]
        lv = last_values.cpu().numpy().flatten()
        lv = np.where(last_done, 0.0, lv)   # a decision that ended its episode never bootstraps into the next one
        rollout_buffer.compute_returns_and_advantage(lv)
        n_dec = int(decisions.sum())
        self.m7r_last_rollout = {
            "schema": ACCOUNTING_SCHEMA,
            "native_ticks": int(ticks.sum()), "native_ticks_per_env": ticks.tolist(),
            "decisions": n_dec, "decisions_per_env": decisions.tolist(), "idle_replies": idle,
            "tau_histogram": {str(k): v for k, v in sorted(tau_hist.items())},
            "tau_mean": round(float(ticks.sum()) / max(1, n_dec), 4),
            "end_reasons": dict(sorted(reasons.items())), "d_usage": {str(k): v for k, v in sorted(d_use.items())},
            "mode_usage": mode_use,
        }
        callback.update_locals(locals())
        callback.on_rollout_end()
        return True

    # -- optimisation ---------------------------------------------------------------------------------------------

    def train(self) -> None:
        n = len(self.rollout_buffer.advantages)
        k = min(self.m7r_minibatches, n)
        self.rollout_buffer.minibatches = k
        n_updates_before = self._n_updates
        try:
            super().train()
        finally:
            self.rollout_buffer.minibatches = None
        epochs_run = self._n_updates - n_updates_before
        steps_per_epoch = k
        rec = dict(getattr(self, "m7r_last_rollout", {}) or {})
        rec.update({"minibatch_size_min": n // k, "minibatch_size_max": math.ceil(n / k),
                    "minibatches_per_epoch": steps_per_epoch, "epochs": epochs_run,
                    "gradient_steps": steps_per_epoch * epochs_run,
                    "optimizer_samples": n * epochs_run})
        c = self.m7r_cumulative
        c["ticks"] += int(rec.get("native_ticks", 0))
        c["decisions"] += int(rec.get("decisions", n))
        c["gradient_steps"] += rec["gradient_steps"]
        c["optimizer_samples"] += rec["optimizer_samples"]
        rec["cumulative"] = dict(c)
        self.m7r_rollouts.append(rec)
        self.m7r_last_rollout = rec


def per_tick_accounting(n_envs: int, n_steps: int, batch_size: int, n_epochs: int, cumulative: Dict[str, int]
                        ) -> Dict[str, Any]:
    """The same accounting record for a per-tick (M7PPO) rollout: every decision is one tick."""
    n = n_envs * n_steps
    steps_per_epoch = math.ceil(n / batch_size)
    cumulative["ticks"] += n
    cumulative["decisions"] += n
    cumulative["gradient_steps"] += steps_per_epoch * n_epochs
    cumulative["optimizer_samples"] += n * n_epochs
    return {"schema": ACCOUNTING_SCHEMA, "native_ticks": n, "native_ticks_per_env": [n_steps] * n_envs,
            "decisions": n, "decisions_per_env": [n_steps] * n_envs, "idle_replies": 0,
            "tau_histogram": {"1": n}, "tau_mean": 1.0, "minibatch_size": batch_size,
            "minibatches_per_epoch": steps_per_epoch, "epochs": n_epochs,
            "gradient_steps": steps_per_epoch * n_epochs, "optimizer_samples": n * n_epochs,
            "cumulative": dict(cumulative)}
