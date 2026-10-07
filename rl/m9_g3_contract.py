"""M9-g3: the registered constants of the third robustification gate (pure, standard library only).

Design: docs/rl_m9_g2_stop_review_2026-10-06.md (section 3) as decided in docs/rl_m9_g3_decisions_2026-10-06.md. g3 is a NEW LINE, not an amendment of
g2, with exactly ONE change against g2: the attempt bounds (3 failed attempts per pointer per session: HELD; 6 over the line: STALLED, the line ends)
are replaced by a spacing rule under which attempts REPLENISH with training progress. After f >= 1 consecutive failed attempts at the pointer since
the last move, the next attempt needs at least min(320, 20 x 2^(f-1)) counted strip outcomes at the pointer since the last failed attempt, and a
fresh trigger; a trigger inside the spacing is logged `deferred_trigger`, no attempt runs and the window restarts. There is no HELD and no STALLED
state; no attempt count can freeze the frontier or end the line (the line ends only on the progress milestones, the session cap or a suspension).

Everything else is READ from rl/m9_g2_contract (imported unchanged), which reads g1's values from rl/m9_contract: g3 carries no private copy of a g2
or g1 value. Keys move to the m9|g3|... family with one registered exception: the close audit's sticky labels keep g2-s1's `m9|g2|reach|<landing>|<k>`
family, so that the audit episodes stay paired (identical sticky draws) with the REUSED tape baseline (decision 7: g2-s1's pinned table, read by digest
and verified at the open together with the executable and asset pins; T0 is not re-measured).

SCOPE: the first session (s1) of a resumable line; a fresh policy (seed 0); one set of keyed draws; progress measured as the sustained frontier depth D
and the reliable reach R against the reused pinned tape baseline under the registered rules; no claim of a tick-0 policy.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Tuple

import m9_contract as C
import m9_g2_contract as G2

GATE = "m9_g3"
LINE_ID = "m9_g3_line"
CONTRACT_ID = "m9_g3_contract_v1"
LINE_CONTRACT_ID = "m9_g3_line_contract_v1"
FRONTIER_RULE_ID = "m9_g3_frontier_v1"
TAPE_RULE_ID = G2.TAPE_RULE_ID                    # the tape baseline procedure is g2's; the table itself is g2-s1's, reused by digest
S1_RULE_ID = "m9_g3_s1_rule_v1"
LINE_RULE_ID = "m9_g3_line_rule_v1"
MILESTONE = C.MILESTONE
SCOPE = ("M9-g3-s1: backward-algorithm robustification under the replenishing controlled frontier rule m9_g3_frontier_v1 (PPO from prefix-replayed start "
         "states on the agent's own two verified rd4 clears, sticky actions p = 0.25, observation btt_policy_obs_v3_entities, reward btt_reward_v2, entropy "
         "coefficient 0.01; the g2 trigger, frozen strip test and re-checks unchanged; attempts spaced by 20 x 2^(f-1) counted strip outcomes, cap 320, no HELD "
         "and no STALLED); the first session of a new resumable line (not an amendment of g2); a fresh policy (seed 0); one set of keyed draws; progress "
         "measured as the sustained frontier depth D and the reliable reach R at landing states against g2-s1's pinned tape baseline reused by digest, under "
         "the registered rules; no claim of a tick-0 policy")

# -- read from g2 / g1, unchanged ----------------------------------------------------------------------------------------------------------
TASK = C.TASK
TASK_ID = C.TASK_ID
HORIZON = C.HORIZON
LANDINGS: Tuple[int, ...] = C.LANDINGS
STICKY_P = C.STICKY_P
PPO: Dict[str, Any] = dict(G2.PPO)                 # the M7n profile, ent_coef 0.01, a fresh policy (seed 0) in s1
ROLLOUT_SIZE = G2.ROLLOUT_SIZE
CHECKPOINT_EVERY = G2.CHECKPOINT_EVERY
SHARED_PREFIX = G2.SHARED_PREFIX
TAPE_LINEAGE = G2.TAPE_LINEAGE
TRUNK = G2.TRUNK
TAU0 = G2.TAU0
STRIP = G2.STRIP
TRIGGER_WINDOW = G2.TRIGGER_WINDOW                 # 20
TRIGGER_CLEARS = G2.TRIGGER_CLEARS                 # the trigger fires at the 8th clear of a window
TRIGGER_VOID_NONCLEARS = G2.TRIGGER_VOID_NONCLEARS  # 13: the window is void at the 13th non-clear
TEST_EPISODES = G2.TEST_EPISODES                   # 20
TEST_PASS = G2.TEST_PASS                           # pass at the 10th clear
TEST_FAIL_NONCLEARS = G2.TEST_FAIL_NONCLEARS       # 11: fail at the 11th non-clear
PROBE_SLOTS = G2.PROBE_SLOTS                       # 6
PROBE_LIFECYCLE_LIMIT = G2.PROBE_LIFECYCLE_LIMIT
TAPE_KEYS: Dict[int, int] = dict(G2.TAPE_KEYS)     # the shape the reused table must have (200 at 2,128; 40 elsewhere)
AUDIT_EPISODES = G2.AUDIT_EPISODES
AUDIT_UNPERTURBED = G2.AUDIT_UNPERTURBED
AUDIT_DETERMINISTIC = G2.AUDIT_DETERMINISTIC
TICK0_EPISODES = G2.TICK0_EPISODES
BAR_MIN = G2.BAR_MIN
BAR_MARGIN = G2.BAR_MARGIN
D_MIN_CLEARS = G2.D_MIN_CLEARS
PASS_REACH = G2.PASS_REACH                         # PASS iff R_1 <= 1,966
INCONCLUSIVE_DEPTH = G2.INCONCLUSIVE_DEPTH         # INCONCLUSIVE iff D_1 <= 2,128
ROUTE_END = G2.ROUTE_END
INCOMPLETE_COUNTS_IF_TRAIN_FRACTION = G2.INCOMPLETE_COUNTS_IF_TRAIN_FRACTION
SPLIT: Tuple[int, int] = G2.SPLIT                  # fixed 4 + 6
N_SLOTS = G2.N_SLOTS
VERIFY_THREADS = G2.VERIFY_THREADS
VERIFY_LAUNCH_MARGIN_S = G2.VERIFY_LAUNCH_MARGIN_S
MEMORY_CAPS_MB: Dict[str, float] = dict(G2.MEMORY_CAPS_MB)
MAX_BATTLESHIP_PROCESSES = G2.MAX_BATTLESHIP_PROCESSES
LIFECYCLE_FAILURE_LIMIT = G2.LIFECYCLE_FAILURE_LIMIT
ARTIFACT_SAMPLE_PER_MILLE = G2.ARTIFACT_SAMPLE_PER_MILLE
FIRST_CLEARS_VERIFIED = G2.FIRST_CLEARS_VERIFIED
SESSION_SEED_BASE = G2.SESSION_SEED_BASE           # the Python-side training seed of session k >= 2 is 1000 + k; s1 is the fresh policy's seed 0
TRANSITION_CAP = G2.TRANSITION_CAP
GLOBAL_CAP_S = G2.GLOBAL_CAP_S                     # the 145-minute session hard cap
WALL_CAP_GRACE_S = G2.WALL_CAP_GRACE_S
POOL_SPAWN_S = G2.POOL_SPAWN_S
POOL_SPAWNS = G2.POOL_SPAWNS                       # P2, the tape drift check, training, the close audit
P2_STARTS = G2.P2_STARTS

# -- the one change: attempts replenish with training progress (decision 2; stop review 3.1) ---------------------------------------------------
SPACING_UNIT = 20                                  # counted strip outcomes
SPACING_CAP = 320


def spacing_need(f: int) -> int:
    """Counted strip outcomes at the pointer, since the last failed attempt, that the next attempt needs after f consecutive failed attempts at the
    pointer since the last move: 0 for f = 0; min(320, 20 x 2^(f-1)) for f >= 1 (20, 40, 80, 160, 320, 320, ...)."""
    f = int(f)
    if f <= 0:
        return 0
    return min(SPACING_CAP, SPACING_UNIT * (2 ** (f - 1)))


# -- the line budget, progress-only (decision 4; stop review 3.4) ------------------------------------------------------------------------------
LINE_BUDGET: Dict[int, int] = {2: 2128, 4: 1966, 6: 1694}   # END_BUDGET_<depth>: at counted session k the depth D_k must be at or before the named landing
LINE_SUCCESS_DEPTH = 1473                          # END_SUCCESS: D_k <= 1,473
LINE_CAP_SESSIONS = 8                              # END_CAP
LINE_PROGRESS_FROM_SESSION = 4                     # END_NO_PROGRESS: k >= 4 and D_k not earlier than D_{k-2}

# -- the reused tape baseline (decision 7) -------------------------------------------------------------------------------------------------------
TAPE_REUSE: Dict[str, Any] = {
    "source": "runs/m9_g2/s1/session/tape_baseline.json",
    "records": "runs/m9_g2/s1/t0/episodes.jsonl",
    "file_sha256": "81fa52c21078b2c2e5af9239678918099c6fb407608de085c7dd0c46d98196cd",
    "content_sha256": "d915fab9205547742e77360ba83f247b7ab304af7a37540ceb9910a2b614a23b",
    "measured_with_executable_sha256": "30a3913b32c4435369c8bbfa5c54ccd63bb5d398802c5c918969fd0eb1b666ee",
    "keys": dict(TAPE_KEYS),
    "labels": G2.KEYS["reach_label"],
    "measured_in": "M9-g2-s1 (T0, 2026-10-06), every counted tape clear replayed exactly",
}
DRIFT_LANDING = 2128
DRIFT_KEYS = 5                                     # the drift check of a session that reads the table by digest (g2 proposal 5.3 item 3): keys 0..4 at 2,128

# -- the session envelope (decision 6; the T0 phase is the digest verification and the drift check, not a measurement) ---------------------------
PHASES: Tuple[str, ...] = G2.PHASES                # open, p1, p2, t0, train, audit, verify, close
WALL_CAPS_S: Dict[str, float] = {"open": 60.0, "p1": 240.0, "p2": 120.0, "t0": 240.0, "train": 4800.0, "audit": 1200.0, "verify": 600.0, "close": 300.0}
TICK_CAPS: Dict[str, int] = {"open": 0, "p1": 60_000, "p2": 60_000, "t0": 60_000, "train": 20_000_000, "audit": 3_000_000, "verify": 1_500_000, "close": 0}
TRAIN_WALL_S = WALL_CAPS_S["train"]

# -- draw keys (Python-side sha256 uniforms; never the native RNG) ------------------------------------------------------------------------------
KEYS: Dict[str, str] = {
    "train_label": "m9|g3|train|<episode>", "sticky": "<label>|<tick>",
    "start": "m9|g3|start|<episode>|region|tau|lineage",
    "probe_label": "m9|g3|probe|<pointer>|<a>|<strip or landing>|<k>", "probe_start": "m9|g3|probe|<pointer>|<a>|strip|<k>|tau|lineage",
    "probe_action": "m9|g3|probeact|<pointer>|<a>|<part>|<k>|<tick>|<stick or button>",
    "reach_label": G2.KEYS["reach_label"],         # m9|g2|reach|<landing>|<k>: KEPT, so the audit pairs with the reused tape (identical sticky draws)
    "tick0_label": "m9|g3|tick0|<k>",
    "audit_action": "m9|g3|auditact|<sticky or unperturbed>|<landing>|<k>|<tick>|<stick or button>",
    "verify_pick": "m9|g3|verifypick|<pointer>|<a>|<part>", "artifact_sample": "m9|g3|artifact|<episode>",
    "p2": G2.KEYS["p2"],
}


def train_label(episode: int) -> str:
    return f"m9|g3|train|{int(episode)}"


def start_key(episode: int, what: str) -> str:
    return f"m9|g3|start|{int(episode)}|{what}"


def probe_label(pointer: int, attempt: int, part: Any, k: int) -> str:
    return f"m9|g3|probe|{int(pointer)}|{int(attempt)}|{part}|{int(k)}"


def probe_action_key(pointer: int, attempt: int, part: Any, k: int, tick: int) -> str:
    return f"m9|g3|probeact|{int(pointer)}|{int(attempt)}|{part}|{int(k)}|{int(tick)}"


def reach_label(landing: int, k: int) -> str:
    """The g2 family, kept: the reused tape's episode k at the landing was perturbed under exactly this label."""
    return G2.reach_label(landing, k)


