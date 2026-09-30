"""M7u: the worker stack (opt-in; every earlier stack is unchanged).

    M7BattleShipBTTEnv -> M7uProbeWrapper -> M7RewardWrapper (v2, recorded only) -> EpisodeRecordingWrapper
    -> Track1PolicyWrapper -> EntityObsV4Wrapper -> M7uTrialWrapper -> EpisodeStatsWrapper -> M7uWorkerWrapper

The environment is the unchanged v4 profile rl/configs/m7q/m7q_pilot_s0.toml (SSB64_RL_SPATIAL / ENTITY / INPUT,
no-render + Raphnet bypass, 5 workers + 1 standby each, horizon 3,600). Every episode starts with the environment's
normal non-consuming tick-0 reset; every submitted word is one native tick through the unchanged request path and is
recorded by the M4 recorder as a canonical native word (the replay truth). Prefix words are ordinary recorded words.

M7uProbeWrapper sits below the reward wrapper and the recorder (as M7s's GoalProbeWrapper), so the two Python-side ends
it declares (`goal_reached`, `trial_budget`) are recorded as ordinary truncations. It builds the native row of every
step reply (rl/m7u_state.row_from_reply), checks the start-state identity on the tick the prefix completes, and scores
the SCORED goal g (for S as for P and RC: reaching the commanded pi(g) never ends a trial).

M7uTrialWrapper takes the configuration from the parent (env_method), guards every submitted prefix / replay word
against the entry, keeps the episode's rows and words, writes the sidecar `m7u_states.npz` into the preserved artifact
directory and reports one record per step (`info['m7u']`). NumPy / Gymnasium only (spawn workers import this module).
"""
from __future__ import annotations

import io
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import gymnasium as gym
import numpy as np

import btt_parallel as bp
import m7n_obs as mn
import m7q_obs as mq
import m7u_goals as ug
import m7u_state as us

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PROFILE = REPO_ROOT / "rl" / "configs" / "m7q" / "m7q_pilot_s0.toml"   # the v4 environment block (unchanged)
N_WORKERS = 5
SIDECAR_FILE = "m7u_states.npz"
SIDECAR_SCHEMA = "m7u_sidecar_v1"
END_GOAL = "goal_reached"
END_BUDGET = "trial_budget"
MODES = ("collect", "trial", "replay")


class WorkerContractError(RuntimeError):
    pass


def rows_equal(a: np.ndarray, b: np.ndarray) -> List[str]:
    """Field names where two rows differ (exact float equality; NaN equals NaN)."""
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    same = (a == b) | (np.isnan(a) & np.isnan(b))
    return [us.FIELDS[i] for i in np.nonzero(~same)[0]]


