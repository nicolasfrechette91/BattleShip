"""M7u3 (proposed gate m7u3): goal selection with a non-overlap rule, and per-goal training coverage (design:
docs/rl_model_planning_m7u3_proposal_2026-10-01.md section 3.3, as amended by
docs/rl_model_planning_m7u3_decisions_2026-10-01.md). NumPy only; the eligibility, rarity and reach semantics are
m7u2's (imported, unchanged).

Scope, repeated in every record: refit-versus-frozen test of planner-controlled reach of rare behaviour-drawn airborne
points from the normal tick-0 reset (one seed, one refit, 24 non-overlapping goals); not a landing, wall-top reach,
crossing, target result or clear.

- **Training pool** (fitting only): TRAIN_EPISODES behaviour episodes t000.., at most TRAIN_TICKS words, from the normal
  reset, stream seed 1.
- **Goal pool** (never fitted, collected after the refit is frozen): GOAL_EPISODES behaviour episodes g000.., at most
  GOAL_TICKS words, stream seed 2.
- **Eligibility / rarity**: m7u2's (tau in [32, 96]; valid airborne row that is not the fatal-fall tick; rise >= 300;
  at most 1 of the 92 m7u1 reference episodes make a valid airborne reach of the +-150 box within input ticks 1..128).
- **Selection** `m7u3_tick0_goal_v1`, deterministic, from the goal pool and the reference ONLY (no outcome, model or
  training-pool argument; a test pins the signature):
  1. episodes in the order of sha256('m7u3|goal|<entry>'); within an episode its eligible taus in the order of
     sha256('m7u3|goal|<entry>|<tau>');
  2. the first tau whose box overlaps NO registered goal's box is registered: max(|dx|, |dy|) > NON_OVERLAP_SPAN (300,
     m7u2's overlap definition, so an exact duplicate is the special case) against every registered goal;
  3. an episode with no such tau is skipped; the record keeps every skipped episode and every passed-over tau with the
     goal it overlapped and its Chebyshev distance;
  4. stop at N_GOALS, one goal per episode. Fewer is INCOMPLETE: no fill, no relaxation, no second pool.
- **Independence**: the registered set's overlap graph has no edges, confirmed by brute force over all pairs; the
  minimum pairwise Chebyshev distance is recorded. So 24 goals = 24 independent units (some dependence is inherent and
  not removed: one model, one reset state, one seed).
- **Coverage** (reported only, computed AFTER selection): how many training-pool / m7u1 training episodes make a valid
  airborne reach of each goal's box within input ticks 1..128.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

import m7u2_goals as g2
import m7u_state as us

GOAL_CONTRACT = "m7u3_tick0_goal_v1"
SCOPE = ("refit-versus-frozen test of planner-controlled reach of rare behaviour-drawn airborne points from the normal "
         "tick-0 reset (one seed, one refit, 24 non-overlapping goals); not a landing, wall-top reach, crossing, target "
         "result or clear")
TRAIN_EPISODES, TRAIN_TICKS = 540, 192
GOAL_EPISODES, GOAL_TICKS = 540, 128
TAU_MIN, TAU_MAX = g2.TAU_MIN, g2.TAU_MAX
BUDGET = g2.BUDGET                      # 128 words per evaluation trial
RISE, BOX = g2.RISE, g2.BOX
REF_EPISODES, REF_MAX_REACHING = g2.REF_EPISODES, g2.REF_MAX_REACHING
N_GOALS = 24
SCRAMBLE_SHIFT = N_GOALS // 2           # 12
NON_OVERLAP_SPAN = 2 * BOX              # 300: goals must be farther apart than this (Chebyshev) to both register
SEED_TRAIN, SEED_POOL, SEED_EVAL = 1, 2, 3
TRAIN_ENTRIES: Tuple[str, ...] = tuple(f"t{i:03d}" for i in range(TRAIN_EPISODES))
GOAL_ENTRIES: Tuple[str, ...] = tuple(f"g{i:03d}" for i in range(GOAL_EPISODES))

GoalError = g2.GoalError
Goal = g2.Goal
Reference = g2.Reference
row_digest = g2.row_digest
rise_events = g2.rise_events
composition = g2.composition
reach_ok = g2.reach_ok
sha = g2.sha


def scrambled(k: int, n_goals: int = N_GOALS) -> int:
    """pi(k) = (k + n / 2) mod n: a derangement pairing every goal with the one half the registered list away."""
    return (int(k) + n_goals // 2) % n_goals


def goals_digest(goals: Sequence[Goal]) -> str:
    return sha(json.dumps([g.to_json() for g in goals], sort_keys=True, default=str))


def chebyshev(a: Mapping[str, Any], b: Mapping[str, Any]) -> float:
    return float(max(abs(a["x"] - b["x"]), abs(a["y"] - b["y"])))


def independence_report(registered: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Brute force over every pair: the overlap graph (Chebyshev distance <= NON_OVERLAP_SPAN) must have no edge."""
    n = len(registered)
    edges: List[Dict[str, Any]] = []
    dmin = None
    for i in range(n):
        for j in range(i + 1, n):
            d = chebyshev(registered[i], registered[j])
            dmin = d if dmin is None else min(dmin, d)
            if d <= NON_OVERLAP_SPAN:
                edges.append({"k": [i, j], "chebyshev": d})
    return {"n_goals": n, "n_pairs_checked": n * (n - 1) // 2, "overlapping_pairs": edges,
            "min_pairwise_chebyshev": dmin, "span": NON_OVERLAP_SPAN, "independent_units": n if not edges else None}


