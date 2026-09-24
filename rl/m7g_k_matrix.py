#!/usr/bin/env python3
"""M7g Phase K: the controlled btt_policy_obs_v1 versus btt_policy_obs_v2_spatial matrix, its manifest and guards.

    python rl/m7g_k_run.py manifest          # writes docs/rl_obs_v2_phase_k_manifest_m7g.json

The pre-registered design is docs/rl_obs_v2_experiment_proposal_m7g.md (revision 2); the profiles are the reviewable
TOMLs under rl/configs/m7g/ (six comparison runs, four extension runs used only if gate 6 fires, two pilot runs under
rl/configs/m7g/pilot/). This module only names the matrix, resolves and proves it, and guards it:

- identity of every run: arm (observation contract, policy class, network, VecNormalize keys, native flags), seed,
  profile sources and fingerprints, the untrained policy / statistics digests built through the trainer's own
  helpers, the executable, the parent and submodule revisions and a fingerprint of the Python code that trains and
  evaluates (rl/*.py, tests excluded);
- field-by-field proofs: each v1 run equals the M7e run of its seed except output fields; each v2 run equals the v1
  run of its seed except contracts.observation and ppo.policy; each extension run equals the seed-0 run of its arm
  except run.name, run.notes and run.base_seed; each pilot run equals the seed-0 run of its arm except run.name,
  run.mode, run.notes, run.total_transitions and run.output_root;
- the post-hoc evaluation plan (M7e's protocol, both arms, with the evaluation-only metrics recorder and its
  SSB64_RL_TARGET_DIAG=1 flag) and its census: 3 seeds 5,910 + 100 random = 6,010 episodes; with the extension
  3,940 more = 9,950;
- output isolation: planned directories unique, disjoint, under runs/m7g_k only, never inside a historical run tree.

Reused unchanged from rl/m7d_matrix.py / rl/m7e_matrix.py: flatten, field_diff, classify, trainer_view,
historical_snapshot, compare_snapshots, within, read_json, write_json, MatrixError and the M7e protocol constants.

Standard library + experiment_config at module level (no PyTorch): digests import the trainer lazily. No native RNG
state is introduced, inspected, logged, validated, controlled, compared or hashed; seeds are Python / NumPy /
PyTorch / SB3 only. The M7g-a crossing fixtures are never read here.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import experiment_config as ec  # noqa: E402
import m7d_matrix as mm  # noqa: E402  (no torch at module level)
import m7e_matrix as em  # noqa: E402  (no torch at module level)

MatrixError = mm.MatrixError
flatten = mm.flatten
field_diff = mm.field_diff
classify = mm.classify
trainer_view = mm.trainer_view
historical_snapshot = mm.historical_snapshot
compare_snapshots = mm.compare_snapshots
within = mm.within
read_json = mm.read_json
write_json = mm.write_json

REPO_ROOT = ec.REPO_ROOT
MILESTONE = "M7g"
PHASE = "K"
MATRIX_SCHEMA = "battleship_m7g_k_matrix_v1"
CONFIG_DIR = REPO_ROOT / "rl" / "configs" / "m7g"
PILOT_CONFIG_DIR = CONFIG_DIR / "pilot"
M7E_CONFIG_DIR = REPO_ROOT / "rl" / "configs" / "m7e"
MANIFEST_DOC = REPO_ROOT / "docs" / "rl_obs_v2_phase_k_manifest_m7g.json"
PROPOSAL_DOC = REPO_ROOT / "docs" / "rl_obs_v2_experiment_proposal_m7g.md"
HISTORICAL_ROOT = REPO_ROOT / "runs"
DEFAULT_MATRIX_ROOT = REPO_ROOT / "runs" / "m7g_k"
MAX_GAME_PROCESSES = mm.MAX_GAME_PROCESSES        # 10 = N=5 x (1 active + 1 standby)

# -- arms ---------------------------------------------------------------------------------------------------------------
ARMS: Tuple[str, ...] = ("v1", "v2")
OBSERVATION = {"v1": "btt_policy_obs_v1", "v2": "btt_policy_obs_v2_spatial"}
POLICY = {"v1": "MlpPolicy", "v2": "MultiInputPolicy"}
POLICY_CLASS = {"v1": "ActorCriticPolicy", "v2": "MultiInputActorCriticPolicy"}
PARAMETERS = {"v1": 11_538, "v2": 76_818}
V2_CONTRACT_SHA256 = "dcfd14b276c3d9f38f180888c132febb67ace39797bdef2aefb185e024c8c0cb"
V2_NETWORK_ID = "btt_policy_net_v2_multiinput_mlp64"
M6_FLAGS = {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1"}
ARM_FLAGS = {"v1": dict(M6_FLAGS), "v2": dict(M6_FLAGS, SSB64_RL_SPATIAL="1")}
EVAL_METRICS_FLAG = {"SSB64_RL_TARGET_DIAG": "1"}   # evaluation workers only (btt_eval_metrics_v1)

# -- seeds and the pre-registered order ----------------------------------------------------------------------------------
SEEDS: Tuple[int, ...] = (0, 1, 2)
EXTENSION_SEEDS: Tuple[int, ...] = (3, 4)
# Strictly sequential. Counterbalanced ABBA order within seeds (M7d's precedent) so that neither arm always runs first
# and slow drift of the machine cannot line up with the arm.
ORDER: Tuple[Tuple[int, str], ...] = ((0, "v1"), (0, "v2"), (1, "v2"), (1, "v1"), (2, "v1"), (2, "v2"))
EXTENSION_ORDER: Tuple[Tuple[int, str], ...] = ((3, "v1"), (3, "v2"), (4, "v2"), (4, "v1"))
PILOT_ORDER: Tuple[Tuple[str, int], ...] = (("v1", 102_400), ("v2", 204_800))

# -- the frozen training contract (identical to M7e's; proposal section 3) ----------------------------------------------
TOTAL_TRANSITIONS = em.TOTAL_TRANSITIONS          # 3,072,000, hard maximum per run
CHECKPOINT_INTERVAL = em.CHECKPOINT_INTERVAL      # 102,400
HORIZON = em.HORIZON                              # 3,600
PROCESS_COUNT = em.PROCESS_COUNT                  # 5
EVAL_INTERVAL = em.EVAL_INTERVAL                  # 307,200 -> 11 evaluated points per run
FINAL_EPISODES = dict(em.FINAL_EPISODES)          # initial and final: 100 deterministic + 100 stochastic
CURVE_EPISODES = dict(em.CURVE_EPISODES)          # each intermediate point: 5 + 60
RANDOM_BASELINE_EPISODES = em.RANDOM_BASELINE_EPISODES
EVAL_SEED = em.EVAL_SEED
MAX_RUNS = len(ORDER) + len(EXTENSION_ORDER)      # 10
MAX_TRANSITIONS = MAX_RUNS * TOTAL_TRANSITIONS    # 30,720,000

# -- roots (redirectable for tests; the profiles' run.output_root is overridden when a root is redirected) ---------------
_ROOT = DEFAULT_MATRIX_ROOT


def matrix_root() -> Path:
    return _ROOT


def configure_root(root: Optional[Path]) -> Path:
    """Tests only: move the whole Phase K tree (runs, state, evaluations, pilot) below `root`."""
    global _ROOT
    _ROOT = Path(root).resolve() if root is not None else DEFAULT_MATRIX_ROOT
    return _ROOT


def state_dir() -> Path:
    return _ROOT / "_matrix"


def eval_root() -> Path:
    return _ROOT / "_eval"


def clears_root() -> Path:
    return _ROOT / "_clears"


def pilot_root() -> Path:
    return _ROOT / "_pilot"


def partial_root() -> Path:
    return _ROOT / "_partial"


# -- the runs ------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RunSpec:
    seed: int
    arm: str
    order_index: int
    extension: bool = False
    pilot_total: Optional[int] = None   # set for the two pilot runs only

    @property
    def pilot(self) -> bool:
        return self.pilot_total is not None

    @property
    def name(self) -> str:
        return f"m7g_pilot_s{self.seed}_{self.arm}" if self.pilot else f"m7g_s{self.seed}_{self.arm}"

    @property
    def config_path(self) -> Path:
        return (PILOT_CONFIG_DIR if self.pilot else CONFIG_DIR) / f"{self.name}.toml"

    @property
    def run_dir(self) -> Path:
        return (pilot_root() if self.pilot else _ROOT) / self.name

    @property
    def eval_dir(self) -> Path:
        return (pilot_root() / "_eval" if self.pilot else eval_root()) / self.name

    @property
    def clears_dir(self) -> Path:
        return (pilot_root() / "_clears" if self.pilot else clears_root()) / self.name

    @property
    def m7e_counterpart(self) -> Optional[Path]:
        if self.arm == "v1" and self.seed in SEEDS and not self.extension and not self.pilot:
            return M7E_CONFIG_DIR / f"m7e_s{self.seed}_v2.toml"
        return None

    @property
    def total_transitions(self) -> int:
        return int(self.pilot_total) if self.pilot else TOTAL_TRANSITIONS


def matrix(*, include_extension: bool = False) -> List[RunSpec]:
    specs = [RunSpec(seed=s, arm=a, order_index=i) for i, (s, a) in enumerate(ORDER, 1)]
    if include_extension:
        specs += [RunSpec(seed=s, arm=a, order_index=len(ORDER) + i, extension=True)
                  for i, (s, a) in enumerate(EXTENSION_ORDER, 1)]
    return specs


def extension_specs() -> List[RunSpec]:
    return [s for s in matrix(include_extension=True) if s.extension]


def pilot_specs() -> List[RunSpec]:
    return [RunSpec(seed=0, arm=a, order_index=i, pilot_total=t) for i, (a, t) in enumerate(PILOT_ORDER, 1)]


def run_by_name(name: str) -> RunSpec:
    for spec in matrix(include_extension=True) + pilot_specs():
        if spec.name == name:
            return spec
    raise MatrixError(f"{name!r} is not a Phase K run")


def load_run(spec: RunSpec) -> ec.Experiment:
    """The profile, with run.output_root redirected when the matrix root is (tests)."""
    exp = ec.load_experiment(spec.config_path)
    if _ROOT != DEFAULT_MATRIX_ROOT:
        exp = exp.with_overrides({"run.output_root": str(spec.run_dir.parent)})
    return exp


# -- identity -----------------------------------------------------------------------------------------------------------


def arm_checks(spec: RunSpec, exp: ec.Experiment) -> Dict[str, bool]:
    """Every identity and frozen-contract fact of one run, checked against its resolved profile."""
    v = exp.values
    po = exp.policy_observation()
    checks = {
        "name": exp.name == spec.name,
        "seed": v["run.base_seed"] == spec.seed,
        "observation_contract": v["contracts.observation"] == OBSERVATION[spec.arm],
        "policy": v["ppo.policy"] == POLICY[spec.arm],
        "native_flags": dict(exp.extra_env) == ARM_FLAGS[spec.arm],
        "observation_identity": (po is None) if spec.arm == "v1" else (
            po is not None and po["contract_sha256"] == V2_CONTRACT_SHA256 and po["network_id"] == V2_NETWORK_ID
            and po["norm_obs_keys"] == ["segment_geometry", "state", "target_geometry"]
            and po["unnormalized_keys"] == ["segment_kind", "target_live"]),
        "network": (v["ppo.net_arch"], v["ppo.activation"]) == ([64, 64], "tanh"),
        "task": v["task.id"] == "ssb64_us_mario_btt_v1",
        "action_contract": v["contracts.action"] == "btt_s9_b8_v1",
        "reward_v2_unchanged": exp.reward.contract == "btt_reward_v2" and exp.reward.canonical and
        (v["reward.target_broken"], v["reward.per_step"], v["reward.clear_bonus"], v["reward.failure_penalty"])
        == (1.0, -0.001, 10.0, -5.0),
        "no_reward_normalisation": (v["ppo.vecnormalize.normalize_observations"],
                                    v["ppo.vecnormalize.normalize_rewards"]) == (True, False),
        "process_count_5_standby": exp.process_count == PROCESS_COUNT and exp.standby_preboot and exp.standby_count == 1
        and exp.max_game_processes == MAX_GAME_PROCESSES,
        "horizon": v["environment.horizon"] == HORIZON,
        "budget": v["run.total_transitions"] == spec.total_transitions,
        "rollout_geometry": (v["ppo.rollout_size"], v["ppo.n_steps"], v["ppo.batch_size"], v["ppo.n_epochs"])
        == (5120, 1024, 512, 10),
        "ppo": (v["ppo.learning_rate"], v["ppo.gamma"], v["ppo.gae_lambda"], v["ppo.clip_range"], v["ppo.ent_coef"],
                v["ppo.vf_coef"], v["ppo.max_grad_norm"]) == (3e-4, 0.999, 0.995, 0.2, 0.0, 0.5, 0.5),
        "cpu_one_thread": (v["ppo.device"], v["ppo.torch_threads"]) == ("cpu", 1),
        "fresh_start": exp.mode != "resume" and exp.resume_source is None,
        "no_in_process_evaluation": (v["evaluation.interval"], v["evaluation.initial"], v["evaluation.final"])
        == (0, False, False),
        "checkpoint_cadence": (v["checkpoint.interval"], v["checkpoint.initial"]) == (CHECKPOINT_INTERVAL, True),
        "evaluation_protocol": (v["evaluation.deterministic_episodes"], v["evaluation.stochastic_episodes"],
                                v["evaluation.seed"], v["evaluation.random_baseline_episodes"])
        == (CURVE_EPISODES["deterministic"], CURVE_EPISODES["stochastic"], EVAL_SEED, RANDOM_BASELINE_EPISODES),
        "run_dir": exp.run_dir == spec.run_dir,
    }
    return checks


def expected_initial_digests(exp: ec.Experiment) -> Tuple[str, str]:
    """(policy parameter digest, statistics digest) of the untrained model a fresh run of this profile must save as
    ckpt_000000000: built with the trainer's own helpers (make_vecnormalize, make_model) around an offline vector env
    with the arm's spaces. Depends only on the seed, the spaces and the network, never on the game."""
    import gymnasium as gym
    import numpy as np
    import torch
    from stable_baselines3.common.vec_env import DummyVecEnv

    import m7_trainer as tr
    import m7g_obs as mo
    from btt_learning import make_policy_observation_space, make_track1_action_space
    from m7_evaluation import obs_rms_digest, policy_parameter_digest

    cfg = tr.config_from_experiment(exp)
    space = mo.make_observation_space() if cfg.observation_v2 else make_policy_observation_space()

    class _Spaces(gym.Env):
        def __init__(self) -> None:
            self.observation_space = space
            self.action_space = make_track1_action_space()

        def _zero(self) -> Any:
            if isinstance(space, gym.spaces.Dict):
                return {k: np.zeros(s.shape, dtype=np.float32) for k, s in space.spaces.items()}
            return np.zeros(space.shape, dtype=np.float32)

        def reset(self, *, seed=None, options=None):
            super().reset(seed=seed)
            return self._zero(), {}

        def step(self, action):
            return self._zero(), 0.0, False, False, {}

    threads = torch.get_num_threads()
    torch.set_num_threads(int(cfg.torch_threads))
    try:
        vecnorm = tr.make_vecnormalize(cfg, DummyVecEnv([_Spaces for _ in range(cfg.n_envs)]))
        model = tr.make_model(cfg, vecnorm)
        out = (policy_parameter_digest(model), obs_rms_digest(vecnorm))
        vecnorm.close()
    finally:
        torch.set_num_threads(threads)
    return out