def tick0_label(k: int) -> str:
    return f"m9|g3|tick0|{int(k)}"


def audit_action_key(mode: str, landing: int, k: int, tick: int) -> str:
    if mode not in ("sticky", "unperturbed"):
        raise ValueError(f"unknown audit mode {mode!r}")
    return f"m9|g3|auditact|{mode}|{int(landing)}|{int(k)}|{int(tick)}"


def verify_pick_key(pointer: int, attempt: int, part: Any) -> str:
    return f"m9|g3|verifypick|{int(pointer)}|{int(attempt)}|{part}"


def artifact_sample_key(episode: int) -> str:
    return f"m9|g3|artifact|{int(episode)}"


def sticky_key(label: str, tick: int) -> str:
    return f"{label}|{int(tick)}"


bar = G2.bar
bar_from_counts = G2.bar_from_counts


def frontier_description() -> Dict[str, Any]:
    g2 = G2.frontier_description()
    return {"rule": FRONTIER_RULE_ID, "tau0": TAU0, "strip": STRIP,
            "trigger": dict(g2["trigger"], restarts="at the session open, after every move, after every attempt at the pointer, after every deferred trigger"),
            "test": dict(g2["test"]), "recheck": g2["recheck"], "move": g2["move"],
            "attempts": {"bounds": "none: no HELD and no STALLED; no attempt count freezes the frontier or ends the line; per-pointer attempt counts are recorded and reported",
                         "spacing": {"unit": SPACING_UNIT, "cap": SPACING_CAP, "need": "0 for f = 0; min(cap, unit x 2^(f-1)) for f >= 1 consecutive failed attempts at the pointer since the last move",
                                     "counts": "counted strip outcomes at the pointer since the last failed attempt (completed training episodes whose start was drawn from the strip under the "
                                               "current pointer; stale and non-strip outcomes never count; outcomes completing between a trigger and its attempt count)",
                                     "deferred": "a trigger inside the spacing is logged deferred_trigger, no attempt runs, the window restarts",
                                     "interrupted": "an attempt interrupted by a cap counts as neither pass nor fail: f and the outcome count are unchanged; the window restarts",
                                     "carried": "f (the failed attempts at the pointer over the line) and the outcomes since the last failed attempt are carried in curriculum_state.json"}},
            "pause": g2["pause"], "keys": {k: KEYS[k] for k in ("probe_label", "probe_start", "probe_action", "sticky")}}


