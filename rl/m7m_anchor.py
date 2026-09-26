"""M7m: anchored backward consolidation of the replay-verified M7l training sweep - the pure part (no game, SB3, torch).

Design: docs/rl_sweep_consolidation_m7m_design.md. Registration: docs/rl_sweep_consolidation_m7m_anchor.json (the
source trajectory and its provenance) and docs/rl_sweep_consolidation_m7m_feasibility_plan.json (the no-training gate).

The anchor is ONE tick-0 training trajectory of run m7l_t2_s1 (episode_20260925T190612Z_49414363, discovered by a
policy trained under btt_reward_v3_t2; M7l classifies it as a replay-verified training event, not a learned result).
Its only permitted use (user authorization, 2026-09-25) is to supply START STATES: an explicit native action-prefix
replay after a normal, non-consuming tick-0 reset. Its actions are never supervised targets, its policy weights are
never transferred, and the user's crossing fixtures and TAS are never inputs of any kind.

This module owns
  * the registered anchor record and its integrity checks (digest pinned here);
  * the cut semantics: a cut tau (1 <= tau <= MAX_CUT) replays anchor rows 0..tau-1, i.e. the actions that consumed
    native ticks 0..tau-1; the policy's first action is the one for input tick tau. The horizon counts every tick from
    the reset, so the policy phase has at most HORIZON - tau steps; prefix steps earn no reward and never enter a PPO
    rollout (they run inside the worker between two vector steps);
  * the backward schedule (pointer, window, blocks of anchored outcomes, completion) with its own seeded generator
    (never the global random module, never native RNG);
  * the per-episode sweep outcome and its success test;
  * the registered feasibility plan (F1-F5): cuts, episode counts, seeds, thresholds and classification rules.

Target identity comes from the read-only M7f diagnostic (SSB64_RL_TARGET_DIAG=1; gameplay-neutral). A break at
consumed tick b is the first step reply (the step that consumed tick b) whose target table shows the target broken.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import m7h_curriculum as mc

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACT_ID = "btt_curriculum_anchor_sweep_v1"
ANCHOR_SCHEMA = "m7m_anchor_v1"
OBS_TABLE_SCHEMA = "m7m_anchor_observations_v1"
OUTCOME_SCHEMA = "m7m_sweep_outcome_v1"

ANCHOR_ID = "m7l_t2_s1_sweep_49414363"
ANCHOR_FILE = REPO_ROOT / "docs" / "rl_sweep_consolidation_m7m_anchor.json"
OBS_TABLE_FILE = REPO_ROOT / "docs" / "rl_sweep_consolidation_m7m_anchor_observations.json"
ANCHOR_SOURCE_RUN = "m7l_t2_s1"
ANCHOR_EPISODE_ID = "episode_20260925T190612Z_49414363"
ANCHOR_NATIVE_DIGEST = "8ccf81f247571f2c3219f1b64efaa107eeedfb1cacebb2d4b7c26218699163a5"
ANCHOR_ROWS = 3600
ANCHOR_SOURCE_REWARD = "btt_reward_v3_t2"

# native target identity (M7f table; docs/rl_target2_m7l_decision_rule.json)
RIGHT_IDS: Tuple[int, ...] = (0, 2, 3, 4, 5, 7, 9)
STATIC_RIGHT_IDS: Tuple[int, ...] = (0, 3, 4, 5, 7, 9)
LEFT_IDS: Tuple[int, ...] = (1, 6, 8)
MOVING_TARGET_ID = 2
TARGETS_TOTAL = 10
# the anchor's right-target breaks, {native id: consumed tick} (M7l replay _replays/training_sweep_s1, exact)
ANCHOR_RIGHT_BREAKS: Dict[int, int] = {9: 41, 0: 119, 4: 165, 5: 580, 3: 800, 2: 837, 7: 1030}

HORIZON = 3600
DEADLINE_CONSUMED_TICK = 2699        # R: all seven right targets broken at consumed ticks <= 2699 (M7l rule)

# the registered schedule
MIN_CUT = 1
MAX_CUT = 1020
START_POINTER = 1020
WINDOW = 120
BLOCK = 10
BLOCK_SUCCESSES = 5
TICK0_PROBABILITY_E = 0.5
TICK0_PROBABILITY_K = 1.0

# start kinds recorded by the parent (the worker's recorder label reuses the M7h prefix-boundary label and kinds)
START_TICK0 = mc.START_TICK0                          # "tick0"
START_TICK0_INITIAL = mc.START_TICK0_INITIAL          # "tick0_initial"
START_TICK0_COMPLETE = "tick0_schedule_complete"      # the anchored half after the final window passed
START_ANCHOR = mc.START_PREFIX                        # "archive_prefix": rows [0, tau) are prefix rows
START_TICK0_AFTER_FAILURE = mc.START_TICK0_AFTER_FAILURE

REGISTERED_TABLE_KEYS = ("contract", "anchor", "tick0_probability", "start_pointer", "window", "block",
                         "block_successes", "deadline_consumed_tick", "max_cut", "observation_table_sha256")


class AnchorError(RuntimeError):
    """A violated M7m invariant (never silently tolerated)."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(data: Any) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


