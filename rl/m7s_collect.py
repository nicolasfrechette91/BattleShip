"""M7s stage 1: main-process collection, GCSL learning and evaluation loops over the goal worker stack.

One `run_phase` drives five workers (M7SubprocVecEnv, each with one standby process, the M7n v3 environment) through
one phase: phase A (null goal, 4 episodes per worker), phase B (matched schedule, 71,680 consumed ticks per worker; R
trains 100 GCSL steps after every 5,120 ticks, U never trains) or evaluation (plan entries, episodes end at the first valid
return). Actions are sampled from the policy with the episode's registered generator (common random numbers for R and
U). Idle workers (quota used up) send nothing and consume no tick. Every consumed tick is counted against the phase cap.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

import m7n_obs as mn
import m7s_goal as mg
import m7s_worker as msw

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PROFILE = REPO_ROOT / "rl" / "configs" / "m7n" / "m7n_s0_v3.toml"   # the M7n v3 environment block (unchanged)
N_WORKERS = 5
PHASE_A_PER_WORKER = mg.PHASE_A_EPISODES // N_WORKERS            # 4
PHASE_B_TICKS_PER_WORKER = 71_680                                # 70 chunks x 1,024 ticks per worker
PHASE_B_TICKS = N_WORKERS * PHASE_B_TICKS_PER_WORKER             # 358,400
EVAL_EPISODES = (mg.E_RARE + mg.E_MID) * mg.EVAL_REPEATS          # 30


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
    """The environment of the selected M7n v3 profile (flags, workers, standby, horizon, reward v2, ports)."""
    import experiment_config as ec
    from m7_trainer import config_from_experiment

    exp = ec.load_experiment(profile)
    c = config_from_experiment(exp)
    if c.observation != mn.OBS_CONTRACT or c.n_envs != N_WORKERS or c.horizon != mg.HORIZON:
        raise mg.GoalContractError(f"{profile}: not the M7n v3 environment ({c.observation}, {c.n_envs}, {c.horizon})")
    return EnvSettings(executable=str(c.executable), extra_env=tuple(c.extra_env), horizon=int(c.horizon),
                       reward=c.reward, standby_preboot=bool(c.standby_preboot), standby_count=int(c.standby_count),
                       standby_wait_timeout=float(c.standby_wait_timeout), port_block_base=int(c.port_block_base),
                       port_block_size=int(c.port_block_size), request_timeout=float(c.request_timeout),
                       step_timeout=float(c.step_timeout), startup_attempts=int(c.startup_attempts),
                       retain_failed_cap=int(c.retain_failed_cap),
                       experiment={"task_id": str(exp.values["task.id"]), "environment_profile": profile.name,
                                   "m7s": {"goal_contract": mg.CELL_CONTRACT, "gcsl": mg.GCSL_CONTRACT}})


def worker_spec(root: Path, rank: int, run_id: str, role: str, s: EnvSettings, coord_dir: Path, *,
                preserve_all: bool = True) -> Any:
    from btt_parallel import WorkerSpec

    return WorkerSpec(rank=rank, run_id=run_id, role=role, worker_dir=str(root / "workers" / f"w{rank:02d}"),
                      coordination_dir=str(coord_dir), executable=s.executable, horizon=s.horizon, base_seed=0,
                      extra_env=s.extra_env, reward_contract=s.reward, experiment=s.experiment,
                      retain_failed_cap=s.retain_failed_cap, startup_attempts=s.startup_attempts,
                      request_timeout=s.request_timeout, preserve_all=preserve_all,
                      port_block_base=s.port_block_base, port_block_size=s.port_block_size,
                      standby_preboot=s.standby_preboot, standby_count=s.standby_count,
                      standby_wait_timeout=s.standby_wait_timeout)


def prepare_factories(root: Path, run_id: str, role: str, s: EnvSettings) -> List[msw.M7sWorkerFactory]:
    from btt_parallel import RunCoordinator, initial_coordination_state
    from m7_runtime import prepare_worker_runtime, validate_port_blocks

    root = Path(root).resolve()
    if root.exists():
        raise mg.GoalContractError(f"{root} exists (never overwritten)")
    coord = root / "coordination"
    RunCoordinator.create(coord, initial_coordination_state(run_id, role, None))
    validate_port_blocks(range(N_WORKERS), s.port_block_base, s.port_block_size)
    out = []
    for rank in range(N_WORKERS):
        spec = worker_spec(root, rank, run_id, role, s, coord)
        prepare_worker_runtime(Path(spec.worker_dir) / "runtime", Path(s.executable))
        out.append(msw.M7sWorkerFactory(spec))
    return out


def v3_flat(obs: Mapping[str, np.ndarray]) -> np.ndarray:
    """(n, 606) in the v3 key order (the order SB3's CombinedExtractor used for v3)."""
    n = len(obs[mn.KEY_ORDER[0]])
    return np.concatenate([np.asarray(obs[k], dtype=np.float32).reshape(n, -1) for k in mn.KEY_ORDER], axis=1)


# -- one phase -------------------------------------------------------------------------------------------------------------


@dataclass
class PhaseResult:
    phase: str
    episodes: List[Dict[str, Any]] = field(default_factory=list)   # one row per finished episode
    ticks_per_rank: Dict[int, int] = field(default_factory=dict)
    ticks: int = 0
    vec_steps: int = 0
    idle_steps: int = 0
    wall_s: float = 0.0
    train_chunks: List[Dict[str, Any]] = field(default_factory=list)
    close: Optional[Dict[str, Any]] = None


@dataclass
class _Episode:
    rank: int
    worker_episode: int
    plan_entry: Optional[int]
    gen: np.random.Generator
    pos: Tuple[float, float]
    obs: List[np.ndarray] = field(default_factory=list)
    pos_log: List[Tuple[float, float]] = field(default_factory=list)
    actions: List[Tuple[int, int]] = field(default_factory=list)
    cells: List[Optional[str]] = field(default_factory=list)


def run_phase(*, venv: Any, configs: Mapping[int, Mapping[str, Any]], policy: Any, seed: int, phase: str,
              tick_cap: int, store: bool, trainer: Any = None, dataset: Optional[List[mg.EpisodeData]] = None,
              plan: Optional[Sequence[Mapping[str, Any]]] = None, act: Optional[Callable[..., np.ndarray]] = None,
              chunk_ticks: int = 0) -> PhaseResult:
    """Drive `venv` (already constructed) through one phase. `store`: keep o_t / a_t for the learner's dataset;
    `trainer` (R's phase B only): a GCSLTrainer, trained on `dataset` every `chunk_ticks` consumed ticks."""
    import m7s_policy as mp

    act = act or (lambda v3, g, gens: mp.sample_actions(*mp.action_probs(policy, v3, g), gens))
    res = PhaseResult(phase=phase)
    t0 = time.perf_counter()
    n = venv.num_envs
    ranks = [int(r) for r in getattr(venv, "ranks", range(n))]
    venv.env_method_each("m7s_configure", {i: ((dict(configs[ranks[i]]),), {}) for i in range(n)})
    obs = venv.reset()
    plan_by_entry = {int(p["entry"]): p for p in (plan or [])}

    def new_episode(i: int, rec: Mapping[str, Any]) -> Optional[_Episode]:
        if rec is None or rec.get("idle"):
            return None
        entry = rec.get("plan_entry")
        if entry is not None:
            g = np.random.default_rng(int(plan_by_entry[int(entry)]["sampling_seed"]))
        else:
            g = np.random.default_rng(mg.collection_seed(seed, phase if phase == "A" else "B", ranks[i],
                                                         int(rec["worker_episode"])))
        return _Episode(rank=ranks[i], worker_episode=int(rec["worker_episode"]), plan_entry=entry, gen=g,
                        pos=(float(rec["x"]), float(rec["y"])))

    cur: List[Optional[_Episode]] = [new_episode(i, (venv.reset_infos[i] or {}).get("m7s")) for i in range(n)]
    for i in range(n):
        res.ticks_per_rank[ranks[i]] = 0
    next_train = chunk_ticks if trainer is not None else None
    while any(c is not None for c in cur):
        v3 = v3_flat(obs)
        goal = np.asarray(obs[msw.GOAL_KEY], dtype=np.float32)
        actions = act(v3, goal, [c.gen if c is not None else None for c in cur])
        new_obs, _rew, dones, infos = venv.step(actions)
        res.vec_steps += 1
        for i in range(n):
            rec = (infos[i] or {}).get("m7s") or {}
            c = cur[i]
            if c is None:
                if not rec.get("idle"):
                    raise mg.GoalContractError(f"rank {ranks[i]} stepped after its quota")
                res.idle_steps += 1
                continue
            if rec.get("idle") or int(rec.get("worker_episode", -1)) != c.worker_episode:
                raise mg.GoalContractError(f"rank {ranks[i]}: step record does not belong to episode {c.worker_episode}")
            if rec["consumed"]:
                if store:
                    c.obs.append(v3[i])
                    c.pos_log.append(c.pos)
                    c.actions.append((int(actions[i, 0]), int(actions[i, 1])))
                c.cells.append(rec["cell"])
                c.pos = (float(rec["x"]), float(rec["y"]))
                res.ticks += 1
                res.ticks_per_rank[ranks[i]] += 1
                if res.ticks > tick_cap:
                    raise mg.GoalContractError(f"phase {phase}: {res.ticks} ticks exceed the cap {tick_cap}")
            if dones[i]:
                summary = (infos[i] or {}).get("m7_episode")
                if summary is None:
                    raise mg.GoalContractError(f"rank {ranks[i]}: episode ended without a summary")
                res.episodes.append(_finish(c, summary, store, dataset, phase))
                cur[i] = None if rec.get("idle_next") else new_episode(i, (venv.reset_infos[i] or {}).get("m7s"))
                if cur[i] is not None and cur[i].worker_episode != c.worker_episode + 1:
                    raise mg.GoalContractError(f"rank {ranks[i]}: episode {cur[i].worker_episode} after {c.worker_episode}")
        if next_train is not None and res.ticks >= next_train:
            res.train_chunks.append(trainer.train_chunk(dataset))
            next_train += chunk_ticks
        obs = new_obs
    res.wall_s = round(time.perf_counter() - t0, 1)
    return res


def _finish(c: _Episode, summary: Mapping[str, Any], store: bool, dataset: Optional[List[mg.EpisodeData]],
            phase: str) -> Dict[str, Any]:
    fell = summary.get("end_reason") == "fall"
    cells = [mg.parse_key(k) if k else None for k in c.cells]
    elig = mg.valid_cells(cells, fell)
    first: Dict[str, int] = {}
    for k, cell in enumerate(elig, start=1):
        if cell is not None:
            first.setdefault(mg.cell_key(cell), k)
    row = {"rank": c.rank, "worker_episode": c.worker_episode, "plan_entry": c.plan_entry,
           "episode_id": summary.get("episode_id"), "artifact_dir": summary.get("artifact_dir"),
           "preserved": bool(summary.get("preserved")), "native_action_digest": summary.get("native_action_digest"),
           "end_reason": summary.get("end_reason"), "truncation_reason": summary.get("truncation_reason"),
           "termination_reason": summary.get("termination_reason"), "cleared": bool(summary.get("cleared")),
           "completion_time_passed": summary.get("completion_time_passed"),
           "completion_input_tick": summary.get("completion_input_tick"),
           "startup_mode": summary.get("startup_mode"), "ticks": len(c.cells), "steps": summary.get("steps"),
           "targets_broken": summary.get("targets_broken"), "first_reach": first, "m7s": summary.get("m7s")}
    if store and dataset is not None:
        if len(c.obs) == 0:
            return row
        dataset.append(mg.EpisodeData(episode_id=str(summary.get("episode_id")),
                                      origin="phase_a" if phase == "A" else "phase_b",
                                      obs=np.stack(c.obs).astype(np.float32),
                                      pos=np.asarray(c.pos_log, dtype=np.float32),
                                      actions=np.asarray(c.actions, dtype=np.int64), cells=elig,
                                      native_action_digest=summary.get("native_action_digest")))
    return row


def phase_configs(mode: str, *, phase: str, schedule: Optional[Mapping[str, Any]] = None,
                  plan: Optional[Sequence[Mapping[str, Any]]] = None) -> Dict[int, Dict[str, Any]]:
    """Per-rank m7s_configure payloads of one phase."""
    out: Dict[int, Dict[str, Any]] = {}
    for r in range(N_WORKERS):
        if mode == "null":
            out[r] = {"mode": "null", "phase": phase, "episode_quota": PHASE_A_PER_WORKER, "end_on_success": False}
        elif mode == "schedule":
            out[r] = {"mode": "schedule", "phase": phase, "tick_quota": PHASE_B_TICKS_PER_WORKER,
                      "end_on_success": False, "schedule": mg.schedule_for_rank(schedule, r)}
        elif mode == "plan":
            mine = [{"entry": p["entry"], "goal": mg.parse_key(p["cell"])} for p in plan if int(p["rank"]) == r]
            out[r] = {"mode": "plan", "phase": phase, "episode_quota": len(mine), "end_on_success": True, "plan": mine}
        else:
            raise ValueError(mode)
    return out


def phase_a_episodes(res: PhaseResult) -> List[mg.PhaseAEpisode]:
    normal = {"cold_start", "standby_promoted", "cold_fallback"}
    return [mg.PhaseAEpisode(episode_id=str(e["episode_id"]), artifact_dir=e["artifact_dir"],
                             native_action_digest=e["native_action_digest"], first_reach=dict(e["first_reach"]),
                             end_reason=str(e["end_reason"]), started_at_tick0=e.get("startup_mode") in normal)
            for e in sorted(res.episodes, key=lambda x: (x["rank"], x["worker_episode"]))]


def write_json(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)
