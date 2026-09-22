#!/usr/bin/env python3
"""M7d: the controlled reward-v1 versus reward-v2 experiment matrix, its manifest and its guards.

    python rl/m7d_run.py manifest            # writes docs/rl_reward_comparison_m7d_manifest.json

Six fresh PPO runs on the M7c standby stack (N=5, 1,024,000 transitions,
3,600-tick horizon, observation-only VecNormalize): three paired seeds x two
reward contracts. The profiles are the explicit, reviewable TOMLs under
rl/configs/m7d/; every behavioural value comes from them (rl/experiment_config.py
validates, resolves and fingerprints them). This module only:

- names the matrix (seeds, rewards, counterbalanced order, directories);
- builds the resolved comparison manifest: every resolved field of every run,
  a field-by-field diff of every seed pair (v1 versus v2), of every run against
  its canonical M7c standby profile and across seeds, the trainer configuration
  each run will receive, the post-hoc evaluation plan and the pre-registered
  decision rule, with an explicit proof that a pair differs only in the reward
  identity and definition, the run identity, output paths and derived hashes;
- guards the matrix: planned directories are unique, disjoint and new, the
  historical run tree is fingerprinted and must stay byte-identical, and a
  resume may only continue a run's own lineage (same semantic fingerprint,
  seed and reward contract).

Standard library + rl/experiment_config.py only at module level (no PyTorch):
the trainer-configuration view imports rl/m7_trainer.py lazily.
No native RNG inspection, logging, validation, control, comparison or hashing
exists here; seeds are Python / NumPy / PyTorch / SB3 only.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import experiment_config as ec  # noqa: E402

REPO_ROOT = ec.REPO_ROOT
MILESTONE = "M7d"
MATRIX_SCHEMA = "battleship_m7d_matrix_v1"
CONFIG_DIR = REPO_ROOT / "rl" / "configs" / "m7d"
CANONICAL = {"v1": REPO_ROOT / "rl" / "configs" / "m7_mario_us_reward_v1_standby.toml",
             "v2": REPO_ROOT / "rl" / "configs" / "m7_mario_us_reward_v2_standby.toml"}
REWARD_IDS = {"v1": "btt_reward_v1", "v2": "btt_reward_v2"}
SEEDS: Tuple[int, ...] = (0, 1, 2)          # the canonical profiles' base_seed (0) and the two adjacent valid seeds
REWARDS: Tuple[str, ...] = ("v1", "v2")
# Counterbalanced execution order (user-specified): seed A v1 -> v2, seed B v2 -> v1, seed C v1 -> v2.
ORDER: Tuple[Tuple[int, str], ...] = ((0, "v1"), (0, "v2"), (1, "v2"), (1, "v1"), (2, "v1"), (2, "v2"))
MATRIX_ROOT = REPO_ROOT / "runs" / "m7d"
STATE_DIR = MATRIX_ROOT / "_matrix"
EVAL_ROOT = MATRIX_ROOT / "_eval"
REPLAY_ROOT = MATRIX_ROOT / "_replay"
MANIFEST_DOC = REPO_ROOT / "docs" / "rl_reward_comparison_m7d_manifest.json"
HISTORICAL_ROOT = REPO_ROOT / "runs"
MAX_GAME_PROCESSES = 10                     # N=5 x (1 active + 1 standby)

# -- post-hoc evaluation protocol (M7d; recorded in the manifest before any training) ------------------------
FINAL_EPISODES = {"deterministic": 100, "stochastic": 100}     # initial (ckpt_000000000) and final sets
CURVE_INTERVAL = 102_400                                        # the canonical evaluation cadence, evaluated post hoc
RANDOM_BASELINE_EPISODES = 100
M7A_RANDOM_BASELINE = REPO_ROOT / "runs" / "m7a_random_baseline" / "evaluation_summary.json"

# -- pre-registered decision rule (fixed before any M7d training data exists) --------------------------------
NON_INFERIORITY_TARGETS = 0.5      # targets per episode (5 % of the task)
IDLE_TAIL_TICKS = 1800             # a horizon episode with >= 1800 ticks after its last target break (or no break) idles
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_LEVEL = 0.95
DECISION_RULE: Dict[str, Any] = {
    "rule_id": "m7d_decision_rule_v1",
    "registered": "2026-09-22, before any M7d training (approved by the user in the M7d Phase A review)",
    "primary_endpoint": "final stochastic policy, 100 evaluation episodes per model, seeds 0/1/2, objective ranking "
                        "(verified clear > more targets > faster completion_time_passed); reward is never consulted",
    "definitions": {
        "D_s": "mean targets broken (v2) - mean targets broken (v1) for seed s, 95 % percentile bootstrap CI "
               "(independent resampling of each run's episodes)",
        "F_s": "fall rate (v2) - fall rate (v1) for seed s, 95 % bootstrap CI",
        "C_s": "verified clears (v2) - verified clears (v1) for seed s",
        "D, F": "mean over seeds of D_s / F_s with a seed-stratified bootstrap CI (episodes resampled within each run)",
        "C": "sum of C_s",
        "idle episode": f"horizon-truncated episode whose last target break (or tick 0 if none) is >= {IDLE_TAIL_TICKS} "
                        "ticks before its end",
        "I": "idle-episode rate (v2) - idle-episode rate (v1), seed-stratified bootstrap CI",
        "margin": NON_INFERIORITY_TARGETS,
    },
    "v1_retained_if_any": [
        "C < 0 (v2 has fewer verified clears in aggregate)",
        "CI(D) upper bound < 0 (v2 breaks significantly fewer targets)",
        f"D < -{NON_INFERIORITY_TARGETS} and CI(F) upper bound < 0 (v2 trades targets for survival)",
    ],
    "v2_preferred_if_no_v1_condition_and_any": [
        "C > 0 and no seed with C_s < 0 (more verified clears)",
        "CI(D) lower bound > 0 and CI(D_s) lower bound > 0 in at least 2 of 3 seeds (significantly more targets)",
        f"CI(D) lower bound > -{NON_INFERIORITY_TARGETS} (non-inferior targets) and C >= 0 and CI(F) upper bound < 0 and "
        "CI(F_s) upper bound < 0 in at least 2 of 3 seeds (fewer falls) and CI(I) lower bound <= 0 (no significant "
        "increase of idle episodes)",
    ],
    "otherwise": "inconclusive - more evidence required",
    "secondary_reported_not_decisive": ["deterministic (argmax) outcome per seed", "learning curves by transitions",
                                         "idle / conservative metrics", "throughput and lifecycle",
                                         "diagnostic reward (not comparable across contracts)"],
    "bootstrap": {"resamples": BOOTSTRAP_RESAMPLES, "level": BOOTSTRAP_LEVEL, "method": "percentile", "seed": 0},
}


class MatrixError(RuntimeError):
    """The matrix, its manifest or one of its guards is violated."""


@dataclass(frozen=True)
class RunSpec:
    seed: int
    reward: str          # "v1" | "v2"
    order_index: int     # 1-based position in the counterbalanced execution order

    @property
    def name(self) -> str:
        return f"m7d_s{self.seed}_{self.reward}"

    @property
    def config_path(self) -> Path:
        return CONFIG_DIR / f"{self.name}.toml"

    @property
    def canonical_path(self) -> Path:
        return CANONICAL[self.reward]

    @property
    def partner(self) -> str:
        return f"m7d_s{self.seed}_{'v2' if self.reward == 'v1' else 'v1'}"

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
    """The six runs in execution order."""
    return [RunSpec(seed=s, reward=r, order_index=i) for i, (s, r) in enumerate(ORDER, 1)]


def run_by_name(name: str) -> RunSpec:
    for spec in matrix():
        if spec.name == name:
            return spec
    raise MatrixError(f"{name!r} is not an M7d matrix run ({[s.name for s in matrix()]})")


def load_run(spec: RunSpec) -> ec.Experiment:
    return ec.load_experiment(spec.config_path)


# -- flattening and diffs ------------------------------------------------------------------------------------------


def flatten(data: Any, prefix: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if isinstance(data, Mapping):
        for k, v in data.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, Mapping) and v:
                out.update(flatten(v, key))
            else:
                out[key] = v
    else:
        out[prefix] = data
    return out


def field_diff(a: Mapping[str, Any], b: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    fa, fb = flatten(a), flatten(b)
    return {k: {"a": fa.get(k), "b": fb.get(k)} for k in sorted(set(fa) | set(fb)) if fa.get(k) != fb.get(k)}


# Every path that may differ between the two runs of one seed, by category. Anything else is a violation.
PAIR_ALLOWED: Dict[str, Tuple[str, ...]] = {
    "reward_identity_and_definition": ("config.contracts.reward", "config.reward.failure_penalty",
                                       "resolved.reward.contract", "resolved.reward.failure_penalty"),
    "run_identity": ("config.run.name", "config.run.notes"),
    "output_paths": ("resolved.run_dir", "source.path"),
    "derived_hashes": ("fingerprints.source_sha256", "fingerprints.semantic_fingerprint",
                       "fingerprints.compatibility_fingerprint", "source.sha256", "source.size"),
}
# M7d run versus its canonical M7c standby profile (same reward).
CANONICAL_ALLOWED: Dict[str, Tuple[str, ...]] = {
    "seed": ("config.run.base_seed",),
    "run_identity": ("config.run.name", "config.run.notes"),
    "output_paths": ("config.run.output_root", "resolved.output_root", "resolved.run_dir", "source.path"),
    "post_hoc_evaluation": ("config.evaluation.interval", "config.evaluation.initial", "config.evaluation.final"),
    "derived_hashes": ("fingerprints.source_sha256", "fingerprints.semantic_fingerprint", "source.sha256", "source.size"),
}
# Two seeds of the same reward.
SEED_ALLOWED: Dict[str, Tuple[str, ...]] = {
    "seed": ("config.run.base_seed",),
    "run_identity": ("config.run.name", "config.run.notes"),
    "output_paths": ("resolved.run_dir", "source.path"),
    "derived_hashes": ("fingerprints.source_sha256", "fingerprints.semantic_fingerprint", "source.sha256"),
}
# Trainer configuration (m7_trainer.M7Config.to_json) of the two runs of one seed.
TRAINER_PAIR_ALLOWED: Dict[str, Tuple[str, ...]] = {
    "reward_identity_and_definition": ("reward.contract", "reward.failure_penalty", "experiment.reward_contract",
                                       "experiment.reward_values.failure_penalty"),
    "run_identity": ("run_id", "experiment.name"),
    "output_paths": ("experiment.source.path",),
    "derived_hashes": ("experiment.source.sha256", "experiment.semantic_fingerprint",
                       "experiment.compatibility_fingerprint"),
}
# Post-hoc evaluation plan entries of the two runs of one seed.
EVAL_PAIR_ALLOWED: Dict[str, Tuple[str, ...]] = {
    "reward_identity_and_definition": ("reward_contract",),
    "run_identity": ("run",),
    "output_paths": ("checkpoint", "out_dir"),
}


def classify(diff: Mapping[str, Any], allowed: Mapping[str, Sequence[str]]) -> Dict[str, Any]:
    by_cat: Dict[str, List[str]] = {c: [] for c in allowed}
    unexpected: List[str] = []
    lookup = {p: c for c, paths in allowed.items() for p in paths}
    for path in diff:
        cat = lookup.get(path)
        if cat is None:
            unexpected.append(path)
        else:
            by_cat[cat].append(path)
    return {"differing_paths": len(diff), "by_category": by_cat, "unexpected": unexpected, "proof_ok": not unexpected}


# -- trainer and evaluation views ------------------------------------------------------------------------------------


def trainer_view(exp: ec.Experiment) -> Dict[str, Any]:
    """The configuration the trainer would receive (m7_trainer.config_from_experiment(...).to_json())."""
    import m7_trainer as tr  # lazy: PyTorch

    cfg = tr.config_from_experiment(exp)
    cfg.validate()
    view = cfg.to_json()
    view.pop("experiment", None)
    view["experiment"] = {k: v for k, v in exp.summary().items() if k not in ("cli_overrides",)}
    return view


def expected_initial_policy_digest(exp: ec.Experiment, *, return_obs_rms: bool = False) -> Any:
    """The parameter digest the untrained policy of this profile must have (ckpt_000000000 of a fresh run).

    Built exactly as m7_trainer.M7Run builds a fresh model (observation-only VecNormalize, then M7PPO with the
    profile's PPO values, policy_kwargs and seed) around an offline vector environment with the worker stack's
    spaces (btt_policy_obs_v1 Box(15) float32, Track 1 MultiDiscrete([9, 8])): the initial parameters depend only on
    the seed, the spaces and the network settings, never on the reward contract or the game."""
    import gymnasium as gym
    import numpy as np
    import torch
    from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

    import m7_trainer as tr
    from btt_learning import make_policy_observation_space, make_track1_action_space
    from m7_evaluation import obs_rms_digest, policy_parameter_digest

    class _Spaces(gym.Env):
        def __init__(self) -> None:
            self.observation_space = make_policy_observation_space()
            self.action_space = make_track1_action_space()

        def reset(self, *, seed=None, options=None):
            super().reset(seed=seed)
            return np.zeros(self.observation_space.shape, dtype=np.float32), {}

        def step(self, action):
            return np.zeros(self.observation_space.shape, dtype=np.float32), 0.0, False, False, {}

    cfg = tr.config_from_experiment(exp)
    threads = torch.get_num_threads()
    torch.set_num_threads(int(cfg.torch_threads))
    try:
        venv = DummyVecEnv([_Spaces for _ in range(cfg.n_envs)])
        vecnorm = VecNormalize(venv, training=True, norm_obs=cfg.norm_obs, norm_reward=False, clip_obs=cfg.clip_obs,
                               gamma=cfg.gamma)
        model = tr.M7PPO(tr.POLICY, vecnorm, learning_rate=cfg.learning_rate, n_steps=cfg.n_steps,
                         batch_size=cfg.batch_size, n_epochs=cfg.n_epochs, gamma=cfg.gamma, gae_lambda=cfg.gae_lambda,
                         clip_range=cfg.clip_range, ent_coef=cfg.ent_coef, vf_coef=cfg.vf_coef,
                         max_grad_norm=cfg.max_grad_norm, seed=cfg.base_seed, device=cfg.device, verbose=0,
                         policy_kwargs=tr.policy_kwargs(cfg))
        digest = policy_parameter_digest(model)
        rms = obs_rms_digest(vecnorm)
        vecnorm.close()
    finally:
        torch.set_num_threads(threads)
    return (digest, rms) if return_obs_rms else digest


def evaluation_plan(spec: RunSpec, exp: ec.Experiment) -> List[Dict[str, Any]]:
    """The post-hoc evaluations of one run (identical protocol for every run; only paths and identity differ)."""
    v = exp.values
    total = int(v["run.total_transitions"])
    common = {"seed": int(v["evaluation.seed"]), "workers": exp.eval_workers, "horizon": int(v["environment.horizon"]),
              "extra_env": dict(exp.extra_env), "standby_preboot": exp.standby_preboot,
              "standby_count": exp.standby_count, "frozen_vecnormalize": True, "preserve_all": True,
              "reward_contract": exp.reward.contract, "run": spec.name}
    plan = [dict(common, label="initial", checkpoint=f"{spec.name}/checkpoints/ckpt_000000000",
                 num_timesteps=0, deterministic_episodes=FINAL_EPISODES["deterministic"],
                 stochastic_episodes=FINAL_EPISODES["stochastic"], out_dir=f"_eval/{spec.name}/initial")]
    for t in range(CURVE_INTERVAL, total, CURVE_INTERVAL):
        plan.append(dict(common, label=f"curve_t{t:09d}", checkpoint=f"{spec.name}/checkpoints/ckpt_{t:09d}",
                         num_timesteps=t, deterministic_episodes=int(v["evaluation.deterministic_episodes"]),
                         stochastic_episodes=int(v["evaluation.stochastic_episodes"]),
                         out_dir=f"_eval/{spec.name}/curve_t{t:09d}"))
    plan.append(dict(common, label="final", checkpoint=f"{spec.name}/final", num_timesteps=total,
                     deterministic_episodes=FINAL_EPISODES["deterministic"],
                     stochastic_episodes=FINAL_EPISODES["stochastic"], out_dir=f"_eval/{spec.name}/final"))
    return plan


def planned_directories() -> Dict[str, Path]:
    dirs: Dict[str, Path] = {"matrix_root": MATRIX_ROOT, "state": STATE_DIR, "eval_root": EVAL_ROOT,
                             "replay_root": REPLAY_ROOT, "random_baseline": EVAL_ROOT / "random_baseline"}
    for spec in matrix():
        dirs[f"run:{spec.name}"] = spec.run_dir
        dirs[f"eval:{spec.name}"] = spec.eval_dir
        dirs[f"replay:{spec.name}"] = spec.replay_dir
    return dirs


# -- guards -----------------------------------------------------------------------------------------------------------


def within(child: Path, parent: Path) -> bool:
    """True when `child` is `parent` or lies below it (lexical, after normalisation)."""
    c, p = Path(os.path.normpath(str(child))), Path(os.path.normpath(str(parent)))
    try:
        c.relative_to(p)
        return True
    except ValueError:
        return False


def check_directory_plan(*, require_absent: bool = True) -> Dict[str, Any]:
    """Planned directories: unique; run / evaluation / replay / state trees pairwise disjoint; outside every
    historical run directory; absent before the matrix starts (require_absent)."""
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
    for k, p in resolved.items():
        for h in historical:
            if within(h, MATRIX_ROOT):
                continue   # the M7d tree itself
            if within(p, h) or within(h, p):
                problems.append(f"{k} ({p}) overlaps historical {h.name}")
    for spec in matrix():
        exp = load_run(spec)
        if exp.run_dir != spec.run_dir:
            problems.append(f"{spec.name}: profile run directory {exp.run_dir} != planned {spec.run_dir}")
        if exp.name != spec.name:
            problems.append(f"{spec.name}: profile run.name {exp.name!r}")
    existing = [k for k, p in resolved.items() if k.startswith(("run:", "eval:", "replay:")) and p.exists()]
    if require_absent and existing:
        problems.append(f"planned directories already exist (never overwritten): {existing}")
    return {"directories": {k: ec.repo_relative(p) for k, p in resolved.items()}, "problems": problems,
            "ok": not problems, "existing": existing}


def _walk_files(root: Path, exclude: Sequence[Path]) -> List[Tuple[str, Path]]:
    out: List[Tuple[str, Path]] = []
    ex = [Path(os.path.normpath(str(p))) for p in exclude]
    for dirpath, dirnames, filenames in os.walk(root):
        dp = Path(dirpath)
        keep = []
        for d in sorted(dirnames):
            full = dp / d
            if os.path.isjunction(full) or full.is_symlink():   # never descend into .tcc junctions
                continue
            if any(Path(os.path.normpath(str(full))) == e for e in ex):
                continue
            keep.append(d)
        dirnames[:] = keep
        for fn in sorted(filenames):
            full = dp / fn
            out.append((full.relative_to(root).as_posix(), full))
    return out


def historical_snapshot(*, root: Path = HISTORICAL_ROOT, exclude: Sequence[Path] = (MATRIX_ROOT,),
                        with_entries: bool = True) -> Dict[str, Any]:
    """Byte fingerprint of every historical file under runs/ (junctions not followed; the M7d tree excluded)."""
    t0 = time.perf_counter()
    agg = hashlib.sha256()
    entries: Dict[str, Dict[str, Any]] = {}
    total = 0
    for rel, path in _walk_files(Path(root), exclude):
        st = path.stat()
        h = hashlib.sha256()
        with open(path, "rb") as fp:
            for chunk in iter(lambda: fp.read(1 << 20), b""):
                h.update(chunk)
        digest = h.hexdigest()
        entries[rel] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": digest}
        agg.update(f"{rel}\0{st.st_size}\0{digest}\n".encode("utf-8"))
        total += st.st_size
    snap = {"root": ec.repo_relative(Path(root)), "excluded": [ec.repo_relative(p) for p in exclude],
            "files": len(entries), "bytes": total, "aggregate_sha256": agg.hexdigest(),
            "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "seconds": round(time.perf_counter() - t0, 2)}
    if with_entries:
        snap["entries"] = entries
    return snap


def compare_snapshots(before: Mapping[str, Any], after: Mapping[str, Any]) -> Dict[str, Any]:
    """Historical files must be byte-identical and unmoved (sha256, size and mtime); new files are reported."""
    eb, ea = before.get("entries") or {}, after.get("entries") or {}
    removed = sorted(set(eb) - set(ea))
    added = sorted(set(ea) - set(eb))
    changed = sorted(k for k in set(eb) & set(ea) if (eb[k]["sha256"], eb[k]["size"]) != (ea[k]["sha256"], ea[k]["size"]))
    touched = sorted(k for k in set(eb) & set(ea) if eb[k]["mtime_ns"] != ea[k]["mtime_ns"] and k not in changed)
    return {"identical": not removed and not changed and not touched, "removed": removed[:50], "changed": changed[:50],
            "mtime_changed": touched[:50], "added": added[:50], "added_count": len(added),
            "before_aggregate": before.get("aggregate_sha256"), "after_aggregate": after.get("aggregate_sha256")}


def resume_guard(spec: RunSpec, checkpoint_dir: Path, exp: Optional[ec.Experiment] = None, *,
                 matrix_root: Optional[Path] = None) -> Dict[str, Any]:
    """A resume may only continue the run's OWN lineage: the checkpoint must lie in the run's directory (or in one
    of its resumed continuations <name>_r<k>), carry the same semantic fingerprint (seed, reward, every behavioural
    value), the same base seed and the same reward contract. The generic M7b resume path permits a seed change;
    the M7d matrix does not. Raises MatrixError, returns the evidence."""
    exp = exp or load_run(spec)
    ckpt = Path(checkpoint_dir).resolve()
    meta_path = ckpt / "checkpoint.json"
    if not meta_path.is_file():
        raise MatrixError(f"{ckpt}: not a checkpoint set (checkpoint.json missing)")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    problems: List[str] = []
    root = Path(matrix_root) if matrix_root is not None else MATRIX_ROOT
    own_dirs = [root / spec.name] + [root / f"{spec.name}_r{k}" for k in range(1, 10)]
    if not any(within(ckpt, d.resolve()) for d in own_dirs):
        problems.append(f"checkpoint {ckpt} is not inside {spec.name}'s own lineage directories")
    run_id = str(meta.get("run_id") or "")
    if run_id != spec.name and not (run_id.startswith(spec.name + "_r") and run_id[len(spec.name) + 2:].isdigit()):
        problems.append(f"checkpoint run_id {run_id!r} is not {spec.name} or a resumed continuation of it")
    block = meta.get("experiment") or {}
    if block.get("semantic_fingerprint") != exp.semantic_fingerprint:
        problems.append(f"semantic fingerprint {str(block.get('semantic_fingerprint'))[:16]}... != profile "
                        f"{exp.semantic_fingerprint[:16]}... (seed, reward or another behavioural value differs)")
    seeds = meta.get("seeds") or {}
    if seeds.get("base_seed") != int(exp.values["run.base_seed"]):
        problems.append(f"checkpoint base_seed {seeds.get('base_seed')!r} != profile {exp.values['run.base_seed']}")
    contract = (meta.get("contracts") or {}).get("reward_contract")
    if contract != exp.reward.contract or block.get("reward_contract") != exp.reward.contract:
        problems.append(f"checkpoint reward contract {contract!r} / {block.get('reward_contract')!r} != "
                        f"{exp.reward.contract}")
    compat = ec.compare_compatibility(ec.checkpoint_compatibility_view(meta),
                                      ec.compatibility_view_from_values(exp.values, exp.reward, dict(exp.extra_env)))
    if compat:
        problems.append(f"compatibility diffs {sorted(compat)}")
    if problems:
        raise MatrixError(f"resume of {spec.name} from {ckpt} refused: " + "; ".join(problems))
    return {"run": spec.name, "checkpoint": ec.repo_relative(ckpt), "checkpoint_run_id": run_id,
            "num_timesteps": meta.get("num_timesteps"), "semantic_fingerprint": exp.semantic_fingerprint,
            "base_seed": seeds.get("base_seed"), "reward_contract": contract}


# -- manifest ----------------------------------------------------------------------------------------------------------


def build_manifest(*, with_trainer_view: bool = True) -> Dict[str, Any]:
    specs = matrix()
    exps = {s.name: load_run(s) for s in specs}
    canon = {r: ec.load_experiment(p) for r, p in CANONICAL.items()}
    problems: List[str] = []
    runs: Dict[str, Any] = {}
    trainer: Dict[str, Any] = {}
    plans: Dict[str, Any] = {}
    for s in specs:
        exp = exps[s.name]
        v = exp.values
        checks = {
            "task": v["task.id"] == "ssb64_us_mario_btt_v1",
            "process_count_5": exp.process_count == 5,
            "standby_on": exp.standby_preboot is True and exp.standby_count == 1,
            "max_game_processes_10": exp.max_game_processes == MAX_GAME_PROCESSES,
            "horizon_3600": v["environment.horizon"] == 3600,
            "transitions_1024000": v["run.total_transitions"] == 1_024_000,
            "ppo": (v["ppo.n_steps"], v["ppo.batch_size"], v["ppo.n_epochs"], v["ppo.gamma"], v["ppo.gae_lambda"],
                    v["ppo.learning_rate"]) == (1024, 512, 10, 0.999, 0.995, 3e-4),
            "mlp_64x64_tanh": (v["ppo.policy"], v["ppo.net_arch"], v["ppo.activation"]) == ("MlpPolicy", [64, 64], "tanh"),
            "cpu_one_thread": (v["ppo.device"], v["ppo.torch_threads"]) == ("cpu", 1),
            "observation_only_vecnormalize": (v["ppo.vecnormalize.normalize_observations"],
                                              v["ppo.vecnormalize.normalize_rewards"]) == (True, False),
            "fresh_initialisation": exp.mode != "resume" and exp.resume_source is None,
            "reward_contract": exp.reward.contract == REWARD_IDS[s.reward] and exp.reward.canonical,
            "seed": v["run.base_seed"] == s.seed,
            "no_in_process_evaluation": (v["evaluation.interval"], v["evaluation.initial"], v["evaluation.final"])
            == (0, False, False),
            "checkpoint_cadence": (v["checkpoint.interval"], v["checkpoint.initial"]) == (51200, True),
            "artifacts": (v["artifacts.periodic_episodes"], v["artifacts.retain_failed_cap"]) == (10, 20),
            "run_dir": exp.run_dir == s.run_dir,
            "m6_flags": dict(exp.extra_env) == {"SSB64_RL_NO_RENDER": "1", "SSB64_RAPHNET_DISABLE": "1"},
        }
        bad = [k for k, ok in checks.items() if not ok]
        if bad:
            problems.append(f"{s.name}: required values violated: {bad}")
        runs[s.name] = {"seed": s.seed, "reward": s.reward, "order_index": s.order_index, "partner": s.partner,
                        "config": ec.repo_relative(s.config_path), "source_sha256": exp.source.sha256,
                        "semantic_fingerprint": exp.semantic_fingerprint,
                        "compatibility_fingerprint": exp.compatibility_fingerprint,
                        "reward_contract": exp.reward.to_json(), "lifecycle": exp.lifecycle(),
                        "run_dir": ec.repo_relative(exp.run_dir), "required_value_checks": checks,
                        "resolved": exp.resolved_json()}
        plans[s.name] = evaluation_plan(s, exp)
        if with_trainer_view:
            trainer[s.name] = trainer_view(exp)
            digest, rms = expected_initial_policy_digest(exp, return_obs_rms=True)
            runs[s.name]["expected_initial_policy_digest"] = digest
            runs[s.name]["expected_initial_obs_rms_digest"] = rms
    pairs: Dict[str, Any] = {}
    for seed in SEEDS:
        a, b = exps[f"m7d_s{seed}_v1"], exps[f"m7d_s{seed}_v2"]
        d = field_diff(a.resolved_json(), b.resolved_json())
        entry: Dict[str, Any] = {"runs": [a.name, b.name], "resolved_diff": d,
                                 "resolved_proof": classify(d, PAIR_ALLOWED)}
        if with_trainer_view:
            td = field_diff(trainer[a.name], trainer[b.name])
            entry["trainer_diff"] = td
            entry["trainer_proof"] = classify(td, TRAINER_PAIR_ALLOWED)
        ed = [field_diff(x, y) for x, y in zip(plans[a.name], plans[b.name], strict=True)]
        merged: Dict[str, Any] = {}
        for item in ed:
            merged.update(item)
        entry["evaluation_plan_proof"] = classify(merged, EVAL_PAIR_ALLOWED)
        entry["same_base_seed"] = a.values["run.base_seed"] == b.values["run.base_seed"] == seed
        if with_trainer_view:
            entry["same_initial_policy"] = (runs[a.name]["expected_initial_policy_digest"]
                                            == runs[b.name]["expected_initial_policy_digest"]
                                            and runs[a.name]["expected_initial_obs_rms_digest"]
                                            == runs[b.name]["expected_initial_obs_rms_digest"])
            if not entry["same_initial_policy"]:
                problems.append(f"seed {seed} pair: the untrained policies differ")
        entry["same_compatibility_except_reward"] = sorted(ec.compare_compatibility(
            ec.compatibility_view_from_values(a.values, a.reward, dict(a.extra_env)),
            ec.compatibility_view_from_values(b.values, b.reward, dict(b.extra_env)))) == ["contracts.reward_resolved"]
        for key in ("resolved_proof", "trainer_proof", "evaluation_plan_proof"):
            if key in entry and not entry[key]["proof_ok"]:
                problems.append(f"seed {seed} pair: {key} unexpected diffs {entry[key]['unexpected']}")
        if not entry["same_base_seed"] or not entry["same_compatibility_except_reward"]:
            problems.append(f"seed {seed} pair: seed or compatibility mismatch")
        pairs[f"seed_{seed}"] = entry
    vs_canonical: Dict[str, Any] = {}
    for s in specs:
        d = field_diff(canon[s.reward].resolved_json(), exps[s.name].resolved_json())
        proof = classify(d, CANONICAL_ALLOWED)
        same_compat = exps[s.name].compatibility_fingerprint == canon[s.reward].compatibility_fingerprint
        same_semantic = exps[s.name].semantic_fingerprint == canon[s.reward].semantic_fingerprint
        vs_canonical[s.name] = {"canonical": ec.repo_relative(s.canonical_path), "resolved_diff": d, "proof": proof,
                                "same_compatibility_fingerprint": same_compat,
                                "same_semantic_fingerprint": same_semantic,
                                "semantic_equal_expected": s.seed == 0}
        if not proof["proof_ok"] or not same_compat or same_semantic != (s.seed == 0):
            problems.append(f"{s.name} vs canonical: {proof['unexpected']} compat {same_compat} semantic {same_semantic}")
    across_seeds: Dict[str, Any] = {}
    for r in REWARDS:
        for i, sa in enumerate(SEEDS):
            for sb in SEEDS[i + 1:]:
                a, b = exps[f"m7d_s{sa}_{r}"], exps[f"m7d_s{sb}_{r}"]
                d = field_diff(a.resolved_json(), b.resolved_json())
                proof = classify(d, SEED_ALLOWED)
                across_seeds[f"{r}:s{sa}_vs_s{sb}"] = {"resolved_diff": d, "proof": proof,
                                                       "same_compatibility_fingerprint":
                                                       a.compatibility_fingerprint == b.compatibility_fingerprint}
                if not proof["proof_ok"] or not across_seeds[f"{r}:s{sa}_vs_s{sb}"]["same_compatibility_fingerprint"]:
                    problems.append(f"{r} seeds {sa}/{sb}: {proof['unexpected']}")
    if with_trainer_view:
        per_seed_digest = {seed: runs[f"m7d_s{seed}_v1"]["expected_initial_policy_digest"] for seed in SEEDS}
        if len(set(per_seed_digest.values())) != len(SEEDS):
            problems.append(f"two seeds produce the same untrained policy: {per_seed_digest}")
    directory_plan = check_directory_plan(require_absent=False)
    problems.extend(directory_plan["problems"])
    exe = exps[specs[0].name].executable_fingerprint()
    manifest = {
        "schema": MATRIX_SCHEMA,
        "milestone": MILESTONE,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "purpose": "controlled paired comparison of btt_reward_v1 and btt_reward_v2 by gameplay outcome",
        "seeds": {"values": list(SEEDS), "canonical_seed": 0,
                  "selection": "the canonical profiles' base_seed (0) and the two adjacent valid seeds (base_seed >= 0)",
                  "scope": "Python / NumPy / PyTorch / SB3 only; never reaches the game",
                  "derived": "SB3/PPO seed = base_seed (network initialisation, action sampling, minibatch order); "
                             "worker and vector-reset seeds = base_seed + rank (0-4, 1-5, 2-6 overlap across base "
                             "seeds, but they only seed worker-side Python/NumPy/Gymnasium generators that never "
                             "influence actions or gameplay)"},
        "order": [{"index": s.order_index, "run": s.name, "seed": s.seed, "reward": s.reward} for s in specs],
        "counterbalancing": "seed 0: v1 then v2; seed 1: v2 then v1; seed 2: v1 then v2 (v1 at positions 1, 4, 5; "
                            "v2 at 2, 3, 6); runs strictly sequential, never two PPO experiments at once",
        "executable": exe,
        "canonical_profiles": {r: {"path": ec.repo_relative(p), "source_sha256": canon[r].source.sha256,
                                   "semantic_fingerprint": canon[r].semantic_fingerprint,
                                   "compatibility_fingerprint": canon[r].compatibility_fingerprint}
                               for r, p in CANONICAL.items()},
        "runs": runs,
        "pairs": pairs,
        "vs_canonical": vs_canonical,
        "across_seeds": across_seeds,
        "trainer_config": trainer if with_trainer_view else None,
        "evaluation_protocol": {
            "where": "after training, in a separate process, on saved checkpoint sets (no in-process evaluation: it "
                     "would keep the training games alive, up to 20 BattleShip processes, and reseed the trainer's "
                     "global RNGs)",
            "initial_and_final": FINAL_EPISODES, "curve_interval": CURVE_INTERVAL,
            "curve_episodes": {"deterministic": 2, "stochastic": 20},
            "seed": 12345, "workers": 5, "lifecycle": "standby (as in training), at most 10 game processes",
            "vecnormalize": "frozen: training=False, norm_reward=False, statistics of the evaluated checkpoint",
            "preservation": "every evaluation episode keeps its canonical native-action artifact (preserve_all)",
            "random_baseline": {"episodes": RANDOM_BASELINE_EPISODES, "seed": 12345, "workers": 5,
                                "cross_check": ec.repo_relative(M7A_RANDOM_BASELINE)},
            "plan": plans,
        },
        "decision_rule": DECISION_RULE,
        "directory_plan": directory_plan,
        "limits": {"max_game_processes": MAX_GAME_PROCESSES, "reward_normalization": False},
        "problems": problems,
        "ok": not problems,
    }
    return manifest


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fp:
        json.dump(data, fp, indent=2, sort_keys=False, default=str)
        fp.write("\n")
    os.replace(tmp, path)


def read_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)
