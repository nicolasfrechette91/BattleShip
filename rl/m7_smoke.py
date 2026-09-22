#!/usr/bin/env python3
"""M7a smoke tests and regressions for parallel training (run sequentially; game cases launch BattleShip).

    python rl/m7_smoke.py                      # every case, in order
    python rl/m7_smoke.py unit                 # all no-game unit cases
    python rl/m7_smoke.py fall_regression isolation_boot_replay

No-game unit cases: unit_factory_pickle, unit_ports, unit_metadata,
unit_ranking, unit_fall_rule, unit_reward_fall, unit_coordinator,
unit_vec_protocol.

Game cases (sequential, one group at a time): isolation_boot_replay,
fall_regression, request_timeout_cleanup, startup_failure_retry,
vector_smoke_n2, vector_smoke_n4, vector_smoke_n5, checkpoint_reload,
resume_short, worker_exception_cleanup, interrupt_cleanup, job_object_kill.

After every case: zero BattleShip.exe processes, and the user's
build-us/Release/BattleShip.cfg.json byte-identical (sha256) to its value at
the start of the suite. Outputs go under runs/_m7_smoke_<utc>/ (git-ignored).
Standard library + NumPy + Gymnasium at module level only: spawn children
re-import this file.
"""

from __future__ import annotations

import argparse
import json
import math
import multiprocessing
import os
import pickle
import shutil
import socket
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

import gymnasium as gym
import numpy as np
from gymnasium import spaces

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REPO_ROOT = Path(__file__).resolve().parent.parent
EXECUTABLE = REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"
USER_CONFIG = EXECUTABLE.parent / "BattleShip.cfg.json"
REPLAY = REPO_ROOT / "tas_input_2" / "mario_743.btti"
FLAGS = (("SSB64_RL_NO_RENDER", "1"), ("SSB64_RAPHNET_DISABLE", "1"))
FALL_TICK = 431  # consumed_tick of the first game_status == 5 observation of FALL_SCRIPT (measured, M7 Phase B)


def fall_script(i: int) -> List[int]:
    """Deterministic Track 1 fall: hold right, C-up (jump) every 40 ticks; Mario leaves the right edge."""
    return [1, 3] if i % 40 == 0 else [1, 0]


class CaseFailure(AssertionError):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise CaseFailure(message)


def log(message: str) -> None:
    print(message, flush=True)


# -- spawn-importable helpers (must stay top level) -------------------------------------------------------


@dataclass(frozen=True)
class FakeSpec:
    rank: int
    marker_dir: str
    episode_length: int = 5
    truncate: bool = False
    fail_at_step: Optional[int] = None


class FakeBTTEnv(gym.Env):
    """Scripted stand-in with the Track 1 / policy-observation spaces. No game."""

    def __init__(self, spec: FakeSpec):
        self.fake_spec = spec
        self.action_space = spaces.MultiDiscrete([9, 8])
        self.observation_space = spaces.Box(-np.inf, np.inf, (15,), np.float32)
        self.t = 0
        self.total = 0
        self.episodes = 0

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.t = 0
        self.episodes += 1
        return np.full(15, float(self.fake_spec.rank), np.float32), {"m7_reset_s": 0.001, "pid": None}

    def step(self, action):
        self.t += 1
        self.total += 1
        if self.fake_spec.fail_at_step is not None and self.total == self.fake_spec.fail_at_step:
            raise RuntimeError(f"fake failure at step {self.total}")
        obs = np.full(15, 100.0 * self.fake_spec.rank + self.t, np.float32)
        done = self.t >= self.fake_spec.episode_length
        info = {"m7_service_s": 0.0001}
        return obs, -0.001, done and not self.fake_spec.truncate, done and self.fake_spec.truncate, info

    def error_context(self):
        return {"worker_episode": self.episodes, "step_in_episode": self.t}

    def ping(self, x):
        return (self.fake_spec.rank, x)

    def close(self):
        Path(self.fake_spec.marker_dir, f"closed_{self.fake_spec.rank}").write_text("closed")


class FakeFactory:
    def __init__(self, spec: FakeSpec):
        self.spec = spec

    def __call__(self):
        return FakeBTTEnv(self.spec)


def _child_factory_check(payload: bytes, queue: Any) -> None:
    factory = pickle.loads(payload)
    queue.put({"rank": factory.spec.rank, "spec": factory.spec, "torch_imported": "torch" in sys.modules,
               "sb3_imported": "stable_baselines3" in sys.modules})


def _coordinator_hammer(directory: str, seed: int, n: int, queue: Any) -> None:
    from btt_parallel import RunCoordinator

    rng = np.random.default_rng(seed)
    coord = RunCoordinator(directory)
    events = []
    for i in range(n):
        cleared = bool(rng.random() < 0.1)
        facts = {"rank": seed, "worker_episode": i + 1, "episode_id": f"e{seed}_{i}", "artifact_dir": f"a{seed}_{i}",
                 "steps": int(rng.integers(1, 3600)), "targets_broken": 10 if cleared else int(rng.integers(0, 10)),
                 "cleared": cleared, "completion_time_passed": int(rng.integers(400, 3000)) if cleared else None,
                 "completion_input_tick": None}
        events.append((facts, coord.decide(facts)))
    queue.put(events)


def _job_victim(root: str) -> None:
    """Separate trainer-like process for job_object_kill: job + 2 workers with live games, then waits to be killed."""
    from btt_parallel import RunCoordinator, WorkerFactory, WorkerSpec, initial_coordination_state
    from m7_runtime import install_kill_on_close_job, prepare_worker_runtime
    from m7_vec_env import M7SubprocVecEnv

    base = Path(root)
    job = install_kill_on_close_job()
    RunCoordinator.create(base / "coordination", initial_coordination_state("victim", "test", None))
    factories = []
    for r in range(2):
        wd = base / "workers" / f"w{r:02d}"
        prepare_worker_runtime(wd / "runtime", EXECUTABLE)
        factories.append(WorkerFactory(WorkerSpec(rank=r, run_id="victim", role="test", worker_dir=str(wd.resolve()),
                                                  coordination_dir=str((base / "coordination").resolve()),
                                                  executable=str(EXECUTABLE), horizon=600)))
    venv = M7SubprocVecEnv(factories)
    venv.reset()
    info = {"job": job.describe(), "parent": os.getpid(), "workers": [p.pid for p in venv.processes],
            "games": list(venv.game_pids)}
    (base / "victim_pids.json").write_text(json.dumps(info))
    time.sleep(600)


# -- shared game-case helpers -----------------------------------------------------------------------------


class Suite:
    def __init__(self, root: Path):
        self.root = root
        self.results: Dict[str, Any] = {}
        self.shared: Dict[str, Any] = {}

    def dir(self, name: str) -> Path:
        d = self.root / name
        d.mkdir(parents=True, exist_ok=False)
        return d