# -- the registered anchor ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Anchor:
    anchor_id: str
    actions: bytes                       # Track 1 indices, one per row, row i consumed tick i
    native_digest: str
    right_breaks: Dict[int, int]
    record: Dict[str, Any] = field(repr=False, compare=False, default_factory=dict)

    def prefix(self, tau: int) -> bytes:
        check_cut(tau)
        return self.actions[:tau]

    def prefix_digest(self, tau: int) -> str:
        return mc.prefix_digest(self.prefix(tau))


def check_cut(tau: int) -> int:
    t = int(tau)
    if not MIN_CUT <= t <= MAX_CUT:
        raise AnchorError(f"cut {tau} outside {MIN_CUT}..{MAX_CUT}")
    return t


def anchor_from_record(doc: Mapping[str, Any]) -> Anchor:
    if doc.get("schema") != ANCHOR_SCHEMA or doc.get("anchor_id") != ANCHOR_ID:
        raise AnchorError(f"not the registered anchor: {doc.get('schema')} / {doc.get('anchor_id')}")
    traj = doc["trajectory"]
    actions = bytes.fromhex(traj["track1_actions_hex"])
    if len(actions) != ANCHOR_ROWS or int(traj["rows"]) != ANCHOR_ROWS:
        raise AnchorError(f"anchor rows {len(actions)} / {traj['rows']} != {ANCHOR_ROWS}")
    if any(a >= mc.TRACK1_ACTIONS for a in actions):
        raise AnchorError("anchor holds a byte that is not a Track 1 index")
    digest = mc.prefix_digest(actions)
    if digest != ANCHOR_NATIVE_DIGEST or traj["native_action_digest"] != ANCHOR_NATIVE_DIGEST:
        raise AnchorError(f"anchor digest {digest[:16]} / {str(traj['native_action_digest'])[:16]} != the pinned "
                          f"{ANCHOR_NATIVE_DIGEST[:16]}")
    if sha256_bytes(actions) != traj["track1_actions_sha256"]:
        raise AnchorError("anchor action bytes do not match their recorded sha256")
    breaks = {int(k): int(v) for k, v in traj["right_breaks"].items()}
    if breaks != ANCHOR_RIGHT_BREAKS:
        raise AnchorError(f"anchor right breaks {breaks} != the registered {ANCHOR_RIGHT_BREAKS}")
    return Anchor(ANCHOR_ID, actions, digest, breaks, dict(doc))


def load_anchor(path: Path = ANCHOR_FILE) -> Anchor:
    return anchor_from_record(json.loads(Path(path).read_text(encoding="utf-8")))


def standing_right(tau: int, breaks: Mapping[int, int] = ANCHOR_RIGHT_BREAKS) -> Tuple[int, ...]:
    """Right targets still standing when the policy takes over at input tick tau (a break at consumed tick b happened
    inside the prefix iff b <= tau - 1)."""
    return tuple(i for i in RIGHT_IDS if int(breaks[i]) >= int(tau))


def broken_mask_at(tau: int, breaks: Mapping[int, int] = ANCHOR_RIGHT_BREAKS) -> int:
    """Native broken mask after prefix row tau-1 (every anchor break is a right target; the anchor broke no other)."""
    m = 0
    for i, b in breaks.items():
        if int(b) <= int(tau) - 1:
            m |= 1 << int(i)
    return m


# -- the anchor observation table (written by F1 from identical fresh-process replays) -----------------------------


def load_observation_table(expected_sha256: str, path: Path = OBS_TABLE_FILE) -> List[Dict[str, Any]]:
    """observations[tau - 1] = the observation after prefix row tau - 1 (the policy's first observation at cut tau)."""
    data = Path(path).read_bytes()
    if sha256_bytes(data) != expected_sha256:
        raise AnchorError(f"{Path(path).name}: sha256 {sha256_bytes(data)[:16]} != registered {expected_sha256[:16]}")
    doc = json.loads(data)
    if doc.get("schema") != OBS_TABLE_SCHEMA or doc.get("anchor_id") != ANCHOR_ID \
            or doc.get("native_action_digest") != ANCHOR_NATIVE_DIGEST:
        raise AnchorError("observation table of another anchor or schema")
    obs = doc["observations_after_row"]
    masks = doc["broken_masks_after_row"]
    if len(obs) != MAX_CUT or len(masks) != MAX_CUT:
        raise AnchorError(f"observation table covers {len(obs)} / {len(masks)} rows, not {MAX_CUT}")
    for tau in range(MIN_CUT, MAX_CUT + 1):
        if int(masks[tau - 1]) != broken_mask_at(tau):
            raise AnchorError(f"table mask after row {tau - 1} != the registered breaks")
    return [dict(o, broken_mask=int(m)) for o, m in zip(obs, masks)]


