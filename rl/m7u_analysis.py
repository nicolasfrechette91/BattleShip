"""M7u gate m7u1: reported diagnostics (forward passes on the frozen ensemble only; never an input of the rule).

* attribution of every failed P trial: MODEL if, from some decision, rolling the words actually executed (from the
  recorded native state and history) makes a majority of members (>= 2 of 3) predict a reach of g before a predicted
  fall; PLAN otherwise. P successes the model did not predict at any decision are UNPREDICTED.
* witness test: does a majority of members predict that the goal's recorded continuation (64 words) reaches g?
* calibration: AUROC of the ensemble spread for a realized 4-word-block error > BOX, on held-out behaviour blocks and on
  executed P / S blocks.
* held-out accuracy: teacher-state one-step position error and status accuracy per class v2; 64-tick open-loop
  position error on held-out behaviour sequences.
* ambiguity flags per trial (omitted projectile / persistent state; see the implementation record): an owned projectile
  during control, a target break while Mario's attack is inactive, an air tornado after an earlier air tornado in the
  same airtime, shield use, and statuses whose hidden-state coverage is conditional (Turn, Squat, jab 1-3, down tilt).
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import torch

import m7q_status_table as st2
import m7u_goals as ug
import m7u_model as um
import m7u_planner as up
import m7u_state as us

CONDITIONAL_STATUSES = {18: "Turn", 28: "Squat", 190: "Attack11", 191: "Attack12", 220: "Attack13", 201: "AttackLw3"}
MAJORITY = 2


def majority_reach(roll: um.Rollout, goals: np.ndarray, lengths: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """(N,) majority predicted-reach flags and (E, N) per-member first reach index (H when none), counting only
    tau < length and tau < predicted fall. goals (N, 2)."""
    E, N, H = roll.x.shape
    tau = torch.arange(H)
    g = torch.tensor(goals, dtype=torch.float64)
    cheb = torch.maximum((roll.x - g[None, :, 0:1]).abs(), (roll.y - g[None, :, 1:2]).abs())
    valid = (tau[None, None, :] < torch.tensor(lengths)[None, :, None]) & (tau[None, None, :] < roll.fall_at[:, :, None])
    reach = valid & (cheb <= up.BOX) & roll.air
    first = torch.where(reach, tau.expand_as(reach), torch.full_like(reach, H, dtype=torch.long)).min(2).values
    maj = ((first < H).sum(0) >= MAJORITY).numpy()
    return maj, first.numpy()


def _pad(words: Sequence[Tuple[int, int]], H: int) -> np.ndarray:
    w = list(words)[:H]
    if not w:
        w = [(0, 0)]
    return np.array(w + [w[-1]] * (H - len(w)), dtype=np.int64)


def trial_attribution(model: um.DynamicsEnsemble, ctx: um.Context, trial: Mapping[str, Any]) -> Dict[str, Any]:
    """trial: rows (T+1, F), words (T, 2), t (prefix length), goal (x, y), decisions (control ticks), reached."""
    rows, words, t = np.asarray(trial["rows"]), np.asarray(trial["words"]), int(trial["t"])
    hist = us.history_sequence(rows, [tuple(int(v) for v in w) for w in words])
    starts = [t + int(a) for a in trial["decisions"] if t + int(a) < len(words)]
    if not starts:
        return {"class": "PLAN", "decisions": 0}
    plans = np.stack([_pad([tuple(w) for w in words[s:]], up.H) for s in starts])
    lengths = np.array([min(len(words) - s, up.H) for s in starts])
    roll = um.rollout(model, ctx, torch.tensor(rows[starts]), torch.tensor(hist[starts]), torch.tensor(plans))
    maj, _first = majority_reach(roll, np.tile(np.asarray(trial["goal"], dtype=np.float64), (len(starts), 1)), lengths)
    predicted = bool(maj.any())
    if trial.get("reached"):
        return {"class": "PREDICTED" if predicted else "UNPREDICTED", "decisions": len(starts)}
    return {"class": "MODEL" if predicted else "PLAN", "decisions": len(starts),
            "first_predicting_decision": int(np.nonzero(maj)[0][0]) if predicted else None}


def witness_accepted(model: um.DynamicsEnsemble, ctx: um.Context, goals: Sequence[ug.Goal],
                     start_rows: np.ndarray, start_hist: np.ndarray) -> np.ndarray:
    plans = np.stack([_pad(g.witness, up.H) for g in goals])
    roll = um.rollout(model, ctx, torch.tensor(start_rows), torch.tensor(start_hist), torch.tensor(plans))
    maj, _ = majority_reach(roll, np.array([[g.x, g.y] for g in goals]), np.array([len(g.witness) for g in goals]))
    return maj


def auroc(scores: np.ndarray, labels: np.ndarray) -> Optional[float]:
    s, y = np.asarray(scores, dtype=np.float64), np.asarray(labels, dtype=bool)
    npos, nneg = int(y.sum()), int((~y).sum())
    if npos == 0 or nneg == 0:
        return None
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s))
    sv = s[order]
    i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and sv[j + 1] == sv[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return float((ranks[y].sum() - npos * (npos + 1) / 2.0) / (npos * nneg))


def block_errors(model: um.DynamicsEnsemble, ctx: um.Context, rows: np.ndarray, hist: np.ndarray, words: np.ndarray,
                 starts: Sequence[int], k: int = up.EXEC) -> Tuple[np.ndarray, np.ndarray]:
    """For each start s (rows s..s+k valid): realized Chebyshev error of the ensemble-mean position after k recorded
    words, and the ensemble spread (max of the x / y std) at that point."""
    starts = [s for s in starts if s + k < len(rows)]
    if not starts:
        return np.zeros(0), np.zeros(0)
    plans = np.stack([_pad([tuple(w) for w in words[s:s + k]], k) for s in starts])
    roll = um.rollout(model, ctx, torch.tensor(rows[starts]), torch.tensor(hist[starts]), torch.tensor(plans))
    px, py = roll.x[:, :, k - 1], roll.y[:, :, k - 1]
    real = rows[np.array(starts) + k]
    err = np.maximum(np.abs(px.mean(0).numpy() - real[:, us.F["x"]]), np.abs(py.mean(0).numpy() - real[:, us.F["y"]]))
    spread = torch.maximum(px.std(0, unbiased=False), py.std(0, unbiased=False)).numpy()
    return err, spread


def heldout_accuracy(model: um.DynamicsEnsemble, ctx: um.Context, episodes: Sequence[um.Episode],
                     n_open_loop: int = 200) -> Dict[str, Any]:
    ts = um.build_transitions(ctx, episodes)
    n = len(ts.cur)
    out: Dict[str, Any] = {"transitions": n}
    if n == 0:
        return out
    with torch.no_grad():
        idx = torch.arange(n)[None, :].expand(model.members, -1)
        h = model.trunk(ts.dense[idx], ts.cur[idx], ts.prev[idx])
        d = um.decode_step(model, ctx, h)
    dx = d["h6"][:, :, 0].double() * um.H6_SCALE[0]
    dy = d["h6"][:, :, 1].double() * um.H6_SCALE[1]
    tdx = ts.targets["h6"][:, 0].double() * um.H6_SCALE[0]
    tdy = ts.targets["h6"][:, 1].double() * um.H6_SCALE[1]
    perr = torch.maximum((dx.mean(0) - tdx).abs(), (dy.mean(0) - tdy).abs()).numpy()
    s_ok = (d["s"] == ts.targets["s"][None]).double().mean(0).numpy()
    cls = ctx.status_class[ctx.idx_to_status[ts.targets["s"]].long().clamp(0, um.STATUS_LOOKUP - 1)].numpy()
    per_class = {}
    for c in np.unique(cls):
        m = cls == c
        per_class[st2.CLASSES[int(c)]] = {"n": int(m.sum()), "pos_err_median": round(float(np.median(perr[m])), 3),
                                          "pos_err_p95": round(float(np.quantile(perr[m], 0.95)), 3),
                                          "status_acc": round(float(s_ok[m].mean()), 4)}
    out.update({"pos_err_median": round(float(np.median(perr)), 4), "pos_err_p99": round(float(np.quantile(perr, 0.99)), 3),
                "status_acc": round(float(s_ok.mean()), 4), "per_class": per_class})
    # open loop, 64 recorded words from sha-ordered start ticks
    cands = []
    for e, ep in enumerate(episodes):
        for t in ug.usable_pairs(ep.rows, ep.fell, up.H):
            cands.append((hashlib.sha256(f"m7u1|openloop|{ep.episode_id}|{t}".encode()).hexdigest(), e, int(t)))
    cands.sort()
    pick = cands[:n_open_loop]
    if pick:
        errs = {16: [], 32: [], 64: []}
        by_ep: Dict[int, List[int]] = {}
        for _s, e, t in pick:
            by_ep.setdefault(e, []).append(t)
        for e, starts in by_ep.items():
            ep = episodes[e]
            hist = us.history_sequence(ep.rows, [tuple(int(v) for v in w) for w in ep.words])
            plans = np.stack([_pad([tuple(w) for w in ep.words[s:s + up.H]], up.H) for s in starts])
            roll = um.rollout(model, ctx, torch.tensor(ep.rows[starts]), torch.tensor(hist[starts]), torch.tensor(plans))
            for k in errs:
                real = ep.rows[np.array(starts) + k]
                ex = np.abs(roll.x[:, :, k - 1].mean(0).numpy() - real[:, us.F["x"]])
                ey = np.abs(roll.y[:, :, k - 1].mean(0).numpy() - real[:, us.F["y"]])
                errs[k] += np.maximum(ex, ey).tolist()
        out["open_loop"] = {str(k): {"median": round(float(np.median(v)), 2), "p90": round(float(np.quantile(v, 0.9)), 2)}
                            for k, v in errs.items() if v}
    return out


def ambiguity_flags(rows: np.ndarray, t: int) -> Dict[str, bool]:
    """Flags over the controlled part (rows t..end) of one trial."""
    F = us.F
    ctl = rows[t:]
    flags = {"projectile": bool((np.nan_to_num(ctl[:, F["n_proj"]]) > 0).any()), "shield": bool((ctl[:, F["shield"]] == 1).any()),
             "conditional_status": bool(np.isin(ctl[:, F["status"]].astype(int), list(CONDITIONAL_STATUSES)).any())}
    brk = False
    for a, b in zip(ctl[:-1], ctl[1:]):
        lost = int(a[F["live_mask"]]) & ~int(b[F["live_mask"]])
        if lost and int(b[F["attack"]]) == 0 and int(a[F["attack"]]) == 0:
            brk = True
    flags["break_without_attack"] = brk
    hist = us.history_sequence(rows, [(0, 0)] * (len(rows) - 1))   # the tornado bit depends on rows only
    tor = False
    for k in range(t, len(rows)):
        if hist[k, us.Hh["tornado"]] == 1 and int(rows[k, F["status"]]) == us.STATUS_SPECIAL_AIR_LW:
            tor = True
    flags["second_air_tornado"] = tor
    flags["any"] = any(flags.values())
    return flags
