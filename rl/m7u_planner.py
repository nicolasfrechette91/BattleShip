"""M7u: the fixed planner and its controls (design: docs/rl_model_planning_m7u_proposal_2026-09-29.md, revision 2, §5).

No learned parameters. Works in Track 1 indices only (stick 0..8, button 0..7: all 72 combinations, none masked or
suppressed); the worker stack below converts them to canonical native words, which stay the replay truth. Imports no
transport, process or environment code (a test checks sys.modules).

Every decision (every EXEC = 4 controlled ticks) draws ONE fixed block from a generator keyed by (stream key, decision
index), whatever the arm or the state, so every arm of a goal consumes identical random numbers:

    refill   REFILL_SEGMENTS (64) segments          extend candidate 0 (and the mutants) to H words
    mutants  MUTANTS (15) positions u in [0, 1) + 15 replacement segments
    fresh    (N - 1 - MUTANTS) plans x FRESH_SEGMENTS (64) segments

A segment is (stick, button, mode tap | hold, length in {1, 2, 4, 8, 16, 32}), drawn uniformly per field; it expands
exactly as the M7r option space (rl/m7r_commit.tick_word): tap = the button on its first tick only, hold = on every tick.

Candidates (each H words):
    0          the retained plan shifted by EXEC words, extended with refill segments (at a trial's first decision:
               the refill segments alone)
    1..15      candidate 0 with segment j = floor(u * n) of its n segments (start < H) replaced, re-extended with the
               refill segments not used by candidate 0, truncated to H
    16..N-1    fresh plans

Arms: P chooses argmin of the ensemble score toward its commanded goal (ties -> lowest index); S is P commanded to the
scrambled goal; RC always takes candidate 0 and evaluates no model. The chosen candidate becomes the retained plan and
its first EXEC words are submitted, one native tick each. RC's executed stream is a continuous flow of full random
segments: the behaviour policy that collects the training data.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

PLANNER_CONTRACT = "m7u_planner_v1"
H = 64
EXEC = 4
MUTANTS = 15
REFILL_SEGMENTS = 64
FRESH_SEGMENTS = 64
SEG_LENGTHS = (1, 2, 4, 8, 16, 32)
FIELD_HIGH = (9, 8, 2, len(SEG_LENGTHS))       # stick, button, mode, length index
BOX = 150.0                                      # success / predicted-reach half-width (native units)
W_CONTACT, W_TIME, FALL_COST, STD_WEIGHT = 1.0, 0.1, 10.0, 1.0
ARMS = ("P", "RC", "S")


class PlannerError(RuntimeError):
    pass


def expand(segment: Sequence[int]) -> List[Tuple[int, int]]:
    """Track 1 words of one segment (M7r option semantics)."""
    stick, button, mode, li = (int(v) for v in segment)
    n = SEG_LENGTHS[li]
    return [(stick, button if (mode == 1 or i == 0) else 0) for i in range(n)]


def stream_seed(stream_key: str, decision: int) -> int:
    return int.from_bytes(hashlib.sha256(f"m7u|cand|{stream_key}|{int(decision)}".encode("utf-8")).digest()[:8], "little")


@dataclass
class Draws:
    refill: np.ndarray       # (REFILL_SEGMENTS, 4)
    mut_u: np.ndarray        # (MUTANTS,)
    mut_seg: np.ndarray      # (MUTANTS, 4)
    fresh: np.ndarray        # (n_fresh, FRESH_SEGMENTS, 4)


def draw_block(stream_key: str, decision: int, n_candidates: int) -> Draws:
    if n_candidates < MUTANTS + 2:
        raise PlannerError(f"{n_candidates} candidates < {MUTANTS + 2}")
    rng = np.random.Generator(np.random.PCG64(stream_seed(stream_key, decision)))
    high = np.array(FIELD_HIGH)
    refill = rng.integers(0, high, size=(REFILL_SEGMENTS, 4))
    mut_u = rng.random(MUTANTS)
    mut_seg = rng.integers(0, high, size=(MUTANTS, 4))
    fresh = rng.integers(0, high, size=(n_candidates - 1 - MUTANTS, FRESH_SEGMENTS, 4))
    return Draws(refill=refill, mut_u=mut_u, mut_seg=mut_seg, fresh=fresh)


@dataclass
class Plan:
    words: List[Tuple[int, int]]
    starts: List[int]              # start index of each segment (the first may be a partially executed segment)

    def shifted(self, k: int) -> "Plan":
        words = self.words[k:]
        starts = sorted({0} | {s - k for s in self.starts if s - k > 0}) if words else []
        return Plan(words=list(words), starts=starts)


def _extend(plan: Plan, segments: np.ndarray, first: int) -> Tuple[Plan, int]:
    """Append segments[first:] until the plan has at least H words, then truncate to H. Returns (plan, next index)."""
    words, starts = list(plan.words), list(plan.starts)
    i = first
    while len(words) < H:
        if i >= len(segments):
            raise PlannerError("refill pool exhausted")
        starts.append(len(words))
        words += expand(segments[i])
        i += 1
    words = words[:H]
    return Plan(words=words, starts=[s for s in starts if s < H]), i


def candidates(retained: Optional[Plan], draws: Draws, n_candidates: int) -> Tuple[List[Plan], np.ndarray]:
    """The N candidate plans of one decision and their (N, H, 2) word array."""
    base = retained.shifted(EXEC) if retained is not None else Plan(words=[], starts=[])
    c0, used = _extend(base, draws.refill, 0)
    plans = [c0]
    nseg = len(c0.starts)
    for m in range(MUTANTS):
        j = min(int(draws.mut_u[m] * nseg), nseg - 1)
        a = c0.starts[j]
        b = c0.starts[j + 1] if j + 1 < nseg else H
        words = c0.words[:a] + expand(draws.mut_seg[m]) + c0.words[b:]
        starts = c0.starts[:j + 1] + [s - (b - a) + len(expand(draws.mut_seg[m])) for s in c0.starts[j + 1:]]
        mp = Plan(words=words[:H], starts=[s for s in starts if s < min(len(words), H)])
        if len(mp.words) < H:
            mp, _ = _extend(mp, draws.refill, used)
        plans.append(mp)
    for f in range(n_candidates - 1 - MUTANTS):
        p, _ = _extend(Plan(words=[], starts=[]), draws.fresh[f], 0)
        plans.append(p)
    arr = np.array([p.words for p in plans], dtype=np.int64)
    if arr.shape != (n_candidates, H, 2):
        raise PlannerError(f"candidate array {arr.shape}")
    return plans, arr


# -- scoring (P and S only) -----------------------------------------------------------------------------------------------


def score(x: Any, y: Any, air: Any, fall_at: Any, goal: Tuple[float, float], tau_max: int) -> Any:
    """Per-candidate score from an ensemble rollout: x, y, air (E, N, H), fall_at (E, N) torch tensors.
    Member cost C = min over tau < min(tau_max, fall) of [Chebyshev / BOX + W_CONTACT * grounded + W_TIME * (tau+1)/H];
    FALL_COST when a fall is predicted within tau_max and no predicted reach precedes it, or when no tick is valid.
    Score = mean_m C + STD_WEIGHT * std_m C (population). Returns (N,) float64 and (E, N) predicted-reach tick
    (H when none)."""
    import torch

    E, N, Hh = x.shape
    tau = torch.arange(Hh)
    cheb = torch.maximum((x - goal[0]).abs(), (y - goal[1]).abs())
    d = cheb / BOX + W_CONTACT * (~air).double() + W_TIME * (tau + 1).double() / Hh
    valid = (tau[None, None, :] < min(int(tau_max), Hh)) & (tau[None, None, :] < fall_at[:, :, None])
    reach = valid & (cheb <= BOX) & air
    big = torch.full_like(d, float("inf"))
    c = torch.where(valid, d, big).min(dim=2).values
    never = torch.full_like(reach, Hh, dtype=torch.long)
    reach_at = torch.where(reach, tau[None, None, :].expand_as(reach), never).min(2).values
    fell = fall_at < min(int(tau_max), Hh)
    c = torch.where(torch.isinf(c) | (fell & (reach_at >= fall_at)), torch.full_like(c, FALL_COST), c)
    s = c.mean(dim=0) + STD_WEIGHT * c.std(dim=0, unbiased=False)
    return s, reach_at


# -- controllers ----------------------------------------------------------------------------------------------------------


@dataclass
class Decision:
    index: int
    chosen: int
    n_candidates: int
    at_tick: int
    predicted_reach: Optional[int] = None


@dataclass
class Controller:
    """One trial's (or one collection episode's) controller. `goal` is the COMMANDED point (P: g, S: pi(g), RC: None).
    `budget` None = unbounded (collection)."""
    arm: str
    stream_key: str
    n_candidates: int
    goal: Optional[Tuple[float, float]] = None
    budget: Optional[int] = None
    executed: int = 0
    decisions: List[Decision] = field(default_factory=list)
    retained: Optional[Plan] = None
    pending: Optional[Tuple[List[Plan], np.ndarray]] = None
    words: List[Tuple[int, int]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.arm not in ARMS and self.arm != "collect":
            raise PlannerError(f"arm {self.arm!r}")
        if self.arm in ("P", "S") and self.goal is None:
            raise PlannerError(f"arm {self.arm} needs a commanded goal")
        if self.arm in ("RC", "collect") and self.goal is not None:
            raise PlannerError("RC evaluates no goal")

    @property
    def needs_model(self) -> bool:
        return self.arm in ("P", "S")

    def needs_decision(self) -> bool:
        return self.executed % EXEC == 0

    def remaining(self) -> int:
        return H if self.budget is None else self.budget - self.executed

    def prepare(self) -> np.ndarray:
        """Draw this decision's block and build the candidates (identical for every arm at the same decision index)."""
        k = len(self.decisions)
        plans, arr = candidates(self.retained, draw_block(self.stream_key, k, self.n_candidates), self.n_candidates)
        self.pending = (plans, arr)
        return arr

    def choose(self, index: int, predicted_reach: Optional[int] = None) -> None:
        if self.pending is None:
            raise PlannerError("choose() without prepare()")
        if not self.needs_model and index != 0:
            raise PlannerError("RC / collection always takes candidate 0")
        plans, _arr = self.pending
        self.retained = plans[int(index)]
        self.decisions.append(Decision(index=len(self.decisions), chosen=int(index), n_candidates=self.n_candidates,
                                       at_tick=self.executed, predicted_reach=predicted_reach))
        self.pending = None

    def next_word(self) -> Tuple[int, int]:
        """The word for the next controlled tick (after a decision when one is due)."""
        if self.needs_decision() and (not self.decisions or self.decisions[-1].at_tick != self.executed):
            raise PlannerError("a decision is due")
        assert self.retained is not None
        w = self.retained.words[self.executed % EXEC]
        self.executed += 1
        self.words.append((int(w[0]), int(w[1])))
        return int(w[0]), int(w[1])


def rc_words(stream_key: str, n_candidates: int, length: int) -> List[Tuple[int, int]]:
    """The word stream of the no-model controller (RC / collection) for `length` ticks, regenerated offline."""
    c = Controller(arm="collect", stream_key=stream_key, n_candidates=n_candidates)
    out = []
    for _ in range(length):
        if c.needs_decision():
            c.prepare()
            c.choose(0)
        out.append(c.next_word())
    return out


def contract_digest() -> str:
    import json

    d = {"contract": PLANNER_CONTRACT, "H": H, "EXEC": EXEC, "MUTANTS": MUTANTS, "REFILL": REFILL_SEGMENTS,
         "FRESH": FRESH_SEGMENTS, "lengths": SEG_LENGTHS, "field_high": FIELD_HIGH, "box": BOX, "w_contact": W_CONTACT,
         "w_time": W_TIME, "fall_cost": FALL_COST, "std_weight": STD_WEIGHT, "arms": ARMS,
         "seed_rule": "sha256('m7u|cand|' + stream_key + '|' + decision)[:8] little-endian -> PCG64"}
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode("utf-8")).hexdigest()