def select_goals(pool: Sequence[Mapping[str, Any]], reference: Reference, tick0_row: np.ndarray, *,
                 entries: Sequence[str] = GOAL_ENTRIES, n_goals: int = N_GOALS) -> Dict[str, Any]:
    """pool: one mapping per goal-pool episode with entry, episode_id, rows (T+1, F), words (T, 2), fell. Returns the
    registered goals and the selection record. There is deliberately no outcome, model or training-pool argument:
    selection sees the goal pool and the reference only."""
    F = us.F
    got = sorted(str(p["entry"]) for p in pool)
    if got != sorted(entries):
        raise GoalError(f"the pool is not exactly the registered {len(entries)} entries ({len(got)} given)")
    t0 = np.asarray(tick0_row, dtype=np.float64)
    spawn_y = float(t0[F["y"]])
    choices: List[Dict[str, Any]] = []
    n_with_candidates = n_eligible_points = 0
    for p in sorted(pool, key=lambda p: str(p["entry"])):
        rows = np.asarray(p["rows"], dtype=np.float64)
        if len(p["words"]) > GOAL_TICKS or len(rows) != len(p["words"]) + 1:
            raise GoalError(f"{p['entry']}: {len(p['words'])} words, {len(rows)} rows (at most {GOAL_TICKS} words)")
        same = (rows[0] == t0) | (np.isnan(rows[0]) & np.isnan(t0))
        if not same.all():
            raise GoalError(f"{p['entry']}: the reset row differs from the tick-0 record")
        taus = g2.candidates(rows, bool(p["fell"]), spawn_y)
        n_with_candidates += bool(taus)
        elig = [t for t in taus if reference.reaching(rows[t, F["x"]], rows[t, F["y"]]) <= REF_MAX_REACHING]
        n_eligible_points += len(elig)
        if not elig:
            continue
        options = []
        for tau in sorted(elig, key=lambda t: sha(f"m7u3|goal|{p['entry']}|{t}")):
            options.append({"entry": str(p["entry"]), "episode_id": str(p["episode_id"]), "tau": int(tau),
                            "x": float(rows[tau, F["x"]]), "y": float(rows[tau, F["y"]]),
                            "rise": float(rows[tau, F["y"]] - spawn_y),
                            "ref_reaching": reference.reaching(rows[tau, F["x"]], rows[tau, F["y"]]),
                            "witness": [(int(a), int(b)) for a, b in np.asarray(p["words"])[:tau]],
                            "witness_composition": composition(rise_events(rows, 0, tau))})
        choices.append({"entry": str(p["entry"]), "sha": sha(f"m7u3|goal|{p['entry']}"), "options": options})
    choices.sort(key=lambda c: c["sha"])
    registered: List[Dict[str, Any]] = []
    passed_over: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for c in choices:
        if len(registered) >= n_goals:
            break
        chosen = None
        for o in c["options"]:
            hits = [{"goal_k": k, "entry": r["entry"], "chebyshev": chebyshev(o, r)}
                    for k, r in enumerate(registered) if chebyshev(o, r) <= NON_OVERLAP_SPAN]
            if not hits:
                chosen = o
                break
            passed_over.append({"entry": o["entry"], "tau": o["tau"], "overlaps": hits})
        if chosen is None:
            skipped.append({"entry": c["entry"], "eligible_taus": len(c["options"])})
            continue
        registered.append(chosen)
    independence = independence_report(registered)
    record = {"contract": GOAL_CONTRACT, "scope": SCOPE, "pool_episodes": len(pool),
              "episodes_with_candidates": n_with_candidates, "eligible_points": n_eligible_points,
              "episodes_with_a_goal": len(choices), "passed_over_overlapping_taus": passed_over,
              "skipped_episodes": skipped, "registered": len(registered), "independence": independence,
              "reference_episodes": reference.n, "reference_digest": reference.digest(),
              "tick0_row_digest": row_digest(t0), "scramble": {"rule": f"pi(k) = (k + {SCRAMBLE_SHIFT}) mod {n_goals}"}}
    if independence["overlapping_pairs"]:
        raise GoalError(f"internal error: registered goals overlap {independence['overlapping_pairs'][:2]}")
    if len(registered) < n_goals:
        raise GoalError(f"only {len(registered)} non-overlapping eligible goals < {n_goals}", incomplete=True,
                        record=record)
    goals = [Goal(k=k, entry=c["entry"], episode_id=c["episode_id"], tau=c["tau"], x=c["x"], y=c["y"], rise=c["rise"],
                  ref_reaching=c["ref_reaching"], witness=c["witness"], witness_composition=c["witness_composition"])
             for k, c in enumerate(registered)]
    return {"goals": goals, "record": record}


