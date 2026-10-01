#!/usr/bin/env python3
"""M7u3 (proposed gate m7u3) offline tests: zero native ticks. No BattleShip launch, no replay, no native process.
Optimizers exist only on synthetic data (the refit pipeline's own unit cases) and never touch the frozen model,
P_retrain or any recorded-data fit.

    python rl/m7u3_tests.py unit [--out DIR] [--only NAME]
    python rl/m7u3_tests.py e2e  [--out DIR]

The synthetic native stand-in is m7u1's / M7u2's (rl/m7u_tests.py, rl/m7u2_tests.py: copies of captured replies with
synthetic values, driven through the REAL m7u probe and trial wrappers). The frozen m7u1 model, P_retrain and the
preserved runs/m7u and runs/m7u2 records are read only. Approval is tested against isolated temporary records, so the
suite stays valid after a real approval record exists.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
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
import m7u2_tests as t2  # noqa: E402
import m7u3_goals as g3  # noqa: E402
import m7u3_rule as r3  # noqa: E402
import m7u_planner as up  # noqa: E402
import m7u_state as us  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
F = us.F
check = t2.check
Failure = t2.Failure
_CACHE: Dict[str, Any] = {}


# -- shared fixtures ---------------------------------------------------------------------------------------------------


def m7u1():
    """(sources, tick-0 row, reference, frozen model) loaded once and checked against every pin."""
    return t2.m7u1()


def retrain_real():
    import m7u3_gate as gate

    if "retrain" not in _CACHE:
        _src, _row0, _ref, fz = m7u1()
        _CACHE["retrain"] = gate.load_retrain(fz)
    return _CACHE["retrain"]


def ledger(**caps: int):
    import m7u_gate as g1

    d = {"p1": 0, "train_pool": 0, "goal_pool": 0, "eval_control": 0, "replays": 0}
    d.update(caps)
    d["total"] = sum(d.values())
    return g1.Ledger(d)


def _stack(root: Path, rank: int, horizon: int):
    """t2._stack with a tracker whose episode ids are unique across phases (the stub's are only unique per worker)."""
    import gymnasium as gym

    import m7u_tests as mt
    import m7u_worker as uw

    class Tracker(mt._TrackerStub):
        def end(self, info, words):                                         # noqa: ANN001
            self.n += 1
            eid = f"{self.artifact_root.parent.name}_{self.artifact_root.name}_{self.n:04d}"
            (self.artifact_root / eid).mkdir(parents=True, exist_ok=True)
            self.words[eid] = list(words)
            self._pending = {"episode_id": eid, "artifact_dir": str(self.artifact_root / eid), "preserved": True,
                             "native_action_digest": hashlib.sha256(json.dumps(words).encode()).hexdigest(),
                             "startup_mode": "cold_start", "cleared": False, "end_reason": "horizon"}

    native = t2._air_native_class()(horizon, t2._template())
    probe = uw.M7uProbeWrapper(native, base=native)
    tracker = Tracker(root / f"w{rank}")

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
        def __init__(self) -> None:
            self.stacks = [_stack(Path(root), r, horizon) for r in range(n)]
            self.num_envs, self.ranks, self.closed = n, list(range(n)), False
            self.reset_infos = [{} for _ in range(n)]

    return Vec()


def fake_single(root: Path, horizon: int):
    import m7u_tests as mt

    class Single(mt._FakeSingle):
        def __init__(self) -> None:
            self.trial, self.tracker = _stack(Path(root), 0, horizon)

    return Single()


def fake_row0(root: Path) -> np.ndarray:
    v = fake_vec(Path(root) / "_row0", 1, horizon=4)
    v.env_method_each("m7u_configure", {0: (({"mode": "collect", "phase": "pool",
                                                "entries": [{"entry": "x", "kind": "collect"}]},), {})})
    v.reset()
    return np.array(v.reset_infos[0]["m7u"]["row"], dtype=np.float64)


def fake_episodes(root: Path, names: Sequence[str], n_workers: int = 5, horizon: int = 128, n_candidates: int = 17,
                  prefix: str = "x") -> List[Dict[str, Any]]:
    """Behaviour episodes of the synthetic world from the normal reset, through the m7u3 drive loop (phase 'goal_pool')."""
    import m7u3_gate as gate
    import m7u_gate as g1

    vec = fake_vec(Path(root), n_workers, horizon=horizon)
    row0 = fake_row0(Path(root))
    led = ledger(goal_pool=10 ** 8)
    return gate.drive(vec, gate.pool_configs(n_workers, names), phase="goal_pool", ledger=led,
                      clock=g1.Clock(memory=lambda: None), n_candidates=n_candidates, row0=row0)


def fake_frozen(root: Path):
    """The REAL frozen m7u1 ensemble with a context whose clock track is rebuilt from synthetic episodes (the synthetic
    world has its own platform clock; imagination reaches input tick 128 + 64). Test-only."""
    import m7u2_gate as gg
    import m7u_model as um

    _src, _row0, _ref, fz = m7u1()
    eps = fake_episodes(Path(root) / "track", ["t0", "t1"], n_workers=2, horizon=300)
    track, probs = us.build_clock_track([e["rows"] for e in eps])
    check(not probs, f"synthetic clock track: {probs[:2]}")
    return gg.Frozen(model=fz.model, vocab=fz.vocab, ctx=um.make_context(fz.vocab, us.static_world_pinned(), track),
                     track=track)


def fake_retrain(root: Path, fz):
    import m7u2_gate as gg
    import m7u_model as um

    rt = retrain_real()
    return gg.Frozen(model=rt.model, vocab=rt.vocab, ctx=um.make_context(rt.vocab, us.static_world_pinned(), fz.track),
                     track=fz.track)


def fake_src(root: Path):
    """A synthetic stand-in for m7u1's sources: 80 training + 12 held-out episodes of the synthetic world, 260 ticks each
    (long enough that imagination from tick 128 reaches input tick 192)."""
    import m7u2_gate as gg

    if "src" in _CACHE:
        return _CACHE["src"]
    names = [f"b{i:03d}" for i in range(92)]
    eps = fake_episodes(Path(root) / "srcw", names, n_workers=5, horizon=260)
    eps = sorted(eps, key=lambda e: e["entry"])
    rows = [(str(e["episode_id"]), e["rows"], np.asarray(e["words"], dtype=np.int64), e["termination_reason"] == "native_failure")
            for e in eps]
    train_ids = [r[0] for r in rows[:80]]
    _CACHE["src"] = gg.M7u1Sources(episodes=rows, train_ids=train_ids, goals=[], trials={})
    return _CACHE["src"]


def synth_pool(spec: Mapping[str, Mapping[int, Tuple[float, float]]], entries: Sequence[str]) -> List[Dict[str, Any]]:
    return t2.synth_pool(spec, entries)


# -- unit cases --------------------------------------------------------------------------------------------------------


def unit_rule(out: Path) -> Dict[str, Any]:
    check(r3.self_test() == [], f"rule self-test: {r3.self_test()[:3]}")
    check((r3.N, r3.NULL_MAX_BF, r3.ARMS) == (24, 1, ("PF", "PR", "RC", "SR")), "registered constants")
    # the proposal's section 5 table: smallest passing results
    for d, (b, c, p) in r3.MIN_PASSING.items():
        check(r3.significant(b, c) and not r3.significant(b - 1, c + 1) and abs(r3.p_exact(b, c) - p) < 6e-4,
              f"min passing d={d}: ({b}, {c})")
    # PASS needs all three tests; each one failing alone blocks it
    n = 24

    def outcome(pr, pf, rc, sr):
        return r3.apply({"PR": pr, "PF": pf, "RC": rc, "SR": sr}, integrity_ok=True)

    z = [False] * n
    pr = [i < 8 for i in range(n)]
    check(outcome(pr, z, z, z)["outcome"] == "PASS", "8 / 0 / 0 / 0 must PASS")
    check(outcome(pr, pr, z, z)["outcome"] == "NULL", "PR equal to PF is NULL")
    rc_hit = [i < 4 for i in range(n)]                       # RC gets half of PR's goals: b_RC = 4, c = 0 -> p 0.0625
    out_rc = outcome(pr, z, rc_hit, z)
    check(out_rc["outcome"] == "INCONCLUSIVE" and any(b.startswith("not model-attributable") for b in out_rc["blockers"]),
          f"RC blocker: {out_rc['outcome']} {out_rc.get('blockers')}")
    sr_hit = [i < 4 for i in range(n)]
    out_sr = outcome(pr, z, z, sr_hit)
    check(out_sr["outcome"] == "INCONCLUSIVE" and any(b.startswith("undirected") for b in out_sr["blockers"]),
          f"S blocker: {out_sr['outcome']} {out_sr.get('blockers')}")
    pr5 = [i < 5 for i in range(n)]
    check(outcome(pr5, z, z, z)["outcome"] == "PASS" and outcome([i < 4 for i in range(n)], z, z, z)["outcome"] == "INCONCLUSIVE",
          "5 vs 0 passes (p 0.031); 4 vs 0 does not (p 0.0625)")
    # NULL: b_F - c_F <= 1 (threshold 1, not 2)
    pf5 = [i < 5 for i in range(n)]
    check(outcome([i < 6 for i in range(n)], pf5, z, z)["outcome"] == "NULL", "b - c = 1 is NULL")
    check(outcome([i < 7 for i in range(n)], pf5, z, z)["outcome"] == "INCONCLUSIVE", "b - c = 2 is not NULL")
    # an exact sign test never exceeds its level, at any number of discordant pairs
    from math import comb

    worst = max(sum(comb(d, k) for k in range(d + 1) if r3.significant(k, d - k)) / 2 ** d for d in range(1, 25))
    check(worst <= 0.05, f"an exact sign test exceeds its level under p = 1/2 ({worst:.4f})")
    # wording and scope
    check(r3.scope_problems(f"m7u3 ({r3.SCOPE}): PASS; PF 3, PR 9, RC 0, SR 0 of 24") == [], "registered summary wording")
    check(r3.scope_problems("a wall-top landing") == ["landing", "wall-top"], "forbidden words")
    check(g3.SCOPE.startswith(r3.SCOPE), "the goal and rule scope labels agree")
    return {"rule_sha256": r3.rule_digest()[:16], "thresholds": {"alpha": 0.05, "null_max_bf": 1}}


def unit_model_reading_and_replication(out: Path) -> Dict[str, Any]:
    """The pre-declared readings (decision 8) and the M7u2 replication readout (decision 7): wording and boundaries."""
    base = list(range(100, 120))
    mk = lambda f, r, t: {h: {"frozen": [100.0 + i for i in range(20)], "refit": [r + i for i in range(20)],   # noqa: E731
                              "retrain": [t + i for i in range(20)]} for h in r3.HORIZONS}
    check(r3.model_reading(mk(0, 60.0, 98.0))["label"] == "MODEL_GAIN_BEYOND_RETRAIN_VARIATION", "gain beyond variation")
    check(r3.model_reading(mk(0, 70.0, 70.0))["label"] == "MODEL_GAIN_WITHIN_RETRAIN_VARIATION", "gain within variation")
    check(r3.model_reading(mk(0, 95.0, 99.0))["label"] == "NO_MODEL_GAIN", "no gain")
    check(r3.model_reading(mk(0, 130.0, 99.0))["label"] == "MODEL_REGRESSION", "regression")
    # the 20 % floor is exact: a reduction of 19 % is no gain, 20 % is the floor (the comparison is not float-sensitive)
    flat = {h: {"frozen": [100.0] * 20, "refit": [81.0] * 20, "retrain": [100.0] * 20} for h in r3.HORIZONS}
    check(r3.model_reading(flat)["label"] == "NO_MODEL_GAIN", "a 19 % reduction is below the floor")
    flat2 = {h: {"frozen": [100.0] * 20, "refit": [80.0] * 20, "retrain": [100.0] * 20} for h in r3.HORIZONS}
    check(r3.model_reading(flat2)["label"] == "MODEL_GAIN_BEYOND_RETRAIN_VARIATION", "a 20 % reduction is the floor")
    up_ = {h: {"frozen": [100.0] * 20, "refit": [120.0] * 20, "retrain": [100.0] * 20} for h in r3.HORIZONS}
    check(r3.model_reading(up_)["label"] == "MODEL_REGRESSION", "a 20 % increase is a regression")
    up2 = {h: {"frozen": [100.0] * 20, "refit": [119.0] * 20, "retrain": [100.0] * 20} for h in r3.HORIZONS}
    check(r3.model_reading(up2)["label"] == "NO_MODEL_GAIN", "a 19 % increase is not")
    # the reading is reported only: it never enters apply()
    check("model_reading" not in inspect.getsource(r3.apply) and "replication" not in inspect.getsource(r3.apply),
          "the rule must not consult a diagnostic")
    n = 24
    z = [False] * n
    rep = r3.replication_readout({"PF": [i < 6 for i in range(n)], "RC": z})
    check(rep["label"] == "MEETS_EVALUABLE_M7U2_PASS_CONDITIONS" and "S_frozen" in rep["not_evaluable"], f"replication {rep}")
    check(all(r3.replication_readout({"PF": [i < k for i in range(n)], "RC": z})["reading_label"]
              == "partial replication (S condition not evaluable)" for k in (0, 1, 6)), "readout label on every outcome")
    check(r3.replication_readout({"PF": [True], "RC": [False]})["reading_label"] == r3.REPLICATION_READING_LABEL, "label when UNAVAILABLE")
    check(r3.replication_readout({"PF": [i < 5 for i in range(n)], "RC": z})["label"] == "INCONCLUSIVE", "n_P = 5")
    check(r3.replication_readout({"PF": [i < 1 for i in range(n)], "RC": z})["label"] == "NULL_VS_RC", "b - c = 1")
    check(r3.replication_readout({"PF": [i < 6 for i in range(n)], "RC": [i < 1 for i in range(n)]})["label"] == "INCONCLUSIVE",
          "b - c = 5 with n_P = 6 is below the b - c >= 6 condition")
    return {"labels": ["MODEL_GAIN_BEYOND_RETRAIN_VARIATION", "MODEL_GAIN_WITHIN_RETRAIN_VARIATION", "NO_MODEL_GAIN",
                       "MODEL_REGRESSION"]}


def unit_goal_selection_rules(out: Path) -> Dict[str, Any]:
    entries = [f"g{i:03d}" for i in range(12)]
    ref_eps = [(f"r{i}", t2.synth_rows({}), False) for i in range(6)]
    ref = g3.Reference(ref_eps)
    row0 = t2.synth_rows({})[0]
    spec = {
        "g000": {40: (0.0, -1000.0), 90: (2000.0, -1000.0)},                   # tau 40 and 90 eligible (rise 1550)
        "g001": {40: (200.0, -1000.0), 70: (3000.0, -900.0)},                  # tau 40 overlaps g000's (dx 200)
        "g002": {50: (-1500.0, -1500.0)},
        "g003": {50: (300.0, -1000.0), 60: (900.0, -1000.0)},                  # dx exactly 300 overlaps; tau 60 free
        "g004": {50: (-1500.0, -1400.0)},                                      # overlaps g002 (dy 100)
        "g005": {50: (5000.0, -500.0)},
    }
    pool = synth_pool(spec, entries)
    sel = g3.select_goals(pool, ref, row0, entries=entries, n_goals=4)
    goals, rec = sel["goals"], sel["record"]
    # brute force: no two registered goals within the span; minimum distance recorded
    mind = min(g3.chebyshev(a.__dict__, b.__dict__) for i, a in enumerate(goals) for b in goals[i + 1:])
    check(mind > g3.NON_OVERLAP_SPAN and rec["independence"]["overlapping_pairs"] == [], f"overlap {rec['independence']}")
    check(rec["independence"]["min_pairwise_chebyshev"] == mind and rec["independence"]["n_pairs_checked"] == 6,
          "the minimum pairwise distance and the pair count are recorded")
    check(len({g.entry for g in goals}) == len(goals) == 4, "one goal per episode")
    # span boundary: a distance of exactly 300 overlaps, 300.5 does not
    a = {"x": 0.0, "y": 0.0}
    check(g3.chebyshev(a, {"x": 300.0, "y": 100.0}) <= g3.NON_OVERLAP_SPAN < g3.chebyshev(a, {"x": 300.5, "y": 0.0}),
          "span boundary")
    # a brute-force reference of the rule (sha order of episodes and taus; first tau overlapping nobody; skip otherwise)
    elig = {p["entry"]: sorted([t for t in spec.get(p["entry"], {})], key=lambda t, e=p["entry"]: g2.sha(f"m7u3|goal|{e}|{t}"))
            for p in pool}
    ref_goals = []
    for e in sorted([e for e in entries if elig[e]], key=lambda e: g2.sha(f"m7u3|goal|{e}")):
        for t in elig[e]:
            x, y = spec[e][t]
            if all(max(abs(x - gx), abs(y - gy)) > 300 for _e, _t, gx, gy in ref_goals):
                ref_goals.append((e, t, x, y))
                break
        if len(ref_goals) == 4:
            break
    check([(g.entry, g.tau) for g in goals] == [(e, t) for e, t, _x, _y in ref_goals], "selection differs from the brute-force reference")
    # the skip / pass-over records
    po = {(p["entry"], p["tau"]): p["overlaps"] for p in rec["passed_over_overlapping_taus"]}
    check(po or rec["skipped_episodes"], "this fixture must exercise a pass-over or a skip")
    for p in rec["passed_over_overlapping_taus"]:
        check(all(h["chebyshev"] <= g3.NON_OVERLAP_SPAN for h in p["overlaps"]), "a passed-over tau must overlap")
    check(all(s["entry"] in spec and s["eligible_taus"] >= 1 for s in rec["skipped_episodes"]), "skipped episodes are listed")
    # order and permutation invariance (selection depends on the pool as a set)
    rng = np.random.default_rng(3)
    sel2 = g3.select_goals([pool[i] for i in rng.permutation(len(pool))], ref, row0, entries=entries, n_goals=4)
    check(g3.goals_digest(sel2["goals"]) == g3.goals_digest(goals), "permutation invariance")
    # sha order: episodes by sha of the entry, taus by sha of entry|tau
    order = sorted((g.entry for g in goals), key=lambda e: g2.sha(f"m7u3|goal|{e}"))
    check([g.entry for g in goals] == order[:len(goals)] or len({g.entry for g in goals}) == 4, "sha episode order")
    # too few goals: INCOMPLETE, no fill, no relaxation
    try:
        g3.select_goals(pool, ref, row0, entries=entries, n_goals=6)
        check(False, "too few goals was accepted")
    except g3.GoalError as exc:
        check(exc.incomplete and exc.record["registered"] == 5 or exc.incomplete, f"incomplete: {exc}")
    # the pool must be exactly the registered entries; 129 words and a changed reset row are refused
    for bad, why in ((pool[:-1], "a missing entry"), (pool + [pool[0]], "a duplicate entry")):
        try:
            g3.select_goals(bad, ref, row0, entries=entries, n_goals=2)
            check(False, f"{why} was accepted")
        except g3.GoalError:
            pass
    long_ep = dict(pool[0], rows=t2.synth_rows({}, T=129), words=np.zeros((129, 2), np.int64))
    try:
        g3.select_goals([long_ep] + pool[1:], ref, row0, entries=entries, n_goals=2)
        check(False, "129 words was accepted")
    except g3.GoalError:
        pass
    moved = row0.copy()
    moved[F["x"]] += 1.0
    try:
        g3.select_goals(pool, ref, moved, entries=entries, n_goals=2)
        check(False, "a reset row off the record was accepted")
    except g3.GoalError:
        pass
    # the signature has no outcome, model or training-pool input
    params = set(inspect.signature(g3.select_goals).parameters)
    check(params == {"pool", "reference", "tick0_row", "entries", "n_goals"}, f"select_goals signature {params}")
    # production constants and the scramble
    check((g3.TRAIN_EPISODES, g3.TRAIN_TICKS, g3.GOAL_EPISODES, g3.GOAL_TICKS, g3.N_GOALS, g3.NON_OVERLAP_SPAN, g3.BUDGET)
          == (540, 192, 540, 128, 24, 300.0, 128), "production constants")
    check(len(g3.TRAIN_ENTRIES) == len(g3.GOAL_ENTRIES) == 540 and g3.TRAIN_ENTRIES[0] == "t000"
          and g3.GOAL_ENTRIES[-1] == "g539", "entry names")
    sc = [g3.scrambled(k) for k in range(24)]
    check(sorted(sc) == list(range(24)) and all(sc[k] != k and sc[sc[k]] == k for k in range(24)), "pi is a derangement")
    # coverage: counted only on request, with the reference semantics (valid airborne reach of the box within 128)
    eps = [(f"e{i}", t2.synth_rows({40: (0.0, -1000.0)}), False) for i in range(3)] + [("far", t2.synth_rows({}), False)]
    cov = g3.coverage([goals[0]] + [g2.Goal(k=1, entry="x", episode_id="x", tau=40, x=0.0, y=-1000.0, rise=0, ref_reaching=0)], eps)
    check(cov[1] == 3, f"coverage {cov}")
    return {"goals": [(g.entry, g.tau) for g in goals], "min_pairwise": mind, "passed_over": len(po),
            "skipped": len(rec["skipped_episodes"])}


def unit_selection_on_m7u2_pool(out: Path) -> Dict[str, Any]:
    """The m7u3 rule on the PRESERVED M7u2 pool (read only, forward passes elsewhere): the supply estimate of the proposal's
    section 3.4. The m7u2 selection reproduces its goal digest; the m7u3 rule (sha order of the m7u3 keys) yields at least
    24 non-overlapping goals from those 360 episodes."""
    import m7u3_gate as gate

    src, row0, ref, _fz = m7u1()
    rec = gate.load_m7u2_records()
    pool = []
    import m7u_worker as uw

    for e in rec["pool"]:
        side = uw.read_sidecar(gate.g1.resolve(e["artifact_dir"]))
        pool.append({"entry": e["entry"], "episode_id": e["episode_id"], "rows": side["rows"], "words": side["words"],
                     "fell": e["termination_reason"] == "native_failure"})
    s2 = g2.select_goals(pool, ref, row0)
    check(g2.goals_digest(s2["goals"]) == gate.PIN["m7u2_goal_digest"], "m7u2 selection no longer reproduces its digest")
    names = [e["entry"] for e in pool]
    s3 = g3.select_goals(pool, ref, row0, entries=names, n_goals=24)
    ind = s3["record"]["independence"]
    check(ind["overlapping_pairs"] == [] and ind["n_pairs_checked"] == 276, "24 goals, 276 pairs, no overlap")
    check(s3["record"]["eligible_points"] == 823 and s3["record"]["episodes_with_a_goal"] == 63,
          f"eligibility on the M7u2 pool: {s3['record']['eligible_points']} points, {s3['record']['episodes_with_a_goal']} episodes")
    return {"m7u2_goal_digest": g2.goals_digest(s2["goals"])[:16], "m7u3_goal_digest": g3.goals_digest(s3["goals"])[:16],
            "eligible_points": s3["record"]["eligible_points"], "episodes_with_a_goal": s3["record"]["episodes_with_a_goal"],
            "min_pairwise_chebyshev": ind["min_pairwise_chebyshev"], "passed_over": len(s3["record"]["passed_over_overlapping_taus"]),
            "skipped": len(s3["record"]["skipped_episodes"])}


def unit_streams(out: Path) -> Dict[str, Any]:
    import m7u3_gate as gate

    check(gate.stream_key_problems() == [], f"stream keys: {gate.stream_key_problems()}")
    keys = gate.all_stream_keys()
    check(all(k.startswith("m7u3|1|train|") for k in keys["train"]) and all(k.startswith("m7u3|2|pool|") for k in keys["pool"])
          and all(k.startswith("m7u3|3|goal|") for k in keys["goal"]), "seeds 1 / 2 / 3")
    check(len(keys["train"]) == len(keys["pool"]) == 540 and len(keys["goal"]) == 24, "key counts")
    check(not (set(keys["train"]) | set(keys["pool"]) | set(keys["goal"])) & set(gate.earlier_stream_keys()),
          "overlap with an m7u1 / M7u2 key")
    # the stream of an entry is the behaviour policy: candidate 0 of its fixed-draw stream, independent of the arm
    w1 = up.rc_words(gate.stream_key("train", "t000"), 17, 40)
    w2 = up.rc_words(gate.stream_key("pool", "g000"), 17, 40)
    check(w1 != w2 and w1 == up.rc_words(gate.stream_key("train", "t000"), 17, 40), "streams are distinct and deterministic")
    return {"keys": {k: len(v) for k, v in keys.items()}}


def unit_refit_pipeline(out: Path) -> Dict[str, Any]:
    """The refit's pieces on synthetic data: stratified bootstrap, the training loop against m7u1's, the data manifest,
    the optimizer registry, vocabulary caps. No recorded data is trained on."""
    import torch

    import m7u2_gate as gg
    import m7u3_gate as gate
    import m7u3_refit as rf
    import m7u_model as um

    # synthetic transition set with 90 'base' episodes then 130 'pool' episodes
    _src, _row0, _ref, fz = m7u1()
    ts = t2_synthetic_ts(fz.ctx, 22000, 1)
    ts.episode_of = np.arange(22000) // 100                      # 220 episodes of 100 transitions
    ts.n_episodes = 220
    # bootstrap equals m7u1's when the pool is empty
    base_only = um.TransitionSet(dense=ts.dense[:9000], cur=ts.cur[:9000], prev=ts.prev[:9000],
                                 targets={k: v[:9000] for k, v in ts.targets.items()}, episode_of=ts.episode_of[:9000],
                                 n_episodes=90)
    a = rf.stratified_bootstrap_indices(base_only, 90, 3, 5)
    b = um.bootstrap_indices(base_only, 3, 5)
    check(all(np.array_equal(x, y) for x, y in zip(a, b)), "the stratified bootstrap must equal m7u1's with an empty pool")
    # strata: every member draws exactly n_base base episodes and n_pool pool episodes (with replacement)
    s = rf.stratified_bootstrap_indices(ts, 90, 3, 5)
    for m in range(3):
        eps_drawn = ts.episode_of[s[m]]
        starts = eps_drawn[::100]
        check(len(s[m]) == 22000 and int((starts < 90).sum()) == 90 and int((starts >= 90).sum()) == 130,
              f"member {m}: strata sizes {(starts < 90).sum()} / {(starts >= 90).sum()}")
    check(len({tuple(x[:300]) for x in s}) == 3, "members draw different bootstraps")
    check(all(np.array_equal(x, y) for x, y in zip(s, rf.stratified_bootstrap_indices(ts, 90, 3, 5))), "deterministic")
    # the training loop equals um.train when given m7u1's bootstrap (identical parameters)
    vocab = fz.vocab
    ctx = fz.ctx
    m1 = um.DynamicsEnsemble(vocab, members=3, seed=4)
    m2 = um.DynamicsEnsemble(vocab, members=3, seed=4)
    um.train(m1, ctx, base_only, steps=6, batch=64, seed=2, log_every=3)
    n_before = len(rf.OPTIMIZERS)
    rf.train_loop(m2, ctx, base_only, um.bootstrap_indices(base_only, 3, 2), steps=6, batch=64, seed=2, log_every=3)
    check(um.parameter_digest(m1) == um.parameter_digest(m2), "train_loop differs from um.train")
    opts = rf.OPTIMIZERS[n_before:]
    check(len(opts) == 1 and opts[0]["all_model_params"] and opts[0]["params"] == len(list(m2.parameters())),
          f"optimizer registry {opts}")
    # an optimizer over another model's parameters is flagged
    other = um.DynamicsEnsemble(vocab, members=3, seed=9)
    rf.train_loop(other, ctx, base_only, um.bootstrap_indices(base_only, 3, 2), steps=1, batch=16, seed=1)
    check(rf.OPTIMIZERS[-1]["all_model_params"], "registry flags the optimizer's own model")
    # after training, constructing an optimizer is guarded (the gate's guard); the guard is removed afterwards
    with gg.no_optimizer():
        try:
            torch.optim.Adam(m2.parameters())
            check(False, "an optimizer was constructed under the guard")
        except gg.IntegrityStop:
            pass
        try:
            rf.train_loop(m2, ctx, base_only, um.bootstrap_indices(base_only, 3, 2), steps=1, batch=16, seed=1)
            check(False, "train_loop ran under the guard")
        except gg.IntegrityStop:
            pass
    torch.optim.SGD([torch.zeros(1, requires_grad=True)], lr=0.1)
    # the driver trains only through m7u3_refit.train_loop (a source scan backs the guard)
    text = (REPO_ROOT / "rl" / "m7u3_gate.py").read_text(encoding="utf-8")
    for bad_call in ("um.train(", ".backward(", "um.losses(", "optim.Adam", "optim.SGD", ".step()", "torch.optim"):
        check(bad_call not in text, f"m7u3_gate.py contains {bad_call!r}")
    rtext = (REPO_ROOT / "rl" / "m7u3_refit.py").read_text(encoding="utf-8")
    check(rtext.count("torch.optim.Adam(") == 1 and ".backward(" in rtext and rtext.count(".backward(") == 1,
          "the refit module has exactly one optimizer construction and one backward")
    # parameters of a trained synthetic model are not the frozen ones; the identity digest function agrees with um's
    check(rf.parameter_diff(m1, m2)["max_abs_diff"] == 0.0, "parameter_diff")
    # vocabulary caps are enforced (INVALID, nothing merged silently)
    caps = um.S_CAP
    try:
        um.S_CAP = 3
        rows = np.zeros((10, us.N_FIELDS))
        rows[:, F["valid"]] = 1.0
        rows[:, F["status"]] = np.arange(10)
        um.build_vocab(rows)
        check(False, "the status cap was not enforced")
    except um.ModelError:
        pass
    finally:
        um.S_CAP = caps
    return {"optimizers_registered": len(rf.OPTIMIZERS)}


def t2_synthetic_ts(ctx: Any, n: int, seed: int) -> Any:
    import m7u_tests as mt

    return mt._synthetic_ts(ctx, n, seed)


def unit_refit_manifest(out: Path) -> Dict[str, Any]:
    """The data manifest: exactly m7u1's 80 training episodes plus t000..t539; exclusions verified."""
    import m7u2_gate as gg
    import m7u3_gate as gate

    src, _row0, _ref, _fz = m7u1()
    train, held = (lambda m: m.m7u1_split(src))(__import__("m7u3_refit"))
    check(len(train) == 80 and len(held) == 12 and not ({e.episode_id for e in train} & {e.episode_id for e in held}),
          "m7u1 split")
    check([e.episode_id for e in train] == [str(i) for i in src.train_ids], "m7u1 order = record order")
    results = [{"entry": e, "episode_id": f"pool_{e}"} for e in g3.TRAIN_ENTRIES]
    m2pool = [{"episode_id": f"m7u2_{i}"} for i in range(360)]
    man = gate.refit_manifest(src, results, m2pool)
    check(man["problems"] == [] and len(man["pool_entries"]) == 540 and man["pool_entries"][0] == "t000", "clean manifest")
    heldout_id = sorted({e[0] for e in src.episodes} - set(src.train_ids))[0]
    for mutate, why in ((lambda r, m: r[0].update(episode_id=heldout_id), "a held-out episode"),
                        (lambda r, m: r[1].update(episode_id=str(src.train_ids[0])), "an m7u1 training episode"),
                        (lambda r, m: r[2].update(episode_id="m7u2_5"), "an M7u2 pool episode"),
                        (lambda r, m: r.pop(), "a missing training-pool entry"),
                        (lambda r, m: r[3].update(entry="g003"), "a non-registered entry")):
        r2_ = [dict(r) for r in results]
        mutate(r2_, m2pool)
        check(gate.refit_manifest(src, r2_, m2pool)["problems"], f"{why} was accepted")
    gp = gate.refit_manifest(src, results, m2pool, goal_ids=["pool_t004"])
    check(gp["problems"], "a goal-pool episode in the training pool was accepted")
    return {"entries": 540}


def unit_prep_records(out: Path) -> Dict[str, Any]:
    """The preparation's results: the identity retrain was bit-exact (decision 6), P_retrain is pinned (decision 4)."""
    import m7u2_gate as gg
    import m7u3_gate as gate
    import m7u_model as um

    ok, why = gate.attestation_status()
    check(ok, f"attestation: {why}")
    ident = json.loads(gate.IDENTITY_RECORD.read_text(encoding="utf-8"))
    check(ident["bit_exact"] and ident["parameter_digest"] == gg.PIN["parameter_digest"]
          and ident["parameter_diff"]["max_abs_diff"] == 0.0 and ident["parameter_diff"]["elements_differing"] == 0,
          "identity retrain not bit-exact")
    check(ident["rebuilt_inputs_equal_m7u1_saved_inputs"]["ok"] and ident["vocab_equals_pin"], "identity inputs / vocabulary")
    check(ident["steps"] == 6000 and ident["seed"] == 0 and ident["threads"] == 6, "identity retrain settings")
    _src, _row0, _ref, fz = m7u1()
    rt = retrain_real()
    check(all(not p.requires_grad for p in rt.model.parameters()) and not rt.model.training, "P_retrain gradients / mode")
    check(um.parameter_digest(rt.model) == gate.retrain_pins()["parameter_digest"] != gg.PIN["parameter_digest"],
          "P_retrain digest")
    # a tampered file or wrong pin is refused
    import torch

    m2, vocab, _ = um.load(gate.RETRAIN_PATH)
    with torch.no_grad():
        next(iter(m2.parameters())).view(-1)[0] += 1e-3
    bad = out / "retrain_tampered.pt"
    um.save(m2, vocab, bad)
    for path, pins, why2 in ((bad, gate.retrain_pins(), "a tampered file"),
                             (gate.RETRAIN_PATH, dict(gate.retrain_pins(), parameter_digest="0" * 64), "a wrong digest pin"),
                             (gate.RETRAIN_PATH, dict(gate.retrain_pins(), model_sha256="0" * 64), "a wrong file pin"),
                             (gate.RETRAIN_PATH, {"model_sha256": None, "parameter_digest": None}, "missing pins")):
        try:
            gate.load_retrain(fz, path, pins=pins)
            check(False, f"{why2} was accepted")
        except gate.IntegrityStop:
            pass
    return {"retrain_digest": gate.retrain_pins()["parameter_digest"][:16], "identity_wall_s": ident["train_wall_s"]}


def unit_frozen_and_records(out: Path) -> Dict[str, Any]:
    import m7u2_gate as gg
    import m7u3_gate as gate

    src, row0, _ref, fz = m7u1()
    before = gg.parameter_digest(fz.model)
    r1 = gg.reproduce_decisions(fz, src)
    rec2 = gate.load_m7u2_records()
    r2_ = gate.reproduce_m7u2_decisions(fz, rec2)
    check(r1["ok"] and r1["chosen_equal"] == 32, f"m7u1 reproduction {r1}")
    check(r2_["ok"] and r2_["chosen_equal"] == 32 and r2_["decisions"] == 32, f"M7u2 reproduction {r2_}")
    check(gg.parameter_digest(fz.model) == before == gg.PIN["parameter_digest"], "forward passes changed the digest")
    # a tampered M7u2 pin is refused
    saved = gate.PIN["m7u2_pool_sha256"]
    gate.PIN["m7u2_pool_sha256"] = "0" * 64
    try:
        gate.load_m7u2_records()
        check(False, "a wrong M7u2 pool pin was accepted")
    except gate.IntegrityStop:
        pass
    finally:
        gate.PIN["m7u2_pool_sha256"] = saved
    # the P1 entries (m7u1's two and M7u2's two) from the records: words, reach ticks, digests as pinned
    p1b = gate.p1_expected_m7u2(rec2, row0)
    check([e["entry"] for e in p1b] == ["p1_m7u2_g14_P", "p1_m7u2_g03_P"] and [len(e["words"]) for e in p1b] == [49, 60]
          and all(e["t"] == 0 and e["prefix"] == [] for e in p1b), "M7u2 P1 entries")
    p1a = gg.p1_expected(src)
    check([len(e["words"]) for e in p1a] == [171, 183], "m7u1 P1 entries")
    check(sum(len(e["words"]) for e in p1a + p1b) == gate.TICK_BUDGET["p1"] == 463, "P1 ticks")
    return {"m7u1_repro": {k: r1[k] for k in ("chosen_equal", "max_abs_diff")},
            "m7u2_repro": {k: r2_[k] for k in ("chosen_equal", "max_abs_diff")}}


def unit_strict_from_reset_on_m7u2_pool(out: Path) -> Dict[str, Any]:
    """The frozen model's strict from-reset open-loop figures on the 360 M7u2 pool episodes, through the PRODUCTION
    diagnostic code, must equal the proposal's section 1.2 (153 / 333 / 714 / 908). Forward passes only; the same code is
    run on P_retrain."""
    import m7u3_analysis as an
    import m7u3_gate as gate

    _src, _row0, _ref, fz = m7u1()
    rec2 = gate.load_m7u2_records()
    pool = gate.m7u2_pool_episodes(rec2)
    check(len(pool) == 360 and all(len(e["words"]) == 128 for e in pool), "M7u2 pool shape")
    strict = an.strict_open_loop(fz.model, fz.ctx, pool)
    summ = an.summarise_strict(strict)
    got = {h: summ[str(h)]["median"] for h in an.HORIZONS}
    for h, want in gate.STRICT_M7U2_FROZEN_MEDIANS.items():
        check(abs(got[h] - want) <= 1.0 and summ[str(h)]["n"] == 360, f"h={h}: median {got[h]} != {want} (n {summ[str(h)]['n']})")
    # the same episodes for every model (the included set depends on the episode alone)
    rt = retrain_real()
    s2 = an.strict_open_loop(rt.model, rt.ctx, pool)
    check(all(list(strict[h]["index"]) == list(s2[h]["index"]) for h in an.HORIZONS), "the included episodes differ by model")
    paired = an.paired_strict(s2, strict)
    check(all(0.0 <= v["share_a_better"] <= 1.0 for v in paired.values()), "paired shares")
    return {"frozen_medians": got, "frozen_p90": {h: summ[str(h)]["p90"] for h in an.HORIZONS},
            "frozen_share_gt_box": {h: summ[str(h)]["share_gt_box"] for h in an.HORIZONS},
            "retrain_medians": {h: an.summarise_strict(s2)[str(h)]["median"] for h in an.HORIZONS},
            "retrain_vs_frozen_paired": paired}


def unit_tree_memory_and_clock(out: Path) -> Dict[str, Any]:
    import m7u3_gate as gate
    import m7u_gate as g1

    # the real tree snapshot sees a child and a grandchild process and their memory
    snap0 = gate.tree_snapshot()
    check(snap0 is not None and snap0["processes"] >= 1 and snap0["tree_private_mb"] > 0, f"tree snapshot {snap0}")
    code = ("import subprocess, sys, time\n"
            "c = subprocess.Popen([sys.executable, '-c', 'a = bytearray(120 * 2 ** 20); a[::4096] = b\"x\" * len(a[::4096]); import time; time.sleep(6)'])\n"
            "b = bytearray(120 * 2 ** 20); b[::4096] = b'x' * len(b[::4096])\n"
            "time.sleep(6)\n")
    p = subprocess.Popen([sys.executable, "-c", code])
    try:
        time.sleep(2.5)
        snap1 = gate.tree_snapshot()
        check(snap1["processes"] >= snap0["processes"] + 2 and snap1["tree_private_mb"] >= snap0["tree_private_mb"] + 200,
              f"descendants not counted: {snap0['processes']} -> {snap1['processes']}, "
              f"{snap0['tree_private_mb']} -> {snap1['tree_private_mb']} MB")
    finally:
        p.kill()
        p.wait()
    # every cap, one at a time
    ok = {"main_private_mb": 100.0, "tree_private_mb": 100.0, "tree_working_set_mb": 100.0, "system_available_mb": 5000.0,
          "system_commit_free_mb": 9000.0, "processes": 3}
    check(gate.memory_breach(ok) is None, "a snapshot within every cap was refused")
    for key, value, word in (("main_private_mb", 3073.0, "main process"), ("tree_private_mb", 9217.0, "tree private"),
                             ("tree_working_set_mb", 4097.0, "working set"), ("system_available_mb", 1023.0, "available"),
                             ("system_commit_free_mb", 2047.0, "free commit")):
        why = gate.memory_breach(dict(ok, **{key: value}))
        check(why is not None and word in why, f"{key}: {why}")
    for key, value in (("main_private_mb", 3072.0), ("tree_private_mb", 9216.0), ("tree_working_set_mb", 4096.0),
                       ("system_available_mb", 1024.0), ("system_commit_free_mb", 2048.0)):
        check(gate.memory_breach(dict(ok, **{key: value})) is None, f"{key} exactly at the cap must be allowed")
    # the sampler logs every sample, remembers the first breach, and the clock stops the run on it
    log = out / "mem.jsonl"
    seq = iter([dict(ok), dict(ok, tree_private_mb=9300.0), dict(ok)])
    s = gate.TreeSampler(log, snapshot=lambda: next(seq))
    for _ in range(3):
        s.sample()
    check(s.breach and "tree private" in s.breach and s.samples == 3 and s.peak["tree_private_mb"] == 9300.0
          and len(log.read_text().splitlines()) == 3, f"sampler {s.breach} {s.samples}")
    clk = gate.Clock3(caps={"p1": 10}, global_cap=10 ** 6, memory=lambda: None, sampler=s)
    clk.phase = "p1"
    try:
        clk.check()
        check(False, "a tree-memory breach did not stop the run")
    except g1.CapStop as exc:
        check("tree private" in str(exc), str(exc))
    clk2 = gate.Clock3(caps={"p1": 10}, global_cap=10 ** 6, memory=lambda: None, sampler=gate.TreeSampler(out / "m2.jsonl", snapshot=lambda: dict(ok)))
    clk2.phase = "p1"
    clk2.check()
    # a live sampler thread produces samples and stops cleanly
    live = gate.TreeSampler(out / "live.jsonl", interval=0.2).start()
    time.sleep(0.9)
    st = live.stop()
    check(st["samples"] >= 3 and st["breach"] is None or st["breach"], f"live sampler {st}")
    return {"live_samples": st["samples"], "peak": {k: v for k, v in st["peak"].items() if "private" in k}}


def unit_readiness(out: Path) -> Dict[str, Any]:
    import m7u3_gate as gate

    good_mem = lambda: {"available_mb": 8000.0, "commit_free_mb": 16000.0}  # noqa: E731
    fast = lambda: {"n": 40, "median_s": 0.3, "p95_s": 0.31}  # noqa: E731
    tp_ok = lambda: {"steps": 20, "median_s": 0.06, "p95_s": 0.07}  # noqa: E731
    check(gate.readiness(fast, good_mem, tp_ok)["ok"], "a ready machine was refused")
    for probe, mem, tp, why in ((lambda: {"n": 40, "median_s": 0.5, "p95_s": 0.51}, good_mem, tp_ok, "slow planning"),
                                (fast, lambda: {"available_mb": 3000.0, "commit_free_mb": 16000.0}, tp_ok, "low memory"),
                                (fast, lambda: {"available_mb": 8000.0, "commit_free_mb": 9000.0}, tp_ok, "low commit"),
                                (fast, lambda: None, tp_ok, "unknown memory"),
                                (fast, good_mem, lambda: {"steps": 20, "median_s": 0.11, "p95_s": 0.12}, "slow training step")):
        r = gate.readiness(probe, mem, tp)
        check(not r["ok"] and r["problems"], f"{why} was not refused")
    _src, row0, _ref, fz = m7u1()
    t = gate.g1 and __import__("m7u2_gate").timing_probe(fz, row0, n=3, warmup=1)
    check(0 < t["median_s"] < 10 and t["n"] == 3, f"timing probe {t}")
    before = __import__("m7u2_gate").parameter_digest(fz.model)
    tr = gate.training_probe(fz, steps=3, warmup=1)
    check(0 < tr["median_s"] < 5, f"training probe {tr}")
    check(__import__("m7u2_gate").parameter_digest(fz.model) == before, "the training probe touched the frozen model")
    return {"probe": t, "train_probe": tr}


def _gate_world(out: Path, n_goal_entries: int = 60):
    """Shared synthetic pieces: reference, frozen / retrain contexts, a synthetic m7u1 source."""
    import m7u_gate as g1

    ref_eps = fake_episodes(out / "ref", [f"r{i:03d}" for i in range(20)], n_workers=5)
    row0 = ref_eps[0]["rows"][0]
    ref = g2.Reference([(e["entry"], e["rows"], e["termination_reason"] == "native_failure") for e in ref_eps])
    fz = fake_frozen(out)
    rt = fake_retrain(out, fz)
    return row0, ref, fz, rt


def unit_tick0_drive(out: Path) -> Dict[str, Any]:
    """Four arms from the normal tick-0 reset, each planned with its own model; no prefix; the reset row is checked before
    the first word."""
    import m7u3_gate as gate
    import m7u_gate as g1
    import m7u_model as um

    row0, ref, fz, rt = _gate_world(out)
    eps = fake_episodes(out / "src", ["s0", "s1", "s2", "s3", "s4", "s5"], n_workers=3)
    goals = []
    for e in eps:
        r = e["rows"]
        air = [t for t in range(g3.TAU_MIN, min(g3.TAU_MAX, len(r) - 1) + 1) if r[t, F["ga"]] == 1]
        if air and len(goals) < 3 and all(g3.chebyshev({"x": r[air[0], F["x"]], "y": r[air[0], F["y"]]}, g.__dict__) > 300
                                          for g in goals):
            t = air[0]
            goals.append(g2.Goal(k=len(goals), entry=e["entry"], episode_id=str(e["episode_id"]), tau=t,
                                 x=float(r[t, F["x"]]), y=float(r[t, F["y"]]), rise=float(r[t, F["y"]] - row0[F["y"]]),
                                 ref_reaching=0, witness=[tuple(int(v) for v in w) for w in e["words"][:t]]))
    check(len(goals) == 3, f"synthetic goals {len(goals)}")
    models = {"frozen": (fz.model, fz.ctx), "refit": (rt.model, rt.ctx)}
    # record which model each planning batch used (a wrapper around the generic batch planner)
    used: List[Tuple[str, str]] = []
    real = g1.plan_batch

    def spy(model, ctx, items):                                           # noqa: ANN001
        key = "frozen" if model is fz.model else ("refit" if model is rt.model else "other")
        for t, _a in items:
            used.append((t.entry["arm"], key))
        return real(model, ctx, items)

    g1.plan_batch = spy
    try:
        cfg = gate.evaluation_configs(goals, 3, row0)
        L = ledger(eval_control=12 * g3.BUDGET)
        trials = gate.drive(fake_vec(out / "eval", 3, horizon=3600), cfg, phase="evaluation", ledger=L,
                            clock=g1.Clock(memory=lambda: None), n_candidates=17, row0=row0, goals=goals, models=models,
                            track=fz.track)
    finally:
        g1.plan_batch = real
    check(len(trials) == 12 and L.used["eval_control"] == sum(len(r["words"]) for r in trials), "ledger = words")
    check({a for a, _k in used if True} == {"PF", "PR", "SR"}, f"planned arms {set(a for a, _ in used)}")
    check(all(k == ("frozen" if a == "PF" else "refit") for a, k in used), "an arm planned with the wrong model")
    check(not any(a == "RC" for a, _k in used), "RC reached a model")
    for r in trials:
        check(np.array_equal(r["rows"][0], row0, equal_nan=True), f"{r['entry']}: start row")
        check(all(int(r["rows"][i, F["input_tick"]]) == i for i in range(len(r["rows"]))), "input_tick = words submitted")
        check(1 <= len(r["words"]) <= g3.BUDGET, f"{r['entry']}: {len(r['words'])} words")
        check(r["decisions"][0] == 0, f"{r['entry']}: the first decision is not at consumed tick 0")
        if r["arm"] == "RC":
            regen = up.rc_words(gate.stream_key("goal", r["goal_k"]), 17, len(r["words"]))
            check([tuple(w) for w in r["words"]] == regen, f"{r['entry']}: RC is not candidate 0 from tick 0")
    # the four arms of a goal share one stream: their first decision draws the same candidates
    by = {(r["goal_k"], r["arm"]): r for r in trials}
    ctls = [gate.controller_for({"kind": "trial", "arm": a, "goal_k": 1, "budget": 128}, 17, goals) for a in gate.ARMS]
    check(len({c.stream_key for c in ctls}) == 1 and ctls[0].stream_key == gate.stream_key("goal", 1), "shared stream")
    check(ctls[0].goal == ctls[1].goal == (goals[1].x, goals[1].y) and ctls[3].goal == (goals[g3.scrambled(1, 3)].x,
                                                                                         goals[g3.scrambled(1, 3)].y)
          and ctls[2].goal is None and ctls[3].arm == "S", "commanded goals (SR is commanded pi(g))")
    # the evaluation ledger cap one tick short stops before the request that would exceed it
    L_short = ledger(eval_control=7)
    try:
        gate.drive(fake_vec(out / "eval_cap", 3, horizon=3600), gate.evaluation_configs(goals, 3, row0), phase="evaluation",
                   ledger=L_short, clock=g1.Clock(memory=lambda: None), n_candidates=17, row0=row0, goals=goals,
                   models=models, track=fz.track)
        check(False, "the evaluation tick cap was not enforced")
    except g1.CapStop:
        check(0 < L_short.used["eval_control"] <= 7, f"ledger {L_short.used}")
    # a reset row off the tick-0 record stops the run before any word is sent
    bad_row = row0.copy()
    bad_row[F["x"]] += 1.0
    L2 = ledger(eval_control=10 ** 6)
    try:
        gate.drive(fake_vec(out / "eval_bad", 1, horizon=3600), gate.evaluation_configs(goals[:1], 1, bad_row),
                   phase="evaluation", ledger=L2, clock=g1.Clock(memory=lambda: None), n_candidates=17, row0=bad_row,
                   goals=goals, models=models, track=fz.track)
        check(False, "a reset row off the record was accepted")
    except gate.IntegrityStop:
        check(L2.used["eval_control"] == 0, "ticks were consumed before the start check")
    # prefixes, archived starts, longer budgets and another scored goal are refused before launch
    for mutate, why in ((lambda e: e.update(t=95), "a prefix length"), (lambda e: e.update(prefix=[[0, 0]]), "a prefix"),
                        (lambda e: e.update(expected_start_row=[0.0] * us.N_FIELDS), "an archived start row"),
                        (lambda e: e.update(budget=200), "a longer budget"),
                        (lambda e: e.update(goal=[0.0, 0.0]), "a scored goal other than g"),
                        (lambda e: e.update(arm="S"), "an unregistered arm")):
        c = gate.evaluation_configs(goals, 1, row0)
        mutate(c[0]["entries"][0])
        try:
            gate.validate_entries(c, "evaluation", goals, row0)
            check(False, f"{why} was accepted")
        except ValueError:
            pass
    return {"trials": len(trials), "ticks": L.used["eval_control"], "reached": sum(r["reach_tick"] is not None for r in trials),
            "planned_by_model": {k: sum(1 for _a, kk in used if kk == k) for k in ("frozen", "refit")}}


def unit_scrambled_scoring(out: Path) -> Dict[str, Any]:
    """SR is commanded pi(g) but scored on g: reaching pi(g) never ends or counts a trial (the REAL probe)."""
    import m7u_gate as g1

    row0, _ref, fz, _rt = _gate_world(out)
    eps = fake_episodes(out / "src", ["s0", "s1", "s2", "s3"], n_workers=2)
    near = None
    for e in eps:
        r = e["rows"]
        air = [t for t in range(g3.TAU_MIN, min(g3.TAU_MAX, len(r) - 1) + 1) if r[t, F["ga"]] == 1]
        if air:
            t = air[0]
            near = g2.Goal(k=1, entry=e["entry"], episode_id=str(e["episode_id"]), tau=t, x=float(r[t, F["x"]]),
                           y=float(r[t, F["y"]]), rise=0.0, ref_reaching=0, witness=[tuple(int(v) for v in w) for w in e["words"][:t]])
            break
    check(near is not None, "no airborne synthetic point")
    far = g2.Goal(k=0, entry="far", episode_id="far", tau=50, x=50000.0, y=50000.0, rise=0.0, ref_reaching=0)
    start = [None if np.isnan(v) else float(v) for v in row0]
    words = [list(w) for w in near.witness] + [[0, 0]] * 5
    base = {"kind": "trial", "t": 0, "prefix": [], "expected_start_row": start, "budget": len(words), "words": words}
    led = ledger(replays=10 ** 6)
    s_far = g1.run_single(fake_single(out / "far", 3600), [dict(base, entry="S_far", goal=[far.x, far.y])], phase="replays",
                          ledger=led, clock=g1.Clock(memory=lambda: None))[0]
    s_near = g1.run_single(fake_single(out / "near", 3600), [dict(base, entry="S_near", goal=[near.x, near.y])],
                           phase="replays", ledger=led, clock=g1.Clock(memory=lambda: None))[0]
    in_box = [i for i, r in enumerate(s_far["rows"]) if i > 0 and r[F["ga"]] == 1 and abs(r[F["x"]] - near.x) <= g3.BOX
              and abs(r[F["y"]] - near.y) <= g3.BOX]
    check(in_box and in_box[0] <= near.tau, "the witness does not pass through the partner's box")
    check(s_far["reach_tick"] is None and s_far["truncation_reason"] == "trial_budget" and s_far["sent"] == len(words),
          "a trial ended or counted at a box other than its scored goal")
    check(s_near["reach_tick"] == in_box[0] and s_near["truncation_reason"] == "goal_reached",
          "the scored goal's first reach did not end the trial")
    return {"partner_box_entered_at": in_box[0]}


def unit_pools_and_caps(out: Path) -> Dict[str, Any]:
    import m7u3_gate as gate
    import m7u_gate as g1

    for entries, per, words in ((g3.TRAIN_ENTRIES, 108, 192), (g3.GOAL_ENTRIES, 108, 128)):
        cfg = gate.pool_configs(5, entries)
        names = [e["entry"] for c in cfg.values() for e in c["entries"]]
        check(sorted(names) == list(entries) and all(len(c["entries"]) == per for c in cfg.values()), "production pool")
    check(gate.TRAIN_POOL == (540, 192) and gate.GOAL_POOL == (540, 128), "pool constants")
    names = [f"t{i:03d}" for i in range(6)]
    eps = fake_episodes(out / "pool", names, n_workers=3, horizon=192)
    for e in eps:
        check(len(e["words"]) <= g3.TRAIN_TICKS, f"{e['entry']}: {len(e['words'])} words")
        check([tuple(w) for w in e["words"]] == up.rc_words(gate.stream_key("train", e["entry"]), 17, len(e["words"])),
              f"{e['entry']}: not the training-pool behaviour stream")
    # pool entries other than plain registered behaviour episodes are refused before launch
    row0 = eps[0]["rows"][0]
    for bad, why in (({"entry": "t000", "kind": "collect", "prefix": []}, "an entry with extra fields"),
                     ({"entry": "zzz", "kind": "collect"}, "an unregistered entry"),
                     ({"entry": "t000", "kind": "trial"}, "a trial entry")):
        try:
            gate.validate_entries({0: {"entries": [bad]}}, "train_pool", None, row0, g3.TRAIN_ENTRIES)
            check(False, f"{why} was accepted")
        except ValueError:
            pass
    # a pool cap one tick short stops before the request that would exceed it
    for phase, ent in (("train_pool", names), ("goal_pool", [f"g{i:03d}" for i in range(6)])):
        L = ledger(**{phase: 6 * 192 - 1})
        try:
            gate.drive(fake_vec(out / f"{phase}2", 3, horizon=192), gate.pool_configs(3, ent), phase=phase, ledger=L,
                       clock=g1.Clock(memory=lambda: None), n_candidates=17, row0=row0)
            check(False, f"the {phase} cap was not enforced")
        except g1.CapStop:
            check(L.used[phase] <= 6 * 192 - 1, "ledger exceeded before the stop")
    # wall and memory caps
    ticks = iter(range(10 ** 6))
    clk = g1.Clock(now=lambda: float(next(ticks)), caps={"train_pool": 5}, global_cap=10 ** 6, memory=lambda: None)
    clk.begin("train_pool")
    try:
        for _ in range(10):
            clk.check()
        check(False, "the wall cap was not enforced")
    except g1.CapStop:
        pass
    clk2 = g1.Clock(caps={"refit": 900}, memory=lambda: 4000.0, memory_cap_mb=gate.MEMORY_CAP_MB)
    try:
        clk2.begin("refit")
        check(False, "the memory cap was not enforced")
    except g1.CapStop:
        pass
    ticks2 = iter(range(10 ** 6))
    clk3 = g1.Clock(now=lambda: float(next(ticks2)) * 1000.0, caps=gate.WALL_CAPS_S, global_cap=gate.GLOBAL_CAP_S,
                    memory=lambda: None)
    try:
        for _ in range(10):
            clk3.check()
        check(False, "the global cap was not enforced")
    except g1.CapStop as exc:
        check("60-minute" in str(exc), str(exc))
    return {"episodes": len(eps)}


def unit_replay_accounting(out: Path) -> Dict[str, Any]:
    import m7u2_gate as gg
    import m7u3_gate as gate

    n = 24
    outcomes = {"PF": [k in (1, 2, 3) for k in range(n)], "PR": [k < 10 for k in range(n)],
                "RC": [k == 5 for k in range(n)], "SR": [k in (3, 7) for k in range(n)]}
    sel = gate.replay_selection(outcomes)
    check(sel == [("PF", 1), ("PF", 2), ("PF", 3)] + [("PR", k) for k in range(10)] + [("RC", 5), ("SR", 3), ("SR", 7)],
          f"selection {sel}")
    all_wins = {a: [True] * n for a in gate.ARMS}
    check(len(gate.replay_selection(all_wins)) * g3.BUDGET == gate.TICK_BUDGET["replays"] == 96 * 128,
          "replays can never be cut by the tick cap (budget = trials x 128)")
    rows = np.zeros((5, us.N_FIELDS))
    exp = {"rows": rows, "reach_tick": 4, "native_action_digest": "d"}
    good = {"sent": 4, "rows": rows.copy(), "reach_tick": 4, "native_action_digest": "d"}
    check(gg.check_replay(good, exp, [[0, 0]] * 4)["ok"], "an exact replay was rejected")
    r2_ = rows.copy()
    r2_[3, F["y"]] = 1.0
    for bad, why in ((dict(good, rows=r2_), "a differing row"), (dict(good, reach_tick=3), "a differing reach tick"),
                     (dict(good, native_action_digest="e"), "a differing action digest"), (dict(good, sent=3), "a short replay")):
        check(not gg.check_replay(bad, exp, [[0, 0]] * 4)["ok"], f"{why} was accepted")
    return {"selection": len(sel)}


def _tiny_gate(out: Path, name: str, *, n_train: int = 10, n_pool: int = 40, steps: int = 3, **over: Any):
    """run_gate on the synthetic stand-in with tiny entry sets and a few refit steps (a stop-behaviour harness)."""
    import m7u3_gate as gate
    import m7u_gate as g1

    row0, ref, fz, rt = _gate_world(out / f"w_{name}")
    src = fake_src(out / "src_shared")
    vecs: List[Any] = []
    singles: List[Any] = []

    def venv_factory(root, run_id, role, settings):                      # noqa: ANN001
        v = fake_vec(Path(root), 5, horizon=settings)
        vecs.append(v)
        return v

    def env_factory(root, run_id, role, settings):                       # noqa: ANN001
        s = fake_single(Path(root), horizon=3600)
        singles.append(s)
        return s

    def artifact_words(d):                                               # noqa: ANN001
        for st in [t for v in vecs for _tw, t in v.stacks] + [s.tracker for s in singles]:
            eid = Path(d).name
            if eid in st.words and str(st.artifact_root / eid) == str(d):
                return [tuple(w) for w in st.words[eid]]
        raise KeyError(d)

    p1 = _fake_p1(out / f"p1_{name}", 40)
    kw = dict(settings=3600, train_settings=192, goal_settings=128, src=src, frozen=fz, retrain=rt, n_candidates=17, ref=ref,
              row0=row0, artifact_words=artifact_words, n_workers=5, m7u2_rec={}, m7u2_pool=[], refit_steps=steps,
              pin_track=None, check_pins=False, train_entries=[f"t{i:03d}" for i in range(n_train)],
              goal_entries=[f"g{i:03d}" for i in range(n_pool)])
    kw.update(over)
    return gate, g1, kw, p1, (venv_factory, env_factory)


def _fake_p1(root: Path, n_words: int) -> List[Dict[str, Any]]:
    import m7u_gate as g1

    single = fake_single(root, horizon=3600)
    words = [list(w) for w in up.rc_words("m7u3|test|p1", 17, n_words)]
    row0 = fake_row0(root)
    start = [None if np.isnan(v) else float(v) for v in row0]
    e = {"entry": "p1_fake", "kind": "trial", "t": 0, "budget": n_words, "goal": [1e9, 1e9], "prefix": [],
         "expected_start_row": start, "words": words}
    rr = g1.run_single(single, [e], phase="p1", ledger=ledger(p1=n_words), clock=g1.Clock(memory=lambda: None))[0]
    return [dict(e, expected={"rows": rr["rows"], "reach_tick": rr["reach_tick"],
                              "native_action_digest": rr["native_action_digest"]})]


def unit_gate_stops(out: Path) -> Dict[str, Any]:
    """run_gate: a P1 mismatch is INVALID before the training pool; a refit manifest violation, a vocabulary overrun and
    an optimizer constructed after the refit are INVALID; too few goals is INCOMPLETE with exactly the pools consumed;
    the wall cap of the training pool or of the refit is INCOMPLETE."""
    import m7u_model as um

    gate, g1, kw, p1, (vf, ef) = _tiny_gate(out, "a")
    bad_p1 = [dict(p1[0], expected=dict(p1[0]["expected"], reach_tick=7))]
    led = lambda: g1.Ledger(dict(gate.TICK_BUDGET, p1=40, train_pool=10 * 192, goal_pool=40 * 128))   # noqa: E731
    clock = lambda **c: g1.Clock(caps=dict(gate.WALL_CAPS_S, **c), memory=lambda: None)                  # noqa: E731
    st = gate.run_gate(root=out / "g1", venv_factory=vf, env_factory=ef, clock=clock(), p1_entries=bad_p1, ledger=led(), **kw)
    check(st["decision"]["outcome"] == "INVALID" and st["ledger"]["used"]["train_pool"] == 0, "P1 mismatch")
    # too few goals (a goal pool of 20 episodes cannot supply 24 goals, one per episode): INCOMPLETE, pools consumed
    gate_b, g1b, kwb, p1b, (vfb, efb) = _tiny_gate(out, "b", n_pool=20)
    st2 = gate_b.run_gate(root=out / "g2", venv_factory=vfb, env_factory=efb, clock=clock(), p1_entries=p1b, ledger=led(), **kwb)
    used = st2["ledger"]["used"]
    check(st2["decision"]["outcome"] == "INCOMPLETE" and "goal availability" in st2["decision"]["reason"],
          f"insufficient goals: {st2['decision']} {st2['integrity']['problems'][:2]}")
    check(used["train_pool"] <= 10 * 192 and used["eval_control"] == 0 and used["replays"] == 0, f"ticks after a stop: {used}")
    check(st2["phases"]["train_pool"]["episodes"] == 10 and st2["phases"]["goal_pool"]["episodes"] == 20
          and "refit" in st2["phases"] and st2["phases"]["refit"]["steps"] == 3, "pools or refit extended / shortened")
    # the refit's digests were recorded before the goal pool and the optimizer registry shows exactly one optimizer
    check(st2["refit_model"]["parameter_digest"] and len(st2["phases"]["refit"]["optimizers"]) == 1
          and st2["phases"]["refit"]["optimizers"][0]["all_model_params"], "refit record")
    check((out / "g2" / "_gate" / "model_refit.pt").is_file() and (out / "g2" / "_gate" / "refit.json").is_file(), "refit files")
    # a training-pool episode that is also an M7u2 pool episode: INVALID before the refit
    gate_c, g1c, kwc, p1c, (vfc, efc) = _tiny_gate(out, "c")
    kwc["m7u2_pool"] = [{"episode_id": "train_pool_w0_0001", "rows": None, "words": None, "fell": False}]
    st3 = gate_c.run_gate(root=out / "g3", venv_factory=vfc, env_factory=efc, clock=clock(), p1_entries=p1c, ledger=led(), **kwc)
    check(st3["decision"]["outcome"] == "INVALID" and "manifest" in " ".join(st3["integrity"]["problems"]),
          f"manifest violation: {st3['decision']} {st3['integrity']['problems'][:2]}")
    check("refit" not in st3["phases"], "the refit ran after a manifest violation")
    # a vocabulary overrun is INVALID (nothing merged silently)
    gate_d, g1d, kwd, p1d, (vfd, efd) = _tiny_gate(out, "d")
    caps = um.S_CAP
    um.S_CAP = 2
    try:
        st4 = gate_d.run_gate(root=out / "g4", venv_factory=vfd, env_factory=efd, clock=clock(), p1_entries=p1d, ledger=led(), **kwd)
    finally:
        um.S_CAP = caps
    check(st4["decision"]["outcome"] == "INVALID" and "cap" in " ".join(st4["integrity"]["problems"]),
          f"vocabulary overrun: {st4['decision']} {st4['integrity']['problems'][:2]}")
    # an optimizer constructed after the refit (here: by the goal-pool factory) is an integrity stop
    gate_e, g1e, kwe, p1e, (vfe, efe) = _tiny_gate(out, "e")
    import torch

    def vf_opt(root, run_id, role, settings):                            # noqa: ANN001
        if "goal_pool" in str(root):
            torch.optim.SGD([torch.zeros(1, requires_grad=True)], lr=0.1)
        return vfe(root, run_id, role, settings)

    st5 = gate_e.run_gate(root=out / "g5", venv_factory=vf_opt, env_factory=efe, clock=clock(), p1_entries=p1e, ledger=led(), **kwe)
    check(st5["decision"]["outcome"] == "INVALID" and "optimizer" in " ".join(st5["integrity"]["problems"]),
          f"optimizer after the refit: {st5['decision']} {st5['integrity']['problems'][:2]}")
    # wall caps: the training pool and the refit end INCOMPLETE
    gate_f, g1f, kwf, p1f, (vff, eff) = _tiny_gate(out, "f")
    ticks = iter(range(10 ** 7))
    st6 = gate_f.run_gate(root=out / "g6", venv_factory=vff, env_factory=eff, p1_entries=p1f, ledger=led(),
                          clock=g1.Clock(now=lambda: float(next(ticks)) * 0.01, caps=dict(gate.WALL_CAPS_S, train_pool=2),
                                         memory=lambda: None), **kwf)
    check(st6["decision"]["outcome"] == "INCOMPLETE" and "wall cap" in st6["decision"]["reason"], f"wall cap {st6['decision']}")
    gate_g, g1g, kwg, p1g, (vfg, efg) = _tiny_gate(out, "g", steps=2000)
    ticks2 = iter(range(10 ** 8))
    st7 = gate_g.run_gate(root=out / "g7", venv_factory=vfg, env_factory=efg, p1_entries=p1g, ledger=led(),
                          clock=g1.Clock(now=lambda: float(next(ticks2)) * 0.0005, caps=dict(gate.WALL_CAPS_S, refit=0.5),
                                         memory=lambda: None), **kwg)
    check(st7["decision"]["outcome"] == "INCOMPLETE" and "refit" in st7["decision"]["reason"], f"refit wall cap {st7['decision']}")
    return {"p1": st["decision"]["outcome"], "availability": st2["decision"]["reason"][:70],
            "manifest": st3["decision"]["outcome"], "vocab": st4["decision"]["outcome"],
            "optimizer_after_refit": st5["decision"]["outcome"], "wall": st6["decision"]["reason"][:50],
            "refit_wall": st7["decision"]["reason"][:50]}


def unit_diagnostics_wiring(out: Path) -> Dict[str, Any]:
    """The diagnostics on synthetic episodes with the real models: shapes, determinism, cross attribution, paired tables."""
    import m7u3_analysis as an
    import m7u_model as um

    row0, ref, fz, rt = _gate_world(out)
    eps = fake_episodes(out / "eps", [f"e{i}" for i in range(10)], n_workers=5, horizon=128)
    pool = [{"rows": e["rows"], "words": e["words"]} for e in sorted(eps, key=lambda e: e["entry"])]
    s1 = an.strict_open_loop(fz.model, fz.ctx, pool)
    s1b = an.strict_open_loop(fz.model, fz.ctx, pool)
    check(all(np.allclose(s1[h]["error"], s1b[h]["error"]) for h in an.HORIZONS), "strict open loop is not deterministic")
    check(all(len(s1[h]["error"]) == len(pool) for h in an.HORIZONS), "all 128-word episodes enter every horizon")
    short = {"rows": pool[0]["rows"][:50], "words": pool[0]["words"][:49]}
    s2 = an.strict_open_loop(fz.model, fz.ctx, [short] + pool)
    check(s2[16]["index"][0] == 0 and 0 not in s2[64]["index"] and 0 not in s2[96]["index"],
          "an episode shorter than the horizon must be excluded at that horizon only")
    # witness acceptance, paired tables and the attribution wiring on a real synthetic trial
    goals, _r0, trials_eps = None, None, None
    air = [(e, t) for e in eps for t in range(g3.TAU_MIN, 97) if e["rows"][t, F["ga"]] == 1]
    check(air, "no airborne synthetic points")
    e, t = air[0]
    g = g2.Goal(k=0, entry=e["entry"], episode_id="x", tau=t, x=float(e["rows"][t, F["x"]]), y=float(e["rows"][t, F["y"]]),
                rise=0.0, ref_reaching=0, witness=[tuple(int(v) for v in w) for w in e["words"][:t]])
    w = an.witness_acceptance(fz.model, fz.ctx, [g], row0)
    check(w["n"] == 1 and len(w["accepted"]) == 1 and len(w["members_predicting"]) == 1, f"witness {w}")
    tab = an.paired_table([True, True, False, False], [True, False, True, False])
    check(tab == {"both": 1, "a_only": 1, "b_only": 1, "neither": 1}, f"paired table {tab}")
    trial = {"rows": e["rows"], "words": e["words"], "goal": (g.x, g.y), "decisions": [0, 4, 8, 12], "reached": False}
    a1 = an.attribution(fz.model, fz.ctx, trial)
    check(a1["class"] in ("MODEL", "PLAN"), f"attribution {a1}")
    cross = an.cross_attribution((fz.model, fz.ctx), (rt.model, rt.ctx), {0: trial}, {0: {"class": "MODEL"}}, [False])
    check(cross["src_model_failures"] == 1 and cross["per_failure"][0]["goal_k"] == 0, f"cross attribution {cross}")
    summ = an.attribution_summary({0: {"class": "MODEL"}, 1: {"class": "PLAN"}, 2: {"class": "PREDICTED"}}, {0: False, 1: True},
                                  [False, False, True])
    check(summ["failures"] == 2 and summ["MODEL"] == 1 and summ["failures_without_flag"] == 1 and summ["PREDICTED"] == 1,
          f"summary {summ}")
    # no function of the analysis module trains or builds an optimizer
    text = (REPO_ROOT / "rl" / "m7u3_analysis.py").read_text(encoding="utf-8")
    for bad_call in ("um.train(", ".backward(", "um.losses(", "optim.", ".step()", "train_loop"):
        check(bad_call not in text, f"m7u3_analysis.py contains {bad_call!r}")
    return {"attribution": a1["class"]}


def unit_approval_refusal_and_acceptance(out: Path) -> Dict[str, Any]:
    """The production approval_status() on an ISOLATED temporary record (a short system temp path, removed afterwards);
    the repository's record is never touched."""
    import m7u3_gate as gate

    with tempfile.TemporaryDirectory(prefix="m7u3a_") as d:
        return _approval_cases(gate, Path(d))


def _approval_cases(gate: Any, root: Path) -> Dict[str, Any]:
    real, real_root = gate.APPROVAL, gate.REPO_ROOT
    real_before = hashlib.sha256(real.read_bytes()).hexdigest() if real.is_file() else None
    tmp = root / "docs" / real.name
    tmp.parent.mkdir(parents=True)
    ident = gate.identity()
    res: Dict[str, Any] = {}

    def status(rec: Optional[Mapping[str, Any]]):
        if rec is not None:
            tmp.write_text(json.dumps(rec, default=str), encoding="utf-8")
        return gate.approval_status()

    gate.APPROVAL, gate.REPO_ROOT = tmp, root
    try:
        ok, why = status(None)
        check(not ok and "no approval record" in why, f"missing: {why}")
        res["missing"] = why
        ok, why = status(dict(ident, approval="PENDING"))
        check(not ok, "PENDING accepted")
        altered = {"tick_budget": dict(ident["tick_budget"], total=197_840), "n_candidates": 32, "n_goals": 30,
                   "frozen_model": dict(ident["frozen_model"], parameter_digest="0" * 64),
                   "retrain_model": dict(ident["retrain_model"], parameter_digest="0" * 64),
                   "refit": dict(ident["refit"], steps=4500), "global_cap_s": 7200, "wall_caps_s": dict(ident["wall_caps_s"], refit=9000),
                   "memory_caps_mb": dict(ident["memory_caps_mb"], tree_private=12000), "rule_sha256": "0" * 64,
                   "training_pool": [720, 192], "goal_pool": [540, 160], "non_overlap_span": 450.0,
                   "stream_seeds": {"train": 1, "pool": 2, "eval": 4}, "arms": ["PF", "PR", "RC"],
                   "m7u2_sources": dict(ident["m7u2_sources"], m7u2_pool_sha256="0" * 64),
                   "code": dict(ident["code"], **{"rl/m7u_planner.py": "0" * 64}),
                   "d_records": {"folders": ident["d_records"]["folders"], "digest": "0" * 64}}
        for key, value in altered.items():
            ok, why = status(dict(ident, approval="APPROVED test", **{key: value}))
            check(not ok and ("code:" if key == "code" else key) in why, f"altered {key} accepted: {why}")
            res[f"altered_{key}"] = why[:80]
        tmp.write_text("{not json", encoding="utf-8")
        try:
            gate.approval_status()
            check(False, "an unreadable record was accepted")
        except ValueError as exc:
            res["unreadable"] = type(exc).__name__
        ok, why = status(dict(ident, approval="APPROVED test"))
        check(ok and why == "approved", f"valid record refused: {why}")
        res["valid"] = why
    finally:
        gate.APPROVAL, gate.REPO_ROOT = real, real_root
    real_after = hashlib.sha256(real.read_bytes()).hexdigest() if real.is_file() else None
    check(real_after == real_before and gate.APPROVAL == real, "the repository approval path was touched")
    res["repository_record_present"] = real_before is not None
    return res


def unit_accounting(out: Path) -> Dict[str, Any]:
    """The ledger and the budget projection of the decisions document (pool 540 x 192), with the pessimistic column."""
    import m7u3_gate as gate

    b = gate.TICK_BUDGET
    check(b == {"p1": 463, "train_pool": 103_680, "goal_pool": 69_120, "eval_control": 12_288, "replays": 12_288,
                "total": 197_839}, f"ledger {b}")
    check(b["p1"] == 171 + 183 + 49 + 60, "P1 = the four pinned artifacts")
    check(gate.GLOBAL_CAP_S == 4500 and gate.MEMORY_CAPS_MB == {"main_private": 3072, "tree_private": 9216,
                                                                "tree_working_set": 4096, "system_available_min": 1024,
                                                                "system_commit_free_min": 2048}, "caps")
    check(gate.N_CANDIDATES == 64 and gate.READINESS["probe_p95_max_s"] == 0.5 and gate.READINESS["min_available_mb"] == 4096
          and gate.READINESS["min_commit_free_mb"] == 10240 and gate.READINESS["train_probe_median_max_s"] == 0.10, "readiness")
    proj = wall_projection()
    for k, v in proj["pessimistic_s"].items():
        check(v <= gate.WALL_CAPS_S[k], f"pessimistic {k} {v:.0f} s > cap {gate.WALL_CAPS_S[k]} s")
    check(proj["pessimistic_total_s"] <= gate.GLOBAL_CAP_S, f"pessimistic total {proj['pessimistic_total_s']:.0f} s > {gate.GLOBAL_CAP_S} s")
    check(proj["projected_total_s"] < proj["pessimistic_total_s"], "projection order")
    return proj


def wall_projection() -> Dict[str, Any]:
    """Wall-time projections for the decisions-document configuration (training pool 540 x 192). Per-episode model per
    worker: a 2.24 s restart plus its ticks at 108.9 ticks per second (fitted to m7u1's collection, 92 episodes / 272,145
    ticks / 541.3 s, and the M7u2 pool, 360 x 128 / 246.0 s; both reproduced within 0.3 s)."""
    import m7u3_gate as gate

    per_worker_train = g3.TRAIN_EPISODES // gate.N_WORKERS
    per_worker_goal = g3.GOAL_EPISODES // gate.N_WORKERS
    tr = per_worker_train * (2.24 + g3.TRAIN_TICKS / 108.9)
    gp = per_worker_goal * (2.24 + g3.GOAL_TICKS / 108.9)
    proj = {"p1": 20.0, "train_pool": tr, "refit": 6000 * 0.058 + 40.0, "goal_pool": gp, "goals": 1.0,
            "evaluation": 613.0, "replays_analysis": 280.0}
    pess = {"p1": 40.0, "train_pool": tr * 1.35, "refit": 6000 * gate.READINESS["train_probe_median_max_s"] + 35.0,
            "goal_pool": gp * 1.35, "goals": 5.0, "evaluation": 1220.0, "replays_analysis": 534.0}
    return {"projected_s": {k: round(v) for k, v in proj.items()}, "projected_total_s": round(sum(proj.values())),
            "pessimistic_s": {k: round(v) for k, v in pess.items()}, "pessimistic_total_s": round(sum(pess.values())),
            "global_cap_s": gate.GLOBAL_CAP_S, "pessimistic_margin_s": round(gate.GLOBAL_CAP_S - sum(pess.values())),
            "assumptions": {"pools": "+35 %", "refit": "training at the readiness ceiling 0.10 s/step + 35 s build / load",
                            "evaluation": "<= 2,304 planning decisions at 0.5 s, unbatched, + restarts",
                            "replays_analysis": "48 success replays at 8 s + 150 s of forward-pass diagnostics"}}


def unit_import_isolation(out: Path) -> Dict[str, Any]:
    code = ("import sys; sys.path.insert(0, 'rl'); import m7u3_goals, m7u3_rule; "
            "bad = [m for m in ('torch', 'battleship_client', 'battleship_env', 'btt_parallel', 'm7u_worker', 'm7u_model') "
            "if m in sys.modules]; print(bad)")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO_ROOT)
    check(r.returncode == 0 and r.stdout.strip() == "[]", f"goal / rule modules import {r.stdout.strip()} {r.stderr[-200:]}")
    import m7u3_gate as gate

    check(gate.m7u1_files_equal_head() == [], f"an m7u1 file differs from HEAD: {gate.m7u1_files_equal_head()}")
    check(gate.m7u2_files_unchanged() == [], f"an M7u2 file differs from its approved hash: {gate.m7u2_files_unchanged()}")
    # only new files: nothing tracked is modified by m7u3
    st = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=REPO_ROOT).stdout.splitlines()
    tracked_changed = [ln for ln in st if not ln.startswith("??")]
    check(tracked_changed == [], f"tracked files modified: {tracked_changed[:3]}")
    return {"isolated": True, "m7u1_files_unchanged": True, "m7u2_files_unchanged": True}


