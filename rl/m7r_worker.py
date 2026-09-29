"""M7r worker stacks (opt-in): the commitment executor and the gate trace recorder on top of the M7q v4 stack.

    commit arm (C):   M7BattleShipBTTEnv -> reward v2 -> EpisodeRecordingWrapper -> Track1PolicyWrapper
                      -> EntityObsV4Wrapper [-> GateTraceWrapper] -> CommitExecutorWrapper -> EpisodeStatsWrapper
                      -> M7rWorkerWrapper
    per-tick arm (F): the unchanged M7q stack (training); for gate evaluations GateTraceWrapper is inserted above
                      EntityObsV4Wrapper (a pass-through recorder: it changes no action, observation or reward)

Every layer below the executor is the M7q stack, built by the same calls as rl/m7n_obs.build_worker_env_v3 (copied
here so no inherited file changes). The recorder and the executor read the raw reply the v4 observation wrapper keeps
(`_last_reply`); neither sends any request of its own.
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
import m7q_obs as mq
import m7q_status_table as st2
import m7r_commit as mc
from btt_learning import TRACK1_CONTRACT

GATE_TRACE_FILE = "gate_trace.json.gz"
GATE_TRACE_SCHEMA = "btt_gate_trace_v1"
GATE_TRACE_FIELDS = ("t", "buttons", "stick_x", "stick_y", "live", "status", "klass", "airborne", "hitlag",
                     "button_tap", "button_hold", "floor_line_id", "air_vx", "air_vy", "pos_x", "pos_y", "targets")


def m7r_contracts(horizon: int, reward: Any, character: str = mq.DEFAULT_CHARACTER) -> Dict[str, Any]:
    """The M7q v4 contracts plus the commitment action contract (per-tick words stay Track 1)."""
    c = mq.m7q_contracts(horizon, reward, character)
    c.update({"action_contract": mc.CONTRACT, "action_contract_sha256": mc.contract_digest(),
              "per_tick_action_contract": TRACK1_CONTRACT, "commit_sidecar_schema": mc.SIDECAR_SCHEMA})
    return c


# -- gate trace recorder ----------------------------------------------------------------------------------------


def trace_row(t: int, native: Any, reply: Mapping[str, Any], classifier: Any) -> List[Any]:
    o = reply.get("observation") or {}
    en = (reply.get("entity") or {}).get("fighter") or {}
    inp = reply.get("input") or {}
    fi = (reply.get("spatial") or {}).get("fighter") or {}
    live = int(bool(o.get("btt_active")) and bool(o.get("fighter_valid")) and bool(inp.get("valid")))
    status = int(o.get("fighter_status_id", -1))
    return [int(t),
            None if native is None else int(native.buttons), None if native is None else int(native.stick_x),
            None if native is None else int(native.stick_y), live, status,
            int(classifier.index(status)) if live else -1, int(int(o.get("ground_air_state", 0)) == 1),
            int(en.get("hitlag_tics", 0)), int(inp.get("button_tap", 0)), int(inp.get("button_hold", 0)),
            int(fi.get("floor_line_id", -1)) if fi else -1, float(o.get("air_velocity_x", 0.0)),
            float(o.get("air_velocity_y", 0.0)), float(o.get("position_x", 0.0)), float(o.get("position_y", 0.0)),
            int(o.get("targets_remaining", 0))]


class GateTraceWrapper(gym.Wrapper):
    """Per-tick recorder directly above EntityObsV4Wrapper (evaluation only). Row -1 is the tick-0 observe reply,
    row t the reply after consumed tick t with the native word consumed on it. Written as GATE_TRACE_FILE into the
    artifact directory of every preserved episode (gate evaluations preserve every episode)."""

    def __init__(self, env: Any, *, obs_wrapper: Any, tracker: Any, character: str):
        super().__init__(env)
        self.obs_wrapper = obs_wrapper
        self.tracker = tracker
        self.classifier = st2.ActionClassifier(st2.load_table(), character)   # own instance: v4 info counts untouched
        self.rows: Optional[List[List[Any]]] = None

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        obs, info = self.env.reset(seed=seed, options=options)
        self.rows = [trace_row(-1, None, self.obs_wrapper._last_reply, self.classifier)]
        return obs, info

    def step(self, action: Any):
        obs, reward, terminated, truncated, info = self.env.step(action)
        if self.rows is not None and info.get("consumed_tick") is not None:
            self.rows.append(trace_row(int(info["consumed_tick"]), info.get("native_action"),
                                       self.obs_wrapper._last_reply, self.classifier))
        if terminated or truncated:
            rows, self.rows = self.rows, None

            def build(summary: Mapping[str, Any]) -> Dict[str, Any]:
                if not summary.get("preserved") or rows is None:
                    return {"gate_trace": None}
                directory = Path(self.tracker.artifact_root) / str(summary["episode_id"])
                directory.mkdir(parents=True, exist_ok=True)
                with gzip.open(directory / GATE_TRACE_FILE, "wt", encoding="utf-8") as fp:
                    json.dump({"schema": GATE_TRACE_SCHEMA, "fields": list(GATE_TRACE_FIELDS),
                               "episode_id": summary["episode_id"],
                               "native_action_digest": summary.get("native_action_digest"),
                               "classes": list(st2.CLASSES), "class_table_sha256": self.classifier.table_sha256,
                               "rows": rows}, fp, separators=(",", ":"))
                return {"gate_trace": GATE_TRACE_FILE}

            self.tracker.extend_pending_summary(build)
        return obs, reward, terminated, truncated, info


# -- the outermost worker wrapper --------------------------------------------------------------------------------


class M7rWorkerWrapper(bp.M7WorkerWrapper):
    """M7WorkerWrapper plus: the executor's per-decision record in every step info, and idle replies once the
    environment's rollout tick quota is used up (no request is sent, no tick consumed, nothing counted)."""

    def __init__(self, env: Any, *, spec: Any, base: Any, tracker: Any, recording: Any, executor: Any = None):
        super().__init__(env, spec=spec, base=base, tracker=tracker, recording=recording)
        self.executor = executor
        self.idle_replies = 0

    def step(self, action):
        ex = self.executor
        if ex is not None and ex.quota_exhausted:
            self.idle_replies += 1
            return ex.last_obs, 0.0, False, False, {"m7_rank": self.worker_spec.rank,
                                                    "commit": {"contract": mc.CONTRACT, "idle": True}}
        observation, reward, terminated, truncated, slim = super().step(action)
        if ex is not None:
            slim["commit"] = ex.last_commit_info
        return observation, reward, terminated, truncated, slim

    def commit_begin_rollout(self, ticks: int) -> bool:
        if self.executor is None:
            raise mc.CommitError("commit_begin_rollout on a worker without the commitment executor")
        return self.executor.commit_begin_rollout(ticks)

    def commit_end_rollout(self) -> int:
        return self.executor.commit_end_rollout() if self.executor is not None else 0

    def commit_totals(self) -> Dict[str, Any]:
        t = dict(self.executor.totals) if self.executor is not None else {}
        t["idle_replies"] = self.idle_replies
        return t