class M7uProbeWrapper(gym.Wrapper):
    def __init__(self, env: Any, *, base: Any):
        super().__init__(env)
        self.base = base
        self.reply_source: Any = None
        self.entry: Optional[Dict[str, Any]] = None
        self.k = 0
        self.reach_tick: Optional[int] = None
        self.prefix_identity: Optional[Dict[str, Any]] = None
        self.last: Optional[Dict[str, Any]] = None

    def set_entry(self, entry: Optional[Mapping[str, Any]]) -> None:
        self.entry = dict(entry) if entry is not None else None

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        obs, info = self.env.reset(seed=seed, options=options)
        self.k, self.reach_tick, self.prefix_identity, self.last = 0, None, None, None
        return obs, info

    def step(self, action: Any):
        obs, reward, terminated, truncated, info = self.env.step(action)   # an EpisodeFailure propagates: no tick
        self.k += 1
        reply = self.reply_source() if self.reply_source is not None else None
        if not reply or reply.get("op") != "step":
            raise WorkerContractError("no raw step reply for the consumed tick")
        row = us.row_from_reply(reply)
        reason = info.get("termination_reason") if terminated else None
        fell = reason == bp.TERMINATION_NATIVE_FAILURE
        clear = reason == bp.TERMINATION_NATIVE_CLEAR
        e = self.entry or {}
        kind = e.get("kind", "collect")
        reached = False
        ended_by = None
        if kind == "trial":
            t, budget = int(e["t"]), int(e["budget"])
            if self.k == t:
                exp = np.array([np.nan if v is None else v for v in e["expected_start_row"]], dtype=np.float64)
                diff = rows_equal(row, exp)
                self.prefix_identity = {"ok": not diff, "fields": diff[:12], "tick": self.k}
            if self.k > t and self.reach_tick is None:
                gx, gy = e["goal"]
                valid = row[us.F["valid"]] == 1.0 and not fell and not clear
                reached = bool(valid and int(row[us.F["ga"]]) == 1 and abs(row[us.F["x"]] - gx) <= ug.BOX
                               and abs(row[us.F["y"]] - gy) <= ug.BOX)
                if reached:
                    self.reach_tick = self.k
            if not (terminated or truncated):
                if reached:
                    truncated, ended_by = True, END_GOAL
                elif self.k >= t + budget:
                    truncated, ended_by = True, END_BUDGET
            if ended_by is not None:
                info["truncation_reason"] = ended_by
        self.last = {"k": self.k, "row": row, "reached": reached, "ended_by": ended_by, "fell": fell, "clear": clear,
                     "control": kind == "trial" and self.k > int(e.get("t", 0))}
        info["m7u_probe"] = self.last
        return obs, reward, terminated, truncated, info


