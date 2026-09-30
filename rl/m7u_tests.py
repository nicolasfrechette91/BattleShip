#!/usr/bin/env python3
"""M7u preparation tests (offline; nothing is launched, replayed or trained on recorded data).

    python rl/m7u_tests.py unit [--out <dir>]

Read-only capture cases use runs/m7q/_equiv/input_all (recorded raw replies of own Track 1 policy episodes; the TAS
traces only where stated) for shape, featurisation, row and world checks - never as training examples. Every model
fit uses synthetic tensors; every driver case runs the REAL probe / trial wrappers, row parser, ledger, caps and drive
loop over a synthetic native stand-in whose replies are copies of a captured reply with synthetic values.
"""
from __future__ import annotations

import copy
import gzip
import hashlib
import itertools
import json
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import gymnasium as gym
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import m7u_goals as ug  # noqa: E402
import m7u_planner as up  # noqa: E402
import m7u_rule as ur  # noqa: E402
import m7u_state as us  # noqa: E402

REPO_ROOT = HERE.parent
CAPTURES = REPO_ROOT / "runs" / "m7q" / "_equiv" / "input_all"


class Failure(AssertionError):
    pass


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise Failure(msg)


# -- capture helpers (read-only) -----------------------------------------------------------------------------------------


_CACHE: Dict[str, Any] = {}


def captures(prefix: str = "fx_") -> List[Tuple[str, Dict[str, Any], np.ndarray, np.ndarray]]:
    """(name, trace, rows, Track 1 words) of the capture traces (read-only)."""
    key = f"cap:{prefix}"
    if key not in _CACHE:
        import m7f_trace as mt
        from btt_learning import native_to_track1

        out = []
        for p in sorted(CAPTURES.glob(f"{prefix}*.json.gz")):
            with gzip.open(p, "rt", encoding="utf-8") as fp:
                d = json.load(fp)
            rows = np.stack([us.row_from_reply(d["initial"])] + [us.row_from_reply(r) for r in d["steps"]])
            acts, _ = mt.artifact_actions(REPO_ROOT / d["artifact"]) if d.get("artifact") else ([], None)
            words = np.array([native_to_track1(b, x, y) for (b, x, y, _t) in acts][:len(d["steps"])],
                             dtype=np.int64).reshape(-1, 2)
            out.append((p.name, d, rows, words))
        _CACHE[key] = out
    return _CACHE[key]


# -- planner ---------------------------------------------------------------------------------------------------------------


def unit_expansion_and_coverage(out: Path) -> Dict[str, Any]:
    import m7r_commit as mr

    bad = 0
    for s, b, m, li in itertools.product(range(9), range(8), range(2), range(6)):
        opt = mr.Option(stick=s, button=b, mode=m, d_index=li)
        if [mr.tick_word(opt, i) for i in range(1, opt.d + 1)] != up.expand((s, b, m, li)):
            bad += 1
    check(bad == 0, f"{bad} options expand differently from rl/m7r_commit.tick_word")
    words = up.rc_words("coverage", 64, 20_000)
    check(len(set(words)) == 72, f"RC covers {len(set(words))} of 72 Track 1 words")
    check({w[1] for w in words} == set(range(8)), "a button index never appears (B and every other button must)")
    cands = []
    for k in range(20):
        _plans, arr = up.candidates(None, up.draw_block("cov", k, 64), 64)
        cands.append(arr.reshape(-1, 2))
    allw = {tuple(w) for w in np.concatenate(cands)}
    check(len(allw) == 72, f"candidates cover {len(allw)} of 72 words")
    return {"options_checked": 576, "rc_distinct_words": len(set(words)), "candidate_distinct_words": len(allw)}


def unit_streams_and_retention(out: Path) -> Dict[str, Any]:
    for n in (64, 32):
        d1, d2 = up.draw_block("k", 3, n), up.draw_block("k", 3, n)
        check(all(np.array_equal(getattr(d1, f), getattr(d2, f)) for f in ("refill", "mut_u", "mut_seg", "fresh")),
              "draws are not deterministic")
        check(d1.refill.shape == (64, 4) and d1.mut_seg.shape == (15, 4) and d1.fresh.shape == (n - 16, 64, 4),
              f"fixed draw shapes broken at N={n}")
    # every arm of a goal gets identical candidates at the same state and decision index
    arms = {a: up.Controller(arm=a, stream_key="m7u1|0|goal|7", n_candidates=64,
                             goal=None if a == "RC" else (0.0, 0.0), budget=96) for a in ("P", "RC", "S")}
    arrs = {a: c.prepare() for a, c in arms.items()}
    check(np.array_equal(arrs["P"], arrs["RC"]) and np.array_equal(arrs["P"], arrs["S"]),
          "arms see different candidate sets at decision 0")
    # RC is forced to candidate 0
    try:
        arms["RC"].choose(5)
        check(False, "RC accepted a non-zero choice")
    except up.PlannerError:
        pass
    # retention: candidate 0 of the next decision continues the chosen plan shifted by EXEC
    c = arms["P"]
    c.choose(9)
    chosen = arrs["P"][9]
    first = [c.next_word() for _ in range(up.EXEC)]
    check(first == [tuple(int(v) for v in w) for w in chosen[:up.EXEC]], "executed words are not the chosen plan's first 4")
    nxt = c.prepare()
    check(np.array_equal(nxt[0][:up.H - up.EXEC], chosen[up.EXEC:]), "candidate 0 does not continue the retained plan")
    check(nxt.shape == (64, up.H, 2), "candidate shape")
    # a decision is due every EXEC ticks; next_word refuses before it is taken
    try:
        c.next_word()
        check(False, "a word was issued while a decision was due")
    except up.PlannerError:
        pass
    # RC regeneration equals a controller loop
    w = up.rc_words("m7u1|0|collect|c001", 64, 333)
    c2 = up.Controller(arm="collect", stream_key="m7u1|0|collect|c001", n_candidates=64)
    loop = []
    for _ in range(333):
        if c2.needs_decision():
            c2.prepare()
            c2.choose(0)
        loop.append(c2.next_word())
    check(w == loop, "rc_words differs from the controller loop")
    return {"streams": "deterministic, fixed shapes, identical across arms", "retention": "ok"}


def unit_score(out: Path) -> Dict[str, Any]:
    import torch

    E, N, H = 3, 4, up.H
    x = torch.zeros(E, N, H, dtype=torch.float64)
    y = torch.zeros(E, N, H, dtype=torch.float64)
    air = torch.ones(E, N, H, dtype=torch.bool)
    fall = torch.full((E, N), H, dtype=torch.long)
    x[:, 1, 10:] = 1000.0                # candidate 1 reaches (1000, 0) at tau 10
    x[:, 2, 5:] = 1000.0                 # candidate 2 reaches at tau 5 ...
    fall[:, 2] = 3                       # ... but falls first
    x[:, 3, 20:] = 1000.0
    air[:, 3, :] = False                 # grounded: contact penalty
    s, reach = up.score(x, y, air, fall, (1000.0, 0.0), 96)
    check(int(torch.argmin(s)) == 1, f"best candidate {int(torch.argmin(s))}, want 1")
    check(float(s[2]) == up.FALL_COST, "a predicted fall before any reach must cost FALL_COST")
    check(int(reach[0, 1]) == 10 and int(reach[0, 3]) == H, "reach index")
    s2, _ = up.score(x, y, air, fall, (1000.0, 0.0), 8)
    check(float(s2[1]) > 1.0, "tau beyond the remaining budget must not count")
    return {"score": [round(float(v), 3) for v in s]}


# -- rows, world, track, featurisation (captures, read-only) --------------------------------------------------------------


