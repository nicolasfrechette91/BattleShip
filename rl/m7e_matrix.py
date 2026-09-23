#!/usr/bin/env python3
"""M7e Phase B: the bounded reward-v2 extension matrix, its manifest and its guards.

    python rl/m7e_run.py manifest            # writes docs/rl_extended_training_m7e_manifest.json

Three fresh PPO runs on the unchanged M7c standby stack (N=5, 3,600-tick
horizon, observation-only VecNormalize, btt_reward_v2 unchanged): seeds 0, 1
and 2, each to a hard maximum of 3,072,000 transitions. Exactly one
behavioural thing changes from the M7d reward-v2 baseline - the transition
budget - with the post-hoc evaluation episode counts raised as a measurement
consequence of it.

The authority for every number here is the committed Phase A proposal
docs/rl_extended_training_m7e_proposal.md (sections 6.1-6.7 and 7); the
profiles are the explicit, reviewable TOMLs under rl/configs/m7e/ and
rl/experiment_config.py validates, resolves and fingerprints them. This
module only:

- names the matrix (seeds, execution order, directories);
- builds the resolved experiment matrix: every resolved field of every run, a
  field-by-field diff of each profile pair, of each profile against its M7d
  reward-v2 counterpart and against the canonical M7c standby v2 profile, the
  trainer configuration each run will receive, the post-hoc evaluation plan
  and the eight pre-registered decision gates, with an explicit proof that the
  three profiles differ only in run identity, the seed and its derived worker
  seeds, output paths and the derived hashes;
- guards the matrix: planned directories are unique, disjoint, new and unable
  to touch runs/m7d, the historical run tree is fingerprinted and must stay
  byte-identical, and a resume may only continue a run's own lineage (same
  semantic fingerprint, seed and reward contract).

Reused unchanged from rl/m7d_matrix.py (the M7d infrastructure is not
duplicated): flatten, field_diff, classify, trainer_view,
expected_initial_policy_digest, historical_snapshot, compare_snapshots,
resume_guard, within, read_json, write_json, MatrixError, MAX_GAME_PROCESSES.

Standard library + rl/experiment_config.py + rl/m7d_matrix.py only at module
level (no PyTorch): the trainer-configuration view imports rl/m7_trainer.py
lazily. No native RNG state is introduced, inspected, logged, validated,
controlled, compared or hashed here; seeds are Python / NumPy / PyTorch / SB3
only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import experiment_config as ec  # noqa: E402
import m7d_matrix as mm  # noqa: E402  (no torch at module level)

# -- reused unchanged from the M7d matrix -----------------------------------------------------------------------------
MatrixError = mm.MatrixError
flatten = mm.flatten
field_diff = mm.field_diff
classify = mm.classify
trainer_view = mm.trainer_view
expected_initial_policy_digest = mm.expected_initial_policy_digest
historical_snapshot = mm.historical_snapshot
compare_snapshots = mm.compare_snapshots
within = mm.within
read_json = mm.read_json
write_json = mm.write_json

REPO_ROOT = ec.REPO_ROOT
MILESTONE = "M7e"
PHASE = "B"
MATRIX_SCHEMA = "battleship_m7e_matrix_v1"
CONFIG_DIR = REPO_ROOT / "rl" / "configs" / "m7e"
CANONICAL_V2 = REPO_ROOT / "rl" / "configs" / "m7_mario_us_reward_v2_standby.toml"
M7D_CONFIG_DIR = REPO_ROOT / "rl" / "configs" / "m7d"
REWARD_ID = "btt_reward_v2"
SEEDS: Tuple[int, ...] = (0, 1, 2)
# Execution order: the proposal (section 6.1) names seeds 0, 1, 2 and requires strictly sequential runs; it
# registers no other order, so the task's default applies.
ORDER: Tuple[int, ...] = (0, 1, 2)
MATRIX_ROOT = REPO_ROOT / "runs" / "m7e"
STATE_DIR = MATRIX_ROOT / "_matrix"
EVAL_ROOT = MATRIX_ROOT / "_eval"
REPLAY_ROOT = MATRIX_ROOT / "_replay"
MANIFEST_DOC = REPO_ROOT / "docs" / "rl_extended_training_m7e_manifest.json"
HISTORICAL_ROOT = REPO_ROOT / "runs"
MAX_GAME_PROCESSES = mm.MAX_GAME_PROCESSES        # 10 = N=5 x (1 active + 1 standby)
PROPOSAL_DOC = REPO_ROOT / "docs" / "rl_extended_training_m7e_proposal.md"
DIAGNOSIS_DOC = REPO_ROOT / "docs" / "rl_v2_idle_diagnosis_m7e.md"

# -- the frozen M7e training contract (proposal sections 6.1, 6.2, 6.7) -----------------------------------------------
TOTAL_TRANSITIONS = 3_072_000        # hard maximum per seed; no continuation beyond it inside M7e
CHECKPOINT_INTERVAL = 102_400        # 30 checkpoint sets + final
HORIZON = 3600
PROCESS_COUNT = 5

# -- post-hoc evaluation protocol (proposal section 6.3) --------------------------------------------------------------
EVAL_INTERVAL = 307_200              # evaluated points: initial, 9 intermediate, final = 11 per seed
FINAL_EPISODES = {"deterministic": 100, "stochastic": 100}     # initial (ckpt_000000000) and final sets
CURVE_EPISODES = {"deterministic": 5, "stochastic": 60}        # each intermediate point (from the profile)
RANDOM_BASELINE_EPISODES = 100
EVAL_SEED = 12345
M7A_RANDOM_BASELINE = mm.M7A_RANDOM_BASELINE

# -- the pre-registered plateau rule (proposal section 6.6) -----------------------------------------------------------
PLATEAU_WINDOW_POINTS = 6            # the final 6 evaluated checkpoints: 1,536,000 .. 3,072,000
PLATEAU_SLOPE_THRESHOLD = 0.25       # targets per 1e6 transitions
PLATEAU_SEEDS_REQUIRED = 2           # in at least 2 of 3 seeds
PLATEAU_TAIL_TOLERANCE = 0.05        # no seed's tail fraction may have fallen by more than this over the span
BOOTSTRAP_RESAMPLES = mm.BOOTSTRAP_RESAMPLES
BOOTSTRAP_LEVEL = mm.BOOTSTRAP_LEVEL

PLATEAU_RULE: Dict[str, Any] = {
    "rule_id": "m7e_plateau_rule_v1",
    "registered": "docs/rl_extended_training_m7e_proposal.md section 6.6, committed in 9d45235 before any M7e "
                  "Phase B training data existed",
    "window": f"the final {PLATEAU_WINDOW_POINTS} evaluated checkpoints, t = {TOTAL_TRANSITIONS - 5 * EVAL_INTERVAL} "
              f"through {TOTAL_TRANSITIONS} (spanning {5 * EVAL_INTERVAL} transitions)",
    "declared_when": [
        f"the bootstrap {int(BOOTSTRAP_LEVEL * 100)} % CI of the Theil-Sen slope of mean stochastic targets excludes "
        f"+{PLATEAU_SLOPE_THRESHOLD} targets per 1e6 transitions, in at least {PLATEAU_SEEDS_REQUIRED} of 3 seeds",
        f"and no seed's tail fraction has fallen by more than {PLATEAU_TAIL_TOLERANCE} over the same span",
    ],
    "both_halves_required": "a flat target curve with a still-shrinking tail is progress in a form the target count "
                            "has not yet registered",
    "slope_units": "targets per 1e6 transitions",
    "bootstrap": {"resamples": BOOTSTRAP_RESAMPLES, "level": BOOTSTRAP_LEVEL,
                  "unit": "the stochastic episodes of each evaluated point are resampled with replacement inside "
                          "that point; the Theil-Sen slope is recomputed from the resampled point means"},
}

# -- the eight pre-registered decision gates (proposal section 7, verbatim) -------------------------------------------
OBJECTIVE_RANKING = ("verified clear", "more targets for incomplete runs", "faster time among verified clears",
                     "reward is diagnostic only")
GATES: Tuple[Dict[str, Any], ...] = (
    {"gate": 1, "key": "verified_clear", "outcome": "A verified clear (natively re-validated per section 6.5)",
     "response": "The primary objective is reached for the first time. M7f becomes clear-rate and completion-time "
                 "work under btt_reward_v2, which is then confirmed rather than provisional. Preserve the clear, its "
                 "checkpoint and its full action stream permanently; report both completion clocks separately; open "
                 "the Track 2 comparison against the 7.43 s baseline. Do not retune anything until the clear is "
                 "reproduced at a second seed.",
     "mutually_exclusive_with": [2, 4], "evaluation_order": 1},
    {"gate": 2, "key": "better_targets_no_clear",
     "outcome": "Better targets, no clear (mean targets up, 3/3 or 2/3 seeds, ceiling still <= 6)",
     "response": "v2 is confirmed for continued use on objective rank 2. The budget question is answered: more "
                 "transitions help. M7f addresses the ceiling, not the budget - and the target-identity "
                 "instrumentation (section 6.6) is promoted from optional to prerequisite, because 'which four are "
                 "never broken' is then the blocking unknown.",
     "mutually_exclusive_with": [1, 4], "evaluation_order": 2},
    {"gate": 3, "key": "still_improving",
     "outcome": f"Still improving at {TOTAL_TRANSITIONS:,} (no plateau by section 6.6)",
     "response": "Do not silently extend. Record that the budget is still not the binding constraint, and open M7f "
                 "as an explicit budget-versus-intervention decision with the new curves in hand. A further "
                 "extension needs its own pre-registration and its own maximum.",
     "evaluation_order": 4},
    {"gate": 4, "key": "plateau", "outcome": "A plateau (by the section 6.6 rule)",
     "response": "The budget question is settled negatively: unchanged v2 has converged short of the objective. This "
                 "is the trigger for option C - a controlled anti-confinement or exploration intervention, one "
                 "behaviour-changing variable against the v2 baseline, given a new contract identity (never an edit "
                 "to v1 or v2), with v2 preserved and rerun as the control arm.",
     "mutually_exclusive_with": [1, 2], "evaluation_order": 3},
    {"gate": 5, "key": "worse_idling",
     "outcome": "Worse idling (tail fraction up >= 0.10 in >= 2 seeds, or zero_target_horizon_rate > 0.05 anywhere, "
                "or targets flat/down)",
     "response": "Treat as a genuine regression of the selected contract, not a metric artefact - the proportional "
                 "metric is immune to the section 1 confound. Stop; do not extend further. Re-open the M7d selection "
                 "with the M7e evidence attached, and design the intervention against a documented failure rather "
                 "than a suspicion.",
     "thresholds": {"tail_fraction_rise": 0.10, "seeds_required": 2, "zero_target_horizon_rate": 0.05},
     "evaluation_order": 5},
    {"gate": 6, "key": "seed_disagreement",
     "outcome": "Strong seed disagreement (>= 1 seed improving while >= 1 regresses, by section 3's rule)",
     "response": "No aggregate claim is made. Report per seed, add seeds 3 and 4 at the same 3,072,000 budget before "
                 "any contract or hyperparameter change, and treat the three-seed conclusion as unresolved until "
                 "five exist. Seed-cluster intervals, not episode-level ones, carry the cross-seed claim.",
     "evaluation_order": 6},
    {"gate": 7, "key": "deterministic_collapse",
     "outcome": "Deterministic collapse persists (collapse_share >= 0.5 in >= 2 of 3 seeds at final)",
     "response": "Record it as an evaluation-mode property of the contract, not as a training failure, and keep the "
                 "stochastic policy as the reported one. If it persists while policy entropy has stopped falling, "
                 "that combination contradicts hypothesis 1 in section 4 and forces a re-ranking of the root causes "
                 "before M7f is designed.",
     "thresholds": {"collapse_share": 0.5, "seeds_required": 2}, "evaluation_order": 7},
    {"gate": 8, "key": "lifecycle_regression",
     "outcome": "A lifecycle, artifact or replay regression (any process-count breach, port leak, non-reproducing "
                "preserved artifact, git diff --check failure, or a changed user-configuration sha256)",
     "response": "Stop the experiment at once. Do not analyse or report gameplay results from a run whose lifecycle "
                 "is in question. Diagnose, document under docs/bugs/, fix, re-verify the full regression chain, and "
                 "only then decide whether the affected runs are salvageable or must be rerun.",
     "pre_empts": "all others", "evaluation_order": 0},
)
GATE_ORDERING = ("Gate 8 pre-empts all others. Gates 1, 2 and 4 are mutually exclusive and are evaluated in that "
                 "order. Gate 3 is the complement of gate 4 under the section 6.6 rule. Gates 5, 6 and 7 are "
                 "independent observations and may co-occur with any of the others.")

# -- early-stop / continue rules (proposal sections 6.2, 6.5 and gate 8) ----------------------------------------------
STOPPING_RULES: Dict[str, Any] = {
    "maximum_budget": f"{TOTAL_TRANSITIONS:,} transitions per seed, hard. No continuation beyond it inside M7e, "
                      f"whatever the curves do; a further extension is a new milestone with its own "
                      f"pre-registration (proposal section 6.2).",
    "a_clear_does_not_stop_training": "Training is not stopped by a clear; the run continues to its budget so the "
                                      "curve stays interpretable (proposal section 6.5 item 5).",
    "hard_stop": "Gate 8 conditions stop the experiment at once: more than 10 live BattleShip processes, a "
                 "user-configuration change, free disk below 5 GiB, or any episode / reward-contract invariant "
                 "violated. The monitor raises them; the orchestrator stops the trainer and the matrix.",
    "no_post_hoc_rule_invention": "The plateau rule, the eight gates and this budget were registered in 9d45235 "
                                  "before any M7e Phase B data existed and are applied as written.",
}

# -- allowed differences ----------------------------------------------------------------------------------------------
# Across the three M7e profiles: run identity, the seed and its derived worker seeds, output paths, derived hashes.
PROFILE_ALLOWED: Dict[str, Tuple[str, ...]] = {
    "seed_and_derived_worker_seeds": ("config.run.base_seed",),
    "run_identity": ("config.run.name", "config.run.notes"),
    "output_paths": ("resolved.run_dir", "source.path"),
    "derived_hashes": ("fingerprints.source_sha256", "fingerprints.semantic_fingerprint", "source.sha256",
                       "source.size"),
}
# One M7e profile against its M7d reward-v2 counterpart at the same seed: the budget, the checkpoint cadence and the
# curve episode counts, plus identity / paths / hashes. Nothing else may differ.
VS_M7D_ALLOWED: Dict[str, Tuple[str, ...]] = {
    "transition_budget": ("config.run.total_transitions", "resolved.rollouts"),
    "checkpoint_cadence": ("config.checkpoint.interval",),
    "evaluation_episode_counts": ("config.evaluation.deterministic_episodes",
                                  "config.evaluation.stochastic_episodes"),
    "run_identity": ("config.run.name", "config.run.notes", "config.run.mode", "resolved.mode"),
    "output_paths": ("config.run.output_root", "resolved.output_root", "resolved.run_dir", "source.path"),
    "derived_hashes": ("fingerprints.source_sha256", "fingerprints.semantic_fingerprint",
                       "fingerprints.compatibility_fingerprint", "source.sha256", "source.size"),
}
# Trainer configuration (m7_trainer.M7Config.to_json) of two M7e runs.
TRAINER_ALLOWED: Dict[str, Tuple[str, ...]] = {
    "seed_and_derived_worker_seeds": ("base_seed", "seeds.base_seed", "seeds.ppo_seed", "seeds.worker_seeds",
                                      "seeds.vector_reset_seeds"),
    "run_identity": ("run_id", "experiment.name"),
    "output_paths": ("run_dir", "output_root", "experiment.source.path"),
    "derived_hashes": ("experiment.source.sha256", "experiment.semantic_fingerprint"),
}
# Post-hoc evaluation plan entries of two M7e runs.
EVAL_ALLOWED: Dict[str, Tuple[str, ...]] = {
    "run_identity": ("run",),
    "output_paths": ("checkpoint", "out_dir"),
}


@dataclass(frozen=True)
class RunSpec:
    seed: int
    order_index: int     # 1-based position in the sequential execution order

    @property
    def name(self) -> str:
        return f"m7e_s{self.seed}_v2"

    @property
    def config_path(self) -> Path:
        return CONFIG_DIR / f"{self.name}.toml"

    @property
    def m7d_counterpart(self) -> str:
        return f"m7d_s{self.seed}_v2"

    @property
    def m7d_config_path(self) -> Path:
        return M7D_CONFIG_DIR / f"{self.m7d_counterpart}.toml"

    @property
    def run_dir(self) -> Path:
        return MATRIX_ROOT / self.name

    @property
    def eval_dir(self) -> Path:
        return EVAL_ROOT / self.name

    @property
    def replay_dir(self) -> Path:
        return REPLAY_ROOT / self.name


def matrix() -> List[RunSpec]:
    """The three runs in execution order."""
    return [RunSpec(seed=s, order_index=i) for i, s in enumerate(ORDER, 1)]


def run_by_name(name: str) -> RunSpec:
    for spec in matrix():
        if spec.name == name:
            return spec
    raise MatrixError(f"{name!r} is not an M7e matrix run ({[s.name for s in matrix()]})")


def load_run(spec: RunSpec) -> ec.Experiment:
    return ec.load_experiment(spec.config_path)


# -- the evaluation plan ----------------------------------------------------------------------------------------------


def evaluated_points(total: int = TOTAL_TRANSITIONS, interval: int = EVAL_INTERVAL) -> List[int]:
    """0, then every `interval` up to but excluding `total`, then `total`: 11 points at the registered cadence."""
    return [0] + list(range(interval, total, interval)) + [total]


def evaluation_plan(spec: RunSpec, exp: ec.Experiment) -> List[Dict[str, Any]]:
    """The post-hoc evaluations of one run (identical protocol for every run; only paths and identity differ).

    Proposal section 6.3: initial (0), every 307,200 transitions (9 intermediate points), then final
    (3,072,000) = 11 points; 100 stochastic + 100 deterministic at initial and final, 60 + 5 at each
    intermediate point; frozen VecNormalize statistics, seed 12345, every episode preserved."""
    v = exp.values
    total = int(v["run.total_transitions"])
    if total != TOTAL_TRANSITIONS:
        raise MatrixError(f"{spec.name}: total_transitions {total} != the registered budget {TOTAL_TRANSITIONS}")
    common = {"seed": int(v["evaluation.seed"]), "workers": exp.eval_workers, "horizon": int(v["environment.horizon"]),
              "extra_env": dict(exp.extra_env), "standby_preboot": exp.standby_preboot,
              "standby_count": exp.standby_count, "frozen_vecnormalize": True, "preserve_all": True,
              "reward_contract": exp.reward.contract, "run": spec.name}
    plan = [dict(common, label="initial", checkpoint=f"{spec.name}/checkpoints/ckpt_000000000",
                 num_timesteps=0, deterministic_episodes=FINAL_EPISODES["deterministic"],
                 stochastic_episodes=FINAL_EPISODES["stochastic"], out_dir=f"_eval/{spec.name}/initial")]
    for t in evaluated_points(total)[1:-1]:
        plan.append(dict(common, label=f"curve_t{t:09d}", checkpoint=f"{spec.name}/checkpoints/ckpt_{t:09d}",
                         num_timesteps=t, deterministic_episodes=int(v["evaluation.deterministic_episodes"]),
                         stochastic_episodes=int(v["evaluation.stochastic_episodes"]),
                         out_dir=f"_eval/{spec.name}/curve_t{t:09d}"))
    plan.append(dict(common, label="final", checkpoint=f"{spec.name}/final", num_timesteps=total,
                     deterministic_episodes=FINAL_EPISODES["deterministic"],
                     stochastic_episodes=FINAL_EPISODES["stochastic"], out_dir=f"_eval/{spec.name}/final"))
    return plan


def evaluation_census_plan() -> Dict[str, Any]:
    """The exact arithmetic of the proposal's 3,055 post-hoc evaluation episodes."""
    points = evaluated_points()
    inter = len(points) - 2
    per_seed_stoch = 2 * FINAL_EPISODES["stochastic"] + inter * CURVE_EPISODES["stochastic"]
    per_seed_det = 2 * FINAL_EPISODES["deterministic"] + inter * CURVE_EPISODES["deterministic"]
    per_seed = per_seed_stoch + per_seed_det
    model_total = per_seed * len(SEEDS)
    return {
        "evaluated_points_per_seed": len(points),
        "points": points,
        "intermediate_points": inter,
        "arithmetic": {
            "stochastic_per_seed": f"{FINAL_EPISODES['stochastic']} (initial) + {inter} x "
                                   f"{CURVE_EPISODES['stochastic']} (intermediate) + {FINAL_EPISODES['stochastic']} "
                                   f"(final) = {per_seed_stoch}",
            "deterministic_per_seed": f"{FINAL_EPISODES['deterministic']} (initial) + {inter} x "
                                      f"{CURVE_EPISODES['deterministic']} (intermediate) + "
                                      f"{FINAL_EPISODES['deterministic']} (final) = {per_seed_det}",
            "per_seed": f"{per_seed_stoch} + {per_seed_det} = {per_seed}",
            "three_seeds": f"{len(SEEDS)} x {per_seed} = {model_total}",
            "plus_random_baseline": f"{model_total} + {RANDOM_BASELINE_EPISODES} = "
                                    f"{model_total + RANDOM_BASELINE_EPISODES}",
        },
        "stochastic_per_seed": per_seed_stoch,
        "deterministic_per_seed": per_seed_det,
        "per_seed": per_seed,
        "model_episodes": model_total,
        "random_baseline_episodes": RANDOM_BASELINE_EPISODES,
        "total_episodes": model_total + RANDOM_BASELINE_EPISODES,
        "proposal_total": 3055,
        "reconciles": model_total + RANDOM_BASELINE_EPISODES == 3055,
        "sessions": {"per_seed": 2 * len(points), "model": 2 * len(points) * len(SEEDS),
                     "random_baseline": 1, "total": 2 * len(points) * len(SEEDS) + 1,
                     "note": "one deterministic and one stochastic session per evaluated point, plus the random "
                             "baseline session"},
    }


