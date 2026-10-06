"""M9-g2: the registered constants of the second robustification gate (pure, standard library only).

Design: docs/rl_m9_g2_proposal_2026-10-04.md as decided in docs/rl_m9_g2_decisions_2026-10-05.md. Every number that the g2 rules, the controlled
frontier, the tape baseline, the envelope caps and the line budget read lives here, so the digests pin them all at once. The g1 constants that g2 keeps
unchanged (horizon, contracts, flags, lineages, curriculum constants, sticky p, landings, PPO, checkpoint cadence, memory caps) are READ from
rl/m9_contract (imported unchanged): g2 carries no private copy of a g1 value.

SCOPE: the first session (s1) of a resumable line; one set of keyed draws; progress measured as the sustained frontier depth D and the reliable reach R
under the registered rules; no claim of a tick-0 policy.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Tuple

import m9_contract as C

GATE = "m9_g2"
LINE_ID = "m9_g2_line"
CONTRACT_ID = "m9_g2_contract_v1"
LINE_CONTRACT_ID = "m9_g2_line_contract_v1"
FRONTIER_RULE_ID = "m9_g2_frontier_v1"
TAPE_RULE_ID = "m9_g2_tape_baseline_v1"
S1_RULE_ID = "m9_g2_s1_rule_v1"
LINE_RULE_ID = "m9_g2_line_rule_v1"
MILESTONE = C.MILESTONE
SCOPE = ("M9-g2-s1: backward-algorithm robustification under the controlled frontier rule m9_g2_frontier_v1 (PPO from prefix-replayed start states on the "
         "agent's own two verified rd4 clears, sticky actions p = 0.25, observation btt_policy_obs_v3_entities, reward btt_reward_v2, entropy coefficient 0.01); "
         "the first session of a resumable line; one set of keyed draws; progress measured as the sustained frontier depth D and the reliable reach R at landing "
         "states against a pinned tape baseline under the registered rules; no claim of a tick-0 policy")

TASK = C.TASK
TASK_ID = C.TASK_ID
HORIZON = C.HORIZON
LANDINGS: Tuple[int, ...] = C.LANDINGS
STICKY_P = C.STICKY_P
PPO: Dict[str, Any] = dict(C.PPO)                      # the M7n profile, ent_coef 0.01, a fresh policy (seed 0) in s1
ROLLOUT_SIZE = C.ROLLOUT_SIZE
CHECKPOINT_EVERY = C.CHECKPOINT_EVERY
SHARED_PREFIX = C.SHARED_PREFIX
TAPE_LINEAGE = C.TAPE_LINEAGE
TRUNK = C.TAPE_LINEAGE

# -- the controlled frontier (decision 1; proposal 2.2) --------------------------------------------------------------------------------
TAU0 = C.TAU0
STRIP = C.STRIP
TRIGGER_WINDOW = 20                      # counted strip outcomes per window
TRIGGER_CLEARS = 8                       # the trigger fires at the 8th clear of a window
TRIGGER_VOID_NONCLEARS = TRIGGER_WINDOW - TRIGGER_CLEARS + 1      # 13: the window is void at the 13th non-clear
TEST_EPISODES = 20                       # a strip test or a re-check: up to 20 sticky episodes from the frozen snapshot
TEST_PASS = 10                           # pass at the 10th clear
TEST_FAIL_NONCLEARS = TEST_EPISODES - TEST_PASS + 1              # 11: fail at the 11th non-clear
ATTEMPTS_PER_SESSION = 3                 # failed attempts at one pointer in one session: HELD
ATTEMPTS_PER_LINE = 6                    # failed attempts at one pointer over the line: STALLED (the line ends)
PROBE_SLOTS = 6                          # the preparing slots run the attempt; the four playing slots stay parked
PROBE_LIFECYCLE_LIMIT = C.LIFECYCLE_FAILURE_LIMIT

# -- the tape baseline (decision 4; proposal 5) ----------------------------------------------------------------------------------------
TAPE_KEYS: Dict[int, int] = {2128: 200, 1966: 40, 1694: 40, 1473: 40, 1369: 40, 1248: 40}
AUDIT_EPISODES = 20                      # sticky episodes per audited landing (keys k = 0..19 of the tape's family)
AUDIT_UNPERTURBED = 20
AUDIT_DETERMINISTIC = 1
TICK0_EPISODES = 20
BAR_MIN = C.GATE_MIN_CLEARS              # 10
BAR_MARGIN = C.TAPE_MARGIN               # 5
D_MIN_CLEARS = C.GATE_MIN_CLEARS         # D: >= 10 of 20 at the landing and every later audited landing

# -- the s1 rule and the line budget (decisions 6, 7; proposal 6.5, 7) ----------------------------------------------------------------
PASS_REACH = 1966                        # PASS iff R_1 <= 1,966
INCONCLUSIVE_DEPTH = 2128                # INCONCLUSIVE iff D_1 <= 2,128 (and not PASS)
LINE_BUDGET_DEPTH = 1966                 # END_BUDGET_1966: k = 3 and D_3 later than 1,966
LINE_BUDGET_SESSIONS = 3                 # N = 3
LINE_PROGRESS_FROM_SESSION = 4           # from session 4, D must gain a landing every two sessions
LINE_CAP_SESSIONS = 8
LINE_SUCCESS_DEPTH = 1473                # END_SUCCESS: D_k <= 1,473
INCOMPLETE_COUNTS_IF_TRAIN_FRACTION = 0.5
ROUTE_END = 2326

# -- the session envelope (decision 5; proposal 6.1) -----------------------------------------------------------------------------------
PHASES: Tuple[str, ...] = ("open", "p1", "p2", "t0", "train", "audit", "verify", "close")
WALL_CAPS_S: Dict[str, float] = {"open": 60.0, "p1": 240.0, "p2": 120.0, "t0": 900.0, "train": 4800.0, "audit": 1200.0, "verify": 600.0, "close": 300.0}
TICK_CAPS: Dict[str, int] = {"open": 0, "p1": 60_000, "p2": 60_000, "t0": 1_500_000, "train": 20_000_000, "audit": 3_000_000, "verify": 1_500_000, "close": 0}
TRANSITION_CAP = C.TRANSITION_CAP        # 3,072,000 policy transitions per session
GLOBAL_CAP_S = 8700.0                    # the 145-minute session hard cap
TRAIN_WALL_S = WALL_CAPS_S["train"]
WALL_CAP_GRACE_S = C.WALL_CAP_GRACE_S
POOL_SPAWN_S = 15.0
POOL_SPAWNS = 4                          # P2, T0, training, the close audit
P2_STARTS = C.P2_STARTS
SPLIT: Tuple[int, int] = (4, 6)          # fixed (decision 9): 4 playing + 6 preparing slots; no P3
N_SLOTS = C.N_SLOTS
VERIFY_THREADS = 8
VERIFY_LAUNCH_MARGIN_S = 120.0           # replay launches stop this long before the verification wall cap, so the replays in flight finish inside it (the g1 checkpoint evaluation's margin)
MEMORY_CAPS_MB: Dict[str, float] = dict(C.MEMORY_CAPS_MB)
MAX_BATTLESHIP_PROCESSES = C.MAX_BATTLESHIP_PROCESSES
LIFECYCLE_FAILURE_LIMIT = C.LIFECYCLE_FAILURE_LIMIT
ARTIFACT_SAMPLE_PER_MILLE = C.ARTIFACT_SAMPLE_PER_MILLE
FIRST_CLEARS_VERIFIED = 20
SESSION_SEED_BASE = 1000                 # the Python-side training seed of session k >= 2 is 1000 + k; s1 is the fresh policy's seed 0

# -- draw keys (Python-side sha256 uniforms; never the native RNG) ------------------------------------------------------------------
KEYS: Dict[str, str] = {
    "train_label": "m9|g2|train|<episode>", "sticky": "<label>|<tick>",
    "start": "m9|g2|start|<episode>|region|tau|lineage",
    "probe_label": "m9|g2|probe|<pointer>|<a>|<strip or landing>|<k>", "probe_start": "m9|g2|probe|<pointer>|<a>|strip|<k>|tau|lineage",
    "probe_action": "m9|g2|probeact|<pointer>|<a>|<part>|<k>|<tick>|<stick or button>",
    "reach_label": "m9|g2|reach|<landing>|<k>", "tick0_label": "m9|g2|tick0|<k>",
    "audit_action": "m9|g2|auditact|<sticky or unperturbed>|<landing>|<k>|<tick>|<stick or button>",
    "verify_pick": "m9|g2|verifypick|<pointer>|<a>|<part>", "artifact_sample": "m9|g2|artifact|<episode>",
    "p2": "m9|g1|p2|<k>|tau|word (as g1: an integrity check)",
}


def train_label(episode: int) -> str:
    return f"m9|g2|train|{int(episode)}"


def start_key(episode: int, what: str) -> str:
    return f"m9|g2|start|{int(episode)}|{what}"


def probe_label(pointer: int, attempt: int, part: Any, k: int) -> str:
    return f"m9|g2|probe|{int(pointer)}|{int(attempt)}|{part}|{int(k)}"


def probe_action_key(pointer: int, attempt: int, part: Any, k: int, tick: int) -> str:
    return f"m9|g2|probeact|{int(pointer)}|{int(attempt)}|{part}|{int(k)}|{int(tick)}"


def reach_label(landing: int, k: int) -> str:
    return f"m9|g2|reach|{int(landing)}|{int(k)}"


def tick0_label(k: int) -> str:
    return f"m9|g2|tick0|{int(k)}"


def audit_action_key(mode: str, landing: int, k: int, tick: int) -> str:
    if mode not in ("sticky", "unperturbed"):
        raise ValueError(f"unknown audit mode {mode!r}")
    return f"m9|g2|auditact|{mode}|{int(landing)}|{int(k)}|{int(tick)}"


def verify_pick_key(pointer: int, attempt: int, part: Any) -> str:
    return f"m9|g2|verifypick|{int(pointer)}|{int(attempt)}|{part}"


def artifact_sample_key(episode: int) -> str:
    return f"m9|g2|artifact|{int(episode)}"


def sticky_key(label: str, tick: int) -> str:
    return f"{label}|{int(tick)}"


def bar(p_hat: float) -> int:
    """B(landing) = max(10, ceil(20 p_hat) + 5) on exact rational arithmetic when p_hat is given as clears / keys (see tape.bar_from_counts)."""
    import math

    return max(BAR_MIN, int(math.ceil(AUDIT_EPISODES * float(p_hat) - 1e-12)) + BAR_MARGIN)


def bar_from_counts(clears: int, keys: int) -> int:
    """B from integer counts: ceil(20 * clears / keys) + 5, at least 10 (integer arithmetic, no rounding hazard)."""
    if keys <= 0:
        raise ValueError("a tape landing needs at least one key")
    c = (AUDIT_EPISODES * int(clears) + int(keys) - 1) // int(keys)
    return max(BAR_MIN, c + BAR_MARGIN)


def frontier_description() -> Dict[str, Any]:
    return {"rule": FRONTIER_RULE_ID, "tau0": TAU0, "strip": STRIP, "trigger": {"window": TRIGGER_WINDOW, "clears": TRIGGER_CLEARS, "void_nonclears": TRIGGER_VOID_NONCLEARS,
            "restarts": "at the session open, after every move, after every attempt at the pointer"},
            "test": {"episodes": TEST_EPISODES, "pass_clears": TEST_PASS, "fail_nonclears": TEST_FAIL_NONCLEARS, "curtailed": True, "snapshot": "frozen weights at the rollout boundary",
                     "sampling": "keyed inverse CDF", "sticky_p": STICKY_P},
            "recheck": "every registered landing >= pointer + 20, the trunk's own state, the same test, in parallel; the attempt fails at the first failing landing",
            "move": "pointer - 20 iff the strip test and every re-check pass; never forward", "attempts": {"per_session": ATTEMPTS_PER_SESSION, "per_line": ATTEMPTS_PER_LINE,
            "held": "no further attempt at the pointer in the session", "stalled": "training ends validly; the line ends"},
            "pause": "the four playing slots stay parked; the six preparing slots run the attempt; staged training starts are withdrawn and recorded",
            "keys": {k: KEYS[k] for k in ("probe_label", "probe_start", "probe_action", "sticky")}}


def tape_description() -> Dict[str, Any]:
    return {"rule": TAPE_RULE_ID, "keys": dict(TAPE_KEYS), "label": KEYS["reach_label"], "sticky_p": STICKY_P, "lineage": TAPE_LINEAGE, "measured": "once, in s1 (T0)",
            "verified": "every counted tape clear replayed exactly", "bar": "max(10, ceil(20 p_hat) + 5)", "audit_keys": f"k = 0..{AUDIT_EPISODES - 1} of the same family in every session"}


def line_contract_description() -> Dict[str, Any]:
    """The line's contract (fixed in s1; a resume refuses any change): observation, reward, action, PPO values, sticky p, curriculum constants, the frontier rule."""
    return {"contract": LINE_CONTRACT_ID, "task": dict(TASK), "horizon": HORIZON, "action": C.ACTION_CONTRACT, "observation": C.OBSERVATION_CONTRACT, "reward": C.REWARD_CONTRACT,
            "flags": {"train": C.FLAGS_TRAIN, "eval": C.FLAGS_EVAL, "verify": C.FLAGS_VERIFY}, "lineages": [dict(x) for x in C.LINEAGES], "shared_prefix": SHARED_PREFIX,
            "tape_lineage": TAPE_LINEAGE, "landings": list(LANDINGS), "sticky_p": STICKY_P,
            "curriculum": {"tau0": TAU0, "strip": STRIP, "near_window": C.NEAR_WINDOW, "region_weights": [list(x) for x in C.REGION_WEIGHTS], "min_words_after_start": C.MIN_WORDS_AFTER_START,
                           "stale_rule": "only strip starts drawn under the current pointer count"},
            "frontier": frontier_description(), "tape": tape_description(), "ppo": dict(PPO), "rollout_size": ROLLOUT_SIZE, "checkpoint_every": CHECKPOINT_EVERY,
            "split": list(SPLIT), "session_seed": f"{SESSION_SEED_BASE} + k for k >= 2; s1 fresh seed {PPO['seed']}", "transition_cap_per_session": TRANSITION_CAP}


