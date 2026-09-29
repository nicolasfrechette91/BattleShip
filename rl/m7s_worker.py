"""M7s stage 1: the goal worker stack (opt-in; every earlier stack is unchanged).

    M7BattleShipBTTEnv -> GoalProbeWrapper -> M7RewardWrapper (v2) -> EpisodeRecordingWrapper -> Track1PolicyWrapper
    -> EntityObsV3Wrapper -> GoalObsWrapper -> EpisodeStatsWrapper -> M7sWorkerWrapper

GoalProbeWrapper sits directly above the native environment, below the reward wrapper and the M4 recorder, so the two
Python-side episode ends it may declare (`goal_reached` in evaluation, `tick_quota` in collection) are recorded as
ordinary truncations with their native words preserved (the tracker labels them end_reason `horizon`; every consumer
distinguishes them by truncation_reason). It reads the raw reply of the step the v3 wrapper captured, never sends
anything and never changes an action. Return success is the FIRST VALID REACH of the commanded cell (with its contact
class): a live tick inside the box, before the horizon, that is not the tick on which a native-failure (fatal) fall
ends the episode (a reach on a native-clear tick is a clear, not a return). An evaluation episode ends on that tick.
GoalObsWrapper appends the 14-value goal vector (btt_goal_obs_v3_v1) to the unchanged v3 observation, commands goals
from the matched schedule (collection: the next goal on the tick of a reach) or the evaluation plan, enforces episode /
tick quotas with idle replies (no request, no tick) and writes the per-episode sidecar `m7s_goals.json.gz` (commanded
goals, reach ticks, per-tick achieved cells, and the NON-DECISIVE 120-tick survival diagnostic of collection reaches)
into the artifact directory. Every episode starts with the environment's normal reset at tick 0.
"""
from __future__ import annotations

import gzip
import json
import random
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import gymnasium as gym
import numpy as np

import btt_parallel as bp
import m7n_obs as mn
import m7s_goal as mg

GOAL_KEY = "goal"
MODES = ("null", "schedule", "plan")
END_GOAL = mg.END_GOAL
END_QUOTA = mg.END_QUOTA


class GoalProbeWrapper(gym.Wrapper):
    def __init__(self, env: Any, *, base: Any):
        super().__init__(env)
        self.base = base
        self.reply_source: Any = None          # set after construction: the v3 wrapper's capture of this step
        self.commanded: Optional[mg.Cell] = None
        self.end_on_success = False
        self.tick_quota: Optional[int] = None  # remaining consumed ticks of this worker's phase quota
        self.ticks = 0
        self.reach_tick: Optional[int] = None
        self.last: Optional[Dict[str, Any]] = None

    def command(self, goal: Optional[mg.Cell]) -> None:
        self.commanded = goal
        self.reach_tick = None

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        obs, info = self.env.reset(seed=seed, options=options)
        self.ticks = 0
        self.reach_tick = None
        self.last = None
        return obs, info

    def step(self, action: Any):
        obs, reward, terminated, truncated, info = self.env.step(action)   # an EpisodeFailure propagates: no tick
        self.ticks += 1
        reply = self.reply_source() if self.reply_source is not None else None
        if not reply or reply.get("op") != "step":
            raise mg.GoalContractError("no raw step reply for the consumed tick")
        state = mg.reply_state(reply)
        cell = mg.state_cell(state)
        reason = info.get("termination_reason") if terminated else None
        fell = reason == bp.TERMINATION_NATIVE_FAILURE
        clear = reason == bp.TERMINATION_NATIVE_CLEAR
        valid = cell is not None and not fell
        reached = bool(self.commanded is not None and self.reach_tick is None and valid and not clear
                       and cell == self.commanded)
        if reached:
            self.reach_tick = self.ticks
        ended_by = None
        if self.tick_quota is not None:
            self.tick_quota -= 1
        if reached and self.end_on_success:
            # the first valid reach ends an evaluation episode on its own tick (also on the native horizon tick)
            truncated, ended_by = True, END_GOAL
        elif not (terminated or truncated) and self.tick_quota is not None and self.tick_quota <= 0:
            truncated, ended_by = True, END_QUOTA
        if ended_by is not None:
            info["truncation_reason"] = ended_by
        self.last = {"k": self.ticks, "cell": mg.cell_key(cell) if cell is not None else None,
                     "x": state["x"], "y": state["y"], "live": state["live"], "valid": valid, "fell": fell,
                     "reached": reached, "ended_by": ended_by}
        info["m7s_probe"] = self.last
        return obs, reward, terminated, truncated, info


