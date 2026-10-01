#!/usr/bin/env python3
"""M7u2 (proposed gate m7u2) offline tests: zero native ticks. No BattleShip launch, no replay, no optimizer step.

    python rl/m7u2_tests.py unit [--out DIR] [--only NAME]
    python rl/m7u2_tests.py e2e  [--out DIR]

The synthetic native stand-in is m7u1's (rl/m7u_tests.py: copies of captured replies with synthetic values, driven
through the REAL m7u probe and trial wrappers). The frozen m7u1 model and the preserved runs/m7u records are read only.
Approval is tested against isolated temporary records, so the suite stays valid after a real approval record exists.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import m7u2_goals as g2  # noqa: E402
import m7u2_rule as r2  # noqa: E402
import m7u_planner as up  # noqa: E402
import m7u_state as us  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
F = us.F


class Failure(AssertionError):
    pass


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise Failure(msg)


# -- shared fixtures ---------------------------------------------------------------------------------------------------

_CACHE: Dict[str, Any] = {}


def m7u1():
    """(sources, tick-0 row, reference, frozen model), loaded once and checked against every pin."""
    import m7u2_gate as gg

    if "src" not in _CACHE:
        src = gg.load_m7u1_sources()
        _CACHE.update(src=src, row0=gg.tick0_row(src), ref=gg.reference(src), fz=gg.load_frozen(src))
    return _CACHE["src"], _CACHE["row0"], _CACHE["ref"], _CACHE["fz"]


def _template():
    import m7u_tests as mt

    if "tpl" not in _CACHE:
        _CACHE["tpl"] = mt._Template()
    return _CACHE["tpl"]


def _air_native_class():
    """m7u1's synthetic native (copies of captured replies with synthetic values) with a richer airtime, test-only:
    3x horizontal speed, a ground jump (vy 120), one double jump (C button while falling slowly, vy 110, status
    JumpAerialF) and one up-B-like rise (B, vy 180, status SpecialAirHi) per airtime, gravity 4.8, so rare airborne
    points spread over thousands of units in both axes (with m7u1's 1-D-ish world they cluster in one narrow band)."""
    import m7u_tests as mt

    if "air" in _CACHE:
        return _CACHE["air"]

    class AirNative(mt._FakeNative):
        def _reply(self, op):
            r = super()._reply(op)
            r["observation"]["fighter_status_id"] = int(getattr(self, "status", 10))
            return r

        def reset(self, *, seed=None, options=None):
            out = super().reset(seed=seed, options=options)
            self.status, self.jumps, self.upb = 10, 0, False
            self.last_reply = self._reply("observe")
            return out

        def step(self, action):
            from btt_learning import TRACK1_STICK_TABLE

            s, b = int(action[0]), int(action[1])
            self.sx, self.sy = TRACK1_STICK_TABLE[s]
            self.x += self.sx * 0.75
            if self.ga == 0:
                if b in (3, 4) or self.sy > 0:
                    self.ga, self.vy, self.jumps, self.upb, self.status = 1, 120.0, 1, False, 22
            elif b == 2 and not self.upb:
                self.vy, self.upb, self.status = 180.0, True, 226
            elif b in (3, 4) and self.jumps == 1 and self.vy < 60.0:
                self.vy, self.jumps, self.status = 110.0, 2, 24
            if self.ga == 1:
                self.y += self.vy
                self.vy -= 4.8
                if self.y <= -2550.0:
                    self.y, self.vy, self.ga, self.status, self.jumps = -2550.0, 0.0, 0, 10, 0
            self.k += 1
            self.last_reply = self._reply("step")
            end = self.k >= self.horizon
            return np.zeros(1, np.float32), 0.0, False, end, ({"truncation_reason": "max_episode_steps"} if end else {})

    _CACHE["air"] = AirNative
    return AirNative


def _stack(root: Path, rank: int, horizon: int):
    """rl/m7u_tests._fake_stack with the richer synthetic native (the REAL m7u probe and trial wrappers)."""
    import gymnasium as gym

    import m7u_tests as mt
    import m7u_worker as uw

    native = _air_native_class()(horizon, _template())
    probe = uw.M7uProbeWrapper(native, base=native)
    tracker = mt._TrackerStub(root / f"w{rank}")

    class Recorder(gym.Wrapper):
        def reset(self, **kw):
            self.words = []
            return self.env.reset(**kw)

        def step(self, action):
            self.words.append((int(action[0]), int(action[1])))
            o, r, term, trunc, info = self.env.step(action)
            if term or trunc:
                tracker.end(info, self.words)
            return o, r, term, trunc, info

    class V4Stub(gym.Wrapper):
        _last_reply = None

        def reset(self, **kw):
            o, i = self.env.reset(**kw)
            self._last_reply = native.last_reply
            return o, i

        def step(self, a):
            o, r, t, tr, i = self.env.step(a)
            self._last_reply = native.last_reply
            return o, r, t, tr, i

    v4 = V4Stub(Recorder(probe))
    probe.reply_source = lambda: native.last_reply
    return uw.M7uTrialWrapper(v4, probe=probe, v4=v4, tracker=tracker, rank=rank), tracker


def fake_vec(root: Path, n: int, horizon: int):
    import m7u_tests as mt

    class Vec(mt._FakeVec):
        def __init__(self) -> None:          # noqa: D401 - the m7u1 vector over the richer stacks
            self.stacks = [_stack(root, r, horizon) for r in range(n)]
            self.num_envs, self.ranks, self.closed = n, list(range(n)), False
            self.reset_infos = [{} for _ in range(n)]

    return Vec()


def fake_single(root: Path, horizon: int):
    import m7u_tests as mt

    class Single(mt._FakeSingle):
        def __init__(self) -> None:
            self.trial, self.tracker = _stack(root, 0, horizon)

    return Single()


def ledger(**caps: int):
    """A ledger over the m7u2 phases with the given caps (others 0) and their sum as the total."""
    import m7u_gate as g1

    d = {"p1": 0, "pool": 0, "eval_control": 0, "replays": 0}
    d.update(caps)
    d["total"] = sum(d.values())
    return g1.Ledger(d)


def fake_row0(root: Path) -> np.ndarray:
    v = fake_vec(root / "_row0", 1, horizon=4)
    v.env_method_each("m7u_configure", {0: (({"mode": "collect", "phase": "pool",
                                                "entries": [{"entry": "x", "kind": "collect"}]},), {})})
    v.reset()
    return np.array(v.reset_infos[0]["m7u"]["row"], dtype=np.float64)


def fake_episodes(root: Path, names: Sequence[str], n_workers: int = 5, horizon: int = g2.POOL_TICKS,
                  n_candidates: int = 17) -> List[Dict[str, Any]]:
    """Behaviour episodes of the synthetic world from the normal reset (the m7u2 drive loop, phase 'pool')."""
    import m7u_gate as g1
    import m7u2_gate as gg

    vec = fake_vec(root, n_workers, horizon=horizon)
    row0 = fake_row0(root)
    led = ledger(pool=10 ** 7)
    return gg.drive(vec, gg.pool_configs(n_workers, names), phase="pool", ledger=led,
                    clock=g1.Clock(memory=lambda: None), n_candidates=n_candidates, row0=row0)


def fake_frozen(root: Path):
    """The REAL frozen m7u1 ensemble with a context whose clock track is rebuilt from synthetic episodes of 256 ticks
    (the synthetic world has its own platform clock; imagination reaches tick 128 + 64). Test-only."""
    import m7u2_gate as gg
    import m7u_model as um

    _src, _row0, _ref, fz = m7u1()
    eps = fake_episodes(Path(root) / "track", ["t0", "t1"], n_workers=2, horizon=256)
    track, probs = us.build_clock_track([e["rows"] for e in eps])
    check(not probs, f"synthetic clock track: {probs[:2]}")
    return gg.Frozen(model=fz.model, vocab=fz.vocab, ctx=um.make_context(fz.vocab, us.static_world_pinned(), track),
                     track=track)


# -- synthetic rows for goal-selection cases ---------------------------------------------------------------------------


def synth_rows(points: Mapping[int, Tuple[float, float]], T: int = 128, airborne: Sequence[int] = ()) -> np.ndarray:
    """T+1 rows: on the ground at the spawn except at the given ticks (x, y), which are airborne."""
    rows = np.zeros((T + 1, us.N_FIELDS))
    rows[:, F["valid"]] = 1.0
    rows[:, F["input_tick"]] = np.arange(T + 1)
    rows[:, F["y"]] = -2550.0
    rows[:, F["status"]] = 10
    for t, (x, y) in points.items():
        rows[t, F["x"]], rows[t, F["y"]] = x, y
        rows[t, F["ga"]] = 1.0
        rows[t, F["status"]] = 22
    for t in airborne:
        rows[t, F["ga"]] = 1.0
    return rows


def synth_pool(spec: Mapping[str, Mapping[int, Tuple[float, float]]], entries: Sequence[str]) -> List[Dict[str, Any]]:
    out = []
    for e in entries:
        rows = synth_rows(spec.get(e, {}))
        out.append({"entry": e, "episode_id": f"ep_{e}", "rows": rows, "words": np.zeros((len(rows) - 1, 2), np.int64),
                    "fell": False})
    return out


# -- unit cases --------------------------------------------------------------------------------------------------------


def unit_rule_and_scramble(out: Path) -> Dict[str, Any]:
    check(r2.self_test() == [], f"rule self-test: {r2.self_test()[:3]}")
    check((r2.N, r2.PASS_MIN_P, r2.PASS_MIN_BR, r2.PASS_MIN_BS, r2.NULL_MAX_BR, r2.NULL_MAX_BS) == (24, 6, 6, 5, 1, 0),
          "registered thresholds")
    pi = [g2.scrambled(k) for k in range(g2.N_GOALS)]
    check(sorted(pi) == list(range(24)) and all(pi[k] != k for k in range(24)) and all(pi[pi[k]] == k for k in range(24)),
          "pi is not an involutive derangement of 0..23")
    check(g2.SCRAMBLE_SHIFT == 12 and pi[0] == 12, "pi(k) = (k + 12) mod 24")
    return {"rule_sha256": r2.rule_digest(), "pi": pi[:4]}


def unit_goal_selection_rules(out: Path) -> Dict[str, Any]:
    entries = [f"c{i:03d}" for i in range(10)]
    ref_eps = [("r0", synth_rows({40: (0.0, -2000.0)}), False), ("r1", synth_rows({40: (0.0, -2000.0)}), False),
               ("r2", synth_rows({50: (1000.0, -2100.0)}), False)]
    ref = g2.Reference(ref_eps)
    # brute-force reference count
    for gx, gy, want in ((0.0, -2000.0, 2), (1000.0, -2100.0, 1), (1100.0, -2000.0, 1), (5000.0, 0.0, 0)):
        brute = sum(any(r[t, F["valid"]] == 1 and r[t, F["ga"]] == 1 and abs(r[t, F["x"]] - gx) <= 150
                        and abs(r[t, F["y"]] - gy) <= 150 for t in range(1, 129)) for _e, r, _f in ref_eps)
        check(ref.reaching(gx, gy) == brute == want, f"reference count at ({gx}, {gy}): {ref.reaching(gx, gy)} / {brute}")
    # Roles are fixed against the registered sha order (episodes c006, c009, c001, c008, c005, c004, c007).
    spec = {
        "c000": {40: (0.0, -2000.0)},                       # common (2 references): never eligible
        "c001": {40: (1000.0, -2100.0), 60: (-900.0, -1800.0)},   # one reference / rare; its sha-first tau is 60
        "c002": {20: (3000.0, -1000.0), 100: (3000.0, -1000.0)},  # outside the tau window: no candidate
        "c003": {50: (2000.0, -2400.0)},                    # rise 150 < 300: no candidate
        "c004": {50: (-3000.0, -1500.0)},                   # EXACT duplicate of c008's only point: skipped
        "c005": {50: (-3100.0, -1450.0)},                   # box OVERLAPS c008's but is a distinct definition: registered
        "c006": {70: (2500.0, -500.0)},
        "c007": {40: (-3000.0, -1500.0), 90: (-500.0, 0.0)},     # sha-first tau 40 duplicates c008: tau 90 registers
        "c008": {60: (-3000.0, -1500.0)},
        "c009": {45: (1500.0, -2000.0)},
    }
    pool = synth_pool(spec, entries)
    row0 = pool[0]["rows"][0]
    sel = g2.select_goals(pool, ref, row0, entries=entries, n_goals=6)
    goals, rec = sel["goals"], sel["record"]
    got = [g.entry for g in goals]
    check(got == ["c006", "c009", "c001", "c008", "c005", "c007"], f"registered {got}")
    check([g.tau for g in goals] == [70, 45, 60, 60, 50, 90], f"taus {[g.tau for g in goals]}")
    check(len(set(got)) == len(got), "more than one goal from one source episode")
    check(len({(g.x, g.y) for g in goals}) == len(goals), "an exact duplicate goal definition was registered")
    # overlap does not gate: c005's box overlaps c008's and both are registered, and the overlap is RECORDED
    ov = rec["overlap"]
    check({"c005", "c008"} <= set(got), "an overlapping (non-duplicate) goal was refused")
    check(ov["n_pairs"] == 1 and ov["pairs"][0]["entries"] == ["c008", "c005"] and ov["pairs"][0]["k"] == [3, 4],
          f"overlap pairs {ov['pairs']}")
    check(ov["per_goal"] == [0, 0, 0, 1, 1, 0] and ov["correlated_groups"] == [[3, 4]] and
          ov["independent_goals"] == 4 and ov["n_possible_pairs"] == 15, f"overlap record {ov}")
    check("correlated" in ov["reading"], "overlapping goals not described as correlated")
    for i, a in enumerate(goals):       # the recorded pairs equal a brute-force count over the registered goals
        for b_ in goals[i + 1:]:
            hit = abs(a.x - b_.x) <= g2.OVERLAP_SPAN and abs(a.y - b_.y) <= g2.OVERLAP_SPAN
            check(hit == ([i, goals.index(b_)] in [p_["k"] for p_ in ov["pairs"]]), "overlap record vs brute force")
    # duplicates: c004's only tau and c007's sha-first tau are passed over (recorded with the goal they duplicated);
    # c004 has no other tau and is skipped, c007 registers its second
    check(rec["passed_over_duplicates"] == [{"entry": "c004", "tau": 50, "duplicates": ["c008"]},
                                            {"entry": "c007", "tau": 40, "duplicates": ["c008"]}],
          f"passed over {rec['passed_over_duplicates']}")
    check(rec["skipped_for_duplicate"] == [{"entry": "c004", "eligible_taus": 1}], f"skipped {rec['skipped_for_duplicate']}")
    # a point one unit away is a different definition, not a duplicate
    near = [dict(p_) for p_ in pool]
    i4 = [p_["entry"] for p_ in near].index("c004")
    near[i4] = synth_pool({"c004": {50: (-3001.0, -1500.0)}}, ["c004"])[0]
    got_near = [g.entry for g in g2.select_goals(near, ref, row0, entries=entries, n_goals=7)["goals"]]
    check("c004" in got_near, "a non-identical definition was treated as a duplicate")
    # episodes in sha order; within an episode, the first eligible tau (sha order) that is not a duplicate
    check([g2.sha(f"m7u2|goal|{e}") for e in got] == sorted(g2.sha(f"m7u2|goal|{e}") for e in got), "episode order")
    pts = {e: {t: xy for t, xy in spec[e].items()} for e in spec}
    for i, g in enumerate(goals):
        order = sorted([t for t in pts[g.entry] if g2.TAU_MIN <= t <= g2.TAU_MAX],
                       key=lambda t: g2.sha(f"m7u2|goal|{g.entry}|{t}"))
        earlier = goals[:i]
        for t in order[:order.index(g.tau)]:
            check(any(pts[g.entry][t] == (e.x, e.y) for e in earlier), f"{g.entry}: tau {t} was passed over, no duplicate")
    # determinism: a permuted pool gives the identical registration
    sel2 = g2.select_goals(list(reversed(pool)), ref, row0, entries=entries, n_goals=6)
    check(g2.goals_digest(sel2["goals"]) == g2.goals_digest(goals), "selection depends on pool order")
    # insufficient supply: INCOMPLETE, no fill and no relaxation (the skipped duplicate is not used to make up the number)
    try:
        g2.select_goals(pool, ref, row0, entries=entries, n_goals=7)
        check(False, "too few goals were not refused")
    except g2.GoalError as exc:
        check(exc.incomplete and exc.record["registered"] == 6, "insufficient supply must be INCOMPLETE")
        check(exc.record["skipped_for_duplicate"] == [{"entry": "c004", "eligible_taus": 1}] and
              exc.record["overlap"]["n_pairs"] == 1, "the INCOMPLETE record keeps the duplicate skip and the overlaps")
    # the pool must be exactly the registered entries; words <= 128; the reset row must be the tick-0 record
    for bad, why in ((pool[:-1], "a missing pool episode"), (pool + [dict(pool[0], entry="c999")], "an extra episode")):
        try:
            g2.select_goals(bad, ref, row0, entries=entries, n_goals=3)
            check(False, f"{why} was accepted")
        except g2.GoalError as exc:
            check(not exc.incomplete, f"{why} must be an integrity refusal, not INCOMPLETE")
    long = [dict(p) for p in pool]
    long[1] = dict(long[1], rows=synth_rows({}, T=129), words=np.zeros((129, 2), np.int64))
    shifted = [dict(p) for p in pool]
    r = shifted[2]["rows"].copy()
    r[0, F["x"]] += 1.0
    shifted[2] = dict(shifted[2], rows=r)
    for bad, why in ((long, "129 words"), (shifted, "a reset row off the tick-0 record")):
        try:
            g2.select_goals(bad, ref, row0, entries=entries, n_goals=3)
            check(False, f"{why} was accepted")
        except g2.GoalError:
            pass
    params = list(inspect.signature(g2.select_goals).parameters)
    check(params == ["pool", "reference", "tick0_row", "entries", "n_goals"], f"selection inputs {params}")
    # production constants
    check(g2.POOL_ENTRIES == tuple(f"c{i:03d}" for i in range(360)) and g2.POOL_TICKS == 128, "pool registration")
    check((g2.TAU_MIN, g2.TAU_MAX, g2.BUDGET, g2.RISE, g2.BOX, g2.REF_MAX_REACHING, g2.N_GOALS) ==
          (32, 96, 128, 300.0, 150.0, 1, 24), "goal constants")
    return {"registered": [(g.entry, g.tau) for g in goals], "overlap_pairs": rec["overlap"]["n_pairs"],
            "passed_over_duplicates": rec["passed_over_duplicates"], "skipped": rec["skipped_for_duplicate"]}


def unit_goals_on_m7u1_data(out: Path) -> Dict[str, Any]:
    """The preserved m7u1 records: identical tick-0 rows, pinned reference, and the proposal's leave-one-out yield."""
    import m7u2_gate as gg

    src, row0, ref, _fz = m7u1()
    check(g2.row_digest(row0) == gg.PIN["tick0_row_digest"], "tick-0 row digest")
    check(ref.digest() == gg.PIN["reference_digest"] and ref.n == 92, "reference digest")
    spawn = float(row0[F["y"]])
    yielding = 0
    for eid, rows, _w, fell in src.episodes:
        rr = rows[:g2.POOL_TICKS + 1]
        ff = fell and len(rows) <= g2.POOL_TICKS + 1
        el = [t for t in g2.candidates(rr, ff, spawn)
              if ref.reaching(rr[t, F["x"]], rr[t, F["y"]], exclude=eid) <= g2.REF_MAX_REACHING]
        yielding += bool(el)
    check(yielding == 12, f"leave-one-out yield {yielding} != 12 (proposal §2)")
    return {"loo_yield": f"{yielding}/92", "tick0_row": g2.row_digest(row0)[:16], "reference": ref.digest()[:16]}


def unit_frozen_model_integrity(out: Path) -> Dict[str, Any]:
    import torch

    import m7u2_gate as gg
    import m7u_model as um

    src, _row0, _ref, fz = m7u1()
    check(all(not p.requires_grad for p in fz.model.parameters()) and not fz.model.training, "gradients or train mode")
    check(gg.parameter_digest(fz.model) == gg.PIN["parameter_digest"], "parameter digest")
    # a modified model file is refused
    m2, vocab, _ = um.load(gg.MODEL_PATH)
    with torch.no_grad():
        next(iter(m2.parameters())).view(-1)[0] += 1e-3
    bad = out / "model_tampered.pt"
    um.save(m2, vocab, bad)
    for path, pins, why in ((bad, gg.PIN, "a tampered file"),
                            (gg.MODEL_PATH, dict(gg.PIN, parameter_digest="0" * 64), "a wrong parameter pin"),
                            (gg.MODEL_PATH, dict(gg.PIN, track_sha256="0" * 64), "a wrong clock-track pin")):
        try:
            gg.load_frozen(src, path, pins=pins)
            check(False, f"{why} was accepted")
        except gg.IntegrityStop:
            pass
    # no optimizer can be constructed while the guard is active; the guard is removed afterwards
    with gg.no_optimizer():
        try:
            torch.optim.Adam([torch.zeros(1, requires_grad=True)])
            check(False, "an optimizer was constructed under the guard")
        except gg.IntegrityStop:
            pass
    torch.optim.SGD([torch.zeros(1, requires_grad=True)], lr=0.1)
    # forward passes leave the parameters unchanged; the recorded m7u1 decisions reproduce
    before = gg.parameter_digest(fz.model)
    rep = gg.reproduce_decisions(fz, src)
    check(rep["ok"] and rep["chosen_equal"] == 32, f"decision reproduction {rep}")
    check(gg.parameter_digest(fz.model) == before, "parameters changed by forward passes")
    # the gate's own code builds no optimizer and runs no training
    text = (REPO_ROOT / "rl" / "m7u2_gate.py").read_text(encoding="utf-8")
    for bad_call in ("um.train(", ".backward(", "um.losses(", "optim.Adam", "optim.SGD", ".step()"):
        check(bad_call not in text, f"m7u2_gate.py contains {bad_call!r}")
    return {"repro": rep, "parameter_digest": before[:16]}


def unit_readiness(out: Path) -> Dict[str, Any]:
    import m7u2_gate as gg

    good_mem = lambda: {"available_mb": 8000.0, "commit_free_mb": 16000.0}  # noqa: E731
    fast = lambda: {"n": 40, "median_s": 0.3, "p95_s": 0.31}  # noqa: E731
    check(gg.readiness(fast, good_mem)["ok"], "a ready machine was refused")
    for probe, mem, why in ((lambda: {"n": 40, "median_s": 0.5, "p95_s": 0.51}, good_mem, "slow planning"),
                            (fast, lambda: {"available_mb": 3000.0, "commit_free_mb": 16000.0}, "low memory"),
                            (fast, lambda: {"available_mb": 8000.0, "commit_free_mb": 9000.0}, "low commit"),
                            (fast, lambda: None, "unknown memory")):
        r = gg.readiness(probe, mem)
        check(not r["ok"] and r["problems"], f"{why} was not refused")
    _src, row0, _ref, fz = m7u1()
    t = gg.timing_probe(fz, row0, n=3, warmup=1)
    check(0 < t["median_s"] < 10 and t["n"] == 3, f"timing probe {t}")
    return {"probe": t}


def _three_goals(out: Path) -> Tuple[List[g2.Goal], np.ndarray, List[Dict[str, Any]]]:
    """Three goals from synthetic behaviour episodes of the same synthetic reset (their witnesses reproduce them)."""
    eps = fake_episodes(out / "src", ["s0", "s1", "s2", "s3"], n_workers=2)
    row0 = eps[0]["rows"][0]
    goals = []
    for e in eps:
        r = e["rows"]
        air = [t for t in range(g2.TAU_MIN, min(g2.TAU_MAX, len(r) - 1) + 1) if r[t, F["ga"]] == 1]
        if air and len(goals) < 3:
            t = air[0]
            goals.append(g2.Goal(k=len(goals), entry=e["entry"], episode_id=str(e["episode_id"]), tau=t,
                                 x=float(r[t, F["x"]]), y=float(r[t, F["y"]]), rise=float(r[t, F["y"]] - row0[F["y"]]),
                                 ref_reaching=0, witness=[tuple(int(v) for v in w) for w in e["words"][:t]]))
    check(len(goals) == 3, "synthetic goal construction")
    return goals, row0, eps


def unit_tick0_drive(out: Path) -> Dict[str, Any]:
    """Evaluation from the normal tick-0 reset: no prefix, the reset row checked before the first word, k = words."""
    import m7u_gate as g1
    import m7u2_gate as gg

    goals, row0, eps = _three_goals(out)
    fz = fake_frozen(out)
    cfg = gg.evaluation_configs(goals, 3, row0)
    L = ledger(eval_control=3 * 3 * g2.BUDGET)
    trials = gg.drive(fake_vec(out / "eval", 3, horizon=3600), cfg, phase="evaluation", ledger=L,
                      clock=g1.Clock(memory=lambda: None), n_candidates=17, row0=row0, goals=goals, model=fz.model,
                      ctx=fz.ctx, track=fz.track)
    check(len(trials) == 9 and L.used["eval_control"] == sum(len(r["words"]) for r in trials), "ledger = words")
    for r in trials:
        check(np.array_equal(r["rows"][0], row0, equal_nan=True), f"{r['entry']}: start row")
        check(all(int(r["rows"][i, F["input_tick"]]) == i for i in range(len(r["rows"]))), "input_tick = words submitted")
        check(1 <= len(r["words"]) <= g2.BUDGET, f"{r['entry']}: {len(r['words'])} words")
        if r["arm"] == "RC":
            regen = up.rc_words(gg.stream_key("goal", r["goal_k"]), 17, len(r["words"]))
            check([tuple(w) for w in r["words"]] == regen, f"{r['entry']}: RC from tick 0 is not candidate 0")
        check(r["decisions"][0] == 0, f"{r['entry']}: the first decision is not at consumed tick 0")
    # a reset row off the tick-0 record stops the run before any word is sent
    bad_row = row0.copy()
    bad_row[F["x"]] += 1.0
    L2 = ledger(eval_control=10 ** 6)
    try:
        gg.drive(fake_vec(out / "eval_bad", 1, horizon=3600), gg.evaluation_configs(goals[:1], 1, bad_row),
                 phase="evaluation", ledger=L2, clock=g1.Clock(memory=lambda: None), n_candidates=17, row0=bad_row,
                 goals=goals, model=fz.model, ctx=fz.ctx, track=fz.track)
        check(False, "a reset row off the record was accepted")
    except gg.IntegrityStop:
        check(L2.used["eval_control"] == 0, "ticks were consumed before the start check")
    # prefixes and archived starts are refused before anything is launched
    for mutate, why in ((lambda e: e.update(t=95), "a prefix length"), (lambda e: e.update(prefix=[[0, 0]]), "a prefix"),
                        (lambda e: e.update(expected_start_row=[0.0] * us.N_FIELDS), "an archived start row"),
                        (lambda e: e.update(budget=200), "a longer budget"),
                        (lambda e: e.update(goal=[0.0, 0.0]), "a scored goal other than g")):
        c = gg.evaluation_configs(goals, 1, row0)
        mutate(c[0]["entries"][0])
        try:
            gg.validate_entries(c, "evaluation", goals, row0)
            check(False, f"{why} was accepted")
        except ValueError:
            pass
    return {"trials": len(trials), "ticks": L.used["eval_control"],
            "reached": sum(r["reach_tick"] is not None for r in trials)}


def unit_scrambled_scoring(out: Path) -> Dict[str, Any]:
    """S is commanded pi(g) but scored on g: reaching pi(g) never ends or counts an S trial."""
    import m7u_gate as g1
    import m7u2_gate as gg

    goals, row0, eps = _three_goals(out)
    for k in range(3):
        e = {"kind": "trial", "arm": "S", "goal_k": k, "budget": g2.BUDGET}
        c = gg.controller_for(e, 17, goals)
        p = gg.controller_for(dict(e, arm="P"), 17, goals)
        pk = g2.scrambled(k, 3)
        check(c.goal == (goals[pk].x, goals[pk].y) and p.goal == (goals[k].x, goals[k].y) and pk != k, "commanded goals")
        check(c.stream_key == p.stream_key == gg.stream_key("goal", k), "P and S share the goal's stream")
    # Deterministic scoring check through the REAL probe: the same words pass through the commanded partner's box
    # (they are its witness). Scored on a far goal they end only at the budget; scored on the partner they end at
    # the first reach.
    near = goals[1]
    far = g2.Goal(k=0, entry="far", episode_id="far", tau=50, x=50000.0, y=50000.0, rise=0.0, ref_reaching=0)
    start = [None if np.isnan(v) else float(v) for v in row0]
    words = [list(w) for w in near.witness] + [[0, 0]] * 5
    base = {"kind": "trial", "t": 0, "prefix": [], "expected_start_row": start, "budget": len(words), "words": words}
    led = ledger(replays=10 ** 6)
    s_far = g1.run_single(fake_single(out / "far", 3600), [dict(base, entry="S_far", goal=[far.x, far.y])],
                          phase="replays", ledger=led, clock=g1.Clock(memory=lambda: None))[0]
    s_near = g1.run_single(fake_single(out / "near", 3600), [dict(base, entry="S_near", goal=[near.x, near.y])],
                           phase="replays", ledger=led, clock=g1.Clock(memory=lambda: None))[0]
    in_box = [i for i, r in enumerate(s_far["rows"]) if i > 0 and r[F["ga"]] == 1 and abs(r[F["x"]] - near.x) <= g2.BOX
              and abs(r[F["y"]] - near.y) <= g2.BOX]
    check(in_box and in_box[0] <= near.tau, "the witness does not pass through the partner's box")
    check(s_far["reach_tick"] is None and s_far["truncation_reason"] == "trial_budget" and s_far["sent"] == len(words),
          "a trial ended or counted at a box other than its scored goal")
    check(s_near["reach_tick"] == in_box[0] and s_near["truncation_reason"] == "goal_reached",
          "the scored goal's first reach did not end the trial")
    return {"partner_box_entered_at": in_box[0], "scored_far_reach": s_far["reach_tick"],
            "scored_partner_reach": s_near["reach_tick"]}


def unit_pool_and_caps(out: Path) -> Dict[str, Any]:
    import m7u_gate as g1
    import m7u2_gate as gg

    cfg = gg.pool_configs(5)
    names = [e["entry"] for c in cfg.values() for e in c["entries"]]
    check(sorted(names) == list(g2.POOL_ENTRIES) and all(len(c["entries"]) == 72 for c in cfg.values()),
          "production pool configuration")
    eps = fake_episodes(out / "pool", [f"c{i:03d}" for i in range(6)], n_workers=3)
    for e in eps:
        check(len(e["words"]) <= g2.POOL_TICKS, f"{e['entry']}: {len(e['words'])} words")
        check([tuple(w) for w in e["words"]] == up.rc_words(gg.stream_key("collect", e["entry"]), 17, len(e["words"])),
              f"{e['entry']}: not the behaviour stream")
    # a pool cap one tick short stops before the request that would exceed it
    row0 = eps[0]["rows"][0]
    L = ledger(pool=6 * g2.POOL_TICKS - 1)
    try:
        gg.drive(fake_vec(out / "pool2", 3, horizon=g2.POOL_TICKS), gg.pool_configs(3, [f"c{i:03d}" for i in range(6)]),
                 phase="pool", ledger=L, clock=g1.Clock(memory=lambda: None), n_candidates=17, row0=row0)
        check(False, "the pool cap was not enforced")
    except g1.CapStop:
        check(L.used["pool"] <= 6 * g2.POOL_TICKS - 1, "ledger exceeded before the stop")
    # wall and memory caps
    ticks = iter(range(10 ** 6))
    clk = g1.Clock(now=lambda: float(next(ticks)), caps={"pool": 5}, global_cap=10 ** 6, memory=lambda: None)
    clk.begin("pool")
    try:
        for _ in range(10):
            clk.check()
        check(False, "the wall cap was not enforced")
    except g1.CapStop:
        pass
    clk2 = g1.Clock(caps={"pool": 600}, memory=lambda: 4000.0, memory_cap_mb=gg.MEMORY_CAP_MB)
    try:
        clk2.begin("pool")
        check(False, "the memory cap was not enforced")
    except g1.CapStop:
        pass
    return {"episodes": len(eps), "words": [len(e["words"]) for e in eps]}


def unit_replay_accounting(out: Path) -> Dict[str, Any]:
    import m7u2_gate as gg

    outcomes = {"P": [k < 10 for k in range(24)], "RC": [k == 5 for k in range(24)],
                "S": [k in (3, 7, 9) for k in range(24)]}
    sel = gg.replay_selection(outcomes)
    check(sel == [("P", k) for k in range(6)] + [("RC", 5)] + [("S", 3), ("S", 7)], f"replay selection {sel}")
    check(len(sel) * g2.BUDGET <= gg.TICK_BUDGET["replays"] == 1280, "replay budget")
    rows = np.zeros((5, us.N_FIELDS))
    exp = {"rows": rows, "reach_tick": 4, "native_action_digest": "d"}
    good = {"sent": 4, "rows": rows.copy(), "reach_tick": 4, "native_action_digest": "d"}
    check(gg.check_replay(good, exp, [[0, 0]] * 4)["ok"], "an exact replay was rejected")
    r2_ = rows.copy()
    r2_[3, F["y"]] = 1.0
    for bad, why in ((dict(good, rows=r2_), "a differing row"), (dict(good, reach_tick=3), "a differing reach tick"),
                     (dict(good, native_action_digest="e"), "a differing action digest"),
                     (dict(good, sent=3), "a short replay")):
        check(not gg.check_replay(bad, exp, [[0, 0]] * 4)["ok"], f"{why} was accepted")
    return {"selection": sel}


def unit_gate_stops(out: Path) -> Dict[str, Any]:
    """run_gate: a P1 mismatch is INVALID before the pool; too few goals is INCOMPLETE with exactly the pool consumed
    and nothing extended; a pool wall cap is INCOMPLETE."""
    import m7u_gate as g1
    import m7u2_gate as gg

    src, _row0, _ref, _fz = m7u1()
    ref_eps = fake_episodes(out / "ref", [f"r{i:03d}" for i in range(10)], n_workers=5)
    row0 = ref_eps[0]["rows"][0]
    ref = g2.Reference([(e["entry"], e["rows"], e["termination_reason"] == "native_failure") for e in ref_eps])
    fz = fake_frozen(out)
    words = {}

    def venv_factory(root, run_id, role, settings):
        return fake_vec(Path(root), 5, horizon=settings)

    def env_factory(root, run_id, role, settings):
        return fake_single(Path(root), horizon=3600)

    p1 = _fake_p1(out / "p1src", 40)
    bad_p1 = [dict(p1[0], expected=dict(p1[0]["expected"], reach_tick=7))]
    small = [f"c{i:03d}" for i in range(10)]
    common = dict(settings=3600, pool_settings=g2.POOL_TICKS, src=src, frozen=fz, n_candidates=17, ref=ref, row0=row0,
                  artifact_words=lambda d: words[d], n_workers=5)
    st = gg.run_gate(root=out / "g1", venv_factory=venv_factory, env_factory=env_factory,
                     clock=g1.Clock(caps=gg.WALL_CAPS_S, memory=lambda: None), p1_entries=bad_p1,
                     ledger=g1.Ledger(dict(gg.TICK_BUDGET, p1=40)), pool_entries=small, **common)
    check(st["decision"]["outcome"] == "INVALID" and st["ledger"]["used"]["pool"] == 0, "P1 mismatch")
    st2 = gg.run_gate(root=out / "g2", venv_factory=venv_factory, env_factory=env_factory,
                      clock=g1.Clock(caps=gg.WALL_CAPS_S, memory=lambda: None), p1_entries=p1,
                      ledger=g1.Ledger(dict(gg.TICK_BUDGET, p1=40)), pool_entries=small, **common)
    used = st2["ledger"]["used"]
    check(st2["decision"]["outcome"] == "INCOMPLETE" and "goal availability" in st2["decision"]["reason"],
          f"insufficient goals: {st2['decision']}")
    check(used["pool"] <= len(small) * g2.POOL_TICKS and used["eval_control"] == 0 and used["replays"] == 0,
          f"ticks after an availability stop: {used}")
    check(st2["phases"]["pool"]["episodes"] == len(small), "the pool was extended or shortened")
    ticks = iter(range(10 ** 7))
    st3 = gg.run_gate(root=out / "g3", venv_factory=venv_factory, env_factory=env_factory,
                      clock=g1.Clock(now=lambda: float(next(ticks)) * 0.01, caps=dict(gg.WALL_CAPS_S, pool=2),
                                     memory=lambda: None), p1_entries=p1,
                      ledger=g1.Ledger(dict(gg.TICK_BUDGET, p1=40)), pool_entries=small, **common)
    check(st3["decision"]["outcome"] == "INCOMPLETE" and "wall cap" in st3["decision"]["reason"],
          f"wall cap {st3['decision']}")
    return {"p1_mismatch": st["decision"]["outcome"], "availability": st2["decision"]["reason"][:80],
            "wall": st3["decision"]["reason"][:60]}


def _fake_p1(root: Path, n_words: int) -> List[Dict[str, Any]]:
    """A synthetic P1 entry: a budgeted tick-0 trial with an unreachable goal, its expected rows from one prior run."""
    import m7u_gate as g1

    single = fake_single(root, horizon=3600)
    words = [list(w) for w in up.rc_words("m7u2|test|p1", 17, n_words)]
    row0 = fake_row0(root)
    start = [None if np.isnan(v) else float(v) for v in row0]
    e = {"entry": "p1_fake", "kind": "trial", "t": 0, "budget": n_words, "goal": [1e9, 1e9], "prefix": [],
         "expected_start_row": start, "words": words}
    rr = g1.run_single(single, [e], phase="p1", ledger=ledger(p1=n_words),
                       clock=g1.Clock(memory=lambda: None))[0]
    return [dict(e, expected={"rows": rr["rows"], "reach_tick": rr["reach_tick"],
                              "native_action_digest": rr["native_action_digest"]})]


def unit_approval_refusal_and_acceptance(out: Path) -> Dict[str, Any]:
    """The production approval_status() on an ISOLATED temporary record (a short system temp path, removed afterwards);
    the repository's record is never touched."""
    import m7u2_gate as gg

    with tempfile.TemporaryDirectory(prefix="m7u2a_") as d:
        return _approval_cases(gg, Path(d))


def _approval_cases(gg: Any, root: Path) -> Dict[str, Any]:
    real, real_root = gg.APPROVAL, gg.REPO_ROOT
    real_before = hashlib.sha256(real.read_bytes()).hexdigest() if real.is_file() else None
    tmp = root / "docs" / real.name
    tmp.parent.mkdir(parents=True)
    ident = gg.identity()
    res: Dict[str, Any] = {}

    def status(rec: Optional[Mapping[str, Any]]):
        if rec is not None:
            tmp.write_text(json.dumps(rec, default=str), encoding="utf-8")
        return gg.approval_status()

    gg.APPROVAL, gg.REPO_ROOT = tmp, root
    try:
        ok, why = status(None)
        check(not ok and "no approval record" in why, f"missing: {why}")
        res["missing"] = why
        ok, why = status(dict(ident, approval="PENDING"))
        check(not ok, "PENDING accepted")
        res["pending"] = why
        altered = {"tick_budget": dict(ident["tick_budget"], total=56_931), "n_candidates": 32,
                   "frozen_model": dict(ident["frozen_model"], parameter_digest="0" * 64),
                   "global_cap_s": 3600, "memory_cap_mb": 4096, "rule_sha256": "0" * 64, "pool": [400, 128],
                   "code": dict(ident["code"], **{"rl/m7u_planner.py": "0" * 64})}
        for key, value in altered.items():
            ok, why = status(dict(ident, approval="APPROVED test", **{key: value}))
            check(not ok and ("code:" if key == "code" else key) in why, f"altered {key} accepted: {why}")
            res[f"altered_{key}"] = why
        tmp.write_text("{not json", encoding="utf-8")
        try:
            gg.approval_status()
            check(False, "an unreadable record was accepted")
        except ValueError as exc:
            res["unreadable"] = type(exc).__name__
        ok, why = status(dict(ident, approval="APPROVED test"))
        check(ok and why == "approved", f"valid record refused: {why}")
        res["valid"] = why
    finally:
        gg.APPROVAL, gg.REPO_ROOT = real, real_root
    real_after = hashlib.sha256(real.read_bytes()).hexdigest() if real.is_file() else None
    check(real_after == real_before and gg.APPROVAL == real, "the repository approval path was touched")
    res["repository_record_present"] = real_before is not None
    return res


def unit_accounting(out: Path) -> Dict[str, Any]:
    import m7u2_gate as gg

    b = gg.TICK_BUDGET
    check(b == {"p1": 354, "pool": 46_080, "eval_control": 9_216, "replays": 1_280, "total": 56_930}, f"ledger {b}")
    check(b["p1"] == sum(v["words"] for v in gg.PIN["p1"].values()) == 171 + 183, "P1 = the two pinned artifacts")
    check(gg.GLOBAL_CAP_S == 2400 and gg.MEMORY_CAP_MB == 3072 and sum(gg.WALL_CAPS_S.values()) <= gg.GLOBAL_CAP_S,
          "caps")
    check(gg.REPLAYS == {"P": 6, "RC": 2, "S": 2} and gg.N_CANDIDATES == 64, "replays and candidates")
    check(gg.READINESS["probe_p95_max_s"] == 0.5 and gg.READINESS["min_available_mb"] == 4096, "readiness")
    # projection from m7u1's measured rates: about 560 native ticks/s over 5 workers with the m7u wrappers, about 3 s per
    # restart, 1,536 planning decisions at the readiness ceiling p95 0.5 s
    proj = {"p1": 354 / 112 + 2 * 3, "pool": 46_080 / 560 + 360 / 5 * 3, "goals": 30,
            "evaluation": 9_216 / 560 + 72 / 5 * 3 + 30 + 1_536 * gg.READINESS["probe_p95_max_s"],
            "replays_analysis": 10 * (128 / 112 + 3) + 120}
    for k, v in proj.items():
        check(v <= gg.WALL_CAPS_S[k], f"projection {k} {v:.0f} s > cap {gg.WALL_CAPS_S[k]} s")
    return {"tick_budget": b, "projection_s": {k: round(v) for k, v in proj.items()},
            "projection_total_s": round(sum(proj.values()))}


def unit_import_isolation(out: Path) -> Dict[str, Any]:
    code = ("import sys; sys.path.insert(0, 'rl'); import m7u2_goals, m7u2_rule; "
            "bad = [m for m in ('torch', 'battleship_client', 'battleship_env', 'btt_parallel', 'm7u_worker') "
            "if m in sys.modules]; "
            "print(bad)")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO_ROOT)
    check(r.returncode == 0 and r.stdout.strip() == "[]", f"goal / rule modules import {r.stdout.strip()} {r.stderr[-200:]}")
    # m7u1 files are reused unchanged: their committed identity
    r2_ = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "rl/m7u_state.py", "rl/m7u_model.py", "rl/m7u_planner.py",
                          "rl/m7u_goals.py", "rl/m7u_rule.py", "rl/m7u_analysis.py", "rl/m7u_worker.py", "rl/m7u_gate.py",
                          "rl/m7u_tests.py"], cwd=REPO_ROOT)
    check(r2_.returncode == 0, "an m7u1 file differs from HEAD")
    return {"isolated": True, "m7u1_files_unchanged": True}


