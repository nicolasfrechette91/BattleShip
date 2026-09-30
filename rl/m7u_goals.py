"""M7u gate m7u1: held-out split, rising-airborne goal selection, pooled chance q and the scrambled pairing (design:
docs/rl_model_planning_m7u_proposal_2026-09-29.md, revision 2, §6.2). NumPy only.

Scope, fixed here and repeated in every record: these goals test LOCAL CONTROL AFTER THE AGENT'S OWN SUPPLIED PREFIX.
A reach is a rising airborne point 64 ticks from a start state taken from this run's own behaviour episodes; it is never
a landing, a crossing or a policy-controlled reach from tick 0. Prefixes come only from this run's own RC episodes.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

import m7u_state as us

GOAL_CONTRACT = "m7u1_rising_goal_v1"
SCOPE = "local control after the agent's own supplied recorded prefix (not a landing, crossing or tick-0 reach)"
HZ = 64                 # goal horizon: the witness reaches the goal exactly HZ ticks after the start
BUDGET = 96             # controlled ticks per trial
T_MIN, T_MAX = 60, 600  # start tick range (prefix length)
RISE = 300.0            # y* - y_t >= RISE
BOX = 150.0             # half-width, per axis
Q_MAX = 0.02
N_GOALS = 40
PER_EPISODE = 4
MIN_GAP = 32
MIN_CANDIDATES = 30
SCRAMBLE_SHIFT = 20
HELDOUT_EPISODES = 12


class GoalError(RuntimeError):
    def __init__(self, msg: str, *, incomplete: bool = False):
        super().__init__(msg)
        self.incomplete = incomplete


@dataclass
class Goal:
    k: int                     # registered order
    episode_id: str
    t: int                     # start tick = prefix length
    x: float                   # goal point (the recorded state at t + HZ)
    y: float
    start_x: float
    start_y: float
    start_ga: int
    q: float
    filled: bool               # selected by the fill rule (q > Q_MAX)
    prefix: List[Tuple[int, int]] = field(default_factory=list)
    witness: List[Tuple[int, int]] = field(default_factory=list)
    expected_start_row: List[float] = field(default_factory=list)

    def to_json(self) -> Dict[str, Any]:
        d = dict(self.__dict__)
        d["expected_start_row"] = [None if (isinstance(v, float) and np.isnan(v)) else v for v in self.expected_start_row]
        return d


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def heldout_split(episode_ids: Sequence[str], n: int = HELDOUT_EPISODES) -> Tuple[List[str], List[str]]:
    """(training ids, held-out ids): the n ids with the smallest sha256('m7u1|holdout|' + id) are held out."""
    order = sorted(episode_ids, key=lambda e: sha(f"m7u1|holdout|{e}"))
    held = order[:n]
    return [e for e in episode_ids if e not in set(held)], held


def usable_pairs(rows: np.ndarray, fell: bool, h: int = HZ) -> np.ndarray:
    """Start ticks t of an episode with rows t..t+h all valid and t+h not the fatal-fall tick (the last row of a fall)."""
    F = us.F
    valid = rows[:, F["valid"]] == 1.0
    T = len(rows) - 1
    out = []
    run = 0
    ok = np.zeros(len(rows), dtype=bool)
    for i in range(len(rows)):
        run = run + 1 if valid[i] else 0
        ok[i] = run >= h + 1          # rows i-h..i all valid
    for t in range(0, T - h + 1):
        end = t + h
        if ok[end] and not (fell and end == T):
            out.append(t)
    return np.array(out, dtype=np.int64)


@dataclass
class ChanceTable:
    """Training-split h-tick displacements grouped by start ground/air, sorted by dx for exact box counts."""
    dx: Dict[int, np.ndarray]
    dy: Dict[int, np.ndarray]
    air_end: Dict[int, np.ndarray]
    count: Dict[int, int]

    def q(self, start_ga: int, dx: float, dy: float) -> float:
        g = int(start_ga)
        n = self.count.get(g, 0)
        if n == 0:
            return 1.0
        xs = self.dx[g]
        lo = np.searchsorted(xs, dx - BOX, side="left")
        hi = np.searchsorted(xs, dx + BOX, side="right")
        sel = (np.abs(self.dy[g][lo:hi] - dy) <= BOX) & self.air_end[g][lo:hi]
        return float(sel.sum()) / n


def chance_table(training: Sequence[Tuple[np.ndarray, bool]]) -> ChanceTable:
    F = us.F
    acc: Dict[int, List[np.ndarray]] = {0: [], 1: []}
    for rows, fell in training:
        ts = usable_pairs(rows, fell)
        if not len(ts):
            continue
        a, b = rows[ts], rows[ts + HZ]
        block = np.stack([a[:, F["ga"]], b[:, F["x"]] - a[:, F["x"]], b[:, F["y"]] - a[:, F["y"]], b[:, F["ga"]]], axis=1)
        for g in (0, 1):
            acc[g].append(block[block[:, 0] == g])
    dx, dy, air, cnt = {}, {}, {}, {}
    for g in (0, 1):
        m = np.concatenate(acc[g]) if acc[g] else np.zeros((0, 4))
        order = np.argsort(m[:, 1], kind="stable")
        m = m[order]
        dx[g], dy[g], air[g], cnt[g] = m[:, 1], m[:, 2], m[:, 3] == 1.0, len(m)
    return ChanceTable(dx=dx, dy=dy, air_end=air, count=cnt)


def rising_candidates(episode_id: str, rows: np.ndarray, words: np.ndarray, fell: bool) -> List[Dict[str, Any]]:
    F = us.F
    out = []
    for t in usable_pairs(rows, fell):
        if not (T_MIN <= t <= T_MAX):
            continue
        s, g = rows[t], rows[t + HZ]
        if int(g[F["ga"]]) != 1 or g[F["y"]] - s[F["y"]] < RISE:
            continue
        if abs(s[F["x"]] - g[F["x"]]) <= BOX and abs(s[F["y"]] - g[F["y"]]) <= BOX and int(s[F["ga"]]) == 1:
            continue                      # the start already satisfies the goal
        out.append({"episode_id": episode_id, "t": int(t), "x": float(g[F["x"]]), "y": float(g[F["y"]]),
                    "start_x": float(s[F["x"]]), "start_y": float(s[F["y"]]), "start_ga": int(s[F["ga"]])})
    return out


def select_goals(heldout: Mapping[str, Tuple[np.ndarray, np.ndarray, bool]], table: ChanceTable) -> Dict[str, Any]:
    """The registered goal list (k = 0..N_GOALS-1) and its selection record. heldout: id -> (rows, words, fell)."""
    cands: List[Dict[str, Any]] = []
    for eid in sorted(heldout):
        rows, words, fell = heldout[eid]
        cands += rising_candidates(eid, rows, words, fell)
    if len(cands) < MIN_CANDIDATES:
        raise GoalError(f"{len(cands)} rising airborne candidates < {MIN_CANDIDATES}", incomplete=True)
    for c in cands:
        c["q"] = table.q(c["start_ga"], c["x"] - c["start_x"], c["y"] - c["start_y"])
        c["sha"] = sha(f"m7u1|goal|{c['episode_id']}|{c['t']}")
    chosen: List[Dict[str, Any]] = []
    per_ep: Dict[str, List[int]] = {}

    def fits(c: Mapping[str, Any]) -> bool:
        ts = per_ep.get(c["episode_id"], [])
        return len(ts) < PER_EPISODE and all(abs(c["t"] - t) >= MIN_GAP for t in ts)

    def take(c: Dict[str, Any], filled: bool) -> None:
        c["filled"] = filled
        chosen.append(c)
        per_ep.setdefault(c["episode_id"], []).append(c["t"])

    for c in sorted([c for c in cands if c["q"] <= Q_MAX], key=lambda c: c["sha"]):
        if len(chosen) < N_GOALS and fits(c):
            take(c, False)
    if len(chosen) < N_GOALS:
        taken = {(c["episode_id"], c["t"]) for c in chosen}
        for c in sorted([c for c in cands if c["q"] > Q_MAX], key=lambda c: (c["q"], c["sha"])):
            if len(chosen) < N_GOALS and (c["episode_id"], c["t"]) not in taken and fits(c):
                take(c, True)
    if len(chosen) < N_GOALS:
        raise GoalError(f"only {len(chosen)} goals satisfy the per-episode constraints", incomplete=True)
    goals = []
    for k, c in enumerate(chosen):
        rows, words, _fell = heldout[c["episode_id"]]
        t = c["t"]
        goals.append(Goal(k=k, episode_id=c["episode_id"], t=t, x=c["x"], y=c["y"], start_x=c["start_x"],
                          start_y=c["start_y"], start_ga=c["start_ga"], q=c["q"], filled=bool(c["filled"]),
                          prefix=[(int(a), int(b)) for a, b in words[:t]],
                          witness=[(int(a), int(b)) for a, b in words[t:t + HZ]],
                          expected_start_row=[float(v) for v in rows[t]]))
    rec = {"contract": GOAL_CONTRACT, "scope": SCOPE, "candidates": len(cands),
           "tail_candidates": sum(1 for c in cands if c["q"] <= Q_MAX), "filled": sum(g.filled for g in goals),
           "scramble": {"rule": f"pi(k) = (k + {SCRAMBLE_SHIFT}) mod {N_GOALS}"}}
    return {"goals": goals, "record": rec}


def scrambled(k: int) -> int:
    return (int(k) + SCRAMBLE_SHIFT) % N_GOALS


def goals_digest(goals: Sequence[Goal]) -> str:
    return sha(json.dumps([g.to_json() for g in goals], sort_keys=True, default=str))