CODE_EXCLUDED_SUFFIXES = ("_tests.py", "_smoke.py")


def code_fingerprint() -> Dict[str, Any]:
    """sha256 over every Python module under rl/ that trains, evaluates or orchestrates (test / smoke scripts
    excluded) plus every Phase K profile: the exact code a campaign ran with."""
    files = sorted(p for p in (REPO_ROOT / "rl").glob("*.py") if not p.name.endswith(CODE_EXCLUDED_SUFFIXES))
    files += sorted(CONFIG_DIR.glob("*.toml")) + sorted(PILOT_CONFIG_DIR.glob("*.toml"))
    agg = hashlib.sha256()
    per: Dict[str, str] = {}
    for p in files:
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        rel = p.relative_to(REPO_ROOT).as_posix()
        per[rel] = h
        agg.update(f"{rel}\0{h}\n".encode("utf-8"))
    return {"files": len(files), "sha256": agg.hexdigest(), "per_file": per}


def revisions() -> Dict[str, Any]:
    """Parent HEAD, submodule commits and dirty state (m7_runtime.repository_revisions), without the file list."""
    from m7_runtime import repository_revisions

    r = repository_revisions()
    return {"head": r.get("head"), "dirty": r.get("dirty"),
            "submodules": {s["path"]: s["commit"] for s in r.get("submodules") or []},
            "submodules_differ_from_index": [s["path"] for s in r.get("submodules") or [] if s.get("differs_from_index")]}


