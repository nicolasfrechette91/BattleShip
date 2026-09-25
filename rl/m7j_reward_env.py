#!/usr/bin/env python3
"""M7j: the btt_reward_v3 reward wrapper of an M7 worker (opt-in; built only by btt_parallel.make_reward_wrapper when a
worker's contract is btt_reward_v3).

It sits exactly where M7RewardWrapper sits (directly on the M7 base environment, below the M4 recorder and Track 1) and
replaces its arithmetic with btt_reward_v3.RouteRewardState. Everything else is M7RewardWrapper's: the same info keys,
the same tracker hook, the same episode counters, the same EpisodeFailure propagation (a lifecycle failure reaches
the learner as Track 1's truncation with reward 0.0 and never reaches this arithmetic).

The route terms need two native facts M7RewardWrapper does not read:
* the target identity of every step: the M7f diagnostic's `targets` object in the raw step reply
  (SSB64_RL_TARGET_DIAG=1, read-only, gameplay-neutral by M7f's strict equivalence), read through an instance-level
  shadow of the episode client's `request` (the rl/m7g_eval_metrics.py pattern);
* the tick-0 target table: one extra NON-CONSUMING `observe` per reset (no tick, no clock; checked equal to the reset
  observation).
Nothing here enters the policy observation: btt_policy_obs_v1 is built from the M3 observation above this wrapper and
is unchanged. The per-episode v3 record travels in info["reward_v3_episode"] on the episode's last step and lands in
the worker's episode summary and artifact labels (key `reward_v3`).
"""
from __future__ import annotations

import dataclasses
from typing import Any, Dict, Mapping, Optional

import btt_parallel as bp
from btt_learning import live_targets
from btt_reward_v3 import RewardV3Violation, RouteRewardState
from btt_rewards import RewardContract, is_route_contract, reward_extra_env


class RouteRewardWiringError(RuntimeError):
    """The wrapper cannot pair a raw reply with the step (a wiring defect, never a gameplay fact)."""


class M7RouteRewardWrapper(bp.M7RewardWrapper):
    route_capable = True

    def __init__(self, env: Any, contract: RewardContract, tracker: Optional["bp.M7EpisodeTracker"] = None, *,
                 extra_env: Mapping[str, str]):
        if not is_route_contract(contract):
            raise ValueError(f"M7RouteRewardWrapper needs btt_reward_v3, got {contract.contract}")
        missing = [f"{k}={v}" for k, v in reward_extra_env(contract) if dict(extra_env).get(k) != v]
        if missing:
            raise ValueError(f"{contract.contract} needs the native flag(s) {missing} in every worker process")
        horizon = getattr(env, "max_episode_steps", None)
        if horizon != int(contract.horizon_ticks):
            raise ValueError(f"{contract.contract} is defined for a {contract.horizon_ticks}-tick horizon, "
                             f"not {horizon}")
        super().__init__(env, contract, tracker)
        self.state: Optional[RouteRewardState] = None
        self.last_record: Optional[Dict[str, Any]] = None
        self._client: Any = None
        self._last_step_reply: Optional[Dict[str, Any]] = None

    def _capture(self, client: Any) -> None:
        if self._client is client:
            return
        original = client.request

        def request(op: str, **payload: Any) -> Dict[str, Any]:
            reply = original(op, **payload)
            if op == "step":
                self._last_step_reply = reply
            return reply

        client.request = request
        self._client = client

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        self.state = None
        observation, info = super().reset(seed=seed, options=options)
        base = self.env
        episode = base.episode
        if episode is None or episode.client is None:
            raise RouteRewardWiringError("no active episode after reset")
        self._capture(episode.client)
        reply = episode.client.request("observe")          # non-consuming: no tick, no clock
        reset_obs = dataclasses.asdict(base.last_observe.observation)
        if reply.get("ok") is not True or reply.get("observation") != reset_obs:
            raise RouteRewardWiringError(f"the v3 re-observe does not match the reset observation "
                                         f"({reply.get('observation')} vs {reset_obs})")
        from btt_reward_t2 import make_route_state    # M7k: v3's own state for v3, its subclass for btt_reward_v3_t2

        self.state = make_route_state(self.reward_contract)
        self.state.start(reply)
        self._last_step_reply = None
        self.last_record = None
        return observation, info

    def rebase_for_policy_phase(self, observation: Mapping[str, Any]) -> int:
        raise RouteRewardWiringError("btt_reward_v3 is registered for tick-0 starts only (no prefix phase / curriculum)")

    def step(self, action: Any):
        if self.state is None:
            raise RouteRewardWiringError("step before a successful reset")
        self._last_step_reply = None
        observation, _placeholder, terminated, truncated, info = self.env.step(action)  # EpisodeFailure propagates
        reply = self._last_step_reply
        result = self.env.last_step_result
        if reply is None or result is None or reply.get("step_count") != result.step_count:
            raise RouteRewardWiringError("no raw step reply paired with the step result")
        current = live_targets(observation)
        if current is not None and int(reply["observation"]["targets_remaining"]) != current:
            raise RewardV3Violation("the raw reply and the M3 observation disagree on targets_remaining")
        reason = info.get("termination_reason") if terminated else None
        terms = self.state.step(reply, clear=reason == bp.TERMINATION_NATIVE_CLEAR,
                                native_failure=reason == bp.TERMINATION_NATIVE_FAILURE)
        self._previous_targets = current
        self.last_breakdown = terms.m5_breakdown()
        self.episode_return += terms.total
        self.episode_steps += 1
        self.episode_targets_broken += terms.newly_broken
        if terms.failure_term:
            self.episode_failure_terms += 1
        info["reward_contract"] = self.reward_contract.contract
        info["reward_terms"] = terms.to_json()
        info["episode_return"] = self.episode_return
        info["episode_targets_broken"] = self.episode_targets_broken
        if terminated or truncated:
            self.last_record = self.state.record()
            info["reward_v3_episode"] = self.last_record
        if self.tracker is not None:
            self.tracker.note_step(terms, terminated, truncated, info)
        return observation, terms.total, terminated, truncated, info