class M7uTrialWrapper(gym.Wrapper):
    def __init__(self, env: Any, *, probe: M7uProbeWrapper, v4: Any, tracker: Any, rank: int):
        super().__init__(env)
        self.probe, self.v4, self.tracker, self.rank = probe, v4, tracker, int(rank)
        self.cfg: Optional[Dict[str, Any]] = None
        self.entries: List[Dict[str, Any]] = []
        self.done = 0
        self.idle = False
        self.entry: Optional[Dict[str, Any]] = None
        self.rows: List[np.ndarray] = []
        self.words: List[Tuple[int, int]] = []
        self._cached: Any = None
        self.last_reset_record: Optional[Dict[str, Any]] = None
        self.last_step_record: Optional[Dict[str, Any]] = None
        self.totals = {"episodes": 0, "ticks": 0, "idle_steps": 0, "idle_resets": 0, "sidecars_written": 0,
                       "guard_violations": 0}

    # -- control (env_method) ---------------------------------------------------------------------------------------

    def m7u_configure(self, cfg: Mapping[str, Any]) -> bool:
        cfg = dict(cfg)
        if cfg.get("mode") not in MODES:
            raise WorkerContractError(f"mode {cfg.get('mode')!r}")
        entries = list(cfg.get("entries") or [])
        if not entries:
            raise WorkerContractError("no entries")
        for e in entries:
            kind = e.get("kind")
            if kind not in ("collect", "trial"):
                raise WorkerContractError(f"entry kind {kind!r}")
            if kind == "trial" and not all(k in e for k in ("t", "budget", "goal", "prefix", "expected_start_row")):
                raise WorkerContractError(f"trial entry {e.get('entry')} is incomplete")
            if cfg["mode"] == "replay" and "words" not in e:
                raise WorkerContractError("replay entries carry their words")
        self.cfg, self.entries, self.done, self.idle = cfg, entries, 0, False
        return True

    def m7u_status(self) -> Dict[str, Any]:
        return {"rank": self.rank, "idle": self.idle, "episodes_done": self.done, "totals": dict(self.totals)}

    # -- Gymnasium API ------------------------------------------------------------------------------------------------

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        if self.cfg is None:
            raise WorkerContractError("m7u_configure before the first reset")
        if self.idle:
            self.totals["idle_resets"] += 1
            self.last_reset_record = {"idle": True, "rank": self.rank}
            return self._cached, {"m7u": self.last_reset_record}
        self.entry = self.entries[self.done]
        self.probe.set_entry(self.entry)
        obs, info = self.env.reset(seed=seed, options=options)
        reply = self.v4._last_reply or {}
        row0 = us.row_from_reply(reply)
        if int(row0[us.F["input_tick"]]) != 0:
            raise WorkerContractError(f"reset observation at input_tick {row0[us.F['input_tick']]}")
        self.rows, self.words = [row0], []
        self._cached = obs
        self.last_reset_record = {"reset": True, "idle": False, "rank": self.rank, "entry": self.entry.get("entry"),
                                  "row": row0.tolist(), "startup_mode": info.get("startup_mode"),
                                  "world_digest": us.world_digest(us.static_world(reply))}
        info["m7u"] = self.last_reset_record
        return obs, info

    def _guard(self, word: Tuple[int, int]) -> Optional[str]:
        e = self.entry or {}
        k = len(self.words)
        if self.cfg and self.cfg["mode"] == "replay":
            want = e["words"]
            if k >= len(want) or tuple(want[k]) != word:
                return f"replay word {k}: {word} != {want[k] if k < len(want) else None}"
        elif e.get("kind") == "trial" and k < int(e["t"]):
            if tuple(e["prefix"][k]) != word:
                return f"prefix word {k}: {word} != {tuple(e['prefix'][k])}"
        return None

    def step(self, action: Any):
        if self.idle:
            self.totals["idle_steps"] += 1
            self.last_step_record = {"idle": True, "rank": self.rank}
            return self._cached, 0.0, False, False, {"m7u": self.last_step_record}
        word = (int(action[0]), int(action[1]))
        bad = self._guard(word)
        if bad:
            self.totals["guard_violations"] += 1
            raise WorkerContractError(bad)          # nothing is sent: the guard runs before the request
        obs, reward, terminated, truncated, info = self.env.step(action)
        probe = info.pop("m7u_probe", None)
        consumed = probe is not None
        if not consumed and info.get("truncation_reason") != "episode_failure":
            raise WorkerContractError("a step without the probe's record")
        rec: Dict[str, Any] = {"idle": False, "rank": self.rank, "entry": (self.entry or {}).get("entry"),
                               "consumed": consumed, "episode_failure": not consumed}
        if consumed:
            self.totals["ticks"] += 1
            self.rows.append(probe["row"])
            self.words.append(word)
            rec.update({"k": probe["k"], "row": probe["row"].tolist(), "reached": probe["reached"],
                        "ended_by": probe["ended_by"], "control": probe["control"]})
            if self.probe.prefix_identity is not None and probe["k"] == self.probe.prefix_identity["tick"]:
                rec["prefix_identity"] = self.probe.prefix_identity
        self._cached = obs
        done = bool(terminated or truncated)
        if done:
            self._finish(terminated, truncated, info)
            self.done += 1
            self.totals["episodes"] += 1
            if self.done >= len(self.entries):
                self.idle = True
            rec["idle_next"] = self.idle
            rec["reach_tick"] = self.probe.reach_tick
            rec["truncation_reason"] = info.get("truncation_reason") if truncated else None
            rec["termination_reason"] = info.get("termination_reason") if terminated else None
        self.last_step_record = rec
        info["m7u"] = rec
        return obs, reward, terminated, truncated, info

    def _finish(self, terminated: bool, truncated: bool, info: Mapping[str, Any]) -> None:
        e = dict(self.entry or {})
        meta = {"schema": SIDECAR_SCHEMA, "state_contract": us.CONTRACT, "state_digest": us.contract_digest(),
                "entry": {k: v for k, v in e.items() if k not in ("prefix", "words", "expected_start_row")},
                "prefix_length": int(e.get("t", 0)) if e.get("kind") == "trial" else 0,
                "reach_tick": self.probe.reach_tick, "prefix_identity": self.probe.prefix_identity,
                "terminated": bool(terminated), "truncated": bool(truncated),
                "truncation_reason": info.get("truncation_reason") if truncated else None,
                "termination_reason": info.get("termination_reason") if terminated else None,
                "mode": (self.cfg or {}).get("mode"), "phase": (self.cfg or {}).get("phase"), "rank": self.rank}
        rows = np.stack(self.rows)
        words = np.array(self.words, dtype=np.int16).reshape(-1, 2)

        def build(summary: Mapping[str, Any]) -> Dict[str, Any]:
            extra: Dict[str, Any] = {"m7u": dict(meta, sidecar=None)}
            if summary.get("preserved"):
                directory = Path(self.tracker.artifact_root) / str(summary["episode_id"])
                buf = io.BytesIO()
                np.savez_compressed(buf, rows=rows, words=words,
                                    meta=np.frombuffer(json.dumps(dict(meta, episode_id=str(summary["episode_id"]),
                                                                       native_action_digest=summary.get("native_action_digest")),
                                                                  default=str).encode("utf-8"), dtype=np.uint8))
                (directory / SIDECAR_FILE).write_bytes(buf.getvalue())
                extra["m7u"]["sidecar"] = SIDECAR_FILE
                self.totals["sidecars_written"] += 1
            return extra

        self.tracker.extend_pending_summary(build)