# -- the evaluation plan and its census -------------------------------------------------------------------------------


def evaluation_plan(spec: RunSpec, exp: ec.Experiment) -> List[Dict[str, Any]]:
    """M7e's post-hoc protocol for every run of both arms (proposal section 4): initial, every 307,200 transitions,
    final; 100 + 100 at initial and final, 60 stochastic + 5 deterministic at each intermediate point; seed 12345;
    frozen statistics; every episode preserved; the evaluation-only metrics recorder on (SSB64_RL_TARGET_DIAG=1)."""
    if spec.pilot:
        raise MatrixError(f"{spec.name}: pilot runs have their own small evaluation (m7g_k_run.py pilot)")
    v = exp.values
    total = int(v["run.total_transitions"])
    if total != TOTAL_TRANSITIONS:
        raise MatrixError(f"{spec.name}: total_transitions {total} != {TOTAL_TRANSITIONS}")
    flags = dict(exp.extra_env, **EVAL_METRICS_FLAG)
    common = {"seed": int(v["evaluation.seed"]), "workers": exp.eval_workers, "horizon": int(v["environment.horizon"]),
              "extra_env": flags, "standby_preboot": exp.standby_preboot, "standby_count": exp.standby_count,
              "frozen_vecnormalize": True, "preserve_all": True, "eval_metrics": True,
              "observation": OBSERVATION[spec.arm], "reward_contract": exp.reward.contract, "run": spec.name,
              "arm": spec.arm}
    plan = [dict(common, label="initial", checkpoint=f"{spec.name}/checkpoints/ckpt_000000000", num_timesteps=0,
                 deterministic_episodes=FINAL_EPISODES["deterministic"],
                 stochastic_episodes=FINAL_EPISODES["stochastic"])]
    for t in em.evaluated_points(total)[1:-1]:
        plan.append(dict(common, label=f"curve_t{t:09d}", checkpoint=f"{spec.name}/checkpoints/ckpt_{t:09d}",
                         num_timesteps=t, deterministic_episodes=int(v["evaluation.deterministic_episodes"]),
                         stochastic_episodes=int(v["evaluation.stochastic_episodes"])))
    plan.append(dict(common, label="final", checkpoint=f"{spec.name}/final", num_timesteps=total,
                     deterministic_episodes=FINAL_EPISODES["deterministic"],
                     stochastic_episodes=FINAL_EPISODES["stochastic"]))
    return plan


