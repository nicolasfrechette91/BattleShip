"""M7s stage 1 (learned return): the goal contract, goal features, frozen goal set, matched schedule, evaluation plan
and GCSL hindsight relabelling. Pure Python / numpy: no torch, no game, no inherited module changes.

Design: docs/rl_goal_exploration_design_2026-09-28.md (revision 5, sections 3-4).

  btt_goal_cell_v1     cell = (i, j, contact): 300-unit bins of the stage box x [-3900, 3300], y [-4050, 3600] (the
                       static btt_spatial_v1 vertices plus the moving platform's surface range; 24 x 26 bins) and
                       contact = AIR, a grounded floor line id (0, 1, 2, 3, 4, 19) or OTHER. A VALID cell is the cell
                       of a consumed tick with btt_active 1 and fighter_valid 1, inside the box, that is not the tick on
                       which a native-failure (fatal) fall ends the episode. Success = the first valid reach of the
                       commanded cell before the horizon. The same validity defines the archive and the labels.
                       SURVIVAL_TICKS (120) is a separately named, non-decisive collection diagnostic only.
  btt_goal_obs_v3_v1   the unchanged v3 observation plus a separate GOAL_DIM = 14 goal vector (goal_features()).
  btt_gcsl_return_v1   supervised examples (o_t, a_t, g = c_{t+h}, h) with remaining-horizon input b in [h, H - t]
                       (b = h with probability 1/2, else uniform); collection and evaluation use b = H - t. Both t and
                       t + h lie inside the recorded ticks of the episode (a quota-cut episode supplies its prefix only).

Goals only ever come from the seed's own phase-A tick-0 episodes (the frozen set E and archive A); no position,
height, wall, route or waypoint term exists here. Every random draw is a Python-side numpy generator seeded from a
registered string; the native RNG is never read, logged, compared or controlled.
"""
from __future__ import annotations

import bisect
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

CELL_CONTRACT = "btt_goal_cell_v1"
OBS_CONTRACT = "btt_goal_obs_v3_v1"
GCSL_CONTRACT = "btt_gcsl_return_v1"
SIDECAR_SCHEMA = "btt_goal_sidecar_v1"
SIDECAR_FILE = "m7s_goals.json.gz"
END_GOAL = "goal_reached"                         # truncation_reason of an evaluation episode ended by
                                                  # its first valid reach (tracker end_reason: horizon)
END_QUOTA = "tick_quota"                          # truncation_reason of a collection episode cut by
                                                  # the worker tick quota (tracker end_reason: horizon)
NATIVE_HORIZON = "max_episode_steps"              # truncation_reason of the native 3,600-tick horizon

HORIZON = 3600
CELL = 300.0
BOX = (-3900.0, 3300.0, -4050.0, 3600.0)          # x0, x1, y0, y1 (native units)
NX = 24                                           # ceil((x1 - x0) / CELL)
NY = 26                                           # ceil((y1 - y0) / CELL)
AIR = -1
OTHER = -2
FLOOR_LINES = (0, 1, 2, 3, 4, 19)                 # the geometry's floor-kind lines (19 = the moving platform)
CONTACT_CLASSES = (AIR,) + FLOOR_LINES + (OTHER,)
GOAL_DIM = 1 + 2 + 2 + len(CONTACT_CLASSES) + 1   # 14
SURVIVAL_TICKS = 120                              # NON-DECISIVE collection diagnostic: no fatal fall within this after a
                                                  # reach; never changes success, the archive or the labels
PHASE_A_EPISODES = 20
E_RARE = 10
E_MID = 5
RARE_BAND = (1, 2)                                # reached by 1-2 of the 20 phase-A episodes
MID_BAND = (3, 9)
EVAL_REPEATS = 2
SCHEDULE_GOALS = 8                                # goals per collection episode (the next on the tick of a valid reach)
SCHEDULE_EPISODES = 400                           # schedule entries per worker (phase B needs about 20-40)
E_SHARE = 0.5                                     # a schedule draw comes from E with this probability, else from A
B_EXACT_P = 0.5                                   # relabelled b = h with this probability, else uniform in [h, H - t]