def prepare_workers(base: Path, specs_kwargs: Sequence[Dict[str, Any]], run_id: str, role: str = "test",
                    periodic: Optional[int] = None):
    from btt_parallel import RunCoordinator, WorkerFactory, WorkerSpec, initial_coordination_state
    from m7_runtime import prepare_worker_runtime

    coord = base / "coordination"
    RunCoordinator.create(coord, initial_coordination_state(run_id, role, periodic))
    factories = []
    for kw in specs_kwargs:
        rank = kw["rank"]
        wd = base / "workers" / f"w{rank:02d}"
        prepare_worker_runtime(wd / "runtime", EXECUTABLE)
        spec = WorkerSpec(run_id=run_id, role=role, worker_dir=str(wd.resolve()), coordination_dir=str(coord.resolve()),
                          executable=str(EXECUTABLE), **kw)
        factories.append(WorkerFactory(spec))
    return factories, coord


def battleship_pids() -> List[int]:
    from m7_runtime import list_processes_named

    return list_processes_named() or []


def artifact_rows_are_canonical(artifact_dir: Path) -> Dict[str, Any]:
    from btt_learning import native_to_track1
    from run_artifacts import read_artifact

    art = read_artifact(artifact_dir)
    ticks = [a.consumed_tick for a in art.actions]
    for a in art.actions:
        native_to_track1(a.buttons, a.stick_x, a.stick_y)  # raises for anything outside Track 1
    check(ticks == list(range(len(ticks))), f"{artifact_dir.name}: consumed ticks not 0..{len(ticks) - 1}")
    return {"rows": len(art.actions), "status": art.metadata["status"], "terminal": art.metadata["terminal"],
            "reasons": [m["reason"] for m in art.metadata["preservation_reasons"]]}


def short_config(suite: Suite, run_id: str, n: int, **kw: Any):
    from m7_trainer import M7Config

    base = dict(run_id=run_id, n_envs=n, total_timesteps=10240, runs_dir=suite.root, purpose="test",
                horizon=600, checkpoint_interval=5120, periodic_episodes=4)
    base.update(kw)
    return M7Config(**base)


# -- unit cases (no game) -------------------------------------------------------------------------------------


def unit_factory_pickle(suite: Suite) -> Dict[str, Any]:
    from btt_parallel import WorkerFactory, WorkerSpec, build_worker_env

    spec = WorkerSpec(rank=3, run_id="r", role="test", worker_dir=str(suite.root / "none" / "w03"),
                      coordination_dir=str(suite.root / "none" / "c"), executable=str(EXECUTABLE), base_seed=7)
    factory = WorkerFactory(spec)
    payload = pickle.dumps(factory)
    again = pickle.loads(payload)
    check(again.spec == spec, "WorkerFactory does not survive pickle")
    check(spec.worker_seed == 10, "worker seed must be base_seed + rank")
    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    p = ctx.Process(target=_child_factory_check, args=(payload, q))
    p.start()
    child = q.get(timeout=120)
    p.join(30)
    check(child["spec"] == spec and child["rank"] == 3, "spawn child did not rebuild the same spec")
    check(not child["torch_imported"] and not child["sb3_imported"],
          f"spawn child imported torch/SB3 ({child}); workers must stay light")
    try:
        build_worker_env(spec)
        raise CaseFailure("build_worker_env accepted an unprepared runtime directory")
    except RuntimeError as exc:
        check("not prepared" in str(exc), str(exc))
    return {"pickle_bytes": len(payload), "spawn_child": {k: v for k, v in child.items() if k != "spec"}}


def unit_ports(suite: Suite) -> Dict[str, Any]:
    from m7_runtime import PortCandidates, PortExhausted, dynamic_port_range, port_block, validate_port_blocks

    v = validate_port_blocks(range(8))
    dyn = dynamic_port_range()
    for r, (lo, hi) in v["blocks"].items():
        check(hi < dyn["start"], f"rank {r} block {lo}..{hi} not below the dynamic range {dyn}")
    seen = set()
    for r in range(8):
        b = set(port_block(r))
        check(not (seen & b), "blocks overlap")
        seen |= b
    pc = PortCandidates(0, start_offset=10)
    ports = [pc.claim()[0] for _ in range(5)]
    check(len(set(ports)) == 5 and all(ports[i + 1] == ports[i] + 1 for i in range(4)),
          f"consecutive claims must move to fresh candidates: {ports}")
    squatters = []
    try:
        pc2 = PortCandidates(1, start_offset=20)
        blk = port_block(1)
        for port in (blk.start + 20, blk.start + 21):  # an unrelated application holding two candidates
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("127.0.0.1", port))
            s.listen(1)
            squatters.append(s)
        port, busy = pc2.claim()
        check(busy == [blk.start + 20, blk.start + 21] and port == blk.start + 22, f"busy skip wrong: {port} {busy}")
        skipped = busy
        tiny_base = 39990  # a two-port block whose ports are both held by the squatters below
        for port in (tiny_base, tiny_base + 1):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("127.0.0.1", port))
            s.listen(1)
            squatters.append(s)
        tiny = PortCandidates(0, base=tiny_base, size=2, start_offset=0)
        try:
            tiny.claim()
            raise CaseFailure("exhausted block did not raise")
        except PortExhausted:
            pass
    finally:
        for s in squatters:
            s.close()
    try:
        port_block(40)
        raise CaseFailure("rank outside the block table accepted")
    except ValueError:
        pass
    return {"dynamic_range": dyn, "blocks": v["blocks"], "claims": ports, "busy_skipped": skipped}


def _dummy_model(tmp: Path):
    from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

    from m7_trainer import M7PPO

    spec = FakeSpec(rank=0, marker_dir=str(tmp), episode_length=16)
    venv = VecNormalize(DummyVecEnv([lambda: FakeBTTEnv(spec)] * 2), norm_obs=True, norm_reward=False, clip_obs=10.0)
    model = M7PPO("MlpPolicy", venv, n_steps=64, batch_size=64, n_epochs=1, gamma=0.999, gae_lambda=0.995, seed=0,
                  device="cpu", verbose=0)
    return model, venv