def evaluation_census_plan(*, include_extension: bool = False) -> Dict[str, Any]:
    per_seed = em.evaluation_census_plan()["per_seed"]                  # 985 = 740 stochastic + 245 deterministic
    runs = len(matrix(include_extension=include_extension))
    model = runs * per_seed
    total = model + RANDOM_BASELINE_EPISODES
    expected = 9_950 if include_extension else 6_010
    return {"runs": runs, "per_run": per_seed, "model_episodes": model,
            "random_baseline_episodes": RANDOM_BASELINE_EPISODES, "total_episodes": total,
            "arithmetic": f"{runs} runs x {per_seed} + {RANDOM_BASELINE_EPISODES} random = {total}",
            "registered_total": expected, "reconciles": total == expected,
            "sessions": 2 * len(em.evaluated_points()) * runs + 1}


# -- directories ------------------------------------------------------------------------------------------------------


def planned_directories(*, include_extension: bool = True) -> Dict[str, Path]:
    dirs: Dict[str, Path] = {"matrix_root": _ROOT, "state": state_dir(), "eval_root": eval_root(),
                             "clears_root": clears_root(), "pilot_root": pilot_root(), "partial_root": partial_root(),
                             "random_baseline": eval_root() / "random_baseline"}
    for spec in matrix(include_extension=include_extension) + pilot_specs():
        dirs[f"run:{spec.name}"] = spec.run_dir
        dirs[f"eval:{spec.name}"] = spec.eval_dir
        dirs[f"clears:{spec.name}"] = spec.clears_dir
    return dirs