class GoalObsWrapper(gym.Wrapper):
    def __init__(self, env: Any, *, probe: GoalProbeWrapper, v3: Any, tracker: Any, rank: int):
        super().__init__(env)
        spaces = dict(env.observation_space.spaces)
        spaces[GOAL_KEY] = gym.spaces.Box(low=-2.0, high=2.0, shape=(mg.GOAL_DIM,), dtype=np.float32)
        self.observation_space = gym.spaces.Dict(spaces)
        self.probe = probe
        self.v3 = v3
        self.tracker = tracker
        self.rank = int(rank)
        self.cfg: Optional[Dict[str, Any]] = None
        self.idle = False
        self.episodes_done = 0
        self.ordinal = 0
        self.goals: List[mg.Cell] = []
        self.goal_index = 0
        self.pos = (0.0, 0.0)
        self.cells: List[Optional[str]] = []
        self.log: Optional[Dict[str, Any]] = None
        self._cached: Optional[Dict[str, np.ndarray]] = None
        self.last_reset_record: Optional[Dict[str, Any]] = None
        self.last_step_record: Optional[Dict[str, Any]] = None
        self.totals = {"episodes": 0, "ticks": 0, "idle_steps": 0, "idle_resets": 0, "sidecars_written": 0,
                       "reached": 0}

    # -- control (env_method) -------------------------------------------------------------------------------------

    def m7s_configure(self, cfg: Mapping[str, Any]) -> bool:
        cfg = dict(cfg)
        if cfg.get("mode") not in MODES:
            raise mg.GoalContractError(f"mode {cfg.get('mode')!r}")
        if cfg["mode"] == "schedule" and not cfg.get("schedule"):
            raise mg.GoalContractError("schedule mode without a schedule")
        if cfg["mode"] == "plan" and not cfg.get("plan"):
            raise mg.GoalContractError("plan mode without plan entries")
        if (cfg.get("episode_quota") is None) == (cfg.get("tick_quota") is None):
            raise mg.GoalContractError("exactly one of episode_quota / tick_quota")
        if cfg["mode"] == "plan" and int(cfg["episode_quota"]) != len(cfg["plan"]):
            raise mg.GoalContractError("plan mode: episode_quota must equal the number of plan entries")
        self.cfg = cfg
        self.idle = False
        self.episodes_done = 0
        self.probe.end_on_success = bool(cfg.get("end_on_success", False))
        self.probe.tick_quota = None if cfg.get("tick_quota") is None else int(cfg["tick_quota"])
        return True

    def m7s_status(self) -> Dict[str, Any]:
        return {"rank": self.rank, "idle": self.idle, "episodes_done": self.episodes_done,
                "tick_quota_left": self.probe.tick_quota, "totals": dict(self.totals)}

    # -- Gymnasium API ------------------------------------------------------------------------------------------------

    def _obs(self, v3obs: Mapping[str, np.ndarray]) -> Dict[str, np.ndarray]:
        d = dict(v3obs)
        d[GOAL_KEY] = mg.goal_features(self.probe.commanded, self.pos[0], self.pos[1], mg.HORIZON - self.probe.ticks)
        self._cached = d
        return d

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        if self.cfg is None:
            raise mg.GoalContractError("m7s_configure before the first reset")
        if self.idle:
            self.totals["idle_resets"] += 1
            self.last_reset_record = {"idle": True, "rank": self.rank}
            return self._cached, {"m7s": self.last_reset_record}
        obs, info = self.env.reset(seed=seed, options=options)
        self.ordinal = int(self.tracker.episodes_started)
        state = mg.reply_state(self.v3._last_reply or {})
        self.pos = (state["x"], state["y"])
        mode = self.cfg["mode"]
        entry = None
        if mode == "schedule":
            row = self.cfg["schedule"].get(self.ordinal)
            if row is None:
                raise mg.GoalContractError(f"no schedule entry for rank {self.rank} episode {self.ordinal}")
            self.goals = [tuple(int(v) for v in c) for c in row]
        elif mode == "plan":
            entry = self.cfg["plan"][self.episodes_done]
            self.goals = [tuple(int(v) for v in entry["goal"])]
        else:
            self.goals = []
        self.goal_index = 0
        first = self.goals[0] if self.goals else None
        self.probe.command(first)
        self.cells = []
        self.log = {"schema": mg.SIDECAR_SCHEMA, "contract": mg.CELL_CONTRACT, "obs_contract": mg.OBS_CONTRACT,
                    "phase": self.cfg.get("phase"), "mode": mode, "rank": self.rank, "worker_episode": self.ordinal,
                    "plan_entry": None if entry is None else entry["entry"],
                    "commanded": ([{"cell": mg.cell_key(first), "set_tick": 0, "reach_tick": None,
                                    "survival_120": None}] if first else [])}
        out = self._obs(obs)
        self.last_reset_record = {"reset": True, "rank": self.rank, "worker_episode": self.ordinal,
                                  "plan_entry": self.log["plan_entry"], "goal": mg.cell_key(first) if first else None,
                                  "x": self.pos[0], "y": self.pos[1], "phase": self.cfg.get("phase")}
        info["m7s"] = self.last_reset_record
        return out, info

    def step(self, action: Any):
        if self.idle:
            self.totals["idle_steps"] += 1
            self.last_step_record = {"idle": True, "rank": self.rank}
            return self._cached, 0.0, False, False, {"m7s": self.last_step_record}
        obs, reward, terminated, truncated, info = self.env.step(action)
        probe = info.pop("m7s_probe", None)
        consumed = probe is not None
        if not consumed and info.get("truncation_reason") != "episode_failure":
            raise mg.GoalContractError("a step without the probe's record")
        events: List[str] = []
        if consumed:
            self.totals["ticks"] += 1
            self.cells.append(probe["cell"])
            self.pos = (probe["x"], probe["y"])
            k = probe["k"]
            # NON-DECISIVE survival diagnostic of earlier reaches (never changes success, archive or labels)
            for c in self.log["commanded"]:
                r = c.get("reach_tick")
                if r is not None and c.get("survival_120") is None and k > r:
                    if probe["fell"] and k - r <= mg.SURVIVAL_TICKS:
                        c["survival_120"] = False
                    elif k - r >= mg.SURVIVAL_TICKS:
                        c["survival_120"] = True
            cur = self.log["commanded"][-1] if self.log["commanded"] else None
            if probe["reached"] and cur is not None:
                cur["reach_tick"] = k
                self.totals["reached"] += 1
                events.append("reached")
                if self.cfg["mode"] == "schedule":
                    self.goal_index += 1
                    nxt = self.goals[self.goal_index] if self.goal_index < len(self.goals) else None
                    self.probe.command(nxt)
                    if nxt is not None:
                        self.log["commanded"].append({"cell": mg.cell_key(nxt), "set_tick": k, "reach_tick": None,
                                                      "survival_120": None})
        out = self._obs(obs)
        done = bool(terminated or truncated)
        rec = {"idle": False, "rank": self.rank, "worker_episode": self.ordinal, "consumed": consumed,
               "k": self.probe.ticks, "cell": probe["cell"] if consumed else None,
               "x": self.pos[0], "y": self.pos[1], "live": bool(probe["live"]) if consumed else False,
               "goal": mg.cell_key(self.probe.commanded) if self.probe.commanded else None, "events": events,
               "ended_by": probe["ended_by"] if consumed else None, "idle_next": False}
        if done:
            self._finish(terminated, truncated, info, probe)
            self.episodes_done += 1
            self.totals["episodes"] += 1
            q = self.cfg.get("episode_quota")
            if (q is not None and self.episodes_done >= int(q)) or \
                    (self.probe.tick_quota is not None and self.probe.tick_quota <= 0):
                self.idle = True
            rec["idle_next"] = self.idle
        self.last_step_record = rec
        info["m7s"] = rec
        return out, reward, terminated, truncated, info

    def _finish(self, terminated: bool, truncated: bool, info: Mapping[str, Any], probe: Optional[Mapping[str, Any]]):
        log = dict(self.log or {})
        log.update({"ticks": self.probe.ticks, "cells": list(self.cells),
                    "ended_by": probe.get("ended_by") if probe else info.get("truncation_reason"),
                    "terminated": bool(terminated), "truncated": bool(truncated),
                    "truncation_reason": info.get("truncation_reason") if truncated else None,
                    "termination_reason": info.get("termination_reason") if terminated else None,
                    "reached_any": any(c.get("reach_tick") is not None for c in log.get("commanded", []))})

        def build(summary: Mapping[str, Any]) -> Dict[str, Any]:
            extra: Dict[str, Any] = {"m7s": {k: v for k, v in log.items() if k != "cells"}}
            extra["m7s"]["sidecar"] = None
            if summary.get("preserved"):
                directory = Path(self.tracker.artifact_root) / str(summary["episode_id"])
                doc = dict(log, episode_id=str(summary["episode_id"]),
                           native_action_digest=summary.get("native_action_digest"),
                           goal_contract_sha256=mg.contract_digest())
                with gzip.open(directory / mg.SIDECAR_FILE, "wt", encoding="utf-8") as fp:
                    json.dump(doc, fp, separators=(",", ":"))
                extra["m7s"]["sidecar"] = mg.SIDECAR_FILE
                self.totals["sidecars_written"] += 1
            return extra

        self.tracker.extend_pending_summary(build)