_X0, _X1, _Y0, _Y1 = BOX
_MX, _HW = (_X0 + _X1) / 2.0, (_X1 - _X0) / 2.0
_MY, _HH = (_Y0 + _Y1) / 2.0, (_Y1 - _Y0) / 2.0

Cell = Tuple[int, int, int]


class GoalContractError(RuntimeError):
    pass


# -- cells ------------------------------------------------------------------------------------------------------------


def contact_of(airborne: bool, floor_line_id: int) -> int:
    if airborne or int(floor_line_id) < 0:
        return AIR
    return int(floor_line_id) if int(floor_line_id) in FLOOR_LINES else OTHER


def cell_of(x: float, y: float, airborne: bool, floor_line_id: int) -> Optional[Cell]:
    """The cell of a live position, or None outside the box."""
    if not (_X0 <= x <= _X1 and _Y0 <= y <= _Y1):
        return None
    i = min(int((x - _X0) // CELL), NX - 1)
    j = min(int((y - _Y0) // CELL), NY - 1)
    return (i, j, contact_of(airborne, floor_line_id))


def reply_state(reply: Mapping[str, Any]) -> Dict[str, Any]:
    """Position, contact and liveness of one raw native reply (observation + spatial diagnostic)."""
    o = reply.get("observation") or {}
    fi = (reply.get("spatial") or {}).get("fighter") or {}
    return {"live": bool(o.get("btt_active")) and bool(o.get("fighter_valid")),
            "x": float(o.get("position_x", 0.0)), "y": float(o.get("position_y", 0.0)),
            "airborne": int(o.get("ground_air_state", 0)) == 1,
            "floor": int(fi.get("floor_line_id", -1)) if fi else -1}


def state_cell(state: Mapping[str, Any]) -> Optional[Cell]:
    if not state.get("live"):
        return None
    return cell_of(float(state["x"]), float(state["y"]), bool(state["airborne"]), int(state["floor"]))


def cell_of_trace_row(row: Sequence[Any], fields: Mapping[str, int]) -> Optional[Cell]:
    """The same cell from an M7r gate-trace row (rl/m7r_worker.trace_row fields)."""
    if not row[fields["live"]]:
        return None
    return cell_of(float(row[fields["pos_x"]]), float(row[fields["pos_y"]]), bool(row[fields["airborne"]]),
                   int(row[fields["floor_line_id"]]))


def cell_key(c: Cell) -> str:
    return f"{int(c[0])},{int(c[1])},{int(c[2])}"


def cell_centre(c: Cell) -> Tuple[float, float]:
    return _X0 + (int(c[0]) + 0.5) * CELL, _Y0 + (int(c[1]) + 0.5) * CELL


def valid_cells(cells: Sequence[Optional[Cell]], fell: bool) -> List[Optional[Cell]]:
    """The valid cells of one episode (index k - 1 = consumed tick k): the live in-box cells, except the last tick of an
    episode that ended in a native-failure (fatal) fall. Nothing else is removed."""
    out = list(cells)
    if fell and out:
        out[-1] = None
    return out


# -- goal features (btt_goal_obs_v3_v1) ---------------------------------------------------------------------------------


def goal_features(goal: Optional[Cell], x: float, y: float, b: float) -> np.ndarray:
    """The 14-value goal vector; all zeros for the null goal. b = the remaining-horizon budget in ticks."""
    f = np.zeros(GOAL_DIM, dtype=np.float32)
    if goal is None:
        return f
    cx, cy = cell_centre(goal)
    f[0] = 1.0
    f[1] = (cx - _MX) / _HW
    f[2] = (cy - _MY) / _HH
    f[3] = np.clip((cx - float(x)) / _HW, -2.0, 2.0)
    f[4] = np.clip((cy - float(y)) / _HH, -2.0, 2.0)
    f[5 + CONTACT_CLASSES.index(int(goal[2]))] = 1.0
    f[13] = np.clip(float(b) / HORIZON, 0.0, 1.0)
    return f


def goal_features_batch(goals: np.ndarray, xs: np.ndarray, ys: np.ndarray, bs: np.ndarray) -> np.ndarray:
    """Vectorised goal_features for relabelled examples (every goal non-null); equal to the scalar function."""
    goals = np.asarray(goals, dtype=np.int64)
    n = len(goals)
    f = np.zeros((n, GOAL_DIM), dtype=np.float32)
    if n == 0:
        return f
    cx = _X0 + (goals[:, 0] + 0.5) * CELL
    cy = _Y0 + (goals[:, 1] + 0.5) * CELL
    f[:, 0] = 1.0
    f[:, 1] = (cx - _MX) / _HW
    f[:, 2] = (cy - _MY) / _HH
    f[:, 3] = np.clip((cx - np.asarray(xs, dtype=np.float64)) / _HW, -2.0, 2.0)
    f[:, 4] = np.clip((cy - np.asarray(ys, dtype=np.float64)) / _HH, -2.0, 2.0)
    index = {c: k for k, c in enumerate(CONTACT_CLASSES)}
    cols = np.array([5 + index[int(c)] for c in goals[:, 2]], dtype=np.int64)
    f[np.arange(n), cols] = 1.0
    f[:, 13] = np.clip(np.asarray(bs, dtype=np.float64) / HORIZON, 0.0, 1.0)
    return f


# -- registered seeds ----------------------------------------------------------------------------------------------------


def seed_int(*parts: Any) -> int:
    key = "m7s1|" + "|".join(str(p) for p in parts)
    return int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "little")


def generator(*parts: Any) -> np.random.Generator:
    return np.random.default_rng(seed_int(*parts))


def collection_seed(seed: int, phase: str, rank: int, worker_episode: int) -> int:
    """Action-sampling seed of one collection episode; identical for R and U (common random numbers)."""
    return seed_int("sample", seed, phase, rank, worker_episode)


def evaluation_seed(seed: int, entry: int) -> int:
    return seed_int("sample", seed, "eval", entry)


# -- the frozen goal set E and archive A (phase A) -------------------------------------------------------------------------


@dataclass
class PhaseAEpisode:
    episode_id: str
    artifact_dir: Optional[str]
    native_action_digest: Optional[str]
    first_reach: Dict[str, int]          # cell key -> first consumed tick k (>= 1) of a valid occupation
    end_reason: str
    started_at_tick0: bool = True


def archive_counts(episodes: Sequence[PhaseAEpisode]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for e in episodes:
        for key in e.first_reach:
            counts[key] = counts.get(key, 0) + 1
    return counts


def parse_key(key: str) -> Cell:
    i, j, c = (int(v) for v in key.split(","))
    return (i, j, c)


def freeze_goal_set(seed: int, episodes: Sequence[PhaseAEpisode]) -> Dict[str, Any]:
    """E_rare (reached by 1-2 of the phase-A episodes) and E_mid (3-9), each in sha256 order; with witnesses."""
    if len(episodes) != PHASE_A_EPISODES:
        raise GoalContractError(f"phase A has {len(episodes)} episodes, {PHASE_A_EPISODES} required")
    bad = [e.episode_id for e in episodes if not e.started_at_tick0]
    if bad:
        raise GoalContractError(f"phase-A episodes not started at normal tick 0: {bad}")
    counts = archive_counts(episodes)

    def ordered(lo: int, hi: int) -> List[str]:
        keys = [k for k, n in counts.items() if lo <= n <= hi]
        return sorted(keys, key=lambda k: hashlib.sha256(f"m7s1|E|{seed}|{k}".encode("utf-8")).hexdigest())

    rare, mid = ordered(*RARE_BAND)[:E_RARE], ordered(*MID_BAND)[:E_MID]
    if len(rare) < E_RARE or len(mid) < E_MID:
        raise GoalContractError(f"too few candidate goals: rare {len(rare)} / {E_RARE}, mid {len(mid)} / {E_MID}")

    def witnesses(key: str) -> List[Dict[str, Any]]:
        return [{"episode_id": e.episode_id, "artifact_dir": e.artifact_dir,
                 "native_action_digest": e.native_action_digest, "first_reach_tick": e.first_reach[key]}
                for e in episodes if key in e.first_reach]

    doc = {"contract": CELL_CONTRACT, "seed": int(seed), "phase_a_episodes": [e.episode_id for e in episodes],
           "archive": dict(sorted(counts.items())),
           "rare": [{"cell": k, "phase_a_episodes": counts[k], "witnesses": witnesses(k)} for k in rare],
           "mid": [{"cell": k, "phase_a_episodes": counts[k], "witnesses": witnesses(k)} for k in mid],
           "candidates": {"rare": sum(1 for n in counts.values() if RARE_BAND[0] <= n <= RARE_BAND[1]),
                          "mid": sum(1 for n in counts.values() if MID_BAND[0] <= n <= MID_BAND[1])}}
    doc["digest"] = hashlib.sha256(json.dumps(doc, sort_keys=True).encode("utf-8")).hexdigest()
    return doc


def goal_set_cells(goal_set: Mapping[str, Any], stratum: str) -> List[Cell]:
    return [parse_key(g["cell"]) for g in goal_set[stratum]]


def check_provenance(goal_set: Mapping[str, Any], phase_a: Sequence[PhaseAEpisode]) -> List[str]:
    """Every E goal and every archive cell must come from the seed's own phase-A tick-0 episodes (and nothing else)."""
    problems: List[str] = []
    ids = {e.episode_id for e in phase_a}
    if set(goal_set.get("phase_a_episodes") or []) != ids:
        problems.append("goal set names episodes that are not this seed's phase A")
    counts = archive_counts(phase_a)
    if dict(goal_set.get("archive") or {}) != counts:
        problems.append("archive counts differ from the phase-A episodes")
    for stratum, band in (("rare", RARE_BAND), ("mid", MID_BAND)):
        for g in goal_set.get(stratum) or []:
            n = counts.get(g["cell"], 0)
            if not band[0] <= n <= band[1]:
                problems.append(f"{stratum} goal {g['cell']} reached by {n} phase-A episodes")
            if {w["episode_id"] for w in g["witnesses"]} - ids or len(g["witnesses"]) != n:
                problems.append(f"{stratum} goal {g['cell']} witnesses do not match phase A")
    return problems


# -- matched collection schedule and evaluation plan -------------------------------------------------------------------------


def make_schedule(seed: int, goal_set: Mapping[str, Any], *, ranks: int = 5, episodes: int = SCHEDULE_EPISODES,
                  goals: int = SCHEDULE_GOALS) -> Dict[str, Any]:
    """One schedule per seed, used identically by R and U: entry (rank, worker_episode) = up to `goals` cells, each
    from E with probability E_SHARE (uniform) else from the phase-A archive with weight (1 + n)^(-1/2)."""
    rng = generator("schedule", seed)
    e_keys = [g["cell"] for g in goal_set["rare"]] + [g["cell"] for g in goal_set["mid"]]
    a_keys = sorted(goal_set["archive"])
    w = np.array([(1.0 + goal_set["archive"][k]) ** -0.5 for k in a_keys], dtype=np.float64)
    w /= w.sum()
    entries: Dict[str, List[str]] = {}
    for r in range(ranks):
        for k in range(1, episodes + 1):
            row = []
            for _ in range(goals):
                if rng.random() < E_SHARE:
                    row.append(e_keys[int(rng.integers(len(e_keys)))])
                else:
                    row.append(a_keys[int(rng.choice(len(a_keys), p=w))])
            entries[f"{r}:{k}"] = row
    doc = {"seed": int(seed), "goal_set_digest": goal_set["digest"], "ranks": ranks, "episodes": episodes,
           "goals": goals, "e_share": E_SHARE, "entries": entries}
    doc["digest"] = hashlib.sha256(json.dumps(doc, sort_keys=True).encode("utf-8")).hexdigest()
    return doc


def schedule_for_rank(schedule: Mapping[str, Any], rank: int) -> Dict[int, List[Cell]]:
    out: Dict[int, List[Cell]] = {}
    for key, row in schedule["entries"].items():
        r, k = (int(v) for v in key.split(":"))
        if r == rank:
            out[k] = [parse_key(c) for c in row]
    return out


def make_eval_plan(seed: int, goal_set: Mapping[str, Any], *, ranks: int = 5) -> List[Dict[str, Any]]:
    """30 entries (E_rare x 2, E_mid x 2) in sha256 order; entry e is run by worker e mod ranks; same for R and U."""
    items = [(s, g["cell"], rep) for s in ("rare", "mid") for g in goal_set[s] for rep in range(EVAL_REPEATS)]
    items.sort(key=lambda it: hashlib.sha256(f"m7s1|eval|{seed}|{it[1]}|{it[2]}".encode("utf-8")).hexdigest())
    return [{"entry": e, "stratum": s, "cell": c, "repeat": rep, "rank": e % ranks,
             "sampling_seed": evaluation_seed(seed, e)} for e, (s, c, rep) in enumerate(items)]


# -- GCSL relabelling (btt_gcsl_return_v1) -------------------------------------------------------------------------


@dataclass
class EpisodeData:
    """One own tick-0 episode of the learner. obs[t] / pos[t] describe o_t (the state before a_t); cells[k - 1] is the
    valid cell after consumed tick k (None when not valid). Only recorded ticks exist: a quota-cut episode is its
    recorded prefix."""

    episode_id: str
    origin: str                                   # phase_a | phase_b
    obs: np.ndarray                               # (T, 606) float32
    pos: np.ndarray                               # (T, 2) float32
    actions: np.ndarray                           # (T, 2) int64: Track 1 stick, button
    cells: List[Optional[Cell]]                   # length T
    native_action_digest: Optional[str] = None
    visits: Dict[Cell, List[int]] = field(default_factory=dict)
    order: List[Cell] = field(default_factory=list)
    last: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    k_max: int = 0

    def __post_init__(self) -> None:
        if not (len(self.obs) == len(self.pos) == len(self.actions) == len(self.cells)):
            raise GoalContractError(f"episode {self.episode_id}: misaligned arrays")
        for k, c in enumerate(self.cells, start=1):
            if c is not None:
                self.visits.setdefault(c, []).append(k)
        self.order = sorted(self.visits)
        self.last = np.array([self.visits[c][-1] for c in self.order], dtype=np.int64)
        self.k_max = int(self.last.max()) if len(self.last) else 0


def sample_examples(episodes: Sequence[EpisodeData], n: int, rng: np.random.Generator) -> Dict[str, np.ndarray]:
    """n supervised examples (o_t, a_t, g = c_{t+h}, h) with b in [h, H - t]: episode uniform, t uniform over the ticks
    with a valid future cell, g uniform over the distinct valid cells after t. t < T and t + h <= T always (T = the
    recorded ticks), so a quota-cut episode supplies pairs from its recorded prefix only."""
    usable = [e for e in episodes if e.k_max >= 1]
    if not usable:
        raise GoalContractError("no episode with a valid achieved cell")
    ei, ts, hs, bs, gs = [], [], [], [], []
    for _ in range(int(n)):
        idx = int(rng.integers(len(usable)))
        e = usable[idx]
        t = int(rng.integers(e.k_max))                      # 0 <= t <= k_max - 1: some valid visit k > t exists
        cand = np.nonzero(e.last > t)[0]
        g = e.order[int(cand[int(rng.integers(len(cand)))])]
        visits = e.visits[g]
        k = visits[bisect.bisect_right(visits, t)]           # first valid visit of g after t
        h = k - t
        if not (0 <= t < k <= len(e.cells)):
            raise GoalContractError(f"{e.episode_id}: example outside the recorded prefix (t {t}, t + h {k})")
        b = h if rng.random() < B_EXACT_P else int(rng.integers(h, HORIZON - t + 1))
        ei.append(idx)
        ts.append(t)
        hs.append(h)
        bs.append(b)
        gs.append(g)
    ei_a, ts_a = np.array(ei), np.array(ts)
    obs = np.stack([usable[i].obs[t] for i, t in zip(ei_a, ts_a)])
    pos = np.stack([usable[i].pos[t] for i, t in zip(ei_a, ts_a)])
    act = np.stack([usable[i].actions[t] for i, t in zip(ei_a, ts_a)])
    goals = np.array(gs, dtype=np.int64)
    return {"obs": obs.astype(np.float32), "goal": goal_features_batch(goals, pos[:, 0], pos[:, 1], np.array(bs)),
            "stick": act[:, 0].astype(np.int64), "button": act[:, 1].astype(np.int64), "t": ts_a,
            "h": np.array(hs), "b": np.array(bs), "cell": goals,
            "episode": np.array([usable[i].episode_id for i in ei_a])}


# -- contract identity ----------------------------------------------------------------------------------------------------


def contract_description() -> Dict[str, Any]:
    return {"cell": {"contract": CELL_CONTRACT, "box": list(BOX), "cell": CELL, "bins": [NX, NY],
                     "contact_classes": list(CONTACT_CLASSES), "floor_lines": list(FLOOR_LINES),
                     "valid": "btt_active 1, fighter_valid 1, inside the box, not the tick on which a native-failure "
                              "(fatal) fall ends the episode",
                     "success": "first valid reach of the commanded cell (with its contact class) before the horizon; "
                                "an evaluation episode ends there with truncation_reason goal_reached",
                     "no_survival_requirement": "a valid first reach needs no future survival period",
                     "horizon_precedence": "a valid reach on the native horizon tick ends as goal_reached, not "
                                           "max_episode_steps",
                     "clear": "a reach on a native-clear tick is a clear (terminated native_clear, never truncated), not "
                              "a return; any claimed clear needs an exact native replay",
                     "next_goal": "collection: the next schedule goal is commanded after the reach tick k is consumed; it "
                                  "enters o_k and first applies to action a_k (consumed tick k + 1); no action is "
                                  "inserted; it can first be reached at k + 1",
                     "survival_diagnostic": f"{SURVIVAL_TICKS} ticks without a fatal fall after a reach (collection only; "
                                            "never decisive, never used by the archive or the labels)"},
            "observation": {"contract": OBS_CONTRACT, "v3": "btt_policy_obs_v3_entities (unchanged, 606)",
                            "goal_dim": GOAL_DIM,
                            "goal": ["has_goal", "centre_x", "centre_y", "delta_x", "delta_y",
                                     *[f"contact_{c}" for c in CONTACT_CLASSES], "b_over_H"]},
            "gcsl": {"contract": GCSL_CONTRACT, "example": "(o_t, a_t, g = c_{t+h}, h), b in [h, H - t]",
                     "b_exact_p": B_EXACT_P, "evaluation_b": "H - t", "horizon": HORIZON,
                     "prefix_rule": "t and t + h inside the recorded ticks (quota-cut episodes: prefix only)"},
            "goals": {"phase_a_episodes": PHASE_A_EPISODES, "rare": [E_RARE, list(RARE_BAND)],
                      "mid": [E_MID, list(MID_BAND)], "eval_repeats": EVAL_REPEATS, "schedule_goals": SCHEDULE_GOALS,
                      "e_share": E_SHARE}}


def contract_digest() -> str:
    return hashlib.sha256(json.dumps(contract_description(), sort_keys=True).encode("utf-8")).hexdigest()


def keys_of(cells: Iterable[Optional[Cell]]) -> List[str]:
    return [cell_key(c) for c in cells if c is not None]
