#!/usr/bin/env python3
"""Offline failure analysis of the completed M7s gate m7s1 (outcome 3, inconclusive). Zero native ticks: no game is
launched and no optimizer step is taken. Reads only this run's records under runs/m7s/gate/ (episode artifacts, goal
sidecars, init.pt / R_final.pt, R_train_chunks.json, state.json) and the pinned source; writes a parse cache and
m7s_failure_analysis.json to --out (keep it outside runs/ so the D: coverage of runs/ stays exact).

    python rl/tools/m7s_failure_analysis.py --out <dir>

Report: docs/rl_gcsl_return_m7s_failure_analysis.md. Sections:
  audit     relabel invariants rebuilt from the recorded episodes with the unchanged m7s_goal.sample_examples;
            relabel horizon / sampling-weight distribution
  collector run_phase's stored (o_t, a_t, c_(t+1)) alignment on the synthetic in-process workers of m7s_tests
  params    init.pt -> R_final.pt change per layer vs the pure-noise Adam scale lr * sqrt(steps)
  crn       R vs U word sequences under common random numbers: phase-B pairs vs chunk boundaries, evaluation pairs
  labels    action marginals; held-out information of the recorded action about the relabelled / h-ahead goal offset
            given a coarse state (cell, contact, 8-tick motion sign, time bucket), with shuffled-goal controls
  segments  held-out information of k-tick action segments about the fighter's cell offset h ticks later
  contexts  the same per-tick measure split by landing / airborne / stationary context (action-lock proxies)
State is coarse by necessity: the v3 observations the learner saw were never stored. Every information number is a
held-out cross-entropy difference with episode-level folds and an episode bootstrap; it is diagnostic, not causal.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "rl"))

import m7s_goal as mg  # noqa: E402

GATE = REPO / "runs" / "m7s" / "gate"
SEEDS = (0, 1, 2)
PHASES = ("phase_a", "R_phase_b", "U_phase_b", "R_eval", "U_eval")
NONE = -99
CONTACT_INDEX = {c: k for k, c in enumerate(mg.CONTACT_CLASSES)}
TIME_EDGES = (0, 300, 900, 1800, 3601)
H_EDGES = (1, 17, 65, 257, 1025, 3601)
FOLDS = 4                 # episode-hash folds (stratify the null only)
PERMS = 10
LN72 = math.log(72)


# -- parsing ---------------------------------------------------------------------------------------------------------------


def _track1_maps() -> Tuple[Dict[Tuple[int, int], int], Dict[int, int]]:
    from btt_learning import TRACK1_BUTTON_TABLE, TRACK1_STICK_TABLE

    return ({(int(x), int(y)): k for k, (x, y) in enumerate(TRACK1_STICK_TABLE)},
            {int(b): k for k, b in enumerate(TRACK1_BUTTON_TABLE)})


def parse_episode(art: Path, smap, bmap) -> Dict[str, Any]:
    sticks, buttons, ticks = [], [], []
    with open(art / "actions.jsonl", encoding="utf-8") as fp:
        for line in fp:
            r = json.loads(line)
            sticks.append(smap[(r["stick_x"], r["stick_y"])])
            buttons.append(bmap[r["buttons"]])
            ticks.append(r["consumed_tick"])
    with gzip.open(art / mg.SIDECAR_FILE, "rt", encoding="utf-8") as fp:
        side = json.load(fp)
    meta = json.loads((art / "metadata.json").read_text(encoding="utf-8"))
    cells = side["cells"]
    T = len(sticks)
    if len(cells) != T or ticks != list(range(T)):
        raise RuntimeError(f"{art}: {T} words, {len(cells)} cells, ticks 0..{ticks[-1] if ticks else None}")
    ci = np.full(T, NONE, np.int16)
    cj = np.full(T, NONE, np.int16)
    cc = np.full(T, NONE, np.int16)
    for k, key in enumerate(cells):
        if key is not None:
            i, j, c = mg.parse_key(key)
            ci[k], cj[k], cc[k] = i, j, c
    fell = (meta["labels"].get("end_reason") == "fall")
    valid = ci != NONE
    if fell and T:
        valid[-1] = False                      # the fatal-fall tick is never valid (mg.valid_cells)
    return {"episode_id": side["episode_id"], "phase": side["phase"], "rank": side["rank"],
            "worker_episode": side["worker_episode"], "plan_entry": side["plan_entry"], "T": T,
            "stick": np.array(sticks, np.int8), "button": np.array(buttons, np.int8), "ci": ci, "cj": cj, "cc": cc,
            "valid": valid, "end_reason": meta["labels"].get("end_reason"),
            "startup_mode": meta["labels"].get("startup_mode"), "commanded": side["commanded"],
            "digest": side["native_action_digest"], "targets_broken": meta["labels"].get("targets_broken")}


def load(cache: Path) -> Dict[Tuple[int, str], List[Dict[str, Any]]]:
    cache.mkdir(parents=True, exist_ok=True)
    smap, bmap = _track1_maps()
    out: Dict[Tuple[int, str], List[Dict[str, Any]]] = {}
    for s in SEEDS:
        for ph in PHASES:
            f = cache / f"s{s}_{ph}.npz"
            if f.is_file():
                z = np.load(f, allow_pickle=True)
                out[(s, ph)] = list(z["episodes"])
                continue
            eps = [parse_episode(a, smap, bmap)
                   for a in sorted((GATE / f"s{s}" / ph / "workers").glob("w*/artifacts/episode_*"))]
            np.savez_compressed(f, episodes=np.array(eps, dtype=object))
            out[(s, ph)] = eps
    return out


# -- estimation machinery ----------------------------------------------------------------------------------------------
#
# Information is the plug-in conditional mutual information I(X; G | S) in nats per row, compared with an exact
# within-stratum permutation of X (PERMS times). The permutation keeps every stratum's X and G marginals, so it
# carries the plug-in estimator's finite-sample bias; the estimate is observed - null mean. It is exact only when X
# is exchangeable across rows (see cmi_test). Two earlier estimators were discarded (see the report): a held-out
# backoff-count predictor (an independent but skewed variable 'gained' up to +11 millinats by undoing the parent
# level's over-smoothing) and a cross-episode resampling null (sampling with replacement from small strata, duplicated
# relabel rows and overlapping segments all made the observed bias larger than the null's).


def fold_of(episode_id: str) -> int:
    return int(hashlib.sha256(episode_id.encode()).hexdigest()[:8], 16) % FOLDS


def cmi(x: np.ndarray, nx: int, g: np.ndarray, ng: int, s: np.ndarray) -> float:
    """Plug-in I(X; G | S) in nats (x in [0, nx), g in [0, ng), s any integer stratum code)."""
    s = np.unique(s, return_inverse=True)[1].astype(np.int64)
    x = x.astype(np.int64)
    g = g.astype(np.int64)
    u, c = np.unique((s * nx + x) * ng + g, return_counts=True)
    su, xu, gu = u // (nx * ng), (u // ng) % nx, u % ng
    ns = np.bincount(s).astype(np.float64)
    nsx = np.bincount(s * nx + x, minlength=len(ns) * nx).astype(np.float64)
    nsg = np.bincount(s * ng + g, minlength=len(ns) * ng).astype(np.float64)
    c = c.astype(np.float64)
    return float((c / len(x) * np.log(c * ns[su] / (nsx[su * nx + xu] * nsg[su * ng + gu]))).sum())


def permute_within(values: np.ndarray, strata: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """An exact permutation of `values` inside each stratum (no replacement: every stratum keeps its multiset)."""
    key = strata.astype(np.int64)
    o1 = np.lexsort((rng.random(len(key)), key))
    o2 = np.lexsort((rng.random(len(key)), key))
    out = np.empty_like(values)
    out[o1] = values[o2]
    return out


def cmi_test(x, nx, g, ng, s, ep, rng, perms: int = PERMS) -> Dict[str, Any]:
    """Observed plug-in I(X; G | S) against an exact within-stratum permutation of X (a conditional permutation test).
    Valid when X is exchangeable across rows within a stratum under independence: the callers pass per-tick
    actions (drawn with fresh uniforms every tick), one relabelled example per (episode, tick), or non-overlapping
    action segments - never overlapping windows or duplicated rows, which would make the observed statistic's
    finite-sample bias larger than the null's."""
    obs = cmi(x, nx, g, ng, s)
    null = np.array([cmi(permute_within(x, s, rng), nx, g, ng, s) for _ in range(perms)])
    sd = float(null.std(ddof=1)) if perms > 1 else float("nan")
    return {"excess_mnat": 1000 * (obs - float(null.mean())), "null_sd_mnat": 1000 * sd,
            "z": (obs - float(null.mean())) / sd if sd > 0 else float("nan"),
            "observed_mnat": 1000 * obs, "null_mean_mnat": 1000 * float(null.mean()),
            "rows": int(len(x)), "episodes": int(len(np.unique(ep)))}


