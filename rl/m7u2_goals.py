"""M7u2 (proposed gate m7u2): tick-0 goal eligibility, the fixed chance reference and deterministic goal selection
(design: docs/rl_model_planning_m7u2_tick0_proposal_2026-09-30.md, §3.2-§3.3). NumPy only.

Scope, fixed here and repeated in every record: a proposed test of rare airborne-point reach initiated from the normal
tick-0 reset, with the frozen m7u1 model on one seed. A reach is never reported as a landing, a crossing, a target
result or a clear.

- **Goal source.** Exactly POOL_EPISODES behaviour episodes of this run, named c000..c359 in advance, each at most
  POOL_TICKS words from the normal reset. None of them trains the model, tunes the planner or alters a threshold.
- **Candidate (entry, tau).** tau in [TAU_MIN, TAU_MAX]; the row at tau is valid and airborne, and is not the
  fatal-fall tick; y_tau - y_spawn >= RISE.
- **Rarity.** At most REF_MAX_REACHING of the REF_EPISODES preserved m7u1 behaviour episodes (same reset, same
  behaviour; read-only) make a valid airborne reach of the +-BOX box at any input tick 1..BUDGET.
- **Selection.** Deterministic from the pool alone, never from any trial outcome:
  - episodes are taken in the order of sha256('m7u2|goal|<entry>');
  - within an episode, its eligible taus are tried in the order of sha256('m7u2|goal|<entry>|<tau>');
  - the first tau whose goal definition (the box centre x, y) is not byte-identical to an already registered goal's is
    registered. A passed-over tau is recorded with the goal it duplicated; an episode whose every eligible tau
    duplicates is skipped and recorded;
  - the first N_GOALS registrations are the goals, one per episode;
  - boxes MAY overlap. Overlapping pairs are recorded, and goals that overlap are correlated trials, not independent
    evidence.
- **Too few goals.** The run is INCOMPLETE. There is no fill, relaxation or second pool.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

import m7u_state as us

GOAL_CONTRACT = "m7u2_tick0_goal_v1"
SCOPE = ("proposed test of rare airborne-point reach initiated from the normal tick-0 reset (frozen m7u1 model, "
         "one seed); not a landing, crossing, target or clear")
POOL_EPISODES = 360
POOL_TICKS = 128
TAU_MIN, TAU_MAX = 32, 96
BUDGET = 128
RISE = 300.0
BOX = 150.0
REF_EPISODES = 92
REF_MAX_REACHING = 1
N_GOALS = 24
SCRAMBLE_SHIFT = N_GOALS // 2    # 12
OVERLAP_SPAN = 2 * BOX            # two +-BOX boxes intersect iff their centres are within 2 * BOX on both axes (REPORTED only)
POOL_ENTRIES: Tuple[str, ...] = tuple(f"c{i:03d}" for i in range(POOL_EPISODES))
# Rise events are REPORTED only (never a selection criterion). A double jump is counted only from an entry into
# JumpAerialF / JumpAerialB, never from jumps_used (a capacity counter that up-B sets to jumps_max).
RISE_EVENTS = {"ground_jump": (20, 21), "double_jump": (24, 25), "up_b": (225, 226), "air_tornado": (228,)}


class GoalError(RuntimeError):
    def __init__(self, msg: str, *, incomplete: bool = False, record: Optional[Mapping[str, Any]] = None):
        super().__init__(msg)
        self.incomplete = incomplete
        self.record = dict(record or {})


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def row_digest(row: np.ndarray) -> str:
    """Digest of one native row (NaN normalised), used to pin the tick-0 reset row."""
    r = np.array(row, dtype=np.float64)
    return hashlib.sha256(np.where(np.isnan(r), -1.2345e300, r).tobytes()).hexdigest()


def reach_ok(rows: np.ndarray, fell: bool) -> np.ndarray:
    """Per input tick: valid, airborne, and not the fatal-fall tick (the m7u1 reach semantics without the box)."""
    F = us.F
    ok = (rows[:, F["valid"]] == 1.0) & (rows[:, F["ga"]] == 1.0)
    ok[0] = False
    if fell:
        ok[len(rows) - 1] = False
    return ok


class Reference:
    """The fixed chance reference: per episode, the positions and reach-validity of input ticks 1..BUDGET."""

    def __init__(self, episodes: Sequence[Tuple[str, np.ndarray, bool]], budget: int = BUDGET):
        self.ids = [str(e) for e, _r, _f in episodes]
        n = len(episodes)
        self.budget = int(budget)
        self.x = np.zeros((n, budget))
        self.y = np.zeros((n, budget))
        self.ok = np.zeros((n, budget), dtype=bool)
        for i, (_e, rows, fell) in enumerate(episodes):
            ok = reach_ok(np.asarray(rows, dtype=np.float64), bool(fell))
            m = min(budget, len(rows) - 1)
            self.x[i, :m] = rows[1:m + 1, us.F["x"]]
            self.y[i, :m] = rows[1:m + 1, us.F["y"]]
            self.ok[i, :m] = ok[1:m + 1]

    @property
    def n(self) -> int:
        return len(self.ids)

    def reaching(self, gx: float, gy: float, exclude: Optional[str] = None) -> int:
        """How many reference episodes make a valid airborne reach of the box around (gx, gy) within the budget."""
        hit = self.ok & (np.abs(self.x - gx) <= BOX) & (np.abs(self.y - gy) <= BOX)
        per = hit.any(axis=1)
        if exclude is not None and exclude in self.ids:
            per[self.ids.index(exclude)] = False
        return int(per.sum())

    def digest(self) -> str:
        h = hashlib.sha256()
        h.update(json.dumps({"ids": self.ids, "budget": self.budget}).encode("utf-8"))
        for a in (self.x, self.y, self.ok):
            h.update(np.ascontiguousarray(a).tobytes())
        return h.hexdigest()


def candidates(rows: np.ndarray, fell: bool, spawn_y: float) -> List[int]:
    F = us.F
    ok = reach_ok(rows, fell)
    return [tau for tau in range(TAU_MIN, min(TAU_MAX, len(rows) - 1) + 1)
            if ok[tau] and rows[tau, F["y"]] - spawn_y >= RISE]


def rise_events(rows: np.ndarray, a: int, b: int) -> List[Tuple[int, str]]:
    """(input tick, kind) of every status ENTRY into a rise-producing status in (a, b] (reported only)."""
    st = np.asarray(rows)[:, us.F["status"]].astype(int)
    out = []
    for i in range(max(a + 1, 1), min(b, len(st) - 1) + 1):
        if st[i] != st[i - 1]:
            for name, ids in RISE_EVENTS.items():
                if st[i] in ids:
                    out.append((i, name))
    return out


def composition(events: Sequence[Tuple[int, str]]) -> str:
    counts: Dict[str, int] = {}
    for _i, n in events:
        counts[n] = counts.get(n, 0) + 1
    return "+".join(n + (f"x{counts[n]}" if counts[n] > 1 else "") for n in RISE_EVENTS if n in counts) or "none"


@dataclass
class Goal:
    k: int                          # registered order
    entry: str                      # pool entry (c000..c359)
    episode_id: str
    tau: int                        # the goal is the recorded state at input tick tau
    x: float
    y: float
    rise: float                     # y - y_spawn
    ref_reaching: int               # reference episodes reaching its box within the budget (<= REF_MAX_REACHING)
    witness: List[Tuple[int, int]] = field(default_factory=list)       # the pool episode's own words 0..tau-1
    witness_composition: str = ""   # reported only

    def to_json(self) -> Dict[str, Any]:
        return dict(self.__dict__)


def overlap_report(registered: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Overlaps among registered goals (their +-BOX boxes intersect iff both centre offsets are <= OVERLAP_SPAN).
    Reported only: overlap never affects selection. Goals that overlap are correlated, not independent evidence."""
    n = len(registered)
    pairs: List[Dict[str, Any]] = []
    per = [0] * n
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            a, b = registered[i], registered[j]
            dx, dy = abs(a["x"] - b["x"]), abs(a["y"] - b["y"])
            if dx <= OVERLAP_SPAN and dy <= OVERLAP_SPAN:
                pairs.append({"k": [i, j], "entries": [str(a["entry"]), str(b["entry"])], "dx": float(dx),
                              "dy": float(dy)})
                per[i] += 1
                per[j] += 1
                parent[find(i)] = find(j)
    groups: Dict[int, List[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    correlated = sorted(g for g in groups.values() if len(g) > 1)
    return {"pairs": pairs, "n_pairs": len(pairs), "n_possible_pairs": n * (n - 1) // 2, "per_goal": per,
            "correlated_groups": correlated, "goals_in_a_group": sum(len(g) for g in correlated),
            "independent_goals": n - sum(len(g) for g in correlated),
            "reading": "goals whose boxes overlap are correlated trials, not independent evidence"}


def select_goals(pool: Sequence[Mapping[str, Any]], reference: Reference, tick0_row: np.ndarray, *,
                 entries: Sequence[str] = POOL_ENTRIES, n_goals: int = N_GOALS) -> Dict[str, Any]:
    """pool: one mapping per pool episode with entry, episode_id, rows (T+1, F), words (T, 2), fell. Returns the
    registered goals and the selection record. There is deliberately no outcome argument: selection sees the pool and
    the reference only."""
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
        if len(p["words"]) > POOL_TICKS or len(rows) != len(p["words"]) + 1:
            raise GoalError(f"{p['entry']}: {len(p['words'])} words, {len(rows)} rows (at most {POOL_TICKS} words)")
        same = (rows[0] == t0) | (np.isnan(rows[0]) & np.isnan(t0))
        if not same.all():
            raise GoalError(f"{p['entry']}: the reset row differs from the tick-0 record")
        taus = candidates(rows, bool(p["fell"]), spawn_y)
        n_with_candidates += bool(taus)
        elig = [t for t in taus if reference.reaching(rows[t, F["x"]], rows[t, F["y"]]) <= REF_MAX_REACHING]
        n_eligible_points += len(elig)
        if not elig:
            continue
        options = []
        for tau in sorted(elig, key=lambda t: sha(f"m7u2|goal|{p['entry']}|{t}")):
            options.append({"entry": str(p["entry"]), "episode_id": str(p["episode_id"]), "tau": int(tau),
                            "x": float(rows[tau, F["x"]]), "y": float(rows[tau, F["y"]]),
                            "rise": float(rows[tau, F["y"]] - spawn_y),
                            "ref_reaching": reference.reaching(rows[tau, F["x"]], rows[tau, F["y"]]),
                            "witness": [(int(a), int(b)) for a, b in np.asarray(p["words"])[:tau]],
                            "witness_composition": composition(rise_events(rows, 0, tau))})
        choices.append({"entry": str(p["entry"]), "sha": sha(f"m7u2|goal|{p['entry']}"), "options": options})
    choices.sort(key=lambda c: c["sha"])

    def same_definition(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
        """An exact duplicate goal definition: the same box centre (compared exactly, not within a tolerance)."""
        return a["x"] == b["x"] and a["y"] == b["y"]

    registered: List[Dict[str, Any]] = []
    passed_over: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for c in choices:
        if len(registered) >= n_goals:
            break
        chosen = None
        for o in c["options"]:
            dup = [r["entry"] for r in registered if same_definition(o, r)]
            if not dup:
                chosen = o
                break
            passed_over.append({"entry": o["entry"], "tau": o["tau"], "duplicates": dup})
        if chosen is None:
            skipped.append({"entry": c["entry"], "eligible_taus": len(c["options"])})
            continue
        registered.append(chosen)
    overlap = overlap_report(registered)
    record = {"contract": GOAL_CONTRACT, "scope": SCOPE, "pool_episodes": len(pool),
              "episodes_with_candidates": n_with_candidates, "eligible_points": n_eligible_points,
              "episodes_with_a_goal": len(choices), "passed_over_duplicates": passed_over,
              "skipped_for_duplicate": skipped, "registered": len(registered), "overlap": overlap,
              "reference_episodes": reference.n,
              "reference_digest": reference.digest(), "tick0_row_digest": row_digest(t0),
              "scramble": {"rule": f"pi(k) = (k + {SCRAMBLE_SHIFT}) mod {n_goals}"}}
    if len(registered) < n_goals:
        raise GoalError(f"only {len(registered)} distinct eligible goals < {n_goals}", incomplete=True,
                        record=record)
    goals = [Goal(k=k, entry=c["entry"], episode_id=c["episode_id"], tau=c["tau"], x=c["x"], y=c["y"], rise=c["rise"],
                  ref_reaching=c["ref_reaching"], witness=c["witness"], witness_composition=c["witness_composition"])
             for k, c in enumerate(registered)]
    return {"goals": goals, "record": record}


def scrambled(k: int, n_goals: int = N_GOALS) -> int:
    """pi(k) = (k + n / 2) mod n: a derangement pairing every goal with the one half the registered list away."""
    return (int(k) + n_goals // 2) % n_goals


def goals_digest(goals: Sequence[Goal]) -> str:
    return sha(json.dumps([g.to_json() for g in goals], sort_keys=True, default=str))


def contract_digest() -> str:
    d = {"contract": GOAL_CONTRACT, "pool": [POOL_EPISODES, POOL_TICKS], "tau": [TAU_MIN, TAU_MAX], "budget": BUDGET,
         "rise": RISE, "box": BOX, "reference": [REF_EPISODES, REF_MAX_REACHING], "n_goals": N_GOALS,
         "scramble_shift": SCRAMBLE_SHIFT, "overlap_span": OVERLAP_SPAN,
         "keys": ["m7u2|goal|<entry>|<tau>", "m7u2|goal|<entry>"],
         "duplicate": "exact (x, y) centre; next eligible tau in sha order, else skip", "overlap": "allowed, recorded"}
    return sha(json.dumps(d, sort_keys=True))