# -- stack construction ------------------------------------------------------------------------------------------


def build_worker_env_m7r(spec: Any, *, commit: bool, gate_trace: bool, eval_metrics: bool = False) -> Any:
    """eval_metrics (evaluation only): M7g Phase K's EvalMetricsWrapper directly above EntityObsV4Wrapper, i.e. per
    native tick (it reads one step reply per step() call, so it must sit below the executor)."""
    missing = [f"{k}={v}" for k, v in mq.ENTITY_EXTRA_ENV if dict(spec.extra_env).get(k) != v]
    if missing:
        raise ValueError(f"M7r worker spec needs {missing} in extra_env")
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
    contracts_fn = m7r_contracts if commit else mq.m7q_contracts
    tracker = mn._tracker_class(character, contracts_fn)(
        run_id=spec.run_id, role=spec.role, rank=spec.rank, coordinator=bp.RunCoordinator(spec.coordination_dir),
        artifact_root=paths["artifacts"], ledger_path=paths["ledger"], env=base, reward=spec.reward_contract,
        retain_failed_cap=spec.retain_failed_cap, preserve_all=spec.preserve_all, experiment=spec.experiment)
    rewarded = bp.make_reward_wrapper(base, spec, tracker)
    recording = bp.EpisodeRecordingWrapper(rewarded, paths["artifacts"],
                                           detectors=[bp.PositionDeltaDetector(spec.position_delta_threshold)],
                                           labels=tracker.labels_for_new_episode,
                                           on_episode_end=tracker.on_episode_end, targets_total=bp.TARGETS_TOTAL)
    track1 = bp.Track1PolicyWrapper(recording)
    v4 = mq.EntityObsV4Wrapper(track1, base=base, character=character)
    top: Any = v4
    if eval_metrics:
        from m7g_eval_metrics import DIAG_ENV, EvalMetricsWrapper

        if dict(spec.extra_env).get(DIAG_ENV) != "1":
            raise ValueError(f"evaluation metrics need {DIAG_ENV}=1 in the worker flags")
        top = EvalMetricsWrapper(top, base=base, tracker=tracker)
    if gate_trace:
        top = GateTraceWrapper(top, obs_wrapper=v4, tracker=tracker, character=character)
    executor = None
    if commit:
        executor = mc.CommitExecutorWrapper(top, obs_wrapper=v4, classifier=st2.ActionClassifier(st2.load_table(), character),
                             tracker=tracker)
        top = executor
    stats = bp.EpisodeStatsWrapper(top)
    return M7rWorkerWrapper(stats, spec=spec, base=base, tracker=tracker, recording=recording, executor=executor)


class M7rCommitWorkerFactory:
    """Picklable (spawn-safe) factory of the commit arm's worker stack (training: no recorders)."""

    def __init__(self, spec: Any, gate_trace: bool = False, eval_metrics: bool = False):
        self.spec = spec
        self.gate_trace = bool(gate_trace)
        self.eval_metrics = bool(eval_metrics)

    def __call__(self) -> Any:
        return build_worker_env_m7r(self.spec, commit=True, gate_trace=self.gate_trace, eval_metrics=self.eval_metrics)


class M7rEvalWorkerFactory:
    """Picklable factory of a gate evaluation worker: either arm, per-tick recorders below any executor."""

    def __init__(self, spec: Any, *, commit: bool, gate_trace: bool, eval_metrics: bool):
        self.spec = spec
        self.commit, self.gate_trace, self.eval_metrics = bool(commit), bool(gate_trace), bool(eval_metrics)

    def __call__(self) -> Any:
        return build_worker_env_m7r(self.spec, commit=self.commit, gate_trace=self.gate_trace,
                                    eval_metrics=self.eval_metrics)
