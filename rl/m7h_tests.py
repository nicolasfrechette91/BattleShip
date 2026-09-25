"""M7h E1: unit tests (no game process). Run: python rl/m7h_tests.py [--out <json>]

Covers the pure curriculum logic, CurriculumVecEnv inside a real SB3 VecNormalize (selection only after automatic
resets, unchanged rewards / dones / terminal observations, each returned observation counted exactly once), the reward
rebase, atomic checkpoint-set writes, interruption provenance and the cooperative stop, the memory-policy levels, the
all-or-nothing [curriculum] table, and that the control path constructs and imports nothing of M7h.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Tuple

import numpy as np

RL_DIR = Path(__file__).resolve().parent
if str(RL_DIR) not in sys.path:
    sys.path.insert(0, str(RL_DIR))
REPO_ROOT = RL_DIR.parent

import m7h_curriculum as mc  # noqa: E402

RESULTS: List[Dict[str, Any]] = []


class Failure(AssertionError):
    pass


def check(cond: bool, message: str) -> None:
    if not cond:
        raise Failure(message)


# -- helpers --------------------------------------------------------------------------------------------------------


def obs_dict(tick: int, x: float, y: float, targets: int = 10, live: bool = True, host: int = 0) -> Dict[str, Any]:
    return {"observation_schema": 1, "host_frame": host, "input_tick": tick, "time_passed": max(0, tick - 1),
            "game_status": 1, "btt_active": 1 if live else 0, "targets_remaining": targets, "fighter_valid": 1 if live else 0,
            "position_x": float(x), "position_y": float(y), "air_velocity_x": 0.0, "air_velocity_y": 0.0,
            "ground_velocity_x": 0.0, "facing_direction": 1, "ground_air_state": 0, "fighter_status_id": 10,
            "jumps_used": 0}


def synthetic_report(run_id: str, episode_id: str, positions: List[Tuple[float, float]], *, prefix_len: int = 0,
                     end_reason: str = "horizon", start: Mapping[str, Any] = None, actions_seed: int = 0) -> Dict[str, Any]:
    tr = mc.EpisodeTrace(reset_observation=obs_dict(0, 0, 0), reset_step_count=0)
    for r, (x, y) in enumerate(positions):
        a = (r * 7 + actions_seed) % mc.TRACK1_ACTIONS
        tr.add_row(a, mc.track1_triple(a), r, obs_dict(r + 1, x, y), prefix=r < prefix_len)
    tr.prefix_length = prefix_len
    summary = {"worker_episode": 1, "episode_id": episode_id, "end_reason": end_reason,
               "last_consumed_tick": len(positions) - 1, "native_action_digest": tr.rows_digest.hexdigest()}
    return tr.report(start=start or {"kind": mc.START_TICK0, "prefix_length": 0}, summary=summary, run_id=run_id, rank=0)


# -- tests: pure logic -------------------------------------------------------------------------------------------------


def unit_codec_cells_digest() -> Dict[str, Any]:
    from btt_learning import track1_to_native

    for i in range(mc.TRACK1_ACTIONS):
        s, b = mc.decode_track1(i)
        check(mc.encode_track1(s, b) == i, f"codec {i}")
        n = track1_to_native((s, b))
        check(mc.track1_triple(i) == (int(n.buttons), int(n.stick_x), int(n.stick_y)), f"triple {i}")
    check(mc.cell_of(obs_dict(1, -1.0, 0.0)) == (-1, 0, 10), "floor(-1/300) = -1")
    check(mc.cell_of(obs_dict(1, -300.0, 299.9)) == (-1, 0, 10), "floor(-300/300) = -1")
    check(mc.cell_of(obs_dict(1, -300.0001, 300.0)) == (-2, 1, 10), "floor(-300.0001/300) = -2")
    check(mc.cell_of(obs_dict(1, 0, 0, live=False)) is None, "not live -> no cell")
    check(not mc.is_left(obs_dict(1, -2100.0, 0)), "x = -2100.0 is not left (strict)")
    check(mc.is_left(obs_dict(1, -2100.0001, 0)), "x < -2100 is left")
    check(not mc.is_left(obs_dict(1, -2500.0, 0, live=False)), "a non-live step is never left")
    import m7f_trace as tr

    acts = bytes([3, 17, 70, 0, 71])
    rows = [(*mc.track1_triple(a), None) for a in acts]
    check(mc.prefix_digest(acts) == tr.action_digest(rows, range(len(acts))), "prefix digest = M7 native_action_digest")
    return {"actions": mc.TRACK1_ACTIONS}


def unit_classify_and_trace() -> Dict[str, Any]:
    check(mc.classify(0, None, False) is None, "no left step")
    check(mc.classify(0, 5, False) == mc.CLASS_GENUINE, "policy entry, naive lineage")
    check(mc.classify(0, 5, True) == mc.CLASS_REENTRY, "policy entry, exposed lineage")
    check(mc.classify(2, 9, False) == mc.CLASS_PREFIX, "left step inside the prefix")
    # prefix rows x: 0, -300 ; policy rows: -300 (seen in prefix), -600 (new), -2200 (left, new)
    rep = synthetic_report("r", "e1", [(0, 0), (-300, 0), (-300, 0), (-600, 0), (-2200, 0)], prefix_len=2)
    cells = [tuple(c) for c, _row, _o in rep["first_reach"]]
    check(cells == [(-2, 0, 10), (-8, 0, 10)], f"first reach on policy rows only, not prefix-seen cells: {cells}")
    check([row for _c, row, _o in rep["first_reach"]] == [3, 4], "first-reach rows")
    check(rep["left"] == {"any_left": True, "prefix_left_steps": 0, "first_policy_left_step": 4}, f"left {rep['left']}")
    check(rep["class"] == mc.CLASS_GENUINE, "genuine class")
    check(rep["consumed_ticks_ok"] and rep["full_digest"] == rep["tracker_digest"], "digest / ticks")
    rep2 = synthetic_report("r", "e2", [(-2200, 0), (0, 0)], prefix_len=1)
    check(rep2["class"] == mc.CLASS_PREFIX, "left step on a prefix row -> prefix_reproduced")
    rep3 = synthetic_report("r", "e3", [(0, 0), (-2200, 0)], prefix_len=1, start={"kind": mc.START_PREFIX,
                            "prefix_length": 1, "lineage_left_exposed": True})
    check(rep3["class"] == mc.CLASS_REENTRY, "exposed lineage -> re-entry, never genuine")
    return {"classes": [rep["class"], rep2["class"], rep3["class"]]}


def unit_archive() -> Dict[str, Any]:
    a = mc.Archive("run")
    pos = [(float(300 * k), 0.0) for k in range(10)]
    r1 = synthetic_report("run", "e1", pos)
    res = a.ingest(r1)
    check(res["inserted"] == 10 and len(a.entries) == 10, f"first reach inserts every cell: {res}")
    e = a.entries[(3, 0, 10)]
    check(e.length == 4 and e.prefix == bytes(r1["actions"][:4]) and e.digest == mc.prefix_digest(e.prefix), "L = row + 1")
    check(e.visits == 1, "a new cell visited on a policy row counts one visit")
    # the same cells again, reached later (longer) -> no replacement; visits +1
    r2 = synthetic_report("run", "e2", [(0.0, 0.0)] + pos, actions_seed=5)
    a.ingest(r2)
    check(a.entries[(3, 0, 10)].length == 4 and a.entries[(3, 0, 10)].visits == 2, "equal/longer never replaces")
    # strictly shorter replaces the prefix, keeps visits
    r3 = synthetic_report("run", "e3", [(900.0, 0.0)], actions_seed=9)
    a.ingest(r3)
    e = a.entries[(3, 0, 10)]
    check(e.length == 1 and e.replaced == 1 and e.visits == 3 and e.source["episode_id"] == "e3", "strictly shorter replaces")
    # eligibility
    check(mc.eligibility(3000, "horizon", 3599) == (True, None), "L = 3000 eligible")
    check(not mc.eligibility(3001, "horizon", 3599)[0], "L = 3001 ineligible")
    check(not mc.eligibility(0, "horizon", 3599)[0], "L = 0 ineligible")
    check(not mc.eligibility(100, "fall", 159)[0], "fall exactly 60 ticks after step L-1 -> excluded")
    check(mc.eligibility(100, "fall", 160)[0], "fall 61 ticks after -> eligible")
    check(not mc.eligibility(100, "clear", 99)[0], "source ended within the prefix -> excluded")
    # not ingested ends, refusals
    check(a.ingest(synthetic_report("run", "e4", pos, end_reason="lifecycle_failure"))["ingested"] is False, "lifecycle")
    for bad, why in ((dict(r1, run_id="other"), "another run"), (dict(r1, full_digest="0" * 64), "digest mismatch"),
                     (dict(r1, consumed_ticks_ok=False), "consumed ticks")):
        try:
            a.ingest(bad)
            raise Failure(f"archive accepted a report with {why}")
        except mc.CurriculumError:
            pass
    # lineage exposure: a source with any left step exposes every entry it creates
    b = mc.Archive("run")
    b.ingest(synthetic_report("run", "x", [(0, 0), (-2400, 0), (0, 3000)]))
    check(all(en.lineage_left_exposed for en in b.entries.values()), "entries of a left-exposed source are exposed")
    # persistence round trip + tamper
    data, blob = a.to_json(), a.prefixes_blob()
    a2 = mc.Archive.from_json(json.loads(json.dumps(data)), blob)
    check([en.to_json() for en in a2.entries.values()] == [en.to_json() for en in a.entries.values()], "round trip")
    try:
        mc.Archive.from_json(data, bytes([(blob[0] + 1) % 72]) + blob[1:])
        raise Failure("a tampered prefix blob was accepted")
    except mc.CurriculumError:
        pass
    return {"cells": len(a.entries), "stats": a.stats}


def unit_selector() -> Dict[str, Any]:
    a = mc.Archive("run")
    s1, s2 = mc.Selector(7), mc.Selector(7)
    kinds = [s1.select(a)[0] for _ in range(200)]
    check(kinds == [s2.select(a)[0] for _ in range(200)], "deterministic for a seed")
    check(set(kinds) == {mc.START_TICK0, mc.START_TICK0_ARCHIVE_EMPTY}, "empty archive: tick0 or tick0_archive_empty")
    check(mc.Selector(7).rng.random() != mc.Selector(8).rng.random(), "different seeds differ")
    for v, x in zip((0, 3, 8), (0.0, 300.0, 600.0)):
        # the source goes on for 99 more ticks after reaching the cell, so the L = 1 prefix is eligible
        a.ingest(synthetic_report("run", f"v{v}", [(x, 0.0)] + [(x, 0.0)] * 99))
        a.entries[(int(x // 300), 0, 10)].visits = v
    check(len(a.eligible()) == 3, f"three eligible cells, got {len(a.eligible())}")
    sel = mc.Selector(1)
    n, counts, tick0 = 60000, {}, 0
    for _ in range(n):
        kind, entry, _d = sel.select(a)
        if entry is None:
            tick0 += 1
        else:
            counts[entry.cell] = counts.get(entry.cell, 0) + 1
    p0 = tick0 / n
    check(abs(p0 - 0.5) < 4 * (0.25 / n) ** 0.5, f"50/50 draw: {p0}")
    w = {c: mc.weight(e.visits) for c, e in a.entries.items()}
    tot, m = sum(w.values()), n - tick0
    for c, k in counts.items():
        p = w[c] / tot
        check(abs(k / m - p) < 4 * (p * (1 - p) / m) ** 0.5, f"cell {c}: {k / m:.4f} vs {p:.4f}")
    check(abs(mc.weight(3) - 0.5) < 1e-15 and abs(mc.weight(8) - 1 / 3) < 1e-15, "w = 1/sqrt(1+visits)")
    return {"p0": round(p0, 4), "cell_shares": {str(c): round(k / m, 4) for c, k in counts.items()}}


# -- tests: CurriculumVecEnv inside VecNormalize ------------------------------------------------------------------------


def _fake_vec_class():
    from gymnasium import spaces
    from stable_baselines3.common.vec_env.base_vec_env import VecEnv

    from m7h_vec import policy_observation_from_dict

    class FakeWorkers(VecEnv):
        """Three scripted workers: env i ends an episode every (5 + i) steps (auto-reset to a tick-0 observation)."""

        def __init__(self, run_id: str):
            super().__init__(3, spaces.Box(-1e9, 1e9, (15,), np.float32), spaces.MultiDiscrete([9, 8]))
            self.run_id = run_id
            self.t = 0
            self.len = [0, 0, 0]
            self.episode = [0, 0, 0]
            self.reset_infos = [{} for _ in range(3)]
            self.inner_outputs: List[Dict[str, Any]] = []
            self.prefix_calls: List[Tuple[int, Dict[str, Any]]] = []

        def _tick0(self, i: int) -> np.ndarray:
            return policy_observation_from_dict(obs_dict(0, 0.0, -2550.0))

        def reset(self):
            return np.stack([self._tick0(i) for i in range(3)])

        def step_async(self, actions):
            self._a = actions

        def step_wait(self):
            self.t += 1
            obs, rews, dones, infos = [], [], [], []
            for i in range(3):
                self.len[i] += 1
                o = policy_observation_from_dict(obs_dict(self.len[i], 300.0 * self.len[i] + 17 * i, 50.0 * i))
                done = self.len[i] % (5 + i) == 0
                info: Dict[str, Any] = {}
                rew = float(-0.001 * (i + 1) + (1.0 if done else 0.0))
                if done:
                    self.episode[i] += 1
                    ep = f"ep_{i}_{self.episode[i]}"
                    rep = synthetic_report(self.run_id, ep, [(300.0 * (r + 1) + 17 * i, 50.0 * i) for r in range(self.len[i])],
                                           actions_seed=i)
                    info = {"terminal_observation": o.copy(), mc_report_key(): rep,
                            "m7_episode": {"episode_id": ep, "native_action_digest": rep["full_digest"]},
                            "TimeLimit.truncated": False}
                    o = self._tick0(i)
                    self.len[i] = 0
                obs.append(o), rews.append(rew), dones.append(done), infos.append(info)
            out = (np.stack(obs), np.array(rews, dtype=np.float32), np.array(dones), infos)
            self.inner_outputs.append({"obs": out[0].copy(), "rews": out[1].copy(), "dones": out[2].copy(),
                                       "terminal": {i: inf["terminal_observation"].copy() for i, inf in enumerate(infos)
                                                    if "terminal_observation" in inf}})
            return out

        def env_method_each(self, name, calls):
            check(name == "run_prefix_phase", name)
            out = {}
            for i, (args, _kw) in calls.items():
                spec = args[0]
                self.prefix_calls.append((i, spec))
                out[i] = {"observation": policy_observation_from_dict(spec["end_observation"]),
                          "start": {"kind": mc.START_PREFIX, "prefix_length": len(spec["prefix"]),
                                    "prefix_digest": spec["prefix_digest"], "cell": spec["cell"]}}
            return out

        def close(self):
            pass

        def get_attr(self, attr_name, indices=None):
            return [None] * 3

        def set_attr(self, attr_name, value, indices=None):
            pass

        def env_method(self, method_name, *a, indices=None, **k):
            return [None] * 3

        def env_is_wrapped(self, wrapper_class, indices=None):
            return [False] * 3

    return FakeWorkers


TIMING_KEYS = ("dispatch_wall_s", "prefix_wall_s")


def strip_timing(path: Path) -> List[Dict[str, Any]]:
    """A selection log without its wall-clock fields (the only non-deterministic content)."""
    rows = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return [{k: v for k, v in r.items() if k not in TIMING_KEYS} for r in rows]


def mc_report_key() -> str:
    from m7h_worker import REPORT_KEY

    return REPORT_KEY


def _run_vec(tmp: Path, steps: int) -> Dict[str, Any]:
    from stable_baselines3.common.running_mean_std import RunningMeanStd
    from stable_baselines3.common.vec_env import VecNormalize

    from m7h_vec import CurriculumVecEnv

    fake = _fake_vec_class()("run")
    cur = CurriculumVecEnv(fake, settings=dict(mc.REGISTERED), run_id="run", seed=3, log_dir=tmp)
    returned: List[np.ndarray] = []
    orig_reset, orig_wait = cur.reset, cur.step_wait

    def spy_reset():
        o = orig_reset()
        returned.append(o.copy())
        return o

    def spy_wait():
        o, r, d, i = orig_wait()
        returned.append(o.copy())
        out = fake.inner_outputs[-1]
        check(np.array_equal(r, out["rews"]) and np.array_equal(d, out["dones"]), "rewards / dones changed")
        for k, term in out["terminal"].items():
            check(np.array_equal(i[k]["terminal_observation"], term), "terminal observation changed")
        substituted = {k for k, _s in fake.prefix_calls if k in set(np.flatnonzero(d))}
        for k in range(3):
            if k not in substituted:
                check(np.array_equal(o[k], out["obs"][k]), f"env {k}: observation changed without a prefix phase")
        return o, r, d, i

    cur.reset, cur.step_wait = spy_reset, spy_wait
    vn = VecNormalize(cur, training=True, norm_obs=True, norm_reward=False, clip_obs=10.0, gamma=0.999)
    first = vn.reset()
    check(len(fake.prefix_calls) == 0, "reset() must never select or replay a prefix")
    terms_ok = 0
    for _ in range(steps):
        n_calls = len(fake.prefix_calls)
        o, r, d, infos = vn.step(np.zeros((3, 2), dtype=np.int64))
        raw = fake.inner_outputs[-1]
        check(np.array_equal(r, raw["rews"]), "VecNormalize(norm_reward=False) changed rewards")
        for k, term in raw["terminal"].items():
            check(np.allclose(infos[k]["terminal_observation"], vn.normalize_obs(term)), "terminal normalisation")
            terms_ok += 1
        for k, spec in fake.prefix_calls[n_calls:]:
            check(bool(d[k]), f"prefix phase on env {k} without an automatic reset")
    rms = RunningMeanStd(shape=(15,))
    for batch in returned:
        rms.update(batch)
    check(abs(vn.obs_rms.count - (1e-4 + 3 * (1 + steps))) < 1e-9, f"count {vn.obs_rms.count}")
    check(np.array_equal(rms.mean, vn.obs_rms.mean) and np.array_equal(rms.var, vn.obs_rms.var) and rms.count == vn.obs_rms.count,
          "VecNormalize statistics differ from exactly-once counting of the returned observations")
    # the tick-0 observation of a substituted env never reached VecNormalize at that step
    tick0 = fake._tick0(0)
    starts = cur.stats["starts"]
    return {"steps": steps, "prefix_phases": len(fake.prefix_calls), "starts": starts, "terminal_checks": terms_ok,
            "selector": [ln for ln in (tmp / "selection.jsonl").read_text().splitlines()][:3],
            "obs_rms_count": vn.obs_rms.count, "first_obs_equal_tick0": bool(np.array_equal(first[0] * 0, tick0 * 0))}


def unit_curriculum_vecenv() -> Dict[str, Any]:
    with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
        a = _run_vec(Path(t1), 400)
        b = _run_vec(Path(t2), 400)
        la, lb = (strip_timing(Path(t) / "selection.jsonl") for t in (t1, t2))
        check(la == lb, "selection logs (timing fields removed) differ between identical runs")
    check(a["prefix_phases"] > 20 and a["starts"].get(mc.START_TICK0, 0) > 20, f"both kinds exercised: {a['starts']}")
    check(a["starts"].get(mc.START_TICK0_INITIAL) == 3, "initial resets are tick0_initial")
    return a


# -- tests: worker pieces, reward rebase -------------------------------------------------------------------------------


def unit_reward_rebase() -> Dict[str, Any]:
    import gymnasium as gym
    from gymnasium import spaces

    from btt_parallel import M7RewardWrapper
    from btt_rewards import REWARD_V2

    class Env(gym.Env):
        observation_space = spaces.Dict({})
        action_space = spaces.Discrete(1)

        def __init__(self):
            self.targets = 10

        def reset(self, *, seed=None, options=None):
            self.targets = 10
            return {"targets_remaining": 10, "btt_active": 1}, {}

        def step(self, action):
            self.targets -= 1
            return {"targets_remaining": self.targets, "btt_active": 1}, 0.0, False, False, {}

    env = Env()
    w = M7RewardWrapper(env, REWARD_V2)
    w.reset()
    env.targets = 7                                      # three breaks happen during a recorded prefix
    check(w.rebase_for_policy_phase({"targets_remaining": 7, "btt_active": 1}) == 7, "reference 7")
    _o, r, *_ = w.step(0)                                # first policy step breaks one more (7 -> 6)
    check(abs(r - (1.0 - 0.001)) < 1e-12, f"first policy reward {r}: prefix breaks must earn nothing")
    try:
        w.rebase_for_policy_phase({"targets_remaining": 6, "btt_active": 1})
        raise Failure("rebase after a policy step was accepted")
    except RuntimeError:
        pass
    return {"first_policy_reward": r}


def unit_worker_refuses_non_fresh() -> Dict[str, Any]:
    """The real worker stack (no game launched): run_prefix_phase before any reset is refused."""
    from btt_parallel import WorkerSpec, build_worker_env
    from btt_rewards import REWARD_V2
    from m7_runtime import prepare_worker_runtime, remove_worker_runtime
    from m7h_worker import CurriculumWorkerWrapper

    exe = REPO_ROOT / "build-us" / "Release" / "BattleShip.exe"
    with tempfile.TemporaryDirectory() as tmp:
        wdir = Path(tmp) / "w00"
        (Path(tmp) / "coord").mkdir()
        from btt_parallel import RunCoordinator, initial_coordination_state

        RunCoordinator.create(Path(tmp) / "coord", initial_coordination_state("unit", "training", 10))
        prepare_worker_runtime(wdir / "runtime", exe)
        try:
            spec = WorkerSpec(rank=0, run_id="unit", role="training", worker_dir=str(wdir),
                              coordination_dir=str(Path(tmp) / "coord"), executable=str(exe), reward_contract=REWARD_V2)
            env = CurriculumWorkerWrapper(build_worker_env(spec), settings=dict(mc.REGISTERED), run_id="unit", rank=0)
            prefix = bytes([0, 1, 2])
            good = {"contract": mc.CONTRACT_ID, "run_id": "unit", "prefix": prefix, "prefix_digest": mc.prefix_digest(prefix),
                    "cell": [0, 0, 10], "end_observation": obs_dict(3, 0, 0), "source": {}, "lineage_left_exposed": False}
            refused = []
            for spec_, why in ((dict(good, run_id="other"), "other run"), (dict(good, prefix_digest="0" * 64), "digest"),
                               (dict(good, prefix=b""), "empty"), (good, "not fresh (no reset)")):
                try:
                    env.run_prefix_phase(spec_)
                    raise Failure(f"run_prefix_phase accepted: {why}")
                except mc.CurriculumError as exc:
                    refused.append(f"{why}: {str(exc)[:80]}")
            check(env.base.phase == "idle", "no process was launched")
            env.close()
        finally:
            remove_worker_runtime(wdir / "runtime")
    return {"refused": refused}


# -- tests: trainer pieces (atomic sets, interruption provenance, stop) --------------------------------------------------


def _tiny_model():
    import gymnasium as gym
    from gymnasium import spaces
    from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

    import m7_trainer as tr

    class Box(gym.Env):
        observation_space = spaces.Box(-1, 1, (15,), np.float32)
        action_space = spaces.MultiDiscrete([9, 8])

        def reset(self, *, seed=None, options=None):
            return np.zeros(15, np.float32), {}

        def step(self, a):
            return np.random.uniform(-1, 1, 15).astype(np.float32), 0.0, False, False, {}

    vn = VecNormalize(DummyVecEnv([Box]), norm_obs=True, norm_reward=False)
    model = tr.M7PPO("MlpPolicy", vn, n_steps=16, batch_size=16, n_epochs=1, seed=0, device="cpu", verbose=0)
    return model, vn


def _run_meta() -> Dict[str, Any]:
    return {k: None for k in ("run_id", "purpose", "lineage", "contracts", "horizon", "n_envs", "ppo", "seeds",
                              "executable", "revisions", "m6_flags", "versions", "torch_threads")}


def unit_atomic_checkpoint_set() -> Dict[str, Any]:
    import m7_trainer as tr
    from btt_parallel import RunCoordinator, initial_coordination_state
    from m7_evaluation import read_checkpoint_set

    model, vn = _tiny_model()
    with tempfile.TemporaryDirectory() as tmp:
        coord = RunCoordinator.create(Path(tmp) / "coord", initial_coordination_state("unit", "training", 10))
        target = Path(tmp) / "checkpoints" / "ckpt_000000000"
        tr.save_checkpoint_set(target, model, vn, run_meta=_run_meta(), coordinator=coord, label=target.name, rollouts=0)
        check(target.is_dir() and not tr.incomplete_path(target).exists(), "complete set visible, no .incomplete")
        read_checkpoint_set(target)
        try:
            tr.save_checkpoint_set(target, model, vn, run_meta=_run_meta(), coordinator=coord, label=target.name, rollouts=0)
            raise Failure("overwrote an existing set")
        except FileExistsError:
            pass
        bad = Path(tmp) / "checkpoints" / "ckpt_000005120"

        def boom(d: Path) -> Dict[str, str]:
            raise RuntimeError("simulated failure while writing")
        try:
            tr.save_checkpoint_set(bad, model, vn, run_meta=_run_meta(), coordinator=coord, label=bad.name, rollouts=1,
                                   extra_writer=boom)
            raise Failure("the failing write did not raise")
        except RuntimeError:
            pass
        check(not bad.exists() and tr.incomplete_path(bad).is_dir(), "a failed write never appears under its name")
        check(not tr.incomplete_path(bad).name.startswith("ckpt_"), "the incomplete name never matches ckpt_*")
        extra = Path(tmp) / "interrupted"
        tr.save_checkpoint_set(extra, model, vn, run_meta=_run_meta(), coordinator=coord, label="interrupted", rollouts=1,
                               extra_writer=lambda d: {"x.bin": (d / "x.bin").write_bytes(b"x") and
                                                       hashlib.sha256(b"x").hexdigest()},
                               interruption={"kind": "stopped", "completed_update_checkpoint": False})
        meta = read_checkpoint_set(extra)
        check(meta["interruption"]["completed_update_checkpoint"] is False and meta["extra_files"]["x.bin"], "blocks")
    return {"incomplete_name": tr.incomplete_path(bad).name}


def unit_interruption_and_stop() -> Dict[str, Any]:
    import m7_trainer as tr

    model, vn = _tiny_model()
    with tempfile.TemporaryDirectory() as tmp:
        run = object.__new__(tr.M7Run)
        run.model, run.vecnorm, run.rollouts, run.curriculum_env = model, vn, [{}] * 4, None
        run._stop, run._ignored_stop_logged, run._phase = None, False, "setup"
        run.update_boundary, run._boundary_obs_rms = None, None
        run.layout = tr.M7Layout(Path(tmp) / "run")
        run.layout.coordination.mkdir(parents=True)
        model.num_timesteps, model._n_updates = 20480, 40
        run._snapshot_update_boundary()
        b = dict(run.update_boundary)
        # a partial rollout: timesteps and statistics advance, the policy does not
        model.num_timesteps += 1234
        vn.obs_rms.update(np.random.uniform(-1, 1, (1234, 15)))
        check(run.continue_training(), "no request -> continue")
        (run.layout.coordination / tr.STOP_REQUEST_FILE).write_text(json.dumps({"reason": "low_commit"}))
        os.environ[tr.IGNORE_STOP_ENV] = "1"
        try:
            check(run.continue_training(), "ignored in the fallback drill")
        finally:
            del os.environ[tr.IGNORE_STOP_ENV]
        check(not run.continue_training() and run._stop["trigger"] == "stop_request", "request -> stop")
        rec = run._interruption_record(run._stop)
        check(rec["completed_update_checkpoint"] is False and rec["kind"] == "stopped", "never a completed-update set")
        check(rec["policy_parameters"]["state"] == "last_completed_update"
              and rec["policy_parameters"]["equals_update_boundary_digest"], "policy at the last update")
        check(rec["num_timesteps"] == {"at_stop": 21714, "at_last_completed_update": 20480, "partial_rollout_steps": 1234},
              f"timesteps {rec['num_timesteps']}")
        check(rec["vecnormalize"]["state"] == "advanced_through_partial_rollout"
              and rec["vecnormalize"]["obs_rms_digest"] != b["obs_rms_digest"], "statistics advanced")
        check(abs(run._boundary_obs_rms.count - b["obs_rms_count"]) < 1e-9, "boundary copy kept")
        # an interrupt during optimisation: the parameters may be mid-update
        for p in model.policy.parameters():
            p.data.add_(0.01)
            break
        rec2 = run._interruption_record({"trigger": "keyboard_interrupt", "phase": "optimize"})
        check(rec2["kind"] == "interrupted" and rec2["policy_parameters"]["state"] == "possibly_mid_update"
              and not rec2["policy_parameters"]["equals_update_boundary_digest"], "mid-update flagged")
    return {"stopped": {k: rec[k] for k in ("kind", "phase_at_stop", "num_timesteps")},
            "interrupted_policy_state": rec2["policy_parameters"]["state"]}


def unit_episode_invariants() -> Dict[str, Any]:
    """m7d_run.validate_episode_row with an m7h block: prefix ticks and prefix breaks are accounted; without the block
    (tick-0 / historical rows) the checks are unchanged."""
    import m7d_run as dr
    from btt_rewards import REWARD_V2

    obs = obs_dict(3600, 0, 0, targets=5)
    base = {"rank": 0, "worker_episode": 2, "end_reason": "horizon", "targets_broken": 3, "steps": 2400,
            "return": -0.001 * 2400 + 3.0, "cleared": False, "termination_reason": None, "failure_penalty_terms": 0,
            "failure_penalty_total": 0.0, "terminal_native_observation": obs, "target_break_ticks": [1300, 2000, 3500],
            "startup_mode": "standby_promoted"}
    cur = dict(base, m7h={"prefix_length": 1200, "prefix_targets_broken": 2})
    check(dr.validate_episode_row(cur, REWARD_V2, 3600) == [], f"curriculum row: {dr.validate_episode_row(cur, REWARD_V2, 3600)}")
    plain = dr.validate_episode_row(base, REWARD_V2, 3600)
    check(len(plain) == 3, f"the same numbers without the block must fail exactly as before: {plain}")
    bad = dict(cur, m7h={"prefix_length": 1199, "prefix_targets_broken": 2})
    check(any("horizon" in x for x in dr.validate_episode_row(bad, REWARD_V2, 3600)), "L + steps != 3600 detected")
    bad2 = dict(cur, m7h={"prefix_length": 1200, "prefix_targets_broken": 1})
    check(any("targets_remaining" in x for x in dr.validate_episode_row(bad2, REWARD_V2, 3600)), "prefix breaks checked")
    bad3 = dict(cur, target_break_ticks=[1100, 2000, 3500])
    check(any("target_break_ticks" in x for x in dr.validate_episode_row(bad3, REWARD_V2, 3600)), "a break inside the prefix")
    return {"plain_row_problems": plain}


def unit_guard_levels() -> Dict[str, Any]:
    import m7h_guard as g

    p = g.REGISTERED_POLICY
    check((p.warn_gib, p.stop_gib, p.emergency_gib, p.probe_interval_s, p.escalate_after_s) == (4.0, 3.0, 1.0, 2.0, 30.0),
          "registered 4 / 3 / 1 GiB, 2 s probe, 30 s escalation")
    cases = {4.0: "ok", 3.999: "warn", 3.0: "warn", 2.999: "stop", 1.0: "stop", 0.999: "emergency", None: "stop"}
    for v, want in cases.items():
        check(g.level_of(v, p) == want, f"{v} -> {g.level_of(v, p)} (want {want})")
    check((g.LAUNCH_COMMIT_GIB, g.LAUNCH_PHYSICAL_GIB) == (10.0, 4.0), "launch gate 10 / 4 GiB")
    import m7_trainer as tr

    check((g.STOP_REQUEST_FILE, g.IGNORE_STOP_ENV) == (tr.STOP_REQUEST_FILE, tr.IGNORE_STOP_ENV), "guard/trainer names")
    return {"levels": {str(k): v for k, v in cases.items()}}


# -- tests: configuration and the control path --------------------------------------------------------------------------


CURRICULUM_TABLE = ('\n[curriculum]\ncontract = "btt_curriculum_frontier_v1"\ntick0_probability = 0.5\n'
                    'max_prefix_ticks = 3000\npre_fall_exclusion_ticks = 60\ncell_size = 300\n')


def unit_config_and_control_path() -> Dict[str, Any]:
    import experiment_config as ec
    import m7_trainer as tr
    from btt_parallel import WorkerFactory, WorkerSpec

    same = []
    for s in (0, 1, 2):
        exp = ec.load_experiment(REPO_ROOT / f"rl/configs/m7g/m7g_s{s}_v1.toml")
        saved = json.loads((REPO_ROOT / f"runs/m7g_k/m7g_s{s}_v1/experiment_resolved.json").read_text(encoding="utf-8"))
        same.append(json.loads(json.dumps(exp.resolved_json())) == saved)
        c = tr.config_from_experiment(exp)
        c.validate()
        check(c.curriculum is None and "curriculum" not in c.to_json(), "off: no curriculum key")
        check(not any(k.startswith("curriculum.") for k in c.compatibility_view()), "off: no view key")
    check(all(same), f"curriculum-off profiles resolve exactly as recorded in Phase K: {same}")
    base = (REPO_ROOT / "rl/configs/m7g/m7g_s0_v1.toml").read_text(encoding="utf-8")
    on = ec.parse_toml_text(base + CURRICULUM_TABLE)
    con = tr.config_from_experiment(on)
    con.validate()
    check(con.curriculum == mc.REGISTERED, "on: registered settings reach M7Config")
    for bad, why in ((base + CURRICULUM_TABLE.replace("cell_size = 300\n", ""), "partial table"),
                     (base + CURRICULUM_TABLE.replace("= 3000", "= 2999"), "unregistered value"),
                     (base + "\n[curriculum]\n", "empty table")):
        try:
            ec.parse_toml_text(bad)
            raise Failure(f"accepted: {why}")
        except ec.ConfigError:
            pass
    v2 = (REPO_ROOT / "rl/configs/m7g/m7g_s0_v2.toml").read_text(encoding="utf-8")
    try:
        ec.parse_toml_text(v2 + CURRICULUM_TABLE)
        raise Failure("curriculum accepted on observation v2")
    except ec.ConfigError:
        pass
    spec = WorkerSpec(rank=0, run_id="x", role="training", worker_dir="w", coordination_dir="c", executable="e")
    check(type(tr.worker_factory(tr.config_from_experiment(ec.load_experiment(REPO_ROOT / "rl/configs/m7g/m7g_s0_v1.toml")),
                                 spec)) is WorkerFactory, "off: the Phase K worker factory")
    check(type(tr.worker_factory(con, spec)).__name__ == "CurriculumWorkerFactory", "on: the curriculum factory")
    # importing the trainer imports nothing of M7h
    code = ("import sys; sys.path.insert(0, r'%s'); import m7_trainer; "
            "print(sorted(m for m in sys.modules if m.startswith('m7h')))" % RL_DIR)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300).stdout.strip()
    check(out == "[]", f"importing m7_trainer imported {out}")
    src = inspect.getsource(tr.M7Run.run)
    pinned = ("worker_factory(c, s)", "VecNormalize(self.venv, training=True, norm_obs=c.norm_obs, norm_reward=False",
              "**vecnormalize_keys(c)", "make_model(c, self.vecnorm)", "annotate_model(c, self.model)", "run_contracts(c)",
              "resolved_ppo_params(self.model, c.policy)", "norm_reward=False")
    check(all(p in src for p in pinned), "the M7d / M7e / Phase K source guards' substrings are intact")
    check("if c.curriculum is not None:" in src and "from m7h_vec import attach" in src, "attach only under the flag")
    return {"phase_k_resolved_equal": same}


def unit_isolation_guard() -> Dict[str, Any]:
    forbidden = ("rl/fixtures", "fixtures/m7g", "m7g/capture", "tas_input", "mario_743", "runs/m7f", "runs/m7g",
                 "runs/m7e", "runs/m7d", "crossing_fixture", "rl_crossing")
    hits = {}
    for name in ("m7h_curriculum.py", "m7h_worker.py", "m7h_vec.py", "m7_trainer.py"):
        text = (RL_DIR / name).read_text(encoding="utf-8").replace("\\", "/")
        found = [f for f in forbidden if f in text]
        if found:
            hits[name] = found
    check(not hits, f"training-path modules reference fixture / TAS / other-run paths: {hits}")
    ev = (RL_DIR / "m7_evaluation.py").read_text(encoding="utf-8")
    check("m7h" not in ev, "the evaluator references M7h")
    return {"modules": 4, "forbidden_fragments": len(forbidden)}


TESTS: List[Tuple[str, Callable[[], Dict[str, Any]]]] = [
    ("codec_cells_digest", unit_codec_cells_digest),
    ("classify_and_trace", unit_classify_and_trace),
    ("archive", unit_archive),
    ("selector", unit_selector),
    ("curriculum_vecenv_in_vecnormalize", unit_curriculum_vecenv),
    ("reward_rebase", unit_reward_rebase),
    ("worker_refuses_non_fresh", unit_worker_refuses_non_fresh),
    ("atomic_checkpoint_set", unit_atomic_checkpoint_set),
    ("interruption_and_stop", unit_interruption_and_stop),
    ("episode_invariants_prefix_aware", unit_episode_invariants),
    ("guard_levels", unit_guard_levels),
    ("config_and_control_path", unit_config_and_control_path),
    ("isolation_guard", unit_isolation_guard),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path)
    ap.add_argument("--only")
    args = ap.parse_args(argv)
    passed = 0
    for name, fn in TESTS:
        if args.only and name not in args.only.split(","):
            continue
        t0 = time.perf_counter()
        try:
            detail = fn()
            RESULTS.append({"test": name, "ok": True, "s": round(time.perf_counter() - t0, 2), "detail": detail})
            passed += 1
            print(f"PASS {name} ({time.perf_counter() - t0:.1f}s)", flush=True)
        except Exception as exc:  # noqa: BLE001
            RESULTS.append({"test": name, "ok": False, "error": f"{type(exc).__name__}: {exc}",
                            "traceback": traceback.format_exc()[-3000:]})
            print(f"FAIL {name}: {type(exc).__name__}: {exc}", flush=True)
    total = len([t for t in TESTS if not args.only or t[0] in args.only.split(",")])
    print(f"{passed}/{total} passed", flush=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"passed": passed, "total": total, "results": RESULTS}, indent=1, default=str),
                            encoding="utf-8")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