UNITS: Dict[str, Callable[[Path], Dict[str, Any]]] = {
    "unit_rule_and_scramble": unit_rule_and_scramble,
    "unit_goal_selection_rules": unit_goal_selection_rules,
    "unit_goals_on_m7u1_data": unit_goals_on_m7u1_data,
    "unit_frozen_model_integrity": unit_frozen_model_integrity,
    "unit_readiness": unit_readiness,
    "unit_tick0_drive": unit_tick0_drive,
    "unit_scrambled_scoring": unit_scrambled_scoring,
    "unit_pool_and_caps": unit_pool_and_caps,
    "unit_replay_accounting": unit_replay_accounting,
    "unit_gate_stops": unit_gate_stops,
    "unit_approval_refusal_and_acceptance": unit_approval_refusal_and_acceptance,
    "unit_accounting": unit_accounting,
    "unit_import_isolation": unit_import_isolation,
}


def e2e(out: Path) -> Dict[str, Any]:
    """run_gate through EVERY phase at production counts over the synthetic stand-in: 360 pool episodes x <= 128 words,
    a synthetic 92-episode chance reference, 24 goals x 3 arms from the normal reset, replays, rule. N = 17 candidates
    for speed; the REAL frozen ensemble plans (its clock track rebuilt from synthetic episodes). Exercises the glue only;
    its outcome says nothing about Mario."""
    import m7u_gate as g1
    import m7u2_gate as gg

    src, _row0, _ref, _fz = m7u1()
    ref_eps = fake_episodes(out / "ref", [f"r{i:03d}" for i in range(g2.REF_EPISODES)], n_workers=5)
    row0 = ref_eps[0]["rows"][0]
    ref = g2.Reference([(e["entry"], e["rows"], e["termination_reason"] == "native_failure") for e in ref_eps])
    fz = fake_frozen(out)
    vecs: List[Any] = []
    singles: List[Any] = []

    def venv_factory(root, run_id, role, settings):
        v = fake_vec(Path(root), 5, horizon=settings)
        vecs.append(v)
        return v

    def env_factory(root, run_id, role, settings):
        s = fake_single(Path(root), horizon=3600)
        singles.append(s)
        return s

    def artifact_words(d):
        for st in [t for v in vecs for _tw, t in v.stacks] + [s.tracker for s in singles]:
            eid = Path(d).name
            if eid in st.words and str(st.artifact_root / eid) == str(d):
                return [tuple(w) for w in st.words[eid]]
        raise KeyError(d)

    p1 = _fake_p1(out / "p1src", 171) + [dict(_fake_p1(out / "p1src2", 183)[0], entry="p1_fake2")]
    t0 = time.perf_counter()
    with gg.no_optimizer():
        st = gg.run_gate(settings=3600, pool_settings=g2.POOL_TICKS, root=out / "gate", venv_factory=venv_factory,
                         env_factory=env_factory, clock=g1.Clock(caps=gg.WALL_CAPS_S, global_cap=gg.GLOBAL_CAP_S,
                                                                 memory=lambda: None),
                         src=src, frozen=fz, n_candidates=17, p1_entries=p1, artifact_words=artifact_words, ref=ref,
                         row0=row0)
    d = st["decision"]
    check(d["outcome"] in ("PASS", "NULL", "INCONCLUSIVE"), f"e2e decision {d.get('outcome')}: {d.get('reason')} "
          f"{st['integrity']['problems'][:3]}")
    used = st["ledger"]["used"]
    check(st["ledger"]["total"] <= gg.TICK_BUDGET["total"] and used["p1"] == 354, f"ledger {used}")
    check(used["replays"] == sum(r["sent"] for r in st["phases"]["replays"]) <= 1280, "replay accounting")
    check(all(r["ok"] for r in st["phases"]["replays"]), "a replay was not exact")
    check(st["phases"]["pool"]["episodes"] == 360 and st["phases"]["goals"]["registered"] == 24, "pool / goals")
    check(not r2.scope_problems(d["summary"]), "summary wording")
    check(gg.parameter_digest(fz.model) == gg.PIN["parameter_digest"], "the frozen model changed")
    gd = out / "gate" / "_gate"
    goals = json.loads((gd / "goals.json").read_text(encoding="utf-8"))
    check(len(goals["goals"]) == 24 and len({g["entry"] for g in goals["goals"]}) == 24, "goal definitions")
    trial_files = sorted((gd / "trials").glob("*.npz"))
    check(len(trial_files) == 72, f"{len(trial_files)} trial evidence files")
    for f in trial_files:
        with np.load(f) as z:
            meta = json.loads(z["meta"].tobytes().decode("utf-8"))
            check(meta["t"] == 0 and np.array_equal(z["rows"][0], row0, equal_nan=True), f"{f.name}: not a tick-0 start")
            check(("scores" in z.files) == meta["model_evaluated"], f"{f.name}: predictions")
    return {"decision": {k: d.get(k) for k in ("outcome", "n", "vs_RC", "vs_S", "null_reading")}, "ledger": used,
            "phase_wall_s": st["clock"]["phase_wall_s"], "replays": len(st["phases"]["replays"]),
            "goal_record": {"eligible_points": st["phases"]["goals"]["eligible_points"],
                            "episodes_with_a_goal": st["phases"]["goals"]["episodes_with_a_goal"],
                            "passed_over_duplicates": len(st["phases"]["goals"]["passed_over_duplicates"]),
                            "skipped_for_duplicate": len(st["phases"]["goals"]["skipped_for_duplicate"]),
                            "overlap_pairs": st["phases"]["goals"]["overlap"]["n_pairs"],
                            "correlated_groups": st["phases"]["goals"]["overlap"]["correlated_groups"],
                            "registered": st["phases"]["goals"]["registered"]},
            "wall_s": round(time.perf_counter() - t0, 1)}


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["unit", "e2e"])
    ap.add_argument("--out", default=None)
    ap.add_argument("--only", default=None)
    a = ap.parse_args(argv)
    base = Path(a.out) if a.out else Path(tempfile.mkdtemp(prefix="m7u2_tests_"))
    if (REPO_ROOT / "runs") in base.resolve().parents:
        print("refused: test outputs never go under runs/")
        return 2
    base.mkdir(parents=True, exist_ok=True)
    if a.mode == "e2e":
        try:
            r = {"ok": True, **e2e(base)}
        except Exception as exc:  # noqa: BLE001
            r = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-3000:]}
        (base / "m7u2_e2e.json").write_text(json.dumps(r, indent=1, default=str) + "\n", encoding="utf-8")
        print(json.dumps({k: v for k, v in r.items() if k != "trace"}, default=str)[:2500])
        if not r["ok"]:
            print(r["trace"])
        return 0 if r["ok"] else 1
    results, failed = {}, []
    for name, fn in UNITS.items():
        if a.only and a.only not in name:
            continue
        d = base / name
        d.mkdir(parents=True, exist_ok=True)
        t0 = time.perf_counter()
        try:
            results[name] = {"ok": True, **fn(d), "s": round(time.perf_counter() - t0, 1)}
        except Exception as exc:  # noqa: BLE001 - reported per case
            failed.append(name)
            results[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-1500:],
                             "s": round(time.perf_counter() - t0, 1)}
    (base / "m7u2_unit.json").write_text(json.dumps(results, indent=1, default=str) + "\n", encoding="utf-8")
    for name, r in results.items():
        print(f"{'ok  ' if r['ok'] else 'FAIL'} {name} ({r['s']} s)" + ("" if r["ok"] else f": {r['error']}"))
    print(f"m7u2 unit: {len(results) - len(failed)}/{len(results)} passed; report {base / 'm7u2_unit.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