def unit_rows_and_encoding(out: Path) -> Dict[str, Any]:
    """Rows parse on every capture reply; the latched hold equals the documented fold of the submitted word on live
    ticks (a data check of the controller-encoding assumption; the fold appears only in this test). Word-level edges
    vs the game's latched tap / release masks are reported, not required (hitlag, hit tick, Turn re-injection)."""
    import m7q_input as mi
    from btt_learning import TRACK1_BUTTON_TABLE

    fold_bad = hold_n = edge_mismatch = edge_n = 0
    for name, _d, rows, words in captures():
        for k, w in enumerate(words):
            r = rows[k + 1]
            if r[us.F["valid"]] != 1.0:
                continue
            native = int(TRACK1_BUTTON_TABLE[int(w[1])])
            if native & mi.BUTTON_R:
                native |= mi.BUTTON_A | mi.BUTTON_Z
            hold_n += 1
            if us.button_mask7(native) != int(r[us.F["hold"]]):
                fold_bad += 1
            prev_native = 0
            if k > 0:
                prev_native = int(TRACK1_BUTTON_TABLE[int(words[k - 1][1])])
                if prev_native & mi.BUTTON_R:
                    prev_native |= mi.BUTTON_A | mi.BUTTON_Z
            word_edge = us.button_mask7(native & ~prev_native)
            if int(r[us.F["hitlag"]]) == 0 and int(rows[k, us.F["hitlag"]]) == 0:
                edge_n += 1
                edge_mismatch += word_edge != int(r[us.F["tap_mask"]])
    check(fold_bad == 0, f"{fold_bad} of {hold_n} live ticks: latched hold != fold(word)")
    return {"hold_checked": hold_n, "fold_mismatch": fold_bad, "no_hitlag_edges": edge_n,
            "word_edge_vs_latched_tap_mismatch": edge_mismatch}


def unit_world_and_track(out: Path) -> Dict[str, Any]:
    pinned = us.world_digest(us.static_world_pinned())
    n = 0
    for name, d, _rows, _w in captures("") :
        check(us.world_digest(us.static_world(d["initial"])) == pinned, f"{name}: reset world != pinned")
        n += 1
    track, probs = us.build_clock_track([c[2] for c in captures()])
    check(not probs, f"clock track problems on captures: {probs[:2]}")
    # a planted disagreement must be caught
    rows = captures()[0][2].copy()
    rows[100, us.F["grp_ty"]] += 1.0
    _t, p2 = us.build_clock_track([captures()[1][2], rows])
    check(any("grp_ty" in p for p in p2), "a planted platform disagreement was not detected")
    check(len(us.STATIC_TARGET_POSITIONS) == us.TARGET_COUNT, "static targets")
    return {"worlds_checked": n, "track_ticks": int(track.covered.sum())}


def unit_featurisation_equivalence(out: Path) -> Dict[str, Any]:
    """Torch featurisation vs the unchanged v3 / v4 builders on every capture (agent without echoes, class v2, the 8
    nearest segments from the builder's own 32 rows, targets); bookkeeping status tics vs native; torch history ==
    numpy history."""
    import torch

    import m7g_spatial as ms
    import m7n_entity as ne
    import m7n_status_table as st1
    import m7q_input as mi
    import m7q_obs as mq
    import m7q_status_table as st2
    import m7u_model as um

    caps = captures()
    rows_all = np.concatenate([c[2] for c in caps])
    track, _ = us.build_clock_track([c[2] for c in caps])
    vocab = um.build_vocab(rows_all[rows_all[:, us.F["valid"]] == 1.0])
    ctx = um.make_context(vocab, us.static_world_pinned(), track)
    t1, t2 = st1.load_table(), st2.load_table()
    v3idx = list(range(0, 21)) + [22, 23, 24, 25, 26, 27] + list(range(37, 45))
    worst = {"agent": 0.0, "segments": 0.0, "targets": 0.0, "class": 0.0, "history": 0.0}
    tics_mismatch = n = 0
    for name, d, rows, words in caps:
        T = len(words)
        hist = us.history_sequence(rows, [tuple(int(v) for v in w) for w in words])
        dense, _cur, _prev = um.featurise(ctx, torch.tensor(rows[:T]), torch.tensor(hist[:T]), torch.tensor(words))
        # torch history == numpy history
        ht = um.advance_history_t(torch.tensor(hist[:T]), torch.tensor(rows[:T]), torch.tensor(words),
                                  torch.tensor(rows[1:T + 1])).numpy()
        diff = np.abs(np.nan_to_num(ht, nan=-7.0) - np.nan_to_num(hist[1:T + 1], nan=-7.0)).max()
        worst["history"] = max(worst["history"], float(diff))
        sp0 = ms.spatial_of(d["initial"], expect_lines=True)
        b = mq.InputObservationBuilder(sp0.lines, st1.ActionClassifier(t1, "mario"), st2.ActionClassifier(t2, "mario"),
                                       st2.aerial_attack_ids(t2))
        replies = [d["initial"]] + d["steps"]
        world = us.static_world_pinned()
        for k in range(T):
            r = replies[k]
            obs, stale = b.build(r["observation"], ms.spatial_of(r, expect_lines=(k == 0)), ne.entity_of(r), mi.input_of(r))
            if stale:
                continue
            n += 1
            mine = dense[k].numpy()
            ag = mine[68:68 + 35]
            ref = obs["agent"][v3idx]
            if abs(ag[18] - ref[18]) > 1e-6:
                tics_mismatch += 1
            dd = np.abs(ag - ref)
            dd[18] = 0.0
            worst["agent"] = max(worst["agent"], float(dd.max()))
            worst["class"] = max(worst["class"], float(np.abs(mine[68 + 35 + 42:68 + 35 + 42 + 23] - obs["action_class"]).max()))
            worst["targets"] = max(worst["targets"], float(np.abs(mine[338 - 50:] - obs["targets"].reshape(-1)).max()))
            geo, kind, dist = us.segment_rows_all(world, rows[k, us.F["x"]], rows[k, us.F["y"]],
                                                  *track.table[int(rows[k, us.F["input_tick"]])][:4])
            ns = len(world.seg)
            worst["segments"] = max(worst["segments"], float(np.abs(geo - obs["segment_geometry"][:ns]).max()),
                                    float(np.abs(kind - obs["segment_kind"][:ns]).max()))
            order = np.argsort(dist, kind="stable")[:us.SEGMENTS_KEPT]
            sel = np.concatenate([geo[order], kind[order]], axis=1).reshape(-1)
            worst["segments"] = max(worst["segments"], float(np.abs(sel - mine[68 + 35 + 42 + 23:68 + 35 + 42 + 23 + 120]).max()))
    check(max(worst.values()) <= 1e-5, f"featurisation differs from the v3 / v4 builders: {worst}")
    return {"rows_compared": n, "max_abs_diff": worst, "bookkeeping_status_tics_vs_native_mismatch": tics_mismatch}


# -- model -----------------------------------------------------------------------------------------------------------------


