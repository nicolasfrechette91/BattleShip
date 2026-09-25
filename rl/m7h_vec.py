"""M7h parent side: CurriculumVecEnv, a VecEnvWrapper between M7SubprocVecEnv and VecNormalize.

Constructed only when the profile has a [curriculum] table. It never changes reset(): the initial reset of every
worker is an ordinary tick-0 start. Curriculum selection happens only after an AUTOMATIC reset inside step():

    step_wait(): obs, rews, dones, infos = venv.step_wait()     # workers auto-reset done envs (tick 0, non-consuming)
        for each done env (index order): ingest the finished episode's report into this run's archive
        for each done env (index order): 50/50 draw; archive_prefix -> a prefix spec
        dispatch run_prefix_phase to the selected workers in parallel; each replays and records its prefix
        replace only those envs' observations by the post-prefix policy observations
        return obs, rews, dones, infos                            # rewards, dones, terminal observations untouched

VecNormalize (above) therefore updates its statistics once per returned observation; a curriculum episode's tick-0
observation is recorded by its worker but never returned to the policy. Every call verifies that rewards, dones and
the previous episodes' terminal observations left this wrapper unchanged.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

import numpy as np
from stable_baselines3.common.vec_env.base_vec_env import VecEnvWrapper

import m7h_curriculum as mc
from m7h_worker import REPORT_KEY, ROW_KEY

OBS_LOG_ENV = "M7H_TEST_OBSERVATION_LOG"      # E4 only: log every observation batch returned to VecNormalize
LEFT_EPISODES_FILE = "left_episodes.jsonl"     # every finished training episode with a live left step, whole trajectory


class CurriculumVecEnv(VecEnvWrapper):
    def __init__(self, venv: Any, *, settings: Mapping[str, Any], run_id: str, seed: int, log_dir: Path):
        super().__init__(venv)
        self.settings = mc.check_registered(settings)
        self.run_id = run_id
        self.archive = mc.Archive(run_id, max_prefix=self.settings["max_prefix_ticks"],
                                  fall_window=self.settings["pre_fall_exclusion_ticks"])
        self.selector = mc.Selector(seed, tick0_probability=self.settings["tick0_probability"])
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.selection_log = self.log_dir / "selection.jsonl"
        self.left_episodes = self.log_dir / LEFT_EPISODES_FILE
        self.vec_steps = 0
        self.stats: Dict[str, Any] = {"auto_resets": 0, "initial_resets": 0, "starts": {}, "prefix_ticks": 0,
                                      "prefix_dispatches": 0, "dispatch_wall_s": 0.0, "dispatch_steps": 0,
                                      "max_dispatch_wall_s": 0.0, "invariant_checks": 0,
                                      "delivered_equals_archived_end": 0, "lifecycle_failures": 0, "classes": {},
                                      "left_episodes_kept": 0}
        path = os.environ.get(OBS_LOG_ENV)
        self._obs_log = open(path, "ab") if path else None

    # -- VecEnv API -------------------------------------------------------------------------------------

    def reset(self):
        obs = self.venv.reset()
        self.stats["initial_resets"] += self.num_envs
        self._log({"vec_step": self.vec_steps, "event": "initial_reset", "envs": self.num_envs,
                   "kind": mc.START_TICK0_INITIAL})
        self._count(mc.START_TICK0_INITIAL, self.num_envs)
        self._write_obs(obs)
        return obs

    def step_async(self, actions: np.ndarray) -> None:
        self.venv.step_async(actions)

    def step_wait(self):
        obs, rews, dones, infos = self.venv.step_wait()
        self.vec_steps += 1
        done_idx = [int(i) for i in np.flatnonzero(dones)]
        if done_idx:
            rews_before, dones_before = np.array(rews, copy=True), np.array(dones, copy=True)
            terminal_before = {i: np.array(infos[i].get("terminal_observation"), copy=True) for i in done_idx}
            self._after_auto_resets(obs, infos, done_idx)
            same = np.array_equal(rews_before, rews) and np.array_equal(dones_before, dones) and all(
                np.array_equal(terminal_before[i], infos[i].get("terminal_observation")) for i in done_idx)
            if not same:
                raise mc.CurriculumError("rewards, dones or terminal observations changed inside CurriculumVecEnv")
            self.stats["invariant_checks"] += 1
        self._write_obs(obs)
        return obs, rews, dones, infos

    def close(self) -> None:
        if self._obs_log is not None:
            self._obs_log.close()
            self._obs_log = None
        self.venv.close()

    # -- the curriculum --------------------------------------------------------------------------------

    def _after_auto_resets(self, obs: np.ndarray, infos: List[Dict[str, Any]], done_idx: List[int]) -> None:
        self.stats["auto_resets"] += len(done_idx)
        for i in done_idx:                               # 1. ingest, index order
            report = infos[i].pop(REPORT_KEY, None)
            summary = infos[i].get("m7_episode") or {}
            if report is None:
                self._log({"vec_step": self.vec_steps, "env": i, "event": "no_report",
                           "episode_id": summary.get("episode_id")})
                continue
            res = self.archive.ingest(report, tracker_digest=summary.get("native_action_digest"))
            cls = report.get("class")
            if cls:
                self.stats["classes"][cls] = self.stats["classes"].get(cls, 0) + 1
                self._keep_left_episode(report)
            self._log({"vec_step": self.vec_steps, "env": i, "event": "ingest", "episode_id": report.get("episode_id"),
                       "rows": report.get("rows"), "end_reason": report.get("end_reason"), "class": cls,
                       "start_kind": (report.get("start") or {}).get("kind"), **res,
                       "cells": len(self.archive.entries), "eligible": len(self.archive.eligible())})
        calls: Dict[int, Any] = {}
        chosen: Dict[int, mc.Entry] = {}
        for i in done_idx:                               # 2. select, index order (one or two draws per done env)
            kind, entry, draws = self.selector.select(self.archive)
            rec = {"vec_step": self.vec_steps, "env": i, "event": "select", "kind": kind, **draws}
            if entry is not None:
                entry.selected += 1
                chosen[i] = entry
                calls[i] = ((mc.prefix_spec(entry, self.run_id),), {})
                rec.update(cell=list(entry.cell), length=entry.length, digest=entry.digest,
                           visits=entry.visits, source_episode_id=entry.source.get("episode_id"))
            else:
                self._count(kind, 1)
            self._log(rec)
        if not calls:
            return
        t0 = time.perf_counter()                         # 3. explicit prefix phases, in parallel
        replies = self.venv.env_method_each("run_prefix_phase", calls)
        wall = time.perf_counter() - t0
        self.stats["dispatch_steps"] += 1
        self.stats["prefix_dispatches"] += len(calls)
        self.stats["dispatch_wall_s"] = round(self.stats["dispatch_wall_s"] + wall, 4)
        self.stats["max_dispatch_wall_s"] = max(self.stats["max_dispatch_wall_s"], round(wall, 4))
        for i, reply in replies.items():                 # 4. deliver the post-prefix policy observation
            start = reply["start"]
            pobs = np.asarray(reply["observation"], dtype=obs.dtype)
            if start["kind"] == mc.START_PREFIX:
                expected = policy_observation_from_dict(chosen[i].end_observation)
                if not np.array_equal(pobs, expected):
                    raise mc.CurriculumError(f"env {i}: delivered observation differs from the archived end observation")
                self.stats["delivered_equals_archived_end"] += 1
                self.stats["prefix_ticks"] += int(start["prefix_length"])
            else:
                self.stats["lifecycle_failures"] += 1
            obs[i] = pobs
            self._count(start["kind"], 1)
            reset_infos = getattr(self.venv, "reset_infos", None)
            if reset_infos is not None and i < len(reset_infos) and isinstance(reset_infos[i], dict):
                reset_infos[i]["m7h_start"] = {k: start.get(k) for k in ("kind", "prefix_length", "prefix_digest", "cell")}
            self._log({"vec_step": self.vec_steps, "env": i, "event": "delivered", "kind": start["kind"],
                       "prefix_length": start.get("prefix_length"), "prefix_wall_s": start.get("prefix_wall_s"),
                       "host_frame_equal": start.get("prefix_host_frame_equal"), "dispatch_wall_s": round(wall, 4)})
        if self.stats["lifecycle_failures"] > 3:
            raise mc.CurriculumError(f"{self.stats['lifecycle_failures']} prefix-phase lifecycle failures (limit 3)")

    # -- persistence and reporting ---------------------------------------------------------------------

    def write_state(self, directory: Path) -> Dict[str, str]:
        """Archive + selector state into a checkpoint set being written (returns {file: sha256})."""
        import hashlib

        directory = Path(directory)
        files = {"curriculum_archive.json": json.dumps(dict(self.archive.to_json(), selector=self.selector.state_json(),
                                                            vec_steps=self.vec_steps, stats=self.report()),
                                                       indent=1, default=str).encode("utf-8"),
                 "curriculum_prefixes.bin": self.archive.prefixes_blob()}
        out = {}
        for name, data in files.items():
            (directory / name).write_bytes(data)
            out[name] = hashlib.sha256(data).hexdigest()
        return out

    def report(self) -> Dict[str, Any]:
        return {"contract": mc.CONTRACT_ID, "settings": dict(self.settings), "vec_steps": self.vec_steps,
                **{k: (dict(v) if isinstance(v, dict) else v) for k, v in self.stats.items()},
                "archive": {"cells": len(self.archive.entries), "eligible": len(self.archive.eligible()),
                            **self.archive.stats}, "selector_draws": self.selector.draws}

    def _keep_left_episode(self, report: Mapping[str, Any]) -> None:
        """The section-4 verification replays genuine left entries from tick 0, but training preserves only some
        artifacts; so every episode with a live left step keeps its whole trajectory here (Track 1 indices from tick
        0, one byte per row, with its digests and its prefix boundary). Written after ingestion, which has already
        refused a trajectory whose digest disagrees with the tracker's."""
        start = report.get("start") or {}
        rec = {"vec_step": self.vec_steps, "run_id": report.get("run_id"), "episode_id": report.get("episode_id"),
               "rank": report.get("rank"), "worker_episode": report.get("worker_episode"), "class": report.get("class"),
               "start_kind": start.get("kind"), "prefix_length": int(start.get("prefix_length") or 0),
               "prefix_digest": start.get("prefix_digest"), "lineage_left_exposed": bool(report.get("lineage_left_exposed")),
               "source_episode_id": (start.get("source") or {}).get("episode_id"), "rows": report.get("rows"),
               "full_digest": report.get("full_digest"), "end_reason": report.get("end_reason"),
               "last_consumed_tick": report.get("last_consumed_tick"), "left": report.get("left"),
               "actions_hex": bytes(report.get("actions") or b"").hex()}
        with open(self.left_episodes, "a", encoding="utf-8", newline="\n") as fp:
            fp.write(json.dumps(rec, separators=(",", ":"), default=str) + "\n")
        self.stats["left_episodes_kept"] += 1

    def _count(self, kind: str, n: int) -> None:
        self.stats["starts"][kind] = self.stats["starts"].get(kind, 0) + int(n)

    def _log(self, record: Mapping[str, Any]) -> None:
        with open(self.selection_log, "a", encoding="utf-8", newline="\n") as fp:
            fp.write(json.dumps(record, separators=(",", ":"), default=str) + "\n")

    def _write_obs(self, obs: np.ndarray) -> None:
        if self._obs_log is not None:
            np.save(self._obs_log, np.asarray(obs), allow_pickle=False)


def policy_observation_from_dict(obs: Mapping[str, Any]) -> np.ndarray:
    from btt_learning import POLICY_FIELDS

    return np.array([float(obs[name]) for name in POLICY_FIELDS], dtype=np.float32)


def attach(vecnorm: Any, venv: Any, *, settings: Mapping[str, Any], run_id: str, seed: int, log_dir: Path
           ) -> CurriculumVecEnv:
    """Insert CurriculumVecEnv between a freshly constructed VecNormalize and its M7SubprocVecEnv (before the model
    exists and before any reset). VecNormalize's constructor only reads spaces, so this equals constructing it on the
    wrapper; the pinned `VecNormalize(self.venv, ...)` literal of M7Run.run stays as it is."""
    if getattr(vecnorm, "venv", None) is not venv:
        raise mc.CurriculumError("attach(): VecNormalize does not wrap the given M7SubprocVecEnv directly")
    cur = CurriculumVecEnv(venv, settings=settings, run_id=run_id, seed=seed, log_dir=log_dir)
    if cur.observation_space != vecnorm.observation_space or cur.num_envs != vecnorm.num_envs:
        raise mc.CurriculumError("attach(): spaces differ")
    vecnorm.venv = cur
    return cur