class M7sWorkerWrapper(bp.M7WorkerWrapper):
    """M7WorkerWrapper plus the goal wrapper's per-step and reset records in the slim infos."""

    def __init__(self, env: Any, *, spec: Any, base: Any, tracker: Any, recording: Any, goal: GoalObsWrapper):
        super().__init__(env, spec=spec, base=base, tracker=tracker, recording=recording)
        self.goal = goal

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        observation, slim = super().reset(seed=seed, options=options)
        slim["m7s"] = self.goal.last_reset_record
        return observation, slim

    def step(self, action):
        observation, reward, terminated, truncated, slim = super().step(action)
        slim["m7s"] = self.goal.last_step_record
        return observation, reward, terminated, truncated, slim


def m7s_contracts(horizon: int, reward: Any, character: str = mn.DEFAULT_CHARACTER) -> Dict[str, Any]:
    c = dict(mn.m7n_contracts(horizon, reward, character))
    c.update({"goal_cell_contract": mg.CELL_CONTRACT, "goal_observation_contract": mg.OBS_CONTRACT,
              "gcsl_contract": mg.GCSL_CONTRACT, "goal_contract_sha256": mg.contract_digest(),
              "python_side_truncations": [END_GOAL, END_QUOTA]})
    return c


def build_worker_env_m7s(spec: Any) -> M7sWorkerWrapper:
    """The v3 stack of rl/m7n_obs.build_worker_env_v3 with the probe below the reward wrapper and the goal wrapper
    above the v3 wrapper (every other layer, argument and order identical)."""
    missing = [f"{k}={v}" for k, v in mn.ENTITY_EXTRA_ENV if dict(spec.extra_env).get(k) != v]
    if missing:
        raise ValueError(f"M7s worker spec needs {missing} in extra_env")
    if getattr(spec, "exploration", None) is not None or bp.is_route_contract(spec.reward_contract):
        raise ValueError("M7s workers use reward v1 / v2 without an exploration table")
    random.seed(spec.worker_seed)            # Python-side reproducibility only; never reaches the game
    np.random.seed(spec.worker_seed % (2 ** 32))
    character = mn.character_of(spec.experiment)
    paths = spec.paths()
    if not (paths["runtime"] / "runtime_manifest.json").is_file():
        raise RuntimeError(f"worker runtime directory not prepared: {paths['runtime']}")
    for key in ("episodes", "artifacts"):
        paths[key].mkdir(parents=True, exist_ok=True)
    launch = bp.LaunchConfig(
        executable=bp.Path(spec.executable), working_dir=paths["runtime"], run_root=paths["episodes"],
        startup_timeout=spec.startup_timeout, ready_timeout=spec.ready_timeout, request_timeout=spec.request_timeout,
        exit_timeout=spec.exit_timeout, extra_env=dict(spec.extra_env))
    ports = bp.PortCandidates(spec.rank, spec.port_block_base, spec.port_block_size)
    base = bp.M7BattleShipBTTEnv(launch, max_episode_steps=spec.horizon, rank=spec.rank, ports=ports,
                                 startup_attempts=spec.startup_attempts,
                                 detect_native_failure=spec.detect_native_failure,
                                 standby=spec.standby, generation_runtime_root=paths["runtime_gens"],
                                 profile=spec.profile(), standby_fault=spec.standby_fault,
                                 retain_failed_cap=spec.retain_failed_cap)
    probe = GoalProbeWrapper(base, base=base)
    tracker = mn._tracker_class(character, m7s_contracts)(
        run_id=spec.run_id, role=spec.role, rank=spec.rank, coordinator=bp.RunCoordinator(spec.coordination_dir),
        artifact_root=paths["artifacts"], ledger_path=paths["ledger"], env=base, reward=spec.reward_contract,
        retain_failed_cap=spec.retain_failed_cap, preserve_all=spec.preserve_all, experiment=spec.experiment)
    rewarded = bp.make_reward_wrapper(probe, spec, tracker)
    recording = bp.EpisodeRecordingWrapper(rewarded, paths["artifacts"],
                                           detectors=[bp.PositionDeltaDetector(spec.position_delta_threshold)],
                                           labels=tracker.labels_for_new_episode,
                                           on_episode_end=tracker.on_episode_end, targets_total=bp.TARGETS_TOTAL)
    track1 = bp.Track1PolicyWrapper(recording)
    v3 = mn.EntityObsV3Wrapper(track1, base=base, character=character)
    probe.reply_source = lambda: v3._last_reply
    goal = GoalObsWrapper(v3, probe=probe, v3=v3, tracker=tracker, rank=spec.rank)
    stats = bp.EpisodeStatsWrapper(goal)
    return M7sWorkerWrapper(stats, spec=spec, base=base, tracker=tracker, recording=recording, goal=goal)


class M7sWorkerFactory:
    """Top-level, picklable (spawn-safe) factory of the goal worker stack."""

    def __init__(self, spec: Any):
        self.spec = spec

    def __call__(self) -> M7sWorkerWrapper:
        return build_worker_env_m7s(self.spec)
