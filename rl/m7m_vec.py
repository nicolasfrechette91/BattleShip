"""M7m parent side: AnchorVecEnv, a VecEnvWrapper between M7SubprocVecEnv and VecNormalize (M7h's position).

Constructed only when the profile has an [anchor_curriculum] table. reset() is never changed: the initial reset of
every worker is an ordinary tick-0 start. After an AUTOMATIC reset inside step():

    step_wait(): obs, rews, dones, infos = venv.step_wait()     # workers auto-reset done envs (tick 0, non-consuming)
        for each done env (index order): read the finished episode's sweep outcome; the schedule counts it (anchored
                                         starts of the current window only) and may move the pointer back
        for each done env (index order): draw the next start (tick 0, or a cut tau in the current window)
        dispatch run_prefix_phase to the selected workers in parallel (anchor rows 0..tau-1, recorded, unrewarded)
        replace only those envs' observations by the post-prefix policy observations (checked against the table)
        return obs, rews, dones, infos                            # rewards, dones, terminal observations untouched

PPO therefore never sees a prefix step: its rollout holds only policy transitions, and num_timesteps counts policy
transitions only. Prefix ticks and their wall time are counted separately (report()).
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping

import numpy as np
from stable_baselines3.common.vec_env.base_vec_env import VecEnvWrapper

import m7h_curriculum as mc
import m7m_anchor as ma
from m7h_vec import policy_observation_from_dict
from m7h_worker import REPORT_KEY
from m7m_worker import OUTCOME_KEY, prefix_spec

NOT_COUNTED_ENDS = ("lifecycle_failure", "aborted")
NOTABLE_FILE = "notable_episodes.jsonl"     # whole trajectories of training episodes with a sweep or a left step


class AnchorVecEnv(VecEnvWrapper):
    def __init__(self, venv: Any, *, settings: Mapping[str, Any], run_id: str, seed: int, log_dir: Path):
        super().__init__(venv)
        self.settings = ma.check_table(settings)
        self.run_id = run_id
        self.anchor = ma.load_anchor()
        self.table = ma.load_observation_table(self.settings["observation_table_sha256"])
        self.schedule = ma.AnchorSchedule(seed, tick0_probability=self.settings["tick0_probability"])
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.selection_log = self.log_dir / "selection.jsonl"
        self.notable = self.log_dir / NOTABLE_FILE
        self.vec_steps = 0
        self.stats: Dict[str, Any] = {"auto_resets": 0, "initial_resets": 0, "starts": {}, "prefix_ticks": 0,
                                      "prefix_dispatches": 0, "dispatch_wall_s": 0.0, "dispatch_steps": 0,
                                      "max_dispatch_wall_s": 0.0, "invariant_checks": 0,
                                      "delivered_equals_table": 0, "lifecycle_failures": 0, "no_outcome": 0,
                                      "outcomes": {}, "successes_by_kind": {}, "notable_kept": 0}

    # -- VecEnv API -------------------------------------------------------------------------------------

    def reset(self):
        obs = self.venv.reset()
        self.stats["initial_resets"] += self.num_envs
        self._log({"vec_step": self.vec_steps, "event": "initial_reset", "envs": self.num_envs,
                   "kind": ma.START_TICK0_INITIAL})
        self._count("starts", ma.START_TICK0_INITIAL, self.num_envs)
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
                raise ma.AnchorError("rewards, dones or terminal observations changed inside AnchorVecEnv")
            self.stats["invariant_checks"] += 1
        return obs, rews, dones, infos

    def close(self) -> None:
        self.venv.close()

    # -- the schedule ----------------------------------------------------------------------------------

    def _after_auto_resets(self, obs: np.ndarray, infos: List[Dict[str, Any]], done_idx: List[int]) -> None:
        self.stats["auto_resets"] += len(done_idx)
        for i in done_idx:                               # 1. outcomes, index order
            report = infos[i].pop(REPORT_KEY, None)
            out = infos[i].pop(OUTCOME_KEY, None)
            summary = infos[i].get("m7_episode") or {}
            if out is None:
                self.stats["no_outcome"] += 1
                self._log({"vec_step": self.vec_steps, "env": i, "event": "no_outcome",
                           "episode_id": summary.get("episode_id"), "end_reason": summary.get("end_reason")})
                continue
            kind = out.get("kind")
            self._count("outcomes", kind, 1)
            self._count("successes_by_kind", kind, int(bool(out["success"])))
            o = ma.Outcome(kind=kind, tau=int(out["tau"]), window_index=out.get("window_index"),
                           success=bool(out["success"]), end_reason=out.get("end_reason"),
                           counted_end=out.get("end_reason") not in NOT_COUNTED_ENDS)
            ev = self.schedule.ingest(o)
            self._log({"vec_step": self.vec_steps, "env": i, "event": "outcome", "episode_id": out.get("episode_id"),
                       "kind": kind, "tau": out["tau"], "window_index": out.get("window_index"),
                       "success": out["success"], "seven_right": out["seven_right"], "sweep_tick": out["sweep_tick"],
                       "t2_policy": out["t2_policy"], "left_ids": out["left_ids"], "end_reason": out.get("end_reason"),
                       "policy_steps": out.get("policy_steps"), "schedule": ev, "pointer": self.schedule.pointer()})
            if out["seven_right"] or out["left_ids"] or (report or {}).get("class"):
                self._keep_notable(report, out)
        calls: Dict[int, Any] = {}
        drawn: Dict[int, int] = {}
        for i in done_idx:                               # 2. draws, index order
            kind, tau, k, draws = self.schedule.draw()
            rec = {"vec_step": self.vec_steps, "env": i, "event": "select", "kind": kind, **draws,
                   "pointer": self.schedule.pointer()}
            if kind == ma.START_ANCHOR:
                calls[i] = ((prefix_spec(self.anchor, self.table, tau=tau, window_index=k, run_id=self.run_id),), {})
                drawn[i] = tau
                rec.update(tau=tau, window_index=k)
            else:
                self._count("starts", kind, 1)
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
                expected = policy_observation_from_dict(self.table[drawn[i] - 1])
                if int(start["prefix_length"]) != drawn[i] or not np.array_equal(pobs, expected):
                    raise ma.AnchorError(f"env {i}: delivered observation differs from the table at cut {drawn[i]}")
                self.stats["delivered_equals_table"] += 1
                self.stats["prefix_ticks"] += int(start["prefix_length"])
            else:
                self.stats["lifecycle_failures"] += 1
            obs[i] = pobs
            self._count("starts", start["kind"], 1)
            reset_infos = getattr(self.venv, "reset_infos", None)
            if reset_infos is not None and i < len(reset_infos) and isinstance(reset_infos[i], dict):
                reset_infos[i]["m7m_start"] = {k: start.get(k) for k in ("kind", "prefix_length", "prefix_digest",
                                                                          "window_index")}
            self._log({"vec_step": self.vec_steps, "env": i, "event": "delivered", "kind": start["kind"],
                       "prefix_length": start.get("prefix_length"), "prefix_wall_s": start.get("prefix_wall_s"),
                       "host_frame_equal": start.get("prefix_host_frame_equal"), "dispatch_wall_s": round(wall, 4)})
        if self.stats["lifecycle_failures"] > 3:
            raise ma.AnchorError(f"{self.stats['lifecycle_failures']} prefix-phase lifecycle failures (limit 3)")

    # -- persistence and reporting ---------------------------------------------------------------------

    def write_state(self, directory: Path) -> Dict[str, str]:
        """Schedule state into a checkpoint set being written (returns {file: sha256})."""
        data = json.dumps({"schedule": self.schedule.state_json(), "vec_steps": self.vec_steps,
                           "stats": self.report()}, indent=1, default=str).encode("utf-8")
        (Path(directory) / "anchor_schedule.json").write_bytes(data)
        return {"anchor_schedule.json": hashlib.sha256(data).hexdigest()}

    def report(self) -> Dict[str, Any]:
        st = self.schedule.state_json()
        st.pop("rng", None)
        return {"contract": ma.CONTRACT_ID, "settings": dict(self.settings), "vec_steps": self.vec_steps,
                **{k: (dict(v) if isinstance(v, dict) else v) for k, v in self.stats.items()},
                "schedule": st, "min_pointer_reached": ma.min_pointer_reached(st)}

    def _keep_notable(self, report: Any, out: Mapping[str, Any]) -> None:
        """Every training episode with all seven right targets broken or a live left step keeps its whole trajectory
        (Track 1 indices from tick 0, prefix rows included) for exact replay; never an input to anything."""
        report = report or {}
        start = report.get("start") or {}
        rec = {"vec_step": self.vec_steps, "run_id": report.get("run_id"), "episode_id": report.get("episode_id"),
               "rank": report.get("rank"), "worker_episode": report.get("worker_episode"),
               "start_kind": start.get("kind"), "prefix_length": int(start.get("prefix_length") or 0),
               "prefix_digest": start.get("prefix_digest"), "class": report.get("class"), "outcome": dict(out),
               "rows": report.get("rows"), "full_digest": report.get("full_digest"),
               "tracker_digest": report.get("tracker_digest"), "end_reason": report.get("end_reason"),
               "actions_hex": bytes(report.get("actions") or b"").hex()}
        with open(self.notable, "a", encoding="utf-8", newline="\n") as fp:
            fp.write(json.dumps(rec, separators=(",", ":"), default=str) + "\n")
        self.stats["notable_kept"] += 1

    def _count(self, key: str, kind: Any, n: int) -> None:
        d = self.stats[key]
        d[str(kind)] = d.get(str(kind), 0) + int(n)

    def _log(self, record: Mapping[str, Any]) -> None:
        with open(self.selection_log, "a", encoding="utf-8", newline="\n") as fp:
            fp.write(json.dumps(record, separators=(",", ":"), default=str) + "\n")


def attach(vecnorm: Any, venv: Any, *, settings: Mapping[str, Any], run_id: str, seed: int, log_dir: Path
           ) -> AnchorVecEnv:
    """Insert AnchorVecEnv between a VecNormalize (fresh or loaded from the warm-start checkpoint) and its
    M7SubprocVecEnv, before the model is loaded and before any reset (the M7h attach rule)."""
    if getattr(vecnorm, "venv", None) is not venv:
        raise ma.AnchorError("attach(): VecNormalize does not wrap the given M7SubprocVecEnv directly")
    cur = AnchorVecEnv(venv, settings=settings, run_id=run_id, seed=seed, log_dir=log_dir)
    if cur.observation_space != vecnorm.observation_space or cur.num_envs != vecnorm.num_envs:
        raise ma.AnchorError("attach(): spaces differ")
    vecnorm.venv = cur
    return cur
