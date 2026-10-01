"""M7u3 gate m7u3: reported diagnostics (forward passes only; never an input of the rule). Design:
docs/rl_model_planning_m7u3_proposal_2026-10-01.md section 6 as amended by
docs/rl_model_planning_m7u3_decisions_2026-10-01.md. Reuses m7u1's analysis (rl/m7u_analysis.py) for every definition
the proposal says is unchanged: attribution (MODEL / PLAN, PREDICTED / UNPREDICTED), witness majority, calibration, held-out
accuracy and ambiguity flags.

Models are (model, ctx) pairs; the frozen model, the refit and P_retrain have different contexts only through their
vocabularies. No function here calls a training routine or constructs an optimizer.

- `strict_open_loop`: the model rolled over a goal-pool / M7u2-pool episode's own recorded words from its RESET ROW
  (never an early-window mixture of starts), the Chebyshev error of the ensemble-mean position at each horizon.
- `decision_flags` / `cross_attribution`: the same executed words re-rolled from the same decision states through the
  other model (the most direct same-input measure of "fewer from-rest model failures").
- `witness_acceptance`: does a majority of members predict that a goal's recorded path from the reset row reaches it.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import torch

import m7u2_goals as g2
import m7u_analysis as ua
import m7u_model as um
import m7u_planner as up
import m7u_state as us

HORIZONS = (16, 32, 64, 96)
BOX = up.BOX


def _quantiles(v: np.ndarray) -> Dict[str, Any]:
    if len(v) == 0:
        return {"n": 0}
    return {"n": int(len(v)), "median": round(float(np.median(v)), 3), "p90": round(float(np.quantile(v, 0.9)), 3),
            "share_gt_box": round(float((v > BOX).mean()), 4)}


def strict_open_loop(model: um.DynamicsEnsemble, ctx: um.Context, episodes: Sequence[Mapping[str, Any]],
                     horizons: Sequence[int] = HORIZONS, chunk: int = 135) -> Dict[int, Dict[str, Any]]:
    """For each horizon h: the per-episode Chebyshev error of the ensemble-mean position h ticks after the reset row,
    over the episode's own recorded words, for the episodes with at least h words and a valid row at h (a set that
    depends on the episode alone, so it is the same for every model). Returns {h: {"index": [episode index], "error":
    ndarray}}. episodes: mappings with rows (T+1, F) and words (T, 2)."""
    hmax = max(horizons)
    n = len(episodes)
    errs: Dict[int, List[Tuple[int, float]]] = {h: [] for h in horizons}
    for a in range(0, n, chunk):
        batch = list(range(a, min(n, a + chunk)))
        rows0 = np.stack([np.asarray(episodes[i]["rows"][0], dtype=np.float64) for i in batch])
        hist0 = np.stack([us.init_history(r) for r in rows0])
        plans = np.stack([ua._pad([tuple(int(v) for v in w) for w in np.asarray(episodes[i]["words"])[:hmax]], hmax)
                          for i in batch])
        roll = um.rollout(model, ctx, torch.tensor(rows0), torch.tensor(hist0), torch.tensor(plans))
        mx, my = roll.x.mean(0).numpy(), roll.y.mean(0).numpy()
        for j, i in enumerate(batch):
            rows, words = np.asarray(episodes[i]["rows"]), np.asarray(episodes[i]["words"])
            for h in horizons:
                if len(words) >= h and rows[h, us.F["valid"]] == 1.0:
                    errs[h].append((i, float(max(abs(mx[j, h - 1] - rows[h, us.F["x"]]),
                                                 abs(my[j, h - 1] - rows[h, us.F["y"]])))))
    return {h: {"index": [i for i, _ in v], "error": np.array([e for _, e in v])} for h, v in errs.items()}


def summarise_strict(strict: Mapping[int, Mapping[str, Any]]) -> Dict[str, Any]:
    return {str(h): _quantiles(np.asarray(v["error"])) for h, v in strict.items()}


def paired_strict(a: Mapping[int, Mapping[str, Any]], b: Mapping[int, Mapping[str, Any]]) -> Dict[str, Any]:
    """Per-episode paired differences (a - b; negative = a has the lower error) at each horizon."""
    out = {}
    for h in a:
        if list(a[h]["index"]) != list(b[h]["index"]):
            raise ValueError(f"horizon {h}: the two models were evaluated on different episodes")
        d = np.asarray(a[h]["error"]) - np.asarray(b[h]["error"])
        out[str(h)] = {"n": int(len(d)), "median_diff": round(float(np.median(d)), 3) if len(d) else None,
                       "share_a_better": round(float((d < 0).mean()), 4) if len(d) else None,
                       "share_equal": round(float((d == 0).mean()), 4) if len(d) else None}
    return out


def trial_flags(model: um.DynamicsEnsemble, ctx: um.Context, rows: np.ndarray, words: np.ndarray, goal: Tuple[float, float],
                starts: Sequence[int]) -> np.ndarray:
    """Per decision start: do >= 2 of 3 members predict a reach of `goal` (before a predicted fall) when the words
    actually executed from that start are rolled from the recorded native state and bookkeeping history?"""
    starts = [int(s) for s in starts if int(s) < len(words)]
    if not starts:
        return np.zeros(0, dtype=bool)
    hist = us.history_sequence(rows, [tuple(int(v) for v in w) for w in words])
    plans = np.stack([ua._pad([tuple(int(v) for v in w) for w in words[s:]], up.H) for s in starts])
    lengths = np.array([min(len(words) - s, up.H) for s in starts])
    roll = um.rollout(model, ctx, torch.tensor(rows[starts]), torch.tensor(hist[starts]), torch.tensor(plans))
    maj, _first = ua.majority_reach(roll, np.tile(np.asarray(goal, dtype=np.float64), (len(starts), 1)), lengths)
    return maj


def attribution(model: um.DynamicsEnsemble, ctx: um.Context, trial: Mapping[str, Any]) -> Dict[str, Any]:
    """m7u1's / M7u2's attribution of one P trial with its own model (`ua.trial_attribution`, unchanged)."""
    return ua.trial_attribution(model, ctx, {"rows": trial["rows"], "words": trial["words"], "t": 0, "goal": trial["goal"],
                                             "decisions": trial["decisions"], "reached": trial["reached"]})


def attribution_summary(attr: Mapping[int, Mapping[str, Any]], flags_any: Mapping[int, bool], reached: Sequence[bool]
                        ) -> Dict[str, Any]:
    """MODEL / PLAN over all failures and over failures without an ambiguity flag; PREDICTED / UNPREDICTED successes."""
    fails = [k for k in range(len(reached)) if not reached[k]]
    wins = [k for k in range(len(reached)) if reached[k]]
    model_all = sum(1 for k in fails if attr[k]["class"] == "MODEL")
    clean = [k for k in fails if not flags_any.get(k, False)]
    model_clean = sum(1 for k in clean if attr[k]["class"] == "MODEL")
    return {"failures": len(fails), "MODEL": model_all, "PLAN": len(fails) - model_all,
            "model_share": (model_all / len(fails)) if fails else None, "failures_without_flag": len(clean),
            "MODEL_without_flag": model_clean, "model_share_without_flag": (model_clean / len(clean)) if clean else None,
            "successes": len(wins), "PREDICTED": sum(1 for k in wins if attr[k]["class"] == "PREDICTED"),
            "UNPREDICTED": sum(1 for k in wins if attr[k]["class"] == "UNPREDICTED")}


def cross_attribution(src: Tuple[um.DynamicsEnsemble, um.Context], other: Tuple[um.DynamicsEnsemble, um.Context],
                      trials: Mapping[int, Mapping[str, Any]], src_attr: Mapping[int, Mapping[str, Any]],
                      reached: Sequence[bool]) -> Dict[str, Any]:
    """The src model's MODEL failures (it predicted a reach on the executed words, but none occurred) re-rolled through
    the other model from the SAME decision states and the same executed words. Trial level: the share of those failures
    whose false reach the other model no longer predicts at any decision. Decision level: over the decisions where src
    predicted a reach in those trials, the share the other model does not."""
    model_fails = [k for k in range(len(reached)) if not reached[k] and src_attr[k]["class"] == "MODEL"]
    n_dec = n_dec_gone = n_gone = 0
    per = []
    for k in model_fails:
        t = trials[k]
        starts = [int(a) for a in t["decisions"] if int(a) < len(t["words"])]
        f_src = trial_flags(src[0], src[1], t["rows"], t["words"], t["goal"], starts)
        f_oth = trial_flags(other[0], other[1], t["rows"], t["words"], t["goal"], starts)
        gone = not bool(f_oth.any())
        n_gone += gone
        n_dec += int(f_src.sum())
        n_dec_gone += int((f_src & ~f_oth).sum())
        per.append({"goal_k": k, "src_predicted_decisions": int(f_src.sum()), "other_predicted_decisions": int(f_oth.sum()),
                    "other_no_longer_predicts": bool(gone)})
    return {"src_model_failures": len(model_fails), "other_no_longer_predicts": n_gone,
            "share_trial": (n_gone / len(model_fails)) if model_fails else None,
            "src_predicted_decisions": n_dec, "other_no_longer_predicts_decisions": n_dec_gone,
            "share_decision": (n_dec_gone / n_dec) if n_dec else None, "per_failure": per}


def witness_acceptance(model: um.DynamicsEnsemble, ctx: um.Context, goals: Sequence[g2.Goal], row0: np.ndarray
                       ) -> Dict[str, Any]:
    """Each goal's recorded path (the goal-pool episode's own words 0..tau-1) from the reset row, padded to 96 as in
    M7u2: accepted when a majority (>= 2 of 3) of members predicts a valid reach within tau."""
    hist0 = us.init_history(row0)
    n = len(goals)
    plans = np.stack([ua._pad(g.witness, g2.TAU_MAX) for g in goals])
    roll = um.rollout(model, ctx, torch.tensor(np.repeat(row0[None], n, 0)), torch.tensor(np.repeat(hist0[None], n, 0)),
                      torch.tensor(plans))
    maj, first = ua.majority_reach(roll, np.array([[g.x, g.y] for g in goals]), np.array([g.tau for g in goals]))
    return {"accepted": [bool(v) for v in maj], "count": int(maj.sum()), "n": n,
            "members_predicting": [int((first[:, i] < g2.TAU_MAX).sum()) for i in range(n)]}


def paired_table(a: Sequence[bool], b: Sequence[bool]) -> Dict[str, int]:
    return {"both": sum(1 for x, y in zip(a, b) if x and y), "a_only": sum(1 for x, y in zip(a, b) if x and not y),
            "b_only": sum(1 for x, y in zip(a, b) if y and not x), "neither": sum(1 for x, y in zip(a, b) if not x and not y)}


def executed_calibration(model: um.DynamicsEnsemble, ctx: um.Context, trials: Sequence[Mapping[str, Any]]
                         ) -> Dict[str, Any]:
    """Executed-block calibration (M7u2's): the 4-word-block error of the ensemble mean, blocks above the box, and the
    AUROC of the ensemble spread for an error above the box."""
    e_all: List[np.ndarray] = []
    s_all: List[np.ndarray] = []
    for r in trials:
        hs = us.history_sequence(r["rows"], [tuple(int(v) for v in w) for w in r["words"]])
        e_, s_ = ua.block_errors(model, ctx, r["rows"], hs, r["words"], list(r["decisions"]))
        e_all.append(e_)
        s_all.append(s_)
    e = np.concatenate(e_all) if e_all else np.zeros(0)
    s = np.concatenate(s_all) if s_all else np.zeros(0)
    return {"blocks": int(len(e)), "error_gt_box": int((e > BOX).sum()), "auroc_spread": ua.auroc(s, e > BOX),
            "error_median": float(np.median(e)) if len(e) else None}


def accuracy(model: um.DynamicsEnsemble, ctx: um.Context, episodes: Sequence[um.Episode], n_open_loop: int = 200,
             chunk: int = 8192) -> Dict[str, Any]:
    """`ua.heldout_accuracy` (rl/m7u_analysis.py, unchanged and still the reference) computed with bounded memory and time:
    the one-step forward pass runs in chunks of `chunk` transitions instead of all at once (about 0.9 GB of transient
    memory on a 46,000-transition set), and the 64-tick open-loop starts of ALL episodes are rolled in batches instead of
    one rollout per episode. The definitions are identical: teacher-state one-step position error of the ensemble mean and
    status accuracy per class v2; ensemble-mean open-loop error at 16 / 32 / 64 ticks from the 200 sha-ordered start ticks
    (`m7u1|openloop|<episode>|<t>`) of the usable pairs. A test checks equality with `ua.heldout_accuracy` on recorded data."""
    import hashlib

    import m7q_status_table as st2
    import m7u_goals as ug

    ts = um.build_transitions(ctx, episodes)
    n = len(ts.cur)
    out: Dict[str, Any] = {"transitions": n}
    if n == 0:
        return out
    perr_parts: List[np.ndarray] = []
    sok_parts: List[np.ndarray] = []
    cls_parts: List[np.ndarray] = []
    with torch.no_grad():
        for a in range(0, n, chunk):
            b = min(n, a + chunk)
            idx = torch.arange(a, b)[None, :].expand(model.members, -1)
            h = model.trunk(ts.dense[idx], ts.cur[idx], ts.prev[idx])
            d = um.decode_step(model, ctx, h)
            dx = d["h6"][:, :, 0].double() * um.H6_SCALE[0]
            dy = d["h6"][:, :, 1].double() * um.H6_SCALE[1]
            tdx = ts.targets["h6"][a:b, 0].double() * um.H6_SCALE[0]
            tdy = ts.targets["h6"][a:b, 1].double() * um.H6_SCALE[1]
            perr_parts.append(torch.maximum((dx.mean(0) - tdx).abs(), (dy.mean(0) - tdy).abs()).numpy())
            sok_parts.append((d["s"] == ts.targets["s"][a:b][None]).double().mean(0).numpy())
            cls_parts.append(ctx.status_class[ctx.idx_to_status[ts.targets["s"][a:b]].long().clamp(0, um.STATUS_LOOKUP - 1)].numpy())
    perr, s_ok, cls = np.concatenate(perr_parts), np.concatenate(sok_parts), np.concatenate(cls_parts)
    per_class = {}
    for c in np.unique(cls):
        m = cls == c
        per_class[st2.CLASSES[int(c)]] = {"n": int(m.sum()), "pos_err_median": round(float(np.median(perr[m])), 3),
                                          "pos_err_p95": round(float(np.quantile(perr[m], 0.95)), 3),
                                          "status_acc": round(float(s_ok[m].mean()), 4)}
    out.update({"pos_err_median": round(float(np.median(perr)), 4), "pos_err_p99": round(float(np.quantile(perr, 0.99)), 3),
                "status_acc": round(float(s_ok.mean()), 4), "per_class": per_class})
    cands = []
    for e, ep in enumerate(episodes):
        for t in ug.usable_pairs(ep.rows, ep.fell, up.H):
            cands.append((hashlib.sha256(f"m7u1|openloop|{ep.episode_id}|{t}".encode()).hexdigest(), e, int(t)))
    cands.sort()
    pick = cands[:n_open_loop]
    if pick:
        by_ep: Dict[int, List[int]] = {}
        for _s, e, t in pick:
            by_ep.setdefault(e, []).append(t)
        rows_all, hist_all, plans_all, ks = [], [], [], []
        for e, starts in by_ep.items():
            ep = episodes[e]
            hist = us.history_sequence(ep.rows, [tuple(int(v) for v in w) for w in ep.words])
            for s0 in starts:
                rows_all.append(ep.rows[s0])
                hist_all.append(hist[s0])
                plans_all.append(ua._pad([tuple(int(v) for v in w) for w in ep.words[s0:s0 + up.H]], up.H))
                ks.append((e, s0))
        errs = {16: [], 32: [], 64: []}
        step = 256
        for a in range(0, len(ks), step):
            sl = slice(a, a + step)
            roll = um.rollout(model, ctx, torch.tensor(np.stack(rows_all[sl])), torch.tensor(np.stack(hist_all[sl])),
                              torch.tensor(np.stack(plans_all[sl])))
            for k in errs:
                real = np.stack([episodes[e].rows[s0 + k] for e, s0 in ks[sl]])
                ex = np.abs(roll.x[:, :, k - 1].mean(0).numpy() - real[:, us.F["x"]])
                ey = np.abs(roll.y[:, :, k - 1].mean(0).numpy() - real[:, us.F["y"]])
                errs[k] += np.maximum(ex, ey).tolist()
        out["open_loop"] = {str(k): {"median": round(float(np.median(v)), 2), "p90": round(float(np.quantile(v, 0.9)), 2)}
                            for k, v in errs.items() if v}
    return out


def one_step_and_open_loop(model: um.DynamicsEnsemble, ctx: um.Context, episodes: Sequence[um.Episode]) -> Dict[str, Any]:
    """M7u2's early-window measure (200 sha-ordered starts, input ticks 0..64 of the pool episodes) and the one-step
    position / status accuracy, with bounded memory and time (`accuracy`)."""
    return accuracy(model, ctx, episodes)
