#!/usr/bin/env python3
"""M7s stage-1 (learned return) offline tests. No game process is launched; nothing under runs/ is written.

    python rl/m7s_tests.py unit [--out DIR] [--only a,b]

Real-data cases read the eight pinned M7q `input_all` traces (recorded raw native replies, read only) and the stage
geometry; every other case is synthetic.
"""
from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
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

import m7n_obs as mn  # noqa: E402
import m7s_analysis as ma  # noqa: E402
import m7s_collect as mc  # noqa: E402
import m7s_goal as mg  # noqa: E402
import m7s_policy as mp  # noqa: E402
import m7s_worker as msw  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
INPUT_ALL = REPO_ROOT / "runs" / "m7q" / "_equiv" / "input_all"


class Failure(AssertionError):
    pass


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise Failure(msg)


# -- helpers ----------------------------------------------------------------------------------------------------------------


def _pinned() -> List[Tuple[str, Dict[str, Any], List[Tuple[int, int, int, int]]]]:
    import m7f_trace as mt

    out = []
    for p in sorted(INPUT_ALL.glob("fx_*.json.gz")):
        tr = mt.read_trace(p)
        acts, _meta = mt.artifact_actions(REPO_ROOT / tr["artifact"])
        out.append((p.name.replace(".json.gz", ""), tr, [(int(a[3]), int(a[0]), int(a[1]), int(a[2])) for a in acts]))
    return out


def _track1_of(b: int, sx: int, sy: int) -> Tuple[int, int]:
    from btt_learning import TRACK1_BUTTON_TABLE, TRACK1_STICK_TABLE

    return [tuple(v) for v in TRACK1_STICK_TABLE].index((sx, sy)), [int(v) for v in TRACK1_BUTTON_TABLE].index(b)


def _native_of(word: Tuple[int, int]) -> Tuple[int, int, int]:
    from btt_learning import TRACK1_BUTTON_TABLE, TRACK1_STICK_TABLE

    sx, sy = TRACK1_STICK_TABLE[word[0]]
    return int(TRACK1_BUTTON_TABLE[word[1]]), int(sx), int(sy)


class _FakeClient:
    def __init__(self, trace: Mapping[str, Any]):
        self.replies = [trace["initial"]] + list(trace["steps"])
        self.t = 0

    def request(self, op: str, **payload: Any) -> Dict[str, Any]:
        if op == "observe":
            return self.replies[0]
        self.t += 1
        return self.replies[self.t]


class _FakeTrack1(gym.Env):
    """Stands for Track1PolicyWrapper and below: each Track 1 word goes out as a `step` request through the episode
    client (so the v3 wrapper's capture sees the recorded reply) and must equal the recorded word."""

    def __init__(self, trace: Mapping[str, Any], words: Sequence[Tuple[int, int]], *, fall_end: bool = False):
        from btt_learning import make_policy_observation_space

        self.trace, self.words, self.fall_end = trace, list(words), fall_end
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
        b, sx, sy = _native_of(w)
        info = {"consumed_tick": t, "native_action": SimpleNamespace(buttons=b, stick_x=sx, stick_y=sy)}
        if last and self.fall_end:
            info["termination_reason"] = "native_failure"
        return np.zeros(15, dtype=np.float32), -0.001, last, False, info


class _TrackerStub:
    def __init__(self, root: Path):
        self.artifact_root = Path(root)
        self.episodes_started = 0
        self.pending: Optional[Dict[str, Any]] = None
        self.done: List[Dict[str, Any]] = []

    def begin(self) -> None:
        self.episodes_started += 1

    def end(self, end_reason: str, digest: str = "d", truncation: Optional[str] = None) -> None:
        eid = f"ep{self.episodes_started:04d}_{len(self.done)}"
        (self.artifact_root / eid).mkdir(parents=True, exist_ok=True)
        self.pending = {"episode_id": eid, "preserved": True, "native_action_digest": digest, "end_reason": end_reason,
                        "truncation_reason": truncation, "artifact_dir": str(self.artifact_root / eid),
                        "startup_mode": "standby_promoted", "steps": 0, "targets_broken": 0}

    def extend_pending_summary(self, build: Callable[[Mapping[str, Any]], Mapping[str, Any]]) -> bool:
        if self.pending is None:
            return False
        self.pending.update(build(dict(self.pending)))
        return True

    def pop(self) -> Optional[Dict[str, Any]]:
        s, self.pending = self.pending, None
        if s is not None:
            self.done.append(s)
        return s


def _real_v3_states(max_traces: int = 8) -> Dict[str, Any]:
    """Real v3 observations built by the unchanged v3 builder from the recorded replies of the pinned traces."""
    import m7f_trace as mt
    import m7g_spatial as ms
    import m7n_entity as ne
    import m7n_status_table as st

    v, pos, ticks, cells = [], [], [], []
    for p in sorted(INPUT_ALL.glob("fx_*.json.gz"))[:max_traces]:
        tr = mt.read_trace(p)
        ini = tr["initial"]
        sp0 = ms.spatial_of(ini, expect_lines=True)
        b = mn.EntityObservationBuilder(sp0.lines or (), st.ActionClassifier(st.load_table(), "mario"))
        for k, r in enumerate([ini] + list(tr["steps"])):
            o, _ = b.build(r["observation"], sp0 if k == 0 else ms.spatial_of(r, expect_lines=False), ne.entity_of(r))
            s = mg.reply_state(r)
            v.append(mn.flatten(o))
            pos.append((s["x"], s["y"]))
            ticks.append(k)
            c = mg.state_cell(s)
            if c is not None and k > 0:
                cells.append(c)
    return {"v3": np.asarray(v, np.float32), "pos": np.asarray(pos, np.float32), "ticks": np.asarray(ticks),
            "cells": sorted(set(cells))}


def init_check_report(seeds: Sequence[int] = (0, 1, 2)) -> Dict[str, Any]:
    """The registered initialisation diagnostics (design section 7) on real v3 observations; per seed."""
    data = _real_v3_states()
    rng = np.random.default_rng(20260928)
    idx = rng.choice(len(data["v3"]), size=min(4000, len(data["v3"])), replace=False)
    per = {}
    for s in seeds:
        pol = mp.init_policy(s)
        per[str(s)] = mp.init_diagnostics(pol, data["v3"][idx], data["pos"][idx], data["ticks"][idx], data["cells"],
                                          pairs=2000, seed=s)
    ratios = [r["goal_state_sensitivity_ratio"] for r in per.values()]
    return {"states_available": int(len(data["v3"])), "states_used": int(len(idx)), "goal_pool": len(data["cells"]),
            "per_seed": per, "sensitivity_in_registered_range": all(r["sensitivity_in_registered_range"] for r in per.values()),
            "ratio_range": [min(ratios), max(ratios)], "registered_range": list(mp.SENSITIVITY_RANGE)}


# -- cases -------------------------------------------------------------------------------------------------------------------


def unit_cell_contract(out: Path) -> Dict[str, Any]:
    """The box, bins and floor lines are exactly those derived from the btt_spatial_v1 stage geometry."""
    import m7n_crossing as mx

    g = mx.geometry()
    xs = [v[0] for v in g.vertices]
    ys = [v[1] for v in g.vertices] + list(g.derived["moving_platform_surface_y_range"])
    check((min(xs), max(xs), min(ys), max(ys)) == mg.BOX, f"box {min(xs), max(xs), min(ys), max(ys)} != {mg.BOX}")
    check(mg.NX == int(np.ceil((mg.BOX[1] - mg.BOX[0]) / mg.CELL)) and mg.NY == int(np.ceil((mg.BOX[3] - mg.BOX[2]) / mg.CELL)),
          "bin counts")
    floors = tuple(sorted(line.index for line in g.lines if line.kind == "floor"))
    check(floors == mg.FLOOR_LINES, f"floor lines {floors}")
    check(mg.cell_of(mg.BOX[0], mg.BOX[2], True, -1) == (0, 0, mg.AIR), "lower-left corner")
    check(mg.cell_of(mg.BOX[1], mg.BOX[3], False, 0) == (mg.NX - 1, mg.NY - 1, 0), "upper-right corner clamps")
    check(mg.cell_of(mg.BOX[1] + 1, 0, True, -1) is None and mg.cell_of(0, mg.BOX[2] - 1, True, -1) is None, "outside")
    check(mg.contact_of(False, 7) == mg.OTHER and mg.contact_of(False, -1) == mg.AIR and mg.contact_of(True, 4) == mg.AIR,
          "contact classes")
    check(mg.GOAL_DIM == 14, "goal dim")
    return {"box": mg.BOX, "bins": [mg.NX, mg.NY], "floor_lines": floors, "geometry_sha256": g.source_sha256[:16]}


def unit_goal_features(out: Path) -> Dict[str, Any]:
    """Scalar and batch features agree; the null goal is zero; every value stays inside the observation box."""
    rng = np.random.default_rng(1)
    n = 500
    goals = np.stack([rng.integers(0, mg.NX, n), rng.integers(0, mg.NY, n),
                      np.array(mg.CONTACT_CLASSES)[rng.integers(0, len(mg.CONTACT_CLASSES), n)]], axis=1)
    xs, ys = rng.uniform(-9000, 9000, n), rng.uniform(-9000, 9000, n)
    bs = rng.integers(1, mg.HORIZON + 1, n)
    batch = mg.goal_features_batch(goals, xs, ys, bs)
    scalar = np.stack([mg.goal_features(tuple(int(v) for v in goals[k]), xs[k], ys[k], bs[k]) for k in range(n)])
    check(np.allclose(batch, scalar, atol=1e-6), "batch vs scalar features")
    check(np.all(np.abs(batch) <= 2.0) and np.all(batch[:, 1:3] >= -1) and np.all(batch[:, 1:3] <= 1), "ranges")
    check(np.allclose(batch[:, 5:13].sum(1), 1.0) and np.all(batch[:, 0] == 1), "one-hot / has-goal")
    check(not mg.goal_features(None, 0, 0, 100).any(), "null goal is zero")
    space = msw.gym.spaces.Box(low=-2.0, high=2.0, shape=(mg.GOAL_DIM,), dtype=np.float32)
    check(all(space.contains(r.astype(np.float32)) for r in batch[:50]), "inside the Box space")
    return {"checked": n}


def unit_reply_cells(out: Path) -> Dict[str, Any]:
    """Cells from raw replies equal cells from the M7r gate-trace rows of the same replies (all eight pinned traces)."""
    import m7q_status_table as st2
    import m7r_analysis as mra
    import m7r_worker as mrw

    if not INPUT_ALL.is_dir():
        return {"skipped": "pinned traces missing"}
    cls = st2.ActionClassifier(st2.load_table(), "mario")
    ticks = cells = 0
    for name, tr, acts in _pinned():
        for (t, b, sx, sy), r in zip(acts, tr["steps"]):
            row = mrw.trace_row(t, SimpleNamespace(buttons=b, stick_x=sx, stick_y=sy), r, cls)
            a = mg.state_cell(mg.reply_state(r))
            bcell = mg.cell_of_trace_row(row, mra.F)
            check(a == bcell, f"{name} tick {t}: {a} vs {bcell}")
            ticks += 1
            cells += a is not None
    return {"ticks": ticks, "with_cell": cells}


def _synthetic_episode(eid: str, cells: Sequence[Optional[mg.Cell]], rng: np.random.Generator) -> mg.EpisodeData:
    T = len(cells)
    return mg.EpisodeData(episode_id=eid, origin="phase_b", obs=rng.normal(size=(T, mp.V3_DIM)).astype(np.float32),
                          pos=rng.uniform(-3000, 3000, size=(T, 2)).astype(np.float32),
                          actions=np.stack([rng.integers(0, 9, T), rng.integers(0, 8, T)], axis=1), cells=list(cells))