def tape_description() -> Dict[str, Any]:
    return {"rule": TAPE_RULE_ID, "reuse": dict(TAPE_REUSE), "sticky_p": STICKY_P, "lineage": TAPE_LINEAGE, "bar": "max(10, ceil(20 p_hat) + 5)",
            "audit_keys": f"k = 0..{AUDIT_EPISODES - 1} of the reused table's family in every session", "verified_at_open": "file sha256, content digest, every landing pinned, the executable pin",
            "drift_check": {"landing": DRIFT_LANDING, "keys": DRIFT_KEYS, "requires": "identical outcomes (and native action digests where the source records exist); a difference is INVALID"}}


def line_contract_description() -> Dict[str, Any]:
    """The line's contract (fixed in s1; a resume refuses any change): observation, reward, action, PPO values, sticky p, curriculum constants, the frontier
    rule (the spacing rule included), the reused tape."""
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
                      "line": {"id": LINE_RULE_ID, "budget": {str(k): v for k, v in sorted(LINE_BUDGET.items())}, "progress_from_session": LINE_PROGRESS_FROM_SESSION,
                               "cap_sessions": LINE_CAP_SESSIONS, "success_depth": LINE_SUCCESS_DEPTH, "incomplete_counts_if_train_fraction": INCOMPLETE_COUNTS_IF_TRAIN_FRACTION,
                               "never_ends_on": ["a NULL s1", "an attempt count", "a HELD or STALLED state (none exists)"]}},
            "phases": list(PHASES), "wall_caps_s": dict(WALL_CAPS_S), "tick_caps": dict(TICK_CAPS), "transition_cap": TRANSITION_CAP, "global_cap_s": GLOBAL_CAP_S,
            "wall_cap_grace_s": WALL_CAP_GRACE_S, "pool_spawn_s": POOL_SPAWN_S, "pool_spawns": POOL_SPAWNS, "p2_starts": P2_STARTS, "split": list(SPLIT), "slots": N_SLOTS,
            "probe_slots": PROBE_SLOTS, "verify_threads": VERIFY_THREADS, "verify_launch_margin_s": VERIFY_LAUNCH_MARGIN_S, "memory_caps_mb": dict(MEMORY_CAPS_MB),
            "max_battleship_processes": MAX_BATTLESHIP_PROCESSES, "lifecycle_failure_limit": LIFECYCLE_FAILURE_LIMIT, "probe_lifecycle_limit": PROBE_LIFECYCLE_LIMIT,
            "artifact_sample_per_mille": ARTIFACT_SAMPLE_PER_MILLE, "first_clears_verified": FIRST_CLEARS_VERIFIED, "keys": dict(KEYS),
            "g2_contract_sha256": G2.contract_digest(), "g2_line_contract_sha256": G2.line_contract_digest(), "g1_contract_sha256": C.contract_digest()}


def contract_digest() -> str:
    return hashlib.sha256(json.dumps(description(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


if __name__ == "__main__":
    print(json.dumps({"contract": CONTRACT_ID, "digest": contract_digest(), "line_contract": LINE_CONTRACT_ID, "line_digest": line_contract_digest(),
                      "spacing": {f: spacing_need(f) for f in range(8)}}, indent=1))