# -- per-tick features ---------------------------------------------------------------------------------------------------


def cell_id(i, j, c):
    cidx = np.vectorize(lambda v: CONTACT_INDEX.get(int(v), len(CONTACT_INDEX)))(c) if np.ndim(c) else CONTACT_INDEX[int(c)]
    return (i.astype(np.int64) * mg.NY + j) * 10 + cidx


def tick_table(eps: Sequence[Dict[str, Any]]) -> Dict[str, np.ndarray]:
    """One row per action a_t (t >= 1) whose state s_t (the cell of tick t = cells[t - 1]) is valid."""
    rows: Dict[str, List[np.ndarray]] = {k: [] for k in ("ep", "t", "T", "stick", "button", "ci", "cj", "cc", "mot",
                                                         "tb", "since_land", "since_air", "still", "fold", "row0")}
    base = 0
    for e in eps:
        T = e["T"]
        if T < 3:
            continue
        ci, cj, cc, valid = e["ci"], e["cj"], e["cc"], e["valid"]
        t = np.arange(1, T)
        s_ok = valid[t - 1]
        # 8-tick motion sign of the state (cells of ticks t and t - 8)
        mot = np.full(T - 1, 9, np.int16)
        tp = t - 8
        ok8 = (tp >= 1) & s_ok
        ok8[ok8] &= valid[tp[ok8] - 1]
        di = np.sign(ci[t - 1].astype(int) - ci[np.maximum(tp, 1) - 1].astype(int))
        dj = np.sign(cj[t - 1].astype(int) - cj[np.maximum(tp, 1) - 1].astype(int))
        mot[ok8] = ((di + 1) * 3 + (dj + 1))[ok8]
        # landing / take-off recency (contact transitions of the recorded cells) and stationarity
        air = (cc == mg.AIR)
        ground = valid & ~air
        since_land = np.full(T, 10 ** 6, np.int32)
        since_air = np.full(T, 10 ** 6, np.int32)
        still = np.zeros(T, np.int32)
        last_land = last_air = -10 ** 6
        for k in range(T):
            if k > 0 and ground[k] and air[k - 1]:
                last_land = k
            if k > 0 and air[k] and ground[k - 1]:
                last_air = k
            since_land[k] = k - last_land
            since_air[k] = k - last_air
            if k > 0 and valid[k] and valid[k - 1] and ci[k] == ci[k - 1] and cj[k] == cj[k - 1] and cc[k] == cc[k - 1]:
                still[k] = still[k - 1] + 1
        sel = np.nonzero(s_ok)[0]
        tt = t[sel]
        rows["ep"].append(np.full(len(sel), e["episode_id"], dtype=object))
        rows["t"].append(tt)
        rows["T"].append(np.full(len(sel), T))
        rows["stick"].append(e["stick"][tt].astype(np.int64))
        rows["button"].append(e["button"][tt].astype(np.int64))
        rows["ci"].append(ci[tt - 1].astype(np.int64))
        rows["cj"].append(cj[tt - 1].astype(np.int64))
        rows["cc"].append(cc[tt - 1].astype(np.int64))
        rows["mot"].append(mot[sel].astype(np.int64))
        rows["tb"].append(np.searchsorted(TIME_EDGES, tt, side="right") - 1)
        rows["since_land"].append(since_land[tt - 1])
        rows["since_air"].append(since_air[tt - 1])
        rows["still"].append(still[tt - 1])
        rows["fold"].append(np.full(len(sel), fold_of(e["episode_id"])))
        rows["row0"].append(np.full(len(sel), base))
        base += T
    out = {k: np.concatenate(v) for k, v in rows.items()}
    out["cell"] = cell_id(out["ci"], out["cj"], out["cc"])
    out["S"] = (out["cell"] * 10 + out["mot"]) * 4 + out["tb"]
    return out