def unit_relabel(out: Path) -> Dict[str, Any]:
    """Every relabelled example is (o_t, a_t, g = c_{t+h}, h) with h the first VALID visit after t, b in [h, H - t],
    b = h about half the time, features of g at o_t's position; only the fatal-fall tick is invalid (no 120-tick
    exclusion); and a quota-cut episode supplies pairs whose action and achieved future both lie in its prefix."""
    rng = np.random.default_rng(2)
    eps = []
    for e in range(6):
        T = int(rng.integers(50, 400))
        cells: List[Optional[mg.Cell]] = []
        for k in range(T):
            cells.append(None if rng.random() < 0.2 else (int(rng.integers(0, 6)), int(rng.integers(0, 3)), mg.AIR))
        cells = mg.valid_cells(cells, fell=(e % 2 == 0))
        eps.append(_synthetic_episode(f"e{e}", cells, rng))
    ex = mg.sample_examples(eps, 4000, np.random.default_rng(3))
    by_id = {e.episode_id: e for e in eps}
    exact = 0
    for k in range(len(ex["t"])):
        e = by_id[str(ex["episode"][k])]
        t, h, b = int(ex["t"][k]), int(ex["h"][k]), int(ex["b"][k])
        g = tuple(int(v) for v in ex["cell"][k])
        check(t + h <= len(e.cells), f"example {k}: outside the recorded ticks")
        check(e.cells[t + h - 1] == g, f"example {k}: c_(t+h) != g")
        check(all(e.cells[j - 1] != g for j in range(t + 1, t + h)), f"example {k}: h is not the first visit")
        check(h <= b <= mg.HORIZON - t, f"example {k}: b {b} outside [{h}, {mg.HORIZON - t}]")
        exact += b == h
        check(np.array_equal(ex["obs"][k], e.obs[t]) and ex["stick"][k] == e.actions[t, 0]
              and ex["button"][k] == e.actions[t, 1], f"example {k}: o_t / a_t")
        check(np.allclose(ex["goal"][k], mg.goal_features(g, e.pos[t, 0], e.pos[t, 1], b), atol=1e-6), f"example {k}: features")
    share = exact / len(ex["t"])
    check(0.44 < share < 0.56, f"b = h share {share}")
    # validity: a fall episode loses exactly its last (fatal-fall) tick; nothing else changes
    raw = [(1, 1, mg.AIR)] * 300
    fell, kept = mg.valid_cells(raw, fell=True), mg.valid_cells(raw, fell=False)
    check(fell[-1] is None and all(c is not None for c in fell[:-1]) and kept == raw, "validity = only the fatal-fall tick")
    # quota-cut prefix: an episode cut at tick 120 of a longer trajectory supplies pairs inside ticks 1..120 only
    full = [(int(k // 10) % 7, 2, mg.AIR) for k in range(400)]
    cut = _synthetic_episode("cut", full[:120], rng)
    exc = mg.sample_examples([cut], 3000, np.random.default_rng(5))
    check(int((exc["t"] + exc["h"]).max()) <= 120 and int(exc["t"].max()) < 120, "quota-cut pairs outside the prefix")
    beyond = {full[k] for k in range(120, 400)} - set(full[:120])
    check(not ({tuple(int(v) for v in c) for c in exc["cell"]} & beyond), "a cell reached only after the cut was used")
    # uniform over distinct future cells: two cells, one visited 1 tick, one 99 ticks -> about 1/2 each
    cells2 = [(0, 0, mg.AIR)] + [(1, 0, mg.AIR)] * 99
    e2 = _synthetic_episode("u", cells2, rng)
    ex2 = mg.sample_examples([e2], 3000, np.random.default_rng(4))
    at0 = ex2["t"] == 0
    frac = float(np.mean(ex2["cell"][at0][:, 0] == 0)) if at0.any() else 0.5
    check(np.sum(at0) < 200 or 0.3 < frac < 0.7, f"distinct-cell uniformity at t = 0: {frac}")
    return {"examples": int(len(ex["t"])), "b_equals_h_share": round(share, 3),
            "quota_cut_max_t_plus_h": int((exc["t"] + exc["h"]).max())}


def _phase_a(n: int = 20, seed: int = 0) -> List[mg.PhaseAEpisode]:
    rng = np.random.default_rng(seed)
    eps = []
    for e in range(n):
        first = {}
        for c in range(40):                       # common cells
            if rng.random() < 0.8:
                first[f"{c},1,-1"] = int(rng.integers(1, 3600))
        for c in range(40):                       # rarer cells
            if rng.random() < 0.08 + 0.2 * (c % 3 == 0):
                first[f"{c},20,-1"] = int(rng.integers(1, 3600))
        eps.append(mg.PhaseAEpisode(episode_id=f"a{e:02d}", artifact_dir=f"x/a{e:02d}", native_action_digest=f"d{e}",
                                    first_reach=first, end_reason="horizon"))
    return eps


def unit_goal_set_provenance(out: Path) -> Dict[str, Any]:
    """E comes only from the seed's own phase-A episodes, by rarity band and sha256 order; tampering is detected."""
    pa = _phase_a()
    gs = mg.freeze_goal_set(7, pa)
    check(mg.freeze_goal_set(7, pa)["digest"] == gs["digest"], "deterministic")
    counts = mg.archive_counts(pa)
    check(all(1 <= counts[g["cell"]] <= 2 for g in gs["rare"]) and all(3 <= counts[g["cell"]] <= 9 for g in gs["mid"]),
          "rarity bands")
    rare_all = [k for k, n in counts.items() if 1 <= n <= 2]
    want = sorted(rare_all, key=lambda k: hashlib.sha256(f"m7s1|E|7|{k}".encode()).hexdigest())[:mg.E_RARE]
    check([g["cell"] for g in gs["rare"]] == want, "sha256 order, no position preference")
    check(mg.check_provenance(gs, pa) == [], "clean provenance")
    bad = json.loads(json.dumps(gs))
    bad["rare"][0]["witnesses"].append({"episode_id": "foreign", "artifact_dir": None, "native_action_digest": None,
                                        "first_reach_tick": 1})
    check(mg.check_provenance(bad, pa), "foreign witness detected")
    bad2 = json.loads(json.dumps(gs))
    bad2["archive"][gs["rare"][0]["cell"]] = 5
    check(mg.check_provenance(bad2, pa), "archive tampering detected")
    pa_bad = _phase_a()
    pa_bad[3].started_at_tick0 = False
    try:
        mg.freeze_goal_set(7, pa_bad)
        check(False, "a non-tick-0 episode was accepted")
    except mg.GoalContractError:
        pass
    try:
        mg.freeze_goal_set(7, pa[:19])
        check(False, "19 phase-A episodes accepted")
    except mg.GoalContractError:
        pass
    rev = mg.freeze_goal_set(7, sorted(pa, key=lambda e: e.episode_id, reverse=True))
    check([g["cell"] for g in rev["rare"]] == [g["cell"] for g in gs["rare"]], "independent of episode order")
    return {"rare": len(gs["rare"]), "mid": len(gs["mid"]), "candidates": gs["candidates"]}


def unit_schedule_plan(out: Path) -> Dict[str, Any]:
    """One schedule per seed, identical on every call (R and U), drawing from E about half the time and otherwise only
    from the phase-A archive; the plan has every E goal exactly twice, entry e on worker e mod 5, fixed seeds."""
    gs = mg.freeze_goal_set(3, _phase_a())
    s1, s2 = mg.make_schedule(3, gs), mg.make_schedule(3, gs)
    check(s1["digest"] == s2["digest"] and s1["entries"] == s2["entries"], "schedule deterministic")
    e_keys = {g["cell"] for g in gs["rare"] + gs["mid"]}
    draws = [c for row in s1["entries"].values() for c in row]
    check(all(c in gs["archive"] for c in draws), "only archive cells")
    e_share = sum(c in e_keys for c in draws) / len(draws)
    # half of the draws come from E; the archive half lands on E with E's share of the (1 + n)^(-1/2) weights
    w = {k: (1.0 + n) ** -0.5 for k, n in gs["archive"].items()}
    expected = mg.E_SHARE + (1 - mg.E_SHARE) * sum(w[k] for k in e_keys) / sum(w.values())
    check(abs(e_share - expected) < 0.02, f"E share {e_share:.3f} vs expected {expected:.3f}")
    check(mg.make_schedule(4, gs)["digest"] != s1["digest"], "seed dependent")
    plan = mg.make_eval_plan(3, gs)
    check(len(plan) == 30 and plan == mg.make_eval_plan(3, gs), "plan size / determinism")
    from collections import Counter

    cnt = Counter(p["cell"] for p in plan)
    check(set(cnt.values()) == {2} and set(cnt) == e_keys, "each E goal twice")
    check(all(p["rank"] == p["entry"] % 5 for p in plan) and len({p["sampling_seed"] for p in plan}) == 30, "ranks / seeds")
    rows = mg.schedule_for_rank(s1, 2)
    check(len(rows) == mg.SCHEDULE_EPISODES and all(len(r) == mg.SCHEDULE_GOALS for r in rows.values()), "rank rows")
    return {"e_share": round(e_share, 3), "draws": len(draws)}


class _ReplyEnv(gym.Env):
    """A bare native-level stand-in: scripted replies; stores the actions it receives; can end in a fall."""

    def __init__(self, positions: Sequence[Tuple[float, float]], *, fall_at: Optional[int] = None,
                 horizon: Optional[int] = None):
        self.positions = list(positions)
        self.fall_at, self.horizon = fall_at, horizon
        self.observation_space = gym.spaces.Box(-1, 1, (1,), np.float32)
        self.action_space = gym.spaces.MultiDiscrete([9, 8])
        self.last_reply: Optional[Dict[str, Any]] = None
        self.received: List[Any] = []
        self.k = 0

    def _reply(self, k: int) -> Dict[str, Any]:
        x, y = self.positions[min(k, len(self.positions) - 1)]
        return {"op": "step" if k else "observe", "observation": {"btt_active": 1, "fighter_valid": 1, "position_x": x,
                                                                  "position_y": y, "ground_air_state": 1},
                "spatial": {"fighter": {"floor_line_id": -1}}}

    def reset(self, *, seed=None, options=None):
        self.k = 0
        self.received = []
        self.last_reply = self._reply(0)
        return np.zeros(1, np.float32), {}

    def step(self, action):
        self.received.append(np.array(action).tolist())
        self.k += 1
        self.last_reply = self._reply(self.k)
        term = self.fall_at is not None and self.k == self.fall_at
        trunc = self.horizon is not None and self.k >= self.horizon and not term
        info: Dict[str, Any] = {"termination_reason": "native_failure"} if term else {}
        return np.zeros(1, np.float32), 0.0, term, trunc, info


def _probe_on(env: "_ReplyEnv", goal: Optional[mg.Cell], *, end_on_success: bool) -> msw.GoalProbeWrapper:
    p = msw.GoalProbeWrapper(env, base=env)
    p.reply_source = lambda: env.last_reply
    p.reset()
    p.command(goal)
    p.end_on_success = end_on_success
    return p


def unit_probe(out: Path) -> Dict[str, Any]:
    """First valid reach: an evaluation episode ends ON the reach tick (goal_reached), also on the native horizon tick;
    a reach on the fatal-fall tick or on a native-clear tick is not a return; collection does not end at a reach; the
    tick quota ends collection exactly; actions pass through unchanged."""
    goal = mg.cell_of(150.0, 150.0, True, -1)
    far, near = (-3000.0, -3000.0), (150.0, 150.0)
    # reach at tick 5 ends the evaluation episode at tick 5
    env = _ReplyEnv([far] * 5 + [near] * 3 + [far] * 400, horizon=3600)
    p = _probe_on(env, goal, end_on_success=True)
    acts, k = [], 0
    while True:
        a = [k % 9, (k * 3) % 8]
        acts.append(a)
        _o, _r, term, trunc, info = p.step(np.array(a))
        k += 1
        if term or trunc:
            break
    check(k == 5 and p.reach_tick == 5 and trunc and not term and info["truncation_reason"] == mg.END_GOAL
          and p.last["reached"] and p.last["ended_by"] == mg.END_GOAL, f"reach end at {k}: {p.last}")
    check(env.received == acts, "actions unchanged")
    # a reach followed by a fall 60 ticks later still counts (no survival requirement) in collection
    env2 = _ReplyEnv([far] * 5 + [near] * 3 + [far] * 400, fall_at=65)
    p2 = _probe_on(env2, goal, end_on_success=False)
    for _ in range(65):
        _o, _r, term, trunc, info = p2.step(np.array([0, 0]))
        if term or trunc:
            break
    check(p2.reach_tick == 5 and term and info.get("termination_reason") == "native_failure", "a later fall does not void")
    # reached only on the fatal-fall tick: not a reach
    env3 = _ReplyEnv([far] * 10 + [near], fall_at=10)
    p3 = _probe_on(env3, goal, end_on_success=True)
    for _ in range(10):
        _o, _r, term, trunc, info = p3.step(np.array([0, 0]))
    check(p3.reach_tick is None and term and "truncation_reason" not in info and not p3.last["valid"],
          "a reach on the fatal-fall tick does not count")
    # reach on the native horizon tick: success, truncation_reason overridden to goal_reached
    env4 = _ReplyEnv([far] * 30 + [near], horizon=30)
    env4_trunc_reason = "max_episode_steps"
    orig_step = env4.step

    def horizon_step(action, _orig=orig_step):
        o, r, term, trunc, info = _orig(action)
        if trunc:
            info["truncation_reason"] = env4_trunc_reason
        return o, r, term, trunc, info

    env4.step = horizon_step
    p4 = _probe_on(env4, goal, end_on_success=True)
    for _ in range(30):
        _o, _r, term, trunc, info = p4.step(np.array([0, 0]))
    check(p4.reach_tick == 30 and trunc and info["truncation_reason"] == mg.END_GOAL, "reach on the horizon tick")
    env4b = _ReplyEnv([far] * 40, horizon=30)
    env4b.step = (lambda a, _o=env4b.step: (lambda r: (r[0], r[1], r[2], r[3], dict(r[4], truncation_reason="max_episode_steps") if r[3] else r[4]))(_o(a)))
    p4b = _probe_on(env4b, goal, end_on_success=True)
    for _ in range(30):
        _o, _r, term, trunc, info = p4b.step(np.array([0, 0]))
    check(trunc and info["truncation_reason"] == "max_episode_steps" and p4b.reach_tick is None, "no reach: native horizon kept")
    # native clear on the reach tick: a clear, not a return
    env5 = _ReplyEnv([far] * 12 + [near])
    orig5 = env5.step
    env5.step = lambda a, _o=orig5: (lambda r: (r[0], r[1], env5.k == 12, False,
                                                dict(r[4], termination_reason="native_clear") if env5.k == 12 else r[4]))(_o(a))
    p5 = _probe_on(env5, goal, end_on_success=True)
    for _ in range(12):
        _o, _r, term, trunc, info = p5.step(np.array([0, 0]))
    check(term and p5.reach_tick is None and "truncation_reason" not in info, "a clear tick is not a return")
    # tick quota (collection)
    env6 = _ReplyEnv([far] * 100)
    p6 = _probe_on(env6, None, end_on_success=False)
    p6.tick_quota = 17
    n = 0
    while True:
        _o, _r, term, trunc, info = p6.step(np.array([0, 0]))
        n += 1
        if trunc:
            break
    check(n == 17 and info["truncation_reason"] == mg.END_QUOTA, "tick quota end")
    return {"cases": 7}


def unit_real_stack(out: Path) -> Dict[str, Any]:
    """The real v3 wrapper and the goal wrappers on recorded replies. Collection: every recorded word goes out unchanged,
    the v3 part of the observation is bit-identical to the plain v3 stack at every tick, the goal vector equals
    goal_features(commanded goal, position, H - t), probe cells equal reply cells, a goal taken from the trace is
    reached at its first valid occurrence and the next goal is commanded on that tick. Evaluation: the same goal ends
    the episode on that tick as goal_reached, after exactly the recorded prefix of words."""
    if not INPUT_ALL.is_dir():
        return {"skipped": "pinned traces missing"}
    rep = {}
    for name, tr, acts in _pinned()[:4]:
        words = [_track1_of(b, sx, sy) for _t, b, sx, sy in acts]
        ref_inner = _FakeTrack1(tr, words)
        ref = mn.EntityObsV3Wrapper(ref_inner, base=ref_inner.base, character="mario")
        ref_obs = [ref.reset()[0]]
        for w in words:
            ref_obs.append(ref.step(np.array(w))[0])
        cells = [mg.state_cell(mg.reply_state(r)) for r in tr["steps"]]
        goal_k = next((k for k in range(len(cells) // 3, len(cells)) if cells[k] is not None
                       and cells[k] not in cells[:k]), None)
        goal = cells[goal_k] if goal_k is not None else None
        second = next((c for c in cells[goal_k + 1:] if c is not None and c != goal), None) if goal_k is not None else None
        # collection
        inner = _FakeTrack1(tr, words)
        probe = msw.GoalProbeWrapper(inner, base=inner.base)
        v3 = mn.EntityObsV3Wrapper(probe, base=inner.base, character="mario")
        probe.reply_source = lambda v3=v3: v3._last_reply
        tracker = _TrackerStub(out / name)
        gw = msw.GoalObsWrapper(v3, probe=probe, v3=v3, tracker=tracker, rank=0)
        gw.m7s_configure({"mode": "schedule", "phase": "test", "tick_quota": 10 ** 6, "end_on_success": False,
                          "schedule": {1: [c for c in (goal, second) if c is not None]}})
        tracker.begin()
        obs, info = gw.reset()
        check(all(np.array_equal(obs[k], ref_obs[0][k]) for k in ref_obs[0]), f"{name}: reset v3 observation")
        s0 = mg.reply_state(tr["initial"])
        check(np.allclose(obs[msw.GOAL_KEY], mg.goal_features(goal, s0["x"], s0["y"], mg.HORIZON)), f"{name}: reset goal")
        reached_at = None
        for t, w in enumerate(words, start=1):
            if t == len(words):
                tracker.end("horizon")
            obs, _r, term, trunc, info = gw.step(np.array(w))
            check(all(np.array_equal(obs[k], ref_obs[t][k]) for k in ref_obs[t]), f"{name}: tick {t} v3 observation")
            rec = info["m7s"]
            want = mg.cell_key(cells[t - 1]) if cells[t - 1] is not None else None
            check(rec["cell"] == want, f"{name}: tick {t} probe cell {rec['cell']} vs {want}")
            s = mg.reply_state(tr["steps"][t - 1])
            check(np.allclose(obs[msw.GOAL_KEY], mg.goal_features(probe.commanded, s["x"], s["y"], mg.HORIZON - t)),
                  f"{name}: goal t {t}")
            if "reached" in rec["events"] and reached_at is None:
                reached_at = t
                check(probe.commanded == second, f"{name}: the next goal is commanded on the reach tick")
            if term or trunc:
                break
        check(inner.submitted == words, f"{name}: submitted words differ")
        if goal is not None:
            check(reached_at == goal_k + 1, f"{name}: reached at {reached_at}, first valid occurrence {goal_k + 1}")
        side = json.load(gzip.open(Path(tracker.pending["artifact_dir"]) / mg.SIDECAR_FILE, "rt"))
        check(side["cells"] == [mg.cell_key(c) if c else None for c in cells[:len(side['cells'])]], f"{name}: sidecar cells")
        check(side["commanded"][0]["reach_tick"] == reached_at, f"{name}: sidecar reach tick")
        # evaluation: the episode ends on the reach tick as goal_reached
        inner_e = _FakeTrack1(tr, words)
        probe_e = msw.GoalProbeWrapper(inner_e, base=inner_e.base)
        v3e = mn.EntityObsV3Wrapper(probe_e, base=inner_e.base, character="mario")
        probe_e.reply_source = lambda v3e=v3e: v3e._last_reply
        tracker_e = _TrackerStub(out / (name + "_eval"))
        ge = msw.GoalObsWrapper(v3e, probe=probe_e, v3=v3e, tracker=tracker_e, rank=0)
        ge.m7s_configure({"mode": "plan", "phase": "test", "episode_quota": 1, "end_on_success": True,
                          "plan": [{"entry": 0, "goal": goal}]})
        tracker_e.begin()
        ge.reset()
        ended = None
        for t, w in enumerate(words, start=1):
            if goal is not None and t == goal_k + 1:
                tracker_e.end("horizon", truncation="goal_reached")
            obs, _r, term, trunc, info = ge.step(np.array(w))
            if term or trunc:
                ended = (t, info.get("truncation_reason"))
                break
        if goal is not None:
            check(ended == (goal_k + 1, mg.END_GOAL), f"{name}: evaluation ended {ended}")
            check(inner_e.submitted == words[:goal_k + 1], f"{name}: evaluation words = the recorded prefix")
        rep[name] = {"ticks": len(words), "goal": mg.cell_key(goal) if goal else None, "reached_at": reached_at,
                     "evaluation_end": ended}
    return rep


class _InprocWorker:
    """One in-process worker: a synthetic native stand-in under the REAL GoalProbeWrapper and GoalObsWrapper, with the
    tracker / recorder roles and the SubprocVecEnv auto-reset emulated."""

    def __init__(self, rank: int, root: Path, lengths: Callable[[int], int], falls: Callable[[int], bool],
                 path: Callable[[int, int], Tuple[float, float]]):
        self.rank = rank
        self.tracker = _TrackerStub(root / f"w{rank}")
        self.lengths, self.falls, self.path = lengths, falls, path
        worker = self

        class Native(gym.Env):
            observation_space = gym.spaces.Box(-1, 1, (1,), np.float32)
            action_space = gym.spaces.MultiDiscrete([9, 8])

            def reset(self, *, seed=None, options=None):
                worker.tracker.begin()
                self.k, self.ep = 0, worker.tracker.episodes_started
                self.received = []
                worker.v3._last_reply = worker.reply(self.ep, 0, "observe")
                return np.zeros(1, np.float32), {}

            def step(self, action):
                self.k += 1
                self.received.append(tuple(int(v) for v in action))
                worker.v3._last_reply = worker.reply(self.ep, self.k, "step")
                end = self.k >= worker.lengths(self.ep)
                fell = end and worker.falls(self.ep)
                # as the real environment: a fall is a native_failure termination, the length a max_episode_steps truncation
                info = ({"termination_reason": "native_failure"} if fell
                        else {"truncation_reason": "max_episode_steps"} if end else {})
                return np.zeros(1, np.float32), 0.0, fell, end and not fell, info

        class Recorder(gym.Wrapper):
            def step(self, action):
                o, r, term, trunc, info = self.env.step(action)
                if term or trunc:
                    worker.tracker.end("fall" if term else "horizon", digest=f"d{worker.tracker.episodes_started}",
                                       truncation=info.get("truncation_reason"))
                return o, r, term, trunc, info

        class V3(gym.Wrapper):
            def __init__(self, env):
                super().__init__(env)
                self.observation_space = mn.make_observation_space()
                self._last_reply = None

            def _obs(self):
                d = {k: np.zeros(s, np.float32) for k, s in mn.SHAPES.items()}
                d[mn.AGENT_KEY][0] = float(self._last_reply["observation"]["position_x"]) / 2000.0
                return d

            def reset(self, **kw):
                self.env.reset(**kw)
                return self._obs(), {}

            def step(self, action):
                _o, r, term, trunc, info = self.env.step(action)
                return self._obs(), r, term, trunc, info

        self.native = Native()
        self.probe = msw.GoalProbeWrapper(self.native, base=self.native)
        self.v3 = V3(Recorder(self.probe))
        self.probe.reply_source = lambda: self.v3._last_reply
        self.goal = msw.GoalObsWrapper(self.v3, probe=self.probe, v3=self.v3, tracker=self.tracker, rank=rank)

    def reply(self, ep: int, k: int, op: str) -> Dict[str, Any]:
        x, y = self.path(ep, k)
        return {"op": op, "observation": {"btt_active": 1, "fighter_valid": 1, "position_x": x, "position_y": y,
                                          "ground_air_state": 1}, "spatial": {"fighter": {"floor_line_id": -1}}}


class _InprocVec:
    """A synchronous stand-in for M7SubprocVecEnv with the m7_worker protocol (auto-reset, reset_infos)."""

    def __init__(self, workers: Sequence[_InprocWorker]):
        self.workers = list(workers)
        self.num_envs = len(self.workers)
        self.ranks = [w.rank for w in self.workers]
        self.reset_infos: List[Dict[str, Any]] = [{} for _ in self.workers]
        self.sent: List[List[Tuple[int, int]]] = [[] for _ in self.workers]

    def env_method_each(self, name: str, calls: Mapping[int, Tuple[Sequence[Any], Mapping[str, Any]]]) -> Dict[int, Any]:
        return {i: getattr(self.workers[i].goal, name)(*a, **k) for i, (a, k) in calls.items()}

    def _stack(self, obs: Sequence[Mapping[str, np.ndarray]]) -> Dict[str, np.ndarray]:
        return {k: np.stack([o[k] for o in obs]) for k in obs[0]}

    def reset(self) -> Dict[str, np.ndarray]:
        out = []
        for i, w in enumerate(self.workers):
            o, info = w.goal.reset()
            self.reset_infos[i] = {"m7s": w.goal.last_reset_record}
            out.append(o)
        return self._stack(out)

    def step(self, actions: np.ndarray):
        obs, dones, infos = [], [], []
        for i, w in enumerate(self.workers):
            self.reset_infos[i] = {}
            o, _r, term, trunc, info = w.goal.step(actions[i])
            slim = {"m7s": w.goal.last_step_record}
            if not w.goal.last_step_record.get("idle"):
                self.sent[i].append((int(actions[i][0]), int(actions[i][1])))
            if term or trunc:
                slim["m7_episode"] = w.tracker.pop()
                o, rinfo = w.goal.reset()
                self.reset_infos[i] = {"m7s": w.goal.last_reset_record}
            obs.append(o)
            dones.append(term or trunc)
            infos.append(slim)
        return self._stack(obs), np.zeros(len(obs)), np.array(dones), infos


def _world(seed: int, root: Path) -> _InprocVec:
    def path(ep: int, k: int) -> Tuple[float, float]:
        return (-3750.0 + 300.0 * (((k // 7) + ep) % 12), -3900.0 + 300.0 * (ep % 3))

    return _InprocVec([_InprocWorker(r, root, lengths=lambda ep, r=r: 40 + 9 * ((ep + r) % 4),
                                     falls=lambda ep, r=r: (ep + r) % 5 == 0, path=path) for r in range(5)])


class _SmallTrainer:
    def __init__(self, policy: mp.GoalPolicy, seed: int):
        self.t = mp.GCSLTrainer(policy, seed)

    def train_chunk(self, episodes):
        return self.t.train_chunk(episodes, steps=4, batch=64)


def unit_collector(out: Path) -> Dict[str, Any]:
    """run_phase over five in-process workers built from the real goal wrappers: exact episode / tick quotas, idle
    workers step nothing, chunked training, the dataset holds only the run's own episodes, U never changes, and the
    same parameters + schedule + seeds reproduce the same actions (common random numbers); plan mode runs each entry
    once with its registered sampling seed."""
    seed = 5
    init = mp.init_policy(seed)
    init_digest = mp.parameter_digest(init)
    # phase A: 4 null episodes per worker
    va = _world(seed, out / "A")
    data: List[mg.EpisodeData] = []
    ra = mc.run_phase(venv=va, configs=mc.phase_configs("null", phase="A"), policy=init, seed=seed, phase="A",
                      tick_cap=20 * 3600, store=True, dataset=data)
    check(len(ra.episodes) == 20 and len(data) == 20 and ra.ticks == sum(len(d.cells) for d in data), "phase A episodes")
    check(all(len(w.native.received) >= 0 for w in va.workers) and ra.idle_steps >= 0, "phase A ran")
    check(all(len(v) == ra.ticks_per_rank[i] for i, v in enumerate(va.sent)), "idle workers sent nothing")
    # a schedule from these episodes' own cells
    pa = [mg.PhaseAEpisode(episode_id=str(e["episode_id"]), artifact_dir=e["artifact_dir"],
                           native_action_digest=e["native_action_digest"], first_reach=dict(e["first_reach"]),
                           end_reason=str(e["end_reason"])) for e in ra.episodes]
    counts = mg.archive_counts(pa)
    e_keys = sorted(counts)[:15]
    gs = {"digest": "t", "archive": counts, "rare": [{"cell": k} for k in e_keys[:10]], "mid": [{"cell": k} for k in e_keys[10:]]}
    sched = mg.make_schedule(seed, gs, episodes=60)
    quota = 150
    cfg = {r: {"mode": "schedule", "phase": "B", "tick_quota": quota, "end_on_success": False,
               "schedule": mg.schedule_for_rank(sched, r)} for r in range(5)}
    # R: chunked training on phase A + own phase-B episodes
    r_pol, _ = mp.GoalPolicy(), None
    r_pol.load_state_dict(init.state_dict())
    trainer = _SmallTrainer(r_pol, seed)
    rr = mc.run_phase(venv=_world(seed, out / "RB"), configs=cfg, policy=r_pol, seed=seed, phase="B_R",
                      tick_cap=5 * quota, store=True, trainer=trainer, dataset=data, chunk_ticks=50)
    check(rr.ticks == 5 * quota and all(v == quota for v in rr.ticks_per_rank.values()), f"R quota {rr.ticks_per_rank}")
    check(len(rr.train_chunks) == 5 * quota // 50 and trainer.t.gradient_steps == 4 * len(rr.train_chunks), "chunks")
    check(mp.parameter_digest(r_pol) != init_digest, "R changed")
    check({d.origin for d in data} == {"phase_a", "phase_b"} and len(data) == 20 + len(rr.episodes), "dataset = own episodes")
    import m7s_gate as gate

    classes = [gate.end_class(e) for e in rr.episodes]
    check(set(classes) <= {"fall", "native_horizon", "tick_quota"}, f"collection end classes {set(classes)}")
    last = {r: max((e for e in rr.episodes if e["rank"] == r), key=lambda e: e["worker_episode"]) for r in range(5)}
    check(all(gate.end_class(e) == "tick_quota" for e in last.values()), "each worker's last episode is the quota cut")
    check(sum(c == "tick_quota" for c in classes) == 5, "exactly one quota cut per worker")
    # U: same schedule, same ticks, no updates; twice -> identical actions (determinism, common random numbers)
    u_pol = mp.GoalPolicy()
    u_pol.load_state_dict(init.state_dict())
    vu1, vu2 = _world(seed, out / "U1"), _world(seed, out / "U2")
    ru1 = mc.run_phase(venv=vu1, configs=cfg, policy=u_pol, seed=seed, phase="B_U", tick_cap=5 * quota, store=False)
    ru2 = mc.run_phase(venv=vu2, configs=cfg, policy=u_pol, seed=seed, phase="B_U", tick_cap=5 * quota, store=False)
    check(mp.parameter_digest(u_pol) == init_digest, "U unchanged")
    check(vu1.sent == vu2.sent and ru1.ticks == 5 * quota, "U reproducible")
    # the untrained R (same parameters as U) would have sent exactly U's actions: phase tag B is shared
    r0 = mp.GoalPolicy()
    r0.load_state_dict(init.state_dict())
    vr0 = _world(seed, out / "R0")
    mc.run_phase(venv=vr0, configs=cfg, policy=r0, seed=seed, phase="B_R", tick_cap=5 * quota, store=False)
    check(vr0.sent == vu1.sent, "common random numbers across arms")
    # plan mode
    plan = [{"entry": e, "stratum": "rare" if e < 20 else "mid", "cell": e_keys[e % 15], "repeat": 0, "rank": e % 5,
             "sampling_seed": mg.evaluation_seed(seed, e)} for e in range(30)]
    ve = _world(seed, out / "E")
    re_ = mc.run_phase(venv=ve, configs=mc.phase_configs("plan", phase="E", plan=plan), policy=r_pol, seed=seed,
                       phase="E_R", tick_cap=30 * 3600, store=False, plan=plan)
    entries = sorted(int(e["plan_entry"]) for e in re_.episodes)
    check(entries == list(range(30)), f"plan entries {entries}")
    cmd = {int(e["plan_entry"]): e["m7s"]["commanded"][0]["cell"] for e in re_.episodes}
    check(all(cmd[p["entry"]] == p["cell"] for p in plan), "commanded = plan cell")
    import m7s_gate as gate

    rows, probs = gate._eval_rows(re_, plan)
    check(not probs, f"evaluation rows: {probs}")
    succ = sum(r["success"] for r in rows)
    for r, e in zip(rows, sorted(re_.episodes, key=lambda x: int(x["plan_entry"]))):
        reach = e["m7s"]["commanded"][0]["reach_tick"]
        check(r["success"] == (e["truncation_reason"] == mg.END_GOAL), "success is the goal_reached truncation")
        check((reach is not None) == r["success"] and (not r["success"] or reach == e["ticks"]), "reach = last tick")
    check(all(e["end_reason"] == "horizon" for e in re_.episodes if e["truncation_reason"] == mg.END_GOAL), "label")
    return {"phase_a_ticks": ra.ticks, "R_chunks": len(rr.train_chunks), "U_ticks": ru1.ticks, "eval_successes": succ}


def unit_gcsl_synthetic(out: Path) -> Dict[str, Any]:
    """A deterministic chain world from a fixed start: GCSL on random own episodes learns to reach far cells that the
    identical untrained policy rarely reaches (the learner, relabelling, goal branch and features work end to end)."""
    N, T = 14, 40
    rng = np.random.default_rng(11)

    def cell(p: int) -> mg.Cell:
        return (p, 0, mg.AIR)

    def x_of(p: int) -> float:
        return mg.BOX[0] + (p + 0.5) * mg.CELL

    def obs_of(p: int, t: int) -> np.ndarray:
        o = np.zeros(mp.V3_DIM, np.float32)
        o[p] = 1.0
        o[100] = t / mg.HORIZON
        return o

    def move(p: int, stick: int) -> int:
        return min(N - 1, p + 1) if stick == 5 else max(0, p - 1) if stick == 3 else p

    def rollout(pol: Optional[mp.GoalPolicy], goal: Optional[mg.Cell], g: np.random.Generator):
        p, O, P, A, C = 0, [], [], [], []
        for t in range(T):
            if pol is None:
                a = (int(g.integers(9)), int(g.integers(8)))
            else:
                f = mg.goal_features(goal, x_of(p), mg.BOX[2] + 150, mg.HORIZON - t)[None]
                ps, pb = mp.action_probs(pol, obs_of(p, t)[None], f)
                a = tuple(mp.sample_actions(ps, pb, [g])[0])
            O.append(obs_of(p, t))
            P.append((x_of(p), mg.BOX[2] + 150))
            A.append(a)
            p = move(p, a[0])
            C.append(cell(p))
        return O, P, A, C

    eps = []
    for e in range(150):
        O, P, A, C = rollout(None, None, rng)
        eps.append(mg.EpisodeData(episode_id=f"s{e}", origin="phase_b", obs=np.asarray(O), pos=np.asarray(P, np.float32),
                                  actions=np.asarray(A), cells=C))
    reach = lambda C, g: g in C
    init = mp.init_policy(0)
    trained = mp.GoalPolicy()
    trained.load_state_dict(init.state_dict())
    tr = mp.GCSLTrainer(trained, 0)
    for _ in range(6):
        rec = tr.train_chunk(eps, steps=100, batch=256)
    res = {}
    for goal_p in (4, 6):
        goal = cell(goal_p)
        g1, g2 = np.random.default_rng(100 + goal_p), np.random.default_rng(100 + goal_p)
        su = sum(reach(rollout(init, goal, g1)[3], goal) for _ in range(40))
        st = sum(reach(rollout(trained, goal, g2)[3], goal) for _ in range(40))
        res[goal_p] = {"untrained": su, "trained": st}
        check(st >= su + 15 and st >= 25, f"goal {goal_p}: trained {st} / 40 vs untrained {su} / 40")
    check(rec["action_tv_goal_shuffle"] > 0.01, f"goal sensitivity after training {rec['action_tv_goal_shuffle']}")
    import m7s_gate as gate

    sens = gate.post_training_sensitivity(eps, trained, init, [cell(q) for q in range(N)], seed=0, n=1500)
    check(not sens["goal_blind_flag"] and sens["R_final"]["action_tv_goal_swap"] > 10 * sens["U_initial"]["action_tv_goal_swap"],
          f"post-training sensitivity {sens['R_final']['action_tv_goal_swap']} vs {sens['U_initial']['action_tv_goal_swap']}")
    blind = gate.post_training_sensitivity(eps, init, init, [cell(q) for q in range(N)], seed=0, n=1500)
    check(blind["goal_blind_flag"], "an untrained (goal-blind) policy is flagged")
    return {"reach_of_40": res, "last_chunk": rec,
            "post_training_action_tv": {"R": sens["R_final"]["action_tv_goal_swap"], "U": sens["U_initial"]["action_tv_goal_swap"]}}


def unit_policy_matched(out: Path) -> Dict[str, Any]:
    """One initial parameter set per seed: identical for R and U, reproducible, saved and reloaded bit-exactly; heads
    near uniform; sampling uses the same two uniforms per tick whatever the probabilities (common random numbers)."""
    a, b, c = mp.init_policy(1), mp.init_policy(1), mp.init_policy(2)
    check(mp.parameter_digest(a) == mp.parameter_digest(b) != mp.parameter_digest(c), "init reproducibility")
    path = out / "init.pt"
    d = mp.save_policy(path, a, {"seed": 1})
    u, meta = mp.load_policy(path)
    check(meta["digest"] == d == mp.parameter_digest(u), "save / load")
    v = np.random.default_rng(0).normal(size=(64, mp.V3_DIM)).astype(np.float32)
    g = np.stack([mg.goal_features((3, 4, mg.AIR), 0, 0, 100)] * 64)
    ps, pb = mp.action_probs(a, v, g)
    check(ps.shape == (64, 9) and pb.shape == (64, 8) and ps.max() < 0.2 and pb.max() < 0.2, "near-uniform heads")
    g1, g2 = np.random.default_rng(9), np.random.default_rng(9)
    x = mp.sample_actions(ps, pb, [g1] * 1)
    y = mp.sample_actions(ps, pb, [g2] * 1)
    check(np.array_equal(x, y), "same generator -> same action")
    q = np.full_like(ps, 1 / 9)
    uni = np.random.default_rng(9).random(2)
    z = mp.sample_actions(q[:1], np.full((1, 8), 1 / 8), [np.random.default_rng(9)])
    check(z[0, 0] == int(uni[0] * 9) and z[0, 1] == int(uni[1] * 8), "inverse CDF on the registered uniforms")
    return {"init_digest_seed1": d[:16]}


def unit_init_scaling(out: Path) -> Dict[str, Any]:
    """Registered initialisation check (design section 7) on real v3 observations: goal / state sensitivity ratio in
    [0.1, 10] for every seed; the goal branch is not saturated at initialisation."""
    if not INPUT_ALL.is_dir():
        return {"skipped": "pinned traces missing"}
    rep = init_check_report()
    check(rep["sensitivity_in_registered_range"], f"sensitivity ratio {rep['ratio_range']}")
    check(all(r["goal_branch_saturation"] < 0.05 for r in rep["per_seed"].values()), "goal branch saturated at init")
    return rep


def unit_coverage_logic(out: Path) -> Dict[str, Any]:
    """Base + increment coverage: covered, a new file, a changed file, a failed record and a tampered manifest."""
    sys.path.insert(0, str(REPO_ROOT / "rl" / "tools"))
    import m7s_gate as gate
    import runs_backup as rb

    src = out / "cov" / "runs"
    for rel, text in (("a/x.txt", "1"), ("m7r/y.txt", "22"), ("m7r/z/w.txt", "333")):
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text(text)

    def make_dest(dest: Path, source: Path) -> None:
        files, _s, _e = rb.walk(source)
        rows = [(rb.sha256_of(rb.native(source, r)), s, m, r) for r, (s, m) in sorted(files.items())]
        dest.mkdir(parents=True, exist_ok=True)
        sha = rb.write_tsv_gz(dest / rb.MANIFEST, rows)
        (dest / rb.RECORD).write_text(json.dumps({"result": "PASS", "manifest_sha256": sha, "source": str(source.resolve()),
                                                  "files": len(rows), "verified_utc": "t"}))

    base, inc = out / "cov" / "base", out / "cov" / "inc"
    make_dest(base, src)                     # base covers everything at first
    r = gate.combined_coverage(src, base, ())
    check(r["ok"], f"base alone {r}")
    (src / "m7r" / "new.txt").write_text("4444")
    r = gate.combined_coverage(src, base, ())
    check(not r["ok"] and r["uncovered"] == 1, "new file detected")
    make_dest(inc, src / "m7r")
    r = gate.combined_coverage(src, base, (inc,))
    check(r["ok"], f"base + increment {r}")
    time.sleep(0.02)
    (src / "a" / "x.txt").write_text("changed")
    r = gate.combined_coverage(src, base, (inc,))
    check(not r["ok"], "changed file detected")
    make_dest(base, src)
    rec = json.loads((inc / rb.RECORD).read_text())
    (inc / rb.RECORD).write_text(json.dumps(dict(rec, result="FAIL")))
    check(not gate.combined_coverage(src, base, (inc,))["ok"], "failed record refused")
    (inc / rb.RECORD).write_text(json.dumps(rec))
    with gzip.open(inc / rb.MANIFEST, "at") as fp:
        fp.write("x\t1\t1\tbogus\n")
    check(not gate.combined_coverage(src, base, (inc,))["ok"], "tampered manifest refused")
    return {"cases": 6}


def unit_contract_and_budget(out: Path) -> Dict[str, Any]:
    import m7s_gate as gate

    b = gate.TICK_BUDGET
    check(b["total"] == 3_108_269 and b["total"] < 3_139_200, f"total {b['total']}")
    check(sum(v for k, v in b.items() if k != "total") == b["total"], "sum")
    check(gate.P1_BUDGET == {"null_goal": 27_521, "goal_on": 1_548} and b["p1_identity"] == 29_069
          and gate.GOAL_ON_TICKS == gate.GOAL_ON["repeats"] * gate.GOAL_ON["reach_tick"], f"P1 caps {gate.P1_BUDGET}")
    check(b["clear_replays"] == 3 * gate.CLEAR_REPLAYS_PER_SEED * mg.HORIZON == 21_600, "clear replay cap")
    check((b["phase_a"], b["phase_b"], b["evaluation"], b["replays"]) == (216_000, 2_150_400, 648_000, 43_200),
          "unchanged phase caps")
    check(mc.PHASE_B_TICKS == 358_400 and mc.PHASE_B_TICKS % mp.CHUNK_TICKS == 0
          and mc.PHASE_B_TICKS // mp.CHUNK_TICKS == 70 and mc.PHASE_B_TICKS_PER_WORKER * mc.N_WORKERS == mc.PHASE_B_TICKS,
          "phase B arithmetic")
    check(mc.EVAL_EPISODES == 30 and mc.PHASE_A_PER_WORKER * mc.N_WORKERS == mg.PHASE_A_EPISODES, "episodes")
    check(len({mg.contract_digest(), mp.contract_digest()}) == 2, "digests")
    s = mc.env_settings()
    check(dict(s.extra_env).get("SSB64_RL_SPATIAL") == "1" and dict(s.extra_env).get("SSB64_RL_ENTITY") == "1"
          and s.reward.contract == "btt_reward_v2" and s.horizon == 3600, "M7n v3 environment")
    check(msw.m7s_contracts(3600, s.reward)["policy_observation_contract"] == mn.OBS_CONTRACT, "v3 contract unchanged")
    return {"total": b["total"], "p1": b["p1_identity"], "goal_contract": mg.contract_digest()[:16],
            "policy_contract": mp.contract_digest()[:16], "rule": ma.rule_digest()[:16]}


FORBIDDEN_IMPORTS = ("m7g_", "btti_replay", "m1e_", "m7h_", "m7m_")   # prefixes: M7g-a tooling, TAS replay, prefix curricula
FORBIDDEN_NAMES = ("run_prefix_phase", "rebase_for_policy_phase", "savestate", "load_state_from", "tas_rows")


def unit_no_forbidden_sources(out: Path) -> Dict[str, Any]:
    """No m7s training / collection module imports a fixture, TAS, replay-prefix or curriculum module or uses a
    prefix / state-restore entry point; only the gate (identity check and success replays) reads recorded traces."""
    found = []
    for name in ("m7s_goal.py", "m7s_policy.py", "m7s_worker.py", "m7s_collect.py", "m7s_analysis.py", "m7s_gate.py"):
        src = (REPO_ROOT / "rl" / name).read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            for m in mods:
                if any(m == f or m.startswith(f) for f in FORBIDDEN_IMPORTS):
                    found.append(f"{name}: import {m}")
                if name != "m7s_gate.py" and m == "m7f_trace":
                    found.append(f"{name}: training path imports m7f_trace")
            if isinstance(node, (ast.Name, ast.Attribute)):
                ident = node.id if isinstance(node, ast.Name) else node.attr
                if ident in FORBIDDEN_NAMES:
                    found.append(f"{name}: {ident}")
    check(not found, f"forbidden sources: {found}")
    return {"checked": 6}


def unit_analysis(out: Path) -> Dict[str, Any]:
    check(ma.self_test() == 0, "analysis self-test")
    return {"rule": ma.RULE_ID}


def unit_end_reason_interpretation(out: Path) -> Dict[str, Any]:
    """end_reason `horizon` is shared by three truncations; every gate result and replay consumer tells them apart by
    truncation_reason: only goal_reached is a return; tick_quota in an evaluation, a reach without goal_reached or
    goal_reached without a reach on the last tick are integrity problems; replays refuse any non-goal_reached row."""
    import m7s_collect as mcol
    import m7s_gate as gate

    def ep(entry, cell, er, tr, reach, ticks):
        return {"plan_entry": entry, "preserved": True, "end_reason": er, "truncation_reason": tr, "ticks": ticks,
                "episode_id": f"e{entry}", "artifact_dir": "x", "native_action_digest": "d", "rank": 0,
                "m7s": {"commanded": [{"cell": cell, "reach_tick": reach}]}}

    plan = [{"entry": e, "stratum": "rare", "cell": f"{e},1,-1"} for e in range(6)]
    clear_facts = {"termination_reason": "native_clear", "cleared": True, "targets_broken": 10,
                   "completion_time_passed": 3099, "completion_input_tick": 3100}
    good = [ep(0, "0,1,-1", "horizon", mg.END_GOAL, 812, 812),                  # return
            ep(1, "1,1,-1", "horizon", mg.NATIVE_HORIZON, None, 3600),          # native horizon: no return
            ep(2, "2,1,-1", "fall", None, None, 2210),                           # fall
            dict(ep(3, "3,1,-1", "clear", None, None, 3100), **clear_facts),     # clear: not a return
            ep(4, "4,1,-1", "lifecycle_failure", None, None, 90),
            ep(5, "5,1,-1", "horizon", mg.END_GOAL, 17, 17)]
    rows, probs = gate._eval_rows(mcol.PhaseResult(phase="E", episodes=good), plan)
    check(not probs, f"clean rows flagged: {probs}")
    check([r["success"] for r in rows] == [True, False, False, False, False, True], "success = goal_reached only")
    check([r["end_class"] for r in rows] == ["goal_reached", "native_horizon", "fall", "clear", "lifecycle_failure",
                                             "goal_reached"], "end classes")
    check(all(r["end_reason"] == "horizon" for r in rows if r["success"]), "tracker label of a return is horizon")
    bad = [ep(0, "0,1,-1", "horizon", mg.END_QUOTA, None, 5000),                # quota in an evaluation
           ep(1, "1,1,-1", "horizon", mg.NATIVE_HORIZON, 3000, 3600),           # reach without goal_reached
           ep(2, "2,1,-1", "horizon", mg.END_GOAL, None, 400),                  # goal_reached without a reach
           ep(3, "3,1,-1", "horizon", mg.END_GOAL, 100, 400),                   # reach not on the last tick
           ep(4, "4,1,-1", "horizon", "something_else", None, 10),
           ep(5, "5,1,-1", "horizon", mg.END_GOAL, 9, 9)]
    rows_b, probs_b = gate._eval_rows(mcol.PhaseResult(phase="E", episodes=bad), plan)
    check(len(probs_b) == 5 and not any("entry 5" in p for p in probs_b), f"integrity problems {probs_b}")
    check([r["success"] for r in rows_b] == [False, False, True, True, False, True], "success still = goal_reached")
    for r in rows:
        pre = gate.replay_precondition(r)
        check(bool(pre) == (not r["success"]), f"replay precondition {r['end_class']}: {pre}")
    check(gate.replay_precondition(rows_b[3]), "a goal_reached row whose reach is not the last tick is refused")
    refused = gate.replay_success(rows[1], out / "never", None, 0)
    check(not refused["ok"] and refused["ticks"] == 0, "replay_success refuses a native-horizon row without launching")
    check(gate.end_class({"end_reason": "horizon", "truncation_reason": mg.END_QUOTA}) == "tick_quota", "quota class")
    # a clear is accepted only with its four recorded facts in agreement; a cleared flag elsewhere is inconsistent
    for bad_clear in (ep(0, "0,1,-1", "clear", None, None, 3100),
                      dict(ep(0, "0,1,-1", "clear", None, None, 3100), **dict(clear_facts, targets_broken=9)),
                      dict(ep(0, "0,1,-1", "clear", None, None, 3100), **dict(clear_facts, completion_input_tick=None)),
                      dict(ep(0, "0,1,-1", "horizon", mg.NATIVE_HORIZON, None, 3600), cleared=True)):
        _rows, pb = gate._eval_rows(mcol.PhaseResult(phase="E", episodes=[bad_clear]), plan[:1])
        check(bool(pb), f"inconsistent clear record accepted: {bad_clear}")
    return {"clean_rows": len(rows), "problems_detected": len(probs_b)}


def unit_survival_diagnostic(out: Path) -> Dict[str, Any]:
    """The 120-tick survival diagnostic is recorded for collection reaches only and changes nothing decisive: a reach
    followed by a fatal fall 60 ticks later keeps its reach tick (the next goal was commanded at once), its cell stays
    valid for the archive and the labels, and survival reads False; a reach that lasts reads True; an episode that ends
    otherwise within 120 ticks leaves it None."""
    goal = mg.cell_of(150.0, 150.0, True, -1)
    goal2 = mg.cell_of(-2850.0, -2850.0, True, -1)
    far, near = (-3000.0, -3000.0), (150.0, 150.0)
    res = {}
    for label, positions, fall_at, horizon, want in (
            ("fall_after_60", [far] * 5 + [near] * 3 + [far] * 400, 65, None, False),
            ("survives", [far] * 5 + [near] * 3 + [far] * 400, None, 200, True),
            ("horizon_within_120", [far] * 5 + [near] * 3 + [far] * 400, None, 50, None)):
        env = _ReplyEnv(positions, fall_at=fall_at, horizon=horizon)
        probe = msw.GoalProbeWrapper(env, base=env)
        tracker = _TrackerStub(out / label)

        class V3(gym.Wrapper):
            def __init__(self, e):
                super().__init__(e)
                self.observation_space = mn.make_observation_space()

            @property
            def _last_reply(self):
                return env.last_reply

            def reset(self, **kw):
                self.env.reset(**kw)
                return {k: np.zeros(sh, np.float32) for k, sh in mn.SHAPES.items()}, {}

            def step(self, a):
                _o, r, term, trunc, info = self.env.step(a)
                if term or trunc:
                    tracker.end("fall" if term else "horizon")
                return {k: np.zeros(sh, np.float32) for k, sh in mn.SHAPES.items()}, r, term, trunc, info

        v3 = V3(probe)
        probe.reply_source = lambda: env.last_reply
        gw = msw.GoalObsWrapper(v3, probe=probe, v3=v3, tracker=tracker, rank=0)
        gw.m7s_configure({"mode": "schedule", "phase": "B", "tick_quota": 10 ** 6, "end_on_success": False,
                          "schedule": {1: [goal, goal2]}})
        tracker.begin()
        gw.reset()
        while True:
            _o, _r, term, trunc, info = gw.step(np.array([0, 0]))
            if term or trunc:
                break
        side = json.load(gzip.open(Path(tracker.pending["artifact_dir"]) / mg.SIDECAR_FILE, "rt"))
        first = side["commanded"][0]
        check(first["reach_tick"] == 5 and first["survival_120"] is want, f"{label}: {first}")
        check(len(side["commanded"]) == 2 and side["commanded"][1]["set_tick"] == 5, f"{label}: next goal at the reach")
        valid = mg.valid_cells([mg.parse_key(c) if c else None for c in side["cells"]], fell=fall_at is not None)
        check(valid[4] == goal, f"{label}: the reached cell stays valid for the archive / labels")
        res[label] = {"reach_tick": first["reach_tick"], "survival_120": first["survival_120"], "ticks": side["ticks"]}
    return res


# -- revision 5: goal-blind rule, clear precedence, next-goal timing, the P1 goal-on check ------------------------------


def unit_goal_blind_rule(out: Path) -> Dict[str, Any]:
    """Rule v2: a goal-blind trained R (post-training goal-swap action TV < 0.01) never registers a pass however many
    goals it reaches; the seed is inconclusive with its success counts reported. The threshold is one fixed value
    (policy contract = rule), pinned by the rule digest in the approval identity; the gate hands
    post_training_sensitivity's record to the rule unchanged; analyse() refuses a pass from goal-blind seeds."""
    import m7s_gate as gate

    check(ma.GOAL_BLIND_TV == mp.GOAL_BLIND_TV == 0.01, "one fixed threshold")
    check(mp.contract_description()["goal_blind_tv"] == 0.01 and ma.rule_description()["goal_blind_tv"] == 0.01,
          "the threshold is pinned in the policy contract and the rule")
    ident = gate.identity()
    check(ident["rule"] == "m7s1_return_rule_v2" and ident["rule_sha256"] == ma.rule_digest()
          and ident["goal_blind_tv"] == 0.01, "the approval identity pins rule v2 and the threshold")
    check(ma.self_test() == 0, "rule self-test")
    blind = {"R_final": {"action_tv_goal_swap": 0.0042}, "U_initial": {"action_tv_goal_swap": 0.0004}, "goal_blind_flag": True}
    sighted = {"R_final": {"action_tv_goal_swap": 0.13}, "U_initial": {"action_tv_goal_swap": 0.0004}, "goal_blind_flag": False}
    check(gate.rule_goal_sensitivity(blind) == {"R_goal_swap_tv": 0.0042, "U_goal_swap_tv": 0.0004, "goal_blind_flag": True},
          "gate -> rule mapping")
    rare = [f"{k},20,-1" for k in range(10)]
    mid = [f"{k},5,4" for k in range(5)]

    def rows(stratum: str, goals: Sequence[str], wins: Sequence[int]) -> List[Dict[str, Any]]:
        return [{"stratum": stratum, "cell": g, "success": rep < w} for g, w in zip(goals, wins) for rep in range(2)]

    r_eval = rows("rare", rare, [2, 1, 1, 1, 1, 1, 0, 0, 0, 0]) + rows("mid", mid, [2, 2, 1, 1, 1])
    u_eval = rows("rare", rare, [0] * 10) + rows("mid", mid, [1, 0, 0, 0, 0])

    def seed_rec(sens: Mapping[str, Any]) -> Dict[str, Any]:
        return {"problems": [], "reported": {},
                "analysis_inputs": {"r_eval": r_eval, "u_eval": u_eval, "rare_goals": rare, "mid_goals": mid,
                                    "data_counts": {g: 3 for g in rare}, "goal_sensitivity": gate.rule_goal_sensitivity(sens)}}

    def state(*recs: Mapping[str, Any]) -> Dict[str, Any]:
        return {"phases": {"p1_identity": {"ok": True}, "seeds": {str(s): seed_rec(r) for s, r in enumerate(recs)}},
                "ledger": {}}

    saved = gate.STATE_DIR
    gate.STATE_DIR = out / "_gate"
    try:
        d_blind = gate.analyse(state(blind, blind, blind))
        d_mixed = gate.analyse(state(sighted, blind, blind))
        d_pass = gate.analyse(state(sighted, sighted, blind))
    finally:
        gate.STATE_DIR = saved
    per = d_blind["per_seed"]["0"]
    check(d_blind["outcome"] == "inconclusive" and d_blind["counts"]["goal_blind_blocked_pass"] == ["0", "1", "2"],
          f"three goal-blind would-pass seeds: {d_blind['outcome']}")
    check(per["rare_criteria_met"] and not per["rare_pass"] and per["R_rare_successes"] == 7 and per["U_rare_successes"] == 0
          and per["R_distinct_rare_goals"] == 6 and per["R_goal_swap_tv"] == 0.0042
          and any("goal-blind" in b and "R 7 vs U 0" in b for b in d_blind["reasons"]["0"]), f"counts reported {per}")
    check(d_mixed["outcome"] == "inconclusive" and d_mixed["counts"]["rare_pass"] == ["0"], f"1 sighted + 2 blind {d_mixed}")
    check(d_pass["outcome"] == "pass_return_learned", f"2 sighted + 1 blind {d_pass['outcome']}")
    return {"rule": ma.RULE_ID, "rule_sha256": ma.rule_digest()[:16], "blind": d_blind["outcome"],
            "one_sighted": d_mixed["outcome"], "two_sighted": d_pass["outcome"]}


class _ZeroV3(gym.Wrapper):
    """Stands for the v3 wrapper in synthetic stacks (zero observation; the raw reply comes from the native stand-in)."""

    def __init__(self, env: gym.Env, native: "_ReplyEnv"):
        super().__init__(env)
        self.observation_space = mn.make_observation_space()
        self.native = native

    @property
    def _last_reply(self):
        return self.native.last_reply

    def _o(self) -> Dict[str, np.ndarray]:
        return {k: np.zeros(sh, np.float32) for k, sh in mn.SHAPES.items()}

    def reset(self, **kw):
        self.env.reset(**kw)
        return self._o(), {}

    def step(self, a):
        _o, r, term, trunc, info = self.env.step(a)
        return self._o(), r, term, trunc, info


CLEAR_FACTS = {"termination_reason": "native_clear", "cleared": True, "targets_broken": 10,
               "completion_time_passed": 11, "completion_input_tick": 12}


class _EndRecorder(gym.Wrapper):
    """The tracker's role on episode end: end_reason clear / fall / horizon with the recorded clear facts."""

    def __init__(self, env: gym.Env, tracker: "_TrackerStub"):
        super().__init__(env)
        self.tracker = tracker

    def step(self, a):
        o, r, term, trunc, info = self.env.step(a)
        if term or trunc:
            reason = info.get("termination_reason") if term else None
            self.tracker.end("clear" if reason == "native_clear" else "fall" if term else "horizon",
                             truncation=info.get("truncation_reason") if trunc else None)
            self.tracker.pending.update(CLEAR_FACTS if reason == "native_clear" else
                                        {"termination_reason": reason, "cleared": False})
        return o, r, term, trunc, info


class _ClearEnv(_ReplyEnv):
    """_ReplyEnv plus a native clear on tick `clear_at` (terminated, never truncated, as battleship_env) and the
    max_episode_steps truncation reason on the horizon tick."""

    def __init__(self, positions: Sequence[Tuple[float, float]], *, clear_at: Optional[int], horizon: Optional[int] = None):
        super().__init__(positions, horizon=horizon)
        self.clear_at = clear_at

    def step(self, action):
        o, r, term, trunc, info = super().step(action)
        if self.clear_at is not None and self.k == self.clear_at:
            return o, r, True, False, {"termination_reason": "native_clear"}
        if trunc:
            info = dict(info, truncation_reason="max_episode_steps")
        return o, r, term, trunc, info


def _synthetic_goal_stack(native: "_ReplyEnv", root: Path, cfg: Mapping[str, Any]):
    probe = msw.GoalProbeWrapper(native, base=native)
    tracker = _TrackerStub(root)
    v3 = _ZeroV3(_EndRecorder(probe, tracker), native)
    probe.reply_source = lambda: native.last_reply
    gw = msw.GoalObsWrapper(v3, probe=probe, v3=v3, tracker=tracker, rank=0)
    gw.m7s_configure(dict(cfg))
    return gw, tracker


def _run_until_done(gw: msw.GoalObsWrapper, tracker: "_TrackerStub", limit: int = 5000):
    tracker.begin()
    obs, _ = gw.reset()
    steps = []
    for _ in range(limit):
        obs, _r, term, trunc, info = gw.step(np.array([0, 0]))
        steps.append((obs, term, trunc, info))
        if term or trunc:
            break
    summary = tracker.pop()
    side = json.load(gzip.open(Path(summary["artifact_dir"]) / mg.SIDECAR_FILE, "rt"))
    return steps, summary, side


def unit_clear_precedence(out: Path) -> Dict[str, Any]:
    """A native clear on the tick the commanded cell is entered is a clear, never a return: in evaluation (also on the
    native horizon tick) it ends terminated with no truncation reason and no reach; in collection it records no reach
    and commands no next goal. The evaluation analysis accepts the clear row (no unknown-reason or integrity
    problem), the rule never counts it, the return replay refuses it, and it becomes a clear candidate that is claimed
    only after an exact native replay. Without a clear, a valid reach on the horizon tick is goal_reached through
    the full goal stack."""
    import m7s_collect as mcol
    import m7s_gate as gate

    goal = mg.cell_of(150.0, 150.0, True, -1)
    key = mg.cell_key(goal)
    far, near = (-3000.0, -3000.0), (150.0, 150.0)
    plan = [{"entry": 0, "stratum": "rare", "cell": key}]
    ev = {"mode": "plan", "phase": "E_R", "episode_quota": 1, "end_on_success": True, "plan": [{"entry": 0, "goal": goal}]}

    def row_of(summary, side):
        c = mcol._Episode(rank=0, worker_episode=1, plan_entry=0, gen=None, pos=(0.0, 0.0), cells=list(side["cells"]))
        return mcol._finish(c, summary, False, None, "E_R")

    res: Dict[str, Any] = {}
    for label, horizon in (("clear_on_reach_tick", None), ("clear_on_reach_and_horizon_tick", 12)):
        native = _ClearEnv([far] * 12 + [near] * 5, clear_at=12, horizon=horizon)
        gw, tracker = _synthetic_goal_stack(native, out / label, ev)
        steps, summary, side = _run_until_done(gw, tracker)
        _obs, term, trunc, info = steps[-1]
        check(len(steps) == 12 and term and not trunc and "truncation_reason" not in info
              and info.get("termination_reason") == "native_clear", f"{label}: end {len(steps)} {term} {trunc} {info}")
        check(not any("reached" in s[3]["m7s"]["events"] for s in steps) and side["commanded"][0]["reach_tick"] is None
              and side["truncation_reason"] is None and side["termination_reason"] == "native_clear", f"{label}: sidecar {side}")
        check(side["cells"][-1] == key, f"{label}: the clear tick is in the commanded cell")
        row = row_of(summary, side)
        rows, probs = gate._eval_rows(mcol.PhaseResult(phase="E", episodes=[row]), plan)
        check(not probs and rows[0]["end_class"] == "clear" and not rows[0]["success"] and rows[0]["cleared"],
              f"{label}: evaluation analysis {probs} {rows}")
        check(gate.replay_precondition(rows[0]), f"{label}: a clear is refused as return evidence")
        cmp_ = ma.seed_comparison(0, rows, [], [key], [], {}, {"R_goal_swap_tv": 0.2, "U_goal_swap_tv": 0.0,
                                                                 "goal_blind_flag": False})
        check(cmp_["R_rare_successes"] == 0, f"{label}: the rule never counts a clear")
        cands, cprobs = gate.clear_candidates([("evaluation_R", [row])])
        check(not cprobs and len(cands) == 1 and cands[0]["goal_reach_tick"] is None, f"{label}: clear candidate {cands}")
        res[label] = {"ticks": len(steps), "end_class": rows[0]["end_class"]}
    # the claim needs an exact native replay: verified replay -> claimed; over the cap -> never claimed
    fake_ok = lambda art, work, **kw: {"ok": True, "checks": {"native_clear": True, "completion_clocks": True},
                                       "completion_time_passed": 11, "completion_input_tick": 12, "submitted": 12}
    settings = SimpleNamespace(executable="x", extra_env=())
    v = gate.verify_clears(cands, out / "v", settings, index_base=0, replay=fake_ok)
    check(v["verified"] == 1 and not v["problems"] and v["ticks"] == 12, f"verified clear {v}")
    v0 = gate.verify_clears(cands, out / "v0", settings, index_base=0, cap=0, replay=fake_ok)
    check(v0["verified"] == 0 and len(v0["unverified_not_claimed"]) == 1 and v0["ticks"] == 0, f"cap 0 {v0}")
    # collection: a clear on the reach tick records no reach and commands no next goal
    native = _ClearEnv([far] * 12 + [near] * 5, clear_at=12)
    gw, tracker = _synthetic_goal_stack(native, out / "collection", {"mode": "schedule", "phase": "B", "tick_quota": 10 ** 6,
                                                                     "end_on_success": False,
                                                                     "schedule": {1: [goal, (0, 0, mg.AIR)]}})
    steps, summary, side = _run_until_done(gw, tracker)
    check(len(side["commanded"]) == 1 and side["commanded"][0]["reach_tick"] is None and steps[-1][1],
          f"collection clear: {side['commanded']}")
    # no clear: a valid reach on the native horizon tick is goal_reached through the full goal stack
    native = _ClearEnv([far] * 12 + [near] * 5, clear_at=None, horizon=12)
    gw, tracker = _synthetic_goal_stack(native, out / "horizon_reach", ev)
    steps, summary, side = _run_until_done(gw, tracker)
    _obs, term, trunc, info = steps[-1]
    check(len(steps) == 12 and trunc and not term and info["truncation_reason"] == mg.END_GOAL
          and side["commanded"][0]["reach_tick"] == 12 and summary["truncation_reason"] == mg.END_GOAL, "horizon reach")
    rows, probs = gate._eval_rows(mcol.PhaseResult(phase="E", episodes=[row_of(summary, side)]), plan)
    check(not probs and rows[0]["success"] and rows[0]["end_reason"] == "horizon", f"horizon reach row {probs} {rows}")
    res["horizon_reach"] = {"ticks": len(steps), "truncation_reason": info["truncation_reason"]}
    return res


def unit_next_goal_timing(out: Path) -> Dict[str, Any]:
    """Collection: a goal selected after a reach applies to the next action tick. The reach step already returns the
    next goal in its observation (so it first governs a_k, consumed at k + 1); exactly one native action goes out per
    env.step (nothing is inserted on the reach tick); the next goal is never evaluated on the reach tick itself, so a
    repeated cell is reached one tick later at the earliest."""
    g1 = mg.cell_of(150.0, 150.0, True, -1)
    g2 = mg.cell_of(750.0, 150.0, True, -1)
    far, p1, p2 = (-3000.0, -3000.0), (150.0, 150.0), (750.0, 150.0)
    res = {}
    for label, positions, sched, want in (("next_cell", [far] * 5 + [p1, p2] + [far] * 30, [g1, g2], [5, 6]),
                                          ("same_cell", [far] * 5 + [p1] * 3 + [far] * 30, [g1, g1], [5, 6])):
        native = _ReplyEnv(positions, horizon=20)
        orig = native.step
        native.step = lambda a, _o=orig: (lambda r: (r[0], r[1], r[2], r[3], dict(r[4], truncation_reason="max_episode_steps")
                                                     if r[3] else r[4]))(_o(a))
        gw, tracker = _synthetic_goal_stack(native, out / label, {"mode": "schedule", "phase": "B", "tick_quota": 10 ** 6,
                                                                  "end_on_success": False, "schedule": {1: sched}})
        steps, _summary, side = _run_until_done(gw, tracker)
        check(len(native.received) == len(steps) == 20, f"{label}: {len(native.received)} native actions for {len(steps)} steps")
        reached = [k for k, s in enumerate(steps, start=1) if "reached" in s[3]["m7s"]["events"]]
        check(reached == want, f"{label}: reaches {reached}")
        check([(c["set_tick"], c["reach_tick"]) for c in side["commanded"]] == [(0, want[0]), (want[0], want[1])],
              f"{label}: sidecar {side['commanded']}")
        x, y = positions[want[0]]
        obs_k = steps[want[0] - 1][0]
        check(np.array_equal(obs_k[msw.GOAL_KEY], mg.goal_features(sched[1], x, y, mg.HORIZON - want[0])),
              f"{label}: the reach step's observation carries the next goal")
        res[label] = {"reaches": reached, "native_actions": len(native.received)}
    return res


class _GoalOnProcess:
    """A fake BattleShip process with its episode client (the recorded replies): alive until closed."""

    def __init__(self, trace: Mapping[str, Any], pid: int, cleanup: str):
        self.client = _FakeClient(trace)
        self.pid, self._cleanup = pid, cleanup
        self._alive = True
        self.cleanup_action: Optional[str] = None

    @property
    def alive(self) -> bool:
        return self._alive

    def crash(self) -> None:
        self._alive = False

    def close(self) -> str:
        if self.cleanup_action is None:
            self.cleanup_action = self._cleanup if self._alive else "already_exited"
            self._alive = self.cleanup_action == "still_alive"
        return self.cleanup_action


class _GoalOnBase:
    """Lifecycle stand-in: the v3 wrapper's episode / last_observe / last_step_result and the termination facts the
    goal-on check reads (episode.alive / cleanup_action, live_processes, standby history, last_standby_close)."""

    def __init__(self, trace: Mapping[str, Any], faults: Mapping[str, Any]):
        self.trace, self.faults = trace, faults
        self.episode: Optional[_GoalOnProcess] = None
        self.last_observe = self.last_step_result = None
        self.standby = SimpleNamespace(history=[])
        self.last_standby_close: Optional[Dict[str, Any]] = None
        self.launches = 0

    def launch(self) -> None:
        if self.episode is not None:
            self.episode.close()                  # as M7BattleShipBTTEnv.reset retires the previous process
        self.launches += 1
        self.episode = _GoalOnProcess(self.trace, 4000 + self.launches, self.faults.get("cleanup", "terminated"))
        self.last_observe = SimpleNamespace(observation=dict(self.trace["initial"]["observation"]))
        self.last_step_result = None

    def live_processes(self) -> int:
        return int(self.episode is not None and self.episode.alive)

    def close(self) -> None:
        if self.episode is not None:
            self.episode.close()
            self.episode = None
        self.standby.history.append({"generation": 99, "cleanup_action": self.faults.get("standby_cleanup", "terminated")})
        self.last_standby_close = {"cancelled_generation": 99, "thread_joined": True, "state": "no_standby"}


class _GoalOnNative(gym.Env):
    """Track1PolicyWrapper and below: each word goes out as a `step` request on the process's recorded-reply client."""

    observation_space = gym.spaces.Box(-np.inf, np.inf, (15,), np.float32)
    action_space = gym.spaces.MultiDiscrete([9, 8])

    def __init__(self, base: _GoalOnBase, tracker: "_TrackerStub"):
        self.base, self.tracker = base, tracker
        self.submitted: List[Tuple[int, int, int, int]] = []

    def reset(self, *, seed=None, options=None):
        self.base.launch()
        self.tracker.begin()
        self.submitted = []
        return np.zeros(15, np.float32), {}

    def step(self, action):
        b, sx, sy = _native_of((int(action[0]), int(action[1])))
        self.submitted.append((len(self.submitted), b, sx, sy))
        r = self.base.episode.client.request("step")
        self.base.last_step_result = SimpleNamespace(step_count=r["step_count"])
        return np.zeros(15, np.float32), -0.001, False, False, {"consumed_tick": len(self.submitted) - 1}


class _GoalOnRecorder(gym.Wrapper):
    """The M4 recorder + tracker roles on episode end: the artifact's native words (words.json), the tracker-format
    native_action_digest and the summary facts; optional faults corrupt one of them."""

    def __init__(self, env: gym.Env, worker: "_GoalOnWorker"):
        super().__init__(env)
        self.worker = worker

    def step(self, a):
        o, r, term, trunc, info = self.env.step(a)
        if term or trunc:
            w, f = self.worker, self.worker.faults
            words = list(w.native.submitted)
            digest = hashlib.sha256("".join(f"{b},{sx},{sy},{t}\n" for t, b, sx, sy in words).encode("ascii")).hexdigest()
            w.tracker.end("horizon" if trunc else "fall", digest=digest, truncation=info.get("truncation_reason") if trunc else None)
            if f.get("corrupt_word") is not None:
                t, b, sx, sy = words[f["corrupt_word"]]
                words[f["corrupt_word"]] = (t, b, 80 if sx != 80 else -80, sy)
            (Path(w.tracker.pending["artifact_dir"]) / "words.json").write_text(json.dumps(words))
            w.tracker.pending.update(steps=len(w.native.submitted), cleared=False, termination_reason=None,
                                     startup_mode="cold_start" if w.base.launches == 1 else "standby_promoted")
            if f.get("summary_truncation"):
                w.tracker.pending["truncation_reason"] = f["summary_truncation"]
            if f.get("crash_on_truncation") and trunc:
                w.base.episode.crash()
        return o, r, term, trunc, info


class _GoalOnWorker:
    """The goal worker of the P1 goal-on check with the REAL GoalProbeWrapper, EntityObsV3Wrapper and GoalObsWrapper
    over recorded replies; the M7WorkerWrapper slim infos (m7s, m7_episode, truncation / termination reasons)."""

    def __init__(self, trace: Mapping[str, Any], root: Path, faults: Optional[Mapping[str, Any]] = None):
        self.faults = dict(faults or {})
        self.base = _GoalOnBase(trace, self.faults)
        self.tracker = _TrackerStub(root)
        self.native = _GoalOnNative(self.base, self.tracker)
        probe = msw.GoalProbeWrapper(self.native, base=self.base)
        v3 = mn.EntityObsV3Wrapper(_GoalOnRecorder(probe, self), base=self.base, character="mario")
        probe.reply_source = lambda: v3._last_reply
        self.goal = msw.GoalObsWrapper(v3, probe=probe, v3=v3, tracker=self.tracker, rank=0)

    def reset(self):
        obs, _info = self.goal.reset()
        return obs, {"m7s": self.goal.last_reset_record}

    def step(self, action):
        obs, r, term, trunc, info = self.goal.step(action)
        slim = {"m7s": self.goal.last_step_record}
        for k in ("truncation_reason", "termination_reason"):
            if k in info:
                slim[k] = info[k]
        if term or trunc:
            slim["m7_episode"] = self.tracker.pop()
        return obs, r, term, trunc, slim

    def close(self) -> None:
        self.base.close()


def _fake_words(artifact_dir: Path) -> List[Tuple[int, int, int, int]]:
    return [tuple(w) for w in json.loads((Path(artifact_dir) / "words.json").read_text())]


def unit_p1_goal_on_expected(out: Path) -> Dict[str, Any]:
    """The registered P1 goal-on expectations are exactly what the pinned trace gives: a normal tick-0 trace, 774 Track 1
    words, goal (17, 8, floor 2) first validly occupied on tick 774 while the same bin is occupied in the air from tick
    771 (a contact-blind probe would stop early), and a v3 block equal to the v3 builder applied directly. A changed
    trace, reach tick, contact class or v3 digest is refused before anything could launch."""
    import m7s_gate as gate

    if not INPUT_ALL.is_dir():
        return {"skipped": "pinned traces missing"}
    import m7f_trace as mt
    import m7g_spatial as ms
    import m7n_entity as ne
    import m7n_status_table as st

    exp = gate.goal_on_expected()
    check(not exp["problems"], f"expectation problems {exp['problems']}")
    check(exp["reach_tick"] == 774 and exp["goal_key"] == "17,8,2" and len(exp["words"]) == len(exp["track1"]) == 774
          and exp["v3"].shape == (775, mp.V3_DIM) and exp["goal_vectors"].shape == (775, mg.GOAL_DIM), "shapes")
    check(exp["same_bin_other_contact_tick"] == 771 and exp["cells"][770] == "17,8,-1", "contact-discriminating goal")
    check(gate.GOAL_ON["trace"].startswith("runs/m7q/_equiv/input_all/") and "tas" not in gate.GOAL_ON["trace"],
          "a pinned policy trace, not a TAS or human recording")
    tr = mt.read_trace(REPO_ROOT / gate.GOAL_ON["trace"])
    ini = tr["initial"]
    sp0 = ms.spatial_of(ini, expect_lines=True)
    b = mn.EntityObservationBuilder(sp0.lines or (), st.ActionClassifier(st.load_table(), "mario"))
    direct = [mn.flatten(b.build(ini["observation"], sp0, ne.entity_of(ini))[0])]
    for r in tr["steps"][:774]:
        direct.append(mn.flatten(b.build(r["observation"], ms.spatial_of(r, expect_lines=False), ne.entity_of(r))[0]))
    check(np.asarray(direct, np.float32).tobytes() == exp["v3"].tobytes(), "wrapper path == direct builder path")
    bad_trace = out / "tampered.json.gz"
    bad_trace.write_bytes((REPO_ROOT / gate.GOAL_ON["trace"]).read_bytes() + b"\0")
    check(any("sha256" in p for p in gate.goal_on_expected(trace_path=bad_trace)["problems"]), "a changed trace is refused")
    e775 = gate.goal_on_expected(dict(gate.GOAL_ON, reach_tick=775))["problems"]
    check(any("first validly occupied on tick 774" in p for p in e775) and any("word-prefix" in p for p in e775),
          f"a wrong reach tick is refused {e775}")
    check(any("first validly occupied on tick 771" in p
              for p in gate.goal_on_expected(dict(gate.GOAL_ON, goal="17,8,-1"))["problems"]), "the contact class matters")
    check(any("v3 block digest" in p for p in gate.goal_on_expected(dict(gate.GOAL_ON, v3_prefix_sha256="0" * 64))["problems"]),
          "a changed v3 digest is refused")
    return {"reach_tick": exp["reach_tick"], "goal": exp["goal_key"], "v3_prefix_sha256": exp["v3_prefix_sha256"][:16],
            "same_bin_air_from": exp["same_bin_other_contact_tick"]}


def unit_p1_goal_on_check(out: Path) -> Dict[str, Any]:
    """goal_on_check on the real goal / probe / v3 wrappers over the pinned recorded replies (fake processes). It
    passes with exactly 2 x 774 ticks, the first parked process retired by terminate() and a clean close. Every
    registered condition fails it, stops it after the failing repetition and never sends a word after tick 774: a
    recorded word differs; a v3 value differs; the goal's contact differs on tick 774 (no reach); an earlier reach;
    a tracker truncation reason other than goal_reached; a parked process that died; a killed process; a leftover
    BattleShip process; a standby cleanup failure; and a refused expectation launches nothing."""
    import copy

    import m7f_trace as mt
    import m7s_gate as gate

    if not INPUT_ALL.is_dir():
        return {"skipped": "pinned traces missing"}
    exp = gate.goal_on_expected()
    tr = mt.read_trace(REPO_ROOT / gate.GOAL_ON["trace"])
    R = exp["reach_tick"]

    def run(label: str, *, trace: Optional[Mapping[str, Any]] = None, faults: Optional[Mapping[str, Any]] = None,
            procs: Sequence[int] = ()) -> Dict[str, Any]:
        rep = gate.goal_on_check(out / label, None, expected=exp,
                                 make_env=lambda: _GoalOnWorker(trace or tr, out / label / "art", faults),
                                 read_words=_fake_words, processes=lambda: list(procs))
        check(rep["ticks"] <= gate.P1_BUDGET["goal_on"] and "termination" in rep, f"{label}: cap / close {rep['ticks']}")
        return rep

    ok = run("pass")
    check(ok["ok"] and ok["ticks"] == 2 * R and len(ok["repetitions"]) == 2 and not ok["problems"], f"pass {ok['problems']}")
    check(ok["repetitions"][0]["retire_action"] == "terminated" and ok["termination"]["last_cleanup_action"] == "terminated"
          and all(r["first_reach"] == R and r["end"]["truncation_reason"] == mg.END_GOAL for r in ok["repetitions"]),
          "pass details")

    def perturbed(fn: Callable[[Dict[str, Any]], None]) -> Dict[str, Any]:
        t = copy.deepcopy(tr)
        fn(t)
        return t

    def shift_x(t):
        t["steps"][299]["observation"]["position_x"] += 1.0

    def airborne_at_reach(t):
        t["steps"][R - 1]["observation"]["ground_air_state"] = 1
        t["steps"][R - 1]["spatial"]["fighter"]["floor_line_id"] = -1

    def early_reach(t):
        early = copy.deepcopy(t["steps"][R - 1])
        early["step_count"] = t["steps"][499]["step_count"]
        t["steps"][499] = early

    cases = {
        "word": (dict(faults={"corrupt_word": 100}), ("first difference at word 100",)),
        "v3": (dict(trace=perturbed(shift_x)), ("v3 block differs at", "first [300")),
        "contact": (dict(trace=perturbed(airborne_at_reach)), ("first valid reach on tick None",)),
        "early_reach": (dict(trace=perturbed(early_reach)), ("first valid reach on tick 500",)),
        "truncation_reason": (dict(faults={"summary_truncation": "max_episode_steps"}),
                              ("tracker summary horizon / max_episode_steps",)),
        "died_parked": (dict(faults={"crash_on_truncation": True}), ("not alive and parked",)),
        "killed": (dict(faults={"cleanup": "killed"}), ("retired as killed",)),
        "leftover_process": (dict(procs=[4242]), ("BattleShip processes left after close: [4242]",)),
        "standby_cleanup": (dict(faults={"standby_cleanup": "cleanup_failure: survived"}), ("standby cleanup failures",)),
    }
    seen = {}
    for label, (kw, needles) in cases.items():
        rep = run(label, **kw)
        text = " | ".join(rep["problems"])
        check(not rep["ok"] and all(n in text for n in needles), f"{label}: expected {needles} in {rep['problems'][:6]}")
        check(len(rep["repetitions"]) == (2 if label in ("leftover_process", "standby_cleanup") else 1),
              f"{label}: stops after the failing repetition ({len(rep['repetitions'])})")
        seen[label] = {"ticks": rep["ticks"], "problems": len(rep["problems"])}
    check(seen["early_reach"]["ticks"] == 500 and seen["word"]["ticks"] == R, "ticks sent")

    def never():
        raise AssertionError("launched although the expectation was refused")

    refused = gate.goal_on_check(out / "refused", None, expected={"problems": ["pinned trace sha256 x != y"]},
                                 make_env=never, read_words=_fake_words, processes=lambda: [])
    check(not refused["ok"] and refused["ticks"] == 0 and "termination" not in refused, "refused before launch")
    return {"pass_ticks": ok["ticks"], "failures": seen}


def unit_p1_stops_gate(out: Path) -> Dict[str, Any]:
    """P1 runs before any training and stops the gate: a failing goal-on check (or null-goal check, or a raised check,
    or ticks over a cap) returns 3 without calling the seed phase, and the state record names where P1 stopped with
    its ticks on the P1 ledger; only a complete P1 (27,521 + 1,548 ticks) lets seed 0 start. Nothing under runs/ is
    written (the gate root is redirected)."""
    import m7_runtime
    import m7s_gate as gate

    saved = (gate.GATE_ROOT, gate.STATE_DIR, gate.preflight, m7_runtime.install_kill_on_close_job)
    gate.GATE_ROOT = out / "gate"
    gate.STATE_DIR = gate.GATE_ROOT / "_gate"
    gate.preflight = lambda **kw: {"ok": True, "problems": []}
    m7_runtime.install_kill_on_close_job = lambda: None
    calls: List[int] = []

    def seed_fn(s, settings, ledger):
        calls.append(s)
        return {"problems": ["stop after the first seed (test)"], "seed": s}

    def p1_with(ng, go):
        return lambda work, settings: gate.p1_identity(work, settings, null_goal=ng, goal_on=go)

    good_ng = lambda w, s: {"ok": True, "ticks": gate.P1_BUDGET["null_goal"]}
    good_go = lambda w, s: {"ok": True, "ticks": gate.P1_BUDGET["goal_on"]}
    out_rec = {}
    try:
        for label, p1, want_stop in (
                ("goal_on_fails", p1_with(good_ng, lambda w, s: {"ok": False, "ticks": 774, "problems": ["v3"]}), "goal_on"),
                ("null_goal_fails", p1_with(lambda w, s: {"ok": False, "ticks": 3361}, good_go), "null_goal"),
                ("goal_on_raises", p1_with(good_ng, lambda w, s: 1 / 0), "goal_on"),
                ("goal_on_over_cap", p1_with(good_ng, lambda w, s: {"ok": True, "ticks": gate.P1_BUDGET["goal_on"] + 1}), "goal_on")):
            calls.clear()
            rc = gate.cmd_run(p1=p1, seed_fn=seed_fn)
            st = json.loads((gate.STATE_DIR / "state.json").read_text(encoding="utf-8"))
            p1rec = st["phases"]["p1_identity"]
            check(rc == 3 and not calls and "seeds" not in st["phases"] and p1rec["stopped_at"] == want_stop
                  and "no training started" in st["stopped"], f"{label}: rc {rc}, calls {calls}, {p1rec.get('stopped_at')}")
            check(st["ledger"]["p1_identity"] == p1rec["ticks"] <= gate.TICK_BUDGET["p1_identity"] + 1, f"{label}: ledger")
            out_rec[label] = {"rc": rc, "stopped_at": p1rec["stopped_at"], "ticks": p1rec["ticks"]}
        calls.clear()
        rc = gate.cmd_run(p1=p1_with(good_ng, good_go), seed_fn=seed_fn)
        st = json.loads((gate.STATE_DIR / "state.json").read_text(encoding="utf-8"))
        check(rc == 0 and calls == [0] and st["phases"]["p1_identity"]["ok"]
              and st["ledger"]["p1_identity"] == gate.TICK_BUDGET["p1_identity"], f"complete P1: rc {rc}, calls {calls}")
        out_rec["complete"] = {"rc": rc, "seeds_started": calls}
    finally:
        gate.GATE_ROOT, gate.STATE_DIR, gate.preflight, m7_runtime.install_kill_on_close_job = saved
    check(not (REPO_ROOT / "runs" / "m7s").exists(), "nothing written under runs/")
    return out_rec


CASES: Dict[str, Callable[[Path], Dict[str, Any]]] = {
    "unit_cell_contract": unit_cell_contract,
    "unit_goal_features": unit_goal_features,
    "unit_reply_cells": unit_reply_cells,
    "unit_relabel": unit_relabel,
    "unit_goal_set_provenance": unit_goal_set_provenance,
    "unit_schedule_plan": unit_schedule_plan,
    "unit_probe": unit_probe,
    "unit_real_stack": unit_real_stack,
    "unit_collector": unit_collector,
    "unit_gcsl_synthetic": unit_gcsl_synthetic,
    "unit_policy_matched": unit_policy_matched,
    "unit_init_scaling": unit_init_scaling,
    "unit_coverage_logic": unit_coverage_logic,
    "unit_contract_and_budget": unit_contract_and_budget,
    "unit_no_forbidden_sources": unit_no_forbidden_sources,
    "unit_analysis": unit_analysis,
    "unit_end_reason_interpretation": unit_end_reason_interpretation,
    "unit_survival_diagnostic": unit_survival_diagnostic,
    "unit_goal_blind_rule": unit_goal_blind_rule,
    "unit_clear_precedence": unit_clear_precedence,
    "unit_next_goal_timing": unit_next_goal_timing,
    "unit_p1_goal_on_expected": unit_p1_goal_on_expected,
    "unit_p1_goal_on_check": unit_p1_goal_on_check,
    "unit_p1_stops_gate": unit_p1_stops_gate,
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("suite", choices=("unit",))
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--only", default="")
    a = ap.parse_args(argv)
    import torch

    torch.set_num_threads(1)
    out = a.out or Path(tempfile.mkdtemp(prefix="m7s_unit_"))
    out.mkdir(parents=True, exist_ok=True)
    only = [s for s in a.only.split(",") if s]
    results, failed = {}, 0
    for name, fn in CASES.items():
        if only and name not in only:
            continue
        t0 = time.perf_counter()
        case_dir = out / name
        case_dir.mkdir(parents=True, exist_ok=True)
        try:
            rep = fn(case_dir)
            results[name] = {"ok": True, "report": rep}
            print(f"PASS {name} ({time.perf_counter() - t0:.1f} s)")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            results[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-3000:]}
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    (out / "m7s_unit_results.json").write_text(json.dumps(results, indent=1, default=str) + "\n", encoding="utf-8")
    print(f"{len(results) - failed}/{len(results)} passed; results {out / 'm7s_unit_results.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