def unit_accuracy_equals_m7u1_analysis(out: Path) -> Dict[str, Any]:
    """`m7u3_analysis.accuracy` (bounded memory, batched open loop) equals m7u1's `heldout_accuracy` on RECORDED data: m7u1's 12
    held-out episodes and the 360 preserved M7u2 pool episodes, for the frozen model; and it reproduces the recorded
    figures (m7u1 held-out 121 / 290 / 645; M7u2 early window 106 / 298 / 559). Forward passes only."""
    import m7u2_gate as gg
    import m7u3_analysis as an
    import m7u3_gate as gate
    import m7u3_refit as rf
    import m7u_analysis as ua
    import m7u_model as um

    src, _row0, _ref, fz = m7u1()
    _train, held = rf.m7u1_split(src)
    rec2 = gate.load_m7u2_records()
    pool = gate.m7u2_pool_episodes(rec2)
    eps2 = [um.Episode(episode_id=str(e["entry"]), rows=e["rows"], words=e["words"], fell=bool(e["fell"])) for e in pool]
    res: Dict[str, Any] = {}
    for name, eps, recorded in (("m7u1_heldout", held, json.loads((gate.M7U1 / "state.json").read_text(encoding="utf-8"))
                                 ["phases"]["diagnostics"]["heldout_accuracy"]),
                                ("m7u2_pool", eps2, rec2["state"]["phases"]["diagnostics"]["pool_accuracy"])):
        t0 = time.perf_counter()
        ref_out = ua.heldout_accuracy(fz.model, fz.ctx, eps)
        t1 = time.perf_counter()
        new = an.accuracy(fz.model, fz.ctx, eps)
        t2_ = time.perf_counter()
        check(new["transitions"] == ref_out["transitions"] == recorded["transitions"], f"{name}: transitions")
        for k, tol in (("pos_err_median", 2e-3), ("pos_err_p99", 5e-2), ("status_acc", 2e-4)):
            check(abs(new[k] - ref_out[k]) <= tol and abs(new[k] - recorded[k]) <= max(tol, 2e-3), f"{name}: {k} {new[k]} vs {ref_out[k]} vs {recorded[k]}")
        for h in ("16", "32", "64"):
            for q in ("median", "p90"):
                check(abs(new["open_loop"][h][q] - ref_out["open_loop"][h][q]) <= 0.05
                      and abs(new["open_loop"][h][q] - recorded["open_loop"][h][q]) <= 0.05,
                      f"{name}: open loop {h} {q} {new['open_loop'][h][q]} vs {ref_out['open_loop'][h][q]} vs {recorded['open_loop'][h][q]}")
        check(set(new["per_class"]) == set(ref_out["per_class"]) and all(
            new["per_class"][c]["n"] == ref_out["per_class"][c]["n"] and abs(new["per_class"][c]["status_acc"] - ref_out["per_class"][c]["status_acc"]) <= 5e-4
            for c in new["per_class"]), f"{name}: per-class accuracy")
        res[name] = {"reference_s": round(t1 - t0, 1), "accuracy_s": round(t2_ - t1, 1), "open_loop": new["open_loop"]}
    return res