def future(eps: Sequence[Dict[str, Any]], tab: Dict[str, np.ndarray], h: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """For each row (state at tick t), the cell of tick t + h: (ok, i, j, contact)."""
    by_id = {e["episode_id"]: e for e in eps}
    ok = np.zeros(len(tab["t"]), bool)
    gi = np.zeros(len(ok), np.int64)
    gj = np.zeros(len(ok), np.int64)
    gc = np.zeros(len(ok), np.int64)
    start = 0
    ep = tab["ep"]
    while start < len(ep):
        e = by_id[ep[start]]
        end = start + 1
        while end < len(ep) and ep[end] == ep[start]:
            end += 1
        t = tab["t"][start:end]
        k = t + h - 1                                  # cells index of tick t + h
        inside = k < e["T"]
        kk = np.where(inside, k, 0)
        v = inside & e["valid"][kk]
        ok[start:end] = v
        gi[start:end] = e["ci"][kk]
        gj[start:end] = e["cj"][kk]
        gc[start:end] = e["cc"][kk]
        start = end
    return ok, gi, gj, gc


def offset_class(si, sj, gi, gj, gc) -> np.ndarray:
    """18 classes: sign of the goal-cell offset in x and y (relative to the state cell) x goal contact air / ground."""
    return ((np.sign(gi - si) + 1) * 3 + (np.sign(gj - sj) + 1)) * 2 + (gc != mg.AIR)


# -- sections --------------------------------------------------------------------------------------------------------------


def section_audit(data, rng) -> Dict[str, Any]:
    """Rebuild each seed's final training dataset (phase A + R phase B) and draw examples with the unchanged
    m7s_goal.sample_examples; check every invariant against the recorded words and cells."""
    out: Dict[str, Any] = {}
    for s in SEEDS:
        eps = data[(s, "phase_a")] + data[(s, "R_phase_b")]
        ed = []
        for e in eps:
            cells = [(int(i), int(j), int(c)) if v else None for i, j, c, v in zip(e["ci"], e["cj"], e["cc"], e["valid"])]
            T = e["T"]
            ed.append(mg.EpisodeData(episode_id=e["episode_id"], origin="x", obs=np.zeros((T, 1), np.float32),
                                     pos=np.zeros((T, 2), np.float32),
                                     actions=np.stack([e["stick"], e["button"]], 1).astype(np.int64), cells=cells))
        n = 20_000
        ex = mg.sample_examples(ed, n, mg.generator("audit", s))
        by = {e.episode_id: e for e in ed}
        bad = 0
        for k in range(n):
            e = by[str(ex["episode"][k])]
            t, h, b = int(ex["t"][k]), int(ex["h"][k]), int(ex["b"][k])
            g = tuple(int(v) for v in ex["cell"][k])
            ok = (0 <= t < t + h <= len(e.cells) and e.cells[t + h - 1] == g
                  and all(e.cells[j - 1] != g for j in range(t + 1, t + h)) and h <= b <= mg.HORIZON - t
                  and int(ex["stick"][k]) == int(e.actions[t, 0]) and int(ex["button"][k]) == int(e.actions[t, 1]))
            bad += not ok
        h = ex["h"]
        kmax = np.array([e.k_max for e in ed if e.k_max >= 1], np.float64)
        w = 1.0 / kmax                                  # per-tick sampling weight of an episode-uniform draw
        ess = (w * kmax).sum() ** 2 / ((w ** 2) * kmax).sum() / kmax.sum()
        ch = json.loads((GATE / f"s{s}" / "R_train_chunks.json").read_text())
        out[str(s)] = {"episodes": len(ed), "ticks": int(sum(e["T"] for e in eps)), "examples_checked": n,
                       "invariant_violations": bad,
                       "h_mean": float(h.mean()), "h_quantiles": [int(q) for q in np.quantile(h, [0.1, 0.25, 0.5, 0.75, 0.9])],
                       "share_h_le_16": float((h <= 16).mean()), "share_h_le_64": float((h <= 64).mean()),
                       "share_h_gt_256": float((h > 256).mean()), "b_equals_h_share": float((ex["b"] == h).mean()),
                       "goal_contact_air_share": float((ex["cell"][:, 2] == mg.AIR).mean()),
                       "logged_h_mean_last_chunk": ch[-1]["h_mean"], "logged_episodes_last_chunk": ch[-1]["episodes_available"],
                       "per_tick_sampling_ess_share": float(ess)}
    return out


def section_collector() -> Dict[str, Any]:
    """The one update-path link no earlier test covers: run_phase's stored (o_t, a_t, c_(t+1)) alignment. The real
    run_phase (store=True, no trainer: forward passes only, no optimizer step) drives the existing synthetic in-process
    workers of rl/m7s_tests.py, whose observation encodes the known position of the state before each action."""
    import tempfile

    import m7n_obs as mn
    import m7s_collect as mc
    import m7s_policy as mp
    import m7s_tests as T

    seed = 5
    root = Path(tempfile.mkdtemp(prefix="m7s_fa_collector_"))
    venv = T._world(seed, root)
    data: List[mg.EpisodeData] = []
    res = mc.run_phase(venv=venv, configs=mc.phase_configs("null", phase="A"), policy=mp.init_policy(seed), seed=seed,
                       phase="A", tick_cap=20 * 3600, store=True, dataset=data)
    agent0 = sum(int(np.prod(mn.SHAPES[k])) for k in mn.KEY_ORDER[:mn.KEY_ORDER.index(mn.AGENT_KEY)])
    path = lambda ep, k: (-3750.0 + 300.0 * (((k // 7) + ep) % 12), -3900.0 + 300.0 * (ep % 3))   # T._world's path
    # _finish appends the row and the dataset entry in the same order (the stub's episode ids repeat across workers)
    rows = [e for e in res.episodes if e["ticks"] > 0]
    if len(rows) != len(data):
        raise RuntimeError(f"{len(rows)} rows for {len(data)} dataset episodes")
    obs_bad = act_bad = cell_bad = checked = 0
    per_rank: Dict[int, List[Tuple[int, int]]] = {}
    for row, d in zip(rows, data):
        ep = int(d.episode_id[2:6])                      # _TrackerStub ids: ep<episodes_started>_<n>
        for t in range(len(d.cells)):
            checked += 1
            obs_bad += not math.isclose(float(d.obs[t, agent0]), path(ep, t)[0] / 2000.0, rel_tol=0, abs_tol=1e-6)
            want = mg.cell_of(*path(ep, t + 1), True, -1)
            cell_bad += d.cells[t] != want and not (t == len(d.cells) - 1 and d.cells[t] is None)
        per_rank.setdefault(int(row["rank"]), []).extend(tuple(int(v) for v in a) for a in d.actions)
    for i, rank in enumerate(venv.ranks):
        act_bad += per_rank.get(rank, []) != venv.sent[i]
    return {"episodes": len(data), "ticks_checked": checked, "obs_before_action_mismatches": obs_bad,
            "next_cell_mismatches": cell_bad, "workers_with_action_label_mismatch": act_bad,
            "note": "synthetic in-process workers; zero native ticks; no optimizer step"}


def section_params() -> Dict[str, Any]:
    import m7s_policy as mp

    out: Dict[str, Any] = {"noise_only_adam_rms": mp.LEARNING_RATE * math.sqrt(7000),
                           "max_coherent_drift": mp.LEARNING_RATE * 7000}
    for s in SEEDS:
        a, _ = mp.load_policy(GATE / f"s{s}" / "init.pt")
        b, bm = mp.load_policy(GATE / f"s{s}" / "R_final.pt")
        A, B = a.state_dict(), b.state_dict()
        layers = {}
        for k in A:
            d = (B[k] - A[k]).double()
            layers[k] = {"init_norm": float(A[k].double().norm()), "delta_norm": float(d.norm()),
                         "delta_rms": float(d.pow(2).mean().sqrt()), "delta_max": float(d.abs().max())}
        wj = (B["joint.weight"] - A["joint.weight"]).double()
        out[str(s)] = {"gradient_steps": bm.get("gradient_steps"), "layers": layers,
                       "joint_delta_trunk_cols": float(wj[:, :mp.TRUNK].norm()),
                       "joint_delta_goal_cols": float(wj[:, mp.TRUNK:].norm())}
    return out


def _first_diff(a: Dict[str, Any], b: Dict[str, Any]) -> Tuple[int, bool]:
    m = min(a["T"], b["T"])
    d = np.nonzero((a["stick"][:m] != b["stick"][:m]) | (a["button"][:m] != b["button"][:m]))[0]
    if len(d):
        return int(d[0]), False
    return m, a["T"] == b["T"]


def section_crn(data) -> Dict[str, Any]:
    """Same sampling seeds, same goals, same tick-0 start: R and U emit the same words until R's policy (updated after
    every 1,024 worker ticks of phase B) samples differently. Phase-B pairs locate the first divergence relative to R's
    chunk boundaries; evaluation pairs give the per-tick hazard of R_final vs U."""
    out: Dict[str, Any] = {}
    for s in SEEDS:
        R = {(e["rank"], e["worker_episode"]): e for e in data[(s, "R_phase_b")]}
        U = {(e["rank"], e["worker_episode"]): e for e in data[(s, "U_phase_b")]}
        cum: Dict[int, int] = {}
        pairs = []
        for key in sorted(R):
            r = R[key]
            w0 = cum.get(key[0], 0)
            cum[key[0]] = w0 + r["T"]
            if key not in U:
                continue
            d, same = _first_diff(r, U[key])
            pairs.append({"rank": key[0], "worker_episode": key[1], "worker_tick_start": w0, "first_diff": d,
                          "identical": same, "chunk_at_start": w0 // 1024, "chunk_at_diff": (w0 + d) // 1024,
                          "cells_equal_before_diff": bool(np.array_equal(r["ci"][:d], U[key]["ci"][:d])
                                                          and np.array_equal(r["cc"][:d], U[key]["cc"][:d]))})
        first = [p for p in pairs if p["worker_episode"] == 1]
        ev_r = {e["plan_entry"]: e for e in data[(s, "R_eval")]}
        ev_u = {e["plan_entry"]: e for e in data[(s, "U_eval")]}
        ev = [_first_diff(ev_r[k], ev_u[k])[0] for k in sorted(ev_r) if k in ev_u]

        def med(lo: int, hi: int) -> Optional[float]:
            v = [p["first_diff"] for p in pairs if lo <= p["chunk_at_start"] < hi and not p["identical"]]
            return float(np.median(v)) if v else None

        out[str(s)] = {"phase_b_pairs": len(pairs),
                       "first_episodes": [{k: p[k] for k in ("rank", "first_diff", "identical", "cells_equal_before_diff")}
                                          for p in first],
                       "pairs_diverging_before_first_chunk": sum(1 for p in pairs if not p["identical"]
                                                                 and p["worker_tick_start"] + p["first_diff"] < 1024),
                       "pairs_identical_whole_episode": sum(1 for p in pairs if p["identical"]),
                       "cells_equal_before_diff_all": all(p["cells_equal_before_diff"] for p in pairs),
                       "median_first_diff_by_chunk_at_start": {"1-9": med(1, 10), "10-34": med(10, 35), "35-70": med(35, 71)},
                       "eval_pairs": len(ev), "eval_first_diff_median": float(np.median(ev)),
                       "eval_hazard_per_tick": float(len(ev) / (np.sum(ev) + len(ev)))}
    return out


def _state_keys(cell, mot, tb, hb=None):
    """S_small = the goal-cell contract state (cell, contact); S_full adds the 8-tick motion sign and time bucket."""
    small = cell if hb is None else cell * 5 + hb
    full = (cell * 10 + mot) * 4 + tb
    return small, (full if hb is None else full * 5 + hb)


def section_labels(data, rng) -> Dict[str, Any]:
    """GCSL direction: information in the recorded action a_t (stick, button) about the goal offset, given the state."""
    out: Dict[str, Any] = {}
    for name, phs in (("R_train", ("phase_a", "R_phase_b")), ("U_phase_b", ("U_phase_b",))):
        st = np.concatenate([e["stick"] for s in SEEDS for ph in phs for e in data[(s, ph)]]).astype(int)
        bt = np.concatenate([e["button"] for s in SEEDS for ph in phs for e in data[(s, ph)]]).astype(int)
        ps = np.bincount(st, minlength=9) / len(st)
        pb = np.bincount(bt, minlength=8) / len(bt)
        out[f"marginal_{name}"] = {"ticks": int(len(st)), "stick": [round(float(x), 4) for x in ps],
                                   "button": [round(float(x), 4) for x in pb],
                                   "kl_stick_vs_uniform_mnat": 1000 * float((ps * np.log(ps * 9)).sum()),
                                   "kl_button_vs_uniform_mnat": 1000 * float((pb * np.log(pb * 8)).sum())}
    eps = [e for s in SEEDS for ph in ("phase_a", "R_phase_b") for e in data[(s, ph)]]
    tab = tick_table(eps)
    out["tick_rows"] = int(len(tab["t"]))
    Ss, Sf = _state_keys(tab["cell"], tab["mot"], tab["tb"])
    zero = np.zeros(len(Ss), np.int64)
    # unconditional control: does the (near-uniform) behaviour policy's action depend on the coarse state at all?
    out["action_vs_state"] = {head: {sname: cmi_test(tab[head], ny, np.unique(sk, return_inverse=True)[1],
                                                     int(len(np.unique(sk))), zero, tab["ep"], rng)
                                     for sname, sk in (("S_small", Ss), ("S_full", Sf))}
                              for head, ny in (("stick", 9), ("button", 8))}
    fixed = {}
    for h in (1, 4, 16, 64, 256, 1024):
        ok, gi, gj, gc = future(eps, tab, h)
        G = offset_class(tab["ci"][ok], tab["cj"][ok], gi[ok], gj[ok], gc[ok])
        fixed[str(h)] = {head: {sname: cmi_test(tab[head][ok], ny, G, 18, sk[ok], tab["ep"][ok], rng)
                                for sname, sk in (("S_small", Ss), ("S_full", Sf))}
                         for head, ny in (("stick", 9), ("button", 8))}
    out["fixed_horizon"] = fixed
    # the GCSL label distribution itself: relabelled (t, g = first visit at t + h, h) examples of the final datasets
    ed = []
    for e in eps:
        cells = [(int(i), int(j), int(c)) if v else None for i, j, c, v in zip(e["ci"], e["cj"], e["cc"], e["valid"])]
        T = e["T"]
        ed.append(mg.EpisodeData(episode_id=e["episode_id"], origin="x", obs=np.zeros((T, 1), np.float32),
                                 pos=np.zeros((T, 2), np.float32),
                                 actions=np.stack([e["stick"], e["button"]], 1).astype(np.int64), cells=cells))
    ex = mg.sample_examples(ed, 600_000, mg.generator("failure-analysis", "relabel"))
    by = {e["episode_id"]: e for e in eps}
    rows = {k: [] for k in ("ci", "cj", "cc", "mot", "tb", "gi", "gj", "gc", "h", "stick", "button", "ep")}
    seen = set()
    for k in np.nonzero(ex["t"] >= 1)[0]:
        e = by[str(ex["episode"][k])]
        tt = int(ex["t"][k])
        if not e["valid"][tt - 1] or (e["episode_id"], tt) in seen:
            continue                                   # one relabelled example per (episode, tick): no duplicated rows
        seen.add((e["episode_id"], tt))
        rows["ci"].append(e["ci"][tt - 1]); rows["cj"].append(e["cj"][tt - 1]); rows["cc"].append(e["cc"][tt - 1])
        p = tt - 8
        rows["mot"].append((np.sign(int(e["ci"][tt - 1]) - int(e["ci"][p - 1])) + 1) * 3
                           + (np.sign(int(e["cj"][tt - 1]) - int(e["cj"][p - 1])) + 1)
                           if p >= 1 and e["valid"][p - 1] else 9)
        rows["tb"].append(int(np.searchsorted(TIME_EDGES, tt, side="right") - 1))
        rows["gi"].append(int(ex["cell"][k][0])); rows["gj"].append(int(ex["cell"][k][1])); rows["gc"].append(int(ex["cell"][k][2]))
        rows["h"].append(int(ex["h"][k])); rows["stick"].append(int(ex["stick"][k])); rows["button"].append(int(ex["button"][k]))
        rows["ep"].append(str(ex["episode"][k]))
    R = {k: np.array(v) for k, v in rows.items()}
    R["ep"] = np.array(rows["ep"], dtype=object)
    cell = cell_id(R["ci"], R["cj"], R["cc"])
    hb = np.searchsorted(H_EDGES, R["h"], side="right") - 1
    rSs, rSf = _state_keys(cell, R["mot"], R["tb"], hb)
    G = offset_class(R["ci"], R["cj"], R["gi"], R["gj"], R["gc"])
    Gx = np.unique(cell_id(R["gi"], R["gj"], R["gc"]), return_inverse=True)[1]          # the exact goal cell
    rel: Dict[str, Any] = {"draws": int(len(ex["t"])), "examples": int(len(G)), "h_mean": float(R["h"].mean()),
                           "h_bucket_share": {f"{H_EDGES[b]}-{H_EDGES[b + 1] - 1}": float((hb == b).mean()) for b in range(5)}}
    for gname, gk, gn in (("offset18", G, 18), ("exact_cell", Gx, int(Gx.max()) + 1)):
        rel[gname] = {head: {sname: cmi_test(R[head], ny, gk, gn, sk, R["ep"], rng)
                             for sname, sk in (("S_small", rSs), ("S_full", rSf))}
                      for head, ny in (("stick", 9), ("button", 8))}
    rel["by_h_bucket_S_small_offset18"] = {
        f"{H_EDGES[b]}-{H_EDGES[b + 1] - 1}": {head: cmi_test(R[head][hb == b], ny, G[hb == b], 18, rSs[hb == b],
                                                              R["ep"][hb == b], rng)
                                               for head, ny in (("stick", 9), ("button", 8))}
        for b in range(5)}
    out["relabel"] = rel
    return out


def section_segments(data, rng) -> Dict[str, Any]:
    """Forward measure: information in the action segment [t, t + k) about the cell offset of tick t + h, given
    S_small, on non-overlapping windows (t a multiple of k). Summary = direction of the summed stick vector (dead zone 0.2 k) x any jump button (C-up / C-left)."""
    from btt_learning import TRACK1_STICK_TABLE

    sx = np.array([np.sign(v[0]) for v in TRACK1_STICK_TABLE])
    sy = np.array([np.sign(v[1]) for v in TRACK1_STICK_TABLE])
    eps = [e for s in SEEDS for ph in ("phase_a", "R_phase_b") for e in data[(s, ph)]]
    tab = tick_table(eps)
    offs: Dict[str, int] = {}
    parts: List[List[np.ndarray]] = [[], [], []]
    base = 0
    for e in eps:                       # cumulative stick-x, stick-y and jump counts, one leading zero per episode
        st = e["stick"].astype(int)
        jump = np.isin(e["button"].astype(int), (3, 4)).astype(int)
        for p, v in zip(parts, (sx[st], sy[st], jump)):
            p.append(np.concatenate([[0], np.cumsum(v)]))
        offs[e["episode_id"]] = base
        base += e["T"] + 1
    CX, CY, CJ = (np.concatenate(p) for p in parts)
    off = np.array([offs[x] for x in tab["ep"]], np.int64)
    out: Dict[str, Any] = {}
    for h in (16, 64, 256, 1024):
        ok, gi, gj, gc = future(eps, tab, h)
        G = offset_class(tab["ci"], tab["cj"], gi, gj, gc)
        for k in (1, 4, 16, 64):
            if k > h:
                continue
            m = ok & (tab["t"] + k <= tab["T"]) & (tab["t"] % k == 0)       # non-overlapping windows
            i0 = off + tab["t"]
            i1 = np.where(m, i0 + k, i0)
            nx_, ny_, nj = CX[i1] - CX[i0], CY[i1] - CY[i0], CJ[i1] - CJ[i0]
            dz = 0.2 * k
            dx = np.where(np.abs(nx_) <= dz, 0, np.sign(nx_))
            dy = np.where(np.abs(ny_) <= dz, 0, np.sign(ny_))
            summ = (((dx + 1) * 3 + (dy + 1)) * 2 + (nj > 0)).astype(np.int64)
            res = cmi_test(summ[m], 18, G[m], 18, tab["cell"][m], tab["ep"][m], rng)
            hs = np.bincount(summ[m], minlength=18) / m.sum()
            res["summary_entropy_nat"] = float(-(hs[hs > 0] * np.log(hs[hs > 0])).sum())
            out[f"h{h}_k{k}"] = res
    return out


def section_contexts(data, rng) -> Dict[str, Any]:
    """Forward measure at h = 16 (stick direction x jump at t -> cell offset 16 ticks later, given S_small), split by
    action-lock proxies built from the recorded contact transitions and cell stationarity."""
    eps = [e for s in SEEDS for ph in ("phase_a", "R_phase_b") for e in data[(s, ph)]]
    tab = tick_table(eps)
    ok, gi, gj, gc = future(eps, tab, 16)
    G = offset_class(tab["ci"], tab["cj"], gi, gj, gc)
    A = tab["stick"] * 2 + np.isin(tab["button"], (3, 4)).astype(np.int64)
    air = tab["cc"] == mg.AIR
    ctx = {"all": ok,
           "grounded_since_landing_ge48": ok & ~air & (tab["since_land"] >= 48),
           "grounded_since_landing_16_47": ok & ~air & (tab["since_land"] >= 16) & (tab["since_land"] < 48),
           "grounded_since_landing_lt16": ok & ~air & (tab["since_land"] < 16),
           "airborne_lt32_after_takeoff": ok & air & (tab["since_air"] < 32),
           "airborne_ge32_after_takeoff": ok & air & (tab["since_air"] >= 32),
           "same_cell_for_ge60_ticks": ok & (tab["still"] >= 60)}
    out: Dict[str, Any] = {}
    for name, m in ctx.items():
        out[name] = dict(cmi_test(A[m], 18, G[m], 18, tab["cell"][m], tab["ep"][m], rng),
                         share_of_rows=float(m.sum() / ok.sum()))
    return out




def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--sections", default="audit,collector,params,crn,labels,segments,contexts")
    a = ap.parse_args(argv)
    if str(a.out.resolve()).startswith(str((REPO / "runs").resolve())):
        raise SystemExit("--out must be outside runs/ (the D: coverage of runs/ stays exact)")
    a.out.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    data = load(a.out / "cache")
    res: Dict[str, Any] = {"tool": "m7s_failure_analysis_v3", "source": "runs/m7s/gate (this run's records only)",
                           "episodes": {f"s{s}_{ph}": len(data[(s, ph)]) for s in SEEDS for ph in PHASES},
                           "parse_s": round(time.perf_counter() - t0, 1)}
    fns = {"audit": section_audit, "collector": lambda d, r: section_collector(),
           "params": lambda d, r: section_params(), "crn": lambda d, r: section_crn(d),
           "labels": section_labels, "segments": section_segments, "contexts": section_contexts}
    for name in a.sections.split(","):
        t1 = time.perf_counter()
        res[name] = fns[name](data, np.random.default_rng(20260929))
        res[f"{name}_s"] = round(time.perf_counter() - t1, 1)
        (a.out / "m7s_failure_analysis.json").write_text(json.dumps(res, indent=1, default=str) + "\n", encoding="utf-8")
        print(f"{name} done ({res[f'{name}_s']} s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
