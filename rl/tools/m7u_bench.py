#!/usr/bin/env python3
"""M7u preparation: benchmark `m7u_bench_v1` (zero native ticks; nothing launched, replayed or trained on data).

Measures, on the intended CPU configuration (6 torch threads), with the pinned architecture at its vocabulary caps and
SEEDED RANDOM WEIGHTS that are discarded (never saved):
  1. complete planning decisions: candidate generation for every controller + featurisation + E x N x H rollouts +
     scoring + choice, median / p95 over timed decisions, at concurrency 1 and batched 5, for N = 64 and N = 32;
  2. featurisation-only latency of one rollout step's batch;
  3. training step time (batch 1,024 x E = 3, Adam) on SYNTHETIC tensors of the cached-input shape;
  4. transition-building rate (featurisation + bookkeeping + targets) on existing capture rows - read-only shape /
     featurisation / forward-pass use only; no capture becomes a training example;
  5. peak private memory of this process.
Then applies the ONLY permitted choices of revision 2 (N in {64, 32}, S in {6,000, 4,500, 3,000}; planning and
training projections <= 720 s each) and projects the end-to-end gate with explicit allowances for native capture
(throughputs taken from recorded M7s measurements, cited), evaluation, verification, analysis and cleanup. If nothing
fits, `fits` is false and preparation stops there. Output: logs/m7u_bench/bench.json (Git-ignored).

    python rl/tools/m7u_bench.py [--out logs/m7u_bench] [--timed 200] [--warmup 20]
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import torch  # noqa: E402

import m7u_gate as ug8  # noqa: E402
import m7u_goals as ugo  # noqa: E402
import m7u_model as um  # noqa: E402
import m7u_planner as up  # noqa: E402
import m7u_state as us  # noqa: E402

REPO_ROOT = HERE.parent.parent
CAPTURES = REPO_ROOT / "runs" / "m7q" / "_equiv" / "input_all"
THREADS = 6
PROJECTION_LIMIT_S = 720.0
# Recorded native throughputs (not re-measured: no native run is authorised in preparation)
RECORDED = {
    "vec_ticks_per_s": {"value": 65_721 / 53.4, "source": "docs/rl_gcsl_return_m7s_results.md: M7s phase A seed 0, "
                                                          "65,721 ticks in 53.4 s, 5 workers + standby, v3 stack"},
    "single_ticks_per_s": {"value": 27_521 / 52.0, "source": "docs/rl_gcsl_return_m7s_results.md: M7s P1 null goal, "
                                                             "27,521 ticks in 52.0 s incl. 8 process starts"},
}
ALLOW = {"native_safety_factor": 0.8, "restart_s_per_episode": 3.0, "single_start_s": 3.0, "vec_close_s": 30.0,
         "single_close_s": 10.0, "goal_selection_s": 30.0, "rule_and_records_s": 30.0}


def capture_episodes(limit: int = 8) -> List[um.Episode]:
    import m7f_trace as mt
    from btt_learning import native_to_track1

    eps = []
    for p in sorted(CAPTURES.glob("fx_*.json.gz"))[:limit]:
        with gzip.open(p, "rt", encoding="utf-8") as fp:
            d = json.load(fp)
        rows = np.stack([us.row_from_reply(d["initial"])] + [us.row_from_reply(r) for r in d["steps"]])
        acts, _ = mt.artifact_actions(REPO_ROOT / d["artifact"])
        words = np.array([native_to_track1(b, x, y) for (b, x, y, _t) in acts][:len(d["steps"])], dtype=np.int64)
        eps.append(um.Episode(episode_id=p.name, rows=rows, words=words, fell=False))
    return eps


def cap_vocab(rows: np.ndarray) -> um.Vocab:
    """The real vocabulary of the capture rows, filled with synthetic entries up to every cap (worst-case cost)."""
    real = um.build_vocab(rows)
    status = list(real.status_ids)
    filler = [s for s in range(500, 1000) if s not in status][:um.S_CAP - 1 - len(status)]
    status = sorted(status + filler)
    h3 = list(real.h3_combos)
    k = 0
    while len(h3) < um.V3_CAP:
        c = (k % 21 - 1, (k // 21) % 32)
        if c not in h3:
            h3.append(c)
        k += 1
    h4 = list(real.h4_combos)
    k = 0
    while len(h4) < um.V4_CAP:
        c = (k % 16, (k // 16) % 2, (k // 32) % 2, 0)
        if c not in h4:
            h4.append(c)
        k += 1
    h3 = sorted(h3)
    h4 = sorted(h4)
    return um.Vocab(status_ids=status, h2_mask=np.ones((len(status) + 1, um.N_H2), dtype=bool), h3_combos=h3,
                    h3_mask=np.ones((2, len(h3)), dtype=bool), h4_combos=h4)


def pct(v: List[float], q: float) -> float:
    return float(np.quantile(np.array(v), q))


def bench_decisions(model: um.DynamicsEnsemble, ctx: um.Context, starts: List[Any], n_cand: int, conc: int,
                    warmup: int, timed: int, mem: List[float]) -> Dict[str, Any]:
    tasks = []
    for i in range(conc):
        row, hist = starts[i % len(starts)]
        c = up.Controller(arm="P", stream_key=f"bench|{n_cand}|{conc}|{i}", n_candidates=n_cand,
                          goal=(float(row[us.F["x"]]) + 300.0, float(row[us.F["y"]]) + 800.0), budget=10 ** 9)
        tasks.append(ug8.Task(rank=i, entry={"entry": f"b{i}", "kind": "collect"}, controller=c, rows=[row], hist=hist))
    times = []
    for it in range(warmup + timed):
        t0 = time.perf_counter()
        items = [(t, t.controller.prepare()) for t in tasks]
        ug8.plan_batch(model, ctx, items)
        dt = time.perf_counter() - t0
        for t in tasks:
            for _ in range(up.EXEC):
                t.controller.next_word()
        if it >= warmup:
            times.append(dt)
        if it % 16 == 0:
            m = ug8.private_mb()
            if m is not None:
                mem.append(m)
    return {"n_candidates": n_cand, "concurrency": conc, "timed": timed, "median_s": round(pct(times, 0.5), 4),
            "p95_s": round(pct(times, 0.95), 4), "mean_s": round(float(np.mean(times)), 4),
            "transitions_per_batch": model.members * n_cand * up.H * conc}


def bench_training(model: um.DynamicsEnsemble, ctx: um.Context, warmup: int, timed: int, mem: List[float]
                   ) -> Dict[str, Any]:
    g = torch.Generator().manual_seed(123)
    n = 60_000
    v = ctx.vocab
    S, V3, V4 = v.S, v.V3, v.V4
    targets = {"s": torch.randint(1, S, (n,), generator=g), "h2": torch.randint(0, um.N_H2, (n,), generator=g),
               "h3": torch.randint(0, V3, (n,), generator=g), "h4": torch.randint(0, V4, (n,), generator=g),
               "ga": torch.randint(0, 2, (n,), generator=g), "tapx": torch.randint(0, 5, (n,), generator=g),
               "tapy": torch.randint(0, 5, (n,), generator=g), "z": torch.randint(0, us.N_Z_LEVELS, (n,), generator=g),
               "masks": torch.randint(0, 2, (n, 14), generator=g).float(),
               "h6": torch.randn(n, len(um.H6_FIELDS), generator=g),
               "breaks": torch.zeros(n, us.TARGET_COUNT), "live": torch.ones(n, us.TARGET_COUNT),
               "fall": torch.zeros(n)}
    ts = um.TransitionSet(dense=torch.randn(n, um.DENSE, generator=g), cur=torch.randint(0, S, (n,), generator=g),
                          prev=torch.randint(0, S, (n,), generator=g), targets=targets,
                          episode_of=np.arange(n) // 3000, n_episodes=n // 3000)
    opt = torch.optim.Adam(model.parameters(), lr=3e-4)
    times = []
    for it in range(warmup + timed):
        idx = torch.randint(0, n, (model.members, 1024), generator=g)
        t0 = time.perf_counter()
        L = um.losses(model, ctx, idx, ts)
        opt.zero_grad(set_to_none=True)
        L["total"].backward()
        opt.step()
        dt = time.perf_counter() - t0
        if it >= warmup:
            times.append(dt)
        if it % 16 == 0:
            m = ug8.private_mb()
            if m is not None:
                mem.append(m)
    return {"batch_per_member": 1024, "members": model.members, "timed": timed, "median_s": round(pct(times, 0.5), 4),
            "p95_s": round(pct(times, 0.95), 4), "synthetic_transitions": n}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO_ROOT / "logs" / "m7u_bench"))
    ap.add_argument("--timed", type=int, default=200)
    ap.add_argument("--warmup", type=int, default=20)
    a = ap.parse_args(argv)
    out = Path(a.out)
    if (REPO_ROOT / "runs") in out.resolve().parents:
        print("refused: outputs never go under runs/")
        return 2
    torch.set_num_threads(THREADS)
    t_start = time.perf_counter()
    mem: List[float] = []
    m0 = ug8.private_mb()
    eps = capture_episodes()
    rows_all = np.concatenate([e.rows for e in eps])
    track, tprob = us.build_clock_track([e.rows for e in eps])
    vocab = cap_vocab(rows_all)
    ctx = um.make_context(vocab, us.static_world_pinned(), track)
    model = um.DynamicsEnsemble(vocab, members=ug8.MEMBERS, seed=987654)      # random weights, discarded
    macs = model.macs_per_transition()
    # transition building rate on capture rows (featurisation + bookkeeping + targets), read-only
    t0 = time.perf_counter()
    ts = um.build_transitions(ctx, eps)
    build_s = time.perf_counter() - t0
    per_transition_build = build_s / max(1, len(ts.cur))
    # featurisation-only latency of one rollout step (E x N x 5 rows)
    starts = []
    for e in eps:
        hist = us.history_sequence(e.rows, [tuple(int(v) for v in w) for w in e.words])
        for t in (300, 900, 1500, 2100):
            if t < len(e.rows) - 200 and e.rows[t, us.F["valid"]] == 1.0:
                starts.append((e.rows[t], hist[t]))
    feat = []
    for n_cand in (64, 32):
        nrows = ug8.MEMBERS * n_cand * 5
        r = torch.tensor(np.stack([starts[i % len(starts)][0] for i in range(nrows)]))
        h = torch.tensor(np.stack([starts[i % len(starts)][1] for i in range(nrows)]))
        w = torch.zeros(nrows, 2, dtype=torch.long)
        times = []
        for it in range(a.warmup + a.timed):
            t1 = time.perf_counter()
            um.featurise(ctx, r, h, w)
            if it >= a.warmup:
                times.append(time.perf_counter() - t1)
        feat.append({"rows": nrows, "median_s": round(pct(times, 0.5), 5)})
    decisions = []
    with torch.no_grad():
        for n_cand in (64, 32):
            for conc in (1, 5):
                decisions.append(bench_decisions(model, ctx, starts, n_cand, conc, a.warmup, a.timed, mem))
    train_rec = bench_training(model, ctx, a.warmup, a.timed, mem)
    del model                                                           # weights discarded, never saved
    peak = max(mem + ([m0] if m0 else [])) if (mem or m0) else None
    # projections
    lat = {(d["n_candidates"], d["concurrency"]): d for d in decisions}
    decisions_max = ugo.N_GOALS * 2 * ugo.BUDGET / up.EXEC                      # 1,920 P and S decisions
    planning_batched = {n: lat[(n, 5)]["p95_s"] * decisions_max / 5 for n in (64, 32)}     # revision 2's rule
    planning_unbatched = {n: lat[(n, 1)]["p95_s"] * decisions_max for n in (64, 32)}       # every decision alone
    # The evaluation cannot guarantee 5-way batching (trials enter control at different ticks after prefixes of
    # different lengths), so the choice uses the larger, unbatched projection (a correction found in implementation).
    planning = {n: max(planning_batched[n], planning_unbatched[n]) for n in (64, 32)}
    n_train_trans = ug8.N_TRAIN * 3600
    n_held_trans = ugo.HELDOUT_EPISODES * 3600
    build_proj = per_transition_build * (n_train_trans + n_held_trans)
    training = {s: train_rec["median_s"] * s + build_proj for s in ug8.BENCH_CHOICES["train_steps"]}
    n_choice = next((n for n in ug8.BENCH_CHOICES["n_candidates"] if planning[n] <= PROJECTION_LIMIT_S), None)
    s_choice = next((s for s in ug8.BENCH_CHOICES["train_steps"] if training[s] <= PROJECTION_LIMIT_S), None)
    fits = n_choice is not None and s_choice is not None
    proj: Dict[str, Any] = {}
    if fits:
        vec = RECORDED["vec_ticks_per_s"]["value"] * ALLOW["native_safety_factor"]
        single = RECORDED["single_ticks_per_s"]["value"] * ALLOW["native_safety_factor"]
        rs = ALLOW["restart_s_per_episode"]
        b = ug8.TICK_BUDGET
        p1 = b["p1"] / single + 2 * ALLOW["single_start_s"] + ALLOW["single_close_s"]
        coll = b["collection"] / vec + (ug8.N_COLLECT / 5) * rs + ALLOW["vec_close_s"]
        storage = b["storage"] / single + ALLOW["single_start_s"] + ALLOW["single_close_s"]
        train_phase = ALLOW["goal_selection_s"] + training[s_choice]
        evaluation = ((b["eval_prefix"] + b["eval_control"]) / vec + (ug8.TRIALS / 5) * rs + planning[n_choice]
                      + ALLOW["vec_close_s"])
        one = lat[(n_choice, 1)]["p95_s"]
        analysis = ugo.N_GOALS * one + one + (200 / n_choice) * one + per_transition_build * n_held_trans * 2
        replays = b["replays"] / single + sum(ug8.REPLAYS.values()) * (ALLOW["single_start_s"] + ALLOW["single_close_s"])
        phases = {"p1": p1, "collection": coll, "storage": storage, "train": train_phase, "evaluation": evaluation,
                  "replays_analysis": analysis + replays + ALLOW["rule_and_records_s"]}
        proj = {"phases_s": {k: round(v, 1) for k, v in phases.items()},
                "phase_caps_s": ug8.WALL_CAPS_S,
                "phase_within_cap": {k: phases[k] <= ug8.WALL_CAPS_S[k] for k in phases},
                "end_to_end_s": round(sum(phases.values()), 1), "global_cap_s": ug8.GLOBAL_CAP_S,
                "within_global_cap": sum(phases.values()) <= ug8.GLOBAL_CAP_S}
        fits = fits and proj["within_global_cap"] and all(proj["phase_within_cap"].values())
    rec = {"tool": "m7u_bench_v1", "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "machine": {"platform": platform.platform(), "processor": platform.processor(), "cpu_count": os.cpu_count(),
                       "torch": torch.__version__, "threads": torch.get_num_threads(), "python": platform.python_version()},
           "model": {"members": ug8.MEMBERS, "vocab_at_caps": {"S": vocab.S, "V3": vocab.V3, "V4": vocab.V4},
                     "macs_per_transition": macs, "flop_per_transition": 2 * macs,
                     "parameters": sum(p.numel() for p in um.DynamicsEnsemble(vocab, members=ug8.MEMBERS).parameters()),
                     "weights": "seeded random, discarded (never saved)"},
           "accounting": {str(n): {"transitions_per_decision": ug8.MEMBERS * n * up.H,
                                   "transitions_per_controlled_tick": ug8.MEMBERS * n * up.H // up.EXEC,
                                   "forward_flop_per_decision": 2 * macs * ug8.MEMBERS * n * up.H,
                                   "gate_decisions_max": ugo.N_GOALS * 2 * ugo.BUDGET // up.EXEC,
                                   "gate_planning_flop": 2 * macs * ug8.MEMBERS * n * up.H
                                   * (ugo.N_GOALS * 2 * ugo.BUDGET // up.EXEC)}
                          for n in (64, 32)},
           "capture_use": {"episodes": [e.episode_id for e in eps], "transitions_built": int(len(ts.cur)),
                           "use": "read-only shape / featurisation / forward-pass timing; never training data",
                           "track_problems": tprob},
           "transition_build_s_per_transition": per_transition_build, "featurisation": feat, "decisions": decisions,
           "training_step": train_rec, "peak_private_mb": round(peak, 1) if peak else None,
           "projection_rule": {"planning": "max(p95 batched(5) x 1,920 / 5 [revision 2], p95 single x 1,920 [unbatched: "
                                           "used because 5-way batching is not guaranteed])",
                               "training": "median step x S + transition building of 80 + 12 episodes x 3,600 at the "
                                           "measured rate", "limit_s": PROJECTION_LIMIT_S},
           "planning_projection_s": {str(k): round(v, 1) for k, v in planning.items()},
           "planning_projection_batched_rev2_s": {str(k): round(v, 1) for k, v in planning_batched.items()},
           "planning_projection_unbatched_s": {str(k): round(v, 1) for k, v in planning_unbatched.items()},
           "training_projection_s": {str(k): round(v, 1) for k, v in training.items()},
           "recorded_native_throughputs": RECORDED, "allowances": ALLOW, "end_to_end": proj,
           "choice": {"n_candidates": n_choice, "train_steps": s_choice}, "fits": fits,
           "wall_s": round(time.perf_counter() - t_start, 1)}
    out.mkdir(parents=True, exist_ok=True)
    (out / "bench.json").write_text(json.dumps(rec, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: rec[k] for k in ("choice", "fits", "planning_projection_s", "training_projection_s",
                                          "peak_private_mb", "wall_s")} | {"end_to_end_s": proj.get("end_to_end_s")}))
    return 0 if fits else 1


if __name__ == "__main__":
    sys.exit(main())