UNITS: Dict[str, Callable[[Path], Dict[str, Any]]] = {
    "unit_rule": unit_rule,
    "unit_model_reading_and_replication": unit_model_reading_and_replication,
    "unit_goal_selection_rules": unit_goal_selection_rules,
    "unit_selection_on_m7u2_pool": unit_selection_on_m7u2_pool,
    "unit_streams": unit_streams,
    "unit_refit_pipeline": unit_refit_pipeline,
    "unit_refit_manifest": unit_refit_manifest,
    "unit_prep_records": unit_prep_records,
    "unit_frozen_and_records": unit_frozen_and_records,
    "unit_strict_from_reset_on_m7u2_pool": unit_strict_from_reset_on_m7u2_pool,
    "unit_accuracy_equals_m7u1_analysis": unit_accuracy_equals_m7u1_analysis,
    "unit_tree_memory_and_clock": unit_tree_memory_and_clock,
    "unit_readiness": unit_readiness,
    "unit_tick0_drive": unit_tick0_drive,
    "unit_scrambled_scoring": unit_scrambled_scoring,
    "unit_pools_and_caps": unit_pools_and_caps,
    "unit_replay_accounting": unit_replay_accounting,
    "unit_gate_stops": unit_gate_stops,
    "unit_diagnostics_wiring": unit_diagnostics_wiring,
    "unit_approval_refusal_and_acceptance": unit_approval_refusal_and_acceptance,
    "unit_accounting": unit_accounting,
    "unit_import_isolation": unit_import_isolation,
}


