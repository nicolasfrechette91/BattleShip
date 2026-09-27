#!/usr/bin/env python3
"""M7o: the exploration-credit reward wrapper of an M7 worker (opt-in; built by btt_parallel.make_reward_wrapper only
when the worker spec carries an [exploration] table).

It sits exactly where M7RewardWrapper sits (directly on the M7 base environment) and keeps M7RewardWrapper's contract
arithmetic untouched: the btt_reward_v2 terms, the tracker's `return` (the contract return, still equal to the v2
closed form), the artifact labels and the episode rows are what they were. It ADDS the btt_explore_cells_v1 credit
(rl/btt_explore_cells.py) to the reward the learner receives and logs it separately:

  info["reward_terms"]        the contract terms (unchanged)
  info["explore_terms"]       this step's credit accounting (banked, pending_added, voided, capped, ...)
  info["learner_reward"]      contract total + banked credit (what the step returns as its reward)
  info["explore_episode"]     the per-episode record on the episode's last step -> episode summary / row key `explore`
                              and artifact labels `explore`

Native facts it needs beyond the M3 observation: the stage's map bounds from the spatial diagnostic (SSB64_RL_SPATIAL=1),
read from one extra NON-CONSUMING `observe` per reset (checked equal to the reset observation; the rl/m7j_reward_env.py
pattern), and the action class of the fighter status (the v3 action-class table). The table of visit counts belongs to
this worker slot: it is written after every episode to <worker_dir>/explore_table.json and reloaded when a worker of the
same run directory is constructed again; game-process restarts and standby promotions never touch it.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import btt_explore_cells as xp
import btt_parallel as bp
import m7n_status_table as st
from btt_learning import live_targets
from btt_rewards import RewardContract, is_route_contract, reward_step

ROW_KEY = "explore"
TABLE_FILE = "explore_table.json"


class ExploreWiringError(RuntimeError):
    """The wrapper cannot pair a raw reply with the step or is built on the wrong stack (a defect, never a gameplay fact)."""


class M7ExploreRewardWrapper(bp.M7RewardWrapper):
    def __init__(self, env: Any, contract: RewardContract, tracker: Optional["bp.M7EpisodeTracker"] = None, *,
                 settings: Mapping[str, Any], extra_env: Mapping[str, str], character: str, worker_dir: Path, rank: int):
        if is_route_contract(contract) or contract.contract != "btt_reward_v2":
            raise ExploreWiringError(f"{xp.CONTRACT_ID} is registered on btt_reward_v2 only, not {contract.contract}")
        missing = [f"{k}={v}" for k, v in xp.REQUIRED_EXTRA_ENV if dict(extra_env).get(k) != v]
        if missing:
            raise ExploreWiringError(f"{xp.CONTRACT_ID} needs the native flag(s) {missing} in every worker process")
        super().__init__(env, contract, tracker)
        self.explore = xp.check_settings(settings)
        self.classifier = st.ActionClassifier(st.load_table(), character)
        self.rank = int(rank)
        self.table_path = Path(worker_dir) / TABLE_FILE
        if self.table_path.is_file():          # the same run's worker constructed again (resume): continue the slot's table
            self.table = xp.ExploreTable.load(self.table_path, self.explore)
            if self.table.rank not in (None, self.rank):
                raise ExploreWiringError(f"{self.table_path} belongs to rank {self.table.rank}, this worker is rank {self.rank}")
            self.table.rank = self.rank
        else:
            self.table = xp.ExploreTable(self.explore, rank=self.rank)
        self.episode: Optional[xp.ExploreEpisode] = None
        self.last_record: Optional[Dict[str, Any]] = None
        self.map_bounds: Optional[list] = None
        self._client: Any = None
        self.episode_explore_bonus = 0.0
        self.last_terms: Any = None                 # the contract terms of the last step (M7WorkerWrapper slims step info)
        self.last_explore_step: Optional[xp.ExploreStep] = None

    def _observe_bounds(self, episode: Any, base: Any) -> None:
        reply = episode.client.request("observe")          # non-consuming: no tick, no clock
        reset_obs = dataclasses.asdict(base.last_observe.observation)
        if reply.get("ok") is not True or reply.get("observation") != reset_obs:
            raise ExploreWiringError(f"the exploration re-observe does not match the reset observation "
                                     f"({reply.get('observation')} vs {reset_obs})")
        spatial = reply.get("spatial")
        if not isinstance(spatial, Mapping) or "map_bounds" not in spatial:
            raise ExploreWiringError("the observe reply carries no spatial.map_bounds (SSB64_RL_SPATIAL=1 required)")
        bounds = [int(v) for v in spatial["map_bounds"]]
        if self.map_bounds is not None and bounds != self.map_bounds:
            raise ExploreWiringError(f"map bounds changed between episodes: {self.map_bounds} -> {bounds}")
        self.map_bounds = bounds

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        self.episode = None
        self.last_record = None
        self.episode_explore_bonus = 0.0
        observation, info = super().reset(seed=seed, options=options)
        base = self.env
        episode = base.episode
        if episode is None or episode.client is None:
            raise ExploreWiringError("no active episode after reset")
        self._observe_bounds(episode, base)
        self.episode = xp.ExploreEpisode.start(dict(observation), self.map_bounds, self.table, self.explore)
        info["explore_contract"] = xp.CONTRACT_ID
        info["explore_cell_size"] = self.episode.size
        info["explore_table_episodes"] = self.table.episodes
        return observation, info

    def rebase_for_policy_phase(self, observation: Mapping[str, Any]) -> int:
        raise ExploreWiringError(f"{xp.CONTRACT_ID} is registered for tick-0 starts only (no prefix phase / curriculum)")

    def step(self, action: Any):
        if self.episode is None:
            raise ExploreWiringError("step before a successful reset")
        observation, _placeholder, terminated, truncated, info = self.env.step(action)  # EpisodeFailure propagates
        reason = info.get("termination_reason") if terminated else None
        clear = reason == bp.TERMINATION_NATIVE_CLEAR
        native_failure = reason == bp.TERMINATION_NATIVE_FAILURE
        current = live_targets(observation)
        terms = reward_step(self._previous_targets, current, clear=clear, native_failure=native_failure,
                            contract=self.reward_contract)
        self._previous_targets = current
        self.last_breakdown = terms.m5_breakdown()
        self.episode_return += terms.total
        self.episode_steps += 1
        self.episode_targets_broken += terms.newly_broken
        if terms.failure_term:
            self.episode_failure_terms += 1
        status = int(observation.get("fighter_status_id", -1)) if int(observation.get("fighter_valid", 0)) == 1 else -1
        cls = self.classifier.name(status) if status >= 0 else "unmapped"
        xs = self.episode.step(dict(observation), cls, consumed_tick=info.get("consumed_tick"),
                               native_failure=native_failure, episode_end=bool(terminated or truncated))
        self.episode_explore_bonus += xs.banked
        self.last_terms, self.last_explore_step = terms, xs
        learner_reward = terms.total + xs.banked
        info["reward_contract"] = self.reward_contract.contract
        info["reward_terms"] = terms.to_json()
        info["episode_return"] = self.episode_return
        info["episode_targets_broken"] = self.episode_targets_broken
        info["explore_terms"] = xs.to_json()
        info["learner_reward"] = learner_reward
        info["episode_explore_bonus"] = self.episode_explore_bonus
        if terminated or truncated:
            self.last_record = dict(self.episode.record(), rank=self.rank, learner_return=round(self.episode_return + self.episode_explore_bonus, 6),
                                    contract_return=round(self.episode_return, 6))
            info["explore_episode"] = self.last_record
            self.last_record["table_sha256"] = self.table.save(self.table_path)
            self.last_record["table_episodes_after"] = self.table.episodes
        if self.tracker is not None:
            self.tracker.note_step(terms, terminated, truncated, info)
        return observation, learner_reward, terminated, truncated, info