def observation_table_doc(observations: Sequence[Mapping[str, Any]], masks: Sequence[int],
                          replays: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    return {"schema": OBS_TABLE_SCHEMA, "anchor_id": ANCHOR_ID, "native_action_digest": ANCHOR_NATIVE_DIGEST,
            "rows": MAX_CUT, "fields": list(mc.OBSERVATION_FIELDS),
            "note": "observations_after_row[i] = native observation after anchor row i (= the first policy observation "
                    "at cut tau = i + 1); broken_masks_after_row[i] = the M7f broken mask in that step reply; produced by "
                    "F1 and identical (every field except host_frame) across the listed fresh-process replays",
            "replays": [dict(r) for r in replays],
            "observations_after_row": [dict(o) for o in observations], "broken_masks_after_row": [int(m) for m in masks]}


# -- the backward schedule ---------------------------------------------------------------------------------------


def windows() -> List[Tuple[int, int, int]]:
    """[(pointer, lo, hi)]: pointer_k = START_POINTER - k * WINDOW while >= MIN_CUT; window [max(1, pointer - 119),
    pointer]. The last window is clipped at 1."""
    out = []
    p = START_POINTER
    while p >= MIN_CUT:
        out.append((p, max(MIN_CUT, p - WINDOW + 1), p))
        p -= WINDOW
    return out


WINDOWS: Tuple[Tuple[int, int, int], ...] = tuple(windows())


@dataclass
class Outcome:
    """What the parent learns about one finished training episode (from the worker's info)."""

    kind: str
    tau: int
    window_index: Optional[int]
    success: bool
    end_reason: Optional[str]
    counted_end: bool                    # False for lifecycle failures / aborted episodes (never counted)


class AnchorSchedule:
    """Draws the start of every automatically reset episode and moves the pointer back after passing blocks.

    Selection (after an automatic reset only; initial resets are tick-0 starts):
      u1 < tick0_probability            -> tick0
      else, schedule complete            -> tick0_schedule_complete (no further draw)
      else                               -> anchor at tau = lo + floor(u2 * (hi - lo + 1)) in the current window
    Blocks: anchored outcomes whose start window is the current window are counted in parent ingestion order; after
    BLOCK counted outcomes the block passes with >= BLOCK_SUCCESSES successes -> the pointer moves to the next
    (earlier) window, or the schedule completes after the last window; a failed block starts a new block at the same
    window. Outcomes of an earlier window (still running when the pointer moved) are logged as stale, never counted.
    """

    def __init__(self, run_seed: int, *, tick0_probability: float):
        if float(tick0_probability) not in (TICK0_PROBABILITY_E, TICK0_PROBABILITY_K):
            raise AnchorError(f"tick0_probability {tick0_probability} is not registered")
        material = hashlib.sha256(f"{CONTRACT_ID}|{int(run_seed)}".encode("ascii")).digest()
        self.rng = random.Random(int.from_bytes(material[:8], "big"))
        self.p0 = float(tick0_probability)
        self.k = 0
        self.complete = False
        self.block_n = 0
        self.block_s = 0
        self.blocks: List[Dict[str, Any]] = []
        self.draws = 0
        self.counts: Dict[str, int] = {"counted": 0, "stale": 0, "excluded": 0, "successes_counted": 0}

    @property
    def window(self) -> Optional[Tuple[int, int, int]]:
        return None if self.complete else WINDOWS[self.k]

    def draw(self) -> Tuple[str, int, Optional[int], Dict[str, float]]:
        u1 = self.rng.random()
        self.draws += 1
        if u1 < self.p0:
            return START_TICK0, 0, None, {"u1": u1}
        if self.complete:
            return START_TICK0_COMPLETE, 0, None, {"u1": u1}
        u2 = self.rng.random()
        self.draws += 1
        _p, lo, hi = WINDOWS[self.k]
        tau = lo + int(math.floor(u2 * (hi - lo + 1)))
        return START_ANCHOR, min(hi, tau), self.k, {"u1": u1, "u2": u2}

    def ingest(self, o: Outcome) -> Optional[Dict[str, Any]]:
        """One finished anchored episode. Returns the event (counted / stale / excluded, plus a block record)."""
        if o.kind != START_ANCHOR:
            return None
        if not o.counted_end:
            self.counts["excluded"] += 1
            return {"event": "excluded", "window_index": o.window_index, "tau": o.tau, "end_reason": o.end_reason}
        if self.complete or o.window_index != self.k:
            self.counts["stale"] += 1
            return {"event": "stale", "window_index": o.window_index, "current": None if self.complete else self.k,
                    "tau": o.tau, "success": o.success}
        self.counts["counted"] += 1
        self.counts["successes_counted"] += int(bool(o.success))
        self.block_n += 1
        self.block_s += int(bool(o.success))
        ev: Dict[str, Any] = {"event": "counted", "window_index": self.k, "tau": o.tau, "success": bool(o.success),
                              "block_n": self.block_n, "block_s": self.block_s}
        if self.block_n == BLOCK:
            passed = self.block_s >= BLOCK_SUCCESSES
            p, lo, hi = WINDOWS[self.k]
            rec = {"block": len(self.blocks), "window_index": self.k, "pointer": p, "window": [lo, hi],
                   "successes": self.block_s, "n": self.block_n, "passed": passed}
            self.blocks.append(rec)
            self.block_n = self.block_s = 0
            if passed:
                self.k += 1
                if self.k >= len(WINDOWS):
                    self.complete = True
                    self.k = len(WINDOWS) - 1
            rec["next_window_index"] = None if self.complete else self.k
            rec["complete"] = self.complete
            ev["block"] = rec
        return ev

    def pointer(self) -> Optional[int]:
        return None if self.complete else WINDOWS[self.k][0]

    def state_json(self) -> Dict[str, Any]:
        version, internal, gauss = self.rng.getstate()
        return {"contract": CONTRACT_ID, "p0": self.p0, "k": self.k, "pointer": self.pointer(),
                "complete": self.complete, "block_n": self.block_n, "block_s": self.block_s, "blocks": list(self.blocks),
                "draws": self.draws, "counts": dict(self.counts),
                "rng": {"version": version, "internal": list(internal), "gauss_next": gauss}}


def min_pointer_reached(state: Mapping[str, Any]) -> int:
    """The earliest pointer whose window was reached (0 when the schedule completed)."""
    if state.get("complete"):
        return 0
    return int(WINDOWS[int(state["k"])][0])


# -- the per-episode sweep outcome ---------------------------------------------------------------------------------


def sweep_outcome(*, tau: int, first_break_ticks: Mapping[int, int], end_reason: Optional[str],
                  policy_steps: int) -> Dict[str, Any]:
    """Facts of one episode from its first-break table {native id: consumed tick} over ALL rows (prefix + policy).

    success = every right target broken, the last one at consumed tick <= DEADLINE_CONSUMED_TICK. For an anchored start
    the right targets broken in the prefix (tick <= tau - 1) are already broken, so success means the policy broke every
    right target still standing at tau by the deadline. For a tick-0 start (tau = 0) success is the M7l fact R."""
    fb = {int(k): int(v) for k, v in first_break_ticks.items()}
    tau = int(tau)
    standing = [i for i in RIGHT_IDS if i not in fb or fb[i] >= tau]
    policy_right = {i: fb[i] for i in RIGHT_IDS if i in fb and fb[i] >= tau}
    seven = all(i in fb for i in RIGHT_IDS)
    sweep_tick = max(fb[i] for i in RIGHT_IDS) if seven else None
    success = seven and sweep_tick <= DEADLINE_CONSUMED_TICK
    t2 = fb.get(MOVING_TARGET_ID)
    return {"schema": OUTCOME_SCHEMA, "tau": tau, "standing_right": standing,
            "policy_right_breaks": {str(k): v for k, v in sorted(policy_right.items())},
            "first_break_ticks": {str(k): v for k, v in sorted(fb.items())},
            "seven_right": seven, "sweep_tick": sweep_tick, "success": bool(success),
            "t2_policy": t2 is not None and t2 >= tau, "t2_tick": t2,
            "left_ids": sorted(i for i in fb if i in LEFT_IDS), "fall": end_reason == mc.END_FALL,
            "end_reason": end_reason, "policy_steps": int(policy_steps)}


# -- the registered feasibility plan (F1-F5) --------------------------------------------------------------------


F1_REPLAYS = 3
F3_LANDMARK_CUTS: Tuple[int, ...] = (42, 120, 166, 581, 801, 838, 1020)   # one tick after each break, and MAX_CUT
F3_RANDOM_CUT_COUNT = 50
F3_RANDOM_SEED_MATERIAL = "m7m_f3_random_cuts_v1"
F3_FULL_CUTS: Tuple[int, ...] = (42, 838, 1020)     # prefix, then the anchor's own remaining rows to the horizon

F4_SEEDS: Tuple[int, ...] = (0, 1, 2)
F4_MAX_WINDOWS = 3                                  # W0 [901,1020], W1 [781,900], W2 [661,780]; never more
F4_CUT_OFFSETS: Tuple[int, ...] = (0, 24, 48, 72, 96, 119)
F4_EPISODES_PER_CUT = 5                             # 6 cuts x 5 = 30 per window per seed
F4_BLOCKED_MAX = 2                                  # <= 2 / 30 (< 10 %)       -> blocked at this window
F4_SATURATED_MIN = 28                               # >= 28 / 30 (> 90 %)      -> test the next earlier window
F4_SEEDS_REQUIRED = 2                               # F4 passes when >= 2 of 3 seeds are not blocked

F5_CUTS: Tuple[int, ...] = (801, 810, 819, 828, 837)
F5_EPISODES_PER_CUT = 10                            # 50 per seed, 150 in total; never extended
F5_MIN_GROUP_POOLED = 10                            # fewer target-2 (or no-target-2) episodes pooled -> inconclusive
F5_MIN_GROUP_SEED = 5                               # per-seed difference reported only with >= 5 in each group
F5_SE_MULTIPLIER = 2.0


def f3_random_cuts() -> List[int]:
    material = hashlib.sha256(F3_RANDOM_SEED_MATERIAL.encode("ascii")).digest()
    rng = random.Random(int.from_bytes(material[:8], "big"))
    pool = [t for t in range(MIN_CUT, MAX_CUT + 1) if t not in F3_LANDMARK_CUTS]
    return sorted(rng.sample(pool, F3_RANDOM_CUT_COUNT))


def f4_window_cuts(window_index: int) -> List[int]:
    if not 0 <= int(window_index) < F4_MAX_WINDOWS:
        raise AnchorError(f"F4 window {window_index} outside the registered 0..{F4_MAX_WINDOWS - 1}")
    _p, lo, hi = WINDOWS[int(window_index)]
    cuts = [lo + o for o in F4_CUT_OFFSETS]
    if cuts[-1] != hi:
        raise AnchorError("F4 offsets do not end at the window's upper bound")
    return cuts


def episode_seed(tag: str, seed: int, tau: int, k: int) -> int:
    """The per-episode Python/NumPy/PyTorch seed of a feasibility episode (policy sampling only; never native)."""
    return int(hashlib.sha256(f"m7m_{tag}|s{int(seed)}|{int(tau)}|{int(k)}".encode("ascii")).hexdigest()[:8], 16)


def f4_classify_window(successes: int, n: int) -> str:
    if n != len(F4_CUT_OFFSETS) * F4_EPISODES_PER_CUT:
        raise AnchorError(f"F4 window with {n} episodes, registered {len(F4_CUT_OFFSETS) * F4_EPISODES_PER_CUT}")
    if successes <= F4_BLOCKED_MAX:
        return "blocked"
    if successes >= F4_SATURATED_MIN:
        return "saturated"
    return "foothold"


def f4_seed_status(window_results: Sequence[Tuple[int, int]]) -> Dict[str, Any]:
    """window_results[i] = (successes, n) of window W_i, evaluated in order. The procedure stops at the first window
    that is not saturated, or after F4_MAX_WINDOWS windows."""
    classes = []
    for i, (s, n) in enumerate(window_results):
        c = f4_classify_window(s, n)
        classes.append(c)
        if c != "saturated":
            if i != len(window_results) - 1:
                raise AnchorError("F4 evaluated a window after a non-saturated one")
            return {"status": c, "window_index": i, "classes": classes, "passes": c == "foothold"}
    if len(window_results) != F4_MAX_WINDOWS:
        raise AnchorError(f"F4 stopped after {len(window_results)} saturated windows (registered {F4_MAX_WINDOWS})")
    return {"status": "saturated_through_max_window", "window_index": F4_MAX_WINDOWS - 1, "classes": classes,
            "passes": True}


def f4_next_window(window_results: Sequence[Tuple[int, int]]) -> Optional[int]:
    """The next window to evaluate for one seed, or None when its procedure is finished."""
    if not window_results:
        return 0
    last = f4_classify_window(*window_results[-1])
    if last != "saturated" or len(window_results) >= F4_MAX_WINDOWS:
        return None
    return len(window_results)


def f5_diagnostic(groups: Mapping[str, Sequence[float]], *, min_group: int) -> Dict[str, Any]:
    """Mean policy-phase btt_reward_v2 return of episodes with vs without a target-2 break (diagnostic only)."""
    a, b = list(groups.get("t2") or []), list(groups.get("no_t2") or [])

    def stats(x: List[float]) -> Dict[str, Any]:
        if not x:
            return {"n": 0, "mean": None, "sd": None}
        m = sum(x) / len(x)
        sd = math.sqrt(sum((v - m) ** 2 for v in x) / (len(x) - 1)) if len(x) > 1 else None
        return {"n": len(x), "mean": round(m, 6), "sd": None if sd is None else round(sd, 6)}

    out: Dict[str, Any] = {"t2": stats(a), "no_t2": stats(b), "min_group": int(min_group)}
    if len(a) < min_group or len(b) < min_group:
        out.update(delta=None, se=None, classification="inconclusive_insufficient_samples")
        return out
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    va = sum((v - ma) ** 2 for v in a) / (len(a) - 1)
    vb = sum((v - mb) ** 2 for v in b) / (len(b) - 1)
    d, se = ma - mb, math.sqrt(va / len(a) + vb / len(b))
    if d - F5_SE_MULTIPLIER * se > 0:
        cls = "positive"
    elif d + F5_SE_MULTIPLIER * se < 0:
        cls = "negative"
    else:
        cls = "inconclusive_within_2se"
    out.update(delta=round(d, 6), se=round(se, 6), classification=cls)
    return out


def registered_plan() -> Dict[str, Any]:
    """The feasibility plan exactly as this module executes it (written to docs before any check runs)."""
    return {
        "anchor": {"anchor_id": ANCHOR_ID, "native_action_digest": ANCHOR_NATIVE_DIGEST, "max_cut": MAX_CUT},
        "cut_semantics": ("cut tau (1..1020): after the ordinary non-consuming tick-0 reset, anchor rows 0..tau-1 are "
                          "submitted one per native tick (consumed ticks 0..tau-1); the policy's first action is for "
                          "input tick tau; the horizon counts from the reset, so at most 3600 - tau policy steps; prefix "
                          "breaks earn nothing (reward reference rebased on the post-prefix observation)"),
        "success": ("all seven right targets {0,2,3,4,5,7,9} broken, the last at consumed tick <= 2699 (for a cut, the "
                    "standing right targets broken by the policy; a later fall does not undo it)"),
        "F1": {"replays": F1_REPLAYS, "what": "full 3,600-row anchor replay from tick 0, each in a fresh process; "
               "digest, consumed ticks 0..3599, break table, horizon end; observation table rows 1..1020 identical "
               "across replays (every field except host_frame)"},
        "F2": {"what": "the artifact's native rows map one-to-one onto Track 1 indices; re-encoding reproduces the "
               "recorded native action digest; equals the registered action bytes"},
        "F3": {"landmark_cuts": list(F3_LANDMARK_CUTS), "random_cuts": f3_random_cuts(),
               "random_cut_generator": f"random.Random(sha256('{F3_RANDOM_SEED_MATERIAL}')[:8]).sample(1..1020 minus "
                                       f"landmarks, {F3_RANDOM_CUT_COUNT})",
               "full_cuts": list(F3_FULL_CUTS),
               "what": "the M7m training worker (in-process, fresh game process per cut): run_prefix_phase delivers o_tau "
                       "equal to the F1 table (every field except host_frame) with the registered broken mask; for the "
                       "full cuts the anchor's remaining rows run through the worker's normal step() to the horizon: "
                       "3600 - tau policy steps, policy-only return (prefix breaks earn nothing), full-row digest equal "
                       "to the anchor, the episode row valid under the m7d validator"},
        "harness_validation": ("per warm start, a deterministic tick-0 harness episode reproduces the Phase K final "
                               "deterministic evaluation digest and return"),
        "F4": {"seeds": list(F4_SEEDS), "windows": [list(WINDOWS[i]) for i in range(F4_MAX_WINDOWS)],
               "cuts_by_window": {f"W{i}": f4_window_cuts(i) for i in range(F4_MAX_WINDOWS)},
               "episodes_per_cut": F4_EPISODES_PER_CUT, "episodes_per_window": len(F4_CUT_OFFSETS) * F4_EPISODES_PER_CUT,
               "max_episodes_per_seed": F4_MAX_WINDOWS * len(F4_CUT_OFFSETS) * F4_EPISODES_PER_CUT,
               "max_episodes_total": len(F4_SEEDS) * F4_MAX_WINDOWS * len(F4_CUT_OFFSETS) * F4_EPISODES_PER_CUT,
               "policy": "frozen warm start, stochastic actions, VecNormalize statistics frozen (evaluator semantics)",
               "episode_end": "success, native clear / failure, or the step that consumed tick 2699 (whichever first)",
               "episode_seed": "int(sha256('m7m_f4|s<seed>|<tau>|<k>')[:8], 16) (policy sampling only)",
               "classes": {"blocked": f"<= {F4_BLOCKED_MAX}/30", "foothold": f"{F4_BLOCKED_MAX + 1}..{F4_SATURATED_MIN - 1}/30",
                           "saturated": f">= {F4_SATURATED_MIN}/30"},
               "procedure": ("per seed: evaluate W0; while the last window is saturated and fewer than 3 windows were "
                             "evaluated, evaluate the next earlier window. Seed status = the class of the first "
                             "non-saturated window (foothold passes, blocked fails) or saturated_through_max_window "
                             "(passes; the schedule would move past those windows in one block each)"),
               "pass": f">= {F4_SEEDS_REQUIRED} of {len(F4_SEEDS)} seeds pass",
               "schedule_unchanged": "F4 never changes the registered schedule (every run starts at pointer 1020)"},
        "F5": {"role": "diagnostic only: never gates GO / NO-GO; not proof that reward v2 can or cannot consolidate "
                       "the route",
               "seeds": list(F4_SEEDS), "cuts": list(F5_CUTS), "episodes_per_cut": F5_EPISODES_PER_CUT,
               "episodes_per_seed": len(F5_CUTS) * F5_EPISODES_PER_CUT,
               "episodes_total": len(F4_SEEDS) * len(F5_CUTS) * F5_EPISODES_PER_CUT,
               "episode_end": "natural end (native clear / failure / horizon)",
               "episode_seed": "int(sha256('m7m_f5|s<seed>|<tau>|<k>')[:8], 16)",
               "measure": "policy-phase btt_reward_v2 return (rebased at o_tau) of episodes where the policy broke "
                          "target 2 (any tick) vs episodes where it did not; fall rates of both groups",
               "classification": (f"pooled over seeds: inconclusive_insufficient_samples if either group < "
                                  f"{F5_MIN_GROUP_POOLED}; positive if delta - 2 SE > 0; negative if delta + 2 SE < 0; "
                                  f"else inconclusive_within_2se (Welch SE). Per seed only with >= {F5_MIN_GROUP_SEED} "
                                  "in each group. Rare target-2 breaks are reported as they are; sampling is never "
                                  "extended and reward v2 is never changed"),
               "confound": "groups differ in cut composition; per-cut counts are reported"},
        "GO": ("F1, F2, F3, the harness validation and F4 pass, with no integrity, provenance, resource or process stop. "
               "F5 is reported and never gates."),
        "stops": ("a failed launch gate (after 5 readings 60 s apart), available commit < 3 GiB during a check, an "
                  "integrity or provenance mismatch, or a leftover BattleShip process stops the checks; every episode "
                  "already written is preserved; nothing is relaunched without the user"),
        "budget": {"episodes_max": {"F1": F1_REPLAYS, "F3": len(F3_LANDMARK_CUTS) + F3_RANDOM_CUT_COUNT,
                                    "harness_validation": len(F4_SEEDS),
                                    "F4": len(F4_SEEDS) * F4_MAX_WINDOWS * len(F4_CUT_OFFSETS) * F4_EPISODES_PER_CUT,
                                    "F5": len(F4_SEEDS) * len(F5_CUTS) * F5_EPISODES_PER_CUT},
                   "verification_replays_max": 150},
    }


# -- the [anchor_curriculum] profile table -------------------------------------------------------------------------


def registered_table(*, tick0_probability: float, observation_table_sha256: str) -> Dict[str, Any]:
    return {"contract": CONTRACT_ID, "anchor": ANCHOR_ID, "tick0_probability": float(tick0_probability),
            "start_pointer": START_POINTER, "window": WINDOW, "block": BLOCK, "block_successes": BLOCK_SUCCESSES,
            "deadline_consumed_tick": DEADLINE_CONSUMED_TICK, "max_cut": MAX_CUT,
            "observation_table_sha256": str(observation_table_sha256)}


def check_table(settings: Mapping[str, Any]) -> Dict[str, Any]:
    s = dict(settings)
    if tuple(sorted(s)) != tuple(sorted(REGISTERED_TABLE_KEYS)):
        raise AnchorError(f"[anchor_curriculum] keys {sorted(s)} != {sorted(REGISTERED_TABLE_KEYS)}")
    want = registered_table(tick0_probability=s.get("tick0_probability"),
                            observation_table_sha256=s.get("observation_table_sha256"))
    if s != want or float(s["tick0_probability"]) not in (TICK0_PROBABILITY_E, TICK0_PROBABILITY_K):
        raise AnchorError(f"[anchor_curriculum] {s} differs from the registered M7m settings")
    sha = str(s["observation_table_sha256"])
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise AnchorError("observation_table_sha256 must be 64 lowercase hex digits")
    return s


def self_test() -> int:
    ok = True

    def expect(cond: bool, name: str) -> None:
        nonlocal ok
        if not cond:
            ok = False
            print("FAIL", name)

    w = windows()
    expect(len(w) == 9 and w[0] == (1020, 901, 1020) and w[1] == (900, 781, 900) and w[-1] == (60, 1, 60),
           f"windows {w}")
    expect(standing_right(1020) == (7,) and standing_right(838) == (7,) and standing_right(837) == (2, 7),
           "standing right at 1020 / 838 / 837")
    expect(standing_right(42) == (0, 2, 3, 4, 5, 7) and standing_right(41) == RIGHT_IDS, "standing right at 42 / 41")
    expect(broken_mask_at(42) == 1 << 9 and broken_mask_at(1) == 0, "masks")
    o = sweep_outcome(tau=901, first_break_ticks={**{k: v for k, v in ANCHOR_RIGHT_BREAKS.items() if v < 901}, 7: 2699},
                      end_reason="fall", policy_steps=10)
    expect(o["success"] and o["standing_right"] == [7] and o["fall"], "success at the deadline, fall later")
    o = sweep_outcome(tau=901, first_break_ticks={**{k: v for k, v in ANCHOR_RIGHT_BREAKS.items() if v < 901}, 7: 2700},
                      end_reason="horizon", policy_steps=10)
    expect(not o["success"] and o["seven_right"], "one tick late")
    s = AnchorSchedule(5, tick0_probability=TICK0_PROBABILITY_E)
    for i in range(10):
        s.ingest(Outcome(START_ANCHOR, 950, 0, i < 5, "horizon", True))
    expect(s.k == 1 and len(s.blocks) == 1 and s.blocks[0]["passed"], "5/10 moves the pointer")
    ev = s.ingest(Outcome(START_ANCHOR, 950, 0, True, "horizon", True))
    expect(ev["event"] == "stale" and s.block_n == 0, "stale outcome")
    ev = s.ingest(Outcome(START_ANCHOR, 850, 1, True, "lifecycle_failure", False))
    expect(ev["event"] == "excluded" and s.block_n == 0, "excluded outcome")
    for i in range(10):
        s.ingest(Outcome(START_ANCHOR, 850, 1, i < 4, "horizon", True))
    expect(s.k == 1 and len(s.blocks) == 2 and not s.blocks[1]["passed"], "4/10 keeps the pointer")
    s2 = AnchorSchedule(5, tick0_probability=TICK0_PROBABILITY_E)
    for k in range(len(WINDOWS)):
        for i in range(10):
            s2.ingest(Outcome(START_ANCHOR, WINDOWS[k][2], k, True, "horizon", True))
    expect(s2.complete and min_pointer_reached(s2.state_json()) == 0 and s2.draw()[0] in (START_TICK0, START_TICK0_COMPLETE),
           "completion")
    s3 = AnchorSchedule(1, tick0_probability=TICK0_PROBABILITY_K)
    expect(all(s3.draw()[0] == START_TICK0 for _ in range(1000)), "K never anchors")
    s4 = AnchorSchedule(1, tick0_probability=TICK0_PROBABILITY_E)
    taus = [d[1] for d in (s4.draw() for _ in range(4000)) if d[0] == START_ANCHOR]
    expect(min(taus) == 901 and max(taus) == 1020 and 1700 < len(taus) < 2300, f"draw range {min(taus)}..{max(taus)}")
    expect(f4_window_cuts(0) == [901, 925, 949, 973, 997, 1020] and f4_window_cuts(2) == [661, 685, 709, 733, 757, 780],
           "F4 cuts")
    expect(f4_seed_status([(28, 30), (3, 30)])["status"] == "foothold" and
           f4_seed_status([(2, 30)])["status"] == "blocked" and
           f4_seed_status([(30, 30), (29, 30), (28, 30)])["passes"] and f4_next_window([(28, 30)]) == 1 and
           f4_next_window([(27, 30)]) is None and f4_next_window([(28, 30)] * 3) is None, "F4 procedure")
    d = f5_diagnostic({"t2": [1.0] * 4, "no_t2": [0.0] * 20}, min_group=10)
    expect(d["classification"] == "inconclusive_insufficient_samples", "F5 rare target 2")
    d = f5_diagnostic({"t2": [1.0, 1.1] * 6, "no_t2": [0.0, 0.1] * 6}, min_group=10)
    expect(d["classification"] == "positive", "F5 positive")
    rc = f3_random_cuts()
    expect(len(rc) == 50 and len(set(rc)) == 50 and not set(rc) & set(F3_LANDMARK_CUTS), "F3 cuts")
    print("m7m_anchor self-test", "ok" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(self_test())