class M7uWorkerWrapper(bp.M7WorkerWrapper):
    def __init__(self, env: Any, *, spec: Any, base: Any, tracker: Any, recording: Any, trial: M7uTrialWrapper):
        super().__init__(env, spec=spec, base=base, tracker=tracker, recording=recording)
        self.trial = trial

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        observation, slim = super().reset(seed=seed, options=options)
        slim["m7u"] = self.trial.last_reset_record
        return observation, slim

    def step(self, action):
        observation, reward, terminated, truncated, slim = super().step(action)
        slim["m7u"] = self.trial.last_step_record
        return observation, reward, terminated, truncated, slim


def read_sidecar(directory: Path) -> Dict[str, Any]:
    with np.load(Path(directory) / SIDECAR_FILE) as z:
        return {"rows": z["rows"], "words": z["words"].astype(np.int64), "meta": json.loads(bytes(z["meta"]).decode("utf-8"))}


def m7u_contracts(horizon: int, reward: Any, character: str = mn.DEFAULT_CHARACTER) -> Dict[str, Any]:
    c = dict(mq.m7q_contracts(horizon, reward, character))
    c.update({"m7u_state_contract": us.CONTRACT, "m7u_state_digest": us.contract_digest(),
              "m7u_goal_contract": ug.GOAL_CONTRACT, "python_side_truncations": [END_GOAL, END_BUDGET],
              "m7u_scope": ug.SCOPE})
    return c


def build_worker_env_m7u(spec: Any) -> M7uWorkerWrapper:
    missing = [f"{k}={v}" for k, v in mq.ENTITY_EXTRA_ENV if dict(spec.extra_env).get(k) != v]
    if missing:
        raise ValueError(f"M7u worker spec needs {missing} in extra_env")
    if getattr(spec, "exploration", None) is not None or bp.is_route_contract(spec.reward_contract):
        raise ValueError("M7u workers use reward v2 (recorded only) without an exploration table")
    random.seed(spec.worker_seed)             # Python-side reproducibility only; never reaches the game
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
    probe = M7uProbeWrapper(base, base=base)
    tracker = mn._tracker_class(character, m7u_contracts)(
        run_id=spec.run_id, role=spec.role, rank=spec.rank, coordinator=bp.RunCoordinator(spec.coordination_dir),
        artifact_root=paths["artifacts"], ledger_path=paths["ledger"], env=base, reward=spec.reward_contract,
        retain_failed_cap=spec.retain_failed_cap, preserve_all=spec.preserve_all, experiment=spec.experiment)
    rewarded = bp.make_reward_wrapper(probe, spec, tracker)
    recording = bp.EpisodeRecordingWrapper(rewarded, paths["artifacts"],
                                           detectors=[bp.PositionDeltaDetector(spec.position_delta_threshold)],
                                           labels=tracker.labels_for_new_episode,
                                           on_episode_end=tracker.on_episode_end, targets_total=bp.TARGETS_TOTAL)
    track1 = bp.Track1PolicyWrapper(recording)
    v4 = mq.EntityObsV4Wrapper(track1, base=base, character=character)
    probe.reply_source = lambda: v4._last_reply
    trial = M7uTrialWrapper(v4, probe=probe, v4=v4, tracker=tracker, rank=spec.rank)
    stats = bp.EpisodeStatsWrapper(trial)
    return M7uWorkerWrapper(stats, spec=spec, base=base, tracker=tracker, recording=recording, trial=trial)