def _synthetic_ts(ctx: Any, n: int, seed: int) -> Any:
    import torch

    import m7u_model as um

    g = torch.Generator().manual_seed(seed)
    v = ctx.vocab
    dense = torch.randn(n, um.DENSE, generator=g)
    s = torch.randint(1, v.S, (n,), generator=g)
    tg = {"s": s, "h2": torch.tensor([int(np.nonzero(v.h2_mask[int(i)])[0][0]) for i in s]),
          "h3": torch.randint(0, v.V3, (n,), generator=g), "h4": torch.randint(0, v.V4, (n,), generator=g),
          "ga": torch.zeros(n, dtype=torch.long), "tapx": torch.randint(0, 5, (n,), generator=g),
          "tapy": torch.randint(0, 5, (n,), generator=g), "z": torch.randint(0, us.N_Z_LEVELS, (n,), generator=g),
          "masks": torch.zeros(n, 14), "h6": 0.5 * dense[:, :len(um.H6_FIELDS)].clone(),
          "breaks": torch.zeros(n, us.TARGET_COUNT), "live": torch.ones(n, us.TARGET_COUNT), "fall": torch.zeros(n)}
    allowed = np.nonzero(v.h3_mask[0])[0]            # targets must be combinations the ground mask allows
    tg["h3"] = torch.tensor([int(allowed[int(i) % len(allowed)]) for i in tg["h3"]])
    return um.TransitionSet(dense=dense, cur=torch.randint(0, v.S, (n,), generator=g),
                            prev=torch.randint(0, v.S, (n,), generator=g), targets=tg,
                            episode_of=np.arange(n) // 100, n_episodes=n // 100)


def unit_model_masks_rollout_training(out: Path) -> Dict[str, Any]:
    """Vocabulary caps; imagined combinations always recorded ones; imagined live flags monotone; clock +1; echo
    fields NaN; the imagined history equals the numpy bookkeeping applied to the imagined rows; a synthetic fit lowers
    its loss (no recorded data is trained on)."""
    import torch

    import m7u_model as um

    caps = captures()
    rows_all = np.concatenate([c[2] for c in caps])
    rows_v = rows_all[rows_all[:, us.F["valid"]] == 1.0]
    vocab = um.build_vocab(rows_v)
    try:
        big = rows_v[:200].copy()
        big = np.repeat(big, 200, axis=0)
        big[:, us.F["status"]] = np.arange(len(big)) % 400
        um.build_vocab(big)
        check(False, "the status cap was not enforced")
    except um.ModelError:
        pass
    track, _ = us.build_clock_track([c[2] for c in caps])
    ctx = um.make_context(vocab, us.static_world_pinned(), track)
    model = um.DynamicsEnsemble(vocab, members=3, seed=5)
    _name, _d, rows, words = caps[3]
    hist = us.history_sequence(rows, [tuple(int(v) for v in w) for w in words])
    starts = [200, 700, 1300]
    plans = np.stack([np.concatenate([words[s:s + up.H]]) for s in starts])
    roll = um.rollout(model, ctx, torch.tensor(rows[starts]), torch.tensor(hist[starts]), torch.tensor(plans),
                      keep_rows=True)
    R = roll.rows.numpy()                     # (E, N, H, F)
    bad_mask = 0
    for e in range(R.shape[0]):
        for i in range(R.shape[1]):
            prev_row, h = rows[starts[i]], hist[starts[i]]
            live_prev = int(prev_row[us.F["live_mask"]])
            for tau in range(R.shape[2]):
                r = R[e, i, tau]
                if tau >= int(roll.fall_at[e, i]):
                    break
                s_idx = vocab.status_ids.index(int(r[us.F["status"]])) + 1
                h2 = um.h2_index(r[us.F["ga"]], r[us.F["facing"]], r[us.F["jumps_used"]], r[us.F["fastfall"]])
                h3 = vocab.h3_combos.index((int(r[us.F["floor_line"]]), um.contact_bits(r)))
                bad_mask += (not vocab.h2_mask[s_idx, h2]) + (not vocab.h3_mask[int(r[us.F["ga"]]), h3])
                check(int(r[us.F["live_mask"]]) & ~live_prev == 0, "an imagined target came back to life")
                check(int(r[us.F["input_tick"]]) == int(prev_row[us.F["input_tick"]]) + 1, "imagined clock not +1")
                check(np.isnan(r[us.F["hold"]]) and np.isnan(r[us.F["status_tics"]]), "echo fields must be NaN")
                h = us.advance_history(h, prev_row, tuple(int(v) for v in plans[i, tau]), r)
                prev_row, live_prev = r, int(r[us.F["live_mask"]])
    check(bad_mask == 0, f"{bad_mask} imagined combinations outside the recorded masks")
    # the torch rollout's history equals numpy bookkeeping on the imagined rows (last step of member 0, plan 0)
    # (checked implicitly: featurisation consumed the torch history; recompute the final one explicitly)
    ts = _synthetic_ts(ctx, 4000, 1)
    m2 = um.DynamicsEnsemble(vocab, members=3, seed=6)
    before = float(um.losses(m2, ctx, torch.arange(512)[None].expand(3, -1), ts)["total"].detach())
    res = um.train(m2, ctx, ts, steps=60, batch=256, seed=3, log_every=60)
    after = float(um.losses(m2, ctx, torch.arange(512)[None].expand(3, -1), ts)["total"].detach())
    check(after < before, f"synthetic fit did not lower the loss ({before:.3f} -> {after:.3f})")
    p = out / "m.pt"
    dig = um.save(m2, vocab, p)
    m3, v3, _ = um.load(p)
    check(um.parameter_digest(m3) == um.parameter_digest(m2) and v3.digest() == vocab.digest(), "save / load round trip")
    return {"vocab": {"S": vocab.S, "V3": vocab.V3, "V4": vocab.V4}, "macs_per_transition": model.macs_per_transition(),
            "synthetic_loss": [round(before, 3), round(after, 3)], "model_sha256": dig[:16], "train_steps": res.steps}


def unit_import_isolation(out: Path) -> Dict[str, Any]:
    code = ("import sys; sys.path.insert(0, r'%s'); import m7u_planner, m7u_model, m7u_state, m7u_goals, m7u_rule, "
            "m7u_analysis; bad=[m for m in ('battleship_client','battleship_process','battleship_env','btt_parallel',"
            "'btt_learning','m7_vec_env') if m in sys.modules]; print(bad)") % str(HERE)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    check(r.returncode == 0 and r.stdout.strip() == "[]",
          f"planner / model import transport or env code: {r.stdout} {r.stderr[-300:]}")
    code2 = "import sys; sys.path.insert(0, r'%s'); import m7u_worker; print('torch' in sys.modules)" % str(HERE)
    r2 = subprocess.run([sys.executable, "-c", code2], capture_output=True, text=True)
    check(r2.returncode == 0 and r2.stdout.strip() == "False",
          f"spawn workers would import torch: {r2.stdout} {r2.stderr[-300:]}")
    return {"planner_model_transport_free": True, "worker_torch_free": True}


# -- goals, rule, caps -------------------------------------------------------------------------------------------------------


def _synthetic_episode(seed: int, T: int = 900) -> Tuple[np.ndarray, np.ndarray, bool]:
    rng = np.random.default_rng(seed)
    rows = np.zeros((T + 1, us.N_FIELDS))
    rows[:, us.F["valid"]] = 1.0
    rows[:, us.F["input_tick"]] = np.arange(T + 1)
    x = np.cumsum(rng.normal(0, 20, T + 1))
    period = 97 + 6 * (seed % 5)                     # ramps longer than the 64-tick horizon: rises >= 300 exist
    y = ((np.arange(T + 1) + 13 * seed) % period) / period * (600 + 400 * (seed % 3))
    rows[:, us.F["x"]], rows[:, us.F["y"]] = x, y
    rows[:, us.F["ga"]] = (y > 50).astype(float)
    words = rng.integers(0, [9, 8], size=(T, 2))
    return rows, words, bool(seed % 4 == 0)


def unit_goals(out: Path) -> Dict[str, Any]:
    train = [_synthetic_episode(s)[0::2] for s in range(20)]
    table = ug.chance_table([(r, f) for r, _w, f in [_synthetic_episode(s) for s in range(20)]])
    # exact q vs brute force
    tr = [_synthetic_episode(s) for s in range(20)]
    for start_ga, dx, dy in ((1, 30.0, 400.0), (0, -80.0, 600.0), (1, 0.0, 0.0)):
        num = den = 0
        for rows, _w, fell in tr:
            for t in ug.usable_pairs(rows, fell):
                a, b = rows[t], rows[t + ug.HZ]
                if int(a[us.F["ga"]]) != start_ga:
                    continue
                den += 1
                num += (abs((b[us.F["x"]] - a[us.F["x"]]) - dx) <= ug.BOX and abs((b[us.F["y"]] - a[us.F["y"]]) - dy) <= ug.BOX
                        and int(b[us.F["ga"]]) == 1)
        check(abs(table.q(start_ga, dx, dy) - (num / den if den else 1.0)) < 1e-12, "q differs from brute force")
    held = {f"e{s}": _synthetic_episode(100 + s) for s in range(12)}
    sel = ug.select_goals(held, table)
    sel2 = ug.select_goals(held, table)
    goals = sel["goals"]
    check(len(goals) == ug.N_GOALS, f"{len(goals)} goals")
    check(ug.goals_digest(goals) == ug.goals_digest(sel2["goals"]), "selection is not deterministic")
    per: Dict[str, List[int]] = {}
    for g in goals:
        per.setdefault(g.episode_id, []).append(g.t)
        rows, words, _ = held[g.episode_id]
        check(ug.T_MIN <= g.t <= ug.T_MAX and len(g.prefix) == g.t and len(g.witness) == ug.HZ, "goal fields")
        check(g.y - rows[g.t, us.F["y"]] >= ug.RISE and int(rows[g.t + ug.HZ, us.F["ga"]]) == 1, "not a rising airborne goal")
    check(all(len(v) <= ug.PER_EPISODE and all(abs(a - b) >= ug.MIN_GAP for a, b in itertools.combinations(v, 2))
              for v in per.values()), "per-episode constraints")
    check(sorted(ug.scrambled(k) for k in range(ug.N_GOALS)) == list(range(ug.N_GOALS))
          and all(ug.scrambled(k) != k for k in range(ug.N_GOALS)), "pi is not a derangement")
    try:
        ug.select_goals({"e0": _synthetic_episode(3, T=120)}, table)
        check(False, "too few candidates must be incomplete")
    except ug.GoalError as exc:
        check(exc.incomplete, "too few candidates must be flagged incomplete")
    tr_ids, held_ids = ug.heldout_split([f"x{i}" for i in range(92)])
    check(len(held_ids) == 12 and len(tr_ids) == 80 and not set(tr_ids) & set(held_ids), "held-out split")
    return {"goals": len(goals), "filled": sel["record"]["filled"], "candidates": sel["record"]["candidates"]}


def unit_rule(out: Path) -> Dict[str, Any]:
    p = ur.self_test()
    check(not p, f"rule self-test: {p}")
    return {"rule": ur.RULE_ID, "digest": ur.rule_digest()}


def unit_ledger_clock(out: Path) -> Dict[str, Any]:
    import m7u_gate as g8

    L = g8.Ledger({"a": 10, "b": 5, "total": 12})
    L.check("a", 10)
    L.add("a", 10)
    for phase, n in (("a", 1), ("b", 3)):
        try:
            L.check(phase, n)
            check(False, f"ledger allowed {phase} +{n}")
        except g8.CapStop:
            pass
    t = [0.0]
    c = g8.Clock(now=lambda: t[0], caps={"x": 5.0, "y": 100.0}, global_cap=8.0, memory=lambda: 10.0, memory_cap_mb=50.0)
    c.begin("x")
    t[0] = 4.9
    c.check()
    t[0] = 5.2
    try:
        c.check()
        check(False, "phase cap not enforced")
    except g8.CapStop:
        pass
    c.begin("y")
    t[0] = 8.5
    try:
        c.check()
        check(False, "global cap not enforced")
    except g8.CapStop:
        pass
    c2 = g8.Clock(now=lambda: 0.0, caps={"x": 5.0}, memory=lambda: 99.0, memory_cap_mb=50.0)
    try:
        c2.begin("x")
        check(False, "memory cap not enforced")
    except g8.CapStop:
        pass
    check(g8.TICK_BUDGET["total"] == 431_201 and sum(g8.WALL_CAPS_S.values()) == 3600, "pinned budgets")
    return {"tick_budget": g8.TICK_BUDGET, "wall_caps_s": g8.WALL_CAPS_S}


# -- synthetic native stand-in under the REAL probe / trial wrappers --------------------------------------------------------


class _Template:
    def __init__(self) -> None:
        name, d, _rows, _w = captures()[3]
        self.initial = d["initial"]
        self.step = d["steps"][0]


class _FakeNative(gym.Env):
    """Deterministic 1-D-ish world: replies are copies of captured replies with synthetic values."""
    observation_space = gym.spaces.Box(-1, 1, (1,), np.float32)
    action_space = gym.spaces.MultiDiscrete([9, 8])

    def __init__(self, horizon: int, tpl: _Template):
        self.horizon, self.tpl = horizon, tpl
        self.last_reply: Optional[Dict[str, Any]] = None
        self.k = 0

    def _reply(self, op: str) -> Dict[str, Any]:
        src = self.tpl.initial if op == "observe" else self.tpl.step
        r = copy.deepcopy(src)
        r["op"] = op
        o = r["observation"]
        o["input_tick"] = self.k
        o["time_passed"] = self.k
        o["position_x"], o["position_y"] = float(self.x), float(self.y)
        o["ground_air_state"] = int(self.ga)
        o["fighter_status_id"] = 10 if self.ga == 0 else 22
        o["air_velocity_y"] = float(self.vy)
        for key in ("spatial", "entity", "input"):
            r[key]["input_tick"] = self.k
        r["spatial"]["groups"][2]["translate"] = [2700.0, 2150.0 + float(self.k)]
        r["spatial"]["groups"][2]["speed"] = [0.0, 1.0]
        r["spatial"]["target_positions"][2] = [2700.0, 2750.0 + float(self.k)]
        r["input"]["stick_x"], r["input"]["stick_y"] = int(self.sx), int(self.sy)
        if op == "step":
            r["consumed_tick"] = self.k - 1
            r["step_count"] = self.k
        return r

    def reset(self, *, seed=None, options=None):
        self.k, self.x, self.y, self.vy, self.ga, self.sx, self.sy = 0, 0.0, -2550.0, 0.0, 0, 0, 0
        self.last_reply = self._reply("observe")
        return np.zeros(1, np.float32), {"startup_mode": "cold_start"}

    def step(self, action):
        from btt_learning import TRACK1_STICK_TABLE

        s, b = int(action[0]), int(action[1])
        self.sx, self.sy = TRACK1_STICK_TABLE[s]
        self.x += self.sx / 4.0
        if self.ga == 0 and (b in (3, 4) or self.sy > 0):
            self.ga, self.vy = 1, 60.0
        if self.ga == 1:
            self.y += self.vy
            self.vy -= 2.4
            if self.y <= -2550.0:
                self.y, self.vy, self.ga = -2550.0, 0.0, 0
        self.k += 1
        self.last_reply = self._reply("step")
        end = self.k >= self.horizon
        return np.zeros(1, np.float32), 0.0, False, end, ({"truncation_reason": "max_episode_steps"} if end else {})


class _TrackerStub:
    def __init__(self, root: Path):
        self.artifact_root = root
        root.mkdir(parents=True, exist_ok=True)
        self._pending: Optional[Dict[str, Any]] = None
        self.n = 0
        self.words: Dict[str, List[Tuple[int, int]]] = {}

    def begin(self, words: List[Tuple[int, int]]) -> None:
        self.cur_words = words

    def end(self, info: Mapping[str, Any], words: List[Tuple[int, int]]) -> None:
        self.n += 1
        eid = f"ep{self.n:04d}_{self.artifact_root.name}"
        (self.artifact_root / eid).mkdir(parents=True, exist_ok=True)
        dig = hashlib.sha256(json.dumps(words).encode()).hexdigest()
        self.words[eid] = list(words)
        self._pending = {"episode_id": eid, "artifact_dir": str(self.artifact_root / eid), "preserved": True,
                         "native_action_digest": dig, "startup_mode": "cold_start", "cleared": False,
                         "end_reason": "horizon"}

    def extend_pending_summary(self, build):
        if self._pending is None:
            return False
        self._pending.update(build(dict(self._pending)))
        return True

    def pop(self):
        s, self._pending = self._pending, None
        return s


def _fake_stack(root: Path, rank: int, horizon: int, tpl: _Template):
    import m7u_worker as uw

    native = _FakeNative(horizon, tpl)
    probe = uw.M7uProbeWrapper(native, base=native)
    tracker = _TrackerStub(root / f"w{rank}")

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

    rec = Recorder(probe)
    v4 = V4Stub(rec)
    probe.reply_source = lambda: native.last_reply
    trial = uw.M7uTrialWrapper(v4, probe=probe, v4=v4, tracker=tracker, rank=rank)
    return trial, tracker


class _FakeVec:
    def __init__(self, root: Path, n: int, horizon: int):
        tpl = _Template()
        self.stacks = [_fake_stack(root, r, horizon, tpl) for r in range(n)]
        self.num_envs = n
        self.ranks = list(range(n))
        self.reset_infos: List[Dict[str, Any]] = [{} for _ in range(n)]
        self.closed = False

    def env_method_each(self, name, calls):
        return {i: getattr(self.stacks[i][0], name)(*a, **k) for i, (a, k) in calls.items()}

    def reset(self):
        for i, (tw, _t) in enumerate(self.stacks):
            _o, info = tw.reset()
            self.reset_infos[i] = {"m7u": info.get("m7u") or tw.last_reset_record}

    def step(self, actions):
        dones, infos = [], []
        for i, (tw, tracker) in enumerate(self.stacks):
            self.reset_infos[i] = {}
            _o, _r, term, trunc, info = tw.step(actions[i])
            slim = {"m7u": tw.last_step_record}
            if term or trunc:
                slim["m7_episode"] = tracker.pop()
                _o2, rinfo = tw.reset()
                self.reset_infos[i] = {"m7u": tw.last_reset_record}
            dones.append(bool(term or trunc))
            infos.append(slim)
        return None, None, np.array(dones), infos

    def close(self):
        self.closed = True


class _FakeSingle:
    def __init__(self, root: Path, horizon: int):
        self.trial, self.tracker = _fake_stack(root, 0, horizon, _Template())

    def reset(self):
        _o, info = self.trial.reset()
        return None, {"m7u": self.trial.last_reset_record}

    def step(self, action):
        _o, _r, term, trunc, _info = self.trial.step(action)
        info = {"m7u": self.trial.last_step_record}
        if term or trunc:
            info["m7_episode"] = self.tracker.pop()
        return None, 0.0, term, trunc, info

    def close(self):
        pass


def unit_driver_collection_and_single(out: Path) -> Dict[str, Any]:
    import m7u_gate as g8
    import m7u_worker as uw

    vec = _FakeVec(out / "coll", 2, horizon=150)
    cfg = {0: {"mode": "collect", "phase": "collection", "entries": [{"entry": "c000", "kind": "collect"},
                                                                     {"entry": "c002", "kind": "collect"}]},
           1: {"mode": "collect", "phase": "collection", "entries": [{"entry": "c001", "kind": "collect"}]}}
    L = g8.Ledger(dict(g8.TICK_BUDGET, collection=450))
    res = g8.drive(vec, cfg, phase="collection", ledger=L, clock=g8.Clock(memory=lambda: None), n_candidates=17)
    check(len(res) == 3 and L.used["collection"] == 450, f"collection: {len(res)} episodes, {L.used['collection']} ticks")
    for r in res:
        check([tuple(w) for w in r["words"]] == up.rc_words(f"m7u1|{g8.GATE_SEED}|collect|{r['entry']}", 17, 150),
              f"{r['entry']}: collection words are not the RC stream")
        side = uw.read_sidecar(Path(r["artifact_dir"]))
        check(np.array_equal(side["rows"], r["rows"], equal_nan=True) and np.array_equal(side["words"], r["words"]),
              f"{r['entry']}: sidecar differs from the streamed rows")
    # a cap one tick short stops before the request that would exceed it (INCOMPLETE, not a result)
    vec2 = _FakeVec(out / "coll2", 2, horizon=150)
    L2 = g8.Ledger(dict(g8.TICK_BUDGET, collection=449))
    try:
        g8.drive(vec2, cfg, phase="collection", ledger=L2, clock=g8.Clock(memory=lambda: None), n_candidates=17)
        check(False, "the collection cap was not enforced")
    except g8.CapStop:
        check(L2.used["collection"] <= 449, "ledger exceeded before the stop")
    # single-env replay of one collected episode reproduces its rows
    single = _FakeSingle(out / "single", horizon=150)
    words = [list(w) for w in res[0]["words"]]
    L3 = g8.Ledger()
    rr = g8.run_single(single, [{"entry": "r0", "kind": "collect", "words": words}], phase="storage", ledger=L3,
                       clock=g8.Clock(memory=lambda: None))[0]
    check(rr["sent"] == 150 and np.array_equal(rr["rows"], res[0]["rows"], equal_nan=True), "single-env replay rows")
    # a wrong replay word is refused before anything is sent
    single2 = _FakeSingle(out / "single2", horizon=150)
    bad = [list(w) for w in words]
    try:
        single2.trial.m7u_configure({"mode": "replay", "entries": [{"entry": "r1", "kind": "collect", "words": bad}],
                                     "phase": "x"})
        single2.reset()
        single2.step(np.array([(bad[0][0] + 1) % 9, bad[0][1]]))
        check(False, "a word differing from the replay entry was sent")
    except uw.WorkerContractError:
        pass
    return {"episodes": len(res), "ticks": L.used["collection"], "cap_stop": "ok", "replay": "exact"}


def _trial_goals(out: Path) -> Tuple[List[ug.Goal], np.ndarray]:
    """Goals built from one synthetic RC episode through the real stack (so the prefixes reproduce the start rows)."""
    import m7u_gate as g8

    vec = _FakeVec(out / "held", 1, horizon=400)
    res = g8.drive(vec, {0: {"mode": "collect", "phase": "collection", "entries": [{"entry": "h0", "kind": "collect"}]}},
                   phase="collection", ledger=g8.Ledger(dict(g8.TICK_BUDGET, collection=10 ** 6)),
                   clock=g8.Clock(memory=lambda: None), n_candidates=17)[0]
    rows, words = res["rows"], res["words"]
    goals = []
    for k, t in enumerate((70, 130, 190)):
        g = rows[t + ug.HZ]
        goals.append(ug.Goal(k=k, episode_id="h0", t=t, x=float(g[us.F["x"]]), y=float(g[us.F["y"]]) + 0.0,
                             start_x=float(rows[t, us.F["x"]]), start_y=float(rows[t, us.F["y"]]),
                             start_ga=int(rows[t, us.F["ga"]]), q=0.0, filled=False,
                             prefix=[tuple(int(v) for v in w) for w in words[:t]],
                             witness=[tuple(int(v) for v in w) for w in words[t:t + ug.HZ]],
                             expected_start_row=[float(v) for v in rows[t]]))
    return goals, rows


def unit_driver_evaluation(out: Path) -> Dict[str, Any]:
    """Evaluation through the real drive loop: prefixes itemised in the ledger and guarded, start identity checked, S
    scored on g, RC evaluates no model, control ticks bounded by the budget, the rule never sees a partial run."""
    import torch

    import m7u_gate as g8
    import m7u_model as um

    goals, rows = _trial_goals(out)
    track, _ = us.build_clock_track([rows])
    vocab = um.build_vocab(rows[1:])
    ctx = um.make_context(vocab, us.static_world_pinned(), track)
    model = um.DynamicsEnsemble(vocab, members=3, seed=11)
    calls = {"n": 0, "arms": set()}
    real_plan = g8.plan_batch

    def counting(model_, ctx_, items):
        calls["n"] += 1
        calls["arms"] |= {t.entry["arm"] for t, _ in items}
        return real_plan(model_, ctx_, items)

    g8.plan_batch = counting
    try:
        n_goals = len(goals)
        cfg = g8.evaluation_configs(goals, 3)
        L = g8.Ledger(dict(g8.TICK_BUDGET, eval_prefix=3 * sum(g.t for g in goals), eval_control=3 * n_goals * ug.BUDGET))
        vec = _FakeVec(out / "eval", 3, horizon=3600)
        # the scrambled pairing needs 40 goals in production; here pi maps within the 3 synthetic goals
        orig = ug.scrambled
        ug.scrambled = lambda k: (int(k) + 1) % n_goals
        try:
            trials = g8.drive(vec, cfg, phase="evaluation", ledger=L, clock=g8.Clock(memory=lambda: None),
                              n_candidates=17, goals=goals, model=model, ctx=ctx, track=track)
        finally:
            ug.scrambled = orig
    finally:
        g8.plan_batch = real_plan
    check(len(trials) == 3 * n_goals, f"{len(trials)} trials")
    check(L.used["eval_prefix"] == 3 * sum(g.t for g in goals), f"prefix ticks {L.used['eval_prefix']}")
    check(calls["arms"] <= {"P", "S"}, f"RC reached the model: {calls['arms']}")
    for r in trials:
        g = goals[r["goal_k"]]
        check(r["prefix_identity"] and r["prefix_identity"]["ok"], f"{r['entry']}: start identity")
        check([tuple(w) for w in r["words"][:g.t]] == g.prefix, f"{r['entry']}: prefix words")
        ctl = len(r["words"]) - g.t
        check(1 <= ctl <= ug.BUDGET, f"{r['entry']}: {ctl} controlled ticks")
        if r["reach_tick"] is not None:
            row = r["rows"][r["reach_tick"]]
            check(abs(row[us.F["x"]] - g.x) <= ug.BOX and abs(row[us.F["y"]] - g.y) <= ug.BOX, "scored on g")
            check(r["truncation_reason"] == "goal_reached" and r["reach_tick"] == len(r["words"]), "reach ends the trial")
        else:
            check(r["truncation_reason"] == "trial_budget" and ctl == ug.BUDGET, "budget end")
        if r["arm"] == "RC":
            regen = up.rc_words(f"m7u1|{g8.GATE_SEED}|goal|{r['goal_k']}", 17, ctl)
            check([tuple(w) for w in r["words"][g.t:]] == regen, f"{r['entry']}: RC words are not candidate 0 streams")
        ev = r["evidence"]
        check([d["at_tick"] for d in ev] == r["decisions"], f"{r['entry']}: one evidence record per decision")
        check(all(("scores" in d) == (r["arm"] != "RC") for d in ev),
              f"{r['entry']}: predictions only where the model ran")
        for d in ev:
            check(d["candidates"].shape == (17, up.H, 2), f"{r['entry']}: candidate record shape")
            if "scores" in d:
                check(int(np.argmin(d["scores"])) == d["chosen"], f"{r['entry']}: chosen != argmin of recorded scores")
                check(d["pred_x"].shape == (3, 17, up.H), f"{r['entry']}: prediction shape")
    by = {(r["goal_k"], r["arm"]): r for r in trials}
    for k in range(n_goals):                 # common random numbers: identical first candidates across the arms
        c0 = [by[(k, a)]["evidence"][0]["candidates"] for a in ("P", "RC", "S")]
        check(np.array_equal(c0[0], c0[1]) and np.array_equal(c0[1], c0[2]), f"goal {k}: first candidates differ")
    # a wrong expected start row makes the run invalid (never a result)
    bad = [ug.Goal(**{**goals[0].__dict__, "expected_start_row": [v + 1.0 for v in goals[0].expected_start_row]})]
    vec2 = _FakeVec(out / "eval_bad", 1, horizon=3600)
    try:
        g8.drive(vec2, g8.evaluation_configs(bad, 1), phase="evaluation", ledger=g8.Ledger(),
                 clock=g8.Clock(memory=lambda: None), n_candidates=17, goals=bad, model=model, ctx=ctx, track=track)
        check(False, "a start-state mismatch was not detected")
    except g8.IntegrityStop:
        pass
    return {"trials": len(trials), "model_batches": calls["n"], "prefix_ticks": L.used["eval_prefix"],
            "control_ticks": L.used["eval_control"], "reached": sum(r["reach_tick"] is not None for r in trials)}


def unit_gate_stops(out: Path) -> Dict[str, Any]:
    """run_gate: a P1 mismatch is INVALID; a wall-cap stop in collection is INCOMPLETE; neither retries or extends."""
    import m7u_gate as g8

    def env_factory(root, run_id, role, settings):
        return _FakeSingle(Path(root), horizon=30)

    p1 = [{"entry": "p1a", "kind": "collect", "words": [[0, 0]] * 30}]
    st = g8.run_gate(settings=None, choice={"n_candidates": 17, "train_steps": 10}, root=out / "g1",
                     venv_factory=lambda *a: _FakeVec(out / "g1v", 5, 30), env_factory=env_factory,
                     clock=g8.Clock(memory=lambda: None), p1_entries=p1,
                     artifact_words=lambda d: [(1, 0)] * 30)
    check(st["decision"]["outcome"] == "INVALID", f"P1 mismatch gave {st['decision']['outcome']}")
    t = [0.0]

    def now() -> float:
        t[0] += 0.5
        return t[0]

    words = {}

    def aw(d):
        return words.get(str(d), [(0, 0)] * 30)

    fs = _FakeSingle(out / "g2s", horizon=30)

    def env_factory2(root, run_id, role, settings):
        return fs

    st2 = g8.run_gate(settings=None, choice={"n_candidates": 17, "train_steps": 10}, root=out / "g2",
                      venv_factory=lambda *a: _FakeVec(out / "g2v", 5, 3600), env_factory=env_factory2,
                      clock=g8.Clock(now=now, memory=lambda: None, caps=dict(g8.WALL_CAPS_S, collection=40.0)),
                      p1_entries=[{"entry": "p1a", "kind": "collect", "words": [[0, 0]] * 30}],
                      artifact_words=lambda d: [(0, 0)] * 30)
    check(st2["decision"]["outcome"] == "INCOMPLETE" and "collection" in st2["decision"]["reason"],
          f"collection wall cap gave {st2['decision']}")
    return {"p1_mismatch": st["decision"]["outcome"], "wall_cap": st2["decision"]["outcome"],
            "ledger_at_stop": st2["ledger"]["used"]}


def unit_real_v4_stack_on_capture(out: Path) -> Dict[str, Any]:
    """The REAL v4 wrapper with the M7u probe and trial wrappers over recorded replies (read-only; rl/m7s_tests.py's
    recorded-reply stand-in): a replay entry streams rows equal to the recorded replies' rows and writes the sidecar;
    a trial entry checks the start state at the prefix end and ends as goal_reached on the first valid reach."""
    import m7q_obs as mq
    import m7s_tests as mst
    import m7u_worker as uw

    name, d, rows, words = captures()[3]
    wl = [tuple(int(v) for v in w) for w in words]
    # replay entry (collect kind)
    inner = mst._FakeTrack1(d, wl)
    probe = uw.M7uProbeWrapper(inner, base=inner.base)
    v4 = mq.EntityObsV4Wrapper(probe, base=inner.base, character="mario")
    probe.reply_source = lambda: v4._last_reply
    tracker = mst._TrackerStub(out / "replay")
    trial = uw.M7uTrialWrapper(v4, probe=probe, v4=v4, tracker=tracker, rank=0)
    trial.m7u_configure({"mode": "replay", "phase": "t", "entries": [{"entry": "r", "kind": "collect",
                                                                     "words": [list(w) for w in wl]}]})
    tracker.begin()
    _o, info = trial.reset()
    check(trial.last_reset_record["world_digest"] == us.world_digest(us.static_world_pinned()), "reset world digest")
    streamed = [np.array(trial.last_reset_record["row"])]
    for k, w in enumerate(wl):
        if k == len(wl) - 1:
            tracker.end("horizon")
        _o, _r, term, trunc, info = trial.step(np.array(w))
        streamed.append(np.array(info["m7u"]["row"]))
    check(np.array_equal(np.stack(streamed), rows, equal_nan=True), "streamed rows differ from the recorded replies")
    side = uw.read_sidecar(Path(tracker.done[-1]["artifact_dir"]) if tracker.done else Path(tracker.pending["artifact_dir"]))
    check(np.array_equal(side["rows"], rows, equal_nan=True), "sidecar rows")
    # trial entry: goal = the recorded airborne state 64 ticks after a start where one exists
    t = next(t for t in range(ug.T_MIN, ug.T_MAX) if rows[t + ug.HZ, us.F["ga"]] == 1 and rows[t + ug.HZ, us.F["valid"]] == 1)
    gx, gy = rows[t + ug.HZ, us.F["x"]], rows[t + ug.HZ, us.F["y"]]
    first = next(k for k in range(t + 1, len(rows)) if rows[k, us.F["valid"]] == 1 and rows[k, us.F["ga"]] == 1
                 and abs(rows[k, us.F["x"]] - gx) <= ug.BOX and abs(rows[k, us.F["y"]] - gy) <= ug.BOX)
    inner2 = mst._FakeTrack1(d, wl)
    probe2 = uw.M7uProbeWrapper(inner2, base=inner2.base)
    v42 = mq.EntityObsV4Wrapper(probe2, base=inner2.base, character="mario")
    probe2.reply_source = lambda: v42._last_reply
    tracker2 = mst._TrackerStub(out / "trial")
    trial2 = uw.M7uTrialWrapper(v42, probe=probe2, v4=v42, tracker=tracker2, rank=0)
    trial2.m7u_configure({"mode": "trial", "phase": "t", "entries": [{
        "entry": "g", "kind": "trial", "t": t, "budget": ug.BUDGET, "goal": [gx, gy], "prefix": [list(w) for w in wl[:t]],
        "expected_start_row": [None if np.isnan(v) else v for v in rows[t]]}]})
    tracker2.begin()
    trial2.reset()
    end = None
    for k, w in enumerate(wl):
        if k + 1 == first:
            tracker2.end("horizon", truncation=uw.END_GOAL)
        _o, _r, term, trunc, info = trial2.step(np.array(w))
        rec = info["m7u"]
        if k + 1 == t:
            check(rec.get("prefix_identity", {}).get("ok"), "start identity at the prefix end")
        if term or trunc:
            end = (k + 1, rec.get("truncation_reason"), rec.get("reach_tick"))
            break
    check(end == (first, uw.END_GOAL, first), f"trial end {end}, want ({first}, goal_reached, {first})")
    return {"capture": name, "rows": len(rows), "trial_start": t, "first_reach": first}


def unit_worker_stack_assembly(out: Path) -> Dict[str, Any]:
    """build_worker_env_m7u assembles the documented layer order with the native environment class substituted (no
    process can start: the stand-in never launches anything)."""
    import gymnasium as gym_

    import btt_parallel as bp
    import m7u_worker as uw
    from btt_parallel import RunCoordinator, initial_coordination_state

    class NoLaunchBase(gym_.Env):
        observation_space = gym_.spaces.Box(-1, 1, (15,), np.float32)
        action_space = gym_.spaces.Dict({})
        max_episode_steps = 3600
        standby = None

        def __init__(self, *a, **k):
            self.kw = k

        def reset(self, **kw):
            raise AssertionError("the assembly test never resets")

    settings = uw.env_settings()
    root = out / "stack"
    coord = root / "coordination"
    RunCoordinator.create(coord, initial_coordination_state("m7u_test", "test", None))
    spec = uw.worker_spec(root, 0, "m7u_test", "test", settings, coord)
    rt = Path(spec.worker_dir) / "runtime"
    rt.mkdir(parents=True, exist_ok=True)
    (rt / "runtime_manifest.json").write_text("{}", encoding="utf-8")
    real = bp.M7BattleShipBTTEnv
    bp.M7BattleShipBTTEnv = NoLaunchBase
    try:
        env = uw.build_worker_env_m7u(spec)
    finally:
        bp.M7BattleShipBTTEnv = real
    chain, e = [], env
    while hasattr(e, "env"):
        chain.append(type(e).__name__)
        e = e.env
    chain.append(type(e).__name__)
    want = ["M7uWorkerWrapper", "EpisodeStatsWrapper", "M7uTrialWrapper", "EntityObsV4Wrapper", "Track1PolicyWrapper",
            "EpisodeRecordingWrapper", "M7RewardWrapper", "M7uProbeWrapper", "NoLaunchBase"]
    check(chain == want, f"layer order {chain}")
    check(dict(spec.extra_env).get("SSB64_RL_INPUT") == "1", "input diagnostic flag")
    return {"chain": chain}


def unit_approval_refusal(out: Path) -> Dict[str, Any]:
    """The production approval_status() run against an ISOLATED temporary record, so the result never depends on
    whether the repository's approval record exists. Refused: missing, not APPROVED, APPROVED with any identity field
    or code hash that differs. Never accepted: unreadable JSON (raises). Accepted: APPROVED with the current identity.
    The repository's record, present or absent, is left untouched."""
    import m7u_gate as g8

    real, real_root = g8.APPROVAL, g8.REPO_ROOT
    real_before = hashlib.sha256(real.read_bytes()).hexdigest() if real.is_file() else None
    root = Path(tempfile.mkdtemp(prefix="approval_", dir=out))
    tmp = root / "docs" / real.name
    tmp.parent.mkdir(parents=True)
    ident = g8.identity()
    results: Dict[str, Any] = {}

    def status(rec: Optional[Mapping[str, Any]]) -> Tuple[bool, str]:
        if rec is not None:
            tmp.write_text(json.dumps(rec, default=str), encoding="utf-8")
        return g8.approval_status()

    g8.APPROVAL, g8.REPO_ROOT = tmp, root
    try:
        ok, why = status(None)
        check(not ok and "no approval record" in why, f"missing record: {ok} {why}")
        results["missing"] = why
        ok, why = status(dict(ident, approval="PENDING (a reviewer replaces this with APPROVED <name> <date>)"))
        check(not ok, f"a PENDING record was accepted: {why}")
        results["pending"] = why
        altered = {"choice": dict(ident["choice"], n_candidates=32),
                   "tick_budget": dict(ident["tick_budget"], total=ident["tick_budget"]["total"] + 1),
                   "memory_cap_mb": ident["memory_cap_mb"] + 1, "rule_sha256": "0" * 64,
                   "code": dict(ident["code"], **{"rl/m7u_planner.py": "0" * 64})}
        for key, value in altered.items():
            ok, why = status(dict(ident, approval="APPROVED test", **{key: value}))
            check(not ok and ("code:" if key == "code" else key) in why, f"altered {key} was accepted: {why}")
            results[f"altered_{key}"] = why
        tmp.write_text("{not json", encoding="utf-8")
        try:
            g8.approval_status()
            check(False, "an unreadable record was accepted")
        except ValueError as exc:
            results["unreadable"] = f"raises {type(exc).__name__}"
        ok, why = status(dict(ident, approval="APPROVED test"))
        check(ok and why == "approved", f"a valid record was refused: {why}")
        results["valid"] = why
    finally:
        g8.APPROVAL, g8.REPO_ROOT = real, real_root
    real_after = hashlib.sha256(real.read_bytes()).hexdigest() if real.is_file() else None
    check(real_after == real_before, "the repository's approval record changed")
    check(g8.APPROVAL == real and g8.REPO_ROOT == real_root, "module paths not restored")
    results["repository_record_present"] = real_before is not None
    return results


UNITS: Dict[str, Callable[[Path], Dict[str, Any]]] = {
    "unit_expansion_and_coverage": unit_expansion_and_coverage,
    "unit_streams_and_retention": unit_streams_and_retention,
    "unit_score": unit_score,
    "unit_rows_and_encoding": unit_rows_and_encoding,
    "unit_world_and_track": unit_world_and_track,
    "unit_featurisation_equivalence": unit_featurisation_equivalence,
    "unit_model_masks_rollout_training": unit_model_masks_rollout_training,
    "unit_import_isolation": unit_import_isolation,
    "unit_goals": unit_goals,
    "unit_rule": unit_rule,
    "unit_ledger_clock": unit_ledger_clock,
    "unit_driver_collection_and_single": unit_driver_collection_and_single,
    "unit_driver_evaluation": unit_driver_evaluation,
    "unit_gate_stops": unit_gate_stops,
    "unit_real_v4_stack_on_capture": unit_real_v4_stack_on_capture,
    "unit_worker_stack_assembly": unit_worker_stack_assembly,
    "unit_approval_refusal": unit_approval_refusal,
}


def e2e(out: Path) -> Dict[str, Any]:
    """run_gate through EVERY phase at production counts (92 collection episodes, 12 held out, 40 goals x 3 arms,
    replays, rule) over the synthetic stand-in: fake horizon 700 ticks, N = 17 candidates, 40 optimizer steps. Exercises
    the driver's glue; its outcome says nothing about Mario."""
    import m7u_gate as g8

    words_by_dir: Dict[str, List[Tuple[int, int]]] = {}
    vecs: List[_FakeVec] = []
    singles: List[_FakeSingle] = []

    def venv_factory(root, run_id, role, settings):
        v = _FakeVec(Path(root), 5, horizon=700)
        vecs.append(v)
        return v

    def env_factory(root, run_id, role, settings):
        s = _FakeSingle(Path(root), horizon=700)
        singles.append(s)
        return s

    def artifact_words(d):
        for st in [t for v in vecs for _tw, t in v.stacks] + [s.tracker for s in singles]:
            eid = Path(d).name
            if eid in st.words and str(st.artifact_root / eid) == str(d):
                return [tuple(w) for w in st.words[eid]]
        raise KeyError(d)

    p1 = [{"entry": "p1a", "kind": "collect", "words": [[0, 0]] * 700}]
    t0 = time.perf_counter()
    st = g8.run_gate(settings=None, choice={"n_candidates": 17, "train_steps": 40}, root=out / "gate",
                     venv_factory=venv_factory, env_factory=env_factory, clock=g8.Clock(memory=lambda: None),
                     p1_entries=p1, artifact_words=artifact_words)
    d = st["decision"]
    check(d["outcome"] in ("PASS", "NULL", "INCONCLUSIVE"), f"e2e decision {d.get('outcome')}: {d.get('reason')} "
          f"{st['integrity']['problems'][:3]}")
    check(st["ledger"]["total"] <= g8.TICK_BUDGET["total"], "ledger over budget")
    check(all(r["ok"] for r in st["phases"]["replays"]), "a replay was not exact")
    check(not ur.scope_problems(d["summary"].replace(ug.SCOPE, "")), "summary wording")
    gd = out / "gate" / "_gate"
    coll = json.loads((gd / "collection.json").read_text(encoding="utf-8"))
    check(len(coll["episodes"]) == g8.N_COLLECT and not set(coll["train_ids"]) & set(coll["heldout_ids"]),
          "collection manifest / split")
    with np.load(gd / "model_inputs_train.npz") as tr, np.load(gd / "model_inputs_heldout.npz") as ho:
        check(set(tr["episode_ids"].tolist()) == set(coll["train_ids"])
              and set(ho["episode_ids"].tolist()) == set(coll["heldout_ids"]), "train / held-out model inputs separated")
        check(len(tr["dense"]) == st["phases"]["train"]["transitions"], "saved training inputs")
    goals = json.loads((gd / "goals.json").read_text(encoding="utf-8"))["goals"]
    trial_files = sorted((gd / "trials").glob("*.npz"))
    check(len(trial_files) == 3 * ug.N_GOALS, f"{len(trial_files)} trial evidence files")
    for f in trial_files:
        with np.load(f) as z:
            meta = json.loads(z["meta"].tobytes().decode("utf-8"))
            g = goals[meta["goal_k"]]
            check([list(w) for w in z["words"][:g["t"]].tolist()] == [list(w) for w in g["prefix"]],
                  f"{f.name}: supplied prefix")
            check(("scores" in z.files) == meta["model_evaluated"], f"{f.name}: predictions")
            check(len(z["chosen"]) == len(z["candidates"]), f"{f.name}: candidate records")
    with np.load(gd / "model_inputs_trials.npz") as mt:
        check(len(set(mt["episode_ids"].tolist())) == 3 * ug.N_GOALS, "trial model inputs")
    return {"decision": {k: d.get(k) for k in ("outcome", "n", "vs_RC", "vs_S", "null_reading")},
            "ledger": st["ledger"]["used"], "phase_wall_s": st["clock"]["phase_wall_s"],
            "replays": len(st["phases"]["replays"]), "wall_s": round(time.perf_counter() - t0, 1)}


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["unit", "e2e"])
    ap.add_argument("--out", default=None)
    ap.add_argument("--only", default=None)
    a = ap.parse_args(argv)
    base = Path(a.out) if a.out else Path(tempfile.mkdtemp(prefix="m7u_tests_"))
    if (REPO_ROOT / "runs") in base.resolve().parents:
        print("refused: test outputs never go under runs/")
        return 2
    if a.mode == "e2e":
        try:
            r = {"ok": True, **e2e(base)}
        except Exception as exc:  # noqa: BLE001
            r = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-3000:]}
        (base / "m7u_e2e.json").write_text(json.dumps(r, indent=1, default=str) + "\n", encoding="utf-8")
        print(json.dumps({k: v for k, v in r.items() if k != "trace"}, default=str)[:2000])
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
    (base / "m7u_unit.json").write_text(json.dumps(results, indent=1, default=str) + "\n", encoding="utf-8")
    for name, r in results.items():
        print(f"{'ok  ' if r['ok'] else 'FAIL'} {name} ({r['s']} s)" + ("" if r["ok"] else f": {r['error']}"))
    print(f"m7u unit: {len(results) - len(failed)}/{len(results)} passed; report {base / 'm7u_unit.json'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