def coverage(goals: Sequence[Goal], episodes: Sequence[Tuple[str, np.ndarray, bool]]) -> List[int]:
    """Per goal: how many of `episodes` (id, rows, fell) make a valid airborne reach of the goal's +-BOX box within
    input ticks 1..BUDGET. Reported only; call it after selection (the selection function never sees these episodes)."""
    ref = Reference(list(episodes), budget=BUDGET)
    return [ref.reaching(g.x, g.y) for g in goals]


def contract_digest() -> str:
    d = {"contract": GOAL_CONTRACT, "train_pool": [TRAIN_EPISODES, TRAIN_TICKS], "goal_pool": [GOAL_EPISODES, GOAL_TICKS],
         "tau": [TAU_MIN, TAU_MAX], "budget": BUDGET, "rise": RISE, "box": BOX,
         "reference": [REF_EPISODES, REF_MAX_REACHING], "n_goals": N_GOALS, "scramble_shift": SCRAMBLE_SHIFT,
         "non_overlap_span": NON_OVERLAP_SPAN, "seeds": [SEED_TRAIN, SEED_POOL, SEED_EVAL],
         "keys": ["m7u3|goal|<entry>|<tau>", "m7u3|goal|<entry>"],
         "non_overlap": "Chebyshev > 300 against every registered goal; else next eligible tau in sha order, else skip"}
    return sha(json.dumps(d, sort_keys=True))