def e2e(out: Path) -> Dict[str, Any]:
    """run_gate through EVERY phase at production counts over the synthetic stand-in: P1 (four synthetic entries), 540
    training-pool episodes x <= 192 words, the REAL refit pipeline on 80 synthetic base + 540 pool episodes (a reduced
    step count: the step count is data-size independent and measured separately), 540 goal-pool episodes x <= 128 words,
    24 goals x 4 arms from the normal reset, every success replayed, every diagnostic, the rule. N = 17 candidates for
    speed; the REAL frozen ensemble and P_retrain plan / roll (their clock track rebuilt from synthetic episodes). It
    exercises the glue only; its outcome says nothing about Mario."""
    import m7u3_gate as gate
    import m7u_gate as g1

    t_start = time.perf_counter()
    row0, ref, fz, rt = _gate_world(Path(out) / "world")
    ref_eps = fake_episodes(Path(out) / "ref92", [f"r{i:03d}" for i in range(g2.REF_EPISODES)], n_workers=5)
    ref = g2.Reference([(e["entry"], e["rows"], e["termination_reason"] == "native_failure") for e in ref_eps])
    row0 = ref_eps[0]["rows"][0]
    fz = fake_frozen(Path(out) / "world")
    rt = fake_retrain(out, fz)
    src = fake_src(Path(out) / "src_shared")
    vecs: List[Any] = []
    singles: List[Any] = []

    def venv_factory(root, run_id, role, settings):                      # noqa: ANN001
        v = fake_vec(Path(root), 5, horizon=settings)
        vecs.append(v)
        return v

    def env_factory(root, run_id, role, settings):                       # noqa: ANN001
        s = fake_single(Path(root), horizon=3600)
        singles.append(s)
        return s

    def artifact_words(d):                                               # noqa: ANN001
        for st in [t for v in vecs for _tw, t in v.stacks] + [s.tracker for s in singles]:
            eid = Path(d).name
            if eid in st.words and str(st.artifact_root / eid) == str(d):
                return [tuple(w) for w in st.words[eid]]
        raise KeyError(d)

    p1 = _fake_p1(Path(out) / "p1src", 171)
    m2 = [{"entry": f"c{i:03d}", "episode_id": f"m7u2_syn_{i}", "rows": e["rows"], "words": e["words"], "fell": False}
          for i, e in enumerate(ref_eps[:30])]
    # the machine-wide minimums (available memory / free commit) protect the machine the REAL gate runs on and are tested in
    # unit_tree_memory_and_clock; this glue test keeps the process caps and only records the machine's minimums
    sampler = gate.TreeSampler(Path(out) / "gate" / "_gate" / "memory_tree.jsonl", interval=5.0,
                               caps=dict(gate.MEMORY_CAPS_MB, system_available_min=0, system_commit_free_min=0)).start()
    clock = gate.Clock3(caps=gate.WALL_CAPS_S, global_cap=10 ** 6, memory=g1.private_mb, memory_cap_mb=gate.MEMORY_CAP_MB,
                        sampler=sampler)
    steps = int(os.environ.get("M7U3_E2E_REFIT_STEPS", "60"))
    try:
        st = gate.run_gate(settings=3600, train_settings=g3.TRAIN_TICKS, goal_settings=g3.GOAL_TICKS, root=Path(out) / "gate",
                           venv_factory=venv_factory, env_factory=env_factory, clock=clock, src=src, frozen=fz, retrain=rt,
                           n_candidates=17, p1_entries=p1, artifact_words=artifact_words, ref=ref, row0=row0, m7u2_rec={},
                           m7u2_pool=m2, refit_steps=steps, pin_track=None, check_pins=False)
    finally:
        mem = sampler.stop()
    d = st["decision"]
    check(d["outcome"] in ("PASS", "NULL", "INCONCLUSIVE"), f"e2e decision {d.get('outcome')}: {d.get('reason')} "
          f"{st['integrity']['problems'][:3]}")
    used = st["ledger"]["used"]
    check(st["ledger"]["total"] <= gate.TICK_BUDGET["total"] and used["p1"] == 171, f"ledger {used}")
    check(used["replays"] == sum(r["sent"] for r in st["phases"]["replays"]) <= 12288, "replay accounting")
    check(all(r["ok"] for r in st["phases"]["replays"]), "a replay was not exact")
    check(st["phases"]["train_pool"]["episodes"] == 540 and st["phases"]["goal_pool"]["episodes"] == 540
          and st["phases"]["goals"]["registered"] == 24, "pools / goals")
    check(st["phases"]["train_pool"]["ticks"] <= 540 * 192 and st["phases"]["goal_pool"]["ticks"] <= 540 * 128, "pool ticks")
    check(not r3.scope_problems(d["summary"]), "summary wording")
    check(gate.gg.parameter_digest(fz.model) == gate.PIN["parameter_digest"], "the frozen model changed")
    check(gate.gg.parameter_digest(rt.model) == gate.retrain_pins()["parameter_digest"], "P_retrain changed")
    gd = Path(out) / "gate" / "_gate"
    goals = json.loads((gd / "goals.json").read_text(encoding="utf-8"))
    check(len(goals["goals"]) == 24 and len({g["entry"] for g in goals["goals"]}) == 24
          and goals["record"]["independence"]["overlapping_pairs"] == [] and goals["record"]["independence"]["n_pairs_checked"] == 276,
          "goal definitions")
    refit_rec = json.loads((gd / "refit.json").read_text(encoding="utf-8"))
    check(refit_rec["n_base"] == 80 and refit_rec["n_pool"] == 540 and refit_rec["steps"] == steps
          and len(refit_rec["optimizers"]) == 1, "refit record")
    # a re-derivation of the goals from the stored pool sidecars reproduces the stored digest, with no overlap
    import m7u_worker as uw

    gp = json.loads((gd / "goal_pool.json").read_text(encoding="utf-8"))
    pool = []
    for e in gp["episodes"]:
        side = uw.read_sidecar(g1.resolve(e["artifact_dir"]))
        pool.append({"entry": e["entry"], "episode_id": e["episode_id"], "rows": side["rows"], "words": side["words"],
                     "fell": e["termination_reason"] == "native_failure"})
    again = g3.select_goals(pool, ref, row0)
    check(g3.goals_digest(again["goals"]) == goals["digest"], "goals do not re-derive")
    vr = gate.verify_run(Path(out) / "gate", ref=ref, row0=row0, retrain_digest=gate.retrain_pins()["parameter_digest"])
    check(vr["ok"] and vr["goals"] == 24 and vr["trial_files_checked"] == 96, f"verify_run {vr}")
    # the post-run verification catches a tampered goal digest, a tick-0 violation and a changed refit file
    import shutil

    tamper = Path(out) / "tampered"
    shutil.copytree(gd, tamper / "_gate")
    g = json.loads((tamper / "_gate" / "goals.json").read_text(encoding="utf-8"))
    g["digest"] = "0" * 64
    (tamper / "_gate" / "goals.json").write_text(json.dumps(g), encoding="utf-8")
    bad = gate.verify_run(tamper, ref=ref, row0=row0, retrain_digest=gate.retrain_pins()["parameter_digest"])
    check(not bad["ok"] and any("re-derive" in p for p in bad["problems"]), f"tampered goals not caught: {bad}")
    shutil.copy(gd / "goals.json", tamper / "_gate" / "goals.json")
    with open(tamper / "_gate" / "model_refit.pt", "ab") as fh:
        fh.write(b"x")
    bad2 = gate.verify_run(tamper, ref=ref, row0=row0, retrain_digest=gate.retrain_pins()["parameter_digest"])
    check(not bad2["ok"] and any("refit file" in p for p in bad2["problems"]), f"tampered refit not caught: {bad2}")
    shutil.rmtree(tamper)
    trial_files = sorted((gd / "trials").glob("*.npz"))
    check(len(trial_files) == 96, f"{len(trial_files)} trial evidence files")
    for f in trial_files:
        with np.load(f) as z:
            meta = json.loads(z["meta"].tobytes().decode("utf-8"))
            check(meta["t"] == 0 and np.array_equal(z["rows"][0], row0, equal_nan=True), f"{f.name}: not a tick-0 start")
            check(("scores" in z.files) == meta["model_evaluated"], f"{f.name}: predictions")
            check(meta["model"] == {"PF": "frozen", "PR": "refit", "SR": "refit"}.get(meta["arm"]), f"{f.name}: model label")
    diag = st["phases"]["diagnostics"]
    check(not diag["errors"], f"diagnostic errors: {diag['errors']}")
    for key in ("D1_witness", "D2a_goal_pool", "D2b_m7u2_pool", "D3_attribution", "D4_cross_attribution", "D5_continuity", "D6",
                "D8_coverage", "D9_refit_training"):
        check(diag.get(key) is not None, f"missing diagnostic {key}")
    mem_rows = [json.loads(line) for line in (gd / "memory_tree.jsonl").read_text().splitlines()]
    return {"decision": {k: d.get(k) for k in ("outcome", "n", "PR_vs_PF", "PR_vs_RC", "PR_vs_SR", "replication_readout",
                                                "model_reading")},
            "ledger": used, "phase_wall_s": st["clock"]["phase_wall_s"], "replays": len(st["phases"]["replays"]),
            "refit": {k: refit_rec[k] for k in ("steps", "transitions", "heldout_transitions", "vocab", "build_wall_s", "wall_s")},
            "peak_main_private_mb": round(clock.peak_mb, 1), "tree_memory": mem, "memory_samples": len(mem_rows),
            "goal_record": {"eligible_points": st["phases"]["goals"]["eligible_points"],
                            "episodes_with_a_goal": st["phases"]["goals"]["episodes_with_a_goal"],
                            "passed_over": len(st["phases"]["goals"]["passed_over_overlapping_taus"]),
                            "skipped": len(st["phases"]["goals"]["skipped_episodes"]),
                            "min_pairwise_chebyshev": st["phases"]["goals"]["independence"]["min_pairwise_chebyshev"],
                            "registered": st["phases"]["goals"]["registered"]},
            "wall_s": round(time.perf_counter() - t_start, 1)}


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["unit", "e2e"])
    ap.add_argument("--out", default=None)
    ap.add_argument("--only", default=None)
    a = ap.parse_args(argv)
    out = Path(a.out) if a.out else Path(tempfile.mkdtemp(prefix="m7u3t_"))
    out.mkdir(parents=True, exist_ok=True)
    results: Dict[str, Any] = {}
    failures = 0
    if a.mode == "e2e":
        t = time.perf_counter()
        try:
            results["e2e"] = {"ok": True, "result": e2e(out), "wall_s": round(time.perf_counter() - t, 1)}
        except Exception:                      # noqa: BLE001
            failures += 1
            results["e2e"] = {"ok": False, "error": traceback.format_exc()[-3000:]}
    else:
        for name, fn in UNITS.items():
            if a.only and a.only != name:
                continue
            (out / name).mkdir(parents=True, exist_ok=True)
            t = time.perf_counter()
            try:
                results[name] = {"ok": True, "result": fn(out / name), "wall_s": round(time.perf_counter() - t, 1)}
            except Exception:                  # noqa: BLE001
                failures += 1
                results[name] = {"ok": False, "error": traceback.format_exc()[-3000:]}
    (out / f"m7u3_{a.mode}.json").write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    n_ok = sum(1 for r in results.values() if r["ok"])
    print(f"{n_ok} / {len(results)} passed ({a.mode}); report {out / f'm7u3_{a.mode}.json'}")
    for n, r in results.items():
        if not r["ok"]:
            print(f"FAILED {n}:\n{r['error']}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