def check_directory_plan(*, require_absent: bool = False) -> Dict[str, Any]:
    """Unique; run / evaluation / clear-verification / state leaves pairwise disjoint; everything below the Phase K
    root; the root never inside or around a historical run tree; optionally absent."""
    dirs = planned_directories()
    problems: List[str] = []
    resolved = {k: Path(os.path.normpath(str(p))) for k, p in dirs.items()}
    if len(set(resolved.values())) != len(resolved):
        problems.append("two planned directories resolve to the same path")
    leaves = {k: p for k, p in resolved.items()
              if k.split(":")[0] in ("run", "eval", "clears") or k in ("random_baseline", "state", "partial_root")}
    items = sorted(leaves.items())
    for i, (ka, pa) in enumerate(items):
        for kb, pb in items[i + 1:]:
            if within(pa, pb) or within(pb, pa):
                problems.append(f"{ka} and {kb} overlap")
    root = resolved["matrix_root"]
    for k, p in resolved.items():
        if not within(p, root):
            problems.append(f"{k} ({p}) lies outside the Phase K root {root}")
    if _ROOT == DEFAULT_MATRIX_ROOT and HISTORICAL_ROOT.is_dir():
        for h in HISTORICAL_ROOT.iterdir():
            hp = Path(os.path.normpath(str(h)))
            if h.is_dir() and hp != root and (within(root, hp) or within(hp, root)):
                problems.append(f"the Phase K root overlaps the historical tree {hp}")
    for spec in matrix(include_extension=True) + pilot_specs():
        exp = load_run(spec)
        if exp.run_dir != spec.run_dir or exp.name != spec.name:
            problems.append(f"{spec.name}: profile resolves to {exp.name} / {exp.run_dir}, planned {spec.run_dir}")
    existing = sorted(k for k, p in resolved.items() if k.startswith(("run:", "eval:", "clears:")) and p.exists())
    if require_absent and existing:
        problems.append(f"planned directories already exist (never overwritten): {existing}")
    return {"directories": {k: ec.repo_relative(p) for k, p in sorted(resolved.items())}, "existing": existing,
            "require_absent": require_absent, "problems": problems, "ok": not problems}


