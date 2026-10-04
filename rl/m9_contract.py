"""M9-g1: the registered constants of the gate (pure, standard library only).

Design: docs/rl_m9_policy_proposal_2026-10-03.md as decided in docs/rl_m9_g1_decisions_2026-10-04.md. Every number that the gate's rule,
curriculum, perturbation, caps or budgets read lives here, so the contract digest (`contract_digest`) pins them all at once and no other
module carries a private copy.

SCOPE: backward-algorithm robustification of the agent's own verified rd4 clears (M9-g1). One gate, one run. Not a claim that a policy
clears from tick 0; not a comparison; not a learning result beyond the registered rule `m9_g1_rule_v1`.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Tuple

GATE = "m9_g1"
CONTRACT_ID = "m9_g1_contract_v1"
RULE_ID = "m9_g1_rule_v1"
MILESTONE = "M9"
SCOPE = ("M9-g1: backward-algorithm robustification (PPO from prefix-replayed start states on the agent's own two verified rd4 clears, "
         "sticky actions p = 0.25, observation btt_policy_obs_v3_entities, reward btt_reward_v2); one gate, one run, one set of keyed "
         "draws; reach measured at landing states under the registered rule; no claim of a tick-0 policy")

# -- task identity (the single task of the project; rl/experiment_config.SUPPORTED_TASKS is the registry, checked by the artifact writer) --
TASK_ID = "ssb64_us_mario_btt_v1"
TASK: Dict[str, str] = {"id": TASK_ID, "character": "mario", "stage": "btt_mario"}

# -- environment contracts ----------------------------------------------------------------------------------------------------------
HORIZON = 3600                           # input ticks, counted from the reset (a prefix tick counts)
ACTION_CONTRACT = "btt_s9_b8_v1"         # Track 1, MultiDiscrete([9, 8]); word = stick * 8 + button
OBSERVATION_CONTRACT = "btt_policy_obs_v3_entities"
REWARD_CONTRACT = "btt_reward_v2"
FLAGS_TRAIN: Dict[str, str] = {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1", "SSB64_RL_SPATIAL": "1", "SSB64_RL_ENTITY": "1"}
FLAGS_EVAL: Dict[str, str] = dict(FLAGS_TRAIN, SSB64_RL_TARGET_DIAG="1")
FLAGS_VERIFY: Dict[str, str] = dict(FLAGS_EVAL, SSB64_RL_INPUT="1")      # the four read-only diagnostics, as rd1-rd4's verification replays

# -- the routes (decision 5: only the two verified rd4 clears) ----------------------------------------------------------------------
LINEAGES: Tuple[Dict[str, Any], ...] = (
    {"name": "T_clear", "route_dir": "runs/m8_rd_rd4/routes/T_clear", "iteration": 11206, "words": 2326,
     "native_action_digest": "5eccd4e2d5d77b25d69a2ae87211c05f8c7349fdeeeed6e094b53a88003907ba", "completion_time_passed": 2325, "completion_input_tick": 2326},
    {"name": "T_t", "route_dir": "runs/m8_rd_rd4/routes/T_t", "iteration": 11286, "words": 2315,
     "native_action_digest": "de1228be4146b720adc3f1272a9e65a8c0dcd7882b83134949f3893adfef8045",
     "completion_time_passed": 2314, "completion_input_tick": 2315},
)
SHARED_PREFIX = 2298                     # T_t shares its first 2,298 words with T_clear (rd4 results, section 3)
TAPE_LINEAGE = "T_clear"                 # the tape control replays the trunk's words (T_clear)

# -- the curriculum (proposal 5.1) ---------------------------------------------------------------------------------------------------
TAU0 = 2300                              # the frontier pointer's first value
STRIP = 20                               # the pointer moves back in strips of 20 ticks
NEAR_WINDOW = 40                         # the near window [tau* + 20, tau* + 60)
REGION_WEIGHTS: Tuple[Tuple[str, int], ...] = (("strip", 50), ("near", 30), ("rehearsal", 20))     # per cent
BLOCK_SIZE = 10                          # strip outcomes per block
BLOCK_PASS = 3                           # clears per block that earn a step back (rho = 0.3)
MIN_WORDS_AFTER_START = 2                # a start tau needs a lineage with at least tau + 2 words (a start never lies on the terminal tick)

# -- sticky actions (decision 2) -----------------------------------------------------------------------------------------------------
STICKY_P = 0.25

# -- the reach measure (proposal 5.5, decision 3) -----------------------------------------------------------------------------------
LANDINGS: Tuple[int, ...] = (2128, 1966, 1694, 1473, 1369, 1248)       # the first tick of each grounded segment of the shared trunk
EVAL_EPISODES = 20                       # stochastic sticky episodes per landing state, and tape episodes per landing state
GATE_MIN_CLEARS = 10                     # at least 10 of 20 at the landing and at every later landing
TAPE_MARGIN = 5                          # and at least 5 more clears than the paired tape control
PASS_DEPTH = 1694                        # decision 4: PASS if R <= 1,694
CROSSING_DEPTH = 1473                    # R <= 1,473 adds "crossing learned"
INCONCLUSIVE_DEPTHS: Tuple[int, ...] = (1966, 2128)
FINE_GRID_STEP = 25
FINE_GRID_EPISODES = 10
FINE_GRID_MAX_POINTS = 40
FINE_GRID_MIN_CLEARS = 5                 # R_fine (descriptive): at least 5 of 10 at the point and at every later point
TICK0_EPISODES = 20
# the final claim: defined, NOT tested in g1 (decision 3)
CLAIM = {"unperturbed_clears_min_of_100": 50, "sticky_clears_min_of_100": 50, "tape_margin_min": 25, "episodes": 100, "tested_in_g1": False}

# -- PPO (decision 6: the M7n profile, a fresh policy, ent_coef 0.01 from the start) --------------------------------------------------
ROLLOUT_SIZE = 5120
PPO: Dict[str, Any] = {"policy": "MultiInputPolicy", "net_arch": [64, 64], "activation": "tanh", "learning_rate": 3e-4, "batch_size": 512,
                       "n_epochs": 10, "gamma": 0.999, "gae_lambda": 0.995, "clip_range": 0.2, "ent_coef": 0.01, "vf_coef": 0.5,
                       "max_grad_norm": 0.5, "torch_threads": 1, "device": "cpu", "seed": 0, "rollout_size": ROLLOUT_SIZE,
                       "normalize_observations": False, "normalize_rewards": False, "initialisation": "fresh"}
CHECKPOINT_EVERY = 102_400

# -- process split (decision 9) -------------------------------------------------------------------------------------------------------
SPLIT_DEFAULT = (4, 6)                   # (playing, preparing)
SPLIT_ALTERNATIVE = (2, 8)
SPLIT_SWITCH_RATIO = 1.10                # the registered selection rule: 2 + 8 only if its measured transitions/s >= 1.10 x 4 + 6's
N_SLOTS = 10                             # BattleShip process slots (at most 10 game processes)

# -- budgets and caps (decision 12; proposal 5.3) -------------------------------------------------------------------------------------
PHASES: Tuple[str, ...] = ("p1", "p2", "p3", "p4", "train", "eval", "verify", "close")
WALL_CAPS_S: Dict[str, float] = {"p1": 240.0, "p2": 120.0, "p3": 300.0, "p4": 360.0, "train": 3600.0, "eval": 1500.0, "verify": 900.0, "close": 300.0}
TICK_CAPS: Dict[str, int] = {"p1": 60_000, "p2": 40_000, "p3": 600_000, "p4": 600_000, "train": 15_000_000, "eval": 3_000_000, "verify": 1_500_000, "close": 0}
TRANSITION_CAP = 3_072_000
GLOBAL_CAP_S = 7800.0                    # the 130-minute session hard cap
WALL_CAP_GRACE_S = 20.0
JOB_TIMEOUT_S = 900.0
P2_STARTS = 12
P3_WINDOW_S = 120.0
P3_TAU_WINDOW = (2250, 2310)             # the random-policy window of the split measurement
MEMORY_CAPS_MB: Dict[str, float] = {"main_private": 3072, "tree_private": 9216, "tree_working_set": 4096, "system_available_min": 1024,
                                    "system_commit_free_min": 2048}
MAX_BATTLESHIP_PROCESSES = 10
LIFECYCLE_FAILURE_LIMIT = 3              # as rd1-rd4: more than three lifecycle failures in a phase is INCOMPLETE
ARTIFACT_SAMPLE_PER_MILLE = 20           # a keyed 2 % sample of training episodes keeps a full artifact

# -- draw keys (Python-side sha256 uniforms; never the native RNG) --------------------------------------------------------------------
KEYS: Dict[str, str] = {
    "start_region": "m9|g1|start|<episode>|region", "start_tau": "m9|g1|start|<episode>|tau", "start_lineage": "m9|g1|start|<episode>|lineage",
    "sticky": "m9|g1|sticky|<episode label>|<tick>", "p2_start": "m9|g1|p2|<k>|tau", "p2_word": "m9|g1|p2|<k>|word",
    "artifact_sample": "m9|g1|artifact|<episode>",
}


def description() -> Dict[str, Any]:
    return {"contract": CONTRACT_ID, "gate": GATE, "rule": RULE_ID, "task": dict(TASK), "horizon": HORIZON, "action": ACTION_CONTRACT,
            "observation": OBSERVATION_CONTRACT, "reward": REWARD_CONTRACT, "flags": {"train": FLAGS_TRAIN, "eval": FLAGS_EVAL, "verify": FLAGS_VERIFY},
            "lineages": [dict(x) for x in LINEAGES], "shared_prefix": SHARED_PREFIX, "tape_lineage": TAPE_LINEAGE,
            "curriculum": {"tau0": TAU0, "strip": STRIP, "near_window": NEAR_WINDOW, "region_weights": [list(x) for x in REGION_WEIGHTS],
                           "block_size": BLOCK_SIZE, "block_pass": BLOCK_PASS, "min_words_after_start": MIN_WORDS_AFTER_START},
            "sticky_p": STICKY_P, "landings": list(LANDINGS),
            "reach": {"episodes": EVAL_EPISODES, "min_clears": GATE_MIN_CLEARS, "tape_margin": TAPE_MARGIN, "pass_depth": PASS_DEPTH,
                      "crossing_depth": CROSSING_DEPTH, "inconclusive_depths": list(INCONCLUSIVE_DEPTHS), "fine_grid_step": FINE_GRID_STEP,
                      "fine_grid_episodes": FINE_GRID_EPISODES, "fine_grid_max_points": FINE_GRID_MAX_POINTS,
                      "fine_grid_min_clears": FINE_GRID_MIN_CLEARS, "tick0_episodes": TICK0_EPISODES},
            "claim": dict(CLAIM), "ppo": dict(PPO), "checkpoint_every": CHECKPOINT_EVERY,
            "split": {"default": list(SPLIT_DEFAULT), "alternative": list(SPLIT_ALTERNATIVE), "switch_ratio": SPLIT_SWITCH_RATIO, "slots": N_SLOTS},
            "wall_caps_s": dict(WALL_CAPS_S), "tick_caps": dict(TICK_CAPS), "transition_cap": TRANSITION_CAP, "global_cap_s": GLOBAL_CAP_S,
            "wall_cap_grace_s": WALL_CAP_GRACE_S, "job_timeout_s": JOB_TIMEOUT_S, "p2_starts": P2_STARTS, "p3_window_s": P3_WINDOW_S,
            "p3_tau_window": list(P3_TAU_WINDOW), "memory_caps_mb": dict(MEMORY_CAPS_MB), "max_battleship_processes": MAX_BATTLESHIP_PROCESSES,
            "lifecycle_failure_limit": LIFECYCLE_FAILURE_LIMIT, "artifact_sample_per_mille": ARTIFACT_SAMPLE_PER_MILLE, "keys": dict(KEYS)}


def contract_digest() -> str:
    return hashlib.sha256(json.dumps(description(), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


if __name__ == "__main__":
    print(json.dumps({"contract": CONTRACT_ID, "digest": contract_digest()}, indent=1))