class M7uWorkerFactory:
    """Top-level, picklable (spawn-safe) factory of the M7u worker stack."""

    def __init__(self, spec: Any):
        self.spec = spec

    def __call__(self) -> M7uWorkerWrapper:
        return build_worker_env_m7u(self.spec)


# -- environment settings (the v4 profile's environment block, read-only) ---------------------------------------------


@dataclass(frozen=True)
class EnvSettings:
    executable: str
    extra_env: Tuple[Tuple[str, str], ...]
    horizon: int
    reward: Any
    standby_preboot: bool
    standby_count: int
    standby_wait_timeout: float
    port_block_base: int
    port_block_size: int
    request_timeout: float
    step_timeout: float
    startup_attempts: int
    retain_failed_cap: int
    experiment: Optional[Dict[str, Any]] = None


def env_settings(profile: Path = ENV_PROFILE) -> EnvSettings:
    import experiment_config as ec
    from m7_trainer import config_from_experiment

    exp = ec.load_experiment(profile)
    c = config_from_experiment(exp)
    if c.observation != mq.OBS_CONTRACT or c.n_envs != N_WORKERS or int(c.horizon) != 3600:
        raise WorkerContractError(f"{profile}: not the v4 environment ({c.observation}, {c.n_envs}, {c.horizon})")
    if any(dict(c.extra_env).get(k) != v for k, v in mq.ENTITY_EXTRA_ENV):
        raise WorkerContractError(f"{profile}: diagnostics flags missing")
    return EnvSettings(executable=str(c.executable), extra_env=tuple(c.extra_env), horizon=int(c.horizon),
                       reward=c.reward, standby_preboot=bool(c.standby_preboot), standby_count=int(c.standby_count),
                       standby_wait_timeout=float(c.standby_wait_timeout), port_block_base=int(c.port_block_base),
                       port_block_size=int(c.port_block_size), request_timeout=float(c.request_timeout),
                       step_timeout=float(c.step_timeout), startup_attempts=int(c.startup_attempts),
                       retain_failed_cap=int(c.retain_failed_cap),
                       experiment={"task_id": str(exp.values["task.id"]), "environment_profile": profile.name,
                                   "m7u": {"state_contract": us.CONTRACT, "goal_contract": ug.GOAL_CONTRACT}})


def worker_spec(root: Path, rank: int, run_id: str, role: str, s: EnvSettings, coord_dir: Path) -> Any:
    from btt_parallel import WorkerSpec

    return WorkerSpec(rank=rank, run_id=run_id, role=role, worker_dir=str(root / "workers" / f"w{rank:02d}"),
                      coordination_dir=str(coord_dir), executable=s.executable, horizon=s.horizon, base_seed=0,
                      extra_env=s.extra_env, reward_contract=s.reward, experiment=s.experiment,
                      retain_failed_cap=s.retain_failed_cap, startup_attempts=s.startup_attempts,
                      request_timeout=s.request_timeout, preserve_all=True,
                      port_block_base=s.port_block_base, port_block_size=s.port_block_size,
                      standby_preboot=s.standby_preboot, standby_count=s.standby_count,
                      standby_wait_timeout=s.standby_wait_timeout)