# -- proofs -------------------------------------------------------------------------------------------------------------

V1_VS_M7E_ALLOWED: Dict[str, Tuple[str, ...]] = {
    "run_identity": ("config.run.name", "config.run.notes"),
    "output_paths": ("config.run.output_root", "resolved.output_root", "resolved.run_dir", "source.path"),
    "derived_hashes": ("fingerprints.source_sha256", "source.sha256", "source.size"),
}
V2_VS_V1_ALLOWED: Dict[str, Tuple[str, ...]] = {
    "observation_arm": ("config.contracts.observation", "config.ppo.policy", "resolved.extra_env.SSB64_RL_SPATIAL")
    + tuple(f"resolved.policy_observation.{k}" for k in (
        "contract", "contract_sha256", "flat_size", "key_order", "native_flags.SSB64_RL_SPATIAL", "network_id",
        "norm_obs_keys", "policy", "schema_version", "unnormalized_keys")),
    "run_identity": ("config.run.name", "config.run.notes"),
    "output_paths": ("resolved.run_dir", "source.path"),
    "derived_hashes": ("fingerprints.source_sha256", "fingerprints.semantic_fingerprint",
                       "fingerprints.compatibility_fingerprint", "source.sha256", "source.size"),
}
EXTENSION_ALLOWED: Dict[str, Tuple[str, ...]] = {
    "seed": ("config.run.base_seed",),
    "run_identity": ("config.run.name", "config.run.notes"),
    "output_paths": ("resolved.run_dir", "source.path"),
    "derived_hashes": ("fingerprints.source_sha256", "fingerprints.semantic_fingerprint", "source.sha256",
                       "source.size"),
}
PILOT_ALLOWED: Dict[str, Tuple[str, ...]] = {
    "pilot_identity": ("config.run.name", "config.run.mode", "config.run.notes"),
    "pilot_budget": ("config.run.total_transitions", "resolved.rollouts"),
    "output_paths": ("config.run.output_root", "resolved.output_root", "resolved.run_dir", "source.path"),
    "derived_hashes": ("fingerprints.source_sha256", "fingerprints.semantic_fingerprint", "source.sha256",
                       "source.size"),
}


def _proof(a: ec.Experiment, b: ec.Experiment, allowed: Mapping[str, Sequence[str]]) -> Dict[str, Any]:
    d = field_diff(a.resolved_json(), b.resolved_json())
    return {"runs": [a.name, b.name], "differing_paths": sorted(d), "proof": classify(d, allowed),
            "compatibility_differences": sorted(ec.compare_compatibility(a.compatibility_view(), b.compatibility_view()))}


# -- the manifest -------------------------------------------------------------------------------------------------------