def unit_metadata(suite: Suite) -> Dict[str, Any]:
    from btt_parallel import RunCoordinator, initial_coordination_state, m7_contracts
    from m7_evaluation import CheckpointError, read_checkpoint_set
    from m7_trainer import M7Config, M7Layout, resolved_ppo_params, save_checkpoint_set

    tmp = suite.dir("unit_metadata")
    model, venv = _dummy_model(tmp)
    model.learn(128)
    coord = RunCoordinator.create(tmp / "coord", initial_coordination_state("unit", "training", 10))
    run_meta = {"run_id": "unit", "purpose": "test", "lineage": [], "contracts": m7_contracts(3600), "horizon": 3600,
                "n_envs": 2, "ppo": resolved_ppo_params(model), "seeds": {"base_seed": 0, "worker_seeds": [0, 1]},
                "executable": {"path": "x", "sha256": "y"}, "revisions": {"head": "h"}, "m6_flags": dict(FLAGS),
                "versions": {}, "torch_threads": {"requested": 1}}
    ck = tmp / "ckpt"
    saved = save_checkpoint_set(ck, model, venv, run_meta=run_meta, coordinator=coord, label="unit", rollouts=2)
    meta = read_checkpoint_set(ck, expected_contracts=m7_contracts(3600))
    required = ("num_timesteps", "n_updates", "contracts", "horizon", "n_envs", "ppo", "seeds", "executable", "revisions",
                "m6_flags", "files", "vecnormalize", "lineage", "run_id", "versions")
    missing = [k for k in required if k not in meta]
    check(not missing, f"checkpoint.json misses {missing}")
    for k in ("gamma", "gae_lambda", "batch_size", "n_epochs", "n_steps", "learning_rate", "clip_range", "ent_coef",
              "vf_coef", "max_grad_norm", "net_arch", "optimizer_defaults"):
        check(k in meta["ppo"], f"resolved PPO value {k} missing")
    check(meta["ppo"]["gamma"] == 0.999 and meta["ppo"]["gae_lambda"] == 0.995, "gamma/lambda not recorded")
    try:
        save_checkpoint_set(ck, model, venv, run_meta=run_meta, coordinator=coord, label="again", rollouts=2)
        raise CaseFailure("an existing checkpoint set was overwritten")
    except FileExistsError:
        pass
    problems = {}
    for name, mutate in (
        ("missing_vecnormalize", lambda d: (d / "vecnormalize.pkl").unlink()),
        ("tampered_vecnormalize", lambda d: (d / "vecnormalize.pkl").write_bytes(b"x" + (d / "vecnormalize.pkl").read_bytes())),
        ("tampered_model", lambda d: (d / "model.zip").write_bytes((d / "model.zip").read_bytes() + b"x")),
    ):
        d = tmp / name
        shutil.copytree(ck, d)
        mutate(d)
        try:
            read_checkpoint_set(d, expected_contracts=m7_contracts(3600))
            raise CaseFailure(f"{name} accepted")
        except CheckpointError as exc:
            problems[name] = str(exc)[:120]
    try:
        read_checkpoint_set(ck, expected_contracts=m7_contracts(1800))
        raise CaseFailure("contract mismatch (horizon) accepted")
    except CheckpointError as exc:
        problems["horizon_mismatch"] = str(exc)[:120]
    layout = M7Layout(tmp / "layout")
    layout.create()
    try:
        layout.create()
        raise CaseFailure("an existing run directory was reused")
    except FileExistsError:
        pass
    bad = []
    for kw in ({"batch_size": 500}, {"total_timesteps": 5000}, {"eval_interval": 5120, "checkpoint_interval": 10240}):
        try:
            M7Config(**({"run_id": "x", "n_envs": 4, "total_timesteps": 51200} | kw)).validate()
            bad.append(kw)
        except ValueError:
            pass
    check(not bad, f"invalid configurations accepted: {bad}")
    c4, c5 = M7Config(run_id="a", n_envs=4, total_timesteps=51200), M7Config(run_id="b", n_envs=5, total_timesteps=51200)
    check((c4.n_steps, c5.n_steps, c4.rollout_size, c5.rollout_size) == (1280, 1024, 5120, 5120), "rollout sizes")
    venv.close()
    return {"saved": saved, "refusals": problems, "files": meta["files"]}


def unit_ranking(suite: Suite) -> Dict[str, Any]:
    from m7_evaluation import aggregate, bootstrap_diff_ci, learning_evidence, objective_key, rank_episodes

    eps = [
        {"episode_id": "fast_clear", "cleared": True, "completion_time_passed": 900, "targets_broken": 10, "return": 1.0},
        {"episode_id": "slow_clear", "cleared": True, "completion_time_passed": 1500, "targets_broken": 10, "return": 50.0},
        {"episode_id": "nine", "cleared": False, "completion_time_passed": None, "targets_broken": 9, "return": 99.0},
        {"episode_id": "three", "cleared": False, "completion_time_passed": None, "targets_broken": 3, "return": 5.0},
        {"episode_id": "three_b", "cleared": False, "completion_time_passed": None, "targets_broken": 3, "return": -5.0},
    ]
    order = [e["episode_id"] for e in rank_episodes(list(reversed(eps)))]
    check(order[:3] == ["fast_clear", "slow_clear", "nine"], f"objective order wrong: {order}")
    check(order[3:] == ["three_b", "three"], f"ties must keep input order, reward ignored: {order}")
    check(objective_key({"cleared": True, "completion_time_passed": None, "targets_broken": 10}) == (0, 10, 0),
          "a clear without completion_time_passed is not a verified clear")
    rows = [dict(e, steps=100, end_reason="clear" if e["cleared"] else "horizon", status="terminal" if e["cleared"] else "truncated",
                 native_action_digest=e["episode_id"]) for e in eps]
    agg = aggregate(rows)
    check(agg["best_episode"]["episode_id"] == "fast_clear" and agg["fastest_clear"]["episode_id"] == "fast_clear", str(agg))
    d = bootstrap_diff_ci([5, 6, 7, 5, 6], [1, 2, 1, 2, 1])
    check(d["ci_low"] > 0, str(d))
    ev = learning_evidence([5, 6, 7, 5, 6], [1, 2, 1, 2], [3, 3, 4, 3])
    check(ev["learning_supported"], str(ev))
    ev2 = learning_evidence([3, 4, 3, 4], [1, 2, 1, 2], [3, 3, 4, 3])
    check(not ev2["learning_supported"], "overlapping random baseline must not support a learning claim")
    return {"order": order, "aggregate_targets_mean": agg["targets_mean"]}


def _obs(**kw: Any):
    from battleship_client import Observation

    base = dict(observation_schema=1, host_frame=0, input_tick=10, time_passed=9, game_status=1, btt_active=1,
                targets_remaining=10, fighter_valid=1, position_x=0.0, position_y=0.0, air_velocity_x=0.0,
                air_velocity_y=0.0, ground_velocity_x=0.0, facing_direction=1, ground_air_state=0, fighter_status_id=0,
                jumps_used=0)
    base.update(kw)
    return Observation(**base)


def unit_fall_rule(suite: Suite) -> Dict[str, Any]:
    from battleship_client import StepState
    from btt_parallel import is_native_failure

    cases = [
        ("first failure observation", _obs(game_status=5, targets_remaining=7), StepState.WAITING_FOR_ACTION, True),
        ("failure with all targets left", _obs(game_status=5, targets_remaining=10), StepState.WAITING_FOR_ACTION, True),
        ("clear transition (EpisodeEnded, 0 left)", _obs(game_status=5, targets_remaining=0), StepState.EPISODE_ENDED, False),
        ("EpisodeEnded with targets (never a fall)", _obs(game_status=5, targets_remaining=3), StepState.EPISODE_ENDED, False),
        ("0 left without EpisodeEnded", _obs(game_status=5, targets_remaining=0), StepState.WAITING_FOR_ACTION, False),
        ("normal play", _obs(game_status=1, targets_remaining=7), StepState.WAITING_FOR_ACTION, False),
        ("later failure screen status 6", _obs(game_status=6, targets_remaining=7), StepState.WAITING_FOR_ACTION, False),
        ("btt inactive", _obs(game_status=5, targets_remaining=7, btt_active=0), StepState.WAITING_FOR_ACTION, False),
    ]
    out = {}
    for name, o, state, expected in cases:
        got = is_native_failure(o, state)
        check(got == expected, f"{name}: is_native_failure {got}, expected {expected}")
        out[name] = got
    return out


