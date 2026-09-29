#!/usr/bin/env python3
"""M7r unit tests (no game process): the commitment contract, executor, sidecar, semi-Markov learner, configuration.

    python rl/m7r_tests.py unit [--out DIR]

Every case runs offline. The real-data cases read the eight pinned M7q `input_all` traces (raw native replies) and
their canonical action artifacts under runs/ read-only; nothing is written under runs/ (the default output is a fresh
temporary directory).
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import gymnasium as gym
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m7r_commit as mc  # noqa: E402
from btt_learning import TRACK1_BUTTON_TABLE, TRACK1_STICK_TABLE  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
INPUT_ALL = REPO_ROOT / "runs" / "m7q" / "_equiv" / "input_all"


class Failure(AssertionError):
    pass


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise Failure(msg)


# -- fakes ---------------------------------------------------------------------------------------------------------


def reply(status: int = 1, airborne: int = 0, vy: float = 0.0, hitlag: int = 0, targets: int = 10, live: int = 1
          ) -> Dict[str, Any]:
    return {"observation": {"btt_active": live, "fighter_valid": live, "fighter_status_id": status,
                            "ground_air_state": airborne, "air_velocity_y": vy, "targets_remaining": targets},
            "entity": {"fighter": {"valid": live, "hitlag_tics": hitlag}}, "input": {"valid": live}}


class IdentityClassifier:
    def index(self, status: int) -> int:
        return int(status)


class ScriptEnv(gym.Env):
    """Stands for Track1PolicyWrapper + EntityObsV4Wrapper: one Track 1 action per tick, scripted native replies
    (replies[0] = the observe reply, replies[t + 1] = after tick t). Records every submitted word; optionally asserts
    it equals an expected word; is its own `obs_wrapper` (`_last_reply`)."""

    def __init__(self, replies: Sequence[Mapping[str, Any]], *, rewards: Optional[Sequence[float]] = None,
                 expected: Optional[Sequence[Tuple[int, int]]] = None, end: str = "terminated"):
        self.replies = list(replies)
        self.rewards = list(rewards) if rewards is not None else [-0.001] * (len(replies) - 1)
        self.expected = list(expected) if expected is not None else None
        self.end = end
        self.observation_space = gym.spaces.Box(-1e9, 1e9, (1,), np.float64)
        self.action_space = gym.spaces.MultiDiscrete([9, 8])
        self.t = 0
        self.submitted: List[Tuple[int, int]] = []
        self._last_reply: Optional[Mapping[str, Any]] = None

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        self.t = 0
        self.submitted = []
        self._last_reply = self.replies[0]
        return np.array([0.0]), {}

    def step(self, action: Any):
        word = (int(action[0]), int(action[1]))
        if self.expected is not None:
            check(self.t < len(self.expected) and word == self.expected[self.t],
                  f"tick {self.t}: submitted {word}, expected {self.expected[self.t] if self.t < len(self.expected) else None}")
        self.submitted.append(word)
        self.t += 1
        self._last_reply = self.replies[self.t]
        last = self.t == len(self.replies) - 1
        b, sx, sy = mc.native_word(word)
        info = {"consumed_tick": self.t - 1, "native_action": SimpleNamespace(buttons=b, stick_x=sx, stick_y=sy)}
        return (np.array([float(self.t)]), float(self.rewards[self.t - 1]), last and self.end == "terminated",
                last and self.end == "truncated", info)


class TrackerStub:
    def __init__(self, root: Path, preserved: bool = True):
        self.artifact_root = root
        self.preserved = preserved
        self.summaries: List[Dict[str, Any]] = []

    def extend_pending_summary(self, build: Callable[[Mapping[str, Any]], Mapping[str, Any]]) -> bool:
        # like M7EpisodeTracker: every wrapper extends the SAME pending summary of the episode that just ended (one
        # episode per stub in these cases)
        s = {"episode_id": "ep000", "preserved": self.preserved, "native_action_digest": "d"}
        s.update(build(dict(s)))
        self.summaries.append(s)
        return True


def executor_on(env: ScriptEnv, tracker: Any = None, classifier: Any = None) -> mc.CommitExecutorWrapper:
    return mc.CommitExecutorWrapper(env, obs_wrapper=env, classifier=classifier or IdentityClassifier(), tracker=tracker)


# -- reference expansion (independent of the executor's loop) ------------------------------------------------------


def ref_boundary(p: Mapping[str, Any], c: Mapping[str, Any]) -> bool:
    po, co = p["observation"], c["observation"]
    if not (po["btt_active"] and co["btt_active"]):
        return False
    pe, ce = p["entity"]["fighter"], c["entity"]["fighter"]
    return (po["fighter_status_id"] != co["fighter_status_id"] or po["ground_air_state"] != co["ground_air_state"]
            or (po["ground_air_state"] == 1 and co["ground_air_state"] == 1 and po["air_velocity_y"] > 0
                >= co["air_velocity_y"])
            or (pe["hitlag_tics"] > 0 and ce["hitlag_tics"] == 0) or co["targets_remaining"] < po["targets_remaining"])


def ref_expand(replies: Sequence[Mapping[str, Any]], options: Sequence[Sequence[int]], quota: Optional[int]
               ) -> Tuple[List[Tuple[int, int]], List[int]]:
    words: List[Tuple[int, int]] = []
    taus: List[int] = []
    t, left = 0, quota
    n_ticks = len(replies) - 1
    for o in options:
        if t >= n_ticks or (left is not None and left <= 0):
            break
        s, b, m, di = o
        d = mc.DURATIONS[di]
        i = 0
        while True:
            i += 1
            words.append((s, b if (i == 1 or m == 1) else 0))
            t += 1
            if left is not None:
                left -= 1
            if t >= n_ticks:
                break
            if i >= 2 and ref_boundary(replies[t - 1], replies[t]):
                break
            if i >= d:
                break
            if left is not None and left <= 0:
                break
        taus.append(i)
    return words, taus


def random_script(rng: np.random.Generator, n: int) -> List[Dict[str, Any]]:
    out = [reply()]
    status, air, vy, hit, tg = 1, 0, 0.0, 0, 10
    for _ in range(n):
        if rng.random() < 0.06:
            status = int(rng.integers(1, 6))
        if rng.random() < 0.04:
            air = 1 - air
        vy = float(rng.normal(0, 5)) if air else 0.0
        hit = int(rng.integers(1, 6)) if rng.random() < 0.02 else max(0, hit - 1)
        if rng.random() < 0.01 and tg > 0:
            tg -= 1
        out.append(reply(status, air, vy, hit, tg))
    return out


# -- cases ---------------------------------------------------------------------------------------------------------


def unit_duration_one_is_track1(out: Path) -> Dict[str, Any]:
    n = 0
    for s in range(9):
        for b in range(8):
            for m in (0, 1):
                env = ScriptEnv([reply(), reply(status=2)], rewards=[0.25], expected=[(s, b)])
                ex = executor_on(env)
                ex.reset()
                obs, r, term, trunc, info = ex.step(np.array([s, b, m, 0]))
                c = info["commit"]
                check(env.submitted == [(s, b)], f"({s},{b},{m}) d=1 submitted {env.submitted}")
                check(mc.native_word((s, b)) == (int(TRACK1_BUTTON_TABLE[b]), *TRACK1_STICK_TABLE[s]),
                      "native word differs from the Track 1 tables")
                check(c["tau"] == 1 and r == 0.25 and c["tick_rewards"] == [0.25] and float(obs[0]) == 1.0,
                      f"d=1 result {c} reward {r}")
                check(c["reason"] == mc.END_EPISODE, f"single-tick episode must end with episode_end, got {c['reason']}")
                n += 1
    # d = 1 inside a longer episode: the reason is max_length even when a boundary fires on that tick
    env = ScriptEnv([reply(), reply(status=5), reply(status=5)], expected=[(3, 6), (3, 6)])
    ex = executor_on(env)
    ex.reset()
    _o, _r, _t, _tr, info = ex.step(np.array([3, 6, 1, 0]))
    check(info["commit"]["reason"] == mc.END_MAX_LENGTH and info["commit"]["tau"] == 1, f"{info['commit']}")
    return {"words_checked": n, "note": "72 Track 1 words x 2 modes at d = 1: identical words, one tick each"}


def unit_no_hidden_input(out: Path) -> Dict[str, Any]:
    rng = np.random.default_rng(20260928)
    checked_ticks = checked_options = 0
    for trial in range(60):
        n = int(rng.integers(50, 400))
        replies = random_script(rng, n)
        options = [[int(rng.integers(0, 9)), int(rng.integers(0, 8)), int(rng.integers(0, 2)), int(rng.integers(0, 6))]
                   for _ in range(n + 5)]
        quota = int(rng.integers(20, n)) if trial % 3 == 0 else None
        want_words, want_taus = ref_expand(replies, options, quota)
        env = ScriptEnv(replies, expected=want_words, end="truncated" if trial % 2 else "terminated")
        ex = executor_on(env)
        ex.reset()
        if quota is not None:
            ex.commit_begin_rollout(quota)
        taus: List[int] = []
        for o in options:
            if env.t >= n or ex.quota_exhausted:
                break
            _obs, _r, term, trunc, info = ex.step(np.array(o))
            c = info["commit"]
            taus.append(c["tau"])
            check(c["first_tick"] == sum(taus[:-1]), f"trial {trial}: option starts at {c['first_tick']}, previous "
                                                       f"options ended at {sum(taus[:-1])} (a hidden tick?)")
            if term or trunc:
                break
        check(env.submitted == want_words, f"trial {trial}: submitted words differ from the reference expansion")
        check(taus == want_taus, f"trial {trial}: option lengths {taus[:12]} != reference {want_taus[:12]}")
        if quota is not None and quota < n:
            check(sum(taus) == quota and ex.quota_exhausted, f"trial {trial}: quota {quota} vs ticks {sum(taus)}")
            try:
                ex.step(np.array([0, 0, 0, 0]))
                raise Failure("a step with an exhausted quota must raise (the worker answers idle instead)")
            except mc.CommitError:
                pass
            check(ex.commit_end_rollout() == 0, "quota not used up exactly")
        checked_ticks += len(want_words)
        checked_options += len(want_taus)
    return {"trials": 60, "ticks": checked_ticks, "options": checked_options,
            "note": "words and option lengths equal an independent reference expansion; every option starts on the "
                    "tick after the previous one ended; quota cuts exact"}


def unit_boundaries(out: Path) -> Dict[str, Any]:
    c = IdentityClassifier()
    sig = lambda **k: mc.signature_of(reply(**k), c)  # noqa: E731
    check(mc.boundaries(sig(status=1), sig(status=2)) == ["class_change"], "class change")
    check(mc.boundaries(sig(airborne=0), sig(airborne=1)) == ["ground_air_change"], "ground/air change")
    check(mc.boundaries(sig(airborne=1, vy=3.0), sig(airborne=1, vy=0.0)) == ["apex"], "apex at vy 0")
    check(mc.boundaries(sig(airborne=1, vy=3.0), sig(airborne=1, vy=-1.0)) == ["apex"], "apex below 0")
    check(mc.boundaries(sig(airborne=1, vy=-3.0), sig(airborne=1, vy=-4.0)) == [], "falling: no apex")
    check(mc.boundaries(sig(airborne=0, vy=3.0), sig(airborne=0, vy=0.0)) == [], "grounded: no apex")
    check(mc.boundaries(sig(hitlag=2), sig(hitlag=0)) == ["hitlag_end"], "hitlag end")
    check(mc.boundaries(sig(hitlag=0), sig(hitlag=5)) == [], "hitlag start is not a boundary")
    check(mc.boundaries(sig(targets=5), sig(targets=4)) == ["target_break"], "target break")
    check(mc.boundaries(sig(live=1), sig(live=0, status=9)) == [], "no boundary across a non-live reply")
    check(mc.boundaries(sig(status=1, airborne=0), sig(status=2, airborne=1)) == ["class_change", "ground_air_change"],
          "order of simultaneous boundaries")
    # tick-1 suppression: a boundary on the option's first tick does not end it
    env = ScriptEnv([reply(), reply(status=2), reply(status=2), reply(status=2), reply(status=3), reply(status=3)],
                    expected=[(1, 1), (1, 0), (1, 0), (1, 0)])
    ex = executor_on(env)
    ex.reset()
    _o, _r, _t, _tr, info = ex.step(np.array([1, 1, 0, 3]))   # tap A, d = 8
    check(info["commit"]["tau"] == 4 and info["commit"]["reason"] == "class_change",
          f"tick-1 change ignored, tick-4 change ends the option: {info['commit']}")
    return {"cases": 13}


def unit_sidecar_expansion(out: Path) -> Dict[str, Any]:
    rng = np.random.default_rng(7)
    replies = random_script(rng, 300)
    tracker = TrackerStub(out / "artifacts")
    env = ScriptEnv(replies)
    ex = executor_on(env, tracker=tracker)
    ex.reset()
    while True:
        o = [int(rng.integers(0, 9)), int(rng.integers(0, 8)), int(rng.integers(0, 2)), int(rng.integers(0, 6))]
        _obs, _r, term, trunc, _info = ex.step(np.array(o))
        if term or trunc:
            break
    s = tracker.summaries[-1]
    check(s["commit"]["sidecar"] == mc.SIDECAR_FILE, f"sidecar not written: {s}")
    doc = mc.read_sidecar(out / "artifacts" / s["episode_id"] / mc.SIDECAR_FILE)
    rows = [(t, *mc.native_word(w)) for t, w in enumerate(env.submitted)]
    problems = mc.check_expansion(doc, rows, allow_rollout_cut=False)
    check(problems == [], f"exact record reported problems: {problems[:3]}")
    detected = {}
    bad = json.loads(json.dumps(doc))
    bad["decisions"][3]["tau"] += 1
    detected["tau_changed"] = bool(mc.check_expansion(bad, rows, allow_rollout_cut=False))
    rows2 = list(rows)
    rows2[5] = (rows2[5][0], rows2[5][1] ^ 0x8000 if rows2[5][1] != 0x8000 else 0, rows2[5][2], rows2[5][3])
    detected["word_changed"] = bool(mc.check_expansion(doc, rows2, allow_rollout_cut=False))
    bad = json.loads(json.dumps(doc))
    k = next(i for i, d in enumerate(bad["decisions"][:-1]) if d["reason"] == mc.END_MAX_LENGTH and d["tau"] >= 2) \
        if any(d["reason"] == mc.END_MAX_LENGTH and d["tau"] >= 2 for d in bad["decisions"][:-1]) else None
    if k is not None:
        bad["decisions"][k]["reason"] = mc.END_ROLLOUT
        detected["rollout_cut_in_evaluation"] = bool(mc.check_expansion(bad, rows, allow_rollout_cut=False))
    bad = json.loads(json.dumps(doc))
    kb = next((i for i, d in enumerate(bad["decisions"]) if d["reason"] in mc.BOUNDARY_EVENTS), None)
    if kb is not None:
        bad["decisions"][kb]["reason"] = mc.END_MAX_LENGTH
        detected["boundary_relabelled"] = bool(mc.check_expansion(bad, rows, allow_rollout_cut=False))
    rows3 = rows + [(len(rows), 0, 0, 0)]
    detected["extra_tick"] = bool(mc.check_expansion(doc, rows3, allow_rollout_cut=False))
    check(all(detected.values()), f"a mutation went undetected: {detected}")
    return {"decisions": len(doc["decisions"]), "ticks": doc["ticks"], "mutations_detected": detected}


def _track1_of(native: Tuple[int, int, int]) -> Tuple[int, int]:
    b, sx, sy = native
    s = [tuple(v) for v in TRACK1_STICK_TABLE].index((sx, sy))
    return s, [int(v) for v in TRACK1_BUTTON_TABLE].index(b)


def _pinned() -> List[Tuple[str, Dict[str, Any], List[Tuple[int, int, int, int]]]]:
    import m7f_trace as mt

    out = []
    for p in sorted(INPUT_ALL.glob("fx_*.json.gz")):
        tr = mt.read_trace(p)
        acts, _meta = mt.artifact_actions(REPO_ROOT / tr["artifact"])
        out.append((p.name.replace(".json.gz", ""), tr, [(int(a[3]), int(a[0]), int(a[1]), int(a[2])) for a in acts]))
    return out


def _greedy_options(replies: Sequence[Mapping[str, Any]], words: Sequence[Tuple[int, int]], classifier: Any
                    ) -> List[List[int]]:
    sigs = [mc.signature_of(r, classifier) for r in replies]
    n = len(words)
    options, t = [], 0
    while t < n:
        chosen = None
        for di in reversed(range(len(mc.DURATIONS))):
            for m in (1, 0):
                d = mc.DURATIONS[di]
                s, b = words[t]
                i = 0
                ok = True
                while True:
                    i += 1
                    if t + i - 1 >= n or words[t + i - 1] != (s, b if (i == 1 or m == 1) else 0):
                        ok = False
                        break
                    if t + i >= n or (i >= 2 and mc.boundaries(sigs[t + i - 1], sigs[t + i])) or i >= d:
                        break
                if ok:
                    chosen = [s, b, m, di]
                    break
            if chosen:
                break
        assert chosen is not None
        options.append(chosen)
        d, i = mc.DURATIONS[chosen[3]], 0   # its length under the contract's own (class-table) boundary rule
        while True:
            i += 1
            if t + i >= n or (i >= 2 and mc.boundaries(sigs[t + i - 1], sigs[t + i])) or i >= d:
                break
        t += i
    return options


def unit_real_replies(out: Path) -> Dict[str, Any]:
    """The executor driven by the eight pinned native reply traces: d = 1 identity and a greedy re-segmentation into
    longer options both reproduce every recorded canonical word; the sidecars pass the expansion check."""
    import m7q_status_table as st2

    if not INPUT_ALL.is_dir():
        return {"skipped": f"{INPUT_ALL} missing"}
    classifier = st2.ActionClassifier(st2.load_table(), "mario")
    report = {}
    for name, tr, acts in _pinned():
        replies = [tr["initial"]] + list(tr["steps"])
        words = [_track1_of((b, sx, sy)) for _t, b, sx, sy in acts]
        check(len(words) == len(tr["steps"]), f"{name}: {len(words)} actions vs {len(tr['steps'])} replies")
        rec = {}
        for label, options in (("d1", [[s, b, 0, 0] for s, b in words]),
                               ("greedy", _greedy_options(replies, words, classifier))):
            tracker = TrackerStub(out / "real" / name / label)
            env = ScriptEnv(replies, expected=words, end="terminated")
            ex = mc.CommitExecutorWrapper(env, obs_wrapper=env, classifier=classifier, tracker=tracker)
            ex.reset()
            taus, reasons = [], {}
            for o in options:
                _obs, _r, term, trunc, info = ex.step(np.array(o))
                taus.append(info["commit"]["tau"])
                reasons[info["commit"]["reason"]] = reasons.get(info["commit"]["reason"], 0) + 1
                if term or trunc:
                    break
            check(env.submitted == words, f"{name}/{label}: submitted words differ from the recorded canonical words")
            doc = mc.read_sidecar(Path(tracker.artifact_root) / tracker.summaries[-1]["episode_id"] / mc.SIDECAR_FILE)
            problems = mc.check_expansion(doc, acts, allow_rollout_cut=False)
            check(problems == [], f"{name}/{label}: expansion problems {problems[:3]}")
            rec[label] = {"decisions": len(taus), "ticks": sum(taus), "tau_mean": round(sum(taus) / len(taus), 3),
                          "reasons": reasons}
        report[name] = rec
    return report


def unit_gae(out: Path) -> Dict[str, Any]:
    import torch as th
    from gymnasium import spaces
    from stable_baselines3.common.buffers import RolloutBuffer

    from m7r_ppo import smdp_gae

    rng = np.random.default_rng(3)
    gamma, lam, n, envs = 0.999, 0.995, 64, 3
    buf = RolloutBuffer(n, spaces.Box(-1, 1, (2,)), spaces.Discrete(2), gamma=gamma, gae_lambda=lam, n_envs=envs)
    rewards = rng.normal(0, 1, (n, envs)).astype(np.float32)
    values = rng.normal(0, 1, (n, envs)).astype(np.float32)
    dones = (rng.random((n, envs)) < 0.08)
    for j in range(n):
        starts = np.zeros(envs, dtype=np.float32) if j == 0 else dones[j - 1].astype(np.float32)
        buf.add(np.zeros((envs, 2), np.float32), np.zeros((envs, 1)), rewards[j], starts,
                th.tensor(values[j]), th.zeros(envs))
    last = rng.normal(0, 1, envs).astype(np.float32)
    buf.compute_returns_and_advantage(th.tensor(last), dones[-1])
    worst = 0.0
    for e in range(envs):
        adv, ret = smdp_gae(rewards[:, e], values[:, e], [1] * n, dones[:, e], float(last[e]), gamma, lam)
        worst = max(worst, float(np.abs(adv - buf.advantages[:, e]).max()), float(np.abs(ret - buf.returns[:, e]).max()))
    check(worst < 1e-4, f"tau = 1 differs from SB3's GAE by {worst}")
    # tau > 1: lambda = 1 gives the discounted return with a gamma^tau bootstrap; lambda = 0 the one-step SMDP TD
    taus = rng.integers(1, 33, 40).tolist()
    r = rng.normal(0, 1, 40).tolist()
    v = rng.normal(0, 1, 40).tolist()
    d = [False] * 40
    d[17] = True
    adv, ret = smdp_gae(r, v, taus, d, 0.7, gamma, 1.0)
    g, exp_ret = 0.7, [0.0] * 40
    for j in reversed(range(40)):
        g = r[j] + (gamma ** taus[j]) * (0.0 if d[j] else g)
        exp_ret[j] = g
    check(max(abs(a - b) for a, b in zip(ret, exp_ret)) < 1e-4, "lambda = 1 returns differ from the discounted return")
    adv0, _ = smdp_gae(r, v, taus, d, 0.7, gamma, 0.0)
    exp0 = [r[j] + (gamma ** taus[j]) * (0.0 if d[j] else (v[j + 1] if j < 39 else 0.7)) - v[j] for j in range(40)]
    check(max(abs(a - b) for a, b in zip(adv0, exp0)) < 1e-4, "lambda = 0 advantages differ from the one-step SMDP TD")
    return {"tau1_max_abs_diff_vs_sb3": worst, "cases": 3}


class FakeCommitEnv(gym.Env):
    """A commitment environment without the game: v4 observation space, the commit action space, a rollout quota,
    idle replies once it is used up, variable option lengths, falls and horizon truncations."""

    def __init__(self, seed: int = 0, horizon: int = 300):
        import m7q_obs as mq

        self.observation_space = mq.make_observation_space()
        self.action_space = mc.make_action_space()
        self.rng = np.random.default_rng(seed)
        self.horizon = horizon
        self.quota: Optional[int] = None
        self.t = 0

    def _obs(self) -> Dict[str, np.ndarray]:
        return {k: self.rng.normal(0, 0.1, s.shape).astype(np.float32) for k, s in self.observation_space.spaces.items()}

    def reset(self, *, seed: Optional[int] = None, options: Optional[dict] = None):
        self.t = 0
        self.last = self._obs()
        return self.last, {}

    def commit_begin_rollout(self, ticks: int) -> bool:
        self.quota = int(ticks)
        return True

    def commit_end_rollout(self) -> int:
        q, self.quota = self.quota, None
        return int(q or 0)

    def step(self, action: Any):
        if self.quota is not None and self.quota <= 0:
            return self.last, 0.0, False, False, {"commit": {"idle": True}}
        o = mc.decode(np.asarray(action, dtype=np.int64))
        tau = min(o.d, int(self.rng.integers(1, o.d + 1)), self.horizon - self.t,
                  self.quota if self.quota is not None else 10 ** 9)
        self.t += tau
        if self.quota is not None:
            self.quota -= tau
        fall = self.rng.random() < 0.01
        rewards = [-0.001] * tau
        if self.rng.random() < 0.05:
            rewards[-1] += 1.0
        if fall:
            rewards[-1] += -5.0
        truncated = not fall and self.t >= self.horizon
        self.last = self._obs()
        info = {"commit": {"tau": tau, "reason": "max_length", "tick_rewards": rewards, "option": o.to_json(),
                           "idle": False}}
        return self.last, float(sum(rewards)), bool(fall), bool(truncated), info


def unit_commit_ppo(out: Path) -> Dict[str, Any]:
    from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

    from m7r_ppo import CommitPPO

    venv = DummyVecEnv([lambda s=s: FakeCommitEnv(seed=s) for s in range(2)])
    vn = VecNormalize(venv, training=True, norm_obs=False, norm_reward=False, gamma=0.999)
    n_steps, batch = 128, 32
    model = CommitPPO("MultiInputPolicy", vn, n_steps=n_steps, batch_size=batch, n_epochs=2, gamma=0.999,
                      gae_lambda=0.995, seed=1, device="cpu", verbose=0, m7r_minibatches=(2 * n_steps) // batch,
                      policy_kwargs={"net_arch": {"pi": [64, 64], "vf": [64, 64]}})
    model.learn(total_timesteps=3 * 2 * n_steps)
    recs = model.m7r_rollouts
    check(model.num_timesteps == 3 * 2 * n_steps, f"num_timesteps {model.num_timesteps} != native ticks")
    check(len(recs) == 3, f"{len(recs)} rollouts")
    for r in recs:
        check(r["native_ticks"] == 2 * n_steps and r["native_ticks_per_env"] == [n_steps, n_steps],
              f"rollout ticks {r['native_ticks_per_env']}")
        check(r["minibatches_per_epoch"] == 8 and r["gradient_steps"] == 16 and r["epochs"] == 2,
              f"gradient steps {r}")
        check(r["decisions"] == sum(r["decisions_per_env"]) and r["decisions"] < r["native_ticks"], "decision counts")
        check(r["optimizer_samples"] == r["decisions"] * 2, "optimizer exposure")
    check(recs[-1]["cumulative"]["ticks"] == 3 * 2 * n_steps, "cumulative ticks")
    vn.close()
    return {"rollouts": [{k: r[k] for k in ("native_ticks", "decisions", "idle_replies", "tau_mean", "gradient_steps",
                                            "minibatch_size_min", "minibatch_size_max")} for r in recs]}


def unit_worker_idle(out: Path) -> Dict[str, Any]:
    import m7r_worker as mrw

    class Inner(gym.Env):
        observation_space = gym.spaces.Box(-1, 1, (1,))
        action_space = mc.make_action_space()
        calls = 0

        def reset(self, *, seed=None, options=None):
            return np.zeros(1), {}

        def step(self, action):
            Inner.calls += 1
            return np.ones(1), 1.0, False, False, {"commit": {"tau": 3}, "noise": 1}

    ex = SimpleNamespace(quota_exhausted=False, last_obs=np.full(1, 7.0), last_commit_info={"tau": 3, "reason": "apex"})
    tracker = SimpleNamespace(_ledger=lambda r: None, pop_summary=lambda: None, episodes_started=1)
    base = SimpleNamespace(standby=None, ledger_hook=None)
    spec = SimpleNamespace(rank=2, fault=None)
    w = mrw.M7rWorkerWrapper(Inner(), spec=spec, base=base, tracker=tracker, recording=None, executor=ex)
    obs, r, term, trunc, info = w.step(np.zeros(4, dtype=np.int64))
    check(Inner.calls == 1 and info["commit"] == ex.last_commit_info and "noise" not in info and r == 1.0,
          f"normal step: {info}")
    ex.quota_exhausted = True
    obs, r, term, trunc, info = w.step(np.zeros(4, dtype=np.int64))
    check(Inner.calls == 1, "an idle reply must not step the environment")
    check(info["commit"]["idle"] is True and r == 0.0 and not term and not trunc and float(obs[0]) == 7.0,
          f"idle reply {info}")
    check(w.idle_replies == 1, "idle replies counted")
    return {"cases": 2}


def unit_config(out: Path) -> Dict[str, Any]:
    import experiment_config as ec
    import m7_trainer as tr
    import m7r_worker as mrw

    res = {}
    for arm in ("commit", "tick"):
        for s in (0, 1, 2):
            p = REPO_ROOT / "rl" / "configs" / "m7r" / f"m7r_s{s}_{arm}.toml"
            exp = ec.load_experiment(p)
            cfg = tr.config_from_experiment(exp)
            cfg.validate()
            check(cfg.total_timesteps == 307200 and cfg.n_steps == 1024 and cfg.rollout_size == 5120
                  and cfg.checkpoint_interval == 102400 and cfg.observation_v4, f"{p.name}: geometry")
            check(cfg.action_commit == (arm == "commit"), f"{p.name}: action {cfg.action}")
            j = cfg.to_json()
            check(("action" in j) == (arm == "commit"), f"{p.name}: to_json action key")
            check(cfg.compatibility_view()["contracts.action"] == exp.values["contracts.action"], "compat view action")
            contracts = tr.run_contracts(cfg)
            check(("action_contract" in contracts) == (arm == "commit"), f"{p.name}: run contracts")
            fac = tr.worker_factory(cfg, SimpleNamespace(extra_env=cfg.extra_env))
            check(isinstance(fac, mrw.M7rCommitWorkerFactory) == (arm == "commit"), f"{p.name}: worker factory")
            check(("action_contract" in exp.summary()) == (arm == "commit"), f"{p.name}: summary block")
            res[p.name] = {"semantic_fingerprint": exp.semantic_fingerprint[:16],
                           "compatibility_fingerprint": exp.compatibility_fingerprint[:16]}
    # the two arms of a seed differ exactly in contracts.action (and name / notes)
    for s in (0, 1, 2):
        a = ec.load_experiment(REPO_ROOT / "rl" / "configs" / "m7r" / f"m7r_s{s}_commit.toml").values
        b = ec.load_experiment(REPO_ROOT / "rl" / "configs" / "m7r" / f"m7r_s{s}_tick.toml").values
        diff = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
        check(diff == ["contracts.action", "run.name", "run.notes"], f"seed {s}: arms differ in {diff}")
    text = (REPO_ROOT / "rl" / "configs" / "m7r" / "m7r_s0_commit.toml").read_text(encoding="utf-8")
    rejected = {}
    for label, old, new in (
            ("observation v3", 'observation = "btt_policy_obs_v4_input"', 'observation = "btt_policy_obs_v3_entities"'),
            ("horizon 1800", "horizon = 3600", "horizon = 1800"),
            ("reward v1", 'reward = "btt_reward_v2"\n', 'reward = "btt_reward_v1"\n')):
        try:
            t = text.replace(old, new)
            if label == "reward v1":
                t = t.replace("failure_penalty = -5.0", "failure_penalty = 0.0")
            ec.parse_toml_text(t)
            rejected[label] = False
        except ec.ConfigError:
            rejected[label] = True
    check(all(rejected.values()), f"invalid commit profiles accepted: {rejected}")
    return {"profiles": res, "rejected": rejected}


def unit_evaluation_defaults(out: Path) -> Dict[str, Any]:
    from m7_evaluation import EvaluationSettings

    s = EvaluationSettings(executable="x")
    check(s.action is None and s.gate_trace is False, "evaluation defaults changed")
    return {"action": s.action, "gate_trace": s.gate_trace}


def unit_contract_identity(out: Path) -> Dict[str, Any]:
    d1, d2 = mc.contract_digest(), mc.contract_digest()
    check(d1 == d2 and len(d1) == 64, "digest not stable")
    desc = mc.contract_description()
    check(desc["space"]["nvec"] == [9, 8, 2, 6] and desc["components"]["max_length"]["values"] == [1, 2, 4, 8, 16, 32],
          "contract description")
    check(desc["components"]["button"]["native"] == [int(b) for b in TRACK1_BUTTON_TABLE], "button table")
    return {"contract": mc.CONTRACT, "sha256": d1}


def unit_gate_measures_real(out: Path) -> Dict[str, Any]:
    """Gate-trace rows built from the pinned real replies (as GateTraceWrapper would) and the gate measures."""
    import m7q_status_table as st2
    import m7r_analysis as ma
    import m7r_worker as mrw

    if not INPUT_ALL.is_dir():
        return {"skipped": f"{INPUT_ALL} missing"}
    classifier = st2.ActionClassifier(st2.load_table(), "mario")
    rep = {}
    for name, tr, acts in _pinned():
        rows = [mrw.trace_row(-1, None, tr["initial"], classifier)]
        for (t, b, sx, sy), r in zip(acts, tr["steps"]):
            rows.append(mrw.trace_row(t, SimpleNamespace(buttons=b, stick_x=sx, stick_y=sy), r, classifier))
        m = ma.episode_measures(rows, st2.CLASSES)
        check(m["T"] >= 0 and m["RE1"] >= 1, f"{name}: measures {m}")
        rep[name] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items() if k != "floors"}
    return rep


class _FakeClient:
    """Serves one recorded trace: `observe` returns the tick-0 reply, each `step` the next recorded reply."""

    def __init__(self, trace: Mapping[str, Any]):
        self.initial, self.steps, self.k = trace["initial"], list(trace["steps"]), 0

    def request(self, op: str, **payload: Any) -> Dict[str, Any]:
        if op == "observe":
            return self.initial
        if op == "step":
            r = self.steps[self.k]
            self.k += 1
            return r
        raise ValueError(op)


class _FakeTrack1(gym.Env):
    """Stands for Track1PolicyWrapper and everything below it: submits each Track 1 word as a `step` request through
    the episode client (so the v4 wrapper's request capture sees it) and asserts it is the recorded word."""

    def __init__(self, trace: Mapping[str, Any], words: Sequence[Tuple[int, int]]):
        from btt_learning import make_policy_observation_space

        self.trace, self.words = trace, list(words)
        self.observation_space = make_policy_observation_space()
        self.action_space = gym.spaces.MultiDiscrete([9, 8])
        self.base = SimpleNamespace(episode=None, last_observe=None, last_step_result=None)
        self.submitted: List[Tuple[int, int]] = []

    def reset(self, *, seed=None, options=None):
        self.base.episode = SimpleNamespace(client=_FakeClient(self.trace))
        self.base.last_observe = SimpleNamespace(observation=dict(self.trace["initial"]["observation"]))
        self.base.last_step_result = None
        self.submitted = []
        return np.zeros(15, dtype=np.float32), {}

    def step(self, action):
        w = (int(action[0]), int(action[1]))
        t = len(self.submitted)
        check(t < len(self.words) and w == self.words[t], f"tick {t}: submitted {w}, recorded {self.words[t] if t < len(self.words) else None}")
        self.submitted.append(w)
        r = self.base.episode.client.request("step", buttons=0, stick_x=0, stick_y=0)
        self.base.last_step_result = SimpleNamespace(step_count=r["step_count"])
        last = len(self.submitted) == len(self.words)
        b, sx, sy = mc.native_word(w)
        info = {"consumed_tick": t, "native_action": SimpleNamespace(buttons=b, stick_x=sx, stick_y=sy)}
        return np.zeros(15, dtype=np.float32), -0.001, last, False, info


def unit_real_stack(out: Path) -> Dict[str, Any]:
    """The real EntityObsV4Wrapper (v4 builder on every reply) under GateTraceWrapper and CommitExecutorWrapper, fed
    the recorded native replies of the pinned traces: re-segmented options reproduce every recorded word, the
    observation at each decision point is bit-identical to the per-tick stack's observation at that tick, and the gate
    trace rows equal rows computed directly from the replies."""
    import m7q_obs as mq
    import m7q_status_table as st2
    import m7r_worker as mrw

    if not INPUT_ALL.is_dir():
        return {"skipped": f"{INPUT_ALL} missing"}
    classifier = st2.ActionClassifier(st2.load_table(), "mario")
    rep = {}
    for name, tr, acts in _pinned()[:4]:
        words = [_track1_of((b, sx, sy)) for _t, b, sx, sy in acts]
        # per-tick reference: every observation of the v4 stack
        inner = _FakeTrack1(tr, words)
        ref = mq.EntityObsV4Wrapper(inner, base=inner.base, character="mario")
        ref_obs = [ref.reset()[0]]
        for w in words:
            o, _r, term, _tr, _i = ref.step(np.array(w))
            ref_obs.append(o)
        # the commit stack on the same replies
        inner2 = _FakeTrack1(tr, words)
        v4 = mq.EntityObsV4Wrapper(inner2, base=inner2.base, character="mario")
        tracker = TrackerStub(out / name)
        trace_w = mrw.GateTraceWrapper(v4, obs_wrapper=v4, tracker=tracker, character="mario")
        ex = mc.CommitExecutorWrapper(trace_w, obs_wrapper=v4, classifier=st2.ActionClassifier(st2.load_table(), "mario"),
                                      tracker=tracker)
        obs0, _ = ex.reset()
        check(all(np.array_equal(obs0[k], ref_obs[0][k]) for k in obs0), f"{name}: reset observation differs")
        options = _greedy_options([tr["initial"]] + list(tr["steps"]), words, classifier)
        t, decisions = 0, 0
        for o in options:
            obs, _r, term, trunc, info = ex.step(np.array(o))
            t += info["commit"]["tau"]
            decisions += 1
            check(all(np.array_equal(obs[k], ref_obs[t][k]) for k in obs),
                  f"{name}: decision {decisions}: observation after tick {t - 1} differs from the per-tick stack")
            check(mq.flatten({k: v[None] for k, v in obs.items()}).shape[-1] == mq.FLAT_SIZE, "flat size")
            if term or trunc:
                break
        check(inner2.submitted == words, f"{name}: submitted words differ")
        ep = tracker.summaries[0]["episode_id"]   # the recorder builds first, the executor second (same episode)
        doc = __import__("m7r_analysis").read_trace(out / name / ep / mrw.GATE_TRACE_FILE)
        direct = [mrw.trace_row(-1, None, tr["initial"], classifier)] + [
            mrw.trace_row(tt, SimpleNamespace(buttons=b, stick_x=sx, stick_y=sy), r, classifier)
            for (tt, b, sx, sy), r in zip(acts, tr["steps"])]
        check(json.loads(json.dumps(direct)) == doc["rows"], f"{name}: gate trace rows differ from direct rows")
        side = mc.read_sidecar(out / name / ep / mc.SIDECAR_FILE)
        check(mc.check_expansion(side, acts, allow_rollout_cut=False) == [], f"{name}: expansion check")
        rep[name] = {"ticks": t, "decisions": decisions, "v4_stale_steps": v4.stale_steps}
    return rep


CASES: Dict[str, Callable[[Path], Dict[str, Any]]] = {
    "unit_duration_one_is_track1": unit_duration_one_is_track1,
    "unit_no_hidden_input": unit_no_hidden_input,
    "unit_boundaries": unit_boundaries,
    "unit_sidecar_expansion": unit_sidecar_expansion,
    "unit_real_replies": unit_real_replies,
    "unit_real_stack": unit_real_stack,
    "unit_gae": unit_gae,
    "unit_commit_ppo": unit_commit_ppo,
    "unit_worker_idle": unit_worker_idle,
    "unit_config": unit_config,
    "unit_evaluation_defaults": unit_evaluation_defaults,
    "unit_contract_identity": unit_contract_identity,
    "unit_gate_measures_real": unit_gate_measures_real,
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("suite", choices=("unit",))
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--only", default="")
    a = ap.parse_args(argv)
    out = a.out or Path(tempfile.mkdtemp(prefix="m7r_unit_"))
    out.mkdir(parents=True, exist_ok=True)
    results, failed = {}, 0
    for name, fn in CASES.items():
        if a.only and name not in a.only.split(","):
            continue
        t0 = time.perf_counter()
        try:
            detail = fn(out / name)
            results[name] = {"ok": True, "s": round(time.perf_counter() - t0, 2), "detail": detail}
            print(f"PASS {name} ({results[name]['s']} s)")
        except Exception as exc:  # noqa: BLE001 - reported per case
            failed += 1
            results[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()[-3000:]}
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    (out / "m7r_unit_results.json").write_text(json.dumps(results, indent=1, default=str) + "\n", encoding="utf-8")
    print(f"{len(results) - failed}/{len(results)} passed; results {out / 'm7r_unit_results.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