DECISION_RULE = {
    "rule_id": "m7g_k_decision_rule_rev2",
    "registered": "docs/rl_obs_v2_experiment_proposal_m7g.md section 6 (revision 2, 2026-09-23), before any Phase K "
                  "training or evaluation data existed",
    "implemented_by": "rl/m7g_k_analysis.py decide()",
    "gate_order": "0 pre-empts; then 1 -> 7, the first whose condition holds decides",
    "extension": {"seeds": list(EXTENSION_SEEDS), "arms": list(ARMS), "runs": len(EXTENSION_ORDER),
                  "transitions": len(EXTENSION_ORDER) * TOTAL_TRANSITIONS,
                  "evaluation_episodes": len(EXTENSION_ORDER) * em.evaluation_census_plan()["per_seed"],
                  "applications": 1, "trigger": "gate 6 at n = 3 (including single-seed clears / crossings, gates 3 "
                                                "and 4d)"},
    "maximum": {"runs": MAX_RUNS, "transitions": MAX_TRANSITIONS, "policy_evaluation_episodes": 9_850,
                "random_baseline_episodes": RANDOM_BASELINE_EPISODES},
}


def build_manifest(*, with_digests: bool = True) -> Dict[str, Any]:
    problems: List[str] = []
    specs = matrix(include_extension=True)
    pilots = pilot_specs()
    exps: Dict[str, ec.Experiment] = {s.name: load_run(s) for s in specs + pilots}
    runs: Dict[str, Any] = {}
    plans: Dict[str, Any] = {}
    for s in specs + pilots:
        exp = exps[s.name]
        checks = arm_checks(s, exp)
        bad = [k for k, ok in checks.items() if not ok]
        if bad:
            problems.append(f"{s.name}: identity / frozen values violated: {bad}")
        runs[s.name] = {"seed": s.seed, "arm": s.arm, "order_index": s.order_index, "extension": s.extension,
                        "pilot": s.pilot, "config": ec.repo_relative(s.config_path),
                        "source_sha256": exp.source.sha256, "semantic_fingerprint": exp.semantic_fingerprint,
                        "compatibility_fingerprint": exp.compatibility_fingerprint,
                        "observation": OBSERVATION[s.arm], "policy": POLICY[s.arm],
                        "policy_class": POLICY_CLASS[s.arm], "parameters": PARAMETERS[s.arm],
                        "policy_observation": exp.policy_observation(), "native_flags": dict(exp.extra_env),
                        "total_transitions": s.total_transitions, "run_dir": ec.repo_relative(s.run_dir),
                        "eval_dir": ec.repo_relative(s.eval_dir), "arm_checks": checks}
        if with_digests:
            d, rms = expected_initial_digests(exp)
            runs[s.name]["expected_initial_policy_digest"] = d
            runs[s.name]["expected_initial_obs_rms_digest"] = rms
        if not s.pilot:
            plans[s.name] = evaluation_plan(s, exp)
    proofs: Dict[str, Any] = {}
    for s in specs + pilots:
        exp = exps[s.name]
        if s.m7e_counterpart is not None:
            m7e = ec.load_experiment(s.m7e_counterpart)
            p = _proof(m7e, exp, V1_VS_M7E_ALLOWED)
            p["same_semantic_fingerprint"] = m7e.semantic_fingerprint == exp.semantic_fingerprint
            p["same_compatibility_fingerprint"] = m7e.compatibility_fingerprint == exp.compatibility_fingerprint
            proofs[f"{s.name}_vs_m7e"] = p
            if not (p["proof"]["proof_ok"] and p["same_semantic_fingerprint"] and p["same_compatibility_fingerprint"]):
                problems.append(f"{s.name} vs M7e: {p['proof']['unexpected']} (fingerprints equal: "
                                f"{p['same_semantic_fingerprint']}/{p['same_compatibility_fingerprint']})")
        if s.arm == "v2" and not s.pilot:
            p = _proof(exps[f"m7g_s{s.seed}_v1"], exp, V2_VS_V1_ALLOWED)
            proofs[f"{s.name}_vs_v1"] = p
            if not p["proof"]["proof_ok"] or set(p["compatibility_differences"]) != \
                    {"contracts.observation", "ppo.policy", "environment.extra_env"}:
                problems.append(f"{s.name} vs v1: {p['proof']['unexpected']} {p['compatibility_differences']}")
        if s.extension:
            p = _proof(exps[f"m7g_s0_{s.arm}"], exp, EXTENSION_ALLOWED)
            proofs[f"{s.name}_vs_s0"] = p
            if not p["proof"]["proof_ok"] or p["compatibility_differences"]:
                problems.append(f"{s.name} vs seed 0: {p['proof']['unexpected']} {p['compatibility_differences']}")
        if s.pilot:
            p = _proof(exps[f"m7g_s0_{s.arm}"], exp, PILOT_ALLOWED)
            proofs[f"{s.name}_vs_s0"] = p
            if not p["proof"]["proof_ok"] or p["compatibility_differences"]:
                problems.append(f"{s.name} vs seed 0: {p['proof']['unexpected']} {p['compatibility_differences']}")
    if with_digests:
        for arm in ARMS:
            per_seed = {s.seed: runs[s.name]["expected_initial_policy_digest"] for s in specs if s.arm == arm}
            if len(set(per_seed.values())) != len(per_seed):
                problems.append(f"{arm}: two seeds build the same untrained policy {per_seed}")
            pilot = runs[f"m7g_pilot_s0_{arm}"]["expected_initial_policy_digest"]
            if pilot != runs[f"m7g_s0_{arm}"]["expected_initial_policy_digest"]:
                problems.append(f"{arm}: the pilot's untrained policy differs from the seed-0 run's")
    census = evaluation_census_plan()
    census_ext = evaluation_census_plan(include_extension=True)
    if not (census["reconciles"] and census_ext["reconciles"]):
        problems.append(f"evaluation census does not reconcile: {census['arithmetic']} / {census_ext['arithmetic']}")
    directory_plan = check_directory_plan()
    problems.extend(directory_plan["problems"])
    exe = exps[specs[0].name].executable_fingerprint()
    if not exe.get("exists"):
        problems.append("the executable is missing")
    return {
        "schema": MATRIX_SCHEMA, "milestone": MILESTONE, "phase": PHASE,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "authority": ec.repo_relative(PROPOSAL_DOC),
        "question": "does structured perception (btt_policy_obs_v2_spatial) change what PPO learns at the M7e budget, "
                    "everything else held constant",
        "arms": {a: {"observation": OBSERVATION[a], "policy": POLICY[a], "policy_class": POLICY_CLASS[a],
                     "parameters": PARAMETERS[a], "native_flags": ARM_FLAGS[a]} for a in ARMS},
        "order": [{"index": s.order_index, "run": s.name, "seed": s.seed, "arm": s.arm} for s in matrix()],
        "extension_order": [{"index": s.order_index, "run": s.name, "seed": s.seed, "arm": s.arm}
                            for s in extension_specs()],
        "pilot_order": [{"index": s.order_index, "run": s.name, "arm": s.arm, "transitions": s.total_transitions}
                        for s in pilots],
        "sequencing": "strictly sequential, one training process at a time, in the registered order; the extension "
                      "only after the recorded n = 3 decision is gate 6; the pilot before everything",
        "executable": exe,
        "revisions": revisions(),
        "code": {k: v for k, v in code_fingerprint().items() if k != "per_file"},
        "runs": runs,
        "proofs": proofs,
        "evaluation_protocol": {"plan": plans, "census": census, "census_with_extension": census_ext,
                                "metrics": "btt_eval_metrics_v1 (rl/m7g_eval_metrics.py) on every evaluation episode "
                                           "of both arms and the random baseline; SSB64_RL_TARGET_DIAG=1 in evaluation "
                                           "workers only",
                                "clear_verification": "every cleared episode (deduplicated by native action digest) "
                                                      "is replayed natively on a fresh process from tick 0 "
                                                      "(m7d_run.replay_one); completion_time_passed and "
                                                      "completion_input_tick are compared as two values"},
        "decision_rule": DECISION_RULE,
        "directory_plan": directory_plan,
        "limits": {"max_game_processes": MAX_GAME_PROCESSES, "max_runs": MAX_RUNS, "max_transitions": MAX_TRANSITIONS,
                   "reward_normalization": False, "evaluation_inside_learn": False},
        "problems": problems,
        "ok": not problems,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-digests", action="store_true")
    args = ap.parse_args(argv)
    man = build_manifest(with_digests=not args.no_digests)
    print(f"manifest ok={man['ok']} problems={man['problems']}")
    return 0 if man["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