# -- directories ------------------------------------------------------------------------------------------------------


def planned_directories() -> Dict[str, Path]:
    dirs: Dict[str, Path] = {"matrix_root": MATRIX_ROOT, "state": STATE_DIR, "eval_root": EVAL_ROOT,
                             "replay_root": REPLAY_ROOT, "random_baseline": EVAL_ROOT / "random_baseline"}
    for spec in matrix():
        dirs[f"run:{spec.name}"] = spec.run_dir
        dirs[f"eval:{spec.name}"] = spec.eval_dir
        dirs[f"replay:{spec.name}"] = spec.replay_dir
    return dirs


def check_directory_plan(*, require_absent: bool = True) -> Dict[str, Any]:
    """Planned directories: unique; run / evaluation / replay / state trees pairwise disjoint; outside every
    historical run directory (runs/m7d above all); absent before the matrix starts (require_absent)."""
    dirs = planned_directories()
    problems: List[str] = []
    resolved = {k: Path(os.path.normpath(str(p))) for k, p in dirs.items()}
    if len(set(resolved.values())) != len(resolved):
        problems.append("two planned directories resolve to the same path")
    leaves = {k: p for k, p in resolved.items()
              if k.split(":")[0] in ("run", "eval", "replay") or k in ("random_baseline", "state")}
    items = sorted(leaves.items())
    for i, (ka, pa) in enumerate(items):
        for kb, pb in items[i + 1:]:
            if within(pa, pb) or within(pb, pa):
                problems.append(f"{ka} ({pa}) and {kb} ({pb}) overlap")
    historical = [p for p in HISTORICAL_ROOT.iterdir()] if HISTORICAL_ROOT.is_dir() else []
    historical = [p for p in historical if p.is_dir() and Path(os.path.normpath(str(p))) != resolved["matrix_root"]]
    for key, p in sorted(resolved.items()):
        for h in historical:
            hp = Path(os.path.normpath(str(h)))
            if within(p, hp):
                problems.append(f"{key} ({p}) lies inside the historical run directory {hp}")
    if require_absent:
        for key, p in sorted(resolved.items()):
            if p.exists():
                problems.append(f"{key} ({p}) already exists")
    m7d = Path(os.path.normpath(str(REPO_ROOT / "runs" / "m7d")))
    cannot_touch_m7d = not any(within(p, m7d) or within(m7d, p) for p in resolved.values())
    if not cannot_touch_m7d:
        problems.append("a planned M7e directory overlaps runs/m7d")
    return {"directories": {k: ec.repo_relative(p) for k, p in sorted(resolved.items())},
            "historical_directories": len(historical), "cannot_touch_m7d": cannot_touch_m7d,
            "require_absent": require_absent, "problems": problems, "ok": not problems}