class _ScriptedM3(gym.Env):
    """Emits M3-shaped transitions for the reward wrapper: (targets_remaining, terminated, truncated, reason)."""

    def __init__(self, script):
        self.script = script
        self.i = 0
        self.observation_space = spaces.Dict({})
        self.action_space = spaces.Discrete(1)

    def reset(self, *, seed=None, options=None):
        self.i = 0
        return {"btt_active": 1, "targets_remaining": np.array(10, np.uint32)}, {}

    def step(self, action):
        targets, term, trunc, reason = self.script[self.i]
        self.i += 1
        info = {}
        if reason:
            info["termination_reason" if term else "truncation_reason"] = reason
        return {"btt_active": 1, "targets_remaining": np.array(targets, np.uint32)}, 0.0, term, trunc, info


def unit_reward_fall(suite: Suite) -> Dict[str, Any]:
    from btt_learning import RewardContractViolation
    from btt_parallel import M7RewardWrapper

    def run(script):
        env = M7RewardWrapper(_ScriptedM3(script))
        env.reset()
        return [env.step(0)[1] for _ in script]

    fall = run([(10, False, False, None), (9, False, False, None), (8, True, False, "native_failure")])
    check([round(r, 9) for r in fall] == [-0.001, 0.999, 0.999], f"fall with a same-tick target: {fall}")
    fall0 = run([(10, True, False, "native_failure")])
    check(round(fall0[0], 9) == -0.001, f"plain fall must cost only the tick: {fall0}")
    clear = run([(1, False, False, None), (0, True, False, "native_clear")])
    check([round(r, 9) for r in clear] == [8.999, 10.999], f"clear: {clear}")
    trunc = run([(10, False, True, "max_episode_steps")])
    check(round(trunc[0], 9) == -0.001, f"horizon truncation: {trunc}")
    try:
        run([(3, True, False, "native_clear")])
        raise CaseFailure("a native clear with targets left was accepted")
    except RewardContractViolation:
        pass
    return {"fall_same_tick_target": fall, "fall_plain": fall0, "clear": clear, "truncation": trunc}