def line_contract_digest() -> str:
    return hashlib.sha256(json.dumps(line_contract_description(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def description() -> Dict[str, Any]:
    return {"contract": CONTRACT_ID, "gate": GATE, "line": LINE_ID, "scope": SCOPE, "task": dict(TASK), "line_contract": line_contract_description(),
            "audit": {"episodes": AUDIT_EPISODES, "unperturbed": AUDIT_UNPERTURBED, "deterministic": AUDIT_DETERMINISTIC, "tick0": TICK0_EPISODES,
                      "landings": "every registered landing >= pointer + 20 plus the first landing below"},
            "rules": {"s1": {"id": S1_RULE_ID, "pass_reach": PASS_REACH, "inconclusive_depth": INCONCLUSIVE_DEPTH, "d_min_clears": D_MIN_CLEARS},
                      "line": {"id": LINE_RULE_ID, "budget_depth": LINE_BUDGET_DEPTH, "budget_sessions": LINE_BUDGET_SESSIONS, "progress_from_session": LINE_PROGRESS_FROM_SESSION,
                               "cap_sessions": LINE_CAP_SESSIONS, "success_depth": LINE_SUCCESS_DEPTH, "incomplete_counts_if_train_fraction": INCOMPLETE_COUNTS_IF_TRAIN_FRACTION}},
            "phases": list(PHASES), "wall_caps_s": dict(WALL_CAPS_S), "tick_caps": dict(TICK_CAPS), "transition_cap": TRANSITION_CAP, "global_cap_s": GLOBAL_CAP_S,
            "wall_cap_grace_s": WALL_CAP_GRACE_S, "pool_spawn_s": POOL_SPAWN_S, "pool_spawns": POOL_SPAWNS, "p2_starts": P2_STARTS, "split": list(SPLIT), "slots": N_SLOTS,
            "probe_slots": PROBE_SLOTS, "verify_threads": VERIFY_THREADS, "verify_launch_margin_s": VERIFY_LAUNCH_MARGIN_S, "memory_caps_mb": dict(MEMORY_CAPS_MB), "max_battleship_processes": MAX_BATTLESHIP_PROCESSES,
            "lifecycle_failure_limit": LIFECYCLE_FAILURE_LIMIT, "probe_lifecycle_limit": PROBE_LIFECYCLE_LIMIT, "artifact_sample_per_mille": ARTIFACT_SAMPLE_PER_MILLE,
            "first_clears_verified": FIRST_CLEARS_VERIFIED, "keys": dict(KEYS), "g1_contract_sha256": C.contract_digest()}


def contract_digest() -> str:
    return hashlib.sha256(json.dumps(description(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


if __name__ == "__main__":
    print(json.dumps({"contract": CONTRACT_ID, "digest": contract_digest(), "line_contract": LINE_CONTRACT_ID, "line_digest": line_contract_digest()}, indent=1))