def resume_guard(spec: RunSpec, checkpoint_dir: Path, exp: Optional[ec.Experiment] = None) -> Dict[str, Any]:
    """A resume may only continue the run's OWN lineage: same directory tree, run_id, semantic fingerprint (so the
    same seed, reward contract and budget) - never across seeds, contracts or runs. Reuses the M7d guard with the
    M7e matrix root."""
    return mm.resume_guard(spec, checkpoint_dir, exp or load_run(spec), matrix_root=MATRIX_ROOT)


# -- required values -------------------------------------------------------------------------------------------------


def required_value_checks(spec: RunSpec, exp: ec.Experiment) -> Dict[str, bool]:
    """Every frozen field of the M7e training contract, checked against the resolved profile."""
    v = exp.values
    return {
        "task": v["task.id"] == "ssb64_us_mario_btt_v1",
        "action_contract": v["contracts.action"] == "btt_s9_b8_v1",
        "observation_contract": v["contracts.observation"] == "btt_policy_obs_v1",
        "reward_contract_v2_unchanged": exp.reward.contract == REWARD_ID and exp.reward.canonical,
        "reward_values": (v["reward.target_broken"], v["reward.per_step"], v["reward.clear_bonus"],
                          v["reward.failure_penalty"]) == (1.0, -0.001, 10.0, -5.0),
        "process_count_5": exp.process_count == PROCESS_COUNT,
        "standby_on": exp.standby_preboot is True and exp.standby_count == 1,
        "max_game_processes_10": exp.max_game_processes == MAX_GAME_PROCESSES,
        "horizon_3600": v["environment.horizon"] == HORIZON,
        "transitions_3072000": v["run.total_transitions"] == TOTAL_TRANSITIONS,
        "rollout_geometry": (v["ppo.rollout_size"], v["ppo.n_steps"]) == (5120, 1024)
        and v["run.total_transitions"] % v["ppo.rollout_size"] == 0,
        "ppo": (v["ppo.n_steps"], v["ppo.batch_size"], v["ppo.n_epochs"], v["ppo.gamma"], v["ppo.gae_lambda"],
                v["ppo.learning_rate"]) == (1024, 512, 10, 0.999, 0.995, 3e-4),
        "mlp_64x64_tanh": (v["ppo.policy"], v["ppo.net_arch"], v["ppo.activation"]) == ("MlpPolicy", [64, 64], "tanh"),
        "ent_coef_zero": v["ppo.ent_coef"] == 0.0,
        "cpu_one_thread": (v["ppo.device"], v["ppo.torch_threads"]) == ("cpu", 1),
        "observation_only_vecnormalize": (v["ppo.vecnormalize.normalize_observations"],
                                         v["ppo.vecnormalize.normalize_rewards"]) == (True, False),
        "fresh_initialisation": exp.mode != "resume" and exp.resume_source is None,
        "seed": v["run.base_seed"] == spec.seed,
        "no_in_process_evaluation": (v["evaluation.interval"], v["evaluation.initial"], v["evaluation.final"])
        == (0, False, False),
        "checkpoint_cadence": (v["checkpoint.interval"], v["checkpoint.initial"]) == (CHECKPOINT_INTERVAL, True),
        "curve_episode_counts": (v["evaluation.deterministic_episodes"], v["evaluation.stochastic_episodes"])
        == (CURVE_EPISODES["deterministic"], CURVE_EPISODES["stochastic"]),
        "evaluation_seed": v["evaluation.seed"] == EVAL_SEED,
        "random_baseline_episodes": v["evaluation.random_baseline_episodes"] == RANDOM_BASELINE_EPISODES,
        "artifacts": (v["artifacts.periodic_episodes"], v["artifacts.retain_failed_cap"]) == (10, 20),
        "run_dir": exp.run_dir == spec.run_dir,
        "output_root_is_m7e": exp.run_dir.parent == MATRIX_ROOT,
        "m6_flags": dict(exp.extra_env) == {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1"},
    }


# -- the manifest ----------------------------------------------------------------------------------------------------


def build_manifest(*, with_trainer_view: bool = True) -> Dict[str, Any]:
    """The resolved experiment matrix: every resolved field, the equivalence proofs, the trainer configuration, the
    post-hoc evaluation plan, the plateau rule and the eight pre-registered gates."""
    specs = matrix()
    problems: List[str] = []
    exps: Dict[str, ec.Experiment] = {}
    runs: Dict[str, Any] = {}
    plans: Dict[str, List[Dict[str, Any]]] = {}
    trainer: Dict[str, Any] = {}
    canon = ec.load_experiment(CANONICAL_V2)
    m7d: Dict[str, ec.Experiment] = {}
    for s in specs:
        exp = load_run(s)
        exps[s.name] = exp
        checks = required_value_checks(s, exp)
        bad = [k for k, ok in checks.items() if not ok]
        if bad:
            problems.append(f"{s.name}: required values violated: {bad}")
        runs[s.name] = {"seed": s.seed, "order_index": s.order_index, "reward": "v2",
                        "m7d_counterpart": s.m7d_counterpart,
                        "config": ec.repo_relative(s.config_path), "source_sha256": exp.source.sha256,
                        "source_size": exp.source.size,
                        "semantic_fingerprint": exp.semantic_fingerprint,
                        "compatibility_fingerprint": exp.compatibility_fingerprint,
                        "reward_contract": exp.reward.to_json(), "lifecycle": exp.lifecycle(),
                        "run_dir": ec.repo_relative(exp.run_dir), "eval_dir": ec.repo_relative(s.eval_dir),
                        "replay_dir": ec.repo_relative(s.replay_dir),
                        "checkpoint_sets": len(range(0, TOTAL_TRANSITIONS, CHECKPOINT_INTERVAL)),
                        "rollouts": TOTAL_TRANSITIONS // int(exp.values["ppo.rollout_size"]),
                        "required_value_checks": checks, "resolved": exp.resolved_json()}
        plans[s.name] = evaluation_plan(s, exp)
        if s.m7d_config_path.is_file():
            m7d[s.name] = ec.load_experiment(s.m7d_config_path)
        if with_trainer_view:
            trainer[s.name] = trainer_view(exp)
            digest, rms = expected_initial_policy_digest(exp, return_obs_rms=True)
            runs[s.name]["expected_initial_policy_digest"] = digest
            runs[s.name]["expected_initial_obs_rms_digest"] = rms
    # Profile pairs: the three M7e profiles must differ only in identity, seed, paths and derived hashes.
    pairs: Dict[str, Any] = {}
    for i, sa in enumerate(SEEDS):
        for sb in SEEDS[i + 1:]:
            a, b = exps[f"m7e_s{sa}_v2"], exps[f"m7e_s{sb}_v2"]
            d = field_diff(a.resolved_json(), b.resolved_json())
            entry: Dict[str, Any] = {"runs": [a.name, b.name], "resolved_diff": d,
                                     "resolved_proof": classify(d, PROFILE_ALLOWED),
                                     "same_compatibility_fingerprint":
                                     a.compatibility_fingerprint == b.compatibility_fingerprint,
                                     "different_semantic_fingerprint":
                                     a.semantic_fingerprint != b.semantic_fingerprint,
                                     "different_base_seed": a.values["run.base_seed"] != b.values["run.base_seed"],
                                     "compatibility_differences": sorted(ec.compare_compatibility(
                                         ec.compatibility_view_from_values(a.values, a.reward, dict(a.extra_env)),
                                         ec.compatibility_view_from_values(b.values, b.reward, dict(b.extra_env))))}
            if with_trainer_view:
                td = field_diff(trainer[a.name], trainer[b.name])
                entry["trainer_diff"] = td
                entry["trainer_proof"] = classify(td, TRAINER_ALLOWED)
                entry["different_initial_policy"] = (runs[a.name]["expected_initial_policy_digest"]
                                                     != runs[b.name]["expected_initial_policy_digest"])
                if not entry["different_initial_policy"]:
                    problems.append(f"seeds {sa}/{sb}: the untrained policies are identical (seeding is not working)")
            ed = [field_diff(x, y) for x, y in zip(plans[a.name], plans[b.name], strict=True)]
            merged: Dict[str, Any] = {}
            for item in ed:
                merged.update(item)
            entry["evaluation_plan_proof"] = classify(merged, EVAL_ALLOWED)
            entry["evaluation_plan_points"] = [len(plans[a.name]), len(plans[b.name])]
            for key in ("resolved_proof", "trainer_proof", "evaluation_plan_proof"):
                if key in entry and not entry[key]["proof_ok"]:
                    problems.append(f"seeds {sa}/{sb}: {key} unexpected diffs {entry[key]['unexpected']}")
            if not entry["same_compatibility_fingerprint"] or not entry["different_semantic_fingerprint"] \
                    or entry["compatibility_differences"]:
                problems.append(f"seeds {sa}/{sb}: fingerprint expectations violated {entry['compatibility_differences']}")
            pairs[f"s{sa}_vs_s{sb}"] = entry
    # Each M7e profile against its M7d reward-v2 counterpart: only the budget, the cadence, the curve counts and
    # identity / paths / hashes may differ.
    vs_m7d: Dict[str, Any] = {}
    for s in specs:
        if s.name not in m7d:
            vs_m7d[s.name] = {"available": False, "m7d_config": ec.repo_relative(s.m7d_config_path)}
            problems.append(f"{s.name}: the M7d counterpart profile {s.m7d_config_path} is missing")
            continue
        old, new = m7d[s.name], exps[s.name]
        d = field_diff(old.resolved_json(), new.resolved_json())
        proof = classify(d, VS_M7D_ALLOWED)
        entry = {"available": True, "m7d_config": ec.repo_relative(s.m7d_config_path),
                 "m7d_run_dir": ec.repo_relative(old.run_dir), "resolved_diff": d, "proof": proof,
                 "same_base_seed": old.values["run.base_seed"] == new.values["run.base_seed"] == s.seed,
                 "same_reward_contract": old.reward.to_json() == new.reward.to_json(),
                 "m7d_total_transitions": int(old.values["run.total_transitions"]),
                 "m7e_total_transitions": int(new.values["run.total_transitions"]),
                 "budget_multiple": int(new.values["run.total_transitions"])
                 / int(old.values["run.total_transitions"]),
                 "compatibility_differences": sorted(ec.compare_compatibility(
                     ec.compatibility_view_from_values(old.values, old.reward, dict(old.extra_env)),
                     ec.compatibility_view_from_values(new.values, new.reward, dict(new.extra_env))))}
        if not proof["proof_ok"]:
            problems.append(f"{s.name} vs {s.m7d_counterpart}: unexpected diffs {proof['unexpected']}")
        if not entry["same_base_seed"] or not entry["same_reward_contract"]:
            problems.append(f"{s.name} vs {s.m7d_counterpart}: seed or reward contract differs")
        vs_m7d[s.name] = entry
    # Each M7e profile against the canonical M7c standby v2 profile (the reward-contract ancestor).
    vs_canonical: Dict[str, Any] = {}
    for s in specs:
        new = exps[s.name]
        d = field_diff(canon.resolved_json(), new.resolved_json())
        vs_canonical[s.name] = {
            "canonical": ec.repo_relative(CANONICAL_V2), "differing_paths": sorted(d),
            "same_reward_contract": canon.reward.to_json() == new.reward.to_json(),
            "reward_paths_differ": [p for p in d if p.startswith(("config.reward", "resolved.reward",
                                                                  "config.contracts.reward"))],
            "compatibility_differences": sorted(ec.compare_compatibility(
                ec.compatibility_view_from_values(canon.values, canon.reward, dict(canon.extra_env)),
                ec.compatibility_view_from_values(new.values, new.reward, dict(new.extra_env))))}
        if not vs_canonical[s.name]["same_reward_contract"] or vs_canonical[s.name]["reward_paths_differ"]:
            problems.append(f"{s.name} vs the canonical v2 profile: the reward contract is not identical")
    if with_trainer_view:
        per_seed = {s.seed: runs[s.name]["expected_initial_policy_digest"] for s in specs}
        if len(set(per_seed.values())) != len(SEEDS):
            problems.append(f"two seeds produce the same untrained policy: {per_seed}")
    # No M7d checkpoint can be a training source.
    resume_sources = {s.name: exps[s.name].resume_source for s in specs}
    if any(v is not None for v in resume_sources.values()):
        problems.append(f"a profile declares a resume source: {resume_sources}")
    census = evaluation_census_plan()
    if not census["reconciles"]:
        problems.append(f"the evaluation census does not reconcile with the proposal's 3,055 episodes: {census}")
    directory_plan = check_directory_plan(require_absent=False)
    problems.extend(directory_plan["problems"])
    exe = exps[specs[0].name].executable_fingerprint()
    manifest = {
        "schema": MATRIX_SCHEMA,
        "milestone": MILESTONE,
        "phase": PHASE,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "purpose": "bounded extension of the provisionally selected btt_reward_v2 contract from 1,024,000 to "
                   "3,072,000 transitions per seed, to determine whether unchanged reward v2 and unchanged PPO "
                   "continue learning beyond the M7d budget, produce the first verified clear, or reach a "
                   "defensible plateau",
        "authority": {"proposal": ec.repo_relative(PROPOSAL_DOC), "diagnosis": ec.repo_relative(DIAGNOSIS_DOC),
                      "note": "the committed Phase A proposal is authoritative for the checkpoint cadence, the "
                              "evaluation counts, the artifact settings, the decision gates, the resource "
                              "estimates and the stopping rules"},
        "what_changes_from_m7d": {
            "behavioural": "the transition budget only (1,024,000 -> 3,072,000 per seed)",
            "measurement_consequence": "the checkpoint cadence (51,200 -> 102,400, keeping 30 sets over the larger "
                                       "budget and aligning every evaluated point with a saved set) and the "
                                       "intermediate evaluation episode counts (20 -> 60 stochastic, 2 -> 5 "
                                       "deterministic)",
            "unchanged": ["reward identity and values", "PPO hyperparameters", "action contract",
                          "observation contract", "horizon", "N", "lifecycle", "normalisation", "seeds",
                          "artifact policy"],
            "excluded_in_any_form": ["route hints", "target order hints", "TAS demonstrations",
                                     "target-distance shaping", "hardcoded movement",
                                     "hidden termination changes", "reward v3", "RNG seed checking"],
        },
        "seeds": {"values": list(SEEDS), "canonical_seed": 0,
                  "selection": "the same three seeds as M7d, so every M7e point is paired with an M7d point at the "
                               "same seed",
                  "scope": "Python / NumPy / PyTorch / SB3 only; never reaches the game",
                  "derived": "SB3/PPO seed = base_seed (network initialisation, action sampling, minibatch order); "
                             "worker and vector-reset seeds = base_seed + rank (0-4, 1-5, 2-6 overlap across base "
                             "seeds, but they only seed worker-side Python/NumPy/Gymnasium generators that never "
                             "influence actions or gameplay)",
                  "native_rng": "no native RNG state is introduced, inspected, logged, validated, controlled, "
                                "compared or hashed anywhere in M7e"},
        "order": [{"index": s.order_index, "run": s.name, "seed": s.seed} for s in specs],
        "sequencing": "strictly sequential, never two PPO experiments at once; the proposal registers no order other "
                      "than seeds 0, 1, 2",
        "budget": {"per_seed": TOTAL_TRANSITIONS, "hard_maximum": True,
                   "checkpoint_interval": CHECKPOINT_INTERVAL,
                   "checkpoint_sets_per_run": len(range(0, TOTAL_TRANSITIONS, CHECKPOINT_INTERVAL)),
                   "rollouts_per_run": TOTAL_TRANSITIONS // 5120,
                   "derivation": "proposal section 6.2: about 1.22M transitions to bring the slowest seed to the "
                                 "entropy level v1 already reached, plus at least 0.8M afterwards during which a "
                                 "flattening curve can be measured; 3 x 1.024M because 1.024M is the M7d unit"},
        "executable": exe,
        "canonical_profile": {"path": ec.repo_relative(CANONICAL_V2), "source_sha256": canon.source.sha256,
                              "semantic_fingerprint": canon.semantic_fingerprint,
                              "compatibility_fingerprint": canon.compatibility_fingerprint},
        "runs": runs,
        "profile_pairs": pairs,
        "vs_m7d": vs_m7d,
        "vs_canonical_v2": vs_canonical,
        "fresh_models": {"policy": "fresh PPO models, not resumes of the M7d runs; the M7d runs and their "
                                   "checkpoints, statistics and artifacts are preserved untouched",
                         "resume_sources_declared": {k: (v if v is None else str(v))
                                                     for k, v in resume_sources.items()},
                         "no_m7d_checkpoint_is_a_training_source": all(v is None for v in resume_sources.values()),
                         "verified_after_each_run": "ckpt_000000000 is compared against the offline fresh "
                                                    "construction of the same profile (expected_initial_* above)"},
        "trainer_config": trainer if with_trainer_view else None,
        "evaluation_protocol": {
            "where": "after all training completes, in a separate process, on saved checkpoint sets - so evaluation "
                     "can never reseed training and the process count can never exceed 10",
            "points_per_seed": census["evaluated_points_per_seed"], "interval": EVAL_INTERVAL,
            "initial_and_final": FINAL_EPISODES, "intermediate": CURVE_EPISODES,
            "seed": EVAL_SEED, "workers": PROCESS_COUNT,
            "lifecycle": "standby (as in training), at most 10 game processes",
            "vecnormalize": "frozen: training=False, norm_reward=False, statistics of the evaluated checkpoint, "
                            "never updated",
            "preservation": "every evaluation episode keeps its canonical native-action artifact (preserve_all), so "
                            "the M7e action-stream analysis can be rerun exactly as the Phase A one was",
            "census": census,
            "random_baseline": {"episodes": RANDOM_BASELINE_EPISODES, "seed": EVAL_SEED, "workers": PROCESS_COUNT,
                                "cross_check": ec.repo_relative(M7A_RANDOM_BASELINE)},
            "plan": plans,
        },
        "first_clear_protocol": {
            "preserve": "immediately and unconditionally, with the full canonical native action stream, metadata, "
                        "both observations and the checkpoint that produced it, regardless of any other "
                        "preservation rule",
            "two_clocks": "completion_time_passed and completion_input_tick are recorded as two separate values; "
                          "neither is collapsed into the other nor decremented",
            "native_revalidation": "the canonical actions are replayed on a fresh process from tick 0 through the "
                                   "existing replay_one path (fresh state, initial observation, every consumed_tick, "
                                   "the final observation including host_frame, the target count, both completion "
                                   "clocks and cleared_natively). A clear that does not reproduce is a clear "
                                   "CANDIDATE, never a verified clear",
            "baseline_comparison": "only after native re-validation, against completion_time_passed = 446 / "
                                   "completion_input_tick = 447 as separate clocks",
            "training_not_stopped": True,
        },
        "plateau_rule": PLATEAU_RULE,
        "decision_gates": list(GATES),
        "gate_ordering": GATE_ORDERING,
        "objective_ranking": list(OBJECTIVE_RANKING),
        "stopping_rules": STOPPING_RULES,
        "directory_plan": directory_plan,
        "limits": {"max_game_processes": MAX_GAME_PROCESSES, "reward_normalization": False,
                   "evaluation_inside_learn": False, "video_recording": False,
                   "resume_scope": "a run's own lineage only: same semantic fingerprint, seed and reward contract; "
                                   "never across seeds, contracts or runs"},
        "problems": problems,
        "ok": not problems,
    }
    return manifest


# -- tests ------------------------------------------------------------------------------------------------------------


def _tests() -> int:
    """Definition tests of the matrix itself (no training, no game, no PyTorch)."""
    failures: List[str] = []

    def check(ok: bool, label: str) -> None:
        print(f"  {'ok  ' if ok else 'FAIL'} {label}")
        if not ok:
            failures.append(label)

    print("m7e_matrix definitions")
    specs = matrix()
    check([s.name for s in specs] == ["m7e_s0_v2", "m7e_s1_v2", "m7e_s2_v2"], "three runs, seeds 0/1/2 in order")
    check([s.order_index for s in specs] == [1, 2, 3], "1-based sequential order")
    check(all(s.config_path.is_file() for s in specs), "every profile file exists")
    check(all(s.m7d_config_path.is_file() for s in specs), "every M7d counterpart profile exists")
    pts = evaluated_points()
    check(len(pts) == 11 and pts[0] == 0 and pts[-1] == TOTAL_TRANSITIONS, "11 evaluated points, 0 .. 3,072,000")
    check(pts[1:-1] == [307_200 * k for k in range(1, 10)], "9 intermediate points at 307,200")
    check(all(p % CHECKPOINT_INTERVAL == 0 for p in pts), "every evaluated point aligns with a checkpoint set")
    check(TOTAL_TRANSITIONS % 5120 == 0 and TOTAL_TRANSITIONS // 5120 == 600, "600 rollouts of 5,120")
    check(CHECKPOINT_INTERVAL % 5120 == 0 and len(range(0, TOTAL_TRANSITIONS, CHECKPOINT_INTERVAL)) == 30,
          "30 checkpoint sets at 102,400")
    cen = evaluation_census_plan()
    check(cen["stochastic_per_seed"] == 740, "740 stochastic episodes per seed")
    check(cen["deterministic_per_seed"] == 245, "245 deterministic episodes per seed")
    check(cen["per_seed"] == 985 and cen["model_episodes"] == 2955, "985 per seed, 2,955 over three seeds")
    check(cen["total_episodes"] == 3055 and cen["reconciles"], "3,055 with the 100-episode random baseline")
    check(cen["sessions"]["total"] == 67, "67 evaluation sessions (2 x 11 x 3 + 1)")
    plateau_points = pts[-PLATEAU_WINDOW_POINTS:]
    check(plateau_points[0] == 1_536_000 and plateau_points[-1] == TOTAL_TRANSITIONS
          and plateau_points[-1] - plateau_points[0] == 1_536_000,
          "the plateau window is 1,536,000 .. 3,072,000, spanning 1,536,000")
    check(len(GATES) == 8 and [g["gate"] for g in GATES] == list(range(1, 9)), "eight gates, numbered 1..8")
    check([g["key"] for g in GATES if g["gate"] in (1, 2, 4)]
          == ["verified_clear", "better_targets_no_clear", "plateau"], "gates 1, 2, 4 are the exclusive triple")
    check(GATES[7]["pre_empts"] == "all others", "gate 8 pre-empts all others")
    check(MAX_GAME_PROCESSES == 10, "maximum 10 game processes")
    dp = check_directory_plan(require_absent=False)
    check(dp["cannot_touch_m7d"], "no planned directory can touch runs/m7d")
    check(not [p for p in dp["problems"] if "already exists" not in p], f"directory plan clean ({dp['problems']})")
    for s in specs:
        exp = load_run(s)
        bad = [k for k, ok in required_value_checks(s, exp).items() if not ok]
        check(not bad, f"{s.name}: frozen contract values ({bad})")
        plan = evaluation_plan(s, exp)
        check(len(plan) == 11, f"{s.name}: 11 planned evaluations")
        check(sum(int(p["stochastic_episodes"]) for p in plan) == 740
              and sum(int(p["deterministic_episodes"]) for p in plan) == 245,
              f"{s.name}: planned episode counts match the census")
        check(all(p["frozen_vecnormalize"] and p["preserve_all"] for p in plan),
              f"{s.name}: every evaluation is frozen and preserves every episode")
        check(all(str(p["out_dir"]).startswith("_eval/") for p in plan), f"{s.name}: evaluation output under _eval/")
    a, b = load_run(specs[0]), load_run(specs[1])
    d = field_diff(a.resolved_json(), b.resolved_json())
    pr = classify(d, PROFILE_ALLOWED)
    check(pr["proof_ok"], f"s0 vs s1 differ only in the allowed categories ({pr['unexpected']})")
    check(a.compatibility_fingerprint == b.compatibility_fingerprint, "seeds share the compatibility fingerprint")
    check(a.semantic_fingerprint != b.semantic_fingerprint, "seeds differ in the semantic fingerprint")
    old = ec.load_experiment(specs[0].m7d_config_path)
    dm = field_diff(old.resolved_json(), a.resolved_json())
    pm = classify(dm, VS_M7D_ALLOWED)
    check(pm["proof_ok"], f"m7e_s0_v2 vs m7d_s0_v2 differ only in the allowed categories ({pm['unexpected']})")
    check(old.reward.to_json() == a.reward.to_json(), "the reward contract is byte-identical to M7d's v2")
    check(a.resume_source is None and a.mode != "resume", "fresh initialisation, no resume source")
    print(f"m7e_matrix: {'all definition tests passed' if not failures else str(len(failures)) + ' FAILED'}")
    return 0 if not failures else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="M7e Phase B matrix definitions and guards")
    ap.add_argument("--test", action="store_true", help="definition tests only (no game, no PyTorch)")
    ap.add_argument("--manifest", action="store_true", help="print the manifest to stdout")
    ap.add_argument("--no-trainer-view", action="store_true", help="skip the PyTorch-dependent trainer view")
    args = ap.parse_args(list(argv) if argv is not None else None)
    if args.test:
        return _tests()
    if args.manifest:
        man = build_manifest(with_trainer_view=not args.no_trainer_view)
        json.dump(man, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return 0 if man["ok"] else 1
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