def unit_coordinator(suite: Suite) -> Dict[str, Any]:
    from btt_parallel import RunCoordinator, initial_coordination_state

    d = suite.dir("unit_coordinator")
    RunCoordinator.create(d, initial_coordination_state("unit", "training", 7))
    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    procs = [ctx.Process(target=_coordinator_hammer, args=(str(d), s, 60, q)) for s in range(6)]
    for p in procs:
        p.start()
    results = [q.get(timeout=300) for _ in procs]
    for p in procs:
        p.join(60)
    state = RunCoordinator(d).read()
    total = sum(len(r) for r in results)
    check(state["episodes_finished"] == total == 360, f"episodes_finished {state['episodes_finished']} != {total}")
    check(state["native_steps"] == sum(f["steps"] for r in results for f, _ in r), "native_steps lost an update")
    ledger = [json.loads(line) for line in (d / RunCoordinator.LEDGER).read_text().splitlines()]
    best = [e for e in ledger if e["event"] == "new_best_target_count"]
    values = [int(e["note"].split()[0]) for e in best]
    check(values == sorted(values) and len(set(values)) == len(values), f"new-best events not strictly increasing: {values}")
    check(len([e for e in ledger if e["event"] == "first_successful_clear"]) == 1, "first clear claimed != once")
    fastest = [int(e["note"].split()[1]) for e in ledger if e["event"] == "new_fastest_completed_run" and e["note"] != "first clear"]
    check(fastest == sorted(fastest, reverse=True), f"fastest clears not strictly decreasing: {fastest}")
    periodic = [e for e in ledger if e["event"] == "periodic_milestone"]
    check(len(periodic) == 360 // 7, f"periodic events {len(periodic)} != {360 // 7}")
    check(state["best_targets_broken"] == 10, "best not 10 despite clears")
    return {"episodes": total, "ledger_entries": len(ledger), "best_sequence": values, "periodic": len(periodic),
            "fastest_sequence": fastest}


def unit_vec_protocol(suite: Suite) -> Dict[str, Any]:
    from m7_vec_env import M7SubprocVecEnv, M7WorkerFailure

    d = suite.dir("unit_vec_protocol")
    specs = [FakeSpec(0, str(d), episode_length=5), FakeSpec(1, str(d), episode_length=3, truncate=True)]
    venv = M7SubprocVecEnv([FakeFactory(s) for s in specs])
    try:
        venv.seed(0)
        obs = venv.reset()
        check(obs.shape == (2, 15) and obs[1, 0] == 1.0, f"reset obs {obs[:, 0]}")
        check(venv.env_method("ping", 7) == [(0, 7), (1, 7)], "env_method routing")
        seen = {0: None, 1: None}
        for k in range(5):
            obs, rew, dones, infos = venv.step(np.zeros((2, 2), np.int64))
            for i in range(2):
                if dones[i] and seen[i] is None:
                    seen[i] = (k, infos[i]["terminal_observation"][0], infos[i]["TimeLimit.truncated"], obs[i, 0])
        check(seen[0] == (4, 5.0, False, 0.0), f"terminated auto-reset wrong: {seen[0]}")
        check(seen[1] == (2, 103.0, True, 1.0), f"truncated auto-reset wrong: {seen[1]}")
    finally:
        venv.close()
    check(all((d / f"closed_{r}").exists() for r in (0, 1)), "worker env.close() did not run on ordinary close")
    report = venv.close_report
    check(all(e["closed_cleanly"] for e in report["ranks"].values()), f"close report {report}")
    # A failing worker: the parent gets rank + command + context, the others close normally.
    d2 = suite.dir("unit_vec_protocol_fail")
    specs = [FakeSpec(0, str(d2)), FakeSpec(1, str(d2), fail_at_step=3), FakeSpec(2, str(d2))]
    venv = M7SubprocVecEnv([FakeFactory(s) for s in specs], step_timeout=60)
    err = None
    t0 = time.perf_counter()
    try:
        venv.reset()
        for _ in range(5):
            venv.step(np.zeros((3, 2), np.int64))
    except M7WorkerFailure as exc:
        err = exc
    finally:
        venv.close()
    check(err is not None and err.rank == 1 and err.failure.command == "step", f"worker failure not surfaced: {err}")
    check(err.failure.context.get("env_closed") is True, f"failed worker did not close its env: {err.failure.context}")
    check(time.perf_counter() - t0 < 60, "failure took too long to surface")
    check(all((d2 / f"closed_{r}").exists() for r in (0, 1, 2)), "some env.close() did not run after a failure")
    # KeyboardInterrupt inside step_wait with replies pending: close drains and closes everything.
    d3 = suite.dir("unit_vec_protocol_interrupt")
    venv = M7SubprocVecEnv([FakeFactory(FakeSpec(r, str(d3))) for r in range(2)])
    venv.interrupt_at_step = 2
    interrupted = False
    try:
        venv.reset()
        for _ in range(4):
            venv.step(np.zeros((2, 2), np.int64))
    except KeyboardInterrupt:
        interrupted = True
    finally:
        venv.close()
    check(interrupted and all((d3 / f"closed_{r}").exists() for r in (0, 1)), "interrupt path did not close workers")
    return {"auto_reset": {str(k): v for k, v in seen.items()}, "failure": err.failure.describe()[:300],
            "interrupt_close": {k: v for k, v in venv.close_report.items() if k != "ranks"}}


# -- game cases ---------------------------------------------------------------------------------------------------


def isolation_boot_replay(suite: Suite) -> Dict[str, Any]:
    """Isolated runtime dir: config read+written privately, archives from the exe dir, replay equivalent."""
    from battleship_process import LaunchConfig
    from btti_replay import read_btti_rows
    from m6_equivalence_regression import (NO_RENDER_RAPHNET_DISABLED_CHILD_ENV, check_frozen_contract, compare_traces,
                                           run_trace)
    from m7_runtime import file_fingerprint, prepare_worker_runtime, sha256_file

    d = suite.dir("isolation_boot_replay")
    runtime = d / "runtime"
    manifest = prepare_worker_runtime(runtime, EXECUTABLE)
    cfg = runtime / "BattleShip.cfg.json"
    data = json.loads(cfg.read_text(encoding="utf-8"))
    data["M7IsolationProbe"] = {"marker": "private-worker-config"}
    cfg.write_text(json.dumps(data, indent=4), encoding="utf-8")
    probe_hash, probe_mtime = sha256_file(cfg), cfg.stat().st_mtime_ns
    user_before = file_fingerprint(USER_CONFIG)
    rows = read_btti_rows(str(REPLAY))
    flags = {"no_render": True, "raphnet_disabled": True}
    isolated = run_trace("isolated", 1, LaunchConfig(executable=EXECUTABLE, working_dir=runtime, run_root=d / "ep_iso",
                                                     extra_env=NO_RENDER_RAPHNET_DISABLED_CHILD_ENV),
                         rows, d / "artifacts", flags)
    user_after_isolated = file_fingerprint(USER_CONFIG)
    check(user_after_isolated == user_before, "the user's config changed (hash or mtime) during the isolated run")
    after = json.loads(cfg.read_text(encoding="utf-8"))
    rewritten = sha256_file(cfg) != probe_hash or cfg.stat().st_mtime_ns != probe_mtime
    check(after.get("M7IsolationProbe", {}).get("marker") == "private-worker-config",
          "the process did not read the private config (marker lost on its save)")
    check((runtime / "logs" / "BattleShip.log").is_file(), "libultraship log not written in the private cwd")
    default = run_trace("default_cwd", 2, LaunchConfig(executable=EXECUTABLE, run_root=d / "ep_def",
                                                       extra_env=NO_RENDER_RAPHNET_DISABLED_CHILD_ENV),
                        rows, d / "artifacts", flags)
    for t in (isolated, default):
        check_frozen_contract(t)
    divergence, host_frames = compare_traces(default, isolated)
    check(divergence is None, f"isolated vs default cwd diverge: {divergence}")
    # Native replay (SSB64_BTT_INPUT) in the isolated cwd: checksum + archive resolution from ssb64.log.
    native = native_replay(runtime, d / "native")
    user_after = file_fingerprint(USER_CONFIG)
    check(user_after["sha256"] == user_before["sha256"], "the user's config bytes changed")
    # M7 stack on the same replay: clear classified as native_clear (never a fall) and btt_reward_v1 = 19.553.
    m7 = m7_replay(d / "m7_replay")
    return {"manifest": {k: manifest[k] for k in ("private_copies", "links")},
            "isolated": isolated.summary(), "default": default.summary(), "host_frames_identical": host_frames,
            "private_config": {"marker_preserved": True, "rewritten_by_game": rewritten,
                               "logs": sorted(p.name for p in (runtime / "logs").iterdir())},
            "native_replay": native, "m7_replay": m7,
            "user_config": {"before": user_before, "after_isolated_run": user_after_isolated, "after_all": user_after,
                            "note": "the default-cwd reference leg runs in build-us/Release by design"}}


def native_replay(runtime: Path, out: Path) -> Dict[str, Any]:
    out = out.resolve()  # the game resolves relative paths against its own (private) cwd
    out.mkdir(parents=True)
    env = os.environ.copy()
    for k in ("SSB64_RL_STEP", "SSB64_RL_PORT", "SSB64_RL_EXIT_ON_END", "SSB64_RL_TIMING"):
        env.pop(k, None)
    env.update({"SSB64_RL_BTT": "1", "SSB64_BTT_INPUT": str(REPLAY), "SSB64_MAX_FRAMES": "1500",
                "SSB64_SAVE_PATH": str(out / "save.bin"), "SSB64_RL_RESULT_PATH": str(out / "result.json")})
    t0 = time.perf_counter()
    r = subprocess.run([str(EXECUTABLE)], cwd=str(runtime), env=env, timeout=300, check=False)
    log_path = Path(os.environ["APPDATA"]) / "BattleShip" / "ssb64.log"
    text = log_path.read_text(encoding="utf-8", errors="replace")
    lines = [ln.strip() for ln in text.splitlines() if ("BTT Replay" in ln or "archive" in ln.lower()
                                                        or "input exhausted" in ln)]
    result = json.loads((out / "result.json").read_text())
    check("actual_checksum=0x93E9EFB4" in text and "frames=468" in text, f"native replay checksum line missing: {lines}")
    check("COMPLETE input_tick=447 time_passed=446" in text, f"native replay completion line missing: {lines}")
    exe_dir = str(EXECUTABLE.parent).lower()
    archive_lines = [ln for ln in lines if "archive" in ln.lower() and "->" in ln]
    check(archive_lines and all(exe_dir in ln.lower() for ln in archive_lines),
          f"archives not resolved from the executable directory: {archive_lines}")
    check(result.get("targets_broken") == 10 and result.get("completion_time_passed") == 446
          and result.get("completion_input_tick") == 447, f"native result {result}")
    return {"exit_code": r.returncode, "wall_s": round(time.perf_counter() - t0, 2), "log_lines": lines,
            "result": {k: result.get(k) for k in ("outcome", "targets_broken", "completion_time_passed",
                                                  "completion_input_tick", "host_frames")}}


def m7_replay(out: Path) -> Dict[str, Any]:
    from battleship_env import native_to_action
    from battleship_process import LaunchConfig
    from btt_parallel import M7BattleShipBTTEnv, M7RewardWrapper, TERMINATION_NATIVE_CLEAR
    from btti_replay import read_btti_rows
    from m7_runtime import PortCandidates, prepare_worker_runtime

    out.mkdir(parents=True)
    prepare_worker_runtime(out / "runtime", EXECUTABLE)
    base = M7BattleShipBTTEnv(LaunchConfig(executable=EXECUTABLE, working_dir=out / "runtime", run_root=out / "episodes",
                                           extra_env=dict(FLAGS)), max_episode_steps=3600, rank=0,
                              ports=PortCandidates(0))
    env = M7RewardWrapper(base)
    rewards: List[float] = []
    try:
        env.reset()
        for i, row in enumerate(read_btti_rows(str(REPLAY))):
            _o, r, term, trunc, info = env.step(native_to_action(row.buttons, row.stick_x, row.stick_y))
            rewards.append(r)
            if term or trunc:
                break
    finally:
        env.close()
    res = base.last_step_result
    check(term and not trunc and info.get("termination_reason") == TERMINATION_NATIVE_CLEAR,
          f"replay clear classified as {info.get('termination_reason')} term={term} trunc={trunc}")
    check(len(rewards) == 447 and res.consumed_tick == 446 and res.observation.input_tick == 447
          and res.observation.time_passed == 446, "replay completion values")
    total = math.fsum(rewards)
    check(abs(total - 19.553) < 1e-9, f"btt_reward_v1 baseline {total} != 19.553")
    return {"steps": len(rewards), "last_consumed_tick": res.consumed_tick, "completion_time_passed": res.observation.time_passed,
            "completion_input_tick": res.observation.input_tick, "game_status_at_clear": res.observation.game_status,
            "termination_reason": info.get("termination_reason"), "return_fsum": round(total, 9)}


def _vec_fall_run(base: Path, *, vecnormalize: bool, detect: bool = True, request_timeout: float = 10.0,
                  steps_limit: int = 800) -> Dict[str, Any]:
    from btt_learning import policy_observation_from_native
    from battleship_client import Observation
    from m7_runtime import pid_alive
    from m7_vec_env import M7SubprocVecEnv

    factories, _coord = prepare_workers(base, [dict(rank=0, horizon=3600, preserve_all=True, detect_native_failure=detect,
                                                    request_timeout=request_timeout, exit_timeout=5.0)], "fall")
    venv = M7SubprocVecEnv(factories, step_timeout=120)
    env: Any = venv
    if vecnormalize:
        from stable_baselines3.common.vec_env import VecNormalize

        env = VecNormalize(venv, norm_obs=True, norm_reward=False, clip_obs=10.0)
    out: Dict[str, Any] = {}
    try:
        env.reset()
        pid = venv.game_pids[0]
        for i in range(steps_limit):
            t0 = time.perf_counter()
            obs, rew, dones, infos = env.step(np.array([fall_script(i)]))
            wall = time.perf_counter() - t0
            if dones[0]:
                info = infos[0]
                ep = info["m7_episode"]
                native = Observation(**ep["terminal_native_observation"])
                raw = policy_observation_from_native(native)
                if vecnormalize:
                    same = bool(np.array_equal(env.normalize_obs(raw), info["terminal_observation"]))
                else:
                    same = bool(np.array_equal(raw, info["terminal_observation"]))
                out = {"done_at_step_index": i, "vector_step_wall_s": round(wall, 3),
                       "service_s": round(info.get("m7_service_s", 0.0), 4),
                       "termination_reason": info.get("termination_reason"),
                       "truncation_reason": info.get("truncation_reason"),
                       "failure_outcome": info.get("failure_outcome"),
                       "TimeLimit.truncated": info.get("TimeLimit.truncated"), "episode": ep,
                       "terminal_observation_is_post_update_failure_observation": same,
                       "terminal_game_status": native.game_status, "terminal_input_tick": native.input_tick,
                       "old_pid": pid, "old_pid_alive_after_step": pid_alive(pid),
                       "new_pid": venv.game_pids[0]}
                break
    finally:
        env.close()
    out["close"] = {k: v for k, v in (venv.close_report or {}).items() if k != "ranks"}
    return out


def fall_regression(suite: Suite) -> Dict[str, Any]:
    from btt_parallel import TERMINATION_NATIVE_FAILURE

    d = suite.dir("fall_regression")
    res = {}
    for label, vn in (("plain", False), ("vecnormalize", True)):
        r = _vec_fall_run(d / label, vecnormalize=vn)
        ep = r["episode"]
        check(r["termination_reason"] == TERMINATION_NATIVE_FAILURE and ep["end_reason"] == "fall", f"{label}: {r}")
        check(r["TimeLimit.truncated"] is False and ep["status"] == "terminal", f"{label}: must be terminated, not truncated")
        check(ep["last_consumed_tick"] == FALL_TICK and ep["steps"] == FALL_TICK + 1,
              f"{label}: fall at consumed tick {ep['last_consumed_tick']} (steps {ep['steps']}), expected {FALL_TICK}")
        check(r["terminal_game_status"] == 5 and r["terminal_input_tick"] == FALL_TICK + 1, f"{label}: terminal obs")
        check(r["terminal_observation_is_post_update_failure_observation"], f"{label}: terminal_observation mismatch")
        check(r["service_s"] < 1.0, f"{label}: fall step took {r['service_s']} s (request timeout path?)")
        check(not r["old_pid_alive_after_step"] and r["new_pid"] != r["old_pid"], f"{label}: old process not disposed")
        check(abs(ep["return"] - (-0.001 * (FALL_TICK + 1))) < 1e-9 and ep["targets_broken"] == 0,
              f"{label}: return {ep['return']} (reward v1: -0.001 per tick, no bonus, no penalty)")
        check(ep["cleared"] is False and ep["completion_time_passed"] is None, f"{label}: a fall is never a clear")
        art = artifact_rows_are_canonical(REPO_ROOT / ep["artifact_dir"] if not Path(ep["artifact_dir"]).is_absolute()
                                          else Path(ep["artifact_dir"]))
        check(art["rows"] == FALL_TICK + 1 and art["status"] == "terminal"
              and art["terminal"]["termination_reason"] == TERMINATION_NATIVE_FAILURE
              and art["terminal"]["end_reason"] == "fall", f"{label}: artifact {art}")
        res[label] = {k: v for k, v in r.items() if k != "episode"} | {"artifact": art,
                                                                       "episode_return": ep["return"]}
    return res


def request_timeout_cleanup(suite: Suite) -> Dict[str, Any]:
    d = suite.dir("request_timeout_cleanup")
    r = _vec_fall_run(d, vecnormalize=False, detect=False, request_timeout=3.0, steps_limit=900)
    ep = r["episode"]
    check(ep["end_reason"] == "lifecycle_failure" and ep["failure_outcome"] == "episode_timeout",
          f"expected the old hang -> episode_timeout path with detection disabled: {ep['end_reason']} {ep['failure_outcome']}")
    check(r["truncation_reason"] == "episode_failure" and r["TimeLimit.truncated"] is True, str(r))
    check(3.0 <= r["service_s"] < 30.0, f"timeout step took {r['service_s']} s")
    check(not r["old_pid_alive_after_step"], "timed-out process not disposed")
    check(r["close"]["forced_terminations"] == [] and not r["close"]["orphan_games_killed"], str(r["close"]))
    return {k: v for k, v in r.items() if k != "episode"} | {"steps_before_hang": ep["steps"]}


def startup_failure_retry(suite: Suite) -> Dict[str, Any]:
    from m7_runtime import pid_alive
    from m7_vec_env import M7SubprocVecEnv, M7WorkerFailure

    d = suite.dir("startup_failure_retry")
    out: Dict[str, Any] = {}
    for mode in ("post_launch", "preflight"):
        factories, _ = prepare_workers(d / mode, [dict(rank=0, horizon=600, squat_first_attempt=mode, request_timeout=3.0,
                                                       exit_timeout=3.0)], f"retry_{mode}")
        venv = M7SubprocVecEnv(factories, step_timeout=180)
        try:
            venv.reset()
            report = venv.env_method("worker_report")[0]
            fresh_pid = venv.game_pids[0]
        finally:
            venv.close()
        attempts = report["startup_attempts"]
        check(len(attempts) == 2 and attempts[0]["outcome"] != "fresh" and attempts[1]["outcome"] == "fresh",
              f"{mode}: expected one failed attempt then a fresh one: {attempts}")
        check(attempts[0]["port"] != attempts[1]["port"], f"{mode}: retry reused the failed port")
        if mode == "post_launch":
            check(attempts[0]["pid"] is not None, f"post_launch: no process was launched by the failed attempt: {attempts[0]}")
            check(attempts[0]["process_alive_after"] is False and not pid_alive(attempts[0]["pid"]),
                  "post_launch: the failed attempt's process was not killed and reaped")
            check(attempts[0]["pid"] != fresh_pid, "post_launch: the retry reused the failed process")
        out[mode] = attempts
    # All attempts failing: surfaced to the parent with rank context, nothing left running.
    factories, _ = prepare_workers(d / "exhaust", [dict(rank=0, horizon=600, squat_first_attempt="post_launch",
                                                        startup_attempts=1, request_timeout=3.0, exit_timeout=3.0)], "exhaust")
    venv = M7SubprocVecEnv(factories, step_timeout=180)
    err = None
    try:
        venv.reset()
    except M7WorkerFailure as exc:
        err = exc
    finally:
        venv.close()
    check(err is not None and err.failure.exc_type == "M7StartupError" and err.rank == 0, f"exhaustion not surfaced: {err}")
    out["exhausted"] = err.failure.describe()[:400]
    return out


def vector_smoke(suite: Suite, n: int) -> Dict[str, Any]:
    from m7_trainer import run_training

    s = run_training(short_config(suite, f"vector_smoke_n{n}", n))
    check(s["status"] == "completed" and s["cleanup"]["leak_free"], f"N={n}: {s['status']} {s['cleanup']}")
    check(s["timesteps"]["sb3_num_timesteps"] == 10240 and s["timesteps"]["n_updates"] == 20, str(s["timesteps"]))
    check(s["episodes"]["finished"] >= n, f"N={n}: too few finished episodes to exercise auto-reset")
    check(s["user_config"]["byte_identical"] and s["user_config"]["mtime_unchanged"], "user config touched")
    check(all(e.get("closed_cleanly") for e in s["cleanup"]["ranks"].values()), "a worker did not close cleanly")
    arts = [artifact_rows_are_canonical(REPO_ROOT / p) for p in s["artifacts"]["written"]]
    check(arts, "no artifact preserved")
    suite.shared[f"vector_smoke_n{n}"] = s
    return {"e2e_tps": s["throughput"]["end_to_end_transitions_per_s"], "episodes": s["episodes"],
            "restarts": s["restarts"]["reset_s"], "artifacts": len(arts), "checkpoints": [c["label"] for c in s["checkpoints"]],
            "ports": sorted({e["port"] for e in _episodes(suite.root / f"vector_smoke_n{n}")})}


def _episodes(run: Path) -> List[Dict[str, Any]]:
    p = run / "metrics" / "episodes.jsonl"
    return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []


def checkpoint_reload(suite: Suite) -> Dict[str, Any]:
    from stable_baselines3.common.vec_env import VecNormalize

    from btt_learning import track1_to_native
    from btt_parallel import m7_contracts
    from m7_evaluation import CheckpointError, obs_rms_digest, policy_parameter_digest, read_checkpoint_set
    from m7_trainer import M7PPO
    from m7_vec_env import M7SubprocVecEnv

    run = suite.root / "vector_smoke_n2"
    final = run / "final"
    meta = read_checkpoint_set(final, expected_contracts=m7_contracts(600))
    model = M7PPO.load(str(final / "model.zip"), device="cpu")
    d = suite.dir("checkpoint_reload")
    factories, _ = prepare_workers(d, [dict(rank=0, horizon=600)], "reload")
    venv = M7SubprocVecEnv(factories)
    vec = VecNormalize.load(str(final / "vecnormalize.pkl"), venv)
    vec.training, vec.norm_reward = False, False
    p0, r0 = policy_parameter_digest(model), obs_rms_digest(vec)
    actions = []
    try:
        obs = vec.reset()
        for _ in range(30):
            a, _ = model.predict(obs, deterministic=True)
            check(model.action_space.contains(a[0]), f"illegal action {a}")
            track1_to_native(a[0])
            actions.append([int(a[0][0]), int(a[0][1])])
            obs, *_ = vec.step(a)
    finally:
        vec.close()
    check(policy_parameter_digest(model) == p0 and obs_rms_digest(vec) == r0, "inference changed the model or statistics")
    refused = {}
    for name, mutate in (("missing", lambda x: (x / "vecnormalize.pkl").unlink()),
                         ("tampered", lambda x: (x / "vecnormalize.pkl").write_bytes(b"0" * 64))):
        copy = d / f"set_{name}"
        shutil.copytree(final, copy)
        mutate(copy)
        try:
            read_checkpoint_set(copy, expected_contracts=m7_contracts(600))
            raise CaseFailure(f"{name} statistics accepted")
        except CheckpointError as exc:
            refused[name] = str(exc)[:100]
    return {"num_timesteps": meta["num_timesteps"], "actions": actions[:10], "refused": refused,
            "obs_rms_count": meta["vecnormalize"]["obs_rms_count"]}


def resume_short(suite: Suite) -> Dict[str, Any]:
    from m7_evaluation import CheckpointError
    from m7_runtime import sha256_file
    from m7_trainer import run_training

    source_run = suite.root / "vector_smoke_n2"
    source = source_run / "checkpoints" / "ckpt_000005120"
    before = {str(p.relative_to(source_run)): sha256_file(p) for p in source_run.rglob("*") if p.is_file()}
    try:
        run_training(short_config(suite, "resume_bad_horizon", 2, total_timesteps=5120, resume_from=source, horizon=1200))
        raise CaseFailure("resume with a different horizon accepted")
    except CheckpointError as exc:
        bad_horizon = str(exc)[:120]
    check(not (suite.root / "resume_bad_horizon").exists(), "a rejected resume created a run directory")
    s = run_training(short_config(suite, "resume_ok", 2, total_timesteps=5120, resume_from=source))
    after = {str(p.relative_to(source_run)): sha256_file(p) for p in source_run.rglob("*") if p.is_file()}
    check(before == after, "the source run changed during resume")
    t = s["timesteps"]
    check(t["start"] == 5120 and t["sb3_num_timesteps"] == 10240 and t["transitions_this_run"] == 5120,
          f"timestep accounting {t}")
    check(s["lineage"] and s["lineage"][-1]["num_timesteps"] == 5120, f"lineage {s['lineage']}")
    check(s["status"] == "completed" and s["cleanup"]["leak_free"], str(s["status"]))
    final_meta = json.loads((suite.root / "resume_ok" / "final" / "checkpoint.json").read_text())
    check(final_meta["num_timesteps"] == 10240 and final_meta["lineage"], "final set lineage/timesteps")
    return {"timesteps": t, "lineage": s["lineage"], "rejected_horizon": bad_horizon,
            "source_files_unchanged": len(before)}


def worker_exception_cleanup(suite: Suite) -> Dict[str, Any]:
    from m7_trainer import run_training
    from m7_vec_env import M7WorkerFailure

    err = None
    t0 = time.perf_counter()
    try:
        run_training(short_config(suite, "worker_exception", 2, fault={"raise_in_step": (1, 50)}, fault_rank=1))
    except M7WorkerFailure as exc:
        err = exc
    wall = time.perf_counter() - t0
    check(err is not None and err.rank == 1 and "M7InjectedFault" in err.failure.exc_type, f"got {err!r}")
    check(err.failure.context.get("worker_episode") == 1 and err.failure.context.get("step_in_episode") == 50,
          f"context {err.failure.context}")
    s = json.loads((suite.root / "worker_exception" / "training_summary.json").read_text())
    check(s["status"] == "failed" and s["cleanup"]["leak_free"], f"{s['status']} {s['cleanup']}")
    check(battleship_pids() == [], "BattleShip left running")
    return {"failure": err.failure.describe()[:300], "wall_s": round(wall, 2), "cleanup": s["cleanup"]}


def interrupt_cleanup(suite: Suite) -> Dict[str, Any]:
    from m7_evaluation import read_checkpoint_set
    from m7_trainer import run_training

    s = run_training(short_config(suite, "interrupt", 2, interrupt_at_vec_step=300))
    check(s["status"] == "interrupted", s["status"])
    check(s["cleanup"]["leak_free"] and s["cleanup"]["close"]["forced_terminations"] == [], str(s["cleanup"]))
    meta = read_checkpoint_set(suite.root / "interrupt" / "interrupted")
    manual = [e for e in _all_artifact_meta(suite.root / "interrupt")
              if any(m["reason"] == "manual" for m in e["preservation_reasons"])]
    check(len(manual) == 2, f"expected the 2 running episodes preserved for manual, got {len(manual)}")
    return {"interrupted_set_timesteps": meta["num_timesteps"], "manual_artifacts": len(manual),
            "cleanup": s["cleanup"]["close"]}


def _all_artifact_meta(run: Path) -> List[Dict[str, Any]]:
    return [json.loads(p.read_text()) for p in run.glob("workers/*/artifacts/*/metadata.json")]


def job_object_kill(suite: Suite) -> Dict[str, Any]:
    from m7_runtime import kill_pid, pid_alive

    d = suite.dir("job_object_kill")
    proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "_job_victim", str(d)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pid_file = d / "victim_pids.json"
    deadline = time.monotonic() + 180
    while not pid_file.exists():
        check(proc.poll() is None, f"victim exited early ({proc.returncode})")
        check(time.monotonic() < deadline, "victim never reported its processes")
        time.sleep(0.5)
    info = json.loads(pid_file.read_text())
    alive_before = {p: pid_alive(p) for p in info["workers"] + info["games"]}
    check(all(alive_before.values()), f"not all processes alive before the kill: {alive_before}")
    kill_pid(proc.pid)  # TerminateProcess: no Python cleanup runs in the victim
    proc.wait(30)
    deadline = time.monotonic() + 15
    while any(pid_alive(p) for p in info["workers"] + info["games"]) and time.monotonic() < deadline:
        time.sleep(0.25)
    alive_after = {p: pid_alive(p) for p in info["workers"] + info["games"]}
    check(not any(alive_after.values()), f"processes survived the hard kill of their trainer: {alive_after}")
    return {"victim": info, "alive_after": alive_after}


# -- runner ---------------------------------------------------------------------------------------------------------

UNIT_CASES: Dict[str, Callable[[Suite], Dict[str, Any]]] = {
    "unit_factory_pickle": unit_factory_pickle,
    "unit_ports": unit_ports,
    "unit_metadata": unit_metadata,
    "unit_ranking": unit_ranking,
    "unit_fall_rule": unit_fall_rule,
    "unit_reward_fall": unit_reward_fall,
    "unit_coordinator": unit_coordinator,
    "unit_vec_protocol": unit_vec_protocol,
}
GAME_CASES: Dict[str, Callable[[Suite], Dict[str, Any]]] = {
    "isolation_boot_replay": isolation_boot_replay,
    "fall_regression": fall_regression,
    "request_timeout_cleanup": request_timeout_cleanup,
    "startup_failure_retry": startup_failure_retry,
    "vector_smoke_n2": lambda s: vector_smoke(s, 2),
    "vector_smoke_n4": lambda s: vector_smoke(s, 4),
    "vector_smoke_n5": lambda s: vector_smoke(s, 5),
    "checkpoint_reload": checkpoint_reload,
    "resume_short": resume_short,
    "worker_exception_cleanup": worker_exception_cleanup,
    "interrupt_cleanup": interrupt_cleanup,
    "job_object_kill": job_object_kill,
}
ALL_CASES = {**UNIT_CASES, **GAME_CASES}


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["_job_victim"]:
        _job_victim(argv[1])
        return 0
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cases", nargs="*", help="case names, 'unit' or 'game' (default: all)")
    parser.add_argument("--root", default=None, help="output root (default: runs/_m7_smoke_<utc>)")
    args = parser.parse_args(argv)
    names: List[str] = []
    for c in args.cases or list(ALL_CASES):
        names += list(UNIT_CASES) if c == "unit" else list(GAME_CASES) if c == "game" else [c]
    unknown = [n for n in names if n not in ALL_CASES]
    if unknown:
        parser.error(f"unknown case(s) {unknown}")
    if "checkpoint_reload" in names or "resume_short" in names:
        if "vector_smoke_n2" not in names:
            names.insert(0, "vector_smoke_n2")
    from m7_runtime import file_fingerprint, install_kill_on_close_job

    install_kill_on_close_job()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = (Path(args.root) if args.root else REPO_ROOT / "runs" / f"_m7_smoke_{stamp}").resolve()
    root.mkdir(parents=True, exist_ok=False)
    suite = Suite(root)
    user_cfg = file_fingerprint(USER_CONFIG)
    before = battleship_pids()
    if before:
        log(f"ERROR: BattleShip already running: {before}")
        return 2
    log(f"M7 smoke: {len(names)} case(s), output {root}, user config sha256 {user_cfg['sha256'][:16]}")
    failures = 0
    for name in names:
        t0 = time.perf_counter()
        try:
            details = ALL_CASES[name](suite)
            ok, error = True, None
        except Exception as exc:  # noqa: BLE001 - reported per case
            ok, error, details = False, f"{type(exc).__name__}: {exc}", {"traceback": traceback.format_exc()[-4000:]}
        from m7_runtime import wait_until_no_process

        left = wait_until_no_process(timeout=20)
        cfg_now = file_fingerprint(USER_CONFIG)
        cfg_ok = cfg_now.get("sha256") == user_cfg.get("sha256")
        if left or not cfg_ok:
            ok = False
            error = (error or "") + f" | leaked {left}" * bool(left) + " | user config bytes changed" * (not cfg_ok)
        failures += 0 if ok else 1
        suite.results[name] = {"ok": ok, "error": error, "wall_s": round(time.perf_counter() - t0, 2),
                               "battleship_after": left, "user_config_sha256_unchanged": cfg_ok,
                               "user_config_mtime_unchanged": cfg_now.get("mtime_ns") == user_cfg.get("mtime_ns"),
                               "details": details}
        log(f"{'PASS' if ok else 'FAIL'} {name} ({suite.results[name]['wall_s']} s)" + (f": {error}" if error else ""))
        with open(root / "m7_smoke_results.json", "w", encoding="utf-8", newline="\n") as fp:
            json.dump({"cases": suite.results, "user_config_start": user_cfg}, fp, indent=2, default=str)
    log(f"M7 smoke: {len(names) - failures}/{len(names)} PASS; results {root / 'm7_smoke_results.json'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
